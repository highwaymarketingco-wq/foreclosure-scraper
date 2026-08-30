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

import asyncio
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
# Fannie's API caps at 400 properties per request. A single NC+SC bbox returns
# ~400 but totalProperties is 26,955 nationwide. We subdivide each state into
# a grid of smaller bboxes so we stay under the 400-per-request ceiling and
# capture every listing. Grid cells are ~0.7 degrees (~50mi) which yields
# 10-80 properties per cell in NC/SC density.
BBOXES = (
    ("NC", 33.75, -84.50, 36.60, -75.30),
    ("SC", 32.00, -83.40, 35.25, -78.50),
)

# Grid subdivision: split each state bbox into NxM cells to stay under the
# 400-per-request API cap. Tuned so no cell in NC/SC exceeds ~200 results.
_GRID_ROWS = 4
_GRID_COLS = 4


def _subdivide(sw_lat: float, sw_lng: float, ne_lat: float, ne_lng: float,
               rows: int = _GRID_ROWS, cols: int = _GRID_COLS) -> list[tuple[float, float, float, float]]:
    """Split a bbox into a rows x cols grid of smaller bboxes."""
    dlat = (ne_lat - sw_lat) / rows
    dlng = (ne_lng - sw_lng) / cols
    cells: list[tuple[float, float, float, float]] = []
    for r in range(rows):
        for c in range(cols):
            cells.append((
                sw_lat + r * dlat,
                sw_lng + c * dlng,
                sw_lat + (r + 1) * dlat,
                sw_lng + (c + 1) * dlng,
            ))
    return cells


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
    img_url = p.get("primHiResImageUrl") or p.get("primaryImageUrl")
    photos = [img_url] if img_url and isinstance(img_url, str) and img_url.startswith("http") else []
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
            "images": {"real": photos} if photos else {},
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
            cells = _subdivide(sw_lat, sw_lng, ne_lat, ne_lng)
            tasks = [
                _fetch_bbox(state, c[0], c[1], c[2], c[3], self.slug)
                for c in cells
            ]
            results = await asyncio.gather(*tasks, return_exceptions=True)
            for i, result in enumerate(results):
                if isinstance(result, Exception):
                    log.warning("fannie_homepath.cell_failed", state=state,
                                cell=i, error=str(result)[:200])
                    continue
                for li in result:
                    if li.case_number and li.case_number in seen:
                        continue
                    if li.case_number:
                        seen.add(li.case_number)
                    out.append(li)
        log.info("fannie_homepath.done", total=len(out), cells=len(BBOXES) * _GRID_ROWS * _GRID_COLS)
        return out
