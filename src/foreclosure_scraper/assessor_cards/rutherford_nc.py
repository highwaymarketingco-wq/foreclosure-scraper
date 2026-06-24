"""Rutherford County NC assessor card — NCPTS Cloud public JSON API (no login, no WAF).

Fills heated/finished living sqft + recorded SALE PRICE + sale history + appraised value
from the county's public parcel portal (lrcpwa.ncptscloud.com, a Farragut/NCPTS SPA).

Two JSON endpoints, both require the `X-Tenant: Rutherford` header (a bare call 500s):
  GET  /api/SimpleParcelSearch?query={pin|address}&pageIndex=0&pageSize=...
       -> {"totalCount", "results":[{"id": <internal ParcelId>, "formattedPin", ...}]}
  GET  /api/getParcelDetails?ParcelId={internalId}
       -> heatedArea (+ buildings[0].heatedArea), yearBuilt, bedrooms, bathFull/bathHalf,
          totalPropertyValue (appraised total), packageSalePrice/packageSaleDate,
          deedBook/deedPage, deeds[] (full sale history)

KEY RESOLUTION: the portal key is the internal `ParcelId` (parcelPk, e.g. 4591) — NOT the
PIN (1578-86-4464) nor the REID (324731). We resolve it via SimpleParcelSearch: try
li.parcel_id (works for formatted "1578-86-4464" or bare "1578864464"), else street address.
If li.parcel_id already looks like the small internal integer key, we use it directly.
"""
from __future__ import annotations

import re

from ..http_client import client
from .base import CardResult, CardSale, money

_BASE = "https://lrcpwa.ncptscloud.com"
_SEARCH = f"{_BASE}/api/SimpleParcelSearch"
_DETAILS = f"{_BASE}/api/getParcelDetails"
SOURCE_URL = f"{_BASE}/"
_HDRS = {
    "X-Tenant": "Rutherford",
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36",
    "Accept": "application/json, text/plain, */*",
}

COUNTY = ("NC", "Rutherford")   # auto-discovery key


def _to_int(v) -> int | None:
    try:
        i = int(float(v))
        return i if i > 0 else None
    except (TypeError, ValueError):
        return None


def _iso_date(v) -> str | None:
    """NCPTS dates look like '2017-10-31T14:03:00' -> 'YYYY-MM-DD'."""
    if not v:
        return None
    m = re.match(r"(\d{4}-\d{2}-\d{2})", str(v))
    return m.group(1) if m else None


def _clean(v) -> str | None:
    if v is None:
        return None
    s = str(v).strip()
    return s or None


async def _resolve_parcel_key(c, li) -> str | None:
    """Return the internal NCPTS ParcelId (the `id` field from SimpleParcelSearch)."""
    pid = (li.parcel_id or "").strip()

    # A short bare integer is likely already the internal key — try it as-is first.
    if pid and pid.isdigit() and len(pid) <= 6:
        return pid

    # Search candidates in priority order: PIN as-given, bare-digit PIN, street address.
    # Only treat a value as a PIN if it's PIN-shaped (digits/dashes/dots/spaces) — an
    # alphanumeric junk string must NOT be reduced to a digit fragment that happens to
    # collide with a real internal key.
    candidates: list[str] = []
    if pid and re.fullmatch(r"[\d.\-\s]+", pid):
        candidates.append(pid)
        digits = re.sub(r"\D", "", pid)
        if digits and digits != pid:
            candidates.append(digits)
    addr = _clean(getattr(li, "street_address", None))
    if addr:
        candidates.append(addr)

    for q in candidates:
        try:
            r = await c.get(
                _SEARCH,
                params={"query": q, "pageIndex": 0, "pageSize": 25},
            )
            rows = (r.json() or {}).get("results") or []
        except Exception:
            continue
        if not rows:
            continue
        # Single hit -> trust it. Multiple -> prefer an exact street match if we have one.
        if len(rows) == 1:
            key = _clean(rows[0].get("id"))
            if key:
                return key
        if addr:
            want = addr.upper()
            for row in rows:
                if (row.get("propertyAddress1") or "").strip().upper() == want:
                    key = _clean(row.get("id"))
                    if key:
                        return key
        # Fall back to the first result for a PIN query (PINs are unique).
        key = _clean(rows[0].get("id"))
        if key:
            return key
    return None


def _parse_sales(d: dict) -> list[CardSale]:
    """Build a newest-first sale list from deeds[], enriched by package* fields."""
    rows: list[tuple[str, CardSale]] = []
    for dd in d.get("deeds") or []:
        sale_date = _iso_date(dd.get("deedDate"))
        rows.append((sale_date or "", CardSale(
            sale_date=sale_date,
            price=money(dd.get("salePrice")),
            book=_clean(dd.get("book")),
            page=_clean(dd.get("page")),
            reason=_clean(dd.get("deedType")),
            grantor=_clean(dd.get("ownerName")),
        )))
    rows.sort(key=lambda r: r[0], reverse=True)   # newest-first by ISO date
    sales = [cs for _, cs in rows]

    # If deeds[] carried no usable price, fall back to the package-sale summary fields.
    pkg_price = money(d.get("packageSalePrice"))
    if pkg_price and not any(s.price for s in sales):
        sales.insert(0, CardSale(
            sale_date=_iso_date(d.get("packageSaleDate")),
            price=pkg_price,
            book=_clean(d.get("deedBook")),
            page=_clean(d.get("deedPage")),
        ))
    return sales


async def fetch(li) -> CardResult | None:
    async with client(timeout=30.0, headers=_HDRS) as c:
        try:
            key = await _resolve_parcel_key(c, li)
            if not key:
                return None
            r = await c.get(_DETAILS, params={"ParcelId": key})
            d = r.json()
        except Exception:
            return None

    if not isinstance(d, dict):
        return None

    bldg = (d.get("buildings") or [{}])[0] or {}

    # Heated/finished area: prefer the top-level heatedArea, else the building's.
    living = _to_int(d.get("heatedArea")) or _to_int(bldg.get("heatedArea"))

    # Bathrooms = full + 0.5 * half (NCPTS exposes bathFull / bathHalf on the building).
    full = _to_int(bldg.get("bathFull"))
    half = _to_int(bldg.get("bathHalf"))
    baths = None
    if full is not None or half is not None:
        baths = float(full or 0) + 0.5 * float(half or 0)
        baths = baths or None

    res = CardResult(
        source_url=SOURCE_URL,
        living_sqft=float(living) if living else None,
        living_sqft_is_heated=bool(living),
        year_built=_to_int(bldg.get("yearBuilt")),
        bedrooms=_to_int(bldg.get("bedrooms")),
        bathrooms=baths,
        market_value=money(d.get("totalPropertyValue")),
    )
    res.sales = _parse_sales(d)
    return res if res.has_fill() else None
