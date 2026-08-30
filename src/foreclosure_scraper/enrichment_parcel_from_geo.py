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
import json
from typing import Any, Optional

import structlog

from .enrichment_arcgis import (
    SCDOT_BASE, SC_LAYER,
    scdot_walled, mark_scdot_walled, is_scdot_token_error,  # noqa: F401  (compat)
    host_walled, mark_host_walled, note_host_ok, note_host_hard_failure,
    is_token_error,
)
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


# Half-width of the fallback envelope, in degrees. ~5.5 m at NC/SC latitude —
# tight enough that it lands inside the intended parcel, wide enough to survive
# the server's spatial-index tolerance. Measured on 25 live geo-only leads:
# 5e-5 -> 13 unique / 4 ambiguous / 8 empty; 1e-4 -> 14 unique / 9 ambiguous.
# The bigger box buys one extra hit and more than doubles ambiguity, so 5e-5 it is.
_ENVELOPE_HALF_DEG = 5e-5


async def _arc_query(c, layer_query_url: str, params: dict) -> Optional[list]:
    """GET an ArcGIS /query and return its feature list (None on any failure).
    ArcGIS reports failure as HTTP 200 + an `error` key, so status alone is not
    enough — a token-required response looks exactly like an empty result set."""
    # Generic per-host breaker: skip a host that's already been tripped (token
    # wall or repeated timeouts) instead of re-hitting it for every lead.
    if host_walled(layer_query_url):
        return None
    try:
        r = await c.get(layer_query_url, params=params, timeout=25.0)
        if r.status_code != 200:
            note_host_hard_failure(layer_query_url)
            return None
        data = r.json()
        if "error" in data:
            # A token/auth wall (SCDOT-class) trips the host immediately so no
            # later lead re-hits it; an ordinary query error (bad where clause)
            # does not — it's per-request, not a dead host.
            if is_token_error(data):
                mark_host_walled(layer_query_url, reason="token/auth error")
            return None
        note_host_ok(layer_query_url)
        return data.get("features") or []
    except Exception:  # noqa: BLE001  (timeout / connection — a HARD failure)
        note_host_hard_failure(layer_query_url)
        return None


async def _point_query(
    c, layer_query_url: str, lat: float, lon: float, out_fields: str = "*"
) -> Optional[dict[str, Any]]:
    """Resolve the parcel polygon containing (lat, lon) — point first, then a
    tiny envelope.

    NC OneMap's NC1Map_Parcels currently answers EVERY esriGeometryPoint query
    with HTTP 200 and zero features — verified 2026-07-27 against Buncombe,
    downtown Asheville and downtown Raleigh, on a layer that reports 5,938,639
    parcels and happily returns rows for an attribute query. A silent
    always-empty spatial filter, not a coverage gap. The identical query with
    geometryType=esriGeometryEnvelope returns the right parcel, so we retry as a
    ~5.5 m box around the same point.

    The envelope result is accepted ONLY when it matches exactly one parcel.
    A box straddling a boundary returns several, and picking features[0] there
    would write a confidently wrong neighbouring parcel onto the lead — worse
    than leaving it unresolved. Point-in-polygon needs no such guard because it
    is unique by construction.
    """
    base = {
        "geometryType": "esriGeometryPoint",
        "geometry": f"{lon},{lat}",
        "inSR": 4326,
        "spatialRel": "esriSpatialRelIntersects",
        "outFields": out_fields,
        "returnGeometry": "false",
        "f": "json",
    }
    feats = await _arc_query(c, layer_query_url, base)
    if feats:
        return dict(feats[0].get("attributes") or {})
    if feats is None:
        return None  # hard failure (HTTP error / ArcGIS error) — don't re-hit

    d = _ENVELOPE_HALF_DEG
    env = dict(base)
    env["geometryType"] = "esriGeometryEnvelope"
    env["geometry"] = json.dumps({
        "xmin": lon - d, "ymin": lat - d, "xmax": lon + d, "ymax": lat + d,
        "spatialReference": {"wkid": 4326},
    })
    env["resultRecordCount"] = 2  # only need to know "exactly one" vs "several"
    feats = await _arc_query(c, layer_query_url, env)
    if not feats or len(feats) != 1:
        return None
    return dict(feats[0].get("attributes") or {})


async def _parcel_from_point_sc(c, li: Listing) -> str:
    # SCDOT is the only SC point-parcel source here; once the token wall is tripped
    # every subsequent SC lead would just re-hit it, so short-circuit immediately.
    if scdot_walled():
        return ""
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


# The matched OneMap record already carries the SITUS address, city and ZIP —
# the very fields the next enricher would otherwise re-query a county layer for.
# `siteadd` / `scity` / `szip` are names enrichment_arcgis._ADDR_FIELD_CANDIDATES
# and enrichment_situs_address already recognise, so stashing the bag lets
# enrich_situs_address resolve the address from cache with ZERO extra HTTP.
_NC_OUT_FIELDS = (
    "parno,cntyname,siteadd,sunit,scity,sstate,szip,"
    "saddno,saddpref,saddstname,saddsttyp,saddstsuf,ownname,parval"
)


async def _parcel_from_point_nc(c, li: Listing) -> str:
    # NC OneMap is the ONLY NC point-parcel source here; if it's tripped (token
    # wall on its /secure/ path, or repeated timeouts) skip it — re-hitting it for
    # every NC lead is the SCDOT-class 16h hang. (_point_query fires TWO 25s calls
    # per lead, so an unguarded degradation is especially expensive here.)
    if host_walled(NC_ONEMAP_PARCELS):
        return ""
    attrs = await _point_query(
        c, NC_ONEMAP_PARCELS, li.latitude, li.longitude, out_fields=_NC_OUT_FIELDS
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
    pid = _clean_parcel(attrs.get("parno"))
    if pid and isinstance(li.raw, dict) and not li.raw.get("gis_attrs_full"):
        # Only when absent: a county-layer bag stashed by gis_attrs is richer
        # than the statewide one and must not be clobbered.
        cleaned = _clean_nc_situs(attrs)
        li.raw["gis_attrs_full"] = cleaned
        road = cleaned.get(_NC_ROAD_ONLY_KEY)
        if road:
            # Surface the road as CONTEXT ONLY, never as an address. Keyed to
            # nothing: it is written onto the very Listing whose own point
            # matched this parcel, so no cross-lead fan-out is possible, and the
            # parcel_id it is stamped with is the unique id of that same parcel.
            li.raw[_NC_ROAD_ONLY_KEY] = {
                "road": road,
                "city": cleaned.get("scity") or None,
                "zip": cleaned.get("szip") or None,
                "parcel_id": pid,
                "source": "nc_onemap_point",
                "mailable": False,
                "note": "NC parcel has no assigned house number (vacant/unnumbered lot)",
            }
    return pid


# NC's "no house number assigned" sentinels. 17,788 parcels carry siteadd
# "99999 <ROAD>" and 285,716 carry "0 <ROAD>" — all vacant land / undeveloped
# lots / unnumbered building lots. Passed through, "99999 MEADOW RD" reads as a
# real street address (it starts with digits, so every downstream validator
# accepts it) and would be mailed, geocoded and shown on the board as fact.
_NC_NO_NUMBER_SENTINELS = ("99999", "0")

# Where the bare road goes once the sentinel is stripped. NOT `siteadd`:
# `siteadd` is the field enrichment_situs_address reads to WRITE
# li.street_address (it is in enrichment_arcgis._ADDR_FIELD_CANDIDATES), and a
# numberless road ("MEADOW RD") is not a mailable address — yet it satisfies
# web_artifact._is_valid_street_address via the road-suffix rule, so writing it
# would (a) publish it as the property's address, (b) send it to the geocoder
# and a mail merge, and (c) make scripts/resolve_addresses classify the lead
# "resolved" and checkpoint it as done FOREVER, killing any later chance at the
# real address. The road still locates the parcel roughly and pairs with
# parcel_id + coords, so it is kept here as provenance instead.
_NC_ROAD_ONLY_KEY = "situs_road_only"


def _clean_nc_situs(attrs: dict[str, Any]) -> dict[str, Any]:
    """Sanitize NC OneMap situs fields. Returns a copy; caller's dict untouched.

    A sentinel house number means the parcel has NO assigned address, so the
    address fields are emptied rather than patched: `siteadd` is blanked (an
    empty situs is skipped by every address writer) and the bare road is parked
    under `situs_road_only` with a `situs_no_house_number` flag. Real addresses
    ("801 BILTMORE  AVE") only get their double spaces collapsed.
    """
    out = dict(attrs)
    raw = str(out.get("siteadd") or "").strip()
    if raw:
        head, _, rest = raw.partition(" ")
        road = " ".join(rest.split())
        if head in _NC_NO_NUMBER_SENTINELS:
            # No house number exists for this parcel -> there is no address to
            # write. Keep the road as context under its own key.
            out["siteadd"] = ""
            out["situs_no_house_number"] = True
            if road:
                out[_NC_ROAD_ONLY_KEY] = road
        else:
            out["siteadd"] = " ".join(raw.split())
    num = str(out.get("saddno") or "").strip()
    if num in _NC_NO_NUMBER_SENTINELS:
        out["saddno"] = ""
        out["situs_no_house_number"] = True
    for f in ("saddstname", "scity"):
        if out.get(f):
            out[f] = " ".join(str(out[f]).split())
    return out


async def _resolve_one(c, li: Listing, counts: dict) -> None:
    if li.parcel_id:
        return
    if not (li.state and li.county and _in_box(li)):
        return
    counts["queried"] += 1
    # Normalize raw BEFORE the lookup — _parcel_from_point_nc stashes the
    # matched attribute bag into it, and would silently skip that on a lead
    # whose raw isn't a dict yet.
    if not isinstance(li.raw, dict):
        li.raw = {}
    if li.state == "SC":
        pid = await _parcel_from_point_sc(c, li)
    elif li.state == "NC":
        pid = await _parcel_from_point_nc(c, li)
    else:
        return
    if not pid:
        return
    li.parcel_id = pid
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
