#!/usr/bin/env python3
"""One-time landing for public_notices.funeral_home_rss.py (FuneralHomeRss -- already wired in
main.py's scraper list; a ROLLING current-obituaries RSS snapshot, not a static historical
dataset) and append its genuinely-new listings onto the board.

FOUND 2026-10-22, checking why gap_matrix flagged atty_obituary_match as "code covers this
county but nothing landed here" for Berkeley SC: the real producer (funeral_home_rss.py, a
real Frazer-CMS obituary RSS feed, dial-murrayfuneralhome.com) works fine live -- 18 current
Berkeley obituaries -- but ZERO rows from this source existed anywhere on the board, for any
of its ~20 covered counties, despite being wired. Since this is a rolling snapshot (today's
obituaries only), ongoing freshness depends on the daily pipeline actually reaching this
scraper each run -- not re-investigated here; this script only lands TODAY's real catch.

    python scripts/land_funeral_home_rss.py --dry-run
    BOARD_PATCH_ALLOW_LARGE=1 BOARD_APPEND_ALLOW_LARGE=1 \
        python scripts/land_funeral_home_rss.py --allow-large
"""
from __future__ import annotations

import argparse
import asyncio
import os
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "src"))

from foreclosure_scraper.board_stream import iter_board_rows  # noqa: E402
from foreclosure_scraper.models import Listing  # noqa: E402
from foreclosure_scraper.scrapers.public_notices.funeral_home_rss import FuneralHomeRss  # noqa: E402
from foreclosure_scraper.web_artifact import (  # noqa: E402
    append_new_rows, board_lock, board_patch_size_state,
)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--allow-large", action="store_true")
    args = ap.parse_args()

    docs_dir = REPO / "docs"
    if not args.dry_run:
        size_state = board_patch_size_state(docs_dir)
        if not size_state["ok"] and not args.allow_large:
            print(f"REFUSING: {size_state['reason']}. Re-run with --allow-large.")
            return 1
        if args.allow_large:
            os.environ["BOARD_PATCH_ALLOW_LARGE"] = "1"

    print("fetching current funeral-home obituary RSS feeds...")
    listings = asyncio.run(FuneralHomeRss().fetch())
    print(f"fetched {len(listings)} candidate listings")
    if not listings:
        print("nothing to land.")
        return 0

    print("checking against existing board for already-known keys...")
    existing_keys: set[str] = set()
    for rec in iter_board_rows(docs_dir / "listings.json.gz"):
        light = Listing.model_construct(**{
            k: rec.get(k) for k in
            ("state", "county", "parcel_id", "street_address", "zip_code",
             "case_number", "source_url", "listing_type")
        })
        try:
            existing_keys.add(light.dedupe_key())
        except Exception:  # noqa: BLE001
            continue

    new_listings = []
    seen = set()
    for li in listings:
        try:
            key = li.dedupe_key()
        except Exception:  # noqa: BLE001
            continue
        if key in existing_keys or key in seen:
            continue
        seen.add(key)
        new_listings.append(li)

    print(f"genuinely new (not already on board): {len(new_listings)} of {len(listings)}")
    if args.dry_run:
        print("DRY RUN -- nothing written.")
        for li in new_listings[:3]:
            print(" ", li.county, li.state, li.owner_name, li.defendant)
        return 0
    if not new_listings:
        print("nothing new to append.")
        return 0

    with board_lock(REPO, owner="land_funeral_home_rss", wait=900, poll=10):
        stats = append_new_rows(
            new_listings, {"public_notices.funeral_home_rss": len(new_listings)},
            docs_dir=docs_dir)
    print(f"append_new_rows: {stats}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
