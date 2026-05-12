"""Pin the dedupe_key normalization (H3 fix).

The audit found that pre-normalization, common variations across
sources produced different dedup keys for the same property:
  - "123 Main St" vs "123 Main Street" vs "123 MAIN ST."
  - parcel "1234-56-7890" vs "1234567890" vs "1234-56-7890.000"
  - case "24 SP 123" vs "24SP123" vs "24-SP-123"

These tests pin the normalization helpers + the dedupe_key branches
so future refactors can't quietly regress dedup matching.
"""
from __future__ import annotations

from datetime import datetime

from foreclosure_scraper.models import (
    Listing,
    ListingType,
    _normalize_addr,
    _normalize_case,
    _normalize_parcel,
)


def _li(**kw) -> Listing:
    base = dict(
        source="test",
        source_url="https://example.com/x",
        listing_type=ListingType.FORECLOSURE_SALE,
        first_seen=datetime.utcnow(),
        last_seen=datetime.utcnow(),
    )
    base.update(kw)
    return Listing(**base)


# ---- _normalize_addr ----

def test_addr_street_expansion():
    assert _normalize_addr("123 Main Street") == "123 main st"
    assert _normalize_addr("123 Main St") == "123 main st"
    assert _normalize_addr("123 MAIN ST.") == "123 main st"


def test_addr_avenue_expansion():
    assert _normalize_addr("456 Oak Avenue") == "456 oak ave"
    assert _normalize_addr("456 Oak Ave") == "456 oak ave"
    assert _normalize_addr("456 Oak Ave.") == "456 oak ave"


def test_addr_road_drive_lane():
    assert _normalize_addr("789 Pine Road") == "789 pine rd"
    assert _normalize_addr("100 Elm Drive") == "100 elm dr"
    assert _normalize_addr("200 Birch Lane") == "200 birch ln"


def test_addr_directional_prefix():
    assert _normalize_addr("123 North Main St") == "123 n main st"
    assert _normalize_addr("123 N. Main St") == "123 n main st"
    assert _normalize_addr("456 Northeast Oak Ave") == "456 ne oak ave"


def test_addr_strips_unit():
    assert _normalize_addr("123 Main St Apt 5") == "123 main st"
    assert _normalize_addr("123 Main St #5") == "123 main st"
    assert _normalize_addr("123 Main St Unit B") == "123 main st"
    assert _normalize_addr("123 Main St Suite 200") == "123 main st"


def test_addr_strips_city_state_zip():
    """When address contains comma-separated city/state/zip, only the
    street portion is used for matching."""
    assert _normalize_addr("123 Main St, Asheville, NC 28801") == "123 main st"


def test_addr_empty_inputs():
    assert _normalize_addr(None) == ""
    assert _normalize_addr("") == ""
    assert _normalize_addr("   ") == ""


# ---- _normalize_parcel ----

def test_parcel_strips_dashes():
    assert _normalize_parcel("1234-56-7890") == "1234567890"
    assert _normalize_parcel("1234567890") == "1234567890"


def test_parcel_strips_trailing_zeros_suffix():
    """Some county GIS exports add a '.000' subparcel suffix to
    base parcels — strip when result still has substantial digits."""
    assert _normalize_parcel("1234-56-7890.000") == "1234567890"


def test_parcel_does_not_strip_significant_zeros():
    """A short parcel ending in 000 shouldn't lose those digits —
    only the .000 suffix variant should."""
    assert _normalize_parcel("12-3000") == "123000"


def test_parcel_lowercase():
    assert _normalize_parcel("PIN-1234ABCD") == "pin1234abcd"


def test_parcel_empty():
    assert _normalize_parcel(None) == ""
    assert _normalize_parcel("") == ""


# ---- _normalize_case ----

def test_case_strips_dashes_spaces():
    assert _normalize_case("24 SP 123") == "24sp123"
    assert _normalize_case("24-SP-123") == "24sp123"
    assert _normalize_case("24SP123") == "24sp123"


def test_case_handles_cv_cvs_sp():
    assert _normalize_case("23-CVS-1234") == "23cvs1234"
    assert _normalize_case("23 CV 567") == "23cv567"


def test_case_empty():
    assert _normalize_case(None) == ""
    assert _normalize_case("") == ""


# ---- dedupe_key integration ----

def test_dedupe_same_address_variants_collapse():
    """The motivating bug: 'Main Street' vs 'Main St' should produce
    the same key when the parcel is unknown."""
    a = _li(street_address="123 Main Street", zip_code="28801")
    b = _li(street_address="123 Main St", zip_code="28801")
    assert a.dedupe_key() == b.dedupe_key()


def test_dedupe_address_case_insensitive():
    a = _li(street_address="123 MAIN ST.", zip_code="28801")
    b = _li(street_address="123 Main St", zip_code="28801")
    assert a.dedupe_key() == b.dedupe_key()


def test_dedupe_address_fallback_county_when_no_zip():
    """Pre-enrich listings often have no zip — fall back to
    county+state. Same address in same county should collapse."""
    a = _li(street_address="123 Main St", county="Buncombe", state="NC")
    b = _li(street_address="123 MAIN STREET", county="Buncombe", state="NC")
    assert a.dedupe_key() == b.dedupe_key()


def test_dedupe_address_different_counties_dont_collide():
    """Same street name in two counties is different properties."""
    a = _li(street_address="123 Main St", county="Buncombe", state="NC")
    b = _li(street_address="123 Main St", county="Rutherford", state="NC")
    assert a.dedupe_key() != b.dedupe_key()


def test_dedupe_parcel_variants_collapse():
    a = _li(parcel_id="1234-56-7890", state="NC", county="Buncombe")
    b = _li(parcel_id="1234567890", state="NC", county="Buncombe")
    c = _li(parcel_id="1234-56-7890.000", state="NC", county="Buncombe")
    assert a.dedupe_key() == b.dedupe_key() == c.dedupe_key()


def test_dedupe_parcel_different_counties_dont_collide():
    """Parcel '1234' could exist in two counties — county prevents
    cross-county collisions."""
    a = _li(parcel_id="1234", state="NC", county="Buncombe")
    b = _li(parcel_id="1234", state="NC", county="Rutherford")
    assert a.dedupe_key() != b.dedupe_key()


def test_dedupe_case_number_variants_collapse():
    a = _li(case_number="24 SP 123", county="Buncombe", state="NC")
    b = _li(case_number="24-SP-123", county="Buncombe", state="NC")
    c = _li(case_number="24SP123", county="Buncombe", state="NC")
    assert a.dedupe_key() == b.dedupe_key() == c.dedupe_key()


def test_dedupe_falls_through_to_url_when_no_signals():
    """Listings with no parcel / no addr / no case still get a key
    (the URL fallback) so they don't collide indiscriminately."""
    a = _li(source_url="https://a.com/1")
    b = _li(source_url="https://b.com/2")
    assert a.dedupe_key() != b.dedupe_key()
    assert a.dedupe_key().startswith("url:")
