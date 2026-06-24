"""Henderson County NC assessor card — Spatialest Laravel API (public, no login).

Fills both NC gaps the bulk parcel feed omits: HEATED/finished living sqft and the
recorded SALE PRICE + sale history (+ appraised total / year built / baths).

Reachable via plain httpx (no StealthyFetcher render needed) once the Laravel
session is primed:
  1. GET the SPA root ``…/nc/henderson/`` -> sets XSRF-TOKEN + laravel_session
     cookies (shared on the httpx client) and embeds a <meta name="csrf-token">.
  2. Every API call then sends that meta token as the ``X-CSRF-TOKEN`` header
     (Laravel returns 419 "session could not be verified" without it).

Resolve the county's internal id (REID) — which is NOT li.parcel_id (a PIN):
  POST …/api/v1?  no — POST ``api/v2/search`` with
  ``{"filters": {"term": <PIN | REID | street address>}, "page": 1, "limit": 21}``
  -> a single exact match returns ``{"id": <REID>}``; multiple returns
  ``{"results": [...]}`` where each row carries ``order_parcel_REID`` /
  ``ParcelIdentifier`` and a ``display`` list with ``LOCATION_ADDR``.

Card JSON:  GET ``api/v1/recordcard/{REID}``  ->  ``parcel.sections`` is a deeply
nested list-of-lists; the building block holds HEATED_AREA / YEAR_BUILT / BLDG_VALUE
/ BATH_FULL / BATH_HALF, and the sales block holds rows of
SALE_PRICE / DEED_DATE / DEED_TYPE / BOOK / PAGE / STAMPS. We walk the tree
defensively rather than relying on fixed indices.
"""
from __future__ import annotations

import re

from ..http_client import client
from .base import CardResult, CardSale, money

COUNTY = ("NC", "Henderson")

_BASE = "https://property.spatialest.com/nc/henderson"
SOURCE_URL = f"{_BASE}/"
_UA = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36",
}
_CSRF_RE = re.compile(r'name="csrf-token"\s+content="([^"]+)"')
_DATE_RE = re.compile(r"(\d{1,2})/(\d{1,2})/(\d{4})")
_DIGITS_RE = re.compile(r"\D")


def _sqft(v) -> float | None:
    """'1,158 SqFt' -> 1158.0"""
    if v is None:
        return None
    m = re.search(r"[\d,]+(?:\.\d+)?", str(v))
    if not m:
        return None
    try:
        f = float(m.group(0).replace(",", ""))
    except ValueError:
        return None
    return f if f > 0 else None


def _year(v) -> int | None:
    try:
        y = int(str(v).strip())
    except (TypeError, ValueError):
        return None
    return y if 1700 <= y <= 2100 else None


def _deed_date_iso(v) -> str | None:
    """'07/30/2009' -> '2009-07-30'."""
    if not v:
        return None
    m = _DATE_RE.search(str(v))
    if not m:
        return None
    mm, dd, yyyy = m.groups()
    return f"{yyyy}-{int(mm):02d}-{int(dd):02d}"


def _norm_addr(s: str | None) -> str:
    return re.sub(r"\s+", " ", (s or "").upper()).strip()


def _walk_dicts(obj):
    """Yield every dict found anywhere inside a nested list/dict tree."""
    if isinstance(obj, dict):
        yield obj
        for v in obj.values():
            yield from _walk_dicts(v)
    elif isinstance(obj, list):
        for v in obj:
            yield from _walk_dicts(v)


async def _prime(c) -> str | None:
    """Load SPA root for cookies + return the meta csrf-token, or None."""
    try:
        root = await c.get(SOURCE_URL)
    except Exception:
        return None
    if root.status_code != 200:
        return None
    m = _CSRF_RE.search(root.text)
    return m.group(1) if m else None


async def _resolve_reid(c, headers: dict, li) -> str | None:
    """Map li -> county REID. Try PIN/parcel_id first, then street address."""
    terms: list[str] = []
    pid = (getattr(li, "parcel_id", None) or "").strip()
    if pid:
        terms.append(pid)
        digits = _DIGITS_RE.sub("", pid)
        if digits and digits != pid:
            terms.append(digits)
    addr = (getattr(li, "street_address", None) or "").strip()
    if addr:
        terms.append(addr)

    want = _norm_addr(addr)
    for term in terms:
        if not term:
            continue
        body = {"filters": {"term": term}, "page": 1, "limit": 21}
        try:
            r = await c.post(f"{_BASE}/api/v2/search", json=body, headers=headers)
            d = r.json()
        except Exception:
            continue
        if not isinstance(d, dict):
            continue
        # Single exact match: API returns {"id": <REID>}
        if d.get("id"):
            return str(d["id"])
        # A multi-row ``results`` list is only trustworthy when one row's
        # LOCATION_ADDR matches our subject address. The API returns a generic
        # unfiltered list (not real matches) for terms it doesn't recognize, so
        # we never blind-pick results[0] — that would attach the wrong parcel.
        if not want:
            continue
        for row in d.get("results") or d.get("searchResults") or []:
            for f in row.get("display") or []:
                if f.get("id") == "LOCATION_ADDR" and want in _norm_addr(f.get("value")):
                    rid = row.get("order_parcel_REID") or row.get("ParcelIdentifier")
                    if rid is not None:
                        return str(rid)
    return None


def _parse_card(d: dict) -> CardResult:
    res = CardResult(source_url=SOURCE_URL)

    parcel = d.get("parcel") or {}
    header = parcel.get("header") or {}
    res.market_value = money(header.get("TOTAL_PROP_VALUE"))

    sales_seen: dict[tuple, tuple[str | None, CardSale]] = {}
    for blk in _walk_dicts(parcel):
        # Building block: heated area / year built / baths / bldg value.
        if "HEATED_AREA" in blk or "YEAR_BUILT" in blk:
            sq = _sqft(blk.get("HEATED_AREA"))
            if sq and not res.living_sqft:
                res.living_sqft = sq
                res.living_sqft_is_heated = True
            yb = _year(blk.get("YEAR_BUILT"))
            if yb and not res.year_built:
                res.year_built = yb
            full = blk.get("BATH_FULL")
            half = blk.get("BATH_HALF")
            if res.bathrooms is None and (full is not None or half is not None):
                try:
                    res.bathrooms = float(full or 0) + 0.5 * float(half or 0) or None
                except (TypeError, ValueError):
                    pass
            mv = money(blk.get("BLDG_VALUE"))
            if mv and not res.market_value:
                res.market_value = mv

        # Sales row: {"row": {SALE_PRICE, DEED_DATE, ...}, "subdata": {OWNER_NAME}}
        row = blk.get("row") if isinstance(blk.get("row"), dict) else None
        if row and ("SALE_PRICE" in row or "DEED_DATE" in row) and ("BOOK" in row or "DEED_TYPE" in row):
            sub = blk.get("subdata") or {}
            iso = _deed_date_iso(row.get("DEED_DATE"))
            cs = CardSale(
                sale_date=iso or (str(row.get("DEED_DATE")).strip() or None),
                price=money(row.get("SALE_PRICE")),
                book=(str(row.get("BOOK")).strip() or None) if row.get("BOOK") is not None else None,
                page=(str(row.get("PAGE")).strip() or None) if row.get("PAGE") is not None else None,
                reason=(str(row.get("DEED_TYPE")).strip() or None) if row.get("DEED_TYPE") else None,
                grantor=(str(sub.get("OWNER_NAME")).strip() or None) if sub.get("OWNER_NAME") else None,
            )
            key = (cs.book, cs.page, cs.sale_date, cs.price)
            if key not in sales_seen:
                sales_seen[key] = (iso, cs)

    # Newest-first by ISO deed date (None sorts last).
    res.sales = [cs for _, cs in sorted(
        sales_seen.values(), key=lambda t: t[0] or "", reverse=True
    )]
    return res


async def fetch(li) -> CardResult | None:
    try:
        async with client(timeout=30.0, headers=_UA) as c:
            csrf = await _prime(c)
            if not csrf:
                return None
            headers = {
                "Accept": "application/json, text/plain, */*",
                "X-Requested-With": "XMLHttpRequest",
                "Referer": SOURCE_URL,
                "X-CSRF-TOKEN": csrf,
            }
            reid = await _resolve_reid(c, headers, li)
            if not reid:
                return None
            try:
                r = await c.get(f"{_BASE}/api/v1/recordcard/{reid}", headers=headers)
                d = r.json()
            except Exception:
                return None
            if not isinstance(d, dict) or not d.get("parcel"):
                return None
            res = _parse_card(d)
            return res if res.has_fill() else None
    except Exception:
        return None
