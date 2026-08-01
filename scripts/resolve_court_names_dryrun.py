#!/usr/bin/env python
"""READ-ONLY proof that the name->property resolver works on real court leads.

Loads the published board WITHOUT the board-writing machinery, picks real
unresolved leads (default: counties_sc.sc_public_index), runs the exact resolver
logic against the live county GIS layers, and prints the measured resolution
rate plus sample matches.

IT NEVER WRITES. No load_board()/write_artifact(), no Listing is persisted, no
file is touched. Safe to run while a full engine run is in flight.

    uv run python scripts/resolve_court_names_dryrun.py --limit 40
    uv run python scripts/resolve_court_names_dryrun.py --limit 60 --county Pickens
    uv run python scripts/resolve_court_names_dryrun.py --source counties_sc.sc_public_index_export

Exit code is 0 whenever the run completes; the hit rate is data, not a pass/fail.
"""
from __future__ import annotations

import argparse
import asyncio
import gzip
import json
import random
import sys
from pathlib import Path
from typing import Any, Optional

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "src"))

from foreclosure_scraper.enrichment_address_owner_v2 import _query_owner  # noqa: E402
from foreclosure_scraper.enrichment_resolve_name_to_property import (  # noqa: E402
    SC_NO_FREE_OWNER_SEARCH,
    SC_OWNER_LAYERS,
    _county_clean,
    _endpoint_cfg,
    _lead_name,
    _layer_health,
    _row_parcel,
    _strict_matches,
    _valid_parcel,
    _valid_situs,
)
from foreclosure_scraper.http_client import client  # noqa: E402
from foreclosure_scraper.models import Listing  # noqa: E402
from foreclosure_scraper.name_normalize import (  # noqa: E402
    like_patterns,
    middle_conflict,
)


def _read_board(docs: Path) -> list[dict[str, Any]]:
    """Plain read of docs/listings.json (or the .gz). No sidecar merge, no write."""
    p = docs / "listings.json"
    if p.exists():
        return json.loads(p.read_text())
    gz = docs / "listings.json.gz"
    if gz.exists():
        return json.loads(gzip.decompress(gz.read_bytes()).decode("utf-8"))
    raise SystemExit(f"no board at {p} or {gz}")


def _pick_leads(
    records: list[dict[str, Any]], source: str, county: Optional[str], limit: int,
    seed: int,
) -> list[Listing]:
    pool: list[Listing] = []
    for rec in records:
        if rec.get("source") != source:
            continue
        if (rec.get("street_address") or "").strip() or (rec.get("parcel_id") or "").strip():
            continue
        try:
            li = Listing.model_validate(rec)
        except Exception:  # noqa: BLE001
            continue
        if county and _county_clean(li).lower() != county.lower():
            continue
        if not _lead_name(li):
            continue
        pool.append(li)
    random.Random(seed).shuffle(pool)
    return pool[:limit]


async def _resolve_one(
    c: Any, li: Listing, health: dict[str, Optional[str]],
) -> dict[str, Any]:
    out: dict[str, Any] = {
        "county": _county_clean(li), "name": _lead_name(li),
        "outcome": "", "matched_owner": "", "street": "", "parcel": "",
        "queries": 0, "middle_conflict": False,
    }
    cfg = _endpoint_cfg(li)
    if not cfg:
        out["outcome"] = "no_endpoint"
        return out
    base = cfg["base"]
    if base not in health:
        health[base] = await _layer_health(c, base)
    if health[base]:
        out["outcome"] = f"endpoint_dead:{health[base]}"
        return out
    owner_field = cfg["owner_field"]
    if not owner_field:
        out["outcome"] = "no_owner_field"
        return out

    name = _lead_name(li)
    patterns = like_patterns(name)
    if not patterns:
        out["outcome"] = "unparseable_name"
        return out
    out["queries"] = len(patterns)
    rows = await _query_owner(c, base, owner_field, patterns)
    if not rows:
        out["outcome"] = "no_rows"
        return out

    hits = _strict_matches(rows, owner_field, name)
    if not hits:
        out["outcome"] = "no_match"
        out["matched_owner"] = f"({len(rows)} rows, none strict)"
        return out

    parcels = {
        _row_parcel(r, cfg.get("parcel_field")) or str(r.get("OBJECTID") or i)
        for i, (_k, r) in enumerate(hits)
    }
    if len(hits) > 1 and len(parcels) > 1:
        out["outcome"] = "ambiguous_multi_parcel"
        out["matched_owner"] = str(hits[0][1].get(owner_field) or "").strip()
        out["parcel"] = f"{len(parcels)} parcels"
        return out

    kind, best = hits[0]
    out["matched_owner"] = str(best.get(owner_field) or "").strip()
    situs_field = cfg.get("situs_field")
    if situs_field:
        for k, v in best.items():
            if k.lower() == situs_field.lower():
                s = str(v or "").strip()
                if s and _valid_situs(s):
                    out["street"] = s
                break
    pid = _row_parcel(best, cfg.get("parcel_field"))
    if pid and _valid_parcel(pid):
        out["parcel"] = pid
    out["middle_conflict"] = middle_conflict(name, out["matched_owner"])
    out["outcome"] = kind if (out["street"] or out["parcel"]) else f"{kind}_no_parcel_data"
    return out


async def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--limit", type=int, default=40)
    ap.add_argument("--source", default="counties_sc.sc_public_index")
    ap.add_argument("--county", default=None)
    ap.add_argument("--concurrency", type=int, default=4)
    ap.add_argument("--seed", type=int, default=7)
    ap.add_argument("--docs", default=str(REPO / "docs"))
    args = ap.parse_args()

    records = _read_board(Path(args.docs))
    leads = _pick_leads(records, args.source, args.county, args.limit, args.seed)
    print(f"board={len(records)} leads  source={args.source}  sample={len(leads)}")
    if not leads:
        print("no unresolved leads matched that filter")
        return

    counties: dict[str, int] = {}
    for li in leads:
        counties[_county_clean(li)] = counties.get(_county_clean(li), 0) + 1
    print("sample by county: " + ", ".join(f"{k}={v}" for k, v in sorted(counties.items())))
    print("wired SC layers: " + ", ".join(sorted(SC_OWNER_LAYERS)))
    print("no free owner search (skipped): " + ", ".join(sorted(SC_NO_FREE_OWNER_SEARCH)))
    print()

    health: dict[str, Optional[str]] = {}
    sem = asyncio.Semaphore(args.concurrency)
    results: list[dict[str, Any]] = []

    async def run(c: Any, li: Listing) -> None:
        async with sem:
            results.append(await _resolve_one(c, li, health))

    async with client(timeout=30.0) as c:
        await asyncio.gather(*(run(c, li) for li in leads))

    tally: dict[str, int] = {}
    for r in results:
        key = r["outcome"].split(":")[0]
        tally[key] = tally.get(key, 0) + 1
    resolved = [r for r in results if r["outcome"] in ("exact", "strong")]
    ambiguous = [r for r in results if r["outcome"] == "ambiguous_multi_parcel"]

    clean = [r for r in resolved if not r["middle_conflict"]]
    flagged = [r for r in resolved if r["middle_conflict"]]

    print("=== SAMPLE MATCHES ===")
    for r in resolved[:15]:
        tag = "middle-conflict" if r["middle_conflict"] else r["outcome"]
        print(f"  [{tag:15}] {r['county']:12} {r['name']:30} -> "
              f"{r['matched_owner']:32} | {r['street'] or '(no situs field)'} "
              f"| parcel {r['parcel'] or '-'}")
    if ambiguous:
        print("\n=== FLAGGED AMBIGUOUS (kept, not committed) ===")
        for r in ambiguous[:5]:
            print(f"  {r['county']:12} {r['name']:32} -> {r['matched_owner']:34} "
                  f"| {r['parcel']}")

    print("\n=== OUTCOMES ===")
    for k, v in sorted(tally.items(), key=lambda kv: -kv[1]):
        print(f"  {k:28} {v:4}  ({v / len(results):.0%})")
    print(f"\nRESOLVED (address and/or parcel committed): "
          f"{len(resolved)}/{len(results)} = {len(resolved) / len(results):.1%}")
    print(f"  of which high-confidence (no middle-name conflict): {len(clean)}")
    print(f"  of which flagged middle_conflict=true:              {len(flagged)}")
    print(f"AMBIGUOUS (flagged, no guess):              "
          f"{len(ambiguous)}/{len(results)} = {len(ambiguous) / len(results):.1%}")
    print(f"GIS queries issued: {sum(r['queries'] for r in results)}")


if __name__ == "__main__":
    asyncio.run(main())
