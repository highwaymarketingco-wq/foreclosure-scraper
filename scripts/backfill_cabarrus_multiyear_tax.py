#!/usr/bin/env python3
"""One-time backfill: land Cabarrus NC's new, LIVE multi-year-tax enrichment
(enrichment_cabarrus_multiyear_tax.py, 2026-10-20) onto the already-published board.

Same shape as backfill_catawba_multiyear_tax.py. enrich_with_cabarrus_multiyear_tax() does its
OWN internal capping (CABARRUS_MYDT_MAX, default 300/call) and budget (CABARRUS_MYDT_BUDGET_S),
so this script's batch loop is simpler: call it repeatedly against the shrinking "not yet
checked" set until nothing eligible remains or --max-batches is hit.

BOARD I/O: board_stream.iter_board_rows() once, then patch_existing_rows() under board_lock(),
same discipline as every backfill before this one (never load_board()/write_artifact()).

Usage:
    python scripts/backfill_cabarrus_multiyear_tax.py --dry-run
    python scripts/backfill_cabarrus_multiyear_tax.py --dry-run --max-batches 1
    python scripts/backfill_cabarrus_multiyear_tax.py --allow-large
"""
from __future__ import annotations

import argparse
import asyncio
import contextlib
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "src"))

from foreclosure_scraper.board_stream import iter_board_rows  # noqa: E402
from foreclosure_scraper.enrichment_cabarrus_multiyear_tax import (  # noqa: E402
    CHECKED_KEY, MYDT_KEY, TYD_KEY, enrich_with_cabarrus_multiyear_tax,
)
from foreclosure_scraper.models import Listing  # noqa: E402
from foreclosure_scraper.web_artifact import (  # noqa: E402
    _APPEND_SIG_FIELDS, board_lock, board_patch_size_state, patch_existing_rows,
)

_IS_CABARRUS = lambda rec: (
    str(rec.get("county") or "").strip().lower() == "cabarrus"
    and str(rec.get("state") or "").upper() == "NC"
)


def _candidates(docs_dir: Path) -> list[tuple[str, Listing]]:
    out = []
    for rec in iter_board_rows(docs_dir / "listings.json.gz"):
        if not _IS_CABARRUS(rec):
            continue
        raw = rec.get("raw") if isinstance(rec.get("raw"), dict) else {}
        if TYD_KEY in raw or MYDT_KEY in raw or CHECKED_KEY in raw:
            continue
        if not rec.get("parcel_id"):
            continue
        li = Listing.model_construct(**{k: rec.get(k) for k in _APPEND_SIG_FIELDS if k in rec})
        li.raw = dict(raw)
        out.append((li.dedupe_key(), li))
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--allow-large", action="store_true")
    ap.add_argument("--max-batches", type=int, default=5)
    args = ap.parse_args()

    docs_dir = REPO / "docs"
    if not args.dry_run:
        size_state = board_patch_size_state(docs_dir)
        if not size_state["ok"] and not args.allow_large:
            print(f"REFUSING: {size_state['reason']}. Re-run with --allow-large.")
            return 1

    all_patches: dict[str, dict] = {}
    seen_keys: set[str] = set()
    qualified = 0
    checked = 0

    for batch in range(1, args.max_batches + 1):
        cands = [(k, li) for k, li in _candidates(docs_dir) if k not in seen_keys]
        if not cands:
            print(f"batch {batch}: nothing left eligible, stopping early")
            break
        print(f"\n=== Cabarrus NC batch {batch}: {len(cands)} remaining eligible ===")
        listings = [li for _, li in cands]
        stats = asyncio.run(enrich_with_cabarrus_multiyear_tax(listings))
        print(f"  {stats}")
        for key, li in cands:
            seen_keys.add(key)
            if TYD_KEY in li.raw or MYDT_KEY in li.raw or CHECKED_KEY in li.raw:
                checked += 1
                if MYDT_KEY in li.raw:
                    qualified += 1
                all_patches[key] = {"raw": li.raw}
        if stats.get("attempted", 0) == 0:
            break

    print(f"\npatches staged: {len(all_patches)}")
    print(f"    qualified (multi_year_delinquent_tax written): {qualified}")
    print(f"    checked, did not qualify:                      {checked - qualified}")

    if args.dry_run:
        print("\nDRY RUN -- nothing written.")
        return 0

    if not all_patches:
        print("nothing to write.")
        return 0

    with board_lock(REPO, owner="cabarrus_mydt_backfill"):
        stats = patch_existing_rows(all_patches, {"cabarrus_mydt_backfill": len(all_patches)},
                                     docs_dir=docs_dir)
        print("patch_existing_rows:", stats)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
