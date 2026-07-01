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

    a_p = sum(1 for li in listings if (li.parcel_id or "").strip())
    a_o = sum(1 for li in listings if (li.owner_name or "").strip())
    a_a = sum(1 for li in listings if (li.street_address or "").strip())
    write_artifact(listings, {"notes": "catch-up: geo-only parcel/owner/situs resolution"}, docs_dir=DOCS)
    print(f"wrote board | parcel +{a_p - b_p} owner +{a_o - b_o} addr +{a_a - b_a}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
