"""USFWS Wetlands Mapper enrichment — NWI wetland intersection overlay.

The USFWS National Wetlands Inventory (NWI) Wetlands Mapper provides free,
no-auth ArcGIS REST access to the Wetlands_Extract MapServer. For each
listing's lat/lon, we query whether the property intersects any NWI-mapped
wetland polygons and collect their wetland types.

Endpoint: https://www.fws.gov/wetlandsmapserver/services/Wetlands_Extract/MapServer/0/query
Params: geometry (point), geometryType, spatialRel=Intersects, inSR=4326
Format: JSON, no key needed

This enricher fills: raw["wetlands"] with a list of wetland type strings.
"""
from __future__ import annotations

import asyncio
from typing import Any

import structlog

from .http_client import client
from .models import Listing

log = structlog.get_logger()

WETLANDS_URL = (
    "https://www.fws.gov/wetlandsmapserver/services/"
    "Wetlands_Extract/MapServer/0/query"
)
_SEMAPHORE = asyncio.Semaphore(3)  # be polite, 3 concurrent
_walled = False
_consecutive_fail = 0
_WALL_THRESHOLD = 10  # after 10 consecutive DNS/network failures, stop trying


async def _query_wetlands(lat: float, lon: float) -> list[dict[str, Any]]:
    """Query NWI wetlands intersecting a point (lat/lon)."""
    global _walled, _consecutive_fail
    if _walled:
        return []
    try:
        async with client(timeout=15.0) as c:
            resp = await c.get(
                WETLANDS_URL,
                params={
                    "geometry": f"{lon},{lat}",
                    "geometryType": "esriGeometryPoint",
                    "inSR": "4326",
                    "spatialRel": "esriSpatialRelIntersects",
                    "returnGeometry": "false",
                    "returnCountOnly": "false",
                    "f": "json",
                    "outFields": "WETLAND_TYPE,ATTRIBUTE,ACRES",
                },
                headers={"Accept": "application/json"},
            )
            if resp.status_code != 200:
                return []
            data = resp.json()
        _consecutive_fail = 0  # reset on success
    except Exception as exc:
        _consecutive_fail += 1
        if _consecutive_fail >= _WALL_THRESHOLD:
            _walled = True
            log.warning("wetlands.walled", consecutive_fail=_consecutive_fail,
                        error=str(exc)[:80])
        else:
            log.debug("wetlands.query_fail", lat=lat, lon=lon, error=str(exc)[:80])
        return []

    features = data.get("features", [])
    if not features:
        return []

    results: list[dict[str, Any]] = []
    for feat in features:
        attrs = feat.get("attributes", {})
        wtype = attrs.get("WETLAND_TYPE")
        if wtype:
            results.append({
                "type": wtype,
                "code": attrs.get("ATTRIBUTE"),
                "acres": attrs.get("ACRES"),
            })
    return results


async def enrich_usfws_wetlands(listing: Listing) -> Listing:
    """Enrich a listing with NWI wetland intersection data."""
    raw_update: dict[str, Any] = {"wetlands": []}

    # Try lat/lon from listing fields or previous enrichment
    lat = listing.latitude
    lon = listing.longitude
    if not lat or not lon:
        raw = listing.raw if isinstance(listing.raw, dict) else {}
        lat = raw.get("latitude")
        lon = raw.get("longitude")

    if lat and lon:
        try:
            lat_f = float(lat)
            lon_f = float(lon)
            async with _SEMAPHORE:
                wetlands = await _query_wetlands(lat_f, lon_f)
            if wetlands:
                raw_update["wetlands"] = wetlands
        except (TypeError, ValueError):
            pass

    listing.raw = {**listing.raw, **raw_update}
    return listing


async def enrich_batch_usfws_wetlands(
    listings: list[Listing], max_concurrent: int = 5
) -> list[Listing]:
    """Batch enrich listings with NWI wetland intersection data."""
    need_wet = [l for l in listings if "wetlands" not in (l.raw or {})]
    if not need_wet:
        return listings

    sem = asyncio.Semaphore(max_concurrent)

    async def _bounded(l: Listing) -> Listing:
        async with sem:
            return await enrich_usfws_wetlands(l)

    results = await asyncio.gather(
        *[_bounded(l) for l in need_wet], return_exceptions=True
    )

    idx = 0
    for i, listing in enumerate(listings):
        if "wetlands" not in (listing.raw or {}):
            if idx < len(results) and not isinstance(results[idx], Exception):
                listings[i] = results[idx]
            idx += 1

    log.info(
        "usfws_wetlands.batch_done",
        total=len(need_wet),
        enriched=sum(1 for r in results if not isinstance(r, Exception)),
    )
    return listings
