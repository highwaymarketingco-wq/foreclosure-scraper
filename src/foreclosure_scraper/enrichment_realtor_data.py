"""Realtor.com Data Library enrichment — county-level housing market data.

The Realtor.com Data Library (https://www.realtor.com/research/data/)
provides free TSV/CSV downloads of housing market statistics at the
metropolitan and county level. We download the county-level market data
once per run (cached in memory), then look up each listing's county for:

  - Median listing price
  - Median days on market
  - New listings count
  - Active listing count
  - Median listing price per sqft

The TSV is moderately sized (~5-10MB) and we parse it once into a lookup
dict keyed by (county_name, state).

This enricher fills: raw["housing_market"] dict with county-level housing data.
"""
from __future__ import annotations

import asyncio
import csv
import io
from typing import Any

import structlog

from .http_client import client
from .models import Listing

log = structlog.get_logger()

REALTOR_COUNTY_URL = (
    "https://www.realtor.com/research/data/realtor.com_county_market_data.tsv"
)
_SEMAPHORE = asyncio.Semaphore(3)

# In-memory cache: {(county_lower, state_upper): {latest row fields}}
_COUNTY_CACHE: dict[tuple[str, str], dict[str, Any]] | None = None
_COUNTY_LOADED = False


async def _ensure_realtor_county_data() -> bool:
    """Download and parse the Realtor.com county-level TSV once."""
    global _COUNTY_CACHE, _COUNTY_LOADED
    if _COUNTY_LOADED:
        return _COUNTY_CACHE is not None
    _COUNTY_LOADED = True

    try:
        async with client(timeout=90.0) as c:
            resp = await c.get(
                REALTOR_COUNTY_URL,
                headers={
                    "Accept": "text/tab-separated-values, text/plain, */*",
                },
            )
            if resp.status_code != 200:
                log.warning("realtor.download_failed", status=resp.status_code)
                return False
            text = resp.text
    except Exception as exc:
        log.warning("realtor.download_failed", error=str(exc)[:160])
        return False

    if not text or len(text) < 1000:
        log.warning("realtor.download_suspicious", size=len(text))
        return False

    _COUNTY_CACHE = {}
    reader = csv.DictReader(io.StringIO(text), delimiter="\t")
    for row in reader:
        county_name = (row.get("county_name") or row.get("County") or "").strip()
        state = (row.get("state") or row.get("State") or "").strip().upper()
        if not county_name or not state:
            continue

        # Normalize county name (strip "County" suffix, lowercase)
        county_lower = county_name.lower().replace(" county", "").strip()

        # Keep the latest row per county (file is sorted by month)
        _COUNTY_CACHE[(county_lower, state)] = {
            "median_listing_price": _safe_float(
                row.get("median_listing_price")
            ),
            "median_listing_price_yoy": _safe_float(
                row.get("median_listing_price_yoy")
            ),
            "median_days_on_market": _safe_float(
                row.get("median_days_on_market")
            ),
            "median_days_on_market_yoy": _safe_float(
                row.get("median_days_on_market_yoy")
            ),
            "new_listing_count": _safe_float(
                row.get("new_listing_count")
            ),
            "active_listing_count": _safe_float(
                row.get("active_listing_count")
            ),
            "median_listing_ppsf": _safe_float(
                row.get("median_listing_ppsf")
            ),
            "total_listing_count": _safe_float(
                row.get("total_listing_count")
            ),
            "pending_listing_count": _safe_float(
                row.get("pending_listing_count")
            ),
            "median_pending_listing_ppsf": _safe_float(
                row.get("median_pending_listing_ppsf")
            ),
            "month": row.get("month", ""),
        }

    log.info("realtor.county_loaded", counties=len(_COUNTY_CACHE))
    return _COUNTY_CACHE is not None and len(_COUNTY_CACHE) > 0


def _safe_float(val: str | None) -> float | None:
    if val is None or val == "" or val == "undefined":
        return None
    try:
        return float(val)
    except (ValueError, TypeError):
        return None


async def enrich_realtor_data(listing: Listing) -> Listing:
    """Enrich a listing with Realtor.com county-level housing market data."""
    raw_update: dict[str, Any] = {"housing_market": {}}

    county = (listing.county or "").strip().lower().replace(" county", "").strip()
    state = (listing.state or "").strip().upper()

    if county and state and _COUNTY_CACHE:
        key = (county, state)
        if key in _COUNTY_CACHE:
            stats = _COUNTY_CACHE[key]
            if any(v is not None for v in stats.values()):
                raw_update["housing_market"] = {
                    "county": county,
                    "state": state,
                    "source": "realtor.com_data_library",
                    **stats,
                }

    listing.raw = {**listing.raw, **raw_update}
    return listing


async def enrich_batch_realtor_data(
    listings: list[Listing], max_concurrent: int = 5
) -> list[Listing]:
    """Batch enrich listings with Realtor.com county-level housing data."""
    need_realtor = [l for l in listings if "housing_market" not in (l.raw or {})]
    if not need_realtor:
        return listings

    # Download the TSV once before processing
    await _ensure_realtor_county_data()

    sem = asyncio.Semaphore(max_concurrent)

    async def _bounded(l: Listing) -> Listing:
        async with sem:
            return await enrich_realtor_data(l)

    results = await asyncio.gather(
        *[_bounded(l) for l in need_realtor], return_exceptions=True
    )

    idx = 0
    for i, listing in enumerate(listings):
        if "housing_market" not in (listing.raw or {}):
            if idx < len(results) and not isinstance(results[idx], Exception):
                listings[i] = results[idx]
            idx += 1

    log.info(
        "realtor_data.batch_done",
        total=len(need_realtor),
        enriched=sum(1 for r in results if not isinstance(r, Exception)),
    )
    return listings
