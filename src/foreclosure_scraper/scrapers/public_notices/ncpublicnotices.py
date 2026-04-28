"""ncpublicnotices.com — North Carolina Press Association legal notice aggregator."""
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

BASE = "https://www.ncpublicnotices.com"

QUERIES = (
    "foreclosure",
    "trustee sale",
    "substitute trustee",
    "tax foreclosure",
    "upset bid",
)


class PublicNoticeNC(BaseScraper):
    slug = "public_notices.ncpublicnotices"
    name = "Public Notice NC (NCPA)"
    category = "public_notice"
    timeout_s = 240.0

    async def fetch(self) -> Iterable[Listing]:
        out: list[Listing] = []
        for county in NC_COUNTIES:
            for q in QUERIES:
                params = {
                    "keyword": q,
                    "county": county.name,
                    "lookbackDays": "60",
                }
                url = f"{BASE}/Search.aspx?{urlencode(params)}"
                try:
                    html = await get_text(url, timeout=30.0, referer=BASE)
                except Exception:
                    continue
                tree = HTMLParser(html)
                for card in tree.css("div.notice, article.notice, li.notice, tr.noticeRow"):
                    a = card.css_first("a[href*='Details.aspx'], a[href*='/notice/']")
                    if not a:
                        continue
                    href = a.attributes.get("href", "")
                    if href.startswith("/"):
                        href = f"{BASE}{href}"
                    title = (a.text(strip=True) or "")[:300]
                    body = card.text(strip=True)
                    listing_type = ListingType.FORECLOSURE_SALE
                    blob = (title + " " + body).lower()
                    if "tax foreclosure" in blob or "tax sale" in blob:
                        listing_type = ListingType.TAX_SALE
                    elif "upset bid" in blob:
                        listing_type = ListingType.FORECLOSURE_SALE
                    elif "sheriff" in blob:
                        listing_type = ListingType.SHERIFF_SALE

                    addr = None
                    m = re.search(
                        r"(\d+\s+[A-Z][\w .'\-]+(?:Road|Rd|Street|St|Drive|Dr|Lane|Ln|Avenue|Ave|Highway|Hwy|Boulevard|Blvd|Circle|Cir|Court|Ct|Way|Place|Pl|Trail|Trl|Parkway|Pkwy)\.?)",
                        body,
                        re.I,
                    )
                    if m:
                        addr = m.group(1)

                    out.append(
                        Listing(
                            source=self.slug,
                            source_url=href,
                            listing_type=listing_type,
                            property_kind=PropertyKind.UNKNOWN,
                            street_address=addr,
                            state="NC",
                            county=county.name,
                            description=title,
                            first_seen=datetime.utcnow(),
                            last_seen=datetime.utcnow(),
                            raw={"snippet": body[:800]},
                        )
                    )
        return out
