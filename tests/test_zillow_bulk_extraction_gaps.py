"""national.zillow_bulk — HERMES extraction-completeness audit, national
batch 5 (2026-10-04).

zillow_bulk.py (sold-foreclosure-comps) is a near-line-for-line sibling of
national.zillow_foreclosures (active listings), which batch 18 audited and
fixed the same day for the identical RAW_KEEP silent-drop pattern plus
several free, zero-marginal-cost fields on the same already-fetched item.
This file applies the same fix here (see module docstring for the full
writeup); unlike the sibling, no `_ltype()` classification fix is needed --
this scraper always hardcodes `listing_type=REO` since it feeds the sold-comp
pool, not the active-leads pool.

Fixture built from a realistic real-shaped item (same field names/shapes the
sibling's test file captured live 2026-10-04 off the real __NEXT_DATA__
payload).
"""
from __future__ import annotations

from foreclosure_scraper.models import ListingType
from foreclosure_scraper.scrapers.national import zillow_bulk as m
from foreclosure_scraper.web_artifact import RAW_KEEP, _slim_raw


def _real_item(**overrides) -> dict:
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
        "statusText": "Sold",
        "statusType": "SOLD",
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
            ],
        },
        "hdpData": {
            "homeInfo": {
                "homeType": "SINGLE_FAMILY",
                "county": None,
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


def test_always_classified_reo_regardless_of_marketing_status():
    """Unlike the active-listings sibling, this scraper always hardcodes
    REO -- it feeds the sold-comp pool, so no _ltype() fix is needed."""
    li = m._to_listing(_real_item(), "NC", "national.zillow_bulk")
    assert li is not None
    assert li.listing_type == ListingType.REO


def test_beds_baths_area_promoted_to_first_class_fields():
    li = m._to_listing(_real_item(), "NC", "national.zillow_bulk")
    assert li.bedrooms == 3
    assert li.bathrooms == 2
    assert li.living_sqft == 1400


def test_zestimate_promoted_to_market_value():
    li = m._to_listing(_real_item(), "NC", "national.zillow_bulk")
    assert li.market_value == 196100.0


def test_lot_area_acres_converted_to_sqft():
    li = m._to_listing(_real_item(), "NC", "national.zillow_bulk")
    assert li.lot_size_sqft is not None
    assert abs(li.lot_size_sqft - 15389.748) < 0.01


def test_full_photo_gallery_captured_not_just_single_imgsrc():
    li = m._to_listing(_real_item(), "NC", "national.zillow_bulk")
    photos = li.raw["images"]["real"]
    assert len(photos) == 2
    assert photos[0] == "https://photos.zillowstatic.com/fp/61cae0e462da9119c485fd0aaa8085d1-p_e.jpg"


def test_photo_gallery_falls_back_to_imgsrc_when_carousel_absent():
    item = _real_item()
    item["carouselPhotosComposable"] = None
    li = m._to_listing(item, "NC", "national.zillow_bulk")
    assert li.raw["images"]["real"] == ["https://photos.zillowstatic.com/fp/single-fallback.jpg"]


def test_broker_name_and_occupancy_signals_captured_in_namespaced_raw():
    li = m._to_listing(_real_item(), "NC", "national.zillow_bulk")
    zb = li.raw["zillow_bulk"]
    assert zb["broker_name"] == "NorthGroup Real Estate LLC"
    assert zb["is_non_owner_occupied"] is True
    assert zb["is_zillow_owned"] is False
    assert zb["days_on_zillow"] == 40
    assert zb["rent_zestimate"] == 1893
    # Previously-dropped flat fields now namespaced too.
    assert zb["marketing_status"] == "RecentChange"
    assert zb["status_text"] == "Sold"
    assert zb["home_type"] == "SINGLE_FAMILY"
    assert zb["beds"] == 3
    assert zb["baths"] == 2
    assert zb["area"] == 1400


def test_zillow_bulk_key_registered_in_raw_keep():
    assert RAW_KEEP.get("zillow_bulk") == "*"


def test_previously_dropped_fields_survive_slim_raw_round_trip():
    """Direct regression pin for the silent-drop bug this batch found."""
    li = m._to_listing(_real_item(), "NC", "national.zillow_bulk")
    slim = _slim_raw(li.raw)
    assert slim.get("zillow_bulk") == li.raw["zillow_bulk"]
    assert slim.get("zpid") == li.raw["zpid"]
    assert slim.get("sold_comp") == li.raw["sold_comp"]


def test_zero_or_missing_zestimate_and_lot_area_do_not_crash():
    item = _real_item(zestimate=None)
    item["hdpData"]["homeInfo"]["lotAreaValue"] = None
    item["hdpData"]["homeInfo"]["lotAreaUnit"] = None
    li = m._to_listing(item, "NC", "national.zillow_bulk")
    assert li is not None
    assert li.market_value is None
    assert li.lot_size_sqft is None


def test_scraper_registered():
    from foreclosure_scraper.scrapers._registry import all_scrapers

    assert "national.zillow_bulk" in {s.slug for s in all_scrapers()}
