#!/usr/bin/env python3
"""One-time backfill: run enrichment_alamance_tax_search.py's live Spatialest-tax-tenant
search against every eligible Alamance NC board row and land the result. ALAMANCE_TAX_MAX
is overridden via env for one larger pass than a single normal pipeline run's default (300).

Built 2026-10-28, wired into main.py, but never backfilled onto the board's existing 2,858
Alamance rows (gap_matrix still showed sourced-not-built as of 2026-10-29's fresh run) --
this is the backfill that closes that gap.

`before` is captured from the raw board row BEFORE any Listing construction/mutation --
see scripts/backfill_pender_multiyear_tax.py's own docstring for why this ordering matters
(a before-snapshot taken after an in-memory sentinel clear can hide a real change forever).
This module has no retry-sentinel to clear, but the same discipline is kept here regardless.

Usage:
    ALAMANCE_TAX_MAX=3000 python scripts/backfill_alamance_tax.py --dry-run
    ALAMANCE_TAX_MAX=3000 python scripts/backfill_alamance_tax.py --allow-large
"""
from __future__ import annotations

import argparse
import asyncio
import os
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "src"))

from foreclosure_scraper.board_stream import iter_board_rows  # noqa: E402
from foreclosure_scraper.enrichment_alamance_tax_search import (  # noqa: E402
    enrich_alamance_tax, RAW_KEY, MYDT_KEY, TWO_YEAR_KEY,
)
from foreclosure_scraper.models import Listing  # noqa: E402
from foreclosure_scraper.web_artifact import (  # noqa: E402
    _APPEND_SIG_FIELDS, board_lock, board_patch_size_state, patch_existing_rows,
)

_LIGHT_FIELDS = _APPEND_SIG_FIELDS + ("raw", "state", "county", "owner_name", "street_address")
_WATCH_KEYS = (RAW_KEY, MYDT_KEY, TWO_YEAR_KEY)


def _light(rec: dict) -> Listing:
    return Listing.model_construct(**{k: rec.get(k) for k in _LIGHT_FIELDS})


def _collect_candidates(docs: Path) -> tuple[dict[str, Listing], dict[str, dict]]:
    """Returns (candidates, before) -- `before[key]` is each row's raw dict exactly as read
    off the board, captured before any Listing is constructed or mutated."""
    cands: dict[str, Listing] = {}
    before: dict[str, dict] = {}
    for rec in iter_board_rows(docs / "listings.json.gz"):
        if (rec.get("state") or "").strip().upper() != "NC":
            continue
        if (rec.get("county") or "").replace(" County", "").strip().lower() != "alamance":
            continue
        if not (rec.get("owner_name") or "").strip():
            continue
        raw_before = rec.get("raw")
        if isinstance(raw_before, dict) and isinstance(raw_before.get(RAW_KEY), dict):
            continue  # already done -- never a candidate at all
        li = _light(rec)
        try:
            key = li.dedupe_key()
        except Exception:  # noqa: BLE001
            continue
        before[key] = dict(raw_before) if isinstance(raw_before, dict) else {}
        cands[key] = li
    return cands, before


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--allow-large", action="store_true")
    args = ap.parse_args()

    docs = REPO / "docs"
    candidates, before = _collect_candidates(docs)
    print(f"Alamance NC candidates with an owner_name, not already done: {len(candidates):,}")
    if not candidates:
        print("\nnothing to do.")
        return 0

    listings = list(candidates.values())
    stats = asyncio.run(enrich_alamance_tax(listings))
    print(f"\nstats: {stats}")

    patches: dict[str, dict] = {}
    qualified = 0
    for key, li in candidates.items():
        b = before[key]
        raw_patch = {k: li.raw.get(k) for k in _WATCH_KEYS
                    if isinstance(li.raw, dict) and li.raw.get(k) != b.get(k)}
        if raw_patch:
            patches[key] = {"raw": raw_patch}
            if MYDT_KEY in raw_patch:
                qualified += 1
    print(f"\npatches staged: {len(patches):,} (of which {qualified:,} carry a real "
          f"multi_year_delinquent_tax block)")

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

    with board_lock(REPO, owner="alamance_tax_backfill"):
        result = patch_existing_rows(patches, {"qualified": qualified}, docs_dir=docs)
    print(f"\nwrote board: patched {result['applied']:,}/{len(patches):,} rows "
          f"(existing: {result['existing']:,}, not_found: {result['not_found']:,}, "
          f"duplicate_key_matches: {result['duplicate_key_matches']:,})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
