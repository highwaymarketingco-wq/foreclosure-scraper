#!/usr/bin/env python3
"""Backfill: fetch each eligible NC Watauga parcel's real-estate tax bill history LIVE from
wataugacounty.org (enrichment_watauga_tax_search.py) and patch raw['watauga_delinquent_tax'] +
raw['multi_year_delinquent_tax'] + raw['two_year_delinquent'] onto the board.

Unlike the ustaxdata/Gaston/Nash multiyear restatement backfills, this one IS a live network
call per row (one GET for fresh VIEWSTATE tokens + one POST per parcel, ~380 NC Watauga rows
carry a usable parcel_id) -- not a one-shot pure-compute pass. --max-rows caps a single
invocation (self-looping wrapper pattern already used by every other continuous backfill here);
a small per-row delay keeps this a light, polite load on a small county's own web server.

Usage:
    python scripts/backfill_watauga_tax_search.py --dry-run --max-rows 10
    python scripts/backfill_watauga_tax_search.py --max-rows 50 --allow-large
"""
from __future__ import annotations

import argparse
import os
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "src"))

from foreclosure_scraper.board_stream import iter_board_rows  # noqa: E402
from foreclosure_scraper.enrichment_watauga_tax_search import (  # noqa: E402
    RAW_KEY, SRC_KEY, TWO_YEAR_KEY, _eligible, enrich_watauga_tax_search,
)
from foreclosure_scraper.models import Listing  # noqa: E402
from foreclosure_scraper.web_artifact import (  # noqa: E402
    BoardChangedSinceLoad, BoardLockBusy, _APPEND_SIG_FIELDS, board_lock,
    board_patch_size_state, patch_existing_rows,
)

_LIGHT_FIELDS = _APPEND_SIG_FIELDS + ("raw", "state", "county", "parcel_id")
_WATCH_KEYS = (SRC_KEY, RAW_KEY, TWO_YEAR_KEY)
_PAGE_DELAY_S = 1.0  # between parcels -- a light, polite pace for a small county's own server


def _light(rec: dict) -> Listing:
    return Listing.model_construct(**{k: rec.get(k) for k in _LIGHT_FIELDS})


def _collect_candidates(docs: Path, max_rows: int) -> tuple[dict[str, Listing], dict[str, dict]]:
    """Returns (candidates, before), capped at max_rows -- see enrichment_watauga_tax_search.
    _eligible() for the exact gate (NC, Watauga, board-shaped parcel_id, not already fetched)."""
    cands: dict[str, Listing] = {}
    before: dict[str, dict] = {}
    for rec in iter_board_rows(docs / "listings.json.gz"):
        if len(cands) >= max_rows:
            break
        li = _light(rec)
        if not _eligible(li):
            continue
        try:
            key = li.dedupe_key()
        except Exception:  # noqa: BLE001
            continue
        before[key] = dict(li.raw) if isinstance(li.raw, dict) else {}
        cands[key] = li
    return cands, before


class _PacedSession:
    """Wraps a curl_cffi Session so every GET/POST this backfill makes sleeps first -- the
    bare module (enrich_watauga_tax_search) stays pace-agnostic for its own unit tests, which
    use a fake session with no delay at all."""

    def __init__(self, inner):
        self._inner = inner

    def get(self, *a, **k):
        time.sleep(_PAGE_DELAY_S)
        return self._inner.get(*a, **k)

    def post(self, *a, **k):
        time.sleep(_PAGE_DELAY_S)
        return self._inner.post(*a, **k)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--allow-large", action="store_true")
    ap.add_argument("--max-rows", type=int, default=50)
    args = ap.parse_args()

    docs = REPO / "docs"
    candidates, before = _collect_candidates(docs, args.max_rows)
    print(f"NC Watauga candidates with a usable parcel_id, not yet fetched: {len(candidates):,} "
          f"(this invocation capped at --max-rows {args.max_rows:,})")
    if not candidates:
        print("\nnothing to do.")
        return 0

    from curl_cffi import requests as creq
    listings = list(candidates.values())
    stats = enrich_watauga_tax_search(listings, session=_PacedSession(creq.Session(impersonate="chrome")))
    print(f"\nstats: {stats}")

    patches: dict[str, dict] = {}
    qualified = 0
    for key, li in candidates.items():
        b = before[key]
        raw_patch = {k: li.raw.get(k) for k in _WATCH_KEYS
                    if isinstance(li.raw, dict) and li.raw.get(k) != b.get(k)}
        if raw_patch:
            patches[key] = {"raw": raw_patch}
            if RAW_KEY in raw_patch:
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

    # Retry pattern matches backfill_deed_chain_v2.py's own (board_lock's wait=/poll= already
    # retries internally up to 600s; the outer _ATTEMPTS loop additionally covers
    # BoardChangedSinceLoad, and gives real headroom beyond one 600s window). Added 2026-11-28
    # after a live run found a genuine race: an external shell loop saw the lock free, then by
    # the time this script finished its ~15 live fetches and reached board_lock() itself, a
    # DIFFERENT process had already grabbed it -- BoardLockBusy with no internal wait threw away
    # every fetch this invocation had just done over the network. wait=600 moves the waiting to
    # the actual point of need instead of a check-then-act race against it.
    _ATTEMPTS = 8
    result = None
    for attempt in range(_ATTEMPTS):
        try:
            with board_lock(REPO, owner="watauga_tax_search_backfill", wait=600, poll=10):
                result = patch_existing_rows(patches, {"qualified": qualified}, docs_dir=docs)
            break
        except (BoardLockBusy, BoardChangedSinceLoad) as exc:
            if attempt == _ATTEMPTS - 1:
                raise
            print(f"  board write contention (attempt {attempt + 1}/{_ATTEMPTS}), retrying: "
                  f"{type(exc).__name__}: {exc}")
    print(f"\nwrote board: patched {result['applied']:,}/{len(patches):,} rows "
          f"(existing: {result['existing']:,}, not_found: {result['not_found']:,}, "
          f"duplicate_key_matches: {result['duplicate_key_matches']:,})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
