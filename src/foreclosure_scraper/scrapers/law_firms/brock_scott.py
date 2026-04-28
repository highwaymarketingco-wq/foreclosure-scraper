"""Brock & Scott — search-foreclosure-sales endpoint. Uses a POST form with state filter.

We try a GET first (some installs accept query params) then fall back to POST.
"""
from __future__ import annotations

import re
from datetime import datetime
from typing import Iterable

from dateutil import parser as dateparser
from selectolax.parser import HTMLParser

from ...base_scraper import BaseScraper
from ...http_client import client
from ...models import Listing, ListingType, PropertyKind

SEARCH_URL = "https://www.brockandscott.com/search-foreclosure-sales/"


def _parse_grid(html: str, state: str, source_slug: str, source_url: str) -> list[Listing]:
    out: list[Listing] = []
    tree = HTMLParser(html)
    table = tree.css_first("table.foreclosure-sales, table.sales-table, table#salesTable") or tree.css_first("table")
    if not table:
        return out
    headers = [h.text(strip=True).lower() for h in table.css("th")]
    # Find column indices by header text
    def idx(*candidates: str) -> int | None:
        for c in candidates:
            for i, h in enumerate(headers):
                if c in h:
                    return i
        return None

    i_case = idx("case")
    i_county = idx("county")
    i_date = idx("sale date", "sale")
    i_addr = idx("address", "property")
    i_bid = idx("opening", "bid")
    i_book = idx("book", "page")

    for row in table.css("tr")[1:]:
        cells = [c.text(strip=True) for c in row.css("td")]
        if len(cells) < 4:
            continue
        case = cells[i_case] if i_case is not None and i_case < len(cells) else None
        county = cells[i_county] if i_county is not None and i_county < len(cells) else None
        addr = cells[i_addr] if i_addr is not None and i_addr < len(cells) else None
        date_raw = cells[i_date] if i_date is not None and i_date < len(cells) else None
        bid_raw = cells[i_bid] if i_bid is not None and i_bid < len(cells) else None

        if not case and not addr:
            continue
        sale_date = None
        if date_raw:
            try:
                sale_date = dateparser.parse(date_raw)
            except (ValueError, TypeError):
                pass
        bid = None
        if bid_raw:
            m = re.search(r"\$?\s*([\d,]+(?:\.\d{2})?)", bid_raw)
            if m:
                try:
                    bid = float(m.group(1).replace(",", ""))
                except ValueError:
                    pass

        out.append(
            Listing(
                source=source_slug,
                source_url=source_url,
                listing_type=ListingType.FORECLOSURE_SALE,
                property_kind=PropertyKind.UNKNOWN,
                street_address=addr,
                state=state,
                county=(county or "").replace(" County", "") or None,
                sale_date=sale_date,
                case_number=case,
                opening_bid=bid,
                description=f"Brock & Scott trustee sale ({state})",
                first_seen=datetime.utcnow(),
                last_seen=datetime.utcnow(),
            )
        )
    return out


class BrockScott(BaseScraper):
    slug = "law_firms.brock_scott"
    name = "Brock & Scott"
    category = "law_firm"
    timeout_s = 180.0

    async def fetch(self) -> Iterable[Listing]:
        out: list[Listing] = []
        async with client(timeout=45.0) as c:
            for state in ("NC", "SC"):
                # Try GET with query string first
                try:
                    r = await c.get(SEARCH_URL, params={"state": state, "search_state": state})
                    html = r.text if r.status_code < 400 else ""
                except Exception:
                    html = ""
                listings = _parse_grid(html, state, self.slug, SEARCH_URL) if html else []

                # Fall back to form POST
                if not listings:
                    try:
                        r = await c.post(
                            SEARCH_URL,
                            data={"state": state, "search_state": state, "submit": "Search"},
                        )
                        if r.status_code < 400:
                            listings = _parse_grid(r.text, state, self.slug, SEARCH_URL)
                    except Exception:
                        pass

                out.extend(listings)
        return out
