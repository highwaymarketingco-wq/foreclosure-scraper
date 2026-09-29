"""Sidecar memory of jail-roster bookings across runs: data/jail_roster_history.db.

Dirty Deeds Tier B #36: "rosters are wired; what is missing is a standing
re-query." `enrichment_jail_bookings.py` already fetches every covered county's
current in-custody roster on every pipeline run, but it treats each fetch as an
independent snapshot -- it never remembers what it saw last time. That means two
things the synthesis calls out are both structurally impossible today:

  1. "Start the clock at detection." Approved-contact registration at a jail or
     prison takes 6-8 weeks, so an operator needs to know WHEN a booking was
     first observed, not just that it currently exists. `match_rosters` sets
     raw['jail_booking'] once and never revisits the listing, so there has never
     been a durable "first seen" timestamp independent of when a particular
     lead happened to get matched.
  2. Cross-county re-identification. A person can drop off one county's roster
     and turn up on a DIFFERENT county's roster later (the synthesis's ep 069
     fugitive-heir story). The existing match only checks a listing's OWN
     property county against that county's roster, so it cannot even in
     principle notice a booking in a different county.

This module is the persistence layer that makes both possible: one row per
(state, county, normalized last, normalized first) ever observed on a covered
roster, with a first_seen_at that never moves once set and a last_seen_at /
times_seen / currently_listed that update on every fetch. `diff_and_record` is
the only write path and returns, per name, whether THIS fetch was the first time
that name appeared under that county -- the "is_new" flag
`enrichment_jail_bookings` needs to flag a distinct, actionable event instead of
silently re-confirming a stale match forever.

SILENT-SUCCESS GUARD (see CLAUDE.md): a vendor fetcher in this codebase returns
an empty list both when a roster is genuinely empty AND when the fetch quietly
failed (timeout, block, malformed response) -- the two are indistinguishable at
that layer. If this module inferred "nobody left on the roster this fetch =
everybody was released," a single flaky fetch would falsely mark an entire
county's roster as departed. So `diff_and_record` only demotes `currently_listed`
rows when the incoming batch is non-empty; an empty batch updates nothing and is
silently ignored by design (the caller's own logging already covers the fetch
failure).

Sits next to data/deed_index.db and data/sc_parcel_mailing.db and follows the
same shape: a plain sqlite3 file, gitignored (see .gitignore `data/` and `*.db`),
rebuilt by the pipeline itself rather than checked in.
"""
from __future__ import annotations

import re
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable, Optional

import structlog

log = structlog.get_logger()

DB_PATH = Path(__file__).resolve().parent.parent.parent / "data" / "jail_roster_history.db"

_SCHEMA = """
CREATE TABLE IF NOT EXISTS bookings (
    booking_key      TEXT PRIMARY KEY,
    state             TEXT NOT NULL,
    county            TEXT NOT NULL,
    vendor            TEXT NOT NULL,
    last_name         TEXT NOT NULL,
    first_name        TEXT NOT NULL,
    first_seen_at     TEXT NOT NULL,
    last_seen_at      TEXT NOT NULL,
    times_seen        INTEGER NOT NULL DEFAULT 1,
    last_arrest_date  TEXT,
    last_charge       TEXT,
    last_dob          TEXT,
    currently_listed  INTEGER NOT NULL DEFAULT 1
);
CREATE INDEX IF NOT EXISTS idx_bookings_name ON bookings (state, last_name, first_name);
CREATE INDEX IF NOT EXISTS idx_bookings_county ON bookings (state, county);
"""


def _norm(s: str) -> str:
    return re.sub(r"[^A-Z]", "", (s or "").upper())


def booking_key(state: str, county: str, last: str, first: str) -> str:
    return "|".join((_norm(state), _norm(county), _norm(last), _norm(first)))


def connect(path: Path | str | None = None) -> sqlite3.Connection:
    p = Path(path) if path else DB_PATH
    p.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(str(p))
    con.row_factory = sqlite3.Row
    con.executescript(_SCHEMA)
    return con


def diff_and_record(con: sqlite3.Connection, state: str, county: str, vendor: str,
                    records: Iterable[dict], now: Optional[datetime] = None,
                    commit: bool = True,
                    ) -> dict[tuple[str, str], dict]:
    """Upsert this fetch's roster rows and report which names are new.

    `records` is the list of dicts `_fetch_*` returns (each needs at least
    "last" and "first"; "arrest_date", "charge", "dob" are carried through if
    present). Returns {(LAST, FIRST): {"is_new", "first_seen_at",
    "last_seen_at", "times_seen"}} keyed by the SAME normalized (last, first)
    pair `enrichment_jail_bookings._norm_key` produces, so callers can just do
    `meta.get(_norm_key(rec["last"], rec["first"]))`.

    An empty `records` writes nothing and returns {} -- see module docstring
    on why an empty fetch must never be read as "the roster emptied out."

    `commit` mirrors `foreclosure_docket_history.observe_case`'s parameter of
    the same name (2026-09-29, same fix class): when False, every INSERT/
    UPDATE below still runs against `con`, so the returned meta (is_new /
    first_seen_at / times_seen) is exactly as accurate as a real call -- a
    dry run can still compute and report what WOULD be new -- but the
    transaction is never committed here. A caller doing a genuine dry run
    passes commit=False and then closes `con` without ever calling
    con.commit() itself; sqlite3 discards an uncommitted transaction on
    close, so nothing reaches disk (verified: this is NOT "commit on close").
    This fixes the 2026-09-29 bug where `run_pending_signal_enrichers.py
    --dry-run` silently persisted this diff for real, so a REAL run shortly
    after saw `is_new=False` for names its own dry run had just "seen" --
    590 genuine jail_booking_new detections were lost this way in one run.
    See `enrichment_jail_bookings._load_roster`'s `dry_run` parameter for the
    caller side.
    """
    now = now or datetime.now(timezone.utc)
    now_iso = now.replace(microsecond=0).isoformat()
    meta: dict[tuple[str, str], dict] = {}
    seen_keys: list[str] = []

    for rec in records:
        last, first = _norm(rec.get("last") or ""), _norm(rec.get("first") or "")
        if not last or not first:
            continue
        key = booking_key(state, county, last, first)
        seen_keys.append(key)
        cur = con.execute(
            "SELECT first_seen_at, times_seen FROM bookings WHERE booking_key=?",
            (key,)).fetchone()
        if cur is None:
            con.execute(
                "INSERT INTO bookings (booking_key, state, county, vendor, last_name,"
                " first_name, first_seen_at, last_seen_at, times_seen, last_arrest_date,"
                " last_charge, last_dob, currently_listed)"
                " VALUES (?,?,?,?,?,?,?,?,1,?,?,?,1)",
                (key, state, county, vendor, last, first, now_iso, now_iso,
                 rec.get("arrest_date"), rec.get("charge"), rec.get("dob")))
            meta[(last, first)] = {"is_new": True, "first_seen_at": now_iso,
                                   "last_seen_at": now_iso, "times_seen": 1}
        else:
            times_seen = int(cur["times_seen"]) + 1
            con.execute(
                "UPDATE bookings SET last_seen_at=?, times_seen=?, vendor=?,"
                " last_arrest_date=?, last_charge=?, last_dob=?, currently_listed=1"
                " WHERE booking_key=?",
                (now_iso, times_seen, vendor, rec.get("arrest_date"), rec.get("charge"),
                 rec.get("dob"), key))
            meta[(last, first)] = {"is_new": False, "first_seen_at": cur["first_seen_at"],
                                   "last_seen_at": now_iso, "times_seen": times_seen}

    if seen_keys:
        # Demote anyone previously on this county's roster who is absent from a
        # REAL (non-empty) fetch -- they were released or transferred. Guarded
        # by `if seen_keys` above: never runs off an empty/failed fetch.
        qmarks = ",".join("?" * len(seen_keys))
        con.execute(
            f"UPDATE bookings SET currently_listed=0 WHERE state=? AND county=? AND"
            f" currently_listed=1 AND booking_key NOT IN ({qmarks})",
            (state, county, *seen_keys))
        if commit:
            con.commit()
    log.info("jail_history.diff", state=state, county=county, vendor=vendor,
             fetched=len(seen_keys), new=sum(1 for m in meta.values() if m["is_new"]))
    return meta


def stats(con: sqlite3.Connection) -> list[dict]:
    """Per (state, county) coverage summary -- rows, currently listed, newest fetch."""
    rows = con.execute(
        "SELECT state, county, COUNT(*) AS total,"
        " SUM(currently_listed) AS in_custody, MAX(last_seen_at) AS last_fetch"
        " FROM bookings GROUP BY state, county ORDER BY state, county").fetchall()
    return [dict(r) for r in rows]
