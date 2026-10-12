#!/usr/bin/env python3
"""
Single-pass production runner for Polk delinquent tax search.
Runs all surnames once, parses results inline, saves to JSON.
No double-pass — does NOT call scraper.fetch() again.
"""
import asyncio
import json
import os
import re
import sys
import time
from datetime import datetime

sys.path.insert(0, "src")
os.environ["DISPLAY"] = ":99"
os.environ.setdefault("PYTHONUNBUFFERED", "1")

from foreclosure_scraper.scrapers.counties_nc.polk_tax import (
    _SEARCH_TERMS,
    _search_via_nodriver,
    PolkTaxAuction,
)
from foreclosure_scraper.browser_utils import start_browser


async def main():
    t0 = time.time()
    print(f"Polk Delinquent Tax Production Run (single-pass)", flush=True)
    print(f"Surnames: {len(_SEARCH_TERMS)}", flush=True)
    print("=" * 60, flush=True)

    scraper = PolkTaxAuction()
    seen_ids: set[str] = set()
    all_listings = []
    errors = 0

    browser = await start_browser(headless=False)
    try:
        for i, term in enumerate(_SEARCH_TERMS):
            html = None
            for attempt in range(3):
                try:
                    html = await _search_via_nodriver(browser, term)
                except Exception as e:
                    print(f"  [{i+1}/{len(_SEARCH_TERMS)}] {term}: ERROR ({e})", flush=True)
                    html = None
                    continue
                low = html.lower()
                if ("just a moment" in low or "sorry, you have been blocked" in low
                        or len(html) > 25000 and "taxdetail" not in low and "gvhdr" not in low
                        and "no records" not in low and "too many records" not in low):
                    print(f"  [{i+1}/{len(_SEARCH_TERMS)}] {term}: Cloudflare challenge (attempt {attempt+1}), retrying...", flush=True)
                    await asyncio.sleep(8)
                    html = None
                    continue
                break

            if html is None:
                errors += 1
                print(f"  [{i+1}/{len(_SEARCH_TERMS)}] {term}: FAILED after retries", flush=True)
                continue

            # Parse inline using the scraper's parser
            new_listings = scraper._parse_search_html(html, seen_ids)
            print(f"  [{i+1}/{len(_SEARCH_TERMS)}] {term}: {len(new_listings)} listings", flush=True)
            all_listings.extend(new_listings)

            if (i + 1) % 10 == 0:
                elapsed = time.time() - t0
                print(f"  --- Checkpoint: {len(all_listings)} listings, {errors} errors, {elapsed:.0f}s ---", flush=True)
    finally:
        try:
            browser.stop()
        except BaseException:
            pass

    elapsed = time.time() - t0
    print("=" * 60, flush=True)
    print(f"Total listings: {len(all_listings)}", flush=True)
    print(f"Unique IDs: {len(seen_ids)}", flush=True)
    print(f"Errors: {errors}", flush=True)
    print(f"Time: {elapsed:.0f}s ({elapsed/60:.1f}m)", flush=True)

    # Save to JSON
    out_path = "data/walled_output/polk_tax.json"
    os.makedirs("data/walled_output", exist_ok=True)
    data = [l.model_dump(mode="json") for l in all_listings]
    with open(out_path, "w") as f:
        json.dump(data, f, default=str)
    print(f"Saved {len(data)} listings to {out_path}", flush=True)


if __name__ == "__main__":
    asyncio.run(main())
