#!/usr/bin/env python3
"""One-time backfill: run rod/county_sweeps.py's CchsClassicReader + sweep()/stamp_for() (already
wired into enrichment_county_lien_sweep.SWEEP_COUNTIES via `*CS.HOSTED_CCHS`, default-ON) against
the real board for the 12 HOSTED_CCHS us3/us5 tenants that have NEVER actually landed a single
raw['rod_lien_sweep'] stamp.

Confirmed via a board_stream scan 2026-11-16 (read-only, iter_board_rows(), never load_board()):
0 of 2030/1054/315/1275/1167/1607/669/869/1369/822/720/3148/740/720(dup)/1429/705/2289(these and
the 12 below) rows carry raw['rod_lien_sweep'] for ANY of the 12 counties below, while the sibling
county-run-server path on the SAME mechanism (Orange, Surry -- not vendor-hosted) shows real
2,857/3,046 and 1,046/1,218 coverage. The mechanism is not broken; it has simply never reached
these specific vendor-hosted counties' rows.

Live-smoke-tested all 12 the same day (CS.sweep(reader, since=<400 days ago>, budget_s=20),
cache_dir=None i.e. the real data/county_sweeps/ cache): every one answers walled=None, error=None,
with a real nonzero adverse-instrument index in 3-7 seconds (index_size: Caldwell 60, Currituck 12,
Gates 6, Dare 17, Caswell 6, Burke 50, Cleveland 90, Pender 30, Perquimans 17, Person 22,
Richmond 33, Rockingham 9). This is the exact set project_cchs_getall_session_bug_FIXED_2026-11-12's
SharedSession fix (http_client.SharedSession, CchsClassicReader._impersonated_classic_pair) newly
unblocked -- 3/25 -> 13/25 HOSTED_CCHS tenants working -- MINUS the 12 separate us4-host tenants
(Lincoln, Madison, Henderson, Hertford, Hyde, Montgomery, Chowan, Franklin, Camden, Duplin,
Tyrrell, Washington), which that SAME memory says now fail with a plain HTTP 400 on the search
call itself -- a DIFFERENT, still-unsolved bug, NOT attempted here, NOT this script's target.
Watauga is also excluded: SWEEP_COUNTIES wires it for the marriage job only (a different reader,
LrSearchReader-style MVC app); its lien side was explicitly left unprobed by a prior session and
is not addressed here either.

ROOT CAUSE, investigated but deliberately NOT fixed here: enrich_county_lien_sweep() in
enrichment_county_lien_sweep.py gives EVERY swept county (currently 31, SWEEP_COUNTIES) the SAME
FORECLOSURE_COUNTY_SWEEP_BUDGET_S=900s budget concurrently via asyncio.gather(asyncio.to_thread(...)),
but main.py's outer `_await_capped` deadline for the WHOLE pass is only budget_s + 240 = ~1,140s
total shared across all of them. A full since-2016 (CS.DEFAULT_SINCE) multi-year read-back for
~30 counties sharing one thread pool very plausibly does not finish inside that one shared
deadline for every county every run; _await_capped's own cancellation then loses whatever hadn't
reached save_cache() yet for any county still mid-sweep when it fires -- and Python's default
ThreadPoolExecutor(max_workers=min(32, cpu_count+4)) queues the rest behind whichever counties
happened to grab a thread first, with no rotation/priority among lien-sweep counties (unlike
gis_fill.py's/enrichment_cchs_rod.py's day-of-year rotation fix for an analogous starvation shape).
NOT fixed here, same reasoning project_bttaxpayerportal_other_columns_2026-11-16 gave for the
sibling multi_year_delinquent_tax scheduling gap: retuning a shared production budget/concurrency
path blind, with no live production run to verify before/after, is too risky for one pass. This
script sidesteps that entirely -- it runs the exact same CS.sweep()/CS.stamp_for() primitives the
scheduled job already uses, standalone, with its own generous per-county budget and no shared
deadline, writing real data now rather than waiting for (or blindly retuning) the shared pass.

    python scripts/backfill_cchs_lien_sweep.py --dry-run
    BOARD_PATCH_ALLOW_LARGE=1 python scripts/backfill_cchs_lien_sweep.py
"""
from __future__ import annotations

import argparse
import sys
import time
from datetime import date, timezone, datetime
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "src"))

from foreclosure_scraper.board_stream import iter_board_rows  # noqa: E402
from foreclosure_scraper.models import Listing  # noqa: E402
from foreclosure_scraper.rod import county_sweeps as CS  # noqa: E402
from foreclosure_scraper.web_artifact import (  # noqa: E402
    _APPEND_SIG_FIELDS, board_lock, board_patch_size_state, patch_existing_rows,
)

#: The 12 HOSTED_CCHS us3/us5 tenants confirmed live + confirmed zero rod_lien_sweep coverage
#: 2026-11-16 (see module docstring). NOT the 12 us4 tenants (separate HTTP-400 bug) and NOT
#: Watauga (marriage-only job).
COUNTIES = ("Caldwell", "Currituck", "Gates", "Dare", "Caswell", "Burke", "Cleveland",
            "Pender", "Perquimans", "Person", "Richmond", "Rockingham")

SINCE = date(2016, 1, 1)           # CS.DEFAULT_SINCE's own value; matches the scheduled job's default
BUDGET_S = 300.0                   # generous per county; no shared deadline here, unlike main.py's pass


def _all_county_rows(docs_dir: Path, counties: tuple[str, ...]) -> dict[str, list[tuple[str, Listing]]]:
    """ONE pass over the whole board (never load_board(); iter_board_rows() only) collecting every
    real NC row for each target county that has a usable owner name and no existing rod_lien_sweep
    stamp (never clobber a stamp that landed some other way) -- a single scan for all `counties`,
    not one scan per county (the board is ~587k rows; scanning it once per county would be the same
    N-counties-times waste scripts/backfill_pasquotank_delinquent_tax.py's template avoids by only
    ever targeting one county)."""
    want = {c.lower() for c in counties}
    out: dict[str, list[tuple[str, Listing]]] = {c: [] for c in counties}
    by_lower = {c.lower(): c for c in counties}
    for rec in iter_board_rows(docs_dir / "listings.json.gz"):
        if str(rec.get("state") or "").upper() != "NC":
            continue
        c = str(rec.get("county") or "").replace(" County", "").strip().lower()
        if c not in want:
            continue
        raw = rec.get("raw") if isinstance(rec.get("raw"), dict) else {}
        if isinstance(raw.get("rod_lien_sweep"), dict):
            continue
        owner = (rec.get("owner_name") or "").strip()
        if not owner:
            continue
        li = Listing.model_construct(**{k: rec.get(k) for k in _APPEND_SIG_FIELDS if k in rec})
        li.owner_name = owner
        li.raw = dict(raw)
        out[by_lower[c]].append((li.dedupe_key(), li))
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--allow-large", action="store_true")
    ap.add_argument("--counties", nargs="*", default=None,
                    help="subset of COUNTIES to run (default: all 12)")
    args = ap.parse_args()

    docs_dir = REPO / "docs"
    if not args.dry_run:
        size_state = board_patch_size_state(docs_dir)
        if not size_state["ok"] and not args.allow_large:
            print(f"REFUSING: {size_state['reason']}. Re-run with --allow-large.")
            return 1

    targets = tuple(args.counties) if args.counties else COUNTIES
    checked_at = datetime.now(timezone.utc).date().isoformat()

    print(f"scanning board once for {len(targets)} counties...")
    t_scan = time.time()
    rows_by_county = _all_county_rows(docs_dir, targets)
    print(f"board scan done in {round(time.time() - t_scan, 1)}s: "
          f"{ {c: len(v) for c, v in rows_by_county.items()} }")

    all_patches: dict[str, dict] = {}
    totals = {"found": 0, "possible": 0, "none_found": 0, "unmatchable": 0, "skipped_county": 0}

    for county in targets:
        t0 = time.time()
        reader = CS.CchsClassicReader(county)
        try:
            index, res = CS.sweep(reader, since=SINCE, budget_s=BUDGET_S)
        except Exception as exc:  # noqa: BLE001 - one county never stops the backfill
            print(f"{county}: EXC {type(exc).__name__}: {str(exc)[:150]}")
            totals["skipped_county"] += 1
            continue
        if res.walled or res.error or not res.window_from:
            print(f"{county}: no_stamp (walled={res.walled!r} error={res.error!r})")
            totals["skipped_county"] += 1
            continue

        cands = rows_by_county[county]
        c_counts = {"found": 0, "possible": 0, "none_found": 0, "unmatchable": 0}
        for key, li in cands:
            stamp = CS.stamp_for(index.match(li.owner_name), res, checked_at=checked_at)
            if stamp is None:
                c_counts["unmatchable"] += 1
                continue
            li.raw["rod_lien_sweep"] = stamp
            all_patches[key] = {"raw": li.raw}
            c_counts[stamp["status"]] += 1
        for k, v in c_counts.items():
            totals[k] += v
        print(f"{county}: window={res.window_from}..{res.window_to} index_size={res.index_size} "
              f"rows_eligible={len(cands)} stamped={c_counts} elapsed={round(time.time() - t0, 1)}s")

    print(f"\npatches staged: {len(all_patches)}")
    print(f"totals: {totals}")

    if args.dry_run:
        print("\nDRY RUN -- nothing written.")
        return 0

    if not all_patches:
        print("nothing to write.")
        return 0

    with board_lock(REPO, owner="cchs_lien_sweep_backfill", wait=600, poll=10):
        wstats = patch_existing_rows(all_patches, {"cchs_lien_sweep_backfill": len(all_patches)},
                                     docs_dir=docs_dir)
        print("patch_existing_rows:", wstats)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
