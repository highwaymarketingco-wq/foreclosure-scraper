"""enrich_with_images' name+city rescue (Pass 1) must not trust a resolved point that turns out
to be shared by other leads too -- the same fallback rule block_binding.py applies everywhere
else (audit 2026-10-18, block-binding-family-photo). Every owner, address and point here is made
up."""
from __future__ import annotations

import asyncio
from datetime import datetime

from foreclosure_scraper import enrichment_images as eimg
from foreclosure_scraper.models import Listing, ListingType, PropertyKind

NOW = datetime(2026, 10, 18)


def _li(owner="SAMPLE ESTATES LLC", city="Sampleton", state="NC", source_url="https://x.invalid/1"):
    return Listing(source="counties_nc.nc_ecourts_lis_pendens", source_url=source_url,
                   listing_type=ListingType.LIS_PENDENS, property_kind=PropertyKind.UNKNOWN,
                   state=state, county="Sample", owner_name=owner, city=city,
                   first_seen=NOW, last_seen=NOW, raw={})


def test_eight_leads_rescued_to_the_same_point_get_no_aerial(monkeypatch):
    # block_binding.FALLBACK_POINT_MIN_ROWS: a point 8+ rows share is a fallback, same as a
    # county seat -- two unrelated nc_ecourts_lis_pendens filings with no name/city distinction
    # of their own all land here when the name+city geocode degrades the same way for each.
    shared_pt = (33.9, -78.0)

    async def _fake_geocode(c, li, delay):
        return shared_pt, False
    monkeypatch.setattr(eimg, "_geocode_named_complex", _fake_geocode)

    rows = [_li(owner="SAMPLE ESTATES LLC", source_url=f"https://x.invalid/{n}") for n in range(8)]
    asyncio.run(eimg.enrich_with_images(rows, use_mapillary=False))

    for li in rows:
        assert li.latitude == shared_pt[0] and li.longitude == shared_pt[1]
        assert "aerial" not in li.raw.get("images", {})


def test_a_single_rescued_lead_still_gets_its_aerial(monkeypatch):
    async def _fake_geocode(c, li, delay):
        return (33.9, -78.0), False
    monkeypatch.setattr(eimg, "_geocode_named_complex", _fake_geocode)

    li = _li()
    asyncio.run(eimg.enrich_with_images([li], use_mapillary=False))

    assert "aerial" in li.raw.get("images", {})
