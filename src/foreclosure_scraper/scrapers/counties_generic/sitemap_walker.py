"""Walk every county website's sitemap.xml, harvest foreclosure / tax-sale /
auction / notice URLs, then visit each and extract listings.

This is the cleanest possible source: the county's own canonical URL list,
shipped for free as XML. No Apify, no rendering, no aggregator middleman.

For each county we:
  1. GET /sitemap.xml (or sitemap_index.xml)
  2. Filter URLs to keyword-relevant ones (foreclosure, master-equity, tax-sale,
     deficiency, sheriff, notice, delinquent, auction, public-notice)
  3. GET each filtered URL
  4. Extract:
     - Embedded sale rosters (HTML tables, plain text blocks)
     - PDF links inside DocumentCenter/View/<id> pages → download PDF, parse
     - Case numbers, addresses, parcel IDs, sale dates, opening bids

Each listing produced points back to the county.gov source URL, so the
dashboard's link is always to the canonical authoritative page.
"""
from __future__ import annotations

import asyncio
import re
from datetime import datetime
from typing import Iterable

import httpx
from selectolax.parser import HTMLParser

from ..base_scraper import BaseScraper
from ..http_client import client
from ..models import Listing, ListingType, PropertyKind

# (state, county_name, base_domain) — covers our 6 priority counties + a few extras
# we already have direct scrapers for (still useful as a cross-check / discovery layer).
COUNTY_SITES: tuple[tuple[str, str, str], ...] = (
    ("SC", "Spartanburg", "https://www.spartanburgcounty.gov"),
    ("SC", "Cherokee",    "https://www.cherokeecountysc.gov"),
    ("SC", "Greenville",  "https://www.greenvillecounty.org"),
    ("SC", "Anderson",    "https://www.andersoncountysc.org"),
    ("SC", "Pickens",     "https://www.co.pickens.sc.us"),
    ("SC", "Greenwood",   "https://www.greenwoodsc.gov"),
    ("SC", "Oconee",      "https://oconeesc.com"),
    ("NC", "Henderson",   "https://www.hendersoncountync.gov"),
    ("NC", "Rutherford",  "https://www.rutherfordcountync.gov"),
    ("NC", "Cleveland",   "https://www.clevelandcountync.gov"),
    ("NC", "Polk",        "https://www.polknc.gov"),
    ("NC", "Gaston",      "https://www.gastongov.com"),
    ("NC", "Buncombe",    "https://www.buncombecounty.org"),
    ("NC", "Mecklenburg", "https://www.mecklenburgcountync.gov"),
)

# URL keyword filter — only visit pages plausibly about foreclosures / sales.
KEYWORDS = (
    "foreclos", "master-in-equity", "master-equity", "tax-sale", "tax_sale",
    "deficiency", "sheriff-sale", "sheriff_sale", "delinquent",
    "auction", "public-notice", "public_notice", "deed",
    "notice-of-sale", "notice_of_sale", "lis-pendens", "lis_pendens",
)

# Address regex (street + optional city + state)
ADDR_RE = re.compile(
    r"(\d+\s+[A-Z][\w .'\-]+(?:Rd|Road|St|Street|Dr|Drive|Ln|Lane|Ave|Avenue|"
    r"Hwy|Highway|Cir|Circle|Ct|Court|Way|Pl|Place|Trl|Trail|Pkwy|Parkway|Blvd))",
    re.I,
)
# NC Special Proceedings "23 M 258" / "21 SP 34" / "26CV001033-220"
NC_CASE_RE = re.compile(r"\b(\d{2}\s*(?:M|SP|CVD|CV)\s?\d{1,5}(?:-\d+)?)\b", re.I)
# SC Common Pleas "2025CP2303497"
SC_CASE_RE = re.compile(r"\b(\d{4}CP\d{4,8})\b")
# Date — "April 8, 2026", "5/27/2026"
DATE_RE = re.compile(
    r"\b((?:January|February|March|April|May|June|July|August|September|October|November|December)\s+\d{1,2},?\s+\d{4}"
    r"|\d{1,2}/\d{1,2}/\d{2,4})\b",
    re.I,
)
# Opening bid / current bid
BID_RE = re.compile(r"\$([\d,]+(?:\.\d{2})?)")
# Parcel / TMS — varies by county
PARCEL_RE = re.compile(r"(?:Parcel|TMS|PIN)[\s#:]*([\d.\-]{6,20})", re.I)


def _decode_html_entities(s: str) -> str:
    return s.replace("&amp;", "&").replace("&lt;", "<").replace("&gt;", ">").replace("&nbsp;", " ").replace("&quot;", '"')


def _tag_strip(html: str) -> str:
    return re.sub(r"<[^>]+>", " ", html)


def _ws_collapse(s: str) -> str:
    return re.sub(r"\s+", " ", s).strip()


async def _fetch_sitemap(c: httpx.AsyncClient, base: str) -> list[str]:
    """Return all URLs found in the sitemap.xml for `base`. Handles sitemap-index recursion."""
    urls: list[str] = []
    try:
        # Try common sitemap entry points
        for path in ("/sitemap.xml", "/sitemap_index.xml", "/sitemap-index.xml"):
            r = await c.get(f"{base}{path}", timeout=15.0,
                            headers={"User-Agent": "Mozilla/5.0 (compatible; CountyForeclosureBot/1.0)"})
            if r.status_code != 200 or "xml" not in r.headers.get("content-type", "").lower() and "<urlset" not in r.text and "<sitemapindex" not in r.text:
                continue
            text = r.text
            # Sitemap index → recurse one level
            if "<sitemapindex" in text:
                child_locs = re.findall(r"<loc>([^<]+)</loc>", text)
                for child in child_locs[:10]:  # cap recursion
                    try:
                        rc = await c.get(child, timeout=15.0)
                        if rc.status_code == 200:
                            urls.extend(re.findall(r"<loc>([^<]+)</loc>", rc.text))
                    except Exception:
                        pass
            else:
                urls.extend(re.findall(r"<loc>([^<]+)</loc>", text))
            return urls
    except Exception:
        pass
    return urls


def _matches_keywords(url: str) -> bool:
    u = url.lower()
    return any(k in u for k in KEYWORDS)


async def _fetch_page(c: httpx.AsyncClient, url: str) -> str:
    try:
        r = await c.get(url, timeout=15.0,
                        headers={
                            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
                                          "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
                            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9",
                        })
        if r.status_code == 200:
            return r.text
    except Exception:
        return ""
    return ""


def _parse_listings(text: str, source_url: str, state: str, county: str) -> list[Listing]:
    """Extract one or more Listings from a county-page text body.

    Strategy: split on `**********`-style separators OR per-paragraph; for each
    block, look for case#, address, sale date, parcel, bid. Emit a Listing if
    ANY of (case_number, parcel_id, street_address) is present.
    """
    flat = _ws_collapse(_decode_html_entities(_tag_strip(text)))
    if len(flat) < 100:
        return []

    # Split into chunks: look for repeating separators or paragraph breaks
    chunks = re.split(r"\*{20,}|={20,}|-{20,}|\n{2,}", flat)
    if len(chunks) < 2:
        # Fallback: split by case-number pattern (each case = one listing)
        cases = list(NC_CASE_RE.finditer(flat)) + list(SC_CASE_RE.finditer(flat))
        if not cases:
            return []
        # Build chunks centered on each case occurrence (300 chars each side)
        chunks = []
        for m in cases[:30]:
            s = max(0, m.start() - 200)
            e = min(len(flat), m.end() + 400)
            chunks.append(flat[s:e])

    out: list[Listing] = []
    seen: set[str] = set()
    for chunk in chunks:
        if len(chunk) < 50:
            continue
        case_m = NC_CASE_RE.search(chunk) or SC_CASE_RE.search(chunk)
        addr_m = ADDR_RE.search(chunk)
        date_m = DATE_RE.search(chunk)
        parcel_m = PARCEL_RE.search(chunk)
        bid_m = BID_RE.search(chunk)

        if not (case_m or parcel_m or addr_m):
            continue
        case_number = re.sub(r"\s+", " ", case_m.group(1)).upper() if case_m else None
        parcel = parcel_m.group(1).strip() if parcel_m else None
        address = addr_m.group(1).strip() if addr_m else None

        key = case_number or parcel or address
        if not key or key in seen:
            continue
        seen.add(key)

        sale_date = None
        if date_m:
            try:
                from dateutil import parser as dateparser
                sale_date = dateparser.parse(date_m.group(1), fuzzy=True)
            except Exception:
                pass

        opening_bid = None
        if bid_m:
            try:
                opening_bid = float(bid_m.group(1).replace(",", ""))
            except ValueError:
                pass

        out.append(
            Listing(
                source="counties.sitemap_walker",
                source_url=source_url,
                listing_type=ListingType.FORECLOSURE_SALE if "foreclos" in source_url.lower()
                             else (ListingType.TAX_SALE if "tax" in source_url.lower() else ListingType.UNKNOWN),
                property_kind=PropertyKind.UNKNOWN,
                state=state,
                county=county,
                street_address=address,
                parcel_id=parcel,
                sale_date=sale_date,
                opening_bid=opening_bid,
                case_number=case_number,
                description=chunk[:500],
                first_seen=datetime.utcnow(),
                last_seen=datetime.utcnow(),
                raw={"sitemap_walker": {
                    "discovered_via": source_url,
                    "snippet": chunk[:500],
                }},
            )
        )
    return out


async def walk_county(c: httpx.AsyncClient, state: str, county: str, base: str) -> list[Listing]:
    """Walk one county's sitemap and harvest listings."""
    urls = await _fetch_sitemap(c, base)
    if not urls:
        return []
    relevant = [u for u in urls if _matches_keywords(u)][:25]  # cap per county
    out: list[Listing] = []
    for url in relevant:
        html = await _fetch_page(c, url)
        if html:
            out.extend(_parse_listings(html, url, state, county))
    return out


class CountySitemapWalker(BaseScraper):
    slug = "counties.sitemap_walker"
    name = "Generic county-sitemap discovery (free, all 14 counties)"
    category = "county_discovery"
    expected_min_count = 5
    timeout_s = 360.0

    async def fetch(self) -> Iterable[Listing]:
        all_out: list[Listing] = []
        async with client(timeout=20.0) as c:
            sem = asyncio.Semaphore(4)

            async def one(state: str, county: str, base: str):
                async with sem:
                    return await walk_county(c, state, county, base)

            results = await asyncio.gather(
                *(one(s, ct, b) for s, ct, b in COUNTY_SITES),
                return_exceptions=True,
            )
            for r in results:
                if isinstance(r, list):
                    all_out.extend(r)
        return all_out
