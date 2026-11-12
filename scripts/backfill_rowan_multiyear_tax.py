#!/usr/bin/env python3
"""One-off/repeatable backfill: run the REAL, unmodified enrichment_rowan_multiyear_tax.
enrich_rowan_multiyear_tax() against the ALREADY-PUBLISHED board's historical Rowan rows.

WHY THIS EXISTS (2026-11-12). Same shape a research agent confirmed live this session for
gap_matrix's two_year_delinquent/tax_aging_surfaced columns: enrichment_rowan_multiyear_tax.py
(built 2026-11-05) is already wired into main.py's enrichment chain, stamping
raw['two_year_delinquent'] and raw['multi_year_delinquent_tax'] -- but main.py's enrichment
tail only ever walks that run's OWN newly-merged rows, never the historical backlog, exactly
like Mecklenburg's case (scripts/backfill_mecklenburg_tax.py, which this script mirrors).
Mecklenburg got a dedicated backfill on 2026-11-11; Rowan (and Greenville, see
scripts/backfill_greenville_tax.py) did not, so their ~4,594 (Rowan, as last measured)
historical rows have been sitting unchecked since the module was built one week ago.

enrich_rowan_multiyear_tax() is a LIVE per-parcel query against tax.rowancountync.gov (no bulk
export). It is already self-bounding (ROWAN_MYDT_MAX env, default 300 per call; ROWAN_MYDT_
BUDGET_S wall-clock cap, default 600s; ROWAN_MYDT_CONCURRENCY semaphore, default 3; a
consecutive-failure circuit breaker) -- this script does not change or bypass any of those, it
only chooses WHICH rows to hand it (Rowan's real backlog, not whatever a live run happened to
just merge) and chunks repeated calls into checkpointed board writes so a long backfill
survives being re-invoked across sessions.

BOARD I/O: streamed read-only via board_stream.iter_board_rows() (never load_board()), scoped
to state=="NC" and county=="Rowan" during the stream itself (not after loading everything) --
this board has 470k+ rows, no reason to build a lightweight Listing for the rest. Writes via
web_artifact.patch_existing_rows() with the same dedupe_key()-collision guard every sibling
backfill in this project uses.

    ROWAN_MYDT_MAX=300 python scripts/backfill_rowan_multiyear_tax.py --dry-run
    FORECLOSURE_ROWAN_MULTIYEAR_TAX=1 BOARD_PATCH_ALLOW_LARGE=1 \
        python scripts/backfill_rowan_multiyear_tax.py --rounds 3
"""
from __future__ import annotations

import argparse
import asyncio
import contextlib
import os
import sys
from pathlib import Path
from typing import Optional

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "src"))

# enrich_rowan_multiyear_tax() itself checks _ENABLED (FORECLOSURE_ROWAN_MULTIYEAR_TAX) and
# no-ops if unset -- force it on for this standalone backfill regardless of the caller's shell
# env, same as backfill_mecklenburg_tax.py and siblings do for their own feature flags.
os.environ.setdefault("FORECLOSURE_ROWAN_MULTIYEAR_TAX", "1")

from foreclosure_scraper.board_stream import iter_board_rows  # noqa: E402
from foreclosure_scraper.enrichment_rowan_multiyear_tax import (  # noqa: E402
    MULTIYEAR_KEY, TWO_YEAR_KEY, enrich_rowan_multiyear_tax,
)
from foreclosure_scraper.models import Listing  # noqa: E402
from foreclosure_scraper.web_artifact import BoardLockBusy, board_lock, patch_existing_rows  # noqa: E402

_LIGHT_FIELDS = ("state", "county", "parcel_id", "street_address", "zip_code",
                  "case_number", "source_url", "listing_type", "source", "raw")
_WATCH_KEYS = (TWO_YEAR_KEY, MULTIYEAR_KEY)


def _dedupe_key(li) -> Optional[str]:
    try:
        return li.dedupe_key()
    except Exception:  # noqa: BLE001 - a row too malformed to key is simply skipped
        return None


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--rounds", type=int, default=1,
                     help="how many times to call enrich_rowan_multiyear_tax() in this "
                          "invocation (each round is its own MAX/BUDGET_S-capped pass over the "
                          "still-eligible rows; re-invoke the whole script across sessions to "
                          "keep grinding through the backlog)")
    args = ap.parse_args()

    docs = REPO / "docs"

    # BOARD I/O only happens at the final write below -- see backfill_mecklenburg_tax.py's own
    # comment for why the lock is narrowed to just the write, not the whole --rounds loop.
    board: list[Listing] = []
    keys: list[Optional[str]] = []
    before: list[dict] = []
    for rec in iter_board_rows(docs / "listings.json.gz"):
        if (rec.get("state") or "").strip().upper() != "NC":
            continue
        if (rec.get("county") or "").strip() != "Rowan":
            continue
        li = Listing.model_construct(**{k: rec.get(k) for k in _LIGHT_FIELDS})
        board.append(li)
        keys.append(_dedupe_key(li))
        raw = li.raw if isinstance(li.raw, dict) else {}
        before.append({k: raw.get(k) for k in _WATCH_KEYS})

    key_counts: dict[str, int] = {}
    for k in keys:
        if k is not None:
            key_counts[k] = key_counts.get(k, 0) + 1

    print(f"Rowan/NC rows on board: {len(board):,}")

    total_stats: dict = {}
    for rnd in range(args.rounds):
        stats = asyncio.run(enrich_rowan_multiyear_tax(board))
        print(f"  round {rnd + 1}/{args.rounds}: {stats}")
        for k, v in stats.items():
            total_stats[k] = total_stats.get(k, 0) + v
        if stats.get("eligible", 0) == 0:
            print("  no more eligible rows -- backlog exhausted for this invocation")
            break

    print(f"\ncumulative this invocation: {total_stats}")

    if args.dry_run:
        print("\n--dry-run: nothing written (enrich_rowan_multiyear_tax() still ran live "
              "network queries above -- there is no network-free dry-run path for this "
              "module; --dry-run here only means the board write is skipped)")
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
        lock = contextlib.nullcontext() if args.dry_run else board_lock(
            REPO, owner="backfill_rowan_multiyear_tax", wait=3600, poll=10)
        try:
            with lock:
                stats = patch_existing_rows(
                    patches, {"backfill_rowan_multiyear_tax": f"n={len(patches)}"}, docs_dir=docs)
        except BoardLockBusy as exc:
            print(f"{exc} -- refusing to write ({len(patches):,} patches from this "
                  f"invocation's live queries are lost; re-run to redo them and retry).")
            return 1
        print(f"patch_existing_rows: {stats}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
