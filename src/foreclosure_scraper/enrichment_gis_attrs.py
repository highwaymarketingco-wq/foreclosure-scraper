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

from pathlib import Path

from .enrichment_arcgis import NC_GIS, SCDOT_BASE, SC_LAYER, SC_GIS, host_walled
from .http_client import client

# ---------------------------------------------------------------------------
# Persistent parcel/point -> GIS-attrs cache (Phase-2 hang/volume fix)
# ---------------------------------------------------------------------------
# A fresh scrape produces leads with no markers, so gis_attrs would re-query EVERY
# parcel over the network — thousands of gov-GIS calls, the exact load that stalls on
# a flaky connection. This disk cache keys resolved attrs by (state, county, parcel or
# rounded lat/lng) and persists across runs, so only NET-NEW parcels hit the network.
# Cuts per-run GIS volume ~10x. FORECLOSURE_GIS_CACHE=0 disables; FORECLOSURE_GIS_FORCE
# still re-queries (and refreshes the cache) as before.
_CACHE_PATH = Path(__file__).resolve().parent.parent.parent / ".cache" / "gis_attrs_cache.json"
_ATTR_CACHE: dict[str, Any] = {}
_CACHE_LOADED = False
_CACHE_ON = os.environ.get("FORECLOSURE_GIS_CACHE", "1") != "0"


def _norm_parcel(p: str) -> str:
    return re.sub(r"[^0-9A-Za-z]", "", (p or "")).upper()


def _parcel_variants(parcel: str) -> list[str]:
    """Parcel-id spellings to try against a GIS id field, best-first.

    County GIS layers store parcels inconsistently: some keep the dashed form
    the tax PDF uses (1728-00-87-8115), others store it clean (172800878115),
    and some carry a `.NNN` sub-parcel suffix (Georgetown TMS). These layers
    match on an exact `=` (no LIKE), so a single raw spelling silently returns
    0 rows against a layer that stores a different form. We try each spelling
    until one hits. Raw form is first so existing matches are unaffected.
    """
    p = (parcel or "").strip()
    if not p:
        return []
    out: list[str] = []

    def _add(x: str) -> None:
        x = (x or "").strip()
        if x and x not in out:
            out.append(x)

    _add(p)                         # raw, e.g. dashed-store layers
    _add(_norm_parcel(p))           # clean alnum, e.g. `parno` / `PIN`
    if "." in p:                    # drop a .NNN sub-parcel suffix
        base = p.split(".", 1)[0]
        _add(base)
        _add(_norm_parcel(base))
    return out


def _cache_key(li) -> "str | None":
    st = (li.state or "").upper()
    cty = (li.county or "").replace(" County", "").strip().title()
    if (li.parcel_id or "").strip():
        return f"{st}|{cty}|P:{_norm_parcel(li.parcel_id)}"
    if li.latitude and li.longitude:
        return f"{st}|{cty}|G:{round(float(li.latitude), 5)},{round(float(li.longitude), 5)}"
    return None


def _load_cache() -> None:
    global _CACHE_LOADED
    if _CACHE_LOADED or not _CACHE_ON:
        return
    _CACHE_LOADED = True
    try:
        if _CACHE_PATH.exists():
            _ATTR_CACHE.update(json.loads(_CACHE_PATH.read_text()))
    except Exception:  # noqa: BLE001
        pass


def _save_cache() -> None:
    if not _CACHE_ON:
        return
    try:
        _CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
        _CACHE_PATH.write_text(json.dumps(_ATTR_CACHE))
    except Exception:  # noqa: BLE001
        pass
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
# Situs / physical address — the street address of the property itself.
ADDRESS_FIELDS = (
    "StreetAddress", "situs", "siteadd", "Physical_Address", "LOCATION_ADDR",
    "LOCATE_ADDRESS", "Property_Address", "ADDRESS", "SiteAddr", "SITUS",
    "address", "phys_addr", "PHYS_ADDR", "propertyaddress", "PropAddr",
    "PropertyAddress", "PHYSICALADDRESS", "physicaladdress",
    "ADDRLINE1", "addrline1", "SITE_ADDR", "site_address",
)


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
        # Prefer county-native endpoints (SC_GIS) — SCDOT SC_LAYER went
        # token-walled 2026-08-12 (HTTP 200 + {"error":{"code":499}}).
        # SCDOT is kept as a fallback: if a county has no county-native
        # endpoint AND SCDOT hasn't been tripped this process, it still
        # works. If SCDOT IS walled, host_walled() short-circuits it.
        cfg = SC_GIS.get(county)
        if cfg:
            return cfg["url"]
        layer = SC_LAYER.get(county)
        if layer and not host_walled(SCDOT_BASE):
            return f"{SCDOT_BASE}/{layer}/query"
        return None
    if li.state == "NC":
        cfg = NC_GIS.get(county)
        return cfg["url"] if cfg else None
    return None


class _GISNetworkError(Exception):
    """Transport/connection error reaching the GIS endpoint (NOT a no-match). Lets the
    idempotency marker distinguish 'GIS has no data for this lead' from 'the network was
    down', so a flaky connection never permanently skips a lead on future re-enriches."""


async def _query_point(c: httpx.AsyncClient, base: str, lat: float, lng: float,
                       raise_on_net_error: bool = False) -> dict | None:
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
    except httpx.HTTPError as e:
        if raise_on_net_error:
            raise _GISNetworkError from e
        return None
    except ValueError:
        return None
    return None


_PARCEL_FIELDS = ("PIN", "TMS", "REID", "PARCELNUMBER", "TAXPIN", "PARNO",
                  "PARID", "MAPNUMBER", "pid", "parno", "PARCEL", "PARCEL_ID",
                  "PARCELID", "GPIN", "ACCOUNT", "ACCOUNTNO")
_LAYER_FIELDS_CACHE: dict[str, list[str]] = {}


async def _layer_fields(c: httpx.AsyncClient, base: str, raise_on_net_error: bool = False) -> list[str]:
    if base in _LAYER_FIELDS_CACHE:
        return _LAYER_FIELDS_CACHE[base]
    try:
        r = await c.get(base.rsplit("/query", 1)[0], params={"f": "json"}, timeout=15.0)
        fields = [f["name"] for f in r.json().get("fields", []) if "name" in f]
    except httpx.HTTPError as e:
        if raise_on_net_error:
            raise _GISNetworkError from e
        fields = []
    except ValueError:
        fields = []
    _LAYER_FIELDS_CACHE[base] = fields
    return fields


async def _query_parcel(c: httpx.AsyncClient, base: str, parcel: str,
                        raise_on_net_error: bool = False) -> dict | None:
    """Fallback when the lead has no lat/lng: match on a parcel-id-style field."""
    fields = await _layer_fields(c, base, raise_on_net_error=raise_on_net_error)
    flow = {f.lower(): f for f in fields}
    cands = [flow[p.lower()] for p in _PARCEL_FIELDS if p.lower() in flow]
    variants = _parcel_variants(parcel)
    for fld in cands:
        for pv0 in variants:
            pv = pv0.replace("'", "''")
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
            except httpx.HTTPError as e:
                if raise_on_net_error:
                    raise _GISNetworkError from e
                continue
            except ValueError:
                continue
    return None


# ---- Apply ---------------------------------------------------------------------

# Statutory tax-relief exemption codes (NC homestead etc.) — a HARD, free age/disability
# signal that several county GIS layers (e.g. Buncombe) carry in the attribute bag we already
# fetch. ELD requires owner 65+, DIS = totally & permanently disabled, BLD = blind, by law.
EXEMPT_FIELDS = ("exempt", "exemptcd", "exempt_cd", "exemptioncode", "exemption",
                 "exemptdesc", "exempt_desc", "taxrelief", "tax_relief", "exemptstat")
_EXEMPT_TABLE = {"ELD": "elderly_exemption", "DIS": "disabled_exemption",
                 "BLD": "blind_exemption", "VET": "disabled_veteran_exemption"}


def _exempt_signal(norm: dict) -> tuple[str, str] | None:
    """Return (code, tag) for a recognized statutory age/disability exemption, else None."""
    raw = _pick(norm, EXEMPT_FIELDS)
    if raw is None:
        return None
    v = str(raw).strip().upper()
    if not v or v in ("0", "NONE", "N", "NO", "FALSE", "0.0"):
        return None
    code = v[:3]
    if code in _EXEMPT_TABLE:
        return code, _EXEMPT_TABLE[code]
    if "ELDER" in v:
        return "ELD", "elderly_exemption"
    if "DISAB" in v:
        return "DIS", "disabled_exemption"
    if "BLIND" in v:
        return "BLD", "blind_exemption"
    if "VETERAN" in v:
        return "VET", "disabled_veteran_exemption"
    return None


def apply_gis_attrs(li: Listing, attrs: dict[str, Any]) -> dict[str, int]:
    """Backfill value/owner/specs from a matched GIS feature. Missing-only.
    Returns per-field fill flags (1 = newly populated this call)."""
    norm = _norm(attrs)
    flags = {k: 0 for k in ("market_value", "assessed_value", "owner_name",
                            "living_sqft", "year_built", "acreage", "land_use",
                            "street_address")}

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

    # Backfill street_address from the GIS situs field — addresses the 27%
    # gap where tax-sale / PDF-sourced leads have a parcel ID but no situs.
    if not (li.street_address or "").strip():
        ad = _pick(norm, ADDRESS_FIELDS)
        if ad:
            s = re.sub(r"\s+", " ", str(ad).strip())
            # Skip PO boxes, vacant lot markers, and noise.
            if s and len(s) >= 5 and not s.upper().startswith("P.O."):
                li.street_address = s
                flags["street_address"] = 1

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
        # Promote a recognized statutory exemption to a durable, whitelisted signal so the
        # life-events enricher can flag elderly/disabled owners (survives to listings.json,
        # unlike gis_attrs_full which is stripped at publish).
        ex = _exempt_signal(norm)
        if ex:
            li.raw["gis_exempt"] = {"code": ex[0], "tag": ex[1]}
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
        # FORCE re-attempts all (per docstring) — needed so coded fields like the exemption
        # signal get read even on leads whose core attrs are already complete.
        if not _force and (li.assessed_value or li.market_value) and li.owner_name and li.living_sqft:
            stats["skipped_done"] += 1
            return
        if not _force and (raw.get("gis") or {}).get("queried"):
            stats["skipped_done"] += 1
            return
        # PERSISTENT parcel cache — a LOCAL JOIN against the weekly bulk-downloaded county
        # parcel layer (data/parcel_cache). No network: fills owner/value/sqft/acreage/situs
        # in microseconds instead of a ~1.5s live GIS query. Only OPEN counties are cached
        # (walled ones aren't), so this is a fast path, not a replacement — a miss falls
        # through to the live query below. Proven Buncombe 2026-08-14: 99% hit, 95ms/6.6k leads.
        if li.parcel_id:
            from .parcel_cache import lookup as _pcache_lookup
            pc = _pcache_lookup(li.county or "", li.parcel_id)
            if pc:
                if not isinstance(li.raw, dict):
                    li.raw = {}
                if not li.owner_name and pc.get("owner"):
                    li.owner_name = pc["owner"]; stats["filled_owner"] += 1
                if not li.market_value and pc.get("market_value"):
                    li.market_value = pc["market_value"]; stats["filled_market"] += 1
                if not li.tax_value and pc.get("tax_value"):
                    li.tax_value = pc["tax_value"]
                if not li.living_sqft and pc.get("living_sqft"):
                    li.living_sqft = pc["living_sqft"]; stats["filled_sqft"] += 1
                if not li.acreage and pc.get("acreage"):
                    li.acreage = pc["acreage"]; stats["filled_acre"] += 1
                if not (li.street_address or "").strip() and pc.get("address"):
                    li.street_address = pc["address"]
                # Skip the live GIS query ONLY when we now have a situs address (the main thing
                # the live point/parcel query resolves). If the cache row had no address, fall
                # through to the live query to try for one via gis_attrs' own layer — we keep
                # the owner/value/sqft/acre just filled either way (they won't be overwritten).
                if (li.street_address or "").strip():
                    stats["parcel_cache_hit"] = stats.get("parcel_cache_hit", 0) + 1
                    li.raw.setdefault("gis", {})["queried"] = True
                    li.raw["gis"]["source"] = "parcel_cache"
                    stats["matched"] += 1
                    return
                stats["parcel_cache_partial"] = stats.get("parcel_cache_partial", 0) + 1
        base = _resolve_layer(li)
        if not base:
            return
        # Cache hit — reuse a prior run's resolved attrs for this parcel/point; NO network.
        key = _cache_key(li)
        if not _force and key and key in _ATTR_CACHE:
            cached = _ATTR_CACHE[key]
            stats["cache_hit"] = stats.get("cache_hit", 0) + 1
            if not isinstance(li.raw, dict):
                li.raw = {}
            li.raw.setdefault("gis", {})["queried"] = True
            if cached:
                stats["matched"] += 1
                apply_gis_attrs(li, cached)
            return
        async with sem:
            attrs = None
            net_ok = True
            if li.latitude and li.longitude:
                try:
                    attrs = await _query_point(c, base, float(li.latitude), float(li.longitude),
                                               raise_on_net_error=True)
                except _GISNetworkError:
                    net_ok = False
                except (ValueError, TypeError):
                    attrs = None
            if attrs is None and net_ok and li.parcel_id:
                try:
                    attrs = await _query_parcel(c, base, li.parcel_id, raise_on_net_error=True)
                except _GISNetworkError:
                    net_ok = False
            stats["queried"] += 1
            # Mark attempted ONLY when we actually reached the GIS endpoint. A transient
            # network error leaves net_ok False -> lead stays unmarked -> retried next run
            # (a flaky wifi drop never permanently skips a lead). A genuine no-match (reached
            # GIS, no feature) IS marked so we don't re-query it every run forever.
            if net_ok and (li.latitude or li.parcel_id):
                if not isinstance(li.raw, dict):
                    li.raw = {}
                li.raw.setdefault("gis", {})["queried"] = True
                if key:  # cache the result (a match OR a confirmed no-match) for reuse
                    _ATTR_CACHE[key] = attrs or {}
            elif not net_ok:
                stats["net_err"] = stats.get("net_err", 0) + 1
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
            stats["filled_address"] = stats.get("filled_address", 0) + flags["street_address"]

    _load_cache()
    # Batch processing to avoid OOM on 8GB machines — process in chunks of 2500
    # instead of creating 53k+ coroutines via asyncio.gather all at once.
    BATCH = 2500
    async with client(timeout=20.0) as c:
        for i in range(0, len(listings), BATCH):
            batch = listings[i:i + BATCH]
            await asyncio.gather(*(one(c, li) for li in batch))
    _save_cache()
    stats["cache_hit"] = stats.get("cache_hit", 0)
    stats["cache_size"] = len(_ATTR_CACHE)

    log.info("enrichment.gis_attrs.done", **stats)
    return stats
