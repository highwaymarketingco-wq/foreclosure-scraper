#!/usr/bin/env python3
"""Enrich bankruptcy dockets with property data via GIS name cross-reference."""
import asyncio, sys, os
sys.path.insert(0, os.path.expanduser("~/foreclosure-scraper/src"))
os.environ.setdefault("PYTHONPATH", "~/foreclosure-scraper/src:~/foreclosure-scraper/.venv/lib/python3.12/site-packages")

from foreclosure_scraper.board_persist import load_board
from foreclosure_scraper.enrichment_bankruptcy_property import enrich_bankruptcy_property
from foreclosure_scraper.web_artifact import write_artifact

DOCS = os.path.expanduser("~/foreclosure-scraper/docs")

async def main():
    board = load_board()
    print(f"Board size: {len(board)}")

    # Get bare bankruptcy listings
    bare = [
        l for l in board
        if "courtlistener" in (l.source or "").lower()
        and "bankrupt" in (l.source or "").lower()
        and not l.street_address
    ]
    print(f"Bare bankruptcy listings to enrich: {len(bare)}")

    if not bare:
        print("Nothing to enrich.")
        return

    # Run enrichment (fixes defendant from raw, queries NC OneMap + SC GIS)
    await enrich_bankruptcy_property(bare, concurrency=4)

    # Check results
    now_with_addr = [l for l in bare if l.street_address]
    print(f"\nAfter enrichment:")
    print(f"  Now with address: {len(now_with_addr)} / {len(bare)}")
    if now_with_addr:
        for s in now_with_addr[:5]:
            print(f"  {s.defendant}: {s.street_address}, {s.county} {s.state} parcel={s.parcel_id} assessed={s.assessed_value}")

    # Save board
    print(f"\nSaving board ({len(board)} listings)...")
    write_artifact(board, {}, DOCS)
    print("Board saved.")

if __name__ == "__main__":
    asyncio.run(main())
