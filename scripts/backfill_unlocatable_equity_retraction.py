#!/usr/bin/env python3
"""One-off backfill: retract the phantom equity_band the ALREADY-PUBLISHED board
carries on "unlocatable" leads (no street_address AND no parcel_id).

WHY THIS EXISTS
    2026-09-29 re-measurement of docs/extraction_gaps.md's "Unlocatable" line
    (the old 5,565/14.5% figure was stale by ~7x -- the live number is 39,564,
    18.0% of the 219,530-row board, mostly NC eCourts lis pendens/judgments/
    divorce, courtlistener bankruptcy, and SC public-index name-only leads).

    Root cause of the tier-inflation half of that finding: `distress_score.
    _equity_info()` reads raw['equity']/raw['calc'] regardless of whether the
    listing itself was ever tied to a real address or parcel. For a listing
    with neither, any ARV on it came from comps run against a ZIP/county
    centroid (raw['geo_imprecise'] == 'centroid_snap') for AN UNKNOWN HOUSE --
    `enrichment_calc`'s own data_quality block already says so on the card
    ("no address resolved ... ARV UNVERIFIED ... no deal verdict is
    published"), but the scorer never checked location, so a bare lis_pendens
    (score 28, no mailing, no other evidence) rode a phantom, unevidenced
    "equity_band": "high" straight to WARM via the `score >= 28 and eq_ok`
    route. Measured live: 2,653 of 39,564 unlocatable rows (6.7%) were WARM,
    almost all uncontactable (`contactable: false`) and unevidenced
    (`equity_evidenced: false`).

    Fixed going forward in distress_score.py's group-scoring step (only
    listings with a street_address or parcel_id contribute to a group's
    `eq`/`eq_evidenced`; see the F20 comment there and
    tests/test_scoring_audit_fixes.py's F20 tests). This script lands the
    same correction on the rows already published, without a full re-score
    (score_board() needs load_board(), which this board's size refuses).

    It reuses distress_score.retract_equity_rank() -- the function this
    codebase already built for exactly this shape of problem ("pull the
    equity term out of an already-published distress_stack", written for
    enrichment_board_qa's county-appraisal retraction) -- rather than
    reimplementing the tier math here.

BOARD I/O (same pattern as scripts/backfill_georgetown_flc_tax_owed.py)
    Streamed read-only via board_stream.iter_board_rows(). Only unlocatable
    rows (no street_address AND no parcel_id) whose published distress_stack
    carries a non-null equity_band are collected into a `patches` dict
    (Listing.dedupe_key() -> {"raw": {"distress_stack": ...}}) and landed with
    web_artifact.patch_existing_rows(), which streams the whole board through
    unchanged for everything else and MERGES the raw update (only
    distress_stack changes; grade/calc/skip_trace/... on the row are
    untouched).

    python scripts/backfill_unlocatable_equity_retraction.py --dry-run
    python scripts/backfill_unlocatable_equity_retraction.py
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
from foreclosure_scraper.distress_score import retract_equity_rank  # noqa: E402
from foreclosure_scraper.models import Listing  # noqa: E402
from foreclosure_scraper.web_artifact import board_lock, patch_existing_rows  # noqa: E402

#: Same identity fields patch_existing_rows()/append_new_rows() use internally.
_SIG_FIELDS = ("state", "county", "parcel_id", "street_address", "zip_code",
              "case_number", "source_url", "listing_type")


def _dedupe_key(rec: dict) -> str | None:
    light = Listing.model_construct(**{k: rec.get(k) for k in _SIG_FIELDS})
    try:
        return light.dedupe_key()
    except Exception:  # noqa: BLE001 - a row too malformed to key is simply skipped
        return None


def _is_unlocatable(rec: dict) -> bool:
    return not ((rec.get("street_address") or "").strip()
                or (rec.get("parcel_id") or "").strip())


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    docs = REPO / "docs"
    lock = contextlib.nullcontext() if args.dry_run else board_lock(
        REPO, owner="backfill_unlocatable_equity_retraction")

    with lock:
        key_counts: Counter = Counter()
        patches: dict[str, dict] = {}
        by_tier_before: Counter = Counter()
        by_tier_after: Counter = Counter()
        scanned = 0
        unlocatable_seen = 0
        no_equity_band = 0
        skipped_no_key = 0

        for rec in iter_board_rows(docs / "listings.json.gz"):
            scanned += 1
            key = _dedupe_key(rec)
            if key is None:
                if _is_unlocatable(rec):
                    skipped_no_key += 1
                continue
            key_counts[key] += 1

            if not _is_unlocatable(rec):
                continue
            unlocatable_seen += 1

            raw = rec.get("raw") if isinstance(rec.get("raw"), dict) else {}
            ds = raw.get("distress_stack")
            if not isinstance(ds, dict) or ds.get("equity_band") is None:
                no_equity_band += 1
                continue

            by_tier_before[ds.get("tier") or "?"] += 1
            li = Listing.model_construct(raw=raw)
            changed = retract_equity_rank(li)
            if not changed:
                # defensive: retract_equity_rank() itself found nothing to remove
                no_equity_band += 1
                continue
            new_ds = li.raw["distress_stack"]
            by_tier_after[new_ds.get("tier") or "?"] += 1
            patches[key] = {"raw": {"distress_stack": new_ds}}

        collision_keys = {k for k in patches if key_counts[k] > 1}
        for k in collision_keys:
            del patches[k]

        print(f"scanned {scanned:,} board rows")
        print(f"unlocatable rows (no street_address AND no parcel_id): {unlocatable_seen:,}")
        print(f"  no equity_band to retract (already clean): {no_equity_band:,}")
        print(f"  no dedupe key (skipped): {skipped_no_key}")
        print(f"  dropped as dedupe_key collisions: {len(collision_keys)}")
        print(f"eligible for patch: {len(patches):,}")
        print(f"tier before retraction: {dict(by_tier_before)}")
        print(f"tier after retraction:  {dict(by_tier_after)}")

        if args.dry_run:
            print("\nDRY RUN — nothing written. Sample patches:")
            for k, v in list(patches.items())[:5]:
                print(f"  {k}: tier={v['raw']['distress_stack']['tier']} "
                      f"equity_band={v['raw']['distress_stack']['equity_band']}")
            return 0

        if not patches:
            print("\nNothing to patch.")
            return 0

        stats = patch_existing_rows(
            patches,
            {"backfill_unlocatable_equity_retraction": f"n={len(patches)}"},
            docs_dir=docs)
        print("\n=== RESULTS ===")
        print(stats)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
