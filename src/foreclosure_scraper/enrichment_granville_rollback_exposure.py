"""Granville County NC ``tax.granvillecounty.org`` BasicSearch "Deferred" field -> the shared
raw['rollback_exposure'] contract enrichment_rollback_deferral.py established and gap_matrix.py's
own checked_columns()/positive_columns() already read.

WHY THIS EXISTS (overnight task, 2026-10-21: "Granville County NC: rollback_exposure +
multi_year_delinquent_tax (1,944 rows each), source: tax.granvillecounty.org"). The task asked
to check, before building anything, whether Granville shares a platform already read elsewhere --
specifically Harnett's cama.harnett.org/ITSPublicHT "ITS Public" BasicSearch product
(enrichment_harnett_rollback_exposure.py, 2026-10-20), built for exactly this same situation: a
county whose TaxBillSearch tenant (scrapers/counties_nc/nc_its_public_tax.py's own PORTALS
dict -- Granville has had an entry there, "https://tax.granvillecounty.org/ITSPublic",
full_model=True, since the 2026-10-09 top-80 build) sits on a host that is NOT
www.bttaxpayerportal.com, so it was never added to enrichment_bt_appraisal_card.py's/
enrichment_bt_parcel_info.py's shared 14-county TENANTS dict either.

LIVE-VERIFIED 2026-10-21 (real search + ViewParcel fetch against the real host, read-only, no
board touched): GET https://tax.granvillecounty.org/ITSPublic/ -> HTTP 200, title "Basic Search",
9,322 bytes -- the SAME CAMA product's own landing page, not the TaxBillSearch one, confirming
this tenant exposes BOTH products under the one host (the same shape
enrichment_its_public_multiyear_tax.py's own docstring already documents for Duplin). A real
owner-name search + ViewParcel fetch for three different live board owners (Stokes, parcel
099000689935; Dickerson, parcel 193504630294; Daniel, parcel 192320718727) all returned a real
"Property Values" fieldset with the SAME six lines Harnett's does -- Building, Obxf, Land, Market,
Assessed, Deferred, Exemption(s) -- confirmed via the SAME shared parser,
enrichment_bt_parcel_info.parse_view_parcel(), which already extracts "Deferred" for every
TENANTS county (added 2026-10-20 for Harnett; this module reuses it unchanged). All three sampled
owners read Deferred=0 (not under present-use deferral) -- real zeros, not a parsing failure (the
same field reads real, nonzero Market/Assessed/deed values on every one of them) -- so a positive
hit is a matter of which of the 882 already-matched Granville parcels (and however many more a
fresh search resolves) happen to carry a present-use deferral, not a question of whether the
field exists. See scripts/backfill_granville_rollback_exposure.py for the real measured yield.

NOT THE SAME GAP AS multi_year_delinquent_tax (reported and fixed separately, nothing here depends
on it): a live board scan 2026-10-21 found all 882 Granville rows carrying raw['nc_its_public_tax']
have exactly ONE bill year on file (years_read is unset -- a capped/sample run, not a full
YEARS_BACK=20 read), although the real portal has genuine multi-year depth back to at least 2020
(live-probed: 2025/2024/2023/2020 all nonzero, one real multi-year parcel found in the first 20
rows sampled: account 1117983 / parcel 089610454922, delinquent both 2024 and 2025). That is a
scraper RUN-DEPTH gap on the TaxBillSearch side, fixed by re-running the existing, unmodified
NcItsPublicTax scraper for this one county at full depth (scripts/backfill_granville_multiyear_tax.py),
not by any code here.

WHAT THIS MODULE DOES. Identical shape to enrichment_harnett_rollback_exposure.py: reuses
enrichment_bt_parcel_info.py's own, already-tested _search_owner()/_view_parcel()/_search_query()/
_best_match() functions (all already generic over a `tenant_base` url) against Granville's own
host instead of bttaxpayerportal.com, the same two-step flow (search by "LAST FIRST", confirm with
BOTH owner name AND street address, then fetch ViewParcel) and the same bounds (MAX_LISTINGS, a
small concurrency, a hard candidate-count ceiling against a common-surname over-match). Granville
is not added to enrichment_bt_appraisal_card.TENANTS because its host is NOT
www.bttaxpayerportal.com -- the same reason Harnett's own module gives.

RATE, NEVER ASSUMED (same convention as Harnett's module and
enrichment_rollback_deferral.py's Buncombe/Wake/Mecklenburg sections). The effective combined tax
rate is DERIVED per parcel from that SAME parcel's own numbers -- never a hard-coded millage --
from raw['nc_its_public_tax']['bills'] (the TaxBillSearch product every Granville board row
already carries) divided by THIS fetch's own assessed_value, kept only when it lands inside the
sane band (_RATE_MIN/_RATE_MAX). A parcel whose rate doesn't land in the band (or has no matching
bill) still gets its real deferred_value, just without a derived annual/estimated-rollback figure.

GATE. Only a positive `deferred_value` off a CONFIRMED (owner name + street address) ViewParcel
match qualifies -- build_block() never invents one.

Bounded, opt-in, free, public, no login, no CAPTCHA (same host enrichment_bt_appraisal_card.py's
14-county TENANTS family already reads, same per-row request shape). Gate off entirely with
FORECLOSURE_GRANVILLE_ROLLBACK=0.
"""
from __future__ import annotations

import asyncio
import os
from typing import Any, Iterable, Optional

import httpx
import structlog

from .enrichment_bt_parcel_info import (
    _UA, _best_match, _search_owner, _search_query, _view_parcel,
)
from .enrichment_rollback_deferral import _RATE_MAX, _RATE_MIN
from .models import Listing
from .name_normalize import is_entity

log = structlog.get_logger()

RAW_KEY = "rollback_exposure"
SOURCE_KEY = "granville_cama"
TENANT_BASE = "https://tax.granvillecounty.org/ITSPublic"
#: NC G.S. 105-277.4(c) -- see enrichment_rollback_deferral.py's module docstring.
ROLLBACK_YEARS_NC = 4

MAX_LISTINGS = int(os.getenv("GRANVILLE_ROLLBACK_MAX", "300"))
_CONCURRENCY = int(os.getenv("GRANVILLE_ROLLBACK_CONCURRENCY", "3"))
#: a search whose candidate set is this large or more is too loose to trust
MAX_CANDIDATES = 20

ENABLED = os.environ.get("FORECLOSURE_GRANVILLE_ROLLBACK") != "0"


def _already_done(raw: Any) -> bool:
    return isinstance(raw, dict) and isinstance(raw.get(RAW_KEY), dict)


def _positive(v: Any) -> Optional[float]:
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return f if f > 0 else None


def _eligible(li: Listing) -> bool:
    raw = li.raw if isinstance(li.raw, dict) else {}
    return bool(
        li.state == "NC" and (li.county or "").strip().lower() == "granville"
        and li.owner_name and not is_entity(li.owner_name)
        and (li.street_address or "").strip()
        and not _already_done(raw)
    )


def rate_from_its_public_tax(raw: dict, assessed_value: Any, tax_year: Any) -> Optional[float]:
    """Pure: the matching tax year's bill.original_levy / assessed_value from this row's OWN
    already-fetched raw['nc_its_public_tax']['bills'] -- no new network call, no assumed millage.
    None when there is no bill for that year, no usable assessed_value, or the ratio falls
    outside the sane band every sibling rollback section already validates against. Identical
    to enrichment_harnett_rollback_exposure.rate_from_its_public_tax (not imported from there to
    avoid a cross-county-module dependency for a four-line pure function)."""
    assessed = _positive(assessed_value)
    src = raw.get("nc_its_public_tax") if isinstance(raw, dict) else None
    if not isinstance(src, dict) or assessed is None:
        return None
    try:
        year_int = int(str(tax_year)[:4])
    except (TypeError, ValueError):
        return None
    for bill in src.get("bills") or ():
        if not isinstance(bill, dict) or bill.get("year") != year_int:
            continue
        levy = _positive(bill.get("original_levy"))
        if levy is None:
            continue
        rate = levy / assessed
        if _RATE_MIN <= rate <= _RATE_MAX:
            return rate
    return None


def build_block(detail: dict, raw: dict) -> Optional[dict]:
    """Pure: the raw['rollback_exposure'] record from one ViewParcel detail's own 'Deferred'
    Property-Values line, or None when it is blank/zero -- never invented."""
    deferred = _positive((detail or {}).get("deferred_value"))
    if deferred is None:
        return None
    rec: dict[str, Any] = {
        "deferred_value": round(deferred, 2),
        "basis": "present_use_deferral",
        "county": "Granville",
        "state": "NC",
        "source": 'tax.granvillecounty.org/ITSPublic BasicSearch, ViewParcel "Property Values" ("Deferred :")',
        "source_key": SOURCE_KEY,
        "rollback_years": ROLLBACK_YEARS_NC,
        "estimate_is_floor": True,       # statutory interest not modelled
        "match_method": "owner_name+street_address",
    }
    tax_year = detail.get("tax_year")
    if tax_year:
        rec["tax_year"] = tax_year
    rate = rate_from_its_public_tax(raw, detail.get("assessed_value"), tax_year)
    if rate:
        annual = round(deferred * rate, 2)
        rec.update(effective_tax_rate=round(rate, 6), tax_rate_source="nc_its_public_tax_bill",
                   annual_deferred_tax=annual, estimated_rollback=round(annual * ROLLBACK_YEARS_NC, 2))
    return rec


async def enrich_granville_rollback_exposure(listings: Iterable[Listing]) -> dict[str, Any]:
    """Search tax.granvillecounty.org/ITSPublic by owner name, confirm with street address (never
    one signal alone), fetch ViewParcel for the confirmed match, and restate its 'Deferred'
    Property-Values line into raw['rollback_exposure'] when positive. Writes
    raw['rollback_exposure']."""
    if not ENABLED:
        return {"skipped": "disabled (FORECLOSURE_GRANVILLE_ROLLBACK=0)"}
    targets = [li for li in listings if _eligible(li)]
    stats = {"eligible": len(targets), "searched": 0, "no_candidates": 0,
             "too_many_candidates": 0, "no_confident_match": 0, "matched": 0,
             "errors": 0, "deferred_found": 0}
    if not targets:
        return stats
    targets = targets[:MAX_LISTINGS]
    sem = asyncio.Semaphore(_CONCURRENCY)

    async with httpx.AsyncClient(timeout=30.0, headers={"User-Agent": _UA},
                                 follow_redirects=True) as c:
        async def one(li: Listing) -> None:
            query = _search_query(li)
            if not query:
                return
            async with sem:
                try:
                    candidates = await _search_owner(c, TENANT_BASE, query)
                except Exception:  # noqa: BLE001 - one lead never kills the pass
                    stats["errors"] += 1
                    return
                await asyncio.sleep(0.4)
            stats["searched"] += 1
            if not candidates:
                stats["no_candidates"] += 1
                return
            if len(candidates) >= MAX_CANDIDATES:
                stats["too_many_candidates"] += 1
                return
            match = _best_match(li, candidates)
            if not match or not match.get("tax_year"):
                stats["no_confident_match"] += 1
                return
            async with sem:
                try:
                    detail = await _view_parcel(c, TENANT_BASE, match["parcel_number"],
                                                match["tax_year"])
                except Exception:  # noqa: BLE001
                    stats["errors"] += 1
                    return
                await asyncio.sleep(0.4)
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
    log.info("granville_rollback.done", **stats)
    return stats
