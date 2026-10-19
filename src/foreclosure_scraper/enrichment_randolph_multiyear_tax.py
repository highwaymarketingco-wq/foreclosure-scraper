"""Randolph County NC multi-year delinquent-tax HISTORY, read live per parcel from the same
PTS "Public Web Access" bill-search portal verification/verifiers/tax_lien_pwa.py already reads
to confirm claims against.

WHY THIS EXISTS (docs/gap_matrix/gap_list_2026-10-18.csv, read before writing a line here).
    NC Randolph "multi_year_delinquent_tax": applicable=6,043, hits=0, built=no,
    gap_class="sourced-not-built", source="tax/property card: txpwa.randolphcountync.gov".
    "two_year_delinquent" (same applicable count) and "atty_tax_verified_confirmed" (4,619
    applicable) show the identical gap_class and next_action.

    verification/verifiers/tax_lien_pwa.py (top-80 build, 2026-10-09) already reads this exact
    county's exact source -- posts `BillSearchResults.aspx` with taxYear="ALL" and the row's
    parcel number, which returns the parcel's FULL multi-year bill grid, newest first -- but it
    only reads that grid to answer the single point-in-time question "is a late-year bill due
    right now" (the tax_lien SIGNAL: confirmed/stale/unconfirmed). It only runs at all on a row
    that already claims a property-tax debt (`applies()` gates on `_tax_common.
    claims_property_tax`, true for Randolph's `nc_tax_lien_ad` rows). This module is the
    missing UPSTREAM half, exactly the shape of last night's Gaston precedent
    (project_tax_roll_reader_workflow_2026-10-18.md, enrichment_gaston_multiyear_tax.py): it
    reads the SAME parcel's SAME grid directly, keeps every year's own balance instead of
    collapsing it to one verdict, and writes the claim (raw['multi_year_delinquent_tax']) that
    the verifier (or any later verification sweep) can then check. There is no double build:
    tax_lien_pwa.py keeps doing its own job, completely unchanged, and the two modules share
    its exact live-proven HTTP call (`tax_lien_pwa._search` / `.build_form` / `.parse_grid`,
    reused verbatim below, not re-implemented).

    Once a row gains raw['multi_year_delinquent_tax'] here, enrichment_tax_owed.py's existing
    `_SOURCES["multi_year_delinquent_tax"]` mapping derives raw['tax_owed'] from it the same
    run, which widens tax_lien_pwa.applies()'s own `claims_property_tax` test (via
    `tax_owed_claim`) to more Randolph rows than carried a bare `nc_tax_lien_ad` block before --
    so this module also feeds, rather than duplicates, the separate atty_tax_verified_confirmed
    gap (hit = a tax_lien verdict "confirmed"; that verdict itself is tax_lien_pwa.py's own job,
    run by the verification sweep, not this module's).

LIVE-VERIFIED 2026-10-18, directly against the real portal (not assumed). The lookupCriterion
    dropdown on https://txpwa.randolphcountync.gov/publicwebaccess/BillSearchResults.aspx
    offers Bill/Business/Invoice/Old-Bill/Owner/Parcel/Street search; real parcels pulled from
    the county's own published 2025 tax-lien advertisement PDF
    (randolphcountync.gov/DocumentCenter/View/545, scrapers/counties_nc/nc_tax_lien_ads.py's own
    source) and re-queried with taxYear="ALL":
      parcel 7751357444 (TAYLOR, DORETHA GARNER COBLE HEIRS) -- unpaid 2023/2024/2025/2026,
          ($219.16/$203.59/$248.02/$168.05): 3 MATURED years (2023-2025) plus the current,
          not-yet-due 2026 bill -- clears the gate.
      parcel 7761140352 (TAYLOR, ELIZABETH HEIRS) -- unpaid 2020/2021/2022/2023/2024/2025/2026,
          7 straight years, 6 of them matured -- clears the gate with room to spare.
      parcel 7728633591 (TALBERT, ELANOR J HEIRS) -- unpaid 2024/2025/2026, 2 matured years --
          the minimum shape that still clears the gate.
    Most parcels sampled this same pass (random Owner Name hits, and two more names off the
    same advertisement PDF) are paid current except for this year's own not-yet-late bill, and
    correctly yield nothing -- the same "most sampled parcels are paid current" shape Gaston's
    own recon found.

SHAPE. Reuses tax_lien_pwa.PORTALS["Randolph"] / .build_form / .parse_grid / ._search verbatim
    (the same live-proven form-POST, VIEWSTATE and grid-parse chain, over the same verification.
    fetch.Fetcher the verifier itself runs on) so raw['multi_year_delinquent_tax'] here is
    byte-shape-compatible with the Buncombe/Oconee/Pickens scraper's own blocks and with
    Gaston's/PTS-Cloud's/ITSPublic's own enrichments -- the same
    tax_binding.BLOCK_PARCEL_FIELDS / enrichment_tax_owed._SOURCES / web_artifact.RAW_KEEP
    wiring already expects this shape; nothing downstream needs to change. One real difference
    from Gaston's DevNetWedge source: a single taxYear="ALL" search returns every year's bill in
    ONE request (no per-year page), so there is no "stop after two empty years" early-exit to
    write -- the whole history is already in hand after one fetch.

SCALE / BUDGET. One live form-POST per not-yet-checked Randolph row -- 6,043 of them. Capped
    per run (RANDOLPH_MYDT_MAX, default 300) and wall-clock-budgeted (RANDOLPH_MYDT_BUDGET_S,
    default 600s), the same shape enrichment_gaston_multiyear_tax.py and
    enrichment_lrcpwa_parcel.py already use for their own per-parcel network enrichment.
    Idempotent via raw['_randolph_mydt_checked'] (a short status string) on a row that was
    fetched but did not clear the gate or could not be resolved at all -- without that
    sentinel surviving to the next run's prior-board merge, every run would re-walk the same
    first-N unchecked rows forever. A qualifying hit needs no sentinel:
    raw['multi_year_delinquent_tax'] itself is the "done" mark. Repeated runs converge over the
    6,043-row backlog; RANDOLPH_MYDT_MAX can be raised for an explicit one-off backfill.
    Gate off entirely with FORECLOSURE_RANDOLPH_MYDT=0.

PRIVACY. No owner name or mailing address is ever written here -- the portal's grid carries an
    owner name and a situs per bill (tax_lien_pwa.py already reads both for its own verdict),
    neither of which this module's raw['multi_year_delinquent_tax'] block stores. Only tax-year
    amounts and the parcel's own id.
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
from .verification.verifiers import tax_lien_pwa as pwa

log = structlog.get_logger()

RAW_KEY = "multi_year_delinquent_tax"
CHECKED_KEY = "_randolph_mydt_checked"
COUNTY = "Randolph"

ENABLED = os.environ.get("FORECLOSURE_RANDOLPH_MYDT") != "0"
MAX_ROWS = int(os.environ.get("RANDOLPH_MYDT_MAX", "300"))
BUDGET_S = float(os.environ.get("RANDOLPH_MYDT_BUDGET_S", "600"))
CONCURRENCY = int(os.environ.get("RANDOLPH_MYDT_CONCURRENCY", "4"))
MIN_YEARS = int(os.environ.get("RANDOLPH_MYDT_MIN_YEARS", "2"))

_PORTAL = pwa.PORTALS[COUNTY]


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


def build_block(parcel: str, bills: list[dict], *, today: Optional[date] = None) -> Optional[dict]:
    """Pure: the raw['multi_year_delinquent_tax'] block from one parcel's full PTS Public Web
    Access bill grid (tax_lien_pwa.parse_grid's own `bills` list, taxYear="ALL"), or None when
    the parcel doesn't clear the multi-year gate (fewer than MIN_YEARS unpaid years, or no
    MATURED unpaid year -- a parcel whose only unpaid bill is this year's current, not-yet-due
    one is not repeat delinquency). `parcel` is the row's own parcel id; stored as parcel_key
    the same normalized way tax_binding.py's own parcel-id matching expects."""
    today = today or date.today()
    want = tc.alnum(parcel)
    per_year: dict[int, float] = {}
    for b in bills or ():
        if tc.alnum(b.get("parcel") or "") != want:
            continue
        due = b.get("due") or 0.0
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
        "layers": ["randolph_pwa_bill_search"],
        "parcel_key": _normalize_parcel(parcel),
        "source_url": _PORTAL.form_url,
    }


async def _fetch(client: Any, parcel: str) -> tuple[Optional[list[dict]], str]:
    """(bills, status) for one Randolph parcel via tax_lien_pwa's own live-proven form/grid
    chain, reused verbatim. status is "ok" with bills set, else a short machine reason."""
    try:
        grid = await pwa._search(client, _PORTAL, parcel)
    except Exception as exc:  # noqa: BLE001 - every outcome is an answer
        return None, f"fetch_failed:{type(exc).__name__}"
    bills = grid.get("bills") if isinstance(grid, dict) else None
    if not bills:
        return None, "no_bills_on_page"
    return bills, "ok"


async def enrich_with_randolph_multiyear_tax(listings: Iterable[Listing],
                                             *, client: Optional[Any] = None) -> dict[str, Any]:
    """Walk not-yet-checked Randolph NC board rows and stamp raw['multi_year_delinquent_tax']
    from the parcel's own live PTS Public Web Access bill grid when it shows real repeat
    delinquency. `client` is exposed for tests; the real pipeline always lets it default (a
    fresh Fetcher, this call's own rate limit)."""
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
        parcel = str(li.parcel_id or "").strip()
        async with sem:
            bills, status = await _fetch(cli, parcel)
        stats["attempted"] += 1
        if not isinstance(li.raw, dict):
            li.raw = {}
        if status != "ok":
            stats["no_bills" if status == "no_bills_on_page" else "fetch_errors"] += 1
            li.raw[CHECKED_KEY] = status
            return
        block = build_block(parcel, bills, today=today)
        if block is None:
            stats["insufficient_history"] += 1
            li.raw[CHECKED_KEY] = "insufficient_history"
            return
        block["checked_at"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
        li.raw[RAW_KEY] = block
        stats["qualified"] += 1

    await asyncio.gather(*(one(li) for li in capped))
    log.info("randolph_mydt.done", **stats)
    return stats
