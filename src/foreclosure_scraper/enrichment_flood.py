"""FEMA flood-zone risk per listing.

FEMA's National Flood Hazard Layer (NFHL) is exposed as a free public ArcGIS
REST FeatureService — no API key required. We query the flood-zone layer at
each listing's lat/lng and tag the SFHA (Special Flood Hazard Area) zone code.

Flood-zone codes (key ones for investors):
  - AE     = 1% annual flood (100-year), high-risk; mandatory flood insurance
  - A      = 1% annual flood, no detailed study
  - VE     = coastal high-velocity wave action
  - X      = outside SFHA (low risk)
  - X SHADED = 0.2% annual flood (500-year), moderate risk
  - D      = undetermined risk
  - OPEN WATER

For each listing we attach raw.flood = {zone, sfha_pct, in_sfha} so the
calculator + grade can dock points for high-risk parcels.
"""
from __future__ import annotations

import asyncio
import os
from typing import Optional

import httpx
import structlog

from .models import Listing

log = structlog.get_logger()

FEMA_NFHL_LAYER = (
    "https://hazards.fema.gov/arcgis/rest/services/public/NFHL/MapServer/28/query"
)


async def _query_flood_zone(c: httpx.AsyncClient, lat: float, lon: float) -> Optional[dict]:
    """Return {zone, sfha_pct, in_sfha} or None if no NFHL coverage at point."""
    try:
        r = await c.get(
            FEMA_NFHL_LAYER,
            params={
                "geometry": f"{lon},{lat}",
                "geometryType": "esriGeometryPoint",
                "inSR": "4326",
                "spatialRel": "esriSpatialRelIntersects",
                "outFields": "FLD_ZONE,ZONE_SUBTY,SFHA_TF,STATIC_BFE",
                "returnGeometry": "false",
                "f": "json",
            },
            timeout=10.0,
        )
        if r.status_code != 200:
            return None
        data = r.json()
        features = data.get("features") or []
        if not features:
            return {"zone": "X", "sfha_tf": False, "in_sfha": False, "note": "outside any mapped flood zone"}
        attrs = features[0].get("attributes") or {}
        zone = attrs.get("FLD_ZONE") or "?"
        sfha = (attrs.get("SFHA_TF") or "").upper() == "T"
        return {
            "zone": zone,
            "subtype": attrs.get("ZONE_SUBTY"),
            "sfha_tf": sfha,
            "in_sfha": sfha,
            "static_bfe": attrs.get("STATIC_BFE"),
        }
    except Exception:
        return None


#: Coordinate precision for the in-run cache. 4 decimals is ~11 m, so two leads
#: that collapse to one key are on the same parcel for flood purposes. Going
#: coarser would start merging across a zone boundary, which is a real risk near
#: a floodway edge and not worth the extra saving.
_CACHE_PRECISION = 4

#: A flood zone is a fixed FEMA polygon: it does not change between runs, and
#: raw["flood"] survives on the board. Re-querying an already-tagged lead every
#: run is the single largest waste in this enricher. Set FLOOD_REFRESH=1 to
#: force a full re-read after a FEMA map revision.
_REFRESH = os.environ.get("FLOOD_REFRESH", "").strip() == "1"


def _needs_flood(li: Listing) -> bool:
    if not (li.latitude and li.longitude):
        return False
    if _REFRESH:
        return True
    existing = li.raw.get("flood") if isinstance(li.raw, dict) else None
    return not isinstance(existing, dict) or not existing.get("zone")


async def enrich_with_flood(listings: list[Listing], concurrency: int = 8) -> None:
    """Tag each listing with FEMA flood-zone data. Free, no API key.

    A full run was spending hours here re-reading zones it already had. Three
    things keep it cheap now, in order of how much they save:

      1. leads that already carry a zone are skipped entirely
      2. identical coordinates are queried once and shared
      3. concurrency is 8 rather than 4

    All three are counted in the completion log, so a run that is slow here
    again says why instead of just looking stuck.
    """
    if not listings:
        return
    sem = asyncio.Semaphore(concurrency)
    in_sfha = 0
    matched = 0

    geocoded = [li for li in listings if li.latitude and li.longitude]
    targets = [li for li in geocoded if _needs_flood(li)]
    skipped = len(geocoded) - len(targets)
    cache: dict[tuple[float, float], Optional[dict]] = {}
    cache_hits = 0

    async with httpx.AsyncClient(timeout=httpx.Timeout(15.0)) as c:

        async def lookup(li: Listing) -> None:
            nonlocal in_sfha, matched, cache_hits
            key = (round(li.latitude, _CACHE_PRECISION),
                   round(li.longitude, _CACHE_PRECISION))
            if key in cache:
                result = cache[key]
                cache_hits += 1
            else:
                async with sem:
                    # Re-check: a coroutine scheduled before this one may have
                    # filled the key while this one waited on the semaphore.
                    if key in cache:
                        result = cache[key]
                        cache_hits += 1
                    else:
                        result = await _query_flood_zone(c, li.latitude, li.longitude)
                        cache[key] = result
            if not result:
                return
            if not isinstance(li.raw, dict):
                li.raw = {}
            li.raw["flood"] = result
            matched += 1
            if result.get("in_sfha"):
                in_sfha += 1

        await asyncio.gather(*(lookup(li) for li in targets))

    log.info("flood.enrich.plan", total=len(listings), queried=len(targets),
             skipped_already_tagged=skipped, cache_hits=cache_hits,
             distinct_points=len(cache))

    log.info(
        "flood.enrich.done",
        listings=len(listings),
        with_flood_data=matched,
        in_high_risk_zone=in_sfha,
    )
