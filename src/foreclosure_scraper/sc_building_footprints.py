"""Building-footprint ground-floor area from Microsoft US Building Footprints
(free, ODbL, nationwide) as a SQFT ESTIMATE source for SC counties whose
assessor withholds heated sqft (Spartanburg: LivingArea is 0% populated).

This NEVER produces a true heated-GLA number — it gives footprint ground-floor
area, which enrichment_footprint_sqft multiplies by StoryHeight (from the
Assessor CSV) minus an unheated haircut to ESTIMATE living sqft. Always flagged
estimated=True so the valuation never treats it as ground truth.

Dependency-free: streams the per-state GeoJSON (one Feature per line), clips to a
county bbox, computes polygon area via a local equirectangular projection +
shoelace, and answers point lookups with ray-cast point-in-polygon. Footprints
were captured ~2019, so post-2019 construction is absent.

Build monthly-ish via scripts/build_sc_footprints.py.
"""
from __future__ import annotations

import json
import math
import sqlite3
import urllib.request
import zipfile
from pathlib import Path

import structlog

log = structlog.get_logger()

DB_PATH = Path(__file__).resolve().parent.parent.parent / "data" / "sc_footprints.db"
_SRC_DIR = Path(__file__).resolve().parent.parent.parent / "data" / "footprints_src"

# Microsoft US Building Footprints, legacy v2 per-state GeoJSON (geometry only).
STATE_URL = {
    "SC": "https://minedbuildings.z5.web.core.windows.net/legacy/usbuildings-v2/SouthCarolina.geojson.zip",
    "NC": "https://minedbuildings.z5.web.core.windows.net/legacy/usbuildings-v2/NorthCarolina.geojson.zip",
}

# Generous lon/lat bounding boxes per county (point-in-polygon at lookup time
# guarantees correctness; an over-inclusive bbox only stores a few extra rows).
COUNTY_BBOX = {
    ("SC", "Spartanburg"): (-82.33, 34.77, -81.73, 35.24),
}

_FT_PER_DEG_LAT = 364000.0  # ~constant; good to <0.5% for area estimates


def _poly_area_sqft(ring: list, lat0: float) -> float:
    """Shoelace area in ft^2 via a local equirectangular projection at lat0."""
    ft_lon = _FT_PER_DEG_LAT * math.cos(math.radians(lat0))
    pts = [((p[0]) * ft_lon, (p[1]) * _FT_PER_DEG_LAT) for p in ring]
    s = 0.0
    for i in range(len(pts) - 1):
        s += pts[i][0] * pts[i + 1][1] - pts[i + 1][0] * pts[i][1]
    return abs(s) / 2.0


def _point_in_ring(x: float, y: float, ring: list) -> bool:
    """Ray-casting point-in-polygon (ring = [[lon,lat],...])."""
    inside = False
    n = len(ring)
    j = n - 1
    for i in range(n):
        xi, yi = ring[i][0], ring[i][1]
        xj, yj = ring[j][0], ring[j][1]
        if ((yi > y) != (yj > y)) and (x < (xj - xi) * (y - yi) / ((yj - yi) or 1e-12) + xi):
            inside = not inside
        j = i
    return inside


def _connect() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(DB_PATH)
    con.execute("""CREATE TABLE IF NOT EXISTS footprints (
        state TEXT, county TEXT, cx REAL, cy REAL,
        minx REAL, miny REAL, maxx REAL, maxy REAL, area_sqft REAL, ring TEXT)""")
    con.execute("CREATE INDEX IF NOT EXISTS idx_fp_box ON footprints(state, county, minx, maxx)")
    con.execute("CREATE INDEX IF NOT EXISTS idx_fp_y ON footprints(state, county, miny, maxy)")
    return con


def _download(state: str) -> Path:
    _SRC_DIR.mkdir(parents=True, exist_ok=True)
    dest = _SRC_DIR / Path(STATE_URL[state]).name
    if dest.exists() and dest.stat().st_size > 1_000_000:
        return dest
    req = urllib.request.Request(STATE_URL[state], headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=600) as r, open(dest, "wb") as f:
        while True:
            chunk = r.read(1 << 20)
            if not chunk:
                break
            f.write(chunk)
    return dest


def build_footprints(state: str, county: str) -> int:
    """Stream the state file, clip to the county bbox, store footprint areas."""
    bbox = COUNTY_BBOX.get((state, county))
    if not bbox or state not in STATE_URL:
        return 0
    bxmin, bymin, bxmax, bymax = bbox
    zpath = _download(state)
    rows: list[tuple] = []
    seen = kept = 0
    with zipfile.ZipFile(zpath) as z:
        member = z.namelist()[0]
        with z.open(member) as fh:
            for raw in fh:
                line = raw.strip().rstrip(b",")
                if not line.startswith(b'{"type":"Feature"'):
                    continue
                seen += 1
                try:
                    feat = json.loads(line)
                    ring = feat["geometry"]["coordinates"][0]
                except (ValueError, KeyError, IndexError):
                    continue
                xs = [p[0] for p in ring]
                ys = [p[1] for p in ring]
                cx = sum(xs) / len(xs)
                cy = sum(ys) / len(ys)
                if not (bxmin <= cx <= bxmax and bymin <= cy <= bymax):
                    continue
                area = _poly_area_sqft(ring, cy)
                if area < 120:  # drop sheds/garages/noise below ~120 sqft
                    continue
                kept += 1
                rows.append((state, county, round(cx, 6), round(cy, 6),
                             min(xs), min(ys), max(xs), max(ys), round(area, 1),
                             json.dumps([[round(p[0], 6), round(p[1], 6)] for p in ring])))
    log.info("footprints.parsed", state=state, county=county, scanned=seen, kept=kept)
    con = _connect()
    try:
        con.execute("DELETE FROM footprints WHERE state=? AND county=?", (state, county))
        con.executemany("INSERT INTO footprints VALUES (?,?,?,?,?,?,?,?,?,?)", rows)
        con.commit()
    finally:
        con.close()
    log.info("footprints.stored", state=state, county=county, stored=len(rows))
    return len(rows)


def has_data(state: str, county: str) -> bool:
    if not DB_PATH.exists():
        return False
    con = _connect()
    try:
        return con.execute("SELECT 1 FROM footprints WHERE state=? AND county=? LIMIT 1",
                           (state, county)).fetchone() is not None
    finally:
        con.close()


def largest_in_polygon(state: str, county: str, ring: list) -> tuple | None:
    """Return (area_sqft, 'in_parcel') for the LARGEST footprint whose centroid
    falls inside the parcel polygon — the main dwelling, correctly attributed to
    the parcel (avoids grabbing a neighbor's structure). None if none inside.
    """
    if not DB_PATH.exists() or not ring:
        return None
    xs = [p[0] for p in ring]
    ys = [p[1] for p in ring]
    con = _connect()
    try:
        cand = con.execute(
            """SELECT area_sqft, cx, cy FROM footprints
               WHERE state=? AND county=? AND cx BETWEEN ? AND ? AND cy BETWEEN ? AND ?""",
            (state, county, min(xs), max(xs), min(ys), max(ys))).fetchall()
        inside = [a for (a, cx, cy) in cand if _point_in_ring(cx, cy, ring)]
        return (round(max(inside), 1), "in_parcel") if inside else None
    finally:
        con.close()


def lookup_area(state: str, county: str, lon: float, lat: float) -> tuple | None:
    """Return (area_sqft, match_type) for the footprint at/nearest the point, or None.

    match_type: 'contains' (point inside footprint) or 'nearest' (closest within ~60m).
    """
    if not DB_PATH.exists() or lon is None or lat is None:
        return None
    con = _connect()
    try:
        pad = 0.0007  # ~75 m search pad
        cand = con.execute(
            """SELECT area_sqft, cx, cy, ring FROM footprints
               WHERE state=? AND county=? AND minx<=? AND maxx>=? AND miny<=? AND maxy>=?""",
            (state, county, lon, lon, lat, lat)).fetchall()
        for area, cx, cy, ring in cand:
            if _point_in_ring(lon, lat, json.loads(ring)):
                return round(area, 1), "contains"
        # No footprint contains the parcel point (centroid may sit off the house):
        # take the nearest footprint centroid within the pad.
        near = con.execute(
            """SELECT area_sqft, cx, cy FROM footprints
               WHERE state=? AND county=? AND cx BETWEEN ? AND ? AND cy BETWEEN ? AND ?""",
            (state, county, lon - pad, lon + pad, lat - pad, lat + pad)).fetchall()
        if near:
            best = min(near, key=lambda r: (r[1] - lon) ** 2 + (r[2] - lat) ** 2)
            return round(best[0], 1), "nearest"
        return None
    finally:
        con.close()
