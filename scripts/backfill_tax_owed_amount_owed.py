#!/usr/bin/env python3
"""One-off backfill: promote raw['tax_owed'] into raw['amount_owed'] on the
ALREADY-PUBLISHED board, for rows main.py's normal pipeline never got to fix.

WHY THIS EXISTS
    enrichment_amount_owed.enrich_amount_owed() (the cross-source "amount owed"
    waterfall the dashboard/valuation engine reads) runs BEFORE
    enrichment_tax_owed.enrich_tax_owed() in main.py's pipeline -- tax_owed depends
    on the resolver having run first. So on every run to date, the waterfall could
    only ever see judgment_amount / opening_bid / assessed_value / tax_value; it has
    never once seen the real, county-stated delinquent-tax balance enrich_tax_owed
    normalizes into raw['tax_owed'] a few steps later.

    Measured live on the 2026-09-29 board (219,530 rows, docs/board.manifest.json):
    88,959 rows carry a real raw['tax_owed'].balance. Of those, only 628 (0.7%)
    show it as amount_owed. 35,694 show nothing; 33,576+ show a mislabeled,
    is_actual_debt=False assessed-value PROXY despite the real number sitting one
    key over -- counties_sc.qpaybill_delinquent_roll alone (31,231 rows, every one
    of them carrying a real balance) had only 36 rows correctly surfaced. This is
    the exact "proxy value confused with a real debt amount" defect docs/HANDOFF.md's
    mandate flags, and it is far larger than the parcel-mismatch join gap
    docs/extraction_gaps.md's 2026-08-14 note described (that note is now stale;
    see the same date's entry in docs/extraction_gaps.md for the correction).

    A new call to enrichment_amount_owed.promote_tax_owed_amount_owed() now runs
    every future main.py pipeline pass right after enrich_tax_owed, so this defect
    will not recur going forward. This script fixes the SAME defect on the board
    that is already published, without waiting for (or forcing) a full re-run.

BOARD I/O (audit O13 / task_0658b33b pattern)
    load_board() self-refuses on this board's real size (BoardLoadTooLarge --
    measured 11.1 GB physical footprint against 217,883 rows, per
    web_artifact.BOARD_LOAD_MAX_SOURCE_MB's comment). This script never calls it:
    the board is streamed read-only via board_stream.iter_board_rows() (no
    lazy-detail sidecar needed -- the decision only touches raw['tax_owed'] and
    raw['amount_owed']). The promotion decision itself is the SAME pure-dict logic
    enrichment_amount_owed._tax_owed_promotion() uses on real Listing objects in the
    main pipeline, called directly on the raw dict here so no row is ever paid for
    with a Listing.model_validate() it doesn't need. Only rows that need a change
    are collected into a small `patches` dict (Listing.dedupe_key() -> {"raw": {...}})
    and landed with web_artifact.patch_existing_rows(), which streams the existing
    board through unchanged for everything else -- see that function's docstring.

    COLLISION GUARD (added after the 2026-09-29 run, see
    scripts/fix_amount_owed_collision_targets.py for the incident this closes). The
    board holds pairs of rows, from DIFFERENT scrapers, whose raw parcel_id strings
    differ but normalize (Listing._normalize_parcel's zero-pad stripping) to the
    SAME dedupe_key() -- a pre-existing un-merged-duplicate condition this script
    does not create and cannot fix, but must not be tripped by either.
    patch_existing_rows()'s own contract is explicit: "a dedupe_key() matching MORE
    than one existing row ... gets the SAME patch applied to every match, not just
    the first." The first version of this script built `pending` in ONE streaming
    pass and hit exactly that: 331 rows on the 2026-09-29 board shared a key with a
    DIFFERENT, judgment_amount-bearing row that was never itself a candidate (its
    OWN amount_owed.source was already "judgment", correctly skipped) -- but because
    its ELIGIBLE sibling's promotion got queued under the SAME key, both rows
    received the sibling's tax_owed value, silently overwriting 331 legitimate
    judgment figures. Fixed by running TWO passes: pass 1 tallies how many DISTINCT
    board rows produce each dedupe_key() (every row counts, eligible or not) and
    separately records the promotion for any eligible one; pass 2 patches only the
    keys counted exactly once. A key counted more than once is dropped from this
    run entirely (reported as `skipped_collision`) rather than guessed at -- a
    missed promotion costs nothing this pass can't retry once the underlying
    un-merged duplicate is fixed; a wrong guess corrupts a different, unrelated row.

    python scripts/backfill_tax_owed_amount_owed.py --dry-run
    python scripts/backfill_tax_owed_amount_owed.py
"""
from __future__ import annotations

import argparse
import contextlib
import sys
from collections import Counter
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "src"))

from foreclosure_scraper.board_stream import iter_board_rows  # noqa: E402
from foreclosure_scraper.enrichment_amount_owed import _tax_owed_promotion  # noqa: E402
from foreclosure_scraper.models import Listing  # noqa: E402
from foreclosure_scraper.web_artifact import board_lock, patch_existing_rows  # noqa: E402

#: Same identity fields patch_existing_rows()/append_new_rows() use internally
#: (web_artifact._APPEND_SIG_FIELDS) -- kept as a local literal rather than
#: importing a private symbol across modules.
_SIG_FIELDS = ("state", "county", "parcel_id", "street_address", "zip_code",
              "case_number", "source_url", "listing_type")

CHECKPOINT_EVERY = 20_000  # rows scanned between patch_existing_rows() writes


def _dedupe_key(rec: dict) -> str | None:
    light = Listing.model_construct(**{k: rec.get(k) for k in _SIG_FIELDS})
    try:
        return light.dedupe_key()
    except Exception:  # noqa: BLE001 - a row too malformed to key is simply skipped
        return None


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--limit", type=int, default=None,
                    help="Stop after inspecting this many board rows (testing)")
    args = ap.parse_args()

    docs = REPO / "docs"
    lock = contextlib.nullcontext() if args.dry_run else board_lock(
        REPO, owner="backfill_tax_owed_amount_owed")

    with lock:
        # --- PASS 1 (read-only): tally every row's dedupe_key(), and separately record the
        # promotion for any row that is itself eligible. A key seen more than once means at
        # least two DISTINCT board rows share it -- see the COLLISION GUARD note above -- and
        # is dropped from `promotions` before pass 2 ever runs, however many of the rows under
        # it were themselves eligible.
        key_counts: Counter = Counter()
        promotions: dict[str, dict] = {}
        promoted_source: dict[str, str] = {}
        scanned = 0
        skipped_no_key = 0

        for rec in iter_board_rows(docs / "listings.json.gz"):
            scanned += 1
            key = _dedupe_key(rec)
            if key is None:
                skipped_no_key += 1
            else:
                key_counts[key] += 1
                new_ao = _tax_owed_promotion(rec.get("raw") or {})
                if new_ao is not None:
                    promotions[key] = {"raw": {"amount_owed": new_ao}}
                    promoted_source[key] = rec.get("source") or "?"
            if args.limit and scanned >= args.limit:
                break

        collision_keys = {k for k in promotions if key_counts[k] > 1}
        by_source_promoted: Counter = Counter()
        for k in collision_keys:
            del promotions[k]
        for k, src in promoted_source.items():
            if k not in collision_keys:
                by_source_promoted[src] += 1

        print(f"pass 1: scanned {scanned:,} rows, {len(promotions):,} eligible for promotion, "
              f"{len(collision_keys):,} dropped as dedupe_key collisions "
              f"(no dedupe key at all: {skipped_no_key:,})")

        if args.dry_run:
            print("\nDRY RUN — nothing written.")
            print("top sources that would be promoted:")
            for src, n in by_source_promoted.most_common(15):
                print(f"  {n:7,d}  {src}")
            return 0

        # --- PASS 2: land the collision-free promotions, checkpointed. ---
        items = list(promotions.items())
        applied_total = 0
        for i in range(0, len(items), CHECKPOINT_EVERY):
            chunk = dict(items[i:i + CHECKPOINT_EVERY])
            stats = patch_existing_rows(
                chunk, {"backfill_tax_owed_amount_owed": f"chunk={i}"}, docs_dir=docs)
            applied_total += stats["applied"]
            print(f"  [checkpoint {i}] patched {stats['applied']}/{len(chunk)} "
                  f"(existing board: {stats['existing']:,}, "
                  f"not_found: {stats['not_found']}, "
                  f"duplicate_key_matches: {stats['duplicate_key_matches']})", flush=True)

        print(f"\n=== RESULTS ===")
        print(f"rows scanned: {scanned:,}")
        print(f"rows promoted: {applied_total:,}")
        print(f"dropped as dedupe_key collisions: {len(collision_keys):,}")
        print(f"rows with a promotion but no dedupe key (skipped): {skipped_no_key:,}")
        print("top sources promoted:")
        for src, n in by_source_promoted.most_common(15):
            print(f"  {n:7,d}  {src}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
