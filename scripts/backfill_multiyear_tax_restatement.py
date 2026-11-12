#!/usr/bin/env python3
"""One-time backfill: land the 3 new, PURE, no-network multi-year-tax restatement enrichments
(gap-matrix sweep, 2026-10-18) onto the ALREADY-PUBLISHED board, without a full pipeline run.

enrichment_qpaybill_multiyear_tax.py (SC qPayBill, 29 counties), enrichment_ptscloud_multiyear_tax.py
(NC PTS Cloud / Farragut BillPWA, 9 tenants) and enrichment_its_public_multiyear_tax.py (NC
ITSPublic / BT TaxPayer Portal, 12 counties) are all already wired into main.py for FUTURE runs.
None of them touch the network or re-derive anything: each walks a row's OWN already-fetched
source block (raw['qpaybill_roll'] / raw['nc_ptscloud_delinquent_tax'] / raw['nc_its_public_tax'])
and restates its already-collected multi-year history under the shared contract keys
gap_matrix.py actually reads (raw['multi_year_delinquent_tax'], and for qpaybill only,
raw['two_year_delinquent']). Nothing published today carries those two keys from any of these
three sources, so every row they qualify is currently a false "sourced-not-built" gap-matrix miss.

This is the same situation backfill_deed_ref_bound.py solved for a different gap last night, and
reuses its exact shape:
  * Phase 1 streams the published board exactly once via board_stream.iter_board_rows() (never
    load_board() -- web_artifact.py's own BOARD_LOAD_MAX_SOURCE_MB comment records this board's
    real-footprint cost, and it has already refused outright on the Oracle VM once tonight at
    4,985 MB against a 1,200 MB ceiling). A cheap dict-level pre-filter (does this row's raw even
    carry one of the three source keys, as a dict, at all?) runs before paying for a
    Listing.model_construct() -- only real candidates are ever materialized this way.
  * Each candidate is bucketed by WHICH of the three source keys it carries. The three source
    keys are mutually exclusive by construction (different scrapers, different state/county
    coverage -- SC qPayBill vs two disjoint NC county lists), so a row should never carry more
    than one; this is asserted live (main() counts and reports `multi_source_conflict` -- a row
    carrying more than one source key is excluded from every bucket and reported rather than
    guessed at, exactly the discipline this project's other backfills use for anything
    unconfirmed).
  * Each bucket is then run through the REAL production enrichment function
    (enrich_qpaybill_multiyear_tax / enrich_ptscloud_multiyear_tax / enrich_its_public_multiyear_tax),
    unmodified, over its own list of lightweight Listings -- not a reimplementation of their
    logic. This guarantees the backfill produces byte-identical output to what a real pipeline
    run would have written, and reuses each module's own idempotent _already_done() gate for
    free. A patch is built from whatever raw keys actually changed value (diffed before/after),
    for every candidate whose block the real function actually wrote.
  * Same ambiguous-shared-identity-key exclusion safety net as backfill_deed_ref_bound.py: a
    dedupe_key() seen on more than one candidate (board already has two DIFFERENT rows under one
    identity) is excluded from `patches` entirely rather than guessed at -- unlike
    backfill_deed_ref_bound.py's two mechanisms (which derive their patch value from a specific
    candidate's own content that could legitimately differ sibling-to-sibling), the value here
    IS a property-level fact (this parcel's unpaid-tax history) that should be equally true for
    every row sharing one identity -- but patch_existing_rows()'s own 10/19 duplicate_key_matches
    incident (6/924 patches landed on a sibling via a WEAK, address-only dedupe_key that in fact
    named a different property -- a real collision, not a true duplicate) is exactly why this
    exclusion stays unconditional rather than being narrowed "because this case is different."
  * Same dual-watchdog supervised write for the actual patch_existing_rows() call: an internal
    /proc/<pid>/status-based wall-clock + VmRSS/VmHWM watchdog in THIS script (reused verbatim
    from backfill_deed_ref_bound.py), run underneath the project's own second-layer
    deploy/oracle/mem_watchdog.py on the VM.
  * --dry-run classifies and reports without writing. --allow-large overrides
    BOARD_PATCH_MAX_SOURCE_MB (2,300 MB; this board measured far over that tonight) for one
    supervised run.

SCALE, INVESTIGATED RATHER THAN ASSUMED. patch_existing_rows()'s own docstring states its design
scale as "roughly 1,000-1,500 leads" (scripts/resolver_backfill_parcel.py's case); this backfill
is expected to produce tens of thousands of patches (qpaybill ~8,100 multiyear + ~38,500
two_year_delinquent; ptscloud ~8,600; its_public some fraction of Duplin's 2,900 plus whatever
the other 11 PORTALS counties add) -- 30-50x that design point. Read all the way through
patch_existing_rows()'s streaming loop (web_artifact.py) before writing this script: the per-row
cost inside the one streaming pass is a single dict-literal Listing.model_construct() (identity
fields only) plus an O(1) hash-set membership test against `pending` -- neither depends on
len(patches) beyond the O(1) hash lookup, so there is no quadratic blowup at this scale. The only
things that actually grow with patch count are the `patches`/`pending` dict itself and the
`matched_keys`/`dup_keys` sets -- at ~50,000 small dicts (each a handful of numeric/string/short-
list fields) this is realistically tens of MB, negligible next to the hundreds-of-MB-per-row-
batch streaming cost the function already pays regardless of patch count. The STRICT count guard
(manifest record count must equal the streamed total EXACTLY, not within append_new_rows()'s 10%
shrink tolerance) and the backup-before-overwrite are both independent of patch count too. The one
scale-sensitive number this script DOES watch and report is the ambiguous-dedupe_key exclusion
rate and the duplicate_key_matches count from the real write -- both are reported, never silently
treated as fine (see this module's main() and the task's own spot-check requirement).

Usage:
    python scripts/backfill_multiyear_tax_restatement.py --dry-run
    python scripts/backfill_multiyear_tax_restatement.py --allow-large
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
from foreclosure_scraper.enrichment_its_public_multiyear_tax import (  # noqa: E402
    enrich_its_public_multiyear_tax,
    RAW_KEY as ITS_PUBLIC_RAW_KEY,
    SOURCE_KEY as ITS_PUBLIC_SOURCE_KEY,
)
from foreclosure_scraper.enrichment_ptscloud_multiyear_tax import (  # noqa: E402
    enrich_ptscloud_multiyear_tax,
    RAW_KEY as PTSCLOUD_RAW_KEY,
    SOURCE_KEY as PTSCLOUD_SOURCE_KEY,
)
from foreclosure_scraper.enrichment_qpaybill_multiyear_tax import (  # noqa: E402
    enrich_qpaybill_multiyear_tax,
    MYDT_KEY as QPAYBILL_MYDT_KEY,
    SOURCE_KEY as QPAYBILL_SOURCE_KEY,
    TYD_KEY as QPAYBILL_TYD_KEY,
)
from foreclosure_scraper.models import Listing  # noqa: E402
from foreclosure_scraper.web_artifact import (  # noqa: E402
    _APPEND_SIG_FIELDS, board_lock, board_patch_size_state, patch_existing_rows,
)

#: identity + raw fields enough to build a lightweight, UNVALIDATED Listing for the three
#: enrichment functions (they only read li.raw / li.parcel_id / li.state / li.county) and
#: Listing.dedupe_key() -- append_new_rows()'s/patch_existing_rows()'s own model_construct()
#: trick, reused here for the same reason: it avoids Listing.model_validate()'s cost over rows
#: that are not even candidates.
_LIGHT_FIELDS = _APPEND_SIG_FIELDS + ("raw",)

#: one bucket per source family: (source_key_in_raw, enrich_fn, [raw keys it may write]).
_BUCKETS: dict[str, tuple[str, Any, tuple[str, ...]]] = {
    "qpaybill": (QPAYBILL_SOURCE_KEY, enrich_qpaybill_multiyear_tax,
                 (QPAYBILL_TYD_KEY, QPAYBILL_MYDT_KEY)),
    "ptscloud": (PTSCLOUD_SOURCE_KEY, enrich_ptscloud_multiyear_tax, (PTSCLOUD_RAW_KEY,)),
    "its_public": (ITS_PUBLIC_SOURCE_KEY, enrich_its_public_multiyear_tax, (ITS_PUBLIC_RAW_KEY,)),
}


def _light(rec: dict) -> Listing:
    return Listing.model_construct(**{k: rec.get(k) for k in _LIGHT_FIELDS})


def _raw(li: Any) -> dict:
    r = getattr(li, "raw", None)
    return r if isinstance(r, dict) else {}


def _source_keys_present(raw: dict) -> list[str]:
    """Which of the three bucket names this row's raw dict carries a dict-shaped source block
    for -- normally exactly one; see this module's docstring on mutual exclusivity."""
    return [name for name, (source_key, _fn, _keys) in _BUCKETS.items()
            if isinstance(raw.get(source_key), dict)]


# ===========================================================================
# Phase 1: stream the board once, bucket candidates -- never load_board().
# ===========================================================================

def _collect_candidates_from_rows(rows) -> tuple[dict[str, dict[str, Listing]], int, int, dict]:
    """The actual Phase-1 logic, over any iterable of board-shaped dicts -- split out from
    _collect_candidates() so it is unit-testable against synthetic fixtures without touching
    board_stream.iter_board_rows() or a real board file. Returns ({bucket_name:
    {dedupe_key: light_listing}}, total rows seen, multi_source_conflict rows excluded,
    ambiguity report dict -- see below).

    Ambiguity is tracked across ALL buckets together (patches are issued keyed by dedupe_key()
    globally, not per bucket) -- same "skip and count, never guess" discipline
    backfill_deed_ref_bound.py's _collect_candidates() uses: a dedupe_key seen on more than one
    candidate means the board already has (at least) two rows sharing one identity, and
    patch_existing_rows() applies whichever ONE patch gets built under that key to EVERY matching
    row -- correct when the two rows truly are the same property, but patch_existing_rows()'s own
    2026-10-19 duplicate_key_matches incident (6/924 patches landed on an unrelated sibling via a
    weak address-only dedupe_key that in fact named a different property) is exactly why this
    stays unconditional.

    REPORTING GOTCHA FOUND WHILE BUILDING THIS (live-verified against the real board, not
    assumed): counting DISTINCT ambiguous keys badly understates the real row-level impact when
    many rows collapse onto the SAME weak fallback key. Concretely, ~10,618 of the 20,077 board
    rows carrying raw['nc_ptscloud_delinquent_tax'] have no top-level parcel_id/street_address/
    case_number at all and share one literal source_url (the bare tenant-less portal root,
    "https://bcpwa.ncptscloud.com/") -- dedupe_key()'s own documented fallback order collapses
    every one of them onto the SAME single key, "url:https://bcpwa.ncptscloud.com/". That is ONE
    distinct ambiguous key, but it correctly excludes ~10,618 real candidate rows (53% of that
    source's eligible population) from this backfill -- the safety net is working exactly as
    intended (none of those rows' genuinely different tax histories get cross-applied to each
    other), but reporting only "1 ambiguous key" would hide a result that cuts this source's
    real yield roughly in half. qpaybill has a smaller version of the same thing, concentrated in
    Orangeburg (~1,062 rows under one key) -- already-documented in
    enrichment_qpaybill_multiyear_tax.py's own ACCOUNT-ID COUNTIES section as a county whose
    identification_no is an account number, not a parcel id, by design. its_public has a smaller
    one too (~236 rows, one tenant). This is why the ambiguity report below carries BOTH the
    distinct-key count and the actual row count per bucket -- main() prints both, never just the
    smaller of the two."""
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
    """Stream the published board exactly once (board_stream.iter_board_rows()) and delegate to
    _collect_candidates_from_rows() -- see that function's docstring for the actual logic."""
    return _collect_candidates_from_rows(iter_board_rows(docs / "listings.json.gz"))


def _build_patches(buckets: dict[str, dict[str, Listing]], c: Counter) -> dict[str, dict]:
    """Run each bucket through its REAL production enrich_*() function (unmodified, over its own
    list of lightweight Listings) and diff raw before/after to build {dedupe_key: {"raw": {...}}}
    for every candidate whose block the real function actually wrote. Reusing the production
    function -- rather than re-deriving its logic here -- guarantees this backfill's output is
    byte-identical to what a real pipeline run would have written, and gets each module's own
    idempotent _already_done() gate for free."""
    patches: dict[str, dict] = {}
    for bucket, (_source_key, enrich_fn, raw_keys) in _BUCKETS.items():
        candidates = buckets[bucket]
        before: dict[str, dict] = {key: {rk: _raw(li).get(rk) for rk in raw_keys}
                                   for key, li in candidates.items()}
        stats = enrich_fn(list(candidates.values()))
        for k, v in stats.items():
            c[f"{bucket}_{k}"] += v
        for key, li in candidates.items():
            raw = _raw(li)
            changed = {rk: raw[rk] for rk in raw_keys
                       if raw.get(rk) is not None and raw.get(rk) != before[key].get(rk)}
            if not changed:
                continue
            patches[key] = {"raw": changed}
            c[f"{bucket}_patched"] += 1
            c[f"{bucket}_patched_county:{li.county}"] += 1
    return patches


# ===========================================================================
# Phase 2: supervised patch_existing_rows() -- the only part of this script that write-locks
# and mutates the live board. Identical to backfill_deed_ref_bound.py's own Phase 2.
# ===========================================================================

def _parse_proc_status_text(text: str) -> tuple[Optional[float], Optional[float]]:
    """(VmRSS MB, VmHWM MB) parsed out of a /proc/<pid>/status-shaped string. Pure and
    OS-independent so it is unit-testable without a real /proc filesystem."""
    rss = hwm = None
    for line in text.splitlines():
        parts = line.split()
        if len(parts) < 2:
            continue
        if line.startswith("VmRSS:"):
            try:
                rss = float(parts[1]) / 1024.0  # kB -> MB
            except ValueError:
                pass
        elif line.startswith("VmHWM:"):
            try:
                hwm = float(parts[1]) / 1024.0
            except ValueError:
                pass
    return rss, hwm


def _read_proc_status_mb(pid: int) -> tuple[Optional[float], Optional[float]]:
    """(VmRSS MB, VmHWM MB) for `pid` via /proc/<pid>/status -- (None, None) when unavailable."""
    try:
        text = Path(f"/proc/{pid}/status").read_text()
    except OSError:
        return None, None
    return _parse_proc_status_text(text)


def _watchdog_should_kill(elapsed_s: float, rss_mb: Optional[float], hwm_mb: Optional[float], *,
                          timeout_s: float, mem_ceiling_mb: float) -> Optional[str]:
    """Pure decision function: the kill reason string, or None to keep waiting."""
    if elapsed_s > timeout_s:
        return f"wall-clock timeout ({timeout_s:.0f}s) exceeded (elapsed={elapsed_s:.1f}s)"
    if rss_mb is not None and rss_mb > mem_ceiling_mb:
        return f"VmRSS {rss_mb:.0f} MB exceeded the {mem_ceiling_mb:.0f} MB ceiling"
    if hwm_mb is not None and hwm_mb > mem_ceiling_mb:
        return f"VmHWM {hwm_mb:.0f} MB exceeded the {mem_ceiling_mb:.0f} MB ceiling"
    return None


def _patch_worker(patches: dict, summary: dict, docs_dir: str, allow_large: bool,
                  result_queue: "mp.Queue") -> None:
    """The child-process entrypoint: exactly ONE patch_existing_rows() call, nothing else."""
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
    """Run patch_existing_rows() in a CHILD PROCESS, polling /proc/<pid>/status on an interval
    and SIGKILL-ing it if _watchdog_should_kill() says to. The board_lock() the caller already
    holds is inherited by the child via os.environ (multiprocessing's "spawn" start method passes
    the parent's environment through)."""
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
    ap.add_argument("--allow-large", action="store_true",
                    help="Override BOARD_PATCH_MAX_SOURCE_MB (BOARD_PATCH_ALLOW_LARGE=1) in the "
                         "supervised child process, when the board's measured source size is "
                         "over that ceiling. Pass this only for a SUPERVISED run -- the watchdog "
                         "below (--patch-timeout-s / --patch-mem-ceiling-mb) is what actually "
                         "keeps it safe, not this flag alone.")
    ap.add_argument("--patch-timeout-s", type=float, default=1800.0,
                    help="Wall-clock kill-switch (seconds) for the patch_existing_rows() child "
                         "process. Default 30 minutes (this backfill's patch count is far above "
                         "backfill_deed_ref_bound.py's, so its 20-minute default is widened).")
    ap.add_argument("--patch-mem-ceiling-mb", type=float, default=16000.0,
                    help="VmRSS/VmHWM kill-switch (MB) for the patch_existing_rows() child "
                         "process. Default 16,000 MB.")
    args = ap.parse_args()

    docs = REPO / "docs"

    lock = contextlib.nullcontext() if args.dry_run else board_lock(REPO, owner="multiyear_tax_restatement_backfill")
    with lock:
        buckets, total_rows, conflicts, ambiguity = _collect_candidates(docs)
        print(f"board rows streamed: {total_rows:,}")
        if conflicts:
            print(f"EXCLUDED as multi_source_conflict (row carries more than one of the three "
                  f"source keys -- should not happen; investigate before trusting this run): "
                  f"{conflicts:,}")
        for bucket in _BUCKETS:
            print(f"{bucket} candidates: {len(buckets[bucket]):,}")

        c: Counter = Counter()
        c["skipped_ambiguous_dedupe_key_distinct"] = ambiguity["distinct_keys"]
        c["skipped_ambiguous_dedupe_key_rows"] = ambiguity["rows_total"]
        c["skipped_multi_source_conflict"] = conflicts
        if ambiguity["rows_total"]:
            # Report BOTH numbers -- see _collect_candidates_from_rows()'s own "REPORTING
            # GOTCHA" docstring section: distinct-key count alone can hide a large row-level
            # impact when many rows collapse onto one weak fallback key.
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
                  f"supervised watchdog (--patch-timeout-s / --patch-mem-ceiling-mb) is wired "
                  f"the way you want it -- see patch_existing_rows()'s BOARD_PATCH_ALLOW_LARGE "
                  f"docstring in web_artifact.py for what 'supervised' means.")
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
                  f"assume these are fine. patch_existing_rows() applies the same patch to EVERY "
                  f"board row sharing a dedupe_key; backfill_deed_ref_bound.py's 2026-10-19 run "
                  f"found 6/924 of these were a real collision (a WEAK dedupe_key, e.g. the "
                  f"address-only fallback, naming two actually-different properties), not a true "
                  f"duplicate. Spot-check these specific rows before anyone decides to publish. ***")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
