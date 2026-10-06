"""The pipeline's jail stamp, re-evaluated: spelling drift and long stays (2026-10-06, HANDOFF 79).

The per-listing verifier (verification/verifiers/jail_booking.py, v2) was fixed for two defects the
live re-check found, and the pipeline's own stamping step (enrichment_jail_bookings.
_reevaluate_stamp, which match_rosters and enrich_jail_bookings call each run) had both:

  * SPELLING DRIFT. It looked the stamp's person up by the exact first + last name, so a person
    still on the roster whose first name the vendor had respelled by one inserted character read as
    "absent", was marked released_or_transferred, and the scorer dropped the incarceration signal.
    Now one roster record with the same last name, booking date and date of birth (else age) and a
    first name within the edit distance is the same person.
  * LONG STAYS. It read any absence from a healthy roster as a release. A county roster cannot
    tell a release from a transfer to state prison, so after a stay of 60 days or more the claim is
    kept (roster_absence_reason possible_transfer_to_prison); 59 days still reads as released.

The rules are jail_matching's, shared with the verifier: the parity tests at the end run the REAL
verifier and the stamp on the same roster and require the same answer. Every name is a made-up
placeholder (the stamp carries the older spelling PATRIK, the roster says PATRICK: the one inserted
character of the Henderson case); no network.
"""
from __future__ import annotations

import asyncio
import copy
import sys
from datetime import date
from pathlib import Path

import pytest

from foreclosure_scraper import enrichment_jail_bookings as jb
from foreclosure_scraper.distress_score import _signals_for
from foreclosure_scraper.models import Listing
from foreclosure_scraper.signal_freshness import custody_ended, incarceration_active
from foreclosure_scraper.verification.verifiers import jail_booking as v
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

import backfill_jail_rosters as bjr  # noqa: E402
from tests.test_jail_bookings_middle_gate_reeval import _fillers as _pipe_fillers
from tests.test_jail_bookings_middle_gate_reeval import _install as _pipe_install
from tests.test_verification_jail_booking import (  # noqa: F401  (_own_history: autouse fixture)
    _Client, _fillers, _install, _jail_inc, _own_history, _row, _seed_history, _stamp,
)
from tests.test_verification_jail_recheck_defects import drift_row, zrec

TODAY = date(2026, 10, 6)
KEY = ("NC", "Henderson")


# --------------------------------------------------------------------------- #
# rows and rosters                                                            #
# --------------------------------------------------------------------------- #

def _own(matched="PATRIK TESTOWNER", **extra):
    s = {"county": "Henderson", "state": "NC", "matched_name": matched,
         "release_status": "in_custody", "scheduled_release": None,
         "confidence": "name_only_low", "facility_type": "jail",
         "arrest_date": "2026-09-01", "roster_dob": "1980-04-12"}
    s.update(extra)
    return s


def _li(stamp=None, owner="TESTOWNER PATRIK A"):
    return Listing(source="test", source_url="http://x", state="NC", county="Henderson County",
                   raw={"owner_mailing": {"owner": owner},
                        "jail_booking": stamp if stamp is not None else _own(),
                        "incarceration": {"state": "NC", "source": "Henderson County jail roster",
                                          "matched_name": "PATRIK TESTOWNER",
                                          "confidence": "name_only_low"}})


def _rec(last="TESTOWNER", first="PATRICK", middle="ALLEN", dob="1980-04-12", age=None,
         arrest="2026-09-01T00:00:00.000Z", **extra):
    r = {"last": last, "first": first, "middle": middle, "dob": dob, "age": age,
         "arrest_date": arrest, "charge": "PLACEHOLDER CHARGE"}
    r.update(extra)
    return r


def _idx(*recs, healthy=True):
    idx = jb.RosterIndex()
    for r in recs:
        idx.add(r)
    idx.healthy = healthy
    return idx


def _run(li, idx, today=TODAY):
    stats: dict = {}
    jb.match_rosters([li], {KEY: idx}, today=today, stats=stats)
    return stats


def _scored(li):
    return "incarceration" in [n for n, _c, _w in _signals_for(li, today=TODAY)]


# --------------------------------------------------------------------------- #
# spelling drift                                                              #
# --------------------------------------------------------------------------- #

def test_a_respelled_first_name_on_the_roster_is_the_same_person_not_a_release():
    """The Henderson case: still on the live roster, first name one inserted character off."""
    li = _li()
    stats = _run(li, _idx(_rec()))
    jbk = li.raw["jail_booking"]
    assert stats == {"reeval_confirmed": 1}
    assert jbk["release_status"] == "in_custody" and "left_roster_detected_at" not in jbk
    assert custody_ended(jbk, TODAY) is False and _scored(li)
    assert jbk["matched_name"] == "PATRIK TESTOWNER"            # the stamp keeps its own spelling
    assert jbk["last_confirmed_on_roster"] == "2026-10-06"
    assert jbk["middle_verdict"] == "agrees" and jbk["confidence"] == "middle_corroborated"
    assert (jbk["name_variant"], jbk["name_variant_edit_distance"],
            jbk["name_variant_basis"]) == (True, 1, "dob")
    assert li.raw["incarceration"]["confidence"] == "middle_corroborated"


def test_the_variant_stamp_never_carries_the_rosters_spelling():
    li = _li()
    _run(li, _idx(_rec()))
    blob = repr(li.raw["jail_booking"])
    assert "PATRICK" not in blob and "TESTOWNER" in blob        # only the stamp's own name


def test_a_variant_whose_middle_name_conflicts_is_a_different_person():
    li = _li()
    stats = _run(li, _idx(_rec(middle="KYLE")))
    assert stats == {"reeval_conflict_cleared": 1}
    assert "jail_booking" not in li.raw and "incarceration" not in li.raw


def test_a_different_last_name_is_never_a_variant():
    """The Buncombe case: same first name, booking day and age, another last name: another person,
    so the stamp's person is gone (a 35-day stay: released)."""
    li = _li()
    other = _rec(last="OTHERLAST", first="PATRIK", dob=None, age="41",
                 arrest="2026-09-01T14:30:00.000Z")
    stats = _run(li, _idx(other))
    assert stats == {"reeval_left_roster": 1}
    assert "name_variant" not in li.raw["jail_booking"]
    assert custody_ended(li.raw["jail_booking"], TODAY) is True


@pytest.mark.parametrize("kw", [{"dob": "1979-04-12"},                       # another date of birth
                                {"arrest": "2026-09-02T00:00:00.000Z"}])     # another booking day
def test_a_different_dob_or_booking_day_is_a_different_person(kw):
    li = _li()
    assert _run(li, _idx(_rec(**kw))) == {"reeval_left_roster": 1}
    assert "name_variant" not in li.raw["jail_booking"]


def test_two_candidate_spellings_are_ambiguous_and_the_stamp_is_left_as_it_was():
    li = _li()
    before = copy.deepcopy(li.raw)
    stats = _run(li, _idx(_rec(), _rec(first="PATRYK")))
    assert stats == {"reeval_ambiguous_name_variant": 1}
    assert li.raw == before                                     # neither ended nor refreshed
    assert custody_ended(li.raw["jail_booking"], TODAY) is False


def test_age_decides_when_a_side_has_no_date_of_birth():
    """CentralSquare rosters redact the DOB and keep the age."""
    stamp = _own(roster_dob=None, roster_age=41)
    li = _li(stamp)
    assert _run(li, _idx(_rec(dob=None, age="41"))) == {"reeval_confirmed": 1}
    assert li.raw["jail_booking"]["name_variant_basis"] == "age"
    li2 = _li(_own(roster_dob=None, roster_age=41))
    assert _run(li2, _idx(_rec(dob=None, age="42"))) == {"reeval_left_roster": 1}
    li3 = _li(_own(roster_dob=None, roster_age=41))
    assert _run(li3, _idx(_rec(dob=None, age=None))) == {"reeval_left_roster": 1}   # nothing to compare


def test_a_stamp_with_no_booking_date_cannot_match_fuzzily():
    li = _li(_own(arrest_date=None))
    assert _run(li, _idx(_rec())) == {"reeval_left_roster": 1}


def test_the_exact_name_is_untouched_and_clears_an_earlier_variant_marking():
    li = _li(_own(name_variant=True, name_variant_edit_distance=1, name_variant_basis="dob"))
    stats = _run(li, _idx(_rec(first="PATRIK")))
    assert stats == {"reeval_confirmed": 1}
    assert not [k for k in li.raw["jail_booking"] if k.startswith("name_variant")]


def test_a_variant_on_an_unhealthy_roster_is_still_presence():
    """Presence needs no health; only ABSENCE is gated on the roster being healthy."""
    li = _li()
    assert _run(li, _idx(_rec(), healthy=False)) == {"reeval_confirmed": 1}
    assert custody_ended(li.raw["jail_booking"], TODAY) is False


def test_the_variant_stamp_is_idempotent_across_runs():
    li = _li()
    idx = _idx(_rec())
    _run(li, idx)
    after_first = copy.deepcopy(li.raw)
    stats = _run(li, idx)
    assert li.raw == after_first and stats == {"reeval_confirmed": 1}


# --------------------------------------------------------------------------- #
# long stays                                                                  #
# --------------------------------------------------------------------------- #

def _absent():
    return _idx(_rec(last="SOMEONE", first="ELSE"), healthy=True)


def test_a_59_day_stay_is_released_and_a_60_day_stay_is_not():
    short, long_ = _li(_own(arrest_date="2026-08-08")), _li(_own(arrest_date="2026-08-07"))
    assert (TODAY - date(2026, 8, 8)).days == 59 and (TODAY - date(2026, 8, 7)).days == 60
    assert _run(short, _absent()) == {"reeval_left_roster": 1}
    assert short.raw["jail_booking"]["release_status"] == jb.LEFT_ROSTER_STATUS
    assert custody_ended(short.raw["jail_booking"], TODAY) is True and not _scored(short)

    assert _run(long_, _absent()) == {"reeval_long_stay_kept": 1}
    jbk = long_.raw["jail_booking"]
    assert jbk["release_status"] == "in_custody" and "left_roster_detected_at" not in jbk
    assert jbk["roster_absence_reason"] == "possible_transfer_to_prison"
    assert jbk["roster_absence_detected_at"] == "2026-10-06" and jbk["roster_absence_stay_days"] == 60
    assert jbk["matched_name"] == "PATRIK TESTOWNER"
    assert custody_ended(jbk, TODAY) is False and _scored(long_)
    assert incarceration_active(long_.raw["incarceration"], jbk, TODAY) is True


@pytest.mark.parametrize("booked", ["2024-12-14", "2025-10-16", "2026-01-09", "2026-07-17"])
def test_the_real_long_stays_keep_the_claim(booked):
    """Real long stays the verifier re-check found stale (about 662, 355, 270 and 81-87 days)."""
    li = _li(_own(arrest_date=booked))
    assert _run(li, _absent()) == {"reeval_long_stay_kept": 1}
    assert custody_ended(li.raw["jail_booking"], TODAY) is False


def test_the_stay_ends_at_the_last_time_the_person_was_seen_on_the_roster():
    """Booked 127 days ago, last seen 19 days after: a short stay, then gone (released). Last seen
    105 days after: a long one."""
    short = _li(_own(arrest_date="2026-06-01", last_confirmed_on_roster="2026-06-20"))
    assert _run(short, _absent()) == {"reeval_left_roster": 1}
    long_ = _li(_own(arrest_date="2026-06-01", last_confirmed_on_roster="2026-09-20"))
    assert _run(long_, _absent()) == {"reeval_long_stay_kept": 1}
    # no last-seen date: the span to today is the upper bound
    assert _run(_li(_own(arrest_date="2026-06-01")), _absent()) == {"reeval_long_stay_kept": 1}


def test_a_stamp_with_no_booking_date_cannot_be_measured_and_still_reads_as_released():
    """The verifier's rule too (stay_days is None: not a long stay)."""
    li = _li(_own(arrest_date=None))
    assert _run(li, _absent()) == {"reeval_left_roster": 1}


def test_an_unhealthy_roster_never_reads_a_long_stay_absence_either_way():
    li = _li(_own(arrest_date="2025-01-01"))
    before = copy.deepcopy(li.raw)
    assert _run(li, _idx(_rec(last="SOMEONE", first="ELSE"), healthy=False)) == {
        "reeval_absent_roster_unhealthy": 1}
    assert li.raw == before                      # no roster_absence_* keys either


def test_the_long_stay_stamp_is_idempotent_and_keeps_its_first_detection():
    li = _li(_own(arrest_date="2026-06-01", last_confirmed_on_roster="2026-09-20"))
    _run(li, _absent(), today=TODAY)
    after_first = copy.deepcopy(li.raw)
    stats = _run(li, _absent(), today=date(2026, 10, 20))        # a later run, same absence
    assert stats == {"reeval_long_stay_kept": 1}
    assert li.raw == after_first
    assert li.raw["jail_booking"]["roster_absence_detected_at"] == "2026-10-06"


def test_back_on_the_roster_after_a_kept_long_stay_clears_the_absence_marking():
    li = _li(_own(arrest_date="2026-06-01", last_confirmed_on_roster="2026-09-20"))
    _run(li, _absent())
    assert li.raw["jail_booking"]["roster_absence_reason"]
    stats = _run(li, _idx(_rec(first="PATRIK")), today=date(2026, 10, 13))
    jbk = li.raw["jail_booking"]
    assert stats == {"reeval_confirmed": 1}
    assert not [k for k in jbk if k.startswith("roster_absence")]
    assert jbk["last_confirmed_on_roster"] == "2026-10-13"


def test_a_long_stay_an_earlier_run_marked_ended_is_restored():
    """The old rule ended the claim after any absence. The stay is bounded by the last time the
    person was seen, or (no such date on the stamp) by the date it was marked ended."""
    ended = _own(arrest_date="2024-10-01", release_status=jb.LEFT_ROSTER_STATUS,
                 left_roster_detected_at="2026-09-29")
    li = _li(ended)
    assert custody_ended(li.raw["jail_booking"], TODAY) is True
    assert _run(li, _absent()) == {"reeval_long_stay_restored": 1}
    jbk = li.raw["jail_booking"]
    assert jbk["release_status"] == "in_custody" and "left_roster_detected_at" not in jbk
    assert jbk["roster_absence_reason"] == "possible_transfer_to_prison"
    assert custody_ended(jbk, TODAY) is False and _scored(li)
    assert _run(li, _absent(), today=date(2026, 10, 13)) == {"reeval_long_stay_kept": 1}   # now stable


def test_a_short_stay_marked_ended_stays_ended_as_the_days_pass():
    """No last_confirmed_on_roster on the stamp: measuring to today would, weeks later, turn a real
    12-day stay into a 'long' one. The marking date bounds it."""
    li = _li(_own(arrest_date="2026-08-20", release_status=jb.LEFT_ROSTER_STATUS,
                  left_roster_detected_at="2026-09-01"))
    assert _run(li, _absent(), today=date(2026, 12, 1)) == {"reeval_already_ended": 1}
    assert custody_ended(li.raw["jail_booking"], date(2026, 12, 1)) is True


def test_the_search_lane_still_never_reads_absence():
    """roster_complete=False (LANSA page 1): neither a release nor a long-stay marking."""
    li = _li(_own(arrest_date="2025-01-01"))
    before = copy.deepcopy(li.raw)
    outcome = jb._reevaluate_stamp(li, _idx(_rec(last="SOMEONE", first="ELSE")),
                                   ("TESTOWNER", "PATRIK"), roster_complete=False, today=TODAY)
    assert outcome == "absent_unchecked" and li.raw == before


# --------------------------------------------------------------------------- #
# end to end: the real fetcher + _load_roster + health judge (Zuercher fake)  #
# --------------------------------------------------------------------------- #

def _sc_li(stamp):
    return Listing(source="test", source_url="http://x", state="SC", county="Cherokee County",
                   raw={"owner_mailing": {"owner": "TESTOWNER PATRIK A"}, "jail_booking": stamp,
                        "incarceration": {"state": "SC", "source": "Cherokee County jail roster",
                                          "matched_name": "PATRIK TESTOWNER",
                                          "confidence": "name_only_low"}})


def _sc_stamp(**extra):
    s = {"county": "Cherokee", "state": "SC", "matched_name": "PATRIK TESTOWNER",
         "release_status": "in_custody", "scheduled_release": None,
         "confidence": "name_only_low", "facility_type": "jail", "arrest_date": "2026-09-01",
         "roster_dob": "1980-04-12"}
    s.update(extra)
    return s


@pytest.mark.asyncio
async def test_e2e_the_respelled_person_stays_on_the_roster_run_after_run(monkeypatch):
    present = [{"name": "Testowner, Patrick Allen", "dob": "1980-04-12",
                "arrest_date": "2026-09-01T00:00:00.000Z", "hold_reasons": "PLACEHOLDER"}]
    _pipe_install(monkeypatch, [present + _pipe_fillers(99), present + _pipe_fillers(99)])
    li = _sc_li(_sc_stamp())
    r1 = await jb.enrich_jail_bookings([li], today=date(2026, 10, 5))
    r2 = await jb.enrich_jail_bookings([li], today=TODAY)
    assert r1["reeval_confirmed"] == 1 and r2["rosters_unhealthy"] == []
    assert r2["reeval_confirmed"] == 1 and r2.get("reeval_left_roster", 0) == 0
    assert custody_ended(li.raw["jail_booking"], TODAY) is False


@pytest.mark.asyncio
@pytest.mark.parametrize("booked, key", [("2026-08-08", "reeval_left_roster"),          # 59 days
                                         ("2026-08-07", "reeval_long_stay_kept")])      # 60 days
async def test_e2e_absent_from_a_healthy_roster_after_59_versus_60_days(monkeypatch, booked, key):
    _pipe_install(monkeypatch, [_pipe_fillers(100), _pipe_fillers(100)])
    li = _sc_li(_sc_stamp(arrest_date=booked))
    r1 = await jb.enrich_jail_bookings([li], today=date(2026, 10, 5))     # cold sidecar: not trusted
    assert r1["reeval_absent_roster_unhealthy"] == 1
    r2 = await jb.enrich_jail_bookings([li], today=TODAY)
    assert r2[key] == 1
    assert custody_ended(li.raw["jail_booking"], TODAY) is (key == "reeval_left_roster")


# --------------------------------------------------------------------------- #
# parity with the REAL verifier on the same roster                            #
# --------------------------------------------------------------------------- #

_SEEN_AS = {"conflict_cleared": {"refuted"}, "left_roster": {"stale"},
            "absent_unchecked": {"unconfirmed"}, "ambiguous_variant": {"unconfirmed"},
            "long_stay_kept": {"unconfirmed"}, "confirmed": {"confirmed", "unconfirmed"}}

_PRESENT = lambda **kw: ([zrec("Testowner, Patrick Allen", **kw)] + _fillers(99), (100,))   # noqa: E731
_ABSENT = (_fillers(101), (100, 104, 98))

PARITY = [
    # id, roster, history sizes, stamp overrides, verifier verdict, verifier reason, stamp outcome
    ("variant", *_PRESENT(), {}, "confirmed", None, "confirmed"),
    ("variant_middle_conflict", [zrec("Testowner, Patrick Kyle")] + _fillers(99), (100,), {},
     "refuted", None, "conflict_cleared"),
    ("variant_other_dob", *_PRESENT(dob="1979-04-12"), {}, "stale", None, "left_roster"),
    ("variant_other_booking_day", *_PRESENT(arrest="2026-09-02T00:00:00.000Z"), {},
     "stale", None, "left_roster"),
    ("two_candidates", [zrec("Testowner, Patrick Allen"), zrec("Testowner, Patryk Allen")]
     + _fillers(98), (100,), {}, "unconfirmed", "ambiguous_name_variant", "ambiguous_variant"),
    ("662_days", *_ABSENT, {"arrest_date": "2024-12-14"}, "unconfirmed",
     "possible_transfer_to_prison", "long_stay_kept"),
    ("59_days", *_ABSENT, {"arrest_date": "2026-08-08"}, "stale", None, "left_roster"),
    ("60_days", *_ABSENT, {"arrest_date": "2026-08-07"}, "unconfirmed",
     "possible_transfer_to_prison", "long_stay_kept"),
    ("last_seen_after_19_days", *_ABSENT,
     {"arrest_date": "2026-06-01", "last_confirmed_on_roster": "2026-06-20"}, "stale", None,
     "left_roster"),
    ("last_seen_after_111_days", *_ABSENT,
     {"arrest_date": "2026-06-01", "last_confirmed_on_roster": "2026-09-20"}, "unconfirmed",
     "possible_transfer_to_prison", "long_stay_kept"),
    ("no_booking_date", *_ABSENT, {"arrest_date": None, "roster_dob": None}, "stale", None,
     "left_roster"),
    ("unhealthy_long_stay", _fillers(25), (100,), {"arrest_date": "2025-01-01"}, "unconfirmed",
     "roster_unhealthy", "absent_unchecked"),
]


@pytest.mark.parametrize("name, roster, sizes, over, verdict, reason, outcome", PARITY,
                         ids=[p[0] for p in PARITY])
def test_the_stamp_and_the_verifier_read_the_same_roster_the_same_way(
        monkeypatch, name, roster, sizes, over, verdict, reason, outcome):
    _seed_history(sizes=sizes)
    _install(monkeypatch, [roster])
    row = drift_row()
    row["raw"]["jail_booking"].update(over)
    client = _Client()                             # held: the per-run cache is keyed weakly by it
    res = asyncio.run(v.verify(row, client, today=TODAY))
    idx = v._RUNS[client][("SC", "Cherokee")].index
    li = Listing(source="t", source_url="http://x", state="SC", county="Cherokee",
                 raw=copy.deepcopy(row["raw"]))
    got = jb._reevaluate_stamp(li, idx, jb._name_parts(jb._owner_of(li)),
                               roster_complete=bool(idx.healthy), today=TODAY)
    assert (res.verdict, res.evidence.get("reason"), got) == (verdict, reason, outcome)
    assert res.verdict in _SEEN_AS[got]
    # the claim is ended exactly when the verifier says stale / refuted
    jbk = li.raw.get("jail_booking")
    ended = jbk is None or custody_ended(jbk, TODAY)
    assert ended == (res.verdict in ("stale", "refuted"))


# --------------------------------------------------------------------------- #
# the backfill script's dry run counts what the rule does                     #
# --------------------------------------------------------------------------- #

def _board_row(owner, matched, **stamp_extra):
    return {"state": "NC", "county": "Henderson County", "defendant": None,
            "raw": {"owner_mailing": {"owner": owner},
                    "jail_booking": _own(matched=matched, **stamp_extra),
                    "incarceration": {"state": "NC", "source": "Henderson County jail roster",
                                      "matched_name": matched, "confidence": "name_only_low"}}}


def test_the_backfill_dry_run_preview_agrees_with_the_rule():
    rows = [_board_row("TESTOWNER PATRIK A", "PATRIK TESTOWNER"),                    # respelled
            _board_row("LONGSTAY PERSON", "PERSON LONGSTAY", arrest_date="2025-01-01"),
            _board_row("SHORTSTAY PERSON", "PERSON SHORTSTAY", arrest_date="2026-09-20"),
            _board_row("PRESENT PERSON", "PERSON PRESENT")]
    idx = _idx(_rec(), _rec(last="PRESENT", first="PERSON", middle=""))

    scan = bjr.scan_board(rows, {KEY})[KEY]
    assert len(scan["stamped"]) == 4
    preview = bjr.reeval_preview(scan, idx, today=TODAY)
    assert preview == {"rechecked": 4, "conflict_cleared": 0, "left_roster": 1,
                       "long_stay_kept": 1, "name_variant": 1, "ambiguous_variant": 0}

    listings = [Listing(source="t", source_url="http://x", state=r["state"], county=r["county"],
                        raw=copy.deepcopy(r["raw"]), defendant=r["defendant"]) for r in rows]
    stats: dict = {}
    jb.match_rosters(listings, {KEY: idx}, today=TODAY, stats=stats)
    assert stats == {"reeval_confirmed": 2, "reeval_long_stay_kept": 1, "reeval_left_roster": 1}
