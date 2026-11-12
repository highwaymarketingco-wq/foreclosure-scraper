"""Johnston County NC ``www.bttaxpayerportal.com/itspublicjo`` BasicSearch "Deferred" field ->
the shared raw['rollback_exposure'] contract enrichment_rollback_deferral.py established and
gap_matrix.py's own checked_columns()/positive_columns() already read.

WHY THIS EXISTS (docs/gap_matrix/gap_list_2026-10-21.csv, read before writing a line here).
    rollback_exposure, two_year_delinquent and tax_aging_surfaced all show the identical 3,485
    est_rows_affected for Johnston NC, source "tax/property card: www.johnstonnc.gov",
    built=no -- the next_action guesses a brand-new reader is needed for each.

    THE RECORD WAS STALE. verification/verifiers/tax_lien_johnston.py's own docstring (and this
    project's own 2026-10-19/20 memory) says Johnston's old ITS Public tenant
    ("bttaxpayerportal.com/ITSPublicJO") is DEAD, replaced entirely by the new my.johnstonnc.gov
    (PayIt Gov) billing portal. LIVE-RECHECKED 2026-10-21: that is only true for BILL
    PAYMENT. The county's own tax-office page still links it:
    https://www.johnstonnc.gov/tax2/taxcards redirects (confirmed live, HTTP 200, no error) to
    https://www.bttaxpayerportal.com/itspublicjo -- a real, reachable "Basic Search" page, the
    SAME BasicSearch/ViewParcel CAMA product already read for Duplin/Granville/Harnett/Rowan/
    Brunswick. Owner-name search for "MIX PROPERTY" returned parcel 01F09039B, 234 GILBERT RD --
    the EXACT parcel/address/owner my.johnstonnc.gov's own guest bill-pay flow returned for this
    same property in the 2026-10-19 investigation (see memory: project_sumter_johnston_corrections_
    2026-10-19). Conclusion: the county runs TWO live systems side by side -- my.johnstonnc.gov
    for bill pay/account lookup (PayIt Gov, no CAMA detail), and the older ITSPublicJO tenant for
    BasicSearch/ViewParcel property-card data (market/assessed/deferred value, legal description,
    deed reference) -- NOT a dead-vs-alive situation, a split-by-FUNCTION situation. The "dead"
    classification in tax_lien_johnston.py refers only to this tenant's TAX BILL/PAYMENT product
    (plausibly retired in favor of my.johnstonnc.gov); its CAMA product is still live.

    QUERY FORMAT (live-checked 2026-10-21, same trap as Duplin). Johnston's own
    GetSearchOptionsPartial form text reads "Enter Name (Last First) separated by a comma. (Ex.
    PUBLIC, JOHN Q)" -- identical wording to Duplin's tenant. Four real Johnston board owners
    (Kimberley Anderson, Jose Manuel Munoz, Massey Benjamin D Sr, Brandie Robertson) all returned
    ZERO candidates on enrichment_bt_parcel_info._search_query()'s space-separated form; the
    comma form ("MUNOZ, JOSE" / "MASSEY, BENJAMIN" / "ROBERTSON, BRANDIE") returned real
    candidates for 3 of 4 immediately. This module ships its own comma-form `_search_query`,
    same as enrichment_duplin_rollback_exposure.py.

    ViewParcel for a confirmed match returns the same shared "Property Values" fieldset
    (enrichment_bt_parcel_info.parse_view_parcel(), unmodified -- its "Deferred" line was added
    2026-10-20 for Harnett and already generalizes here with no Johnston-specific parsing).
    Sampled parcels so far (01F09039B, 14023006, ROBERTSON's 05G03040A) all show deferred_value
    0.0 -- real zeros, not yet a genuine nonzero present-use deferral; a larger live run is
    needed before claiming this county's real yield (see this module's own dry-run driver).

NOT THE SAME GAP AS two_year_delinquent / tax_aging_surfaced (investigated and reported
    separately, nothing here depends on either): those two read from raw['tax_owed'] /
    raw['johnston_delinquent_tax_crosswalk'] (the 2026-10-20 delinquent-tax-file crosswalk,
    scrapers/counties_nc/johnston_delinquent_tax_crosswalk.py), a completely different source
    from this module's ITS Public CAMA read.

WHAT THIS MODULE DOES. Identical shape to enrichment_duplin_rollback_exposure.py: reuses
    enrichment_bt_parcel_info.py's own, already-tested `_UA`/`_best_match()`/`_search_owner()`/
    `_view_parcel()` (all already generic over a `tenant_base` url) against Johnston's own
    itspublicjo tenant, with this module's own `_search_query()` (comma-separated) standing in
    for the shared one. Same bounds (MAX_LISTINGS, a small concurrency, a hard candidate-count
    ceiling against a common-surname over-match).

RATE, NEVER ASSUMED (same convention as every sibling rollback module). The effective combined
    tax rate is DERIVED per parcel from that SAME parcel's own numbers -- never a hard-coded
    millage -- from raw['nc_its_public_tax']['bills'] when present, divided by THIS fetch's own
    assessed_value, kept only when it lands inside the sane band (_RATE_MIN/_RATE_MAX). Most
    Johnston board rows do NOT carry raw['nc_its_public_tax'] (Johnston is not one of the 11
    dedicated nc_its_public_tax.py PORTALS counties), so this will usually be None -- a parcel
    without a usable rate still gets its real deferred_value, just without a derived annual/
    estimated-rollback figure, same as every sibling.

GATE. Only a positive `deferred_value` off a CONFIRMED (owner name + street address) ViewParcel
    match qualifies -- build_block() never invents one.

Bounded, opt-in, free, public, no login, no CAPTCHA (same host enrichment_bt_appraisal_card.py's
14-county TENANTS family already reads, same per-row request shape). Gate off entirely with
FORECLOSURE_JOHNSTON_ROLLBACK=0.
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
SOURCE_KEY = "johnston_bt_tenant"
TENANT_BASE = "https://www.bttaxpayerportal.com/itspublicjo"
#: NC G.S. 105-277.4(c) -- see enrichment_rollback_deferral.py's module docstring.
ROLLBACK_YEARS_NC = 4

MAX_LISTINGS = int(os.getenv("JOHNSTON_ROLLBACK_MAX", "300"))
_CONCURRENCY = int(os.getenv("JOHNSTON_ROLLBACK_CONCURRENCY", "3"))
#: a search whose candidate set is this large or more is too loose to trust
MAX_CANDIDATES = 20

ENABLED = os.environ.get("FORECLOSURE_JOHNSTON_ROLLBACK") != "0"


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
        li.state == "NC" and (li.county or "").strip().lower() == "johnston"
        and li.owner_name and not is_entity(li.owner_name)
        and (li.street_address or "").strip()
        and not _already_done(raw)
    )


def _search_query(li: Listing) -> Optional[str]:
    """'LAST, FIRST' -- Johnston's own tenant form text: "Enter Name (Last First) separated by a
    comma. (Ex. PUBLIC, JOHN Q)", identical wording to Duplin's tenant.
    enrichment_bt_parcel_info._search_query's space-separated form (built for Warren, which
    accepts it) returned ZERO candidates for 4 real Johnston board owners live-checked
    2026-10-21; the comma form returned real candidates for 3 of 4 immediately. See module
    docstring."""
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
    enrichment_duplin_rollback_exposure.rate_from_its_public_tax (not imported from there to avoid
    a cross-county-module dependency for a four-line pure function)."""
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
        "county": "Johnston",
        "state": "NC",
        "source": 'bttaxpayerportal.com/itspublicjo BasicSearch, ViewParcel "Property Values" ("Deferred :")',
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


async def enrich_johnston_rollback_exposure(listings: Iterable[Listing]) -> dict[str, Any]:
    """Search www.bttaxpayerportal.com/itspublicjo by owner name (comma-separated -- see
    _search_query), confirm with street address (never one signal alone), fetch ViewParcel for
    the confirmed match, and restate its 'Deferred' Property-Values line into
    raw['rollback_exposure'] when positive. Writes raw['rollback_exposure']."""
    if not ENABLED:
        return {"skipped": "disabled (FORECLOSURE_JOHNSTON_ROLLBACK=0)"}
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
    log.info("johnston_rollback.done", **stats)
    return stats
