"""Mecklenburg County (NC) tax foreclosure — Kania Law Firm publishes the upcoming list
on a county-specific sub-page.
"""
from __future__ import annotations

import re
from datetime import datetime
from typing import Iterable

from dateutil import parser as dateparser
from selectolax.parser import HTMLParser

from ...base_scraper import BaseScraper
from ...http_client import get_text
from ...models import Listing, ListingType, PropertyKind

# The Kania site lists each NC county under tax-foreclosures/<county>-county-nc/
COUNTY_URLS = {
    "Mecklenburg": "https://kanialawfirm.com/tax-foreclosures/mecklenburg-county-nc/",
    "Davidson": "https://kanialawfirm.com/tax-foreclosures/davidson-county-nc/",
    # Index page that may surface other counties Kania handles
}
INDEX_URL = "https://kanialawfirm.com/tax-foreclosures/foreclosure-listings/"

ADDR_RE = re.compile(
    r"(\d+\s+[A-Z][\w .'\-]+(?:Road|Rd|Street|St|Drive|Dr|Lane|Ln|Avenue|Ave|"
    r"Highway|Hwy|Boulevard|Blvd|Circle|Cir|Court|Ct|Way|Place|Pl|Trail|Trl|Parkway|Pkwy)\.?)",
    re.I,
)
DATE_RE = re.compile(
    r"\b(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\s+\d{1,2},?\s+\d{4}\b",
    re.I,
)
PARCEL_RE = re.compile(r"\b(?:parcel|tax id|tax pin|pin)\b[:#\s]+([A-Z0-9\-\.]{6,})", re.I)


def _parse_county_page(html: str, county: str, url: str, slug: str) -> list[Listing]:
    out: list[Listing] = []
    tree = HTMLParser(html)
    # Each foreclosure tends to be its own card / table row — try tables first
    for tbl in tree.css("table"):
        for row in tbl.css("tr"):
            text = row.text(separator=" | ", strip=True)
            if len(text) < 30:
                continue
            addr_m = ADDR_RE.search(text)
            date_m = DATE_RE.search(text)
            parcel_m = PARCEL_RE.search(text)
            if not (addr_m or parcel_m):
                continue
            sale_date = None
            if date_m:
                try:
                    sale_date = dateparser.parse(date_m.group(0))
                except (ValueError, TypeError):
                    pass
            out.append(
                Listing(
                    source=slug,
                    source_url=url,
                    listing_type=ListingType.TAX_SALE,
                    property_kind=PropertyKind.UNKNOWN,
                    state="NC",
                    county=county,
                    street_address=addr_m.group(1) if addr_m else None,
                    parcel_id=parcel_m.group(1) if parcel_m else None,
                    sale_date=sale_date,
                    description=f"Kania Law tax foreclosure ({county} Co. NC) — {text[:200]}",
                    first_seen=datetime.utcnow(),
                    last_seen=datetime.utcnow(),
                )
            )
    # Fallback: scan text blocks with addresses + dates
    if not out:
        body = tree.body.text(separator="\n") if tree.body else ""
        for chunk in re.split(r"\n{2,}", body):
            chunk = chunk.strip()
            addr_m = ADDR_RE.search(chunk)
            date_m = DATE_RE.search(chunk)
            if not addr_m or not date_m:
                continue
            try:
                sale_date = dateparser.parse(date_m.group(0))
            except (ValueError, TypeError):
                continue
            out.append(
                Listing(
                    source=slug,
                    source_url=url,
                    listing_type=ListingType.TAX_SALE,
                    property_kind=PropertyKind.UNKNOWN,
                    state="NC",
                    county=county,
                    street_address=addr_m.group(1),
                    sale_date=sale_date,
                    description=chunk[:300],
                    first_seen=datetime.utcnow(),
                    last_seen=datetime.utcnow(),
                )
            )
    return out


class MecklenburgTaxForeclosures(BaseScraper):
    slug = "counties_nc.mecklenburg_tax"
    name = "Kania Law NC Tax Foreclosures"
    category = "county_tax"
    timeout_s = 240.0

    async def fetch(self) -> Iterable[Listing]:
        out: list[Listing] = []
        # Direct county pages
        for county, url in COUNTY_URLS.items():
            try:
                html = await get_text(url, timeout=45.0)
            except Exception:
                continue
            out.extend(_parse_county_page(html, county, url, self.slug))

        # Discover any additional NC counties published on the index page
        try:
            idx_html = await get_text(INDEX_URL, timeout=45.0)
        except Exception:
            return out
        tree = HTMLParser(idx_html)
        for a in tree.css("a[href*='-county-nc']"):
            href = a.attributes.get("href", "")
            if not href:
                continue
            if href.startswith("/"):
                href = "https://kanialawfirm.com" + href
            m = re.search(r"/([a-z\-]+)-county-nc/?", href, re.I)
            if not m:
                continue
            county = m.group(1).replace("-", " ").title()
            if county in COUNTY_URLS:
                continue  # already fetched
            try:
                page = await get_text(href, timeout=45.0)
            except Exception:
                continue
            out.extend(_parse_county_page(page, county, href, self.slug))
        return out
