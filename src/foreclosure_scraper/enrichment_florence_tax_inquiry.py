"""raw['tax_owed'] (the canonical delinquent-tax balance) and raw['florence_tax_inquiry'] (this
module's own source block) for Florence County SC parcels, from the treasurer's live tax inquiry
CGI at web.florenceco.org -- a plain, free, no-login, no-CAPTCHA GET, already documented and
read (for VERIFICATION of an existing claim, not for FILLING a new one) by
verification/verifiers/tax_lien_florence.py.

WHY THIS EXISTS (gap_matrix "sourced-not-built": Florence tax_aging_surfaced AND
two_year_delinquent, ~3,883 est rows, "check" layer). Florence's tax-sale-list rows
(counties_sc.florence_delinquent_tax, the county's own annual delinquent-tax advertisement) name a
claim no fetcher ever turns into raw['tax_owed'] -- measured 2026-11-05, read-only against the live
board (docs/listings_part_*.json.gz): every sampled Florence row carries raw['florence_delinquent_tax']
(the sale-list block: taxpayer, TMS, lot description, acreage) but zero carry raw['tax_owed']. The
verifier (tax_lien_florence.py) reads the SAME two CGI endpoints this module reads, but only to
CONFIRM/REFUTE a claim a row already states for its verification ledger -- it does not write
raw['tax_owed'], and it is a different subsystem with a different orchestrator (not main.py's
enrichment phases, the ones this project's gap_matrix/fill-layer language is about). This module
is the FILL half: it writes the canonical balance field every other reader in this codebase already
knows how to consume --
  raw['tax_owed']            enrichment_tax_aging.py (already wired in main.py, line ~3777) reads
                              this via enrichment_tax_owed.tax_year_status()/unpaid_levy_years() to
                              compute raw['tax_aging_surfaced'] / raw['tax_aging_high']. Nothing new
                              to wire for that signal -- it is automatic once tax_owed is real.
  raw['florence_tax_inquiry'] this module's own per-parcel block (modeled on
                              raw['billtrax_dorchester_delinquent_tax']), read by the new sibling
                              enrichment_florence_two_year_delinquent.py to produce
                              raw['two_year_delinquent'] (same restate pattern as
                              enrichment_dorchester_two_year_delinquent.py / enrichment_berkeley_
                              two_year_delinquent.py / enrichment_qpaybill_multiyear_tax.py --
                              "years" in the shared contract is a COUNT of matured/late years, not
                              a list; is_two_year_plus is computed here with the SAME statutory
                              late-date rule (tax_calendar.levy_year_is_delinquent) those siblings
                              apply, not re-derived downstream).

SOURCE (live-checked 2026-11-05, plain httpx, no cookie, no session, no login, no CAPTCHA):
  GET http://web.florenceco.org/cgi-bin/ta/tax-inq.cgi?step=2&file=<F>&name=&street=
      &map=<MMMMM>&block=<BB>&parcel=<PPP>&acct=&cat=&num=&rc1=&rc2=
      one levy year's bill of the parcel. F: rpcpubf (current levy), rpcpubp1 (one year back).
      Real response, parcel 30000-44-787 (BARTELL BARRY, from the live board), file=rpcpubf:
      a single Real/district-200 bill, "BARTELL BARRY ... 1984 CONNER 14X56", posted 09/12/26,
      Total Due $164.47, not yet paid (a CURRENT-year bill, not yet late).
  GET http://web.florenceco.org/cgi-bin/ta/tax-del.cgi?step=2&<same parcel fields>
      every bill of the parcel that ever went delinquent, since 1981, with its paid date; a still-
      open delinquent bill is highlighted bgcolor="#ffa0a0" ("Red Entries Are Delinquent Taxes").
      Real response, parcel 41000-52-676 (BRAILEY KEVIN LEVERN): three notices, two already paid
      late (2021, 2023 levies, each with a Paid date), one still red/open (2024 levy, notice
      24006873, Total 268.01, Posted 09/14/24, Paid --/--/--, flagged "R BANKRUPTCY").
The parcel key is Map-Block-Parcel; the board's own TMS strings ("30000-44-787", "41000-52-676")
already carry it in that order and need only zero-padding (map to 5 digits, block to 2, parcel to
3) -- the exact same mbp()/zero-pad rule tax_lien_florence.py already applies, reimplemented here
independently (pure, 3 lines) so this fetcher has no import-time dependency on the verification
package. The HTML row parser (parse_bills below) matches tax_lien_florence.parse_bills() cell-for-
cell (7 <td>s after the per-row Map-Block-Parcel marker: type/district, name/lot, billing address,
messages, assessment(+Total Due/Total Paid label), money(last number = grand total), dates), and
the owed/open test is the SAME formula that module's to_bills() already uses: a bill is open only
when it has no Paid date, no Abated date, AND (its delinquent-page row is red OR its total-row
label reads "Total Due" rather than "Total Paid").

WHAT IT WRITES (missing-only for tax_owed; the source block is unconditional once a fetch answers,
mirroring enrichment_dorchester_two_year_delinquent.py's own sibling block):
  raw['tax_owed'] = {balance, kind: 'delinquent_tax', source: 'web.florenceco.org',
                     basis: 'own_record', years: [...], status} -- written only when balance > 0
                     and the row has no balance yet (never overwrites a real existing figure).
  raw['florence_tax_inquiry'] = {tms, balance, years, late_years, is_two_year_plus,
                                 years_delinquent, oldest_year, sold_at_tax_sale, fetched_at,
                                 source: 'web.florenceco.org'}

POLITENESS: web.florenceco.org is an old county CGI box, not a modern API -- MIN_GAP_S apart, one
request in flight at a time (a module lock, like gis_fill.py's), a small concurrency cap, a
consecutive-failure breaker, and a wall-clock budget. 3 requests per parcel (2 year files + the
delinquent list), cached per parcel for one run.

FLAG: FORECLOSURE_FLORENCE_TAX_INQUIRY (default off -- opt in explicitly; this is a new, previously
untested-at-scale fetcher against a single county CGI box). FORECLOSURE_FLORENCE_TAX_INQUIRY_BUDGET_S
bounds the wall clock (default 1200s); FORECLOSURE_FLORENCE_TAX_INQUIRY_MAX_PARCELS caps parcels
per run (default 2000).

NOT WIRED INTO main.py by this change -- see the caller's own report for the one import+call line.
"""
from __future__ import annotations

import asyncio
import html as _html
import os
import re
import time
from datetime import date, datetime, timezone
from typing import Any, Iterable, Optional
from urllib.parse import urlencode

import httpx
import structlog

from . import tax_calendar as _cal
from .models import Listing

log = structlog.get_logger()

_ENV_FLAG = "FORECLOSURE_FLORENCE_TAX_INQUIRY"
_ENV_BUDGET = "FORECLOSURE_FLORENCE_TAX_INQUIRY_BUDGET_S"
_ENV_MAX_PARCELS = "FORECLOSURE_FLORENCE_TAX_INQUIRY_MAX_PARCELS"
RECHECK_DAYS = 14.0
COUNTY = "florence"
STATE = "SC"
BASE = "http://web.florenceco.org/cgi-bin/ta/"
#: current levy file first, then one year back -- the same two the verifier reads for its check
YEAR_FILES = ("rpcpubf", "rpcpubp1")
MIN_GAP_S = 2.0
CONCURRENCY = 3
BREAKER_FAILS = 6
TIMEOUT_S = 30.0

_lock = asyncio.Lock()
_last = [0.0]


def enabled() -> bool:
    return os.environ.get(_ENV_FLAG, "0").strip() == "1"


def _raw(li: Any) -> dict:
    r = getattr(li, "raw", None)
    return r if isinstance(r, dict) else {}


# ---------------------------------------------------------------------------------------------
# pure parsers -- independent of, but matching cell-for-cell, tax_lien_florence.parse_bills()
# ---------------------------------------------------------------------------------------------

_TMS = re.compile(r"^\s*(\d{1,5})[-\s.]+(\d{1,2})[-\s.]+(\d{1,3})\s*$")


def mbp(v: Any) -> Optional[tuple[str, str, str]]:
    """('30000', '44', '787') from a board TMS ('30000-44-787'), zero-padded to 5-2-3; None for a
    blank/all-zero/unshaped value."""
    m = _TMS.match(str(v or ""))
    if not m:
        return None
    a, b, c = m.group(1).zfill(5), m.group(2).zfill(2), m.group(3).zfill(3)
    return None if set(a + b + c) <= {"0"} else (a, b, c)


def _query(m: tuple[str, str, str]) -> list[tuple[str, str]]:
    return [("name", ""), ("street", ""), ("map", m[0]), ("block", m[1]), ("parcel", m[2]),
            ("acct", ""), ("cat", ""), ("num", ""), ("rc1", ""), ("rc2", "")]


def year_url(m: tuple[str, str, str], file: str) -> str:
    return f"{BASE}tax-inq.cgi?{urlencode([('step', 2), ('file', file)] + _query(m))}"


def del_url(m: tuple[str, str, str]) -> str:
    return f"{BASE}tax-del.cgi?{urlencode([('step', 2)] + _query(m))}"


#: the notice anchor on a YEAR file carries an extra '&file=rpcpubf' before the closing '>' that
#: the DELINQUENT list's anchor does not ('key=26004137&file=rpcpubf>26004137</a>' vs
#: 'key=24006873>24006873</a>') -- [^>]* covers both shapes instead of only the second.
_ANCHOR = re.compile(r"key=(\d{6,10})[^>]*>\s*\d{6,10}\s*</a>", re.I)
_MBP_CELL = re.compile(r"</table>\s*(\d{5}\s+\d{2}\s+\d{3})\s*</td>", re.I)
_TD = re.compile(r"<td\b[^>]*>(.*?)</td>", re.S | re.I)
_BR = re.compile(r"<br\s*/?>|<hr\s*/?>", re.I)
_NOT_FOUND = re.compile(r"No match found", re.I)


def _parts(cell: str) -> list[str]:
    return [" ".join(_html.unescape(re.sub(r"<[^>]+>", " ", p)).split()) for p in _BR.split(cell or "")]


def _num(s: Any) -> Optional[float]:
    t = re.sub(r"[^\d.\-]", "", str(s or ""))
    try:
        return round(float(t), 2) if t not in ("", ".", "-") else None
    except ValueError:
        return None


def _d(s: Any) -> Optional[date]:
    try:
        return datetime.strptime(str(s or "").strip(), "%m/%d/%y").date()
    except ValueError:
        return None


def parse_bills(page: str) -> Optional[list[dict]]:
    """One page (a year file or the delinquent list) -> [{year, real, owed, paid, delinquent,
    sold, flags}], oldest-notice-first; [] for 'No match found'; None when the page is not an
    inquiry answer at all (a network/portal problem, never a legitimate empty result)."""
    page = page or ""
    if _NOT_FOUND.search(page):
        return []
    if "Notice #" not in page:
        return None
    hits = list(_ANCHOR.finditer(page))
    starts = [max(page.rfind("<tr", 0, page.rfind("<tr", 0, h.start())), 0) for h in hits]
    out: list[dict] = []
    for i, h in enumerate(hits):
        start = starts[i]
        seg = page[start:starts[i + 1] if i + 1 < len(hits) else len(page)]
        head = page[start:h.start()]
        mm = _MBP_CELL.search(seg)
        rest = seg[mm.end():] if mm else seg[seg.find("</table>") + 8:]
        tds = _TD.findall(rest)
        if len(tds) < 7:
            continue
        typ, _owner_lot, _billing, msgs, assess, money, dates = (_parts(t) for t in tds[:7])
        notice = h.group(1)
        yy = int(notice[:2])
        year = 2000 + yy if yy < 80 else 1900 + yy
        label = next((p for p in reversed(assess) if p.lower().startswith("total")), "")
        nums = [x for x in (_num(p) for p in money) if x is not None]
        dts = [_d(x) for x in dates] + [None] * 4
        paid, abated = dts[1], dts[2]
        delinquent = "ffa0a0" in head.lower()
        msg_text = " ".join(msgs).upper()
        sold = bool(re.search(r"\bSOLD\b", msg_text))
        real = (typ[0] if typ else "").strip().lower().startswith("real")
        open_ = real and paid is None and abated is None and (delinquent or label.lower() == "total due")
        out.append({"year": year, "real": real, "owed": (nums[-1] if (open_ and nums) else 0.0),
                    "paid": paid, "delinquent": delinquent, "sold": sold})
    return out


def aggregate(rows: list[dict]) -> dict:
    """Pure: {balance, years, sold} from every parsed bill (year files + delinquent list,
    deduped by year -- the delinquent list repeats a year the year files already answered)."""
    by_year: dict[int, dict] = {}
    for r in rows:
        if not r["real"]:
            continue
        cur = by_year.get(r["year"])
        if cur is None or r["owed"] > cur["owed"]:
            by_year[r["year"]] = r
    owed_years = sorted(y for y, r in by_year.items() if r["owed"] > 0)
    balance = round(sum(by_year[y]["owed"] for y in owed_years), 2)
    sold = any(r["sold"] for r in by_year.values())
    return {"balance": balance, "years": owed_years, "sold": sold}


# ---------------------------------------------------------------------------------------------
# transport
# ---------------------------------------------------------------------------------------------

class PortalDown(RuntimeError):
    pass


async def _get(client: httpx.AsyncClient, url: str) -> Optional[list[dict]]:
    async with _lock:
        wait = MIN_GAP_S - (time.monotonic() - _last[0])
        if wait > 0:
            await asyncio.sleep(wait)
        try:
            r = await client.get(url, timeout=TIMEOUT_S)
        finally:
            _last[0] = time.monotonic()
    if r.status_code != 200:
        return None
    return parse_bills(r.text)


async def fetch_parcel(client: httpx.AsyncClient, m: tuple[str, str, str]) -> Optional[dict]:
    """aggregate() for one parcel, or None when the portal did not answer usefully (a transient
    failure, never a legitimate 'nothing owed')."""
    rows: list[dict] = []
    for f in YEAR_FILES:
        got = await _get(client, year_url(m, f))
        if got is None:
            return None
        rows += got
    got = await _get(client, del_url(m))
    if got is None:
        return None
    rows += got
    return aggregate(rows)


# ---------------------------------------------------------------------------------------------
# the enricher
# ---------------------------------------------------------------------------------------------

def _recently_checked(raw: dict, now: datetime) -> bool:
    blk = raw.get("florence_tax_inquiry")
    if not isinstance(blk, dict) or not blk.get("fetched_at"):
        return False
    try:
        t = datetime.fromisoformat(str(blk["fetched_at"]).replace("Z", "+00:00"))
    except ValueError:
        return False
    if t.tzinfo is None:
        t = t.replace(tzinfo=timezone.utc)
    return (now - t).total_seconds() < RECHECK_DAYS * 86400.0


def needs(li: Any, now: datetime) -> bool:
    if str(getattr(li, "state", "") or "").upper() != STATE:
        return False
    if str(getattr(li, "county", "") or "").strip().lower().replace(" county", "") != COUNTY:
        return False
    if mbp(getattr(li, "parcel_id", None)) is None:
        return False
    raw = _raw(li)
    to = raw.get("tax_owed")
    if isinstance(to, dict) and to.get("balance"):
        return False
    return not _recently_checked(raw, now)


def build_block(m: tuple[str, str, str], agg: dict, now_iso: str, today: date) -> dict:
    """Pure: raw['florence_tax_inquiry'] from one parcel's aggregate()."""
    years = agg["years"]
    late = [y for y in years if _cal.levy_year_is_delinquent(y, STATE, COUNTY.title(), today)]
    return {"tms": "-".join(m), "balance": agg["balance"], "years": years, "late_years": late,
            "is_two_year_plus": len(late) >= 2, "years_delinquent": len(late),
            "oldest_year": min(years) if years else None, "sold_at_tax_sale": agg["sold"],
            "fetched_at": now_iso, "source": "web.florenceco.org"}


def apply_block(li: Any, block: dict) -> bool:
    """Write florence_tax_inquiry unconditionally, tax_owed only when balance > 0 and the row has
    none yet. Returns True when tax_owed was (newly) written."""
    raw = dict(_raw(li))
    raw["florence_tax_inquiry"] = block
    filled = False
    to = raw.get("tax_owed")
    has_balance = isinstance(to, dict) and bool(to.get("balance"))
    if block["balance"] > 0 and not has_balance:
        raw["tax_owed"] = {"balance": block["balance"], "kind": "delinquent_tax",
                           "source": "web.florenceco.org", "basis": "own_record",
                           "years": block["years"],
                           "status": "sold_at_tax_sale" if block["sold_at_tax_sale"] else "unpaid"}
        filled = True
    li.raw = raw
    return filled


async def enrich_florence_tax_inquiry(listings: Iterable[Listing]) -> dict:
    stats = {"eligible_rows": 0, "parcels": 0, "fetched": 0, "owed_parcels": 0, "filled_rows": 0,
             "portal_failures": 0, "budget_exhausted": False, "circuit_open": False}
    if not enabled():
        return {**stats, "skipped": f"{_ENV_FLAG}=0"}
    now = datetime.now(timezone.utc)
    now_iso = now.isoformat(timespec="seconds")
    today = now.date()
    try:
        budget_s = float(os.environ.get(_ENV_BUDGET, "1200"))
    except ValueError:
        budget_s = 1200.0
    try:
        max_parcels = int(os.environ.get(_ENV_MAX_PARCELS, "2000"))
    except ValueError:
        max_parcels = 2000
    t0 = time.monotonic()

    by_parcel: dict[tuple[str, str, str], list[Listing]] = {}
    for li in listings:
        if not needs(li, now):
            continue
        stats["eligible_rows"] += 1
        m = mbp(li.parcel_id)
        by_parcel.setdefault(m, []).append(li)
    stats["parcels"] = len(by_parcel)

    sem = asyncio.Semaphore(CONCURRENCY)
    consec_fail = {"n": 0}
    tripped = {"v": False}

    async with httpx.AsyncClient(headers={"User-Agent": "Mozilla/5.0 (compatible; foreclosure-scraper)"},
                                 follow_redirects=True) as client:
        async def one(m: tuple[str, str, str], rows: list[Listing]) -> None:
            if tripped["v"] or time.monotonic() - t0 > budget_s:
                return
            async with sem:
                if tripped["v"] or time.monotonic() - t0 > budget_s:
                    return
                try:
                    agg = await fetch_parcel(client, m)
                except Exception as exc:  # noqa: BLE001 - one parcel never kills the pass
                    log.warning("florence_tax_inquiry.failed", tms="-".join(m),
                               error=f"{type(exc).__name__}: {str(exc)[:120]}")
                    agg = None
                if agg is None:
                    stats["portal_failures"] += 1
                    consec_fail["n"] += 1
                    if BREAKER_FAILS and consec_fail["n"] >= BREAKER_FAILS:
                        tripped["v"] = True
                        log.warning("florence_tax_inquiry.circuit_open", parcels_done=stats["fetched"])
                    return
                consec_fail["n"] = 0
                stats["fetched"] += 1
                block = build_block(m, agg, now_iso, today)
                if block["balance"] > 0:
                    stats["owed_parcels"] += 1
                for li in rows:
                    if apply_block(li, block):
                        stats["filled_rows"] += 1

        parcels = list(by_parcel.items())[:max_parcels]
        await asyncio.gather(*(one(m, rows) for m, rows in parcels))

    stats["budget_exhausted"] = time.monotonic() - t0 > budget_s
    stats["circuit_open"] = tripped["v"]
    log.info("florence_tax_inquiry.done", **stats)
    return stats
