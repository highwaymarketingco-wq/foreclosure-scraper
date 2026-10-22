#!/usr/bin/env python3
"""One-time landing: run counties_sc.sc_heir_estate_parcel_cache.py (SCHeirEstateParcelCache --
already wired in main.py's scraper list, pure-local parcel_cache read, no network, calibrated
against an earlier independent sweep, see that module's own docstring) and append its
genuinely-new listings onto the board.

FOUND 2026-10-22, checking why gap_matrix flagged heir_estate as "code covers this county but
nothing landed here" for Greenville/Orangeburg/Dorchester/Jasper/Aiken/Greenwood SC (Anderson is
NOT actually covered by this producer -- parcel_cache has no 'owner' field for it; some other
mechanism or a real gap). Ran the scraper directly: it classifies 9,850 real decedent-titled
parcels across 20 SC counties, matching this module's own documented calibration (Greenville: 40,
docstring predicted 38). 2,948 of the 9,850 are genuinely new to the board (not already
represented by some other producer's listing on the same parcel) -- those land here.

The other 6,902 overlap an existing board row for the same parcel under a different signal.
Whether the heir_estate classification should be MERGED onto those existing rows (not just
dropped as a duplicate) is a separate, real question -- not attempted here; this script only
appends the standalone-new ones, exactly like every other land_*.py script tonight.

    python scripts/land_sc_heir_estate_parcel_cache.py --dry-run
    BOARD_PATCH_ALLOW_LARGE=1 BOARD_APPEND_ALLOW_LARGE=1 \
        python scripts/land_sc_heir_estate_parcel_cache.py --allow-large
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
from foreclosure_scraper.scrapers.counties_sc.sc_heir_estate_parcel_cache import (  # noqa: E402
    SCHeirEstateParcelCache,
)
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

    print("classifying heir/estate parcels from the local parcel_cache...")
    listings = asyncio.run(SCHeirEstateParcelCache().fetch())
    print(f"classified {len(listings)} candidate listings")
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
            print(" ", li.county, li.owner_name, li.parcel_id)
        return 0
    if not new_listings:
        print("nothing new to append.")
        return 0

    with board_lock(REPO, owner="land_sc_heir_estate_parcel_cache", wait=900, poll=10):
        stats = append_new_rows(
            new_listings, {"counties_sc.sc_heir_estate_parcel_cache": len(new_listings)},
            docs_dir=docs_dir)
    print(f"append_new_rows: {stats}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
