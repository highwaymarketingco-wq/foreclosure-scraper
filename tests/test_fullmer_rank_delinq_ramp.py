"""Delinquency ripeness must ramp with years, not cliff flat at 2+.

Dirty Deeds synthesis numeric rule: "Delinquency is not a 2-3 year window.
Make it ... a monotonic ramp with no upper bound. Year 1 is worthless, 2 is
interested, 3 better, 4 plus penalties is peak." Before this fix,
fullmer_rank.score() awarded a flat 22 points to any lead >= 2 years
delinquent, scoring a 2-year and a 17-year lead identically.
"""
from __future__ import annotations

from foreclosure_scraper.fullmer_rank import (
    DELINQ_RIPE_BASE_PTS,
    DELINQ_RIPE_PEAK_PTS,
    DELINQ_RIPE_PEAK_YEARS,
    DELINQ_RIPE_YEARS,
    delinq_ripeness_points,
    score,
)
from foreclosure_scraper.models import Listing, ListingType


def _mk(years_delinquent=None, source_tag="nc_ptscloud", is_two_year_plus=None):
    raw = {}
    if years_delinquent is not None:
        raw["tax_aging_surfaced"] = {"years_delinquent": years_delinquent, "source": source_tag}
    if is_two_year_plus is not None:
        raw["two_year_delinquent"] = {"is_two_year_plus": is_two_year_plus}
    return Listing(source="x", source_url="u1", listing_type=ListingType.TAX_LIEN,
                   state="NC", county="Gaston", raw=raw)


def test_ramp_is_monotonic_not_flat():
    p2 = delinq_ripeness_points(2.0)
    p5 = delinq_ripeness_points(5.0)
    p10 = delinq_ripeness_points(10.0)
    p17 = delinq_ripeness_points(17.0)
    assert p2 == DELINQ_RIPE_BASE_PTS
    assert p2 < p5 < p10 < p17, "a 17-year lead must outscore a 5-year lead, not tie it"
    assert p17 == DELINQ_RIPE_PEAK_PTS


def test_ramp_never_exceeds_peak():
    assert delinq_ripeness_points(50.0) == DELINQ_RIPE_PEAK_PTS
    assert delinq_ripeness_points(DELINQ_RIPE_PEAK_YEARS) == DELINQ_RIPE_PEAK_PTS


def test_under_ripe_threshold_falls_back_to_base():
    assert delinq_ripeness_points(1.5) == DELINQ_RIPE_BASE_PTS


def test_none_years_falls_back_to_base_not_a_crash():
    # is_two_year_plus=True but no measured year count -- old behavior preserved.
    assert delinq_ripeness_points(None) == DELINQ_RIPE_BASE_PTS


def test_score_integration_two_year_and_seventeen_year_differ():
    two_yr = _mk(years_delinquent=DELINQ_RIPE_YEARS)
    seventeen_yr = _mk(years_delinquent=17.0)
    s2 = score(two_yr)
    s17 = score(seventeen_yr)
    assert s2["why"]["delinq_ripe"] == DELINQ_RIPE_BASE_PTS
    assert s17["why"]["delinq_ripe"] == DELINQ_RIPE_PEAK_PTS
    assert s17["rank"] > s2["rank"]


def test_score_flag_only_case_still_gets_base_points():
    li = _mk(is_two_year_plus=True)  # boolean flag only, no numeric years
    s = score(li)
    assert s["why"]["delinq_ripe"] == DELINQ_RIPE_BASE_PTS
