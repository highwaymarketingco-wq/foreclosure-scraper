"""FBI Uniform Crime Reporting enrichment — county-level crime statistics.

The FBI UCR API (https://api.usdoj.gov/api/public/api/) provides free access to
crime data collected under the Uniform Crime Reporting program. It requires a
free API key (sign up at https://api.usdoj.gov/api-public/signup/).

For each listing's county, we query:
  1. Law enforcement agencies in the county (by FIPS code)
  2. Summarized annual estimates for violent and property crime rates

API key: FBI_API_KEY in .env (required — the API returns 401 without it)
Endpoint: https://api.usdoj.gov/api/public/api/
Params: api_key, format=json

This enricher fills: raw["crime_stats"] dict with violent/property crime rates.
"""
from __future__ import annotations

import asyncio
import os
from typing import Any

import structlog

from .http_client import client
from .models import Listing

log = structlog.get_logger()

FBI_BASE = "https://api.usdoj.gov/api/public/api"
_SEMAPHORE = asyncio.Semaphore(3)


def _get_api_key() -> str | None:
    """Read the FBI API key from the environment."""
    key = os.environ.get("FBI_API_KEY", "").strip()
    return key if key else None


async def _query_fbi_agencies(
    county_fips: str, api_key: str
) -> list[dict[str, Any]]:
    """Query FBI UCR for law enforcement agencies in a county."""
    url = f"{FBI_BASE}/queries/agencies"
    try:
        async with client(timeout=15.0) as c:
            resp = await c.get(
                url,
                params={
                    "api_key": api_key,
                    "county": county_fips,
                    "format": "json",
                },
                headers={"Accept": "application/json"},
            )
            if resp.status_code != 200:
                return []
            data = resp.json()
    except Exception as exc:
        log.debug("fbi_ucr.agencies_fail", county=county_fips, error=str(exc)[:80])
        return []

    # Response shape: {"county_agencies": [...]} or {"agencies": [...]}
    return (
        data.get("county_agencies", [])
        or data.get("agencies", [])
        or []
    )


async def _query_fbi_estimates(
    ori: str, api_key: str
) -> dict[str, Any] | None:
    """Query FBI UCR summarized annual estimates for a single agency (ORI)."""
    url = f"{FBI_BASE}/summarized/estimates/agencies/{ori}"
    try:
        async with client(timeout=15.0) as c:
            resp = await c.get(
                url,
                params={
                    "api_key": api_key,
                    "format": "json",
                },
                headers={"Accept": "application/json"},
            )
            if resp.status_code != 200:
                return None
            data = resp.json()
    except Exception as exc:
        log.debug("fbi_ucr.estimates_fail", ori=ori, error=str(exc)[:80])
        return None

    # Response shape: {"results": [...]} — one row per year, newest-first typically
    results = data.get("results", [])
    if not results:
        return None

    # Take the most recent year's data
    latest = results[0] if isinstance(results, list) else results
    if not isinstance(latest, dict):
        return None

    return {
        "year": latest.get("data_year"),
        "violent_crime": _safe_int(latest.get("violent_crime")),
        "property_crime": _safe_int(latest.get("property_crime")),
        "homicide": _safe_int(latest.get("homicide")),
        "rape": _safe_int(latest.get("rape")),
        "robbery": _safe_int(latest.get("robbery")),
        "aggravated_assault": _safe_int(latest.get("aggravated_assault")),
        "burglary": _safe_int(latest.get("burglary")),
        "larceny": _safe_int(latest.get("larceny")),
        "motor_vehicle_theft": _safe_int(latest.get("motor_vehicle_theft")),
    }


def _safe_int(val) -> int | None:
    if val is None:
        return None
    try:
        return int(val)
    except (ValueError, TypeError):
        return None


async def enrich_fbi_ucr(listing: Listing) -> Listing:
    """Enrich a listing with FBI UCR county-level crime statistics."""
    raw_update: dict[str, Any] = {"crime_stats": {}}

    api_key = _get_api_key()
    if not api_key:
        log.debug("fbi_ucr.no_api_key")
        listing.raw = {**listing.raw, **raw_update}
        return listing

    # Get county FIPS from previous enrichment (census_geocoder) or construct it
    raw = listing.raw if isinstance(listing.raw, dict) else {}
    county_fips = raw.get("county_fips")
    state_fips = raw.get("state_fips")

    if not county_fips and listing.county and listing.state:
        # Without FIPS, we can't query the county endpoint reliably
        log.debug("fbi_ucr.no_county_fips", county=listing.county, state=listing.state)
        listing.raw = {**listing.raw, **raw_update}
        return listing

    if county_fips:
        county_fips_str = str(county_fips).zfill(3)

        async with _SEMAPHORE:
            agencies = await _query_fbi_agencies(county_fips_str, api_key)

        if agencies:
            # Aggregate crime stats across all agencies in the county
            total_violent = 0
            total_property = 0
            agency_count = 0
            latest_year = None

            for agency in agencies[:10]:  # cap at 10 agencies to be polite
                ori = agency.get("ori") or agency.get("ORI")
                if not ori:
                    continue
                async with _SEMAPHORE:
                    est = await _query_fbi_estimates(ori, api_key)
                if est:
                    agency_count += 1
                    if est.get("violent_crime"):
                        total_violent += est["violent_crime"]
                    if est.get("property_crime"):
                        total_property += est["property_crime"]
                    if est.get("year") and (
                        latest_year is None or est["year"] > latest_year
                    ):
                        latest_year = est["year"]

            if agency_count > 0:
                raw_update["crime_stats"] = {
                    "county_fips": county_fips_str,
                    "agency_count": agency_count,
                    "year": latest_year,
                    "violent_crime_total": total_violent,
                    "property_crime_total": total_property,
                    "violent_crime_rate": (
                        round(total_violent / agency_count, 1) if agency_count else None
                    ),
                    "property_crime_rate": (
                        round(total_property / agency_count, 1) if agency_count else None
                    ),
                    "source": "fbi_ucr",
                }

    listing.raw = {**listing.raw, **raw_update}
    return listing


async def enrich_batch_fbi_ucr(
    listings: list[Listing], max_concurrent: int = 3
) -> list[Listing]:
    """Batch enrich listings with FBI UCR county-level crime stats.

    Lower default concurrency (3) because the FBI API is rate-sensitive and
    we make multiple sub-queries per listing (agencies + per-agency estimates).
    """
    need_crime = [l for l in listings if "crime_stats" not in (l.raw or {})]
    if not need_crime:
        return listings

    sem = asyncio.Semaphore(max_concurrent)

    async def _bounded(l: Listing) -> Listing:
        async with sem:
            return await enrich_fbi_ucr(l)

    results = await asyncio.gather(
        *[_bounded(l) for l in need_crime], return_exceptions=True
    )

    idx = 0
    for i, listing in enumerate(listings):
        if "crime_stats" not in (listing.raw or {}):
            if idx < len(results) and not isinstance(results[idx], Exception):
                listings[i] = results[idx]
            idx += 1

    log.info(
        "fbi_ucr.batch_done",
        total=len(need_crime),
        enriched=sum(1 for r in results if not isinstance(r, Exception)),
    )
    return listings
