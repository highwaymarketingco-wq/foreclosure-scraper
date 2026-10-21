#!/usr/bin/env python3
"""One-time backfill: run enrichment_gaston_multiyear_tax.py's existing, already-wired
enrich_with_gaston_multiyear_tax() against the full backlog of Gaston NC rows it's never
checked (26,620 applicable, 0 checked per docs/gap_matrix/low_yield_queue.md's own top entry --
the single biggest built-but-low-yield cell in the whole gap list). The module and its live
DevNetWedge per-parcel read were already live-verified 2026-10-18; nothing new to build here,
just run it at volume via its own internal batching (MAX_ROWS=300/call default).

Same shape as scripts/backfill_cabarrus_multiyear_tax.py: enrich_with_gaston_multiyear_tax()
does its OWN internal capping (GASTON_MYDT_MAX) and budget (GASTON_MYDT_BUDGET_S), so this
script's batch loop just calls it repeatedly against the shrinking "not yet checked" set.

LOCK LESSON (cost real time multiple times tonight): lock wraps ONLY the final write, never
candidate-collection or the live-fetch batches, with wait=600/poll=10.

    python scripts/backfill_gaston_multiyear_tax.py --dry-run --max-batches 1
    BOARD_PATCH_ALLOW_LARGE=1 python scripts/backfill_gaston_multiyear_tax.py --max-batches 10
"""
from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "src"))

from foreclosure_scraper.board_stream import iter_board_rows  # noqa: E402
from foreclosure_scraper.enrichment_gaston_multiyear_tax import (  # noqa: E402
    CHECKED_KEY, RAW_KEY, enrich_with_gaston_multiyear_tax,
)
from foreclosure_scraper.models import Listing  # noqa: E402
from foreclosure_scraper.web_artifact import (  # noqa: E402
    _APPEND_SIG_FIELDS, board_lock, board_patch_size_state, patch_existing_rows,
)

_IS_GASTON = lambda rec: (
    str(rec.get("county") or "").replace(" County", "").strip().lower() == "gaston"
    and str(rec.get("state") or "").upper() == "NC"
)


def _candidates(docs_dir: Path) -> list[tuple[str, Listing]]:
    out = []
    for rec in iter_board_rows(docs_dir / "listings.json.gz"):
        if not _IS_GASTON(rec):
            continue
        raw = rec.get("raw") if isinstance(rec.get("raw"), dict) else {}
        if RAW_KEY in raw or CHECKED_KEY in raw:
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
    ap.add_argument("--max-batches", type=int, default=10,
                    help="Batches of up to 300 rows this invocation will run (default 10 = "
                         "3,000 rows -- a real, measured slice of the 26,620-row backlog, not "
                         "all of it in one go). Re-run with a higher value, or run again, to "
                         "cover more.")
    args = ap.parse_args()

    docs_dir = REPO / "docs"
    if not args.dry_run:
        size_state = board_patch_size_state(docs_dir)
        if not size_state["ok"] and not args.allow_large:
            print(f"REFUSING: {size_state['reason']}. Re-run with --allow-large.")
            return 1
        if args.allow_large:
            import os
            os.environ["BOARD_PATCH_ALLOW_LARGE"] = "1"

    all_patches: dict[str, dict] = {}
    seen_keys: set[str] = set()
    qualified = 0
    checked = 0

    for batch in range(1, args.max_batches + 1):
        cands = [(k, li) for k, li in _candidates(docs_dir) if k not in seen_keys]
        if not cands:
            print(f"batch {batch}: nothing left eligible, stopping early")
            break
        print(f"\n=== Gaston NC batch {batch}: {len(cands)} remaining eligible ===")
        listings = [li for _, li in cands]
        stats = asyncio.run(enrich_with_gaston_multiyear_tax(listings))
        print(f"  {stats}")
        for key, li in cands:
            seen_keys.add(key)
            if RAW_KEY in li.raw or CHECKED_KEY in li.raw:
                checked += 1
                if RAW_KEY in li.raw:
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

    with board_lock(REPO, owner="gaston_mydt_backfill", wait=600, poll=10):
        stats = patch_existing_rows(all_patches, {"gaston_mydt_backfill": len(all_patches)},
                                     docs_dir=docs_dir)
        print("patch_existing_rows:", stats)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
