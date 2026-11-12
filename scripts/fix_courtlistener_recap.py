#!/usr/bin/env python3
"""Fix courtlistener.recap's mislabeled sale_date, found 2026-09-15 in a
board-wide scope-violation sweep. This orphaned source (no live scraper
module produces this slug; almost certainly a pre-rename name for what's
now national.courtlistener_bankruptcy) is BANKRUPTCY-type data with a
structured `sale_date` populated from what is really a bankruptcy filing/
petition date -- bankruptcy cases don't have a real-estate "sale date".
The live courtlistener_bankruptcy.py scraper never sets sale_date at all
(confirmed by reading its source), so this field never should have been
populated here either.

Left as-is, this field defeats the DATELESS_OK_SOURCES exemption just
added for this source: main._active_only() only checks that whitelist
when sale_date is None -- a non-None-but-stale date still gets window-
checked and dropped regardless (same trap found and fixed for
greenville_mie_adverts.py earlier this same sweep). This script clears
the structured field (preserving the original value in raw for anyone
who wants it) so the 730 unique, real, non-duplicate bankruptcy filings
this source carries actually survive the real pipeline gates.

Operates directly on existing board rows -- no live source to re-fetch.

    python scripts/fix_courtlistener_recap.py --dry-run
    python scripts/fix_courtlistener_recap.py
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
SOURCE_SLUG = "courtlistener.recap"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    lock = contextlib.nullcontext() if args.dry_run else board_lock(REPO, owner="fix_courtlistener_recap")
    with lock:
        rows = load_board(REPO / "docs")
        before = len(rows)
        print(f"board rows before: {before:,}")

        fixed = 0
        for li in rows:
            if li.source != SOURCE_SLUG:
                continue
            if li.sale_date is not None:
                if not isinstance(li.raw, dict):
                    li.raw = {}
                li.raw.setdefault("courtlistener_recap", {})["original_sale_date"] = li.sale_date.isoformat()
                li.sale_date = None
                fixed += 1

        print(f"cleared structured sale_date on {fixed:,} rows (preserved in raw)")

        target = [li for li in rows if li.source == SOURCE_SLUG]
        now_pass = sum(1 for li in target if _active_only(li, HORIZON_DAYS) and _in_scope(li))
        print(f"{SOURCE_SLUG}: {len(target):,} total, {now_pass:,} now pass both real gates")

        if args.dry_run:
            print("\nDRY RUN — nothing written.")
            return 0

        write_artifact(rows, {"fix_courtlistener_recap": fixed}, docs_dir=REPO / "docs")
        print(f"\nwrote board: {len(rows):,} rows")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
