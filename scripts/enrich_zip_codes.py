#!/usr/bin/env python3
"""Fill missing zip_code on all listings.

Strategy:
  1. Reverse-geocode lat/lon → zip via Census Geocoder (free, no rate limit, batch API)
  2. Forward-geocode street_address + city + state → zip via Census Geocoder
  3. For listings with no address and no coords, use county-seat zip lookup

Streaming save to avoid OOM on 8GB machine.
"""
import json, sys, os, time, asyncio, gzip, traceback
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "src"))

BOARD = REPO / "docs" / "listings.json"
GZ = REPO / "docs" / "listings.json.gz"

CENSUS_GEO = "https://geocoding.geo.census.gov/geocoder/locations/onelineaddress"
CENSUS_BATCH = "https://geocoding.geo.census.gov/geocoder/locations/addressbatch"
CENSUS_REVGEO = "https://geocoding.geo.census.gov/geocoder/geographies/coordinates"

# County-seat zip codes for our counties (for fallback)
COUNTY_SEAT_ZIPS = {
    ("SC", "Spartanburg"): "29302", ("SC", "Anderson"): "29621",
    ("SC", "Pickens"): "29671", ("SC", "Oconee"): "29631",
    ("SC", "Cherokee"): "29302", ("SC", "Union"): "28160",
    ("SC", "Laurens"): "29360", ("SC", "Charleston"): "29401",
    ("SC", "Greenville"): "29601", ("SC", "Berkeley"): "29445",
    ("SC", "Dorchester"): "29437", ("SC", "Lexington"): "29072",
    ("SC", "Richland"): "29201", ("SC", "Beaufort"): "29902",
    ("SC", "Horry"): None,  # excluded
    ("NC", "Rutherford"): "28043", ("NC", "Cleveland"): "28013",
    ("NC", "Henderson"): "28739", ("NC", "Polk"): "28722",
    ("NC", "Gaston"): "28052", ("NC", "Mecklenburg"): "28202",
    ("NC", "Buncombe"): "28801", ("NC", "Transylvania"): "28712",
    ("NC", "McDowell"): "28752", ("NC", "Lincoln"): "28092",
    ("NC", "Madison"): "28754", ("NC", "Yancey"): "28714",
    ("NC", "Mitchell"): "28705", ("NC", "Burke"): "28655",
    ("NC", "Forsyth"): "27101", ("NC", "Guilford"): "27401",
    ("NC", "Beaufort"): "27810", ("NC", "Pitt"): "27858",
    ("NC", "New Hanover"): "28401", ("NC", "Wake"): "27601",
    ("NC", "Orange"): "27510", ("NC", "Hyde"): "27838",
    ("NC", "Cumberland"): "28301", ("NC", "Haywood"): "27712",
    ("NC", "Stokes"): "27022",
}


def stream_save(listings, path_board, path_gz):
    """Write JSON + gzip one listing at a time."""
    t0 = time.time()
    print(f"  [stream_save] Writing {len(listings)} listings...")
    tmp_board = str(path_board) + ".tmp"
    with open(tmp_board, 'w') as f:
        f.write('[')
        for i, li in enumerate(listings):
            if i > 0:
                f.write(',')
            f.write(json.dumps(li, default=str))
            if (i + 1) % 10000 == 0:
                print(f"    ...{i+1}/{len(listings)} ({os.path.getsize(tmp_board)//1024}KB)")
        f.write(']')
    print(f"  [stream_save] JSON written: {os.path.getsize(tmp_board)//1024}KB")
    os.replace(tmp_board, str(path_board))

    tmp_gz = str(path_gz) + ".tmp"
    with open(str(path_board), 'rb') as src, open(tmp_gz, 'wb') as dst:
        with gzip.GzipFile(fileobj=dst, mode='wb', compresslevel=6) as gz:
            while True:
                chunk = src.read(1024 * 1024)
                if not chunk:
                    break
                gz.write(chunk)
    print(f"  [stream_save] GZ written: {os.path.getsize(tmp_gz)//1024}KB")
    os.replace(tmp_gz, str(path_gz))
    print(f"  [stream_save] Done ({time.time()-t0:.1f}s)")


async def reverse_geocode_batch(coords: list[tuple[int, float, float]]) -> dict[int, str]:
    """Reverse-geocode lat/lon → zip via Census coordinates API.
    coords = [(index, lat, lon), ...]
    Returns {index: zip_code}
    """
    import httpx as _httpx
    results = {}
    
    async with _httpx.AsyncClient(timeout=15.0) as c:
        sem = asyncio.Semaphore(10)  # 10 concurrent (Census has no rate limit)
        
        async def _one(idx, lat, lon):
            async with sem:
                try:
                    r = await c.get(CENSUS_REVGEO, params={
                        "x": str(lon), "y": str(lat),
                        "benchmark": "Public_AR_Current",
                        "vintage": "Current_Current",
                        "format": "json",
                    })
                    if r.status_code != 200:
                        return
                    data = r.json()
                    geos = (data.get("result") or {}).get("geographies") or {}
                    zctas = geos.get("ZIP Code Tabulation Areas") or geos.get("Zip Code Tabulation Areas") or []
                    if zctas:
                        z = zctas[0].get("GEOID") or zctas[0].get("ZCTA")
                        if z:
                            results[idx] = str(z).zfill(5)[:5]
                except Exception:
                    pass
        
        tasks = [_one(idx, lat, lon) for idx, lat, lon in coords]
        await asyncio.gather(*tasks)
    
    return results


def forward_geocode_batch(targets: list[tuple[int, str]]) -> dict[int, str]:
    """Forward-geocode addresses → zip via Census batch API.
    targets = [(index, "street, city, state"), ...]
    Returns {index: zip_code}
    """
    import csv as _csv
    import io as _io
    
    results = {}
    BATCH = 250
    MAX_TRIES = 3
    
    import httpx as _httpx
    
    for start in range(0, len(targets), BATCH):
        chunk = targets[start:start + BATCH]
        buf = _io.StringIO()
        w = _csv.writer(buf)
        for i, (_, addr) in enumerate(chunk):
            parts = addr.rsplit(",", 2)
            street = parts[0].strip() if len(parts) >= 1 else ""
            city = parts[1].strip() if len(parts) >= 2 else ""
            state_zip = parts[2].strip() if len(parts) >= 3 else ""
            w.writerow([i, street, city, state_zip, ""])
        
        r = None
        for attempt in range(MAX_TRIES):
            try:
                r = _httpx.post(
                    CENSUS_BATCH,
                    files={"addressFile": ("addresses.csv", buf.getvalue(), "text/csv")},
                    data={"benchmark": "Public_AR_Current", "vintage": "Current_Current"},
                    timeout=180.0,
                )
                if r.status_code == 200:
                    break
            except Exception:
                pass
            time.sleep(2 * (attempt + 1))
        
        if r is None or r.status_code != 200:
            print(f"    batch {start}: giveup")
            continue
        
        for line in _csv.reader(_io.StringIO(r.text)):
            if len(line) < 6 or line[2] != "Match":
                continue
            try:
                idx = int(line[0])
                # line[4] is matched_addr like "123 MAIN ST, ASHEVILLE, NC, 28801"
                matched_addr = line[4]
                # Extract zip from the end
                parts = matched_addr.rsplit(",", 1)
                if len(parts) > 1:
                    zip_part = parts[1].strip()
                    if zip_part.isdigit() and len(zip_part) == 5:
                        orig_idx = chunk[idx][0]
                        results[orig_idx] = zip_part
            except (ValueError, IndexError):
                continue
        
        if (start // BATCH + 1) % 10 == 0:
            print(f"    forward_geocode: {start + len(chunk)}/{len(targets)} done, {len(results)} matched")
    
    return results


def main():
    print("Loading board...")
    t0 = time.time()
    with open(BOARD, 'r') as f:
        listings = json.load(f)
    print(f"Board: {len(listings)} listings ({time.time()-t0:.1f}s)")

    # Find listings missing zip
    missing = [(i, li) for i, li in enumerate(listings) if not li.get("zip_code")]
    print(f"Missing zip_code: {len(missing):,} / {len(listings):,}")

    if not missing:
        print("All listings have zip_code — nothing to do.")
        return

    # Split into groups:
    # A) Has lat/lon → reverse geocode
    # B) Has street_address (+ city or state) but no lat/lon → forward geocode
    # C) Has neither → county-seat fallback
    
    group_a = []  # (index, lat, lon)
    group_b = []  # (index, address_string)
    group_c = []  # (index, state, county)
    
    for i, li in missing:
        lat = li.get("latitude")
        lon = li.get("longitude")
        addr = li.get("street_address")
        city = li.get("city")
        state = li.get("state")
        county = li.get("county", "").replace(" County", "").strip()
        
        if lat is not None and lon is not None:
            group_a.append((i, float(lat), float(lon)))
        elif addr and (city or state):
            addr_str = f"{addr}, {city or ''}, {state or ''}"
            group_b.append((i, addr_str))
        else:
            group_c.append((i, state, county))
    
    print(f"\nGroup A (reverse geocode from lat/lon): {len(group_a):,}")
    print(f"Group B (forward geocode from address): {len(group_b):,}")
    print(f"Group C (county-seat fallback):         {len(group_c):,}")
    
    filled = 0
    
    # Group A: reverse geocode
    if group_a:
        print(f"\n[Group A] Reverse-geocoding {len(group_a):,} listings...")
        try:
            zips = asyncio.run(reverse_geocode_batch(group_a))
            for idx, zip_code in zips.items():
                listings[idx]["zip_code"] = zip_code
                filled += 1
            print(f"  Reverse geocode: {len(zips):,} zips found ({filled} total filled)")
        except Exception as e:
            print(f"  Reverse geocode ERROR: {e}")
            traceback.print_exc()
    
    # Group B: forward geocode
    if group_b:
        print(f"\n[Group B] Forward-geocoding {len(group_b):,} listings...")
        try:
            zips = forward_geocode_batch(group_b)
            for idx, zip_code in zips.items():
                listings[idx]["zip_code"] = zip_code
                filled += 1
            print(f"  Forward geocode: {len(zips):,} zips found ({filled} total filled)")
        except Exception as e:
            print(f"  Forward geocode ERROR: {e}")
            traceback.print_exc()
    
    # Group C: county-seat fallback
    if group_c:
        print(f"\n[Group C] County-seat fallback for {len(group_c):,} listings...")
        fallback_filled = 0
        for idx, state, county in group_c:
            zip_code = COUNTY_SEAT_ZIPS.get((state, county))
            if zip_code and not listings[idx].get("zip_code"):
                listings[idx]["zip_code"] = zip_code
                listings[idx].setdefault("raw", {})
                if isinstance(listings[idx].get("raw"), dict):
                    listings[idx]["raw"]["zip_source"] = "county_seat_fallback"
                filled += 1
                fallback_filled += 1
        print(f"  County-seat fallback: {fallback_filled:,} zips assigned ({filled} total filled)")
    
    # Final count
    still_missing = sum(1 for li in listings if not li.get("zip_code"))
    now_have = len(listings) - still_missing
    print(f"\n=== ZIP CODE ENRICHMENT COMPLETE ===")
    print(f"  Filled: {filled:,}")
    print(f"  Now have zip: {now_have:,} ({now_have/len(listings)*100:.1f}%)")
    print(f"  Still missing: {still_missing:,} ({still_missing/len(listings)*100:.1f}%)")
    
    if filled > 0:
        print("\nSaving board (stream)...")
        stream_save(listings, BOARD, GZ)
        print("\n✅ Zip code enrichment saved.")
    else:
        print("\nNo zips filled — skipping save.")


if __name__ == "__main__":
    main()
