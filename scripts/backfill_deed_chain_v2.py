#!/usr/bin/env python3
"""Run enrich_deed_chain() board-wide using the modern streamed/patch board I/O instead of
scripts/backfill_deed_chain.py's load_board()/write_artifact(). That script's load_board() call
alone was measured live 2026-10-22 at 13.5GB RSS and still climbing after <2 minutes (full
Pydantic validation of 447,664 rows) -- killed before it risked an OOM.

A FIRST attempt here still held every row's full `raw` dict (via lightweight model_construct,
not full validation) in memory at once -- also killed, at 19+ GB RSS and still climbing. The
real cost isn't validation, it's simply holding 447K rows' nested raw dicts simultaneously
(Python object overhead on deeply nested structures is real).

Fixed with a genuine two-pass, bounded-memory design:
  PASS 1 -- stream the board ONCE collecting only (lat, lng) per row (tiny: a list of float
            pairs, no raw data at all) and compute block_binding.shared_points() from that.
            This is the one thing that genuinely needs whole-board context; it's cheap.
  PASS 2 -- stream the board AGAIN in bounded batches (default 20,000 rows). Each batch builds
            light Listings WITH raw, calls enrich_deed_chain(batch, shared_pts=<pass 1's set>)
            (enrichment_deed_chain.py now accepts a precomputed set, added alongside this
            script), patches results, then DISCARDS the batch before the next one. Peak memory
            is bounded by one batch's raw data, not the whole board's.

    python scripts/backfill_deed_chain_v2.py --dry-run
    BOARD_PATCH_ALLOW_LARGE=1 python scripts/backfill_deed_chain_v2.py
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "src"))

# AUTO-RESUME (2026-11-25). Found live via gap_matrix.py: despite the two board_lock retry
# fixes above both confirmed firing-and-succeeding, real board coverage for deed_chain_fetched
# and its 3 dependents had NOT moved AT ALL since the 2026-11-24 baseline (covered=129,900,
# identical digit-for-digit in both runs). Root cause: this script's own --skip-rows flag
# already existed for manual resume, but the standing wrapper
# (for i in $(seq 1 1000); do python3.12 scripts/backfill_deed_chain_v2.py --allow-large; ...)
# never passes it, so EVERY crash-and-relaunch starts pass 2 over at row 0. Every "deed_chain.done"
# line logged this session shows IDENTICAL stamped/cleared counts for the first one or two
# batches -- direct proof the run has never gotten past ~40,000 of 633,730 rows before something
# (lock contention, a future exception type, host load) ends it, no matter how robust a single
# flush() is. This file persists the last successfully-flushed row boundary locally (per host,
# not git-tracked -- logs/ is gitignored) so a relaunch resumes instead of redoing the same
# early rows forever; a full clean finish resets it to 0 so the next natural pass re-scans
# everything (to pick up newly added/changed rows), rather than resuming into "0 rows left"
# forever.
_RESUME_FILE = REPO / "logs" / "deed_chain_v2_resume.json"


def _load_resume_skip() -> int:
    try:
        return max(0, int(json.loads(_RESUME_FILE.read_text())["skip_rows"]))
    except (OSError, ValueError, KeyError, TypeError):
        return 0


def _save_resume_skip(n: int) -> None:
    from datetime import datetime, timezone
    try:
        _RESUME_FILE.parent.mkdir(parents=True, exist_ok=True)
        _RESUME_FILE.write_text(json.dumps(
            {"skip_rows": n, "updated_at": datetime.now(timezone.utc).isoformat()}))
    except OSError:
        pass  # resume is a throughput optimization, never worth failing the run over

from foreclosure_scraper.board_stream import iter_board_rows  # noqa: E402
from foreclosure_scraper.block_binding import FALLBACK_POINT_MIN_ROWS  # noqa: E402
from foreclosure_scraper.enrichment_deed_chain import enrich_deed_chain  # noqa: E402
from foreclosure_scraper.models import Listing  # noqa: E402
from foreclosure_scraper.web_artifact import (  # noqa: E402
    BoardChangedSinceLoad, BoardLockBusy, _APPEND_SIG_FIELDS, board_lock, board_patch_size_state,
    patch_existing_rows,
)

_LIGHT_FIELDS = _APPEND_SIG_FIELDS + ("raw", "latitude", "longitude")


def _point(rec: dict):
    lat, lng = rec.get("latitude"), rec.get("longitude")
    try:
        return (round(float(lat), 5), round(float(lng), 5))
    except (TypeError, ValueError):
        return None


def _compute_shared_points(docs_dir: Path) -> set:
    from collections import Counter
    n: Counter = Counter()
    total = 0
    for rec in iter_board_rows(docs_dir / "listings.json.gz"):
        p = _point(rec)
        if p is not None:
            n[p] += 1
        total += 1
    print(f"pass 1: {total:,} rows scanned for (lat,lng) clustering")
    return {p for p, c in n.items() if c >= FALLBACK_POINT_MIN_ROWS}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--allow-large", action="store_true")
    ap.add_argument("--batch-size", type=int, default=20000)
    ap.add_argument("--skip-rows", type=int, default=None,
                     help="Resume support: skip this many streamed rows before batching. If "
                          "omitted (the normal case -- the standing wrapper never passes this), "
                          "auto-resumes from logs/deed_chain_v2_resume.json, the last row "
                          "boundary this host successfully flushed. Pass 0 explicitly to force "
                          "a full fresh pass, ignoring any saved resume point.")
    args = ap.parse_args()
    skip_rows = args.skip_rows if args.skip_rows is not None else _load_resume_skip()
    if skip_rows:
        print(f"resuming: skipping {skip_rows:,} rows already flushed by a prior run")

    docs_dir = REPO / "docs"
    if not args.dry_run:
        size_state = board_patch_size_state(docs_dir)
        if not size_state["ok"] and not args.allow_large:
            print(f"REFUSING: {size_state['reason']}. Re-run with --allow-large.")
            return 1
        if args.allow_large:
            os.environ["BOARD_PATCH_ALLOW_LARGE"] = "1"

    shared_pts = _compute_shared_points(docs_dir)
    print(f"shared fallback points: {len(shared_pts):,}")

    total_rows = 0
    before_count = 0
    after_count = 0
    cleared_count = 0
    new_count = 0
    total_patched = 0
    batch: list[tuple[str, Listing, bool]] = []

    def flush(batch: list[tuple[str, Listing, bool]]) -> None:
        nonlocal after_count, total_patched, cleared_count, new_count
        if not batch:
            return
        listings = [li for _, li, _ in batch]
        enrich_deed_chain(listings, shared_pts=shared_pts)
        patches = {}
        for key, li, had_before in batch:
            if key is None or not (li.parcel_id or li.street_address
                                    or (li.case_number and li.county)):
                continue
            has_now = isinstance(li.raw, dict) and isinstance(li.raw.get("deed_chain"), dict)
            if has_now:
                after_count += 1
            if has_now and not had_before:
                new_count += 1
                patches[key] = {"raw": {"deed_chain": li.raw["deed_chain"]}}
            elif had_before and not has_now:
                # enrich_deed_chain() deliberately pops a stale deed_chain built from a
                # fallback-point-contaminated source when it finds no genuine records this
                # pass (enrichment_deed_chain.py line ~408) -- must propagate the removal to
                # the board too, not just skip it, or the wrong data stays live.
                cleared_count += 1
                patches[key] = {"raw": {"deed_chain": None}}
            elif has_now and had_before:
                # refreshed with (possibly) new underlying source data -- always re-patch,
                # matching the original script's own "worth re-running" rationale.
                patches[key] = {"raw": {"deed_chain": li.raw["deed_chain"]}}
        if not patches or args.dry_run:
            return
        # FIXED 2026-11-24: board_lock(wait=600) already retries internally for up to 600s,
        # but on this VM that is NOT always enough -- the other standing lanes (meck_gis_attrs,
        # meck_code_enforcement) are observed live holding the SAME lock for 10+ minutes at a
        # stretch. Before this fix, a single BoardLockBusy here was uncaught and crashed the
        # WHOLE multi-hour run (pass 1 + however much of pass 2 had completed), and the
        # supervisor's relaunch starts over from row 0 every time -- on a contended host this
        # could mean near-zero net progress despite "running continuously" for hours (confirmed
        # live: logs/manual_deed_chain_v2_run.log shows BoardLockBusy crashes on most
        # invocations). Retrying the SAME lock acquisition a few more times here (each with its
        # own full 600s internal wait) costs nothing when the lock is free, and turns a
        # transient long hold into "wait a while longer" instead of "lose this whole run."
        #
        # EXTENDED 2026-11-25: confirmed live that the first fix's own retry can SUCCEED at
        # acquiring the lock and still crash one line later. patch_existing_rows() stamps
        # listings.json's mtime/size (web_artifact.py's _LOAD_STAMPS) after its own first
        # successful write in this process; every call after that checks the file still
        # matches that stamp before writing again (BoardChangedSinceLoad otherwise -- "another
        # writer replaced the board while this one worked on a stale copy"). On this host,
        # 5+ other lanes each take the lock and write in the gap between two of THIS script's
        # own flush() calls, so the stamp from our last write is routinely stale by the time we
        # get the lock back -- confirmed live 2026-11-25 00:17-ish: lock acquired on a retry
        # (attempt 1/4 against backfill_mecklenburg_code_enforcement), then
        # BoardChangedSinceLoad fired on the very next line and crashed the run (same
        # restart-from-row-0 cost the first fix was written to avoid). patch_existing_rows()
        # re-streams the current board fresh on every call rather than reusing anything from an
        # earlier call, so simply retrying the whole lock+patch sequence again is correct here
        # too, same as BoardLockBusy -- it will see the board as it is right now, not the stale
        # view that triggered the guard.
        for attempt in range(4):
            try:
                with board_lock(REPO, owner="deed_chain_backfill_v2", wait=600, poll=10):
                    pstats = patch_existing_rows(
                        patches, {"deed_chain_backfill_v2_batch": len(patches)}, docs_dir=docs_dir)
                break
            except (BoardLockBusy, BoardChangedSinceLoad) as exc:
                if attempt == 3:
                    raise
                print(f"  board write contention (attempt {attempt + 1}/4), retrying: "
                      f"{type(exc).__name__}: {exc}")
        print(f"  patch_existing_rows: {pstats}")
        total_patched += pstats.get("applied", 0)

    print("pass 2: streaming board in batches...")
    for rec in iter_board_rows(docs_dir / "listings.json.gz"):
        total_rows += 1
        if total_rows <= skip_rows:
            continue
        raw = rec.get("raw") if isinstance(rec.get("raw"), dict) else {}
        had_before = bool(raw.get("deed_chain"))
        if had_before:
            before_count += 1
        li = Listing.model_construct(**{k: rec.get(k) for k in _LIGHT_FIELDS})
        try:
            key = li.dedupe_key()
        except Exception:  # noqa: BLE001
            key = None
        batch.append((key, li, had_before))
        if len(batch) >= args.batch_size:
            print(f"  batch at row {total_rows:,}...")
            flush(batch)
            batch = []
            if not args.dry_run:
                _save_resume_skip(total_rows)
    flush(batch)
    if not args.dry_run:
        # reached the end clean -- reset to 0 so the next natural pass re-scans the whole
        # board (new/changed rows since this run), instead of resuming into "nothing left"
        # forever.
        _save_resume_skip(0)

    print(f"\nboard rows: {total_rows:,}")
    print(f"rows with deed_chain before: {before_count:,}")
    print(f"rows with deed_chain after: {after_count:,} (net {after_count - before_count:+,})")
    print(f"  newly stamped: {new_count:,}")
    print(f"  cleared (stale/contaminated, no genuine records this pass): {cleared_count:,}")
    if args.dry_run:
        print("DRY RUN -- nothing written.")
    else:
        print(f"total applied: {total_patched:,}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
