"""Backfill owner + mailing + absentee/out-of-state onto the existing board.

The #0 contactability fix. Runs enrich_owner_mailing over docs/listings.json
(county ArcGIS REST, free, no token), fills raw['owner_mailing'] + parcel_id,
re-grades, and republishes. Incremental: skips listings already filled.
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
from foreclosure_scraper.enrichment_owner_mailing import enrich_owner_mailing
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
    path = Path("docs/listings.json")
    data = json.loads(path.read_text())
    listings, by_id = [], {}
    for d in data:
        li = _hydrate(d)
        if li:
            listings.append(li)
            by_id[id(li)] = d
    print(f"[{time.strftime('%H:%M:%S')}] loaded {len(listings)}", flush=True)

    t0 = time.time()
    counts = await enrich_owner_mailing(listings, max_concurrency=int(os.environ.get("OM_CONCURRENCY", "6")))
    print(f"[{time.strftime('%H:%M:%S')}] owner/mailing: {counts} in {int(time.time()-t0)}s", flush=True)

    for li in listings:
        d = by_id[id(li)]
        d["raw"] = _to_dict(li)["raw"]
        if li.parcel_id:
            d["parcel_id"] = li.parcel_id

    path.write_text(json.dumps(data, ensure_ascii=False, default=str), encoding="utf-8")
    mailable = sum(1 for x in data if (x.get("raw") or {}).get("owner_mailing", {}).get("mailing"))
    print(f"[{time.strftime('%H:%M:%S')}] wrote — mailable now {mailable}", flush=True)

    import gzip as _gz  # regen the .gz the dashboard fetches (listings.json is gitignored)
    _p = Path("docs/listings.json")
    (_p.parent / "listings.json.gz").write_bytes(_gz.compress(_p.read_bytes(), compresslevel=9, mtime=0))

    # This script is a board writer that BYPASSES write_artifact(): it mutates
    # docs/listings.json in place and regenerates only listings.json.gz. It
    # therefore cannot regenerate docs/listings_slim.json.gz, the index-aligned
    # mobile payload write_artifact() emits. Publishing here would ship a fresh
    # board next to a slim file describing the PREVIOUS board — phones would show
    # stale owner/mailing data while desktop showed the new data, silently.
    # So once the slim payload exists, refuse to publish. Nothing is lost: the
    # mutation is already persisted to docs/listings.json, and the next
    # write_artifact() caller re-emits board + slim together from one payload.
    if (_p.parent / "listings_slim.json.gz").exists():
        print(f"[{time.strftime('%H:%M:%S')}] NOT PUBLISHING: docs/listings.json was "
              "updated in place, but this script cannot regenerate "
              "docs/listings_slim.json.gz (the mobile payload), which would go "
              "stale against the board.\n"
              "  Next step:  python scripts/regenerate_dashboard.py\n"
              "  That calls write_artifact(), which re-emits listings.json.gz, "
              "listings_detail.json.gz and listings_slim.json.gz from one payload.\n"
              "  Then publish (or just let the next daily job publish it).",
              flush=True)
        return 0

    if os.environ.get("OM_PUBLISH", "1") == "1":
        import subprocess
        root = str(Path(__file__).parent.parent)
        subprocess.run(["git", "add", "docs/listings.json.gz"], cwd=root, check=False)
        if subprocess.run(["git", "diff", "--staged", "--quiet"], cwd=root).returncode != 0:
            subprocess.run(["git", "commit", "-q", "-m",
                            f"owner/mailing backfill: {mailable} mailable ({time.strftime('%Y-%m-%d')})"], cwd=root, check=False)
            subprocess.run(["git", "pull", "--rebase", "--autostash", "origin", "main"], cwd=root, check=False)
            p = subprocess.run(["git", "push", "origin", "main"], cwd=root)
            print("published ✓" if p.returncode == 0 else "push failed ⚠", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
