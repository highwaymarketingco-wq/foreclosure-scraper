"""Albertelli Law (ALAW) — North Carolina foreclosure sales list.

ALAW (alaw.net, substitute-trustee / default-services firm, Charlotte NC office)
publishes its NC upcoming foreclosure sales at
    https://www.alaw.net/foreclosure-sales/north-carolina/

The page itself has NO HTML table and NO JSON API. It is a WordPress shell that
embeds a PUBLIC, anonymously-shared SharePoint / Excel-Online workbook
(``FSales-NC.xlsx``) via an ``<iframe ... action=embedview>``. The grid is painted
inside the Office Web Apps (WAC) frame — nothing to parse with plain httpx.

Extraction (FREE + PUBLIC only — no login, no CAPTCHA, no token forgery, no WAF
defeat). This is the exact anonymous embed a human visitor sees:

  1. GET the public WP page and pull the SharePoint embed URL out of the iframe
     (``data-lazy-src``). We follow whatever the public page currently embeds, so
     the workbook GUID never has to be hard-coded.
  2. Render that embed with a headless browser. To paint the canvas immediately,
     the Office WAC bootstrap frame (``xlembed.aspx``, served by
     ``*.officeapps.live.com``) inlines the visible cell range as
     ``{"Col":c,"Row":r,"Text":"..."}`` objects. We capture that frame's HTML and
     reconstruct the grid from those cells. No file download, no WOPI call.
  3. Map the columns to :class:`Listing` rows.

Why a browser and not httpx: the workbook renders server-side in the WAC frame;
the anonymous ``download.aspx`` path returns a JS SPA interstitial and the WOPI
``GetFile`` endpoint requires the Office host's ``X-WOPI-Proof`` signature. The
only free, compliant path is to render the public embed the same way a browser
does and read the cell bootstrap. The parser (:func:`parse_wac_cells`) is pure and
network-free so it is unit-tested against a saved fixture.

Firm coverage is STATEWIDE NC ("from the mountains to the coast"). Rows outside
the Western-NC / Upstate-SC footprint are dropped downstream. ALAW also publishes a sibling SC workbook at
``/foreclosure-sales/south-carolina/`` (SC Upstate is core footprint); both pages
flow through the same state-aware parser.
"""
from __future__ import annotations

import html as htmllib
import os
import re
from datetime import datetime
from typing import Iterable

from dateutil import parser as dateparser

from ...base_scraper import BaseScraper
from ...http_client import get_text
from ...models import Listing, ListingType, PropertyKind

log = __import__("structlog").get_logger()

# Human-facing public pages — used as the stable source_url and the embed source.
# ALAW publishes a workbook per state via the same anonymous Office embed; the
# parser is state-aware (reads "NC - County" / "SC - County"), so both flow through
# the same path. SC is Upstate-core for us; NC is statewide (Cleveland/Gaston etc).
WP_PAGE_URL = "https://www.alaw.net/foreclosure-sales/north-carolina/"
WP_PAGES = (
    "https://www.alaw.net/foreclosure-sales/north-carolina/",
    "https://www.alaw.net/foreclosure-sales/south-carolina/",
)

# Pull the SharePoint Office-embed URL out of the WP page iframe. The real markup
# lazy-loads it via data-lazy-src (and repeats it in a <noscript> src).
_EMBED_RE = re.compile(
    r'(?:data-lazy-src|src)=["\']'
    r'([^"\']*albertellilaw\.sharepoint\.com[^"\']*action=embedview[^"\']*)["\']',
    re.I,
)

# Office WAC cell bootstrap: {"Col":c,"Row":r,"Text":"..."} — but the JSON is
# multiply backslash-escaped inside a JS string inside HTML, so allow one-or-more
# backslashes before every quote. Text runs until the next unescaped quote.
_CELL_RE = re.compile(
    r'\\+"Col\\+":(\d+),\\+"Row\\+":(\d+),\\+"Text\\+":\\+"((?:[^"\\]|\\.)*?)\\+"'
)

# How long to wait for the WAC frame to deliver its bootstrap.
_RENDER_TIMEOUT_MS = int(os.environ.get("ALAW_RENDER_TIMEOUT_MS", "60000"))
_CAPTURE_WAIT_MS = int(os.environ.get("ALAW_CAPTURE_WAIT_MS", "8000"))


def _deescape(text: str) -> str:
    """Undo the JS/JSON escaping on a captured cell value.

    The cell text is wrapped in several escaping layers (JSON inside a JS string
    inside HTML), so a slash can arrive as ``\\/`` or ``\\\\\\/`` etc. These
    workbook cells (addresses, cities, dates, case numbers) never legitimately
    contain a backslash, so after decoding ``\\uXXXX`` escapes we drop any
    remaining escaping backslashes at whatever depth."""
    # Decode \uXXXX (any backslash depth) — e.g. an escaped ampersand.
    text = re.sub(r'\\+u([0-9a-fA-F]{4})', lambda m: chr(int(m.group(1), 16)), text)
    text = text.replace('\\r', ' ').replace('\\n', ' ').replace('\\t', ' ')
    text = text.replace('\\', '')   # collapse remaining structural backslashes
    text = htmllib.unescape(text)
    return re.sub(r'\s+', ' ', text).strip()


def _norm_header(h: str) -> str:
    return re.sub(r'[^a-z]', '', h.lower())


# Canonical column → normalized header aliases (robust to minor label drift).
_COL_ALIASES = {
    "file_number": {"filenumber", "fileno", "file"},
    "case_status": {"casestatus", "status"},
    "address": {"address", "propertyaddress", "street"},
    "city": {"city"},
    "state": {"state"},
    "zip": {"zip", "zipcode", "postalcode"},
    "county": {"county"},
    "bid": {"bidamount", "openingbid", "bid"},
    "sale_date": {"currentsaledate", "saledate", "currentsale", "date"},
    "case_number": {"courtcasenumber", "courtcase", "casenumber", "caseno"},
}


def _f(v: str | None) -> str | None:
    v = (v or "").strip()
    return v or None


def parse_wac_cells(wac_html: str, source_url: str = WP_PAGE_URL) -> list[Listing]:
    """Reconstruct the workbook grid from a captured WAC ``xlembed.aspx`` payload
    and map each data row to a :class:`Listing`. Pure + network-free."""
    cells: dict[tuple[int, int], str] = {}
    for m in _CELL_RE.finditer(wac_html):
        row, col = int(m.group(2)), int(m.group(1))
        cells[(row, col)] = _deescape(m.group(3))
    if not cells:
        return []

    rows = sorted({r for r, _ in cells})
    # Header row = the first row that contains a recognizable "Address"/"County".
    header_row = None
    for r in rows:
        vals = {c: v for (rr, c), v in cells.items() if rr == r}
        norms = {_norm_header(v) for v in vals.values()}
        if norms & _COL_ALIASES["address"] and norms & _COL_ALIASES["county"]:
            header_row = r
            break
    if header_row is None:
        return []

    # Map canonical field -> column index from the header row.
    colmap: dict[str, int] = {}
    for (rr, c), v in cells.items():
        if rr != header_row:
            continue
        nh = _norm_header(v)
        for field, aliases in _COL_ALIASES.items():
            if nh in aliases and field not in colmap:
                colmap[field] = c

    def cell(r: int, field: str) -> str | None:
        c = colmap.get(field)
        return cells.get((r, c)) if c is not None else None

    out: list[Listing] = []
    for r in rows:
        if r <= header_row:
            continue
        addr = _f(cell(r, "address"))
        case_no = _f(cell(r, "case_number"))
        file_no = _f(cell(r, "file_number"))
        if not addr and not case_no:
            continue  # blank/spacer row

        # County column is "NC - Cleveland" (or "NC -" when unknown).
        county_raw = _f(cell(r, "county")) or ""
        state = _f(cell(r, "state")) or "NC"
        county = None
        m = re.match(r'^\s*([A-Za-z]{2})\s*-\s*(.*)$', county_raw)
        if m:
            state = m.group(1).upper()
            county = _f(m.group(2))
        elif county_raw:
            county = county_raw
        if county:
            county = county.replace(" County", "").strip() or None

        sale_date = None
        dr = _f(cell(r, "sale_date"))
        if dr:
            try:
                sale_date = dateparser.parse(dr)
            except (ValueError, TypeError, OverflowError):
                sale_date = None

        bid = None
        br = _f(cell(r, "bid"))
        if br:
            bm = re.search(r'([\d,]+(?:\.\d{1,2})?)', br)
            if bm:
                try:
                    bid = float(bm.group(1).replace(",", ""))
                except ValueError:
                    bid = None

        out.append(
            Listing(
                source="law_firms.alaw",
                source_url=source_url,
                listing_type=ListingType.FORECLOSURE_SALE,
                property_kind=PropertyKind.UNKNOWN,
                street_address=addr,
                city=_f(cell(r, "city")),
                state=state,
                zip_code=_f(cell(r, "zip")),
                county=county,
                sale_date=sale_date,
                opening_bid=bid,
                case_number=case_no,
                trustee="Albertelli Law",
                foreclosure_process="power_of_sale",
                description=f"ALAW trustee sale — file {file_no or '?'}",
                first_seen=datetime.utcnow(),
                last_seen=datetime.utcnow(),
            )
        )
    return out


def _discover_embed_url(page_html: str) -> str | None:
    m = _EMBED_RE.search(page_html or "")
    return htmllib.unescape(m.group(1)) if m else None


async def _render_capture(embed_url: str) -> str:
    """Render the public Office embed with a headless browser and return the WAC
    ``xlembed.aspx`` bootstrap HTML (which inlines the visible cell range).

    A tall viewport is used so the WAC frame bootstraps as many rows as possible
    (Office only inlines the visible range). Returns "" on any failure — the
    scraper treats that as an empty run, not a crash."""
    try:
        from playwright.async_api import async_playwright
    except ImportError:
        log.warning("alaw.playwright_missing")
        return ""

    captured: list[str] = []
    try:
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            ctx = await browser.new_context(viewport={"width": 1400, "height": 3200})
            pg = await ctx.new_page()

            async def _on_response(resp):  # noqa: ANN001
                if "xlembed.aspx" in resp.url:
                    try:
                        body = await resp.text()
                    except Exception:  # noqa: BLE001
                        return
                    if 'Col' in body and 'Text' in body:
                        captured.append(body)

            pg.on("response", _on_response)
            try:
                await pg.goto(embed_url, wait_until="domcontentloaded",
                              timeout=_RENDER_TIMEOUT_MS)
            except Exception as exc:  # noqa: BLE001
                log.warning("alaw.goto_failed", error=str(exc)[:200])
            # Poll for the bootstrap frame to arrive.
            waited = 0
            step = 1000
            while not captured and waited < _RENDER_TIMEOUT_MS:
                await pg.wait_for_timeout(step)
                waited += step
            if captured:
                await pg.wait_for_timeout(_CAPTURE_WAIT_MS)  # let all cells stream in
            await browser.close()
    except Exception as exc:  # noqa: BLE001
        log.warning("alaw.render_failed", error=str(exc)[:200])
        return ""
    # Prefer the payload with the most cell objects (fullest range).
    if not captured:
        return ""
    return max(captured, key=lambda h: len(_CELL_RE.findall(h)))


class Alaw(BaseScraper):
    """Albertelli Law (ALAW) — NC statewide + SC foreclosure sales (SharePoint embed)."""

    slug = "law_firms.alaw"
    name = "Albertelli Law (ALAW) — NC + SC Foreclosure Sales"
    category = "law_firm"
    timeout_s = 180.0
    # The firm's sheet sits between manual refreshes and can be empty or dated;
    # don't flag a low/zero count as a regression.
    expected_min_count = 0

    async def fetch(self) -> Iterable[Listing]:
        # NC statewide + SC (Upstate is core footprint). Each page is independent:
        # a failure on one must not lose the other, so per-page try/except.
        out: list[Listing] = []
        for url in WP_PAGES:
            try:
                page = await get_text(url, timeout=45.0)
                embed = _discover_embed_url(page)
                if not embed:
                    log.warning("alaw.no_embed_url", page=url)
                    continue
                wac = await _render_capture(embed)
                if not wac:
                    log.warning("alaw.no_wac_capture", page=url)
                    continue
                rows = parse_wac_cells(wac, url)
                log.info("alaw.parsed", page=url, count=len(rows))
                out.extend(rows)
            except Exception as exc:  # noqa: BLE001
                log.warning("alaw.page_failed", page=url, error=str(exc)[:200])
        return out
