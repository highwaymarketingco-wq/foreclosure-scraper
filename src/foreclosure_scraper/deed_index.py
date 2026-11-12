"""Sidecar index of recorded deed instruments: data/deed_index.db.

One row per recorded INSTRUMENT, not per party. Registers of deeds serve one row
per party, so a single trustee's deed arrives as three or four rows (Burke 2025:
166 party rows for 55 documents). The adapter collapses them before anything is
stored, and the primary key is book, page, instrument number and instrument code,
so a re-sweep replaces rows instead of duplicating them.

Why a sidecar and not the board: the board only holds parcels that are already
leads. A county-wide sweep finds people who lost a parcel that was never a lead,
and enrichment_repeat_tax_loss needs exactly those names (finding F5 in
docs/deed_index_scoping_2026-09-20.md). Sizing is about 800 instruments a year
across the 18 core counties, trivial for SQLite. Sits next to data/parcel_cache.db.

LOSER NAMES. loser_names is derived, not served. A trustee's deed lists the
foreclosing law firm as a grantor next to the borrowers, and a commissioner's
deed lists the attorney commissioner next to the delinquent taxpayer, so the
grantor list alone is not the list of people who lost the parcel. derive_loss()
drops firms, entities and officers. refresh_losers() also drops a STANDING
officer: a person who is a grantor on a large share of one county's loss deeds is
a commissioner or trustee attorney, not a repeat loser (a habitual defaulter
cannot reach that share of a whole county).
"""
from __future__ import annotations

import json
import re
import sqlite3
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

import structlog

from .name_normalize import is_entity, normalize_name
from .rod.inst_class import (
    COMMISSIONER_DEED, LOSS_CLASSES, MASTER_DEED, SHERIFF_DEED, TAX_DEED, TRUSTEE_DEED,
)

log = structlog.get_logger()

DB_PATH = Path(__file__).resolve().parent.parent.parent / "data" / "deed_index.db"

_SCHEMA = """
CREATE TABLE IF NOT EXISTS instruments (
    doc_key       TEXT PRIMARY KEY,
    county        TEXT NOT NULL,
    state         TEXT NOT NULL,
    source        TEXT NOT NULL,
    instrument_no TEXT,
    book          TEXT,
    page          TEXT,
    recorded_date TEXT,
    inst_code     TEXT,
    inst_class    TEXT NOT NULL,
    grantors      TEXT NOT NULL DEFAULT '[]',
    grantor_flags TEXT NOT NULL DEFAULT '[]',
    grantees      TEXT NOT NULL DEFAULT '[]',
    excise_stamp  REAL,
    parcel_id     TEXT,
    description   TEXT,
    loss_kind     TEXT NOT NULL DEFAULT 'unknown',
    loser_names   TEXT NOT NULL DEFAULT '[]',
    fetched_at    TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_instruments_class ON instruments (inst_class);
CREATE INDEX IF NOT EXISTS idx_instruments_county ON instruments (state, county);
"""


@dataclass(frozen=True)
class Party:
    """One named party on an instrument, as the vendor served it."""

    name: str            # surname-first as served ("SMITH JOHN A"); a firm is its whole name
    kind: str = ""       # vendor party class: "I" individual, "F" firm; "" when not served
    suffix: str = ""     # vendor name suffix or role ("TR" = trustee, "JR", ...)


@dataclass
class DeedInstrument:
    county: str
    state: str
    source: str                       # cchs_classic | cchs_lrsearch | acclaim | aumentum | logan | assessor_open_data
    inst_code: str                    # vendor code as served (TR/D, COM/D, ...)
    inst_class: str                   # canonical, see rod/inst_class.py
    recorded_date: str | None = None  # ISO date
    book: str | None = None
    page: str | None = None
    instrument_no: str | None = None
    grantors: list[str] = field(default_factory=list)
    grantor_parties: list[Party] = field(default_factory=list)
    grantees: list[str] = field(default_factory=list)
    excise_stamp: float | None = None   # NC: consideration is at most stamp x 500, never a comp when 0
    parcel_id: str | None = None        # vendor parcel key or TMS when served
    description: str | None = None      # Burke puts the foreclosed deed-of-trust book/page here
    loss_kind: str = "unknown"          # mortgage_foreclosure | tax_foreclosure | tax_deed | judicial_sale | unknown
    loser_names: list[str] = field(default_factory=list)
    fetched_at: str = ""

    @property
    def doc_key(self) -> str:
        return make_doc_key(self.county, self.state, self.book, self.page,
                            self.instrument_no, self.inst_code)


def make_doc_key(county, state, book, page, instrument_no, inst_code) -> str:
    return "|".join(str(x or "") for x in (county, state, book, page, instrument_no, inst_code))


# --------------------------------------------------------------------------- #
# Loser derivation                                                            #
# --------------------------------------------------------------------------- #

# A trustee-firm or attorney party: LLC/PLLC/LLP/PC, LAW, ATTORNEY, TRUSTEE,
# COMMISSIONER, or a trailing "P.A." Only the form with a period counts: two
# middle initials ("DOE JOHN P A") are a person, and a bare "PA" token is already
# an entity marker in name_normalize.
_FIRM_RE = re.compile(
    r"\b(?:LLC|PLLC|LLP|PC|LAW|ATTORNEYS?|ATTY|TRUSTEES?|COMMISSIONERS?|SUBSTITUTE)\b"
    r"|(?:^|[\s,])P\.\s?A\.?\s*$", re.I)
# Officers of the sale itself. COUNTY catches "BURKE COUNTY SHERIFF" and taxing units.
_OFFICER_RE = re.compile(
    r"\b(?:SHERIFF|TREASURER|TAX COLLECTOR|CLERK|MASTER IN EQUITY|COUNTY)\b", re.I)
_OFFICER_SUFFIXES = {"TR", "TRUSTEE", "SUB TR", "COMM", "COMMISSIONER", "ATTY", "SHERIFF"}
# "1347/484" or "1347-484": the book and page of the deed of trust being foreclosed.
_XREF_RE = re.compile(r"\b\d{2,5}\s*[/-]\s*\d{1,5}\b")


def _is_officer(p: Party) -> bool:
    """A firm, attorney or sale officer, by name or by the vendor's role suffix."""
    return bool(_FIRM_RE.search(p.name) or _OFFICER_RE.search(p.name)
                or p.suffix.strip().upper() in _OFFICER_SUFFIXES)


def _is_person(p: Party) -> bool:
    """A natural person who could have lost the parcel. A vendor firm flag, an
    entity marker (LLC, TRUST, BANK, ...) or an officer marker all rule it out."""
    if not p.name.strip() or p.kind.strip().upper() == "F":
        return False
    return not is_entity(p.name) and not _is_officer(p)


def derive_loss(inst_class: str, grantors: list[Party], description: str = "",
                standing_officers: frozenset[str] = frozenset()) -> tuple[str, list[str]]:
    """(loss_kind, loser_names) for one instrument.

    Trustee's deed: a mortgage foreclosure when a firm or attorney grantor sits
    beside a natural person, or the description holds a deed-of-trust book/page
    cross-reference. A trustee's deed whose only grantor is a trust is not a loss.
    Commissioner's, sheriff's and master's deeds: the losers are the natural
    persons who are not the officer. Tax deed: same rule, loss_kind tax_deed.
    Returns ("unknown", []) when the instrument cannot be read as a loss.
    """
    if inst_class not in LOSS_CLASSES:
        return "unknown", []
    persons = [p for p in grantors if _is_person(p)]
    losers = [p.name for p in persons if normalize_name(p.name) not in standing_officers]
    if not losers:
        return "unknown", []
    desc = description or ""
    if inst_class == TRUSTEE_DEED:
        officer_seen = (any(_is_officer(p) for p in grantors)
                        or len(losers) < len(persons))
        if officer_seen or _XREF_RE.search(desc):
            return "mortgage_foreclosure", losers
        return "unknown", []
    if inst_class == TAX_DEED:
        return "tax_deed", losers
    if inst_class == COMMISSIONER_DEED:
        return ("tax_foreclosure" if re.search(r"\bTAX", desc, re.I) else "judicial_sale"), losers
    if inst_class in (SHERIFF_DEED, MASTER_DEED):
        return "judicial_sale", losers
    return "unknown", []


# --------------------------------------------------------------------------- #
# SQLite                                                                      #
# --------------------------------------------------------------------------- #

def connect(path: Path | str | None = None) -> sqlite3.Connection:
    p = Path(path) if path else DB_PATH
    p.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(str(p))
    con.row_factory = sqlite3.Row
    con.executescript(_SCHEMA)
    return con


def upsert(con: sqlite3.Connection, instruments: list[DeedInstrument]) -> int:
    """Insert or replace by doc_key. Returns the number of rows written."""
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    rows = [(
        i.doc_key, i.county, i.state, i.source, i.instrument_no, i.book, i.page,
        i.recorded_date, i.inst_code, i.inst_class,
        json.dumps(i.grantors), json.dumps([[p.kind, p.suffix] for p in i.grantor_parties]),
        json.dumps(i.grantees), i.excise_stamp, i.parcel_id, i.description,
        i.loss_kind, json.dumps(i.loser_names), i.fetched_at or now,
    ) for i in instruments]
    con.executemany(
        "INSERT OR REPLACE INTO instruments (doc_key, county, state, source, instrument_no,"
        " book, page, recorded_date, inst_code, inst_class, grantors, grantor_flags, grantees,"
        " excise_stamp, parcel_id, description, loss_kind, loser_names, fetched_at)"
        " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)", rows)
    con.commit()
    return len(rows)


def _parties(row) -> list[Party]:
    names = json.loads(row["grantors"] or "[]")
    flags = json.loads(row["grantor_flags"] or "[]")
    out = []
    for n, name in enumerate(names):
        kind, suffix = (flags[n] if n < len(flags) else ["", ""])
        out.append(Party(name, kind or "", suffix or ""))
    return out


def standing_officers(name_counts: dict[str, int], total_docs: int,
                      min_docs: int = 8, min_share: float = 0.15) -> frozenset[str]:
    """Names that are a grantor on at least min_docs of a county's loss deeds AND
    at least min_share of them. The share test is what protects a genuine repeat
    loser: to reach 15 percent of a county's deeds a person would have to lose a
    parcel every few weeks for years."""
    if total_docs <= 0:
        return frozenset()
    return frozenset(n for n, c in name_counts.items()
                     if c >= min_docs and c / total_docs >= min_share)


def refresh_losers(con: sqlite3.Connection, min_docs: int = 8, min_share: float = 0.15) -> dict:
    """Recompute loss_kind and loser_names for every loss row, per county, with
    that county's standing officers removed. Idempotent. Run after each sweep
    (a 30-day refresh alone is too small a sample to spot an officer)."""
    stats = {"rows": 0, "updated": 0, "officers": {}}
    placeholders = ",".join("?" for _ in LOSS_CLASSES)
    groups = con.execute(
        f"SELECT DISTINCT state, county FROM instruments WHERE inst_class IN ({placeholders})",
        sorted(LOSS_CLASSES)).fetchall()
    for g in groups:
        rows = con.execute(
            f"SELECT * FROM instruments WHERE state=? AND county=? AND inst_class IN ({placeholders})",
            [g["state"], g["county"], *sorted(LOSS_CLASSES)]).fetchall()
        counts: dict[str, int] = {}
        for r in rows:
            for nid in {normalize_name(p.name) for p in _parties(r) if _is_person(p)}:
                counts[nid] = counts.get(nid, 0) + 1
        officers = standing_officers(counts, len(rows), min_docs, min_share)
        if officers:
            stats["officers"][f"{g['county']}, {g['state']}"] = sorted(officers)
        for r in rows:
            stats["rows"] += 1
            kind, losers = derive_loss(r["inst_class"], _parties(r), r["description"] or "", officers)
            if kind != r["loss_kind"] or json.dumps(losers) != r["loser_names"]:
                con.execute("UPDATE instruments SET loss_kind=?, loser_names=? WHERE doc_key=?",
                            (kind, json.dumps(losers), r["doc_key"]))
                stats["updated"] += 1
    con.commit()
    return stats


def load_loss_rows(path: Path | str | None = None) -> list[dict]:
    """Loss instruments that name at least one loser, as plain dicts. [] when the
    sidecar does not exist yet, so the enricher runs unchanged before the first
    sweep. Read-only."""
    p = Path(path) if path else DB_PATH
    if not p.exists():
        return []
    try:
        con = sqlite3.connect(f"file:{p}?mode=ro", uri=True)
    except sqlite3.Error as exc:
        log.warning("deed_index.open_failed", path=str(p), error=str(exc)[:200])
        return []
    con.row_factory = sqlite3.Row
    try:
        placeholders = ",".join("?" for _ in LOSS_CLASSES)
        rows = con.execute(
            f"SELECT * FROM instruments WHERE inst_class IN ({placeholders}) AND loser_names != '[]'",
            sorted(LOSS_CLASSES)).fetchall()
    except sqlite3.Error as exc:
        log.warning("deed_index.read_failed", path=str(p), error=str(exc)[:200])
        return []
    finally:
        con.close()
    out = []
    for r in rows:
        d = dict(r)
        d["loser_names"] = json.loads(d["loser_names"] or "[]")
        d["grantors"] = json.loads(d["grantors"] or "[]")
        d["grantees"] = json.loads(d["grantees"] or "[]")
        d.pop("grantor_flags", None)
        out.append(d)
    return out


def coverage(con: sqlite3.Connection) -> list[dict]:
    """Per county: instruments, loss instruments, how many name a loser, date span.
    The first sweep's index start year per county falls out of min_date."""
    placeholders = ",".join("?" for _ in LOSS_CLASSES)
    rows = con.execute(
        f"SELECT state, county, COUNT(*) AS docs,"
        f" SUM(CASE WHEN inst_class IN ({placeholders}) THEN 1 ELSE 0 END) AS loss_docs,"
        f" SUM(CASE WHEN loser_names != '[]' THEN 1 ELSE 0 END) AS with_losers,"
        f" MIN(recorded_date) AS min_date, MAX(recorded_date) AS max_date"
        f" FROM instruments GROUP BY state, county ORDER BY state, county",
        sorted(LOSS_CLASSES)).fetchall()
    return [dict(r) for r in rows]
