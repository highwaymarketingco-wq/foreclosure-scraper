"""True-oceanfront filter for NC + SC coastal properties.

A listing passes ``is_oceanfront`` when it satisfies AT LEAST TWO of three
signals. Single-signal hits are rejected: each signal can produce false
positives on its own, but two signals agreeing is reliable for "must
have immediate beach front access" (user direction 2026-05-15).

Signals
-------
1. **Description keyword** — listing text contains "oceanfront",
   "beachfront", "direct beach access", "right on the beach", or
   "steps to the beach". MLS rules in NC + SC restrict use of these
   terms to true oceanfront listings; sellers rarely abuse them.

2. **Geofence** — lat/lng is within ``OCEANFRONT_DISTANCE_M`` meters of
   the Atlantic Ocean shoreline polyline. The polyline runs from
   Currituck OBX south to Hilton Head, ocean-facing edges only (sound
   sides excluded — a property on Hilton Head's Calibogue Sound side
   is NOT oceanfront). 150m default accommodates typical oceanfront
   lot depth (~80-100m) plus geocoder centroid drift.

3. **Street whitelist** — the street_address sits on a known
   first-row oceanfront street. Manually curated list per beach town;
   high-precision but incomplete.

Implementation note: the geofence uses local-Euclidean distance after
converting lat/lng to meter offsets from a reference latitude. Accuracy
is sub-meter over our coast (32°-36° N), no shapely dependency needed.
"""
from __future__ import annotations

import math
import re
from typing import Iterable


# Distance threshold for the geofence signal (meters). 150m fits a
# typical oceanfront lot's front-to-back depth plus geocoding drift.
OCEANFRONT_DISTANCE_M = 150.0


# Keywords in description / source text that mean "true oceanfront" in
# MLS parlance. Case-insensitive, matched as substrings.
OCEANFRONT_KEYWORDS: tuple[str, ...] = (
    "oceanfront",
    "ocean front",
    "ocean-front",
    "beachfront",
    "beach front",
    "beach-front",
    "direct beach access",
    "direct ocean access",
    "right on the beach",
    "steps to the beach",
    "feet to the beach",
    "on the sand",
    "sand to the door",
)


# Known first-row oceanfront streets in NC + SC beach towns. Match is on
# the street component of street_address starting with one of these names
# (case-insensitive). Pre-normalized for fast lookup.
OCEANFRONT_STREET_PATTERNS: tuple[tuple[str, str], ...] = (
    # SC Grand Strand
    (r"^\d+\s+(N|North|S|South)?\s*Ocean (?:Blvd|Boulevard)\b", "Myrtle Beach / N Myrtle / Surfside"),
    (r"^\d+\s+Ocean Blvd\s+(N|North|S|South)\b", "N Myrtle Beach"),
    (r"^\d+\s+Atlantic (?:Ave|Avenue)\b.*Pawley", "Pawleys Island"),
    (r"^\d+\s+Ocean Front (?:Dr|Drive)\b", "Garden City"),
    (r"^\d+\s+Springs (?:Ave|Avenue)\b.*Pawley", "Pawleys Island"),
    # SC Charleston barrier islands
    (r"^\d+\s+(E|East|W|West)\s+Ashley (?:Ave|Avenue)\b", "Folly Beach"),
    (r"^\d+\s+Wild Dunes\b", "Isle of Palms"),
    (r"^\d+\s+Ocean (?:Blvd|Boulevard)\b.*Isle of Palms", "Isle of Palms"),
    (r"^\d+\s+(E|East|W|West)\s+Atlantic (?:Ave|Avenue)\b.*Edisto", "Edisto Beach"),
    (r"^\d+\s+Beach Walker (?:Dr|Drive)\b", "Kiawah Island"),
    (r"^\d+\s+Seabrook Island (?:Rd|Road)\b", "Seabrook Island"),
    # SC Hilton Head + Lowcountry
    (r"^\d+\s+(N|North|S|South)\s+Forest Beach (?:Dr|Drive)\b", "Hilton Head"),
    (r"^\d+\s+Burkes Beach (?:Rd|Road)\b", "Hilton Head"),
    (r"^\d+\s+Singleton Beach\b", "Hilton Head"),
    (r"^\d+\s+Folly Field (?:Rd|Road)\b", "Hilton Head"),  # leads to + along ocean
    (r"^\d+\s+Ocean Lane\b", "Hilton Head"),
    (r"^\d+\s+(N|North|S|South)?\s*Sea Pines (?:Dr|Drive)\b", "Hilton Head (Sea Pines)"),
    (r"^\d+\s+Lighthouse (?:Rd|Road)\b.*Hilton Head", "Hilton Head Sea Pines"),
    (r"^\d+\s+Tarpon (?:Blvd|Boulevard)\b", "Fripp Island"),
    (r"^\d+\s+Forest Beach\b", "Hilton Head"),
    (r"^\d+\s+Deallyon (?:Ave|Avenue)\b", "Hilton Head"),  # NW Sea Pines oceanfront row
    (r"^\d+\s+Beachside Tennis\b", "Hilton Head"),
    # NC Wrightsville
    (r"^\d+\s+(N|North|S|South)\s+Lumina (?:Ave|Avenue)\b", "Wrightsville Beach"),
    (r"^\d+\s+(E|East)\s+(Salisbury|Atlanta|Brisbane|Charlotte|Columbia|Greensboro|Henderson)\s+St\b", "Wrightsville Beach"),
    # NC Carolina Beach + Kure
    (r"^\d+\s+Carolina Beach Ave\s+(N|North|S|South)?\b", "Carolina Beach"),
    (r"^\d+\s+(N|North|S|South)?\s*Carolina Beach (?:Ave|Avenue)\b", "Carolina Beach"),
    (r"^\d+\s+Atlantic (?:Ave|Avenue)\b.*Kure", "Kure Beach"),
    (r"^\d+\s+Fort Fisher (?:Blvd|Boulevard)\b", "Kure Beach"),
    # NC Brunswick beaches
    (r"^\d+\s+(E|East|W|West)\s+Beach (?:Dr|Drive)\b", "Oak Island"),
    (r"^\d+\s+Ocean Blvd\s+(E|East|W|West)\b", "Holden Beach / Sunset Beach"),
    (r"^\d+\s+(E|East|W|West)\s+First St\b.*Ocean Isle", "Ocean Isle"),
    (r"^\d+\s+(E|East|W|West)\s+Second St\b.*Ocean Isle", "Ocean Isle"),
    (r"^\d+\s+(E|East|W|West)\s+Main St\b.*Sunset", "Sunset Beach"),
    (r"^\d+\s+Federal (?:Rd|Road)\b.*Bald Head", "Bald Head Island"),
    # NC Topsail Island
    (r"^\d+\s+(N|North|S|South)\s+Anderson (?:Blvd|Boulevard)\b", "Topsail Island"),
    (r"^\d+\s+(N|North|S|South)\s+Shore (?:Dr|Drive)\b.*Surf City", "Surf City"),
    (r"^\d+\s+Ocean (?:Blvd|Boulevard)\b.*Topsail", "Topsail Beach"),
    # NC OBX (Currituck, Dare)
    (r"^\d+\s+(N|North|S|South)\s+Virginia Dare (?:Trl|Trail)\b", "Outer Banks (KDH, KH, NH)"),
    (r"^\d+\s+(N|North|S|South)\s+Croatan (?:Hwy|Highway)\b", "Outer Banks"),
    (r"^\d+\s+Ocean Front Arch\b", "Duck"),
    (r"^\d+\s+Lighthouse (?:Rd|Road)\b.*Buxton", "Cape Hatteras"),
    # NC Bogue Banks (Carteret) — Atlantic Beach, Pine Knoll Shores, Emerald Isle
    (r"^\d+\s+E\.?\s*Fort Macon (?:Rd|Road)\b", "Atlantic Beach"),
    (r"^\d+\s+(E|East|W|West)\s+Salter Path (?:Rd|Road)\b", "Pine Knoll Shores"),
    (r"^\d+\s+Ocean (?:Dr|Drive)\b.*Emerald", "Emerald Isle"),
    (r"^\d+\s+(E|East|W|West)\s+Ocean (?:Dr|Drive)\b.*Emerald", "Emerald Isle"),
)
_STREET_REGEXES: list[re.Pattern] = [
    re.compile(pat, re.I) for pat, _label in OCEANFRONT_STREET_PATTERNS
]


# Atlantic Ocean shoreline polyline for NC + SC. Ocean-facing edges only
# (sound / ICW / harbor sides excluded — a Hilton Head property facing
# Calibogue Sound is NOT oceanfront). North-to-south, ~70 vertices for
# sub-mile resolution. Each entry is (lat, lng).
_COAST_NC_SC: tuple[tuple[float, float], ...] = (
    # Currituck OBX
    (36.554, -75.880),  # Carova
    (36.450, -75.860),  # Corolla
    (36.378, -75.832),
    (36.260, -75.770),  # Duck
    (36.155, -75.738),  # Southern Shores
    (36.072, -75.708),  # Kitty Hawk
    (36.020, -75.667),  # Kill Devil Hills
    (35.957, -75.611),  # Nags Head
    (35.857, -75.564),  # South Nags Head
    (35.788, -75.503),  # Bodie Island
    (35.687, -75.491),  # Rodanthe
    (35.625, -75.473),  # Salvo
    (35.555, -75.474),  # Avon
    (35.270, -75.520),  # Cape Hatteras
    (35.244, -75.610),  # Frisco
    (35.215, -75.690),  # Hatteras Village
    (35.111, -75.985),  # Ocracoke (Hwy 12 end)
    # Carteret
    (34.616, -76.535),  # Cape Lookout
    (34.692, -76.738),  # Atlantic Beach
    (34.694, -76.812),  # Pine Knoll Shores
    (34.671, -76.945),  # Indian Beach
    (34.660, -77.078),  # Emerald Isle
    # Onslow / Pender
    (34.524, -77.327),  # North Topsail Beach (north end)
    (34.477, -77.430),  # North Topsail
    (34.421, -77.547),  # Surf City
    (34.366, -77.624),  # Topsail Beach (south end)
    # New Hanover
    (34.222, -77.788),  # Wrightsville Beach (north)
    (34.210, -77.793),  # Wrightsville Beach (south)
    (34.130, -77.870),  # Masonboro Island
    (34.040, -77.886),  # Carolina Beach
    (33.991, -77.911),  # Kure Beach
    (33.948, -77.953),  # Fort Fisher
    # Brunswick
    (33.855, -77.987),  # Bald Head Island (south point)
    (33.871, -78.025),  # Bald Head west
    (33.910, -78.075),  # Oak Island (east end)
    (33.910, -78.170),  # Oak Island (middle)
    (33.913, -78.255),  # Oak Island (west) / Caswell
    (33.907, -78.290),  # Holden Beach (east)
    (33.910, -78.370),  # Holden Beach (west)
    (33.893, -78.420),  # Ocean Isle Beach (east)
    (33.888, -78.500),  # Ocean Isle Beach (west)
    (33.880, -78.535),  # Sunset Beach
    # SC Grand Strand (Horry)
    (33.853, -78.595),  # Cherry Grove
    (33.823, -78.683),  # N Myrtle Beach
    (33.778, -78.745),  # Crescent Beach
    (33.728, -78.829),  # Atlantic Beach SC
    (33.690, -78.890),  # Myrtle Beach (north)
    (33.620, -78.965),  # Myrtle Beach (south)
    (33.602, -78.973),  # Surfside
    (33.578, -78.998),  # Garden City
    # SC Georgetown
    (33.510, -79.063),  # Litchfield
    (33.450, -79.120),  # Pawleys Island (north)
    (33.396, -79.158),  # Pawleys (south) / DeBordieu
    (33.250, -79.225),  # Cedar Island
    (33.118, -79.355),  # Bulls Bay / Cape Romain
    # SC Charleston (Charleston County barrier islands)
    (32.962, -79.529),  # Bulls Island
    (32.870, -79.660),  # Capers Island
    (32.795, -79.760),  # Isle of Palms (north)
    (32.776, -79.795),  # Isle of Palms (south) / Sullivan's
    (32.755, -79.838),  # Sullivan's Island
    (32.680, -79.890),  # Folly Beach (north)
    (32.645, -79.928),  # Folly Beach (south)
    (32.598, -80.022),  # Kiawah Island (east)
    (32.572, -80.085),  # Kiawah (south) / Seabrook
    (32.563, -80.180),  # Seabrook
    (32.498, -80.307),  # Edisto Beach
    # SC Beaufort (Hunting, Fripp, Hilton Head). 2026-05-15 — these were
    # drawn through Calibogue Sound by mistake; corrected to true ocean
    # shore on east side of each island.
    (32.420, -80.443),  # Otter Island ocean
    (32.370, -80.430),  # Hunting Island ocean (east shore)
    (32.327, -80.470),  # Fripp Island ocean
    (32.260, -80.530),  # Pritchards Island ocean
    (32.252, -80.690),  # Hilton Head — north (Port Royal Plantation ocean)
    (32.215, -80.690),  # Hilton Head — N central (Folly Field area)
    (32.190, -80.700),  # Hilton Head — Singleton Beach
    (32.165, -80.730),  # Hilton Head — Mid Forest Beach
    (32.135, -80.770),  # Hilton Head — Sea Pines north
    (32.115, -80.810),  # Hilton Head — Sea Pines south point
    # Daufuskie + Tybee-area approach (Hilton Head south end faces sound)
)


def _latlng_to_meters(lat: float, lng: float, ref_lat: float) -> tuple[float, float]:
    """Convert (lat, lng) to (x, y) meters in a local flat plane.
    Accurate to sub-meter over a few-hundred-km extent."""
    m_per_deg_lat = 111_320.0
    m_per_deg_lng = 111_320.0 * math.cos(math.radians(ref_lat))
    return lng * m_per_deg_lng, lat * m_per_deg_lat


def _distance_to_segment(px: float, py: float, ax: float, ay: float,
                          bx: float, by: float) -> float:
    """Euclidean distance from point P to segment AB."""
    dx, dy = bx - ax, by - ay
    if dx == 0 and dy == 0:
        return math.hypot(px - ax, py - ay)
    t = max(0.0, min(1.0, ((px - ax) * dx + (py - ay) * dy) / (dx * dx + dy * dy)))
    cx, cy = ax + t * dx, ay + t * dy
    return math.hypot(px - cx, py - cy)


def distance_to_shoreline_m(lat: float, lng: float) -> float:
    """Return distance in meters from (lat, lng) to the nearest point on
    the NC+SC Atlantic Ocean shoreline polyline. Sub-meter accurate at
    our latitudes via local-Euclidean conversion.
    """
    if not (-90 <= lat <= 90) or not (-180 <= lng <= 180):
        return float("inf")
    ref = 34.0  # mid-coast latitude
    px, py = _latlng_to_meters(lat, lng, ref)
    best = float("inf")
    prev = _latlng_to_meters(_COAST_NC_SC[0][0], _COAST_NC_SC[0][1], ref)
    for nxt_ll in _COAST_NC_SC[1:]:
        cur = _latlng_to_meters(nxt_ll[0], nxt_ll[1], ref)
        d = _distance_to_segment(px, py, prev[0], prev[1], cur[0], cur[1])
        if d < best:
            best = d
        prev = cur
    return best


def _keyword_hit(text: str | None) -> bool:
    if not text:
        return False
    low = text.lower()
    return any(k in low for k in OCEANFRONT_KEYWORDS)


def _street_hit(street_address: str | None, city: str | None) -> bool:
    if not street_address:
        return False
    # Inline the city into the address string so address-only regexes
    # like ".*Edisto" can match the city portion.
    blob = f"{street_address} {city or ''}"
    return any(rx.search(blob) for rx in _STREET_REGEXES)


def is_oceanfront(*, description: str | None = None,
                   street_address: str | None = None,
                   city: str | None = None,
                   latitude: float | None = None,
                   longitude: float | None = None,
                   distance_threshold_m: float = OCEANFRONT_DISTANCE_M,
                   ) -> tuple[bool, dict]:
    """Return (is_oceanfront, signals) where ``signals`` enumerates which
    of the three checks passed. A listing is considered oceanfront when
    AT LEAST TWO of three signals hit.

    >>> ok, sig = is_oceanfront(description="True oceanfront 3br",
    ...                          street_address="123 N Lumina Ave",
    ...                          city="Wrightsville Beach",
    ...                          latitude=34.222, longitude=-77.788)
    >>> ok
    True
    """
    kw = _keyword_hit(description)
    st = _street_hit(street_address, city)
    geo = False
    geo_dist = None
    if latitude is not None and longitude is not None:
        try:
            geo_dist = distance_to_shoreline_m(float(latitude), float(longitude))
            geo = geo_dist <= distance_threshold_m
        except (TypeError, ValueError):
            geo_dist = None
    hits = sum((kw, st, geo))
    return hits >= 2, {
        "keyword": kw,
        "street": st,
        "geofence": geo,
        "geo_distance_m": geo_dist,
        "hits": hits,
    }
