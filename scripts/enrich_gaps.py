#!/usr/bin/env python3
"""Gap-filling enrichment pass — runs enrichers that have low coverage.

Each enricher runs in THIS process but the board is loaded fresh and
stream-saved after each one. Sequential, one at a time — safe for 8GB RAM.

Usage: python3 scripts/enrich_gaps.py [step_number]
  No args = run all steps in sequence
  step_number = run just that step (1-N)
"""
import asyncio, gc, gzip, json, os, sys, time, traceback
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "src"))
os.environ.setdefault("PATH", os.path.expanduser("~/bin") + ":" + os.environ.get("PATH", ""))

from foreclosure_scraper.web_artifact import load_board, write_artifact
from foreclosure_scraper.models import Listing

DOCS = REPO / "docs"

def stream_save(board):
    """Save board via write_artifact — writes listings.json, listings.json.gz,
    AND listings_detail.json sidecar. (Patched from old custom stream_save
    which skipped the sidecar and caused load_board() to silently drop records.)
    """
    t0 = time.time()
    print(f"  [save] Writing {len(board)} listings via write_artifact...", flush=True)
    write_artifact(board, {}, DOCS)
    print(f"  [save] Done ({time.time()-t0:.1f}s)", flush=True)


STEPS = [
    # (name, module, func, timeout, kwargs, description)
    # OFFLINE first (no network, fast, no OOM risk):
    ("deed_chain", "foreclosure_scraper.enrichment_deed_chain", "enrich_deed_chain",
     300, {}, "Rebuild deed chains from all available sale records (offline)"),
    ("life_events", "foreclosure_scraper.enrichment_life_events", "enrich_life_events",
     120, {}, "Tag estate/elderly/probate from owner names + GIS exemptions (offline)"),
    ("census_rent", "foreclosure_scraper.enrichment_census_rent", "enrich_census_rent",
     300, {}, "Fill rental data now that zip codes are populated"),
    # NETWORK enrichers (slower, may hit external APIs):
    ("gis_attrs", "foreclosure_scraper.enrichment_gis_attrs", "enrich_gis_attrs",
     600, {"concurrency": 4}, "Fill assessed/market values, owner, sqft, acreage from county GIS"),
    ("flood_zone", "foreclosure_scraper.enrichment_flood_zone", "enrich_flood_zones",
     360, {}, "Fill flood zone data (3k per 5-min deadline, re-run fills more)"),
    ("courts", "foreclosure_scraper.enrichment_courts", "enrich_with_court_records",
     600, {}, "Retry court records — SC Public Index + NC eCourts"),
    ("bankruptcy", "foreclosure_scraper.enrichment_bankruptcy", "enrich_with_bankruptcy",
     300, {}, "Retry bankruptcy records via CourtListener/PACER"),
    # Final recompute — valuations may change with new GIS data
    ("equity_recompute", "foreclosure_scraper.enrichment_equity", "enrich_equity",
     300, {}, "Recompute equity with new assessed values"),
    ("amount_owed_recompute", "foreclosure_scraper.enrichment_amount_owed", "enrich_amount_owed",
     300, {}, "Recompute amount owed with new data"),
    ("title_risk_recompute", "foreclosure_scraper.enrichment_title_risk", "enrich_title_risk",
     120, {}, "Recompute title risk"),
    ("distress_recompute", "foreclosure_scraper.distress_score", "score_board",
     120, {}, "Recompute distress score"),
    ("strategy_recompute", "foreclosure_scraper.enrichment_strategy_fit", "enrich_strategy_fit",
     120, {}, "Recompute strategy fit"),
]


async def run_step(step_idx):
    name, module_path, func_name, timeout, kwargs, desc = STEPS[step_idx]
    print(f"\n{'='*60}")
    print(f"STEP {step_idx+1}/{len(STEPS)}: {name}")
    print(f"  {desc}")
    print(f"{'='*60}", flush=True)

    print("  Loading board...", flush=True)
    t_load = time.time()
    board = load_board(DOCS)
    print(f"  Board: {len(board)} listings ({time.time()-t_load:.1f}s)", flush=True)

    print(f"  Running {name}...", flush=True)
    t0 = time.time()
    try:
        import importlib, inspect
        mod = importlib.import_module(module_path)
        func = getattr(mod, func_name)

        if inspect.iscoroutinefunction(func):
            stats = await asyncio.wait_for(func(board, **kwargs), timeout=timeout)
        else:
            stats = await asyncio.wait_for(asyncio.to_thread(func, board, **kwargs), timeout=timeout)

        s_str = str(stats)
        if len(s_str) > 300:
            s_str = s_str[:300] + "..."
        print(f"  {name} OK ({time.time()-t0:.1f}s): {s_str}", flush=True)
    except asyncio.TimeoutError:
        print(f"  {name} TIMEOUT ({timeout}s) — partial results saved", flush=True)
    except Exception as e:
        print(f"  {name} ERR: {e}", flush=True)
        traceback.print_exc()

    gc.collect()

    # Coverage check
    total = len(board)
    coverage = {}
    for li in board:
        raw = li.raw if hasattr(li, "raw") and isinstance(li.raw, dict) else {}
        for k in ["gis", "gis_attrs", "deed_chain", "life_events", "flood_zone",
                   "census_rent", "court_record", "bankruptcy", "equity", "amount_owed",
                   "title_risk", "distress_stack", "strategy_fit"]:
            v = raw.get(k)
            if v is not None and v != "" and v != [] and v != {}:
                coverage[k] = coverage.get(k, 0) + 1
    print(f"  Coverage after {name}:", flush=True)
    for k, v in sorted(coverage.items(), key=lambda x: -x[1]):
        print(f"    {k}: {v:,} ({v/total*100:.1f}%)", flush=True)

    # Stream-save
    print("  Saving board...", flush=True)
    try:
        stream_save(board)
    except Exception as e:
        print(f"  Save ERR: {e}")
        traceback.print_exc()

    del board
    gc.collect()


async def main():
    start_step = int(sys.argv[1]) - 1 if len(sys.argv) > 1 else 0
    for i in range(start_step, len(STEPS)):
        await run_step(i)
        print(f"\n  Step {i+1} complete. gc.collect()...", flush=True)
        gc.collect()
    print(f"\n✅ ALL {len(STEPS)} GAP-FILLING STEPS COMPLETE!")


if __name__ == "__main__":
    asyncio.run(main())
