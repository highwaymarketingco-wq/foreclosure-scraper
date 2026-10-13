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
import json

from foreclosure_scraper.scrapers.national.landwatch import (
    GALLERY_PHOTO_CAP,
    _apply_detail_extras,
    _extract_acres,
    _extract_county,
    _extract_gallery_photos,
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


# ---------------------------------------------------------------------------
# Gallery fix (source-completeness audit, 2026-10-13): live-confirmed on 3
# real current listings (landwatch.com Spartanburg + the shared Land.com-
# network Buncombe listing also checked on the sibling landandfarm.com) that
# EVERY JSON-LD block on a detail page (Residence / Product /
# RealEstateListing+Product / BreadcrumbList) carries only the single main
# photo. The real 16-38-photo gallery lives in a separate, non-JSON-LD
# <script type="application/json" id="__SERVER_STATE__"> SSR state blob at
# propertyDetailPage.propertyData.imageDocumentIds. This is a
# trimmed-but-real fixture (12 of the 38 real document IDs) live-captured
# 2026-10-13 from the same shared-network listing as _DETAIL_HTML above.
# ---------------------------------------------------------------------------
_SERVER_STATE_JSON = json.dumps({
    "propertyDetailPage": {
        "propertyData": {
            "mainPhotoDocumentId": 5527661172,
            "imageDocumentIds": [
                5527661172, 5527661173, 5527661174, 5527661177, 5527661175,
                5527661176, 5527661178, 5527661179, 5527661180, 5527661181,
                5527661188, 5527661189,
            ],
        }
    },
    "settings": {"servers": {"Image": "https://assets.landwatch.com"}},
})

_DETAIL_HTML_WITH_GALLERY = (
    _DETAIL_HTML.replace("</body></html>", "")
    + f'<script type="application/json" id="__SERVER_STATE__">{_SERVER_STATE_JSON}</script>'
    + "</body></html>"
)

_EXPECTED_GALLERY_URLS = [
    f"https://assets.landwatch.com/resizedimages/394/0/h/80/1-{doc_id}"
    for doc_id in (
        5527661172, 5527661173, 5527661174, 5527661177, 5527661175,
        5527661176, 5527661178, 5527661179,
    )
]


def test_extract_gallery_photos_from_real_server_state():
    """All real photos captured (capped at GALLERY_PHOTO_CAP), in order."""
    photos = _extract_gallery_photos(_DETAIL_HTML_WITH_GALLERY)
    assert len(photos) == GALLERY_PHOTO_CAP == 8
    assert photos == _EXPECTED_GALLERY_URLS
    assert photos[0] == "https://assets.landwatch.com/resizedimages/394/0/h/80/1-5527661172"


def test_extract_gallery_photos_dedupes_repeated_document_ids():
    dup_state = json.dumps({
        "propertyDetailPage": {"propertyData": {
            "imageDocumentIds": [111, 111, 222, 111, 333],
        }},
        "settings": {"servers": {"Image": "https://assets.landwatch.com"}},
    })
    html = (
        "<html><body>"
        f'<script type="application/json" id="__SERVER_STATE__">{dup_state}</script>'
        "</body></html>"
    )
    photos = _extract_gallery_photos(html)
    assert photos == [
        "https://assets.landwatch.com/resizedimages/394/0/h/80/1-111",
        "https://assets.landwatch.com/resizedimages/394/0/h/80/1-222",
        "https://assets.landwatch.com/resizedimages/394/0/h/80/1-333",
    ]
    assert len(photos) == len(set(photos))


def test_extract_gallery_photos_empty_when_server_state_missing():
    """A page with only the single original JSON-LD block (no
    __SERVER_STATE__ at all) must not regress -- just no extra photos."""
    assert _extract_gallery_photos(_DETAIL_HTML) == []


def test_extract_gallery_photos_empty_on_malformed_server_state():
    """A malformed __SERVER_STATE__ blob must never raise."""
    html = (
        "<html><body>"
        '<script type="application/json" id="__SERVER_STATE__">{not valid json!!</script>'
        "</body></html>"
    )
    assert _extract_gallery_photos(html) == []


def test_extract_gallery_photos_empty_when_image_document_ids_absent():
    html = (
        "<html><body>"
        '<script type="application/json" id="__SERVER_STATE__">{"propertyDetailPage": {"propertyData": {}}}</script>'
        "</body></html>"
    )
    assert _extract_gallery_photos(html) == []


def test_parse_detail_extras_includes_gallery_photos():
    extras = _parse_detail_extras(_DETAIL_HTML_WITH_GALLERY)
    assert extras["photos"] == _EXPECTED_GALLERY_URLS
    assert extras["agent_phone"] == "(828) 555-0756"


def test_parse_detail_extras_malformed_server_state_does_not_break_other_fields():
    """A malformed gallery blob must never take down the phone/date/
    description extraction that already worked."""
    html = (
        _DETAIL_HTML.replace("</body></html>", "")
        + '<script type="application/json" id="__SERVER_STATE__">{broken</script>'
        + "</body></html>"
    )
    extras = _parse_detail_extras(html)
    assert extras["agent_phone"] == "(828) 555-0756"
    assert "photos" not in extras


def test_apply_detail_extras_merges_gallery_into_raw_images():
    li = _base_listing()
    li.raw["images"] = {"real": ["https://assets.landwatch.com/resizedimages/394/0/h/80/1-5527661172"]}
    extras = _parse_detail_extras(_DETAIL_HTML_WITH_GALLERY)
    _apply_detail_extras(li, extras)
    have = li.raw["images"]["real"]
    assert have.count("https://assets.landwatch.com/resizedimages/394/0/h/80/1-5527661172") == 1
    assert len(have) == GALLERY_PHOTO_CAP == 8
    assert have == _EXPECTED_GALLERY_URLS


def test_apply_detail_extras_gallery_noop_when_no_photos_key():
    li = _base_listing()
    li.raw["images"] = {"real": ["https://x/img.jpg"]}
    _apply_detail_extras(li, {"agent_phone": "(555) 111-2222"})
    assert li.raw["images"]["real"] == ["https://x/img.jpg"]


def test_full_pipeline_survives_malformed_gallery_block():
    """End-to-end: a malformed __SERVER_STATE__ must never break the main
    listing build (_parse_item) or the rest of the enrichment pipeline."""
    item = {
        "url": "https://www.landwatch.com/x/pid/123",
        "name": "10 Acres, Asheville, NC",
        "description": "Nice land",
        "image": "https://assets.landwatch.com/resizedimages/394/0/h/80/1-999/",
    }
    li = _parse_item(item, "national.landwatch")
    assert li is not None
    broken_html = (
        '<html><body><script type="application/json" id="__SERVER_STATE__">'
        "{totally not json</script></body></html>"
    )
    extras = _parse_detail_extras(broken_html)
    _apply_detail_extras(li, extras)  # must not raise
    assert li.street_address is None  # untouched core field, listing intact
    assert li.raw["landwatch"]["title"] == "10 Acres, Asheville, NC"


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
