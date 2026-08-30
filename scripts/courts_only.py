#!/usr/bin/env python3
"""Run court records enrichment only (NC eCourts + SC Public Index)."""
import asyncio, json, os, sys, time, gzip
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "src"))

BOARD = REPO / "docs" / "listings.json"
GZ = REPO / "docs" / "listings.json.gz"


def stream_save(listings):
    t0 = time.time()
    n = len(listings)
    print(f"  [save] Writing {n} listings...", flush=True)
    tmp = str(BOARD) + ".tmp"
    with open(tmp, 'w') as f:
        f.write('[')
        for i, li in enumerate(listings):
            if i > 0:
                f.write(',')
            f.write(json.dumps(li, default=str))
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


async def main():
    from foreclosure_scraper.enrichment_courts import enrich_with_court_records
    from foreclosure_scraper.web_artifact import load_board

    docs = REPO / "docs"
    print("Loading board...", flush=True)
    t0 = time.time()
    board = load_board(docs)
    print(f"Board: {len(board)} listings ({time.time()-t0:.1f}s)")

    # Count current coverage
    have = sum(1 for li in board
               if isinstance(li.raw, dict) and li.raw.get("court_record"))
    print(f"Court record coverage: {have}/{len(board)} ({have/len(board)*100:.1f}%)")

    # NC/SC breakdown
    nc_with_case = sum(1 for li in board if li.state == "NC" and li.case_number)
    sc_with_case = sum(1 for li in board if li.state == "SC" and li.case_number)
    print(f"  NC with case_number: {nc_with_case}")
    print(f"  SC with case_number: {sc_with_case}")

    print("\nRunning court records enrichment...", flush=True)
    t0 = time.time()
    result = await enrich_with_court_records(board)
    elapsed = time.time() - t0

    # Count results
    have_after = sum(1 for li in board
                     if isinstance(li.raw, dict) and li.raw.get("court_record"))
    print(f"\nCourt enrichment done ({elapsed:.1f}s)")
    print(f"  Before: {have}  After: {have_after}  New: {have_after - have}")
    print(f"  Coverage: {have_after}/{len(board)} ({have_after/len(board)*100:.1f}%)")

    if have_after > have:
        print("\nSaving board...", flush=True)
        listings_data = []
        for li in board:
            if hasattr(li, 'model_dump'):
                listings_data.append(li.model_dump())
            elif hasattr(li, 'dict'):
                listings_data.append(li.dict())
            else:
                listings_data.append(li)
        stream_save(listings_data)
    else:
        print("No new court records — skipping save.")


if __name__ == "__main__":
    asyncio.run(main())
