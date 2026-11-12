#!/usr/bin/env python3
"""Compare a candidate board with the live one, and say which is better, before it can replace it.

WHY (owner's standing instruction, 2026-10-08): whenever a new board could replace the live one,
compare the two and publish whichever is better; never publish blind. A full run moves hundreds of
thousands of rows; "the run exited 0" says nothing about whether the board it left is better than
the one people are calling from. Every defect of this month (a tax debt copied onto 20,185 wrong
rows, placeholder presence checks, starved counties, unwired enrichers) would have shown here as a
number that moved the wrong way.

WHAT IT READS
  --baseline   the live published board directory (docs/), or a checkpoint directory.
  --candidate  another board directory (a scratch write_artifact output) or a checkpoint directory
               (data/checkpoint: board.json.gz + manifest.json [+ resume_state.json]). A checkpoint
               is read exactly as `board_selfcheck.py --checkpoint` and `audit_suite.py --checkpoint`
               read one: each row validated to a Listing and passed through web_artifact._to_dict,
               i.e. the row write_artifact would publish. A board directory is read with
               board_stream.iter_board_rows_with_detail (parts verified against the manifest, the
               index-aligned sidecar merged for the detail keys the checks need).
  Optional run evidence per board: --*-log (the vm-run / vm-resume log), --*-memlog (its watchdog
  log), --*-state (a resume_state.json, e.g. data/checkpoint_archive/pre_publish_<ts>/).

HOW (memory). Two streaming passes, one row at a time, never a board in memory: pass 1 reads the
baseline and keeps, per row, a fixed 92-byte record (tier, source, county, 11 field hashes, a
column bitmask, a signal bitmask) in one bytearray, an opaque reference string, and its identity
keys as 64-bit hashes in two flat arrays sorted once; pass 2 streams the candidate, joins each row
to the baseline on the board's stable identity (verification.core.row_keys: parcel, then numbered
address, then case, the keys the verification ledger already matches on, because Listing.dedupe_key
moves when a parcel is backfilled; the as-scraped fingerprint last), and counts. Measured on the
350,013-row 10/7 board compared with itself (2026-10-08, the Mac): 491 s, 521 MB maximum resident
set, 792 MB peak memory footprint; details in docs/audit_2026-10-09/compare_boards.md.

WHAT IT REPORTS (each section in the JSON and in the plain-words markdown)
  1 rows       totals by state, county and source for both; baseline rows missing from the
               candidate by source and by the reason bucket the row itself shows; rows new in the
               candidate; sources under 90% of baseline or at zero.
  2 coverage   every gap_matrix column (the owner's 73 + the 9 attorney columns, computed by
               scripts/gap_matrix.py's own functions, not restated here), three extra fields and
               every distress signal: ROW COUNTS first, then the share of all rows, of HOT+WARM
               rows, and of rows present in BOTH boards (the like-for-like lens). Regressions are
               judged on the like-for-like lens and on the rows HOT or WARM on BOTH boards, never
               on the all-rows or all-HOT+WARM share alone (a board that grows with sparse rows, or
               promotes COLD rows, lowers those while no row loses the value).
  3 fields     rows present in both that HAD a value and now have none (lost) or another one
               (changed): owner name, street address, parcel id, phone, email, mailing address,
               tax balance, tax years, tax levy year, assessed value, comps, and each signal flag;
               up to 20 sample ids per class.
  4 tiers      HOT/WARM/COLD counts, the transition matrix, HOT leads leaving or entering with
               the signals they lost or gained.
  5 invariants scripts/audit_checks/* (via scripts/audit_suite.py's loader) and
               board_selfcheck.invariants, run on both boards inside the same passes.
  6 publish    artifact sizes against the limits the repo documents (board_parts.PART_MAX_BYTES,
               check_payload_size.py: GitHub 50/95/100 MiB, Pages 600/950 MB), part/manifest/
               sidecar alignment (BoardIntegrityError paths), JSON/gzip validity of every payload
               file, and the heir publishing rule (PUBLISHABLE_HEIR_RELATIONS: no other relation,
               no phone, e-mail or age, no minor). A checkpoint has no files yet: its published
               sizes are estimated by compressing each row as write_artifact would (level 9).
  7 process    what produced each board (commit pin, run profile, phases that ran, were capped or
               failed, sources and their rows, per-phase seconds, peak memory, selfcheck and audit
               results, rows dropped by each named filter, how fresh its verification ledgers
               were) and which board has the process and structure right; "not recorded" where
               the run left no record, with the list of what runs should record from now on.
  8 verdict    PASS / PASS_WITH_NOTES / HOLD, each blocker with the threshold it crossed
               (thresholds are the constants below), and the BEST-OF-BOTH list: field values the
               live board holds that the candidate lost (ids only): the merge's fix candidates.

PRIVACY. The repo and dashboard are public. Every output is counts, source slugs, county names,
column and signal names, parcel ids and opaque row references ("h:<16 hex>" for a row with no
parcel id: a hash of its identity key, recomputable with row_ref()). No owner name, phone, e-mail,
street address or notice text is written. The run-log reader keeps numbers and code identifiers
only.

OUTPUTS
  --out FILE.json            the full report
  --md FILE.md               the plain-words verdict (default: FILE.json with .md)
  --best-of-both-out F.jsonl one line per lost good value (default: FILE.json -> .best_of_both.jsonl)
  docs/board_versions/<date>_<label>.json   the iteration ledger record (counts only; --no-ledger
                             or --ledger-dir to change)
  --append-changelog         also append the human entry to docs/board_versions/CHANGELOG.md

USAGE
  uv run python scripts/compare_boards.py --candidate data/checkpoint --out /tmp/cmp.json \
      [--baseline docs] [--candidate-log logs/vm-run-X.log --candidate-memlog logs/vm-run-X.mem.log] \
      [--label gated_d42058b3] [--accept-source-drop national.fannie_homepath] [--append-changelog]
EXIT 0 PASS or PASS_WITH_NOTES, 1 HOLD, 2 could not compare.
"""
from __future__ import annotations

import argparse
import array
import gzip
import importlib.util
import hashlib
import json
import math
import os
import re
import resource
import struct
import subprocess
import sys
import time
import zlib
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Iterable, Iterator, Optional

import numpy as np

REPO = Path(__file__).resolve().parent.parent
for _p in (REPO / "src", REPO / "scripts"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import board_selfcheck as BS  # noqa: E402  (scripts/: invariants + the checkpoint reader)
import check_payload_size as CPS  # noqa: E402  (scripts/: GitHub / Pages size limits)
import gap_matrix as GM  # noqa: E402  (scripts/: the owner's column definitions)
from foreclosure_scraper import board_parts as BP  # noqa: E402
from foreclosure_scraper import checkpoint as CK  # noqa: E402
from foreclosure_scraper.board_stream import detail_source, iter_board_rows_with_detail  # noqa: E402
from foreclosure_scraper.enrichment_heir_candidates import (  # noqa: E402
    PUBLISHABLE_HEIR_RELATIONS, PUBLISHED_FIELDS)
from foreclosure_scraper.models import _normalize_addr, _normalize_parcel  # noqa: E402
from foreclosure_scraper.verification.core import (  # noqa: E402
    _fingerprint, _house_numbered, looks_like_address, row_keys)
from foreclosure_scraper.web_artifact import (  # noqa: E402
    LAZY_DETAIL_KEYS, _project_slim_record, _shard_record)

try:
    import audit_suite as AS  # noqa: E402  (scripts/: the shared check loader)
except Exception:  # noqa: BLE001 - the suite is another audit area's file; compare without it
    AS = None

# =================================================================================================
# THRESHOLDS. Each one is the line a candidate must not cross; the reason sits beside it.
# =================================================================================================

#: The owner's rule: a source whose candidate count falls under 90% of its live count is flagged.
SOURCE_DROP_RATIO = 0.90
#: A source with fewer live rows than this moves 10% on a handful of rows: a drop is a note, not a
#: blocker (a fall to zero is always reported).
SOURCE_MIN_BASELINE_ROWS = 50
#: The candidate's total may not fall under 95% of the live total: the same 5% band
#: scripts/carry_publish_state.py uses before it lets two boards be paired.
TOTAL_ROWS_MIN_RATIO = 0.95
#: The owner's rule: a column whose coverage drops by more than half a percentage point is flagged.
COVERAGE_DROP_PP = 0.5
#: A share computed over fewer rows than this moves half a point on one row: not judged.
LENS_MIN_ROWS = 200
#: A column whose count moves by less than 1% (or fewer than 10 rows) is "flat".
FLAT_REL = 0.01
FLAT_MIN_ROWS = 10
#: Rows present in both that HAD a field value and lost it: more than 1% of the rows that had it is
#: a blocker (a re-scrape legitimately clears a few values; 1% of 300K rows is 3,000 leads).
FIELD_LOST_MAX_PCT = 1.0
#: ... judged only when at least this many overlapping rows had the value.
FIELD_MIN_ROWS = 100
#: Changed values (both present, different): noted above 5%. Re-scrapes legitimately change owners,
#: balances and valuations; a large share changing at once is worth a look, not an automatic stop.
FIELD_CHANGED_NOTE_PCT = 5.0
#: A signal flag lost on more than 10% of the overlapping rows that carried it is noted (verification
#: removes refuted and stale signals on purpose, so this is never a blocker by itself).
SIGNAL_LOST_NOTE_PCT = 10.0
#: Sample ids kept per class (the brief: ids only, at most 20 per class).
SAMPLE_IDS = 20
#: Heir publishing violations allowed on a board that goes live: none (owner decision 2026-10-07).
HEIR_VIOLATIONS_MAX = 0
#: Rows a checkpoint loses to validation (or a short file) before it is not publishable: the same
#: 0.1% as BOARD_LOAD_MAX_DROP_RATE / board_persist.PRIOR_MERGE_MAX_DROP_RATE.
CHECKPOINT_ROW_LOSS_MAX = 0.001
#: Unscored rows (no HOT/WARM/COLD tier) on the candidate: more than 0.1% means a path bypassed
#: the scorer (audit_checks/pipeline.py: pipeline-row-scored).
UNSCORED_MAX_FRACTION = 0.001
#: A run whose peak memory reached 90% of the watchdog's kill line is noted (the next, larger run
#: would be killed).
PEAK_MEM_NOTE_FRACTION = 0.90
#: A board whose newest verification verdict for a signal is this much older than the other
#: board's was scored on older ledgers (HANDOFF item 79: a pinned run applies the ledgers of its pin).
LEDGER_STALE_DAYS = 1.0
#: GitHub and Pages limits, from scripts/check_payload_size.py (warn 50 MiB per file, the repo's
#: 95 MiB pre-commit gate, GitHub's 100 MiB hard limit; Pages warns at 600 MB, fails at 950 MB) and
#: the part cap from board_parts.PART_MAX_BYTES (24 MiB, each part must fit Cloudflare's 25 MiB).
WARN_MIB = float(CPS.GITHUB_WARN_MIB)
GATE_MIB = 95.0
PART_MAX_MIB = BP.DEFAULT_PART_MAX_BYTES / (1024 * 1024)
PAGES_WARN_MB = CPS.PAGES_SITE_WARN_MB
PAGES_FAIL_MB = CPS.PAGES_SITE_FAIL_MB
#: An identity key carried by this many baseline rows with as many distinct addresses is a fused /
#: placeholder key (board_selfcheck.FUSION_THRESHOLD, dedupe.suspicious_parcel_keys): never a join key.
FUSION_THRESHOLD = BS.FUSION_THRESHOLD

try:  # the age-out rules the prior-board merge applies (reason buckets for missing rows)
    from foreclosure_scraper.board_persist import AGE_EXEMPT_SOURCES, _is_terminal_dict
except Exception:  # noqa: BLE001
    AGE_EXEMPT_SOURCES, _is_terminal_dict = frozenset({"liensnc"}), None
try:
    from foreclosure_scraper.enrichment_pulled_sales import PULLED_RETENTION_WEEKS
except Exception:  # noqa: BLE001
    PULLED_RETENTION_WEEKS = 4
try:
    from foreclosure_scraper.enrichment_reo_freshness import SNAPSHOT_REO_SOURCES
except Exception:  # noqa: BLE001
    SNAPSHOT_REO_SOURCES = ("national.fannie_homepath",)
try:
    from foreclosure_scraper.distress_score import FILING_DATE_SOURCES
except Exception:  # noqa: BLE001
    FILING_DATE_SOURCES = frozenset({"liensnc", "nc_sos_ucc"})
try:
    from foreclosure_scraper.enrichment_foreclosure_sold_comps import state_upset_window_days
except Exception:  # noqa: BLE001
    def state_upset_window_days(_state):  # type: ignore[misc]
        return 14

# =================================================================================================
# Row facts
# =================================================================================================

TIERS = ("none", "COLD", "WARM", "HOT")
TIER_CODE = {t: i for i, t in enumerate(TIERS)}
EXTRA_COLUMNS = ("x_mailing_address", "x_tax_balance", "x_tax_years_late")
COLUMNS: tuple[str, ...] = tuple(GM.ALL_COLUMNS) + EXTRA_COLUMNS
COL_BIT = {c: i for i, c in enumerate(COLUMNS)}
assert len(COLUMNS) <= 128, "the column bitmask is 16 bytes"
SIG_BYTES = 24                      # room for 192 distinct signal names
FIELDS = ("owner_name", "street_address", "parcel_id", "phone", "email", "mailing_address",
          "tax_balance", "tax_years", "tax_levy_year", "assessed_value", "comps")
NF = len(FIELDS)
#: fields judged for the best-of-both list (a value the live board had and the candidate lost)
BEST_OF_BOTH_FIELDS = FIELDS
REC = struct.Struct("<BBHHH" + "I" * NF + "16s" + f"{SIG_BYTES}s")

# flag bits (why a baseline row could legitimately be gone from the candidate)
F_TERMINAL, F_MISSES, F_COUNTYLESS, F_REO_SNAPSHOT, F_SALE_PASSED, F_AGE_EXEMPT = 1, 2, 4, 8, 16, 32

_PLACEHOLDER_OWNER = re.compile(r"^(unknown|n/?a|none|owner|current owner|not available|tbd)$")
_EMAIL_OK = re.compile(r"^[^@\s]+@[^@\s]+\.[a-z]{2,}$")


def _h4(s: str) -> int:
    v = int.from_bytes(hashlib.blake2b(s.encode("utf-8", "replace"), digest_size=4).digest(), "little")
    return v or 1


def _h8(s: str) -> int:
    return int.from_bytes(hashlib.blake2b(s.encode("utf-8", "replace"), digest_size=8).digest(), "little")


def _text(v: Any) -> Optional[str]:
    s = re.sub(r"\s+", " ", str(v if v is not None else "")).strip().casefold()
    return s or None


def _num(v: Any, nd: int = 2) -> Optional[float]:
    if isinstance(v, bool) or v is None or v == "":
        return None
    try:
        f = float(str(v).replace(",", "").replace("$", "")) if isinstance(v, str) else float(v)
    except (TypeError, ValueError):
        return None
    if f != f or f == 0:
        return None
    return round(f, nd)


def _dict(v: Any) -> dict:
    return v if isinstance(v, dict) else {}


def _raw(rec: dict) -> dict:
    r = rec.get("raw")
    return r if isinstance(r, dict) else {}


def row_ref(rec: dict, keys: Optional[list[str]] = None) -> str:
    """A public-safe reference to a row: "<STATE>|<county>|<parcel id>" when it has a parcel id (a
    public record), else "h:" + 16 hex of blake2b(its first identity key) (opaque; recompute it with
    this function on the same row to find it)."""
    pid = str(rec.get("parcel_id") or "").strip()
    st = str(rec.get("state") or "").strip().upper()
    co = str(rec.get("county") or "").strip()
    if pid:
        return f"{st}|{co}|{pid}"
    k = (keys or row_keys(rec) or ["?"])[0]
    return "h:" + hashlib.blake2b(k.encode("utf-8", "replace"), digest_size=8).hexdigest()


def field_values(rec: dict) -> list[tuple[Optional[str], bool]]:
    """[(normalized value or None, the value is a GOOD one)] in FIELDS order. A good value is one
    worth carrying back into a merge: a real-looking address, a parcel id that is not junk
    (gap_matrix.parcel_junk), a NANP phone (gap_matrix.phone_problem), a real e-mail, ..."""
    raw = _raw(rec)
    out: list[tuple[Optional[str], bool]] = []
    on = _text(rec.get("owner_name"))
    out.append((on, bool(on) and len(on) >= 3 and not _PLACEHOLDER_OWNER.match(on)))
    addr = rec.get("street_address")
    na = _normalize_addr(addr) if addr else ""
    out.append((na or None, bool(na) and looks_like_address(addr) and _house_numbered(na)))
    pid = rec.get("parcel_id")
    npid = (_normalize_parcel(pid) or _text(pid)) if pid else None
    out.append((npid, bool(npid) and not GM.parcel_junk(pid) and bool(_normalize_parcel(pid))))
    ph = _dict(raw.get("owner_phone")).get("phone")
    d = re.sub(r"\D", "", str(ph or ""))[-10:] or None
    out.append((d, bool(d) and GM.phone_problem(d) is None))
    em = _text(_dict(raw.get("owner_email")).get("best_email"))
    out.append((em, bool(em) and bool(_EMAIL_OK.match(em))))
    m = _dict(raw.get("owner_mailing")).get("mailing")
    if isinstance(m, dict):
        m = " ".join(str(v) for v in m.values() if v)
    mt = re.sub(r"[^a-z0-9]+", " ", str(m or "").lower()).strip() or None
    out.append((mt, bool(mt) and len(mt) >= 8 and any(ch.isdigit() for ch in mt)))
    to = _dict(raw.get("tax_owed"))
    bal = _num(to.get("balance"))
    out.append((None if bal is None else f"{bal:.2f}", bool(bal) and bal > 0))
    yd = to.get("years_delinquent")
    yd = yd if isinstance(yd, int) and not isinstance(yd, bool) else None
    out.append((None if yd is None else str(yd), bool(yd) and yd > 0))
    ly = to.get("year")
    ly = str(ly).strip() if ly not in (None, "") else None
    out.append((ly, bool(ly)))
    av = next((x for x in (_num(rec.get(k), 0) for k in ("assessed_value", "market_value", "tax_value"))
               if x is not None), None)
    out.append((None if av is None else f"{av:.0f}", bool(av) and av > 0))
    comps = raw.get("comps")
    if isinstance(comps, list) and comps:
        sig = "|".join(sorted(f"{c.get('sold_date')}:{c.get('sold_price')}" for c in comps if isinstance(c, dict)))
        out.append((sig or str(len(comps)), True))
    else:
        out.append((None, False))
    return out


def row_columns(rec: dict) -> set[str]:
    """The gap_matrix columns (computed by gap_matrix's own functions: owner_columns for the
    owner's 73, positive_columns for the attorney columns) plus the three extra fields."""
    owner = GM.owner_columns(rec)
    verdicts = GM.row_verdicts(rec, {}, [])          # raw.verification only: the board's own
    pos = GM.positive_columns(rec, owner, verdicts)
    cols = set(owner) | {c for c in pos if c.startswith("atty_")}
    raw = _raw(rec)
    if _dict(raw.get("owner_mailing")).get("mailing"):
        cols.add("x_mailing_address")
    to = _dict(raw.get("tax_owed"))
    if (_num(to.get("balance")) or 0) > 0:
        cols.add("x_tax_balance")
    yd = to.get("years_delinquent")
    if isinstance(yd, int) and not isinstance(yd, bool) and yd > 0:
        cols.add("x_tax_years_late")
    return cols


def tier_and_signals(rec: dict) -> tuple[int, frozenset]:
    ds = _raw(rec).get("distress_stack")
    if not isinstance(ds, dict):
        return 0, frozenset()
    sig = ds.get("signals")
    sigs = frozenset(str(s) for s in sig if isinstance(s, str)) if isinstance(sig, list) else frozenset()
    return TIER_CODE.get(str(ds.get("tier") or ""), 0), sigs


def _parse_dt(v: Any) -> Optional[datetime]:
    if not v:
        return None
    try:
        d = datetime.fromisoformat(str(v).replace("Z", "+00:00"))
    except ValueError:
        return None
    return d.replace(tzinfo=None) if d.tzinfo else d


def leave_flags(rec: dict, now: datetime) -> int:
    """Why this row could legitimately leave in the next run (the rules the run applies):
    board_persist._is_terminal_dict (sold / confirmed / upset deadline passed / sale over a year
    ago), the pulled-sale miss limit (board_persist, PULLED_RETENTION_WEEKS), main's countyless
    national/REO drop, enrichment_reo_freshness.prune_stale_reo's snapshot sources, main._active_only's
    upset window (a year for FILING_DATE_SOURCES). AGE_EXEMPT sources never reach the miss limit."""
    f = 0
    raw = _raw(rec)
    src = str(rec.get("source") or "")
    parts = src.split(".")
    exempt = any(part in AGE_EXEMPT_SOURCES for part in parts)
    try:
        if _is_terminal_dict is not None and _is_terminal_dict(rec, now):
            f |= F_TERMINAL
    except Exception:  # noqa: BLE001
        pass
    if not exempt and (_dict(raw.get("pulled_sale")).get("consecutive_misses") or 0) >= PULLED_RETENTION_WEEKS:
        f |= F_MISSES
    if (src.startswith("national.") or src.startswith("reo.")) and not str(rec.get("county") or "").strip():
        f |= F_COUNTYLESS
    if src in SNAPSHOT_REO_SOURCES:
        f |= F_REO_SNAPSHOT
    sd = _parse_dt(rec.get("sale_date"))
    # a filing-date source stores the FILING date there; main._active_only gives it a year
    window = 365 if any(part in FILING_DATE_SOURCES for part in parts) else state_upset_window_days(rec.get("state"))
    if sd is not None and sd < now - timedelta(days=window):
        f |= F_SALE_PASSED
    if exempt:
        f |= F_AGE_EXEMPT
    return f


# ---- heir publishing rule ----------------------------------------------------------------------
_HEIR_FORBIDDEN = {"phone", "phones", "phone_number", "telephone", "email", "emails", "e_mail", "age",
                   "birth_date", "birthdate", "dob", "born", "date_of_birth", "minor", "note", "notes"}
_PHONE_RE = re.compile(r"\(?\b\d{3}\)?[-.\s]\d{3}[-.\s]\d{4}\b")
_EMAIL_RE = re.compile(r"[^@\s]+@[^@\s]+\.[A-Za-z]{2,}")
_CONTACT_LIKE = re.compile(r"\d|@|https?://|www\.", re.I)


def _walk_strings(v: Any, depth: int = 0) -> Iterator[str]:
    if depth > 4:
        return
    if isinstance(v, str):
        yield v
    elif isinstance(v, dict):
        for x in v.values():
            yield from _walk_strings(x, depth + 1)
    elif isinstance(v, list):
        for x in v[:200]:
            yield from _walk_strings(x, depth + 1)


def _walk_forbidden(v: Any, depth: int = 0) -> Iterator[str]:
    if depth > 4:
        return
    if isinstance(v, dict):
        for k, x in v.items():
            if str(k).lower() in _HEIR_FORBIDDEN and x not in (None, "", [], {}, False):
                yield str(k).lower()
            yield from _walk_forbidden(x, depth + 1)
    elif isinstance(v, list):
        for x in v[:200]:
            yield from _walk_forbidden(x, depth + 1)


def heir_findings(rec: dict) -> tuple[Counter, Counter]:
    """(violations, notes) of the heir publishing rule on one PUBLISHED row.

    Violations (a board carrying any is not publishable, HEIR_VIOLATIONS_MAX): raw.heir_candidates
    entries outside PUBLISHABLE_HEIR_RELATIONS, fields outside PUBLISHED_FIELDS (+ a probate
    representative's printed address), a minor, a name carrying digits / '@' / a URL, a phone or
    e-mail anywhere in an heir name list (heir_candidates, obituary.survivors,
    heir_naming_publication.named_heirs, heir_estate.heir_names) or a phone / e-mail / age / birth
    date / minor field in one, and raw.obituary_match (never published: whole survivor lists).
    Notes (owner-decision territory, counted): heir names published with NO relation by older
    blocks (heir_estate.heir_names from the tax roll, heir_naming_publication.named_heirs from a
    court notice), and obituary survivor lists."""
    raw = _raw(rec)
    bad: Counter = Counter()
    note: Counter = Counter()
    hc = raw.get("heir_candidates")
    if hc is not None:
        if not isinstance(hc, list):
            bad["heir_candidates_not_a_list"] += 1
        else:
            for c in hc:
                if not isinstance(c, dict):
                    bad["heir_candidate_not_an_object"] += 1
                    continue
                if c.get("relation") not in PUBLISHABLE_HEIR_RELATIONS:
                    bad["heir_relation_not_publishable"] += 1
                extra = set(c) - set(PUBLISHED_FIELDS) - {"address"}
                if extra & _HEIR_FORBIDDEN:
                    bad["heir_contact_age_or_minor_field"] += 1
                elif extra:
                    bad["heir_unpublished_field"] += 1
                if "address" in c and c.get("source_kind") != "probate_notice_personal_representative":
                    bad["heir_address_outside_probate_notice"] += 1
                age = c.get("age")
                if c.get("minor") or (isinstance(age, (int, float)) and not isinstance(age, bool) and age < 18):
                    bad["heir_minor"] += 1
                name = str(c.get("name") or "")
                if len(name.split()) < 2 or _CONTACT_LIKE.search(name):
                    bad["heir_name_not_a_plain_name"] += 1
                if any(_PHONE_RE.search(s) or _EMAIL_RE.search(s) for s in _walk_strings(
                        {k: v for k, v in c.items() if k not in ("source_url", "address")})):
                    bad["heir_phone_or_email"] += 1
    if raw.get("obituary_match") is not None:
        bad["obituary_match_published"] += 1
    lists = {
        "obituary.survivors": _dict(raw.get("obituary")).get("survivors"),
        "heir_naming_publication.named_heirs": _dict(raw.get("heir_naming_publication")).get("named_heirs"),
        "heir_estate.heir_names": _dict(raw.get("heir_estate")).get("heir_names"),
    }
    for where, v in lists.items():
        if not v:
            continue
        note[f"rows_with_{where}"] += 1
        if any(_PHONE_RE.search(s) or _EMAIL_RE.search(s) for s in _walk_strings(v)):
            bad[f"phone_or_email_in_{where}"] += 1
        for k in _walk_forbidden(v):
            bad[f"{k}_field_in_{where}"] += 1
            if k == "minor":
                bad["heir_minor"] += 1
        if isinstance(v, list) and where == "obituary.survivors":
            for s in v:
                if isinstance(s, dict) and s.get("relation") and str(s["relation"]).lower() not in PUBLISHABLE_HEIR_RELATIONS:
                    bad["obituary_survivor_relation_not_publishable"] += 1
    return bad, note


# =================================================================================================
# Small containers
# =================================================================================================

class Samples:
    """At most `cap` ids per class (ids only)."""

    def __init__(self, cap: int = SAMPLE_IDS):
        self.cap = cap
        self.d: dict[str, list[str]] = {}

    def add(self, cls: str, ref: str) -> None:
        lst = self.d.setdefault(cls, [])
        if len(lst) < self.cap:
            lst.append(ref)

    def get(self, cls: str) -> list[str]:
        return list(self.d.get(cls, []))


class Cov:
    """Rows and column counts by state (and ALL)."""

    def __init__(self):
        self.n: Counter = Counter()
        self.c: dict[str, Counter] = defaultdict(Counter)

    def add(self, state: str, cols: Iterable[str]) -> None:
        cols = list(cols)
        for s in ("ALL", state):
            self.n[s] += 1
            cs = self.c[s]
            for col in cols:
                cs[col] += 1


def _state(st: str) -> str:
    return st if st in ("NC", "SC") else "other"


class BoardStats:
    """Everything counted on one board during its pass (bounded: counters and capped samples)."""

    def __init__(self, name: str):
        self.name = name
        self.n = 0
        self.by_state: Counter = Counter()
        self.by_county: Counter = Counter()
        self.by_source: Counter = Counter()
        self.tiers: Counter = Counter()
        self.cov_all = Cov()
        self.cov_hw = Cov()
        self.heir_bad: Counter = Counter()
        self.heir_note: Counter = Counter()
        self.heir_samples = Samples()
        self.ver_rows: Counter = Counter()
        self.ver_verdicts: dict[str, Counter] = defaultdict(Counter)
        self.ver_newest: dict[str, str] = {}
        self.unscored = 0
        self.selfcheck: Optional[list] = None
        self.audit: Optional[list] = None
        self.audit_note = ""
        self.read_error: Optional[str] = None

    def add(self, rec: dict, st: str, co: str, src: str, tier: int, sigs: frozenset, cols: set[str]) -> None:
        self.n += 1
        s = _state(st)
        self.by_state[st or "?"] += 1
        self.by_county[f"{st or '?'}|{co}"] += 1
        self.by_source[src] += 1
        self.tiers[TIERS[tier]] += 1
        if tier == 0:
            self.unscored += 1
        allcols = set(cols) | {"sig:" + x for x in sigs}
        self.cov_all.add(s, allcols)
        if tier >= 2:
            self.cov_hw.add(s, allcols)
        bad, note = heir_findings(rec)
        if bad:
            self.heir_bad.update(bad)
            for k in bad:
                self.heir_samples.add(k, row_ref(rec))
        if note:
            self.heir_note.update(note)
        ver = _raw(rec).get("verification")
        if isinstance(ver, list):
            seen = set()
            for v in ver:
                if not isinstance(v, dict) or not v.get("signal"):
                    continue
                sig = str(v["signal"])
                if sig not in seen:
                    self.ver_rows[sig] += 1
                    seen.add(sig)
                self.ver_verdicts[sig][str(v.get("verdict"))] += 1
                ca = str(v.get("checked_at") or "")
                if ca and ca > self.ver_newest.get(sig, ""):
                    self.ver_newest[sig] = ca


# =================================================================================================
# Reading a board
# =================================================================================================

class BoardInput:
    """A board directory or a checkpoint directory, opened through the existing readers."""

    def __init__(self, path: Path, kind: str = "auto", detail_keys: Iterable[str] = ("comps",),
                 estimate_sizes: bool = False):
        self.path = Path(path)
        if self.path.is_file() and self.path.name == CK.BOARD_FILE:
            self.path = self.path.parent
        self.kind = kind if kind != "auto" else self._detect()
        self.detail_keys = tuple(dict.fromkeys(["comps", *detail_keys]))
        self.rows_read = 0
        self.ckpt_manifest: dict = {}
        self.ckpt_state: dict = {}
        self.ckpt_state_problem: Optional[str] = None
        self.ckpt_age_h: Optional[float] = None
        self.estimator = SizeEstimator() if (estimate_sizes and self.kind == "checkpoint") else None
        if self.kind == "checkpoint":
            self._read_checkpoint_meta()

    def _detect(self) -> str:
        p = self.path
        if (p / CK.BOARD_FILE).is_file() and (p / CK.MANIFEST_FILE).is_file():
            return "checkpoint"
        if (p / BP.MANIFEST_NAME).is_file() or BP.list_part_files(p) or (p / "listings.json.gz").is_file():
            return "board"
        raise FileNotFoundError(f"{p}: neither a board directory (board.manifest.json / listings parts) "
                                f"nor a checkpoint directory ({CK.BOARD_FILE} + {CK.MANIFEST_FILE})")

    def _read_checkpoint_meta(self) -> None:
        """The checkpoint's manifest, age and publish inputs, via checkpoint.py's own readers
        (pointed at this directory for the call: they read the module's CHECKPOINT_DIR)."""
        old = CK.CHECKPOINT_DIR
        try:
            CK.CHECKPOINT_DIR = self.path
            self.ckpt_manifest = CK.manifest() or {}
            self.ckpt_age_h = CK.age_hours()
            self.ckpt_state, self.ckpt_state_problem = CK.load_publish_state()
        finally:
            CK.CHECKPOINT_DIR = old

    def run_time(self) -> Optional[datetime]:
        if self.kind == "checkpoint":
            return _parse_dt(self.ckpt_manifest.get("saved_at"))
        try:
            return _parse_dt(json.loads((self.path / "run_meta.json").read_text()).get("run_time"))
        except (OSError, ValueError):
            return None

    def rows(self) -> Iterator[dict]:
        """The board's rows in the PUBLISHED shape, with raw['comps'] (and any detail key a check
        names) merged from the sidecar; a checkpoint row is validated and passed through
        web_artifact._to_dict by board_selfcheck's own reader (its lazy-detail keys stay inline, as
        audit_suite feeds them)."""
        self.rows_read = 0
        if self.kind == "checkpoint":
            est = self.estimator
            for rec in BS._checkpoint_rows(self.path):
                if est is not None:
                    raw = rec.get("raw") if isinstance(rec.get("raw"), dict) else {}
                    d = {k: raw.pop(k) for k in LAZY_DETAIL_KEYS if k in raw}
                    est.add(rec, d)
                    raw.update(d)
                self.rows_read += 1
                yield rec
            return
        src = self.path / "listings.json.gz"
        try:
            detail_source(self.path)
            have_detail = True
        except FileNotFoundError:
            have_detail = False
        it = iter_board_rows_with_detail(src, keys=self.detail_keys if have_detail else ())
        for rec in it:
            self.rows_read += 1
            yield rec


class SizeEstimator:
    """What write_artifact would write for a checkpoint, without writing it: each row encoded the
    way write_artifact encodes it (parts: the row minus LAZY_DETAIL_KEYS; listings_detail: those
    keys; slim: _project_slim_record; shards: _shard_record), streamed through gzip-level-9
    compressors (write_artifact uses level 9 for all four). One stream per file family; parts are
    cut later, so their total is what is estimated. Nothing is kept but byte counts."""

    def __init__(self, level: int = 9):
        self._enc = json.JSONEncoder(ensure_ascii=False, default=str)
        self.z = {k: zlib.compressobj(level, zlib.DEFLATED, 31) for k in ("parts", "detail", "slim", "shards")}
        self.out = Counter()
        self.raw = Counter()
        self.n = 0

    def _feed(self, k: str, b: bytes, sep: bytes) -> None:
        if self.n:
            b = sep + b
        self.raw[k] += len(b)
        self.out[k] += len(self.z[k].compress(b))

    def add(self, rec: dict, d: dict) -> None:
        self._feed("parts", self._enc.encode(rec).encode("utf-8"), b", ")
        self._feed("detail", self._enc.encode(d).encode("utf-8"), b", ")
        try:
            self._feed("slim", json.dumps(_project_slim_record(rec), ensure_ascii=False, default=str,
                                          separators=(",", ":")).encode("utf-8"), b",")
            self._feed("shards", json.dumps(_shard_record(rec, d), ensure_ascii=False, default=str,
                                            separators=(",", ":")).encode("utf-8"), b",")
        except Exception:  # noqa: BLE001 - a derivative estimate, never the comparison
            pass
        self.n += 1

    def finish(self) -> dict:
        res = {}
        for k, z in self.z.items():
            self.out[k] += len(z.flush())
            res[k + "_gz_bytes"] = self.out[k] + 2
            res[k + "_raw_bytes"] = self.raw[k] + 2
        res["rows"] = self.n
        return res


# =================================================================================================
# The passes
# =================================================================================================

class Interned:
    def __init__(self):
        self.items: list = []
        self.idx: dict = {}

    def get(self, v) -> int:
        i = self.idx.get(v)
        if i is None:
            i = self.idx[v] = len(self.items)
            self.items.append(v)
        return i


class BaselineIndex:
    """Pass 1's product: one fixed record per baseline row, its reference, and its identity keys as
    two flat arrays (64-bit key hash, row number), sorted once after the pass and searched with
    numpy.searchsorted: about 12 bytes per key instead of a dict entry and two int objects (~120 MB
    at 1M keys measured on the 10/7 board's first version of this index)."""

    def __init__(self):
        self.buf = bytearray()
        self.refs: list[str] = []
        self.n = 0
        self._kh = array.array("Q")
        self._ki = array.array("I")
        self.kh = np.zeros(0, dtype=np.uint64)
        self.ki = np.zeros(0, dtype=np.uint32)
        self.fused: set[int] = set()
        self.sources = Interned()
        self.counties = Interned()
        self.sig_names = Interned()
        self.fused_keys = 0
        self.matched = bytearray()
        self.seen = bytearray()

    def sig_mask(self, sigs: Iterable[str]) -> bytes:
        m = 0
        for s in sigs:
            i = self.sig_names.get(s)
            if i < SIG_BYTES * 8:
                m |= 1 << i
        return m.to_bytes(SIG_BYTES, "little")

    def sigs_of(self, mask: bytes) -> set[str]:
        m = int.from_bytes(mask, "little")
        out = set()
        i = 0
        while m:
            if m & 1:
                out.add(self.sig_names.items[i])
            m >>= 1
            i += 1
        return out

    @staticmethod
    def col_mask(cols: Iterable[str]) -> bytes:
        m = 0
        for c in cols:
            b = COL_BIT.get(c)
            if b is not None:
                m |= 1 << b
        return m.to_bytes(16, "little")

    @staticmethod
    def cols_of(mask: bytes) -> set[str]:
        m = int.from_bytes(mask, "little")
        return {COLUMNS[i] for i in range(len(COLUMNS)) if m >> i & 1}

    def add(self, facts: "Facts") -> None:
        fh = [(_h4(v) if v is not None else 0) for v, _ in facts.fvals]
        good = 0
        for i, (_, g) in enumerate(facts.fvals):
            if g:
                good |= 1 << i
        self.buf += REC.pack(facts.tier, facts.flags, self.sources.get(facts.src),
                             self.counties.get((facts.st, facts.co)), good, *fh,
                             self.col_mask(facts.cols), self.sig_mask(facts.sigs))
        self.refs.append(facts.ref)
        for k in dict.fromkeys(facts.keys):
            self._kh.append(_h8(k))
            self._ki.append(self.n)
        self.n += 1

    def rows_for(self, kh: int) -> list[int]:
        """Baseline rows carrying key hash `kh` (none for a fused key)."""
        if kh in self.fused:
            return []
        v = np.uint64(kh)
        lo = int(np.searchsorted(self.kh, v, "left"))
        if lo >= len(self.kh) or self.kh[lo] != v:
            return []
        hi = int(np.searchsorted(self.kh, v, "right"))
        return [int(x) for x in self.ki[lo:hi]]

    def record(self, i: int) -> tuple:
        return REC.unpack_from(self.buf, i * REC.size)

    def finish(self) -> None:
        """Retire fused keys (FUSION_THRESHOLD rows with as many distinct addresses) and size the
        match / seen flags."""
        kh = np.frombuffer(self._kh, dtype=np.uint64) if len(self._kh) else np.zeros(0, dtype=np.uint64)
        ki = np.frombuffer(self._ki, dtype=np.uint32) if len(self._ki) else np.zeros(0, dtype=np.uint32)
        order = np.argsort(kh, kind="stable")
        self.kh, self.ki = kh[order], ki[order]
        del kh, ki, order
        self._kh, self._ki = array.array("Q"), array.array("I")
        if len(self.kh):
            uniq, start, counts = np.unique(self.kh, return_index=True, return_counts=True)
            for j in np.nonzero(counts >= FUSION_THRESHOLD)[0]:
                rows = self.ki[start[j]:start[j] + counts[j]]
                addrs = {self.record(int(i))[5 + 1] for i in rows}
                addrs.discard(0)
                if len(addrs) >= FUSION_THRESHOLD:
                    self.fused.add(int(uniq[j]))
            del uniq, start, counts
        self.fused_keys = len(self.fused)
        self.matched = bytearray(self.n)
        self.seen = bytearray(self.n)


def _source_id_fields() -> dict:
    """{source slug: (raw block, key)} of the ids sources keep in their own raw block: board_persist's
    table of nulled short ids plus parcel_alias's short-id sources (Lincoln PARCELID, Rutherford
    Parcel_Number). Empty when the package cannot be imported."""
    out: dict = {}
    try:
        from foreclosure_scraper.board_persist import _SOURCE_PARCEL_FIELDS
        out.update(_SOURCE_PARCEL_FIELDS)
    except Exception:  # noqa: BLE001
        pass
    try:
        from foreclosure_scraper.parcel_alias import ALIAS_SOURCES
        out.update(ALIAS_SOURCES)
    except Exception:  # noqa: BLE001
        pass
    return out


_SID_FIELDS = _source_id_fields()
_SID_BLOCKS = sorted({b for b, _ in _SID_FIELDS.values()})


def source_id_keys(rec: dict) -> list[str]:
    """"sid:<STATE>:<county>:<id>" for the id a source published for the row in its own raw block
    (_SID_FIELDS) or that validation nulled (raw['parcel_id_nulled']), whatever the row's parcel_id
    is now. Why (audit 2026-10-09, regressions): the 10/7 board published 15,932 Lincoln and Rutherford
    rows with no parcel (their short ids were nulled) and the next run published the same rows under
    the 10-digit PIN, so the two boards shared no parcel key; unnumbered vacant lots shared no address
    key either, and the as-scraped fingerprint paired different lots of one owner on one road. The
    comparison then reported 1,818 Lincoln rows missing and 1,009 rows as having lost their comps (625
    their tax balance) that were all on the candidate under the PIN. Ids of four characters or more
    (dedupe.MIN_SOURCE_PARCEL_LEN), county-qualified, so one county's id system never meets another's."""
    raw = _raw(rec)
    st = str(rec.get("state") or "").strip().upper()
    co = str(rec.get("county") or "").strip().lower()
    if not co:
        return []
    ids = []
    nulled = raw.get("parcel_id_nulled")
    if isinstance(nulled, dict) and nulled.get("value"):
        ids.append(nulled["value"])
    for blk_name in _SID_BLOCKS:
        blk = raw.get(blk_name)
        if isinstance(blk, dict):
            for b, k in _SID_FIELDS.values():
                if b == blk_name and blk.get(k):
                    ids.append(blk[k])
    out = []
    for v in ids:
        n = re.sub(r"[^0-9a-z]", "", str(v).lower())
        if len(n) >= 4 and len(set(n)) > 1:
            k = f"sid:{st}:{co}:{n}"
            if k not in out:
                out.append(k)
    return out


def join_keys(rec: dict) -> list[str]:
    """The row's identity keys for the join, strongest first: verification.core.row_keys (parcel,
    numbered address, case; else the as-scraped fingerprint), the id its source published in its own
    raw block (source_id_keys: a short id that became a PIN between two boards is still one row),
    then, as a last resort, that same fingerprint ("fp:", which leaves the parcel id out) so a row
    that lost its only parcel key still finds itself when its as-scraped fields did not change."""
    try:
        keys = [k for k in row_keys(rec) if not k.startswith("row:")]
    except Exception:  # noqa: BLE001 - an odd row has only its fingerprint key
        keys = []
    try:
        keys.extend(source_id_keys(rec))
    except Exception:  # noqa: BLE001
        pass
    try:
        keys.append("fp:" + _fingerprint(rec))        # row_keys' own "row:" key is this same hash
    except Exception:  # noqa: BLE001
        pass
    return keys


class Facts:
    __slots__ = ("keys", "ref", "st", "co", "src", "tier", "sigs", "cols", "fvals", "flags")

    def __init__(self, rec: dict, now: datetime):
        self.keys = join_keys(rec)
        self.ref = row_ref(rec, [k for k in self.keys if not k.startswith("fp:")] or None)
        self.st, self.co = GM.county_key(rec)
        self.src = str(rec.get("source") or "")
        self.tier, self.sigs = tier_and_signals(rec)
        self.cols = row_columns(rec)
        self.fvals = field_values(rec)
        self.flags = leave_flags(rec, now)


def _drive(rows: Iterator[dict], on_row: Callable[[dict], None], selfcheck: bool) -> Optional[list]:
    """One pass: every row goes to on_row and then (when asked) to board_selfcheck.invariants,
    which consumes the same stream (its one-pass contract), as board_selfcheck._tee does."""
    def gen():
        for r in rows:
            on_row(r)
            yield r
    if selfcheck:
        return BS.invariants(gen())
    for _ in gen():
        pass
    return None


class AuditFeed:
    """scripts/audit_checks/* loaded through audit_suite.discover (a fresh set per board), fed in
    the pass, finished with audit_suite's own normalization."""

    def __init__(self, enabled: bool, checks_dir: Optional[Path] = None):
        self.checks: list = []
        self.note = ""
        self.detail_keys: tuple = ()
        self.errors: list[int] = []
        self.first_error: list[Optional[str]] = []
        if not enabled:
            self.note = "skipped (--no-audit-checks)"
            return
        if AS is None:
            self.note = "skipped: scripts/audit_suite.py is absent"
            return
        d = checks_dir or AS.CHECKS_DIR
        if not Path(d).is_dir() or not any(Path(d).glob("*.py")):
            self.note = f"skipped: no checks in {Path(d).name}/"
            return
        self.checks = AS.discover(Path(d))
        self.detail_keys = tuple(sorted({k for _, _, ks in self.checks for k in ks}))
        self.errors = [0] * len(self.checks)
        self.first_error = [None] * len(self.checks)

    def feed(self, row: dict) -> None:
        for i, (_, c, _) in enumerate(self.checks):
            try:
                c.feed(row)
            except Exception as exc:  # noqa: BLE001 - one check's bug never stops the pass
                self.errors[i] += 1
                if self.first_error[i] is None:
                    self.first_error[i] = f"{type(exc).__name__}: {exc}"

    def finish(self) -> Optional[list]:
        if not self.checks:
            return None
        out = []
        for i, (stem, c, _) in enumerate(self.checks):
            name = str(getattr(c, "name", stem))
            try:
                res = AS._normalize(c.finish(), name)
            except Exception as exc:  # noqa: BLE001
                res = {"name": name, "checked": 0, "violations": 1, "max_violations": 0, "ok": False,
                       "detail": f"finish() raised {type(exc).__name__}"}
            if self.errors[i]:
                res["ok"] = False
                res["feed_errors"] = self.errors[i]
            out.append({k: res.get(k) for k in ("name", "checked", "violations", "max_violations", "ok")}
                       | ({"feed_errors": res["feed_errors"]} if res.get("feed_errors") else {})
                       | {"module": stem})
        return out


class Comparison:
    """Pass 2's tallies (candidate rows joined to the baseline)."""

    def __init__(self, base: BaselineIndex, best_out: Optional[Path]):
        self.base = base
        self.matched = 0
        self.new_by_source: Counter = Counter()
        self.new_by_state: Counter = Counter()
        self.new_cov = Cov()
        self.new_tiers: Counter = Counter()
        self.ov_base = Cov()
        self.ov_cand = Cov()
        self.f_base: Counter = Counter()         # field -> overlapping rows whose baseline had it
        self.f_lost: Counter = Counter()
        self.f_changed: Counter = Counter()
        self.f_gained: Counter = Counter()
        self.s_base: Counter = Counter()
        self.s_lost: Counter = Counter()
        self.s_gained: Counter = Counter()
        self.samples = Samples()
        self.trans: Counter = Counter()
        self.hot_left_lost: Counter = Counter()
        self.hot_left_gained: Counter = Counter()
        self.hot_in_gained: Counter = Counter()
        self.hot_in_lost: Counter = Counter()
        self.hot_new_sigs: Counter = Counter()
        self.best: Counter = Counter()
        self.best_fh = open(best_out, "w") if best_out else None
        self.match_by: Counter = Counter()
        # live source -> matched rows whose candidate row carries another PRIMARY source (the merge
        # base flipped; the row is still there: attribution, not loss), and the pairs
        self.relabeled: Counter = Counter()
        self.relabeled_to: Counter = Counter()
        # rows HOT or WARM on BOTH boards: the like-for-like HOT+WARM lens (audit 2026-10-09,
        # regressions: on the d42058b3 run HOT+WARM grew by 13,554 new and 9,757 promoted rows and
        # 1,744 rows left the tier while staying on the board; the share over all HOT+WARM rows read
        # that churn as lost comps, divorce and lien checks that the rows in both still carried)
        self.hw_base = Cov()
        self.hw_cand = Cov()

    def close(self) -> None:
        if self.best_fh:
            self.best_fh.close()

    def add(self, f: Facts) -> None:
        b = self.base
        pick = None
        how = None
        for k in f.keys:
            cands = b.rows_for(_h8(k))
            if not cands:
                continue
            for i in cands:
                b.seen[i] = 1
            if pick is None:
                free = [i for i in cands if not b.matched[i]]
                if free:
                    if len(free) > 1:
                        # several live rows share this key (a parcel listed at two addresses, two
                        # sources on one parcel): prefer the one with the same street address, then
                        # the same source, so a shared key does not pair the wrong rows
                        av = f.fvals[1][0]
                        ah = _h4(av) if av is not None else 0
                        sidx = b.sources.idx.get(f.src)
                        free.sort(key=lambda i: (b.record(i)[6] != ah or not ah, b.record(i)[2] != sidx))
                    pick = free[0]
                    how = k.split(":", 1)[0]
        if pick is None:
            self.new_by_source[f.src] += 1
            self.new_by_state[f.st] += 1
            self.new_cov.add(_state(f.st), set(f.cols) | {"sig:" + s for s in f.sigs})
            self.new_tiers[TIERS[f.tier]] += 1
            self.trans[f"new->{TIERS[f.tier]}"] += 1
            if f.tier == 3:
                self.hot_new_sigs.update(f.sigs)
                self.samples.add("hot_new_row", f.ref)
            return
        b.matched[pick] = 1
        self.matched += 1
        self.match_by[how] += 1
        rec = b.record(pick)
        btier, _flags, _src, cty, good = rec[0], rec[1], rec[2], rec[3], rec[4]
        bh = rec[5:5 + NF]
        bcols = b.cols_of(rec[5 + NF])
        bsigs = b.sigs_of(rec[6 + NF])
        bst = _state(b.counties.items[cty][0])
        bref = b.refs[pick]
        bsrc = b.sources.items[_src]
        if bsrc != f.src:
            self.relabeled[bsrc] += 1
            self.relabeled_to[(bsrc, f.src)] += 1
        self.ov_base.add(bst, bcols | {"sig:" + s for s in bsigs})
        self.ov_cand.add(bst, set(f.cols) | {"sig:" + s for s in f.sigs})
        if btier >= 2 and f.tier >= 2:
            self.hw_base.add(bst, bcols | {"sig:" + s for s in bsigs})
            self.hw_cand.add(bst, set(f.cols) | {"sig:" + s for s in f.sigs})
        for i, name in enumerate(FIELDS):
            v, _g = f.fvals[i]
            hc = _h4(v) if v is not None else 0
            hb = bh[i]
            if hb:
                self.f_base[name] += 1
                if not hc:
                    self.f_lost[name] += 1
                    self.samples.add(f"lost:{name}", f.ref if f.ref[:2] != "h:" else bref)
                    if good >> i & 1:
                        self.best[name] += 1
                        if self.best_fh:
                            self.best_fh.write(json.dumps({"field": name, "candidate_ref": f.ref,
                                                           "baseline_ref": bref}) + "\n")
                elif hc != hb:
                    self.f_changed[name] += 1
                    self.samples.add(f"changed:{name}", f.ref)
            elif hc:
                self.f_gained[name] += 1
        for s in bsigs:
            self.s_base[s] += 1
        lost = bsigs - f.sigs
        gained = f.sigs - bsigs
        for s in lost:
            self.s_lost[s] += 1
            self.samples.add(f"signal_lost:{s}", f.ref)
        for s in gained:
            self.s_gained[s] += 1
        self.trans[f"{TIERS[btier]}->{TIERS[f.tier]}"] += 1
        if btier == 3 and f.tier != 3:
            self.hot_left_lost.update(lost)
            self.hot_left_gained.update(gained)
            self.samples.add("hot_left_tier", f.ref)
        elif btier != 3 and f.tier == 3:
            self.hot_in_gained.update(gained)
            self.hot_in_lost.update(lost)
            self.samples.add("hot_entered", f.ref)


# =================================================================================================
# Publish safety
# =================================================================================================

_DEPLOYED = ("listings_detail.json.gz", "listings_slim.json.gz", "run_meta.json", "run_health.json",
             "board.manifest.json", "foreclosure_sold_pool.json", "multifamily.json")
_PLAIN_TWINS = ("listings.json", "listings_detail.json", "listings_slim.json")


def _payload_rows(d: Path) -> list[tuple[str, int]]:
    rows = []
    for name in _DEPLOYED + ("listings.json.gz",):
        p = d / name
        if p.is_file():
            rows.append((name, p.stat().st_size))
    for p in BP.list_part_files(d):
        rows.append((p.name, p.stat().st_size))
    for sub in ("detail_shards", "parcel_photos"):
        sd = d / sub
        if sd.is_dir():
            for p in sorted(sd.rglob("*")):
                if p.is_file():
                    rows.append((f"{sub}/{p.relative_to(sd)}", p.stat().st_size))
    return rows


def _pages_decider() -> Optional[Callable[[str], bool]]:
    """check_pages_publish.decide() with docs/_config.yml's exclude/include, loaded the way
    .github/workflows/pages.yml loads it (by file path), so 'what Pages deploys' is the workflow's
    own answer."""
    try:
        spec = importlib.util.spec_from_file_location("cpp_for_compare", REPO / "scripts" / "check_pages_publish.py")
        cpp = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(cpp)
        return cpp
    except Exception:  # noqa: BLE001
        return None


def site_measure(d: Path) -> Optional[dict]:
    """What the Pages workflow's 'Measure the deployed site' step would count for docs dir `d` of a
    checkout: git-tracked files that Jekyll publishes (check_pages_publish.decide over
    docs/_config.yml), sizes on disk; plus every such file over GitHub's 50 MiB warning (one file
    can block a push or the publish commit). None when `d` is not a checkout's docs/."""
    try:
        d = d.resolve()
        if d.name != "docs" or not (d.parent / ".git").exists():
            return None
        out = subprocess.run(["git", "-C", str(d.parent), "ls-files", "-z", "docs"], capture_output=True,
                             timeout=60).stdout
    except (OSError, subprocess.SubprocessError):
        return None
    cpp = _pages_decider()
    try:
        exclude, include = cpp.parse_config((d / "_config.yml").read_text()) if cpp else ([], [])
    except OSError:
        exclude, include = [], []
    total = 0
    by_top: Counter = Counter()
    big = []
    for name in out.split(b"\0"):
        if not name:
            continue
        rel = name.decode("utf-8", "replace")[len("docs/"):]
        p = d / rel
        if not p.is_file():
            continue
        if cpp is not None and not cpp.decide(rel, exclude, include)[0]:
            continue
        sz = p.stat().st_size
        total += sz
        by_top[rel.split("/")[0] + "/" if "/" in rel else rel] += sz
        if sz / (1024 * 1024) >= WARN_MIB and not BP.is_part_name(rel):
            big.append({"path": "docs/" + rel, "mib": round(sz / (1024 * 1024), 1)})
    return {"bytes": total, "mb": round(total / 1e6, 1), "largest_entries_mb": {k: round(v / 1e6, 1) for k, v in by_top.most_common(8)},
            "files_over_warn": big,
            "how": "tracked docs/ files Jekyll publishes (check_pages_publish.decide), as .github/workflows/pages.yml measures"}


def _site_bytes_for(d: Path) -> tuple[Optional[int], str]:
    m = site_measure(d)
    if m is None:
        return None, "not a checkout's docs/: the rest of the site is not in this directory"
    return m["bytes"], m["how"]


def board_dir_safety(d: Path, rows_streamed: Optional[int], scan_derivatives: bool) -> dict:
    """The publish checks a board DIRECTORY must pass (problems -> HOLD; warnings -> notes)."""
    out: dict = {"kind": "board", "problems": [], "warnings": [], "info": []}
    man = BP.read_manifest(d)
    out["manifest"] = bool(man)
    vd = BP.verify_dir(d, verify=True)
    out["parts"] = {"ok": vd.get("ok"), "count": vd.get("parts"), "records": vd.get("records")}
    out["problems"] += [f"parts: {p}" for p in vd.get("problems", [])]
    count = (man or {}).get("count")
    if man:
        for k in ("detail_count", "slim_count"):
            if man.get(k) is not None and man.get(k) != count:
                out["problems"].append(f"manifest {k} {man.get(k)} != count {count}")
        sh = man.get("shards")
        if isinstance(sh, dict) and sh.get("records") is not None and sh.get("records") != count:
            out["problems"].append(f"manifest shards.records {sh.get('records')} != count {count}")
        if rows_streamed is not None and count is not None and rows_streamed != count:
            out["problems"].append(f"streamed {rows_streamed} rows, the manifest says {count}")
        # every deployed file the manifest names must match it (the plain twins are git-ignored and
        # never deployed: a stale local twin is information, not a defect of the published set)
        for name, ent in (man.get("files") or {}).items():
            p = d / name
            if not isinstance(ent, dict) or BP.is_part_name(name):
                continue
            if not p.is_file():
                (out["info"] if name in _PLAIN_TWINS else out["problems"]).append(f"{name}: in the manifest, missing on disk")
                continue
            bad = (ent.get("bytes") is not None and p.stat().st_size != ent["bytes"]) or \
                  (ent.get("sha256") and BP.sha256_file(p) != ent["sha256"])
            if bad:
                (out["info"] if name in _PLAIN_TWINS else out["problems"]).append(
                    f"{name}: size or sha256 differs from the manifest")
    else:
        out["warnings"].append("no board.manifest.json: the set cannot be verified as one write")
    try:
        detail_source(d)
    except BP.BoardIntegrityError as exc:
        out["problems"].append(f"detail sidecar: {exc}")
    except FileNotFoundError:
        out["problems"].append("no listings_detail.json(.gz) sidecar")
    for name in ("run_meta.json", BP.MANIFEST_NAME):
        p = d / name
        if p.is_file():
            try:
                json.loads(p.read_text())
            except ValueError as exc:
                out["problems"].append(f"{name}: not valid JSON ({exc})")
    try:
        rm = json.loads((d / "run_meta.json").read_text())
        if count is not None and rm.get("total") is not None and rm["total"] != count:
            out["problems"].append(f"run_meta total {rm['total']} != manifest count {count}")
        blk = rm.get("board_parts")
        mblk = BP.manifest_parts_block(man) if man else None
        if blk and mblk:
            a = [(e["name"], e["sha256"]) for e in BP.normalize_entries(blk)]
            b = [(e["name"], e["sha256"]) for e in BP.normalize_entries(mblk)]
            if a != b:
                out["problems"].append("run_meta board_parts differs from the manifest's parts")
    except (OSError, ValueError):
        pass
    except BP.BoardIntegrityError as exc:
        out["problems"].append(f"run_meta board_parts: {exc}")
    if scan_derivatives:
        p = d / "listings_slim.json.gz"
        if p.is_file():
            try:
                n = sum(1 for _ in BP.iter_gz_rows(p))
                out["slim_rows"] = n
                if man and man.get("slim_count") is not None and n != man["slim_count"]:
                    out["problems"].append(f"listings_slim.json.gz holds {n} rows, the manifest says {man['slim_count']}")
            except Exception as exc:  # noqa: BLE001 - gzip / JSON damage
                out["problems"].append(f"listings_slim.json.gz unreadable: {type(exc).__name__}")
        sd = d / "detail_shards"
        if sd.is_dir():
            recs = 0
            bad = 0
            for p in sorted(sd.glob("*.json.gz")):
                try:
                    recs += sum(1 for _ in BP.iter_gz_rows(p))       # streamed: a shard is never held whole
                except Exception:  # noqa: BLE001
                    bad += 1
            out["shard_records"] = recs
            if bad:
                out["problems"].append(f"{bad} detail shard(s) are not valid gzip JSON")
            sh = (man or {}).get("shards")
            if isinstance(sh, dict) and sh.get("records") is not None and recs != sh["records"]:
                out["problems"].append(f"detail shards hold {recs} records, the manifest says {sh['records']}")
    ev = CPS.evaluate(_payload_rows(d), WARN_MIB, GATE_MIB, PART_MAX_MIB)
    out["sizes"] = {"board_parts": ev.get("board_parts"),
                    "largest": [{k: f[k] for k in ("path", "mib", "status")} for f in ev["files"][:8]]}
    for f in ev["files"]:
        if f["status"] in ("BLOCK", "OVER_PART"):
            out["problems"].append(f"{f['path']}: {f['mib']} MiB ({f['status']}; gate {GATE_MIB:g} MiB, "
                                   f"part cap {PART_MAX_MIB:g} MiB)")
        elif f["status"] == "WARN":
            out["warnings"].append(f"{f['path']}: {f['mib']} MiB, over GitHub's {WARN_MIB:g} MiB warning")
    payload = sum(sz for _, sz in _payload_rows(d))
    out["payload_bytes"] = payload
    site = site_measure(d)
    out["site"] = site
    if site is not None:
        mb = site["mb"]
        if mb >= PAGES_FAIL_MB:
            out["problems"].append(f"Pages site {mb:.0f} MB >= {PAGES_FAIL_MB} MB: the Pages workflow's size step "
                                   f"fails the deploy (largest: {site['largest_entries_mb']})")
        elif mb >= PAGES_WARN_MB:
            out["warnings"].append(f"Pages site {mb:.0f} MB >= the {PAGES_WARN_MB} MB warning")
        for f in site["files_over_warn"]:
            if f["path"].endswith(tuple(_DEPLOYED)):
                continue                                  # already judged above
            (out["problems"] if f["mib"] >= GATE_MIB else out["warnings"]).append(
                f"{f['path']}: {f['mib']} MiB (GitHub warns at {WARN_MIB:g}, the repo gate is {GATE_MIB:g}, "
                "GitHub refuses 100)")
    return out


def checkpoint_safety(b: BoardInput, est: Optional[dict], baseline_dir: Optional[Path]) -> dict:
    out: dict = {"kind": "checkpoint", "problems": [], "warnings": [], "info": []}
    m = b.ckpt_manifest
    out["manifest"] = {k: m.get(k) for k in ("phase", "count", "saved_at", "origin", "resumed_from")}
    out["age_hours"] = None if b.ckpt_age_h is None else round(b.ckpt_age_h, 1)
    if m.get("phase") != CK.PRE_PUBLISH:
        out["problems"].append(f"checkpoint phase is {m.get('phase')!r}, not {CK.PRE_PUBLISH!r}: the board is "
                               "not the scored board --publish-only publishes (its tiers are the prior run's or none)")
    if b.ckpt_state_problem:
        out["problems"].append(f"publish inputs: {b.ckpt_state_problem}")
    if b.ckpt_age_h is not None and m.get("phase") == CK.PRE_PUBLISH and b.ckpt_age_h > CK.PRE_PUBLISH_MAX_AGE_H:
        out["problems"].append(f"checkpoint is {b.ckpt_age_h:.0f} h old: vm_resume.sh --publish-only refuses "
                               f"one over {CK.PRE_PUBLISH_MAX_AGE_H:g} h")
    cnt = m.get("count")
    if isinstance(cnt, int) and cnt > 0:
        short = cnt - b.rows_read
        out["rows_not_read"] = short
        if short > cnt * CHECKPOINT_ROW_LOSS_MAX:
            out["problems"].append(f"{short} of {cnt} checkpoint rows did not load (over "
                                   f"{CHECKPOINT_ROW_LOSS_MAX:.1%}): truncated file or rows that do not validate")
        elif short:
            out["warnings"].append(f"{short} checkpoint rows did not validate (checkpoint.load drops them too)")
    if est:
        mib = 1024 * 1024
        parts_n = math.ceil(est["parts_gz_bytes"] / (BP.DEFAULT_PART_MAX_BYTES * BP.TARGET_FILL)) or 1
        out["estimate"] = {
            "rows": est["rows"],
            "bytes": {k: est[k] for k in ("parts_gz_bytes", "detail_gz_bytes", "slim_gz_bytes", "shards_gz_bytes")},
            "board_parts_total_mib": round(est["parts_gz_bytes"] / mib, 1),
            "board_parts_count_about": parts_n,
            "listings_detail_json_gz_mib": round(est["detail_gz_bytes"] / mib, 1),
            "listings_slim_json_gz_mib": round(est["slim_gz_bytes"] / mib, 1),
            "detail_shards_total_mib": round(est["shards_gz_bytes"] / mib, 1),
            "how": "one gzip-9 stream per file family over the rows write_artifact would write; parts "
                   "are cut under the 24 MiB cap by the writer, so only their total is estimated",
        }
        for name, key in (("listings_detail.json.gz", "detail_gz_bytes"), ("listings_slim.json.gz", "slim_gz_bytes")):
            v = est[key] / mib
            if v >= GATE_MIB:
                out["problems"].append(f"{name} would be about {v:.0f} MiB (>= the {GATE_MIB:g} MiB gate; one file)")
            elif v >= WARN_MIB:
                out["warnings"].append(f"{name} would be about {v:.0f} MiB (over GitHub's {WARN_MIB:g} MiB warning)")
        if baseline_dir is not None:
            site, how = _site_bytes_for(baseline_dir)
            if site is not None:
                now_payload = sum(sz for name, sz in _payload_rows(baseline_dir)
                                  if BP.is_part_name(name) or name.startswith("detail_shards/")
                                  or name in ("listings_detail.json.gz", "listings_slim.json.gz"))
                new_payload = est["parts_gz_bytes"] + est["detail_gz_bytes"] + est["slim_gz_bytes"] + est["shards_gz_bytes"]
                site_est = site - now_payload + new_payload
                out["estimate"]["pages_site_mb_about"] = round(site_est / 1e6, 1)
                if site_est / 1e6 >= PAGES_FAIL_MB:
                    out["problems"].append(f"Pages site would be about {site_est / 1e6:.0f} MB (>= {PAGES_FAIL_MB} MB: the build fails)")
                elif site_est / 1e6 >= PAGES_WARN_MB:
                    out["warnings"].append(f"Pages site would be about {site_est / 1e6:.0f} MB (>= the {PAGES_WARN_MB} MB warning)")
    else:
        out["info"].append("sizes not estimated (--no-size-estimate)")
    return out


# =================================================================================================
# Process and structure
# =================================================================================================

_EVENT_RE = re.compile(r'"event": "([^"]+)"')
#: events whose numeric fields are kept (named filters, merge, scoring, write); every other event
#: is only counted by name. Strings are never kept except the few listed in _KEEP_STR.
_NUMERIC_EVENTS = (
    "orchestrator.start", "orchestrator.role_filtered", "orchestrator.in_scope", "orchestrator.flip_filtered",
    "orchestrator.deduped", "orchestrator.dedupe2", "orchestrator.scope_repass", "orchestrator.oceanfront_repass",
    "orchestrator.drop_countyless_national", "orchestrator.grandfather_restored",
    "orchestrator.situs_sanity_nulled", "orchestrator.partitioned", "orchestrator.count_drop_alert",
    "orchestrator.validated", "board_persist.done", "reo_freshness.done", "distress_score.done",
    "web_artifact.written", "verification_apply.applied", "checkpoint.saved", "checkpoint.loaded",
    "resume.stage", "orchestrator.prior_correction",
)
_KEEP_STR = {"phase", "stage", "status", "mode"}
#: rows a named filter removed: (event, field) -> filter name in the report
_FILTERS = {
    ("orchestrator.in_scope", "pruned"): "in_scope (footprint)",
    ("orchestrator.flip_filtered", "pruned"): "flip_filtered (flip footprint / coast)",
    ("orchestrator.deduped", "pruned"): "dedupe (first pass)",
    ("orchestrator.dedupe2", "collapsed"): "dedupe2 (after the prior merge)",
    ("orchestrator.scope_repass", "dropped"): "scope_repass (_denied_now)",
    ("orchestrator.oceanfront_repass", "dropped"): "oceanfront_repass",
    ("orchestrator.drop_countyless_national", "dropped"): "drop_countyless_national",
    ("board_persist.done", "aged_out_terminal"): "merge_prior_board aged_out_terminal",
    ("board_persist.done", "aged_out_misses"): "merge_prior_board aged_out_misses",
    ("reo_freshness.done", "pruned"): "prune_stale_reo",
    ("orchestrator.grandfather_restored", "restored"): "GRANDFATHER restore (added back)",
}


def _numeric(d: dict) -> dict:
    out = {}
    for k, v in d.items():
        if k in ("event", "level", "timestamp"):
            continue
        if isinstance(v, bool) or isinstance(v, (int, float)):
            out[k] = v
        elif isinstance(v, str) and k in _KEEP_STR:
            out[k] = v[:60]
        elif isinstance(v, dict):
            sub = {}
            for k2, v2 in v.items():
                if isinstance(v2, (int, float)) and not isinstance(v2, bool):
                    sub[str(k2)[:60]] = v2
                elif isinstance(v2, dict):
                    sub2 = {str(a)[:40]: b for a, b in v2.items() if isinstance(b, (int, float)) and not isinstance(b, bool)}
                    if sub2:
                        sub[str(k2)[:60]] = sub2
            out[k] = sub            # an empty dict is a recorded zero (reo_freshness pruned {})
    return out


def parse_run_log(paths: Iterable[Path]) -> dict:
    """Facts from a vm-run / vm-resume log: numbers and code identifiers only (never a message,
    a sample array or an address)."""
    res: dict = {"files": [], "events": {}, "event_counts": Counter(), "checkpoints": [], "time_capped": [],
                 "failed_events": Counter(), "skipped_events": Counter(), "source_all_filtered": {},
                 "first_ts": None, "last_ts": None, "header": {}}
    for path in paths:
        p = Path(path)
        if not p.is_file():
            res["files"].append({"name": p.name, "missing": True})
            continue
        res["files"].append({"name": p.name, "bytes": p.stat().st_size})
        with open(p, "r", encoding="utf-8", errors="replace") as fh:
            for line in fh:
                if line.startswith("==>"):
                    _parse_banner(line, res["header"])
                    continue
                m = _EVENT_RE.search(line)
                if not m:
                    continue
                ev = m.group(1)
                res["event_counts"][ev] += 1
                ts = re.search(r'"timestamp": "([^"]+)"', line)
                if ts:
                    t = ts.group(1)
                    res["first_ts"] = t if not res["first_ts"] or t < res["first_ts"] else res["first_ts"]
                    res["last_ts"] = t if not res["last_ts"] or t > res["last_ts"] else res["last_ts"]
                if ev.endswith(".failed") or ev.endswith("_failed"):
                    res["failed_events"][ev] += 1
                if "skipped" in ev:
                    res["skipped_events"][ev] += 1
                if ev in _NUMERIC_EVENTS or ev == "enrich.time_capped" or ev.endswith(".time_capped") \
                        or ev == "orchestrator.source_all_filtered":
                    try:
                        d = json.loads(line)
                    except ValueError:
                        continue
                    if ev == "enrich.time_capped" or ev.endswith(".time_capped"):
                        res["time_capped"].append(str(d.get("phase") or ev)[:60])
                    elif ev == "orchestrator.source_all_filtered":
                        res["source_all_filtered"][str(d.get("source"))[:120]] = d.get("scraped")
                    elif ev == "checkpoint.saved":
                        res["checkpoints"].append({"phase": d.get("phase"), "leads": d.get("leads"),
                                                   "seconds": d.get("seconds"), "at": d.get("timestamp")})
                    else:
                        res["events"].setdefault(ev, []).append(_numeric(d))
    res["event_counts"] = dict(res["event_counts"].most_common(60))
    res["failed_events"] = dict(res["failed_events"].most_common(30))
    res["skipped_events"] = dict(res["skipped_events"])
    # per-phase seconds: run start -> first checkpoint -> ... -> last event
    marks = [("start", res["first_ts"])] + [(c["phase"], c["at"]) for c in res["checkpoints"]] + [("end", res["last_ts"])]
    phases = []
    for (a, ta), (b, tb) in zip(marks, marks[1:]):
        da, db = _parse_dt(ta), _parse_dt(tb)
        if da and db:
            phases.append({"from": a, "to": b, "seconds": round((db - da).total_seconds())})
    res["phase_seconds"] = phases
    filt: dict = {}
    for (ev, fld), name in _FILTERS.items():
        for d in res["events"].get(ev, []):
            v = d.get(fld)
            if isinstance(v, dict):
                v = sum(x for x in v.values() if isinstance(x, (int, float)))
            if isinstance(v, (int, float)):
                filt[name] = filt.get(name, 0) + v
    res["named_filters"] = filt
    return res


def _parse_banner(line: str, hdr: dict) -> None:
    s = line[3:].strip()
    m = re.match(r"code at ([0-9a-f]{6,40})( \(pinned\))?", s)
    if m:
        hdr["code_pin"] = m.group(1)
        hdr["pinned"] = bool(m.group(2))
        return
    m = re.match(r"VM (run|resume) (\S+)\s+(.*)", s)
    if m:
        hdr["job"] = m.group(1)
        hdr["stamp"] = m.group(2)
        for k, v in re.findall(r"(\w+)=(\S+)", m.group(3)):
            if k in ("role", "vision", "stop_before_publish", "mode"):
                hdr[k] = v[:40]
        return
    m = re.match(r"exit=(\d+)\s+elapsed=(\d+)m", s)
    if m:
        hdr["exit"] = int(m.group(1))
        hdr["elapsed_min"] = int(m.group(2))
        return
    m = re.match(r"stealth hand-off: ([0-9a-f]{6,40}) (\S+)", s)
    if m:
        hdr["handoff_commit"] = m.group(1)
        hdr["handoff_date"] = m.group(2)
        return
    if "COUNT-DROP" in s:
        hdr["count_drop_alert"] = True
    m = re.match(r"total listings this run: (\d+)", s)
    if m:
        hdr["total_listings"] = int(m.group(1))


def parse_memlog(path: Path) -> dict:
    out: dict = {"file": Path(path).name}
    p = Path(path)
    if not p.is_file():
        out["missing"] = True
        return out
    peak_total = peak_rss = 0
    killed = []
    with open(p, "r", encoding="utf-8", errors="replace") as fh:
        for line in fh:
            if line.startswith("#"):
                m = re.search(r"rss\+swap > (\d+) MB", line)
                if m:
                    out["kill_total_mb"] = int(m.group(1))
                continue
            if line.startswith("PEAK"):
                out["peak_line"] = {k: int(v) for k, v in re.findall(r"(\w+)_mb=(\d+)", line)}
                continue
            if line.startswith("KILLED"):
                killed.append(line[:120].strip())
                continue
            rss = re.search(r"rss_mb=(\d+)", line)
            sw = re.search(r"swap_mb=(\d+)", line)
            if rss:
                r = int(rss.group(1))
                t = r + (int(sw.group(1)) if sw else 0)
                peak_rss = max(peak_rss, r)
                peak_total = max(peak_total, t)
    out["peak_total_mb"] = (out.get("peak_line") or {}).get("total", peak_total)
    out["peak_rss_mb"] = (out.get("peak_line") or {}).get("rss", peak_rss)
    out["killed"] = killed
    return out


_PROFILE_PREFIXES = ("FORECLOSURE_", "ASSESSOR_", "STREETVIEW_", "BOARD_", "VISION_", "SKIP_TRACE_", "LOG_LEVEL")
_PROFILE_DENY = re.compile(r"EMAIL|SENDER|RECIPIENT|KEY|TOKEN|PASSWORD|SECRET|SHEET", re.I)


def profile_facts() -> dict:
    """The run profile as THIS checkout declares it: deploy/oracle/run_profile.json (the pre-run
    gate's intended profile) when present, and vm_lib.sh's exported defaults. The run's EFFECTIVE
    environment is not recorded anywhere (see should_record)."""
    out: dict = {}
    rp = REPO / "deploy" / "oracle" / "run_profile.json"
    if rp.is_file():
        try:
            d = json.loads(rp.read_text())
            out["declared_profile"] = d.get("profile")
            out["declared_flags"] = {k: v for k, v in (d.get("flags") or {}).items() if not _PROFILE_DENY.search(k)}
        except ValueError:
            out["declared_profile"] = "unreadable"
    lib = REPO / "deploy" / "oracle" / "vm_lib.sh"
    if lib.is_file():
        flags = {}
        for k, v in re.findall(r'export (\w+)="\$\{\1:-([^}]*)\}"', lib.read_text()):
            if k.startswith(_PROFILE_PREFIXES) and not _PROFILE_DENY.search(k):
                flags[k] = v
        out["vm_lib_defaults"] = flags
    return out


def _git(cwd: Path, *args: str) -> Optional[str]:
    try:
        r = subprocess.run(["git", "-C", str(cwd), *args], capture_output=True, text=True, timeout=20)
        return r.stdout.strip() or None if r.returncode == 0 else None
    except (OSError, subprocess.SubprocessError):
        return None


def process_facts(b: BoardInput, stats: BoardStats, log_paths: list[Path], memlog: Optional[Path],
                  state_path: Optional[Path]) -> dict:
    f: dict = {"kind": b.kind, "dir": b.path.name}
    state: dict = {}
    if b.kind == "checkpoint":
        m = b.ckpt_manifest
        f["checkpoint"] = {k: m.get(k) for k in ("phase", "count", "saved_at", "elapsed_s", "origin", "resumed_from")}
        state = b.ckpt_state or {}
    else:
        try:
            rm = json.loads((b.path / "run_meta.json").read_text())
        except (OSError, ValueError):
            rm = {}
        st = rm.get("source_status") or {}
        f["run_meta"] = {
            "run_time": rm.get("run_time"), "total": rm.get("total"),
            "notes": str(rm.get("notes") or "")[:300],
            "health_stale": rm.get("health_stale"), "health_age_hours": rm.get("health_age_hours"),
            "errors": len(rm.get("errors") or []), "regressions": len(rm.get("regressions") or []),
            "source_status": dict(Counter("ALARM" if "ALARM" in str(v) else ("OK" if str(v).startswith("OK") else "other")
                                          for v in st.values())),
        }
        f["sources_ran"] = len(rm.get("by_source") or {})
        f["by_source_rows"] = rm.get("by_source") or {}
        try:
            dd = b.path.resolve()
            if (dd / BP.MANIFEST_NAME).is_file() and (dd.parent / ".git").exists():
                f["publish_commit"] = _git(dd.parent, "log", "-1", "--format=%h %cI", "--",
                                           f"{dd.name}/{BP.MANIFEST_NAME}")
        except OSError:
            pass
    if state_path and Path(state_path).is_file():
        try:
            state = json.loads(Path(state_path).read_text())
        except ValueError:
            state = {}
        f["state_file"] = Path(state_path).name
    if state:
        s = state.get("summary") or {}
        f["state"] = {
            "scoring_failed": state.get("scoring_failed"),
            "publish": state.get("publish"),
            "errors": len(state.get("errors") or []),
            "summary_total": s.get("total"),
            "regressions": len(s.get("regressions") or []),
            "source_alarms": len(s.get("source_alarms") or {}),
            "off_footprint_removed": s.get("off_footprint_removed"),
            "count_drop_alert": bool(s.get("count_drop_alert")),
            "notes": str(s.get("notes") or "")[:300],
        }
        es = state.get("enrichment_stats") or {}
        f["enrichers_recorded"] = sorted(es.keys())
        if s.get("code_pin"):                      # recorded by main.run_enrich_tail once wired
            f["state_code_pin"] = str(s["code_pin"])[:40]
        if isinstance(s.get("run_env"), dict):
            f["run_env"] = {k: str(v)[:80] for k, v in s["run_env"].items() if not _PROFILE_DENY.search(k)}
        if s.get("by_source"):
            f["sources_ran"] = len(s["by_source"])
            f["by_source_rows"] = s["by_source"]
    f["log"] = parse_run_log(log_paths) if log_paths else None
    f["mem"] = parse_memlog(memlog) if memlog else None
    f["selfcheck"] = stats.selfcheck
    f["audit"] = stats.audit
    f["audit_note"] = stats.audit_note
    f["unscored_rows"] = stats.unscored
    f["verification"] = {s: {"rows": stats.ver_rows[s], "newest_checked_at": stats.ver_newest.get(s),
                             "verdicts": dict(stats.ver_verdicts[s])} for s in sorted(stats.ver_rows)}
    lg = f["log"] or {}
    hdr = lg.get("header") or {}
    f["code_pin"] = hdr.get("code_pin") or f.get("state_code_pin")
    f["named_filters"] = lg.get("named_filters") or None
    f["phase_seconds"] = lg.get("phase_seconds") or None
    f["peak_mem_mb"] = (f["mem"] or {}).get("peak_total_mb")
    not_rec = []
    for k, label in (("code_pin", "commit pin (only the run log's '==> code at' line has it)"),
                     ("phase_seconds", "per-phase seconds (only the run log's checkpoint events)"),
                     ("peak_mem_mb", "peak memory (only the watchdog's .mem.log)"),
                     ("named_filters", "rows dropped by each named filter (only the run log)")):
        if not f.get(k):
            not_rec.append(label)
    if not f.get("enrichers_recorded"):
        not_rec.append("which enrichers ran (enrichment_stats lives in resume_state.json, not in run_meta.json)")
    if not f.get("run_env"):
        not_rec.append("the run's effective FORECLOSURE_* environment (only vm_lib.sh defaults are known)")
    not_rec.append("board_selfcheck and audit_suite results at the time of the run (computed here instead)")
    f["not_recorded"] = not_rec
    return f


def process_flags(me: dict, other: dict) -> list[str]:
    """What is wrong with how THIS board was produced, judged against the other where needed."""
    out = []
    if me.get("unscored_rows"):
        out.append(f"{me['unscored_rows']:,} rows carry no HOT/WARM/COLD tier (a path bypassed the scorer)")
    ck = me.get("checkpoint") or {}
    if me["kind"] == "checkpoint" and ck.get("phase") != CK.PRE_PUBLISH:
        out.append(f"checkpoint phase {ck.get('phase')!r}: the scoring tail has not run on it")
    st = me.get("state") or {}
    if st.get("scoring_failed"):
        out.append(f"scoring_failed is set ({str(st['scoring_failed'])[:80]})")
    if st.get("count_drop_alert"):
        out.append("the run raised a count-drop alert")
    rm = me.get("run_meta") or {}
    if rm.get("health_stale"):
        out.append("run_meta says the scrape health is stale")
    a, b = set(me.get("enrichers_recorded") or ()), set(other.get("enrichers_recorded") or ())
    if a and b and (b - a):
        out.append(f"{len(b - a)} enricher(s) recorded stats on the other board's run but not on this one: "
                   + ", ".join(sorted(b - a)[:12]))
    mv, ov = me.get("verification") or {}, other.get("verification") or {}
    older = []
    for sig, v in ov.items():
        mine = (mv.get(sig) or {}).get("newest_checked_at")
        theirs = v.get("newest_checked_at")
        dm, dt = _parse_dt(mine), _parse_dt(theirs)
        if dt and (dm is None or (dt - dm).total_seconds() > LEDGER_STALE_DAYS * 86400):
            older.append(sig)
    if older:
        out.append(f"scored on older verification ledgers than the other board for: {', '.join(sorted(older)[:12])}")
    lg = me.get("log") or {}
    if lg.get("time_capped"):
        out.append(f"{len(lg['time_capped'])} phase(s) hit their time cap: {', '.join(sorted(set(lg['time_capped']))[:10])}")
    mem = me.get("mem") or {}
    if mem.get("killed"):
        out.append("the memory watchdog killed the job")
    elif mem.get("peak_total_mb") and mem.get("kill_total_mb") and \
            mem["peak_total_mb"] >= PEAK_MEM_NOTE_FRACTION * mem["kill_total_mb"]:
        out.append(f"peak memory {mem['peak_total_mb']:,} MB is within {100 - PEAK_MEM_NOTE_FRACTION * 100:.0f}% "
                   f"of the {mem['kill_total_mb']:,} MB kill line")
    sc = me.get("selfcheck") or []
    br = [i["name"] for i in sc if not i.get("ok")]
    if br:
        out.append(f"board_selfcheck breaches: {', '.join(br)}")
    au = me.get("audit") or []
    nok = [i["name"] for i in au if not i.get("ok")]
    if nok:
        out.append(f"audit checks not ok: {', '.join(nok[:10])}")
    return out


# =================================================================================================
# Report assembly
# =================================================================================================

def _pct(a: float, b: float) -> Optional[float]:
    return round(100.0 * a / b, 2) if b else None


def _accepted(name: str, accepted: Iterable[str]) -> bool:
    for a in accepted:
        if a == name or (a.endswith("*") and name.startswith(a[:-1])):
            return True
    return False


#: The defaults file of accepted drops (audit 2026-10-09, regressions): intended corrections that the
#: owner or an audit accepted, each with its reason and a BOUND (max_loss rows), so the comparison shows
#: only real findings and a bigger loss of the same column still holds. docs/audit_2026-10-09/
#: accepted_drops.md explains each entry. --accept-file replaces it, --no-accept-file ignores it.
ACCEPT_FILE = REPO / "docs" / "board_versions" / "accepted_drops.json"


def load_accept_file(path: Optional[Path]) -> list[dict]:
    """[{kind: source|coverage|field, name, state?, max_loss?, reason}] from the defaults file; an entry
    without a reason is ignored (an acceptance must say why)."""
    if not path or not Path(path).is_file():
        return []
    try:
        doc = json.loads(Path(path).read_text())
    except (OSError, ValueError):
        return []
    out = []
    for e in doc.get("entries") or []:
        if isinstance(e, dict) and e.get("kind") in ("source", "coverage", "field") and e.get("name") \
                and str(e.get("reason") or "").strip():
            out.append(e)
    return out


def accept_reason(args, kind: str, name: str, loss: int, state: str = "ALL") -> Optional[str]:
    """Why a blocker of this kind and name does not block, or None: a command-line accept flag
    (unbounded), else a defaults-file entry whose state matches (absent = any) and whose max_loss
    (absent = any) covers `loss` rows."""
    flags = {"source": getattr(args, "accept_source_drop", []), "coverage": getattr(args, "accept_coverage_drop", []),
             "field": getattr(args, "accept_field_loss", [])}[kind]
    if _accepted(name, flags):
        return f"accepted with --accept-{ {'source': 'source-drop', 'coverage': 'coverage-drop', 'field': 'field-loss'}[kind]}"
    for e in getattr(args, "accept_entries", None) or []:
        if e["kind"] != kind or not _accepted(name, [e["name"]]):
            continue
        if e.get("state") and e["state"] != state:
            continue
        mx = e.get("max_loss")
        if mx is not None and loss > int(mx):
            continue
        return f"accepted ({ACCEPT_FILE.name if not getattr(args, 'accept_file', None) else Path(args.accept_file).name}): {e['reason']}"
    return None


def coverage_section(bs: BoardStats, cs: BoardStats, cmp: Comparison, missing_cov: Cov, missing_hw: Cov,
                     accept: list[str], args=None) -> tuple[list[dict], list[dict], list[dict]]:
    """Per column and signal, per state: counts first, then the three shares; a class for each.
    Returns (rows, blockers, notes)."""
    names = set(COLUMNS)
    for cov in (bs.cov_all, cs.cov_all):
        for s in cov.c.values():
            names.update(k for k in s if k.startswith("sig:"))
    rows, blockers, notes = [], [], []
    for state in ("ALL", "NC", "SC", "other"):
        nb, nc = bs.cov_all.n[state], cs.cov_all.n[state]
        if not nb and not nc:
            continue
        hb, hc = bs.cov_hw.n[state], cs.cov_hw.n[state]
        ob, oc = cmp.ov_base.n[state], cmp.ov_cand.n[state]
        for col in sorted(names, key=lambda c: (c.startswith("sig:"), COL_BIT.get(c, 999), c)):
            b, c = bs.cov_all.c[state][col], cs.cov_all.c[state][col]
            if not b and not c:
                continue
            hwb, hwc = bs.cov_hw.c[state][col], cs.cov_hw.c[state][col]
            ovb, ovc = cmp.ov_base.c[state][col], cmp.ov_cand.c[state][col]
            r = {"state": state, "column": col, "count": [b, c],
                 "share_all": [_pct(b, nb), _pct(c, nc)],
                 "share_hotwarm": [_pct(hwb, hb), _pct(hwc, hc)],
                 "count_both": [ovb, ovc], "share_both": [_pct(ovb, ob), _pct(ovc, oc)],
                 "left_with_rows": missing_cov.c[state][col], "came_with_new_rows": cmp.new_cov.c[state][col]}
            lfl = (r["share_both"][1] - r["share_both"][0]) if ob >= LENS_MIN_ROWS and None not in r["share_both"] else None
            alls = (r["share_all"][1] - r["share_all"][0]) if None not in r["share_all"] else None
            d = c - b
            why = []
            if lfl is not None and lfl < -COVERAGE_DROP_PP:
                why.append(f"rows in both: {r['share_both'][0]}% -> {r['share_both'][1]}% ({ovb:,} -> {ovc:,} rows)")
            # the HOT+WARM lens is judged on the rows HOT or WARM on BOTH boards (like for like): new
            # hot leads arriving without the value, rows promoted from COLD and rows leaving the tier or
            # the board move the share over all HOT+WARM rows (dilution, the tiers and rows sections'
            # business) without a single row losing it. Measured on the d42058b3 run: comps 40.77% ->
            # 26.63% over all HOT+WARM rows, 39.15% -> 38.87% on the 43,201 rows HOT+WARM on both.
            nhw = cmp.hw_base.n[state]
            hbb, hbc = cmp.hw_base.c[state][col], cmp.hw_cand.c[state][col]
            r["count_hotwarm_both"] = [hbb, hbc]
            r["share_hotwarm_both"] = [_pct(hbb, nhw), _pct(hbc, nhw)]
            if nhw >= LENS_MIN_ROWS and None not in r["share_hotwarm_both"] and \
                    r["share_hotwarm_both"][1] - r["share_hotwarm_both"][0] < -COVERAGE_DROP_PP:
                why.append(f"rows HOT+WARM on both boards: {r['share_hotwarm_both'][0]}% -> "
                           f"{r['share_hotwarm_both'][1]}% ({hbb:,} -> {hbc:,} of {nhw:,} rows)")
            if why:
                cls = "regression"
            elif abs(d) <= max(FLAT_MIN_ROWS, FLAT_REL * max(b, 1)):
                cls = "flat"
            elif d > 0:
                cls = "dilution" if (alls is not None and alls < -COVERAGE_DROP_PP) else "improved"
                if cls == "dilution":
                    why.append(f"count up {b:,} -> {c:,}; share of all rows {r['share_all'][0]}% -> "
                               f"{r['share_all'][1]}% because the board grew")
            else:
                cls = "rows_left"
                why.append(f"count down {b:,} -> {c:,}: {r['left_with_rows']:,} rows with it left the board, "
                           f"{r['came_with_new_rows']:,} came with new rows; like-for-like held")
            r["class"] = cls
            r["why"] = "; ".join(why)
            rows.append(r)
            if cls == "regression":
                item = {"section": "coverage", "name": f"{state}:{col}",
                        "detail": r["why"], "threshold": f"a drop of more than {COVERAGE_DROP_PP} percentage "
                        f"points on the like-for-like or HOT+WARM lens (each judged on at least {LENS_MIN_ROWS} rows)"}
                loss = max(ovb - ovc, r["count_hotwarm_both"][0] - r["count_hotwarm_both"][1])
                why_ok = (accept_reason(args, "coverage", col, loss, state) if args is not None
                          else ("accepted with --accept-coverage-drop" if _accepted(col, accept) else None))
                if col.startswith("sig:") or why_ok:
                    item["why_not_blocking"] = ("a signal: verification removes refuted or stale signals on purpose"
                                                if col.startswith("sig:") else why_ok)
                    notes.append(item)
                else:
                    blockers.append(item)
    return rows, blockers, notes


def build_report(args, base_in: BoardInput, cand_in: BoardInput, bs: BoardStats, cs: BoardStats,
                 bidx: BaselineIndex, cmp: Comparison, base_safety: dict, cand_safety: dict,
                 pf_base: dict, pf_cand: dict, timing: dict) -> dict:
    blockers: list[dict] = []
    notes: list[dict] = []
    if cs.read_error:
        blockers.append({"section": "publish_safety", "name": "candidate_unreadable", "detail": cs.read_error,
                         "threshold": "every row must stream (manifest, parts, sidecar and gzip intact)"})

    # ---------------------------------------------------------------- 1 rows
    miss_reason: Counter = Counter()
    miss_by_source: dict[str, Counter] = defaultdict(Counter)
    miss_by_state: Counter = Counter()
    miss_tier: Counter = Counter()
    miss_cov = Cov()
    miss_cov_hw = Cov()
    hot_gone: Counter = Counter()
    rsamples = Samples()
    cand_sources = set(cs.by_source)
    for i in range(bidx.n):
        if bidx.matched[i]:
            continue
        rec = bidx.record(i)
        tier, flags, src_i, cty = rec[0], rec[1], rec[2], rec[3]
        src = bidx.sources.items[src_i]
        st = bidx.counties.items[cty][0]
        if bidx.seen[i]:
            reason = "folded_into_another_row"
        elif src not in cand_sources:
            reason = "source_gone_from_candidate"
        elif flags & F_TERMINAL:
            reason = "aged_out_terminal"
        elif flags & F_MISSES:
            reason = "aged_out_miss_limit"
        elif flags & F_COUNTYLESS:
            reason = "filter_drop_countyless_national"
        elif flags & F_REO_SNAPSHOT:
            reason = "filter_prune_stale_reo"
        elif flags & F_SALE_PASSED:
            reason = "filter_active_only_sale_window"
        else:
            reason = "unexplained"
        miss_reason[reason] += 1
        miss_by_source[src][reason] += 1
        miss_by_state[st] += 1
        miss_tier[TIERS[tier]] += 1
        cmp.trans[f"{TIERS[tier]}->left"] += 1
        mcols = bidx.cols_of(rec[5 + NF]) | {"sig:" + s for s in bidx.sigs_of(rec[6 + NF])}
        miss_cov.add(_state(st), mcols)
        if tier >= 2:
            miss_cov_hw.add(_state(st), mcols)
        rsamples.add(reason, bidx.refs[i])
        if tier == 3:
            hot_gone[reason] += 1
            rsamples.add("hot_left_board", bidx.refs[i])
    flagged_sources = []
    relabel_notes = []
    for src, nb in sorted(bs.by_source.items(), key=lambda kv: -kv[1]):
        nc = cs.by_source.get(src, 0)
        # A live row of `src` still on the candidate under another PRIMARY source (the merge base
        # flipped: main.run() collected scraper results from an unordered set until 2026-10-09) is
        # attribution, not loss: judge the source on the rows it still HOLDS, i.e. its live rows
        # minus the missing ones plus its new ones (audit 2026-10-09, regressions: buncombe_
        # delinquent_tax 1,182 -> 827, multi_year_delinquent_tax 1,115 -> 436, kania 177 -> 150
        # and sc_catalis 63 -> 53 were all relabels with 0 or 1 rows missing).
        missing_n = sum(miss_by_source.get(src, {}).values())
        held = nb - missing_n + cmp.new_by_source.get(src, 0)
        relab = cmp.relabeled.get(src, 0)
        if nc < nb * SOURCE_DROP_RATIO and held >= nb * SOURCE_DROP_RATIO and relab:
            to = {t: n for (s, t), n in cmp.relabeled_to.most_common() if s == src}
            relabel_notes.append({"section": "rows", "name": f"relabeled:{src}",
                                  "detail": f"{nb:,} -> {nc:,} rows under this primary source, but {held:,} of its "
                                            f"rows are on the candidate ({relab:,} under another primary source: "
                                            f"{dict(list(to.items())[:5])}); attribution, not loss"})
        if held >= nb * SOURCE_DROP_RATIO:
            continue
        item = {"source": src, "baseline": nb, "candidate": nc, "held": held, "relabeled": relab,
                "ratio": round(held / nb, 3) if nb else None,
                "missing_by_reason": dict(miss_by_source.get(src, {}))}
        flagged_sources.append(item)
        entry = {"section": "rows", "name": f"source:{src}",
                 "detail": f"{nb:,} -> {held:,} rows held ({'zero' if held <= 0 else f'{100 * held / nb:.0f}%'}; "
                           f"{nc:,} under this primary source, {relab:,} relabeled); missing rows by "
                           f"reason: {dict(miss_by_source.get(src, {}))}",
                 "threshold": f"under {SOURCE_DROP_RATIO:.0%} of the live count with at least "
                              f"{SOURCE_MIN_BASELINE_ROWS} live rows"}
        why_ok = accept_reason(args, "source", src, nb - held)
        if why_ok:
            entry["why_not_blocking"] = why_ok
            notes.append(entry)
        elif nb >= SOURCE_MIN_BASELINE_ROWS:
            blockers.append(entry)
        else:
            entry["why_not_blocking"] = f"fewer than {SOURCE_MIN_BASELINE_ROWS} live rows"
            notes.append(entry)
    notes.extend(relabel_notes)
    if bs.n and cs.n < bs.n * TOTAL_ROWS_MIN_RATIO:
        blockers.append({"section": "rows", "name": "total_rows",
                         "detail": f"{bs.n:,} -> {cs.n:,} rows ({100 * cs.n / bs.n:.1f}%)",
                         "threshold": f"the candidate keeps at least {TOTAL_ROWS_MIN_RATIO:.0%} of the live rows"})
    if miss_reason.get("unexplained"):
        notes.append({"section": "rows", "name": "unexplained_missing_rows",
                      "detail": f"{miss_reason['unexplained']:,} live rows are missing with no reason the row shows "
                                "(see by_source_and_reason and the process section's named-filter counts)"})
    rows = {
        "baseline_total": bs.n, "candidate_total": cs.n, "matched": cmp.matched,
        "matched_by_key": dict(cmp.match_by), "fused_keys_not_used_for_matching": bidx.fused_keys,
        "missing_from_candidate": bidx.n - cmp.matched, "new_in_candidate": cs.n - cmp.matched,
        "by_state": {"baseline": dict(bs.by_state), "candidate": dict(cs.by_state)},
        "by_county": {"baseline": dict(bs.by_county), "candidate": dict(cs.by_county)},
        "by_source": {"baseline": dict(bs.by_source), "candidate": dict(cs.by_source)},
        "missing_by_reason": dict(miss_reason),
        "missing_by_source_and_reason": {s: dict(c) for s, c in sorted(miss_by_source.items(), key=lambda kv: -sum(kv[1].values()))},
        "missing_by_state": dict(miss_by_state),
        "new_by_source": dict(cmp.new_by_source.most_common()),
        "new_by_state": dict(cmp.new_by_state),
        "sources_flagged": flagged_sources,
        "samples": rsamples.d,
        "reason_buckets": {
            "folded_into_another_row": "one of its identity keys is on a candidate row joined to another live row (dedupe / merge fold)",
            "source_gone_from_candidate": "its source has no row at all in the candidate (scraper failed, disabled or filtered whole)",
            "aged_out_terminal": "board_persist._is_terminal_dict: sold, confirmed, upset deadline passed or sale over a year ago",
            "aged_out_miss_limit": f"raw.pulled_sale.consecutive_misses reached PULLED_RETENTION_WEEKS ({PULLED_RETENTION_WEEKS})",
            "filter_drop_countyless_national": "national.* / reo.* with no county: main's orchestrator.drop_countyless_national",
            "filter_prune_stale_reo": "a snapshot REO source: enrichment_reo_freshness.prune_stale_reo",
            "filter_active_only_sale_window": "sale date past the state's upset window: main._active_only",
            "unexplained": "none of the above shows on the row",
        },
    }

    # ---------------------------------------------------------------- 2 coverage
    cov_rows, cov_block, cov_notes = coverage_section(bs, cs, cmp, miss_cov, miss_cov_hw, args.accept_coverage_drop, args)
    blockers += cov_block
    notes += cov_notes

    # ---------------------------------------------------------------- 3 fields
    fields = []
    for name in FIELDS:
        had = cmp.f_base[name]
        lost, chg = cmp.f_lost[name], cmp.f_changed[name]
        r = {"field": name, "overlap_rows_with_value": had, "lost": lost, "changed": chg,
             "gained": cmp.f_gained[name], "lost_pct": _pct(lost, had), "changed_pct": _pct(chg, had),
             "lost_good_values": cmp.best[name],
             "sample_lost": cmp.samples.get(f"lost:{name}"), "sample_changed": cmp.samples.get(f"changed:{name}")}
        fields.append(r)
        if had >= FIELD_MIN_ROWS and r["lost_pct"] is not None and r["lost_pct"] > FIELD_LOST_MAX_PCT:
            item = {"section": "fields", "name": f"lost:{name}",
                    "detail": f"{lost:,} of {had:,} rows in both lost their {name} ({r['lost_pct']}%)",
                    "threshold": f"more than {FIELD_LOST_MAX_PCT}% of the overlapping rows that had it (at least {FIELD_MIN_ROWS})"}
            why_ok = accept_reason(args, "field", name, lost)
            if why_ok:
                item["why_not_blocking"] = why_ok
                notes.append(item)
            else:
                blockers.append(item)
        if had >= FIELD_MIN_ROWS and r["changed_pct"] is not None and r["changed_pct"] > FIELD_CHANGED_NOTE_PCT:
            notes.append({"section": "fields", "name": f"changed:{name}",
                          "detail": f"{chg:,} of {had:,} rows in both changed their {name} ({r['changed_pct']}%)",
                          "threshold": f"noted above {FIELD_CHANGED_NOTE_PCT}%"})
    signals = []
    for s in sorted(set(cmp.s_base) | set(cmp.s_gained), key=lambda x: -cmp.s_base[x]):
        had = cmp.s_base[s]
        r = {"signal": s, "overlap_rows_with_signal": had, "lost": cmp.s_lost[s], "gained": cmp.s_gained[s],
             "lost_pct": _pct(cmp.s_lost[s], had), "sample_lost": cmp.samples.get(f"signal_lost:{s}")}
        signals.append(r)
        if had >= FIELD_MIN_ROWS and r["lost_pct"] is not None and r["lost_pct"] > SIGNAL_LOST_NOTE_PCT:
            notes.append({"section": "fields", "name": f"signal_lost:{s}",
                          "detail": f"{cmp.s_lost[s]:,} of {had:,} rows in both lost the {s} signal ({r['lost_pct']}%)",
                          "threshold": f"noted above {SIGNAL_LOST_NOTE_PCT}% (verification removes signals on purpose)"})

    # ---------------------------------------------------------------- 4 tiers
    tiers = {
        "baseline": {t: bs.tiers.get(t, 0) for t in ("HOT", "WARM", "COLD", "none")},
        "candidate": {t: cs.tiers.get(t, 0) for t in ("HOT", "WARM", "COLD", "none")},
        "transitions": dict(sorted(cmp.trans.items())),
        "hot_left_tier": {"rows": sum(v for k, v in cmp.trans.items() if k.startswith("HOT->") and k not in ("HOT->HOT", "HOT->left")),
                          "signals_lost": dict(cmp.hot_left_lost.most_common(25)),
                          "signals_gained": dict(cmp.hot_left_gained.most_common(25)),
                          "sample": cmp.samples.get("hot_left_tier")},
        "hot_left_board": {"rows": sum(hot_gone.values()), "by_reason": dict(hot_gone), "sample": rsamples.get("hot_left_board")},
        "hot_entered": {"rows": sum(v for k, v in cmp.trans.items() if k.endswith("->HOT") and not k.startswith(("HOT", "new"))),
                        "signals_gained": dict(cmp.hot_in_gained.most_common(25)),
                        "signals_lost": dict(cmp.hot_in_lost.most_common(25)),
                        "sample": cmp.samples.get("hot_entered")},
        "hot_new_rows": {"rows": cmp.trans.get("new->HOT", 0), "signals": dict(cmp.hot_new_sigs.most_common(25)),
                         "sample": cmp.samples.get("hot_new_row")},
    }
    if cs.n and cs.unscored > max(0, cs.n * UNSCORED_MAX_FRACTION):
        blockers.append({"section": "tiers", "name": "unscored_rows",
                         "detail": f"{cs.unscored:,} candidate rows carry no HOT/WARM/COLD tier",
                         "threshold": f"at most {UNSCORED_MAX_FRACTION:.1%} of rows (audit check pipeline-row-scored)"})
    hb, hc = bs.tiers.get("HOT", 0), cs.tiers.get("HOT", 0)
    if hb != hc:
        notes.append({"section": "tiers", "name": "hot_count", "detail": f"HOT {hb:,} -> {hc:,}"})

    # ---------------------------------------------------------------- 5 invariants
    inv = {"selfcheck": None, "audit": None, "audit_note": cs.audit_note or bs.audit_note}
    if bs.selfcheck is not None and cs.selfcheck is not None:
        bmap = {i["name"]: i for i in bs.selfcheck}
        sc_rows = []
        for i in cs.selfcheck:
            b = bmap.get(i["name"], {})
            sc_rows.append({"name": i["name"], "baseline": b.get("count"), "candidate": i["count"],
                            "baseline_ok": b.get("ok"), "candidate_ok": i["ok"]})
            if not i["ok"] and b.get("ok", True):
                blockers.append({"section": "invariants", "name": f"selfcheck:{i['name']}",
                                 "detail": f"{b.get('count')} -> {i['count']} (newly breached)",
                                 "threshold": f"must be {i.get('must_be', 0)}; a breach the live board does not have"})
            elif not i["ok"] and i["count"] > (b.get("count") or 0):
                notes.append({"section": "invariants", "name": f"selfcheck:{i['name']}",
                              "detail": f"{b.get('count')} -> {i['count']} (breached on both, larger on the candidate)"})
        inv["selfcheck"] = sc_rows
    if bs.audit is not None and cs.audit is not None:
        bmap = {i["name"]: i for i in bs.audit}
        a_rows = []
        for i in cs.audit:
            b = bmap.get(i["name"], {})
            a_rows.append({"name": i["name"], "module": i.get("module"), "baseline_violations": b.get("violations"),
                           "candidate_violations": i["violations"], "max_violations": i["max_violations"],
                           "baseline_ok": b.get("ok"), "candidate_ok": i["ok"]})
            if not i["ok"] and b.get("ok", True):
                blockers.append({"section": "invariants", "name": f"audit:{i['name']}",
                                 "detail": f"{b.get('violations')} -> {i['violations']} violations (newly not ok)",
                                 "threshold": f"at most {i['max_violations']} (the check's own max_violations)"})
            elif (i["violations"] or 0) > (b.get("violations") or 0):
                notes.append({"section": "invariants", "name": f"audit:{i['name']}",
                              "detail": f"{b.get('violations')} -> {i['violations']} violations"})
        inv["audit"] = a_rows

    # ---------------------------------------------------------------- 6 publish safety
    heir = {"baseline": {"violations": dict(bs.heir_bad), "notes": dict(bs.heir_note)},
            "candidate": {"violations": dict(cs.heir_bad), "notes": dict(cs.heir_note),
                          "sample": cs.heir_samples.d}}
    nbad = sum(v for k, v in cs.heir_bad.items())
    if nbad > HEIR_VIOLATIONS_MAX:
        blockers.append({"section": "publish_safety", "name": "heir_publishing_rule",
                         "detail": f"{nbad:,} violations: {dict(cs.heir_bad)}",
                         "threshold": "none allowed: only PUBLISHABLE_HEIR_RELATIONS, no phone, e-mail, age or minor"})
    for k, v in cs.heir_note.items():
        notes.append({"section": "publish_safety", "name": f"heir_note:{k}",
                      "detail": f"{v:,} rows publish {k.replace('rows_with_', '')} (names with no relation; "
                                "owner-decision territory, outside the heir_candidates rule)"})
    for p in cand_safety.get("problems", []):
        blockers.append({"section": "publish_safety", "name": "artifact", "detail": p,
                         "threshold": "every payload file intact, aligned and under the documented limits"})
    for w in cand_safety.get("warnings", []):
        notes.append({"section": "publish_safety", "name": "artifact", "detail": w})
    safety = {"candidate": cand_safety, "baseline": base_safety, "heir": heir}

    # ---------------------------------------------------------------- 7 process
    fl_b, fl_c = process_flags(pf_base, pf_cand), process_flags(pf_cand, pf_base)
    for x in fl_c:
        if x not in fl_b:
            notes.append({"section": "process", "name": "candidate_process", "detail": x})
    if (pf_cand.get("state") or {}).get("scoring_failed"):
        blockers.append({"section": "process", "name": "scoring_failed",
                         "detail": str(pf_cand["state"]["scoring_failed"])[:200],
                         "threshold": "the scorer must have run on the candidate"})
    better = ("candidate" if len(fl_c) < len(fl_b) else "baseline" if len(fl_b) < len(fl_c) else "even")
    process = {"baseline": pf_base, "candidate": pf_cand,
               "flags": {"baseline": fl_b, "candidate": fl_c},
               "fewer_process_flags": better,
               "profile": profile_facts(),
               "should_record": sorted(set(pf_base.get("not_recorded", [])) | set(pf_cand.get("not_recorded", [])))}

    # ---------------------------------------------------------------- 8 verdict
    verdict = "HOLD" if blockers else ("PASS_WITH_NOTES" if notes else "PASS")
    by_class = Counter(r["class"] for r in cov_rows if r["state"] == "ALL")
    best = {"lost_good_values_by_field": dict(cmp.best), "total": sum(cmp.best.values()),
            "file": Path(args.best_of_both_out).name if args.best_of_both_out else None,
            "sample": {f: cmp.samples.get(f"lost:{f}")[:5] for f in FIELDS if cmp.best[f]}}
    return {
        "schema": "compare-boards-v1",
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "label": args.label,
        "baseline": {"kind": base_in.kind, "dir": base_in.path.name, "rows": bs.n,
                     "run_time": _iso(base_in.run_time())},
        "candidate": {"kind": cand_in.kind, "dir": cand_in.path.name, "rows": cs.n,
                      "run_time": _iso(cand_in.run_time())},
        "verdict": verdict,
        "blockers": blockers,
        "notes": notes,
        "coverage_classes_all_states": dict(by_class),
        "thresholds": {k: v for k, v in globals().items() if k.isupper() and isinstance(v, (int, float))
                       and k in _THRESHOLD_NAMES},
        "rows": rows,
        "coverage": cov_rows,
        "fields": fields,
        "signals": signals,
        "tiers": tiers,
        "invariants": inv,
        "publish_safety": safety,
        "process": process,
        "best_of_both": best,
        "timing": timing,
    }


_THRESHOLD_NAMES = {"SOURCE_DROP_RATIO", "SOURCE_MIN_BASELINE_ROWS", "TOTAL_ROWS_MIN_RATIO", "COVERAGE_DROP_PP",
                    "LENS_MIN_ROWS", "FLAT_REL", "FLAT_MIN_ROWS", "FIELD_LOST_MAX_PCT", "FIELD_MIN_ROWS",
                    "FIELD_CHANGED_NOTE_PCT", "SIGNAL_LOST_NOTE_PCT", "SAMPLE_IDS", "HEIR_VIOLATIONS_MAX",
                    "CHECKPOINT_ROW_LOSS_MAX", "UNSCORED_MAX_FRACTION", "PEAK_MEM_NOTE_FRACTION",
                    "LEDGER_STALE_DAYS", "WARN_MIB", "GATE_MIB", "PART_MAX_MIB", "PAGES_WARN_MB",
                    "PAGES_FAIL_MB", "FUSION_THRESHOLD"}


def _iso(d: Optional[datetime]) -> Optional[str]:
    return d.isoformat(timespec="seconds") if d else None


# =================================================================================================
# Markdown, ledger, changelog
# =================================================================================================

def _n(v: Any) -> str:
    return f"{v:,}" if isinstance(v, int) else str(v)


def render_markdown(rep: dict) -> str:
    b, c = rep["baseline"], rep["candidate"]
    L = [f"# Board comparison: {rep['label']} vs the live board", "",
         f"Baseline: {b['kind']} `{b['dir']}`, {_n(b['rows'])} rows (run {b['run_time']}). "
         f"Candidate: {c['kind']} `{c['dir']}`, {_n(c['rows'])} rows (run {c['run_time']}).", "",
         f"## Verdict: {rep['verdict']}", ""]
    if rep["verdict"] == "HOLD":
        L.append("Do not publish the candidate as it is. Keep the live board until each blocker below is fixed "
                 "or explicitly accepted, and use the best-of-both list to carry back what the live board has.")
    elif rep["verdict"] == "PASS_WITH_NOTES":
        L.append("The candidate is not worse on anything that blocks a publish. Read the notes before publishing.")
    else:
        L.append("The candidate is at least as good as the live board on everything measured.")
    L.append("")
    if rep["blockers"]:
        L += ["### Blockers (each with the line it crossed)", ""]
        for x in rep["blockers"]:
            L.append(f"- [{x['section']}] {x['name']}: {x['detail']}. Threshold: {x.get('threshold', '')}.")
        L.append("")
    if rep["notes"]:
        L += ["### Notes", ""]
        for x in rep["notes"][:60]:
            extra = f" ({x['why_not_blocking']})" if x.get("why_not_blocking") else ""
            L.append(f"- [{x['section']}] {x['name']}: {x['detail']}{extra}")
        if len(rep["notes"]) > 60:
            L.append(f"- ... and {len(rep['notes']) - 60} more in the JSON")
        L.append("")
    r = rep["rows"]
    L += ["## 1. Rows", "",
          f"{_n(r['baseline_total'])} live rows, {_n(r['candidate_total'])} candidate rows; {_n(r['matched'])} in both "
          f"(joined by {r['matched_by_key']}), {_n(r['missing_from_candidate'])} live rows missing from the candidate, "
          f"{_n(r['new_in_candidate'])} new.", "",
          f"Missing rows by reason: {r['missing_by_reason']}.", ""]
    if r["sources_flagged"]:
        L.append("Sources under 90% of their live count (or gone):")
        for s in r["sources_flagged"][:25]:
            held = f" ({_n(s['held'])} held, {_n(s.get('relabeled', 0))} relabeled)" if "held" in s else ""
            L.append(f"- {s['source']}: {_n(s['baseline'])} -> {_n(s['candidate'])}{held}")
        L.append("")
    L += ["## 2. Coverage (row counts first)", "",
          "| column | rows (live -> candidate) | share of all rows | share of HOT+WARM | share of rows in both | class |",
          "|---|---|---|---|---|---|"]
    keyset = ("address", "parcel_id", "owner_name", "phone", "email", "assessed_value", "comps", "sqft",
              "x_mailing_address", "x_tax_balance", "x_tax_years_late", "lt_tax_lien", "two_year_delinquent",
              "tax_aging_surfaced", "heir_estate", "probate", "divorce", "deed_chain_has_history",
              "atty_legal_description", "atty_deed_ref", "atty_heir_candidates")
    for row in rep["coverage"]:
        if row["state"] != "ALL":
            continue
        if row["column"] in keyset or row["class"] == "regression":
            L.append(f"| {row['column']} | {_n(row['count'][0])} -> {_n(row['count'][1])} | "
                     f"{row['share_all'][0]}% -> {row['share_all'][1]}% | {row['share_hotwarm'][0]}% -> "
                     f"{row['share_hotwarm'][1]}% | {row['share_both'][0]}% -> {row['share_both'][1]}% | {row['class']} |")
    L += ["", f"All states, every column and signal: {rep['coverage_classes_all_states']}. Per-state rows are in the JSON.", "",
          "## 3. Fields on rows present in both", "",
          "| field | rows that had it | lost | changed | gained |", "|---|---|---|---|---|"]
    for f in rep["fields"]:
        L.append(f"| {f['field']} | {_n(f['overlap_rows_with_value'])} | {_n(f['lost'])} ({f['lost_pct']}%) | "
                 f"{_n(f['changed'])} ({f['changed_pct']}%) | {_n(f['gained'])} |")
    top_sig = [s for s in rep["signals"] if s["lost"]][:12]
    if top_sig:
        L += ["", "Signals lost on rows in both: " + ", ".join(f"{s['signal']} {_n(s['lost'])} of {_n(s['overlap_rows_with_signal'])}"
                                                           for s in top_sig) + "."]
    t = rep["tiers"]
    L += ["", "## 4. Tiers", "",
          f"Live: {t['baseline']}. Candidate: {t['candidate']}.", "",
          f"HOT rows that dropped a tier: {_n(t['hot_left_tier']['rows'])} (signals lost: {t['hot_left_tier']['signals_lost']}). "
          f"HOT rows gone from the board: {_n(t['hot_left_board']['rows'])} ({t['hot_left_board']['by_reason']}). "
          f"Rows that became HOT: {_n(t['hot_entered']['rows'])} (signals gained: {t['hot_entered']['signals_gained']}). "
          f"New HOT rows: {_n(t['hot_new_rows']['rows'])}.", "",
          "## 5. Invariants", ""]
    inv = rep["invariants"]
    if inv["selfcheck"]:
        for i in inv["selfcheck"]:
            L.append(f"- selfcheck {i['name']}: {i['baseline']} -> {i['candidate']}"
                     f"{'' if i['candidate_ok'] else ' (BREACHED)'}")
    if inv["audit"]:
        for i in inv["audit"]:
            L.append(f"- audit {i['name']}: {i['baseline_violations']} -> {i['candidate_violations']} "
                     f"(max {i['max_violations']}){'' if i['candidate_ok'] else ' (NOT OK)'}")
    elif inv.get("audit_note"):
        L.append(f"- audit checks: {inv['audit_note']}")
    ps = rep["publish_safety"]
    L += ["", "## 6. Publish safety", "",
          f"Candidate artifact problems: {len(ps['candidate'].get('problems', []))}; warnings: "
          f"{len(ps['candidate'].get('warnings', []))}. Heir rule violations: {ps['heir']['candidate']['violations'] or 'none'}."]
    if ps["candidate"].get("estimate"):
        L.append(f"Estimated published sizes: {ps['candidate']['estimate']}.")
    elif ps["candidate"].get("sizes"):
        L.append(f"Sizes: {ps['candidate']['sizes'].get('board_parts')}.")
    pr = rep["process"]
    L += ["", "## 7. Process and structure", "",
          f"Fewer process flags: {pr['fewer_process_flags']}.", ""]
    for side in ("baseline", "candidate"):
        p = pr[side]
        L.append(f"- {side}: code pin {p.get('code_pin') or 'not recorded'}; peak memory "
                 f"{p.get('peak_mem_mb') or 'not recorded'} MB; unscored rows {_n(p.get('unscored_rows'))}; "
                 f"flags: {pr['flags'][side] or 'none'}")
    L += ["", "Not recorded by the runs (should be from now on): " + "; ".join(pr["should_record"]) + ".", "",
          "## 8. Best of both", "",
          f"{_n(rep['best_of_both']['total'])} good values the live board holds were lost by the candidate, by field: "
          f"{rep['best_of_both']['lost_good_values_by_field']}. Ids in `{rep['best_of_both']['file']}` (fix candidates "
          "for the merge).", ""]
    return "\n".join(L) + "\n"


def ledger_record(rep: dict) -> dict:
    cov = {r["column"]: {k: r[k] for k in ("count", "share_all", "share_hotwarm", "share_both", "class")}
           for r in rep["coverage"] if r["state"] == "ALL"}
    return {"schema": "board-version-v1", "generated_at": rep["generated_at"], "label": rep["label"],
            "baseline": rep["baseline"], "candidate": rep["candidate"], "verdict": rep["verdict"],
            "blockers": [{k: x.get(k) for k in ("section", "name", "detail")} for x in rep["blockers"]],
            "notes": len(rep["notes"]),
            "rows": {k: rep["rows"][k] for k in ("baseline_total", "candidate_total", "matched",
                                                  "missing_from_candidate", "new_in_candidate", "missing_by_reason")},
            "tiers": {k: rep["tiers"][k] for k in ("baseline", "candidate")},
            "fields": {f["field"]: {k: f[k] for k in ("overlap_rows_with_value", "lost", "changed", "gained")}
                       for f in rep["fields"]},
            "coverage": cov,
            "process_flags": rep["process"]["flags"],
            "best_of_both_total": rep["best_of_both"]["total"]}


def write_ledger(rep: dict, ledger_dir: Path, date_s: str) -> Path:
    ledger_dir.mkdir(parents=True, exist_ok=True)
    label = re.sub(r"[^A-Za-z0-9_.-]+", "_", rep["label"])[:60] or "candidate"
    p = ledger_dir / f"{date_s}_{label}.json"
    k = 2
    while p.exists():
        p = ledger_dir / f"{date_s}_{label}_{k}.json"
        k += 1
    p.write_text(json.dumps(ledger_record(rep), indent=1, default=str) + "\n")
    return p


_HUMAN = {"address": "street address", "parcel_id": "parcel id", "owner_name": "owner name", "phone": "phone",
          "email": "email", "assessed_value": "assessed value", "lot_size": "lot size", "sqft": "living area",
          "comps": "comps", "x_mailing_address": "mailing address", "x_tax_balance": "tax balance",
          "x_tax_years_late": "late tax years", "lt_tax_lien": "tax-lien flag", "lt_tax_sale": "tax-sale flag",
          "lt_distressed": "\"distressed\" flag", "tax_aging_surfaced": "tax aging surfaced",
          "deed_chain_has_history": "deed chain with history", "heir_estate": "heir/estate",
          "lt_estate_lead": "estate lead", "lt_divorce_notice": "divorce notice"}


def changelog_entry(rep: dict, ledger_path: Optional[Path]) -> str:
    """One entry in docs/board_versions/CHANGELOG.md's style: counts first, then the classes."""
    b, c = rep["baseline"], rep["candidate"]
    rows = [r for r in rep["coverage"] if r["state"] == "ALL" and not r["column"].startswith("sig:")]

    def fmt(r):
        nm = _HUMAN.get(r["column"], r["column"].replace("_", " "))
        return f"{nm} {r['count'][0]:,} -> {r['count'][1]:,}"

    def pick(cls, n=18):
        sel = sorted((r for r in rows if r["class"] == cls), key=lambda r: -max(r["count"]))
        return sel[:n]
    imp, flat, dil, left, reg = pick("improved"), pick("flat", 10), pick("dilution", 12), pick("rows_left", 12), pick("regression", 30)
    cd = (c["run_time"] or "")[:10] or rep["generated_at"][:10]
    bd = (b["run_time"] or "")[:10]
    L = [f"## {cd} board ({rep['label']}, {c['rows']:,} rows) vs {bd} board ({b['rows']:,} rows)",
         f"Source: scripts/compare_boards.py" + (f", record docs/board_versions/{ledger_path.name}" if ledger_path else "")
         + f". Verdict {rep['verdict']}. Rows with the value, {bd} -> {cd}:", ""]
    L.append("Improved: " + ("; ".join(fmt(r) for r in imp) or "none") + ".")
    L.append("")
    L.append("Flat: " + ("; ".join(fmt(r) for r in flat) or "none") + ".")
    L.append("")
    dl = [f"{_HUMAN.get(r['column'], r['column'])} {r['share_all'][0]}% -> {r['share_all'][1]}% of all rows "
          f"({r['count'][0]:,} -> {r['count'][1]:,} rows)" for r in dil]
    dl += [f"{_HUMAN.get(r['column'], r['column'])} {r['count'][0]:,} -> {r['count'][1]:,} (rows that left the board; "
           f"rows in both {r['share_both'][0]}% -> {r['share_both'][1]}%)" for r in left]
    L.append("Looked like regressions but are dilution or rows leaving: " + ("; ".join(dl) or "none") + ".")
    L.append("")
    rl = [f"{_HUMAN.get(r['column'], r['column'])}: {r['why']}" for r in reg]
    rl += [f"{x['name']}: {x['detail']}" for x in rep["blockers"] if x["section"] != "coverage"]
    L.append("Real regressions: " + ("; ".join(rl) or "none") + ".")
    L.append("")
    L.append("Defects found later: none recorded yet (add them here when found).")
    return "\n".join(L) + "\n"


def append_changelog(path: Path, entry: str) -> None:
    text = path.read_text() if path.is_file() else "# Board versions: what improved and what regressed, iteration to iteration\n"
    if not text.endswith("\n"):
        text += "\n"
    path.write_text(text + "\n" + entry)


# =================================================================================================
# main
# =================================================================================================

def _peak_rss_mb() -> float:
    r = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    return round(r / (1024 * 1024) if sys.platform == "darwin" else r / 1024, 1)


def compare(args) -> dict:
    if not getattr(args, "accept_entries", None):
        # the defaults file was measured against the live board: read it when the baseline IS the
        # live board (docs/), or when --accept-file names one
        live = Path(args.baseline).resolve() == (REPO / "docs").resolve()
        if getattr(args, "no_accept_file", False):
            args.accept_entries = []
        elif getattr(args, "accept_file", None):
            args.accept_entries = load_accept_file(Path(args.accept_file))
        else:
            args.accept_entries = load_accept_file(ACCEPT_FILE) if live else []
    audit_b = AuditFeed(not args.no_audit_checks, Path(args.checks_dir) if args.checks_dir else None)
    dk = audit_b.detail_keys
    base_in = BoardInput(Path(args.baseline), args.baseline_kind, detail_keys=dk)
    cand_in = BoardInput(Path(args.candidate), args.candidate_kind, detail_keys=dk,
                         estimate_sizes=not args.no_size_estimate)
    ref_time = (cand_in.run_time() or datetime.now(timezone.utc).replace(tzinfo=None))
    timing: dict = {}

    # ---- pass 1: the baseline
    t0 = time.monotonic()
    bidx = BaselineIndex()
    bs = BoardStats("baseline")

    def on_base(rec: dict) -> None:
        f = Facts(rec, ref_time)
        bidx.add(f)
        bs.add(rec, f.st, f.co, f.src, f.tier, f.sigs, f.cols)
        audit_b.feed(rec)

    try:
        bs.selfcheck = _drive(base_in.rows(), on_base, not args.no_selfcheck)
    except BP.BoardIntegrityError as exc:
        raise SystemExit(f"the baseline board is not intact, nothing to compare against: {exc}")
    bs.audit = audit_b.finish()
    bs.audit_note = audit_b.note
    bidx.finish()
    timing["baseline_pass_s"] = round(time.monotonic() - t0, 1)
    timing["peak_rss_mb_after_baseline"] = _peak_rss_mb()
    print(f"baseline: {bs.n:,} rows in {timing['baseline_pass_s']}s, peak RSS {timing['peak_rss_mb_after_baseline']} MB",
          file=sys.stderr)

    # ---- pass 2: the candidate
    t0 = time.monotonic()
    audit_c = AuditFeed(not args.no_audit_checks, Path(args.checks_dir) if args.checks_dir else None)
    cs = BoardStats("candidate")
    cmp = Comparison(bidx, Path(args.best_of_both_out) if args.best_of_both_out else None)

    def on_cand(rec: dict) -> None:
        f = Facts(rec, ref_time)
        cmp.add(f)
        cs.add(rec, f.st, f.co, f.src, f.tier, f.sigs, f.cols)
        audit_c.feed(rec)

    try:
        cs.selfcheck = _drive(cand_in.rows(), on_cand, not args.no_selfcheck)
    except (BP.BoardIntegrityError, OSError, EOFError, ValueError, zlib.error) as exc:
        cs.read_error = f"{type(exc).__name__}: {str(exc)[:300]} (after {cand_in.rows_read:,} rows)"
        cs.selfcheck = None
    finally:
        cmp.close()
    cs.audit = audit_c.finish() if not cs.read_error else None
    cs.audit_note = audit_c.note
    timing["candidate_pass_s"] = round(time.monotonic() - t0, 1)
    timing["peak_rss_mb"] = _peak_rss_mb()
    print(f"candidate: {cs.n:,} rows in {timing['candidate_pass_s']}s, peak RSS {timing['peak_rss_mb']} MB",
          file=sys.stderr)

    # ---- publish safety + process
    t0 = time.monotonic()
    est = cand_in.estimator.finish() if cand_in.estimator else None
    if cand_in.kind == "board":
        cand_safety = board_dir_safety(cand_in.path, None if cs.read_error else cand_in.rows_read,
                                       not args.skip_artifact_scan)
    else:
        cand_safety = checkpoint_safety(cand_in, est, base_in.path if base_in.kind == "board" else None)
    if base_in.kind == "board":
        base_safety = board_dir_safety(base_in.path, base_in.rows_read, scan_derivatives=False)
    else:
        base_safety = checkpoint_safety(base_in, None, None)
    pf_base = process_facts(base_in, bs, [Path(p) for p in args.baseline_log],
                            Path(args.baseline_memlog) if args.baseline_memlog else None,
                            Path(args.baseline_state) if args.baseline_state else None)
    pf_cand = process_facts(cand_in, cs, [Path(p) for p in args.candidate_log],
                            Path(args.candidate_memlog) if args.candidate_memlog else None,
                            Path(args.candidate_state) if args.candidate_state else None)
    timing["safety_and_process_s"] = round(time.monotonic() - t0, 1)
    return build_report(args, base_in, cand_in, bs, cs, bidx, cmp, base_safety, cand_safety,
                        pf_base, pf_cand, timing)


def main(argv: Optional[list[str]] = None) -> int:
    ap = argparse.ArgumentParser(description="Compare a candidate board with the live one (counts only).")
    ap.add_argument("--baseline", default=str(REPO / "docs"), help="the live board dir (default docs/) or a checkpoint dir")
    ap.add_argument("--candidate", default=None, help="a board dir or a checkpoint dir (data/checkpoint)")
    ap.add_argument("--baseline-kind", default="auto", choices=("auto", "board", "checkpoint"))
    ap.add_argument("--candidate-kind", default="auto", choices=("auto", "board", "checkpoint"))
    ap.add_argument("--out", default=None, help="the JSON report")
    ap.add_argument("--from-report", default=None, metavar="REPORT.json",
                    help="no passes: write the ledger record / changelog entry (and --md) from a report "
                         "made earlier (e.g. on the VM, copied here)")
    ap.add_argument("--md", default=None, help="the markdown verdict (default: --out with .md)")
    ap.add_argument("--best-of-both-out", default=None,
                    help="JSON lines of lost good values, ids only (default: --out with .best_of_both.jsonl)")
    ap.add_argument("--label", default="candidate", help="a short name for the candidate (ledger file name)")
    ap.add_argument("--baseline-log", action="append", default=[], help="the run log that produced the baseline")
    ap.add_argument("--candidate-log", action="append", default=[], help="the run log(s) that produced the candidate")
    ap.add_argument("--baseline-memlog", default=None)
    ap.add_argument("--candidate-memlog", default=None)
    ap.add_argument("--baseline-state", default=None, help="a resume_state.json for the baseline's run")
    ap.add_argument("--candidate-state", default=None, help="a resume_state.json for the candidate (default: the checkpoint's own)")
    ap.add_argument("--accept-source-drop", action="append", default=[], metavar="SLUG",
                    help="an intended source drop (exact slug, or a prefix ending in *): a note, not a blocker")
    ap.add_argument("--accept-coverage-drop", action="append", default=[], metavar="COLUMN")
    ap.add_argument("--accept-field-loss", action="append", default=[], metavar="FIELD")
    ap.add_argument("--accept-file", default=None, metavar="JSON",
                    help=f"accepted drops with reasons and bounds (default {ACCEPT_FILE.relative_to(REPO)})")
    ap.add_argument("--no-accept-file", action="store_true", help="ignore the accepted-drops defaults file")
    ap.add_argument("--no-size-estimate", action="store_true", help="checkpoint: skip the gzip size estimate")
    ap.add_argument("--no-selfcheck", action="store_true")
    ap.add_argument("--no-audit-checks", action="store_true")
    ap.add_argument("--checks-dir", default=None, help="audit checks dir (default scripts/audit_checks)")
    ap.add_argument("--skip-artifact-scan", action="store_true", help="do not re-read slim and shards")
    ap.add_argument("--ledger-dir", default=str(REPO / "docs" / "board_versions"))
    ap.add_argument("--no-ledger", action="store_true", help="write no docs/board_versions record")
    ap.add_argument("--append-changelog", action="store_true",
                    help="append the human entry to <ledger-dir>/CHANGELOG.md")
    ap.add_argument("--date", default=None, help="date for the ledger file name (default today, UTC)")
    args = ap.parse_args(argv)
    date_s = args.date or datetime.now(timezone.utc).strftime("%Y-%m-%d")
    if args.from_report:
        rep = json.loads(Path(args.from_report).read_text())
        if args.label != "candidate":
            rep["label"] = args.label
        ledger_path = None if args.no_ledger else write_ledger(rep, Path(args.ledger_dir), date_s)
        if args.append_changelog:
            append_changelog(Path(args.ledger_dir) / "CHANGELOG.md", changelog_entry(rep, ledger_path))
        if args.md:
            Path(args.md).write_text(render_markdown(rep))
        print(f"verdict {rep['verdict']} (from {Path(args.from_report).name})"
              + (f"; ledger {ledger_path}" if ledger_path else "")
              + ("; changelog entry appended" if args.append_changelog else ""))
        return 1 if rep["verdict"] == "HOLD" else 0
    if not args.candidate or not args.out:
        ap.error("--candidate and --out are required (or --from-report)")
    out = Path(args.out)
    if args.best_of_both_out is None:
        args.best_of_both_out = str(out.with_suffix("")) + ".best_of_both.jsonl"
    md = Path(args.md) if args.md else out.with_suffix(".md")
    out.parent.mkdir(parents=True, exist_ok=True)
    try:
        rep = compare(args)
    except FileNotFoundError as exc:
        print(f"cannot compare: {exc}", file=sys.stderr)
        return 2
    ledger_path = None
    if not args.no_ledger:
        ledger_path = write_ledger(rep, Path(args.ledger_dir), date_s)
        rep["ledger_record"] = ledger_path.name
    if args.append_changelog:
        append_changelog(Path(args.ledger_dir) / "CHANGELOG.md", changelog_entry(rep, ledger_path))
    tmp = out.with_suffix(out.suffix + ".tmp")
    tmp.write_text(json.dumps(rep, indent=1, default=str) + "\n")
    os.replace(tmp, out)
    md.write_text(render_markdown(rep))
    print(f"verdict {rep['verdict']}: {len(rep['blockers'])} blocker(s), {len(rep['notes'])} note(s); "
          f"report {out}, verdict {md}" + (f", ledger {ledger_path}" if ledger_path else ""))
    for x in rep["blockers"][:20]:
        print(f"  BLOCKER [{x['section']}] {x['name']}: {x['detail'][:160]}")
    return 1 if rep["verdict"] == "HOLD" else 0


if __name__ == "__main__":
    raise SystemExit(main())
