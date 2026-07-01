"""Catch-up: resolve geo-only leads (precise property lat/lng, no parcel_id)
that the full-run geo chain budget-bailed on, snapping them to
parcel -> owner + market value + situs address.

Led by 652 Hurricane-Helene-damaged Buncombe structures (ATC-45 placards) — a
strong distress signal that was sitting on the board contact-less. Scoped to
sources whose coordinates ARE the subject property (a geocoded court-filing
point could be a party's mailing address and mis-snap to the wrong parcel, so
those sources are excluded). Resolved parcels/owners persist forward and the
LLC owners feed the SoS agent + absentee enrichers on later passes.

Board-writer — run alone (no weekly/merge/lrcpwa/sos pass active). The chain's
own county-agreement + junk-address guards keep a bad point from writing a
wrong owner.
"""
from __future__ import annotations

import asyncio
import json
from pathlib import Path

from foreclosure_scraper.models import Listing
from foreclosure_scraper.enrichment_parcel_from_geo import enrich_parcel_from_geo
from foreclosure_scraper.enrichment_gis_attrs import enrich_gis_attrs
from foreclosure_scraper.enrichment_situs_address import enrich_situs_address
from foreclosure_scraper.valuation import calc as vcalc, grading as vgrade
from foreclosure_scraper.web_artifact import write_artifact

DOCS = Path(__file__).resolve().parent.parent / "docs"

# Sources whose lat/lng is the actual property location (safe to reverse-snap).
PROPERTY_GPS_SOURCES = {
    "counties_nc.asheville_helene",     # precise ATC-45 building-inspection GPS
    "national.hud_reac_inspection",     # HUD property inspection point
    "national.distressed",              # per-listing coordinates
    "national.foreclosure_dot_com",     # per-listing coordinates
    "national.crexi_multifamily",       # per-listing coordinates
}


import re

_PLACARD_RANK = {"unsafe": 2, "restricted": 1}


def _placard_severity(li) -> tuple[int, float]:
    """(placard rank, damage %) from a Helene lead's description — bigger is worse."""
    desc = li.description or ""
    m = re.search(r"Helene damage:\s*([A-Za-z]+)\s+placard", desc)
    rank = _PLACARD_RANK.get((m.group(1) if m else "").lower(), 0)
    p = re.search(r"placard\s*-\s*([0-9]+)%", desc)
    pct = float(p.group(1)) if p else 0.0
    return rank, pct


def dedup_helene_by_parcel(listings: list) -> int:
    """Collapse asheville_helene leads that resolved to the SAME parcel into one
    lead per owner/parcel (a multi-building complex is inspected per-structure but
    is a single outreach target). Keep the most-severe placard; record how many
    damaged buildings the parcel has. Returns the number of leads removed.

    Mutating the list in place, so the caller's `listings` shrinks. Only touches
    asheville_helene leads WITH a resolved parcel_id — everything else is left as-is.
    """
    from collections import defaultdict
    groups: dict[tuple, list] = defaultdict(list)
    for li in listings:
        if li.source == "counties_nc.asheville_helene" and (li.parcel_id or "").strip():
            groups[(li.parcel_id, li.county)].append(li)

    drop: set[int] = set()
    for grp in groups.values():
        if len(grp) < 2:
            continue
        grp.sort(key=_placard_severity, reverse=True)
        keep = grp[0]
        rank, pct = _placard_severity(keep)
        if not isinstance(keep.raw, dict):
            keep.raw = {}
        keep.raw["helene"] = {
            "damaged_buildings": len(grp),
            "worst_placard": "Unsafe" if rank == 2 else "Restricted" if rank == 1 else None,
            "worst_damage_pct": pct or None,
        }
        for li in grp[1:]:
            drop.add(id(li))

    if drop:
        listings[:] = [li for li in listings if id(li) not in drop]
    return len(drop)


def main() -> int:
    listings = []
    for d in json.loads((DOCS / "listings.json").read_text()):
        try:
            listings.append(Listing.model_validate(d))
        except Exception:  # noqa: BLE001
            pass

    targets = [
        li for li in listings
        if li.source in PROPERTY_GPS_SOURCES
        and not (li.parcel_id or "").strip()
        and li.latitude and li.longitude
        and li.state in ("NC", "SC")
    ]
    b_p = sum(1 for li in listings if (li.parcel_id or "").strip())
    b_o = sum(1 for li in listings if (li.owner_name or "").strip())
    b_a = sum(1 for li in listings if (li.street_address or "").strip())
    print(f"loaded {len(listings)} | targets={len(targets)} | before parcel={b_p} owner={b_o} addr={b_a}", flush=True)

    async def go():
        print("parcel_from_geo:", await enrich_parcel_from_geo(targets), flush=True)
        print("gis_attrs:", await enrich_gis_attrs(targets), flush=True)
        print("situs:", await enrich_situs_address(targets), flush=True)
    asyncio.run(go())

    # recompute value/grade on the newly-resolved targets
    for li in targets:
        try:
            c = vcalc.compute(li); g = vgrade.grade(li, c)
            if not isinstance(li.raw, dict):
                li.raw = {}
            li.raw["calc"] = vcalc.to_dict(c); li.raw["grade"] = vgrade.to_dict(g)
        except Exception:  # noqa: BLE001
            pass

    removed = dedup_helene_by_parcel(listings)
    print(f"helene dedup: removed {removed} same-parcel duplicate leads", flush=True)

    a_p = sum(1 for li in listings if (li.parcel_id or "").strip())
    a_o = sum(1 for li in listings if (li.owner_name or "").strip())
    a_a = sum(1 for li in listings if (li.street_address or "").strip())
    write_artifact(listings, {"notes": "catch-up: geo-only parcel/owner/situs resolution + helene dedup"}, docs_dir=DOCS)
    print(f"wrote board | leads={len(listings)} | parcel +{a_p - b_p} owner +{a_o - b_o} addr +{a_a - b_a}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
