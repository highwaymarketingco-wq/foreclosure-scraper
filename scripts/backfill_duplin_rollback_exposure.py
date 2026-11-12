#!/usr/bin/env python3
"""One-time backfill: land the new enrichment_duplin_rollback_exposure.py enrichment (built
2026-10-21) onto the already-published board, without a full pipeline run.

Same shape as scripts/backfill_brunswick_rollback_exposure.py / scripts/backfill_granville_
rollback_exposure.py: the production enrich_duplin_rollback_exposure() is already internally
scoped (county=="Duplin"), already bounded (DUPLIN_ROLLBACK_MAX, default 300 listings a run) and
already idempotent (skips any row with an existing raw['rollback_exposure']). This script's own
pre-filter (state=="NC", county=="Duplin", owner present, not an entity, street address present)
just avoids materializing the other ~447K board rows into Listing objects before handing the
small real candidate set to that function, via the memory-safe board_stream.iter_board_rows() +
patch_existing_rows() pattern this board's size requires (never load_board()/write_artifact()).

    python scripts/backfill_duplin_rollback_exposure.py --dry-run
    BOARD_PATCH_ALLOW_LARGE=1 python scripts/backfill_duplin_rollback_exposure.py
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
from foreclosure_scraper.enrichment_duplin_rollback_exposure import (  # noqa: E402
    _eligible, enrich_duplin_rollback_exposure,
)
from foreclosure_scraper.models import Listing  # noqa: E402
from foreclosure_scraper.web_artifact import (  # noqa: E402
    _APPEND_SIG_FIELDS, board_lock, board_patch_size_state, patch_existing_rows,
)

#: _APPEND_SIG_FIELDS does not carry owner_name (it's an identity-signature tuple, not a full
#: field list) -- _eligible() below needs it, same fix backfill_brunswick_rollback_exposure.py's
#: _light() needs for the same reason.
_LIGHT_FIELDS = _APPEND_SIG_FIELDS + ("raw", "owner_name")


def _light(rec: dict) -> Listing:
    return Listing.model_construct(**{k: rec.get(k) for k in _LIGHT_FIELDS})


def _collect_candidates(docs: Path) -> tuple[dict[str, Listing], int]:
    """{dedupe_key: light_listing} of every eligible Duplin NC row, + total rows streamed."""
    cands: dict[str, Listing] = {}
    total = 0
    for rec in iter_board_rows(docs / "listings.json.gz"):
        total += 1
        if str(rec.get("state") or "").upper() != "NC":
            continue
        county = (rec.get("county") or "").replace(" County", "").strip()
        if county != "Duplin":
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
    args = ap.parse_args()

    docs = REPO / "docs"
    # Lock wraps ONLY the final write (see backfill_brunswick_rollback_exposure.py's own comment
    # and backfill_nash_multiyear_tax.py's commit message for the full story) -- candidate
    # collection needs no lock, and the live fetch below is pure network I/O.
    candidates, total_rows = _collect_candidates(docs)
    print(f"board rows streamed: {total_rows:,}")
    print(f"Duplin NC eligible candidates (owner present, not an entity, street address "
          f"present, not already checked): {len(candidates):,}")

    if not candidates:
        print("\nnothing to do.")
        return 0

    print("\n=== running the REAL enrich_duplin_rollback_exposure() against the live host ===")
    stats = asyncio.run(enrich_duplin_rollback_exposure(list(candidates.values())))
    print(f"\nstats: {stats}")

    patches: dict[str, dict] = {}
    for key, li in candidates.items():
        block = li.raw.get("rollback_exposure") if isinstance(li.raw, dict) else None
        if isinstance(block, dict):
            patches[key] = {"raw": {"rollback_exposure": block}}

    print(f"\npatches staged (positive deferred_value found): {len(patches):,}")

    if args.dry_run:
        print("\nDRY RUN -- nothing written. (enrich_duplin_rollback_exposure() above still "
              "hits the real live portal -- this module has no network-free dry-run mode; "
              "--dry-run here only controls whether the result is WRITTEN to the board.)")
        return 0
    if not patches:
        print("\nnothing to patch (0 positive matches this run).")
        return 0

    size_state = board_patch_size_state(docs)
    _allow_large = os.environ.get("BOARD_PATCH_ALLOW_LARGE", "").strip().lower() in ("1", "true", "yes")
    if not size_state["ok"] and not _allow_large:
        print(f"\nREFUSING: {size_state['reason']}. Re-run with BOARD_PATCH_ALLOW_LARGE=1 "
              f"under supervision.")
        return 1

    with board_lock(REPO, owner="duplin_rollback_backfill", wait=600, poll=10):
        pstats = patch_existing_rows(
            patches, {"backfill_duplin_rollback_exposure": stats}, docs_dir=docs)
    print(f"\npatch result: {pstats}")
    print(f"patched {pstats['applied']}/{len(patches)} rows "
          f"(existing board: {pstats['existing']:,})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
