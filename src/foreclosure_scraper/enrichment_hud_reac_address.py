"""HUD REAC address backfill — give the multifamily REAC-inspection leads a real
street address by joining their REMS property id to HUD's public Multifamily
Properties (Assisted) layer.

The REAC inspection-scores XLS (national.hud_reac_inspection) carries the property
NAME, City, and a ``rems_property_id`` but NO street address — so the scraper uses
the complex name as a placeholder ``street_address``. That blocks parcel/GIS/comps
because there's nothing to geocode, and owner-name search can't match a complex
owned by an LLC.

HUD publishes the real address for every REMS property in its free, no-login
``Multifamily_Properties_Assisted`` ArcGIS FeatureServer, keyed by ``PROPERTY_ID``
(the HEREMS id) with standardized ``STD_ADDR``/``STD_CITY``/``STD_ST``/``STD_ZIP5``
columns plus point geometry. One query for NC+SC (~1,300 rows) builds the lookup;
live-verified 2026-06 it resolves ~82% of our REAC leads (e.g. A.R.P. MANOR ->
2900 Union Rd, Gastonia NC 28054 with lat/lng).

Once a real address + lat/lng land here, the downstream GIS chain (parcel_from_geo
-> gis_attrs) + comps + Vision all fire on the lead like any other. Free, public,
no auth. Gate off with FORECLOSURE_HUD_REAC_ADDR=0.
"""
from __future__ import annotations

import json
import os
from typing import Iterable
from urllib.parse import quote

import structlog

from .http_client import get_bytes
from .models import Listing

log = structlog.get_logger()

_LAYER = (
    "https://services.arcgis.com/VTyQ9soqVukalItT/arcgis/rest/services/"
    "Multifamily_Properties_Assisted/FeatureServer/0/query"
)
_OUT = (
    "PROPERTY_ID,PROPERTY_NAME_TEXT,STD_ADDR,STD_CITY,STD_ST,STD_ZIP5,"
    "TOTAL_UNIT_COUNT,TOTAL_ASSISTED_UNIT_COUNT,"
    "PROPERTY_ON_SITE_PHONE_NUMBER,MGMT_CONTACT_MAIN_PHN_NBR,"
    "MGMT_CONTACT_EMAIL_TEXT,MGMT_AGENT_ORG_NAME,"
    "REAC_LAST_INSPECTION_SCORE,REAC_LAST_INSPECTION_DATE"
)


def _has_real_address(li: Listing) -> bool:
    """A REAC row's street_address is the complex NAME placeholder until we fill a
    real one — treat name==address (or blank) as 'no real address'."""
    addr = (li.street_address or "").strip()
    if not addr:
        return False
    return addr.lower() != (li.owner_name or "").strip().lower()


def _rems_id(li: Listing) -> str | None:
    reac = (li.raw or {}).get("reac") or {}
    rid = reac.get("rems_property_id")
    return str(rid).strip() if rid not in (None, "") else None


async def _build_index() -> dict[str, dict]:
    """PROPERTY_ID -> {addr, city, st, zip, lat, lng} for all NC+SC HUD MF props."""
    where = quote("STD_ST IN ('NC','SC')")
    url = (
        f"{_LAYER}?where={where}&outFields={_OUT}"
        "&returnGeometry=true&outSR=4326&resultRecordCount=4000&f=json"
    )
    raw = await get_bytes(url, timeout=60.0)
    feats = json.loads(raw).get("features", []) or []
    idx: dict[str, dict] = {}
    for ft in feats:
        a = ft.get("attributes", {}) or {}
        g = ft.get("geometry", {}) or {}
        pid = str(a.get("PROPERTY_ID") or "").strip()
        addr = (a.get("STD_ADDR") or "").strip()
        if not pid or not addr:
            continue
        idx[pid] = {
            "addr": addr,
            "city": (a.get("STD_CITY") or "").strip() or None,
            "st": (a.get("STD_ST") or "").strip() or None,
            "zip": (a.get("STD_ZIP5") or "").strip() or None,
            "lat": g.get("y"),
            "lng": g.get("x"),
            "total_units": a.get("TOTAL_UNIT_COUNT"),
            "assisted_units": a.get("TOTAL_ASSISTED_UNIT_COUNT"),
            "site_phone": (a.get("PROPERTY_ON_SITE_PHONE_NUMBER") or "").strip() or None,
            "mgmt_phone": (a.get("MGMT_CONTACT_MAIN_PHN_NBR") or "").strip() or None,
            "mgmt_email": (a.get("MGMT_CONTACT_EMAIL_TEXT") or "").strip() or None,
            "mgmt_org": (a.get("MGMT_AGENT_ORG_NAME") or "").strip() or None,
            "reac_score": a.get("REAC_LAST_INSPECTION_SCORE"),
            "reac_date_ms": a.get("REAC_LAST_INSPECTION_DATE"),
        }
    return idx


async def enrich_hud_reac_address(listings: Iterable[Listing]) -> dict:
    """Fill street_address + lat/lng on HUD REAC leads via the REMS-id join."""
    if os.environ.get("FORECLOSURE_HUD_REAC_ADDR", "1") == "0":
        return {"matched": 0, "skipped": "disabled"}

    targets = [
        li for li in listings
        if li.source == "national.hud_reac_inspection"
        and not _has_real_address(li)
        and _rems_id(li)
    ]
    if not targets:
        return {"matched": 0}

    try:
        idx = await _build_index()
    except Exception as exc:  # noqa: BLE001
        log.warning("hud_reac_addr.index_failed", error=str(exc)[:200])
        return {"matched": 0, "error": "index_fetch_failed"}
    log.info("hud_reac_addr.index", properties=len(idx), targets=len(targets))

    matched = 0
    geo_filled = 0
    for li in targets:
        hit = idx.get(_rems_id(li))
        if not hit:
            continue
        li.street_address = hit["addr"]
        if hit["city"]:
            li.city = hit["city"]
        if hit["st"]:
            li.state = hit["st"]
        if hit["zip"]:
            li.zip_code = hit["zip"]
        if li.latitude is None and hit["lat"] is not None:
            li.latitude = float(hit["lat"])
            geo_filled += 1
        if li.longitude is None and hit["lng"] is not None:
            li.longitude = float(hit["lng"])
        if not isinstance(li.raw, dict):
            li.raw = {}
        reac = li.raw.setdefault("reac", {})
        reac["hud_address_source"] = "Multifamily_Properties_Assisted"
        # Wire additional fields from the ArcGIS layer
        if hit["total_units"] is not None:
            reac["total_units"] = hit["total_units"]
            # unit_count is the standard first-class field name in this codebase
            li.raw.setdefault("unit_count", hit["total_units"])
        if hit["assisted_units"] is not None:
            reac["assisted_units"] = hit["assisted_units"]
        # Phone: prefer on-site phone; fall back to mgmt phone
        site_ph = hit["site_phone"]
        mgmt_ph = hit["mgmt_phone"]
        if site_ph:
            reac.setdefault("site_phone", site_ph)
        if mgmt_ph:
            reac.setdefault("mgmt_phone", mgmt_ph)
        # Management contact
        if hit["mgmt_email"]:
            reac.setdefault("mgmt_email", hit["mgmt_email"])
        if hit["mgmt_org"]:
            reac.setdefault("mgmt_org", hit["mgmt_org"])
        # ArcGIS-layer REAC score (overrides if available and not already set)
        if hit["reac_score"] is not None:
            reac.setdefault("arcgis_reac_score", hit["reac_score"])
        matched += 1

    log.info("hud_reac_addr.done", matched=matched, geo_filled=geo_filled,
             targets=len(targets))
    return {"matched": matched, "geo_filled": geo_filled, "targets": len(targets),
            "new_fields": ["total_units", "assisted_units", "site_phone",
                           "mgmt_phone", "mgmt_email", "mgmt_org", "arcgis_reac_score"]}
