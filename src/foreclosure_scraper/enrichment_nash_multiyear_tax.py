"""Nash County NC multi-year delinquent-tax HISTORY, read live from the county's own Tyler Munis
"Citizen Self Service" tax-bill search -- the SAME Munis vendor
verification/verifiers/tax_lien_munis.py already drives for New Hanover/Hoke/Lee (its own
PORTALS dict), a NEW TENANT, not a new integration: this module reuses that file's parsing
functions (hidden_fields/search_form/view_form/parse_grid/parse_bill/_money) verbatim.

WHY THIS EXISTS (docs/gap_matrix/gap_list_2026-10-20.csv). NC Nash's "two_year_delinquent",
    "tax_aging_surfaced" and "multi_year_delinquent_tax" (2,090 applicable rows each) all show
    sourced-not-built, source "tax/property card: taxdata.nashcountync.gov", built=no.

CHECKED FIRST, PER TASK BRIEF: grepped the codebase for "nashcounty"/"taxdata.nashcounty" --
    nothing. Then checked whether taxdata.nashcountync.gov shares a vendor with an
    already-wired county (ITS.NET, the Iredell/Chowan/Cabarrus platform) or a different one.
    LIVE-VERIFIED 2026-10-21, NOT ASSUMED: taxdata.nashcountync.gov is NEITHER. Its homepage
    footer reads "Powered by iasWorld Public Access" (Tyler Technologies / Akanda Solutions) --
    the SAME product tax_lien_rowan.py already drives for Rowan County (identical
    commonsearch.aspx search form, identical hidden-field names). A live canary search
    (PARID "305400", a real board parcel) against taxdata.nashcountync.gov confirmed the
    platform match -- but also found the real gap: this iasWorld TENANT exposes only a property/
    CAMA profile (its own tab list, read live from the Datalet nav: profileall, sales, land,
    residential, commercial, oby, valuesall, comapt, comuse, sketch) and carries NO
    "tax_bills_int" tab or any other billing/balance data at all -- unlike Rowan's tenant, which
    does. Nash's own site separates the two systems explicitly: the "Tax Search" site
    (taxdata.nashcountync.gov, CAMA only) and a separate "Tax Bill Search" / "Tax Website" link
    to nashcountync.munisselfservice.com -- Tyler's OTHER product, Munis Citizen Self Service,
    which is where the real per-year balance lives. So the gap list's one-line source guess
    (taxdata.nashcountync.gov) named the right COUNTY but the wrong of Nash's two Tyler systems;
    the money data is on Munis, already a known, multi-tenant vendor in this codebase
    (tax_lien_munis.py's PORTALS: New Hanover, Hoke, Lee).

NASH'S MUNIS TENANT IS AN OLDER "CSS" SKIN, confirmed live 2026-10-21: its real estate search
    lives at nashcountync.munisselfservice.com/css/citizens/RealEstate/Default.aspx?mode=new
    (New Hanover/Hoke/Lee all use .../citizens/RealEstate/... with NO "/css" segment) -- so this
    tenant is NOT a one-line PORTALS dict addition to tax_lien_munis.py (that module's FORM/
    BROWSE/PAYMENTS path constants are shared across all of its portals). Rather than add a
    path-prefix field to that already-shipped, multi-county verifier and risk the three counties
    it already serves, this module stays standalone and reuses tax_lien_munis's PURE parsing
    functions verbatim (hidden_fields, search_form, view_form, parse_grid, parse_bill, _money,
    and the exact FORM/BROWSE/PAYMENTS relative paths and control-ID constants, which a live
    diff of the two tenants' raw HTML confirmed are byte-identical control names/IDs -- only the
    base URL differs) with its OWN tiny session/search/view wrapper below.

    Nash's Munis tenant ALSO bounces a fresh (cookieless) GET of the search form to
    /css/common/Upgrade.aspx ("enable cookies/JS") with Set-Cookie headers that make a SECOND GET
    of the identical URL return the real form -- confirmed live (a fresh cookie jar's first GET
    got the Upgrade page, a second GET with those cookies got the real
    ParcelIDTextBox/__VIEWSTATE form). `_open_form` below does that warm-up GET once, defensively
    (a session that is already warm just succeeds on the first try, also observed live).

    PARCEL ID SHAPE, confirmed live against 3 real board parcels: Munis's ParcelIDTextBox wants
    the SAME short PARID iasWorld uses ("305400", 6 digits), NOT the board's 12-digit NC PIN
    ("385208991720" for that same parcel -- zero results) and not the "NC#####" dam-safety ID a
    handful of Nash rows carry in parcel_id (a pre-existing, unrelated shape, same noise pattern
    documented in enrichment_iredell_multiyear_tax.py). Streamed Nash's own 2,090 NC board rows
    directly (board_stream, 2026-10-21) before writing this module: 952 carry ANY parcel_id
    (45.6%), split 612 six-digit PARID-shaped / 282 twelve-digit PIN-shaped / 58 "NC#####"
    dam-safety IDs -- so this module's realistic ceiling is ~612 rows, not 2,090. Like every
    sibling restater (Iredell/Cabarrus/Catawba), `_eligible` does NOT pre-filter on shape: every
    non-empty parcel_id is a candidate, and a wrong-shaped one naturally sentinels as
    "parcel_not_found" once searched (Munis matches by exact PARID, not prefix).

    LIVE CANARY (2026-10-21, one real parcel, PARID 305400 / "ROCKY MOUNT GOLF CLUB WEH LP",
    201 Belmont Club Way): search -> a 12-year bill grid (2015-2026) -> each year's own ViewBill
    page -> real dollar balances. 2026 (current, not yet late): $6,340.45 due. 2015 (oldest):
    $17,900.87 billed, fully paid, but flagged "newer_unpaid" (a later year is still owed) --
    this single real parcel is itself a genuine multi-year delinquency, not a constructed
    fixture.

GRID VS. BALANCE: parse_grid() (the search answer) carries no dollar amount, only
    {address,owner,parcel,year,type,target} per bill row -- the balance comes only from each
    year's own ViewBill page (parse_bill()'s "due"), exactly like tax_lien_munis.verify()'s own
    walk. This module views every grid year up to VIEWS_PER_PARCEL_CAP (12, matching the full
    depth seen live -- Nash's grid holds no more than the county's own online history) through
    the SAME browse-page viewstate for every view (tax_lien_munis.view()'s own re-use pattern,
    confirmed live: three sequential ViewBill posts against one search's browse page all
    answered correctly).

GATE, same discipline as enrichment_iredell_multiyear_tax.py. raw['two_year_delinquent'] is
    written for every row a search actually answers (status "ok", even an all-paid answer).
    raw['multi_year_delinquent_tax'] only when >=MIN_YEARS (2) MATURED/late years still carry a
    due amount today (tax_calendar's NC Jan-6-of-next-year rule).

SCALE / BUDGET. One live search (+ up to 12 bill views) per not-yet-checked, non-empty-parcel_id
    Nash row, capped (NASH_MYDT_MAX, default 200) and wall-clock-budgeted (NASH_MYDT_BUDGET_S,
    default 900s) -- lower concurrency (NASH_MYDT_CONCURRENCY, default 2) than the Iredell/
    Cabarrus siblings because each row here costs up to 13 requests (1 search + <=12 views)
    against an older, single-box legacy host, not 1. Idempotent via raw['_nash_mydt_checked'] on
    a row whose search failed to produce a usable grid. Gate off entirely with
    FORECLOSURE_NASH_MYDT=0.

PRIVACY. No owner name or mailing address is read or written here -- only the board's own PARID
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
from .verification.verifiers import tax_lien_munis as munis

log = structlog.get_logger()

MYDT_KEY = "multi_year_delinquent_tax"
TYD_KEY = "two_year_delinquent"
CHECKED_KEY = "_nash_mydt_checked"
COUNTY = "Nash"
SOURCE_SLUG = "verification.verifiers.tax_lien_munis"

ENABLED = os.environ.get("FORECLOSURE_NASH_MYDT") != "0"
MAX_ROWS = int(os.environ.get("NASH_MYDT_MAX", "200"))
BUDGET_S = float(os.environ.get("NASH_MYDT_BUDGET_S", "900"))
CONCURRENCY = int(os.environ.get("NASH_MYDT_CONCURRENCY", "2"))
MIN_YEARS = int(os.environ.get("NASH_MYDT_MIN_YEARS", "2"))
VIEWS_PER_PARCEL_CAP = 12

#: Nash's Munis tenant is the older "css" skin (confirmed live 2026-10-21); its FORM/BROWSE/
#: PAYMENTS *relative* paths and control-ID constants are byte-identical to tax_lien_munis.py's
#: existing portals (New Hanover/Hoke/Lee) -- only this base differs.
NASH_BASE = "https://nashcountync.munisselfservice.com/css"
FORM_URL = NASH_BASE + munis.FORM
TIMEOUT_S = 45.0


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
        "layers": ["nash_munis_bill_search"],
        "parcel_key": _normalize_parcel(parid),
        "source_url": FORM_URL,
    }


# ---------------------------------------------------------------------------
# live fetch -- reuses tax_lien_munis's parsing chain verbatim, own session plumbing (the
# older "css"-skin tenant needs a cookie warm-up GET tax_lien_munis.py's other 3 portals don't)
# ---------------------------------------------------------------------------

async def _open_form(s: Any) -> str:
    """The search form's HTML, warming up the "enable cookies" bounce once if needed (confirmed
    live 2026-10-21: a fresh cookie jar's first GET lands on /css/common/Upgrade.aspx; a second
    GET of the identical URL, cookies now set, returns the real form). A session that is already
    warm just succeeds on the first try."""
    r = await s.get(FORM_URL, timeout=TIMEOUT_S)
    if r.status == 200 and munis.PARCEL_FIELD.replace("$", "_") in r.text.replace("$", "_"):
        return r.text
    r = await s.get(FORM_URL, timeout=TIMEOUT_S)
    if r.status != 200 or munis.PARCEL_FIELD.replace("$", "_") not in r.text.replace("$", "_"):
        raise RuntimeError(f"form page unreadable after warm-up (HTTP {r.status})")
    return r.text


async def _fetch(client: Any, parid: str) -> tuple[Optional[list[dict]], str]:
    """(bills, status) for one Nash PARID: `bills` is the list of parse_bill() answers, one per
    grid year actually viewed (up to VIEWS_PER_PARCEL_CAP), or None with a short machine reason."""
    try:
        async with client.form_session() as s:
            form_html = await _open_form(s)
            r = await s.post_form(FORM_URL, munis.search_form(form_html, parid),
                                  headers={"Referer": FORM_URL}, timeout=TIMEOUT_S)
            if r.status != 200:
                return None, f"search_http_{r.status}"
            grid = munis.parse_grid(r.text)
            if grid is None:
                return None, "no_bills_grid"
            want = tc.alnum(parid)
            rows = [b for b in grid if tc.alnum(b.get("parcel")) == want]
            if not rows:
                return None, "parcel_not_found"
            browse_url, browse_html = (r.url or NASH_BASE + munis.BROWSE), r.text
            bills: list[dict] = []
            for b in rows[:VIEWS_PER_PARCEL_CAP]:
                vr = await s.post_form(browse_url, munis.view_form(browse_html, b["target"]),
                                       headers={"Referer": FORM_URL}, timeout=TIMEOUT_S)
                if vr.status != 200:
                    continue
                parsed = munis.parse_bill(vr.text)
                if parsed:
                    bills.append(parsed)
            if not bills:
                return None, "bill_pages_unreadable"
            return bills, "ok"
    except Exception as exc:  # noqa: BLE001 - every outcome is an answer
        return None, f"fetch_failed:{type(exc).__name__}"


async def enrich_with_nash_multiyear_tax(listings: Iterable[Listing],
                                         *, client: Optional[Any] = None) -> dict[str, Any]:
    """Walk not-yet-checked Nash NC board rows and stamp raw['two_year_delinquent'] (always, on a
    real search answer) and raw['multi_year_delinquent_tax'] (when the parcel's own live Munis
    bill history shows real repeat delinquency). `client` is exposed for tests; the real pipeline
    always lets it default (a fresh Fetcher, this call's own rate limit)."""
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
        parid = str(li.parcel_id or "").strip()
        async with sem:
            bills, status = await _fetch(cli, parid)
        stats["attempted"] += 1
        if not isinstance(li.raw, dict):
            li.raw = {}
        if status != "ok":
            stats["fetch_errors"] += 1
            li.raw[CHECKED_KEY] = status
            return
        li.raw[TYD_KEY] = build_two_year_block(bills, today=today)
        stats["two_year_written"] += 1
        block = build_multiyear_block(parid, bills, today=today)
        if block is None:
            stats["multiyear_insufficient_years"] += 1
        else:
            block["checked_at"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
            li.raw[MYDT_KEY] = block
            stats["multiyear_qualified"] += 1

    await asyncio.gather(*(one(li) for li in capped))
    log.info("nash_mydt.done", **stats)
    return stats
