"""homeharvest_distressed._scrape_county: a transient transport/timeout error
from the underlying homeharvest.scrape_property() call gets retried, not
treated as "this county's whole scrape failed."

Confirmed 2026-11-07 by reading the installed homeharvest package source:
scrape_property() -> RealtorScraper.search() -> general_search() ->
_graphql_post() -> a bare requests.post(), with zero retry/try-except
anywhere in that chain for the first page or any paginated page (only
handle_location() carries @retry, and get_bulk_prop_details()'s @retry is
dead code here since homeharvest.core.scrapers.Scraper.__init__ hardcodes
extra_property_data=False). The only thing wrapping that chain in this
project's own file was `except Exception as exc: log.debug(...)` inside
_scrape_county -- a catch-and-log-and-give-up, not a retry, and logged only
at debug so a zeroed county was easy to miss. Same bug shape already fixed
tonight for the Column legal-notice API scraper, spartan_weekly_legals.py,
and arcgis_webmap.query_features().

_scrape_county has no injectable http client -- it does
``from homeharvest import scrape_property`` fresh on every call, so these
tests monkeypatch the attribute on the real ``homeharvest`` module (picked
up by that fresh import at call time) rather than passing a fake client in.

Note on what "raises" means here: _scrape_county's OWN outer
`except Exception` (pre-existing, unrelated to this fix, and explicitly
out of scope to change -- see fetch()'s matching per-county isolation) means
no exception ever reaches this function's caller, by design, whether the
retry budget is exhausted or not. That was already true before this fix for
any unretried exception. So "exhausted after the retry budget, not an
infinite hang" is proven here the same way retry correctness is proven in
every other test below: by the exact call count the mocked scrape_property
sees, plus (for the exhaustion case) a wall-clock bound -- not by asserting
a raise through a boundary that was never going to raise.
"""
from __future__ import annotations

import time

import homeharvest
import pandas as pd
import pytest
from homeharvest.exceptions import AuthenticationError
from requests.exceptions import ConnectionError as RequestsConnectionError
from requests.exceptions import Timeout as RequestsTimeout
from tenacity import wait_exponential_jitter

from foreclosure_scraper.scrapers.national import homeharvest_distressed as hd

STATE = "NC"
COUNTY = "Mecklenburg"


def _distressed_row() -> dict:
    """A minimal row shaped like a real homeharvest for_sale row that matches
    DISTRESS_KEYWORDS and carries a property_url -- so _to_listing actually
    produces a Listing, proving df.iterrows() was reached for real (i.e. the
    retry succeeded) rather than the exception having been swallowed."""
    return {
        "property_url": "https://www.realtor.com/x/retry-test-1",
        "text": "Estate sale, as-is condition, motivated seller",
        "style": "single_family",
        "street": "1 Test St",
        "city": "Charlotte",
        "state": "NC",
        "zip_code": "28202",
        "list_price": 150000,
    }


def _real_df() -> pd.DataFrame:
    return pd.DataFrame([_distressed_row()])


def _empty_df() -> pd.DataFrame:
    return pd.DataFrame()


class _FlakyScrapeProperty:
    """Raises on the first N calls, then serves a real (non-empty, terminal) result."""

    def __init__(self, fail_times: int, exc=None, final_df: pd.DataFrame | None = None):
        self.fail_times = fail_times
        self.exc = exc or RequestsConnectionError("boom")
        self.final_df = final_df if final_df is not None else _real_df()
        self.calls = 0

    def __call__(self, *, location, listing_type, **kw):
        self.calls += 1
        if self.calls <= self.fail_times:
            raise self.exc
        return self.final_df


@pytest.fixture(autouse=True)
def _fast_backoff(monkeypatch):
    # Same pattern as tests/test_arcgis_webmap_query_features_retry.py: patch the
    # module-level name _scrape_county's Retrying(...) resolves at call time, so
    # the test doesn't actually wait out exponential backoff.
    monkeypatch.setattr(hd, "wait_exponential_jitter",
                        lambda **kw: wait_exponential_jitter(initial=0.001, max=0.002))


def test_a_transient_connection_error_is_retried_and_then_succeeds(monkeypatch):
    fake = _FlakyScrapeProperty(fail_times=2)
    monkeypatch.setattr(homeharvest, "scrape_property", fake)

    rows = hd._scrape_county(STATE, COUNTY)

    assert fake.calls == 3  # 2 failures + 1 success
    assert len(rows) == 1
    assert rows[0].source_url == "https://www.realtor.com/x/retry-test-1"


def test_a_read_timeout_is_also_retried_and_then_succeeds(monkeypatch):
    fake = _FlakyScrapeProperty(fail_times=1, exc=RequestsTimeout("slow"))
    monkeypatch.setattr(homeharvest, "scrape_property", fake)

    rows = hd._scrape_county(STATE, COUNTY)

    assert fake.calls == 2
    assert len(rows) == 1


def test_a_connection_error_that_never_clears_still_exhausts_not_hangs(monkeypatch):
    fake = _FlakyScrapeProperty(fail_times=99)  # never clears
    monkeypatch.setattr(homeharvest, "scrape_property", fake)

    started = time.monotonic()
    rows = hd._scrape_county(STATE, COUNTY)
    elapsed = time.monotonic() - started

    assert fake.calls == 3  # stop_after_attempt(3) honored -- not an infinite retry loop
    assert elapsed < 2.0  # fast-backoff fixture + a real stop: this returns almost immediately,
    # not after real exponential delays (1 + 2 + 4...8s) and never hangs forever.
    # The exhausted exception is then caught by _scrape_county's own pre-existing
    # `except Exception` (unchanged by this fix) -- same fail-soft contract a
    # permanently-failing, unretried call already had before this fix.
    assert rows == []


def test_a_real_authentication_error_is_not_retried(monkeypatch):
    """homeharvest's own real-403/bad-auth signal -- the task's "never retry a
    genuine bad status" case for this file. Must fail on attempt 1."""
    calls = {"n": 0}

    def _bad_auth(*, location, listing_type, **kw):
        calls["n"] += 1
        raise AuthenticationError("Received 403 Forbidden from Realtor.com API.", response=None)

    monkeypatch.setattr(homeharvest, "scrape_property", _bad_auth)

    rows = hd._scrape_county(STATE, COUNTY)

    assert calls["n"] == 1  # a real auth/bad-status error is not a transport/timeout error
    assert rows == []


def test_an_unrelated_error_is_also_not_retried(monkeypatch):
    """Belt-and-suspenders on "retrying ONLY transport/timeout errors": a
    plain, unrelated exception (standing in for a malformed-response /
    HTTP-200-with-error-body style failure deep in homeharvest's own parsing)
    must not be mistaken for a transient transport blip either."""
    calls = {"n": 0}

    def _bad_parse(*, location, listing_type, **kw):
        calls["n"] += 1
        raise ValueError("unexpected homeharvest response shape")

    monkeypatch.setattr(homeharvest, "scrape_property", _bad_parse)

    rows = hd._scrape_county(STATE, COUNTY)

    assert calls["n"] == 1
    assert rows == []
