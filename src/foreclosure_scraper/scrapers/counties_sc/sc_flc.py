"""SC Forfeited Land Commission — statewide tax-sale list.

The SC FLC publishes a county-by-county tax sale calendar plus the list of
forfeited parcels available for over-the-counter purchase. We scrape the FLC
landing page on each upstate county tax collector's site.

JUNK FILTER (2026-06-25):
  The old inline body-text harvest scanned EVERY line of the page body and
  emitted a Listing whenever ADDR_RE matched a street suffix. On real CMS
  pages that matched county-office addresses ("110 Railroad Ave", "222
  McDaniel Avenue"), nav / GIS-menu items ("E-911 Addressing"), copyright
  footers ("© 2021 Pickens County"), and even JS snippets — producing 18
  address-less nav-chrome rows with no real parcel. Fix:
    * inline rows now REQUIRE a real SC TMS (PARCEL_RE) — addr-only lines
      are no longer harvested at all, and
    * any line that overlaps the page's own contact / nav / footer block
      (county office address, phone, hours, copyright, menu labels) is
      dropped even if it somehow carried a TMS.
  Net: nav-chrome yields 0 rows; only genuine forfeited-land/tax-sale PDFs
  and real TMS-tagged inline rows survive.
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

# Substrings that mark a line as page chrome (county-office contact block,
# nav / GIS menu items, footer, JS) rather than a forfeited-land parcel row.
# Lines containing any of these are dropped even if they happen to carry a TMS.
_NAV_CONTACT_MARKERS = (
    "e-911", "e911", "911 address", "addressing",
    "copyright", "©", "all rights reserved",
    "contact", "phone", "fax", "email", "hours", "monday", "friday",
    "planning", "subdividing", "combining",
    "linklevel", "linksection", "pagelinkfilter", "rz.",  # JS chrome
    "privacy", "sitemap", "site map", "accessibility", "disclaimer",
    "department", "treasurer's office", "tax collector's office",
)


def _is_nav_or_contact(line: str) -> bool:
    """True if a body line is page chrome (office address/phone, nav, footer,
    JS) and must not be emitted as a forfeited-land parcel row."""
    low = (line or "").lower()
    return any(m in low for m in _NAV_CONTACT_MARKERS)


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
                    # Skip post-sale / bidder-info sheets (e.g. "Tax Sale
                    # Bidders", "...RESULTS...") — those are not the list of
                    # forfeited / available parcels.
                    if any(k in (label + " " + href.lower())
                           for k in ("bidder", "result", "sold", "winning")):
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
                # Also scan inline tables for parcel rows. Require a REAL SC TMS
                # (PARCEL_RE) — addr-only lines are page chrome (county-office
                # address, nav, footer), never a forfeited-land row. Also drop
                # any line that is nav / contact / footer / JS even if it
                # somehow carried a TMS-looking token.
                body_text = tree.body.text(separator="\n") if tree.body else ""
                for line in body_text.splitlines():
                    line = line.strip()
                    if len(line) < 15:
                        continue
                    if _is_nav_or_contact(line):
                        continue
                    parcel = PARCEL_RE.search(line)
                    if not parcel:
                        continue
                    addr = ADDR_RE.search(line)
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
