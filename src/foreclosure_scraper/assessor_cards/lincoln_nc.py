"""Lincoln County NC assessor card — county ArcGIS REST (public, no login, no render).

Fills heated sqft + recorded sale price + appraised total from the Reval parcel
layer. This is a single-row-per-parcel layer (current owner / most-recent recorded
sale only), so there is at most one CardSale per parcel.

Endpoint, keyed by PIN (10-digit, li.parcel_id digits):
  RevalLayers/MapServer/24  -> SALEPRICE, MAINAREASQFT (heated), SDATE (MM/DD/YYYY),
                               DEEDBK, DEEDPG, DEEDYR, NAME1, PHYSICALADDR,
                               TOTALVALUE (appraised), QUALIFIEDCODE (qualification)

The layer has no year_built / bedrooms / bathrooms fields, so those stay None.
"""
from __future__ import annotations

import re

from ..http_client import client
from .base import CardResult, CardSale, money

_QUERY = ("https://arcgisserver.lincolncountync.gov/arcgis/rest/services/"
          "RevalLayers/MapServer/24/query")
SOURCE_URL = "https://arcgisserver.lincolncountync.gov/arcgis/rest/services/RevalLayers/MapServer/24"
_UA = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) Chrome/126"}

COUNTY = ("NC", "Lincoln")   # auto-discovery key (see enrichment_assessor_card._adapters)


def _pin(li) -> str | None:
    """Lincoln PINs are 10 digits; pull them out of li.parcel_id."""
    digits = re.sub(r"\D", "", getattr(li, "parcel_id", "") or "")
    return digits or None


def _esc(v: str) -> str:
    return v.replace("'", "''")


def _sdate_to_iso(v) -> str | None:
    """'MM/DD/YYYY' -> 'YYYY-MM-DD'; fall back to a bare year if only that parses."""
    if not v:
        return None
    s = str(v).strip()
    m = re.match(r"^(\d{1,2})/(\d{1,2})/(\d{4})$", s)
    if m:
        mo, da, yr = m.groups()
        return f"{yr}-{int(mo):02d}-{int(da):02d}"
    m = re.search(r"(19|20)\d{2}", s)
    return m.group(0) if m else None


async def _query(c, where: str) -> list[dict]:
    params = {"where": where, "outFields": "*", "f": "json"}
    try:
        data = (await c.get(_QUERY, params=params)).json()
    except Exception:
        return []
    if not isinstance(data, dict) or data.get("error"):
        return []
    return data.get("features") or []


async def fetch(li) -> CardResult | None:
    try:
        async with client(timeout=30.0, headers=_UA) as c:
            feats: list[dict] = []

            # 1) Resolve by PIN (the county's internal key).
            pin = _pin(li)
            if pin:
                feats = await _query(c, f"PIN='{_esc(pin)}'")

            # 2) Fallback: search by physical address.
            if not feats:
                addr = (getattr(li, "street_address", "") or "").strip()
                if addr:
                    feats = await _query(
                        c, f"UPPER(PHYSICALADDR) LIKE UPPER('%{_esc(addr)}%')"
                    )

            if not feats:
                return None
            attrs = (feats[0].get("attributes")) or {}

            sqft = money(attrs.get("MAINAREASQFT"))
            res = CardResult(
                source_url=SOURCE_URL,
                living_sqft=sqft,
                living_sqft_is_heated=bool(sqft),  # MAINAREASQFT = heated/main area
                market_value=money(attrs.get("TOTALVALUE")),
            )

            price = money(attrs.get("SALEPRICE"))
            if price:
                res.sales = [CardSale(
                    sale_date=(_sdate_to_iso(attrs.get("SDATE"))
                               or (str(attrs.get("DEEDYR")) if attrs.get("DEEDYR") else None)),
                    price=price,
                    book=(str(attrs.get("DEEDBK")).strip() or None)
                         if attrs.get("DEEDBK") not in (None, "") else None,
                    page=(str(attrs.get("DEEDPG")).strip() or None)
                         if attrs.get("DEEDPG") not in (None, "") else None,
                    reason=(str(attrs.get("QUALIFIEDCODE")).strip() or None)
                           if attrs.get("QUALIFIEDCODE") not in (None, "") else None,
                    grantor=(str(attrs.get("NAME1")).strip() or None)
                            if attrs.get("NAME1") not in (None, "") else None,
                )]

            return res if res.has_fill() else None
    except Exception:
        return None
