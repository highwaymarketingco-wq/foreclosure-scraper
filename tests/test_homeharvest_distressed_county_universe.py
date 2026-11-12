"""national.distressed (homeharvest_distressed.py) county-universe fix (2026-10-03).

Audit finding: ``DistressedListings.fetch()`` built its HomeHarvest for_sale
pull by looping ``config.ALL_COUNTIES`` -- the 18-county (11 NC + 7 SC) FLIP
footprint from a 2026-05 scoping decision -- querying each county by its SEAT
TOWN. Most of this scraper's output is NOT a flip: distress-keyword matches
land on TAX_SALE / LIS_PENDENS / DISTRESSED (not in main._FLIP_LISTING_TYPES),
all of which are distressed-type leads admissible in any real NC/SC county
per config.in_scope_distressed's 2026-09-15 mandate. Looping only the 18
footprint seats meant every one of those non-flip matches outside the
footprint could never even be fetched, no matter how permissive the
downstream scope gate is -- the same bug class enrichment_comps.py's c3edea94
fix closed.

Live-verified 2026-10-03 against the real HomeHarvest for_sale feed, querying
by county (not seat town): Catawba NC 34 distress matches / 1,091 for_sale,
Mecklenburg NC 170 / 5,231, Richland SC 114 / 2,318 -- all counties the old
18-county seat-town loop could never reach.

Fix: loop every real NC/SC county (validation.py, COUNTY_UNIVERSE) and query
"<County> County, <ST>" (``_distress_location``), the format the comps fix
proved resolves the whole county. These tests mock the network-calling
``_scrape_county`` so they run offline and fast.
"""
from __future__ import annotations

import asyncio

from foreclosure_scraper.scrapers.national import homeharvest_distressed as hd
from foreclosure_scraper.validation import NC_COUNTIES, SC_COUNTIES


def test_distress_location_is_county_not_seat():
    assert hd._distress_location("Catawba", "NC") == "Catawba County, NC"
    assert hd._distress_location("Richland", "SC") == "Richland County, SC"


def test_county_universe_covers_every_real_nc_sc_county():
    """Widened 2026-10-03 from the 18-county (11 NC + 7 SC) flip footprint to
    every real NC/SC county."""
    nc = {c for state, c in hd.COUNTY_UNIVERSE if state == "NC"}
    sc = {c for state, c in hd.COUNTY_UNIVERSE if state == "SC"}
    assert nc == set(NC_COUNTIES)
    assert sc == set(SC_COUNTIES)
    assert len(hd.COUNTY_UNIVERSE) == 146


def test_county_universe_includes_the_old_18_county_footprint():
    """The widen must not drop the original footprint counties."""
    old_footprint = {
        ("SC", "Spartanburg"), ("SC", "Anderson"), ("SC", "Pickens"),
        ("SC", "Oconee"), ("SC", "Cherokee"), ("SC", "Union"), ("SC", "Laurens"),
        ("NC", "Rutherford"), ("NC", "Cleveland"), ("NC", "Henderson"),
        ("NC", "Polk"), ("NC", "Gaston"), ("NC", "Buncombe"),
        ("NC", "Transylvania"), ("NC", "McDowell"), ("NC", "Lincoln"),
        ("NC", "Mitchell"), ("NC", "Burke"),
    }
    assert old_footprint <= set(hd.COUNTY_UNIVERSE)


def test_county_universe_includes_counties_outside_the_old_footprint():
    """Catawba/Mecklenburg NC and Richland SC are real counties the old
    18-county seat-town loop could never reach -- live-verified above that
    real distress matches exist for all three."""
    assert ("NC", "Catawba") in hd.COUNTY_UNIVERSE
    assert ("NC", "Mecklenburg") in hd.COUNTY_UNIVERSE
    assert ("SC", "Richland") in hd.COUNTY_UNIVERSE


def test_fetch_queries_every_county_in_the_universe_not_just_18(monkeypatch):
    calls: list[tuple[str, str]] = []

    def fake_scrape(state, county):
        calls.append((state, county))
        return []

    monkeypatch.setattr(hd, "_scrape_county", fake_scrape)

    scraper = hd.DistressedListings()
    asyncio.run(scraper.fetch())

    assert len(calls) == len(hd.COUNTY_UNIVERSE) == 146
    assert ("NC", "Catawba") in calls
    assert ("SC", "Richland") in calls


def test_fetch_dedupes_by_url_across_counties(monkeypatch):
    from datetime import datetime

    from foreclosure_scraper.models import Listing, ListingType, PropertyKind

    def fake_scrape(state, county):
        return [
            Listing(
                source="national.distressed", source_url="http://example.test/dupe",
                listing_type=ListingType.DISTRESSED, property_kind=PropertyKind.SINGLE_FAMILY,
                state=state, county=county,
                first_seen=datetime.utcnow(), last_seen=datetime.utcnow(),
            )
        ]

    monkeypatch.setattr(hd, "_scrape_county", fake_scrape)

    scraper = hd.DistressedListings()
    rows = asyncio.run(scraper.fetch())

    assert len(rows) == 1, "146 counties returning the same URL must dedupe to one row"
