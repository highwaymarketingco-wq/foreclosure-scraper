"""HTTP fetching helpers.

Three transports are exposed:

- `fetch_text` — plain httpx (HTTP/2, gzip). For friendly sites (cars.com,
  eBay HTML, AutoTempest, GovDeals static HTML).

- `fetch_text_stealth` — layered fallback:
    1. curl-cffi browser-impersonation (TLS+JA3)
    2. Scrapling StealthyFetcher (Cloudflare/AWS-WAF auto-solve + JS render)
    3. Apify rag-web-browser actor (paid; only if APIFY_TOKEN set)
  Use for sites with TLS-fingerprint or light Cloudflare challenges
  (BringATrailer, CarsAndBids, AutoTrader, CarsForSale, salvage brokers).

- `fetch_rendered` — goes straight to Scrapling StealthyFetcher
  (skips curl-cffi which can't render JS). Use for SPAs that need a
  real browser to render results (GovDeals, PublicSurplus, GSA Auctions,
  Hagerty, CollectingCars, Mecum, Hemmings, etc.).

A user can supply PROXY_URL via env to route requests through a residential
proxy. For heavy bot-protected sites this is still recommended even with
Scrapling.

Env vars:
- PROXY_URL          — http(s) or SOCKS5 proxy
- APIFY_TOKEN        — enables Apify rendering fallback
- CAPSOLVER_API_KEY  — enables AWS WAF token solving (rare; opt-in per call)
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


async def _curl_cffi_fetch(
    url: str, *, timeout: float, headers: dict | None, impersonate: str
) -> str:
    """curl-cffi browser-impersonation (TLS+JA3). Raises on failure."""
    from curl_cffi.requests import AsyncSession  # type: ignore

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
    raise last_exc or RuntimeError("curl-cffi fetch failed")


async def _scrapling_fetch(
    url: str,
    *,
    timeout: float,
    wait_for_selector: str | None,
    solve_cloudflare: bool,
) -> str:
    """Scrapling StealthyFetcher — runs a real Chromium under the hood."""
    from scrapling.fetchers import StealthyFetcher  # type: ignore

    page_action = None
    if wait_for_selector:
        async def page_action(page):  # type: ignore[no-redef]
            try:
                await page.wait_for_selector(wait_for_selector, timeout=15000)
            except Exception:
                pass
            try:
                # Scroll to trigger any lazy-loaded cards.
                await page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
                await page.wait_for_timeout(1500)
            except Exception:
                pass

    result = await StealthyFetcher.async_fetch(
        url,
        headless=True,
        network_idle=True,
        timeout=int(timeout * 1000),
        page_action=page_action,
        solve_cloudflare=solve_cloudflare,
        google_search=True,
        wait=2000,
        retries=1,
    )
    body = getattr(result, "body", b"") if result else b""
    if isinstance(body, bytes):
        return body.decode("utf-8", errors="replace")
    return str(body or "")


async def _apify_render(url: str) -> str:
    """Apify rag-web-browser fallback. Only runs if APIFY_TOKEN is set.

    Reuses the foreclosure_scraper.apify_helper module since they're in
    the same repo and that helper already has cost gating + retries.
    """
    token = os.environ.get("APIFY_TOKEN")
    if not token:
        return ""
    try:
        from foreclosure_scraper.apify_helper import fetch_rendered  # type: ignore
    except ImportError:
        return ""
    try:
        return await fetch_rendered(url, token=token)
    except Exception as exc:  # noqa: BLE001
        log.warning("apify render failed for %s: %s", url, exc)
        return ""


async def fetch_text_stealth(
    url: str,
    *,
    timeout: float = 45.0,
    headers: dict | None = None,
    impersonate: str = "chrome120",
    fallback_to_render: bool = False,
) -> str:
    """Layered stealth fetch.

    Order: curl-cffi → (optional) Scrapling → (optional) Apify.

    Defaults to curl-cffi only. Sites that get blocked at the TLS layer
    should pass `fallback_to_render=True` or use `fetch_rendered`
    directly. Falling back to Scrapling is expensive (~10-30s per URL),
    so avoid it for sites where curl-cffi normally succeeds.
    """
    try:
        return await _curl_cffi_fetch(
            url, timeout=timeout, headers=headers, impersonate=impersonate
        )
    except ImportError:
        log.info("curl_cffi unavailable; trying plain httpx")
        try:
            return await fetch_text(url, timeout=timeout, headers=headers)
        except Exception:
            pass  # Fall through to render below.
    except Exception as curl_exc:
        log.info("curl-cffi failed for %s: %s — trying scrapling", url, curl_exc)

    if not fallback_to_render:
        raise RuntimeError(f"stealth fetch failed for {url}")

    try:
        rendered = await _scrapling_fetch(
            url, timeout=timeout * 2, wait_for_selector=None, solve_cloudflare=True
        )
        if rendered and len(rendered) > 500:
            return rendered
    except ImportError:
        log.info("scrapling not installed")
    except Exception as exc:  # noqa: BLE001
        log.info("scrapling failed for %s: %s", url, exc)

    apify_md = await _apify_render(url)
    if apify_md:
        return apify_md

    raise RuntimeError(f"all stealth layers failed for {url}")


async def fetch_rendered(
    url: str,
    *,
    timeout: float = 90.0,
    wait_for_selector: str | None = None,
    solve_cloudflare: bool = True,
) -> str:
    """Force a JS-rendered fetch via Scrapling StealthyFetcher.

    Use this for SPAs where curl-cffi returns only an empty shell
    (GovDeals, PublicSurplus, GSA, Hagerty, Mecum, etc.). Falls back to
    Apify if Scrapling is unavailable or fails.
    """
    try:
        html = await _scrapling_fetch(
            url,
            timeout=timeout,
            wait_for_selector=wait_for_selector,
            solve_cloudflare=solve_cloudflare,
        )
        if html and len(html) > 500:
            return html
    except ImportError:
        log.info("scrapling not installed; trying apify")
    except Exception as exc:  # noqa: BLE001
        log.info("scrapling render failed for %s: %s", url, exc)

    apify_md = await _apify_render(url)
    if apify_md:
        return apify_md
    raise RuntimeError(f"render layers failed for {url}")
