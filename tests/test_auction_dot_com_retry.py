"""auction_dot_com._render: a transient Scrapling/Playwright timeout on the
StealthyFetcher.async_fetch call gets retried, not treated as "give up and
silently zero this state's whole scrape."

Found 2026-11-07 (network-resilience audit): _render() is the ONLY fetch
primitive in this module -- both _fetch_state (the main per-state listing
loop) and _fetch_reo_ids (the REO cross-reference loop) call it once per
page and `break` the instant it returns "". Per the module's own docstring,
auction.com has no URL-addressable pagination and embeds a state's ENTIRE
result set on page 1, so the first _render call for a state is effectively
that state's whole scrape. The old code wrapped StealthyFetcher.async_fetch
in a bare try/except that caught literally any exception, logged a warning,
and gave up immediately with zero retry of its own -- the exact same root
cause already fixed tonight for the Column legal-notice API scraper,
spartan_weekly_legals.py, and the shared arcgis_webmap.query_features().

Unlike those httpx-backed callers, this call goes through Scrapling's
StealthyFetcher (a Playwright wrapper) and never raises httpx's exception
types, so the retry predicate here targets the real transient/timeout
exceptions this stack actually raises instead: the builtin TimeoutError
(Scrapling itself raises this directly for page-pool contention) and
Playwright's own TimeoutError (a stalled navigation/selector wait).

_render()'s own contract is -- and remains -- "never raise, return '' on
any failure" (its callers `break` on empty string, they never catch an
exception from it). So unlike query_features's tests, the "exhausted" and
"not retried" cases here are proven via call-count + empty-string return,
not via pytest.raises.
"""
from __future__ import annotations

import asyncio

import pytest
import scrapling.fetchers as scrapling_fetchers
from playwright.async_api import TimeoutError as PlaywrightTimeoutError
from tenacity import wait_exponential_jitter

from foreclosure_scraper.scrapers.national import auction_dot_com as adc

URL = "https://www.auction.com/residential/nc/"

# _render() discards anything shorter than this (its own
# `if not html or len(html) < 5000: return ""` guard) -- every fake
# "successful" body below must clear it, or a passing fetch would be
# indistinguishable from a soft too-short failure.
_BODY = "<html>" + ("x" * 6000) + "</html>"


class _FakeResult:
    """Minimal stand-in for scrapling's Response -- _render only ever reads
    `.body` off whatever StealthyFetcher.async_fetch returns."""

    def __init__(self, body: str):
        self.body = body


class _FlakyFetch:
    """Raises ``exc`` on the first ``fail_times`` calls, then returns a real
    (long-enough) body."""

    def __init__(self, fail_times: int, exc: Exception):
        self.fail_times = fail_times
        self.exc = exc
        self.calls = 0

    async def __call__(self, url, **kwargs):
        self.calls += 1
        if self.calls <= self.fail_times:
            raise self.exc
        return _FakeResult(_BODY)


class _AlwaysFails:
    """Raises ``exc`` on every call -- for both the exhausted-retry-budget
    case and the not-retried-at-all case."""

    def __init__(self, exc: Exception):
        self.exc = exc
        self.calls = 0

    async def __call__(self, url, **kwargs):
        self.calls += 1
        raise self.exc


@pytest.fixture(autouse=True)
def _fast_backoff(monkeypatch):
    monkeypatch.setattr(
        adc, "wait_exponential_jitter",
        lambda **kw: wait_exponential_jitter(initial=0.001, max=0.002),
    )


def _patch_fetch(monkeypatch, fake):
    """_render does ``from scrapling.fetchers import StealthyFetcher``
    locally on every call, so patching auction_dot_com's own namespace
    would do nothing -- patch the real StealthyFetcher class's
    ``async_fetch`` classmethod itself, which is what that local import
    resolves to."""
    monkeypatch.setattr(scrapling_fetchers.StealthyFetcher, "async_fetch", staticmethod(fake))


def test_a_transient_timeout_is_retried_and_then_succeeds(monkeypatch):
    fake = _FlakyFetch(fail_times=2, exc=TimeoutError("page pool exhausted"))
    _patch_fetch(monkeypatch, fake)
    html = asyncio.run(adc._render(URL))
    assert fake.calls == 3
    assert html == _BODY


def test_a_playwright_timeout_is_also_retried(monkeypatch):
    fake = _FlakyFetch(fail_times=1, exc=PlaywrightTimeoutError("Timeout 120000ms exceeded"))
    _patch_fetch(monkeypatch, fake)
    html = asyncio.run(adc._render(URL))
    assert fake.calls == 2
    assert html == _BODY


def test_a_timeout_that_never_clears_gives_up_after_the_retry_budget_not_a_hang(monkeypatch):
    fake = _AlwaysFails(TimeoutError("page pool exhausted"))
    _patch_fetch(monkeypatch, fake)
    html = asyncio.run(adc._render(URL))
    # stop_after_attempt(3): exactly 3 tries, then AsyncRetrying re-raises
    # the original TimeoutError -- which _render's own outer except
    # catches and converts to its normal "" give-up return. Bounded, not
    # an infinite retry loop, and never an exception escaping to the
    # caller (_render's existing never-raises contract, unchanged by this
    # fix -- _fetch_state/_fetch_reo_ids `break` on "", they don't catch).
    assert fake.calls == 3
    assert html == ""


def test_a_real_non_transient_error_is_not_retried(monkeypatch):
    # A structural Scrapling failure -- e.g. its own "Failed to get
    # response for <url>" RuntimeError when navigation doesn't yield a
    # response -- is not a transport/timeout error. It must fail on
    # attempt 1, not burn the retry budget on something a retry can never
    # fix (the closest analogue here to "a real bad HTTP status is not
    # retried", since this call has no HTTP-status concept of its own).
    fake = _AlwaysFails(RuntimeError(f"Failed to get response for {URL}"))
    _patch_fetch(monkeypatch, fake)
    html = asyncio.run(adc._render(URL))
    assert fake.calls == 1
    assert html == ""
