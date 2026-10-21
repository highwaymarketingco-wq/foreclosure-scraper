#!/usr/bin/env python3
"""One-time backfill: land Nash NC's new, LIVE multi-year-tax enrichment
(enrichment_nash_multiyear_tax.py, 2026-10-21) onto the already-published board.

Same shape as backfill_iredell_multiyear_tax.py (a LIVE per-parcel fetch against a real portal,
one row at a time, not a pure no-network restatement) -- see that script's own docstring for the
Phase 1/2/3 discipline this one copies verbatim.

NASH IS A HARDER CASE THAN IT LOOKS: the board's own parcel_id field holds THREE different
shapes for this county, and only one of them is searchable on the county's Munis tax-bill
portal. Nash's own 2,090 NC board rows were counted directly (board_stream, 2026-10-21) before
this script was written: of 952 rows carrying ANY parcel_id, 612 (64.3%) are the short 6-digit
Munis/iasWorld PARID ("305400") the portal actually searches by, 282 (29.6%) are the board's
usual 12-digit NC PIN (a DIFFERENT number for the same parcel -- confirmed live, PARID 305400's
own PIN is 385208991720, and searching the PIN on Munis returns zero), and 58 (6.1%) carry the
"NC#####" NC dam-safety inventory ID in parcel_id, not a tax parcel number at all (the same
unrelated-shape noise enrichment_iredell_multiyear_tax.py's own docstring documents for Iredell).
So this script's realistic ceiling is ~612 rows, not 952 and nowhere near the gap list's 2,090.
It does not pre-filter on shape (same as every sibling backfill): every NC/Nash row with ANY
non-empty parcel_id is a Phase-1 candidate, and enrichment_nash_multiyear_tax's own _fetch()
sentinels the wrong-shaped ones as "parcel_not_found" (Munis matches by exact PARID, not prefix).

BOARD I/O, same discipline as every backfill before this one. Phase 1 streams the board once via
board_stream.iter_board_rows(), keeping only NC Nash rows not already carrying
multi_year_delinquent_tax or a _nash_mydt_checked marker, as lightweight Listings
(_APPEND_SIG_FIELDS + raw). Phase 2 runs the real enrich_with_nash_multiyear_tax() in a batch
loop, in-memory, no board writes yet. Phase 3 diffs each candidate's raw (two_year_delinquent /
multi_year_delinquent_tax / _nash_mydt_checked) before/after, builds patches (the same
ambiguous-dedupe_key exclusion safety net as every prior backfill), and lands them with ONE
patch_existing_rows() call under board_lock(), via the same supervised dual-signal watchdog.

Usage:
    python scripts/backfill_nash_multiyear_tax.py --dry-run
    python scripts/backfill_nash_multiyear_tax.py --dry-run --max-batches 1
    python scripts/backfill_nash_multiyear_tax.py --allow-large --max-batches 4
"""
from __future__ import annotations

import argparse
import asyncio
import contextlib
import multiprocessing as mp
import os
import sys
import time
from pathlib import Path
from typing import Any, Optional

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "src"))

from foreclosure_scraper.board_stream import iter_board_rows  # noqa: E402
from foreclosure_scraper.enrichment_nash_multiyear_tax import (  # noqa: E402
    CHECKED_KEY, MYDT_KEY, TYD_KEY, enrich_with_nash_multiyear_tax,
)
from foreclosure_scraper.models import Listing  # noqa: E402
from foreclosure_scraper.web_artifact import (  # noqa: E402
    _APPEND_SIG_FIELDS, board_lock, board_patch_size_state, patch_existing_rows,
)

_LIGHT_FIELDS = _APPEND_SIG_FIELDS + ("raw",)
COUNTY = "Nash"
_WATCH_KEYS = (TYD_KEY, MYDT_KEY, CHECKED_KEY)


def _light(rec: dict) -> Listing:
    return Listing.model_construct(**{k: rec.get(k) for k in _LIGHT_FIELDS})


def _already_checked(raw: Any) -> bool:
    if not isinstance(raw, dict):
        return False
    return isinstance(raw.get(TYD_KEY), dict) or bool(raw.get(CHECKED_KEY))


# ===========================================================================
# Phase 1
# ===========================================================================

def _collect_candidates(docs: Path) -> tuple[dict[str, Listing], int, int]:
    """{dedupe_key: light_listing}, total rows streamed, ambiguous-identity count excluded
    (shared dedupe_key with another Nash candidate)."""
    cands: dict[str, Listing] = {}
    seen: dict[str, int] = {}
    total = 0
    for rec in iter_board_rows(docs / "listings.json.gz"):
        total += 1
        if str(rec.get("state") or "").upper() != "NC":
            continue
        county = (rec.get("county") or "").replace(" County", "").strip().title()
        if county != COUNTY:
            continue
        if not str(rec.get("parcel_id") or "").strip():
            continue
        if _already_checked(rec.get("raw")):
            continue
        li = _light(rec)
        try:
            key = li.dedupe_key()
        except Exception:  # noqa: BLE001
            continue
        seen[key] = seen.get(key, 0) + 1
        cands[key] = li
    ambiguous = 0
    for key, n in seen.items():
        if n > 1:
            cands.pop(key, None)
            ambiguous += 1
    return cands, total, ambiguous


# ===========================================================================
# Phase 2: batch loop over the REAL enrich_with_nash_multiyear_tax(), unmodified.
# ===========================================================================

async def _run_batches(candidates: dict[str, Listing], max_batches: int) -> list[dict]:
    listings = list(candidates.values())
    batch_stats: list[dict] = []
    for i in range(max_batches):
        remaining = sum(1 for li in listings if not _already_checked(li.raw))
        if remaining == 0:
            break
        t0 = time.monotonic()
        stats = await enrich_with_nash_multiyear_tax(listings)
        stats["batch"] = i + 1
        stats["elapsed_s"] = round(time.monotonic() - t0, 1)
        stats["remaining_before_batch"] = remaining
        print(f"  {COUNTY} batch {i + 1}: {stats}")
        batch_stats.append(stats)
        if stats.get("attempted", 0) == 0:
            break  # nothing left this module considers eligible
    return batch_stats


def _build_patches(candidates: dict[str, Listing], before: dict[str, dict]) -> dict[str, dict]:
    patches: dict[str, dict] = {}
    for key, li in candidates.items():
        after_raw = li.raw if isinstance(li.raw, dict) else {}
        b = before[key]
        raw_patch = {k: after_raw.get(k) for k in _WATCH_KEYS if after_raw.get(k) != b.get(k)}
        if raw_patch:
            patches[key] = {"raw": raw_patch}
    return patches


# ===========================================================================
# Phase 3: supervised patch_existing_rows() -- copied verbatim from the established harness
# (backfill_iredell_multiyear_tax.py's own Phase 3).
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
    ap.add_argument("--max-batches", type=int, default=4,
                    help="Batches of up to 200 rows this invocation will run. Default 4 "
                         "(800 rows) -- comfortably above the ~612-row realistic ceiling "
                         "(most of the rest sentinel out as parcel_not_found in one pass). "
                         "Re-run with a higher value, or run again, if ever needed.")
    ap.add_argument("--patch-timeout-s", type=float, default=1200.0)
    ap.add_argument("--patch-mem-ceiling-mb", type=float, default=16000.0)
    args = ap.parse_args()

    docs = REPO / "docs"

    lock = contextlib.nullcontext() if args.dry_run else board_lock(REPO, owner="nash_mydt_backfill")
    with lock:
        candidates, total_rows, ambiguous = _collect_candidates(docs)
        print(f"board rows streamed: {total_rows:,}")
        print(f"{COUNTY} NC eligible candidates: {len(candidates):,}")
        if ambiguous:
            print(f"excluded as ambiguous-identity (shared dedupe_key with another "
                  f"candidate, never guessed at): {ambiguous:,}")

        before = {key: dict(li.raw) if isinstance(li.raw, dict) else {}
                 for key, li in candidates.items()}

        if candidates:
            print(f"\n=== {COUNTY} NC: running real enrich_with_nash_multiyear_tax in "
                  f"batches ===")
            asyncio.run(_run_batches(candidates, args.max_batches))

        patches = _build_patches(candidates, before)
        print(f"\npatches staged: {len(patches):,}")
        by_kind = {"qualified": 0, "two_year_only": 0, "checked_no_answer": 0}
        for p in patches.values():
            r = p["raw"]
            if r.get(MYDT_KEY) is not None:
                by_kind["qualified"] += 1
            elif r.get(TYD_KEY) is not None:
                by_kind["two_year_only"] += 1
            else:
                by_kind["checked_no_answer"] += 1
        print(f"    qualified (multi_year_delinquent_tax written): {by_kind['qualified']:,}")
        print(f"    two_year_delinquent written, did not qualify:  {by_kind['two_year_only']:,}")
        print(f"    checked, no usable answer (sentinel only):     {by_kind['checked_no_answer']:,}")

        if args.dry_run:
            print("\nDRY RUN -- nothing written. (Note: enrich_with_nash_multiyear_tax above "
                  "still hits the real live portal -- this module has no network-free dry-run "
                  "mode; --dry-run here only controls whether the result is WRITTEN to the "
                  "board.)")
            return 0
        if not patches:
            print("\nnothing to do.")
            return 0

        size_state = board_patch_size_state(docs)
        if not size_state["ok"] and not args.allow_large:
            print(f"\nREFUSING: {size_state['reason']}. Re-run with --allow-large under "
                  f"supervision.")
            return 1

        stats_patch, watchdog = _run_patch_supervised(
            patches, {"ambiguous": ambiguous}, docs,
            timeout_s=args.patch_timeout_s, mem_ceiling_mb=args.patch_mem_ceiling_mb,
            allow_large=args.allow_large,
        )
        print(f"\nwatchdog: peak VmRSS {watchdog['peak_rss_mb']:.0f} MB, "
              f"peak VmHWM {watchdog['peak_vmhwm_mb']:.0f} MB, wall {watchdog['elapsed_s']:.1f}s")
        print(f"wrote board: patched {stats_patch['applied']:,}/{len(patches):,} rows "
              f"(existing board: {stats_patch['existing']:,}, not_found: {stats_patch['not_found']:,}, "
              f"duplicate_key_matches: {stats_patch['duplicate_key_matches']:,})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
