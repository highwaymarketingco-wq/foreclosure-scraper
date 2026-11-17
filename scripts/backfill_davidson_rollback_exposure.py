#!/usr/bin/env python3
"""One-time backfill: run the newly-built enrichment_davidson_rollback_exposure.py (round 18,
2026-11-17 -- see that module's own docstring for the live evidence this is based on) over
Davidson NC's already-published board rows, so the owner-name+street-address-confirmed
"Deferred Value" producer actually lands real raw['rollback_exposure'] data, not just exists in
code (same reason every prior county-wiring round in this project needed its own backfill
script: the normal scrape-and-merge cycle only enriches NEWLY scraped rows, never the existing
historical board).

BOARD I/O (this round's own documented discipline): streams the board via
board_stream.iter_board_rows() (NEVER load_board(), NEVER json.load() on the whole file) and
lands the result with ONE patch_existing_rows() call under board_lock(REPO) (the real absolute
repo path, never Path('.')), same discipline as every backfill before this one
(scripts/backfill_vance_ustaxdata_tax.py, which this script's own shape is adapted from).

Usage:
    python scripts/backfill_davidson_rollback_exposure.py --dry-run
    python scripts/backfill_davidson_rollback_exposure.py --allow-large
"""
from __future__ import annotations

import argparse
import asyncio
import contextlib
import os
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "src"))

from foreclosure_scraper.board_stream import iter_board_rows  # noqa: E402
from foreclosure_scraper.enrichment_davidson_rollback_exposure import (  # noqa: E402
    enrich_davidson_rollback_exposure,
)
from foreclosure_scraper.models import Listing  # noqa: E402
from foreclosure_scraper.web_artifact import (  # noqa: E402
    _APPEND_SIG_FIELDS, board_lock, board_patch_size_state, patch_existing_rows,
)

COUNTY = "Davidson"
_LIGHT_FIELDS = _APPEND_SIG_FIELDS + ("raw", "owner_name")
_WATCH_KEYS = ("rollback_exposure",)


def _is_davidson_nc(rec: dict) -> bool:
    return (str(rec.get("county") or "").replace(" County", "").strip().lower() == COUNTY.lower()
            and str(rec.get("state") or "").upper() == "NC")


def _already_done(raw) -> bool:
    return isinstance(raw, dict) and isinstance(raw.get("rollback_exposure"), dict)


def _light(rec: dict) -> Listing:
    li = Listing.model_construct(**{k: rec.get(k) for k in _LIGHT_FIELDS if k in rec})
    if not isinstance(li.raw, dict):
        li.raw = {}
    return li


def _collect_candidates(docs_path: str) -> tuple[dict[str, Listing], int, int]:
    """{dedupe_key: light_listing} for every Davidson NC row with an owner_name + street_address
    (the module's own eligibility gate) not already carrying raw['rollback_exposure']. Streamed
    via board_stream.iter_board_rows() -- never load_board(), never the whole board held as a
    parsed list."""
    cands: dict[str, Listing] = {}
    seen: dict[str, int] = {}
    total = 0
    for rec in iter_board_rows(docs_path):
        total += 1
        if not _is_davidson_nc(rec):
            continue
        if not (rec.get("owner_name") and (rec.get("street_address") or "").strip()):
            continue
        if _already_done(rec.get("raw")):
            continue
        li = _light(rec)
        try:
            key = li.dedupe_key()
        except Exception:  # noqa: BLE001
            continue
        seen[key] = seen.get(key, 0) + 1
        cands[key] = li
    ambiguous = 0
    for key, n in seen.items():
        if n > 1:
            cands.pop(key, None)
            ambiguous += 1
    return cands, total, ambiguous


def _build_patches(candidates: dict[str, Listing], before: dict[str, dict]) -> dict[str, dict]:
    patches: dict[str, dict] = {}
    for key, li in candidates.items():
        after_raw = li.raw if isinstance(li.raw, dict) else {}
        b_raw = before[key]
        raw_patch = {k: after_raw.get(k) for k in _WATCH_KEYS if after_raw.get(k) != b_raw.get(k)}
        if raw_patch:
            patches[key] = {"raw": raw_patch}
    return patches


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--allow-large", action="store_true")
    args = ap.parse_args()

    docs = REPO / "docs"
    docs_path = str(docs / "listings.json.gz")

    lock = contextlib.nullcontext() if args.dry_run else board_lock(REPO, owner="davidson_rollback_backfill")
    with lock:
        candidates, total_rows, ambiguous = _collect_candidates(docs_path)
        print(f"board rows streamed: {total_rows:,}")
        print(f"{COUNTY} NC eligible candidates (owner_name+street_address, not yet checked): "
              f"{len(candidates):,}")
        if ambiguous:
            print(f"excluded as ambiguous-identity (shared dedupe_key with another candidate, "
                  f"never guessed at): {ambiguous:,}")

        before = {key: (dict(li.raw) if isinstance(li.raw, dict) else {})
                 for key, li in candidates.items()}

        listings = list(candidates.values())
        stats = {}
        if listings:
            print(f"\n=== {COUNTY} NC: running enrich_davidson_rollback_exposure "
                  f"({len(listings):,} eligible rows) ===")
            stats = asyncio.run(enrich_davidson_rollback_exposure(listings))
            print(f"  {stats}")

        patches = _build_patches(candidates, before)
        print(f"\npatches staged: {len(patches):,}")

        if args.dry_run:
            print("\nDRY RUN -- nothing written. (Note: the enrichment above still hits the "
                  "real live vendor -- this module has no network-free dry-run mode; --dry-run "
                  "here only controls whether the result is WRITTEN to the board.)")
            return 0
        if not patches:
            print("\nnothing to do.")
            return 0

        size_state = board_patch_size_state(docs)
        if not size_state["ok"] and not args.allow_large:
            print(f"\nREFUSING: {size_state['reason']}. Re-run with --allow-large under "
                  f"supervision.")
            return 1
        if args.allow_large:
            os.environ["BOARD_PATCH_ALLOW_LARGE"] = "1"

        stats_patch = patch_existing_rows(
            patches, {"davidson_rollback_backfill": len(patches), "ambiguous": ambiguous},
            docs_dir=docs)
        print(f"\nwrote board: patched {stats_patch['applied']:,}/{len(patches):,} rows "
              f"(existing board: {stats_patch['existing']:,}, not_found: "
              f"{stats_patch['not_found']:,}, duplicate_key_matches: "
              f"{stats_patch['duplicate_key_matches']:,})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
