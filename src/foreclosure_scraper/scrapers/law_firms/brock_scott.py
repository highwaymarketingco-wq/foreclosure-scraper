"""Brock & Scott — fully scrapeable WordPress + Search & Filter Pro archive.

Verified URL: /foreclosure-sales/?_sft_foreclosure_state={nc|sc}&sf_paged={N}
Static HTML, no Cloudflare, no disclaimer, ~10 articles per page.
NC: 229 listings / 23 pages.  SC: 115 listings / 12 pages.
"""
from __future__ import annotations

import re
from datetime import datetime
from typing import Iterable

from dateutil import parser as dateparser
from selectolax.parser import HTMLParser

from ...base_scraper import BaseScraper
from ...http_client import get_text
from ...models import Listing, ListingType, PropertyKind

BASE = "https://www.brockandscott.com/foreclosure-sales/"


def _parse_article(art, state: str, slug: str) -> Listing | None:
    # Pull state + county from the article class attribute (more robust than text)
    cls = art.attributes.get("class", "")
    county_m = re.search(r"foreclosure_county-([a-z\-]+)", cls)
    state_m = re.search(r"foreclosure_state-([a-z]{2})", cls)
    county = county_m.group(1).replace("-", " ").title() if county_m else None
    real_state = (state_m.group(1) if state_m else state).upper()

    # Each .forecol has two <p>: label, value
    cols = art.css(".forecol")
    if len(cols) < 6:
        return None

    def col_value(idx: int) -> str | None:
        if idx >= len(cols):
            return None
        ps = cols[idx].css("p")
        if len(ps) >= 2:
            return ps[1].text(strip=True) or None
        return ps[0].text(strip=True) or None if ps else None

    # Column order: County | Sale Date | State | Court SP # | Case # | Address | Opening Bid | Book/Page
    sale_date_raw = col_value(1)
    sp_num = col_value(3)
    case_num = col_value(4)
    addr_raw = col_value(5) or ""
    bid_raw = col_value(6)
    book_page = col_value(7)

    # Address is "<street> <city>, <state> <zip>"
    street = addr_raw
    city = None
    zip_code = None
    m = re.match(r"^(.+?)\s+([A-Za-z .'-]+),\s*([A-Z]{2})\s+(\d{5})", addr_raw)
    if m:
        street = m.group(1).strip()
        city = m.group(2).strip()
        zip_code = m.group(4).strip()

    sale_date = None
    if sale_date_raw:
        try:
            sale_date = dateparser.parse(sale_date_raw)
        except (ValueError, TypeError):
            pass

    bid = None
    if bid_raw:
        bm = re.search(r"\$?\s*([\d,]+(?:\.\d{2})?)", bid_raw)
        if bm:
            try:
                bid = float(bm.group(1).replace(",", ""))
            except ValueError:
                pass

    # Detail URL (if linked)
    a = art.css_first("a[href*='/foreclosure-sale/']")
    detail = a.attributes.get("href") if a else BASE

    desc_bits = [
        f"SP# {sp_num}" if sp_num else "",
        f"Book/Page {book_page}" if book_page else "",
    ]
    description = " | ".join(b for b in desc_bits if b) or None

    return Listing(
        source=slug,
        source_url=detail,
        listing_type=ListingType.FORECLOSURE_SALE,
        property_kind=PropertyKind.UNKNOWN,
        street_address=street,
        city=city,
        state=real_state,
        zip_code=zip_code,
        county=county,
        sale_date=sale_date,
        case_number=case_num,
        opening_bid=bid,
        description=description,
        first_seen=datetime.utcnow(),
        last_seen=datetime.utcnow(),
    )


class BrockScott(BaseScraper):
    slug = "law_firms.brock_scott"
    name = "Brock & Scott"
    category = "law_firm"
    timeout_s = 360.0

    async def fetch(self) -> Iterable[Listing]:
        out: list[Listing] = []
        for state in ("nc", "sc"):
            for page in range(1, 30):
                url = f"{BASE}?_sft_foreclosure_state={state}&sf_paged={page}"
                try:
                    html = await get_text(url, timeout=30.0)
                except Exception:
                    break
                tree = HTMLParser(html)
                articles = tree.css("article.foreclosure_search")
                if not articles:
                    break
                for art in articles:
                    li = _parse_article(art, state, self.slug)
                    if li:
                        out.append(li)
        return out
