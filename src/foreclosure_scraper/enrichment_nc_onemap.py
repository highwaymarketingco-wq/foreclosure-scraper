"""NC OneMap geospatial enrichment — parcel, zoning, floodplain overlay for NC.

NC OneMap provides free ArcGIS REST services for North Carolina counties.
For each listing's lat/lon (NC properties only), we query:

  1. Parcel boundaries — identify the parcel at the point
  2. Zoning — zoning designation at the property location
  3. Floodplains — FEMA flood zone overlay

Endpoint: https://services.nconemap.gov/arcgis/rest/services
Format: JSON (ArcGIS REST), no key needed for public services

This enricher fills: raw["nc_onemap"] dict with parcel, zoning, floodplain data.
"""
from __future__ import annotations

import asyncio
from typing import Any

import structlog

from .http_client import client
from .models import Listing

log = structlog.get_logger()

ONEMAP_BASE = "https://services.nconemap.gov/arcgis/rest/services"
_SEMAPHORE = asyncio.Semaphore(3)  # be polite, 3 concurrent

# Known NC OneMap ArcGIS REST service endpoints for property-relevant layers.
# These are the public (non-secure) MapServer endpoints that don't require auth.
PARCEL_URL = f"{ONEMAP_BASE}/NC_Parcels/MapServer/0/query"
FLOODPLAIN_URL = f"{ONEMAP_BASE}/NFHL/MapServer/0/query"
ZONING_URL = f"{ONEMAP_BASE}/NC_Zoning/MapServer/0/query"


async def _query_arcgis_point(
    url: str, lat: float, lon: float
) -> list[dict[str, Any]]:
    """Generic ArcGIS REST point-intersection query on a MapServer layer."""
    try:
        async with client(timeout=15.0) as c:
            resp = await c.get(
                url,
                params={
                    "geometry": f"{lon},{lat}",
                    "geometryType": "esriGeometryPoint",
                    "inSR": "4326",
                    "spatialRel": "esriSpatialRelIntersects",
                    "returnGeometry": "false",
                    "returnCountOnly": "false",
                    "f": "json",
                    "outFields": "*",
                },
                headers={"Accept": "application/json"},
            )
            if resp.status_code != 200:
                return []
            data = resp.json()
    except Exception as exc:
        log.debug("nc_onemap.query_fail", url=url, error=str(exc)[:80])
        return []

    features = data.get("features", [])
    if not features:
        return []

    results: list[dict[str, Any]] = []
    for feat in features:
        attrs = feat.get("attributes", {})
        if attrs:
            results.append(attrs)
    return results


async def enrich_nc_onemap(listing: Listing) -> Listing:
    """Enrich an NC listing with parcel, zoning, and floodplain data."""
    raw_update: dict[str, Any] = {"nc_onemap": {}}

    # Only query for NC properties
    state = (listing.state or "").strip().upper()
    if state != "NC":
        listing.raw = {**listing.raw, **raw_update}
        return listing

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

            # Query parcel boundaries
            async with _SEMAPHORE:
                parcels = await _query_arcgis_point(PARCEL_URL, lat_f, lon_f)
            if parcels:
                raw_update["nc_onemap"]["parcel"] = parcels[0]

            # Query floodplains
            async with _SEMAPHORE:
                floods = await _query_arcgis_point(FLOODPLAIN_URL, lat_f, lon_f)
            if floods:
                raw_update["nc_onemap"]["floodplain"] = [
                    {"zone": f.get("FLD_ZONE"), "type": f.get("ZONE_SUBTYPE")}
                    for f in floods[:5]
                ]

            # Query zoning
            async with _SEMAPHORE:
                zones = await _query_arcgis_point(ZONING_URL, lat_f, lon_f)
            if zones:
                raw_update["nc_onemap"]["zoning"] = [
                    z.get("ZONING_TYPE") or z.get("ZONE_CODE") or str(z)
                    for z in zones[:5]
                ]

        except (TypeError, ValueError):
            pass

    listing.raw = {**listing.raw, **raw_update}
    return listing


async def enrich_batch_nc_onemap(
    listings: list[Listing], max_concurrent: int = 5
) -> list[Listing]:
    """Batch enrich NC listings with OneMap geospatial data."""
    need_onemap = [l for l in listings if "nc_onemap" not in (l.raw or {})]
    if not need_onemap:
        return listings

    sem = asyncio.Semaphore(max_concurrent)

    async def _bounded(l: Listing) -> Listing:
        async with sem:
            return await enrich_nc_onemap(l)

    results = await asyncio.gather(
        *[_bounded(l) for l in need_onemap], return_exceptions=True
    )

    idx = 0
    for i, listing in enumerate(listings):
        if "nc_onemap" not in (listing.raw or {}):
            if idx < len(results) and not isinstance(results[idx], Exception):
                listings[i] = results[idx]
            idx += 1

    log.info(
        "nc_onemap.batch_done",
        total=len(need_onemap),
        enriched=sum(1 for r in results if not isinstance(r, Exception)),
    )
    return listings
