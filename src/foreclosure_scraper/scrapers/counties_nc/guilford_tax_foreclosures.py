"""Guilford County NC tax-foreclosure pipeline (ForeclosuresPublic ArcGIS layer).

Source
------
Guilford County's own "Preview of Foreclosures" page
(https://www.guilfordcountync.gov/preview-foreclosures) links a dashboard and an
Experience Builder app ("Advanced Foreclosure Properties Map & Search"). Both read
one public, anonymous ArcGIS layer:

    https://gcgis.guilfordcountync.gov/arcgis/rest/services/Foreclosure/ForeclosuresPublic/FeatureServer/0

Every parcel the county tax office has flagged for tax foreclosure is a row. Read
live 2026-10-07 (one count query, one group-by query, one full read): 931 rows, all
FLAG_TYPE = FLAGMORTGAGE, with FLAG_STATUS one of

    Assigned To Attorney   ~890   (suit filed or about to be; no sale date yet)
    Notice of Sale            17   (sale advertised)
    Pending Confirmation       6   (sold, waiting on the clerk)
    Upset Bid                 13   (10-day upset-bid window)

The full read the same day produced 930 listings (one row carries neither a PIN nor
a parcel id), every one with owner, situs and owner mailing address.

Each row carries the record owner, the owner's mailing address, the situs, NC PIN,
REID, assessed value, deed book-page and date, plat, lot size, and for the sale
statuses the auction date, time and place. The commissioner sales themselves are
run by Zacchaeus Legal Services (zls-nc.com, already read by
``law_firms.zacchaeus``), but that feed only shows parcels once a sale is set; this
layer is the whole pipeline, about 50 times larger.

Why it matters: a parcel assigned to the county attorney for tax foreclosure is a
forced-sale lead months before any newspaper notice, and the owner and mailing
address come with it, so no name resolution is needed.

Access: open ArcGIS REST, no key, no login, no CAPTCHA. The layer's maxRecordCount
is 2000, so one page holds the whole set; pagination is still handled. Fields are
always enumerated (never ``outFields=*``) and every attribute bag goes through
``sensitive_fields.drop_sensitive`` before it is stored.

Gate with FORECLOSURE_GUILFORD_TAX_FC=0 to skip.
"""
from __future__ import annotations

import os
import re
from datetime import datetime, timezone
from typing import Any, Iterable

import structlog

from ... import arcgis_webmap as agw
from ...base_scraper import BaseScraper
from ...http_client import client
from ...models import Listing, ListingType, PropertyKind
from ...sensitive_fields import drop_sensitive

log = structlog.get_logger()

LAYER = ("https://gcgis.guilfordcountync.gov/arcgis/rest/services/"
         "Foreclosure/ForeclosuresPublic/FeatureServer/0")
SOURCE_PAGE = "https://www.guilfordcountync.gov/preview-foreclosures"
ENV_OFF = "FORECLOSURE_GUILFORD_TAX_FC"

# Explicit field list. Owner_History (prior owners) is deliberately NOT requested:
# it is other people's names and the deed reference below already gives the chain.
OUT_FIELDS = ",".join((
    "OBJECTID", "Owner", "LOCATION_ADDR", "Total_Assessed", "Total_Land_Value",
    "Total_Building_Value", "YEAR_BUILT", "PARCEL_ID", "REID", "PIN",
    "FLAG_TYPE", "FLAG_STATUS", "Centroid_X", "Centroid_Y",
    "AuctionDate", "AuctionTime", "AuctionLocation",
    "Mail_Address", "Mail_City", "Mail_State", "Mail_Zip",
    "PROPERTY_DESCR", "Deed", "Plat", "DEED_DATE", "Property_Type",
    "Structure_Size", "Lot_Size", "BEDROOMS", "Bathrooms",
))

# Statuses that mean a sale is set, done, or in its upset window.
_SALE_STATUSES = ("notice of sale", "upset bid", "pending confirmation", "sold")

_KIND = {
    "RESIDENTIAL": PropertyKind.SINGLE_FAMILY,
    "TOWNHOUSE": PropertyKind.TOWNHOUSE,
    "CONDO": PropertyKind.CONDO,
    "VACANT": PropertyKind.LAND,
    "AGRI/HORT": PropertyKind.LAND,
    "DRAINAGE LOT": PropertyKind.LAND,
    "DEVELOPMT RESTRICTED": PropertyKind.LAND,
    "MFG HOM": PropertyKind.MOBILE,
    "SINGLE WIDE MH": PropertyKind.MOBILE,
    "MULTI-FAMILY<4": PropertyKind.MULTI_FAMILY,
    "APART": PropertyKind.MULTI_FAMILY,
    "COMM": PropertyKind.COMMERCIAL,
    "OFFICE": PropertyKind.COMMERCIAL,
    "RETAIL": PropertyKind.COMMERCIAL,
    "IND": PropertyKind.COMMERCIAL,
}


def _s(v: Any) -> str | None:
    s = re.sub(r"\s+", " ", str(v if v is not None else "")).strip()
    return s or None


def _f(v: Any) -> float | None:
    try:
        f = float(str(v).replace(",", "").replace("$", "").strip())
    except (TypeError, ValueError):
        return None
    return f if f > 0 else None


def _epoch_ms(v: Any) -> datetime | None:
    """ArcGIS date (epoch milliseconds, UTC) -> naive UTC datetime."""
    try:
        ms = float(v)
    except (TypeError, ValueError):
        return None
    if ms <= 0:
        return None
    return datetime.fromtimestamp(ms / 1000.0, tz=timezone.utc).replace(tzinfo=None)


def _kind(prop_type: str | None) -> PropertyKind:
    if not prop_type:
        return PropertyKind.UNKNOWN
    return _KIND.get(prop_type.strip().upper(), PropertyKind.UNKNOWN)


def _is_absentee(mail_state: str | None, mail_street: str | None, situs: str | None) -> bool:
    """Owner mails from out of state, from a PO box, or from a different street than
    the parcel. The street test only runs when the situs carries a house number."""
    st = (mail_state or "").strip().upper()
    if st and st != "NC":
        return True
    street = (mail_street or "").strip().upper()
    if re.search(r"\bP\.?\s?O\.?\s?BOX\b", street):
        return True
    if street and situs and re.match(r"^\d", situs.strip()):
        a = street.split()
        b = situs.strip().upper().split()
        if a[:2] != b[:2]:
            return True
    return False


def build_listing(attrs: dict[str, Any], *, now: datetime | None = None) -> Listing | None:
    """One layer row -> one Listing. Rows with neither a PIN nor a parcel id are dropped."""
    a = drop_sensitive(attrs or {})
    now = now or datetime.utcnow()
    pin = _s(a.get("PIN"))
    parcel = _s(a.get("PARCEL_ID")) or _s(a.get("REID"))
    if not pin and not parcel:
        return None

    owner = _s(a.get("Owner"))
    situs = _s(a.get("LOCATION_ADDR"))
    status = _s(a.get("FLAG_STATUS"))
    flag_type = _s(a.get("FLAG_TYPE"))
    auction_dt = _epoch_ms(a.get("AuctionDate"))
    status_l = (status or "").lower()
    in_sale = any(k in status_l for k in _SALE_STATUSES)
    listing_type = ListingType.TAX_SALE if in_sale else ListingType.TAX_LIEN

    lat = _f(a.get("Centroid_Y"))
    lng = a.get("Centroid_X")
    try:
        lng = float(lng) if lng is not None else None
    except (TypeError, ValueError):
        lng = None
    # The layer's centroids are WGS84 degrees; anything else is not usable as lat/lng.
    if lat is None or lng is None or not (33.0 < lat < 37.5 and -85.0 < lng < -75.0):
        lat, lng = None, None

    mail_street = _s(a.get("Mail_Address"))
    mail_city = _s(a.get("Mail_City"))
    mail_state = _s(a.get("Mail_State"))
    mail_zip = _s(a.get("Mail_Zip"))
    deed_dt = _epoch_ms(a.get("DEED_DATE"))

    block: dict[str, Any] = {
        "county": "Guilford",
        "flag_type": flag_type,
        "flag_status": status,
        "pin": pin,
        "reid": _s(a.get("REID")),
        "parcel_id": parcel,
        "auction_date": auction_dt.date().isoformat() if auction_dt else None,
        "auction_time": _s(a.get("AuctionTime")),
        "auction_location": _s(a.get("AuctionLocation")),
        "auction_date_past": bool(auction_dt and auction_dt < now),
        "total_assessed": _f(a.get("Total_Assessed")),
        "land_value": _f(a.get("Total_Land_Value")),
        "building_value": _f(a.get("Total_Building_Value")),
        "deed": _s(a.get("Deed")),
        "deed_date": deed_dt.date().isoformat() if deed_dt else None,
        "plat": _s(a.get("Plat")),
        "legal_description": _s(a.get("PROPERTY_DESCR")),
        "property_type": _s(a.get("Property_Type")),
        "signal": "tax_foreclosure_pipeline",
        "process": "NCGS 105-374 tax foreclosure (county-flagged)",
    }
    raw: dict[str, Any] = {"guilford_tax_foreclosure": block}
    if mail_street or mail_city:
        mailing = ", ".join(x for x in (
            mail_street, " ".join(y for y in (mail_city, mail_state, mail_zip) if y)) if x)
        raw["owner_mailing"] = {
            "street": mail_street, "city": mail_city, "state": mail_state, "zip": mail_zip,
            "mailing": mailing or None,
            "mail_state": (mail_state or "").upper() or None,
            "out_of_state": bool(mail_state and mail_state.strip().upper() != "NC"),
            "absentee": _is_absentee(mail_state, mail_street, situs),
            "source": "guilford_foreclosures_public",
        }

    where = f"PIN='{pin}'" if pin else f"PARCEL_ID='{parcel}'"
    desc_bits = [f"Guilford NC tax foreclosure: {status or 'flagged'}"]
    if auction_dt and in_sale:
        desc_bits.append(f"auction {auction_dt.date().isoformat()}")
    return Listing(
        source=GuilfordTaxForeclosures.slug,
        source_url=f"{LAYER}/query?where={where}&outFields={OUT_FIELDS}&f=html",
        listing_type=listing_type,
        property_kind=_kind(_s(a.get("Property_Type"))),
        owner_name=owner,
        defendant=owner,
        plaintiff="Guilford County",
        street_address=situs,
        state="NC",
        county="Guilford",
        parcel_id=pin or parcel,
        legal_description=_s(a.get("PROPERTY_DESCR")),
        latitude=lat,
        longitude=lng,
        sale_date=auction_dt if in_sale else None,
        sale_time=_s(a.get("AuctionTime")) if in_sale else None,
        sale_location=_s(a.get("AuctionLocation")) if in_sale else None,
        auction_status=status,
        foreclosure_process="tax",
        assessed_value=_f(a.get("Total_Assessed")),
        tax_value=_f(a.get("Total_Assessed")),
        year_built=int(a["YEAR_BUILT"]) if _f(a.get("YEAR_BUILT")) else None,
        bedrooms=_f(a.get("BEDROOMS")),
        bathrooms=_f(a.get("Bathrooms")),
        living_sqft=_f(a.get("Structure_Size")),
        acreage=_f(a.get("Lot_Size")),
        description=" - ".join(desc_bits)[:300],
        first_seen=now,
        last_seen=now,
        raw=raw,
    )


class GuilfordTaxForeclosures(BaseScraper):
    slug = "counties_nc.guilford_tax_foreclosures"
    name = "Guilford County (NC) Tax Foreclosure Pipeline (ForeclosuresPublic)"
    category = "tax_sale"
    timeout_s = 120.0
    expected_min_count = 0
    optional = True

    async def fetch(self) -> Iterable[Listing]:
        if os.environ.get(ENV_OFF, "1") == "0":
            log.info("guilford_tax_fc.disabled")
            return []
        async with client(timeout=45.0) as http:
            attrs_list = await agw.query_attributes(
                http, LAYER, out_fields=OUT_FIELDS, where="1=1",
                page=2000, max_records=20000, order_by="OBJECTID")
        now = datetime.utcnow()
        out: list[Listing] = []
        for attrs in attrs_list:
            li = build_listing(attrs, now=now)
            if li is not None:
                out.append(li)
        log.info("guilford_tax_fc.parsed", raw=len(attrs_list), listings=len(out),
                 in_sale=sum(1 for li in out if li.listing_type == ListingType.TAX_SALE))
        return out


if __name__ == "__main__":
    import asyncio
    from collections import Counter

    async def _main() -> None:
        s = GuilfordTaxForeclosures()
        rows = await s.safe_run()
        print(f"outcome={s.last_outcome} count={len(rows)}")
        print(Counter(li.auction_status for li in rows).most_common())
        print("with_owner", sum(1 for li in rows if li.owner_name),
              "with_situs", sum(1 for li in rows if li.street_address),
              "with_mailing", sum(1 for li in rows if (li.raw or {}).get("owner_mailing")))

    asyncio.run(_main())
