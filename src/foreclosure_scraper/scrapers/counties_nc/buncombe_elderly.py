"""Buncombe County NC elderly/disabled homeowners — a PROPERTY-KEYED motivated-seller source.

The county parcel GIS carries a statutory tax-relief exemption code per parcel (ELD = owner 65+,
DIS = totally & permanently disabled, BLD = blind, VET = disabled veteran). Those owners are prime
motivated-seller prospects (downsizing, can't maintain, or heirs about to inherit). Unlike a
name-indexed lane this is property-keyed: ONE bulk query returns owner + situs address + value +
parcel — a complete lead, no name-resolution needed.

PROPERTY ADDRESS = THE SITUS COLUMNS, NOT `Address` (fixed 2026-10-06). On this layer
`Address`/`CityName`/`State`/`Zipcode` are the OWNER'S MAILING address and `City` is a
jurisdiction code; the parcel's own location exists only as HouseNumber/NumberSuffix/
direction/streetname/StreetType/PostDirection. The scraper used to publish the mailing
block as the property: 271 of 3,898 board rows (2026-10-06) showed a street other than
the parcel's, e.g. a Lytle Cove Rd parcel listed at its owner's Virginia address. The
street now comes from the situs columns (enrichment_arcgis.situs_city_zip); city and ZIP,
which the layer does not publish for the situs, are filled only when the owner's mailing
street IS the situs street (owner-occupied). The mailing block goes to raw['owner_mailing'].

Free, anonymous, compliant (public ArcGIS, no auth/captcha). ~4,300 parcels, paginated.
Gate with FORECLOSURE_ELDERLY_SOURCE=0 to skip.

EXTRACTION-COMPLETENESS AUDIT 2026-10-03: the SAME bulk query (no extra request)
also carries two real, currently-unread fields:
  * SalePrice/DeedDate/DeedBook/DeedPage/Instrument -- a real recorded last-
    arms-length sale, live-confirmed on 1,627 of 4,352 rows (37%). Wired into
    raw['gis']['last_sale'], enrichment_last_sale.py's own highest-priority
    input (same convention as counties_generic.multi_year_delinquent_tax's
    Pickens SALEDT/SALEP fix). NOTE: Buncombe ALSO has a dedicated on-demand
    assessor-card render (assessor_cards/buncombe_nc.py, ASSESSOR_CARD_ON=1,
    ~30s-3min/parcel) that fetches this same sale history plus heated sqft --
    this fix is NOT a duplicate of that: it surfaces the fact for free, for
    EVERY row, from data already paid for in this one bulk call, without
    spending any of that render budget.
  * CareOf -- an executor/guardian/relative "in care of" mailing name,
    live-confirmed non-empty on several rows (e.g. an elderly owner's niece).
    A real contactability signal specific to this exact elderly/disabled
    cohort -- nc_heir_estate_parcels.py already surfaces the identical
    Buncombe "CareOf" field for its own (disjoint) heir/estate-name-matched
    rows, but this scraper's broader Exempt-based rows never read it.
"""
from __future__ import annotations

import os
import re
from datetime import datetime
from typing import Iterable

from ...base_scraper import BaseScraper
from ...enrichment_arcgis import situs_city_zip
from ...http_client import client
from ...models import Listing, ListingType, PropertyKind

QUERY_URL = "https://gis.buncombecounty.org/arcgis/rest/services/property_bc_dis/MapServer/1/query"
_WHERE = "Exempt IN ('ELD','DIS','BLD','VET')"
_OUT = ("pin,pinnum,owner,HouseNumber,NumberSuffix,direction,streetname,StreetType,PostDirection,"
        "Address,CityName,State,Zipcode,TotalMarketValue,TaxValue,LandUse,Class,"
        "Acreage,Exempt,CareOf,SalePrice,DeedDate,DeedBook,DeedPage,Instrument")
_PAGE = 2000
_TAGS = {"ELD": "elderly_exemption", "DIS": "disabled_exemption",
         "BLD": "blind_exemption", "VET": "disabled_veteran_exemption"}


def _iso_date(yyyymmdd) -> str | None:
    """Buncombe's DeedDate is an 8-digit string/number ('20070814')."""
    s = re.sub(r"\D", "", str(yyyymmdd or ""))
    if len(s) != 8:
        return None
    try:
        datetime.strptime(s, "%Y%m%d")  # validate real calendar date
    except ValueError:
        return None
    return f"{s[:4]}-{s[4:6]}-{s[6:]}"


def _f(v) -> float | None:
    try:
        f = float(str(v).replace(",", "").strip())
        return f if f > 0 else None
    except (ValueError, TypeError):
        return None


def _owner_mailing(a: dict, owner: str, pin: str, situs: str | None) -> dict | None:
    """The layer's owner-mailing block, in the raw['owner_mailing'] shape the absentee and
    contact consumers read (mailing_shape.mailing_of). None when the row has no mailing."""
    street = re.sub(r"\s+", " ", str(a.get("Address") or "")).strip()
    city = re.sub(r"\s+", " ", str(a.get("CityName") or "")).strip()
    state = str(a.get("State") or "").strip().upper()[:2] or None
    zipc = str(a.get("Zipcode") or "").strip()
    mailing = " ".join(b for b in (street, city, state or "", zipc) if b) or None
    if not mailing:
        return None
    same = bool(situs and street and re.sub(r"[^A-Z0-9]", "", street.upper())
                == re.sub(r"[^A-Z0-9]", "", situs.upper()))
    return {
        "owner": owner, "mailing": mailing, "situs": situs, "parcel_id": pin,
        "mail_state": state,
        # Unknown (None) when the parcel has no situs to compare against.
        "absentee": (not same) if situs else None,
        "out_of_state": bool(state and state != "NC"),
        "source": "buncombe_elderly_gis",
    }


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

                    raw = {"gis_exempt": {"code": code, "tag": _TAGS.get(code, "exemption")},
                           "life_event": "elderly_disabled_homestead"}
                    # A real recorded sale, already in this same bulk row (no
                    # extra request) -- $0/missing means no arms-length sale
                    # recorded (inheritance, correction deed, etc.), not a
                    # free property, so it is deliberately NOT surfaced then.
                    sale_amt = _f(a.get("SalePrice"))
                    sale_date = _iso_date(a.get("DeedDate"))
                    if sale_amt and sale_date:
                        raw["gis"] = {"last_sale": {
                            "date": sale_date, "amount": sale_amt,
                            "source": "buncombe_elderly_gis",
                            "deed_book": (a.get("DeedBook") or "").strip() or None,
                            "deed_page": (a.get("DeedPage") or "").strip() or None,
                            "instrument": (a.get("Instrument") or "").strip() or None,
                        }}
                    care_of = (a.get("CareOf") or "").strip() or None
                    if care_of:
                        raw["gis_exempt"]["care_of"] = care_of

                    situs, city, zip5 = situs_city_zip(a)
                    raw["owner_mailing"] = _owner_mailing(a, owner, pin, situs)

                    out.append(Listing(
                        source=self.slug,
                        source_url=f"{QUERY_URL}?where=pin%3D%27{pin}%27&outFields=*&f=html",
                        listing_type=ListingType.ELDERLY_DISABLED,
                        property_kind=pk,
                        owner_name=owner,
                        street_address=situs,
                        city=(city.title() if city else None),
                        state="NC",
                        county="Buncombe",
                        zip_code=zip5,
                        parcel_id=pin,
                        market_value=_f(a.get("TotalMarketValue")),
                        assessed_value=_f(a.get("TaxValue")),
                        land_use=(a.get("LandUse") or "").strip() or None,
                        acreage=_f(a.get("Acreage")),
                        description=f"Statutory {_TAGS.get(code, 'exemption').replace('_', ' ')} on file "
                                    f"(owner age/disability property-tax relief).",
                        first_seen=now,
                        last_seen=now,
                        raw=raw,
                    ))
                offset += len(feats)
                if len(feats) < _PAGE:
                    break
        return out
