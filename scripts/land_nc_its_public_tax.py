#!/usr/bin/env python3
"""Landing script for NcItsPublicTax, scoped to one or more counties via --county
(generalized from the original Moore-only land_moore_its_public_tax.py, round 20b,
2026-11-17 -- same script, renamed and parameterized after finding the same gap in
a second county).

WHY THIS EXISTS. counties_nc/nc_its_public_tax.py's PORTALS dict wires 15 NC
counties, but its fetch()'s own documented "round-robin-starvation" shape (a global
3300s timeout divided across all counties at up to COUNTY_BUDGET_S=420s each, with
the rotation start picked by date.today().toordinal()) means a county can go
indefinitely without ever being reached in a normal full run -- silently, with no
error. Round 20 found Moore (0 rows landed despite being wired since round 18/19);
checking EVERY PORTALS county's actual board-row count the same way found Carteret
as a second, even starker case (13 rows vs its peers' 322-3,829). The module's own
ITS_TAX_COUNTIES env var exists exactly to bypass this for one or more counties at
a time; ITS_TAX_COUNTY_BUDGET_S (default 420) can be raised too, for a
high-volume county (Carteret's own per-year page count is large enough that even a
single-county scoped run can still exhaust the default 420s mid-way through its
history -- live-confirmed truncated=True at year 2022 on a first attempt).

Appends only genuinely-new rows -- a hit landing on a parcel already represented by
some OTHER producer's row is skipped (fill-only Listing.merge() semantics would keep
that row's existing data regardless -- same reasoning as land_sc_wthgis_heir_estate.py's
own docstring).

BOARD I/O: one streaming read-only pass (board_stream.iter_board_rows()) to build
the existing-keys set; board_lock() wraps ONLY the final append_new_rows() write,
real absolute repo path. Never load_board().

    python scripts/land_nc_its_public_tax.py --county Moore --dry-run
    python scripts/land_nc_its_public_tax.py --county Carteret --county-budget-s 1800 --dry-run
    BOARD_PATCH_ALLOW_LARGE=1 BOARD_APPEND_ALLOW_LARGE=1 \
        python scripts/land_nc_its_public_tax.py --county Carteret --county-budget-s 1800 --allow-large
"""
from __future__ import annotations

import argparse
import asyncio
import os
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "src"))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--county", action="append", required=True,
                     help="county name, repeatable (e.g. --county Moore --county Carteret)")
    ap.add_argument("--county-budget-s", type=float, default=None,
                     help="override ITS_TAX_COUNTY_BUDGET_S (default 420) for "
                          "high-volume counties that truncate at the default")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--allow-large", action="store_true")
    args = ap.parse_args()

    os.environ["ITS_TAX_COUNTIES"] = ",".join(args.county)
    if args.county_budget_s:
        os.environ["ITS_TAX_COUNTY_BUDGET_S"] = str(args.county_budget_s)

    from foreclosure_scraper.board_stream import iter_board_rows
    from foreclosure_scraper.models import Listing
    from foreclosure_scraper.scrapers.counties_nc.nc_its_public_tax import NcItsPublicTax
    from foreclosure_scraper.web_artifact import (
        append_new_rows, board_lock, board_patch_size_state,
    )

    docs_dir = REPO / "docs"
    if not args.dry_run:
        size_state = board_patch_size_state(docs_dir)
        if not size_state["ok"] and not args.allow_large:
            print(f"REFUSING: {size_state['reason']}. Re-run with --allow-large.")
            return 1
        if args.allow_large:
            os.environ["BOARD_PATCH_ALLOW_LARGE"] = "1"
            os.environ["BOARD_APPEND_ALLOW_LARGE"] = "1"

    print(f"fetching NcItsPublicTax scoped to {args.county} "
          f"(ITS_TAX_COUNTIES={os.environ['ITS_TAX_COUNTIES']})...")
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

    with board_lock(REPO, owner="land_nc_its_public_tax", wait=900, poll=10):
        stats = append_new_rows(
            new_listings, {"counties_nc.nc_its_public_tax": len(new_listings)},
            docs_dir=docs_dir)
    print(f"append_new_rows: {stats}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
