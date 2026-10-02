"""ServiceLink Auction (REO + foreclosure auctions) via the public JSON API.

ServiceLink Auction (servicelinkauction.com) is a major bank/REO + foreclosure
auction platform (peer of Auction.com / Hubzu / Xome). The site is an Angular
SPA (``Exos.AuctionSpa``) backed by a public, no-auth JSON API at
``ui.exostechnology.com``. The listing search endpoint the SPA itself calls is:

    GET https://ui.exostechnology.com/api/listingsvc/v1/listings?limit=100&state={ST}

(Discovered 2026-06-30 by reading the bundle: ``apiRoot``+``listingsvc``+
``apiVersion``(``/v1/``)+``listings``; the SPA's ``searchCriteriaService.search``
builds ``?limit=100`` and appends ``state=`` — ``STATE_KEY="state"``.)

Response shape (verified live 2026-06-30):
  {
    "searchResultCount": 145,
    "continuationToken": "<opaque>",   # null/"" on the last page
    "data": [ { listingId, openingBid, tpsOpenBid, foreclosureSaleDate,
                listingProgramWebsite ("Bank-Owned"|"Foreclosure Sale"|
                "Newly Foreclosed"|"Short Sale"), status, canonicalUrl,
                propertyInfo: { address, city, county, state, postalCode,
                                latitude, longitude, propertyType, bedrooms,
                                fullBathrooms, interiorSqFt, lotSize, yearBuilt,
                                occupancyStatus, websiteUrl },
                auctionRunInfo: { auctionName, auctionNumber, startDate,
                                  endDate, auctionMethod },
                listingStatus: { statusText, ... },
                foreclosureAttorneyName, foreclosureAttorneyPhone, ... } ]
  }

Pagination: ``limit`` maxes at 100 (>=150 -> HTTP 400). Pass the prior page's
``continuationToken`` back as ``&continuationToken=`` to get the next page; stop
when the token is empty. NC ~145, SC ~67 statewide; we keep only our CORE
Western-NC + Upstate-SC counties (~28 live). No auth, no cookie, no render —
100% free public data, peer of the existing hubzu.py JSON scraper.

FIXED 2026-10-01 (national-auction-tier audit, batch 4) — two real issues,
both confirmed live against the actual response, not guessed:

1. ``auction_status`` was the raw free-text ``listingStatus.statusText``
   verbatim (e.g. "Status: Cancelled", "Status: Auctioned - Sold to 3rd
   Party"). ``main.py``'s own shared terminal-status filter
   (``_active_only()``) checks ``li.auction_status.lower() in
   TERMINAL_AUCTION_STATUSES`` — an EXACT match against bare words like
   "cancelled"/"sold" — so the "Status: " prefix and free-text suffix meant
   it never matched, and a confirmed live, in-footprint row (403 W
   Rustling Leaves Ln, Spartanburg SC, status "Status: Cancelled") was
   shipping as an apparently-live lead. ``listingStatus.isAuctionClosed``
   looked like the obvious authoritative flag instead but is NOT reliable
   for this — verified live, it was ``False`` on that same cancelled
   listing. ``_normalize_status()`` now maps to the bare canonical
   vocabulary so the existing shared filter actually works for this source
   (no local drop-logic added, to keep ServiceLink and every other source
   checking the SAME list, the whole point of that shared filter existing).
2. The API response already carries real per-property ``images`` and
   ``documents`` arrays (confirmed live: an actual "Property Report" PDF,
   a purchase-and-sale agreement, a lead-paint disclosure pamphlet, a
   state-specific agent-disclosure form) right next to the fields already
   being read — neither was ever captured.
"""
from __future__ import annotations

from datetime import datetime
from typing import Iterable

import structlog
from dateutil import parser as dateparser

from ...base_scraper import BaseScraper
from ...document_links import stamp_documents
from ...http_client import client
from ...models import Listing, ListingType, PropertyKind

log = structlog.get_logger()

API = "https://ui.exostechnology.com/api/listingsvc/v1/listings"
_HEADERS = {
    "Accept": "application/json, text/plain, */*",
    "Origin": "https://www.servicelinkauction.com",
    "Referer": "https://www.servicelinkauction.com/",
}

# Core target counties (Western NC + Upstate SC). Title-case to match the API's
# propertyInfo.county values ("Cleveland", "Spartanburg", ...).
NC_CORE = {
    "Buncombe", "Henderson", "Burke", "Cleveland", "Gaston", "Madison",
    "McDowell", "Mitchell", "Polk", "Rutherford", "Transylvania",
}
SC_CORE = {
    "Spartanburg", "Anderson", "Pickens", "Oconee", "Cherokee", "Union",
    "Laurens",
}
_CORE_BY_STATE = {"NC": NC_CORE, "SC": SC_CORE}

# listingProgramWebsite -> ListingType. "Bank-Owned"/"Newly Foreclosed" are
# post-sale, bank-held inventory (REO); "Foreclosure Sale"/"Short Sale" are the
# pre/at-sale auction track.
_PROGRAM_TYPE = {
    "bank-owned": ListingType.REO,
    "newly foreclosed": ListingType.REO,
    "foreclosure sale": ListingType.AUCTION,
    "short sale": ListingType.AUCTION,
}

_MAX_PAGES = 20  # safety cap; NC+SC each resolve in 1-2 pages (<=200 rows)

# FIXED 2026-10-01 (national-auction-tier audit, batch 4): auction_status
# used to be the raw free-text `listingStatus.statusText` verbatim (e.g.
# "Status: Cancelled", "Status: Auctioned - Sold to 3rd Party"). Confirmed
# live this slips straight through main.py's own terminal-status safety net
# (`_active_only()` checks `li.auction_status.lower() in
# TERMINAL_AUCTION_STATUSES`, an EXACT match against bare words like
# "cancelled"/"sold" -- the "Status: " prefix and free-text suffix meant it
# never matched) -- confirmed a live, in-footprint row (403 W Rustling
# Leaves Ln, Spartanburg SC, status "Status: Cancelled") was shipping as an
# apparently-live lead. `listingStatus.isAuctionClosed` looked like the
# obvious authoritative flag but is NOT reliable for this (verified live:
# it was `False` on that same cancelled listing). Normalize to the bare
# canonical vocabulary from models.TERMINAL_AUCTION_STATUSES instead, so
# main.py's existing shared filter actually works for this source.
_TERMINAL_KEYWORDS = (
    ("cancel", "cancelled"),
    ("withdraw", "withdrawn"),
    ("rescind", "rescinded"),
    ("redeem", "redeemed"),
    ("sold", "sold"),
    ("auctioned", "sold"),
)


def _normalize_status(status_text: str | None, status_srp: str | None) -> str | None:
    blob = f"{status_text or ''} {status_srp or ''}".lower()
    for kw, canon in _TERMINAL_KEYWORDS:
        if kw in blob:
            return canon
    return (status_srp or status_text or "").strip() or None


def _kind(raw: str | None) -> PropertyKind:
    s = (raw or "").lower()
    if not s:
        return PropertyKind.UNKNOWN
    if "single" in s:
        return PropertyKind.SINGLE_FAMILY
    if "condo" in s:
        return PropertyKind.CONDO
    if "town" in s:
        return PropertyKind.TOWNHOUSE
    if "multi" in s or "duplex" in s or "plex" in s:
        return PropertyKind.MULTI_FAMILY
    if "mobile" in s or "manufactured" in s:
        return PropertyKind.MOBILE
    if "commercial" in s:
        return PropertyKind.COMMERCIAL
    if "land" in s or "lot" in s:
        return PropertyKind.LAND
    return PropertyKind.UNKNOWN


def _money(v) -> float | None:
    try:
        f = float(str(v).replace(",", "").replace("$", "").strip())
        return f if f > 0 else None
    except (ValueError, TypeError):
        return None


def _date(v):
    if not v:
        return None
    try:
        return dateparser.parse(str(v)).replace(tzinfo=None)
    except (ValueError, TypeError, OverflowError):
        return None


def _parse_item(item: dict, state: str) -> Listing | None:
    pi = item.get("propertyInfo") or {}
    if not isinstance(pi, dict):
        return None
    county = (pi.get("county") or "").strip().title() or None
    # Scope to CORE counties only — the API returns whole-state inventory.
    if county not in _CORE_BY_STATE.get(state, set()):
        return None

    street = (pi.get("address") or "").strip() or None
    url = (pi.get("websiteUrl") or item.get("canonicalUrl") or "").strip()
    if not street or not url:
        return None

    program = (item.get("listingProgramWebsite") or "").strip()
    ltype = _PROGRAM_TYPE.get(program.lower(), ListingType.AUCTION)

    ari = item.get("auctionRunInfo") or {}
    if not isinstance(ari, dict):
        ari = {}
    # Prefer the explicit foreclosure sale date; fall back to the auction
    # end date (when the online auction closes / the sale resolves).
    sale_date = _date(item.get("foreclosureSaleDate")) or _date(ari.get("endDate"))

    lstatus = item.get("listingStatus") or {}
    status_text = (lstatus.get("statusText") if isinstance(lstatus, dict) else None) \
        or item.get("status") or item.get("stage")
    status_srp = lstatus.get("statusTextSRP") if isinstance(lstatus, dict) else None
    auction_status = _normalize_status(status_text, status_srp)

    bid = _money(item.get("openingBid")) or _money(item.get("tpsOpenBid"))

    attorney = (item.get("foreclosureAttorneyName") or "").strip() or None

    # FIXED 2026-10-01: the API already returns real per-property photos
    # and documents (e.g. a "Property Report" PDF) right in this same
    # response -- confirmed live, neither was ever captured.
    photos = [
        (im.get("mediaUrl") or im.get("url") or "").strip()
        for im in (item.get("images") or []) if isinstance(im, dict)
    ]
    photos = [p for p in photos if p.startswith("http")]
    doc_urls = [
        (d.get("mediaUrl") or d.get("url") or "").strip()
        for d in (item.get("documents") or []) if isinstance(d, dict)
    ]
    doc_urls = [d for d in doc_urls if d.startswith("http")]

    li = Listing(
        source="national.servicelink_auction",
        source_url=url,
        listing_type=ltype,
        property_kind=_kind(pi.get("propertyType")),
        street_address=street,
        city=(pi.get("city") or "").strip() or None,
        state=(pi.get("state") or state).strip()[:2].upper(),
        county=county,
        zip_code=(str(pi.get("postalCode") or "").strip()[:5]) or None,
        latitude=pi.get("latitude") if isinstance(pi.get("latitude"), (int, float)) else None,
        longitude=pi.get("longitude") if isinstance(pi.get("longitude"), (int, float)) else None,
        sale_date=sale_date,
        opening_bid=bid,
        bedrooms=_money(pi.get("bedrooms")),
        bathrooms=_money(pi.get("fullBathrooms")),
        living_sqft=_money(pi.get("interiorSqFt")),
        lot_size_sqft=(_money(pi.get("lotSize")) * 43560) if _money(pi.get("lotSize")) else None,
        year_built=int(pi["yearBuilt"]) if str(pi.get("yearBuilt") or "").isdigit() else None,
        auction_status=auction_status[:120] if auction_status else None,
        trustee=attorney,  # foreclosure attorney/trustee handling the sale
        case_number=f"slauction-{item.get('listingId')}" if item.get("listingId") else None,
        description=(f"ServiceLink Auction — {program}" if program else "ServiceLink Auction").strip(),
        first_seen=datetime.utcnow(),
        last_seen=datetime.utcnow(),
        raw={"servicelink": {
            "listing_id": item.get("listingId"),
            "asset_number": pi.get("assetNumber"),
            "program": program,
            "auction_program": item.get("auctionProgram"),
            "status": item.get("status"),
            "stage": item.get("stage"),
            "status_text": status_text,
            "status_text_srp": status_srp,
            "occupancy": pi.get("occupancyStatus"),
            "auction_number": ari.get("auctionNumber"),
            "auction_name": ari.get("auctionName"),
            "auction_method": ari.get("auctionMethod"),
            "auction_start": ari.get("startDate"),
            "auction_end": ari.get("endDate"),
            "attorney_name": attorney,
            "attorney_phone": (item.get("foreclosureAttorneyPhone") or "").strip() or None,
            "is_cash_only": item.get("isCashOnly"),
            "is_financible": item.get("isFinancible"),
        }},
    )
    if photos:
        li.raw["images"] = {"real": photos}
    if doc_urls:
        stamp_documents(li, doc_urls)
    return li


async def _fetch_state(c, state: str) -> list[Listing]:
    out: list[Listing] = []
    seen: set[str] = set()
    token: str | None = None
    for page in range(1, _MAX_PAGES + 1):
        params = {"limit": "100", "state": state}
        if token:
            params["continuationToken"] = token
        try:
            r = await c.get(API, params=params, follow_redirects=True)
        except Exception as exc:  # noqa: BLE001
            log.warning("servicelink.fetch_failed", state=state, page=page, error=str(exc)[:160])
            break
        if r.status_code != 200:
            log.warning("servicelink.bad_status", state=state, page=page, status=r.status_code)
            break
        try:
            body = r.json()
        except (ValueError, AttributeError):
            log.warning("servicelink.json_failed", state=state, page=page)
            break
        data = body.get("data") or []
        if not isinstance(data, list):
            break
        kept = 0
        for item in data:
            try:
                li = _parse_item(item, state)
            except Exception:  # noqa: BLE001
                continue
            if not li:
                continue
            key = (li.raw.get("servicelink") or {}).get("listing_id") or li.source_url
            if key in seen:
                continue
            seen.add(key)
            out.append(li)
            kept += 1
        token = body.get("continuationToken") or None
        log.info("servicelink.page_done", state=state, page=page,
                 fetched=len(data), core_kept=kept, total=len(out),
                 result_count=body.get("searchResultCount"))
        if not token or not data:
            break
    return out


class ServiceLinkAuction(BaseScraper):
    slug = "national.servicelink_auction"
    name = "ServiceLink Auction (REO + foreclosure auctions, free JSON)"
    category = "national_auction"
    expected_min_count = 0   # core-county inventory turns over; can legit be 0
    requires_apify = False
    requires_render = False
    timeout_s = 120.0

    async def fetch(self) -> Iterable[Listing]:
        out: list[Listing] = []
        async with client(timeout=45.0, headers=_HEADERS) as c:
            for state in ("NC", "SC"):
                try:
                    rows = await _fetch_state(c, state)
                except Exception as exc:  # noqa: BLE001
                    log.warning("servicelink.state_failed", state=state, error=str(exc)[:160])
                    continue
                out.extend(rows)
                log.info("servicelink.state_done", state=state, count=len(rows))
        log.info("servicelink.done", count=len(out))
        return out
