#!/usr/bin/env python3
"""Recompute equity on all listings with assessed values."""
import os, sys, json
HOME = os.path.expanduser("~")
sys.path.insert(0, os.path.join(HOME, "foreclosure-scraper", "src"))
sys.path.insert(0, os.path.join(HOME, "foreclosure-scraper", ".venv", "lib", "python3.12", "site-packages"))

from foreclosure_scraper.web_artifact import load_board, write_artifact
from foreclosure_scraper.enrichment_equity import enrich_equity

def main():
    print("[1] Loading board...")
    listings = load_board()
    print(f"    Board: {len(listings)} listings")

    # Count pre-existing equity
    pre = sum(1 for li in listings if isinstance(li.raw, dict) and li.raw.get("equity"))
    have_av = sum(1 for li in listings if li.assessed_value and li.assessed_value > 0)
    print(f"    Pre-existing equity: {pre}")
    print(f"    Have assessed_value: {have_av}")

    print("\n[2] Running equity recompute...")
    result = enrich_equity(listings)
    print(f"    Result: {result}")

    # Count post
    post = sum(1 for li in listings if isinstance(li.raw, dict) and li.raw.get("equity"))
    print(f"    Post equity: {post}")
    print(f"    Delta: +{post - pre}")

    print("\n[3] Saving board...")
    write_artifact(listings, {})
    print(f"\n✅ DONE: equity {pre} -> {post}")

if __name__ == "__main__":
    main()
