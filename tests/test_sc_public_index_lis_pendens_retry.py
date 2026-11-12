"""sc_public_index_lis_pendens._fetch_window: a transient Playwright/Scrapling transport or
timeout failure on the single StealthyFetcher.async_fetch() call gets retried, not treated
as "the whole date window failed."

Confirmed 2026-11-07 (bug-shape sweep, same root cause already fixed tonight for a Column
legal-notice API scraper, spartan_weekly_legals.py, and the shared arcgis_webmap.query_features()
function): _fetch_window() drives the ENTIRE multi-step ASP.NET postback flow (disclaimer
accept, 3 dropdown postbacks, date range, search submit) as ONE browser-automation call via
Scrapling's StealthyFetcher, and had zero retry cushioning of its own -- a bare
try/except Exception that logged `scpi.window_fetch_failed` and returned "" on ANY failure,
transient or not, with no re-attempt. Because this scraper is registered in
main.DATELESS_OK_SOURCES semantics apply per-window here too: a window lost to one transient
blip is never backfilled by a later run (_scrape_county just continue()s to the next window).

Unlike the other four already-fixed files, the underlying client here is Scrapling/Playwright,
not httpx, so the retry condition targets Playwright's own transient-failure exception types
(playwright.async_api.Error / TimeoutError) plus the builtin TimeoutError, instead of
httpx.TransportError / httpx.TimeoutException.
"""
from __future__ import annotations

import asyncio

import pytest
from playwright.async_api import Error as PlaywrightError, TimeoutError as PlaywrightTimeoutError
from tenacity import wait_exponential_jitter

from foreclosure_scraper.scrapers.counties_sc import sc_public_index_lis_pendens as scpi

URL = "https://publicindex.sccourts.org/Spartanburg/PublicIndex/"
COUNTY = "Spartanburg"
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


def test_a_transient_playwright_error_is_retried_and_then_succeeds():
    fetcher = _FlakyFetcher(fail_times=2, exc=PlaywrightError("net::ERR_CONNECTION_RESET"))
    html = asyncio.run(scpi._fetch_window(fetcher, URL, COUNTY, DATE_FROM, DATE_TO))
    assert fetcher.calls == 3
    assert html == "<html>real page</html>"


def test_a_playwright_timeout_error_is_also_retried():
    """The other listed transient type (a TimeoutError subclass of Error) is honored too."""
    fetcher = _FlakyFetcher(fail_times=1, exc=PlaywrightTimeoutError("Timeout 30000ms exceeded"))
    html = asyncio.run(scpi._fetch_window(fetcher, URL, COUNTY, DATE_FROM, DATE_TO))
    assert fetcher.calls == 2
    assert html == "<html>real page</html>"


def test_a_builtin_timeout_error_is_also_retried():
    """The plain builtin TimeoutError hedge (mirrors the httpx-based fixes' third type)."""
    fetcher = _FlakyFetcher(fail_times=1, exc=TimeoutError("asyncio timeout"))
    html = asyncio.run(scpi._fetch_window(fetcher, URL, COUNTY, DATE_FROM, DATE_TO))
    assert fetcher.calls == 2
    assert html == "<html>real page</html>"


def test_a_transient_error_that_never_clears_still_stops_after_budget_not_hangs():
    """_fetch_window's pre-existing outer try/except is untouched -- it still returns ""
    on an ultimately-unrecoverable failure rather than raising to its caller. What the fix
    adds is that this now happens only after stop_after_attempt(3) is exhausted, not on the
    first blip, and it terminates promptly instead of hanging."""
    fetcher = _AlwaysFailsFetcher(PlaywrightError("net::ERR_CONNECTION_RESET"))
    html = asyncio.run(scpi._fetch_window(fetcher, URL, COUNTY, DATE_FROM, DATE_TO))
    assert fetcher.calls == 3  # stop_after_attempt(3), then gives up -- no infinite retry
    assert html == ""


def test_a_real_non_transient_error_is_not_retried():
    """A genuine (non-transport/timeout) failure -- e.g. a bug surfaced as a plain
    ValueError/TypeError rather than a Playwright transport or timeout error -- must fail
    immediately on attempt 1, exactly like before this fix. Retrying it would just waste
    time re-running the whole multi-step postback flow on a failure that will never clear."""
    fetcher = _AlwaysFailsFetcher(ValueError("Argument `selector_config` must be a dictionary."))
    html = asyncio.run(scpi._fetch_window(fetcher, URL, COUNTY, DATE_FROM, DATE_TO))
    assert fetcher.calls == 1  # a real non-transport/timeout error is not retried
    assert html == ""
