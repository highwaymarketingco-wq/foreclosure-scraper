"""Aldridge Pite — NC only. Disclaimer page is bypassed via Referer header.

Currently empty (verified 2026-04-28); the scraper still runs cheaply via httpx
and will start producing results when Aldridge re-populates their listings.
"""
from __future__ import annotations

import re
from datetime import datetime
from typing import Iterable

import httpx
from selectolax.parser import HTMLParser

from ...base_scraper import BaseScraper
from ...http_client import client
from ...models import Listing, ListingType, PropertyKind

LISTINGS_URL = "https://aldridgepite.com/sale-day-listings-selection/foreclosure-listings-north-carolina/"
DISCLAIMER_URL = "https://aldridgepite.com/disclaimer-north-carolina/"


class AldridgePite(BaseScraper):
    slug = "law_firms.aldridge_pite"
    name = "Aldridge Pite"
    category = "law_firm"
    timeout_s = 120.0

    async def fetch(self) -> Iterable[Listing]:
        out: list[Listing] = []
        async with client(timeout=30.0) as c:
            try:
                r = await c.get(
                    LISTINGS_URL,
                    headers={"Referer": DISCLAIMER_URL},
                    follow_redirects=True,
                )
                if r.status_code != 200:
                    return out
                html = r.text
            except httpx.HTTPError:
                return out

        tree = HTMLParser(html)
        table = tree.css_first("table.posts-data-table")
        if not table:
            return out
        for tr in table.css("tbody tr"):
            cells = [td.text(strip=True) for td in tr.css("td")]
            if len(cells) < 8:
                continue
            file_no, addr, city, state, zip_code, county, date_listed, bid_raw = cells[:8]
            if not addr:
                continue
            bid = None
            bm = re.search(r"\$?\s*([\d,]+(?:\.\d{2})?)", bid_raw or "")
            if bm:
                try:
                    bid = float(bm.group(1).replace(",", ""))
                except ValueError:
                    pass
            out.append(
                Listing(
                    source=self.slug,
                    source_url=LISTINGS_URL,
                    listing_type=ListingType.FORECLOSURE_SALE,
                    property_kind=PropertyKind.UNKNOWN,
                    street_address=addr or None,
                    city=city or None,
                    state=(state or "NC").upper(),
                    zip_code=zip_code or None,
                    county=(county or "").replace(" County", "") or None,
                    case_number=file_no or None,
                    opening_bid=bid,
                    description=f"Aldridge Pite NC — file {file_no}",
                    first_seen=datetime.utcnow(),
                    last_seen=datetime.utcnow(),
                )
            )
        return out
