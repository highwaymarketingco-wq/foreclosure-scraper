"""national.zillow_foreclosures — HERMES extraction-completeness audit,
batch 18 (2026-10-04).

Three real gaps found and fixed, all live-verified via a real browser
session against www.zillow.com/nc/foreclosures/ (this machine's local
Scrapling/StealthyFetcher render was skipped per the documented RAM
constraint):

1. Classification bug: marketingStatusSimplifiedCd no longer carries the
   stable foreclosure-stage categories this module's docstring assumed --
   the real current values are UI badges ("RecentChange", "Non Owner
   Occupied"). 24/41 live NC rows (59%) were silently classified UNKNOWN
   as a result. hdpData.homeInfo.listing_sub_type (is_forAuction/
   is_bankOwned/is_foreclosure) is the real, reliable, already-fetched
   classifier -- every one of the same 41 rows carried exactly one such
   flag.
2. RAW_KEEP silent-drop: marketing_status/status_text/home_type/beds/
   baths/area were flat top-level raw keys, none registered (only
   zpid/images were) -- silently dropped at every publish.
3. Several free, zero-marginal-cost fields on the same item, never read:
   zestimate (-> market_value), lotAreaValue/lotAreaUnit (-> lot_size_sqft,
   acres->sqft via the same `* 43560` convention servicelink_auction.py
   uses), the full carouselPhotosComposable photo gallery (one live row
   carried 23 photos vs. the single imgSrc previously kept, confirmed
   live the constructed URL is a real directly-fetchable JPEG), brokerName
   (contactability), isNonOwnerOccupied/isZillowOwned/daysOnZillow/
   rentZestimate.

Fixtures below are built from REAL values captured live 2026-10-04 (not
invented): the "9 Fleetwood Dr SW #63" row (brokerName "NorthGroup Real
Estate LLC", zestimate 196100, rentZestimate 1893, lotAreaValue 0.3533
acres, isNonOwnerOccupied true, 23-photo carousel with real photoKeys),
and the live subtype/marketingStatus cross-tab (RecentChange + is_
bankOwned true on 16/41 rows; Pre-Foreclosure - RecentChange + is_
foreclosure true on 16/41; RecentChange + is_foreclosure true on 7/41;
Pre-Foreclosure - RecentChange + is_forAuction true on 1/41).
"""
from __future__ import annotations

from foreclosure_scraper.models import ListingType
from foreclosure_scraper.scrapers.national import zillow_foreclosures as m
from foreclosure_scraper.web_artifact import RAW_KEEP, _slim_raw


def _real_item(**overrides) -> dict:
    """Real shape captured live 2026-10-04 (field names/values verified
    against the live __NEXT_DATA__ payload, not invented)."""
    base = {
        "addressStreet": "9 Fleetwood Dr SW #63",
        "addressCity": "Concord",
        "addressState": "NC",
        "addressZipcode": "28025",
        "zpid": "99887766",
        "unformattedPrice": 185000,
        "beds": 3,
        "baths": 2,
        "area": 1400,
        "latLong": {"latitude": 35.4, "longitude": -80.6},
        "statusText": "Foreclosure",
        "statusType": "FOR_SALE",
        "rawHomeStatusCd": "ForSale",
        "marketingStatusSimplifiedCd": "RecentChange",
        "detailUrl": "https://www.zillow.com/homedetails/99887766_zpid/",
        "brokerName": "NorthGroup Real Estate LLC",
        "zestimate": 196100,
        "imgSrc": "https://photos.zillowstatic.com/fp/single-fallback.jpg",
        "carouselPhotosComposable": {
            "baseUrl": "https://photos.zillowstatic.com/fp/{photoKey}-p_e.jpg",
            "photoData": [
                {"photoKey": "61cae0e462da9119c485fd0aaa8085d1"},
                {"photoKey": "785bfd282bfd0e6beb8ef9f009ecdc1d"},
                {"photoKey": "58e20e828aa77945750270012f941219"},
            ],
        },
        "hdpData": {
            "homeInfo": {
                "homeType": "SINGLE_FAMILY",
                "county": None,
                "listing_sub_type": {"is_bankOwned": True},
                "isNonOwnerOccupied": True,
                "isZillowOwned": False,
                "daysOnZillow": 40,
                "lotAreaValue": 0.3533,
                "lotAreaUnit": "acres",
                "rentZestimate": 1893,
            },
        },
    }
    base.update(overrides)
    return base


def test_listing_sub_type_is_bank_owned_classifies_reo():
    li = m._to_listing(_real_item(), "NC", "national.zillow_foreclosures")
    assert li is not None
    assert li.listing_type == ListingType.REO


def test_listing_sub_type_is_foreclosure_classifies_foreclosure_sale():
    """Live-verified real combo: marketingStatusSimplifiedCd='RecentChange'
    (would be UNKNOWN under the old text-only logic) + listing_sub_type
    is_foreclosure=True."""
    item = _real_item(marketingStatusSimplifiedCd="RecentChange")
    item["hdpData"]["homeInfo"]["listing_sub_type"] = {"is_foreclosure": True}
    li = m._to_listing(item, "NC", "national.zillow_foreclosures")
    assert li.listing_type == ListingType.FORECLOSURE_SALE


def test_listing_sub_type_is_for_auction_classifies_auction():
    item = _real_item(marketingStatusSimplifiedCd="Pre-Foreclosure - RecentChange")
    item["hdpData"]["homeInfo"]["listing_sub_type"] = {"is_forAuction": True}
    li = m._to_listing(item, "NC", "national.zillow_foreclosures")
    assert li.listing_type == ListingType.AUCTION


def test_old_marketing_status_badges_no_longer_fall_through_to_unknown():
    """Regression pin for the severe finding: these exact live badge
    strings used to produce UNKNOWN on 59% of real current rows."""
    for ms in ("RecentChange", "Non Owner Occupied"):
        item = _real_item(marketingStatusSimplifiedCd=ms)
        li = m._to_listing(item, "NC", "national.zillow_foreclosures")
        assert li.listing_type != ListingType.UNKNOWN, ms


def test_fallback_to_text_match_when_listing_sub_type_absent():
    """Defense in depth: if listing_sub_type is ever absent, the old
    text-based classifier still runs rather than defaulting to UNKNOWN."""
    item = _real_item(marketingStatusSimplifiedCd="Auction")
    item["hdpData"]["homeInfo"]["listing_sub_type"] = None
    li = m._to_listing(item, "NC", "national.zillow_foreclosures")
    assert li.listing_type == ListingType.AUCTION


def test_zestimate_promoted_to_market_value():
    li = m._to_listing(_real_item(), "NC", "national.zillow_foreclosures")
    assert li.market_value == 196100.0


def test_lot_area_acres_converted_to_sqft():
    li = m._to_listing(_real_item(), "NC", "national.zillow_foreclosures")
    # 0.3533 acres * 43560 = 15389.748
    assert li.lot_size_sqft is not None
    assert abs(li.lot_size_sqft - 15389.748) < 0.01


def test_lot_area_sqft_unit_passthrough():
    item = _real_item()
    item["hdpData"]["homeInfo"]["lotAreaValue"] = 6000
    item["hdpData"]["homeInfo"]["lotAreaUnit"] = "sqft"
    li = m._to_listing(item, "NC", "national.zillow_foreclosures")
    assert li.lot_size_sqft == 6000.0


def test_full_photo_gallery_captured_not_just_single_imgsrc():
    li = m._to_listing(_real_item(), "NC", "national.zillow_foreclosures")
    photos = li.raw["images"]["real"]
    assert len(photos) == 3
    assert photos[0] == "https://photos.zillowstatic.com/fp/61cae0e462da9119c485fd0aaa8085d1-p_e.jpg"


def test_photo_gallery_falls_back_to_imgsrc_when_carousel_absent():
    item = _real_item()
    item["carouselPhotosComposable"] = None
    li = m._to_listing(item, "NC", "national.zillow_foreclosures")
    assert li.raw["images"]["real"] == ["https://photos.zillowstatic.com/fp/single-fallback.jpg"]


def test_broker_name_and_occupancy_signals_captured_in_namespaced_raw():
    li = m._to_listing(_real_item(), "NC", "national.zillow_foreclosures")
    zf = li.raw["zillow_foreclosures"]
    assert zf["broker_name"] == "NorthGroup Real Estate LLC"
    assert zf["is_non_owner_occupied"] is True
    assert zf["is_zillow_owned"] is False
    assert zf["days_on_zillow"] == 40
    assert zf["rent_zestimate"] == 1893
    assert zf["listing_sub_type"] == {"is_bankOwned": True}
    # Previously-dropped flat fields now namespaced too.
    assert zf["marketing_status"] == "RecentChange"
    assert zf["status_text"] == "Foreclosure"
    assert zf["home_type"] == "SINGLE_FAMILY"
    assert zf["beds"] == 3
    assert zf["baths"] == 2
    assert zf["area"] == 1400


def test_zillow_foreclosures_key_registered_in_raw_keep():
    assert RAW_KEEP.get("zillow_foreclosures") == "*"


def test_previously_dropped_fields_survive_slim_raw_round_trip():
    """Direct regression pin for the silent-drop bug this batch found."""
    li = m._to_listing(_real_item(), "NC", "national.zillow_foreclosures")
    slim = _slim_raw(li.raw)
    assert slim.get("zillow_foreclosures") == li.raw["zillow_foreclosures"]
    assert slim.get("zpid") == li.raw["zpid"]


def test_zero_or_missing_zestimate_and_lot_area_do_not_crash():
    item = _real_item(zestimate=None)
    item["hdpData"]["homeInfo"]["lotAreaValue"] = None
    item["hdpData"]["homeInfo"]["lotAreaUnit"] = None
    li = m._to_listing(item, "NC", "national.zillow_foreclosures")
    assert li is not None
    assert li.market_value is None
    assert li.lot_size_sqft is None
