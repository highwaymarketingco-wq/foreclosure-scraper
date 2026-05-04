"""Bankruptcy property lookup — for every CourtListener bankruptcy listing,
search the county GIS by debtor name across all counties in the appropriate
court's footprint to recover address + property specs.

Bankruptcy dockets do NOT include the debtor's property address (only
debtor name + chapter). To get property info we need to either:
  - Pay PACER to download Schedule A (Real Property) — paid
  - Cross-reference the debtor name against county tax assessor / GIS
    owner records — FREE, what we do here

Strategy:
  - NCWB (Western District NC) → query our 14 NC counties' GIS owner fields
  - NCEB (Eastern District NC) → out of our footprint, skip
  - SCB (SC) → query our 7 SC counties

For each match, populate:
  - street_address, city, zip_code, latitude, longitude
  - parcel_id, year_built, bedrooms, bathrooms, living_sqft, tax_value
  - acreage, zoning
  - property_kind (inferred from zoning/structure)
  - county (which we discover via the match)

Once these are populated, the bankruptcy listing flows through the normal
photo/comp/vision/calc pipeline like any other property listing.
"""
from __future__ import annotations

import asyncio
import re
from typing import Any

import httpx
import structlog

from .enrichment_address_backfill import (
    _OWNER_FIELD_CANDIDATES,
    _defendant_search_terms,
    _detect_owner_field,
    _populate_from_attrs,
    _query_by_owner,
)
from .enrichment_arcgis import (
    FIELD_ALIASES,
    NC_GIS,
    SC_LAYER,
    SCDOT_BASE,
    _apply_attrs,
    _pick,
)
from .http_client import client
from .models import Listing, PropertyKind

log = structlog.get_logger()


# Court → list of counties to query. NCEB is NC Eastern District (Raleigh +
# eastern coast); not our footprint, skip. SC has only one bankruptcy
# district covering all counties.
COURT_FOOTPRINT_COUNTIES: dict[str, list[tuple[str, str]]] = {
    "ncwb": [("NC", c) for c in NC_GIS.keys()],
    "nceb": [],  # out of footprint
    "scb": [("SC", c) for c in SC_LAYER.keys() if c in {
        "Spartanburg", "Anderson", "Pickens", "Oconee",
        "Cherokee", "Union", "Laurens",
    }],
}


def _gis_base(state: str, county: str) -> str | None:
    """Return the ArcGIS query base URL for a (state, county) pair, or None."""
    if state == "NC":
        cfg = NC_GIS.get(county)
        return cfg.get("url") if cfg else None
    if state == "SC":
        layer = SC_LAYER.get(county)
        return f"{SCDOT_BASE}/{layer}/query" if layer else None
    return None


def _infer_property_kind(attrs: dict[str, Any]) -> PropertyKind | None:
    """Best-effort property_kind inference from GIS attributes."""
    # Check zoning
    z = (_pick(attrs, FIELD_ALIASES["zoning"]) or "").upper()
    living = _pick(attrs, FIELD_ALIASES["living_sqft"])
    try:
        living_f = float(living) if living else 0.0
    except (TypeError, ValueError):
        living_f = 0.0
    acreage = _pick(attrs, FIELD_ALIASES["acreage"])
    try:
        acres_f = float(acreage) if acreage else 0.0
    except (TypeError, ValueError):
        acres_f = 0.0

    # Land use / property class fields (not in standard aliases — try common names)
    use = ""
    for k in ("LAND_USE", "LandUse", "USE_DESC", "PROP_CLASS", "PROPCLASS",
              "PROPERTY_CLASS", "PROPERTY_TYPE", "PROPTYPE", "BLDG_USE"):
        if k.lower() in {kk.lower() for kk in attrs.keys()}:
            for kk, vv in attrs.items():
                if kk.lower() == k.lower() and vv:
                    use = str(vv).upper()
                    break
            if use:
                break

    blob = f"{z} {use}"

    # Ordering matters — most specific first
    if "MULTI" in blob or "APARTMENT" in blob or "DUPLEX" in blob or "TRIPLEX" in blob:
        return PropertyKind.MULTI_FAMILY
    if "CONDO" in blob:
        return PropertyKind.CONDO
    if "TOWNHOUSE" in blob or "TOWNHOME" in blob:
        return PropertyKind.TOWNHOUSE
    if "MANUFACTURED" in blob or "MOBILE" in blob:
        return PropertyKind.MANUFACTURED
    if "COMMERCIAL" in blob or "INDUSTRIAL" in blob or "RETAIL" in blob or "OFFICE" in blob:
        return PropertyKind.COMMERCIAL

    # Pure land: zero/low building sqft + meaningful acreage
    if living_f < 100 and acres_f >= 0.05:
        return PropertyKind.LAND
    # Standard SFR
    if living_f >= 400 and ("RESID" in blob or "R-" in blob or "R1" in blob or "R2" in blob or not blob):
        return PropertyKind.SINGLE_FAMILY
    if living_f >= 400:
        return PropertyKind.SINGLE_FAMILY
    return None


async def _try_county(
    c: httpx.AsyncClient,
    state: str,
    county: str,
    defendant: str,
    owner_field_cache: dict[str, str | None],
) -> tuple[dict[str, Any], int] | None:
    """Try to find a single confident match for `defendant` in (state, county).
    Returns (attrs, n_results) on hit, None otherwise.
    """
    base = _gis_base(state, county)
    if not base:
        return None
    if base not in owner_field_cache:
        owner_field_cache[base] = await _detect_owner_field(c, base)
    owner_field = owner_field_cache[base]
    if not owner_field:
        return None
    results = await _query_by_owner(c, base, owner_field, defendant)
    if not results:
        return None
    if len(results) == 1:
        return results[0], 1
    # Multiple results — prefer one whose owner contains ALL distinctive tokens
    d_tokens = {
        t for t in re.split(r"\W+", defendant.lower())
        if len(t) >= 3 and t not in {
            "llc", "inc", "corp", "corporation", "company", "co", "ltd", "lp",
            "llp", "trust", "trustee", "estate", "of", "the", "and",
        }
    }
    best = None
    best_score = 0
    for r in results:
        owner = (_pick(r, FIELD_ALIASES["owner_name"]) or "").lower()
        score = sum(1 for t in d_tokens if t in owner)
        if score > best_score:
            best_score = score
            best = r
    if best and best_score == len(d_tokens) and len(d_tokens) >= 2:
        return best, len(results)
    return None


async def enrich_bankruptcy_property(
    listings: list[Listing], concurrency: int = 8
) -> None:
    """For each CourtListener bankruptcy listing, scan all counties in the
    BK court's footprint via owner-name search. Populate full property
    info on confident match.
    """
    targets = [
        li
        for li in listings
        if li.source == "national.courtlistener_bankruptcy"
        and li.defendant
        and not li.street_address
    ]
    if not targets:
        log.info("bk_property.no_targets")
        return

    log.info("bk_property.start", target_count=len(targets))

    sem = asyncio.Semaphore(concurrency)
    counts = {
        "queried": 0,
        "matched": 0,
        "no_match": 0,
        "fields_filled": 0,
        "kind_inferred": 0,
    }
    owner_field_cache: dict[str, str | None] = {}

    async def one(c: httpx.AsyncClient, li: Listing) -> None:
        court = (li.raw or {}).get("courtlistener", {}).get("court", "").lower()
        counties = COURT_FOOTPRINT_COUNTIES.get(court, [])
        if not counties:
            return
        async with sem:
            counts["queried"] += 1
            for state, county in counties:
                hit = await _try_county(c, state, county, li.defendant, owner_field_cache)
                if not hit:
                    continue
                attrs, n_results = hit
                # Populate basic address/coords/owner
                filled = _populate_from_attrs(li, attrs)
                # Also populate property specs (sqft/beds/baths/year/parcel/tax_value)
                # via the standard apply-attrs from enrichment_arcgis
                attrs["_match_confident"] = True  # we already filtered for confidence
                filled += _apply_attrs(li, attrs)
                # Set county since we discovered it
                if not li.county:
                    li.county = county
                # Infer property kind
                kind = _infer_property_kind(attrs)
                if kind and (not li.property_kind or li.property_kind == PropertyKind.UNKNOWN):
                    li.property_kind = kind
                    counts["kind_inferred"] += 1
                counts["matched"] += 1
                counts["fields_filled"] += filled
                # Stop on first successful county
                return
            counts["no_match"] += 1

    async with client(timeout=20.0) as c:
        await asyncio.gather(*(one(c, li) for li in targets))

    log.info("bk_property.done", **counts)
