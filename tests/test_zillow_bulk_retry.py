"""zillow_bulk._fetch_state: a transient Playwright/Scrapling transport-or-timeout
error on StealthyFetcher.async_fetch() gets retried, not treated as "the whole
state's sold-comp scrape failed" on the very first blip.

Found 2026-11-07 (gap-sweep follow-up): the page-1 fetch inside _fetch_state()'s
`for page in range(1, max_pages + 1):` pagination loop was a bare
``try: result = await StealthyFetcher.async_fetch(...) except Exception: log.warning(...);
break``. That `break` abandons EVERY remaining page for the state (not just the failed
one) -- the pagination loop is not a retry loop. Page 1 must succeed before `out` holds
anything, so a single transient blip there silently zeroed the whole state's sold-comp
result for the run. This call never goes through httpx/http_client (grepped the module's
imports to confirm: json/os/re/datetime/typing/structlog/BaseScraper/models only, plus the
function-scoped `from scrapling.fetchers import StealthyFetcher`) -- it is Scrapling's
browser-driven StealthyFetcher, which raises Playwright's own exception types
(``playwright.async_api.Error`` / ``TimeoutError``) on a transient navigation, connection or
timeout failure, never httpx's. A verbatim copy of the httpx-shaped retry= clause used
elsewhere in this repo (arcgis_webmap.query_features, the Column legal-notice API scrapers,
spartan_weekly_legals.py) would silently never fire here -- this test pins down the
Playwright-specific exception types the real fix must use, matching the identical call shape
already fixed the same night in this file's own sibling, zillow_foreclosures.py
(test_zillow_foreclosures_retry.py) and in ncpublicnotices.py (test_ncpublicnotices_retry.py).

Modeled on tests/test_arcgis_webmap_query_features_retry.py's shape and fixture style, with
the fake fetcher adapted to Scrapling/Playwright exactly as test_zillow_foreclosures_retry.py
already does for this same StealthyFetcher.async_fetch() call shape (zillow_bulk.py and
zillow_foreclosures.py are near-line-for-line siblings per zillow_bulk.py's own module
docstring). The one real difference: zillow_bulk._fetch_state(state, slug, max_pages) takes
an explicit max_pages arg (no hardcoded range(1, 11)), and has no separate "empty first page"
warning branch -- an empty-but-successful page-1 parse just falls through its own pre-existing
`new == 0: break` check, which stops the loop after exactly one successful call either way.
"""
from __future__ import annotations

import asyncio

import pytest
from playwright.async_api import Error as PlaywrightError, TimeoutError as PlaywrightTimeoutError
from scrapling.fetchers import StealthyFetcher
from tenacity import wait_exponential_jitter

from foreclosure_scraper.scrapers.national import zillow_bulk as zb

_STATE = "NC"
_SLUG = "national.zillow_bulk"
_MAX_PAGES = 3  # matches the ZILLOW_SOLD_PAGES env default; irrelevant to these
                # tests since every scenario here resolves or gives up within page 1.

# Deliberately >= 5000 chars (_fetch_state's own pre-existing "short page -> captcha/
# blocked, stop" heuristic) and containing no `__NEXT_DATA__` script tag _parse_page's
# NEXT_DATA_RE can match, so a successful fetch resolves to zero listings and
# _fetch_state's own pre-existing `new == 0: break` branch returns right after page 1.
# That keeps each test's call count scoped to exactly ONE page's retry budget -- this
# module tries only one URL per page (no fallback-URL cascade), so there is no
# multiplier to account for.
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
        zb, "wait_exponential_jitter",
        lambda **kw: wait_exponential_jitter(initial=0.001, max=0.002),
    )


def test_a_transient_playwright_timeout_is_retried_and_then_succeeds(monkeypatch):
    fake = _FlakyStealthyFetcher(fail_times=2)
    monkeypatch.setattr(StealthyFetcher, "async_fetch", fake.async_fetch)

    out = asyncio.run(zb._fetch_state(_STATE, _SLUG, _MAX_PAGES))

    # 2 failures + 1 success == stop_after_attempt(3)'s budget exactly.
    assert fake.calls == 3
    # The successful page has no __NEXT_DATA__, so _parse_page yields zero listings;
    # _fetch_state's own pre-existing "new == 0" branch then stops cleanly after page 1.
    assert out == []


def test_a_transient_playwright_error_that_never_clears_exhausts_budget_not_hang(monkeypatch):
    # net::ERR_CONNECTION_RESET-shaped: a plain playwright.async_api.Error, not the
    # TimeoutError subclass -- proves both members of the retry tuple are honored.
    fake = _AlwaysRaises(PlaywrightError("net::ERR_CONNECTION_RESET at https://www.zillow.com/"))
    monkeypatch.setattr(StealthyFetcher, "async_fetch", fake.async_fetch)

    # Must terminate promptly (bounded by stop_after_attempt(3), not an infinite
    # retry loop/hang). The retry budget genuinely exhausts and re-raises
    # (reraise=True) out of the AsyncRetrying block; _fetch_state's own
    # PRE-EXISTING outer `try/except Exception` (unchanged by this fix) catches
    # that and `break`s out of the page loop for this state -- so no exception
    # escapes _fetch_state itself, exactly the same shape as before this fix for
    # a terminal failure, just now reached only after 3 genuine attempts instead
    # of swallowing the very first one.
    out = asyncio.run(zb._fetch_state(_STATE, _SLUG, _MAX_PAGES))

    assert out == []
    assert fake.calls == 3  # stop_after_attempt(3), then the retry genuinely gives up


def test_a_bare_builtin_timeout_error_is_also_retried(monkeypatch):
    # The third tuple member (builtin TimeoutError, e.g. an asyncio-level
    # cancellation/timeout) gets the same treatment as the two Playwright types.
    fake = _FlakyStealthyFetcher(fail_times=1, exc=TimeoutError("deadline exceeded"))
    monkeypatch.setattr(StealthyFetcher, "async_fetch", fake.async_fetch)

    out = asyncio.run(zb._fetch_state(_STATE, _SLUG, _MAX_PAGES))

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
    fake = _AlwaysRaises(RuntimeError("Failed to get response for https://www.zillow.com/nc/sold/foreclosures/"))
    monkeypatch.setattr(StealthyFetcher, "async_fetch", fake.async_fetch)

    out = asyncio.run(zb._fetch_state(_STATE, _SLUG, _MAX_PAGES))

    assert fake.calls == 1   # not retried -- fails on the very first attempt
    assert out == []


def test_a_short_captcha_page_is_not_treated_as_a_retryable_error(monkeypatch):
    # A short/blocked body is a SUCCESSFUL fetch (no exception raised at all) --
    # the classic HTTP-200-with-error-body shape. _fetch_state's own pre-existing
    # `len(html) < 5000` captcha/short-page heuristic must stay untouched and
    # un-retried by this fix, exactly like a 200-with-error-body is never retried
    # in the httpx-shaped version of this same proven pattern.
    fake = _AlwaysShortPage()
    monkeypatch.setattr(StealthyFetcher, "async_fetch", fake.async_fetch)

    out = asyncio.run(zb._fetch_state(_STATE, _SLUG, _MAX_PAGES))

    assert fake.calls == 1   # succeeded on attempt 1; short body stops the page loop
    assert out == []
