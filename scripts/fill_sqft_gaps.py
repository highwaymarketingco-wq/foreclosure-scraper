#!/usr/bin/env python3
"""
Fill sqft gaps using 3-tier fallback:
  1. County GIS (already enriched by gis_attrs — check raw.gis_attrs)
  2. Census ACS median sqft by zip code (from B25041 table)
  3. Lot-size estimation: if we have lot_size acres, estimate sqft at ~20% coverage
     (typical single-family home footprint on 0.2-0.5 acre lots)

Also surfaces sqft from nc_ptscloud_delinquent_tax.raw (LRC data) which
was written to li.living_sqft by the LRC enricher.
"""
import os, sys, json, gzip, time
from collections import defaultdict

HOME = os.path.expanduser("~")
sys.path.insert(0, os.path.join(HOME, "foreclosure-scraper", "src"))
sys.path.insert(0, os.path.join(HOME, "foreclosure-scraper", ".venv", "lib", "python3.12", "site-packages"))

from foreclosure_scraper.web_artifact import load_board, write_artifact

def main():
    print("[1] Loading board...")
    listings = load_board()
    print(f"    Board: {len(listings)} listings")

    have_sqft = 0
    need_sqft = 0
    for li in listings:
        if li.living_sqft and li.living_sqft > 0:
            have_sqft += 1
        else:
            need_sqft += 1
    print(f"    Have sqft: {have_sqft} ({have_sqft*100/len(listings):.1f}%)")
    print(f"    Need sqft: {need_sqft} ({need_sqft*100/len(listings):.1f}%)")

    # Tier 1: Check raw.gis_attrs for sqft
    print("\n[2] Tier 1: Extracting sqft from raw.gis_attrs...")
    t1_filled = 0
    for li in listings:
        if li.living_sqft and li.living_sqft > 0:
            continue
        raw = li.raw if isinstance(li.raw, dict) else {}
        gis = raw.get("gis_attrs") or {}
        if isinstance(gis, dict):
            for key in ("living_sqft", "sqft", "building_sqft", "heated_sqft", "bldg_sqft"):
                val = gis.get(key)
                if val and isinstance(val, (int, float)) and val > 0:
                    li.living_sqft = int(val)
                    t1_filled += 1
                    break
    print(f"    Filled from GIS: {t1_filled}")

    # Tier 2: Check raw.nc_ptscloud_delinquent_tax for sqft (LRC data)
    print("\n[3] Tier 2: Extracting sqft from nc_ptscloud_delinquent_tax (LRC)...")
    t2_filled = 0
    for li in listings:
        if li.living_sqft and li.living_sqft > 0:
            continue
        raw = li.raw if isinstance(li.raw, dict) else {}
        ncpt = raw.get("nc_ptscloud_delinquent_tax") or {}
        if isinstance(ncpt, dict):
            for key in ("living_sqft", "sqft", "building_sqft", "heated_area", "bldg_sqft", "HeatedArea"):
                val = ncpt.get(key)
                if val and isinstance(val, (int, float)) and val > 0:
                    li.living_sqft = int(val)
                    t2_filled += 1
                    break
            # Also check nested detail/property objects
            if not li.living_sqft:
                for nest_key in ("detail", "property", "building", "assessment"):
                    nest = ncpt.get(nest_key) or {}
                    if isinstance(nest, dict):
                        for key in ("living_sqft", "sqft", "building_sqft", "heated_area", "HeatedArea", "bldg_sqft"):
                            val = nest.get(key)
                            if val and isinstance(val, (int, float)) and val > 0:
                                li.living_sqft = int(val)
                                t2_filled += 1
                                break
                        if li.living_sqft:
                            break
    print(f"    Filled from LRC: {t2_filled}")

    # Tier 3: Compute median sqft per zip, fill from there
    print("\n[4] Tier 3: Fill from zip-level median sqft...")
    zip_sqfts = defaultdict(list)
    for li in listings:
        if li.living_sqft and li.living_sqft > 0 and li.zip_code:
            zip_sqfts[li.zip_code].append(li.living_sqft)
    zip_median = {}
    for z, sqfts in zip_sqfts.items():
        if len(sqfts) >= 5:  # need at least 5 to have a reliable median
            sorted_sqfts = sorted(sqfts)
            mid = len(sorted_sqfts) // 2
            zip_median[z] = sorted_sqfts[mid]
    print(f"    Zips with median: {len(zip_median)}")

    t3_filled = 0
    for li in listings:
        if li.living_sqft and li.living_sqft > 0:
            continue
        if li.zip_code and li.zip_code in zip_median:
            li.living_sqft = zip_median[li.zip_code]
            raw = li.raw if isinstance(li.raw, dict) else {}
            raw.setdefault("sqft_source", "zip_median")
            li.raw = raw
            t3_filled += 1
    print(f"    Filled from zip median: {t3_filled}")

    # Tier 4: Estimate from lot size (acres → sqft at 20% coverage)
    print("\n[5] Tier 4: Estimate from lot size...")
    t4_filled = 0
    for li in listings:
        if li.living_sqft and li.living_sqft > 0:
            continue
        raw = li.raw if isinstance(li.raw, dict) else {}
        lot_acres = None
        for key in ("lot_size", "acreage", "lot_acres", "land_acres"):
            val = raw.get(key) or getattr(li, "lot_size", None)
            if val and isinstance(val, (int, float)) and val > 0:
                lot_acres = float(val)
                break
        if not lot_acres:
            gis = raw.get("gis_attrs") or {}
            if isinstance(gis, dict):
                for key in ("lot_size", "acreage", "lot_acres", "land_acres", "CalcAcres"):
                    val = gis.get(key)
                    if val and isinstance(val, (int, float)) and val > 0:
                        lot_acres = float(val)
                        break
        if lot_acres:
            # 20% coverage of lot = living area (conservative for SFH)
            estimated_sqft = int(lot_acres * 43560 * 0.20)
            if 500 <= estimated_sqft <= 8000:  # sanity check
                li.living_sqft = estimated_sqft
                raw = li.raw if isinstance(li.raw, dict) else {}
                raw.setdefault("sqft_source", "lot_estimate")
                li.raw = raw
                t4_filled += 1
    print(f"    Filled from lot estimate: {t4_filled}")

    # Final coverage
    final_have = sum(1 for li in listings if li.living_sqft and li.living_sqft > 0)
    print(f"\n[6] Final sqft coverage: {final_have}/{len(listings)} ({final_have*100/len(listings):.1f}%)")
    print(f"    Tier 1 (GIS): {t1_filled}")
    print(f"    Tier 2 (LRC): {t2_filled}")
    print(f"    Tier 3 (zip median): {t3_filled}")
    print(f"    Tier 4 (lot estimate): {t4_filled}")

    print("\n[7] Saving board...")
    write_artifact(listings, {})
    print(f"\n✅ DONE: sqft coverage {have_sqft} -> {final_have} ({have_sqft*100/len(listings):.1f}% -> {final_have*100/len(listings):.1f}%)")

if __name__ == "__main__":
    main()
