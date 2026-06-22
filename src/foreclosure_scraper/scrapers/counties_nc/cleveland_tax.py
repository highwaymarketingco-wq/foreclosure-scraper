"""Cleveland NC tax foreclosure sales — Legal Department.

Page is HTML <p> with numbered inline listings:
  "1. Wednesday, April 8, 2026 at 9:15 a.m. Parcel 25219 / File # 25CV003887-220 /
   China Ave, Shelby, NC 28150 / Map 6-4B, Block 1, Lot 1."

Plus a "PROPERTIES CURRENTLY IN FORECLOSURE" section with <li> bullets that
match the same pattern.

Cleveland's mod_security blocks plain "Mozilla/5.0" UA; need full Chrome UA + Accept headers.
"""
from __future__ import annotations

import html as _html
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
# Tolerant entry pattern. The page lists every property (whether a scheduled
# upset-bid sale or a pending foreclosure) as:
#   "Parcel[:] <id> / File # <case#> / [Address:] <address> / Map ..."
# "Parcel" may carry an optional colon and the "/" separators may be padded
# with &nbsp; (decoded before matching). The address runs up to the next "/".
ENTRY_RE = re.compile(
    r"Parcel:?\s*(?P<parcel>\d+)\s*/\s*File\s*#\s*(?P<file>[\dA-Za-z\-]+)\s*/\s*"
    r"(?:Address:\s*)?(?P<addr>[^/]+)",
    re.I,
)
# Sale date, when present in a section header preceding a scheduled listing.
DATE_RE = re.compile(
    r"(?:January|February|March|April|May|June|July|August|September|October|"
    r"November|December)\s+\d{1,2},?\s+\d{4}"
    r"(?:\s+at\s+\d{1,2}(?::\d{2})?\s*[ap]\.?m\.?)?",
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

        # Decode HTML entities BEFORE flattening whitespace: the page pads its
        # "/" separators with literal &nbsp; entities (e.g. "Parcel 57139 /&nbsp;
        # File #"). Without unescape these survive as literal text and break the
        # "/ File" boundary, silently dropping the scheduled/upset-bid listings.
        flat = _WS.sub(" ", _html.unescape(_TAG.sub(" ", html)))
        out: list[Listing] = []
        seen: set[str] = set()

        # Properties after the "CURRENTLY IN FORECLOSURE" marker are pending
        # (no sale yet); those before it are scheduled / in the upset-bid window.
        marker = flat.upper().find("CURRENTLY IN FORECLOSURE")

        for m in ENTRY_RE.finditer(flat):
            parcel = m.group("parcel")
            file_no = m.group("file")
            key = (parcel, file_no)
            if key in seen:
                continue
            seen.add(key)
            addr = (m.group("addr") or "").strip().rstrip("/").strip()
            pending = marker > 0 and m.start() > marker

            sale_date = None
            if not pending:
                # Look back a short window for a section/header sale date.
                dm = DATE_RE.search(flat[max(0, m.start() - 180):m.start()])
                if dm:
                    try:
                        sale_date = dateparser.parse(dm.group(0))
                    except (ValueError, TypeError):
                        pass

            out.append(
                Listing(
                    source=self.slug,
                    source_url=URL,
                    listing_type=ListingType.LIS_PENDENS if pending else ListingType.TAX_SALE,
                    property_kind=PropertyKind.UNKNOWN,
                    state="NC",
                    county="Cleveland",
                    parcel_id=parcel,
                    street_address=addr or None,
                    sale_date=sale_date,
                    case_number=file_no,
                    description=m.group(0)[:500],
                    auction_status="pending" if pending else None,
                    first_seen=datetime.utcnow(),
                    last_seen=datetime.utcnow(),
                    raw={"cleveland_tax": {"entry": m.group(0)[:500],
                                          "stage": "pending" if pending else "scheduled"}},
                )
            )
        return out
