#!/usr/bin/env python3
"""One-off/repeatable backfill: patch the missing 'year' onto Greenville SC rows whose
raw['tax_owed'] already has a balance (from an older/different producer, e.g. the Taxsale
roster's generic promotion) but no usable year -- the EXACT blocker this module's own header
docstring already documented and enrichment_greenville_tax.patch_cached_tax_owed_year() fixes.

WHY THIS EXISTS (2026-11-16, gap_matrix sourced-not-built sweep). scripts/backfill_greenville_
tax.py (run 2026-11-12) fetched 3,268 Greenville parcels live and found bills on 3,247 of them,
but logged tax_owed_filled=0 the entire run -- NOT a bug in that run, every single one of those
rows already had SOME raw['tax_owed']['balance'] from an earlier, different producer (the
Taxsale roster's generic promotion via enrichment_tax_owed.py, or similar), so
enrich_greenville_tax()'s own "don't clobber an existing balance" guard correctly declined to
overwrite it with its own fresher-but-not-necessarily-more-authoritative block -- discarding
the 'year' it had just computed along with the rest of that block. Confirmed live via a direct
board_stream sample (read-only, this investigation): of 5,547 Greenville/SC rows, 3,346 already
carry a real raw['tax_owed']['balance'] but ZERO carry a real raw['tax_aging_surfaced'] --
because enrichment_tax_aging.py's first gate reads a SINGULAR raw['tax_owed']['year'] before it
ever calls tax_year_status() (the same contract just fixed for Florence this session, see
enrichment_florence_tax_inquiry.apply_block()'s 2026-11-16 commit), and Greenville's
pre-existing tax_owed blocks never had one.

This script does NOT re-fetch anything. Every row this module already queried (2026-11-12 run)
stored its full bill history on raw['greenville_tax_history']['bills'] (SOURCE_KEY) -- this
just re-derives build_tax_owed_block() from that SAME cached data and patches in only the
missing year/years/years_delinquent/status fields, leaving the existing balance/source/kind/
basis exactly as they are (patch_cached_tax_owed_year() itself enforces this -- see its
docstring). Pure/offline: zero network calls, safe to re-run any time new rows get a cached
greenville_tax_history without a yeared tax_owed.

Expected next step after this lands: re-run scripts/backfill_tax_aging_surfaced.py --state SC
--county Greenville to surface raw['tax_aging_surfaced'] from the now-yeared tax_owed blocks
(and from the 510 rows whose multi_year_delinquent_tax block already had everything it needed
-- that one needed no code change at all, just a re-run, confirmed by direct inspection before
writing this script).

BOARD I/O: streamed read-only via board_stream.iter_board_rows() (never load_board()), scoped
to state=="SC" and county=="Greenville" during the stream itself. Writes via
web_artifact.patch_existing_rows() with the same dedupe_key()-collision guard every sibling
backfill in this project uses.

    python scripts/backfill_greenville_tax_owed_year.py --dry-run
    BOARD_PATCH_ALLOW_LARGE=1 python scripts/backfill_greenville_tax_owed_year.py
"""
from __future__ import annotations

import argparse
import contextlib
import copy
import sys
from pathlib import Path
from typing import Optional

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "src"))

from foreclosure_scraper.board_stream import iter_board_rows  # noqa: E402
from foreclosure_scraper.enrichment_greenville_tax import (  # noqa: E402
    patch_cached_tax_owed_year,
)
from foreclosure_scraper.models import Listing  # noqa: E402
from foreclosure_scraper.web_artifact import BoardLockBusy, board_lock, patch_existing_rows  # noqa: E402

_LIGHT_FIELDS = ("state", "county", "parcel_id", "street_address", "zip_code",
                  "case_number", "source_url", "listing_type", "source", "raw")
_WATCH_KEYS = ("tax_owed",)


def _dedupe_key(li) -> Optional[str]:
    try:
        return li.dedupe_key()
    except Exception:  # noqa: BLE001 - a row too malformed to key is simply skipped
        return None


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    docs = REPO / "docs"

    board: list[Listing] = []
    keys: list[Optional[str]] = []
    before: list[dict] = []
    for rec in iter_board_rows(docs / "listings.json.gz"):
        if (rec.get("state") or "").strip().upper() != "SC":
            continue
        if (rec.get("county") or "").replace(" County", "").strip() != "Greenville":
            continue
        li = Listing.model_construct(**{k: rec.get(k) for k in _LIGHT_FIELDS})
        board.append(li)
        keys.append(_dedupe_key(li))
        raw = li.raw if isinstance(li.raw, dict) else {}
        # deepcopy, not a shallow {k: raw.get(k)} reference: patch_cached_tax_owed_year()
        # mutates the EXISTING raw['tax_owed'] dict IN PLACE (adds missing keys without
        # replacing the object, unlike enrich_greenville_tax()'s own to_block path, which
        # always assigns a brand-new dict) -- a shallow reference here would silently point
        # at the SAME object the patch later mutates, making every before/after diff below
        # compare a dict against itself and stage zero patches despite real in-memory changes.
        before.append(copy.deepcopy({k: raw.get(k) for k in _WATCH_KEYS}))

    key_counts: dict[str, int] = {}
    for k in keys:
        if k is not None:
            key_counts[k] = key_counts.get(k, 0) + 1

    print(f"Greenville/SC rows on board: {len(board):,}")

    patched_n = 0
    for li in board:
        if patch_cached_tax_owed_year(li):
            patched_n += 1
    print(f"rows patched (year added to existing tax_owed): {patched_n:,}")

    if args.dry_run:
        print("\n--dry-run: nothing written")
        return 0

    patches: dict[str, dict] = {}
    collisions = 0
    for li, key, b4 in zip(board, keys, before):
        raw = li.raw if isinstance(li.raw, dict) else {}
        after = {k: raw.get(k) for k in _WATCH_KEYS}
        if after == b4:
            continue
        if key is None:
            continue
        if key_counts.get(key, 0) > 1:
            collisions += 1
            continue
        patches[key] = {"raw": {k: v for k, v in after.items() if v is not None}}

    print(f"patches staged: {len(patches):,} (dropped as dedupe_key collisions: {collisions:,})")

    if patches:
        lock = board_lock(REPO, owner="backfill_greenville_tax_owed_year", wait=3600, poll=10)
        try:
            with lock:
                stats = patch_existing_rows(
                    patches, {"backfill_greenville_tax_owed_year": f"n={len(patches)}"},
                    docs_dir=docs)
        except BoardLockBusy as exc:
            print(f"{exc} -- refusing to write ({len(patches):,} patches from this "
                  f"invocation are lost; re-run to redo them and retry).")
            return 1
        print(f"patch_existing_rows: {stats}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
