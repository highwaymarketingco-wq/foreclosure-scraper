#!/usr/bin/env python3
"""Clear parcel_ids that are not parcel identifiers. Clears only; never adds/drops a row.

Measured on the live board 2026-09-13, 115,942 rows:

    1,053 rows carry a parcel_id that _normalize_parcel already REJECTS (no digit)
      205 more are shorter than 4 characters after stripping punctuation
    worst values: 'e' 336 · 'es' 171 · 'g' 105 · 'I' 94 · 'ey' 69 · '-' 51 · 'of' 19
    source: counties_generic.liensnc 1,184 of 1,258

These are regex fragments, the same class as the PIN_RE bug that produced 'ehurst' from
"Pinehurst" and 'number' from "PIN number:". The dedupe guards already refuse to merge on
a digitless parcel, so they are not fusing rows -- but they still:
  * waste a parcel-cache lookup per row, which can never hit
  * break per-county tooling that probes with "the first parcel in this county" (this is
    exactly how they were found: BT tax-year discovery used Moore's 'es' and concluded
    the whole county had no appraisal cards)
  * read as a real parcel to anyone looking at the row

The original value is preserved in raw["parcel_id_cleared"] so nothing is destroyed.

    python scripts/clear_junk_parcel_ids.py --dry-run
    python scripts/clear_junk_parcel_ids.py
"""
from __future__ import annotations

import argparse
import contextlib
import re
import sys
from collections import Counter
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "src"))

MIN_CHARS = 4


def is_junk(parcel: str | None) -> bool:
    """True when this cannot be a parcel identifier."""
    from foreclosure_scraper.models import _normalize_parcel
    p = (parcel or "").strip()
    if not p:
        return False                      # absent is not junk
    if not _normalize_parcel(p):          # digitless -- already rejected downstream
        return True
    return len(re.sub(r"[^A-Za-z0-9]", "", p)) < MIN_CHARS


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()
    from foreclosure_scraper.web_artifact import board_lock, load_board, write_artifact

    lock = contextlib.nullcontext() if args.dry_run else board_lock(REPO, owner="junk_parcels")
    with lock:
        rows = load_board(REPO / "docs")
        before = len(rows)
        cleared = Counter(); by_src = Counter()
        for li in rows:
            if not is_junk(li.parcel_id):
                continue
            cleared[li.parcel_id] += 1
            by_src[li.source] += 1
            if not args.dry_run:
                if not isinstance(li.raw, dict):
                    li.raw = {}
                li.raw["parcel_id_cleared"] = li.parcel_id
                li.parcel_id = None

        n = sum(cleared.values())
        print(f"board rows: {before:,}")
        print(f"rows whose parcel_id is cleared: {n:,}")
        for v, k in cleared.most_common(10):
            print(f"  {k:>6,}  {v!r}")
        print("\nby source:")
        for s, k in by_src.most_common(6):
            print(f"  {k:>6,}  {s}")

        if args.dry_run:
            print("\nDRY RUN — nothing written.")
            return 0
        assert len(rows) == before, "clearing must not change the row count"
        write_artifact(rows, {
            "total": before,
            "notes": f"cleared {n:,} junk parcel_ids (originals kept in raw.parcel_id_cleared)",
            "off_footprint_removed": 0,
        }, docs_dir=REPO / "docs")
        print(f"\nwrote board: {before:,} rows unchanged")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
