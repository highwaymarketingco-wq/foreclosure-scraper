#!/usr/bin/env python3
"""Stamp enrichment_hoa_plaintiff_signal.enrich_hoa_plaintiff_signal() onto the EXISTING
board via the streaming patch path, not load_board()/write_artifact().

docs/HANDOFF.md item 46 built this enricher, wired it into main.py's live pipeline (new
scraped rows get it automatically going forward), and ran a READ-ONLY live check
(board_stream.iter_board_rows()) proving 64/4,491 plaintiff-bearing foreclosure_sale/
lis_pendens rows should tag -- but explicitly left "no board write/backfill on either
host" as separate future work. This script is that backfill, done the SAME memory-safe
way scripts/resolver_backfill_parcel.py already established for this exact board-size
problem (board source ~2.6 GB, over load_board()'s 1,200 MB ceiling by ~2.2x and over
patch_existing_rows()'s own 2,300 MB ceiling by a few percent):

  1. Stream the published board (board_stream.iter_board_rows(), read-only) through a
     cheap dict-level pre-filter (listing_type in {foreclosure_sale, lis_pendens}) BEFORE
     ever calling Listing.model_validate() -- only that small subset (14,009 rows per the
     HANDOFF investigation, not the full ~220K-row board) is ever materialized into real
     Listing objects.
  2. Run the real, already-tested enrich_hoa_plaintiff_signal() over just that subset --
     identical output to running it over the whole board, since the function itself
     already scopes to TARGET_LISTING_TYPES and every row outside that scope is a no-op.
  3. Patch only the rows that got tagged onto the board via web_artifact.patch_existing_rows()
     (streams the existing listings.json.gz exactly once, one row's parsed dict alive at a
     time -- never the whole-board materialization load_board()/write_artifact() would need).

    python scripts/backfill_hoa_plaintiff_signal.py --dry-run
    BOARD_PATCH_ALLOW_LARGE=1 python scripts/backfill_hoa_plaintiff_signal.py
"""
from __future__ import annotations

import argparse
import contextlib
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "src"))

from foreclosure_scraper.board_stream import iter_board_rows  # noqa: E402
from foreclosure_scraper.enrichment_hoa_plaintiff_signal import enrich_hoa_plaintiff_signal  # noqa: E402
from foreclosure_scraper.models import Listing  # noqa: E402
from foreclosure_scraper.web_artifact import board_lock, patch_existing_rows  # noqa: E402

TARGET_TYPES = {"foreclosure_sale", "lis_pendens"}


def _collect_targets(docs: Path) -> list[Listing]:
    """foreclosure_sale/lis_pendens rows only, validated into real Listing objects --
    everything else stays a cheap, discarded dict (same pattern resolver_backfill_parcel.py
    uses for this exact board-size problem)."""
    targets: list[Listing] = []
    for rec in iter_board_rows(docs / "listings.json.gz"):
        if rec.get("listing_type") not in TARGET_TYPES:
            continue
        try:
            li = Listing.model_validate(rec)
        except Exception:  # noqa: BLE001 - a malformed row must not crash the whole backfill
            continue
        targets.append(li)
    return targets


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    docs = REPO / "docs"
    lock = contextlib.nullcontext() if args.dry_run else board_lock(REPO, owner="backfill_hoa_plaintiff_signal")
    with lock:
        targets = _collect_targets(docs)
        print(f"foreclosure_sale/lis_pendens rows (candidate set): {len(targets):,}")

        before = sum(1 for li in targets if isinstance(li.raw, dict) and li.raw.get("hoa_plaintiff_signal"))
        print(f"hoa_plaintiff_signal already set (candidate set): {before:,}")

        # Identity MUST be captured before enrich_hoa_plaintiff_signal mutates li.raw --
        # dedupe_key() doesn't read raw, so this ordering is just defensive hygiene.
        pre_keys = {li.dedupe_key(): li for li in targets}

        stats = enrich_hoa_plaintiff_signal(targets)
        print(f"\nstats: {stats}")

        pending_patches: dict[str, dict] = {}
        for key, li in pre_keys.items():
            tag = li.raw.get("hoa_plaintiff_signal") if isinstance(li.raw, dict) else None
            if tag is None:
                continue
            pending_patches[key] = {"raw": {"hoa_plaintiff_signal": tag}}

        print(f"rows to patch: {len(pending_patches):,}")

        if args.dry_run:
            print("\nDRY RUN — nothing written.")
            return 0

        if not pending_patches:
            print("\nnothing to patch (0 tagged this run)")
            return 0

        pstats = patch_existing_rows(
            pending_patches, {"backfill_hoa_plaintiff_signal": stats}, docs_dir=docs)
        print(f"\npatch result: {pstats}")
        print(f"patched {pstats['applied']}/{len(pending_patches)} rows "
              f"(existing board: {pstats['existing']:,})")
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
