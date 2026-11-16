#!/usr/bin/env python3
"""One-time backfill: run rod/county_sweeps.py's CchsClassicReader (+ LrSearchReader for one
county) and sweep()/stamp_for() (already wired into enrichment_county_lien_sweep.SWEEP_COUNTIES,
default-ON) against the real board for 14 counties that have NEVER actually landed a single
raw['rod_lien_sweep'] stamp: the original 12 HOSTED_CCHS us3/us5 tenants (round 6) plus Pasquotank
and Watauga (round 7, see below).

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
2026-11-16, round 7: added 2 more counties this script skipped the first time, both live-probed
and confirmed working the same day. Pasquotank (us4-hosted CCHS, CchsClassicReader) was wrongly
swept into "the 12 broken us4 tenants" by round 6's own framing -- it is NOT one of the 12; its
own code comment in county_sweeps.py already said "fully worked, not walled at all" and a fresh
live POST (cookie+Referer, exactly what read() sends) confirms it: 200, real <SearchResponse>,
392 real 2024 docs. Watauga (LrSearchReader, the SAME LRSearch MVC app as Beaufort) had its lien
side explicitly left unprobed by a prior session (SWEEP_COUNTIES wired its marriage job only) --
live-probed now: open()/doc_types() found 4 real adverse codes, CS.sweep() read 2024-01-01..today
cleanly (walled=None, error=None, 20 real instruments). Both now wired into SWEEP_COUNTIES too
(Pasquotank automatically via `*CS.HOSTED_CCHS`; Watauga via a new lien Job alongside its existing
marriage one) -- this script's own board scan confirmed both still had ZERO rod_lien_sweep rows
beforehand (2,413 Pasquotank-eligible, 793 Watauga-eligible, unstamped).

The other 12 us4 tenants (Lincoln, Madison, Hertford, Hyde, Montgomery, Franklin, Camden, Duplin,
Tyrrell, Washington -- 10 of them -- plus Henderson and Chowan) remain OUT OF SCOPE, live-recheck
2026-11-16: a cookie+Referer POST (what read() actually sends) gets a flat HTTP 400 "Bad Request"
for 10 of them (Lincoln/Madison/Hertford/Hyde/Montgomery/Franklin/Camden/Duplin/Tyrrell/Washington
-- stable across 3 retries each, across 4 request-body shapes, and across curl-cffi Chrome
impersonation -- genuinely NOT the Cloudflare Turnstile/search_token wall documented in
project_us4_cchs_session_expired_unsolved_2026-11-12 (no challenge page, no search_token
involvement, no cf-mitigated header; a bare 11-byte IIS-level body), but ALSO not fixed by any
header/body/fingerprint variation tried -- a genuinely separate, still-unexplained server-side
rejection, not attempted here. Henderson and Chowan are the opposite: their SAME cookie+Referer
POST gets HTTP 400 with the literal body "session_expired" (stable across 3 retries each) -- THE
SAME search_token/Turnstile-gated check as the already-confirmed-dead owner-search path, just
surfacing on this endpoint with a 400 instead of a 200. Confirmed dead end for those 2, not a new
bug, not attempted here either.

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
from typing import Callable

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "src"))

from foreclosure_scraper.board_stream import iter_board_rows  # noqa: E402
from foreclosure_scraper.models import Listing  # noqa: E402
from foreclosure_scraper.rod import county_sweeps as CS  # noqa: E402
from foreclosure_scraper.web_artifact import (  # noqa: E402
    _APPEND_SIG_FIELDS, board_lock, board_patch_size_state, patch_existing_rows,
)

#: county -> reader factory. The original 12 HOSTED_CCHS us3/us5 tenants (round 6) plus, as of
#: round 7 (2026-11-16, see module docstring): Pasquotank (HOSTED_CCHS us4, but NOT one of the
#: 12 broken ones -- live-confirmed working) and Watauga (LrSearchReader, the Beaufort-style
#: LRSearch MVC app, lien side newly confirmed working). NOT the 12 genuinely-broken/walled us4
#: tenants.
READERS: dict[str, "Callable[[], CS.Reader]"] = {
    **{c: (lambda c=c: CS.CchsClassicReader(c))
       for c in ("Caldwell", "Currituck", "Gates", "Dare", "Caswell", "Burke", "Cleveland",
                 "Pender", "Perquimans", "Person", "Richmond", "Rockingham", "Pasquotank")},
    "Watauga": (lambda: CS.LrSearchReader("Watauga")),
}
COUNTIES = tuple(READERS)

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
                    help="subset of COUNTIES to run (default: all 14)")
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
        reader = READERS[county]()
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
