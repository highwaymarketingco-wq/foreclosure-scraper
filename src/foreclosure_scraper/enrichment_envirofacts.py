"""EPA EnviroFacts enrichment — environmental hazard overlay for property leads.

The EPA EnviroFacts multistream API provides free, no-auth access to multiple
environmental databases. For a real-estate lead engine, the relevant ones are:

  1. Cleanups in My Community (CIMC) — Superfund, RCRA, Brownfields, DSCA sites
  2. ECHO (Enforcement & Compliance History Online) — facility compliance records
  3. TRI (Toxics Release Inventory) — facilities releasing toxic chemicals
  4. Air Quality System (AIRS) — air monitoring sites

We query by geographic area (lat/lon radius or ZIP/county) to flag properties
near environmental hazards. This is a distress signal — properties near
Superfund sites or toxic releases have depressed values and health concerns.

Endpoint: https://data.epa.gov/ef/service/
Format: JSON, no key needed
Alternative: REST data API at https://data.epa.gov/ef/

This enricher fills: envirofacts data into raw.envirofacts
"""
from __future__ import annotations

import asyncio
import json
from typing import Any

import structlog

from .http_client import client
from .models import Listing

log = structlog.get_logger()

# EPA ECHO REST endpoint (free, no key, rate-limited 300/hr 1500/day)
ECHO_URL = "https://echodata.epa.gov/echo/echo_rest_services.get_facilities"

# NOTE: data.epa.gov/ef/* endpoints (TRI, Superfund) are DEAD as of 2026 —
# they all return "Welcome to data.epa.gov!" instead of JSON.
# Removed TRI_URL and SUPERFUND_URL to stop wasting API calls on dead endpoints.

# Search radius in miles (convert to meters for EPA API)
DEFAULT_RADIUS_MILES = 1.0
MILES_TO_METERS = 1609.34

_SEMAPHORE = asyncio.Semaphore(3)


async def _query_echo(lat: float, lon: float, radius_m: float = 1609.0) -> list[dict]:
    """Query ECHO for facilities near coordinates."""
    try:
        async with client(timeout=15.0) as c:
            resp = await c.get(
                ECHO_URL,
                params={
                    "latitude": lat,
                    "longitude": lon,
                    "radius": radius_m,
                    "output": "JSON",
                },
                headers={"Accept": "application/json"},
            )
            if resp.status_code != 200:
                return []
            ct = resp.headers.get("content-type", "")
            if "json" not in ct:
                return []
            data = resp.json()
            return data.get("Results", {}).get("Facilities", [])
    except Exception as exc:
        log.debug("envirofacts.echo_fail", error=str(exc)[:80])
        return []


async def enrich_envirofacts(listing: Listing) -> Listing:
    """Enrich a listing with nearby environmental hazard data."""
    raw_update: dict[str, Any] = {"envirofacts": True}

    # Try lat/lon from previous enrichment (census_geocoder or arcgis)
    lat = None
    lon = None
    if listing.raw:
        lat = listing.raw.get("latitude")
        lon = listing.raw.get("longitude")

    if lat and lon:
        try:
            lat_f = float(lat)
            lon_f = float(lon)
            radius_m = DEFAULT_RADIUS_MILES * MILES_TO_METERS

            async with _SEMAPHORE:
                echo_results = await _query_echo(lat_f, lon_f, radius_m)

            if echo_results:
                raw_update["nearby_facilities"] = {
                    "count": len(echo_results),
                    "facilities": [
                        {
                            "name": f.get("FacilityName"),
                            "type": f.get("FacilityType"),
                            "registry_id": f.get("RegistryId"),
                            "distance_m": f.get("Distance"),
                        }
                        for f in echo_results[:10]
                    ],
                }
        except (TypeError, ValueError):
            pass

    if len(raw_update) > 1:  # more than just {"envirofacts": True}
        listing.raw = {**listing.raw, **raw_update}

    return listing


async def enrich_batch_envirofacts(
    listings: list[Listing], max_concurrent: int = 5
) -> list[Listing]:
    """Batch enrich listings with environmental hazard data."""
    need_env = [l for l in listings if "envirofacts" not in (l.raw or {})]
    if not need_env:
        return listings

    sem = asyncio.Semaphore(max_concurrent)

    async def _bounded(l: Listing) -> Listing:
        async with sem:
            return await enrich_envirofacts(l)

    results = await asyncio.gather(*[_bounded(l) for l in need_env], return_exceptions=True)

    idx = 0
    for i, listing in enumerate(listings):
        if "envirofacts" not in (listing.raw or {}):
            if idx < len(results) and not isinstance(results[idx], Exception):
                listings[i] = results[idx]
            idx += 1

    log.info("envirofacts.batch_done",
             total=len(need_env),
             enriched=sum(1 for r in results if not isinstance(r, Exception)))
    return listings
