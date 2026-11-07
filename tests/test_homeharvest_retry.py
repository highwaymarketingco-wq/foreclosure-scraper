"""scrapers.national.homeharvest._scrape_one_county: a transient transport/timeout
error from HomeHarvest's own scrape_property() gets retried, not treated as "no
foreclosures in this county this run."

Confirmed 2026-11-07 (bug-shape sweep): scrape_property() hits Realtor.com's GraphQL
API via plain `requests` under the hood (installed homeharvest package,
core/scrapers/realtor/__init__.py: general_search() -> _graphql_post() ->
requests.post(), no timeout set). Only homeharvest's own handle_location() retries
internally (its own @retry decorator); the actual listing search (general_search(),
used on every page) does not, so a requests.exceptions.ConnectionError/Timeout from
one blip propagates straight up through scrape_property() uncaught. The bare
try/except around this call in homeharvest.py logged at debug level and moved on
with zero retry attempts -- the same root cause already fixed tonight for the Column
legal-notice API scraper, spartan_weekly_legals.py, and arcgis_webmap.query_features().

_scrape_one_county is a plain sync function run in a ThreadPoolExecutor (not native
asyncio), so the fix uses tenacity's sync Retrying rather than AsyncRetrying, and the
retry predicate is requests.exceptions.ConnectionError/Timeout (verified above against
the installed homeharvest package's actual HTTP stack) plus the builtin TimeoutError,
not httpx's exception classes.

Modeled on tests/test_arcgis_webmap_query_features_retry.py (same proven shape/fixture
style), adapted because this call site has no single return value to hand back across
an await boundary -- it is two independent per-listing_type retry loops inside one
function that keeps its own existing per-item try/except (deliberately unchanged: it
is the thing that already isolates one county's blast radius, per the investigation),
so "raises after the retry budget is exhausted" is observed via the real exception
reaching that existing except (captured through the debug log) rather than via
pytest.raises at the top, which only applies where no such enclosing catch exists.
"""
from __future__ import annotations

import sys

import pytest
import requests
from tenacity import wait_exponential_jitter

from foreclosure_scraper.scrapers.national import homeharvest as hh


class _FlakyHomeHarvest:
    """Fake `homeharvest` module: scrape_property() raises `exc` on the first
    `fail_times` calls for a given listing_type, then returns a real (None,
    terminal) result -- mirrors scrape_property() handing back an empty/no-match
    DataFrame. Tracks calls per listing_type since for_sale and pending each run
    their own independent retry loop in _scrape_one_county.
    """

    def __init__(self, fail_times: int, exc=None):
        self.fail_times = fail_times
        self.exc = exc or requests.exceptions.ConnectTimeout("boom")
        self.calls: dict[str, int] = {}

    def scrape_property(self, location, listing_type, foreclosure, past_days=None):
        n = self.calls.get(listing_type, 0) + 1
        self.calls[listing_type] = n
        if n <= self.fail_times:
            raise self.exc
        return None


class _AlwaysBadStatusHomeHarvest:
    """Fake `homeharvest` module: scrape_property() always raises a real,
    non-transport failure -- simulates the AuthenticationError homeharvest itself
    raises on a genuine 403 (core/scrapers/realtor/__init__.py's _graphql_post),
    not a network blip. Must never be retried.
    """

    def __init__(self):
        self.calls: dict[str, int] = {}

    def scrape_property(self, location, listing_type, foreclosure, past_days=None):
        self.calls[listing_type] = self.calls.get(listing_type, 0) + 1
        raise RuntimeError("HTTP 403 Forbidden (real auth failure, not a transport blip)")


def _install_fake_homeharvest(monkeypatch, fake):
    monkeypatch.setitem(sys.modules, "homeharvest", fake)


@pytest.fixture(autouse=True)
def _fast_backoff(monkeypatch):
    monkeypatch.setattr(hh, "wait_exponential_jitter",
                        lambda **kw: wait_exponential_jitter(initial=0.001, max=0.002))


def test_a_transient_connect_timeout_is_retried_and_then_succeeds(monkeypatch):
    fake = _FlakyHomeHarvest(fail_times=2)
    _install_fake_homeharvest(monkeypatch, fake)

    result = hh._scrape_one_county("Rutherfordton", "NC", "Rutherford")

    assert result == []  # fake's successful attempt returns None (no matches)
    # 2 failures + 1 success == exactly stop_after_attempt(3)'s budget, per
    # listing_type -- before the fix this would have been 1 (zero retries).
    assert fake.calls["for_sale"] == 3
    assert fake.calls["pending"] == 3


def test_a_read_timeout_is_also_retried(monkeypatch):
    fake = _FlakyHomeHarvest(fail_times=1, exc=requests.exceptions.ReadTimeout("slow"))
    _install_fake_homeharvest(monkeypatch, fake)

    result = hh._scrape_one_county("Rutherfordton", "NC", "Rutherford")

    assert result == []
    assert fake.calls["for_sale"] == 2
    assert fake.calls["pending"] == 2


def test_a_connect_timeout_that_never_clears_still_raises_after_budget_not_hang(monkeypatch):
    fake = _FlakyHomeHarvest(fail_times=99)  # never clears within the retry budget
    _install_fake_homeharvest(monkeypatch, fake)
    debug_calls = []
    monkeypatch.setattr(hh.log, "debug", lambda *a, **kw: debug_calls.append((a, kw)))

    result = hh._scrape_one_county("Rutherfordton", "NC", "Rutherford")

    # stop_after_attempt(3): exactly 3 tries per listing_type, never more --
    # proves the retry loop is bounded (not an infinite retry/hang) and that it
    # really did retry at all (before the fix this would have been exactly 1).
    assert fake.calls["for_sale"] == 3
    assert fake.calls["pending"] == 3
    # reraise=True: the real ConnectTimeout -- not a RetryError, not silently
    # dropped inside the retry construct -- is what finally reaches this file's
    # own existing (unchanged) per-listing_type `except Exception`, proving the
    # exception genuinely propagated out of the retry block after exhausting it.
    assert len(debug_calls) == 2  # one per listing_type (for_sale, pending)
    for _args, kw in debug_calls:
        assert kw.get("type") in ("for_sale", "pending")
        assert "boom" in kw.get("error", "")
    # Per-item isolation (pre-existing, untouched by this fix) still holds: one
    # county's exhausted retries don't raise out of _scrape_one_county itself.
    assert result == []


def test_a_bare_timeouterror_is_also_retried(monkeypatch):
    fake = _FlakyHomeHarvest(fail_times=1, exc=TimeoutError("socket timed out"))
    _install_fake_homeharvest(monkeypatch, fake)

    result = hh._scrape_one_county("Rutherfordton", "NC", "Rutherford")

    assert result == []
    assert fake.calls["for_sale"] == 2
    assert fake.calls["pending"] == 2


def test_a_real_non_transport_error_is_not_retried(monkeypatch):
    fake = _AlwaysBadStatusHomeHarvest()
    _install_fake_homeharvest(monkeypatch, fake)
    debug_calls = []
    monkeypatch.setattr(hh.log, "debug", lambda *a, **kw: debug_calls.append((a, kw)))

    result = hh._scrape_one_county("Rutherfordton", "NC", "Rutherford")

    # A real bad-status/auth failure is not a transport/timeout error -- fails
    # immediately on attempt 1 for each listing_type, no retries wasted on a
    # permanent failure.
    assert fake.calls["for_sale"] == 1
    assert fake.calls["pending"] == 1
    assert len(debug_calls) == 2
    for _args, kw in debug_calls:
        assert "403" in kw.get("error", "")
    assert result == []
