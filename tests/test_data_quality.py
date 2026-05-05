"""Tests for the data-quality flag enrichment.

Investor-facing caveats — surfaces in dashboard/sheet/email so a user
making a purchase decision sees "this address is a placeholder, verify"
rather than treating a synthetic value as authoritative.
"""
from __future__ import annotations

from datetime import datetime

from foreclosure_scraper.enrichment_data_quality import (
    enrich_data_quality,
    _is_synthetic_address,
    _arv_confidence,
)
from foreclosure_scraper.models import Listing, ListingType, PropertyKind


def _li(**kw):
    base = dict(
        source="counties_sc.sc_public_index_lis_pendens", source_url="http://x",
        listing_type=ListingType.LIS_PENDENS, property_kind=PropertyKind.SINGLE_FAMILY,
        first_seen=datetime.utcnow(), last_seen=datetime.utcnow(), raw={},
    )
    base.update(kw)
    return Listing(**base)


# ---- synthetic detection ----------------------------------------------------

def test_synthetic_lis_pendens():
    assert _is_synthetic_address(_li(street_address="Lis Pendens 2026-CP-04 — Smith"))


def test_synthetic_vacant_parcel():
    assert _is_synthetic_address(_li(street_address="Vacant parcel 12345"))


def test_synthetic_bk_property():
    assert _is_synthetic_address(_li(street_address="Bk Property X"))


def test_real_address_not_flagged():
    assert _is_synthetic_address(_li(street_address="123 Main St")) is False


# ---- ARV confidence detection -----------------------------------------------

def test_arv_confidence_high_from_comps():
    li = _li(raw={"calc": {"notes": [
        "ARV from 3 zip-matched sold comps × subject sqft ($138/sqft × 1,110 sqft)"
    ]}})
    assert _arv_confidence(li) == "HIGH"


def test_arv_confidence_low_from_tax_proxy():
    li = _li(raw={"calc": {"notes": ["ARV from tax-assessed × 1.25 (75,000 × 1.25)"]}})
    assert _arv_confidence(li) == "LOW"


def test_arv_confidence_low_from_bid_proxy():
    li = _li(raw={"calc": {"notes": ["ARV proxy from opening bid × 2.4 (45,000 × 2.4) — rough"]}})
    assert _arv_confidence(li) == "LOW"


def test_arv_confidence_high_from_land_comps():
    li = _li(raw={"calc": {"notes": ["ARV from 4 land comps × 2.0 ac"]}})
    assert _arv_confidence(li) == "HIGH"


# ---- end-to-end enrichment --------------------------------------------------

def test_enrich_flags_synthetic_address():
    li = _li(street_address="Lis Pendens 2026-CP-04 — Smith John")
    enrich_data_quality([li])
    flags = li.raw["data_quality"]["flags"]
    assert "synthetic_address" in flags
    assert "placeholder" in li.raw["data_quality"]["summary"]


def test_enrich_flags_no_address():
    li = _li(street_address=None)
    enrich_data_quality([li])
    assert "no_address" in li.raw["data_quality"]["flags"]


def test_enrich_flags_no_sqft_for_sfr():
    li = _li(street_address="123 Real St", living_sqft=None,
             property_kind=PropertyKind.SINGLE_FAMILY)
    enrich_data_quality([li])
    assert "no_sqft" in li.raw["data_quality"]["flags"]


def test_enrich_does_not_flag_no_sqft_for_land():
    li = _li(street_address="0 Field Rd", living_sqft=None,
             property_kind=PropertyKind.LAND)
    enrich_data_quality([li])
    assert "no_sqft" not in li.raw["data_quality"]["flags"]


def test_enrich_flags_low_arv_when_tax_proxy():
    li = _li(
        street_address="123 Real St", living_sqft=1500.0,
        raw={"calc": {"notes": ["ARV from tax-assessed × 1.25 (75,000 × 1.25)"]}},
    )
    enrich_data_quality([li])
    assert "low_arv_confidence" in li.raw["data_quality"]["flags"]


def test_clean_listing_has_empty_flags():
    li = _li(
        street_address="123 Real St", living_sqft=1500.0,
        property_kind=PropertyKind.SINGLE_FAMILY,
        raw={"calc": {"notes": ["ARV from 3 zip-matched sold comps × subject sqft"]}},
    )
    enrich_data_quality([li])
    dq = li.raw["data_quality"]
    assert dq["flags"] == []
    assert dq["summary"] == "OK — no data-quality caveats."
