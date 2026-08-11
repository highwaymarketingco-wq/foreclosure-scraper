"""Scheduled land-records refresh — fills the lrcpwa addresses + assessed values
+ absentee flags + county building PHOTOS that were deferred when the
lrcpwa.ncptscloud.com API rate-limited during heavy same-day testing, then
recomputes the strategy + buyer-match tags. Runs on the committed board (no
re-scrape); the shell wrapper commits + pushes.

Board-writer — the wrapper guards against running while the weekly/merge is
active. Safe + idempotent: lrcpwa skips leads that already have an address,
photos skip files already on disk.
"""
from __future__ import annotations

import asyncio
import json
from pathlib import Path

from foreclosure_scraper.models import Listing
from foreclosure_scraper.enrichment_lrcpwa_parcel import enrich_lrcpwa_parcel
from foreclosure_scraper.enrichment_lrcpwa_photo import enrich_lrcpwa_photo
from foreclosure_scraper.enrichment_strategy_fit import enrich_strategy_fit
from foreclosure_scraper.enrichment_buyer_match import enrich_buyer_match
from foreclosure_scraper.valuation import calc as vcalc, grading as vgrade
from foreclosure_scraper.web_artifact import (
    BoardLockBusy, board_lock, load_board, write_artifact,
)

REPO = Path(__file__).resolve().parent.parent
DOCS = REPO / "docs"


def main() -> int:
    # THE LOCK, held across load_board -> enrich -> write_artifact.
    #
    # Reentrant: scripts/lrcpwa_refresh.sh already holds it when it invokes this
    # script and passes it down through FORECLOSURE_BOARD_LOCK_HELD, so this
    # acquire is a no-op there. It matters when the pass is run by hand.
    #
    # This is the job that got reverted on 2026-08-10: 1,064 parcels resolved,
    # 343 county values, 410 absentee tags, published — and then overwritten by
    # the 09:30 vision job writing back the board it had loaded at 09:33.
    try:
        with board_lock(REPO, owner="lrcpwa_refresh.py"):
            return _run()
    except BoardLockBusy as exc:
        print(f"{exc} — skipping this pass.", flush=True)
        return 0


def _run() -> int:
    listings = load_board(DOCS)  # merges lazy-detail sidecar back so it round-trips
    b_addr = sum(1 for l in listings if (l.street_address or "").strip())
    print(f"loaded {len(listings)} | before addr={b_addr}", flush=True)

    async def go():
        print("lrcpwa_parcel:", await enrich_lrcpwa_parcel(listings), flush=True)
        print("lrcpwa_photo:", await enrich_lrcpwa_photo(listings), flush=True)
    asyncio.run(go())

    # recompute value/grade on the leads lrcpwa just valued
    for li in listings:
        try:
            c = vcalc.compute(li); g = vgrade.grade(li, c)
            if not isinstance(li.raw, dict):
                li.raw = {}
            li.raw["calc"] = vcalc.to_dict(c); li.raw["grade"] = vgrade.to_dict(g)
        except Exception:  # noqa: BLE001
            pass
    print("strategy_fit:", enrich_strategy_fit(listings), flush=True)
    print("buyer_match:", enrich_buyer_match(listings), flush=True)

    a_addr = sum(1 for l in listings if (l.street_address or "").strip())
    photos = sum(1 for l in listings if ((l.raw or {}).get("images") or {}).get("real"))
    write_artifact(listings, {"notes": "scheduled land-records refresh"}, docs_dir=DOCS)
    print(f"wrote board | addr={a_addr}(+{a_addr - b_addr}) real_photos={photos}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
