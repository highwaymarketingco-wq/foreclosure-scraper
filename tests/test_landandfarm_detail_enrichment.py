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
listing: phone "(828) 555-0756". Also confirmed live: unlike the
search-results page (Akamai-gated, needs StealthyFetcher), the detail page
is reachable via plain curl_cffi impersonation (`get_text_impersonate`) --
no extra render cost. Wired as a best-effort, per-county-capped enrichment
(DETAIL_FETCH_CAP_PER_COUNTY) in `_fetch_county`.
"""
from __future__ import annotations

import asyncio
import json

from foreclosure_scraper.scrapers.national.landandfarm import (
    GALLERY_PHOTO_CAP,
    _apply_detail_extras,
    _extract_acres,
    _extract_county,
    _extract_gallery_photos,
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
   "seller":{"@type":"RealEstateAgent","name":"Billy May","telephone":"(828) 555-0756"}
 }
}
</script>
</body></html>
"""


# ---------------------------------------------------------------------------
# Gallery fix (source-completeness audit, 2026-10-13): live-confirmed on 3
# real current listings that EVERY JSON-LD block on a detail page (Residence
# / Product / RealEstateListing+Product / BreadcrumbList) carries only the
# single main photo. The real 18-48-photo gallery lives in a separate,
# non-JSON-LD <script type="application/json" id="__SERVER_STATE__"> SSR
# state blob at propertyDetailPage.propertyData.imageDocumentIds. This is a
# trimmed-but-real fixture (12 of the 38 real document IDs) live-captured
# 2026-10-13 from the same Pisgah Highlands listing as _DETAIL_HTML above.
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
    "settings": {"servers": {"Image": "https://assets.landandfarm.com"}},
})

_DETAIL_HTML_WITH_GALLERY = (
    _DETAIL_HTML.replace("</body></html>", "")
    + f'<script type="application/json" id="__SERVER_STATE__">{_SERVER_STATE_JSON}</script>'
    + "</body></html>"
)

_EXPECTED_GALLERY_URLS = [
    f"https://assets.landandfarm.com/resizedimages/394/0/h/80/1-{doc_id}"
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
    # the first URL must match the exact format already used for the single
    # photo captured by `_parse_item` from the search-page JSON-LD, so the
    # two sources dedupe cleanly against each other.
    assert photos[0] == "https://assets.landandfarm.com/resizedimages/394/0/h/80/1-5527661172"


def test_extract_gallery_photos_dedupes_repeated_document_ids():
    dup_state = json.dumps({
        "propertyDetailPage": {"propertyData": {
            "imageDocumentIds": [111, 111, 222, 111, 333],
        }},
        "settings": {"servers": {"Image": "https://assets.landandfarm.com"}},
    })
    html = (
        "<html><body>"
        f'<script type="application/json" id="__SERVER_STATE__">{dup_state}</script>'
        "</body></html>"
    )
    photos = _extract_gallery_photos(html)
    assert photos == [
        "https://assets.landandfarm.com/resizedimages/394/0/h/80/1-111",
        "https://assets.landandfarm.com/resizedimages/394/0/h/80/1-222",
        "https://assets.landandfarm.com/resizedimages/394/0/h/80/1-333",
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
    # pre-existing fields must still be parsed correctly alongside it
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
    li.raw["images"] = {"real": ["https://assets.landandfarm.com/resizedimages/394/0/h/80/1-5527661172"]}
    extras = _parse_detail_extras(_DETAIL_HTML_WITH_GALLERY)
    _apply_detail_extras(li, extras)
    have = li.raw["images"]["real"]
    # the pre-existing single photo (same URL the gallery's first entry
    # resolves to) must not be duplicated, and the total must respect the cap.
    assert have.count("https://assets.landandfarm.com/resizedimages/394/0/h/80/1-5527661172") == 1
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
        "url": "https://www.landandfarm.com/property/x-123/",
        "name": "10 Acres, Asheville, NC",
        "description": "Nice land",
        "image": "https://assets.landandfarm.com/resizedimages/394/0/h/80/1-999/",
    }
    li = _parse_item(item, "national.landandfarm")
    assert li is not None
    broken_html = (
        '<html><body><script type="application/json" id="__SERVER_STATE__">'
        "{totally not json</script></body></html>"
    )
    extras = _parse_detail_extras(broken_html)
    _apply_detail_extras(li, extras)  # must not raise
    assert li.street_address is None  # untouched core field, listing intact
    assert li.raw["landandfarm"]["title"] == "10 Acres, Asheville, NC"


def test_parse_detail_extras_pulls_phone_date_and_properties():
    extras = _parse_detail_extras(_DETAIL_HTML)
    assert extras["agent_phone"] == "(828) 555-0756"
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
    _apply_detail_extras(li, {"agent_phone": "(828) 555-0756"})
    assert li.raw["landandfarm"]["agent_phone"] == "(828) 555-0756"


def test_apply_detail_extras_does_not_overwrite_existing_phone():
    li = _base_listing(agent_phone="(555) 000-0000")
    _apply_detail_extras(li, {"agent_phone": "(828) 555-0756"})
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
