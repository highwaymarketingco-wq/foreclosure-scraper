"""Laurens County SC assessor card — county ArcGIS REST (public, no login).

Fills the SC bulk gap on the PRICE side only: recorded SALE PRICE + deed
book/page + owner. There is NO building/CAMA sqft on this GIS layer (parcel
attributes only), so heated living sqft is not available here -> price-only.

One endpoint, keyed by TMS (dashed, e.g. 905-02-01-021):
  Pebble/PropertyParcel/MapServer/5  ->
    Sale_Price ("80,000"), Sale_Date ("20201020" = YYYYMMDD),
    Deed_Book, Deed_Page, Owner, Property_Address
"""
from __future__ import annotations

import re

from ..http_client import client
from .base import CardResult, CardSale, money

_LAYER = (
    "https://www.laurenscountygis.org/arcgis/rest/services/"
    "Pebble/PropertyParcel/MapServer/5/query"
)
SOURCE_URL = "https://www.laurenscountygis.org/"
_UA = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) Chrome/126"}

COUNTY = ("SC", "Laurens")   # auto-discovery key (see enrichment_assessor_card._adapters)

_TMS_RE = re.compile(r"\d+")


def _tms(li) -> str | None:
    """Normalize li.parcel_id to the dashed Laurens TMS (e.g. 905-02-01-021).

    Accepts already-dashed input, or a bare digit string that we re-segment into
    the county's 3-2-2-3 grouping. Returns None if there's nothing usable.
    """
    raw = (li.parcel_id or "").strip()
    if not raw:
        return None
    if "-" in raw:
        return raw
    digits = "".join(_TMS_RE.findall(raw))
    if len(digits) == 10:   # 3-2-2-3
        return f"{digits[0:3]}-{digits[3:5]}-{digits[5:7]}-{digits[7:10]}"
    return raw or None


def _sale_date(v) -> str | None:
    """'20201020' (YYYYMMDD) -> '2020-10-20'. Falls back to a bare year string."""
    s = re.sub(r"\D", "", str(v or ""))
    if len(s) == 8:
        return f"{s[0:4]}-{s[4:6]}-{s[6:8]}"
    if len(s) == 4:
        return s
    return None


def _clean(v) -> str | None:
    if v is None:
        return None
    s = str(v).strip()
    return s or None


async def fetch(li) -> CardResult | None:
    tms = _tms(li)
    if not tms:
        return None
    # ArcGIS where-clause: escape any single quote in the key defensively.
    where = "TMS='{}'".format(tms.replace("'", "''"))
    params = {
        "where": where,
        "outFields": "*",
        "returnGeometry": "false",
        "f": "json",
    }
    async with client(timeout=30.0, headers=_UA) as c:
        try:
            data = (await c.get(_LAYER, params=params)).json()
        except Exception:
            return None

    feats = data.get("features") or []
    attrs = (feats[0].get("attributes") if feats else {}) or {}
    price = money(attrs.get("Sale_Price"))
    if not price:
        return None

    sale = CardSale(
        sale_date=_sale_date(attrs.get("Sale_Date")),
        price=price,
        book=_clean(attrs.get("Deed_Book")),
        page=_clean(attrs.get("Deed_Page")),
        grantee=_clean(attrs.get("Owner")),
    )
    res = CardResult(source_url=SOURCE_URL, sales=[sale])
    return res if res.has_fill() else None
