#!/usr/bin/env python3
"""One-time backfill: land enrichment_madison_rollback_exposure.py (rollback_exposure gap-matrix
build, 2026-10-28) onto the ALREADY-PUBLISHED board, without a full pipeline run.

Same shape as scripts/backfill_hyde_rollback_exposure.py (read that script's own docstring for
the full discipline this reuses): stream the board exactly once via board_stream.iter_board_rows()
(never load_board()), bucket every Madison NC row whose parcel_id is already shaped like lrcpwa's
own 9-11 digit PIN as a candidate, run the REAL production enrich_madison_rollback_exposure()
(unmodified, over lightweight Listings), diff raw['rollback_exposure'] before/after to build
patches, and apply them through the same supervised patch_existing_rows() wrapper.

The real production enrichment here is ASYNC (live calls against lrcpwa.ncptscloud.com, no local
cache to join against) -- _build_patches wraps it in asyncio.run().

Usage:
    python scripts/backfill_madison_rollback_exposure.py --dry-run
    python scripts/backfill_madison_rollback_exposure.py --allow-large
"""
from __future__ import annotations

import argparse
import asyncio
import contextlib
import multiprocessing as mp
import os
import sys
import time
from collections import Counter
from pathlib import Path
from typing import Any, Optional

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "src"))

from foreclosure_scraper.board_stream import iter_board_rows  # noqa: E402
from foreclosure_scraper.enrichment_madison_rollback_exposure import (  # noqa: E402
    RAW_KEY,
    _eligible,
    enrich_madison_rollback_exposure,
)
from foreclosure_scraper.models import Listing  # noqa: E402
from foreclosure_scraper.web_artifact import (  # noqa: E402
    _APPEND_SIG_FIELDS, board_lock, board_patch_size_state, patch_existing_rows,
)

_LIGHT_FIELDS = _APPEND_SIG_FIELDS + ("raw",)


def _light(rec: dict) -> Listing:
    return Listing.model_construct(**{k: rec.get(k) for k in _LIGHT_FIELDS})


def _raw(li: Any) -> dict:
    r = getattr(li, "raw", None)
    return r if isinstance(r, dict) else {}


# ===========================================================================
# Phase 1: stream the board once, collect candidates -- never load_board().
# ===========================================================================

def _collect_candidates_from_rows(rows) -> tuple[dict[str, Listing], int, dict]:
    """({dedupe_key: light_listing}, total rows seen, ambiguity report). Same "skip and count,
    never guess" discipline as backfill_hyde_rollback_exposure.py's own function: a dedupe_key
    seen on more than one eligible row means patch_existing_rows() would apply whichever ONE
    patch gets built under that key to EVERY matching row -- excluded unconditionally rather
    than guessed at."""
    candidates: dict[str, Listing] = {}
    total = 0
    occurrences: dict[str, int] = {}
    for rec in rows:
        total += 1
        li = _light(rec)
        if not _eligible(li):
            continue
        try:
            key = li.dedupe_key()
        except Exception:  # noqa: BLE001 - a row too malformed to key is simply unpatchable
            continue
        occurrences[key] = occurrences.get(key, 0) + 1
        candidates[key] = li

    ambiguous_keys = {k for k, n in occurrences.items() if n > 1}
    rows_excluded = sum(occurrences[k] for k in ambiguous_keys)
    for k in ambiguous_keys:
        candidates.pop(k, None)
    ambiguity_report = {"distinct_keys": len(ambiguous_keys), "rows_total": rows_excluded}
    return candidates, total, ambiguity_report


def _collect_candidates(docs: Path) -> tuple[dict[str, Listing], int, dict]:
    return _collect_candidates_from_rows(iter_board_rows(docs / "listings.json.gz"))


def _build_patches(candidates: dict[str, Listing], c: Counter) -> dict[str, dict]:
    """Run the REAL production enrich_madison_rollback_exposure() (unmodified, over its own list
    of lightweight Listings) and diff raw[RAW_KEY] before/after -- guarantees byte-identical
    output to a real pipeline run and reuses the module's own idempotent _already_done() gate.
    The real enrichment is async (live lrcpwa.ncptscloud.com calls); asyncio.run() drives it."""
    before: dict[str, Any] = {key: _raw(li).get(RAW_KEY) for key, li in candidates.items()}
    stats = asyncio.run(enrich_madison_rollback_exposure(list(candidates.values())))
    for k, v in stats.items():
        if isinstance(v, (int, float)):
            c[k] += v
    patches: dict[str, dict] = {}
    for key, li in candidates.items():
        raw = _raw(li)
        after = raw.get(RAW_KEY)
        if after is None or after == before.get(key):
            continue
        patches[key] = {"raw": {RAW_KEY: after}}
        c["patched"] += 1
    return patches


# ===========================================================================
# Phase 2: supervised patch_existing_rows() -- reused verbatim from
# backfill_hyde_rollback_exposure.py (same watchdog shape).
# ===========================================================================

def _parse_proc_status_text(text: str) -> tuple[Optional[float], Optional[float]]:
    rss = hwm = None
    for line in text.splitlines():
        parts = line.split()
        if len(parts) < 2:
            continue
        if line.startswith("VmRSS:"):
            try:
                rss = float(parts[1]) / 1024.0
            except ValueError:
                pass
        elif line.startswith("VmHWM:"):
            try:
                hwm = float(parts[1]) / 1024.0
            except ValueError:
                pass
    return rss, hwm


def _read_proc_status_mb(pid: int) -> tuple[Optional[float], Optional[float]]:
    try:
        text = Path(f"/proc/{pid}/status").read_text()
    except OSError:
        return None, None
    return _parse_proc_status_text(text)


def _watchdog_should_kill(elapsed_s: float, rss_mb: Optional[float], hwm_mb: Optional[float], *,
                          timeout_s: float, mem_ceiling_mb: float) -> Optional[str]:
    if elapsed_s > timeout_s:
        return f"wall-clock timeout ({timeout_s:.0f}s) exceeded (elapsed={elapsed_s:.1f}s)"
    if rss_mb is not None and rss_mb > mem_ceiling_mb:
        return f"VmRSS {rss_mb:.0f} MB exceeded the {mem_ceiling_mb:.0f} MB ceiling"
    if hwm_mb is not None and hwm_mb > mem_ceiling_mb:
        return f"VmHWM {hwm_mb:.0f} MB exceeded the {mem_ceiling_mb:.0f} MB ceiling"
    return None


def _patch_worker(patches: dict, summary: dict, docs_dir: str, allow_large: bool,
                  result_queue: "mp.Queue") -> None:
    if allow_large:
        os.environ["BOARD_PATCH_ALLOW_LARGE"] = "1"
    try:
        stats = patch_existing_rows(patches, summary, docs_dir=docs_dir)
        result_queue.put(("ok", stats))
    except BaseException as exc:  # noqa: BLE001
        result_queue.put(("error", f"{type(exc).__name__}: {exc}"))


def _run_patch_supervised(patches: dict, summary: dict, docs_dir: Path, *,
                          timeout_s: float, mem_ceiling_mb: float, allow_large: bool,
                          poll_s: float = 1.0) -> tuple[dict, dict]:
    ctx = mp.get_context("spawn")
    q: "mp.Queue" = ctx.Queue()
    proc = ctx.Process(target=_patch_worker, args=(patches, summary, str(docs_dir), allow_large, q))
    proc.start()
    start = time.monotonic()
    peak_rss = peak_hwm = 0.0
    killed_reason: Optional[str] = None
    try:
        while proc.is_alive():
            elapsed = time.monotonic() - start
            rss, hwm = _read_proc_status_mb(proc.pid)
            if rss is not None:
                peak_rss = max(peak_rss, rss)
            if hwm is not None:
                peak_hwm = max(peak_hwm, hwm)
            killed_reason = _watchdog_should_kill(
                elapsed, rss, hwm, timeout_s=timeout_s, mem_ceiling_mb=mem_ceiling_mb)
            if killed_reason:
                proc.kill()
                break
            time.sleep(poll_s)
    finally:
        proc.join(timeout=60)
    report = {"peak_rss_mb": peak_rss, "peak_vmhwm_mb": peak_hwm,
              "elapsed_s": time.monotonic() - start, "killed_reason": killed_reason}
    if killed_reason:
        raise RuntimeError(
            f"patch_existing_rows watchdog killed the child process: {killed_reason}. {report}")
    if proc.exitcode != 0:
        raise RuntimeError(
            f"patch_existing_rows child process exited with code {proc.exitcode}: {report}")
    try:
        status, payload = q.get(timeout=30)
    except Exception as exc:  # noqa: BLE001
        raise RuntimeError(
            f"patch_existing_rows child produced no result: {exc}. {report}") from exc
    if status != "ok":
        raise RuntimeError(f"patch_existing_rows child raised: {payload}. {report}")
    return payload, report


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--allow-large", action="store_true")
    ap.add_argument("--patch-timeout-s", type=float, default=1800.0)
    ap.add_argument("--patch-mem-ceiling-mb", type=float, default=16000.0)
    args = ap.parse_args()

    docs = REPO / "docs"

    lock = contextlib.nullcontext() if args.dry_run else board_lock(
        REPO, owner="madison_rollback_exposure_backfill")
    with lock:
        candidates, total_rows, ambiguity = _collect_candidates(docs)
        print(f"board rows streamed: {total_rows:,}")
        print(f"Madison NC candidates (bare-PIN parcel_id, not already stamped): {len(candidates):,}")

        c: Counter = Counter()
        c["skipped_ambiguous_dedupe_key_distinct"] = ambiguity["distinct_keys"]
        c["skipped_ambiguous_dedupe_key_rows"] = ambiguity["rows_total"]
        if ambiguity["rows_total"]:
            print(f"excluded as ambiguous-identity (shared dedupe_key with another candidate, "
                  f"never guessed at): {ambiguity['rows_total']:,} rows under "
                  f"{ambiguity['distinct_keys']:,} distinct colliding key(s)")

        patches = _build_patches(candidates, c)

        print("\nby kind:")
        for k, v in sorted(c.items()):
            print(f"    {k:40} {v:,}")
        print(f"\npatches staged: {len(patches):,}")

        if args.dry_run:
            print("\nDRY RUN -- nothing written.")
            return 0
        if not patches:
            print("\nnothing to do.")
            return 0

        size_state = board_patch_size_state(docs)
        if not size_state["ok"] and not args.allow_large:
            print(f"\nREFUSING: {size_state['reason']}. Re-run with --allow-large once the "
                  f"supervised watchdog is wired the way you want it.")
            return 1

        stats, watchdog = _run_patch_supervised(
            patches, dict(c), docs,
            timeout_s=args.patch_timeout_s, mem_ceiling_mb=args.patch_mem_ceiling_mb,
            allow_large=args.allow_large,
        )
        print(f"\nwatchdog: peak VmRSS {watchdog['peak_rss_mb']:.0f} MB, "
              f"peak VmHWM {watchdog['peak_vmhwm_mb']:.0f} MB, wall {watchdog['elapsed_s']:.1f}s")
        print(f"wrote board: patched {stats['applied']:,}/{len(patches):,} rows "
              f"(existing board: {stats['existing']:,}, not_found: {stats['not_found']:,}, "
              f"duplicate_key_matches: {stats['duplicate_key_matches']:,})")
        if stats["duplicate_key_matches"]:
            print(f"\n*** {stats['duplicate_key_matches']:,} duplicate_key_matches -- DO NOT "
                  f"assume these are fine. Spot-check before anyone decides to publish. ***")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
