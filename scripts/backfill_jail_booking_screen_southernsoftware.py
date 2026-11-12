#!/usr/bin/env python3
"""One-time backfill: execute the already-shipped jail_booking_screen stamp (commit 65a8873e,
2026-10-16, enrichment_jail_bookings.py's match_rosters()/_stamp_screen()) against the real
board, for real, for the two counties that fix genuinely closes: Transylvania NC and Polk NC.

WHY THIS EXISTS. Confirmed 2026-10-19 (project_jail_booking_nothinglands_checked memory note):
match_rosters() has carried the jail_booking_screen "healthy roster, no match" sentinel since
2026-10-16, but nothing has executed it against the live board since -- zero jail_booking_screen
entries exist anywhere on the whole 437,170-row board. run_pending_signal_enrichers.py (the
normal caller) has a documented OOM-risk hold, so this is a scoped, standalone runner instead of
waiting for that to be lifted -- same shape as backfill_deed_ref_bound.py /
backfill_multiyear_tax_restatement.py before it.

SCOPE, DELIBERATELY NARROW. Of jail_booking's 5 "nothing lands" counties (Transylvania NC, Lee NC,
Polk NC, Lee SC, Cherokee NC), only Transylvania and Polk have a real adapter: both are the same
Southern Software Citizen Connect tenant as Henderson NC (ROSTERS in enrichment_jail_bookings.py),
just a different AgencyID/JMSAgencyID. Lee NC, Lee SC and NC Cherokee are confirmed FALSE
POSITIVES (gap_matrix.py text-grep artifacts, no adapter exists) -- deliberately not attempted
here; building anything for them would be wasted/wrong, per the memory note's own finding.

WHAT THIS CALLS, UNMODIFIED. _load_roster() (the real per-run roster fetch, Citizen Connect lane)
and match_rosters() (the real stamp logic) -- not a reimplementation. match_cross_county() (the
whole-board name fan-out) is deliberately NOT invoked: this runner's job is the per-county
Story-A/B screen stamp for these two counties, not the separate cross-county re-identification
feature, which needs the whole NC/SC board in memory to mean anything and is out of scope here.

BOARD I/O, same discipline as every other backfill tonight. Phase 1 streams the published board
exactly once via board_stream.iter_board_rows() (never load_board() -- this board measures far
over BOARD_LOAD_MAX_SOURCE_MB on the VM) and keeps only Transylvania NC / Polk NC rows as
lightweight, UNVALIDATED Listings (model_construct(), the same _APPEND_SIG_FIELDS + raw trick
backfill_deed_ref_bound.py uses) -- a few hundred rows at most, not the 437,170-row board. Phase 2
fetches both counties' live rosters (2 HTTP round trips total, not per-row -- this is a BULK
roster fetch, not the per-name SEARCH_ROSTERS lane) and calls match_rosters() once over the
in-memory candidate list. Phase 3 diffs each candidate's raw dict before/after the call (only
jail_booking_screen / jail_booking / incarceration can change) and builds a patches dict from
exactly what changed, then lands it with ONE patch_existing_rows() call under board_lock() --
same ambiguous-shared-dedupe_key exclusion safety net as every prior backfill (a person-matched
jail record is row-specific content, same reasoning backfill_deed_ref_bound.py uses for its own
content-derived patches -- never guessed at across two rows sharing one identity).

--dry-run threads through to _load_roster()'s own dry_run (-> jail_roster_history.diff_and_record
commit=False) so a dry run's roster-health bookkeeping is never persisted, exactly the
2026-09-29 bug backfill scripts before this one were built to avoid repeating.

Usage:
    python scripts/backfill_jail_booking_screen_southernsoftware.py --dry-run
    python scripts/backfill_jail_booking_screen_southernsoftware.py --allow-large
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
from foreclosure_scraper.enrichment_jail_bookings import _load_roster, match_rosters  # noqa: E402
from foreclosure_scraper.models import Listing  # noqa: E402
from foreclosure_scraper.web_artifact import (  # noqa: E402
    _APPEND_SIG_FIELDS, board_lock, board_patch_size_state, patch_existing_rows,
)

#: Transylvania + Polk NC's own ROSTERS entries, copied verbatim from
#: enrichment_jail_bookings.ROSTERS (not re-derived -- if that list ever changes, this runner
#: should be re-pointed at it directly rather than silently drifting).
_TARGETS = [
    ("NC", "Polk", "citizen_connect", "PolkCoNC|NC0750000"),
    ("NC", "Transylvania", "citizen_connect", "TransylvaniaCoNC|NC0880000"),
]
_TARGET_COUNTIES = {(s, c) for s, c, _, _ in _TARGETS}

#: identity + raw fields enough to build a lightweight, UNVALIDATED Listing for
#: _owner_of()/_plain_county()/match_rosters()/dedupe_key() -- same trick
#: backfill_deed_ref_bound.py uses, for the same reason.
_LIGHT_FIELDS = _APPEND_SIG_FIELDS + ("raw",)

_WATCH_KEYS = ("jail_booking_screen", "jail_booking", "incarceration")


def _light(rec: dict) -> Listing:
    return Listing.model_construct(**{k: rec.get(k) for k in _LIGHT_FIELDS})


def _plain_county(li: Any) -> str:
    return (li.county or "").replace(" County", "").strip().title()


# ===========================================================================
# Phase 1: stream the board once, keep only Transylvania/Polk NC rows.
# ===========================================================================

def _collect_candidates(docs: Path) -> tuple[dict[str, Listing], int, int]:
    """{dedupe_key: light_listing} for every Transylvania/Polk NC row, total rows streamed,
    and candidates excluded as sharing an ambiguous dedupe_key with another candidate (same
    "never guess across two rows sharing one identity" rule every prior backfill uses)."""
    candidates: dict[str, Listing] = {}
    seen: dict[str, int] = {}
    total = 0
    for rec in iter_board_rows(docs / "listings.json.gz"):
        total += 1
        if str(rec.get("state") or "").upper() != "NC":
            continue
        county = (rec.get("county") or "").replace(" County", "").strip().title()
        if ("NC", county) not in _TARGET_COUNTIES:
            continue
        li = _light(rec)
        try:
            key = li.dedupe_key()
        except Exception:  # noqa: BLE001 - too malformed to key, unpatchable
            continue
        seen[key] = seen.get(key, 0) + 1
        candidates[key] = li
    ambiguous = {k for k, n in seen.items() if n > 1}
    for key in ambiguous:
        candidates.pop(key, None)
    return candidates, total, len(ambiguous)


# ===========================================================================
# Phase 2: fetch both counties' live rosters (2 HTTP round trips, bulk lane) and run the
# real match_rosters() over the in-memory candidate list.
# ===========================================================================

async def _fetch_rosters(dry_run: bool) -> dict:
    return dict(await asyncio.gather(
        *[_load_roster(s, c, v, t, dry_run=dry_run) for s, c, v, t in _TARGETS]))


def _run_match(candidates: dict[str, Listing], rosters: dict) -> tuple[dict[str, dict], dict]:
    """Diffs each candidate's raw dict before/after match_rosters() and returns
    ({dedupe_key: {"raw": {...changed keys...}}}, stats)."""
    listings = list(candidates.values())
    before = {id(li): {k: (li.raw or {}).get(k) for k in _WATCH_KEYS} for li in listings}
    stats: dict = {}
    matched = match_rosters(listings, rosters, stats=stats)
    stats["bulk_matched"] = len(matched)

    patches: dict[str, dict] = {}
    key_by_id = {id(li): key for key, li in candidates.items()}
    for li in listings:
        after = li.raw if isinstance(li.raw, dict) else {}
        b = before[id(li)]
        raw_patch = {k: after.get(k) for k in _WATCH_KEYS if after.get(k) != b.get(k)}
        if raw_patch:
            patches[key_by_id[id(li)]] = {"raw": raw_patch}
    return patches, stats


# ===========================================================================
# Phase 3: supervised patch_existing_rows() -- the only part of this script that write-locks
# and mutates the live board. Copied verbatim from backfill_deed_ref_bound.py's own harness
# (same dual /proc/<pid>/status wall-clock + VmRSS/VmHWM watchdog), not re-derived.
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
    ap.add_argument("--patch-timeout-s", type=float, default=600.0,
                    help="Wall-clock kill-switch (seconds). Default 10 minutes -- this backfill "
                         "touches at most a few hundred rows, far below the 41,145-row "
                         "multiyear-tax run's 20-minute allowance.")
    ap.add_argument("--patch-mem-ceiling-mb", type=float, default=16000.0)
    args = ap.parse_args()

    docs = REPO / "docs"

    lock = contextlib.nullcontext() if args.dry_run else board_lock(REPO, owner="jail_booking_screen_backfill")
    with lock:
        candidates, total_rows, ambiguous = _collect_candidates(docs)
        print(f"board rows streamed: {total_rows:,}")
        print(f"Transylvania/Polk NC candidates: {len(candidates):,}")
        if ambiguous:
            print(f"excluded as ambiguous-identity (shared dedupe_key with another "
                  f"candidate, never guessed at): {ambiguous:,}")
        if not candidates:
            print("\nnothing to do -- no Transylvania/Polk NC rows found.")
            return 0

        rosters = asyncio.run(_fetch_rosters(dry_run=args.dry_run))
        for (s, c), idx in sorted(rosters.items()):
            print(f"roster {s}/{c}: {len(idx):,} names, healthy={getattr(idx, 'healthy', False)}, "
                  f"health={getattr(idx, 'health', {})}")

        patches, stats = _run_match(candidates, rosters)
        print("\nmatch_rosters() outcome:")
        for k, v in sorted(stats.items()):
            print(f"    {k:30} {v:,}")
        print(f"\npatches staged: {len(patches):,}")
        screen_only = sum(1 for p in patches.values() if "jail_booking" not in p["raw"] or p["raw"].get("jail_booking") is None)
        real_hits = len(patches) - screen_only
        print(f"    jail_booking_screen-only (no match): {screen_only:,}")
        print(f"    genuine jail_booking match:          {real_hits:,}")

        if args.dry_run:
            print("\nDRY RUN -- nothing written.")
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
            patches, dict(stats), docs,
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
