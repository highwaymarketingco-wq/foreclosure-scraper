"""DNC (Do Not Call) scrub of every phone on the board: the national registry and the company's own list.

Every phone surfaced by the voter_phone, county_phone, skip_trace, free_phones or sc_voter_xref
enrichers is tagged needs_dnc_scrub=True. This module checks each one against local list files
the operator puts in data/ (the folder is git-ignored; nothing here downloads, logs in or reads an
account):

    data/dnc_registry.csv      the national registry (operator downloads it from the federal
                               registry's seller site); one number per line, 10 digits, or the
                               download's "area code, number" two-column form; a third column
                               "D" (a deletion in a change file) is skipped. Files in the folder
                               data/dnc_registry/ (*.csv, *.txt) are read too, so a per-area-code
                               download can be dropped in as it comes.
    data/internal_dnc.csv      OPTIONAL: the company's own do-not-call list (every 10-digit cell of
                               every row counts). Read on every scrub: a request never waits 31 days.

STATUSES (raw['dnc_scrub'] = [{phone, dnc_status, dnc_registered, internal_dnc, registry_as_of,
scrubbed_at, block_reason?}])
    clear              not on the registry (read in full, as of registry_as_of) and not on the
                       company list; good for RESCRUB_DAYS (31) from scrubbed_at, then unverified
    on_registry        on the national registry
    on_internal_dnc    on the company's own list (takes precedence over the registry answer)
    unverified         no registry file, a registry read cut short or too small to be one, or a
                       clear result older than 31 days: never dial on it
    do_not_dial / not_owner_contact   a phone that must not be dialed as the owner's number
                       whatever the lists say (see below); block_reason says why
"registered" (the name before 2026-10-09) is read as on_registry and rewritten on the next scrub.

RE-SCRUB RULE (16 CFR 310.4(b)(3)(iv): a seller calls only numbers checked against the registry
within the previous 31 days)
    A phone gets a fresh registry answer when it has none, when its answer is unverified and a
    registry is now readable, when its scrub is older than RESCRUB_DAYS, or when the registry on
    disk is not the one it was scrubbed against (registry_as_of). Otherwise the entry is left
    exactly as it is: a second scrub with the same files changes nothing (idempotent).

COST
    No network. The registry is STREAMED, never loaded: the board's phones (about 40K distinct) are
    the set held in memory, and each registry line is looked up in it, so a registry of tens of
    millions of numbers costs its read time (about 1 s per million lines), not gigabytes. The read
    stops at a deadline (DNC_SCRUB_MAX_SECONDS, default 600 s): numbers found so far are
    on_registry, every other wanted phone stays unverified (a partial read never proves clear).
    A registry file with fewer than MIN_REGISTRY_NUMBERS numbers is treated as damaged (unverified).

PHONES THAT ARE NEVER SCRUBBED AS DIALABLE (see enrichment_sc_phone)
    A phone that must not be dialed gets a dnc_scrub entry with dnc_status "do_not_dial" (and a
    block_reason), never "clear": do_not_dial True on the phone, an NC-voter-xref phone whose
    identity is not corroborated, a people-search phone, everything in raw.free_phones. An agent,
    attorney or trustee phone gets "not_owner_contact". A scrub result from before a phone was
    gated is downgraded on the next run, and a phone whose block is later lifted is re-scrubbed.
    The lane rules themselves (role "agent", do_not_dial on the walled people-search lane) are
    stamped here too, so a phone written by an enricher that predates the gate is still tagged.
"""
from __future__ import annotations

import os
import re
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable, Iterator, Optional

import structlog

from .enrichment_sc_phone import (
    WALLED_REASON,
    flag_lane_phones,
    owner_phone_block_reason,
)
from .models import Listing

log = structlog.get_logger()

_DATA = Path(__file__).resolve().parent.parent.parent / "data"
_DNC_PATH = _DATA / "dnc_registry.csv"
_INTERNAL_PATH = _DATA / "internal_dnc.csv"
#: a preset registry (tests, or a caller that already holds the numbers); None = read the files
_DNC_SET: set[str] | None = None
#: a preset company list; None = read _INTERNAL_PATH
_INTERNAL_SET: set[str] | None = None

RESCRUB_DAYS = 31
MIN_REGISTRY_NUMBERS = int(os.environ.get("DNC_MIN_REGISTRY_NUMBERS", "1000") or 1000)
DEFAULT_MAX_SECONDS = float(os.environ.get("DNC_SCRUB_MAX_SECONDS", "600") or 600)

CLEAR, ON_REGISTRY, ON_INTERNAL, UNVERIFIED = "clear", "on_registry", "on_internal_dnc", "unverified"
BLOCKED = ("do_not_dial", "not_owner_contact")
#: every status that keeps a phone from being dialed (call_ready reads this)
NOT_DIALABLE = frozenset({ON_REGISTRY, ON_INTERNAL, "registered", *BLOCKED})
_LEGACY = {"registered": ON_REGISTRY}


def _normalize_phone(phone: str | None) -> str | None:
    """Extract 10-digit phone (strip country code 1, non-digits)."""
    if not phone:
        return None
    digits = re.sub(r"\D", "", str(phone))
    if len(digits) == 11 and digits.startswith("1"):
        digits = digits[1:]
    if len(digits) == 10:
        return digits
    return None


def _load_dnc() -> set[str] | None:
    """The preset registry numbers, or None (the files are streamed by enrich_dnc_scrub, never
    loaded whole). Kept for callers that only ask whether numbers are held in memory."""
    return _DNC_SET


# ------------------------------------------------------------------------------- list files
def registry_files() -> list[Path]:
    """The national-registry files on disk: data/dnc_registry.csv and data/dnc_registry/*.{csv,txt}."""
    out = []
    if _DNC_PATH.is_file():
        out.append(_DNC_PATH)
    d = _DNC_PATH.with_suffix("")
    if d.is_dir():
        out.extend(sorted(p for p in d.iterdir() if p.is_file() and p.suffix.lower() in (".csv", ".txt")))
    return out


def _as_of(paths: list[Path]) -> Optional[str]:
    if not paths:
        return None
    m = max(p.stat().st_mtime for p in paths)
    return datetime.fromtimestamp(m, tz=timezone.utc).date().isoformat()


_SPLIT = re.compile(r"[,\t;|]")


def numbers_in_line(line: str) -> list[str]:
    """The 10-digit numbers one list line names: every cell that is a phone, or the registry
    download's "area code, number" pair. A change-file deletion (a cell that is just D) names none."""
    s = line.strip()
    if not s:
        return []
    if len(s) == 10 and s.isdigit():
        return [s]
    if len(s) == 11 and s[3] == "," and s[:3].isdigit() and s[4:].isdigit():
        return [s[:3] + s[4:]]                     # the registry download's "area code,number" line
    cells =[c.strip().strip('"') for c in _SPLIT.split(s)]
    if any(c.upper() == "D" for c in cells[2:]):
        return []
    out = [p for p in (_normalize_phone(c) for c in cells) if p]
    if out:
        return out
    digits = [re.sub(r"\D", "", c) for c in cells]
    for a, b in zip(digits, digits[1:]):
        if len(a) == 3 and len(b) == 7:
            return [a + b]
    return []


def stream_hits(paths: Iterable[Path], wanted: set[str], deadline: float) -> tuple[set[str], int, bool]:
    """(numbers of `wanted` the files list, numbers read, read to the end before the deadline)."""
    hits: set[str] = set()
    n = 0
    for p in paths:
        with open(p, "r", encoding="utf-8", errors="replace") as f:
            for i, line in enumerate(f):
                if (i & 0xFFFF) == 0 and time.monotonic() > deadline:
                    return hits, n, False
                for num in numbers_in_line(line):
                    n += 1
                    if num in wanted:
                        hits.add(num)
    return hits, n, True


# ------------------------------------------------------------------------------- phones on a row
def _get_phone_records(li: Listing) -> list[tuple[str, str | None]]:
    """Every phone on a listing as (10 digits, block reason or None).

    A reason means the phone must not be dialed as the owner's number (do_not_dial, an
    uncorroborated NC-voter-xref match, a people-search phone, an agent). Sources: owner_phone
    (voter_phone, surfaced contacts, county phones, liensnc), skip_trace, free_phones and
    sc_voter_xref. A number listed twice keeps the unblocked status if any source clears it.
    """
    if not isinstance(li.raw, dict):
        li.raw = {}
    raw = li.raw
    found: dict[str, str | None] = {}

    def _add(phone, reason: str | None) -> None:
        ph = _normalize_phone(phone)
        if not ph:
            return
        if ph not in found or (found[ph] is not None and reason is None):
            found[ph] = reason

    # voter_phone enricher: raw['owner_phone']['phone']
    op = raw.get("owner_phone")
    if isinstance(op, dict) and op.get("phone"):
        _add(op["phone"], owner_phone_block_reason(op))
    # skip_trace enricher: raw['skip_trace']['phone_numbers'] (list)
    st = raw.get("skip_trace")
    if isinstance(st, dict):
        for p in st.get("phone_numbers") or []:
            _add(p, None)
    # free_phones enricher: raw['free_phones'] (list of dicts with 'phone'). People-search lane: walled.
    fp = raw.get("free_phones")
    if isinstance(fp, list):
        for entry in fp:
            if isinstance(entry, dict) and entry.get("phone"):
                _add(entry["phone"], WALLED_REASON)
    # sc_voter_xref enricher: raw['sc_voter_xref']['phone'], always an NC-voter xref phone
    sx = raw.get("sc_voter_xref")
    if isinstance(sx, dict) and sx.get("phone"):
        _add(sx["phone"], owner_phone_block_reason({**sx, "source": "sc_voter_xref"}))
    return list(found.items())


def _get_phones(li: Listing) -> list[str]:
    """The phones on a listing that may be scrubbed as dialable (blocked ones excluded)."""
    return [ph for ph, why in _get_phone_records(li) if why is None]


def _blocked_status(reason: str) -> str:
    return "not_owner_contact" if reason == "agent_contact" else "do_not_dial"


# ------------------------------------------------------------------------------- statuses
def _age_days(iso: object, now: datetime) -> Optional[float]:
    try:
        t = datetime.fromisoformat(str(iso).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    if t.tzinfo is None:
        t = t.replace(tzinfo=timezone.utc)
    return (now - t).total_seconds() / 86400.0


def derive_status(entry: dict, now: datetime) -> str:
    """The dialability status an unblocked entry's facts give today."""
    if entry.get("internal_dnc") is True:
        return ON_INTERNAL
    reg = entry.get("dnc_registered")
    if reg is True:
        return ON_REGISTRY
    if reg is False:
        age = _age_days(entry.get("scrubbed_at"), now)
        if age is not None and age <= RESCRUB_DAYS:
            return CLEAR
    return UNVERIFIED


def status_expired(entry: dict, now: datetime) -> bool:
    """A registry answer older than RESCRUB_DAYS (or with no date) no longer counts."""
    age = _age_days(entry.get("scrubbed_at"), now)
    return age is None or age > RESCRUB_DAYS


def _needs_registry(entry: Optional[dict], registry_readable: bool, as_of: Optional[str],
                    now: datetime) -> bool:
    if entry is None or entry.get("dnc_status") in BLOCKED:
        return True
    if entry.get("dnc_registered") is None:
        return registry_readable
    if status_expired(entry, now):
        return True
    return registry_readable and entry.get("registry_as_of") != as_of


def enrich_dnc_scrub(listings, *, now: Optional[datetime] = None,
                     max_seconds: Optional[float] = None) -> dict:
    """Scrub every phone on `listings` against the registry and the company list (see the module
    docstring). Writes li.raw['dnc_scrub']; returns counts. No network."""
    t0 = time.monotonic()
    now = now or datetime.now(timezone.utc)
    stamp = now.isoformat()
    budget = DEFAULT_MAX_SECONDS if max_seconds is None else float(max_seconds)
    deadline = t0 + budget
    listings = list(listings)
    stats = {"total_listings": len(listings), "listings_with_phone": 0, "scrubbed": 0, "phones": 0,
             "registered": 0, "on_registry": 0, "on_internal_dnc": 0, "clear": 0, "unverified": 0,
             "blocked": 0, "rescrubbed": 0, "kept": 0, "registry_files": 0, "registry_numbers": 0,
             "registry_complete": False, "internal_list": False, "internal_numbers": 0}

    # Lane rules first (role agent, people-search do_not_dial) so the block reasons see them.
    lane = flag_lane_phones(listings, apply=True)
    stats["agent_tagged"] = lane["agent_tagged"]
    stats["walled_flagged"] = lane["walled_flagged"] + lane["free_phones_flagged"]

    files = [] if _DNC_SET is not None else registry_files()
    as_of = None if _DNC_SET is not None else _as_of(files)
    readable = _DNC_SET is not None or bool(files)
    stats["registry_files"] = len(files)

    # pass 1: the phones that need a registry answer, and every dialable phone (company list)
    want_reg: set[str] = set()
    dialable: set[str] = set()
    for li in listings:
        raw = li.raw if isinstance(li.raw, dict) else None
        if not raw:
            continue
        recs = _get_phone_records(li)
        if not recs:
            continue
        have = {}
        for e in raw.get("dnc_scrub") or [] if isinstance(raw.get("dnc_scrub"), list) else []:
            if isinstance(e, dict) and _normalize_phone(e.get("phone")):
                have[_normalize_phone(e.get("phone"))] = e
        for ph, why in recs:
            if why:
                continue
            dialable.add(ph)
            if _needs_registry(have.get(ph), readable, as_of, now):
                want_reg.add(ph)

    # the lists
    reg_hits: set[str] = set()
    reg_ok = False
    if _DNC_SET is not None:
        reg_hits, reg_ok = want_reg & _DNC_SET, True
        stats["registry_numbers"] = len(_DNC_SET)
    elif files and want_reg:
        reg_hits, n, complete = stream_hits(files, want_reg, deadline)
        stats["registry_numbers"] = n
        reg_ok = complete and n >= MIN_REGISTRY_NUMBERS
        if not complete:
            log.warning("dnc.registry_read_cut_short", numbers=n, budget_s=budget)
        elif n < MIN_REGISTRY_NUMBERS:
            log.warning("dnc.registry_too_small", numbers=n, minimum=MIN_REGISTRY_NUMBERS)
    elif files:
        reg_ok = True               # nothing wanted an answer: every entry is current
    stats["registry_complete"] = bool(reg_ok)

    internal: Optional[set[str]] = None
    if _INTERNAL_SET is not None:
        internal = dialable & _INTERNAL_SET
        stats["internal_list"] = True
    elif _INTERNAL_PATH.is_file():
        internal, n, _ = stream_hits([_INTERNAL_PATH], dialable, float("inf"))
        stats["internal_list"], stats["internal_numbers"] = True, n

    # pass 2: apply
    for li in listings:
        raw = li.raw if isinstance(li.raw, dict) else None
        if not raw:
            continue
        recs = _get_phone_records(li)
        existing = raw.get("dnc_scrub")
        if not recs:
            if existing is not None:
                raw.pop("dnc_scrub", None)        # the phones are gone: so is their scrub
            continue
        stats["listings_with_phone"] += 1
        have: dict[str, dict] = {}
        for e in existing if isinstance(existing, list) else []:
            if isinstance(e, dict):
                d = _normalize_phone(e.get("phone"))
                if d and d not in have:
                    have[d] = e
        results: list[dict] = []
        for ph, why in recs:
            stats["phones"] += 1
            entry = have.get(ph)
            if why:
                status = _blocked_status(why)
                stats["blocked"] += 1
                if entry is None:
                    entry = {"phone": ph, "dnc_registered": None}
                if entry.get("dnc_status") != status or entry.get("block_reason") != why:
                    entry.update({"dnc_status": status, "block_reason": why, "scrubbed_at": stamp})
                results.append(entry)
                continue
            if entry is None or entry.get("dnc_status") in BLOCKED:
                entry = {"phone": ph, "dnc_registered": None}     # a lifted block is scrubbed afresh
            if ph in want_reg:
                if ph in reg_hits:
                    entry.update(dnc_registered=True, registry_as_of=as_of, scrubbed_at=stamp)
                    stats["rescrubbed"] += 1
                elif reg_ok:
                    entry.update(dnc_registered=False, registry_as_of=as_of, scrubbed_at=stamp)
                    stats["rescrubbed"] += 1
                elif entry.get("dnc_registered") is not None or entry.get("dnc_status") is None:
                    # no usable registry and the old answer has expired (or there never was one)
                    entry.update(dnc_registered=None, scrubbed_at=stamp)
                    entry.pop("registry_as_of", None)
            else:
                stats["kept"] += 1
            if internal is not None:
                on_list = ph in internal
                if entry.get("internal_dnc") != on_list:
                    entry["internal_dnc"] = on_list
            entry.pop("block_reason", None)
            st = derive_status(entry, now)
            if entry.get("dnc_status") != st:
                entry["dnc_status"] = st
            stats[st] += 1
            results.append(entry)
        if results != existing:
            raw["dnc_scrub"] = results
        stats["scrubbed"] += 1

    stats["registered"] = stats["on_registry"]           # the name before 2026-10-09
    stats["seconds"] = round(time.monotonic() - t0, 1)
    log.info("dnc.done", **{k: v for k, v in stats.items() if isinstance(v, (int, float, bool))})
    return stats


def scrub_summary(rows: Iterable[dict], now: Optional[datetime] = None) -> dict:
    """Counts of dnc_scrub statuses over board rows (dicts), for checks and reports."""
    now = now or datetime.now(timezone.utc)
    out: dict[str, int] = {}
    for row in rows:
        raw = row.get("raw") if isinstance(row, dict) else None
        for e in (raw or {}).get("dnc_scrub") or []:
            if isinstance(e, dict):
                s = str(e.get("dnc_status"))
                out[s] = out.get(s, 0) + 1
    return out


def iter_phone_numbers(rows: Iterable[dict]) -> Iterator[str]:
    """Every 10-digit phone the scrub would see on board rows (dicts)."""
    for row in rows:
        raw = row.get("raw") if isinstance(row, dict) else None
        if not isinstance(raw, dict):
            continue
        op = raw.get("owner_phone")
        if isinstance(op, dict):
            p = _normalize_phone(op.get("phone"))
            if p:
                yield p
