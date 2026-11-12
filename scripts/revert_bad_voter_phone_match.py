#!/usr/bin/env python3
"""One-time, targeted revert: scripts/backfill_voter_phone.py's batch 5 (2026-10-22) matched
ONE dedupe_key -- url:https://bcpwa.ncptscloud.com/ -- that 11,029 distinct Madison County NC
board rows collapse onto (they all lack parcel_id/street_address/case_number+county, so
dedupe_key() falls back to the generic portal URL every row on this source shares). Because
patch_existing_rows() applies the same patch to every row under a shared key (by design, on
the assumption a shared key IS the same property -- see its own docstring), one voter match
("MORGAN,GLENN"'s phone) got stamped onto all 11,029 of them, most of which are a DIFFERENT
real owner (sample checked: "MCKAIG, FRED").

This clears owner_phone back to absent (not present at all -- same patch mechanism, raw.update()
only touches keys it's given, so this is a precise, single-field revert that leaves every row's
OTHER raw data, which differs row to row, untouched) for exactly this one bad batch. It does
NOT touch backfill_voter_phone.py's other 8 batches' matches, which were all clean (each had a
specific parcel_id/street_address-based key, applied == patches, no inflation).

    python scripts/revert_bad_voter_phone_match.py --dry-run
    BOARD_PATCH_ALLOW_LARGE=1 python scripts/revert_bad_voter_phone_match.py
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "src"))

from foreclosure_scraper.board_stream import iter_board_rows  # noqa: E402
from foreclosure_scraper.models import Listing  # noqa: E402
from foreclosure_scraper.web_artifact import (  # noqa: E402
    _APPEND_SIG_FIELDS, board_lock, patch_existing_rows,
)

BAD_URL = "https://bcpwa.ncptscloud.com/"
BAD_MATCHED_NAME = "MORGAN,GLENN"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    docs_dir = REPO / "docs"
    affected = 0
    key = None
    for rec in iter_board_rows(docs_dir / "listings.json.gz"):
        if rec.get("source_url") != BAD_URL:
            continue
        if rec.get("parcel_id") or rec.get("street_address") or (
                rec.get("case_number") and rec.get("county")):
            continue
        raw = rec.get("raw") if isinstance(rec.get("raw"), dict) else {}
        op = raw.get("owner_phone")
        if not (isinstance(op, dict) and op.get("matched_name") == BAD_MATCHED_NAME):
            continue
        affected += 1
        if key is None:
            li = Listing.model_construct(**{k: rec.get(k) for k in _APPEND_SIG_FIELDS})
            key = li.dedupe_key()

    print(f"rows carrying the bad match: {affected:,}")
    print(f"shared dedupe_key: {key!r}")
    if not key:
        print("nothing to revert.")
        return 0

    patches = {key: {"raw": {"owner_phone": None}}}
    if args.dry_run:
        print("DRY RUN -- would patch this one key (applies to all rows sharing it).")
        return 0

    os.environ["BOARD_PATCH_ALLOW_LARGE"] = "1"
    with board_lock(REPO, owner="revert_bad_voter_phone_match", wait=600, poll=10):
        pstats = patch_existing_rows(patches, {"revert_bad_voter_phone_match": 1}, docs_dir=docs_dir)
    print("patch_existing_rows:", pstats)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
