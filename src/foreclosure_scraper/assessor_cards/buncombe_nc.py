"""Buncombe County NC assessor card — Spatialest record-card JSON (headless render).

Fills the gap: HEATED/FINISHED living sqft + dwelling specs + appraised total
PLUS the recorded transfer/sale history, all from the Spatialest record-card API.

Flow (parcel key = Spatialest 15-digit PIN == the county GIS `pinnum`):
  1. RESOLVE the PIN:
       - if li.parcel_id is already a 15-digit (or 10-digit) Spatialest PIN -> use it
       - else query the county ArcGIS `bcmap_vt/MapServer/0` (Property) layer by
         li.parcel_id (pinnum / pin) or street address; that layer carries `pinnum`
         and a `propcard` link (https://prc-buncombe.spatialest.com/#/property/{PIN}).
  2. CARD:  GET https://prc-buncombe.spatialest.com/api/v1/recordcard/{PIN} (JSON) ->
       header.Total (appraised total), building rows (TotalFinishedArea == heated/
       finished area, YearBuilt, Bedrooms, FullBath/HalfBath), and a transfer-history
       block of {saledate, saleprice, salesvalidity, book, page, DeedInstrument}.

  The /api/v1/recordcard endpoint is WALLED to direct httpx (403 "Direct API access
  is not permitted", and a primed-cookie call still 419s on Laravel CSRF). So we use
  the project StealthyFetcher render path: load the SPA, navigate to the parcel deep
  link, and capture the card JSON off the SPA's own authenticated XHR. The county
  ArcGIS layer answers plain httpx, so PIN resolution stays cheap.

Defensive: any exception / timeout / no-match / no-render -> return None (never raise).
"""
from __future__ import annotations

import json
import re

from ..http_client import client
from .base import CardResult, CardSale, money

COUNTY = ("NC", "Buncombe")   # auto-discovery key

_SPATIALEST = "https://prc-buncombe.spatialest.com"
_CARD = f"{_SPATIALEST}/api/v1/recordcard"
_GIS = ("https://gis.buncombecounty.org/arcgis/rest/services/"
        "bcmap_vt/MapServer/0/query")
SOURCE_URL = f"{_SPATIALEST}/"

_UA = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json, text/plain, */*",
}
# A Spatialest/GIS PIN is the 15-digit pinnum (10-digit pin + 5-digit ext).
_PIN_FROM_PROPCARD = re.compile(r"/property/(\d{6,})")


def _to_int(v) -> int | None:
    if v is None:
        return None
    m = re.search(r"\d+", str(v).replace(",", ""))
    if not m:
        return None
    try:
        return int(m.group(0))
    except ValueError:
        return None


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


def _clean(v) -> str | None:
    if v is None:
        return None
    s = str(v).strip()
    return s or None


def _esc(v: str) -> str:
    return v.replace("'", "''")


def _saledate_iso(v) -> str | None:
    """'MM/DD/YYYY' -> 'YYYY-MM-DD'; fall back to a bare year. Drop pre-1900 placeholders."""
    if not v:
        return None
    s = str(v).strip()
    m = re.match(r"^(\d{1,2})/(\d{1,2})/(\d{4})$", s)
    if m:
        mo, da, yr = m.groups()
        if int(yr) < 1900:
            return None
        return f"{yr}-{int(mo):02d}-{int(da):02d}"
    m = re.search(r"(19|20)\d{2}", s)
    return m.group(0) if m else None


# --- PIN resolution via county ArcGIS (plain httpx) -------------------------

def _pin_candidate(li) -> str | None:
    """If li.parcel_id already looks like a Spatialest/GIS PIN, return its digits."""
    digits = re.sub(r"\D", "", getattr(li, "parcel_id", "") or "")
    return digits if len(digits) in (10, 15) else None


async def _gis_query(c, where: str) -> list[dict]:
    params = {
        "where": where,
        "outFields": "pinnum,pin,propcard,Address,HouseNumber,streetname",
        "returnGeometry": "false",
        "f": "json",
        "resultRecordCount": 10,
    }
    try:
        data = (await c.get(_GIS, params=params, headers=_UA)).json()
    except Exception:
        return []
    if not isinstance(data, dict) or data.get("error"):
        return []
    return [f.get("attributes") or {} for f in (data.get("features") or [])]


def _pin_from_attrs(a: dict) -> str | None:
    pinnum = _clean(a.get("pinnum"))
    if pinnum and pinnum.isdigit():
        return pinnum
    m = _PIN_FROM_PROPCARD.search(a.get("propcard") or "")
    return m.group(1) if m else None


async def _resolve_pin(c, li) -> str | None:
    """Return the 15-digit Spatialest PIN (county GIS `pinnum`)."""
    # 1) parcel_id already a PIN.
    cand = _pin_candidate(li)
    if cand:
        if len(cand) == 15:
            return cand
        # 10-digit pin -> resolve to the 15-digit pinnum via GIS.
        rows = await _gis_query(c, f"pin='{_esc(cand)}'")
        if rows:
            pin = _pin_from_attrs(rows[0])
            if pin:
                return pin
        return cand  # last resort

    # 2) parcel_id is some other identifier — try it against pinnum/pin literally.
    raw = _clean(getattr(li, "parcel_id", None))
    if raw and re.fullmatch(r"[\d.\-\s]+", raw):
        digits = re.sub(r"\D", "", raw)
        if digits:
            rows = await _gis_query(c, f"pinnum='{_esc(digits)}' OR pin='{_esc(digits)}'")
            if rows:
                pin = _pin_from_attrs(rows[0])
                if pin:
                    return pin

    # 3) Address search. Try the GIS `Address` field, then a HouseNumber+streetname split.
    addr = _clean(getattr(li, "street_address", None))
    if not addr:
        return None
    rows = await _gis_query(c, f"UPPER(Address) LIKE UPPER('%{_esc(addr)}%')")
    if not rows:
        m = re.match(r"^\s*(\d+)\s+(.*)$", addr)
        if m:
            num, rest = m.group(1), m.group(2).strip()
            street = re.split(r"\b(ST|AVE|RD|DR|LN|CT|BLVD|HWY|WAY|PL|CIR|TER)\b",
                              rest.upper(), maxsplit=1)[0].strip() or rest
            rows = await _gis_query(
                c, f"HouseNumber='{_esc(num)}' AND UPPER(streetname) LIKE UPPER('%{_esc(street)}%')")
    if rows:
        pin = _pin_from_attrs(rows[0])
        if pin:
            return pin
    return None


# --- record-card render -----------------------------------------------------

async def _render_card(pin: str) -> dict | None:
    """Render the Spatialest SPA, navigate to the parcel deep-link, and capture the
    record-card JSON off the SPA's own (session-authenticated) XHR."""
    try:
        from scrapling.fetchers import StealthyFetcher
    except ImportError:
        return None

    holder: dict = {"body": None}

    async def page_action(page):
        async def on_resp(resp):
            try:
                if "recordcard" in resp.url and resp.status == 200 and holder["body"] is None:
                    holder["body"] = await resp.text()
            except Exception:
                pass

        page.on("response", on_resp)
        try:
            await page.goto(
                f"{_SPATIALEST}/#/property/{pin}",
                wait_until="networkidle", timeout=40000,
            )
        except Exception:
            pass
        await page.wait_for_timeout(6000)

    try:
        from .base import cf_solving_disabled
        await StealthyFetcher.async_fetch(
            SOURCE_URL, headless=True, network_idle=True, timeout=120000,
            page_action=page_action, solve_cloudflare=not cf_solving_disabled(),
        )
    except Exception:
        return None

    body = holder.get("body")
    if not body:
        return None
    try:
        data = json.loads(body)
    except Exception:
        return None
    return data if isinstance(data, dict) and data.get("parcel") else None


def _iter_dict_rows(o):
    """Yield every leaf dict in the heterogeneous parcel['sections'] tree."""
    if isinstance(o, dict):
        yield o
        for v in o.values():
            yield from _iter_dict_rows(v)
    elif isinstance(o, list):
        for v in o:
            yield from _iter_dict_rows(v)


def _parse_building(sections) -> dict:
    for row in _iter_dict_rows(sections):
        if "TotalFinishedArea" in row or "YearBuilt" in row:
            return row
    return {}


def _parse_sales(sections) -> list[CardSale]:
    rows: list[tuple[str, CardSale]] = []
    for row in _iter_dict_rows(sections):
        if "saleprice" not in row and "saledate" not in row:
            continue
        sale_date = _saledate_iso(row.get("saledate"))
        # `order_0` carries a sortable 'YYYY-MM-DD ...' timestamp; prefer it for ordering.
        order = _clean(row.get("order_0")) or sale_date or ""
        rows.append((order, CardSale(
            sale_date=sale_date,
            price=money(row.get("saleprice")),
            book=_clean(row.get("book")),
            page=_clean(row.get("page")),
            reason=_clean(row.get("salesvalidity")) or _clean(row.get("DeedInstrument")),
        )))
    rows.sort(key=lambda r: r[0], reverse=True)   # newest-first
    return [cs for _, cs in rows]


async def fetch(li) -> CardResult | None:
    try:
        async with client(timeout=30.0, headers=_UA) as c:
            pin = await _resolve_pin(c, li)
        if not pin:
            return None

        card = await _render_card(pin)
        if not card:
            return None

        parcel = card.get("parcel") or {}
        hdr = parcel.get("header") or {}
        sections = parcel.get("sections") or []

        res = CardResult(
            source_url=f"{SOURCE_URL}#/property/{pin}",
            market_value=money(hdr.get("Total")),
        )

        bldg = _parse_building(sections)
        if bldg:
            res.living_sqft = _to_float(bldg.get("TotalFinishedArea"))
            if res.living_sqft:
                res.living_sqft_is_heated = True   # TotalFinishedArea == heated/finished
            res.year_built = _to_int(bldg.get("YearBuilt"))
            res.bedrooms = _to_float(bldg.get("Bedrooms"))
            full = _to_float(bldg.get("FullBath")) or 0.0
            half = _to_float(bldg.get("HalfBath")) or 0.0
            res.bathrooms = (full + 0.5 * half) or None

        res.sales = _parse_sales(sections)
        return res if res.has_fill() else None
    except Exception:
        return None
