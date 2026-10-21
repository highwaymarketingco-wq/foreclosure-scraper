#!/usr/bin/env python3
"""One-time backfill: land the new enrichment_rowan_rollback_exposure.py enrichment (built
2026-10-21) onto the already-published board, without a full pipeline run.

Same shape as scripts/backfill_granville_rollback_exposure.py: the production enrich_rowan_
rollback_exposure() is already internally scoped (county=="Rowan"), already bounded
(ROWAN_ROLLBACK_MAX, default 300 listings a run) and already idempotent (skips any row with an
existing raw['rollback_exposure']). This script's own pre-filter (state=="NC", county=="Rowan",
parcel_id present) just avoids materializing the other ~447K board rows into Listing objects
before handing the small real candidate set to that function, via the memory-safe
board_stream.iter_board_rows() + patch_existing_rows() pattern this board's size requires (never
load_board()/write_artifact()).

Rowan's own match method is parcel_id only (not owner+address -- see enrichment_rowan_rollback_
exposure.py's docstring), so unlike the Granville/Brunswick siblings, owner_name is not needed
in the light Listing here.

    python scripts/backfill_rowan_rollback_exposure.py --dry-run
    BOARD_PATCH_ALLOW_LARGE=1 python scripts/backfill_rowan_rollback_exposure.py
"""
from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "src"))

from foreclosure_scraper.board_stream import iter_board_rows  # noqa: E402
from foreclosure_scraper.enrichment_rowan_rollback_exposure import (  # noqa: E402
    _eligible, enrich_rowan_rollback_exposure,
)
from foreclosure_scraper.models import Listing  # noqa: E402
from foreclosure_scraper.web_artifact import (  # noqa: E402
    _APPEND_SIG_FIELDS, board_lock, board_patch_size_state, patch_existing_rows,
)

_LIGHT_FIELDS = _APPEND_SIG_FIELDS + ("raw",)


def _light(rec: dict) -> Listing:
    return Listing.model_construct(**{k: rec.get(k) for k in _LIGHT_FIELDS})


def _collect_candidates(docs: Path) -> tuple[dict[str, Listing], int]:
    """{dedupe_key: light_listing} of every eligible Rowan NC row, + total rows streamed."""
    cands: dict[str, Listing] = {}
    total = 0
    for rec in iter_board_rows(docs / "listings.json.gz"):
        total += 1
        if str(rec.get("state") or "").upper() != "NC":
            continue
        county = (rec.get("county") or "").replace(" County", "").strip()
        if county != "Rowan":
            continue
        li = _light(rec)
        if not _eligible(li):
            continue
        try:
            key = li.dedupe_key()
        except Exception:  # noqa: BLE001
            continue
        cands[key] = li
    return cands, total


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--max-batches", type=int, default=1)
    args = ap.parse_args()

    docs = REPO / "docs"
    # 2026-10-21: lock moved to wrap ONLY the final write (see backfill_nash_multiyear_tax.py's
    # commit message for the full story) -- candidate collection needs no lock, and the live
    # fetch is pure network I/O. Holding the lock for the whole run blocked other Mac-side board
    # writers tonight for the run's entire duration.
    candidates, total_rows = _collect_candidates(docs)
    print(f"board rows streamed: {total_rows:,}")
    print(f"Rowan NC eligible candidates (parcel_id present, not already checked): "
          f"{len(candidates):,}")

    if not candidates:
        print("\nnothing to do.")
        return 0

    print("\n=== running the REAL enrich_rowan_rollback_exposure() against the live "
          "host (sequential -- shared ASP.NET viewstate session, see module docstring) ===")
    stats = asyncio.run(enrich_rowan_rollback_exposure(list(candidates.values())))
    print(f"\nstats: {stats}")

    patches: dict[str, dict] = {}
    for key, li in candidates.items():
        block = li.raw.get("rollback_exposure") if isinstance(li.raw, dict) else None
        if isinstance(block, dict):
            patches[key] = {"raw": {"rollback_exposure": block}}

    print(f"\npatches staged (positive deferred_value found): {len(patches):,}")

    if args.dry_run:
        print("\nDRY RUN -- nothing written. (enrich_rowan_rollback_exposure() above still "
              "hits the real live portal -- this module has no network-free dry-run mode; "
              "--dry-run here only controls whether the result is WRITTEN to the board.)")
        return 0
    if not patches:
        print("\nnothing to patch (0 positive matches this run).")
        return 0

    size_state = board_patch_size_state(docs)
    if not size_state["ok"]:
        print(f"\nREFUSING: {size_state['reason']}. Re-run with BOARD_PATCH_ALLOW_LARGE=1 "
              f"under supervision.")
        return 1

    with board_lock(REPO, owner="rowan_rollback_backfill", wait=1800, poll=10):
        pstats = patch_existing_rows(
            patches, {"backfill_rowan_rollback_exposure": stats}, docs_dir=docs)
    print(f"\npatch result: {pstats}")
    print(f"patched {pstats['applied']}/{len(patches)} rows "
          f"(existing board: {pstats['existing']:,})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
