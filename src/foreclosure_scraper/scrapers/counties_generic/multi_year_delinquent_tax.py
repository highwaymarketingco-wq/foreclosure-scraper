"""Multi-year property-tax delinquency — arrears HISTORY per parcel, not a snapshot.

Every other tax source in this repo answers "who is delinquent right now". This
one answers "who has been delinquent, and for how long, and is it getting
worse". Three counties publish their unpaid-bill roll as a SEPARATE hosted
ArcGIS service PER YEAR, going back a decade. Reading all of them and joining on
parcel turns a flat list into a time series: a parcel that shows up in 2021,
2022, 2023, 2024 and 2025 is a fundamentally different lead from one that missed
a single bill.

Covered (all free, public, no-login, no CAPTCHA/WAF — plain ArcGIS REST JSON):

  Buncombe NC   org VLA0ImJ33zhtGEaP (services6)
                "Unpaid Property Bills from <YYYY>" and friends — 18 services,
                14 with rows, levy years 2013..2026.
  Oconee SC     org UOvRn2Rvzysthh3i (services1)
                DT2023 / DT2024 / DT2025 + DelqTaxSale_2015.
  Pickens SC    org 59960rq18IxUcAVI (services1)
                delinquent_2020 / del_2021 / dqnt_2022 / dqnt_2023 / dqnt_2024
                + the October-2025 newspaper-ad and posting layers.

WHICH YEAR IS A LAYER? The two states lie in OPPOSITE directions, so the year
is resolved differently per county and neither one trusts the item title:

  * Buncombe — the SERVICE title is wrong and the TABLE name is wrong too. The
    service titled "Unpaid Property Bills from 2021" holds the table
    ``Buncombe_County_All_Property_Bills_Unpaid_from_2022`` (4,175 rows, every
    row ``levy_year='2022'``), while the real 2021 roll lives in the
    underscored twin ``Unpaid_Property_Bills_from_2021``. There is no 2022-
    titled service at all. So Buncombe's year comes from the DATA: one cheap
    ``returnDistinctValues`` probe on ``levy_year`` per service. Titles are
    only used to find candidates.
  * Oconee / Pickens — here the LAYER NAME is right and the DATA column lies.
    ``dqnt_2022`` carries ``TAXYEAR=2023`` and ``dqnt_2023`` carries
    ``TAXYEAR=2024`` (TAXYEAR is a CAMA-snapshot field that rides along on the
    parcel join, not the delinquency year). So these counties take the year
    from the service name.

Because both counties are enumerated from the org root every run rather than
hard-coded, a new annual service (Buncombe 2027, Oconee DT2026, Pickens
dqnt_2025) is picked up automatically the week it is published.

REAL PROPERTY ONLY. Buncombe's unpaid roll is dominated by PERSONAL property
bills (vehicles, business personal) — 6,846 of 7,922 rows in the 2025 service.
Those rows have ``pin=''`` and ``real_value='0'``, and their ``address_line1``
is the taxpayer's mailing address, not a parcel. They are not leads. Every
Buncombe query is filtered ``pin<>''``.

CURRENT LEVY vs MATURED ARREARS. Buncombe's newest service is the CURRENT bill
run — 103,285 real-property bills sit in levy year 2026 simply because the
cycle has not closed yet. Treating that as distress would flood the board with
the entire county. The scraper detects it structurally rather than by calendar:
for each county, if the newest year's row count is >= ``_CURRENT_LEVY_RATIO``x
the next-newest year's, that year is flagged ``current_levy`` and excluded from
``matured_years``. A parcel must clear BOTH gates to be emitted — at least
``_MIN_YEARS`` distinct years total AND at least one MATURED year — so
"unpaid 2026 only" is dropped while "unpaid 2026 + 2025" survives.

EXCLUDED, deliberately:
  * Oconee ``Delinquent_Tax_Properties`` — a 2-row template layer whose owner
    is literally "John Doe" at "201 Street Name Rd Your Town, State Zip".
  * Pickens ``DelqParcels_Ad_paperlisting2`` — a shapefile-join duplicate of
    ``DelParces_October2025NewsAd`` with truncated field names
    (DelqParcel/DelqParc_1/...); same parcels, no extra information.
  * Pickens ``FLC_2022`` — post-sale forfeited-land inventory, not arrears.

PRIVACY: no ``outFields=*`` anywhere. Every query sends an explicit field
allowlist built from ``_Fields`` below, so a county that later adds an
SSN/DOB-style column to one of these layers can never leak into the board.
None of the layers in scope expose such a column today (verified against the
layer metadata of all 30 candidate layers).

Emits one Listing per PARCEL (not per bill) carrying the full history in
``raw['multi_year_delinquent_tax']``: ``per_year`` amounts, ``years``,
``years_delinquent``, ``matured_years_delinquent``, ``consecutive_years``,
``first_year``, ``latest_year``, ``total_owed``, ``trend`` and
``still_accruing``.

Dateless — an arrears history has no sale date, so
``counties.multi_year_delinquent_tax`` must be added to
``main.DATELESS_OK_SOURCES`` or every row is filtered out.
"""
from __future__ import annotations

import asyncio
import os
import re
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Iterable

import httpx
import structlog

from ...base_scraper import BaseScraper
from ...http_client import client
from ...models import Listing, ListingType, PropertyKind

log = structlog.get_logger()

SLUG = "counties.multi_year_delinquent_tax"

BUNCOMBE_ORG = "https://services6.arcgis.com/VLA0ImJ33zhtGEaP/arcgis/rest/services"
OCONEE_ORG = "https://services1.arcgis.com/UOvRn2Rvzysthh3i/arcgis/rest/services"
PICKENS_ORG = "https://services1.arcgis.com/59960rq18IxUcAVI/arcgis/rest/services"

# Human-reachable pages for source_url (the FeatureServer itself is a JSON API).
BUNCOMBE_PAGE = "https://www.buncombecounty.org/governing/depts/tax/"
OCONEE_PAGE = "https://oconeesc.com/delinquent-tax"
PICKENS_PAGE = "https://www.co.pickens.sc.us/departments/delinquent-tax"

# ArcGIS hard cap on these servers is maxRecordCount=2000; we page with
# resultOffset and stop on exceededTransferLimit=false.
_PAGE_SIZE = 2000
#: Runaway guard per layer. Buncombe's current levy is ~103k rows, so this has
#: to clear that comfortably while still bounding a pathological loop.
_MAX_ROWS_PER_LAYER = 400_000

#: A parcel needs this many distinct delinquent years to be emitted. The whole
#: point of this source is the repeat signal; single-year delinquency is
#: already covered by buncombe_delinquent_tax / oconee_tax_sale / pickens_*.
_MIN_YEARS = int(os.environ.get("FORECLOSURE_MYD_MIN_YEARS", "2"))
#: Newest year counts as an un-matured "current levy" when it is at least this
#: many times bigger than the next-newest year (Buncombe 2026 is ~96x 2025).
_CURRENT_LEVY_RATIO = 10.0

_YEAR_MIN, _YEAR_MAX = 2000, 2100


# ---------------------------------------------------------------------------
# field maps
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class _Fields:
    """Explicit per-layer field allowlist (never ``outFields=*``, see module doc)."""

    parcel: tuple[str, ...] = ()
    owner: tuple[str, ...] = ()
    situs: tuple[str, ...] = ()
    situs_city: tuple[str, ...] = ()
    situs_zip: tuple[str, ...] = ()
    mail: tuple[str, ...] = ()
    mail_state: str | None = None
    amount: tuple[str, ...] = ()
    acres: tuple[str, ...] = ()
    value: tuple[str, ...] = ()
    legal: tuple[str, ...] = ()
    mortgage_co: str | None = None
    lat: str | None = None
    lng: str | None = None
    #: Fields fetched for provenance only (deed refs, item numbers, ...).
    extra: tuple[str, ...] = ()

    def names(self) -> list[str]:
        names: list[str] = []
        for group in (self.parcel, self.owner, self.situs, self.situs_city,
                      self.situs_zip, self.mail, self.amount, self.acres,
                      self.value, self.legal, self.extra):
            names.extend(group)
        for single in (self.mail_state, self.mortgage_co, self.lat, self.lng):
            if single:
                names.append(single)
        seen: set[str] = set()
        out: list[str] = []
        for n in names:
            if n not in seen:
                seen.add(n)
                out.append(n)
        return out

    def out_fields(self, available: frozenset[str] | None = None) -> str:
        """Explicit allowlist, intersected with what the layer actually has.

        The same county spells the same column differently across years
        (DT2023 ``Owners_Nam`` vs DT2025 ``Owner_Name``; dqnt_2024 ``Max_AMT_DU``
        vs dqnt_2023 ``AMOUNT_DUE``; the 2025 news-ad layer has no
        ``MAP_PARCEL``). ArcGIS rejects the WHOLE query with HTTP 400 "Invalid
        query parameters" if a single requested field is unknown, so a union
        spec has to be filtered against the live schema. Filtering here (rather
        than falling back to ``outFields=*``) keeps the privacy guarantee: only
        named columns are ever requested."""
        names = self.names()
        if available is not None:
            names = [n for n in names if n in available]
        return ",".join(names)


# Buncombe unpaid-bill TABLE (no geometry). situs is assembled from the
# house_num/street_* columns; address_line1/city/state/postal_code is the
# TAXPAYER MAILING address and is kept separate so absentee can be derived.
_BUNCOMBE_FIELDS = _Fields(
    parcel=("pin",),
    owner=("owner1_last_name", "owner1_first_name", "owner1_third_name",
           "owner1_suffix_name", "owner2_last_name", "owner2_first_name",
           "owner2_third_name", "owner2_suffix_name"),
    situs=("house_num", "street_direction", "street_name", "street_type"),
    mail=("address_line1", "address_line2", "city", "state", "postal_code"),
    mail_state="state",
    amount=("total_due", "tax_due", "interest_due", "fees_due", "late_due",
            "cost_due", "ad_cost_due", "original_bill_amount"),
    acres=("acres",),
    value=("real_value", "total_value"),
    legal=("subdivision", "sub_lot"),
    mortgage_co="mortgage_co",
    extra=("levy_year", "bill", "deed_book", "deed_page", "deed_date",
           "deed_instrument"),
)

# Oconee DT<YYYY> polygon layers. X/Y are plain attribute columns holding the
# parcel centroid in WGS84, so no geometry request is needed.
_OCONEE_DT_FIELDS = _Fields(
    parcel=("TMS_NUMBER", "Map_Number"),
    owner=("Owner_Name",),
    amount=("Total_Tax_",),
    acres=("GIS_ACRES", "TMS_ACRES"),
    legal=("Descriptio", "SUBDIVSION"),
    lat="Y", lng="X",
    extra=("Item_Numbe", "DEEDREF"),
)
# DT2023/DT2024 spell the owner column "Owners_Nam" (DT2025 uses "Owner_Name").
_OCONEE_DT_FIELDS_LEGACY = _Fields(
    parcel=("TMS_NUMBER", "Map_Number"),
    owner=("Owners_Nam",),
    amount=("Total_Tax_",),
    acres=("GIS_ACRES", "TMS_ACRES"),
    legal=("Descriptio", "SUBDIVSION"),
    lat="Y", lng="X",
    extra=("Item_Numbe", "DEEDREF"),
)
_OCONEE_2015_FIELDS = _Fields(
    parcel=("TMS_NUMBER",),
    owner=("Owner",),
    amount=("TaxDue",),
    legal=("Description",),
)

# Pickens dqnt_<YYYY>: full CAMA join — owner, mailing AND situs.
_PICKENS_FULL_FIELDS = _Fields(
    parcel=("PIN", "MAP_PARCEL", "PARCEL_NUM"),
    owner=("OWNER__NOW", "NAME1", "NAME2"),
    situs=("LOCADD",), situs_city=("LOCCITY",), situs_zip=("LOCZIP",),
    mail=("ADD1", "CITY", "STATE", "ZIP"), mail_state="STATE",
    amount=("AMOUNT_DUE", "Max_AMT_DU", "AMT"),
    acres=("ACRES", "CalcAcres", "CALCACRE"),
    value=("ACTUALVAL",),
    legal=("SubDivisio", "IMPVAC"),
    extra=("ACCTNO", "STATUS"),
)
# Pickens del_2021 / delinquent_2020: parcel + situs only, no owner column.
_PICKENS_THIN_FIELDS = _Fields(
    parcel=("PIN", "MAP_NUMBER"),
    situs=("LOCADD",), situs_city=("LOCCITY",), situs_zip=("LOCZIP",),
    acres=("ACRES", "ACREAGE"),
    extra=("ACCTNO",),
)
# Pickens Oct-2025 newspaper-ad / posting layers: parcel + owner + amount.
_PICKENS_AD_FIELDS = _Fields(
    parcel=("PIN", "MAP_PARCEL"),
    owner=("OWNER__NOW",),
    amount=("AMOUNT_DUE",),
    acres=("CALCACRE",),
)


@dataclass
class _Layer:
    """One (county, year) delinquency roll."""

    state: str
    county: str
    year: int
    url: str                 # .../FeatureServer/<layer id>
    fields: _Fields
    page_url: str
    where: str = "1=1"
    label: str = ""
    centroid: bool = False   # ask ArcGIS for the polygon centroid (no X/Y cols)
    #: Column names the layer actually exposes; the outFields allowlist is
    #: intersected with this so a union field-spec never 400s the query.
    available: frozenset[str] = frozenset()


# ---------------------------------------------------------------------------
# small helpers
# ---------------------------------------------------------------------------
def _clean(val: Any) -> str | None:
    """Trim an ArcGIS string cell. These layers pad heavily with single spaces
    and use '0'/'' interchangeably for 'absent'."""
    if val is None:
        return None
    s = re.sub(r"\s+", " ", str(val)).strip()
    return s or None


def _money(val: Any) -> float | None:
    """Coerce an amount cell. Oconee DT2023 stores ' $1,979.70' as text while
    DT2024/DT2025 store a float, so both shapes have to work."""
    if val is None:
        return None
    if isinstance(val, bool):
        return None
    if isinstance(val, (int, float)):
        return float(val) if val > 0 else None
    s = re.sub(r"[^\d.\-]", "", str(val))
    if not s or s in (".", "-", "-."):
        return None
    try:
        f = float(s)
    except ValueError:
        return None
    return f if f > 0 else None


def _first_money(attrs: dict, names: tuple[str, ...]) -> float | None:
    for n in names:
        m = _money(attrs.get(n))
        if m is not None:
            return m
    return None


def _first_float(attrs: dict, names: tuple[str, ...]) -> float | None:
    for n in names:
        v = attrs.get(n)
        try:
            f = float(v)
        except (TypeError, ValueError):
            continue
        if f > 0:
            return f
    return None


def _first_str(attrs: dict, names: tuple[str, ...]) -> str | None:
    for n in names:
        s = _clean(attrs.get(n))
        # ArcGIS zip columns come back as int 0 for "absent".
        if s and s not in ("0",):
            return s
    return None


def _join(attrs: dict, names: tuple[str, ...], sep: str = " ") -> str | None:
    parts = [_clean(attrs.get(n)) for n in names]
    parts = [p for p in parts if p and p != "0"]
    return sep.join(parts) if parts else None


def _norm_parcel(pid: str | None) -> str:
    return re.sub(r"[^0-9A-Za-z]", "", pid or "").upper()


def _zip5(val: Any) -> str | None:
    s = re.sub(r"\D", "", str(val or ""))
    if not s:
        return None
    # Pickens stores 296400000 (zip + zip4 concatenated) as an int.
    return s[:5] if s[:5] != "00000" else None


def _norm_addr(s: str | None) -> str:
    return re.sub(r"[^a-z0-9]", "", (s or "").lower())


def _buncombe_owner(attrs: dict) -> str | None:
    """Buncombe splits owners into last/first/third/suffix columns. Rebuild the
    regional GIS record-owner form ("LAST FIRST MIDDLE SUFFIX") and join a
    second owner with ' & ' so name-matching downstream sees what the assessor
    sees."""
    names = []
    for pfx in ("owner1", "owner2"):
        who = _join(attrs, (f"{pfx}_last_name", f"{pfx}_first_name",
                            f"{pfx}_third_name", f"{pfx}_suffix_name"))
        if who:
            names.append(who)
    return " & ".join(names) if names else None


def _buncombe_situs(attrs: dict) -> str | None:
    """Situs from house_num/street_*, NOT address_line1 (that is the taxpayer's
    mailing address and is frequently out of county)."""
    num = _clean(attrs.get("house_num"))
    street = _join(attrs, ("street_direction", "street_name", "street_type"))
    if not street:
        return None
    if num and num != "0":
        return f"{num} {street}"
    return street


def _dedupe_year_label(county: str, year: int) -> str:
    return f"{county}:{year}"


# ---------------------------------------------------------------------------
# ArcGIS plumbing
# ---------------------------------------------------------------------------
async def _get_json(c: httpx.AsyncClient, url: str, params: dict) -> dict:
    r = await c.get(url, params=params)
    r.raise_for_status()
    data = r.json()
    if isinstance(data, dict) and data.get("error"):
        # ArcGIS answers 200 with an {"error": ...} body — never let that read
        # as a legitimate empty result (see project_column_source_silent_death).
        raise ValueError(f"arcgis error: {str(data['error'])[:200]}")
    return data


async def _list_services(c: httpx.AsyncClient, org: str) -> list[dict]:
    try:
        data = await _get_json(c, org, {"f": "json"})
    except (httpx.HTTPError, ValueError):
        log.warning("myd.org_enumerate_failed", org=org, exc_info=True)
        return []
    return [s for s in (data.get("services") or [])
            if s.get("type") == "FeatureServer" and s.get("url")]


async def _resolve_layer(c: httpx.AsyncClient,
                         service_url: str) -> tuple[str, frozenset[str]] | None:
    """(layer url, its column names) for the service's single child layer.

    Each of these services exposes exactly one child — sometimes a Feature
    Layer (Oconee/Pickens polygons), sometimes a Table (Buncombe bills). The
    column set comes back from the same metadata call, which is what lets the
    outFields allowlist be intersected against the real schema."""
    try:
        meta = await _get_json(c, service_url, {"f": "json"})
    except (httpx.HTTPError, ValueError):
        return None
    lid = None
    for kind in ("layers", "tables"):
        for entry in meta.get(kind) or []:
            lid = int(entry["id"])
            break
        if lid is not None:
            break
    if lid is None:
        return None
    layer_url = f"{service_url}/{lid}"
    try:
        lmeta = await _get_json(c, layer_url, {"f": "json"})
    except (httpx.HTTPError, ValueError):
        return None
    cols = frozenset(f["name"] for f in (lmeta.get("fields") or []) if f.get("name"))
    return layer_url, cols


async def _count(c: httpx.AsyncClient, layer_url: str, where: str) -> int:
    data = await _get_json(c, layer_url + "/query",
                           {"where": where, "returnCountOnly": "true", "f": "json"})
    return int(data.get("count") or 0)


async def _distinct(c: httpx.AsyncClient, layer_url: str, fld: str, where: str) -> list[str]:
    data = await _get_json(c, layer_url + "/query", {
        "where": where, "outFields": fld, "returnDistinctValues": "true",
        "returnGeometry": "false", "f": "json",
    })
    vals = {_clean((f.get("attributes") or {}).get(fld))
            for f in (data.get("features") or [])}
    return sorted(v for v in vals if v)


async def _fetch_layer(c: httpx.AsyncClient, layer: _Layer) -> list[dict]:
    """Page a layer with resultOffset/resultRecordCount, stopping only when the
    server both returns a short page AND clears exceededTransferLimit."""
    rows: list[dict] = []
    offset = 0
    out_fields = layer.fields.out_fields(layer.available or None)
    if not out_fields:
        log.warning("myd.layer_no_known_fields", layer=layer.label)
        return []
    params_base = {
        "where": layer.where,
        "outFields": out_fields,
        "returnGeometry": "false",
        "f": "json",
    }
    if layer.centroid:
        params_base["returnCentroid"] = "true"
        params_base["outSR"] = "4326"
    while True:
        params = dict(params_base,
                      resultOffset=str(offset), resultRecordCount=str(_PAGE_SIZE))
        data = await _get_json(c, layer.url + "/query", params)
        feats = data.get("features") or []
        for f in feats:
            attrs = dict(f.get("attributes") or {})
            cen = f.get("centroid") or {}
            if cen:
                attrs["__lat"] = cen.get("y")
                attrs["__lng"] = cen.get("x")
            rows.append(attrs)
        if not feats:
            break
        offset += len(feats)
        if len(feats) < _PAGE_SIZE and not data.get("exceededTransferLimit"):
            break
        if offset >= _MAX_ROWS_PER_LAYER:
            log.warning("myd.layer_row_cap", layer=layer.label, rows=offset)
            break
    return rows


# ---------------------------------------------------------------------------
# per-county layer discovery
# ---------------------------------------------------------------------------
_BUNCOMBE_NAME_RE = re.compile(r"unpaid", re.I)


async def _discover_buncombe(c: httpx.AsyncClient) -> list[_Layer]:
    """Enumerate the org, then resolve each service's year from its DATA.

    Neither the service title nor the table name can be trusted here (see the
    module docstring): the service titled ".. from 2021" holds levy_year 2022.
    One returnDistinctValues probe on ``levy_year`` per service settles it, and
    it also skips the four services that are entirely empty (2009-2012).
    """
    where = "pin<>''"
    services = [s for s in await _list_services(c, BUNCOMBE_ORG)
                if _BUNCOMBE_NAME_RE.search(s.get("name") or "")]
    out: list[_Layer] = []

    async def one(svc: dict) -> None:
        resolved = await _resolve_layer(c, svc["url"])
        if resolved is None:
            return
        layer_url, cols = resolved
        if "levy_year" not in cols or "pin" not in cols:
            return  # not an unpaid-bill roll despite the title
        try:
            years = await _distinct(c, layer_url, "levy_year", where)
        except (httpx.HTTPError, ValueError):
            log.warning("myd.buncombe_year_probe_failed", service=svc.get("name"),
                        exc_info=True)
            return
        for y in years:
            if not (y.isdigit() and _YEAR_MIN <= int(y) <= _YEAR_MAX):
                continue
            out.append(_Layer(
                state="NC", county="Buncombe", year=int(y), url=layer_url,
                fields=_BUNCOMBE_FIELDS, page_url=BUNCOMBE_PAGE,
                # Pin each layer to its own levy year: the underscored/spaced
                # 2021 twins are two DIFFERENT rolls, and one service could in
                # principle carry more than one year.
                where=f"{where} AND levy_year='{y}'",
                label=f"buncombe:{y}:{svc.get('name')}",
                available=cols,
            ))

    await asyncio.gather(*(one(s) for s in services))
    return out


_OCONEE_DT_RE = re.compile(r"^DT(\d{4})$", re.I)
_OCONEE_SALE_RE = re.compile(r"^DelqTaxSale_(\d{4})$", re.I)
#: 2-row demo layer ("John Doe" / "Your Town, State Zip") — never a lead.
_OCONEE_SKIP = {"delinquent_tax_properties"}


async def _discover_oconee(c: httpx.AsyncClient) -> list[_Layer]:
    """Oconee names its layers honestly (DT2025 == the 2025 roll); the TAXYEAR
    column is the untrustworthy one, so the year comes from the name."""
    out: list[_Layer] = []
    for svc in await _list_services(c, OCONEE_ORG):
        name = svc.get("name") or ""
        if name.lower() in _OCONEE_SKIP:
            continue
        m = _OCONEE_DT_RE.match(name) or _OCONEE_SALE_RE.match(name)
        if not m:
            continue
        year = int(m.group(1))
        if not _YEAR_MIN <= year <= _YEAR_MAX:
            continue
        resolved = await _resolve_layer(c, svc["url"])
        if resolved is None:
            continue
        layer_url, cols = resolved
        if _OCONEE_SALE_RE.match(name):
            flds = _OCONEE_2015_FIELDS
        else:
            # DT2025 renamed Owners_Nam -> Owner_Name. Key off the live schema
            # rather than the year, so either spelling keeps resolving.
            flds = (_OCONEE_DT_FIELDS_LEGACY
                    if "Owner_Name" not in cols and "Owners_Nam" in cols
                    else _OCONEE_DT_FIELDS)
        out.append(_Layer(
            state="SC", county="Oconee", year=year, url=layer_url,
            fields=flds, page_url=OCONEE_PAGE, label=f"oconee:{year}:{name}",
            available=cols,
        ))
    return out


_PICKENS_YEAR_RE = re.compile(r"^(?:dqnt|del|delinquent)_(\d{4})$", re.I)
#: Layers whose year is only in the human title. Value = (year, fields).
_PICKENS_NAMED: dict[str, tuple[int, _Fields]] = {
    "delparces_october2025newsad": (2025, _PICKENS_AD_FIELDS),
    "posting3": (2025, _PICKENS_AD_FIELDS),
}
#: Shapefile-join duplicate of DelParces_October2025NewsAd (truncated column
#: names, identical parcels) and the post-sale FLC inventory (not arrears).
_PICKENS_SKIP = {"delqparcels_ad_paperlisting2", "flc_2022"}


async def _discover_pickens(c: httpx.AsyncClient) -> list[_Layer]:
    out: list[_Layer] = []
    for svc in await _list_services(c, PICKENS_ORG):
        name = svc.get("name") or ""
        key = name.lower()
        if key in _PICKENS_SKIP:
            continue
        m = _PICKENS_YEAR_RE.match(name)
        if m:
            year = int(m.group(1))
            flds = _PICKENS_THIN_FIELDS if key.startswith(("del_", "delinquent_")) \
                else _PICKENS_FULL_FIELDS
        elif key in _PICKENS_NAMED:
            year, flds = _PICKENS_NAMED[key]
        else:
            continue
        if not _YEAR_MIN <= year <= _YEAR_MAX:
            continue
        resolved = await _resolve_layer(c, svc["url"])
        if resolved is None:
            continue
        layer_url, cols = resolved
        out.append(_Layer(
            state="SC", county="Pickens", year=year, url=layer_url,
            fields=flds, page_url=PICKENS_PAGE, centroid=True,
            label=f"pickens:{year}:{name}", available=cols,
        ))
    return out


async def discover_layers(c: httpx.AsyncClient) -> list[_Layer]:
    groups = await asyncio.gather(
        _discover_buncombe(c), _discover_oconee(c), _discover_pickens(c),
        return_exceptions=True,
    )
    out: list[_Layer] = []
    for g in groups:
        if isinstance(g, BaseException):
            log.warning("myd.discovery_failed", error=repr(g)[:200])
            continue
        out.extend(g)
    # A layer with no parcel column can't be keyed into a history — drop it
    # loudly rather than emitting parcel-less rows.
    keep: list[_Layer] = []
    for ly in out:
        if ly.available and not (set(ly.fields.parcel) & ly.available):
            log.warning("myd.layer_no_parcel_column", layer=ly.label,
                        wanted=list(ly.fields.parcel))
            continue
        keep.append(ly)
    keep.sort(key=lambda ly: (ly.county, ly.year, ly.label))
    return keep


# ---------------------------------------------------------------------------
# row -> per-year observation
# ---------------------------------------------------------------------------
@dataclass
class _Obs:
    """One parcel-year sighting."""

    year: int
    amount: float | None = None
    owner: str | None = None
    situs: str | None = None
    city: str | None = None
    zip_code: str | None = None
    mailing: str | None = None
    mail_state: str | None = None
    acres: float | None = None
    value: float | None = None
    legal: str | None = None
    lat: float | None = None
    lng: float | None = None
    mortgage_co: str | None = None
    layer: str = ""
    extra: dict[str, Any] = field(default_factory=dict)


def row_to_obs(attrs: dict, layer: _Layer) -> tuple[str, _Obs] | None:
    """(normalized parcel key, observation) or None when the row has no parcel."""
    parcel = _first_str(attrs, layer.fields.parcel)
    key = _norm_parcel(parcel)
    if not key:
        return None

    f = layer.fields
    if layer.county == "Buncombe":
        owner = _buncombe_owner(attrs)
        situs = _buncombe_situs(attrs)
        mailing = _join(attrs, ("address_line1", "address_line2", "city",
                                "state", "postal_code"), sep=" ")
    else:
        owner = _first_str(attrs, f.owner)
        situs = _first_str(attrs, f.situs)
        mailing = _join(attrs, f.mail, sep=" ")

    lat = lng = None
    if f.lat and f.lng:
        try:
            lat, lng = float(attrs[f.lat]), float(attrs[f.lng])
        except (KeyError, TypeError, ValueError):
            lat = lng = None
    if lat is None and attrs.get("__lat") is not None:
        try:
            lat, lng = float(attrs["__lat"]), float(attrs["__lng"])
        except (TypeError, ValueError):
            lat = lng = None
    # Guard against a 0/0 or out-of-range centroid from an empty geometry.
    if lat is not None and not (-90 < lat < 90 and -180 < (lng or 0) < 180
                                and (abs(lat) > 0.001 or abs(lng or 0) > 0.001)):
        lat = lng = None

    mail_state = None
    if f.mail_state:
        mail_state = (_clean(attrs.get(f.mail_state)) or "").upper()[:2] or None

    extra = {k: _clean(attrs.get(k)) for k in f.extra if _clean(attrs.get(k))}
    # Buncombe splits the balance across components; keep them for the operator.
    if layer.county == "Buncombe":
        for comp in ("tax_due", "interest_due", "fees_due", "late_due",
                     "cost_due", "ad_cost_due"):
            v = _money(attrs.get(comp))
            if v:
                extra[comp] = v

    return key, _Obs(
        year=layer.year,
        amount=_first_money(attrs, f.amount),
        owner=owner,
        situs=situs,
        city=_first_str(attrs, f.situs_city),
        zip_code=_zip5(_first_str(attrs, f.situs_zip)),
        mailing=mailing,
        mail_state=mail_state,
        acres=_first_float(attrs, f.acres),
        value=_first_float(attrs, f.value),
        legal=_first_str(attrs, f.legal),
        lat=lat, lng=lng,
        mortgage_co=_clean(attrs.get(f.mortgage_co)) if f.mortgage_co else None,
        layer=layer.label,
        extra=extra,
    )


# ---------------------------------------------------------------------------
# history assembly
# ---------------------------------------------------------------------------
def current_levy_year(years: dict[int, int]) -> int | None:
    """Return the newest year that is an UN-MATURED current bill run, if any.

    ``years`` maps year -> parcel count for one county. Buncombe's newest roll
    holds 103,285 real-property parcels against 1,076 the year before — that is
    the whole county's current levy, not distress. Detected by ratio so the rule
    keeps working as the calendar rolls and so Oconee/Pickens (whose newest
    roll is already a past-due list, ~1.3x the prior year) are left alone.
    """
    if len(years) < 2:
        return None
    ordered = sorted(years, reverse=True)
    newest, prev = ordered[0], ordered[1]
    if years[prev] > 0 and years[newest] >= _CURRENT_LEVY_RATIO * years[prev]:
        return newest
    return None


def _longest_run(years: list[int]) -> int:
    """Longest streak of consecutive years present."""
    if not years:
        return 0
    best = run = 1
    for a, b in zip(years, years[1:]):
        run = run + 1 if b == a + 1 else 1
        best = max(best, run)
    return best


def _trend(per_year: dict[int, float | None], matured: list[int]) -> str:
    """Direction of the per-year owed amount across MATURED years.

    Each year is its own bill, so a rising series means the owner is falling
    further behind every cycle; a falling one means they are partly catching up
    (or the parcel has been split / partially redeemed)."""
    amts = [(y, per_year[y]) for y in matured if per_year.get(y) is not None]
    if len(amts) < 2:
        return "flat"
    first, last = amts[0][1], amts[-1][1]
    if first is None or last is None or first <= 0:
        return "flat"
    if last >= first * 1.05:
        return "growing"
    if last <= first * 0.95:
        return "shrinking"
    return "flat"


def build_listing(state: str, county: str, parcel_key: str, obs: list[_Obs],
                  page_url: str, levy_year: int | None,
                  county_latest_year: int | None = None) -> Listing | None:
    """Fold every parcel-year sighting into one Listing carrying the history."""
    if not obs:
        return None
    obs = sorted(obs, key=lambda o: o.year)  # noqa: PLR6104 - stable by year
    years = sorted({o.year for o in obs})
    matured = [y for y in years if y != levy_year]

    if len(years) < _MIN_YEARS or not matured:
        return None

    per_year: dict[int, float | None] = {}
    for o in obs:
        amt = o.amount
        if amt is None:
            per_year.setdefault(o.year, None)
        else:
            # A parcel can carry more than one bill in a year (Pickens ad +
            # posting layers, Buncombe supplemental bills); keep the largest
            # rather than summing, since the layers overlap.
            prev = per_year.get(o.year)
            per_year[o.year] = amt if prev is None else max(prev, amt)

    total_owed = sum(v for v in per_year.values() if v) or None
    matured_total = sum(per_year[y] for y in matured if per_year.get(y)) or None

    # Newest non-empty value wins for every descriptive field.
    def newest(attr: str) -> Any:
        for o in reversed(obs):
            v = getattr(o, attr)
            if v not in (None, "", 0):
                return v
        return None

    owner = newest("owner")
    situs = newest("situs")
    mailing = newest("mailing")
    lat, lng = newest("lat"), newest("lng")
    # "Still accruing" has to be measured against the NEWEST ROLL THE COUNTY
    # PUBLISHES, not against this parcel's own newest year — max(this parcel's
    # years) is trivially its own latest year, which would make the flag
    # unconditionally True. When the caller doesn't supply the county-wide
    # newest year, fall back to the parcel's own (flag degrades to True) rather
    # than crashing.
    county_newest = county_latest_year or levy_year or years[-1]

    raw_block = {
        "years": years,
        "per_year": {str(y): per_year.get(y) for y in years},
        "years_delinquent": len(years),
        "matured_years": matured,
        "matured_years_delinquent": len(matured),
        "consecutive_years": _longest_run(years),
        "first_year": years[0],
        "latest_year": years[-1],
        "latest_matured_year": max(matured),
        "county_latest_year": county_newest,
        "current_levy_year": levy_year,
        "in_current_levy": bool(levy_year and levy_year in years),
        "total_due": total_owed,          # read by enrichment_tax_owed
        "total_owed": total_owed,
        "matured_owed": matured_total,
        "year": years[-1],                # read by enrichment_tax_owed
        "trend": _trend(per_year, matured),
        "still_accruing": years[-1] >= county_newest,
        "mortgage_servicer": newest("mortgage_co"),
        # What a per_year number MEANS, so nobody reads the sum as a payoff:
        #   annual_bill        - Buncombe publishes one row per LEVY YEAR, so
        #                        per_year is that year's own unpaid bill and
        #                        total_owed is the true principal arrears.
        #   advertised_balance - Oconee/Pickens publish an annual delinquent
        #                        list; per_year is the balance advertised that
        #                        year. Verified non-cumulative (a parcel's
        #                        amount holds roughly steady year over year
        #                        rather than stacking), but it is the county's
        #                        advertised figure, not a payoff quote.
        "amount_basis": "annual_bill" if county == "Buncombe" else "advertised_balance",
        "layers": sorted({o.layer for o in obs if o.layer}),
        "parcel_key": parcel_key,
    }
    for o in obs:
        if o.extra:
            raw_block.setdefault("per_year_detail", {})[str(o.year)] = o.extra

    raw: dict[str, Any] = {"multi_year_delinquent_tax": raw_block}
    if mailing:
        mail_state = newest("mail_state")
        raw["owner_mailing"] = {
            "owner": owner,
            "mailing": mailing,
            "situs": situs,
            "parcel_id": None,
            "mail_state": mail_state,
            "absentee": bool(situs and _norm_addr(situs) not in _norm_addr(mailing)),
            "out_of_state": bool(mail_state and mail_state != state),
            "source": "county_tax_roll",
        }

    label = (f"{county} County {state} — delinquent {len(years)} year(s) "
             f"({years[0]}-{years[-1]})")
    if total_owed:
        label += f", ${total_owed:,.0f} owed"
    if raw_block["consecutive_years"] >= 2:
        label += f", {raw_block['consecutive_years']} consecutive"
    if raw_block["trend"] != "flat":
        label += f", arrears {raw_block['trend']}"

    return Listing(
        source=SLUG,
        source_url=page_url,
        listing_type=ListingType.TAX_LIEN,
        property_kind=PropertyKind.UNKNOWN,
        state=state,
        county=county,
        # Placeholder — assemble() overwrites this with the county's own
        # human-formatted parcel id (dashes intact) once it has one.
        parcel_id=parcel_key,
        street_address=situs,
        city=newest("city"),
        zip_code=newest("zip_code"),
        latitude=lat,
        longitude=lng,
        acreage=newest("acres"),
        # NOTE: never put the OWED amount in tax_value/assessed_value — calc.py
        # reads tax_value as the property value and an ARV of taxes-owed x1.25
        # would collapse the lead's economics. Assessed value only when the
        # layer actually publishes one (Buncombe real_value, Pickens ACTUALVAL).
        tax_value=newest("value"),
        judgment_amount=total_owed,
        owner_name=owner,
        defendant=owner,
        legal_description=newest("legal"),
        foreclosure_process="tax",
        description=label,
        first_seen=datetime.utcnow(),
        last_seen=datetime.utcnow(),
        raw=raw,
    )


# ---------------------------------------------------------------------------
# scraper
# ---------------------------------------------------------------------------
def assemble(rows_by_layer: list[tuple[_Layer, list[dict]]]) -> list[Listing]:
    """Join every layer's rows on (state, county, parcel) into arrears histories."""
    # (state, county) -> parcel key -> [_Obs]
    buckets: dict[tuple[str, str], dict[str, list[_Obs]]] = {}
    display: dict[tuple[str, str, str], str] = {}
    year_counts: dict[tuple[str, str], dict[int, set[str]]] = {}
    page_urls: dict[tuple[str, str], str] = {}

    for layer, rows in rows_by_layer:
        ck = (layer.state, layer.county)
        page_urls[ck] = layer.page_url
        for attrs in rows:
            parsed = row_to_obs(attrs, layer)
            if parsed is None:
                continue
            key, ob = parsed
            buckets.setdefault(ck, {}).setdefault(key, []).append(ob)
            year_counts.setdefault(ck, {}).setdefault(layer.year, set()).add(key)
            pid = _first_str(attrs, layer.fields.parcel)
            if pid:
                display.setdefault((layer.state, layer.county, key), pid)

    out: list[Listing] = []
    for ck, parcels in buckets.items():
        state, county = ck
        counts = {y: len(ks) for y, ks in year_counts.get(ck, {}).items()}
        levy = current_levy_year(counts)
        county_newest = max(counts) if counts else None
        if levy:
            log.info("myd.current_levy_detected", county=county, year=levy,
                     parcels=counts.get(levy))
        for key, obs in parcels.items():
            li = build_listing(state, county, key, obs, page_urls[ck], levy,
                               county_latest_year=county_newest)
            if li is None:
                continue
            li.parcel_id = display.get((state, county, key)) or key
            if isinstance(li.raw.get("owner_mailing"), dict):
                li.raw["owner_mailing"]["parcel_id"] = li.parcel_id
            out.append(li)
    return out


class MultiYearDelinquency(BaseScraper):
    slug = SLUG
    name = "Multi-Year Property-Tax Delinquency (Buncombe NC / Oconee SC / Pickens SC)"
    category = "county_tax"
    # Repeat-delinquency parcels are a standing population; if this ever returns
    # 0 something broke (an org moved, a filter drifted).
    expected_min_count = 100
    timeout_s = 900.0

    async def fetch(self) -> Iterable[Listing]:
        async with client(timeout=90.0) as c:
            layers = await discover_layers(c)
            if not layers:
                log.warning("myd.no_layers_discovered")
                return []
            log.info("myd.layers", count=len(layers),
                     detail=[(ly.county, ly.year) for ly in layers])

            sem = asyncio.Semaphore(4)

            async def pull(ly: _Layer) -> tuple[_Layer, list[dict]]:
                async with sem:
                    try:
                        rows = await _fetch_layer(c, ly)
                    except (httpx.HTTPError, ValueError):
                        log.warning("myd.layer_failed", layer=ly.label, exc_info=True)
                        return ly, []
                log.info("myd.layer_ok", layer=ly.label, rows=len(rows))
                return ly, rows

            pulled = await asyncio.gather(*(pull(ly) for ly in layers))

        listings = assemble(list(pulled))
        log.info("myd.done", layers=len(layers), parcels=len(listings),
                 min_years=_MIN_YEARS)
        return listings
