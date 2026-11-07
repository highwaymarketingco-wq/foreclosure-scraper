"""sc_public_notices._render_category / harvest_category_keywords: a transient
Playwright/Scrapling transport-or-timeout error on StealthyFetcher.async_fetch()
gets retried, not treated as "the whole category's leads are gone" on the very
first blip.

Confirmed 2026-11-07 (gap-sweep): both of this file's StealthyFetcher.async_fetch()
call sites were wrapped only in a bare ``try: ... except Exception: log.warning(...);
return <whatever was accumulated>`` -- zero retry, zero backoff. This call never goes
through httpx/http_client at all (grepped to confirm -- and the module's own docstring
explains why: "a bare httpx postback returns HTTP 500, so it must be driven in a real
browser (Scrapling StealthyFetcher)"). It is Scrapling's browser-driven StealthyFetcher,
which raises Playwright's own exception types (``playwright.async_api.Error`` /
``TimeoutError``) on a transient navigation, connection or timeout failure, never
httpx's. A verbatim copy of the httpx-shaped retry= clause used elsewhere in this repo
(arcgis_webmap.query_features, the Column legal-notice API scrapers,
spartan_weekly_legals.py) would silently never fire here, so this test pins down the
Playwright-specific exception types the real fix must use -- the same types already
proven correct for this exact StealthyFetcher shape in ncpublicnotices._search_one(),
nc_notices_counties's two call sites, and sc_public_index_lis_pendens._fetch_window()
(the sibling module this file's own docstring says it mirrors).

_render_category() is the primary, higher-severity call site: one browser session
drives the ENTIRE category's multi-county/multi-page sweep via page_action, so a
single transient blip previously zeroed that whole category's leads for the run.
harvest_category_keywords() is secondary (a failed harvest just falls back to running
every category, via _distinct_categories({}) -> list(_CATEGORIES), so no leads are
lost) but shares the identical zero-retry bug shape and is fixed the same way.

Modeled on tests/test_arcgis_webmap_query_features_retry.py's shape and fixture
style, following tests/test_ncpublicnotices_retry.py's StealthyFetcher-mocking
approach for this same bug shape.
"""
from __future__ import annotations

import asyncio

import pytest
from playwright.async_api import Error as PlaywrightError, TimeoutError as PlaywrightTimeoutError
from scrapling.fetchers import StealthyFetcher
from tenacity import wait_exponential_jitter

from foreclosure_scraper.scrapers.counties_sc import sc_public_notices as M


class _FlakyStealthyFetcher:
    """Raises a transient-shaped exception on the first N calls, then serves a
    real (terminal) fetch -- mirroring _FlakyHttp in the arcgis_webmap reference
    test. page_action is never actually invoked (no real browser page exists
    here), which is fine: these tests exercise the retry/call-count behavior
    around StealthyFetcher.async_fetch itself, not row/keyword parsing -- that
    is already covered by test_sc_public_notices.py's fixture-driven tests."""

    def __init__(self, fail_times: int, exc=None):
        self.fail_times = fail_times
        self.exc = exc or PlaywrightTimeoutError("Timeout 300000ms exceeded.")
        self.calls = 0

    async def async_fetch(self, url, **kwargs):
        self.calls += 1
        if self.calls <= self.fail_times:
            raise self.exc
        return None  # neither caller uses async_fetch's return value


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
        M, "wait_exponential_jitter",
        lambda **kw: wait_exponential_jitter(initial=0.001, max=0.002),
    )


# ------------------------------------------------------- _render_category (primary)
def test_render_category_transient_timeout_is_retried_and_then_succeeds(monkeypatch):
    fake = _FlakyStealthyFetcher(fail_times=2)
    monkeypatch.setattr(StealthyFetcher, "async_fetch", fake.async_fetch)

    rows = asyncio.run(M._render_category("4", counties=["Spartanburg"]))

    # 2 failures + 1 success == stop_after_attempt(3)'s budget exactly.
    assert fake.calls == 3
    assert rows == []


def test_render_category_transient_error_that_never_clears_still_raises_not_hangs(monkeypatch):
    # net::ERR_CONNECTION_RESET-shaped: a plain playwright.async_api.Error, not
    # the TimeoutError subclass -- proves both members of the retry tuple fire.
    fake = _AlwaysRaises(
        PlaywrightError("net::ERR_CONNECTION_RESET at https://www.scpublicnotices.com/"))
    monkeypatch.setattr(StealthyFetcher, "async_fetch", fake.async_fetch)

    # _render_category()'s own docstring: "Never raises — returns what it got."
    # Its outer try/except still catches the retry-exhausted reraise and returns
    # the (empty) rows accumulated so far, rather than hanging or propagating.
    rows = asyncio.run(M._render_category("4", counties=["Spartanburg"]))

    assert rows == []
    assert fake.calls == 3   # stop_after_attempt(3), then gives up -- not unbounded/hanging


def test_render_category_bare_builtin_timeout_error_is_also_retried(monkeypatch):
    # The third tuple member (builtin TimeoutError) gets the same treatment as
    # the two Playwright-specific types.
    fake = _FlakyStealthyFetcher(fail_times=1, exc=TimeoutError("deadline exceeded"))
    monkeypatch.setattr(StealthyFetcher, "async_fetch", fake.async_fetch)

    rows = asyncio.run(M._render_category("4", counties=["Spartanburg"]))

    assert fake.calls == 2
    assert rows == []


def test_render_category_non_transient_runtime_error_is_not_retried(monkeypatch):
    # Scrapling's OWN "Failed to get response for {url}" failure mode (page.goto()
    # returned no response) surfaces as a bare RuntimeError -- deliberately left
    # out of the retry tuple (retrying on an unqualified RuntimeError would also
    # catch unrelated state-machine bugs a retry can never fix). Must fail
    # immediately on attempt 1, exactly like a real non-transport HTTP error
    # status in the httpx-shaped version of this same proven pattern.
    fake = _AlwaysRaises(
        RuntimeError("Failed to get response for https://www.scpublicnotices.com/"))
    monkeypatch.setattr(StealthyFetcher, "async_fetch", fake.async_fetch)

    rows = asyncio.run(M._render_category("4", counties=["Spartanburg"]))

    assert rows == []
    assert fake.calls == 1   # one attempt, never retried


# ------------------------------------------------ harvest_category_keywords (secondary)
def test_harvest_category_keywords_transient_timeout_is_retried_and_then_succeeds(monkeypatch):
    fake = _FlakyStealthyFetcher(fail_times=2)
    monkeypatch.setattr(StealthyFetcher, "async_fetch", fake.async_fetch)

    found = asyncio.run(M.harvest_category_keywords())

    assert fake.calls == 3
    assert found == {}


def test_harvest_category_keywords_transient_error_that_never_clears_still_raises_not_hangs(monkeypatch):
    fake = _AlwaysRaises(PlaywrightTimeoutError("Timeout 300000ms exceeded."))
    monkeypatch.setattr(StealthyFetcher, "async_fetch", fake.async_fetch)

    # harvest_category_keywords() swallows the retry-exhausted exception in its
    # own outer try/except and returns whatever was found (empty here) -- it
    # must not hang or propagate. _distinct_categories({}) documents the
    # fallback: an empty harvest just means every category still runs.
    found = asyncio.run(M.harvest_category_keywords())

    assert found == {}
    assert fake.calls == 3


def test_harvest_category_keywords_non_transport_runtime_error_is_not_retried(monkeypatch):
    fake = _AlwaysRaises(
        RuntimeError("Failed to get response for https://www.scpublicnotices.com/"))
    monkeypatch.setattr(StealthyFetcher, "async_fetch", fake.async_fetch)

    found = asyncio.run(M.harvest_category_keywords())

    assert found == {}
    assert fake.calls == 1
