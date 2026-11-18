#!/usr/bin/env python3
"""Landing script for NcItsPublicTax scoped to Moore NC (round 20, 2026-11-17 finding).

WHY THIS EXISTS. counties_nc/nc_its_public_tax.py's PORTALS dict has carried a real,
wired Moore NC entry since round 18 (live-confirmed 3 separate years of real unpaid
bills -- 2,445/1,562/643 records) -- but round 20 found Moore has never landed a
single row on the board. Root cause, from the scraper's own fetch() docstring
comment ("round-robin-starvation"): its global timeout_s (3300s) divided across
~16 PORTALS counties at up to 420s each can exhaust before a late-rotation county is
ever reached in a given day's run, and the starting county rotates by
date.today().toordinal() -- Moore can go days without being reached by sheer
rotation luck, with zero indication anything is broken. The module's own
ITS_TAX_COUNTIES env var exists exactly to bypass this: scope a run to one county
so it is never starved by its siblings' own budget.

Appends only genuinely-new rows -- a hit landing on a parcel already represented by
some OTHER producer's row is skipped (fill-only Listing.merge() semantics would keep
that row's existing data regardless, so forcing a merge would not move this
column's real count -- same reasoning as land_sc_wthgis_heir_estate.py's own
docstring).

BOARD I/O: one streaming read-only pass (board_stream.iter_board_rows()) to build
the existing-keys set; board_lock() wraps ONLY the final append_new_rows() write,
real absolute repo path. Never load_board().

    python scripts/land_moore_its_public_tax.py --dry-run
    BOARD_PATCH_ALLOW_LARGE=1 BOARD_APPEND_ALLOW_LARGE=1 \
        python scripts/land_moore_its_public_tax.py --allow-large
"""
from __future__ import annotations

import argparse
import asyncio
import os
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "src"))

os.environ["ITS_TAX_COUNTIES"] = "Moore"

from foreclosure_scraper.board_stream import iter_board_rows  # noqa: E402
from foreclosure_scraper.models import Listing  # noqa: E402
from foreclosure_scraper.scrapers.counties_nc.nc_its_public_tax import (  # noqa: E402
    NcItsPublicTax,
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
            os.environ["BOARD_APPEND_ALLOW_LARGE"] = "1"

    print("fetching NcItsPublicTax scoped to Moore (ITS_TAX_COUNTIES=Moore)...")
    s = NcItsPublicTax()
    listings = asyncio.run(s.safe_run())
    print(f"outcome={s.last_outcome} reason={s.last_reason!r} classified={len(listings)} "
          f"stats={getattr(s, 'county_stats', {})}")
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
            print(" ", li.county, li.parcel_id, li.owner_name)
        return 0
    if not new_listings:
        print("nothing new to append.")
        return 0

    with board_lock(REPO, owner="land_moore_its_public_tax", wait=900, poll=10):
        stats = append_new_rows(
            new_listings, {"counties_nc.nc_its_public_tax": len(new_listings)},
            docs_dir=docs_dir)
    print(f"append_new_rows: {stats}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
