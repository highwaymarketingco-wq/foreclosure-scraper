"""Pin the NC eCourts docket-history recording hook (Dirty Deeds Tier B #37).

`_hit_to_listing` correctly discards a hit whose civilJudgmentStatus is
terminal (Dismissed/Canceled/Satisfied/Vacated/Withdrawn/Expired/Released) —
a dead lien is not an actionable lead. But that means the fact "this case was
Dismissed" would otherwise leave zero trace once the status changes, because
the hit never becomes a Listing for anything downstream to observe. This pins
that `_record_docket_history` captures it BEFORE that filter runs, from the
same `all_hits` list `fetch()` builds, using the live API hit shape (same
`_hit()` builder `test_nc_ecourts_active_filter.py` uses).
"""
from __future__ import annotations

from foreclosure_scraper import foreclosure_docket_history as fdh
from foreclosure_scraper.scrapers.counties_nc.nc_ecourts_lis_pendens import (
    _hit_to_listing,
    _record_docket_history,
)

SLUG = "counties_nc.nc_ecourts_lis_pendens"


def _hit(case_no: str, status: str, cause: str = "CV - Lis Pendens",
        location: str = "Henderson District Court",
        debtor: str = "Smith John", creditor: str = "Acme Bank") -> dict:
    return {
        "caseNumber": case_no,
        "orderedDate": "2026-06-01T00:00:00",
        "judgmentType": "Civil",
        "civilJudgmentStatus": status,
        "caseCategoryKey": "CV",
        "caseID": "abc123",
        "judgmentId": "j-001",
        "causeOfActionDesc": cause,
        "location": location,
        "debtors": [{"name": debtor}],
        "creditors": [{"name": creditor}],
    }


def test_dismissed_hit_is_recorded_even_though_it_never_becomes_a_listing(tmp_path):
    hit = _hit("24CVD005555-320", "Dismissed")
    # Confirm the premise: this hit produces NO Listing.
    assert _hit_to_listing(hit, SLUG) is None

    con = fdh.connect(tmp_path / "h.db")
    _record_docket_history(con, hit, SLUG)
    con.commit()

    row = con.execute(
        "SELECT ever_dismissed, latest_status FROM cases WHERE case_number=?",
        ("24CVD005555-320",),
    ).fetchone()
    assert row is not None, "dismissed hit must still be recorded in the sidecar"
    assert row["ever_dismissed"] == 1
    assert row["latest_status"] == "Dismissed"


def test_active_hit_is_recorded_and_not_dismissed(tmp_path):
    hit = _hit("24CVD006666-320", "Active")
    assert _hit_to_listing(hit, SLUG) is not None

    con = fdh.connect(tmp_path / "h.db")
    _record_docket_history(con, hit, SLUG)
    con.commit()

    row = con.execute(
        "SELECT ever_dismissed FROM cases WHERE case_number=?",
        ("24CVD006666-320",),
    ).fetchone()
    assert row["ever_dismissed"] == 0


def test_non_foreclosure_cause_is_not_recorded(tmp_path):
    """Divorce judgments aren't a lender filing — out of scope for this
    signal even though the scraper also handles FAM - Divorce hits."""
    hit = _hit("24CVD007777-320", "Dismissed", cause="FAM - Divorce")
    con = fdh.connect(tmp_path / "h.db")
    _record_docket_history(con, hit, SLUG)
    con.commit()
    assert con.execute("SELECT COUNT(*) FROM cases").fetchone()[0] == 0


def test_repeat_dismissed_cases_can_then_flag_a_later_active_case(tmp_path):
    con = fdh.connect(tmp_path / "h.db")
    _record_docket_history(con, _hit("24CVD001111-320", "Dismissed", debtor="Bob Jones"), SLUG)
    _record_docket_history(con, _hit("24CVD002222-320", "Terminated", debtor="Bob Jones"), SLUG)
    con.commit()

    flag = fdh.repeat_filing_flag(con, state="NC", county="Henderson",
                                  owner_name="Bob Jones",
                                  exclude_case_number="24CVD003333-320")
    assert flag is not None
    assert flag["count"] == 2
