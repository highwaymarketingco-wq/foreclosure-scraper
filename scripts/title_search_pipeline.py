#!/usr/bin/env python3
"""Title search & red flag detection pipeline.

Runs enrichers that surface title risk, liens, probate, bankruptcy, code
violations, and other red flags — then aggregates them into a unified
`red_flags` array on each listing.

Each enricher runs sequentially, one at a time (safe for 8GB RAM).
Board is loaded fresh and stream-saved after each step.

Usage:
  python3 scripts/title_search_pipeline.py [step_number]
  No args = run all steps in sequence
  step_number = run just that step (1-N)
"""
import asyncio, gc, gzip, json, os, sys, time, traceback
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "src"))
os.environ.setdefault("PATH", os.path.expanduser("~/bin") + ":" + os.environ.get("PATH", ""))

from foreclosure_scraper.web_artifact import load_board, _to_dict
from foreclosure_scraper.models import Listing

DOCS = REPO / "docs"


def stream_save(board):
    """Stream-write board to JSON + GZ — peak memory = board + 1 dict."""
    t0 = time.time()
    n = len(board)
    print(f"  [save] Writing {n} listings...", flush=True)
    tmp = str(DOCS / "listings.json") + ".tmp"
    total = 0
    with open(tmp, "w", encoding="utf-8") as f:
        f.write("[")
        for i, li in enumerate(board):
            if i > 0:
                f.write(",")
            d = _to_dict(li)
            raw = d.get("raw")
            if isinstance(raw, dict):
                for k in ("comps", "vision", "cama"):
                    raw.pop(k, None)
            chunk = json.dumps(d, ensure_ascii=False, default=str)
            f.write(chunk)
            total += len(chunk)
            if (i + 1) % 10000 == 0:
                print(f"    ...{i+1}/{n} ({total//1024}KB)", flush=True)
                gc.collect()
        f.write("]")
    os.replace(tmp, str(DOCS / "listings.json"))
    print(f"  [save] JSON: {os.path.getsize(str(DOCS/'listings.json'))//1024}KB")
    tmp_gz = str(DOCS / "listings.json.gz") + ".tmp"
    with open(str(DOCS / "listings.json"), "rb") as src, \
         gzip.GzipFile(filename=tmp_gz, mode="wb", compresslevel=9, mtime=0) as dst:
        while True:
            block = src.read(65536)
            if not block:
                break
            dst.write(block)
    os.replace(tmp_gz, str(DOCS / "listings.json.gz"))
    print(f"  [save] GZ: {os.path.getsize(str(DOCS/'listings.json.gz'))//1024}KB ({time.time()-t0:.1f}s)")


# ─── TITLE SEARCH & RED FLAG STEPS ─────────────────────────────────────
# Each tuple: (name, module_path, func_name, timeout, kwargs, description)

STEPS = [
    # ── OFFLINE FIRST (no network, fast) ──
    ("deed_chain", "foreclosure_scraper.enrichment_deed_chain", "enrich_deed_chain",
     300, {}, "Rebuild deed chains from sale records (offline)"),
    ("title_risk", "foreclosure_scraper.enrichment_title_risk", "enrich_title_risk",
     300, {}, "Classify title holders & flag complex ownership (offline)"),
    ("life_events", "foreclosure_scraper.enrichment_life_events", "enrich_life_events",
     120, {}, "Tag estate/elderly/probate from owner names + GIS exemptions"),
    ("amount_owed", "foreclosure_scraper.enrichment_amount_owed", "enrich_amount_owed",
     120, {}, "Recompute amount_owed with new LRC data"),
    ("tax_owed", "foreclosure_scraper.enrichment_tax_owed", "enrich_tax_owed",
     120, {}, "Recompute tax owed from delinquent years"),
    ("eviction_market", "foreclosure_scraper.enrichment_eviction_market", "enrich_eviction_market",
     120, {}, "Tag eviction-market signals (offline)"),
    ("vacant_landuse", "foreclosure_scraper.enrichment_vacant_landuse", "enrich_vacant_landuse",
     120, {}, "Flag vacant/abandoned properties from land-use codes"),
    # ── NETWORK (external APIs, slower) ──
    ("dew_liens", "foreclosure_scraper.enrichment_dew_liens", "enrich_dew_liens",
     300, {}, "Check DEW utility liens (SC)"),
    ("irs_liens", "foreclosure_scraper.enrichment_irs_lien", "enrich_irs_liens",
     300, {}, "Check IRS tax liens via CourtListener"),
    ("bankruptcy", "foreclosure_scraper.enrichment_bankruptcy", "enrich_with_bankruptcy",
     300, {}, "Check bankruptcy records via CourtListener/PACER"),
    ("bankruptcy_prop", "foreclosure_scraper.enrichment_bankruptcy_property", "enrich_bankruptcy_property",
     300, {}, "Match bankruptcy properties to listings"),
    ("courts", "foreclosure_scraper.enrichment_courts", "enrich_with_court_records",
     600, {}, "Retry court records — SC Public Index + NC eCourts"),
    ("incarceration", "foreclosure_scraper.enrichment_incarceration", "enrich_incarceration",
     300, {"max_queries": 100}, "Check incarceration records (motivated seller signal)"),
    ("code_enforcement", "foreclosure_scraper.enrichment_code_enforcement", "enrich_with_code_enforcement",
     300, {}, "Check code enforcement violations"),
    ("helene_damage", "foreclosure_scraper.enrichment_helene_damage", "enrich_with_helene_damage",
     300, {}, "Flag Hurricane Helene damage zones"),
    ("usps_vacancy", "foreclosure_scraper.enrichment_usps_vacancy", "enrich_usps_vacancy",
     300, {}, "Check USPS vacancy indicators"),
    ("sos_dissolution", "foreclosure_scraper.enrichment_sos_dissolution", "enrich_with_sos_dissolution",
     300, {"max_check": 200}, "Check business entity dissolution (LLC owner risk)"),
    ("fema_repetitive", "foreclosure_scraper.enrichment_fema_repetitive_loss", "enrich_with_fema_repetitive_loss",
     300, {}, "Flag FEMA repetitive-loss properties (flood risk)"),
    ("septic_status", "foreclosure_scraper.enrichment_septic_status", "enrich_with_septic_status",
     300, {}, "Check septic system status (environmental risk)"),
    # ── FINAL: Recompute derived signals & red flags ──
    ("derived_signals", "foreclosure_scraper.enrichment_derived_signals", "enrich_derived_signals",
     120, {}, "Recompute derived signals from all new data"),
    ("lead_signals", "foreclosure_scraper.enrichment_lead_signals", "enrich_lead_signals",
     120, {}, "Recompute lead signals (motivation score)"),
    ("distress_recompute", "foreclosure_scraper.distress_score", "enrich_distress",
     120, {}, "Recompute distress score with all new data"),
    ("strategy_recompute", "foreclosure_scraper.enrichment_strategy_fit", "enrich_strategy_fit",
     120, {}, "Recompute strategy fit"),
    ("equity_final", "foreclosure_scraper.enrichment_equity", "enrich_equity",
     120, {}, "Final equity recompute with all data"),
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

    # Coverage check — track red flag signals
    total = len(board)
    coverage = {}
    red_flag_count = 0
    for li in board:
        raw = li.raw if hasattr(li, "raw") and isinstance(li.raw, dict) else {}
        for k in ["deed_chain", "title_risk", "life_events", "amount_owed", "tax_owed",
                   "irs_liens", "bankruptcy", "court_record", "code_enforcement",
                   "incarceration", "helene_damage", "usps_vacancy", "sos_dissolution",
                   "fema_repetitive_loss", "septic_status", "eviction_market",
                   "vacant_landuse", "equity", "distress_stack", "strategy_fit",
                   "derived_signals", "lead_signals"]:
            v = raw.get(k)
            if v is not None and v != "" and v != [] and v != {}:
                coverage[k] = coverage.get(k, 0) + 1
        # Count red flags
        if raw.get("helene_damage") or raw.get("code_enforcement") or \
           raw.get("usps_vacancy") or raw.get("incarceration"):
            red_flag_count += 1
    print(f"  Coverage after {name}:", flush=True)
    for k, v in sorted(coverage.items(), key=lambda x: -x[1]):
        print(f"    {k}: {v:,} ({v/total*100:.1f}%)", flush=True)
    print(f"  Red flag count: {red_flag_count:,} ({red_flag_count/total*100:.1f}%)", flush=True)

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
    print(f"\n✅ ALL {len(STEPS)} TITLE SEARCH STEPS COMPLETE!")


if __name__ == "__main__":
    asyncio.run(main())
