"""Redfin Data Center enrichment — ZIP-level market statistics.

The Redfin Data Center (https://www.redfin.com/news/data-center/) provides
free TSV downloads of housing market data at the ZIP, city, county, and metro
level. We download the ZIP-code-level market tracker once per run (cached
in memory), then look up each listing's ZIP code for:

  - Median sale price
  - Inventory (active listings)
  - Median days on market
  - Median sale price per sqft
  - New listings count

The TSV is large (~100MB) but we only parse it once and build a lookup dict
keyed by ZIP code. A single download per run is the politest approach.

This enricher fills: raw["market_stats"] dict with ZIP-level market data.
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

REDFIN_ZIP_URL = "https://redfin.com/data-library/download-data/zip_code_market_tracker.tsv"
_SEMAPHORE = asyncio.Semaphore(3)

# In-memory cache: {zip_code: {latest row fields}}
_ZIP_CACHE: dict[str, dict[str, Any]] | None = None
_ZIP_LOADED = False


async def _ensure_redfin_zip_data() -> bool:
    """Download and parse the Redfin ZIP-level TSV once. Returns False if unavailable."""
    global _ZIP_CACHE, _ZIP_LOADED
    if _ZIP_LOADED:
        return _ZIP_CACHE is not None
    _ZIP_LOADED = True

    try:
        async with client(timeout=90.0) as c:
            resp = await c.get(
                REDFIN_ZIP_URL,
                headers={"Accept": "text/tab-separated-values, text/plain, */*"},
            )
            if resp.status_code != 200:
                log.warning("redfin.download_failed", status=resp.status_code)
                return False
            text = resp.text
    except Exception as exc:
        log.warning("redfin.download_failed", error=str(exc)[:160])
        return False

    if not text or len(text) < 1000:
        log.warning("redfin.download_suspicious", size=len(text))
        return False

    _ZIP_CACHE = {}
    reader = csv.DictReader(io.StringIO(text), delimiter="\t")
    # Track the latest month per ZIP (TSV is sorted oldest-first)
    for row in reader:
        region = row.get("region", "") or row.get("Region", "")
        # Redfin ZIP rows have region like "Zip: 28202" or just the ZIP
        zip_code = None
        if region:
            # Extract 5-digit ZIP from region string
            for part in region.replace("Zip:", "").strip().split():
                if part.isdigit() and len(part) == 5:
                    zip_code = part
                    break
        if not zip_code:
            continue

        # Keep the latest row per ZIP (file is sorted by date)
        _ZIP_CACHE[zip_code] = {
            "median_sale_price": _safe_float(row.get("median_sale_price")),
            "median_sale_price_yoy": _safe_float(row.get("median_sale_price_yoy")),
            "homes_sold": _safe_float(row.get("homes_sold")),
            "inventory": _safe_float(row.get("inventory")),
            "median_dom": _safe_float(row.get("median_dom")),
            "median_dom_yoy": _safe_float(row.get("median_dom_yoy")),
            "median_ppsf": _safe_float(row.get("median_sale_ppsf")),
            "new_listings": _safe_float(row.get("new_listings")),
            "median_new_listing_ppsf": _safe_float(row.get("median_new_listings_ppsf")),
            "avg_sale_to_list": _safe_float(row.get("avg_sale_to_list")),
            "period_begin": row.get("period_begin", ""),
        }

    log.info("redfin.zip_loaded", zips=len(_ZIP_CACHE))
    return _ZIP_CACHE is not None and len(_ZIP_CACHE) > 0


def _safe_float(val: str | None) -> float | None:
    """Parse a TSV cell to float, returning None for blanks/errors."""
    if val is None or val == "" or val == "undefined":
        return None
    try:
        f = float(val)
        return f if f != 0 or val.strip().endswith("0") else None
    except (ValueError, TypeError):
        return None


async def enrich_redfin_datacenter(listing: Listing) -> Listing:
    """Enrich a listing with Redfin ZIP-level market statistics."""
    raw_update: dict[str, Any] = {"market_stats": {}}

    zip_code = (listing.zip_code or "").strip()[:5]
    if zip_code and len(zip_code) == 5:
        if _ZIP_CACHE and zip_code in _ZIP_CACHE:
            stats = _ZIP_CACHE[zip_code]
            # Only fill if we got real data
            if any(v is not None for v in stats.values()):
                raw_update["market_stats"] = {
                    "zip": zip_code,
                    "source": "redfin_data_center",
                    **stats,
                }

    listing.raw = {**listing.raw, **raw_update}
    return listing


async def enrich_batch_redfin_datacenter(
    listings: list[Listing], max_concurrent: int = 5
) -> list[Listing]:
    """Batch enrich listings with Redfin ZIP-level market statistics."""
    need_redfin = [l for l in listings if "market_stats" not in (l.raw or {})]
    if not need_redfin:
        return listings

    # Download the TSV once before processing
    await _ensure_redfin_zip_data()

    sem = asyncio.Semaphore(max_concurrent)

    async def _bounded(l: Listing) -> Listing:
        async with sem:
            return await enrich_redfin_datacenter(l)

    results = await asyncio.gather(
        *[_bounded(l) for l in need_redfin], return_exceptions=True
    )

    idx = 0
    for i, listing in enumerate(listings):
        if "market_stats" not in (listing.raw or {}):
            if idx < len(results) and not isinstance(results[idx], Exception):
                listings[i] = results[idx]
            idx += 1

    log.info(
        "redfin_datacenter.batch_done",
        total=len(need_redfin),
        enriched=sum(1 for r in results if not isinstance(r, Exception)),
    )
    return listings
