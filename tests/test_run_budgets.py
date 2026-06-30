"""Wall-clock budget bails on the two full-run hang sources (geocode + sold-comps).

These guard the 8.5h-hang regression: with the budget set to 0 the rate-limited /
CPU-spin loops must bail immediately and still leave the run in a valid state.
"""
from __future__ import annotations

import asyncio
from datetime import datetime

from foreclosure_scraper.models import Listing, ListingType, PropertyKind
from foreclosure_scraper import enrichment_geocode as geo
from foreclosure_scraper.enrichment_foreclosure_sold_comps import (
    enrich_foreclosure_sold_comps,
)


def _li(**kw):
    now = datetime.utcnow()
    base = dict(source="s", source_url="https://x/" + str(kw.get("source_url", "1")),
                listing_type=ListingType.FORECLOSURE_SALE,
                property_kind=PropertyKind.SINGLE_FAMILY,
                first_seen=now, last_seen=now)
    base.update({k: v for k, v in kw.items() if k != "source_url"})
    return Listing(**base)


def test_geocode_budget_zero_falls_to_centroid_no_network(monkeypatch):
    # Budget spent immediately -> fast_only -> no Census/Nominatim, county centroid.
    monkeypatch.setenv("GEOCODE_BUDGET_S", "0")
    # Hard-fail if any network geocoder is even called.
    async def _boom(*a, **k):
        raise AssertionError("network geocoder called despite spent budget")
    monkeypatch.setattr(geo, "_census_geocode", _boom)
    monkeypatch.setattr(geo, "_nominatim_geocode", _boom)

    li = _li(state="NC", county="Gaston")  # in COUNTY_SEAT_CENTROIDS
    asyncio.run(geo.enrich([li]))
    assert li.latitude is not None and li.longitude is not None  # got centroid


def test_sold_comps_budget_zero_bails_immediately():
    active = [_li(source_url=str(i), county="Buncombe", state="NC",
                  living_sqft=1500, bedrooms=3) for i in range(50)]
    pool = [_li(source_url="p" + str(i), county="Buncombe", state="NC",
                living_sqft=1500, bedrooms=3) for i in range(50)]
    import os
    os.environ["FORECLOSURE_SOLD_COMPS_BUDGET_S"] = "0"
    try:
        stats = enrich_foreclosure_sold_comps(active, pool)
    finally:
        del os.environ["FORECLOSURE_SOLD_COMPS_BUDGET_S"]
    assert stats.get("budget_hit") == 1
    assert stats["matched"] == 0  # bailed before matching any
