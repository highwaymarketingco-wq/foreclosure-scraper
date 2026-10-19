#!/usr/bin/env python3
"""One-time backfill: land the 3 new, PURE, no-network two_year_delinquent restatement
enrichments (gap-matrix sweep, 2026-10-19) onto the ALREADY-PUBLISHED board, without a full
pipeline run.

enrichment_ptscloud_two_year_delinquent.py (NC PTS Cloud / Farragut BillPWA, bcpwa.ncptscloud.com
-- Guilford/Beaufort/Orange/Madison tenants), enrichment_berkeley_two_year_delinquent.py (SC
Berkeley, paystar.io) and enrichment_dorchester_two_year_delinquent.py (SC Dorchester,
billtrax.com) are all already wired into main.py for FUTURE runs. None of them touch the network
or re-derive anything new: each walks a row's OWN already-fetched source block
(raw['nc_ptscloud_delinquent_tax'] / raw['berkeley_paystar_tax'] /
raw['billtrax_dorchester_delinquent_tax']) and restates its already-computed two-year-delinquency
signal under the one shared contract key gap_matrix.py actually reads
(raw['two_year_delinquent']). Nothing published before tonight carries that key from any of
these three sources, so every row they qualify is currently a false "sourced-not-built"
gap-matrix miss (docs/gap_matrix/gap_list_2026-10-19.csv, column==two_year_delinquent AND
gap_class==sourced-not-built: NC Guilford 12,276 / Beaufort 4,281 / Orange 3,046 / Madison 1,704,
SC Berkeley 3,012, SC Dorchester 1,817).

Same shape as scripts/backfill_multiyear_tax_restatement.py (read that script's own docstring for
the full discipline this reuses, including its live-measured "distinct ambiguous keys can
understate real row-level impact" gotcha, which applies here too for the same ptscloud
ambiguous-dedupe_key reason):
  * Phase 1 streams the published board exactly once via board_stream.iter_board_rows() (never
    load_board()). A cheap dict-level pre-filter (does this row's raw even carry one of the three
    source keys, as a dict, at all?) runs before paying for a Listing.model_construct().
  * Each candidate is bucketed by WHICH of the three source keys it carries. The three source
    keys are mutually exclusive by construction (different scrapers, different state/county
    coverage); asserted live via `multi_source_conflict` the same way the sibling script does.
  * Each bucket is then run through its REAL production enrichment function
    (enrich_ptscloud_two_year_delinquent / enrich_berkeley_two_year_delinquent /
    enrich_dorchester_two_year_delinquent), unmodified, over its own list of lightweight Listings
    -- guarantees byte-identical output to a real pipeline run, and reuses each module's own
    idempotent `_already_done()` gate for free. Unlike the sibling multiyear backfill (whose three
    buckets each write a DIFFERENT raw key), all three buckets here write the SAME raw key
    (`two_year_delinquent`) -- the diff-before/after in _build_patches() below is keyed on that one
    field name shared across buckets, not a per-bucket key list.
  * Same ambiguous-shared-identity-key exclusion safety net, same dual-watchdog supervised write,
    same --dry-run / --allow-large flags.

Usage:
    python scripts/backfill_two_year_delinquent_restatement.py --dry-run
    python scripts/backfill_two_year_delinquent_restatement.py --allow-large
"""
from __future__ import annotations

import argparse
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
from foreclosure_scraper.enrichment_berkeley_two_year_delinquent import (  # noqa: E402
    enrich_berkeley_two_year_delinquent,
    SOURCE_KEY as BERKELEY_SOURCE_KEY,
)
from foreclosure_scraper.enrichment_dorchester_two_year_delinquent import (  # noqa: E402
    enrich_dorchester_two_year_delinquent,
    SOURCE_KEY as DORCHESTER_SOURCE_KEY,
)
from foreclosure_scraper.enrichment_ptscloud_two_year_delinquent import (  # noqa: E402
    enrich_ptscloud_two_year_delinquent,
    SOURCE_KEY as PTSCLOUD_SOURCE_KEY,
)
from foreclosure_scraper.models import Listing  # noqa: E402
from foreclosure_scraper.web_artifact import (  # noqa: E402
    _APPEND_SIG_FIELDS, board_lock, board_patch_size_state, patch_existing_rows,
)

RAW_KEY = "two_year_delinquent"

#: identity + raw fields enough to build a lightweight, UNVALIDATED Listing for the three
#: enrichment functions (they only read li.raw / li.county) and Listing.dedupe_key().
_LIGHT_FIELDS = _APPEND_SIG_FIELDS + ("raw",)

#: one bucket per source family: (source_key_in_raw, enrich_fn).
_BUCKETS: dict[str, tuple[str, Any]] = {
    "ptscloud": (PTSCLOUD_SOURCE_KEY, enrich_ptscloud_two_year_delinquent),
    "berkeley": (BERKELEY_SOURCE_KEY, enrich_berkeley_two_year_delinquent),
    "dorchester": (DORCHESTER_SOURCE_KEY, enrich_dorchester_two_year_delinquent),
}


def _light(rec: dict) -> Listing:
    return Listing.model_construct(**{k: rec.get(k) for k in _LIGHT_FIELDS})


def _raw(li: Any) -> dict:
    r = getattr(li, "raw", None)
    return r if isinstance(r, dict) else {}


def _source_keys_present(raw: dict) -> list[str]:
    """Which of the three bucket names this row's raw dict carries a dict-shaped source block
    for -- normally exactly one; see this module's docstring on mutual exclusivity."""
    return [name for name, (source_key, _fn) in _BUCKETS.items()
            if isinstance(raw.get(source_key), dict)]


# ===========================================================================
# Phase 1: stream the board once, bucket candidates -- never load_board().
# ===========================================================================

def _collect_candidates_from_rows(rows) -> tuple[dict[str, dict[str, Listing]], int, int, dict]:
    """({bucket_name: {dedupe_key: light_listing}}, total rows seen, multi_source_conflict rows
    excluded, ambiguity report dict). Same "skip and count, never guess" discipline as
    backfill_multiyear_tax_restatement.py's own _collect_candidates_from_rows()."""
    buckets: dict[str, dict[str, Listing]] = {name: {} for name in _BUCKETS}
    source_keys = {name: spec[0] for name, spec in _BUCKETS.items()}
    total = 0
    conflicts = 0
    occurrences: dict[str, list[str]] = {}
    for rec in rows:
        total += 1
        raw = rec.get("raw")
        if not isinstance(raw, dict):
            continue
        if not any(isinstance(raw.get(sk), dict) for sk in source_keys.values()):
            continue
        present = _source_keys_present(raw)
        if len(present) > 1:
            conflicts += 1
            continue
        bucket = present[0]
        li = _light(rec)
        try:
            key = li.dedupe_key()
        except Exception:  # noqa: BLE001 - a row too malformed to key is simply unpatchable
            continue
        occurrences.setdefault(key, []).append(bucket)
        buckets[bucket][key] = li

    ambiguous_keys = {k for k, buckets_hit in occurrences.items() if len(buckets_hit) > 1}
    rows_by_bucket: Counter = Counter()
    for key in ambiguous_keys:
        for bucket_map in buckets.values():
            bucket_map.pop(key, None)
        for bucket in occurrences[key]:
            rows_by_bucket[bucket] += 1
    ambiguity_report = {
        "distinct_keys": len(ambiguous_keys),
        "rows_total": sum(rows_by_bucket.values()),
        "rows_by_bucket": dict(rows_by_bucket),
    }
    return buckets, total, conflicts, ambiguity_report


def _collect_candidates(docs: Path) -> tuple[dict[str, dict[str, Listing]], int, int, dict]:
    return _collect_candidates_from_rows(iter_board_rows(docs / "listings.json.gz"))


def _build_patches(buckets: dict[str, dict[str, Listing]], c: Counter) -> dict[str, dict]:
    """Run each bucket through its REAL production enrich_*() function (unmodified, over its own
    list of lightweight Listings) and diff raw[RAW_KEY] before/after -- guarantees byte-identical
    output to what a real pipeline run would have written and reuses each module's own
    idempotent _already_done() gate. All three buckets write the SAME raw key, so a later bucket
    in iteration order simply finds nothing-to-diff on a row an earlier bucket already patched
    (mutually exclusive by source key anyway, per the module docstring)."""
    patches: dict[str, dict] = {}
    for bucket, (_source_key, enrich_fn) in _BUCKETS.items():
        candidates = buckets[bucket]
        before: dict[str, Any] = {key: _raw(li).get(RAW_KEY) for key, li in candidates.items()}
        stats = enrich_fn(list(candidates.values()))
        for k, v in stats.items():
            c[f"{bucket}_{k}"] += v
        for key, li in candidates.items():
            raw = _raw(li)
            after = raw.get(RAW_KEY)
            if after is None or after == before.get(key):
                continue
            patches[key] = {"raw": {RAW_KEY: after}}
            c[f"{bucket}_patched"] += 1
            c[f"{bucket}_patched_county:{li.county}"] += 1
    return patches


# ===========================================================================
# Phase 2: supervised patch_existing_rows() -- reused verbatim from
# backfill_multiyear_tax_restatement.py / backfill_transylvania_rollback_exposure.py (same
# watchdog shape).
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
        REPO, owner="two_year_delinquent_restatement_backfill")
    with lock:
        buckets, total_rows, conflicts, ambiguity = _collect_candidates(docs)
        print(f"board rows streamed: {total_rows:,}")
        for bucket in _BUCKETS:
            print(f"{bucket} candidates: {len(buckets[bucket]):,}")
        if conflicts:
            print(f"multi_source_conflict (row carries >1 source key, excluded from every "
                  f"bucket): {conflicts:,}")

        c: Counter = Counter()
        c["skipped_ambiguous_dedupe_key_distinct"] = ambiguity["distinct_keys"]
        c["skipped_ambiguous_dedupe_key_rows"] = ambiguity["rows_total"]
        if ambiguity["rows_total"]:
            print(f"excluded as ambiguous-identity (shared dedupe_key with another candidate, "
                  f"never guessed at): {ambiguity['rows_total']:,} rows under "
                  f"{ambiguity['distinct_keys']:,} distinct colliding key(s)")
            for bucket, n in sorted(ambiguity["rows_by_bucket"].items(), key=lambda kv: -kv[1]):
                print(f"    {bucket:12} {n:,} rows excluded this way")

        patches = _build_patches(buckets, c)

        print("\nby kind:")
        for k, v in sorted(c.items()):
            if ":" not in k:
                print(f"    {k:40} {v:,}")
        print("\nby county (patched only):")
        for k, v in sorted(c.items()):
            if ":" in k:
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
