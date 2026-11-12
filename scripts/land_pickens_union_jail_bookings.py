#!/usr/bin/env python3
"""One-time landing: run the two newly-discovered Zuercher Portal jail-booking sources
(Pickens SC, Union SC -- found 2026-10-22 via a subdomain-pattern discovery sweep against the
project's own 18-county footprint, following the jail_bookings identity fix) and append their
results onto the board.

Scoped to these two counties alone, not the full JailBookingsScraper.fetch() (which would also
re-scrape the other 9 pre-existing ROSTERS entries) -- Pickens/Union are brand new, so there is
no existing-board-row collision risk the other 6 fixed counties still have (see
land_york_jail_bookings.py's own docstring for that separate, deferred concern).

    python scripts/land_pickens_union_jail_bookings.py --dry-run
    BOARD_PATCH_ALLOW_LARGE=1 python scripts/land_pickens_union_jail_bookings.py
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
from foreclosure_scraper.scrapers.national.jail_bookings import (  # noqa: E402
    ROSTERS, _fetch_roster, _to_listing,
)
from foreclosure_scraper.web_artifact import (  # noqa: E402
    append_new_rows, board_lock, board_patch_size_state,
)

TARGETS = [r for r in ROSTERS if r[1] in ("Pickens", "Union")]


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

    listings: list[Listing] = []
    for state, county, vendor, target in TARGETS:
        print(f"fetching {state}/{county} via {vendor}...")
        recs = asyncio.run(_fetch_roster(state, county, vendor, target))
        print(f"  fetched {len(recs)} inmate records")
        listings.extend(_to_listing(rec, state, county) for rec in recs)

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
            print(" ", li.county, li.defendant, li.case_number, li.description)
        return 0
    if not new_listings:
        print("nothing new to append.")
        return 0

    with board_lock(REPO, owner="land_pickens_union_jail_bookings", wait=600, poll=10):
        stats = append_new_rows(
            new_listings, {"national.jail_bookings": len(new_listings)}, docs_dir=docs_dir)
    print(f"append_new_rows: {stats}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
