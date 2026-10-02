"""GovDeals.com — government surplus property auctions (Maestro API).

GovDeals is a free auction platform for government surplus real property.
The site is an Angular SPA that calls a backend API at maestro.lqdt1.com.
We POST to the /search/list endpoint with the embedded API key to get
JSON results.

FIXED 2026-10-01 (national-auction-tier audit, batch 4) — TWO real bugs
found live, both of the "silent success" shape CLAUDE.md warns about:

1. THE REQUEST BODY WAS STALE AND THE API WAS SILENTLY DEGRADING. The old
   payload wrapped everything in a `{"searchModel": {...}, "businessUnit":
   "GovDeals", "businessId": "GD", "siteId": 1}` envelope with field names
   ("pageNumber"/"pageSize"/"isTimeSearch") that do not exist in the
   current production contract. Reverse-engineered the REAL request shape
   from the live Angular bundle's `GetSearchResults()` call (main.js,
   2026-10-01): it POSTs a FLAT object (page/displayRows, not
   pageNumber/pageSize; isSimpleTimeSearch, not isTimeSearch; no
   searchModel/businessUnit/siteId wrapper at all) straight to
   /search/list. The API never 4xx'd on the old stale shape -- it returned
   HTTP 200 with `isAPIFailureActive: true` and silently fell back to an
   UNFILTERED, cross-state, cross-category default result set (confirmed
   live: a `facetsFilter` of `stateDesc:NC` came back with rows in IL, AL,
   AR, IA, TN, GA, MO, OR, NV -- zero NC). The old code's own client-side
   `if state not in STATES: return None` check caught the wrong-state junk
   before it reached a Listing, so nothing bad ever published -- but it
   also meant genuine NC/SC real-property rows already on the platform
   were close to never being seen, because the state facetsFilter it sent
   plainly was not taking effect. Also: the real `stateDesc` facet value
   is the FULL state name, quoted and space-escaped --
   `{!tag=stateDesc}stateDesc:"North\\ Carolina"` -- not the 2-letter
   abbreviation the old code sent.

2. CATEGORY-KEYWORD SUBSTRING MATCHING WAS A CONFIRMED FALSE-POSITIVE
   FABRICATOR. The old `_is_real_property()` matched on bare substrings
   like "land" and "building" against categoryDescription/description
   text. GovDeals' OWN category taxonomy (pulled live from
   POST /menus/categories) nests completely unrelated MOVABLE-ASSET
   categories under names that contain those same substrings: "Nursery/
   Horticulture/**Land**scaping" (a 2022 Scag turf sprayer, $2,675),
   "Portable **Building**s and structures" (an 8x10 storage shed, a 12x20
   steel carport) -- confirmed live, these all passed the old
   `_is_real_property()` check AND carried a street address (the seller's
   depot, not a property for sale), so once bug #1 above is fixed and this
   scraper starts returning non-zero rows, it would have started minting
   fake REAL-PROPERTY-AUCTION leads out of a lawnmower and a garden shed.
   Fixed by scoping the SERVER-SIDE `categoryIds` param (confirmed live,
   it genuinely constrains results) to exactly the two taxonomy branches
   that are actual real estate: "84" (Real Estate / Land Parcels: vacant
   land, single-family residential, commercial property, real-estate
   bid & assume) and "95A" (Real Estate Tax Deed and Lien Sales:
   foreclosures, tax liquidations, tax liens). Deliberately EXCLUDED the
   sibling branches "20" (Permanent Buildings) and "980" (Portable
   Buildings and structures) -- GovDeals' own taxonomy nests those under
   the same "Real Estate, Buildings, Structures" L0 node, but they are
   relocatable STRUCTURES sold without land, not real property.

  POST https://maestro.lqdt1.com/search/list
  Headers: x-api-key, Ocp-Apim-Subscription-Key, x-api-correlation-id, ...
  Body (flat, per the live Angular bundle): {categoryIds, businessId,
    searchText, isQAL, locationId, model, makebrand, eventId,
    auctionTypeId, page, displayRows, sortField, sortOrder, sessionId,
    requestType, responseStyle, facets, facetsFilter, timeType,
    sellerTypeId, accountIds, zipcode, proximityWithinDistance,
    isSimpleTimeSearch, simpleTimeSearchType, simpleTimeWithIn,
    rangeTimeSearchType, toDate, fromDate, timeUnitValue, facetLimit,
    facetsShortened, modelYear, isVehicleSearch}

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
    "isAPIFailureActive": true,   # NOTE: true even on a correctly-scoped,
                                  # correctly-filtered response -- live-
                                  # verified this flag does NOT indicate the
                                  # request failed; the real site's own
                                  # frontend treats it as a soft/cosmetic
                                  # degraded-facets signal, not a data error.
    ...
  }

We scope to the real-estate category branches (84, 95A) in NC and SC,
paging each (category, state) combination until the server returns fewer
than PER_PAGE rows or we hit PAGES_CAP.
"""
from __future__ import annotations

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

# States we scrape (core 2-state footprint) + the full names the live
# `stateDesc` facet actually matches against (verified live 2026-10-01 --
# the 2-letter abbreviation the old code sent matched nothing).
STATES = ("NC", "SC")
_STATE_FULL = {"NC": "North Carolina", "SC": "South Carolina"}

# Real-estate taxonomy branches, pulled live from POST /menus/categories
# under the top-level "Real Estate, Buildings, Structures" node (2026-10-01):
#   84  = Real Estate / Land Parcels (vacant land res/ag, single-family
#         residential, commercial property, "Buildings", other real
#         estate, real-estate bid & assume)
#   95A = Real Estate Tax Deed and Lien Sales (foreclosures, tax
#         liquidations, tax liens)
# Deliberately EXCLUDED sibling branches under the same L0 node:
#   20  = Permanent Buildings, 980 = Portable Buildings and structures --
#   both are relocatable STRUCTURES sold without land, not real property.
REAL_ESTATE_CATEGORY_IDS = ("84", "95A")

# Hard cap on pages per (category, state) to avoid an unbounded loop.
PAGES_CAP = 10
PER_PAGE = 50

_PROP_KIND_MAP = {
    "single family": PropertyKind.SINGLE_FAMILY,
    "residential": PropertyKind.SINGLE_FAMILY,
    "condo": PropertyKind.CONDO,
    "townhouse": PropertyKind.TOWNHOUSE,
    "multi-family": PropertyKind.MULTI_FAMILY,
    "mobile": PropertyKind.MOBILE,
    "manufactured": PropertyKind.MOBILE,
    "vacant land": PropertyKind.LAND,
    "land parcels": PropertyKind.LAND,
    "agricultural": PropertyKind.LAND,
    "commercial": PropertyKind.COMMERCIAL,
    "mixed": PropertyKind.MIXED,
}


def _kind(row: dict) -> PropertyKind:
    haystack = " ".join(
        str(row.get(field) or "").lower()
        for field in ("categoryDescription", "assetShortDescription",
                      "assetLongDescription", "assetCategory")
    )
    # Land-vs-residential needs to come first: a vacant-lot listing's own
    # zoning text often says "(Residential Low Density)" or similar, which
    # would otherwise false-positive match the "residential" key below and
    # mislabel a bare 0.474-acre lot as a built single-family home. Only
    # treat it as land when no dwelling-specific word is also present.
    has_dwelling = any(w in haystack for w in (
        "home", "house", "residence", "bedroom", "bath", "dwelling", "cottage",
    ))
    if not has_dwelling and any(w in haystack for w in (
        "acre", "vacant land", "lot size", "land parcel",
    )):
        return PropertyKind.LAND
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
    """Convert one GovDeals maestro API result row (already server-side
    scoped to a real-estate categoryId) into a Listing, or None if it has
    no usable address or is in the wrong state."""
    # Address fields from maestro API
    street = (row.get("locationAddress1") or "").strip() or None
    state = (row.get("locationState") or "").strip().upper() or None
    if not state:
        full = (row.get("stateDescription") or "").strip()
        state = {v: k for k, v in _STATE_FULL.items()}.get(full)
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
            # Kept flat + in RAW_KEEP for backward compat (stable per-asset id).
            "govdeals_asset_id": aid,
            # FIXED 2026-10-01 (national-auction-tier audit, batch 4): everything
            # below used to be flat top-level raw keys (govdeals_lot_id,
            # govdeals_auction_id, current_bid, bid_count, category, seller_name,
            # start_date, end_date, is_sold, has_reserve) and NONE of them were
            # in web_artifact.RAW_KEEP except govdeals_asset_id -- _slim_raw()
            # silently dropped all of them at publish. Namespaced under one
            # "govdeals" key (now registered "*" in RAW_KEEP) so the whole
            # payload survives instead of needing 9 individual allowlist entries.
            "govdeals": {
                "lot_id": lot,
                "auction_id": row.get("auctionId"),
                "current_bid": bid,
                "bid_count": row.get("bidCount"),
                "category": row.get("categoryDescription"),
                "seller_name": row.get("displaySellerName") or row.get("companyName"),
                "start_date": start_date.isoformat() if start_date else None,
                "end_date": end_date.isoformat() if end_date else None,
                "is_sold": row.get("isSoldAuction"),
                "has_reserve": row.get("hasReservePrice"),
            },
            "images": {"real": photos} if photos else {},
        },
    )


def _build_payload(category_id: str, state_full: str, page: int) -> dict:
    """The real, flat request body the live Angular bundle's
    GetSearchResults() posts to /search/list (reverse-engineered
    2026-10-01 -- see module docstring bug #1). facetLimit/facetsShortened
    must be a real int/bool (not null) or the API 400s with a .NET model-
    binding error; every other optional field tolerates null."""
    return {
        "categoryIds": category_id,
        "businessId": "GD",
        "searchText": "",
        "isQAL": False,
        "locationId": None,
        "model": None,
        "makebrand": None,
        "eventId": None,
        "auctionTypeId": None,
        "page": page,
        "displayRows": PER_PAGE,
        "sortField": "auctionEndDate",
        "sortOrder": "asc",
        "sessionId": str(uuid.uuid4()),
        "requestType": None,
        "responseStyle": None,
        "facets": [],
        "facetsFilter": [
            '{!tag=stateDesc}stateDesc:"' + state_full.replace(" ", "\\ ") + '"'
        ],
        "timeType": None,
        "sellerTypeId": None,
        "accountIds": None,
        "zipcode": None,
        "proximityWithinDistance": None,
        "isSimpleTimeSearch": True,
        "simpleTimeSearchType": 1,
        "simpleTimeWithIn": None,
        "rangeTimeSearchType": None,
        "toDate": None,
        "fromDate": None,
        "timeUnitValue": "Atauction",
        "facetLimit": 10,
        "facetsShortened": False,
        "modelYear": None,
        "isVehicleSearch": False,
    }


async def _fetch_category_state(c, category_id: str, state: str, slug: str) -> list[Listing]:
    state_full = _STATE_FULL[state]
    out: list[Listing] = []
    seen: set[str] = set()

    for page in range(1, PAGES_CAP + 1):
        headers = {
            **HEADERS,
            "x-api-correlation-id": str(uuid.uuid4()),
            "x-page-unique-id": str(uuid.uuid4()),
        }
        payload = _build_payload(category_id, state_full, page)
        try:
            r = await c.post(API, json=payload, headers=headers, follow_redirects=True)
        except Exception as exc:
            log.warning("govdeals.fetch_failed", category=category_id, state=state,
                        page=page, error=str(exc)[:200])
            break

        if r.status_code != 200:
            log.warning("govdeals.bad_status", category=category_id, state=state,
                        page=page, code=r.status_code, body=r.text[:200])
            break

        try:
            payload_resp = r.json()
        except Exception:
            log.warning("govdeals.bad_json", category=category_id, state=state, page=page)
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
            category=category_id, state=state, page=page,
            rows=len(rows), kept=new_this_page, running=len(out),
        )

        if len(rows) < PER_PAGE or new_this_page == 0:
            break

    return out


class GovDeals(BaseScraper):
    """GovDeals.com government surplus real-property auctions.

    Queries the maestro.lqdt1.com search API, scoped SERVER-SIDE to the
    real-estate taxonomy branches (categoryIds 84 + 95A) and to NC/SC via
    the stateDesc facet, and returns Listing objects with
    listing_type=AUCTION.
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
        async with client(timeout=30.0) as c:
            for state in STATES:
                for category_id in REAL_ESTATE_CATEGORY_IDS:
                    try:
                        rows = await _fetch_category_state(c, category_id, state, self.slug)
                        out.extend(rows)
                    except Exception as exc:
                        log.warning("govdeals.combo_failed", category=category_id,
                                    state=state, error=str(exc)[:200])
        log.info("govdeals.done", total=len(out))
        return out
