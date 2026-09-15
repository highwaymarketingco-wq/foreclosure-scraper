#!/usr/bin/env python3
"""Chunked, checkpointed runner for enrich_parcel_from_geo() over the whole
board.

The point-in-polygon resolver itself (enrichment_parcel_from_geo.py) already
exists and is correct (as of 2026-09-15, after fixing the _clean_parcel()
length-gate bug that silently discarded valid short NC parno ids like
'1020') -- but its public entrypoint `enrich_parcel_from_geo()` runs ALL
targets through one asyncio.gather with no checkpointing. Against the ~100K+
NC/SC leads that will have lat/lon after the geocode backfill
(resolver_backfill_geocode.py) finishes, that's a multi-hour single call with
zero progress saved until the very end -- a crash or interrupt loses
everything. This script chunks the target list and checkpoints via
write_artifact() between chunks, matching the pattern already established
for the geocode backfill.

SC is included, not skipped: SCDOT is currently token-walled (confirmed live
2026-09-15), but enrich_parcel_from_geo()'s own host_walled()/scdot_walled()
breaker already short-circuits SC leads near-instantly once tripped, so
there's no real cost to leaving SC in the target set -- and if the wall ever
lifts, this script picks it up automatically with no code change.

    python scripts/resolver_backfill_parcel.py --dry-run
    python scripts/resolver_backfill_parcel.py
"""
from __future__ import annotations

import argparse
import asyncio
import contextlib
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "src"))

from foreclosure_scraper.enrichment_parcel_from_geo import _in_box, enrich_parcel_from_geo  # noqa: E402
from foreclosure_scraper.web_artifact import board_lock, load_board, write_artifact  # noqa: E402

CHUNK_SIZE = 1500
CHECKPOINT_EVERY = 2  # chunks (~3,000 leads) between board writes


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--limit", type=int, default=None, help="Cap total targets processed (testing)")
    args = ap.parse_args()

    lock = contextlib.nullcontext() if args.dry_run else board_lock(REPO, owner="resolver_backfill_parcel")
    with lock:
        rows = load_board(REPO / "docs")
        print(f"board rows: {len(rows):,}")

        targets = [
            li for li in rows
            if not li.parcel_id and li.state in ("SC", "NC") and li.county and _in_box(li)
        ]
        print(f"parcel-resolution targets (lat/lon in box, no parcel_id): {len(targets):,}")

        if args.limit:
            targets = targets[: args.limit]
            print(f"--limit applied: processing {len(targets):,}")

        chunks = [targets[i:i + CHUNK_SIZE] for i in range(0, len(targets), CHUNK_SIZE)]
        total_queried = total_resolved = 0

        async def run_chunk(chunk):
            return await enrich_parcel_from_geo(chunk, concurrency=8)

        for ci, chunk in enumerate(chunks, 1):
            counts = asyncio.run(run_chunk(chunk))
            total_queried += counts["queried"]
            total_resolved += counts["resolved"]
            print(f"chunk {ci}/{len(chunks)}: queried={counts['queried']} "
                  f"resolved={counts['resolved']} (running total: {total_resolved}/{total_queried})",
                  flush=True)

            if ci % CHECKPOINT_EVERY == 0 and not args.dry_run:
                write_artifact(rows, {"resolver_backfill_parcel_checkpoint": total_resolved},
                               docs_dir=REPO / "docs")
                print(f"  [checkpoint] wrote board at chunk {ci}/{len(chunks)}", flush=True)

        print(f"\n=== RESULTS ===")
        print(f"queried: {total_queried:,}")
        print(f"resolved: {total_resolved:,}")
        still_missing = sum(
            1 for li in rows
            if not li.parcel_id and li.state in ("SC", "NC") and li.county and _in_box(li)
        )
        print(f"still missing parcel_id (in-box NC/SC): {still_missing:,}")

        if args.dry_run:
            print("\nDRY RUN — nothing written.")
            return 0

        write_artifact(rows, {"resolver_backfill_parcel": total_resolved}, docs_dir=REPO / "docs")
        print(f"\nwrote board: {len(rows):,} rows")
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
