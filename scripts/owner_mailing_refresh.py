"""Board-wide owner-MAILING enrichment — the #1 free contactability lever.

Fills raw['owner_mailing'] (owner + mailing address + absentee/out-of-state) from
county GIS for every lead that has a parcel/address but no mailing yet, then
recomputes distress (mailing/absentee are a HOT gate + score bump). Turns
identified owners into MAILABLE owners for free — the biggest coverage gap.

Board-writer — run alone. Loads via load_board() so the lazy sidecar round-trips.
Wall-clock capped (OWNER_MAILING_BUDGET_S) so a slow GIS host can't hang it;
leads are filled in place as it goes, so a partial run still commits real gains.
"""
from __future__ import annotations

import asyncio
import os
from pathlib import Path

from foreclosure_scraper.enrichment_owner_mailing import enrich_owner_mailing
from foreclosure_scraper.distress_score import score_board
from foreclosure_scraper.web_artifact import write_artifact, load_board

DOCS = Path(__file__).resolve().parent.parent / "docs"
BUDGET_S = float(os.environ.get("OWNER_MAILING_BUDGET_S", "3600"))
# Concurrency 2 is deliberate: county ArcGIS hosts THROTTLE at 5 (a board-wide
# conc=5 run resolved 15/13031; conc=2 resolves ~95%). Keep it low + polite.
CONC = int(os.environ.get("OWNER_MAILING_CONCURRENCY", "2"))


def _has_mail(li) -> bool:
    raw = li.raw
    if not isinstance(raw, dict):
        return False
    om = raw.get("owner_mailing")
    if not isinstance(om, dict):
        return False
    return bool(om.get("mailing"))


def main() -> int:
    listings = load_board(DOCS)
    targets = [li for li in listings
               if not _has_mail(li) and ((li.street_address or "").strip() or (li.parcel_id or "").strip())]
    b_mail = sum(1 for li in listings if _has_mail(li))
    print(f"loaded {len(listings)} | targets={len(targets)} | mailing before={b_mail}", flush=True)

    async def go():
        try:
            return await asyncio.wait_for(
                enrich_owner_mailing(targets, max_concurrency=CONC), timeout=BUDGET_S)
        except asyncio.TimeoutError:
            print(f"budget {BUDGET_S}s hit — committing partial fills", flush=True)
            return {"timed_out": True}
    print("owner_mailing:", asyncio.run(go()), flush=True)

    # stamp the offline county eviction-market signal on every lead too
    try:
        from foreclosure_scraper.enrichment_eviction_market import enrich_eviction_market
        print("eviction_market:", enrich_eviction_market(listings), flush=True)
    except Exception:  # noqa: BLE001
        pass
    # mailing/absentee affects tier -> rescore
    score_board(listings, previous_path=DOCS / "listings.json")
    a_mail = sum(1 for li in listings if _has_mail(li))
    absentee = sum(1 for li in listings
                   if isinstance(li.raw, dict)
                   and isinstance(li.raw.get("owner_mailing"), dict)
                   and li.raw["owner_mailing"].get("absentee"))
    write_artifact(listings, {"notes": "board-wide owner-mailing contactability enrichment"}, docs_dir=DOCS)
    print(f"wrote board | mailing={a_mail}(+{a_mail - b_mail}) absentee={absentee}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
