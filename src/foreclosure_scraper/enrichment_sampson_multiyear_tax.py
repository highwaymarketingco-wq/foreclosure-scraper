"""Sampson County NC multi-year delinquent-tax HISTORY, read live from the county's own Tyler
Munis "Citizen Self Service" tax-bill search -- the SAME Munis vendor
verification/verifiers/tax_lien_munis.py already drives for New Hanover/Hoke/Lee/Pender/Nash.
Sampson itself was added to that module's own PORTALS dict on 2026-10-29/11-12 (that module's own
PORTALS note has the live-verification story: a bare /citizens/RealEstate/Default.aspx?mode=new
fetch returns the real search form, ParcelIDTextBox present, no "/css" segment needed -- unlike
Pender/Nash's tenants; search() confirmed live against 3 real board parcels, 19-21 real bill rows
each).

WHY THIS EXISTS. gap_matrix's 2026-11-19 "sourced-not-built" sweep found Sampson NC's
    two_year_delinquent / tax_aging_surfaced / multi_year_delinquent_tax all still unbuilt
    (1,016 applicable rows each, source "tax/property card: sampsonnc.munisselfservice.com"),
    THREE-TO-SEVEN DAYS after tax_lien_munis.py's own PORTALS dict already proved Sampson's
    portal live and working. The verifier alone is a CONFIRM/REFUTE check on a claim a row
    already carries from some OTHER producer; Sampson's board rows carry no such claim (0/1,016
    have any multi_year_delinquent_tax or two_year_delinquent block, live-measured via
    board_stream 2026-11-19), so the verifier has nothing to act on -- the exact same gap
    enrichment_pender_multiyear_tax.py's own docstring identified for Pender. This module closes
    it the same way: independently WALKS the live bill history for every row with a resolvable
    parcel_id.

REUSES tax_lien_munis.py's search()/view() DIRECTLY, not a standalone re-implementation like
    Nash's sibling needed: Sampson is already a registered Portal in that module's own PORTALS
    dict (unlike Nash's older, differently-pathed "/css" tenant, which stayed standalone), so this
    module gets that function's existing session cache, per-portal circuit breaker (PortalDown
    after PORTAL_MAX_FAILURES) and parcel/browse-page reuse for free -- the same reduced-code path
    enrichment_pender_multiyear_tax.py already took for the same reason.

CONCURRENCY MUST STAY 1, same constraint Pender's sibling documents: tax_lien_munis._session()
    caches ONE shared ASP.NET WebForms session PER PORTAL (not per parcel); running at >1 races on
    that shared session/__VIEWSTATE and can trip the portal's own error response, poisoning the
    rest of the run via PORTAL_MAX_FAILURES's circuit breaker. Not independently re-tested here;
    inherited as a hard default rather than re-discovering the same race live against a portal
    this project has not yet run at any volume.

PARCEL ID SHAPE. tax_lien_munis.search_id() has no Sampson-specific branch -- it falls through to
    the generic _UNDASHED check (a no-op passthrough for Sampson's plain-digit ids, e.g.
    "02005052601", "03044468001", live-sampled from the board 2026-11-19: no letter prefix, no
    dashes). This is the SAME passthrough behaviour already in effect when Sampson's 2026-10-29/
    11-12 live verification found real bill grids, so no new id-shape handling is added here.

GRID VS. BALANCE / VIEW ORDER / STOP RULE: identical to Pender's sibling -- the search grid
    carries no dollar amount, only the balance from each year's own ViewBill page; bills are
    viewed NEWEST YEAR FIRST (the grid itself lists them oldest first) up to
    VIEWS_PER_PARCEL_CAP, stopping once a bill's own prior_unpaid flag is false.

GATE, same discipline as every Munis sibling. raw['two_year_delinquent'] is written for every row
    a search actually answers (status "ok", even an all-paid answer). raw['multi_year_delinquent_tax']
    only when >=MIN_YEARS (2) MATURED/late years still carry a due amount today (tax_calendar's NC
    Jan-6-of-next-year rule).

SCALE / BUDGET. One live search (+ up to VIEWS_PER_PARCEL_CAP bill views) per not-yet-checked,
    non-empty-parcel_id Sampson row, capped (SAMPSON_MYDT_MAX, default 40 -- deliberately smaller
    than Pender/Nash's 200: this portal has never been run by this project at ANY volume, so a
    first pass is a small, real pilot, not the full 349-row eligible set) and wall-clock-budgeted
    (SAMPSON_MYDT_BUDGET_S, default 900s), CONCURRENCY fixed at 1 (see above). Idempotent via
    raw['_sampson_mydt_checked'] on a row whose search failed to produce a usable grid. Gate off
    entirely with FORECLOSURE_SAMPSON_MYDT=0. 1,016 total Sampson NC board rows measured
    2026-11-19 (board_stream, read-only); only 349 (34.4%) carry any parcel_id at all -- this
    module's own _eligible() ceiling is 349, not 1,016, discovered naturally by each run rather
    than pre-counted here (a wrong-shaped id simply sentinels "parcel_not_found" once searched,
    same convention tax_lien_munis.py's own verify() already uses).

PRIVACY. No owner name or mailing address is read or written here -- only the board's own
parcel_id (already public) and tax-year amounts land in raw['multi_year_delinquent_tax'] /
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
from .verification.verifiers import tax_lien_munis as munis

log = structlog.get_logger()

MYDT_KEY = "multi_year_delinquent_tax"
TYD_KEY = "two_year_delinquent"
CHECKED_KEY = "_sampson_mydt_checked"
COUNTY = "Sampson"
SOURCE_SLUG = "verification.verifiers.tax_lien_munis"

ENABLED = os.environ.get("FORECLOSURE_SAMPSON_MYDT") != "0"
#: Deliberately smaller than Pender/Nash's 200 -- see module docstring's SCALE/BUDGET note.
MAX_ROWS = int(os.environ.get("SAMPSON_MYDT_MAX", "40"))
BUDGET_S = float(os.environ.get("SAMPSON_MYDT_BUDGET_S", "900"))
#: MUST stay 1 -- see module docstring's CONCURRENCY note. tax_lien_munis's search()/view() cache
#: one shared session PER PORTAL, not per parcel; >1 races on it.
CONCURRENCY = int(os.environ.get("SAMPSON_MYDT_CONCURRENCY", "1"))
MIN_YEARS = int(os.environ.get("SAMPSON_MYDT_MIN_YEARS", "2"))
VIEWS_PER_PARCEL_CAP = 12

PORTAL = munis.PORTALS["Sampson"]


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
# pure: one parcel's bill-view answers -> matured/unpaid years
# ---------------------------------------------------------------------------

def _years_matured_and_balances(bills: list[dict], today: date) -> tuple[list[int], list[int], dict[int, float]]:
    """(years with a due amount today, the MATURED/late subset, {year: due}) from one parcel's
    own ViewBill answers -- `due` already nets payments/credits/interest (tax_lien_munis.py's
    own parse_bill() convention)."""
    per_year: dict[int, float] = {}
    for b in bills or ():
        due = b.get("due") or 0.0
        year = b.get("year")
        if due <= 0 or year is None:
            continue
        prev = per_year.get(year)
        per_year[year] = due if prev is None else max(prev, due)
    years = sorted(per_year)
    matured = tax_calendar.completed_delinquent_years(years, "NC", COUNTY, today)
    return years, matured, per_year


def build_two_year_block(bills: list[dict], *, today: Optional[date] = None) -> dict:
    """Pure: the raw['two_year_delinquent'] wrapper, written unconditionally once a search
    actually answers -- even a zero-matured-year answer states `is_two_year_plus` truthfully,
    the same "years is a count" discipline every sibling two_year_delinquent producer uses."""
    today = today or date.today()
    _, matured, _ = _years_matured_and_balances(bills, today)
    return {
        "is_two_year_plus": len(matured) >= 2,
        "years": len(matured),
        "oldest_year": min(matured) if matured else None,
        "source": SOURCE_SLUG,
    }


def build_multiyear_block(parid: str, bills: list[dict], *,
                          today: Optional[date] = None) -> Optional[dict]:
    """Pure: the raw['multi_year_delinquent_tax'] block, or None when the parcel doesn't clear
    the multi-year gate (fewer than MIN_YEARS matured/late years with a due amount today)."""
    today = today or date.today()
    years, matured, per_year = _years_matured_and_balances(bills, today)
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
        "layers": ["sampson_munis_bill_search"],
        "parcel_key": _normalize_parcel(parid),
        "source_url": PORTAL.base + munis.FORM.split("?")[0],
    }


# ---------------------------------------------------------------------------
# live fetch -- reuses tax_lien_munis's search()/view() directly (Sampson is already a
# registered Portal, unlike Nash's differently-pathed tenant)
# ---------------------------------------------------------------------------

async def _fetch(client: Any, board_parcel: str) -> tuple[Optional[list[dict]], str]:
    """(bills, status) for one Sampson board parcel_id: `bills` is the list of parse_bill()
    answers, one per real-estate grid year actually viewed (up to VIEWS_PER_PARCEL_CAP), or
    None with a short machine reason."""
    parid = munis.search_id(board_parcel, COUNTY)
    try:
        rows = await munis.search(client, PORTAL, parid)
    except munis.PortalDown as exc:
        return None, f"portal_unhealthy:{str(exc)[:80]}"
    except Exception as exc:  # noqa: BLE001 - every outcome is an answer
        return None, f"fetch_failed:{type(exc).__name__}"
    rows = [b for b in rows if "REAL ESTATE" in b["type"]]
    if not rows:
        return None, "parcel_not_found"
    # NEWEST year first -- see module docstring; the grid itself lists them oldest first.
    rows = sorted(rows, key=lambda b: -b["year"])
    bills: list[dict] = []
    for b in rows[:VIEWS_PER_PARCEL_CAP]:
        try:
            page = await munis.view(client, PORTAL, parid, b)
        except munis.PortalDown as exc:
            return (bills or None), f"portal_unhealthy:{str(exc)[:80]}"
        except Exception:  # noqa: BLE001 - keep whatever years already viewed
            continue
        bills.append(page)
        if not page.get("prior_unpaid"):
            break   # no older unpaid bill on file: the rest are paid, same stop rule _decide() uses
    if not bills:
        return None, "bill_pages_unreadable"
    return bills, "ok"


async def enrich_with_sampson_multiyear_tax(listings: Iterable[Listing],
                                            *, client: Optional[Any] = None) -> dict[str, Any]:
    """Walk not-yet-checked Sampson NC board rows and stamp raw['two_year_delinquent'] (always,
    on a real search answer) and raw['multi_year_delinquent_tax'] (when the parcel's own live
    Munis bill history shows real repeat delinquency). `client` is exposed for tests; the real
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
    cli = client or Fetcher(min_interval_s=0.5)
    start = time.monotonic()
    sem = asyncio.Semaphore(CONCURRENCY)

    async def one(li: Listing) -> None:
        if (time.monotonic() - start) > BUDGET_S:
            stats["skipped_budget"] += 1
            return
        board_parcel = str(li.parcel_id or "").strip()
        async with sem:
            bills, status = await _fetch(cli, board_parcel)
        stats["attempted"] += 1
        if not isinstance(li.raw, dict):
            li.raw = {}
        if status != "ok":
            stats["fetch_errors"] += 1
            li.raw[CHECKED_KEY] = status
            return
        li.raw[TYD_KEY] = build_two_year_block(bills, today=today)
        stats["two_year_written"] += 1
        block = build_multiyear_block(board_parcel, bills, today=today)
        if block is None:
            stats["multiyear_insufficient_years"] += 1
        else:
            block["checked_at"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
            li.raw[MYDT_KEY] = block
            stats["multiyear_qualified"] += 1

    await asyncio.gather(*(one(li) for li in capped))
    log.info("sampson_mydt.done", **stats)
    return stats
