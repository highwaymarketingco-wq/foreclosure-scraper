#!/usr/bin/env python3
"""Run enrich_deed_chain() board-wide using the modern streamed/patch board I/O instead of
scripts/backfill_deed_chain.py's load_board()/write_artifact(). That script's load_board() call
alone was measured live 2026-10-22 at 13.5GB RSS and still climbing after <2 minutes (full
Pydantic validation of 447,664 rows) -- killed before it risked an OOM.

A FIRST attempt here still held every row's full `raw` dict (via lightweight model_construct,
not full validation) in memory at once -- also killed, at 19+ GB RSS and still climbing. The
real cost isn't validation, it's simply holding 447K rows' nested raw dicts simultaneously
(Python object overhead on deeply nested structures is real).

Fixed with a genuine two-pass, bounded-memory design:
  PASS 1 -- stream the board ONCE collecting only (lat, lng) per row (tiny: a list of float
            pairs, no raw data at all) and compute block_binding.shared_points() from that.
            This is the one thing that genuinely needs whole-board context; it's cheap.
  PASS 2 -- stream the board AGAIN in bounded batches (default 20,000 rows). Each batch builds
            light Listings WITH raw, calls enrich_deed_chain(batch, shared_pts=<pass 1's set>)
            (enrichment_deed_chain.py now accepts a precomputed set, added alongside this
            script), patches results, then DISCARDS the batch before the next one. Peak memory
            is bounded by one batch's raw data, not the whole board's.

    python scripts/backfill_deed_chain_v2.py --dry-run
    BOARD_PATCH_ALLOW_LARGE=1 python scripts/backfill_deed_chain_v2.py
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "src"))

from foreclosure_scraper.board_stream import iter_board_rows  # noqa: E402
from foreclosure_scraper.block_binding import FALLBACK_POINT_MIN_ROWS  # noqa: E402
from foreclosure_scraper.enrichment_deed_chain import enrich_deed_chain  # noqa: E402
from foreclosure_scraper.models import Listing  # noqa: E402
from foreclosure_scraper.web_artifact import (  # noqa: E402
    _APPEND_SIG_FIELDS, board_lock, board_patch_size_state, patch_existing_rows,
)

_LIGHT_FIELDS = _APPEND_SIG_FIELDS + ("raw", "latitude", "longitude")


def _point(rec: dict):
    lat, lng = rec.get("latitude"), rec.get("longitude")
    try:
        return (round(float(lat), 5), round(float(lng), 5))
    except (TypeError, ValueError):
        return None


def _compute_shared_points(docs_dir: Path) -> set:
    from collections import Counter
    n: Counter = Counter()
    total = 0
    for rec in iter_board_rows(docs_dir / "listings.json.gz"):
        p = _point(rec)
        if p is not None:
            n[p] += 1
        total += 1
    print(f"pass 1: {total:,} rows scanned for (lat,lng) clustering")
    return {p for p, c in n.items() if c >= FALLBACK_POINT_MIN_ROWS}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--allow-large", action="store_true")
    ap.add_argument("--batch-size", type=int, default=20000)
    ap.add_argument("--skip-rows", type=int, default=0,
                     help="Resume support: skip this many streamed rows before batching (the "
                          "22 batches already written this session covered rows 1-440,000; a "
                          "transient BoardIntegrityError crashed the setup for the final ~7,664-"
                          "row tail, re-confirmed clean on a fresh read -- no need to redo "
                          "everything already successfully patched).")
    args = ap.parse_args()

    docs_dir = REPO / "docs"
    if not args.dry_run:
        size_state = board_patch_size_state(docs_dir)
        if not size_state["ok"] and not args.allow_large:
            print(f"REFUSING: {size_state['reason']}. Re-run with --allow-large.")
            return 1
        if args.allow_large:
            os.environ["BOARD_PATCH_ALLOW_LARGE"] = "1"

    shared_pts = _compute_shared_points(docs_dir)
    print(f"shared fallback points: {len(shared_pts):,}")

    total_rows = 0
    before_count = 0
    after_count = 0
    cleared_count = 0
    new_count = 0
    total_patched = 0
    batch: list[tuple[str, Listing, bool]] = []

    def flush(batch: list[tuple[str, Listing, bool]]) -> None:
        nonlocal after_count, total_patched, cleared_count, new_count
        if not batch:
            return
        listings = [li for _, li, _ in batch]
        enrich_deed_chain(listings, shared_pts=shared_pts)
        patches = {}
        for key, li, had_before in batch:
            if key is None or not (li.parcel_id or li.street_address
                                    or (li.case_number and li.county)):
                continue
            has_now = isinstance(li.raw, dict) and isinstance(li.raw.get("deed_chain"), dict)
            if has_now:
                after_count += 1
            if has_now and not had_before:
                new_count += 1
                patches[key] = {"raw": {"deed_chain": li.raw["deed_chain"]}}
            elif had_before and not has_now:
                # enrich_deed_chain() deliberately pops a stale deed_chain built from a
                # fallback-point-contaminated source when it finds no genuine records this
                # pass (enrichment_deed_chain.py line ~408) -- must propagate the removal to
                # the board too, not just skip it, or the wrong data stays live.
                cleared_count += 1
                patches[key] = {"raw": {"deed_chain": None}}
            elif has_now and had_before:
                # refreshed with (possibly) new underlying source data -- always re-patch,
                # matching the original script's own "worth re-running" rationale.
                patches[key] = {"raw": {"deed_chain": li.raw["deed_chain"]}}
        if not patches or args.dry_run:
            return
        with board_lock(REPO, owner="deed_chain_backfill_v2", wait=600, poll=10):
            pstats = patch_existing_rows(
                patches, {"deed_chain_backfill_v2_batch": len(patches)}, docs_dir=docs_dir)
        print(f"  patch_existing_rows: {pstats}")
        total_patched += pstats.get("applied", 0)

    print("pass 2: streaming board in batches...")
    for rec in iter_board_rows(docs_dir / "listings.json.gz"):
        total_rows += 1
        if total_rows <= args.skip_rows:
            continue
        raw = rec.get("raw") if isinstance(rec.get("raw"), dict) else {}
        had_before = bool(raw.get("deed_chain"))
        if had_before:
            before_count += 1
        li = Listing.model_construct(**{k: rec.get(k) for k in _LIGHT_FIELDS})
        try:
            key = li.dedupe_key()
        except Exception:  # noqa: BLE001
            key = None
        batch.append((key, li, had_before))
        if len(batch) >= args.batch_size:
            print(f"  batch at row {total_rows:,}...")
            flush(batch)
            batch = []
    flush(batch)

    print(f"\nboard rows: {total_rows:,}")
    print(f"rows with deed_chain before: {before_count:,}")
    print(f"rows with deed_chain after: {after_count:,} (net {after_count - before_count:+,})")
    print(f"  newly stamped: {new_count:,}")
    print(f"  cleared (stale/contaminated, no genuine records this pass): {cleared_count:,}")
    if args.dry_run:
        print("DRY RUN -- nothing written.")
    else:
        print(f"total applied: {total_patched:,}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
