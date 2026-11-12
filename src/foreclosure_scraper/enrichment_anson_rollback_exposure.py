"""Anson County NC ``www.bttaxpayerportal.com/ITSPublicAN`` BasicSearch "Deferred" field -> the
shared raw['rollback_exposure'] contract enrichment_rollback_deferral.py established and
gap_matrix.py's own checked_columns()/positive_columns() already read.

WHY THIS EXISTS (overnight task: "Anson County NC at www.bttaxpayerportal.com -- feeds
multi_year_delinquent_tax AND rollback_exposure, 2,580 est rows affected"). CHECKED FIRST, PER
TASK BRIEF, before writing anything:

    bttaxpayerportal.com IS CONFIRMED LIVE AS A SHARED MULTI-COUNTY VENDOR -- not just
    "looks like one". It is the "ITS Public" / BT TaxPayer Portal platform this codebase
    already drives for (at least) 14 NC counties across THREE separate sub-products:
      * TaxBillSearch   (delinquent bill history)  -- scrapers/counties_nc/nc_its_public_tax.py
      * AppraisalCard   (PRC PDF: sqft/beds/sale)   -- enrichment_bt_appraisal_card.py
      * BasicSearch/ViewParcel (CAMA: legal/deed/Property Values incl. "Deferred") --
        enrichment_bt_parcel_info.py
    Every one of those three ALREADY lists Anson as a verified tenant: TENANTS["Anson"]="AN"
    (enrichment_bt_appraisal_card.py), PORTALS["Anson"] (nc_its_public_tax.py, full_model=True,
    its own parse_description_cols() even carries an Anson-specific comment: "Anson prints
    '<parcel><br/><br/>[<situs>]' with no acreage on some real bills"), and _TENANTS_CI (via
    import) in enrichment_bt_parcel_info.py.

    multi_year_delinquent_tax IS THEREFORE ALREADY BUILT for Anson, by two existing files this
    task's instructions forbid editing or duplicating: nc_its_public_tax.PORTALS["Anson"] (the
    live TaxBillSearch reader) + enrichment_its_public_multiyear_tax.py (the pure, no-network
    restatement into the canonical raw['multi_year_delinquent_tax'] key, explicitly "not county-
    restricted" and naming Anson by name in its own docstring's "12 PORTALS counties" list). The
    2026-11-04 gap_matrix snapshot still shows this cell "sourced-not-built"/ran=False -- that is
    a scheduling/run-depth gap (the scraper has not yet completed a full pass that reaches
    Anson's position in PORTALS, the same round-robin-starvation shape its own docstring already
    documents for Scotland/Yadkin), not a missing-code gap. No new file is written for this half;
    see the task report for the full finding. rollback_exposure is the genuinely open half, and
    is what this module builds.

    LIVE-VERIFIED 2026-11-05 (real search + ViewParcel fetches against the real host, read-only,
    no board touched, using real board owners pulled read-only from docs/listings_part_*.json.gz).
    GET https://www.bttaxpayerportal.com/ITSPublicAN/ -> 200, title "Basic Search". Four real
    board owners (Jones Eugene Glenn, Whitlock Steven Dale & wife, Isenberg Warren D Jr & wife,
    Black Carol Benton) were searched both ways to settle the query-format question rather than
    assume either default: Anson's own GetSearchOptionsPartial prints the SAME template text
    every tenant on this vendor shares ("Enter Name (Last First) separated by a comma. (Ex.
    PUBLIC, JOHN Q)"), but the comma form ("JONES, EUGENE") returned ZERO rows for all four real
    owners while the plain SPACE form ("JONES EUGENE") returned real candidates for all four (4,
    13, 3 and 11 rows respectively) -- the OPPOSITE per-tenant trap from Duplin (whose comma form
    was the one that worked) and proof the help text is not evidence either way on this vendor
    family; this module reuses enrichment_bt_parcel_info.py's own `_search_query` UNCHANGED
    (space form), like Harnett/Johnston, NOT a county-specific override like Duplin's.

    ViewParcel for four confirmed matches, via the EXACT shared parser
    (enrichment_bt_parcel_info.parse_view_parcel(), unmodified, no Anson-specific parsing needed)
    returned real, genuinely mixed values -- not just real zeros, and not every row drowned by a
    search over-match either:
      Jones Eugene Glenn    parcel 642800318784 (60.5 AC, Cappadocia Church Rd): market $198,000
                             / assessed $34,100 / DEFERRED $163,900 (present-use land, 82.8% of
                             market value untaxed -- a large real rollback exposure)
      Black Carol Benton    parcel 646800368225 (11.13 AC, Martin Rd): market $40,300 / assessed
                             $20,800 / DEFERRED $19,500
      Whitlock Steven Dale  parcel 740415541491 (0.49 AC town lot): deferred $0.0 (genuinely no
                             deferral -- a small in-town lot, as expected)
      Isenberg Warren D Jr  parcel 646200372896 (6.07 AC w/ a house): deferred $0.0
    Anson's board parcel_id (12-digit numeric NC PIN, e.g. "642800318784") is IDENTICAL to this
    portal's own parcel number for the same property (confirmed on the Jones match above) -- no
    normalization needed on that axis; the open question this module's own match bar (owner name
    AND street address, never one alone) resolves is which of several same-surname search
    candidates is the board's actual parcel, same as every sibling county.

    NOT THE SAME GAP AS multi_year_delinquent_tax (see above -- already built elsewhere, nothing
    here depends on it except, optionally, its OWN already-collected bill data for a same-parcel
    tax-rate derivation, same as every sibling module below).

WHAT THIS MODULE DOES. Reuses enrichment_bt_parcel_info.py's own, already-tested
    _search_owner()/_search_query()/_view_parcel()/_best_match() functions (generic over a
    `tenant_base` url; Anson is already one of that module's own TENANTS counties, so this file
    adds NOTHING to the search/parse layer -- only the rollback-specific gate, block shape and
    its own opt-in run loop, matching enrichment_harnett_rollback_exposure.py's structure exactly
    (same two-step flow: search by "LAST FIRST", confirm with BOTH owner name AND street address,
    then fetch ViewParcel) and the same bounds (MAX_LISTINGS, a small concurrency, a hard
    candidate-count ceiling against a common-surname over-match).

RATE, NEVER ASSUMED (same convention every sibling in this family uses -- Buncombe/Wake/
    Mecklenburg in enrichment_rollback_deferral.py, Harnett/Duplin/Johnston/Granville
    standalone). The effective combined tax rate is DERIVED per parcel from that SAME parcel's
    own numbers -- never a hard-coded millage -- from data already on the row, when present:
    raw['nc_its_public_tax']['bills'] (written by the ALREADY-BUILT nc_its_public_tax scraper
    for Anson, see above) gives the matching tax year's own original_levy; dividing it by THIS
    fetch's own assessed_value (the BasicSearch product's "Assessed" line, the SAME tax year)
    gives the rate, kept only when it lands inside the sane band (_RATE_MIN/_RATE_MAX, imported
    from enrichment_rollback_deferral.py rather than re-declared). No new network call for the
    rate. `rate_from_its_public_tax` is reimplemented here verbatim rather than imported from
    enrichment_harnett_rollback_exposure / enrichment_duplin_rollback_exposure / enrichment_
    johnston_rollback_exposure (all three carry their own identical copy, deliberately, per their
    own docstrings -- "not imported from there to avoid" a fragile cross-county import chain
    between standalone, independently-gated modules). A parcel whose rate doesn't land in the
    band (or has no matching bill, e.g. because the multi-year scraper hasn't reached Anson yet)
    still gets its real deferred_value, just without a derived annual/estimated-rollback figure.

GATE. Only a positive `deferred_value` off a CONFIRMED (owner name + street address) ViewParcel
    match qualifies -- build_block() never invents one, matching every sibling in this family.

NEGATIVE-RESULT MARKER (same fix enrichment_harnett_rollback_exposure.py already carries,
    2026-10-22 gap-list audit): a search that found no deferral, no candidates, too many
    candidates, or no confident match still stamps raw['rollback_exposure_checked'] (never
    RAW_KEY itself, so a negative result can never be misread as a positive hit) so a capped
    daily run advances through the eligible population instead of re-trying the same first
    MAX_LISTINGS rows forever.

Bounded, opt-in, free, public, no login, no CAPTCHA (same host enrichment_bt_appraisal_card.py's
    14-county TENANTS family already reads, same per-row request shape). Gate off entirely with
    FORECLOSURE_ANSON_ROLLBACK=0.
"""
from __future__ import annotations

import asyncio
import os
from datetime import date
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
SOURCE_KEY = "anson_bt_tenant"
TENANT_BASE = "https://www.bttaxpayerportal.com/ITSPublicAN"
#: NC G.S. 105-277.4(c) -- see enrichment_rollback_deferral.py's module docstring.
ROLLBACK_YEARS_NC = 4

MAX_LISTINGS = int(os.getenv("ANSON_ROLLBACK_MAX", "300"))
_CONCURRENCY = int(os.getenv("ANSON_ROLLBACK_CONCURRENCY", "3"))
#: a search whose candidate set is this large or more is too loose to trust
MAX_CANDIDATES = 20

ENABLED = os.environ.get("FORECLOSURE_ANSON_ROLLBACK") != "0"

CHECKED_KEY = "rollback_exposure_checked"


def _already_done(raw: Any) -> bool:
    if not isinstance(raw, dict):
        return False
    return isinstance(raw.get(RAW_KEY), dict) or isinstance(raw.get(CHECKED_KEY), dict)


def _stamp_checked(li: Listing, result: str) -> None:
    # Same bug/fix enrichment_harnett_rollback_exposure.py documents: a search that found no
    # deferral must leave ITS OWN marker, never RAW_KEY, so a capped daily run advances through
    # the eligible population on later runs instead of re-trying the same first MAX_LISTINGS rows.
    if not isinstance(li.raw, dict):
        li.raw = {}
    li.raw[CHECKED_KEY] = {"result": result, "checked_at": date.today().isoformat()}


def _positive(v: Any) -> Optional[float]:
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return f if f > 0 else None


def _eligible(li: Listing) -> bool:
    raw = li.raw if isinstance(li.raw, dict) else {}
    return bool(
        li.state == "NC" and (li.county or "").strip().lower() == "anson"
        and li.owner_name and not is_entity(li.owner_name)
        and (li.street_address or "").strip()
        and not _already_done(raw)
    )


def rate_from_its_public_tax(raw: dict, assessed_value: Any, tax_year: Any) -> Optional[float]:
    """Pure: the matching tax year's bill.original_levy / assessed_value from this row's OWN
    already-fetched raw['nc_its_public_tax']['bills'] -- no new network call, no assumed millage.
    None when there is no bill for that year, no usable assessed_value, or the ratio falls
    outside the sane band every sibling rollback section already validates against."""
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
        "county": "Anson",
        "state": "NC",
        "source": 'www.bttaxpayerportal.com/ITSPublicAN BasicSearch, ViewParcel "Property Values" ("Deferred :")',
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


async def enrich_anson_rollback_exposure(listings: Iterable[Listing]) -> dict[str, Any]:
    """Search www.bttaxpayerportal.com/ITSPublicAN by owner name, confirm with street address
    (never one signal alone), fetch ViewParcel for the confirmed match, and restate its
    'Deferred' Property-Values line into raw['rollback_exposure'] when positive."""
    if not ENABLED:
        return {"skipped": "disabled (FORECLOSURE_ANSON_ROLLBACK=0)"}
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
                _stamp_checked(li, "no_candidates")
                return
            if len(candidates) >= MAX_CANDIDATES:
                stats["too_many_candidates"] += 1
                _stamp_checked(li, "too_many_candidates")
                return
            match = _best_match(li, candidates)
            if not match or not match.get("tax_year"):
                stats["no_confident_match"] += 1
                _stamp_checked(li, "no_confident_match")
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
                _stamp_checked(li, "no_deferral")
                return
            stats["deferred_found"] += 1
            if not isinstance(li.raw, dict):
                li.raw = {}
            li.raw[RAW_KEY] = block

        await asyncio.gather(*(one(li) for li in targets))
    log.info("anson_rollback.done", **stats)
    return stats
