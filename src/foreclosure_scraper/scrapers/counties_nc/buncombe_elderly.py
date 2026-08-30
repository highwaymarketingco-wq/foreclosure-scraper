"""Buncombe County NC elderly/disabled homeowners — a PROPERTY-KEYED motivated-seller source.

The county parcel GIS carries a statutory tax-relief exemption code per parcel (ELD = owner 65+,
DIS = totally & permanently disabled, BLD = blind, VET = disabled veteran). Those owners are prime
motivated-seller prospects (downsizing, can't maintain, or heirs about to inherit). Unlike a
name-indexed lane this is property-keyed: ONE bulk query returns owner + situs address + value +
parcel — a complete lead, no name-resolution needed.

Free, anonymous, compliant (public ArcGIS, no auth/captcha). ~4,300 parcels, paginated.
Gate with FORECLOSURE_ELDERLY_SOURCE=0 to skip.
"""
from __future__ import annotations

import os
from datetime import datetime
from typing import Iterable

from ...base_scraper import BaseScraper
from ...http_client import client
from ...models import Listing, ListingType, PropertyKind

QUERY_URL = "https://gis.buncombecounty.org/arcgis/rest/services/property_bc_dis/MapServer/1/query"
_WHERE = "Exempt IN ('ELD','DIS','BLD','VET')"
_OUT = "pin,owner,Address,CityName,State,Zipcode,TotalMarketValue,TaxValue,LandUse,Class,Acreage,Exempt"
_PAGE = 2000
_TAGS = {"ELD": "elderly_exemption", "DIS": "disabled_exemption",
         "BLD": "blind_exemption", "VET": "disabled_veteran_exemption"}


def _f(v) -> float | None:
    try:
        f = float(str(v).replace(",", "").strip())
        return f if f > 0 else None
    except (ValueError, TypeError):
        return None


class BuncombeElderly(BaseScraper):
    slug = "counties_nc.buncombe_elderly"
    name = "Buncombe County (NC) Elderly/Disabled Homeowners"
    category = "motivated_seller"
    timeout_s = 120.0
    expected_min_count = 2000

    async def fetch(self) -> Iterable[Listing]:
        if os.environ.get("FORECLOSURE_ELDERLY_SOURCE", "1") == "0":
            return []
        out: list[Listing] = []
        now = datetime.utcnow()
        async with client(timeout=60.0) as c:
            offset = 0
            while offset < 50000:  # hard backstop; real set ~4,300
                params = {"where": _WHERE, "outFields": _OUT, "returnGeometry": "false",
                          "resultRecordCount": str(_PAGE), "resultOffset": str(offset),
                          "orderByFields": "pin", "f": "json"}
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
                    owner = (a.get("owner") or "").strip()
                    pin = (a.get("pin") or "").strip()
                    if not owner or not pin:
                        continue
                    code = (a.get("Exempt") or "").strip().upper()[:3]
                    cls = str(a.get("Class") or "").strip()
                    pk = PropertyKind.SINGLE_FAMILY if cls == "100" else PropertyKind.UNKNOWN
                    out.append(Listing(
                        source=self.slug,
                        source_url=f"{QUERY_URL}?where=pin%3D%27{pin}%27&outFields=*&f=html",
                        listing_type=ListingType.ELDERLY_DISABLED,
                        property_kind=pk,
                        owner_name=owner,
                        street_address=(a.get("Address") or "").strip() or None,
                        city=((a.get("CityName") or "").strip().title() or None),
                        state="NC",
                        county="Buncombe",
                        zip_code=(str(a.get("Zipcode") or "").strip() or None),
                        parcel_id=pin,
                        market_value=_f(a.get("TotalMarketValue")),
                        assessed_value=_f(a.get("TaxValue")),
                        land_use=(a.get("LandUse") or "").strip() or None,
                        acreage=_f(a.get("Acreage")),
                        description=f"Statutory {_TAGS.get(code, 'exemption').replace('_', ' ')} on file "
                                    f"(owner age/disability property-tax relief).",
                        first_seen=now,
                        last_seen=now,
                        raw={"gis_exempt": {"code": code, "tag": _TAGS.get(code, "exemption")},
                             "life_event": "elderly_disabled_homestead"},
                    ))
                offset += len(feats)
                if len(feats) < _PAGE:
                    break
        return out
