#!/usr/bin/env python3
"""One-time backfill: land Richland SC's two new signals (vacant_lot, heir_estate-enabling
raw['gis']['owner']) from enrichment_richland_parcel.py's 2026-10-20 fix onto rows the board
ALREADY processed before that fix existed.

WHY A SEPARATE SCRIPT (not just letting the next normal run pick it up). Richland rows that are
already `matched: true` with mailing+parcel_id filled are "done" under enrich_richland_parcel's
own `wants()` gate (RETRY_DAYS=30) -- a normal run will not re-ask richlandmaps.com for them for
up to 30 days, and even then the gate is `_has_mailing(raw) and li.parcel_id` which stays True
forever once set. So the fix in apply_parcel() (stamping raw['gis']['owner'] unconditionally, and
deriving raw['vacant_lot'] from Building_V) will never reach these already-matched rows through
the normal path at all -- it only helps rows not yet looked up. This script re-asks the LIVE API
for rows that are missing raw['vacant_lot'] specifically (the gap this fix targets), regardless of
their prior `matched`/`attempted` state, canary-capped and polite (same 1.7s delay as the module).

BOARD I/O: board_stream.iter_board_rows() once (read-only), then a LIVE re-fetch of a capped
sample, then (only with --write) ONE patch_existing_rows() call under board_lock(). Never
load_board()/write_artifact(). This is read-only / dry-run by default; --write is required for an
actual board change, and even then this script does not bypass the "only one board process /
owner reviews real writes" rule -- it is meant to be run with --dry-run first and reviewed.

Usage:
    python scripts/backfill_richland_vacant_heir.py --dry-run --max-rows 25
    python scripts/backfill_richland_vacant_heir.py --dry-run --max-rows 2236   # full canary, slow
    python scripts/backfill_richland_vacant_heir.py --write --max-rows 2236 --allow-large
"""
from __future__ import annotations

import argparse
import asyncio
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "src"))

from foreclosure_scraper import enrichment_richland_parcel as R  # noqa: E402
from foreclosure_scraper.board_stream import iter_board_rows  # noqa: E402
from foreclosure_scraper.models import Listing  # noqa: E402
from foreclosure_scraper.web_artifact import (  # noqa: E402
    _APPEND_SIG_FIELDS, board_lock, board_patch_size_state, patch_existing_rows,
)

def _is_richland_sc(rec: dict) -> bool:
    return (str(rec.get("state") or "").upper() == "SC"
            and (rec.get("county") or "").replace(" County", "").strip().lower() == "richland")


def _needs_backfill(rec: dict) -> bool:
    """Missing the NEW signal (vacant_lot) -- the thing this fix adds. Does not require a
    street address here; that is checked again per-row before the live fetch."""
    raw = rec.get("raw")
    return not (isinstance(raw, dict) and isinstance(raw.get("vacant_lot"), dict))


def _light(rec: dict) -> Listing:
    li = Listing.model_construct(**{k: rec.get(k) for k in _APPEND_SIG_FIELDS if k in rec})
    li.raw = dict(rec.get("raw") or {})
    return li


def _collect(docs: Path) -> tuple[dict[str, Listing], int, int]:
    cands: dict[str, Listing] = {}
    total_richland = 0
    no_street = 0
    for rec in iter_board_rows(docs / "listings.json.gz"):
        if not _is_richland_sc(rec):
            continue
        total_richland += 1
        if not _needs_backfill(rec):
            continue
        if not R._HOUSE.match(str(rec.get("street_address") or "")):  # noqa: SLF001
            no_street += 1
            continue
        li = _light(rec)
        try:
            key = li.dedupe_key()
        except Exception:  # noqa: BLE001
            continue
        cands[key] = li
    return cands, total_richland, no_street


async def _canary_fetch(listings: list[Listing], *, max_rows: int, delay_s: float) -> dict:
    """Live search+parcel lookup for up to `max_rows` candidates, via the real
    choose_point/choose_parcel/apply_parcel -- the exact same code path
    enrich_richland_parcel() runs, just without its own `wants()`/retry-window gate."""
    from foreclosure_scraper.http_client import client

    now = __import__("datetime").datetime.now(__import__("datetime").timezone.utc).replace(tzinfo=None)
    todo = listings[:max_rows]
    stats = {"attempted": 0, "matched": 0, "no_point": 0, "no_parcel": 0, "errors": 0,
             "vacant_lot_new": 0, "gis_owner_new": 0, "heir_estate_new": 0}
    async with client(timeout=30.0) as c:
        first = True
        for li in todo:
            street = (li.street_address or "").split(",")[0].strip()
            try:
                if not first:
                    await asyncio.sleep(delay_s)
                first = False
                stats["attempted"] += 1
                s = await R._get_json(c, R.SEARCH, {"searchTerm": street, "searchLimit": "10",  # noqa: SLF001
                                                    "useFuzzyBkp": "1"})
                pt = R.choose_point((s or {}).get("d") or [], street)
                if not pt:
                    stats["no_point"] += 1
                    continue
                await asyncio.sleep(delay_s)
                d = await R._get_json(c, R.AT_POINT, {"lat": f"{pt[0]:.8f}", "lon": f"{pt[1]:.8f}"})  # noqa: SLF001
                p = R.choose_parcel((d or {}).get("d") or [], street)
                if not p:
                    stats["no_parcel"] += 1
                    continue
                stats["matched"] += 1
                before_vacant = isinstance(li.raw.get("vacant_lot"), dict)
                before_gis_owner = bool((li.raw.get("gis") or {}).get("owner"))
                before_heir = isinstance(li.raw.get("heir_estate"), dict)
                R.apply_parcel(li, p, now)
                if not before_vacant and isinstance(li.raw.get("vacant_lot"), dict):
                    stats["vacant_lot_new"] += 1
                if not before_gis_owner and (li.raw.get("gis") or {}).get("owner"):
                    stats["gis_owner_new"] += 1
                if not before_heir and isinstance(li.raw.get("heir_estate"), dict):
                    stats["heir_estate_new"] += 1
            except Exception as e:  # noqa: BLE001
                stats["errors"] += 1
                print(f"  error on {street!r}: {e}")
    return stats


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true", default=True)
    ap.add_argument("--write", action="store_true")
    ap.add_argument("--allow-large", action="store_true")
    ap.add_argument("--max-rows", type=int, default=25)
    ap.add_argument("--delay-s", type=float, default=1.7)
    args = ap.parse_args()
    dry_run = not args.write

    docs_dir = REPO / "docs"
    candidates, total_richland, no_street = _collect(docs_dir)
    print(f"Richland SC rows streamed: {total_richland:,}")
    print(f"missing raw['vacant_lot'] and no usable street address: {no_street:,}")
    print(f"missing raw['vacant_lot'] WITH a usable street address (real candidates): {len(candidates):,}")

    listings = list(candidates.values())
    before_raw = {li.dedupe_key(): dict(li.raw) for li in listings}

    t0 = time.monotonic()
    stats = asyncio.run(_canary_fetch(listings, max_rows=args.max_rows, delay_s=args.delay_s))
    elapsed = time.monotonic() - t0
    print(f"\nlive canary over {min(args.max_rows, len(listings))} rows, {elapsed:.1f}s elapsed:")
    print(" ", stats)

    patches = {key: {"raw": li.raw} for key, li in candidates.items()
               if li.raw != before_raw.get(key)}
    print(f"\nrows actually changed, patches staged: {len(patches):,}")

    if dry_run:
        print("\nDRY RUN -- nothing written. Re-run with --write --allow-large to land this.")
        return 0

    size_state = board_patch_size_state(docs_dir)
    if not size_state["ok"] and not args.allow_large:
        print(f"REFUSING: {size_state['reason']}. Re-run with --allow-large.")
        return 1
    if args.allow_large:
        import os
        os.environ["BOARD_PATCH_ALLOW_LARGE"] = "1"
    with board_lock(REPO, owner="richland_vacant_heir_backfill"):
        out = patch_existing_rows(patches, {"richland_vacant_heir_backfill": len(patches)},
                                  docs_dir=docs_dir)
        print("patch_existing_rows:", out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
