"""Alamance County NC assessor card — Spatialest JSON (public, no login, no render).

Same vendor/tenant pattern as Gaston (gaston_nc.py) and Henderson (henderson_nc.py):
Alamance runs the identical Spatialest Laravel SPA at ``property.spatialest.com/nc/
alamance``, just a different tenant slug. Live-verified 2026-10-20 directly against the
host (no fixture guesswork):
  - ``GET /nc/alamance/`` -> 200, sets the ``laravel_session``/``XSRF-TOKEN`` cookies and
    embeds ``<meta name="csrf-token">`` (same priming flow as Gaston/Henderson).
  - The SPA's own bundle (mainapp.js) shows the real search contract is
    ``POST /api/v2/search`` with JSON body ``{"filters": {"term": <value>}, "page": 1,
    "limit": 21}`` -- a GET with ``filters[query]=...`` (Gaston's pattern) is silently
    IGNORED here and always returns the same unfiltered default page, so it must be a
    POST with "term". A single exact match returns ``{"id": <ParcelIdentifier>}``
    directly; terms that match more than one parcel return a ``results`` list whose
    ``display`` rows here carry only ``total_FMV_current``/``parcel_number``/
    ``current_owners`` (no street-address field to disambiguate on, unlike Gaston's
    PHYSSTRADD) -- so, same defensive rule as the siblings, only an exact single-id hit
    is trusted; an ambiguous list is never guessed from.
  - ``ParcelIdentifier`` IS the plain Spatialest ``parcel_number`` (e.g. 100396), but
    board rows carry the COUNTY's own PIN (``li.parcel_id``, e.g. "8844451684" -- this
    matches the card's own ``grouping_parcel_num``/``map_pin`` field, confirmed live),
    which the search's ``term`` resolves correctly by itself -- no separate REID lookup
    (Henderson) or digit-guess fallback (Gaston) needed. The full street address string
    also resolves to a single id when it is the only parcel on that address.
  - ``GET /api/v1/recordcard/{id}`` (JSON, CSRF-protected via X-CSRF-TOKEN) ->
    ``parcel.header.total_FMV_current`` (appraised total) and ``parcel.sections``, a
    nested list-of-lists holding (live-verified on 2 real parcels, one vacant land, one
    improved):
      * dwelling block (improved parcels only): ``finished_area`` ("1,616 sqft"),
        ``year_actually_built``, ``num_of_bedrooms`` (int), ``num_of_bathrooms``
        ("2 Full Bath(s)"), ``num_of_half_baths`` ("0 Half Bath(s)").
      * sales rows: ``date_sold`` ("MM/DD/YYYY"), ``sales_amount`` ("$0"/"$102,000"),
        ``deed_book`` ("4428-0206" -- book-dash-page, one string, unlike Gaston/
        Henderson's separate book/page fields), ``deed_name`` (grantor), ``qualify_code``.

IMPORTANT, and the reason this adapter does NOT also cover Alamance's tax-delinquency
gaps (two_year_delinquent / tax_aging_surfaced / multi_year_delinquent_tax): the
recordcard JSON was read in full on both live test parcels and contains NO tax-bill,
amount-due, paid/unpaid, or delinquent-year field anywhere -- only assessment (land/
improvement FMV), dwelling specs, owner, and sale history. The ``tax_year`` on a sales
row is the REASSESSMENT year tied to that transfer, not a payment-status flag. The SPA
bundle's few "tax"-adjacent strings (``email_annual_tax_bill``, a notification-opt-in
checkbox; ``currenttaxyear``/``historicaltaxyear``, the record-card's own "as of which
assessment year" selector; a ``modria`` config key, an online VALUE-APPEAL tool) confirm
this is the ASSESSOR's card, not the tax COLLECTOR's bill/delinquency system -- Alamance's
real delinquent-tax source is a different, not-yet-identified host. This module only
fills the same two fields its Gaston/Henderson siblings fill: heated/finished living
sqft and recorded sale price/history.

No CAPTCHA / WAF / render needed -- plain httpx GETs/POSTs answer directly.
Defensive: any exception / timeout / no-match -> return None.
"""
from __future__ import annotations

import re

from ..http_client import client
from .base import CardResult, CardSale, money

COUNTY = ("NC", "Alamance")   # auto-discovery key

_BASE = "https://property.spatialest.com/nc/alamance"
_SEARCH = f"{_BASE}/api/v2/search"
_CARD = f"{_BASE}/api/v1/recordcard"
SOURCE_URL = f"{_BASE}/"

_UA = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
    )
}
_CSRF_META = re.compile(
    r'name=["\']csrf-token["\']\s+content=["\']([^"\']+)["\']', re.I
)
_DIGITS_RE = re.compile(r"\D")
_DATE_RE = re.compile(r"(\d{1,2})/(\d{1,2})/(\d{4})")


def _to_float(v) -> float | None:
    if v is None:
        return None
    m = re.search(r"\d+(?:\.\d+)?", str(v).replace(",", ""))
    if not m:
        return None
    try:
        return float(m.group(0))
    except ValueError:
        return None


def _to_int(v) -> int | None:
    f = _to_float(v)
    return int(f) if f is not None else None


def _year(v) -> int | None:
    y = _to_int(v)
    return y if y is not None and 1700 <= y <= 2100 else None


def _deed_date_iso(v) -> str | None:
    """'1/25/1995' -> '1995-01-25'. Drop obvious placeholders (pre-1900)."""
    m = _DATE_RE.search(str(v or ""))
    if not m:
        return None
    mo, da, yr = (int(x) for x in m.groups())
    if yr < 1900:
        return None
    try:
        return f"{yr:04d}-{mo:02d}-{da:02d}"
    except (ValueError, TypeError):
        return None


def _split_book_page(v) -> tuple[str | None, str | None]:
    """'4428-0206' -> ('4428', '0206'). Missing/odd formats -> (whole string, None)."""
    s = (str(v).strip() if v is not None else "")
    if not s:
        return (None, None)
    if "-" in s:
        book, _, page = s.partition("-")
        return (book.strip() or None, page.strip() or None)
    return (s, None)


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
    """GET the SPA root to set the laravel_session cookie; return its csrf token."""
    try:
        r = await c.get(SOURCE_URL)
    except Exception:
        return None
    if r.status_code != 200:
        return None
    m = _CSRF_META.search(r.text)
    return m.group(1) if m else None


async def _search_id(c, headers: dict, term: str) -> str | None:
    """POST a search term; trust ONLY a single exact-match {"id": ...} response
    (an ambiguous `results` list is never guessed from -- see module docstring)."""
    try:
        r = await c.post(
            _SEARCH,
            json={"filters": {"term": term}, "page": 1, "limit": 21},
            headers=headers,
        )
        d = r.json()
    except Exception:
        return None
    if isinstance(d, dict) and d.get("id") is not None:
        return str(d["id"])
    return None


async def _resolve_pid(c, headers: dict, li) -> str | None:
    """Alamance's own PIN (li.parcel_id) resolves directly via search; the full
    street address is the fallback when no PIN is on the row."""
    pin = _DIGITS_RE.sub("", getattr(li, "parcel_id", None) or "")
    if pin:
        pid = await _search_id(c, headers, pin)
        if pid:
            return pid
    addr = (getattr(li, "street_address", None) or "").strip()
    if addr:
        pid = await _search_id(c, headers, addr)
        if pid:
            return pid
    return None


async def _fetch_card(c, headers: dict, pid: str) -> dict | None:
    try:
        r = await c.get(f"{_CARD}/{pid}", headers=headers)
        if r.status_code != 200:
            return None
        data = r.json()
    except Exception:
        return None
    return data if isinstance(data, dict) and data.get("parcel") else None


def parse_card(card: dict) -> CardResult:
    """Pure: card JSON (from /api/v1/recordcard/{id}) -> normalized CardResult.
    Walks parcel.sections defensively rather than relying on fixed indices, same
    approach as henderson_nc.py -- Alamance's own section shape is observed, not
    guaranteed stable across every parcel kind."""
    res = CardResult(source_url=SOURCE_URL)
    parcel = card.get("parcel") or {}
    header = parcel.get("header") or {}
    res.market_value = money(header.get("total_FMV_current"))

    sales: list[CardSale] = []
    for blk in _walk_dicts(parcel.get("sections") or []):
        if "finished_area" in blk or "year_actually_built" in blk:
            if res.living_sqft is None:
                sq = _to_float(blk.get("finished_area"))
                if sq:
                    res.living_sqft = sq
                    res.living_sqft_is_heated = True
            if res.year_built is None:
                res.year_built = _year(blk.get("year_actually_built"))
            if res.bedrooms is None and blk.get("num_of_bedrooms") is not None:
                res.bedrooms = _to_float(blk.get("num_of_bedrooms"))
            if res.bathrooms is None and (
                blk.get("num_of_bathrooms") is not None
                or blk.get("num_of_half_baths") is not None
            ):
                full = _to_float(blk.get("num_of_bathrooms")) or 0.0
                half = _to_float(blk.get("num_of_half_baths")) or 0.0
                baths = full + 0.5 * half
                res.bathrooms = baths or None

        if "date_sold" in blk and "sales_amount" in blk:
            iso = _deed_date_iso(blk.get("date_sold"))
            book, page = _split_book_page(blk.get("deed_book"))
            sales.append(
                CardSale(
                    sale_date=iso,
                    price=money(blk.get("sales_amount")),
                    book=book,
                    page=page,
                    reason=(str(blk["qualify_code"]).strip() or None)
                    if blk.get("qualify_code") else None,
                    grantor=(str(blk["deed_name"]).strip() or None)
                    if blk.get("deed_name") else None,
                )
            )

    sales.sort(key=lambda s: s.sale_date or "", reverse=True)
    res.sales = sales
    return res


async def fetch(li) -> CardResult | None:
    try:
        async with client(timeout=30.0, headers=_UA) as c:
            csrf = await _prime(c)
            if not csrf:
                return None
            headers = {
                "Accept": "application/json",
                "Content-Type": "application/json",
                "X-Requested-With": "XMLHttpRequest",
                "Referer": SOURCE_URL,
                "X-CSRF-TOKEN": csrf,
            }
            pid = await _resolve_pid(c, headers, li)
            if not pid:
                return None
            card = await _fetch_card(c, headers, pid)
            if not card:
                return None
            res = parse_card(card)
            res.source_url = f"{SOURCE_URL}#/property/{pid}"
            return res if res.has_fill() else None
    except Exception:
        return None
