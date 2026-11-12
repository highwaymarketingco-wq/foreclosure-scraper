"""counties_sc.sc_public_index._fetch_window: a transient Playwright/Scrapling transport or
timeout failure on the single StealthyFetcher.async_fetch() call gets retried, not treated
as "the whole date window failed."

Confirmed 2026-11-07 (bug-shape sweep): _fetch_window() drives the ENTIRE multi-step ASP.NET
postback flow (disclaimer accept, 3 dropdown postbacks, date range, search submit) for one
(county, court_type, case_type, date-window) slice as ONE browser-automation call via
Scrapling's StealthyFetcher, and had zero retry cushioning of its own -- a bare
try/except Exception that logged `scpi_bulk.window_fetch_failed` and returned "" on ANY
failure, transient or not, with no re-attempt. Because this scraper is registered in
main.DATELESS_OK_SOURCES semantics, a window lost to one transient blip is never backfilled
by a later run (_scrape_county just continue()s to the next window, and the per-county loop
in SCPublicIndexBulk.fetch() does the same one level up).

This is the same root cause, and the same fix, already shipped for this module's own sibling
in the same package, sc_public_index_lis_pendens.py (see
test_sc_public_index_lis_pendens_retry.py) -- this file's _fetch_window is the near-identical
bulk (civil + criminal, all-county) counterpart, with its own court_type/case_type params.
Since the underlying client here is Scrapling/Playwright, not httpx, the retry condition
targets Playwright's own transient-failure exception types (playwright.async_api.Error /
TimeoutError) plus the builtin TimeoutError, instead of httpx.TransportError /
httpx.TimeoutException.

NOTE ON THIS TEST FILE'S NAME: the mechanical naming rule (test_<module_basename>_retry.py)
would collide with tests/test_sc_public_index_retry.py, which already exists and covers a
DIFFERENT, unrelated module that happens to share the same basename --
foreclosure_scraper.scrapers.national.sc_public_index (a Charleston-specific, curl_cffi-based
scraper, already fixed in an earlier pass). Every existing "test_sc_public_index_*.py" file in
this directory (minus the "_lis_pendens" ones) imports that national module, not this one --
there was previously NO test file at all for counties_sc.sc_public_index. Overwriting
test_sc_public_index_retry.py would have destroyed its passing coverage of that unrelated
code, so this file is named test_sc_public_index_bulk_retry.py instead, after this module's
own class name (SCPublicIndexBulk), to disambiguate without clobbering it.
"""
from __future__ import annotations

import asyncio

import pytest
from playwright.async_api import Error as PlaywrightError, TimeoutError as PlaywrightTimeoutError
from tenacity import wait_exponential_jitter

from foreclosure_scraper.scrapers.counties_sc import sc_public_index as scpi

URL = "https://publicindex.sccourts.org/Spartanburg/PublicIndex/"
COURT_TYPE = "G"
CASE_TYPE = "CP  "
DATE_FROM = "09/01/2026"
DATE_TO = "09/15/2026"


class _FakeResult:
    """Mimics the Scrapling ``Response`` object's one attribute _fetch_window reads."""

    def __init__(self, body: bytes):
        self.body = body


class _FlakyFetcher:
    """Raises on the first N-1 calls, then serves a real (terminal) page body."""

    def __init__(self, fail_times: int, exc: Exception | None = None):
        self.fail_times = fail_times
        self.exc = exc or PlaywrightError("net::ERR_CONNECTION_RESET")
        self.calls = 0

    async def async_fetch(self, url, **kwargs):
        self.calls += 1
        if self.calls <= self.fail_times:
            raise self.exc
        return _FakeResult(b"<html>real page</html>")


class _AlwaysFailsFetcher:
    """Raises the same exception on every call -- never clears."""

    def __init__(self, exc: Exception):
        self.exc = exc
        self.calls = 0

    async def async_fetch(self, url, **kwargs):
        self.calls += 1
        raise self.exc


@pytest.fixture(autouse=True)
def _fast_backoff(monkeypatch):
    """Make the exponential-jitter backoff effectively instant for tests."""
    monkeypatch.setattr(
        scpi, "wait_exponential_jitter",
        lambda **kw: wait_exponential_jitter(initial=0.001, max=0.002),
    )


def _run(fetcher):
    return asyncio.run(
        scpi._fetch_window(fetcher, URL, COURT_TYPE, CASE_TYPE, DATE_FROM, DATE_TO)
    )


def test_a_transient_playwright_error_is_retried_and_then_succeeds():
    fetcher = _FlakyFetcher(fail_times=2, exc=PlaywrightError("net::ERR_CONNECTION_RESET"))
    html = _run(fetcher)
    assert fetcher.calls == 3
    assert html == "<html>real page</html>"


def test_a_playwright_timeout_error_is_also_retried():
    """The other listed transient type (a TimeoutError subclass of Error) is honored too."""
    fetcher = _FlakyFetcher(fail_times=1, exc=PlaywrightTimeoutError("Timeout 30000ms exceeded"))
    html = _run(fetcher)
    assert fetcher.calls == 2
    assert html == "<html>real page</html>"


def test_a_builtin_timeout_error_is_also_retried():
    """The plain builtin TimeoutError hedge (mirrors the httpx-based fixes' third type)."""
    fetcher = _FlakyFetcher(fail_times=1, exc=TimeoutError("asyncio timeout"))
    html = _run(fetcher)
    assert fetcher.calls == 2
    assert html == "<html>real page</html>"


def test_a_transient_error_that_never_clears_still_stops_after_budget_not_hangs():
    """_fetch_window's pre-existing outer try/except is untouched -- it still returns ""
    on an ultimately-unrecoverable failure rather than raising to its caller (that outer catch
    is part of the original, deliberately-preserved request/response handling -- only the
    retry cushioning around the fetch call itself is new). What the fix adds is that this now
    happens only after stop_after_attempt(3) is exhausted, not on the very first blip, and it
    terminates promptly -- proving there is no infinite retry loop / hang."""
    fetcher = _AlwaysFailsFetcher(PlaywrightError("net::ERR_CONNECTION_RESET"))
    html = _run(fetcher)
    assert fetcher.calls == 3  # stop_after_attempt(3), then gives up -- no infinite retry
    assert html == ""


def test_a_real_non_transient_error_is_not_retried():
    """A genuine (non-transport/timeout) failure -- e.g. a bug surfaced as a plain
    ValueError/TypeError rather than a Playwright transport or timeout error -- must fail
    immediately on attempt 1, exactly like before this fix. Retrying it would just waste time
    re-running the whole multi-step postback flow on a failure that will never clear (the
    application-level "successfully-returned-but-wrong-page" case is not modeled here since
    _fetch_window never raises for that -- it would just return a page whose grid doesn't
    parse, which is unchanged, un-retried behavior both before and after this fix)."""
    fetcher = _AlwaysFailsFetcher(ValueError("Argument `selector_config` must be a dictionary."))
    html = _run(fetcher)
    assert fetcher.calls == 1  # a real non-transport/timeout error is not retried
    assert html == ""
