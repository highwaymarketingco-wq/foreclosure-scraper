"""Regression tests for the pre-write validation gate.

This is the chokepoint that prevents the audit's recurring data-quality
bugs from reaching investors. Every case here pins a specific bug.
"""
from __future__ import annotations

from datetime import datetime

from foreclosure_scraper.models import Listing, ListingType, PropertyKind
from foreclosure_scraper.validation import validate, _normalize_county


# ---- _normalize_county ------------------------------------------------------

def test_normalize_county_mcdowell():
    assert _normalize_county("Mcdowell") == "McDowell"
    assert _normalize_county("MCDOWELL") == "McDowell"
    assert _normalize_county("mcdowell") == "McDowell"
    assert _normalize_county("McDowell County") == "McDowell"


def test_normalize_county_mccormick():
    assert _normalize_county("Mccormick") == "McCormick"
    assert _normalize_county("MCCORMICK") == "McCormick"


def test_normalize_county_strips_state():
    assert _normalize_county("Mecklenburg, NC") == "Mecklenburg"


def test_normalize_county_strips_suffix():
    assert _normalize_county("Spartanburg County") == "Spartanburg"


# ---- helpers ----------------------------------------------------------------

def _li(**kw) -> Listing:
    base = dict(
        source="test", source_url="http://x",
        listing_type=ListingType.FORECLOSURE_SALE,
        property_kind=PropertyKind.SINGLE_FAMILY,
        first_seen=datetime.utcnow(), last_seen=datetime.utcnow(),
        raw={},
    )
    base.update(kw)
    return Listing(**base)


# ---- state <-> county -------------------------------------------------------

def test_county_casing_normalized_silently():
    li = _li(state="NC", county="Mcdowell")
    stats = validate([li])
    assert li.county == "McDowell"
    assert stats["county_normalized"] == 1
    assert stats["county_nulled_cross_state"] == 0


def test_cross_state_county_nulled_out():
    """SC listing tagged with Wake County (NC-only) → null county, keep listing."""
    li = _li(state="SC", county="Wake")
    stats = validate([li])
    assert li.county is None
    assert stats["county_nulled_cross_state"] == 1


def test_dual_state_county_kept_in_either_state():
    """Cherokee, Beaufort, Lee, Union exist in both NC and SC."""
    nc_li = _li(state="NC", county="Cherokee")
    sc_li = _li(state="SC", county="Cherokee")
    validate([nc_li, sc_li])
    assert nc_li.county == "Cherokee"
    assert sc_li.county == "Cherokee"


def test_unknown_state_passes_through():
    li = _li(state="NY", county="Madison")
    validate([li])
    # No NC/SC validation applied — pass-through
    assert li.county == "Madison"


# ---- parcel_id --------------------------------------------------------------

def test_parcel_too_short_nulled():
    li = _li(parcel_id="123")
    stats = validate([li])
    assert li.parcel_id is None
    assert stats["parcel_nulled_too_short"] == 1


def test_parcel_all_zeros_nulled():
    li = _li(parcel_id="0000000")
    stats = validate([li])
    assert li.parcel_id is None
    assert stats["parcel_nulled_bad_pattern"] == 1


def test_parcel_book_page_nulled():
    li = _li(parcel_id="B123P456")
    stats = validate([li])
    assert li.parcel_id is None


def test_parcel_real_kept():
    li = _li(parcel_id="906-12-07-004")
    validate([li])
    assert li.parcel_id == "906-12-07-004"


def test_parcel_long_numeric_kept():
    li = _li(parcel_id="2641302296")
    validate([li])
    assert li.parcel_id == "2641302296"


# ---- numeric bounds ---------------------------------------------------------

def test_opening_bid_zero_nulled():
    li = _li(opening_bid=0.0)
    stats = validate([li])
    assert li.opening_bid is None
    assert stats["opening_bid_zeroed"] == 1


def test_opening_bid_negative_nulled():
    li = _li(opening_bid=-5.0)
    stats = validate([li])
    assert li.opening_bid is None


def test_opening_bid_too_large_nulled():
    li = _li(opening_bid=999_999_999.0)
    stats = validate([li])
    assert li.opening_bid is None
    assert stats["opening_bid_too_large"] == 1


def test_tax_value_too_low_for_sfr_nulled():
    li = _li(tax_value=300.0, property_kind=PropertyKind.SINGLE_FAMILY)
    stats = validate([li])
    assert li.tax_value is None
    assert stats["tax_value_too_low"] == 1


def test_tax_value_low_for_land_kept():
    """Raw rural land legitimately can have low tax_value — don't null."""
    li = _li(tax_value=2_000.0, property_kind=PropertyKind.LAND)
    validate([li])
    assert li.tax_value == 2_000.0


def test_sqft_out_of_range_nulled():
    li = _li(living_sqft=99_999.0, property_kind=PropertyKind.SINGLE_FAMILY)
    stats = validate([li])
    assert li.living_sqft is None


def test_year_built_out_of_range_nulled():
    li = _li(year_built=1500)
    stats = validate([li])
    assert li.year_built is None


def test_bedrooms_unreasonable_nulled():
    li = _li(bedrooms=99)
    validate([li])
    assert li.bedrooms is None


# ---- comp validation --------------------------------------------------------

def test_comps_invalid_price_dropped():
    li = _li(
        property_kind=PropertyKind.SINGLE_FAMILY,
        raw={"comps": [
            {"sold_price": 0, "sqft": 1500, "kind": "single_family", "price_per_sqft": 0},
            {"sold_price": 200_000, "sqft": 1500, "kind": "single_family", "price_per_sqft": 133.0},
            {"sold_price": 10_000_000, "sqft": 1500, "kind": "single_family", "price_per_sqft": 6667.0},
        ], "comp_median_ppsf": 133.0},
    )
    stats = validate([li])
    assert len(li.raw["comps"]) == 1
    assert li.raw["comps"][0]["sold_price"] == 200_000
    assert stats["comps_dropped_price"] == 2


def test_comps_kind_mismatch_dropped():
    """Land comp on a SFR subject — clear category mismatch, drop."""
    li = _li(
        property_kind=PropertyKind.SINGLE_FAMILY,
        raw={"comps": [
            {"sold_price": 50_000, "kind": "land", "price_per_sqft": 50.0},
            {"sold_price": 200_000, "kind": "single_family", "price_per_sqft": 133.0},
        ]},
    )
    stats = validate([li])
    assert len(li.raw["comps"]) == 1
    assert stats["comps_dropped_kind_mismatch"] == 1


def test_comps_kind_equivalent_kept():
    """sfr ≡ single_family — must NOT drop (taxonomy alignment)."""
    li = _li(
        property_kind=PropertyKind.SINGLE_FAMILY,
        raw={"comps": [
            {"sold_price": 200_000, "kind": "sfr", "price_per_sqft": 133.0},
            {"sold_price": 220_000, "kind": "single_family", "price_per_sqft": 147.0},
            {"sold_price": 215_000, "kind": "house", "price_per_sqft": 143.0},
        ]},
    )
    stats = validate([li])
    assert len(li.raw["comps"]) == 3, "equivalent kinds should not be dropped"
    assert stats["comps_dropped_kind_mismatch"] == 0


def test_comps_townhouse_allowed_against_sfr():
    """Townhouses trade similarly to SFR for flip economics — keep both."""
    li = _li(
        property_kind=PropertyKind.SINGLE_FAMILY,
        raw={"comps": [
            {"sold_price": 200_000, "kind": "townhouse", "price_per_sqft": 133.0},
            {"sold_price": 220_000, "kind": "sfr", "price_per_sqft": 147.0},
        ]},
    )
    stats = validate([li])
    assert len(li.raw["comps"]) == 2
    assert stats["comps_dropped_kind_mismatch"] == 0


def test_comps_mobile_kept_against_manufactured():
    """mobile ≡ manufactured."""
    li = _li(
        property_kind=PropertyKind.MOBILE,
        raw={"comps": [
            {"sold_price": 50_000, "kind": "manufactured", "price_per_sqft": 45.0},
            {"sold_price": 60_000, "kind": "mobile", "price_per_sqft": 55.0},
        ]},
    )
    stats = validate([li])
    assert len(li.raw["comps"]) == 2
    assert stats["comps_dropped_kind_mismatch"] == 0


def test_comps_land_against_sfr_dropped():
    li = _li(
        property_kind=PropertyKind.LAND,
        raw={"comps": [
            {"sold_price": 200_000, "kind": "sfr", "price_per_sqft": 133.0},  # drop
            {"sold_price": 25_000, "kind": "land", "lot_sqft": 21_780},        # keep
        ]},
    )
    stats = validate([li])
    assert len(li.raw["comps"]) == 1
    assert li.raw["comps"][0]["kind"] == "land"


def test_comps_recompute_median_ppsf_after_drop():
    li = _li(
        property_kind=PropertyKind.SINGLE_FAMILY,
        raw={"comps": [
            {"sold_price": 0, "kind": "single_family", "price_per_sqft": 999.0},
            {"sold_price": 200_000, "kind": "single_family", "price_per_sqft": 100.0},
            {"sold_price": 250_000, "kind": "single_family", "price_per_sqft": 125.0},
            {"sold_price": 300_000, "kind": "single_family", "price_per_sqft": 150.0},
        ], "comp_median_ppsf": 999.0},  # bogus median from invalid comp
    )
    validate([li])
    # 999 dropped; median of [100, 125, 150] = 125
    assert li.raw["comp_median_ppsf"] == 125.0
