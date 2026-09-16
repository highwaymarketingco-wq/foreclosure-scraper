#!/usr/bin/env python3
"""Run enrichment_derivation_flags.enrich_derivation_flags() board-wide.

Wired into main.py but stale: derivation_flags present on only 1,564 of
175,518 rows. 100% offline -- free_and_clear (no open mortgages in ROD
history), tired_landlord (absentee + 10yr+ tenure, direct Dirty Deeds
Tier A #5), and divorce_flag (cross-ref against nc_ecourts_divorce), all
read-only over raw[] fields already on the board.

    python scripts/backfill_derivation_flags.py --dry-run
    python scripts/backfill_derivation_flags.py
"""
from __future__ import annotations

import argparse
import contextlib
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "src"))

from foreclosure_scraper.enrichment_derivation_flags import enrich_derivation_flags  # noqa: E402
from foreclosure_scraper.web_artifact import board_lock, load_board, write_artifact  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    lock = contextlib.nullcontext() if args.dry_run else board_lock(REPO, owner="backfill_derivation_flags")
    with lock:
        rows = load_board(REPO / "docs")
        print(f"board rows: {len(rows):,}")

        before = sum(1 for li in rows if isinstance(li.raw, dict) and li.raw.get("derivation_flags"))
        print(f"derivation_flags before: {before:,}")

        if args.dry_run:
            stats = enrich_derivation_flags(rows)
            print(f"\n(dry run -- computed but not persisted): {stats}")
            print("\nDRY RUN — nothing written.")
            return 0

        stats = enrich_derivation_flags(rows)
        after = sum(1 for li in rows if isinstance(li.raw, dict) and li.raw.get("derivation_flags"))
        print(f"\nstats: {stats}")
        print(f"derivation_flags after: {after:,} (+{after - before:,})")

        write_artifact(rows, {"backfill_derivation_flags": stats}, docs_dir=REPO / "docs")
        print(f"wrote board: {len(rows):,} rows")
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
