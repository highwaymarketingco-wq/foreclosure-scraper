#!/usr/bin/env python3
"""Canonicalise every county name on the board. Fills/rewrites only, never adds or drops.

    python scripts/canonicalize_board_counties.py --dry-run
    python scripts/canonicalize_board_counties.py
"""
from __future__ import annotations

import argparse
import contextlib
import sys
from collections import Counter
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "src"))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    from foreclosure_scraper.county_name import canonical_county
    from foreclosure_scraper.web_artifact import board_lock, load_board, write_artifact

    lock = contextlib.nullcontext() if args.dry_run else board_lock(REPO, owner="county_canon")
    with lock:
        rows = load_board(REPO / "docs")
        before = len(rows)
        changed = Counter()
        for li in rows:
            cur = (li.county or "").strip()
            if not cur:
                continue
            canon = canonical_county(cur)
            if canon and canon != cur:
                changed[f"{cur!r} -> {canon!r}"] += 1
                if not args.dry_run:
                    li.county = canon

        print(f"board rows: {before:,}")
        print(f"rows whose county spelling changes: {sum(changed.values()):,}")
        for k, n in changed.most_common(12):
            print(f"  {n:>6,}  {k}")

        if args.dry_run:
            print("\nDRY RUN — nothing written.")
            return 0
        assert len(rows) == before, "canonicalisation must not change the row count"
        write_artifact(rows, {
            "total": before,
            "notes": f"county canonicalisation: {sum(changed.values()):,} spellings normalised",
            "off_footprint_removed": 0,
        }, docs_dir=REPO / "docs")
        print(f"\nwrote board: {before:,} rows unchanged")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
