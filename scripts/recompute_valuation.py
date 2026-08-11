#!/usr/bin/env python3
"""Re-run the VALUATION over the published board and republish. No network.

WHY THIS EXISTS
    scripts/regenerate_dashboard.py is the full re-enrichment: parcel_from_geo,
    parcel_lookup, gis_attrs, situs_address, images. Its own timeout budget adds
    up to ~13 hours, and it spent 8 of them on network I/O without reaching the
    valuation. That is the right tool after a scrape; it is the wrong tool when
    the only thing that changed is calc.py.

    This does the arithmetic half only: load the board, recompute calc + grade,
    re-derive everything downstream of ARV, and republish. Minutes, not hours,
    and it touches no external service.

ORDER MATTERS AND IS NOT ARBITRARY
    Mirrors scripts/regenerate_dashboard.py's post-network section and main.py:

      calc/grade -> gis_derived -> equity -> distress -> derived_signals
                 -> data_quality -> board_qa -> write

    data_quality LAST of the ARV-aware passes, because every caveat it writes is
    read out of raw['calc']. Run it earlier and it captions the board off the
    PREVIOUS valuation — a clean bill of health signed for a number that has
    since been flagged. tests/test_enrichment_order.py fails any publisher that
    gets this backwards; this script is covered by it.

    equity runs after calc because it is ARV - payoff - senior liens, and its
    own trust gate has to see the fresh calc to know whether to withhold.

USAGE
    uv run python scripts/recompute_valuation.py [--dry-run]

    --dry-run recomputes and reports the deltas without writing docs/.
"""
from __future__ import annotations

import argparse
import subprocess
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "src"))

from foreclosure_scraper.web_artifact import load_board, write_artifact  # noqa: E402
from foreclosure_scraper.valuation import calc as vcalc  # noqa: E402
from foreclosure_scraper.valuation import grading as vgrade  # noqa: E402

DOCS = REPO / "docs"


def _engine_running() -> bool:
    # Pattern must not start with "-": pgrep reads a leading dash as an option,
    # matches nothing, and the guard silently never fires.
    r = subprocess.run(
        ["pgrep", "-f", "--", r"run_local\.sh|-m foreclosure_scraper|merge_today_sources"
                             r"|patch_vision_gemini|regenerate_dashboard"],
        capture_output=True, text=True)
    return bool(r.stdout.strip())


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true",
                    help="recompute and report deltas without writing docs/")
    args = ap.parse_args()

    if _engine_running():
        print("a board writer is running and holds the board — refusing to write.")
        return 1

    t0 = time.time()
    listings = load_board(DOCS)
    print(f"[{time.strftime('%H:%M:%S')}] loaded {len(listings):,} listings "
          f"(sidecar merged) in {time.time()-t0:.0f}s", flush=True)
    if not listings:
        print("no board found — nothing to do")
        return 1

    before = [((li.raw or {}).get("calc") or {}) for li in listings]
    b_arv = [c.get("arv_expected") for c in before]
    b_bid = [c.get("max_bid_70") for c in before]
    b_deal = [c.get("deal_status") for c in before]
    b_eq = [((li.raw or {}).get("equity") or {}).get("value") for li in listings]

    errs = 0
    for li in listings:
        try:
            c = vcalc.compute(li)
            g = vgrade.grade(li, c)
            if not isinstance(li.raw, dict):
                li.raw = {}
            li.raw["calc"] = vcalc.to_dict(c)
            li.raw["grade"] = vgrade.to_dict(g)
        except Exception:  # noqa: BLE001 - one bad lead must not void the pass
            errs += 1
    print(f"[{time.strftime('%H:%M:%S')}] recomputed calc+grade "
          f"({errs} lead errors)", flush=True)

    from foreclosure_scraper.enrichment_gis_derived import enrich_gis_derived
    from foreclosure_scraper.enrichment_equity import enrich_equity
    from foreclosure_scraper.distress_score import score_board
    from foreclosure_scraper.enrichment_derived_signals import enrich_derived_signals
    from foreclosure_scraper.enrichment_data_quality import enrich_data_quality
    from foreclosure_scraper.enrichment_board_qa import enrich_board_qa

    print("gis_derived:", enrich_gis_derived(listings), flush=True)
    print("equity:", enrich_equity(listings), flush=True)
    print("distress:", score_board(listings), flush=True)
    print("derived_signals:", enrich_derived_signals(listings), flush=True)
    # LAST of the ARV-aware passes — see the ORDER note in the docstring.
    print("data_quality:", enrich_data_quality(listings), flush=True)
    try:
        print("board_qa:", enrich_board_qa(listings), flush=True)
    except Exception as exc:  # noqa: BLE001
        print(f"board_qa: ERROR {str(exc)[:100]}", flush=True)

    after = [((li.raw or {}).get("calc") or {}) for li in listings]
    a_arv = [c.get("arv_expected") for c in after]
    a_bid = [c.get("max_bid_70") for c in after]
    a_deal = [c.get("deal_status") for c in after]
    a_eq = [((li.raw or {}).get("equity") or {}).get("value") for li in listings]

    def _n(xs):
        return sum(1 for x in xs if x)

    up = sum(1 for b, a in zip(b_arv, a_arv) if b and a and a > b)
    down = sum(1 for b, a in zip(b_arv, a_arv) if b and a and a < b)
    lost = sum(1 for b, a in zip(b_arv, a_arv) if b and not a)
    gained = sum(1 for b, a in zip(b_arv, a_arv) if a and not b)

    print("\n--- deltas ---")
    print(f"  ARV published   {_n(b_arv):>7,} -> {_n(a_arv):>7,}   "
          f"(up {up:,} / down {down:,} / withheld {lost:,} / new {gained:,})")
    print(f"  max_bid_70      {_n(b_bid):>7,} -> {_n(a_bid):>7,}")
    print(f"  deal verdict    {_n(b_deal):>7,} -> {_n(a_deal):>7,}")
    print(f"  equity figures  {_n(b_eq):>7,} -> {_n(a_eq):>7,}")
    print(f"  ARV over $2M    {sum(1 for x in b_arv if x and x > 2e6):>7,} -> "
          f"{sum(1 for x in a_arv if x and x > 2e6):>7,}")

    if args.dry_run:
        print("\n--dry-run: nothing written")
        return 0

    import json
    meta_path = DOCS / "run_meta.json"
    meta = json.loads(meta_path.read_text()) if meta_path.exists() else {}
    meta = {k: v for k, v in meta.items() if k != "board"}  # write_artifact rebuilds it
    meta["notes"] = (f"valuation recompute: {_n(a_arv):,} ARVs, "
                     f"{_n(a_bid):,} max bids, {_n(a_deal):,} verdicts")
    write_artifact(listings, meta, docs_dir=DOCS)
    print(f"\n[{time.strftime('%H:%M:%S')}] published in {time.time()-t0:.0f}s total")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
