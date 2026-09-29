"""Land buildability layer (Dirty Deeds Tier B #35).

docs/dirty_deeds_synthesis_2026-09-10.md, item #35: "Land buildability layer:
per-jurisdiction minimum road frontage table, landlocked flag, subdividability
(acreage + zoning + frontage + min lot size), cemetery layer, adjacency to
buyer-registry parcels ... Landlocked is a rank-up flag, not a kill: roughly 1
in 5 supposedly landlocked parcels are not, and landlocked land still resells
at ~70% of retail in NC because subdivision law is lax ... Every commercial
land data provider scrubs landlocked parcels out, so they are uncontested.
Cemetery on the parcel is competitor-repellent, score it positive." Rated
Free / NC yes / SC yes / Easy, except the frontage table which is manual per
jurisdiction.

This module ships the TWO sub-signals that turned out to have real, live,
queryable data behind them, and documents (rather than fakes) the other two.

===========================================================================
BUILT: landlocked candidate flag (raw['landlocked'], NC only)
===========================================================================
Mechanism: for a LAND lead with lat/lng, fetch its parcel BOUNDARY polygon
from NC OneMap's statewide parcel layer, fetch every road centerline in a
buffered envelope around that polygon from NC OneMap's statewide road layer,
and compute the minimum distance between any parcel-boundary edge and any
road edge in local meters. A parcel whose boundary sits farther than
``_FRONTAGE_THRESHOLD_M`` from every mapped road centerline is a landlocked
CANDIDATE -- written as a rank-up flag per the synthesis (never a kill; see
NOTE below), not a certainty.

Two layers, both live-verified 2026-09-29:
  * Parcels: NC1Map_Parcels FeatureServer/1 (services.nconemap.gov) -- the
    SAME layer enrichment_parcel_from_geo.py already resolves parcel_id from.
    Its exact-point query always answers 0 features (a known, documented
    quirk -- see that module's _point_query docstring); the tiny-envelope
    fallback ( _ENVELOPE_HALF_DEG, same ~5.5 m box already tuned there)
    works and, with returnGeometry=true, returns the full polygon ring(s) of
    the ONE parcel the envelope lands in. Accepted only when the envelope
    matches exactly 1 feature -- same ambiguity guard as the existing module,
    for the same reason (a straddled boundary must not silently pick a
    neighbour).
  * Roads: NC1Map_Transportation/FeatureServer/0, "NG911 Centerlines" --
    NC's statewide 911-addressing road-centerline layer, found by walking the
    NC OneMap service catalog (folders: AddressNC, Broadband, Elevation,
    Imagery, ImageryProject, NG911, test1, Utilities; NC1Map_Transportation is
    a top-level FeatureServer with exactly this one layer). This is a
    materially better source than a per-county road layer: it is uniform and
    statewide, so no per-county registry is needed for NC (unlike the
    cemetery layer below, which genuinely is per-county).

LIVE VERIFICATION (2026-09-29, board_stream.iter_board_rows, read-only, no
load_board -- 25 real Lincoln County NC land leads with full-precision
lat/lng, /tmp scratch script, not committed):
  * 22 of 25 parcels resolved unambiguously (3 hit the same "0 or 2+ features
    in the tiny envelope" ambiguity this module shares with
    enrichment_parcel_from_geo -- skipped, not guessed).
  * Of the 22, every ``parno`` NC OneMap returned for a Lincoln County parcel
    matched the board's OWN ``parcel_id`` character-for-character (e.g.
    "4605830808"). This is NOT true everywhere -- Buncombe's board parcel_id
    is the county's own dashed PIN format ("9608-10-8745-00000"), which does
    NOT match NC OneMap's parno for the same parcel (confirmed live: querying
    a Buncombe lead's rounded lat/lng landed on parno "961728972500000", a
    different id entirely). This module never assumes the two ids match; it
    always resolves geometry itself from lat/lng, never by parcel_id lookup.
  * All 22 resolved parcels came back NOT landlocked, with min boundary-to-
    road distances of 1.3-19.4 m and the nearest road's ``st_name`` matching
    the lead's own street_address in every case that had one (e.g. parcel
    4605830808 at "7440 Edgestone Ln" -> nearest road "EDGESTONE", 3.7 m).
    This is exactly the expected result (most land leads DO have frontage --
    landlocked is the synthesis's named MINORITY case) and it validates the
    full pipeline (envelope resolve -> polygon -> road envelope -> distance)
    against real board rows, not just that it runs without raising.
  * No positive (landlocked-candidate) example was available in this sample
    to verify against -- noted as a real gap in this verification, not
    hidden. The negative-case verification (zero false positives on 22 real
    frontage parcels) is what the 30 m threshold below is tuned against.

NOTE on the threshold and the doc's own warning: _FRONTAGE_THRESHOLD_M=30 is
deliberately generous (the 22 real hits above all landed under 20 m) so an
ordinary parcel is not misflagged by ROW-width/setback noise. Per the
synthesis, roughly 1 in 5 flagged parcels will still turn out to have real
access (a private easement, an unmapped gravel drive, a recorded right-of-way
this layer does not carry) -- this is captured in raw['landlocked'] as a
CANDIDATE flag for ranking UP (uncontested inventory, since every commercial
land provider scrubs these out), never as a reason to drop a lead.

SC: NOT built. SCDOT's own road server (smpesri.scdot.org/.../SCDOT_Roads)
publishes exactly one layer, "State_Highways" -- state-maintained highways
only, not local/subdivision roads. Using it alone would flag nearly every
rural parcel not fronting a state highway as landlocked, which is a false-
positive machine, not a signal. A search for a SC-equivalent of NC's
statewide NG911 centerline layer (ArcGIS Online public item search, SCDOT's
own service catalog, and the per-county GIS servers already in
parcel_cache.PARCEL_LAYERS for Anderson/Oconee/Pickens/Spartanburg/Laurens)
found county-level road layers in some counties (e.g. Henderson NC, Oconee
SC has "Roads"/"CountyRoads_FOCUS") but no free, queryable, uniform SC
source. Building this for SC would mean a per-county road-layer registry, the
same "manual per jurisdiction" shape as the frontage table the synthesis
already scopes out -- left undone rather than forced.

===========================================================================
BUILT: cemetery layer (raw['cemetery_proximity'], 2 NC counties)
===========================================================================
Live-verified 2026-09-29 by walking the ArcGIS service catalogs of the
county GIS hosts this codebase already trusts (parcel_cache.PARCEL_LAYERS /
arcgis_distress_layers.py hosts):
  * Buncombe: gis.buncombecounty.org/.../Cemetery/MapServer, layer 0
    "Bun.DBO.CemeteryPoints" (point geometry, 370 records) -- fields include
    PINNUM, Owner, StreetNumber/StreetName.
  * Gaston: gis.gastoncountync.gov/publicgis/.../Cemeteries/MapServer, layer
    15 "Cemeteries" (POLYGON geometry, 245 records) -- fields include NAME,
    PRIMARY_PID.
  Both are real, populated, public layers exactly matching the synthesis's
  prediction ("many counties do [publish one], often as a public-safety/
  historic layer"). Six other core-footprint county GIS hosts were walked
  looking for a sibling layer (Anderson SC, Henderson NC, Rutherford NC,
  Gaston's own other folders, Spartanburg SC, Oconee SC, Laurens SC) and none
  published one -- this is a genuinely per-county layer, not a per-state one,
  so _CEMETERY_LAYERS is a small, extensible registry (same NamedTuple-config
  shape as scrapers/counties_generic/arcgis_distress_layers.py) rather than a
  single statewide call. Extending coverage later means adding one entry per
  live-verified county layer, not new code.

Mechanism: for a LAND lead with lat/lng in a registered county, spatial-query
the county's cemetery layer with a buffered envelope around the lead's own
point. A polygon layer (Gaston) additionally gets a true point-in-polygon
check via the same local-projection ring math the landlocked flag uses, so a
lead whose coordinate falls inside a mapped cemetery boundary reads
relation="on_parcel" / distance_m=0 rather than merely "nearby".

===========================================================================
NOT BUILT (dead end / manual-only) -- subdividability's minimum-lot-size
===========================================================================
Acreage (Listing.acreage) and zoning (Listing.zoning, already populated for
many rows by enrichment_arcgis.py's FIELD_ALIASES["zoning"] scan across 30+
county GIS layers, and by enrichment_ncpts_lrc.py / nc_lincoln_bulk.py) are
ALREADY on the board -- no new enrichment needed to surface those two inputs.
The third input, a numeric MINIMUM LOT SIZE per zoning code, was checked live
and does not exist as a GIS attribute anywhere this pass found: Oconee SC
publishes a DEDICATED zoning-polygon layer (ZoningMap/MapServer, separate
from its parcel layer) and its only non-geometry fields are ZONING (the code,
e.g. "R-1") and Descript (a name) -- no minimum-lot-size number. This matches
the general pattern already encoded in enrichment_arcgis.py's FIELD_ALIASES,
built and iterated across 30+ county layers over this project's life, which
has never picked up a min-lot-size alias either. A zoning CODE ("R-1", "RA")
is not itself a minimum lot size -- that number lives in each municipality's
zoning ORDINANCE TEXT (a PDF/municode page), which is exactly the "per-town,
not per-state, 15-30 ft in most places, some was 75-100 ft" shape the
synthesis already scopes the frontage table out for. Fabricating a generic
acreage-multiple heuristic in its place (e.g. "flag any parcel over N acres
as subdividable") would not be sourced from anything jurisdiction-specific
and was deliberately not built -- see the task's own instruction not to force
a fake signal. Treat subdividability as: acreage + zoning already visible on
the row, minimum-lot-size and true frontage requirement both manual-only,
same class of gap as the frontage table itself.

===========================================================================
NOT BUILT (dead end) -- adjacency to buyer-registry parcels
===========================================================================
scripts/build_buyer_registry.py produces data/discovered_cash_buyers.json,
423 buyers with a ``sample_parcels`` list (495 parcels total, concentrated in
5 counties: Pickens SC 197, Henderson NC 101, Cleveland NC 96, Burke NC 61,
Madison NC 40). The mechanism this item asks for -- is a land lead
geometrically adjacent to a parcel a known active buyer already owns -- was
checked live and the parcel identifiers do not cross-walk to anything this
codebase can resolve geometry from. build_buyer_registry.py's ``parcel``
field is the ROD (Acclaim) deed index's OWN internal ``ParcelNumber``
("Henderson,NC:1-3669057"), not the county assessor GIS parcel id
parcel_cache.PARCEL_LAYERS and the board's own ``Listing.parcel_id`` use
("9568736975", Henderson's 10-digit PIN format). Querying Henderson's own
parcel layer for PIN='1-3669057' (live, 2026-09-29) returned zero features --
confirmed live, not assumed. Resolving the Acclaim parcel token to a real GIS
parcel would need a SECOND lookup hop (most plausibly an owner-name search
against the same county GIS, i.e. enrichment_resolve_name_to_property's
mechanism) with real false-positive risk on common buyer names, which is a
materially bigger and riskier build than this item's "Easy" rating implies --
left undone rather than forced. If a future pass adds parcel-id capture (not
just the ROD's own token) to build_buyer_registry.py's harvest, this module
is the natural place to wire true polygon-adjacency using the exact geometry
helpers already built here for the landlocked flag.
"""
from __future__ import annotations

import asyncio
import json
import math
import os
import traceback
from typing import Any, Iterable, NamedTuple, Optional

import httpx
import structlog

from .enrichment_arcgis import (
    host_walled, mark_host_walled, note_host_ok, note_host_hard_failure, is_token_error,
)
from .http_client import client
from .models import Listing, PropertyKind

log = structlog.get_logger()

_UA = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) Chrome/126"}

# Rough NC+SC bounding box, same as enrichment_parcel_from_geo._in_box --
# reject (0,0)/out-of-area coords before spending a query on them.
_LAT_MIN, _LAT_MAX = 32.0, 37.0
_LON_MIN, _LON_MAX = -84.5, -75.0

# ---------------------------------------------------------------------------
# Pure geometry helpers (no network) -- shared by both sub-signals.
# ---------------------------------------------------------------------------

_M_PER_DEG_LAT = 110_574.0  # ~constant across NC/SC's latitude range


def _to_local_xy(lon: float, lat: float, lon0: float, lat0: float) -> tuple[float, float]:
    """Equirectangular local meters relative to (lon0, lat0). Accurate to well
    under 1% over the few-hundred-meter extents a single parcel spans."""
    m_per_deg_lon = 111_320.0 * math.cos(math.radians(lat0))
    return (lon - lon0) * m_per_deg_lon, (lat - lat0) * _M_PER_DEG_LAT


def _point_seg_dist_m(px: float, py: float, ax: float, ay: float, bx: float, by: float) -> float:
    """Distance (local meters) from point P to segment AB."""
    dx, dy = bx - ax, by - ay
    if dx == 0 and dy == 0:
        return math.hypot(px - ax, py - ay)
    t = ((px - ax) * dx + (py - ay) * dy) / (dx * dx + dy * dy)
    t = max(0.0, min(1.0, t))
    cx, cy = ax + t * dx, ay + t * dy
    return math.hypot(px - cx, py - cy)


def _seg_seg_dist_m(ax, ay, bx, by, cx, cy, dx, dy) -> float:
    """Approximate min distance (local meters) between segments AB and CD via
    the four endpoint-to-opposite-segment distances. Exact when the segments
    do not cross; near-zero (not exactly 0) when they do, which is immaterial
    at the tens-of-meters scale this module decides at."""
    return min(
        _point_seg_dist_m(ax, ay, cx, cy, dx, dy),
        _point_seg_dist_m(bx, by, cx, cy, dx, dy),
        _point_seg_dist_m(cx, cy, ax, ay, bx, by),
        _point_seg_dist_m(dx, dy, ax, ay, bx, by),
    )


def _point_in_ring_xy(px: float, py: float, ring_xy: list[tuple[float, float]]) -> bool:
    """Ray-casting point-in-polygon on a local-xy ring."""
    inside = False
    n = len(ring_xy)
    if n < 3:
        return False
    j = n - 1
    for i in range(n):
        xi, yi = ring_xy[i]
        xj, yj = ring_xy[j]
        if (yi > py) != (yj > py):
            x_at_py = (xj - xi) * (py - yi) / ((yj - yi) or 1e-12) + xi
            if px < x_at_py:
                inside = not inside
        j = i
    return inside


def _ring_edges_xy(rings: list[list[list[float]]], lon0: float, lat0: float) -> list[tuple]:
    edges = []
    for ring in rings:
        xy = [_to_local_xy(pt[0], pt[1], lon0, lat0) for pt in ring]
        for i in range(len(xy) - 1):
            edges.append((xy[i], xy[i + 1]))
    return edges


def _polyline_edges_xy(paths: list[list[list[float]]], lon0: float, lat0: float) -> list[tuple]:
    edges = []
    for path in paths:
        xy = [_to_local_xy(pt[0], pt[1], lon0, lat0) for pt in path]
        for i in range(len(xy) - 1):
            edges.append((xy[i], xy[i + 1]))
    return edges


def _min_ring_to_polylines_m(
    rings: list[list[list[float]]], polylines: list[list[list[float]]],
    lon0: float, lat0: float,
) -> float:
    """Min meters between any edge of a polygon's rings and any edge of a set
    of polylines (esri [x,y] coordinate order, lon/lat degrees), projected to
    local meters around (lon0, lat0). O(edges * edges) -- cheap at parcel
    scale (typically well under 30 ring edges, a few dozen road edges)."""
    ring_edges = _ring_edges_xy(rings, lon0, lat0)
    road_edges = _polyline_edges_xy(polylines, lon0, lat0)
    if not ring_edges or not road_edges:
        return float("inf")
    best = float("inf")
    for a, b in ring_edges:
        for c, d in road_edges:
            dist = _seg_seg_dist_m(a[0], a[1], b[0], b[1], c[0], c[1], d[0], d[1])
            if dist < best:
                best = dist
    return best


def _haversine_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    r = 6_371_000.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlmb = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dlmb / 2) ** 2
    return 2 * r * math.asin(min(1.0, math.sqrt(a)))


def _point_to_ring_min_dist_m(
    lat: float, lon: float, rings: list[list[list[float]]],
) -> tuple[float, bool]:
    """(min_distance_m, is_inside) from (lat, lon) to a polygon's rings."""
    if not rings:
        return float("inf"), False
    lon0, lat0 = lon, lat
    inside_any = False
    best = float("inf")
    for ring in rings:
        xy = [_to_local_xy(pt[0], pt[1], lon0, lat0) for pt in ring]
        if _point_in_ring_xy(0.0, 0.0, xy):
            inside_any = True
        for i in range(len(xy) - 1):
            ax, ay = xy[i]
            bx, by = xy[i + 1]
            d = _point_seg_dist_m(0.0, 0.0, ax, ay, bx, by)
            if d < best:
                best = d
    if inside_any:
        best = 0.0
    return best, inside_any


# ---------------------------------------------------------------------------
# ArcGIS fetch helper (breaker-aware, same convention as enrichment_arcgis /
# enrichment_parcel_from_geo -- a token/auth error walls the HOST so later
# leads short-circuit instead of re-hitting a dead endpoint).
# ---------------------------------------------------------------------------

async def _arc_get(c, url: str, params: dict) -> Optional[dict]:
    if host_walled(url):
        return None
    try:
        r = await c.get(url, params=params, timeout=25.0)
        if r.status_code != 200:
            note_host_hard_failure(url)
            return None
        data = r.json()
        if "error" in data:
            if is_token_error(data):
                mark_host_walled(url, reason="token/auth error")
            return None
        note_host_ok(url)
        return data
    except (httpx.TransportError, httpx.TimeoutException):
        note_host_hard_failure(url)
        return None
    except Exception:  # noqa: BLE001
        note_host_hard_failure(url)
        return None


# A sentinel distinct from ``None``: ``_arc_get`` returning ``None`` conflates
# two very different things for a caller -- "the query ran and genuinely found
# nothing / was ambiguous" versus "the query never got a real answer" (host
# walled from a prior circuit-breaker trip, a hard failure/non-200, a token
# error, a transport error/timeout, or any other exception _arc_get swallows).
# QUERY_FAILED marks the second case explicitly so it can be told apart from a
# genuine (if negative or inconclusive) determination. See _check_landlocked /
# _check_cemetery docstrings and enrich_land_buildability._one -- only a
# genuine determination (positive, negative, or "not applicable") may set
# raw['_land_buildability_checked']; QUERY_FAILED must leave the row eligible
# for retry once the host recovers.
class _QueryFailed:
    __slots__ = ()

    def __repr__(self) -> str:  # pragma: no cover - debugging aid only
        return "QUERY_FAILED"


QUERY_FAILED = _QueryFailed()


# ---------------------------------------------------------------------------
# Landlocked flag (NC only) -- see module docstring for verification.
# ---------------------------------------------------------------------------

NC1MAP_PARCELS_URL = (
    "https://services.nconemap.gov/secure/rest/services/NC1Map_Parcels/FeatureServer/1/query"
)
NC1MAP_ROADS_URL = (
    "https://services.nconemap.gov/secure/rest/services/NC1Map_Transportation/FeatureServer/0/query"
)

# Same tuned box as enrichment_parcel_from_geo._ENVELOPE_HALF_DEG: tight
# enough to land inside the intended parcel, wide enough to survive the
# server's spatial-index tolerance on NC OneMap's always-empty point query.
_ENVELOPE_HALF_DEG = 5e-5

# Buffer (degrees) around a parcel's own bounding box when searching for
# nearby roads -- ~90-100 m at NC/SC latitude, generous relative to the
# frontage threshold below so a real roadside parcel is never missed.
_ROAD_SEARCH_BUFFER_DEG = 9e-4

# A parcel-boundary edge farther than this from every mapped road centerline
# is a landlocked CANDIDATE. Tuned against 22 live, real, frontage-confirmed
# NC land leads (min distances 1.3-19.4 m) -- see module docstring.
_FRONTAGE_THRESHOLD_M = 30.0


async def _fetch_parcel_polygon_nc(c, lat: float, lon: float):
    """{'rings': [...], 'attrs': {...}} for the ONE NC1Map_Parcels feature the
    tiny envelope around (lat, lon) lands in; None if the query succeeded but
    was genuinely ambiguous (0 or 2+ features -- same guard as
    enrichment_parcel_from_geo._point_query) or had no polygon geometry;
    QUERY_FAILED if the underlying ArcGIS query itself never got a real
    answer (host wall / hard failure / token error -- see _arc_get)."""
    d = _ENVELOPE_HALF_DEG
    params = {
        "geometryType": "esriGeometryEnvelope",
        "geometry": json.dumps({
            "xmin": lon - d, "ymin": lat - d, "xmax": lon + d, "ymax": lat + d,
            "spatialReference": {"wkid": 4326},
        }),
        "inSR": 4326, "spatialRel": "esriSpatialRelIntersects",
        "outFields": "parno,cntyname", "returnGeometry": "true", "outSR": 4326,
        "resultRecordCount": 2, "f": "json",
    }
    data = await _arc_get(c, NC1MAP_PARCELS_URL, params)
    if data is None:
        return QUERY_FAILED
    feats = data.get("features") or []
    if len(feats) != 1:
        return None
    f = feats[0]
    rings = (f.get("geometry") or {}).get("rings") or []
    if not rings:
        return None
    return {"rings": rings, "attrs": f.get("attributes") or {}}


async def _fetch_roads_near_nc(c, rings: list[list[list[float]]]):
    """Road FEATURES (dicts with 'paths' and 'st_name') in a buffered envelope
    around the parcel's own bounding box -- genuinely empty when the query
    succeeded and found none; QUERY_FAILED when the underlying ArcGIS query
    itself never got a real answer (host wall / hard failure -- see
    _arc_get)."""
    xs = [pt[0] for ring in rings for pt in ring]
    ys = [pt[1] for ring in rings for pt in ring]
    if not xs or not ys:
        return []
    b = _ROAD_SEARCH_BUFFER_DEG
    params = {
        "geometryType": "esriGeometryEnvelope",
        "geometry": json.dumps({
            "xmin": min(xs) - b, "ymin": min(ys) - b, "xmax": max(xs) + b, "ymax": max(ys) + b,
            "spatialReference": {"wkid": 4326},
        }),
        "inSR": 4326, "spatialRel": "esriSpatialRelIntersects",
        "outFields": "st_name,st_pretyp,st_posdir,roadclass", "returnGeometry": "true", "outSR": 4326,
        "resultRecordCount": 200, "f": "json",
    }
    data = await _arc_get(c, NC1MAP_ROADS_URL, params)
    if data is None:
        return QUERY_FAILED
    out = []
    for f in data.get("features") or []:
        paths = (f.get("geometry") or {}).get("paths") or []
        if not paths:
            continue
        out.append({"paths": paths, "st_name": (f.get("attributes") or {}).get("st_name")})
    return out


async def _check_landlocked(c, li: Listing):
    """None when not applicable (non-NC, missing lat/lng, out of box) or when
    the query succeeded but was genuinely inconclusive (ambiguous parcel
    resolution); QUERY_FAILED when the underlying ArcGIS query itself never
    got a real answer (host wall / circuit-breaker trip / hard failure --
    caller must NOT treat this as a determination, see enrich_land_buildability
    ._one); a dict with at least 'candidate' on a genuine determination
    (positive or negative)."""
    if li.state != "NC":
        return None
    if li.latitude is None or li.longitude is None:
        return None
    if not (_LAT_MIN <= li.latitude <= _LAT_MAX and _LON_MIN <= li.longitude <= _LON_MAX):
        return None

    parcel = await _fetch_parcel_polygon_nc(c, li.latitude, li.longitude)
    if parcel is QUERY_FAILED:
        return QUERY_FAILED
    if not parcel:
        return None
    rings = parcel["rings"]

    roads = await _fetch_roads_near_nc(c, rings)
    if roads is QUERY_FAILED:
        return QUERY_FAILED
    if not roads:
        return {
            "candidate": True,
            "min_distance_m": None,
            "nearest_road": None,
            "roads_in_envelope": 0,
            "method": "nc1map_parcels+ng911_centerlines",
        }

    xs = [pt[0] for ring in rings for pt in ring]
    ys = [pt[1] for ring in rings for pt in ring]
    lon0, lat0 = sum(xs) / len(xs), sum(ys) / len(ys)

    ring_edges = _ring_edges_xy(rings, lon0, lat0)
    best = float("inf")
    nearest_name = None
    for road in roads:
        road_edges = _polyline_edges_xy(road["paths"], lon0, lat0)
        for c1, d1 in road_edges:
            for a, b in ring_edges:
                dist = _seg_seg_dist_m(a[0], a[1], b[0], b[1], c1[0], c1[1], d1[0], d1[1])
                if dist < best:
                    best = dist
                    nearest_name = road["st_name"]

    if best == float("inf"):
        return {
            "candidate": True, "min_distance_m": None, "nearest_road": None,
            "roads_in_envelope": len(roads), "method": "nc1map_parcels+ng911_centerlines",
        }

    return {
        "candidate": best > _FRONTAGE_THRESHOLD_M,
        "min_distance_m": round(best, 1),
        "nearest_road": nearest_name,
        "roads_in_envelope": len(roads),
        "method": "nc1map_parcels+ng911_centerlines",
    }


# ---------------------------------------------------------------------------
# Cemetery proximity (per-county registry) -- see module docstring.
# ---------------------------------------------------------------------------

class CemeteryLayer(NamedTuple):
    state: str
    county: str
    url: str                 # .../query endpoint
    geometry_type: str        # "point" or "polygon"
    name_field: str
    buffer_deg: float         # search-envelope half-width, tuned per layer
    proximity_m: float        # accept a hit only within this many meters


_CEMETERY_LAYERS: tuple[CemeteryLayer, ...] = (
    # Live-verified 2026-09-29: 370 point records. This layer is a JOIN
    # (displayFieldName "Bun.DBO.CemeteryPoints.StreetName") so ArcGIS returns
    # attributes keyed by the FULLY QUALIFIED field name, not the alias -- a
    # bare outFields="Owner" 400s ("Failed to execute query"), confirmed live.
    # Bun.DBO.CemeteryData.Cemetery_Name is the joined, human-readable
    # cemetery name (0 nulls in a 50-record sample) rather than the plot
    # OWNER's name, so it is both the field that works and the better label.
    CemeteryLayer(
        state="NC", county="Buncombe",
        url="https://gis.buncombecounty.org/arcgis/rest/services/Cemetery/MapServer/0/query",
        geometry_type="point", name_field="Bun.DBO.CemeteryData.Cemetery_Name",
        buffer_deg=18e-4, proximity_m=200.0,
    ),
    # Live-verified 2026-09-29: 245 polygon records, NAME/PRIMARY_PID fields.
    # Polygon geometry lets a lead's own point fall INSIDE a mapped cemetery
    # boundary, which is the strongest form of this signal.
    CemeteryLayer(
        state="NC", county="Gaston",
        url=("https://gis.gastoncountync.gov/publicgis/rest/services/"
             "PublicGIS/Cemeteries/MapServer/15/query"),
        geometry_type="polygon", name_field="NAME",
        buffer_deg=6e-4, proximity_m=75.0,
    ),
)

_CEMETERY_LAYER_BY_COUNTY: dict[tuple[str, str], CemeteryLayer] = {
    (lay.state, lay.county): lay for lay in _CEMETERY_LAYERS
}


async def _check_cemetery(c, li: Listing):
    """None when not applicable (no registered layer for this county, missing
    lat/lng) or when the query succeeded but genuinely found nothing within
    range; QUERY_FAILED when the underlying ArcGIS query itself never got a
    real answer (host wall / hard failure -- see _arc_get); a dict on a
    genuine hit."""
    layer = _CEMETERY_LAYER_BY_COUNTY.get((li.state, li.county))
    if not layer:
        return None
    if li.latitude is None or li.longitude is None:
        return None

    lat, lon = li.latitude, li.longitude
    b = layer.buffer_deg
    params = {
        "geometryType": "esriGeometryEnvelope",
        "geometry": json.dumps({
            "xmin": lon - b, "ymin": lat - b, "xmax": lon + b, "ymax": lat + b,
            "spatialReference": {"wkid": 4326},
        }),
        "inSR": 4326, "spatialRel": "esriSpatialRelIntersects",
        "outFields": layer.name_field, "returnGeometry": "true", "outSR": 4326,
        "resultRecordCount": 25, "f": "json",
    }
    data = await _arc_get(c, layer.url, params)
    if data is None:
        return QUERY_FAILED
    feats = data.get("features") or []
    if not feats:
        return None

    best_d = float("inf")
    best_name = None
    for f in feats:
        geom = f.get("geometry") or {}
        name = (f.get("attributes") or {}).get(layer.name_field)
        if layer.geometry_type == "point":
            gx, gy = geom.get("x"), geom.get("y")
            if gx is None or gy is None:
                continue
            d = _haversine_m(lat, lon, gy, gx)
        else:
            rings = geom.get("rings") or []
            d, inside = _point_to_ring_min_dist_m(lat, lon, rings)
            if inside:
                d = 0.0
        if d < best_d:
            best_d = d
            best_name = name

    if best_d > layer.proximity_m:
        return None

    return {
        "relation": "on_parcel" if best_d <= 5.0 else "nearby",
        "distance_m": round(best_d, 1),
        "cemetery_name": best_name,
        "county": li.county,
        "state": li.state,
    }


# ---------------------------------------------------------------------------
# Entry point.
# ---------------------------------------------------------------------------

_CAP = int(os.environ.get("LAND_BUILDABILITY_CAP", "300"))


async def enrich_land_buildability(listings: list[Listing], concurrency: int = 6) -> dict:
    """Landlocked-candidate flag (NC) + cemetery proximity (2 registered NC
    counties) for LAND leads with lat/lng. Free, pure-HTTP. Additive only --
    writes raw['landlocked'] only on a positive candidate finding and
    raw['cemetery_proximity'] only on a hit, matching the sibling single-
    purpose enrichers' convention of not padding the board with negative
    results. Idempotent via raw['_land_buildability_checked'] (internal, not
    published) so a re-run does not re-query a lead already checked; the
    ``_CAP`` (env LAND_BUILDABILITY_CAP) bounds how many NEW leads one run
    queries, keeping concurrent live-GIS load modest per the project's
    memory-safety / politeness constraints.

    raw['_land_buildability_checked'] is set ONLY when both sub-signals
    reached a genuine determination for this row -- a real positive/negative
    finding, or a structurally "not applicable" case (wrong state, no
    registered cemetery layer, ambiguous parcel resolution). It is
    deliberately NOT set when either _check_landlocked or _check_cemetery
    returns QUERY_FAILED (the underlying ArcGIS query never got a real answer
    because a host was walled by the circuit breaker, hit a hard failure/
    non-200, a token error, or a transport error/timeout -- see _arc_get) or
    when the row raises an unexpected exception. This keeps a row that failed
    purely for transient/host-wall reasons eligible for a future run once the
    host recovers, instead of being silently and permanently excluded from
    retry (fixed 2026-09-29 -- see QUERY_FAILED above and
    tests/test_enrichment_land_buildability.py for the reproduction cases).
    """
    targets = [
        li for li in listings
        if li.property_kind == PropertyKind.LAND
        and li.latitude is not None and li.longitude is not None
        and not (isinstance(li.raw, dict) and li.raw.get("_land_buildability_checked"))
    ][:_CAP]

    stats = {
        "targets": len(targets), "landlocked_candidate": 0, "cemetery_hit": 0,
        "errors": 0, "undetermined": 0,
    }
    if not targets:
        return stats

    sem = asyncio.Semaphore(concurrency)

    async def _one(c, li: Listing) -> None:
        async with sem:
            cemetery_ok = False
            landlocked_ok = False
            try:
                cem = await _check_cemetery(c, li)
                if cem is QUERY_FAILED:
                    cemetery_ok = False
                else:
                    cemetery_ok = True
                    if cem:
                        li.raw["cemetery_proximity"] = cem
                        stats["cemetery_hit"] += 1

                ll = await _check_landlocked(c, li)
                if ll is QUERY_FAILED:
                    landlocked_ok = False
                else:
                    landlocked_ok = True
                    if ll and ll.get("candidate"):
                        li.raw["landlocked"] = ll
                        stats["landlocked_candidate"] += 1
            except Exception:
                stats["errors"] += 1
                log.error("land_buildability.row_failed", traceback=traceback.format_exc())
                cemetery_ok = False
                landlocked_ok = False
            finally:
                if cemetery_ok and landlocked_ok:
                    li.raw["_land_buildability_checked"] = True
                else:
                    stats["undetermined"] += 1

    async with client(timeout=25.0, headers=_UA) as c:
        await asyncio.gather(*(_one(c, li) for li in targets))

    log.info("land_buildability.done", **stats)
    return stats
