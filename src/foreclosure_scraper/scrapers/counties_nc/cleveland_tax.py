"""Cleveland NC tax foreclosure sales — Legal Department.

Page is HTML <p> with numbered inline listings:
  "1. Wednesday, April 8, 2026 at 9:15 a.m. Parcel 25219 / File # 25CV003887-220 /
   China Ave, Shelby, NC 28150 / Map 6-4B, Block 1, Lot 1."

Plus a "PROPERTIES CURRENTLY IN FORECLOSURE" section with <li> bullets that
match the same pattern.

Cleveland's mod_security blocks plain "Mozilla/5.0" UA; need full Chrome UA + Accept headers.
"""
from __future__ import annotations

import re
from datetime import datetime
from typing import Iterable

from dateutil import parser as dateparser

from ...base_scraper import BaseScraper
from ...http_client import client
from ...models import Listing, ListingType, PropertyKind

URL = ("https://www.clevelandcounty.com/main/departments/"
       "find_tax_foreclosures___county_owned_properties_for_sale/index.php")
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9",
    "Accept-Language": "en-US,en;q=0.9",
}

_TAG = re.compile(r"<[^>]+>")
_WS = re.compile(r"\s+")
# Each entry: <day>, <Month> <day>, <year> at <time> Parcel <id> / File # <case#> / <address>, <city>, NC <zip>
ENTRY_RE = re.compile(
    r"(?P<day>\w+),?\s+(?P<month>January|February|March|April|May|June|July|August|"
    r"September|October|November|December)\s+(?P<dayno>\d{1,2}),?\s+(?P<year>\d{4})"
    r"(?:\s+at\s+(?P<time>\d{1,2}(?::\d{2})?\s*(?:a\.?m\.?|p\.?m\.?)))?\s*\.?\s*"
    r"Parcel\s+(?P<parcel>\d+)\s*/\s*File\s*#\s*(?P<file>[\dA-Z\-]+)\s*/\s*"
    r"(?P<addr>[^,/]+,\s*[\w ]+,?\s*NC\s*\d{5})?",
    re.I,
)
# In-foreclosure bullets (no sale date yet)
PENDING_RE = re.compile(
    r"Parcel\s+(?P<parcel>\d+)\s*/\s*File\s*#\s*(?P<file>[\dA-Z\-]+)\s*/\s*"
    r"(?:Address:\s*)?(?P<addr>[^/]+(?:NC\s*\d{5})?)",
    re.I,
)


class ClevelandTaxForeclosure(BaseScraper):
    slug = "counties_nc.cleveland_tax"
    name = "Cleveland NC Tax Foreclosure Sales"
    category = "county_tax"
    expected_min_count = 3
    timeout_s = 60.0

    async def fetch(self) -> Iterable[Listing]:
        async with client(timeout=20.0) as c:
            r = await c.get(URL, headers=HEADERS)
            if r.status_code != 200:
                return []
            html = r.text

        flat = _WS.sub(" ", _TAG.sub(" ", html))
        out: list[Listing] = []
        seen: set[str] = set()

        # Pattern 1: scheduled sales (have date+time)
        for m in ENTRY_RE.finditer(flat):
            parcel = m.group("parcel")
            file_no = m.group("file")
            key = (parcel, file_no)
            if key in seen:
                continue
            seen.add(key)
            sale_date = None
            try:
                sale_date = dateparser.parse(
                    f"{m.group('month')} {m.group('dayno')} {m.group('year')} "
                    f"{m.group('time') or ''}".strip()
                )
            except (ValueError, TypeError):
                pass
            addr = (m.group("addr") or "").strip().rstrip("/").strip()
            out.append(
                Listing(
                    source=self.slug,
                    source_url=URL,
                    listing_type=ListingType.TAX_SALE,
                    property_kind=PropertyKind.UNKNOWN,
                    state="NC",
                    county="Cleveland",
                    parcel_id=parcel,
                    street_address=addr or None,
                    sale_date=sale_date,
                    case_number=file_no,
                    description=m.group(0)[:500],
                    first_seen=datetime.utcnow(),
                    last_seen=datetime.utcnow(),
                    raw={"cleveland_tax": {"entry": m.group(0)[:500]}},
                )
            )

        # Pattern 2: properties IN foreclosure (no sale date yet)
        # Limit search to text after "CURRENTLY IN FORECLOSURE" marker
        in_marker = flat.upper().find("CURRENTLY IN FORECLOSURE")
        if in_marker > 0:
            tail = flat[in_marker:in_marker + 8000]
            for m in PENDING_RE.finditer(tail):
                parcel = m.group("parcel")
                file_no = m.group("file")
                key = (parcel, file_no)
                if key in seen:
                    continue
                seen.add(key)
                addr = (m.group("addr") or "").strip().rstrip("/").strip()
                out.append(
                    Listing(
                        source=self.slug,
                        source_url=URL,
                        listing_type=ListingType.LIS_PENDENS,
                        property_kind=PropertyKind.UNKNOWN,
                        state="NC",
                        county="Cleveland",
                        parcel_id=parcel,
                        street_address=addr or None,
                        case_number=file_no,
                        description=m.group(0)[:500],
                        auction_status="pending",
                        first_seen=datetime.utcnow(),
                        last_seen=datetime.utcnow(),
                        raw={"cleveland_tax": {"entry": m.group(0)[:500], "stage": "pending"}},
                    )
                )
        return out
