#!/usr/bin/env python3
"""Reverse-lookup street addresses from parcel IDs via county GIS layers.

For the ~5,085 listings that have a parcel_id but no street_address, this
script queries the county ArcGIS layer's situs field using the parcel_id,
filling in the missing street address (and city/zip where available).

Reuses COUNTY_GIS configs from enrichment_owner_mailing.py.

Usage:
    python3.12 scripts/parcel_reverse_lookup.py [--dry-run] [--limit N]
"""
from __future__ import annotations

import asyncio
import json
import gzip
import os
import re
import sys
import time
from collections import Counter

# Path setup
sys.path.insert(0, os.path.expanduser("~/foreclosure-scraper/src"))
sys.path.insert(0, os.path.expanduser("~/foreclosure-scraper/.venv/lib/python3.12/site-packages"))

import httpx
from foreclosure_scraper.models import Listing
from foreclosure_scraper.enrichment_owner_mailing import (
    COUNTY_GIS, _county_key, _pid_variants, _norm,
)

BOARD_PATH = os.path.expanduser("~/foreclosure-scraper/docs/listings.json.gz")
OUTPUT_PATH = os.path.expanduser("~/foreclosure-scraper/docs/listings.json")


async def _query_parcel_situs(
    http: httpx.AsyncClient,
    base_url: str,
    spec: dict,
    parcel_id: str,
) -> dict | None:
    """Query a county ArcGIS layer for the situs address of a parcel."""
    parcel_field = spec.get("parcel", "pin")
    situs_fields = spec.get("situs", [])
    if not situs_fields:
        return None

    # Build WHERE clause from parcel ID variants
    variants = _pid_variants(parcel_id)
    if not variants:
        return None

    where_parts = []
    for v in variants:
        v_escaped = v.replace("'", "''")
        where_parts.append(f"UPPER({parcel_field}) LIKE '%{v_escaped.upper()}%'")
    where_clause = " OR ".join(where_parts)

    out_fields = ",".join([parcel_field] + situs_fields)
    if spec.get("where_suffix"):
        where_clause = f"({where_clause}) AND {spec['where_suffix']}"

    params = {
        "f": "json",
        "where": where_clause,
        "outFields": out_fields,
        "returnGeometry": "false",
        "resultRecordCount": 5,
    }
    url = base_url.rstrip("/") + "/query"
    try:
        resp = await http.get(url, params=params, timeout=20)
        if resp.status_code != 200:
            return None
        data = resp.json()
        feats = data.get("features", [])
        if not feats:
            return None
        # Take first feature
        attrs = feats[0].get("attributes", {})
        situs_parts = []
        for f in situs_fields:
            v = attrs.get(f)
            if v and str(v).strip():
                situs_parts.append(str(v).strip())
        situs = " ".join(situs_parts).strip()
        if not situs or len(situs) < 5:
            return None
        # Clean up common GIS address quirks
        situs = re.sub(r"\s+", " ", situs).strip()
        return {"situs": situs, "attrs": attrs}
    except Exception:
        return None


async def main(dry_run: bool = False, limit: int | None = None):
    print("Loading board...")
    with gzip.open(BOARD_PATH, "rt") as f:
        raw_listings = json.load(f)
    print(f"  {len(raw_listings)} listings loaded")

    # Find targets: have parcel_id, no street_address
    targets_raw = [li for li in raw_listings if li.get("parcel_id") and not li.get("street_address")]
    print(f"  {len(targets_raw)} targets (parcel_id, no street_address)")

    if limit:
        targets_raw = targets_raw[:limit]
        print(f"  Limited to {len(targets_raw)}")

    # Group by county for efficient querying
    by_county: dict[tuple[str, str], list[dict]] = {}
    for li in targets_raw:
        state = li.get("state", "")
        county = (li.get("county") or "").strip().title()
        county = {"Mcdowell": "McDowell", "Mccormick": "McCormick"}.get(county, county)
        key = (state, county)
        by_county.setdefault(key, []).append(li)

    # Check which counties have GIS configs
    has_gis = 0
    no_gis = 0
    for (state, county) in sorted(by_county.keys()):
        ckey = f"{state}:{county}"
        if ckey in COUNTY_GIS:
            spec = COUNTY_GIS[ckey]
            n = len(by_county[(state, county)])
            has_gis += n
            situs = spec.get("situs", [])
            print(f"  {ckey}: {n} listings, situs_fields={situs}")
        else:
            n = len(by_county[(state, county)])
            no_gis += n
            print(f"  {ckey}: {n} listings, NO GIS CONFIG")

    print(f"\nHas GIS config: {has_gis}, No GIS: {no_gis}")

    # Query each county
    resolved = 0
    failed = 0
    no_config = 0
    county_stats = Counter()

    async with httpx.AsyncClient(timeout=25.0, headers={"User-Agent": "Mozilla/5.0"}) as http:
        for (state, county), group in sorted(by_county.items()):
            ckey = f"{state}:{county}"
            spec = COUNTY_GIS.get(ckey)
            if not spec:
                no_config += len(group)
                county_stats[f"{ckey}:no_config"] = len(group)
                continue

            base_url = spec.get("url", "")
            situs_fields = spec.get("situs", [])
            if not situs_fields:
                no_config += len(group)
                county_stats[f"{ckey}:no_situs"] = len(group)
                continue

            print(f"\n--- {ckey}: {len(group)} listings ---")
            sem = asyncio.Semaphore(10)

            async def one(li: dict) -> bool:
                async with sem:
                    pid = li.get("parcel_id", "")
                    result = await _query_parcel_situs(http, base_url, spec, pid)
                    if result:
                        situs = result["situs"]
                        # Basic sanity check: must start with a number
                        if re.match(r"^\d+\s", situs) or len(situs) > 8:
                            li["street_address"] = situs
                            # Try to extract zip from attrs
                            attrs = result.get("attrs", {})
                            for zfield in ["Zip", "Zipcode", "ZIP", "OWZIPA", "ZIP_CODE", "owner_zip"]:
                                zval = attrs.get(zfield)
                                if zval and str(zval).strip() and str(zval) != "0":
                                    li["zip_code"] = str(zval).strip()[:5]
                                    break
                            for cfield in ["City", "CITY", "OWCITY", "owner_citystate"]:
                                cval = attrs.get(cfield)
                                if cval and str(cval).strip():
                                    li["city"] = str(cval).strip()
                                    break
                            return True
                    return False

            results = await asyncio.gather(*[one(li) for li in group], return_exceptions=True)
            county_resolved = sum(1 for r in results if r is True)
            county_failed = sum(1 for r in results if r is False)
            county_err = sum(1 for r in results if isinstance(r, Exception))
            resolved += county_resolved
            failed += county_failed
            county_stats[f"{ckey}:resolved"] = county_resolved
            county_stats[f"{ckey}:failed"] = county_failed
            if county_err:
                county_stats[f"{ckey}:error"] = county_err
            print(f"  resolved={county_resolved}, failed={county_failed}, error={county_err}")

    print(f"\n=== SUMMARY ===")
    print(f"Total targets: {len(targets_raw)}")
    print(f"Resolved (address filled): {resolved}")
    print(f"Failed (no match): {failed}")
    print(f"No GIS config: {no_config}")
    print(f"Success rate: {resolved}/{resolved+failed} = {resolved/max(resolved+failed,1)*100:.1f}%" if resolved + failed else "N/A")

    if dry_run:
        print("\n[DRY RUN] Not writing board.")
        return

    if resolved > 0:
        print(f"\nWriting board to {OUTPUT_PATH}...")
        # Write uncompressed (the board writer expects this)
        with open(OUTPUT_PATH, "w") as f:
            json.dump(raw_listings, f)
        print(f"  Written {len(raw_listings)} listings")

        # Also write gzipped
        with gzip.open(BOARD_PATH, "wt") as f:
            json.dump(raw_listings, f)
        print(f"  Written gzipped")

    print("\nDone.")


if __name__ == "__main__":
    dry = "--dry-run" in sys.argv
    limit = None
    for i, arg in enumerate(sys.argv):
        if arg == "--limit" and i + 1 < len(sys.argv):
            limit = int(sys.argv[i + 1])
    asyncio.run(main(dry_run=dry, limit=limit))
