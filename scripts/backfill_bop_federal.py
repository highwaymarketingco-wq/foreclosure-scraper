#!/usr/bin/env python3
"""One-time, bounded catch-up for the federal BOP inmate-locator signal
(enrichment_bop_federal.py). Confirmed dormant 2026-10-23: scripts/
run_pending_signal_enrichers.py (the shared 8-signal catch-up this module was
wired into on 2026-10-02) has not been run since 2026-10-03 -- the board has
grown from ~238K to 472K rows since then, and that script's full-raw-dict
whole-board materialization (needed to feed all 8 signals at once) now costs
~16GB (confirmed live: killed it 2026-10-23 at 16G MEM/15G compressed, 82MB
free physical memory, 86% swap), the same memory-architecture wall
scripts/backfill_incarceration.py hit the same night. Rather than fight that
shared script's memory footprint, this is a scoped, single-signal rewrite
that copies ONLY the 4 raw sub-keys enrich_bop_federal() actually reads
(owner_mailing, bop_federal, bop_check, incarceration) instead of the full
raw dict -- the same fix shape as backfill_incarceration.py.

Runs the SAME enrich_bop_federal() function (not a reimplementation), at the
SAME pacing (1 req/sec, concurrency 1 -- never raised, that delay is the
actual politeness mechanism to bop.gov), just with a much larger max_queries
for one supervised run tonight instead of the default 400/day.

    python scripts/backfill_bop_federal.py --dry-run --max-queries 2000
    BOARD_PATCH_ALLOW_LARGE=1 python scripts/backfill_bop_federal.py --max-queries 20000
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
from foreclosure_scraper.enrichment_bop_federal import enrich_bop_federal  # noqa: E402
from foreclosure_scraper.models import Listing  # noqa: E402
from foreclosure_scraper.web_artifact import (  # noqa: E402
    _APPEND_SIG_FIELDS, board_lock, board_patch_size_state, patch_existing_rows,
)

_LIGHT_FIELDS = _APPEND_SIG_FIELDS
_WATCH_KEYS = ("bop_federal", "bop_check", "incarceration")
# enrich_bop_federal() (and _owner_still_supports_match/_clear_stale_matches it
# calls) only ever reads these 4 raw sub-keys -- never the rest of a row's raw
# dict, which by now carries many other unrelated enrichment blocks (comps,
# vision, rod_lien, heir_estate, deed_chain, ...) per row. Copying only these
# keeps per-row memory to a small fraction of a full raw clone across all
# ~280K NC/SC rows.
_NEEDED_RAW_KEYS = ("owner_mailing", "bop_federal", "bop_check", "incarceration")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--allow-large", action="store_true")
    ap.add_argument("--max-queries", type=int, default=20000)
    args = ap.parse_args()

    docs_dir = REPO / "docs"
    if not args.dry_run:
        size_state = board_patch_size_state(docs_dir)
        if not size_state["ok"] and not args.allow_large:
            print(f"REFUSING: {size_state['reason']}. Re-run with --allow-large.")
            return 1
        if args.allow_large:
            os.environ["BOARD_PATCH_ALLOW_LARGE"] = "1"

    print("streaming board for NC/SC rows...")
    keyed: dict[str, Listing] = {}
    before: dict[str, dict] = {}
    for rec in iter_board_rows(docs_dir / "listings.json.gz"):
        if rec.get("state") not in ("NC", "SC"):
            continue
        full_raw = rec.get("raw") if isinstance(rec.get("raw"), dict) else {}
        li = Listing.model_construct(**{k: rec.get(k) for k in _LIGHT_FIELDS})
        li.raw = {k: full_raw[k] for k in _NEEDED_RAW_KEYS if k in full_raw}
        try:
            key = li.dedupe_key()
        except Exception:  # noqa: BLE001
            continue
        keyed[key] = li
        before[key] = {k: li.raw.get(k) for k in _WATCH_KEYS}

    print(f"NC/SC rows: {len(keyed):,}")
    print(f"running enrich_bop_federal(max_queries={args.max_queries}) -- "
          f"paces at 1 req/sec, expect roughly {args.max_queries} seconds of "
          f"wall-clock time...")

    async def run():
        return await enrich_bop_federal(list(keyed.values()), max_queries=args.max_queries)

    stats = asyncio.run(run())
    print(f"enrich stats: {stats}")

    patches: dict[str, dict] = {}
    for key, li in keyed.items():
        raw = li.raw if isinstance(li.raw, dict) else {}
        changed = {k: raw.get(k) for k in _WATCH_KEYS}
        if changed != before[key]:
            patches[key] = {"raw": changed}

    print(f"rows changed (new match, check stamp, or stale-match clear): {len(patches):,}")
    new_matches = sum(1 for p in patches.values() if p["raw"].get("bop_federal"))
    print(f"  of those, a new/refreshed bop_federal match: {new_matches:,}")
    if args.dry_run:
        print("DRY RUN -- nothing written.")
        for key, p in list(patches.items())[:5]:
            print(" ", key, p)
        return 0
    if not patches:
        print("nothing to patch.")
        return 0

    with board_lock(REPO, owner="backfill_bop_federal", wait=1800, poll=10):
        pstats = patch_existing_rows(
            patches, {"backfill_bop_federal": len(patches)}, docs_dir=docs_dir)
    print(f"patch_existing_rows: {pstats}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
