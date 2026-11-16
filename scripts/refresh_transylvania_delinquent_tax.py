#!/usr/bin/env python3
"""Live refresh: re-scrape Transylvania County NC's real tax portal and land the FRESH
per-year bill history onto the board -- both for parcels already on the board (patch) and
genuinely new ones (append). Closes the `multi_year_delinquent_tax` gap-matrix gap
(docs/gap_matrix/gap_list_2026-11-16.csv: NC/Transylvania, 12,528 applicable, 0 built) for real.

WHY A LIVE SCRAPE, NOT A PURE RESTATEMENT. Investigated first (read-only, iter_board_rows()):
Transylvania has 12,528 total board rows (the gap's whole "applicable" denominator -- this is a
row-scope signal, so every county row counts against it even though only genuinely multi-year-
delinquent parcels will ever carry it). Of those, only 480 carry raw['transylvania_tax'] at all,
and all 480 sampled are in the OLD, pre-2026-10-14 single-year snapshot shape (keys like
tax_year/balance_owed/original_levy, no `bills` list) with last_seen on or before 2026-09-22 --
PREDATING scrapers/counties_nc/transylvania_delinquent_tax.py's own 2026-10-14 multi-year fix
(its module docstring's "DATE COVERAGE" section). The scraper's CURRENT code (read directly, not
assumed from its docstring) already writes the correct raw['transylvania_tax']['bills'] list
(build_listing(), ~line 405) and enrichment_transylvania_multiyear_tax.py (already wired into
main.py since commit afae3501, 2026-11-10) already restates that into the shared
raw['multi_year_delinquent_tax'] key gap_matrix.py reads -- but it is a PURE, no-network
restatement: it can only restate data that is actually ON the row, and the row's own data is
stale. A pure backfill (scripts/backfill_transylvania_multiyear_tax.py, this session's sibling
script) run against the CURRENT board would find zero qualifying candidates, because none of
the 480 existing blocks have a `bills` key. The fix has to start with a real scrape.

WHY NOT scripts/run_scoped_scrapers.py --apply. That tool's apply_rows_streaming() is
deliberately ADDITIVE ONLY (see its own module docstring): a freshly-scraped row that matches an
EXISTING board row by any strong signature is skipped and counted, never modified. Re-scraping
through it would re-fetch exactly the right data and then silently discard it for every one of
the ~480 already-represented parcels -- the one case this fix actually needs to touch. This
script is the bespoke patch_existing_rows() counterpart that situation calls for (each row needs
its OWN freshly-fetched, per-row-different bill history written onto it, not one constant value),
built the same way backfill_transylvania_rollback_exposure.py and backfill_multiyear_tax_
restatement.py already do for the sibling columns on this same board.

WHAT THIS DOES.
  1. Runs the REAL, unmodified scraper (TransylvaniaDelinquentTax.safe_run(), the exact class
     run_scoped_scrapers.py would also instantiate) -- one live network pass, no mocking.
  2. Runs the REAL, unmodified enrich_transylvania_multiyear_tax() over the fresh listings
     in-process (pure, no network) so a listing already carries raw['multi_year_delinquent_tax']
     the moment it is staged, whether it ends up patched onto an existing row or appended as new
     -- no second board pass needed for rows this script itself lands.
  3. Streams the published board EXACTLY ONCE (board_stream.iter_board_rows(), never
     load_board()) to index every existing Transylvania NC row by its normalized parcel_id ->
     dedupe_key(). _normalize_parcel() already rejects any digit-less value, which for free
     excludes a handful of existing rows whose parcel_id is a label-parsing artifact ("Escrow :")
     from some earlier, buggier scraper pass -- a pre-existing, separate issue, not touched here
     (those rows simply get no match and are left exactly as they are).
  4. Every fresh listing whose own normalized parcel_id lands in that index becomes a PATCH
     (raw['transylvania_tax'] overwritten with the fresh block; raw['multi_year_delinquent_tax']
     included too when step 2 qualified it) keyed by the EXISTING row's own dedupe_key(), applied
     via patch_existing_rows() -- which MERGES a raw update into the row's existing raw dict
     (web_artifact.py's own docstring), so gis/vision/cama/owner_mailing/etc. already on that row
     are never touched. Everything else is a genuinely new parcel, landed via append_new_rows().
  5. Same ambiguous-identity safety net the sibling backfills use: an existing parcel whose
     normalized id maps to more than one DISTINCT board dedupe_key (the board already has two
     different-identity rows sharing one parcel number) is excluded from matching entirely,
     never guessed at -- both candidates are reported, neither is patched.
  6. Same supervised child-process watchdog (wall-clock + /proc/<pid>/status VmRSS/VmHWM) around
     the actual patch_existing_rows()/append_new_rows() calls, copied verbatim from
     backfill_transylvania_rollback_exposure.py.

DELIBERATELY NOT DONE HERE (kept separate / deferred, not an oversight):
  * two_year_delinquent / tax_owed / rollback_exposure are not refreshed on matched rows --
    out of scope for the multi_year_delinquent_tax gap this script closes. A future pass over
    the SAME fresh scrape could extend this the same way; not needed to land this fix.
  * Newly-APPENDED rows get no valuation/distress-score pass (run_scoped_scrapers.py's convention
    for brand-new rows) -- the dominant population here is PATCHES to existing rows (the whole
    reason this gap existed), not new leads; new rows still get picked up by the next full
    pipeline run or scoped-scraper pass, same as any other freshly-scraped row normally would be.

Usage:
    python scripts/refresh_transylvania_delinquent_tax.py --dry-run
    python scripts/refresh_transylvania_delinquent_tax.py --apply
    python scripts/refresh_transylvania_delinquent_tax.py --apply --allow-large
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
from foreclosure_scraper.enrichment_transylvania_multiyear_tax import (  # noqa: E402
    RAW_KEY,
    SOURCE_KEY,
    enrich_transylvania_multiyear_tax,
)
from foreclosure_scraper.models import Listing, _normalize_parcel  # noqa: E402
from foreclosure_scraper.scrapers.counties_nc.transylvania_delinquent_tax import (  # noqa: E402
    SLUG,
    TransylvaniaDelinquentTax,
)
from foreclosure_scraper.web_artifact import (  # noqa: E402
    _APPEND_SIG_FIELDS,
    append_new_rows,
    board_lock,
    board_patch_size_state,
    patch_existing_rows,
)

_LIGHT_FIELDS = _APPEND_SIG_FIELDS + ("raw",)


def _light(rec: dict) -> Listing:
    return Listing.model_construct(**{k: rec.get(k) for k in _LIGHT_FIELDS})


# ===========================================================================
# Phase 1: live scrape (the only network call in this script).
# ===========================================================================

async def _scrape_fresh() -> tuple[list[Listing], str, str]:
    scraper = TransylvaniaDelinquentTax()
    rows = list(await scraper.safe_run())
    for li in rows:
        if not li.source:
            li.source = SLUG
    return rows, getattr(scraper, "last_outcome", "?"), getattr(scraper, "last_reason", "")


# ===========================================================================
# Phase 2: stream the board once, index existing Transylvania rows by parcel.
# ===========================================================================

def _existing_parcel_index(docs: Path) -> tuple[dict[str, str], set[str], int]:
    """({normalized_parcel: existing dedupe_key}, ambiguous normalized parcels excluded,
    Transylvania NC rows seen). A normalized parcel mapping to more than one DISTINCT
    dedupe_key -- the board already carries two different-identity rows sharing one parcel
    number -- is excluded from the index entirely, same "skip and count, never guess"
    discipline backfill_multiyear_tax_restatement.py's own ambiguity guard uses."""
    idx: dict[str, str] = {}
    conflict: dict[str, set[str]] = {}
    county_rows = 0
    for rec in iter_board_rows(docs / "listings.json.gz"):
        if (rec.get("county") or "").strip().lower() != "transylvania":
            continue
        if (rec.get("state") or "").strip().upper() != "NC":
            continue
        county_rows += 1
        norm = _normalize_parcel(rec.get("parcel_id"))
        if not norm:
            continue
        li = _light(rec)
        try:
            key = li.dedupe_key()
        except Exception:  # noqa: BLE001 - a row too malformed to key is simply unmatchable
            continue
        conflict.setdefault(norm, set()).add(key)
        idx[norm] = key
    ambiguous = {p for p, keys in conflict.items() if len(keys) > 1}
    for p in ambiguous:
        idx.pop(p, None)
    return idx, ambiguous, county_rows


# ===========================================================================
# Phase 3: supervised patch_existing_rows()/append_new_rows() -- reused verbatim
# from backfill_transylvania_rollback_exposure.py's own Phase 2.
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


def _write_worker(patches: dict, new_listings: list, patch_summary: dict, append_summary: dict,
                  docs_dir: str, allow_large: bool, result_queue: "mp.Queue") -> None:
    if allow_large:
        os.environ["BOARD_PATCH_ALLOW_LARGE"] = "1"
        os.environ["BOARD_APPEND_ALLOW_LARGE"] = "1"
    try:
        patch_stats = patch_existing_rows(patches, patch_summary, docs_dir=docs_dir) if patches \
            else {"applied": 0, "existing": 0, "not_found": 0, "duplicate_key_matches": 0}
        append_stats = append_new_rows(new_listings, append_summary, docs_dir=docs_dir) \
            if new_listings else {"added": 0, "written": False}
        result_queue.put(("ok", (patch_stats, append_stats)))
    except BaseException as exc:  # noqa: BLE001
        result_queue.put(("error", f"{type(exc).__name__}: {exc}"))


def _run_write_supervised(patches: dict, new_listings: list, patch_summary: dict,
                          append_summary: dict, docs_dir: Path, *, timeout_s: float,
                          mem_ceiling_mb: float, allow_large: bool,
                          poll_s: float = 1.0) -> tuple[dict, dict, dict]:
    ctx = mp.get_context("spawn")
    q: "mp.Queue" = ctx.Queue()
    proc = ctx.Process(target=_write_worker,
                       args=(patches, new_listings, patch_summary, append_summary,
                             str(docs_dir), allow_large, q))
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
        raise RuntimeError(f"supervised write watchdog killed the child process: "
                           f"{killed_reason}. {report}")
    if proc.exitcode != 0:
        raise RuntimeError(f"supervised write child process exited with code "
                           f"{proc.exitcode}: {report}")
    try:
        status, payload = q.get(timeout=30)
    except Exception as exc:  # noqa: BLE001
        raise RuntimeError(f"supervised write child produced no result: {exc}. {report}") from exc
    if status != "ok":
        raise RuntimeError(f"supervised write child raised: {payload}. {report}")
    patch_stats, append_stats = payload
    return patch_stats, append_stats, report


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--allow-large", action="store_true")
    ap.add_argument("--write-timeout-s", type=float, default=1800.0)
    ap.add_argument("--write-mem-ceiling-mb", type=float, default=16000.0)
    args = ap.parse_args()
    if not args.dry_run and not args.apply:
        ap.error("pass --dry-run or --apply")

    docs = REPO / "docs"

    print("scraping tax.transylvaniacounty.org live (TransylvaniaDelinquentTax.safe_run())...")
    fresh, outcome, reason = asyncio.run(_scrape_fresh())
    print(f"scraper outcome: {outcome} ({reason or 'no reason given'})")
    print(f"fresh listings scraped: {len(fresh):,}")
    if not fresh:
        print("nothing scraped -- nothing to do.")
        return 0

    stats = enrich_transylvania_multiyear_tax(fresh)
    print(f"multi_year_delinquent_tax restatement over fresh listings: {dict(stats)}")

    lock = contextlib.nullcontext() if args.dry_run else board_lock(
        REPO, owner="transylvania_tax_refresh")
    with lock:
        index, ambiguous, county_rows = _existing_parcel_index(docs)
        print(f"\nTransylvania NC board rows streamed: {county_rows:,}")
        print(f"existing parcels indexed for matching: {len(index):,} "
              f"(ambiguous parcels excluded: {len(ambiguous)})")

        patches: dict[str, dict] = {}
        new_listings: list[Listing] = []
        c: Counter = Counter()
        for li in fresh:
            norm = _normalize_parcel(li.parcel_id)
            if norm and norm in index:
                c["matched_existing"] += 1
                raw = li.raw if isinstance(li.raw, dict) else {}
                raw_patch: dict[str, Any] = {}
                if isinstance(raw.get(SOURCE_KEY), dict):
                    raw_patch[SOURCE_KEY] = raw[SOURCE_KEY]
                if isinstance(raw.get(RAW_KEY), dict):
                    raw_patch[RAW_KEY] = raw[RAW_KEY]
                    c["matched_with_mydt"] += 1
                if raw_patch:
                    patches[index[norm]] = {"raw": raw_patch}
            else:
                c["unmatched_new"] += 1
                new_listings.append(li)

        print(f"\nmatched existing rows (will PATCH raw['{SOURCE_KEY}']"
              f"{' + raw[' + repr(RAW_KEY) + ']' if True else ''} where it landed): "
              f"{c['matched_existing']:,}")
        print(f"  of those, qualifying for multi_year_delinquent_tax too: {c['matched_with_mydt']:,}")
        print(f"genuinely new parcels (will APPEND): {c['unmatched_new']:,}")
        print(f"distinct patch keys staged: {len(patches):,}"
              + (" *** fewer than matched_existing -- two fresh parcels collapsed onto one "
                 "existing identity; inspect before trusting this run ***"
                 if len(patches) < c["matched_existing"] else ""))

        if args.dry_run:
            print("\nDRY RUN -- nothing written.")
            return 0
        if not patches and not new_listings:
            print("\nnothing to do.")
            return 0

        size_state = board_patch_size_state(docs)
        if patches and not size_state["ok"] and not args.allow_large:
            print(f"\nREFUSING: {size_state['reason']}. Re-run with --allow-large once the "
                  f"supervised watchdog is wired the way you want it.")
            return 1

        patch_stats, append_stats, watchdog = _run_write_supervised(
            patches, new_listings, dict(c), dict(c), docs,
            timeout_s=args.write_timeout_s, mem_ceiling_mb=args.write_mem_ceiling_mb,
            allow_large=args.allow_large,
        )
        print(f"\nwatchdog: peak VmRSS {watchdog['peak_rss_mb']:.0f} MB, "
              f"peak VmHWM {watchdog['peak_vmhwm_mb']:.0f} MB, wall {watchdog['elapsed_s']:.1f}s")
        print(f"patch: applied {patch_stats['applied']:,}/{len(patches):,} "
              f"(existing board: {patch_stats['existing']:,}, "
              f"not_found: {patch_stats['not_found']:,}, "
              f"duplicate_key_matches: {patch_stats['duplicate_key_matches']:,})")
        print(f"append: added {append_stats.get('added', 0):,}/{len(new_listings):,}, "
              f"written={append_stats.get('written')}")
        if patch_stats["duplicate_key_matches"]:
            print(f"\n*** {patch_stats['duplicate_key_matches']:,} duplicate_key_matches -- "
                  f"spot-check before anyone decides to publish. ***")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
