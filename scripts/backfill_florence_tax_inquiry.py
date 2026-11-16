#!/usr/bin/env python3
"""One-time catch-up: land Florence County SC's tax-inquiry signal
(enrichment_florence_tax_inquiry.py) and its pure restate
(enrichment_florence_two_year_delinquent.py) onto the already-published board.

WHY. gap_matrix.py reports Florence SC "sourced-not-built" on TWO columns --
tax_aging_surfaced and two_year_delinquent, ~3,883 est rows each, identical
count. Both read off the SAME underlying signal: raw['tax_owed']
(tax_aging_surfaced's own precondition, via enrichment_tax_aging.py, already
wired board-wide) and raw['two_year_delinquent'] (written by the sibling
restate module here) are BOTH downstream of raw['florence_tax_inquiry'],
which only enrichment_florence_tax_inquiry.py writes, and that module's own
FORECLOSURE_FLORENCE_TAX_INQUIRY flag defaults OFF ("opt in explicitly" --
built+wired into main.py 2026-11-10, never turned on since). One flag flip
closes both columns for every Florence row with a usable Map-Block-Parcel
parcel_id -- 1,836 of 3,883 Florence SC rows from the dash-separated TMS form
(counties_sc.florence_delinquent_tax) plus another 1,297 from
counties_sc.sc_heir_estate_parcel_cache's own flat 10-digit form once mbp()
was taught to read it too (measured 2026-11-16: up to ~3,133 of 3,883). The
remaining rows carry no parcel_id at all on the row -- a real scope
boundary (nothing to query), not a bug this fetcher can close.

Live-verified 2026-11-16 against the real web.florenceco.org CGI (18/18 real
parcels, 0 portal failures) before this script was written.

Runs the SAME enrich_florence_tax_inquiry() / enrich_florence_two_year_delinquent()
functions main.py calls (not a reimplementation), at the SAME pacing the
module already enforces (MIN_GAP_S=2.0, one request in flight at a time,
concurrency 3, a 6-consecutive-failure breaker) -- never raised here. That
pacing makes a full 1,836-parcel sweep a multi-hour run (~3 req/parcel * 2s
~= 3h); --budget-s below is generous specifically so one supervised run can
attempt the whole backlog instead of only today's slice. A run that still
hits the budget or the breaker exits cleanly with whatever it fetched
patched onto the board -- safe to re-run (RECHECK_DAYS=14 skips rows already
freshly checked).

BOARD I/O: board_stream.iter_board_rows() once, the two enrichers run
in-memory (the live network fetch happens with NO lock held), then ONE
patch_existing_rows() call under board_lock() at the very end -- never
load_board()/write_artifact().

Usage:
    python scripts/backfill_florence_tax_inquiry.py --dry-run
    BOARD_PATCH_ALLOW_LARGE=1 python scripts/backfill_florence_tax_inquiry.py --allow-large
    python scripts/backfill_florence_tax_inquiry.py --allow-large --budget-s 1200  # a short slice
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "src"))

# Opt in to the fetcher for THIS process only -- the live run_profile.json flag (added
# alongside this script) is what turns it on for main.py's own regular runs.
os.environ.setdefault("FORECLOSURE_FLORENCE_TAX_INQUIRY", "1")

from foreclosure_scraper.board_stream import iter_board_rows  # noqa: E402
from foreclosure_scraper.enrichment_florence_tax_inquiry import (  # noqa: E402
    enrich_florence_tax_inquiry, mbp,
)
from foreclosure_scraper.enrichment_florence_two_year_delinquent import (  # noqa: E402
    enrich_florence_two_year_delinquent,
)
from foreclosure_scraper.enrichment_tax_aging import enrich_tax_aging  # noqa: E402
from foreclosure_scraper.models import Listing  # noqa: E402
from foreclosure_scraper.web_artifact import (  # noqa: E402
    _APPEND_SIG_FIELDS, board_lock, board_patch_size_state, patch_existing_rows,
)

_IS_FLORENCE = lambda rec: (
    str(rec.get("state") or "").upper() == "SC"
    and str(rec.get("county") or "").strip().lower().replace(" county", "") == "florence"
)
# florence_tax_inquiry/tax_owed/two_year_delinquent: enrichment_florence_tax_inquiry.py +
# its sibling restate. tax_aging_surfaced/tax_aging_high/tax_not_yet_late/tax_big_old:
# enrichment_tax_aging.py's own derivation off the raw['tax_owed'] this run just populated --
# already wired board-wide in main.py with no county gate, called directly here (pure,
# no network) so BOTH gap_matrix columns land in the SAME pass/patch, not a later run.
_WATCH_KEYS = ("florence_tax_inquiry", "tax_owed", "two_year_delinquent",
               "tax_aging_surfaced", "tax_aging_high", "tax_not_yet_late", "tax_big_old")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--allow-large", action="store_true")
    ap.add_argument("--budget-s", type=float, default=13000.0,
                     help="wall-clock budget for the live fetch pass (default: enough for "
                          "the whole ~1,836-parcel backlog at the module's own pacing)")
    ap.add_argument("--max-parcels", type=int, default=2000)
    ap.add_argument("--stats-out", default="",
                     help="optional path to write the final stats dict as JSON")
    args = ap.parse_args()
    os.environ["FORECLOSURE_FLORENCE_TAX_INQUIRY_BUDGET_S"] = str(args.budget_s)
    os.environ["FORECLOSURE_FLORENCE_TAX_INQUIRY_MAX_PARCELS"] = str(args.max_parcels)

    docs_dir = REPO / "docs"
    if not args.dry_run:
        size_state = board_patch_size_state(docs_dir)
        if not size_state["ok"] and not args.allow_large:
            print(f"REFUSING: {size_state['reason']}. Re-run with --allow-large.")
            return 1
        if args.allow_large:
            os.environ["BOARD_PATCH_ALLOW_LARGE"] = "1"

    print("streaming board for Florence SC rows...", flush=True)
    keyed: dict[str, Listing] = {}
    before: dict[str, dict] = {}
    total_florence = 0
    eligible = 0
    for rec in iter_board_rows(docs_dir / "listings.json.gz"):
        if not _IS_FLORENCE(rec):
            continue
        total_florence += 1
        full_raw = rec.get("raw") if isinstance(rec.get("raw"), dict) else {}
        li = Listing.model_construct(**{k: rec.get(k) for k in _APPEND_SIG_FIELDS if k in rec})
        li.raw = {k: full_raw[k] for k in _WATCH_KEYS if k in full_raw}
        try:
            key = li.dedupe_key()
        except Exception:  # noqa: BLE001
            continue
        if mbp(li.parcel_id) is not None:
            eligible += 1
        keyed[key] = li
        before[key] = dict(li.raw)

    print(f"Florence SC rows streamed: {total_florence:,}; distinct dedupe_keys: {len(keyed):,}; "
          f"eligible (usable Map-Block-Parcel id): {eligible:,}", flush=True)
    print(f"running enrich_florence_tax_inquiry(budget_s={args.budget_s}, "
          f"max_parcels={args.max_parcels}) -- politeness-paced, this can take a while...",
          flush=True)

    t0 = time.monotonic()

    async def run():
        return await enrich_florence_tax_inquiry(list(keyed.values()))

    ftx_stats = asyncio.run(run())
    elapsed = time.monotonic() - t0
    print(f"enrich_florence_tax_inquiry done in {elapsed:.0f}s: {ftx_stats}", flush=True)

    tyd_stats = enrich_florence_two_year_delinquent(list(keyed.values()))
    print(f"enrich_florence_two_year_delinquent: {tyd_stats}", flush=True)

    tas_stats = enrich_tax_aging(list(keyed.values()))
    print(f"enrich_tax_aging: {tas_stats}", flush=True)

    patches: dict[str, dict] = {}
    for key, li in keyed.items():
        raw = li.raw if isinstance(li.raw, dict) else {}
        changed = {k: raw.get(k) for k in _WATCH_KEYS if k in raw}
        if changed != before[key]:
            patches[key] = {"raw": changed}

    print(f"rows changed (tax_owed/florence_tax_inquiry/two_year_delinquent/tax_aging_surfaced): "
          f"{len(patches):,}", flush=True)
    result = {"total_florence": total_florence, "eligible": eligible,
              "ftx_stats": ftx_stats, "tyd_stats": tyd_stats, "tas_stats": tas_stats,
              "patches_staged": len(patches), "elapsed_s": round(elapsed, 1)}

    if args.dry_run:
        print("DRY RUN -- nothing written.")
        for key, p in list(patches.items())[:5]:
            print(" ", key, p)
        result["written"] = False
        if args.stats_out:
            Path(args.stats_out).write_text(json.dumps(result, indent=2))
        return 0

    if not patches:
        print("nothing to patch.")
        result["written"] = False
        if args.stats_out:
            Path(args.stats_out).write_text(json.dumps(result, indent=2))
        return 0

    with board_lock(REPO, owner="backfill_florence_tax_inquiry", wait=1800, poll=10):
        pstats = patch_existing_rows(
            patches, {"backfill_florence_tax_inquiry": len(patches)}, docs_dir=docs_dir)
    print(f"patch_existing_rows: {pstats}", flush=True)
    result["written"] = True
    result["patch_stats"] = pstats
    if args.stats_out:
        Path(args.stats_out).write_text(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
