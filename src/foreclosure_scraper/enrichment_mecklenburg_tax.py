"""Mecklenburg County NC "Bill Search" portal (taxbill.co.mecklenburg.nc.us) -> per-parcel
property-tax BILL HISTORY, restated into the two literal raw keys gap_matrix.py's own
checked_columns() actually credits: raw['multi_year_delinquent_tax'] and
raw['two_year_delinquent']. raw['tax_aging_surfaced'] is NOT written here -- it rides along for
free (see FOR FREE below), the same bonus every sibling <county>_multiyear_tax module in this
codebase already produces.

WHY THIS EXISTS (gap_matrix, 2026-11-05 run). NC Mecklenburg's "multi_year_delinquent_tax",
    "tax_aging_surfaced" and "two_year_delinquent" all show sourced-not-built, ~39,861 applicable
    rows each -- the single biggest sourced-not-built cell in the whole matrix. Checked first,
    per this task's own brief: `enrichment_mecklenburg_*` did not exist anywhere in this repo
    before this module. The ONLY existing Mecklenburg tax producer,
    scrapers/counties_nc/mecklenburg_delinquent_tax.py, is a DIFFERENT thing and does NOT close
    this gap:

NOT THE SAME GAP AS THE EXISTING MECKLENBURG SCRAPER (landed 2026-10-23, 20,786 rows, still live).
    That module reads the county's NCGS 105-369 statutory ADVERTISEMENT of unpaid taxes -- a
    once-a-year XLSX snapshot with taxpayer name + property address + one dollar amount, NO
    parcel number in the file at all (rows are joined to parcels afterward by matching the
    situs address against data/parcel_cache/mecklenburg.sqlite). It carries no per-year history,
    so it can state only "a lien exists" (raw['tax_lien']-style, one flag) -- it structurally
    cannot say how MANY years a parcel has been behind, which is what multi_year_delinquent_tax /
    two_year_delinquent / tax_aging_surfaced all actually ask. This module reads a completely
    different, live, searchable portal that answers that question directly, per parcel.

THE PORTAL (live-verified 2026-11-05, read-only, no login/CAPTCHA/click-through):
    GET  https://taxbill.co.mecklenburg.nc.us/publicwebaccess/
         -> an ASP.NET WebForms "Bill Search" page (lookupCriterion: Parcel Number / Owner Name /
            Street Name / Bill Number / Business Name / ...; the form itself states
            hdnParcelMaxLength=9, confirming the county's own Parcel Number is at most 9 digits).
    GET  https://taxbill.co.mecklenburg.nc.us/publicwebaccess/BillSearchResults.aspx?ParcelNum=<id>
         -> THE SAME results grid the form's own VIEWSTATE postback renders, from a bare
            query-string GET -- no __VIEWSTATE/__EVENTVALIDATION dance needed at all (confirmed:
            POSTing the form and GETting this URL directly return byte-identical grids). This is
            simpler than the classic ITS.NET product Iredell/Cabarrus/Chowan read
            (verification/verifiers/tax_lien_itsnet.py) -- Mecklenburg is a different vendor
            product, not another ITS.NET tenant, so nothing there is reused.

    Grid shape (one <tr> per BILL YEAR, newest first, no header row -- parsed by cell POSITION,
    same discipline enrichment_qpaybill_tax.py's own _parse_rows() docstring states): cell 0 Bill
    Number ("0002620348-2026-2026-0000-00" -- embeds the tax year), cell 1 a secondary/deed
    number (blank on most rows), cell 2 Parcel Number, cell 3 Owner Name AS OF THAT BILL YEAR
    (changes across rows on a sale -- e.g. one real parcel below went ANDREWS, MIA (2012-2018) ->
    COHEN, ERIC SAMUEL (2019-2025) -> COHEN CO REAL ESTATE LLC (2026)), cell 4 Property Address,
    cell 5 a mailing/status note ("Postcard", "OWNERSHIP TRANSFER, UNDELIVERED", or blank -- never
    a paid/unpaid marker), cell 6 the dollar balance ($0.00 once paid). A non-bill "Total:" footer
    row closes the grid; it has a different shape (no Bill Number in cell 0) and is dropped by
    the Bill-Number regex check, not by position, so it can never be mistaken for a real year.
    A parcel with no match answers "NO DATA FOUND" and renders no results table at all (tested
    live against two clearly-invalid numbers) -- a real, valid empty answer, not an error.

    PARCEL ID SHAPE, VERIFIED NOT GUESSED. The county's own Parcel Number is an 8-digit,
    ZERO-PADDED string ("00507430", not "507430" -- tested live: the unpadded 6-digit form and a
    4-digit prefix both answer "NO DATA FOUND", so the portal does exact-match only, no prefix/
    fuzzy search). data/parcel_cache/mecklenburg.sqlite (the same local cache
    mecklenburg_delinquent_tax.py already resolves against, read here ONLY to find real sample
    parcels, never queried by the production path below) stores every parcel under BOTH this bare
    8-digit id and a 13-digit tax-district-prefixed id ("3711917103426" = district "37119" + the
    same 8-digit "17103426" -- confirmed same owner/address on both rows for 3 separate parcels).
    A board row's parcel_id could plausibly carry either shape depending on which upstream source
    wrote it, so _candidate_parcel() below reduces anything longer than 9 digits to its last 8
    before zero-padding, rather than assuming the bare form.

    LIVE CANARY, 3 real parcels pulled from that same cache (owner names below are already public
    tax-roll record, read only to confirm the match -- never written to raw):
      17103426 (Eric Samuel Cohen, 1000 E Woodlawn Rd #203) -- 15 bill-years on file (2012-2026,
        page 1 of 2 -- see PAGING below), every year 2012-2025 paid $0.00, 2026 (current, billed
        this year, not yet due) unpaid $2,224.22. Not a multi-year delinquency: the only balance
        is the current, not-yet-matured levy.
      00507430 (Jessica Francovig, 19862 Deer Valley Dr, Cornelius) -- same shape: 2012-2025 paid,
        2026 unpaid $1,564.50.
      07808409 (NR Charlotte LLC, 215 N Pine St #409) -- same shape: 2012-2025 paid, 2026 unpaid
        $2,397.30.
    All three real canary parcels are current-bill-only, the identical "most sampled parcels are
    paid current" shape every other county's own canary in this codebase has found (Iredell's,
    Cabarrus's, Catawba's) -- expected, not a sign anything is broken; the real yield is in the
    ~39,861-row backlog this 3-parcel sample cannot represent by itself. A 4th query (Owner Name =
    "FRANCOVIG JESSICA") confirmed the Owner Name criterion also works and returns bills across
    that owner's several parcels -- not used by this module (parcel-number search is exact and
    one-row-at-a-time; name search is left as a possible future fallback for rows with no usable
    parcel_id, not built here since the task's own ~39,861-row estimate is keyed on parcel, not
    owner).

    PAGING, A REAL AND DOCUMENTED LIMIT. The grid pages at 15 bill-years per page ("[Page 1 of 2]"
    on all 3 canary parcels, 2012-2026 on page 1); page 2 (pre-2012 years) is reachable only
    through a __doPostBack JS link, not a plain GET, and is NOT fetched here. This does not
    weaken the two signals this module writes: two_year_delinquent and the MIN_YEARS=2 gate on
    multi_year_delinquent_tax only ever need the most RECENT matured years, which page 1 always
    carries (it is newest-first) -- an old, since-resolved delinquency sitting only on page 2
    would not change either verdict. Documented the same way tax_lien_itsnet's own
    "results_paged" sentinel documents its paging limit, not hidden as a silent gap.

FOR FREE. tax_binding.BLOCK_PARCEL_FIELDS["multi_year_delinquent_tax"] = ("parcel_key",) and
    enrichment_tax_owed.py's FIELD_PRIORITY ("multi_year_delinquent_tax" -> reads this block's own
    "total_due") already exist and already run every pipeline pass -- raw['multi_year_delinquent_
    tax'] here is byte-shape-compatible with the Iredell/Cabarrus/Catawba/Wake/Gaston/Pender
    blocks (same keys, same _longest_run/_trend helpers, reused verbatim, not reimplemented), so
    it is promoted into raw['tax_owed'] and then raw['tax_aging_surfaced']
    (enrichment_tax_aging.py) with no code added here for either step.

    raw['two_year_delinquent'] IS WRITTEN HERE, unconditionally on every row a search actually
    answers (status "ok", even an all-paid answer) -- gap_matrix.py reads it directly as its own
    literal key, not derived from multi_year_delinquent_tax, the same "years is a count" (not a
    list) discipline every sibling two_year_delinquent producer in this codebase already uses.

GATE. raw['two_year_delinquent'] is written for every row a search actually answers,
    truthfully either way. raw['multi_year_delinquent_tax'] is written ONLY when >=MIN_YEARS (2,
    MECKLENBURG_MYDT_MIN_YEARS) MATURED/late years still carry a balance TODAY (tax_calendar's NC
    January-6-of-next-year rule) -- a parcel whose only unpaid bill is this year's current,
    not-yet-due one (every canary parcel above) is not repeat delinquency. Idempotent via
    raw['_mecklenburg_mydt_checked'] on a row whose search failed to produce a usable answer, so
    later runs do not re-walk the same no-result/unreadable rows forever; a row that got a real
    grid answer needs no separate sentinel because raw['two_year_delinquent'] is itself written
    unconditionally on that path.

SCALE / BUDGET. One live GET per not-yet-checked, well-shaped Mecklenburg row, capped
    (MECKLENBURG_MYDT_MAX, default 300) and wall-clock-budgeted (MECKLENBURG_MYDT_BUDGET_S,
    default 600s), bounded concurrency (MECKLENBURG_MYDT_CONCURRENCY, default 4) and a
    consecutive-failure circuit breaker (MECKLENBURG_MYDT_BREAKER_FAILS, default 8) -- the same
    shape enrichment_qpaybill_tax.py (this module's own primary reference) already uses. httpx
    alone was never blocked or rate-limited in any live probe (no 403s, no WAF, no CAPTCHA), so
    the curl_cffi fallback this codebase's other fetchers reach for when httpx IS blocked is not
    implemented here -- there was nothing to fall back from.

PRIVACY. No owner name or mailing address is read into raw here -- only the board's own parcel
    number (already public) and tax-year dollar amounts land in raw['multi_year_delinquent_tax']
    / raw['two_year_delinquent']. Owner names appear only in this module's own live-verification
    docstring above (already public tax-roll record), never in code or in written data.

Gate off entirely with FORECLOSURE_MECKLENBURG_MYDT unset/not "1" (OFF by default -- this module
follows enrichment_qpaybill_tax.py's `_ENABLED = os.environ.get(...) == "1"` convention, not the
`!= "0"` default-on convention some older sibling multiyear_tax modules use, since nothing has
wired this into main.py yet and it should not silently start running the moment this file lands).
"""
from __future__ import annotations

import asyncio
import os
import re
import time
from datetime import date, datetime, timezone
from typing import Any, Iterable, Optional

import httpx
import structlog

from . import tax_calendar
from .models import Listing, _normalize_parcel
from .scrapers.counties_generic.multi_year_delinquent_tax import _longest_run, _trend

log = structlog.get_logger()

BASE = "https://taxbill.co.mecklenburg.nc.us/publicwebaccess/"
_UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
       "(KHTML, like Gecko) Chrome/120 Safari/537.36")

STATE = "NC"
COUNTY = "Mecklenburg"
MYDT_KEY = "multi_year_delinquent_tax"
TYD_KEY = "two_year_delinquent"
CHECKED_KEY = "_mecklenburg_mydt_checked"
SOURCE_SLUG = "enrichment_mecklenburg_tax"

_ENABLED = os.environ.get("FORECLOSURE_MECKLENBURG_MYDT") == "1"
MAX_ROWS = int(os.environ.get("MECKLENBURG_MYDT_MAX", "300"))
BUDGET_S = float(os.environ.get("MECKLENBURG_MYDT_BUDGET_S", "600"))
CONCURRENCY = int(os.environ.get("MECKLENBURG_MYDT_CONCURRENCY", "4"))
MIN_YEARS = int(os.environ.get("MECKLENBURG_MYDT_MIN_YEARS", "2"))
_BREAKER_FAILS = int(os.environ.get("MECKLENBURG_MYDT_BREAKER_FAILS", "8"))
_REQUEST_TIMEOUT_S = float(os.environ.get("MECKLENBURG_MYDT_TIMEOUT_S", "30"))

_BILL_ROW_RE = re.compile(r"^(\d+)-(\d{4})-\d{4}-")
_AMOUNT_RE = re.compile(r"\$([\d,]+\.\d{2})")


# ---------------------------------------------------------------------------
# which rows, which parcel string to search (pure)
# ---------------------------------------------------------------------------

def _county_key(li: Listing) -> str:
    return (li.county or "").replace(" County", "").strip().lower()


def _candidate_parcel(li: Listing) -> Optional[str]:
    """The portal's own 8-digit, zero-padded Parcel Number for this row's parcel_id, or None when
    it isn't shaped like one. See the module docstring's PARCEL ID SHAPE section: a board id
    longer than 9 digits is a 13/14-digit district-prefixed form whose LAST 8 digits are the same
    REID (verified against 3 real cache parcels); anything from 5 to 9 significant digits is
    zero-padded to 8 (verified live: the portal needs the full padded form, not the bare number).
    """
    digits = re.sub(r"\D", "", str(li.parcel_id or ""))
    if not digits:
        return None
    if len(digits) > 9:
        digits = digits[-8:]
    if len(digits) < 5:
        return None  # too short to be a real Mecklenburg Parcel Number, not a guessable match
    return digits.zfill(8)


def _already_done(li: Listing) -> bool:
    if not isinstance(li.raw, dict):
        return False
    return isinstance(li.raw.get(TYD_KEY), dict) or bool(li.raw.get(CHECKED_KEY))


def _eligible(li: Listing) -> bool:
    return (
        (li.state or "").strip().upper() == STATE
        and _county_key(li) == COUNTY.lower()
        and _candidate_parcel(li) is not None
        and not _already_done(li)
    )


# ---------------------------------------------------------------------------
# live fetch + parse (the portal's own grid, read positionally)
# ---------------------------------------------------------------------------

def _parse_bill_rows(html: str) -> list[dict]:
    """Every real bill-year row from a BillSearchResults.aspx answer, newest first, parsed by
    cell POSITION (the grid has no header row): cell 0 Bill Number (embeds the tax year), cell 2
    Parcel Number, cell 3 Owner Name as of that bill, cell 4 Property Address, cell 5 a mailing/
    status note, cell 6 the dollar balance. The 'Total:' footer row is dropped because its cell 0
    never matches the Bill-Number shape -- not by position, so it can't be mistaken for a year.

    FIX 2026-11-13: used to assume the bills grid is always tables[4] (treating fewer than 5
    tables as proof of "no data"). Live-verified that's false -- e.g. parcel 02951502 (real,
    18 bill rows, GOODALL KIMBERLY A) renders with only 4 tables total, grid at tables[3], on a
    page that is NOT a "NO DATA FOUND" answer. That false "no data" tripped
    enrichment_mecklenburg_tax's circuit breaker on a large, unpredictable fraction of otherwise-
    healthy parcels (mecklenburg_mydt.circuit_open, zero real writes). Fixed by scanning every
    table on the page and keeping whichever one actually contains the most bill-shaped rows,
    instead of trusting a fixed index -- robust to any extra/missing table elsewhere on the page."""
    tables = re.findall(r"<table[^>]*>(.*?)</table>", html, re.S)
    best: list[dict] = []
    for table in tables:
        candidate: list[dict] = []
        for row in re.findall(r"<tr[^>]*>(.*?)</tr>", table, re.S):
            cells = [re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", c)).strip()
                     for c in re.findall(r"<t[dh][^>]*>(.*?)</t[dh]>", row, re.S)]
            if len(cells) < 7:
                continue
            m = _BILL_ROW_RE.match(cells[0])
            if not m:
                continue
            amt_m = _AMOUNT_RE.search(cells[6])
            candidate.append({
                "year": int(m.group(2)),
                "bill_number": cells[0],
                "parcel": cells[2].strip(),
                "owner": cells[3].strip(),
                "address": cells[4].strip(),
                "note": cells[5].strip(),
                "balance": float(amt_m.group(1).replace(",", "")) if amt_m else 0.0,
            })
        if len(candidate) > len(best):
            best = candidate
    return best


async def _fetch_parcel_bills(client: httpx.AsyncClient, parcel: str) -> tuple[Optional[list[dict]], str]:
    """(bill rows, status) for one Mecklenburg Parcel Number via a plain query-string GET -- no
    login, no CAPTCHA, no ASP.NET VIEWSTATE postback needed (live-verified: the same grid the
    form's own POST renders comes back from a bare GET to BillSearchResults.aspx?ParcelNum=<id>).
    status is "ok" with `bills` set on a real answer (every canary parcel had 15 rows; an
    all-paid parcel still answers "ok" with every row at $0.00), "no_results" on a real, valid
    "NO DATA FOUND" answer (not an error), else a short machine reason."""
    try:
        r = await client.get(BASE + "BillSearchResults.aspx", params={"ParcelNum": parcel})
    except Exception as exc:  # noqa: BLE001 - every outcome is an answer
        return None, f"fetch_failed:{type(exc).__name__}"
    if r.status_code != 200:
        return None, f"fetch_failed:http_{r.status_code}"
    html = r.text
    if "NO DATA FOUND" in html.upper():
        return [], "no_results"
    rows = _parse_bill_rows(html)
    if not rows:
        return None, "unreadable_answer"
    return rows, "ok"


# ---------------------------------------------------------------------------
# pure: one parcel's bill rows -> matured/unpaid years (shared by both blocks)
# ---------------------------------------------------------------------------

def _years_matured_and_balances(parcel: str, rows: list[dict],
                                today: date) -> tuple[list[int], list[int], dict[int, float]]:
    """(years with a balance owed today, the MATURED/late subset, {year: balance}) for one
    parcel's own bill rows -- only rows whose own Parcel Number cell matches the parcel searched
    (belt-and-suspenders; the portal only ever returns that parcel's own bills for a Parcel Number
    search, but this keeps the same discipline every sibling multiyear_tax module uses)."""
    want = re.sub(r"\D", "", parcel)
    per_year: dict[int, float] = {}
    for b in rows or ():
        if re.sub(r"\D", "", str(b.get("parcel") or "")) != want:
            continue
        due = b.get("balance") or 0.0
        if due <= 0:
            continue
        year = b.get("year")
        if year is None:
            continue
        prev = per_year.get(year)
        per_year[year] = due if prev is None else max(prev, due)
    years = sorted(per_year)
    matured = tax_calendar.completed_delinquent_years(years, STATE, COUNTY, today)
    return years, matured, per_year


def build_two_year_block(parcel: str, rows: list[dict], *, today: Optional[date] = None) -> dict:
    """raw['two_year_delinquent'], written unconditionally once a search actually answers --
    even a zero-matured-year answer states `is_two_year_plus` truthfully, the "years is a count"
    discipline every sibling two_year_delinquent producer in this codebase already uses."""
    today = today or date.today()
    _, matured, _ = _years_matured_and_balances(parcel, rows, today)
    return {
        "is_two_year_plus": len(matured) >= 2,
        "years": len(matured),
        "oldest_year": min(matured) if matured else None,
        "source": SOURCE_SLUG,
    }


def build_multiyear_block(parcel: str, rows: list[dict], *,
                          today: Optional[date] = None) -> Optional[dict]:
    """raw['multi_year_delinquent_tax'], or None when the parcel doesn't clear the multi-year
    gate (fewer than MIN_YEARS matured/late unpaid years -- a parcel whose only unpaid bill is
    this year's current, not-yet-due one, the shape every canary parcel in the module docstring
    showed, is not repeat delinquency)."""
    today = today or date.today()
    years, matured, per_year = _years_matured_and_balances(parcel, rows, today)
    if len(matured) < MIN_YEARS:
        return None
    current = [y for y in years if y not in matured]
    total_owed = round(sum(per_year.values()), 2) or None
    matured_owed = round(sum(per_year[y] for y in matured), 2) or None
    county_latest_year = max((b["year"] for b in rows if b.get("year") is not None), default=years[-1])
    return {
        "years": years,
        "per_year": {str(y): per_year[y] for y in years},
        "years_delinquent": len(matured),
        "unpaid_bill_years": len(years),
        "matured_years": matured,
        "matured_years_delinquent": len(matured),
        "consecutive_years": _longest_run(years),
        "first_year": years[0],
        "latest_year": years[-1],
        "latest_matured_year": max(matured),
        "county_latest_year": county_latest_year,
        "current_levy_year": (current[-1] if current else None),
        "in_current_levy": bool(current),
        "total_due": total_owed,
        "total_owed": total_owed,
        "matured_owed": matured_owed,
        "year": years[-1],
        "trend": _trend(per_year, matured),
        "still_accruing": years[-1] >= county_latest_year,
        "amount_basis": "annual_bill",
        "layers": ["mecklenburg_taxbill_search"],
        "parcel_key": _normalize_parcel(parcel),
        "source_url": f"{BASE}BillSearchResults.aspx?ParcelNum={parcel}",
    }


# ---------------------------------------------------------------------------
# orchestration
# ---------------------------------------------------------------------------

async def enrich_mecklenburg_tax(listings: Iterable[Listing], *,
                                 client: Optional[httpx.AsyncClient] = None) -> dict[str, Any]:
    """Walk not-yet-checked Mecklenburg NC board rows and stamp raw['two_year_delinquent']
    (always, on a real search answer) and raw['multi_year_delinquent_tax'] (when the parcel's
    own live Bill Search history shows real repeat delinquency). `client` is exposed for tests
    and the standalone probe; the real pipeline lets it default to a fresh httpx.AsyncClient."""
    stats = {"eligible": 0, "attempted": 0, "two_year_written": 0, "multiyear_qualified": 0,
             "multiyear_insufficient_years": 0, "no_results": 0, "fetch_errors": 0,
             "skipped_cap": 0, "skipped_budget": 0, "circuit_tripped": 0}
    if not _ENABLED:
        return stats
    targets = [li for li in listings if _eligible(li)]
    stats["eligible"] = len(targets)
    if not targets:
        return stats
    capped = targets[:MAX_ROWS]
    stats["skipped_cap"] = len(targets) - len(capped)

    today = date.today()
    start = time.monotonic()
    sem = asyncio.Semaphore(CONCURRENCY)
    state = {"consec_fail": 0, "tripped": False}

    async def _walk(cli: httpx.AsyncClient) -> None:
        async def one(li: Listing) -> None:
            if state["tripped"] or (time.monotonic() - start) > BUDGET_S:
                stats["skipped_budget"] += 1
                return
            parcel = _candidate_parcel(li)
            async with sem:
                if state["tripped"] or (time.monotonic() - start) > BUDGET_S:
                    stats["skipped_budget"] += 1
                    return
                rows, status = await _fetch_parcel_bills(cli, parcel)
            stats["attempted"] += 1
            if not isinstance(li.raw, dict):
                li.raw = {}
            if status == "ok":
                state["consec_fail"] = 0
            elif status != "no_results":
                state["consec_fail"] += 1
                if _BREAKER_FAILS and state["consec_fail"] >= _BREAKER_FAILS:
                    state["tripped"] = True
                    stats["circuit_tripped"] = 1
                    log.warning("mecklenburg_mydt.circuit_open", attempted=stats["attempted"])
            if status == "no_results":
                stats["no_results"] += 1
                li.raw[CHECKED_KEY] = status
                return
            if status != "ok":
                stats["fetch_errors"] += 1
                li.raw[CHECKED_KEY] = status
                return
            li.raw[TYD_KEY] = build_two_year_block(parcel, rows, today=today)
            stats["two_year_written"] += 1
            block = build_multiyear_block(parcel, rows, today=today)
            if block is None:
                stats["multiyear_insufficient_years"] += 1
            else:
                block["checked_at"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
                li.raw[MYDT_KEY] = block
                stats["multiyear_qualified"] += 1

        await asyncio.gather(*(one(li) for li in capped))

    if client is not None:
        await _walk(client)
    else:
        async with httpx.AsyncClient(timeout=_REQUEST_TIMEOUT_S, follow_redirects=True,
                                     headers={"User-Agent": _UA}) as cli:
            await _walk(cli)

    log.info("mecklenburg_mydt.done", **stats)
    return stats
