#!/usr/bin/env python3
"""One-time backfill: land Berkeley NC's three new, pure-compute enrichments
(enrichment_berkeley_vacant_lot.py, _rollback_exposure.py, _multiyear_tax.py --
all 2026-10-20) onto the already-published board.

All three are synchronous, no-network derivations from raw['berkeley_paystar_tax']
data already refreshed by ingest_berkeley_paystar_tax.py's re-scrape (commit
14aacaf1) -- no live fetch here, this is pure in-memory compute, so there is
no batching/budget concern the way Catawba/Cabarrus's LIVE per-parcel fetches had.

BOARD I/O: board_stream.iter_board_rows() once, then ONE patch_existing_rows()
call under board_lock() -- never load_board()/write_artifact().

Usage:
    python scripts/backfill_berkeley_tax_signals.py --dry-run
    python scripts/backfill_berkeley_tax_signals.py --allow-large
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "src"))

from foreclosure_scraper.board_stream import iter_board_rows  # noqa: E402
from foreclosure_scraper.enrichment_berkeley_multiyear_tax import enrich_berkeley_multiyear_tax  # noqa: E402
from foreclosure_scraper.enrichment_berkeley_rollback_exposure import (  # noqa: E402
    enrich_berkeley_rollback_exposure,
)
from foreclosure_scraper.enrichment_berkeley_vacant_lot import enrich_berkeley_vacant_lot  # noqa: E402
from foreclosure_scraper.models import Listing  # noqa: E402
from foreclosure_scraper.web_artifact import (  # noqa: E402
    _APPEND_SIG_FIELDS, board_lock, board_patch_size_state, patch_existing_rows,
)

_IS_BERKELEY = lambda rec: (
    str(rec.get("county") or "").strip().lower() == "berkeley" and str(rec.get("state") or "").upper() == "SC"
)


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

    candidates: dict[str, Listing] = {}
    before_raw: dict[str, dict] = {}
    total_berkeley = 0
    for rec in iter_board_rows(docs_dir / "listings.json.gz"):
        if not _IS_BERKELEY(rec):
            continue
        total_berkeley += 1
        li = Listing.model_construct(**{k: rec.get(k) for k in _APPEND_SIG_FIELDS if k in rec})
        li.raw = dict(rec.get("raw") or {})
        key = li.dedupe_key()
        candidates[key] = li
        before_raw[key] = dict(li.raw)
    print(f"Berkeley SC rows streamed: {total_berkeley:,}; distinct dedupe_keys: {len(candidates):,}")

    listings = list(candidates.values())
    vl_stats = enrich_berkeley_vacant_lot(listings)
    rb_stats = enrich_berkeley_rollback_exposure(listings)
    mt_stats = enrich_berkeley_multiyear_tax(listings)
    print("vacant_lot:        ", vl_stats)
    print("rollback_exposure: ", rb_stats)
    print("multi_year_tax:    ", mt_stats)

    patches = {key: {"raw": li.raw} for key, li in candidates.items() if li.raw != before_raw[key]}
    print(f"\nrows actually changed, patches staged: {len(patches):,}")

    if args.dry_run:
        print("\nDRY RUN -- nothing written.")
        return 0

    with board_lock(REPO, owner="berkeley_tax_signals_backfill"):
        stats = patch_existing_rows(patches, {"berkeley_tax_signals_backfill": len(patches)},
                                     docs_dir=docs_dir)
        print("patch_existing_rows:", stats)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
