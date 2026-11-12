#!/usr/bin/env python3
"""Normalize whitespace in street_address for the 377 board rows (all
liensnc/counties_generic.liensnc) that carry a literal embedded newline --
a PDF-text-extraction artifact where a wrapped line was never rejoined,
e.g. "12\\nTBD Taylor Lane" instead of "12 TBD Taylor Lane". Found
2026-09-15 while building the resolver geocode backfill: a raw newline
mid-address silently corrupted the entire Census batch-geocode CSV upload
for any batch that happened to include one. This is a real display/data-
correctness bug independent of geocoding -- a literal newline inside a
stored street address is wrong regardless of what consumes it.

Collapses all runs of whitespace (newlines, tabs, multiple spaces) to a
single space. Does not touch any other field.

    python scripts/fix_liensnc_address_whitespace.py --dry-run
    python scripts/fix_liensnc_address_whitespace.py
"""
from __future__ import annotations

import argparse
import contextlib
import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "src"))

from foreclosure_scraper.web_artifact import board_lock, load_board, write_artifact  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    lock = contextlib.nullcontext() if args.dry_run else board_lock(REPO, owner="fix_liensnc_address_whitespace")
    with lock:
        rows = load_board(REPO / "docs")
        print(f"board rows: {len(rows):,}")

        fixed = 0
        examples = []
        for li in rows:
            addr = li.street_address
            if addr and re.search(r"\s{2,}|\n|\t|\r", addr):
                cleaned = re.sub(r"\s+", " ", addr).strip()
                if cleaned != addr:
                    if len(examples) < 5:
                        examples.append((repr(addr), repr(cleaned)))
                    li.street_address = cleaned
                    fixed += 1

        print(f"normalized whitespace on {fixed:,} rows")
        for before, after in examples:
            print(f"  {before} -> {after}")

        if args.dry_run:
            print("\nDRY RUN — nothing written.")
            return 0

        write_artifact(rows, {"fix_liensnc_address_whitespace": fixed}, docs_dir=REPO / "docs")
        print(f"\nwrote board: {len(rows):,} rows")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
