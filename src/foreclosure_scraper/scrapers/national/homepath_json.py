"""Fannie Mae HomePath — state/zipcode JSON search API (complement to bbox).

The existing ``fannie_homepath`` scraper queries the property-inventory
endpoint by geographic bounding box. HomePath ALSO exposes a state/zipcode
search endpoint that returns richer, text-query-filtered results:

  GET https://homepath.fanniemae.com/cfl/property-inventory/search-listings
      ?state=NC&zipcode=&page=1&pageSize=100

This endpoint returns a paginated JSON response keyed on state/zip rather
than lat/lng bounds, so it catches listings that the bbox grid might miss
at the edges and provides a cross-check on the bbox results. The response
shape:

  {
    "properties": [
      { "propertyUuid", "reoId", "mlsId", "addressLine1", "city",
        "state", "zipCode", "county", "propertyType",
        "bedrooms", "bathrooms", "sqft", "yearBuilt",
        "price", "listingStartDate", "retailStatus",
        "geoPoint": {"latitude", "longitude"},
        "primHiResImageUrl", "onlineOfferOnly", "firstLookProgramIndicator"
      }, ...
    ],
    "total": N,
    "page": 1,
    "pageSize": 100
  }

We page through NC and SC, dedupe by reoId/propertyUuid, and return Listing
objects with listing_type=REO. The bbox scraper remains the primary; this
module is a complementary channel whose results merge in via the normal
dedupe path (case_number collision).
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from typing import Iterable

import structlog

from ...base_scraper import BaseScraper
from ...http_client import client
from ...models import Listing, ListingType, PropertyKind

log = structlog.get_logger()

# The state/zipcode search endpoint (distinct from the bbox endpoint used
# by fannie_homepath.py).
API = "https://homepath.fanniemae.com/cfl/property-inventory/search"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_5) AppleWebKit/605.1.15 "
        "(KHTML, like Gecko) Version/17.5 Safari/605.1.15"
    ),
    "Accept": "application/json, text/plain, */*",
    "Referer": "https://homepath.fanniemae.com/",
}

STATES = ("NC", "SC")
PAGE_SIZE = 100
# Hard cap on pages per state. HomePath nationwide has ~27k listings; NC+SC
# combined are ~500-800, so 20 pages (2000 listings) is a generous ceiling.
PAGES_CAP = 20

_PROP_KIND_MAP = {
    "Single Family": PropertyKind.SINGLE_FAMILY,
    "Condominium": PropertyKind.CONDO,
    "Condo": PropertyKind.CONDO,
    "Townhouse": PropertyKind.TOWNHOUSE,
    "Multi-Family": PropertyKind.MULTI_FAMILY,
    "Manufactured Home": PropertyKind.MOBILE,
    "Mobile Home": PropertyKind.MOBILE,
    "Land": PropertyKind.LAND,
    "Commercial": PropertyKind.COMMERCIAL,
}


def _safe_float(v):
    try:
        f = float(v)
        return f if f > 0 else None
    except (TypeError, ValueError):
        return None


def _to_listing(p: dict, slug: str) -> Listing | None:
    """Convert a HomePath search-listings API property row to a Listing."""
    state = (p.get("state") or "").strip().upper()
    if state not in STATES:
        return None

    addr = (p.get("addressLine1") or "").strip()
    if not addr:
        return None

    uuid = p.get("propertyUuid") or p.get("reoId") or p.get("mlsId")
    geo = p.get("geoPoint") or {}
    img_url = p.get("primHiResImageUrl") or p.get("primaryImageUrl")
    photos = (
        [img_url]
        if isinstance(img_url, str) and img_url.startswith("http")
        else []
    )

    listing_ms = p.get("listingStartDate")
    first_seen = datetime.utcnow()
    if isinstance(listing_ms, (int, float)) and listing_ms > 0:
        try:
            first_seen = (
                datetime.fromtimestamp(listing_ms / 1000, tz=timezone.utc)
                .replace(tzinfo=None)
            )
        except (ValueError, OSError):
            pass

    price = _safe_float(p.get("price"))
    lat = geo.get("latitude") if isinstance(geo.get("latitude"), (int, float)) else None
    lng = (
        geo.get("longitude")
        if isinstance(geo.get("longitude"), (int, float))
        else None
    )

    return Listing(
        source=slug,
        source_url=(
            f"https://homepath.fanniemae.com/property/{uuid}"
            if uuid
            else "https://homepath.fanniemae.com/"
        ),
        listing_type=ListingType.REO,
        property_kind=_PROP_KIND_MAP.get(
            (p.get("propertyType") or "").strip(), PropertyKind.UNKNOWN
        ),
        state=state,
        county=(p.get("county") or "").replace(" COUNTY", "").title() or None,
        city=(p.get("city") or "").title() or None,
        zip_code=(p.get("zipCode") or "").strip() or None,
        street_address=addr,
        case_number=f"homepath-json-{uuid}" if uuid else None,
        latitude=lat,
        longitude=lng,
        opening_bid=price,
        description=(
            f"HomePath REO {p.get('propertyType') or ''} "
            f"{int(p['bedrooms']) if p.get('bedrooms') else ''}bd/"
            f"{int(p['bathrooms']) if p.get('bathrooms') else ''}ba "
            f"{int(p['sqft']) if p.get('sqft') else ''} sqft"
        ).strip(),
        first_seen=first_seen,
        last_seen=datetime.utcnow(),
        raw={
            "reo_id": p.get("reoId"),
            "mls_id": p.get("mlsId"),
            "property_uuid": p.get("propertyUuid"),
            "year_built": p.get("yearBuilt"),
            "bedrooms": p.get("bedrooms"),
            "bathrooms": p.get("bathrooms"),
            "sqft": p.get("sqft"),
            "retail_status": p.get("retailStatus"),
            "online_offer_only": p.get("onlineOfferOnly"),
            "first_look": bool(p.get("firstLookProgramIndicator")),
            "images": {"real": photos} if photos else {},
        },
    )


async def _fetch_state(state: str, slug: str) -> list[Listing]:
    """Page through the HomePath search-listings endpoint for one state.

    Paginates with ?page=N&pageSize=100 until a page returns fewer than
    PAGE_SIZE rows (last page) or we hit PAGES_CAP. Dedupes by case_number
    (propertyUuid) within this state's results."""
    out: list[Listing] = []
    seen: set[str] = set()

    async with client(timeout=30.0) as c:
        for page in range(1, PAGES_CAP + 1):
            params = {
                "state": state,
                "zipcode": "",
                "page": str(page),
                "pageSize": str(PAGE_SIZE),
            }
            try:
                r = await c.get(
                    API, params=params, headers=HEADERS, follow_redirects=True
                )
            except Exception as exc:
                log.warning(
                    "homepath_json.fetch_failed",
                    state=state, page=page, error=str(exc)[:200],
                )
                break

            if r.status_code != 200:
                log.warning(
                    "homepath_json.bad_status",
                    state=state, page=page, code=r.status_code,
                )
                break

            try:
                payload = r.json()
            except Exception:
                log.warning("homepath_json.bad_json", state=state, page=page)
                break

            # The search-listings endpoint wraps results in 'properties'.
            # Some HomePath API variants use 'data' or 'results' — handle all.
            props = (
                payload.get("properties")
                or payload.get("data")
                or payload.get("results")
                or []
            )
            if not isinstance(props, list):
                break

            new_this_page = 0
            for p in props:
                if not isinstance(p, dict):
                    continue
                li = _to_listing(p, slug)
                if li is None:
                    continue
                key = li.case_number or li.source_url
                if key in seen:
                    continue
                seen.add(key)
                out.append(li)
                new_this_page += 1

            total = payload.get("total")
            log.info(
                "homepath_json.page_done",
                state=state, page=page,
                props=len(props), kept=new_this_page,
                total_reported=total, running=len(out),
            )

            # Stop on last page (fewer than PAGE_SIZE returned) or empty page.
            if len(props) < PAGE_SIZE or new_this_page == 0:
                break

    log.info("homepath_json.state_done", state=state, count=len(out))
    return out


class HomePathJSON(BaseScraper):
    """Fannie Mae HomePath REO via state/zipcode JSON search API.

    A complement to ``fannie_homepath`` (which uses the bbox endpoint).
    Queries the search-listings endpoint by state, paginates, and returns
    REO Listings for NC and SC.
    """

    slug = "national.homepath_json"
    name = "Fannie Mae HomePath (REO, state/zipcode JSON API)"
    category = "national_reo"
    expected_min_count = 0
    requires_apify = False
    requires_render = False
    timeout_s = 120.0

    async def fetch(self) -> Iterable[Listing]:
        # Fetch both states concurrently — each state does its own pagination
        # but the two states are independent, so we parallelize them.
        tasks = [_fetch_state(state, self.slug) for state in STATES]
        results = await asyncio.gather(*tasks, return_exceptions=True)
        out: list[Listing] = []
        for i, result in enumerate(results):
            if isinstance(result, Exception):
                log.warning(
                    "homepath_json.state_failed",
                    state=STATES[i], error=str(result)[:200],
                )
                continue
            out.extend(result)
        log.info("homepath_json.done", total=len(out))
        return out
