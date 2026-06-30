"""Asheville / Buncombe NC — Hurricane Helene damaged structures (ATC-45 placards).

The City of Asheville's public Phase-II damage-assessment layer carries every inspected structure
with an ATC-45 posting. 'Unsafe' (red) and 'Restricted' (yellow) buildings are strong motivated-seller
signals — owners facing a major repair or a teardown. The layer is GEO-ONLY (precise inspection
lat/lng, no address/owner), but the coordinates are real building GPS, so the downstream GIS chain
(parcel_from_geo + gis_attrs) snaps them to the correct parcel + owner + value reliably.

Free, anonymous, compliant (public ArcGIS). ~650 Unsafe/Restricted structures.
Gate with FORECLOSURE_HELENE=0 to skip.
"""
from __future__ import annotations

import os
from datetime import datetime
from typing import Iterable

from ...base_scraper import BaseScraper
from ...http_client import client
from ...models import Listing, ListingType, PropertyKind

QUERY_URL = ("https://services.arcgis.com/aJ16ENn1AaqdFlqx/arcgis/rest/services/"
             "Helene_Property_Damage_Assessment_Phase_II_Public_View/FeatureServer/0/query")
_WHERE = "current_posting IN ('Unsafe','Restricted')"
_OUT = ("objectid,incident_name,inspect_date,building_type,building_primary_occupancy,"
        "building_damage,previous_posting,current_posting,building_number_res_units")


class AshevilleHeleneDamage(BaseScraper):
    slug = "counties_nc.asheville_helene"
    name = "Asheville/Buncombe (NC) Helene Damaged Structures (Unsafe/Restricted)"
    category = "motivated_seller"
    timeout_s = 90.0
    expected_min_count = 50

    async def fetch(self) -> Iterable[Listing]:
        if os.environ.get("FORECLOSURE_HELENE", "1") == "0":
            return []
        out: list[Listing] = []
        now = datetime.utcnow()
        async with client(timeout=60.0) as c:
            try:
                r = await c.get(QUERY_URL, params={
                    "where": _WHERE, "outFields": _OUT, "returnGeometry": "true",
                    "outSR": "4326", "resultRecordCount": "2000", "f": "json"})
                if r.status_code != 200:
                    return []
                feats = r.json().get("features", []) or []
            except Exception:  # noqa: BLE001
                return []
            for ft in feats:
                a = ft.get("attributes", {}) or {}
                g = ft.get("geometry", {}) or {}
                lat, lng = g.get("y"), g.get("x")
                if lat is None or lng is None:
                    continue
                oid = a.get("objectid")
                posting = (a.get("current_posting") or "").strip()
                occ = (a.get("building_primary_occupancy") or "").strip()
                # Commercial/industrial structures aren't motivated-seller homes; mark kind but keep.
                pk = PropertyKind.COMMERCIAL if "commercial" in occ.lower() else PropertyKind.UNKNOWN
                out.append(Listing(
                    source=self.slug,
                    source_url=f"{QUERY_URL}?where=objectid%3D{oid}&outFields=*&f=html",
                    listing_type=ListingType.DISTRESSED,
                    property_kind=pk,
                    state="NC",
                    county="Buncombe",
                    latitude=float(lat),
                    longitude=float(lng),
                    description=f"Helene damage: {posting} placard"
                                + (f" - {a.get('building_damage')}" if a.get("building_damage") else "")
                                + (f" ({occ})" if occ else ""),
                    first_seen=now,
                    last_seen=now,
                    raw={"helene": {
                        "current_posting": posting,
                        "previous_posting": a.get("previous_posting"),
                        "building_damage": a.get("building_damage"),
                        "building_type": a.get("building_type"),
                        "occupancy": occ or None,
                        "res_units": a.get("building_number_res_units"),
                        "inspect_date": a.get("inspect_date"),
                    }, "life_event": "storm_damage"},
                ))
        return out
