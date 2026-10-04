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
from urllib.parse import urljoin, urlparse

import httpx
from selectolax.parser import HTMLParser

from ...base_scraper import BaseScraper
from ...document_links import stamp_documents
from ...http_client import client
from ...models import Listing, ListingType, PropertyKind

# (state, county_name, base_domain) — covers our 6 priority counties + a few extras
# we already have direct scrapers for (still useful as a cross-check / discovery layer).
COUNTY_SITES: tuple[tuple[str, str, str], ...] = (
    # Greenville/Greenwood/Newberry/Abbeville removed per scope narrowing 2026-05.
    ("SC", "Spartanburg", "https://www.spartanburgcounty.gov"),
    ("SC", "Cherokee",    "https://www.cherokeecountysc.gov"),
    ("SC", "Anderson",    "https://www.andersoncountysc.org"),
    ("SC", "Pickens",     "https://www.co.pickens.sc.us"),
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

# Address regex (street + optional city + state). The \b before the suffix
# alternation is load-bearing: without it, re.I lets the alternation match a
# SUBSTRING inside an unrelated word ("Addr" in "Address" satisfies "...Dr"),
# which is exactly how this scraper was fabricating addresses like "103685
# Physical Addr" out of a Gaston County page's own "Physical Address:" label
# (live-confirmed 2026-10-01; the identical bug was also found and fixed in
# counties_nc.nc_civicplus_tax_sale's copy of this pattern the same day).
ADDR_RE = re.compile(
    r"(\d+\s+[A-Z][\w .'\-]+\b(?:Rd|Road|St|Street|Dr|Drive|Ln|Lane|Ave|Avenue|"
    r"Hwy|Highway|Cir|Circle|Ct|Court|Way|Pl|Place|Trl|Trail|Pkwy|Parkway|Blvd)\b)",
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

# EXTRACTION-COMPLETENESS AUDIT 2026-10-03: _parse_listings only ever reads
# the page's own TEXT. Live-verified across all 12 counties: most of the
# "relevant" keyword-matched pages (sheriff/MOE/tax-foreclosure pages on
# Anderson/Oconee/Henderson/Spartanburg) parse to ZERO listings not because
# nothing is published there, but because the real sale roster is a LINKED
# PDF, never embedded in the page text at all. Anderson County's own
# Master-in-Equity page links 226 PDFs -- almost all site chrome (employment
# applications, holiday schedules, an unrelated road-sign PDF) but several
# are the real thing: "October-6-2026-Sale-List.pdf" (an upcoming sale,
# live-confirmed), "September-3-2026-Deficiency-Sale-Results.pdf". Henderson
# County's tax-foreclosure page links a real "notice_of_sale.pdf" the same
# way. A blind PDF-href scan would reintroduce exactly the page-wide-chrome
# anti-pattern city_websites.search was disabled for (see that module's
# docstring) -- confirmed live on Oconee's own delinquent-tax page, which
# links an unrelated bond-financing TEFRA notice on a DIFFERENT domain
# (scjeda.com) via a shared sidebar widget. So this filter is deliberately
# narrow: the PDF's own filename must carry a real sale-roster keyword (not
# the page URL's broader KEYWORDS, which would let "notice"/"deed" alone
# over-match), AND it must be same-domain as the page that linked it.
_REAL_NOTICE_PDF_RE = re.compile(
    r"(sale[-_]?list|sale[-_]?result|deficiency[-_]?sale|tax[-_]?foreclosure|"
    r"notice[-_]?of[-_]?sale|foreclosure[-_]?sale|master[-_]?in[-_]?equity)",
    re.I,
)
_CHROME_PDF_RE = re.compile(
    r"(employment|application|holiday|schedule|sign-|signage|logo|\bw9\b|"
    r"brochure|newsletter|job-posting|\brfp\b)", re.I,
)
_PDF_HREF_RE = re.compile(r'href="([^"]+\.pdf[^"]*)"', re.I)
# A sale-list filename usually embeds its own date ("October-6-2026-Sale-
# List.pdf") -- a real, free sale_date with no extra request (no PDF fetch
# needed), and the one thing that keeps this fallback row from being
# dateless-filtered by main._active_only() (this slug is not in
# DATELESS_OK_SOURCES, same as the rest of this file's rows).
_PDF_FILENAME_DATE_RE = re.compile(
    r"(January|February|March|April|May|June|July|August|September|"
    r"October|November|December)[-_](\d{1,2})[-_](\d{4})",
    re.I,
)


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
        # Fallback: split by case-number pattern (each case = one listing).
        cases = sorted(list(NC_CASE_RE.finditer(flat)) + list(SC_CASE_RE.finditer(flat)),
                       key=lambda m: m.start())
        if not cases:
            return []
        # Build each chunk as the FULL gap flanking this case match -- back to
        # the previous case's end, forward to the next case's start -- rather
        # than a fixed +-200/400 char window centered on the match. A
        # same-direction fixed window reaches into a NEIGHBOR's own fields
        # whenever records run back-to-back with no separator (live-confirmed
        # on Gaston's foreclosure-sale page: the real layout is "Owner /
        # Parcel / Address / ... / File Number: <CASE>" with the case number
        # at the END of its own record and the next record's Owner/Parcel
        # starting immediately after -- a +400-char forward window pulled in
        # the NEXT record's parcel number: "File Number: 24 M 867" paired its
        # own correctly-matched address "2508 Gardner St" with parcel 120452,
        # which actually belongs to the following record). The two-sided gap
        # still resolves correctly for a page whose fields TRAIL the case
        # number instead, because regex .search() returns the leftmost match
        # and this record's own trailing fields sit textually before the next
        # case's leading text.
        cases = cases[:30]
        chunks = []
        for i, m in enumerate(cases):
            left = cases[i - 1].end() if i > 0 else max(0, m.start() - 600)
            right = cases[i + 1].start() if i + 1 < len(cases) else min(len(flat), m.end() + 600)
            chunks.append(flat[left:right])

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


def _pdf_filename_date(url: str) -> datetime | None:
    m = _PDF_FILENAME_DATE_RE.search(url)
    if not m:
        return None
    try:
        from dateutil import parser as dateparser
        return dateparser.parse(f"{m.group(1)} {m.group(2)}, {m.group(3)}", fuzzy=True)
    except Exception:
        return None


def _real_notice_pdfs(html: str, page_url: str) -> list[str]:
    """Strictly-matched real sale-roster PDFs linked from a county page --
    same domain as the page, filename carries a real sale-list/notice
    keyword, and not a chrome document (see the module-level comment on
    _REAL_NOTICE_PDF_RE for the live evidence)."""
    page_netloc = urlparse(page_url).netloc
    seen: set[str] = set()
    out: list[str] = []
    for href in _PDF_HREF_RE.findall(html):
        full = urljoin(page_url, _decode_html_entities(href))
        if full in seen:
            continue
        if urlparse(full).netloc != page_netloc:
            continue  # cross-domain link (e.g. an unrelated agency's own notice)
        if _CHROME_PDF_RE.search(full):
            continue
        if not _REAL_NOTICE_PDF_RE.search(full):
            continue
        seen.add(full)
        out.append(full)
    return out


def _pdf_listing(pdf_url: str, discovered_via: str, state: str, county: str) -> Listing:
    """A fallback Listing anchored to a real sale-roster PDF the page text
    scan found nothing for (case/address/parcel data lives in the PDF, not
    the page). Carries the PDF via raw['documents'] so enrich_doc_ocr can
    read the real content later."""
    u = pdf_url.lower()
    ltype = (ListingType.FORECLOSURE_SALE
             if any(k in u for k in ("foreclos", "deficiency", "master", "sale-list", "sale_list"))
             else (ListingType.TAX_SALE if "tax" in u else ListingType.UNKNOWN))
    sale_date = _pdf_filename_date(pdf_url)
    fname = pdf_url.rsplit("/", 1)[-1]
    li = Listing(
        source="counties.sitemap_walker",
        source_url=pdf_url,
        listing_type=ltype,
        property_kind=PropertyKind.UNKNOWN,
        state=state,
        county=county,
        sale_date=sale_date,
        description=f"{county} County {state} — real sale-roster document discovered via sitemap crawl: {fname}",
        first_seen=datetime.utcnow(),
        last_seen=datetime.utcnow(),
        raw={"sitemap_walker": {"discovered_via": discovered_via}},
    )
    stamp_documents(li, [pdf_url])
    return li


async def walk_county(c: httpx.AsyncClient, state: str, county: str, base: str) -> list[Listing]:
    """Walk one county's sitemap and harvest listings."""
    urls = await _fetch_sitemap(c, base)
    if not urls:
        return []
    relevant = [u for u in urls if _matches_keywords(u)][:25]  # cap per county
    out: list[Listing] = []
    seen_pdfs: set[str] = set()
    for url in relevant:
        html = await _fetch_page(c, url)
        if not html:
            continue
        out.extend(_parse_listings(html, url, state, county))
        for pdf in _real_notice_pdfs(html, url):
            if pdf in seen_pdfs:
                continue
            seen_pdfs.add(pdf)
            out.append(_pdf_listing(pdf, url, state, county))
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
