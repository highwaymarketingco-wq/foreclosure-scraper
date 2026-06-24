"""Greenville County SC assessor card — county RealProperty web app (public, no login).

Fills the SC bulk gap on the PRICE side only: recorded SALE PRICE + deed
book/page + deed date + appraised Fair Market Value. Heated living sqft is NOT
parsed here — Greenville exposes building/finished area only on an IMAGE-based
property-card PDF (a scanned AS/400 card, no text layer), so this adapter is
PRICE-ONLY by design.

Card (plain HTML, no Cloudflare / no disclaimer gate):
  GET .../RealProperty/Details.aspx?MapNumber={13-digit-PIN}&TaxYear={year}
  -> <th>Sale Price:</th><td>$225,000</td>
     <th>Deed Date:</th><td>08/02/2019</td>
     <th>Deed Book-Page:</th><td>2572 - 2018</td>   (book - page)
     <th>Fair Market Value:</th><td>373,370</td>

Key = 13-digit MapNumber. Resolved from:
  1. li.parcel_id digits (use directly when it's exactly 13 digits), else
  2. a street search -> SearchResults.aspx (GET shortcut; no ASP.NET postback
     needed — the search form simply redirects to this URL) -> first/best
     Details.aspx?MapNumber=... link for li.street_address.
"""
from __future__ import annotations

import re
from datetime import datetime

from selectolax.parser import HTMLParser

from ..http_client import client
from .base import CardResult, CardSale, money

_BASE = "https://www.greenvillecounty.org/appsas400/RealProperty"
_DETAILS = f"{_BASE}/Details.aspx"
_RESULTS = f"{_BASE}/SearchResults.aspx"
SOURCE_URL = f"{_BASE}/Default.aspx"
_UA = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
       "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"}

COUNTY = ("SC", "Greenville")   # auto-discovery key (see enrichment_assessor_card._adapters)

_LINK_RE = re.compile(r"Details\.aspx\?MapNumber=(\d{13})", re.I)
_NUM_RE = re.compile(r"\d+")


def _tax_years() -> list[int]:
    """Current year first, then prior — a fresh-foreclosure card may not yet be
    rolled into the new tax year, so fall back one year."""
    y = datetime.now().year
    return [y, y - 1]


def _map_number(li) -> str | None:
    """li.parcel_id -> 13-digit MapNumber when the id already carries it."""
    digits = "".join(_NUM_RE.findall(li.parcel_id or ""))
    return digits if len(digits) == 13 else None


def _norm_addr(s: str | None) -> str:
    """Collapse whitespace + uppercase for fuzzy street-row matching."""
    return re.sub(r"\s+", " ", (s or "").strip()).upper()


async def _resolve_by_street(c, li) -> str | None:
    """Street search -> 13-digit MapNumber. Picks the row whose address best
    matches li.street_address; falls back to the single/first result."""
    street = (li.street_address or "").strip()
    if not street:
        return None
    for year in _tax_years():
        try:
            r = await c.get(_RESULTS, params={
                "type": "Street", "Criteria": street, "TaxYear": str(year)})
        except Exception:
            continue
        if r.status_code != 200:
            continue
        tree = HTMLParser(r.text)
        rows: list[tuple[str, str]] = []   # (map_number, row_address_text)
        for a in tree.css("a[href*='Details.aspx']"):
            m = _LINK_RE.search(a.attributes.get("href") or "")
            if not m:
                continue
            tr = a.parent
            while tr is not None and tr.tag != "tr":
                tr = tr.parent
            row_txt = _norm_addr(tr.text()) if tr is not None else ""
            rows.append((m.group(1), row_txt))
        if not rows:
            continue
        if len(rows) == 1:
            return rows[0][0]
        # Match on the leading house number + first street word for precision.
        want = _norm_addr(street)
        want_tokens = [t for t in want.split() if t][:2]
        for mn, row_txt in rows:
            if want_tokens and all(t in row_txt for t in want_tokens):
                return mn
        return rows[0][0]   # last-resort: first result
    return None


def _field(tree: HTMLParser, label: str) -> str | None:
    """Return the <td> text for the <th>{label}</th> row (case-insensitive)."""
    want = label.strip().lower().rstrip(":")
    for th in tree.css("th"):
        txt = (th.text() or "").strip().lower().rstrip(":")
        if txt == want:
            td = th.next
            while td is not None and td.tag != "td":
                td = td.next
            if td is not None:
                return re.sub(r"\s+", " ", td.text() or "").strip() or None
    return None


def _deed_date(v: str | None) -> str | None:
    """'08/02/2019' (MM/DD/YYYY) -> '2019-08-02'. Falls back to a bare year."""
    s = (v or "").strip()
    m = re.match(r"(\d{1,2})/(\d{1,2})/(\d{4})", s)
    if m:
        mm, dd, yy = m.groups()
        return f"{yy}-{int(mm):02d}-{int(dd):02d}"
    ym = re.search(r"\b(\d{4})\b", s)
    return ym.group(1) if ym else None


def _book_page(v: str | None) -> tuple[str | None, str | None]:
    """'2572 - 2018' -> ('2572', '2018'). Handles '/', '-', or whitespace splits."""
    s = (v or "").strip()
    if not s:
        return None, None
    parts = re.split(r"\s*[-/]\s*", s, maxsplit=1)
    book = parts[0].strip() or None
    page = parts[1].strip() if len(parts) > 1 else None
    return book, (page or None)


def _parse_card(html: str) -> CardResult | None:
    tree = HTMLParser(html)
    price = money(_field(tree, "Sale Price"))
    fmv = money(_field(tree, "Fair Market Value"))
    if not price and not fmv:
        return None
    res = CardResult(source_url=SOURCE_URL, market_value=fmv)
    if price:
        book, page = _book_page(_field(tree, "Deed Book-Page"))
        res.sales = [CardSale(
            sale_date=_deed_date(_field(tree, "Deed Date")),
            price=price,
            book=book,
            page=page,
        )]
    return res if res.has_fill() else None


async def fetch(li) -> CardResult | None:
    async with client(timeout=30.0, headers=_UA) as c:
        map_no = _map_number(li)
        if not map_no:
            try:
                map_no = await _resolve_by_street(c, li)
            except Exception:
                map_no = None
        if not map_no:
            return None
        for year in _tax_years():
            try:
                r = await c.get(_DETAILS, params={
                    "MapNumber": map_no, "TaxYear": str(year)})
            except Exception:
                continue
            if r.status_code != 200:
                continue
            try:
                res = _parse_card(r.text)
            except Exception:
                res = None
            if res and res.has_fill():
                return res
    return None
