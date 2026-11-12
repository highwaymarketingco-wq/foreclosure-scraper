"""Tests for the buy-and-hold (rental) verdict path in calc.py.

Investors who'd rather hold than flip need cap-rate, cashflow, and a
verdict — alongside the existing flip math. This is a strict superset
of the prior calculator: nothing changes for flip-only data.
"""
from __future__ import annotations

from datetime import datetime

from foreclosure_scraper.models import Listing, ListingType, PropertyKind
from foreclosure_scraper.valuation import calc as vcalc


def _li(**kw) -> Listing:
    base = dict(
        source="counties_sc.spartanburg_master_in_equity",
        source_url="http://x", listing_type=ListingType.FORECLOSURE_SALE,
        property_kind=PropertyKind.SINGLE_FAMILY,
        first_seen=datetime.utcnow(), last_seen=datetime.utcnow(),
        raw={},
    )
    base.update(kw)
    return Listing(**base)


def test_hold_status_great_for_high_cap_rate():
    """$50k bid, 1500 sqft, $1.50/sqft rent ($2,250/mo, $27,000/yr).
    NOI = $13,500/yr.  Acquisition ≈ $52k (with 4% closing).
    Cap rate ≈ 26%."""
    li = _li(
        opening_bid=50_000.0,
        living_sqft=1500.0,
        property_kind=PropertyKind.SINGLE_FAMILY,
        raw={
            "comps": [{"sold_price": 200_000, "sqft": 1500, "price_per_sqft": 133}] * 3,
            "comp_median_ppsf": 133.0,
            "rent_median_ppsf": 1.5,
        },
    )
    c = vcalc.compute(li)
    assert c.monthly_rent_est == 2_250.0
    assert c.annual_gross_rent == 27_000.0
    assert c.noi_annual == 13_500.0
    # All-in acq ≈ $50k + $82.5k rehab + $2k closing = $134k → cap ~10%
    assert c.cap_rate_pct is not None and c.cap_rate_pct >= 9
    assert c.hold_status == "GREAT"
    # Rent $2,250 vs $50k bid = 4.5% → 1% rule passes (well above 1%)
    assert c.one_pct_rule is True


def test_hold_status_pass_for_low_cap_rate():
    """$300k bid, 1500 sqft, $0.50/sqft rent → cap rate way under 5%."""
    li = _li(
        source="national.distressed",
        opening_bid=300_000.0,
        living_sqft=1500.0,
        property_kind=PropertyKind.SINGLE_FAMILY,
        raw={
            "comps": [{"sold_price": 280_000, "sqft": 1500, "price_per_sqft": 187}] * 3,
            "comp_median_ppsf": 187.0,
            "rent_median_ppsf": 0.5,
        },
    )
    c = vcalc.compute(li)
    # gross rent $750/mo × 12 = $9,000/yr → NOI $4,500
    # acq ~ $300k + closing → cap ~1.5%
    assert c.cap_rate_pct is not None
    assert c.cap_rate_pct < 5
    assert c.hold_status == "PASS"
    assert c.one_pct_rule is False


def test_hold_skipped_for_land():
    li = _li(
        property_kind=PropertyKind.LAND,
        opening_bid=15_000.0,
        acreage=0.5,
        raw={"rent_median_ppsf": 1.0},  # nonsensical for land
    )
    c = vcalc.compute(li)
    assert c.hold_status is None
    assert c.monthly_rent_est is None


def test_hold_skipped_when_no_rent_data():
    li = _li(
        opening_bid=80_000.0,
        living_sqft=1200.0,
        property_kind=PropertyKind.SINGLE_FAMILY,
        raw={
            "comps": [{"sold_price": 150_000, "sqft": 1200, "price_per_sqft": 125}] * 3,
            "comp_median_ppsf": 125.0,
            # No rent_median_ppsf
        },
    )
    c = vcalc.compute(li)
    assert c.hold_status is None
    assert c.monthly_rent_est is None
    # Flip path still works
    assert c.deal_status is not None


def test_flip_and_hold_coexist():
    """A property that's both a good flip AND a good hold should yield
    both verdicts."""
    li = _li(
        opening_bid=60_000.0,
        living_sqft=1100.0,
        property_kind=PropertyKind.SINGLE_FAMILY,
        raw={
            "comps": [{"sold_price": 145_000, "sqft": 1100, "price_per_sqft": 132}] * 3,
            "comp_median_ppsf": 132.0,
            "rent_median_ppsf": 1.3,
            "vision": {"condition_tier": "cosmetic", "confidence": "HIGH",
                       "rehab_psf_low": 10, "rehab_psf_high": 25},
            "condition_tier": "cosmetic",
            "condition_source": "vision-HIGH",
        },
    )
    c = vcalc.compute(li)
    assert c.deal_status in ("GREAT", "OK", "NEGOTIATE", "PASS")
    assert c.hold_status in ("GREAT", "OK", "NEGOTIATE", "PASS")
    assert c.cap_rate_pct is not None


def test_one_pct_rule_threshold():
    """Right at 1% — verify the boolean."""
    li = _li(
        opening_bid=100_000.0,
        living_sqft=1000.0,
        property_kind=PropertyKind.SINGLE_FAMILY,
        raw={
            "comps": [{"sold_price": 200_000, "sqft": 1000, "price_per_sqft": 200}] * 3,
            "comp_median_ppsf": 200.0,
            "rent_median_ppsf": 1.10,  # rent $1100/mo on $100k acq → 1.1% > 1%
        },
    )
    c = vcalc.compute(li)
    assert c.one_pct_rule is True
