"""#0 Contactability spine — county GIS owner + MAILING address enrichment.

For every listing with a property address, query the county's ArcGIS REST
parcel layer to pull the **owner name + owner MAILING address** (the taxpayer
mailing address, which is what you actually mail) + parcel id, and derive the
two signals that make a lead actionable:

  - absentee  = owner's mailing address != the property (situs) address
  - out_of_state = owner mails from a different state than the property

Without this, a distress signal is just a name with nowhere to send a letter.
The prior pipeline resolved only situs addresses and left owner/mailing empty
(run_health: 288/4816 mailable, 0 absentee) — this fills that gap.

Endpoints + field names were verified live per county (workflow wf_1dc91254).
ArcGIS REST is open JSON (no token). Counties without an ArcGIS owner/mailing
layer (Anderson SC, Cherokee SC = qPublic-only) are skipped here and handled
via the qPublic stealth path elsewhere.
"""
from __future__ import annotations

import asyncio
import os
import re
from typing import Optional

import httpx
import structlog

from .models import Listing

log = structlog.get_logger()

# Per-county verified ArcGIS REST parcel layers. `mail`/`situs` list the
# attribute fields to concatenate (in order) into one address string.
# `situs_combined`=True means situs is a single field; otherwise it's components.
COUNTY_GIS: dict[str, dict] = {
    # --- NC ---
    "NC:Buncombe": {"url": "https://gis.buncombecounty.org/arcgis/rest/services/property_bc_dis/MapServer/1",
        "owner": ["owner"], "care_of": "CareOf",
        "mail": ["Address", "CityName", "State", "Zipcode"], "mail_state": "State",
        "situs": ["HouseNumber", "NumberSuffix", "direction", "streetname", "StreetType", "PostDirection"],
        "situs_match": "streetname",  # split situs → LIKE the street-name field, not house#
        "parcel": "pin"},
    "NC:Henderson": {"url": "https://gisweb.hendersoncountync.gov/arcgis/rest/services/Parcels/FeatureServer/0",
        "owner": ["PROPERTY_OWNER"],
        "mail": ["OWNER_MAIL_1", "OWNER_MAIL_2", "OWNER_MAIL_3", "OWNER_MAIL_CITY", "OWNER_MAIL_STATE", "OWNER_MAIL_ZIP"],
        "mail_state": "OWNER_MAIL_STATE", "situs": ["LOCATION_ADDR"], "parcel": "PIN"},
    "NC:Rutherford": {"url": "https://gis.rutherfordcountync.gov/server/rest/services/MapMetricsServiceRutherford/MapServer/7",
        "owner": ["Property_Owner"],
        "mail": ["Owner_Mailing_Address_1", "Owner_Mailing_Address_2", "Owner_Mailing_Address_City", "Owner_Mailing_Address_State", "Owner_Mailing_Address_Zip"],
        "mail_state": "Owner_Mailing_Address_State", "situs": ["Physical_Address"], "parcel": "PIN"},
    "NC:Gaston": {"url": "https://cogserver.gastonianc.gov/serverweb/rest/services/Parcels/GastonCountyParcels/MapServer/0",
        "owner": ["CURR_NAME1", "CURR_NAME2"],
        "mail": ["CURR_ADDR1", "CURR_ADDR2", "CURR_CITY", "CURR_STATE", "CURR_ZIPCODE"],
        "mail_state": "CURR_STATE", "situs": ["PHYSSTRADD"], "parcel": "PIN"},
    "NC:Transylvania": {"url": "https://gis.transylvaniacounty.org/server/rest/services/Parcels/MapServer/2",
        "owner": ["OWNER_NAME"], "mail": ["ADDRESS_1", "ADDRESS_2", "ADDRESS_3"],
        "situs": ["LEGAL_ADDR"], "parcel": "PIN"},
    "NC:Polk": {"url": "https://services1.arcgis.com/23uf7jKvz6SRPFWJ/arcgis/rest/services/Parcels/FeatureServer/0",
        "owner": ["OWNAM1", "OWNAM2", "OWNAM3"], "mail": ["OWADR1", "OWCITY", "OWSTA", "OWZIPA"],
        "mail_state": "OWSTA", "situs": ["PHYSICAL_STREET_ADDRESS"], "parcel": "TMS"},
    "NC:Lincoln": {"url": "https://arcgisserver.lincolncountync.gov/arcgis/rest/services/Server_TaxParcelViewerSP/MapServer/0",
        "owner": ["NAME1", "NAME2"], "mail": ["ADDRESS1", "ADDRESS2", "CITY", "STATE", "ZIP"],
        "mail_state": "STATE", "situs": ["PHYSICALADDR"], "parcel": "PIN"},
    "NC:Mitchell": {"url": "https://mapping.mitchellcountync.gov/arcgis/rest/services/WebMapNew/MapServer/12",
        "owner": ["Owner1", "Owner2"], "mail": ["MailAddr", "MailCity", "MailState", "MailZip"],
        "mail_state": "MailState", "situs": ["LocAddr"], "parcel": "PIN"},
    "NC:Burke": {"url": "https://gis.morgantonnc.gov/server/rest/services/General/Parcels_Only/FeatureServer/0",
        "owner": ["Property_Owner"], "mail": ["Owner_MA"], "mail_combined": True,
        "situs": ["Property_Address"], "parcel": "PIN"},
    "NC:McDowell": {"url": "https://services9.arcgis.com/ETP7IuCigkUz7iI9/arcgis/rest/services/McDowell_Parcels/FeatureServer/0",
        "owner": ["ownname", "ownname2"], "mail": ["mailadd", "munit", "mcity", "mstate", "mzip"],
        "mail_state": "mstate", "situs": ["siteadd"], "parcel": "parno"},
    # Cleveland resolves to NC OneMap statewide service (also a fallback for any NC county).
    "NC:Cleveland": {"url": "https://services.nconemap.gov/secure/rest/services/NC1Map_Parcels/FeatureServer/1",
        "owner": ["ownname", "ownname2"], "mail": ["mailadd", "munit", "mcity", "mstate", "mzip"],
        "mail_state": "mstate", "situs": ["siteadd"], "parcel": "parno", "county_field": "cntyname"},
    # --- SC ---
    "SC:Spartanburg": {"url": "https://services9.arcgis.com/HoRra3ATPLGmyjn6/arcgis/rest/services/Parcel_and_CAMA_Feb_1_2021/FeatureServer/0",
        "owner": ["OwnerName", "TaxpayerNa"], "mail": ["StreetAddr", "City", "State", "Zip"],
        "mail_state": "State", "situs": ["PropertyLo"], "parcel": "TAXPIN"},
    "SC:Pickens": {"url": "https://services1.arcgis.com/59960rq18IxUcAVI/arcgis/rest/services/Pickens_Open_data/FeatureServer/6",
        "owner": ["NAME1", "NAME2"], "mail": ["ADD1", "CITY", "STATE", "ZIP"],
        "mail_state": "STATE", "situs": ["LOCADD"], "parcel": "PIN"},
    "SC:Oconee": {"url": "https://arcserver2.oconeesc.com/arcgis/rest/services/PARCELDATA_owner_Assr/MapServer/1",
        "owner": ["current_owner"], "mail": ["owner_street", "owner_citystate", "owner_zip"],
        "situs": [], "parcel": "TMS_NUMBER"},  # no situs field → parcel-match only
    "SC:Laurens": {"url": "https://laurenscountygis.org/arcgis/rest/services/Pebble/TaxParcel/MapServer/5",
        "owner": ["Owner"], "mail": ["Mailing_Address", "Mailing_City_State_ZIP"],
        "situs": ["Property_Address"], "parcel": "TMS"},
    "SC:Union": {"url": "https://services6.arcgis.com/xQgypOVdY84tFTiW/arcgis/rest/services/UNION_SC_PARCELS_WFL1/FeatureServer/2",
        "owner": ["Name"], "mail": ["Address_1", "Address_2", "Address_3"],
        "situs": [], "parcel": "ParcelID"},  # situs on a different layer → parcel-match only
}
# Anderson SC + Cherokee SC: no ArcGIS owner/mailing layer (qPublic-only) → not here.

_NUM_STREET = re.compile(r"^\s*(\d+)\s+(.+?)\s*$")


def _norm(s: str) -> str:
    return re.sub(r"[^a-z0-9 ]", "", (s or "").lower()).strip()


def _join(attrs: dict, fields: list[str]) -> str:
    parts = [str(attrs.get(f)).strip() for f in fields if attrs.get(f) not in (None, "", " ")]
    return " ".join(p for p in parts if p and p.lower() != "none").strip()


async def _query(http: httpx.AsyncClient, base: str, where: str, out_fields: str = "*",
                 count: int = 25) -> list[dict]:
    url = base.rstrip("/") + "/query"
    params = {"where": where, "outFields": out_fields, "returnGeometry": "false",
              "resultRecordCount": str(count), "f": "json"}
    try:
        r = await http.get(url, params=params, timeout=20.0)
        if r.status_code != 200:
            return []
        return [f.get("attributes", {}) for f in (r.json().get("features") or [])]
    except Exception:
        return []


# 2026-06-19: generic building-spec extractor. County CAMA/parcel layers that
# expose building attributes (e.g. Spartanburg: LivingArea/YearBuilt/BedRooms/
# FullBaths) can backfill beds/baths/sqft/year — the root unblocker for ARV. We
# match by field-NAME pattern (not per-county hardcoding) so it works on any
# layer that has them, and sanity-check values so junk fields don't leak in.
_SPEC_PATTERNS = {
    "living_sqft": re.compile(r"^(living_?area|heated_?(sq_?ft|area)|tot(al)?_?liv(ing)?(_?area)?|finish(ed)?_?(sq_?ft|area)|gross_?(sq_?ft|living)|bldg_?sq_?ft|heatedsqft|sqft_?heated|heated_?sf)$", re.I),
    "year_built": re.compile(r"^(year_?built|yr_?built|act(ual)?_?year_?bl?t|yearbuilt|eff(ective)?_?year_?built)$", re.I),
    "bedrooms":   re.compile(r"^(bed_?rooms?|beds|no_?(of_?)?bed(room)?s?|num_?bed(room)?s?)$", re.I),
    "bathrooms":  re.compile(r"^(full_?baths?|bath_?rooms?|baths|no_?(of_?)?baths?|num_?baths?)$", re.I),
}
def _extract_specs(attrs: dict) -> dict:
    out: dict = {}
    half = None
    for k, v in (attrs or {}).items():
        if (k or "").lower() in ("halfbaths", "half_baths") and v not in (None, "", 0, "0"):
            try: half = float(str(v).replace(",", ""))
            except (ValueError, TypeError): pass
    for field, pat in _SPEC_PATTERNS.items():
        for k, v in (attrs or {}).items():
            if pat.match(k or "") and v not in (None, "", 0, "0"):
                try: fv = float(str(v).replace(",", ""))
                except (ValueError, TypeError): continue
                if field == "living_sqft" and not (200 <= fv <= 30000): continue
                if field == "year_built" and not (1800 <= fv <= 2030): continue
                if field in ("bedrooms", "bathrooms") and not (0 < fv <= 25): continue
                if field == "bathrooms" and half and 0 < half <= 10:
                    fv += 0.5 * half   # combine full + half baths
                out[field] = fv
                break
    return out


# 2026-06-21: county appraised/market value extractor. Most county CAMA layers
# expose the total property valuation (the root unblocker for the proxy-ARV in
# valuation/calc.py, which reads tax_value × 1.25). Field names vary wildly, so
# we try priority-ordered patterns for a single TOTAL value, then fall back to
# summing land + improvement. Land-only fields and SC's "Assessment" class
# string ("4% OO RES IM") are deliberately NOT used as the value.
_VALUE_PRIORITY = [
    re.compile(r"^(total_?market_?value|market_?value)$", re.I),                       # Buncombe TotalMarketValue
    re.compile(r"^(appraised_?value|apprval|appr_?val)$", re.I),                       # Buncombe AppraisedValue
    re.compile(r"^(total_?tax_?value|cost_?total_?value|total_?value|totval|totalvalue)$", re.I),  # Polk/Henderson/Lincoln/Gaston
    re.compile(r"^(assessed_?value|assessed_?v|taxvalue|tax_?value)$", re.I),          # Transylvania ASSESSED_V, Buncombe TaxValue
]
_LAND_PAT = re.compile(r"^(land_?value|landval)$", re.I)
_IMPROV_PAT = re.compile(r"^(improvement_?value|improv_?value|improvval|bldg_?value|building_?value|building_?v)$", re.I)


def _num_value(v) -> Optional[float]:
    try:
        f = float(str(v).replace(",", "").replace("$", "").strip())
    except (ValueError, TypeError):
        return None
    return f if 1000 <= f <= 50_000_000 else None  # reject 0/exempt + absurd


def _extract_value(attrs: dict) -> Optional[float]:
    """Total appraised/market property value, or None."""
    if not attrs:
        return None
    for pat in _VALUE_PRIORITY:
        for k, v in attrs.items():
            if pat.match(k or ""):
                n = _num_value(v)
                if n:
                    return n
    # Last resort: land + improvement components summed (e.g. McDowell).
    land = improv = None
    for k, v in attrs.items():
        if _LAND_PAT.match(k or ""):
            land = _num_value(v) or land
        if _IMPROV_PAT.match(k or ""):
            improv = _num_value(v) or improv
    if land or improv:
        s = (land or 0) + (improv or 0)
        return s if s >= 1000 else None
    return None


async def _resolve_one(http: httpx.AsyncClient, li: Listing) -> Optional[dict]:
    spec = COUNTY_GIS.get(f"{li.state}:{(li.county or '').strip().title()}")
    if not spec:
        return None
    attrs = None
    # 1) exact parcel match if we already have a parcel id
    if li.parcel_id:
        pid = re.sub(r"[^A-Za-z0-9]", "", li.parcel_id)
        if pid:
            rows = await _query(http, spec["url"], f"{spec['parcel']} LIKE '%{pid}%'")
            attrs = rows[0] if rows else None
    # 2) else match on situs street address. Query the street-NAME field broadly
    #    (the longest, most distinctive street word) so format differences don't
    #    block the hit, then verify house-number + street client-side. Works for
    #    both combined-situs and component-situs (e.g. Buncombe) counties.
    if attrs is None and spec.get("situs") and li.street_address:
        m = _NUM_STREET.match(li.street_address)
        if m:
            num = m.group(1)
            words = [w for w in _norm(m.group(2)).split()
                     if w not in ("rd", "dr", "st", "ln", "ave", "ct", "way", "cir",
                                  "blvd", "pl", "trl", "hwy", "pkwy", "n", "s", "e", "w")]
            if words:
                mfield = spec.get("situs_match", spec["situs"][0])
                key = max(words, key=len)  # most distinctive street word
                rows = await _query(http, spec["url"],
                                    f"UPPER({mfield}) LIKE '%{key.upper()}%'")
                for row in rows:
                    rs = _norm(_join(row, spec["situs"]))
                    if num in rs and all(w in rs for w in words):
                        attrs = row
                        break
                if attrs is None:  # looser: number + the key word
                    for row in rows:
                        rs = _norm(_join(row, spec["situs"]))
                        if num in rs and key in rs:
                            attrs = row
                            break
    if not attrs:
        return None

    owner = _join(attrs, spec["owner"])
    if spec.get("care_of") and attrs.get(spec["care_of"]):
        mailing = f"C/O {attrs[spec['care_of']]}, " + _join(attrs, spec["mail"])
    else:
        mailing = _join(attrs, spec["mail"])
    situs = _join(attrs, spec["situs"]) if spec.get("situs") else None
    parcel = str(attrs.get(spec["parcel"]) or "").strip() or None
    mail_state = (attrs.get(spec.get("mail_state", "")) or "").strip().upper() if spec.get("mail_state") else None

    if not owner and not mailing:
        return None
    # absentee = mailing differs from situs; out_of_state = mails from another state
    absentee = bool(situs and mailing and _norm(situs) not in _norm(mailing))
    out_of_state = bool(mail_state and li.state and mail_state != li.state)
    return {"owner": owner or None, "mailing": mailing or None, "situs": situs,
            "parcel_id": parcel, "mail_state": mail_state or None,
            "absentee": absentee, "out_of_state": out_of_state, "source": "county_gis",
            "_specs": _extract_specs(attrs), "_value": _extract_value(attrs)}


async def enrich_owner_mailing(listings: list[Listing], max_concurrency: int = 4) -> dict:
    """Fill owner + mailing + absentee/out-of-state + parcel_id from county GIS."""
    targets = [li for li in listings
               if f"{li.state}:{(li.county or '').strip().title()}" in COUNTY_GIS
               and (li.street_address or li.parcel_id)
               and not ((li.raw or {}).get("owner_mailing") or {}).get("mailing")]
    if not targets:
        return {"queried": 0, "resolved": 0}
    sem = asyncio.Semaphore(max_concurrency)
    counts = {"queried": 0, "resolved": 0, "absentee": 0, "out_of_state": 0}

    async with httpx.AsyncClient(timeout=httpx.Timeout(25.0)) as http:
        async def one(li: Listing):
            async with sem:
                counts["queried"] += 1
                res = await _resolve_one(http, li)
            if res:
                if not isinstance(li.raw, dict):
                    li.raw = {}
                # Backfill building specs from the GIS record (where the layer
                # exposes them) — beds/baths/sqft/year, only when missing.
                specs = res.pop("_specs", None) or {}
                if specs.get("living_sqft") and not li.living_sqft:
                    li.living_sqft = specs["living_sqft"]; counts["specs_sqft"] = counts.get("specs_sqft", 0) + 1
                if specs.get("year_built") and not li.year_built:
                    li.year_built = int(specs["year_built"])
                if specs.get("bedrooms") and not li.bedrooms:
                    li.bedrooms = specs["bedrooms"]
                if specs.get("bathrooms") and not li.bathrooms:
                    li.bathrooms = specs["bathrooms"]
                # County total appraised/market value — feeds the proxy-ARV in
                # valuation/calc.py (tax_value × 1.25) and closes the
                # assessed_value gap. Fill all three value fields when missing
                # (for these county appraisal records they are the same total).
                val = res.pop("_value", None)
                if val:
                    if not li.tax_value:
                        li.tax_value = val
                        counts["value_filled"] = counts.get("value_filled", 0) + 1
                    if not li.market_value:
                        li.market_value = val
                    if not li.assessed_value:
                        li.assessed_value = val
                li.raw["owner_mailing"] = res
                if res.get("parcel_id") and not li.parcel_id:
                    li.parcel_id = res["parcel_id"]
                counts["resolved"] += 1
                if res.get("absentee"):
                    counts["absentee"] += 1
                if res.get("out_of_state"):
                    counts["out_of_state"] += 1
        await asyncio.gather(*(one(li) for li in targets))
    log.info("owner_mailing.done", **counts, targets=len(targets))
    return counts
