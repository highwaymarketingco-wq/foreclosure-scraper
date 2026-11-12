"""jail_booking v2: the two defects of the 2026-10-06 recheck of all stale verdicts.

  5. Spelling drift. A Henderson (Citizen Connect) booking: the person IS on the live roster, the
     roster's first name differs from the board stamp's by one inserted character, and the exact
     first + last lookup read "absent": stale. Same last name + same
     booking date + same date of birth (else age) + a first name within the edit distance is the
     same person; a different last name (a Buncombe case: same first name, booking day and age,
     another last name, booking time and charge) is another person.
  6. Long stays. A county roster cannot tell a release from a transfer to state prison, so a stay
     of JAIL_LONG_STAY_DAYS (60) or more that ends in an absence is unconfirmed
     (possible_transfer_to_prison), never stale. Real long stays that were stale: about 662, 355,
     270 and 102 days and four between 81 and 87.

Every name is a made-up placeholder; the roster is a Zuercher fake served through the real fetcher,
_load_roster and health judge (the shape test_verification_jail_booking.py uses). No network.
"""
from __future__ import annotations

import asyncio
from datetime import date

import pytest

from foreclosure_scraper import enrichment_jail_bookings as jb
from foreclosure_scraper.verification.verifiers import jail_booking as v
from tests.test_verification_jail_booking import (  # noqa: F401  (_own_history: autouse fixture)
    _Client, _fillers, _install, _jail_inc, _own_history, _row, _seed_history, _stamp,
)

TODAY = date(2026, 10, 6)


def run(row):
    return asyncio.run(v.verify(row, _Client(), today=TODAY))


def zrec(name, dob="1980-04-12", arrest="2026-09-01T00:00:00.000Z", charge="PLACEHOLDER CHARGE"):
    return {"name": name, "dob": dob, "arrest_date": arrest, "hold_reasons": charge}


def drift_row(**stamp_extra):
    """The stamp carries the older spelling PATRIK; the roster now says PATRICK (one inserted
    character). roster_dob / arrest_date are the stamp's own copy of the roster record."""
    stamp = _stamp(matched="PATRIK TESTOWNER", roster_dob="1980-04-12", arrest_date="2026-09-01",
                   **stamp_extra)
    return _row(owner="TESTOWNER PATRIK A", stamp=stamp, inc=_jail_inc(matched="PATRIK TESTOWNER"))


# ---------------------------------------------------------------------------
# the name rule
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("a,b,d", [
    ("PATRIK", "PATRICK", 1),            # one inserted character: the Henderson case
    ("JONATHON", "JONATHAN", 1),
    ("KATHRYN", "KATHERYN", 1),
    ("STEPHANIE", "STEPHANY", 2),        # two edits, both 5+ letters
    ("ROB", "ROBERT", 3),                # same first letter + prefix
    ("BETH", "ELIZABETH", None),         # different first letter: not a prefix variant
    ("JOHN", "JON", 1),
    ("JOHN", "JAKE", None),              # 4 letters: only one edit is allowed
    ("AL", "ALAN", None),                # under 3 letters: exact only
    ("MARK", "MARC", 1),
    ("PATRICK", "PATRICK", None),        # equal: not a variant (exact match handles it)
    ("ERIC", "ERICA", 1),
    ("DAVID", "DANIEL", None),
])
def test_first_name_variant(a, b, d):
    assert v.first_name_variant(a, b) == d


def test_the_long_stay_threshold_lives_in_one_place():
    import inspect
    assert v.JAIL_LONG_STAY_DAYS == 60
    assert inspect.getsource(v).count("JAIL_LONG_STAY_DAYS = ") == 1


# ---------------------------------------------------------------------------
# 5. spelling drift
# ---------------------------------------------------------------------------

def test_the_person_on_the_roster_under_another_spelling_is_still_on_the_roster(monkeypatch):
    """v1: no exact match -> absent from a healthy roster -> stale. v2: the same last name,
    booking date and date of birth with a one-character first-name difference IS the person."""
    _seed_history()
    _install(monkeypatch, [[zrec("Testowner, Patrick Allen")] + _fillers(99)])
    res = run(drift_row())
    assert res.verdict == "confirmed"
    ev = res.evidence
    assert ev["on_roster"] is True and ev["name_variant"] is True
    assert ev["first_name_edit_distance"] == 1 and ev["name_variant_basis"] == "dob"
    assert ev["middle_agrees"] is True and ev["same_name_count"] == 1


def test_spelling_variant_middle_conflict_is_still_a_different_person(monkeypatch):
    _seed_history()
    _install(monkeypatch, [[zrec("Testowner, Patrick Kyle")] + _fillers(99)])
    res = run(drift_row())
    assert res.verdict == "refuted" and res.evidence["name_variant"] is True


@pytest.mark.parametrize("kw,why", [
    ({"dob": "1979-04-12"}, "another date of birth"),
    ({"arrest": "2026-09-02T00:00:00.000Z"}, "another booking day"),
])
def test_a_different_dob_or_booking_day_is_a_different_person(monkeypatch, kw, why):
    _seed_history()
    _install(monkeypatch, [[zrec("Testowner, Patrick Allen", **kw)] + _fillers(99)])
    res = run(drift_row())
    assert res.verdict == "stale", why
    assert "name_variant" not in res.evidence


def test_a_different_last_name_is_never_a_variant(monkeypatch):
    """The Buncombe case: the same first name, booking day and age, but another last name (and
    booking time and charge): a different person. The stamp's person is gone: stale."""
    _seed_history()
    other = zrec("Otherlast, Patrik Allen", arrest="2026-09-01T14:30:00.000Z", charge="DWI")
    _install(monkeypatch, [[other] + _fillers(99)])
    res = run(drift_row())
    assert res.verdict == "stale" and "name_variant" not in res.evidence
    stamp = drift_row()["raw"]["jail_booking"]
    assert v.spelling_variants(_index([other]), stamp, ("TESTOWNER", "PATRIK")) == []
    # the same record under the stamp's last name would have matched (the rule is not vacuous)
    same = zrec("Testowner, Patrick Allen", arrest="2026-09-01T14:30:00.000Z", charge="DWI")
    assert len(v.spelling_variants(_index([same]), stamp, ("TESTOWNER", "PATRIK"))) == 1


def test_two_candidate_spellings_are_ambiguous_not_merged(monkeypatch):
    _seed_history()
    _install(monkeypatch, [[zrec("Testowner, Patrick Allen"), zrec("Testowner, Patryk Allen")] + _fillers(98)])
    res = run(drift_row())
    assert res.verdict == "unconfirmed" and res.evidence["reason"] == "ambiguous_name_variant"


def _index(records):
    idx = jb.RosterIndex()
    for r in records:
        first_last = v._jb()._split_zuercher_name(r["name"])
        rec = {"last": first_last[0], "first": first_last[1], "middle": first_last[2],
               "dob": r.get("dob"), "age": r.get("age"), "arrest_date": r.get("arrest_date"),
               "charge": r.get("hold_reasons")}
        idx.add(rec)
    return idx


def test_age_is_compared_when_a_side_has_no_date_of_birth():
    """P2C CentralSquare rosters redact the DOB and keep the age: the age decides."""
    stamp = {"arrest_date": "2026-09-01", "roster_dob": None, "roster_age": 41}
    mk = lambda age: _index([{"name": "Testowner, Patrick Allen", "dob": None, "age": age,   # noqa: E731
                              "arrest_date": "2026-09-01T00:00:00.000Z"}])
    got = v.spelling_variants(mk("41"), stamp, ("TESTOWNER", "PATRIK"))
    assert [g["basis"] for g in got] == ["age"] and got[0]["distance"] == 1
    assert v.spelling_variants(mk("42"), stamp, ("TESTOWNER", "PATRIK")) == []
    assert v.spelling_variants(mk(None), stamp, ("TESTOWNER", "PATRIK")) == []   # nothing to compare
    # a stamp with no booking date cannot be matched fuzzily
    assert v.spelling_variants(mk("41"), {"roster_age": 41}, ("TESTOWNER", "PATRIK")) == []


def test_the_exact_name_is_untouched_by_the_variant_rule(monkeypatch):
    _seed_history()
    _install(monkeypatch, [[zrec("Testowner, Patrik Allen")] + _fillers(99)])
    res = run(drift_row())
    assert res.verdict == "confirmed" and "name_variant" not in res.evidence


def test_the_variant_evidence_names_nobody(monkeypatch):
    _seed_history()
    _install(monkeypatch, [[zrec("Testowner, Patrick Allen")] + _fillers(99)])
    ev = run(drift_row()).evidence
    blob = repr(ev)
    for w in ("Patrick", "PATRICK", "Patrik", "PATRIK", "Testowner", "TESTOWNER", "1980"):
        assert w not in blob


# ---------------------------------------------------------------------------
# 6. long stays
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("booked", ["2024-12-14", "2025-10-16", "2026-01-09", "2026-06-26",
                                    "2026-07-14", "2026-07-17", "2026-07-11", "2026-07-09"])
def test_an_absence_after_a_long_stay_is_a_possible_transfer_not_stale(monkeypatch, booked):
    """The real long stays that were stale (about 662, 355, 270, 102 and four of 81-87 days)."""
    _seed_history(sizes=(100, 104, 98))
    _install(monkeypatch, [_fillers(101)])
    res = run(_row(stamp=_stamp(arrest_date=booked)))
    assert res.verdict == "unconfirmed" and res.evidence["reason"] == "possible_transfer_to_prison"
    assert res.evidence["on_roster"] is False and res.evidence["long_stay_days"] == 60
    assert res.evidence["stay_days"] == (TODAY - date.fromisoformat(booked)).days


@pytest.mark.parametrize("booked,verdict", [("2026-08-08", "stale"),       # 59 days
                                            ("2026-08-07", "unconfirmed"),  # 60 days
                                            ("2026-09-20", "stale")])
def test_sixty_days_is_the_line(monkeypatch, booked, verdict):
    _seed_history(sizes=(100, 104, 98))
    _install(monkeypatch, [_fillers(101)])
    assert run(_row(stamp=_stamp(arrest_date=booked))).verdict == verdict


def test_the_stay_ends_at_the_last_time_the_person_was_seen_on_the_roster(monkeypatch):
    """Booked 127 days ago but last seen on the roster 19 days after: a short stay, then gone."""
    _seed_history(sizes=(100, 104, 98))
    _install(monkeypatch, [_fillers(101)])
    short = _stamp(arrest_date="2026-06-01", last_confirmed_on_roster="2026-06-20")
    assert run(_row(stamp=short)).verdict == "stale"
    long_ = _stamp(arrest_date="2026-06-01", last_confirmed_on_roster="2026-09-20")
    assert run(_row(stamp=long_)).evidence["reason"] == "possible_transfer_to_prison"
    # no last-seen date: the span to today is the upper bound
    assert run(_row(stamp=_stamp(arrest_date="2026-06-01"))).evidence["reason"] == "possible_transfer_to_prison"


def test_a_long_stay_still_on_the_roster_is_decided_as_before(monkeypatch):
    _seed_history()
    _install(monkeypatch, [[zrec("Testowner, Patrick Allen")] + _fillers(99)])
    res = run(_row(stamp=_stamp(arrest_date="2025-01-01")))
    assert res.verdict == "confirmed"


def test_an_unhealthy_roster_is_still_roster_unhealthy_not_a_transfer(monkeypatch):
    _seed_history()
    _install(monkeypatch, [_fillers(25)])
    res = run(_row(stamp=_stamp(arrest_date="2025-01-01")))
    assert res.evidence["reason"] == "roster_unhealthy"


def test_version_is_v2():
    assert v.VERSION == "v2"
