"""Pender County NC multi-year delinquent-tax HISTORY, read live from the county's own Tyler
Munis "Citizen Self Service" tax-bill search -- the SAME Munis vendor
verification/verifiers/tax_lien_munis.py already drives for New Hanover/Hoke/Lee, and Pender
itself was added to that module's own PORTALS dict on 2026-10-29 (tax_lien_munis.py's own
PORTALS note has the full live-verification story: a prior session's "needs stealth-browser,
AJAX-rendered" diagnosis was wrong -- a bare curl with no User-Agent hits the portal's
browser-upgrade gate, Location: /css/common/Upgrade.aspx, before ever reaching the real form;
a realistic UA, which this project's Fetcher.form_session() already sends, gets a clean 200
with every control name search_form()/search_id() already expect).

WHY THIS EXISTS. The tax_lien_munis verifier alone is a CONFIRM/REFUTE check on a claim a row
already carries from some OTHER producer -- live-verified 2026-10-29 via
scripts/verification_sweep.py --signal tax_lien --county Pender: only 3 of Pender's 1,543
board rows carry any existing tax_owed/tax_aging claim at all, so the verifier has almost
nothing to act on. To populate raw['multi_year_delinquent_tax']/raw['two_year_delinquent']
for Pender at the scale gap_matrix actually wants (multi_year_delinquent_tax/
two_year_delinquent/tax_aging_surfaced all "sourced-not-built"), this module independently
WALKS the live bill history for every row with a resolvable parcel_id, the same shape
enrichment_nash_multiyear_tax.py already established for the same vendor's Nash tenant.

REUSES tax_lien_munis.py's search()/view() DIRECTLY, not a standalone re-implementation like
Nash's sibling needed: Pender is already a registered Portal in that module's own PORTALS
dict (unlike Nash's older, differently-pathed tenant, which stayed standalone rather than
touch the shared module), so this module gets that function's existing session cache,
per-portal circuit breaker (PortalDown after PORTAL_MAX_FAILURES) and parcel/browse-page
reuse for free -- less code, same battle-tested session plumbing the verifier itself uses.

CONCURRENCY MUST STAY 1, live-verified the hard way (2026-10-29): tax_lien_munis._session()
caches ONE shared ASP.NET WebForms session PER PORTAL (not per parcel) -- exactly matching
verification_sweep.py's own documented usage, "one row at a time" through a verifier. Running
this module at CONCURRENCY=2 against 5 real rows made two parcels' searches race on that one
shared session/__VIEWSTATE and the portal answered "search HTTP 500" for both, which tripped
PORTAL_MAX_FAILURES's circuit breaker and poisoned the rest of the run (fetch_errors=4/5).
Dropping to CONCURRENCY=1 (this module's own default) fixed it; Nash's sibling avoids the
same trap by opening an INDEPENDENT session per call instead of reusing tax_lien_munis's
cached one -- this module instead just never asks for more than one in flight.

PARCEL ID SHAPE: Pender's board parcel_id ("4202-82-6152-0000") is dashed the opposite way
New Hanover's is; tax_lien_munis.search_id(parcel, "Pender") strips the dashes to the portal's
own 14-digit PARID ("42028261520000") -- see that function's own docstring.

GRID VS. BALANCE: tax_lien_munis.search()'s grid carries no dollar amount, only
{address,owner,parcel,year,type,target} per bill row -- the balance comes only from each
year's own ViewBill page (view()'s "due"). This module views grid years NEWEST FIRST (the
grid itself lists them OLDEST first, live-confirmed against a real 19-year-deep parcel,
2008-2026 -- the first version of this module took rows[:CAP] unsorted and silently only
ever saw the oldest 12 years, never the current one) up to VIEWS_PER_PARCEL_CAP (matching
Nash's own 12), STOPPING once a bill's own prior_unpaid flag is false -- no older unpaid
bill on file means the rest are paid, the same early-exit tax_lien_munis.verify()'s own
_decide() already uses. A parcel with only one bill record on file skips the grid entirely
(tax_lien_munis.py's own _single_bill_row, added 2026-10-29 for this reason) and this
module's view() call on it is a cache hit, no extra request.

GATE, same discipline as enrichment_nash_multiyear_tax.py / enrichment_iredell_multiyear_tax.py.
raw['two_year_delinquent'] is written for every row a search actually answers (status "ok",
even an all-paid answer). raw['multi_year_delinquent_tax'] only when >=MIN_YEARS (2)
MATURED/late years still carry a due amount today (tax_calendar's NC Jan-6-of-next-year rule).

SCALE / BUDGET. One live search (+ up to VIEWS_PER_PARCEL_CAP bill views) per not-yet-checked,
non-empty-parcel_id Pender row, capped (PENDER_MYDT_MAX, default 200) and wall-clock-budgeted
(PENDER_MYDT_BUDGET_S, default 900s), CONCURRENCY default 2 (Nash's own choice for this same
vendor, where each row can cost well over a dozen requests, not 1). Idempotent via
raw['_pender_mydt_checked'] on a row whose search failed to produce a usable grid. Gate off
entirely with FORECLOSURE_PENDER_MYDT=0. 1,543 total Pender NC board rows measured 2026-10-29
(board_stream, read-only); not every one carries a resolvable parcel_id, so this module's own
_eligible() ceiling is lower than that, discovered naturally by each run rather than
pre-counted here (a wrong-shaped id simply sentinels "parcel_not_found" once searched, same
convention tax_lien_munis.py's own verify() already uses).

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
CHECKED_KEY = "_pender_mydt_checked"
COUNTY = "Pender"
SOURCE_SLUG = "verification.verifiers.tax_lien_munis"

ENABLED = os.environ.get("FORECLOSURE_PENDER_MYDT") != "0"
MAX_ROWS = int(os.environ.get("PENDER_MYDT_MAX", "200"))
BUDGET_S = float(os.environ.get("PENDER_MYDT_BUDGET_S", "900"))
#: MUST stay 1 by default -- see the module docstring's CONCURRENCY note. tax_lien_munis's
#: search()/view() cache one shared session PER PORTAL, not per parcel; >1 races on it.
CONCURRENCY = int(os.environ.get("PENDER_MYDT_CONCURRENCY", "1"))
MIN_YEARS = int(os.environ.get("PENDER_MYDT_MIN_YEARS", "2"))
VIEWS_PER_PARCEL_CAP = 12

PORTAL = munis.PORTALS["Pender"]


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
        "layers": ["pender_munis_bill_search"],
        "parcel_key": _normalize_parcel(parid),
        "source_url": PORTAL.base + munis.FORM.split("?")[0],
    }


# ---------------------------------------------------------------------------
# live fetch -- reuses tax_lien_munis's search()/view() directly (Pender is already a
# registered Portal, unlike Nash's differently-pathed tenant)
# ---------------------------------------------------------------------------

async def _fetch(client: Any, board_parcel: str) -> tuple[Optional[list[dict]], str]:
    """(bills, status) for one Pender board parcel_id: `bills` is the list of parse_bill()
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
    # NEWEST year first: live-verified 2026-10-29 against a real 19-year-deep Pender parcel
    # (2008-2026) that the grid itself lists OLDEST first -- the naive rows[:CAP] this module
    # shipped with first took the OLDEST 12 years and silently never saw the current,
    # most-delinquency-relevant ones at all. Sorted here, matching tax_lien_munis.verify()'s
    # own _decide() walk order.
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


async def enrich_with_pender_multiyear_tax(listings: Iterable[Listing],
                                           *, client: Optional[Any] = None) -> dict[str, Any]:
    """Walk not-yet-checked Pender NC board rows and stamp raw['two_year_delinquent'] (always,
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
    log.info("pender_mydt.done", **stats)
    return stats
