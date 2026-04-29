"""Free geocoding fallback via OpenStreetMap Nominatim.

Used for listings the county GIS didn't return geometry for. Rate-limited to
1 req/sec per Nominatim's usage policy, with a small in-memory cache.
"""
from __future__ import annotations

import asyncio
from typing import Any

import structlog

from .http_client import client
from .models import Listing

log = structlog.get_logger()

NOMINATIM = "https://nominatim.openstreetmap.org/search"
UA = "ForeclosureScraperDashboard/1.0 (highwaymarketingco@gmail.com)"

_CACHE: dict[str, tuple[float, float] | None] = {}


async def _geocode_once(c, query: str) -> tuple[float, float] | None:
    if query in _CACHE:
        return _CACHE[query]
    try:
        r = await c.get(
            NOMINATIM,
            params={"q": query, "format": "jsonv2", "limit": 1, "countrycodes": "us"},
            headers={"User-Agent": UA},
        )
        if r.status_code != 200:
            _CACHE[query] = None
            return None
        data = r.json()
        if data and isinstance(data, list):
            try:
                lat = float(data[0]["lat"])
                lng = float(data[0]["lon"])
                _CACHE[query] = (lat, lng)
                return (lat, lng)
            except (KeyError, ValueError, TypeError):
                pass
    except Exception:
        pass
    _CACHE[query] = None
    return None


async def enrich(listings: list[Listing], rate_per_sec: float = 1.0) -> list[Listing]:
    """Fill missing lat/lng from Nominatim. Rate-limited per their policy."""
    targets = [
        li
        for li in listings
        if (li.latitude is None or li.longitude is None)
        and li.street_address
        and (li.zip_code or (li.city and li.state))
    ]
    if not targets:
        return listings

    async with client(timeout=20.0) as c:
        delay = max(1.0 / rate_per_sec, 1.0)
        matched = 0
        for li in targets:
            bits = [li.street_address, li.city or "", f"{li.state or ''} {li.zip_code or ''}".strip()]
            query = ", ".join(b for b in bits if b)
            res = await _geocode_once(c, query)
            if res:
                li.latitude, li.longitude = res
                matched += 1
            await asyncio.sleep(delay)

    log.info("geocode.done", queried=len(targets), matched=matched)
    return listings
