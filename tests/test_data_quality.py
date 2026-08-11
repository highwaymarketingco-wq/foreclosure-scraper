"""Tests for the data-quality flag enrichment.

Investor-facing caveats — surfaces in dashboard/sheet/email so a user
making a purchase decision sees "this address is a placeholder, verify"
rather than treating a synthetic value as authoritative.
"""
from __future__ import annotations

from datetime import datetime

from foreclosure_scraper.enrichment_data_quality import (
    NO_CAVEATS_SUMMARY,
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


def test_arv_confidence_prefers_persisted_field_over_notes():
    # calc.arv_confidence is authoritative; the comp note would say HIGH but the
    # engine capped it to MEDIUM (e.g. estimated sqft) — the field must win.
    li = _li(raw={"calc": {"arv_confidence": "MEDIUM",
                           "notes": ["ARV from 3 zip-matched sold comps × subject sqft"]}})
    assert _arv_confidence(li) == "MEDIUM"


def test_flags_sqft_estimated_from_footprint():
    li = _li(street_address="123 Real St", living_sqft=1800.0,
             property_kind=PropertyKind.SINGLE_FAMILY,
             raw={"calc": {"arv_confidence": "MEDIUM", "notes": ["ARV from comps × subject sqft"]},
                  "footprint": {"estimated": True, "est_living_sqft": 1800}})
    enrich_data_quality([li])
    dq = li.raw["data_quality"]
    assert "sqft_estimated" in dq["flags"]
    assert "ESTIMATE" in dq["summary"]


def test_flags_arv_outlier_on_high_proxy_no_comps():
    li = _li(street_address="123 Real St", living_sqft=None,
             property_kind=PropertyKind.SINGLE_FAMILY,
             raw={"calc": {"arv_confidence": "MEDIUM", "arv_expected": 9_000_000,
                           "notes": ["ARV from tax-assessed × 1.25"]}})
    enrich_data_quality([li])
    assert "arv_outlier" in li.raw["data_quality"]["flags"]
    assert "outlier" in li.raw["data_quality"]["summary"].lower()


def test_no_arv_outlier_when_comp_grounded():
    li = _li(street_address="123 Real St", living_sqft=2000.0,
             raw={"calc": {"arv_confidence": "HIGH", "arv_expected": 9_000_000,
                           "notes": ["ARV from comps × subject sqft"]},
                  "comp_median_ppsf": 200})
    enrich_data_quality([li])
    assert "arv_outlier" not in li.raw["data_quality"]["flags"]


def test_clean_listing_has_empty_flags():
    li = _li(
        street_address="123 Real St", living_sqft=1500.0,
        property_kind=PropertyKind.SINGLE_FAMILY,
        raw={"calc": {"notes": ["ARV from 3 zip-matched sold comps × subject sqft"]}},
    )
    enrich_data_quality([li])
    dq = li.raw["data_quality"]
    assert dq["flags"] == []
    assert dq["summary"] == NO_CAVEATS_SUMMARY


# =============================================================================
# Regression locks for the bugs the operator kept catching BY HAND.
# These pin recent fixes (cross-source dup-address collapse, the ARV floor) and
# the automated board-QA verifier so they can't silently regress.
# =============================================================================

from foreclosure_scraper.dedupe import dedupe
from foreclosure_scraper.valuation import calc as valuation_calc
from foreclosure_scraper.enrichment_board_qa import enrich_board_qa


def test_dedupe_collapses_same_address_across_sources():
    """The '19 Gosnell Ave' cross-source duplicate class: the SAME street address
    arriving from two sources (one copy jamming the city into the street field, no
    shared parcel) must collapse to ONE row via the _canon_street signature."""
    a = _li(
        source="counties_sc.spartanburg_a", source_url="http://a",
        listing_type=ListingType.FORECLOSURE_SALE,
        street_address="19 Gosnell Avenue", county="Spartanburg", state="SC",
        parcel_id="1-23-45-678.00",
    )
    b = _li(
        source="counties_sc.spartanburg_b", source_url="http://b",
        listing_type=ListingType.FORECLOSURE_SALE,
        street_address="19 Gosnell Avenue Inman", county="Spartanburg", state="SC",
        parcel_id=None,
    )
    out = dedupe([a, b])
    assert len(out) == 1, f"expected 1 merged row, got {len(out)}"


def test_arv_floored_at_market_value():
    """The ARV floor: a comp-grounded ARV that lands BELOW the county market value
    (after-repair value can't sit under the as-is value) must be raised to the
    market value. Weak comps (~$60/sqft on a 1,000 sqft house ≈ $60k) against a
    $315,000 county value -> ARV floored to ~$315k."""
    li = _li(
        source="counties_sc.x", source_url="http://x",
        listing_type=ListingType.FORECLOSURE_SALE,
        property_kind=PropertyKind.SINGLE_FAMILY,
        street_address="123 Real St", living_sqft=1000.0, market_value=315000.0,
        raw={
            "comp_median_ppsf": 60.0,
            "comps": [
                {"price_per_sqft": 58.0, "sold_price": 58000, "geo_anchored": True},
                {"price_per_sqft": 60.0, "sold_price": 60000, "geo_anchored": True},
                {"price_per_sqft": 62.0, "sold_price": 62000, "geo_anchored": True},
            ],
        },
    )
    c = valuation_calc.compute(li)
    assert c.arv_expected is not None
    assert c.arv_expected >= 315000 * 0.99, (
        f"ARV {c.arv_expected} should be floored to >= the $315k as-is value"
    )


def test_board_qa_flags_arv_below_asis():
    """The board-QA verifier must CATCH an ARV that sits below the as-is value
    (a regression tripwire for the floor) by writing 'arv_below_asis'."""
    li = _li(
        source="counties_sc.x", source_url="http://x",
        listing_type=ListingType.FORECLOSURE_SALE,
        street_address="123 Real St", market_value=315000.0,
        raw={"calc": {"arv_expected": 264500.0}},
    )
    summary = enrich_board_qa([li])
    assert "arv_below_asis" in li.raw["qa_flags"]
    assert summary.get("arv_below_asis") == 1


def test_board_qa_clean_case_no_arv_flag():
    """A lead whose ARV is at/above the county value must NOT be flagged
    arv_below_asis (and a fully-populated lead carries no qa_flags at all)."""
    li = _li(
        source="counties_sc.x", source_url="http://x",
        listing_type=ListingType.FORECLOSURE_SALE,
        street_address="123 Real St", market_value=315000.0,
        owner_name="JANE DOE", living_sqft=1500.0,
        raw={"calc": {"arv_expected": 330000.0, "rehab_tier": "light"},
             "condition_tier": "cosmetic"},
    )
    summary = enrich_board_qa([li])
    assert "arv_below_asis" not in li.raw.get("qa_flags", [])
    assert summary.get("arv_below_asis", 0) == 0
    # fully-populated single lead -> no qa_flags key written at all
    assert "qa_flags" not in li.raw


def test_board_qa_flags_rehab_vs_condition():
    """Good condition (cosmetic) but a heavy rehab tier (gut) is a contradiction."""
    li = _li(
        source="counties_sc.x", source_url="http://x",
        listing_type=ListingType.FORECLOSURE_SALE,
        street_address="123 Real St", owner_name="JANE DOE", living_sqft=1500.0,
        raw={"condition_tier": "cosmetic", "calc": {"rehab_tier": "gut"}},
    )
    enrich_board_qa([li])
    assert "rehab_vs_condition" in li.raw["qa_flags"]


def test_board_qa_flags_missing_last_sale():
    """Assessor sale DATE present but the surfaced raw.last_sale empty -> flag it."""
    li = _li(
        source="counties_sc.x", source_url="http://x",
        listing_type=ListingType.FORECLOSURE_SALE,
        street_address="123 Real St", owner_name="JANE DOE", living_sqft=1500.0,
        raw={"cama": {"last_sale_date": "20220818"}},
    )
    enrich_board_qa([li])
    assert "missing_last_sale" in li.raw["qa_flags"]


def test_board_qa_dup_address_counts_groups():
    """dup_address is counted by GROUP (clusters), not by row."""
    common = dict(
        listing_type=ListingType.FORECLOSURE_SALE,
        street_address="19 Gosnell Avenue", county="Spartanburg", state="SC",
        owner_name="JANE DOE", living_sqft=1500.0,
    )
    a = _li(source="a", source_url="http://a", **common)
    b = _li(source="b", source_url="http://b", **common)
    summary = enrich_board_qa([a, b])
    assert summary.get("dup_address") == 1
    assert "dup_address" in a.raw["qa_flags"]
    assert "dup_address" in b.raw["qa_flags"]
