"""SC Forfeited Land Commission — statewide tax-sale list.

The SC FLC publishes a county-by-county tax sale calendar plus the list of
forfeited parcels available for over-the-counter purchase. We scrape the FLC
landing page on each upstate county tax collector's site.
"""
from __future__ import annotations

import re
from datetime import datetime
from typing import Iterable

from selectolax.parser import HTMLParser

from ...base_scraper import BaseScraper
from ...config import SC_COUNTIES
from ...http_client import get_text
from ...models import Listing, ListingType, PropertyKind

# Each SC county's tax collector hosts its own tax sale page. URL patterns vary.
# URLs verified via 2026-04-28 audit. Sources where the original URL was a 404
# wrapper page are replaced; sites known to be down or returning 500 are kept
# but expected to fail until restored.
COUNTY_TAX_URLS: dict[str, tuple[str, ...]] = {
    # Greenville/Greenwood/Newberry/Abbeville removed per scope narrowing 2026-05.
    "Spartanburg": (
        "https://www.spartanburgcounty.gov/216/Tax-Collector",
    ),
    "Anderson": (
        "https://www.andersoncountysc.org/departments-a-z/treasurer/",
    ),
    "Pickens": (
        "https://www.pickenscountysc.gov/treasurer/tax-sale",
    ),
    "Oconee": (
        "https://oconeesc.com/Departments/A-E/Delinquent-Tax-Collector",  # currently 500; retained for retry
    ),
    "Cherokee": (
        "https://cherokeecountysc.gov/delinquent-tax/",
    ),
    "Union": ("https://www.countyofunion.com/treasurer/tax-sale",),
    "Laurens": ("https://www.co.laurens.sc.us/treasurer/tax-sale",),
}

PARCEL_RE = re.compile(r"\b\d{4}-\d{2}-\d{2}-\d{3}\.\d{3}\b|\b[A-Z0-9]{3,5}-\d{2}-\d{2,4}-\d{3,4}\b")
ADDR_RE = re.compile(
    r"(\d+\s+[A-Z][\w .'\-]+(?:Road|Rd|Street|St|Drive|Dr|Lane|Ln|Avenue|Ave|"
    r"Highway|Hwy|Boulevard|Blvd|Circle|Cir|Court|Ct|Way|Place|Pl|Trail|Trl|Parkway|Pkwy)\.?)",
    re.I,
)


class SCForfeitedLand(BaseScraper):
    slug = "counties_sc.sc_flc"
    name = "SC Forfeited Land / Tax Sale (all counties)"
    category = "county_tax"
    timeout_s = 240.0

    async def fetch(self) -> Iterable[Listing]:
        out: list[Listing] = []
        for c in SC_COUNTIES:
            for url in COUNTY_TAX_URLS.get(c.name, ()):
                try:
                    html = await get_text(url, timeout=45.0)
                except Exception:
                    continue
                tree = HTMLParser(html)
                # Capture any PDF list of forfeited / tax-sale parcels
                for a in tree.css("a[href$='.pdf']"):
                    href = a.attributes.get("href", "")
                    if href.startswith("/"):
                        href = f"{url.split('/', 3)[0]}//{url.split('/')[2]}{href}"
                    label = (a.text(strip=True) or "").lower()
                    if not any(
                        k in label
                        for k in ("forfeit", "tax sale", "delinquent", "fla", "flc", "forfeited land")
                    ):
                        continue
                    out.append(
                        Listing(
                            source=self.slug,
                            source_url=href,
                            listing_type=ListingType.TAX_SALE,
                            property_kind=PropertyKind.UNKNOWN,
                            state="SC",
                            county=c.name,
                            description=a.text(strip=True)[:200],
                            first_seen=datetime.utcnow(),
                            last_seen=datetime.utcnow(),
                            raw={"page_url": url},
                        )
                    )
                # Also scan inline tables for parcel rows
                body_text = tree.body.text(separator="\n") if tree.body else ""
                for line in body_text.splitlines():
                    line = line.strip()
                    if len(line) < 15:
                        continue
                    parcel = PARCEL_RE.search(line)
                    addr = ADDR_RE.search(line)
                    if not (parcel or addr):
                        continue
                    out.append(
                        Listing(
                            source=self.slug,
                            source_url=url,
                            listing_type=ListingType.TAX_SALE,
                            property_kind=PropertyKind.UNKNOWN,
                            state="SC",
                            county=c.name,
                            parcel_id=parcel.group(0) if parcel else None,
                            street_address=addr.group(1) if addr else None,
                            description=line[:300],
                            first_seen=datetime.utcnow(),
                            last_seen=datetime.utcnow(),
                        )
                    )
        return out
