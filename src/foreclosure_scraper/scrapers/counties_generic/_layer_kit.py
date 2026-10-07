"""Small shared helpers for the single-purpose county/city ArcGIS layer scrapers added
2026-10-07 (docs/new_sources_2026-10-07_distress.md).

Leading underscore: the registry skips this module (it holds no scraper).

Every attribute bag read through :func:`fetch_attrs` goes through
``sensitive_fields.drop_sensitive`` before any caller sees it, and ``out_fields`` must be an
explicit list (``arcgis_webmap.query_features`` refuses ``*``).

DATELESS SOURCES: ``main._active_only`` drops a row with no ``sale_date`` unless its
``source`` is whitelisted in ``main.DATELESS_OK_SOURCES``. That set already admits the
whole ``counties_generic.arcgis_distress.<layer>`` family by prefix, which is what these
modules are (one county ArcGIS layer that IS the distress signal). :data:`DATELESS_PREFIX`
is that family's prefix, so a dateless lead from these modules reaches the board without
editing ``main.py``.
"""
from __future__ import annotations

from typing import Any, Iterable, Optional

from ... import arcgis_webmap as agw
from ...sensitive_fields import drop_sensitive

DATELESS_PREFIX = "counties_generic.arcgis_distress."


def clean(v: Any) -> Optional[str]:
    """Whitespace-squashed text, or None for blank/None."""
    s = " ".join(str(v).split()) if v is not None else ""
    return s or None


def num(v: Any) -> Optional[float]:
    """A positive number from a numeric or '$1,234' string, else None."""
    try:
        f = float(str(v).replace(",", "").replace("$", "").strip())
    except (TypeError, ValueError):
        return None
    return f if f > 0 else None


def norm_addr(s: Optional[str]) -> str:
    return " ".join((s or "").lower().replace(",", " ").split())


def owner_mailing(owner: Optional[str], parts: Iterable[Any], mail_state: Any,
                  situs: Optional[str], parcel: Optional[str], home_state: str,
                  source: str) -> Optional[dict]:
    """The raw['owner_mailing'] block the rest of the pipeline reads (absentee and
    out-of-state flags). None when the layer carries no mailing line."""
    mailing = " ".join(b for b in (clean(p) for p in parts) if b) or None
    if not mailing:
        return None
    st = (clean(mail_state) or "").upper()[:2] or None
    return {
        "owner": owner,
        "mailing": mailing,
        "situs": situs,
        "parcel_id": parcel,
        "mail_state": st,
        "absentee": bool(situs and norm_addr(situs) not in norm_addr(mailing)),
        "out_of_state": bool(st and st != home_state),
        "source": source,
    }


async def fetch_attrs(http, layer_url: str, fields: Iterable[str], where: str = "1=1",
                      page: int = 1000) -> list[dict]:
    """Every row of one layer (paged), attribute dicts only, sensitive columns dropped."""
    rows = await agw.query_attributes(http, layer_url, out_fields=",".join(fields),
                                      where=where, page=page)
    return [drop_sensitive(a) for a in rows]


# ------------------------------------------------------------------------------------------
# Spatial helpers (2026-10-07, second round): a layer whose rows carry only a point or an
# outline (Charleston's EnerGov history points, Iredell's delinquent-parcel outlines) is tied
# to a parcel by asking the parcel / address layer for the features under a BATCH of points
# (one multipoint query per `batch` points, polite pacing) and matching each point locally.
# ------------------------------------------------------------------------------------------
import asyncio
import json as _json
import math as _math


def point_in_rings(x: float, y: float, rings) -> bool:
    """Even-odd ray cast over every ring (holes included), so a point in a hole is outside."""
    inside = False
    for ring in rings or ():
        n = len(ring)
        for i in range(n):
            x1, y1 = ring[i][0], ring[i][1]
            x2, y2 = ring[i - 1][0], ring[i - 1][1]
            if (y1 > y) != (y2 > y):
                xi = (x2 - x1) * (y - y1) / ((y2 - y1) or 1e-300) + x1
                if x < xi:
                    inside = not inside
    return inside


def interior_point(rings) -> Optional[tuple[float, float]]:
    """A point INSIDE a polygon (an odd parcel's centroid can fall outside it): the midpoint of
    the widest span of a horizontal line through the vertex-average height."""
    pts = [p for r in (rings or ()) for p in r]
    if not pts:
        return None
    y = sum(p[1] for p in pts) / len(pts)
    xs = []
    for ring in rings:
        n = len(ring)
        for i in range(n):
            x1, y1 = ring[i][0], ring[i][1]
            x2, y2 = ring[i - 1][0], ring[i - 1][1]
            if (y1 > y) != (y2 > y):
                xs.append((x2 - x1) * (y - y1) / ((y2 - y1) or 1e-300) + x1)
    xs.sort()
    best = None
    for a, b in zip(xs[0::2], xs[1::2]):
        if best is None or b - a > best[1] - best[0]:
            best = (a, b)
    if best is None:
        return (sum(p[0] for p in pts) / len(pts), y)
    return ((best[0] + best[1]) / 2.0, y)


def _meters(x1, y1, x2, y2) -> float:
    k = 111_320.0
    return _math.hypot((x2 - x1) * k * _math.cos(_math.radians((y1 + y2) / 2)), (y2 - y1) * k)


async def match_points(http, layer_url: str, points: list[tuple[float, float]], fields,
                       *, where: str = "1=1", distance_m: Optional[float] = None,
                       batch: int = 100, delay_s: float = 1.7) -> list[Optional[dict]]:
    """For each (lon, lat) WGS84 point, the attributes of the feature of `layer_url` it falls in
    (polygon layer) or the nearest one within `distance_m` (point layer); None when there is none.
    One POST per `batch` points; sensitive columns are dropped; geometry never leaves here."""
    out: list[Optional[dict]] = [None] * len(points)
    url = layer_url.rstrip("/") + "/query"
    first = True
    for start in range(0, len(points), batch):
        chunk = points[start:start + batch]
        if not chunk:
            continue
        if not first and delay_s:
            await asyncio.sleep(delay_s)
        first = False
        params = {
            "where": where, "outFields": ",".join(fields), "f": "json",
            "geometry": _json.dumps({"points": [[x, y] for x, y in chunk],
                                     "spatialReference": {"wkid": 4326}}),
            "geometryType": "esriGeometryMultipoint", "inSR": "4326", "outSR": "4326",
            "spatialRel": "esriSpatialRelIntersects", "returnGeometry": "true",
        }
        if distance_m:
            params.update({"distance": str(distance_m), "units": "esriSRUnit_Meter"})
        r = await http.post(url, data=params, timeout=90.0)
        if r.status_code != 200:
            raise RuntimeError(f"{layer_url}: HTTP {r.status_code}")
        d = r.json()
        if d.get("error"):
            raise RuntimeError(f"{layer_url}: {str(d['error'])[:160]}")
        feats = [(drop_sensitive(f.get("attributes") or {}), f.get("geometry") or {})
                 for f in d.get("features") or []]
        for i, (x, y) in enumerate(chunk):
            best, best_d = None, None
            for attrs, g in feats:
                if "rings" in g:
                    if point_in_rings(x, y, g["rings"]):
                        best = attrs
                        break
                elif "x" in g:
                    dd = _meters(x, y, g["x"], g["y"])
                    if (distance_m is None or dd <= distance_m) and (best_d is None or dd < best_d):
                        best, best_d = attrs, dd
            out[start + i] = best
    return out
