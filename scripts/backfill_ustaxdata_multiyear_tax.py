#!/usr/bin/env python3
"""One-time backfill: restate multi_year_delinquent_tax + two_year_delinquent for every NC
Robeson/Alexander/Rockingham row that already carries raw['ustaxdata_delinquent_tax'] -- pure
compute, NO network call at all. Same shape as backfill_johnston_tax_restatement.py.

Usage:
    python scripts/backfill_ustaxdata_multiyear_tax.py --dry-run
    python scripts/backfill_ustaxdata_multiyear_tax.py --allow-large
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "src"))

from foreclosure_scraper.board_stream import iter_board_rows  # noqa: E402
from foreclosure_scraper.enrichment_ustaxdata_multiyear_tax import (  # noqa: E402
    RAW_KEY, TWO_YEAR_KEY, _eligible, enrich_ustaxdata_multiyear_tax,
)
from foreclosure_scraper.models import Listing  # noqa: E402
from foreclosure_scraper.web_artifact import (  # noqa: E402
    _APPEND_SIG_FIELDS, board_lock, board_patch_size_state, patch_existing_rows,
)

_LIGHT_FIELDS = _APPEND_SIG_FIELDS + ("raw",)
_WATCH_KEYS = (RAW_KEY, TWO_YEAR_KEY)


def _light(rec: dict) -> Listing:
    return Listing.model_construct(**{k: rec.get(k) for k in _LIGHT_FIELDS})


def _collect_candidates(docs: Path) -> tuple[dict[str, Listing], int]:
    cands: dict[str, Listing] = {}
    total = 0
    for rec in iter_board_rows(docs / "listings.json.gz"):
        total += 1
        li = _light(rec)
        if not _eligible(li):
            continue
        try:
            key = li.dedupe_key()
        except Exception:  # noqa: BLE001
            continue
        cands[key] = li
    return cands, total


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--allow-large", action="store_true")
    args = ap.parse_args()

    docs = REPO / "docs"
    candidates, total_rows = _collect_candidates(docs)
    print(f"board rows streamed: {total_rows:,}")
    print(f"NC Robeson/Alexander/Rockingham candidates: {len(candidates):,}")
    if not candidates:
        print("\nnothing to do.")
        return 0

    before = {key: dict(li.raw) for key, li in candidates.items()}
    listings = list(candidates.values())
    stats = enrich_ustaxdata_multiyear_tax(listings)
    print(f"\nenrich_ustaxdata_multiyear_tax: {stats}")

    patches: dict[str, dict] = {}
    for key, li in candidates.items():
        b = before[key]
        raw_patch = {k: li.raw.get(k) for k in _WATCH_KEYS if li.raw.get(k) != b.get(k)}
        if raw_patch:
            patches[key] = {"raw": raw_patch}
    print(f"\npatches staged: {len(patches):,}")

    if args.dry_run:
        print("\nDRY RUN -- nothing written.")
        return 0
    if not patches:
        print("\nnothing to do.")
        return 0

    size_state = board_patch_size_state(docs)
    _allow_large = args.allow_large or os.environ.get(
        "BOARD_PATCH_ALLOW_LARGE", "").strip().lower() in ("1", "true", "yes")
    if not size_state["ok"] and not _allow_large:
        print(f"\nREFUSING: {size_state['reason']}. Re-run with --allow-large.")
        return 1
    if _allow_large:
        os.environ["BOARD_PATCH_ALLOW_LARGE"] = "1"

    with board_lock(REPO, owner="ustaxdata_multiyear_tax_backfill"):
        result = patch_existing_rows(patches, dict(stats), docs_dir=docs)
    print(f"\nwrote board: patched {result['applied']:,}/{len(patches):,} rows "
          f"(existing: {result['existing']:,}, not_found: {result['not_found']:,}, "
          f"duplicate_key_matches: {result['duplicate_key_matches']:,})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
