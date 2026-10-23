#!/usr/bin/env python3
"""One-time, bounded catch-up for the incarceration signal (enrichment_incarceration.py --
owner-vs-state-prison-roster match, NC DAC + SC SCDC). Not dormant -- it runs every day,
deliberately capped to INCARCERATION_MAX_QUERIES=150/run and paced at 1 req/sec (concurrency 1)
to stay polite to the state's live lookup servers. At that rate, the real eligible backlog
(203,233 unique owner names across NC/SC as measured 2026-10-23) would take 50+ days to clear
even once. This runs the SAME enrich_incarceration() function (not a reimplementation), with
a much larger max_queries for one supervised run tonight, at the SAME pacing (never raised --
the 1 req/sec delay is the actual politeness mechanism, the query count is not).

Streams the whole board (NC/SC rows only), runs one large batch, patches every row that
changed (a new state-prison match, a negative recheck stamp, or a stale match cleared).

    python scripts/backfill_incarceration.py --dry-run --max-queries 2000
    BOARD_PATCH_ALLOW_LARGE=1 python scripts/backfill_incarceration.py --max-queries 20000
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
from foreclosure_scraper.enrichment_incarceration import enrich_incarceration  # noqa: E402
from foreclosure_scraper.models import Listing  # noqa: E402
from foreclosure_scraper.web_artifact import (  # noqa: E402
    _APPEND_SIG_FIELDS, board_lock, board_patch_size_state, patch_existing_rows,
)

_LIGHT_FIELDS = _APPEND_SIG_FIELDS
_WATCH_KEYS = ("incarceration", "incarceration_check")
# enrich_incarceration() (and the _owner_of/_stamp_of/_clear_stale_matches helpers it calls)
# only ever reads these 4 raw sub-keys -- never the rest of a row's raw dict, which by now
# carries many other unrelated enrichment blocks (rollback_exposure, deed_chain, heir_estate,
# jail_booking_screen, ...) per row. Copying only these keeps per-row memory to a small
# fraction of a full raw clone across all ~280K NC/SC rows -- the first attempt at this
# backfill (2026-10-23) held full raw dicts for all of them simultaneously and pushed this
# 8GB Mac's swap to 92% full while another scheduled job (daily vision) was also running.
_NEEDED_RAW_KEYS = ("owner_mailing", "incarceration", "jail_booking", "incarceration_check")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--allow-large", action="store_true")
    ap.add_argument("--max-queries", type=int, default=20000)
    ap.add_argument("--per-county-cap", type=int, default=0, help="0 = no cap")
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
    print(f"running enrich_incarceration(max_queries={args.max_queries}, "
          f"per_county_cap={args.per_county_cap}) -- this paces at 1 req/sec, "
          f"so expect roughly {args.max_queries} seconds of wall-clock time...")

    async def run():
        return await enrich_incarceration(
            list(keyed.values()), max_queries=args.max_queries,
            per_county_cap=args.per_county_cap)

    stats = asyncio.run(run())
    print(f"enrich stats: {stats}")

    patches: dict[str, dict] = {}
    for key, li in keyed.items():
        raw = li.raw if isinstance(li.raw, dict) else {}
        changed = {k: raw.get(k) for k in _WATCH_KEYS}
        if changed != before[key]:
            patches[key] = {"raw": changed}

    print(f"rows changed (new match, check stamp, or stale-match clear): {len(patches):,}")
    new_matches = sum(1 for p in patches.values() if p["raw"].get("incarceration"))
    print(f"  of those, a new/refreshed incarceration match: {new_matches:,}")
    if args.dry_run:
        print("DRY RUN -- nothing written.")
        for key, p in list(patches.items())[:5]:
            print(" ", key, p)
        return 0
    if not patches:
        print("nothing to patch.")
        return 0

    with board_lock(REPO, owner="backfill_incarceration", wait=1800, poll=10):
        pstats = patch_existing_rows(
            patches, {"backfill_incarceration": len(patches)}, docs_dir=docs_dir)
    print(f"patch_existing_rows: {pstats}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
