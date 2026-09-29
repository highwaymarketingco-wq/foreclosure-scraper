"""foreclosure_docket_history.py — the sidecar behind Dirty Deeds Tier B #37
("Foreclosure docket history per parcel, including dismissed and terminated
cases. Count how many times a lender filed and failed.").

What these pin:
  * a dismissal is recorded ONLY from a literal status-text match (Dismissed/
    Terminated/Withdrawn), never inferred from anything
  * a normal, non-failure disposition (Judgment/Settled/Satisfied) must NOT
    ever be recorded as a dismissal — Judgment means the LENDER WON
  * a single dismissed case does not trigger repeat_filing_flag (the default
    threshold is 2+ — a one-off is not "repeat")
  * two dismissed cases for the SAME owner+county DOES trigger it, and the
    payload's `basis` is explicitly "status_text" (never absence-based)
  * exclude_case_number lets a caller ask "aside from the case I'm looking at
    right now" without double-counting it
  * two different counties with the same owner name do not collide
  * case_key normalizes dashed vs undashed case-number spellings to the SAME
    row, so the same real case scraped by two different sources still merges
  * once ever_dismissed is set it never un-sets on a later re-observation
  * a missing sidecar file is created lazily, matching jail_roster_history.py
"""
from __future__ import annotations

from datetime import datetime, timezone

from foreclosure_scraper import foreclosure_docket_history as fdh


def test_a_missing_sidecar_file_is_created_lazily_not_an_error(tmp_path):
    p = tmp_path / "nested" / "new.db"
    assert not p.exists()
    con = fdh.connect(p)
    assert p.exists()
    assert con.execute("SELECT COUNT(*) FROM cases").fetchone()[0] == 0


def test_first_observation_with_no_terminal_status_is_not_dismissed(tmp_path):
    con = fdh.connect(tmp_path / "h.db")
    meta = fdh.observe_case(con, state="SC", county="Spartanburg",
                            case_number="2026-CP-42-01234", owner_name="JOHN SMITH",
                            status="Pending")
    assert meta["is_new"] is True
    assert meta["ever_dismissed"] is False
    assert meta["first_dismissed_at"] is None


def test_a_literal_dismissed_status_is_recorded_as_dismissed(tmp_path):
    con = fdh.connect(tmp_path / "h.db")
    meta = fdh.observe_case(con, state="SC", county="Spartanburg",
                            case_number="2026CP4201234", owner_name="JOHN SMITH",
                            status="Dismissed")
    assert meta["ever_dismissed"] is True
    assert meta["first_dismissed_at"] is not None


def test_judgment_settled_and_satisfied_are_never_treated_as_dismissed(tmp_path):
    """Judgment means the LENDER WON — the opposite of 'filed and failed'.
    Settled/Satisfied usually means the debt got paid. None of these are a
    failed filing and must never set ever_dismissed."""
    con = fdh.connect(tmp_path / "h.db")
    for i, status in enumerate(("Judgment", "Settled", "Satisfied", "Disposed",
                                "Transferred", "Consolidated", "Pending/ADR")):
        meta = fdh.observe_case(con, state="SC", county="Anderson",
                                case_number=f"2026-CP-04-{1000+i}",
                                owner_name="JANE DOE", status=status)
        assert meta["ever_dismissed"] is False, f"{status!r} must not count as dismissed"


def test_ever_dismissed_never_unsets_on_a_later_status_change(tmp_path):
    con = fdh.connect(tmp_path / "h.db")
    fdh.observe_case(con, state="NC", county="Buncombe", case_number="24CVD001234-320",
                     owner_name="BOB JONES", status="Dismissed")
    # A later re-observation reports a blank/different status (e.g. the row
    # rolled off the source's window and a different source re-touches it
    # with no status text at all) — the dismissal fact must persist.
    meta = fdh.observe_case(con, state="NC", county="Buncombe",
                            case_number="24CVD001234-320", owner_name="BOB JONES",
                            status=None)
    assert meta["ever_dismissed"] is True


def test_single_dismissal_does_not_trigger_repeat_flag(tmp_path):
    con = fdh.connect(tmp_path / "h.db")
    fdh.observe_case(con, state="SC", county="Pickens", case_number="2026-CP-39-00001",
                     owner_name="MARY WHITE", status="Dismissed")
    flag = fdh.repeat_filing_flag(con, state="SC", county="Pickens",
                                  owner_name="MARY WHITE")
    assert flag is None, "one dismissal is not a 'repeat' filer"


def test_two_dismissals_for_the_same_owner_trigger_the_flag(tmp_path):
    con = fdh.connect(tmp_path / "h.db")
    fdh.observe_case(con, state="SC", county="Pickens", case_number="2026-CP-39-00001",
                     owner_name="MARY WHITE", plaintiff="ACME BANK", status="Dismissed")
    fdh.observe_case(con, state="SC", county="Pickens", case_number="2026-CP-39-00099",
                     owner_name="MARY WHITE", plaintiff="ACME BANK", status="Dismissed")
    flag = fdh.repeat_filing_flag(con, state="SC", county="Pickens",
                                  owner_name="MARY WHITE")
    assert flag is not None
    assert flag["count"] == 2
    assert flag["basis"] == "status_text"
    assert flag["total_filings_against_owner"] == 2
    case_numbers = {c["case_number"] for c in flag["prior_dismissed_cases"]}
    assert case_numbers == {"2026-CP-39-00001", "2026-CP-39-00099"}


def test_exclude_case_number_leaves_out_the_case_being_asked_about(tmp_path):
    """A THIRD, currently-active case against the same owner should be able
    to ask 'does this owner have a failure history aside from me' without
    counting itself."""
    con = fdh.connect(tmp_path / "h.db")
    fdh.observe_case(con, state="SC", county="Oconee", case_number="2026-CP-37-00001",
                     owner_name="TOM BLACK", status="Dismissed")
    fdh.observe_case(con, state="SC", county="Oconee", case_number="2026-CP-37-00002",
                     owner_name="TOM BLACK", status="Terminated")
    fdh.observe_case(con, state="SC", county="Oconee", case_number="2026-CP-37-00003",
                     owner_name="TOM BLACK", status="Pending")
    flag = fdh.repeat_filing_flag(con, state="SC", county="Oconee",
                                  owner_name="TOM BLACK",
                                  exclude_case_number="2026-CP-37-00003")
    assert flag is not None
    assert flag["count"] == 2
    # Excluding ONE of the two dismissed cases leaves only one qualifying
    # case behind — below the 2+ threshold, so no flag (min_dismissed=1
    # confirms the exclusion itself worked: exactly 1 remains, not 2).
    assert fdh.repeat_filing_flag(
        con, state="SC", county="Oconee", owner_name="TOM BLACK",
        exclude_case_number="2026-CP-37-00001") is None
    flag_min1 = fdh.repeat_filing_flag(
        con, state="SC", county="Oconee", owner_name="TOM BLACK",
        exclude_case_number="2026-CP-37-00001", min_dismissed=1)
    assert flag_min1["count"] == 1
    assert flag_min1["prior_dismissed_cases"][0]["case_number"] == "2026-CP-37-00002"


def test_two_counties_with_the_same_owner_name_do_not_collide(tmp_path):
    con = fdh.connect(tmp_path / "h.db")
    fdh.observe_case(con, state="SC", county="Laurens", case_number="2026-CP-30-00001",
                     owner_name="RICK GREEN", status="Dismissed")
    fdh.observe_case(con, state="SC", county="Laurens", case_number="2026-CP-30-00002",
                     owner_name="RICK GREEN", status="Dismissed")
    # Same name, DIFFERENT county — must not inherit Laurens' history.
    flag_other_county = fdh.repeat_filing_flag(con, state="SC", county="Union",
                                               owner_name="RICK GREEN")
    assert flag_other_county is None
    flag_laurens = fdh.repeat_filing_flag(con, state="SC", county="Laurens",
                                          owner_name="RICK GREEN")
    assert flag_laurens is not None
    assert flag_laurens["count"] == 2


def test_case_key_normalizes_dashed_and_undashed_case_numbers_to_one_row(tmp_path):
    """national.sc_public_index leaves case numbers undashed
    ('2026CP4201234'); sc_public_index_lis_pendens normalizes to
    '2026-CP-42-01234'. The SAME real case scraped by both sources must
    resolve to one history row, not two."""
    con = fdh.connect(tmp_path / "h.db")
    t1 = datetime(2026, 8, 1, tzinfo=timezone.utc)
    t2 = datetime(2026, 9, 1, tzinfo=timezone.utc)
    fdh.observe_case(con, state="SC", county="Spartanburg", case_number="2026CP4201234",
                     owner_name="AL YOUNG", status="Pending", now=t1)
    meta = fdh.observe_case(con, state="SC", county="Spartanburg",
                            case_number="2026-CP-42-01234", owner_name="AL YOUNG",
                            status="Dismissed", now=t2)
    assert meta["is_new"] is False, "dashed/undashed forms must be the same case row"
    assert con.execute("SELECT COUNT(*) FROM cases").fetchone()[0] == 1


def test_missing_case_number_or_owner_name_writes_nothing(tmp_path):
    con = fdh.connect(tmp_path / "h.db")
    assert fdh.observe_case(con, state="SC", county="Union", case_number="",
                            owner_name="NOBODY", status="Dismissed") is None
    assert fdh.observe_case(con, state="SC", county="Union", case_number="2026-CP-1",
                            owner_name="", status="Dismissed") is None
    assert con.execute("SELECT COUNT(*) FROM cases").fetchone()[0] == 0


def test_stats_rolls_up_per_state_county(tmp_path):
    con = fdh.connect(tmp_path / "h.db")
    fdh.observe_case(con, state="NC", county="Henderson", case_number="24CVD0001",
                     owner_name="A B", status="Active")
    fdh.observe_case(con, state="NC", county="Henderson", case_number="24CVD0002",
                     owner_name="C D", status="Dismissed")
    rows = {(r["state"], r["county"]): r for r in fdh.stats(con)}
    r = rows[("NC", "Henderson")]
    assert r["total_cases"] == 2
    assert r["dismissed_cases"] == 1


def test_is_dismissal_status_matches_the_synthesis_vocabulary_only():
    assert fdh.is_dismissal_status("Dismissed") is True
    assert fdh.is_dismissal_status("Terminated") is True
    assert fdh.is_dismissal_status("Withdrawn") is True
    assert fdh.is_dismissal_status("Judgment") is False
    assert fdh.is_dismissal_status("Settled") is False
    assert fdh.is_dismissal_status("Satisfied") is False
    assert fdh.is_dismissal_status(None) is False
    assert fdh.is_dismissal_status("") is False
