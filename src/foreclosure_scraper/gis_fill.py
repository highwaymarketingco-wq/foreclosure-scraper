"""County parcel-record fill: deed book/page, short legal description, assessed value, acreage.

WHY (top-80 build list 2026-10-09, group "fill": items 1, 5, 9, 22, 27, 59). The attorney's checklist
(atty_deed_ref, atty_legal_description) and the field cube (assessed_value, lot_size, parcel_id) were
open in 150+ county cells although the county's own free parcel layer carries the facts. This module
reads them, one batched request per 40 parcels, for the parcels the board already holds.

SOURCES (all free, open ArcGIS REST, no key, no login, no CAPTCHA; field names read off each layer's
own field list and a live sample 2026-10-09):
  NC   every county   NC OneMap statewide parcels (NC1Map_Parcels/FeatureServer/1): sourceref (the
                      assessor's deed 'Book/Page'), sourcedatx / saledatetx, legdecfull (the
                      assessor's SHORT legal), parval, gisacres. One service for all 100 counties.
  SC   SC_FILL below  the county's own layer (the same endpoints parcel_cache.PARCEL_LAYERS uses, plus
                      the ones the 10/9 source hunt found open). A county with no open layer, a
                      token-walled layer or a layer without the field is NOT guessed at: it is
                      listed in NOT_FILLABLE with the reason (those cells are verdicts).

WHAT IT WRITES (missing-only; a value already on the row is never overwritten):
  raw['county_deed_ref']  {source, parno, book, page, date, fetched_at}  (the key lawyer_lane reads)
  raw['county_legal']     {source, text, kind: 'assessor_short_legal', parno, fetched_at}
                          NOT the deed's full legal (the image has that); the sheet says so.
  raw['gis_fill']         {checked_at, source, found, deed, legal, value, acres}: the dated screen.
                          found = the parcel was in the layer; each of deed / legal / value / acres is
                          'found', 'none' (the county record has it blank for this parcel: a per-row
                          'screened, none found' verdict the cube counts) or 'skip' (not asked).
  li.assessed_value / li.market_value / li.acreage  when empty and the layer carries a plausible one.
li.legal_description is NOT touched (enrichment flags read it as notice text).

POLITENESS: at least MIN_GAP_S (2 s) between two requests to one host, one at a time per host (a host
lock), the ordinary browser headers the register adapters send, POST with form fields (the id lists
are long), 40 parcels per request, a wall-clock budget (FORECLOSURE_GIS_FILL_BUDGET_S, default 2400),
counties served round-robin so a short budget thins every county instead of starving the last ones.
A layer that answers an error object (token required, 4xx/5xx) twice is closed for the run and listed
in the stats; nothing retries or works around it.

FLAG: FORECLOSURE_GIS_FILL (default 1). Wiring line: docs/audit_2026-10-09/top80_fill.md.
"""
from __future__ import annotations

import asyncio
import os
import re
import threading
import time
from datetime import datetime, timedelta, timezone
from typing import Any, Callable, Iterable, Optional
from urllib.parse import urlsplit

import structlog

log = structlog.get_logger()

NC_URL = "https://services.nconemap.gov/secure/rest/services/NC1Map_Parcels/FeatureServer/1/query"
NC_FIELDS = "parno,altparno,cntyname,sourceref,sourcedatx,saledatetx,legdecfull,parval,gisacres"
#: parcels per request (id lists go in a POST body)
BATCH = 40
#: at least this many seconds between two requests to one host
MIN_GAP_S = 2.0
#: a row screened this recently is not asked again
RECHECK_DAYS = 45
#: the cube columns a per-row 'screened, none found' verdict closes (see verdict_columns)
VERDICT_COLUMNS = ("atty_deed_ref", "atty_legal_description", "assessed_value", "lot_size")

_ENV_FLAG = "FORECLOSURE_GIS_FILL"
_ENV_BUDGET = "FORECLOSURE_GIS_FILL_BUDGET_S"

# ---------------------------------------------------------------------------------------------
# the SC registry
# ---------------------------------------------------------------------------------------------
# keys: url (the layer's /query), ids (id fields, tried in order), book/page (separate fields; a list
# is tried in order as (book, page) pairs), combined ('695-194' style), date, legal (fields joined),
# market / assessed (value fields), acres (fields, first plausible wins).
SC_FILL: dict[str, dict] = {
    "Aiken": dict(
        url="https://gis.cityofaikensc.gov/arcgis/rest/services/PublicGIS/MapServer/13/query",
        ids=["PARCEL_ASR", "PARC_NO"], combined="SaleBookPage", date="SaleDate",
        legal=["LegalDescription"], market="TotalMarketValue", assessed="AssessedValue",
        acres=["Acres", "Calc_Acres"]),
    "Barnwell": dict(
        url="https://services8.arcgis.com/qqnlHdXochyJPfSY/arcgis/rest/services/ParcelData_ExportFeatures/FeatureServer/2/query",
        ids=["TaxPIN", "Map_Number"], book="Deed_Book", page="Deed_Page", date="Deed_Ref_Dt_YYYYMMDD",
        legal=["Legal_Description1", "Legal_Description2"], assessed="Tot_Assesd_Value",
        acres=["Tot_Number_Acres"]),
    "Berkeley": dict(
        url="https://gis.berkeleycountysc.gov/arcgis/rest/services/internet/MapServer/4/query",
        ids=["O_TMS", "O_TMS_NODASH"], book="DeedBook", page="DeedPage", date="SaleDate",
        market="TotalTaxValue", acres=["TotalAcres"]),
    "Darlington": dict(
        url="https://services5.arcgis.com/8FJikaProY6O3ncx/arcgis/rest/services/PARCELS/FeatureServer/1/query",
        ids=["MBP", "Map_Number"], book="Deed_Book", page="Deed_Page_", legal=["LEGAL1", "LEGAL2"],
        market="TOT_MARKET", assessed="ASSESSED_V", acres=["GIS_ACRES"]),
    "Dorchester": dict(
        url="https://gisportal.dorchestercounty.net/hosting/rest/services/General_Data/Parcels_Public/MapServer/0/query",
        ids=["FULL_TMS", "TMS", "PARCELNO"], combined="DEED", date="SALE_DATE",
        acres=["TAXED_ACRES", "GIS_ACREAGE"]),
    "Greenville": dict(
        url="https://www.gcgis.org/arcgis3/rest/services/GreenvilleNJ/QueryLayers/MapServer/0/query",
        ids=["PIN"], book="CUBOOK", page="CUPAGE", date="DEEDDATE", legal=["DESCR"], acres=["TACRES"]),
    "Greenwood": dict(
        url="https://www.greenwoodsc.gov/arcgis/rest/services/Operational_Layers/CAMA/MapServer/9/query",
        ids=["PIN"], combined="Deed", date="PurchaseDate", legal=["Description"],
        market="MarketValue_Total", assessed="AssessedValue", acres=["DeedAcres"]),
    "Hampton": dict(
        url="https://services8.arcgis.com/6eabNhFouHU5vuYk/arcgis/rest/services/Parcels_Published_view/FeatureServer/1/query",
        ids=["Map_Number", "Parcel_polygons_TMS"], book="Deed_Book", page="Deed_Page", date="Instrmnt_Dt",
        market="Tot_Market_Appr", assessed="Tot_Assesd_Value", acres=["Tot_Number_Acres"]),
    "Horry": dict(
        url="https://www.horrycountysc.gov/parcelapp/rest/services/HorryCountyGISApp/MapServer/24/query",
        ids=["PINtext", "PIN", "TMS"], book="DeedBook", page="DeedPage", date="SaleDate",
        legal=["LegalDescr"], market="MarketProp", assessed="AssessedProp", acres=["Acreage"]),
    "Lancaster": dict(
        url="https://services3.arcgis.com/rJcpRneDUBgTeCT3/arcgis/rest/services/LC_Parcels/FeatureServer/0/query",
        ids=["PIN", "PIN2"], book="DEED_BOOK", page="DEED_PAGE", acres=["ACRES", "GIS_Acres"]),
    "Lexington": dict(
        url="https://maps.lex-co.com/agstserver/rest/services/Property/MapServer/4/query",
        ids=["TMS", "TMS_No_Dash"], book=["CAMA_DeedBook", "TM_DeedBook"],
        page=["CAMA_DeedPage", "TM_DeedPage"], date="SaleDate", legal=["Legal_1_2", "Legal_3"],
        market="MktTotal", acres=["Acres"]),
    "Saluda": dict(
        url="https://saludacountysc.net/arcgis/rest/services/ParcelViewers/PublicWebsite_Pro/MapServer/4/query",
        ids=["SDE.DBO.Parcels.TaxMapNumber", "SDE.DBO.AssessorData.Map_Number"],
        book="SDE.DBO.AssessorData.Deed_Book", page="SDE.DBO.AssessorData.Deed_Page",
        legal=["SDE.DBO.AssessorData.Legal_Description1", "SDE.DBO.AssessorData.Legal_Description2"],
        assessed="SDE.DBO.AssessorData.Tot_Assesd_Value", acres=["SDE.DBO.AssessorData.Tot_Number_Acres"]),
    "Sumter": dict(
        url="https://gis.sumter-sc.com/server/rest/services/BaseMaps/Sumter_City_County/FeatureServer/7/query",
        ids=["parid", "parcel_number"], book="deed_book", page="deed_page", legal=["legal_description"],
        market="market_value_total", acres=["deedacre"]),
    "York": dict(
        url="https://services1.arcgis.com/2AGLxyiJoNiVHKwq/arcgis/rest/services/Parcels/FeatureServer/0/query",
        ids=["ParcelID", "TAXMAPID", "AprAccNum"], book="TransferBook", page="TransferPage",
        legal=["LegalDescription"], market="AprTotVal", acres=["deededacres"]),
    # Orangeburg SC: owner / mailing / acres only (the layer has no value, deed or legal field)
    "Orangeburg": dict(
        url="https://services2.arcgis.com/bUKn95BqgpYYTnx3/arcgis/rest/services/Main_Public_Tax_Parcel_Map_WFL1/FeatureServer/0/query",
        ids=["MAPBLOLOT", "parcel_id"], acres=["CalculatedAcres"]),
    # Beaufort SC: the EnerGov service parcel_cache.SC_DUAL_LAYERS reads (open, no token)
    "Beaufort": dict(
        url="https://gis.beaufortcountysc.gov/server/rest/services/EnerGov/MapServer/1/query",
        ids=["GisFile_PIN", "ParcelPIN"], book="GisFile_Book", page="GisFile_Page", date="GisFile_SaleDate",
        legal=["GisFile_LegalDescr"], market="GisFile_Appraised", assessed="GisFile_Assessed",
        acres=["GisFile_Acres"]),
}

#: counties where a cube cell stays open because the county has no usable free source for the field,
#: with the reason (the build list items that end as verdicts, not builds). county -> {column: reason}
NOT_FILLABLE: dict[tuple[str, str], dict[str, str]] = {}


def _nf(state: str, counties: Iterable[str], cols: Iterable[str], reason: str) -> None:
    for c in counties:
        NOT_FILLABLE.setdefault((state, c), {}).update({col: reason for col in cols})


_QPUBLIC = ("the county's only parcel viewer is Schneider qPublic/Beacon, which answers scripts with a "
            "Cloudflare 'Just a moment' check (2026-10-07 county records matrix; walls_register card "
            "sc_qpublic has the owner's steps)")
_nf("SC", ("Clarendon", "Edgefield", "Fairfield", "Lee"), ("assessed_value", "lot_size"), _QPUBLIC)
_nf("SC", ("Chesterfield", "Marion", "Williamsburg"), ("assessed_value", "lot_size"),
    "the county's only viewer is a WTH 'tgis' map shell with no open ArcGIS parcel REST layer "
    "(parcel_cache.py research note, 2026-09-21; re-read in the 2026-10-07 county records matrix)")
_nf("SC", ("Jasper",), ("assessed_value", "lot_size"),
    "the layer parcel_cache reads now answers 'Token Required' (2026-10-09); the public June-17 copy of "
    "the same service has market value and acres and is read here (SC_FILL_EXTRA), for the 2 in 8 sampled "
    "board parcels it holds")
_nf("SC", ("Dorchester", "Lancaster", "Colleton"), ("assessed_value",),
    "the county's open parcel layer carries no value field (fields read 2026-10-09)")
_nf("SC", ("Florence",), ("assessed_value",),
    "the county's open layer publishes TOTBDGVAL, the BUILDING value only (no land value), which is not "
    "an assessed or market value (parcel_cache.py note; fields read 2026-10-09)")
_nf("SC", ("Florence", "Colleton"), ("atty_deed_ref", "atty_legal_description"),
    "the county's open parcel layer carries no deed or legal field (fields read 2026-10-09)")
_nf("SC", ("Dorchester", "Lancaster", "Hampton"), ("atty_legal_description",),
    "the county's open parcel layer carries no legal-description field (fields read 2026-10-09)")
_nf("SC", ("Orangeburg",), ("assessed_value", "atty_deed_ref", "atty_legal_description"),
    "the county's open Tax Parcel layer (Main_Public_Tax_Parcel_Map_WFL1) carries parcel number, owner "
    "and acres only (fields read 2026-10-09); the value is on the qPublic card (walls_register sc_qpublic)")
_nf("SC", ("Newberry",), ("assessed_value", "lot_size"),
    "the county's own parcel service (map.newberrycounty.net PropertyParcel/MapServer) answers 'Service "
    "not started' (HTTP 500, 2026-10-09); no other open layer exists (matrix 2026-10-07)")
_PID_NAME_ONLY = ("the rows carry a name only (probate / newspaper notices, HUD REAC property names, "
                  "state tax-lien registry): no street address, no precise point, and an owner-name match to "
                  "the county layer found 0 unique parcels of the {n} names that could be matched "
                  "(Aiken 31, Orangeburg 31, 2026-10-09 checkpoint; most are ambiguous)")
_nf("SC", ("Aiken",), ("parcel_id",), _PID_NAME_ONLY.format(n=31))
_nf("SC", ("Hampton", "Marion"), ("parcel_id",), "the rows carry a name only (state tax-lien registry, bankruptcy "
    "filing, probate notice): no address, no precise point; Marion has no open parcel layer to match against")
_nf("SC", ("Orangeburg",), ("parcel_id",), _PID_NAME_ONLY.format(n=31) +
    "; the 93 qPayBill roll rows are the exception: their account number joins the county layer exactly "
    "(enrich_account_parcels, 78 of 93 resolved on 2026-10-09)")

#: Jasper: parcel_cache's own layer is token-walled; this is the public copy of the same county service
SC_FILL_EXTRA: dict[str, dict] = {
    "Jasper": dict(
        url="https://services6.arcgis.com/UXJOITFCLbn0Ibm0/arcgis/rest/services/sde_SDE_JasperCounty_Parcels_June17/FeatureServer/2/query",
        ids=["TaxPIN", "TMS"], book="DeedBook", page="DeedPage", date="InstrmntDt",
        market="TotMarketA", acres=["TotNumberA"]),
}
SC_FILL.update(SC_FILL_EXTRA)


def sc_spec(county: str) -> Optional[dict]:
    return SC_FILL.get(str(county or "").strip().title())


# ---------------------------------------------------------------------------------------------
# pure parsers (tested on made-up fixtures)
# ---------------------------------------------------------------------------------------------

def pin_key(s: Any) -> str:
    """Letters and digits only, upper case: the join key between the board's and a layer's ids."""
    return re.sub(r"[^A-Za-z0-9]", "", str(s or "")).upper()


_ZERO_SUFFIX = re.compile(r"[-. ]0{2,4}$")


def pin_aliases(pin: Any) -> list[str]:
    """The join keys of a board parcel id: its letters-and-digits key, and, when it ends in a separated
    sub-parcel group of zeros ('4738-71-6101-00'), the key of the main parcel ('4738716101', at least 8
    characters). The layer's own ids are joined on the same keys."""
    s = str(pin or "").strip()
    out = [pin_key(s)]
    if re.fullmatch(r"\d{10}", out[0]):
        out.append(out[0] + "00000")      # Buncombe: the 10-digit index PIN is the 15-digit parno's head
    if _ZERO_SUFFIX.search(s):
        k2 = pin_key(_ZERO_SUFFIX.sub("", s))
        if len(k2) >= 8 and k2 not in out:
            out.append(k2)
    return out


def pin_literals(pin: str) -> list[str]:
    """The PIN as the board writes it plus its letters-and-digits form, for an IN (...) list."""
    raw = str(pin or "").strip()
    main = _ZERO_SUFFIX.sub("", raw) if _ZERO_SUFFIX.search(raw) and len(pin_key(_ZERO_SUFFIX.sub("", raw))) >= 8 else ""
    out = []
    for v in (raw, pin_key(raw), main, pin_key(main) if main else ""):
        v = v.replace("'", "")
        if v and v not in out:
            out.append(v)
    return out


def _z(s: Any) -> Optional[str]:
    """'000246' -> '246'; '' / '0' / '0000' / 'NA' -> None."""
    t = re.sub(r"\s+", "", str(s if s is not None else "")).upper()
    if t in ("NA", "N/A", "NONE", "NULL", "UNK", "UNKNOWN", "-", "--"):
        return None
    t = t.lstrip("0")
    return t or None


def book_page(book: Any, page: Any) -> Optional[tuple[str, str]]:
    """(book, page) without zero padding when both are usable, else None. A book or page of 0 / blank /
    'NA' is not a deed reference."""
    b, p = _z(book), _z(page)
    if b and p and re.fullmatch(r"[A-Z0-9]{1,8}", b) and re.fullmatch(r"[A-Z0-9]{1,8}", p):
        return b, p
    return None


_COMBINED = re.compile(r"^\s*(?:[A-Za-z ]*Book\s*/?\s*Page:?\s*)?([0-9A-Za-z]{1,8})\s*[-/ ]\s*([0-9]{1,8})\s*$")
_BKPG = re.compile(r"^\s*BK\s*([A-Z0-9]+)\s+PG\s*([A-Z0-9]+)", re.I)


def parse_combined(text: Any) -> Optional[tuple[str, str]]:
    """'695-194' / '5268/1393' / '007687-289' / 'Deed Book/Page 001234/00567' / 'BK 1111 PG 2222' -> (book, page)."""
    s = str(text or "").strip()
    if not s or re.search(r"plat|map", s, re.I):
        return None
    m = _BKPG.match(s)
    if m:
        return book_page(m.group(1), m.group(2))
    m = _COMBINED.match(s)
    return book_page(m.group(1), m.group(2)) if m else None


def parse_nc_ref(sourceref: Any) -> Optional[tuple[str, str]]:
    """The assessor's deed reference on a NC OneMap parcel: 'Deed Book/Page 001234/00567',
    'Sale Book/Page ...', a bare '26972/906'. A plat reference, a book alone ('Guilford: the book only')
    or a blank one is not a deed reference."""
    from .quiet_title.adapters.nc_onemap import parse_ref
    s = str(sourceref or "").strip()
    if not s:
        return None
    word, book, page = parse_ref(s)
    if word:
        if word.lower() not in ("deed", "sale"):
            return None
        return book_page(book, page)
    return parse_combined(s)


def iso_date(v: Any) -> Optional[str]:
    """A layer's date as ISO as precise as written: epoch milliseconds, 'YYYYMMDD', 'M/D/YYYY',
    'YYYY-MM-DD', 'YYYYMM', 'YYYY'. Placeholders (0, 00000000, 12/30/1899, years <= 1900) are not dates."""
    if v is None or isinstance(v, bool):
        return None
    if isinstance(v, (int, float)):
        if v > 10 ** 11:
            try:
                d = datetime.fromtimestamp(v / 1000, timezone.utc).date().isoformat()
            except (OverflowError, OSError, ValueError):
                return None
            return d if int(d[:4]) > 1900 else None
        v = str(int(v))
    from .quiet_title.adapters.nc_onemap import layer_date
    d = layer_date(str(v))
    return d if d and d[:4].isdigit() and int(d[:4]) > 1900 else None


def num(v: Any) -> Optional[float]:
    """A positive number from '4,229,310' / 12700.0 / '$1,200'; None for blanks, zero, junk."""
    if v is None or isinstance(v, bool):
        return None
    try:
        f = float(str(v).replace(",", "").replace("$", "").strip())
    except (ValueError, TypeError):
        return None
    return f if f == f and f > 0 else None


def plausible_value(f: Optional[float]) -> Optional[float]:
    return f if f is not None and 100 <= f <= 5e8 else None


def plausible_acres(f: Optional[float]) -> Optional[float]:
    return f if f is not None and 0 < f <= 100000 else None


_LEGAL_JUNK = re.compile(r"^(n/?a|none|null|unknown|see deed|see plat|tbd|\.+|-+|0+)$", re.I)


def legal_text(*parts: Any) -> Optional[str]:
    """The assessor's short legal from one or more fields: whitespace collapsed, at most 200 chars.
    Blank, a placeholder, or text with fewer than 4 characters / no letter ('7', '1', 'UNIT' alone is
    kept only with a number) is not a legal."""
    bits = []
    for p in parts:
        s = " ".join(str(p if p is not None else "").split())
        if s and not _LEGAL_JUNK.match(s):
            bits.append(s)
    t = " ".join(bits).strip()
    if len(t) < 4 or not re.search(r"[A-Za-z]", t):
        return None
    return t[:200]


def _first(a: dict, names: Iterable[str], fn: Callable[[Any], Any]) -> Any:
    for n in names:
        v = fn(a.get(n))
        if v is not None:
            return v
    return None


def parse_nc_attrs(a: dict) -> dict:
    """{deed: {book, page, date}|None, legal, market, acres} from one NC OneMap attribute bag (pure)."""
    from .quiet_title.adapters.nc_onemap import legal_as_deed_ref
    ref = parse_nc_ref(a.get("sourceref"))
    legal_raw = str(a.get("legdecfull") or "")
    if not ref:
        # Caldwell writes the deed reference in legdecfull ('BK 1111 PG 2222')
        alt = legal_as_deed_ref(legal_raw)
        if alt and alt[0] and alt[1]:
            ref = book_page(alt[0], alt[1])
    legal = None if legal_as_deed_ref(legal_raw) else legal_text(legal_raw)
    date = iso_date(a.get("sourcedatx")) or iso_date(a.get("saledatetx"))
    deed = {"book": ref[0], "page": ref[1], "date": date} if ref else None
    return {"deed": deed, "legal": legal, "market": plausible_value(num(a.get("parval"))),
            "assessed": None, "acres": plausible_acres(num(a.get("gisacres")))}


def parse_sc_attrs(spec: dict, a: dict) -> dict:
    """The same shape from one SC county layer attribute bag (pure)."""
    ref = None
    if spec.get("combined"):
        ref = parse_combined(a.get(spec["combined"]))
    if not ref and spec.get("book"):
        books = spec["book"] if isinstance(spec["book"], list) else [spec["book"]]
        pages = spec["page"] if isinstance(spec["page"], list) else [spec["page"]]
        for b, p in zip(books, pages):
            ref = book_page(a.get(b), a.get(p))
            if ref:
                break
    date = iso_date(a.get(spec["date"])) if spec.get("date") else None
    deed = {"book": ref[0], "page": ref[1], "date": date} if ref else None
    legal = legal_text(*[a.get(f) for f in spec.get("legal") or []]) if spec.get("legal") else None
    return {"deed": deed, "legal": legal,
            "market": plausible_value(num(a.get(spec["market"]))) if spec.get("market") else None,
            "assessed": plausible_value(num(a.get(spec["assessed"]))) if spec.get("assessed") else None,
            "acres": _first(a, spec.get("acres") or [], lambda v: plausible_acres(num(v)))}


def asks(spec: Optional[dict]) -> dict:
    """What a county's layer is asked for: {deed, legal, value, acres} -> bool."""
    if spec is None:
        return {"deed": True, "legal": True, "value": True, "acres": True}
    return {"deed": bool(spec.get("combined") or spec.get("book")), "legal": bool(spec.get("legal")),
            "value": bool(spec.get("market") or spec.get("assessed")), "acres": bool(spec.get("acres"))}


def spec_fields(spec: dict) -> list[str]:
    out: list[str] = []
    for k in ("combined", "date", "market", "assessed"):
        if spec.get(k):
            out.append(spec[k])
    for k in ("book", "page"):
        v = spec.get(k)
        out += v if isinstance(v, list) else ([v] if v else [])
    out += spec.get("legal") or []
    out += spec.get("acres") or []
    out += spec.get("ids") or []
    return list(dict.fromkeys(out))


def build_block(row_state: str, county: str, pin: str, matched: Optional[dict], source: str, now_iso: str,
                want: dict) -> dict:
    """raw['gis_fill'] for one screened parcel (pure). `matched` is parse_*_attrs output or None when the
    parcel was not in the layer. 'none' means the parcel IS in the layer and its record is blank/unusable
    for the field; a field the layer was not asked for is 'skip'."""
    found = matched is not None
    def v(key: str, present: bool, asked: bool) -> str:
        if not asked:
            return "skip"
        if not found:
            return "unknown"
        return "found" if present else "none"
    m = matched or {}
    return {"checked_at": now_iso, "source": source, "found": found,
            "deed": v("deed", bool(m.get("deed")), want["deed"]),
            "legal": v("legal", bool(m.get("legal")), want["legal"]),
            "value": v("value", bool(m.get("market") or m.get("assessed")), want["value"]),
            "acres": v("acres", bool(m.get("acres")), want["acres"])}


def verdict_columns(raw: Any) -> set[str]:
    """The cube columns this row's raw['gis_fill'] gives a per-row 'screened, none found' verdict: the
    parcel was in the county layer and the county record is blank for the field. Pure."""
    g = raw.get("gis_fill") if isinstance(raw, dict) else None
    if not isinstance(g, dict) or not g.get("found") or not g.get("checked_at"):
        return set()
    out = set()
    if g.get("deed") == "none":
        out.add("atty_deed_ref")
    if g.get("legal") == "none":
        out.add("atty_legal_description")
    if g.get("value") == "none":
        out.add("assessed_value")
    if g.get("acres") == "none":
        out.add("lot_size")
    return out


def deed_ref_on_row(raw: Any) -> bool:
    """A usable county_deed_ref (book and page) on a raw dict."""
    c = raw.get("county_deed_ref") if isinstance(raw, dict) else None
    return isinstance(c, dict) and bool(c.get("book") and c.get("page"))


def legal_on_row(raw: Any) -> bool:
    c = raw.get("county_legal") if isinstance(raw, dict) else None
    return isinstance(c, dict) and bool(c.get("text"))


# ---------------------------------------------------------------------------------------------
# transport
# ---------------------------------------------------------------------------------------------

_gate_lock = threading.Lock()
_host_locks: dict[str, threading.Lock] = {}
_last: dict[str, float] = {}
#: test seams
sleep: Callable[[float], None] = time.sleep
clock: Callable[[], float] = time.monotonic
post_fn: Optional[Callable[..., Any]] = None   # tests replace; default requests.post


def _host_lock(host: str) -> threading.Lock:
    with _gate_lock:
        return _host_locks.setdefault(host, threading.Lock())


class LayerClosed(RuntimeError):
    """The layer answered an error object / a non-200 status twice: closed for the run."""


_errors: dict[str, int] = {}
_closed: dict[str, str] = {}


def reset_state() -> None:
    with _gate_lock:
        _errors.clear()
        _closed.clear()
        _last.clear()


def closed_layers() -> dict[str, str]:
    return dict(_closed)


def query(url: str, form: dict) -> Optional[list[dict]]:
    """POST one ArcGIS query; the list of attribute bags ([] when none), or None when the layer did
    not answer usefully (the error is counted; two in a row close the layer for the run)."""
    host = (urlsplit(url).hostname or "").lower()
    if url in _closed:
        return None
    from .rod import nc_polite
    with _host_lock(host):
        wait = MIN_GAP_S - (clock() - _last.get(host, -1e9))
        if wait > 0:
            sleep(wait)
        try:
            fn = post_fn
            if fn is None:
                import requests
                fn = requests.post
            r = fn(url, data=form, headers=nc_polite.HEADERS, timeout=60)
        except Exception as e:  # noqa: BLE001 - one request never stops a pass
            _last[host] = clock()
            return _fail(url, f"{type(e).__name__}")
        finally:
            _last[host] = clock()
    try:
        status = int(r.status_code)
        j = r.json() if status == 200 else None
    except Exception:  # noqa: BLE001
        return _fail(url, "unreadable answer")
    if status != 200 or not isinstance(j, dict):
        return _fail(url, f"HTTP {status}")
    if "error" in j:
        msg = str((j.get("error") or {}).get("message") or (j.get("error") or {}).get("code") or "error")
        return _fail(url, msg[:80])
    _errors[url] = 0
    return [(f.get("attributes") or {}) for f in (j.get("features") or []) if isinstance(f, dict)]


def _fail(url: str, why: str) -> None:
    n = _errors.get(url, 0) + 1
    _errors[url] = n
    if n >= 2:
        _closed[url] = why
        log.warning("gis_fill.layer_closed", url=url.split("?")[0][:100], why=why)
    return None


def nc_where(county: str, pins: list[str]) -> str:
    from .quiet_title.adapters.nc_onemap import pin_variants
    vals: list[str] = []
    for p in pins:
        vals += pin_variants(p)
        if _ZERO_SUFFIX.search(str(p)):
            vals += pin_variants(_ZERO_SUFFIX.sub("", str(p).strip()))
        vals += [a for a in pin_aliases(p)[1:] if a.endswith("00000")]
    inl = ",".join("'" + v.replace("'", "") + "'" for v in dict.fromkeys(vals))
    return f"cntyname='{county}' AND (parno IN ({inl}) OR altparno IN ({inl}))"


def _lookup(pin: str, index: dict[str, dict]) -> Optional[dict]:
    for k in pin_aliases(pin):
        if k in index:
            return index[k]
    return None


def fetch_nc(county: str, pins: list[str]) -> Optional[dict[str, dict]]:
    """{board pin: parse_nc_attrs(...)} for the pins found in the layer; None when the layer did not answer."""
    feats = query(NC_URL, {"where": nc_where(county, pins), "outFields": NC_FIELDS,
                           "returnGeometry": "false", "f": "json"})
    if feats is None:
        return None
    index: dict[str, dict] = {}
    for a in feats:
        parsed = {**parse_nc_attrs(a), "parno": a.get("parno") or a.get("altparno")}
        for f in ("parno", "altparno"):
            k = pin_key(a.get(f))
            if k and (k not in index or (parsed["deed"] and not index[k].get("deed"))):
                index[k] = parsed
    out = {}
    for p in pins:
        m = _lookup(p, index)
        if m is not None:
            out[p] = m
    return out


def fetch_sc(spec: dict, pins: list[str]) -> Optional[dict[str, dict]]:
    """{board pin: parsed} for the pins found, trying each id field for the pins still missing."""
    out: dict[str, dict] = {}
    answered = False
    fields = ",".join(spec_fields(spec))
    for idf in spec["ids"]:
        todo = [p for p in pins if p not in out]
        if not todo:
            break
        vals = ",".join("'" + v + "'" for p in todo for v in pin_literals(p))
        feats = query(spec["url"], {"where": f"{idf} IN ({vals})", "outFields": fields,
                                    "returnGeometry": "false", "f": "json"})
        if feats is None:
            if spec["url"] in _closed:
                break
            continue
        answered = True
        index = {pin_key(a.get(idf)): {**parse_sc_attrs(spec, a), "parno": a.get(idf)} for a in feats
                 if pin_key(a.get(idf))}
        for p in todo:
            m = _lookup(p, index)
            if m is not None:
                out[p] = m
    return out if answered else None


# ---------------------------------------------------------------------------------------------
# the enricher
# ---------------------------------------------------------------------------------------------

def enabled() -> bool:
    return os.environ.get(_ENV_FLAG, "1").strip().lower() not in ("0", "false", "no", "off", "")


def _raw(li: Any) -> dict:
    r = getattr(li, "raw", None)
    return r if isinstance(r, dict) else {}


def _recent(block: Any, days: int, now: datetime) -> bool:
    if not isinstance(block, dict) or not block.get("checked_at"):
        return False
    try:
        t = datetime.fromisoformat(str(block["checked_at"]).replace("Z", "+00:00"))
    except ValueError:
        return False
    if t.tzinfo is None:
        t = t.replace(tzinfo=timezone.utc)
    return now - t < timedelta(days=days)


def _pin_ok(pin: Any) -> bool:
    s = str(pin or "").strip()
    return len(pin_key(s)) >= 5 and bool(re.search(r"\d", s))


def county_name(li: Any) -> str:
    c = re.sub(r"\s+county\s*$", "", str(getattr(li, "county", "") or "").strip(), flags=re.I)
    return c.split(",")[0].strip()


def needs(li: Any, now: datetime) -> bool:
    """A row this module should screen: NC or SC, a usable parcel id, a county it can read, not screened
    recently, and at least one field still missing."""
    st = str(getattr(li, "state", "") or "").upper()
    if st not in ("NC", "SC") or not _pin_ok(getattr(li, "parcel_id", None)):
        return False
    raw = _raw(li)
    if _recent(raw.get("gis_fill"), RECHECK_DAYS, now):
        return False
    co = county_name(li)
    if st == "SC" and not sc_spec(co):
        return False
    if st == "NC":
        from .quiet_title.adapters.nc_onemap import canonical_county
        if not canonical_county(co):
            return False
    spec = sc_spec(co) if st == "SC" else None
    a = asks(spec)
    return bool((a["deed"] and not deed_ref_on_row(raw)) or (a["legal"] and not legal_on_row(raw))
                or (a["value"] and not (getattr(li, "assessed_value", None) or getattr(li, "market_value", None)))
                or (a["acres"] and not (getattr(li, "acreage", None) or getattr(li, "lot_size_sqft", None))))


def apply_one(li: Any, matched: Optional[dict], source: str, county: str, now_iso: str, want: dict) -> dict:
    """Write the fill into one Listing (missing-only) and its raw['gis_fill'] screen; returns counters."""
    raw = dict(_raw(li))
    c = {"deed": 0, "legal": 0, "value": 0, "acres": 0}
    pin = str(getattr(li, "parcel_id", "") or "")
    if matched:
        d = matched.get("deed")
        if d and want["deed"] and not deed_ref_on_row(raw):
            raw["county_deed_ref"] = {"source": source, "parno": matched.get("parno"), "book": d["book"],
                                      "page": d["page"], "date": d.get("date"), "fetched_at": now_iso}
            c["deed"] = 1
        if matched.get("legal") and want["legal"] and not legal_on_row(raw):
            raw["county_legal"] = {"source": source, "kind": "assessor_short_legal", "text": matched["legal"],
                                   "parno": matched.get("parno"), "fetched_at": now_iso}
            c["legal"] = 1
        if matched.get("assessed") and not getattr(li, "assessed_value", None):
            li.assessed_value = matched["assessed"]
            c["value"] = 1
        if matched.get("market") and not getattr(li, "market_value", None):
            li.market_value = matched["market"]
            c["value"] = 1
        if matched.get("acres") and not (getattr(li, "acreage", None) or getattr(li, "lot_size_sqft", None)):
            li.acreage = matched["acres"]
            c["acres"] = 1
    raw["gis_fill"] = build_block(str(getattr(li, "state", "")), county, pin, matched, source, now_iso, want)
    li.raw = raw
    return c


#: Counties whose qPayBill roll names an ACCOUNT number that the county's own parcel layer carries as a
#: field, so the roll row's parcel is an exact key join (not a name match): (state, county) -> layer.
#: Orangeburg SC: the roll's identification_no equals the layer's parcel_id (the CAMA account; 11 of 12
#: sampled roll accounts found, 2026-10-09); the layer's MAPBLOLOT is the TMS in the board's shape.
ACCOUNT_JOIN: dict[tuple[str, str], dict] = {
    ("SC", "Orangeburg"): dict(
        url="https://services2.arcgis.com/bUKn95BqgpYYTnx3/arcgis/rest/services/Main_Public_Tax_Parcel_Map_WFL1/FeatureServer/0/query",
        account="parcel_id", pin="MAPBLOLOT", acres="CalculatedAcres"),
}


def roll_account(li: Any) -> Optional[str]:
    """The qPayBill roll account number on a row (digits), or None."""
    q = _raw(li).get("qpaybill_roll")
    if not isinstance(q, dict):
        return None
    a = re.sub(r"\D", "", str(q.get("identification_no") or ""))
    return a.lstrip("0") or None if a else None


def account_pin(spec: dict, accounts: list[str]) -> Optional[dict[str, dict]]:
    """{account (no leading zeros): {pin, acres}} for the accounts the layer holds exactly once (an
    account on several parcels is not resolved); None when the layer did not answer."""
    vals: list[str] = []
    for a in accounts:
        vals += [a, a.zfill(7), a.zfill(10)]
    inl = ",".join("'" + v + "'" for v in dict.fromkeys(vals))
    feats = query(spec["url"], {"where": f"{spec['account']} IN ({inl})",
                                "outFields": f"{spec['account']},{spec['pin']},{spec['acres']}",
                                "returnGeometry": "false", "f": "json"})
    if feats is None:
        return None
    by: dict[str, list] = {}
    for a in feats:
        k = re.sub(r"\D", "", str(a.get(spec["account"]) or "")).lstrip("0")
        pin = str(a.get(spec["pin"]) or "").strip()
        if k and pin:
            by.setdefault(k, []).append({"pin": pin, "acres": plausible_acres(num(a.get(spec["acres"])))})
    return {k: v[0] for k, v in by.items() if len({x["pin"] for x in v}) == 1}


def _account_rows(listings: list) -> dict[tuple[str, str], dict[str, list]]:
    out: dict[tuple[str, str], dict[str, list]] = {}
    for li in listings:
        if getattr(li, "parcel_id", None) or str(getattr(li, "state", "") or "").upper() != "SC":
            continue
        key = ("SC", county_name(li).title())
        if key not in ACCOUNT_JOIN:
            continue
        a = roll_account(li)
        if a:
            out.setdefault(key, {}).setdefault(a, []).append(li)
    return out


async def enrich_account_parcels(listings: list, stats: dict, t0: float, budget_s: float) -> None:
    """parcel_id for qPayBill roll rows from the county layer's account field (exact key join)."""
    now_iso = datetime.now(timezone.utc).isoformat(timespec="seconds")
    for key, accts in _account_rows(listings).items():
        spec = ACCOUNT_JOIN[key]
        keys = list(accts)
        for i in range(0, len(keys), BATCH):
            if clock() - t0 > budget_s:
                stats["budget_hit"] = True
                return
            got = await asyncio.to_thread(account_pin, spec, keys[i:i + BATCH])
            stats["requests"] += 1
            if got is None:
                break
            for a in keys[i:i + BATCH]:
                hit = got.get(a)
                for li in accts[a]:
                    if not hit:
                        continue
                    li.parcel_id = hit["pin"]
                    raw = dict(_raw(li))
                    raw["parcel_from_account"] = {"source": f"{key[1].lower()}_parcel_layer",
                                                  "join": "qpaybill_roll.identification_no = layer account",
                                                  "fetched_at": now_iso}
                    li.raw = raw
                    if hit.get("acres") and not (getattr(li, "acreage", None) or getattr(li, "lot_size_sqft", None)):
                        li.acreage = hit["acres"]
                        stats["acres"] += 1
                    stats["parcel_from_account"] += 1


def _plan(listings: list, now: datetime) -> dict[tuple[str, str], dict[str, list]]:
    """{(state, county): {pin: [listing, ...]}} for the rows to screen."""
    plan: dict[tuple[str, str], dict[str, list]] = {}
    for li in listings:
        if not needs(li, now):
            continue
        st = str(li.state).upper()
        co = county_name(li)
        if st == "NC":
            from .quiet_title.adapters.nc_onemap import canonical_county
            co = canonical_county(co) or co
        else:
            co = co.title()
        plan.setdefault((st, co), {}).setdefault(str(li.parcel_id).strip(), []).append(li)
    return plan


LIKE_BATCH = 12
#: a LIKE pattern needs at least this many characters to be selective
LIKE_MIN_KEY = 8


def nc_like_where(county: str, pins: list[str]) -> str:
    from .quiet_title.adapters.nc_onemap import like_pattern
    terms = []
    for p in pins:
        pat = like_pattern(p).replace("'", "")
        terms.append(f"parno LIKE '{pat}' OR altparno LIKE '{pat}'")
    return f"cntyname='{county}' AND ({' OR '.join(terms)})"


def fetch_nc_like(county: str, pins: list[str]) -> Optional[dict[str, dict]]:
    """Second pass for pins the exact id forms missed: the layer writes the same characters with other
    separators ('166220-70-9679' for '166220709679'). A LIKE pattern with every separator wild narrows the
    layer; a record is accepted ONLY when its parno/altparno equals the PIN letter for letter (alias keys),
    so a loose pattern can never bind another parcel."""
    feats = query(NC_URL, {"where": nc_like_where(county, pins), "outFields": NC_FIELDS,
                           "returnGeometry": "false", "f": "json"})
    if feats is None:
        return None
    index: dict[str, dict] = {}
    for a in feats:
        parsed = {**parse_nc_attrs(a), "parno": a.get("parno") or a.get("altparno")}
        for f in ("parno", "altparno"):
            k = pin_key(a.get(f))
            if k and (k not in index or (parsed["deed"] and not index[k].get("deed"))):
                index[k] = parsed
    return {p: m for p in pins for m in [_lookup(p, index)] if m is not None}


def _fetch_chunk(st: str, co: str, pins: list[str]) -> Optional[dict[str, dict]]:
    if st == "NC":
        return fetch_nc(co, pins)
    return fetch_sc(sc_spec(co), pins)


async def enrich_gis_fill(listings: list, budget_s: Optional[float] = None) -> dict:
    """Screen every NC/SC row with a parcel id against its county's parcel layer and fill what is blank.
    Pass 1: exact id forms, BATCH parcels per request, counties round-robin. Pass 2 (NC): the pins pass 1
    missed, LIKE_BATCH per request, with the remaining budget. A pin the layer does not hold is stamped
    (found: false) only after every pass that applies has run, so a budget that ends early never turns an
    unasked row into a 'not in layer' verdict."""
    stats: dict = {"candidates": 0, "screened": 0, "not_in_layer": 0, "deed": 0, "legal": 0, "value": 0,
                   "acres": 0, "none_deed": 0, "none_legal": 0, "requests": 0, "budget_hit": False,
                   "parcel_from_account": 0, "found_by_like": 0, "closed_layers": {}}
    if not enabled():
        return {**stats, "skipped": f"{_ENV_FLAG}=0"}
    if budget_s is None:
        try:
            budget_s = float(os.environ.get(_ENV_BUDGET, "2400"))
        except ValueError:
            budget_s = 2400.0
    t0 = clock()
    now = datetime.now(timezone.utc)
    now_iso = now.isoformat(timespec="seconds")
    await enrich_account_parcels(listings, stats, t0, budget_s)
    plan = _plan(listings, now)
    stats["candidates"] = sum(len(ls) for m in plan.values() for ls in m.values())

    def settle(key: tuple[str, str], pin: str, m: Optional[dict]) -> None:
        st, co = key
        want = asks(sc_spec(co) if st == "SC" else None)
        source = "nc_onemap" if st == "NC" else f"{co.lower()}_parcel_layer"
        for li in plan[key][pin]:
            c = apply_one(li, m, source, co, now_iso, want)
            stats["screened"] += 1
            if m is None:
                stats["not_in_layer"] += 1
            else:
                if want["deed"] and not m.get("deed"):
                    stats["none_deed"] += 1
                if want["legal"] and not m.get("legal"):
                    stats["none_legal"] += 1
            for k2 in ("deed", "legal", "value", "acres"):
                stats[k2] += c[k2]

    def out_of_time() -> bool:
        if clock() - t0 > budget_s:
            stats["budget_hit"] = True
            return True
        return False

    queues = {k: list(m) for k, m in sorted(plan.items())}
    missed: dict[tuple[str, str], list[str]] = {}
    while queues and not out_of_time():
        for key in list(queues):
            if out_of_time():
                queues = {}
                break
            st, co = key
            pins = queues[key][:BATCH]
            del queues[key][:BATCH]
            if not queues[key]:
                del queues[key]
            url = NC_URL if st == "NC" else (sc_spec(co) or {}).get("url", "")
            if url in _closed:
                continue
            got = await asyncio.to_thread(_fetch_chunk, st, co, pins)
            stats["requests"] += 1
            if got is None:
                continue          # the layer did not answer: these rows stay unscreened (not a verdict)
            for pin in pins:
                m = got.get(pin)
                if m is None and st == "NC" and len(pin_key(pin)) >= LIKE_MIN_KEY:
                    missed.setdefault(key, []).append(pin)
                    continue
                settle(key, pin, m)
    like_q = {k: list(v) for k, v in sorted(missed.items())}
    while like_q and not out_of_time():
        for key in list(like_q):
            if out_of_time():
                like_q = {}
                break
            st, co = key
            pins = like_q[key][:LIKE_BATCH]
            del like_q[key][:LIKE_BATCH]
            if not like_q[key]:
                del like_q[key]
            if NC_URL in _closed:
                like_q = {}
                break
            got = await asyncio.to_thread(fetch_nc_like, co, pins)
            stats["requests"] += 1
            if got is None:
                continue
            for pin in pins:
                m = got.get(pin)
                if m is not None:
                    stats["found_by_like"] += 1
                settle(key, pin, m)
    stats["closed_layers"] = {u.split("/rest/")[0][-40:]: w for u, w in closed_layers().items()}
    log.info("gis_fill.done", **{k: v for k, v in stats.items() if k != "closed_layers"})
    return stats
