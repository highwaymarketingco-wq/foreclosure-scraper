"""Comps county-universe fix (2026-10-03).

Audit finding: `enrichment_comps.enrich_with_comps()` built its HomeHarvest
sold/rent pools by looping `config.ALL_COUNTIES` -- an 18-county "flip only"
corridor (7 SC + 11 NC, see config.py's history comments) -- even though the
board carries leads from all 146 real NC+SC counties (config.py's
`in_scope_distressed` docstring: "if its a flip, its only in the counties we
talked about. if its a distressed property its anywhere in nc and sc",
2026-09-15). Any listing whose county wasn't one of the 18 could never get a
sold pool, so `raw['comps']`/`raw['comps_tight']` were structurally capped at
~18/148 counties no matter how much distressed-lead coverage grew elsewhere.

Live-verified (2026-10-03) that this is a real breadth bug, not a paid/walled
MLS wall: HomeHarvest resolves "<County> County, <ST>" for counties outside
the 18, e.g. Catawba NC (1,858 sold/180d) and Greenville SC (5,763), down to
rural Allendale SC (20) -- and the county-level query even beats the old
seat-town query for the ORIGINAL 18 (Spartanburg SC: 5,935 vs 1,747).

Fix: the county universe for a given `enrich_with_comps()` call is now the
distinct, validated (state, county) pairs actually present in the `listings`
argument (checked against the full 146-county NC+SC register via
`config.in_scope_distressed`), not the frozen 18-county list -- so a batch
touching Catawba NC gets a Catawba pool built, which it could never do
before. These tests mock the network-calling pool functions so they run
offline and fast.
"""
from __future__ import annotations

import asyncio
from datetime import datetime

from foreclosure_scraper import enrichment_comps as ec
from foreclosure_scraper.models import Listing, ListingType, PropertyKind


def _listing(state, county, **kw):
    base = dict(
        source="t", source_url="x", listing_type=ListingType.FORECLOSURE_SALE,
        property_kind=PropertyKind.SINGLE_FAMILY, state=state, county=county,
        living_sqft=1500, bedrooms=3,
        first_seen=datetime.utcnow(), last_seen=datetime.utcnow(),
    )
    base.update(kw)
    return Listing(**base)


def test_comp_location_is_county_not_seat():
    # The fix: query by county, not by a seat-town gazetteer that doesn't
    # exist for 128 of the 146 real NC+SC counties.
    assert ec._comp_location("Catawba", "NC") == "Catawba County, NC"
    assert ec._comp_location("Greenville", "SC") == "Greenville County, SC"


def test_pool_fetch_covers_a_county_outside_the_old_18(monkeypatch):
    """Catawba NC is not in config.ALL_COUNTIES (the old 18-county loop
    bound) -- confirm enrich_with_comps now still builds a pool for it."""
    calls: list[tuple[str, str]] = []

    def fake_sold(county, state):
        calls.append((state, county))
        return []

    def fake_rent(county, state):
        return []

    def fake_active(county, state):
        return 0

    monkeypatch.setattr(ec, "_sold_pool_for_seat", fake_sold)
    monkeypatch.setattr(ec, "_rent_pool_for_seat", fake_rent)
    monkeypatch.setattr(ec, "_active_count_for_seat", fake_active)

    listings = [_listing("NC", "Catawba"), _listing("SC", "Greenville")]
    asyncio.run(ec.enrich_with_comps(listings))

    assert ("NC", "Catawba") in calls
    assert ("SC", "Greenville") in calls
    # Exactly the 2 distinct counties present -- not a sweep of all 146 and
    # not the old frozen 18.
    assert len(calls) == 2


def test_invalid_or_out_of_scope_county_triggers_no_fetch(monkeypatch):
    calls: list[tuple[str, str]] = []
    monkeypatch.setattr(ec, "_sold_pool_for_seat", lambda c, s: (calls.append((s, c)), [])[1])
    monkeypatch.setattr(ec, "_rent_pool_for_seat", lambda c, s: [])
    monkeypatch.setattr(ec, "_active_count_for_seat", lambda c, s: 0)

    # "Nonexistent" isn't a real NC county; a bare state with no county must
    # also be skipped cleanly (no crash, no network call).
    listings = [_listing("NC", "Nonexistent"), _listing("NC", None)]
    asyncio.run(ec.enrich_with_comps(listings))

    assert calls == []


def test_comps_attach_for_a_county_outside_the_old_18(monkeypatch):
    """End-to-end: a Catawba NC listing (never reachable under the old
    18-county loop) gets matched against a mocked Catawba sold pool."""
    sold_record = dict(
        street="1 Hickory Ln", city="Hickory", state="NC", zip_code="28601",
        sold_price=250000, sqft=1500, beds=3, full_baths=2,
        year_built=2005, lot_sqft=8000, last_sold_date="2026-05-01",
        style="Single Family", property_url="http://example.test/1",
    )

    monkeypatch.setattr(ec, "_sold_pool_for_seat", lambda c, s: [dict(sold_record)])
    monkeypatch.setattr(ec, "_rent_pool_for_seat", lambda c, s: [])
    monkeypatch.setattr(ec, "_active_count_for_seat", lambda c, s: 5)

    subj = _listing("NC", "Catawba", zip_code="28601")
    asyncio.run(ec.enrich_with_comps([subj]))

    assert isinstance(subj.raw, dict)
    assert subj.raw.get("comps"), "expected a matched comp from the Catawba pool"
    assert subj.raw["comps"][0]["address"] == "1 Hickory Ln"


def test_county_casing_is_normalized_for_the_pool_key(monkeypatch):
    """li.county may arrive as 'MCDOWELL' (GIS all-caps); the pool is built
    under the canonical key and the per-row lookup must still hit it."""
    sold_record = dict(
        street="2 Marion Rd", city="Marion", state="NC", zip_code="28752",
        sold_price=180000, sqft=1400, beds=3, full_baths=2,
        year_built=1995, lot_sqft=9000, last_sold_date="2026-04-01",
        style="Single Family", property_url="http://example.test/2",
    )
    seen_keys: list[tuple[str, str]] = []

    def fake_sold(county, state):
        seen_keys.append((state, county))
        return [dict(sold_record)]

    monkeypatch.setattr(ec, "_sold_pool_for_seat", fake_sold)
    monkeypatch.setattr(ec, "_rent_pool_for_seat", lambda c, s: [])
    monkeypatch.setattr(ec, "_active_count_for_seat", lambda c, s: 1)

    subj = _listing("NC", "MCDOWELL", zip_code="28752")
    asyncio.run(ec.enrich_with_comps([subj]))

    # The pool was fetched under the canonical name...
    assert seen_keys == [("NC", "McDowell")]
    # ...and the all-caps row still found it and got a comp attached.
    assert subj.raw.get("comps"), "normalized county key must still match the per-row lookup"
