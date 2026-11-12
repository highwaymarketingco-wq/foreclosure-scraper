"""tax_calendar: the first day a levy-year bill is late, per state and county."""
from __future__ import annotations

from datetime import date

import pytest

from foreclosure_scraper import tax_calendar as tc
from foreclosure_scraper.verification.verifiers import tax_lien_ptscloud, tax_lien_qpaybill
from foreclosure_scraper.verification.verifiers.tax_lien_buncombe import delinquent_after as buncombe_after

OCT_7 = date(2026, 10, 7)


def test_nc_default_is_january_6():
    assert tc.delinquent_after(2025, "NC") == date(2026, 1, 6)
    assert tc.delinquent_after(2026, "nc", "Wake") == date(2027, 1, 6)


def test_sc_default_is_january_16_with_weekend_roll():
    assert tc.delinquent_after(2025, "SC") == date(2026, 1, 16)
    # Jan 15 2028 is a Saturday: the deadline moves to Monday the 17th, late from the 18th
    assert tc.delinquent_after(2027, "SC") == date(2028, 1, 18)


def test_unknown_state_uses_the_latest_known_rule():
    assert tc.delinquent_after(2025, "GA") == tc.delinquent_after(2025, "SC")
    assert tc.delinquent_after(2025, None) == date(2026, 1, 16)


@pytest.mark.parametrize("year", range(2018, 2036))
def test_agrees_with_the_verifiers(year):
    assert tc.delinquent_after(year, "NC") == tax_lien_ptscloud.delinquent_from(year)
    assert tc.delinquent_after(year, "NC", "Buncombe") == buncombe_after(year)
    # the SC verifier's "late" is `today > deadline`: the day after is the day this module calls late
    d = tax_lien_qpaybill.deadline(year)
    assert tc.delinquent_after(year, "SC") == date.fromordinal(d.toordinal() + 1)


def test_county_rules_carry_evidence_and_override_lookup():
    for (state, county), rule in tc.COUNTY_RULES.items():
        assert rule.evidence.strip()
        assert tc.rule_for(state, county) is rule
        assert tc.rule_for(state, f"{county} County") is rule


def test_levy_year_is_delinquent_on_the_boundary():
    assert not tc.levy_year_is_delinquent(2025, "NC", today=date(2026, 1, 5))
    assert tc.levy_year_is_delinquent(2025, "NC", today=date(2026, 1, 6))
    assert not tc.levy_year_is_delinquent(2025, "SC", today=date(2026, 1, 15))
    assert tc.levy_year_is_delinquent(2025, "SC", today=date(2026, 1, 16))
    assert not tc.levy_year_is_delinquent(2026, "NC", today=OCT_7)


def test_completed_delinquent_years_drops_the_current_bill():
    assert tc.completed_delinquent_years([2025, 2026], "NC", "Buncombe", OCT_7) == [2025]
    assert tc.completed_delinquent_years(["2026"], "NC", today=OCT_7) == []
    assert tc.not_yet_late_years(["2024", "2025", "2026"], "SC", today=OCT_7) == [2026]
    # junk and duplicates are ignored, the answer is sorted
    assert tc.completed_delinquent_years(["2023", 2023, "n/a", None, 1850, "2021-2022"],
                                         "SC", today=OCT_7) == [2021, 2023]


def test_january_window_keeps_last_years_bill_current():
    # 2 January 2027: the 2026 bill is still not late in either state
    jan2 = date(2027, 1, 2)
    assert tc.completed_delinquent_years([2025, 2026], "NC", today=jan2) == [2025]
    assert tc.latest_delinquent_levy_year("NC", today=jan2) == 2025
    assert tc.latest_delinquent_levy_year("NC", today=date(2027, 1, 6)) == 2026


def test_years_since_levy_counts_through_the_newest_late_year():
    assert tc.years_since_levy(2025, "NC", today=OCT_7) == 1
    assert tc.years_since_levy(2020, "SC", today=OCT_7) == 6
    assert tc.years_since_levy(2026, "NC", today=OCT_7) == 0


def test_levy_year_parsing():
    assert tc.levy_year("2025") == 2025
    assert tc.levy_year(2024) == 2024
    assert tc.levy_year("2023-2025") == 2023
    assert tc.levy_year("0000653346") is None
    assert tc.levy_year(True) is None
    assert tc.levy_year("") is None
