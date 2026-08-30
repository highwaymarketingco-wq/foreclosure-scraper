"""Census Geocoder enrichment — free address standardization + lat/lon + tract.

The US Census Geocoder is a free, no-auth API that:
  1. Standardizes a street address ( USPS-quality formatting)
  2. Returns lat/lon coordinates
  3. Returns the Census tract and block code (enables demographic joins)
  4. Returns the county FIPS code

Endpoint: https://geocoding.geo.census.gov/geocoder/geographies/onelineaddress
Params: address, benchmark=Public_AR_Current, vintage=Current_Current
Format: JSON, no key needed, rate limit ~1 req/sec (undocumented, be polite)

This enricher fills: latitude, longitude, census_tract, county_fips in raw.
If the address was corrected (standardized), it also stores the standardized
form for later comparison.

Useful for:
  - Standardizing addresses before phone append / mailing
  - Joining ACS demographic data by tract
  - Mapping properties for the dashboard
"""
from __future__ import annotations

import asyncio
import json
import re
from typing import Any

import structlog

from .http_client import client
from .models import Listing

log = structlog.get_logger()

GEOCODER_URL = "https://geocoding.geo.census.gov/geocoder/geographies/onelineaddress"
_SEMAPHORE = asyncio.Semaphore(3)  # be polite, 3 concurrent


async def _geocode_address(address: str, city: str | None = None,
                           state: str | None = None, zip_code: str | None = None) -> dict[str, Any] | None:
    """Geocode a single address via Census API."""
    # Build full address string
    full_addr = address or ""
    if city:
        full_addr = f"{full_addr}, {city}"
    if state:
        full_addr = f"{full_addr}, {state}"
    if zip_code:
        full_addr = f"{full_addr} {zip_code}"
    full_addr = full_addr.strip(", ").strip()
    if not full_addr or len(full_addr) < 5:
        return None

    try:
        async with client(timeout=15.0) as c:
            resp = await c.get(
                GEOCODER_URL,
                params={
                    "address": full_addr,
                    "benchmark": "Public_AR_Current",
                    "vintage": "Current_Current",
                    "format": "json",
                },
                headers={"Accept": "application/json"},
            )
            if resp.status_code != 200:
                return None
            data = resp.json()
    except Exception as exc:
        log.debug("census_geocode.fail", addr=full_addr[:60], error=str(exc)[:80])
        return None

    # Parse the Census response
    result_sets = data.get("result", {}).get("addressMatches", [])
    if not result_sets:
        return None

    match = result_sets[0]
    coords = match.get("coordinates", {})
    geographies = match.get("geographies", {})

    # Extract tract info from geographies
    tract_info = {}
    for layer, entries in geographies.items():
        if entries:
            entry = entries[0]
            tract_info["census_tract"] = entry.get("TRACT")
            tract_info["county_fips"] = entry.get("COUNTY")
            tract_info["state_fips"] = entry.get("STATE")
            tract_info["block_group"] = entry.get("BLKGRP")
            tract_info["block"] = entry.get("BLOCK")
            break

    return {
        "matched_address": match.get("matchedAddress"),
        "matched": match.get("matchType") is not None,
        "latitude": coords.get("y"),
        "longitude": coords.get("x"),
        "tiger_line_id": match.get("tigerLine", {}).get("lineId") if isinstance(match.get("tigerLine"), dict) else None,
        "side": match.get("tigerLine", {}).get("side") if isinstance(match.get("tigerLine"), dict) else None,
        **tract_info,
    }


async def enrich_census_geocoder(listing: Listing) -> Listing:
    """Enrich a listing with Census geocoder data (lat/lon, tract, FIPS)."""
    addr = listing.street_address
    if not addr or len(addr) < 5:
        return listing

    async with _SEMAPHORE:
        result = await _geocode_address(
            addr, city=listing.city, state=listing.state, zip_code=listing.zip_code
        )

    if not result:
        return listing

    # Fill coordinates if missing
    raw_update: dict[str, Any] = {"census_geocoder": True}

    if result.get("latitude") and result.get("longitude"):
        raw_update["latitude"] = float(result["latitude"])
        raw_update["longitude"] = float(result["longitude"])

    if result.get("matched_address"):
        raw_update["standardized_address"] = result["matched_address"]

    if result.get("census_tract"):
        raw_update["census_tract"] = result["census_tract"]
    if result.get("county_fips"):
        raw_update["county_fips"] = result["county_fips"]
    if result.get("state_fips"):
        raw_update["state_fips"] = result["state_fips"]
    if result.get("block_group"):
        raw_update["block_group"] = result["block_group"]

    listing.raw = {**listing.raw, **raw_update}
    return listing


async def enrich_batch_census_geocoder(
    listings: list[Listing], max_concurrent: int = 5
) -> list[Listing]:
    """Batch geocode listings. Rate-limited to be polite."""
    need_geo = [l for l in listings if l.street_address and "census_geocoder" not in (l.raw or {})]
    if not need_geo:
        return listings

    sem = asyncio.Semaphore(max_concurrent)

    async def _bounded(l: Listing) -> Listing:
        async with sem:
            return await enrich_census_geocoder(l)

    results = await asyncio.gather(*[_bounded(l) for l in need_geo], return_exceptions=True)

    idx = 0
    for i, listing in enumerate(listings):
        if listing.street_address and "census_geocoder" not in (listing.raw or {}):
            if idx < len(results) and not isinstance(results[idx], Exception):
                listings[i] = results[idx]
            idx += 1

    log.info("census_geocoder.batch_done",
             total=len(need_geo),
             enriched=sum(1 for r in results if not isinstance(r, Exception)))
    return listings
