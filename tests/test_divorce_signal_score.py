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


# Fixed 2026-10-02: _divorce_signal now REQUIRES party_middle_verdict() ==
# "agrees" (not merely "not a proven conflict") before scoring anything -- see
# that function's updated docstring. Every case fixture below therefore
# carries a `parties` caption that genuinely agrees with OWNER's middle
# initial, and every _divorce_signal() call below passes owner_name=OWNER,
# so the recency/role tests exercise that logic in isolation rather than
# being swallowed by the new verdict gate. The gate itself is covered by its
# own section further down.
OWNER = "BYRD SANDRA D"
AGREEING_CAPTION = "SANDRA D BYRD vs. ROBERT BYRD"


def _dv(*cases, count=None):
    return {"divorce": {"state": "SC", "county": "Spartanburg",
                        "case_count": len(cases) if count is None else count, "cases": list(cases)}}


def _case(filed, role="Defendant", parties=AGREEING_CAPTION):
    return {"case_number": "2024DR4200001", "filed_date": filed, "category": "110 - Divorce",
            "role": role, "parties": parties}


def test_recent_party_case_scores_full_weight():
    assert _divorce_signal(_dv(_case("2025-03-01")), TODAY, owner_name=OWNER) == ("divorce", "LIFE_EVENT", 12)


def test_three_to_seven_years_scores_reduced_weight():
    assert _divorce_signal(_dv(_case("2021-01-01")), TODAY, owner_name=OWNER) == ("divorce", "LIFE_EVENT", 6)


def test_decades_old_divorce_is_history_not_motivation():
    assert _divorce_signal(_dv(_case("2009-03-20")), TODAY, owner_name=OWNER) is None


def test_attorney_and_guardian_rows_are_not_the_owner():
    assert _divorce_signal(_dv(_case("2026-01-01", role="Attorney")), TODAY, owner_name=OWNER) is None
    assert _divorce_signal(_dv(_case("2026-01-01", role="Guardian Ad Litem")), TODAY, owner_name=OWNER) is None


def test_a_party_row_counts_even_when_an_attorney_row_is_present():
    d = _dv(_case("2026-01-01", role="Attorney"), _case("2025-06-01", role="Plaintiff"))
    assert _divorce_signal(d, TODAY, owner_name=OWNER) == ("divorce", "LIFE_EVENT", 12)


def test_newest_party_case_decides_the_weight():
    d = _dv(_case("2001-01-01"), _case("2024-05-05"))
    assert _divorce_signal(d, TODAY, owner_name=OWNER)[2] == 12


def test_no_hit_missing_dates_and_unknown_role_handling():
    assert _divorce_signal({}, TODAY, owner_name=OWNER) is None
    assert _divorce_signal({"divorce": {"case_count": 0, "cases": []}}, TODAY, owner_name=OWNER) is None
    assert _divorce_signal(_dv({"role": "Plaintiff", "parties": AGREEING_CAPTION}), TODAY,
                           owner_name=OWNER) is None          # no filed_date
    no_role = {"case_number": "x", "filed_date": "2025-01-01", "parties": AGREEING_CAPTION}  # role unknown: kept
    assert _divorce_signal(_dv(no_role), TODAY, owner_name=OWNER) == ("divorce", "LIFE_EVENT", 12)


def test_signal_reaches_signals_for_and_adds_a_life_event_category():
    li = Listing(source="counties_sc.qpaybill_delinquent_roll", source_url="u",
                 listing_type=ListingType.TAX_LIEN, state="SC", county="Spartanburg",
                 owner_name=OWNER,
                 raw=_dv(_case(date.today().replace(year=date.today().year - 1).isoformat())))
    sigs = _signals_for(li)
    assert ("divorce", "LIFE_EVENT", 12) in sigs
    assert {c for _, c, _ in sigs} >= {"FINANCIAL", "LIFE_EVENT"}   # stacks with the tax lien


# ---- same first+last name, different middle initial = a different person ----------------
from foreclosure_scraper.name_normalize import owner_last_first_middle, party_middle_conflict


def test_owner_parts_for_both_board_conventions_and_joint_owners():
    assert owner_last_first_middle("BYRD SANDRA D") == ("BYRD", "SANDRA", "D")
    assert owner_last_first_middle("Joshua D Smith") == ("SMITH", "JOSHUA", "D")
    assert owner_last_first_middle("Roper, John A., Jr.") == ("ROPER", "JOHN", "A")
    assert owner_last_first_middle("SMITH JOHN & MELINDA") == ("SMITH", "JOHN", "")     # co-owner is not a middle name
    assert owner_last_first_middle("SMITH JOHN C & MELINDA P") == ("SMITH", "JOHN", "C")
    assert owner_last_first_middle("Madonna") is None


def test_a_different_middle_initial_is_a_conflict():
    parties = ["SANDRA LEE BYRD vs. ROBERT BYRD"]
    assert party_middle_conflict("BYRD SANDRA D", parties) is True        # D versus L


def test_matching_middle_initial_is_not_a_conflict():
    assert party_middle_conflict("BYRD SANDRA L", ["SANDRA LEE BYRD vs. ROBERT BYRD"]) is False


def test_no_middle_initial_on_either_side_is_never_a_conflict():
    assert party_middle_conflict("BYRD SANDRA", ["SANDRA LEE BYRD vs. ROBERT BYRD"]) is False   # owner has none
    assert party_middle_conflict("BYRD SANDRA D", ["SANDRA BYRD vs. ROBERT BYRD"]) is False     # party has none


def test_one_agreeing_party_among_several_saves_the_match():
    parties = ["SANDRA LEE BYRD vs. ROBERT BYRD", "SANDRA DAWN BYRD vs. TOM BYRD"]
    assert party_middle_conflict("BYRD SANDRA D", parties) is False


def test_a_different_first_name_is_not_this_test():
    assert party_middle_conflict("BYRD SANDRA D", ["LINDA LEE BYRD vs. ROBERT BYRD"]) is False


def test_score_skips_the_divorce_signal_on_a_middle_initial_conflict():
    d = {"divorce": {"case_count": 1, "cases": [{"filed_date": "2025-06-01", "role": "Defendant",
                                                  "parties": "SANDRA LEE BYRD vs. ROBERT BYRD"}]}}
    assert _divorce_signal(d, TODAY, owner_name="BYRD SANDRA D") is None            # conflict: D vs LEE
    assert _divorce_signal(d, TODAY, owner_name="BYRD SANDRA L") == ("divorce", "LIFE_EVENT", 12)  # agrees: L vs LEE
    # Fixed 2026-10-02: 'unverified' (no middle initial on one side, so nothing
    # corroborates the match either way) used to be scored anyway ("unknown:
    # kept"/"no owner passed: unchanged") -- a live population-scale check
    # found 0% real matches at that confidence level, so both now score
    # nothing. Only a POSITIVE middle-initial agreement scores.
    assert _divorce_signal(d, TODAY, owner_name="BYRD SANDRA") is None             # owner has no middle: unverified
    assert _divorce_signal(d, TODAY) is None                                       # no owner passed: unverified


from foreclosure_scraper.name_normalize import party_middle_verdict  # noqa: E402


def test_verdict_has_three_outcomes():
    p = ["SANDRA LEE BYRD vs. ROBERT BYRD"]
    assert party_middle_verdict("BYRD SANDRA L", p) == "agrees"
    assert party_middle_verdict("BYRD SANDRA D", p) == "conflict"
    assert party_middle_verdict("BYRD SANDRA", p) == "unverified"
    assert party_middle_verdict("BYRD SANDRA D", []) == "unverified"
    assert party_middle_verdict(None, p) == "unverified"
