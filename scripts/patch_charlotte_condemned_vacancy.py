#!/usr/bin/env python3
"""Backfill raw['vacancy']/raw['gis']['vacant'] onto the board's pre-2026-10-20-fix
charlotte_open_data condemned rows.

CONFIRMED SAFE 2026-10-23: unlike the broader charlotte_open_data refresh (see
land_charlotte_open_data_refresh.py and feedback_dedupe_key_parcel_first_collision),
all 15 of the board's current raw['condemned']=True rows from this source have
EXACTLY ONE row at their parcel_id (checked directly) -- zero dedupe_key()
collision risk, so patch_existing_rows() is safe here.

    python scripts/patch_charlotte_condemned_vacancy.py --dry-run
    BOARD_PATCH_ALLOW_LARGE=1 python scripts/patch_charlotte_condemned_vacancy.py --allow-large
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "src"))

from foreclosure_scraper.board_stream import iter_board_rows  # noqa: E402
from foreclosure_scraper.models import Listing  # noqa: E402
from foreclosure_scraper.web_artifact import (  # noqa: E402
    board_lock, board_patch_size_state, patch_existing_rows,
)

SOURCE_SLUG = "city_websites.charlotte_open_data"


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

    patches: dict[str, dict] = {}
    for rec in iter_board_rows(docs_dir / "listings.json.gz"):
        if rec.get("county") != "Mecklenburg" or rec.get("source") != SOURCE_SLUG:
            continue
        raw = rec.get("raw") if isinstance(rec.get("raw"), dict) else {}
        if not raw.get("condemned"):
            continue
        gis = raw.get("gis") if isinstance(raw.get("gis"), dict) else {}
        if raw.get("vacancy") and gis.get("vacant"):
            continue  # already has it
        light = Listing.model_construct(**{
            k: rec.get(k) for k in
            ("state", "county", "parcel_id", "street_address", "zip_code",
             "case_number", "source_url", "listing_type")})
        try:
            key = light.dedupe_key()
        except Exception:  # noqa: BLE001
            continue
        patch_raw: dict = {}
        if not raw.get("vacancy"):
            patch_raw["vacancy"] = {"vacant": True, "boarded_up": None,
                                     "utility_status": None, "source": SOURCE_SLUG}
        if not gis.get("vacant"):
            patch_raw["gis"] = {**gis, "vacant": True}
        if patch_raw:
            patches[key] = {"raw": patch_raw}

    print(f"rows to patch: {len(patches)}")
    for key, p in patches.items():
        print(" ", key, p)
    if args.dry_run:
        print("DRY RUN -- nothing written.")
        return 0
    if not patches:
        print("nothing to patch.")
        return 0

    with board_lock(REPO, owner="patch_charlotte_condemned_vacancy", wait=1800, poll=10):
        pstats = patch_existing_rows(
            patches, {"patch_charlotte_condemned_vacancy": len(patches)}, docs_dir=docs_dir)
        print(f"patch_existing_rows: {pstats}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
