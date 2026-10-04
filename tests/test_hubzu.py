"""national.hubzu: 2026-10-01 national/reo per-source extraction audit.

Live-verified the /portal/auctions JSON endpoint already returns a real
per-property photo (imageUrl, protocol-relative) and the listing
agent/broker name (agentCompanyName) on every item, and neither was
captured -- the same miss class already fixed today in
national.gsa_surplus / servicelink_auction / tranzon_auctions (raw["images"]
= {"real": [...]}). Everything else (address, bid, beds/baths/sqft,
lat/lng, sale/auction-end date) was already correctly wired.
"""
from __future__ import annotations

from foreclosure_scraper.scrapers.national.hubzu import _parse_item, _photo_url

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
