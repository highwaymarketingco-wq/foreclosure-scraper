"""counties_nc.nc_rowan_cott: the one-shot Playwright calls that gate the
WHOLE guest-session + search-submission chain get retried on a transient
blip, not treated as "the whole run failed."

Found 2026-11-07 (gap-sweep): fetch()'s goto -> "Sign in as a Guest" click ->
"Date Range" tab click -> Index Type select -> Search click sequence is a
single unbroken chain of one-shot Playwright actions with zero retry
cushioning anywhere in it. A transient blip on any one of them propagates
out of fetch()'s own try block, is caught only by its blanket
``except Exception`` (nc_rowan_cott.error), and falls through to
``return results`` -- empty, since rows are only appended after the search
has already succeeded. Because this source is registered in
main.DATELESS_OK_SOURCES (no fallback date window), a zeroed run can't
self-heal later; it just reports an empty/healthy result until someone
notices by hand -- the same root cause already fixed for the Column
legal-notice API scraper, spartan_weekly_legals.py,
arcgis_webmap.query_features(), nc_rod_captcha.py, nc_ecourts_estates.py,
and sc_public_index.py.

Unlike the httpx-flavored callers among those, this file is driven entirely
by a Playwright `page` object (no httpx import anywhere in it) and raises
Playwright's own `Error` / `TimeoutError` -- not `httpx.TransportError` /
`httpx.TimeoutException` -- so the retry predicate in the three new helpers
(`_goto_with_retry`, `_click_with_retry`, `_select_option_with_retry`) names
Playwright's actual transient exception types. Each helper is exercised
directly against a minimal Playwright page/locator double (no real browser,
no network).
"""
from __future__ import annotations

import asyncio

import pytest
from playwright.async_api import Error as PlaywrightError, TimeoutError as PlaywrightTimeoutError
from tenacity import wait_exponential_jitter

from foreclosure_scraper.scrapers.counties_nc import nc_rowan_cott as nrc


@pytest.fixture(autouse=True)
def _fast_backoff(monkeypatch):
    monkeypatch.setattr(nrc, "wait_exponential_jitter",
                        lambda **kw: wait_exponential_jitter(initial=0.001, max=0.002))


# ---------------------------------------------------------------------------
# _goto_with_retry (fetch()'s page.goto(_URL) -- starts the whole chain)
# ---------------------------------------------------------------------------

class _FlakyGotoPage:
    """Playwright-page double: goto raises on the first `fail_times` calls,
    then succeeds (mirrors the page landing once the transient blip
    clears)."""

    def __init__(self, fail_times: int, exc=None):
        self.fail_times = fail_times
        self.exc = exc or PlaywrightTimeoutError("Timeout 30000ms exceeded.")
        self.calls = 0

    async def goto(self, url, timeout=None):
        self.calls += 1
        if self.calls <= self.fail_times:
            raise self.exc
        return None


def test_goto_with_retry_retries_a_transient_timeout_and_then_succeeds():
    page = _FlakyGotoPage(fail_times=2)
    asyncio.run(nrc._goto_with_retry(page, "https://rod.rowancountync.gov/external", timeout=30000))
    assert page.calls == 3


def test_goto_with_retry_timeout_that_never_clears_still_raises_not_hangs():
    page = _FlakyGotoPage(fail_times=99)
    with pytest.raises(PlaywrightTimeoutError):
        asyncio.run(nrc._goto_with_retry(page, "https://rod.rowancountync.gov/external", timeout=30000))
    assert page.calls == 3   # stop_after_attempt(3), then gives up


def test_goto_with_retry_a_non_playwright_error_is_not_retried():
    class _BadGotoPage:
        def __init__(self):
            self.calls = 0

        async def goto(self, url, timeout=None):
            self.calls += 1
            raise RuntimeError("dns resolver crashed")

    page = _BadGotoPage()
    with pytest.raises(RuntimeError):
        asyncio.run(nrc._goto_with_retry(page, "https://rod.rowancountync.gov/external", timeout=30000))
    assert page.calls == 1   # a non-Playwright error is not a transport/timeout error


# ---------------------------------------------------------------------------
# _click_with_retry (the three click sites: Guest sign-in, Date Range tab,
# Search -- each a link in the same unbroken chain)
# ---------------------------------------------------------------------------

class _FlakyClickLocator:
    """Playwright-locator double: click raises on the first `fail_times`
    calls, then succeeds (mirrors the click landing once the transient
    network blip -- e.g. a dropped __doPostBack round trip -- clears)."""

    def __init__(self, fail_times: int, exc=None):
        self.fail_times = fail_times
        self.exc = exc or PlaywrightError("net::ERR_CONNECTION_RESET")
        self.calls = 0

    async def click(self):
        self.calls += 1
        if self.calls <= self.fail_times:
            raise self.exc
        return None


def test_click_with_retry_retries_a_transient_error_and_then_succeeds():
    locator = _FlakyClickLocator(fail_times=2)
    asyncio.run(nrc._click_with_retry(locator))
    assert locator.calls == 3


def test_click_with_retry_error_that_never_clears_still_raises_not_hangs():
    locator = _FlakyClickLocator(fail_times=99)
    with pytest.raises(PlaywrightError):
        asyncio.run(nrc._click_with_retry(locator))
    assert locator.calls == 3   # stop_after_attempt(3), then gives up


def test_click_with_retry_a_non_playwright_error_is_not_retried():
    class _BadClickLocator:
        def __init__(self):
            self.calls = 0

        async def click(self):
            self.calls += 1
            raise RuntimeError("element handle disposed")

    locator = _BadClickLocator()
    with pytest.raises(RuntimeError):
        asyncio.run(nrc._click_with_retry(locator))
    assert locator.calls == 1   # a non-Playwright error is not a transport/timeout error


# ---------------------------------------------------------------------------
# _select_option_with_retry (the Index Type listbox select, which fires its
# own __doPostBack over the wire)
# ---------------------------------------------------------------------------

class _FlakySelectOptionPage:
    """Playwright-page double: select_option raises on the first
    `fail_times` calls, then succeeds (mirrors the listbox's own
    __doPostBack landing once the transient blip clears)."""

    def __init__(self, fail_times: int, exc=None):
        self.fail_times = fail_times
        self.exc = exc or PlaywrightTimeoutError("Timeout 30000ms exceeded.")
        self.calls = 0

    async def select_option(self, selector, label=None):
        self.calls += 1
        if self.calls <= self.fail_times:
            raise self.exc
        return None


def test_select_option_with_retry_retries_a_transient_timeout_and_then_succeeds():
    page = _FlakySelectOptionPage(fail_times=2)
    asyncio.run(nrc._select_option_with_retry(
        page, "select[id$='lbIndexTypes']", label="CONSOLIDATED REAL PROPERTY"
    ))
    assert page.calls == 3


def test_select_option_with_retry_timeout_that_never_clears_still_raises_not_hangs():
    page = _FlakySelectOptionPage(fail_times=99)
    with pytest.raises(PlaywrightTimeoutError):
        asyncio.run(nrc._select_option_with_retry(
            page, "select[id$='lbIndexTypes']", label="CONSOLIDATED REAL PROPERTY"
        ))
    assert page.calls == 3   # stop_after_attempt(3), then gives up


def test_select_option_with_retry_a_non_playwright_error_is_not_retried():
    class _BadSelectOptionPage:
        def __init__(self):
            self.calls = 0

        async def select_option(self, selector, label=None):
            self.calls += 1
            raise ValueError("no such option")

    page = _BadSelectOptionPage()
    with pytest.raises(ValueError):
        asyncio.run(nrc._select_option_with_retry(
            page, "select[id$='lbIndexTypes']", label="CONSOLIDATED REAL PROPERTY"
        ))
    assert page.calls == 1   # a non-Playwright error is not a transport/timeout error
