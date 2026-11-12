#!/usr/bin/env python3
"""
Surface tax delinquency aging as top-level fields.

For each listing with raw.nc_ptscloud_delinquent_tax data:
  - Surface tax_year as top-level delinquent_tax_year
  - Compute delinquent_years (current_year - tax_year)
  - Flag 2+ year delinquent as high_margin (tax_aging_high = True)
  - Surface principal_tax_due as top-level delinquent_tax_amount
  - Add tax_aging_bucket: '<1yr', '1-2yr', '2-3yr', '3+yr'

Also surfaces assessed_value from nc_ptscloud_delinquent_tax to top-level
if not already set (NCPTS LRC may have already done this).
"""
import gzip, json, os, sys, time
from datetime import datetime

HOME = os.path.expanduser("~")
sys.path.insert(0, os.path.join(HOME, "foreclosure-scraper", "src"))

from foreclosure_scraper.web_artifact import load_board, write_artifact

DOCS_DIR = os.path.join(HOME, "foreclosure-scraper", "docs")
CURRENT_YEAR = datetime.now().year


def main():
    t0 = time.time()
    print("[1] Loading board...")
    board = load_board(DOCS_DIR)
    total = len(board)
    print(f"    Board: {total:,} listings")

    surfaced = 0
    high_margin = 0
    assessed_surfaced = 0

    for li in board:
        raw = li.raw if isinstance(li.raw, dict) else {}
        ncpts = raw.get("nc_ptscloud_delinquent_tax")
        if not isinstance(ncpts, dict):
            continue

        # Surface assessed_value from nc_ptscloud to top-level if not set
        if not li.assessed_value and ncpts.get("assessed_value"):
            try:
                li.assessed_value = float(ncpts["assessed_value"])
                assessed_surfaced += 1
            except (TypeError, ValueError):
                pass

        # Surface tax_year
        tax_year = ncpts.get("tax_year")
        if tax_year:
            try:
                ty = int(tax_year)
                # Store as top-level field
                if not isinstance(li.raw, dict):
                    li.raw = {}
                li.raw["delinquent_tax_year"] = ty
                delinquent_years = CURRENT_YEAR - ty
                li.raw["delinquent_years"] = delinquent_years

                # Tax aging bucket
                if delinquent_years < 1:
                    bucket = "<1yr"
                elif delinquent_years < 2:
                    bucket = "1-2yr"
                elif delinquent_years < 3:
                    bucket = "2-3yr"
                else:
                    bucket = "3+yr"
                li.raw["tax_aging_bucket"] = bucket

                # High margin flag: 2+ years delinquent = more motivated seller
                if delinquent_years >= 2:
                    li.raw["tax_aging_high"] = True
                    high_margin += 1
                else:
                    li.raw["tax_aging_high"] = False

                surfaced += 1
            except (TypeError, ValueError):
                pass

        # Surface principal_tax_due as delinquent_tax_amount
        principal = ncpts.get("principal_tax_due")
        if principal:
            try:
                if not isinstance(li.raw, dict):
                    li.raw = {}
                li.raw["delinquent_tax_amount"] = float(principal)
            except (TypeError, ValueError):
                pass

        # Also surface total_tax_due if available
        total_tax = ncpts.get("total_tax_due") or ncpts.get("total_due")
        if total_tax:
            try:
                if not isinstance(li.raw, dict):
                    li.raw = {}
                li.raw["delinquent_tax_total"] = float(total_tax)
            except (TypeError, ValueError):
                pass

    print(f"\n[2] Results:")
    print(f"    Tax year surfaced: {surfaced:,}/{total:,}")
    print(f"    Assessed value surfaced: {assessed_surfaced:,}")
    print(f"    2+ year delinquent (high margin): {high_margin:,}")

    print(f"\n[3] Saving board...")
    write_artifact(board, {"enrichment": "tax_aging_surfaced"}, DOCS_DIR)

    elapsed = time.time() - t0
    print(f"\n{'='*60}")
    print(f"COMPLETE: Tax aging surfaced for {surfaced:,} listings")
    print(f"  High-margin (2+yr delinquent): {high_margin:,}")
    print(f"  Assessed values surfaced: {assessed_surfaced:,}")
    print(f"  Time: {elapsed:.0f}s")
    print(f"{'='*60}")


if __name__ == "__main__":
    main()
