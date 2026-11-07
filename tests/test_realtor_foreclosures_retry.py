"""realtor_foreclosures._scrape_location: a transient transport/timeout error on the
underlying homeharvest.scrape_property() call gets retried, not treated as "this
location's whole scrape failed."

Found 2026-11-07: this file's only network call is third-party
homeharvest.scrape_property(), called once per SEARCH_LOCATIONS entry inside a bare
`try: df = scrape_property(...) except Exception: continue`. Reading homeharvest's
own source (installed in this repo's own .venv) shows two of its three network
methods already retry internally via tenacity (handle_location,
get_bulk_prop_details) -- but the one that actually returns the foreclosure
listings, general_search()'s own self._graphql_post() -> requests.post() to
realtor.com's GraphQL endpoint, has neither a @retry decorator nor a try/except
anywhere inside homeharvest itself. A single transient connection reset or timeout
there used to propagate straight through scrape_property() into this file's bare
except, silently zeroing that location's results for the run with zero retries --
the exact same root cause already fixed tonight for the Column legal-notice API
scraper, spartan_weekly_legals.py, and arcgis_webmap.query_features().

homeharvest calls `requests`, not httpx (requests is a hard dependency of the
homeharvest package itself, confirmed via its own dist-info METADATA), and
scrape_property() runs synchronously inside a ThreadPoolExecutor worker here (see
fetch()), not as an awaited coroutine -- so the fix uses tenacity's sync Retrying,
not AsyncRetrying, and retries only requests' own transient transport/timeout
exceptions (ConnectionError / Timeout / ChunkedEncodingError), never a real bad
HTTP status or auth failure.

homeharvest.scrape_property is imported freshly inside _scrape_location on every
call (`from homeharvest import scrape_property`), so what actually takes effect is
monkeypatching the attribute on the real `homeharvest` module -- there is no
module-level `m.scrape_property` name in realtor_foreclosures.py to patch instead.
"""
from __future__ import annotations

import homeharvest
import pytest
import requests
from tenacity import wait_exponential_jitter

from foreclosure_scraper.scrapers.national import realtor_foreclosures as m

LOCATION = "Horry County, SC"
SLUG = "national.realtor_foreclosures"


class _FlakyScrapeProperty:
    """Raises on the first N calls, then returns a real (empty, terminal) result."""

    def __init__(self, fail_times: int, exc: Exception | None = None):
        self.fail_times = fail_times
        self.exc = exc or requests.exceptions.ConnectionError("boom")
        self.calls = 0

    def __call__(self, **kwargs):
        self.calls += 1
        if self.calls <= self.fail_times:
            raise self.exc
        # scrape_property's real return is a pandas DataFrame; _scrape_location's
        # own `if df is None or len(df) == 0: continue` already treats None as the
        # terminal "no rows" case, so a fake has no need to construct a real
        # DataFrame just to prove the retry/success boundary.
        return None


class _BoomScrapeProperty:
    """Always raises the given (non-transient) exception, counting calls."""

    def __init__(self, exc: Exception):
        self.exc = exc
        self.calls = 0

    def __call__(self, **kwargs):
        self.calls += 1
        raise self.exc


@pytest.fixture(autouse=True)
def _fast_backoff(monkeypatch):
    monkeypatch.setattr(m, "wait_exponential_jitter",
                        lambda **kw: wait_exponential_jitter(initial=0.001, max=0.002))


def test_a_transient_connection_error_is_retried_and_then_succeeds(monkeypatch):
    fake = _FlakyScrapeProperty(fail_times=2)
    monkeypatch.setattr(homeharvest, "scrape_property", fake)
    out = m._scrape_location(LOCATION, SLUG)
    assert fake.calls == 3
    assert out == []


def test_a_timeout_is_also_retried(monkeypatch):
    fake = _FlakyScrapeProperty(fail_times=1, exc=requests.exceptions.Timeout("slow"))
    monkeypatch.setattr(homeharvest, "scrape_property", fake)
    out = m._scrape_location(LOCATION, SLUG)
    assert fake.calls == 2
    assert out == []


def test_a_chunked_encoding_error_is_also_retried(monkeypatch):
    fake = _FlakyScrapeProperty(
        fail_times=1, exc=requests.exceptions.ChunkedEncodingError("cut off"))
    monkeypatch.setattr(homeharvest, "scrape_property", fake)
    out = m._scrape_location(LOCATION, SLUG)
    assert fake.calls == 2
    assert out == []


def test_a_connection_error_that_never_clears_stops_after_3_attempts_not_hangs(monkeypatch):
    """Proves stop_after_attempt(3) is really wired up: if retry coverage were
    missing (or the exception type didn't match retry_if_exception_type, so
    nothing ever retried), this would see calls == 1; if the retry budget never
    stopped, this would spin far past 3 calls or hang the test. It does neither --
    it stops at exactly 3 and _scrape_location returns gracefully, because the
    existing, UNCHANGED per-location `except Exception: continue` still swallows
    the exhausted retry's reraised error, exactly as it swallowed the original
    unretried error before this fix. The only behavior change is that it now
    takes 3 real attempts (with backoff) before giving up, instead of 1."""
    fake = _FlakyScrapeProperty(fail_times=99)
    monkeypatch.setattr(homeharvest, "scrape_property", fake)
    out = m._scrape_location(LOCATION, SLUG)
    assert fake.calls == 3   # stop_after_attempt(3), then gives up -- not an infinite retry/hang
    assert out == []         # existing except Exception: continue still applies, unchanged


def test_a_real_non_transport_error_is_not_retried(monkeypatch):
    """A genuine bug (bad kwarg, parsing error, etc.) must fail on attempt 1, not
    burn 3 attempts and real backoff time on something retrying will never fix."""
    fake = _BoomScrapeProperty(ValueError("not a transport error"))
    monkeypatch.setattr(homeharvest, "scrape_property", fake)
    out = m._scrape_location(LOCATION, SLUG)
    assert fake.calls == 1    # a real bug is not a transport/timeout error -- no retry
    assert out == []          # still silently skipped by the existing except Exception:
                               # continue, exactly as before this fix


def test_homeharvest_authentication_error_is_not_retried(monkeypatch):
    """homeharvest itself raises its own AuthenticationError (not a requests.exceptions
    subclass) on a real 403 from realtor.com -- confirm that real, specifically-named
    failure mode is not mistaken for a transient network blip either."""
    fake = _BoomScrapeProperty(
        homeharvest.exceptions.AuthenticationError("403 from realtor.com", response=None))
    monkeypatch.setattr(homeharvest, "scrape_property", fake)
    out = m._scrape_location(LOCATION, SLUG)
    assert fake.calls == 1
    assert out == []


def test_successful_first_attempt_is_not_retried_at_all(monkeypatch):
    """Sanity check the other direction: the happy path still makes exactly one
    call, so the retry wrapper adds no overhead when nothing ever fails."""
    fake = _FlakyScrapeProperty(fail_times=0)
    monkeypatch.setattr(homeharvest, "scrape_property", fake)
    out = m._scrape_location(LOCATION, SLUG)
    assert fake.calls == 1
    assert out == []
