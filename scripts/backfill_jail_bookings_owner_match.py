#!/usr/bin/env python3
"""One-time catch-up for enrichment_jail_bookings.py (the OWNER-cross-match signal -- flags an
EXISTING property owner who shows up on a county jail roster; separate from
scrapers/national/jail_bookings.py, which creates booking Listings themselves).

WHY THIS EXISTS. data/jail_roster_history.db -- this module's own persistent sidecar, recording
every roster fetch across the project's WHOLE lifetime -- held exactly 2 entries (Polk and
Transylvania, both from a single day, 2026-10-19) before this backfill. Zero of the other 11
covered counties (Buncombe/Burke/Cleveland/Gaston/Henderson/Lincoln/Anderson/Cherokee/Greenville/
Laurens/Oconee) had EVER been recorded. main.py calls this under a 900s wall-clock cap
(_await_capped) against `enriched` -- whatever subset of the board that specific run's phase
touches, not a guaranteed full-board sweep -- so the owner-in-jail signal (this project's own
docstring: "an owner sitting in the county jail... is a motivated seller the state rosters miss
entirely") has been almost completely dormant since the module was written, the exact same
"touches only this run's subset, never retroactively sweeps the historical board" bug class as
parcel_cache_join()'s original 36,469-row miss.

Streams the WHOLE board for the 13 covered counties (~100K rows, ~70K eligible), runs the SAME
enrich_jail_bookings() function once (not a reimplementation) with the Greenville per-name search
cap raised to cover its full eligible population, then patches every row that changed.

    python scripts/backfill_jail_bookings_owner_match.py --dry-run
    BOARD_PATCH_ALLOW_LARGE=1 python scripts/backfill_jail_bookings_owner_match.py --allow-large
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
from foreclosure_scraper.enrichment_jail_bookings import (  # noqa: E402
    ROSTERS, SEARCH_ROSTERS, enrich_jail_bookings,
)
from foreclosure_scraper.models import Listing  # noqa: E402
from foreclosure_scraper.web_artifact import (  # noqa: E402
    _APPEND_SIG_FIELDS, board_lock, board_patch_size_state, patch_existing_rows,
)

_LIGHT_FIELDS = _APPEND_SIG_FIELDS + ("raw", "owner_name")
# FOUND 2026-10-22: a first full-scope dry run (bulk + Greenville) hit sustained
# "Could not resolve host" failures partway through Greenville's ~3,615-search per-name
# lane after ~25 minutes of continuous automated traffic -- re-tested with a single fresh
# request immediately after and it succeeded normally, so this is a transient/rate-limit
# condition, not a wall. Scoped to the 12 BULK rosters only for tonight (cheap, proven,
# zero rate-limit risk -- confirmed fast and clean in the same dry run before Greenville's
# lane started). Greenville's per-name search lane needs its own, more conservative,
# separately-paced catch-up -- not attempted here. Pass --include-greenville to include it.
_BULK_COVERED = {(s, c) for s, c, _, _ in ROSTERS}
_SEARCH_COVERED = {(s, c) for s, c, _, _ in SEARCH_ROSTERS}
_WATCH_KEYS = ("jail_booking", "jail_booking_new", "jail_booking_screen")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--allow-large", action="store_true")
    ap.add_argument("--greenville-cap", type=int, default=4000,
                     help="max_searches_per_county for the Greenville per-name search lane "
                          "(default covers its full ~3,615-row eligible population)")
    ap.add_argument("--include-greenville", action="store_true",
                     help="also run Greenville's live per-name search lane (see this "
                          "script's module docstring -- scoped out by default tonight "
                          "after a transient rate-limit-shaped failure)")
    args = ap.parse_args()
    covered = _BULK_COVERED | (_SEARCH_COVERED if args.include_greenville else set())

    docs_dir = REPO / "docs"
    if not args.dry_run:
        size_state = board_patch_size_state(docs_dir)
        if not size_state["ok"] and not args.allow_large:
            print(f"REFUSING: {size_state['reason']}. Re-run with --allow-large.")
            return 1
        if args.allow_large:
            os.environ["BOARD_PATCH_ALLOW_LARGE"] = "1"

    print(f"streaming board for rows in {len(covered)} covered counties...")
    keyed: dict[str, Listing] = {}
    before: dict[str, dict] = {}
    for rec in iter_board_rows(docs_dir / "listings.json.gz"):
        if (rec.get("state"), (rec.get("county") or "").strip()) not in covered:
            continue
        li = Listing.model_construct(**{k: rec.get(k) for k in _LIGHT_FIELDS})
        li.raw = dict(rec.get("raw") or {})
        try:
            key = li.dedupe_key()
        except Exception:  # noqa: BLE001
            continue
        keyed[key] = li
        before[key] = {k: li.raw.get(k) for k in _WATCH_KEYS}

    print(f"covered rows: {len(keyed):,}")
    if not keyed:
        print("nothing to do.")
        return 0

    async def run():
        return await enrich_jail_bookings(
            list(keyed.values()), max_searches_per_county=args.greenville_cap)

    stats = asyncio.run(run())
    print(f"enrich stats: {stats}")

    patches: dict[str, dict] = {}
    for key, li in keyed.items():
        raw = li.raw if isinstance(li.raw, dict) else {}
        changed = {k: raw.get(k) for k in _WATCH_KEYS}
        if changed != before[key]:
            patches[key] = {"raw": {k: v for k, v in changed.items() if v is not None
                                     or before[key].get(k) is not None}}

    print(f"rows changed (new match, screen stamp, or stale-match clear): {len(patches):,}")
    new_matches = sum(1 for p in patches.values() if p["raw"].get("jail_booking"))
    new_screens = sum(1 for p in patches.values() if p["raw"].get("jail_booking_screen"))
    print(f"  of those, a new jail_booking match: {new_matches:,}")
    print(f"  of those, a new county screen sentinel: {new_screens:,}")
    if args.dry_run:
        print("DRY RUN -- nothing written.")
        for key, p in list(patches.items())[:3]:
            print(" ", key, p)
        return 0
    if not patches:
        print("nothing to patch.")
        return 0

    with board_lock(REPO, owner="backfill_jail_bookings_owner_match", wait=900, poll=10):
        pstats = patch_existing_rows(
            patches, {"backfill_jail_bookings_owner_match": len(patches)}, docs_dir=docs_dir)
    print(f"patch_existing_rows: {pstats}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
