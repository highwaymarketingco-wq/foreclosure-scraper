#!/usr/bin/env python3
"""Source composition per county per signal family, split by lead class
(DISTRESSED vs FORECLOSURE/flip), reflecting the 2026-09-15 scope-policy
split: flip-type leads (FORECLOSURE_SALE/AUCTION/SHERIFF_SALE/HOA_SALE/REO)
stay narrow-footprint; everything else (DISTRESSED bucket) is now admitted
anywhere in NC/SC.

Writes scripts/_source_signal_county_matrix.json (gitignored, regenerate
on demand) -- feed it to a "matrix.js" (`const MATRIX = <json>;`) for the
"County signal ledger" artifact dashboard built 2026-09-15, or read it
directly for a quick per-county/per-signal source breakdown.

    python scripts/source_signal_county_matrix.py
"""
from __future__ import annotations

import gzip
import json
import sys
from collections import defaultdict
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "src"))

BOARD = REPO / "docs" / "listings.json.gz"

FLIP_TYPES = {"foreclosure_sale", "auction", "sheriff_sale", "hoa_sale", "reo"}

SIGNAL_FAMILIES = {
    "tax_delinquent": ("delinquent_tax", "tax_delinquent", "ptscloud", "pdf_delinquent",
                       "csv_delinquent", "multi_year", "qpaybill", "flc", "tax_sale",
                       "rutherford_tax", "paystar_tax", "delinquent_parcels", "forfeited_land",
                       "overage_claims", "buncombe_tax"),
    "tax_foreclosure": ("tax_foreclos", "kania", "zacchaeus", "upset"),
    "mortgage_foreclosure": ("hutchens", "brock_scott", "shapiro", "substitute_trustee",
                             "foreclosure_sale", "sheriff", "trustee", "mie_advert", "auction",
                             "master_in_equity", "rogers_townsend", "bell_carrington",
                             "rutherford_foreclosure"),
    "lis_pendens": ("lis_pendens", "public_index"),
    "probate_estate": ("probate", "estate", "obitu", "funeral", "deceased"),
    "code_vacancy": ("code_violation", "condemn", "vacant", "min_housing", "demoli",
                     "zombie", "nuisance", "code_enforcement", "arcgis_distress",
                     "charlotte_open_data", "civicengage"),
    "bankruptcy": ("bankruptcy", "courtlistener"),
    "divorce": ("divorce", "marriage", "separation"),
    "liens_judgments": ("lien", "judgment", "ucc", "ecourts_judgment", "dew_lien",
                        "rod_acclaim", "rod_cott", "rod_logan", "rod_substitute"),
    "reo_bank_owned": ("_reo", "homepath", "homesteps", "hubzu", "auction_dot_com",
                        "auction_bank_reo", "gsa_surplus", "cash_buyer", "zillow",
                        "foreclosure_dot_com", "landwatch", "landandfarm", "homeharvest",
                        "usda_properties", "crexi", "xome", "servicelink"),
    "environmental": ("epa_frs", "state_contamination", "epa_superfund", "brownfield",
                      "ust_registry"),
    "disaster": ("fema_disaster", "helene", "wildfire", "storm"),
    "elderly_disabled_exemption": ("_elderly",),
    "rental_permit_lapsed": ("str_permits",),
    "other_court": ("sc_public_index", "nc_ecourts", "public_notice", "column_legal",
                    "weekly_legals"),
    "hud_section8": ("hud_reac", "hud_section8"),
}


def _family(source: str) -> str:
    low = (source or "").lower()
    for fam, pats in SIGNAL_FAMILIES.items():
        if any(p in low for p in pats):
            return fam
    return "other"


def stream(path: Path):
    """Rows of the board at `path` (docs/listings.json.gz), one at a time. The board is now
    published as parts (docs/listings_part_NNN.json.gz, audit O1): board_stream.iter_board_rows reads
    the parts beside `path` in order (checked against docs/board.manifest.json), and reads `path`
    itself as one gzipped array when there are none."""
    from foreclosure_scraper.board_stream import iter_board_rows
    yield from iter_board_rows(path)


def main() -> int:
    # bucket -> county_key -> family -> source -> count
    data = {
        "distressed": defaultdict(lambda: defaultdict(lambda: defaultdict(int))),
        "foreclosure": defaultdict(lambda: defaultdict(lambda: defaultdict(int))),
    }
    county_state = {}
    total_rows = 0
    no_county = {"distressed": 0, "foreclosure": 0}

    for r in stream(BOARD):
        total_rows += 1
        ltype = (r.get("listing_type") or "").lower()
        bucket = "foreclosure" if ltype in FLIP_TYPES else "distressed"

        cty = (r.get("county") or "").replace(" County", "").strip()
        st = (r.get("state") or "").strip().upper()
        if not cty or not st or st not in ("NC", "SC"):
            no_county[bucket] += 1
            continue
        ck = f"{cty},{st}"
        county_state[ck] = st

        fam = _family(r.get("source") or "")
        src = r.get("source") or "unknown"
        data[bucket][ck][fam][src] += 1

    out = {"generated_rows": total_rows, "no_county_or_out_of_state": no_county, "buckets": {}}
    for bucket in ("distressed", "foreclosure"):
        counties_out = {}
        for ck, fams in data[bucket].items():
            fam_out = {}
            county_total = 0
            for fam, sources in fams.items():
                fam_total = sum(sources.values())
                county_total += fam_total
                fam_out[fam] = {
                    "total": fam_total,
                    "sources": dict(sorted(sources.items(), key=lambda kv: -kv[1])),
                }
            counties_out[ck] = {
                "state": county_state[ck],
                "total": county_total,
                "families": fam_out,
            }
        out["buckets"][bucket] = counties_out

    with open(REPO / "scripts" / "_source_signal_county_matrix.json", "w") as f:
        json.dump(out, f)

    for bucket in ("distressed", "foreclosure"):
        n_counties = len(out["buckets"][bucket])
        n_rows = sum(c["total"] for c in out["buckets"][bucket].values())
        print(f"{bucket}: {n_counties} counties, {n_rows:,} rows "
              f"(+{no_county[bucket]:,} no-county/out-of-state)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
