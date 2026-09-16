#!/usr/bin/env python3
"""Chunked, checkpointed runner for enrich_flood_zones() over the whole board.

FEMA NFHL (hazards.fema.gov), free, no key. enrich_flood_zones() already
handles its own concurrency (semaphore=10) and idempotency (skips rows that
already have raw['flood_zone']), but calling it once over all 117K+ targets
in a single await would run for many hours with zero progress saved until
the very end. This script chunks the target list and checkpoints via
write_artifact() between chunks, matching the pattern used for the
parcel/geocode backfills earlier this session.

    python scripts/backfill_flood_zone.py --dry-run
    python scripts/backfill_flood_zone.py
    python scripts/backfill_flood_zone.py --limit 500   # testing
"""
from __future__ import annotations

import argparse
import asyncio
import contextlib
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "src"))

from foreclosure_scraper.enrichment_flood_zone import enrich_flood_zones  # noqa: E402
from foreclosure_scraper.web_artifact import board_lock, load_board, write_artifact  # noqa: E402

CHUNK_SIZE = 2000
CHECKPOINT_EVERY = 3  # chunks (~6,000 leads) between board writes


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--limit", type=int, default=None)
    args = ap.parse_args()

    lock = contextlib.nullcontext() if args.dry_run else board_lock(REPO, owner="backfill_flood_zone")
    with lock:
        rows = load_board(REPO / "docs")
        print(f"board rows: {len(rows):,}")

        targets = [
            li for li in rows
            if li.latitude and li.longitude and not (isinstance(li.raw, dict) and li.raw.get("flood_zone"))
        ]
        print(f"flood_zone targets: {len(targets):,}")

        if args.limit:
            targets = targets[: args.limit]
            print(f"--limit applied: {len(targets):,}")

        if args.dry_run:
            print("\nDRY RUN — nothing written.")
            return 0

        chunks = [targets[i:i + CHUNK_SIZE] for i in range(0, len(targets), CHUNK_SIZE)]
        totals = {"queried": 0, "in_sfha": 0, "moderate": 0, "low": 0, "unknown": 0, "failed": 0}

        for ci, chunk in enumerate(chunks, 1):
            stats = asyncio.run(enrich_flood_zones(chunk))
            for k in totals:
                totals[k] += stats.get(k, 0)
            print(f"chunk {ci}/{len(chunks)}: {stats}  (running totals: {totals})", flush=True)

            if ci % CHECKPOINT_EVERY == 0:
                write_artifact(rows, {"backfill_flood_zone_checkpoint": totals}, docs_dir=REPO / "docs")
                print(f"  [checkpoint] wrote board at chunk {ci}/{len(chunks)}", flush=True)

        print(f"\n=== RESULTS === {totals}")
        write_artifact(rows, {"backfill_flood_zone": totals}, docs_dir=REPO / "docs")
        print(f"wrote board: {len(rows):,} rows")
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
