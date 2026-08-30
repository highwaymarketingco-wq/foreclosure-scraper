#!/usr/bin/env python3
"""Catchup geocoder for listings with addresses but no lat/lon.

Uses the free Census Bureau geocoder API (no key required):
  https://geocoding.geo.census.gov/geocoder/geographies/onelineaddress

Processes in batches of 1000 (API limit). Falls back to county-seat
centroid lookup for listings with no address but a county.

Usage:
    python3.12 scripts/geocode_catchup.py [--dry-run]

Writes results back to the board via web_artifact.load_board/write_artifact.
"""
from __future__ import annotations

import argparse
import gzip
import json
import os
import sys
import time
from pathlib import Path

import structlog

log = structlog.get_logger()

# Census geocoder — free, no API key, 1000-address batches
CENSUS_GEOCODE_URL = "https://geocoding.geo.census.gov/geocoder/geographies/onelineaddress"
CENSUS_BATCH_URL = "https://geocoding.geo.census.gov/geocoder/geographies/addressbatch"

# County-seat centroids (lat, lon) — fallback for listings with no address
# but a known county. Used when geocoder returns no match.
COUNTY_SEATS = {
    # NC
    "NC:Buncombe": (35.5951, -82.5515),      # Asheville
    "NC:Henderson": (35.3185, -82.4609),     # Hendersonville
    "NC:Rutherford": (35.2654, -81.9646),    # Rutherfordton
    "NC:McDowell": (35.6208, -82.2096),      # Marion
    "NC:Transylvania": (35.2246, -82.7346),  # Brevard
    "NC:Burke": (35.7476, -81.7043),        # Morganton
    "NC:Polk": (35.2382, -82.1990),         # Columbus
    "NC:New Hanover": (34.1808, -77.9462),   # Wilmington
    "NC:Brunswick": (33.8908, -78.2569),    # Bolivia
    "NC:Cleveland": (35.2330, -81.3406),    # Shelby
    "NC:Gaston": (35.2657, -81.1812),       # Gastonia
    "NC:Lincoln": (35.4737, -81.2198),      # Lincolnton
    "NC:Catawba": (35.5512, -81.2234),      # Newton
    "NC:Alexander": (35.8260, -81.1848),     # Taylorsville
    "NC:Iredell": (35.5926, -80.8823),      # Statesville
    "NC:Watauga": (36.1940, -81.6657),      # Boone
    "NC:Avery": (36.0920, -81.8668),         # Newland
    "NC:Mitchell": (35.9150, -82.1582),     # Bakersville
    "NC:Yancey": (35.7390, -82.2982),       # Burnsville
    "NC:Madison": (35.7390, -82.5620),      # Marshall
    # SC
    "SC:Spartanburg": (34.9496, -81.9321),   # Spartanburg
    "SC:Greenville": (34.8526, -82.3940),   # Greenville
    "SC:Pickens": (34.8680, -82.7046),      # Pickens
    "SC:Oconee": (34.7040, -83.0630),       # Walhalla
    "SC:Anderson": (34.5034, -82.6501),     # Anderson
    "SC:Cherokee": (35.0540, -81.6180),      # Gaffney
    "SC:Cherokee": (35.0540, -81.6180),      # Gaffney (dup for safety)
    "SC:Georgetown": (33.5465, -79.2870),   # Georgetown
    "SC:Charleston": (32.7846, -79.9409),   # Charleston
    "SC:Beaufort": (32.4370, -80.6742),     # Beaufort
    "SC:Horry": (33.8360, -79.0946),        # Conway
    "SC:Laurens": (34.4754, -82.0165),      # Laurens
    "SC:Union": (34.6265, -81.6170),        # Union
    "SC:York": (34.9290, -81.1812),         # York
    "SC:Chester": (34.6925, -81.2118),      # Chester
    "SC:Lancaster": (34.7200, -80.7720),    # Lancaster
    "SC:Fairfield": (34.3950, -81.0920),    # Winnsboro
    "SC:Newberry": (34.2790, -81.6180),     # Newberry
    "SC:Lexington": (33.9910, -81.2360),    # Lexington
    "SC:Richland": (34.0007, -80.9027),     # Columbia
    "SC:Sumter": (33.9207, -80.3415),       # Sumter
    "SC:Clarendon": (33.6590, -80.2140),    # Manning
    "SC:Orangeburg": (33.4910, -80.8520),  # Orangeburg
    "SC:Colleton": (32.8440, -80.6780),     # Walterboro
    "SC:Hampton": (32.8360, -81.0940),      # Hampton
    "SC:Jasper": (32.3920, -80.6980),       # Ridgeland
    "SC:Aiken": (33.5490, -81.7200),        # Aiken
    "SC:Edgefield": (33.7890, -81.9280),    # Edgefield
    "SC:Abbeville": (34.0820, -82.3790),    # Abbeville
    "SC:Greenwood": (34.1860, -82.1620),    # Greenwood
    "SC:McCormick": (33.9020, -82.2930),    # McCormick
}


def build_address_string(li: dict) -> str | None:
    """Build a one-line address for geocoding from listing fields."""
    addr = li.get("street_address") or ""
    if not addr or not addr.strip():
        return None
    city = li.get("city") or ""
    state = li.get("state") or ""
    zip_code = li.get("zip_code") or ""

    # Build "123 Main St, City, ST 12345"
    parts = [addr.strip()]
    if city:
        parts.append(city.strip())
    if state:
        state_str = state.strip()
        if city:
            parts[-1] = f"{city.strip()}, {state_str}"
        else:
            parts.append(state_str)
    if zip_code:
        parts.append(zip_code.strip()[:5])

    return ", ".join(parts)


def geocode_batch_census(addresses: list[str]) -> dict[str, tuple[float, float]]:
    """Geocode a batch of addresses via Census batch API (CSV format).

    Returns dict mapping address -> (lat, lon).
    """
    import csv as csv_mod
    import io
    import httpx

    results: dict[str, tuple[float, float]] = {}

    # Census batch API expects a CSV file upload
    # Format: id, street_address, city, state, zip
    lines = []
    for i, addr_str in enumerate(addresses):
        parts = addr_str.split(", ")
        street = parts[0] if parts else ""
        city = parts[1] if len(parts) > 1 else ""
        state_zip = parts[2] if len(parts) > 2 else ""
        state = state_zip.split()[0] if state_zip else ""
        zip_code = state_zip.split()[1] if len(state_zip.split()) > 1 else ""
        lines.append(f"{i},{street},{city},{state},{zip_code}")

    csv_data = "\n".join(lines)

    try:
        files = {"addressFile": ("addrs.csv", csv_data, "text/csv")}
        data = {
            "benchmark": "Public_AR_Current",
            "vintage": "Current_Current",
            "format": "csv",  # CSV, not JSON
        }
        r = httpx.post(CENSUS_BATCH_URL, data=data, files=files, timeout=120.0)
        if r.status_code != 200:
            log.error("geocode_batch.http_error", status=r.status_code, body=r.text[:200])
            return results

        # Parse CSV response:
        # "id","input_addr","status","match_type","matched_addr","coordinates",
        # "geoid",... (fields vary by benchmark)
        reader = csv_mod.reader(io.StringIO(r.text))
        for row in reader:
            if len(row) < 6:
                continue
            idx_str = row[0].strip('"')
            status = row[2].strip('"')
            if status != "Match":
                continue
            coords_str = row[5].strip('"')
            if "," not in coords_str:
                continue
            lon_str, lat_str = coords_str.split(",")
            try:
                lon = float(lon_str)
                lat = float(lat_str)
                idx = int(idx_str)
                if idx >= 0 and idx < len(addresses):
                    results[addresses[idx]] = (lat, lon)
            except (ValueError, IndexError):
                continue
    except Exception as e:
        log.error("geocode_batch.error", error=str(e))

    return results


def geocode_single_census(addr_str: str) -> tuple[float, float] | None:
    """Geocode a single address via Census one-line API."""
    import httpx

    params = {
        "benchmark": "Public_AR_Current",
        "vintage": "Current_Current",
        "format": "json",
        "address": addr_str,
    }
    try:
        r = httpx.get(CENSUS_GEOCODE_URL, params=params, timeout=15.0)
        if r.status_code != 200:
            return None
        resp = r.json()
        matches = resp.get("result", {}).get("addressMatches", [])
        if matches:
            coords = matches[0].get("coordinates", {})
            lat = coords.get("y")
            lon = coords.get("x")
            if lat and lon:
                return (float(lat), float(lon))
    except Exception:
        pass
    return None


def centroid_fallback(li: dict) -> tuple[float, float] | None:
    """Use county-seat centroid as a last-resort coordinate."""
    state = li.get("state") or ""
    county = (li.get("county") or "").strip()
    key = f"{state}:{county}"
    return COUNTY_SEATS.get(key)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true", help="Don't write back, just report")
    args = parser.parse_args()

    docs_dir = Path(__file__).parent.parent / "docs"
    board_path = docs_dir / "listings.json.gz"

    if not board_path.exists():
        print(f"Board not found: {board_path}")
        sys.exit(1)

    print(f"Loading board from {board_path}...")
    with gzip.open(board_path, "rt") as f:
        listings = json.load(f)
    print(f"Loaded {len(listings)} listings")

    # Find listings with no lat/lon
    no_geo = [li for li in listings if not li.get("latitude") or not li.get("longitude")]
    print(f"Listings with no coordinates: {len(no_geo)}")

    # Split: those with addresses (geocodable) vs those without
    with_addr = []
    without_addr = []
    for li in no_geo:
        addr_str = build_address_string(li)
        if addr_str:
            li["_geocode_addr"] = addr_str
            with_addr.append(li)
        else:
            without_addr.append(li)

    print(f"  With address (geocodable): {len(with_addr)}")
    print(f"  Without address (centroid fallback): {len(without_addr)}")

    geocoded = 0
    centroided = 0
    failed = 0

    # Phase 1: Batch geocode addresses
    BATCH_SIZE = 950  # Census limit is 1000, stay under
    for i in range(0, len(with_addr), BATCH_SIZE):
        batch = with_addr[i:i + BATCH_SIZE]
        addresses = [li["_geocode_addr"] for li in batch]
        print(f"\nBatch {i // BATCH_SIZE + 1}: {len(addresses)} addresses...")

        results = geocode_batch_census(addresses)
        print(f"  Census matched: {len(results)}/{len(addresses)}")

        for li in batch:
            addr = li["_geocode_addr"]
            if addr in results:
                lat, lon = results[addr]
                li["latitude"] = lat
                li["longitude"] = lon
                raw = li.get("raw") or {}
                if not isinstance(raw, dict):
                    raw = {}
                    li["raw"] = raw
                raw["geo_imprecise"] = "census_geocode"
                geocoded += 1
            else:
                # Batch missed — try centroid fallback directly
                # (single-address API is too slow for 1000s of misses)
                c = centroid_fallback(li)
                if c:
                    li["latitude"] = c[0]
                    li["longitude"] = c[1]
                    raw = li.get("raw") or {}
                    if not isinstance(raw, dict):
                        raw = {}
                        li["raw"] = raw
                    raw["geo_imprecise"] = "county_centroid"
                    centroided += 1
                else:
                    failed += 1

        # Be polite to the Census API
        if i + BATCH_SIZE < len(with_addr):
            print("  Sleeping 2s...")
            time.sleep(2)

    # Phase 2: Centroid fallback for listings with no address
    for li in without_addr:
        c = centroid_fallback(li)
        if c:
            li["latitude"] = c[0]
            li["longitude"] = c[1]
            raw = li.get("raw") or {}
            if not isinstance(raw, dict):
                raw = {}
                li["raw"] = raw
            raw["geo_imprecise"] = "county_centroid_no_addr"
            centroided += 1
        else:
            failed += 1

    # Clean up temporary field
    for li in with_addr:
        li.pop("_geocode_addr", None)

    print(f"\n=== GEOCODE RESULTS ===")
    print(f"  Census geocoded: {geocoded}")
    print(f"  Centroid fallback: {centroided}")
    print(f"  Failed (no data): {failed}")
    print(f"  Total resolved: {geocoded + centroided}")

    remaining = sum(1 for li in listings if not li.get("latitude"))
    print(f"  Still no coordinates: {remaining}")

    if args.dry_run:
        print("\n[DRY RUN] Not writing back.")
        return

    # Write back
    print(f"\nWriting back to {board_path}...")
    with gzip.open(board_path, "wt") as f:
        json.dump(listings, f)
    print("Done.")

    # Also write uncompressed
    print(f"Writing uncompressed to {docs_dir / 'listings.json'}...")
    with open(docs_dir / "listings.json", "w") as f:
        json.dump(listings, f)
    print("Done.")


if __name__ == "__main__":
    main()
