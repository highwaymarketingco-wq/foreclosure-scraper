"""Brunswick County NC ``tax.brunsco.net/ITSNet`` BasicSearch "Deferred" field -> the shared
raw['rollback_exposure'] contract enrichment_rollback_deferral.py established and gap_matrix.py's
own checked_columns()/positive_columns() already read.

WHY THIS EXISTS (docs/gap_matrix/gap_list_2026-10-21.csv, read before writing a line here).
    rollback_exposure shows sourced-not-built for Brunswick (9,225 applicable), source "tax/
    property card: tax.brunsco.net", built=no, next_action guessing a brand-new tax-roll reader
    is needed. county_records_matrix.json has no "Brunswick" entry at all (checked: 100 NC
    counties listed, none named Brunswick) -- a documentation gap, not evidence either way.

    LIVE-VERIFIED 2026-10-21 (real search + ViewParcel fetches against the real host, read-only,
    no board touched). https://tax.brunsco.net/ redirects to https://tax.brunsco.net/ITSNet/,
    title "Basic Search", `id="ItsPublicNavbar"`, page text "Brunswick County (NC) - Basic
    Search" -- the SAME "ITS Public" / BT TaxPayer Portal vendor this project already reads for
    14 bttaxpayerportal.com-hosted counties (enrichment_bt_appraisal_card.py's TENANTS) plus
    Harnett on its own domain (enrichment_harnett_rollback_exposure.py, cama.harnett.org). A real
    search for a live board owner (CHANEY KATHERINE, 4220 FARMFIELD DR, parcel_id 219902665253 on
    the board) returned parcel 017MA061 at that exact address; ViewParcel returned the same
    fieldset shape bt_parcel_info.py already parses (Parcel Number, Account Number, Owner
    Information, Tax Codes, Property Information, Location Information, Deed Information, Local
    Zoning, Property Values, PIN, Legal Description). Four more live owners (THOMPSON CYNTHIA
    HODGES, BEACHAM ANDRE, FUTREAL DONNA, MARGALLO NENITA ETVIR) all matched their board address
    exactly and returned real "Property Values" numbers (Building/Market/Assessed in the
    thousands) -- not every tenant masks this fieldset, so the earlier single-parcel read (which
    showed "Values masked for public access") was a YEAR artifact, not a vendor-wide policy; see
    below.

    "Deferred" is the exact present-use/ag-deferral VALUE line this project's rollback family
    already keys on by NAME (enrichment_bt_parcel_info.parse_view_parcel already extracts it into
    detail['deferred_value'] for every TENANTS county since the 2026-10-20 Harnett change) -- this
    module needs no new field-parsing logic, only a Brunswick tenant_base and Brunswick-specific
    candidate selection (below). THOMPSON CYNTHIA HODGES's own parcel (2402C122, 355 CYPRESS CT
    NW) showed deferred_value 0.0 for both 2025 and 2026 -- the key existed and parsed, simply not
    a present-use parcel; this module's own live board-wide run is what will surface the nonzero
    cases, the same way Harnett's board-wide run did.

TAX-YEAR TRAP, LIVE-FOUND, NOT IN ANY SIBLING MODULE (because no sibling tenant does this).
    Brunswick's ITSNet tenant returns ALL AVAILABLE TAX YEARS (2021-2027 live-observed) as
    SEPARATE rows for the SAME owner+parcel+address on a single OwnerName search -- Warren
    (bttaxpayerportal.com/ITSPublicWN), already wired, was live-checked the same session and
    returns exactly ONE row (current year only) for the identical query shape, so this is a
    genuine Brunswick-tenant difference, not a generic vendor behavior enrichment_bt_parcel_info's
    `_best_match` (len(hits) == 1) was ever written to expect. Reusing that helper unmodified
    against Brunswick would treat a parcel's own 7 year-duplicate rows as 7 separate "candidates"
    and (correctly, by that function's own address+owner bar) return len(hits) == 7, which its
    == 1 check reads as NO confident match -- a false negative on every single real match. This
    module groups search rows by `parcel_number` instead, and the address+owner bar is applied
    per DISTINCT PARCEL, not per row (see `_best_parcel_match`).

    Live-confirmed the SAME session: ViewParcel for the newest (2027) row of a real parcel
    (THOMPSON/225PC056 and 2402C122, and CHANEY/017MA061) answers "Values masked for public
    access" in the Property Values fieldset -- 2027 is Brunswick's not-yet-published NEXT listing
    year. Every other year on the same parcel (2021-2026, live-checked back to 2021) answers with
    real numbers. So this module picks the LARGEST available tax_year that is <= the current
    calendar year for a matched parcel, never the bare max() of the returned rows -- the same
    "never guess a reval year, discover it live" discipline enrichment_bt_appraisal_card.py's own
    _YEAR_CANDIDATES probing already uses for a different field on the same vendor family.

RATE: NOT DERIVED HERE, DOCUMENTED, NOT GUESSED. Every sibling in this family that derives an
    annual_deferred_tax/estimated_rollback figure (Harnett, Hyde, Mecklenburg, Buncombe) does it
    from a SEPARATE tax-BILL source already on the row (raw['nc_its_public_tax']['bills'], etc.)
    -- no such source exists for Brunswick in this codebase (grepped scrapers/counties_nc/ and
    enrichment_*: no Brunswick-specific tax-bill/delinquent-tax reader, confirmed by board-sample
    rows whose `source` is national.courtlistener_bankruptcy / counties_nc.nc_ecourts_divorce,
    never a Brunswick tax scraper). ITSNet's own "Property Values" fieldset has no billed-dollar
    line (confirmed live, same gap the 2026-10-16 Warren investigation already found for this
    whole vendor family). So `build_block` below writes deferred_value/rollback_years/basis only
    -- no annual_deferred_tax or estimated_rollback -- exactly the documented fallback every
    sibling module already uses when its own rate source is unavailable for a given lead
    ("A parcel whose rate doesn't land in the band... still gets its real deferred_value, just
    without a derived annual/estimated-rollback figure").

MATCH METHOD: owner_name + street_address, the SAME two-signal bar enrichment_bt_parcel_info.py
    and enrichment_harnett_rollback_exposure.py already use -- never parcel_id alone (the board's
    parcel_id is a 12-digit NC PIN like "219902665253"; ITSNet's own parcel_number is a short
    county-local id like "017MA061" or "0210001610" -- confirmed live, the two never collide, so
    there is no shortcut around the owner+address search).

Free, public, no login, no CAPTCHA (same host/product family enrichment_bt_parcel_info.py's 14
TENANTS counties already read, same per-row request shape). Gate off entirely with
FORECLOSURE_BRUNSWICK_ROLLBACK=0.
"""
from __future__ import annotations

import asyncio
import os
from datetime import date
from typing import Any, Iterable, Optional

import httpx
import structlog

from .enrichment_bt_parcel_info import _UA, _search_owner, _search_query, _view_parcel
from .models import Listing
from .name_normalize import is_entity, match_owner
from .name_normalize import owner_last_first_middle  # noqa: F401 (re-export parity w/ siblings)
from .verification.core import address_relation

log = structlog.get_logger()

RAW_KEY = "rollback_exposure"
SOURCE_KEY = "brunswick_itsnet"
TENANT_BASE = "https://tax.brunsco.net/ITSNet"
#: NC G.S. 105-277.4(c) -- see enrichment_rollback_deferral.py's module docstring.
ROLLBACK_YEARS_NC = 4

MAX_LISTINGS = int(os.getenv("BRUNSWICK_ROLLBACK_MAX", "300"))
_CONCURRENCY = int(os.getenv("BRUNSWICK_ROLLBACK_CONCURRENCY", "3"))
#: too many DISTINCT parcels matching both signals is a loose/common-name search, not a real
#: candidate -- counted by parcel, never by raw row (a single real match legitimately carries
#: up to 7 year-duplicate rows on this tenant; see module docstring).
MAX_DISTINCT_PARCELS = 20

ENABLED = os.environ.get("FORECLOSURE_BRUNSWICK_ROLLBACK") != "0"


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
        li.state == "NC" and (li.county or "").strip().lower() == "brunswick"
        and li.owner_name and not is_entity(li.owner_name)
        and (li.street_address or "").strip()
        and not _already_done(raw)
    )


def _best_parcel_match(li: Listing, candidates: list[dict], *,
                        today: Optional[date] = None) -> Optional[dict]:
    """The one candidate ROW to fetch ViewParcel for, or None. Candidates are grouped by
    `parcel_number` first (this tenant returns one row per available tax year for the same real
    parcel -- see module docstring); the address+owner bar is applied per distinct parcel, not
    per row, and exactly one distinct parcel must clear it. Within that parcel's own rows, picks
    the largest tax_year that is <= today's year (never the bare max -- the newest/next-listing
    year answers "masked", live-confirmed)."""
    today = today or date.today()
    by_parcel: dict[str, list[dict]] = {}
    for cand in candidates:
        pn = cand.get("parcel_number")
        if pn:
            by_parcel.setdefault(pn, []).append(cand)
    hits: list[str] = []
    for pn, rows in by_parcel.items():
        matched_any = False
        for cand in rows:
            if address_relation(li.street_address, cand.get("property_address")) != "match":
                continue
            owner_hit = match_owner(li.owner_name, cand.get("owner_name")) or \
                match_owner(li.owner_name, cand.get("co_owner"))
            if owner_hit:
                matched_any = True
                break
        if matched_any:
            hits.append(pn)
    if len(hits) != 1:
        return None
    rows = by_parcel[hits[0]]
    usable = []
    for r in rows:
        try:
            yr = int(str(r.get("tax_year") or "")[:4])
        except (TypeError, ValueError):
            continue
        if yr <= today.year:
            usable.append((yr, r))
    if not usable:
        return None
    usable.sort(key=lambda t: t[0], reverse=True)
    return usable[0][1]


def build_block(detail: dict) -> Optional[dict]:
    """Pure: the raw['rollback_exposure'] record from one ViewParcel detail's own 'Deferred'
    Property-Values line, or None when it is blank/zero/masked -- never invented. No rate is
    derived here (see module docstring); annual_deferred_tax/estimated_rollback are simply
    absent, the documented fallback every sibling in this family already uses."""
    deferred = _positive((detail or {}).get("deferred_value"))
    if deferred is None:
        return None
    rec: dict[str, Any] = {
        "deferred_value": round(deferred, 2),
        "basis": "present_use_deferral",
        "county": "Brunswick",
        "state": "NC",
        "source": 'tax.brunsco.net/ITSNet BasicSearch, ViewParcel "Property Values" ("Deferred :")',
        "source_key": SOURCE_KEY,
        "rollback_years": ROLLBACK_YEARS_NC,
        "estimate_is_floor": True,       # statutory interest not modelled; no rate source either
        "match_method": "owner_name+street_address",
    }
    tax_year = detail.get("tax_year")
    if tax_year:
        rec["tax_year"] = tax_year
    return rec


async def enrich_brunswick_rollback_exposure(listings: Iterable[Listing]) -> dict[str, Any]:
    """Search tax.brunsco.net/ITSNet by owner name, confirm with street address per DISTINCT
    parcel (never per raw row -- this tenant duplicates rows by tax year), fetch ViewParcel for
    the confirmed match's most recent non-future year, and restate its 'Deferred' Property-Values
    line into raw['rollback_exposure'] when positive. Writes raw['rollback_exposure']."""
    if not ENABLED:
        return {"skipped": "disabled (FORECLOSURE_BRUNSWICK_ROLLBACK=0)"}
    targets = [li for li in listings if _eligible(li)]
    stats = {"eligible": len(targets), "searched": 0, "no_candidates": 0,
             "too_many_candidates": 0, "no_confident_match": 0, "matched": 0,
             "errors": 0, "deferred_found": 0}
    if not targets:
        return stats
    targets = targets[:MAX_LISTINGS]
    sem = asyncio.Semaphore(_CONCURRENCY)
    today = date.today()

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
            distinct_parcels = {c.get("parcel_number") for c in candidates if c.get("parcel_number")}
            if len(distinct_parcels) >= MAX_DISTINCT_PARCELS:
                stats["too_many_candidates"] += 1
                return
            match = _best_parcel_match(li, candidates, today=today)
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
            block = build_block(detail)
            if not block:
                return
            stats["deferred_found"] += 1
            if not isinstance(li.raw, dict):
                li.raw = {}
            li.raw[RAW_KEY] = block

        await asyncio.gather(*(one(li) for li in targets))
    log.info("brunswick_rollback.done", **stats)
    return stats
