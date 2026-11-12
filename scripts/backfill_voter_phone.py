#!/usr/bin/env python3
"""One-time backfill: run the existing, already-wired enrich_voter_phone() -- a free, local,
no-network NC voter-file name+address match -- against the FULL historical board, not just
whatever rows happened to be in main.py's own `enriched` working set on some past run.

scripts/fill_voter_phone.py and scripts/run_voter_phone.py both already exist for this, but
both use load_board()/write_artifact(), which this project has since measured impractical at
the board's current size (project_board_load_too_large_both_hosts_2026-10-20.md: VM disk
~69MB/s, 2+ hrs, often never finishes). enrich_voter_phone() itself is unaffected -- it's a
pure, synchronous, in-memory name+address match against a one-time-loaded voter-file index,
no network call at all -- so this script just gives it the modern streamed-read /
patch_existing_rows() board I/O instead.

Statewide NC, not county-scoped (enrich_voter_phone's own gate is just li.state == "NC"), so
this is a bigger potential win than the per-county backfills tonight -- but also a bigger,
less-tested index build (565MB of raw NCSBE voter files), so start small.

LOCK LESSON: lock wraps ONLY the per-batch patch_existing_rows() write, wait=600/poll=10.

    python scripts/backfill_voter_phone.py --dry-run --batch-size 2000 --max-batches 1
    BOARD_PATCH_ALLOW_LARGE=1 python scripts/backfill_voter_phone.py --batch-size 20000 --max-batches 20
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "src"))

from foreclosure_scraper.board_stream import iter_board_rows  # noqa: E402
from foreclosure_scraper.enrichment_voter_phone import enrich_voter_phone  # noqa: E402
from foreclosure_scraper.models import Listing  # noqa: E402
from foreclosure_scraper.web_artifact import (  # noqa: E402
    _APPEND_SIG_FIELDS, board_lock, board_patch_size_state, patch_existing_rows,
)

_LIGHT_FIELDS = _APPEND_SIG_FIELDS + ("raw", "owner_name")


def _has_phone(raw: dict) -> bool:
    return bool(isinstance(raw.get("owner_phone"), dict) and raw["owner_phone"].get("phone"))


def _candidates(docs_dir: Path) -> list[tuple[str, Listing]]:
    """{dedupe_key: light_listing} for every NC row with an owner_name and no owner_phone yet --
    streamed, not loaded, same discipline every backfill tonight used. The Listing carries its
    REAL state/owner_name/street_address/raw -- enrich_voter_phone() matches on those directly.

    REQUIRES parcel_id or street_address or (case_number and county) -- i.e. excludes any row
    whose dedupe_key() would fall through to the generic 'url:{source_url}' branch. Found live
    2026-10-22: 11,029 distinct Madison County rows share one bulk-portal URL
    (bcpwa.ncptscloud.com) as their only identity signal with none of the above fields set.
    patch_existing_rows() applies one patch to every row sharing a dedupe_key (by design -- a
    shared key means "same property"), so a single real voter match got stamped as that many
    DIFFERENT owners' phone number before being caught and reverted
    (scripts/revert_bad_voter_phone_match.py). This guard stops any row with no real identity
    signal from ever entering the candidate pool in the first place."""
    out = []
    for rec in iter_board_rows(docs_dir / "listings.json.gz"):
        if str(rec.get("state") or "").upper() != "NC":
            continue
        if not rec.get("owner_name"):
            continue
        if not (rec.get("parcel_id") or rec.get("street_address")
                or (rec.get("case_number") and rec.get("county"))):
            continue
        raw = rec.get("raw") if isinstance(rec.get("raw"), dict) else {}
        if _has_phone(raw):
            continue
        li = Listing.model_construct(**{k: rec.get(k) for k in _LIGHT_FIELDS})
        li.raw = dict(raw)
        try:
            key = li.dedupe_key()
        except Exception:  # noqa: BLE001
            continue
        out.append((key, li))
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--allow-large", action="store_true")
    ap.add_argument("--batch-size", type=int, default=20000)
    ap.add_argument("--max-batches", type=int, default=20)
    args = ap.parse_args()

    docs_dir = REPO / "docs"
    if not args.dry_run:
        size_state = board_patch_size_state(docs_dir)
        if not size_state["ok"] and not args.allow_large:
            print(f"REFUSING: {size_state['reason']}. Re-run with --allow-large.")
            return 1
        if args.allow_large:
            os.environ["BOARD_PATCH_ALLOW_LARGE"] = "1"

    print("streaming board for NC candidates (owner_name set, no owner_phone yet)...")
    all_cands = _candidates(docs_dir)
    print(f"NC candidates: {len(all_cands):,}")
    if not all_cands:
        print("nothing to do.")
        return 0

    total_matched = 0
    total_written = 0

    for batch_num in range(1, args.max_batches + 1):
        start = (batch_num - 1) * args.batch_size
        chunk = all_cands[start:start + args.batch_size]
        if not chunk:
            print(f"batch {batch_num}: no more rows, stopping")
            break
        print(f"\n=== voter_phone batch {batch_num}: {len(chunk)} rows ===")
        listings = [li for _, li in chunk]
        stats = enrich_voter_phone(listings)
        print(f"  {stats}")

        patches = {}
        for key, li in chunk:
            if _has_phone(li.raw):
                patches[key] = {"raw": {"owner_phone": li.raw.get("owner_phone")}}
        matched_this_batch = len(patches)
        total_matched += matched_this_batch
        print(f"  matched this batch: {matched_this_batch}")

        if args.dry_run:
            print("  DRY RUN -- not writing this batch.")
            continue
        if not patches:
            continue
        with board_lock(REPO, owner="voter_phone_backfill", wait=600, poll=10):
            pstats = patch_existing_rows(
                patches, {"voter_phone_backfill_batch": len(patches)}, docs_dir=docs_dir)
        print(f"  patch_existing_rows: {pstats}")
        total_written += pstats.get("applied", 0)

    print(f"\ntotals: matched={total_matched:,} written={total_written:,}")
    if args.dry_run:
        print("DRY RUN -- nothing written overall.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
