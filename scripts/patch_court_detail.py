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
from foreclosure_scraper.web_artifact import (
    BoardLockBusy, _to_dict, board_lock, read_board_json,
)

REPO = Path(__file__).resolve().parent.parent


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
    # THE LOCK. This script rewrites docs/listings.json in place, so it is a
    # board writer like any other and must not run beside one — the loser's work
    # is silently reverted, with no error anywhere. It also runs for up to
    # COURT_MAX_SECONDS=3600 by default, which is more than long enough to
    # straddle the noon and 2pm scheduled passes. See web_artifact.board_lock.
    try:
        with board_lock(REPO, owner="patch_court_detail.py"):
            return await _run()
    except BoardLockBusy as exc:
        print(f"{exc} — skipping.", flush=True)
        return 0


async def _run() -> int:
    os.environ.setdefault("NC_ECOURTS_INCREMENTAL", "1")
    os.environ.setdefault("SC_COURT_INCREMENTAL", "1")
    budget = float(os.environ.get("COURT_MAX_SECONDS", "3600"))

    path = Path("docs/listings.json")
    # read_board_json, not json.loads: on a fresh clone (or any checkout where
    # the >100MB uncompressed twin has not been rebuilt) only the committed
    # listings.json.gz exists, and reading the plain path raises there.
    data = read_board_json(path)
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

    # THIS SCRIPT DOES NOT PUBLISH. Unconditionally, by design, always.
    #
    # Same shape as patch_owner_mailing.py / patch_distress_score.py: a board
    # writer that BYPASSES write_artifact(), mutating docs/listings.json in place
    # and regenerating only listings.json.gz. It cannot regenerate
    # docs/listings_slim.json.gz or docs/detail_shards/, the index-aligned
    # payloads phones fetch, so pushing the board without them ships a fresh
    # board beside a slim file and a shard set describing the PREVIOUS one:
    # phones go silently stale on sale dates and case detail, and because a
    # shard is joined to the board BY ARRAY INDEX, any change to the record
    # count or order hands one lead's comps, vision and CAMA to a different
    # lead's address. Desktop looks perfect throughout.
    #
    # WHAT USED TO BE HERE was `if (docs/listings_slim.json.gz).exists() or
    # (docs/detail_shards).exists(): return 0`, followed by a git
    # add/commit/push block gated on COURT_PUBLISH. The comment described that
    # as a conditional guard. It has not been conditional since both payloads
    # started shipping on every publish — both always exist, the branch always
    # fires, and the publish block below it was dead code that nothing had
    # reached in months.
    #
    # NOTHING IS LOST BY NOT PUBLISHING. The mutation is persisted to
    # docs/listings.json, and the next write_artifact() caller (the daily vision
    # pass, the noon lrcpwa pass, run_local.sh, recompute_valuation.py) loads it
    # through load_board() and re-emits board + detail + slim + shards together
    # from one payload. The case detail ships on the next publish, joined
    # correctly.
    print(f"[{time.strftime('%H:%M:%S')}] docs/listings.json updated in place "
          f"({tagged} cases). NOT PUBLISHING — this script cannot regenerate "
          "docs/listings_slim.json.gz or docs/detail_shards/, and shipping the "
          "board without them mis-joins every phone.\n"
          "  It will go live on the next write_artifact() publish (the daily "
          "vision pass, the noon lrcpwa pass, or run_local.sh).\n"
          "  To publish now:  uv run python scripts/recompute_valuation.py",
          flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
