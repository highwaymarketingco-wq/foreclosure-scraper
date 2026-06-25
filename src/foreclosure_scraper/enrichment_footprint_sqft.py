"""Estimate living sqft for SC leads whose assessor withholds it (Spartanburg
LivingArea is 0% populated), so the $/sqft ARV path can run instead of falling
back to the conservative appraised-value anchor.

heated_est = footprint_ground_floor_area x StoryHeight - unheated_haircut
  - footprint area: Microsoft US Building Footprints (sc_building_footprints), ~2019
  - StoryHeight: Spartanburg Assessor CSV (raw['cama']['story_height'])

ALWAYS sets li.living_sqft_estimated = True so calc caps confidence to MEDIUM and
labels the ARV as built on an ESTIMATE. Only fills living_sqft when it is missing,
so a true MLS/HomeHarvest sqft is never overwritten. Runs after enrich_sc_cama
(needs story_height) and before the calc loop.
"""
from __future__ import annotations

import urllib.parse
import urllib.request
import ssl

import structlog

from .models import Listing
from . import sc_building_footprints as fp
from .enrichment_arcgis import SCDOT_BASE, SC_LAYER
from .enrichment_geocode import COUNTY_SEAT_CENTROIDS

log = structlog.get_logger()

_CTX = ssl._create_unverified_context()
_UNHEATED_HAIRCUT = 0.10   # garage/porch share of the ground-floor footprint
_BANDS = ((1200, "<1200"), (1800, "1200-1799"), (2500, "1800-2499"))
_MAX_HEATED = 8000         # implausibly large for a single dwelling -> bad footprint
_CENTROID_TOL = 0.001      # deg (~110m): lat/lng this close to a county seat is a
                           # Tier-4 geocode placeholder, not a real situs


def _is_county_centroid(li: Listing) -> bool:
    """True when the lead's lat/lng is (essentially) a county-seat centroid, i.e.
    a Tier-4 geocode fallback rather than a real situs. Point-based footprint
    attribution on such a coord grabs whatever building sits near the county seat
    and poisons living_sqft, so we skip footprint lookup for these."""
    if li.latitude is None or li.longitude is None:
        return False
    seat = COUNTY_SEAT_CENTROIDS.get((li.state, li.county))
    if not seat:
        return False
    try:
        return (abs(float(li.latitude) - seat[0]) <= _CENTROID_TOL
                and abs(float(li.longitude) - seat[1]) <= _CENTROID_TOL)
    except (TypeError, ValueError):
        return False


def _band(sqft: float) -> str:
    for hi, label in _BANDS:
        if sqft < hi:
            return label
    return "2500+"


def _scdot_parcel_ring(state: str, county: str, parcel_id: str) -> list | None:
    """Fetch the SCDOT parcel polygon (largest ring, lon/lat) for a TAXPIN."""
    lid = SC_LAYER.get(county)
    if not lid or not parcel_id:
        return None
    q = {"where": f"TAXPIN='{parcel_id}'", "outFields": "TAXPIN",
         "returnGeometry": "true", "outSR": "4326", "f": "json"}
    url = f"{SCDOT_BASE}/{lid}/query?" + urllib.parse.urlencode(q)
    try:
        import json
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        j = json.loads(urllib.request.urlopen(req, context=_CTX, timeout=25).read())
        feats = j.get("features") or []
        rings = (feats[0].get("geometry") or {}).get("rings") if feats else None
        return max(rings, key=len) if rings else None
    except Exception:
        return None


def enrich_footprint_sqft(listings: list[Listing]) -> dict:
    counties = {(s, c) for (s, c) in fp.COUNTY_BBOX if fp.has_data(s, c)}
    if not counties:
        return {"estimated": 0}
    centroid_cache: dict = {}
    estimated = no_fp = 0
    for li in listings:
        if (li.state, li.county) not in counties:
            continue
        if li.living_sqft and li.living_sqft > 0:
            continue  # already have a real (or prior) sqft
        if _is_county_centroid(li):
            # lat/lng is a county-seat placeholder, not a real situs — attributing
            # a footprint here grabs an unrelated building and poisons living_sqft.
            no_fp += 1
            continue
        raw = li.raw if isinstance(li.raw, dict) else {}
        story = (raw.get("cama") or {}).get("story_height") or 1.0
        try:
            story = float(story)
        except (TypeError, ValueError):
            story = 1.0
        story = max(1.0, min(story, 3.0))
        # Best attribution: the largest footprint INSIDE the parcel polygon (the
        # main dwelling). Fall back to the footprint at/nearest a point only when
        # the parcel polygon is unavailable.
        hit = None
        key = (li.state, li.county, li.parcel_id)
        if key not in centroid_cache:
            centroid_cache[key] = _scdot_parcel_ring(li.state, li.county, li.parcel_id or "")
        ring = centroid_cache[key]
        if ring:
            hit = fp.largest_in_polygon(li.state, li.county, ring)
        if not hit:
            if li.longitude and li.latitude:
                pt = (li.longitude, li.latitude)
            elif ring:
                pt = (sum(p[0] for p in ring) / len(ring), sum(p[1] for p in ring) / len(ring))
            else:
                pt = None
            if pt:
                hit = fp.lookup_area(li.state, li.county, pt[0], pt[1])
        if not hit:
            no_fp += 1
            continue
        area, match = hit
        heated = round(area * story - area * _UNHEATED_HAIRCUT, -1)
        if heated < 320 or heated > _MAX_HEATED:  # implausibly small/large for a dwelling
            no_fp += 1
            continue
        li.living_sqft = heated
        li.living_sqft_estimated = True
        raw["footprint"] = {
            "footprint_sqft": area, "story_height": story, "est_living_sqft": heated,
            "band": _band(heated), "match": match, "haircut": _UNHEATED_HAIRCUT,
            "source": "ms_building_footprints", "capture": "~2019", "estimated": True,
        }
        li.raw = raw
        estimated += 1
    log.info("footprint_sqft.enriched", estimated=estimated, no_footprint=no_fp)
    return {"estimated": estimated, "no_footprint": no_fp}
