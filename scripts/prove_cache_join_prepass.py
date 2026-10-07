#!/usr/bin/env python3
"""Why the normal pipeline left board rows without the owner mailing their parcel cache holds,
and what the enrich_gis_attrs cache pre-pass (parcel_cache_join.join_listings) fills. READ-ONLY.

One streaming pass of the board (board_stream.iter_board_rows; no load_board, nothing written).
For every row with a parcel id and no owner mailing whose county cache holds a mailing for that
parcel ("the gap"), it records which gate of the OLD per-lead code path stopped the lookup:

  overage        TAX_SALE_OVERAGE rows (skipped by design)
  queried        raw["gis"]["queried"] set by an earlier run: returned before the cache lookup
  core_complete  value + owner + sqft already present: returned before the cache lookup
  reached        would reach the per-lead cache block (then only RIDES ON the batch/timeout cap)

then runs the new pre-pass on a bounded sample of gap rows (--sample, default 5,000, spread
across counties) and prints before/after mailing counts. Counts only: no names, addresses or ids.

    python scripts/prove_cache_join_prepass.py --sample 5000
"""
from __future__ import annotations

import argparse
import sys
from collections import Counter, defaultdict
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "src"))
sys.path.insert(0, str(REPO / "scripts"))

from foreclosure_scraper import parcel_cache as pc  # noqa: E402
from foreclosure_scraper.board_stream import iter_board_rows  # noqa: E402
from foreclosure_scraper.models import Listing  # noqa: E402
from foreclosure_scraper.parcel_cache_join import join_listings  # noqa: E402
from measure_parcel_cache_lift import has_mailing  # noqa: E402


def _d(v) -> dict:
    return v if isinstance(v, dict) else {}


def gate(row: dict) -> str:
    raw = _d(row.get("raw"))
    if str(row.get("listing_type") or "") == "tax_sale_overage":
        return "overage"
    if (row.get("assessed_value") or row.get("market_value")) and row.get("owner_name") \
            and row.get("living_sqft"):
        return "core_complete"
    if _d(raw.get("gis")).get("queried"):
        return "queried"
    return "reached"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--board", default="docs/listings.json.gz")
    ap.add_argument("--sample", type=int, default=5000)
    ap.add_argument("--per-county", type=int, default=800)
    a = ap.parse_args()

    gaps = Counter()
    gates = Counter()
    by_county = Counter()
    sample: list[dict] = []
    per = defaultdict(int)
    total = with_pid = 0
    for row in iter_board_rows(a.board):
        total += 1
        pid = row.get("parcel_id")
        if not pid:
            continue
        with_pid += 1
        raw = _d(row.get("raw"))
        if has_mailing(raw):
            continue
        county = (row.get("county") or "").replace(" County", "").strip()
        if not county:
            continue
        try:
            hit = pc.lookup(county, pid, row.get("state"))
        except Exception:  # noqa: BLE001
            continue
        if not hit or not hit.get("owner_mailing"):
            continue
        key = f"{row.get('state')}:{county}"
        gaps["gap rows"] += 1
        by_county[key] += 1
        g = gate(row)
        gates[g] += 1
        if len(sample) < a.sample and per[key] < a.per_county:
            per[key] += 1
            sample.append(row)

    print(f"board rows {total:,}; with parcel id {with_pid:,}")
    print(f"gap (parcel id, no mailing, cache holds mailing): {gaps['gap rows']:,}")
    print("gate that stopped the old per-lead lookup:")
    for k, n in gates.most_common():
        print(f"  {n:>8,}  {k}")
    print("top counties:", ", ".join(f"{k} {n:,}" for k, n in by_county.most_common(12)))

    rows = [Listing.model_validate(r) for r in sample]
    before = sum(has_mailing(li.raw if isinstance(li.raw, dict) else {}) for li in rows)
    c = join_listings(rows)
    after = sum(has_mailing(li.raw if isinstance(li.raw, dict) else {}) for li in rows)
    print(f"\nbounded sample: {len(rows):,} gap rows from {len(per)} counties")
    print(f"  owner mailing before {before:,}  after {after:,}  (+{after - before:,})")
    for k in ("cache HIT", "filled owner mailing", "flagged absentee", "filled year built",
              "filled last sale", "filled market value",
              "skipped: parcel id shared by many distinct addresses",
              "mailing withheld: parcel owner differs from the lead's party",
              "skipped: tax_sale_overage, owner != cache owner"):
        print(f"  {c.get(k, 0):>8,}  {k}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
