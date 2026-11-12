"""Free JS-rendering fetcher — replaces the old Apify rag-web-browser path.

Uses Scrapling's StealthyFetcher (camoufox-based real browser) to render
JavaScript pages and bypass anti-bot defenses (PerimeterX, Cloudflare,
AWS WAF). Zero cost. Runs a real local browser, so it works reliably on
a developer Mac; on headless cloud CI it is more easily fingerprinted —
this is by design, the scraper is meant to run locally.

Public API matches the old apify_helper.fetch_rendered so call sites need
only swap the import:

    from .render import fetch_rendered          # was: from .apify_helper import fetch_rendered
    text = await fetch_rendered(url)            # returns rendered text, or "" on failure

The returned value is the rendered page's visible text. Every current
consumer regexes over it (case numbers, court fields), so text vs HTML
doesn't matter; we return text to keep payloads small.
"""
from __future__ import annotations

import asyncio
import os
from typing import Optional

import structlog

log = structlog.get_logger()


class RenderHTTPFailure(Exception):
    """Raised by fetch_rendered ONLY when raise_on_http_failure=True and the
    render failed with an HTTP-level error (bad status >=400, or the camoufox
    ERR_HTTP_RESPONSE_CODE_FAILURE). Lets a breaker-protected caller (the SC
    court lookup) distinguish a real HTTP failure from a legit empty-page miss,
    which it counts toward its consecutive-failure circuit breaker. Off by
    default so every other caller keeps the old ""-on-failure contract."""


# Marker strings camoufox/playwright emit in the exception text when the
# server returns a non-2xx the browser refuses to render.
_HTTP_FAILURE_MARKERS = ("ERR_HTTP_RESPONSE_CODE_FAILURE", "ERR_ABORTED")


# Tunables (env-overridable so a slow run can be adjusted without code change).
RENDER_TIMEOUT_MS = int(os.environ.get("RENDER_TIMEOUT_MS", "45000"))
RENDER_HEADLESS = os.environ.get("RENDER_HEADLESS", "1") != "0"
RENDER_CONCURRENCY = int(os.environ.get("RENDER_CONCURRENCY", "2"))

# One global semaphore — real browsers are heavy; don't launch a swarm.
_sem: Optional[asyncio.Semaphore] = None


def _semaphore() -> asyncio.Semaphore:
    global _sem
    if _sem is None:
        _sem = asyncio.Semaphore(RENDER_CONCURRENCY)
    return _sem


def _render_sync(url: str, *, timeout_ms: int, headless: bool,
                 raise_on_http_failure: bool = False) -> str:
    """Blocking render in a worker thread. Returns visible text or "".

    When raise_on_http_failure is set, an HTTP-level failure (bad status >=400
    or a camoufox ERR_HTTP_RESPONSE_CODE_FAILURE) raises RenderHTTPFailure
    instead of silently returning "" — so a breaker-protected caller can count
    it as a failure rather than a benign empty miss."""
    try:
        from scrapling.fetchers import StealthyFetcher
    except ImportError:
        log.warning("render.scrapling_missing")
        return ""
    try:
        page = StealthyFetcher.fetch(url, headless=headless, timeout=timeout_ms)
    except Exception as exc:  # network, browser launch, timeout, etc.
        log.debug("render.fetch_error", url=url[:120], error=str(exc)[:150])
        if raise_on_http_failure and any(m in str(exc) for m in _HTTP_FAILURE_MARKERS):
            raise RenderHTTPFailure(str(exc)[:150]) from exc
        return ""
    status = getattr(page, "status", None)
    if status and status >= 400:
        log.debug("render.bad_status", url=url[:120], status=status)
        if raise_on_http_failure:
            raise RenderHTTPFailure(f"status={status}")
        return ""
    # Prefer visible text; fall back to raw HTML if text extraction is empty.
    try:
        text = page.get_all_text(ignore_tags=("script", "style"))
    except Exception:
        text = ""
    if not text:
        text = getattr(page, "html_content", "") or ""
    return text


async def fetch_rendered(url: str, *, token: str | None = None,
                         raise_on_http_failure: bool = False) -> str:
    """Render a JS page with a real stealth browser. Returns text, or "".

    `token` is accepted and ignored for drop-in compatibility with the old
    Apify-based signature.

    `raise_on_http_failure` (opt-in, default off) makes an HTTP-level failure
    raise RenderHTTPFailure instead of returning "". Only the breaker-protected
    SC court lookup sets it; every other caller keeps the ""-on-failure contract.
    """
    async with _semaphore():
        return await asyncio.to_thread(
            _render_sync, url, timeout_ms=RENDER_TIMEOUT_MS,
            headless=RENDER_HEADLESS, raise_on_http_failure=raise_on_http_failure,
        )


async def fetch_rendered_many(
    urls: list[str], *, token: str | None = None, concurrency: int | None = None
) -> dict[str, str]:
    """Render many URLs. Concurrency is bounded by the global render semaphore
    regardless of the `concurrency` arg (kept for signature compatibility)."""
    out: dict[str, str] = {}

    async def one(u: str) -> None:
        out[u] = await fetch_rendered(u)

    await asyncio.gather(*(one(u) for u in urls))
    return out
