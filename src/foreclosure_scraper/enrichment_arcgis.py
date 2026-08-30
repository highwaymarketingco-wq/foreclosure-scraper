"""County GIS enrichment via ArcGIS REST FeatureServer / MapServer endpoints.

Audit confirmed:
  * 9 of 11 SC counties → single shared SCDOT MapServer with one layer per county
  * 12 of 14 NC counties → direct county ArcGIS REST endpoints (same query syntax)
  * Abbeville SC + Yancey NC → JS-only / qPublic; covered by enrichment_apify.py

For each listing with an address + county + state we:
  1. Look up the right FeatureServer URL + address-search field for that county
  2. Query ?where=<addr_field> LIKE '%<street>%' and pull JSON attributes
  3. Map county-specific field names to our Listing schema
  4. Fill missing fields without overwriting good data we already have
"""
from __future__ import annotations

import asyncio
import re
from typing import Any

import httpx
import structlog

from .http_client import client
from .models import Listing, PropertyKind

log = structlog.get_logger()


# ---- SC: single SCDOT base URL with per-county layer ID ---------------------------

SCDOT_BASE = "https://smpesri.scdot.org/arcgis/rest/services/GISMapping/SC_Parcels/MapServer"

# ---- Generic per-host ArcGIS circuit-breaker --------------------------------
# Generalized from the SCDOT token-wall (2026-08-12: HTTP 200 +
# {"error":{"code":499,"Token Required"}}). ANY ArcGIS host that goes token-walled
# OR starts timing out will otherwise be re-hit per-lead across
# parcel_from_geo / gis_attrs / cama / recorded_comps / owner_mailing / footprint
# with no cross-lead memory — the class that dragged a run to 16h on 2026-08-13.
# The breaker trips a host on the FIRST token/auth error OR after N consecutive
# hard failures (timeout/connection), and every later call to that host
# short-circuits for the life of the process. Hosts stay WIRED — a fresh process
# (or a lifted wall / provided token) resolves against them normally again.
from urllib.parse import urlparse as _urlparse

_WALLED_HOSTS: set[str] = set()
_HOST_FAILS: dict[str, int] = {}
_HOST_FAIL_TRIP = 8  # consecutive hard failures before a host is presumed dead


def _host_of(url: str) -> str:
    try:
        return (_urlparse(url).hostname or "").lower()
    except Exception:  # noqa: BLE001
        return ""


def host_walled(url: str) -> bool:
    """True once the host behind ``url`` has been tripped this process."""
    return _host_of(url) in _WALLED_HOSTS


def mark_host_walled(url: str, reason: str = "") -> None:
    """Trip the breaker for a host (idempotent; logs once)."""
    h = _host_of(url)
    if h and h not in _WALLED_HOSTS:
        _WALLED_HOSTS.add(h)
        log.warning("arcgis.host_walled", host=h,
                    reason=reason or "arcgis error / repeated timeout",
                    note="skipping this host for the rest of this run")


def note_host_ok(url: str) -> None:
    """A clean response — reset the host's consecutive-failure counter."""
    h = _host_of(url)
    if h:
        _HOST_FAILS[h] = 0


def note_host_hard_failure(url: str) -> None:
    """A timeout/connection error (NOT a normal empty result). Trip after N in a row."""
    h = _host_of(url)
    if not h:
        return
    _HOST_FAILS[h] = _HOST_FAILS.get(h, 0) + 1
    if _HOST_FAILS[h] >= _HOST_FAIL_TRIP:
        mark_host_walled(url, reason=f"{_HOST_FAILS[h]} consecutive hard failures")


def is_arcgis_error(data: Any) -> bool:
    """ArcGIS reports failure as HTTP 200 + an ``error`` object, so status alone lies."""
    return isinstance(data, dict) and isinstance(data.get("error"), dict)


def is_token_error(data: Any) -> bool:
    """Auth/token wall: code 499/498/403 or a 'token'/'not authorized' message."""
    if not is_arcgis_error(data):
        return False
    err = data["error"]
    msg = str(err.get("message", "")).lower()
    return err.get("code") in (499, 498, 403) or "token" in msg or "not authorized" in msg


# --- backward-compat SCDOT aliases (existing wiring + tests use these) --------
def scdot_walled() -> bool:
    return host_walled(SCDOT_BASE)


def mark_scdot_walled() -> None:
    mark_host_walled(SCDOT_BASE, reason="SC_Parcels 200+Token Required")


def is_scdot_token_error(data: Any) -> bool:
    return is_token_error(data)


# Per-county situs-field overrides for SC SCDOT layers whose address column
# can't be auto-detected by _detect_addr_field (verified live 2026-06-26).
# The auto-detector looks for ADDR/STREET/SITUS-style names; these layers either
# split situs across number+name columns (no single match) or only expose an
# owner-mailing field that the detector would otherwise pick. We pin the field
# the LIKE should match against so the SALEP/SALEDT/value aliases can actually
# fire. Counties whose situs auto-detects cleanly (Pickens=LOCADD,
# Anderson=PHYS_ADDR, Beaufort=SitusAddre) are intentionally absent.
SC_SITUS: dict[str, str] = {
    "Charleston": "PROP_ST_NA",   # split: PROP_ST_NO + PROP_ST_NA; match the name
    "Georgetown": "StreetName",   # split: StreetNumber + StreetName; match the name
    "Laurens": "Property_A",      # full situs; auto-detect wrongly picks owner-mail Address1
}

SC_LAYER: dict[str, int] = {
    "Abbeville": 1, "Aiken": 2, "Allendale": 3, "Anderson": 4, "Bamberg": 5,
    "Barnwell": 6, "Beaufort": 7, "Berkeley": 8, "Calhoun": 9, "Charleston": 10,
    "Cherokee": 11, "Chester": 12, "Chesterfield": 13, "Clarendon": 14, "Colleton": 15,
    "Darlington": 16, "Dillon": 17, "Dorchester": 18, "Edgefield": 19, "Fairfield": 20,
    "Florence": 21, "Georgetown": 22, "Greenville": 23, "Greenwood": 24, "Hampton": 25,
    "Horry": 26, "Jasper": 27, "Kershaw": 28, "Lancaster": 29, "Laurens": 30,
    "Lee": 31, "Lexington": 32, "Marion": 33, "Marlboro": 34, "McCormick": 35,
    "Newberry": 36, "Oconee": 37, "Orangeburg": 38, "Pickens": 39, "Richland": 40,
    "Saluda": 41, "Spartanburg": 42, "Sumter": 43, "Union": 44, "Williamsburg": 45,
    "York": 46,
}

# Sentinel addr_field for layers with NO single situs column — the address is
# split across component fields. When a county's addr_field starts with
# "__concat:", _arcgis_query LIKE-matches the street-name component and
# _stitch_situs() rebuilds the full situs on read.
_BRUNSWICK_CONCAT = "__concat:HouseNumber+StreetDirection+StreetName+StreetType__"
# Georgetown SC splits situs across StreetNumber + StreetName (2026-08-12).
_GEORGETOWN_CONCAT = "__concat:StreetNumber+StreetName__"


# SCDOT SC_Parcels went TOKEN-WALLED 2026-08-12 (HTTP 200 + body
# {"error":{"code":499,"message":"Token Required"}} on the service root AND every
# layer query), which silently killed owner/situs resolution for every SC county.
# SC_GIS is the county-native replacement: same {url, addr_field} shape as NC_GIS.
# addr_field=None -> situs auto-detects via FIELD_ALIASES; a pinned string -> the
# situs column to LIKE-match (for layers whose field name isn't in the aliases).
# Endpoints probed live 2026-08-12 (docs/sc_gis_endpoints_*.md). Counties with no
# free county-native owner+situs path are in docs/walls_register.md.
SC_GIS: dict[str, dict[str, Any]] = {
    "Spartanburg": {
        "url": "https://maps.spartanburgcounty.org/server/rest/services/GIS/CAMA_Parcels/FeatureServer/0/query",
        "addr_field": None,   # situs PropertyLocation, owner OwnerName (both aliased)
    },
    "Laurens": {
        "url": "https://laurenscountygis.org/arcgis/rest/services/Pebble/TaxParcel/MapServer/5/query",
        "addr_field": None,   # situs Property_Address (aliased), owner Owner/Name1
    },
    "Pickens": {
        "url": "https://services1.arcgis.com/59960rq18IxUcAVI/arcgis/rest/services/Pickens_Open_data/FeatureServer/6/query",
        "addr_field": None,   # situs LOCADD (added to aliases), owner NAME1 (aliased)
    },
    "Colleton": {
        "url": "https://services1.arcgis.com/m0cnLGKdhwao8WvM/arcgis/rest/services/Public_Data/FeatureServer/2/query",
        "addr_field": None,   # situs PropertyAddress (aliased), owner OwnerName1 (added)
    },
    "Beaufort": {
        # Every column is GisFile_-prefixed so situs won't auto-detect; pin it.
        # owner GisFile_Owner1 + value GisFile_Appraised + deed GisFile_Book/Page
        # are added to the alias tables below.
        "url": "https://gis.beaufortcountysc.gov/server/rest/services/EnerGov/MapServer/1/query",
        "addr_field": "GisFile_SitusAddre",
    },
    "Georgetown": {
        # Situs is split across StreetNumber + StreetName; match on the name and
        # stitch the full situs on read (owner Owner1 is already aliased).
        "url": "https://gis1.georgetowncountysc.org/portal/rest/services/GCGIS_Energov/MapServer/2/query",
        "addr_field": _GEORGETOWN_CONCAT,
    },
    "Charleston": {
        # Parcel layer (61): owner OWNER1 + PID, NO situs. address_owner_v2 joins
        # the sibling Address-Points layer (1) by PID for the situs (SC_SITUS_JOIN
        # below). addr_field=None here: enrich's address path no-ops for Charleston
        # (61 has no situs), while the name->address resolver does the PID join.
        "url": "https://gisccapps.charlestoncounty.org/arcgis/rest/services/GIS_VIEWER/New_Parcel_Search/MapServer/61/query",
        "addr_field": None,
    },
    # WALLED (no free county-native owner+situs) — see docs/walls_register.md:
    #   Cherokee, Union (WAF-403), Oconee (owner only, no situs), Anderson (owner masked).
}


# ---- NC: direct ArcGIS REST per county ------------------------------------------

NC_GIS: dict[str, dict[str, Any]] = {
    # Audited 2026-06-15 against live FeatureServer schemas. Each addr_field
    # was verified against a real parcel from docs/listings.json. Tests in
    # tests/test_nc_gis_addr_fields.py guard against future drift.
    #
    # When a county's FeatureServer exposes only parcel geometry with no
    # situs/property-address field, set addr_field=None — the resolver
    # skips writing a street address (parcel_id + centroid still useful).
    "Mecklenburg": {
        "url": "https://meckgis.mecklenburgcountync.gov/server/rest/services/TaxParcel_Camaownershipvalues/FeatureServer/0/query",
        "addr_field": "situsaddress1",
    },
    "Buncombe": {
        "url": "https://gis.buncombecounty.org/arcgis/rest/services/property_bc_dis/MapServer/1/query",
        "addr_field": "Address",
    },
    "Henderson": {
        "url": "https://gisweb.hendersoncountync.gov/arcgis/rest/services/Parcels/FeatureServer/0/query",
        "addr_field": "LOCATION_ADDR",
    },
    "Rutherford": {
        # MapServer/6 exposes only parcel geometry + MBL/PIN/REID, no address.
        # Real situs lives at the tax-assessor (a separate, JS-rendered site).
        # TODO: find a Rutherford FeatureServer that exposes situs, or pair
        # with countywide centerline geocode by MBL.
        "url": "https://gis.rutherfordcountync.gov/server/rest/services/MapMetricsServiceRutherford/MapServer/6/query",
        "addr_field": None,
    },
    "Cleveland": {
        # WAS Tax/Tax/MapServer/1 (60,245 rows, GIS_PID/GIS_PIN/GIS_Owner* only,
        # NO address field) — so every Cleveland query returned [] and the county
        # sat at 1.2% parcel_id / 1.2% deed on the board. The Basemap service
        # carries the joined COUNTY_* CAMA extract (verified live 2026-08-03:
        # 70,059 rows, situs 99.4%, owner 99.4%, mailing+city+state+zip 99.4%).
        #
        # TRUNCATION: the upstream CAMA extract hard-caps COUNTY_ADDRESS,
        # COUNTY_OWNER_1 and COUNTY_MAILING_ADDRESS at 20 chars (measured over
        # all 70,059 rows: 9,032 / 23,539 / 11,893 rows sit at exactly len 20 and
        # NONE exceed it). Two of the three are repairable from sibling columns on
        # this same layer — see _repair_cleveland(). COUNTY_MAILING_ADDRESS has no
        # untruncated sibling and is the residual wall.
        "url": "https://gis.clevelandcounty.com/arcgis/rest/services/Basemap/Parcels/MapServer/0/query",
        "addr_field": "COUNTY_ADDRESS",
        "out_fields": (
            "GIS_PID,GIS_PIN,GIS_Owner1,GIS_Owner2,GIS_Calculated_Acres,"
            "GIS_Deeded_Acres,COUNTY_PID,COUNTY_ADDRESS,COUNTY_OWNER_1,"
            "COUNTY_OWNER_2,COUNTY_MAILING_ADDRESS,COUNTY_CITY,COUNTY_STATE,"
            "COUNTY_ZIP,COUNTY_LAND_VALUE,COUNTY_BUILDING_VALUE,"
            "COUNTY_TOTAL_VALUE,COUNTY_DEED,COUNTY_PAGE,COUNTY_ACRES,"
            "LOCATE_ADDRESS"
        ),
    },
    "Polk": {
        "url": "https://services1.arcgis.com/23uf7jKvz6SRPFWJ/arcgis/rest/services/TaxParcels/FeatureServer/0/query",
        "addr_field": "PHYSICAL_STREET_ADDRESS",
    },
    "Gaston": {
        # WAS cogserver.gastonianc.gov (the CITY of Gastonia server) MapServer/0:
        # alive but a thinner, staler copy — 115,066 rows and no bed/bath, no
        # vacancy flag, no prior-year owner, no precomputed lat/lng.
        # The COUNTY's own service is the authority (verified live 2026-08-03):
        # 117,565 rows, PHYSSTRADD situs 99.97%, Latitude/Longitude 100%,
        # XBEDRM/XBATHS 73.7%, plus the VacantImpro / CURR_STATE / PRVYRNAME1
        # columns the cohort flags in _cohort_flags() are built from.
        # NOTE the layer id is 11, NOT 0 — /FeatureServer/0 returns HTTP 500;
        # Parcels is the only layer published on this service and it is id 11.
        "url": "https://gis.gastoncountync.gov/publicgis/rest/services/PublicGIS/Parcels/FeatureServer/11/query",
        "addr_field": "PHYSSTRADD",
        "out_fields": (
            "PIN,PID,AKPAR,PHYSSTRADD,CURR_NAME1,CURR_NAME2,CURR_ADDR1,"
            "CURR_ADDR2,CURR_CITY,CURR_STATE,CURR_ZIPCODE,JAN1_NAME1,"
            "PRVYRNAME1,PRVYRNAME2,FMV_LAND,FMV_IMPRV,FMV_TOTAL,TOTVAL,"
            "DEED_BOOK,DEED_PAGE,SALEDATE,SALE_DAY,SALE_MTH,SALE_YEAR,"
            "SALESAMT,YEARBLT,SQFT,XBEDRM,XBATHS,XHBATHS,CALCAC,DEEDAC,"
            "VacantImpro,property_use,STRUCTTYPE,Latitude,Longitude,ZIP"
        ),
    },
    "Transylvania": {
        # This layer has NO situs column. Verified live 2026-08-03 on real rows:
        #   OWNER_NAME = owner 1        ADDRESS_1  = owner 2's NAME (not an address)
        #   ADDRESS_3  = owner MAILING street   CITY/STATE/ZIP_CODE = MAILING city/st/zip
        #   LEGAL_ADDR = a legal description ("LOT 1 Whitewater Cove 2.00")
        # addr_field was "ADDRESS_3", which LIKE-matched the property's street
        # against the OWNER'S MAILING address — a match there means the owner
        # happens to live on a similarly-named street, not that we found the
        # parcel. Set to None: parcel_id + centroid are still useful and a wrong
        # parcel_id corrupts the dedupe key. Mailing/owner for this county is
        # handled properly in enrichment_owner_mailing.COUNTY_GIS["NC:Transylvania"].
        "url": "https://gis.transylvaniacounty.org/server/rest/services/Parcels/MapServer/2/query",
        "addr_field": None,
    },
    "McDowell": {
        "url": "https://services9.arcgis.com/ETP7IuCigkUz7iI9/arcgis/rest/services/McDowell_Parcels/FeatureServer/0/query",
        "addr_field": "siteadd",
    },
    "Lincoln": {
        "url": "https://arcgisserver.lincolncountync.gov/arcgis/rest/services/Server_TaxParcelViewerSP/MapServer/0/query",
        "addr_field": "PHYSICALADDR",
    },
    "Madison": {
        "url": "https://services1.arcgis.com/SIYkiqjmENweC50g/arcgis/rest/services/Parcels_NC/FeatureServer/0/query",
        "addr_field": "ADDR",
    },
    "Mitchell": {
        # LocAddr returns street name only (no house #). MailAddr is owner
        # mailing, often the situs for owner-occupied but not always. The
        # resolver should prefer LocAddr + house-number from any neighbor
        # field if present; leaving LocAddr here so behaviour is unchanged
        # for now and the resolver can keep enriching from there.
        "url": "https://mapping.mitchellcountync.gov/arcgis/rest/services/WebMapNew/MapServer/12/query",
        "addr_field": "LocAddr",
    },
    "Burke": {
        "url": "https://services3.arcgis.com/axQ4OCSpcxALIQsV/arcgis/rest/services/Tax_Parcels/FeatureServer/0/query",
        "addr_field": "LOCATION_ADDR",
    },
    # ---- Coastal NC (added 2026-06-26, all live-verified against the layer's
    #      DescribeFeatureType + a real residential address-LIKE query) -------
    "Carteret": {
        # owner=OWNER, situs=PropertyAddress (full "208 LIVE OAK DR ..."),
        # sqft=HtdSqFt, value via _pick (TaxValue family). Polygon geometry.
        "url": "https://arcgisweb.carteretcountync.gov/arcgis/rest/services/Layers/Parceldata/MapServer/0/query",
        "addr_field": "PropertyAddress",
    },
    "Onslow": {
        # owner=OWNER1, situs=PHYSICALADDRESS, value=TAXMARKETVALUE,
        # sqft=HEATEDSQUAREFEET. Polygon geometry.
        "url": "https://maps.onslowcountync.gov/arcgis/rest/services/GISWebsite/GISWebsiteLayers/MapServer/7/query",
        "addr_field": "PHYSICALADDRESS",
    },
    "Brunswick": {
        # owner=Name1. NO single situs field — situs must be built by
        # concatenating HouseNumber + StreetDirection + StreetName + StreetType.
        # addr_field is left as the synthetic sentinel so _arcgis_query knows to
        # build a multi-field LIKE and stitch the situs on read.
        "url": "https://bcgis.brunswickcountync.gov/arcgis/rest/services/Layers/TaxParcels/MapServer/0/query",
        "addr_field": _BRUNSWICK_CONCAT,
    },
    "Pender": {
        # owner=NAME, situs=PROPERTY_ADDRESS, sqft=HEAT_SQ_FT. Polygon geometry.
        # Slow TLS handshake — needs a longer timeout than the default.
        "url": "https://gis.pendercountync.gov/arcgis/rest/services/Layers/MapServer/4/query",
        "addr_field": "PROPERTY_ADDRESS",
    },
    "New Hanover": {
        # Geometry + PID/PIN only on this layer (no owner/value/situs). Use it
        # for parcel-id + centroid; owner/value continue to resolve via the
        # county OneMap fallback elsewhere in the pipeline.
        "url": "https://gis.nhcgov.com/server/rest/services/Layers/IASTAX/MapServer/0/query",
        "addr_field": None,
    },
    # Dare is NOT ArcGIS — it's a GeoServer WFS. Handled by the WFS branch in
    # one() via NC_WFS below, not through this ArcGIS registry.
    #
    # Yancey: no public FeatureServer with parcel layer found as of 2026-06-15.
    # Yancey GIS is hosted at gis.yanceycountync.gov but exposes only static
    # map tiles. Skip until a queryable endpoint becomes available.
}


# ---- NC: GeoServer WFS counties (NOT ArcGIS REST) -------------------------------
#
# A handful of NC coastal counties publish parcels through an OGC WFS endpoint
# (GeoServer) rather than an ArcGIS FeatureServer. The query syntax differs:
# GetFeature + CQL_FILTER instead of ?where=. We model them separately and route
# to _wfs_query() in the resolver.
#
# Dare verified 2026-06-26: geometry field is "geom", native SRS EPSG:3857.
# Address-LIKE via CQL works and srsName=EPSG:4326 returns a WGS84 centroid for
# map markers. Point-intersect via INTERSECTS(geom, POINT(x y)) in 3857 also
# works (used for reverse-geocode when only lat/lng is known).

NC_WFS: dict[str, dict[str, Any]] = {
    "Dare": {
        "url": "https://gs.darecountync.gov/geoserver/Production/wfs",
        "type_names": "Production:tax_polygons24",
        "geom_field": "geom",
        "native_srid": 3857,
        "addr_field": "propertyaddress",
        # field map → Listing-facing concept; consumed by _apply_attrs via the
        # shared FIELD_ALIASES (own1/aprtot/sfla/yrblt/saleprice all added there).
    },
}


# ---- Field-name normalization ----------------------------------------------------

# Upper-plausibility ceiling for a parsed last-sale amount. Spartanburg's
# SaleAmount field returns uninitialized doubles (denormalized junk) like
# 1065353216 / ~1.2e9 for blank cells; without a cap these ship to the
# dashboard as billion-dollar "sales". No residential/parcel sale is anywhere
# near $50M here, so anything above the ceiling is garbage and is dropped.
# (Mirrors enrichment_gis_derived._MAX_SALE and validation.py's $50M guards.)
_MAX_PLAUSIBLE_SALE = 50_000_000.0

FIELD_ALIASES = {
    # NOTE: DEEDBK was historically in this list but it's the DEED BOOK number,
    # not a parcel identifier. Multiple parcels recorded in the same book all
    # get the same value, which then poisons the dedupe key. Removed.
    "parcel_id": ("PIN", "TMS", "REID", "PARCELNUMBER", "parno", "pinnum",
                  "MAPNUMBER", "pid", "PARID", "pid_long", "PARNO",
                  # Cleveland Basemap: GIS_PID == COUNTY_PID (the tax account no.)
                  "GIS_PID"),
    "owner_name": ("OwnerName", "OWNAM1", "Owner1", "PROPERTY_OWNER",
                   "full_owner_name", "owner", "ownname", "NAME1", "OWNER_NAME",
                   "Name1", "Name", "OWNER", "NAMECO",
                   # coastal NC: Onslow=OWNER1, Pender=NAME, Dare(WFS)=own1
                   "OWNER1", "NAME", "own1",
                   # Gaston county layer 11 = CURR_NAME1; Cleveland Basemap =
                   # COUNTY_OWNER_1, but GIS_Owner1 is the SAME name untruncated
                   # so it is listed first (see _repair_cleveland).
                   "GIS_Owner1", "CURR_NAME1", "COUNTY_OWNER_1",
                   # SC county-native (2026-08-12): Colleton=OwnerName1,
                   # Beaufort=GisFile_Owner1 (Spartanburg=OwnerName, Pickens=NAME1,
                   # Laurens=Name1 already covered above).
                   "OwnerName1", "GisFile_Owner1"),
    "mailing_addr": ("txt_mailaddr1", "MailAddr", "OWNER_MAIL_1", "mailadd",
                     "Mailing_Address", "OwnerMailingAddress",
                     # Gaston county layer 11 = CURR_ADDR1 (owner mailing, NOT
                     # the situs — PHYSSTRADD is the situs);
                     # Cleveland Basemap = COUNTY_MAILING_ADDRESS.
                     "CURR_ADDR1", "COUNTY_MAILING_ADDRESS"),
    "site_address": ("PropertyLocation", "siteadd", "Property_Address", "LocAddr",
                     "LOCATION_ADDR", "PHYS_ADDR", "PHYADDR",
                     "PHYSICAL_STREET_ADDRESS", "SITUS_ADDR", "ADDRESS_1",
                     "SitusAddre", "SitusAddress", "Situs_Addr", "SITUSADDR",
                     # coastal NC: Carteret=PropertyAddress, Onslow=PHYSICALADDRESS,
                     # Pender=PROPERTY_ADDRESS, Dare(WFS)=propertyaddress
                     "PropertyAddress", "PHYSICALADDRESS", "PROPERTY_ADDRESS",
                     "propertyaddress",
                     # Cleveland Basemap: LOCATE_ADDRESS is the untruncated
                     # situs, COUNTY_ADDRESS the 20-char-capped one.
                     "LOCATE_ADDRESS", "COUNTY_ADDRESS",
                     # SC county-native (2026-08-12): Pickens=LOCADD,
                     # Beaufort=GisFile_SitusAddre (pinned as addr_field but must
                     # also be readable back here).
                     "LOCADD", "GisFile_SitusAddre"),
    "acreage": ("Acreage", "ACRES", "gisacres", "ACREAGE", "LegalAc",
                "DEEDED_ACRES", "Acres", "ACRE", "Acres_Calc",
                # Gaston county layer 11 = CALCAC/DEEDAC; Cleveland = COUNTY_ACRES
                "CALCAC", "DEEDAC", "COUNTY_ACRES", "GIS_Calculated_Acres"),
    "year_built": ("taxYearBui", "AYB", "YearID", "structyear", "YEARBLT",
                   "YEAR_BUILT", "YearBuilt", "year_built", "EFFYR",
                   # coastal NC: Carteret=Y_BLT_HOUSE, Brunswick=ActualYearBuilt,
                   # Dare(WFS)=yrblt
                   "Y_BLT_HOUSE", "ActualYearBuilt", "yrblt"),
    "bedrooms": ("BEDROOMS", "BedRooms", "Bedrooms", "BEDS", "XBEDRM"),
    "bathrooms": ("BATHRMS", "BATHS", "Bathrooms", "FullBaths", "BathRoom",
                  "XBATHS"),
    "living_sqft": ("HEATED_SQ_", "SQFEET", "TotLiving", "TotalLiving", "BLDGSQFT",
                    "BUILDING_S", "HeatedSqFt", "BLDGSF",
                    # coastal NC: Carteret=HtdSqFt, Onslow=HEATEDSQUAREFEET,
                    # Pender=HEAT_SQ_FT, Dare(WFS)=sfla
                    "HtdSqFt", "HEATEDSQUAREFEET", "HEAT_SQ_FT", "sfla"),
    "tax_value": ("TAXMKTVAL", "FAIRMKTVAL", "MRKT_VALUE", "Total", "parval",
                  "presentval", "TotalVal", "TotalValue", "Tot_Val", "AppraisalValue",
                  "TOTAL_VAL",
                  # coastal NC: Onslow=TAXMARKETVALUE, Dare(WFS)=aprtot
                  "TAXMARKETVALUE", "aprtot",
                  # SC SCDOT: Pickens=ACTUALVAL, Charleston=APPRAISAL,
                  # Beaufort=Appraised, Laurens=Tota_Mark/Total_Val. (Anderson's
                  # MRKT_VALUE + Georgetown's Land/Imp sum are already covered.)
                  "ACTUALVAL", "APPRAISAL", "Appraised", "Tota_Mark", "Total_Val",
                  # Oconee=CURRENT_VA (total appraised, 560 leads value 3%->99%).
                  # NOT TOTALASMT — that's the annual assessed/levy figure, would corrupt ARV.
                  "CURRENT_VA",
                  # Gaston county layer 11 = FMV_TOTAL (TOTVAL is the same
                  # figure on the older city layer); Cleveland = COUNTY_TOTAL_VALUE.
                  "FMV_TOTAL", "TOTVAL", "COUNTY_TOTAL_VALUE",
                  # SC county-native (2026-08-12): Beaufort=GisFile_Appraised.
                  "GisFile_Appraised"),
    "deed_book": ("DEEDBK", "Deed_Book", "DEED_BK", "DeedBook", "DB",
                  # SC SCDOT: Charleston=DEED_BOOK_, Anderson=DBOOK,
                  # Beaufort=Book, Laurens=DEEDBOOK
                  "DEED_BOOK_", "DBOOK", "Book", "DEEDBOOK",
                  # Gaston county layer 11 = DEED_BOOK; Cleveland = COUNTY_DEED
                  "DEED_BOOK", "COUNTY_DEED",
                  "GisFile_Book"),  # SC Beaufort county-native (2026-08-12)
    "deed_page": ("DEEDPG", "Deed_Page", "PAGE", "DeedPage", "DP",
                  # SC SCDOT: Anderson=DPAGE, Beaufort=Page, Laurens=DEEDPAGE
                  "DPAGE", "Page", "DEEDPAGE",
                  # Gaston county layer 11 = DEED_PAGE; Cleveland = COUNTY_PAGE
                  "DEED_PAGE", "COUNTY_PAGE",
                  "GisFile_Page"),  # SC Beaufort county-native (2026-08-12)
    "sale_date": ("SaleDate", "SALEDATE", "DEED_YEAR", "SaleYear", "Sale_Year",
                  # SC SCDOT: Pickens=SALEDT (epoch ms), Charleston=RECORDED_D
                  # (epoch ms; DOC_DATE is the instrument date), Anderson=SALE_YEAR,
                  # Laurens=TransferDa. (Beaufort/Georgetown SaleDate already above.)
                  # Epoch-ms values stringify to a 13-digit value that
                  # valuation.amortize._as_date already parses.
                  "SALEDT", "RECORDED_D", "SALE_YEAR", "TransferDa"),
    "sale_amount": ("SaleAmount", "SALEAMT", "SalePrice", "Sale_Price",
                    # SC SCDOT: Pickens=SALEP, Charleston/Anderson=SALE_PRICE,
                    # Laurens=Considerat (True_Sale is a Y/N flag, not an amount).
                    # (Beaufort/Georgetown SalePrice already above.)
                    "SALEP", "SALE_PRICE", "Considerat",
                    # Gaston county layer 11
                    "SALESAMT"),
    "zoning": ("Zoning", "ZONING", "ZONE", "ZoneCode", "zone_code", "PRIM_ZONE"),
    "land_value": ("landval", "Land", "LANDVAL", "LandValue", "Land_Val",
                   "FMV_LAND", "COUNTY_LAND_VALUE"),
    "improvement_value": ("improvval", "Dwelling", "BLDG_VAL", "ImpValue",
                          "Improvement", "STRUCT_VAL",
                          "FMV_IMPRV", "COUNTY_BUILDING_VALUE"),
    "city": ("CITY", "City", "PROP_CITY", "MAIL_CITY"),
    "zip": ("ZIP", "Zip", "PROP_ZIP", "ZIPCODE", "ZipCode", "MAIL_ZIP"),
}


def _pick(attrs: dict[str, Any], candidates: tuple[str, ...]) -> Any:
    """Return the first non-empty value among a list of candidate keys (case-insensitive)."""
    if not isinstance(attrs, dict):
        return None
    norm = {k.lower(): v for k, v in attrs.items()}
    for cand in candidates:
        v = norm.get(cand.lower())
        if v not in (None, "", 0, "0", "<Null>"):
            return v
    return None


def _concat_fields(sentinel: str) -> tuple[str, ...]:
    """Parse a ``__concat:A+B+C__`` addr_field sentinel into its component fields."""
    inner = sentinel.split("__concat:", 1)[1].rstrip("_")
    return tuple(p for p in inner.split("+") if p)


def _stitch_situs(
    attrs: dict[str, Any], fields: tuple[str, ...] | None = None
) -> str | None:
    """Rebuild a full situs from component fields for layers with no single
    situs column.

    ``fields`` lists the component columns in address order; the FIRST is the
    house number (leading zeros stripped), and a component whose name contains
    'name' is required (that is the street). Defaults to Brunswick's layout
    (HouseNumber/StreetDirection/StreetName/StreetType); Georgetown passes
    (StreetNumber/StreetName). Join the non-empty, non-null parts in order.
    """
    if fields is None:
        fields = ("HouseNumber", "StreetDirection", "StreetName", "StreetType")
    parts: list[str] = []
    name_val = ""
    for i, fld in enumerate(fields):
        v = str(attrs.get(fld) or "").strip()
        if not v or v == "<Null>":
            continue
        if i == 0:
            v = v.lstrip("0")  # house number
        if "name" in fld.lower():
            name_val = v
        parts.append(v)
    if not name_val:
        return None
    return " ".join(parts)


def _repair_cleveland(attrs: dict[str, Any]) -> None:
    """Undo Cleveland's upstream 20-char CAMA truncation, in place.

    Cleveland's Basemap/Parcels layer joins a CAMA extract whose COUNTY_ADDRESS,
    COUNTY_OWNER_1 and COUNTY_MAILING_ADDRESS columns are hard-capped at 20
    characters. Measured over all 70,059 rows (2026-08-03): 9,032 / 23,539 /
    11,893 rows sit at exactly len 20 and not one row of any of the three
    exceeds it, which is the signature of a fixed-width cap rather than
    genuinely short values.

    Two of the three have an untruncated sibling column on the SAME layer:
      COUNTY_ADDRESS  -> LOCATE_ADDRESS (max len 34; recovers 6,011 of the 8,547
                         truncated-and-comparable rows, 70.3%)
      COUNTY_OWNER_1  -> GIS_Owner1     (max len 50; differs on 28,757 rows,
                         20,796 of which are longer than 20 chars)
    We take the sibling only when it is strictly LONGER, so a blank or
    abbreviated sibling can never downgrade a good value.

    COUNTY_MAILING_ADDRESS has NO untruncated sibling anywhere on this service —
    17.1% of mailing street lines stay clipped. COUNTY_CITY/STATE/ZIP are not
    truncated (max 15/2/10), so the mail piece still routes; it is the street
    line that may be short. That is a genuine upstream wall, not a bug here.
    """
    def _better(dst: str, src: str) -> None:
        cur = str(attrs.get(dst) or "").strip()
        alt = str(attrs.get(src) or "").strip()
        if alt and alt != "<Null>" and len(alt) > len(cur):
            attrs[dst] = alt

    _better("COUNTY_ADDRESS", "LOCATE_ADDRESS")
    _better("COUNTY_OWNER_1", "GIS_Owner1")
    _better("COUNTY_OWNER_2", "GIS_Owner2")


def _cohort_flags(attrs: dict[str, Any]) -> dict[str, bool]:
    """Derive the vacant / absentee / owner-changed cohorts from a parcel row.

    Verified live against Gaston's 117,565-row layer with returnCountOnly
    (2026-08-03):
        vacant                     VacantImpro='Vacant'          21,380
        absentee                   CURR_STATE not in ('NC','')   10,340
        vacant AND absentee                                       2,962
        owner changed this year    PRVYRNAME1 <> CURR_NAME1       4,764

    Only emitted when the underlying column is actually present, so a county
    without the column gets no flag rather than a false negative. `absentee`
    deliberately excludes the 43 blank-state rows: a blank mailing state is
    unknown, not out-of-state. (Counting blanks as absentee is what turns the
    verified 10,340 into 10,383 / the 2,962 both-cohort into 2,997.)
    """
    out: dict[str, bool] = {}

    vac = attrs.get("VacantImpro")
    if vac not in (None, "", "<Null>"):
        out["vacant"] = str(vac).strip().upper() == "VACANT"

    state = attrs.get("CURR_STATE")
    if state is not None:
        st = str(state).strip().upper()
        if st and st != "<NULL>":
            out["absentee"] = st != "NC"

    prev = str(attrs.get("PRVYRNAME1") or "").strip()
    curr = str(attrs.get("CURR_NAME1") or "").strip()
    if prev and curr:
        out["owner_changed"] = prev.upper() != curr.upper()

    return out


def _street_keywords(street: str) -> str:
    """Pull the most distinctive token from an address for LIKE matching."""
    # Drop leading number + directional + suffix; pick longest remaining word.
    s = re.sub(r"^\d+\s*", "", street)
    s = re.sub(
        r"\b(N|S|E|W|NE|NW|SE|SW|North|South|East|West|"
        r"St|Street|Rd|Road|Ave|Avenue|Dr|Drive|Ln|Lane|"
        r"Ct|Court|Blvd|Boulevard|Hwy|Highway|Pl|Place|Way|Trl|Trail|"
        r"Pkwy|Parkway|Cir|Circle|Terr|Terrace|Hl|Hill)\b\.?",
        "",
        s,
        flags=re.I,
    )
    tokens = [t.strip(".,#") for t in s.split() if len(t) > 2]
    return max(tokens, key=len, default=s.strip())


# ---- Core query ------------------------------------------------------------------

_FIELD_CACHE: dict[str, list[str]] = {}

# Address-like field name candidates (in priority order). PHYSICAL/SITUS fields
# come FIRST so a layer that also exposes an owner-mailing field (e.g. Gaston's
# CURR_ADDR1 = out-of-state owner mailing) never wins the situs slot — we want
# the property's physical address, not where the (often absentee) owner gets mail.
_ADDR_FIELD_CANDIDATES = (
    # explicit physical-situs fields, highest priority
    "PHYSSTRADD", "PHYSADDR", "PHYS_ADDR", "PHYADDR", "PHYSICAL_STREET_ADDRESS",
    "SITE_ADDR", "SITE_ADDRESS", "Site_Address", "siteadd", "SITUS", "SITUS_ADDR",
    "situsaddress1", "PrimarySitusAddress", "SitusAddress", "LOCADD", "LOCADDR",
    "LOCATION_ADDR", "LocAddr",
    # generic property-address fields
    "PROPADDR", "PROPERTY_ADDRESS", "PropertyLocation", "Property_Address",
    "PROP_LOC", "PROP_ADDR", "txt_propaddr", "FULLADDR",
    # last-resort generic street fields (a mailing field could share these, so
    # they rank below every situs field above)
    "ADDRESS_1", "ADDRESS", "ADDR", "STREET_ADDR", "STREET", "StreetAddress",
    "MailAddr",
)

# Substrings that mark a field as an OWNER-MAILING address (never a situs).
_MAILING_FIELD_MARKERS = ("mail", "owner", "curr_addr", "curraddr", "jan1",
                          "ownaddr", "own_addr", "taxaddr", "tax_addr")


async def _detect_addr_field(c: httpx.AsyncClient, base_url: str) -> str | None:
    """Hit the layer's ?f=json once, find the most likely address field."""
    if base_url in _FIELD_CACHE:
        fields = _FIELD_CACHE[base_url]
    else:
        layer_url = base_url.rsplit("/query", 1)[0]
        try:
            r = await c.get(layer_url, params={"f": "json"}, timeout=15.0)
            if r.status_code != 200:
                return None
            data = r.json()
            fields = [f["name"] for f in data.get("fields", []) if "name" in f]
            _FIELD_CACHE[base_url] = fields
        except (httpx.HTTPError, ValueError):
            return None
    # Match against known candidates (case-insensitive). A candidate that is an
    # owner-mailing field on THIS layer is skipped so situs always wins.
    field_lower = {f.lower(): f for f in fields}
    for cand in _ADDR_FIELD_CANDIDATES:
        cl = cand.lower()
        if cl in field_lower and not any(m in cl for m in _MAILING_FIELD_MARKERS):
            return field_lower[cl]
    # Fallback: any addr/street/situs field that is NOT an owner-mailing field.
    for f in fields:
        flow = f.lower()
        if ("addr" in flow or "street" in flow or "situs" in flow) and \
                not any(m in flow for m in _MAILING_FIELD_MARKERS):
            return f
    return None


async def _arcgis_query(
    c: httpx.AsyncClient,
    base_url: str,
    addr_field: str | None,
    street: str,
    house_no: str | None = None,
    out_fields: str = "*",
) -> list[dict[str, Any]]:
    """Run an address LIKE query, auto-detecting the address field if needed.

    Returns list of dicts with both 'attributes' and a derived '_centroid' (lat,lng)
    when geometry is available.

    `out_fields` defaults to "*" for the counties whose alias coverage depends on
    pulling whatever the layer happens to expose. Counties wired with an explicit
    column list pass it here so the request names exactly the fields we consume —
    that is the standing safeguard against a county quietly publishing a
    sensitive column (Lincoln NC has historically exposed TCSSN1/TCSSN2 on a
    public layer) and having it land in li.raw via a blanket "*".
    """
    # Some layers have no single situs column (Brunswick, Georgetown). Match on
    # the street-name component only and rebuild the full situs from the parsed
    # component fields on read.
    concat_situs = isinstance(addr_field, str) and addr_field.startswith("__concat:")
    concat_fields: tuple[str, ...] = ()
    if concat_situs:
        concat_fields = _concat_fields(addr_field)
        addr_field = next(
            (f for f in concat_fields if "name" in f.lower()), concat_fields[-1]
        )

    if not addr_field:
        addr_field = await _detect_addr_field(c, base_url)
    if not addr_field:
        return []

    keyword = _street_keywords(street)
    if not keyword:
        return []
    patterns = []
    if house_no and not concat_situs:
        patterns.append(f"%{house_no}%{keyword}%")
    patterns.append(f"%{keyword}%")

    for pat in patterns:
        where = f"UPPER({addr_field}) LIKE UPPER('{pat.replace(chr(39), chr(39)+chr(39))}')"
        params = {
            "where": where,
            "outFields": out_fields,
            "returnGeometry": "true",          # need centroid for map markers
            "outSR": "4326",                    # request WGS84 lat/lng directly
            "resultRecordCount": "8",
            "f": "json",
        }
        try:
            r = await c.get(base_url, params=params, timeout=20.0)
            if r.status_code != 200:
                continue
            data = r.json()
            if "error" in data:
                continue
            out: list[dict[str, Any]] = []
            for f in data.get("features", []):
                attrs = dict(f.get("attributes", {}) or {})
                # Rebuild Brunswick's situs from its component fields and stash it
                # under a real situs key so _pick(site_address) resolves it.
                if concat_situs:
                    situs = _stitch_situs(attrs, concat_fields)
                    if situs:
                        attrs["SITUS_ADDR"] = situs
                # Cleveland ships a 20-char-truncated CAMA join; swap in the
                # untruncated sibling columns before any alias reads them.
                if "COUNTY_ADDRESS" in attrs or "COUNTY_OWNER_1" in attrs:
                    _repair_cleveland(attrs)
                # Centroid from polygon rings or point geometry
                geom = f.get("geometry") or {}
                cx = cy = None
                if "x" in geom and "y" in geom:
                    cx, cy = geom["x"], geom["y"]
                elif geom.get("rings"):
                    pts = [p for ring in geom["rings"] for p in ring]
                    if pts:
                        cx = sum(p[0] for p in pts) / len(pts)
                        cy = sum(p[1] for p in pts) / len(pts)
                if cx is not None and cy is not None:
                    attrs["_centroid"] = (cy, cx)  # (lat, lng) — outSR=4326 returns lng,lat
                out.append(attrs)
            if out:
                return out
        except (httpx.HTTPError, ValueError):
            continue
    return []


def _cql_escape(s: str) -> str:
    """Escape a literal for an OGC CQL string (single-quote doubling)."""
    return s.replace("'", "''")


async def _wfs_query(
    c: httpx.AsyncClient,
    cfg: dict[str, Any],
    street: str,
    house_no: str | None = None,
) -> list[dict[str, Any]]:
    """Query a GeoServer WFS county (e.g. Dare) by address.

    Uses GetFeature + CQL_FILTER LIKE on the configured addr_field and requests
    srsName=EPSG:4326 so geometry comes back as WGS84 we can centroid for markers.
    Returns the same attrs+_centroid dict shape as _arcgis_query so _apply_attrs
    works unchanged.
    """
    addr_field = cfg["addr_field"]
    keyword = _street_keywords(street)
    if not keyword:
        return []

    patterns = []
    if house_no:
        patterns.append(f"%{house_no}%{keyword}%")
    patterns.append(f"%{keyword}%")

    for pat in patterns:
        cql = f"{addr_field} LIKE '{_cql_escape(pat)}'"
        params = {
            "service": "WFS",
            "version": "2.0.0",
            "request": "GetFeature",
            "typeNames": cfg["type_names"],
            "outputFormat": "application/json",
            "srsName": "EPSG:4326",     # WGS84 lat/lng for map markers
            "CQL_FILTER": cql,
            "count": "8",
        }
        try:
            r = await c.get(cfg["url"], params=params, timeout=30.0)
            if r.status_code != 200:
                continue
            data = r.json()
            out: list[dict[str, Any]] = []
            for f in data.get("features", []):
                attrs = dict(f.get("properties", {}) or {})
                geom = f.get("geometry") or {}
                centroid = _geojson_centroid(geom)
                if centroid:
                    attrs["_centroid"] = centroid  # (lat, lng)
                out.append(attrs)
            if out:
                return out
        except (httpx.HTTPError, ValueError):
            continue
    return []


def _geojson_centroid(geom: dict[str, Any]) -> tuple[float, float] | None:
    """Average all vertices of a GeoJSON geometry → (lat, lng) in WGS84.

    GeoJSON coordinate order is [lng, lat]; we return (lat, lng) to match the
    convention enrichment_geocode / _apply_attrs expect.
    """
    if not geom:
        return None
    coords = geom.get("coordinates")
    if coords is None:
        if "x" in geom and "y" in geom:
            return (geom["y"], geom["x"])
        return None
    xs: list[float] = []
    ys: list[float] = []

    def walk(node: Any) -> None:
        if (
            isinstance(node, (list, tuple))
            and len(node) >= 2
            and isinstance(node[0], (int, float))
            and isinstance(node[1], (int, float))
        ):
            xs.append(float(node[0]))
            ys.append(float(node[1]))
        elif isinstance(node, (list, tuple)):
            for sub in node:
                walk(sub)

    walk(coords)
    if not xs:
        return None
    return (sum(ys) / len(ys), sum(xs) / len(xs))


def _apply_attrs(li: Listing, attrs: dict[str, Any]) -> int:
    """Apply ArcGIS attributes to a Listing without overwriting good data.
    Returns number of fields newly populated."""
    filled = 0

    def maybe(field: str, val: Any) -> None:
        nonlocal filled
        if val in (None, "", 0, "0"):
            return
        cur = getattr(li, field, None)
        if cur in (None, "", 0):
            setattr(li, field, val)
            filled += 1

    # Coordinates (centroid of parcel polygon if we got geometry). Write the
    # precise parcel centroid when lat/lng is empty OR when the current point is a
    # COARSE county-seat centroid stamped by enrichment_geocode's Tier-4 fallback
    # (one courthouse coord shared by hundreds of leads). Without this override,
    # ~1079 parcel-bearing leads (sc_tax_delinquent / sc_rod_acclaim) keep the
    # shared seat coordinate, and enrichment_images refuses to attach an aerial on
    # a shared centroid — capping photo coverage. Never overwrite a precise point.
    centroid = attrs.get("_centroid")
    if centroid:
        try:
            new_lat, new_lng = float(centroid[0]), float(centroid[1])
        except (ValueError, TypeError):
            new_lat = None
        if new_lat is not None:
            from .enrichment_geocode import COUNTY_SEAT_CENTROIDS
            _seats = {(round(a, 3), round(b, 3)) for a, b in COUNTY_SEAT_CENTROIDS.values()}
            is_empty = not li.latitude and not li.longitude
            is_coarse_seat = bool(li.latitude and li.longitude) and \
                (round(li.latitude, 3), round(li.longitude, 3)) in _seats
            if is_empty or is_coarse_seat:
                li.latitude, li.longitude = new_lat, new_lng
                filled += 2

    # Only write parcel_id when we're confident in the address match. A wrong
    # parcel_id silently corrupts the dedupe key (which prefers parcel over
    # address) and can cause unrelated listings to merge.
    if attrs.get("_match_confident"):
        parcel_id = _pick(attrs, FIELD_ALIASES["parcel_id"])
        if parcel_id:
            pid = str(parcel_id).strip()
            # Reject obviously-wrong values (single digits, deed-book-style
            # 4-digit ints, etc.) — real APNs have meaningful structure.
            if len(pid) >= 5 and not pid.isspace():
                maybe("parcel_id", pid)

    if not li.zoning:
        z = _pick(attrs, FIELD_ALIASES["zoning"])
        if z:
            maybe("zoning", str(z).strip())

    if not li.acreage:
        ac = _pick(attrs, FIELD_ALIASES["acreage"])
        if ac:
            try:
                maybe("acreage", float(ac))
            except (ValueError, TypeError):
                pass

    if not li.year_built:
        yb = _pick(attrs, FIELD_ALIASES["year_built"])
        if yb:
            try:
                yb_int = int(str(yb)[:4])
                if 1800 < yb_int < 2030:
                    maybe("year_built", yb_int)
            except (ValueError, TypeError):
                pass

    if not li.bedrooms:
        b = _pick(attrs, FIELD_ALIASES["bedrooms"])
        if b:
            try:
                maybe("bedrooms", float(b))
            except (ValueError, TypeError):
                pass

    if not li.bathrooms:
        b = _pick(attrs, FIELD_ALIASES["bathrooms"])
        if b:
            try:
                maybe("bathrooms", float(b))
            except (ValueError, TypeError):
                pass

    if not li.living_sqft:
        s = _pick(attrs, FIELD_ALIASES["living_sqft"])
        if s:
            try:
                maybe("living_sqft", float(s))
            except (ValueError, TypeError):
                pass

    if not li.tax_value:
        # Prefer total; fall back to land + improvement sum
        tv = _pick(attrs, FIELD_ALIASES["tax_value"])
        if not tv:
            land = _pick(attrs, FIELD_ALIASES["land_value"]) or 0
            imp = _pick(attrs, FIELD_ALIASES["improvement_value"]) or 0
            try:
                tv = float(land) + float(imp)
            except (ValueError, TypeError):
                tv = None
        if tv:
            try:
                maybe("tax_value", float(tv))
            except (ValueError, TypeError):
                pass

    # Owner / mailing → carried in raw for now (we don't have first-class fields)
    owner = _pick(attrs, FIELD_ALIASES["owner_name"])
    mailing = _pick(attrs, FIELD_ALIASES["mailing_addr"])
    if owner or mailing:
        gis = li.raw.setdefault("gis", {})
        if owner and not gis.get("owner"):
            gis["owner"] = str(owner).strip()
            filled += 1
        if mailing and not gis.get("mailing"):
            gis["mailing"] = str(mailing).strip()
            filled += 1

    # Vacant / absentee / owner-changed cohorts. These are lead SIGNALS, not
    # descriptive attributes, so they're written even when the parcel match was
    # not confident enough for parcel_id — a wrong flag costs an operator one
    # look, a wrong parcel_id corrupts the dedupe key.
    flags = _cohort_flags(attrs)
    if flags:
        gis = li.raw.setdefault("gis", {})
        for k, v in flags.items():
            if k not in gis:
                gis[k] = v
                filled += 1

    # Recorded deed/book/page + last sale info
    deed_b = _pick(attrs, FIELD_ALIASES["deed_book"])
    deed_p = _pick(attrs, FIELD_ALIASES["deed_page"])
    sale_d = _pick(attrs, FIELD_ALIASES["sale_date"])
    sale_a = _pick(attrs, FIELD_ALIASES["sale_amount"])
    if deed_b or deed_p or sale_d or sale_a:
        gis = li.raw.setdefault("gis", {})
        gis.setdefault("last_sale", {})
        if deed_b:
            gis["last_sale"]["book"] = str(deed_b)
        if deed_p:
            gis["last_sale"]["page"] = str(deed_p)
        if sale_d:
            gis["last_sale"]["date"] = str(sale_d)
        if sale_a:
            try:
                # Some SC layers store the amount as a formatted string with
                # thousands separators / a currency symbol (e.g. Laurens
                # Considerat = '80,000'); strip those before float().
                if isinstance(sale_a, str):
                    sale_a = re.sub(r"[^\d.\-]", "", sale_a)
                if sale_a not in ("", "-", "."):
                    amt = float(sale_a)
                    # Reject corrupted GIS values (e.g. Spartanburg's
                    # uninitialized-double junk in the ~$1.07B-$1.27B band)
                    # so they never reach the published dashboard.
                    if 0 < amt <= _MAX_PLAUSIBLE_SALE:
                        gis["last_sale"]["amount"] = amt
            except (ValueError, TypeError):
                pass

    return filled


# ---- Public API ------------------------------------------------------------------

async def enrich(listings: list[Listing], concurrency: int = 8) -> list[Listing]:
    """Fill missing fields on each listing by hitting the appropriate county GIS REST.

    Pure HTTP, free, fast. Handles SC via SCDOT shared service + NC per-county.
    """
    sem = asyncio.Semaphore(concurrency)
    counts = {"queried": 0, "matched": 0, "fields_filled": 0}

    async def one(c: httpx.AsyncClient, li: Listing) -> None:
        if not (li.street_address and li.county and li.state):
            return
        # PARCEL-CACHE fast path — this phase's dominant cost is one live address query
        # PER LEAD across ~48k address-having leads (it ran ~6.8h uncapped on 2026-08-14).
        # When a lead already carries a parcel_id in a bulk-cached county, fill owner/value/
        # sqft/acre from the local table and skip the network entirely. Only short-circuits
        # when owner or value is still missing (else fall through to refresh minor fields).
        if li.parcel_id and not (li.owner_name and li.market_value):
            try:
                from .parcel_cache import lookup as _pc_lookup
                pcr = _pc_lookup(li.county or "", li.parcel_id)
            except Exception:  # noqa: BLE001 — cache is best-effort; never break the phase
                pcr = None
            if pcr:
                if not li.owner_name and pcr.get("owner"):
                    li.owner_name = pcr["owner"]
                if not li.market_value and pcr.get("market_value"):
                    li.market_value = pcr["market_value"]
                if not li.tax_value and pcr.get("tax_value"):
                    li.tax_value = pcr["tax_value"]
                if not li.living_sqft and pcr.get("living_sqft"):
                    li.living_sqft = pcr["living_sqft"]
                if not li.acreage and pcr.get("acreage"):
                    li.acreage = pcr["acreage"]
                counts["cache_hit"] = counts.get("cache_hit", 0) + 1
                return
        # Normalize county: strip "County", trailing ", NC" or ", SC", whitespace
        county_clean = li.county.replace(" County", "").strip()
        for suffix in (", NC", ", SC", ",NC", ",SC"):
            if county_clean.upper().endswith(suffix):
                county_clean = county_clean[: -len(suffix)].strip()
        county_clean = county_clean.split(",")[0].strip()

        # Extract house number for tighter match
        m = re.match(r"^\s*(\d+)", li.street_address)
        house_no = m.group(1) if m else None

        # GeoServer WFS counties (Dare) use a different query path entirely.
        wfs_cfg = NC_WFS.get(county_clean) if li.state == "NC" else None
        if wfs_cfg:
            async with sem:
                counts["queried"] += 1
                results = await _wfs_query(c, wfs_cfg, li.street_address, house_no)
                if not results:
                    return
                counts["matched"] += 1
                best = results[0]
                confident = len(results) == 1
                if house_no:
                    for r in results:
                        if str(_pick(r, ("adrno", "ADRNO", "HouseNumber"))).strip().lstrip("0") == house_no:
                            best = r
                            confident = True
                            break
                best["_match_confident"] = confident
                counts["fields_filled"] += _apply_attrs(li, best)
            return

        out_fields = "*"
        if li.state == "SC":
            # SCDOT SC_Parcels is token-walled (2026-08-12); resolve against the
            # county-native SC_GIS endpoints instead. Same {url, addr_field} shape
            # as NC_GIS: addr_field=None auto-detects situs, a pinned string is the
            # situs column to LIKE-match (Beaufort's GisFile_-prefixed layer).
            cfg = SC_GIS.get(county_clean)
            if not cfg:
                return
            base = cfg["url"]
            out_fields = cfg.get("out_fields") or "*"
            addr_field = cfg.get("addr_field")  # None -> auto-detect
        elif li.state == "NC":
            cfg = NC_GIS.get(county_clean)
            if not cfg:
                return
            base = cfg["url"]
            out_fields = cfg.get("out_fields") or "*"
            cfg_addr = cfg.get("addr_field")
            if isinstance(cfg_addr, str) and cfg_addr.startswith("__concat:"):
                # Concat sentinel — auto-detect can't reconstruct it.
                addr_field = cfg_addr
            elif cfg_addr is None:
                # addr_field=None is the documented "this layer has NO situs
                # column" marker. It used to fall through to _detect_addr_field
                # anyway, which is how Transylvania ended up LIKE-matching the
                # property street against ADDRESS_1 — a field that holds the
                # SECOND OWNER'S NAME on that layer. There is nothing correct to
                # match on here, and a bad match writes a wrong parcel_id into
                # the dedupe key, so skip the county's address path entirely.
                #
                # 2026-08-18: fall back to NC OneMap statewide parcel service
                # for situs. OneMap exposes siteadd (situs) for all 100 NC
                # counties — counties like Rutherford, Transylvania, and New
                # Hanover whose own ArcGIS layer has no situs column can still
                # resolve a street address via OneMap's parcel match.
                if li.street_address and li.parcel_id:
                    onemap_url = (
                        "https://services.nconemap.gov/secure/rest/services/"
                        "NC1Map_Parcels/FeatureServer/1/query"
                    )
                    async with sem:
                        counts["queried"] += 1
                        # Try parcel_id match first (most reliable)
                        pid = li.parcel_id.replace("'", "''")
                        # OneMap requires exact parno match — LIKE queries return 500
                        where = f"parno='{pid}'"
                        params = {
                            "where": where,
                            "outFields": "parno,siteadd,ownname,ownname2,cntyname",
                            "returnGeometry": "true",
                            "outSR": "4326",
                            "resultRecordCount": "5",
                            "f": "json",
                        }
                        try:
                            r = await c.get(onemap_url, params=params, timeout=20.0)
                            if r.status_code == 200:
                                data = r.json()
                                if "error" not in data:
                                    feats = data.get("features", [])
                                    if feats:
                                        attrs = dict(feats[0].get("attributes", {}))
                                        situs = str(attrs.get("siteadd") or "").strip()
                                        if situs:
                                            li.street_address = situs
                                            counts["matched"] += 1
                                            counts["fields_filled"] += 1
                                            return
                        except Exception:
                            pass
                return
            else:
                # Auto-detect (robust against schema drift); the configured
                # string documents what we expect it to land on.
                addr_field = None
        else:
            return

        async with sem:
            counts["queried"] += 1
            results = await _arcgis_query(c, base, addr_field, li.street_address,
                                          house_no, out_fields=out_fields)
            if not results:
                return
            counts["matched"] += 1
            # Pick the best-looking record (one with the most matching house_no)
            best = results[0]
            confident = len(results) == 1  # single hit = fairly confident
            if house_no:
                for r in results:
                    if str(_pick(r, ("STRNUM", "HouseNumber", "ADDRNO", "house_num"))).strip() == house_no:
                        best = r
                        confident = True  # house_no matched explicitly
                        break
            # Stash confidence on the chosen result so _apply_attrs can be picky
            # about which fields to write. Specifically: parcel_id only when
            # confident, since a wrong parcel_id corrupts the dedupe key.
            best["_match_confident"] = confident
            counts["fields_filled"] += _apply_attrs(li, best)

    async with client(timeout=20.0) as c:
        await asyncio.gather(*(one(c, li) for li in listings))

    log.info("enrichment.gis.done", **counts)
    return listings
