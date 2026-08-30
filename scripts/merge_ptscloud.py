#!/usr/bin/env python3
"""Run PTSCloud + Charleston delinquent tax scrapers and merge into existing board.

Standalone script — does NOT require a full 7-hour board re-run.
Runs just the scrapers with fresh data, dedupes, merges into existing board,
and writes back.
"""
import asyncio
import sys
import json
from pathlib import Path
from collections import Counter

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from foreclosure_scraper.web_artifact import load_board, write_artifact
from foreclosure_scraper.dedupe import dedupe
from foreclosure_scraper.models import Listing


async def main():
    docs_dir = Path(__file__).parent.parent / "docs"

    # 1. Load existing board
    print("Loading existing board...")
    board = load_board(docs_dir)
    print(f"  Board: {len(board)} listings")

    # 2. Run PTSCloud delinquent tax scraper (8 NC counties, fresh data)
    print("\nRunning PTSCloud delinquent tax scraper...")
    from foreclosure_scraper.scrapers.counties_nc.nc_ptscloud_delinquent_tax import NCPtsCloudDelinquentTax
    pts = NCPtsCloudDelinquentTax()
    pts_listings: list[Listing] = await pts.safe_run()
    print(f"  PTSCloud: {len(pts_listings)} listings (slug={pts.slug})")

    # 3. Run Charleston delinquent tax scraper (834 listings, now active year-round)
    print("\nRunning Charleston delinquent tax scraper...")
    from foreclosure_scraper.scrapers.counties_sc.charleston_delinquent_tax import CharlestonDelinquentTax
    chas = CharlestonDelinquentTax()
    chas_listings: list[Listing] = await chas.safe_run()
    print(f"  Charleston: {len(chas_listings)} listings (slug={chas.slug})")

    # 4. Merge: dedupe new listings against each other first
    print("\nMerging new listings into board...")
    new_listings = pts_listings + chas_listings
    print(f"  New listings before dedupe: {len(new_listings)}")

    # Dedupe new listings against existing board
    combined = board + new_listings
    print(f"  Combined before dedupe: {len(combined)}")
    deduped = dedupe(combined)
    added = len(deduped) - len(board)
    print(f"  After dedupe: {len(deduped)} (net new: {added})")

    # 5. County breakdown of new listings
    if new_listings:
        counties = Counter(l.county for l in new_listings)
        print("\n  New listings by county:")
        for c, n in counties.most_common(15):
            print(f"    {c}: {n}")

    # 6. Write board back
    print(f"\nWriting board: {len(deduped)} listings...")
    summary = {
        "total_listings": len(deduped),
        "new_from_ptscloud": len(pts_listings),
        "new_from_charleston": len(chas_listings),
        "net_new_after_dedupe": added,
        "merge_timestamp": str(__import__("datetime").datetime.now()),
    }
    write_artifact(deduped, summary, docs_dir)
    print(f"\nDone! Board: {len(deduped)} listings (was {len(board)}, +{added} new)")


if __name__ == "__main__":
    asyncio.run(main())
