#!/usr/bin/env python3
"""One-time backfill: stamp raw['multi_year_delinquent_tax'] / raw['two_year_delinquent'] /
raw['_nc_csv_tax_mydt_checked'] onto EXISTING New Hanover NC board rows that
nc_county_csv_delinquent_tax.py already landed, from data the row already carries.

CONTEXT (2026-11-16/17 gap_matrix "no source known" tax-cluster survey). The scraper always
aggregated every (parcel, bill-year) CSV row into one lead per parcel and already stashed the
full per-parcel year set at raw['nc_county_csv_delinquent_tax']['bill_years'] -- direct,
zero-inference evidence of how many distinct tax years are unpaid -- but never copied that into
gap_matrix.py's own raw['multi_year_delinquent_tax'] / raw['two_year_delinquent'] keys, so every
existing New Hanover row (landed by a PRIOR, working run of the scraper, before the county
rotated this same DocumentCenter URL to an .xlsx the old code couldn't read -- see this file's
own 2026-11-17 docstring fix) is missing the new keys even though the evidence for them has
been sitting on the board the whole time. This script needs no live fetch and no re-run of the
scraper: it just derives the new keys from the bill_years list each row already has.

A FUTURE run of the fixed scraper (now xlsx-aware) lands these keys directly on every new/
re-scraped row going forward; this is only for the backlog already on the board.

    python scripts/backfill_nc_csv_tax_multiyear.py --dry-run
    BOARD_PATCH_ALLOW_LARGE=1 python scripts/backfill_nc_csv_tax_multiyear.py
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
    _APPEND_SIG_FIELDS, board_lock, board_patch_size_state, patch_existing_rows,
)

RAW_KEY = "nc_county_csv_delinquent_tax"
MYDT_KEY = "multi_year_delinquent_tax"
TWOYR_KEY = "two_year_delinquent"
CHECKED_KEY = "_nc_csv_tax_mydt_checked"

_IS_NEW_HANOVER = lambda rec: (  # noqa: E731
    str(rec.get("county") or "").replace(" County", "").strip().lower() == "new hanover"
    and str(rec.get("state") or "").upper() == "NC"
)


def _candidates(docs_dir: Path) -> list[tuple[str, dict]]:
    """Every New Hanover NC row this scraper already landed (raw[RAW_KEY] present) that has
    not yet been stamped with the new columns. Returns (dedupe_key, full_updated_raw_dict)."""
    out: list[tuple[str, dict]] = []
    for rec in iter_board_rows(docs_dir / "listings.json.gz"):
        if not _IS_NEW_HANOVER(rec):
            continue
        raw = rec.get("raw") if isinstance(rec.get("raw"), dict) else {}
        blk = raw.get(RAW_KEY)
        if not isinstance(blk, dict):
            continue  # not landed by this producer at all
        if MYDT_KEY in raw or CHECKED_KEY in raw or TWOYR_KEY in raw:
            continue  # already stamped (idempotent re-run)
        years = blk.get("bill_years") or []
        is_multi = len(years) >= 2
        new_raw = dict(raw)
        new_raw[TWOYR_KEY] = {
            "is_two_year_plus": is_multi,
            "years_delinquent": len(years),
            "bill_years": years,
            "source": RAW_KEY,
        }
        if is_multi:
            new_raw[MYDT_KEY] = {
                "years_delinquent": len(years), "bill_years": years, "source": RAW_KEY,
            }
        else:
            new_raw[CHECKED_KEY] = True
        li = Listing.model_construct(**{k: rec.get(k) for k in _APPEND_SIG_FIELDS if k in rec})
        out.append((li.dedupe_key(), new_raw))
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--allow-large", action="store_true")
    args = ap.parse_args()

    docs_dir = REPO / "docs"
    if not args.dry_run:
        size_state = board_patch_size_state(docs_dir)
        if not size_state["ok"] and not args.allow_large:
            print(f"REFUSING: {size_state['reason']}. Re-run with --allow-large.")
            return 1
        if args.allow_large:
            os.environ["BOARD_PATCH_ALLOW_LARGE"] = "1"

    cands = _candidates(docs_dir)
    multi = sum(1 for _, r in cands if MYDT_KEY in r)
    print(f"New Hanover rows to stamp: {len(cands)} "
          f"(multi_year_delinquent_tax hit: {multi}, checked-only: {len(cands) - multi})")
    if not cands:
        print("nothing to do.")
        return 0

    if args.dry_run:
        print("\nDRY RUN -- nothing written.")
        return 0

    all_patches = {key: {"raw": new_raw} for key, new_raw in cands}
    with board_lock(REPO, owner="nc_csv_tax_multiyear_backfill", wait=600, poll=10):
        wstats = patch_existing_rows(
            all_patches, {"nc_csv_tax_multiyear_backfill": len(all_patches)}, docs_dir=docs_dir)
        print("patch_existing_rows:", wstats)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
