"""national.realtor_foreclosures — HERMES extraction-completeness audit,
batch 18 (2026-10-04). No test file existed for this scraper before this
batch.

Two real gaps found and fixed:

1. SEARCH_LOCATIONS queried HomeHarvest by CITY/SEAT name ("Asheville, NC")
   instead of the whole county -- the exact under-coverage bug class batch
   17 found and fixed on the sibling national.homeharvest. Live-verified
   2026-10-04: "Asheville, NC" -> 2 rows vs "Buncombe County, NC" -> 3 rows
   (foreclosure=True, past_days=180); "Myrtle Beach, SC" (10) + "North
   Myrtle Beach, SC" (0) vs "Horry County, SC" (13) -- county-wide is a
   strict superset, not a dedup of the city queries. Fixed by replacing
   every city anchor with its real county (resolved via the same
   upstate/coastal/bankruptcy gazetteers other scrapers already use) and
   deduping counties shared by multiple cities (18 city entries -> 13
   unique counties).

2. last_sold_price/last_sold_date/sold_price/hoa_fee/stories/
   new_construction are already on this scraper's own HomeHarvest row
   (zero extra requests) but were never read -- same gap batch 17 fixed on
   national.homeharvest. Live-verified 2026-10-04 against a real current
   Horry County, SC query: 9/13 rows carry a real last_sold_price, 12/13 a
   real hoa_fee.
"""
from __future__ import annotations

import math

from foreclosure_scraper.scrapers.national import realtor_foreclosures as m
from foreclosure_scraper.web_artifact import RAW_KEEP, _slim_raw


def _row(**overrides) -> dict:
    base = {
        "property_url": "https://www.realtor.com/realestateandhomes-detail/1",
        "status": "for_sale",
        "mls_status": "Active",
        "text": "Foreclosure opportunity, bank owned.",
        "street": "1 Test St",
        "city": "Myrtle Beach",
        "state": "SC",
        "zip_code": "29577",
        "county": "Horry County",
        "list_price": 150000,
        "beds": 3,
        "full_baths": 2,
        "half_baths": 1,
        "sqft": 1500,
        "lot_sqft": 6000,
        "estimated_value": 160000,
        "assessed_value": 140000,
        "year_built": "2001",
        "latitude": 33.68,
        "longitude": -78.88,
        "primary_photo": "https://example.com/photo.jpg",
        "alt_photos": "https://example.com/a.jpg, https://example.com/b.jpg",
        "agent_name": "Jane Agent",
        "agent_email": "jane@example.com",
        "agent_phones": "843-555-0100",
        "office_name": "Test Realty",
        "office_phones": "843-555-0101",
        "broker_name": "Test Broker",
        "mls_id": "MLS123",
        "last_sold_price": 95000,
        "last_sold_date": "2023-05-01",
        "sold_price": float("nan"),
        "hoa_fee": 45,
        "stories": 2,
        "new_construction": False,
    }
    base.update(overrides)
    return base


def test_basic_mapping():
    li = m._to_listing(_row(), m.RealtorForeclosures.slug)
    assert li is not None
    assert li.state == "SC"
    assert li.county == "Horry"  # row's raw "Horry County" has the " County" suffix stripped
    assert li.bedrooms == 3.0
    assert li.bathrooms == 2.0
    assert li.living_sqft == 1500.0


def test_sale_history_and_property_detail_fields_captured():
    """FOUND batch 18: last_sold_price/last_sold_date/sold_price/hoa_fee/
    stories/new_construction are on the real HomeHarvest row but were never
    read before this fix."""
    li = m._to_listing(_row(), m.RealtorForeclosures.slug)
    realtor = li.raw["realtor"]
    assert realtor["last_sold_price"] == 95000.0
    assert realtor["last_sold_date"] == "2023-05-01"
    assert realtor["sold_price"] is None  # NaN normalizes to None
    assert realtor["hoa_fee"] == 45.0
    assert realtor["stories"] == 2.0
    assert realtor["new_construction"] is False


def test_sale_history_fields_survive_slim_raw_round_trip():
    """realtor is already wildcarded in RAW_KEEP -- pin that the new fields
    actually survive the real publish-time filter, not just _to_listing."""
    assert RAW_KEEP.get("realtor") == "*"
    li = m._to_listing(_row(), m.RealtorForeclosures.slug)
    slim = _slim_raw(li.raw)
    assert slim["realtor"]["last_sold_price"] == 95000.0
    assert slim["realtor"]["hoa_fee"] == 45.0


def test_missing_sale_history_does_not_crash():
    li = m._to_listing(_row(last_sold_price=None, last_sold_date=None,
                             sold_price=None, hoa_fee=None, stories=None,
                             new_construction=None),
                        m.RealtorForeclosures.slug)
    assert li is not None
    realtor = li.raw["realtor"]
    assert realtor["last_sold_price"] is None
    assert realtor["new_construction"] is None


def test_search_locations_are_county_wide_not_city_seat_only():
    """FOUND batch 18: every entry must be a '<County> County, <ST>' string
    (the convention national.homeharvest already uses for whole-county
    coverage), not a bare city/seat name -- a bare city under-counts
    relative to the real county (live-verified: Asheville 2 vs Buncombe
    County 3; Myrtle Beach+North Myrtle Beach 10 vs Horry County 13)."""
    assert len(m.SEARCH_LOCATIONS) >= 10
    for loc in m.SEARCH_LOCATIONS:
        assert "County, " in loc, f"{loc!r} is not a county-wide location string"
    # No duplicate counties (the whole point of deduping the old 18-city list).
    assert len(set(m.SEARCH_LOCATIONS)) == len(m.SEARCH_LOCATIONS)
    # The old bare city-only strings must be gone.
    old_city_only_strings = (
        "Asheville, NC", "Hickory, NC", "Wilmington, NC",
        "Myrtle Beach, SC", "North Myrtle Beach, SC", "Charleston, SC",
    )
    for old in old_city_only_strings:
        assert old not in m.SEARCH_LOCATIONS


def test_known_footprint_and_coastal_counties_present():
    expected = {
        "Buncombe County, NC", "Catawba County, NC", "Spartanburg County, SC",
        "New Hanover County, NC", "Brunswick County, NC", "Pender County, NC",
        "Carteret County, NC", "Dare County, NC", "Horry County, SC",
        "Georgetown County, SC", "Charleston County, SC", "Colleton County, SC",
        "Beaufort County, SC",
    }
    assert expected.issubset(set(m.SEARCH_LOCATIONS))


def test_nan_half_baths_normalizes_to_none():
    li = m._to_listing(_row(half_baths=float("nan")), m.RealtorForeclosures.slug)
    assert li.raw["realtor"]["half_baths"] is None


def test_no_url_returns_none():
    row = _row()
    row["property_url"] = None
    row["permalink"] = None
    assert m._to_listing(row, m.RealtorForeclosures.slug) is None
