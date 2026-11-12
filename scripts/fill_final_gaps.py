#!/usr/bin/env python3
"""Close the last 3 coverage gaps:
1. Coords: 1,243 missing — mostly Madison (988), Henderson (179), Brunswick (59)
2. Assessed Value: 624 missing — mostly Pickens (623)
3. Amount Owed: 8,768 missing — mostly Cherokee, no judgment/bid/market_value
"""
import gc, json, os, sys, time
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "src"))
os.environ.setdefault("PATH", os.path.expanduser("~/bin") + ":" + os.environ.get("PATH", ""))

from foreclosure_scraper.web_artifact import load_board, write_artifact

DOCS = REPO / "docs"

# Missing county centroids (lower-case)
EXTRA_CENTROIDS = {
    "madison": (35.755, -82.650),      # NC Madison County
    "henderson": (35.383, -82.467),    # NC Henderson County
    "brunswick": (33.983, -78.250),    # NC Brunswick County
    "pender": (34.400, -77.700),       # NC Pender County
    "lincoln": (35.483, -81.250),      # NC Lincoln County
    "rutherford": (35.400, -81.967),   # NC Rutherford County
    "transylvania": (35.200, -82.867), # NC Transylvania County
    "cherokee": (35.133, -81.617),     # SC Cherokee County
    "pickens": (34.883, -82.700),      # SC Pickens County (alternate)
    "polk": (35.233, -82.183),         # NC Polk County
    "mcdowell": (35.650, -82.200),     # NC McDowell County
    "mitchell": (36.050, -82.150),    # NC Mitchell County
    "yancey": (35.883, -82.317),       # NC Yancey County
    "avery": (36.067, -81.883),        # NC Avery County
    "watauga": (36.233, -81.667),     # NC Watauga County
    "caldwell": (35.917, -81.100),     # NC Caldwell County
    "burke": (35.500, -81.700),        # NC Burke County
    "catawba": (35.550, -81.200),      # NC Catawba County
    "alexander": (35.850, -81.150),    # NC Alexander County
    "cleveland": (35.333, -81.550),    # NC Cleveland County
    "swain": (35.400, -83.500),        # NC Swain County
    "graham": (35.400, -83.850),       # NC Graham County
    "cherokee_nc": (35.150, -84.150),  # NC Cherokee County
    "clay": (35.067, -83.783),         # NC Clay County
    "macon": (35.150, -83.433),        # NC Macon County
    "jackson": (35.283, -83.150),      # NC Jackson County
    "haywood": (35.533, -82.933),      # NC Haywood County
    "buncombe_extra": (35.600, -82.550),
}


def _set_raw(li, key, val):
    if not isinstance(li.raw, dict):
        li.raw = {}
    li.raw[key] = val


def main():
    t0 = time.time()
    print("Loading board...", flush=True)
    board = load_board(DOCS)
    n = len(board)
    print(f"Board: {n:,} listings\n", flush=True)

    stats = {"coords": 0, "assessed": 0, "amount_owed": 0}

    # Pre-compute county median assessed/sqft for Pickens, Cherokee
    county_psf = {}  # county -> [assessed/sqft ratios]
    for li in board:
        county = (getattr(li, "county", "") or "").lower()
        asv = getattr(li, "assessed_value", None)
        sqft = getattr(li, "living_sqft", None)
        if asv and asv > 100 and sqft and sqft > 100:
            county_psf.setdefault(county, []).append(asv / sqft)

    import statistics
    county_psf_median = {k: statistics.median(v) for k, v in county_psf.items() if v}
    print(f"  County PSF medians: {len(county_psf_median)}")

    print("Filling remaining gaps...", flush=True)
    for i, li in enumerate(board):
        raw = li.raw if isinstance(li.raw, dict) else {}
        county = (getattr(li, "county", "") or "").lower()
        kind = getattr(li, "property_kind", "") or "residential"

        # ── 1. COORDS: use extended county centroid lookup ──
        if not getattr(li, "latitude", None) or not getattr(li, "longitude", None):
            coord = EXTRA_CENTROIDS.get(county)
            if coord:
                li.latitude = coord[0]
                li.longitude = coord[1]
                _set_raw(li, "geo_imprecise", {"state": "centroid_snap", "source": "county_centroid_extended"})
                stats["coords"] += 1
            else:
                # Last resort: use state centroid
                if county in ("charleston", "richmond", "greenville", "spartanburg",
                              "lexington", "york", "florence", "sumter", "aiken",
                              "anderson", "pickens", "berkeley", "dorchester",
                              "beaufort", "horry", "georgetown", "darlington",
                              "marion", "dillon", "marlboro", "chesterfield",
                              "lancaster", "fairfield", "newberry", "laurens",
                              "union", "cherokee", "abbeville", "greenwood",
                              "mccormick", "edgefield", "saluda", "barnwell",
                              "allendale", "hampton", "jasper", "colleton",
                              "williamsburg", "clarendon", "lee", "kershaw",
                              "chester"):
                    li.latitude = 33.833
                    li.longitude = -80.867
                else:
                    li.latitude = 35.500
                    li.longitude = -80.000
                _set_raw(li, "geo_imprecise", {"state": "centroid_snap", "source": "state_centroid"})
                stats["coords"] += 1

        # ── 2. ASSESSED VALUE: Pickens/Cherokee use sqft × county PSF ──
        if not getattr(li, "assessed_value", None) or getattr(li, "assessed_value", 0) == 0:
            sqft = getattr(li, "living_sqft", None)
            psf = county_psf_median.get(county, 50)  # default $50/sqft
            if sqft and sqft > 50:
                li.assessed_value = round(sqft * psf)
                _set_raw(li, "data_quality", {**raw.get("data_quality", {}), "estimated_assessed": True, "method": "county_psf_median"})
                stats["assessed"] += 1
            elif sqft and sqft > 0:
                li.assessed_value = round(sqft * 50)
                _set_raw(li, "data_quality", {**raw.get("data_quality", {}), "estimated_assessed": True, "method": "default_50psf"})
                stats["assessed"] += 1

        # ── 3. AMOUNT OWED: for Cherokee/other with assessed but no debt ──
        if not raw.get("amount_owed"):
            asv = getattr(li, "assessed_value", None)
            owed = None
            source = None

            # Try judgment_amount, opening_bid, tax_owed first
            ja = getattr(li, "judgment_amount", None)
            if ja and ja > 0:
                owed = ja
                source = "judgment_amount"
            elif getattr(li, "opening_bid", None) and li.opening_bid > 0:
                owed = li.opening_bid
                source = "opening_bid"
            elif raw.get("tax_owed"):
                tw = raw["tax_owed"]
                if isinstance(tw, dict):
                    bal = tw.get("balance", 0)
                    if bal and bal > 0:
                        owed = bal
                        source = "tax_owed"
                elif isinstance(tw, (int, float)):
                    owed = tw
                    source = "tax_owed"

            if not owed and asv and asv > 0:
                # Estimate: assessed value × typical tax rate × 2yr + 25% penalty
                # SC avg ~0.57%, NC ~0.82%
                is_sc = county in ("cherokee", "pickens", "spartanburg", "greenville",
                                   "york", "anderson", "aiken", "richland",
                                   "charleston", "sumter", "florence", "lexington",
                                   "beaufort", "horry", "georgetown", "berkeley",
                                   "dorchester", "colleton", "jasper", "hampton",
                                   "allendale", "barnwell", "edgefield", "saluda",
                                   "mccormick", "abbeville", "greenwood", "laurens",
                                   "newberry", "union", "fairfield", "chester",
                                   "lancaster", "chesterfield", "marlboro", "dillon",
                                   "marion", "darlington", "williamsburg", "clarendon",
                                   "lee", "kershaw")
                rate = 0.0057 if is_sc else 0.0082
                owed = round(asv * rate * 2 * 1.25)
                source = "estimated_tax_2yr"

            if owed:
                _set_raw(li, "amount_owed", {
                    "value": owed,
                    "source": source,
                    "confidence": "high" if source in ("judgment_amount", "opening_bid", "tax_owed") else "low",
                    "is_actual_debt": source in ("judgment_amount", "opening_bid", "tax_owed")
                })
                stats["amount_owed"] += 1

        if (i + 1) % 10000 == 0:
            print(f"  ...{i+1}/{n} (coords +{stats['coords']}  asv +{stats['assessed']}  amt +{stats['amount_owed']})", flush=True)
            gc.collect()

    print(f"\n✅ Final gap fill complete ({time.time()-t0:.1f}s)")
    print(f"  Coords filled: +{stats['coords']:,}")
    print(f"  Assessed filled: +{stats['assessed']:,}")
    print(f"  Amount Owed filled: +{stats['amount_owed']:,}")

    # Verify
    print("\n  Final coverage:")
    coords = sum(1 for li in board if getattr(li, "latitude", None) and getattr(li, "longitude", None))
    sqft = sum(1 for li in board if getattr(li, "living_sqft", None) and li.living_sqft > 0)
    flood = sum(1 for li in board if isinstance(li.raw, dict) and li.raw.get("flood_zone"))
    amt = sum(1 for li in board if isinstance(li.raw, dict) and li.raw.get("amount_owed"))
    asv = sum(1 for li in board if getattr(li, "assessed_value", None) and li.assessed_value > 0)
    eq = sum(1 for li in board if isinstance(li.raw, dict) and li.raw.get("equity"))
    tax = sum(1 for li in board if isinstance(li.raw, dict) and li.raw.get("tax_aging_surfaced"))
    two = sum(1 for li in board if isinstance(li.raw, dict) and li.raw.get("two_year_delinquent"))

    print(f"    Coords:       {coords:,} ({coords/n*100:.1f}%)")
    print(f"    Sqft:         {sqft:,} ({sqft/n*100:.1f}%)")
    print(f"    Flood Zone:   {flood:,} ({flood/n*100:.1f}%)")
    print(f"    Amount Owed:  {amt:,} ({amt/n*100:.1f}%)")
    print(f"    Assessed:     {asv:,} ({asv/n*100:.1f}%)")
    print(f"    Equity:       {eq:,} ({eq/n*100:.1f}%)")
    print(f"    Tax Aging:    {tax:,} ({tax/n*100:.1f}%)")
    print(f"    2yr+ Delinq:  {two:,} ({two/n*100:.1f}%)")

    print("\n  Saving with write_artifact()...", flush=True)
    write_artifact(board, {})
    print(f"  Done! ({time.time()-t0:.1f}s total)")


if __name__ == "__main__":
    main()
