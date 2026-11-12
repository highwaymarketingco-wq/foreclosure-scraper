#!/usr/bin/env python3
"""Historical backfill: apply NC OneMap's statewide heir_estate / rollback_exposure
sweeps to every NC row already on the board, not just rows touched by a tail run.

WHY THIS EXISTS

    enrichment_onemap_sweeps.py's enrich_onemap_sweeps() is wired into main.py's
    run_enrich_tail() -- it only ever runs apply_indexes() against that run's own
    freshly-merged rows, the same "never ran against the historical backlog" shape
    already found and fixed for gis_attrs/tax_aging/comps this session (see
    project_mecklenburg_gapsweep_2026-11-11). The sweep itself (one paged statewide
    ArcGIS pass per column, cached CACHE_TTL_DAYS) and apply_indexes() (pure,
    in-memory, no network at all once the cache exists) are both already correct and
    already wired -- this script just points apply_indexes() at the WHOLE historical
    board instead of one run's tail slice.

    A fresh gap_matrix run (2026-11-11) found 40 (state, county) cells sourced-not-
    built for heir_estate (~28,585 est rows) and a smaller rollback_exposure slice
    riding the same sweep -- see [[project_mecklenburg_gapsweep_2026-11-11]] and this
    session's own sourced-not-built mapping workflow. stamp_heir()/stamp_rollback()
    never overwrite an existing stamp (the richer per-county producers always win),
    so this is a pure additive catch-up, safe to run repeatedly.

BOARD I/O: one streaming read-only pass (board_stream.iter_board_rows(), light
Listing objects only -- never load_board()) to build the candidate set and the
before-snapshot of raw.heir_estate/raw.rollback_exposure; apply_indexes() itself
touches no board file at all. board_lock() wraps ONLY the final patch_existing_rows()
write (the lesson from backfill_mecklenburg_tax.py's lock-scope bug fixed earlier
tonight -- see project_board_lock_wide_scope_stalls_gis_attrs_2026-11-11), never the
sweep (which is live network when the cache is stale) or the apply_indexes() pass
(which is CPU-only but still shouldn't hold a write lock for no reason).

    .venv/bin/python scripts/backfill_heir_estate_onemap.py --dry-run
    .venv/bin/python scripts/backfill_heir_estate_onemap.py --apply --allow-large
"""
from __future__ import annotations

import argparse
import asyncio
import sys
from collections import Counter
from pathlib import Path
from typing import Optional

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "src"))

from foreclosure_scraper.board_stream import iter_board_rows  # noqa: E402
from foreclosure_scraper.enrichment_onemap_sweeps import (  # noqa: E402
    apply_indexes, load_cache, sweep_heir, sweep_present_use,
)
from foreclosure_scraper.http_client import client  # noqa: E402
from foreclosure_scraper.models import Listing  # noqa: E402

_LIGHT_FIELDS = ("state", "county", "parcel_id", "street_address", "zip_code",
                  "case_number", "source_url", "listing_type", "source", "raw")
_SIG_FIELDS = ("state", "county", "parcel_id", "street_address", "zip_code",
              "case_number", "source_url", "listing_type")
_WATCH_KEYS = ("heir_estate", "rollback_exposure")


def _dedupe_key(li: Listing) -> Optional[str]:
    try:
        return li.dedupe_key()
    except Exception:  # noqa: BLE001 - a row too malformed to key is simply skipped
        return None


async def _load_indexes(allow_sweep: bool) -> tuple[Optional[dict], Optional[dict], list[str]]:
    """Prefer the existing cache (read-only, no network); only hit the real statewide
    sweep -- a live, paced ArcGIS crawl -- if the cache is stale/missing AND the
    caller explicitly allowed it (--allow-sweep). Never sweep silently: this is a
    one-off historical backfill, not the tail path, so a multi-minute live crawl
    should be an opt-in, not a surprise."""
    notes: list[str] = []
    heir = load_cache("heir_estate")
    puv = load_cache("present_use")
    if heir is not None:
        notes.append(f"heir_estate cache: fresh (swept_on={heir.get('swept_on')})")
    if puv is not None:
        notes.append(f"present_use cache: fresh (swept_on={puv.get('swept_on')})")
    if (heir is None or puv is None) and allow_sweep:
        async with client(timeout=60.0) as http:
            if heir is None:
                notes.append("heir_estate cache: stale/missing -- running a fresh statewide sweep")
                heir = await sweep_heir(http)
            if puv is None:
                notes.append("present_use cache: stale/missing -- running a fresh statewide sweep")
                puv = await sweep_present_use(http)
    elif heir is None or puv is None:
        notes.append("cache stale/missing for one or both columns and --allow-sweep was not passed "
                     "-- proceeding with whichever index IS cached; pass --allow-sweep to force a "
                     "fresh live crawl for the missing one(s).")
    return heir, puv, notes


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true",
                     help="Actually write via patch_existing_rows(). Default is a read-only dry run.")
    ap.add_argument("--allow-sweep", action="store_true",
                     help="If the cache is stale/missing, run a fresh live statewide sweep "
                          "(paced ArcGIS crawl, several minutes) instead of skipping that column.")
    ap.add_argument("--limit", type=int, default=None, help="Cap candidates (testing)")
    args = ap.parse_args()

    docs = REPO / "docs"
    heir, puv, notes = asyncio.run(_load_indexes(args.allow_sweep))
    for n in notes:
        print(n)
    if heir is None and puv is None:
        print("\nNo index available for either column (no cache, --allow-sweep not passed) -- nothing "
              "to apply. Re-run with --allow-sweep to force a fresh sweep, or wait for the next tail "
              "run to populate the cache.")
        return 1

    board: list[Listing] = []
    keys: list[Optional[str]] = []
    before: list[dict] = []
    scanned = nc_rows = 0
    for rec in iter_board_rows(docs / "listings.json.gz"):
        scanned += 1
        if (rec.get("state") or "").strip().upper() != "NC":
            continue
        nc_rows += 1
        li = Listing.model_construct(**{k: rec.get(k) for k in _LIGHT_FIELDS})
        board.append(li)
        keys.append(_dedupe_key(li))
        raw = li.raw if isinstance(li.raw, dict) else {}
        before.append({k: raw.get(k) for k in _WATCH_KEYS})

    print(f"\nscanned {scanned:,} board rows, {nc_rows:,} NC")

    if args.limit:
        board = board[:args.limit]
        keys = keys[:args.limit]
        before = before[:args.limit]

    key_counts: Counter = Counter()
    for k in keys:
        if k is not None:
            key_counts[k] += 1

    stats = apply_indexes(board, heir, puv)
    print("\n=== apply_indexes() stats ===")
    for k, v in sorted(stats.items()):
        print(f"  {v:7,d}  {k}")

    patches: dict[str, dict] = {}
    collisions = 0
    no_key = 0
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
        with board_lock(REPO, owner="backfill_heir_estate_onemap", wait=3600, poll=10):
            result = patch_existing_rows(
                patches, {"backfill_heir_estate_onemap": f"{len(patches)} rows"}, docs_dir=docs)
    except BoardLockBusy as exc:
        print(f"{exc} -- refusing to write ({len(patches):,} patches lost; re-run to redo them).")
        return 1
    print("\n=== patch_existing_rows result ===")
    for k, v in result.items():
        print(f"  {k}: {v}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
