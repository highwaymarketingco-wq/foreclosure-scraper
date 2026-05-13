"""HTTP fetching helpers.

Two transports are exposed:
- `fetch_text` uses plain httpx (HTTP/2, gzip) for simple sites (cars.com,
  eBay, AutoTempest).
- `fetch_text_stealth` uses curl-cffi when available to impersonate a real
  browser TLS fingerprint (BringATrailer, CarsAndBids, AutoTrader,
  CarsForSale). Falls back to httpx if curl_cffi isn't installed.

A user can supply PROXY_URL via env to route requests through a residential
proxy. This is required at scale for the bot-protected sites.
"""
from __future__ import annotations

import asyncio
import logging
import os
import random
from contextlib import asynccontextmanager
from typing import AsyncIterator

import httpx
from tenacity import (
    AsyncRetrying,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential_jitter,
)

log = logging.getLogger("porsche_scraper.http")


_DESKTOP_UAS = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_5) AppleWebKit/605.1.15 "
    "(KHTML, like Gecko) Version/17.5 Safari/605.1.15",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
)


def _base_headers(extra: dict | None = None) -> dict:
    h = {
        "User-Agent": random.choice(_DESKTOP_UAS),
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,"
        "image/avif,image/webp,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
        "Accept-Encoding": "gzip, deflate",
        "Cache-Control": "no-cache",
        "Connection": "keep-alive",
    }
    if extra:
        h.update(extra)
    return h


@asynccontextmanager
async def client(
    *,
    timeout: float = 30.0,
    follow_redirects: bool = True,
    headers: dict | None = None,
) -> AsyncIterator[httpx.AsyncClient]:
    proxy = os.environ.get("PROXY_URL") or None
    async with httpx.AsyncClient(
        timeout=timeout,
        follow_redirects=follow_redirects,
        headers=_base_headers(headers),
        proxy=proxy,
        http2=True,
    ) as cli:
        yield cli


async def fetch_text(
    url: str,
    *,
    timeout: float = 30.0,
    headers: dict | None = None,
    referer: str | None = None,
) -> str:
    h = dict(headers or {})
    if referer:
        h["Referer"] = referer
    async for attempt in AsyncRetrying(
        stop=stop_after_attempt(3),
        wait=wait_exponential_jitter(initial=1, max=8),
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


async def fetch_json(
    url: str,
    *,
    method: str = "GET",
    json_body: dict | None = None,
    headers: dict | None = None,
    timeout: float = 30.0,
) -> dict:
    h = dict(headers or {})
    h.setdefault("Accept", "application/json")
    async with client(timeout=timeout, headers=h) as c:
        if method.upper() == "POST":
            r = await c.post(url, json=json_body)
        else:
            r = await c.get(url)
        r.raise_for_status()
        return r.json()


async def fetch_text_stealth(
    url: str,
    *,
    timeout: float = 45.0,
    headers: dict | None = None,
    impersonate: str = "chrome120",
) -> str:
    """Fetch via curl-cffi browser-impersonation (TLS+JA3). Falls back to httpx."""
    try:
        from curl_cffi.requests import AsyncSession  # type: ignore
    except ImportError:
        log.warning("curl_cffi unavailable; falling back to httpx for %s", url)
        return await fetch_text(url, timeout=timeout, headers=headers)

    proxy = os.environ.get("PROXY_URL") or None
    h = _base_headers(headers)
    last_exc: Exception | None = None
    for attempt in range(3):
        try:
            async with AsyncSession(
                impersonate=impersonate,
                timeout=timeout,
                proxies={"https": proxy, "http": proxy} if proxy else None,
            ) as s:
                r = await s.get(url, headers=h)
                if r.status_code in (429, 500, 502, 503, 504):
                    raise RuntimeError(f"transient {r.status_code}")
                if r.status_code >= 400:
                    raise RuntimeError(f"{r.status_code} for {url}")
                return r.text
        except Exception as exc:  # noqa: BLE001
            last_exc = exc
            await asyncio.sleep(1.5 * (attempt + 1))
    raise last_exc or RuntimeError("stealth fetch failed")
