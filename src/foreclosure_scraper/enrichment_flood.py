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


async def enrich_with_flood(listings: list[Listing], concurrency: int = 4) -> None:
    """Tag each listing with FEMA flood-zone data. Free, no API key."""
    if not listings:
        return
    sem = asyncio.Semaphore(concurrency)
    in_sfha = 0
    matched = 0

    async with httpx.AsyncClient(timeout=httpx.Timeout(15.0)) as c:

        async def lookup(li: Listing) -> None:
            nonlocal in_sfha, matched
            if not (li.latitude and li.longitude):
                return
            async with sem:
                result = await _query_flood_zone(c, li.latitude, li.longitude)
            if not result:
                return
            if not isinstance(li.raw, dict):
                li.raw = {}
            li.raw["flood"] = result
            matched += 1
            if result.get("in_sfha"):
                in_sfha += 1

        await asyncio.gather(*(lookup(li) for li in listings))

    log.info(
        "flood.enrich.done",
        listings=len(listings),
        with_flood_data=matched,
        in_high_risk_zone=in_sfha,
    )
