"""Cherokee County SC assessor card — qPublic / Schneider (Spatialest) server-rendered HTML.

Cherokee's qPublic report page is plain SERVER-RENDERED HTML (not the Spatialest
SPA), so it is fetchable WITHOUT a browser using curl_cffi's chrome impersonation
(the TLS/JA3 fingerprint is what gets a bare httpx GET 403'd, not a real
Cloudflare challenge or the "Agree" disclaimer — both of those only appear in
inert JS/boilerplate on this page). If curl_cffi is unavailable or both it and a
full-UA httpx GET are blocked, we fall back to the project's StealthyFetcher
render path (auto-handles Cloudflare + the Agree click).

Card, keyed by the dashed TMS/parcel (e.g. 027-00-00-001.000):
  GET .../Application.aspx?AppID=908&LayerID=17379&PageTypeID=4&PageID=7808&KeyValue=<PARCEL>

Fills the SC gap:
  - HEATED living sqft  <- <strong>Total Heated SF</strong> / editkey ...LivingSqft  (set is_heated=True)
  - year_built          <- editkey ...ActualYearBuilt
  - market_value        <- "Total Market Value" row in the Valuation grid
  - sales[]             <- "Sales" grid (Sale Date | Sale Price | Deed Book |
                           Plat Book | Grantor | True Sale).  newest-first.

KeyValue RESOLUTION: the qPublic KeyValue is the dashed TMS. We normalize
li.parcel_id (already-dashed passes through; a bare 13-digit string is
re-segmented into NNN-NN-NN-NNN.NNN). Cherokee's qPublic search is an ASP.NET
viewstate postback (no clean static address->key GET), so an address-only lead
with no usable parcel_id returns None gracefully.

Defensive: any exception / timeout / no-match -> return None (never raises).
NO CAPTCHA / login / WAF defeat.
"""
from __future__ import annotations

import re
from html import unescape

from .base import CardResult, CardSale, money

COUNTY = ("SC", "Cherokee")   # auto-discovery key (see enrichment_assessor_card._adapters)

_CARD = (
    "https://qpublic.schneidercorp.com/Application.aspx"
    "?AppID=908&LayerID=17379&PageTypeID=4&PageID=7808&KeyValue={key}"
)
SOURCE_URL = (
    "https://qpublic.schneidercorp.com/Application.aspx"
    "?AppID=908&LayerID=17379&PageTypeID=4&PageID=7808"
)
_UA = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
    )
}

_DIGITS = re.compile(r"\d")
_TAG_RE = re.compile(r"<[^>]+>")


# --- parcel-key normalization ----------------------------------------------

def _key(li) -> str | None:
    """Normalize li.parcel_id to the dashed Cherokee TMS (NNN-NN-NN-NNN.NNN).

    - Already-dashed (contains '-') -> pass through (trim/upper not needed).
    - A bare 13-digit string -> re-segment into the 3-2-2-3.3 grouping.
    - Anything else with a dash/dot already -> pass through verbatim.
    Returns None when there is nothing usable.
    """
    raw = (getattr(li, "parcel_id", "") or "").strip()
    if not raw:
        return None
    if "-" in raw or "." in raw:
        return raw
    digits = "".join(_DIGITS.findall(raw))
    if len(digits) == 13:   # 3-2-2-3 . 3
        return f"{digits[0:3]}-{digits[3:5]}-{digits[5:7]}-{digits[7:10]}.{digits[10:13]}"
    return None


# --- value extraction -------------------------------------------------------

def _editkey_value(html: str, editkey: str) -> str | None:
    """Return the inner text of the <span editkey="{editkey}">VALUE</span> cell.

    The qPublic span is sometimes left unclosed in the dump (e.g.
    '<span editkey="...">1683 </div>'), so we stop at the first '<' rather than
    requiring a matching </span>.
    """
    m = re.search(
        r'editkey=["\']' + re.escape(editkey) + r'["\'][^>]*>\s*([^<]*)',
        html, re.I,
    )
    if not m:
        return None
    v = unescape(m.group(1)).strip()
    return v or None


def _to_int(v) -> int | None:
    if v is None:
        return None
    m = re.search(r"\d{3,4}", str(v))
    if not m:
        return None
    try:
        n = int(m.group(0))
    except ValueError:
        return None
    return n if 1700 <= n <= 2100 else None


def _market_value(html: str) -> float | None:
    """Pull the Valuation grid's total. Cherokee renders the row header as
    '= Total Market Value' (a leading '= ') inside a <th scope="row">, with the
    dollar value in the following <td>. Fall back to a plain 'Market Value' row."""
    for label in ("Total Market Value", "Market Value"):
        m = re.search(
            r"<th[^>]*>[^<]*?" + re.escape(label) + r"\s*</th>\s*<td[^>]*>\s*([^<]+)</td>",
            html, re.I,
        )
        if m:
            val = money(m.group(1))
            if val:
                return val
    return None


# --- sales table ------------------------------------------------------------

_ROW_RE = re.compile(r"<tr\b[^>]*>(.*?)</tr>", re.I | re.S)
_CELL_RE = re.compile(r"<t[dh]\b[^>]*>(.*?)</t[dh]>", re.I | re.S)


def _cell_text(fragment: str) -> str:
    return unescape(re.sub(r"\s+", " ", _TAG_RE.sub(" ", fragment))).strip()


def _sales_table_html(html: str) -> str | None:
    """Isolate the grdSales table (the Sales module grid)."""
    i = html.find("grdSales")
    if i < 0:
        return None
    seg = html[i:]
    end = seg.find("</table>")
    return seg[: end + 8] if end >= 0 else seg[:8000]


def _mdY_to_iso(s: str) -> str | None:
    """'9/27/1995' (M/D/YYYY) -> '1995-09-27'. Falls back to a bare 4-digit year."""
    m = re.match(r"\s*(\d{1,2})/(\d{1,2})/(\d{4})\s*$", s or "")
    if m:
        mo, da, yr = (int(x) for x in m.groups())
        if 1700 <= yr <= 2100:
            return f"{yr:04d}-{mo:02d}-{da:02d}"
        return None
    ym = re.search(r"\b(\d{4})\b", s or "")
    return ym.group(1) if ym else None


def _book_page(v: str | None) -> tuple[str | None, str | None]:
    """'14U-7' -> ('14U', '7'). Splits the Deed Book column on the last '-'.
    A bare token with no '-' becomes the book."""
    s = (v or "").strip()
    if not s:
        return None, None
    parts = re.split(r"\s*-\s*", s, maxsplit=1)
    book = parts[0].strip() or None
    page = parts[1].strip() if len(parts) > 1 else None
    return book, (page or None)


def _parse_sales(html: str) -> list[CardSale]:
    """Parse the Sales grid -> CardSale list (already newest-first on qPublic).

    Columns: Sale Date | Sale Price | Deed Book | Plat Book | Grantor | True Sale.
    'True Sale' = qualified flag; 'No' is mapped into reason so it is visible,
    but it is NOT a base auto-skip token (base only skips not-valid/family/exempt/
    quitclaim + price < $1000), so a qualifying-priced row still surfaces.
    """
    seg = _sales_table_html(html)
    if not seg:
        return []
    sales: list[CardSale] = []
    for rm in _ROW_RE.finditer(seg):
        cells = [_cell_text(c) for c in _CELL_RE.findall(rm.group(1))]
        if len(cells) < 2:
            continue
        c0 = cells[0].lower()
        if "sale date" in c0:   # header row
            continue
        date_iso = _mdY_to_iso(cells[0])
        price = money(cells[1]) if len(cells) > 1 else None
        book, page = _book_page(cells[2] if len(cells) > 2 else None)
        grantor = (cells[4].strip() or None) if len(cells) > 4 else None
        true_sale = (cells[5].strip() or None) if len(cells) > 5 else None
        if not (date_iso or price or book):
            continue
        reason = None
        if true_sale:
            reason = ("arms-length" if true_sale.strip().lower() in ("yes", "y", "true")
                      else f"True Sale: {true_sale.strip()}")
        sales.append(CardSale(
            sale_date=date_iso,
            price=price,
            book=book,
            page=page,
            reason=reason,
            grantor=grantor,
        ))
    return sales


# --- card assembly ----------------------------------------------------------

def _parse_card(html: str) -> CardResult | None:
    if not html or "Total Heated SF" not in html and "grdSales" not in html:
        return None

    res = CardResult(source_url=SOURCE_URL)

    sqft = money(_editkey_value(html, "sdw1_residentialbuildings_LivingSqft"))
    if sqft:
        res.living_sqft = sqft
        res.living_sqft_is_heated = True   # "Total Heated SF" = heated/finished area

    res.year_built = _to_int(_editkey_value(html, "sdw1_residentialbuildings_ActualYearBuilt"))
    res.bedrooms = money(_editkey_value(html, "sdw1_residentialbuildings_Bedrooms"))
    full = money(_editkey_value(html, "sdw1_residentialbuildings_FullBaths")) or 0.0
    half = money(_editkey_value(html, "sdw1_residentialbuildings_HalfBaths")) or 0.0
    baths = full + 0.5 * half
    res.bathrooms = baths or None

    res.market_value = _market_value(html)
    res.sales = _parse_sales(html)

    return res if res.has_fill() else None


# --- fetch (curl_cffi -> httpx -> StealthyFetcher render fallback) ----------

def _fetch_curl_cffi(url: str) -> str | None:
    try:
        from curl_cffi import requests as cffi
    except ImportError:
        return None
    try:
        r = cffi.get(url, impersonate="chrome", timeout=30, headers=_UA)
    except Exception:
        return None
    if getattr(r, "status_code", 0) == 200 and r.text:
        return r.text
    return None


async def _fetch_httpx(url: str) -> str | None:
    try:
        from ..http_client import client
    except Exception:
        return None
    try:
        async with client(timeout=30.0, headers=_UA) as c:
            r = await c.get(url)
        if r.status_code == 200 and r.text:
            return r.text
    except Exception:
        return None
    return None


async def _fetch_render(url: str) -> str | None:
    """Last resort: stealth render (auto-handles Cloudflare + the Agree disclaimer)."""
    try:
        from scrapling.fetchers import StealthyFetcher
    except ImportError:
        return None
    holder: dict = {}

    async def page_action(page):
        try:
            await page.wait_for_load_state("networkidle", timeout=25000)
        except Exception:
            pass
        # qPublic gates some sites behind an "Agree" disclaimer button.
        for sel in ("text=Agree", "button:has-text('Agree')", "#btnAgree"):
            try:
                btn = await page.query_selector(sel)
                if btn:
                    await btn.click()
                    await page.wait_for_timeout(2500)
                    break
            except Exception:
                pass
        try:
            holder["html"] = await page.content()
        except Exception:
            holder["html"] = ""

    try:
        await StealthyFetcher.async_fetch(
            url, headless=True, network_idle=True, timeout=90000,
            page_action=page_action, solve_cloudflare=True)
    except Exception:
        return None
    return holder.get("html") or None


async def fetch(li) -> CardResult | None:
    try:
        key = _key(li)
        if not key:
            return None   # address-only lead: qPublic search is a viewstate postback
        url = _CARD.format(key=key)

        # 1) curl_cffi chrome impersonate (synchronous; cheap and reliable here).
        html = _fetch_curl_cffi(url)
        # 2) plain httpx with a full browser UA.
        if not html:
            html = await _fetch_httpx(url)
        # 3) stealth render fallback (Cloudflare + Agree).
        if not html or ("Total Heated SF" not in html and "grdSales" not in html):
            rendered = await _fetch_render(url)
            if rendered:
                html = rendered
        if not html:
            return None

        res = _parse_card(html)
        return res if (res and res.has_fill()) else None
    except Exception:
        return None
