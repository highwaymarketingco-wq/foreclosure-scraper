#!/usr/bin/env python3
"""One-off/repeatable backfill: run the REAL, unmodified enrichment_mecklenburg_tax.
enrich_mecklenburg_tax() against the ALREADY-PUBLISHED board's historical Mecklenburg rows.

WHY THIS EXISTS (2026-11-11, Mecklenburg gap-sweep). enrichment_mecklenburg_tax.py was built
2026-11-05 and wired into main.py's enrichment chain, but shipped behind FORECLOSURE_MECKLENBURG_
MYDT (default off) "since nothing has wired this into main.py yet" -- that reason is gone now
that it's called, and scripts/run_local.sh now exports it on by default (commit ccd012f). BUT
un-gating it only changes what a FUTURE main.py run does: like every other enrichment this
project has found to have this exact shape tonight (tax_aging_surfaced, tax_owed, gis_attrs,
sos_dissolution), main.py's run_enrich_tail only ever walks that run's OWN newly-merged rows,
never the historical backlog -- so the ~39,861 Mecklenburg rows already on the board would sit
unchecked forever without a dedicated pass like this one.

enrich_mecklenburg_tax() is a LIVE per-parcel query against taxbill.co.mecklenburg.nc.us (no
bulk export) -- NOT cheap/offline like tax_owed's cross-reference pass. It is already
self-bounding (MAX_ROWS env, default 300 per call; BUDGET_S wall-clock cap, default 600s;
CONCURRENCY semaphore, default 4; a consecutive-failure circuit breaker) -- this script does
not change or bypass any of those, it only chooses WHICH rows to hand it (Mecklenburg's real
backlog, not whatever a live run happened to just merge) and chunks repeated calls into
checkpointed board writes so a long backfill survives being re-invoked across sessions.

BOARD I/O: streamed read-only via board_stream.iter_board_rows() (never load_board()), scoped
to state=="NC" and county=="Mecklenburg" during the stream itself (not after loading everything)
-- this board has 477k+ rows, no reason to build a lightweight Listing for the other ~438k.
Writes via web_artifact.patch_existing_rows() with the same dedupe_key()-collision guard every
sibling backfill in this project uses (a key shared by >1 distinct row is dropped, counted, never
guessed at).

    MECKLENBURG_MYDT_MAX=300 python scripts/backfill_mecklenburg_tax.py --dry-run
    FORECLOSURE_MECKLENBURG_MYDT=1 MECKLENBURG_MYDT_MAX=300 \
        BOARD_PATCH_ALLOW_LARGE=1 python scripts/backfill_mecklenburg_tax.py --rounds 1
"""
from __future__ import annotations

import argparse
import asyncio
import os
import sys
from pathlib import Path
from typing import Optional

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "src"))

# enrich_mecklenburg_tax() itself checks _ENABLED (FORECLOSURE_MECKLENBURG_MYDT) and no-ops if
# unset -- force it on for this standalone backfill regardless of the caller's shell env, same
# as backfill_lincoln_cchs_rod.py and siblings do for their own feature flags.
os.environ.setdefault("FORECLOSURE_MECKLENBURG_MYDT", "1")

from foreclosure_scraper.board_stream import iter_board_rows  # noqa: E402
from foreclosure_scraper.enrichment_mecklenburg_tax import (  # noqa: E402
    CHECKED_KEY, MYDT_KEY, TYD_KEY, enrich_mecklenburg_tax,
)
from foreclosure_scraper.models import Listing  # noqa: E402
from foreclosure_scraper.web_artifact import BoardLockBusy, board_lock, patch_existing_rows  # noqa: E402

_LIGHT_FIELDS = ("state", "county", "parcel_id", "street_address", "zip_code",
                  "case_number", "source_url", "listing_type", "source", "raw")
_WATCH_KEYS = (TYD_KEY, MYDT_KEY, CHECKED_KEY)


def _dedupe_key(li) -> Optional[str]:
    try:
        return li.dedupe_key()
    except Exception:  # noqa: BLE001 - a row too malformed to key is simply skipped
        return None


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--rounds", type=int, default=1,
                     help="how many times to call enrich_mecklenburg_tax() in this invocation "
                          "(each round is its own MAX_ROWS/BUDGET_S-capped pass over the "
                          "still-eligible rows; re-invoke the whole script across sessions to "
                          "keep grinding through the backlog)")
    args = ap.parse_args()

    docs = REPO / "docs"

    # BOARD I/O only happens at the final write below (patch_existing_rows()). Everything
    # from here through the patches diff touches only in-memory Listing objects built by the
    # streamed read -- never the board file -- so none of it needs board_lock() held. Narrowed
    # 2026-11-11: this used to hold the lock across the WHOLE --rounds loop too, which is pure
    # live network I/O against taxbill.co.mecklenburg.nc.us (up to MECKLENBURG_MYDT_BUDGET_S
    # seconds per round) with zero board-file interaction of its own -- an 11+ min hold was
    # observed in production, starving backfill_gis_attrs_boardwide.py/backfill_mecklenburg_
    # gis_attrs.py of the same lock for just as long. patch_existing_rows() independently
    # refuses to write without the lock held (require_board_lock()), so this narrowing removes
    # no correctness guarantee -- the write itself is unaffected by when the lock is acquired.
    board: list[Listing] = []
    keys: list[Optional[str]] = []
    before: list[dict] = []
    for rec in iter_board_rows(docs / "listings.json.gz"):
        if (rec.get("state") or "").strip().upper() != "NC":
            continue
        if (rec.get("county") or "").strip() != "Mecklenburg":
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

    print(f"Mecklenburg/NC rows on board: {len(board):,}")

    # FIX 2026-11-13: used to accumulate all --rounds worth of changes and write ONCE at the
    # very end. Live-observed consequence: a full invocation (3 rounds x 300 real parcels,
    # ~830 real two_year_written hits, the table-index parser bug now fixed) ran its entire
    # ~30 minutes of live network work successfully, then lost ALL of it -- the single write
    # attempt waited the full 3600s board_lock budget and still never caught a free window,
    # because two OTHER wrappers (deed_chain_v2, then gis_attrs_boardwide) kept passing the
    # lock between themselves the whole time. One lock-contention loss used to cost an entire
    # invocation's yield; now it costs at most one round's. Flushing per round doesn't touch
    # the 2026-11-11 fix above (the lock still wraps only the write, never the live fetch loop).
    total_stats: dict = {}
    total_applied = 0
    total_lost = 0
    for rnd in range(args.rounds):
        stats = asyncio.run(enrich_mecklenburg_tax(board))
        print(f"  round {rnd + 1}/{args.rounds}: {stats}")
        for k, v in stats.items():
            total_stats[k] = total_stats.get(k, 0) + v

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

        print(f"  round {rnd + 1} patches staged: {len(patches):,} "
              f"(dropped as dedupe_key collisions: {collisions:,})")

        if patches and not args.dry_run:
            # THE LOCK, narrowed to just this write -- see the 2026-11-11 comment above.
            # patch_existing_rows() self-enforces require_board_lock() regardless, so this is
            # belt-and-suspenders, not the only thing standing between this script and a
            # lock-less write.
            try:
                with board_lock(REPO, owner="backfill_mecklenburg_tax", wait=3600, poll=10):
                    wstats = patch_existing_rows(
                        patches, {"backfill_mecklenburg_tax": f"round={rnd + 1} n={len(patches)}"},
                        docs_dir=docs)
                print(f"  round {rnd + 1} patch_existing_rows: {wstats}")
                total_applied += wstats.get("applied", 0)
            except BoardLockBusy as exc:
                print(f"{exc} -- refusing to write ({len(patches):,} patches from round "
                      f"{rnd + 1} are lost; re-run to redo them).")
                total_lost += len(patches)

        # Re-snapshot "before" to this round's current state so round N+1's diff only covers
        # what round N+1 itself changes -- not what this round already wrote (or tried to).
        for i, li in enumerate(board):
            raw = li.raw if isinstance(li.raw, dict) else {}
            before[i] = {k: raw.get(k) for k in _WATCH_KEYS}

        if stats.get("eligible", 0) == 0:
            print("  no more eligible rows -- backlog exhausted for this invocation")
            break

    print(f"\ncumulative this invocation: {total_stats}")
    print(f"total applied across all rounds: {total_applied:,}; "
          f"total lost to lock contention: {total_lost:,}")

    if args.dry_run:
        print("\n--dry-run: nothing written (enrich_mecklenburg_tax() still ran live "
              "network queries above -- there is no network-free dry-run path for this "
              "module; --dry-run here only means the board write is skipped)")
        return 0

    return 1 if total_lost else 0


if __name__ == "__main__":
    raise SystemExit(main())
