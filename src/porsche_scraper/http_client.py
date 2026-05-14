"""HTTP fetching helpers.

Three transports — all free, no API keys required:

- `fetch_text` — plain httpx (HTTP/2, gzip). For friendly sites (cars.com,
  eBay HTML, AutoTempest, GovDeals static HTML).

- `fetch_text_stealth` — curl-cffi browser-impersonation (TLS+JA3).
  Use for sites that fingerprint at the TLS layer (BringATrailer,
  CarsAndBids, AutoTrader, CarsForSale, salvage brokers). When the TLS
  layer isn't enough, opt into Scrapling fallback via
  `fallback_to_render=True`.

- `fetch_rendered` — Scrapling StealthyFetcher. Runs a real Chromium
  under the hood (via Patchright). Auto-solves Cloudflare/AWS-WAF.
  Use for SPAs that need a real browser (GovDeals, PublicSurplus,
  GSA Auctions, Hagerty, CollectingCars, Mecum, Hemmings, etc.).

Both stealth layers are free; only PROXY_URL is needed if you want to
route traffic through a residential proxy.

Env vars:
- PROXY_URL — optional http(s) or SOCKS5 proxy
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
    scroll_iterations: int = 1,
    post_scroll_wait_ms: int = 1500,
) -> str:
    """Scrapling StealthyFetcher — runs a real Chromium under the hood.

    `scroll_iterations` repeats scroll-to-bottom + wait that many times
    so lazy-loaded result grids (e.g. Copart's virtualized list of 91
    lots per Porsche-911 search) fully render before we read the HTML.
    """
    from scrapling.fetchers import StealthyFetcher  # type: ignore

    page_action = None
    if wait_for_selector:
        async def page_action(page):  # type: ignore[no-redef]
            try:
                await page.wait_for_selector(wait_for_selector, timeout=15000)
            except Exception:
                pass
            try:
                for _ in range(max(1, scroll_iterations)):
                    await page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
                    await page.wait_for_timeout(post_scroll_wait_ms)
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


async def fetch_browser_api(
    warmup_url: str,
    api_path: str,
    body: dict,
    *,
    timeout: float = 60.0,
    wait_for_selector: str | None = None,
) -> dict | None:
    """Make a JSON API POST from inside a Scrapling-rendered page.

    Some sites (Copart, Tyler) gate their JSON APIs behind cookies +
    headers that only a real browser session has. We load `warmup_url`
    in Scrapling, then `page.evaluate()` a fetch() against `api_path`
    using the page's own credentials. The response is parsed as JSON
    and returned directly — no HTML scraping, no lazy-load races.

    Returns the parsed JSON dict, or None on any failure.
    """
    import json as _json
    from scrapling.fetchers import StealthyFetcher  # type: ignore

    body_json = _json.dumps(body)

    async def page_action(page):
        try:
            if wait_for_selector:
                try:
                    await page.wait_for_selector(wait_for_selector, timeout=10000)
                except Exception:
                    pass
            # Make the API call inside the page so it carries the
            # session's cookies + Origin header. Stash the JSON result
            # in a <pre id="__api__"> element so it survives into the
            # HTML body that StealthyFetcher returns.
            await page.evaluate(
                """async ({path, body}) => {
                    try {
                        const r = await fetch(path, {
                            method: 'POST', credentials: 'same-origin',
                            headers: {'Content-Type': 'application/json',
                                      'Accept': 'application/json'},
                            body: body,
                        });
                        const txt = await r.text();
                        const el = document.createElement('pre');
                        el.id = '__api__';
                        el.textContent = txt;
                        document.body.appendChild(el);
                    } catch (e) {
                        const el = document.createElement('pre');
                        el.id = '__api__';
                        el.textContent = JSON.stringify({_error: String(e)});
                        document.body.appendChild(el);
                    }
                }""",
                {"path": api_path, "body": body_json},
            )
            # Give the response time to fully serialize into DOM.
            await page.wait_for_timeout(500)
        except Exception:
            pass

    try:
        result = await StealthyFetcher.async_fetch(
            warmup_url,
            headless=True,
            network_idle=True,
            timeout=int(timeout * 1000),
            page_action=page_action,
            solve_cloudflare=True,
            google_search=True,
            wait=2000,
            retries=1,
        )
    except Exception as exc:  # noqa: BLE001
        log.warning("fetch_browser_api failed for %s: %s", warmup_url, exc)
        return None
    raw = getattr(result, "body", b"") if result else b""
    if isinstance(raw, bytes):
        html = raw.decode("utf-8", errors="replace")
    else:
        html = str(raw or "")
    # Extract the <pre id="__api__"> contents.
    import re as _re
    m = _re.search(r'<pre[^>]*id="__api__"[^>]*>(.*?)</pre>', html, _re.DOTALL)
    if not m:
        log.info("fetch_browser_api: no __api__ element in returned HTML (len=%d)", len(html))
        return None
    txt = m.group(1)
    # Unescape any HTML entities the renderer inserted.
    txt = txt.replace("&quot;", '"').replace("&amp;", "&").replace("&lt;", "<").replace("&gt;", ">")
    try:
        return _json.loads(txt)
    except Exception as exc:  # noqa: BLE001
        log.warning("fetch_browser_api: JSON parse failed: %s; head=%s", exc, txt[:200])
        return None


async def fetch_text_stealth(
    url: str,
    *,
    timeout: float = 45.0,
    headers: dict | None = None,
    impersonate: str = "chrome120",
    fallback_to_render: bool = False,
) -> str:
    """Stealth fetch via curl-cffi TLS browser-impersonation.

    Defaults to curl-cffi only. Sites that get blocked at the TLS layer
    can opt into a Scrapling browser-render fallback by passing
    `fallback_to_render=True`. Falling back is expensive (~10-30s per
    URL), so leave it off for sites where curl-cffi normally succeeds.
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
        log.info("curl-cffi failed for %s: %s", url, curl_exc)

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

    raise RuntimeError(f"stealth fetch failed for {url}")


async def fetch_rendered(
    url: str,
    *,
    timeout: float = 90.0,
    wait_for_selector: str | None = None,
    solve_cloudflare: bool = True,
    scroll_iterations: int = 1,
    post_scroll_wait_ms: int = 1500,
) -> str:
    """Force a JS-rendered fetch via Scrapling StealthyFetcher.

    Use this for SPAs where curl-cffi returns only an empty shell
    (GovDeals, PublicSurplus, GSA, Hagerty, Mecum, etc.). Free —
    Scrapling drives a local headless Chromium via Patchright.
    Requires `patchright install chromium` once per environment.
    """
    try:
        html = await _scrapling_fetch(
            url,
            timeout=timeout,
            wait_for_selector=wait_for_selector,
            solve_cloudflare=solve_cloudflare,
            scroll_iterations=scroll_iterations,
            post_scroll_wait_ms=post_scroll_wait_ms,
        )
        if html and len(html) > 500:
            return html
    except ImportError:
        log.info("scrapling not installed")
    except Exception as exc:  # noqa: BLE001
        log.info("scrapling render failed for %s: %s", url, exc)
    raise RuntimeError(f"render failed for {url}")
