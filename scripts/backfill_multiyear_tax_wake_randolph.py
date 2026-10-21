#!/usr/bin/env python3
"""One-time backfill: land Wake NC and Randolph NC's new, LIVE multi-year-tax enrichments
(enrichment_wake_multiyear_tax.py / enrichment_randolph_multiyear_tax.py, commits 60a4f051 /
fd70041b, 2026-10-18) onto the already-published board.

WHY THIS IS A SEPARATE SCRIPT FROM backfill_multiyear_tax_restatement.py. That script's three
enrichments (qpaybill/ptscloud/its_public) are PURE, no-network restatements of a source block
the row already carries -- cheap, safe to run over all eligible rows in one pass. Wake and
Randolph's enrichments are a DIFFERENT shape: a LIVE per-parcel fetch against services.wake.gov /
txpwa.randolphcountync.gov, one row at a time, which is why each module ships its own built-in
pacing (WAKE_MYDT_MAX / RANDOLPH_MYDT_MAX = 300 rows per call, CONCURRENCY = 4, a 600s wall-clock
budget per call) -- designed to be invoked repeatedly across pipeline runs, not once over the
whole eligible set. This runner calls each module's real `enrich_with_*` function, UNMODIFIED,
in a loop over its own already-collected candidates (each call naturally picks the next 300
not-yet-checked rows, since the prior call's CHECKED_KEY/RAW_KEY writes are already on the
in-memory Listings) -- same "run the real production function, don't reimplement it" discipline
as every backfill before this one.

DELIBERATE PACING (rule: respect per-portal rate limits; this project has a documented history of
a county site rate-limiting after a burst -- see project_sweep_county_silent_investigated). Wake
has ~12,941 eligible rows, Randolph fewer; a full sweep is 40+ batches of 300. Neither county's
ptax/billing portal has been run at this volume before by this project. --max-batches bounds how
many 300-row batches this invocation will run per county (default 5 = 1,500 rows, a measured
pilot, not the full sweep) so a first run is a deliberate, small, real test rather than an
unbounded 13,000-request burst. Raise it on a later invocation once this run's error rate/latency
say the portal tolerates it. CONCURRENCY/MAX_ROWS/BUDGET_S are left at each module's own env-var
defaults (not raised) -- this script does not override them.

BOARD I/O, same discipline as every backfill tonight. Phase 1 streams the board once via
board_stream.iter_board_rows(), keeping only NC Wake / NC Randolph rows not already carrying
multi_year_delinquent_tax or a _*_mydt_checked marker, as lightweight Listings (_APPEND_SIG_FIELDS
+ raw). Phase 2 runs each county's real enrich_with_*_multiyear_tax() in a batch loop, in-memory,
no board writes yet. Phase 3 diffs each candidate's raw (multi_year_delinquent_tax +
_wake_mydt_checked / _randolph_mydt_checked) before/after, builds patches (same ambiguous-
dedupe_key exclusion safety net as every prior backfill), and lands them with ONE
patch_existing_rows() call under board_lock(), via the same supervised dual-signal watchdog.

PHASE 2.5 ADDED 2026-10-21 -- the missing downstream half of the SAME chain this module's own
commit message promised ("feeds tax_aging_surfaced for free via the existing enrich_tax_owed/
enrich_tax_aging chain"). Live-checked against the board: the ONE Wake row the 2026-10-19 pilot
run already qualified (PIN 1713488099, 4 matured years, $65.03 total) carries
raw['multi_year_delinquent_tax'] but raw['tax_owed'] and raw['tax_aging_surfaced'] are BOTH still
None -- the prior runs of this script (and run_live_backfill_wake_randolph.py) only ever called
enrich_with_wake_multiyear_tax/enrich_with_randolph_multiyear_tax and patched THAT one key; nothing
afterward ever re-ran enrichment_tax_owed.enrich_tax_owed() / enrichment_tax_aging.enrich_tax_aging()
over these same already-patched rows to let the existing, generic, PURE (no-network)
_SOURCES["multi_year_delinquent_tax"] mapping actually derive tax_owed/tax_aging_surfaced from it.
Confirmed by direct call: eto.enrich_tax_owed([that one Listing]) stamps a real tax_owed block
from its own already-present multi_year_delinquent_tax data with zero network I/O, and
eta.enrich_tax_aging() then surfaces tax_aging_surfaced/tax_aging_high from THAT in the same pure
pass. Phase 2.5 runs both of those exact, unmodified, generic functions over this run's own Wake/
Randolph candidate list (the same in-memory Listings Phase 2 already touched -- no new board read,
no network call) so every multi_year_delinquent_tax hit this run lands (old pilot rows carried
over as candidates that already qualified, plus any new ones from this run's batches) also closes
its own tax_aging_surfaced cell in the same write. This does NOT touch the OTHER ~12,939 Wake /
6,043 Randolph rows that never qualify for multi_year_delinquent_tax at all -- those still show
"checked=0" for tax_aging_surfaced because they generate no raw['tax_owed'] year data under any
producer this project has for Wake/Randolph (the structural reason the realistic ceiling here is
far below the gap matrix's raw applicable count; see the dry-run output's own qualified-vs-eligible
ratio for the real, measured rate before taking the applicable count at face value).

Usage:
    python scripts/backfill_multiyear_tax_wake_randolph.py --dry-run
    python scripts/backfill_multiyear_tax_wake_randolph.py --dry-run --max-batches 2
    python scripts/backfill_multiyear_tax_wake_randolph.py --allow-large --max-batches 5
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
from foreclosure_scraper.enrichment_randolph_multiyear_tax import (  # noqa: E402
    CHECKED_KEY as RANDOLPH_CHECKED_KEY, RAW_KEY as RANDOLPH_RAW_KEY,
    enrich_with_randolph_multiyear_tax,
)
from foreclosure_scraper.enrichment_wake_multiyear_tax import (  # noqa: E402
    CHECKED_KEY as WAKE_CHECKED_KEY, RAW_KEY as WAKE_RAW_KEY,
    enrich_with_wake_multiyear_tax,
)
from foreclosure_scraper.enrichment_tax_aging import enrich_tax_aging  # noqa: E402
from foreclosure_scraper.enrichment_tax_owed import enrich_tax_owed  # noqa: E402
from foreclosure_scraper.models import Listing  # noqa: E402
from foreclosure_scraper.web_artifact import (  # noqa: E402
    _APPEND_SIG_FIELDS, board_lock, board_patch_size_state, patch_existing_rows,
)

_LIGHT_FIELDS = _APPEND_SIG_FIELDS + ("raw",)

# (county title-case, enrich_fn, raw_key, checked_key)
_COUNTIES = [
    ("Wake", enrich_with_wake_multiyear_tax, WAKE_RAW_KEY, WAKE_CHECKED_KEY),
    ("Randolph", enrich_with_randolph_multiyear_tax, RANDOLPH_RAW_KEY, RANDOLPH_CHECKED_KEY),
]
_TARGET_COUNTIES = {c for c, *_ in _COUNTIES}
_WATCH_KEYS = (WAKE_RAW_KEY, WAKE_CHECKED_KEY, RANDOLPH_CHECKED_KEY,
              # Phase 2.5 (2026-10-21): the downstream keys enrich_tax_owed/enrich_tax_aging
              # derive from a qualifying multi_year_delinquent_tax hit -- watched here too so a
              # qualifying row's tax_aging_surfaced/tax_owed stamp lands in the SAME patch.
              "tax_owed", "tax_aging_surfaced", "tax_aging_high",
              # 2026-10-21: enrichment_randolph_multiyear_tax.py now also writes
              # raw['two_year_delinquent'] unconditionally off the same live fetch (see that
              # module's TYD_RAW_KEY docstring) -- watched so it lands in the same patch.
              "two_year_delinquent")  # RAW_KEY shared by both


def _light(rec: dict) -> Listing:
    return Listing.model_construct(**{k: rec.get(k) for k in _LIGHT_FIELDS})


def _already_checked(raw: Any, raw_key: str, checked_key: str) -> bool:
    if not isinstance(raw, dict):
        return False
    return isinstance(raw.get(raw_key), dict) or bool(raw.get(checked_key))


# ===========================================================================
# Phase 1
# ===========================================================================

def _collect_candidates(
    docs: Path,
) -> tuple[dict[str, dict[str, Listing]], dict[str, dict[str, Listing]], int, int]:
    """{county: {dedupe_key: light_listing}} of live-fetch-eligible rows (not yet checked),
    PLUS a second {county: {dedupe_key: light_listing}} of rows that ALREADY qualified for
    multi_year_delinquent_tax on some prior run (so Phase 1's own `_already_checked` filter
    excludes them from the live-fetch set above) but may still be missing the downstream
    tax_owed/tax_aging_surfaced restatement Phase 2.5 adds -- same single board stream, one
    extra dict-is-RAW_KEY-dict check per Wake/Randolph row, no second pass. Also returns total
    rows streamed and the ambiguous-identity count excluded from the live-fetch set (shared
    dedupe_key with another candidate in the SAME county)."""
    by_county: dict[str, dict[str, Listing]] = {c: {} for c in _TARGET_COUNTIES}
    prior_qualified: dict[str, dict[str, Listing]] = {c: {} for c in _TARGET_COUNTIES}
    seen: dict[tuple[str, str], int] = {}
    prior_seen: dict[tuple[str, str], int] = {}
    total = 0
    raw_key_checked_key = {"Wake": (WAKE_RAW_KEY, WAKE_CHECKED_KEY),
                           "Randolph": (RANDOLPH_RAW_KEY, RANDOLPH_CHECKED_KEY)}
    for rec in iter_board_rows(docs / "listings.json.gz"):
        total += 1
        if str(rec.get("state") or "").upper() != "NC":
            continue
        county = (rec.get("county") or "").replace(" County", "").strip().title()
        if county not in _TARGET_COUNTIES:
            continue
        if not str(rec.get("parcel_id") or "").strip():
            continue
        raw_key, checked_key = raw_key_checked_key[county]
        raw = rec.get("raw")
        if _already_checked(raw, raw_key, checked_key):
            if isinstance(raw, dict) and isinstance(raw.get(raw_key), dict):
                li = _light(rec)
                try:
                    pkey = li.dedupe_key()
                except Exception:  # noqa: BLE001
                    continue
                prior_seen[(county, pkey)] = prior_seen.get((county, pkey), 0) + 1
                prior_qualified[county][pkey] = li
            continue
        li = _light(rec)
        try:
            key = li.dedupe_key()
        except Exception:  # noqa: BLE001
            continue
        seen[(county, key)] = seen.get((county, key), 0) + 1
        by_county[county][key] = li
    ambiguous = 0
    for (county, key), n in seen.items():
        if n > 1:
            by_county[county].pop(key, None)
            ambiguous += 1
    for (county, key), n in prior_seen.items():
        if n > 1:
            prior_qualified[county].pop(key, None)
            ambiguous += 1
    return by_county, prior_qualified, total, ambiguous


# ===========================================================================
# Phase 2: batch loop over each county's REAL enrich_with_* function, unmodified.
# ===========================================================================

async def _run_county_batches(county: str, enrich_fn, candidates: dict[str, Listing],
                              max_batches: int) -> list[dict]:
    listings = list(candidates.values())
    batch_stats: list[dict] = []
    for i in range(max_batches):
        remaining = sum(1 for li in listings
                        if not _already_checked(li.raw,
                                                 *(WAKE_RAW_KEY, WAKE_CHECKED_KEY) if county == "Wake"
                                                 else (RANDOLPH_RAW_KEY, RANDOLPH_CHECKED_KEY)))
        if remaining == 0:
            break
        t0 = time.monotonic()
        stats = await enrich_fn(listings)
        stats["batch"] = i + 1
        stats["elapsed_s"] = round(time.monotonic() - t0, 1)
        stats["remaining_before_batch"] = remaining
        print(f"  {county} batch {i + 1}: {stats}")
        batch_stats.append(stats)
        if stats.get("attempted", 0) == 0:
            break  # nothing left this module considers eligible
    return batch_stats


def _build_patches(by_county: dict[str, dict[str, Listing]],
                   before_by_county: dict[str, dict[str, dict]]) -> dict[str, dict]:
    patches: dict[str, dict] = {}
    for county, candidates in by_county.items():
        before = before_by_county[county]
        for key, li in candidates.items():
            after_raw = li.raw if isinstance(li.raw, dict) else {}
            b = before[key]
            raw_patch = {k: after_raw.get(k) for k in _WATCH_KEYS if after_raw.get(k) != b.get(k)}
            if raw_patch:
                patches[key] = {"raw": raw_patch}
    return patches


# ===========================================================================
# Phase 3: supervised patch_existing_rows() -- copied verbatim from the established harness.
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
    ap.add_argument("--max-batches", type=int, default=5,
                    help="Batches of up to 300 rows PER COUNTY this invocation will run. "
                         "Default 5 (1,500 rows/county) -- a measured pilot, not the full sweep. "
                         "Re-run with a higher value, or run again, once this is confirmed safe.")
    ap.add_argument("--patch-timeout-s", type=float, default=1200.0)
    ap.add_argument("--patch-mem-ceiling-mb", type=float, default=16000.0)
    args = ap.parse_args()

    docs = REPO / "docs"

    lock = contextlib.nullcontext() if args.dry_run else board_lock(REPO, owner="wake_randolph_mydt_backfill")
    with lock:
        by_county, prior_qualified, total_rows, ambiguous = _collect_candidates(docs)
        print(f"board rows streamed: {total_rows:,}")
        for county, cands in by_county.items():
            print(f"{county} NC eligible candidates (live fetch): {len(cands):,}")
        for county, cands in prior_qualified.items():
            print(f"{county} NC already-qualified-but-not-yet-aged (Phase 2.5 only, no live "
                  f"fetch): {len(cands):,}")
        if ambiguous:
            print(f"excluded as ambiguous-identity (shared dedupe_key with another "
                  f"candidate, never guessed at): {ambiguous:,}")

        before_by_county = {
            county: {key: dict(li.raw) if isinstance(li.raw, dict) else {}
                    for key, li in cands.items()}
            for county, cands in by_county.items()
        }
        before_prior_qualified = {
            county: {key: dict(li.raw) if isinstance(li.raw, dict) else {}
                    for key, li in cands.items()}
            for county, cands in prior_qualified.items()
        }

        all_batch_stats: dict[str, list[dict]] = {}
        for county, enrich_fn, _rk, _ck in _COUNTIES:
            cands = by_county[county]
            if not cands:
                continue
            print(f"\n=== {county} NC: running real enrich_with_* in batches ===")
            all_batch_stats[county] = asyncio.run(
                _run_county_batches(county, enrich_fn, cands, args.max_batches))

        # Phase 2.5: the missing downstream half (module docstring above). PURE, no network --
        # enrich_tax_owed/enrich_tax_aging are the project's own generic, idempotent producers;
        # run verbatim, unmodified, over every Wake/Randolph Listing this invocation touched
        # (this run's own live-fetch candidates, qualifying or not) PLUS every row that already
        # qualified on a PRIOR run and was never carried through this chain. A row with no
        # multi_year_delinquent_tax block (the overwhelming majority) is untouched by both calls,
        # same as every other row on the board they already run over every pipeline cycle.
        aging_listings = [li for cands in by_county.values() for li in cands.values()]
        aging_listings += [li for cands in prior_qualified.values() for li in cands.values()]
        owed_stats = enrich_tax_owed(aging_listings)
        aging_stats = enrich_tax_aging(aging_listings)
        print(f"\n=== Phase 2.5: enrich_tax_owed + enrich_tax_aging over "
              f"{len(aging_listings):,} Wake/Randolph candidates ===")
        print(f"  enrich_tax_owed: {owed_stats}")
        print(f"  enrich_tax_aging: {aging_stats}")

        patches = _build_patches(by_county, before_by_county)
        prior_patches = _build_patches(prior_qualified, before_prior_qualified)
        collision = set(patches) & set(prior_patches)
        if collision:
            print(f"\nWARNING: {len(collision)} dedupe_key(s) appear in both the live-fetch and "
                  f"prior-qualified patch sets -- keeping the live-fetch version for each, never "
                  f"guessed at.")
            for k in collision:
                prior_patches.pop(k, None)
        patches.update(prior_patches)
        print(f"\npatches staged: {len(patches):,}")
        by_kind = {"qualified": 0, "checked_no_qualify": 0, "aging_only": 0}
        for p in patches.values():
            r = p["raw"]
            if r.get(WAKE_RAW_KEY) is not None:
                by_kind["qualified"] += 1
            elif r.get(WAKE_CHECKED_KEY) is not None or r.get(RANDOLPH_CHECKED_KEY) is not None:
                by_kind["checked_no_qualify"] += 1
            else:
                by_kind["aging_only"] += 1
        print(f"    qualified (multi_year_delinquent_tax written): {by_kind['qualified']:,}")
        print(f"    checked, did not qualify (sentinel only):      {by_kind['checked_no_qualify']:,}")
        print(f"    tax_owed/tax_aging_surfaced only (prior-qualified restatement): "
              f"{by_kind['aging_only']:,}")

        if args.dry_run:
            print("\nDRY RUN -- nothing written. (Note: the enrich_with_* calls above still hit "
                  "the real live portals -- these modules have no network-free dry-run mode; "
                  "--dry-run here only controls whether the result is WRITTEN to the board.)")
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
