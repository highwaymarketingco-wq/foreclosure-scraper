"""Mecklenburg County NC tax-foreclosure pipeline (TaxForeclosures ArcGIS layer).

Source
------
The Mecklenburg Office of Tax Administration's "Browse Foreclosed Properties" page
(https://tax.mecknc.gov/tax-foreclosure-properties) embeds an ArcGIS Experience
(item 640b8534655c4397b75f1d5a9cbad201). Its only data source, read from the
item's public JSON on 2026-10-07, is one anonymous MapServer layer:

    https://meckags.mecklenburgcountync.gov/server/rest/services/TaxForeclosures/MapServer/0

Read live the same day (one count query, one group-by query): 618 parcels, every
one in the county's tax-foreclosure pipeline, split by the law firm or process
the county assigned:

    UNASSIGNED   363   (flagged, not yet sent to counsel)
    RBCWB        116   (Ruff, Bond, Cobb, Wade & Bethune)
    KANIA         73   (Kania Law Firm; ``law_firms.kania`` sees these only once
                        a sale date is set, about 5 Mecklenburg rows)
    INREM         66   (NCGS 105-375 in-rem foreclosure by the tax collector)

Fields per parcel: parcel id, situs, ZIP and postal city, total amount due, number
of delinquent bills, total assessed value, bedrooms and baths, property-use code,
Residential/Commercial, point lat/lng and (for some) a broker price opinion PDF.
There is NO owner name on this layer, which keeps the rows free of personal data;
the downstream parcel resolver attaches the owner from the parcel id.

Why it matters: a parcel in the county's tax-foreclosure pipeline is a forced-sale
lead well before any notice of sale is published, and Mecklenburg is the largest
county in NC. Nothing in the repo read this layer before.

Access: open ArcGIS REST, no key, no login, no CAPTCHA. Fields are always
enumerated (never ``outFields=*``) and each attribute bag goes through
``sensitive_fields.drop_sensitive`` before it is stored.

Gate with FORECLOSURE_MECKLENBURG_TAX_FC=0 to skip.
"""
from __future__ import annotations

import os
import re
from datetime import datetime
from typing import Any, Iterable

import structlog

from ... import arcgis_webmap as agw
from ...base_scraper import BaseScraper
from ...http_client import client
from ...models import Listing, ListingType, PropertyKind
from ...sensitive_fields import drop_sensitive

log = structlog.get_logger()

LAYER = ("https://meckags.mecklenburgcountync.gov/server/rest/services/"
         "TaxForeclosures/MapServer/0")
SOURCE_PAGE = "https://tax.mecknc.gov/tax-foreclosure-properties"
ENV_OFF = "FORECLOSURE_MECKLENBURG_TAX_FC"

OUT_FIELDS = ",".join((
    "objectid", "parcel_id", "gis_parcel_id", "situs", "property_description",
    "due_amount", "bill_count", "status", "zip", "po_name", "nme_juris",
    "amt_totalvalue", "num_bedrooms", "cnt_fullbaths", "cnt_halfbaths",
    "cde_propertyuse", "attorney", "proptype", "units",
    "latitude", "longitude", "doc_path", "bpo_status",
))

# Attorney / process codes the layer uses, spelled out for the description.
ATTORNEYS = {
    "KANIA": "Kania Law Firm",
    "RBCWB": "Ruff, Bond, Cobb, Wade & Bethune",
    "INREM": "in-rem foreclosure by the tax collector (NCGS 105-375)",
    "UNASSIGNED": "flagged, not yet assigned to counsel",
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


def _coord(v: Any) -> float | None:
    try:
        return float(str(v).strip())
    except (TypeError, ValueError):
        return None


def _legal(v: Any) -> str | None:
    s = _s(v)
    return None if s in (None, "N/A") else s


def _kind(proptype: str | None) -> PropertyKind:
    p = (proptype or "").strip().lower()
    if p.startswith("res"):
        return PropertyKind.SINGLE_FAMILY
    if p.startswith("com"):
        return PropertyKind.COMMERCIAL
    return PropertyKind.UNKNOWN


def build_listing(attrs: dict[str, Any], *, now: datetime | None = None) -> Listing | None:
    """One layer row -> one Listing. A row without a parcel id is dropped."""
    a = drop_sensitive(attrs or {})
    now = now or datetime.utcnow()
    parcel = _s(a.get("parcel_id")) or _s(a.get("gis_parcel_id"))
    if not parcel:
        return None
    situs = _s(a.get("situs"))
    due = _f(a.get("due_amount"))
    bills = a.get("bill_count")
    try:
        bills = int(bills) if bills is not None else None
    except (TypeError, ValueError):
        bills = None
    attorney = (_s(a.get("attorney")) or "").upper() or None
    lat, lng = _coord(a.get("latitude")), _coord(a.get("longitude"))
    if lat is None or lng is None or not (34.5 < lat < 36.0 and -81.5 < lng < -80.3):
        lat, lng = None, None
    baths = (_f(a.get("cnt_fullbaths")) or 0) + 0.5 * (_f(a.get("cnt_halfbaths")) or 0)

    block = {
        "county": "Mecklenburg",
        "parcel_id": parcel,
        "total_due": due,
        "bill_count": bills,
        "attorney": attorney,
        "attorney_name": ATTORNEYS.get(attorney or "", attorney),
        "status": _s(a.get("status")),
        "jurisdiction": _s(a.get("nme_juris")),
        "property_use_code": _s(a.get("cde_propertyuse")),
        "proptype": _s(a.get("proptype")),
        "units": a.get("units"),
        "total_value": _f(a.get("amt_totalvalue")),
        "bpo_pdf": _s(a.get("doc_path")),
        "bpo_status": _s(a.get("bpo_status")),
        "legal_description": _legal(a.get("property_description")),
        "signal": "tax_foreclosure_pipeline",
    }
    desc = (f"Mecklenburg NC tax foreclosure pipeline - "
            f"{ATTORNEYS.get(attorney or '', attorney or 'status unknown')}")
    if due:
        desc += f" - ${due:,.0f} due"
    if bills:
        desc += f" over {bills} bill(s)"
    return Listing(
        source=MecklenburgTaxForeclosures.slug,
        source_url=f"{LAYER}/query?where=parcel_id%3D%27{parcel}%27&outFields={OUT_FIELDS}&f=html",
        listing_type=ListingType.TAX_LIEN,
        property_kind=_kind(_s(a.get("proptype"))),
        plaintiff="Mecklenburg County",
        street_address=situs,
        city=_s(a.get("po_name")),
        zip_code=_s(a.get("zip")),
        state="NC",
        county="Mecklenburg",
        parcel_id=parcel,
        legal_description=block["legal_description"],
        latitude=lat,
        longitude=lng,
        auction_status=_s(a.get("status")),
        foreclosure_process="tax",
        assessed_value=_f(a.get("amt_totalvalue")),
        tax_value=_f(a.get("amt_totalvalue")),
        bedrooms=_f(a.get("num_bedrooms")),
        bathrooms=baths or None,
        description=desc[:300],
        first_seen=now,
        last_seen=now,
        raw={"mecklenburg_tax_foreclosure": block},
    )


class MecklenburgTaxForeclosures(BaseScraper):
    slug = "counties_nc.mecklenburg_tax_foreclosures"
    name = "Mecklenburg County (NC) Tax Foreclosure Pipeline (TaxForeclosures layer)"
    category = "tax_sale"
    timeout_s = 120.0
    expected_min_count = 0
    optional = True

    async def fetch(self) -> Iterable[Listing]:
        if os.environ.get(ENV_OFF, "1") == "0":
            log.info("mecklenburg_tax_fc.disabled")
            return []
        async with client(timeout=45.0) as http:
            attrs_list = await agw.query_attributes(
                http, LAYER, out_fields=OUT_FIELDS, where="1=1",
                page=1000, max_records=20000, order_by="objectid")
        now = datetime.utcnow()
        out = [li for li in (build_listing(a, now=now) for a in attrs_list) if li is not None]
        log.info("mecklenburg_tax_fc.parsed", raw=len(attrs_list), listings=len(out))
        return out


if __name__ == "__main__":
    import asyncio
    from collections import Counter

    async def _main() -> None:
        s = MecklenburgTaxForeclosures()
        rows = await s.safe_run()
        print(f"outcome={s.last_outcome} count={len(rows)}")
        print(Counter(li.raw["mecklenburg_tax_foreclosure"]["attorney"] for li in rows).most_common())
        print("with_situs", sum(1 for li in rows if li.street_address),
              "with_due", sum(1 for li in rows if li.raw["mecklenburg_tax_foreclosure"]["total_due"]),
              "with_latlng", sum(1 for li in rows if li.latitude))

    asyncio.run(_main())
