#!/usr/bin/env python3
"""One-time catch-up for counties_nc.gastonia_code_enforcement.py's condemned signal.

FOUND 2026-10-23: the board's 1,167 existing gastonia_code_enforcement rows show ZERO
raw.condemned=True, despite the scraper's own code already detecting it (a "vacate"/"demolish"
match on an OPEN case's Status, see _CONDEMNED_STATUS_RE). A live re-check confirmed the code
works correctly -- 10 real condemnation-level cases exist right now (Order to Demolish/Vacate
on open Housing cases) -- the board data was just stale relative to the live site, not a code
bug. Also found FORECLOSURE_GASTONIA_CODE_DESCRIPTIONS=0 (an existing flag) skips the slow
per-case free-text description fetch, which the condemned determination never needed anyway
(Status comes from the bulk spatial-query response) -- this takes the fetch from 30+ minutes
down to under 2.

Appends genuinely-new listings and patches existing Gaston rows that gain condemned=True.

    FORECLOSURE_GASTONIA_CODE_DESCRIPTIONS=0 python scripts/land_gaston_condemned.py --dry-run
    FORECLOSURE_GASTONIA_CODE_DESCRIPTIONS=0 BOARD_PATCH_ALLOW_LARGE=1 BOARD_APPEND_ALLOW_LARGE=1 \
        python scripts/land_gaston_condemned.py --allow-large
"""
from __future__ import annotations

import argparse
import asyncio
import os
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "src"))

os.environ.setdefault("FORECLOSURE_GASTONIA_CODE_DESCRIPTIONS", "0")

from foreclosure_scraper.board_stream import iter_board_rows  # noqa: E402
from foreclosure_scraper.models import Listing  # noqa: E402
from foreclosure_scraper.scrapers.counties_nc.gastonia_code_enforcement import (  # noqa: E402
    GastoniaCodeEnforcement,
)
from foreclosure_scraper.web_artifact import (  # noqa: E402
    append_new_rows, board_lock, board_patch_size_state, patch_existing_rows,
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

    print("fetching Gastonia code-enforcement cases (descriptions skipped)...")
    listings = asyncio.run(GastoniaCodeEnforcement().fetch())
    print(f"fetched {len(listings)} candidate listings")
    if not listings:
        print("nothing to land.")
        return 0

    print("checking against existing Gaston board rows...")
    existing_keys: set[str] = set()
    existing_raw: dict[str, dict] = {}
    for rec in iter_board_rows(docs_dir / "listings.json.gz"):
        if (rec.get("county") or "").strip() != "Gaston":
            continue
        light = Listing.model_construct(**{
            k: rec.get(k) for k in
            ("state", "county", "parcel_id", "street_address", "zip_code",
             "case_number", "source_url", "listing_type")
        })
        try:
            key = light.dedupe_key()
        except Exception:  # noqa: BLE001
            continue
        existing_keys.add(key)
        if key not in existing_raw:
            existing_raw[key] = rec.get("raw") if isinstance(rec.get("raw"), dict) else {}

    new_listings = []
    patches: dict[str, dict] = {}
    seen = set()
    for li in listings:
        try:
            key = li.dedupe_key()
        except Exception:  # noqa: BLE001
            continue
        if key in seen:
            continue
        seen.add(key)
        if key not in existing_keys:
            new_listings.append(li)
            continue
        old_raw = existing_raw.get(key) or {}
        if not old_raw.get("condemned") and li.raw.get("condemned"):
            patches[key] = {"raw": {
                "condemned": True,
                "code_enforcement": li.raw["code_enforcement"],
                "vacancy": li.raw.get("vacancy"),
                "distressed": True,
            }}

    print(f"genuinely new rows to append: {len(new_listings)}")
    print(f"existing rows to patch (newly gain condemned=True): {len(patches)}")
    if args.dry_run:
        print("DRY RUN -- nothing written.")
        for li in new_listings[:3]:
            print("  NEW:", li.street_address, li.raw.get("condemned"))
        for key, p in list(patches.items())[:3]:
            print("  PATCH:", key)
        return 0

    with board_lock(REPO, owner="land_gaston_condemned", wait=1200, poll=10):
        if new_listings:
            astats = append_new_rows(
                new_listings, {"counties_nc.gastonia_code_enforcement": len(new_listings)},
                docs_dir=docs_dir)
            print(f"append_new_rows: {astats}")
        if patches:
            pstats = patch_existing_rows(
                patches, {"land_gaston_condemned": len(patches)}, docs_dir=docs_dir)
            print(f"patch_existing_rows: {pstats}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
