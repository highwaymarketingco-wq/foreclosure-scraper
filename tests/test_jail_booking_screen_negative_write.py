"""match_rosters()'s bulk-roster lane used to write nothing at all when a healthy roster
matched nobody -- invisible to gap_matrix.py's county-scope "ran" check (pos>0 or chk>0 on
ANY row in the county). Fixed 2026-10-16 (gap-sweep wave 3) to stamp one per-county
"screened, none found" sentinel, raw['jail_booking_screen'] -- a SEPARATE key from
raw['jail_booking'] itself, because _gate_jail treats any non-empty jail_booking dict
without a release marker as a currently-active booking: a {"result": "no_match"} wrapper
written to that key would be misread as a hit.
"""
from __future__ import annotations

from datetime import date

from foreclosure_scraper.enrichment_jail_bookings import RosterIndex, match_rosters
from foreclosure_scraper.models import Listing

D1 = date(2026, 10, 16)


def _li(owner, state="NC", county="Transylvania"):
    return Listing(source="test", source_url="http://x", state=state,
                   county=f"{county} County", raw={"owner_mailing": {"owner": owner}})


def _hit(last, first, middle="", **extra):
    return {"last": last, "first": first, "middle": middle,
            "arrest_date": "2026-10-01", "charge": "PLACEHOLDER", **extra}


def _index(*recs, healthy=False):
    idx = RosterIndex()
    for r in recs:
        idx.add(r)
    idx.healthy = healthy
    return idx


def test_a_healthy_roster_with_no_match_still_stamps_a_screen_not_a_hit():
    li = _li("NOBODY, HOME")
    idx = _index(_hit("SOMEONE", "ELSE"), healthy=True)
    match_rosters([li], {("NC", "Transylvania"): idx}, today=D1)
    assert "jail_booking" not in li.raw                  # never a false positive hit
    screen = li.raw["jail_booking_screen"]
    assert screen["result"] == "no_match"
    assert screen["county"] == "Transylvania" and screen["state"] == "NC"
    assert screen["checked_at"]


def test_an_unhealthy_roster_fetch_does_not_stamp_a_screen():
    """A failed/empty/implausible roster must never credit the county as checked --
    the same safeguard already established for the release-detection side of this
    module (test_jail_bookings_middle_gate_reeval.py)."""
    li = _li("NOBODY, HOME")
    idx = _index(healthy=False)
    match_rosters([li], {("NC", "Transylvania"): idx}, today=D1)
    assert "jail_booking_screen" not in li.raw


def test_a_real_match_does_not_also_get_a_screen_wrapper():
    li = _li("DOE, JOHN")
    idx = _index(_hit("DOE", "JOHN"), healthy=True)
    match_rosters([li], {("NC", "Transylvania"): idx}, today=D1)
    assert li.raw["jail_booking"]["matched_name"] == "JOHN DOE"
    assert "jail_booking_screen" not in li.raw


def test_a_matched_row_does_not_consume_the_countys_sentinel_for_a_later_unmatched_row():
    """The sentinel is only written on a genuine no-match search, never pre-emptively on
    the first row seen -- so a county whose first lead matches still screens its other,
    unmatched leads correctly."""
    matched, unmatched = _li("DOE, JOHN"), _li("NOBODY, HOME")
    idx = _index(_hit("DOE", "JOHN"), healthy=True)
    match_rosters([matched, unmatched], {("NC", "Transylvania"): idx}, today=D1)
    assert "jail_booking_screen" not in matched.raw
    assert unmatched.raw["jail_booking_screen"]["result"] == "no_match"


def test_one_sentinel_per_county_not_one_per_row():
    names = ["ALLEN, ANN", "BAKER, BOB", "CARR, CARL", "DAVIS, DAN", "EVANS, ERIN"]
    rows = [_li(n) for n in names]
    idx = _index(_hit("SOMEONE", "ELSE"), healthy=True)
    match_rosters(rows, {("NC", "Transylvania"): idx}, today=D1)
    screened = [r for r in rows if "jail_booking_screen" in r.raw]
    assert len(screened) == 1, "only the first row in the county needs the sentinel"


def test_no_roster_at_all_for_the_county_stamps_nothing():
    li = _li("NOBODY, HOME")
    match_rosters([li], {}, today=D1)
    assert "jail_booking_screen" not in li.raw
    assert "jail_booking" not in li.raw
