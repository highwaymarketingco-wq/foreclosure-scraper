"""Multi-source image stack so every listing has Vision-usable imagery.

For every geocoded listing we attach:
  raw.images.real      — list of real listing photos (HomeHarvest, Realtor)
  raw.images.aerial    — Esri World Imagery aerial (free, no key)
  raw.images.street    — Mapillary user-contributed street-level (free)
  raw.images.map       — OSM static-map fallback
  raw.images.primary   — best image (real > street > aerial > map)
  raw.zillow.photo     — alias of primary so dashboard frontend reads it

Goal: 100% have aerial + map (always works with lat/lng), ~30-50% pick up
street-level via Mapillary, ~30% have real listing photos. Stack feeds
Claude Vision condition assessment with 1-3 images per listing.
"""
from __future__ import annotations

import asyncio
import math
from typing import Optional

import httpx
import structlog

from .models import Listing

log = structlog.get_logger()


# ---- Aerial (Esri World Imagery — free, no key) ----------------------------

def _aerial_url_for_point(lat: float, lon: float, zoom: int = 19) -> str:
    """Esri World Imagery tile URL — high-res aerial, public, no key."""
    # Convert lat/lon to slippy-map tile XY
    n = 2 ** zoom
    x = int((lon + 180) / 360 * n)
    y = int((1 - math.log(math.tan(math.radians(lat)) + 1 / math.cos(math.radians(lat))) / math.pi) / 2 * n)
    return f"https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{zoom}/{y}/{x}"


def _osm_static_map_url(lat: float, lon: float, zoom: int = 17) -> str:
    return (f"https://staticmap.openstreetmap.de/staticmap.php?"
            f"center={lat:.6f},{lon:.6f}&zoom={zoom}&size=600x400&maptype=mapnik"
            f"&markers={lat:.6f},{lon:.6f},red-dot")


# ---- Mapillary street-level (free public API, no key for /search) ----------

async def _mapillary_image(c: httpx.AsyncClient, lat: float, lon: float) -> Optional[str]:
    """Find closest Mapillary user-contributed street photo to (lat, lon).
    Returns thumbnail URL or None.
    """
    try:
        delta = 0.002  # ~200m
        bbox = f"{lon - delta},{lat - delta},{lon + delta},{lat + delta}"
        r = await c.get(
            "https://graph.mapillary.com/images",
            params={"fields": "thumb_1024_url", "bbox": bbox, "limit": 1},
            timeout=8.0,
        )
        if r.status_code != 200:
            return None
        items = (r.json().get("data") or [])
        if items:
            return items[0].get("thumb_1024_url")
    except Exception:
        return None
    return None


# ---- Main enrichment -------------------------------------------------------

async def enrich_with_images(listings: list[Listing], use_mapillary: bool = True) -> None:
    """Attach a layered image stack to every listing. Goal: 100% Vision-usable
    imagery for downstream condition assessment.
    """
    if not listings:
        return

    real_count = aerial_count = street_count = 0

    sem = asyncio.Semaphore(8)

    async with httpx.AsyncClient(timeout=httpx.Timeout(10.0)) as c:

        async def attach(li: Listing) -> None:
            nonlocal real_count, aerial_count, street_count
            if not isinstance(li.raw, dict):
                li.raw = {}
            zillow = li.raw.setdefault("zillow", {})
            images = li.raw.setdefault("images", {})

            # Real listing photos (HomeHarvest sets these)
            existing_photos = []
            if zillow.get("photos"):
                existing_photos = [p for p in zillow["photos"] if p]
            elif zillow.get("photo"):
                existing_photos = [zillow["photo"]]
            if existing_photos:
                images["real"] = existing_photos
                real_count += 1

            # Aerial + map fallbacks (always work if lat/lng known) — but
            # ONLY when we have a real street_address. Without an address,
            # lat/lng is typically a county-centroid fallback, which would
            # cause many unrelated listings to share the same aerial tile
            # (same coords → same tile URL → same image cross-applied).
            if li.latitude and li.longitude and li.street_address:
                images["aerial"] = _aerial_url_for_point(li.latitude, li.longitude)
                images["map"] = _osm_static_map_url(li.latitude, li.longitude)
                aerial_count += 1

                if use_mapillary:
                    async with sem:
                        street = await _mapillary_image(c, li.latitude, li.longitude)
                    if street:
                        images["street"] = street
                        street_count += 1

            # Pick best primary: real photo first, then street, then aerial, then map
            primary = (
                (existing_photos[0] if existing_photos else None)
                or images.get("street")
                or images.get("aerial")
                or images.get("map")
            )
            if primary:
                images["primary"] = primary
                if not zillow.get("photo"):
                    zillow["photo"] = primary

        await asyncio.gather(*(attach(li) for li in listings))

    log.info(
        "images.enrich.done",
        listings=len(listings),
        real=real_count,
        aerial=aerial_count,
        street=street_count,
    )
