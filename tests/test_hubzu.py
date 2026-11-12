"""national.hubzu: 2026-10-01 national/reo per-source extraction audit.

Live-verified the /portal/auctions JSON endpoint already returns a real
per-property photo (imageUrl, protocol-relative) and the listing
agent/broker name (agentCompanyName) on every item, and neither was
captured -- the same miss class already fixed today in
national.gsa_surplus / servicelink_auction / tranzon_auctions (raw["images"]
= {"real": [...]}). Everything else (address, bid, beds/baths/sqft,
lat/lng, sale/auction-end date) was already correctly wired.

ADDED 2026-10-13 (source-completeness audit, Pattern B): live-verified the
search tuple's single `imageUrl` is only the gallery's first/default image --
the free, no-auth `getNewPdpDetails/<propertyId>` endpoint (propertyId = the
leading digits of `listingId`) carries the real gallery. See module
docstring addendum in hubzu.py for the live samples that confirmed this
(photoCount 2/5/5/15 each matched the detail endpoint's real image count).
"""
from __future__ import annotations

from foreclosure_scraper.scrapers.national.hubzu import (
    GALLERY_CAP,
    _gallery_photos,
    _parse_item,
    _photo_url,
    _property_id,
)

# A trimmed but real shape, captured live 2026-10-01 against
# https://www.hubzu.com/portal/auctions?state=NC&pageSize=200
_REAL_ITEM = {
    "propertyCategory": "REO",
    "propertySubType": "Single Family",
    "size": "2,806",
    "lotSize": "43,568",
    "bedCount": "3",
    "bathCount": "2",
    "photoCount": "5",
    "imageUrl": "//image-prod.hubzu.com/2026/8/9321811956/9321811956_20260829092145825_2.JPEG.X278.Y184.JPEG",
    "propAddress": {
        "streetNumber": "1326",
        "streetName": "Cross Link Rd",
        "county": "Wake",
        "city": "Raleigh",
        "state": "NC",
        "zip": "27610",
    },
    "currentBid": "333,400",
    "startingBid": "315,400",
    "category": "REO",
    "agentCompanyName": "Vylla Home",
    "lat": "35.749526",
    "lng": "-78.617295",
    "listingUrl": "/nc/raleigh/auction-9321811956",
    "listingId": "9321811956",
    "listingEndDate": "2026-10-02T09:27:19Z",
    "listingStatus": "Active",
}


def test_photo_url_normalizes_protocol_relative():
    assert _photo_url("//image-prod.hubzu.com/x.jpg") == "https://image-prod.hubzu.com/x.jpg"
    assert _photo_url("https://already-absolute/x.jpg") == "https://already-absolute/x.jpg"
    assert _photo_url("") is None
    assert _photo_url(None) is None
    assert _photo_url("not-a-url") is None


def test_parse_item_captures_photo_and_broker():
    li = _parse_item(_REAL_ITEM, "NC")
    assert li is not None
    assert li.raw["images"] == {
        "real": ["https://image-prod.hubzu.com/2026/8/9321811956/9321811956_20260829092145825_2.JPEG.X278.Y184.JPEG"]
    }
    assert li.raw["hubzu"]["broker"] == "Vylla Home"
    assert li.raw["hubzu"]["photo_count"] == "5"
    # Pre-existing fields must stay intact.
    assert li.street_address == "1326 Cross Link Rd"
    assert li.county == "Wake"
    assert li.opening_bid == 315400.0


def test_parse_item_no_photo_omits_images_key():
    item = dict(_REAL_ITEM)
    item["imageUrl"] = ""
    li = _parse_item(item, "NC")
    assert li is not None
    assert "images" not in li.raw


# ---------------------------------------------------------------------------
# listingPrice / occupancyStatus (2026-10-04, batch 16): live-sampled 132
# current NC+SC rows -- listingPrice present on 42 (32%), differing from
# startingBid on 41 of those 42 (a real, distinct valuation signal, not a
# duplicate); occupancyStatus carries real "Y"/"N" values. Neither was
# captured before this fix.
# ---------------------------------------------------------------------------

def test_listing_price_maps_to_market_value_and_is_kept_in_raw():
    item = dict(_REAL_ITEM)
    item["listingPrice"] = "229,900"  # distinct from startingBid=315,400
    li = _parse_item(item, "NC")
    assert li is not None
    assert li.market_value == 229900.0
    assert li.raw["hubzu"]["listing_price"] == 229900.0
    # startingBid must still drive opening_bid, unaffected by this fix.
    assert li.opening_bid == 315400.0


def test_no_listing_price_leaves_market_value_none():
    li = _parse_item(_REAL_ITEM, "NC")  # no listingPrice key at all
    assert li is not None
    assert li.market_value is None
    assert li.raw["hubzu"]["listing_price"] is None


def test_occupancy_status_captured():
    item = dict(_REAL_ITEM)
    item["occupancyStatus"] = "Y"
    li = _parse_item(item, "NC")
    assert li is not None
    assert li.raw["hubzu"]["occupancy_status"] == "Y"


def test_no_occupancy_status_is_none_not_empty_string():
    li = _parse_item(_REAL_ITEM, "NC")
    assert li is not None
    assert li.raw["hubzu"]["occupancy_status"] is None


# ---------------------------------------------------------------------------
# Full-gallery enrichment (2026-10-13, Pattern B fix): the search tuple's
# listingId -> getNewPdpDetails propertyId mapping, and parsing that detail
# endpoint's own imageDetails[] into the real gallery.
# ---------------------------------------------------------------------------

def test_property_id_strips_auction_round_suffix():
    # Live current shape (2026-10-13): "<propertyId>AUCN<round>".
    assert _property_id("9321811956AUCN7") == "9321811956"
    assert _property_id("501753045164AUCN2") == "501753045164"


def test_property_id_accepts_bare_numeric_id():
    # Older/legacy shape with no suffix (e.g. this file's own _REAL_ITEM).
    assert _property_id("9321811956") == "9321811956"


def test_property_id_handles_missing_or_junk():
    assert _property_id(None) is None
    assert _property_id("") is None
    assert _property_id("AUCN7") is None


# A trimmed but real shape, captured live 2026-10-13 against
# https://www.hubzu.com/portal/property/getNewPdpDetails/9321811956 -- the
# same listing as _REAL_ITEM above (photoCount="5" there matches the 5
# imageDetails entries here exactly).
_REAL_DETAIL_RESPONSE = {
    "propertyDetails": {
        "propertyId": "9321811956",
        "imageDetails": [
            {
                "imageDisplaySequence": "1",
                "imageStoragePath": "//image-prod.hubzu.com/2026/8/9321811956/9321811956_20260829092145825_2.JPEG",
                "defaultImage": True,
            },
            {
                "imageDisplaySequence": "2",
                "imageStoragePath": "//image1-prod.hubzu.com/2026/8/9321811956/9321811956_20260829092144570_1.JPEG",
                "defaultImage": False,
            },
            {
                "imageDisplaySequence": "3",
                "imageStoragePath": "//image2-prod.hubzu.com/2026/8/9321811956/9321811956_20260829092147144_3.JPEG",
                "defaultImage": False,
            },
            {
                "imageDisplaySequence": "4",
                "imageStoragePath": "//image-prod.hubzu.com/2026/8/9321811956/9321811956_20260829092148091_4.JPEG",
                "defaultImage": False,
            },
            {
                "imageDisplaySequence": "5",
                "imageStoragePath": "//image1-prod.hubzu.com/2026/8/9321811956/9321811956_20260829092149065_5.JPEG",
                "defaultImage": False,
            },
        ],
    }
}


def test_gallery_photos_extracts_and_normalizes_all_images():
    photos = _gallery_photos(_REAL_DETAIL_RESPONSE)
    assert photos == [
        "https://image-prod.hubzu.com/2026/8/9321811956/9321811956_20260829092145825_2.JPEG",
        "https://image1-prod.hubzu.com/2026/8/9321811956/9321811956_20260829092144570_1.JPEG",
        "https://image2-prod.hubzu.com/2026/8/9321811956/9321811956_20260829092147144_3.JPEG",
        "https://image-prod.hubzu.com/2026/8/9321811956/9321811956_20260829092148091_4.JPEG",
        "https://image1-prod.hubzu.com/2026/8/9321811956/9321811956_20260829092149065_5.JPEG",
    ]


def test_gallery_photos_dedupes_repeated_urls():
    detail = {
        "propertyDetails": {
            "imageDetails": [
                {"imageStoragePath": "//image-prod.hubzu.com/a.jpg"},
                {"imageStoragePath": "//image-prod.hubzu.com/a.jpg"},
                {"imageStoragePath": "//image-prod.hubzu.com/b.jpg"},
            ]
        }
    }
    assert _gallery_photos(detail) == [
        "https://image-prod.hubzu.com/a.jpg",
        "https://image-prod.hubzu.com/b.jpg",
    ]


def test_gallery_photos_caps_at_gallery_cap():
    # Live-sampled 2026-10-13: one listing (501753045164) genuinely carried 15
    # real photos -- confirm the cap still applies rather than keeping all 15.
    detail = {
        "propertyDetails": {
            "imageDetails": [
                {"imageStoragePath": f"//image-prod.hubzu.com/{n}.jpg"}
                for n in range(15)
            ]
        }
    }
    photos = _gallery_photos(detail)
    assert len(photos) == GALLERY_CAP == 8
    assert photos[0] == "https://image-prod.hubzu.com/0.jpg"


def test_gallery_photos_skips_blank_or_malformed_entries():
    detail = {
        "propertyDetails": {
            "imageDetails": [
                {"imageStoragePath": ""},
                "not-a-dict",
                {"imageStoragePath": "//image-prod.hubzu.com/real.jpg"},
            ]
        }
    }
    assert _gallery_photos(detail) == ["https://image-prod.hubzu.com/real.jpg"]


def test_gallery_photos_handles_empty_or_missing_image_details():
    assert _gallery_photos({"propertyDetails": {"imageDetails": []}}) == []
    assert _gallery_photos({"propertyDetails": {}}) == []
    assert _gallery_photos({}) == []
