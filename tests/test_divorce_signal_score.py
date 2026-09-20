"""raw['divorce'] (FCCMS / eCourts party-name match) must reach the score.

Until 2026-09-20 distress_score never read it, so every court-verified divorce
was collected and displayed but ranked nothing. Weights follow recency because
47% of the newest party cases on the board were more than 15 years old.
"""
from __future__ import annotations

from datetime import date

from foreclosure_scraper.distress_score import _divorce_signal, _signals_for
from foreclosure_scraper.models import Listing, ListingType

TODAY = date(2026, 9, 20)


def _dv(*cases, count=None):
    return {"divorce": {"state": "SC", "county": "Spartanburg",
                        "case_count": len(cases) if count is None else count, "cases": list(cases)}}


def _case(filed, role="Defendant"):
    return {"case_number": "2024DR4200001", "filed_date": filed, "category": "110 - Divorce", "role": role}


def test_recent_party_case_scores_full_weight():
    assert _divorce_signal(_dv(_case("2025-03-01")), TODAY) == ("divorce", "LIFE_EVENT", 12)


def test_three_to_seven_years_scores_reduced_weight():
    assert _divorce_signal(_dv(_case("2021-01-01")), TODAY) == ("divorce", "LIFE_EVENT", 6)


def test_decades_old_divorce_is_history_not_motivation():
    assert _divorce_signal(_dv(_case("2009-03-20")), TODAY) is None


def test_attorney_and_guardian_rows_are_not_the_owner():
    assert _divorce_signal(_dv(_case("2026-01-01", role="Attorney")), TODAY) is None
    assert _divorce_signal(_dv(_case("2026-01-01", role="Guardian Ad Litem")), TODAY) is None


def test_a_party_row_counts_even_when_an_attorney_row_is_present():
    d = _dv(_case("2026-01-01", role="Attorney"), _case("2025-06-01", role="Plaintiff"))
    assert _divorce_signal(d, TODAY) == ("divorce", "LIFE_EVENT", 12)


def test_newest_party_case_decides_the_weight():
    d = _dv(_case("2001-01-01"), _case("2024-05-05"))
    assert _divorce_signal(d, TODAY)[2] == 12


def test_no_hit_missing_dates_and_unknown_role_handling():
    assert _divorce_signal({}, TODAY) is None
    assert _divorce_signal({"divorce": {"case_count": 0, "cases": []}}, TODAY) is None
    assert _divorce_signal(_dv({"role": "Plaintiff"}), TODAY) is None          # no filed_date
    no_role = {"case_number": "x", "filed_date": "2025-01-01"}                 # role unknown: kept
    assert _divorce_signal(_dv(no_role), TODAY) == ("divorce", "LIFE_EVENT", 12)


def test_signal_reaches_signals_for_and_adds_a_life_event_category():
    li = Listing(source="counties_sc.qpaybill_delinquent_roll", source_url="u",
                 listing_type=ListingType.TAX_LIEN, state="SC", county="Spartanburg",
                 raw=_dv(_case(date.today().replace(year=date.today().year - 1).isoformat())))
    sigs = _signals_for(li)
    assert ("divorce", "LIFE_EVENT", 12) in sigs
    assert {c for _, c, _ in sigs} >= {"FINANCIAL", "LIFE_EVENT"}   # stacks with the tax lien
