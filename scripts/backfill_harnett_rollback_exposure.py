#!/usr/bin/env python3
"""One-time catch-up for Harnett NC rollback_exposure, following the negative-stamp fix in
enrichment_harnett_rollback_exposure.py (commit ff855bba). The daily pipeline run caps at
HARNETT_ROLLBACK_MAX=300 listings/run; before the fix, every unproductive search left nothing
behind, so the cap re-tried the same ~300 rows every day and never reached the rest of the
~1,619 eligible population. This runs the SAME enrich_harnett_rollback_exposure() function
(not a reimplementation) over the full eligible set once, with the cap raised, so the real
daily cadence starts from a stamped baseline instead of rows 301+ never having been tried.

Live network calls (owner-name search + ViewParcel detail fetch against cama.harnett.org),
politely paced (0.4s between requests, concurrency 3, same as the live pipeline path) --
NOT a pure-offline backfill like tonight's earlier ones.

    python scripts/backfill_harnett_rollback_exposure.py --dry-run
    BOARD_PATCH_ALLOW_LARGE=1 python scripts/backfill_harnett_rollback_exposure.py
"""
from __future__ import annotations

import argparse
import asyncio
import os
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "src"))

from foreclosure_scraper import enrichment_harnett_rollback_exposure as hre  # noqa: E402
from foreclosure_scraper.board_stream import iter_board_rows  # noqa: E402
from foreclosure_scraper.models import Listing  # noqa: E402
from foreclosure_scraper.web_artifact import (  # noqa: E402
    _APPEND_SIG_FIELDS, board_lock, board_patch_size_state, patch_existing_rows,
)

_LIGHT_FIELDS = _APPEND_SIG_FIELDS + ("raw", "owner_name", "street_address")


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

    print("streaming board for eligible Harnett rows...")
    keyed: dict[str, Listing] = {}
    for rec in iter_board_rows(docs_dir / "listings.json.gz"):
        if (rec.get("county") or "").strip().lower() != "harnett" or rec.get("state") != "NC":
            continue
        li = Listing.model_construct(**{k: rec.get(k) for k in _LIGHT_FIELDS})
        li.raw = dict(rec.get("raw") or {})
        if not hre._eligible(li):
            continue
        try:
            key = li.dedupe_key()
        except Exception:  # noqa: BLE001
            continue
        keyed[key] = li

    print(f"eligible rows: {len(keyed):,}")
    if not keyed:
        print("nothing to do.")
        return 0

    # One-time catch-up: raise the per-call cap so this single run covers the whole eligible
    # population instead of the daily pipeline's MAX_LISTINGS=300.
    hre.MAX_LISTINGS = len(keyed) + 1

    async def run():
        return await hre.enrich_harnett_rollback_exposure(list(keyed.values()))

    stats = asyncio.run(run())
    print(f"enrich stats: {stats}")

    patches: dict[str, dict] = {}
    for key, li in keyed.items():
        raw = li.raw if isinstance(li.raw, dict) else {}
        patch = {}
        if isinstance(raw.get(hre.RAW_KEY), dict):
            patch["rollback_exposure"] = raw[hre.RAW_KEY]
        if isinstance(raw.get(hre.CHECKED_KEY), dict):
            patch["rollback_exposure_checked"] = raw[hre.CHECKED_KEY]
        if patch:
            patches[key] = {"raw": patch}

    print(f"rows to patch (positive or negative stamp): {len(patches):,}")
    found = sum(1 for p in patches.values() if "rollback_exposure" in p["raw"])
    print(f"  of those, real deferral found: {found:,}")
    if args.dry_run:
        print("DRY RUN -- nothing written.")
        for key, p in list(patches.items())[:3]:
            print(" ", key, p)
        return 0
    if not patches:
        print("nothing to patch.")
        return 0

    with board_lock(REPO, owner="backfill_harnett_rollback_exposure", wait=600, poll=10):
        pstats = patch_existing_rows(
            patches, {"backfill_harnett_rollback_exposure": len(patches)}, docs_dir=docs_dir)
    print(f"patch_existing_rows: {pstats}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
