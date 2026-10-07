#!/usr/bin/env python3
"""Per county: what the parcel cache join (parcel_cache_join.join_listings, run by
enrich_gis_attrs every pipeline run) would fill on the current board. READ-ONLY, counts only.

One streaming pass of the board (no load_board, nothing written). For every row with a parcel id
in the named counties (default: every county) it looks the parcel up in its cache (layer cache
plus any county-roll sidecar) and counts, per field, rows missing the field and rows the cache
would fill: owner mailing (respecting the owner_agrees=False withholding), year built, bedrooms,
bathrooms, living sqft, last sale, market value.

    python scripts/measure_cache_facts_lift.py --counties NC:Gaston,NC:Transylvania,SC:Dorchester
    python scripts/measure_cache_facts_lift.py --json /tmp/facts_lift.json
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "src"))
sys.path.insert(0, str(REPO / "scripts"))

from foreclosure_scraper import parcel_cache as pc  # noqa: E402
from foreclosure_scraper.board_stream import iter_board_rows  # noqa: E402
from measure_parcel_cache_lift import has_mailing  # noqa: E402

FIELDS = ("mailing", "year_built", "bedrooms", "bathrooms", "living_sqft", "last_sale", "market_value")


def _d(v) -> dict:
    return v if isinstance(v, dict) else {}


def _has(row: dict, f: str) -> bool:
    raw = _d(row.get("raw"))
    if f == "mailing":
        return has_mailing(raw)
    if f == "last_sale":
        return bool(_d(_d(raw.get("gis")).get("last_sale")).get("amount"))
    try:
        return float(row.get(f) or 0) > 0
    except (TypeError, ValueError):
        return False


def _cache_has(hit: dict, f: str, row: dict) -> bool:
    if f == "mailing":
        pfa = _d(_d(row.get("raw")).get("parcel_from_address"))
        return bool(hit.get("owner_mailing")) and pfa.get("owner_agrees") is not False
    if f == "last_sale":
        return bool(pc.sale_amount(hit.get("sale_price")))
    v = hit.get(f)
    try:
        v = float(v)
    except (TypeError, ValueError):
        return False
    if f == "year_built":
        return 1700 < v <= 2100
    return v > 0


def measure(rows, wanted: set[str] | None) -> dict:
    out: dict = defaultdict(Counter)
    for row in rows:
        county = (row.get("county") or "").replace(" County", "").strip()
        key = f"{row.get('state')}:{county}"
        if wanted and key not in wanted:
            continue
        c = out[key]
        c["rows"] += 1
        if str(row.get("listing_type") or "") == "tax_sale_overage":
            continue
        pid = row.get("parcel_id")
        if not pid or not county:
            continue
        c["parcel_id"] += 1
        try:
            hit = pc.lookup(county, pid, row.get("state"))
        except Exception:  # noqa: BLE001
            hit = None
        if hit:
            c["cache_hit"] += 1
            if hit.get("roll_fields"):
                c["roll_hit"] += 1
        for f in FIELDS:
            have = _has(row, f)
            c[f"{f}_before"] += have
            if not have and hit and _cache_has(hit, f, row):
                c[f"{f}_fill"] += 1
    return {k: dict(v) for k, v in sorted(out.items())}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--counties", default="", help="comma list of ST:County (default all)")
    ap.add_argument("--board", default="docs/listings.json.gz")
    ap.add_argument("--json")
    a = ap.parse_args()
    wanted = {x.strip() for x in a.counties.split(",") if x.strip()} or None
    res = measure(iter_board_rows(a.board), wanted)
    tot = Counter()
    for k, c in res.items():
        tot.update(c)
        if wanted or any(c.get(f"{f}_fill") for f in FIELDS):
            fills = ", ".join(f"{f} +{c.get(f + '_fill', 0):,} (had {c.get(f + '_before', 0):,})"
                              for f in FIELDS if c.get(f + "_fill"))
            print(f"{k:22} rows {c['rows']:>7,} pid {c.get('parcel_id', 0):>7,} hit {c.get('cache_hit', 0):>7,}  {fills}")
    print("TOTAL fills:", ", ".join(f"{f} +{tot.get(f + '_fill', 0):,}" for f in FIELDS))
    if a.json:
        Path(a.json).write_text(json.dumps(res, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
