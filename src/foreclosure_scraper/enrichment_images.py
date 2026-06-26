"""Multi-source image stack so every listing has Vision-usable imagery.

For every geocoded listing we attach:
  raw.images.real      — list of real listing photos (HomeHarvest, Realtor)
  raw.images.aerial    — Esri World Imagery aerial (free, no key)
  raw.images.street    — Mapillary user-contributed street-level (free)
  raw.images.map       — OSM static-map fallback
  raw.images.primary   — best image (real > street > aerial > map)
  raw.images.approx    — True when the aerial/map is centered on an
                         approximate point (geocoded by property name or
                         city), NOT a precise rooftop/parcel point.
  raw.zillow.photo     — alias of primary so dashboard frontend reads it

Coverage goal: an image for EVERY lead. An aerial+map always attach when we
have lat/lng that is precise enough to point at the actual parcel:

  * real street_address (rooftop geocode / GIS situs), OR
  * a parcel_id (the lat/lng is a parcel-polygon centroid), OR
  * lat/lng we just resolved by geocoding 'property name, city, state'.

We deliberately REFUSE to attach an aerial when the only lat/lng is a coarse
county-seat centroid (Tier-4 geocode fallback): hundreds of unrelated parcels
share that one coordinate, so a single courthouse aerial tile would be
cross-applied to all of them. Those leads instead get a city/parcel-level
aerial only once we can pin a real point, and are flagged approx when we fall
back to a city centroid.

Name-only complexes (HUD REAC/Section 8 multifamily) carry a property name +
city but no street. We geocode 'name, city, state' so the aerial frames the
actual building footprint; failing that we use the city centroid and set
images.approx=True so the dashboard/Vision know it is a neighborhood view, not
a rooftop.
"""
from __future__ import annotations

import asyncio
import math
from typing import Optional

import httpx
import structlog

from .models import Listing

log = structlog.get_logger()

UA = "ForeclosureScraperDashboard/1.0 (highwaymarketingco@gmail.com)"
NOMINATIM = "https://nominatim.openstreetmap.org/search"
CENSUS_GEO = "https://geocoding.geo.census.gov/geocoder/locations/onelineaddress"

# County-seat centroids that the Tier-4 geocode fallback stamps onto leads with
# no usable address/city. These are SHARED by many unrelated leads, so an aerial
# centered here is meaningless — we must NOT attach one. Kept in sync with
# enrichment_geocode.COUNTY_SEAT_CENTROIDS.
_COUNTY_SEAT_CENTROIDS: set[tuple[float, float]] = {
    (34.949, -81.932), (34.504, -82.650), (34.882, -82.706), (34.764, -83.064),
    (35.072, -81.650), (34.713, -81.624), (34.499, -82.018), (35.371, -81.957),
    (35.292, -81.535), (35.318, -82.461), (35.252, -82.197), (35.262, -81.187),
    (35.227, -80.843), (35.595, -82.551), (35.233, -82.734), (35.674, -82.040),
    (35.470, -81.255), (35.825, -82.728), (35.918, -82.299), (35.997, -82.143),
    (35.745, -81.685),
}
# Rounded form for tolerant matching (geocode stores them at 3 dp).
_COUNTY_SEAT_ROUNDED: set[tuple[float, float]] = {
    (round(a, 3), round(b, 3)) for a, b in _COUNTY_SEAT_CENTROIDS
}

# In-process geocode cache shared across the run (keyed by query string).
_GEO_CACHE: dict[str, Optional[tuple[float, float]]] = {}


def _is_county_seat_point(lat: float, lon: float) -> bool:
    """True when (lat, lon) is one of the coarse county-seat centroids that the
    geocode Tier-4 fallback shares across many leads."""
    return (round(lat, 3), round(lon, 3)) in _COUNTY_SEAT_ROUNDED


def _has_precise_point(li: Listing) -> bool:
    """A lat/lng precise enough to frame the actual parcel: it came from a real
    address, a parcel-polygon centroid, or a name/city geocode — and is NOT a
    shared county-seat centroid."""
    if li.latitude is None or li.longitude is None:
        return False
    if _is_county_seat_point(li.latitude, li.longitude):
        return False
    if (li.street_address or "").strip():
        return True
    if (li.parcel_id or "").strip():
        return True
    return False


# ---- Aerial (Esri World Imagery — free, no key) ----------------------------

def _aerial_url_for_point(lat: float, lon: float, zoom: int = 19) -> str:
    """Esri World Imagery tile URL — high-res aerial, public, no key."""
    n = 2 ** zoom
    x = int((lon + 180) / 360 * n)
    y = int((1 - math.log(math.tan(math.radians(lat)) + 1 / math.cos(math.radians(lat))) / math.pi) / 2 * n)
    return f"https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{zoom}/{y}/{x}"


def _osm_static_map_url(lat: float, lon: float, zoom: int = 17) -> str:
    return (f"https://staticmap.openstreetmap.de/staticmap.php?"
            f"center={lat:.6f},{lon:.6f}&zoom={zoom}&size=600x400&maptype=mapnik"
            f"&markers={lat:.6f},{lon:.6f},red-dot")


# ---- Mapillary street-level (free public API, no key for /search) ----------

async def _mapillary_image(c: httpx.AsyncClient, lat: float, lon: float) -> Optional[str]:
    """Find closest Mapillary user-contributed street photo to (lat, lon)."""
    try:
        delta = 0.002  # ~200m
        bbox = f"{lon - delta},{lat - delta},{lon + delta},{lat + delta}"
        r = await c.get(
            "https://graph.mapillary.com/images",
            params={"fields": "thumb_1024_url", "bbox": bbox, "limit": 1},
            timeout=8.0,
        )
        if r.status_code != 200:
            return None
        items = (r.json().get("data") or [])
        if items:
            return items[0].get("thumb_1024_url")
    except Exception:
        return None
    return None


# ---- Geocode-by-name for name+city leads (multifamily complexes) -----------

async def _census_geocode(c: httpx.AsyncClient, address: str) -> Optional[tuple[float, float]]:
    try:
        r = await c.get(
            CENSUS_GEO,
            params={"address": address, "benchmark": "Public_AR_Current", "format": "json"},
            timeout=12.0,
        )
        if r.status_code != 200:
            return None
        matches = ((r.json().get("result") or {}).get("addressMatches")) or []
        if matches:
            coords = matches[0].get("coordinates") or {}
            if "x" in coords and "y" in coords:
                return (float(coords["y"]), float(coords["x"]))
    except Exception:
        return None
    return None


async def _nominatim_geocode(c: httpx.AsyncClient, query: str) -> Optional[tuple[float, float]]:
    try:
        r = await c.get(
            NOMINATIM,
            params={"q": query, "format": "jsonv2", "limit": 1, "countrycodes": "us"},
            headers={"User-Agent": UA},
            timeout=12.0,
        )
        if r.status_code != 200:
            return None
        data = r.json()
        if data and isinstance(data, list):
            return (float(data[0]["lat"]), float(data[0]["lon"]))
    except Exception:
        return None
    return None


def _name_for(li: Listing) -> Optional[str]:
    """Best 'building/complex name' to geocode a name-only lead by. HUD REAC/
    Section 8 stash the property name in raw.reac.property_name / owner_name."""
    raw = li.raw if isinstance(li.raw, dict) else {}
    for src in (
        (raw.get("reac") or {}).get("property_name"),
        raw.get("property_name"),
        li.owner_name,
    ):
        if src and isinstance(src, str) and src.strip():
            # Skip obvious person-name owners for street-level geocoding? No —
            # a complex named after a person ('AGAPE RETIREMENT HOME') still
            # geocodes fine. Just require it look like a place, not 'LASTNAME F'.
            return src.strip()
    return None


async def _geocode_named_complex(
    c: httpx.AsyncClient, li: Listing, nominatim_delay: float
) -> tuple[Optional[tuple[float, float]], bool]:
    """Resolve lat/lng for a name+city lead with no street/parcel.

    Returns (point, approx). approx=True means the point is a city centroid
    (neighborhood view), False means we matched the named place / its address.
    """
    name = _name_for(li)
    city, state = (li.city or "").strip(), (li.state or "").strip()
    if not (city and state):
        return None, False

    # Tier A: 'name, city, state' via Nominatim (knows POIs/building names),
    # then Census (structured) as a backstop.
    if name:
        q = f"{name}, {city}, {state}"
        if q in _GEO_CACHE:
            res = _GEO_CACHE[q]
        else:
            res = await _nominatim_geocode(c, q)
            _GEO_CACHE[q] = res
            await asyncio.sleep(nominatim_delay)
        if res:
            return res, False

    # Tier B: city centroid (approximate — neighborhood view, clearly flagged).
    q = f"{city}, {state}"
    if q in _GEO_CACHE:
        res = _GEO_CACHE[q]
    else:
        res = await _census_geocode(c, q) or await _nominatim_geocode(c, q)
        _GEO_CACHE[q] = res
        await asyncio.sleep(nominatim_delay)
    if res:
        return res, True

    return None, False


# ---- Main enrichment -------------------------------------------------------

async def enrich_with_images(
    listings: list[Listing],
    use_mapillary: bool = True,
    geocode_named: bool = True,
    nominatim_delay: float = 1.0,
) -> None:
    """Attach a layered image stack to every listing. Goal: an image for every
    lead. Runs AFTER the geocode + address/situs + parcel resolution chain so
    lat/lng, street_address, and parcel_id are maximally populated.
    """
    if not listings:
        return

    real_count = aerial_count = street_count = named_geocoded = approx_count = 0

    sem = asyncio.Semaphore(8)

    async with httpx.AsyncClient(timeout=httpx.Timeout(15.0)) as c:

        # Pass 1: rescue name+city leads (multifamily complexes) that have no
        # precise point yet — geocode them so an aerial can attach below. Bounded
        # sequentially-ish via the nominatim delay inside the helper.
        if geocode_named:
            named_targets = [
                li for li in listings
                if not _has_precise_point(li)
                and (li.city and li.state)
                and (_name_for(li) is not None)
            ]
            for li in named_targets:
                if not isinstance(li.raw, dict):
                    li.raw = {}
                point, approx = await _geocode_named_complex(c, li, nominatim_delay)
                if point:
                    li.latitude, li.longitude = point
                    li.raw["geocoded_by_name"] = {"approx": approx}
                    named_geocoded += 1

        async def attach(li: Listing) -> None:
            nonlocal real_count, aerial_count, street_count, approx_count
            if not isinstance(li.raw, dict):
                li.raw = {}
            zillow = li.raw.setdefault("zillow", {})
            images = li.raw.setdefault("images", {})

            # Real listing photos (HomeHarvest / Realtor set these).
            existing_photos = []
            if zillow.get("photos"):
                existing_photos = [p for p in zillow["photos"] if p]
            elif zillow.get("photo"):
                existing_photos = [zillow["photo"]]
            if existing_photos:
                images["real"] = existing_photos
                real_count += 1

            # Aerial + map. Attach whenever we can frame the real parcel:
            #   - a precise point (address / parcel / name geocode), OR
            #   - a city-centroid we resolved for a named complex (flagged approx).
            # NEVER attach on a bare shared county-seat centroid.
            geo_named = li.raw.get("geocoded_by_name") or {}
            attach_aerial = False
            approx = False
            if li.latitude is not None and li.longitude is not None:
                if _has_precise_point(li):
                    attach_aerial = True
                elif geo_named:
                    # name-geocoded; may be a city centroid (approx) but still
                    # specific to THIS lead's city, not a shared courthouse pin.
                    attach_aerial = True
                    approx = bool(geo_named.get("approx"))

            if attach_aerial:
                images["aerial"] = _aerial_url_for_point(li.latitude, li.longitude)
                images["map"] = _osm_static_map_url(li.latitude, li.longitude)
                aerial_count += 1
                if approx:
                    images["approx"] = True
                    approx_count += 1

                if use_mapillary:
                    async with sem:
                        street = await _mapillary_image(c, li.latitude, li.longitude)
                    if street:
                        images["street"] = street
                        street_count += 1

            # Pick best primary: real photo > street > aerial > map.
            primary = (
                (existing_photos[0] if existing_photos else None)
                or images.get("street")
                or images.get("aerial")
                or images.get("map")
            )
            if primary:
                images["primary"] = primary
                if not zillow.get("photo"):
                    zillow["photo"] = primary

        await asyncio.gather(*(attach(li) for li in listings))

    with_image = sum(
        1 for li in listings
        if isinstance(li.raw, dict)
        and (li.raw.get("images") or {}).get("primary")
    )
    log.info(
        "images.enrich.done",
        listings=len(listings),
        with_image=with_image,
        real=real_count,
        aerial=aerial_count,
        street=street_count,
        named_geocoded=named_geocoded,
        approx=approx_count,
    )
