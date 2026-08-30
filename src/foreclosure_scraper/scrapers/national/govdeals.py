"""GovDeals.com — government surplus property auctions (Maestro API).

GovDeals is a free auction platform for government surplus real property.
The site is an Angular SPA that calls a backend API at maestro.lqdt1.com.
We POST to the /search/list endpoint with the embedded API key to get
JSON results filtered by state:

  POST https://maestro.lqdt1.com/search/list
  Headers: x-api-key, Ocp-Apim-Subscription-Key, x-api-correlation-id, ...
  Body: {"searchModel": {...}, "businessUnit": "GovDeals", "businessId": "GD", "siteId": 1}

Response shape (verified field names from the maestro API):
  {
    "assetSearchResults": [
      {
        "assetId", "inventoryId", "auctionId",
        "assetShortDescription", "assetLongDescription",
        "categoryDescription", "assetCategory",
        "makebrand", "model", "modelYear",
        "locationCity", "locationState", "locationZip",
        "locationAddress1", "locationAddress2",
        "country", "countryDescription", "stateDescription",
        "latitude", "longitude",
        "assetAuctionStartDate", "assetAuctionEndDate",
        "assetAuctionStartDateDisplay", "assetAuctionEndDateDisplay",
        "currentBid", "bidCount", "assetBidPrice",
        "displaySellerName", "companyName",
        "clickUrl", "photo", "lotNumber",
        "isSoldAuction", "hasReservePrice", ...
      }, ...
    ],
    "isAPIFailureActive": false,
    ...
  }

We filter for real-property / land categories in NC and SC, paging until
the server returns fewer than PER_PAGE rows or we hit PAGES_CAP.
"""
from __future__ import annotations

import re
import uuid
from datetime import datetime
from typing import Iterable

import structlog

from ...base_scraper import BaseScraper
from ...http_client import client
from ...models import Listing, ListingType, PropertyKind

log = structlog.get_logger()

# Maestro API (extracted from GovDeals Angular SPA main.js bundle)
API = "https://maestro.lqdt1.com/search/list"
API_KEY = "af93060f-337e-428c-87b8-c74b5837d6cd"
SUB_KEY = "cf620d1d8f904b5797507dc5fd1fdb80"
DETAIL_BASE = "https://www.govdeals.com/index.cfm?fa=Main&searchText=&category=&keyword="
ASSET_URL = "https://www.govdeals.com/auctions/item/detail/"

HEADERS = {
    "x-api-key": API_KEY,
    "Ocp-Apim-Subscription-Key": SUB_KEY,
    "x-user-id": "-1",
    "x-user-timezone": "300",
    "Content-Type": "application/json",
    "Accept": "application/json, text/plain, */*",
    "Origin": "https://www.govdeals.com",
    "Referer": "https://www.govdeals.com/",
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/127.0.0.0 Safari/537.36"
    ),
}

# States we scrape (core 2-state footprint).
STATES = ("NC", "SC")

# GovDeals categories that indicate real property / land rather than
# movable equipment or vehicles. GovDeals uses free-text categories so we
# match case-insensitively on a set of substrings.
_REAL_PROPERTY_KEYWORDS = (
    "real estate",
    "real property",
    "land",
    "parcel",
    "building",
    "residential",
    "commercial property",
    "house",
    "home",
    "farm",
    "acreage",
    "vacant land",
    "improved land",
    "condo",
    "townhouse",
    "duplex",
    "apartment",
)

# Hard cap on pages per state to avoid an unbounded loop.
PAGES_CAP = 20
PER_PAGE = 50

_PROP_KIND_MAP = {
    "single family": PropertyKind.SINGLE_FAMILY,
    "condo": PropertyKind.CONDO,
    "townhouse": PropertyKind.TOWNHOUSE,
    "multi-family": PropertyKind.MULTI_FAMILY,
    "mobile": PropertyKind.MOBILE,
    "manufactured": PropertyKind.MOBILE,
    "land": PropertyKind.LAND,
    "commercial": PropertyKind.COMMERCIAL,
    "mixed": PropertyKind.MIXED,
}


def _is_real_property(row: dict) -> bool:
    """A row is real-property if its category, title, or description mentions
    one of the real-property keywords. This is the post-fetch filter that
    separates houses/land from desks/trucks/surplus equipment."""
    haystack = " ".join(
        str(row.get(field) or "").lower()
        for field in ("categoryDescription", "assetShortDescription",
                      "assetLongDescription", "assetCategory",
                      "commDesc", "keywords")
    )
    return any(kw in haystack for kw in _REAL_PROPERTY_KEYWORDS)


def _kind(row: dict) -> PropertyKind:
    haystack = " ".join(
        str(row.get(field) or "").lower()
        for field in ("categoryDescription", "assetShortDescription",
                      "assetLongDescription", "assetCategory", "commDesc")
    )
    for key, kind in _PROP_KIND_MAP.items():
        if key in haystack:
            return kind
    return PropertyKind.UNKNOWN


def _parse_date(raw):
    """Parse an ISO-ish date string from the API into a datetime, or None."""
    if not raw or not isinstance(raw, str):
        return None
    s = raw.strip()
    for fmt in (
        "%Y-%m-%dT%H:%M:%S%z",
        "%Y-%m-%dT%H:%M:%SZ",
        "%Y-%m-%dT%H:%M:%S",
        "%Y-%m-%d %H:%M:%S",
        "%Y-%m-%d",
        "%m/%d/%Y",
    ):
        try:
            dt = datetime.strptime(s, fmt)
            if dt.tzinfo is not None:
                dt = dt.replace(tzinfo=None)
            return dt
        except ValueError:
            continue
    if "." in s:
        base = s.split(".", 1)[0]
        for fmt in ("%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M:%S"):
            try:
                return datetime.strptime(base, fmt)
            except ValueError:
                continue
    return None


def _safe_float(v):
    try:
        f = float(v)
        return f if f > 0 else None
    except (TypeError, ValueError):
        return None


def _auction_url(row: dict) -> str:
    """Build a human-reachable detail URL for a GovDeals auction."""
    direct = row.get("clickUrl")
    if isinstance(direct, str) and direct.startswith("http"):
        return direct
    aid = row.get("assetId") or row.get("inventoryId")
    if aid:
        return f"{ASSET_URL}{aid}"
    return "https://www.govdeals.com/"


def _to_listing(row: dict, slug: str) -> Listing | None:
    """Convert one GovDeals maestro API result row into a Listing, or None
    if it's not a real-property row or has no usable address."""
    if not _is_real_property(row):
        return None

    # Address fields from maestro API
    street = (row.get("locationAddress1") or "").strip() or None
    state = (row.get("locationState") or row.get("stateDescription") or "").strip().upper() or None
    if state and state not in STATES:
        return None
    city = (row.get("locationCity") or "").strip().title() or None
    zip_code = (row.get("locationZip") or "").strip()[:5] or None

    # Bid / price
    bid = _safe_float(
        row.get("currentBid")
        or row.get("assetBidPrice")
        or row.get("assetStrikePrice")
    )

    # Dates
    end_date = _parse_date(
        row.get("assetAuctionEndDate") or row.get("assetAuctionEndDateDisplay")
    )
    start_date = _parse_date(
        row.get("assetAuctionStartDate") or row.get("assetAuctionStartDateDisplay")
    )

    # Geo
    lat = _safe_float(row.get("latitude"))
    lng = _safe_float(row.get("longitude"))

    # Image
    img = row.get("photo")
    photos = []
    if isinstance(img, str) and img:
        if not img.startswith("http"):
            img = f"https://webassets.lqdt1.com/ecomm/{img}"
        photos.append(img)

    # Stable identifier for dedupe
    aid = row.get("assetId") or row.get("inventoryId")
    lot = row.get("lotNumber")
    case_no = None
    if aid:
        case_no = f"govdeals-{aid}" + (f"-{lot}" if lot else "")

    title = (row.get("assetShortDescription") or "").strip()
    description = (row.get("assetLongDescription") or "").strip()
    desc_bits = ["GovDeals surplus auction"]
    if title:
        desc_bits.append(title)
    if row.get("categoryDescription"):
        desc_bits.append(f"Category: {row['categoryDescription']}")
    if row.get("bidCount") is not None:
        desc_bits.append(f"{row['bidCount']} bids")
    if description:
        desc_bits.append(description[:300])
    full_desc = " | ".join(desc_bits)

    return Listing(
        source=slug,
        source_url=_auction_url(row),
        listing_type=ListingType.AUCTION,
        property_kind=_kind(row),
        state=state,
        city=city,
        zip_code=zip_code,
        street_address=street,
        case_number=case_no,
        latitude=lat,
        longitude=lng,
        opening_bid=bid,
        sale_date=end_date,
        auction_status="active",
        description=full_desc,
        first_seen=start_date or datetime.utcnow(),
        last_seen=datetime.utcnow(),
        raw={
            "govdeals_asset_id": aid,
            "govdeals_lot_id": lot,
            "govdeals_auction_id": row.get("auctionId"),
            "current_bid": bid,
            "bid_count": row.get("bidCount"),
            "category": row.get("categoryDescription"),
            "seller_name": row.get("displaySellerName") or row.get("companyName"),
            "start_date": start_date.isoformat() if start_date else None,
            "end_date": end_date.isoformat() if end_date else None,
            "is_sold": row.get("isSoldAuction"),
            "has_reserve": row.get("hasReservePrice"),
            "images": {"real": photos} if photos else {},
        },
    )


async def _fetch_state(state: str, slug: str) -> list[Listing]:
    """Page through the GovDeals maestro search API for one state.

    The API returns JSON with an 'assetSearchResults' array. We page
    until we get fewer than PER_PAGE rows (last page) or hit PAGES_CAP."""
    out: list[Listing] = []
    seen: set[str] = set()

    async with client(timeout=30.0) as c:
        for page in range(1, PAGES_CAP + 1):
            # Each request needs unique correlation/page IDs
            headers = {
                **HEADERS,
                "x-api-correlation-id": str(uuid.uuid4()),
                "x-page-unique-id": str(uuid.uuid4()),
            }
            payload = {
                "searchModel": {
                    "searchText": "",
                    "pageNumber": page,
                    "pageSize": PER_PAGE,
                    "facetsFilter": [f"{{!tag=stateDesc}}stateDesc:{state}"],
                    "isTimeSearch": True,
                    "simpleTimeSearchType": 1,
                    "timeUnitValue": "Atauction",
                    "sortBy": "auctionEndDate",
                    "sortOrder": "asc",
                },
                "businessUnit": "GovDeals",
                "businessId": "GD",
                "siteId": 1,
            }
            try:
                r = await c.post(
                    API, json=payload, headers=headers, follow_redirects=True
                )
            except Exception as exc:
                log.warning(
                    "govdeals.fetch_failed",
                    state=state, page=page, error=str(exc)[:200],
                )
                break

            if r.status_code != 200:
                log.warning(
                    "govdeals.bad_status",
                    state=state, page=page, code=r.status_code,
                )
                break

            try:
                payload_resp = r.json()
            except Exception:
                log.warning("govdeals.bad_json", state=state, page=page)
                break

            rows = payload_resp.get("assetSearchResults") or []
            if not isinstance(rows, list):
                break

            new_this_page = 0
            for row in rows:
                if not isinstance(row, dict):
                    continue
                li = _to_listing(row, slug)
                if li is None:
                    continue
                key = li.case_number or li.source_url
                if key in seen:
                    continue
                seen.add(key)
                out.append(li)
                new_this_page += 1

            log.info(
                "govdeals.page_done",
                state=state, page=page,
                rows=len(rows), kept=new_this_page,
                running=len(out),
            )

            # Stop on last page (fewer than PER_PAGE returned) or empty page.
            if len(rows) < PER_PAGE or new_this_page == 0:
                break

    log.info("govdeals.state_done", state=state, count=len(out))
    return out


class GovDeals(BaseScraper):
    """GovDeals.com government surplus real-property auctions.

    Queries the maestro.lqdt1.com search API for NC and SC, filters for
    real-property rows (houses, land, buildings), and returns Listing objects
    with listing_type=AUCTION.
    """

    slug = "national.govdeals"
    name = "GovDeals.com Surplus Property Auctions"
    category = "national_aggregator"
    expected_min_count = 0
    requires_apify = False
    requires_render = False
    timeout_s = 120.0

    async def fetch(self) -> Iterable[Listing]:
        out: list[Listing] = []
        for state in STATES:
            try:
                out.extend(await _fetch_state(state, self.slug))
            except Exception as exc:
                log.warning(
                    "govdeals.state_failed",
                    state=state, error=str(exc)[:200],
                )
        log.info("govdeals.done", total=len(out))
        return out
