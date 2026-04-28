"""NC Clerk of Superior Court — foreclosure file calendar (per county)."""
from __future__ import annotations

import re
from datetime import datetime
from typing import Iterable

from selectolax.parser import HTMLParser

from ...base_scraper import BaseScraper
from ...config import NC_COUNTIES
from ...http_client import get_text
from ...models import Listing, ListingType, PropertyKind

CASE_RE = re.compile(r"\b\d{2}\s?SP\s?\d{3,6}\b", re.I)
ADDR_RE = re.compile(
    r"(\d+\s+[A-Z][\w .'\-]+(?:Road|Rd|Street|St|Drive|Dr|Lane|Ln|Avenue|Ave|"
    r"Highway|Hwy|Boulevard|Blvd|Circle|Cir|Court|Ct|Way|Place|Pl|Trail|Trl|Parkway|Pkwy)\.?)",
    re.I,
)


def _county_url(name: str) -> tuple[str, ...]:
    slug = name.lower().replace(" ", "")
    return (
        f"https://www.nccourts.gov/locations/{slug}-county/foreclosure-sales",
        f"https://www.nccourts.gov/locations/{slug}-county/foreclosure-postings",
    )


class NCClerkForeclosures(BaseScraper):
    slug = "counties_nc.nc_clerk_foreclosures"
    name = "NC Clerk of Court Foreclosure Postings"
    category = "county_court"
    timeout_s = 360.0

    async def fetch(self) -> Iterable[Listing]:
        out: list[Listing] = []
        for c in NC_COUNTIES:
            for url in _county_url(c.name):
                try:
                    html = await get_text(url, timeout=30.0)
                except Exception:
                    continue
                tree = HTMLParser(html)
                # Find any anchor pointing to a foreclosure notice PDF / detail
                for a in tree.css("a[href]"):
                    href = a.attributes.get("href", "")
                    if not href:
                        continue
                    if not any(k in href.lower() for k in (".pdf", "foreclosure", "sp-", "sale")):
                        continue
                    full = href if href.startswith("http") else (
                        f"https://www.nccourts.gov{href}" if href.startswith("/") else f"{url.rstrip('/')}/{href}"
                    )
                    label = a.text(strip=True)
                    case_m = CASE_RE.search(label) or CASE_RE.search(href)
                    addr_m = ADDR_RE.search(label) or ADDR_RE.search(a.parent.text(strip=True) if a.parent else "")
                    out.append(
                        Listing(
                            source=self.slug,
                            source_url=full,
                            listing_type=ListingType.FORECLOSURE_SALE,
                            property_kind=PropertyKind.UNKNOWN,
                            state="NC",
                            county=c.name,
                            case_number=case_m.group(0) if case_m else None,
                            street_address=addr_m.group(1) if addr_m else None,
                            description=(label or "")[:500] or None,
                            first_seen=datetime.utcnow(),
                            last_seen=datetime.utcnow(),
                        )
                    )
        return out
