#!/usr/bin/env python3
"""Live proof for gis_fill.py on real board rows (counts only, nothing written back).

Streams a checkpoint's board once (never loads it whole), takes up to N rows per (state, county) that
gis_fill.needs(), runs the real enricher on those Listings and prints per-county counts: rows asked,
rows whose parcel was in the layer, deed / legal / value / acreage found, the 'none' verdicts. No
parcel id, owner or value is printed or written. At least 2 s between requests to one host (gis_fill's
own gate), one request at a time per host.

    uv run python scripts/top80_fill_proof.py --checkpoint data/checkpoint --per-county 8 \
        --counties NC:Alamance,SC:Berkeley
    uv run python scripts/top80_fill_proof.py --checkpoint data/checkpoint --per-county 6 --all-registered
"""
from __future__ import annotations

import argparse
import asyncio
import collections
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))
sys.path.insert(0, str(REPO / "scripts"))


def pick(ckpt: Path, per: int, only: set[tuple[str, str]] | None):
    import board_selfcheck as bs
    from datetime import datetime, timezone
    from foreclosure_scraper import gis_fill as G
    from foreclosure_scraper.models import Listing
    now = datetime.now(timezone.utc)
    got: dict[tuple[str, str], list] = collections.defaultdict(list)
    for rec in bs._checkpoint_rows(ckpt):
        st = str(rec.get("state") or "").upper()
        co = G.county_name(Listing.model_construct(county=rec.get("county")))
        key = (st, co)
        if only is not None and key not in only:
            continue
        if len(got[key]) >= per:
            continue
        try:
            li = Listing.model_validate(rec)
        except Exception:  # noqa: BLE001
            continue
        if G.needs(li, now):
            got[key].append(li)
    return got


async def main_async(args) -> int:
    from foreclosure_scraper import gis_fill as G
    only = None
    if args.counties:
        only = {tuple(x.split(":", 1)) for x in args.counties.split(",")}
        only = {(s.upper(), c) for s, c in only}
    elif args.all_registered:
        only = {("SC", c) for c in G.SC_FILL}
    got = pick(Path(args.checkpoint), args.per_county, only)
    rows = []
    out = {}
    for (st, co), lis in sorted(got.items()):
        if only is None and st == "NC" and len([k for k in out if k[0] == "NC"]) >= args.max_nc:
            continue
        before = {id(li): None for li in lis}
        stats = await G.enrich_gis_fill(lis, budget_s=args.budget)
        n = len(lis)
        blocks = [(li.raw or {}).get("gis_fill") or {} for li in lis]
        out[(st, co)] = dict(
            asked=n, screened=stats["screened"], in_layer=sum(1 for b in blocks if b.get("found")),
            deed=sum(1 for li in lis if (li.raw or {}).get("county_deed_ref")),
            legal=sum(1 for li in lis if (li.raw or {}).get("county_legal")),
            value=stats["value"], acres=stats["acres"],
            none_deed=sum(1 for b in blocks if b.get("deed") == "none"),
            none_legal=sum(1 for b in blocks if b.get("legal") == "none"),
            requests=stats["requests"], closed=stats["closed_layers"])
        print(f"{st}|{co}: {json.dumps(out[(st, co)])}", flush=True)
    tot = collections.Counter()
    for v in out.values():
        for k in ("asked", "screened", "in_layer", "deed", "legal", "value", "acres", "none_deed", "none_legal"):
            tot[k] += v[k]
    print("TOTAL", dict(tot))
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--checkpoint", default="data/checkpoint")
    ap.add_argument("--per-county", type=int, default=8)
    ap.add_argument("--counties", default="")
    ap.add_argument("--all-registered", action="store_true")
    ap.add_argument("--max-nc", type=int, default=12)
    ap.add_argument("--budget", type=float, default=600.0)
    return asyncio.run(main_async(ap.parse_args()))


if __name__ == "__main__":
    raise SystemExit(main())
