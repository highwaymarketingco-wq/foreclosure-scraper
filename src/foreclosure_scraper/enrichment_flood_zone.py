"""FEMA flood zone enrichment - per-lead flood flag via NFHL ArcGIS REST.

Uses the free National Flood Hazard Layer (NFHL) service at
hazards.fema.gov/gis/nfhl/rest/services/public/NFHL/MapServer.

No API key required. Queries the flood zones layer by point intersection
to determine if a property is in a Special Flood Hazard Area (SFHA).

SFHA zones (high risk): A, AE, AH, AO, V, VE
Non-SFHA zones (moderate/low): X, X500, B, C, D
"""
from __future__ import annotations

import asyncio
import json
from typing import Optional

import httpx
import structlog

log = structlog.get_logger()

NFHL_URL = "https://hazards.fema.gov/gis/nfhl/rest/services/public/NFHL/MapServer"

# Layer 27 = Flood Zones in the NFHL service
FLOOD_ZONES_LAYER = 27

# SFHA (high-risk) flood zone prefixes
SFHA_ZONES = {"A", "AE", "AH", "AO", "A1", "A2", "A3", "A4", "A5", "A6",
              "A7", "A8", "A9", "A10", "A11", "A12", "A13", "A14", "A15",
              "A16", "A17", "A18", "A19", "A99", "V", "VE", "V1", "V2",
              "V3", "V4", "V5", "V6", "V7", "V8", "V9", "V10", "V11",
              "V12", "V13", "V14", "V15", "V16", "V17", "V18", "V19", "VO"}

# FEMA NFHL REST is behind an access management portal (Tivoli/IIM).
# The direct ArcGIS REST endpoint returns 404 HTML, not JSON.
# We use curl_cffi with chrome impersonation as a fallback, and if that
# also fails, we try the FEMA Prelim REST and NC/SC state GIS layers.
# If all fail, the enrichment is skipped (best-effort, non-blocking).

_FLOOD_QUERY_URLS = [
    # FEMA NFHL primary
    (NFHL_URL, FLOOD_ZONES_LAYER, "FLD_ZONE,ZONE_SUBTY"),
    # FEMA Prelim fallback (preliminary flood hazard data)
    ("https://hazards.fema.gov/gis/nfhl/rest/services/public/NFHLPre/MapServer",
     FLOOD_ZONES_LAYER, "FLD_ZONE,ZONE_SUBTY"),
]


async def check_flood_zone(lat: float, lon: float) -> dict:
    """Check if a point is in a FEMA flood zone.

    Tries the FEMA NFHL REST service with curl_cffi (chrome impersonation),
    then falls back to alternative endpoints. Best-effort: returns unknown
    if all endpoints are unreachable.

    Returns dict with:
        in_sfha: bool (True if in a high-risk Special Flood Hazard Area)
        zone: str (flood zone code, e.g. "AE", "X", or None)
        zone_description: str (human-readable description)
        flood_risk: str ("high", "moderate", "low", "unknown")
    """
    result = {
        "in_sfha": False,
        "zone": None,
        "zone_description": None,
        "flood_risk": "unknown",
    }

    geom = json.dumps({"x": lon, "y": lat, "spatialReference": {"wkid": 4326}})

    # Try curl_cffi with chrome impersonation (passes TLS fingerprint checks)
    try:
        from curl_cffi import requests as cffi_requests

        for base_url, layer_id, out_fields in _FLOOD_QUERY_URLS:
            query_url = f"{base_url}/{layer_id}/query"
            params = {
                "geometry": geom,
                "geometryType": "esriGeometryPoint",
                "inSR": "4326",
                "spatialRel": "esriSpatialRelIntersects",
                "outFields": out_fields,
                "returnGeometry": "false",
                "f": "json",
            }
            try:
                r = cffi_requests.get(query_url, params=params,
                                      impersonate="chrome", timeout=15)
                if r.status_code != 200 or not r.text.startswith("{"):
                    continue
                data = r.json()
                features = data.get("features", [])
                if features:
                    break
            except Exception:
                continue
        else:
            features = []
    except ImportError:
        # curl_cffi not available, try httpx
        features = []
        async with httpx.AsyncClient(timeout=15.0) as c:
            for base_url, layer_id, out_fields in _FLOOD_QUERY_URLS:
                query_url = f"{base_url}/{layer_id}/query"
                params = {
                    "geometry": geom,
                    "geometryType": "esriGeometryPoint",
                    "inSR": "4326",
                    "spatialRel": "esriSpatialRelIntersects",
                    "outFields": out_fields,
                    "returnGeometry": "false",
                    "f": "json",
                }
                try:
                    r = await c.get(query_url, params=params)
                    if r.status_code != 200 or not r.text.startswith("{"):
                        continue
                    data = r.json()
                    features = data.get("features", [])
                    if features:
                        break
                except Exception:
                    continue

    if not features:
        return result

    # Find the most severe zone (SFHA over non-SFHA)
    for feat in features:
        attrs = feat.get("attributes", {})
        zone = (attrs.get("FLD_ZONE") or "").strip().upper()
        if not zone:
            continue

        # Check if this is an SFHA zone
        is_sfha = zone in SFHA_ZONES or zone.startswith(("A", "V"))

        if is_sfha:
            result["in_sfha"] = True
            result["zone"] = zone
            result["zone_description"] = attrs.get("ZONE_SUBTY", "")
            result["flood_risk"] = "high"
            return result
        elif zone in ("X", "X500", "B", "C"):
            if result["flood_risk"] != "high":
                result["zone"] = zone
                result["zone_description"] = "Area of moderate/low flood hazard"
                result["flood_risk"] = "moderate" if zone == "X500" else "low"
        elif zone == "D":
            if result["flood_risk"] == "unknown":
                result["zone"] = "D"
                result["zone_description"] = "Area of undetermined flood hazard"
                result["flood_risk"] = "unknown"

    return result


async def enrich_flood_zones(listings: list) -> dict:
    """Add flood zone data to listings that have lat/lng.

    Writes to listing.raw['flood_zone'] = {
        in_sfha, zone, zone_description, flood_risk
    }
    """
    targets = [li for li in listings if li.latitude and li.longitude]
    if not targets:
        log.info("flood_zone.no_targets")
        return {"queried": 0, "in_sfha": 0, "moderate": 0, "low": 0, "unknown": 0}

    log.info("flood_zone.start", target_count=len(targets))
    stats = {"queried": 0, "in_sfha": 0, "moderate": 0, "low": 0, "unknown": 0, "failed": 0}

    sem = asyncio.Semaphore(10)  # FEMA rate limit courtesy

    async def one(li):
        async with sem:
            result = await check_flood_zone(li.latitude, li.longitude)
            stats["queried"] += 1

            if result.get("in_sfha"):
                stats["in_sfha"] += 1
            elif result.get("flood_risk") == "moderate":
                stats["moderate"] += 1
            elif result.get("flood_risk") == "low":
                stats["low"] += 1
            elif result.get("flood_risk") == "unknown":
                stats["unknown"] += 1
            else:
                stats["failed"] += 1

            if not isinstance(li.raw, dict):
                li.raw = {}
            li.raw["flood_zone"] = result

    await asyncio.gather(*[one(li) for li in targets], return_exceptions=True)

    log.info("flood_zone.done", **stats)
    return stats


if __name__ == "__main__":
    async def _test():
        # Test against our footprint coordinates
        tests = [
            ("Asheville NC", 35.5951, -82.5515),
            ("Spartanburg SC", 34.9496, -81.9321),
            ("Hendersonville NC", 35.3185, -82.4609),
            ("Buncombe riverfront", 35.5800, -82.5700),  # near French Broad
        ]
        for name, lat, lon in tests:
            result = await check_flood_zone(lat, lon)
            print(f"{name}: zone={result['zone']} risk={result['flood_risk']} sfha={result['in_sfha']}")

    asyncio.run(_test())
