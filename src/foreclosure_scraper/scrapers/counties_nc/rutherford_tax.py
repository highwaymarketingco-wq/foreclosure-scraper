"""Rutherford NC tax foreclosure sales — Revenue Department.

Page is a long HTML stream with <strong> blocks separated by `***...` lines.
Each block has:
  Parcel: <id>; <acres> acres
  FILE # WITH CLERK OF COURT: <case#>
  <address>
  Current Bid: $<n> / Minimum upset bid: $<n> / Last day to upset: <date>
"""
from __future__ import annotations

import re
from datetime import datetime
from typing import Iterable

from dateutil import parser as dateparser

from ...base_scraper import BaseScraper
from ...http_client import client
from ...models import Listing, ListingType, PropertyKind

URL = "https://www.rutherfordcountync.gov/departments/revenue_department_tax_administrator/foreclosure_sale_dates.php"
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9",
}

# Strip HTML tags + collapse whitespace for flat text parsing
_TAG = re.compile(r"<[^>]+>")
_WS = re.compile(r"\s+")
SEPARATOR = re.compile(r"\*{20,}")
PARCEL_RE = re.compile(r"Parcel(?:\(s\))?:\s*([\d,;\s\-/.]+(?:ac)?)", re.I)
# NC Clerk of Court "Special Proceeding" file pattern: 23 M 258 (year + M + sequence)
FILE_RE = re.compile(r"FILE\s*#\s*WITH\s*CLERK\s*OF\s*COURT:\s*(\d{2}\s*[A-Z]{1,3}\s*\d{1,5}|TBD)", re.I)
BID_RE = re.compile(r"Current Bid:\s*\$([\d,]+\.\d{2})", re.I)
UPSET_RE = re.compile(r"Last day to upset(?:\s*bid)?:\s*(\d{1,2}/\d{1,2}/\d{2,4})", re.I)
ADDRESS_RE = re.compile(
    r"(\d+\s+[A-Z][\w .'\-]+(?:Rd|Road|St|Street|Dr|Drive|Ln|Lane|Ave|Avenue|"
    r"Hwy|Highway|Cir|Circle|Ct|Court|Way|Pl|Place|Trl|Trail|Pkwy|Parkway)[^<,]*,\s*[A-Z][a-z]+)",
    re.I,
)


class RutherfordTaxForeclosure(BaseScraper):
    slug = "counties_nc.rutherford_tax"
    name = "Rutherford NC Tax Foreclosure Sales"
    category = "county_tax"
    expected_min_count = 5
    timeout_s = 60.0

    async def fetch(self) -> Iterable[Listing]:
        async with client(timeout=20.0) as c:
            r = await c.get(URL, headers=HEADERS)
            if r.status_code != 200:
                return []
            html = r.text

        # Strip tags + use *** as block separator
        flat = _WS.sub(" ", _TAG.sub(" ", html))
        blocks = [b.strip() for b in SEPARATOR.split(flat) if "Parcel" in b]
        out: list[Listing] = []
        seen: set[str] = set()
        for blk in blocks:
            parcel_m = PARCEL_RE.search(blk)
            file_m = FILE_RE.search(blk)
            bid_m = BID_RE.search(blk)
            upset_m = UPSET_RE.search(blk)
            addr_m = ADDRESS_RE.search(blk)
            if not parcel_m:
                continue
            parcel = parcel_m.group(1).strip().split(";")[0].strip().split(" ")[0].strip()
            file_no = (file_m.group(1).strip() if file_m else "") or None
            if file_no and file_no.upper() == "TBD":
                file_no = None
            key = (parcel, file_no)
            if key in seen:
                continue
            seen.add(key)
            sale_date = None
            if upset_m:
                try:
                    sale_date = dateparser.parse(upset_m.group(1))
                except (ValueError, TypeError):
                    pass
            opening_bid = None
            if bid_m:
                try:
                    opening_bid = float(bid_m.group(1).replace(",", ""))
                except ValueError:
                    pass
            address = addr_m.group(1).strip() if addr_m else None
            out.append(
                Listing(
                    source=self.slug,
                    source_url=URL,
                    listing_type=ListingType.TAX_SALE,
                    property_kind=PropertyKind.UNKNOWN,
                    state="NC",
                    county="Rutherford",
                    parcel_id=parcel,
                    street_address=address,
                    sale_date=sale_date,
                    opening_bid=opening_bid,
                    case_number=file_no,
                    description=blk[:500],
                    first_seen=datetime.utcnow(),
                    last_seen=datetime.utcnow(),
                    raw={"rutherford_tax": {
                        "block_text": blk[:500],
                        "upset_deadline": upset_m.group(1) if upset_m else None,
                    }},
                )
            )
        return out
