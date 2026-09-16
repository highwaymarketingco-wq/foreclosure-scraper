#!/usr/bin/env python3
"""Run enrichment_comps.enrich_with_comps() board-wide.

Unlike doc_ocr/vision, comps' network cost is bounded by county count (18),
not row count: it builds one sold-comp pool and one rent-comp pool per
county seat via HomeHarvest (free, no key), then matches every listing
against the pre-built pool in memory. Safe to run against the whole board
in one call -- no per-listing network calls, no chunking needed.

    python scripts/backfill_comps.py --dry-run
    python scripts/backfill_comps.py
"""
from __future__ import annotations

import argparse
import asyncio
import contextlib
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "src"))

from foreclosure_scraper.enrichment_comps import enrich_with_comps  # noqa: E402
from foreclosure_scraper.web_artifact import board_lock, load_board, write_artifact  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    lock = contextlib.nullcontext() if args.dry_run else board_lock(REPO, owner="backfill_comps")
    with lock:
        rows = load_board(REPO / "docs")
        print(f"board rows: {len(rows):,}")

        no_comps = sum(1 for li in rows if not (isinstance(li.raw, dict) and li.raw.get("comps")))
        print(f"rows without comps: {no_comps:,}")

        if args.dry_run:
            print("\nDRY RUN — enrich_with_comps() not called, nothing written.")
            return 0

        before_sold = sum(1 for li in rows if isinstance(li.raw, dict) and li.raw.get("comps"))
        before_rent = sum(1 for li in rows if isinstance(li.raw, dict) and li.raw.get("rent_comps"))
        asyncio.run(enrich_with_comps(rows))
        after_sold = sum(1 for li in rows if isinstance(li.raw, dict) and li.raw.get("comps"))
        after_rent = sum(1 for li in rows if isinstance(li.raw, dict) and li.raw.get("rent_comps"))
        print(f"\nnew sold-comp matches: {after_sold - before_sold:,}")
        print(f"new rent-comp matches: {after_rent - before_rent:,}")

        write_artifact(rows, {"backfill_comps": after_sold - before_sold}, docs_dir=REPO / "docs")
        print(f"wrote board: {len(rows):,} rows")
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
