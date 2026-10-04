"""national.landandfarm -- HERMES extraction-completeness audit, batch 17
(2026-10-04). No test file existed for this source before this batch.

Core finding: the 2026-10-01 audit confirmed the SEARCH-RESULTS page's
JSON-LD `offeredBy` never carries a `telephone` field. This batch found
that each listing's own DETAIL page carries a SEPARATE, richer JSON-LD
block (type RealEstateListing, @id ending "#listingdetailpage") with a
REAL `offers.seller.telephone`, the full untruncated description (the
search page truncates at ~250 chars), a real `datePosted`, and a
structured `additionalProperty` list (Acreage/Activities/Lot Description/
Present Use/Proposed Use) -- confirmed live on a real current Buncombe
listing: phone "(828) 506-8701". Also confirmed live: unlike the
search-results page (Akamai-gated, needs StealthyFetcher), the detail page
is reachable via plain curl_cffi impersonation (`get_text_impersonate`) --
no extra render cost. Wired as a best-effort, per-county-capped enrichment
(DETAIL_FETCH_CAP_PER_COUNTY) in `_fetch_county`.
"""
from __future__ import annotations

import asyncio

from foreclosure_scraper.scrapers.national.landandfarm import (
    _apply_detail_extras,
    _extract_acres,
    _extract_county,
    _fetch_detail_extras,
    _parse_detail_extras,
    _parse_item,
)
from foreclosure_scraper.models import Listing, ListingType, PropertyKind

# A trimmed-but-real detail-page JSON-LD shape, live-captured 2026-10-04
# from https://www.landandfarm.com/property/pisgah-highlands-37594929/
_DETAIL_HTML = """
<html><body>
<script type="application/ld+json">
{"@context":"https://schema.org","@type":"Residence","url":"/property/x/"}
</script>
<script type="application/ld+json">
{"@context":"https://schema.org",
 "@type":["RealEstateListing","Product"],
 "url":"https://www.landandfarm.com/property/pisgah-highlands-37594929/",
 "@id":"https://www.landandfarm.com/property/pisgah-highlands-37594929/#listingdetailpage",
 "description":"Perfectly positioned below the iconic summit of Mt Pisgah, a full untruncated multi-sentence description that goes well past the two-hundred-fifty character cutoff the search-results page imposes on the same text.",
 "datePosted":"2025-05-16",
 "name":"124.85 Acres, 59 Pisgah Mountain Trail, Candler, NC 28715",
 "mainEntity":{
   "@type":"Residence",
   "additionalProperty":[
     {"@type":"PropertyValue","name":"Acreage","value":"124.85 acres"},
     {"@type":"PropertyValue","name":"Proposed Use","value":["Commercial","Residential Single"]}
   ]
 },
 "offers":{
   "@type":"Offer","price":1895000,"priceCurrency":"USD",
   "seller":{"@type":"RealEstateAgent","name":"Billy May","telephone":"(828) 506-8701"}
 }
}
</script>
</body></html>
"""


def test_parse_detail_extras_pulls_phone_date_and_properties():
    extras = _parse_detail_extras(_DETAIL_HTML)
    assert extras["agent_phone"] == "(828) 506-8701"
    assert extras["date_posted"] == "2025-05-16"
    assert extras["additional_properties"]["Acreage"] == "124.85 acres"
    assert extras["additional_properties"]["Proposed Use"] == ["Commercial", "Residential Single"]
    assert "Pisgah" in extras["full_description"]
    assert len(extras["full_description"]) > 200  # the search page's own truncation point


def test_parse_detail_extras_empty_on_no_match():
    assert _parse_detail_extras("<html><body>no json-ld here</body></html>") == {}


def _base_listing(description="short", agent_phone=None) -> Listing:
    from datetime import datetime
    return Listing(
        source="national.landandfarm", source_url="https://x/property/1/",
        listing_type=ListingType.UNKNOWN, property_kind=PropertyKind.LAND,
        description=description, first_seen=datetime.utcnow(), last_seen=datetime.utcnow(),
        raw={"landandfarm": {"agent_phone": agent_phone}},
    )


def test_apply_detail_extras_fills_missing_phone():
    li = _base_listing(agent_phone=None)
    _apply_detail_extras(li, {"agent_phone": "(828) 506-8701"})
    assert li.raw["landandfarm"]["agent_phone"] == "(828) 506-8701"


def test_apply_detail_extras_does_not_overwrite_existing_phone():
    li = _base_listing(agent_phone="(555) 000-0000")
    _apply_detail_extras(li, {"agent_phone": "(828) 506-8701"})
    assert li.raw["landandfarm"]["agent_phone"] == "(555) 000-0000"


def test_apply_detail_extras_replaces_truncated_description_with_fuller_one():
    li = _base_listing(description="short")
    extras = _parse_detail_extras(_DETAIL_HTML)
    _apply_detail_extras(li, extras)
    assert len(li.description) > len("short")
    assert "Pisgah" in li.description


def test_apply_detail_extras_noop_on_empty_extras():
    li = _base_listing(description="unchanged")
    _apply_detail_extras(li, {})
    assert li.description == "unchanged"
    assert "date_posted" not in li.raw["landandfarm"]


def test_fetch_detail_extras_returns_empty_dict_on_fetch_failure(monkeypatch):
    """_fetch_detail_extras must be pure best-effort -- a network failure
    must never raise out to the caller (the caller treats it as
    enrichment, not load-bearing)."""
    async def _boom(*a, **k):
        raise RuntimeError("network down")

    import foreclosure_scraper.scrapers.national.landandfarm as m
    monkeypatch.setattr(m, "get_text_impersonate", _boom)
    extras = asyncio.run(_fetch_detail_extras("https://x/property/1/"))
    assert extras == {}


# ---------------------------------------------------------------------------
# Baseline coverage for the pre-existing parser (had zero tests before this
# batch).
# ---------------------------------------------------------------------------

def test_extract_acres_from_name():
    assert _extract_acres("124.85 Acres, Candler, NC", None) == 124.85


def test_extract_county_from_url():
    assert _extract_county(
        "https://www.landandfarm.com/search/north-carolina/buncombe-county-land-for-sale/property/x-1/",
        "x",
    ) == "Buncombe"


def test_parse_item_builds_listing_with_core_fields():
    item = {
        "url": "https://www.landandfarm.com/property/x-123/",
        "name": "10 Acres, Asheville, NC",
        "description": "Nice land",
        "contentLocation": {"address": {
            "streetAddress": "1 Main St", "addressLocality": "Asheville",
            "addressRegion": "NC", "postalCode": "28801",
        }},
        "offers": {"price": 100000, "offeredBy": {"name": "Jane Doe", "url": "https://x/profile"}},
        "image": "https://x/img.jpg",
    }
    li = _parse_item(item, "national.landandfarm")
    assert li.street_address == "1 Main St"
    assert li.state == "NC"
    assert li.opening_bid == 100000.0
    assert li.raw["landandfarm"]["agent_name"] == "Jane Doe"
    assert li.raw["images"]["real"] == ["https://x/img.jpg"]
