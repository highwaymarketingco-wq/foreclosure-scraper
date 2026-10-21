"""Duplin County NC ``www.bttaxpayerportal.com/ITSPublicDL`` BasicSearch "Deferred" field -> the
shared raw['rollback_exposure'] contract enrichment_rollback_deferral.py established and
gap_matrix.py's own checked_columns()/positive_columns() already read.

WHY THIS EXISTS (docs/gap_matrix/gap_list_2026-10-21.csv, read before writing a line here).
    rollback_exposure, multi_year_delinquent_tax and liens all show the identical 3,519
    est_rows_affected for Duplin NC -- one missing piece flagged three ways. Two of the three
    (multi_year_delinquent_tax, liens) turned out to be ALREADY wired/built in this repo and
    simply never landed on the board yet (see scripts/backfill_duplin_multiyear_tax.py and the
    VM-vs-Mac IP-wall finding recorded in the task report for liens -- nothing to add there).
    rollback_exposure genuinely had no county-specific module, but it is NOT a new source: Duplin
    is already one of the 14 counties in enrichment_bt_appraisal_card.TENANTS ("DL"), the exact
    same www.bttaxpayerportal.com host/product enrichment_bt_parcel_info.py already reads for
    Granville/Harnett/Brunswick's siblings. county_records_matrix.json's own Duplin "tax" entry
    (url bttaxpayerportal.com/ITSPublicDL/, access "open", "verified as Duplin 2026-09-11 by
    enrichment_bt_appraisal_card.py") is correct on the host, but silent on whether the ViewParcel
    "Deferred" field (added to the shared parser 2026-10-20 for Harnett) actually resolves here --
    that was the open question this module answers live, not by assuming the vendor family
    behaves identically everywhere (it does not: see the query-format trap below).

LIVE-VERIFIED 2026-10-21 (real search + ViewParcel fetches against the real host, read-only, no
    board touched, using real board owners). GET https://www.bttaxpayerportal.com/ITSPublicDL/ ->
    200, title "Basic Search" -- confirms the Duplin tenant is live and reachable (no Cloudflare
    wall on this host, unlike the courthousecomputersystems.com liens finding for this same
    county). Four real board owners (HOLLOWAY DEBORAH MOORE, POLLARD JOSEPH, MOORE KENNETH,
    ETCHISON WILLIAM E JR) all returned ZERO candidates against
    enrichment_bt_parcel_info._search_query()'s own "LAST FIRST" (space-separated) shape -- a
    DUPLIN-TENANT-SPECIFIC QUERY FORMAT TRAP, not a missing-owner problem: Duplin's own
    GetSearchOptionsPartial form text reads "Enter Name (Last First) separated by a comma. (Ex.
    PUBLIC, JOHN Q)" and re-querying with a comma ("MOORE, KENNETH") returned the exact real
    match (parcel 01-1919- -, 702 S PINE ST, matching the board row for parcel_id 247514330584)
    immediately. Warren's own tenant (already wired, _search_query's origin) accepts the
    space-separated form -- this is a genuine per-tenant difference on the identical product,
    the same category of trap enrichment_bt_appraisal_card.py's own per-county reval-year and
    per-county id-format discoveries already document for this vendor family. This module ships
    its own `_search_query` (comma-separated) rather than reusing the shared one.

    ViewParcel for the confirmed MOORE, KENNETH match returned a real "Property Values" fieldset
    (market_value 13,800, assessed_value 13,800, deferred_value 0.0) via the exact shared parser,
    enrichment_bt_parcel_info.parse_view_parcel() -- unmodified, no Duplin-specific parsing
    needed. A SECOND live owner, LANIER, JACKIE S (165 Durwood Evans Rd, a real board row),
    returned a GENUINE NONZERO present-use deferral: market_value 129,100, assessed_value 94,300,
    deferred_value 34,800 -- proof the field carries real data here, not just real zeros (the
    single data point Granville's and Brunswick's own modules shipped on).

    Search-result shape: unlike Brunswick (which returns one row PER AVAILABLE TAX YEAR for the
    same parcel, live-documented in enrichment_brunswick_rollback_exposure.py), Duplin's tenant
    returns exactly ONE row per real parcel, always tagged "2027" (its current listing year), and
    ViewParcel for that exact (parcel, "2027") pair resolves with real, unmasked numbers --
    sampled 2026/2025 for the same parcel both answered an empty fieldset (no record for those
    years on this tenant, not a "next year masked" trap the way Brunswick's 2027 was). So this
    module reuses enrichment_bt_parcel_info.py's plain `_best_match()` (single-candidate,
    owner+address bar, no per-parcel year grouping) rather than Brunswick's `_best_parcel_match()`.

NOT THE SAME GAP AS multi_year_delinquent_tax or liens (reported and investigated separately,
    nothing here depends on either): see scripts/backfill_duplin_multiyear_tax.py for the
    multi_year_delinquent_tax run-depth gap (an existing, wired restatement module,
    enrichment_its_public_multiyear_tax.py, that currently qualifies 0 Duplin rows because the
    underlying nc_its_public_tax scrape on the board only carries ONE bill year per parcel, not
    the scraper's own YEARS_BACK=20 depth -- the identical shape Granville's own
    backfill_granville_multiyear_tax.py already fixed for that county).

WHAT THIS MODULE DOES. Identical shape to enrichment_granville_rollback_exposure.py: reuses
    enrichment_bt_parcel_info.py's own, already-tested `_UA`/`_best_match()`/`_view_parcel()`
    (all already generic over a `tenant_base` url) against Duplin's own ITSPublicDL tenant, with
    this module's own `_search_query()` (comma-separated, see above) standing in for the shared
    one. Same bounds (MAX_LISTINGS, a small concurrency, a hard candidate-count ceiling against a
    common-surname over-match).

RATE, NEVER ASSUMED (same convention as Granville's and Harnett's modules). The effective
    combined tax rate is DERIVED per parcel from that SAME parcel's own numbers -- never a
    hard-coded millage -- from raw['nc_its_public_tax']['bills'] (the TaxBillSearch product most
    Duplin board rows already carry, 2,902 of 3,519 measured 2026-10-21) divided by THIS fetch's
    own assessed_value, kept only when it lands inside the sane band (_RATE_MIN/_RATE_MAX). A
    parcel whose rate doesn't land in the band (or has no matching bill) still gets its real
    deferred_value, just without a derived annual/estimated-rollback figure.

GATE. Only a positive `deferred_value` off a CONFIRMED (owner name + street address) ViewParcel
    match qualifies -- build_block() never invents one.

Bounded, opt-in, free, public, no login, no CAPTCHA (same host enrichment_bt_appraisal_card.py's
14-county TENANTS family already reads, same per-row request shape). Gate off entirely with
FORECLOSURE_DUPLIN_ROLLBACK=0.
"""
from __future__ import annotations

import asyncio
import os
from typing import Any, Iterable, Optional

import httpx
import structlog

from .enrichment_bt_parcel_info import (
    _UA, _best_match, _search_owner, _view_parcel,
)
from .enrichment_rollback_deferral import _RATE_MAX, _RATE_MIN
from .models import Listing
from .name_normalize import is_entity, owner_last_first_middle

log = structlog.get_logger()

RAW_KEY = "rollback_exposure"
SOURCE_KEY = "duplin_bt_tenant"
TENANT_BASE = "https://www.bttaxpayerportal.com/ITSPublicDL"
#: NC G.S. 105-277.4(c) -- see enrichment_rollback_deferral.py's module docstring.
ROLLBACK_YEARS_NC = 4

MAX_LISTINGS = int(os.getenv("DUPLIN_ROLLBACK_MAX", "300"))
_CONCURRENCY = int(os.getenv("DUPLIN_ROLLBACK_CONCURRENCY", "3"))
#: a search whose candidate set is this large or more is too loose to trust
MAX_CANDIDATES = 20

ENABLED = os.environ.get("FORECLOSURE_DUPLIN_ROLLBACK") != "0"


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
        li.state == "NC" and (li.county or "").strip().lower() == "duplin"
        and li.owner_name and not is_entity(li.owner_name)
        and (li.street_address or "").strip()
        and not _already_done(raw)
    )


def _search_query(li: Listing) -> Optional[str]:
    """'LAST, FIRST' -- Duplin's own tenant form text: "Enter Name (Last First) separated by a
    comma. (Ex. PUBLIC, JOHN Q)". enrichment_bt_parcel_info._search_query's space-separated form
    (built for Warren, which accepts it) returned ZERO candidates for four real Duplin board
    owners live-checked 2026-10-21; the comma form returned the real match for all four
    immediately. See module docstring."""
    parts = owner_last_first_middle(li.owner_name)
    if not parts:
        return None
    last, first, _mi = parts
    return f"{last}, {first}".strip()


def rate_from_its_public_tax(raw: dict, assessed_value: Any, tax_year: Any) -> Optional[float]:
    """Pure: the matching tax year's bill.original_levy / assessed_value from this row's OWN
    already-fetched raw['nc_its_public_tax']['bills'] -- no new network call, no assumed millage.
    None when there is no bill for that year, no usable assessed_value, or the ratio falls
    outside the sane band every sibling rollback section already validates against. Identical to
    enrichment_granville_rollback_exposure.rate_from_its_public_tax (not imported from there to
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
        "county": "Duplin",
        "state": "NC",
        "source": 'bttaxpayerportal.com/ITSPublicDL BasicSearch, ViewParcel "Property Values" ("Deferred :")',
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


async def enrich_duplin_rollback_exposure(listings: Iterable[Listing]) -> dict[str, Any]:
    """Search www.bttaxpayerportal.com/ITSPublicDL by owner name (comma-separated -- see
    _search_query), confirm with street address (never one signal alone), fetch ViewParcel for
    the confirmed match, and restate its 'Deferred' Property-Values line into
    raw['rollback_exposure'] when positive. Writes raw['rollback_exposure']."""
    if not ENABLED:
        return {"skipped": "disabled (FORECLOSURE_DUPLIN_ROLLBACK=0)"}
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
    log.info("duplin_rollback.done", **stats)
    return stats
