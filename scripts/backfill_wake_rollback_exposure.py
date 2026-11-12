#!/usr/bin/env python3
"""One-time catch-up for Wake NC rollback_exposure, same underlying root cause as Harnett's
(enrichment_harnett_rollback_exposure.py) and the jail_bookings owner cross-match: this
column's REAL producer (enrichment_rollback_deferral.py's Wake lane, cheap in-memory matching
once its 2,940-row deferred-parcel index loads once) apparently only ever saw whatever subset
of the board a given pipeline run's `enriched` touches, not a guaranteed full-board sweep.
Confirmed live 2026-10-22: a direct run against ALL 12,941 Wake rows found 26 real matches
immediately, in about a minute -- no network or matching bug, just never run at this scale.

    python scripts/backfill_wake_rollback_exposure.py --dry-run
    BOARD_PATCH_ALLOW_LARGE=1 python scripts/backfill_wake_rollback_exposure.py
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
from foreclosure_scraper.enrichment_rollback_deferral import (  # noqa: E402
    enrich_with_rollback_exposure,
)
from foreclosure_scraper.models import Listing  # noqa: E402
from foreclosure_scraper.web_artifact import (  # noqa: E402
    _APPEND_SIG_FIELDS, board_lock, board_patch_size_state, patch_existing_rows,
)

_LIGHT_FIELDS = _APPEND_SIG_FIELDS + ("raw", "owner_name")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--allow-large", action="store_true")
    args = ap.parse_args()

    docs_dir = REPO / "docs"
    if not args.dry_run:
        size_state = board_patch_size_state(docs_dir)
        if not size_state["ok"] and not args.allow_large:
            print(f"REFUSING: {size_state['reason']}. Re-run with --allow-large.")
            return 1
        if args.allow_large:
            os.environ["BOARD_PATCH_ALLOW_LARGE"] = "1"

    print("streaming board for Wake NC rows...")
    keyed: dict[str, Listing] = {}
    before: dict[str, object] = {}
    for rec in iter_board_rows(docs_dir / "listings.json.gz"):
        if (rec.get("county") or "").strip() != "Wake" or rec.get("state") != "NC":
            continue
        li = Listing.model_construct(**{k: rec.get(k) for k in _LIGHT_FIELDS})
        li.raw = dict(rec.get("raw") or {})
        try:
            key = li.dedupe_key()
        except Exception:  # noqa: BLE001
            continue
        keyed[key] = li
        before[key] = li.raw.get("rollback_exposure")

    print(f"Wake rows: {len(keyed):,}")

    async def run():
        return await enrich_with_rollback_exposure(list(keyed.values()))

    stats = asyncio.run(run())
    print(f"enrich stats: {stats}")

    patches: dict[str, dict] = {}
    for key, li in keyed.items():
        raw = li.raw if isinstance(li.raw, dict) else {}
        current = raw.get("rollback_exposure")
        if current != before[key]:
            patches[key] = {"raw": {"rollback_exposure": current}}

    print(f"rows changed (new rollback_exposure match): {len(patches):,}")
    if args.dry_run:
        print("DRY RUN -- nothing written.")
        for key, p in list(patches.items())[:5]:
            print(" ", key, p)
        return 0
    if not patches:
        print("nothing to patch.")
        return 0

    with board_lock(REPO, owner="backfill_wake_rollback_exposure", wait=600, poll=10):
        pstats = patch_existing_rows(
            patches, {"backfill_wake_rollback_exposure": len(patches)}, docs_dir=docs_dir)
    print(f"patch_existing_rows: {pstats}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
