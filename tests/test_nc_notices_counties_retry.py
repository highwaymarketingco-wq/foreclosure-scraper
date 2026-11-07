"""nc_notices_counties: a transient Playwright transport/timeout error on the
StealthyFetcher.async_fetch() call gets retried, not treated as "the whole
scrape is empty for this run."

Found 2026-11-07 (gap-sweep follow-up): this module's two network call sites --
_render_queries() (the single entry point that drives the entire 20-county,
8-query search session inside one browser page) and fetch_notice_detail() (the
bounded, best-effort per-row address backfill) -- both called
scrapling.fetchers.StealthyFetcher.async_fetch() inside a bare
try/except Exception with zero outer retry cushioning, the exact pattern
already fixed elsewhere in this repo tonight (the Column legal-notice API
scraper, spartan_weekly_legals.py, arcgis_webmap.query_features()).

_render_queries() is the real single point of failure: it is
NCNoticesCounties.fetch()'s ONLY entry point, and this source is registered in
main.DATELESS_OK_SOURCES (no date-window fallback to self-heal later), so one
transient blip -- especially an early one, before page_action has ticked a
single county -- permanently zeroed the whole run, reported as a healthy
empty result rather than a retried one. fetch_notice_detail() has the same
unprotected pattern at lower severity (a bounded per-row loop, so one blip
there only drops that row's best-effort enrichment, not the whole run).

StealthyFetcher is Playwright-backed, not httpx-backed (its own fetchers
import no httpx at all -- confirmed by reading scrapling's installed source),
so the retry predicate here targets Playwright's actual exception surface:
playwright.async_api.Error is the single class Playwright raises for every
navigation/connection-level failure (net::ERR_CONNECTION_RESET,
net::ERR_NAME_NOT_RESOLVED, a crashed/closed target, ...) -- there is no
finer-grained subclass per failure the way httpx has ConnectError/ReadTimeout/
etc. -- plus its TimeoutError subclass for an operation that outright times
out. httpx's exception classes would never fire for this fetcher, so they are
deliberately not in the retry tuple here. A real, non-transient failure (e.g.
a RuntimeError from some unrelated cause) must still fail immediately, on
attempt 1.

Both wrapped functions are explicitly documented to NEVER raise to their own
caller (fetch_notice_detail: "Never raises."; _render_queries: "Every step is
non-fatal... returns whatever was captured so far"), so the retry-exhausted
case is proven here by call COUNT -- bounded at stop_after_attempt(3), not an
infinite hang -- rather than by a propagated exception, unlike
arcgis_webmap.query_features(), which has no such outer swallow-all-exceptions
layer of its own and so can assert pytest.raises(...) directly.

Modeled on tests/test_arcgis_webmap_query_features_retry.py (fast-backoff
fixture, flaky-then-succeeds / never-clears / non-transient-fails-immediately
shape) and on this module's own tests/test_nc_notices_counties.py
(_install_fake_scrapling's sys.modules-injection technique for faking the
lazily-imported `from scrapling.fetchers import StealthyFetcher`).
"""
from __future__ import annotations

import asyncio
import sys
import types

import pytest
from playwright.async_api import Error as PlaywrightError, TimeoutError as PlaywrightTimeoutError
from tenacity import wait_exponential_jitter

from foreclosure_scraper.scrapers.public_notices import nc_notices_counties as M


def _install_fake_scrapling(monkeypatch, async_fetch):
    """Fake out `from scrapling.fetchers import StealthyFetcher` (the lazy
    import both call sites use) via sys.modules injection -- same technique as
    test_nc_notices_counties.py's own _install_fake_scrapling, but
    parameterized directly on the async_fetch callable rather than on a fake
    page, so these retry tests can control exactly when
    StealthyFetcher.async_fetch raises vs. succeeds, independent of either
    call site's own page_action logic (reveal()'s or _render_queries()'s)."""
    mod = types.ModuleType("scrapling.fetchers")
    mod.StealthyFetcher = types.SimpleNamespace(async_fetch=async_fetch)
    monkeypatch.setitem(sys.modules, "scrapling", types.ModuleType("scrapling"))
    monkeypatch.setitem(sys.modules, "scrapling.fetchers", mod)


@pytest.fixture(autouse=True)
def _fast_backoff(monkeypatch):
    """Same technique as test_arcgis_webmap_query_features_retry.py: make the
    exponential-jitter wait trivially short so these tests run in
    milliseconds instead of waiting out the real 1-8s backoff."""
    monkeypatch.setattr(M, "wait_exponential_jitter",
                        lambda **kw: wait_exponential_jitter(initial=0.001, max=0.002))


# --------------------------------------------- _render_queries() call site --
# The real bug: NCNoticesCounties.fetch()'s one and only entry point.

def test_render_queries_retries_a_transient_playwright_error_and_then_succeeds(monkeypatch):
    calls = {"n": 0}

    async def flaky(url, page_action=None, **kw):
        calls["n"] += 1
        if calls["n"] <= 2:
            raise PlaywrightError(f"net::ERR_CONNECTION_RESET at {url}")
        return None  # 3rd attempt "succeeds"; page_action is _render_queries()'s
                      # own elaborate county/query-driving closure and is not
                      # exercised here -- see the module docstring above.

    _install_fake_scrapling(monkeypatch, flaky)
    pages = asyncio.run(M._render_queries())
    assert calls["n"] == 3
    assert pages == []   # nothing captured, but it returned cleanly -- no raise, no hang


def test_render_queries_gives_up_after_the_retry_budget_not_an_infinite_hang(monkeypatch):
    calls = {"n": 0}

    async def always_flaky(url, page_action=None, **kw):
        calls["n"] += 1
        raise PlaywrightTimeoutError("Timeout 600000ms exceeded.")

    _install_fake_scrapling(monkeypatch, always_flaky)
    # _render_queries() never raises to its own caller (see module docstring) --
    # the proof that the retry budget is bounded, not an infinite hang, is the
    # call count: exactly stop_after_attempt(3), then it gives up and returns.
    pages = asyncio.run(M._render_queries())
    assert calls["n"] == 3
    assert pages == []


def test_render_queries_does_not_retry_a_real_non_transient_error(monkeypatch):
    calls = {"n": 0}

    async def boom(url, page_action=None, **kw):
        calls["n"] += 1
        raise RuntimeError("not a transport/timeout error")

    _install_fake_scrapling(monkeypatch, boom)
    pages = asyncio.run(M._render_queries())
    assert calls["n"] == 1   # a real non-transport error is not retried
    assert pages == []


def test_render_queries_succeeds_on_the_first_try_with_no_retry_overhead(monkeypatch):
    """Sanity check: the common, no-failure case still runs page_action exactly
    once and returns normally -- the retry wrapper adds no overhead and does
    not change what is requested."""
    calls = {"n": 0}
    ran_page_action = {"ran": False}

    async def ok(url, page_action=None, **kw):
        calls["n"] += 1
        if page_action is not None:
            ran_page_action["ran"] = True
        return None

    _install_fake_scrapling(monkeypatch, ok)
    pages = asyncio.run(M._render_queries())
    assert calls["n"] == 1
    assert ran_page_action["ran"] is True
    assert pages == []


# ------------------------------------------- fetch_notice_detail() call site -
# Same unprotected pattern, lower severity (one bounded per-row loop, not a
# single point of failure) -- still worth the identical fix for robustness.

class _FakeDetailPage:
    """Minimal stand-in for the page passed to fetch_notice_detail()'s
    page_action (reveal) -- same shape as test_nc_notices_counties.py's own
    _FakeDetailPage, trimmed to what reveal() actually calls."""

    def __init__(self, final_html: str = ""):
        self.final_html = final_html

    async def wait_for_load_state(self, *a, **k):
        return None

    async def wait_for_timeout(self, *a, **k):
        return None

    async def evaluate(self, js):
        return False   # Turnstile token already resolved -- not under test here

    async def click(self, sel, timeout=None):
        return None

    async def content(self):
        return self.final_html


def test_fetch_notice_detail_retries_a_transient_playwright_timeout_and_succeeds(monkeypatch):
    calls = {"n": 0}
    page = _FakeDetailPage('<span id="lblContentText">123 Sycamore Lane</span>')

    async def flaky(url, page_action=None, **kw):
        calls["n"] += 1
        if calls["n"] <= 1:
            raise PlaywrightTimeoutError("Timeout 60000ms exceeded.")
        if page_action:
            await page_action(page)
        return None

    _install_fake_scrapling(monkeypatch, flaky)
    text = asyncio.run(M.fetch_notice_detail("https://www.ncnotices.com/Details.aspx?ID=1"))
    assert calls["n"] == 2
    assert text is not None and "123 Sycamore Lane" in text


def test_fetch_notice_detail_gives_up_after_the_retry_budget_and_returns_none(monkeypatch):
    calls = {"n": 0}

    async def always_flaky(url, page_action=None, **kw):
        calls["n"] += 1
        raise PlaywrightError("net::ERR_CONNECTION_RESET")

    _install_fake_scrapling(monkeypatch, always_flaky)
    text = asyncio.run(M.fetch_notice_detail("https://www.ncnotices.com/Details.aspx?ID=2"))
    assert calls["n"] == 3     # stop_after_attempt(3), then gives up
    assert text is None        # never raises -- see the function's own docstring


def test_fetch_notice_detail_does_not_retry_a_real_non_transient_error(monkeypatch):
    calls = {"n": 0}

    async def boom(url, page_action=None, **kw):
        calls["n"] += 1
        raise RuntimeError("not a transport/timeout error")

    _install_fake_scrapling(monkeypatch, boom)
    text = asyncio.run(M.fetch_notice_detail("https://www.ncnotices.com/Details.aspx?ID=3"))
    assert calls["n"] == 1   # a real non-transport error is not retried
    assert text is None
