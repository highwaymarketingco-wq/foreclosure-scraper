"""Fannie Mae HomePath REO — direct JSON API by bounding box.

Fannie's HomePath SPA queries an unauthenticated JSON endpoint:

  GET https://homepath.fanniemae.com/cfl/property-inventory/search
      ?bounds={lat_sw},{lng_sw},{lat_ne},{lng_ne}

Returns up to ~400 properties per request inside the bbox with:
  addressLine1, city, county, state, zipCode, bedrooms, bathrooms, sqft,
  yearBuilt, price, propertyType, reoId, mlsId, primHiResImageUrl, geoPoint,
  listingStartDate (epoch ms), retailStatus, onlineOfferOnly, ...

We query NC and SC bboxes (slightly tight to limit out-of-state spillover)
and filter results by state. Listings include TN/VA edge cases when the
bbox overlaps; the post-fetch state filter drops them.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Iterable

import structlog

from ...base_scraper import BaseScraper
from ...http_client import client
from ...models import Listing, ListingType, PropertyKind

log = structlog.get_logger()

API = "https://homepath.fanniemae.com/cfl/property-inventory/search"
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_5) AppleWebKit/605.1.15 "
        "(KHTML, like Gecko) Version/17.5 Safari/605.1.15"
    ),
    "Accept": "application/json, text/plain, */*",
    "Referer": "https://homepath.fanniemae.com/",
}

# (state, lat_sw, lng_sw, lat_ne, lng_ne) — bbox boundaries for our 2-state scope.
# Numbers picked to fully cover NC/SC with minimal overlap into neighbors;
# filtering happens by state code on each row regardless.
BBOXES = (
    ("NC", 33.75, -84.50, 36.60, -75.30),
    ("SC", 32.00, -83.40, 35.25, -78.50),
)


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


def _to_listing(p: dict, slug: str) -> Listing | None:
    state = (p.get("state") or "").strip().upper()
    if state not in ("NC", "SC"):
        return None
    addr = (p.get("addressLine1") or "").strip() or None
    if not addr:
        return None
    uuid = p.get("propertyUuid") or p.get("reoId") or p.get("mlsId")
    geo = p.get("geoPoint") or {}
    listing_ms = p.get("listingStartDate")
    first_seen = datetime.utcnow()
    if isinstance(listing_ms, (int, float)) and listing_ms > 0:
        try:
            first_seen = datetime.fromtimestamp(listing_ms / 1000, tz=timezone.utc).replace(tzinfo=None)
        except (ValueError, OSError):
            pass
    return Listing(
        source=slug,
        source_url=f"https://homepath.fanniemae.com/property/{uuid}" if uuid else "https://homepath.fanniemae.com/",
        listing_type=ListingType.REO,
        property_kind=_PROP_KIND_MAP.get((p.get("propertyType") or "").strip(), PropertyKind.UNKNOWN),
        state=state,
        county=(p.get("county") or "").replace(" COUNTY", "").title() or None,
        city=(p.get("city") or "").title() or None,
        zip_code=(p.get("zipCode") or "").strip() or None,
        street_address=addr,
        case_number=f"fannie-{uuid}" if uuid else None,
        latitude=geo.get("latitude") if isinstance(geo.get("latitude"), (int, float)) else None,
        longitude=geo.get("longitude") if isinstance(geo.get("longitude"), (int, float)) else None,
        opening_bid=p.get("price") if isinstance(p.get("price"), (int, float)) else None,
        description=(
            f"Fannie Mae HomePath REO "
            f"{p.get('propertyType') or ''} "
            f"{int(p.get('bedrooms')) if p.get('bedrooms') else ''}bd/"
            f"{int(p.get('bathrooms')) if p.get('bathrooms') else ''}ba "
            f"{int(p.get('sqft')) if p.get('sqft') else ''} sqft"
        ).strip(),
        first_seen=first_seen,
        last_seen=datetime.utcnow(),
        raw={
            "reo_id": p.get("reoId"),
            "mls_id": p.get("mlsId"),
            "year_built": p.get("yearBuilt"),
            "bedrooms": p.get("bedrooms"),
            "bathrooms": p.get("bathrooms"),
            "sqft": p.get("sqft"),
            "retail_status": p.get("retailStatus"),
            "online_offer_only": p.get("onlineOfferOnly"),
            "first_look": bool(p.get("firstLookProgramIndicator")),
        },
    )


async def _fetch_bbox(state: str, sw_lat: float, sw_lng: float, ne_lat: float, ne_lng: float, slug: str) -> list[Listing]:
    params = {"bounds": f"{sw_lat},{sw_lng},{ne_lat},{ne_lng}"}
    async with client(timeout=30.0) as c:
        try:
            r = await c.get(API, params=params, headers=HEADERS, follow_redirects=True)
        except Exception as exc:
            log.warning("fannie_homepath.fetch_failed", state=state, error=str(exc)[:200])
            return []
    if r.status_code != 200:
        log.warning("fannie_homepath.bad_status", state=state, code=r.status_code)
        return []
    try:
        payload = r.json()
    except Exception:
        return []
    props = payload.get("properties") or []
    out: list[Listing] = []
    for p in props:
        li = _to_listing(p, slug)
        if li is not None:
            out.append(li)
    log.info(
        "fannie_homepath.bbox_done", state=state,
        in_bbox=len(props), kept_in_state=len(out),
        total_nationwide=payload.get("totalProperties"),
    )
    return out


class FannieHomePath(BaseScraper):
    slug = "national.fannie_homepath"
    name = "Fannie Mae HomePath (REO, JSON API)"
    category = "national_reo"
    expected_min_count = 0
    requires_apify = False
    requires_render = False
    timeout_s = 60.0

    async def fetch(self) -> Iterable[Listing]:
        out: list[Listing] = []
        seen: set[str] = set()
        for state, sw_lat, sw_lng, ne_lat, ne_lng in BBOXES:
            try:
                rows = await _fetch_bbox(state, sw_lat, sw_lng, ne_lat, ne_lng, self.slug)
            except Exception as exc:
                log.warning("fannie_homepath.state_failed", state=state, error=str(exc)[:200])
                continue
            for li in rows:
                if li.case_number and li.case_number in seen:
                    continue
                if li.case_number:
                    seen.add(li.case_number)
                out.append(li)
        log.info("fannie_homepath.done", total=len(out))
        return out
