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
import html as _html
import io
import re
from datetime import datetime
from typing import Iterable, Optional

import structlog

from ...base_scraper import BaseScraper
from ...models import Listing, ListingType, PropertyKind

log = structlog.get_logger()

# CivicPlus county sites in NC that we haven't built dedicated scrapers for.
# Each entry: county -> base URL. We walk /sitemap.aspx or /departments pages.
# 2026-09-21: four entries pointed at hosts that no longer resolve (curl exit 6) and were
# repaired, each replacement fetched once and answering HTTP 200 with the county's own title.
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
    "Graham": "https://grahamcounty.org",              # was www.grahamcounty.gov (DNS dead); www.grahamcounty.org does not resolve either
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
    "Mitchell": "https://www.mitchellcountync.gov",
    "Montgomery": "https://www.montgomerycountync.com",
    "Moore": "https://www.moorecountync.gov",
    "Nash": "https://www.nashcountync.gov",
    "New Hanover": "https://www.nhcgov.com",
    "Northampton": "https://www.northamptonnc.com",    # was northamptonnc.gov (DNS dead)
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
    "Tyrrell": "http://tyrrellcounty.org",             # was tyrrellcountync.gov (DNS dead); http only, redirects to /en/
    "Union": "https://www.unioncountync.gov",
    "Vance": "https://www.vancecounty.org",
    "Warren": "https://www.warren-county.com",
    "Washington": "https://washconc.org",              # was washingtoncountync.gov (DNS dead)
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

# Address regex (simple street address). A trailing \b on the suffix word is
# required — without it, re.IGNORECASE lets the alternation match a SUBSTRING
# inside an unrelated word ("Addr" in "Address" satisfies "...Dr", "au[ct]ion"
# satisfies "...Ct"), which is exactly how this scraper was fabricating
# addresses like "103685 Physical Addr" and "00 will be due at the time of
# auction" out of page boilerplate (live-confirmed on Gaston and Cherokee
# County pages, 2026-10-01 audit). See also counties.sitemap_walker, which had
# the identical bug in its own copy of this pattern.
ADDR_RE = re.compile(
    r"(\d{2,6}\s+[A-Z][\w\s.]{2,30}(?:Street|St|Avenue|Ave|Road|Rd|Lane|Ln|"
    r"Drive|Dr|Boulevard|Blvd|Place|Pl|Court|Ct|Way|Trail|Trl|"
    r"Circle|Cir|Highway|Hwy)\b[\w\s.]*?)(?:\s|$|,|\n|\.)",
    re.IGNORECASE
)

# Money regex
MONEY_RE = re.compile(r"\$[\d,]+(?:\.\d{2})?")

# Parcel ID regex (NC PINs are typically 10-15 chars alphanumeric)
PARCEL_RE = re.compile(r"\b(\d{6,15}[A-Z]?|\d{3,4}[A-Z]\d{3,4}[A-Z]?)\b")

# Hyphenated NC PIN, e.g. "4595-00-04-4495-000" (seen on Kania Law Firm /
# courthouse-vendor tax-sale tables — Cherokee and others use this format;
# PARCEL_RE above never matches it because of the embedded hyphens).
PIN_HYPHEN_RE = re.compile(r"\b(\d{3,4}-\d{2}-\d{2}-\d{3,4}-\d{2,4})\b")

# NC tax-foreclosure case numbers in either the short "25 M 388" / "26-CVD-178"
# form or the long eCourts "26CV000240-190" form (both seen across NC CivicPlus
# county tax pages).
NC_CASE_RE = re.compile(
    r"\b(\d{2}\s?-?\s?(?:CVD?|SP|M)\s?-?\s?\d{2,8}(?:-\d{2,4})?)\b", re.IGNORECASE
)

# "<County> vs. <Defendant>," / "<County> vs. <Defendant>-" (the defendant name
# in a prose tax-foreclosure announcement, e.g. Alamance's <li> list).
VS_RE = re.compile(
    r"\bvs\.?\s+([A-Z][^,]*?)(?:,|\s*[-–—]\s*(?:a |an )?"
    r"(?:house|vacant|lot|tract|parcel|land))", re.IGNORECASE
)

# "located at/on <description>" — the free-text location clause that follows
# the defendant name in the same prose format.
LOCATED_RE = re.compile(r"located\s+(?:at|on)\s+([^,\n]+(?:,\s*[A-Za-z .]+)?)", re.IGNORECASE)

# "Parcel ID#<id>" / "Parcel ID #<id>" anchor used by the prose <li> format.
PARCEL_ID_HASH_RE = re.compile(r"Parcel\s*ID\s*#\s*([0-9A-Z]{4,15})", re.IGNORECASE)

_LI_RE = re.compile(r"<li[^>]*>(.*?)</li>", re.DOTALL | re.IGNORECASE)

# Date regex
DATE_RE = re.compile(
    r"(\d{1,2}[/-]\d{1,2}[/-]\d{2,4}|\d{1,2}\s+\w{3,9}\s+\d{4}|"
    r"\w{3,9}\s+\d{1,2},?\s+\d{4})"
)


def _strip_tags(raw_html: str) -> str:
    # unescape FIRST: a bare "&nbsp;" run (used as column padding on pages
    # like Cherokee's) is not whitespace to \s until it is decoded to U+00A0,
    # so decoding after the regex sub would leave entity text sitting inside
    # an owner-name capture and silently break the None/len(60) sanity check.
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", _html.unescape(raw_html))).strip()


def _parse_li_blocks(html: str, county: str, url: str) -> list[Listing]:
    """Prose '<li>' tax-foreclosure announcements, one property per item, e.g.
    Alamance: "Alamance County vs. Marshall Yarbrough, Jr., Heirs- a house
    located at 728 Rainbow Ave., Burlington, NC- Parcel ID#132044."

    Parsed PER LIST ITEM so the defendant/address/parcel of one property can
    never bleed into another's (the free-text Pattern 2 fallback below works
    off a fixed character window and was pairing an address from one <li>
    with the parcel ID of the NEXT <li> — live-confirmed on Alamance, where
    "728 Rainbow Ave" belongs to parcel 132044 but was emitted with parcel
    172225, a vacant lot on a different street entirely)."""
    out: list[Listing] = []
    for li_html in _LI_RE.findall(html):
        text = _strip_tags(li_html)
        pid_m = PARCEL_ID_HASH_RE.search(text)
        if not pid_m:
            continue
        parcel = pid_m.group(1)
        vs_m = VS_RE.search(text)
        defendant = vs_m.group(1).strip(" ,.-") if vs_m else None
        addr_m = ADDR_RE.search(text)
        address = addr_m.group(1).strip(" ,.-") if addr_m else None
        loc_m = LOCATED_RE.search(text)
        location_text = loc_m.group(1).strip(" ,.-") if loc_m else None
        case_m = NC_CASE_RE.search(text)
        desc_bits = [p for p in (defendant and f"vs. {defendant}", location_text) if p]
        out.append(Listing(
            source="counties_nc.nc_civicplus_tax_sale",
            source_url=url,
            street_address=address,
            legal_description=None if address else location_text,
            county=county,
            state="NC",
            listing_type=ListingType.TAX_SALE,
            property_kind=PropertyKind.LAND if (not address and location_text
                                                and "vacant" in text.lower()) else PropertyKind.UNKNOWN,
            parcel_id=parcel,
            case_number=(re.sub(r"\s+", "", case_m.group(1)).upper() if case_m else None),
            owner_name=defendant,
            defendant=defendant,
            description=(f"{county} County NC tax foreclosure" +
                         (f": {' — '.join(desc_bits)}" if desc_bits else ""))[:400],
            raw={
                "nc_civicplus_tax_sale": {
                    "county": county,
                    "page_url": url,
                    "parcel_id": parcel,
                    "defendant": defendant,
                    "location_text": location_text,
                    "pattern": "li_prose",
                }
            },
        ))
    return out


def _parse_case_table_blocks(text: str, county: str, url: str) -> list[Listing]:
    """A flat 'Case# ... Owner ... PIN#' table with no real <table>/<tr> markup
    (Cherokee's Kania-Law-Firm-style page: the three columns are &nbsp;-padded
    plain text, so Pattern 1's <tr> regex finds nothing and the free-text
    Pattern 2 fallback was fabricating a street address out of unrelated
    boilerplate ("00 will be due at the time of auction") because the page
    genuinely has no street address to find. Anchored on repeating case-number
    matches so a single stray case-shaped number elsewhere on the page can't
    produce a fake one-row "table"."""
    out: list[Listing] = []
    case_matches = list(NC_CASE_RE.finditer(text))
    if len(case_matches) < 2:
        return out
    for i, m in enumerate(case_matches):
        start = m.end()
        end = case_matches[i + 1].start() if i + 1 < len(case_matches) else min(len(text), start + 300)
        block = text[start:end]
        pin_m = PIN_HYPHEN_RE.search(block) or PARCEL_RE.search(block)
        if not pin_m:
            continue
        owner_part = block[:pin_m.start()]
        owner = re.sub(r"[|\s]+", " ", owner_part).strip(" |.-")
        owner = owner if owner and len(owner) < 60 and re.search(r"[A-Za-z]", owner) else None
        case_no = re.sub(r"\s+", "", m.group(1)).upper()
        out.append(Listing(
            source="counties_nc.nc_civicplus_tax_sale",
            source_url=url,
            county=county,
            state="NC",
            listing_type=ListingType.TAX_SALE,
            property_kind=PropertyKind.UNKNOWN,
            parcel_id=pin_m.group(1),
            case_number=case_no,
            owner_name=owner,
            defendant=owner,
            description=(f"{county} County NC tax foreclosure: case {case_no}, "
                         f"PIN {pin_m.group(1)}" + (f", owner {owner}" if owner else ""))[:400],
            raw={
                "nc_civicplus_tax_sale": {
                    "county": county,
                    "page_url": url,
                    "parcel_id": pin_m.group(1),
                    "case_number": case_no,
                    "owner": owner,
                    "pattern": "case_table",
                }
            },
        ))
    return out


def _pdf_to_text(content: bytes) -> str:
    """Extract real text from a PDF response body, same `pypdf` pattern already
    proven in the sibling nc_county_pdf_delinquent_tax.py. Returns "" (never
    raises) on a corrupt/scanned-image-only PDF, so callers fall through to
    the stealth-fetch retry exactly as they do for any other empty fetch."""
    try:
        from pypdf import PdfReader
        return "\n".join((p.extract_text() or "") for p in PdfReader(io.BytesIO(content)).pages)
    except Exception as exc:
        log.debug("nc_civicplus.pdf_extract_failed", error=str(exc)[:120])
        return ""


async def _fetch_text(url: str) -> str:
    """Fetch page text via httpx.

    This module's own docstring has said since it was written that it
    "also checks those known [PDF/XLSX] URLs" -- but every PDF response was
    being handed straight to `resp.text`, httpx's raw bytes-as-string decode
    of binary PDF content, which is unreadable garbage no downstream regex
    can ever match (confirmed live, 2026-10-03: Davidson County's own
    2.8MB/35-page "Tax-Foreclosures-PDF", updated by the county 2026-09-17,
    decoded via `.text` to a `%PDF-1.7 ... obj<</Type/Catalog...` byte dump).
    Extracting real text via `pypdf` first -- the SAME library already used
    for this exact purpose by nc_county_pdf_delinquent_tax.py -- let the
    EXISTING `_parse_tax_sale_page()` tiers correctly find 21 real pending-
    sale properties (real street addresses, parcel IDs, dollar amounts)
    sitting behind that one PDF with no other code change: the scraper
    could already parse this shape of data, it was just never given real
    text to parse."""
    try:
        from ...http_client import client
        async with client(timeout=20.0) as c:
            resp = await c.get(url, headers={
                "User-Agent": "Mozilla/5.0 (foreclosure-scraper)",
                "Accept": "text/html,*/*",
            })
            if resp.status_code != 200:
                return ""
            if resp.content[:4] == b"%PDF":
                return _pdf_to_text(resp.content)
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

    # Strip tags for text extraction (unescape first — see _strip_tags)
    text = re.sub(r"<[^>]+>", " ", _html.unescape(html))
    text = re.sub(r"\s+", " ", text)

    # Tier 0a: prose <li> announcements, one property per item (Alamance style).
    # Tried first and returned immediately when it finds anything — this page
    # shape carries a defendant name and a Parcel ID# per item that the
    # looser table/free-text patterns below cannot reliably attribute to the
    # right property, so once this shape is detected it is authoritative.
    li_listings = _parse_li_blocks(html, county, url)
    if li_listings:
        return li_listings

    # Tier 0b: a flat, un-tagged "Case# / Owner / PIN#" table (Cherokee /
    # Kania-Law-Firm-vendor style — no <table> markup at all, so Tier 1 below
    # never sees it).
    case_table_listings = _parse_case_table_blocks(text, county, url)
    if case_table_listings:
        return case_table_listings

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
                        self.partial.extend(found)
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
