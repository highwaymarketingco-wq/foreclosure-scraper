#!/usr/bin/env python3
"""Backfill raw.owner_mailing.owner for rows that already got li.owner_name filled by a PAST
parcel_cache_join() run, so gap_matrix's atty_taxpayer_of_record credit (which checks
raw.owner_mailing.owner specifically, not the top-level owner_name field) recognizes them.

WHY THIS EXISTS. parcel_cache_join.apply_hit() was just fixed (2026-10-22) to stamp
owner_mailing.owner on every FUTURE cache-sourced owner-name fill -- but join_listings() is
also "fill only" (only acts when li.owner_name is empty), so rows whose owner_name was ALREADY
filled by an earlier pipeline run never get touched by the forward-looking fix alone. This
re-checks the cache for those rows specifically.

SCOPED, NOT A BLANKET COPY. owner_name can come from sources OTHER than the parcel cache
(a notice, a court caption, heir_estate, etc.) -- those are correctly NOT "taxpayer of record"
by gap_matrix's own careful design. This only stamps owner_mailing.owner when the CACHE'S OWN
owner name for that parcel_id corroborates (normalized match against) the row's current
owner_name -- i.e., the cache confirms this specific row's name really is the tax-roll name,
not a guess from wherever owner_name happened to come from.

Pure local sqlite lookups, no network -- same board-wide bounded-batch pattern as tonight's
deed_chain backfill (pass board in chunks, not all 447K rows' raw held in memory at once).

    python scripts/backfill_taxpayer_of_record_credit.py --dry-run
    BOARD_PATCH_ALLOW_LARGE=1 python scripts/backfill_taxpayer_of_record_credit.py
"""
from __future__ import annotations

import argparse
import os
import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "src"))

from foreclosure_scraper import parcel_cache as pc  # noqa: E402
from foreclosure_scraper.board_stream import iter_board_rows  # noqa: E402
from foreclosure_scraper.models import Listing  # noqa: E402
from foreclosure_scraper.web_artifact import (  # noqa: E402
    _APPEND_SIG_FIELDS, board_lock, board_patch_size_state, patch_existing_rows,
)

_LIGHT_FIELDS = _APPEND_SIG_FIELDS + ("raw", "owner_name")


def _norm(name: str) -> str:
    return re.sub(r"[^A-Z0-9]", "", (name or "").upper())


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--allow-large", action="store_true")
    ap.add_argument("--batch-size", type=int, default=20000)
    args = ap.parse_args()

    docs_dir = REPO / "docs"
    if not args.dry_run:
        size_state = board_patch_size_state(docs_dir)
        if not size_state["ok"] and not args.allow_large:
            print(f"REFUSING: {size_state['reason']}. Re-run with --allow-large.")
            return 1
        if args.allow_large:
            os.environ["BOARD_PATCH_ALLOW_LARGE"] = "1"

    total_rows = 0
    candidates = 0
    matched = 0
    mismatched = 0
    cache_miss = 0
    total_applied = 0
    batch: list[tuple[str, Listing]] = []

    def flush(batch: list[tuple[str, Listing]]) -> None:
        nonlocal total_applied
        if args.dry_run or not batch:
            return
        patches = {key: {"raw": {"owner_mailing": li.raw["owner_mailing"]}} for key, li in batch}
        with board_lock(REPO, owner="taxpayer_of_record_credit_backfill", wait=600, poll=10):
            pstats = patch_existing_rows(
                patches, {"taxpayer_of_record_credit_backfill_batch": len(patches)},
                docs_dir=docs_dir)
        print(f"  patch_existing_rows: {pstats}")
        total_applied += pstats.get("applied", 0)

    print("streaming board...")
    for rec in iter_board_rows(docs_dir / "listings.json.gz"):
        total_rows += 1
        owner_name = rec.get("owner_name")
        if not owner_name or not rec.get("parcel_id"):
            continue
        raw = rec.get("raw") if isinstance(rec.get("raw"), dict) else {}
        gis = raw.get("gis") if isinstance(raw.get("gis"), dict) else {}
        if gis.get("owner"):
            continue  # already credited via raw.gis.owner
        om = raw.get("owner_mailing") if isinstance(raw.get("owner_mailing"), dict) else {}
        if om.get("owner"):
            continue  # already credited
        county = (rec.get("county") or "").replace(" County", "").strip()
        state = rec.get("state")
        if not county or not state:
            continue
        candidates += 1
        try:
            hit = pc.lookup(county, rec["parcel_id"], state)
        except Exception:  # noqa: BLE001
            cache_miss += 1
            continue
        if not hit or not hit.get("owner"):
            cache_miss += 1
            continue
        if _norm(hit["owner"]) != _norm(owner_name):
            mismatched += 1
            continue
        matched += 1

        li = Listing.model_construct(**{k: rec.get(k) for k in _LIGHT_FIELDS})
        li.raw = dict(raw)
        new_om = dict(om)
        new_om["owner"] = hit["owner"]
        new_om.setdefault("source", "parcel_cache")
        li.raw["owner_mailing"] = new_om
        try:
            key = li.dedupe_key()
        except Exception:  # noqa: BLE001
            continue
        if not (li.parcel_id or li.street_address or (li.case_number and li.county)):
            continue
        batch.append((key, li))
        if len(batch) >= args.batch_size:
            print(f"  batch at row {total_rows:,} (matched so far: {matched:,})...")
            flush(batch)
            batch = []
    flush(batch)

    print(f"\nboard rows: {total_rows:,}")
    print(f"candidates (owner_name set, no existing credit, parcel_id present): {candidates:,}")
    print(f"cache match, name corroborated: {matched:,}")
    print(f"cache match, name DIFFERS (not stamped): {mismatched:,}")
    print(f"cache miss (not stamped): {cache_miss:,}")
    if args.dry_run:
        print("DRY RUN -- nothing written.")
    else:
        print(f"total applied: {total_applied:,}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
