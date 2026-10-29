#!/usr/bin/env python3
"""One-time backfill: run enrichment_pender_multiyear_tax.py's live Munis walk against every
eligible Pender NC board row and land the result. CONCURRENCY stays 1 (tax_lien_munis's shared
per-portal session -- see that module's own docstring); PENDER_MYDT_MAX/PENDER_MYDT_BUDGET_S
are overridden via env for one larger pass than a single normal pipeline run would do.

Usage:
    PENDER_MYDT_MAX=2000 PENDER_MYDT_BUDGET_S=10800 python scripts/backfill_pender_multiyear_tax.py --dry-run
    PENDER_MYDT_MAX=2000 PENDER_MYDT_BUDGET_S=10800 python scripts/backfill_pender_multiyear_tax.py --allow-large
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
from foreclosure_scraper.enrichment_pender_multiyear_tax import (  # noqa: E402
    enrich_with_pender_multiyear_tax, MYDT_KEY, TYD_KEY, CHECKED_KEY,
)
from foreclosure_scraper.models import Listing  # noqa: E402
from foreclosure_scraper.web_artifact import (  # noqa: E402
    _APPEND_SIG_FIELDS, board_lock, board_patch_size_state, patch_existing_rows,
)

_LIGHT_FIELDS = _APPEND_SIG_FIELDS + ("raw", "state", "county", "parcel_id")
_WATCH_KEYS = (MYDT_KEY, TYD_KEY, CHECKED_KEY)

#: 2026-10-29, run 1 of this backfill (658 rows): tax_lien_munis.search() treated a real,
#: legitimate single-bill-record parcel as a hard failure, tripped the circuit breaker, and
#: left 602 rows wrongly sentineled "portal_unhealthy" (plus 4 "fetch_failed:ValueError" from
#: the same root cause, caught before the breaker tripped) -- false negatives from a bug now
#: fixed (commit 04b1efc), not genuine answers. _pender_mydt_checked's own idempotency would
#: otherwise skip them forever. "parcel_not_found" is a real, unrelated answer and is left
#: alone -- never re-cleared by this prefix match.
_RETRY_SENTINEL_PREFIXES = ("portal_unhealthy", "fetch_failed:ValueError")


def _light(rec: dict) -> Listing:
    return Listing.model_construct(**{k: rec.get(k) for k in _LIGHT_FIELDS})


def _collect_candidates(docs: Path) -> tuple[dict[str, Listing], dict[str, dict]]:
    """Returns (candidates, before) -- `before[key]` is each row's raw dict AS READ FROM THE
    BOARD, captured BEFORE this function clears any false-negative CHECKED_KEY sentinel.

    2026-10-29, run 2: capturing `before` AFTER the clear (as run 1's script did) meant a row
    that is retried and then SUCCEEDS shows li.raw[CHECKED_KEY] == before[key][CHECKED_KEY] ==
    absent on BOTH sides -- a false "no diff" that silently drops the clear from the patch,
    leaving the OLD failure sentinel on the board forever even though the real
    two_year_delinquent/multi_year_delinquent_tax block landed correctly (confirmed: all 550
    rows left showing a stale sentinel after that run also carry real, freshly-sourced tax
    data -- no data was lost, only this diagnostic field). Capturing `before` from the
    UNMODIFIED board row, before the clear, makes the clear itself a real, detectable diff."""
    cands: dict[str, Listing] = {}
    before: dict[str, dict] = {}
    retried = 0
    for rec in iter_board_rows(docs / "listings.json.gz"):
        if (rec.get("state") or "").strip().upper() != "NC":
            continue
        if (rec.get("county") or "").replace(" County", "").strip().lower() != "pender":
            continue
        if not (rec.get("parcel_id") or "").strip():
            continue
        li = _light(rec)
        try:
            key = li.dedupe_key()
        except Exception:  # noqa: BLE001
            continue
        before[key] = dict(li.raw) if isinstance(li.raw, dict) else {}
        if isinstance(li.raw, dict):
            sentinel = li.raw.get(CHECKED_KEY)
            if isinstance(sentinel, str) and sentinel.startswith(_RETRY_SENTINEL_PREFIXES):
                li.raw = {k: v for k, v in li.raw.items() if k != CHECKED_KEY}
                retried += 1
        cands[key] = li
    print(f"cleared {retried:,} false-negative _pender_mydt_checked sentinels for retry")
    return cands, before


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--allow-large", action="store_true")
    args = ap.parse_args()

    docs = REPO / "docs"
    candidates, before = _collect_candidates(docs)
    print(f"Pender NC candidates with a parcel_id: {len(candidates):,}")
    if not candidates:
        print("\nnothing to do.")
        return 0

    listings = list(candidates.values())
    stats = asyncio.run(enrich_with_pender_multiyear_tax(listings))
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

    with board_lock(REPO, owner="pender_mydt_backfill"):
        result = patch_existing_rows(patches, {"qualified": qualified}, docs_dir=docs)
    print(f"\nwrote board: patched {result['applied']:,}/{len(patches):,} rows "
          f"(existing: {result['existing']:,}, not_found: {result['not_found']:,}, "
          f"duplicate_key_matches: {result['duplicate_key_matches']:,})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
