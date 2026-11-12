#!/usr/bin/env python3
"""Fix nc_ecourts_judgments' mislabeled sale_date, found 2026-09-15 during a
board-wide source/slug reconciliation (following the courtlistener.recap and
greenville_mie_adverts fixes earlier this same sweep).

3,765 real rows (lis_pendens 2978 / tax_lien 787), real counties already
set (New Hanover, Brunswick, Gaston, Cleveland, Onslow, Henderson, Lincoln,
Buncombe, Pender, Rutherford, ...), 0 scope failures -- but ALL 3,765
currently fail `_active_only()` because the structured `sale_date` field
holds the NC court system's judgment/filing date (raw.nc_ecourts.judgment_date
/ raw.nc_ecourts.raw_tyler.orderedDate -- "when was this judgment recorded",
not "when is the property being sold"). A lis pendens or tax lien doesn't
have a real-estate sale date at all; that's the whole point of these
listing types being DISTRESSED-bucket signals, not scheduled sales.

A prior enrichment pass had already half-noticed this (every row carries
`raw.sale_date_passed = True` / `raw.sale_date_passed_days`), but that
flag was never wired into the actual gate -- `_active_only()` still ran
the plain date-window check against the structured field and dropped
every row regardless.

This script clears the structured sale_date to None (the original value
already survives untouched in raw.nc_ecourts.judgment_date, no need to
duplicate it) so the DATELESS_OK_SOURCES entry just added in main.py
actually takes effect -- same fix shape as
scripts/fix_courtlistener_recap.py. Operates directly on existing board
rows; there's no live BaseScraper-subclass module for this slug to edit
(it's ingested via the standalone scripts/scrape_ncecourts.py /
scripts/ingest_all.py lane, confirmed via a repo grep before writing
this).

    python scripts/fix_nc_ecourts_judgments.py --dry-run
    python scripts/fix_nc_ecourts_judgments.py
"""
from __future__ import annotations

import argparse
import contextlib
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "src"))

from foreclosure_scraper.main import _active_only, _in_scope  # noqa: E402
from foreclosure_scraper.web_artifact import board_lock, load_board, write_artifact  # noqa: E402

HORIZON_DAYS = 120
SOURCE_SLUG = "nc_ecourts_judgments"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    lock = contextlib.nullcontext() if args.dry_run else board_lock(REPO, owner="fix_nc_ecourts_judgments")
    with lock:
        rows = load_board(REPO / "docs")
        before = len(rows)
        print(f"board rows before: {before:,}")

        fixed = 0
        for li in rows:
            if li.source != SOURCE_SLUG:
                continue
            if li.sale_date is not None:
                li.sale_date = None
                fixed += 1

        print(f"cleared structured sale_date on {fixed:,} rows "
              f"(original already preserved in raw.nc_ecourts.judgment_date)")

        target = [li for li in rows if li.source == SOURCE_SLUG]
        now_pass = sum(1 for li in target if _active_only(li, HORIZON_DAYS) and _in_scope(li))
        print(f"{SOURCE_SLUG}: {len(target):,} total, {now_pass:,} now pass both real gates")

        if args.dry_run:
            print("\nDRY RUN — nothing written.")
            return 0

        write_artifact(rows, {"fix_nc_ecourts_judgments": fixed}, docs_dir=REPO / "docs")
        print(f"\nwrote board: {len(rows):,} rows")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
