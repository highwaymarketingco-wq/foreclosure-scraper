#!/usr/bin/env python3
"""One-off/repeatable backfill: run the REAL, unmodified enrichment_greenville_tax.
enrich_greenville_tax() against the ALREADY-PUBLISHED board's historical Greenville SC rows.

WHY THIS EXISTS (2026-11-12). Same shape a research agent confirmed live this session for
gap_matrix's two_year_delinquent/tax_aging_surfaced columns, and the same shape Mecklenburg
(scripts/backfill_mecklenburg_tax.py) and Rowan (scripts/backfill_rowan_multiyear_tax.py, this
script's sibling) already had fixed: enrichment_greenville_tax.py (built 2026-11-05) is wired
into main.py's enrichment chain, writing raw['greenville_tax_history'] (always, on >=1 bill),
raw['tax_owed'] (feeds enrichment_tax_aging.py -> tax_aging_surfaced), and
raw['multi_year_delinquent_tax'] -- but main.py's enrichment tail only ever walks that run's OWN
newly-merged rows, never the historical backlog. Greenville's existing board rows have been
sitting unchecked since the module was built one week ago.

enrich_greenville_tax() is a LIVE per-parcel query against greenvillecounty.org's votaxqry
Property Tax Search (no bulk export). It is already self-bounding (GREENVILLE_TAX_MAX_QUERIES
env, default 1500; GREENVILLE_TAX_MAX_SECONDS wall-clock cap, default 1200s;
GREENVILLE_TAX_CONCURRENCY semaphore, default 3; a consecutive-failure circuit breaker) -- this
script does not change or bypass any of those, it only chooses WHICH rows to hand it
(Greenville's real backlog, not whatever a live run happened to just merge) and chunks repeated
calls into checkpointed board writes so a long backfill survives being re-invoked across
sessions.

BOARD I/O: streamed read-only via board_stream.iter_board_rows() (never load_board()), scoped
to state=="SC" and county=="Greenville" during the stream itself (not after loading everything)
-- this board has 470k+ rows, no reason to build a lightweight Listing for the rest. Writes via
web_artifact.patch_existing_rows() with the same dedupe_key()-collision guard every sibling
backfill in this project uses.

    GREENVILLE_TAX_MAX_QUERIES=500 python scripts/backfill_greenville_tax.py --dry-run
    GREENVILLE_TAX=1 BOARD_PATCH_ALLOW_LARGE=1 python scripts/backfill_greenville_tax.py --rounds 3
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

# enrich_greenville_tax() itself checks _ENABLED (GREENVILLE_TAX) and no-ops if unset -- force
# it on for this standalone backfill regardless of the caller's shell env, same as
# backfill_mecklenburg_tax.py and siblings do for their own feature flags.
os.environ.setdefault("GREENVILLE_TAX", "1")

from foreclosure_scraper.board_stream import iter_board_rows  # noqa: E402
from foreclosure_scraper.enrichment_greenville_tax import (  # noqa: E402
    SOURCE_KEY, enrich_greenville_tax,
)
from foreclosure_scraper.models import Listing  # noqa: E402
from foreclosure_scraper.web_artifact import BoardLockBusy, board_lock, patch_existing_rows  # noqa: E402

_LIGHT_FIELDS = ("state", "county", "parcel_id", "street_address", "zip_code",
                  "case_number", "source_url", "listing_type", "source", "raw")
# tax_owed/multi_year_delinquent_tax are shared keys several county modules write to (not
# exported as named constants from this module) -- same literal-string convention
# enrichment_greenville_tax.py's own docstring uses to describe them.
_WATCH_KEYS = (SOURCE_KEY, "tax_owed", "multi_year_delinquent_tax")


def _dedupe_key(li) -> Optional[str]:
    try:
        return li.dedupe_key()
    except Exception:  # noqa: BLE001 - a row too malformed to key is simply skipped
        return None


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--rounds", type=int, default=1,
                     help="how many times to call enrich_greenville_tax() in this invocation "
                          "(each round is its own MAX_QUERIES/MAX_SECONDS-capped pass over the "
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
        if (rec.get("state") or "").strip().upper() != "SC":
            continue
        if (rec.get("county") or "").replace(" County", "").strip() != "Greenville":
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

    print(f"Greenville/SC rows on board: {len(board):,}")

    total_stats: dict = {}
    for rnd in range(args.rounds):
        stats = asyncio.run(enrich_greenville_tax(board))
        print(f"  round {rnd + 1}/{args.rounds}: {stats}")
        for k, v in stats.items():
            total_stats[k] = total_stats.get(k, 0) + v
        if stats.get("targets", 0) == 0:
            print("  no more eligible rows -- backlog exhausted for this invocation")
            break

    print(f"\ncumulative this invocation: {total_stats}")

    if args.dry_run:
        print("\n--dry-run: nothing written (enrich_greenville_tax() still ran live "
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
            REPO, owner="backfill_greenville_tax", wait=3600, poll=10)
        try:
            with lock:
                stats = patch_existing_rows(
                    patches, {"backfill_greenville_tax": f"n={len(patches)}"}, docs_dir=docs)
        except BoardLockBusy as exc:
            print(f"{exc} -- refusing to write ({len(patches):,} patches from this "
                  f"invocation's live queries are lost; re-run to redo them and retry).")
            return 1
        print(f"patch_existing_rows: {stats}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
