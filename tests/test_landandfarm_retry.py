"""landandfarm._fetch_county: a transient StealthyFetcher/patchright navigation
failure on a page fetch gets retried, not treated as "the whole county failed."

Found 2026-11-07 (retry-gap audit): `_fetch_county()`'s own page-fetch loop
called `StealthyFetcher.async_fetch()` directly, wrapped only in a bare
`except Exception: ... break` -- zero retry attempts of ITS OWN. (Scrapling's
own `AsyncStealthySession.fetch()` already retries internally -- default
`retries=3`, 1s apart, on literally any Exception -- before a failure ever
reaches this file, but once THAT budget is exhausted the caller had nothing
further: one still-transient blip broke out of the page loop immediately and
abandoned every remaining page for that county for the whole run.)
`national.landandfarm` carries no sale/auction date, so it is registered in
`main.DATELESS_OK_SOURCES` -- a county zeroed by one blip gets no
fallback-date-window backfill; it just looks like a healthy "no new listings"
result until someone notices by hand.

This file's `StealthyFetcher.async_fetch()` call is a direct Scrapling/
patchright headless-browser fetch, NOT the shared http_client.py wrapper, so
the retry predicate is patchright's own Error/TimeoutError (plus bare
TimeoutError) -- never httpx's, which this call can't raise.

Note on test design: `_fetch_county()` deliberately swallows ANY exception
from its page-fetch block (logs `landandfarm.fetch_fail`, then `break`s) so
one county's failure can never block the other 25 counties in
`LandAndFarm.fetch()` -- that outer swallow is pre-existing, intentional, and
unchanged by this fix. So "retries are exhausted, then it raises" is proven
here as: the real (unwrapped-by-tenacity) exception is what reaches that
swallow -- after exactly `stop_after_attempt`'s budget, not fewer, not more,
and not an infinite retry loop -- observed via the recorded call count and
the logged error text, since `_fetch_county()` itself has no reason to let
the exception escape any further than that pre-existing handler.
"""
from __future__ import annotations

import asyncio

import pytest
from patchright.async_api import Error as PlaywrightError, TimeoutError as PlaywrightTimeoutError
from scrapling.fetchers import StealthyFetcher
from tenacity import wait_exponential_jitter

from foreclosure_scraper.scrapers.national import landandfarm

COUNTY = "testcounty"
STATE = "NC"
BASE_URL = "https://www.landandfarm.com/search/north-carolina/testcounty-county-land-for-sale/"
SLUG = "national.landandfarm"


class _FakeResult:
    """Minimal stand-in for Scrapling's Response -- _fetch_county only reads `.body`."""

    def __init__(self, body: bytes = b"<html></html>"):
        self.body = body


class _FlakyFetch:
    """Raises on the first `fail_times` calls, then serves a real (short,
    terminal) page. A short body is well under the 5000-char floor
    `_fetch_county` checks, so a successful call ends the page loop the
    same ordinary, non-exceptional way a real empty/short page would --
    the point under test is the retry, not the HTML parsing."""

    def __init__(self, fail_times: int, exc: Exception | None = None):
        self.fail_times = fail_times
        self.exc = exc or PlaywrightTimeoutError("Timeout 60000ms exceeded.")
        self.calls = 0

    async def fetch(self, url: str, **kwargs):
        self.calls += 1
        if self.calls <= self.fail_times:
            raise self.exc
        return _FakeResult()


class _RecordingLog:
    """Stand-in for the module's structlog logger: records only what
    `_fetch_county`'s own (unmodified) exception handler would log."""

    def __init__(self):
        self.warnings: list[tuple[str, dict]] = []

    def warning(self, event, **kw):
        self.warnings.append((event, kw))

    def info(self, event, **kw):
        pass

    def debug(self, event, **kw):
        pass


def _patch_async_fetch(monkeypatch, flaky: _FlakyFetch) -> None:
    """Patch the REAL `scrapling.fetchers.StealthyFetcher.async_fetch` classmethod --
    `_fetch_county` does `from scrapling.fetchers import StealthyFetcher` fresh
    on every call, so this is the only name that import can ever bind to."""

    async def _patched(cls, url, **kwargs):
        return await flaky.fetch(url, **kwargs)

    monkeypatch.setattr(StealthyFetcher, "async_fetch", classmethod(_patched))


@pytest.fixture(autouse=True)
def _fast_backoff(monkeypatch):
    """Same technique as test_arcgis_webmap_query_features_retry.py: keep the
    real exponential-jitter shape but make the waits sub-millisecond."""
    monkeypatch.setattr(
        landandfarm,
        "wait_exponential_jitter",
        lambda **kw: wait_exponential_jitter(initial=0.001, max=0.002),
    )


def test_a_transient_timeout_is_retried_and_then_succeeds(monkeypatch):
    flaky = _FlakyFetch(fail_times=2)
    _patch_async_fetch(monkeypatch, flaky)
    fake_log = _RecordingLog()
    monkeypatch.setattr(landandfarm, "log", fake_log)

    rows = asyncio.run(landandfarm._fetch_county(COUNTY, STATE, BASE_URL, SLUG))

    assert flaky.calls == 3        # 2 failures + 1 success, inside stop_after_attempt(3)
    assert rows == []              # short fake body -> ordinary end-of-page break, no exception
    assert fake_log.warnings == [] # retry absorbed it -- fetch_fail must never have logged


def test_a_connection_error_is_also_retried(monkeypatch):
    flaky = _FlakyFetch(fail_times=1, exc=PlaywrightError("net::ERR_CONNECTION_RESET"))
    _patch_async_fetch(monkeypatch, flaky)
    fake_log = _RecordingLog()
    monkeypatch.setattr(landandfarm, "log", fake_log)

    rows = asyncio.run(landandfarm._fetch_county(COUNTY, STATE, BASE_URL, SLUG))

    assert flaky.calls == 2
    assert rows == []
    assert fake_log.warnings == []


def test_a_timeout_that_never_clears_still_gives_up_after_budget_not_an_infinite_hang(monkeypatch):
    flaky = _FlakyFetch(fail_times=99)  # never clears
    _patch_async_fetch(monkeypatch, flaky)
    fake_log = _RecordingLog()
    monkeypatch.setattr(landandfarm, "log", fake_log)

    # wait_for is the literal "not an infinite hang" assertion: with the fast
    # backoff fixture this finishes in well under a second if the retry
    # budget is really bounded, and fails loudly instead of hanging if it isn't.
    rows = asyncio.run(
        asyncio.wait_for(landandfarm._fetch_county(COUNTY, STATE, BASE_URL, SLUG), timeout=5.0)
    )

    assert flaky.calls == 3   # stop_after_attempt(3), then tenacity reraises the real error
    assert rows == []         # _fetch_county's pre-existing outer except caught it and broke
    assert len(fake_log.warnings) == 1
    event, kw = fake_log.warnings[0]
    assert event == "landandfarm.fetch_fail"
    assert "Timeout 60000ms exceeded" in kw["error"]  # the REAL exception, not a tenacity RetryError
    assert kw["county"] == COUNTY
    assert kw["page"] == 1


def test_a_real_non_transient_error_is_not_retried(monkeypatch):
    flaky = _FlakyFetch(
        fail_times=99,
        exc=RuntimeError("Failed to get response for https://example.test"),
    )
    _patch_async_fetch(monkeypatch, flaky)
    fake_log = _RecordingLog()
    monkeypatch.setattr(landandfarm, "log", fake_log)

    rows = asyncio.run(landandfarm._fetch_county(COUNTY, STATE, BASE_URL, SLUG))

    assert flaky.calls == 1   # a real, non-transport failure is not a transient blip -- no retry
    assert rows == []
    assert len(fake_log.warnings) == 1
    event, kw = fake_log.warnings[0]
    assert event == "landandfarm.fetch_fail"
    assert "Failed to get response" in kw["error"]
