"""North Carolina legal notices via ncnotices.com (the SCPA-equivalent site).

Old `ncpublicnotices.com` is NXDOMAIN. New aggregator is ncnotices.com (NC Press
Association). Site is server-rendered enough that we can scrape.
"""
from __future__ import annotations

import re
from datetime import datetime
from typing import Iterable
from urllib.parse import urlencode

from selectolax.parser import HTMLParser

from ...base_scraper import BaseScraper
from ...config import NC_COUNTIES
from ...http_client import get_text
from ...models import Listing, ListingType, PropertyKind

BASE = "https://www.ncnotices.com"
SEARCH_PATH = "/search/"
QUERIES = (
    "foreclosure sale",
    "trustee sale",
    "substitute trustee",
    "tax foreclosure",
    "upset bid",
)
ADDR_RE = re.compile(
    r"(\d+\s+[A-Z][\w .'\-]+(?:Road|Rd|Street|St|Drive|Dr|Lane|Ln|Avenue|Ave|"
    r"Highway|Hwy|Boulevard|Blvd|Circle|Cir|Court|Ct|Way|Place|Pl|Trail|Trl|Parkway|Pkwy)\.?)",
    re.I,
)


class PublicNoticeNC(BaseScraper):
    slug = "public_notices.ncnotices"
    name = "NC Notices (NCPA)"
    category = "public_notice"
    timeout_s = 240.0

    async def fetch(self) -> Iterable[Listing]:
        out: list[Listing] = []
        for county in NC_COUNTIES:
            for q in QUERIES:
                params = {"keyword": q, "county": county.name, "lookbackDays": "60"}
                url = f"{BASE}{SEARCH_PATH}?{urlencode(params)}"
                try:
                    html = await get_text(url, timeout=30.0, referer=BASE)
                except Exception:
                    continue
                tree = HTMLParser(html)
                for card in tree.css(
                    "article.notice, div.notice, li.notice, tr.noticeRow, .search-result, .public-notice"
                ):
                    a = (
                        card.css_first("a[href*='/notice/']")
                        or card.css_first("a[href*='/details/']")
                        or card.css_first("a")
                    )
                    if not a:
                        continue
                    href = a.attributes.get("href", "")
                    if href.startswith("/"):
                        href = f"{BASE}{href}"
                    title = (a.text(strip=True) or "")[:300]
                    body = card.text(strip=True)
                    blob = (title + " " + body).lower()
                    listing_type = ListingType.FORECLOSURE_SALE
                    if "tax foreclosure" in blob or "tax sale" in blob:
                        listing_type = ListingType.TAX_SALE
                    elif "sheriff" in blob:
                        listing_type = ListingType.SHERIFF_SALE
                    addr_m = ADDR_RE.search(body)
                    out.append(
                        Listing(
                            source=self.slug,
                            source_url=href,
                            listing_type=listing_type,
                            property_kind=PropertyKind.UNKNOWN,
                            street_address=addr_m.group(1) if addr_m else None,
                            state="NC",
                            county=county.name,
                            description=title,
                            first_seen=datetime.utcnow(),
                            last_seen=datetime.utcnow(),
                            raw={"snippet": body[:800]},
                        )
                    )
        return out
