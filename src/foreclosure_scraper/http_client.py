"""Shared async HTTP client with sane retries."""
from __future__ import annotations

import asyncio
import os
from contextlib import asynccontextmanager
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

DEFAULT_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_5) "
        "AppleWebKit/605.1.15 (KHTML, like Gecko) "
        "Version/17.5 Safari/605.1.15"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
    "Accept-Encoding": "gzip, deflate, br",
    "Cache-Control": "no-cache",
    "Connection": "keep-alive",
}


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
    transport = httpx.AsyncHTTPTransport(retries=2)
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
    async with client(timeout=timeout) as c:
        r = await c.get(url)
        r.raise_for_status()
        return r.content


async def gather_with_concurrency(n: int, *aws):
    sem = asyncio.Semaphore(n)

    async def sem_task(aw):
        async with sem:
            return await aw

    return await asyncio.gather(*(sem_task(aw) for aw in aws), return_exceptions=True)
