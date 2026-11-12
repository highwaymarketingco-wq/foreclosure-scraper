"""national.trulia — HERMES extraction-completeness audit, national batch 5
(2026-10-04).

Live-verified via the session's own cloud browser against a real current
fetch of trulia.com/foreclosures/ (geo-detected to Spartanburg SC, 14 real
current rows; this machine's local StealthyFetcher render was skipped per
the documented RAM constraint). Found and fixed:

1. The REAL photo gallery (media.photos[]) was never read -- only the
   single heroImage (often a Google Street View static fallback when the
   listing has no real photos) was kept.
2. Agent/broker contactability (activeListing.provider.{listingAgent.name,
   broker.name}) was never read, though present on most live-sampled rows.
3. property_kind was hardcoded UNKNOWN -- propertyType.value was never
   mapped.
4. lot_size_sqft/year_built were never populated -- on some live rows
   these exist ONLY in description.value's free text, not as any
   structured field.
5. is_foreclosure/is_recently_sold/beds_raw/baths_raw/floor_space_raw were
   flat top-level raw keys with no RAW_KEEP entry -- silently dropped at
   every publish.

Fixtures below are built from REAL field shapes captured live 2026-10-04
(2305 Wellington Rd, Spartanburg SC -- a real current Trulia foreclosure
auction row with 5 real photos, agent "Auction.com Customer Service" /
broker "Auction.com"; and 307 Amherst Dr, a real current row with NO real
photos at all, where heroImage is a Google Street View fallback).
"""
from __future__ import annotations

from foreclosure_scraper.models import ListingType, PropertyKind
from foreclosure_scraper.scrapers.national import trulia_foreclosures as mod
from foreclosure_scraper.web_artifact import RAW_KEEP, _slim_raw


def _real_item(**overrides) -> dict:
    base = {
        "location": {
            "city": "Spartanburg", "stateCode": "SC", "zipCode": "29302",
            "streetAddress": "2305 Wellington Rd",
            "coordinates": {"latitude": 34.9, "longitude": -81.9},
        },
        "price": {"formattedPrice": "$212,900"},
        "url": "/home/2305-wellington-rd-spartanburg-sc-29302-11111",
        "homeUrl": None,
        "tags": [{"kind": "AUCTION", "formattedName": "AUCTION"}],
        "fullTags": [{"formattedName": "AUCTION"}],
        "floorSpace": {"formattedDimension": "1,612 sqft"},
        "bedrooms": {"value": 3},
        "bathrooms": {"value": 2},
        "typedHomeId": "11111_ZPID",
        "propertyType": {"value": "SINGLE_FAMILY_HOME"},
        "description": {
            "value": (
                "This single-family home is located at 2305 Wellington Rd, "
                "Spartanburg, SC. This property has 3 bedrooms, 2 bathrooms "
                "and approximately 1,612 sqft of floor space. This property "
                "has a lot size of 0.43 acres and was built in 1960."
            )
        },
        "activeListing": {
            "dateListed": "2026-09-17T16:04:34+00:00",
            "provider": {
                "listingAgent": {"name": "Auction.com Customer Service"},
                "broker": {"name": "Auction.com"},
            },
        },
        "currentStatus": {"isForeclosure": True, "isRecentlySold": False},
        "media": {
            "heroImage": {"url": {"medium": "https://www.trulia.com/pictures/thumbs_4/x-full.jpg"}},
            "photos": [
                {"url": {"large": "https://www.trulia.com/pictures/thumbs_5/a-full.jpg"}},
                {"url": {"large": "https://www.trulia.com/pictures/thumbs_5/b-full.jpg"}},
            ],
        },
    }
    base.update(overrides)
    return base


def test_full_photo_gallery_captured_not_just_heroimage():
    li = mod._to_listing(_real_item(), "national.trulia")
    assert li is not None
    assert li.raw["images"]["real"] == [
        "https://www.trulia.com/pictures/thumbs_5/a-full.jpg",
        "https://www.trulia.com/pictures/thumbs_5/b-full.jpg",
    ]


def test_heroimage_streetview_fallback_used_when_no_real_photos():
    """Regression pin: a real live row (307 Amherst Dr) had media.photos=[]
    and heroImage pointing at a Google Street View static image -- that
    fallback must still be used when photos[] is genuinely empty."""
    item = _real_item()
    item["media"] = {
        "heroImage": {"url": {"medium": "https://maps.googleapis.com/maps/api/streetview?x=1"}},
        "photos": [],
    }
    li = mod._to_listing(item, "national.trulia")
    assert li.raw["images"]["real"] == ["https://maps.googleapis.com/maps/api/streetview?x=1"]


def test_property_type_mapped_to_real_property_kind():
    li = mod._to_listing(_real_item(), "national.trulia")
    assert li.property_kind == PropertyKind.SINGLE_FAMILY

    land = _real_item()
    land["propertyType"] = {"value": "LOT_LAND"}
    li2 = mod._to_listing(land, "national.trulia")
    assert li2.property_kind == PropertyKind.LAND


def test_lot_size_and_year_built_parsed_from_description_when_no_structured_field():
    li = mod._to_listing(_real_item(), "national.trulia")
    # 0.43 acres * 43560 = 18730.8
    assert li.lot_size_sqft is not None
    assert abs(li.lot_size_sqft - 18730.8) < 0.1
    assert li.year_built == 1960


def test_lot_size_sqft_form_in_description_also_parsed():
    item = _real_item()
    item["description"]["value"] = (
        "This single-family home has a lot size of 8712 sqft and was built in 1950."
    )
    li = mod._to_listing(item, "national.trulia")
    assert li.lot_size_sqft == 8712.0
    assert li.year_built == 1950


def test_real_description_text_used_instead_of_generic_placeholder():
    li = mod._to_listing(_real_item(), "national.trulia")
    assert li.description.startswith("This single-family home is located at")
    assert "Trulia foreclosure (" not in li.description


def test_generic_description_fallback_when_no_description_value():
    item = _real_item()
    item["description"] = {}
    li = mod._to_listing(item, "national.trulia")
    assert "Trulia foreclosure" in li.description


def test_agent_and_broker_captured_in_namespaced_raw():
    li = mod._to_listing(_real_item(), "national.trulia")
    ns = li.raw["trulia"]
    assert ns["listing_agent"] == "Auction.com Customer Service"
    assert ns["listing_broker"] == "Auction.com"
    assert ns["date_listed"] == "2026-09-17T16:04:34+00:00"
    assert ns["property_type"] == "SINGLE_FAMILY_HOME"


def test_price_unknown_does_not_crash_and_yields_no_price():
    """Regression: a real live row ("Price Unknown") must not crash the
    regex match (previously bare except Exception already handled this,
    confirmed still correct)."""
    item = _real_item()
    item["price"] = {"formattedPrice": "Price Unknown"}
    li = mod._to_listing(item, "national.trulia")
    assert li is not None
    assert li.opening_bid is None


def test_trulia_key_registered_in_raw_keep():
    assert RAW_KEEP.get("trulia") == "*"


def test_previously_dropped_fields_survive_slim_raw_round_trip():
    li = mod._to_listing(_real_item(), "national.trulia")
    slim = _slim_raw(li.raw)
    assert slim.get("trulia") == li.raw["trulia"]
    assert slim.get("trulia_id") == li.raw["trulia_id"]


def test_not_foreclosure_still_filtered_out():
    item = _real_item()
    item["currentStatus"]["isForeclosure"] = False
    assert mod._to_listing(item, "national.trulia") is None


def test_out_of_core_state_filtered_out():
    item = _real_item()
    item["location"]["stateCode"] = "GA"
    assert mod._to_listing(item, "national.trulia") is None


def test_scraper_registered():
    from foreclosure_scraper.scrapers._registry import all_scrapers

    assert "national.trulia" in {s.slug for s in all_scrapers()}
