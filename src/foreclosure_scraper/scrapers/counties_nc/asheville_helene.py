"""Asheville / Buncombe NC — Hurricane Helene damaged structures (ATC-45 placards).

The City of Asheville's public Phase-II damage-assessment layer carries every inspected structure
with an ATC-45 posting. 'Unsafe' (red) and 'Restricted' (yellow) buildings are strong motivated-seller
signals — owners facing a major repair or a teardown. The layer is GEO-ONLY (precise inspection
lat/lng, no address/owner), but the coordinates are real building GPS, so the downstream GIS chain
(parcel_from_geo + gis_attrs) snaps them to the correct parcel + owner + value reliably.

EXTRACTION-COMPLETENESS AUDIT 2026-10-03: the layer's own metadata reports
`hasAttachments: True`, and live-checking 5 sampled Unsafe/Restricted objectids
confirmed every one carries 2-5 real inspection JPEGs
(`FeatureServer/0/queryAttachments`, image bytes served at
`FeatureServer/0/{objectid}/attachments/{attachmentId}`) that this scraper never
fetched at all -- every row shipped with no real photo for the Vision
enrichment pass, which only reads raw['images']['real'] (same gap class as
counties_sc.terry_howe_auctions / national.irs_judicial_sales, fixed earlier
this audit). Fixed via one batched queryAttachments call (comma-separated
objectIds, chunked) rather than one request per feature (652 live features
would mean 652 extra round-trips).

Free, anonymous, compliant (public ArcGIS). ~650 Unsafe/Restricted structures.
Gate with FORECLOSURE_HELENE=0 to skip.
"""
from __future__ import annotations

import os
from datetime import datetime
from typing import Iterable

import structlog

from ...base_scraper import BaseScraper
from ...http_client import client
from ...models import Listing, ListingType, PropertyKind

log = structlog.get_logger()

_LAYER_BASE = ("https://services.arcgis.com/aJ16ENn1AaqdFlqx/arcgis/rest/services/"
               "Helene_Property_Damage_Assessment_Phase_II_Public_View/FeatureServer/0")
QUERY_URL = f"{_LAYER_BASE}/query"
_ATTACH_URL = f"{_LAYER_BASE}/queryAttachments"
_WHERE = "current_posting IN ('Unsafe','Restricted')"
_OUT = ("objectid,incident_name,inspect_date,building_type,building_primary_occupancy,"
        "building_damage,previous_posting,current_posting,building_number_res_units")
#: Per-feature photo cap (matches the terry_howe_auctions/irs_judicial_sales convention).
_MAX_PHOTOS = 8
#: objectIds per queryAttachments call -- keeps the URL comfortably under typical
#: server/proxy query-string limits even at the live ~650-feature volume.
_ATTACH_CHUNK = 150


async def _fetch_attachments(c, object_ids: list[int]) -> dict[int, list[str]]:
    """Batch-resolve objectid -> real inspection-photo URLs via queryAttachments.
    Never raises; a failed/partial chunk just yields no photos for those ids."""
    out: dict[int, list[str]] = {}
    for i in range(0, len(object_ids), _ATTACH_CHUNK):
        chunk = object_ids[i:i + _ATTACH_CHUNK]
        try:
            r = await c.get(_ATTACH_URL, params={
                "objectIds": ",".join(str(x) for x in chunk), "f": "json"})
            if r.status_code != 200:
                continue
            groups = (r.json() or {}).get("attachmentGroups") or []
        except Exception as exc:  # noqa: BLE001
            log.warning("asheville_helene.attachments_fail", error=str(exc)[:150])
            continue
        for g in groups:
            oid = g.get("parentObjectId")
            if oid is None:
                continue
            urls = []
            for info in g.get("attachmentInfos") or []:
                ct = (info.get("contentType") or "").lower()
                aid = info.get("id")
                if aid is None or not ct.startswith("image/"):
                    continue
                urls.append(f"{_LAYER_BASE}/{oid}/attachments/{aid}")
                if len(urls) >= _MAX_PHOTOS:
                    break
            if urls:
                out[oid] = urls
    return out


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

            object_ids = [a["objectid"] for ft in feats
                          if (a := (ft.get("attributes") or {})).get("objectid") is not None]
            try:
                photos_by_oid = await _fetch_attachments(c, object_ids)
            except Exception as exc:  # noqa: BLE001 - photos are a bonus, never fail the run
                log.warning("asheville_helene.attachments_fail", error=str(exc)[:150])
                photos_by_oid = {}
            log.info("asheville_helene.attachments", features=len(feats),
                     with_photos=len(photos_by_oid))

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
                raw = {"helene": {
                    "current_posting": posting,
                    "previous_posting": a.get("previous_posting"),
                    "building_damage": a.get("building_damage"),
                    "building_type": a.get("building_type"),
                    "occupancy": occ or None,
                    "res_units": a.get("building_number_res_units"),
                    "inspect_date": a.get("inspect_date"),
                }, "life_event": "storm_damage"}
                photos = photos_by_oid.get(oid)
                if photos:
                    raw["images"] = {"real": photos}
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
                    raw=raw,
                ))
        return out
