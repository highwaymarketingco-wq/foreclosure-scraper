"""Ocean-proximity geofilter: straight-line distance from a lat/lon to the Atlantic shore.

Reference shoreline: OpenStreetMap `natural=coastline` for the NC+SC coast, fetched +
decimated (~80 m spacing) into data/nc_sc_ocean_coastline.json. OSM's coastline is the
land/water boundary. It excludes the Intracoastal Waterway proper (tagged `waterway`/`water`)
but it is NOT only the open ocean: it also follows Charleston Harbor, the rivers and bays
behind the Carolina barrier islands, and the Pamlico / Currituck / Roanoke sound shores.
Measured 2026-10-06: the Charleston Battery is 123 m from it, Morehead City downtown 237 m,
Swansboro 118 m, Manteo 1.5 km. So `distance_to_ocean_m` is the distance to the nearest
SHORE, and "near the beach" for anything beyond a block or two needs the ocean-facing check in
oceanfront.flip_near_beach (curated ocean-only polyline) on top of it.

Two bars use this distance (see oceanfront.py): NEAR_BEACH_M below, the true "on the beach or
a couple of blocks back" bar (250 m, owner 2026-06-22), and oceanfront.FLIP_COASTAL_MAX_M, the
flip bar (owner 2026-10-06, "nothing more than a 5 minute drive to the beach"). Free, offline,
no API at runtime.
"""
from __future__ import annotations

import json
import math
import pathlib
from functools import lru_cache
from typing import Optional

_COAST_FILE = pathlib.Path(__file__).parent / "data" / "nc_sc_ocean_coastline.json"

# 2-3 blocks. A coastal "block" is ~80-100 m; 250 m keeps the first ~2-3 rows of
# lots and drops everything behind them. This is the true-beachfront bar (raw.oceanfront);
# a FLIP is admitted farther out, see oceanfront.FLIP_COASTAL_MAX_M.
NEAR_BEACH_M = 250.0


@lru_cache(maxsize=1)
def _coastline() -> list[tuple[float, float]]:
    if not _COAST_FILE.exists():
        return []
    return [(p[0], p[1]) for p in json.loads(_COAST_FILE.read_text())]


def _haversine_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    R = 6_371_000.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dl = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * R * math.asin(math.sqrt(a))


def distance_to_ocean_m(lat: float, lon: float) -> Optional[float]:
    """Meters from (lat, lon) to the nearest Atlantic ocean shoreline point,
    or None if no coordinates / no coastline data."""
    if lat is None or lon is None:
        return None
    pts = _coastline()
    if not pts:
        return None
    # Coarse bbox pre-filter (~0.06deg ~= 6.5 km) so we only haversine the local
    # coast, not all 30k points. Widen if nothing falls in the window.
    for win in (0.06, 0.2, 1.0):
        near = [(a, o) for a, o in pts if abs(a - lat) <= win and abs(o - lon) <= win]
        if near:
            return min(_haversine_m(lat, lon, a, o) for a, o in near)
    return min(_haversine_m(lat, lon, a, o) for a, o in pts)


def is_near_beach(lat: float, lon: float, max_m: float = NEAR_BEACH_M) -> bool:
    """True when (lat, lon) is on or within max_m of the open Atlantic shore."""
    d = distance_to_ocean_m(lat, lon)
    return d is not None and d <= max_m
