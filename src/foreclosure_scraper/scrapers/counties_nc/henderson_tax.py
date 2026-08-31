"""Henderson County NC tax-foreclosure sales — county Tax Office.

Source (live-verified 2026-08-30):
    https://www.hendersoncountync.gov/tax/page/tax-foreclosure-sales

The page carries ONE data <table> whose header row is:
    ["Listing Owner's Name:", "Parcel #:", "Description:",
     "Clerk of Court File #", "Estimated Opening Bid*"]
and 1 row per parcel scheduled for tax foreclosure sale. The batch sale date +
location ("... at 10:00am", 200 N Grove St, Hendersonville NC) is printed once in
prose ABOVE the table and applies to every row. There is no per-row street
address — the "Description" cell is a legal description (subdivision/lot/plat or a
road-frontage note), so a parcel_id is the load-bearing identifier here.

This is the NCGS §105-374 in-rem tax-foreclosure docket, so listings are emitted
as TAX_SALE (matching gaston_tax_foreclosures / haywood_tax_foreclosures) with
``foreclosure_process="tax"``. The "Estimated Opening Bid" is the taxes+costs
upset figure, promoted to ``opening_bid`` and floated (``$1,613.43*`` -> 1613.43).

Tax-foreclosure calendars are seasonal: when the county has no sale scheduled the
table can be empty or absent. An empty parse is a correct zero, not a failure.

Gate with FORECLOSURE_HENDERSON_FCL=0 to skip.
"""
from __future__ import annotations

import os
import re
from datetime import datetime
from typing import Iterable

from dateutil import parser as dateparser
from selectolax.parser import HTMLParser

from ...base_scraper import BaseScraper
from ...http_client import client
from ...models import Listing, ListingType, PropertyKind

URL = "https://www.hendersoncountync.gov/tax/page/tax-foreclosure-sales"
ENV_OFF = "FORECLOSURE_HENDERSON_FCL"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9",
    "Accept-Language": "en-US,en;q=0.9",
}

# "May 27, 2026 at 10:00am"  /  "May 27, 2026"
DATE_RE = re.compile(
    r"((?:January|February|March|April|May|June|July|August|September|October|November|December)"
    r"\s+\d{1,2},?\s+\d{4}(?:\s+at\s+\d{1,2}(?::\d{2})?\s*(?:am|pm))?)", re.I)
# "10:00am" style time-of-day for sale_time
TIME_RE = re.compile(r"\b(\d{1,2}(?::\d{2})?\s*(?:am|pm))\b", re.I)
# "200 N Grove St, Hendersonville, NC ..."
LOCATION_RE = re.compile(r"(\d+\s+[A-Z][\w .'\-]+,\s*[A-Z][\w .'\-]+,?\s*NC[\w\s]*)", re.I)
BID_RE = re.compile(r"\$?\s*([\d,]+(?:\.\d{2})?)")
# "Clerk of Court File #" values look like 25M000267-440
FILE_RE = re.compile(r"\d{2}[A-Z]{1,3}\d{4,}(?:-\d+)?")


def _float(text: str):
    if not text:
        return None
    m = BID_RE.search(text)
    if not m:
        return None
    try:
        return float(m.group(1).replace(",", ""))
    except ValueError:
        return None


class HendersonTaxForeclosure(BaseScraper):
    slug = "counties_nc.henderson_tax"
    name = "Henderson NC Tax Foreclosure Sales"
    category = "county_tax"
    expected_min_count = 0
    timeout_s = 120.0

    async def fetch(self) -> Iterable[Listing]:
        if os.environ.get(ENV_OFF, "1") == "0":
            return []

        html = ""
        try:
            async with client(timeout=60) as c:
                r = await c.get(URL, headers=HEADERS)
                if r.status_code != 200:
                    return []
                html = r.text
        except Exception:  # noqa: BLE001 - network must never raise out of a scraper
            return []
        if not html:
            return []

        # Batch sale date / time / location parsed once for all rows.
        sale_date = None
        sale_time = None
        sale_location = None
        city = None
        try:
            tree = HTMLParser(html)
            page_text = tree.body.text(separator=" ") if tree.body else html
        except Exception:  # noqa: BLE001
            return []

        m = DATE_RE.search(page_text)
        if m:
            try:
                sale_date = dateparser.parse(m.group(1), fuzzy=True)
            except (ValueError, TypeError, OverflowError):
                sale_date = None
            tm = TIME_RE.search(m.group(1))
            if tm:
                sale_time = tm.group(1).strip()
        loc = LOCATION_RE.search(page_text)
        if loc:
            sale_location = " ".join(loc.group(1).split())
            # "200 N Grove St, Hendersonville, NC 28792" -> city = Hendersonville
            parts = [p.strip() for p in sale_location.split(",")]
            if len(parts) >= 2 and parts[1] and parts[1].upper() != "NC":
                city = parts[1]

        out: list[Listing] = []
        seen: set[str] = set()
        for row in tree.css("tr"):
            cells = row.css("td") or row.css("th")
            if len(cells) < 5:
                continue
            owner = " ".join((cells[0].text() or "").split())
            parcel = " ".join((cells[1].text() or "").split())
            description = " ".join((cells[2].text() or "").split())
            file_no = " ".join((cells[3].text() or "").split())
            bid_str = " ".join((cells[4].text() or "").split())

            # Drop the header row and anything without a real numeric parcel.
            if not parcel or not re.match(r"\d{4,}", parcel):
                continue
            low = owner.lower()
            if "owner" in low and "name" in low:
                continue

            key = file_no or parcel
            if key in seen:
                continue
            seen.add(key)

            # Clean the clerk file # to the canonical token if present.
            fm = FILE_RE.search(file_no)
            case_number = fm.group(0) if fm else (file_no or None)

            out.append(
                Listing(
                    source=self.slug,
                    source_url=URL,
                    listing_type=ListingType.TAX_SALE,
                    property_kind=PropertyKind.UNKNOWN,
                    state="NC",
                    county="Henderson",
                    city=city,
                    parcel_id=parcel,
                    legal_description=description or None,
                    sale_date=sale_date,
                    sale_time=sale_time,
                    sale_location=sale_location,
                    opening_bid=_float(bid_str),
                    foreclosure_process="tax",
                    case_number=case_number,
                    owner_name=owner or None,
                    defendant=owner or None,
                    description=description[:500] or None,
                    first_seen=datetime.utcnow(),
                    last_seen=datetime.utcnow(),
                    raw={
                        "henderson_tax": {
                            "owner": owner,
                            "parcel": parcel,
                            "description": description,
                            "clerk_file": file_no,
                            "opening_bid": bid_str,
                        }
                    },
                )
            )
        return out
