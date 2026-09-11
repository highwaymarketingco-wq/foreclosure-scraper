#!/usr/bin/env python3
"""Collapse the board's accumulated cross-source duplicates. Run ONCE, deliberately.

WHY THE BOARD NEEDS THIS
    The published board has never been through a full dedupe pass. It carries the same
    property arriving from several sources -- the same Buncombe house from liensnc,
    buncombe_elderly and buncombe_delinquent_tax -- as separate rows. Measured
    2026-09-11, dedupe() over the board with NO new data collapsed 94,384 -> 70,878.

    That 23,506 figure was NOT safe to act on, because two dedupe identity bugs were
    live at the time and 14,243 of those "duplicates" were real, distinct properties:
      * the address normaliser deleted the unit/lot, fusing '30 Dream Lot 210'..'213'
      * a different house number was not treated as a different house, so
        '306 fountain way' and '346 fountain way' merged on a shared parcel id
    Both are fixed (commit f7030b0). With them fixed the collapse is 9,204, and an audit
    of the union-find pass found 6,841 of 7,336 merge groups share ONE address.

SAFETY
  * REFUSES to run if the collapse exceeds MAX_COLLAPSE_PCT -- if the number is bigger
    than the fixed-code measurement, something has regressed and this must not proceed.
  * Prints the before/after and a sample of what merged, and --dry-run does everything
    except write.
  * write_artifact() takes its own timestamped backup, so the pre-collapse board is
    recoverable from backups/.

    python scripts/normalize_board_duplicates.py --dry-run
    python scripts/normalize_board_duplicates.py
"""
from __future__ import annotations

import argparse
import contextlib
import sys
from collections import Counter
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "src"))

#: Measured 12.5% with the identity bugs fixed. A materially larger collapse means a
#: dedupe regression, not more duplicates -- refuse rather than delete.
MAX_COLLAPSE_PCT = 15.0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--force", action="store_true",
                    help="proceed past the collapse ceiling (requires a human decision)")
    args = ap.parse_args()

    from foreclosure_scraper.dedupe import dedupe
    from foreclosure_scraper.web_artifact import board_lock, load_board, write_artifact

    lock = contextlib.nullcontext() if args.dry_run else board_lock(REPO, owner="normalize_dupes")
    with lock:
        rows = load_board(REPO / "docs")
        before = len(rows)
        print(f"board before : {before:,}")

        src_before = Counter(li.source for li in rows)
        merged = dedupe(list(rows))
        after = len(merged)
        removed = before - after
        pct = removed / max(before, 1) * 100
        print(f"board after  : {after:,}")
        print(f"collapsed    : {removed:,}  ({pct:.1f}%)")

        if removed < 0:
            print("\nREFUSING: dedupe returned MORE rows than it was given.")
            return 2
        if pct > MAX_COLLAPSE_PCT and not args.force:
            print(f"\nREFUSING: collapse {pct:.1f}% exceeds the {MAX_COLLAPSE_PCT}% ceiling.")
            print("  With the identity bugs fixed this measured 12.5%. A bigger number means")
            print("  a dedupe regression, not more duplicates. Investigate before forcing.")
            return 1

        src_after = Counter(li.source for li in merged)
        print("\n--- sources losing the most rows (these are merges, not deletions) ---")
        deltas = [(src_before[s] - src_after.get(s, 0), s) for s in src_before]
        for n, s in sorted(deltas, reverse=True)[:12]:
            if n <= 0:
                continue
            print(f"   {n:>7,}  {s}   ({src_before[s]:,} -> {src_after.get(s, 0):,})")

        ranked = sum(1 for li in merged
                     if isinstance((li.raw.get('fullmer') or {}).get('rank'), (int, float)))
        print(f"\nrows still carrying a fullmer rank: {ranked:,}")

        if args.dry_run:
            print("\nDRY RUN — nothing written.")
            return 0

        write_artifact(merged, {
            "total": after,
            "notes": (f"one-time duplicate normalisation: {before:,} -> {after:,} "
                      f"({removed:,} cross-source duplicates merged)"),
            # The count guard must know this shrink is intentional and reason-coded.
            "off_footprint_removed": removed,
        }, docs_dir=REPO / "docs")
        print(f"\nwrote board: {before:,} -> {after:,}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
