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

CONDOMINIUM UNITS KEEP THEIR OWN PARCEL ID (fixed 2026-10-06). Every unit of a condominium
carries the building's 10-digit `pin` plus its own `pinext`; `pinnum` = pin + pinext (pin
9627023924 returns 226 parcels: the 00000 common area plus 225 units, 9658735582 returns 202).
parcel_id used to be the bare `pin`, so all of a building's exempt units were one property to
Listing.dedupe_key() and verification.core.row_key(), and anything padding the pin to
'<pin>00000' (tax_lien_buncombe.pin_of, enrichment_assessor_photo.buncombe_pin_variants) looked up
the common area. Now a unit's parcel_id is its pinnum ('9627023924C0102', which tax.buncombenc.gov
/Parcel/Details/ and the Spatialest image host take as they are) and its source_url narrows the
layer query to that parcel; every other parcel keeps the bare pin (a '<pin>00000' pinnum has the
same dedupe key, and the string the dashboard's saved notes are keyed by). Of the 4,352 exempt
parcels 130 (43 buildings) are units. See condo_units.py, and board_persist.merge_prior_board for
how the published bare-pin rows are carried over to their units.

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
from ...condo_units import board_parcel_id
from ...enrichment_arcgis import situs_city_zip
from ...http_client import client
from ...models import Listing, ListingType, PropertyKind

QUERY_URL = "https://gis.buncombecounty.org/arcgis/rest/services/property_bc_dis/MapServer/1/query"
_WHERE = "Exempt IN ('ELD','DIS','BLD','VET')"
_OUT = ("pin,pinnum,owner,HouseNumber,NumberSuffix,direction,streetname,StreetType,PostDirection,"
        "Address,CityName,State,Zipcode,TotalMarketValue,TaxValue,LandUse,Class,"
        "Acreage,Exempt,CareOf,SalePrice,DeedDate,DeedBook,DeedPage,Instrument,"
        # 2026-10-07 extraction audit: on the layer, never requested (fill on a live
        # 2,000-row sample): propcard, the county's own property-record-card URL (100%);
        # Land/Building/Appraised/ImprovementValue (98-100%, ImprovementValue 32%);
        # SubName/SubLot/SubBlock/SubSect and PlatBook/PlatPage (the recorded plat
        # reference, 99.8%); Stamps (deed excise stamps, 36%); Reason (sale reason code);
        # Improved; NeighborhoodCode; Township.
        "propcard,LandValue,BuildingValue,AppraisedValue,ImprovementValue,SubName,SubLot,"
        "SubBlock,SubSect,PlatBook,PlatPage,Stamps,Reason,Improved,NeighborhoodCode,Township")
_PAGE = 2000
_TAGS = {"ELD": "elderly_exemption", "DIS": "disabled_exemption",
         "BLD": "blind_exemption", "VET": "disabled_veteran_exemption"}


def _source_url(pin: str, parcel_id: str) -> str:
    """The layer's own page for the row. A building's `pin` alone is every unit of it (200+ parcels);
    the unit's row narrows it to its pinnum, and keeps the `pin='...'` clause that
    verification.verifiers.elderly_disabled.scraped_from_layer reads."""
    where = f"pin%3D%27{pin}%27"
    if parcel_id != pin:
        where += f"+AND+pinnum%3D%27{parcel_id}%27"
    return f"{QUERY_URL}?where={where}&outFields=*&f=html"


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


def _s(v) -> str | None:
    return str(v).strip() or None if v not in (None, "") else None


def _card_facts(a: dict) -> dict:
    """The property-card facts this layer carries beyond owner/situs/value (2026-10-07
    extraction audit). Only non-empty values are returned, so no key is fabricated."""
    url = _s(a.get("propcard"))
    facts = {
        "propcard": url if url and url.lower().startswith("http") else None,
        "land_value": _f(a.get("LandValue")),
        "building_value": _f(a.get("BuildingValue")),
        "appraised_value": _f(a.get("AppraisedValue")),
        "improvement_value": _f(a.get("ImprovementValue")),
        "subdivision": _s(a.get("SubName")),
        "sub_lot": _s(a.get("SubLot")),
        "sub_block": _s(a.get("SubBlock")),
        "sub_section": _s(a.get("SubSect")),
        "plat_book": _s(a.get("PlatBook")),
        "plat_page": _s(a.get("PlatPage")),
        "deed_stamps": _f(a.get("Stamps")),
        "sale_reason": _s(a.get("Reason")),
        "improved": _s(a.get("Improved")),
        "neighborhood": _s(a.get("NeighborhoodCode")),
        "township": _s(a.get("Township")),
    }
    return {k: v for k, v in facts.items() if v is not None}


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
                # pinnum is in the order: a building's units share a pin, so paging on the pin
                # alone has no stable order inside it (a page edge could drop or repeat a unit)
                params = {"where": _WHERE, "outFields": _OUT, "returnGeometry": "false",
                          "resultRecordCount": str(_PAGE), "resultOffset": str(offset),
                          "orderByFields": "pin,pinnum", "f": "json"}
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
                    raw["gis_exempt"].update(_card_facts(a))

                    situs, city, zip5 = situs_city_zip(a)
                    parcel = board_parcel_id(pin, a.get("pinnum"))
                    raw["owner_mailing"] = _owner_mailing(a, owner, parcel, situs)

                    out.append(Listing(
                        source=self.slug,
                        source_url=_source_url(pin, parcel),
                        listing_type=ListingType.ELDERLY_DISABLED,
                        property_kind=pk,
                        owner_name=owner,
                        street_address=situs,
                        city=(city.title() if city else None),
                        state="NC",
                        county="Buncombe",
                        zip_code=zip5,
                        parcel_id=parcel,
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
