"""LiensNC incremental refresh: the Mac side of the hand-off (2026-10-07).

WHY. LiensNC (NC lien-agent appointments) is the largest source on the board (~45,000 rows
under `counties_generic.liensnc` and the bare `liensnc` slug), but no run ever re-scraped it:
`national.liensnc` is disabled (the search is login-gated), and the rows came from the
operator running scripts/scrape_liensnc.py + scripts/ingest_all.py (+ the re-parse backfills)
by hand. The full run only carried them forward, so they stopped at the last manual ingest
(newest filing 08/26/2026).

WHERE IT RUNS. Only on the Mac: the scrape logs in with the owner's own LiensNC account
(scripts/scrape_liensnc.py reads LIENSNC_USER / LIENSNC_PASS from the environment, else its
built-in default). The registry scraper `counties_generic.liensnc`
(scrapers/counties_generic/liensnc.py) is `mac_only`, so source_split counts it with the
residential sources: scripts/run_stealth_sources.py runs it every cycle and the VM run
(FORECLOSURE_ROLE=vm) never does.

ONE CYCLE (run_cycle):
  1. one read-only pass over the published board (board_stream.iter_board_rows, ~30 s and
     ~300 MB): the LiensNC entry numbers already on it (case_number, source_url, raw block,
     also_seen_in links), its newest filing date, and the LiensNC street-address counts;
  2. the ledger data/liensnc/handoff_ledger.json (git-ignored): filings handed off on an
     earlier cycle. Those now on the board are dropped. One still missing after
     PENDING_MAX_DAYS becomes a tombstone (counted in the report, no longer sent);
  3. scrape_liensnc.fetch_incremental(): login, then the search bounded to filings from a
     few days before the board's newest filing date, newest first, stopping at the board's
     frontier (see the INCREMENTAL block in scripts/scrape_liensnc.py);
  4. every pending filing (new this cycle, or sent before and not on the board yet) becomes
     a Listing shaped like the rows already on the board, which scripts/run_stealth_sources.py
     writes to docs/handoff/stealth_leads/. The VM's national.stealth_handoff ingests it
     like any other Mac-scraped lead: same slug, same dedupe keys, same scoring.

ROW SHAPE (to_listing) = scripts/ingest_all.ingest_liensnc() + the fixes applied to the board
since: source `counties_generic.liensnc`, case_number = entry number, sale_date = filing
date, listing_type tax_lien, defendant = filed by, parcel_id = the cell's PIN (only when it
holds a digit: the PIN regex once read 'ehurst' out of "Pinehurst"), street address via
scrape_liensnc._extract_address (the lot-label fix), city / ZIP / county / owner name /
owner phone / email / mailing via backfill_liensnc_raw.parse_property / parse_owner (a
state typed as the county is no county; the city lookup fills it, as
fix_liensnc_bogus_county.py did), raw['liensnc'] = the scraped record, and
raw['builder_distress'] on "Active Related Filings? = Yes" or an address on 2+ filings
(ingest_liensnc.py's rule). distress_score treats every liensnc row as context-only
(_is_liensnc) and enrichment_lead_signals ignores builder_distress on liensnc rows: a
refreshed row scores exactly like an old one.
"""
from __future__ import annotations

import importlib.util
import json
import os
import re
import sys
from collections import Counter
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Iterable

from .models import Listing, ListingType

REPO = Path(__file__).resolve().parents[2]
SOURCE = "counties_generic.liensnc"
DEFAULT_BOARD = REPO / "docs" / "listings.json.gz"
DEFAULT_STATE_DIR = REPO / "data" / "liensnc"
LEDGER_NAME = "handoff_ledger.json"
REPORT_NAME = "last_run.json"
CHECKPOINT_NAME = "incremental_checkpoint.json"
CAPTCHA_HOLD_NAME = "captcha_seen.json"
SEARCH_HOME = "https://apps.liensnc.com/scr/"

#: Rows filed within this many days before the board's newest filing are checked by entry
#: number (a filing posted late is still picked up); older rows count as known by date.
OVERLAP_DAYS = 3
#: First run on a board with no LiensNC rows at all: look back this far.
BOOTSTRAP_DAYS = 30
#: A handed-off filing still not on the board after this many days stops being re-sent.
PENDING_MAX_DAYS = int(os.environ.get("LIENSNC_PENDING_MAX_DAYS", "10"))
DEFAULT_MAX_PAGES = int(os.environ.get("LIENSNC_MAX_PAGES", "300"))
DEFAULT_STOP_AFTER_KNOWN = int(os.environ.get("LIENSNC_STOP_AFTER_KNOWN", "100"))
DEFAULT_MAX_SECONDS = float(os.environ.get("LIENSNC_MAX_SECONDS", "1500"))

_ENTRY_URL_RE = re.compile(r"entryNumber=(\d+)")
_WS_RE = re.compile(r"\s+")
_SCRIPTS: dict = {}


def _script(name: str):
    """scripts/<name>.py as a module, loaded once. The login and the parsers stay in the
    operator's scripts (the account is never handled here), the same way
    scripts/liensnc_related_filings.py reuses them."""
    mod = _SCRIPTS.get(name) or sys.modules.get(name)
    if mod is None:
        spec = importlib.util.spec_from_file_location(name, REPO / "scripts" / f"{name}.py")
        mod = importlib.util.module_from_spec(spec)
        # Registered under its own name, so `import scrape_liensnc` elsewhere (the tests put
        # scripts/ on sys.path) gets this same module and the same exception classes.
        sys.modules[name] = mod
        spec.loader.exec_module(mod)
    _SCRIPTS[name] = mod
    return mod


def _utcnow() -> datetime:
    """Naive UTC, like every other first_seen / last_seen on the board."""
    return datetime.now(timezone.utc).replace(tzinfo=None)


def is_liensnc_source(source) -> bool:
    """Same test as distress_score._is_liensnc: 'liensnc' is one of the slug's parts."""
    return "liensnc" in str(source or "").split(".")


def _mdy(s) -> date | None:
    try:
        return datetime.strptime(str(s or "").strip(), "%m/%d/%Y").date()
    except ValueError:
        return None


def _addr_key(street) -> str:
    return _WS_RE.sub(" ", str(street or "")).strip().upper()


# ---- 1. what the board already holds ------------------------------------------------------

@dataclass
class BoardIndex:
    entries: set = field(default_factory=set)
    newest_filing: date | None = None
    addr_counts: Counter = field(default_factory=Counter)
    rows: int = 0
    liensnc_rows: int = 0


def index_rows(rows: Iterable[dict]) -> BoardIndex:
    """Entry numbers, newest filing date and LiensNC address counts from board row dicts."""
    idx = BoardIndex()
    for r in rows:
        if not isinstance(r, dict):
            continue
        idx.rows += 1
        raw = r.get("raw") if isinstance(r.get("raw"), dict) else {}
        blk = raw.get("liensnc") if isinstance(raw.get("liensnc"), dict) else None
        if blk:
            e = str(blk.get("entry_number") or "").strip()
            if e.isdigit():
                idx.entries.add(e)
            d = _mdy(blk.get("filing_date"))
            if d and (idx.newest_filing is None or d > idx.newest_filing):
                idx.newest_filing = d
        for a in raw.get("also_seen_in") or []:
            if isinstance(a, dict) and is_liensnc_source(a.get("source")):
                m = _ENTRY_URL_RE.search(str(a.get("url") or ""))
                if m:
                    idx.entries.add(m.group(1))
        if not is_liensnc_source(r.get("source")):
            continue
        idx.liensnc_rows += 1
        cn = str(r.get("case_number") or "").strip()
        if cn.isdigit():
            idx.entries.add(cn)
        m = _ENTRY_URL_RE.search(str(r.get("source_url") or ""))
        if m:
            idx.entries.add(m.group(1))
        a = _addr_key(r.get("street_address"))
        if a:
            idx.addr_counts[a] += 1
    return idx


def board_index(path=None) -> BoardIndex:
    """One constant-memory pass over the published board (never load_board on this Mac)."""
    from .board_stream import iter_board_rows
    return index_rows(iter_board_rows(path or DEFAULT_BOARD))


# ---- 2. the ledger of handed-off filings --------------------------------------------------

class Ledger:
    """data/liensnc/handoff_ledger.json: {"version": 1, "entries": {entry: item}}.

    item = {"state": "pending", "record": <scraped record>, "filing_date", "first_sent",
    "last_sent", "sends"}; a tombstone is {"state": "expired", "filing_date", "first_sent",
    "expired_on"} (the record is dropped). git-ignored: it holds names and phone numbers."""

    def __init__(self, path):
        self.path = Path(path)
        self.entries: dict = {}
        if self.path.exists():
            try:
                data = json.loads(self.path.read_text())
                self.entries = dict((data or {}).get("entries") or {})
            except Exception:  # noqa: BLE001 - a torn ledger: the board pass is the truth
                self.entries = {}

    def ids(self) -> set:
        return set(self.entries)

    def pending(self) -> dict:
        return {e: it for e, it in self.entries.items() if it.get("state") == "pending"}

    def add(self, records: Iterable[dict], today: date) -> int:
        n = 0
        for rec in records:
            e = str(rec.get("entry_number") or "").strip()
            if not e.isdigit() or e in self.entries:
                continue
            self.entries[e] = {"state": "pending", "record": rec,
                               "filing_date": rec.get("filing_date"),
                               "first_sent": today.isoformat(), "last_sent": None, "sends": 0}
            n += 1
        return n

    def prune(self, idx: BoardIndex, today: date, max_days: int = PENDING_MAX_DAYS) -> dict:
        """Drop what landed on the board; tombstone what is still missing after `max_days`;
        forget tombstones filed before any future scan window."""
        st = Counter()
        floor = (idx.newest_filing - timedelta(days=OVERLAP_DAYS + 1)
                 if idx.newest_filing else None)
        for e in list(self.entries):
            it = self.entries[e]
            if e in idx.entries:
                del self.entries[e]
                st["landed"] += 1
                continue
            first = it.get("first_sent")
            age = (today - date.fromisoformat(first)).days if first else 0
            if it.get("state") == "pending" and age > max_days:
                self.entries[e] = {"state": "expired", "filing_date": it.get("filing_date"),
                                   "first_sent": first, "expired_on": today.isoformat()}
                st["expired"] += 1
            elif it.get("state") == "expired" and floor:
                fd = _mdy(it.get("filing_date"))
                if fd and fd < floor:
                    del self.entries[e]
                    st["tombstones_forgotten"] += 1
        return dict(st)

    def mark_sent(self, today: date) -> None:
        for it in self.pending().values():
            it["last_sent"] = today.isoformat()
            it["sends"] = int(it.get("sends") or 0) + 1

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps({"version": 1, "entries": self.entries}))
        tmp.replace(self.path)


# ---- 3. one scraped record -> one board row -----------------------------------------------

def to_listing(rec: dict, *, addr_counts: Counter | None = None,
               now: datetime | None = None) -> Listing | None:
    """The hand-off row for one scraped filing, shaped like the LiensNC rows on the board.
    None when the record has no entry number (it would have no identity on the board)."""
    entry = str(rec.get("entry_number") or "").strip()
    if not entry.isdigit():
        return None
    bf = _script("backfill_liensnc_raw")
    now = now or _utcnow()
    p = bf.parse_property(rec.get("property_text") or "")
    o = bf.parse_owner(rec.get("owner_text") or "")

    street = _WS_RE.sub(" ", str(rec.get("address") or "")).strip() or (p["street"] or None)
    rc = str(rec.get("city") or "").split("\n")[-1].strip()
    city = p["city"] or (rc if rc and not (street and street.lower() in rc.lower()) else None)
    county = p["county"]
    if not county and city:
        from ._upstate_city_to_county import upstate_county_for
        county = upstate_county_for(city, "NC")
    pin = str(rec.get("pin") or "").strip()
    filed = _mdy(rec.get("filing_date"))

    raw: dict = {"liensnc": dict(rec), "landed_by": "liensnc_handoff"}
    if o["phone"]:
        raw["owner_phone"] = {
            "phone": o["phone"], "additional_phones": [], "source": "liensnc_filing",
            "match": "self_filed_lien_agent_appointment", "needs_dnc_scrub": True,
            "tcpa_class": "manual_only",
        }
    if o["email"]:
        raw["owner_email"] = {"email": o["email"], "source": "liensnc_filing"}
    if o["mailing"]:
        raw["owner_mailing"] = {
            "owner": o["name"], "mailing": o["mailing"], "situs": street,
            "absentee": bool(street and street.split()[0] not in o["mailing"]),
            "source": "liensnc_filing",
        }
    related = str(rec.get("related_filings") or "").strip().lower() == "yes"
    cluster = bool(street) and (addr_counts or Counter()).get(_addr_key(street), 0) >= 2
    if related or cluster:
        raw["builder_distress"] = {"related_filings": related, "cluster": cluster,
                                   "source": "liensnc"}

    return Listing(
        source=SOURCE,
        source_url=rec.get("detail_url") or SEARCH_HOME,
        listing_type=ListingType.TAX_LIEN,
        defendant=(rec.get("filed_by") or rec.get("owner_text") or None),
        case_number=entry,
        parcel_id=pin if any(ch.isdigit() for ch in pin) else None,
        street_address=street,
        city=city or None,
        state="NC",
        zip_code=rec.get("zip_code") or p["zip"] or None,
        county=county,
        owner_name=o["name"],
        sale_date=datetime(filed.year, filed.month, filed.day) if filed else None,
        first_seen=now,
        last_seen=now,
        raw=raw,
    )


def listing_stats(listings: list[Listing]) -> dict:
    """Counts only (the report and the logs never carry names or addresses)."""
    return {
        "rows": len(listings),
        "nc": sum(1 for li in listings if (li.state or "").upper() == "NC"),
        "nc_with_county": sum(1 for li in listings
                              if (li.state or "").upper() == "NC" and li.county),
        "with_street": sum(1 for li in listings if li.street_address),
        "with_parcel_id": sum(1 for li in listings if li.parcel_id),
        "with_owner_phone": sum(1 for li in listings if (li.raw or {}).get("owner_phone")),
        "builder_distress": sum(1 for li in listings if (li.raw or {}).get("builder_distress")),
        "top_counties": Counter(li.county for li in listings if li.county).most_common(8),
        "filing_dates": [min((li.sale_date for li in listings if li.sale_date),
                             default=None),
                         max((li.sale_date for li in listings if li.sale_date),
                             default=None)],
    }


# ---- 4. the cycle -----------------------------------------------------------------------

async def run_cycle(*, board_path=None, state_dir=None, max_pages: int | None = None,
                    stop_after_known: int | None = None, max_seconds: float | None = None,
                    proof: bool = False, today: date | None = None, fetch=None,
                    index: BoardIndex | None = None, rescan_from: date | None = None,
                    log=print) -> tuple[list[Listing], dict]:
    """One hand-off cycle. Returns (rows to hand off, report). `proof` scrapes with the same
    rules but writes no checkpoint, ledger or report and hands nothing off (counts only).

    `rescan_from` (operator recovery): walk the whole window from that filing date to today
    with no stop rule, forget the given-up tombstones, and queue again every filing the board
    still lacks. For a backlog the VM dropped before it could land (main._active_only drops a
    fresh row whose sale_date, here the filing date, is over 14 days old unless main.py treats
    filing dates as it should).

    A refused login or a CAPTCHA never raises here: the report says so and the filings still
    pending from earlier cycles are handed off anyway. A CAPTCHA also leaves
    data/liensnc/captcha_seen.json, and while that file exists no cycle logs in (delete it
    after a person has looked)."""
    state_dir = Path(state_dir or DEFAULT_STATE_DIR)
    today = today or date.today()
    now = _utcnow()
    max_pages = DEFAULT_MAX_PAGES if max_pages is None else max_pages
    stop_after_known = DEFAULT_STOP_AFTER_KNOWN if stop_after_known is None else stop_after_known
    max_seconds = DEFAULT_MAX_SECONDS if max_seconds is None else max_seconds
    sl = _script("scrape_liensnc")
    fetch = fetch or sl.fetch_incremental

    idx = index or board_index(board_path)
    ledger = Ledger(state_dir / LEDGER_NAME)
    # A proof counts every filing the board lacks, handed off or not, and changes nothing.
    pruned = ledger.prune(idx, today) if not proof else {}
    checkpoint = None if proof else state_dir / CHECKPOINT_NAME
    if idx.newest_filing:
        known_cutoff = idx.newest_filing - timedelta(days=OVERLAP_DAYS)
        since = known_cutoff - timedelta(days=1)
    else:
        known_cutoff, since = None, today - timedelta(days=BOOTSTRAP_DAYS)
    if rescan_from and not proof:
        for e in [e for e, it in ledger.entries.items() if it.get("state") == "expired"]:
            del ledger.entries[e]
        known_cutoff, since = rescan_from, rescan_from - timedelta(days=1)
        stop_after_known, checkpoint = 10 ** 9, None
    neutral = set() if proof else ledger.ids()
    report: dict = {
        "generated_at": now.isoformat(timespec="seconds") + "Z",
        "proof": proof,
        "rescan_from": rescan_from.isoformat() if rescan_from else None,
        "board": {"rows": idx.rows, "liensnc_rows": idx.liensnc_rows,
                  "entries_known": len(idx.entries),
                  "newest_filing": idx.newest_filing.isoformat() if idx.newest_filing else None},
        "ledger": dict(pruned),
    }

    hold = state_dir / CAPTCHA_HOLD_NAME
    res: dict
    if hold.exists():
        res = {"new": [], "stop_reason": "captcha_hold", "complete": False,
               "error": f"{hold} exists: a CAPTCHA was served on an earlier cycle"}
    else:
        try:
            res = await fetch(
                board_ids=idx.entries, known_cutoff=known_cutoff,
                since=since.strftime("%m/%d/%Y"), until=today.strftime("%m/%d/%Y"),
                neutral_ids=neutral, stop_after_known=stop_after_known,
                max_pages=max_pages, max_seconds=max_seconds,
                checkpoint_path=checkpoint, log=log)
        except sl.LoginFailed as exc:
            res = {"new": [], "stop_reason": "login_failed", "complete": False, "error": str(exc)}
        except sl.CaptchaSeen as exc:
            res = {"new": [], "stop_reason": "captcha", "complete": False, "error": str(exc)}
    if res.get("stop_reason") == "captcha" and not proof:
        hold.parent.mkdir(parents=True, exist_ok=True)
        hold.write_text(json.dumps({"seen_at": report["generated_at"],
                                    "error": res.get("error")}))
    report["scan"] = {k: v for k, v in res.items() if k != "new"}
    report["scan"]["new_filings"] = len(res.get("new") or [])

    if proof:
        counts = idx.addr_counts + Counter(_addr_key(r.get("address")) for r in res["new"]
                                           if r.get("address"))
        rows = [li for li in (to_listing(r, addr_counts=counts, now=now) for r in res["new"]) if li]
        report["found"] = listing_stats(rows)
        return rows, report

    report["ledger"]["added"] = ledger.add(res.get("new") or [], today)
    pending = [it["record"] for it in ledger.pending().values()]
    counts = idx.addr_counts + Counter(_addr_key(r.get("address")) for r in pending
                                       if r.get("address"))
    rows = [li for li in (to_listing(r, addr_counts=counts, now=now) for r in pending) if li]
    ledger.mark_sent(today)
    ledger.save()
    report["ledger"]["pending"] = len(pending)
    report["ledger"]["tombstones"] = sum(1 for it in ledger.entries.values()
                                         if it.get("state") == "expired")
    report["handoff"] = listing_stats(rows)
    state_dir.mkdir(parents=True, exist_ok=True)
    (state_dir / REPORT_NAME).write_text(json.dumps(report, default=str, indent=1))
    return rows, report


def summary_lines(report: dict) -> list[str]:
    """Plain counts for a log or a terminal."""
    b, s = report.get("board", {}), report.get("scan", {})
    out = [
        f"liensnc board: {b.get('liensnc_rows')} rows, {b.get('entries_known')} entry numbers, "
        f"newest filing {b.get('newest_filing')}",
        f"liensnc scan: window {s.get('since')}..{s.get('until')} "
        f"({s.get('total_pages')} pages), fetched {s.get('pages_fetched')} "
        f"(through page {s.get('last_page')}), stop={s.get('stop_reason')} "
        f"complete={s.get('complete')} resumed={s.get('resumed')}, "
        f"new filings {s.get('new_filings')}",
    ]
    if s.get("error"):
        out.append(f"liensnc scan error: {s['error']}")
    if report.get("ledger"):
        out.append(f"liensnc ledger: {report['ledger']}")
    for key in ("found", "handoff"):
        if report.get(key):
            out.append(f"liensnc {key}: {report[key]}")
    return out


if __name__ == "__main__":  # pragma: no cover - the operator entry is scripts/scrape_liensnc.py
    sys.exit("run: uv run python scripts/scrape_liensnc.py --incremental [--proof]")
