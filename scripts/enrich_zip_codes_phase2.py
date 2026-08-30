#!/usr/bin/env python3
"""Fix zip_codes: Phase 2 — fill the 16,289 still missing.

Strategy:
  1. Census forward batch for listings with street_address (fast, ~5 min)
  2. Nominatim reverse geocode for listings with lat/lon but no address (slow, background)
  3. County-seat fallback already done in Phase 1

Streaming save to avoid OOM.
"""
import json, sys, os, time, asyncio, gzip, traceback, csv as _csv, io as _io
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "src"))

BOARD = REPO / "docs" / "listings.json"
GZ = REPO / "docs" / "listings.json.gz"

CENSUS_BATCH = "https://geocoding.geo.census.gov/geocoder/locations/addressbatch"
NOMINATIM = "https://nominatim.openstreetmap.org/reverse"


def stream_save(listings):
    t0 = time.time()
    n = len(listings)
    print(f"  [save] Writing {n} listings...", flush=True)
    tmp = str(BOARD) + ".tmp"
    total = 0
    with open(tmp, 'w') as f:
        f.write('[')
        for i, li in enumerate(listings):
            if i > 0:
                f.write(',')
            chunk = json.dumps(li, default=str)
            f.write(chunk)
            total += len(chunk)
            if (i + 1) % 10000 == 0:
                print(f"    ...{i+1}/{n} ({os.path.getsize(tmp)//1024}KB)", flush=True)
        f.write(']')
    print(f"  [save] JSON: {os.path.getsize(tmp)//1024}KB")
    os.replace(tmp, str(BOARD))
    tmp_gz = str(GZ) + ".tmp"
    with open(str(BOARD), 'rb') as src, open(tmp_gz, 'wb') as dst:
        with gzip.GzipFile(fileobj=dst, mode='wb', compresslevel=6) as gz:
            while True:
                chunk = src.read(1024 * 1024)
                if not chunk:
                    break
                gz.write(chunk)
    os.replace(tmp_gz, str(GZ))
    print(f"  [save] GZ: {os.path.getsize(str(GZ))//1024}KB ({time.time()-t0:.1f}s)")


def forward_geocode_batch(targets):
    """Census batch forward geocode: [(index, 'street, city, state'), ...]"""
    import httpx
    results = {}
    BATCH = 1000
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

        for attempt in range(3):
            try:
                r = httpx.post(
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
        else:
            print(f"    batch {start}: giveup", flush=True)
            continue

        for line in _csv.reader(_io.StringIO(r.text)):
            if len(line) < 6 or line[2] != "Match":
                continue
            try:
                idx = int(line[0])
                matched_addr = line[4]
                parts = matched_addr.rsplit(",", 1)
                if len(parts) > 1:
                    zip_part = parts[1].strip()
                    if zip_part.isdigit() and len(zip_part) == 5:
                        orig_idx = chunk[idx][0]
                        results[orig_idx] = zip_part
            except (ValueError, IndexError):
                continue

        print(f"    forward: {start + len(chunk)}/{len(targets)} ({len(results)} matched)", flush=True)

    return results


async def nominatim_reverse(coords):
    """Nominatim reverse geocode: [(index, lat, lon), ...]
    Respects 1 req/sec fair use policy."""
    import httpx
    results = {}
    sem = asyncio.Semaphore(1)  # 1 at a time per Nominatim policy

    async with httpx.AsyncClient(timeout=15.0, headers={"User-Agent": "foreclosure-scraper/1.0"}) as c:
        for i, (idx, lat, lon) in enumerate(coords):
            async with sem:
                try:
                    r = await c.get(NOMINATIM, params={
                        "lat": str(lat), "lon": str(lon),
                        "format": "json", "addressdetails": "1", "zoom": "18",
                    })
                    if r.status_code == 200:
                        data = r.json()
                        addr = data.get("address", {})
                        zip_code = addr.get("postcode")
                        if zip_code and len(zip_code) == 5:
                            results[idx] = zip_code
                except Exception:
                    pass
                # 1.1s delay per request (Nominatim fair use)
                await asyncio.sleep(1.1)

            if (i + 1) % 50 == 0:
                print(f"    nominatim: {i+1}/{len(coords)} ({len(results)} zips found)", flush=True)

    return results


def main():
    print("Loading board...", flush=True)
    t0 = time.time()
    with open(BOARD, 'r') as f:
        listings = json.load(f)
    print(f"Board: {len(listings)} listings ({time.time()-t0:.1f}s)")

    missing = [(i, li) for i, li in enumerate(listings) if not li.get("zip_code")]
    print(f"Still missing zip_code: {len(missing):,} / {len(listings):,}")

    if not missing:
        print("All listings have zip_code — nothing to do.")
        return

    # Split:
    # A) Has street_address → Census forward batch (fast)
    # B) Has lat/lon but no address → Nominatim reverse (slow)
    # C) No address, no coords → county-seat fallback (already assigned, skip)
    group_a = []
    group_b = []

    for i, li in missing:
        addr = li.get("street_address")
        city = li.get("city")
        state = li.get("state")
        lat = li.get("latitude")
        lon = li.get("longitude")

        if addr and (city or state):
            addr_str = f"{addr}, {city or ''}, {state or ''}"
            group_a.append((i, addr_str))
        elif lat is not None and lon is not None:
            group_b.append((i, float(lat), float(lon)))

    print(f"\nGroup A (Census forward batch, has address): {len(group_a):,}")
    print(f"Group B (Nominatim reverse, has coords):      {len(group_b):,}")

    filled = 0

    # Group A: Census forward batch
    if group_a:
        print(f"\n[Group A] Forward-geocoding {len(group_a):,} listings...", flush=True)
        try:
            zips = forward_geocode_batch(group_a)
            for idx, zip_code in zips.items():
                listings[idx]["zip_code"] = zip_code
                filled += 1
            print(f"  Forward geocode: {len(zips):,} zips found ({filled} total)")
        except Exception as e:
            print(f"  Forward geocode ERROR: {e}")
            traceback.print_exc()

    # Save after Group A (don't lose progress before slow Group B)
    if filled > 0:
        print(f"\nSaving board after Group A ({filled} new zips)...", flush=True)
        stream_save(listings)

    # Group B: Nominatim reverse
    if group_b:
        print(f"\n[Group B] Nominatim reverse-geocoding {len(group_b):,} listings...", flush=True)
        print(f"  (1.1s per request = ~{len(group_b)*1.1/60:.0f} min)", flush=True)
        try:
            zips = asyncio.run(nominatim_reverse(group_b))
            for idx, zip_code in zips.items():
                listings[idx]["zip_code"] = zip_code
                filled += 1
            print(f"  Nominatim: {len(zips):,} zips found ({filled} total)")
        except Exception as e:
            print(f"  Nominatim ERROR: {e}")
            traceback.print_exc()

    # Final
    still_missing = sum(1 for li in listings if not li.get("zip_code"))
    now_have = len(listings) - still_missing
    print(f"\n=== ZIP CODE PHASE 2 COMPLETE ===")
    print(f"  Filled this pass: {filled:,}")
    print(f"  Now have zip: {now_have:,} ({now_have/len(listings)*100:.1f}%)")
    print(f"  Still missing: {still_missing:,} ({still_missing/len(listings)*100:.1f}%)")

    if filled > 0:
        print("\nSaving board...", flush=True)
        stream_save(listings)
        print("✅ Saved.")
    else:
        print("No new zips — skipping save.")


if __name__ == "__main__":
    main()
