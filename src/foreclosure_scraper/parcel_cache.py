"""Local parcel-layer cache — bulk-download each county's parcel layer ONCE into a
local SQLite table, then enrich board leads by an in-memory JOIN instead of a
per-lead live GIS query. Turns the multi-hour GIS/resolver phase into seconds.

PROVEN 2026-08-14 (Buncombe): 135,180 parcels downloaded in 80s -> 13.5 MB SQLite ->
6,632 board leads joined in 42 ms (vs ~2.7 h of live per-lead queries every run).

Design:
- `PARCEL_LAYERS[county]` = the county's EXACT parcel-layer /query endpoint + the
  join id field + a field map to our schema. Adding a county = one verified line.
  (Only OPEN ArcGIS counties — SCDOT-token / qPublic / Cott counties can't bulk-export.)
- `refresh_county()` paginates the whole layer and VERIFIES completeness
  (downloaded == server returnCountOnly) before replacing the cache file in place —
  so a truncated download is flagged, never silently accepted. Overwrite-in-place =
  constant disk (~10-15 MB/county, ~200-400 MB all counties, no growth, no cleanup).
- `lookup(county, parcel_id)` reads the local table (indexed on a normalized id).
- Refresh weekly (parcels are slow-moving); runs just READ the cache.
"""
from __future__ import annotations

import json
from urllib.parse import quote
import re
import sqlite3
import time
from pathlib import Path
from typing import Optional

import structlog

log = structlog.get_logger()

CACHE_DIR = Path(__file__).resolve().parent.parent.parent / "data" / "parcel_cache"
_PAGE = 2000

# county -> {url: full .../query endpoint, id: source id field, map: {our_field: src_field}}
# Only counties VERIFIED (count-match + sample join). Extend one line at a time.
PARCEL_LAYERS: dict[str, dict] = {
    "Buncombe": {
        "url": "https://gis.buncombecounty.org/arcgis/rest/services/property_bc_dis/MapServer/1/query",
        # board ids are the 15-digit PIN (pinnum); index pin (10-digit) too for robustness.
        "id_fields": ["pinnum", "pin"],
        "map": {"owner": "owner", "address": "Address", "market_value": "TotalMarketValue",
                "tax_value": "TaxValue", "acreage": "Acreage",
                "sale_price": "SalePrice"},
    },
    # --- NC core footprint (each id_field + field map VERIFIED against a live sample 2026-08-14) ---
    "Rutherford": {  # board parcel_id = the 6-7 digit internal Parcel_Number (NOT the 10-digit PIN)
        "url": "https://gis.rutherfordcountync.gov/arcgis/rest/services/TaxParcels/MapServer/0/query",
        "id_fields": ["Parcel_Number"],
        "map": {"owner": "Property_Owner", "address": "Physical_Address",
                "market_value": "Total_Property_Value", "tax_value": "Total_Land_Value_Assessed",
                "acreage": "Acreage", "living_sqft": "Heated_Area",  # Heated_Area = vision-gate sqft
                "land_use": "Land_Class",
                "owner_mailing": ["Owner_Mailing_Address_1", "Owner_Mailing_Address_2", "Owner_Mailing_Address_3", "Owner_Mailing_Address_City"],
                "sale_price": "Sale_Price"},
    },
    "Lincoln": {  # 10-digit PIN; situs is split across STREETNUM + STREETNAME
        "url": "https://arcgisserver.lincolncountync.gov/arcgis/rest/services/Server_TaxParcelViewerSP/MapServer/0/query",
        # leads with addresses carry the 10-digit PIN; address-less leads carry the internal PARCELID
        "id_fields": ["PIN", "PARCELID"],
        "map": {"owner": "NAME1", "address": ["STREETNUM", "STREETNAME"],
                "market_value": "TOTALVALUE", "acreage": "ACRE", "living_sqft": "MAINAREASQFT",
                "sale_price": "SALEPRICE"},
    },
    "Henderson": {  # 10-digit PIN
        "url": "https://gisweb.hendersoncountync.gov/arcgis/rest/services/Parcels/FeatureServer/0/query",
        "id_fields": ["PIN", "PARCEL_PK"],   # address-less leads carry the internal PARCEL_PK
        "map": {"owner": "PROPERTY_OWNER", "address": "LOCATION_ADDR",
                "market_value": "TOTAL_PROP_VALUE", "acreage": "ACREAGE", "living_sqft": "HEATED_AREA",
                "land_use": "LAND_CLASS",
                "owner_mailing": ["OWNER_MAIL_1", "OWNER_MAIL_2", "OWNER_MAIL_3", "OWNER_MAIL_CITY"],
                "sale_price": "PKG_SALE_PRICE"},
    },
    "Burke": {  # 10-digit PIN
        "url": "https://gis.burkenc.org/arcgis/rest/services/ProdParcelViewFC/MapServer/0/query",
        "id_fields": ["PIN"],
        "map": {"owner": "PROPERTY_OWNER", "address": "LOCATION_ADDR",
                "market_value": "TOTAL_PROP_VALUE", "acreage": "ACREAGE", "living_sqft": "HEATED_AREA",
                "land_use": "LAND_CLASS",
                "owner_mailing": ["OWNER_MAIL_1", "OWNER_MAIL_2", "OWNER_MAIL_3", "OWNER_MAIL_CITY"],
                "sale_price": "PKG_SALE_PRICE"},
    },
    "McDowell": {  # 12-digit parno/altparno
        "url": "https://services9.arcgis.com/ETP7IuCigkUz7iI9/arcgis/rest/services/McDowell_Parcels/FeatureServer/0/query",
        "id_fields": ["parno", "altparno"],
        "map": {"owner": "ownname", "address": "siteadd", "market_value": "parval",
                "tax_value": "landval", "acreage": "gisacres",
                "owner_mailing": "mailadd"},
    },
    "Cleveland": {  # internal 5-digit PID appears as COUNTY_PID/GIS_PID/LOCATE_PID
        "url": "https://gis.clevelandcounty.com/arcgis/rest/services/Basemap/Parcels/MapServer/0/query",
        "id_fields": ["COUNTY_PID", "GIS_PID", "LOCATE_PID"],
        "map": {"owner": "COUNTY_OWNER_1", "address": "LOCATE_ADDRESS",
                "market_value": "COUNTY_TOTAL_VALUE", "acreage": "COUNTY_ACRES",
                "owner_mailing": "COUNTY_MAILING_ADDRESS"},
    },
    # --- SC ---
    "Spartanburg": {  # board 12-digit id = GISParcelNumber (7102-28-3341.88) with punctuation
        # stripped; _norm_id strips it on both sides. CAMA layer has clean situs (StreetAddress).
        # No single total-appraised field (land+bldg are separate) so value stays on the live path.
        "url": "https://maps.spartanburgcounty.org/server/rest/services/GIS/CAMA_Parcels/FeatureServer/0/query",
        "id_fields": ["GISParcelNumber", "PARCELNUMBER"],
        "map": {"owner": "OwnerName", "address": "StreetAddress", "acreage": "Acreage",
                "land_use": "LandUse"},
    },
    "Laurens": {  # TMS (dash format); layer has situs but no value field
        "url": "https://laurenscountygis.org/arcgis/rest/services/Pebble/TaxParcel/MapServer/5/query",
        "id_fields": ["TMS"],
        "map": {"owner": "Owner", "address": "Property_Address", "acreage": "Acres",
                "owner_mailing": ["Mailing_Address", "Mailing_City_State_ZIP"],
                "sale_price": "Sale_Price"},
    },
    # --- 2026-08-30 backbone additions (field maps probed live, valid certs) ---
    "Pickens": {  # SC dashed PIN e.g. "4037-00-34-5506"; open FeatureServer layer 6 (66k parcels)
        "url": "https://services1.arcgis.com/59960rq18IxUcAVI/arcgis/rest/services/Pickens_Open_data/FeatureServer/6/query",
        "id_fields": ["PIN", "ACCTNO"],   # ACCTNO = tax account (e.g. "R0084565")
        "map": {"owner": "NAME1", "address": "LOCADD", "acreage": "ACRES"},  # no total-value field on this layer
    },
    "Gaston": {  # PIN = dashed 10-digit; PID = numeric account; 117k parcels
        "url": "https://gis.gastoncountync.gov/publicgis/rest/services/PublicGIS/Parcels/MapServer/11/query",
        "id_fields": ["PIN", "PID"],
        # FMV_TOTAL (not TOTVAL — reads 0 on exempt parcels); CALCAC (not DEEDAC)
        "map": {"owner": "JAN1_NAME1", "address": "WHOLE_ADDRESS", "market_value": "FMV_TOTAL", "acreage": "CALCAC"},
    },
    "Polk": {  # TMS map-page format e.g. "P92-42"; 17k parcels
        "url": "https://services1.arcgis.com/23uf7jKvz6SRPFWJ/arcgis/rest/services/Parcel_view/FeatureServer/0/query",
        "id_fields": ["TMS"],
        "map": {"owner": "OWNAM1", "address": "PHYSICAL_STREET_ADDRESS",
                "market_value": "TOTAL_TAX_VALUE", "acreage": "DEEDED_ACRES"},
    },
    # Oconee (arcserver2.oconeesc.com) is intentionally NOT cached: its ArcGIS server
    # rejects bulk paginated export (returns 0 rows to resultOffset queries, though a
    # single-row query works), and the layer carries no situs street field anyway — so
    # it stays on the live/qPublic path. Revisit if the county exposes a bulk endpoint.
    "Transylvania": {  # dash-PIN; ADDRESS_1/3 are owner mailing, so owner+value+acre only
        "url": "https://gis.transylvaniacounty.org/server/rest/services/Parcels/MapServer/2/query",
        "id_fields": ["PIN"],
        "map": {"owner": "OWNER_NAME", "market_value": "ASSESSED_V", "acreage": "ACRES",
                "living_sqft": "HEATED_SQ_",
                "sale_price": "SALE_PRICE"},
    },
    # --- 2026-08-18: 4 more counties added (verified live, bulk-exportable) ---
    "Gaston": {  # 117,571 parcels; PIN (dash format) or AKPAR (internal int)
        "url": "https://gis.gastoncountync.gov/publicgis/rest/services/PublicGIS/Parcels/FeatureServer/11/query",
        "id_fields": ["PIN", "AKPAR", "PID"],
        "map": {"owner": "CURR_NAME1", "address": "PHYSSTRADD",
                "market_value": "FMV_TOTAL", "tax_value": "TOTVAL", "acreage": "CALCAC",
                "living_sqft": "SQFT", "land_use": "property_use",
                "owner_mailing": "CURR_ADDR1"},
    },
    "Mitchell": {  # 17,664 parcels; GISPIN (dash format) is the board id
        "url": "https://mapping.mitchellcountync.gov/arcgis/rest/services/WebMapNew/MapServer/12/query",
        "id_fields": ["GISPIN", "PIN", "TaxAcct"],
        "map": {"owner": "Owner1", "address": "LocAddr",
                "market_value": "Total", "tax_value": "Land", "acreage": "LegalAc",
                "living_sqft": "Dwelling",
                "owner_mailing": ["MailAddr", "MailCity", "MailState", "MailZip"]},
    },
    "Polk": {  # 16,878 parcels; TMS (dash format) is the board id
        "url": "https://services1.arcgis.com/23uf7jKvz6SRPFWJ/arcgis/rest/services/TaxParcels/FeatureServer/0/query",
        "id_fields": ["TMS"],
        "map": {"owner": "OWNAM1", "address": "PHYSICAL_STREET_ADDRESS",
                "market_value": "TOTAL_TAX_VALUE", "acreage": "DEEDED_ACRES",
                "living_sqft": "BUILDING_VALUE", "land_use": "NEIGHBORHOOD_CODE",
                "owner_mailing": ["OWCITY", "OWZIPA"]},
    },
    "Pickens": {  # 66,417 parcels; PIN is the board id
        "url": "https://services1.arcgis.com/59960rq18IxUcAVI/arcgis/rest/services/Pickens_Open_data/FeatureServer/6/query",
        "id_fields": ["PIN", "ACCTNO"],
        # market_value was mapped to "CalcAcres" -- an ACREAGE field in a value column.
        # The layer publishes no appraised value, so the honest mapping is None.
        "map": {"owner": "NAME1", "address": "LOCADD",
                "market_value": None, "acreage": "ACRES",
                "land_use": "TAXAREA",
                "owner_mailing": ["ADD1", "CITY", "STATE", "ZIP"],
                "sale_price": "SALEP"},
    },
    # --- 2026-08-19: Anderson SC (city-of-Anderson ArcGIS, 114,516 parcels) ---
    "Anderson": {  # TMS is the board id; layer has owner+mailing+situs+value+sale
        "url": "https://gis.cityofandersonsc.com/arcgis/rest/services/WaterUtilities/County_Parcels/FeatureServer/0/query",
        "id_fields": ["TMS"],
        "map": {"owner": "OWNER", "address": "PHYS_ADDR",
                "market_value": "MRKT_VALUE", "acreage": None,
                "living_sqft": None, "land_use": None,
                "sale_price": "SALE_PRICE"},
    },
}

# schema columns of the local `parcels` table, in insert order
# OWNER_MAILING IS THE POINT OF THE 2026-09-10 ADDITION. Measured that day: 10 of the 14
# cached county layers publish an owner MAILING address, and this schema had no column for
# it, so every one of them was fetched and thrown away. SC owner contact coverage runs
# 8-18% against NC's 50-89% and the per-county coverage matrix names it the binding
# constraint in every SC county -- while the mailing address sat in a layer already being
# downloaded. sale_price/sale_date are added for the same reason: 9 layers carry them and
# the sold-comp pool has no SC half.
_COLS = ("owner", "address", "owner_mailing", "market_value", "tax_value", "acreage",
         "living_sqft", "land_use", "sale_price", "sale_date")
_NUMERIC = {"market_value", "tax_value", "acreage", "living_sqft"}


def _map_val(rec: dict, col: str, spec):
    """Resolve one schema column from a source row. `spec` is a source field name,
    or a LIST of fields joined with spaces (for split situs like STREETNUM+STREETNAME),
    or None (column not available for this county). Numeric columns are coerced to float."""
    if spec is None:
        return None
    if isinstance(spec, list):
        parts = []
        for f in spec:
            v = rec.get(f)
            s = "" if v is None else str(v).strip()
            if s and s not in ("0", "0.0"):
                parts.append(s)
        val = " ".join(parts) or None
    else:
        val = rec.get(spec)
    if col in _NUMERIC and val not in (None, ""):
        try:
            return float(val)
        except (ValueError, TypeError):
            return None
    return val


def _norm_id(v) -> str:
    # whole-number floats (ArcGIS often returns internal PKs as 122973.0) -> "122973",
    # so they match a board id stored as "122973" instead of corrupting to "1229730".
    if isinstance(v, float) and v.is_integer():
        v = int(v)
    s = str(v or "")
    # drop a trailing .0 ONLY from a PURE float-string ("122973.0"); never from a punctuated
    # parcel number like a Spartanburg GISParcelNumber "1234-56-7890.00" (those zeros are real).
    if re.fullmatch(r"\d+\.0+", s):
        s = s[: s.index(".")]
    return re.sub(r"[^0-9a-z]", "", s.lower())


def _id_variants(v) -> set[str]:
    """Every normalized form a parcel id might appear as, so a 15-digit board PIN
    matches a 10-digit layer PIN and vice-versa (the padded/bare split from dedupe.py)."""
    n = _norm_id(v)
    if not n:
        return set()
    out = {n}
    if len(n) == 15 and n.endswith("00000"):
        out.add(n[:10])                 # 963470749800000 -> 9634707498
    elif len(n) == 10 and n.isdigit():
        out.add(n + "00000")            # 9634707498 -> 963470749800000
    return out


def _db_path(county: str) -> Path:
    return CACHE_DIR / f"{county.lower().replace(' ', '_')}.sqlite"


def cached_counties() -> set[str]:
    return {c for c in PARCEL_LAYERS if _db_path(c).exists()}


#: NC counties eligible for the statewide OneMap fallback.
#:
#: AMBIGUOUS NAMES ARE DELIBERATELY EXCLUDED. The parcel cache is keyed by county NAME
#: with no state -- lookup(county, parcel_id) and enrichment_gis_attrs both pass only
#: li.county -- so a name that exists in BOTH states would let an SC lead read NC parcel
#: data. These 4 are shared and are therefore NOT given an NC fallback:
#:   Beaufort, Cherokee, Lee, Union
#: Their SC halves keep whatever dedicated config they have. Fixing the underlying
#: name-only key is a separate change; silently seeding it with 100 more collisions is not.
_NC_COUNTY_NAMES = {
    "Alamance", "Alexander", "Alleghany", "Anson", "Ashe", "Avery",
    "Bertie", "Bladen", "Brunswick", "Buncombe", "Burke", "Cabarrus",
    "Caldwell", "Camden", "Carteret", "Caswell", "Catawba", "Chatham",
    "Chowan", "Clay", "Cleveland", "Columbus", "Craven", "Cumberland",
    "Currituck", "Dare", "Davidson", "Davie", "Duplin", "Durham",
    "Edgecombe", "Forsyth", "Franklin", "Gaston", "Gates", "Graham",
    "Granville", "Greene", "Guilford", "Halifax", "Harnett", "Haywood",
    "Henderson", "Hertford", "Hoke", "Hyde", "Iredell", "Jackson",
    "Johnston", "Jones", "Lenoir", "Lincoln", "Macon", "Madison",
    "Martin", "Mcdowell", "Mecklenburg", "Mitchell", "Montgomery", "Moore",
    "Nash", "New Hanover", "Northampton", "Onslow", "Orange", "Pamlico",
    "Pasquotank", "Pender", "Perquimans", "Person", "Pitt", "Polk",
    "Randolph", "Richmond", "Robeson", "Rockingham", "Rowan", "Rutherford",
    "Sampson", "Scotland", "Stanly", "Stokes", "Surry", "Swain",
    "Transylvania", "Tyrrell", "Vance", "Wake", "Warren", "Washington",
    "Watauga", "Wayne", "Wilkes", "Wilson", "Yadkin", "Yancey",
}

#: NC OneMap statewide parcels. ONE service, all 100 NC counties, 5,938,900 parcels --
#: verified live 2026-09-10. It carries the two layers the coverage matrix says are thin:
#:
#:   CONTACT   mailadd / munit / mcity / mstate / mzip  = the OWNER MAILING ADDRESS,
#:             populated at 99.6-100% in every NC footprint county measured:
#:               Buncombe 134,741/134,741   Gaston 117,252/117,211
#:               Henderson 75,373/75,373    Rutherford 57,599/57,580
#:               Cleveland 59,964/59,790    Burke 59,374/59,350
#:               Lincoln 56,862/56,862      McDowell 33,449/33,449
#:               Transylvania 31,755/31,755 Polk 18,211/18,063  Mitchell 17,671/17,270
#:             = 662,251 footprint parcels, essentially all of them contactable.
#:   VALUE     parval / landval / improvval, plus saledate, structyear and gisacres.
#:
#: This matters most for BUNCOMBE, LINCOLN and TRANSYLVANIA: their dedicated county layers
#: publish NO mailing field at all, so ~223,000 footprint parcels had no owner mailing
#: available anywhere until this.
NC_ONEMAP_URL = ("https://services.nconemap.gov/secure/rest/services/"
                 "NC1Map_Parcels/FeatureServer/1/query")

#: NC counties whose dedicated layer already carries an owner mailing field. For these the
#: dedicated layer wins -- it is the county's own data and usually richer (heated sqft,
#: condition codes) than the statewide aggregate.
_NC_DEDICATED_WITH_MAILING = {"Rutherford", "Henderson", "Burke", "McDowell", "Cleveland",
                              "Gaston", "Mitchell", "Polk"}


def nc_onemap_cfg(county: str) -> dict:
    """A parcel-cache config for any NC county, served off the statewide layer."""
    return {
        "url": NC_ONEMAP_URL,
        "where": f"cntyname='{county}'",
        "id_fields": ["parno", "altparno", "nparno"],
        "map": {"owner": "ownname", "address": "siteadd",
                "owner_mailing": ["mailadd", "munit", "mcity", "mstate", "mzip"],
                "market_value": "parval", "tax_value": "landval",
                "acreage": "gisacres", "land_use": "parusedesc",
                "sale_price": None, "sale_date": "saledatetx"},
    }


def resolve_layer_cfg(county: str) -> dict | None:
    """Dedicated county layer first, NC OneMap as the statewide fallback.

    The fallback only applies to counties that have no dedicated config, or whose
    dedicated config publishes no mailing address -- Buncombe, Lincoln and Transylvania
    are the three footprint counties in that position.
    """
    cfg = PARCEL_LAYERS.get(county)
    if cfg and (cfg.get("map", {}).get("owner_mailing") or county in _NC_DEDICATED_WITH_MAILING):
        return cfg
    if county in _NC_COUNTY_NAMES:
        return nc_onemap_cfg(county)
    return cfg


async def refresh_county(county: str) -> dict:
    """Bulk-download + verify + replace the cache for one county. Returns a status dict."""
    from .http_client import get_text
    cfg = resolve_layer_cfg(county)
    if not cfg:
        return {"county": county, "ok": False, "error": "no config"}
    base = cfg["url"]
    # a map value may be a single field or a list of fields (split situs) — flatten for outFields
    src_fields: set[str] = set(cfg["id_fields"])
    for spec in cfg["map"].values():
        if isinstance(spec, list):
            src_fields.update(spec)
        elif spec:
            src_fields.add(spec)
    out_fields = ",".join(sorted(src_fields))
    # A STATEWIDE layer needs a per-county filter. NC OneMap publishes all 5,938,900 NC
    # parcels in one service, so its config carries where=cntyname='<County>' and the
    # count check and every page must both use it -- counting 5.9M and paging one county
    # would never terminate.
    where_q = quote(cfg.get("where", "1=1"), safe="")
    # expected count first (completeness check)
    try:
        exp = json.loads(await get_text(f"{base}?where={where_q}&returnCountOnly=true&f=json",
                                        timeout=40, impersonate=True)).get("count")
    except Exception as e:  # noqa: BLE001
        return {"county": county, "ok": False, "error": f"count: {str(e)[:80]}"}

    rows, offset, t0, empties = [], 0, time.time(), 0
    # COUNT-DRIVEN pagination: keep pulling until we've collected `exp` rows. Advance by
    # the actual number returned (some servers return < _PAGE per page), and retry a page
    # up to 3x on a transient empty/error response instead of ending the loop early (which
    # is what silently truncated Burke @30k / Laurens @22.9k on the first pass).
    while exp is None or len(rows) < exp:
        url = (f"{base}?where={where_q}&outFields={out_fields}&returnGeometry=false"
               f"&resultOffset={offset}&resultRecordCount={_PAGE}&f=json")
        try:
            data = json.loads(await get_text(url, timeout=90, impersonate=True))
            feats = data.get("features") or []
        except Exception:  # noqa: BLE001 — transient; retry this same offset
            feats = []
        if not feats:
            empties += 1
            if empties >= 3:
                break            # genuinely no more rows at this offset — stop
            continue
        empties = 0
        rows.extend(f["attributes"] for f in feats)
        offset += len(feats)     # advance by what we actually got, not a fixed page size
        if offset > 3_000_000:
            break

    # COMPLETENESS GATE — never replace the cache with a short download
    ok = exp is not None and abs(len(rows) - exp) <= max(2, int(exp * 0.001))
    if not ok:
        return {"county": county, "ok": False, "downloaded": len(rows), "expected": exp,
                "error": "incomplete — cache NOT replaced"}

    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    tmp = _db_path(county).with_suffix(".tmp")
    if tmp.exists():
        tmp.unlink()
    con = sqlite3.connect(tmp)
    con.execute("CREATE TABLE parcels(id TEXT, owner TEXT, address TEXT, "
                "owner_mailing TEXT, market_value REAL, tax_value REAL, acreage REAL, "
                "living_sqft REAL, land_use TEXT, sale_price REAL, sale_date TEXT)")
    m = cfg["map"]
    recs = []
    for r in rows:
        keys: set[str] = set()
        for f in cfg["id_fields"]:
            keys |= _id_variants(r.get(f))
        if not keys:
            continue
        vals = tuple(_map_val(r, c, m.get(c)) for c in _COLS)
        recs.extend((k, *vals) for k in keys)   # index the parcel under each id variant
    con.executemany("INSERT INTO parcels VALUES(" + ",".join("?" * (1 + len(_COLS))) + ")", recs)
    con.execute("CREATE INDEX idx_id ON parcels(id)")
    con.commit(); con.close()
    tmp.replace(_db_path(county))   # atomic overwrite-in-place
    return {"county": county, "ok": True, "downloaded": len(rows), "expected": exp,
            "seconds": round(time.time() - t0, 1),
            "mb": round(_db_path(county).stat().st_size / 1e6, 1)}


_CONN: dict[str, sqlite3.Connection] = {}


def lookup(county: str, parcel_id: str) -> Optional[dict]:
    """Local join: return {owner,address,market_value,tax_value,acreage,living_sqft} or None."""
    p = _db_path(county)
    if not p.exists() or not (parcel_id or "").strip():
        return None
    con = _CONN.get(county)
    if con is None:
        con = _CONN[county] = sqlite3.connect(f"file:{p}?mode=ro", uri=True)
    row = None
    for k in _id_variants(parcel_id):
        try:
            row = con.execute(
                "SELECT " + ",".join(_COLS) + " FROM parcels WHERE id=?", (k,)).fetchone()
        except sqlite3.OperationalError:
            return None   # stale-schema cache (pre-land_use column) — weekly refresh rebuilds it
        if row:
            break
    if not row:
        return None
    return {k: v for k, v in zip(_COLS, row) if v not in (None, "")}
