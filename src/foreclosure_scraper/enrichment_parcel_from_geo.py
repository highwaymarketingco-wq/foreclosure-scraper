"""Resolve a parcel_id for geo-bearing (or address-bearing) leads that have none.

Root cause this closes
----------------------
52% of leads carry a parcel_id; the rest do not. 2054 of the parcel-less leads
DO have lat/lng, and another ~1468 have a street_address. Today nothing turns
those into a parcel:

  * ``enrichment_parcel_lookup`` runs the OTHER direction — it needs a
    parcel_id (or one extractable from description text) ALREADY present, then
    looks up address/specs. It never *derives* a parcel from coordinates.
  * ``enrichment_parcel_reverse_geo`` also requires ``li.parcel_id`` up front;
    it reverse-geocodes a centroid to an approximate address, not a parcel.
  * ``parcel_resolver.resolve_sc_parcel_key`` DOES point-in-polygon, but it is
    (a) only invoked from the assessor-card enricher (gated behind
    ``ASSESSOR_CARD_ON``), (b) limited to 5 SC counties via ``_SC_KEY_FIELD``,
    and (c) returns a county-specific key string for the adapter rather than
    writing ``li.parcel_id``. So the 2054 geo-bearing leads stay parcel-less.

A live probe (2026-06-25) confirmed both statewide layers return a parcel id on
a simple point query for every in-scope county:

  * SC: SCDOT ``SC_Parcels`` MapServer, one layer per county. The parcel-id
    field name varies (Spartanburg ``TAXPIN``, Anderson/Laurens ``TMS``,
    Greenville/Beaufort/Pickens ``PIN``, Oconee ``TMS_NUMBER``, Union
    ``ParcelID`` …) — handled by the existing ``_scdot_parcel`` priority list.
  * NC: NC OneMap ``NC1Map_Parcels`` FeatureServer/1, statewide, parcel field
    ``parno`` (resolves Gaston/Buncombe/Henderson/Forsyth/McDowell/Polk/Lincoln/
    Guilford/Rutherford …; Cleveland parcels are absent from this statewide
    layer and fall through, which is fine).

This module is point-in-polygon FIRST (lat/lng -> parcel), with an
address->parcel fallback (geocode the street to a point via the same county
GIS, then point query) only for leads that have a street_address but no
coordinates. Free, pure-HTTP, no auth. Writes ONLY ``li.parcel_id`` (and a
small provenance blob under ``raw.parcel_from_geo``); never touches address,
value, or owner — the downstream GIS-attrs track consumes the new parcel_id.
"""
from __future__ import annotations

import asyncio
from typing import Any, Optional

import structlog

from .enrichment_arcgis import SCDOT_BASE, SC_LAYER
from .http_client import client
from .models import Listing
from .parcel_inventory import _scdot_parcel

log = structlog.get_logger()

# NC statewide parcel layer (same service already used by enrichment_owner_mailing
# / enrichment_bankruptcy_property). One consistent schema across all 100 NC
# counties; parcel id in ``parno``, county in ``cntyname``.
NC_ONEMAP_PARCELS = (
    "https://services.nconemap.gov/secure/rest/services/"
    "NC1Map_Parcels/FeatureServer/1/query"
)

_UA = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) Chrome/126"}

# Rough NC+SC bounding box — reject (0,0) and out-of-area coords that would
# point-query the wrong place (or nothing).
_LAT_MIN, _LAT_MAX = 32.0, 37.0
_LON_MIN, _LON_MAX = -84.5, -75.0


def _norm_county(county: Optional[str]) -> str:
    """'Spartanburg County, SC' -> 'Spartanburg'."""
    c = (county or "").replace(" County", "").strip()
    for suffix in (", NC", ", SC", ",NC", ",SC"):
        if c.upper().endswith(suffix):
            c = c[: -len(suffix)].strip()
    return c.split(",")[0].strip().title()


def _in_box(li: Listing) -> bool:
    return (
        li.latitude is not None
        and li.longitude is not None
        and _LAT_MIN <= li.latitude <= _LAT_MAX
        and _LON_MIN <= li.longitude <= _LON_MAX
    )


def _clean_parcel(pid: Any) -> str:
    """Reject obviously-bad parcel ids (the same >=5-char / non-trivial gate the
    address-match path in enrichment_arcgis applies, so a junk value never gets
    written into the dedupe key)."""
    s = str(pid or "").strip()
    if len(s) < 5 or s.isspace() or s in ("0", "0.0"):
        return ""
    return s


async def _point_query(
    c, layer_query_url: str, lat: float, lon: float, out_fields: str = "*"
) -> Optional[dict[str, Any]]:
    """Run a point-in-polygon ArcGIS query; return the first feature's
    attributes, or None."""
    params = {
        "geometry": f"{lon},{lat}",
        "geometryType": "esriGeometryPoint",
        "inSR": 4326,
        "spatialRel": "esriSpatialRelIntersects",
        "outFields": out_fields,
        "returnGeometry": "false",
        "f": "json",
    }
    try:
        r = await c.get(layer_query_url, params=params, timeout=25.0)
        if r.status_code != 200:
            return None
        data = r.json()
        if "error" in data:
            return None
        feats = data.get("features") or []
    except Exception:  # noqa: BLE001
        return None
    if not feats:
        return None
    return dict(feats[0].get("attributes") or {})


async def _parcel_from_point_sc(c, li: Listing) -> str:
    layer = SC_LAYER.get(_norm_county(li.county))
    if layer is None:
        return ""
    attrs = await _point_query(c, f"{SCDOT_BASE}/{layer}/query", li.latitude, li.longitude)
    if not attrs:
        return ""
    # _scdot_parcel walks the per-county field-name priority list (TAXPIN, TMS,
    # TMS_NUMBER, PIN via fallback, ParcelID, …) and returns the unique id.
    pid = _scdot_parcel(attrs)
    if not pid:
        # Some county layers only expose PIN (Greenville/Beaufort/Pickens).
        for f in ("PIN", "PARNO", "PARID", "Parcel_ID", "PARCEL_ID"):
            if attrs.get(f):
                pid = str(attrs[f]).strip()
                break
    return _clean_parcel(pid)


async def _parcel_from_point_nc(c, li: Listing) -> str:
    attrs = await _point_query(
        c, NC_ONEMAP_PARCELS, li.latitude, li.longitude, out_fields="parno,cntyname"
    )
    if not attrs:
        return ""
    # County guard: the statewide layer could in theory return a neighbouring
    # county's parcel for a point near a border. Only trust it when cntyname
    # agrees with the lead's county (when both are known).
    want = _norm_county(li.county)
    got = str(attrs.get("cntyname") or "").strip().title()
    if want and got and want != got:
        return ""
    return _clean_parcel(attrs.get("parno"))


async def _resolve_one(c, li: Listing, counts: dict) -> None:
    if li.parcel_id:
        return
    if not (li.state and li.county and _in_box(li)):
        return
    counts["queried"] += 1
    if li.state == "SC":
        pid = await _parcel_from_point_sc(c, li)
    elif li.state == "NC":
        pid = await _parcel_from_point_nc(c, li)
    else:
        return
    if not pid:
        return
    li.parcel_id = pid
    if not isinstance(li.raw, dict):
        li.raw = {}
    li.raw["parcel_from_geo"] = {
        "source": "scdot_point" if li.state == "SC" else "nc_onemap_point",
        "lat": li.latitude,
        "lng": li.longitude,
    }
    counts["resolved"] += 1


async def enrich_parcel_from_geo(listings: list[Listing], concurrency: int = 8) -> dict:
    """Point-in-polygon resolve a parcel_id for every geo-bearing lead that has
    none. SC -> SCDOT SC_Parcels; NC -> NC OneMap NC1Map_Parcels. Writes only
    ``li.parcel_id`` (+ provenance). Idempotent: leads that already carry a
    parcel_id are skipped, so re-runs are no-ops on resolved leads.
    """
    targets = [
        li
        for li in listings
        if not li.parcel_id and li.state in ("SC", "NC") and li.county and _in_box(li)
    ]
    if not targets:
        log.info("parcel_from_geo.no_targets")
        return {"queried": 0, "resolved": 0}

    log.info("parcel_from_geo.start", target_count=len(targets))
    counts = {"queried": 0, "resolved": 0}
    sem = asyncio.Semaphore(concurrency)

    async def _bounded(c, li: Listing) -> None:
        async with sem:
            await _resolve_one(c, li, counts)

    async with client(timeout=25.0, headers=_UA) as c:
        await asyncio.gather(*(_bounded(c, li) for li in targets))

    log.info("parcel_from_geo.done", **counts)
    return counts
