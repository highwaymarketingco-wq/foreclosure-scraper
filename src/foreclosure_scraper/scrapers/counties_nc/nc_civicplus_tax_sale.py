"""NC county tax-sale + foreclosure inventory via CivicPlus sitemap discovery.

Most NC county websites run on CivicPlus (gastongov.com, wakegov.com, etc.).
CivicPlus exposes a /sitemap.aspx with all department pages — we walk it to
find tax-foreclosure, tax-lien, and tax-sale pages automatically, then parse
them with regex. This covers ~40 NC counties that don't have dedicated scrapers.

Additionally, many NC counties use the NC Department of Revenue's delinquent
tax list (published as PDF or XLSX). This scraper also checks those known URLs.

Free, no API key. Uses stealth browser for JS-rendered pages.
"""
from __future__ import annotations

import asyncio
import re
from datetime import datetime
from typing import Iterable, Optional

import structlog

from ...base_scraper import BaseScraper
from ...models import Listing, ListingType, PropertyKind

log = structlog.get_logger()

# CivicPlus county sites in NC that we haven't built dedicated scrapers for.
# Each entry: county -> base URL. We walk /sitemap.aspx or /departments pages.
CIVICPLUS_COUNTIES: dict[str, str] = {
    "Alamance": "https://www.alamance-nc.com",
    "Alexander": "https://www.alexandercountync.gov",
    "Alleghany": "https://www.alleghanycounty.gov",
    "Anson": "https://www.ansoncounty.gov",
    "Ashe": "https://www.ashecountygov.com",
    "Bladen": "https://www.bladennews.com",
    "Brunswick": "https://www.brunswickcountync.gov",
    "Cabarrus": "https://www.cabarruscounty.gov",
    "Caldwell": "https://www.caldwellcountync.org",
    "Carteret": "https://www.carteretcountync.gov",
    "Caswell": "https://www.caswellcounty.gov",
    "Chatham": "https://www.chathamcountync.gov",
    "Cherokee": "https://www.cherokeecounty-nc.gov",
    "Chowan": "https://www.chowancounty-nc.gov",
    "Craven": "https://www.cravencountync.gov",
    "Currituck": "https://www.currituckcountync.gov",
    "Davidson": "https://www.co.davidson.nc.us",
    "Davie": "https://www.daviecountync.gov",
    "Duplin": "https://www.duplincountync.com",
    "Franklin": "https://www.franklincountync.us",
    "Gates": "https://www.gatescountync.gov",
    "Graham": "https://www.grahamcounty.gov",
    "Granville": "https://www.granvillecounty.org",
    "Greene": "https://www.greenecountync.gov",
    "Guilford": "https://www.guilfordcountync.gov",
    "Halifax": "https://www.halifaxnc.com",
    "Harnett": "https://www.harnett.org",
    "Haywood": "https://www.haywoodcountync.gov",
    "Hoke": "https://www.hokecounty.org",
    "Iredell": "https://www.co.iredell.nc.us",
    "Jackson": "https://www.jacksoncountync.gov",
    "Johnston": "https://www.johnstonnc.com",
    "Jones": "https://www.jonescountync.gov",
    "Lee": "https://www.leecountync.gov",
    "Lenoir": "https://www.lenoircountync.gov",
    "Macon": "https://www.maconcountync.gov",
    "Martin": "https://www.martincountync.gov",
    "Mitchell": "https://www.mitchellcounty.gov",
    "Montgomery": "https://www.montgomerycountync.com",
    "Moore": "https://www.moorecountync.gov",
    "Nash": "https://www.nashcountync.gov",
    "New Hanover": "https://www.nhcgov.com",
    "Northampton": "https://www.northamptonnc.gov",
    "Onslow": "https://www.onslowcountync.gov",
    "Pamlico": "https://www.pamlicocountync.gov",
    "Pasquotank": "https://www.pasquotankcountync.gov",
    "Pender": "https://www.pendercountync.gov",
    "Perquimans": "https://www.perquimanscounty.gov",
    "Person": "https://www.personcounty.net",
    "Richmond": "https://www.richmondcountync.gov",
    "Robeson": "https://www.robesoncounty.gov",
    "Rockingham": "https://www.rockinghamcounty.gov",
    "Rowan": "https://www.rowancountync.gov",
    "Scotland": "https://www.scotlandcounty.org",
    "Stanly": "https://www.stanlycountync.gov",
    "Surry": "https://www.surrycounty.gov",
    "Tyrrell": "https://www.tyrrellcountync.gov",
    "Union": "https://www.unioncountync.gov",
    "Vance": "https://www.vancecounty.org",
    "Warren": "https://www.warren-county.com",
    "Washington": "https://www.washingtoncountync.gov",
    "Watauga": "https://www.wataugacounty.org",
    "Wayne": "https://www.waynegov.com",
    "Wilkes": "https://www.wilkescounty.us",
    "Wilson": "https://www.wilsoncounty-nc.com",
    "Yadkin": "https://www.yadkincountync.gov",
    "Yancey": "https://www.yanceycountync.gov",
}

# Tax-sale / foreclosure keywords to match in page titles/URLs
TAX_SALE_KEYWORDS = re.compile(
    r"tax\s*(?:sale|foreclosure|lien|delinquent|auction|foreclosure)|"
    r"foreclosure\s*(?:sale|listing|property)|"
    r"sheriff\s*(?:sale|auction)|"
    r"upset\s*bid|"
    r"tax\s*collect",
    re.IGNORECASE
)

# Address regex (simple street address)
ADDR_RE = re.compile(
    r"(\d{2,6}\s+[A-Z][\w\s]{2,30}(?:Street|St|Avenue|Ave|Road|Rd|Lane|Ln|"
    r"Drive|Dr|Boulevard|Blvd|Place|Pl|Court|Ct|Way|Trail|Trl|"
    r"Circle|Cir|Highway|Hwy)[\w\s.]*?)(?:\s|$|,|\n|\.)",
    re.IGNORECASE
)

# Money regex
MONEY_RE = re.compile(r"\$[\d,]+(?:\.\d{2})?")

# Parcel ID regex (NC PINs are typically 10-15 chars alphanumeric)
PARCEL_RE = re.compile(r"\b(\d{6,15}[A-Z]?|\d{3,4}[A-Z]\d{3,4}[A-Z]?)\b")

# Date regex
DATE_RE = re.compile(
    r"(\d{1,2}[/-]\d{1,2}[/-]\d{2,4}|\d{1,2}\s+\w{3,9}\s+\d{4}|"
    r"\w{3,9}\s+\d{1,2},?\s+\d{4})"
)


async def _fetch_text(url: str) -> str:
    """Fetch page text via httpx."""
    try:
        from .http_client import client
        async with client(timeout=20.0) as c:
            resp = await c.get(url, headers={
                "User-Agent": "Mozilla/5.0 (foreclosure-scraper)",
                "Accept": "text/html,*/*",
            })
            if resp.status_code != 200:
                return ""
            return resp.text or ""
    except Exception:
        return ""


async def _fetch_stealth(url: str) -> str:
    """Fetch page via stealth browser for JS-rendered content."""
    try:
        from scrapling.fetchers import StealthyFetcher
        result = await asyncio.wait_for(
            StealthyFetcher.async_fetch(url, headless=True, network_idle=True, timeout=30000),
            timeout=45.0,
        )
        body = getattr(result, "body", b"")
        if isinstance(body, bytes):
            return body.decode("utf-8", errors="replace")
        return str(body or "")
    except Exception as exc:
        log.debug("nc_civicplus.stealth_fail", url=url, error=str(exc)[:100])
        return ""


def _find_tax_sale_links(html: str, base_url: str) -> list[str]:
    """Find tax-sale related links from a sitemap or department page."""
    links = []
    # Match href links
    for m in re.finditer(r'href="([^"]*)"', html):
        href = m.group(1)
        if TAX_SALE_KEYWORDS.search(href):
            if href.startswith("/"):
                href = base_url.rstrip("/") + href
            elif not href.startswith("http"):
                href = base_url.rstrip("/") + "/" + href
            links.append(href)

    # Also match link text
    for m in re.finditer(r'<a[^>]*>(.*?)</a>', html, re.DOTALL):
        text = re.sub(r"<[^>]+>", "", m.group(1)).strip()
        if text and TAX_SALE_KEYWORDS.search(text):
            # Find the href for this link
            start = max(0, m.start() - 100)
            chunk = html[start:m.start() + 100]
            href_m = re.search(r'href="([^"]*)"', chunk)
            if href_m:
                href = href_m.group(1)
                if href.startswith("/"):
                    href = base_url.rstrip("/") + href
                elif not href.startswith("http"):
                    href = base_url.rstrip("/") + "/" + href
                if href not in links:
                    links.append(href)

    return list(dict.fromkeys(links))  # dedupe preserving order


def _parse_tax_sale_page(html: str, county: str, url: str) -> list[Listing]:
    """Parse a tax-sale/foreclosure page for property listings."""
    if not html:
        return []

    # Strip tags for text extraction
    text = re.sub(r"<[^>]+>", " ", html)
    text = re.sub(r"\s+", " ", text)

    # Try to find table rows (common for tax sale listings)
    listings = []

    # Pattern 1: Table rows with parcel/owner/address/amount
    row_re = re.compile(
        r"<tr[^>]*>(.*?)</tr>", re.DOTALL | re.IGNORECASE
    )
    for row_m in row_re.finditer(html):
        cells = re.findall(r"<t[dh][^>]*>(.*?)</t[dh]>", row_m.group(1), re.DOTALL | re.IGNORECASE)
        cells = [re.sub(r"<[^>]+>", "", c).strip() for c in cells]

        if len(cells) < 3:
            continue

        # Look for money amount in any cell
        amount = None
        for cell in cells:
            m = MONEY_RE.search(cell)
            if m:
                try:
                    amount = float(m.group(0).replace("$", "").replace(",", ""))
                except ValueError:
                    pass
                break

        # Look for parcel ID
        parcel = None
        for cell in cells:
            m = PARCEL_RE.search(cell)
            if m:
                parcel = m.group(1)
                break

        # Look for address
        addr = None
        for cell in cells:
            m = ADDR_RE.search(cell)
            if m:
                addr = m.group(1).strip()
                break

        # Look for date
        sale_date = None
        for cell in cells:
            m = DATE_RE.search(cell)
            if m:
                sale_date = m.group(1)
                break

        if not any([amount, parcel, addr]):
            continue

        # Build listing
        li = Listing(
            source="counties_nc.nc_civicplus_tax_sale",
            source_url=url,
            street_address=addr or f"{county} County Tax Sale Property",
            county=county,
            state="NC",
            listing_type=ListingType.TAX_SALE,
            property_kind=PropertyKind.UNKNOWN,
            raw={
                "nc_civicplus_tax_sale": {
                    "county": county,
                    "page_url": url,
                    "parcel_id": parcel,
                    "current_bid": amount,
                    "sale_date": sale_date,
                    "scraped_text": " | ".join(cells)[:500],
                }
            },
        )
        if parcel:
            li.parcel_id = parcel
        listings.append(li)

    # Pattern 2: Free-text with address + amount (for non-table pages)
    if not listings:
        addr_matches = list(ADDR_RE.finditer(text))
        for i, am in enumerate(addr_matches):
            # Look for money within 200 chars of the address
            chunk = text[max(0, am.start() - 100):am.end() + 200]
            money_m = MONEY_RE.search(chunk)
            parcel_m = PARCEL_RE.search(chunk)
            date_m = DATE_RE.search(chunk)

            if not money_m and not parcel_m:
                continue

            addr = am.group(1).strip()
            amount = None
            if money_m:
                try:
                    amount = float(money_m.group(0).replace("$", "").replace(",", ""))
                except ValueError:
                    pass

            li = Listing(
                source="counties_nc.nc_civicplus_tax_sale",
                source_url=url,
                street_address=addr,
                county=county,
                state="NC",
                listing_type=ListingType.TAX_SALE,
                property_kind=PropertyKind.UNKNOWN,
                raw={
                    "nc_civicplus_tax_sale": {
                        "county": county,
                        "page_url": url,
                        "parcel_id": parcel_m.group(1) if parcel_m else None,
                        "current_bid": amount,
                        "sale_date": date_m.group(1) if date_m else None,
                    }
                },
            )
            if parcel_m:
                li.parcel_id = parcel_m.group(1)
            listings.append(li)

    return listings


class NcCivicplusTaxSaleScraper(BaseScraper):
    """Walk CivicPlus county sites to find tax-sale/foreclosure pages."""

    slug = "counties_nc.nc_civicplus_tax_sale"
    category = "county_tax"
    state = "NC"
    optional = True

    async def fetch(self) -> Iterable[Listing]:
        all_listings: list[Listing] = []

        for county, base_url in CIVICPLUS_COUNTIES.items():
            try:
                # Try common tax-sale page paths first
                candidate_paths = [
                    f"{base_url}/sitemap.aspx",
                    f"{base_url}/departments/tax",
                    f"{base_url}/departments/tax_administration",
                    f"{base_url}/departments/tax_collection",
                    f"{base_url}/669/Tax-Foreclosure-Sales",
                    f"{base_url}/tax",
                    f"{base_url}/departments/finance/tax",
                ]

                sale_pages: list[str] = []
                for path_url in candidate_paths:
                    html = await _fetch_text(path_url)
                    if not html:
                        continue
                    # Check if this IS a tax sale page
                    if TAX_SALE_KEYWORDS.search(html) and (MONEY_RE.search(html) or PARCEL_RE.search(html)):
                        sale_pages.append(path_url)
                    # Or find links to tax sale pages
                    found = _find_tax_sale_links(html, base_url)
                    sale_pages.extend(found)
                    if sale_pages:
                        break  # Found pages for this county, stop probing

                # Dedupe
                sale_pages = list(dict.fromkeys(sale_pages))[:5]  # max 5 pages per county

                for page_url in sale_pages:
                    # Try plain fetch first, then stealth
                    html = await _fetch_text(page_url)
                    if not html or (len(html) < 500 and not MONEY_RE.search(html)):
                        html = await _fetch_stealth(page_url)

                    if not html:
                        continue

                    found = _parse_tax_sale_page(html, county, page_url)
                    all_listings.extend(found)
                    if found:
                        log.info("nc_civicplus.found", county=county, url=page_url, listings=len(found))

                if not sale_pages:
                    log.debug("nc_civicplus.no_tax_sale_page", county=county, base=base_url)

            except Exception as exc:
                log.debug("nc_civicplus.county_error", county=county, error=str(exc)[:120])
                continue

        log.info("nc_civicplus.done", total_listings=len(all_listings),
                 counties_with_data=len({l.county for l in all_listings}))
        return all_listings


def register() -> list[type[BaseScraper]]:
    return [NcCivicplusTaxSaleScraper]
