#!/usr/bin/env python3
"""Catch-up append for city_websites.charlotte_open_data.py -- SCOPED, after
discovering a real identity-model limitation (see below), not the full
refresh this file first attempted.

FOUND 2026-10-23: while researching Mecklenburg's "condemned"/"vacancy"/
"code_enforcement" gap_matrix entries (144+ counties flagged "no source
known"), found the real source already exists, is already wired into
main.py, and is already landing ~5,196 rows. Live-tested the scraper
directly: 2,897 currently-open cases, 1,020 of them (by CaseNumber) not yet
on the board at all.

IDENTITY-MODEL LIMITATION (found live, not theorized): this scraper
deliberately emits ONE ROW PER CASE, and a single Mecklenburg parcel can
legitimately carry several separate cases over time (confirmed: parcel
08114106 already holds 2 board rows under different case numbers, a real
duplex). But Listing.dedupe_key() checks parcel_id FIRST and returns on it
immediately -- case_number is only consulted when parcel_id is absent. Both
append_new_rows() (via dedupe.py's _strong_sigs(), whose "p" parcel
signature is state-scoped, not even county) and patch_existing_rows()
(which recomputes dedupe_key() from parcel_id internally and has no way to
take a caller-supplied finer key) collapse by parcel_id, not by case. Of the
1,020 genuinely-new cases, 370 share a parcel_id with an EXISTING board row
under a DIFFERENT case -- appending or patching those through the normal
mechanisms risks either a silent false-duplicate drop or, worse, a patch
landing one case's data on another case's row. This is a real, pre-existing
limitation of how this source's many-cases-per-parcel shape interacts with
the board's parcel-first identity scheme (not something this run
introduces -- main.py's own regular pipeline pass hits the exact same
collision every time it re-runs this scraper), not a quick fix.

SCOPED TO WHAT IS SAFE TONIGHT: only the 650 of 1,020 new cases that are the
FIRST case ever landed for their parcel (no existing board row shares that
parcel_id) are appended here -- zero collision risk, confirmed by direct
set comparison against every existing city_websites.charlotte_open_data
board row's parcel_id before fetching.

NOT done here (documented, not forced):
  - The 370 colliding new cases (second+ case at an already-represented
    parcel) -- appending them risks append_new_rows() treating them as a
    duplicate of the unrelated existing case and silently dropping them.
  - The vacancy/gis.vacant backfill-patch for the board's 14-15 existing
    condemned=True rows from the pre-2026-10-20-fix scrape -- patching by
    dedupe_key() would apply the SAME patch value to every row sharing that
    parcel's key, which is wrong when more than one case shares the parcel.
  A real fix needs either a per-case patch primitive keyed on
  (parcel_id, case_number) rather than dedupe_key() alone, or accepting that
  this source caps at one row per parcel and reconciling multi-case parcels
  deliberately (e.g. folding every case for one parcel into one row's
  violations list, the way build_listing() already aggregates CASE HISTORY
  in gastonia_code_enforcement.py-style modules) -- a real design decision,
  not a backfill script's call to make silently.

    python scripts/land_charlotte_open_data_refresh.py --dry-run
    BOARD_PATCH_ALLOW_LARGE=1 python scripts/land_charlotte_open_data_refresh.py --allow-large
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
from foreclosure_scraper.scrapers.city_websites.charlotte_open_data import (  # noqa: E402
    CharlotteOpenData,
)
from foreclosure_scraper.web_artifact import (  # noqa: E402
    append_new_rows, board_lock, board_patch_size_state,
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
            os.environ["BOARD_APPEND_ALLOW_LARGE"] = "1"

    print("fetching live charlotte_open_data...")
    listings = asyncio.run(CharlotteOpenData().safe_run())
    print(f"fetched {len(listings)} live open cases")
    if not listings:
        print("nothing to land.")
        return 0

    print("scanning existing board for this source's case numbers + parcel ids...")
    existing_cases: set[str] = set()
    existing_parcels: set[str] = set()
    for rec in iter_board_rows(docs_dir / "listings.json.gz"):
        if rec.get("source") != SOURCE_SLUG:
            continue
        if rec.get("case_number"):
            existing_cases.add(rec["case_number"])
        if rec.get("parcel_id"):
            existing_parcels.add(rec["parcel_id"])

    new_cases = [li for li in listings if li.case_number and li.case_number not in existing_cases]
    seen_case: set[str] = set()
    safe_new: list = []
    colliding = 0
    for li in new_cases:
        if li.case_number in seen_case:
            continue
        seen_case.add(li.case_number)
        if li.parcel_id and li.parcel_id in existing_parcels:
            colliding += 1
            continue
        safe_new.append(li)

    print(f"genuinely new cases: {len(seen_case)}")
    print(f"  colliding with an existing parcel under a different case (SKIPPED): {colliding}")
    print(f"  first case ever for their parcel (safe to append): {len(safe_new)}")
    if args.dry_run:
        print("DRY RUN -- nothing written.")
        for li in safe_new[:5]:
            print("  NEW:", li.case_number, li.street_address, "condemned=", li.raw.get("condemned"))
        return 0
    if not safe_new:
        print("nothing safe to append.")
        return 0

    with board_lock(REPO, owner="land_charlotte_open_data_refresh", wait=6000, poll=10):
        astats = append_new_rows(safe_new, {SOURCE_SLUG: len(safe_new)}, docs_dir=docs_dir)
        print(f"append_new_rows: {astats}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
