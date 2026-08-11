"""ARV sanity band — the guards that stop the engine publishing a confident fiction.

The bug these exist for, verbatim from the operator: "some of the estimated values
are off. like a trailer on a half acre will say 700k". The board really did carry
725 BRYANT RD, Spartanburg SC — a 1,400 sqft manufactured home on 0.51 acres —
at an ARV of $780,300, with a $325,300 max bid and a D grade beside it. Its comps
had produced a defensible $121,100; the ARV FLOOR then overwrote that with the
county market value of a general warehouse whose assessor record had been joined
onto the lead.

Every threshold asserted here is derived from the live 38,500-lead board and is
documented at its constant in valuation/calc.py. The last test in this file is the
regression guard that matters most: an ordinary suburban house must come through
all of it completely untouched. A fix that quietly degrades the 87% of the board
that is fine is not a fix.
"""
from __future__ import annotations

import pytest

from foreclosure_scraper.models import Listing, ListingType, PropertyKind
from foreclosure_scraper.valuation import calc as vcalc
from foreclosure_scraper.valuation import grading


def _li(**kw) -> Listing:
    base = dict(source="counties_sc.test", source_url="http://x",
                listing_type=ListingType.FORECLOSURE_SALE, state="SC",
                county="Spartanburg")
    base.update(kw)
    return Listing(**base)


def _comps(ppsf: float, n: int = 3, kind: str = "sfr") -> list[dict]:
    return [{"price_per_sqft": ppsf, "adjusted_ppsf": ppsf, "sold_price": ppsf * 1500,
             "sqft": 1500, "kind": kind, "geo_anchored": True} for _ in range(n)]


# ---------------------------------------------------------------------------
# 1. THE MANUFACTURED-HOME CASE
# ---------------------------------------------------------------------------

def test_manufactured_home_detected_from_county_land_use():
    """791 board leads are manufactured housing; only 7 carried property_kind
    MOBILE. The county already says so in `land_use` — nothing read it."""
    li = _li(property_kind=PropertyKind.SINGLE_FAMILY, land_use="Mobile Home Lot")
    assert vcalc._is_manufactured(li) is True

    # ...and from the assessor CAMA record when land_use is silent.
    li2 = _li(property_kind=PropertyKind.LAND,
              raw={"cama": {"building_type": "MOBILE HOME"}})
    assert vcalc._is_manufactured(li2) is True

    # A plain house is not swept up.
    assert vcalc._is_manufactured(
        _li(property_kind=PropertyKind.SINGLE_FAMILY, land_use="Residential")) is False


def test_manufactured_detection_does_not_override_an_explicit_kind():
    """One HUD multi-family lead carries a 'Mobile Home Lot' land_use it picked
    up from a bad parcel join. An explicitly-typed lead keeps its own kind."""
    li = _li(property_kind=PropertyKind.MULTI_FAMILY, land_use="Mobile Home Lot")
    assert vcalc._is_manufactured(li) is False


def test_manufactured_home_uses_the_cheap_rehab_table():
    """MOBILE_REHAB_TIERS existed but fired on 7 of 791 manufactured leads."""
    # Gaston NC: calibration factor 1.0, so the arithmetic is readable.
    common = dict(state="NC", county="Gaston", living_sqft=1400.0, year_built=2015,
                  raw={"comp_median_ppsf": 175.0, "comps": _comps(175.0)})
    mobile = vcalc.compute(_li(property_kind=PropertyKind.SINGLE_FAMILY,
                               land_use="Mobile Home Lot", **common))
    stick = vcalc.compute(_li(property_kind=PropertyKind.SINGLE_FAMILY,
                              land_use="Residential", **common))
    assert mobile.rehab_expected < stick.rehab_expected, (
        "manufactured rehab must be cheaper per sqft than stick-built"
    )


def test_manufactured_home_priced_off_site_built_comps_is_flagged_and_low():
    """430 board leads that are manufactured were valued off site-built comps —
    _classify_kind never read land_use, so they fell through as 'unknown' and
    _filter_by_kind coerces unknown to 'sfr'. The number is kept (it is the best
    we have) but it must not read as trustworthy."""
    li = _li(property_kind=PropertyKind.SINGLE_FAMILY, land_use="Mobile Home Lot",
             living_sqft=1400.0, year_built=1995,
             raw={"comp_median_ppsf": 90.0, "comps": _comps(90.0, kind="sfr")})
    c = vcalc.compute(li)
    assert c.arv_expected is not None
    assert "comp_kind_mismatch" in (c.arv_flags or [])
    assert c.arv_confidence == "LOW"
    assert any("manufactured" in n.lower() for n in c.notes)
    # ...and the letter grade is withheld rather than dressed up.
    assert grading.grade(li, c).overall is None


def test_manufactured_home_with_manufactured_comps_is_not_flagged():
    """Like-for-like comps are the goal, not an excuse to flag everything."""
    li = _li(property_kind=PropertyKind.MOBILE, living_sqft=1400.0, year_built=1995,
             raw={"comp_median_ppsf": 60.0, "comps": _comps(60.0, kind="manufactured")})
    c = vcalc.compute(li)
    assert "comp_kind_mismatch" not in (c.arv_flags or [])


def test_the_actual_reported_trailer():
    """725 BRYANT RD as it really sat on the board: 1,400 sqft manufactured home,
    comps at $163.71/sqft, and a GEN WHSE 50 assessor record carrying $780,300.

    Before: ARV $780,300 (= the warehouse), MEDIUM confidence, $325,300 max bid.
    After:  the comp-grounded value survives and the warehouse is refused."""
    li = _li(property_kind=PropertyKind.SINGLE_FAMILY, land_use="Mobile Home Lot",
             living_sqft=1400.0, market_value=780300.0, tax_value=780300.0,
             assessed_value=961.40, year_built=1995,
             raw={"comp_median_ppsf": 163.71, "comps": _comps(163.71),
                  "cama": {"building_type": "GEN WHSE 50", "appraised_value": 780300.0}})
    c = vcalc.compute(li)
    assert c.arv_expected is not None
    assert c.arv_expected < 300_000, (
        f"a 1,400 sqft trailer must not publish {c.arv_expected}"
    )
    assert "cama_class_mismatch" in (c.arv_flags or [])
    assert any("commercial building" in n for n in c.notes)


# ---------------------------------------------------------------------------
# 2. THE RATIO-TO-ASSESSED CASE
# ---------------------------------------------------------------------------

def test_sc_statutory_assessed_value_is_never_the_anchor():
    """SC publishes a 4%/6% RATIO value, so ARV/assessed is a units error — it
    would fire on 58.8% of SC rows and 1.4% of NC ones for the same property.
    Only 100%-basis fields may anchor."""
    li = _li(state="SC", assessed_value=961.40, market_value=16000.0)
    val, label = vcalc._anchor_value(li)
    assert val == 16000.0 and "market" in label

    # With ONLY a ratio-assessed value there is no anchor at all — silence beats
    # a ratio that means nothing.
    li2 = _li(state="SC", assessed_value=961.40)
    assert vcalc._anchor_value(li2) == (None, None)


def test_arv_vs_anchor_is_computed_on_the_PUBLISHED_number():
    """The cross-check used to run BEFORE the ARV floor, so on all 7,118 floored
    rows it described a number that had since been overwritten — one lead stored
    arv_vs_assessed 4.12 on an ARV that was really 289x its anchor."""
    li = _li(property_kind=PropertyKind.SINGLE_FAMILY, living_sqft=1500.0,
             market_value=300000.0, county="Gaston", state="NC",
             raw={"comp_median_ppsf": 100.0, "comps": _comps(100.0)})
    c = vcalc.compute(li)
    # comps say 150k, county says 300k -> floored to 300k -> ratio must be 1.0,
    # not the pre-floor 0.5.
    assert c.arv_expected == 300000
    assert c.arv_vs_assessed == pytest.approx(1.0, abs=0.02)


def test_arv_far_above_anchor_is_withheld_not_published():
    """Improved property: past 10x the county's own full-market appraisal (the
    board's p95 is 3.98x, p99 17.76x) one of the two records is describing a
    different parcel. Withhold the number AND the money derived from it."""
    li = _li(property_kind=PropertyKind.SINGLE_FAMILY, living_sqft=1500.0,
             market_value=20000.0, opening_bid=15000.0, county="Gaston", state="NC",
             raw={"comp_median_ppsf": 200.0, "comps": _comps(200.0)})
    c = vcalc.compute(li)
    assert c.arv_expected is None, "a 15x-over-anchor ARV must not publish"
    assert c.arv_withheld == 300000
    assert "arv_above_anchor_extreme" in (c.arv_flags or [])
    # The derived money must go with it — a blank bid is the point.
    assert c.max_bid_70 is None and c.roi_pct is None and c.deal_status is None
    assert grading.grade(li, c).overall is None


def test_land_gets_a_looser_anchor_band_than_a_house():
    """Land assessments lag market far harder — measured p90 is 7.61x for land
    vs 2.10x for improved. One threshold for both would either miss houses or
    gut land, so a 12x land ratio is degraded, not withheld."""
    li = _li(state="NC", county="Gaston", property_kind=PropertyKind.LAND,
             acreage=2.0, market_value=20000.0,
             raw={"comps": [{"sold_price": 120000, "lot_sqft": 87120, "kind": "land"},
                            {"sold_price": 130000, "lot_sqft": 87120, "kind": "land"}]})
    c = vcalc.compute(li)
    assert c.arv_expected is not None, "land at 12x anchor is degraded, not deleted"
    assert "arv_above_anchor" in (c.arv_flags or [])
    assert c.arv_confidence == "LOW"


def test_stale_recorded_sale_cannot_floor_the_arv():
    """933 S Liberty St published $5,600,000 off a 1992 deed for a whole
    apartment complex. 764 of 1,393 sale-floored rows had no usable date at all."""
    raw = {"comp_median_ppsf": 84.0, "comps": _comps(84.0, kind="multi"),
           "gis": {"last_sale": {"amount": 5600000, "date": "1992-06-01"}}}
    li = _li(property_kind=PropertyKind.MULTI_FAMILY, living_sqft=1800.0, raw=raw)
    c = vcalc.compute(li)
    assert c.arv_expected is not None and c.arv_expected < 200_000
    assert "stale_sale_floor" in (c.arv_flags or [])

    # An undated deed is treated exactly the same as an old one.
    raw2 = dict(raw, gis={"last_sale": {"amount": 5600000, "date": ""}})
    c2 = vcalc.compute(_li(property_kind=PropertyKind.MULTI_FAMILY,
                           living_sqft=1800.0, raw=raw2))
    assert c2.arv_expected < 200_000

    # ...but a RECENT sale still legitimately floors the ARV.
    raw3 = dict(raw, gis={"last_sale": {"amount": 180000, "date": "2024-03-15"}})
    c3 = vcalc.compute(_li(property_kind=PropertyKind.MULTI_FAMILY,
                           living_sqft=1800.0, raw=raw3))
    assert c3.arv_expected == 180000


# ---------------------------------------------------------------------------
# 3. THE $/SQFT CEILING
# ---------------------------------------------------------------------------

def test_ppsf_ceiling_is_per_county_not_one_global_number():
    """Measured county medians span 4x across the footprint ($83 Spartanburg,
    $338 Henderson), so a single absolute ceiling would either miss Spartanburg
    garbage or eat legitimate Henderson value."""
    sp = vcalc._arv_ppsf_ceiling(_li(state="SC", county="Spartanburg"), False)
    hn = vcalc._arv_ppsf_ceiling(_li(state="NC", county="Henderson"), False)
    assert hn > sp
    assert sp >= vcalc.MIN_ARV_PPSF_CEILING
    # Unknown county falls back to the board-wide median, not to infinity.
    unk = vcalc._arv_ppsf_ceiling(_li(state="NC", county="Nowhere"), False)
    assert 0 < unk < 10_000
    # Manufactured housing gets a tighter ceiling (measured 0.50 county $/sqft).
    assert vcalc._arv_ppsf_ceiling(_li(state="SC", county="Spartanburg"), True) < sp


def test_absurd_ppsf_is_withheld():
    """419 UNION ST: comps at $3,281/sqft in an $83/sqft county produced a
    $624,300 ARV on 360 sqft and a $401,400 max bid. Nothing else caught it."""
    li = _li(property_kind=PropertyKind.SINGLE_FAMILY, living_sqft=360.0,
             acreage=0.91, market_value=25099.0,
             raw={"comp_median_ppsf": 3281.25, "comps": _comps(3281.25)})
    c = vcalc.compute(li)
    assert c.arv_expected is None
    assert c.arv_withheld is not None
    assert "ppsf_ceiling" in (c.arv_flags or [])
    assert c.max_bid_70 is None


def test_ppsf_ceiling_skipped_when_the_parcel_carries_real_acreage():
    """A 700 sqft cabin on 8.5 acres is not a $400/sqft house — most of that
    value is dirt. Applying a dwelling metric there would delete real leads."""
    li = _li(property_kind=PropertyKind.SINGLE_FAMILY, living_sqft=700.0,
             acreage=8.54, market_value=250000.0)
    c = vcalc.compute(li)
    assert c.arv_expected is not None
    assert "ppsf_ceiling" not in (c.arv_flags or [])


# ---------------------------------------------------------------------------
# 4. THE LAND PATH, INCLUDING LAND THAT HAS A DWELLING ON IT
# ---------------------------------------------------------------------------

def test_land_comps_must_be_in_the_subjects_size_class():
    """0.63-acre building lots priced an 86.7-acre tract at $2,769,500. $/acre
    decays hard with size (board medians $153,523/ac at 0-1ac vs $22,744/ac at
    20-50ac), so a 100x size gap makes the comp meaningless."""
    small_lots = [{"sold_price": 21000, "lot_sqft": 27442, "kind": "land"},
                  {"sold_price": 21000, "lot_sqft": 27442, "kind": "land"},
                  {"sold_price": 70000, "lot_sqft": 108900, "kind": "land"}]
    li = _li(property_kind=PropertyKind.LAND, acreage=86.7, county="Anderson",
             raw={"comps": small_lots})
    c = vcalc.compute(li)
    assert not any("land comps ×" in n for n in c.notes), (
        "small-lot comps must not price a large tract"
    )
    assert any("Land comps rejected" in n for n in c.notes)


def test_land_comps_in_band_are_still_used():
    """The band widens rather than being all-or-nothing — comparable tracts
    must still produce a value."""
    li = _li(property_kind=PropertyKind.LAND, acreage=10.0, county="Anderson",
             raw={"comps": [{"sold_price": 100000, "lot_sqft": 8 * 43560, "kind": "land"},
                            {"sold_price": 140000, "lot_sqft": 12 * 43560, "kind": "land"},
                            {"sold_price": 120000, "lot_sqft": 10 * 43560, "kind": "land"}]})
    c = vcalc.compute(li)
    assert c.arv_expected is not None
    assert any("land comps ×" in n for n in c.notes)


def test_two_land_comps_use_the_mean_not_the_maximum():
    """`ppa_list[len//2]` on a 2-element list is index 1 — the MAX. That put a
    20-acre Henderson lead at $2,031,800 and published arv_expected ==
    arv_high, which was the tell."""
    li = _li(state="NC", county="Gaston", property_kind=PropertyKind.LAND, acreage=10.0,
             raw={"comps": [{"sold_price": 100000, "lot_sqft": 10 * 43560, "kind": "land"},
                            {"sold_price": 200000, "lot_sqft": 10 * 43560, "kind": "land"}]})
    c = vcalc.compute(li)
    assert c.arv_expected == pytest.approx(150000, abs=100)
    assert c.arv_expected < c.arv_high, "expected must sit inside its own band"
    assert c.arv_confidence != "HIGH", "two comps are not a market"


def test_land_with_a_dwelling_on_it_uses_the_sqft_path_not_dollars_per_acre():
    """A lead mis-classified LAND that plainly has a house on it must be valued
    as a house — otherwise a 1,808 sqft home gets a raw-dirt price."""
    li = _li(property_kind=PropertyKind.LAND, acreage=1.0, living_sqft=1600.0,
             year_built=1998, county="Gaston", state="NC",
             raw={"comp_median_ppsf": 120.0, "comps": _comps(120.0),
                  "comps_land": []})
    c = vcalc.compute(li)
    assert c.arv_expected == pytest.approx(192000, abs=5000)
    assert any("sqft" in n for n in c.notes)


def test_land_falls_back_to_the_county_value_rather_than_going_blank():
    """Tightening the comp band must not simply delete land leads: the county's
    own 100%-basis appraisal is a better answer than no answer. This fallback is
    why the fix ADDS 2,358 ARVs while removing the phantoms."""
    li = _li(property_kind=PropertyKind.LAND, acreage=5.02, market_value=123814.0,
             raw={"comps": [{"sold_price": 100000, "lot_sqft": 6000, "kind": "land"},
                            {"sold_price": 90000, "lot_sqft": 8211, "kind": "land"}]})
    c = vcalc.compute(li)
    # This is board index 10962, 290 CEDAR SPRINGS RD: it published $770,400 off
    # three town-lot comps (0.14-0.73 ac) applied to 5.02 acres. Those are now
    # rejected, and the county's own $123,814 carries the lead instead.
    assert c.arv_expected == pytest.approx(123800, abs=200)
    assert c.arv_confidence == "LOW"


def test_bid_derived_arv_gets_no_deal_verdict_and_no_letter():
    """bid / (bid x 2.4) is a constant, so 316 of 405 bid-proxy leads graded
    exactly C and 297 read GREAT — scoring the arithmetic, not the property."""
    li = _li(state="NC", county="Gaston", property_kind=PropertyKind.SINGLE_FAMILY,
             opening_bid=100000.0, living_sqft=1500.0)
    c = vcalc.compute(li)
    assert c.arv_expected == 240000
    assert "bid_proxy_arv" in (c.arv_flags or [])
    assert c.deal_status is None
    assert grading.grade(li, c).overall is None


# ---------------------------------------------------------------------------
# 4b. REFUSING BAD COMPS MUST NOT BECOME A LICENCE TO INVENT A BIGGER NUMBER
#
# The first pass at the acreage band above pushed 1,624 leads out of the comp
# tier and into the county-value fallback — and 144 of them came out worth MORE
# than the mismatched comps they replaced, 104 with no flag at all. That is the
# reported bug ("a trailer on a half acre will say 700k") re-created by its own
# fix, so it gets the heaviest coverage in this file.
# ---------------------------------------------------------------------------

def test_a_smaller_comp_caps_the_subjects_dollars_per_acre():
    """$/acre falls as parcels grow, so a comp NO BIGGER than the subject is an
    upper bound on the subject — evidence from the lead itself rather than a
    constant. Measured: the smaller parcel carries the higher $/acre on 89.5% of
    board comp pairs at a >=5x size gap, and a 3x tolerance absorbs the rest
    (1.54% of pairs)."""
    # 1030 US 70 TRL as it really sat: 1.21 ac, comps at 0.85 / 15 / 23 ac.
    priced = [(35_294.0, 0.85), (2_609.0, 23.0), (3_666.0, 15.0)]
    ok, why = vcalc._land_anchor_supported(1.209, 648_710, priced)
    assert ok is False and "35,294" in why
    # The same lead with a county value that IS a land value passes untouched.
    assert vcalc._land_anchor_supported(1.209, 40_000, priced)[0] is True


def test_market_ceiling_applies_when_no_comp_is_small_enough_to_bound_anything():
    """When every comp is bigger than the subject there is no comp-derived upper
    bound, so the fallback is p99 of the $/acre of every REAL land sale on the
    board in that size band. Deliberately not p99 of county anchors — those are
    contaminated by improved parcels mis-typed as land ($1.7M/acre median under
    0.25 ac, against $234k for actual sales)."""
    ceilings = [vcalc._land_sale_ppa_ceiling(a) for a in (0.05, 0.3, 0.8, 1.5, 3, 7, 40)]
    assert ceilings == sorted(ceilings, reverse=True), "$/acre must fall with size"
    assert all(c > 0 for c in ceilings)
    # 917 DUNROY DR: 0.06 ac carrying a $664,000 tax value = $11M/acre.
    ok, why = vcalc._land_anchor_supported(0.06, 664_000, [(225_806.0, 0.31)])
    assert ok is False and "11,066,667" in why


def test_the_burke_county_trail_lot_no_longer_becomes_a_deal():
    """Board index 29189, 1030 US 70 TRL, Connelly Springs NC: 1.21 acres listed
    at $29,900, carrying a $648,710 tax record — $536,567 an acre.

    Before: land comps refused for size, ARV taken from that tax record at
    $713,600, NEGOTIATE -> GREAT, ROI -86% -> +766%, max bid $535,200, no flags.
    After: the county number cannot be read as a value for 1.21 acres of dirt
    (a 0.85-acre comp sold at $35,294/acre), so it is refused and the lead falls
    to the labelled bid proxy — which carries no verdict."""
    li = _li(state="NC", county="Burke", property_kind=PropertyKind.LAND, acreage=1.209,
             tax_value=648_710.0, opening_bid=29_900.0,
             raw={"comps": [{"sold_price": 30000, "lot_sqft": 0.85 * 43560, "kind": "land"},
                            {"sold_price": 60000, "lot_sqft": 23.0 * 43560, "kind": "land"},
                            {"sold_price": 55000, "lot_sqft": 15.0 * 43560, "kind": "land"}]})
    c = vcalc.compute(li)
    assert c.arv_expected is not None and c.arv_expected < 100_000, (
        f"the $648,710 tax record must not become the ARV (got {c.arv_expected})"
    )
    assert "land_ppa_ceiling" in (c.arv_flags or [])
    assert c.deal_status is None, "a bid-proxy ARV gets no buy/pass verdict"
    assert any("not usable as a land value" in n for n in c.notes)


def test_a_lead_with_no_bid_and_a_refused_anchor_publishes_nothing():
    """Board index 22, 917 DUNROY DR: 0.06 ac with a $664,000 tax value and no
    opening bid. It published $1,019,000 — $17M an acre — with a $764,200 max
    bid and not one flag. There is no honest number here, so there is no
    number: withholding the ARV withholds everything derived from it."""
    li = _li(state="NC", county="Henderson", property_kind=PropertyKind.LAND, acreage=0.06,
             tax_value=664_000.0,
             raw={"comps": [{"sold_price": 70000, "lot_sqft": 0.31 * 43560, "kind": "land"},
                            {"sold_price": 68000, "lot_sqft": 0.37 * 43560, "kind": "land"},
                            {"sold_price": 1600000, "lot_sqft": 8.80 * 43560, "kind": "land"}]})
    c = vcalc.compute(li)
    assert c.arv_expected is None
    assert {"land_comps_rejected", "land_ppa_ceiling"} <= set(c.arv_flags or [])
    assert c.max_bid_70 is None and c.roi_pct is None and c.deal_status is None
    assert grading.grade(li, c).overall is None


def test_a_rejected_comps_lead_never_publishes_above_its_anchor_unflagged():
    """THE REGRESSION GUARD FOR THIS WHOLE CLASS.

    An ARV that goes UP because its comps were rejected is almost always wrong,
    so the one thing that must never happen again is a rejected-comps lead
    quietly publishing more than the county says the parcel is worth. Measured
    on the live board after this fix: of the 1,624 leads whose land comps are
    refused for size, ZERO publish an ARV above their own anchor without a flag
    (it was 269), and the 135 whose ARV rose against the previously-published
    board are flagged to the last one (it was 104 unflagged)."""
    shapes = [
        # (state, county, acres, county value, comps as (price, acres))
        ("NC", "Gaston", 5.0, 100_000, [(40_000, 0.5), (50_000, 0.6)]),
        ("NC", "Burke", 1.209, 648_710, [(30_000, 0.85), (60_000, 23.0), (55_000, 15.0)]),
        ("NC", "Gaston", 10.46, 1_173_520, [(5_500, 0.21), (165_000, 4.9)]),
        ("NC", "Henderson", 0.06, 664_000, [(70_000, 0.31), (68_000, 0.37)]),
        ("SC", "Anderson", 86.7, 300_000, [(21_000, 0.63), (70_000, 2.5)]),
        ("NC", "Gaston", 2.0, 55_000, [(60_000, 0.05), (66_000, 0.07)]),
    ]
    for state, county, acres, cty_val, comps in shapes:
        li = _li(state=state, county=county, property_kind=PropertyKind.LAND, acreage=acres,
                 tax_value=float(cty_val),
                 raw={"comps": [{"sold_price": p, "lot_sqft": a * 43560, "kind": "land"}
                                for p, a in comps]})
        c = vcalc.compute(li)
        assert any(vcalc.LAND_COMPS_REJECTED_MARKER in n for n in c.notes), (
            f"{county} {acres}ac: expected the size band to refuse these comps"
        )
        if c.arv_expected is not None and c.arv_expected > cty_val:
            assert c.arv_flags, (
                f"{county} {acres}ac published {c.arv_expected:,.0f} against a "
                f"{cty_val:,.0f} county value with NO flag"
            )


def test_the_anchor_fallback_still_carries_land_leads_it_can_justify():
    """The gate must not simply delete the fallback: a county value that IS a
    plausible land value still carries the lead, at LOW confidence and clearly
    labelled as the county's own unverified number."""
    li = _li(state="NC", county="Gaston", property_kind=PropertyKind.LAND, acreage=5.0,
             tax_value=100_000.0,
             raw={"comps": [{"sold_price": 40000, "lot_sqft": 0.5 * 43560, "kind": "land"},
                            {"sold_price": 50000, "lot_sqft": 0.6 * 43560, "kind": "land"}]})
    c = vcalc.compute(li)
    assert c.arv_expected == 110_000
    assert c.arv_confidence == "LOW"
    assert {"land_comps_rejected", "anchor_not_independent"} <= set(c.arv_flags or [])


# ---------------------------------------------------------------------------
# 4c. THE SALE DATE HAS TO BE PARSED, NOT PATTERN-MATCHED
# ---------------------------------------------------------------------------

def test_sale_dates_are_parsed_in_every_shape_the_board_carries():
    """`re.search(r"(1[89]\\d{2}|20\\d{2})")` over the raw string answered with
    whatever four adjacent digits happened to look like a year: the epoch-ms
    stamp "20995200000" (1970) read as 2099, "-441849600000" (1956) read as
    1849. 827 board rows carry a bare epoch date and 474 of them decode to 2016
    or later — every one refused as a stale floor on a fabricated year.

    Shapes counted on the board's 19,828 sale records: 15,222 ISO, 824 bare
    epoch (13-, 12-, 11-digit and negative), 392 bare `YYYY`, 40 `DD-MON-YY`."""
    cases = {
        "2020-04-29": 2020,        # ISO — 15,222 rows
        "2026-01-02": 2026,
        "1025481600000": 2002,     # epoch ms, 13 digits — 662 rows
        "586396800000": 1988,      # epoch ms, 12 digits — 121 rows
        "20995200000": 1970,       # epoch ms, 11 digits — the old code read 2099
        "-441849600000": 1956,     # negative epoch ms — the old code read 1849
        "1704430800000": 2024,     # a RECENT sale the old code could not see
        "1999": 1999,              # bare year — 392 rows
        "02-JUL-09": 2009,         # Oracle DD-MON-YY — 40 rows
        "06-NOV-25": 2025,         # two-digit year pivots on today
        "07-AUG-75": 1975,
        "19931014": 1993,          # YYYYMMDD (assessor CAMA style)
        "03/15/2024": 2024,
        "": None,                  # no date is not a date
        "garbage": None,
    }
    for raw, want in cases.items():
        assert vcalc._sale_year({"date": raw}) == want, f"{raw!r} -> {want}"
    assert vcalc._sale_year(None) is None
    assert vcalc._sale_year({}) is None


def test_a_recent_epoch_dated_sale_still_floors_the_arv():
    """The point of parsing properly: a real 2024 sale above the comp ARV is
    exactly what the floor is for, and it was being thrown away."""
    comps = _comps(100.0)
    li = _li(state="NC", county="Gaston", property_kind=PropertyKind.SINGLE_FAMILY,
             living_sqft=1500.0, year_built=2005,
             raw={"comp_median_ppsf": 100.0, "comps": comps,
                  "gis": {"last_sale": {"amount": 180000, "date": "1704430800000"}}})
    c = vcalc.compute(li)
    assert c.arv_expected == 180_000, "a 2024 sale must floor a $150,000 comp ARV"
    assert "stale_sale_floor" not in (c.arv_flags or [])


def test_refusing_a_floor_can_never_make_a_lead_more_confident_than_taking_it():
    """Accepting a floor caps confidence at MEDIUM — the comps and the county
    disagreed, so it is not a clean comp read. Refusing one used to cap nothing,
    so the disagreement vanished and the lead came out HIGH: 297 leads ended
    MORE confident than before the guards existed, 83 of them MEDIUM -> HIGH and
    49 purely because a floor source had been refused. The disagreement is the
    same fact whichever way it is resolved."""
    common = dict(state="NC", county="Gaston", property_kind=PropertyKind.SINGLE_FAMILY,
                  living_sqft=1500.0, year_built=2005)
    comps = _comps(100.0)                       # -> a $150,000 HIGH-confidence ARV
    accepted = vcalc.compute(_li(market_value=200_000.0,
                                 raw={"comp_median_ppsf": 100.0, "comps": comps}, **common))
    refused_commercial = vcalc.compute(_li(
        market_value=200_000.0,
        raw={"comp_median_ppsf": 100.0, "comps": comps,
             "cama": {"building_type": "GEN WHSE 50"}}, **common))
    refused_stale = vcalc.compute(_li(
        raw={"comp_median_ppsf": 100.0, "comps": comps,
             "gis": {"last_sale": {"amount": 500000, "date": "1992-06-01"}}}, **common))

    assert accepted.arv_expected == 200_000 and accepted.arv_confidence == "MEDIUM"
    rank = {"LOW": 0, "MEDIUM": 1, "HIGH": 2}
    for c in (refused_commercial, refused_stale):
        assert c.arv_expected == 150_000, "the comp number survives the refusal"
        assert rank[c.arv_confidence] <= rank[accepted.arv_confidence], (
            f"refusing the floor left the lead MORE confident ({c.arv_confidence}) "
            f"than accepting it ({accepted.arv_confidence})"
        )


# ---------------------------------------------------------------------------
# 4d. A CROSS-CHECK THAT CANNOT FAIL IS NOT A CROSS-CHECK
# ---------------------------------------------------------------------------

def test_an_arv_derived_from_the_county_value_is_not_validated_against_it():
    """7,000 board ARVs are the county's own number times a constant — `anchor ×
    1.10`, `tax × 1.25`, market_value wearing the Zestimate's label, or the
    floor set to market_value. Dividing one by the other returns the multiplier
    every time, so the check passed 27.8% of the board by construction. It is
    now skipped and the lead is MARKED instead; the ratio still publishes for
    transparency, but nothing claims it was verified."""
    li = _li(state="NC", county="Gaston", property_kind=PropertyKind.SINGLE_FAMILY,
             living_sqft=1500.0, tax_value=100_000.0, raw={})
    c = vcalc.compute(li)
    assert c.arv_expected == 125_000
    assert c.arv_vs_assessed == 1.25            # published, as before
    assert "anchor_not_independent" in (c.arv_flags or [])
    assert any("No independent cross-check" in n for n in c.notes)

    # ...and the floor too: flooring TO the county value makes the ARV that value.
    floored = vcalc.compute(_li(
        state="NC", county="Gaston", property_kind=PropertyKind.SINGLE_FAMILY,
        living_sqft=1500.0, market_value=300_000.0, year_built=2005,
        raw={"comp_median_ppsf": 100.0, "comps": _comps(100.0)}))
    assert floored.arv_expected == 300_000
    assert "anchor_not_independent" in (floored.arv_flags or [])

    # A genuinely independent comp ARV is still checked, and still passes clean.
    independent = vcalc.compute(_li(
        state="NC", county="Gaston", property_kind=PropertyKind.SINGLE_FAMILY,
        living_sqft=1850.0, acreage=0.34, market_value=300_000.0, year_built=2003,
        raw={"comp_median_ppsf": 175.0, "comps": _comps(175.0)}))
    assert "anchor_not_independent" not in (independent.arv_flags or [])


def test_a_mis_joined_commercial_assessor_row_does_not_delete_the_guardrail():
    """calc refuses a commercial assessor row as an ARV floor — correctly. But
    refusing it as the ANCHOR too removed the only cross-check these leads had:
    all 176 that keep an ARV carried arv_vs_assessed == None, and five published
    more than 10x the county figure nobody was allowed to look at. 616 N CHURCH
    ST ran $643,200 against $13,435 — 47.9x — at MEDIUM confidence with a max
    bid beside it. Whichever record is wrong, that disagreement is a fact about
    the lead."""
    li = _li(state="NC", county="Gaston", property_kind=PropertyKind.SINGLE_FAMILY,
             living_sqft=1500.0, opening_bid=20_000.0,
             raw={"comp_median_ppsf": 430.0, "comps": _comps(430.0),
                  "cama": {"building_type": "RETAIL STORE", "appraised_value": 13_435.0}})
    c = vcalc.compute(li)
    assert c.arv_expected is None, "48x the only county figure on the row must not publish"
    assert c.arv_withheld == 645_000
    assert {"cama_class_mismatch", "arv_above_anchor_extreme"} <= set(c.arv_flags or [])
    assert c.max_bid_70 is None and c.roi_pct is None and c.deal_status is None
    assert grading.grade(li, c).overall is None


def test_the_mis_join_flag_does_not_depend_on_which_field_held_the_number():
    """The flag used to be raised only when `market_value` existed AND cleared
    $10,000, but the anchor was suppressed whichever field carried the figure —
    so 7 leads silently lost their cross-check with nothing to say so."""
    li = _li(state="NC", county="Gaston", property_kind=PropertyKind.SINGLE_FAMILY,
             living_sqft=1500.0, market_value=9_000.0,        # below the old gate
             raw={"comp_median_ppsf": 20.0, "comps": _comps(20.0),
                  "cama": {"building_type": "GEN WHSE 50"}})
    c = vcalc.compute(li)
    assert "cama_class_mismatch" in (c.arv_flags or [])
    assert c.arv_vs_assessed == 3.33, "the cross-check ratio must exist, not be None"


# ---------------------------------------------------------------------------
# 5. THE REGRESSION GUARD — the normal case must be untouched
# ---------------------------------------------------------------------------

def test_ordinary_suburban_house_is_completely_unaffected():
    """The whole board's usefulness rests on the ~87% of leads that are fine.

    A 1,850 sqft 2003 house in Gaston County, comps at $175/sqft (the county's
    measured median), county appraisal $300,000, opening bid $210,000. Nothing
    here is anomalous and NOTHING may fire: full ARV, full band, full max bid,
    full ROI, a real letter grade, and not one sanity flag.
    """
    li = _li(state="NC", county="Gaston", property_kind=PropertyKind.SINGLE_FAMILY,
             street_address="14 Maple Dr", living_sqft=1850.0, acreage=0.34,
             bedrooms=3.0, bathrooms=2.0, year_built=2003,
             market_value=300000.0, tax_value=300000.0, opening_bid=210000.0,
             raw={"comp_median_ppsf": 175.0, "comps": _comps(175.0)})
    c = vcalc.compute(li)
    g = grading.grade(li, c)

    assert c.arv_flags is None, f"a normal house raised flags: {c.arv_flags}"
    assert c.arv_withheld is None
    assert c.arv_expected == pytest.approx(323750, abs=1000)
    assert c.arv_low and c.arv_high
    assert c.arv_low <= c.arv_expected <= c.arv_high, "headline must sit in its band"
    assert c.arv_confidence in ("HIGH", "MEDIUM")
    assert c.max_bid_70 and c.max_bid_70 > 0
    assert c.roi_pct is not None
    assert c.deal_status in ("GREAT", "OK", "NEGOTIATE", "PASS")
    assert c.rehab_expected and c.rehab_tier not in (None, "unknown")
    assert g.overall in ("A", "B", "C", "D", "F"), "a normal house must get a letter"


def test_a_modest_floor_still_works():
    """The floor's legitimate job — thin comps sitting just under the county's
    as-is value — is untouched. 78.6% of floors raise by <=2.5x and corroborating
    defects are FLAT with magnitude, so magnitude alone is not a rejection."""
    li = _li(state="NC", county="Gaston", property_kind=PropertyKind.SINGLE_FAMILY,
             living_sqft=1500.0, market_value=200000.0, year_built=2005,
             raw={"comp_median_ppsf": 100.0, "comps": _comps(100.0)})
    c = vcalc.compute(li)
    assert c.arv_expected == 200000, "a 1.33x floor must still apply"
    assert "floor_raise_large" not in (c.arv_flags or [])
    assert c.arv_low <= c.arv_expected <= c.arv_high


def test_normal_land_lead_keeps_its_value():
    """A 2-acre lot comped against 1.5-3 acre lots is exactly what the land path
    is for and must survive every new guard."""
    li = _li(state="NC", county="Gaston", property_kind=PropertyKind.LAND,
             acreage=2.0, market_value=55000.0, opening_bid=30000.0,
             raw={"comps": [{"sold_price": 60000, "lot_sqft": 1.8 * 43560, "kind": "land"},
                            {"sold_price": 66000, "lot_sqft": 2.2 * 43560, "kind": "land"},
                            {"sold_price": 63000, "lot_sqft": 2.0 * 43560, "kind": "land"}]})
    c = vcalc.compute(li)
    assert c.arv_flags is None, f"a normal land lead raised flags: {c.arv_flags}"
    assert c.arv_expected and 50_000 < c.arv_expected < 90_000
    assert c.max_bid_70 is not None


# ---------------------------------------------------------------------------
# 9. THE LAND COMPS MUST AGREE BEFORE THEY MAY BE AVERAGED  (calc.py)
#
# The reported bug, re-created in the land path and found by replaying the
# shipping code: [29184] 215 N Fork River Road, McDowell NC, 1.09 acres. Two
# in-band land comps at $23,962/ac and $984,835/ac — a 41x disagreement, the
# second an improved sale carrying kind:land. The pair was AVERAGED to
# $504,398/ac, published as a $549,800 ARV with a $412,400 max bid and a GREAT
# verdict, and `arv_flags` was EMPTY. The pair set confidence to LOW and stopped
# there; a confidence label nothing downstream reads is not a guard.
# ---------------------------------------------------------------------------

def _land_comp(ppa: float, acres: float) -> dict:
    return {"sold_price": ppa * acres, "lot_sqft": acres * 43560, "kind": "land"}


def test_two_land_comps_41x_apart_are_not_averaged():
    """The reported case. Nothing in the pool supports their mean, so the mean
    is not a land value and must not be published as one."""
    li = _li(state="NC", county="McDowell", property_kind=PropertyKind.LAND,
             acreage=1.09,
             raw={"comps": [_land_comp(23_962, 1.0), _land_comp(984_835, 1.2)]})
    c = vcalc.compute(li)
    assert "land_comps_disagree" in (c.arv_flags or []), (
        "a 41x pool must raise a flag the rest of the system can see, not just "
        f"a LOW confidence label. flags={c.arv_flags}")
    assert not any("land comps ×" in n for n in c.notes), (
        "the refused pair must not go on to price the parcel")
    # No county value and no opening bid here, so every later tier declines too:
    # the honest answer is no ARV rather than an averaged one.
    assert c.arv_expected is None
    assert c.max_bid_70 is None and c.deal_status is None


def test_the_refusal_states_both_comps_so_the_reader_can_judge():
    """A silent refusal is the same failure one level up. The note has to name
    the two $/acre figures and say which way the mean leans."""
    li = _li(state="NC", county="McDowell", property_kind=PropertyKind.LAND,
             acreage=1.09,
             raw={"comps": [_land_comp(23_962, 1.0), _land_comp(984_835, 1.2)]})
    c = vcalc.compute(li)
    note = next(n for n in c.notes if vcalc.LAND_COMPS_DISAGREE_MARKER in n)
    assert "23,962" in note and "984,835" in note
    assert "41x" in note


def test_a_three_comp_land_pool_that_spans_keeps_its_median_and_flags_it():
    """A median of 3+ is an actual comp and is robust to one mis-typed sale, so
    refusing it would delete a defensible answer. It is published, forced to LOW,
    and flagged so the verdict can be withheld off it."""
    li = _li(state="NC", county="Gaston", property_kind=PropertyKind.LAND,
             acreage=2.0,
             raw={"comps": [_land_comp(20_000, 2.0), _land_comp(60_000, 2.0),
                            _land_comp(200_000, 2.0)]})
    c = vcalc.compute(li)
    assert "land_comp_spread" in (c.arv_flags or [])
    assert "land_comps_disagree" not in (c.arv_flags or []), (
        "3+ comps keep their median — only a PAIR is refused")
    assert c.arv_expected == pytest.approx(120_000, abs=100), "the median, ×2 acres"
    assert c.arv_confidence == "LOW"
    assert c.arv_low < c.arv_expected < c.arv_high, "publish the band, not the point"


def test_a_land_pair_just_under_the_threshold_is_still_averaged():
    """DO NOT GUT THE NORMAL CASE. ~8-11x IS ordinary $/acre variation in these
    counties (p90/p10 within a size band on this board), so the threshold is set
    at the low end of it and everything below must come through untouched."""
    li = _li(state="NC", county="Gaston", property_kind=PropertyKind.LAND,
             acreage=2.0,
             raw={"comps": [_land_comp(20_000, 2.0), _land_comp(100_000, 2.0)]})
    c = vcalc.compute(li)
    assert 5.0 == pytest.approx(100_000 / 20_000), "this pool spans 5x, under the 8x bar"
    assert "land_comps_disagree" not in (c.arv_flags or [])
    assert "land_comp_spread" not in (c.arv_flags or [])
    assert c.arv_expected == pytest.approx(120_000, abs=100), "the mean, ×2 acres"


def test_the_spread_threshold_is_the_documented_constant():
    """The threshold is derived from the board's own distinct-pool comp-spread
    distribution (p85 = 8.14x) and from what real $/acre variation looks like
    there (p90/p10 = 8.0-11.0x within a size band). Locked so a future tune is a
    deliberate act with a re-measurement behind it."""
    assert vcalc.LAND_COMP_SPREAD_MAX == 8.0


@pytest.mark.parametrize("flag", ["land_comps_disagree", "land_comp_spread"])
def test_the_land_agreement_flags_are_weak_not_contradicted(flag):
    """Both say "the comps on this card did not produce this number" — a
    disclosure about the evidence, not a contradiction of the figure that
    shipped, which came from a later tier and is judged on ITS flags. So the
    verdict goes and the money stays."""
    assert flag in grading.ARV_FLAGS_WEAK_EVIDENCE
    assert flag not in grading.ARV_FLAGS_CONTRADICTED
    c = vcalc.Calc(arv_expected=300000.0, arv_flags=[flag], max_bid_70=180000.0,
                   roi_pct=42.0, deal_status="GREAT", notes=[])
    level = grading.apply_arv_trust_gate(c)
    assert level == "weak"
    assert c.deal_status is None, "a knife-edge verdict cannot rest on this pool"
    assert c.max_bid_70 == 180000.0, "but the magnitude is not disputed"


# ---------------------------------------------------------------------------
# 10. THE ANOMALY BRANCH IS THE SAME DECISION AS THE TRUST GATE  (grading.py)
#
# `grade()` has refused to LETTER-grade an ROI over 400%, an ARV over $2M in
# these counties, or an opening bid under 5% of the ARV since 2026-06-19. It
# withheld nothing else, and the trust gate keyed on `arv_flags`, which calc
# never set for any of the three — so the verdict, the max bid and the ROI
# walked straight past it. Measured on the live board: 50 leads published a deal
# verdict with the letter withheld.
#
#   Lot 11 Silver Maple Trail, Brevard NC rendered, in badge order: a green
#   "GREAT deal", then "ARV flagged — do not bid off it", then "Max bid (70%)
#   $1,491,800", then "ROI 829%". Replayed after this change it publishes no
#   verdict, no max bid, no ROI and no equity, and carries
#   `arv_implies_implausible_roi` + `placeholder_opening_bid`.
# ---------------------------------------------------------------------------

def test_an_implausible_roi_withholds_the_verdict_and_the_money():
    """Lot 11 Silver Maple Trail. ROI is (ARV − bid − rehab − fees) / cash in, so
    829% means the ARV and the bid are describing different properties — the
    arithmetic disputing itself, which is what CONTRADICTED means."""
    li = _li(state="NC", county="Transylvania", opening_bid=1000.0)
    c = vcalc.Calc(arv_expected=1_989_000.0, arv_flags=None, max_bid_70=1_491_800.0,
                   roi_pct=829.0, estimated_profit=1_400_000.0,
                   deal_status="GREAT", deal_message="below max viable bid", notes=[])
    level = grading.apply_arv_trust_gate(c, opening_bid=li.opening_bid)
    assert "arv_implies_implausible_roi" in c.arv_flags
    assert level == "contradicted"
    assert c.deal_status is None and c.max_bid_70 is None
    assert c.roi_pct is None and c.estimated_profit is None
    assert c.arv_expected == 1_989_000.0, "the ARV itself is still shown"


def test_an_arv_over_two_million_withholds_the_verdict_and_the_money():
    c = vcalc.Calc(arv_expected=2_400_000.0, max_bid_70=1_680_000.0, roi_pct=120.0,
                   deal_status="GREAT", notes=[])
    assert grading.apply_arv_trust_gate(c) == "contradicted"
    assert "arv_above_plausible_max" in c.arv_flags
    assert c.deal_status is None and c.max_bid_70 is None


def test_a_placeholder_opening_bid_takes_the_verdict_but_not_the_bid():
    """`deal_status` is literally `bid <= max_bid * 0.95`, so a $1,000 upset
    figure makes GREAT unconditional. But `max_bid_70` is 0.70 × ARV − rehab and
    never touches the bid, so blanking it would punish a good number for a bad
    neighbour."""
    c = vcalc.Calc(arv_expected=300_000.0, max_bid_70=180_000.0, roi_pct=90.0,
                   deal_status="GREAT", notes=[])
    assert grading.apply_arv_trust_gate(c, opening_bid=1_000.0) == "weak"
    assert "placeholder_opening_bid" in c.arv_flags
    assert c.deal_status is None
    assert c.max_bid_70 == 180_000.0 and c.roi_pct == 90.0


@pytest.mark.parametrize("arv,roi,bid", [
    (1_989_000.0, 829.0, 1000.0),      # implausible ROI + placeholder bid
    (2_400_000.0, 120.0, 900_000.0),   # implausible ARV
    (300_000.0, 90.0, 1_000.0),        # placeholder bid alone
])
def test_the_letter_and_the_verdict_can_never_disagree_again(arv, roi, bid):
    """The letter and the verdict are the same claim at two resolutions. When
    they were defined separately the board withheld the letter and printed
    "GREAT · max bid $1,271,200" on the identical row."""
    li = _li(state="NC", county="Transylvania", opening_bid=bid, living_sqft=1500.0)
    c = vcalc.Calc(arv_expected=arv, arv_confidence="HIGH", max_bid_70=arv * 0.7,
                   roi_pct=roi, deal_status="GREAT", notes=[])
    g = grading.grade(li, c)
    assert g.overall is None, "these are the grader's own garbage-in tests"
    assert c.deal_status is None, (
        "a verdict may not outlive the letter that rates the same lead")


def test_a_clean_lead_still_gets_both_a_letter_and_a_verdict():
    """DO NOT GUT THE NORMAL CASE — the anomaly tests must not fire on an
    ordinary deal."""
    li = _li(state="NC", county="Gaston", opening_bid=90_000.0, living_sqft=1500.0,
             year_built=1995)
    c = vcalc.Calc(arv_expected=300_000.0, arv_confidence="HIGH",
                   max_bid_70=180_000.0, roi_pct=42.0, deal_status="GREAT",
                   deal_message="below max viable bid", notes=[])
    g = grading.grade(li, c)
    assert g.overall in ("A", "B", "C", "D", "F")
    assert c.deal_status == "GREAT" and c.max_bid_70 == 180_000.0
    assert not c.arv_flags


# ---------------------------------------------------------------------------
# 11. EQUITY IS ARV-DERIVED MONEY AND IS GATED LIKE IT
#     (enrichment_equity.py + distress_score.py)
#
# equity = ARV − payoff − senior liens, so on a contradicted ARV it is as
# unsupported as max_bid was — and it is the largest number on the card.
# Measured on the live board before this change: 1,252 leads published an equity
# figure on a contradicted ARV and 113 more on a WITHHELD one, i.e. leads whose
# max bid, ROI, profit, verdict AND letter were all withheld, still showing
# "Equity $1,920,000 (97%)" in green. Lot 11 Silver Maple Trail was one of them.
# ---------------------------------------------------------------------------

def _eq_li(calc_block, **kw) -> Listing:
    raw = {"calc": calc_block,
           "amount_owed": {"value": 120_000, "source": "judgment",
                           "is_actual_debt": True, "confidence": "high"}}
    raw.update(kw.pop("raw", {}))
    return _li(state="NC", county="Gaston", raw=raw, **kw)


def test_equity_is_withheld_on_a_contradicted_arv():
    from foreclosure_scraper.enrichment_equity import enrich_equity
    li = _eq_li({"arv_expected": 300_000, "arv_flags": ["bid_proxy_arv"]})
    enrich_equity([li])
    eq = li.raw["equity"]
    assert eq.get("value") is None and eq.get("pct") is None, (
        "every reader branches on value/pct — neither may survive")
    assert eq["withheld"] is True and eq["arv_trust"] == "contradicted"
    assert eq["arv_flags"] == ["bid_proxy_arv"]
    assert "bid_proxy_arv" in eq["withheld_reason"], "say which flag did it"


def test_equity_is_withheld_when_calc_refused_to_publish_an_arv():
    """`_arv` falls back to market_value, then tax_value × 1.25, so a withheld
    valuation still produced an equity figure — off a denominator that appears
    NOWHERE on the card, because calc refused to print an ARV."""
    from foreclosure_scraper.enrichment_equity import enrich_equity
    li = _eq_li({"arv_expected": None, "arv_withheld": 900_000,
                 "arv_flags": ["arv_above_anchor_extreme"]},
                market_value=400_000.0)
    enrich_equity([li])
    eq = li.raw["equity"]
    assert eq.get("value") is None
    assert eq["withheld"] is True and eq["arv_trust"] == "withheld"


def test_equity_survives_on_a_weak_arv():
    """DO NOT GUT THE NORMAL CASE. The weak tier is ~16,300 leads, most of them
    ARVs that ARE the county's own appraisal times a constant. max_bid and ROI
    publish there and equity is not an exception."""
    from foreclosure_scraper.enrichment_equity import enrich_equity
    li = _eq_li({"arv_expected": 300_000, "arv_flags": ["anchor_not_independent"]})
    enrich_equity([li])
    assert li.raw["equity"]["value"] == 180_000
    assert li.raw["equity"].get("withheld") is None


def test_a_lead_that_never_reached_the_valuation_keeps_its_equity():
    """The gate withholds equity a BAD valuation produced; it does not require a
    valuation. A lead with no raw['calc'] at all must be untouched."""
    from foreclosure_scraper.enrichment_equity import enrich_equity
    li = _li(state="NC", county="Gaston", market_value=250_000.0,
             raw={"gis": {"last_sale": {"amount": 150_000, "date": "2015-06-01"}}})
    enrich_equity([li])
    assert li.raw["equity"]["value"] > 0


def test_the_equity_gate_and_the_money_gate_share_one_definition():
    """A reader/writer split is what let flags go unwarned for months. The two
    call sites outside grading.py import the set, they do not re-spell it."""
    from foreclosure_scraper import distress_score, enrichment_equity
    assert enrichment_equity._EQUITY_TRUST_BLOCKED is grading.ARV_TRUST_BLOCKS_DERIVED
    assert distress_score.ARV_TRUST_BLOCKS_DERIVED is grading.ARV_TRUST_BLOCKS_DERIVED
    assert grading.ARV_TRUST_BLOCKS_DERIVED == {"contradicted", "withheld"}


def test_the_distress_band_refuses_a_stale_equity_figure():
    """The band is computed over whatever raw['equity'] is on the Listing, so on
    a board carried over from a run that predates the writer-side gate the old
    figure is still sitting there. The check is repeated at the reader."""
    from foreclosure_scraper.distress_score import _equity_band
    stale = _li(state="NC", county="Gaston",
                raw={"equity": {"pct": 0.97, "value": 1_920_000},
                     "calc": {"arv_expected": 1_989_000,
                              "arv_flags": ["arv_implies_implausible_roi"]}})
    assert _equity_band(stale) is None
    ok = _li(state="NC", county="Gaston",
             raw={"equity": {"pct": 0.97, "value": 1_920_000}, "calc": {}})
    assert _equity_band(ok) == "high", "an unflagged lead still ranks"


def test_the_roi_fallback_cannot_smuggle_a_contradicted_arv_back_in():
    """`_equity_band` falls back to flip ROI when equity is missing — and ROI is
    ARV minus every cost over cash in, so it is the same disputed number."""
    from foreclosure_scraper.distress_score import _equity_band
    li = _li(state="NC", county="Gaston",
             raw={"calc": {"arv_expected": 300_000, "roi_pct": 90.0,
                           "arv_flags": ["cama_class_mismatch"]}})
    assert _equity_band(li) is None


def test_a_contradicted_lead_cannot_reach_hot_but_its_records_still_rank():
    """equity_band feeds the HOT gate, one WARM route and the ranking. Closing it
    must close HOT — an instruction to spend money contacting an owner — without
    deleting probate/tax/code-enforcement records, which are independent of the
    ARV and are not impugned by a bad comp set."""
    from pathlib import Path
    from foreclosure_scraper.distress_score import score_board

    def _stacked(flags):
        return _li(state="NC", county="Gaston", parcel_id=f"P{abs(hash(str(flags))) % 9999}",
                   raw={"calc": {"arv_expected": 500_000, "arv_flags": flags},
                        "equity": {"pct": 0.80, "value": 400_000},
                        "probate": True, "code_enforcement": True,
                        "owner_mailing": {"mailing": "1 Main St", "absentee": False}})

    clean, bad = _stacked(None), _stacked(["bid_proxy_arv"])
    score_board([clean, bad], previous_path=Path("/nonexistent/listings.json"))
    assert clean.raw["distress_stack"]["tier"] == "HOT"
    assert clean.raw["distress_stack"]["equity_band"] == "high"
    assert bad.raw["distress_stack"]["tier"] == "WARM", (
        "a contradicted valuation cannot buy HOT, but a 2-category stack is "
        "still a real lead")
    assert bad.raw["distress_stack"]["equity_band"] is None
    assert bad.raw["distress_stack"]["stack"] == clean.raw["distress_stack"]["stack"]
    assert "probate" in bad.raw["distress_stack"]["signals"], "the records survive"
    assert "code_enforcement" in bad.raw["distress_stack"]["signals"]
