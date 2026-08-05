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
import re
from typing import Optional

import httpx
import structlog

from .models import Listing

log = structlog.get_logger()


def mailing_dict(obj) -> dict:
    """`raw['owner_mailing']` as a dict, whatever the source actually wrote.

    Most sources write a dict. Several Spartanburg ones (spartanburg_vacant,
    spartanburg_condemned, spartanburg_delinquent_tax) write a bare STRING that
    IS the mailing address — 5,098 leads on the 2026-08-03 board. `or {}` cannot
    rescue a truthy str, so every unguarded `(raw.get("owner_mailing") or {}).get(...)`
    raises AttributeError and takes its whole pass down with it. That killed the
    mail spine for all 30k leads on the 2026-07-31 run.

    Accepts a Listing, a raw dict, or the owner_mailing value itself.
    """
    raw = getattr(obj, "raw", obj)
    if isinstance(raw, dict) and "owner_mailing" in raw:
        om = raw.get("owner_mailing")
    else:
        om = raw
    if isinstance(om, dict):
        return om
    if isinstance(om, str) and om.strip():
        return {"mailing": om.strip()}
    return {}


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
    # 2026-08-03 REPOINT: was cogserver.gastonianc.gov (the CITY of Gastonia
    # server), a 115,066-row copy. The COUNTY's own service is the authority:
    # 117,565 rows, situs 99.97%, mailing state 99.96%. Same column names, so
    # only the URL moves. Layer id is 11 — /FeatureServer/0 is HTTP 500.
    "NC:Gaston": {"url": "https://gis.gastoncountync.gov/publicgis/rest/services/PublicGIS/Parcels/FeatureServer/11",
        "owner": ["CURR_NAME1", "CURR_NAME2"],
        "mail": ["CURR_ADDR1", "CURR_ADDR2", "CURR_CITY", "CURR_STATE", "CURR_ZIPCODE"],
        "mail_state": "CURR_STATE", "situs": ["PHYSSTRADD"], "parcel": "PIN"},
    # 2026-08-03 FIELD FIX (URL unchanged). Verified live on real rows:
    #   ADDRESS_1 holds the SECOND OWNER'S NAME ("Rein Lindsay", "Quinn Starr L"),
    #             not an address — it was being concatenated into the mail string.
    #   ADDRESS_2 is the care-of / first mailing line ("%Karen Mcleod President").
    #   ADDRESS_3 is the mailing street ("PO Box 2845", "840 Springdale Rd NE").
    #   CITY/STATE/ZIP_CODE are the MAILING city/state/zip and were omitted
    #             entirely, so `mail_state` was absent and absentee/out_of_state
    #             could never fire — in a resort county with 7,464 out-of-state
    #             owners on the layer.
    #   LEGAL_ADDR is a legal description ("LOT 1 Whitewater Cove 2.00"), not a
    #             situs, so it can't be address-matched; this layer has no situs
    #             column at all → parcel-match only (same as SC:Oconee/SC:Union).
    "NC:Transylvania": {"url": "https://gis.transylvaniacounty.org/server/rest/services/Parcels/MapServer/2",
        "owner": ["OWNER_NAME", "ADDRESS_1"],
        "mail": ["ADDRESS_2", "ADDRESS_3", "CITY", "STATE", "ZIP_CODE"],
        "mail_state": "STATE", "situs": [], "parcel": "PIN"},
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
    # 2026-08-03 REPOINT: the old AGOL layer (services9…/Parcel_and_CAMA_Feb_1_2021)
    # is a 29,402-row MUNICIPAL extract — it can only answer ~16% of the 8,919
    # Spartanburg board leads. The county's own CAMA FeatureServer carries the
    # FULL roll: 181,369 card-level rows, 163,059 primary cards (CardNumber=1).
    # Parcel key is MAPNUMBER (unique per parcel); GISParcelNumber is NOT unique
    # (condos share a polygon), so it is not used as the join field here.
    "SC:Spartanburg": {"url": "https://maps.spartanburgcounty.org/server/rest/services/GIS/CAMA_Parcels/FeatureServer/0",
        "owner": ["OwnerName", "TaxpayerName"], "mail": ["StreetAddress", "City", "State", "Zip"],
        "mail_state": "State", "situs": ["PropertyLocation"], "situs_match": "StreetName",
        "parcel": "MAPNUMBER", "where_suffix": "CardNumber=1"},
    # Verified live 2026-08-03: 66,417 rows, NAME1 populated on 66,365, ADD1 on
    # 66,353, LOCADD (situs) on 57,009, STATE on 66,346. URL/fields unchanged —
    # what was actually capping this county was the 25-row situs scan (see
    # `_scan`): the street-word LIKE this matcher fires returns 142-324 rows here.
    # outFields is enumerated (no `*`); the layer carries no contact/ID column.
    "SC:Pickens": {"url": "https://services1.arcgis.com/59960rq18IxUcAVI/arcgis/rest/services/Pickens_Open_data/FeatureServer/6",
        "owner": ["NAME1", "NAME2"], "mail": ["ADD1", "CITY", "STATE", "ZIP"],
        "mail_state": "STATE", "situs": ["LOCADD"], "parcel": "PIN",
        "out_fields": "PIN,NAME1,NAME2,ADD1,CITY,STATE,ZIP,LOCADD,ACRES,TAXYEAR"},
    # 2026-08-03 REPOINT: was PARCELDATA_owner_Assr/MapServer/1, the JOINED
    # polygon view — 63,384 rows, current_owner populated on 62,406. Oconee's
    # parcel layers proper (CitizenServe/1 'Parcels', Parcels_OpenData/0) carry NO
    # owner and NO mailing at all, so the assessor TABLE is the county's only
    # machine-readable mail spine: 68,145 rows with current_owner AND owner_street
    # populated on ALL of them (+4,761 rows, +5,739 owners over the joined view).
    # Field names verified live off the layer's own metadata; parcel key is `pin`
    # (dashed TMS, space-padded — '002-00-01-001'), matching board parcel_ids.
    # objectIdField is null on this table, hence the explicit `order_by` for paging.
    # Still situs-less (no address column exists on ANY Oconee owner layer), so
    # this county stays parcel-match only — street-only leads cannot resolve here.
    "SC:Oconee": {"url": "https://arcserver2.oconeesc.com/arcgis/rest/services/CitizenServe/MapServer/5",
        "owner": ["current_owner"], "mail": ["owner_street", "owner_citystate", "owner_zip"],
        "situs": [], "parcel": "pin", "order_by": "pin",
        "out_fields": "pin,current_owner,owner_street,owner_citystate,owner_zip,deed_book,deed_page,proval_acres"},
    # 2026-08-03 NEW. Anderson had no COUNTY_GIS entry at all: it fell through to
    # the statewide SCDOT layer, which is now token-walled, leaving the local bulk
    # roll (sc_parcel_mailing) as the ONLY path — and that path is dark on any host
    # whose SQLite cache is missing or stale. This is the live spine behind it.
    # The service lives on the CITY of Anderson server under a folder named
    # "WaterUtilities", but the layer is LocalGovernment.DBO.Parcels_County and is
    # verified parcel/assessment data, NOT utility customers: TMS, OWNER (owner of
    # record), OWNER_ADDR (taxpayer mailing), PHYS_ADDR (situs), MRKT_VALUE,
    # SALE_PRICE/SALE_YEAR, PREV_OWNER, DBOOK/DPAGE. There is no phone, e-mail,
    # account, meter or customer column on it. 114,516 rows; OWNER + OWNER_ADDR on
    # 113,699; PHYS_ADDR on 100,985; MRKT_VALUE>0 on 112,641.
    # CITY is "CITY  STATE" ("ANDERSON  SC"), same as SCDOT, so mail_state is
    # recovered from the mailing tail rather than a discrete column.
    "SC:Anderson": {"url": "https://gis.cityofandersonsc.com/arcgis/rest/services/WaterUtilities/County_Parcels/FeatureServer/0",
        "owner": ["OWNER"], "mail": ["OWNER_ADDR", "CITY", "ZIPCODE"],
        "situs": ["PHYS_ADDR"], "parcel": "TMS",
        "out_fields": "TMS,OWNER,OWNER_ADDR,CITY,ZIPCODE,PHYS_ADDR,MRKT_VALUE,SALE_PRICE,SALE_YEAR,PREV_OWNER,DBOOK,DPAGE"},
    "SC:Laurens": {"url": "https://laurenscountygis.org/arcgis/rest/services/Pebble/TaxParcel/MapServer/5",
        "owner": ["Owner"], "mail": ["Mailing_Address", "Mailing_City_State_ZIP"],
        "situs": ["Property_Address"], "parcel": "TMS"},
    "SC:Union": {"url": "https://services6.arcgis.com/xQgypOVdY84tFTiW/arcgis/rest/services/UNION_SC_PARCELS_WFL1/FeatureServer/2",
        "owner": ["Name"], "mail": ["Address_1", "Address_2", "Address_3"],
        "situs": [], "parcel": "ParcelID"},  # situs on a different layer → parcel-match only
}
# Cherokee SC: no ArcGIS owner/mailing layer (qPublic-only) → not here.

_NUM_STREET = re.compile(r"^\s*(\d+)\s+(.+?)\s*$")


def _norm(s: str) -> str:
    # Collapse runs of whitespace too: several rolls pad columns into fixed-width
    # slots (Anderson PHYS_ADDR = 'SPRINGSIDE        300 SPRINGSIDE CIR'), and a
    # raw double space made every substring comparison against it fail.
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9 ]", "", (s or "").lower())).strip()


def _has_house_number(num: str, norm_situs: str) -> bool:
    """House number present as a WHOLE token in a normalized situs string.

    Was a bare `num in situs` substring test, which matches '144' inside '1440'.
    That was survivable while the candidate scan was capped at 25 rows; now that
    we page up to 1500 candidates, a substring test would hand back the wrong
    parcel — and a wrong parcel means a letter mailed to a stranger. Every
    configured layer's situs (Pickens 'LOCADD'='144 PORTER RD', Anderson
    'PHYS_ADDR'='SPRINGSIDE  300 SPRINGSIDE CIR', Buncombe's split
    HouseNumber+streetname join) carries the number as its own token."""
    return num in norm_situs.split()


# Several rolls store the mailing ZIP as an integer or as a run-together ZIP+4
# ('296300000', '296708823'), and a missing ZIP arrives as literal 0. Left alone
# those land in the mailing string as '296300000' / '0', which is not a mailable
# address. Normalize the trailing ZIP token only — never the street or city.
def _clean_mailing(mailing: str) -> str:
    if not mailing:
        return mailing
    out = re.sub(r"\s+", " ", mailing).strip()
    out = re.sub(r"\s+0$", "", out)                       # ZIP absent -> integer 0
    out = re.sub(r"\b(\d{5})0000$", r"\1", out)           # ZIP+4 padded with zeros
    out = re.sub(r"\b(\d{5})(\d{4})$", r"\1-\2", out)     # real ZIP+4 -> ZIP5-ZIP4
    return out.strip()


def _pid_variants(parcel_id: str) -> list[str]:
    """Ordered, de-duped LIKE candidates for a parcel id.

    ROOT CAUSE (2026-06-25): the old code only tried the *stripped* form
    (re.sub('[^A-Za-z0-9]','',pid)). But several SC/NC parcel layers store the
    TMS/PIN WITH dashes (Pickens '5038-08-97-3519', Oconee '120-01-01-028',
    Transylvania '9506-68-2123-000'), so `PIN LIKE '%503808973519%'` returned
    zero rows even though the dashed form matches exactly. Pickens alone is
    1358 leads with a parcel_id and ~2% resolved because of this. We now try,
    in order: the raw id, the id minus any trailing ' 000'/'-000' card suffix
    (Union '104-00-00-015 000' → '104-00-00-015'), and the fully-stripped id.
    """
    raw = (parcel_id or "").strip()
    out: list[str] = []

    def _add(v: str) -> None:
        v = (v or "").strip()
        # ArcGIS LIKE: escape single quotes; bail on anything that would make
        # a useless/over-broad wildcard.
        if v and len(v) >= 4 and v not in out:
            out.append(v)

    _add(raw)
    # trailing card/sub-parcel suffix some exports append (' 000', '-000', '.000')
    _add(re.sub(r"[\s.\-]0{3}$", "", raw))
    _add(re.sub(r"[^A-Za-z0-9]", "", raw))
    return out


def _is_absentee(prop_addr: Optional[str], mailing: Optional[str]) -> bool:
    """True when the owner mails from somewhere other than the property.

    prop_addr is the GIS situs when available, else the listing's own street
    address (so counties whose parcel layer has no situs field still resolve an
    absentee flag). The substring test tolerates the mailing carrying extra
    city/state/zip the situs string doesn't.

    The substring test alone is not enough once a layer's situs carries a
    SUBDIVISION prefix: Anderson's PHYS_ADDR is 'SPRINGSIDE  300 SPRINGSIDE CIR'
    against a mailing of '300 SPRINGSIDE CIR ANDERSON SC 29625' — the same house,
    but the situs is not a substring, so every Anderson owner-occupant was
    flagged absentee (+8 distress, and absentee gates HOT). So we also accept a
    token-subset match: if every word of the situs appears somewhere in the
    mailing, the owner mails to the property. Subset is strictly weaker than
    substring, so this can only REMOVE false absentee flags, never add one."""
    if not (prop_addr and mailing):
        return False
    p, m = _norm(prop_addr), _norm(mailing)
    if not p or p in m:
        return False
    toks = p.split()
    # Need a real address (a house number + at least one street word) before a
    # subset match is trustworthy — 'RD' alone must not clear the flag.
    if len(toks) >= 2 and any(t.isdigit() for t in toks) and set(toks) <= set(m.split()):
        return False
    return True


def _join(attrs: dict, fields: list[str], *, dedupe: bool = False) -> str:
    """Concatenate the listed attributes into one string.

    `dedupe` drops a repeated part (case-insensitively) — used for the OWNER
    join, where most rolls set the taxpayer/second-owner column to the SAME
    string as the owner column and a blind join produced doubled names like
    'YOUNG WILLIE YOUNG WILLIE'."""
    parts = [str(attrs.get(f)).strip() for f in fields if attrs.get(f) not in (None, "", " ")]
    parts = [p for p in parts if p and p.lower() != "none"]
    if dedupe:
        seen: set[str] = set()
        kept: list[str] = []
        for p in parts:
            k = re.sub(r"\s+", " ", p).strip().lower()
            if k not in seen:
                seen.add(k)
                kept.append(p)
        parts = kept
    return " ".join(parts).strip()


async def _query_page(http: httpx.AsyncClient, base: str, where: str, out_fields: str = "*",
                      count: int = 25, offset: int = 0,
                      order_by: str = "") -> tuple[list[dict], bool]:
    """One /query call -> (attribute rows, server's exceededTransferLimit)."""
    url = base.rstrip("/") + "/query"
    params = {"where": where, "outFields": out_fields, "returnGeometry": "false",
              "resultRecordCount": str(count), "f": "json"}
    if offset:
        params["resultOffset"] = str(offset)
    # Several of these layers are TABLES with objectIdField=null (Oconee
    # CitizenServe/5, Pickens, Anderson). ArcGIS will not page deterministically
    # without an explicit sort, so pass one whenever we page.
    if order_by:
        params["orderByFields"] = order_by
    try:
        r = await http.get(url, params=params, timeout=20.0)
        if r.status_code != 200:
            return [], False
        data = r.json()
        rows = [f.get("attributes", {}) for f in (data.get("features") or [])]
        return rows, bool(data.get("exceededTransferLimit"))
    except Exception:
        return [], False


async def _query(http: httpx.AsyncClient, base: str, where: str, out_fields: str = "*",
                 count: int = 25) -> list[dict]:
    rows, _ = await _query_page(http, base, where, out_fields, count)
    return rows


# 2026-08-03: the situs street-name query was capped at ONE page of 25 rows, which
# silently truncated every match in a real county. Measured live: the broad
# street-word LIKE this matcher fires returns 44-900 rows on these layers
# (Pickens LOCADD '%MOOREFIELD%'=324, '%MEADOW%'=261; Anderson PHYS_ADDR
# '%SHORE%'=900, '%SHIRLEY%'=252), so the correct parcel was usually past row 25
# and the lead resolved to nothing. We now page through the candidates
# (resultOffset + resultRecordCount, sorted so paging is stable) up to a cap.
_SITUS_PAGE = 500       # <= every configured layer's maxRecordCount (1000/2000)
_SITUS_SCAN_CAP = 1500  # hard ceiling: one lead never costs more than 3 requests


#: Field-name shapes we must never request, whatever a spec or a county layer offers.
#: Belt-and-braces with _spec_out_fields(): even a hand-written out_fields is filtered.
_FORBIDDEN_FIELD = re.compile(
    r"ssn|social_?sec|drivers?_?lic|dl_?num|tcdlc|date_?of_?birth|\bdob\b|birth_?date"
    r"|poc_?phone|poc_?email|account_?(no|num)|acct_?(no|num)",
    re.I,
)


def _spec_out_fields(spec: dict) -> str:
    """Derive the exact field list a spec needs, so we never send outFields=*.

    Every spec already declares the columns it reads (owner / care_of / mail /
    mail_state / situs / situs_match / parcel / order_by), so the list is
    derivable and no county needs a hand-maintained string. This matters for
    privacy, not tidiness: 14 of 17 counties previously fell through to "*", so
    the day any county layer gains an SSN, DOB or customer-contact column we
    would have started pulling it silently. An explicit spec `out_fields` still
    wins, but is filtered through _FORBIDDEN_FIELD the same way.
    """
    explicit = spec.get("out_fields")
    if explicit and explicit != "*":
        names = [f.strip() for f in str(explicit).split(",") if f.strip()]
    else:
        names = []
        for key in ("owner", "mail", "situs"):
            names += list(spec.get(key) or [])
        for key in ("care_of", "mail_state", "situs_match", "parcel", "order_by", "county_field"):
            v = spec.get(key)
            if v:
                names.append(v)
    seen: set[str] = set()
    safe: list[str] = []
    for n in names:
        if n in seen or n == "*" or _FORBIDDEN_FIELD.search(n):
            continue
        seen.add(n)
        safe.append(n)
    # A spec with nothing declared would otherwise become an empty outFields,
    # which ArcGIS treats as "*". Fall back to the parcel key alone.
    return ",".join(safe) or (spec.get("parcel") or "OBJECTID")


async def _scan(http: httpx.AsyncClient, spec: dict, where: str) -> list[dict]:
    """Page a candidate set up to _SITUS_SCAN_CAP rows.

    Stops on the server's exceededTransferLimit=False (or a short/empty page) so
    a full-but-final page doesn't cost an extra round trip per lead."""
    out_fields = _spec_out_fields(spec)
    order_by = spec.get("order_by") or spec.get("parcel", "")
    rows: list[dict] = []
    while len(rows) < _SITUS_SCAN_CAP:
        page, more = await _query_page(http, spec["url"], where, out_fields,
                                       count=_SITUS_PAGE, offset=len(rows),
                                       order_by=order_by)
        if not page:
            break
        rows.extend(page)
        if not more or len(page) < _SITUS_PAGE:
            break
    return rows


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
    re.compile(r"^(total_?market_?value|market_?value|mrkt_?value)$", re.I),           # Buncombe TotalMarketValue; Anderson/SCDOT MRKT_VALUE
    re.compile(r"^(appraised_?value|apprval|appr_?val)$", re.I),                       # Buncombe AppraisedValue
    re.compile(r"^(total_?tax_?value|cost_?total_?value|total_?value|totval|totalvalue|parval|present_?val|presentval)$", re.I),  # Polk/Henderson/Lincoln/Gaston + NC OneMap parval/presentval
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


# 2026-06-22: county CAMA distress signals (the "D" ask — ROD-adjacent data via a
# clean ArcGIS layer instead of the broken Spartanburg deeds portal). Pattern-
# matched so any CAMA layer carrying these fields benefits (Spartanburg's
# Parcel_and_CAMA layer has them all). Conservative: only KNOWN poor-condition
# codes flag distress, and owner-occupancy is only asserted on an explicit
# homestead marker (blank is the majority, so blank != absentee).
_HOMESTEAD_PAT = re.compile(r"^(homestead.*|hmstd.*|owner_?occ.*|oo_?flag)$", re.I)
_CONDITION_PAT = re.compile(r"^(condition.*|cond_?cd|cond_?code|bldg_?cond.*|cdu)$", re.I)
_SALEDATE_PAT = re.compile(r"^(sale_?date|saledate|last_?sale_?date|deed_?date|transfer_?date)$", re.I)
_SALEAMT_PAT = re.compile(r"^(sale_?amt|sale_?amount|saleamount|sale_?price|saleprice|last_?sale_?(amount|price))$", re.I)
_DEEDBOOK_PAT = re.compile(r"^(deed_?book|deedbook)$", re.I)
_DEEDPAGE_PAT = re.compile(r"^(deed_?page|deedpage)$", re.I)
_PREVOWNER_PAT = re.compile(r"^(previous_?ow.*|prev_?ow.*|prior_?ow.*|former_?ow.*)$", re.I)

_POOR_CONDITION = {"PR", "VP", "DL", "UN", "POOR", "VERY POOR", "DILAPIDATED",
                   "UNSOUND", "UNSAFE", "BAD"}
_OWNER_OCC_VALUES = {"H", "Y", "YES", "1", "HS", "HX", "TRUE", "OO"}


def _first_match(attrs: dict, pat) -> Optional[str]:
    for k, v in (attrs or {}).items():
        if pat.match(k or "") and v not in (None, "", " "):
            return str(v).strip()
    return None


def _extract_distress(attrs: dict) -> dict:
    """ROD-adjacent distress signals from a CAMA parcel record (or {})."""
    if not attrs:
        return {}
    out: dict = {}
    hs = _first_match(attrs, _HOMESTEAD_PAT)
    if hs is not None and hs.upper() in _OWNER_OCC_VALUES:
        out["owner_occupied"] = True   # authoritative: suppress false absentee
    cond = _first_match(attrs, _CONDITION_PAT)
    if cond:
        out["condition_code"] = cond
        if cond.upper() in _POOR_CONDITION:
            out["condition_distressed"] = True
    sd = _first_match(attrs, _SALEDATE_PAT)
    if sd:
        out["last_sale_date"] = sd
    sa = _first_match(attrs, _SALEAMT_PAT)
    if sa:
        try:
            amt = float(str(sa).replace(",", "").replace("$", ""))
            if amt > 0:
                out["last_sale_amount"] = amt
                if amt < 1000:   # nominal/quitclaim consideration (informational)
                    out["nominal_transfer"] = True
        except (ValueError, TypeError):
            pass
    book, page = _first_match(attrs, _DEEDBOOK_PAT), _first_match(attrs, _DEEDPAGE_PAT)
    if book and page:
        out["deed_ref"] = f"{book}/{page}"
    prev = _first_match(attrs, _PREVOWNER_PAT)
    if prev:
        out["previous_owner"] = prev
    return out
    return None


# NC OneMap statewide parcel FeatureService — one consistent owner+mailing+value
# (parval) schema across ALL 100 NC counties. Used as a per-county FALLBACK for
# NC listings the county-specific layer didn't resolve, and for counties whose
# own layer has no value field (e.g. Mitchell). MUST be county-filtered (it's
# statewide, so a street-name match would otherwise hit another county's parcel).
NC_ONEMAP = {
    "url": "https://services.nconemap.gov/secure/rest/services/NC1Map_Parcels/FeatureServer/1",
    "owner": ["ownname", "ownname2"],
    "mail": ["mailadd", "munit", "mcity", "mstate", "mzip"], "mail_state": "mstate",
    "situs": ["siteadd"], "parcel": "parno", "county_field": "cntyname",
    "source_label": "nc_onemap",
}

# SCDOT statewide SC_Parcels MapServer — one owner+mailing+value schema for ALL
# 46 SC counties, on a per-county layer index. Verified live 2026-06-25: every
# layer exposes OWNER / OWNER_ADDR / CITY / ZIPCODE / PHYS_ADDR (situs) /
# MRKT_VALUE, keyed on a digits-only TMS. Used as the SC analogue of NC OneMap:
# the contactability path for SC counties with NO dedicated COUNTY_GIS layer
# (Anderson, Greenville, Beaufort, Cherokee, York, Lexington, Richland, …) and a
# value/owner fallback for covered SC counties that didn't resolve. CITY here is
# "CITY  STATE" (e.g. "ANDERSON  SC") so we derive mail_state from its suffix.
SCDOT_SC_BASE = "https://smpesri.scdot.org/arcgis/rest/services/GISMapping/SC_Parcels/MapServer"
SCDOT_SC_LAYER: dict[str, int] = {
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


def _scdot_spec(county: str) -> Optional[dict]:
    """Build an owner_mailing spec for the SCDOT statewide layer of `county`."""
    layer = SCDOT_SC_LAYER.get((county or "").strip().title())
    if layer is None:
        return None
    return {
        "url": f"{SCDOT_SC_BASE}/{layer}",
        "owner": ["OWNER"],
        "mail": ["OWNER_ADDR", "CITY", "ZIPCODE"],  # CITY already carries "  SC"
        "situs": ["PHYS_ADDR"], "parcel": "TMS",
        "source_label": "scdot_sc",
    }

_STREET_STOPWORDS = ("rd", "dr", "st", "ln", "ave", "ct", "way", "cir",
                     "blvd", "pl", "trl", "hwy", "pkwy", "n", "s", "e", "w")


def _county_clause(spec: dict, li: Listing) -> str:
    """Extra WHERE clauses: pin a statewide layer to the listing's county, and
    apply any per-layer row filter (`where_suffix`, e.g. Spartanburg's
    CardNumber=1, which keeps card-level layers from returning duplicate cards)."""
    cf = spec.get("county_field")
    cty = (li.county or "").strip()
    out = f" AND UPPER({cf})='{cty.upper()}'" if cf and cty else ""
    if spec.get("where_suffix"):
        out += f" AND {spec['where_suffix']}"
    return out


async def _match_attrs(http: httpx.AsyncClient, li: Listing, spec: dict) -> Optional[dict]:
    """Find the parcel record for a listing in one GIS layer (parcel match,
    then situs street-name match), county-filtered when the layer is statewide."""
    cc = _county_clause(spec, li)
    # 1) exact parcel match if we already have a parcel id. Try each candidate
    #    format (raw dashed → suffix-trimmed → stripped) because parcel layers
    #    differ on whether they store the TMS/PIN with or without separators.
    if li.parcel_id:
        for cand in _pid_variants(li.parcel_id):
            safe = cand.replace("'", "''")
            rows = await _query(http, spec["url"], f"{spec['parcel']} LIKE '%{safe}%'{cc}",
                                _spec_out_fields(spec))
            if rows:
                return rows[0]
    # 2) else match on situs street address. Query the street-NAME field broadly
    #    (the longest, most distinctive street word) so format differences don't
    #    block the hit, then verify house-number + street client-side.
    if spec.get("situs") and li.street_address:
        m = _NUM_STREET.match(li.street_address)
        if m:
            num = m.group(1)
            words = [w for w in _norm(m.group(2)).split() if w not in _STREET_STOPWORDS]
            if words:
                mfield = spec.get("situs_match", spec["situs"][0])
                key = max(words, key=len)  # most distinctive street word
                rows = await _scan(http, spec,
                                   f"UPPER({mfield}) LIKE '%{key.upper()}%'{cc}")
                for row in rows:
                    rs = _norm(_join(row, spec["situs"]))
                    if _has_house_number(num, rs) and all(w in rs for w in words):
                        return row
                for row in rows:  # looser: number + the key word
                    rs = _norm(_join(row, spec["situs"]))
                    if _has_house_number(num, rs) and key in rs:
                        return row
    return None


def _build_result(li: Listing, spec: dict, attrs: dict) -> Optional[dict]:
    owner = _join(attrs, spec["owner"], dedupe=True)
    if spec.get("care_of") and attrs.get(spec["care_of"]):
        mailing = f"C/O {attrs[spec['care_of']]}, " + _join(attrs, spec["mail"])
    else:
        mailing = _join(attrs, spec["mail"])
    mailing = _clean_mailing(mailing)
    situs = _join(attrs, spec["situs"]) if spec.get("situs") else None
    parcel = str(attrs.get(spec["parcel"]) or "").strip() or None
    mail_state = (attrs.get(spec.get("mail_state", "")) or "").strip().upper() if spec.get("mail_state") else None
    # Layers without a discrete state field (e.g. SCDOT, where CITY is
    # "ANDERSON  SC") — recover the 2-letter state from the mailing tail.
    if not mail_state and mailing:
        m = re.search(r"\b([A-Z]{2})\b(?:\s+\d{5}(?:-\d{4})?)?\s*$", mailing.upper())
        if m:
            mail_state = m.group(1)
    if not owner and not mailing:
        return None
    # absentee = owner mails from somewhere other than the property; out_of_state
    # = mails from a different state. Prefer the GIS situs; fall back to the
    # listing's own street address (no-situs counties).
    prop_addr = situs or (li.street_address or None)
    return {"owner": owner or None, "mailing": mailing or None, "situs": situs,
            "parcel_id": parcel, "mail_state": mail_state or None,
            "absentee": _is_absentee(prop_addr, mailing),
            "out_of_state": bool(mail_state and li.state and mail_state != li.state),
            "source": spec.get("source_label", "county_gis"),
            "_specs": _extract_specs(attrs), "_value": _extract_value(attrs),
            "_distress": _extract_distress(attrs)}


def _county_key(li: Listing) -> str:
    """COUNTY_GIS lookup key. `.title()` mangles intercaps ('mcdowell' →
    'Mcdowell' ≠ 'McDowell'), so normalize a small set of known intercap
    county names before keying."""
    cty = (li.county or "").strip().title()
    cty = {"Mcdowell": "McDowell", "Mccormick": "McCormick",
           "Mcduffie": "McDuffie", "Mcdowel": "McDowell"}.get(cty, cty)
    return f"{li.state}:{cty}"


# --- local bulk assessor rolls (Spartanburg + Anderson) --------------------------
# The two biggest SC mailing gaps publish their FULL county roll for free
# (sc_parcel_mailing). Reading the cached table first is exact-key, offline and
# ~1000x cheaper than a per-lead ArcGIS LIKE, and it is the ONLY path that covers
# Anderson county-wide (SCDOT statewide is now token-walled).
_BULK_COUNTIES: Optional[set[tuple[str, str]]] = None


def _bulk_counties() -> set[tuple[str, str]]:
    global _BULK_COUNTIES
    if _BULK_COUNTIES is None:
        try:
            from . import sc_parcel_mailing as _pm
            _BULK_COUNTIES = _pm.covered_counties()
        except Exception:  # noqa: BLE001 — table absent/unreadable: fall through to live GIS
            _BULK_COUNTIES = set()
    return _BULK_COUNTIES


def _from_bulk_roll(li: Listing) -> Optional[dict]:
    key = (li.state or "", (li.county or "").strip().title())
    if key not in _bulk_counties():
        return None
    from . import sc_parcel_mailing as _pm
    rec = _pm.lookup(key[0], key[1], parcel_id=li.parcel_id,
                     street_address=li.street_address, zip_code=li.zip_code)
    if not rec:
        return None
    mailing = rec.get("mailing") or None
    owner = rec.get("owner") or rec.get("taxpayer") or None
    if not owner and not mailing:
        return None
    situs = rec.get("situs_street") or rec.get("situs") or None
    mail_state = (rec.get("mail_state") or "").strip().upper() or None
    prop_addr = situs or (li.street_address or None)
    specs = {k: v for k, v in (("living_sqft", rec.get("living_sqft")),
                               ("year_built", rec.get("year_built")),
                               ("bedrooms", rec.get("beds")),
                               ("bathrooms", rec.get("baths"))) if v}
    distress = {k: v for k, v in (("condition_code", rec.get("condition_code")),
                                  ("last_sale_date", rec.get("sale_date")),
                                  ("last_sale_amount", rec.get("sale_amount")),
                                  ("deed_ref", rec.get("deed_ref")),
                                  ("previous_owner", rec.get("prev_owner"))) if v}
    if rec.get("condition_distressed"):
        distress["condition_distressed"] = True
    return {"owner": owner, "mailing": mailing, "situs": situs,
            "parcel_id": rec.get("parcel_raw") or rec.get("parcel_key") or None,
            "mail_state": mail_state,
            "absentee": _is_absentee(prop_addr, mailing),
            "out_of_state": bool(mail_state and li.state and mail_state != li.state),
            "source": "sc_assessor_roll",
            "_specs": specs, "_value": rec.get("market_value"), "_distress": distress}


async def _resolve_one(http: httpx.AsyncClient, li: Listing) -> Optional[dict]:
    # 0) local bulk assessor roll — offline exact-key hit, no request at all.
    res = _from_bulk_roll(li)
    if res:
        return res
    # 1) county-specific layer (richer — has building specs/CAMA where available)
    res = None
    spec = COUNTY_GIS.get(_county_key(li))
    if spec:
        attrs = await _match_attrs(http, li, spec)
        if attrs:
            res = _build_result(li, spec, attrs)

    if li.state == "NC" and li.county:
        if res is None:
            # 2a) full NC OneMap fallback — county layer didn't resolve at all.
            attrs = await _match_attrs(http, li, NC_ONEMAP)
            if attrs:
                res = _build_result(li, NC_ONEMAP, attrs)
        elif not res.get("_value"):
            # 2b) county layer resolved owner but has NO value field (e.g.
            #     Mitchell) — supplement the value (parval) from NC OneMap.
            attrs = await _match_attrs(http, li, NC_ONEMAP)
            if attrs:
                v = _extract_value(attrs)
                if v:
                    res["_value"] = v
                    res["value_source"] = "nc_onemap"

    if li.state == "SC" and li.county and res is None:
        # 3) SCDOT statewide SC fallback — the contactability path for SC
        #    counties with no dedicated COUNTY_GIS layer (Anderson, Greenville,
        #    Beaufort, Cherokee, …) and for covered SC counties the dedicated
        #    layer didn't resolve. Same owner+mailing+value shape, keyed on TMS.
        sspec = _scdot_spec(li.county)
        if sspec:
            attrs = await _match_attrs(http, li, sspec)
            if attrs:
                res = _build_result(li, sspec, attrs)
    return res


async def enrich_owner_mailing(listings: list[Listing], max_concurrency: int = 4) -> dict:
    """Fill owner + mailing + absentee/out-of-state + parcel_id from county GIS."""
    def _reachable(li: Listing) -> bool:
        # Dedicated county layer, OR an NC OneMap / SCDOT statewide fallback.
        if _county_key(li) in COUNTY_GIS:
            return True
        if li.state == "NC" and li.county:
            return True  # NC OneMap covers all 100 NC counties
        if li.state == "SC" and _scdot_spec(li.county or "") is not None:
            return True  # SCDOT covers all 46 SC counties
        return False

    def _has_mailing(li) -> bool:
        # owner_mailing is usually a dict but some sources (spartanburg_vacant,
        # spartanburg_condemned, spartanburg_delinquent_tax) emit a bare string
        # that IS the mailing address. `or {}` can't rescue a truthy str, so an
        # unguarded .get() raised AttributeError and killed the whole pass.
        om = (li.raw or {}).get("owner_mailing")
        if isinstance(om, dict):
            return bool(om.get("mailing"))
        return bool(om)

    targets = [li for li in listings
               if _reachable(li)
               and (li.street_address or li.parcel_id)
               and not _has_mailing(li)]
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
                # CAMA distress signals (the "D" ask via clean ArcGIS): record
                # them for the operator and feed scoring. Owner-occupancy is
                # authoritative, so it SUPPRESSES a false-positive absentee flag;
                # known poor condition raises the PROPERTY distress signal.
                dist = res.pop("_distress", None) or {}
                if dist:
                    li.raw["cama"] = dist
                    if dist.get("owner_occupied") and res.get("absentee"):
                        res["absentee"] = False
                        counts["owner_occ_suppressed"] = counts.get("owner_occ_suppressed", 0) + 1
                    if dist.get("condition_distressed"):
                        li.raw["distressed"] = True
                        counts["condition_distress"] = counts.get("condition_distress", 0) + 1
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
