#!/usr/bin/env python3.12
"""Merge working tax delinquent/sale scrapers into the board.

These scrapers produce real listings but were never run in the main engine
or were skipped during merge. This script fetches them live and merges
new listings into the board without re-scraping everything.

Usage:
    python3.12 scripts/merge_tax_scrapers.py [--dry-run]
"""
import argparse
import asyncio
import json
import os
import sys
import traceback
from datetime import datetime

# Must set up path before importing project modules
sys.path.insert(0, os.path.expanduser("~/foreclosure-scraper/src"))
sys.path.insert(0, os.path.expanduser("~/foreclosure-scraper/.venv/lib/python3.12/site-packages"))

from foreclosure_scraper.models import Listing
from foreclosure_scraper.web_artifact import load_board, write_artifact

# Scrapers that WORK but aren't on the board
TAX_SCRAPERS = [
    ("counties_sc.charleston_delinquent_tax", "CharlestonDelinquentTax"),
    ("counties_sc.pickens_tax_sale", "PickensTaxSale"),
    ("counties_sc.colleton_tax_sale", "ColletonTaxSale"),
    ("counties_nc.henderson_tax", "HendersonTaxForeclosure"),
    ("counties_nc.polk_tax", "PolkTaxAuction"),
]


def _existing_keys(board: list[Listing]) -> set[str]:
    """Build dedupe keys for all existing board listings."""
    keys = set()
    for li in board:
        # parcel_id is primary dedupe key
        k = li.parcel_id or li.case_number or li.source_url
        if k:
            keys.add(k.lower().strip() if isinstance(k, str) else str(k))
    return keys


async def fetch_scraper(mod_path: str, cls_name: str) -> list[Listing]:
    """Fetch listings from a single scraper."""
    import inspect
    try:
        mod = __import__("foreclosure_scraper.scrapers." + mod_path, fromlist=[cls_name])
        cls = getattr(mod, cls_name)
        obj = cls()
        result = obj.fetch()
        if inspect.iscoroutine(result):
            result = await result
        if isinstance(result, list):
            return [li for li in result if isinstance(li, Listing)]
        return [li async for li in result] if hasattr(result, "__aiter__") else list(result)
    except Exception as e:
        print(f"  ERR {mod_path}: {type(e).__name__}: {str(e)[:200]}")
        traceback.print_exc()
        return []


async def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    print("Loading board...")
    board = load_board()
    print(f"Board loaded: {len(board)} listings")

    existing_keys = _existing_keys(board)
    print(f"Existing dedupe keys: {len(existing_keys)}")

    new_listings: list[Listing] = []
    for mod_path, cls_name in TAX_SCRAPERS:
        print(f"\nFetching {cls_name}...")
        listings = await fetch_scraper(mod_path, cls_name)
        added = 0
        for li in listings:
            k = li.parcel_id or li.case_number or li.source_url
            k = k.lower().strip() if isinstance(k, str) else str(k)
            if k and k not in existing_keys:
                new_listings.append(li)
                existing_keys.add(k)
                added += 1
        print(f"  Fetched {len(listings)}, new: {added}, dupes: {len(listings) - added}")

    print(f"\nTotal new listings to merge: {len(new_listings)}")

    if args.dry_run:
        print("DRY RUN - not writing board")
        return

    if not new_listings:
        print("No new listings to merge.")
        return

    board.extend(new_listings)
    print(f"Board now: {len(board)} listings (was {len(board) - len(new_listings)})")

    # Write board
    summary = {
        "total": len(board),
        "merged_new": len(new_listings),
        "run_type": "merge_tax_scrapers",
        "timestamp": datetime.now().isoformat(),
    }
    write_artifact(board, summary)
    print(f"Board written with {len(board)} listings.")


if __name__ == "__main__":
    asyncio.run(main())
