"""Cabarrus County NC multi-year delinquent-tax HISTORY, read live per parcel from the same
classic ITS.NET "TaxBill.aspx" bill search verification/verifiers/tax_lien_itsnet.py already
drives for Iredell and Chowan -- the SAME vendor, a new tenant, not a new integration.

WHY THIS EXISTS (docs/gap_matrix/gap_list_2026-10-19.csv, read before writing a line here).
    NC Cabarrus "two_year_delinquent" (2,920 applicable) and "multi_year_delinquent_tax" (2,920)
    both show sourced-not-built, source "tax/property card: tax.cabarruscounty.us", built=no.
    Checked first (per this task's own brief) for a prior Cabarrus tax reader anywhere in this
    codebase: none. grep for "cabarrus" across every enrichment_*.py and scrapers/ file turns up
    only unrelated hits (ROD liens via nc_logan_blazor, NC OneMap FIPS tables, a bankruptcy
    city->county map, enrichment_county_pin's FIPS table) -- there is no prior Cabarrus tax
    scraper or enricher to restate from, so this is a genuine new build, not a Dorchester/
    Berkeley-shaped "already fetched, never restated under the shared key" bug. Confirmed
    directly against the live board too (board_stream, 2026-10-20): all 2,920 Cabarrus NC rows
    carry zero raw keys containing "tax"/"delinq"/"cabarrus".

    LIVE-VERIFIED 2026-10-20 (this session, directly against the real portal, not assumed).
    tax.cabarruscounty.us answers a plain "Basic Search" ASP.NET WebForms site (no CAPTCHA, no
    login, no terms click-through) with a "Tax Bill Search" tab at /TaxBill.aspx -- the EXACT
    classic ITS.NET product tax_lien_itsnet.py already drives for Iredell/Chowan: identical
    "ctl00$contentplaceholdertaxBillSearch$UsercontrolTaxbillSearch$" field prefix, identical
    gridviewSearchResults grid shape (Year Bill#, Account#, Owner Name, Owner Name2, Orig Levy,
    Balance, Disc Year, Property ID, Property Address). tax_lien_itsnet.build_form()/
    parse_grid() work on it completely UNCHANGED; the only new thing needed was the parcel-
    number FIELD SHAPE (search_fields()'s new "sheet_block_parcel" kind, added there, Iredell/
    Chowan untouched).

    5 real board PINs searched live (2026-10-20, Cabarrus's own ctrlParcelNumber Sheet+Block+
    Parcel+Interest fields, no login): 56221770270000 -- 22 real bills back to 2005, every year
    paid $0.00 (SECHLER/METTS-WAKELAND, real owner names, real addresses). 56133499440000 -- 20
    years back to 2005, every year paid (CABARRUS ARMS ASSOC / CABARRUS INVESTORS LLC).
    56301830170000 -- 2 bills: 2025 paid, 2026 unpaid $13,944.50 but NOT YET LATE (NC's Jan-6-of-
    next-year delinquency date has not passed) -- correctly a non-qualifying current bill, not a
    multi-year delinquency. 56223800390000 -- 5 years back to 2014 (ROG PRESERVATION LLC), all
    paid. One PIN (56218292980000) answered no grid row at all (the board's own PIN not on file
    on this vendor, or a typo) -- the __VIEWSTATE was still present on that answer, the same
    "a real empty answer, not a broken page" shape tax_lien_itsnet._search() already codifies.
    No real multi-year delinquency surfaced in this 5-PIN canary -- the same "most sampled
    parcels are paid current" shape every prior county's recon in this codebase has found; the
    real yield is in the ~2,920-row backlog this canary cannot represent by itself.

PARCEL SHAPE: THE BOARD'S OWN PIN IS THE SEARCH KEY, NO BRIDGE NEEDED. Cabarrus's board
    parcel_id is already a 14-digit string (confirmed live against 8 real board rows,
    board_stream, 2026-10-20: "56218292980000" etc.) that splits EXACTLY into TaxBill.aspx's own
    4-part control: Sheet (4 digits) + Block (2) + Parcel (4) + Interest (4) -- the identical
    digits the live grid's own `Property ID` column echoes back unchanged (verified: searching
    56221770270000 returns bills whose `ids[0]` is the literal string "56221770270000"). Simpler
    than Iredell (whose MAP+BLK+PIN uses only 10 of the row's digits) and simpler than Wake (a
    PIN<->REID bridge through NC OneMap) or Catawba's own AlternateParcelIdentifier field: no
    bridge, no lookup, the row's own parcel_id is submitted as-is.

SHAPE. Reuses tax_lien_itsnet.PORTALS["Cabarrus"] / .search_fields() / .fetch_grid() /
    .parse_grid() verbatim (that module's own additive third tenant -- Iredell/Chowan completely
    unchanged) so raw['multi_year_delinquent_tax'] here is byte-shape-compatible with the
    Catawba/Wake/Randolph/Gaston blocks: tax_binding.BLOCK_PARCEL_FIELDS
    ["multi_year_delinquent_tax"] = ("parcel_key",), enrichment_tax_owed.py's FIELD_PRIORITY
    exact-key read of "total_due", and web_artifact.RAW_KEEP's "*" wildcard all already expect
    this shape -- no downstream wiring needed, and that existing FIELD_PRIORITY entry already
    generically promotes this block into raw['tax_owed'] -> raw['tax_aging_surfaced']
    (enrichment_tax_aging.py) for free, the same bonus enrichment_catawba_multiyear_tax.py's own
    block produces for Catawba.

    raw['two_year_delinquent'] IS WRITTEN HERE (Catawba's sibling module does not write it --
    something else already covers Catawba for that specific column, per that module's own
    docstring; Cabarrus has no such prior coverage at all). gap_matrix.py reads
    raw['two_year_delinquent'] directly (checked_columns(), scripts/gap_matrix.py ~line 187-189),
    not derived from multi_year_delinquent_tax, so this module writes it unconditionally on every
    real search answer (even zero or one matured year states `is_two_year_plus` truthfully
    either way) -- the same "years is a count, written for every row with a real answer"
    discipline enrichment_qpaybill_multiyear_tax.build_two_year_block() and the Dorchester/
    Berkeley restaters already use for this same shared key.

GATE. raw['two_year_delinquent'] is written for every row a search actually answers (status
    "ok", even a zero-bill or all-paid answer -- "0 matured years" states the truth). raw
    ['multi_year_delinquent_tax'] only when >=MIN_YEARS (2) MATURED/late years still carry a
    balance today (tax_calendar.completed_delinquent_years, NC's Jan-6-of-next-year rule) -- a
    parcel whose only unpaid bill is this year's current, not-yet-due one (56301830170000 above)
    is not repeat delinquency.

SCALE / BUDGET. One live search per not-yet-checked Cabarrus row, capped (CABARRUS_MYDT_MAX,
    default 300) and wall-clock-budgeted (CABARRUS_MYDT_BUDGET_S, default 600s) -- the identical
    shape enrichment_catawba_multiyear_tax.py / enrichment_wake_multiyear_tax.py already use.
    Idempotent via raw['_cabarrus_mydt_checked'] on a row whose search failed to produce a usable
    grid (parcel_unresolvable / fetch_failed / results_paged), so later runs don't re-walk the
    same unchecked rows forever; a row that got a real grid answer needs no separate sentinel
    because raw['two_year_delinquent'] is itself written unconditionally on that path. Gate off
    entirely with FORECLOSURE_CABARRUS_MYDT=0.

PRIVACY. No owner name or mailing address is read or written here -- only the board's own PIN
    (already public) and tax-year amounts land in raw['multi_year_delinquent_tax'] /
    raw['two_year_delinquent'].
"""
from __future__ import annotations

import asyncio
import os
import time
from datetime import date, datetime, timezone
from typing import Any, Iterable, Optional

import structlog

from . import tax_calendar
from .models import Listing, _normalize_parcel
from .scrapers.counties_generic.multi_year_delinquent_tax import _longest_run, _trend
from .verification.fetch import Fetcher
from .verification.verifiers import _tax_common as tc
from .verification.verifiers import tax_lien_itsnet as itsnet

log = structlog.get_logger()

MYDT_KEY = "multi_year_delinquent_tax"
TYD_KEY = "two_year_delinquent"
CHECKED_KEY = "_cabarrus_mydt_checked"
COUNTY = "Cabarrus"
SOURCE_SLUG = "verification.verifiers.tax_lien_itsnet"

ENABLED = os.environ.get("FORECLOSURE_CABARRUS_MYDT") != "0"
MAX_ROWS = int(os.environ.get("CABARRUS_MYDT_MAX", "300"))
BUDGET_S = float(os.environ.get("CABARRUS_MYDT_BUDGET_S", "600"))
CONCURRENCY = int(os.environ.get("CABARRUS_MYDT_CONCURRENCY", "4"))
MIN_YEARS = int(os.environ.get("CABARRUS_MYDT_MIN_YEARS", "2"))

_PORTAL = itsnet.PORTALS[COUNTY]


def _county_key(li: Listing) -> str:
    return (li.county or "").replace(" County", "").strip().lower()


def _already_done(li: Listing) -> bool:
    if not isinstance(li.raw, dict):
        return False
    return isinstance(li.raw.get(TYD_KEY), dict) or bool(li.raw.get(CHECKED_KEY))


def _eligible(li: Listing) -> bool:
    return (
        (li.state or "").strip().upper() == "NC"
        and _county_key(li) == COUNTY.lower()
        and bool(tc.alnum(str(li.parcel_id or "")))
        and not _already_done(li)
    )


# ---------------------------------------------------------------------------
# pure: one parcel's grid answer -> matured/unpaid years (shared by both blocks)
# ---------------------------------------------------------------------------

def _years_matured_and_balances(pin: str, bills: list[dict],
                                today: date) -> tuple[list[int], list[int], dict[int, float]]:
    """(years with a balance owed today, the MATURED/late subset of those,
    {year: balance}) for one parcel's own bills -- only bills whose own `ids` actually carry
    this PIN count (the search answers for the submitted fields already, so this is a belt-and-
    suspenders check, same discipline as tax_lien_itspublic.bills_of() /
    enrichment_catawba_multiyear_tax.build_block())."""
    want = tc.alnum(pin)
    per_year: dict[int, float] = {}
    for b in bills or ():
        if want not in {tc.alnum(i) for i in (b.get("ids") or ())}:
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
    matured = tax_calendar.completed_delinquent_years(years, "NC", COUNTY, today)
    return years, matured, per_year


def build_two_year_block(pin: str, bills: list[dict], *, today: Optional[date] = None) -> dict:
    """Pure: the raw['two_year_delinquent'] wrapper from one parcel's full grid answer, written
    unconditionally once a search actually answers -- even a zero-matured-year answer states
    `is_two_year_plus` truthfully, the same "years is a count" discipline every sibling
    two_year_delinquent producer in this codebase already uses."""
    today = today or date.today()
    _, matured, _ = _years_matured_and_balances(pin, bills, today)
    return {
        "is_two_year_plus": len(matured) >= 2,
        "years": len(matured),
        "oldest_year": min(matured) if matured else None,
        "source": SOURCE_SLUG,
    }


def build_multiyear_block(pin: str, bills: list[dict], *,
                          today: Optional[date] = None) -> Optional[dict]:
    """Pure: the raw['multi_year_delinquent_tax'] block, or None when the parcel doesn't clear
    the multi-year gate (fewer than MIN_YEARS matured/late unpaid years -- a parcel whose only
    unpaid bill is this year's current, not-yet-due one is not repeat delinquency)."""
    today = today or date.today()
    years, matured, per_year = _years_matured_and_balances(pin, bills, today)
    if len(matured) < MIN_YEARS:
        return None
    current = [y for y in years if y not in matured]
    total_owed = round(sum(per_year.values()), 2) or None
    matured_owed = round(sum(per_year[y] for y in matured), 2) or None
    county_latest_year = max((b["year"] for b in bills if b.get("year") is not None), default=years[-1])
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
        "layers": ["cabarrus_itsnet_bill_search"],
        "parcel_key": _normalize_parcel(pin),
        "source_url": _PORTAL.url,
    }


# ---------------------------------------------------------------------------
# live fetch -- reuses tax_lien_itsnet's session/search/parse chain verbatim
# ---------------------------------------------------------------------------

async def _fetch(client: Any, pin: str) -> tuple[Optional[list[dict]], str]:
    """(bills, status) for one Cabarrus PIN via tax_lien_itsnet's own live-proven
    search_fields()/fetch_grid()/parse_grid() chain, reused verbatim. status is "ok" with
    `bills` set (possibly an empty list -- a real, answered, zero-bill parcel) on a successful
    search, else a short machine reason for a sentinel."""
    fields = itsnet.search_fields(_PORTAL, pin)
    if fields is None:
        return None, "parcel_unresolvable"
    try:
        grid = await itsnet.fetch_grid(client, _PORTAL, fields)
    except Exception as exc:  # noqa: BLE001 - every outcome is an answer
        return None, f"fetch_failed:{type(exc).__name__}"
    if grid is None:
        return None, "fetch_failed:no_grid"
    if grid.get("paged"):
        return None, "results_paged"
    return list(grid.get("bills") or []), "ok"


async def enrich_with_cabarrus_multiyear_tax(listings: Iterable[Listing],
                                             *, client: Optional[Any] = None) -> dict[str, Any]:
    """Walk not-yet-checked Cabarrus NC board rows and stamp raw['two_year_delinquent'] (always,
    on a real search answer) and raw['multi_year_delinquent_tax'] (when the parcel's own live
    ITS.NET bill history shows real repeat delinquency). `client` is exposed for tests; the real
    pipeline always lets it default (a fresh Fetcher, this call's own rate limit)."""
    stats = {"eligible": 0, "attempted": 0, "two_year_written": 0, "multiyear_qualified": 0,
             "multiyear_insufficient_years": 0, "fetch_errors": 0,
             "skipped_cap": 0, "skipped_budget": 0}
    if not ENABLED:
        return stats
    targets = [li for li in listings if _eligible(li)]
    stats["eligible"] = len(targets)
    if not targets:
        return stats
    capped = targets[:MAX_ROWS]
    stats["skipped_cap"] = len(targets) - len(capped)

    today = date.today()
    cli = client or Fetcher(min_interval_s=0.2)
    start = time.monotonic()
    sem = asyncio.Semaphore(CONCURRENCY)

    async def one(li: Listing) -> None:
        if (time.monotonic() - start) > BUDGET_S:
            stats["skipped_budget"] += 1
            return
        pin = str(li.parcel_id or "").strip()
        async with sem:
            bills, status = await _fetch(cli, pin)
        stats["attempted"] += 1
        if not isinstance(li.raw, dict):
            li.raw = {}
        if status != "ok":
            stats["fetch_errors"] += 1
            li.raw[CHECKED_KEY] = status
            return
        li.raw[TYD_KEY] = build_two_year_block(pin, bills, today=today)
        stats["two_year_written"] += 1
        block = build_multiyear_block(pin, bills, today=today)
        if block is None:
            stats["multiyear_insufficient_years"] += 1
        else:
            block["checked_at"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
            li.raw[MYDT_KEY] = block
            stats["multiyear_qualified"] += 1

    await asyncio.gather(*(one(li) for li in capped))
    log.info("cabarrus_mydt.done", **stats)
    return stats
