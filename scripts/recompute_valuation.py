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
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "src"))

from foreclosure_scraper.web_artifact import (  # noqa: E402
    BoardLockBusy, board_lock, load_board, write_artifact,
)
from foreclosure_scraper.valuation import calc as vcalc  # noqa: E402
from foreclosure_scraper.valuation import grading as vgrade  # noqa: E402

DOCS = REPO / "docs"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true",
                    help="recompute and report deltas without writing docs/")
    args = ap.parse_args()

    # THE LOCK, held across load_board -> recompute -> write_artifact.
    #
    # What was here was a pgrep of five process names, taken BEFORE the span it
    # was protecting. That is TOCTOU-racy by construction — it cannot see a
    # writer that starts one second later — and it had to be kept in sync by
    # hand with a list of board writers that has grown to a dozen. Whoever
    # writes last silently reverts the other; nothing errors. See
    # web_artifact.board_lock.
    try:
        with board_lock(REPO, owner="recompute_valuation.py"):
            return _run(args)
    except BoardLockBusy as exc:
        print(f"{exc} — refusing to write.")
        return 1


def _run(args) -> int:
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
    from foreclosure_scraper.enrichment_board_quality import enrich_board_quality
    from foreclosure_scraper.enrichment_board_qa import enrich_board_qa

    print("gis_derived:", enrich_gis_derived(listings), flush=True)
    print("equity:", enrich_equity(listings), flush=True)
    print("distress:", score_board(listings), flush=True)
    print("derived_signals:", enrich_derived_signals(listings), flush=True)
    # LAST of the ARV-aware passes — see the ORDER note in the docstring.
    print("data_quality:", enrich_data_quality(listings), flush=True)
    # enrich_board_quality sets raw['geo_imprecise'] (the shared-centroid tag).
    # Omitting it here — which this script did on its first outing — does not
    # clear the flag, it FREEZES it: qa_flags gets refreshed while geo_imprecise
    # keeps whatever the last full run left, so any coordinate collision that
    # arrived since is permanently invisible on every fast republish. Measured
    # after the first run of this script: 71 clusters hold 15,048 leads, 1,999
    # of them carried no geo_imprecise at all, and 1,560 of those published a
    # max bid with no warning — including all 1,028 leads pinned to South
    # Academy Street, Lincolnton. Its only other call sites are main.py and
    # regenerate_dashboard.py, i.e. the 13-hour path nobody runs for a
    # valuation change.
    try:
        print("board_quality:", enrich_board_quality(listings), flush=True)
    except Exception as exc:  # noqa: BLE001
        print(f"board_quality: ERROR {str(exc)[:100]}", flush=True)
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

    # PASS ONLY WHAT THIS RUN ACTUALLY COMPUTED.
    #
    # This used to read the prior docs/run_meta.json, strip "board", and hand
    # the whole rest back as the summary. That looks like preservation and is
    # actually laundering: write_artifact stamps health_carried_from /
    # health_carried_keys ONLY when a key is ABSENT from the summary it is
    # handed, so re-supplying by_source / source_status / regressions made the
    # carry-forward branch dead code and the published file asserted a
    # months-old per-source health report as current. Measured on the live
    # board: by_source listed 85 sources summing 38,650 against a 38,500 board
    # and omitted reo.vrm_va_reo entirely, with no health_carried_from anywhere
    # in the file. run_meta.json is the only per-source health report there is.
    #
    # write_artifact carries the same values forward from the same file, and
    # labels them. by_state and by_source_on_board it derives from the board
    # being written, so those are current rather than carried.
    meta = {"notes": (f"valuation recompute: {_n(a_arv):,} ARVs, "
                      f"{_n(a_bid):,} max bids, {_n(a_deal):,} verdicts")}
    write_artifact(listings, meta, docs_dir=DOCS)
    print(f"\n[{time.strftime('%H:%M:%S')}] published in {time.time()-t0:.0f}s total")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
