"""Polk NC tax foreclosure auction — published by Kania Law Firm via county page.

Smallest of the four NC pages — only PARCEL + OPENING BID per row.
No address, no case#, no plaintiff/defendant.
Sale date sits in a header block ("Upcoming Auction Date: March 10th, 2026").
Address must be enriched from Polk GIS by parcel ID.
"""
from __future__ import annotations

import re
from datetime import datetime
from typing import Iterable

from dateutil import parser as dateparser

from ...base_scraper import BaseScraper
from ...http_client import client
from ...models import Listing, ListingType, PropertyKind

URL = "https://www.polknc.gov/upcoming_auction.php"
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9",
}

_TAG = re.compile(r"<[^>]+>")
_WS = re.compile(r"\s+")
_ENTITIES = re.compile(r"&(?:nbsp|amp|lt|gt|times);")
DATE_RE = re.compile(
    r"Upcoming Auction Date[:\s]*([A-Z][a-z]+\s+\d{1,2}(?:st|nd|rd|th)?,?\s+\d{4})", re.I
)
TIME_RE = re.compile(r"(\d{1,2}\s*(?:AM|PM|a\.?m\.?|p\.?m\.?))", re.I)
LOCATION_RE = re.compile(r"Location[:\s]*([^A]+(?:Courthouse|Court House)[^$]+?)(?:The|PARCEL)", re.I | re.S)
# Each row: <parcel> <whitespace incl. nbsp>* $<amount>
# Polk's HTML uses `&nbsp;` between parcel and price; selectolax/regex strip it but
# they may collapse to non-breaking-space chars. Match any non-$ chars between.
ROW_RE = re.compile(r"([A-Z]?\d+(?:-[A-Z]?\d+)+)[^\$]{1,40}\$([\d,]+(?:\.\d{2})?)")


class PolkTaxAuction(BaseScraper):
    slug = "counties_nc.polk_tax"
    name = "Polk NC Tax Auction (Kania Law Firm)"
    category = "county_tax"
    expected_min_count = 1
    timeout_s = 30.0

    async def fetch(self) -> Iterable[Listing]:
        async with client(timeout=20.0) as c:
            r = await c.get(URL, headers=HEADERS)
            if r.status_code != 200:
                return []
            html = r.text

        # Strip tags + decode common HTML entities (Polk page is full of `&nbsp;`)
        flat = _ENTITIES.sub(" ", _TAG.sub(" ", html))
        flat = _WS.sub(" ", flat)
        sale_date = None
        date_m = DATE_RE.search(flat)
        if date_m:
            try:
                # strip "th"/"nd"/"st"/"rd" before parse
                clean = re.sub(r"(\d+)(st|nd|rd|th)", r"\1", date_m.group(1))
                sale_date = dateparser.parse(clean)
            except (ValueError, TypeError):
                pass
        loc_m = LOCATION_RE.search(flat)
        sale_location = loc_m.group(1).strip() if loc_m else "Polk County Courthouse, 1 Courthouse St., Columbus NC"

        out: list[Listing] = []
        seen: set[str] = set()
        for m in ROW_RE.finditer(flat):
            parcel = m.group(1).strip()
            if parcel in seen or len(parcel) < 4:
                continue
            seen.add(parcel)
            try:
                bid = float(m.group(2).replace(",", ""))
            except ValueError:
                bid = None
            out.append(
                Listing(
                    source=self.slug,
                    source_url=URL,
                    listing_type=ListingType.TAX_SALE,
                    property_kind=PropertyKind.UNKNOWN,
                    state="NC",
                    county="Polk",
                    parcel_id=parcel,
                    sale_date=sale_date,
                    sale_location=sale_location,
                    opening_bid=bid,
                    description=f"Polk County tax auction parcel {parcel} (Kania Law Firm)",
                    first_seen=datetime.utcnow(),
                    last_seen=datetime.utcnow(),
                    raw={"polk_tax": {"parcel": parcel, "opening_bid": bid}},
                )
            )
        return out
