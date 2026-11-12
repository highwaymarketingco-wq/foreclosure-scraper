"""Madison County NC ``lrcpwa.ncptscloud.com`` parcel-CAMA "Deferred" fields -> the shared
raw['rollback_exposure'] contract enrichment_rollback_deferral.py established and gap_matrix.py's
own checked_columns()/positive_columns() already read.

WHY THIS EXISTS (docs/gap_matrix/gap_list_2026-10-28.csv). rollback_exposure shows
sourced-not-built for Madison (1,704 applicable), source "tax/property card:
lrcpwa.ncptscloud.com" -- the SAME LandRecordsCloud CAMA/parcel REST API (SimpleParcelSearch +
getParcelDetails, X-Tenant header selects the county) that enrichment_hyde_rollback_exposure.py
already built and verified for Hyde 2026-10-20. This module is that same, already-proven pattern,
re-applied to Madison; see enrichment_hyde_rollback_exposure.py's own docstring for the original
live evidence (Hyde parcel pk=1600: totalLandValueAssessed - landUseValue == totalDeferredValue
to the dollar).

LIVE-VERIFIED 2026-10-28: Madison IS a live lrcpwa tenant (X-Tenant: Madison -> SimpleParcelSearch
totalCount 1,065, plain httpx 200, no login/CAPTCHA). getParcelDetails?ParcelId=2 (PIN
9706-66-4047, 75 Roberts Hill Rd, Marshall NC) returned the identical field set Hyde's module
reads -- totalLandValueAssessed, landUseValue, useValueDeferred, historicValueDeferred,
totalDeferredValue -- confirming the schema is shared across lrcpwa tenants, not Hyde-specific.
That particular sampled parcel had totalDeferredValue=0 (no present-use enrollment), so a positive
hit still needs a real parcel that carries one; build_block() below never invents one, same gate
as Hyde's.

Madison is also already a scrapers/counties_nc/nc_ptscloud_delinquent_tax.py TENANTS entry (its
own per-bill delinquent-tax history lands in raw['nc_ptscloud_delinquent_tax']), so
rate_from_ptscloud_bill's per-row effective-tax-rate derivation below works unchanged -- no new
network call, same sane-band validation as every other rollback section in this family.

MATCH METHOD: parcel id only, identical bar to Hyde (no owner-name/address confirmation -- the PIN
is dispositive once lrcpwa echoes it back unchanged). Query SimpleParcelSearch with the board
row's own digits-only parcel_id; a result is trusted only when its own formattedPin, stripped to
digits, matches EXACTLY.

LIVE-MEASURED 2026-10-28 (streamed the real board, read-only): of Madison's 1,704 rows, 350
(20.5%) carry a parcel_id already shaped like lrcpwa's own 9-11 digit PIN -- a better starting
reach than Hyde's 8.5%, still bounded by MAX_LISTINGS per run same as Hyde.

Bounded, opt-in, free, public JSON API, no login, no CAPTCHA, no robots wall. Gate off entirely
with FORECLOSURE_MADISON_ROLLBACK=0.
"""
from __future__ import annotations

import asyncio
import os
import re
from typing import Any, Iterable, Optional

import structlog

from .enrichment_ncpts_lrc import _get_parcel_detail, _search_parcels
from .enrichment_rollback_deferral import _RATE_MAX, _RATE_MIN
from .models import Listing

log = structlog.get_logger()

RAW_KEY = "rollback_exposure"
SOURCE_KEY = "madison_lrcpwa"
TENANT = "Madison"
#: NC G.S. 105-277.4(c) -- see enrichment_rollback_deferral.py's module docstring.
ROLLBACK_YEARS_NC = 4

MAX_LISTINGS = int(os.getenv("MADISON_ROLLBACK_MAX", "400"))
_CONCURRENCY = int(os.getenv("MADISON_ROLLBACK_CONCURRENCY", "4"))

ENABLED = os.environ.get("FORECLOSURE_MADISON_ROLLBACK") != "0"

_PIN_RE = re.compile(r"^[0-9]{9,11}$")


def _digits(s: Any) -> str:
    return re.sub(r"[^0-9]", "", str(s or ""))


def _positive(v: Any) -> Optional[float]:
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return f if f > 0 else None


def _already_done(raw: Any) -> bool:
    return isinstance(raw, dict) and isinstance(raw.get(RAW_KEY), dict)


def _eligible(li: Listing) -> bool:
    raw = li.raw if isinstance(li.raw, dict) else {}
    pid = (li.parcel_id or "").strip()
    return bool(
        li.state == "NC" and (li.county or "").strip().lower() == "madison"
        and _PIN_RE.match(pid) and not _already_done(raw)
    )


def rate_from_ptscloud_bill(raw: dict, assessed_value: Any, tax_year: Any) -> Optional[float]:
    """Pure: the matching tax year's BILL_AMOUNT / assessed_value from this row's OWN already-
    fetched raw['nc_ptscloud_delinquent_tax']['by_year'] -- no new network call, no assumed
    millage. None when there is no bill for that year, no usable assessed_value, or the ratio
    falls outside the sane band every sibling rollback section already validates against."""
    assessed = _positive(assessed_value)
    src = raw.get("nc_ptscloud_delinquent_tax") if isinstance(raw, dict) else None
    if not isinstance(src, dict) or assessed is None:
        return None
    try:
        year_int = str(int(str(tax_year)[:4]))
    except (TypeError, ValueError):
        return None
    for bill in src.get("by_year") or ():
        if not isinstance(bill, dict) or str(bill.get("tax_year") or "")[:4] != year_int:
            continue
        levy = _positive(bill.get("bill_amount"))
        if levy is None:
            continue
        rate = levy / assessed
        if _RATE_MIN <= rate <= _RATE_MAX:
            return rate
    return None


def build_block(detail: dict, raw: dict) -> Optional[dict]:
    """Pure: the raw['rollback_exposure'] record from one lrcpwa getParcelDetails response's own
    totalDeferredValue/useValueDeferred, or None when it is blank/zero -- never invented."""
    deferred = _positive(detail.get("totalDeferredValue"))
    if deferred is None:
        deferred = _positive(detail.get("useValueDeferred"))
    if deferred is None:
        return None
    rec: dict[str, Any] = {
        "deferred_value": round(deferred, 2),
        "basis": "present_use_deferral",
        "county": "Madison",
        "state": "NC",
        "source": "lrcpwa.ncptscloud.com getParcelDetails (totalDeferredValue)",
        "source_key": SOURCE_KEY,
        "rollback_years": ROLLBACK_YEARS_NC,
        "estimate_is_floor": True,       # statutory interest not modelled
        "match_method": "parcel",
    }
    tax_year = detail.get("taxYear")
    if tax_year:
        rec["tax_year"] = tax_year
    rate = rate_from_ptscloud_bill(raw, detail.get("landUseValue"), tax_year)
    if rate:
        annual = round(deferred * rate, 2)
        rec.update(effective_tax_rate=round(rate, 6), tax_rate_source="nc_ptscloud_delinquent_tax_bill",
                   annual_deferred_tax=annual, estimated_rollback=round(annual * ROLLBACK_YEARS_NC, 2))
    return rec


async def _match_by_pin(tenant: str, pin: str) -> Optional[dict]:
    """The one lrcpwa result whose own formattedPin, stripped to digits, equals `pin` exactly --
    never "closest" or "only result in a loose text search"."""
    results = await _search_parcels(tenant, pin, limit=5)
    for r in results:
        if _digits(r.get("formattedPin")) == pin:
            return r
    return None


async def enrich_madison_rollback_exposure(listings: Iterable[Listing]) -> dict[str, Any]:
    """Look up Madison NC rows whose parcel_id is already shaped like lrcpwa's own 9-11 digit PIN,
    confirm an exact PIN match on lrcpwa.ncptscloud.com, and restate a positive deferred value
    into raw['rollback_exposure']. Writes raw['rollback_exposure']."""
    if not ENABLED:
        return {"skipped": "disabled (FORECLOSURE_MADISON_ROLLBACK=0)"}
    targets = [li for li in listings if _eligible(li)]
    stats = {"eligible": len(targets), "searched": 0, "no_match": 0, "matched": 0,
             "errors": 0, "deferred_found": 0}
    if not targets:
        return stats
    targets = targets[:MAX_LISTINGS]
    sem = asyncio.Semaphore(_CONCURRENCY)

    async def one(li: Listing) -> None:
        pin = _digits(li.parcel_id)
        async with sem:
            try:
                hit = await _match_by_pin(TENANT, pin)
            except Exception:  # noqa: BLE001 - one lead never kills the pass
                stats["errors"] += 1
                return
            stats["searched"] += 1
            if not hit or not hit.get("id"):
                stats["no_match"] += 1
                return
            try:
                detail = await _get_parcel_detail(TENANT, hit["id"])
            except Exception:  # noqa: BLE001
                stats["errors"] += 1
                return
            await asyncio.sleep(0.2)
        if not detail:
            return
        stats["matched"] += 1
        raw = li.raw if isinstance(li.raw, dict) else {}
        block = build_block(detail, raw)
        if not block:
            return
        stats["deferred_found"] += 1
        if not isinstance(li.raw, dict):
            li.raw = {}
        li.raw[RAW_KEY] = block

    await asyncio.gather(*(one(li) for li in targets))
    log.info("madison_rollback.done", **stats)
    return stats
