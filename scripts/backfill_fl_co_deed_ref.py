#!/usr/bin/env python3
"""Historical backfill: run enrich_florence_colleton_deed_ref() against the whole
board, not just main.py's tail slice. Closes the "sourced-not-built" atty_deed_ref
gap for Florence SC (~3,883 est rows) and Colleton SC (~3,680 est rows) -- 69% of
that column's whole weight, per the fresh gap_matrix sweep this session.

WHY THIS EXISTS: enrichment_florence_colleton_deed_ref.py's own module docstring
says plainly "NOT WIRED INTO main.py by this change" -- a real, live-verified
producer (register-of-deeds name search for these two SC counties, live-checked
2026-11-05) that has never been pointed at any board, historical or tail. Same
"built but never run against the backlog" shape as gis_attrs/tax_aging/comps/
heir_estate this session.

RATE LIMITING: the real function self-bounds via two mechanisms it already owns --
FORECLOSURE_FL_CO_DEED_REF_BUDGET_S (wall clock, default 1200s) and the SHARED
SC_ROD_MAX_LOOKUPS_PER_COUNTY (every rod/sc_* adapter reads this, default 30/county/
run) -- this script adds no pacing of its own. The FREE fill path (copying an
already-cached raw.rod_chain) has no cap at all and can clear a large chunk in one
pass; only the LIVE lookup path (rows with no usable cached chain) is capped at
60/run (30 Florence + 30 Colleton), so clearing that backlog needs this script
re-run (or self-looped) many times, same as every other live-lookup backfill
tonight.

BOARD I/O: one streaming read-only pass (board_stream.iter_board_rows()) to build
the Florence/Colleton candidate set; the live network lookups happen OUTSIDE any
lock (enrich_florence_colleton_deed_ref() itself does the pacing/capping/budget,
not board I/O). board_lock() wraps ONLY the final patch_existing_rows() write --
the lesson from tonight's backfill_mecklenburg_tax.py lock-scope bug fix.

    FORECLOSURE_FL_CO_DEED_REF=1 .venv/bin/python scripts/backfill_fl_co_deed_ref.py
    FORECLOSURE_FL_CO_DEED_REF=1 BOARD_PATCH_ALLOW_LARGE=1 \\
        .venv/bin/python scripts/backfill_fl_co_deed_ref.py --apply
"""
from __future__ import annotations

import argparse
import asyncio
import os
import sys
from collections import Counter
from pathlib import Path
from typing import Optional

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "src"))

from foreclosure_scraper.board_stream import iter_board_rows  # noqa: E402
from foreclosure_scraper.enrichment_florence_colleton_deed_ref import (  # noqa: E402
    COUNTIES, enrich_florence_colleton_deed_ref,
)
from foreclosure_scraper.models import Listing  # noqa: E402

_LIGHT_FIELDS = ("state", "county", "parcel_id", "street_address", "zip_code",
                  "case_number", "source_url", "listing_type", "source",
                  "owner_name", "defendant", "raw")
_WATCH_KEYS = ("county_deed_ref", "county_deed_ref_check")


def _dedupe_key(li: Listing) -> Optional[str]:
    try:
        return li.dedupe_key()
    except Exception:  # noqa: BLE001 - a row too malformed to key is simply skipped
        return None


def _is_target_county(rec: dict) -> bool:
    if (rec.get("state") or "").strip().upper() != "SC":
        return False
    c = (rec.get("county") or "").strip().lower().replace(" county", "")
    return c in COUNTIES


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true",
                     help="Actually write via patch_existing_rows(). Default is a read-only dry run.")
    ap.add_argument("--limit", type=int, default=None, help="Cap candidates (testing)")
    args = ap.parse_args()

    os.environ.setdefault("FORECLOSURE_FL_CO_DEED_REF", "1")

    docs = REPO / "docs"
    board: list[Listing] = []
    keys: list[Optional[str]] = []
    before: list[dict] = []
    scanned = 0
    for rec in iter_board_rows(docs / "listings.json.gz"):
        scanned += 1
        if not _is_target_county(rec):
            continue
        li = Listing.model_construct(**{k: rec.get(k) for k in _LIGHT_FIELDS})
        board.append(li)
        keys.append(_dedupe_key(li))
        raw = li.raw if isinstance(li.raw, dict) else {}
        before.append({k: raw.get(k) for k in _WATCH_KEYS})

    print(f"scanned {scanned:,} board rows, {len(board):,} Florence/Colleton SC")

    if args.limit:
        board = board[:args.limit]
        keys = keys[:args.limit]
        before = before[:args.limit]

    key_counts: Counter = Counter()
    for k in keys:
        if k is not None:
            key_counts[k] += 1

    stats = asyncio.run(enrich_florence_colleton_deed_ref(board))
    print("\n=== enrich_florence_colleton_deed_ref() stats ===")
    for k, v in sorted(stats.items()):
        print(f"  {k}: {v}")

    patches: dict[str, dict] = {}
    collisions = no_key = 0
    for li, key, b4 in zip(board, keys, before):
        raw = li.raw if isinstance(li.raw, dict) else {}
        after = {k: raw.get(k) for k in _WATCH_KEYS}
        if after == b4:
            continue
        if key is None:
            no_key += 1
            continue
        if key_counts.get(key, 0) > 1:
            collisions += 1
            continue
        changed = {k: v for k, v in after.items() if v is not None and v != b4.get(k)}
        if changed:
            patches[key] = {"raw": changed}

    print(f"\npatches staged: {len(patches):,} "
          f"(dropped as dedupe_key collisions: {collisions:,}, no key: {no_key:,})")

    if not args.apply:
        print("\nDRY RUN -- nothing written. Pass --apply to write for real "
              "(BOARD_PATCH_ALLOW_LARGE=1 env var if the board is over patch_existing_rows()'s "
              "own size ceiling).")
        return 0

    if not patches:
        print("\nnothing to apply.")
        return 0

    from foreclosure_scraper.web_artifact import BoardLockBusy, board_lock, patch_existing_rows
    try:
        with board_lock(REPO, owner="backfill_fl_co_deed_ref", wait=3600, poll=10):
            result = patch_existing_rows(
                patches, {"backfill_fl_co_deed_ref": f"{len(patches)} rows"}, docs_dir=docs)
    except BoardLockBusy as exc:
        print(f"{exc} -- refusing to write ({len(patches):,} patches lost; re-run to redo them).")
        return 1
    print("\n=== patch_existing_rows result ===")
    for k, v in result.items():
        print(f"  {k}: {v}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
