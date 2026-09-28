"""Dirty Deeds synthesis (docs/dirty_deeds_synthesis_2026-09-10.md) numeric-rules
calibration fixes to fullmer_rank.py: arrears production-dollar threshold,
per-state delinquency-ramp override hook, value-conditional owner-count
degrade / hard-pass-with-exception tiers, and the three-tier curative-cost
estimate. See fullmer_rank.py for the full rationale on each constant.
"""
from __future__ import annotations

import pytest

from foreclosure_scraper.fullmer_rank import (
    ARREARS_PRODUCTION_FILTER,
    CURATIVE_TIER1_SIMPLE,
    CURATIVE_TIER2_CAP,
    CURATIVE_TIER2_PER_PROBATE,
    CURATIVE_TIER3_JUDICIAL,
    DELINQ_RIPE_PEAK_YEARS_BY_STATE,
    DELINQ_RIPE_YEARS_BY_STATE,
    OWNER_COUNT_DEGRADE_AT,
    OWNER_COUNT_HARD_PASS_AT,
    _curative_cost_estimate,
    delinq_ripeness_points,
    score,
)
from foreclosure_scraper.models import Listing, ListingType


def _mk(owner_name=None, market_value=None, raw=None, state="NC", county="Gaston"):
    return Listing(
        source="x", source_url="u1", listing_type=ListingType.TAX_LIEN,
        state=state, county=county, owner_name=owner_name,
        market_value=market_value, raw=raw or {},
    )


# --------------------------------------------------------------- arrears $ filter

def test_arrears_production_filter_is_10k_not_5k():
    assert ARREARS_PRODUCTION_FILTER == 10_000.0


def test_arrears_at_old_5k_threshold_now_gets_low_tier():
    li = _mk(raw={"amount_owed": {"value": 6_000, "source": "tax_owed", "is_actual_debt": True}})
    s = score(li)
    assert s["why"]["arrears_stated"] == 4, "the old $5,000 cliff must no longer award the high tier"


def test_arrears_at_10k_gets_high_tier():
    li = _mk(raw={"amount_owed": {"value": 10_000, "source": "tax_owed", "is_actual_debt": True}})
    s = score(li)
    assert s["why"]["arrears_stated"] == 8


# --------------------------------------------------------- per-state ramp override

def test_delinq_ramp_state_override_is_a_documented_noop_by_default():
    assert DELINQ_RIPE_YEARS_BY_STATE == {}
    assert DELINQ_RIPE_PEAK_YEARS_BY_STATE == {}
    # No override present -> passing a state changes nothing vs. no state.
    assert delinq_ripeness_points(5.0, "NC") == delinq_ripeness_points(5.0)
    assert delinq_ripeness_points(5.0, "SC") == delinq_ripeness_points(5.0)


def test_delinq_ramp_state_override_hook_actually_wires_through():
    # Simulate a future calibration without touching the shipped defaults.
    DELINQ_RIPE_YEARS_BY_STATE["SC"] = 1.0
    DELINQ_RIPE_PEAK_YEARS_BY_STATE["SC"] = 5.0
    try:
        # At yrs=5, SC (peak=5) should be at PEAK; NC (peak=15, unaffected) should not.
        sc_pts = delinq_ripeness_points(5.0, "SC")
        nc_pts = delinq_ripeness_points(5.0, "NC")
        assert sc_pts > nc_pts
    finally:
        DELINQ_RIPE_YEARS_BY_STATE.pop("SC", None)
        DELINQ_RIPE_PEAK_YEARS_BY_STATE.pop("SC", None)


# ---------------------------------------------------------------- owner count

def test_owner_count_buy_box_unchanged_at_four():
    li = _mk(owner_name="A & B & C & D")  # oc == 4
    s = score(li)
    assert s["why"]["many_owners"] == 14
    assert s["owner_count"] == 4


def test_owner_count_degrades_past_six_at_low_value():
    li = _mk(owner_name="A & B & C & D & E & F & G")  # oc == 7, no market_value
    s = score(li)
    assert "many_owners_degraded" in s["why"]
    assert s["why"]["many_owners_degraded"] < 14
    assert "many_owners" not in s["why"]


def test_owner_count_past_six_keeps_full_award_above_value_exception():
    li = _mk(owner_name="A & B & C & D & E & F & G", market_value=600_000)  # oc == 7
    s = score(li)
    assert s["why"]["many_owners"] == 14
    assert "many_owners_degraded" not in s["why"]


def test_owner_count_hard_pass_zone_gets_no_bonus_at_low_value():
    li = _mk(owner_name=" & ".join(f"P{i}" for i in range(OWNER_COUNT_HARD_PASS_AT + 2)))
    s = score(li)
    assert "many_owners" not in s["why"]
    assert "many_owners_degraded" not in s["why"]
    assert "many_owners_value_exception" not in s["why"]
    assert any("past_hard_pass_threshold" in f for f in s["flags"])


def test_owner_count_hard_pass_zone_exception_at_named_value_and_tax_band():
    owners = " & ".join(f"P{i}" for i in range(OWNER_COUNT_HARD_PASS_AT + 2))
    li = _mk(
        owner_name=owners,
        market_value=1_500_000,
        raw={"amount_owed": {"value": 50_000, "source": "tax_owed", "is_actual_debt": True}},
    )
    s = score(li)
    assert s["why"]["many_owners_value_exception"] == 10


def test_owner_count_hard_pass_zone_no_exception_if_taxes_too_high():
    owners = " & ".join(f"P{i}" for i in range(OWNER_COUNT_HARD_PASS_AT + 2))
    li = _mk(
        owner_name=owners,
        market_value=1_500_000,
        raw={"amount_owed": {"value": 250_000, "source": "tax_owed", "is_actual_debt": True}},
    )
    s = score(li)
    assert "many_owners_value_exception" not in s["why"]


def test_owner_count_never_drops_a_lead_score_below_zero():
    # A "hard pass" lead must still be present and scoreable, never filtered.
    owners = " & ".join(f"P{i}" for i in range(20))
    li = _mk(owner_name=owners)
    s = score(li)
    assert isinstance(s["rank"], int)
    assert s["rank"] >= 0


# --------------------------------------------------------------- curative cost

def test_curative_tier1_simple_for_clean_lead():
    assert _curative_cost_estimate(1, False, False, {}) == CURATIVE_TIER1_SIMPLE


def test_curative_tier2_scales_with_owner_count_proxy_and_caps():
    one_probate = _curative_cost_estimate(1, True, False, {})
    three_probate = _curative_cost_estimate(3, True, False, {})
    many_probate = _curative_cost_estimate(9, True, False, {})
    assert one_probate == pytest.approx(CURATIVE_TIER2_PER_PROBATE)
    assert three_probate == pytest.approx(CURATIVE_TIER2_PER_PROBATE * 3)
    assert one_probate < three_probate <= CURATIVE_TIER2_CAP
    assert many_probate == CURATIVE_TIER2_CAP, "must cap at the doc's ~$15k anchor, not grow unbounded"


def test_curative_tier3_for_judicial_signal():
    assert _curative_cost_estimate(1, False, True, {}) == CURATIVE_TIER3_JUDICIAL


def test_curative_tier3_for_chain_break_even_without_explicit_judicial_flag():
    assert _curative_cost_estimate(1, False, False, {"chain_breaks": 1}) == CURATIVE_TIER3_JUDICIAL


def test_curative_judicial_signal_overrides_probate_tier():
    # Even a heavily-probated lead should price at the judicial floor once
    # litigation is active -- Tier 3 is where "the $10-30k figure actually
    # belongs" per the synthesis.
    assert _curative_cost_estimate(5, True, True, {}) == CURATIVE_TIER3_JUDICIAL


def test_score_integration_margin_gate_uses_tiered_curative_cost():
    # A probate lead (oc=3) with a $12,000 margin: tier-2 cost = 3 * 3,250 =
    # 9,750, coverage = 12,000/9,750 ~= 1.23 -> below MARGIN_COVERAGE_MIN (2.0),
    # so it should NOT get margin_ok/margin_strong, only the thin-margin flag.
    li = _mk(
        owner_name="ESTATE OF A & B & C",
        market_value=250_000,
        raw={"calc": {"est_gross_margin": 12_000}},
    )
    s = score(li)
    assert "margin_ok" not in s["why"]
    assert "margin_strong" not in s["why"]
    assert "margin_thin_vs_curative" in s["flags"]

    # Same lead, bigger margin that clears 2x tier-2 cost (2 * 9,750 = 19,500+):
    li2 = _mk(
        owner_name="ESTATE OF A & B & C",
        market_value=250_000,
        raw={"calc": {"est_gross_margin": 20_000}},
    )
    s2 = score(li2)
    assert "margin_ok" in s2["why"] or "margin_strong" in s2["why"]
