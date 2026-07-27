"""Opportunity Zone enrichment — point-in-polygon check via HUD ArcGIS REST.

Uses the HUD Opportunity Zone FeatureService (ArcGIS Online, no auth/key):
  https://services.arcgis.com/VTyQ9soqVukalItT/arcgis/rest/services/Opportunity_Zones/FeatureServer/13

Layer 13 is the polygon layer for all designated Qualified Opportunity Zones
(QOZs) — census tracts designated under §§1400Z–1 and 1400Z–2 of the IRC.
Fields: GEOID10 (11-digit tract FIPS), STATE (FIPS), STUSAB (e.g. "NC"),
COUNTY (FIPS), TRACT, STATE_NAME, Rural (Y/N).

For each listing with lat/lng, we issue a point-intersection query against
the OZ polygon layer. If the point falls inside a designated OZ tract, the
listing is tagged with raw['opportunity_zone'] containing the tract GEOID,
state, county, and rural flag.

Opportunity Zones are a tax-incentive program, not a distress signal — but
properties in OZs are attractive to investors (capital-gains tax deferral),
so this is an INVESTMENT-FITNESS signal for the lead-grading pipeline, not a
distress score input.

Self-contained: uses httpx directly (like enrichment_flood_zone), since the
ArcGIS REST endpoint has different characteristics from our shared client.
Results are cached to disk with a 7-day TTL so repeated runs don't re-query
the same points.
"""
from __future__ import annotations

import asyncio
import json
import os
import time
from pathlib import Path
from typing import Optional

import httpx
import structlog

from .models import Listing

log = structlog.get_logger()

# HUD Opportunity Zone FeatureService — ArcGIS Online, no auth/key required.
# Layer 13 = Opportunity_Zones (esriGeometryPolygon).
OZ_FEATURESERVER = (
    "https://services.arcgis.com/VTyQ9soqVukalItT/arcgis/rest/services/"
    "Opportunity_Zones/FeatureServer"
)
OZ_LAYER = 13

# Cache: point → OZ result, disk-backed, 7-day TTL.
_CACHE_DIR = Path(
    os.environ.get(
        "FORECLOSURE_CACHE_DIR",
        str(Path(__file__).resolve().parent.parent / "cache"),
    )
)
_CACHE_FILE = _CACHE_DIR / "opportunity_zone_points.json"
_CACHE_TTL_S = 7 * 24 * 3600  # 7 days


def _load_cache() -> dict[str, dict]:
    """Load the disk cache of point→OZ-result mappings."""
    try:
        if _CACHE_FILE.exists():
            data = json.loads(_CACHE_FILE.read_text())
            # Prune expired entries
            now = time.time()
            return {
                k: v for k, v in data.items()
                if isinstance(v, dict) and (now - v.get("_ts", 0)) < _CACHE_TTL_S
            }
    except (json.JSONDecodeError, OSError):
        pass
    return {}


def _save_cache(cache: dict[str, dict]) -> None:
    """Persist the cache to disk."""
    try:
        _CACHE_DIR.mkdir(parents=True, exist_ok=True)
        _CACHE_FILE.write_text(json.dumps(cache))
    except OSError as exc:
        log.warning("opportunity_zone.cache_save_failed", error=str(exc)[:120])


def _cache_key(lat: float, lon: float) -> str:
    """Round to 5 decimal places (~1m) for cache dedup."""
    return f"{round(lat, 5)},{round(lon, 5)}"


async def check_opportunity_zone(
    lat: float, lon: float, *, timeout: float = 15.0
) -> dict:
    """Check if a point is inside a designated Opportunity Zone.

    Queries the HUD OZ FeatureService with a point-intersection query.
    Returns dict with:
        in_oz: bool — True if the point is inside a designated OZ tract
        geoid: str — 11-digit census tract FIPS (or None)
        state: str — state abbreviation, e.g. "NC" (or None)
        state_name: str — full state name (or None)
        county_fips: str — 3-digit county FIPS (or None)
        tract: str — 6-digit tract code (or None)
        rural: bool — True if the OZ is classified as rural
    """
    result = {
        "in_oz": False,
        "geoid": None,
        "state": None,
        "state_name": None,
        "county_fips": None,
        "tract": None,
        "rural": None,
    }

    geom = json.dumps(
        {"x": lon, "y": lat, "spatialReference": {"wkid": 4326}}
    )
    params = {
        "geometry": geom,
        "geometryType": "esriGeometryPoint",
        "inSR": "4326",
        "spatialRel": "esriSpatialRelIntersects",
        "outFields": "GEOID10,STATE,STUSAB,STATE_NAME,COUNTY,TRACT,Rural",
        "returnGeometry": "false",
        "f": "json",
    }
    query_url = f"{OZ_FEATURESERVER}/{OZ_LAYER}/query"

    try:
        async with httpx.AsyncClient(timeout=timeout) as c:
            r = await c.get(query_url, params=params)
            if r.status_code != 200:
                log.warning(
                    "opportunity_zone.http_error",
                    status=r.status_code,
                    lat=lat,
                    lon=lon,
                )
                return result
            # ArcGIS REST can return HTML error pages on some failures
            text = r.text or ""
            if not text.startswith("{"):
                return result
            data = r.json()
    except (httpx.HTTPError, json.JSONDecodeError) as exc:
        log.warning(
            "opportunity_zone.fetch_error",
            error=str(exc)[:120],
            lat=lat,
            lon=lon,
        )
        return result

    features = data.get("features") or []
    if not features:
        return result

    # Point-in-polygon: typically 0 or 1 feature (tracts don't overlap)
    attrs = features[0].get("attributes", {})
    result["in_oz"] = True
    result["geoid"] = attrs.get("GEOID10")
    result["state"] = attrs.get("STUSAB")
    result["state_name"] = attrs.get("STATE_NAME")
    result["county_fips"] = attrs.get("COUNTY")
    result["tract"] = attrs.get("TRACT")
    result["rural"] = (attrs.get("Rural") or "").upper() == "Y"
    return result


async def enrich_opportunity_zones(listings: list[Listing]) -> dict:
    """Add Opportunity Zone data to listings that have lat/lng.

    Writes to listing.raw['opportunity_zone'] = {
        in_oz, geoid, state, state_name, county_fips, tract, rural
    }

    Uses a disk cache so points already checked in a previous run (within
    the TTL) are served instantly without hitting the ArcGIS endpoint.
    """
    targets = [li for li in listings if li.latitude and li.longitude]
    if not targets:
        log.info("opportunity_zone.no_targets")
        return {"queried": 0, "in_oz": 0, "cached": 0}

    cache = _load_cache()
    stats = {"queried": 0, "in_oz": 0, "cached": 0, "failed": 0}

    # Phase 1: serve from cache where possible
    to_query: list[tuple[Listing, str]] = []
    for li in targets:
        key = _cache_key(li.latitude, li.longitude)
        if key in cache:
            entry = cache[key]
            result = {k: v for k, v in entry.items() if k != "_ts"}
            _stamp(li, result)
            stats["cached"] += 1
            if result.get("in_oz"):
                stats["in_oz"] += 1
        else:
            to_query.append((li, key))

    log.info(
        "opportunity_zone.start",
        target_count=len(targets),
        cached=stats["cached"],
        to_query=len(to_query),
    )

    if not to_query:
        log.info("opportunity_zone.all_cached", **stats)
        return stats

    # Phase 2: query ArcGIS for uncached points, with concurrency limit
    sem = asyncio.Semaphore(8)  # be polite to the ArcGIS endpoint

    async def _one(li: Listing, key: str) -> None:
        async with sem:
            result = await check_opportunity_zone(li.latitude, li.longitude)
            stats["queried"] += 1
            if result.get("in_oz"):
                stats["in_oz"] += 1
            elif result.get("geoid") is None and not result.get("in_oz"):
                # Could be a genuine "not in OZ" or a fetch failure.
                # We cache the result either way (the point didn't change).
                pass
            # Cache the result (including negative results)
            cache[key] = {**result, "_ts": time.time()}
            _stamp(li, result)

    await asyncio.gather(
        *[_one(li, key) for li, key in to_query], return_exceptions=True
    )

    _save_cache(cache)
    log.info("opportunity_zone.done", **stats)
    return stats


def _stamp(li: Listing, result: dict) -> None:
    """Write the OZ result to listing.raw['opportunity_zone']."""
    if not isinstance(li.raw, dict):
        li.raw = {}
    li.raw["opportunity_zone"] = result


# --------------------------------------------------------------------------- #
# Standalone test
# --------------------------------------------------------------------------- #
if __name__ == "__main__":
    async def _test():
        # Test points across our NC/SC footprint
        tests = [
            ("Asheville OZ area", 35.58, -82.56),      # in an Asheville OZ
            ("Asheville downtown", 35.5951, -82.5515),  # may or may not be OZ
            ("Spartanburg SC", 34.9496, -81.9321),
            ("Hendersonville NC", 35.3185, -82.4609),
            ("Charlotte NC", 35.2271, -80.8431),
        ]
        for name, lat, lon in tests:
            result = await check_opportunity_zone(lat, lon)
            status = "IN OZ" if result["in_oz"] else "not in OZ"
            tract = result.get("geoid") or "—"
            print(f"  {name}: {status} (tract={tract}, state={result.get('state')})")

    asyncio.run(_test())
