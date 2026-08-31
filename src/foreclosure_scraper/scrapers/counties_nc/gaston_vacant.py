"""Gaston County NC vacant parcels — a PROPERTY-KEYED motivated-seller / distress source.

The county public parcel GIS carries a per-parcel `VacantImpro` flag. `VacantImpro='Vacant'`
means the parcel has NO improvements (vacant lot / unbuilt land). Vacant land is a classic
distress / absentee signal: holding costs with no rental income, often owned out-of-county
(the mailing address `CURR_*` frequently differs from the situs), and owners are commonly
motivated to offload. Unlike a name-indexed lane this is property-keyed: ONE bulk query
returns owner + situs + mailing + value + parcel + centroid lat/lng — a complete lead, no
name-resolution needed.

Free, anonymous, compliant (public ArcGIS MapServer, no auth/captcha). ~21,288 vacant parcels
of ~117k total, paginated. Gate with FORECLOSURE_GASTON_VACANT=0 to skip.
"""
from __future__ import annotations

import os
from datetime import datetime, timezone
from typing import Iterable

from ...base_scraper import BaseScraper
from ...http_client import client
from ...models import Listing, ListingType, PropertyKind

QUERY_URL = (
    "https://gis.gastoncountync.gov/publicgis/rest/services/"
    "PublicGIS/Parcels/MapServer/11/query"
)
_WHERE = "VacantImpro='Vacant'"
_OUT = (
    "PIN,PID,WHOLE_ADDRESS,PHYSSTRADD,POSTAL,STATE,ZIP,"
    "JAN1_NAME1,JAN1_NAME2,CURR_NAME1,CURR_ADDR1,CURR_CITY,CURR_STATE,CURR_ZIPCODE,"
    "Latitude,Longitude,FMV_TOTAL,FMV_LAND,FMV_IMPRV,TOTVAL,"
    "SALEDATE,SALESAMT,SQFT,YEARBLT,property_use,DESC1_DESC,VacantImpro,CALCAC,DEEDAC"
)
_PAGE = 2000


def _f(v) -> float | None:
    try:
        f = float(str(v).replace(",", "").strip())
        return f if f > 0 else None
    except (ValueError, TypeError):
        return None


def _coord(v) -> float | None:
    """Lat/lng coercion — NC longitudes are negative, so 0/None is the only reject."""
    try:
        f = float(str(v).strip())
        return f if f != 0 else None
    except (ValueError, TypeError):
        return None


def _i(v) -> int | None:
    f = _f(v)
    return int(f) if f is not None else None


def _s(v) -> str | None:
    if v is None:
        return None
    s = str(v).strip()
    return s or None


def _epoch_ms_to_dt(v) -> datetime | None:
    """SALEDATE arrives as epoch-milliseconds (Esri date)."""
    try:
        ms = float(v)
        if ms <= 0:
            return None
        return datetime.fromtimestamp(ms / 1000.0, tz=timezone.utc).replace(tzinfo=None)
    except (ValueError, TypeError, OSError, OverflowError):
        return None


class GastonVacant(BaseScraper):
    slug = "counties_nc.gaston_vacant"
    name = "Gaston County (NC) Vacant Parcels"
    category = "motivated_seller"
    timeout_s = 120.0
    expected_min_count = 0

    async def fetch(self) -> Iterable[Listing]:
        if os.environ.get("FORECLOSURE_GASTON_VACANT", "1") == "0":
            return []
        out: list[Listing] = []
        now = datetime.utcnow()
        async with client(timeout=60.0) as c:
            offset = 0
            while offset < 60000:  # hard backstop; real set ~21,288
                params = {
                    "where": _WHERE,
                    "outFields": _OUT,
                    "returnGeometry": "false",
                    "resultRecordCount": str(_PAGE),
                    "resultOffset": str(offset),
                    "orderByFields": "PID",
                    "f": "json",
                }
                try:
                    r = await c.get(QUERY_URL, params=params)
                    if r.status_code != 200:
                        break
                    feats = r.json().get("features", []) or []
                except Exception:  # noqa: BLE001
                    break
                if not feats:
                    break
                for ft in feats:
                    a = ft.get("attributes", {}) or {}
                    pin = _s(a.get("PIN"))
                    pid = _s(a.get("PID"))
                    owner = _s(a.get("JAN1_NAME1"))
                    if not (pin or pid):
                        continue
                    situs = _s(a.get("WHOLE_ADDRESS")) or _s(a.get("PHYSSTRADD"))
                    zip_raw = a.get("ZIP")
                    zip_code = _s(str(zip_raw)) if zip_raw not in (None, "", 0) else None
                    if zip_code and len(zip_code) == 9:  # 9-digit ZIP+4 stored as int
                        zip_code = zip_code[:5]
                    owner2 = _s(a.get("JAN1_NAME2"))
                    if owner and owner2:
                        owner = f"{owner} & {owner2}"
                    out.append(Listing(
                        source=self.slug,
                        source_url=(
                            f"{QUERY_URL}?where=PIN%3D%27{(pin or '').replace(' ', '+')}%27"
                            "&outFields=*&f=html"
                        ),
                        listing_type=ListingType.DISTRESSED,
                        property_kind=PropertyKind.LAND,
                        owner_name=owner,
                        street_address=situs,
                        city=(_s(a.get("POSTAL")) or "").title() or None,
                        state=_s(a.get("STATE")) or "NC",
                        county="Gaston",
                        zip_code=zip_code,
                        parcel_id=pin or pid,
                        latitude=_coord(a.get("Latitude")),
                        longitude=_coord(a.get("Longitude")),
                        market_value=_f(a.get("FMV_TOTAL")),
                        assessed_value=_f(a.get("TOTVAL")),
                        tax_value=_f(a.get("TOTVAL")),
                        living_sqft=_f(a.get("SQFT")),
                        year_built=_i(a.get("YEARBLT")),
                        acreage=_f(a.get("CALCAC")) or _f(a.get("DEEDAC")),
                        sale_date=_epoch_ms_to_dt(a.get("SALEDATE")),
                        land_use=_s(a.get("property_use")),
                        description=(
                            "Vacant parcel (no improvements on record) per county GIS "
                            "VacantImpro flag — absentee / holding-cost distress signal; "
                            "mailing address often out-of-county."
                        ),
                        first_seen=now,
                        last_seen=now,
                        raw={"gaston_gis": {
                            "signal": "vacant_parcel",
                            "life_event": "vacant_land",
                            "VacantImpro": _s(a.get("VacantImpro")),
                            "DESC1_DESC": _s(a.get("DESC1_DESC")),
                            "property_use": _s(a.get("property_use")),
                            "PIN": pin,
                            "PID": pid,
                            "FMV_TOTAL": _f(a.get("FMV_TOTAL")),
                            "FMV_LAND": _f(a.get("FMV_LAND")),
                            "FMV_IMPRV": _f(a.get("FMV_IMPRV")),
                            "SALESAMT": _f(a.get("SALESAMT")),
                            "owner_mailing": {
                                "name": _s(a.get("CURR_NAME1")),
                                "addr": _s(a.get("CURR_ADDR1")),
                                "city": _s(a.get("CURR_CITY")),
                                "state": _s(a.get("CURR_STATE")),
                                "zip": _s(a.get("CURR_ZIPCODE")),
                            },
                        }},
                    ))
                offset += len(feats)
                if len(feats) < _PAGE:
                    break
        return out
