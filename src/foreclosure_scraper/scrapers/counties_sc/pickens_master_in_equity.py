"""Pickens County (SC) Master in Equity foreclosure sales."""
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
    "https://www.pickenscountysc.gov/master-in-equity",
    "https://www.pickenscountysc.gov/master-in-equity/sales-roster",
)


class PickensMasterInEquity(BaseScraper):
    slug = "counties_sc.pickens_master_in_equity"
    name = "Pickens County (SC) Master in Equity"
    category = "county_court"
    timeout_s = 180.0

    async def fetch(self) -> Iterable[Listing]:
        out: list[Listing] = []
        for url in URLS:
            try:
                html = await get_text(url, timeout=45.0)
            except Exception:
                continue
            tree = HTMLParser(html)
            for row in tree.css("table tr"):
                cells = [c.text(strip=True) for c in row.css("td")]
                if len(cells) < 3:
                    continue
                case_num = next((c for c in cells if re.search(r"\d{2,4}-CP-", c)), None)
                if not case_num:
                    continue
                addr = next(
                    (c for c in cells if re.search(r"\d+\s+[A-Z]", c) and len(c) > 8),
                    None,
                )
                date_cell = next(
                    (c for c in cells if re.search(r"\d{1,2}/\d{1,2}/\d{2,4}", c)), None
                )
                sale_date = None
                if date_cell:
                    try:
                        sale_date = dateparser.parse(date_cell)
                    except (ValueError, TypeError):
                        pass
                out.append(
                    Listing(
                        source=self.slug,
                        source_url=url,
                        listing_type=ListingType.FORECLOSURE_SALE,
                        property_kind=PropertyKind.UNKNOWN,
                        street_address=addr,
                        state="SC",
                        county="Pickens",
                        case_number=case_num,
                        plaintiff=cells[1] if len(cells) > 1 else None,
                        defendant=cells[2] if len(cells) > 2 else None,
                        sale_date=sale_date,
                        description=" | ".join(cells)[:500],
                        first_seen=datetime.utcnow(),
                        last_seen=datetime.utcnow(),
                    )
                )
        return out
