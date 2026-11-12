"""Land comp size band — a widened band must still HAVE a lower bound.

The defect: enrichment_comps stage 3 widened the acreage band by calling
`_within_band(value, target, pct)` with pct=2.0 and pct=4.0. That helper's lower
bound is `target * (1 - pct)`, which past pct=1.0 is NEGATIVE — so the steps
labelled "lot~3x" and "lot~5x" had a ceiling and no floor at all. An 86.7-acre
subject therefore accepted a 0.63-acre building lot as a comparable, and $/acre
decays hard with size (board medians $153,523/ac at 0-1ac vs $22,744/ac at
20-50ac).

valuation/calc.py re-filters by acreage before computing an ARV, so the
published NUMBER was already protected. These comps are the evidence table the
operator reads next to that number, and evidence that does not match the subject
is worse than no evidence.

Measured on the live board, over the 4,932 land leads carrying both comps and a
usable lot size: 4,022 hold at least one comp outside a 3x ratio of the subject
and 3,097 outside 5x. Worst case is a 2,500-acre tract comped against a
0.34-acre lot — 7,353x.
"""
from __future__ import annotations

from datetime import datetime

from foreclosure_scraper.enrichment_comps import (
    LAND_LOT_BAND_PCT,
    LAND_LOT_WIDEN_RATIOS,
    SQFT_BAND_PCT,
    _pick_3_comps,
    _within_band,
    _within_ratio_band,
)
from foreclosure_scraper.models import Listing, ListingType, PropertyKind
from foreclosure_scraper.valuation import calc as vcalc

AC = 43560.0


def _li(**kw) -> Listing:
    base = dict(source="counties_sc.test", source_url="http://x",
                listing_type=ListingType.FORECLOSURE_SALE, state="SC",
                county="Spartanburg", city="Spartanburg", zip_code="29301",
                first_seen=datetime.utcnow(), last_seen=datetime.utcnow(), raw={})
    base.update(kw)
    return Listing(**base)


def _land_comp(acres: float, price: float = 50000.0) -> dict:
    return {"style": "land", "lot_sqft": acres * AC, "sold_price": price,
            "city": "Spartanburg", "state": "SC", "zip_code": "29301",
            "street": f"{acres} ac tract", "last_sold_date": "2026-01-01"}


# ---------------------------------------------------------------------------
# 1. THE HELPER
# ---------------------------------------------------------------------------

def test_within_band_has_no_lower_bound_at_pct_ge_1_unless_guarded():
    """The arithmetic that caused it, stated plainly: at pct=2.0 the naive lower
    bound is target * -1."""
    target = 86.7 * AC
    assert target * (1 - 2.0) < 0, "premise of the bug"
    # The guarded helper collapses to the symmetric ratio band it always meant.
    assert _within_band(0.63 * AC, target, 2.0) is False
    assert _within_band(0.63 * AC, target, 4.0) is False
    assert _within_band(40.0 * AC, target, 2.0) is True   # within 86.7/3
    assert _within_band(20.0 * AC, target, 4.0) is True   # within 86.7/5


def test_sub_one_bands_are_bit_identical():
    """The ±20% sqft bands and the ±50% lot band must not move — they are the
    normal case and their lower bound was always positive."""
    for pct in (SQFT_BAND_PCT, LAND_LOT_BAND_PCT, 0.99):
        for target in (1500.0, 2.0 * AC, 87.0):
            for value in (target * 0.4, target * 0.79, target * 0.81, target,
                          target * 1.19, target * 1.21, target * 1.49,
                          target * 1.51, target * 3.0):
                assert _within_band(value, target, pct) == (
                    target * (1 - pct) <= value <= target * (1 + pct))


def test_within_ratio_band_is_symmetric():
    t = 10.0 * AC
    assert _within_ratio_band(2.0 * AC, t, 5.0) is True     # exactly 1/5
    assert _within_ratio_band(50.0 * AC, t, 5.0) is True     # exactly 5x
    assert _within_ratio_band(1.9 * AC, t, 5.0) is False
    assert _within_ratio_band(51.0 * AC, t, 5.0) is False


# ---------------------------------------------------------------------------
# 2. THE MATCHER
# ---------------------------------------------------------------------------

def test_huge_tract_never_takes_a_building_lot_as_a_comp():
    """86.7 acres against 0.63-acre lots: the case that produced a $2,769,500
    land ARV. With no in-band comp anywhere in the pool, the honest output is
    NO comps — "not enough comps" is true; a 138x-mismatched lot is not."""
    subject = _li(property_kind=PropertyKind.LAND, acreage=86.7)
    pool = [_land_comp(0.63), _land_comp(0.51), _land_comp(0.80)]
    assert _pick_3_comps(subject, pool) == []


def test_widened_band_still_selects_a_genuinely_comparable_tract():
    """The widening exists for a reason and must keep working: nothing within
    ±50% of 86.7 ac, but a 30-acre and a 200-acre tract are the same league."""
    subject = _li(property_kind=PropertyKind.LAND, acreage=86.7)
    pool = [_land_comp(0.63), _land_comp(30.0, 600000.0), _land_comp(200.0, 3_000_000.0)]
    comps = _pick_3_comps(subject, pool)
    got = sorted(round(c["lot_sqft"] / AC, 2) for c in comps)
    assert got == [30.0, 200.0]
    assert "lot~3x" in comps[0]["match_quality"]


def test_tight_band_is_preferred_and_unchanged():
    subject = _li(property_kind=PropertyKind.LAND, acreage=10.0)
    pool = [_land_comp(9.0), _land_comp(11.0), _land_comp(40.0)]
    comps = _pick_3_comps(subject, pool)
    assert sorted(round(c["lot_sqft"] / AC, 1) for c in comps) == [9.0, 11.0]
    assert comps[0]["match_quality"].endswith("+lot")


def test_selected_comps_always_survive_the_arv_path_band():
    """The displayed evidence and the ARV inputs must be the same population.
    Before this fix the comp table showed lots that calc's LAND_COMP_BANDS then
    silently rejected, so the number and its stated evidence disagreed."""
    widest = max(ratio for _label, ratio in vcalc.LAND_COMP_BANDS)
    assert max(ratio for ratio, _label in LAND_LOT_WIDEN_RATIOS) <= widest

    subject = _li(property_kind=PropertyKind.LAND, acreage=86.7)
    pool = [_land_comp(0.63), _land_comp(30.0, 600000.0),
            _land_comp(200.0, 3_000_000.0), _land_comp(0.2)]
    subj_ac = 86.7
    for c in _pick_3_comps(subject, pool):
        comp_ac = c["lot_sqft"] / AC
        assert subj_ac / widest <= comp_ac <= subj_ac * widest
