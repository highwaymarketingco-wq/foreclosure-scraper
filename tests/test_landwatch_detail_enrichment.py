"""national.landwatch -- HERMES extraction-completeness audit, batch 17
(2026-10-04). No test file existed for this source before this batch.

Same finding as the sibling national.landandfarm (same Land.com-network
markup, confirmed live on landwatch.com too): the search-results page's
JSON-LD `offeredBy` never carries a `telephone` field, but each listing's
own DETAIL page carries a richer JSON-LD block with a REAL
`offers.seller.telephone`, full untruncated description, `datePosted`, and
a structured `additionalProperty` list. Confirmed live: phone
"(828) 555-0756" on a real current Buncombe listing, reachable via plain
curl_cffi impersonation (no StealthyFetcher needed for the detail page).
"""
from __future__ import annotations

import asyncio

from foreclosure_scraper.scrapers.national.landwatch import (
    _apply_detail_extras,
    _extract_acres,
    _extract_county,
    _extract_pid,
    _fetch_detail_extras,
    _parse_detail_extras,
    _parse_item,
)
from foreclosure_scraper.models import Listing, ListingType, PropertyKind

# A trimmed-but-real detail-page JSON-LD shape, live-captured 2026-10-04
# from https://www.landwatch.com/buncombe-county-north-carolina-recreational-
# property-for-sale/pid/422965048
_DETAIL_HTML = """
<html><body>
<script type="application/ld+json">
{"@context":"https://schema.org","@type":"Residence","url":"/x/"}
</script>
<script type="application/ld+json">
{"@context":"https://schema.org",
 "@type":["RealEstateListing","Product"],
 "url":"https://www.landwatch.com/buncombe-county-north-carolina-recreational-property-for-sale/pid/422965048",
 "@id":"https://www.landwatch.com/buncombe-county-north-carolina-recreational-property-for-sale/pid/422965048#listingdetailpage",
 "description":"Perfectly positioned below the iconic summit of Mt Pisgah, a full untruncated multi-sentence description that goes well past the two-hundred-fifty character cutoff the search-results page imposes on the same text.",
 "datePosted":"2025-05-16",
 "name":"124.85 Acres, Candler, NC 28715",
 "mainEntity":{
   "@type":"Residence",
   "additionalProperty":[
     {"@type":"PropertyValue","name":"Acreage","value":"124.85 acres"},
     {"@type":"PropertyValue","name":"Proposed Use","value":["Commercial","Residential Single"]}
   ]
 },
 "offers":{
   "@type":"Offer","price":1895000,"priceCurrency":"USD",
   "seller":{"@type":"RealEstateAgent","name":"Billy May","telephone":"(828) 555-0756"}
 }
}
</script>
</body></html>
"""


def test_parse_detail_extras_pulls_phone_date_and_properties():
    extras = _parse_detail_extras(_DETAIL_HTML)
    assert extras["agent_phone"] == "(828) 555-0756"
    assert extras["date_posted"] == "2025-05-16"
    assert extras["additional_properties"]["Acreage"] == "124.85 acres"
    assert len(extras["full_description"]) > 200


def _base_listing(description="short", agent_phone=None) -> Listing:
    from datetime import datetime
    return Listing(
        source="national.landwatch", source_url="https://x/pid/1",
        listing_type=ListingType.UNKNOWN, property_kind=PropertyKind.LAND,
        description=description, first_seen=datetime.utcnow(), last_seen=datetime.utcnow(),
        raw={"landwatch": {"agent_phone": agent_phone}},
    )


def test_apply_detail_extras_fills_missing_phone():
    li = _base_listing(agent_phone=None)
    _apply_detail_extras(li, {"agent_phone": "(828) 555-0756"})
    assert li.raw["landwatch"]["agent_phone"] == "(828) 555-0756"


def test_apply_detail_extras_does_not_overwrite_existing_phone():
    li = _base_listing(agent_phone="(555) 000-0000")
    _apply_detail_extras(li, {"agent_phone": "(828) 555-0756"})
    assert li.raw["landwatch"]["agent_phone"] == "(555) 000-0000"


def test_apply_detail_extras_noop_on_empty_extras():
    li = _base_listing(description="unchanged")
    _apply_detail_extras(li, {})
    assert li.description == "unchanged"


def test_fetch_detail_extras_returns_empty_dict_on_fetch_failure(monkeypatch):
    async def _boom(*a, **k):
        raise RuntimeError("network down")

    import foreclosure_scraper.scrapers.national.landwatch as m
    monkeypatch.setattr(m, "get_text_impersonate", _boom)
    extras = asyncio.run(_fetch_detail_extras("https://x/pid/1"))
    assert extras == {}


# ---------------------------------------------------------------------------
# Baseline coverage for the pre-existing parser (had zero tests before this
# batch).
# ---------------------------------------------------------------------------

def test_extract_acres_from_name():
    assert _extract_acres("124.85 Acres, Candler, NC", None) == 124.85


def test_extract_pid_from_url():
    assert _extract_pid("https://www.landwatch.com/x-for-sale/pid/422965048") == "422965048"


def test_extract_county_from_url():
    assert _extract_county(
        "https://www.landwatch.com/buncombe-county-north-carolina-recreational-"
        "property-for-sale/pid/422965048",
        "x",
    ) == "Buncombe"


def test_parse_item_builds_listing_with_core_fields():
    item = {
        "url": "https://www.landwatch.com/x/pid/123",
        "name": "10 Acres, Asheville, NC",
        "description": "Nice land",
        "contentLocation": {"address": {
            "streetAddress": "1 Main St", "addressLocality": "Asheville",
            "addressRegion": "NC", "postalCode": "28801",
        }},
        "offers": {"price": 100000, "offeredBy": {"name": "Jane Doe", "url": "https://x/profile"}},
        "image": "https://x/img.jpg",
    }
    li = _parse_item(item, "national.landwatch")
    assert li.street_address == "1 Main St"
    assert li.state == "NC"
    assert li.opening_bid == 100000.0
    assert li.raw["landwatch"]["agent_name"] == "Jane Doe"
    assert li.raw["images"]["real"] == ["https://x/img.jpg"]
