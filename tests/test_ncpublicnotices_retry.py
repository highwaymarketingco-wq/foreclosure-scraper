"""ncpublicnotices._search_one: a transient Playwright/Scrapling transport-or-timeout
error on StealthyFetcher.async_fetch() gets retried, not treated as "the whole query
failed" on the very first blip.

Found 2026-11-07 (gap-sweep): _search_one()'s ``for url in candidate_urls:`` loop
wrapped the fetch in a bare ``try/except Exception: log.warning(...); continue``. That
``continue`` advances to the NEXT, DIFFERENTLY-SHAPED candidate URL (Search.aspx ->
Default.aspx -> bare BASE) rather than re-attempting the SAME request -- a fallback-URL
cascade, not a retry. Zero backoff, zero scoping to transient failures. This call never
goes through httpx/http_client at all (grepped to confirm) -- it is Scrapling's
browser-driven StealthyFetcher, which raises Playwright's own exception types
(``playwright.async_api.Error`` / ``TimeoutError``) on a transient navigation, connection
or timeout failure, never httpx's. A verbatim copy of the httpx-shaped retry= clause
already used elsewhere in this repo (arcgis_webmap.query_features, the Column
legal-notice API scrapers, spartan_weekly_legals.py) would silently never fire here, so
this test pins down the Playwright-specific exception types the real fix must use.

Modeled on tests/test_arcgis_webmap_query_features_retry.py's shape and fixture style.
"""
from __future__ import annotations

import asyncio

import pytest
from playwright.async_api import Error as PlaywrightError, TimeoutError as PlaywrightTimeoutError
from scrapling.fetchers import StealthyFetcher
from tenacity import wait_exponential_jitter

from foreclosure_scraper.scrapers.public_notices import ncpublicnotices as ncn

# Deliberately >5000 chars (ncpublicnotices._search_one's own "substantial HTML, no
# listings -> stop trying other candidate URLs" short-circuit) and containing nothing
# _parse_results_html's card-detection can match, so a successful fetch resolves
# _search_one() immediately after the FIRST candidate URL -- keeping each test's call
# count scoped to exactly one URL's retry budget instead of being multiplied across
# all 3 candidate URL shapes the real loop tries.
_BIG_EMPTY_HTML = ("<html><body><p>no results</p></body></html>" + " " * 6000).encode("utf-8")


class _FakeResult:
    def __init__(self, body: bytes):
        self.body = body


class _FlakyStealthyFetcher:
    """Raises a transient-shaped exception on the first N calls, then serves a
    real (substantial, zero-listing, terminal) page -- mirroring _FlakyHttp in the
    arcgis_webmap reference test."""

    def __init__(self, fail_times: int, exc=None):
        self.fail_times = fail_times
        self.exc = exc or PlaywrightTimeoutError("Timeout 90000ms exceeded.")
        self.calls = 0

    async def async_fetch(self, url, **kwargs):
        self.calls += 1
        if self.calls <= self.fail_times:
            raise self.exc
        return _FakeResult(body=_BIG_EMPTY_HTML)


class _AlwaysRaises:
    """Raises the same exception on every call -- no success to ever reach."""

    def __init__(self, exc):
        self.exc = exc
        self.calls = 0

    async def async_fetch(self, url, **kwargs):
        self.calls += 1
        raise self.exc


@pytest.fixture(autouse=True)
def _fast_backoff(monkeypatch):
    monkeypatch.setattr(
        ncn, "wait_exponential_jitter",
        lambda **kw: wait_exponential_jitter(initial=0.001, max=0.002),
    )


@pytest.fixture(autouse=True)
def _no_debug_dump(monkeypatch):
    # The "substantial HTML, zero listings" short-circuit path that keeps these
    # tests scoped to one candidate URL also triggers _dump_html_for_debug's
    # write-to-disk side effect. Disabled so tests never touch the filesystem.
    monkeypatch.setattr(ncn, "DEBUG_DUMP_ENABLED", False)


def test_a_transient_playwright_timeout_is_retried_and_then_succeeds(monkeypatch):
    fake = _FlakyStealthyFetcher(fail_times=2)
    monkeypatch.setattr(StealthyFetcher, "async_fetch", fake.async_fetch)

    listings = asyncio.run(ncn._search_one("foreclosure sale", "foreclosure"))

    # 2 failures + 1 success == stop_after_attempt(3)'s budget exactly. The big,
    # zero-listing HTML on the successful 3rd attempt makes _search_one() return
    # right after the first candidate URL, so this count isn't inflated by the
    # other 2 URL shapes also being tried.
    assert fake.calls == 3
    assert listings == []


def test_a_transient_playwright_error_that_never_clears_still_raises_not_hangs(monkeypatch):
    # net::ERR_CONNECTION_RESET-shaped: a plain playwright.async_api.Error, not the
    # TimeoutError subclass -- proves both members of the retry tuple are honored.
    fake = _AlwaysRaises(PlaywrightError("net::ERR_CONNECTION_RESET at https://www.ncnotices.com/"))
    monkeypatch.setattr(StealthyFetcher, "async_fetch", fake.async_fetch)

    # Must terminate promptly (bounded by stop_after_attempt(3) x 3 candidate URLs,
    # not an infinite retry loop/hang) and must not raise out of _search_one() --
    # its own pre-existing outer try/except still catches the retry-exhausted
    # reraise per URL and falls through to the next candidate exactly as before
    # this fix, ultimately returning [] once all 3 are exhausted.
    listings = asyncio.run(ncn._search_one("foreclosure sale", "foreclosure"))

    assert listings == []
    # 3 candidate URLs x stop_after_attempt(3) each == 9. Not 3 (which would mean
    # no retry happened) and not unbounded/hanging (which would mean the retry
    # budget was never enforced).
    assert fake.calls == 9


def test_a_bare_builtin_timeout_error_is_also_retried(monkeypatch):
    # The third tuple member (builtin TimeoutError, e.g. from an asyncio-level
    # cancellation/timeout) gets the same treatment as the two Playwright types.
    fake = _FlakyStealthyFetcher(fail_times=1, exc=TimeoutError("deadline exceeded"))
    monkeypatch.setattr(StealthyFetcher, "async_fetch", fake.async_fetch)

    listings = asyncio.run(ncn._search_one("foreclosure sale", "foreclosure"))

    assert fake.calls == 2
    assert listings == []


def test_a_non_transient_runtime_error_is_not_retried(monkeypatch):
    # Scrapling's OWN "Failed to get response for {url}" failure mode (page.goto()
    # returned no response) surfaces as a bare RuntimeError -- deliberately left out
    # of the retry tuple (see the fix's own comment): retrying on an unqualified
    # RuntimeError would also catch unrelated state-machine bugs a retry can never
    # fix. It must fail immediately on attempt 1, exactly like a real non-transport
    # HTTP error status in the httpx-shaped version of this same proven pattern.
    fake = _AlwaysRaises(RuntimeError("Failed to get response for https://www.ncnotices.com/"))
    monkeypatch.setattr(StealthyFetcher, "async_fetch", fake.async_fetch)

    listings = asyncio.run(ncn._search_one("foreclosure sale", "foreclosure"))

    # One attempt per candidate URL, never retried: 3 URLs x 1 attempt == 3, not the
    # 9 a retried failure would produce.
    assert fake.calls == 3
    assert listings == []
