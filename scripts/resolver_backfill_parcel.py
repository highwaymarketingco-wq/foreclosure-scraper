#!/usr/bin/env python3
"""Chunked, checkpointed runner for enrich_parcel_from_geo() over the whole
board.

The point-in-polygon resolver itself (enrichment_parcel_from_geo.py) already
exists and is correct (as of 2026-09-15, after fixing the _clean_parcel()
length-gate bug that silently discarded valid short NC parno ids like
'1020') -- but its public entrypoint `enrich_parcel_from_geo()` runs ALL
targets through one asyncio.gather with no checkpointing. This script chunks
the target list and checkpoints between chunks so a crash or interrupt does
not lose everything.

BOARD I/O REWRITE (2026-09-29, follow-up to append_new_rows()/task_0658b33b):
this used to call load_board() to build `rows`, mutate matched Listing
objects in place, then checkpoint by calling write_artifact(rows, ...) --
the WHOLE ~217K-row board, re-validated AND re-serialized, merely to land the
~1,000-1,500 parcel_ids this script actually resolves per run. That is
exactly the double materialization BOARD_LOAD_MAX_SOURCE_MB now refuses on
this board's real size (measured 11.1 GB physical footprint against the real
217,883-row board -- see that constant's comment in web_artifact.py): this
script was, in practice, BLOCKED. Neither the resolution logic
(enrich_parcel_from_geo/_resolve_one, the ArcGIS querying, the chunking, the
circuit-breaker interaction) nor CHUNK_SIZE/CHECKPOINT_EVERY changed here --
only how targets are collected and how a checkpoint is written:

  * targets are collected by streaming the published board
    (board_stream.iter_board_rows(), read-only, no lazy-detail sidecar --
    parcel resolution needs none of comps/vision/cama) through a CHEAP
    dict-level pre-filter (no parcel_id, state in NC/SC, county set) before
    ever calling Listing.model_validate() -- only the rows that survive that
    filter (a small fraction of the board; see docs/HANDOFF.md's "resolver
    hitting hard tail" note) are validated into real Listing objects, which
    is what enrich_parcel_from_geo() genuinely needs (typed lat/lon, a
    mutable .raw dict). The final `_in_box()` check runs on those, exactly
    as before.
  * each checkpoint calls web_artifact.patch_existing_rows() with only the
    handful of leads actually resolved since the last checkpoint, instead of
    write_artifact() with the whole board. See that function's docstring in
    web_artifact.py for how it streams the existing board through unchanged.

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

from foreclosure_scraper.board_stream import iter_board_rows  # noqa: E402
from foreclosure_scraper.enrichment_parcel_from_geo import _in_box, enrich_parcel_from_geo  # noqa: E402
from foreclosure_scraper.http_client import install_hard_sigint_kill  # noqa: E402
from foreclosure_scraper.models import Listing  # noqa: E402
from foreclosure_scraper.web_artifact import board_lock, patch_existing_rows  # noqa: E402

CHUNK_SIZE = 1500
CHECKPOINT_EVERY = 2  # chunks (~3,000 leads) between board writes


def _collect_targets(docs: Path) -> list[Listing]:
    """Board rows lacking a parcel_id, in NC/SC with a county set and lat/lon inside the
    footprint box -- WITHOUT load_board()'s full-board materialization (refused on this
    board's real size; see BOARD_LOAD_MAX_SOURCE_MB in web_artifact.py). Streams the published
    board read-only (no lazy-detail sidecar -- this operation never needs comps/vision/cama)
    and only ever fully validates the small subset of rows that survive a cheap dict-level
    pre-filter into real Listing objects: enrich_parcel_from_geo() needs a genuine Listing
    (typed lat/lon, a mutable .raw dict), so -- the same pattern append_new_rows()/
    patch_existing_rows() use elsewhere -- only the small candidate set is ever paid for in
    full; the other hundreds of thousands of rows are never parsed into anything but the raw
    dict iter_board_rows() itself hands over, one at a time.
    """
    targets: list[Listing] = []
    for rec in iter_board_rows(docs / "listings.json.gz"):
        if rec.get("parcel_id") or rec.get("state") not in ("SC", "NC") or not rec.get("county"):
            continue
        try:
            li = Listing.model_validate(rec)
        except Exception:  # noqa: BLE001 - a malformed row must not crash the whole backfill
            continue
        if _in_box(li):
            targets.append(li)
    return targets


def main() -> int:
    # Diagnosed 2026-09-30: a real run wedged on a hung ArcGIS connection (see
    # enrichment_parcel_from_geo._ARC_HARD_TIMEOUT_S for the network-side fix),
    # and Ctrl-C did not stop it cleanly even after 18s -- only SIGTERM did.
    # This guarantees the process is always killable within a beat regardless
    # of what's wedged inside asyncio/httpx.
    install_hard_sigint_kill(reason="resolver_backfill_parcel")

    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--limit", type=int, default=None, help="Cap total targets processed (testing)")
    args = ap.parse_args()

    docs = REPO / "docs"
    lock = contextlib.nullcontext() if args.dry_run else board_lock(REPO, owner="resolver_backfill_parcel")
    with lock:
        targets = _collect_targets(docs)
        print(f"parcel-resolution targets (lat/lon in box, no parcel_id): {len(targets):,}")

        if args.limit:
            targets = targets[: args.limit]
            print(f"--limit applied: processing {len(targets):,}")

        chunks = [targets[i:i + CHUNK_SIZE] for i in range(0, len(targets), CHUNK_SIZE)]
        total_queried = total_resolved = 0
        pending_patches: dict[str, dict] = {}

        async def run_chunk(chunk):
            return await enrich_parcel_from_geo(chunk, concurrency=8)

        for ci, chunk in enumerate(chunks, 1):
            # Identity MUST be captured before resolution mutates li.parcel_id --
            # Listing.dedupe_key()'s first branch reads parcel_id, so a target with none yet
            # (every target here, by construction) keys off its address/case/url branch; that
            # is the SAME key its unresolved row already has on the board today, so the
            # eventual patch lands on the right row.
            pre_keys = {li.dedupe_key(): li for li in chunk}

            counts = asyncio.run(run_chunk(chunk))
            total_queried += counts["queried"]
            total_resolved += counts["resolved"]
            print(f"chunk {ci}/{len(chunks)}: queried={counts['queried']} "
                  f"resolved={counts['resolved']} (running total: {total_resolved}/{total_queried})",
                  flush=True)

            for key, li in pre_keys.items():
                if not li.parcel_id:
                    continue  # unresolved -- nothing to patch for this one
                patch: dict = {"parcel_id": li.parcel_id}
                pfg = li.raw.get("parcel_from_geo") if isinstance(li.raw, dict) else None
                if pfg is not None:
                    patch["raw"] = {"parcel_from_geo": pfg}
                pending_patches[key] = patch

            if ci % CHECKPOINT_EVERY == 0 and not args.dry_run and pending_patches:
                stats = patch_existing_rows(
                    pending_patches, {"resolver_backfill_parcel_checkpoint": total_resolved},
                    docs_dir=docs)
                print(f"  [checkpoint] patched {stats['applied']}/{len(pending_patches)} rows "
                      f"at chunk {ci}/{len(chunks)}", flush=True)
                pending_patches = {}

        print(f"\n=== RESULTS ===")
        print(f"queried: {total_queried:,}")
        print(f"resolved: {total_resolved:,}")
        # Exactly equivalent to re-scanning the whole board for the same predicate after this
        # run: this run can only ever change li.parcel_id for rows already IN `targets` (every
        # other board row was, by definition, excluded from `targets` and is untouched), so of
        # the original len(targets) rows lacking a parcel_id, exactly total_resolved now have
        # one -- no second full-board stream needed to say so.
        still_missing = len(targets) - total_resolved
        print(f"still missing parcel_id (in-box NC/SC): {still_missing:,}")

        if args.dry_run:
            print("\nDRY RUN — nothing written.")
            return 0

        if pending_patches:
            stats = patch_existing_rows(pending_patches, {"resolver_backfill_parcel": total_resolved},
                                        docs_dir=docs)
            print(f"\npatched {stats['applied']}/{len(pending_patches)} rows "
                  f"(existing board: {stats['existing']:,})")
        else:
            print("\nnothing to patch (0 resolved this run)")
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
