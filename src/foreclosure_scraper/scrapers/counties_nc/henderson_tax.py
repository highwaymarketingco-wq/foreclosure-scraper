"""Henderson NC tax foreclosure sales — county Tax Office.

Cleanest of the four NC tax-foreclosure pages. Single HTML <table> with rows of:
   [Owner, Parcel #, Description, Clerk File #, Opening Bid]
Sale date is shown above the table as a single date for the whole batch
("May 27, 2026 at 10:00am" on courthouse steps, 200 N Grove St, Hendersonville).
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

URL = "https://www.hendersoncountync.gov/tax/page/tax-foreclosure-sales"
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9",
    "Accept-Language": "en-US,en;q=0.9",
}

DATE_RE = re.compile(
    r"((?:January|February|March|April|May|June|July|August|September|October|November|December)"
    r"\s+\d{1,2},?\s+\d{4}(?:\s+at\s+\d{1,2}(?::\d{2})?\s*(?:am|pm))?)", re.I)
LOCATION_RE = re.compile(r"(\d+\s+[A-Z][\w .'\-]+,\s*[A-Z][\w .'\-]+,?\s*NC[\w\s]*)", re.I)


class HendersonTaxForeclosure(BaseScraper):
    slug = "counties_nc.henderson_tax"
    name = "Henderson NC Tax Foreclosure Sales"
    category = "county_tax"
    expected_min_count = 5
    timeout_s = 60.0

    async def fetch(self) -> Iterable[Listing]:
        async with client(timeout=20.0) as c:
            r = await c.get(URL, headers=HEADERS)
            if r.status_code != 200:
                return []
            html = r.text

        # Sale date + location parsed once for all rows
        sale_date = None
        sale_location = None
        m = DATE_RE.search(html)
        if m:
            try:
                sale_date = dateparser.parse(m.group(1), fuzzy=True)
            except (ValueError, TypeError):
                pass
        loc = LOCATION_RE.search(html)
        if loc:
            sale_location = loc.group(1)

        tree = HTMLParser(html)
        out: list[Listing] = []
        seen_files: set[str] = set()
        for row in tree.css("tr"):
            # Henderson uses <th> for ALL data cells (not <td>); fall back to td if needed
            cells = row.css("th") or row.css("td")
            if len(cells) < 5:
                continue
            owner = (cells[0].text() or "").strip()
            parcel = (cells[1].text() or "").strip()
            description = (cells[2].text() or "").strip()
            file_no = (cells[3].text() or "").strip()
            bid_str = (cells[4].text() or "").strip()
            # Skip header rows + empty
            if not parcel or parcel.lower() in {"parcel #", "parcel"}:
                continue
            if not re.match(r"\d{4,}", parcel):
                continue
            # Drop dupes
            key = (file_no or parcel)
            if key in seen_files:
                continue
            seen_files.add(key)

            opening_bid = None
            bid_m = re.search(r"\$([\d,]+(?:\.\d{2})?)", bid_str)
            if bid_m:
                try:
                    opening_bid = float(bid_m.group(1).replace(",", ""))
                except ValueError:
                    pass

            out.append(
                Listing(
                    source=self.slug,
                    source_url=URL,
                    listing_type=ListingType.TAX_SALE,
                    property_kind=PropertyKind.UNKNOWN,
                    state="NC",
                    county="Henderson",
                    parcel_id=parcel,
                    sale_date=sale_date,
                    sale_location=sale_location,
                    opening_bid=opening_bid,
                    defendant=owner,
                    case_number=file_no or None,
                    description=description[:500] or None,
                    first_seen=datetime.utcnow(),
                    last_seen=datetime.utcnow(),
                    raw={"henderson_tax": {"owner": owner, "description": description, "bid": bid_str}},
                )
            )
        return out
