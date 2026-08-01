"""Brock & Scott — WordPress + Search & Filter Pro trustee-sale archive (NC + SC).

Verified live 2026-07-31:
  /foreclosure-sales/?_sft_foreclosure_state={nc|sc}&sf_paged={N}
Static HTML, no Cloudflare, no disclaimer gate, 10 `article.foreclosure_search`
per page. NC = 179 rows / 18 pages. SC = 103 rows / 11 pages. A page past the end
returns 0 articles (not a 404 and not a silent wrap to page 1), so an empty page
is the terminator.

Each article carries 8 `.forecol` cells, each a label <p> + value <p>:
  0 County | 1 Sale Date | 2 State | 3 Court SP # | 4 Case # |
  5 Address | 6 Opening Bid Amount | 7 Book Page

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


def _parse_article(art, state_hint: str, slug: str) -> Listing | None:
    # State + county come from the article's class attribute, which is more
    # reliable than the cell text (it is what the site's own filter keys on).
    cls = art.attributes.get("class", "")
    county_m = re.search(r"foreclosure_county-([a-z0-9\-]+)", cls)
    state_m = re.search(r"foreclosure_state-([a-z]{2})", cls)
    post_m = re.search(r"post-(\d+)", cls)
    county = normalize_county(county_m.group(1).replace("-", " ")) if county_m else None
    state = (state_m.group(1) if state_m else state_hint).upper()

    cols = art.css(".forecol")
    if len(cols) < 6:
        return None

    def col_value(idx: int) -> str | None:
        if idx >= len(cols):
            return None
        ps = cols[idx].css("p")
        if len(ps) >= 2:
            return ps[1].text(strip=True) or None
        return (ps[0].text(strip=True) or None) if ps else None

    if county is None:
        county = normalize_county(col_value(0))

    sale_date_raw = col_value(1)
    court_case = col_value(3)      # NC SP # / SC CP docket — the COURT number
    firm_file_no = col_value(4)    # Brock & Scott internal file number
    street, city, zip_code = _split_address(col_value(5) or "")
    opening_bid = _parse_money(col_value(6))
    book, page = _split_book_page(col_value(7))

    sale_date = None
    sale_time = None
    if sale_date_raw:
        # "07/30/2026 - 02:00:00 PM"
        date_part, _, time_part = sale_date_raw.partition(" - ")
        sale_time = time_part.strip() or None
        try:
            sale_date = dateparser.parse(date_part.strip() or sale_date_raw)
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

    # A row has no per-property detail link, so anchor source_url on the post id
    # to keep it unique + stable (the fragment is never sent to the server).
    detail = f"{BASE}?_sft_foreclosure_state={state.lower()}"
    if post_m:
        detail = f"{detail}#post-{post_m.group(1)}"

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

    async def _page(self, state: str, page: int) -> HTMLParser | None:
        """Fetch one page with retry. None means the page hard-failed."""
        url = f"{BASE}?_sft_foreclosure_state={state}&sf_paged={page}"
        for attempt in range(PAGE_ATTEMPTS):
            try:
                return HTMLParser(await get_text(url, timeout=45.0))
            except Exception as exc:  # noqa: BLE001 — retried, then reported
                if attempt == PAGE_ATTEMPTS - 1:
                    log.warning(
                        "brock_scott.page_failed",
                        state=state, page=page, error=str(exc)[:160],
                    )
                    return None
                await asyncio.sleep(2.0 * (attempt + 1))
        return None

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
                articles = tree.css("article.foreclosure_search")
                if not articles:
                    break
                for art in articles:
                    li = _parse_article(art, state, self.slug)
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
