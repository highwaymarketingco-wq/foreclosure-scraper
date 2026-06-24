"""Resolve a county parcel KEY from a lead's lat/lng via point-in-polygon against
the SCDOT statewide parcel MapServer.

The on-demand assessor-card enricher keys on a parcel id, but only ~22% of B+
leads carry one — while ~100% have a geocoded situs (lat/lng). This closes that
gap: a point query against the county's SCDOT parcel layer returns the parcel
identifier in the exact format the county's assessor adapter expects.

Counties whose assessor key is an internal account number NOT carried in SCDOT
(Pickens R-account; Cherokee's cryptic sheet sub-fields; Greenville's 13-digit
MapNumber vs SCDOT's P-PIN) are omitted — those adapters fall back to their own
address search. Field map verified live 2026-06-24.
"""
from __future__ import annotations

from .http_client import client
from .enrichment_lis_pendens_resolver import SC_LAYER

SCDOT_BASE = "https://smpesri.scdot.org/arcgis/rest/services/GISMapping/SC_Parcels/MapServer"
_UA = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) Chrome/126"}

# county -> SCDOT field(s) whose value == the assessor adapter's KeyValue/TMS.
_SC_KEY_FIELD = {
    "Spartanburg": ("MAPNUMBER",),                   # dashed map -> qPublic KeyValue
    "Oconee":      ("TMS_NUMBER", "PARCEL_NO"),      # dashed parcel -> qPublic KeyValue
    "Anderson":    ("TMS",),                         # TMS digits -> county ArcGIS where TMS=
    "Laurens":     ("TMS", "TaxPIN", "Map_Number"),  # dashed TMS -> Pebble where TMS=
    "Union":       ("Map_Number", "ParcelID"),       # qPublic KeyValue (e.g. '104-00-00-015 000')
}


async def resolve_sc_parcel_key(li) -> str | None:
    """Return the county parcel key for an SC lead, from li.parcel_id if present,
    else by point-querying SCDOT with the lead's lat/lng. None if unresolvable."""
    if li.parcel_id:
        return li.parcel_id
    layer = SC_LAYER.get(li.county)
    fields = _SC_KEY_FIELD.get(li.county)
    if layer is None or not fields or li.latitude is None or li.longitude is None:
        return None
    params = {
        "geometry": f"{li.longitude},{li.latitude}", "geometryType": "esriGeometryPoint",
        "inSR": 4326, "spatialRel": "esriSpatialRelIntersects", "outFields": "*",
        "returnGeometry": "false", "f": "json",
    }
    try:
        async with client(timeout=25.0, headers=_UA) as c:
            r = await c.get(f"{SCDOT_BASE}/{layer}/query", params=params)
            feats = (r.json().get("features") or [])
    except Exception:  # noqa: BLE001
        return None
    if not feats:
        return None
    attrs = feats[0].get("attributes") or {}
    for f in fields:
        v = attrs.get(f)
        if v is not None and str(v).strip() and str(v).strip() not in ("0", "0.0"):
            return str(v).strip()
    return None
