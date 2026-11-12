"""counties_nc.nc_ecourts_estates: the three Playwright single-point-of-failure
calls that gate the WHOLE run get retried on a transient blip, not treated as
"the whole run failed."

Found 2026-11-07 (gap-sweep): `_drive_estate_search`'s Step 1 `page.goto`
(SmartSearch page load), Step 2's `_wait_search_form` `page.wait_for_selector`,
and Step 3's `_select_case_category` `page.evaluate` are each wrapped in a bare
try/except with zero retry cushioning. Each one gates ALL 20 TARGET_COUNTIES
before any per-county work even starts (the per-county loop in Step 4 is
already isolated -- one county's failure there only drops that county, which
is a separate, lower-severity shape not covered here). Because this source is
registered in main.DATELESS_OK_SOURCES (no fallback date window), a single
transient navigation/selector-wait/evaluate blip on any of these three would
silently zero the whole run, reported as a healthy-empty result with no
self-heal -- the same root cause already fixed tonight for the Column
legal-notice API scraper, spartan_weekly_legals.py, and
arcgis_webmap.query_features().

Unlike those httpx-flavored callers, these three are driven by a Playwright
`page` object and raise Playwright's own `Error` / `TimeoutError` -- not
`httpx.TransportError` / `httpx.TimeoutException` -- so the retry predicate
here names Playwright's actual transient exception types. Each of the three
call sites is exercised directly against a minimal Playwright-page double
(no real browser, no network); the Step 1 case is exercised through
`_drive_estate_search` itself (the retry lives inline there, not in its own
helper), with the post-Step-1 pipeline (WAF detection, the search-form wait,
debug dumps) monkeypatched to short-circuit immediately so the test isolates
Step 1's retry wrapper only.
"""
from __future__ import annotations

import asyncio

import pytest
from playwright.async_api import Error as PlaywrightError, TimeoutError as PlaywrightTimeoutError
from tenacity import wait_exponential_jitter

from foreclosure_scraper.scrapers.counties_nc import nc_ecourts_estates as nce


@pytest.fixture(autouse=True)
def _fast_backoff(monkeypatch):
    monkeypatch.setattr(nce, "wait_exponential_jitter",
                        lambda **kw: wait_exponential_jitter(initial=0.001, max=0.002))


# ---------------------------------------------------------------------------
# Step 2: _wait_search_form's page.wait_for_selector
# ---------------------------------------------------------------------------

class _FlakyWaitForSelectorPage:
    """Playwright-page double: wait_for_selector raises on the first
    `fail_times` calls, then succeeds (mirrors a real selector appearing once
    the transient blip clears)."""

    def __init__(self, fail_times: int, exc=None):
        self.fail_times = fail_times
        self.exc = exc or PlaywrightTimeoutError("Timeout 15000ms exceeded.")
        self.calls = 0

    async def wait_for_selector(self, selector, timeout=None):
        self.calls += 1
        if self.calls <= self.fail_times:
            raise self.exc
        return None


def test_wait_search_form_retries_a_transient_timeout_and_then_succeeds():
    page = _FlakyWaitForSelectorPage(fail_times=2)
    ok = asyncio.run(nce._wait_search_form(page))
    assert ok is True
    assert page.calls == 3


def test_wait_search_form_timeout_that_never_clears_returns_false_not_hangs():
    page = _FlakyWaitForSelectorPage(fail_times=99)
    ok = asyncio.run(nce._wait_search_form(page))
    assert ok is False
    assert page.calls == 3   # stop_after_attempt(3), then gives up


def test_wait_search_form_retries_a_bare_timeout_error_and_then_succeeds():
    """2026-11-07 reconciliation: the fix originally used a 2-type tuple
    (PlaywrightError, PlaywrightTimeoutError); the repo's established pattern
    for a Playwright-driven retry (nc_notices_counties.py, ncpublicnotices.py)
    also retries a bare stdlib TimeoutError. Widened to match."""
    page = _FlakyWaitForSelectorPage(fail_times=2, exc=TimeoutError("deadline exceeded"))
    ok = asyncio.run(nce._wait_search_form(page))
    assert ok is True
    assert page.calls == 3


def test_wait_search_form_a_non_playwright_error_is_not_retried():
    class _BadPage:
        def __init__(self):
            self.calls = 0

        async def wait_for_selector(self, selector, timeout=None):
            self.calls += 1
            raise RuntimeError("selector engine crashed")

    page = _BadPage()
    ok = asyncio.run(nce._wait_search_form(page))
    assert ok is False
    assert page.calls == 1   # a non-Playwright error is not a transport/timeout error


# ---------------------------------------------------------------------------
# Step 3: _select_case_category's page.evaluate
# ---------------------------------------------------------------------------

class _FlakyEvaluatePage:
    """Playwright-page double: evaluate raises on the first `fail_times`
    calls, then returns `result` (mirrors the category <select> becoming
    reachable once the transient blip clears)."""

    def __init__(self, fail_times: int, exc=None, result=True):
        self.fail_times = fail_times
        self.exc = exc or PlaywrightError("net::ERR_CONNECTION_RESET")
        self.result = result
        self.calls = 0

    async def evaluate(self, script, arg=None):
        self.calls += 1
        if self.calls <= self.fail_times:
            raise self.exc
        return self.result


def test_select_case_category_retries_a_transient_error_and_then_succeeds():
    page = _FlakyEvaluatePage(fail_times=2, result=True)
    ok = asyncio.run(nce._select_case_category(page, nce.ESTATE_CATEGORY_LABELS))
    assert ok is True
    assert page.calls == 3


def test_select_case_category_error_that_never_clears_returns_false_not_hangs():
    page = _FlakyEvaluatePage(fail_times=99)
    ok = asyncio.run(nce._select_case_category(page, nce.ESTATE_CATEGORY_LABELS))
    assert ok is False
    assert page.calls == 3   # stop_after_attempt(3), then gives up


def test_select_case_category_retries_a_bare_timeout_error_and_then_succeeds():
    """See test_wait_search_form_retries_a_bare_timeout_error_and_then_succeeds."""
    page = _FlakyEvaluatePage(fail_times=2, exc=TimeoutError("deadline exceeded"), result=True)
    ok = asyncio.run(nce._select_case_category(page, nce.ESTATE_CATEGORY_LABELS))
    assert ok is True
    assert page.calls == 3


def test_select_case_category_a_non_playwright_error_is_not_retried():
    class _BadPage:
        def __init__(self):
            self.calls = 0

        async def evaluate(self, script, arg=None):
            self.calls += 1
            raise ValueError("bad JS payload")

    page = _BadPage()
    ok = asyncio.run(nce._select_case_category(page, nce.ESTATE_CATEGORY_LABELS))
    assert ok is False
    assert page.calls == 1   # a non-Playwright error is not a transport/timeout error


# ---------------------------------------------------------------------------
# Step 1: _drive_estate_search's page.goto -- the top-level gate. A failure
# here aborts ALL 20 TARGET_COUNTIES, not just one. The retry lives inline
# inside _drive_estate_search (there's no standalone "_land" helper), so
# these tests drive it through _drive_estate_search itself, with WAF
# detection / the search-form wait / debug dumps monkeypatched to
# short-circuit immediately after Step 1 -- isolating Step 1's retry wrapper
# from the rest of the pipeline.
# ---------------------------------------------------------------------------

class _FlakyGotoPage:
    """Playwright-page double: goto raises on the first `fail_times` calls,
    then succeeds (mirrors the page landing once the transient blip clears)."""

    def __init__(self, fail_times: int, exc=None):
        self.fail_times = fail_times
        self.exc = exc or PlaywrightTimeoutError("Timeout 45000ms exceeded.")
        self.calls = 0
        self.url = "https://portal-nc.tylertech.cloud/Portal/Home/Dashboard/29"

    async def goto(self, url, wait_until=None, timeout=None):
        self.calls += 1
        if self.calls <= self.fail_times:
            raise self.exc
        return None


def _short_circuit_after_step1(monkeypatch):
    """Bypass WAF-detection and fail the search-form wait so
    _drive_estate_search returns right after Step 1, without reaching Step 3
    (category select) / Step 4 (per-county loop) or writing real debug/
    dumps. Also guarantees Step 0's pre-warm token fetch is the documented
    no-op regardless of the ambient test environment."""
    monkeypatch.delenv("TYLER_USE_WAF_SOLVER", raising=False)

    async def _no_waf(page):
        return False

    async def _form_never_found(page):
        return False

    async def _no_content(page):
        return ""

    def _no_dump(label, content):
        return None

    monkeypatch.setattr(nce, "_waf_present", _no_waf)
    monkeypatch.setattr(nce, "_wait_search_form", _form_never_found)
    monkeypatch.setattr(nce, "_safe_content", _no_content)
    monkeypatch.setattr(nce, "_dump", _no_dump)


def test_drive_estate_search_step1_goto_retries_a_transient_timeout_and_succeeds(monkeypatch):
    _short_circuit_after_step1(monkeypatch)
    page = _FlakyGotoPage(fail_times=2)
    rows = asyncio.run(nce._drive_estate_search(page, ["Buncombe"], 120))
    assert page.calls == 3
    # Step 1 itself succeeded on the 3rd try; the empty result here comes
    # from the monkeypatched Step 2 short-circuit, not from a Step 1 failure.
    assert rows == []


def test_drive_estate_search_step1_goto_that_never_clears_returns_empty_not_hangs(monkeypatch):
    _short_circuit_after_step1(monkeypatch)
    page = _FlakyGotoPage(fail_times=99)
    rows = asyncio.run(nce._drive_estate_search(page, ["Buncombe"], 120))
    assert page.calls == 3   # stop_after_attempt(3), then gives up -> land_fail path
    assert rows == []


def test_drive_estate_search_step1_goto_retries_a_bare_timeout_error_and_succeeds(monkeypatch):
    """See test_wait_search_form_retries_a_bare_timeout_error_and_then_succeeds."""
    _short_circuit_after_step1(monkeypatch)
    page = _FlakyGotoPage(fail_times=2, exc=TimeoutError("deadline exceeded"))
    rows = asyncio.run(nce._drive_estate_search(page, ["Buncombe"], 120))
    assert page.calls == 3
    assert rows == []


def test_drive_estate_search_step1_a_non_playwright_error_is_not_retried(monkeypatch):
    _short_circuit_after_step1(monkeypatch)

    class _BadGotoPage(_FlakyGotoPage):
        async def goto(self, url, wait_until=None, timeout=None):
            self.calls += 1
            raise RuntimeError("dns resolver crashed")

    page = _BadGotoPage(fail_times=0)
    rows = asyncio.run(nce._drive_estate_search(page, ["Buncombe"], 120))
    assert page.calls == 1   # a non-Playwright error is not a transport/timeout error
    assert rows == []
