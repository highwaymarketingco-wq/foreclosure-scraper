#!/usr/bin/env python3
"""Standalone SC courts backfill — runs the SC Public Index SEARCH page
for all 7 Upstate counties with a 365-day lookback, then matches results
by case_number to backfill missing plaintiff/defendant on the current board.

Runs in PARALLEL with the main pipeline. Does NOT touch the live board
until the very end (atomic rename).

Root cause being addressed:
  1. The enrichment_courts.py used ?Case= (wrong param) — case detail pages
     return 400/406 regardless. Even with ?CaseNum=, the F5/Shape WAF blocks
     case detail pages entirely (ERR_HTTP_RESPONSE_CODE_FAILURE at goto level).
  2. The scraper's SEARCH page approach WORKS (200 OK) — it accepts the
     disclaimer, fills the form, and gets results with plaintiff/defendant
     in the grid's title attributes.
  3. But the scraper timed out this run (only got Spartanburg 209 rows).
     The carryover has data from yesterday (3698 records) but 2,334 SC cases
     are still missing plaintiff.

This script re-runs the search for ALL 7 counties with a 365-day lookback
to maximise coverage, then backfills.
"""
import asyncio
import json
import os
import sys
import time
from pathlib import Path

# ── path setup ──────────────────────────────────────────────────────────
BASE = Path.home() / "foreclosure-scraper"
sys.path.insert(0, str(BASE / "src"))
sys.path.insert(0, str(BASE / ".venv/lib/python3.12/site-packages"))

# ── set env for longer lookback ─────────────────────────────────────────
os.environ["FORECLOSURE_SC_PI_DAYS"] = "365"  # 1 year lookback (vs default 45)

# ── import the scraper's own code ───────────────────────────────────────
from foreclosure_scraper.scrapers.counties_sc.sc_public_index import (
    _scrape_county, COUNTIES, _parse_results, _format_cp_case,
)
from foreclosure_scraper.scrapers.counties_sc.sc_public_index_lis_pendens import (
    COUNTIES as LP_COUNTIES,
)

BOARD_PATH = BASE / "docs" / "listings.json"
OUTPUT_PATH = BASE / "docs" / "listings_sc_backfill.json"

async def run_backfill():
    print("════════════════════════════════════════════════════════════════")
    print("SC Courts Backfill — Search Page Approach (365-day lookback)")
    print("════════════════════════════════════════════════════════════════")
    
    # Step 1: Run the scraper's search for each county
    all_results = {}  # case_number → {plaintiff, defendant, county, ...}
    
    for i, county in enumerate(COUNTIES):
        print(f"\n[{i+1}/{len(COUNTIES)}] Scraping {county} County...")
        t0 = time.time()
        try:
            listings = await _scrape_county(county)
            elapsed = time.time() - t0
            print(f"  ✓ {len(listings)} rows in {elapsed:.1f}s")
            for li in listings:
                cn = (li.case_number or "").replace(" ", "").upper()
                if cn:
                    all_results[cn] = {
                        "plaintiff": li.plaintiff,
                        "defendant": li.defendant,
                        "county": county,
                        "case_number": li.case_number,
                    }
        except Exception as e:
            elapsed = time.time() - t0
            print(f"  ✗ Error after {elapsed:.1f}s: {e}")
        
        # Polite pause between counties
        if i < len(COUNTIES) - 1:
            print(f"  ...pausing 3s...")
            await asyncio.sleep(3)
    
    print(f"\n════════════════════════════════════════════════════════════════")
    print(f"Search complete: {len(all_results)} unique cases with data")
    
    # Step 2: Load the current board
    print(f"\nLoading board: {BOARD_PATH}")
    with open(BOARD_PATH) as f:
        board = json.load(f)
    print(f"  Board has {len(board)} listings")
    
    # Step 3: Find SC listings missing plaintiff, match by case_number
    sc_listings = [l for l in board if l.get("state") == "SC"]
    sc_with_case = [l for l in sc_listings if l.get("case_number")]
    print(f"  SC listings: {len(sc_listings)}")
    print(f"  SC with case_number: {len(sc_with_case)}")
    
    missing_plaintiff = [l for l in sc_with_case if not l.get("plaintiff")]
    missing_defendant = [l for l in sc_with_case if not l.get("defendant")]
    print(f"  SC missing plaintiff: {len(missing_plaintiff)}")
    print(f"  SC missing defendant: {len(missing_defendant)}")
    
    # Step 4: Backfill
    filled_plaintiff = 0
    filled_defendant = 0
    filled_both = 0
    
    for li in sc_with_case:
        cn = (li.get("case_number") or "").replace(" ", "").upper()
        match = all_results.get(cn)
        if not match:
            continue
        
        if not li.get("plaintiff") and match.get("plaintiff"):
            li["plaintiff"] = match["plaintiff"]
            filled_plaintiff += 1
        if not li.get("defendant") and match.get("defendant"):
            li["defendant"] = match["defendant"]
            filled_defendant += 1
        if match.get("plaintiff") and match.get("defendant"):
            filled_both += 1
    
    print(f"\n════════════════════════════════════════════════════════════════")
    print(f"Backfill results:")
    print(f"  Plaintiff filled: {filled_plaintiff}")
    print(f"  Defendant filled: {filled_defendant}")
    print(f"  Both filled:      {filled_both}")
    
    # Step 5: Save the updated board
    # Write to a SEPARATE file — the main pipeline will merge this later
    # But also save the updated full board for direct use
    print(f"\nSaving backfill data to: {OUTPUT_PATH}")
    with open(OUTPUT_PATH, "w") as f:
        json.dump({
            "updated_sc_listings": [
                li for li in sc_with_case 
                if (li.get("case_number") or "").replace(" ", "").upper() in all_results
            ],
            "case_data": all_results,
            "stats": {
                "counties_scraped": len(COUNTIES),
                "cases_found": len(all_results),
                "plaintiff_filled": filled_plaintiff,
                "defendant_filled": filled_defendant,
            },
        }, f)
    
    # Also save the full updated board
    FULL_PATH = BASE / "docs" / "listings.json.sc_backfill"
    print(f"Saving full updated board to: {FULL_PATH}")
    with open(FULL_PATH, "w") as f:
        json.dump(board, f)
    
    print(f"\n✅ Backfill complete!")
    print(f"   Cases found:     {len(all_results)}")
    print(f"   Plaintiff filled: {filled_plaintiff}")
    print(f"   Defendant filled: {filled_defendant}")
    print(f"   Board saved to:   {FULL_PATH}")
    print(f"   Backfill data:    {OUTPUT_PATH}")
    
    return filled_plaintiff, filled_defendant

if __name__ == "__main__":
    asyncio.run(run_backfill())
