#!/usr/bin/env python3
"""One-time backfill: run the existing, already-wired enrich_cchs_rod() against Lincoln NC's
massively-starved backlog (18,436 eligible, only 8 ever checked -- 0.04%) by bypassing its own
county round-robin, which exists specifically because a 900s-budget pipeline run never gets
through more than one county's share in a day (see enrichment_cchs_rod.py's own 2026-10-16
comment). Filtering the input to Lincoln-only makes the round-robin a no-op (one county = no
spin needed) and lets this run push through Lincoln's own backlog directly.

enrich_cchs_rod() is a flat, uncheckpointed sequential loop (one owner-name search + 0.3s sleep
per row, no internal batching) -- for an 18K-row county that's hours, so THIS script supplies
the checkpointing: one board write after each batch, not one write at the very end. A crash
mid-run loses at most one batch's work, not the whole thing.

LOCK LESSON: lock wraps ONLY the per-batch board_patch_existing_rows() write, wait=600/poll=10.

    python scripts/backfill_lincoln_cchs_rod.py --dry-run --batch-size 50 --max-batches 1
    BOARD_PATCH_ALLOW_LARGE=1 python scripts/backfill_lincoln_cchs_rod.py --batch-size 1000 --max-batches 20
"""
from __future__ import annotations

import argparse
import asyncio
import os
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "src"))

from foreclosure_scraper.board_stream import iter_board_rows  # noqa: E402
from foreclosure_scraper.enrichment_cchs_rod import enrich_cchs_rod  # noqa: E402
from foreclosure_scraper.models import Listing  # noqa: E402
from foreclosure_scraper.rod.classify import is_stale  # noqa: E402
from foreclosure_scraper.web_artifact import (  # noqa: E402
    _APPEND_SIG_FIELDS, board_lock, board_patch_size_state, patch_existing_rows,
)
from datetime import datetime, timezone  # noqa: E402

_LIGHT_FIELDS = _APPEND_SIG_FIELDS + ("raw", "owner_name")


def _light(rec: dict) -> Listing:
    return Listing.model_construct(**{k: rec.get(k) for k in _LIGHT_FIELDS})


def _candidates(docs_dir: Path) -> list[tuple[str, Listing]]:
    """Every Lincoln NC row whose owner_name is set and whose rod check is currently stale
    (same is_stale() gate the production function itself uses -- matches its own definition
    of 'needs a check')."""
    now = datetime.now(timezone.utc)
    out = []
    for rec in iter_board_rows(docs_dir / "listings.json.gz"):
        if str(rec.get("state") or "").upper() != "NC":
            continue
        county = (rec.get("county") or "").replace(" County", "").strip()
        if county != "Lincoln":
            continue
        li = _light(rec)
        if not li.owner_name:
            continue
        if not is_stale(li, now, 2, 7):  # hot_days=2, base_days=7, matching refresh_windows("FORECLOSURE_CCHS_ROD", 7, 2)'s (hot, base) return order
            continue
        try:
            key = li.dedupe_key()
        except Exception:  # noqa: BLE001
            continue
        out.append((key, li))
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--allow-large", action="store_true")
    ap.add_argument("--batch-size", type=int, default=1000)
    ap.add_argument("--max-batches", type=int, default=20)
    args = ap.parse_args()

    docs_dir = REPO / "docs"
    if not args.dry_run:
        size_state = board_patch_size_state(docs_dir)
        if not size_state["ok"] and not args.allow_large:
            print(f"REFUSING: {size_state['reason']}. Re-run with --allow-large.")
            return 1
        if args.allow_large:
            os.environ["BOARD_PATCH_ALLOW_LARGE"] = "1"

    all_cands = _candidates(docs_dir)
    print(f"Lincoln NC eligible (owner present, rod check stale): {len(all_cands):,}")
    if not all_cands:
        print("nothing to do.")
        return 0

    total_searched = 0
    total_with_instruments = 0
    total_written = 0

    for batch_num in range(1, args.max_batches + 1):
        start = (batch_num - 1) * args.batch_size
        chunk = all_cands[start:start + args.batch_size]
        if not chunk:
            print(f"batch {batch_num}: no more rows, stopping")
            break
        print(f"\n=== Lincoln CCHS-ROD batch {batch_num}: {len(chunk)} rows ===")
        listings = [li for _, li in chunk]
        stats = asyncio.run(enrich_cchs_rod(listings))
        print(f"  {stats}")
        total_searched += stats.get("searched", 0)
        total_with_instruments += stats.get("with_instruments", 0)

        patches = {}
        for key, li in chunk:
            if isinstance(li.raw, dict) and "rod" in li.raw:
                patches[key] = {"raw": {"rod": li.raw["rod"]}}
        print(f"  patches this batch: {len(patches)}")

        if args.dry_run:
            print("  DRY RUN -- not writing this batch.")
            continue
        if not patches:
            continue
        with board_lock(REPO, owner="lincoln_cchs_rod_backfill", wait=600, poll=10):
            pstats = patch_existing_rows(
                patches, {"lincoln_cchs_rod_backfill_batch": len(patches)}, docs_dir=docs_dir)
        print(f"  patch_existing_rows: {pstats}")
        total_written += pstats.get("applied", 0)

    print(f"\ntotals: searched={total_searched:,} with_instruments={total_with_instruments:,} "
          f"written={total_written:,}")
    if args.dry_run:
        print("DRY RUN -- nothing written overall.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
