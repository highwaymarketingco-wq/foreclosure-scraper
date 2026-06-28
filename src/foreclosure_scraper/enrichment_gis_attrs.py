"""GIS-ATTRS BACKFILL — the big one.

Attacks the four lowest-coverage Listing fields at once (assessed/market VALUE,
owner_name, living_sqft, year_built, acreage, land_use) by hitting the county GIS
feature that already carries them.

Why a new module instead of just enrichment_arcgis.enrich():
  * enrich() resolves the parcel by an *address LIKE* query, so it can only touch
    the ~56% of leads that have a street_address. But 97% of leads have lat/lng.
  * enrich()/_apply_attrs writes value only to `tax_value` (never the first-class
    assessed_value / market_value fields the dashboard + grading read), and writes
    owner only to raw['gis']['owner'] (never the owner_name field). So even where
    it ran, assessed/market VALUE stayed ~6% and owner_name stayed 0%.
  * FIELD_ALIASES never covered the actual per-county field names. Live inspection
    of the SCDOT SC_Parcels layers shows each county uses different keys
    (ACTUALVAL / APPRAISAL / TotalMarket / MRKT_VALUE / Total_Appraised_Value ...),
    and OwnerAll is the near-universal owner field — none of which were mapped.

Strategy (per lead, free / pure-HTTP / no auth):
  1. Resolve the right layer: SC -> SCDOT SC_Parcels layer-per-county; NC -> the
     per-county FeatureServer already audited in enrichment_arcgis.NC_GIS.
  2. Query by POINT-IN-POLYGON using the lead's lat/lng (covers the 97%); if the
     lead has no lat/lng but has a parcel_id, fall back to a parcel-id where-query.
  3. Map the live attributes with an EXPANDED, value-aware field table and backfill
     assessed_value, market_value, owner_name, living_sqft, year_built, acreage,
     land_use onto the Listing (missing-only, never overwrites good data).
  4. Mirror owner into raw['gis']['owner'] (the dashboard already renders it) and
     stash the full matched attribute bag in raw['gis_attrs'] for provenance.

Wiring (orchestrator owns the single write; do NOT wire here): add
    from foreclosure_scraper.enrichment_gis_attrs import enrich_gis_attrs
    await _step("gis_attrs", enrich_gis_attrs(merged))
in scripts/merge_today_sources.py AFTER parcel_lookup / geocode (so lat/lng is
populated) and BEFORE enrich_sc_cama + the calc/grade pass (so the fresh
value/sqft feed grading).
"""
from __future__ import annotations

import asyncio
import os
import json
import re
from typing import Any

import httpx
import structlog

from .enrichment_arcgis import NC_GIS, SCDOT_BASE, SC_LAYER
from .http_client import client
from .models import Listing

log = structlog.get_logger()


# ---- Expanded, value-aware field map ------------------------------------------
# Built from LIVE inspection of every SCDOT county layer that carries leads plus
# the audited NC FeatureServers. Ordered by preference; first non-empty wins.

# Total MARKET / appraised value (the "what's it worth" number).
MARKET_FIELDS = (
    "TotalMarket", "Total_Mkt_", "Tot_Market", "TotalMkt", "MarketProp",
    "TAXMKTVAL", "FAIRMKTVAL", "MRKT_VALUE", "ActVal_Mkt", "APPRAISAL",
    "ACTUALVAL", "AppraisedValue", "TotalMarketValue", "Total_Appraised_Value",
    "AprTotVal", "TotalVal", "TotalValue", "Total_Val", "TotalAppraised",
    "TotApprais", "presentval", "parval", "AppraisalValue",
)
# ASSESSED value (the taxable / assessed figure, distinct from market).
ASSESSED_FIELDS = (
    "Total_Assessed_Value", "AssessedProp", "AssdVal", "AssessedValue",
    "TotAssess", "TotalAssessed", "ASSESSEDVAL", "AssessTot", "Assessed_Va",
)
# Component values to SUM when no total is published.
LAND_FIELDS = ("Market_Land", "LandMarket", "LandMktVal", "LANDVALUE",
               "LandValue", "Land_Val", "landval", "AprLandVal",
               "CurrentAppraisedLandValue", "Total_Appraised_Land_Value",
               "Mkt_Val_La")
IMPROVE_FIELDS = ("TotImpMktVal", "MarketImprv", "TOTBDGVAL", "BLDG_VAL",
                  "ImpValue", "improvval", "AprBldgVal",
                  "CurrentAppraisedBuildingValue",
                  "Total_Appraised_Building_Value", "Mkt_Val_St")
ASSESSED_LAND_FIELDS = ("CurrentAssessedLandValue", "Total_Assessed_Land_Value",
                        "AssdLandVal")
ASSESSED_IMPROVE_FIELDS = ("CurrentAssessedBuildingValue",
                           "Total_Assessed_Building_Value", "AssdImpVal")

# Owner — OwnerAll is the near-universal SCDOT field; the rest cover the gaps.
OWNER_FIELDS = (
    "OwnerAll", "OwnerName", "OWNER", "OWNERNAME", "Owner_Name", "OwnerName1",
    "Owner1", "Owner", "Formatted_Owner_1", "NAME1", "Name1", "OWNAM1",
    "full_owner_name", "owner", "PROPERTY_OWNER", "OWNER_NAME",
)
# Heated / finished LIVING sqft only. Garage/basement/attic sqft excluded.
LIVING_SQFT_FIELDS = (
    "Heated_Sqf", "HEATED_SQ_", "LivingArea", "SQFEET", "SqFt_Total",
    "TotLiving", "TotalLiving", "HeatedSqFt", "BLDGSQFT", "Total_Sqft",
)
YEAR_FIELDS = ("YearBuilt", "YEAR_BUILT", "year_built", "taxYearBui", "YEARBLT",
               "AYB", "structyear", "EFFYR", "ActualYear")
ACRE_FIELDS = ("Acreage", "ACREAGE", "ACRES", "Acres", "CalcAcres", "TACRES",
               "GIS_ACRES", "gisacres", "DEEDACREAGE", "DEEDED_ACRES",
               "LegalAc", "Acres_Calc", "ACRE")
LANDUSE_FIELDS = ("LandUse", "LANDUSE", "Land_Use", "LandUseDesc", "PROPTYPE",
                  "PropertyType", "ZONINGDESC", "use_desc", "USE_DESC",
                  "PropClass", "PROP_CLASS", "NLUCDESC")


def _norm(attrs: dict[str, Any]) -> dict[str, Any]:
    return {k.lower(): v for k, v in attrs.items() if not k.startswith("_")}


def _pick(norm: dict[str, Any], fields: tuple[str, ...]) -> Any:
    for f in fields:
        v = norm.get(f.lower())
        if v not in (None, "", " ", 0, "0", "<Null>", "NULL"):
            return v
    return None


def _num(v: Any) -> float | None:
    """Parse a money/number value, rejecting denormalized-float junk and bad ranges.

    Some SCDOT layers return uninitialized doubles like 8.487983164e-314 for
    blank numeric cells; those must never become a sqft/value.
    """
    if v is None:
        return None
    try:
        f = float(str(v).replace(",", "").replace("$", "").strip())
    except (ValueError, TypeError):
        return None
    if f != f:  # NaN
        return None
    if 0 < abs(f) < 1e-6:  # denormalized junk
        return None
    return f


def _sum_components(norm, total_fields, land_fields, imp_fields):
    """Total field if present, else land+improvement sum (>0)."""
    tv = _num(_pick(norm, total_fields))
    if tv and tv > 0:
        return tv
    land = _num(_pick(norm, land_fields)) or 0.0
    imp = _num(_pick(norm, imp_fields)) or 0.0
    s = land + imp
    return s if s > 0 else None


# ---- Layer resolution + query --------------------------------------------------

def _resolve_layer(li: Listing) -> str | None:
    """Return the /query base URL for this lead's county GIS, or None."""
    if not (li.county and li.state):
        return None
    county = li.county.replace(" County", "").strip()
    for sfx in (", NC", ", SC", ",NC", ",SC"):
        if county.upper().endswith(sfx):
            county = county[: -len(sfx)].strip()
    county = county.split(",")[0].strip().title()
    if li.state == "SC":
        layer = SC_LAYER.get(county)
        return f"{SCDOT_BASE}/{layer}/query" if layer else None
    if li.state == "NC":
        cfg = NC_GIS.get(county)
        return cfg["url"] if cfg else None
    return None


async def _query_point(c: httpx.AsyncClient, base: str, lat: float, lng: float) -> dict | None:
    """Point-in-polygon query — the parcel whose boundary contains the lead's coord."""
    geom = json.dumps({"x": lng, "y": lat, "spatialReference": {"wkid": 4326}})
    params = {
        "geometry": geom, "geometryType": "esriGeometryPoint", "inSR": "4326",
        "spatialRel": "esriSpatialRelIntersects", "outFields": "*",
        "returnGeometry": "false", "resultRecordCount": "1", "f": "json",
    }
    try:
        r = await c.get(base, params=params, timeout=20.0)
        if r.status_code != 200:
            return None
        data = r.json()
        if "error" in data:
            return None
        feats = data.get("features") or []
        if feats and feats[0].get("attributes"):
            return dict(feats[0]["attributes"])
    except (httpx.HTTPError, ValueError):
        return None
    return None


_PARCEL_FIELDS = ("PIN", "TMS", "REID", "PARCELNUMBER", "TAXPIN", "PARNO",
                  "PARID", "MAPNUMBER", "pid", "parno", "PARCEL", "PARCEL_ID")
_LAYER_FIELDS_CACHE: dict[str, list[str]] = {}


async def _layer_fields(c: httpx.AsyncClient, base: str) -> list[str]:
    if base in _LAYER_FIELDS_CACHE:
        return _LAYER_FIELDS_CACHE[base]
    try:
        r = await c.get(base.rsplit("/query", 1)[0], params={"f": "json"}, timeout=15.0)
        fields = [f["name"] for f in r.json().get("fields", []) if "name" in f]
    except (httpx.HTTPError, ValueError):
        fields = []
    _LAYER_FIELDS_CACHE[base] = fields
    return fields


async def _query_parcel(c: httpx.AsyncClient, base: str, parcel: str) -> dict | None:
    """Fallback when the lead has no lat/lng: match on a parcel-id-style field."""
    fields = await _layer_fields(c, base)
    flow = {f.lower(): f for f in fields}
    cands = [flow[p.lower()] for p in _PARCEL_FIELDS if p.lower() in flow]
    pv = parcel.strip().replace("'", "''")
    for fld in cands:
        try:
            r = await c.get(base, params={
                "where": f"{fld}='{pv}'", "outFields": "*",
                "returnGeometry": "false", "resultRecordCount": "1", "f": "json",
            }, timeout=15.0)
            if r.status_code != 200:
                continue
            data = r.json()
            feats = data.get("features") or []
            if feats and feats[0].get("attributes"):
                return dict(feats[0]["attributes"])
        except (httpx.HTTPError, ValueError):
            continue
    return None


# ---- Apply ---------------------------------------------------------------------

def apply_gis_attrs(li: Listing, attrs: dict[str, Any]) -> dict[str, int]:
    """Backfill value/owner/specs from a matched GIS feature. Missing-only.
    Returns per-field fill flags (1 = newly populated this call)."""
    norm = _norm(attrs)
    flags = {k: 0 for k in ("market_value", "assessed_value", "owner_name",
                            "living_sqft", "year_built", "acreage", "land_use")}

    if not li.market_value:
        mv = _sum_components(norm, MARKET_FIELDS, LAND_FIELDS, IMPROVE_FIELDS)
        if mv and 1000 <= mv <= 1e9:
            li.market_value = mv
            flags["market_value"] = 1

    if not li.assessed_value:
        av = _sum_components(norm, ASSESSED_FIELDS, ASSESSED_LAND_FIELDS,
                             ASSESSED_IMPROVE_FIELDS)
        if av and 100 <= av <= 1e9:
            li.assessed_value = av
            flags["assessed_value"] = 1

    if not li.owner_name:
        ow = _pick(norm, OWNER_FIELDS)
        if ow:
            s = re.sub(r"\s+", " ", str(ow).strip())
            if len(s) >= 3 and not s.replace(" ", "").isdigit():
                li.owner_name = s
                flags["owner_name"] = 1

    if not li.living_sqft:
        sq = _num(_pick(norm, LIVING_SQFT_FIELDS))
        if sq and 100 <= sq <= 100000:
            li.living_sqft = sq
            flags["living_sqft"] = 1

    if not li.year_built:
        yb = _pick(norm, YEAR_FIELDS)
        if yb is not None:
            try:
                y = int(str(yb)[:4])
                if 1800 < y < 2030:
                    li.year_built = y
                    flags["year_built"] = 1
            except (ValueError, TypeError):
                pass

    if not li.acreage:
        ac = _num(_pick(norm, ACRE_FIELDS))
        if ac and 0 < ac <= 1e6:
            li.acreage = ac
            flags["acreage"] = 1

    if not li.land_use:
        lu = _pick(norm, LANDUSE_FIELDS)
        if lu:
            s = str(lu).strip()
            if s and not s.isdigit():
                li.land_use = s.title() if s.isupper() else s
                flags["land_use"] = 1

    # Mirror owner into raw['gis']['owner'] (dashboard renders this) + stash attrs.
    if isinstance(li.raw, dict):
        if li.owner_name:
            gis = li.raw.setdefault("gis", {})
            gis.setdefault("owner", li.owner_name)
            gis.setdefault("owner_match_strategy", "gis_attrs_pip")
        li.raw["gis_attrs"] = {
            "matched": True,
            "market_value": li.market_value,
            "assessed_value": li.assessed_value,
            "owner_name": li.owner_name,
            "living_sqft": li.living_sqft,
            "year_built": li.year_built,
            "acreage": li.acreage,
            "land_use": li.land_use,
        }
        # Stash the WHOLE matched attribute bag (outFields=* already fetched, zero
        # new HTTP) so downstream enrichers — e.g. enrichment_gis_derived — can mine
        # per-county fields (last sale price/date, deed book/page, tax-paid date)
        # that this generic mapper doesn't promote to first-class Listing fields.
        li.raw["gis_attrs_full"] = attrs
    return flags


# ---- Public API ----------------------------------------------------------------

async def enrich_gis_attrs(listings: list[Listing], concurrency: int = 8) -> dict:
    """Backfill GIS attributes for every lead with lat/lng (or parcel_id) in a
    supported SC/NC county. Returns a stats dict for the orchestrator log."""
    _force = bool(os.environ.get("FORECLOSURE_GIS_FORCE"))
    sem = asyncio.Semaphore(concurrency)
    stats = {"queried": 0, "matched": 0, "skipped_done": 0, "filled_market": 0, "filled_assessed": 0,
             "filled_owner": 0, "filled_sqft": 0, "filled_year": 0,
             "filled_acre": 0, "filled_landuse": 0}

    async def one(c: httpx.AsyncClient, li: Listing) -> None:
        # Idempotent skip — the per-lead county GIS query is the dominant cost of a full
        # re-enrich (turned an overnight regenerate into a multi-hour slog). Skip when:
        #   (a) the lead already has the CORE attrs (value + owner + sqft); re-querying
        #       just to maybe fill minor fields (acreage/land_use/year) isn't worth a call;
        #   (b) a prior run already ATTEMPTED this lead (same lat/lng -> same GIS result),
        #       marked raw['gis']['queried']. FORECLOSURE_GIS_FORCE=1 re-attempts all.
        raw = li.raw if isinstance(li.raw, dict) else {}
        if (li.assessed_value or li.market_value) and li.owner_name and li.living_sqft:
            stats["skipped_done"] += 1
            return
        if not _force and (raw.get("gis") or {}).get("queried"):
            stats["skipped_done"] += 1
            return
        base = _resolve_layer(li)
        if not base:
            return
        async with sem:
            attrs = None
            if li.latitude and li.longitude:
                try:
                    attrs = await _query_point(c, base, float(li.latitude), float(li.longitude))
                except (ValueError, TypeError):
                    attrs = None
            if attrs is None and li.parcel_id:
                attrs = await _query_parcel(c, base, li.parcel_id)
            stats["queried"] += 1
            # Mark attempted so future re-enriches skip this lead (idempotent).
            if not isinstance(li.raw, dict):
                li.raw = {}
            li.raw.setdefault("gis", {})["queried"] = True
            if not attrs:
                return
            stats["matched"] += 1
            flags = apply_gis_attrs(li, attrs)
            stats["filled_market"] += flags["market_value"]
            stats["filled_assessed"] += flags["assessed_value"]
            stats["filled_owner"] += flags["owner_name"]
            stats["filled_sqft"] += flags["living_sqft"]
            stats["filled_year"] += flags["year_built"]
            stats["filled_acre"] += flags["acreage"]
            stats["filled_landuse"] += flags["land_use"]

    async with client(timeout=20.0) as c:
        await asyncio.gather(*(one(c, li) for li in listings))

    log.info("enrichment.gis_attrs.done", **stats)
    return stats
