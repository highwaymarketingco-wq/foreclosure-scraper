#!/usr/bin/env python3
"""Landing script for counties_sc.sc_wthgis_heir_estate.py (SCWthgisHeirEstate --
round 18, 2026-11-17, closing part of gap_matrix's lt_estate_lead "no source known"
bucket for Chesterfield SC). Runs the live WTH decedent/life-estate sweep and
appends only the genuinely-new listings onto the board -- same discipline as its
direct sibling, land_sc_heir_estate_parcel_cache.py: a hit that lands on a parcel
already represented by some OTHER producer's row is skipped, not merged (fill-only
Listing.merge() would keep that row's existing listing_type regardless, so forcing
the merge would not move this column's real count -- see the scraper module's own
docstring for the full reasoning this script relies on).

    python scripts/land_sc_wthgis_heir_estate.py --dry-run
    BOARD_PATCH_ALLOW_LARGE=1 BOARD_APPEND_ALLOW_LARGE=1 \
        python scripts/land_sc_wthgis_heir_estate.py --allow-large
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
from foreclosure_scraper.scrapers.counties_sc.sc_wthgis_heir_estate import (  # noqa: E402
    SCWthgisHeirEstate,
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

    print("sweeping chesterfieldsc.wthgis.com for heir/estate/life-estate owners...")
    s = SCWthgisHeirEstate()
    listings = asyncio.run(s.safe_run())
    print(f"outcome={s.last_outcome} reason={s.last_reason!r} classified={len(listings)} "
          f"stats={s.run_stats}")
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
    seen: set[str] = set()
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
        for li in new_listings[:5]:
            print(" ", li.county, li.defendant, li.parcel_id)
        return 0
    if not new_listings:
        print("nothing new to append.")
        return 0

    with board_lock(REPO, owner="land_sc_wthgis_heir_estate", wait=900, poll=10):
        stats = append_new_rows(
            new_listings, {"counties_sc.sc_wthgis_heir_estate": len(new_listings)},
            docs_dir=docs_dir)
    print(f"append_new_rows: {stats}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
