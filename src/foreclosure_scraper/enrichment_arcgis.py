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


# ---- NC: direct ArcGIS REST per county ------------------------------------------

NC_GIS: dict[str, dict[str, Any]] = {
    "Mecklenburg": {
        "url": "https://meckgis.mecklenburgcountync.gov/server/rest/services/TaxParcel_Camaownershipvalues/FeatureServer/0/query",
        "addr_field": "txt_propaddr",
    },
    "Buncombe": {
        "url": "https://gis.buncombecounty.org/arcgis/rest/services/property_bc_dis/MapServer/1/query",
        "addr_field": "streetname",
    },
    "Henderson": {
        "url": "https://gisweb.hendersoncountync.gov/arcgis/rest/services/Parcels/FeatureServer/0/query",
        "addr_field": "PHYADDR",
    },
    "Rutherford": {
        "url": "https://gis.rutherfordcountync.gov/server/rest/services/MapMetricsServiceRutherford/MapServer/6/query",
        "addr_field": "MBL",
    },
    "Cleveland": {
        "url": "https://gis.clevelandcounty.com/arcgis/rest/services/Tax/Tax/MapServer/1/query",
        "addr_field": "PIN",
    },
    "Polk": {
        "url": "https://services1.arcgis.com/23uf7jKvz6SRPFWJ/arcgis/rest/services/TaxParcels/FeatureServer/0/query",
        "addr_field": "PHYSICAL_STREET_ADDRESS",
    },
    "Gaston": {
        "url": "https://cogserver.gastonianc.gov/serverweb/rest/services/Parcels/GastonCountyParcels/MapServer/0/query",
        "addr_field": "PROPADDR",
    },
    "Transylvania": {
        "url": "https://gis.transylvaniacounty.org/server/rest/services/Parcels/MapServer/2/query",
        "addr_field": "ADDRESS_1",
    },
    "McDowell": {
        "url": "https://services9.arcgis.com/ETP7IuCigkUz7iI9/arcgis/rest/services/McDowell_Parcels/FeatureServer/0/query",
        "addr_field": "siteadd",
    },
    "Lincoln": {
        "url": "https://arcgisserver.lincolncountync.gov/arcgis/rest/services/Server_TaxParcelViewerSP/MapServer/0/query",
        "addr_field": "PROPADDR",
    },
    "Madison": {
        "url": "https://services1.arcgis.com/SIYkiqjmENweC50g/arcgis/rest/services/Parcels_NC/FeatureServer/0/query",
        "addr_field": "ADDR",
    },
    "Mitchell": {
        "url": "https://mapping.mitchellcountync.gov/arcgis/rest/services/WebMapNew/MapServer/12/query",
        "addr_field": "LocAddr",
    },
    "Burke": {
        "url": "https://services3.arcgis.com/axQ4OCSpcxALIQsV/arcgis/rest/services/Tax_Parcels/FeatureServer/0/query",
        "addr_field": "LOCATION_ADDR",
    },
}


# ---- Field-name normalization ----------------------------------------------------

FIELD_ALIASES = {
    # NOTE: DEEDBK was historically in this list but it's the DEED BOOK number,
    # not a parcel identifier. Multiple parcels recorded in the same book all
    # get the same value, which then poisons the dedupe key. Removed.
    "parcel_id": ("PIN", "TMS", "REID", "PARCELNUMBER", "parno", "pinnum",
                  "MAPNUMBER", "pid", "PARID", "pid_long", "PARNO"),
    "owner_name": ("OwnerName", "OWNAM1", "Owner1", "PROPERTY_OWNER",
                   "full_owner_name", "owner", "ownname", "NAME1", "OWNER_NAME",
                   "Name1", "Name", "OWNER", "NAMECO"),
    "mailing_addr": ("txt_mailaddr1", "MailAddr", "OWNER_MAIL_1", "mailadd",
                     "Mailing_Address", "OwnerMailingAddress"),
    "site_address": ("PropertyLocation", "siteadd", "Property_Address", "LocAddr",
                     "LOCATION_ADDR", "PHYS_ADDR", "PHYADDR",
                     "PHYSICAL_STREET_ADDRESS", "SITUS_ADDR", "ADDRESS_1"),
    "acreage": ("Acreage", "ACRES", "gisacres", "ACREAGE", "LegalAc",
                "DEEDED_ACRES", "Acres", "ACRE", "Acres_Calc"),
    "year_built": ("taxYearBui", "AYB", "YearID", "structyear", "YEARBLT",
                   "YEAR_BUILT", "YearBuilt", "year_built", "EFFYR"),
    "bedrooms": ("BEDROOMS", "BedRooms", "Bedrooms", "BEDS"),
    "bathrooms": ("BATHRMS", "BATHS", "Bathrooms", "FullBaths", "BathRoom"),
    "living_sqft": ("HEATED_SQ_", "SQFEET", "TotLiving", "TotalLiving", "BLDGSQFT",
                    "BUILDING_S", "HeatedSqFt", "BLDGSF"),
    "tax_value": ("TAXMKTVAL", "FAIRMKTVAL", "MRKT_VALUE", "Total", "parval",
                  "presentval", "TotalVal", "TotalValue", "Tot_Val", "AppraisalValue",
                  "TOTAL_VAL"),
    "deed_book": ("DEEDBK", "Deed_Book", "DEED_BK", "DeedBook", "DB"),
    "deed_page": ("DEEDPG", "Deed_Page", "PAGE", "DeedPage", "DP"),
    "sale_date": ("SaleDate", "SALEDATE", "DEED_YEAR", "SaleYear", "Sale_Year"),
    "sale_amount": ("SaleAmount", "SALEAMT", "SalePrice", "Sale_Price"),
    "zoning": ("Zoning", "ZONING", "ZONE", "ZoneCode", "zone_code", "PRIM_ZONE"),
    "land_value": ("landval", "Land", "LANDVAL", "LandValue", "Land_Val"),
    "improvement_value": ("improvval", "Dwelling", "BLDG_VAL", "ImpValue",
                          "Improvement", "STRUCT_VAL"),
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

# Address-like field name candidates (in priority order)
_ADDR_FIELD_CANDIDATES = (
    "situsaddress1", "PROPADDR", "PROPERTY_ADDRESS", "PropertyLocation",
    "Property_Address", "PHYSICAL_STREET_ADDRESS", "LOCATION_ADDR",
    "PHYS_ADDR", "PHYADDR", "siteadd", "SITUS_ADDR", "ADDRESS_1",
    "Site_Address", "PROP_LOC", "ADDRESS", "ADDR", "LocAddr",
    "STREET_ADDR", "STREET", "StreetAddress", "FULLADDR",
    "PrimarySitusAddress", "SitusAddress", "PROP_ADDR", "MailAddr",
    "txt_propaddr",
)


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
    # Match against known candidates (case-insensitive)
    field_lower = {f.lower(): f for f in fields}
    for cand in _ADDR_FIELD_CANDIDATES:
        if cand.lower() in field_lower:
            return field_lower[cand.lower()]
    # Fallback: any field with "addr" or "street" in the name (excluding mail)
    for f in fields:
        flow = f.lower()
        if ("addr" in flow or "street" in flow or "situs" in flow) and "mail" not in flow and "owner" not in flow:
            return f
    return None


async def _arcgis_query(
    c: httpx.AsyncClient,
    base_url: str,
    addr_field: str | None,
    street: str,
    house_no: str | None = None,
) -> list[dict[str, Any]]:
    """Run an address LIKE query, auto-detecting the address field if needed.

    Returns list of dicts with both 'attributes' and a derived '_centroid' (lat,lng)
    when geometry is available.
    """
    if not addr_field:
        addr_field = await _detect_addr_field(c, base_url)
    if not addr_field:
        return []

    keyword = _street_keywords(street)
    if not keyword:
        return []
    patterns = []
    if house_no:
        patterns.append(f"%{house_no}%{keyword}%")
    patterns.append(f"%{keyword}%")

    for pat in patterns:
        where = f"UPPER({addr_field}) LIKE UPPER('{pat.replace(chr(39), chr(39)+chr(39))}')"
        params = {
            "where": where,
            "outFields": "*",
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

    # Coordinates (centroid of parcel polygon if we got geometry)
    centroid = attrs.get("_centroid")
    if centroid and not li.latitude and not li.longitude:
        try:
            li.latitude, li.longitude = float(centroid[0]), float(centroid[1])
            filled += 2
        except (ValueError, TypeError):
            pass

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
                gis["last_sale"]["amount"] = float(sale_a)
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
        # Normalize county: strip "County", trailing ", NC" or ", SC", whitespace
        county_clean = li.county.replace(" County", "").strip()
        for suffix in (", NC", ", SC", ",NC", ",SC"):
            if county_clean.upper().endswith(suffix):
                county_clean = county_clean[: -len(suffix)].strip()
        county_clean = county_clean.split(",")[0].strip()

        if li.state == "SC":
            layer = SC_LAYER.get(county_clean)
            if not layer:
                return
            base = f"{SCDOT_BASE}/{layer}/query"
            addr_field = None  # auto-detect; SC layers use STREET, PHYS_ADDR, or PropertyLocation
        elif li.state == "NC":
            cfg = NC_GIS.get(county_clean)
            if not cfg:
                return
            base = cfg["url"]
            addr_field = None  # auto-detect; let the layer schema tell us
        else:
            return

        # Extract house number for tighter match
        m = re.match(r"^\s*(\d+)", li.street_address)
        house_no = m.group(1) if m else None

        async with sem:
            counts["queried"] += 1
            results = await _arcgis_query(c, base, addr_field, li.street_address, house_no)
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
