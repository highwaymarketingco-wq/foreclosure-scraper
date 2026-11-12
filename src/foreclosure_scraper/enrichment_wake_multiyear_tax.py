"""Wake County NC multi-year delinquent-tax HISTORY, read live per parcel from the same
services.wake.gov source verification/verifiers/tax_lien_wake.py already verifies claims against.

WHY THIS EXISTS (docs/gap_matrix/gap_list_2026-10-18.csv, read before writing a line here).
    NC Wake "multi_year_delinquent_tax": applicable=12,941, hits=0, built="no",
    gap_class="sourced-not-built", source="tax/property card: services.wake.gov" -- the single
    biggest sourced-not-built cell in the whole gap matrix (shared with rollback_exposure,
    tax_aging_surfaced and atty_tax_verified_confirmed, all pointing at the same source).

    verification/verifiers/tax_lien_wake.py (same session) reads this exact source but, like
    tax_lien_devnet before enrichment_gaston_multiyear_tax.py, only for a row that ALREADY carries
    a property-tax CLAIM (`applies()` gates on `_tax_common.claims_property_tax`). None of Wake's
    12,941 board rows carry one (they come from NC OneMap / court / probate / code sources, not a
    Wake-specific tax-delinquent-list scraper), so that verifier never fires on them. This module
    is the missing UPSTREAM half, exactly the Gaston precedent (enrichment_gaston_multiyear_tax.py,
    2026-10-18 earlier the same night): it reads the parcel's own multi-year bill history directly
    and, when it shows real repeat delinquency, writes the claim
    (`raw['multi_year_delinquent_tax']`) tax_lien_wake (or any later verification sweep) can then
    confirm. There is no double-build: tax_lien_wake keeps doing its own job unchanged, and this
    module reuses its bridge/fetch/parse functions verbatim rather than duplicating them.

NO BULK ROLL ON THIS SOURCE (live-checked 2026-10-18). services.wake.gov's own ptax billing
    system is a per-account lookup (acctsummary.aspx?id=<REID>), not a published delinquent-list
    export -- same shape as Gaston's DevNetWedge, a different reason (Gaston's vendor has no
    county-wide export at all; Wake's bill search needs a specific account, and the only bulk
    export Wake's tax office publishes is the small tax-FORECLOSURE accordion
    wake_tax_foreclosure.py already reads, a tiny subset of all delinquent accounts). So this
    module walks the board's own already-resolved Wake rows one account at a time, same as Gaston.

PIN -> REID. The board's Wake parcel_id is the statewide 10-digit PIN; the bill search is keyed
    by Wake's own 7-digit REID. tax_lien_wake.resolve_reid() bridges one to the other via NC
    OneMap's own parcel layer (altparno), live-verified on 3 real parcels (tax_lien_wake module
    docstring) -- reused here verbatim, one extra live call per not-yet-bridged row.

LIVE-VERIFIED 2026-10-18 (same recon this module is built from). 3 real Wake board-shaped parcels,
    read through the identical PIN -> REID -> bill-history chain this module calls:
      PIN 1713252770 (REID 0047895, 610 Cumberland St, Raleigh) -- unpaid 2022-2026, 4 of the 5
          open-year bills actually LATE (2026's is this year's, not yet due), $1,710-$3,099 each,
          $8,544.84 total matured. A genuine, qualifying multi-year delinquency.
      PIN 0765045120 (REID 0210739, 100 Montauk Point Pl, Cary) -- 2024/2025 bills $0.00 (paid),
          only the current 2026 bill owes anything, and it is not late yet: correctly yields
          nothing (fewer than MIN_YEARS matured unpaid years).
      PIN 1797953869 (REID 0167151, 0 Ferrell Rd, Zebulon) -- a present-use farm whose ordinary
          "000000" bills are each $0 or the small present-use amount; its "002000" rollback-
          tracking rows are a SEPARATE fact (enrichment_rollback_deferral.py's own Wake path),
          never counted here as a second bill (tax_lien_wake.parse_bills' own suffix filter).

SHAPE. Reuses tax_lien_wake.resolve_reid / .fetch_bills / .parse_bills verbatim (the same
    live-proven bridge+fetch, cached per run) and
    scrapers.counties_generic.multi_year_delinquent_tax._longest_run / ._trend verbatim, so
    raw['multi_year_delinquent_tax'] here is byte-shape-compatible with the Buncombe/Oconee/
    Pickens/Gaston blocks -- tax_binding.BLOCK_PARCEL_FIELDS["multi_year_delinquent_tax"] =
    ("parcel_key",), enrichment_tax_owed._SOURCES's exact-key read of "total_due", and
    web_artifact.RAW_KEEP's "*" wildcard all already expect this shape; no downstream wiring
    needed. "years" here means years with an UNPAID "000000" bill (the ordinary annual bill
    only, never a present-use rollback-tracking row), and "matured" is read from
    tax_calendar.levy_year_is_delinquent (NC's statutory Jan-6 rule), same as Gaston.

SCALE / BUDGET. One live bridge lookup (when needed) + one live bill-history fetch per
    not-yet-checked Wake row -- 12,941 of them. Capped per run (WAKE_MYDT_MAX, default 300) and
    wall-clock-budgeted (WAKE_MYDT_BUDGET_S, default 600s), the identical shape
    enrichment_gaston_multiyear_tax.py already uses. Idempotent via `raw['_wake_mydt_checked']`
    on a row that was fetched but did NOT clear the multi-year gate or could not be resolved at
    all, same reason Gaston's module documents (without the sentinel, every run re-walks the same
    first-N unchecked rows forever). A qualifying hit needs no sentinel:
    raw['multi_year_delinquent_tax'] itself is the "done" mark. Repeated runs converge over the
    backlog; WAKE_MYDT_MAX can be raised for an explicit one-off backfill. Gate off entirely with
    FORECLOSURE_WAKE_MYDT=0.

PRIVACY. No owner name or mailing address is ever read or written here -- only the bridged REID
    (a public county account number) and tax-year amounts land in raw['multi_year_delinquent_tax'].
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
from .verification.verifiers import tax_lien_wake as _wake

log = structlog.get_logger()

RAW_KEY = "multi_year_delinquent_tax"
CHECKED_KEY = "_wake_mydt_checked"

ENABLED = os.environ.get("FORECLOSURE_WAKE_MYDT") != "0"
MAX_ROWS = int(os.environ.get("WAKE_MYDT_MAX", "300"))
BUDGET_S = float(os.environ.get("WAKE_MYDT_BUDGET_S", "600"))
CONCURRENCY = int(os.environ.get("WAKE_MYDT_CONCURRENCY", "4"))
MIN_YEARS = int(os.environ.get("WAKE_MYDT_MIN_YEARS", "2"))

#: the ordinary annual bill only -- a present-use "002000"-style suffix is a rollback-tracking
#: row, never a second tax bill (tax_lien_wake.parse_bills docstring)
_ORDINARY_SUFFIXES = ("000000", "0")


def _county_key(li: Listing) -> str:
    return (li.county or "").replace(" County", "").strip().lower()


def _already_done(li: Listing) -> bool:
    if not isinstance(li.raw, dict):
        return False
    return isinstance(li.raw.get(RAW_KEY), dict) or bool(li.raw.get(CHECKED_KEY))


def _eligible(li: Listing) -> bool:
    return (
        (li.state or "").strip().upper() == "NC"
        and _county_key(li) == "wake"
        and bool((li.parcel_id or "").strip())
        and not _already_done(li)
    )


def build_block(pin: str, reid: str, bills: list[dict], *,
                today: Optional[date] = None) -> Optional[dict]:
    """Pure: the raw['multi_year_delinquent_tax'] block from one account's full bill history
    (tax_lien_wake.fetch_bills' own `bills`), or None when the parcel doesn't clear the
    multi-year gate (fewer than MIN_YEARS unpaid ordinary-bill years, or no MATURED unpaid year --
    a parcel whose only unpaid bill is this year's current, not-yet-due one is not repeat
    delinquency)."""
    today = today or date.today()
    per_year: dict[int, float] = {}
    for b in bills or ():
        if b.get("suffix") not in _ORDINARY_SUFFIXES:
            continue
        due = b.get("amount_due") or 0.0
        if due > 0:
            per_year[b["year"]] = due
    years = sorted(per_year)
    if len(years) < MIN_YEARS:
        return None
    matured = [y for y in years if tax_calendar.levy_year_is_delinquent(y, "NC", "Wake", today)]
    if not matured:
        return None
    current = [y for y in years if y not in matured]
    total_owed = round(sum(per_year.values()), 2) or None
    matured_owed = round(sum(per_year[y] for y in matured), 2) or None
    latest_year = max((b["year"] for b in bills if b.get("suffix") in _ORDINARY_SUFFIXES),
                      default=years[-1])
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
        "county_latest_year": latest_year,
        "current_levy_year": (current[-1] if current else None),
        "in_current_levy": bool(current),
        "total_due": total_owed,
        "total_owed": total_owed,
        "matured_owed": matured_owed,
        "year": years[-1],
        "trend": _trend(per_year, matured),
        "still_accruing": years[-1] >= latest_year,
        "amount_basis": "annual_bill",
        "layers": ["wake_ptax_billing_history"],
        "parcel_key": _normalize_parcel(pin),
        "reid": reid,
    }


async def _resolve_and_fetch(client: Fetcher, pin: str,
                             today: date) -> tuple[Optional[str], Optional[list[dict]], str]:
    """(reid, bills, status) for one Wake PIN/REID via tax_lien_wake's own live-proven bridge +
    fetch chain, reused verbatim. status is "ok" with bills set, else a short machine reason."""
    try:
        reid = await _wake.resolve_reid(client, pin)
    except Exception as exc:  # noqa: BLE001
        return None, None, f"bridge_failed:{type(exc).__name__}"
    if not reid:
        return None, None, "bridge_no_match"
    try:
        bills = await _wake.fetch_bills(client, reid)
    except Exception as exc:  # noqa: BLE001
        return reid, None, f"fetch_failed:{type(exc).__name__}"
    return reid, bills, "ok"


async def enrich_with_wake_multiyear_tax(listings: Iterable[Listing],
                                         *, client: Optional[Fetcher] = None) -> dict[str, Any]:
    """Walk not-yet-checked Wake NC board rows and stamp raw['multi_year_delinquent_tax'] from
    the account's own live bill history when it shows real repeat delinquency. Module docstring
    covers why this can't be a bulk pass. `client` is exposed for tests; the real pipeline always
    lets it default (a fresh Fetcher, this call's own rate limit)."""
    stats = {"eligible": 0, "attempted": 0, "qualified": 0, "insufficient_history": 0,
             "no_bridge_match": 0, "no_bills": 0, "fetch_errors": 0,
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
        pin = (li.parcel_id or "").strip()
        async with sem:
            reid, bills, status = await _resolve_and_fetch(cli, pin, today)
        stats["attempted"] += 1
        if not isinstance(li.raw, dict):
            li.raw = {}
        checked_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
        if status != "ok":
            bucket = ("no_bridge_match" if status == "bridge_no_match"
                      else "fetch_errors")
            stats[bucket] += 1
            li.raw[CHECKED_KEY] = status
            return
        if not bills:
            stats["no_bills"] += 1
            li.raw[CHECKED_KEY] = "no_bills"
            return
        block = build_block(pin, reid, bills, today=today)
        if block is None:
            stats["insufficient_history"] += 1
            li.raw[CHECKED_KEY] = "insufficient_history"
            return
        block["checked_at"] = checked_at
        block["source_url"] = _wake.BILLS_URL.format(reid=reid)
        li.raw[RAW_KEY] = block
        stats["qualified"] += 1

    await asyncio.gather(*(one(li) for li in capped))
    log.info("wake_mydt.done", **stats)
    return stats
