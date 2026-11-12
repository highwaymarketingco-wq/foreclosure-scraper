"""Rowan County NC multi-year property-tax delinquency, read LIVE per parcel from
tax.rowancountync.gov -- feeds both raw['multi_year_delinquent_tax'] and
raw['two_year_delinquent'], the two shared contracts gap_matrix.py's own checked_columns()/
positive_columns() already read.

WHY THIS EXISTS. gap_matrix lists both columns as Rowan "sourced-not-built" (~4,594 applicable
    rows each, source "tax/property card: tax.rowancountync.gov"). Rowan's own board source,
    scrapers/counties_nc/rowan_delinquent_tax.py, reads the county's published "Delinquent
    Taxpayer List" XLS -- a SINGLE tax year's snapshot per parcel (one row, one `tax_year`, one
    `balance_due`), so there is no multi-year history already sitting on the row the way
    Transylvania's own per-parcel scraper already carries (see
    enrichment_transylvania_multiyear_tax.py's module docstring for that different case). This
    module is a genuine new live fetcher.

THE SITE: tax.rowancountync.gov, a Tyler Technologies "iasWorld" public CAMA/tax search -- the
    SAME host and the SAME two calls verification/verifiers/tax_lien_rowan.py already documents
    and verifies a tax_lien CLAIM against (its own module docstring: live-checked 2026-10-18,
    no login, no CAPTCHA, no click-through). That module and its sibling
    enrichment_rowan_rollback_exposure.py are NOT imported here (this file is deliberately
    self-contained, its own new file, no edits to either) -- the request/response SHAPE below
    is independently re-verified live, not guessed, against the exact same documented calls:

    GET  {BASE}/search/commonsearch.aspx?mode=realprop
         -> an ASP.NET WebForms page: __VIEWSTATE, __VIEWSTATEGENERATOR, __EVENTVALIDATION.
    POST same URL  {..., inpParid: <parcel id>, hdListType: 'realprop', ...}
         -> an HTML results grid, one row per matching parcel. `inpParid` matches by PREFIX (a
            bare "379" matched 32 rows live), so a result only counts when its OWN "Parcel ID"
            grid column is an EXACT alnum match of the parcel searched -- never owner name (this
            module matches by parcel only, the same conservative discipline every tax-matching
            module in this codebase already uses, to avoid attaching one owner's bill history to
            a different person's lead). Each row carries `selectSearchRow('../Datalets/
            Datalet.aspx?sIndex=N&idx=M')`: sIndex/idx are the detail page's only handle, valid
            only within the SAME cookie session as the search that produced them.
    GET  {BASE}/Datalets/Datalet.aspx?mode=tax_bills_int&sIndex=<N>&idx=<M>
         -> the parcel's "Tax Bills" tab: one row per levy year, as far back as the county keeps
            it. `Amount Due` is what is owed on that year's bill TODAY (already netting
            payments/adjustments/interest).

LIVE-VERIFIED 2026-11-05 (standalone script against the real portal; see the task's own proof
    requirement -- not the board, not main.py). Plain httpx (no curl_cffi / TLS impersonation
    needed -- tried first per this project's convention, worked on the first request, so no
    fallback is wired for this one). Searched 4 REAL currently-delinquent parcels pulled fresh
    from Rowan's own published XLS (the same file rowan_delinquent_tax.py reads) by exact
    `inpParid`, each returning exactly one exact-match row and a real `tax_bills_int` table back
    to 2016 (10 years on every parcel checked):
      parcel "324A021"  (owner redacted here, already public on the county's own site) -- Amount
          Due > 0 (late) in matured years 2024 ($184.22) and 2025 ($1,218.09); 2026 (the current,
          not-yet-due bill) separately owes $0.00 (already paid ahead of its own due date) --
          2 matured delinquent years, clears the gate.
      parcel "051 054" -- matured 2024 ($82.61) and 2025 ($2,002.59) both > 0 -- 2 matured years.
      parcel "804 062" -- matured 2024 ($1,931.64) and 2025 ($2,675.86) both > 0 -- 2 matured
          years, consecutive.
      parcel "245D256" -- only 2025 ($1,400.88) is matured and > 0 (2024 and every earlier year
          on file is $0.00, paid); correctly does NOT clear the >=2-matured-year gate here, and
          build_two_year_block() correctly reports is_two_year_plus=False for it while still
          answering (the "answered but didn't qualify" case).
    Full JSON dumps of all 4 live responses are in this task's own proof script output.

MATCH METHOD: parcel_id only, exact alnum match of the grid's own "Parcel ID" column -- never a
    prefix match, never owner name (see THE SITE above). Matching strips every non-alphanumeric
    character from both sides before comparing, which absorbs incidental formatting noise
    (double spaces, a stray trailing dot) on an id that is ALREADY the county's own short PARID
    -- true for rows sourced from scrapers/counties_nc/rowan_delinquent_tax.py, which reads its
    `parcel_number` from this SAME iasWorld export (live-confirmed: that XLS prints ids with the
    space in place, e.g. "804 062", "051 00801"). It does NOT bridge a genuinely different
    numbering scheme -- live-tested 2026-11-05: searching the SAME real parcel as "804062" (no
    space) returns ZERO results, because the portal's own server-side prefix match compares the
    literal query string, space included, before this module ever sees a candidate row to
    filter. A board row carrying a bare GIS PIN instead of the iasWorld PARID (e.g. this
    county's own parcel_cache, a different source entirely) will not be found here -- the same
    data-contract assumption enrichment_rowan_rollback_exposure.py's own module docstring already
    documents and confirms true for the real board ("0 shape mismatches" across 17 live rows).

CONCURRENCY. tax_lien_rowan.py's own module docstring documents a real hazard on this exact
    host: the search POST stores its own result set in SERVER-SIDE session state keyed by
    sIndex, so two searches racing on ONE shared cookie session can have one search's "sIndex=0"
    overwritten by another's before the matching detail GET fires -- not just a client-side
    __VIEWSTATE race, a real server-side one. Its sibling enrichment_rowan_rollback_exposure.py
    avoids this by running fully sequential (CONCURRENCY=1) against one shared client. This
    module instead gives each concurrent WORKER its own independent httpx.AsyncClient (its own
    cookie jar, so its own distinct ASP.NET session on the server) -- there is then no shared
    mutable state between workers to race on at all, while still allowing real concurrency.
    Within one worker, requests are strictly sequential and the worker's own __VIEWSTATE is
    refreshed after every POST, the same discipline tax_lien_rowan.search() uses.

GATE (multi_year_delinquent_tax). Needs >= MIN_YEARS (2) distinct years with Amount Due > 0 AND
    at least one of them MATURED (tax_calendar.levy_year_is_delinquent, NC's statutory Jan-6
    rule) -- a parcel whose only unpaid bills are this year's and next year's current, not-yet-
    due bill is not repeat delinquency. two_year_delinquent is written UNCONDITIONALLY whenever
    a real bill-history answer comes back (even a "doesn't qualify" one), the same convention
    enrichment_berkeley_two_year_delinquent.py / enrichment_gaston_multiyear_tax.py already use
    for this sibling key -- its own presence is this module's "already checked" idempotency
    marker, so a row is re-attempted only if NEITHER shared key is on it yet.

SHAPE. multi_year_delinquent_tax is byte-shape-compatible with the Buncombe/Oconee/Pickens
    generic scraper's own block (reuses its `_longest_run`/`_trend` helpers verbatim, same reuse
    enrichment_gaston_multiyear_tax.py and enrichment_transylvania_multiyear_tax.py already
    established for this key).

PRIVACY. No owner name is ever read from the search results or stored -- only tax-year amounts
    and the parcel's own id.

SCALE / BUDGET. One live search + one live detail fetch per not-yet-checked Rowan row. Capped
    per run (ROWAN_MYDT_MAX, default 300) and wall-clock-budgeted (ROWAN_MYDT_BUDGET_S, default
    600s), the same shape enrichment_gaston_multiyear_tax.py already uses for its own per-parcel
    network enrichment. A consecutive-failure breaker (ROWAN_MYDT_BREAKER_FAILS, per worker) trips
    early on a dead/blocking portal rather than grinding through the whole capped batch.

Free, public, no login, no CAPTCHA (same host tax_lien_rowan.py already reads every scheduled
run) -- but it IS a live per-row network cost, so (like enrichment_qpaybill_tax.py) this defaults
OFF. Gate on with FORECLOSURE_ROWAN_MULTIYEAR_TAX=1.
Tunables: ROWAN_MYDT_MAX (default 300), ROWAN_MYDT_BUDGET_S (default 600),
          ROWAN_MYDT_CONCURRENCY (default 3, see CONCURRENCY above),
          ROWAN_MYDT_TIMEOUT_S (default 30), ROWAN_MYDT_PACE_S (default 0.5, per-worker politeness
          delay between requests), ROWAN_MYDT_BREAKER_FAILS (default 6, per worker),
          ROWAN_MYDT_MIN_YEARS (default 2).
"""
from __future__ import annotations

import asyncio
import os
import re
import time
from datetime import date
from typing import Any, Iterable, Optional

import httpx
import structlog

from . import tax_calendar
from .models import Listing, _normalize_parcel
from .scrapers.counties_generic.multi_year_delinquent_tax import _longest_run, _trend

log = structlog.get_logger()

BASE = "https://tax.rowancountync.gov"
SEARCH_URL = f"{BASE}/search/commonsearch.aspx?mode=realprop"

MULTIYEAR_KEY = "multi_year_delinquent_tax"
TWO_YEAR_KEY = "two_year_delinquent"
SOURCE_SLUG = "enrichment_rowan_multiyear_tax"
STATE = "NC"
COUNTY = "Rowan"

_ENABLED = os.environ.get("FORECLOSURE_ROWAN_MULTIYEAR_TAX") == "1"
MAX_LISTINGS = int(os.environ.get("ROWAN_MYDT_MAX", "300"))
BUDGET_S = float(os.environ.get("ROWAN_MYDT_BUDGET_S", "600"))
CONCURRENCY = max(1, int(os.environ.get("ROWAN_MYDT_CONCURRENCY", "3")))
TIMEOUT_S = float(os.environ.get("ROWAN_MYDT_TIMEOUT_S", "30"))
PACE_S = float(os.environ.get("ROWAN_MYDT_PACE_S", "0.5"))
BREAKER_FAILS = int(os.environ.get("ROWAN_MYDT_BREAKER_FAILS", "6"))
MIN_YEARS = int(os.environ.get("ROWAN_MYDT_MIN_YEARS", "2"))

_UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
       "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")
_HEADERS = {"User-Agent": _UA, "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8"}

_HIDDEN_NAMES = ("__VIEWSTATE", "__VIEWSTATEGENERATOR", "__EVENTVALIDATION")
_HIDDEN_RE = {n: re.compile(rf"(?:id|name)=['\"]{n}['\"][^>]*value=['\"]([^'\"]*)['\"]")
             for n in _HIDDEN_NAMES}
_ROW_MARK = re.compile(r"selectSearchRow\('\.\./Datalets/Datalet\.aspx\?sIndex=(\d+)&idx=(\d+)'\)\"")
_ROW_CELL = re.compile(r"margin-left:3px;'>([^<]*)</div>")
_BILL_CELL = re.compile(r"class=.DataletData.>([^<]*)</td>")
_YEAR_RE = re.compile(r"^\d{4}$")


def _alnum(s: Optional[str]) -> str:
    return re.sub(r"[^0-9A-Za-z]", "", s or "").upper()


def _money(v: Any) -> float:
    s = re.sub(r"[^\d.\-]", "", str(v or ""))
    if not s or s in (".", "-"):
        return 0.0
    try:
        return round(float(s), 2)
    except ValueError:
        return 0.0


def hidden_fields(html: str) -> dict[str, str]:
    return {n: (m.group(1) if (m := rx.search(html)) else "") for n, rx in _HIDDEN_RE.items()}


def search_form(hidden: dict[str, str], parid: str) -> dict[str, str]:
    form = dict(hidden)
    form.update({
        "PageNum": "1", "SortDir": "", "PageSize": "25",
        "hdAction": "", "hdIndex": "", "sIndex": "",
        "hdListType": "realprop", "hdJur": "", "hdSelectAllChecked": "0",
        "inpParid": parid, "inpNo": "", "inpStreet": "", "inpZip": "",
        "inpOwner1": "", "inpOwnerNo": "", "inpBook": "", "inpBookPage": "",
        "hdTaxYear": "", "mode": "realprop", "mask": "", "param1": "", "searchimmediate": "0",
        "__EVENTTARGET": "", "__EVENTARGUMENT": "",
    })
    return form


def parse_results(html: str) -> list[dict]:
    """One dict per result row: sIndex, idx, parcel_id, owner, account, address, tax_year (the
    grid's own 5 text columns, in their live-confirmed order)."""
    marks = list(_ROW_MARK.finditer(html))
    out = []
    for i, m in enumerate(marks):
        start = m.end()
        end = marks[i + 1].start() if i + 1 < len(marks) else len(html)
        cells = _ROW_CELL.findall(html[start:end])[:5]
        if len(cells) < 5:
            continue
        out.append({"sIndex": m.group(1), "idx": m.group(2), "parcel_id": cells[0],
                    "owner": cells[1], "account": cells[2], "address": cells[3],
                    "tax_year": cells[4]})
    return out


def parse_bills(html: str) -> Optional[list[dict]]:
    """[{year, amount_due}] off the TAX_BILLS_INT datalet, oldest-or-newest as the page prints
    it (not relied upon -- callers sort); None when the datalet itself isn't on the page."""
    i = html.find("name='TAX_BILLS_INT'")
    if i < 0:
        return None
    cells = _BILL_CELL.findall(html[i:i + 20000])
    rows = []
    for k in range(0, len(cells) - 8, 9):
        chunk = cells[k:k + 9]
        if not _YEAR_RE.match(chunk[0].strip()):
            break  # the table's own "Total:" row -- stop, same discipline tax_lien_rowan uses
        rows.append({"year": int(chunk[0].strip()), "amount_due": _money(chunk[6])})
    return rows


# ---------------------------------------------------------------------------
# pure block builders
# ---------------------------------------------------------------------------
def build_two_year_block(bills: list[dict], *, today: Optional[date] = None) -> dict:
    """Pure: the raw['two_year_delinquent'] wrapper, written unconditionally once a real bill
    history answer comes back -- even a zero-matured-year answer states `is_two_year_plus`
    truthfully, the same convention enrichment_berkeley_two_year_delinquent.py and
    enrichment_gaston_multiyear_tax.py's own build_two_year_block() already use for this key."""
    today = today or date.today()
    years = sorted({b["year"] for b in bills or () if (b.get("amount_due") or 0) > 0})
    matured = tax_calendar.completed_delinquent_years(years, STATE, COUNTY, today)
    return {
        "is_two_year_plus": len(matured) >= 2,
        "years": len(matured),
        "oldest_year": min(matured) if matured else None,
        "source": SOURCE_SLUG,
    }


def build_block(bills: list[dict], parcel_id: str, *, today: Optional[date] = None) -> Optional[dict]:
    """Pure: the raw['multi_year_delinquent_tax'] block from one parcel's full tax_bills_int
    history (parse_bills' own rows), or None when the parcel doesn't clear the multi-year gate
    (fewer than MIN_YEARS unpaid years, or no MATURED unpaid year)."""
    today = today or date.today()
    per_year: dict[int, float] = {}
    for b in bills or ():
        due = b.get("amount_due") or 0.0
        if due > 0:
            per_year[b["year"]] = due
    years = sorted(per_year)
    if len(years) < MIN_YEARS:
        return None
    matured = [y for y in years if tax_calendar.levy_year_is_delinquent(y, STATE, COUNTY, today)]
    if not matured:
        return None
    current = [y for y in years if y not in matured]
    total_owed = round(sum(per_year.values()), 2) or None
    matured_owed = round(sum(per_year[y] for y in matured), 2) or None
    # Per-parcel proxy for "the county's own newest published year" -- this module has no
    # cross-row board access either, same documented approximation
    # enrichment_gaston_multiyear_tax.py / enrichment_transylvania_multiyear_tax.py both carry.
    county_latest_year = max((b["year"] for b in bills), default=years[-1])
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
        "layers": [SOURCE_SLUG],
        "parcel_key": _normalize_parcel(parcel_id),
    }


# ---------------------------------------------------------------------------
# eligibility
# ---------------------------------------------------------------------------
def _county_key(li: Listing) -> str:
    return (li.county or "").replace(" County", "").strip().lower()


def _already_done(li: Listing) -> bool:
    if not isinstance(li.raw, dict):
        return False
    return isinstance(li.raw.get(MULTIYEAR_KEY), dict) or isinstance(li.raw.get(TWO_YEAR_KEY), dict)


def _eligible(li: Listing) -> bool:
    return (
        (li.state or "").strip().upper() == STATE
        and _county_key(li) == COUNTY.lower()
        and bool(_alnum(li.parcel_id))
        and not _already_done(li)
    )


# ---------------------------------------------------------------------------
# live fetch (one worker = one independent client/session -- see CONCURRENCY in module doc)
# ---------------------------------------------------------------------------
async def _seed(client: httpx.AsyncClient) -> dict[str, str]:
    r = await client.get(SEARCH_URL, timeout=TIMEOUT_S)
    if r.status_code != 200:
        raise RuntimeError(f"search page HTTP {r.status_code}")
    return hidden_fields(r.text)


async def search_and_fetch(client: httpx.AsyncClient, hidden: dict[str, str],
                           parid: str) -> tuple[Optional[str], Optional[list[dict]], str, dict[str, str]]:
    """(matched_parcel_id, bills, status, fresh_hidden) for one parcel search + detail fetch on
    the caller's own session. `fresh_hidden` is the viewstate to use for the NEXT call on this
    SAME client (refreshed after the POST, same discipline tax_lien_rowan.search() uses)."""
    form = search_form(hidden, parid)
    r = await client.post(SEARCH_URL, data=form, headers={"Referer": SEARCH_URL}, timeout=TIMEOUT_S)
    if r.status_code != 200:
        return None, None, f"search_http_{r.status_code}", hidden
    fresh = hidden_fields(r.text)
    next_hidden = fresh if fresh.get("__VIEWSTATE") else hidden
    results = parse_results(r.text)
    norm = _alnum(parid)
    matches = [row for row in results if _alnum(row["parcel_id"]) == norm]
    if not matches:
        return None, None, "parcel_not_found", next_hidden
    if len(matches) > 1:
        return None, None, "ambiguous_parcel", next_hidden
    match = matches[0]
    url = f"{BASE}/Datalets/Datalet.aspx?mode=tax_bills_int&sIndex={match['sIndex']}&idx={match['idx']}"
    rd = await client.get(url, headers={"Referer": SEARCH_URL}, timeout=TIMEOUT_S)
    if rd.status_code != 200:
        return match["parcel_id"], None, f"detail_http_{rd.status_code}", next_hidden
    bills = parse_bills(rd.text)
    if not bills:
        return match["parcel_id"], None, "no_bills", next_hidden
    return match["parcel_id"], bills, "ok", next_hidden


async def enrich_rowan_multiyear_tax(listings: Iterable[Listing],
                                     *, today: Optional[date] = None) -> dict[str, Any]:
    """Walk not-yet-checked Rowan NC board rows, search tax.rowancountync.gov by exact parcel_id,
    fetch that result's tax_bills_int history, and stamp raw['two_year_delinquent']
    (unconditionally, on any real answer) plus raw['multi_year_delinquent_tax'] (only when it
    clears the repeat-delinquency gate)."""
    stats: dict[str, Any] = {
        "eligible": 0, "searched": 0, "ok": 0, "parcel_not_found": 0, "ambiguous_parcel": 0,
        "no_bills": 0, "errors": 0, "two_year_written": 0, "multiyear_qualified": 0,
        "skipped_cap": 0, "skipped_budget": 0, "circuit_open": 0,
    }
    if not _ENABLED:
        return stats
    targets = [li for li in listings if _eligible(li)]
    stats["eligible"] = len(targets)
    if not targets:
        return stats
    capped = targets[:MAX_LISTINGS]
    stats["skipped_cap"] = len(targets) - len(capped)

    start = time.monotonic()
    deadline = start + BUDGET_S
    lock = asyncio.Lock()

    # Split into CONCURRENCY contiguous chunks -- each worker owns one client/session end to
    # end, so there is never a shared mutable viewstate/server-session for two in-flight
    # searches to race on (see CONCURRENCY in the module docstring).
    chunks: list[list[Listing]] = [[] for _ in range(CONCURRENCY)]
    for i, li in enumerate(capped):
        chunks[i % CONCURRENCY].append(li)

    async def bump(key: str) -> None:
        async with lock:
            stats[key] += 1

    async def worker(chunk: list[Listing]) -> None:
        if not chunk:
            return
        consec_fail = 0
        tripped = False
        async with httpx.AsyncClient(timeout=TIMEOUT_S, follow_redirects=True,
                                     headers=_HEADERS) as client:
            try:
                hidden = await _seed(client)
            except Exception:  # noqa: BLE001
                await bump("errors")
                for _ in chunk:
                    await bump("errors")
                return
            for li in chunk:
                if tripped or time.monotonic() > deadline:
                    await bump("skipped_budget")
                    continue
                pid = str(li.parcel_id or "").strip()
                try:
                    matched_pid, bills, status, hidden = await search_and_fetch(client, hidden, pid)
                except Exception:  # noqa: BLE001
                    status = "fetch_failed"
                    matched_pid = bills = None
                await bump("searched")
                if status != "ok":
                    bucket = status if status in stats else "errors"
                    await bump(bucket if bucket in stats else "errors")
                    consec_fail = 0 if status in ("parcel_not_found", "ambiguous_parcel", "no_bills") \
                        else consec_fail + 1
                    if BREAKER_FAILS and consec_fail >= BREAKER_FAILS:
                        tripped = True
                        await bump("circuit_open")
                    await asyncio.sleep(PACE_S)
                    continue
                consec_fail = 0
                await bump("ok")
                if not isinstance(li.raw, dict):
                    li.raw = {}
                if TWO_YEAR_KEY not in li.raw:
                    li.raw[TWO_YEAR_KEY] = build_two_year_block(bills, today=today)
                    await bump("two_year_written")
                if MULTIYEAR_KEY not in li.raw:
                    block = build_block(bills, matched_pid or pid, today=today)
                    if block is not None:
                        li.raw[MULTIYEAR_KEY] = block
                        await bump("multiyear_qualified")
                await asyncio.sleep(PACE_S)

    await asyncio.gather(*(worker(chunk) for chunk in chunks))
    log.info("rowan_multiyear_tax.done", **stats)
    return stats
