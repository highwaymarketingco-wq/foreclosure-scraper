"""Idempotent board data-quality corrections — runs late in the pipeline / regenerate.

Fixes verified 2026-06-30 against the live board:
  * out-of-footprint geocodes: 3 leads landed in CT/KY/AL (geocoder fell back to a wrong state).
    Null lat/lon + flag so the map and geo-comps don't trust them.
  * centroid/town-center snaps: 319 leads share an identical 5-decimal coordinate (42 on one point)
    = a county-centroid or town-center fallback, not a real rooftop. Flag raw['geo_imprecise'] so
    the map/comps can down-weight; keep the coord (county-level locate is still useful).
  * auction_status casing/empties: 'none'/'' vs None fragmented every status filter. Normalize.
  * presumed_withdrawn stale cases (1,647, incl most of the HOT tier): the case stopped appearing
    in the lis-pendens feed = likely resolved/withdrawn. Flag raw['stale_case'] and down-rank a
    stale HOT to WARM so the operator's HOT queue isn't dominated by dead leads (non-destructive —
    the lead stays on the board, just not prioritized).
"""
from __future__ import annotations

import collections

# NC + SC bounding box (generous): lat 32.0–36.8, lon −84.5 to −75.3.
_LAT_MIN, _LAT_MAX, _LON_MIN, _LON_MAX = 32.0, 36.8, -84.5, -75.3
_CENTROID_MIN_COLLISIONS = 8   # >=8 leads on the exact same ~1m point = geocoder fallback


def _raw(li) -> dict:
    if not isinstance(li.raw, dict):
        li.raw = {}
    return li.raw


def enrich_board_quality(listings) -> dict:
    stats: collections.Counter = collections.Counter()

    # Pre-pass: find centroid-collision coordinates (shared by many leads).
    coord = collections.Counter(
        (round(li.latitude, 5), round(li.longitude, 5))
        for li in listings
        if getattr(li, "latitude", None) and getattr(li, "longitude", None)
    )
    centroids = {c for c, n in coord.items() if n >= _CENTROID_MIN_COLLISIONS}

    for li in listings:
        raw = _raw(li)

        # 1. geo bbox guard — null clearly-wrong out-of-state coordinates.
        lat, lon = getattr(li, "latitude", None), getattr(li, "longitude", None)
        if lat is not None and lon is not None:
            if not (_LAT_MIN <= lat <= _LAT_MAX and _LON_MIN <= lon <= _LON_MAX):
                li.latitude = None
                li.longitude = None
                raw["geo_imprecise"] = "out_of_bbox"
                # a geo-anchored ARV built on wrong-location comps is untrustworthy
                if isinstance(raw.get("calc"), dict):
                    raw["calc"]["arv_geo_suspect"] = True
                stats["bbox_nulled"] += 1
            elif (round(lat, 5), round(lon, 5)) in centroids:
                raw["geo_imprecise"] = "centroid_snap"
                stats["centroid_flagged"] += 1

        # 2. auction_status normalization.
        st = getattr(li, "auction_status", None)
        if isinstance(st, str):
            norm = st.strip().lower()
            if norm in ("", "none", "null", "n/a"):
                li.auction_status = None
                stats["status_nulled"] += 1
            elif norm != st:
                li.auction_status = norm
                stats["status_normalized"] += 1

        # 3. stale presumed-withdrawn cases — flag + down-rank a stale HOT.
        if (getattr(li, "auction_status", None) or "") == "presumed_withdrawn":
            raw["stale_case"] = True
            stats["stale_flagged"] += 1
            ds = raw.get("distress_stack")
            if isinstance(ds, dict) and ds.get("tier") == "HOT":
                ds["tier"] = "WARM"
                ds["downranked_stale"] = True
                stats["hot_downranked"] += 1

    return dict(stats)
