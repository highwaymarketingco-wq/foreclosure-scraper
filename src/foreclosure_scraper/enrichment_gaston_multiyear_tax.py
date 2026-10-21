"""Gaston County NC multi-year delinquent-tax HISTORY, read live per parcel from the same
DevNetWedge source tax_lien_devnet.py already verifies claims against.

WHY THIS EXISTS (docs/gap_matrix/gap_matrix_2026-10-17.json, read before writing a line here).
    NC Gaston "multi_year_delinquent_tax": applicable=26620, hits=0, built="no",
    gap_class="sourced-not-built", source="tax/property card: gastonnc.devnetwedge.com". The
    SAME file's Gaston "rollback_exposure" row is NOT a gap (hits=958, built="ran",
    gap_class=None) -- enrichment_tax_relief.py's Gaston LUV_YES_NO entry already covers it. Any
    note claiming rollback_exposure is still open for Gaston is reading a stale number.

    verification/verifiers/tax_lien_devnet.py (2026-10-09) already reads this exact county's
    exact source -- GIS PIN -> PID, then the parcel page's own "Payment History" panel -- but
    only for a row that ALREADY carries a property-tax CLAIM (`applies()` gates on
    `_tax_common.claims_property_tax`). Of this county's 26,620 board rows (21,608 from
    `counties_nc.gaston_vacant` alone, live-counted 2026-10-18 against docs/listings.json.gz),
    none carry one, so that verifier never fires on them -- it has nothing to confirm, refute or
    go stale. This module is the missing UPSTREAM half: it reads the parcel's own multi-year
    history directly and, when it shows real repeat delinquency, writes the claim
    (`raw['multi_year_delinquent_tax']`) that verifier (or any later verification sweep) can then
    check. There is no double-build: tax_lien_devnet keeps doing its own job unchanged.

NO BULK ROLL ON THIS VENDOR (live-checked 2026-10-18, same session). gastonnc.devnetwedge.com's
    own homepage links exactly one search entry point, `/search/advanced`, whose two tabs POST to
    `/search/ExecuteJointSearch` (parcel number / owner name / address) and
    `/search/ExecuteParcelSearch` (value/acreage/sales ranges) -- neither tab offers a
    delinquency-only or "advertised list" filter, and there is no separate delinquent-tax-list
    page anywhere in the rendered chrome. Unlike Buncombe/Oconee/Pickens
    (scrapers/counties_generic/multi_year_delinquent_tax.py's own bulk ArcGIS "unpaid bills"
    layers, published once per county per year) or this same module's Robeson/Alexander/
    Rockingham sibling (enrichment_ustaxdata_tax_search.py), Gaston's vendor publishes no
    county-wide export at all -- the ONLY way to this history is one page per already-known
    parcel, exactly how tax_lien_devnet.py already reads it. So this module walks the board's
    OWN already-resolved Gaston rows rather than discovering a roll from scratch.

LIVE-VERIFIED 2026-10-18 (same recon re-run against today's live site; the GIS layer and parcel
    page shape both still match tax_lien_devnet.py's 2026-10-09 documentation exactly -- same
    endpoints, same markup). 60 random Gaston board parcel_ids were sampled live
    (board_stream.iter_board_rows('docs/listings.json.gz'), source counties_nc.gaston_vacant) and
    resolved through the identical GIS -> DevNetWedge chain this module calls:
      PIN 3535-68-1884 (PID 102990, HARTMAN ST, Gastonia) -- unpaid 2017-2026, ALL ten years,
          consecutive, $820.32 total ($796.27 of it matured/late as of today).
      PIN 2691-64-6188 (PID 157302, 442 ROBERT RD, Cherryville) -- unpaid 2022-2026, five
          consecutive years, $1,690.06 total ($1,421.45 matured).
      PIN 3516-35-2020 (PID 121138, W ALABAMA AVE, Bessemer City) -- unpaid every year
          2017-2024 and again 2026, EXCEPT 2025 (paid 2026-05-29): the longest run is 8, not 10 --
          a real gap, not a parsing miss. $258.63 total, $236.80 matured.
      PIN 3504-98-8203 (PID 154290, CANTERBURY RD, Kings Mountain) -- unpaid exactly 2025-2026,
          the minimum shape that still clears the >=2-year gate ($195.01 total, $103.51 matured).
    All four pages parsed cleanly with tax_lien_devnet.parse_parcel (reused verbatim, no copy).
    Most sampled parcels (the common case) are paid current and correctly yield nothing.

SHAPE. Reuses tax_lien_devnet.SITES / .lookup_pin / .fetch_parcel / .parse_parcel verbatim (same
    live-proven GIS+parcel fetch, caching and PortalDown circuit breaker) and
    scrapers.counties_generic.multi_year_delinquent_tax._longest_run / ._trend verbatim, so
    raw['multi_year_delinquent_tax'] here is byte-shape-compatible with the Buncombe/Oconee/
    Pickens scraper's own blocks -- tax_binding.BLOCK_PARCEL_FIELDS["multi_year_delinquent_tax"]
    = ("parcel_key",), enrichment_tax_owed._SOURCES's exact-key read of "total_due", and
    web_artifact.RAW_KEEP's "*" wildcard all already expect this shape; no downstream wiring
    needed. One real difference from that sibling: DevNetWedge's own Payment History table
    carries every year it bills, paid or not, so `years` here means years with an UNPAID amount
    (matching what Buncombe/Oconee/Pickens' own "unpaid bills" layers already mean by `years` --
    they simply never emit a paid year at all), and "matured" is read directly from
    tax_calendar.levy_year_is_delinquent (NC's statutory Jan-6 rule) rather than Buncombe's
    current-levy-ROW-COUNT heuristic: that heuristic exists only because Buncombe's bulk layer
    doesn't state a bill's own due date, and DevNetWedge's per-parcel bill effectively does.

SCALE / BUDGET. No bulk roll means one live GIS lookup + one live parcel-page fetch per
    not-yet-checked Gaston row -- 26,620 of them. Capped per run (GASTON_MYDT_MAX, default 300)
    and wall-clock-budgeted (GASTON_MYDT_BUDGET_S, default 600s), the same shape
    enrichment_lrcpwa_parcel.py already uses for its own per-parcel network enrichment.
    Idempotent via `raw['_gaston_mydt_checked']` (RAW_KEEP'd below as "*", a short status string)
    on a row that was fetched but did NOT clear the multi-year gate or could not be resolved at
    all -- WITHOUT that sentinel surviving to the next run's "prior board", every run would re-walk
    the same first-N unchecked rows forever and never reach the rest, the exact failure
    enrichment_land_buildability.py's own RAW_KEEP comment already documents having hit once.
    A qualifying hit needs no sentinel: raw['multi_year_delinquent_tax'] itself is the "done" mark.
    Repeated runs converge over the backlog; GASTON_MYDT_MAX can be raised for an explicit
    one-off backfill. Gate off entirely with FORECLOSURE_GASTON_MYDT=0.

PRIVACY. No owner name or mailing address is ever read or written here -- DevNetWedge's parcel
    page carries a "Paid By" payer name on its Billing panel, which this module (like
    tax_lien_devnet.py before it) never reads. raw['multi_year_delinquent_tax'] carries only
    tax-year amounts and the parcel's own id.
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
from .verification.verifiers import tax_lien_devnet as _devnet

log = structlog.get_logger()

RAW_KEY = "multi_year_delinquent_tax"
CHECKED_KEY = "_gaston_mydt_checked"

ENABLED = os.environ.get("FORECLOSURE_GASTON_MYDT") != "0"
MAX_ROWS = int(os.environ.get("GASTON_MYDT_MAX", "300"))
BUDGET_S = float(os.environ.get("GASTON_MYDT_BUDGET_S", "600"))
CONCURRENCY = int(os.environ.get("GASTON_MYDT_CONCURRENCY", "4"))
MIN_YEARS = int(os.environ.get("GASTON_MYDT_MIN_YEARS", "2"))

_SITE = _devnet.SITES["gaston"]


def _county_key(li: Listing) -> str:
    return (li.county or "").replace(" County", "").strip().lower()


def _already_done(li: Listing) -> bool:
    if not isinstance(li.raw, dict):
        return False
    return isinstance(li.raw.get(RAW_KEY), dict) or bool(li.raw.get(CHECKED_KEY))


def _eligible(li: Listing) -> bool:
    return (
        (li.state or "").strip().upper() == "NC"
        and _county_key(li) == "gaston"
        and bool(_devnet.pin_of(li.parcel_id))
        and not _already_done(li)
    )


def build_block(pin: str, bills: list[dict], *, today: Optional[date] = None) -> Optional[dict]:
    """Pure: the raw['multi_year_delinquent_tax'] block from one parcel's full DevNetWedge
    Payment History (tax_lien_devnet.parse_parcel's `bills`), or None when the parcel doesn't
    clear the multi-year gate (fewer than MIN_YEARS unpaid years, or no MATURED unpaid year --
    a parcel whose only unpaid bill is this year's current, not-yet-due one is not repeat
    delinquency). `pin` is the row's own parcel id, dashed or not; stored as parcel_key the same
    normalized way tax_binding.py's own parcel-id matching expects."""
    today = today or date.today()
    per_year: dict[int, float] = {}
    for b in bills or ():
        unpaid = b.get("unpaid") or 0.0
        if unpaid > 0:
            per_year[b["year"]] = unpaid
    years = sorted(per_year)
    if len(years) < MIN_YEARS:
        return None
    matured = [y for y in years if tax_calendar.levy_year_is_delinquent(y, "NC", "Gaston", today)]
    if not matured:
        return None
    current = [y for y in years if y not in matured]
    total_owed = round(sum(per_year.values()), 2) or None
    matured_owed = round(sum(per_year[y] for y in matured), 2) or None
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
        "layers": ["gaston_devnetwedge_payment_history"],
        "parcel_key": _normalize_parcel(pin),
    }


def build_two_year_block(bills: list[dict], *, today: Optional[date] = None) -> dict:
    """Pure: the raw['two_year_delinquent'] wrapper, written unconditionally once a search
    actually answers -- even a zero-matured-year answer states `is_two_year_plus` truthfully,
    the same convention enrichment_nash_multiyear_tax.py's own build_two_year_block() uses for
    its sibling column from the identical kind of per-year bill list. A SEPARATE function from
    build_block() above (not a refactor of it) specifically so this addition can never change
    multi_year_delinquent_tax's existing, already-live output."""
    today = today or date.today()
    per_year: dict[int, float] = {}
    for b in bills or ():
        unpaid = b.get("unpaid") or 0.0
        if unpaid > 0:
            per_year[b["year"]] = unpaid
    matured = tax_calendar.completed_delinquent_years(sorted(per_year), "NC", "Gaston", today)
    return {
        "is_two_year_plus": len(matured) >= 2,
        "years": len(matured),
        "oldest_year": min(matured) if matured else None,
        "source": "gaston_devnetwedge_payment_history",
    }


async def _resolve_and_fetch(client: Fetcher, pin: str,
                             today: date) -> tuple[Optional[str], Optional[list[dict]], str]:
    """(pid, bills, status) for one Gaston PIN via tax_lien_devnet's own live-proven GIS + parcel
    chain, reused verbatim. status is "ok" with bills set, else a short machine reason."""
    try:
        hit = await _devnet.lookup_pin(client, _SITE, pin)
    except _devnet.PortalDown as exc:
        return None, None, f"portal_unhealthy:{str(exc)[:60]}"
    except Exception as exc:  # noqa: BLE001
        return None, None, f"gis_fetch_failed:{type(exc).__name__}"
    if hit is None:
        return None, None, "gis_no_match"
    pid = hit["pid"]
    last_exc: Optional[BaseException] = None
    for y in (today.year, today.year - 1):
        try:
            page = await _devnet.fetch_parcel(client, _SITE, pid, y)
            return pid, page["bills"], "ok"
        except _devnet.PortalDown as exc:
            return pid, None, f"portal_unhealthy:{str(exc)[:60]}"
        except Exception as exc:  # noqa: BLE001
            last_exc = exc
    reason = type(last_exc).__name__ if last_exc else "no_parcel_page"
    return pid, None, f"no_parcel_page:{reason}"


async def enrich_with_gaston_multiyear_tax(listings: Iterable[Listing],
                                           *, client: Optional[Fetcher] = None) -> dict[str, Any]:
    """Walk not-yet-checked Gaston NC board rows and stamp raw['multi_year_delinquent_tax'] from
    the parcel's own live DevNetWedge payment history when it shows real repeat delinquency.
    Module docstring covers why this can't be a bulk pass. `client` is exposed for tests; the
    real pipeline always lets it default (a fresh Fetcher, this call's own rate limit)."""
    stats = {"eligible": 0, "attempted": 0, "qualified": 0, "insufficient_history": 0,
             "no_gis_match": 0, "no_parcel_page": 0, "fetch_errors": 0,
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
        pin = _devnet.pin_of(li.parcel_id)
        async with sem:
            pid, bills, status = await _resolve_and_fetch(cli, pin, today)
        stats["attempted"] += 1
        if not isinstance(li.raw, dict):
            li.raw = {}
        checked_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
        if status != "ok":
            bucket = ("no_gis_match" if status == "gis_no_match"
                      else "no_parcel_page" if status.startswith("no_parcel_page")
                      else "fetch_errors")
            stats[bucket] += 1
            li.raw[CHECKED_KEY] = status
            return
        # A real Payment History answer came back -- stamp two_year_delinquent from it either
        # way (qualifies for the stricter multi-year gate below, or not). Pure addition: never
        # touches CHECKED_KEY/RAW_KEY's existing behavior on the lines just below it.
        if "two_year_delinquent" not in li.raw:
            li.raw["two_year_delinquent"] = build_two_year_block(bills, today=today)
        block = build_block(pin, bills, today=today)
        if block is None:
            stats["insufficient_history"] += 1
            li.raw[CHECKED_KEY] = "insufficient_history"
            return
        block["pid"] = pid
        block["checked_at"] = checked_at
        block["source_url"] = _devnet.parcel_url(_SITE, pid, today.year)
        li.raw[RAW_KEY] = block
        stats["qualified"] += 1

    await asyncio.gather(*(one(li) for li in capped))
    log.info("gaston_mydt.done", **stats)
    return stats
