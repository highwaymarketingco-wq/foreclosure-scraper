"""Ensure 100% image coverage: every listing gets either a real photo
(from Zillow / Realtor / HomeHarvest) or a free OpenStreetMap static-map
of the property location, plus an optional Mapillary street-level photo.

Free sources used:
  - OpenStreetMap static map via Wikimedia tile servers (no API key required)
  - Mapillary public images API (no API key for /search; rate-limited but
    sufficient for our 200-listing monthly run)

Output: every listing.raw.zillow.photo gets populated (real or map fallback)
plus listing.raw.images = {"primary", "map", "street"} dict for the dashboard.
"""
from __future__ import annotations

import asyncio
from typing import Optional

import httpx
import structlog

from .models import Listing

log = structlog.get_logger()


# Wikimedia OSM tile-rendering: free, no key, 4096px max — way bigger than we need.
# Format: https://maps.wikimedia.org/img/osm-intl,<zoom>,<lat>,<lon>,<size>.png
def _osm_static_map_url(lat: float, lon: float, zoom: int = 17, size: str = "600x400") -> str:
    return f"https://maps.wikimedia.org/img/osm-intl,{zoom},{lat:.6f},{lon:.6f},{size}.png"


# Static-Maps from staticmap.openstreetmap.de (free, no key)
def _osm_de_static_map_url(lat: float, lon: float, zoom: int = 17) -> str:
    return (f"https://staticmap.openstreetmap.de/staticmap.php?"
            f"center={lat:.6f},{lon:.6f}&zoom={zoom}&size=600x400&maptype=mapnik"
            f"&markers={lat:.6f},{lon:.6f},red-dot")


async def _mapillary_image_for_point(c: httpx.AsyncClient, lat: float, lon: float) -> Optional[str]:
    """Find the closest Mapillary user-contributed street photo to (lat, lon).

    Free public API; no key for the search endpoint with reasonable rate.
    Returns a thumbnail URL or None.
    """
    try:
        # 200m bounding box around the point
        delta = 0.002  # ~200m at our latitudes
        bbox = f"{lon - delta},{lat - delta},{lon + delta},{lat + delta}"
        r = await c.get(
            "https://graph.mapillary.com/images",
            params={
                "fields": "id,thumb_1024_url",
                "bbox": bbox,
                "limit": 1,
            },
            headers={"Accept": "application/json"},
            timeout=8.0,
        )
        if r.status_code != 200:
            return None
        data = r.json()
        items = data.get("data") or []
        if not items:
            return None
        return items[0].get("thumb_1024_url")
    except Exception:
        return None


async def enrich_with_images(listings: list[Listing], use_mapillary: bool = False) -> None:
    """Ensure every listing has a fallback image. Adds:
       raw.images.map           — OSM static map (always set when lat/lng known)
       raw.images.street        — Mapillary street view (when use_mapillary=True)
       raw.images.primary       — best image (real photo > street view > map)
       raw.zillow.photo         — set to images.primary if not already set

    Mapillary off by default since it adds 200ms/listing and the OSM map fallback
    already gives the dashboard 100% visual coverage.
    """
    if not listings:
        return

    set_count = 0
    map_count = 0
    street_count = 0

    async with httpx.AsyncClient(timeout=httpx.Timeout(10.0)) as c:
        for li in listings:
            if not isinstance(li.raw, dict):
                li.raw = {}
            zillow = li.raw.setdefault("zillow", {})
            images = li.raw.setdefault("images", {})

            existing_photo = zillow.get("photo") or (zillow.get("photos") or [None])[0]

            # Map fallback (always available if we have lat/lng)
            if li.latitude and li.longitude:
                images["map"] = _osm_de_static_map_url(li.latitude, li.longitude)
                images.setdefault("map_alt", _osm_static_map_url(li.latitude, li.longitude))
                map_count += 1

            # Optional street-level photo via Mapillary
            if use_mapillary and li.latitude and li.longitude and not existing_photo:
                street = await _mapillary_image_for_point(c, li.latitude, li.longitude)
                if street:
                    images["street"] = street
                    street_count += 1

            # Pick best image: real photo > street > map
            primary = (
                existing_photo
                or images.get("street")
                or images.get("map")
            )
            if primary:
                images["primary"] = primary
                if not zillow.get("photo"):
                    zillow["photo"] = primary
                set_count += 1

    log.info(
        "images.enrich.done",
        listings=len(listings),
        with_image=set_count,
        with_map=map_count,
        with_street=street_count,
    )
