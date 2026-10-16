"""enrichment_cchs_rod.py: the 5-county target list rotates by day, same fix as gis_fill.py.

Live board measurement 2026-10-16 (the day this was found): Henderson 28.8% checked, Burke
8.1%, Cleveland 7.5%, Lincoln 0.04% (8 of 18,436 -- Lincoln alone outnumbers the other 4
counties COMBINED), Madison a flat 0%. _await_capped's 900s budget rarely covers every
eligible lead across all 5 counties in one run; a flat `listings`-order scan always reaches
the same counties first and never reaches the rest -- a budget-capped run must starve a
DIFFERENT county each day, not always Lincoln/Madison.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

import foreclosure_scraper.enrichment_cchs_rod as C
from foreclosure_scraper.models import Listing, ListingType


def _li(county, owner="SMITH JOHN"):
    return Listing(source="x", source_url="u", listing_type=ListingType.TAX_LIEN,
                   state="NC", county=county, owner_name=owner,
                   first_seen=datetime(2020, 1, 1), last_seen=datetime(2020, 1, 1))


class _FixedNow(datetime):
    _fixed: "datetime"

    @classmethod
    def now(cls, tz=None):
        return cls._fixed


@pytest.fixture(autouse=True)
def _no_network(monkeypatch):
    """This test is only about which county's leads are OFFERED to the search loop (via
    max_lookups, standing in for a wall-clock budget running out partway through) -- never
    let it make a real cchs.search_by_name call."""
    async def _boom(*a, **k):
        raise AssertionError("a real cchs lookup was attempted")
    monkeypatch.setattr(C.cchs, "search_by_name", _boom)
    monkeypatch.setattr(C, "is_stale", lambda *a, **k: True)


def _first_county_processed(monkeypatch, day: datetime) -> str:
    _FixedNow._fixed = day
    monkeypatch.setattr(C, "datetime", _FixedNow)
    listings = [_li(c) for c in sorted(C._COUNTIES)]   # alphabetical input order, every time

    async def _record(*a, **k):
        raise AssertionError("network call reached despite max_lookups=1")
    # max_lookups=1 stands in for "the 900s budget only covered the first lead" -- the same
    # effect a real run-time cutoff has, deterministic and fast for a unit test.
    monkeypatch.setattr(C.cchs, "search_by_name", _record)
    captured = {}

    async def _capture(*a, **k):
        captured["county"] = (a[1] if len(a) > 1 else k.get("county"))
        return []
    monkeypatch.setattr(C.cchs, "search_by_name", _capture)

    import asyncio
    asyncio.run(C.enrich_cchs_rod(listings, max_lookups=1))
    return captured["county"]


def test_the_starting_county_rotates_by_day_not_always_the_same_one(monkeypatch):
    day0 = datetime(2026, 10, 16, tzinfo=timezone.utc)
    day1 = day0 + timedelta(days=1)
    first0 = _first_county_processed(monkeypatch, day0)
    first1 = _first_county_processed(monkeypatch, day1)
    assert first0 != first1
    assert {first0, first1} <= C._COUNTIES


def test_every_county_gets_a_turn_at_the_front_across_enough_days(monkeypatch):
    day0 = datetime(2026, 10, 16, tzinfo=timezone.utc)
    seen = {_first_county_processed(monkeypatch, day0 + timedelta(days=i))
            for i in range(len(C._COUNTIES))}
    assert seen == C._COUNTIES


def test_a_single_days_targets_are_grouped_by_county_not_interleaved():
    """Within one run, a county's own leads stay together once its turn starts -- this fix
    rotates which GROUP goes first, it does not reshuffle individual leads."""
    listings = [_li("Lincoln", owner="A"), _li("Burke", owner="B"), _li("Lincoln", owner="C"),
                _li("Madison", owner="D"), _li("Lincoln", owner="E")]
    import asyncio

    class _Rec:
        calls: list = []

    async def _record(state, county, owner, max_docs=80):
        _Rec.calls.append(county)
        return []

    import foreclosure_scraper.enrichment_cchs_rod as mod
    orig = mod.cchs.search_by_name
    mod.cchs.search_by_name = _record
    try:
        mod_is_stale = mod.is_stale
        mod.is_stale = lambda *a, **k: True
        try:
            asyncio.run(mod.enrich_cchs_rod(listings))
        finally:
            mod.is_stale = mod_is_stale
    finally:
        mod.cchs.search_by_name = orig

    # Lincoln's 3 leads appear as a contiguous block among the calls, wherever that block starts.
    idxs = [i for i, c in enumerate(_Rec.calls) if c == "Lincoln"]
    assert idxs == list(range(idxs[0], idxs[0] + 3))
