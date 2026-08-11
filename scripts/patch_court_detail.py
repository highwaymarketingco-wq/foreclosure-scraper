"""Daily incremental court-detail pass over docs/listings.json.

Drills into per-case court records to capture judgment / balance / sale
documents / sale_status (incl. the confirmed-sold flag that filters
already-sold properties off the board). Browser-based (Tyler + SC Public
Index sit behind anti-bot), so LOCAL-only and capped per run; incremental
(skips already-enriched cases) so coverage builds across days like vision.

  NC_ECOURTS_INCREMENTAL=1 NC_ECOURTS_AUTH_CAP=150 \
  SC_COURT_INCREMENTAL=1 SC_COURT_CAP=80 \
    uv run python scripts/patch_court_detail.py
"""
from __future__ import annotations

import asyncio
import json
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from foreclosure_scraper.models import Listing, ListingType, PropertyKind
from foreclosure_scraper.valuation import calc as vcalc
from foreclosure_scraper.valuation import grading as vgrade
from foreclosure_scraper.web_artifact import _to_dict


def _hydrate(d: dict) -> Listing | None:
    fields = {k: v for k, v in d.items() if k in Listing.model_fields}
    for ef, enum in (("listing_type", ListingType), ("property_kind", PropertyKind)):
        if isinstance(fields.get(ef), str):
            try:
                fields[ef] = enum(fields[ef])
            except ValueError:
                fields.pop(ef, None)
    try:
        li = Listing.model_validate(fields)
    except Exception:
        return None
    li.raw = d.get("raw") or {}
    return li


async def main() -> int:
    os.environ.setdefault("NC_ECOURTS_INCREMENTAL", "1")
    os.environ.setdefault("SC_COURT_INCREMENTAL", "1")
    budget = float(os.environ.get("COURT_MAX_SECONDS", "3600"))

    path = Path("docs/listings.json")
    data = json.loads(path.read_text())
    listings: list[Listing] = []
    by_id: dict[int, dict] = {}
    for d in data:
        li = _hydrate(d)
        if li:
            listings.append(li)
            by_id[id(li)] = d
    print(f"[{time.strftime('%H:%M:%S')}] loaded {len(listings)} listings", flush=True)

    from foreclosure_scraper.enrichment_nc_case_status_tyler import (
        enrich_with_nc_case_status_authenticated)
    from foreclosure_scraper.enrichment_case_detail import enrich_case_detail_addresses

    t0 = time.time()
    try:
        await asyncio.wait_for(asyncio.gather(
            enrich_with_nc_case_status_authenticated(listings),
            enrich_case_detail_addresses(listings),
        ), timeout=budget)
    except asyncio.TimeoutError:
        print(f"[{time.strftime('%H:%M:%S')}] court pass hit cap ({budget:.0f}s) — writing partial", flush=True)
    except Exception as exc:
        print(f"[{time.strftime('%H:%M:%S')}] court pass error: {str(exc)[:160]}", flush=True)
    print(f"[{time.strftime('%H:%M:%S')}] court pass done in {int(time.time()-t0)}s", flush=True)

    tagged = 0
    for li in listings:
        d = by_id[id(li)]
        if (li.raw or {}).get("court_sale_status") or (li.raw or {}).get("nc_case_status"):
            try:
                c = vcalc.compute(li)
                g = vgrade.grade(li, c)
                li.raw["calc"] = vcalc.to_dict(c)
                li.raw["grade"] = vgrade.to_dict(g)
            except Exception:
                pass
            tagged += 1
        d["raw"] = _to_dict(li)["raw"]
        if li.judgment_amount is not None:
            d["judgment_amount"] = li.judgment_amount
        if li.street_address:
            d["street_address"] = li.street_address

    path.write_text(json.dumps(data, ensure_ascii=False, default=str), encoding="utf-8")
    print(f"[{time.strftime('%H:%M:%S')}] wrote {path} — {tagged} listings carry court detail", flush=True)
    import gzip as _gz  # regen the .gz the dashboard fetches (listings.json is gitignored)
    _p = Path("docs/listings.json")
    (_p.parent / "listings.json.gz").write_bytes(_gz.compress(_p.read_bytes(), compresslevel=9, mtime=0))

    # Same shape as patch_owner_mailing.py / patch_distress_score.py: this is a
    # board writer that BYPASSES write_artifact(), mutating docs/listings.json in
    # place and regenerating only listings.json.gz. It cannot regenerate
    # docs/listings_slim.json.gz, the index-aligned payload phones fetch, so
    # publishing here would ship a fresh board beside a slim file describing the
    # PREVIOUS one — phones silently stale on sale dates and case detail while
    # desktop shows current. Nothing is lost by refusing: the mutation is already
    # on disk, and the next write_artifact() caller re-emits all four together.
    #
    # docs/detail_shards/ is under the identical rule and is checked separately
    # rather than assumed to travel with the slim file: they are independent
    # emits (either can fail or be switched off alone), and a shard set is joined
    # to the board BY ARRAY INDEX, so a board written here that reorders or
    # changes the record count would hand one lead's comps, vision and CAMA to a
    # different lead's address on every phone.
    _stale = [n for n in ("listings_slim.json.gz", "detail_shards")
              if (_p.parent / n).exists()]
    if _stale:
        print(f"[{time.strftime('%H:%M:%S')}] NOT PUBLISHING: docs/listings.json was "
              "updated in place, but this script cannot regenerate "
              f"{' or '.join('docs/' + n for n in _stale)} (the mobile payload), "
              "which would go stale against the board.\n"
              "  Next step:  python scripts/regenerate_dashboard.py\n"
              "  That calls write_artifact(), which re-emits listings.json.gz, "
              "listings_detail.json.gz, listings_slim.json.gz and "
              "detail_shards/ from one payload.",
              flush=True)
        return 0

    if os.environ.get("COURT_PUBLISH", "1") == "1":
        import subprocess
        root = str(Path(__file__).parent.parent)
        try:
            subprocess.run(["git", "add", "docs/listings.json.gz"], cwd=root, check=False)
            if subprocess.run(["git", "diff", "--staged", "--quiet"], cwd=root).returncode != 0:
                subprocess.run(["git", "commit", "-q", "-m",
                                f"daily court detail: {tagged} cases ({time.strftime('%Y-%m-%d')})"],
                               cwd=root, check=False)
                subprocess.run(["git", "pull", "--rebase", "--autostash", "origin", "main"], cwd=root, check=False)
                p = subprocess.run(["git", "push", "origin", "main"], cwd=root)
                print("dashboard published ✓" if p.returncode == 0 else "push failed ⚠", flush=True)
        except Exception as exc:
            print(f"publish error: {exc}", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
