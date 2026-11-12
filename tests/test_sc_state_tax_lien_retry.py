"""sc_state_tax_lien._evaluate_rows: a transient Playwright-level failure on
page.evaluate(_DRIVER_JS) gets retried, not treated as "the whole scrape
produced zero rows."

Found 2026-11-07 (gap-sweep): this source's one network call -- a Scrapling
StealthyFetcher.async_fetch() browser session -- does virtually all of its
real work (pagination across up to 3 pages, the business-tab switch, table
extraction) inside page_action's page.evaluate(_DRIVER_JS) call, which used
to be swallowed to {} on the very first failure, with no log and nothing for
a retry to act on.

Unlike the httpx-based gaps already fixed tonight (a Column legal-notice API
scraper, spartan_weekly_legals.py, arcgis_webmap.query_features()), retrying
the OUTER StealthyFetcher.async_fetch() call -- the mechanical, naive version
of that same proven pattern -- would do NOTHING here: Scrapling's own engine
wraps its invocation of page_action in `except Exception: log.error(...)`
with no re-raise (scrapling/engines/_browsers/_stealth.py, confirmed by
reading the installed library's source), so a page_action failure never
reaches async_fetch()'s caller as an exception for an outer AsyncRetrying to
ever see. The retry has to live one level deeper, around
page.evaluate(_DRIVER_JS) itself -- factored out as _evaluate_rows so it is
directly testable -- keyed to Playwright's own transient-error types rather
than httpx's, since this call stack never raises
httpx.TransportError/httpx.TimeoutException.
"""
from __future__ import annotations

import asyncio

import pytest
from playwright.async_api import Error as PlaywrightError
from playwright.async_api import TimeoutError as PlaywrightTimeoutError
from tenacity import wait_exponential_jitter

from foreclosure_scraper.scrapers.counties_sc import sc_state_tax_lien as m


class _FlakyPage:
    """Stands in for Playwright's `page`. .evaluate() raises on the first
    N-1 calls, then returns a real (possibly empty) driver result -- the
    same shape _DRIVER_JS actually returns: {"individual": [...], "business": [...]}."""

    def __init__(self, fail_times: int, exc: Exception | None = None, result=None):
        self.fail_times = fail_times
        self.exc = exc or PlaywrightError("Target page, context or browser has been closed")
        self.result = result if result is not None else {"individual": [], "business": []}
        self.evaluate_calls = 0

    async def evaluate(self, script):
        self.evaluate_calls += 1
        if self.evaluate_calls <= self.fail_times:
            raise self.exc
        return self.result

    async def wait_for_load_state(self, *a, **kw):
        return None

    async def wait_for_timeout(self, *a, **kw):
        return None


class _FakeStealthyFetcher:
    """Stands in for scrapling.fetchers.StealthyFetcher.async_fetch(): calls
    page_action against a fake page exactly once, and -- like the real
    engine (scrapling/engines/_browsers/_stealth.py) -- NEVER lets a
    page_action exception escape async_fetch(). The fake mirrors that
    unconditional swallow on purpose: it is what makes retrying the OUTER
    call inert for this bug, and what _render_rows()'s own try/except
    inside page_action must cope with instead."""

    page: "_FlakyPage | None" = None

    @classmethod
    async def async_fetch(cls, url, *, page_action=None, **kw):
        if page_action is not None:
            try:
                await page_action(cls.page)
            except Exception:
                pass  # mirrors Scrapling's own unconditional swallow+log
        return object()


@pytest.fixture(autouse=True)
def _fast_backoff(monkeypatch):
    monkeypatch.setattr(m, "wait_exponential_jitter",
                        lambda **kw: wait_exponential_jitter(initial=0.001, max=0.002))


def _install_fake_fetcher(monkeypatch, page: _FlakyPage) -> None:
    import scrapling.fetchers as scrapling_fetchers
    _FakeStealthyFetcher.page = page
    monkeypatch.setattr(scrapling_fetchers, "StealthyFetcher", _FakeStealthyFetcher)


# --------------------------------------------------------------------------- #
# _evaluate_rows: the retry itself, in isolation (mirrors the four cases the
# proven httpx-based pattern tests, adapted to Playwright's error types)
# --------------------------------------------------------------------------- #

def test_a_transient_playwright_error_is_retried_and_then_succeeds():
    page = _FlakyPage(fail_times=2, result={"individual": [["A"]], "business": []})
    result = asyncio.run(m._evaluate_rows(page))
    assert page.evaluate_calls == 3
    assert result == {"individual": [["A"]], "business": []}


def test_a_playwright_timeout_error_is_also_retried():
    """playwright.async_api.TimeoutError is a subclass of Error -- confirm it
    is caught by the same predicate, not just the bare base class."""
    page = _FlakyPage(fail_times=1, exc=PlaywrightTimeoutError("Timeout 25000ms exceeded"),
                      result={"individual": [], "business": [["B"]]})
    result = asyncio.run(m._evaluate_rows(page))
    assert page.evaluate_calls == 2
    assert result == {"individual": [], "business": [["B"]]}


def test_a_transient_error_that_never_clears_still_raises_not_hangs():
    page = _FlakyPage(fail_times=99)
    with pytest.raises(PlaywrightError):
        asyncio.run(m._evaluate_rows(page))
    assert page.evaluate_calls == 3  # stop_after_attempt(3), then gives up -- not an infinite retry/hang


def test_a_non_playwright_error_is_not_retried():
    """Not every failure here is a transient browser/network blip. Playwright
    has no equivalent of "a real bad HTTP status" or "HTTP-200-with-an-
    error-body" in this file's domain (the in-page driver never signals a
    structured failure -- it only ever returns rows or raises a genuine
    Playwright/protocol error), so the discriminating "do not retry this"
    case here is a bug/exception type that ISN'T a Playwright or timeout
    error at all. It must fail on attempt 1, same as the proven pattern's
    ArcGisError case fails unretried."""
    class _UnrelatedBug(RuntimeError):
        pass

    page = _FlakyPage(fail_times=99, exc=_UnrelatedBug("not a browser/transport issue"))
    with pytest.raises(_UnrelatedBug):
        asyncio.run(m._evaluate_rows(page))
    assert page.evaluate_calls == 1  # unretried -- not a Playwright/timeout error


# --------------------------------------------------------------------------- #
# _render_rows / page_action: proving the real calling context (where
# Scrapling's own unconditional swallow lives) still never hangs and still
# benefits from the retry recovering a transient hiccup end-to-end.
# --------------------------------------------------------------------------- #

def test_render_rows_recovers_from_a_transient_hiccup_end_to_end(monkeypatch):
    rows = {"individual": [["COPELAND, QUINTESSA", "100 MAIN ST", "WELLFORD",
                             "SC", "29385", "SPARTANBURG", "$2,201,776.42"]],
            "business": []}
    page = _FlakyPage(fail_times=2, result=rows)
    _install_fake_fetcher(monkeypatch, page)

    result = asyncio.run(m._render_rows())
    assert page.evaluate_calls == 3
    assert result == rows


def test_render_rows_never_hangs_or_raises_when_retries_exhaust(monkeypatch):
    """Scrapling's own page_action wrapper swallows unconditionally, so even
    a fully-exhausted retry budget must come back as a normal (empty) dict
    out of _render_rows(), not an exception -- that propagation past
    async_fetch() is the one thing this file genuinely cannot change without
    patching a third-party library. The real, correct contract at this layer
    is "never hang, log it, and degrade to empty" -- which is exactly what
    the old code did on the FIRST failure with no retry and no log; now it
    only gets there after 3 real attempts, and it logs on the way."""
    page = _FlakyPage(fail_times=99)
    _install_fake_fetcher(monkeypatch, page)

    result = asyncio.run(m._render_rows())
    assert page.evaluate_calls == 3
    assert result == {"individual": [], "business": []}
