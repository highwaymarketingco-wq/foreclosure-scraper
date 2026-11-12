"""crexi_multifamily._render: a transient Playwright/Scrapling transport-or-timeout
error on StealthyFetcher.async_fetch() gets retried, not treated as "this render
attempt failed" on the very first blip.

Found 2026-11-07 (gap-sweep): `_render()`'s only network call was a bare
``try: result = await StealthyFetcher.async_fetch(...) except Exception: log.warning(...);
return "", url``. `_fetch_state()` happens to paper over this with its own
ATTEMPTS_PER_PAGE retry loop that re-invokes `_render()` whenever it comes back
empty/bad -- but `_fetch_detail_photos()` (the photo-gallery enrichment call added
2026-10-13) invokes `_render()` exactly once with NO retry of any kind, by explicit
design ("a failed photo fetch must never drop it or raise"). That design intent was
for a genuinely empty/unavailable gallery, not for a plain connection reset or render
timeout being silently treated the same way as a terminal failure. This call never
goes through httpx/http_client (no httpx import anywhere in this file) -- it is
Scrapling's browser-driven StealthyFetcher, which raises Playwright's own exception
types (``playwright.async_api.Error`` / ``TimeoutError``) on a transient navigation,
connection or timeout failure, never httpx's. A verbatim copy of the httpx-shaped
retry= clause used elsewhere in this repo (arcgis_webmap.query_features, the Column
legal-notice API scrapers, spartan_weekly_legals.py) would silently never fire here --
this test pins down the Playwright-specific exception types the real fix must use,
matching the identical call shape already fixed the same night in
zillow_foreclosures.py (test_zillow_foreclosures_retry.py), trulia_foreclosures.py
(test_trulia_foreclosures_retry.py) and zillow_bulk.py.

Modeled on tests/test_arcgis_webmap_query_features_retry.py's shape and fixture
style, adapted to Scrapling/Playwright exactly as test_trulia_foreclosures_retry.py
and test_zillow_foreclosures_retry.py already do for the identical
StealthyFetcher.async_fetch() call shape.
"""
from __future__ import annotations

import asyncio

import pytest
from playwright.async_api import Error as PlaywrightError, TimeoutError as PlaywrightTimeoutError
from scrapling.fetchers import StealthyFetcher
from tenacity import wait_exponential_jitter

from foreclosure_scraper.scrapers.national import crexi_multifamily as cx

_URL = "https://www.crexi.com/properties/NC/Multifamily?mapZoom=7"

# Deliberately >= 5000 chars (_render()'s own pre-existing "short page -> treat as a
# failed/empty render" heuristic at `if not html or len(html) < 5000:`), so a
# successful fetch resolves to a real (terminal, well-formed) page rather than being
# mistaken for the short/blocked-page outcome. Content is irrelevant beyond length --
# _render() itself does no further parsing; _extract()/_extract_gallery_photos() are
# already exercised by test_crexi_multifamily.py, not this file.
_BIG_HTML = b"<html><body><p>a real rendered Crexi page</p></body></html>" + b" " * 6000


class _FakeResult:
    def __init__(self, body: bytes, url: str | None = None):
        self.body = body
        if url is not None:
            self.url = url


class _FlakyStealthyFetcher:
    """Raises a transient-shaped exception on the first N calls, then serves a real
    (substantial, terminal) page -- mirroring _FlakyHttp in the arcgis_webmap
    reference test."""

    def __init__(self, fail_times: int, exc=None):
        self.fail_times = fail_times
        self.exc = exc or PlaywrightTimeoutError("Timeout 90000ms exceeded.")
        self.calls = 0

    async def async_fetch(self, url, **kwargs):
        self.calls += 1
        if self.calls <= self.fail_times:
            raise self.exc
        return _FakeResult(body=_BIG_HTML, url=url)


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
    body -- _render()'s own pre-existing short-page/Cloudflare-block heuristic. This
    is an HTTP-200-with-error-body-shaped outcome, not an exception, so it must never
    be retried, exactly like a real bad HTTP status is never retried."""

    def __init__(self, body: bytes = b"<html>cloudflare challenge page</html>"):
        self.body = body
        self.calls = 0

    async def async_fetch(self, url, **kwargs):
        self.calls += 1
        return _FakeResult(body=self.body, url=url)


@pytest.fixture(autouse=True)
def _fast_backoff(monkeypatch):
    monkeypatch.setattr(
        cx, "wait_exponential_jitter",
        lambda **kw: wait_exponential_jitter(initial=0.001, max=0.002),
    )


# ---------------------------------------------------------------------------
# (a) a transient transport/timeout error is retried and then succeeds
# ---------------------------------------------------------------------------


def test_a_transient_playwright_timeout_is_retried_and_then_succeeds(monkeypatch):
    fake = _FlakyStealthyFetcher(fail_times=2)
    monkeypatch.setattr(StealthyFetcher, "async_fetch", fake.async_fetch)

    html, final = asyncio.run(cx._render(_URL))

    # 2 failures + 1 success == stop_after_attempt(3)'s budget exactly.
    assert fake.calls == 3
    assert html == _BIG_HTML.decode("utf-8")
    assert final == _URL


def test_a_bare_builtin_timeout_error_is_also_retried(monkeypatch):
    # The third tuple member (builtin TimeoutError, e.g. an asyncio-level
    # cancellation/timeout) gets the same treatment as the two Playwright types.
    fake = _FlakyStealthyFetcher(fail_times=1, exc=TimeoutError("deadline exceeded"))
    monkeypatch.setattr(StealthyFetcher, "async_fetch", fake.async_fetch)

    html, final = asyncio.run(cx._render(_URL))

    assert fake.calls == 2
    assert html == _BIG_HTML.decode("utf-8")
    assert final == _URL


# ---------------------------------------------------------------------------
# (b) a transient error that never clears still raises after the retry budget
#     is exhausted (not an infinite hang) -- _render()'s own pre-existing outer
#     try/except then degrades that to the ("", url) sentinel, same as before.
# ---------------------------------------------------------------------------


def test_a_transient_playwright_error_that_never_clears_exhausts_budget_not_hang(monkeypatch):
    # net::ERR_CONNECTION_RESET-shaped: a plain playwright.async_api.Error, not the
    # TimeoutError subclass -- proves both members of the retry tuple are honored.
    fake = _AlwaysRaises(PlaywrightError("net::ERR_CONNECTION_RESET at https://www.crexi.com/"))
    monkeypatch.setattr(StealthyFetcher, "async_fetch", fake.async_fetch)

    # Must terminate promptly (bounded by stop_after_attempt(3), not an infinite
    # retry loop/hang). The retry budget genuinely exhausts and re-raises
    # (reraise=True) out of the AsyncRetrying block; _render()'s own PRE-EXISTING
    # outer `try/except Exception` (unchanged by this fix) catches that and returns
    # ("", url) -- so no exception escapes _render() itself, exactly the same
    # external shape as before this fix for a terminal failure, just now reached
    # only after 3 genuine attempts instead of swallowing the very first one.
    html, final = asyncio.run(cx._render(_URL))

    assert html == ""
    assert final == _URL
    assert fake.calls == 3  # stop_after_attempt(3), then the retry genuinely gives up


# ---------------------------------------------------------------------------
# (c) a real non-transport error is NOT retried -- fails/resolves on attempt 1.
#     This fetcher has no httpx-style status code, so the two real-world analogs
#     are: a genuinely non-transient exception type, and a "200 with error body"
#     shaped outcome (a short/blocked page returned with no exception at all).
# ---------------------------------------------------------------------------


def test_a_non_transient_runtime_error_is_not_retried(monkeypatch):
    # Scrapling's OWN "Failed to get response for {url}" failure mode (page.goto()
    # returned no response) surfaces as a bare RuntimeError -- deliberately left out
    # of the retry tuple: retrying on an unqualified RuntimeError would also catch
    # unrelated state-machine bugs a retry can never fix. It must fail immediately
    # on attempt 1 -- the real non-transport failure case, which is never retried,
    # same as a real bad HTTP status in the httpx-shaped version of this same
    # proven pattern.
    fake = _AlwaysRaises(RuntimeError("Failed to get response for https://www.crexi.com/"))
    monkeypatch.setattr(StealthyFetcher, "async_fetch", fake.async_fetch)

    html, final = asyncio.run(cx._render(_URL))

    assert fake.calls == 1   # not retried -- fails on the very first attempt
    assert html == ""
    assert final == _URL


def test_a_short_blocked_page_is_not_treated_as_a_retryable_error(monkeypatch):
    # A short/blocked body is a SUCCESSFUL fetch (no exception raised at all) --
    # the classic HTTP-200-with-error-body shape. _render()'s own pre-existing
    # `len(html) < 5000` short-page heuristic must stay untouched and un-retried by
    # this fix, exactly like a 200-with-error-body is never retried in the
    # httpx-shaped version of this same proven pattern.
    fake = _AlwaysShortPage()
    monkeypatch.setattr(StealthyFetcher, "async_fetch", fake.async_fetch)

    html, final = asyncio.run(cx._render(_URL))

    assert fake.calls == 1   # succeeded on attempt 1; short body is handled, not retried
    assert html == ""        # _render()'s own short-page branch returns "" (not raised)
    assert final == _URL


# ---------------------------------------------------------------------------
# Integration: the originally-flagged vulnerable call site, _fetch_detail_photos(),
# invokes _render() exactly once with no retry loop of its own (by explicit design --
# see its own docstring). Confirm it now benefits transitively from _render()'s own
# retry cushioning on a transient blip, instead of degrading to an empty photo list
# after a single failed attempt.
# ---------------------------------------------------------------------------


def test_fetch_detail_photos_benefits_from_renders_retry_on_a_transient_blip(monkeypatch):
    fake = _FlakyStealthyFetcher(fail_times=2)
    monkeypatch.setattr(StealthyFetcher, "async_fetch", fake.async_fetch)

    # pid "999" owns no /assets/999/ images in this bare HTML, so the photo list is
    # legitimately empty -- the point of this test is the call COUNT (proving the
    # retry actually ran underneath _fetch_detail_photos), not the parsed gallery
    # content, which is already covered by test_crexi_multifamily.py.
    photos = asyncio.run(cx._fetch_detail_photos(
        "999", "https://www.crexi.com/properties/999/north-carolina-test"
    ))

    assert fake.calls == 3  # the transient blip was retried inside _render(), not
                            # swallowed on the very first attempt
    assert photos == []


def test_fetch_detail_photos_still_degrades_to_empty_list_when_budget_exhausts(monkeypatch):
    # Belt-and-suspenders: even after this fix, a terminal failure must still
    # degrade _fetch_detail_photos() to [] rather than raise -- the "a failed photo
    # fetch must never drop the listing" contract documented on _fetch_detail_photos
    # itself is completely unchanged by this fix.
    fake = _AlwaysRaises(PlaywrightTimeoutError("Timeout 90000ms exceeded."))
    monkeypatch.setattr(StealthyFetcher, "async_fetch", fake.async_fetch)

    photos = asyncio.run(cx._fetch_detail_photos(
        "999", "https://www.crexi.com/properties/999/north-carolina-test"
    ))

    assert fake.calls == 3  # retried inside _render() up to the budget, then gave up
    assert photos == []     # _fetch_detail_photos()'s own "never raise" contract holds
