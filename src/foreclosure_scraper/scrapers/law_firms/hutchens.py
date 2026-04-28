"""Hutchens Law Firm — sales.hutchenslawfirm.com publishes upcoming foreclosure sales
in two ASP.NET GridViews (NC + SC). This is the highest-volume Carolinas source.
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

URLS = (
    ("https://sales.hutchenslawfirm.com/NCfcSalesList.aspx", "NC"),
    ("https://sales.hutchenslawfirm.com/SCfcSalesList.aspx", "SC"),
)


def _f(cells: list[str], i: int) -> str | None:
    return cells[i].strip() if i < len(cells) and cells[i].strip() else None


class Hutchens(BaseScraper):
    slug = "law_firms.hutchens"
    name = "Hutchens Law Firm"
    category = "law_firm"
    timeout_s = 180.0

    async def fetch(self) -> Iterable[Listing]:
        out: list[Listing] = []
        for url, state in URLS:
            try:
                html = await get_text(url, timeout=45.0)
            except Exception:
                continue
            tree = HTMLParser(html)
            # The grid lives in a table whose id contains "SalesListGrid"
            grid = tree.css_first("table[id*='SalesListGrid']") or tree.css_first("#SalesListGrid")
            if not grid:
                continue
            rows = grid.css("tr")
            for row in rows[1:]:  # skip header
                cells = [c.text(strip=True) for c in row.css("td")]
                if len(cells) < 6:
                    continue
                # Columns observed: Case No | SP# | County | Sale Date | Address | City/State/Zip | Book/Page | Bid Amount
                case = _f(cells, 0)
                sp = _f(cells, 1)
                county = _f(cells, 2)
                date_raw = _f(cells, 3)
                addr = _f(cells, 4)
                cityzip = _f(cells, 5) or ""
                book = _f(cells, 6)
                bid_raw = _f(cells, 7) or ""
                # Hutchens sometimes writes "Gaston, NC" in the county column — strip state suffix
                if county:
                    county = county.replace(" County", "").strip()
                    for sfx in (", NC", ", SC", ",NC", ",SC"):
                        if county.upper().endswith(sfx):
                            county = county[: -len(sfx)].strip()
                    county = county.split(",")[0].strip()

                if not case and not addr:
                    continue
                sale_date = None
                if date_raw:
                    try:
                        sale_date = dateparser.parse(date_raw)
                    except (ValueError, TypeError):
                        pass

                # Parse "Charlotte, NC 28202" → city, zip
                city = None
                zip_code = None
                m = re.match(r"^([A-Za-z .'-]+),\s*([A-Z]{2})\s+(\d{5})", cityzip)
                if m:
                    city = m.group(1)
                    zip_code = m.group(3)

                bid = None
                bm = re.search(r"\$?\s*([\d,]+(?:\.\d{2})?)", bid_raw)
                if bm:
                    try:
                        bid = float(bm.group(1).replace(",", ""))
                    except ValueError:
                        pass

                out.append(
                    Listing(
                        source=self.slug,
                        source_url=url,
                        listing_type=ListingType.FORECLOSURE_SALE,
                        property_kind=PropertyKind.UNKNOWN,
                        street_address=addr,
                        city=city,
                        state=state,
                        zip_code=zip_code,
                        county=(county or "").replace(" County", "") or None,
                        sale_date=sale_date,
                        case_number=case,
                        opening_bid=bid,
                        description=f"Hutchens trustee sale — SP# {sp or '?'}, Book/Page {book or '?'}",
                        first_seen=datetime.utcnow(),
                        last_seen=datetime.utcnow(),
                    )
                )
        return out
