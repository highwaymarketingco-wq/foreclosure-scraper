"""McDowell County NC deceased-owner parcels — a PROPERTY-KEYED probate/heir lead source.

The county parcel GIS carries the record owner name verbatim, and the assessor flags a
deceased owner in-line — e.g. ``ownname2 = 'GROSS PENNY L (DECEASED)'``. Parcels whose
owner (primary OR second owner) is annotated "DECEASED" are prime probate/heir prospects:
the estate is unsettled, heirs often want a fast cash sale, and there is frequently deferred
maintenance or tax exposure. Property-keyed, so ONE bulk query returns owner + situs address
+ value + parcel — a complete lead with no name-resolution step.

Free, anonymous, compliant (public ArcGIS FeatureServer, no auth/captcha). ~414 parcels.
Gate with FORECLOSURE_MCDOWELL_PROBATE=0 to skip.
"""
from __future__ import annotations

import os
from datetime import datetime
from typing import Iterable

from ...base_scraper import BaseScraper
from ...http_client import client
from ...models import Listing, ListingType, PropertyKind

QUERY_URL = (
    "https://services9.arcgis.com/ETP7IuCigkUz7iI9/arcgis/rest/services/"
    "McDowell_Parcels/FeatureServer/0/query"
)
# Deceased flag can sit in either the primary or the second owner name field.
_WHERE = "UPPER(ownname) LIKE '%DECEASED%' OR UPPER(ownname2) LIKE '%DECEASED%'"
_OUT = ("parno,ownname,ownname2,mailadd,mcity,mstate,mzip,siteadd,scity,sstate,szip,"
        "improvval,landval,parval,parvaltype,gisacres,struct,parusedesc,structyear,"
        "sourceref,saledatetx")
_PAGE = 2000


def _f(v) -> float | None:
    try:
        f = float(str(v).replace(",", "").strip())
        return f if f > 0 else None
    except (ValueError, TypeError):
        return None


def _clean_addr(raw) -> str | None:
    """Normalize the full site address: collapse whitespace, drop leading zeros on the number."""
    s = " ".join(str(raw or "").split())
    if not s:
        return None
    parts = s.split(" ", 1)
    if parts[0].isdigit():
        num = parts[0].lstrip("0") or "0"
        s = num + (" " + parts[1] if len(parts) > 1 else "")
    return s.title() or None


class McDowellProbate(BaseScraper):
    slug = "counties_nc.mcdowell_probate"
    name = "McDowell County (NC) Deceased-Owner Parcels (Probate/Heir)"
    category = "distress"
    timeout_s = 120.0
    expected_min_count = 0

    async def fetch(self) -> Iterable[Listing]:
        if os.environ.get("FORECLOSURE_MCDOWELL_PROBATE", "1") == "0":
            return []
        out: list[Listing] = []
        now = datetime.utcnow()
        async with client(timeout=60.0) as c:
            offset = 0
            while offset < 20000:  # hard backstop; real set ~414
                params = {"where": _WHERE, "outFields": _OUT, "returnGeometry": "false",
                          "resultRecordCount": str(_PAGE), "resultOffset": str(offset),
                          "orderByFields": "parno", "f": "json"}
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
                    owner = (a.get("ownname") or "").strip()
                    owner2 = (a.get("ownname2") or "").strip()
                    parcel = (a.get("parno") or "").strip()
                    if not parcel:
                        continue
                    # Which owner carried the deceased flag (for the raw signal).
                    deceased_owner = owner if "DECEASED" in owner.upper() else owner2
                    site = _clean_addr(a.get("siteadd"))
                    city = ((a.get("scity") or "").strip().title() or None)
                    # Site city is often blank; fall back to mailing city.
                    if not city:
                        city = ((a.get("mcity") or "").strip().title() or None)
                    zip_code = (str(a.get("szip") or "").strip()
                                or str(a.get("mzip") or "").strip() or None)
                    struct = (a.get("struct") or "").strip().upper()
                    use = (a.get("parusedesc") or "").strip()
                    pk = PropertyKind.SINGLE_FAMILY if struct == "Y" else PropertyKind.LAND
                    yb = a.get("structyear")
                    try:
                        yb = int(yb) if yb and int(yb) > 1700 else None
                    except (ValueError, TypeError):
                        yb = None
                    out.append(Listing(
                        source=self.slug,
                        source_url=(f"{QUERY_URL}?where=parno%3D%27{parcel}%27"
                                    "&outFields=*&f=html"),
                        listing_type=ListingType.DISTRESSED,
                        property_kind=pk,
                        owner_name=owner or owner2 or None,
                        street_address=site,
                        city=city,
                        state="NC",
                        county="McDowell",
                        zip_code=zip_code,
                        parcel_id=parcel,
                        assessed_value=_f(a.get("parval")),
                        market_value=_f(a.get("parval")),
                        acreage=_f(a.get("gisacres")),
                        year_built=yb,
                        land_use=use or None,
                        description="owner flagged deceased — probate/heir lead",
                        first_seen=now,
                        last_seen=now,
                        raw={"mcdowell_probate": {
                            "signal": "deceased_owner",
                            "deceased_owner": deceased_owner or None,
                            "ownname": owner or None,
                            "ownname2": owner2 or None,
                            "mailing_address": " ".join(str(a.get("mailadd") or "").split()) or None,
                            "mailing_city": (a.get("mcity") or "").strip() or None,
                            "mailing_state": (a.get("mstate") or "").strip() or None,
                            "mailing_zip": (a.get("mzip") or "").strip() or None,
                            "improved_value": _f(a.get("improvval")),
                            "land_value": _f(a.get("landval")),
                            "parcel_value": _f(a.get("parval")),
                            "value_type": (a.get("parvaltype") or "").strip() or None,
                            "deed_book_page": (a.get("sourceref") or "").strip() or None,
                            "last_sale_date": (a.get("saledatetx") or "").strip() or None,
                            "parcel_use": use or None,
                        }},
                    ))
                got = len(feats)
                offset += got
                if got < _PAGE:
                    break
        return out
