#!/usr/bin/env python3
"""Manually add a property you're actively working (bidding/watching) to the board.

WHY THIS EXISTS. The engine is broad but has structural blind spots — e.g. a
*mortgage* (power-of-sale) foreclosure in a VCAP-legacy county (no NC court
portal) that has already gone to sale and entered the 10-day upset window: its
newspaper Notice of Sale has rolled off the local paper's tiny live index, it is
not a tax foreclosure (so not in the Kania/county tax feeds), and the sites that
still list it (RealtyTrac/auction.com) are pay/bot-walled. "149 Shenandoah Dr,
Spindale NC 28160" (Rutherford) was exactly that — a real deal the operator was
bidding on that no free wired source could reach. This gives a guaranteed lane:
type the address (plus whatever you know — case #, current bid, sale/upset date,
trustee) and it lands on the board as a first-class, scored lead.

SAFETY. Acquires the same board lock a run uses, so it will REFUSE to write while
a scrape run holds it (never corrupts the board mid-run). It calls load_board()
so the vision/comps/cama sidecar is folded back in before write_artifact re-emits,
and dedupe() collapses it if a later real-source sighting arrives.

USAGE:
    python scripts/add_watchlist_property.py --dry-run      # build+enrich+print, no write
    python scripts/add_watchlist_property.py                # inject the WATCHLIST seeds
Add more properties by appending dicts to WATCHLIST (or wire argv later).
"""
from __future__ import annotations

import argparse
import collections
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from foreclosure_scraper.models import Listing, ListingType, PropertyKind  # noqa: E402
from foreclosure_scraper.dedupe import dedupe  # noqa: E402
from foreclosure_scraper.valuation import calc as vcalc, grading as vgrade  # noqa: E402
from foreclosure_scraper.distress_score import score_board  # noqa: E402
from foreclosure_scraper.web_artifact import load_board, write_artifact, board_lock  # noqa: E402

DOCS = "docs"

#: Properties to inject. Each entry: the fields you know. Only address/county/
#: state are required; everything else sharpens the lead + its valuation.
WATCHLIST: list[dict] = [
    {
        "street_address": "149 Shenandoah Dr",
        "city": "Spindale",
        "county": "Rutherford",
        "state": "NC",
        "zip_code": "28160",
        "listing_type": ListingType.FORECLOSURE_SALE,
        "property_kind": PropertyKind.SINGLE_FAMILY,
        "auction_status": "upset_bid_period",
        "foreclosure_process": "mortgage",  # power-of-sale, NCGS 45-21 (not tax)
        "sale_location": "Rutherford County Courthouse, Rutherfordton NC",
        "source_url": "https://www.movoto.com/spindale-nc/149-shenandoah-dr-spindale-nc-28160/pid_wvcpa014jh/",
        "description": ("ACTIVE UPSET BID — operator is bidding on this. Rutherford "
                        "power-of-sale foreclosure, ~3bd/1ba 1,247 sqft, est value "
                        "~$258,200. Added via watchlist: VCAP county + rolled-off "
                        "notice = free-source blind spot."),
        # facts from aggregators (Movoto/Trulia/foreclosurelistings) — for the card:
        "_facts": {"beds": 3, "baths": 1, "sqft": 1247, "lot_sqft": 6534,
                   "est_value": 258200},
        # fill these in as you learn them (leave as None otherwise):
        "case_number": None,       # e.g. "25SP000xxx"
        "current_bid": None,       # last high bid $
        "sale_date": None,         # date of the sale that opened the upset window
        "upset_bid_deadline": None,  # last day to upset
        "trustee": None,           # substitute trustee / law firm
    },
]


def _build(entry: dict) -> Listing:
    facts = entry.pop("_facts", {}) or {}
    now = datetime.utcnow()
    li = Listing(
        source="manual.watchlist",
        first_seen=now,
        last_seen=now,
        raw={"watchlist": {"added": now.isoformat(), **facts,
                           "note": "operator-entered; enrich on next full run"}},
        **{k: v for k, v in entry.items() if v is not None},
    )
    return li


def _enrich_fresh(fresh: list[Listing]) -> None:
    """Light, guarded enrichment so the manual lead is scored + valued now.

    Heavy resolvers (CAMA card, GIS owner, comps, vision) fill on the next full
    run; here we just want a map pin, a valuation, and a distress score.
    """
    import asyncio
    import inspect

    def _run(fn, arg):
        """Call an enricher whether it's sync or a coroutine function."""
        r = fn(arg)
        return asyncio.run(r) if inspect.isawaitable(r) else r

    try:
        from foreclosure_scraper.enrichment_geocode import enrich as enrich_geocode
        print("  geocode:", _run(enrich_geocode, fresh))
    except Exception as e:  # noqa: BLE001
        print("  geocode: skip", str(e)[:70])
    try:
        from foreclosure_scraper.enrichment_parcel_lookup import enrich_with_parcel_lookup
        print("  parcel_lookup:", _run(enrich_with_parcel_lookup, fresh))
    except Exception as e:  # noqa: BLE001
        print("  parcel_lookup: skip", str(e)[:70])
    for li in fresh:
        try:
            c = vcalc.compute(li)
            g = vgrade.grade(li, c)
            if not isinstance(li.raw, dict):
                li.raw = {}
            li.raw["calc"] = vcalc.to_dict(c)
            li.raw["grade"] = vgrade.to_dict(g)
        except Exception as e:  # noqa: BLE001
            print("  calc/grade: skip", str(e)[:70])
    try:
        print("  distress score:", score_board(fresh))
    except Exception as e:  # noqa: BLE001
        print("  score: skip", str(e)[:70])


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true",
                    help="build + enrich + print, but do not acquire the lock or write")
    args = ap.parse_args()

    fresh = [_build(dict(e)) for e in WATCHLIST]
    print(f"built {len(fresh)} watchlist lead(s):")
    for li in fresh:
        print(f"  - {li.street_address}, {li.city} {li.county} {li.state} {li.zip_code} "
              f"[{li.listing_type}] status={li.auction_status}")
    _enrich_fresh(fresh)
    for li in fresh:
        g = (li.raw or {}).get("grade", {}) if isinstance(li.raw, dict) else {}
        print(f"  -> {li.street_address}: lat={li.latitude} parcel={li.parcel_id} "
              f"grade={g.get('grade')} distress={getattr(li, 'distress_score', None)}")

    if args.dry_run:
        print("DRY RUN — not writing.")
        return 0

    with board_lock(owner="add_watchlist_property"):
        existing = load_board(DOCS)
        print(f"existing dashboard: {len(existing)}")
        _pre = len(existing) + len(fresh)
        merged = dedupe(existing + fresh)
        print(f"merged+deduped: {len(existing)} + {len(fresh)} -> {len(merged)} "
              f"(collapsed {_pre - len(merged)})")
        summary = {
            "by_source": dict(collections.Counter(li.source for li in merged if li.source)),
            "notes": "manual watchlist injection (add_watchlist_property.py)",
        }
        lp, mp = write_artifact(merged, summary, docs_dir=DOCS)
        print(f"wrote {lp} ({lp.stat().st_size:,} bytes) + {mp.name} | total: {len(merged)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
