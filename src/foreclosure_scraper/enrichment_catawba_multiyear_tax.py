"""Catawba County NC multi-year delinquent-tax HISTORY, read live per parcel from the same
ITSPublic tax-bill portal verification/verifiers/tax_lien_itspublic.py already reads to confirm
claims against.

WHY THIS EXISTS (docs/gap_matrix/gap_list_2026-10-20.csv, read before writing a line here).
    NC Catawba "multi_year_delinquent_tax": applicable=8,291, hits=0, built="no",
    gap_class="sourced-not-built", source="tax/property card: taxbill.catawbacountync.gov".

    tax_lien_itspublic.py has had a full Catawba `Portal` entry since 2026-10-09 ("audit
    tax_checkers_2") -- base https://taxbill.catawbacountync.gov/ITSPublicCT, search field
    AlternateParcelIdentifier (the board's own PIN, no bridge needed), full_model=True,
    real_without_units=True (pre-2025 bills print no acreage), pin_pad="0000" -- but like every
    other county on this family of portals (Wake's services.wake.gov, Randolph's
    txpwa.randolphcountync.gov, Gaston's DevNetWedge), it only reads this source to answer a
    point-in-time verdict on a row that ALREADY carries a property-tax claim
    (`applies()` gates on `_tax_common.claims_property_tax`). Catawba's board rows mostly come
    from `counties_nc.nc_county_pdf_delinquent_tax` (CATAWBA_PDF_ROLL in that same verifier) --
    the county's annual tax-foreclosure-advertisement PDF, a SINGLE snapshot year, not a bill
    history -- so `two_year_delinquent`/`tax_aging_surfaced` already run against Catawba
    (built-but-low-yield in the same gap CSV) but `multi_year_delinquent_tax` specifically never
    got an upstream reader. This module is that missing upstream half, the identical shape as
    enrichment_wake_multiyear_tax.py / enrichment_randolph_multiyear_tax.py: it reads the
    parcel's own full bill history directly (every year the portal still remembers, one search)
    and, when it shows real repeat delinquency, writes the claim
    (raw['multi_year_delinquent_tax']) a later verification sweep can then confirm. There is no
    double build: tax_lien_itspublic.py keeps doing its own job, completely unchanged, and this
    module reuses its exact live-proven session/search/parse chain (`search()`, `bills_of()`,
    `PORTALS["Catawba"]`) verbatim rather than re-implementing it.

    SIMPLER THAN WAKE: Catawba's AlternateParcelIdentifier field takes the board's own PIN
    directly (no NC OneMap PIN<->REID bridge, no services.nconemap.gov dependency) -- so this
    module has none of the bridge-timeout exposure enrichment_wake_multiyear_tax.py's own
    docstring and project_wake_randolph_live_fetch_rate_limited_2026-10-19.md document for Wake.

LIVE-VERIFIED 2026-10-20 (this session, directly against the real portal, not assumed). Root
    https://taxbill.catawbacountync.gov/ answers a bare default-IIS page -- the real app lives
    at the sub-path the verifier already names, /ITSPublicCT/TaxBillSearch, reused here
    unchanged. 7 real board PINs (read-only from the live board, no bulk search exists on this
    vendor -- same shape as every other ITSPublic/Wake/Gaston county), each a single
    AlternateParcelIdentifier search, each answered in well under a second, no login, no
    CAPTCHA, no terms click-through:
      PIN 374117104352 (the exact example tax_lien_itspublic.py's own docstring already uses)
          -- 20 real bills back to 2016, every year paid ($0.00 balance) except the current,
          not-yet-due 2026 bill. Correctly yields nothing (fewer than MIN_YEARS matured unpaid
          years).
      PIN 375005098228 -- 2024 ($291.74) and 2025 ($266.90) both unpaid and matured, plus the
          current 2026 bill ($242.67, not yet due). A genuine, qualifying multi-year
          delinquency: 2 matured years, exactly the minimum qualifying shape.
      5 more PINs (367703049818, 372108895780, 374118205631, 460715647965, 374205186911,
          372011750111, 362703447204, 370106395316) -- all real 20-bill (or shorter, newer-
          parcel) histories, all paid current except this year's own not-yet-due bill: the same
          "most sampled parcels are paid current" shape every prior county's recon has found.

SHAPE. Reuses tax_lien_itspublic.PORTALS["Catawba"] / .search() / .bills_of() verbatim (the same
    live-proven session + GetSearchTablePartial + GetSearchTableData chain, over the same
    verification.fetch.Fetcher the verifier itself runs on) so raw['multi_year_delinquent_tax']
    here is byte-shape-compatible with the Buncombe/Oconee/Pickens/Gaston/Wake/Randolph blocks --
    tax_binding.BLOCK_PARCEL_FIELDS["multi_year_delinquent_tax"] = ("parcel_key",),
    enrichment_tax_owed._SOURCES's exact-key read of "total_due", and web_artifact.RAW_KEEP's
    "*" wildcard all already expect this shape; no downstream wiring needed. A bill's own `ids`
    list already carries both the portal's padded form and (via Portal.pin_pad) the board's own
    unpadded PIN (parse_description), so build_block's own id-match is a belt-and-suspenders
    check, not a new bridge.

SCALE / BUDGET. One live search per not-yet-checked Catawba row -- 8,291 of them. Capped per run
    (CATAWBA_MYDT_MAX, default 300) and wall-clock-budgeted (CATAWBA_MYDT_BUDGET_S, default
    600s), the identical shape enrichment_wake_multiyear_tax.py / enrichment_randolph_multiyear_
    tax.py already use. Idempotent via raw['_catawba_mydt_checked'] on a row that was fetched
    but did NOT clear the multi-year gate or could not be resolved at all, same reason those
    modules document (without the sentinel, every run re-walks the same first-N unchecked rows
    forever). A qualifying hit needs no sentinel: raw['multi_year_delinquent_tax'] itself is the
    "done" mark. Repeated runs converge over the backlog; CATAWBA_MYDT_MAX can be raised for an
    explicit one-off backfill. Gate off entirely with FORECLOSURE_CATAWBA_MYDT=0.

PRIVACY. No owner name or mailing address is ever read or written here -- only the board's own
    PIN (already public) and tax-year amounts land in raw['multi_year_delinquent_tax'].
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
from .verification.verifiers import tax_lien_itspublic as its

log = structlog.get_logger()

RAW_KEY = "multi_year_delinquent_tax"
CHECKED_KEY = "_catawba_mydt_checked"
COUNTY = "Catawba"

ENABLED = os.environ.get("FORECLOSURE_CATAWBA_MYDT") != "0"
MAX_ROWS = int(os.environ.get("CATAWBA_MYDT_MAX", "300"))
BUDGET_S = float(os.environ.get("CATAWBA_MYDT_BUDGET_S", "600"))
CONCURRENCY = int(os.environ.get("CATAWBA_MYDT_CONCURRENCY", "4"))
MIN_YEARS = int(os.environ.get("CATAWBA_MYDT_MIN_YEARS", "2"))

_PORTAL = its.PORTALS[COUNTY]


def _county_key(li: Listing) -> str:
    return (li.county or "").replace(" County", "").strip().lower()


def _already_done(li: Listing) -> bool:
    if not isinstance(li.raw, dict):
        return False
    return isinstance(li.raw.get(RAW_KEY), dict) or bool(li.raw.get(CHECKED_KEY))


def _eligible(li: Listing) -> bool:
    return (
        (li.state or "").strip().upper() == "NC"
        and _county_key(li) == COUNTY.lower()
        and bool(tc.alnum(str(li.parcel_id or "")))
        and not _already_done(li)
    )


def build_block(pin: str, bills: list[dict], *, today: Optional[date] = None) -> Optional[dict]:
    """Pure: the raw['multi_year_delinquent_tax'] block from one parcel's full ITSPublic bill
    history (tax_lien_itspublic.search()'s own `bills` list -- every real-property bill the
    portal still remembers for this PIN), or None when the parcel doesn't clear the multi-year
    gate (fewer than MIN_YEARS unpaid years, or no MATURED unpaid year -- a parcel whose only
    unpaid bill is this year's current, not-yet-due one is not repeat delinquency). Only bills
    whose own `ids` actually carry this PIN count (search() answers for the submitted
    AlternateParcelIdentifier already, so this is a belt-and-suspenders check, same discipline
    as tax_lien_itspublic.bills_of() and enrichment_randolph_multiyear_tax's own parcel guard)."""
    today = today or date.today()
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
    if len(years) < MIN_YEARS:
        return None
    matured = tax_calendar.completed_delinquent_years(years, "NC", COUNTY, today)
    if not matured:
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
        "layers": ["catawba_itspublic_bill_search"],
        "parcel_key": _normalize_parcel(pin),
        "source_url": f"{_PORTAL.base}/TaxBillSearch",
    }


async def _fetch(client: Any, pin: str) -> tuple[Optional[list[dict]], str]:
    """(bills, status) for one Catawba PIN via tax_lien_itspublic's own live-proven
    session/search/parse chain, reused verbatim. status is "ok" with bills set, else a short
    machine reason."""
    try:
        bills = await its.search(client, _PORTAL, _PORTAL.parcel_field, tc.alnum(pin))
    except Exception as exc:  # noqa: BLE001 - every outcome is an answer
        return None, f"fetch_failed:{type(exc).__name__}"
    if not bills:
        return None, "no_bills"
    return bills, "ok"


async def enrich_with_catawba_multiyear_tax(listings: Iterable[Listing],
                                            *, client: Optional[Any] = None) -> dict[str, Any]:
    """Walk not-yet-checked Catawba NC board rows and stamp raw['multi_year_delinquent_tax']
    from the parcel's own live ITSPublic bill history when it shows real repeat delinquency.
    `client` is exposed for tests; the real pipeline always lets it default (a fresh Fetcher,
    this call's own rate limit)."""
    stats = {"eligible": 0, "attempted": 0, "qualified": 0, "insufficient_history": 0,
             "no_bills": 0, "fetch_errors": 0, "skipped_cap": 0, "skipped_budget": 0}
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
            stats["no_bills" if status == "no_bills" else "fetch_errors"] += 1
            li.raw[CHECKED_KEY] = status
            return
        block = build_block(pin, bills, today=today)
        if block is None:
            stats["insufficient_history"] += 1
            li.raw[CHECKED_KEY] = "insufficient_history"
            return
        block["checked_at"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
        li.raw[RAW_KEY] = block
        stats["qualified"] += 1

    await asyncio.gather(*(one(li) for li in capped))
    log.info("catawba_mydt.done", **stats)
    return stats
