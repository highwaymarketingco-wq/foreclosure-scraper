"""Environmental + crime risk enrichment via free public APIs.

EPA ECHO (Enforcement and Compliance History Online):
  - Free public API, no key required
  - Returns regulated facilities within a radius of a point
  - We tag each listing with `raw.epa = {nearby_count, hazardous_count}`

FBI Crime Data Explorer (UCR):
  - Free public API at api.usa.gov/crime/fbi
  - Returns Part I crime counts per agency/year
  - We tag each listing with `raw.crime = {city_violent_per_1k, city_property_per_1k}`
  - Note: needs api.data.gov free key for high-volume; falls back to no-data otherwise

Both are best-effort; failure does not break the pipeline.
"""
from __future__ import annotations

import asyncio
import os
from typing import Optional

import httpx
import structlog

from .models import Listing

log = structlog.get_logger()

ECHO_FACILITIES = "https://echodata.epa.gov/echo/echo_rest_services.get_facilities"
ECHO_FACILITY_INFO = "https://echodata.epa.gov/echo/echo_rest_services.get_facility_info"
FBI_CRIME = "https://api.usa.gov/crime/fbi/cde/summarized"


async def _epa_nearby(c: httpx.AsyncClient, lat: float, lon: float, radius_mi: float = 1.0) -> Optional[dict]:
    """Count regulated facilities within `radius_mi` miles of (lat, lon).

    ECHO's ``get_facilities`` does NOT return the facility array inline — it
    returns a query *summary* whose total count lives at
    ``Results.QueryRows`` (a string). The prior code read a non-existent
    ``Results.Results`` list and therefore always reported ``nearby_count: 0``.

    We read ``QueryRows`` for the nearby count, then fetch the inline facility
    records via ``get_facility_info`` (which DOES nest them under
    ``Results.Facilities``) to break out hazardous/air violators.
    """
    try:
        r = await c.get(
            ECHO_FACILITIES,
            params={
                "output": "JSON",
                "p_lat": lat,
                "p_long": lon,
                "p_r": radius_mi,
                "p_act": "Y",  # active
                "responseset": "1",
            },
            timeout=12.0,
        )
        if r.status_code != 200:
            return None
        res = (r.json().get("Results") or {})
        if res.get("Error"):
            return None
        try:
            nearby = int(str(res.get("QueryRows") or "0").replace(",", ""))
        except (ValueError, TypeError):
            nearby = 0
        if nearby <= 0:
            return {"nearby_count": 0, "hazardous_count": 0}

        # Pull the inline facility records to count hazardous/air violators.
        haz = 0
        try:
            ri = await c.get(
                ECHO_FACILITY_INFO,
                params={
                    "output": "JSON",
                    "p_lat": lat,
                    "p_long": lon,
                    "p_r": radius_mi,
                    "p_act": "Y",
                },
                timeout=12.0,
            )
            if ri.status_code == 200:
                facs = ((ri.json().get("Results") or {}).get("Facilities")) or []
                if isinstance(facs, list):
                    haz = sum(
                        1
                        for f in facs
                        if str(f.get("FacHasInspections") or f.get("Hazardous_Waste") or "").upper() in ("Y", "TRUE")
                        or str(f.get("AIRFlag") or f.get("AIR_FLAG") or "").upper() in ("Y", "TRUE")
                    )
        except (httpx.HTTPError, ValueError):
            pass
        return {"nearby_count": nearby, "hazardous_count": haz}
    except Exception:
        return None


async def _fbi_crime_for_county(c: httpx.AsyncClient, state: str, county: str) -> Optional[dict]:
    """Pull FBI UCR summary for the most recent year. Returns None if no key configured.

    The api.data.gov key is free but optional; without it, FBI's CDE returns
    rate-limit errors quickly. Set FBI_API_KEY env var to enable.
    """
    key = os.environ.get("FBI_API_KEY") or os.environ.get("DATA_GOV_API_KEY")
    if not key:
        return None
    try:
        r = await c.get(
            FBI_CRIME,
            params={
                "API_KEY": key,
                "state": state,
                "agency": county,  # rough — may need real ORI code
            },
            timeout=12.0,
        )
        if r.status_code != 200:
            return None
        return r.json()
    except Exception:
        return None


async def enrich_with_environmental(listings: list[Listing], concurrency: int = 4) -> None:
    """Tag each lat/lng-bearing listing with EPA + (optionally) FBI crime data."""
    if not listings:
        return
    sem = asyncio.Semaphore(concurrency)
    epa_count = 0
    crime_count = 0

    # Cache crime data per (state, county) so we only pull once per county
    crime_cache: dict[tuple[str, str], dict | None] = {}

    async with httpx.AsyncClient(timeout=httpx.Timeout(15.0)) as c:

        async def lookup(li: Listing) -> None:
            nonlocal epa_count, crime_count
            if not (li.latitude and li.longitude):
                return
            async with sem:
                epa = await _epa_nearby(c, li.latitude, li.longitude, radius_mi=1.0)
            if epa:
                if not isinstance(li.raw, dict):
                    li.raw = {}
                li.raw["epa"] = epa
                epa_count += 1
            # Crime per county (cached)
            if li.state and li.county:
                ck = (li.state, li.county)
                if ck not in crime_cache:
                    async with sem:
                        crime_cache[ck] = await _fbi_crime_for_county(c, li.state, li.county)
                cd = crime_cache[ck]
                if cd:
                    if not isinstance(li.raw, dict):
                        li.raw = {}
                    li.raw["crime"] = cd
                    crime_count += 1

        await asyncio.gather(*(lookup(li) for li in listings))

    log.info(
        "environmental.done",
        listings=len(listings),
        epa_tagged=epa_count,
        crime_tagged=crime_count,
        crime_api_configured=bool(os.environ.get("FBI_API_KEY") or os.environ.get("DATA_GOV_API_KEY")),
    )
