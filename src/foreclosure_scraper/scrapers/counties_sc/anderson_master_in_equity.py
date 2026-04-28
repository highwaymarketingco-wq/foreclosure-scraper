"""Anderson County (SC) Master in Equity — only upcoming sales.

The county's MIE page archives every month from 2020 forward; we must filter
strictly to today/forward, otherwise we flood the sheet with historic rosters.
"""
from __future__ import annotations

import re
from datetime import datetime, timedelta
from typing import Iterable

from dateutil import parser as dateparser
from selectolax.parser import HTMLParser

from ...base_scraper import BaseScraper
from ...http_client import get_text
from ...models import Listing, ListingType, PropertyKind

URLS = (
    "https://www.andersoncountysc.org/master-in-equity/",
    "https://www.andersoncountysc.org/master-in-equity/sales-roster/",
    "https://www.andersoncountysc.org/master-in-equity/upcoming-sales/",
)


class AndersonMasterInEquity(BaseScraper):
    slug = "counties_sc.anderson_master_in_equity"
    name = "Anderson County (SC) Master in Equity"
    category = "county_court"
    timeout_s = 180.0

    async def fetch(self) -> Iterable[Listing]:
        out: list[Listing] = []
        today = datetime.utcnow()
        horizon = today + timedelta(days=120)
        cutoff = today - timedelta(days=2)

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
                # Find a date cell
                date_cell = next(
                    (c for c in cells if re.search(r"\d{1,2}/\d{1,2}/\d{2,4}|\d{4}-\d{2}-\d{2}", c)),
                    None,
                )
                if not date_cell:
                    continue  # require a date — drop historic rosters with no parseable date
                try:
                    sale_date = dateparser.parse(date_cell)
                except (ValueError, TypeError):
                    continue
                if not (cutoff <= sale_date <= horizon):
                    continue  # active-only

                addr = next(
                    (c for c in cells if re.search(r"\d+\s+[A-Z]", c) and len(c) > 8),
                    None,
                )
                out.append(
                    Listing(
                        source=self.slug,
                        source_url=url,
                        listing_type=ListingType.FORECLOSURE_SALE,
                        property_kind=PropertyKind.UNKNOWN,
                        street_address=addr,
                        state="SC",
                        county="Anderson",
                        case_number=case_num,
                        plaintiff=cells[1] if len(cells) > 1 else None,
                        defendant=cells[2] if len(cells) > 2 else None,
                        sale_date=sale_date,
                        description=" | ".join(cells)[:500],
                        first_seen=datetime.utcnow(),
                        last_seen=datetime.utcnow(),
                    )
                )
            # Also surface any PDF link that looks like an upcoming sales roster
            for a in tree.css("a[href$='.pdf']"):
                href = a.attributes.get("href", "")
                label = (a.text(strip=True) or "").lower()
                if not any(k in label for k in ("sales roster", "upcoming", "scheduled")):
                    continue
                full = href if href.startswith("http") else "https://www.andersoncountysc.org" + href
                out.append(
                    Listing(
                        source=self.slug,
                        source_url=full,
                        listing_type=ListingType.FORECLOSURE_SALE,
                        property_kind=PropertyKind.UNKNOWN,
                        state="SC",
                        county="Anderson",
                        description=label[:300] or "Anderson upcoming sales roster (PDF)",
                        first_seen=datetime.utcnow(),
                        last_seen=datetime.utcnow(),
                    )
                )
        return out
