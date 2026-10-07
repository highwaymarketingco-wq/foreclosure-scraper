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

from .enrichment_arcgis import NC_GIS, SCDOT_BASE, SC_LAYER, SC_GIS, host_walled, situs_view
from .http_client import client
from .sensitive_fields import drop_sensitive
from . import owner_freshness

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
from .models import Listing, ListingType

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
# Situs / physical address — the street address of the property itself. Read through
# enrichment_arcgis.situs_view(): "StreetAddress" and "ADDRESS" are the OWNER'S MAILING
# street on Spartanburg's CAMA layer and Buncombe's parcel layer (this list wrote the
# mailing street on 40/40 live records of each, 2026-10-06). SITUS_ADDR is the split
# situs situs_view() stitches (Buncombe HouseNumber + streetname ...).
ADDRESS_FIELDS = (
    "SITUS_ADDR", "StreetAddress", "situs", "siteadd", "Physical_Address", "LOCATION_ADDR",
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
            return drop_sensitive(feats[0]["attributes"])
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
                    return drop_sensitive(feats[0]["attributes"])
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
#: 2026-10-02 breadth fix — code -> the exact `kind` string
#: enrichment_tax_relief.py's own senior_exemption classify path writes
#: (`_EXEMPT_KIND = {"ELD": "elderly", "DIS": "disabled", "BLD": "blind"}`
#: there). distress_score.py's `senior_exemption` LIFE_EVENT signal (w=8) reads
#: raw['tax_relief']['kind'] specifically, never raw['gis_exempt'] -- so every
#: ELD/DIS/BLD hit this GENERIC gis_attrs scan found outside
#: enrichment_tax_relief.py's own 7-county _RELIEF_LAYERS list (Buncombe/
#: Henderson/Gaston/Rutherford/York/Burke/Lincoln) was invisible to the score,
#: even though raw['gis_exempt'] itself has carried the identical hard
#: elderly/disabled/blind fact since this field was added. Live-verified
#: 2026-10-02 against Buncombe's own live ArcGIS layer (the same one
#: enrichment_tax_relief.py queries): 3,319 ELD / 139 DIS / 100 BLD real
#: current parcels. VET (disabled_veteran_exemption) is deliberately NOT
#: mapped here -- enrichment_tax_relief.py has never modeled a veteran
#: exemption as a distress signal, so inventing one would be a new scoring
#: decision, not a key-naming fix.
_EXEMPT_TO_TAX_RELIEF_KIND = {"ELD": "elderly", "DIS": "disabled", "BLD": "blind"}


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


#: The scraper whose own rows are read from the exempt parcel itself (counties_nc.buncombe_elderly:
#: one bulk query of Exempt IN ('ELD','DIS','BLD','VET'); its parcel_id and situs ARE that parcel's).
ELDERLY_SOURCE = "counties_nc.buncombe_elderly"

#: Layer fields that carry the matched feature's own parcel id: the full PIN first.
_PIN_FIELDS = ("pinnum", "pin") + _PARCEL_FIELDS


def _same_parcel(a: Any, b: Any) -> bool:
    """Two parcel-id spellings of one parcel: equal once punctuation is gone, or one is the other
    plus a zero pad ('9648-69-0092-00000' == '9648690092'). A condominium unit's id
    ('9627023924C0102') never equals its building's pad."""
    na, nb = _norm_parcel(str(a or "")), _norm_parcel(str(b or ""))
    if not na or not nb:
        return False
    if na == nb:
        return True
    short, long_ = sorted((na, nb), key=len)
    return len(short) >= 6 and long_.startswith(short) and set(long_[len(short):]) <= {"0"}


def exempt_parcel_relation(parcel_id: Any, street_address: Any, resolver_parcel: bool,
                           attrs: dict[str, Any]) -> tuple[str, str]:
    """(pin relation, address relation) of a row, as it was BEFORE this feature filled anything
    in, to the parcel feature `attrs` it was matched to: ('same'|'different'|'unknown',
    'match'|'conflict'|'unknown'). The pin is 'unknown' for a row without a parcel id, one a
    resolver took from the same point (raw['parcel_from_geo'] / ['parcel_from_address']: it proves
    nothing), or a feature that carries no recognizable parcel field. The address is the
    feature's situs against the row's, exact house number and street name after normalization
    (verification.verifiers._tax_common.address_relation)."""
    norm = _norm(attrs)
    pins = [str(norm[f.lower()]) for f in _PIN_FIELDS if norm.get(f.lower()) not in (None, "", " ")]
    if not (parcel_id or "").strip() or resolver_parcel or not pins:
        pin_rel = "unknown"
    else:
        pin_rel = "same" if any(_same_parcel(parcel_id, p) for p in pins) else "different"
    situs = _pick(_norm(situs_view(attrs)), ADDRESS_FIELDS)
    if not (street_address or "").strip() or not situs:
        return pin_rel, "unknown"
    from .verification.verifiers._tax_common import address_relation
    return pin_rel, address_relation(street_address, situs)


def exempt_is_rows_own(pin_rel: str, addr_rel: str) -> bool:
    """May the exemption code of a matched parcel feature be attached to the row? Only when the
    feature IS the row's parcel: the same parcel id and no conflicting address, or (no parcel id
    to compare) the row's exact address. A feature found by POINT alone (a geocode that lands on
    a neighbour's polygon or on the road beside it), one whose parcel id is another parcel's, or
    a row with no identity to compare is not: the code is then somebody else's. Measured
    2026-10-06 on the 2026-10-05 board (4,481 rows carry the claim; 51 only through this path): 41
    of the 51 sit on a parcel that is not exempt today; of the 38 whose point still falls in a
    polygon, 17 landed in an exempt polygon that is not the row's parcel (a different owner in
    14 of the 17) and none in the row's own exempt parcel."""
    return (pin_rel == "same" and addr_rel != "conflict") or (pin_rel == "unknown"
                                                              and addr_rel == "match")


def apply_gis_attrs(li: Listing, attrs: dict[str, Any]) -> dict[str, int]:
    """Backfill value/owner/specs from a matched GIS feature. Missing-only.
    Returns per-field fill flags (1 = newly populated this call).

    The statutory exemption code (raw['gis_exempt'], and raw['tax_relief'] bridged from it) is
    attached only when the feature is the row's own parcel (exempt_is_rows_own); the row's
    identity is read here BEFORE the street-address backfill below can copy the feature's own
    situs onto it."""
    norm = _norm(attrs)
    resolver0 = isinstance(li.raw, dict) and bool(li.raw.get("parcel_from_geo")
                                                  or li.raw.get("parcel_from_address"))
    pin_rel, addr_rel = exempt_parcel_relation(li.parcel_id, li.street_address, resolver0, attrs)
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

    ow = _pick(norm, OWNER_FIELDS)
    if ow:
        s = re.sub(r"\s+", " ", str(ow).strip())
        # Quality gate unchanged from the original missing-only fill (len >= 3,
        # not pure digits). On top of that, owner_freshness.should_refresh_owner_name
        # allows this to act as a REFRESH (not just a blank-fill) when li.owner_name
        # is already set but old enough/unstamped -- see owner_freshness.py docstring
        # for why this field specifically (current-state GIS owner) is safe to
        # refresh while e.g. a court-caption defendant name is not.
        if len(s) >= 3 and not s.replace(" ", "").isdigit() and \
                owner_freshness.should_refresh_owner_name(li, s):
            owner_freshness.stamp_owner_name(li, s)
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
        ad = _pick(_norm(situs_view(attrs)), ADDRESS_FIELDS)
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
        li.raw["gis_attrs_full"] = drop_sensitive(attrs)
        # Promote a recognized statutory exemption to a durable, whitelisted signal so the
        # life-events enricher can flag elderly/disabled owners (survives to listings.json,
        # unlike gis_attrs_full which is stripped at publish).
        ex = _exempt_signal(norm)
        own_row = li.source == ELDERLY_SOURCE and isinstance(li.raw.get("gis_exempt"), dict)
        if ex and own_row:
            # the elderly scraper's own row already carries the code it read from THIS parcel
            # (care_of included): untouched, and the bridge below follows that code, not the
            # polygon a geocode happened to land on
            code0 = str(li.raw["gis_exempt"].get("code") or "").strip().upper()[:3]
            ex = (code0, _EXEMPT_TABLE[code0]) if code0 in _EXEMPT_TABLE else None
        elif ex and not exempt_is_rows_own(pin_rel, addr_rel):
            ex = None            # a neighbour's (or an unidentified) parcel: no claim
        if ex:
            if not own_row:
                li.raw["gis_exempt"] = {"code": ex[0], "tag": ex[1]}
            # 2026-10-02 breadth fix (same shape as code_enforcement/condemned/
            # rollback_exposure the same day): also promote a real elderly/disabled/
            # blind hit into raw['tax_relief'], the key distress_score.py's
            # senior_exemption signal actually reads -- see
            # _EXEMPT_TO_TAX_RELIEF_KIND above. enrichment_tax_relief.py runs LATER
            # in main.py's pipeline and unconditionally overwrites raw['tax_relief']
            # for its own 7 dedicated counties, so this bridge changes nothing there;
            # it only sticks for every OTHER county this generic GIS scan reaches,
            # where gis_exempt was previously the only record of the fact.
            kind = _EXEMPT_TO_TAX_RELIEF_KIND.get(ex[0])
            if kind:
                li.raw["tax_relief"] = {"kind": kind, "basis": "elderly_disabled_exclusion",
                                        "code": ex[0], "county": li.county}
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
        # owner_name may be "complete" (non-empty) yet STALE -- see owner_freshness.py
        # (live-confirmed 2026-10-02/03: 25.4% of a Buncombe sample show a DIFFERENT
        # current owner than the board for the same parcel_id). owner_refresh_due is
        # deliberately gated on li.parcel_id too: the only recheck cheap enough to run
        # on every pass is the FREE, local parcel_cache lookup a few lines down, not a
        # live network query -- a lead with no parcel_id would otherwise fall through
        # past these skips straight into the (expensive) live GIS query below, which
        # these two skip gates exist specifically to avoid paying for on every run.
        owner_refresh_due = bool(li.parcel_id) and bool(li.owner_name) and \
            owner_freshness.is_owner_refreshable(li)
        # FORCE re-attempts all (per docstring) — needed so coded fields like the exemption
        # signal get read even on leads whose core attrs are already complete.
        if not _force and (li.assessed_value or li.market_value) and li.owner_name and \
                li.living_sqft and not owner_refresh_due:
            stats["skipped_done"] += 1
            return
        if not _force and (raw.get("gis") or {}).get("queried") and not owner_refresh_due:
            stats["skipped_done"] += 1
            return
        # TAX_SALE_OVERAGE: every field this function fills (owner, mailing,
        # value, sqft, acreage) describes the parcel's CURRENT owner -- a
        # different person from the overage claimant the listing is about
        # (the claimant lost the parcel AT the tax sale the claim came from).
        # Nothing here is safe to backfill onto this listing_type.
        if li.listing_type == ListingType.TAX_SALE_OVERAGE:
            return
        # PERSISTENT parcel cache — a LOCAL JOIN against the weekly bulk-downloaded county
        # parcel layer (data/parcel_cache). No network: fills owner/value/sqft/acreage/situs
        # in microseconds instead of a ~1.5s live GIS query. Only OPEN counties are cached
        # (walled ones aren't), so this is a fast path, not a replacement — a miss falls
        # through to the live query below. Proven Buncombe 2026-08-14: 99% hit, 95ms/6.6k leads.
        if li.parcel_id:
            from .parcel_cache import lookup as _pcache_lookup, sale_amount
            pc = _pcache_lookup(li.county or "", li.parcel_id, li.state)
            if pc:
                if not isinstance(li.raw, dict):
                    li.raw = {}
                owner_cand = pc.get("owner")
                if owner_cand and owner_freshness.should_refresh_owner_name(li, owner_cand):
                    owner_freshness.stamp_owner_name(li, owner_cand)
                    stats["filled_owner"] += 1
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
                # OWNER MAILING + LAST SALE, added 2026-09-10. The cache has carried these
                # for 10 of its 14 counties since the schema gained the columns, and they
                # are written to raw["gis"]["mailing"] and raw["gis"]["last_sale"]
                # DELIBERATELY -- those are the exact keys flags.py already reads to raise
                # absentee_owner and the equity flags. Writing the value where the existing
                # consumer looks is the whole fix; inventing a new key is how this data got
                # lost the first time.
                #
                # SC owner contact runs 8-18% against NC's 50-89% and the per-county
                # coverage matrix names it the binding constraint in every SC county, while
                # raw["gis"]["mailing"] was populated on 4,060 of 94,384 board rows.
                if pc.get("owner_mailing"):
                    g = li.raw.setdefault("gis", {})
                    if not g.get("mailing"):
                        g["mailing"] = pc["owner_mailing"]
                        stats["filled_mailing"] = stats.get("filled_mailing", 0) + 1
                if pc.get("sale_price") or pc.get("sale_date"):
                    g = li.raw.setdefault("gis", {})
                    ls = g.setdefault("last_sale", {})
                    _amt = sale_amount(pc.get("sale_price"))
                    if _amt and not ls.get("amount"):
                        ls["amount"] = _amt
                        stats["filled_sale_price"] = stats.get("filled_sale_price", 0) + 1
                    if pc.get("sale_date") and not ls.get("date"):
                        ls["date"] = pc["sale_date"]
                # Skip the live GIS query ONLY when we now have a situs address (the main thing
                # the live point/parcel query resolves) AND the cache's VALUE fields were trusted
                # (not withheld for staleness — lookup_with_tier() omits market_value/tax_value
                # once this county's cache is older than parcel_cache.CACHE_VALUE_MAX_AGE_DAYS).
                # A stale-value cache row still needs the live query below, same as a cache
                # miss, so this lead's market_value/tax_value come from the CURRENT county data
                # instead of silently staying empty forever. Proven live 2026-10-02: a Buncombe
                # lead whose cache hit left market_value/tax_value unfilled for exactly this
                # reason, but street_address filled, would otherwise return here and never get a
                # value at all (the OLD code returned on street_address alone).
                from .parcel_cache import cache_is_stale as _pcache_stale
                value_still_missing = not (li.market_value or li.tax_value)
                value_withheld = value_still_missing and _pcache_stale(li.county or "", li.state)
                if (li.street_address or "").strip() and not value_withheld:
                    stats["parcel_cache_hit"] = stats.get("parcel_cache_hit", 0) + 1
                    li.raw.setdefault("gis", {})["queried"] = True
                    li.raw["gis"]["source"] = "parcel_cache"
                    stats["matched"] += 1
                    return
                stats["parcel_cache_partial"] = stats.get("parcel_cache_partial", 0) + 1
            elif owner_refresh_due and li.market_value:
                # pc was a MISS and the only reason this lead reached this point at all
                # is a stale-owner recheck (owner_refresh_due) with everything else
                # already complete (li.market_value here mirrors the first skip gate's
                # condition above). A local cache miss is not grounds to pay for a live
                # network re-query just to re-verify an owner name -- bail; this lead
                # gets another free chance to refresh next time its county's
                # parcel_cache carries a row for it.
                return
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

    # FREE LOCAL PARCEL-CACHE JOIN FIRST, over EVERY listing (2026-10-07). The per-lead
    # block above reads the same cache, but only after the two idempotency gates written
    # for the expensive live query (raw["gis"]["queried"], "core attrs complete") and only
    # for the batches the RESOLVER_PHASE_MAX_SECONDS cap lets run, so 36,469 board rows
    # with a parcel id sat without the owner mailing their county cache already held.
    # A local lookup costs microseconds; it must not wait behind the network budget.
    # Fill-only, same guards as scripts/join_parcel_cache_to_board.py (one shared copy in
    # parcel_cache_join). FORECLOSURE_CACHE_JOIN=0 turns it off.
    if os.environ.get("FORECLOSURE_CACHE_JOIN") != "0":
        try:
            from .parcel_cache_join import join_listings
            jc = join_listings(listings)
            stats["cache_join"] = dict(jc)
            log.info("enrichment.gis_attrs.cache_join", counts=dict(jc))
        except Exception:  # noqa: BLE001 - the live loop below still runs
            log.error("enrichment.gis_attrs.cache_join_failed", exc_info=True)

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
