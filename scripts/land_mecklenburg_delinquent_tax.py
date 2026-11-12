#!/usr/bin/env python3
"""One-time landing: enable and run counties_nc.mecklenburg_delinquent_tax.py
(MecklenburgDelinquentTax -- Mecklenburg County's own NCGS 105-369 statutory advertisement of
unpaid real-property taxes, 43,355 rows / $35.5M due, already wired in main.py's scraper list
but deliberately OFF by default) and append its genuinely-new, parcel-resolved listings onto
the board.

WHY IT DEFAULTS OFF (this module's own docstring): the geocode cost isn't bounded by this
module itself -- turning it on feeds ~29,000 parcel-resolved rows (no lat/lng; the cache has
none) into the board's shared, budget-capped geocode step (GEOCODE_BUDGET_S), competing with
every other source. That's a real resource-allocation tradeoff, not a bug -- decided 2026-10-23
to enable it: the geocode budget is already a safety valve (it throttles the whole pipeline,
not just this source), and the expected value (21,059 genuinely new real tax-lien leads for
NC's largest county, free, legally-mandated, no login/CAPTCHA) is clearly positive. Landing now
does NOT itself consume geocode budget -- it appends rows with resolved parcel/address and no
coordinates yet; the normal daily pipeline's geocode step picks them up over subsequent runs,
same as any other newly-landed address-only row.

    FORECLOSURE_MECKLENBURG_DELINQUENT=1 python scripts/land_mecklenburg_delinquent_tax.py --dry-run
    FORECLOSURE_MECKLENBURG_DELINQUENT=1 BOARD_PATCH_ALLOW_LARGE=1 BOARD_APPEND_ALLOW_LARGE=1 \
        python scripts/land_mecklenburg_delinquent_tax.py --allow-large
"""
from __future__ import annotations

import argparse
import asyncio
import os
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "src"))

os.environ.setdefault("FORECLOSURE_MECKLENBURG_DELINQUENT", "1")

from foreclosure_scraper.board_stream import iter_board_rows  # noqa: E402
from foreclosure_scraper.models import Listing  # noqa: E402
from foreclosure_scraper.scrapers.counties_nc.mecklenburg_delinquent_tax import (  # noqa: E402
    MecklenburgDelinquentTax,
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

    print("fetching Mecklenburg's delinquent-tax advertisement, resolving against parcel_cache...")
    listings = asyncio.run(MecklenburgDelinquentTax().fetch())
    print(f"fetched {len(listings)} parcel-resolved candidate listings")
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
            print(" ", li.defendant, li.street_address, li.raw.get("mecklenburg_delinquent_tax", {}).get("total_due"))
        return 0
    if not new_listings:
        print("nothing new to append.")
        return 0

    with board_lock(REPO, owner="land_mecklenburg_delinquent_tax", wait=1200, poll=10):
        stats = append_new_rows(
            new_listings, {"counties_nc.mecklenburg_delinquent_tax": len(new_listings)},
            docs_dir=docs_dir)
    print(f"append_new_rows: {stats}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
