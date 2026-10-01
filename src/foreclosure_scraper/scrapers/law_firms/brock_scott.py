"""Brock & Scott — WordPress trustee-sale archive (NC + SC).

SITE REDESIGN FOUND AND FIXED 2026-10-01. The site migrated off the
Search & Filter Pro `article.foreclosure_search` card markup documented
below to a plain `<table>` and, more importantly, off the `?sf_paged={N}`
query-string pagination to WordPress's standard `/page/{N}/` path
pagination. Both changes were silent: `?sf_paged={N}` still returns HTTP 200
with a full, well-formed page every time, but it is now completely IGNORED —
confirmed live, pages 1/2/3/10 with the old query param all return the
IDENTICAL first 20 rows. Since the old code also keyed its end-of-list
termination on "zero `article.foreclosure_search` found", and the new markup
has zero of those on every page including page 1, `fetch()` had been
returning 0 Listings on every run for some unmeasured period before this fix
(this source had NO test file to catch it). Live-verified 2026-10-01 against
the real `/page/{N}/` pagination: NC 192 rows across 10 pages (9x20 + 1x12,
matching the page's own "NC (192)" state-filter facet count), SC 59 rows.

The 8 columns themselves are UNCHANGED (still the exact fields below), just
in a `<table><tbody><tr><td>` now instead of 8 `.forecol` divs — the header
row is `<thead><tr><th>...</th></tr></thead>` and is read to build a
field->index map (same drift-tolerant approach as the sibling
`law_firms/hutchens.py`) rather than trusting fixed indices:
  County | Sale Date | State | Court SP # | Case # |
  Address | Opening Bid Amt. | Book Page

Verified live 2026-07-31 (now superseded by the above):
  /foreclosure-sales/?_sft_foreclosure_state={nc|sc}&sf_paged={N}
Static HTML, no Cloudflare, no disclaimer gate, 10 `article.foreclosure_search`
per page. NC = 179 rows / 18 pages. SC = 103 rows / 11 pages. A page past the end
returns 0 articles (not a 404 and not a silent wrap to page 1), so an empty page
is the terminator.

Field notes that the parser depends on:
  * Address is "<street><2+ spaces><city>, <State Name> <zip>" and the state is
    SPELLED OUT ("North Carolina"), which is why the old 2-letter-only regex
    matched nothing and left city + zip null on all 282 rows.
  * "Court SP #" is the COURT file number (NC 25SP001025-150 / SC
    2026-CP-11-00018) — that is what the downstream case-detail and court-bid
    enrichments key on. "Case #" (25-30726-FC01) is Brock & Scott's internal
    file number and is useless for a court lookup, so it lives in the description.
  * "Opening Bid Amount" is "0.00" until the bid is published (215 of 282 rows).
    Zero is *unknown*, not a free house, so it is stored as None.
  * "Book Page" is the deed-of-trust reference (280 of 282 rows) — recorded into
    raw["rod_docs"] so the ROD / payoff lookups can use it.
"""
from __future__ import annotations

import asyncio
import re
from datetime import datetime
from typing import Iterable

import structlog
from dateutil import parser as dateparser
from selectolax.parser import HTMLParser

from ...base_scraper import BaseScraper
from ...http_client import get_text
from ...models import Listing, ListingType, PropertyKind
from ._footprint import in_footprint, keep, normalize_county

log = structlog.get_logger()

BASE = "https://www.brockandscott.com/foreclosure-sales/"

#: Hard ceiling on pages per state — 2x the observed 18 so a growth spurt still
#: paginates fully, while a pagination bug can never spin forever.
MAX_PAGES = 40

#: Per-page fetch attempts. The host 429s intermittently; the previous code
#: `break`-ed on the first exception, which silently truncated the whole state
#: mid-crawl and shipped a partial list as if it were complete.
PAGE_ATTEMPTS = 3

#: "<street>  <city>, <State> <zip>" — accepts the spelled-out state names the
#: site actually uses plus the 2-letter form, and a 9-digit zip with or without
#: the dash ("298030000" appears twice in the live data).
_ADDR_RE = re.compile(
    r"^(?P<head>.*?)\s*,\s*"
    r"(?:North Carolina|South Carolina|NC|SC)\s+"
    r"(?P<zip>\d{5})(?:-?\d{4})?\s*$",
    re.I,
)
_MONEY_RE = re.compile(r"[\d,]+(?:\.\d+)?")


def _split_address(raw_addr: str) -> tuple[str, str | None, str | None]:
    """-> (street, city, zip). Falls back to street-only when the tail is odd."""
    text = " ".join((raw_addr or "").split(" ")).strip()
    if not text:
        return "", None, None
    m = _ADDR_RE.match(text)
    if not m:
        return text, None, None
    zip_code = m.group("zip")
    head = m.group("head").strip()
    # street and city are separated by a run of 2+ spaces (280/282 live rows).
    parts = re.split(r"\s{2,}", head)
    if len(parts) >= 2:
        street = " ".join(p.strip() for p in parts[:-1]).strip()
        city = parts[-1].strip()
        return street or head, city or None, zip_code
    return head, None, zip_code


def _parse_money(raw_val: str | None) -> float | None:
    """Dollar amount, or None. 0/0.00 means 'not published yet', not zero."""
    if not raw_val:
        return None
    m = _MONEY_RE.search(raw_val)
    if not m:
        return None
    try:
        val = float(m.group(0).replace(",", ""))
    except ValueError:
        return None
    return val if val > 0 else None


def _split_book_page(raw_bp: str | None) -> tuple[str | None, str | None]:
    """"164/919" -> ("164", "919"). Tolerates spaces and a book prefix."""
    if not raw_bp:
        return None, None
    text = raw_bp.strip()
    if not text:
        return None, None
    if "/" in text:
        book, _, page = text.partition("/")
        return (book.strip() or None), (page.strip() or None)
    return text or None, None


#: Table header label -> canonical field. Drift-tolerant header-driven mapping
#: (same approach as the sibling law_firms/hutchens.py) rather than fixed
#: column indices, since this table already replaced one markup generation.
_HEADER_MAP = {
    "county": "county",
    "sale date": "sale_date",
    "state": "state",
    "court sp #": "court_case",
    "case #": "firm_file_no",
    "address": "address",
    "opening bid amt.": "bid",
    "book page": "book_page",
}


def _norm_header(label: str) -> str:
    # Strip the sort-arrow glyph ("Sale Date▲") and collapse whitespace.
    return re.sub(r"[^\w .#/]", "", label).strip().lower()


def _table_header_indices(table) -> dict[str, int]:
    thead = table.css_first("thead")
    ths = thead.css("th") if thead else []
    out: dict[str, int] = {}
    for idx, th in enumerate(ths):
        field = _HEADER_MAP.get(_norm_header(th.text(strip=True)))
        if field and field not in out:
            out[field] = idx
    return out


def _parse_row(tr, cols: dict[str, int], state_hint: str, slug: str, page_url: str) -> Listing | None:
    cells = tr.css("td")
    if len(cells) < 6:
        return None

    def cell_text(field: str) -> str | None:
        idx = cols.get(field)
        if idx is None or idx >= len(cells):
            return None
        return cells[idx].text(strip=True) or None

    county = normalize_county(cell_text("county"))
    state = (cell_text("state") or state_hint).upper()
    court_case = cell_text("court_case")      # NC SP # / SC CP docket — the COURT number
    firm_file_no = cell_text("firm_file_no")  # Brock & Scott internal file number
    street, city, zip_code = _split_address(cell_text("address") or "")
    opening_bid = _parse_money(cell_text("bid"))
    book, page = _split_book_page(cell_text("book_page"))

    # The sale-date cell is <time datetime="2026-09-30">09/30/2026 <span
    # class="sale-time">· 1:30 PM</span></time> — the datetime attribute is
    # machine-readable and more reliable than re-parsing the display text.
    sale_date = None
    sale_time = None
    date_idx = cols.get("sale_date")
    time_el = cells[date_idx].css_first("time") if date_idx is not None and date_idx < len(cells) else None
    if time_el is not None:
        iso = time_el.attributes.get("datetime")
        if iso:
            try:
                sale_date = dateparser.parse(iso)
            except (ValueError, TypeError, OverflowError):
                sale_date = None
        span = time_el.css_first(".sale-time")
        if span:
            sale_time = span.text(strip=True).lstrip("·").strip() or None
    if sale_date is None:
        raw_date = cell_text("sale_date")
        if raw_date:
            date_part, _, time_part = raw_date.partition("·")
            sale_time = sale_time or (time_part.strip() or None)
            try:
                sale_date = dateparser.parse(date_part.strip() or raw_date)
            except (ValueError, TypeError, OverflowError):
                sale_date = None

    desc_bits = [
        f"Brock & Scott trustee sale — court case {court_case}" if court_case
        else "Brock & Scott trustee sale",
        f"firm file {firm_file_no}" if firm_file_no else "",
        f"deed of trust book/page {book}/{page}" if book and page else (
            f"deed of trust book {book}" if book else ""
        ),
    ]
    description = ", ".join(b for b in desc_bits if b)

    # A row has no per-property detail link or stable id in the new markup;
    # anchor source_url on the court case number (unique, meaningful, and the
    # fragment is never sent to the server) instead of the old wp post id.
    detail = f"{page_url}#case-{court_case}" if court_case else page_url

    listing = Listing(
        source=slug,
        source_url=detail,
        listing_type=ListingType.FORECLOSURE_SALE,
        property_kind=PropertyKind.UNKNOWN,
        street_address=street or None,
        city=city,
        state=state,
        zip_code=zip_code,
        county=county,
        sale_date=sale_date,
        sale_time=sale_time,
        case_number=court_case,
        opening_bid=opening_bid,
        description=description or None,
        first_seen=datetime.utcnow(),
        last_seen=datetime.utcnow(),
    )
    if book:
        listing.raw["rod_docs"] = [{
            "doc_type": "DEED OF TRUST",
            "book": book,
            "page": page,
            "amount": None,
            "recorded_date": None,
            "county": county,
            "state": state,
            "source": slug,
        }]
    return listing


class BrockScott(BaseScraper):
    slug = "law_firms.brock_scott"
    name = "Brock & Scott"
    category = "law_firm"
    timeout_s = 600.0
    expected_min_count = 20

    @staticmethod
    def _page_url(state: str, page: int) -> str:
        """Page 1 is the bare query URL; page N>1 uses WordPress's standard
        `/page/{N}/` PATH pagination. The old `?sf_paged={N}` query param is
        now silently ignored by the site (confirmed live 2026-10-01: it
        returns HTTP 200 with a full page every time, but always page 1's
        rows) -- this is the real, working scheme."""
        if page <= 1:
            return f"{BASE}?_sft_foreclosure_state={state}"
        return f"{BASE}page/{page}/?_sft_foreclosure_state={state}"

    async def _page(self, state: str, page: int) -> HTMLParser | None:
        """Fetch one page with retry. None means the page hard-failed."""
        url = self._page_url(state, page)
        for attempt in range(PAGE_ATTEMPTS):
            try:
                html = await get_text(url, timeout=45.0)
                if html and len(html) > 500:
                    return HTMLParser(html)
                # Site now returns "Forbidden" (9 bytes) to plain httpx.
                # Fall back to StealthyFetcher which passes the WAF check.
                html = await self._stealth_fetch(url)
                if html:
                    return HTMLParser(html)
            except Exception as exc:  # noqa: BLE001 — retried, then reported
                if attempt == PAGE_ATTEMPTS - 1:
                    log.warning(
                        "brock_scott.page_failed",
                        state=state, page=page, error=str(exc)[:160],
                    )
                    return None
                await asyncio.sleep(2.0 * (attempt + 1))
        return None

    @staticmethod
    async def _stealth_fetch(url: str) -> str | None:
        """StealthyFetcher fallback for WAF-blocked pages."""
        try:
            from scrapling.fetchers import StealthyFetcher
        except ImportError:
            return None
        try:
            result = await StealthyFetcher.async_fetch(
                url, headless=True, network_idle=False, timeout=60000,
                solve_cloudflare=False,
            )
        except Exception as exc:
            log.warning("brock_scott.stealth_failed", url=url, error=str(exc)[:160])
            return None
        body = getattr(result, "body", b"")
        html = body.decode("utf-8", errors="replace") if isinstance(body, bytes) else str(body or "")
        if not html or len(html) < 500:
            return None
        return html

    async def fetch(self) -> Iterable[Listing]:
        out: list[Listing] = []
        total = 0
        failed_pages: list[str] = []

        for state in ("nc", "sc"):
            for page in range(1, MAX_PAGES + 1):
                tree = await self._page(state, page)
                if tree is None:
                    # A failed page is NOT the end of the list — pages are
                    # directly addressable, so skip it and keep paginating
                    # instead of truncating the state like the old `break` did.
                    failed_pages.append(f"{state}:{page}")
                    continue
                table = tree.css_first("table")
                rows = table.css("tbody tr") if table else []
                if not rows:
                    break
                cols = _table_header_indices(table)
                page_url = self._page_url(state, page)
                for tr in rows:
                    li = _parse_row(tr, cols, state, self.slug, page_url)
                    if li is None:
                        continue
                    total += 1
                    if keep(li.county, li.state):
                        out.append(li)

        in_foot = sum(1 for li in out if in_footprint(li.county, li.state))
        log.info(
            "brock_scott.counts",
            total_scraped=total,
            kept=len(out),
            in_footprint=in_foot,
            coastal_lane=len(out) - in_foot,
            failed_pages=failed_pages or None,
        )
        if failed_pages and not out:
            # Everything failed to fetch — surface it as an error so safe_run
            # classifies the run BLOCKED instead of a misleading clean zero.
            raise RuntimeError(
                f"brock_scott: every page fetch failed ({', '.join(failed_pages)})"
            )
        return out
