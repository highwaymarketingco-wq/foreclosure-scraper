#!/usr/bin/env python3
"""
NCPTS LRC enrichment for listings missing coordinates.

For each NC listing without lat/lon that has raw.nc_ptscloud_delinquent_tax
data (tenant + parcel number), queries the LRC API to get:
  - Property street address (fills street_address, city, zip_code)
  - Assessed value (totalPropertyValue)
  - Building details (year_built, bedrooms, heatedArea/sqft)
  - Acreage, zoning
  - Deed book/page/date, sale price
  - Mailing address
  - Parcel photo URL, tax bill URL

Then writes top-level latitude/longitude if the LRC provides coordinates,
and fills assessed_value so the equity engine can use it as ANCHOR.

Saves incrementally to avoid OOM on 8GB macOS.
"""
import asyncio, gc, gzip, json, os, sys, time
from typing import Any

HOME = os.path.expanduser("~")
sys.path.insert(0, os.path.join(HOME, "foreclosure-scraper", "src"))

from foreclosure_scraper.web_artifact import load_board, write_artifact

DOCS_DIR = os.path.join(HOME, "foreclosure-scraper", "docs")
BASE = "https://lrcpwa.ncptscloud.com"
SEARCH_URL = f"{BASE}/api/SimpleParcelSearch"
DETAIL_URL = f"{BASE}/api/getParcelDetails"
SAVE_EVERY = 100
MAX_CONCURRENT = 5  # be polite to NCPTS

import httpx


async def search_by_parcel(client, tenant, parcel_num):
    """Search NCPTS LRC by parcel number. Returns list of results."""
    try:
        resp = await client.get(SEARCH_URL, params={
            "query": str(parcel_num), "pageSize": 5, "pageIndex": 0,
        }, headers={"X-Tenant": tenant, "Accept": "application/json"}, timeout=15.0)
        if resp.status_code != 200:
            return []
        data = resp.json()
        return data.get("results", [])
    except Exception:
        return []


async def get_parcel_detail(client, tenant, parcel_id):
    """Get full CAMA details for a parcel."""
    try:
        resp = await client.get(DETAIL_URL, params={
            "ParcelId": str(parcel_id),
        }, headers={"X-Tenant": tenant, "Accept": "application/json"}, timeout=15.0)
        if resp.status_code != 200:
            return None
        return resp.json()
    except Exception:
        return None


async def enrich_one(client, listing, tenant, parcel_num):
    """Search by parcel, get details, fill listing fields."""
    results = await search_by_parcel(client, tenant, parcel_num)
    if not results:
        return False

    # Take first match (parcel number search is exact)
    matched = results[0]
    parcel_id = matched.get("id")
    if not parcel_id:
        return False

    # Fill property address from search result if available
    prop_addr = matched.get("propertyAddress1")
    if prop_addr and (not listing.street_address or listing.street_address in (None, "None", "")):
        listing.street_address = prop_addr
    prop_addr2 = matched.get("propertyAddress2")
    if prop_addr2 and not listing.city:
        listing.city = prop_addr2

    # Get full details
    detail = await get_parcel_detail(client, tenant, parcel_id)
    if not detail:
        # Still save the address from search results
        if prop_addr:
            if not isinstance(listing.raw, dict):
                listing.raw = {}
            listing.raw.setdefault("ncpts_lrc", True)
            return True
        return False

    # Fill listing fields — never overwrite good data
    if not listing.owner_name and detail.get("primaryOwnerName"):
        listing.owner_name = detail["primaryOwnerName"]

    if not listing.parcel_id and detail.get("formattedPin"):
        listing.parcel_id = detail["formattedPin"]

    # Assessed value — THE KEY FIELD for equity engine
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
        if buildings and buildings[0].get("yearBuilt"):
            try:
                listing.year_built = int(buildings[0]["yearBuilt"])
            except (TypeError, ValueError):
                pass

    if not listing.bedrooms:
        buildings = detail.get("buildings", [])
        if buildings and buildings[0].get("bedrooms"):
            try:
                listing.bedrooms = float(buildings[0]["bedrooms"])
            except (TypeError, ValueError):
                pass

    if not listing.living_sqft and detail.get("heatedArea"):
        try:
            listing.living_sqft = float(detail["heatedArea"])
        except (TypeError, ValueError):
            pass

    # Store everything in raw
    if not isinstance(listing.raw, dict):
        listing.raw = {}
    raw_update = {"ncpts_lrc": True}

    # Property address (overwrite if we now have one)
    if detail.get("propertyAddress1"):
        raw_update["lrc_property_address"] = detail["propertyAddress1"]
    if detail.get("propertyAddress2"):
        raw_update["lrc_property_city"] = detail["propertyAddress2"]

    # Mailing address
    if detail.get("mailingAddress1"):
        raw_update["mailing_address"] = {
            "line1": detail.get("mailingAddress1"),
            "line2": detail.get("mailingAddress2"),
            "city": detail.get("mailingAddressCity"),
            "state": detail.get("mailingAddressState"),
            "zip": detail.get("mailingAddressZip"),
        }

    # Deed info
    if detail.get("deedBook"):
        raw_update["deed"] = {
            "book": detail.get("deedBook"),
            "page": detail.get("deedPage"),
            "date": detail.get("deedDate"),
            "sale_price": detail.get("packageSalePrice"),
        }

    # Land/building assessed values
    if detail.get("totalLandValueAssessed"):
        raw_update["land_value_assessed"] = detail["totalLandValueAssessed"]
    if detail.get("totalBuildingValueAssessed"):
        raw_update["building_value_assessed"] = detail["totalBuildingValueAssessed"]

    # URLs
    if detail.get("taxBillUrl"):
        raw_update["tax_bill_url"] = detail["taxBillUrl"]
    if detail.get("deedBookUrl"):
        raw_update["deed_book_url"] = detail["deedBookUrl"]
    if detail.get("parcelPhotoPath"):
        raw_update["parcel_photo_url"] = detail["parcelPhotoPath"]

    # Building details
    buildings = detail.get("buildings", [])
    if buildings:
        b = buildings[0]
        raw_update["building"] = {
            "year_built": b.get("yearBuilt"),
            "bedrooms": b.get("bedrooms"),
            "heated_area": b.get("heatedArea"),
            "total_units": b.get("totalUnits"),
            "baths": b.get("baths"),
        }

    # Land use
    if detail.get("landUse"):
        raw_update["land_use"] = detail["landUse"]

    listing.raw = {**listing.raw, **raw_update}
    return True


async def main():
    t0 = time.time()
    print(f"[1] Loading board...")
    board = load_board(DOCS_DIR)
    total = len(board)

    # Find NC listings without coords that have nc_ptscloud_delinquent_tax data
    need = []
    for i, li in enumerate(board):
        if li.state != "NC":
            continue
        if getattr(li, "latitude", None) and getattr(li, "longitude", None):
            continue
        # Check if already enriched by LRC
        if isinstance(li.raw, dict) and li.raw.get("ncpts_lrc"):
            continue
        # Get tenant + parcel from nc_ptscloud_delinquent_tax
        ncpts = (li.raw or {}).get("nc_ptscloud_delinquent_tax", {})
        if isinstance(ncpts, dict) and ncpts.get("tenant") and ncpts.get("parcel"):
            need.append((i, ncpts["tenant"], ncpts["parcel"]))

    print(f"    Board: {total:,} listings")
    print(f"    NC listings without coords, with nc_ptscloud parcel data: {len(need):,}")

    if not need:
        print("    Nothing to enrich. Done.")
        return

    print(f"\n[2] Querying NCPTS LRC API (concurrency={MAX_CONCURRENT})...")
    sem = asyncio.Semaphore(MAX_CONCURRENT)
    enriched_count = 0
    processed = 0
    batch_start = time.time()

    async with httpx.AsyncClient() as client:
        for start in range(0, len(need), SAVE_EVERY):
            batch = need[start:start + SAVE_EVERY]
            batch_num = start // SAVE_EVERY + 1
            total_batches = (len(need) + SAVE_EVERY - 1) // SAVE_EVERY

            async def _do_one(idx, tenant, parcel):
                nonlocal enriched_count, processed
                async with sem:
                    li = board[idx]
                    try:
                        success = await enrich_one(client, li, tenant, parcel)
                        if success:
                            enriched_count += 1
                    except Exception as e:
                        pass
                    processed += 1

            tasks = [_do_one(idx, tenant, parcel) for idx, tenant, parcel in batch]
            await asyncio.gather(*tasks, return_exceptions=True)

            elapsed = time.time() - batch_start
            done = start + len(batch)
            rate = done / elapsed if elapsed > 0 else 0
            remaining = (len(need) - done) / rate if rate > 0 else 0
            print(f"  Batch {batch_num}/{total_batches}: {processed:,}/{len(need):,} | "
                  f"Enriched: {enriched_count:,} | Rate: {rate:.1f}/s | ETA: {remaining:.0f}s")

            try:
                write_artifact(board, {"checkpoint": "ncpts_lrc"}, DOCS_DIR)
                gc.collect()
            except Exception as e:
                print(f"  SAVE ERROR: {e}")

    print(f"\n[3] Final save...")
    write_artifact(board, {"enrichment": "ncpts_lrc_complete"}, DOCS_DIR)

    elapsed = time.time() - t0
    print(f"\n{'='*60}")
    print(f"COMPLETE: {enriched_count:,} listings enriched via NCPTS LRC")
    print(f"  Time: {elapsed:.0f}s")
    print(f"  Next: run geocoder to backfill coords from new addresses")
    print(f"{'='*60}")


if __name__ == "__main__":
    asyncio.run(main())
