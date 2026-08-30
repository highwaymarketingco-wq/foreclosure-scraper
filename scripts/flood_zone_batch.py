#!/usr/bin/env python3
"""Run flood_zone enrichment repeatedly until coverage stops improving.

Each call to enrich_flood_zones has a 5-min internal deadline and fills
~3k listings. This script loops it, saving after each pass, until no
new zones are added or max iterations reached.

Run ALONE — no other enrichment process should be writing docs/listings.json.
"""
import asyncio, json, os, sys, time, gzip
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "src"))

BOARD = REPO / "docs" / "listings.json"
GZ = REPO / "docs" / "listings.json.gz"

MAX_ITERS = int(os.environ.get("FLOOD_MAX_ITERS", "10"))
QUIET = os.environ.get("FLOOD_QUIET", "0") == "1"


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


def count_coverage(listings):
    have = 0
    for li in listings:
        raw = li.get("raw") if isinstance(li, dict) else None
        if not raw:
            raw = li.get("raw", {}) if isinstance(li.get("raw"), dict) else {}
        # Try multiple access paths
        if isinstance(raw, dict) and raw.get("flood_zone"):
            have += 1
        elif isinstance(li, dict) and li.get("flood_zone"):
            have += 1
    return have


async def main():
    from foreclosure_scraper.enrichment_flood_zone import enrich_flood_zones
    from foreclosure_scraper.web_artifact import load_board

    docs = REPO / "docs"
    print("Loading board...", flush=True)
    t0 = time.time()
    board = load_board(docs)
    print(f"Board: {len(board)} listings ({time.time()-t0:.1f}s)")

    # Count current coverage
    have = 0
    for li in board:
        raw = li.raw if hasattr(li, 'raw') and isinstance(li.raw, dict) else {}
        if raw.get("flood_zone"):
            have += 1
    print(f"Flood zone coverage: {have}/{len(board)} ({have/len(board)*100:.1f}%)")

    total_new = 0
    for iteration in range(MAX_ITERS):
        print(f"\n{'='*60}")
        print(f"FLOOD ZONE ITERATION {iteration+1}/{MAX_ITERS}")
        print(f"{'='*60}", flush=True)

        t0 = time.time()
        try:
            result = await enrich_flood_zones(board)
            new = result.get("queried", 0) if isinstance(result, dict) else 0
        except Exception as e:
            print(f"  ERROR: {e}")
            import traceback; traceback.print_exc()
            break

        elapsed = time.time() - t0
        print(f"  Iteration {iteration+1}: +{new} new zones ({elapsed:.1f}s)")

        if new == 0:
            print("  No new zones — stopping.")
            break

        total_new += new

        # Save after each iteration
        print("  Saving board...", flush=True)
        # Convert board to JSON-serializable format
        listings_data = []
        for li in board:
            if hasattr(li, 'model_dump'):
                listings_data.append(li.model_dump())
            elif hasattr(li, 'dict'):
                listings_data.append(li.dict())
            else:
                listings_data.append(li)
        stream_save(listings_data)

        # Recount
        have = 0
        for li in board:
            raw = li.raw if hasattr(li, 'raw') and isinstance(li.raw, dict) else {}
            if raw.get("flood_zone"):
                have += 1
        print(f"  Coverage now: {have}/{len(board)} ({have/len(board)*100:.1f}%)")

    print(f"\n=== FLOOD ZONE BATCH COMPLETE ===")
    print(f"  Total new zones: {total_new}")
    print(f"  Final coverage: {have}/{len(board)} ({have/len(board)*100:.1f}%)")


if __name__ == "__main__":
    asyncio.run(main())
