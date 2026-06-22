"""Shared async HTTP client: sane retries + PER-HOST rate limiting + UA rotation.

Politeness is enforced at the TRANSPORT layer, so every request that goes through
`client()` (scrapers, enrichments, get_text/get_bytes) is automatically spaced
per hostname — different hosts stay parallel, same-host bursts get throttled.
This is the structural fix for IP-ban risk: nothing hammers a single host.
"""
from __future__ import annotations

import asyncio
import os
import random
import time
from contextlib import asynccontextmanager
from contextvars import ContextVar
from typing import AsyncIterator

import httpx
import structlog
from tenacity import (
    AsyncRetrying,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential_jitter,
)

log = structlog.get_logger()

# A small pool of REAL current desktop browser UAs. One is chosen per process
# (so a run looks like a single consistent browser) and varies run-to-run, so a
# fingerprinting service can't pin one static UA to our IP over time.
_UA_POOL = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_5) AppleWebKit/605.1.15 "
    "(KHTML, like Gecko) Version/17.5 Safari/605.1.15",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:127.0) Gecko/20100101 Firefox/127.0",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36 Edg/125.0.0.0",
)
_SESSION_UA = random.choice(_UA_POOL)

DEFAULT_HEADERS = {
    "User-Agent": _SESSION_UA,
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
    # Drop brotli — httpx doesn't decode it without the brotli package, and many
    # sites (Brock & Scott / Aldridge / Sucuri-protected) serve br by default
    "Accept-Encoding": "gzip, deflate",
    "Cache-Control": "no-cache",
    "Connection": "keep-alive",
}

# --- per-host rate limiter --------------------------------------------------
# Minimum spacing between request STARTS to the same host, plus random jitter so
# the cadence isn't a tell-tale fixed interval. Tunable via env for a slow,
# extra-polite run.
_MIN_INTERVAL_S = float(os.environ.get("HTTP_MIN_INTERVAL_S", "0.8"))
_JITTER_S = float(os.environ.get("HTTP_JITTER_S", "0.7"))
_host_last: dict[str, float] = {}
_host_locks: dict[tuple[int, str], asyncio.Lock] = {}


def _host_lock(host: str) -> asyncio.Lock:
    # Key by running loop so a lock is never reused across event loops (tests).
    key = (id(asyncio.get_running_loop()), host)
    lk = _host_locks.get(key)
    if lk is None:
        lk = _host_locks[key] = asyncio.Lock()
    return lk


async def _throttle(host: str | None) -> None:
    if not host:
        return
    async with _host_lock(host):
        wait = (_MIN_INTERVAL_S + random.uniform(0, _JITTER_S)) - (
            time.monotonic() - _host_last.get(host, 0.0)
        )
        if wait > 0:
            await asyncio.sleep(wait)
        _host_last[host] = time.monotonic()


# Per-run record of block-status HTTP responses, so a scraper that SWALLOWS its
# own httpx error (returns [] / "") is still classified as BLOCKED by
# base_scraper.safe_run instead of looking like a legit empty result.
#
# The holder is a MUTABLE LIST stored in a ContextVar. safe_run sets a fresh list
# per run; the transport APPENDS to it (never .set()). This is deliberate: a
# child asyncio task (asyncio.gather/create_task — how many scrapers fetch)
# inherits the SAME list object by reference when its context is copied, so an
# append inside the child is visible to safe_run in the parent. A plain
# ContextVar.set() inside a child would NOT propagate back — that was the bug.
# Concurrent scrapers each get their own list (set per safe_run task), so they
# don't clobber each other.
_block_holder: "ContextVar[list | None]" = ContextVar("_block_holder", default=None)
_BLOCK_CODES = {401, 403, 406, 409, 429}


def reset_block_signal() -> None:
    _block_holder.set([])


def take_block_signal() -> "tuple[int, str] | None":
    h = _block_holder.get()
    return h[0] if h else None   # first block recorded this run


class _ThrottledTransport(httpx.AsyncBaseTransport):
    """Wraps the real transport and spaces requests per hostname."""

    def __init__(self, inner: httpx.AsyncBaseTransport):
        self._inner = inner

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        await _throttle(request.url.host)
        resp = await self._inner.handle_async_request(request)
        code = resp.status_code
        if code in _BLOCK_CODES or 500 <= code < 600:
            holder = _block_holder.get()
            if holder is not None:   # mutate the shared list (survives child tasks)
                reason = ("rate-limited" if code == 429
                          else "blocked/forbidden" if code in (401, 403, 406, 409)
                          else "server error / possible WAF")
                holder.append((code, f"HTTP {code} ({reason}) from {request.url.host}"))
        return resp

    async def aclose(self) -> None:
        await self._inner.aclose()


@asynccontextmanager
async def client(
    *,
    timeout: float = 30.0,
    follow_redirects: bool = True,
    headers: dict | None = None,
    impersonate_browser: bool = True,
) -> AsyncIterator[httpx.AsyncClient]:
    h = dict(DEFAULT_HEADERS)
    if headers:
        h.update(headers)
    proxy = os.environ.get("PROXY_URL") or None
    transport = _ThrottledTransport(httpx.AsyncHTTPTransport(retries=2))
    async with httpx.AsyncClient(
        timeout=timeout,
        follow_redirects=follow_redirects,
        headers=h,
        proxy=proxy,
        transport=transport,
        http2=True,
    ) as cli:
        yield cli


async def get_text(
    url: str,
    *,
    timeout: float = 30.0,
    headers: dict | None = None,
    referer: str | None = None,
) -> str:
    """GET a URL and return text, with retry on transient errors."""
    h = dict(headers or {})
    if referer:
        h["Referer"] = referer
    async for attempt in AsyncRetrying(
        stop=stop_after_attempt(3),
        wait=wait_exponential_jitter(initial=1, max=10),
        retry=retry_if_exception_type(
            (httpx.TransportError, httpx.HTTPStatusError, httpx.TimeoutException)
        ),
        reraise=True,
    ):
        with attempt:
            async with client(timeout=timeout) as c:
                r = await c.get(url, headers=h)
                if r.status_code in (429, 500, 502, 503, 504):
                    raise httpx.HTTPStatusError(
                        f"transient {r.status_code}", request=r.request, response=r
                    )
                r.raise_for_status()
                return r.text
    raise RuntimeError("unreachable")


async def get_bytes(url: str, *, timeout: float = 60.0) -> bytes:
    """GET raw bytes (images/PDFs), with the same transient-error retry as text."""
    async for attempt in AsyncRetrying(
        stop=stop_after_attempt(3),
        wait=wait_exponential_jitter(initial=1, max=10),
        retry=retry_if_exception_type(
            (httpx.TransportError, httpx.HTTPStatusError, httpx.TimeoutException)
        ),
        reraise=True,
    ):
        with attempt:
            async with client(timeout=timeout) as c:
                r = await c.get(url)
                if r.status_code in (429, 500, 502, 503, 504):
                    raise httpx.HTTPStatusError(
                        f"transient {r.status_code}", request=r.request, response=r
                    )
                r.raise_for_status()
                return r.content
    raise RuntimeError("unreachable")


async def gather_with_concurrency(n: int, *aws):
    sem = asyncio.Semaphore(n)

    async def sem_task(aw):
        async with sem:
            return await aw

    return await asyncio.gather(*(sem_task(aw) for aw in aws), return_exceptions=True)
