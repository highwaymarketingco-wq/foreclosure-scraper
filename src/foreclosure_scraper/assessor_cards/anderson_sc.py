"""Anderson County SC assessor card — county ArcGIS REST (public, no login).

Fills the SC bulk gap: recorded SALE PRICE + sale history + appraised market value.
Heated sqft is NOT available here (the ACPASS property card is login-walled and the
public GIS has no building/CAMA sqft layer), so this adapter is price-only.

Two endpoints, keyed by TMS (li.parcel_id digits):
  NewPropertyViewer/MapServer/5  -> MRKT_VALUE, SALE_PRICE, DBOOK/DPAGE, SALE_YEAR
  Parcel_Sales/MapServer/0       -> SAPRIC, SADEBK/SADEPG, SALEDATE(epoch ms), SATYPE
"""
from __future__ import annotations

import re

from ..http_client import client
from .base import CardResult, CardSale, epoch_ms_to_iso, money

_CUR = "https://propertyviewer.andersoncountysc.org/arcgis/rest/services/NewPropertyViewer/MapServer/5/query"
_SALES = "https://propertyviewer.andersoncountysc.org/arcgis/rest/services/Parcel_Sales/MapServer/0/query"
SOURCE_URL = "https://acpass.andersoncountysc.org/"
_UA = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) Chrome/126"}

COUNTY = ("SC", "Anderson")   # auto-discovery key (see enrichment_assessor_card._adapters)


def _tms(li) -> str | None:
    digits = re.sub(r"\D", "", li.parcel_id or "")
    return digits or None


def _parse_sales(features: list[dict]) -> list[CardSale]:
    rows: list[tuple[int, CardSale]] = []
    for f in features or []:
        a = f.get("attributes") or {}
        rows.append((int(a.get("SALEDATE") or 0), CardSale(
            sale_date=epoch_ms_to_iso(a.get("SALEDATE")) or (str(a["SALEYEAR"]) if a.get("SALEYEAR") else None),
            price=money(a.get("SAPRIC")),
            book=(str(a.get("SADEBK")).strip() or None) if a.get("SADEBK") is not None else None,
            page=(str(a.get("SADEPG")).strip() or None) if a.get("SADEPG") is not None else None,
            reason=(a.get("SATYPE") or None),
        )))
    rows.sort(key=lambda r: r[0], reverse=True)   # newest first
    return [cs for _, cs in rows]


async def fetch(li) -> CardResult | None:
    tms = _tms(li)
    if not tms:
        return None
    where = f"TMS='{tms}'"
    params = {"where": where, "outFields": "*", "f": "json"}
    async with client(timeout=30.0, headers=_UA) as c:
        try:
            cur = (await c.get(_CUR, params=params)).json()
        except Exception:
            return None
        attrs = ((cur.get("features") or [{}])[0].get("attributes")) or {}
        try:
            sh = (await c.get(_SALES, params=params)).json().get("features") or []
        except Exception:
            sh = []

    res = CardResult(source_url=SOURCE_URL, market_value=money(attrs.get("MRKT_VALUE")))
    res.sales = _parse_sales(sh)
    if not res.sales and money(attrs.get("SALE_PRICE")):
        res.sales = [CardSale(
            price=money(attrs.get("SALE_PRICE")),
            sale_date=str(attrs.get("SALE_YEAR") or "") or None,
            book=(str(attrs.get("DBOOK")).strip() or None) if attrs.get("DBOOK") is not None else None,
            page=(str(attrs.get("DPAGE")).strip() or None) if attrs.get("DPAGE") is not None else None,
        )]
    return res if res.has_fill() else None
