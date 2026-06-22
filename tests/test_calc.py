"""Regression tests for the investor calculator (valuation/calc.py).

Each test pins a single behavior — the audit surfaced these issues and
they must not regress on future weekly runs (investors will use this
data to make purchase decisions).
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


# ---------- ARV anchor guard scoping ----------

def test_anchor_guard_does_not_fire_for_foreclosure_source():
    """A foreclosure-source listing with comp ARV 2x its bid must keep the
    comp ARV. Auction floor and ARV are *supposed* to be far apart."""
    li = _li(
        source="counties_sc.spartanburg_master_in_equity",
        opening_bid=70_000.0,
        living_sqft=1100.0,
        property_kind=PropertyKind.SINGLE_FAMILY,
        raw={
            "comps": [{"sold_price": 145_000, "sqft": 1100, "price_per_sqft": 132}] * 3,
            "comp_median_ppsf": 132.0,
        },
    )
    c = vcalc.compute(li)
    # Comp-grounded ARV: 132 × 1100 ≈ 145,200
    assert c.arv_expected is not None
    assert c.arv_expected > 100_000, (
        f"foreclosure ARV got clamped to bid; expected ~145k, got {c.arv_expected}"
    )
    assert "retail source" not in " ".join(c.notes), \
        "anchor guard fired for non-retail source — should be scoped"


def test_anchor_guard_preserves_arv_when_listing_far_below_comps():
    """A HomeHarvest listing whose asking price is far BELOW comp ARV must
    NOT have its ARV clamped — that's exactly the high-discount flip
    opportunity an investor wants to see. Only annotate the wide gap."""
    li = _li(
        source="national.homeharvest",
        opening_bid=70_000.0,                # asking $70k
        living_sqft=1500.0,
        property_kind=PropertyKind.SINGLE_FAMILY,
        raw={
            "comps": [{"sold_price": 210_000, "sqft": 1500, "price_per_sqft": 140}] * 3,
            "comp_median_ppsf": 140.0,        # comp ARV ≈ $210k → ratio 3.0
        },
    )
    c = vcalc.compute(li)
    # ARV must stay at comp value — investor needs to see the spread.
    assert c.arv_expected is not None and c.arv_expected > 150_000, (
        f"investor flip signal got clamped; arv={c.arv_expected}"
    )
    assert any("high-discount" in n for n in c.notes)


def test_anchor_guard_fires_when_comps_too_low():
    """A HomeHarvest listing whose comp ARV is < 60% of asking is more
    likely a comp data problem (wrong zip cluster, wrong property type)
    than a real overpricing — anchor to listing as a floor."""
    li = _li(
        source="national.homeharvest",
        opening_bid=300_000.0,
        living_sqft=1500.0,
        property_kind=PropertyKind.SINGLE_FAMILY,
        raw={
            "comps": [{"sold_price": 100_000, "sqft": 1500, "price_per_sqft": 67}] * 3,
            "comp_median_ppsf": 67.0,
        },
    )
    c = vcalc.compute(li)
    # ratio = 100k / 300k = 0.33 → anchor up
    assert c.arv_expected == 300_000.0
    assert any("comps appear too low" in n for n in c.notes)


def test_anchor_guard_does_not_fire_for_distressed():
    """homeharvest_distressed listings are *supposed* to be below ARV
    (motivated sellers). Anchor guard must NOT fire."""
    li = _li(
        source="national.distressed",
        opening_bid=70_000.0,
        living_sqft=1100.0,
        property_kind=PropertyKind.SINGLE_FAMILY,
        raw={
            "comps": [{"sold_price": 145_000, "sqft": 1100, "price_per_sqft": 132}] * 3,
            "comp_median_ppsf": 132.0,
        },
    )
    c = vcalc.compute(li)
    assert c.arv_expected is not None
    assert c.arv_expected > 100_000


# ---------- Vision rehab application (the user's main complaint) ----------

def test_vision_rehab_psf_overrides_generic_tier():
    """Vision's photo-grounded $/sqft must drive rehab when present —
    the user paid for Vision specifically to get accurate rehab numbers."""
    li = _li(
        source="national.homeharvest",
        living_sqft=1110.0,
        property_kind=PropertyKind.SINGLE_FAMILY,
        raw={
            "vision": {
                "condition_tier": "major",
                "confidence": "HIGH",
                "rehab_psf_low": 40,
                "rehab_psf_high": 75,
            },
            "condition_tier": "major",
            "condition_source": "vision-HIGH",
        },
    )
    c = vcalc.compute(li)
    # Vision says 40-75 $/sqft × 1110 = 44,400-83,250 (rounded to -2)
    assert c.rehab_low == 44_400.0
    assert c.rehab_high == 83_200.0
    # Mid: (40+75)/2 = 57.5 → 57.5 × 1110 = 63,825 → 63,800
    assert c.rehab_expected == 63_800.0
    assert any("Rehab from Vision photos" in n for n in c.notes)


def test_vision_tier_read_from_raw_vision_path():
    """_condition_to_tier must look at raw.vision.condition_tier, not just
    raw.condition_tier (which the legacy enrichment_comps mirror sets)."""
    li = _li(
        source="national.homeharvest",
        living_sqft=1500.0,
        property_kind=PropertyKind.SINGLE_FAMILY,
        raw={
            # ONLY raw.vision.condition_tier set — no top-level mirror.
            "vision": {"condition_tier": "gut", "confidence": "HIGH"},
        },
    )
    c = vcalc.compute(li)
    assert c.rehab_tier == "gut", f"vision tier ignored; got {c.rehab_tier}"


# ---------- Mobile-home rehab tier ----------

def test_mobile_home_uses_mobile_rehab_table():
    """Mobile/manufactured homes must use the cheaper MOBILE_REHAB_TIERS
    table (vinyl skirting, single-pane windows). Standard SFR cost is 30-50%
    too high for these."""
    sf_li = _li(
        property_kind=PropertyKind.SINGLE_FAMILY,
        living_sqft=1200.0, year_built=1985, raw={"condition_tier": "major"},
    )
    mh_li = _li(
        property_kind=PropertyKind.MOBILE,
        living_sqft=1200.0, year_built=1985, raw={"condition_tier": "major"},
    )
    sf_c = vcalc.compute(sf_li)
    mh_c = vcalc.compute(mh_li)
    # Mobile must be strictly cheaper at the same tier
    assert mh_c.rehab_expected < sf_c.rehab_expected, (
        f"mobile rehab not cheaper: mobile={mh_c.rehab_expected}, sfr={sf_c.rehab_expected}"
    )
    assert any("(mobile)" in n for n in mh_c.notes)
    assert any("(standard)" in n for n in sf_c.notes)


# ---------- sqft-missing refusal ----------

def test_refuses_rehab_when_sqft_missing_for_sfr():
    """SFR with no living_sqft must NOT get an invented sqft. We can't
    confidently estimate rehab without knowing how big the house is."""
    li = _li(
        source="national.homeharvest",
        property_kind=PropertyKind.SINGLE_FAMILY,
        living_sqft=None,
        opening_bid=100_000.0,
    )
    c = vcalc.compute(li)
    assert c.rehab_expected is None, (
        f"rehab should be None without sqft; got {c.rehab_expected}"
    )
    assert c.rehab_tier == "unknown"
    assert any("living_sqft missing" in n for n in c.notes)


def test_land_still_zero_rehab_with_no_sqft():
    """Raw land doesn't have living_sqft and that's correct — rehab=0."""
    li = _li(
        source="national.homeharvest",
        property_kind=PropertyKind.LAND,
        living_sqft=None,
        opening_bid=15_000.0,
        acreage=0.5,
    )
    c = vcalc.compute(li)
    assert c.rehab_expected == 0.0
    assert c.rehab_tier == "land"


# ---------- Land $/acre ARV path ----------

def test_land_arv_uses_dollar_per_acre_from_comps():
    li = _li(
        source="counties_sc.spartanburg_master_in_equity",
        property_kind=PropertyKind.LAND,
        living_sqft=None,
        acreage=2.0,
        opening_bid=15_000.0,
        raw={
            "comps": [
                # 4 comparable land sales — 1 acre each, sold for varying prices.
                # 43560 sqft = 1 acre.
                {"sold_price": 30_000, "lot_sqft": 43_560, "kind": "land"},
                {"sold_price": 35_000, "lot_sqft": 43_560, "kind": "land"},
                {"sold_price": 40_000, "lot_sqft": 43_560, "kind": "land"},
                {"sold_price": 45_000, "lot_sqft": 43_560, "kind": "land"},
            ],
        },
    )
    c = vcalc.compute(li)
    # Median $/ac is ~$37.5k; subject is 2 ac → ~$75k ARV
    assert c.arv_expected is not None
    assert 60_000 <= c.arv_expected <= 90_000, (
        f"land ARV not in expected range: {c.arv_expected}"
    )
    assert any("land comps" in n for n in c.notes)


def test_land_falls_back_to_tax_value_when_no_comps():
    li = _li(
        property_kind=PropertyKind.LAND,
        acreage=0.5,
        tax_value=20_000.0,
        living_sqft=None,
        opening_bid=10_000.0,
    )
    c = vcalc.compute(li)
    assert c.arv_expected is not None
    # tax_value × 1.10 ≈ 22k
    assert 19_000 <= c.arv_expected <= 25_000


# ---------- 70% rule sanity ----------

def test_seventy_pct_rule_max_bid_with_vision_rehab():
    """End-to-end: Vision rehab + retail-source guard NOT firing →
    max_bid_70 reflects real comp ARV, not bid-anchored ARV."""
    li = _li(
        source="counties_sc.spartanburg_master_in_equity",
        opening_bid=70_000.0,
        living_sqft=1100.0,
        property_kind=PropertyKind.SINGLE_FAMILY,
        raw={
            "comps": [{"sold_price": 145_000, "sqft": 1100, "price_per_sqft": 132}] * 3,
            "comp_median_ppsf": 132.0,
            "vision": {
                "condition_tier": "major",
                "confidence": "HIGH",
                "rehab_psf_low": 40, "rehab_psf_high": 75,
            },
            "condition_tier": "major", "condition_source": "vision-HIGH",
        },
    )
    c = vcalc.compute(li)
    # Comp ARV ~145k, vision-adjusted -5% for major tier ~138k.
    # Rehab from vision: ~58k (mid 57.5/sqft × 1100).
    # Max bid 70% rule: 0.7 × 138k - 58k - 9.7k(7%) ≈ 28k.
    # The point: ARV is comp-grounded, not bid-anchored.
    assert c.arv_expected > 100_000, f"ARV got clamped: {c.arv_expected}"
    assert c.max_bid_70 is not None and c.max_bid_70 > 0
    # Bid 70k > max 28k → deal_status = NEGOTIATE or PASS
    assert c.deal_status in ("NEGOTIATE", "PASS", "OK", "GREAT")


# ---- ARV-method confidence (2026-06-21) ----
# arv_conf was computed in compute() but never stored on the Calc object, so
# grading.py's getattr(c, "arv_confidence") was always None and the
# grade-withhold logic silently degraded to "has opening_bid" only. These pin
# the fix + the tax/appraised-value -> MEDIUM upgrade that makes GIS-backfilled
# listings gradeable.

def test_arv_confidence_is_persisted_on_calc():
    c = vcalc.compute(_li(tax_value=150_000))
    assert c.arv_confidence in ("HIGH", "MEDIUM", "LOW")


def test_tax_value_arv_is_medium_confidence():
    c = vcalc.compute(_li(tax_value=200_000))
    assert c.arv_expected and c.arv_expected > 0
    assert c.arv_confidence == "MEDIUM"


def test_opening_bid_only_arv_is_low_confidence():
    c = vcalc.compute(_li(opening_bid=50_000))
    assert c.arv_confidence == "LOW"


def test_tax_value_listing_is_gradeable():
    from foreclosure_scraper.valuation import grading as vgrade
    li = _li(tax_value=180_000, county="Henderson", state="NC",
             living_sqft=1500, year_built=1995)
    c = vcalc.compute(li)
    g = vgrade.grade(li, c)
    assert g.overall is not None  # MEDIUM ARV -> assessable -> actually rated


def test_dataless_listing_grade_still_withheld():
    from foreclosure_scraper.valuation import grading as vgrade
    li = _li(county="Henderson", state="NC")  # no bid, no value, no comps
    c = vcalc.compute(li)
    g = vgrade.grade(li, c)
    assert g.overall is None  # nothing to assess -> withheld (honest)
