#!/usr/bin/env python3
"""Run the Lexington assessment enricher over the board.

Lexington's 2,214 leads all rank D for want of a value. This fills tax_value from
the county's open /assessment endpoint and records the 4%/6% assessment ratio as a
free owner-occupancy signal.

    python scripts/run_lexington_assessment.py --dry-run
    python scripts/run_lexington_assessment.py
"""
from __future__ import annotations

import argparse
import asyncio
import contextlib
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "src"))

from foreclosure_scraper.enrichment_lexington_assessment import enrich_lexington  # noqa: E402
from foreclosure_scraper.web_artifact import board_lock, load_board, write_artifact  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--max", type=int, default=None)
    args = ap.parse_args()

    lock = contextlib.nullcontext() if args.dry_run else board_lock(REPO, owner="lex_assess")
    with lock:
        rows = load_board(REPO / "docs")
        before = len(rows)
        print(f"board rows: {before:,}")
        stats = asyncio.run(enrich_lexington(rows, max_rows=args.max))
        for k, v in sorted(stats.items()):
            print(f"  {k:22} {v:,}")
        if args.dry_run:
            print("\nDRY RUN — nothing written.")
            return 0
        assert len(rows) == before, "row count changed — refusing to write"
        write_artifact(rows, {"lexington_assessment": stats["enriched"]},
                       docs_dir=REPO / "docs")
        print(f"\nwrote board: {len(rows):,} rows unchanged")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
