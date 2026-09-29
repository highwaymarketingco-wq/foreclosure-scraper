"""Sidecar memory of foreclosure-adjacent court cases across runs:
data/foreclosure_docket_history.db.

Dirty Deeds Tier B #37: "Foreclosure docket history per parcel, including
dismissed and terminated cases. Count how many times a lender filed and
failed. This is a schema change, not a new source: today's scrape almost
certainly keeps only the active notice."

INVESTIGATION (2026-09-29) -- what "a case disappeared" can mean here
-----------------------------------------------------------------------
Four scrapers touch this data and each treats a fetch as an independent
snapshot with no run-to-run memory:

  * `counties_nc.nc_ecourts_lis_pendens` queries NC AOC's Tyler-Odyssey
    Judgment Search over a rolling 90-day window and reads a real
    `civilJudgmentStatus` per hit -- but `_hit_to_listing` DISCARDS any hit
    whose status matches cancel/satisf/dismiss/vacat/withdraw/expired/
    released BEFORE it ever becomes a Listing. So the literal ground truth
    ("this lis pendens was Dismissed") is computed every run and then
    thrown away -- confirmed live: of 13,563 board rows from this source
    (2026-09-29 snapshot), 13,558 are status "Active" and the rest are
    unrelated FAM statuses; a dismissed NC case leaves ZERO trace the
    moment its status changes. This is the synthesis's "today's scrape
    almost certainly keeps only the active notice," true by construction.

  * `counties_sc.sc_public_index_lis_pendens` (the CP-Foreclosure-420
    subtype filter -- the actual "SC Public Index" foreclosure source) and
    `counties_sc.sc_public_index` (broader CP+GS sweep) both query by a
    short rolling FILED-date window (60 and 45 days). A case's absence from
    a later run of THESE sources is ambiguous by design: it could mean the
    case was resolved, or it could simply mean the case is now older than
    the window and has aged out while still pending, proceeding normally
    toward judgment/sale -- NOT dismissed. Confirmed live: of 320 (resp.
    4,315) board rows from these two sources, the status vocabulary
    observed is almost entirely "Pending" / "Referred To Master" / None --
    a real "Dismissed" essentially never shows up inside a 45-60 day
    filed-date window because SC dismissals typically take longer than
    that to get entered. So ABSENCE FROM THESE TWO SOURCES ALONE MUST NEVER
    BE READ AS A DISMISSAL -- it is exactly the false-distress-signal risk
    the synthesis item calls out.

  * `national.sc_public_index` sweeps every SC county by last-name prefix
    with NO date filter (the same case keeps reappearing in the same
    alphabetic sweep for as long as it exists in the index, up to the
    site's own per-county result cap) and reads a real `status` field that
    DOES carry live SC Common Pleas disposition text. Confirmed live
    (2026-09-29 board snapshot, 1,625 rows): "Dismissed" appears 272 times,
    alongside "Settled" (573), "Judgment" (120), "Disposed" (30),
    "Satisfied" (9), "Vacated" (1) etc -- a real, directly-reported
    disposition vocabulary, not inferred from anything.

THE SAFE RULE THIS MODULE FOLLOWS
----------------------------------
A case is recorded as dismissed/terminated/withdrawn ONLY when one of the
sources' OWN status text says so (matches `_DISMISS_RE`), never because a
case stopped showing up in a later scrape. This makes the ambiguous
"disappeared" case (aged out of a rolling filed-date window, or proceeding
normally toward a sale) structurally impossible to confuse with a genuine
dismissal: an aged-out case just stops being observed (its row goes stale,
`ever_dismissed` stays whatever it already was, nothing new is asserted).
`repeat_filing_flag` additionally requires TWO OR MORE such directly-observed
terminal cases against the same (state, county, owner) before it will flag
anything, which keeps a single ambiguous or borderline case from ever
producing a "repeat filer" signal on its own.

"Settled" / "Judgment" / "Satisfied" / "Disposed" / "Transferred" /
"Consolidated" are deliberately NOT treated as a failed filing: Judgment
means the lender WON: the opposite of "filed and failed". Settled/Satisfied
usually means the debt got paid or a workout was reached -- a resolution,
not a failure. Only "Dismissed" / "Terminated" / "Withdrawn" (the synthesis
item's own words) are treated as the lender not completing the case.

Coverage note: because `sc_public_index_lis_pendens`'s narrow foreclosure-
subtype filter rarely observes a literal terminal status inside its 60-day
window, most of the real "Dismissed" ground truth for SC will come from
`national.sc_public_index`'s undated sweep -- which only revisits a given
non-Charleston county once every ~22 days (its own day-rotating batch).
Coverage improves automatically as that rotation proceeds; it is not
instant. Charleston and NC (90-day window, every run) refresh every run.

Sits next to data/jail_roster_history.db and data/deed_index.db and follows
the same shape: a plain sqlite3 file, gitignored (see .gitignore `data/` and
`*.db`), rebuilt by the pipeline itself rather than checked in.

KNOWN LIMITATION -- name-indexed, not parcel-indexed. None of these four
sources reliably carry a parcel ID at scrape time (that join happens later,
downstream, via the name->property resolver), so "the same parcel" here
means "the same (state, county, normalized owner/defendant name)". A
multi-debtor case whose defendant list is joined in a different ORDER across
two filings will not match; and two different people who share both a
surname and a county could, in principle, collide. Both are the same
class of approximation the rest of this name-indexed pipeline already
makes (see `enrichment_jail_bookings.py`'s name-only matching), not a new
one introduced here.
"""
from __future__ import annotations

import re
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import structlog

log = structlog.get_logger()

DB_PATH = Path(__file__).resolve().parent.parent.parent / "data" / "foreclosure_docket_history.db"

_SCHEMA = """
CREATE TABLE IF NOT EXISTS cases (
    case_key           TEXT PRIMARY KEY,
    state              TEXT NOT NULL,
    county             TEXT NOT NULL,
    case_number        TEXT NOT NULL,
    owner_key          TEXT NOT NULL,
    owner_name         TEXT,
    plaintiff          TEXT,
    source             TEXT,
    filed_date         TEXT,
    first_seen_at      TEXT NOT NULL,
    last_seen_at       TEXT NOT NULL,
    times_seen         INTEGER NOT NULL DEFAULT 1,
    latest_status      TEXT,
    latest_status_at   TEXT,
    ever_dismissed     INTEGER NOT NULL DEFAULT 0,
    first_dismissed_at TEXT
);
CREATE INDEX IF NOT EXISTS idx_cases_owner ON cases (owner_key);
CREATE INDEX IF NOT EXISTS idx_cases_state_county ON cases (state, county);

CREATE TABLE IF NOT EXISTS case_status_events (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    case_key    TEXT NOT NULL,
    status      TEXT,
    source      TEXT,
    observed_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_events_case ON case_status_events (case_key);
"""

# Only a literal, source-reported "the case did not complete" status counts.
# Deliberately EXCLUDES Settled/Satisfied (debt resolved -- not a failure),
# Judgment (the lender WON), Disposed/Transferred/Consolidated (ambiguous,
# not a stated failure) -- see module docstring.
_DISMISS_RE = re.compile(r"dismiss|terminat|withdraw", re.I)


def _norm(s: Optional[str]) -> str:
    return re.sub(r"[^A-Z]", "", (s or "").upper())


def _norm_case_no(s: Optional[str]) -> str:
    return re.sub(r"[^A-Z0-9]", "", (s or "").upper())


def case_key(state: str, county: str, case_number: str) -> str:
    return "|".join((_norm(state), _norm(county), _norm_case_no(case_number)))


def owner_key(state: str, county: str, owner_name: str) -> str:
    return "|".join((_norm(state), _norm(county), _norm(owner_name)))


def is_dismissal_status(status: Optional[str]) -> bool:
    """True only when the literal status TEXT says the case failed to
    complete. Never call this on "no status text" / "case is absent" -- see
    module docstring on why absence must never be treated as a dismissal."""
    return bool(status) and bool(_DISMISS_RE.search(status))


def connect(path: Path | str | None = None) -> sqlite3.Connection:
    p = Path(path) if path else DB_PATH
    p.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(str(p))
    con.row_factory = sqlite3.Row
    con.executescript(_SCHEMA)
    return con


def observe_case(
    con: sqlite3.Connection,
    *,
    state: str,
    county: str,
    case_number: str,
    owner_name: str,
    status: Optional[str] = None,
    plaintiff: Optional[str] = None,
    filed_date: Optional[str] = None,
    source: str = "",
    now: Optional[datetime] = None,
    commit: bool = True,
) -> Optional[dict]:
    """Upsert one case observation and report what changed.

    Returns None (writes nothing) when state/county/case_number/owner_name
    is missing -- a name-indexed row with no case number or no owner name
    cannot be tracked or matched against anything. `status` is the literal
    text the source reported for THIS fetch (may be None if the source
    doesn't expose one THIS run); it is compared against the previously
    recorded status to decide whether to append a case_status_events row,
    and is source-of-truth for `ever_dismissed` (see `is_dismissal_status`).
    `ever_dismissed` only ever moves True -> stays True: once a source has
    directly reported a terminal status for a case, a later re-observation
    with a different (or missing) status never un-sets it.
    """
    if not (state and county and case_number and owner_name):
        return None
    now = now or datetime.now(timezone.utc)
    now_iso = now.replace(microsecond=0).isoformat()
    ck = case_key(state, county, case_number)
    ok = owner_key(state, county, owner_name)
    dismissed_now = is_dismissal_status(status)

    cur = con.execute("SELECT * FROM cases WHERE case_key=?", (ck,)).fetchone()
    if cur is None:
        con.execute(
            "INSERT INTO cases (case_key, state, county, case_number, owner_key,"
            " owner_name, plaintiff, source, filed_date, first_seen_at, last_seen_at,"
            " times_seen, latest_status, latest_status_at, ever_dismissed,"
            " first_dismissed_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,1,?,?,?,?)",
            (ck, state, county, case_number, ok, owner_name, plaintiff, source,
             filed_date, now_iso, now_iso, status, now_iso if status else None,
             int(dismissed_now), now_iso if dismissed_now else None),
        )
        con.execute(
            "INSERT INTO case_status_events (case_key, status, source, observed_at)"
            " VALUES (?,?,?,?)", (ck, status, source, now_iso),
        )
        if commit:
            con.commit()
        return {"is_new": True, "status_changed": bool(status),
                "ever_dismissed": dismissed_now,
                "first_dismissed_at": now_iso if dismissed_now else None}

    status_changed = (status or None) != (cur["latest_status"] or None)
    ever_dismissed = bool(cur["ever_dismissed"]) or dismissed_now
    first_dismissed_at = cur["first_dismissed_at"] or (now_iso if dismissed_now else None)
    con.execute(
        "UPDATE cases SET last_seen_at=?, times_seen=times_seen+1,"
        " plaintiff=COALESCE(?, plaintiff), source=?, filed_date=COALESCE(filed_date, ?),"
        " latest_status=CASE WHEN ? THEN ? ELSE latest_status END,"
        " latest_status_at=CASE WHEN ? THEN ? ELSE latest_status_at END,"
        " ever_dismissed=?, first_dismissed_at=? WHERE case_key=?",
        (now_iso, plaintiff, source, filed_date,
         int(status_changed), status, int(status_changed), now_iso,
         int(ever_dismissed), first_dismissed_at, ck),
    )
    if status_changed:
        con.execute(
            "INSERT INTO case_status_events (case_key, status, source, observed_at)"
            " VALUES (?,?,?,?)", (ck, status, source, now_iso),
        )
    if commit:
        con.commit()
    return {"is_new": False, "status_changed": status_changed,
            "ever_dismissed": ever_dismissed, "first_dismissed_at": first_dismissed_at}


def repeat_filing_flag(
    con: sqlite3.Connection,
    *,
    state: str,
    county: str,
    owner_name: str,
    exclude_case_number: Optional[str] = None,
    min_dismissed: int = 2,
    limit: int = 5,
) -> Optional[dict]:
    """The Tier B #37 payload: has this owner (in this county) had TWO OR
    MORE directly-observed dismissed/terminated/withdrawn cases -- i.e. has
    a lender filed and failed against them, more than once?

    Returns None when fewer than `min_dismissed` such cases exist (the
    conservative default -- a single dismissal is not "repeat"). Never
    inferred from anything disappearing; every case counted here has a
    literal terminal status text on record (see `observe_case`).
    `exclude_case_number` lets a caller ask "does this owner have a history
    of failed filings ASIDE from the very case I'm looking at right now".
    """
    ok = owner_key(state, county, owner_name)
    rows = con.execute(
        "SELECT case_number, plaintiff, latest_status, first_dismissed_at, source,"
        " filed_date, ever_dismissed FROM cases WHERE owner_key=? ORDER BY first_seen_at",
        (ok,),
    ).fetchall()
    if not rows:
        return None
    excl = _norm_case_no(exclude_case_number) if exclude_case_number else None
    dismissed = [r for r in rows if r["ever_dismissed"]
                 and (excl is None or _norm_case_no(r["case_number"]) != excl)]
    if len(dismissed) < min_dismissed:
        return None
    return {
        "count": len(dismissed),
        "basis": "status_text",  # ground truth is literal source status text,
        # never a case's absence from a later scrape -- see module docstring
        "prior_dismissed_cases": [
            {"case_number": r["case_number"], "plaintiff": r["plaintiff"],
             "status": r["latest_status"], "dismissed_at": r["first_dismissed_at"],
             "source": r["source"], "filed_date": r["filed_date"]}
            for r in dismissed[:limit]
        ],
        "total_filings_against_owner": len(rows),
    }


def stats(con: sqlite3.Connection) -> list[dict]:
    """Per (state, county) coverage summary -- cases tracked, dismissals seen."""
    rows = con.execute(
        "SELECT state, county, COUNT(*) AS total_cases,"
        " SUM(ever_dismissed) AS dismissed_cases, MAX(last_seen_at) AS last_fetch"
        " FROM cases GROUP BY state, county ORDER BY state, county"
    ).fetchall()
    return [dict(r) for r in rows]
