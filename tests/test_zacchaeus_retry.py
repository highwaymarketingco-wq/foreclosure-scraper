"""law_firms.zacchaeus._fetch_rows: a transient patchright/timeout error on the
stealth-browser fetch gets retried, not treated as "the whole ~21-page grid
capture failed" on the very first blip.

Confirmed 2026-11-07 (bug-shape sweep): the one network-dependent call site in
this file -- `await StealthyFetcher.async_fetch(...)` inside the module-level
async helper `_fetch_rows()` -- had zero retry cushioning (a bare
`try/except Exception: return []`), the same root-cause gap already fixed
tonight for the Column legal-notice API scrapers, spartan_weekly_legals.py, and
the shared arcgis_webmap.query_features(). Because law_firms.zacchaeus is listed
in main.DATELESS_OK_SOURCES (no date-window fallback to self-heal), a single
transient blip anywhere across the ~21-page DevExpress grid pager loop used to
silently zero the whole run -- reported as a healthy empty result, not a
visible failure -- since `captured["rows"]` is only ever assigned once, after
the entire page_action closure completes without the outer call raising.

Materially different call shape than the three httpx-based fixes above, so the
proven recipe's literal `(httpx.TransportError, httpx.TimeoutException,
TimeoutError)` tuple is inert here: this is a Scrapling StealthyFetcher browser
call, not an httpx call. It is also a DIFFERENT exception hierarchy than the
`playwright.async_api.Error`/`TimeoutError` types used for this same
StealthyFetcher.async_fetch() call shape elsewhere tonight (zillow_bulk.py,
zillow_foreclosures.py, ncpublicnotices.py) -- confirmed by reading the
installed scrapling package directly: scrapling/engines/_browsers/_stealth.py
imports `async_playwright` from **patchright.async_api**, not from
`playwright.async_api` (`from patchright.async_api import async_playwright`,
then `self.playwright = await async_playwright().start()`, then every
browser/context/page `AsyncStealthySession.fetch()` uses -- including the
`page.goto()` call that can raise on a transient navigation/connection/timeout
failure -- is built from that same `self.playwright`). `patchright` is a
separate, distinct stealth fork of Playwright with its own `Error`/
`TimeoutError` classes: live-verified `patchright._impl._errors.Error is not
playwright._impl._errors.Error` (identical shape, unrelated classes, so
`isinstance()` never crosses between them). A fix that imported
`playwright.async_api` instead would compile, look identical to the proven
pattern, and silently never actually retry anything against the real library --
exactly the landmine this test is written to catch. This fix targets
`patchright.async_api.Error` (which `TimeoutError` subclasses) plus a bare
builtin `TimeoutError`, for parity with the proven recipe's third tuple member.

Modeled on tests/test_arcgis_webmap_query_features_retry.py's shape, fixture
style, and the (a)/(b)/(c) minimum coverage it was built to demonstrate, with
the fake-fetcher mechanics (class-based fakes monkeypatching
StealthyFetcher.async_fetch directly) adapted the same way
test_zillow_bulk_retry.py already adapts them for this identical
StealthyFetcher.async_fetch() call shape -- swapping its playwright.async_api
exception types for the patchright.async_api ones this file's own call chain
actually raises.
"""
from __future__ import annotations

import asyncio

import pytest
from patchright.async_api import Error as PatchrightError, TimeoutError as PatchrightTimeoutError
from scrapling.fetchers import StealthyFetcher
from tenacity import wait_exponential_jitter

from foreclosure_scraper.scrapers.law_firms import zacchaeus as zc


class _FlakyStealthyFetcher:
    """Raises a transient-shaped exception on the first N calls, then "succeeds"
    (no exception) -- mirroring _FlakyHttp in the arcgis_webmap reference test
    and _FlakyStealthyFetcher in test_zillow_bulk_retry.py. The real
    `async_fetch` return value is only ever consumed by zacchaeus.py's
    page_action closure (which this fake does not drive), so a bare `None`
    return is a faithful stand-in here: it proves the retry/give-up bookkeeping
    around the call itself, independent of the separately-tested row-parsing
    logic in test_zacchaeus.py.
    """

    def __init__(self, fail_times: int, exc=None):
        self.fail_times = fail_times
        self.exc = exc or PatchrightTimeoutError("Timeout 300000ms exceeded.")
        self.calls = 0

    async def async_fetch(self, url, **kwargs):
        self.calls += 1
        if self.calls <= self.fail_times:
            raise self.exc
        return None


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
        zc, "wait_exponential_jitter",
        lambda **kw: wait_exponential_jitter(initial=0.001, max=0.002),
    )


def test_a_transient_patchright_error_is_retried_and_then_succeeds(monkeypatch):
    fake = _FlakyStealthyFetcher(fail_times=2, exc=PatchrightError("net::ERR_CONNECTION_RESET"))
    monkeypatch.setattr(StealthyFetcher, "async_fetch", fake.async_fetch)

    rows = asyncio.run(zc._fetch_rows())

    # 2 failures + 1 success == stop_after_attempt(3)'s budget exactly.
    assert fake.calls == 3
    # page_action never ran against a real page in this fake, so nothing was
    # captured -- that's fine, this test only proves the retry-then-succeed
    # bookkeeping around the call, not row parsing (test_zacchaeus.py already
    # covers _row_to_listing exhaustively).
    assert rows == []


def test_a_transient_patchright_timeout_is_also_retried(monkeypatch):
    # patchright's TimeoutError is a subclass of its own Error, so this also
    # proves the retry tuple's first member catches it via the subclass
    # relationship, not only when the base class is raised directly.
    fake = _FlakyStealthyFetcher(fail_times=1, exc=PatchrightTimeoutError("Timeout 300000ms exceeded."))
    monkeypatch.setattr(StealthyFetcher, "async_fetch", fake.async_fetch)

    rows = asyncio.run(zc._fetch_rows())

    assert fake.calls == 2
    assert rows == []


def test_a_bare_builtin_timeout_error_is_also_retried(monkeypatch):
    # The retry tuple's second member (builtin TimeoutError, e.g. a stray
    # asyncio-level timeout not wrapped in patchright's own hierarchy) gets the
    # same treatment, matching the proven recipe's third tuple member.
    fake = _FlakyStealthyFetcher(fail_times=1, exc=TimeoutError("deadline exceeded"))
    monkeypatch.setattr(StealthyFetcher, "async_fetch", fake.async_fetch)

    rows = asyncio.run(zc._fetch_rows())

    assert fake.calls == 2
    assert rows == []


def test_a_transient_patchright_error_that_never_clears_exhausts_budget_not_hang(monkeypatch):
    """stop_after_attempt(3) must still cap it. _fetch_rows()'s own outer bare
    `except Exception: return []` is PRE-EXISTING, unchanged behavior for a
    persistent failure -- it means the exhausted retry's re-raise
    (reraise=True) never escapes _fetch_rows() as a raised exception, so what
    proves the budget is actually enforced (not an infinite retry loop/hang) is
    the call count, not pytest.raises -- the same reasoning
    test_zillow_bulk_retry.py uses for this identical call shape."""
    fake = _AlwaysRaises(PatchrightError("net::ERR_CONNECTION_RESET"))
    monkeypatch.setattr(StealthyFetcher, "async_fetch", fake.async_fetch)

    rows = asyncio.run(zc._fetch_rows())

    assert fake.calls == 3   # stop_after_attempt(3), then genuinely gives up
    assert rows == []        # swallowed by the pre-existing outer bare except


def test_a_non_transport_type_error_is_not_retried(monkeypatch):
    """A real, non-transport failure must fail immediately on attempt 1, not be
    mistaken for a transient condition and retried 3 times. This is a real
    raise path in the wrapped library itself (StealthyFetcher.async_fetch's own
    `selector_config` type-check in scrapling/fetchers/stealth_chrome.py), not a
    contrived example -- the closest analogue this browser-automation call
    shape has to "a real bad HTTP status" in the httpx-shaped version of this
    same proven pattern, since there is no HTTP status code at this call site."""
    fake = _AlwaysRaises(TypeError("Argument `selector_config` must be a dictionary."))
    monkeypatch.setattr(StealthyFetcher, "async_fetch", fake.async_fetch)

    rows = asyncio.run(zc._fetch_rows())

    assert fake.calls == 1   # not in the retry tuple -- fails on the first attempt
    assert rows == []


def test_scraplings_own_runtime_error_is_not_retried(monkeypatch):
    """Scrapling's AsyncStealthySession itself raises a plain RuntimeError (e.g.
    "Failed to get response for {url}") when page.goto() succeeds without
    raising but returns no response -- a real, scrapling-internal invariant
    failure, not a patchright transport/timeout error. Deliberately left out of
    the retry tuple: retrying on an unqualified RuntimeError would also catch
    unrelated scrapling state-machine errors (e.g. "Session has been already
    started") that a retry can never fix. Same reasoning and exception type as
    test_zillow_bulk_retry.py's equivalent check for this call shape."""
    fake = _AlwaysRaises(RuntimeError(f"Failed to get response for {zc.LISTINGS_URL}"))
    monkeypatch.setattr(StealthyFetcher, "async_fetch", fake.async_fetch)

    rows = asyncio.run(zc._fetch_rows())

    assert fake.calls == 1   # not retried -- fails on the very first attempt
    assert rows == []
