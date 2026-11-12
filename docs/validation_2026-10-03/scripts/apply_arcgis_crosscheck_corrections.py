"""Second corroboration pass: the first pass checked each comp ONLY against the
Spatialest record-card's rendered transfer-HISTORY table. Manually spot-checking
every one of the 15 unique addresses that first pass flagged as not-found /
too-stale / wrong-price against Buncombe's own live ArcGIS parcel layer
(gis.buncombecounty.org .../property_bc_dis/MapServer/1 -- the SAME authoritative
county source, read directly via its current SalePrice/DeedDate attributes
instead of the Spatialest SPA's rendered history) surfaced two real methodology
gaps in the first pass, NOT board errors:

  1. Spatialest's rendered transfer-history table lags the county's own current-
     snapshot SalePrice/DeedDate fields for very recent sales (within the last
     ~6 months) -- the history table simply hadn't picked up the newest deed yet
     on several parcels, even though the county's own record already had it.
  2. The address resolver (HouseNumber + LIKE streetname, taking the first/only
     match) has no disambiguation step when MULTIPLE distinct parcels share the
     same house number + a similar street name (e.g. three separate "35 McKinney
     Rd" parcels in different towns, "22 Waters Rd" vs "22 Waters COVE Rd", "3
     View St" vs 4 other "*VIEW*" streets) -- it can silently grab the wrong one.

Re-checking all 15 against the ArcGIS layer's live SalePrice/DeedDate directly
(see verify_mismatch2.py in this same dir) resolves 10 of the 15 as genuinely
accurate board comps that the first pass under-counted. This script applies
that correction to the full result set and recomputes final numbers.
"""
import json
from pathlib import Path

RESULTS = Path("/private/tmp/claude-502/-Users-cashhigh-Desktop/b86058dc-f10e-4c7b-a7fd-37f22fac2920/scratchpad/comps_validation_results.json")

# address (lowercased, as cleaned by the validator) -> corrected real price/date from
# the ArcGIS layer's own current SalePrice/DeedDate attributes, live-checked 2026-10-04
CORRECTIONS = {
    "80 webb cove rd":   {"real_price": 200000.0, "real_date": "2026-08-27", "note": "Spatialest history lag; ArcGIS current snapshot matches exactly"},
    "7 brushwood rd":    {"real_price": 700000.0, "real_date": "2026-04-10", "note": "Spatialest history lag; ArcGIS current snapshot matches (1.1% off)"},
    "1 pensacola hts":   {"real_price": 199000.0, "real_date": "2026-09-03", "note": "Spatialest history lag; ArcGIS current snapshot matches exactly"},
    "4 heather way":     {"real_price": 490000.0, "real_date": "2026-08-27", "note": "comp omitted unit letter (real parcel is 4B Heather Way); ArcGIS matches exactly"},
    "8 hemlock rd":      {"real_price": 226000.0, "real_date": "2026-03-31", "note": "comp said Rd, real parcel is 8 Hemlock DR; ArcGIS matches exactly"},
    "7 woodbury rd":     {"real_price": 740000.0, "real_date": "2026-08-24", "note": "Spatialest history lag; ArcGIS current snapshot matches exactly"},
    "35 mckinney rd":    {"real_price": 510000.0, "real_date": "2026-07-31", "note": "3 distinct parcels share this address; resolver grabbed wrong one, ArcGIS direct lookup matches exactly"},
    "47 timberwood dr":  {"real_price": 744000.0, "real_date": "2026-05-01", "note": "Spatialest history lag; ArcGIS current snapshot matches exactly"},
    "3 view st":         {"real_price": 379000.0, "real_date": "2026-09-17", "note": "5 similarly-named streets; resolver grabbed wrong one, ArcGIS direct lookup matches exactly"},
    "22 waters rd":      {"real_price": 450000.0, "real_date": "2026-04-10", "note": "decoy '22 Waters COVE Rd' nearby; ArcGIS direct lookup on exact street matches exactly"},
    # Stay unresolved / genuinely wrong even after the ArcGIS cross-check:
    "44 haw creek cir":  {"real_price": None, "real_date": None, "note": "no matching parcel in ArcGIS either -- genuinely unconfirmed"},
    "3 windy hollow rd": {"real_price": None, "real_date": None, "note": "ArcGIS's house-number-3 match is a mismatched '6 Windy Hollow Rd' record ($0 sale) -- genuinely unconfirmed"},
    "117 lookout rd":    {"real_price": None, "real_date": None, "note": "address collision: real '117 Lookout DR' last sold $575k/2021; a DIFFERENT parcel ('27 Soco St') happens to share the claimed date+price -- genuinely unconfirmed, not a clean match either way"},
    "205 linden st":     {"real_price": None, "real_date": None, "note": "ArcGIS shows $0/2025-01-29 current snapshot, Spatialest history shows $105k/2026-09-01 'Not Qualified' near the claimed date -- claimed $300,000 is NOT corroborated by either live source"},
    "140 old leicester rd": {"real_price": 160000.0, "real_date": "2026-04-06", "note": "confirmed real sale, price genuinely 12.5% off (board understates)"},
}

PRICE_TOL = 0.10

def main():
    d = json.loads(RESULTS.read_text())
    n_flipped_to_verified = 0
    n_stayed_wrong_or_unconfirmed = 0

    for p in d["property_results"]:
        for c in p["comps"]:
            if c["verdict"] == "price_verified_accurate":
                continue
            addr_key = (c["claimed"].get("address") or "").split(",")[0].strip().lower()
            corr = CORRECTIONS.get(addr_key)
            if not corr:
                continue
            c["corroboration_pass"] = corr
            real_price = corr["real_price"]
            claimed_price = c["claimed"].get("sold_price")
            if real_price is not None and claimed_price:
                err = abs(real_price - claimed_price) / real_price
                c["corroboration_pass"]["price_error_pct"] = round(err * 100, 1)
                if err <= PRICE_TOL:
                    c["verdict_corrected"] = "price_verified_accurate_on_recheck"
                    c["verified_accurate_corrected"] = True
                    n_flipped_to_verified += 1
                else:
                    c["verdict_corrected"] = "price_wrong_confirmed_on_recheck"
                    c["verified_accurate_corrected"] = False
                    n_stayed_wrong_or_unconfirmed += 1
            else:
                c["verdict_corrected"] = "unconfirmed_even_on_recheck"
                c["verified_accurate_corrected"] = False
                n_stayed_wrong_or_unconfirmed += 1

    # default verdict_corrected for comps that were already accurate on pass 1
    for p in d["property_results"]:
        for c in p["comps"]:
            if "verdict_corrected" not in c:
                c["verdict_corrected"] = c["verdict"]
                c["verified_accurate_corrected"] = c["verified_accurate"]

    all_comps = [c for p in d["property_results"] for c in p["comps"]]
    n_total = len(all_comps)
    n_verified_corrected = sum(1 for c in all_comps if c["verified_accurate_corrected"])
    verdict_counts_corrected = {}
    for c in all_comps:
        v = c["verdict_corrected"]
        verdict_counts_corrected[v] = verdict_counts_corrected.get(v, 0) + 1

    # Recompute dollar impact with corrected verdicts
    per_property_dollar_corrected = []
    for p in d["property_results"]:
        board_prices = [c["claimed"]["sold_price"] for c in p["comps"] if c["claimed"].get("sold_price")]
        verified_prices = []
        for c in p["comps"]:
            if not c["verified_accurate_corrected"]:
                continue
            if c.get("corroboration_pass") and c["corroboration_pass"].get("real_price"):
                verified_prices.append(c["corroboration_pass"]["real_price"])
            elif c.get("real") and c["real"].get("matched_sale") and c["real"]["matched_sale"].get("price"):
                verified_prices.append(c["real"]["matched_sale"]["price"])
        board_avg = sum(board_prices) / len(board_prices) if board_prices else None
        verified_avg = sum(verified_prices) / len(verified_prices) if verified_prices else None
        per_property_dollar_corrected.append({
            "parcel_id": p["parcel_id"],
            "board_comp_avg": round(board_avg, 0) if board_avg else None,
            "verified_comp_avg": round(verified_avg, 0) if verified_avg else None,
            "n_verified_comps": len(verified_prices),
        })

    props_zero_verified = [x for x in per_property_dollar_corrected if x["n_verified_comps"] == 0]
    both = [x for x in per_property_dollar_corrected if x["board_comp_avg"] is not None and x["verified_comp_avg"] is not None]
    deltas = [x["verified_comp_avg"] - x["board_comp_avg"] for x in both]
    mean_board = sum(x["board_comp_avg"] for x in both) / len(both) if both else None
    mean_verified = sum(x["verified_comp_avg"] for x in both) / len(both) if both else None

    corrected_summary = {
        "n_total_comp_entries_checked": n_total,
        "n_flipped_to_verified_on_arcgis_crosscheck": n_flipped_to_verified,
        "n_stayed_wrong_or_unconfirmed_on_crosscheck": n_stayed_wrong_or_unconfirmed,
        "verdict_counts_corrected": verdict_counts_corrected,
        "n_verified_accurate_corrected": n_verified_corrected,
        "pct_verified_accurate_corrected_of_total": round(100 * n_verified_corrected / n_total, 1),
        "n_properties_zero_verified_comps_corrected": len(props_zero_verified),
        "pct_properties_zero_verified_comps_corrected": round(100 * len(props_zero_verified) / len(d["property_results"]), 1),
        "mean_board_comp_avg_dollars_corrected": round(mean_board, 0) if mean_board else None,
        "mean_verified_comp_avg_dollars_corrected": round(mean_verified, 0) if mean_verified else None,
        "mean_delta_dollars_corrected": round(sum(deltas) / len(deltas), 0) if deltas else None,
        "median_delta_dollars_corrected": round(sorted(deltas)[len(deltas) // 2], 0) if deltas else None,
        "mean_pct_delta_corrected": round(100 * sum((x["verified_comp_avg"] - x["board_comp_avg"]) / x["board_comp_avg"] for x in both) / len(both), 1) if both else None,
        "n_matched_pairs_corrected": len(both),
    }

    d["corroboration_pass_summary"] = corrected_summary
    d["per_property_dollar_impact_corrected"] = per_property_dollar_corrected
    RESULTS.write_text(json.dumps(d, indent=2, default=str))
    print(json.dumps(corrected_summary, indent=2))

if __name__ == "__main__":
    main()
