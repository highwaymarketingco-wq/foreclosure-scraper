#!/usr/bin/env python3
"""Fix the last 319 amount_owed gaps — Pickens with bad assessed values (asv=2, 7, 26).
Use sqft-based estimate instead: sqft × $50/sqft × SC tax rate (0.57%) × 2yr + 25% penalty.
Also set a minimum amount_owed of $500 for any property with sqft > 100.
"""
import os, sys, time
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "src"))
from foreclosure_scraper.web_artifact import load_board, write_artifact

DOCS = REPO / "docs"

def _set_raw(li, key, val):
    if not isinstance(li.raw, dict):
        li.raw = {}
    li.raw[key] = val

def main():
    t0 = time.time()
    print("Loading board...", flush=True)
    board = load_board(DOCS)
    n = len(board)
    print(f"Board: {n:,} listings\n")

    filled = 0
    for li in board:
        raw = li.raw if isinstance(li.raw, dict) else {}
        if raw.get("amount_owed"):
            continue

        # Last resort: use sqft to estimate
        sqft = getattr(li, "living_sqft", None)
        if sqft and sqft > 100:
            # Estimate market value from sqft × $150/sqft (conservative SC avg)
            est_mv = sqft * 150
            # SC avg tax rate 0.57%, 2yr delinquent + 25% penalty
            owed = round(est_mv * 0.0057 * 2 * 1.25)
            if owed < 500:
                owed = 500  # minimum tax lien
        else:
            # No sqft — use flat minimum
            owed = 500

        _set_raw(li, "amount_owed", {
            "value": owed,
            "source": "sqft_based_estimate",
            "confidence": "low",
            "is_actual_debt": False
        })
        filled += 1

    print(f"Filled: +{filled}")

    # Verify
    amt = sum(1 for li in board if isinstance(li.raw, dict) and li.raw.get("amount_owed"))
    print(f"Amount Owed: {amt:,} ({amt/n*100:.1f}%)")

    print("\nSaving with write_artifact()...", flush=True)
    write_artifact(board, {})
    print(f"Done! ({time.time()-t0:.1f}s)")

if __name__ == "__main__":
    main()
