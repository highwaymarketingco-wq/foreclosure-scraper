#!/usr/bin/env python3
"""One-off backfill: land the FLC opening-bid fix onto the ALREADY-PUBLISHED board.

WHY THIS EXISTS
    2026-09-29 audit of counties_sc.georgetown_civicengage (flagged as capturing
    NO real per-parcel tax amount at all, 355 board rows). Root cause: the FLC
    (Forfeited-Land-Commission) doc's parser already captured a real,
    county-published dollar figure onto Listing.opening_bid, but never wrote it
    into raw['georgetown_civicengage'] -- and enrichment_tax_owed.py reads raw
    sub-dicts, never Listing fields, so it could never see it (and didn't even
    have a mapping entry for this source until this same commit). Fixed going
    forward in georgetown_civicengage.py (parse_flc) and enrichment_tax_owed.py
    (_SOURCES). This script lands the same fix on the 55 FLC rows already
    published, without a full re-scrape/re-run.

    The other 300 published rows (the Tax-Sale doc) are NOT touched here --
    confirmed live 2026-09-29 that Georgetown's Tax-Sale PDF carries no dollar
    figure at all (see docs/extraction_gaps.md), so there is nothing to backfill
    for them.

BOARD I/O (same pattern as scripts/backfill_tax_owed_amount_owed.py)
    Streamed read-only via board_stream.iter_board_rows() -- load_board() is
    refused (BoardLoadTooLarge) against this board's real size and isn't needed:
    the decision only touches raw['georgetown_civicengage']['opening_bid'],
    raw['tax_owed'], and (when eligible) raw['amount_owed']. Only the ~55 rows
    that need a change are collected into a `patches` dict (Listing.dedupe_key()
    -> {"raw": {...}}) and landed with web_artifact.patch_existing_rows(), which
    streams the whole board through unchanged for everything else.

    This source has no dedupe_key() collision risk of the kind
    scripts/fix_amount_owed_collision_targets.py closed (that was a cross-SOURCE
    parcel-normalization collision on OTHER counties' data) but the same
    single-counted-key guard is applied anyway, cheaply, since it costs nothing
    at this row count and this script would rather skip a row than risk
    patching the wrong one.

    python scripts/backfill_georgetown_flc_tax_owed.py --dry-run
    python scripts/backfill_georgetown_flc_tax_owed.py
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

#: Same identity fields patch_existing_rows()/append_new_rows() use internally.
_SIG_FIELDS = ("state", "county", "parcel_id", "street_address", "zip_code",
              "case_number", "source_url", "listing_type")

SOURCE = "counties_sc.georgetown_civicengage"


def _dedupe_key(rec: dict) -> str | None:
    light = Listing.model_construct(**{k: rec.get(k) for k in _SIG_FIELDS})
    try:
        return light.dedupe_key()
    except Exception:  # noqa: BLE001 - a row too malformed to key is simply skipped
        return None


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    docs = REPO / "docs"
    lock = contextlib.nullcontext() if args.dry_run else board_lock(
        REPO, owner="backfill_georgetown_flc_tax_owed")

    with lock:
        key_counts: Counter = Counter()
        patches: dict[str, dict] = {}
        scanned = 0
        flc_rows_seen = 0
        already_has_tax_owed = 0
        skipped_no_key = 0
        skipped_no_bid = 0

        for rec in iter_board_rows(docs / "listings.json.gz"):
            scanned += 1
            key = _dedupe_key(rec)
            if key is None:
                if (rec.get("source") or "") == SOURCE:
                    skipped_no_key += 1
                continue
            key_counts[key] += 1

            if (rec.get("source") or "") != SOURCE:
                continue
            raw = rec.get("raw") or {}
            blk = raw.get("georgetown_civicengage") or {}
            if blk.get("doc") != "flc":
                continue
            flc_rows_seen += 1

            if raw.get("tax_owed"):
                already_has_tax_owed += 1  # already fixed by a later scrape; skip
                continue

            bid = rec.get("opening_bid")
            try:
                bid = float(bid) if bid else None
            except (TypeError, ValueError):
                bid = None
            if not bid or bid <= 0:
                skipped_no_bid += 1
                continue

            new_blk = dict(blk)
            new_blk["opening_bid"] = bid
            new_raw = {"georgetown_civicengage": new_blk,
                       "tax_owed": {"balance": bid, "kind": "flc_opening_bid",
                                    "source": SOURCE, "year": None,
                                    "basis": "own_record"}}
            # Only promote amount_owed if the existing one isn't a judgment/
            # opening_bid figure for a DIFFERENT debt -- same rule
            # _tax_owed_promotion() applies in the normal pipeline.
            probe_raw = dict(raw)
            probe_raw["tax_owed"] = new_raw["tax_owed"]
            new_ao = _tax_owed_promotion(probe_raw)
            if new_ao is not None:
                new_raw["amount_owed"] = new_ao
            patches[key] = {"raw": new_raw}

        collision_keys = {k for k in patches if key_counts[k] > 1}
        for k in collision_keys:
            del patches[k]

        print(f"scanned {scanned:,} board rows")
        print(f"georgetown_civicengage FLC rows seen: {flc_rows_seen}")
        print(f"  already had tax_owed (skipped, no-op): {already_has_tax_owed}")
        print(f"  no positive opening_bid (skipped): {skipped_no_bid}")
        print(f"  no dedupe key (skipped): {skipped_no_key}")
        print(f"  dropped as dedupe_key collisions: {len(collision_keys)}")
        print(f"eligible for patch: {len(patches)}")

        if args.dry_run:
            print("\nDRY RUN — nothing written. Sample patches:")
            for k, v in list(patches.items())[:5]:
                print(f"  {k}: {v['raw']['tax_owed']}  amount_owed="
                      f"{v['raw'].get('amount_owed')}")
            return 0

        if not patches:
            print("\nNothing to patch.")
            return 0

        stats = patch_existing_rows(
            patches, {"backfill_georgetown_flc_tax_owed": f"n={len(patches)}"},
            docs_dir=docs)
        print(f"\n=== RESULTS ===")
        print(stats)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
