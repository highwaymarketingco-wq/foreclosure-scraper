"""trulia_foreclosures._fetch_page: a transient Playwright/Scrapling transport-or-
timeout error on StealthyFetcher.async_fetch() gets retried, not treated as "this
URL variant's whole fetch failed" on the very first blip.

Found 2026-11-07 (gap-sweep): `_fetch_page()`'s only network call was a bare
``try: result = await StealthyFetcher.async_fetch(...) except Exception: log.warning(...);
return []``. TruliaForeclosures.fetch() isolates each of the 8 URL_VARIANTS with its
own try/except (`continue`s to the next URL on failure), so one transient blip only
drops that one variant's ~16 listings rather than zeroing the whole scrape -- but
that isolation is pagination/fan-out, not retry: neither loop ever re-attempts the
SAME failed fetch. A single connection reset or render timeout on any one variant
still permanently zeroed that variant's results for the run, with zero retry
tolerance. This call never goes through httpx/http_client (grepped the file to
confirm -- no httpx import anywhere) -- it is Scrapling's browser-driven
StealthyFetcher, which raises Playwright's own exception types
(``playwright.async_api.Error`` / ``TimeoutError``) on a transient navigation,
connection or timeout failure, never httpx's. A verbatim copy of the httpx-shaped
retry= clause used elsewhere in this repo (arcgis_webmap.query_features, the Column
legal-notice API scrapers, spartan_weekly_legals.py) would silently never fire here
-- this test pins down the Playwright-specific exception types the real fix must
use, matching the identical call shape already fixed the same night in
zillow_foreclosures.py (test_zillow_foreclosures_retry.py) and ncpublicnotices.py.

Modeled on tests/test_arcgis_webmap_query_features_retry.py's shape and fixture
style, adapted to Scrapling/Playwright exactly as test_zillow_foreclosures_retry.py
already does for the identical StealthyFetcher.async_fetch() call shape.
"""
from __future__ import annotations

import asyncio

import pytest
from playwright.async_api import Error as PlaywrightError, TimeoutError as PlaywrightTimeoutError
from scrapling.fetchers import StealthyFetcher
from tenacity import wait_exponential_jitter

from foreclosure_scraper.scrapers.national import trulia_foreclosures as mod

_URL = "https://www.trulia.com/foreclosures/"

# Deliberately >= 5000 chars (_fetch_page's own pre-existing "short page -> likely
# captcha/blocked, bail" heuristic) and containing no `__NEXT_DATA__` script tag
# NEXT_DATA_RE can match, so a successful fetch resolves to zero listings via
# _fetch_page's own "no __NEXT_DATA__ match -> return []" branch. That keeps each
# test's call count scoped to exactly _fetch_page's own retry budget, with no
# downstream JSON-parsing or home-mapping logic in play at all.
_BIG_EMPTY_HTML = b"<html><body><p>no next-data script here</p></body></html>" + b" " * 6000


class _FakeResult:
    def __init__(self, body: bytes):
        self.body = body


class _FlakyStealthyFetcher:
    """Raises a transient-shaped exception on the first N calls, then serves a real
    (substantial, zero-listing, terminal) page -- mirroring _FlakyHttp in the
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


class _AlwaysShortPage:
    """Always 'succeeds' (no exception raised) but with a short, below-5000-char
    body -- the module's own pre-existing captcha/short-page heuristic. This is an
    HTTP-200-with-error-body-shaped outcome, not an exception, so it must never be
    retried, exactly like a real bad HTTP status is never retried."""

    def __init__(self, body: bytes = b"<html>captcha challenge, please try again</html>"):
        self.body = body
        self.calls = 0

    async def async_fetch(self, url, **kwargs):
        self.calls += 1
        return _FakeResult(body=self.body)


@pytest.fixture(autouse=True)
def _fast_backoff(monkeypatch):
    monkeypatch.setattr(
        mod, "wait_exponential_jitter",
        lambda **kw: wait_exponential_jitter(initial=0.001, max=0.002),
    )


def test_a_transient_playwright_timeout_is_retried_and_then_succeeds(monkeypatch):
    fake = _FlakyStealthyFetcher(fail_times=2)
    monkeypatch.setattr(StealthyFetcher, "async_fetch", fake.async_fetch)

    out = asyncio.run(mod._fetch_page(_URL))

    # 2 failures + 1 success == stop_after_attempt(3)'s budget exactly.
    assert fake.calls == 3
    # The successful page has no __NEXT_DATA__, so _fetch_page's own "no match ->
    # return []" branch fires cleanly right after the retry loop succeeds.
    assert out == []


def test_a_transient_playwright_error_that_never_clears_exhausts_budget_not_hang(monkeypatch):
    # net::ERR_CONNECTION_RESET-shaped: a plain playwright.async_api.Error, not the
    # TimeoutError subclass -- proves both members of the retry tuple are honored.
    fake = _AlwaysRaises(PlaywrightError("net::ERR_CONNECTION_RESET at https://www.trulia.com/"))
    monkeypatch.setattr(StealthyFetcher, "async_fetch", fake.async_fetch)

    # Must terminate promptly (bounded by stop_after_attempt(3), not an infinite
    # retry loop/hang). The retry budget genuinely exhausts and re-raises
    # (reraise=True) out of the AsyncRetrying block; _fetch_page's own PRE-EXISTING
    # outer `try/except Exception` (unchanged by this fix) catches that and returns
    # [] -- so no exception escapes _fetch_page itself, exactly the same external
    # shape as before this fix for a terminal failure, just now reached only after
    # 3 genuine attempts instead of swallowing the very first one.
    out = asyncio.run(mod._fetch_page(_URL))

    assert out == []
    assert fake.calls == 3  # stop_after_attempt(3), then the retry genuinely gives up


def test_a_bare_builtin_timeout_error_is_also_retried(monkeypatch):
    # The third tuple member (builtin TimeoutError, e.g. an asyncio-level
    # cancellation/timeout) gets the same treatment as the two Playwright types.
    fake = _FlakyStealthyFetcher(fail_times=1, exc=TimeoutError("deadline exceeded"))
    monkeypatch.setattr(StealthyFetcher, "async_fetch", fake.async_fetch)

    out = asyncio.run(mod._fetch_page(_URL))

    assert fake.calls == 2
    assert out == []


def test_a_non_transient_runtime_error_is_not_retried(monkeypatch):
    # Scrapling's OWN "Failed to get response for {url}" failure mode (page.goto()
    # returned no response) surfaces as a bare RuntimeError -- deliberately left out
    # of the retry tuple (see the fix's own comment): retrying on an unqualified
    # RuntimeError would also catch unrelated state-machine bugs a retry can never
    # fix. It must fail immediately on attempt 1 -- the real non-transport failure
    # case, which is never retried, same as a real bad HTTP status in the
    # httpx-shaped version of this same proven pattern.
    fake = _AlwaysRaises(RuntimeError("Failed to get response for https://www.trulia.com/foreclosures/"))
    monkeypatch.setattr(StealthyFetcher, "async_fetch", fake.async_fetch)

    out = asyncio.run(mod._fetch_page(_URL))

    assert fake.calls == 1   # not retried -- fails on the very first attempt
    assert out == []


def test_a_short_captcha_page_is_not_treated_as_a_retryable_error(monkeypatch):
    # A short/blocked body is a SUCCESSFUL fetch (no exception raised at all) --
    # the classic HTTP-200-with-error-body shape. _fetch_page's own pre-existing
    # `len(html) < 5000` short-page heuristic must stay untouched and un-retried by
    # this fix, exactly like a 200-with-error-body is never retried in the
    # httpx-shaped version of this same proven pattern.
    fake = _AlwaysShortPage()
    monkeypatch.setattr(StealthyFetcher, "async_fetch", fake.async_fetch)

    out = asyncio.run(mod._fetch_page(_URL))

    assert fake.calls == 1   # succeeded on attempt 1; short body is handled, not retried
    assert out == []
