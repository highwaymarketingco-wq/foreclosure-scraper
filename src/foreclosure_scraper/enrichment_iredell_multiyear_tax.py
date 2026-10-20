"""Iredell County NC multi-year delinquent-tax HISTORY, read live per parcel from the same
classic ITS.NET "TaxBill.aspx" bill search verification/verifiers/tax_lien_itsnet.py already
drives for Iredell itself (tax_lien verification) and Chowan -- a SECOND tenant use of a vendor
this module ALREADY talks to, not a new integration, and not even a new PORTAL entry (Iredell's
own Portal("Iredell", ..., "map_blk_pin", (...)) was already there for tax_lien; this is the
same session/search/parse chain reused the way enrichment_cabarrus_multiyear_tax.py reuses it
for a county that previously had zero ITS.NET coverage).

WHY THIS EXISTS (docs/gap_matrix/gap_list_2026-10-20.csv, read before writing a line here).
    NC Iredell "two_year_delinquent" and "multi_year_delinquent_tax" (2,840 applicable each,
    "tax_aging_surfaced" rides along for free, see FOR-FREE below) all show sourced-not-built,
    source "tax/property card: taxweb.iredellcountync.gov", built=no. Checked first (per this
    task's own brief): no prior Iredell MULTI-YEAR reader anywhere in this codebase.
    counties_nc.iredell_delinquent_tax (the only other Iredell tax producer) writes a DIFFERENT
    key (raw['iredell_delinquent_tax'] + raw['tax_owed'], ONE assumed year, no amount) from a
    county ArcGIS "delinquent outline" layer matched through NC OneMap -- a snapshot with no
    parcel number of its own on the layer, not a tax-bill reader, and it has never run as of this
    session (grep across every board row below: zero rows carry that key, zero carry tax_owed).
    This module is the first thing in the codebase to read Iredell's own bill history.

    LIVE-VERIFIED 2026-10-20 (this session, directly against the real portal, not assumed, and
    not assumed-identical to Cabarrus either -- checked). taxweb.iredellcountync.gov/PublicAccess
    answers the identical classic ITS.NET TaxBill.aspx product tax_lien_itsnet.py already has a
    Portal entry for ("map_blk_pin": MAP(4)+BLK(2)+PIN(4) = 10 digits, the same shape the board's
    own parcel_id already carries with a trailing ".000", e.g. "4734693999.000"). 5 real board
    PINs with a well-shaped 10-digit parcel_id were searched live (no login, no CAPTCHA):
    4734693999.000 -- 26 bills back to 2001 (DANIELS NORA W then later owners by sale), every
    year through 2025 paid $0.00, 2026 (current, not-yet-late) unpaid $1,051.28 -- correctly a
    current bill, not a multi-year delinquency. 4745611193.000 -- 26 years back to 2001, every
    year paid including 2026. 4668407535.000 -- 26 years back to 2001, every year through 2025
    paid, 2026 (current) unpaid $3,310.47 -- same current-bill shape as the first. Two PINs
    (4667005970.000, 4745907317.000) answered no grid row at all (__VIEWSTATE still present on
    that answer -- a real empty answer on this vendor, the same shape
    tax_lien_itsnet._search()/enrichment_cabarrus_multiyear_tax._fetch() already codify, not a
    broken page). No real multi-year delinquency surfaced in this 5-PIN canary -- the same
    "most sampled parcels are paid current" shape every prior county's recon in this codebase has
    found (Cabarrus's own canary, Catawba's, Wake's); the real yield is in the backlog this
    canary cannot represent by itself.

PARCEL SHAPE: IREDELL IS THE HARD CASE, NOT THE EASY ONE -- MOST BOARD ROWS HAVE NO USABLE PIN.
    Unlike Cabarrus (whose board parcel_id was already the portal's own 14-digit key on
    essentially every row) and Catawba (a direct AlternateParcelIdentifier match), Iredell's own
    2,840 NC board rows were streamed and counted directly (board_stream, 2026-10-20) BEFORE
    writing this module, because the task brief warned the real yield is "likely much lower" than
    the gap list's row count:
        919 of 2,840 (32.4%)  -- parcel_id already shaped as the portal's own 10-digit MAP+BLK+PIN
                                  (with or without the ".000" suffix the board stores it with)
        1,750 of 2,840 (61.6%) -- NO parcel_id at all (this is the SAME 1,750-row backlog the gap
                                  list's own "parcel_id ... 1,750 applicable rows without it" line
                                  already names as a separate, unfixed gap -- not something this
                                  module's job is to fill)
        168 of 2,840 (5.9%)    -- a parcel_id that IS populated but is not a tax parcel number at
                                  all: "NC01980" etc, the NC dam-safety inventory ID
                                  (counties_generic.state_contamination.nc_dam_safety writes its
                                  own dam ID into parcel_id on rows with no county parcel -- a
                                  pre-existing, unrelated shape, not something to "fix" here)
        3 of 2,840             -- 12/13-digit outliers, also not this shape
    So this module's own realistic ceiling is ~919 rows BEFORE any live-delinquency gate at all,
    not 2,840 -- itsnet.search_fields()'s existing 10-digit check (unchanged, Iredell/Chowan/
    Cabarrus all still gated the same way) already turns every one of the other 1,921 rows into
    the honest "parcel_unresolvable" sentinel per-row, the same discipline every sibling module
    uses; nothing here guesses at a bridge for them.

SHAPE. Reuses tax_lien_itsnet.PORTALS["Iredell"] / .search_fields() / .fetch_grid() /
    .parse_grid() verbatim -- Chowan and Cabarrus entries, and tax_lien_itsnet.verify() itself,
    completely unchanged -- so raw['multi_year_delinquent_tax'] here is byte-shape-compatible
    with the Catawba/Wake/Randolph/Gaston/Cabarrus blocks: tax_binding.BLOCK_PARCEL_FIELDS
    ["multi_year_delinquent_tax"] = ("parcel_key",), enrichment_tax_owed.py's FIELD_PRIORITY
    exact-key read of "total_due", and web_artifact.RAW_KEEP's "*" wildcard all already expect
    this shape -- no downstream wiring needed.

    FOR FREE: that existing FIELD_PRIORITY entry already generically promotes this block into
    raw['tax_owed'] -> raw['tax_aging_surfaced'] (enrichment_tax_aging.py), the same bonus
    enrichment_cabarrus_multiyear_tax.py / enrichment_catawba_multiyear_tax.py produce for their
    own counties -- this module writes no tax_aging_surfaced code of its own, same as them.

    raw['two_year_delinquent'] IS WRITTEN HERE, unconditionally on every real search answer
    (even a zero or one-matured-year answer states `is_two_year_plus` truthfully either way) --
    gap_matrix.py reads it directly (checked_columns(), scripts/gap_matrix.py), not derived from
    multi_year_delinquent_tax, the same "years is a count" discipline every sibling restater uses.

GATE. raw['two_year_delinquent'] is written for every row a search actually answers (status
    "ok", even a zero-bill or all-paid answer). raw['multi_year_delinquent_tax'] only when
    >=MIN_YEARS (2) MATURED/late years still carry a balance today (tax_calendar's NC Jan-6-of-
    next-year rule) -- a parcel whose only unpaid bill is this year's current, not-yet-due one
    (both real non-zero-balance PINs in the 5-PIN canary above) is not repeat delinquency.

SCALE / BUDGET. One live search per not-yet-checked, well-shaped Iredell row, capped
    (IREDELL_MYDT_MAX, default 300) and wall-clock-budgeted (IREDELL_MYDT_BUDGET_S, default 600s)
    -- the identical shape enrichment_cabarrus_multiyear_tax.py / enrichment_catawba_multiyear_tax.py
    already use. Idempotent via raw['_iredell_mydt_checked'] on a row whose search failed to
    produce a usable grid (parcel_unresolvable / fetch_failed / results_paged), so later runs
    don't re-walk the same unchecked or unresolvable rows forever; a row that got a real grid
    answer needs no separate sentinel because raw['two_year_delinquent'] is itself written
    unconditionally on that path. Gate off entirely with FORECLOSURE_IREDELL_MYDT=0.

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
CHECKED_KEY = "_iredell_mydt_checked"
COUNTY = "Iredell"
SOURCE_SLUG = "verification.verifiers.tax_lien_itsnet"

ENABLED = os.environ.get("FORECLOSURE_IREDELL_MYDT") != "0"
MAX_ROWS = int(os.environ.get("IREDELL_MYDT_MAX", "300"))
BUDGET_S = float(os.environ.get("IREDELL_MYDT_BUDGET_S", "600"))
CONCURRENCY = int(os.environ.get("IREDELL_MYDT_CONCURRENCY", "4"))
MIN_YEARS = int(os.environ.get("IREDELL_MYDT_MIN_YEARS", "2"))

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
    enrichment_cabarrus_multiyear_tax._years_matured_and_balances())."""
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
        "layers": ["iredell_itsnet_bill_search"],
        "parcel_key": _normalize_parcel(pin),
        "source_url": _PORTAL.url,
    }


# ---------------------------------------------------------------------------
# live fetch -- reuses tax_lien_itsnet's session/search/parse chain verbatim
# ---------------------------------------------------------------------------

async def _fetch(client: Any, pin: str) -> tuple[Optional[list[dict]], str]:
    """(bills, status) for one Iredell PIN via tax_lien_itsnet's own live-proven
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


async def enrich_with_iredell_multiyear_tax(listings: Iterable[Listing],
                                            *, client: Optional[Any] = None) -> dict[str, Any]:
    """Walk not-yet-checked Iredell NC board rows and stamp raw['two_year_delinquent'] (always,
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
    log.info("iredell_mydt.done", **stats)
    return stats
