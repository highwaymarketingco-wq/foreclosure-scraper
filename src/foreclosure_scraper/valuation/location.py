"""US Census ACS 5-year API location enrichment.

Per-listing ZIP → median HH income, median home value, owner-occupancy %, etc.
Cached in memory per run.

2026-10-15: the docstring used to say "free, no API key required for basic
usage" -- no longer true (found during the overnight VM run: every one of
this run's ~88 unique-ZIP calls got a 200 "missing_key.html" page instead of
real data, same CENSUS_API_KEY gate enrichment_census_rent.py/enrichment_
census_demographics.py already use). Gated the same way those two modules
are: skip the call entirely (no key, no request) rather than firing a call
every run that can only ever fail.
"""
from __future__ import annotations

import asyncio
import os
from typing import Any

import structlog

from ..http_client import client
from ..models import Listing

log = structlog.get_logger()


# https://api.census.gov/data/2023/acs/acs5/variables.html
ACS_URL = "https://api.census.gov/data/2023/acs/acs5"
VARS = {
    "B19013_001E": "median_household_income",
    "B25077_001E": "median_home_value",
    "B25003_002E": "owner_occupied",
    "B25003_001E": "total_occupied",
    "B23025_005E": "unemployed",
    "B23025_002E": "labor_force",
}

_CACHE: dict[str, dict[str, Any]] = {}


async def lookup_zip(zip_code: str) -> dict[str, Any] | None:
    """Return the dict of metrics for a 5-digit ZIP, or None if unavailable."""
    if not zip_code or len(zip_code) < 5:
        return None
    z = zip_code[:5]
    if z in _CACHE:
        return _CACHE[z]

    key = os.environ.get("CENSUS_API_KEY", "").strip()
    if not key:
        log.debug("location.no_api_key", hint="Get free key at https://api.census.gov/data/key_signup.html")
        _CACHE[z] = None
        return None

    params = {
        "get": ",".join(VARS.keys()),
        "for": f"zip code tabulation area:{z}",
        "key": key,
    }
    try:
        async with client(timeout=15.0, follow_redirects=True) as c:
            r = await c.get(ACS_URL, params=params)
            if r.status_code != 200:
                return None
            data = r.json()
    except Exception:
        return None

    # Response shape: [headers, [values...]]
    if not isinstance(data, list) or len(data) < 2:
        return None
    headers = data[0]
    values = data[1]
    out: dict[str, Any] = {}
    for h, v in zip(headers, values):
        if h in VARS:
            try:
                out[VARS[h]] = int(v) if v is not None else None
            except (ValueError, TypeError):
                out[VARS[h]] = None
    # Computed
    if out.get("owner_occupied") and out.get("total_occupied"):
        try:
            out["owner_occupied_pct"] = round(
                100 * out["owner_occupied"] / out["total_occupied"], 1
            )
        except (ZeroDivisionError, TypeError):
            pass
    if out.get("unemployed") is not None and out.get("labor_force"):
        try:
            out["unemployment_pct"] = round(100 * out["unemployed"] / out["labor_force"], 1)
        except (ZeroDivisionError, TypeError):
            pass

    _CACHE[z] = out
    return out


async def enrich(listings: list[Listing], concurrency: int = 6) -> list[Listing]:
    """Enrich each listing's raw['location'] with Census ACS metrics for its ZIP."""
    sem = asyncio.Semaphore(concurrency)
    matched = 0

    async def one(li: Listing) -> None:
        nonlocal matched
        if not li.zip_code:
            return
        async with sem:
            metrics = await lookup_zip(li.zip_code)
        if not metrics:
            return
        if not isinstance(li.raw, dict):
            li.raw = {}
        li.raw.setdefault("location", {}).update(metrics)
        matched += 1

    # Dedupe ZIPs first to minimize API calls
    seen_zips: set[str] = set()
    unique_targets: list[Listing] = []
    for li in listings:
        z = li.zip_code or ""
        if not z or z[:5] in seen_zips:
            continue
        seen_zips.add(z[:5])
        unique_targets.append(li)

    # Pre-warm cache by hitting unique ZIPs
    await asyncio.gather(*(one(li) for li in unique_targets))
    # Now apply cached values to all listings sharing those ZIPs
    for li in listings:
        if not li.zip_code:
            continue
        cached = _CACHE.get(li.zip_code[:5])
        if not cached:
            continue
        if not isinstance(li.raw, dict):
            li.raw = {}
        li.raw.setdefault("location", {}).update(cached)

    log.info("location.enriched", zips_queried=len(unique_targets), matched=matched)
    return listings
