"""Transylvania County NC vacant-land parcels — a PROPERTY-KEYED motivated-seller source.

The county parcel FeatureServer carries a per-parcel building value (BUILDING_V). Parcels with
BUILDING_V=0 are unimproved / vacant land — a classic motivated-seller cohort (out-of-area owners,
inherited lots, tax-burdened holds). One bulk ArcGIS query returns owner + situs (LEGAL_ADDR) +
land value + parcel PIN + sale history, so each row is a complete property-keyed lead with no
name-resolution step.

Note: ADDRESS_1/2/3 + CITY/STATE/ZIP are the OWNER MAILING address (frequently out of county/state);
LEGAL_ADDR is the in-county situs/property location. We key the listing to the situs and stash the
owner mailing block in raw.

Free, anonymous, compliant (public ArcGIS, no auth/captcha). ~11,131 vacant parcels, paginated.
Gate with FORECLOSURE_TRANSYLVANIA_VACANT=0 to skip.
"""
from __future__ import annotations

import os
from datetime import datetime
from typing import Iterable

from ...base_scraper import BaseScraper
from ...http_client import client
from ...models import Listing, ListingType, PropertyKind

QUERY_URL = "https://gis.transylvaniacounty.org/server/rest/services/Parcels/FeatureServer/2/query"
_WHERE = "BUILDING_V=0 AND OWNER_NAME IS NOT NULL"
_OUT = ("PIN,OWNER_NAME,ADDRESS_1,ADDRESS_2,ADDRESS_3,CITY,STATE,ZIP_CODE,LEGAL_ADDR,"
        "USECODE,ZONING,ACRES,HEATED_SQ_,AYB,SALE_PRICE,SALE_DATE,LAND_VALUE,ASSESSED_V,"
        "BUILDING_V,DEED_BK,PAGE,Report_URL")
_PAGE = 2000


def _f(v) -> float | None:
    try:
        f = float(str(v).replace(",", "").strip())
        return f if f > 0 else None
    except (ValueError, TypeError):
        return None


def _s(v) -> str | None:
    if v is None:
        return None
    s = str(v).strip()
    return s or None


class TransylvaniaVacant(BaseScraper):
    slug = "counties_nc.transylvania_vacant"
    name = "Transylvania County (NC) Vacant Land"
    category = "motivated_seller"
    timeout_s = 120.0
    expected_min_count = 0

    async def fetch(self) -> Iterable[Listing]:
        if os.environ.get("FORECLOSURE_TRANSYLVANIA_VACANT", "1") == "0":
            return []
        out: list[Listing] = []
        now = datetime.utcnow()
        async with client(timeout=60.0) as c:
            offset = 0
            while offset < 60000:  # hard backstop; real set ~11,131
                params = {"where": _WHERE, "outFields": _OUT, "returnGeometry": "false",
                          "resultRecordCount": str(_PAGE), "resultOffset": str(offset),
                          "orderByFields": "OBJECTID", "f": "json"}
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
                    owner = _s(a.get("OWNER_NAME"))
                    if not pin or not owner:
                        continue
                    situs = _s(a.get("LEGAL_ADDR"))
                    year = None
                    try:
                        ay = int(str(a.get("AYB")).strip())
                        year = ay if 1700 < ay < 2100 else None
                    except (ValueError, TypeError):
                        year = None
                    mailing = {
                        "owner_line2": _s(a.get("ADDRESS_1")),
                        "addr2": _s(a.get("ADDRESS_2")),
                        "street": _s(a.get("ADDRESS_3")),
                        "city": _s(a.get("CITY")),
                        "state": _s(a.get("STATE")),
                        "zip": _s(a.get("ZIP_CODE")),
                    }
                    out.append(Listing(
                        source=self.slug,
                        source_url=(_s(a.get("Report_URL"))
                                    or f"{QUERY_URL}?where=PIN%3D%27{pin}%27&outFields=*&f=html"),
                        listing_type=ListingType.UNKNOWN,
                        property_kind=PropertyKind.LAND,
                        owner_name=owner,
                        street_address=situs,
                        city=None,  # CITY/STATE/ZIP are owner mailing, not situs
                        state="NC",
                        county="Transylvania",
                        zip_code=None,
                        parcel_id=pin,
                        legal_description=situs,
                        zoning=_s(a.get("ZONING")),
                        acreage=_f(a.get("ACRES")),
                        living_sqft=_f(a.get("HEATED_SQ_")),
                        year_built=year,
                        land_use=_s(a.get("USECODE")),
                        assessed_value=_f(a.get("ASSESSED_V")),
                        market_value=_f(a.get("LAND_VALUE")),
                        description="Vacant/unimproved parcel (building value $0) — motivated-seller "
                                    "cohort (out-of-area/inherited/tax-burdened land holds).",
                        first_seen=now,
                        last_seen=now,
                        raw={"transylvania_vacant": {
                            "building_value": a.get("BUILDING_V"),
                            "land_value": a.get("LAND_VALUE"),
                            "assessed_value": a.get("ASSESSED_V"),
                            "sale_price": a.get("SALE_PRICE"),
                            "sale_date": _s(a.get("SALE_DATE")),
                            "deed_book": _s(a.get("DEED_BK")),
                            "deed_page": _s(a.get("PAGE")),
                            "usecode": _s(a.get("USECODE")),
                            "acres": a.get("ACRES"),
                            "owner_mailing": mailing,
                            "signal": "vacant_land",
                        }},
                    ))
                offset += len(feats)
                if len(feats) < _PAGE:
                    break
        return out
