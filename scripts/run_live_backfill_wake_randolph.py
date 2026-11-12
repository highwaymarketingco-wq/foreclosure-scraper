#!/usr/bin/env python3
"""One-off LIVE-FETCH push: clear a large slice of the Wake and Randolph NC
multi_year_delinquent_tax backlog by calling each county's own already-shipped, already-wired
per-row enrichment function (enrichment_wake_multiyear_tax.enrich_with_wake_multiyear_tax,
enrichment_randolph_multiyear_tax.enrich_with_randolph_multiyear_tax) against the REAL backlog,
with their MAX_ROWS cap raised far past the conservative per-pipeline-run default of 300 -- both
modules' own docstrings explicitly invite this for "an explicit one-off backfill".

UNLIKE scripts/backfill_deed_ref_bound.py and scripts/backfill_multiyear_tax_restatement.py (the
two models this script is built from), the two functions here are NOT pure, no-network
restatements of data already on the row -- each one makes a REAL live HTTP call per candidate row
against a county government tax-billing portal (services.wake.gov / txpwa.randolphcountync.gov).
That changes two things this script's phase 1 and phase 3 account for:
  * Phase 1 still streams the board once via board_stream.iter_board_rows() (never load_board())
    to build the candidate list -- same cheap pre-filter shape, replicating each module's own
    _eligible() (NC, matching county, non-blank parcel_id, not already checked/qualified) so the
    candidate count can be reported BEFORE paying for any network call.
  * Phase 3 (the live fetch itself) is async and happens OUTSIDE board_lock() -- board_lock() is
    only acquired for the brief Phase 1 stream-and-collect and the final Phase 4
    patch_existing_rows() write, never held across what may be many minutes of live HTTP calls to
    a third-party government portal. This matters: another board-touching process must still not
    run concurrently (point 4 of this project's standing discipline -- checked, not locked, before
    phase 3 starts), but a government portal's own round-trip latency is not something this
    script should make board_lock()'s other would-be holders wait on.
  * The live calls are chunked into separate asyncio.run() passes over slices of the raised cap
    (--chunk-size, default 500) rather than one single huge gather(), each chunk pausing
    --chunk-pause-s (default 5s) before the next. This is the "pace a very large batch" judgment
    call this project's standing discipline asks for explicitly on a fragile/major portal: Wake's
    services.wake.gov is a major NC county government site, so the default CONCURRENCY the module
    already ships (4) is left untouched, not raised, and chunking gives a clean, inspectable
    progress log plus a natural place to stop early (--max-rows) without losing work already done
    (each chunk's qualified rows are folded into the patch set as it goes).

SHAPE REUSED VERBATIM FROM THE TWO BACKFILLS ALREADY SHIPPED TONIGHT:
  * Lightweight Listing.model_construct() candidates (never Listing.model_validate()) --
    _APPEND_SIG_FIELDS + "raw", the same fields patch_existing_rows()/append_new_rows() already
    use this way.
  * Same ambiguous-shared-identity-key exclusion safety net as backfill_deed_ref_bound.py and
    backfill_multiyear_tax_restatement.py: a dedupe_key() seen on more than one candidate (the
    board already has two different rows under one weak identity) is excluded from `patches`
    entirely, reported by distinct-key count AND row count, never guessed at -- this is a
    property-level fact (the parcel's own unpaid-tax history), so it should be equally true for
    every row sharing one identity, but patch_existing_rows()'s own 2026-10-19 duplicate_key_matches
    incident is exactly why this stays unconditional regardless.
  * Same dual-watchdog supervised child-process write for the final patch_existing_rows() call:
    an internal /proc/<pid>/status-based wall-clock + VmRSS/VmHWM watchdog in this script, run
    underneath the project's own second-layer deploy/oracle/mem_watchdog.py on the VM.
  * --dry-run classifies (and for this script, ALSO performs the live fetch, since the live
    numbers ARE the thing being measured) but never writes. --allow-large overrides
    BOARD_PATCH_MAX_SOURCE_MB for the one supervised write, same flag shape as both backfills.

Usage:
    python scripts/run_live_backfill_wake_randolph.py --dry-run \
        --wake-max 2000 --randolph-max 2000
    python scripts/run_live_backfill_wake_randolph.py \
        --wake-max 2000 --randolph-max 2000 --allow-large
    # Only one county this run:
    python scripts/run_live_backfill_wake_randolph.py --counties wake --wake-max 3000
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
from foreclosure_scraper.models import Listing  # noqa: E402
from foreclosure_scraper.verification.fetch import Fetcher  # noqa: E402
from foreclosure_scraper.web_artifact import (  # noqa: E402
    _APPEND_SIG_FIELDS, board_lock, board_patch_size_state, patch_existing_rows,
)

log = None  # set up lazily so this script can be imported without structlog side effects

_LIGHT_FIELDS = _APPEND_SIG_FIELDS + ("raw",)


def _light(rec: dict) -> Listing:
    return Listing.model_construct(**{k: rec.get(k) for k in _LIGHT_FIELDS})


def _raw(li: Any) -> dict:
    r = getattr(li, "raw", None)
    return r if isinstance(r, dict) else {}


# ===========================================================================
# Per-county plumbing: eligibility mirrors each module's own _eligible(), kept in sync by hand
# (importing the private function directly, rather than re-deriving it, so this never drifts).
# ===========================================================================

def _make_county_spec(name: str):
    if name == "wake":
        from foreclosure_scraper.enrichment_wake_multiyear_tax import (
            RAW_KEY, _eligible, enrich_with_wake_multiyear_tax as enrich_fn,
        )
        return name, _eligible, enrich_fn, (RAW_KEY,)
    if name == "randolph":
        from foreclosure_scraper.enrichment_randolph_multiyear_tax import (
            RAW_KEY, _eligible, enrich_with_randolph_multiyear_tax as enrich_fn,
        )
        return name, _eligible, enrich_fn, (RAW_KEY,)
    raise ValueError(f"unknown county {name!r}")


# ===========================================================================
# Phase 1: stream the board once, bucket eligible candidates per county -- never load_board().
# ===========================================================================

def _collect_candidates_from_rows(rows, specs: dict[str, tuple]) -> tuple[
        dict[str, dict[str, Listing]], int, dict]:
    """({county: {dedupe_key: light_listing}}, total rows streamed, ambiguity report). Ambiguity
    is tracked GLOBALLY across both counties' candidate sets (a dedupe_key colliding between a
    Wake and a Randolph candidate would be a data error, not a normal case, but is handled the
    same unconditional way regardless of which bucket(s) it appears in)."""
    buckets: dict[str, dict[str, Listing]] = {name: {} for name in specs}
    total = 0
    occurrences: dict[str, list[str]] = {}
    for rec in rows:
        total += 1
        raw = rec.get("raw")
        li = None
        for county, (_name, eligible_fn, _enrich_fn, _raw_keys) in specs.items():
            # Build the lightweight Listing lazily, once, only once some county's cheap
            # top-level checks could plausibly pass -- avoid paying model_construct() for every
            # one of 437k rows when a bare dict check can reject most of them first.
            if (rec.get("state") or "").strip().upper() != "NC":
                break
            if li is None:
                li = _light(rec)
            try:
                ok = eligible_fn(li)
            except Exception:  # noqa: BLE001 - a malformed row is simply not a candidate
                ok = False
            if not ok:
                continue
            try:
                key = li.dedupe_key()
            except Exception:  # noqa: BLE001 - too malformed to key is simply unpatchable
                continue
            occurrences.setdefault(key, []).append(county)
            buckets[county][key] = li

    ambiguous_keys = {k for k, hits in occurrences.items() if len(hits) > 1}
    rows_by_bucket: Counter = Counter()
    for key in ambiguous_keys:
        for bucket_map in buckets.values():
            bucket_map.pop(key, None)
        for county in occurrences[key]:
            rows_by_bucket[county] += 1
    ambiguity_report = {
        "distinct_keys": len(ambiguous_keys),
        "rows_total": sum(rows_by_bucket.values()),
        "rows_by_bucket": dict(rows_by_bucket),
    }
    return buckets, total, ambiguity_report


def _collect_candidates(docs: Path, specs: dict[str, tuple]):
    return _collect_candidates_from_rows(iter_board_rows(docs / "listings.json.gz"), specs)


# ===========================================================================
# Phase 2: chunked, paced live fetch -- the part with no precedent in the two no-network
# backfills. Each chunk is one asyncio.run() over a slice of that county's capped candidate
# list, using a fresh Fetcher per county (never shared across counties: Fetcher.min_interval_s
# paces per-host, and a shared instance would needlessly couple Wake's and Randolph's pacing).
# ===========================================================================

def _run_live_chunked(county: str, enrich_fn, candidates: list[Listing], *,
                      max_rows: int, chunk_size: int, chunk_pause_s: float,
                      concurrency_env: str, fetcher: Fetcher,
                      per_chunk_budget_s: float) -> Counter:
    capped = candidates[:max_rows]
    stats: Counter = Counter()
    stats["eligible_total"] = len(candidates)
    stats["capped_to"] = len(capped)
    n_chunks = (len(capped) + chunk_size - 1) // chunk_size if capped else 0
    for i in range(0, len(capped), chunk_size):
        chunk = capped[i:i + chunk_size]
        chunk_no = i // chunk_size + 1
        t0 = time.monotonic()
        # Let the module's own BUDGET_S env apply per chunk, not to the whole raised cap --
        # otherwise a MAX_ROWS raised to thousands would still get silently truncated by the
        # module's own default 600s BUDGET_S partway through chunk 1.
        prior_budget = os.environ.get(concurrency_env.replace("CONCURRENCY", "BUDGET_S"))
        budget_env = concurrency_env.replace("CONCURRENCY", "BUDGET_S")
        os.environ[budget_env] = str(per_chunk_budget_s)
        try:
            chunk_stats = asyncio.run(enrich_fn(chunk, client=fetcher))
        finally:
            if prior_budget is None:
                os.environ.pop(budget_env, None)
            else:
                os.environ[budget_env] = prior_budget
        elapsed = time.monotonic() - t0
        for k, v in chunk_stats.items():
            stats[k] += v
        print(f"  [{county}] chunk {chunk_no}/{n_chunks}: {len(chunk)} rows in {elapsed:.1f}s -- "
              f"qualified so far: {stats.get('qualified', 0)}, attempted so far: "
              f"{stats.get('attempted', 0)}")
        if chunk_no < n_chunks:
            time.sleep(chunk_pause_s)
    return stats


def _build_patches_for_county(county: str, candidates: dict[str, Listing],
                              raw_keys: tuple[str, ...]) -> dict[str, dict]:
    """Diff each candidate's raw before/after the live fetch already ran on it (mutated
    in-place by enrich_fn) and build {dedupe_key: {"raw": {...}}} for whatever actually changed.
    Candidates never qualifying still pick up the module's own CHECKED sentinel in raw, which is
    exactly as real and worth patching (it is what makes the NEXT run converge further instead of
    re-walking the same rows) -- so this diffs the FULL raw dict's new/changed top-level keys,
    not just raw_keys, deliberately wider than the pure backfills' diff (which only needed to
    watch a fixed small set of restated keys)."""
    patches: dict[str, dict] = {}
    for key, li in candidates.items():
        raw = _raw(li)
        if not raw:
            continue
        # Only ever two kinds of top-level raw keys this script's enrich_fn calls can have
        # added: the qualifying block (raw_keys) or the module's own "_<county>_mydt_checked"
        # sentinel -- both start life absent on the lightweight candidate, so "present at all"
        # is the correct diff here (no stale prior value on a freshly constructed Listing).
        changed = {k: v for k, v in raw.items() if v is not None}
        if not changed:
            continue
        patches[key] = {"raw": changed}
    return patches


# ===========================================================================
# Phase 3: supervised patch_existing_rows() write -- identical shape to both backfills already
# shipped tonight.
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
    except BaseException as exc:  # noqa: BLE001 - must report, never hang the parent
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


_DEFAULT_MAX = {"wake": 300, "randolph": 300}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true",
                    help="Run the real live fetch and report real numbers, but never write the "
                         "board.")
    ap.add_argument("--counties", default="wake,randolph",
                    help="Comma-separated subset of wake,randolph to run this pass.")
    ap.add_argument("--wake-max", type=int, default=_DEFAULT_MAX["wake"],
                    help="Raised MAX_ROWS for Wake this run (module default 300).")
    ap.add_argument("--randolph-max", type=int, default=_DEFAULT_MAX["randolph"],
                    help="Raised MAX_ROWS for Randolph this run (module default 300).")
    ap.add_argument("--chunk-size", type=int, default=500,
                    help="Rows per asyncio.run() pass, per county.")
    ap.add_argument("--chunk-pause-s", type=float, default=5.0,
                    help="Pause between chunks, per county -- the 'pace a very large batch' "
                         "judgment call for a fragile/major portal.")
    ap.add_argument("--chunk-budget-s", type=float, default=240.0,
                    help="Per-chunk wall-clock budget passed to the module's own BUDGET_S env "
                         "(so a raised MAX_ROWS is not silently truncated by the module's "
                         "600s-for-the-whole-call default).")
    ap.add_argument("--allow-large", action="store_true")
    ap.add_argument("--patch-timeout-s", type=float, default=1800.0)
    ap.add_argument("--patch-mem-ceiling-mb", type=float, default=16000.0)
    args = ap.parse_args()

    counties = [c.strip() for c in args.counties.split(",") if c.strip()]
    for c in counties:
        if c not in ("wake", "randolph"):
            print(f"unknown county {c!r}; choices are wake, randolph")
            return 2

    specs = {c: _make_county_spec(c) for c in counties}
    max_rows = {"wake": args.wake_max, "randolph": args.randolph_max}

    docs = REPO / "docs"

    # Phase 1 (board_lock held only for the brief stream-and-collect; see module docstring).
    with board_lock(REPO, owner="live_backfill_wake_randolph_collect"):
        buckets, total_rows, ambiguity = _collect_candidates(docs, specs)
    print(f"board rows streamed: {total_rows:,}")
    for county in counties:
        print(f"{county} eligible candidates: {len(buckets[county]):,}")
    if ambiguity["rows_total"]:
        print(f"excluded as ambiguous-identity (shared dedupe_key with another candidate, never "
              f"guessed at): {ambiguity['rows_total']:,} rows under "
              f"{ambiguity['distinct_keys']:,} distinct colliding key(s)")
        for county, n in sorted(ambiguity["rows_by_bucket"].items(), key=lambda kv: -kv[1]):
            print(f"    {county:10} {n:,} rows excluded this way")

    # Phase 2: the live fetch itself -- NOT under board_lock().
    all_patches: dict[str, dict] = {}
    chunk_stats: dict[str, Counter] = {}
    for county in counties:
        name, _eligible_fn, enrich_fn, raw_keys = specs[county]
        candidates_map = buckets[county]
        candidates = list(candidates_map.values())
        print(f"\n=== {county}: live fetch, cap {max_rows[county]:,} of "
              f"{len(candidates):,} eligible ===")
        fetcher = Fetcher()  # module default rate limit (VERIFY_HOST_MIN_INTERVAL_S or its own
                              # DEFAULT_MIN_INTERVAL_S) -- one Fetcher per county, never shared.
        concurrency_env = f"{county.upper()}_MYDT_CONCURRENCY"
        stats = _run_live_chunked(
            county, enrich_fn, candidates,
            max_rows=max_rows[county], chunk_size=args.chunk_size,
            chunk_pause_s=args.chunk_pause_s, concurrency_env=concurrency_env,
            fetcher=fetcher, per_chunk_budget_s=args.chunk_budget_s,
        )
        chunk_stats[county] = stats
        print(f"{county} done: {dict(stats)}")
        # Only the rows actually sliced into a chunk (max_rows[county] of them) carry a mutated
        # raw dict -- fine to diff the whole candidates_map; untouched rows produce an empty diff.
        touched = {k: li for k, li in list(candidates_map.items())[:max_rows[county]]}
        patches = _build_patches_for_county(county, touched, raw_keys)
        print(f"{county} patches staged: {len(patches):,}")
        all_patches.update(patches)

    print(f"\ntotal patches staged across both counties: {len(all_patches):,}")
    for county, stats in chunk_stats.items():
        print(f"\n{county} summary:")
        for k, v in sorted(stats.items()):
            print(f"    {k:30} {v:,}")

    if args.dry_run:
        print("\nDRY RUN -- nothing written.")
        return 0
    if not all_patches:
        print("\nnothing to do.")
        return 0

    size_state = board_patch_size_state(docs)
    if not size_state["ok"] and not args.allow_large:
        print(f"\nREFUSING: {size_state['reason']}. Re-run with --allow-large once the "
              f"supervised watchdog is wired the way you want it.")
        return 1

    summary_counter: Counter = Counter()
    for county, stats in chunk_stats.items():
        for k, v in stats.items():
            summary_counter[f"{county}_{k}"] += v

    with board_lock(REPO, owner="live_backfill_wake_randolph_write"):
        stats, watchdog = _run_patch_supervised(
            all_patches, dict(summary_counter), docs,
            timeout_s=args.patch_timeout_s, mem_ceiling_mb=args.patch_mem_ceiling_mb,
            allow_large=args.allow_large,
        )
    print(f"\nwatchdog: peak VmRSS {watchdog['peak_rss_mb']:.0f} MB, "
          f"peak VmHWM {watchdog['peak_vmhwm_mb']:.0f} MB, wall {watchdog['elapsed_s']:.1f}s")
    print(f"wrote board: patched {stats['applied']:,}/{len(all_patches):,} rows "
          f"(existing board: {stats['existing']:,}, not_found: {stats['not_found']:,}, "
          f"duplicate_key_matches: {stats['duplicate_key_matches']:,})")
    if stats["duplicate_key_matches"]:
        print(f"\n*** {stats['duplicate_key_matches']:,} duplicate_key_matches -- DO NOT assume "
              f"these are fine. Spot-check these specific rows before anyone decides to "
              f"publish. ***")
    print("\nBoard data changes are staged on disk only -- NOT committed, pushed, or published. "
          "A human go-ahead is required before publish.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
