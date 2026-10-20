#!/usr/bin/env python3
"""Ingest sc_heir_estate_parcel_cache.py's Williamsburg SC rows onto the live board.

The producer has no per-county scope flag -- it iterates every SC county whose
parcel_cache entry carries an owner field (_candidate_counties()). Williamsburg
was added to PARCEL_LAYERS tonight (commit f2b7c673), so this run will also
re-walk every other already-covered county; filtered to Williamsburg only
before landing anything, so no other county's rows are touched here.

Uses patch_existing_rows()/append_new_rows() (never load_board()/write_artifact()),
same convention as scripts/ingest_johnston_tax_crosswalk.py.

    python scripts/ingest_williamsburg_heir_estate.py --dry-run
    python scripts/ingest_williamsburg_heir_estate.py
"""
from __future__ import annotations

import argparse
import asyncio
import contextlib
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
    _APPEND_SIG_FIELDS,
    append_new_rows,
    board_lock,
    patch_existing_rows,
)

_IS_WB = lambda li_or_dict: (
    str(li_or_dict.county if hasattr(li_or_dict, "county") else li_or_dict.get("county") or "").strip().lower()
    == "williamsburg"
    and str(li_or_dict.state if hasattr(li_or_dict, "state") else li_or_dict.get("state") or "").upper() == "SC"
)


async def _fetch_new():
    s = SCHeirEstateParcelCache()
    rows = list(await s.safe_run())
    print(f"scraper outcome: {s.last_outcome}; total rows all counties: {len(rows)}")
    wb_rows = [li for li in rows if _IS_WB(li)]
    print(f"Williamsburg SC rows: {len(wb_rows)}")
    return wb_rows


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    new_rows = asyncio.run(_fetch_new())
    if not new_rows:
        print("nothing scraped for Williamsburg -- aborting.")
        return 1

    existing_keys: dict[str, dict] = {}
    for rec in iter_board_rows(REPO / "docs" / "listings.json.gz"):
        if not _IS_WB(rec):
            continue
        li = Listing.model_construct(**{k: rec.get(k) for k in _APPEND_SIG_FIELDS if k in rec})
        existing_keys[li.dedupe_key()] = rec
    print(f"existing Williamsburg SC dedupe_keys on board: {len(existing_keys)}")

    patches: dict[str, dict] = {}
    appends: list[Listing] = []
    seen_this_run: set[str] = set()
    for li in new_rows:
        key = li.dedupe_key()
        if key in seen_this_run:
            continue
        seen_this_run.add(key)
        if key in existing_keys:
            patches[key] = {"raw": li.raw}
        else:
            appends.append(li)

    print(f"\nclassified {len(new_rows)} heir_estate leads:")
    print(f"  merge into an EXISTING board row (patch): {len(patches)}")
    print(f"  genuinely NEW board rows (append):        {len(appends)}")

    if args.dry_run:
        print("\nDRY RUN -- nothing written.")
        return 0

    with board_lock(REPO, owner="williamsburg_heir_estate_ingest"):
        if patches:
            pstats = patch_existing_rows(patches, {"williamsburg_heir_estate_patch": len(patches)},
                                         docs_dir=REPO / "docs")
            print("patch_existing_rows:", pstats)
        if appends:
            astats = append_new_rows(appends, {"williamsburg_heir_estate_append": len(appends)},
                                     docs_dir=REPO / "docs")
            print("append_new_rows:", astats)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
