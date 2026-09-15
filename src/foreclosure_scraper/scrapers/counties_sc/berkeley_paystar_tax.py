"""Berkeley County SC — delinquent Real Property tax roll via the paystar.io
payment portal's own unauthenticated search API.

BACKGROUND
    Berkeley (and Jasper, and Florence) route their tax payment portal through
    a vendor called paystar.io. Found 2026-09-14 driving Berkeley's portal
    (berkeleycountysc.paystar.io) with a real browser and network capture: its
    search box calls a plain, unauthenticated JSON API. Its Terms of Use is a
    plain liability disclaimer ("no warranties... for informational use
    only"), the same shape as other disclaimer pages already treated as
    non-prohibitive in this codebase -- not a scraping-prohibition clause.

    Scoped 2026-09-14 as a "qpaybill_delinquent_roll.py-scale build" because
    the FIRST endpoint found (`/api/search/suggest?searchTerm=X`) is a
    5-result autocomplete with no bulk path -- exactly the shape that forced
    qpaybill's alphabet-prefix enumeration. Investigated further 2026-09-15
    and found the autocomplete widget is backed by a SECOND, much better
    endpoint the search RESULTS PAGE itself calls: `POST /api/search`. That
    endpoint takes an EMPTY searchTerm plus facet filters and returns the
    ENTIRE roll directly -- no name enumeration needed at all, unlike every
    other SC tax-portal source in this codebase.

VERIFIED LIVE 2026-09-15 (plain httpx, no browser, no cookies, no auth):

    POST https://berkeleycountysc.paystar.io/api/search
    {"searchTerm": "", "facetFilters": {"PaymentStatus": ["Unpaid"],
     "AssetType": ["Real Property"], "TaxYear": []}, "page": 1, "pageSize": 1000}

    -> {"data": {"results": [...], "totalCount": 3587, "facets": [...]}}

    pageSize accepts up to at least 5000 (the whole roll in ONE request,
    confirmed); paginated at 1000 here to stay well inside whatever cap the
    vendor might tighten later. Each list row carries only invoiceNumberHash/
    invoiceNumber/taxYear/invoiceeName/paymentStatus -- no address, no
    parcel, no amount -- so a SECOND, per-row request is required:

    GET https://berkeleycountysc.paystar.io/api/invoices/{invoiceNumberHash}

    This is the real find. One response carries EVERYTHING a lead needs, in
    ONE call, that no other SC tax source in this codebase gives together:
      - invoiceAmountMinor        the actual balance owed, in cents
      - assetIdentifierDisplay    the TMS parcel number
      - invoiceStreetAddress1/City/State/PostalCode   OWNER'S MAILING address
      - assetMetaJson             a stringified JSON blob holding the county's
        OWN raw record: SiteAddress/SiteCity/SiteState/SiteZip (the SITUS --
        i.e. the actual property location, distinct from the mailing address
        above), ParentTMS, DeedBook/DeedPage, TaxesDue, Millage,
        ResidentialAssessmentExemption (owner-occupancy signal), appraisal
        and assessment values, acreage.
    A mismatch between the mailing address and SiteAddress is a live,
    first-party absentee-owner signal -- computed here the same way
    enrichment_owner_mailing.py's _is_absentee() already does for every other
    SC source, reused rather than reimplemented so the two never drift.

NOT A SOLVE-ONCE-FOR-ALL-THREE, CORRECTED CLAIM
    2026-09-14's queue note scoped this as one build covering Berkeley,
    Jasper, AND Florence. That was WRONG, checked live 2026-09-15 before
    building anything on the assumption:
      - Jasper's REAL delinquent roll turned out to live on qpaybill.com, a
        completely different vendor Jasper's own site links to from a
        separate "Pay Delinquent Taxes" button -- paystar there is only the
        CURRENT-year vehicle/property portal. Added to
        counties_sc.qpaybill_delinquent_roll's QPAYBILL_SUBS instead (see
        that module); NOT built here.
      - Florence's tenant on paystar runs an OLDER, DIFFERENT API generation
        (`GET /api/business-units/florence-county-tax/invoices/
        search-configurations/{id}/search`, not the unified `POST
        /api/search` this file uses) that REJECTS an empty searchText
        (returns `data: null`) -- it needs the SAME alphabet/prefix name
        enumeration this whole paystar detour was meant to avoid, and a
        first "Real Property" + name-prefix probe returned zero live rows,
        so it is unclear real-property delinquency data is even loaded into
        that tenant. Deferred, not built.
    So this file covers ONLY Berkeley. Retracted plainly per this session's
    own standing rule on over-optimistic claims, rather than silently
    narrowing the docstring.

WHAT THIS DOES NOT DO
    Nothing here opens the cart, the payment flow, or any authenticated path
    -- read-only GETs/POSTs against the public search/detail API exactly as
    the portal's own front end calls them.

Free, no login, no WAF, no CAPTCHA, no cookies required (verified with
credentials omitted).
Slug: counties_sc.berkeley_paystar_tax
Category: county_tax
ListingType: TAX_SALE
"""
from __future__ import annotations

import asyncio
import json
from datetime import datetime
from typing import Any, Iterable

import httpx
import structlog

from ...base_scraper import BaseScraper
from ...enrichment_owner_mailing import _is_absentee
from ...models import Listing, ListingType, PropertyKind

log = structlog.get_logger()

_HOST = "https://berkeleycountysc.paystar.io"
_SEARCH_URL = f"{_HOST}/api/search"
_DETAIL_URL = f"{_HOST}/api/invoices/{{hash}}"
_UI_URL = f"{_HOST}/app/invoices/{{hash}}"

_PAGE_SIZE = 1000
_DETAIL_CONCURRENCY = 10


async def _list_all(client: httpx.AsyncClient) -> list[dict]:
    """Page the WHOLE Unpaid Real Property roll via an empty searchTerm.

    No name enumeration -- this endpoint (unlike qpaybill and Florence's
    older paystar tenant) answers an empty search directly.
    """
    out: list[dict] = []
    page = 1
    while True:
        r = await client.post(_SEARCH_URL, json={
            "searchTerm": "",
            "facetFilters": {"PaymentStatus": ["Unpaid"], "AssetType": ["Real Property"], "TaxYear": []},
            "page": page,
            "pageSize": _PAGE_SIZE,
        })
        r.raise_for_status()
        data = (r.json() or {}).get("data") or {}
        results = data.get("results") or []
        out.extend(results)
        if len(results) < _PAGE_SIZE:
            break
        page += 1
        if page > 50:   # 50,000 rows -- far above any single SC county's roll; a stall guard, not a real cap
            log.warning("berkeley_paystar.list_page_guard_hit", pages=page)
            break
    return out


async def _fetch_detail(client: httpx.AsyncClient, sem: asyncio.Semaphore, invoice_hash: str) -> dict | None:
    async with sem:
        try:
            r = await client.get(_DETAIL_URL.format(hash=invoice_hash))
            r.raise_for_status()
            return (r.json() or {}).get("data") or None
        except Exception as exc:
            log.warning("berkeley_paystar.detail_fail", invoice_hash=invoice_hash, error=str(exc)[:140])
            return None


def _meta(detail: dict) -> dict[str, Any]:
    raw = detail.get("assetMetaJson")
    if not raw:
        return {}
    try:
        return json.loads(raw)
    except Exception:
        return {}


def _full_addr(line1: str | None, city: str | None, state: str | None, zip_: str | None) -> str | None:
    line1 = (line1 or "").strip()
    city = (city or "").strip()
    state = (state or "").strip()
    zip_ = (zip_ or "").strip()
    bits = [b for b in (line1, ", ".join(b for b in (city, state) if b), zip_) if b]
    return " ".join(bits) or None


def _num(v) -> float | None:
    try:
        f = float(str(v).replace(",", ""))
        return f
    except (TypeError, ValueError):
        return None


def _detail_to_listing(detail: dict, invoice_hash: str) -> Listing | None:
    meta = _meta(detail)
    parcel = detail.get("assetIdentifierDisplay") or meta.get("Identifier") or None
    owner = detail.get("invoiceeName") or detail.get("assetOwner") or meta.get("BillName") or None
    if not (parcel or owner):
        return None

    amount_minor = detail.get("invoiceAmountMinor")
    amount = round(amount_minor / 100.0, 2) if isinstance(amount_minor, (int, float)) else _num(meta.get("TaxesDue"))
    if not amount or amount <= 0:
        return None

    situs = _full_addr(meta.get("SiteAddress"), meta.get("SiteCity"), meta.get("SiteState"), meta.get("SiteZip"))
    mailing = _full_addr(detail.get("invoiceStreetAddress1"), detail.get("invoiceCity"),
                         detail.get("invoiceState"), detail.get("invoicePostalCode"))
    mail_state = (detail.get("invoiceState") or "").strip().upper() or None

    tax_year = detail.get("taxYear")
    invoice_number = detail.get("invoiceNumber") or invoice_hash
    now = datetime.utcnow()

    raw: dict[str, Any] = {
        "berkeley_paystar_tax": {
            "invoice_number": invoice_number,
            "tax_year": tax_year,
            "total_due": amount,
            "delinquent": bool(detail.get("delinquent")),
            "deed_book": meta.get("DeedBook") or None,
            "deed_page": meta.get("DeedPage") or None,
            "parent_tms": meta.get("ParentTMS") or None,
            "acres": _num(meta.get("AcresCount")),
            "appraised_value": (_num(meta.get("QRLandValue")) or 0) + (_num(meta.get("QRBuildingValue")) or 0) or None,
            "assessed_value": _num(meta.get("TotalAssessment")),
            "millage": _num(meta.get("Millage")),
            "residential_assessment_exemption": meta.get("ResidentialAssessmentExemption") or None,
        }
    }
    if mailing:
        raw["owner_mailing"] = {
            "owner": owner,
            "mailing": mailing,
            "situs": situs,
            "parcel_id": parcel,
            "mail_state": mail_state,
            "absentee": _is_absentee(situs, mailing),
            "out_of_state": bool(mail_state and mail_state != "SC"),
            "mailing_source": "berkeley_paystar_tax",
        }

    situs_line = meta.get("SiteAddress") or None
    return Listing(
        source="counties_sc.berkeley_paystar_tax",
        source_url=_UI_URL.format(hash=invoice_hash),
        listing_type=ListingType.TAX_SALE,
        property_kind=PropertyKind.UNKNOWN,
        state="SC",
        county="Berkeley",
        parcel_id=parcel,
        street_address=situs_line,
        city=(meta.get("SiteCity") or None),
        zip_code=(meta.get("SiteZip") or None),
        case_number=str(invoice_number),
        owner_name=owner,
        defendant=owner,
        description=(f"Delinquent {tax_year} property tax of ${amount:,.2f} owed by {owner}"
                     + (f" (parcel {parcel})" if parcel else "")),
        first_seen=now,
        last_seen=now,
        raw=raw,
    )


class BerkeleyPaystarTax(BaseScraper):
    slug = "counties_sc.berkeley_paystar_tax"
    name = "Berkeley County SC Delinquent Real Property Tax (paystar.io)"
    category = "county_tax"
    timeout_s = 300.0
    expected_min_count = 500
    optional = True

    async def fetch(self) -> Iterable[Listing]:
        out: list[Listing] = []
        async with httpx.AsyncClient(timeout=30.0, follow_redirects=True) as client:
            try:
                rows = await _list_all(client)
            except Exception as exc:
                log.warning("berkeley_paystar.list_fail", error=str(exc)[:160])
                return out
            if not rows:
                return out

            sem = asyncio.Semaphore(_DETAIL_CONCURRENCY)
            details = await asyncio.gather(*(
                _fetch_detail(client, sem, r["invoiceNumberHash"])
                for r in rows if r.get("invoiceNumberHash")
            ))

        skipped = 0
        for r, detail in zip((r for r in rows if r.get("invoiceNumberHash")), details):
            if not detail:
                skipped += 1
                continue
            li = _detail_to_listing(detail, r["invoiceNumberHash"])
            if li is None:
                skipped += 1
                continue
            out.append(li)

        log.info("berkeley_paystar.done", listed=len(rows), skipped=skipped, total=len(out))
        return out
