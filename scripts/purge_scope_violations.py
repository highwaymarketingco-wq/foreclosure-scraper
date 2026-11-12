#!/usr/bin/env python3
"""Board-wide scope-violation sweep, 2026-09-15 (follow-up to the
greenville_mie_adverts landmine). Scanned every board row through the
REAL `main._in_scope()` and found 885 rows failing today's policy across
7 sources. Two genuinely different shapes:

  1. 148 rows across 6 sources are unambiguous, unconfused flip-type
     (FORECLOSURE_SALE) sale notices in counties clearly outside the
     narrow 18-county footprint (New Hanover/Dare/Brunswick/Onslow/
     Carteret NC; Aiken/Orangeburg/Florence/Darlington/Berkeley/
     Dorchester/Beaufort/Williamsburg/Sumter/Marion SC) -- a direct match
     to the long-standing, already-established "flip stays narrow, no
     exceptions" policy (not a new distressed-vs-flip question like
     Greenville was). This script REMOVES those 148 rows:
       public_notices.nc_notices_counties (44), newspapers.aiken_standard
       (26), counties.column_legal_notices (25), newspapers.
       berkeley_independent (22), newspapers.journal_scene (20),
       publicnoticesc (11, an orphaned pre-rename slug -- the current
       live scraper is public_notices.publicnoticesc, 0 board rows,
       currently Cloudflare-blocked with no free bypass, so there's no
       live source to re-fetch against).

  2. courtlistener.recap (737 rows) is a DIFFERENT shape entirely --
     genuine BANKRUPTCY-type (non-flip) data, likely an orphaned
     pre-rename slug for what's now national.courtlistener_bankruptcy
     (already in SCOPE_BYPASS_SOURCES), but only 7 of 737 case numbers
     overlap with that live source -- 730 are real, unique, non-
     duplicate bankruptcy filings (genuine defendant names verified).
     county=None on every row (never attached), state correctly set.
     Handled separately in fix_courtlistener_recap.py, NOT removed here.

    python scripts/purge_scope_violations.py --dry-run
    python scripts/purge_scope_violations.py
"""
from __future__ import annotations

import argparse
import contextlib
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "src"))

from foreclosure_scraper.main import _in_scope  # noqa: E402
from foreclosure_scraper.web_artifact import board_lock, load_board, write_artifact  # noqa: E402

TARGET_SOURCES = {
    "public_notices.nc_notices_counties",
    "newspapers.aiken_standard",
    "counties.column_legal_notices",
    "newspapers.berkeley_independent",
    "newspapers.journal_scene",
    "publicnoticesc",
}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    lock = contextlib.nullcontext() if args.dry_run else board_lock(REPO, owner="purge_scope_violations")
    with lock:
        rows = load_board(REPO / "docs")
        before = len(rows)
        print(f"board rows before: {before:,}")

        removed = []
        kept = []
        for li in rows:
            if li.source in TARGET_SOURCES and not _in_scope(li):
                removed.append(li)
            else:
                kept.append(li)

        from collections import Counter
        by_source = Counter(li.source for li in removed)
        print(f"removing {len(removed):,} scope-violating rows:")
        for src, cnt in by_source.most_common():
            print(f"  {cnt:6d}  {src}")

        print(f"\nboard rows after: {len(kept):,} (net: {len(kept) - before:+,})")

        if args.dry_run:
            print("\nDRY RUN — nothing written.")
            return 0

        write_artifact(kept, {"purge_scope_violations": -len(removed)}, docs_dir=REPO / "docs")
        print(f"\nwrote board: {len(kept):,} rows")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
