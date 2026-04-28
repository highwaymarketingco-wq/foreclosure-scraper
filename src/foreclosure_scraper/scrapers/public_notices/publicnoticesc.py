"""publicnoticesc.com — South Carolina Press Association legal-notice aggregator.

Site is Cloudflare-protected; direct curl/httpx hangs the TLS handshake.
We use Apify rag-web-browser to render search-result pages.
"""
from __future__ import annotations

import re
from datetime import datetime
from typing import Iterable
from urllib.parse import urlencode

from ...apify_helper import fetch_rendered
from ...base_scraper import BaseScraper
from ...config import SC_COUNTIES
from ...models import Listing, ListingType, PropertyKind

BASE = "https://www.publicnoticesc.com"

QUERIES = (
    "foreclosure",
    "master in equity",
    "tax sale",
    "trustee sale",
)

ADDR_RE = re.compile(
    r"(\d+\s+[A-Z][\w .'\-]+(?:Road|Rd|Street|St|Drive|Dr|Lane|Ln|Avenue|Ave|"
    r"Highway|Hwy|Boulevard|Blvd|Circle|Cir|Court|Ct|Way|Place|Pl|Trail|Trl|Parkway|Pkwy)\.?)",
    re.I,
)
LINK_RE = re.compile(r"https?://[^\s)\]\"']*publicnoticesc\.com/[^\s)\]\"']+", re.I)


class PublicNoticeSC(BaseScraper):
    slug = "public_notices.publicnoticesc"
    name = "Public Notice SC (SCPA)"
    category = "public_notice"
    timeout_s = 360.0

    async def fetch(self) -> Iterable[Listing]:
        out: list[Listing] = []
        # We aim for ONE rendered fetch per (county, query) — more than that and
        # rag-web-browser cost compounds. Limit to 3 highest-yield counties.
        priority_counties = [c for c in SC_COUNTIES if c.name in ("Greenville", "Spartanburg", "Anderson")]
        for county in priority_counties:
            for q in QUERIES[:2]:  # 2 queries per county = 6 total fetches
                params = {"keyword": q, "category": "Foreclosures", "county": county.name}
                url = f"{BASE}/Search.aspx?{urlencode(params)}"
                content = await fetch_rendered(url)
                if not content:
                    continue
                # Parse markdown / extracted text for listing links + addresses
                seen: set[str] = set()
                for href in set(LINK_RE.findall(content)):
                    if href in seen:
                        continue
                    if "Search.aspx" in href:
                        continue
                    seen.add(href)
                    out.append(
                        Listing(
                            source=self.slug,
                            source_url=href.rstrip(").,]"),
                            listing_type=ListingType.FORECLOSURE_SALE,
                            property_kind=PropertyKind.UNKNOWN,
                            state="SC",
                            county=county.name,
                            description=f"Public Notice SC — {q} in {county.name} County",
                            first_seen=datetime.utcnow(),
                            last_seen=datetime.utcnow(),
                        )
                    )
                # Also pull addresses from the rendered text
                for line in content.split("\n"):
                    addr_m = ADDR_RE.search(line)
                    if not addr_m:
                        continue
                    out.append(
                        Listing(
                            source=self.slug,
                            source_url=url,
                            listing_type=ListingType.FORECLOSURE_SALE,
                            property_kind=PropertyKind.UNKNOWN,
                            state="SC",
                            county=county.name,
                            street_address=addr_m.group(1),
                            description=line[:300],
                            first_seen=datetime.utcnow(),
                            last_seen=datetime.utcnow(),
                        )
                    )
        return out
