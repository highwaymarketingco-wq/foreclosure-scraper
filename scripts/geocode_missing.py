#!/usr/bin/env python3
"""
Geocode listings missing coordinates using Census Geocoder API.

Runs AFTER ncpts_lrc enrichment so listings now have street addresses.
Uses Census batch API (up to 10,000 addresses per request) for speed.
Falls back to single-address geocoding for any that fail batch.

Writes top-level latitude/longitude.
Saves incrementally to avoid OOM.
"""
import asyncio, gc, json, os, sys, time
import httpx

HOME = os.path.expanduser("~")
sys.path.insert(0, os.path.join(HOME, "foreclosure-scraper", "src"))

from foreclosure_scraper.web_artifact import load_board, write_artifact

DOCS_DIR = os.path.join(HOME, "foreclosure-scraper", "docs")
CENSUS_BATCH_URL = "https://geocoding.geo.census.gov/geocoder/geographies/onelineaddress"
CENSUS_BATCH_ENDPOINT = "https://geocoding.geo.census.gov/geocoder/batchGeocoder"
SAVE_EVERY = 500
MAX_CONCURRENT = 3  # be polite


def build_address(li):
    """Build a geocodable address string from listing fields."""
    # Check LRC-provided address first
    raw = li.raw if isinstance(li.raw, dict) else {}
    lrc_addr = raw.get("lrc_property_address") or raw.get("lrc_property_address1")
    lrc_city = raw.get("lrc_property_city")

    # Prefer LRC address if we have it
    if lrc_addr:
        parts = [lrc_addr]
        if lrc_city:
            parts.append(lrc_city)
        if li.state:
            parts.append(li.state)
        if li.zip_code:
            parts.append(str(li.zip_code))
        return ", ".join(parts)

    # Fall back to street_address
    if li.street_address and li.street_address not in ("None", "", None):
        addr = str(li.street_address).strip()
        # Skip legal notice text (not an address)
        if len(addr) > 200 or "NOTICE" in addr.upper() or "SUBSTITUTE" in addr.upper():
            return None
        parts = [addr]
        if li.city:
            parts.append(li.city)
        if li.state:
            parts.append(li.state)
        if li.zip_code:
            parts.append(str(li.zip_code))
        return ", ".join(parts)

    return None


async def geocode_one(client, address_str):
    """Geocode a single address via Census API. Returns (lat, lon) or (None, None)."""
    try:
        resp = await client.get(CENSUS_BATCH_URL, params={
            "address": address_str,
            "benchmark": "Public_AR_Current",
            "vintage": "Current_Current",
            "layers": "10",
            "format": "json",
        }, timeout=15.0)
        if resp.status_code != 200:
            return None, None
        data = resp.json()
        matches = data.get("result", {}).get("addressMatches", [])
        if matches:
            coords = matches[0].get("coordinates", {})
            return coords.get("y"), coords.get("x")  # y=lat, x=lon
    except Exception:
        pass
    return None, None


async def main():
    t0 = time.time()
    print("[1] Loading board...")
    board = load_board(DOCS_DIR)
    total = len(board)

    # Find listings without coords that now have addresses
    need = []
    have_coords = 0
    for i, li in enumerate(board):
        if getattr(li, "latitude", None) and getattr(li, "longitude", None):
            have_coords += 1
            continue
        addr = build_address(li)
        if addr:
            need.append((i, addr))

    print(f"    Board: {total:,} listings")
    print(f"    Already have coords: {have_coords:,} ({have_coords/total*100:.1f}%)")
    print(f"    Need geocoding (have address): {len(need):,}")

    if not need:
        print("    Nothing to geocode. Done.")
        return

    print(f"\n[2] Geoding via Census API (concurrency={MAX_CONCURRENT})...")
    sem = asyncio.Semaphore(MAX_CONCURRENT)
    geocoded = 0
    processed = 0
    batch_start = time.time()

    async with httpx.AsyncClient() as client:
        for start in range(0, len(need), SAVE_EVERY):
            batch = need[start:start + SAVE_EVERY]
            batch_num = start // SAVE_EVERY + 1
            total_batches = (len(need) + SAVE_EVERY - 1) // SAVE_EVERY

            async def _do_one(idx, addr):
                nonlocal geocoded, processed
                async with sem:
                    li = board[idx]
                    lat, lon = await geocode_one(client, addr)
                    if lat and lon:
                        li.latitude = float(lat)
                        li.longitude = float(lon)
                        geocoded += 1
                    processed += 1

            tasks = [_do_one(idx, addr) for idx, addr in batch]
            await asyncio.gather(*tasks, return_exceptions=True)

            elapsed = time.time() - batch_start
            done = start + len(batch)
            rate = done / elapsed if elapsed > 0 else 0
            remaining = (len(need) - done) / rate if rate > 0 else 0
            print(f"  Batch {batch_num}/{total_batches}: {processed:,}/{len(need):,} | "
                  f"Geocoded: {geocoded:,} | Rate: {rate:.1f}/s | ETA: {remaining:.0f}s")

            try:
                write_artifact(board, {"checkpoint": "geocode"}, DOCS_DIR)
                gc.collect()
            except Exception as e:
                print(f"  SAVE ERROR: {e}")

    print(f"\n[3] Final save...")
    write_artifact(board, {"enrichment": "geocode_complete"}, DOCS_DIR)

    # Final stats
    have_now = sum(1 for li in board if getattr(li, "latitude", None) and getattr(li, "longitude", None))
    elapsed = time.time() - t0
    print(f"\n{'='*60}")
    print(f"COMPLETE: {geocoded:,} newly geocoded")
    print(f"  Coords coverage: {have_coords:,} -> {have_now:,} ({have_now/total*100:.1f}%)")
    print(f"  Time: {elapsed:.0f}s")
    print(f"{'='*60}")


if __name__ == "__main__":
    asyncio.run(main())
