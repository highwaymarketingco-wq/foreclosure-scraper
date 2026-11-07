"""nc_rod_captcha.NcRodCaptchaScraper._goto_with_retry: a transient Playwright
transport/timeout failure on a page.goto() gets retried, not treated as "the
whole county/doc-type/related-doc failed."

Confirmed 2026-11-07 (overnight bug-fix sweep): this file's 7 page.goto() call
sites (fetch() x2, _fetch_durham x2, _fetch_wake x2, _fetch_wake_related x1)
were all bare -- no AsyncRetrying, no manual retry loop, no @retry decorator
anywhere in the file. Each one already sits inside a try/except that fails
soft (drops to the next county/doc-type/related-doc rather than crashing the
whole run), but a single transient blip (a connection reset, a timeout) still
permanently zeroed that one item's contribution for the run, and because this
scraper is registered in main.DATELESS_OK_SOURCES (no fallback date window),
a zeroed run could not self-heal later -- it would just silently report an
empty/healthy result until someone noticed by hand.

This is the SAME root cause already fixed tonight for this codebase's
httpx-based scrapers (arcgis_webmap.query_features(), the Column legal-notice
API scraper, spartan_weekly_legals.py) -- but this file is NOT httpx-based.
It is a Playwright browser-automation scraper: it never imports httpx,
requests, or the project's http_client wrapper, and its only real network
calls are Playwright page.goto() navigations. Playwright raises its OWN
exception types (playwright.async_api.Error / TimeoutError), not httpx's --
so the fix (`NcRodCaptchaScraper._goto_with_retry`) tunes
retry_if_exception_type to Playwright's own exception classes instead of
reusing the httpx-specific predicate verbatim, which would have been a silent
no-op (syntactically fine, but would never actually catch a Playwright
timeout/navigation error). Playwright's own goto() does not raise on a real
bad HTTP status -- only on an actual transport/timeout failure -- so a
genuine non-transport error (a real code bug) is exercised here too, and
must NOT be retried.
"""
from __future__ import annotations

import asyncio

import pytest
from playwright.async_api import Error as PlaywrightError, TimeoutError as PlaywrightTimeoutError
from tenacity import wait_exponential_jitter

from foreclosure_scraper.scrapers.counties_nc import nc_rod_captcha as nrc
from foreclosure_scraper.scrapers.counties_nc.nc_rod_captcha import NcRodCaptchaScraper

URL = "https://rod.example.test/web/search/IndexSearchRequired"


class _FakePage:
    """Minimal Playwright Page double -- only .goto() is exercised by
    _goto_with_retry, same minimal-surface style _FlakyHttp uses for
    query_features()'s injected http client in
    test_arcgis_webmap_query_features_retry.py. Raises on the first N calls,
    then "navigates" cleanly (returns None, same as a real successful
    page.goto())."""

    def __init__(self, fail_times: int, exc: BaseException | None = None):
        self.fail_times = fail_times
        self.exc = exc or PlaywrightError(f"net::ERR_CONNECTION_RESET at {URL}")
        self.calls = 0

    async def goto(self, url, timeout=None):
        self.calls += 1
        if self.calls <= self.fail_times:
            raise self.exc
        return None


@pytest.fixture(autouse=True)
def _fast_backoff(monkeypatch):
    monkeypatch.setattr(nrc, "wait_exponential_jitter",
                        lambda **kw: wait_exponential_jitter(initial=0.001, max=0.002))


def _scraper() -> NcRodCaptchaScraper:
    return NcRodCaptchaScraper()


def test_a_transient_connection_reset_is_retried_and_then_succeeds():
    page = _FakePage(fail_times=2)
    asyncio.run(_scraper()._goto_with_retry(page, URL, timeout=30000))
    assert page.calls == 3


def test_a_transient_error_that_never_clears_still_raises_not_hangs():
    page = _FakePage(fail_times=99)
    with pytest.raises(PlaywrightError):
        asyncio.run(_scraper()._goto_with_retry(page, URL, timeout=30000))
    assert page.calls == 3   # stop_after_attempt(3), then gives up -- no infinite hang


def test_a_playwright_timeout_error_is_also_retried():
    # Playwright's own TimeoutError (e.g. "Timeout 30000ms exceeded.") is a
    # distinct exception from its generic connection-level Error above --
    # both must be covered, since a slow/unresponsive ROD site times out
    # this way, not via a connection-reset-shaped Error.
    page = _FakePage(fail_times=1, exc=PlaywrightTimeoutError("Timeout 30000ms exceeded."))
    asyncio.run(_scraper()._goto_with_retry(page, URL, timeout=30000))
    assert page.calls == 2


def test_a_real_non_transport_error_is_not_retried():
    # A genuine application/code bug (never a network blip) must fail
    # immediately on attempt 1, exactly like a real bad HTTP status is never
    # retried in the httpx-based version of this fix. This is also the case
    # that proves the fix isn't a blind copy of the httpx-specific predicate:
    # httpx.TransportError/httpx.TimeoutException would never match this
    # RuntimeError either, but they would ALSO never match the PlaywrightError
    # raised by the two tests above -- only a predicate built from
    # playwright.async_api's own exception classes catches those.
    page = _FakePage(fail_times=1, exc=RuntimeError("programming bug, not a network blip"))
    with pytest.raises(RuntimeError):
        asyncio.run(_scraper()._goto_with_retry(page, URL, timeout=30000))
    assert page.calls == 1   # a real non-transport/timeout error is not retried
