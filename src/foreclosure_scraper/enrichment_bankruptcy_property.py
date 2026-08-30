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
import time
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
    "nceb": [],  # statewide OneMap query handles these
    "ncmb": [],  # statewide OneMap query handles these
    "scb": [("SC", c) for c in SC_LAYER.keys() if c in {
        "Spartanburg", "Anderson", "Pickens", "Oconee",
        "Cherokee", "Union", "Laurens",
    }],
}


# NC OneMap statewide parcel service — one query covers all 100 NC counties
# with a CONSISTENT value field (parval) that many per-county layers lack. We
# search it by owner name for NC bankruptcy debtors, filtered to our footprint,
# so a debtor's NC property + its assessed value get recovered even when the
# per-county layer has no value field. (SC has no statewide equivalent.)
NC_ONEMAP_QUERY = (
    "https://services.nconemap.gov/secure/rest/services/"
    "NC1Map_Parcels/FeatureServer/1/query"
)
# Filter OneMap matches to the canonical IN-SCOPE NC counties (the 11), NOT
# NC_GIS.keys() — that set also carries denied Mecklenburg/Madison (used for
# other cross-refs), which the scope re-pass would just drop anyway.
from .config import NC_COUNTIES as _NC_COUNTIES  # noqa: E402
_ALLOWED_NC_UPPER = {c.name.upper() for c in _NC_COUNTIES}
_NAME_STOP = {
    "llc", "inc", "corp", "corporation", "company", "co", "ltd", "lp",
    "llp", "trust", "trustee", "estate", "of", "the", "and",
}


def _distinctive_tokens(name: str) -> set[str]:
    return {
        t for t in re.split(r"\W+", (name or "").lower())
        if len(t) >= 3 and t not in _NAME_STOP
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
        return PropertyKind.MOBILE
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


async def _try_nc_onemap(
    c: httpx.AsyncClient, defendant: str
) -> dict[str, Any] | None:
    """Search NC OneMap statewide by owner name, keep only matches inside our
    NC footprint, and return a single confident match (with parval value)."""
    results = await _query_by_owner(c, NC_ONEMAP_QUERY, "ownname", defendant)
    if not results:
        return None
    in_fp = [
        r for r in results
        if str(r.get("cntyname") or "").strip().upper() in _ALLOWED_NC_UPPER
    ]
    if not in_fp:
        return None
    if len(in_fp) == 1:
        return in_fp[0]
    # Multiple — require the owner to contain ALL distinctive debtor tokens
    d_tokens = _distinctive_tokens(defendant)
    best, best_score = None, 0
    for r in in_fp:
        owner = (str(r.get("ownname") or "") + " " + str(r.get("ownname2") or "")).lower()
        score = sum(1 for t in d_tokens if t in owner)
        if score > best_score:
            best_score, best = score, r
    if best and best_score == len(d_tokens) and len(d_tokens) >= 2:
        return best
    return None


def _apply_match(li: Listing, attrs: dict[str, Any], county_name: str | None,
                 counts: dict[str, int]) -> None:
    """Populate a bankruptcy listing from a confident GIS/OneMap match."""
    filled = _populate_from_attrs(li, attrs)
    attrs["_match_confident"] = True  # already confidence-gated by the caller
    filled += _apply_attrs(li, attrs)
    if county_name and not li.county:
        li.county = county_name.title() if county_name.isupper() else county_name
    kind = _infer_property_kind(attrs)
    if kind and (not li.property_kind or li.property_kind == PropertyKind.UNKNOWN):
        li.property_kind = kind
        counts["kind_inferred"] += 1
    counts["matched"] += 1
    counts["fields_filled"] += filled


async def enrich_bankruptcy_property(
    listings: list[Listing], concurrency: int = 8
) -> None:
    """For each CourtListener bankruptcy listing, scan all counties in the
    BK court's footprint via owner-name search. Populate full property
    info on confident match.
    """
    # Pre-populate defendant from raw.courtlistener if missing
    for li in listings:
        if not li.defendant:
            cl = (li.raw or {}).get("courtlistener", {})
            name = cl.get("case_name") or ""
            if not name and cl.get("parties"):
                name = cl["parties"][0] if isinstance(cl["parties"], list) else str(cl["parties"])
            if name:
                li.defendant = name
        if not li.case_number:
            cl = (li.raw or {}).get("courtlistener", {})
            li.case_number = cl.get("docket_number") or li.case_number
    targets = [
        li
        for li in listings
        if "courtlistener" in (li.source or "").lower()
        and "bankrupt" in (li.source or "").lower()
        and li.defendant
        and not li.street_address
    ]
    if not targets:
        log.info("bk_property.no_targets")
        return

    log.info("bk_property.start", target_count=len(targets))

    sem = asyncio.Semaphore(concurrency)
    _BUDGET_S = 1800  # 30-min cap
    _start = time.monotonic()
    counts = {
        "queried": 0,
        "matched": 0,
        "no_match": 0,
        "fields_filled": 0,
        "kind_inferred": 0,
        "budget_skip": 0,
    }
    owner_field_cache: dict[str, str | None] = {}

    async def one(c: httpx.AsyncClient, li: Listing) -> None:
        court = (li.raw or {}).get("courtlistener", {}).get("court", "").lower()
        counties = COURT_FOOTPRINT_COUNTIES.get(court, [])
        if not counties and court not in ("nceb", "ncmb", "ncwb", "scb"):
            return
        async with sem:
            if (time.monotonic() - _start) > _BUDGET_S:
                counts["budget_skip"] += 1
                return
            counts["queried"] += 1
            # NC: one statewide OneMap query (covers all NC counties
            # AND carries parval value) before the per-county layers. This
            # recovers value the per-county NC layers often lack.
            if court in ("ncwb", "nceb", "ncmb"):
                om = await _try_nc_onemap(c, li.defendant)
                if om is not None:
                    _apply_match(li, om, str(om.get("cntyname") or "") or None, counts)
                    counts["matched_onemap"] = counts.get("matched_onemap", 0) + 1
                    return
            for state, county in counties:
                hit = await _try_county(c, state, county, li.defendant, owner_field_cache)
                if not hit:
                    continue
                attrs, _n = hit
                _apply_match(li, attrs, county, counts)
                return
            counts["no_match"] += 1

    async with client(timeout=20.0) as c:
        await asyncio.gather(*(one(c, li) for li in targets))

    elapsed = time.monotonic() - _start
    if counts["budget_skip"] > 0:
        log.warning("bk_property.time_capped", budget_s=_BUDGET_S, elapsed_s=round(elapsed),
                     skipped=counts["budget_skip"], **{k: v for k, v in counts.items() if k != "budget_skip"})
    log.info("bk_property.done", **counts)
