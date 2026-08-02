"""Shared async HTTP client: sane retries + PER-HOST rate limiting + UA rotation.

Politeness is enforced at the TRANSPORT layer, so every request that goes through
`client()` (scrapers, enrichments, get_text/get_bytes) is automatically spaced
per hostname — different hosts stay parallel, same-host bursts get throttled.
This is the structural fix for IP-ban risk: nothing hammers a single host.

Fetch tiers, cheapest first — `get_text(impersonate=True)` (or
`get_text_impersonate`) walks them automatically:

1. plain httpx (HTTP/2, gzip) + rotated real-browser UA — for friendly hosts.
2. curl-cffi `AsyncSession(impersonate="chrome")` — a real Chrome JA3/TLS +
   HTTP/2 fingerprint with NO browser process. Many Cloudflare/F5-fronted
   gov + court hosts (e.g. publicindex.sccourts.org) 403/406 plain httpx purely
   on the TLS handshake and return 200 to a matching fingerprint. This is a
   fast (~1s) static-content tier that sits BELOW the StealthyFetcher render
   path: we only escalate to a headless browser when impersonation also fails.

Presenting a real-browser fingerprint is NOT a CAPTCHA/WAF defeat — no solver,
no login, no token forgery. Hosts that still block (e.g. portal-nc.tylertech,
403 on both tiers) need the dedicated WAF-token / render path elsewhere.
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


def clear_block_signal() -> None:
    """Forget blocks recorded so far — for a scraper that RECOVERED from one.

    Mutates the holder list in place rather than rebinding the ContextVar, so
    the change is visible to safe_run in the parent task (a `.set()` inside the
    child context would not propagate back). Call this only after a fetch tier
    actually succeeded: an unrecovered block must still surface as BLOCKED.
    """
    h = _block_holder.get()
    if h is not None:
        h.clear()


# Process-wide memory of hosts that returned a _BLOCK_CODES status to PLAIN httpx
# at least once. Once a host is known to fingerprint-block, get_text(impersonate=
# True) skips the doomed plain attempt and goes straight to the curl-cffi tier —
# saving a guaranteed-failing round-trip on every later fetch of that host.
_impersonate_hosts: set[str] = set()


def _host_of(url: str) -> str | None:
    try:
        return httpx.URL(url).host
    except Exception:  # noqa: BLE001
        return None


def mark_host_blocked(url: str) -> None:
    """Record that `url`'s host blocked plain httpx (so future fetches impersonate first)."""
    host = _host_of(url)
    if host:
        _impersonate_hosts.add(host)


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
    http2: bool = True,
) -> AsyncIterator[httpx.AsyncClient]:
    """Shared throttled client. Pass ``http2=False`` for the rare host whose CDN
    answers an ordinary HTTP/1.1 request but not httpx's HTTP/2 one (see
    law_firms.mewborn_deselms) — everything else keeps HTTP/2."""
    h = dict(DEFAULT_HEADERS)
    if headers:
        h.update(headers)
    proxy = os.environ.get("PROXY_URL") or None
    # HARD-timeout hardening (flaky-connection safe). Bound CONNECT and POOL-acquire
    # tightly: a wedged connect or an exhausted pool are the flaky-network stalls that
    # otherwise freeze a whole per-lead enrichment batch (a float timeout leaves them
    # loose, and the async budget-bail can't cancel a socket stuck below the loop).
    # retries=0 removes the transport's connect-retry amplification — callers already
    # wrap their own AsyncRetrying. All env-tunable.
    _conn_to = float(os.environ.get("HTTP_CONNECT_TIMEOUT", "8.0"))
    _pool_to = float(os.environ.get("HTTP_POOL_TIMEOUT", "8.0"))
    transport = _ThrottledTransport(httpx.AsyncHTTPTransport(retries=0))
    async with httpx.AsyncClient(
        timeout=httpx.Timeout(timeout, connect=_conn_to, pool=_pool_to),
        follow_redirects=follow_redirects,
        headers=h,
        proxy=proxy,
        transport=transport,
        http2=http2,
    ) as cli:
        yield cli


async def _impersonate_fetch(
    url: str,
    *,
    timeout: float,
    headers: dict | None,
    referer: str | None,
    impersonate: str,
) -> str:
    """Fetch via curl-cffi with a real Chrome JA3/TLS + HTTP/2 fingerprint.

    No browser process — this is a fast static-content tier for hosts that
    fingerprint-block plain httpx at the TLS handshake (403/406) but answer a
    matching Chrome fingerprint. curl-cffi is sync per-request under the hood but
    its AsyncSession runs on an internal curl multi loop, so it stays async.

    Honours the same per-host throttle and per-run block signal as the httpx
    transport, so politeness + BLOCKED classification are unchanged. Raises on
    block/transient codes so the retry/escalation logic above can react.
    """
    from curl_cffi.requests import AsyncSession  # local import: keep dep optional

    h = dict(DEFAULT_HEADERS)
    if headers:
        h.update(headers)
    if referer:
        h["Referer"] = referer
    proxy = os.environ.get("PROXY_URL") or None
    proxies = {"http": proxy, "https": proxy} if proxy else None

    await _throttle(_host_of(url))
    async with AsyncSession() as s:
        r = await s.get(
            url,
            headers=h,
            impersonate=impersonate,
            timeout=timeout,
            proxies=proxies,
            allow_redirects=True,
        )
        # Some hosts (e.g. overpass-api.de) reject the browser-like Accept header
        # impersonation sends with a 406, yet answer fine with a permissive Accept.
        # Retry once with Accept: */* before treating it as a block/escalating.
        if r.status_code == 406:
            h2 = dict(h)
            h2["Accept"] = "*/*"
            r = await s.get(
                url, headers=h2, impersonate=impersonate, timeout=timeout,
                proxies=proxies, allow_redirects=True,
            )
    code = r.status_code
    if code in _BLOCK_CODES or 500 <= code < 600:
        holder = _block_holder.get()
        if holder is not None:
            reason = ("rate-limited" if code == 429
                      else "blocked/forbidden" if code in (401, 403, 406, 409)
                      else "server error / possible WAF")
            holder.append((code, f"HTTP {code} ({reason}) from {_host_of(url)} [impersonate]"))
        raise RuntimeError(f"impersonate got {code} for {url}")
    if code >= 400:
        raise RuntimeError(f"impersonate got {code} for {url}")
    return r.text


async def get_text_impersonate(
    url: str,
    *,
    timeout: float = 30.0,
    headers: dict | None = None,
    referer: str | None = None,
    impersonate: str = "chrome",
) -> str:
    """GET via the curl-cffi browser-impersonation tier only, with retry.

    Use directly when a host is known to need a real TLS fingerprint. For the
    automatic plain->impersonate escalation, prefer `get_text(..., impersonate=True)`.
    """
    async for attempt in AsyncRetrying(
        stop=stop_after_attempt(3),
        wait=wait_exponential_jitter(initial=1, max=10),
        reraise=True,
    ):
        with attempt:
            return await _impersonate_fetch(
                url, timeout=timeout, headers=headers,
                referer=referer, impersonate=impersonate,
            )
    raise RuntimeError("unreachable")


async def get_text(
    url: str,
    *,
    timeout: float = 30.0,
    headers: dict | None = None,
    referer: str | None = None,
    impersonate: bool = False,
) -> str:
    """GET a URL and return text, with retry on transient errors.

    With `impersonate=True`, plain httpx is tried first; if the host returns a
    block status (401/403/406/409/429) or any HTTPStatusError, we transparently
    escalate to the curl-cffi Chrome-fingerprint tier (a fast static fallback
    BEFORE any browser render). Hosts seen blocking plain httpx are remembered
    process-wide so later fetches impersonate first and skip the doomed attempt.
    """
    h = dict(headers or {})
    if referer:
        h["Referer"] = referer

    host = _host_of(url)
    impersonate_first = impersonate and host is not None and host in _impersonate_hosts
    if impersonate_first:
        return await get_text_impersonate(
            url, timeout=timeout, headers=headers, referer=referer
        )

    try:
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
    except httpx.HTTPStatusError as exc:
        code = exc.response.status_code if exc.response is not None else None
        # Only the impersonation tier can plausibly fix a fingerprint block; a
        # generic 404/410 won't change, so don't waste a fetch on those.
        if not (impersonate and (code in _BLOCK_CODES)):
            raise
        log.info("get_text.escalate_impersonate", host=host, code=code)
        if host:
            _impersonate_hosts.add(host)
        return await get_text_impersonate(
            url, timeout=timeout, headers=headers, referer=referer
        )


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
