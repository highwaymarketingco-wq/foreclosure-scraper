"""Who is on a county jail roster, and when an absence ends a custody claim: the two rules shared
by the pipeline's stamp and the per-listing verifier.

A pure, neutral module on purpose (the same reason as signal_freshness, its only import): the
pipeline stamp (enrichment_jail_bookings._reevaluate_stamp) and the verifier
(verification/verifiers/jail_booking.py) both read a roster for the same stamp and must reach the
same answer, so the rules live here and neither of them imports the other. No network, no I/O, no
Listing, no board.

SPELLING DRIFT. A person can be on a roster whose first name the vendor later respelled by a
character or two (Henderson, 2026-10-06: the board stamp and the live roster differed by one
inserted letter, and an exact first + last lookup read "absent"). When no roster record has the
stamp's exact name, `spelling_variants` finds the record that is the SAME person under another
spelling: the same LAST name, the same BOOKING date, the same date of birth when both sides carry
one (else the same age), and a first name within `first_name_variant`'s edit distance (2, or 1 for
a name under 5 letters, exact under 3; or the same first letter with one a prefix of the other,
ROB / ROBERT). Nothing else is loosened: a different last name, booking day, date of birth or age
is a different person. Exactly one such record is the person; two are ambiguous and the caller must
not decide (the verifier says unconfirmed, the stamp is left as it was).

LONG STAYS. A county roster cannot tell a release from a transfer to state prison. The stay in this
jail is measured from the booking date to the last time the person was seen on the roster (the
stamp's last_confirmed_on_roster; the caller's `today` bound when the stamp has none, which is an
upper bound). A stay of JAIL_LONG_STAY_DAYS (60) or more that ends in an absence must NOT end the
incarceration claim: `long_stay` returns the stay in days for those, and the caller keeps the claim
(possible_transfer_to_prison). A stay under 60 days, or one with no booking date to measure from, is
not long, so an absence still reads as a release.
"""
from __future__ import annotations

import re
from datetime import date
from typing import Any, Optional

from .signal_freshness import to_date

__all__ = ["JAIL_LONG_STAY_DAYS", "POSSIBLE_TRANSFER", "norm_key", "lev", "first_name_variant",
           "spelling_variants", "variant_candidate", "stay_days", "long_stay"]

#: a stay in the county jail of this many days or more cannot be read as a release when the person
#: is no longer on the roster: the answer is "possible transfer to prison", not "released". The
#: one place the number lives.
JAIL_LONG_STAY_DAYS = 60

#: the reason an absence after a long stay is recorded under (verifier evidence and the stamp's raw)
POSSIBLE_TRANSFER = "possible_transfer_to_prison"


def norm_key(last: str, first: str) -> tuple[str, str]:
    """The (LAST, FIRST) key a roster is indexed by: letters only, upper case."""
    return (re.sub(r"[^A-Z]", "", (last or "").upper()),
            re.sub(r"[^A-Z]", "", (first or "").upper()))


def lev(a: str, b: str) -> int:
    """Levenshtein edit distance."""
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        cur = [i]
        for j, cb in enumerate(b, 1):
            cur.append(min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (ca != cb)))
        prev = cur
    return prev[-1]


def first_name_variant(a: str, b: str) -> Optional[int]:
    """The edit distance between two normalized first names when they can be one person's
    spelling variants, else None: within 2 edits (1 when the shorter is under 5 letters, none
    when it is under 3), or the same first letter with one a prefix of the other (3+ letters)."""
    if not a or not b or a == b:
        return None
    short = min(len(a), len(b))
    if short < 3:
        return None
    d = lev(a, b)
    if d <= (2 if short >= 5 else 1):
        return d
    if a[0] == b[0] and (a.startswith(b) or b.startswith(a)):
        return d
    return None


def _day(v: Any) -> Optional[date]:
    return to_date(v)


def _int(v: Any) -> Optional[int]:
    try:
        return int(str(v).strip())
    except (TypeError, ValueError):
        return None


def spelling_variants(index: Any, jbk: dict, claimed: tuple[str, str]) -> list[dict]:
    """Roster records that are the stamp's person under another spelling of the first name (see
    SPELLING DRIFT in the module docstring), each {record, distance, basis}. `claimed` is the
    stamp's (last, first). Needs the stamp's booking date (arrest_date); compares the date of birth
    (roster_dob) when both sides have one, else the age (roster_age). `index` is a roster index
    keyed by norm_key(last, first), with a `same_name` {key: [records]} attribute when several
    records can share a name (enrichment_jail_bookings.RosterIndex); a plain dict works too."""
    last, first = norm_key(*claimed)
    booked = _day(jbk.get("arrest_date"))
    if booked is None or not last:
        return []
    sdob, sage = _day(jbk.get("roster_dob")), _int(jbk.get("roster_age"))
    groups = getattr(index, "same_name", None) or {k: [v] for k, v in index.items()}
    out = []
    for (rlast, rfirst), recs in groups.items():
        if rlast != last or rfirst == first:
            continue
        dist = first_name_variant(first, rfirst)
        if dist is None:
            continue
        for rec in recs:
            if _day(rec.get("arrest_date")) != booked:
                continue
            rdob = _day(rec.get("dob"))
            if sdob is not None and rdob is not None:
                basis = "dob" if sdob == rdob else None
            else:
                rage = _int(rec.get("age"))
                basis = "age" if (sage is not None and rage is not None and sage == rage) else None
            if basis:
                out.append({"record": rec, "distance": dist, "basis": basis})
    return out


def variant_candidate(variant: dict, claimed: tuple[str, str]) -> dict:
    """The roster record of a `spelling_variants` match, carrying the STAMP's own spelling of the
    first name, so the middle-name rule (which reads the roster's first name against the owner's)
    judges only the middle name."""
    return dict(variant["record"], first=claimed[1])


def stay_days(jbk: dict, today: date) -> Optional[int]:
    """Days from the booking date to the last time the person was seen on the roster (the
    stamp's last_confirmed_on_roster; `today` when it has none: an upper bound), else None when
    the stamp has no booking date."""
    booked = _day(jbk.get("arrest_date"))
    if booked is None:
        return None
    seen = _day(jbk.get("last_confirmed_on_roster")) or today
    return max((seen - booked).days, 0)


def long_stay(jbk: dict, today: date) -> Optional[int]:
    """The stay in days when it is JAIL_LONG_STAY_DAYS or more (an absence after it is a possible
    transfer to state prison, never a release), else None: a short stay, or no booking date to
    measure from."""
    days = stay_days(jbk, today)
    return days if days is not None and days >= JAIL_LONG_STAY_DAYS else None
