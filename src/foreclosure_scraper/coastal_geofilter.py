"""Ocean-proximity geofilter — "on the beach or within ~2-3 blocks of the Atlantic".

The owner wants ONLY oceanfront / near-ocean coastal NC+SC properties (hard pass
on anything further inland). This filters parcels/listings by straight-line
distance from their lat/lon to the Atlantic OCEAN shoreline.

Reference shoreline: OpenStreetMap `natural=coastline` for the NC+SC coast,
fetched + decimated (~80 m spacing) into data/nc_sc_ocean_coastline.json. OSM's
coastline is the land/SEA boundary and EXCLUDES the Intracoastal Waterway /
sounds (those are tagged `waterway`/`water`), so distance-to-coastline ≈
distance-to-OPEN-OCEAN — which is exactly what "near the beach" means and is why
sound-side and inland towns (Manteo, Morehead City, Wilmington, Mt. Pleasant
city, Beaufort) correctly fall outside the threshold.

Default threshold 250 m ≈ 2-3 standard blocks. Free, offline, no API at runtime.
"""
from __future__ import annotations

import json
import math
import pathlib
from functools import lru_cache
from typing import Optional

_COAST_FILE = pathlib.Path(__file__).parent / "data" / "nc_sc_ocean_coastline.json"

# 2-3 blocks. A coastal "block" is ~80-100 m; 250 m keeps the first ~2-3 rows of
# lots and drops everything behind them.
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
