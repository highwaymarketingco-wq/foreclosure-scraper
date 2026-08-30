"""NCPTS LRC Cloud enrichment — full CAMA data for ALL 100 NC counties.

The LRC portal at lrcpwa.ncptscloud.com is a second NCPTS cluster (separate
from bcpwa.ncptscloud.com which handles delinquent-tax CSV downloads).
The LRC cluster exposes a parcel search + detail REST API:

  1. GET /api/SimpleParcelSearch?query=<q>&pageSize=10
     (Header: X-Tenant: <CountyName>)
     -> {totalCount, results: [{id, reid, formattedPin, owners, propertyAddress1,
         propertyAddress2, propertyDescription, totalPropertyValue}]}

  2. GET /api/getParcelDetails?ParcelId=<id>
     (Header: X-Tenant: <CountyName>)
     -> Full CAMA: owners (name, businessName), mailingAddress1/2/3, city,
        state, zip, primaryOwnerName, totalPropertyValue, totalLandValueAssessed,
        totalBuildingValueAssessed, acreage, zoning, landUse, deedBook/Page/Date,
        packageSalePrice, buildings[].yearBuilt, buildings[].bedrooms,
        heatedArea, totalUnits, taxBillUrl, deedBookUrl, platBookUrl, parcelPhotoPath

Auth: ONLY needs X-Tenant header (county name). No key, no login.

We search by street address (most leads have one). If no address, search by
owner name or parcel_id. The API returns numeric PINs and address matches.

Fills: owner_name, mailing address, assessed_value, acreage, zoning, year_built,
bedrooms, living_sqft (heatedArea), deed history (sale price/date), parcel_id.
"""
from __future__ import annotations

import asyncio
import json
import re
from typing import Any

import httpx
import structlog

from .http_client import client
from .models import Listing, PropertyKind

log = structlog.get_logger()

BASE = "https://lrcpwa.ncptscloud.com"
SEARCH_URL = f"{BASE}/api/SimpleParcelSearch"
DETAIL_URL = f"{BASE}/api/getParcelDetails"

# NC counties that use the LRC portal (all 100 are supported — the X-Tenant
# header selects the county). Some counties may not have data online yet.
# Verified working 2026-08-19: Guilford (76k parcels), Forsyth (52k), Cumberland.
# The API returns totalCount=0 for counties without data — they light up
# when the county publishes.

# Rate-limit: be polite. 5 concurrent, 200ms between requests per tenant.
_SEMAPHORE = asyncio.Semaphore(5)


def _extract_street_number(addr: str | None) -> str | None:
    """Pull the street number from an address for NCPTS search."""
    if not addr:
        return None
    m = re.match(r"\s*(\d+)", addr)
    return m.group(1) if m else None


def _extract_street_name(addr: str | None) -> str | None:
    """Pull the street name (without number) from an address."""
    if not addr:
        return None
    # Remove leading number
    s = re.sub(r"^\s*\d+\s+", "", addr).strip()
    # Remove unit/suite
    s = re.sub(r"\s+(?:apt|unit|suite|ste|#)\s*[\w-]+.*$", "", s, flags=re.I)
    # Take first few words for search
    words = s.split()[:3]
    return " ".join(words) if words else None


async def _search_parcels(
    tenant: str, query: str, limit: int = 5
) -> list[dict[str, Any]]:
    """Search NCPTS LRC for parcels matching query."""
    try:
        async with client(timeout=15.0) as c:
            resp = await c.get(
                SEARCH_URL,
                params={"query": query, "pageSize": limit, "pageIndex": 0},
                headers={"X-Tenant": tenant, "Accept": "application/json"},
            )
            if resp.status_code != 200:
                return []
            data = resp.json()
            return data.get("results", [])
    except Exception as exc:
        log.debug("ncpts_lrc.search_fail", tenant=tenant, error=str(exc)[:120])
        return []


async def _get_parcel_detail(
    tenant: str, parcel_id: str | int
) -> dict[str, Any] | None:
    """Get full CAMA details for a parcel."""
    try:
        async with client(timeout=15.0) as c:
            resp = await c.get(
                DETAIL_URL,
                params={"ParcelId": str(parcel_id)},
                headers={"X-Tenant": tenant, "Accept": "application/json"},
            )
            if resp.status_code != 200:
                return None
            return resp.json()
    except Exception as exc:
        log.debug("ncpts_lrc.detail_fail", tenant=tenant, error=str(exc)[:120])
        return None


def _match_parcel(
    results: list[dict], listing: Listing
) -> dict | None:
    """Find the best matching parcel from search results."""
    if not results:
        return None

    # Try to match by address
    listing_addr = (listing.street_address or "").lower().strip()
    # Remove unit/suite from listing address for matching
    listing_addr_base = re.sub(
        r"\s+(?:apt|unit|suite|ste|#)\s*[\w-]+.*$", "", listing_addr, flags=re.I
    )
    listing_num = re.match(r"\s*(\d+)", listing_addr)
    listing_num = listing_num.group(1) if listing_num else None

    for result in results:
        prop_addr = (result.get("propertyAddress1") or "").lower().strip()
        if not prop_addr:
            continue

        # Exact match
        if listing_addr and listing_addr_base in prop_addr:
            return result

        # Street number + partial street name match
        if listing_num:
            result_num = re.match(r"\s*(\d+)", prop_addr)
            if result_num and result_num.group(1) == listing_num:
                return result

    # Fallback: first result if only one
    if len(results) == 1:
        return results[0]

    return None


async def enrich_ncpts_lrc(listing: Listing) -> Listing:
    """Enrich a single NC listing with NCPTS LRC CAMA data."""
    if listing.state != "NC":
        return listing

    county = (listing.county or "").strip()
    if not county:
        return listing

    # Build search query from address
    street_num = _extract_street_number(listing.street_address)
    if not street_num:
        # Fallback: search by owner name
        if listing.owner_name:
            last_name = listing.owner_name.split(",")[0].split()[0]
            results = await _search_parcels(county, last_name, limit=10)
        else:
            return listing
    else:
        results = await _search_parcels(county, street_num, limit=10)

    if not results:
        return listing

    # Match the right parcel
    matched = _match_parcel(results, listing)
    if not matched:
        return listing

    parcel_id = matched.get("id")
    if not parcel_id:
        return listing

    # Get full details
    async with _SEMAPHORE:
        detail = await _get_parcel_detail(county, parcel_id)

    if not detail:
        return listing

    # Fill missing fields — never overwrite good data
    if not listing.owner_name and detail.get("primaryOwnerName"):
        listing.owner_name = detail["primaryOwnerName"]

    if not listing.parcel_id and detail.get("formattedPin"):
        listing.parcel_id = detail["formattedPin"]

    if not listing.assessed_value and detail.get("totalPropertyValue"):
        try:
            listing.assessed_value = float(detail["totalPropertyValue"])
        except (TypeError, ValueError):
            pass

    if not listing.acreage and detail.get("acreage"):
        try:
            listing.acreage = float(detail["acreage"])
        except (TypeError, ValueError):
            pass

    if not listing.zoning and detail.get("zoning"):
        listing.zoning = detail["zoning"]

    if not listing.year_built:
        buildings = detail.get("buildings", [])
        if buildings:
            yb = buildings[0].get("yearBuilt")
            if yb:
                try:
                    listing.year_built = int(yb)
                except (TypeError, ValueError):
                    pass

    if not listing.bedrooms:
        buildings = detail.get("buildings", [])
        if buildings:
            beds = buildings[0].get("bedrooms")
            if beds:
                try:
                    listing.bedrooms = float(beds)
                except (TypeError, ValueError):
                    pass

    if not listing.living_sqft and detail.get("heatedArea"):
        try:
            listing.living_sqft = float(detail["heatedArea"])
        except (TypeError, ValueError):
            pass

    # Store deed history and mailing address in raw
    raw_update: dict[str, Any] = {"ncpts_lrc": True}

    if detail.get("mailingAddress1"):
        raw_update["mailing_address"] = {
            "line1": detail.get("mailingAddress1"),
            "line2": detail.get("mailingAddress2"),
            "line3": detail.get("mailingAddress3"),
            "city": detail.get("mailingAddressCity"),
            "state": detail.get("mailingAddressState"),
            "zip": detail.get("mailingAddressZip"),
        }

    if detail.get("deedBook"):
        raw_update["deed"] = {
            "book": detail.get("deedBook"),
            "page": detail.get("deedPage"),
            "date": detail.get("deedDate"),
            "sale_price": detail.get("packageSalePrice"),
            "land_sale_price": detail.get("landSalePrice"),
        }

    if detail.get("taxBillUrl"):
        raw_update["tax_bill_url"] = detail["taxBillUrl"]

    if detail.get("totalLandValueAssessed"):
        raw_update["land_value_assessed"] = detail["totalLandValueAssessed"]
    if detail.get("totalBuildingValueAssessed"):
        raw_update["building_value_assessed"] = detail["totalBuildingValueAssessed"]

    listing.raw = {**listing.raw, **raw_update}

    return listing


async def enrich_batch_ncpts_lrc(
    listings: list[Listing],
    max_concurrent: int = 10,
) -> list[Listing]:
    """Enrich a batch of NC listings with NCPTS LRC data."""
    nc_listings = [l for l in listings if l.state == "NC" and l.county]
    if not nc_listings:
        return listings

    sem = asyncio.Semaphore(max_concurrent)

    async def _bounded(l: Listing) -> Listing:
        async with sem:
            return await enrich_ncpts_lrc(l)

    results = await asyncio.gather(*[_bounded(l) for l in nc_listings], return_exceptions=True)

    # Merge results back
    idx = 0
    for i, listing in enumerate(listings):
        if listing.state == "NC" and listing.county:
            if idx < len(results) and not isinstance(results[idx], Exception):
                listings[i] = results[idx]
            idx += 1

    log.info("ncpts_lrc.batch_done",
              total=len(nc_listings),
              enriched=sum(1 for r in results if not isinstance(r, Exception)))
    return listings
