#!/usr/bin/env python3
"""Fix-up pass: re-run valuation calc (with sqft_from_comp guard) + strategy_fit (cleaned tags).
Streaming save to avoid OOM on 8GB machine."""
import json, sys, os, gzip, time, traceback
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "src"))
os.environ.setdefault("PYTHONPATH", "")

BOARD = REPO / "docs" / "listings.json"
GZ   = REPO / "docs" / "listings.json.gz"

def stream_save(listings, path_board, path_gz):
    """Write JSON + gzip one listing at a time — peak memory ~300MB not ~6GB."""
    t0 = time.time()
    print(f"  [stream_save] Writing {len(listings)} listings...")
    tmp_board = str(path_board) + ".tmp"
    with open(tmp_board, 'w') as f:
        f.write('[')
        for i, li in enumerate(listings):
            if i > 0:
                f.write(',')
            f.write(json.dumps(li, default=str))
            if (i + 1) % 10000 == 0:
                print(f"    ...{i+1}/{len(listings)} ({os.path.getsize(tmp_board)//1024}KB)")
        f.write(']')
    board_kb = os.path.getsize(tmp_board) // 1024
    print(f"  [stream_save] JSON written: {board_kb}KB")
    os.replace(tmp_board, str(path_board))

    # Stream gzip
    tmp_gz = str(path_gz) + ".tmp"
    with open(str(path_board), 'rb') as src, open(tmp_gz, 'wb') as dst:
        with gzip.GzipFile(fileobj=dst, mode='wb', compresslevel=6) as gz:
            while True:
                chunk = src.read(1024 * 1024)  # 1MB chunks
                if not chunk:
                    break
                gz.write(chunk)
    gz_kb = os.path.getsize(tmp_gz) // 1024
    print(f"  [stream_save] GZ written: {gz_kb}KB")
    os.replace(tmp_gz, str(path_gz))
    print(f"  [stream_save] Done — board saved atomically ({time.time()-t0:.1f}s)")

def main():
    print("Loading board...")
    t0 = time.time()
    with open(BOARD, 'r') as f:
        listings = json.load(f)
    print(f"Board: {len(listings)} listings ({time.time()-t0:.1f}s)")

    # --- 1. Re-run valuation calc with sqft_from_comp guard ---
    print("[valuation_recalc]...")
    try:
        from foreclosure_scraper.valuation.calc import compute, to_dict
        from foreclosure_scraper.models import Listing
        fixed = 0
        cleared = 0
        for i, li_dict in enumerate(listings):
            raw = li_dict.get("raw") or li_dict
            if not isinstance(raw, dict):
                continue
            try:
                # Reconstruct a Listing from the dict
                li = Listing(**{k: v for k, v in li_dict.items() if k != "raw"})
                li.raw = raw
                c = compute(li)
                calc_data = to_dict(c)
                raw["calc"] = calc_data
                li_dict["raw"] = raw
                fixed += 1
            except Exception:
                # Clear stale calc that had circular ARV
                old_calc = raw.get("calc") or {}
                if old_calc.get("arv_expected"):
                    old_calc["arv_expected"] = None
                    old_calc["arv_confidence"] = "NONE"
                    raw["calc"] = old_calc
                    li_dict["raw"] = raw
                    cleared += 1
            if (i + 1) % 10000 == 0:
                print(f"    ...{i+1}/{len(listings)} ({fixed} computed, {cleared} cleared)")
        print(f"  valuation_recalc: {fixed} computed, {cleared} cleared (circular ARV removed)")
    except Exception as e:
        print(f"  valuation_recalc ERROR: {e}")
        traceback.print_exc()

    # --- 2. Re-run strategy_fit with cleaned tags (no WHOLESALE/GATOR/SUBJECT_TO) ---
    print("[strategy_fit_recalc]...")
    try:
        from foreclosure_scraper.enrichment_strategy_fit import enrich_strategy_fit
        from foreclosure_scraper.models import Listing
        # Clear old strategy_fit tags first
        for li_dict in listings:
            raw = li_dict.get("raw") or li_dict
            if isinstance(raw, dict) and "strategy_fit" in raw:
                del raw["strategy_fit"]
                li_dict["raw"] = raw
        # Reconstruct Listing objects
        listing_objs = []
        for li_dict in listings:
            raw = li_dict.get("raw") or li_dict
            try:
                li = Listing(**{k: v for k, v in li_dict.items() if k != "raw"})
                li.raw = raw if isinstance(raw, dict) else {}
                listing_objs.append(li)
            except Exception:
                pass
        stats = enrich_strategy_fit(listing_objs)
        print(f"  strategy_fit: {stats}")
    except Exception as e:
        print(f"  strategy_fit ERROR: {e}")
        traceback.print_exc()

    # --- 3. Stream save ---
    print("Saving board (stream)...")
    stream_save(listings, BOARD, GZ)

    print("\n✅ Fix-up complete — valuation recalculated + strategy tags cleaned")

if __name__ == "__main__":
    main()
