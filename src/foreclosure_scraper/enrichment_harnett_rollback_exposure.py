"""Harnett County NC ``cama.harnett.org`` BasicSearch "Deferred" field -> the shared
raw['rollback_exposure'] contract enrichment_rollback_deferral.py established and gap_matrix.py's
own checked_columns()/positive_columns() already read.

WHY THIS EXISTS (docs/gap_matrix/gap_list_2026-10-20.csv, read before writing a line here).
    rollback_exposure shows sourced-not-built for Harnett (4,221 applicable), source "tax/property
    card: cama.harnett.org", built=no. The next_action guesses a brand-new reader is needed.

    LIVE-VERIFIED 2026-10-20 (real search + detail-page fetch against the real host, read-only,
    no board touched). cama.harnett.org/ITSPublicHT is the SAME "ITS Public" / BT TaxPayer Portal
    vendor this project already reads for Harnett's TaxBillSearch product
    (scrapers/counties_nc/nc_its_public_tax.py's PORTALS["Harnett"]), hosted on the county's own
    domain instead of the shared bttaxpayerportal.com host -- but it ALSO exposes the SAME
    "BasicSearch"/"ViewParcel" CAMA product enrichment_bt_parcel_info.py already reads for its 14
    TENANTS counties (title "Basic Search", GET /ITSPublicHT/ -> HTTP 200, 9,189 bytes; Harnett
    is simply not in that module's TENANTS dict, so nothing has ever queried it before this
    change). A real ViewParcel fetch for a live board owner (Penny Road Developers LLC, parcel
    110662 0022 37) returned a "Property Values" fieldset with SIX lines: Building, Obxf, Land,
    Market, Assessed, Deferred, Exemption(s) -- "Deferred" was never read by
    enrichment_bt_parcel_info.parse_view_parcel() before this change (it only pulled Market and
    Assessed), on ANY of its 14 counties, because nobody had looked for it: the 2026-10-16 Warren
    investigation was checking for tax-PAYMENT/delinquency data (correctly found absent from this
    product) -- present-use VALUATION is a different question nobody had asked of this field.
    "Deferred" is the exact present-use/ag-deferral VALUE line this project's rollback family
    already keys on by NAME, not an inferred gap between two generically-named columns (the NC
    PTS Cloud trap enrichment_rollback_deferral.py's own docstring warns against) -- same
    evidentiary bar Wake's "Total Deferred Value" and Transylvania's "Deferred Value :" lines
    cleared. End-to-end flow re-verified live the same session for a second, non-entity owner
    (Ashley Rubio, 641 White Birch Ln, Angier NC): 2 search candidates, address-matched to the
    right one, ViewParcel returned real deed/legal/value fields -- the owner-name+address match
    enrichment_bt_parcel_info.py already uses for its 14 counties works the same way here.

    NOT THE SAME GAP AS multi_year_delinquent_tax (reported separately, not built this session):
    that column needs >=2 matured years in raw['nc_its_public_tax']['bills'], and a live probe of
    Harnett's current (2025) TaxBillSearch year alone found 5,843 unpaid real-property bills
    (59 pages) -- every sampled board row currently carries exactly ONE bill year, meaning the
    last production scrape of this county ran capped (self.limit, back=1 year) rather than full
    (YEARS_BACK=20). That is a scraper RUN-DEPTH gap, not a code gap, and is reported/queued
    separately; nothing here depends on it.

WHAT THIS MODULE DOES. Reuses enrichment_bt_parcel_info.py's own, already-tested
    _search_owner()/_view_parcel()/_search_query()/_best_match() functions (all already generic
    over a `tenant_base` url -- never re-implemented here) against Harnett's own host instead of
    bttaxpayerportal.com, exactly the same two-step flow (search by "LAST FIRST", confirm with
    BOTH owner name AND street address, then fetch ViewParcel) and the same bounds (MAX_LISTINGS,
    a small concurrency, a hard candidate-count ceiling against a common-surname over-match).
    Harnett is not added to that module's TENANTS dict because its host is NOT
    www.bttaxpayerportal.com -- a separate, tiny module keeps the county-specific host without
    teaching the shared helpers a second base URL.

RATE, NEVER ASSUMED (same convention enrichment_rollback_deferral.py's Buncombe/Wake/Mecklenburg
    sections and enrichment_transylvania_rollback_exposure.py already use). The effective combined
    tax rate is DERIVED per parcel from that SAME parcel's own numbers -- never a hard-coded
    millage -- from data already on the row: raw['nc_its_public_tax']['bills'] (the TaxBillSearch
    product every Harnett board row already carries) gives the matching tax year's own
    original_levy; dividing it by THIS fetch's own assessed_value (the BasicSearch product's
    "Assessed" line, the SAME tax year) gives the rate, kept only when it lands inside the sane
    band (_RATE_MIN/_RATE_MAX, imported from enrichment_rollback_deferral.py rather than
    re-declared). No new network call for the rate: the bill data is already on the row. A parcel
    whose rate doesn't land in the band (or has no matching bill) still gets its real
    deferred_value, just without a derived annual/estimated-rollback figure.

GATE. Only a positive `deferred_value` off a CONFIRMED (owner name + street address) ViewParcel
    match qualifies -- build_block() never invents one, matching every sibling in this family.

Bounded, opt-in, free, public, no login, no CAPTCHA (same host enrichment_bt_appraisal_card.py's
    14-county TENANTS family already reads, same per-row request shape). Gate off entirely with
    FORECLOSURE_HARNETT_ROLLBACK=0.
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
SOURCE_KEY = "harnett_cama"
TENANT_BASE = "https://cama.harnett.org/ITSPublicHT"
#: NC G.S. 105-277.4(c) -- see enrichment_rollback_deferral.py's module docstring.
ROLLBACK_YEARS_NC = 4

MAX_LISTINGS = int(os.getenv("HARNETT_ROLLBACK_MAX", "300"))
_CONCURRENCY = int(os.getenv("HARNETT_ROLLBACK_CONCURRENCY", "3"))
#: a search whose candidate set is this large or more is too loose to trust
MAX_CANDIDATES = 20

ENABLED = os.environ.get("FORECLOSURE_HARNETT_ROLLBACK") != "0"


CHECKED_KEY = "rollback_exposure_checked"


def _already_done(raw: Any) -> bool:
    if not isinstance(raw, dict):
        return False
    return isinstance(raw.get(RAW_KEY), dict) or isinstance(raw.get(CHECKED_KEY), dict)


def _stamp_checked(li: Listing, result: str) -> None:
    # FOUND 2026-10-22 (rollback_exposure gap-list audit): a search that found no deferral
    # wrote nothing at all, so _already_done() (and therefore _eligible()) could never tell
    # "searched, no deferral" from "never searched" -- the daily MAX_LISTINGS=300 cap kept
    # re-trying the same first ~300 eligible rows every run and never reached rows 301+ of the
    # 1,619 eligible population (same bug class as jail_booking_screen, fixed 2026-10-16, for
    # the identical reason). A separate key, never RAW_KEY itself, so a negative result can
    # never be misread as a positive rollback_exposure hit.
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
        li.state == "NC" and (li.county or "").strip().lower() == "harnett"
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
        "county": "Harnett",
        "state": "NC",
        "source": 'cama.harnett.org/ITSPublicHT BasicSearch, ViewParcel "Property Values" ("Deferred :")',
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


async def enrich_harnett_rollback_exposure(listings: Iterable[Listing]) -> dict[str, Any]:
    """Search cama.harnett.org/ITSPublicHT by owner name, confirm with street address (never one
    signal alone), fetch ViewParcel for the confirmed match, and restate its 'Deferred' Property-
    Values line into raw['rollback_exposure'] when positive. Writes raw['rollback_exposure']."""
    if not ENABLED:
        return {"skipped": "disabled (FORECLOSURE_HARNETT_ROLLBACK=0)"}
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
    log.info("harnett_rollback.done", **stats)
    return stats
