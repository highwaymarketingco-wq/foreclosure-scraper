"""McDonald, Patrick, Poston & Hemphill (SC) — county foreclosure sale lists.

Discovered 2026-06-16. This substitute-trustee firm publishes per-county
foreclosure sale notices at mcdonaldpatrick.com/foreclosure-sales/
<county>-county-foreclosure-sales/. Unlike the SC court rosters (which
expose only a TMS parcel id), these notices carry the real situs address
and city, e.g.:

  "US Bank v Randall, et. al., C/A No. 2023CP2400921- 1103 Gary Rd,
   Hodges, SC (Land Only)"

We keep the three counties in our upstate scope: Abbeville, Greenwood,
Newberry. (The firm also covers Edgefield/McCormick/Saluda, out of scope.)

Plain HTTP — no bot protection.
"""
from __future__ import annotations

import re
from datetime import datetime
from typing import Iterable

from selectolax.parser import HTMLParser

from ...base_scraper import BaseScraper
from ...http_client import client
from ...models import Listing, ListingType, PropertyKind

# in-scope county -> page slug
COUNTY_PAGES: dict[str, str] = {
    "Abbeville": "abbeville-county-foreclosure-sales",
    "Greenwood": "greenwood-county-foreclosure-sales",
    "Newberry": "newberry-county-foreclosure-sales",
}
BASE = "https://mcdonaldpatrick.com/foreclosure-sales"

# "US Bank v Randall, et. al., C/A No. 2023CP2400921- 1103 Gary Rd, Hodges, SC"
# Tolerant of: "v"/"vs", optional "et. al.", "-"/"–" before C/A No and before
# the address, one or more case numbers, and a trailing ", SC".
NOTICE_RE = re.compile(
    r"(?P<plaintiff>[A-Z][\w &.,'/-]{2,60}?)\s+vs?\.?\s+"
    r"(?P<defendant>[\w &.,'/-]{2,60}?),?\s*(?:et\.?\s*al\.?,?)?\s*[-–,]?\s*"
    r"C/A\s*No\.?\s*(?P<case>\d{4}CP\d{6,8})"
    r"(?:\s*(?:and|,)\s*\d{4}CP\d{6,8})*\s*[-–]\s*"
    r"(?P<address>\d+\s+[\w .'-]+?),\s*(?P<city>[A-Z][a-zA-Z]+),?\s*SC",
    re.I,
)


class McDonaldPatrick(BaseScraper):
    slug = "law_firms.mcdonald_patrick"
    name = "McDonald Patrick (SC trustee)"
    category = "law_firm"
    expected_min_count = 0
    timeout_s = 120.0

    async def fetch(self) -> Iterable[Listing]:
        out: list[Listing] = []
        seen: set[tuple] = set()
        async with client(timeout=30.0, follow_redirects=True) as c:
            for county, page in COUNTY_PAGES.items():
                url = f"{BASE}/{page}/"
                try:
                    r = await c.get(url, headers={"User-Agent": "Mozilla/5.0"})
                except Exception:
                    continue
                if r.status_code != 200:
                    continue
                tree = HTMLParser(r.text)
                text = tree.body.text(separator="\n") if tree.body else r.text
                for m in NOTICE_RE.finditer(text):
                    case = m.group("case")
                    key = (county, case)
                    if key in seen:
                        continue
                    seen.add(key)

                    addr = re.sub(r"\s+", " ", m.group("address")).strip()
                    city = m.group("city").strip()
                    plaintiff = re.sub(r"\s+", " ", m.group("plaintiff")).strip(" ,-")
                    defendant = re.sub(r"\s+", " ", m.group("defendant")).strip(" ,-")

                    out.append(
                        Listing(
                            source=self.slug,
                            source_url=url,
                            listing_type=ListingType.FORECLOSURE_SALE,
                            property_kind=PropertyKind.UNKNOWN,
                            state="SC",
                            county=county,
                            street_address=addr or None,
                            city=city or None,
                            case_number=case,
                            plaintiff=plaintiff[:200] or None,
                            defendant=defendant[:200] or None,
                            first_seen=datetime.utcnow(),
                            last_seen=datetime.utcnow(),
                            raw={"mcdonald_patrick": {"county": county}},
                        )
                    )
        return out
