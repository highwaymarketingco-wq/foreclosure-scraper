"""Shared qPublic / Schneider (Spatialest SPA) assessor-card adapter — RENDER class.

Four SC counties share one Schneider-hosted qPublic application
(qpublic.schneidercorp.com). The card is a JavaScript SPA sitting behind
Cloudflare Turnstile + (sometimes) a one-click "Agree" disclaimer, so plain HTTP
returns 403 / an empty shell — it MUST be rendered with the project's stealth
browser (Scrapling StealthyFetcher, camoufox), exactly like
scrapers/counties_sc/sc_state_tax_lien.py. `solve_cloudflare=True` handles the
Turnstile; the page_action clicks "Agree" if a disclaimer gate is shown.

Per-county Schneider app config (AppID / LayerID / PageID) and KeyValue strategy:

  Spartanburg  AppID=857  LayerID=16069 PageID=7149  card; PageID=7148 search
               KeyValue = DASHED MAP number. li.parcel_id digits "7170204100"
               -> "7-17-02-041.00"  (d[0]-d[1:3]-d[3:5]-d[5:8].d[8:10]).
  Oconee       AppID=1030 LayerID=21692 PageID=9258  card; PageID=9257 search
               KeyValue = dashed parcel, e.g. "520-77-01-021" (already dashed in
               li.parcel_id, just normalized).
  Pickens      AppID=927  LayerID=18058 PageID=8077  card; PageID=8076 search
               KeyValue = R-account (e.g. "R0022220"), NOT a dashed TMS — resolve
               via the owner/address typeahead SEARCH page.
  Union        AppID=861  LayerID=16112 PageID=7168  card; PageID=7167 search
               "Living Area" sqft (incl. basement). Resolve by address search.
               (Plain curl returned 403 in discovery; render is required. If Union
               still 403s under render, it returns None gracefully.)

Card URL shape:
  https://qpublic.schneidercorp.com/Application.aspx?AppID={A}&LayerID={L}&PageTypeID=4&PageID={P}&KeyValue={key}
Search URL shape (typeahead lives on PageTypeID=2):
  https://qpublic.schneidercorp.com/Application.aspx?AppID={A}&LayerID={L}&PageTypeID=2&PageID={S}&KeyValue={q}

Parsing: the SPA renders standard Schneider markup —
  * Building/residential facts live in `table.tabular-data-two-column` rows
    (<th> label / <td> value), label text e.g. "Heated Square Feet",
    "Square Feet", "Living Area", "Year Built", "Number Of Bedrooms".
  * Value summary is either a simple two-column "Total Value (Market)" row or a
    multi-year grid whose total line uses `td.value-column`.
  * The Sales grid is `table.tabular-data ... gvwSales/gvwList`; columns vary by
    county so we map by HEADER NAME, not fixed index. Newest row is first.

Defensive: ANY exception / timeout / no-match -> return None (never raises).
"""
from __future__ import annotations

import asyncio
import re
from urllib.parse import urlencode

import structlog

from .base import CardResult, CardSale, money

log = structlog.get_logger()

SOURCE_HOST = "https://qpublic.schneidercorp.com"

COUNTIES = [("SC", "Spartanburg"), ("SC", "Oconee"), ("SC", "Pickens"), ("SC", "Union")]

# Per-county Schneider app config. `card`/`search` are PageIDs.
_CFG: dict[str, dict] = {
    "Spartanburg": {"app": 857, "layer": 16069, "card": 7149, "search": 7148, "key": "tms"},
    "Oconee":      {"app": 1030, "layer": 21692, "card": 9258, "search": 9257, "key": "dashed"},
    "Pickens":     {"app": 927, "layer": 18058, "card": 8077, "search": 8076, "key": "search"},
    "Union":       {"app": 861, "layer": 16112, "card": 7168, "search": 7167, "key": "search"},
}

# Render tunables (kept conservative; this is a low-volume, grade-gated path).
_TIMEOUT_MS = 90000
_SETTLE_MS = 2500

# Building-fact label -> attribute. Matched case-insensitively as a substring of
# the row's <th> text. Order matters only for sqft (most specific first).
# Heated/finished labels (the true conditioned living area) — checked FIRST so a
# card that lists both "Gross Sq Ft" and "Finished Sq Ft" (Spartanburg) yields the
# finished value, not gross. Covers both spelled-out and abbreviated ("sq ft") forms.
_SQFT_LABELS_HEATED = ("heated square feet", "heated sq ft", "heated sq",
                       "finished square feet", "finished sq ft", "finished sq",
                       "total heated", "heated/finished")
# Plain fallback (used only when no heated/finished label exists). Gross-area rows
# are filtered out at the call site, so this never returns a garage-inclusive figure.
_SQFT_LABELS_PLAIN = ("living area", "total living area", "square feet", "sq ft", "sqft")


# --------------------------------------------------------------------------- #
# KeyValue derivation
# --------------------------------------------------------------------------- #
def _digits(s: str | None) -> str:
    return re.sub(r"\D", "", s or "")


def _spartanburg_key(li) -> str | None:
    """Spartanburg KeyValue = dashed MAP number d[0]-d[1:3]-d[3:5]-d[5:8].d[8:10]
    e.g. "7170204100" -> "7-17-02-041.00". If li.parcel_id already looks dashed
    (has '-'), pass it through normalized."""
    raw = (li.parcel_id or "").strip()
    if "-" in raw and "." in raw:
        return raw.upper()
    d = _digits(raw)
    if len(d) >= 10:
        d = d[:10]
        return f"{d[0]}-{d[1:3]}-{d[3:5]}-{d[5:8]}.{d[8:10]}"
    return raw or None


def _oconee_key(li) -> str | None:
    """Oconee KeyValue = dashed parcel, e.g. "520-77-01-021". Usually already
    dashed in li.parcel_id; normalize spacing/case."""
    raw = (li.parcel_id or "").strip()
    if not raw:
        return None
    return re.sub(r"\s+", "", raw).upper()


def _card_url(cfg: dict, key: str) -> str:
    q = {"AppID": cfg["app"], "LayerID": cfg["layer"], "PageTypeID": 4,
         "PageID": cfg["card"], "KeyValue": key}
    return f"{SOURCE_HOST}/Application.aspx?{urlencode(q)}"


def _search_url(cfg: dict, query: str) -> str:
    q = {"AppID": cfg["app"], "LayerID": cfg["layer"], "PageTypeID": 2,
         "PageID": cfg["search"], "KeyValue": query}
    return f"{SOURCE_HOST}/Application.aspx?{urlencode(q)}"


# --------------------------------------------------------------------------- #
# Render
# --------------------------------------------------------------------------- #
async def _click_agree(page) -> None:
    """Click the one-click 'Agree' disclaimer gate if present (no-op otherwise)."""
    for sel in ("a:has-text('Agree')", "button:has-text('Agree')",
                "input[value='Agree']", "input[type=submit][value*=Agree]",
                "#btnAgree"):
        try:
            el = await page.query_selector(sel)
            if el:
                await el.click()
                await page.wait_for_timeout(_SETTLE_MS)
                return
        except Exception:
            continue


async def _render(url: str, *, on_loaded=None) -> str:
    """Render `url` with the stealth browser; return final page HTML (or "").

    `on_loaded(page)` runs after the Agree gate is cleared and the card/search
    DOM is present — used by the search flow to drive the typeahead and read the
    resolved card URL. Mirrors sc_state_tax_lien.py's StealthyFetcher pattern.
    """
    try:
        from scrapling.fetchers import StealthyFetcher
    except ImportError:
        log.warning("qpublic.scrapling_missing")
        return ""
    holder: dict = {}

    async def page_action(page):
        try:
            await page.wait_for_load_state("domcontentloaded", timeout=25000)
        except Exception:
            pass
        await page.wait_for_timeout(_SETTLE_MS)
        await _click_agree(page)
        try:
            await page.wait_for_load_state("networkidle", timeout=25000)
        except Exception:
            pass
        await page.wait_for_timeout(_SETTLE_MS)
        if on_loaded is not None:
            try:
                await on_loaded(page)
            except Exception:
                pass
        try:
            holder["html"] = await page.content()
        except Exception:
            holder["html"] = ""

    try:
        resp = await StealthyFetcher.async_fetch(
            url, headless=True, network_idle=True, timeout=_TIMEOUT_MS,
            page_action=page_action, solve_cloudflare=True)
    except Exception as exc:
        log.debug("qpublic.render_error", url=url[:120], error=str(exc)[:150])
        return holder.get("html", "") or ""
    status = getattr(resp, "status", None)
    if status and status >= 400 and not holder.get("html"):
        log.debug("qpublic.bad_status", url=url[:120], status=status)
        return ""
    return holder.get("html") or (getattr(resp, "html_content", "") or "")


async def _resolve_via_search(cfg: dict, query: str) -> str | None:
    """Drive the qPublic typeahead with `query`; return the resolved KeyValue.

    The search box is a twitter-typeahead `input[type=search]`. We type the
    address, wait for the suggestion dropdown, click the first suggestion, and
    read KeyValue out of the resulting card URL. Returns None on any failure.
    """
    holder: dict = {}

    async def on_loaded(page):
        # Find the global search input (typeahead). Try a few selectors.
        box = None
        for sel in ("input.tt-input", "input[type=search].tt-upm-global-search-input",
                    "input[type=search]", "#topSearchControl"):
            try:
                box = await page.query_selector(sel)
                if box:
                    break
            except Exception:
                continue
        if not box:
            return
        try:
            await box.click()
            await box.fill("")
            await box.type(query, delay=40)
            await page.wait_for_timeout(2500)  # let typeahead populate
        except Exception:
            return
        # Click the first typeahead suggestion if shown, else press Enter.
        clicked = False
        for sel in (".tt-suggestion", ".tt-menu .tt-suggestion", "a.tt-suggestion",
                    ".typeahead-results a", "ul.tt-dropdown-menu .tt-suggestion"):
            try:
                sug = await page.query_selector(sel)
                if sug:
                    await sug.click()
                    clicked = True
                    break
            except Exception:
                continue
        if not clicked:
            try:
                await box.press("Enter")
            except Exception:
                return
        try:
            await page.wait_for_load_state("networkidle", timeout=25000)
        except Exception:
            pass
        await page.wait_for_timeout(_SETTLE_MS)
        try:
            holder["url"] = page.url
        except Exception:
            pass

    await _render(_search_url(cfg, query), on_loaded=on_loaded)
    final = holder.get("url") or ""
    m = re.search(r"[?&]KeyValue=([^&#]+)", final)
    if m and "PageTypeID=4" in final:
        from urllib.parse import unquote
        return unquote(m.group(1))
    return None


# --------------------------------------------------------------------------- #
# HTML parsing
# --------------------------------------------------------------------------- #
def _soup(html: str):
    try:
        from bs4 import BeautifulSoup
        return BeautifulSoup(html, "html.parser")
    except Exception:
        return None


def _row_value(th_text: str, td) -> str:
    """Extract the displayed value text from a row's value <td>."""
    if td is None:
        return ""
    return re.sub(r"\s+", " ", td.get_text(" ", strip=True)).strip()


def _two_column_facts(soup) -> dict[str, str]:
    """Collect {label_lower: value} from every <th>/<td> two-column fact row in
    the building / residential / value tables."""
    facts: dict[str, str] = {}
    for tr in soup.find_all("tr"):
        th = tr.find("th")
        if not th:
            continue
        label = re.sub(r"\s+", " ", th.get_text(" ", strip=True)).strip().lower()
        if not label:
            continue
        td = tr.find("td")
        val = _row_value(label, td)
        if val and label not in facts:
            facts[label] = val
    return facts


def _pick(facts: dict[str, str], labels) -> str | None:
    for want in labels:
        for label, val in facts.items():
            if want in label:
                return val
    return None


def _int(v: str | None) -> int | None:
    if not v:
        return None
    m = re.search(r"\d[\d,]*", v)
    if not m:
        return None
    try:
        n = int(m.group(0).replace(",", ""))
    except ValueError:
        return None
    return n or None


def _float(v: str | None) -> float | None:
    if not v:
        return None
    m = re.search(r"\d[\d,]*(?:\.\d+)?", v)
    if not m:
        return None
    try:
        return float(m.group(0).replace(",", "")) or None
    except ValueError:
        return None


def _parse_market_value(soup) -> float | None:
    """Total appraised/market value. Handles the simple two-column row
    ('Total Value (Market)') AND the multi-year grid total line (td.value-column),
    taking the first/current-year value column."""
    # Simple two-column form.
    facts = _two_column_facts(soup)
    for key in ("total value (market)", "total market value", "total appraised value",
                "total value", "appraised value", "market value"):
        if key in facts:
            mv = money(facts[key])
            if mv:
                return mv
    # Multi-year grid: a total row (often class 'double-total-line' or a <th>
    # containing 'Total') with td.value-column cells; take the first one.
    for tr in soup.find_all("tr"):
        th = tr.find("th")
        label = (th.get_text(" ", strip=True).lower() if th else "")
        cls = " ".join(tr.get("class") or [])
        if "total" in label or "total" in cls:
            cells = tr.find_all("td", class_="value-column")
            for c in cells:
                mv = money(c.get_text(" ", strip=True))
                if mv:
                    return mv
    return None


_DATE_RE = re.compile(r"(\d{1,2})/(\d{1,2})/(\d{4})")


def _norm_date(s: str | None) -> str | None:
    """'M/D/YYYY' -> 'YYYY-MM-DD'; a bare year -> the year string; else None."""
    if not s:
        return None
    m = _DATE_RE.search(s)
    if m:
        mm, dd, yy = m.groups()
        return f"{yy}-{int(mm):02d}-{int(dd):02d}"
    y = re.search(r"\b(19|20)\d{2}\b", s)
    return y.group(0) if y else None


def _cell_text(td) -> str:
    return re.sub(r"\s+", " ", td.get_text(" ", strip=True)).strip()


def _parse_sales(soup) -> list[CardSale]:
    """Parse the Schneider sales grid, mapping columns by HEADER NAME (column
    order differs across counties). Returns rows newest-first (table order)."""
    table = None
    for t in soup.find_all("table"):
        tid = (t.get("id") or "")
        if "gvwSales" in tid or "gvwList" in tid:
            # confirm it's the sales grid by its headers
            head = t.get_text(" ", strip=True).lower()
            if "sale date" in head and "sale price" in head:
                table = t
                break
    if table is None:
        for t in soup.find_all("table"):
            head = " ".join(th.get_text(" ", strip=True).lower()
                            for th in t.find_all("th"))
            if "sale date" in head and "sale price" in head:
                table = t
                break
    if table is None:
        return []

    # Build header index map from the <thead> (or first row).
    header_cells = []
    thead = table.find("thead")
    hdr_row = thead.find("tr") if thead else table.find("tr")
    if hdr_row:
        header_cells = [c.get_text(" ", strip=True).lower()
                        for c in hdr_row.find_all(["th", "td"])]

    def col(*names) -> int | None:
        for i, h in enumerate(header_cells):
            for n in names:
                if n in h:
                    return i
        return None

    i_date = col("sale date")
    i_price = col("sale price")
    i_inst = col("instrument")
    # A combined "Deed Book / Page" column (Oconee) must win over the standalone
    # "Deed Book" / "Deed Page" columns (Spartanburg/Union).
    i_bookpage = col("deed book / page", "book / page", "book/page")
    i_book = None if i_bookpage is not None else col("deed book", "book")
    i_page = None if i_bookpage is not None else col("deed page", "page")
    i_reason = col("reason", "qualification", "sale validity", "vacant or improved")
    i_grantor = col("grantor")
    i_grantee = col("grantee")

    body = table.find("tbody") or table
    rows = body.find_all("tr")
    # Skip the header row if there's no <thead>.
    if not thead and rows and rows[0].find("th") and not rows[0].find("td"):
        rows = rows[1:]

    out: list[CardSale] = []
    for tr in rows:
        cells = tr.find_all(["th", "td"])
        if not cells:
            continue
        texts = [_cell_text(c) for c in cells]
        if all(not t for t in texts):
            continue

        def at(idx):
            return texts[idx] if (idx is not None and idx < len(texts)) else None

        book = at(i_book)
        page = at(i_page)
        if (book is None and page is None) and i_bookpage is not None:
            bp = at(i_bookpage) or ""
            parts = re.split(r"[/\s]+", bp.strip())
            if len(parts) >= 2:
                book, page = parts[0], parts[1]
            elif parts and parts[0]:
                book = parts[0]

        price = money(at(i_price))
        date = _norm_date(at(i_date))
        if not price and not date:
            continue
        out.append(CardSale(
            sale_date=date,
            price=price,
            book=(book or None),
            page=(page or None),
            reason=(at(i_reason) or None),
            grantor=(at(i_grantor) or None),
            grantee=(at(i_grantee) or None),
        ))
    return out  # already newest-first in the grid


def _parse_card(html: str, county: str) -> CardResult | None:
    soup = _soup(html)
    if soup is None:
        return None
    # "No data" / not-found guard.
    low = html.lower()
    if ("no data" in low and "found" in low) or "could not be found" in low:
        # still try to parse — some pages contain that phrase in footers
        pass

    facts = _two_column_facts(soup)
    sqft_h = _float(_pick(facts, _SQFT_LABELS_HEATED))
    sqft_is_heated = sqft_h is not None
    # Plain fallback only when no heated/finished label exists; never use a gross row.
    non_gross = {k: v for k, v in facts.items() if "gross" not in k}
    sqft = sqft_h if sqft_h is not None else _float(_pick(non_gross, _SQFT_LABELS_PLAIN))
    # Union exposes "Living Area" (incl. basement); treat as living area, not
    # strictly heated -> living_sqft_is_heated stays False for that label.

    res = CardResult(source_url=SOURCE_HOST)
    res.living_sqft = sqft
    res.living_sqft_is_heated = sqft_is_heated
    res.year_built = _int(_pick(facts, ("year built", "actual year built")))
    res.bedrooms = _float(_pick(facts, ("number of bedrooms", "bedrooms", "bed rooms")))
    res.bathrooms = _float(_pick(facts, ("number of full baths", "full bathrooms",
                                         "bathrooms", "full baths")))
    res.market_value = _parse_market_value(soup)
    res.sales = _parse_sales(soup)
    return res if res.has_fill() else None


# --------------------------------------------------------------------------- #
# Public entrypoint
# --------------------------------------------------------------------------- #
async def fetch(li) -> CardResult | None:
    """Resolve `li` to its qPublic card and return a CardResult, or None."""
    try:
        county = (li.county or "").strip().title()
        cfg = _CFG.get(county)
        if not cfg:
            return None

        # Resolve the KeyValue per county strategy.
        key: str | None = None
        if cfg["key"] == "tms":
            key = _spartanburg_key(li)
        elif cfg["key"] == "dashed":
            key = _oconee_key(li)
        else:  # "search": Pickens (R-account) / Union — resolve via typeahead
            query = (li.street_address or "").strip() or (li.parcel_id or "").strip()
            if not query:
                return None
            key = await _resolve_via_search(cfg, query)

        if not key:
            return None

        html = await _render(_card_url(cfg, key))
        if not html or len(html) < 500:
            return None
        return _parse_card(html, county)
    except Exception:  # absolute backstop — never raise
        log.debug("qpublic.fetch_failed", county=getattr(li, "county", None))
        return None
