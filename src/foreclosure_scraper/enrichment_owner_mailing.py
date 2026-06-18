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


async def _query(http: httpx.AsyncClient, base: str, where: str, out_fields: str = "*") -> list[dict]:
    url = base.rstrip("/") + "/query"
    params = {"where": where, "outFields": out_fields, "returnGeometry": "false",
              "resultRecordCount": "5", "f": "json"}
    try:
        r = await http.get(url, params=params, timeout=20.0)
        if r.status_code != 200:
            return []
        return [f.get("attributes", {}) for f in (r.json().get("features") or [])]
    except Exception:
        return []


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
    # 2) else match on situs street address (house number + street)
    if attrs is None and spec.get("situs") and li.street_address:
        m = _NUM_STREET.match(li.street_address)
        if m:
            num, street = m.group(1), _norm(m.group(2)).split()[0:2]
            field = spec["situs"][0]  # primary combined situs field
            like = f"%{num}%{(' '.join(street))}%".upper().replace("'", "")
            rows = await _query(http, spec["url"], f"UPPER({field}) LIKE '{like}'")
            # pick the row whose situs best matches the listing
            want = _norm(li.street_address)
            for row in rows:
                if _norm(_join(row, spec["situs"])).startswith(want[:10]):
                    attrs = row
                    break
            if attrs is None and rows:
                attrs = rows[0]
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
            "absentee": absentee, "out_of_state": out_of_state, "source": "county_gis"}


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
