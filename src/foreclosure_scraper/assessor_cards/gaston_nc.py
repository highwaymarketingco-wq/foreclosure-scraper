"""Gaston County NC assessor card — Spatialest JSON (public, no login, no render).

Fills the gap: HEATED/FINISHED living sqft + dwelling specs + appraised market value
(from Spatialest's record-card API) PLUS the recorded transfer/sale history (from the
DevNet Wedge HTML parcel page, which the Spatialest card omits).

Flow (parcel key = Spatialest ParcelIdentifier / "PID", which usually != li.parcel_id):
  1. RESOLVE the PID:
       - if li.parcel_id is already an all-digit Spatialest PID -> use it
       - else search  GET /api/v2/search?filters[query]={ADDRESS|PIN}  and match the
         physical street address (PHYSSTRADD) to li.street_address.
  2. CARD:  GET /api/v1/recordcard/{PID}  (JSON) -> YEARBLT, AREA_GROSS (== heated/
     finished area for residential here), XBEDRM, XBATHS(+XHBATHS), TotalValue.
     This endpoint is CSRF-protected: it needs the laravel_session cookie set by the
     SPA root page AND the matching csrf-token (from the root HTML <meta>) echoed back
     in the X-CSRF-TOKEN header. We fetch the root once to prime both.
  3. SALES:  GET https://gastonnc.devnetwedge.com/parcel/view/{PID}/{YEAR}  (HTML) ->
     "Transfer History" table (Book & Page, Sale Type, Sale Date, Sold By/To, Price).
     The DevNet page is also a fallback for finished area ("Base Living Area").

No CAPTCHA / WAF / render needed — both hosts answer plain httpx GETs.
Defensive: any exception / timeout / no-match -> return None.
"""
from __future__ import annotations

import re
from html import unescape

from ..http_client import client
from .base import CardResult, CardSale, money

COUNTY = ("NC", "Gaston")   # auto-discovery key

_BASE = "https://property.spatialest.com/nc/gaston"
_SEARCH = f"{_BASE}/api/v2/search"
_CARD = f"{_BASE}/api/v1/recordcard"
_DEVNET = "https://gastonnc.devnetwedge.com/parcel/view"
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


def _norm_addr(s: str | None) -> str:
    """Loose street-address key for comparison: upper, drop punctuation, collapse ws."""
    if not s:
        return ""
    return re.sub(r"\s+", " ", re.sub(r"[^A-Z0-9 ]", " ", s.upper())).strip()


def _disp(result: dict, field_id: str) -> str | None:
    for d in result.get("display") or []:
        if d.get("id") == field_id:
            v = d.get("value")
            return str(v) if v not in (None, "") else None
    return None


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


def _section_rows(card: dict, want_keys: set[str]) -> list[dict]:
    """Flatten card['parcel']['sections'] (list of groups of rows) and return the
    leaf dict rows that contain ANY of want_keys."""
    out: list[dict] = []

    def walk(o):
        if isinstance(o, dict):
            if any(k in o for k in want_keys):
                out.append(o)
            else:
                for v in o.values():
                    walk(v)
        elif isinstance(o, list):
            for v in o:
                walk(v)

    walk((card.get("parcel") or {}).get("sections") or [])
    return out


async def _prime(c) -> str | None:
    """GET the SPA root to set the laravel_session cookie; return its csrf token."""
    r = await c.get(SOURCE_URL)
    if r.status_code != 200:
        return None
    m = _CSRF_META.search(r.text)
    return m.group(1) if m else None


async def _resolve_pid(c, li) -> str | None:
    """Spatialest ParcelIdentifier. Try li.parcel_id if all-digits, else address search."""
    pid_guess = re.sub(r"\D", "", li.parcel_id or "")
    # Address-based search is the reliable path; PIN search also works as a query.
    queries = []
    if li.street_address:
        queries.append(li.street_address)
    if li.parcel_id:
        queries.append(li.parcel_id)
    target = _norm_addr(li.street_address)

    for q in queries:
        try:
            r = await c.get(_SEARCH, params={"filters[query]": q})
            results = (r.json() or {}).get("results") or []
        except Exception:
            continue
        if not results:
            continue
        # Exact street-address match wins.
        if target:
            for res in results:
                if _norm_addr(_disp(res, "PHYSSTRADD")) == target:
                    pid = res.get("ParcelIdentifier") or _disp(res, "PID")
                    if pid is not None:
                        return str(pid)
        # PIN/PID query: if our digit-guess is present, take it.
        if pid_guess:
            for res in results:
                rid = str(res.get("ParcelIdentifier") or _disp(res, "PID") or "")
                if rid == pid_guess:
                    return rid

    # Last resort: a bare all-digit parcel_id may itself be the Spatialest PID.
    return pid_guess or None


async def _fetch_card(c, csrf: str | None, pid: str) -> dict | None:
    headers = {
        "Accept": "application/json",
        "Referer": SOURCE_URL,
        "X-Requested-With": "XMLHttpRequest",
    }
    if csrf:
        headers["X-CSRF-TOKEN"] = csrf
    try:
        r = await c.get(f"{_CARD}/{pid}", headers=headers)
        if r.status_code != 200:
            return None
        data = r.json()
    except Exception:
        return None
    return data if isinstance(data, dict) and data.get("parcel") else None


_ROW_RE = re.compile(r"<tr\b[^>]*>(.*?)</tr>", re.I | re.S)
_CELL_RE = re.compile(r"<t[dh]\b[^>]*>(.*?)</t[dh]>", re.I | re.S)
_TAG_RE = re.compile(r"<[^>]+>")


def _cell_text(html: str) -> str:
    return unescape(re.sub(r"\s+", " ", _TAG_RE.sub(" ", html))).strip()


def _parse_devnet_sales(html: str) -> list[CardSale]:
    """Parse the DevNet 'Transfer History' table -> newest-first CardSale list.
    Columns: Book & Page | Sale Type | Sale Date | Sold By | Sold To | Price."""
    i = html.find('id="SalesHistory2"')
    if i < 0:
        i = html.find("Transfer History")
    if i < 0:
        return []
    seg = html[i : i + 8000]
    sales: list[CardSale] = []
    for rm in _ROW_RE.finditer(seg):
        cells = [_cell_text(c) for c in _CELL_RE.findall(rm.group(1))]
        if len(cells) < 6:
            continue
        bookpage, stype, sdate, sold_by, sold_to, price = cells[:6]
        # Skip the header row.
        if "book" in bookpage.lower() and "page" in bookpage.lower():
            continue
        book = page = None
        bp = bookpage.split()
        if len(bp) >= 2:
            book, page = bp[0], bp[1]
        elif len(bp) == 1 and bp[0]:
            book = bp[0]
        iso = _devnet_date(sdate)
        if not (iso or money(price) or book):
            continue
        sales.append(
            CardSale(
                sale_date=iso,
                price=money(price),
                book=book or None,
                page=page or None,
                reason=(stype or None),
                grantor=(sold_by or None),
                grantee=(sold_to or None),
            )
        )
    # DevNet lists newest-first already; enforce it by parsed date when available.
    sales.sort(key=lambda s: s.sale_date or "", reverse=True)
    return sales


def _devnet_date(s: str) -> str | None:
    """'1/25/1995' -> '1995-01-25'. Drop obvious placeholders (1/1/1899)."""
    m = re.match(r"\s*(\d{1,2})/(\d{1,2})/(\d{4})\s*$", s or "")
    if not m:
        return None
    mo, da, yr = (int(x) for x in m.groups())
    if yr < 1900:
        return None
    try:
        return f"{yr:04d}-{mo:02d}-{da:02d}"
    except (ValueError, TypeError):
        return None


def _devnet_finished_area(html: str) -> float | None:
    """Fallback heated sqft from DevNet ('Total Finished Area' table or
    'Base Living Area' row)."""
    m = re.search(r"Base Living Area.*?([\d,]+)\s*Square Ft", html, re.I | re.S)
    if m:
        return _to_float(m.group(1))
    m = re.search(r"Total Finished Area.*?</thead>(.*?)</table>", html, re.I | re.S)
    if m:
        nums = re.findall(r">\s*([\d,]{3,})\s*<", m.group(1))
        if nums:
            return _to_float(nums[0])
    return None


async def fetch(li) -> CardResult | None:
    try:
        async with client(timeout=30.0, headers=_UA) as c:
            csrf = await _prime(c)
            pid = await _resolve_pid(c, li)
            if not pid:
                return None

            card = await _fetch_card(c, csrf, pid)

            res = CardResult(source_url=f"{SOURCE_URL}#/property/{pid}")
            year = None
            if card:
                hdr = ((card.get("parcel") or {}).get("header")) or {}
                res.market_value = money(hdr.get("TotalValue"))
                dwell = _section_rows(card, {"AREA_GROSS", "YEARBLT", "XBEDRM"})
                if dwell:
                    d0 = dwell[0]
                    # AREA_GROSS on the residential card == heated/finished area.
                    res.living_sqft = _to_float(d0.get("AREA_GROSS"))
                    if res.living_sqft:
                        res.living_sqft_is_heated = True
                    year = _to_int(d0.get("YEARBLT"))
                    res.year_built = year
                    res.bedrooms = _to_float(d0.get("XBEDRM"))
                    full = _to_float(d0.get("XBATHS")) or 0.0
                    half = _to_float(d0.get("XHBATHS")) or 0.0
                    baths = full + 0.5 * half
                    res.bathrooms = baths or None

            # Sales (and area fallback) from DevNet HTML. Try a couple of years.
            devnet_years = []
            if year:
                devnet_years.append(year if year >= 2000 else 2025)
            devnet_years += [2025, 2024]
            seen: set[int] = set()
            for yr in devnet_years:
                if yr in seen:
                    continue
                seen.add(yr)
                try:
                    r = await c.get(f"{_DEVNET}/{pid}/{yr}", headers=_UA)
                except Exception:
                    continue
                if r.status_code != 200 or "Transfer History" not in r.text:
                    continue
                res.sales = _parse_devnet_sales(r.text)
                if res.living_sqft is None:
                    fa = _devnet_finished_area(r.text)
                    if fa:
                        res.living_sqft = fa
                        res.living_sqft_is_heated = True
                break

            return res if res.has_fill() else None
    except Exception:
        return None
