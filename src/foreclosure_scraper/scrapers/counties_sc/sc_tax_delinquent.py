"""SC county delinquent tax / pre-tax-sale scraper.

SC counties publish their delinquent property tax lists in the months before
the annual tax sale (typically held in October/November). Each county has
its own publication mechanism — some PDFs, some HTML tables, some via the
treasurer's site, some via revize.com CMS.

Coverage:
  - Spartanburg, Anderson, Cherokee, Pickens, Oconee, Union, Laurens
  - Each county has a known landing URL; we scrape the page + linked PDFs
  - When a county hasn't published the current year's list yet, scraper
    returns 0 for that county (graceful)

Why this matters: properties on the delinquent-tax list become next year's
tax sale candidates. 6-12 months of lead time vs scraping the auction roster.

POST-SALE FILTER (2026-06-25):
  Pickens links a deep archive of *past* tax sales. Some of those PDFs are
  POST-SALE RESULTS (header: "BIDDER #" / "SALE/BID PRICE", or the file is
  named "...RESULTS...") and some are historical pre-sale listings headed
  "<date> TAX SALE / OWNER (NOW OR FORMERLY)". Either way they are already
  auctioned and are NOT fresh pre-sale leads — harvesting them produced
  ~1216 address-less, parcel-only fake leads (1334 rows total, all Pickens).
  `_is_post_sale_pdf()` now detects these by filename and PDF text markers
  and EXCLUDES them (they are logged + skipped, never emitted as leads).
  A genuinely current/pre-sale delinquent PDF (no results/bidder markers,
  no "now or formerly") still flows through normally.

KNOWN ISSUES (2026-05-14):
  - Spartanburg, Laurens URLs return 404 (CivicEngage CMS migration)
  - Cherokee returns 403 (Cloudflare)
  - Union DNS-fails
  - Pickens currently links only post-sale / historical RESULT PDFs, which
    are now filtered out (see POST-SALE FILTER above)
  - Anderson / Oconee return HTML but no current delinquent-tax tables
Net effect: this scraper currently returns 0 between sale cycles. URLs
should be re-probed each July/August when counties publish that year's
delinquent list. The text-fallback extraction (PARCEL_SC_RE + ADDR_RE)
will pick up any TMS-tagged property the moment a real delinquent PDF is
linked, even if the column layout differs from expected.

Free, pure HTTP (no Apify, no spend).
"""
from __future__ import annotations

import io
import re
from datetime import datetime
from typing import Iterable
from urllib.parse import urljoin

import structlog
from selectolax.parser import HTMLParser

from ...base_scraper import BaseScraper
from ...http_client import client
from ...models import Listing, ListingType, PropertyKind

log = structlog.get_logger()


# Per-county landing URLs known to host delinquent / pre-tax-sale info.
COUNTY_URLS: dict[str, list[str]] = {
    "Anderson": [
        "https://www.andersoncountysc.org/departments-a-z/treasurer/",
    ],
    "Spartanburg": [
        "https://www.spartanburgcounty.gov/treasurer",
        "https://www.spartanburgcounty.gov/delinquent-tax",
    ],
    "Cherokee": [
        "https://cherokeecountysc.gov/delinquent-tax/",
        "https://cherokeecountysc.gov/delinquent-tax/tax-collection-and-tax-sale-procedures/",
    ],
    "Pickens": [
        "https://www.co.pickens.sc.us/departments/delinquent_tax/index.php",
    ],
    "Oconee": [
        "https://oconeesc.com/delinquent-tax",
        "https://oconeesc.com/departments/delinquent-tax",
    ],
    "Union": [
        "https://www.countyofunion.com/treasurer",
        "https://www.unioncountysc.gov/treasurer",
    ],
    "Laurens": [
        "https://www.laurenscountysc.gov/",
        "https://www.laurenscountysc.gov/treasurer",
    ],
}


ADDR_RE = re.compile(
    r"(\b\d{1,6}\s+[A-Z][\w .'\-]{1,80}?\b(?:Road|Rd|Street|St|Drive|Dr|Lane|Ln|"
    r"Avenue|Ave|Highway|Hwy|Boulevard|Blvd|Circle|Cir|Court|Ct|Way|Place|Pl|"
    r"Trail|Trl|Parkway|Pkwy)\.?)(?=[\s,.\n]|$)",
    re.I,
)
PARCEL_SC_RE = re.compile(r"\b\d{3,4}-\d{2}-\d{2}-\d{3,4}\b")  # SC TMS pattern (3/4-2-2-3/4)

# Markers that a PDF is a POST-SALE result (already auctioned) and therefore
# NOT a fresh pre-sale lead. Two distinct Pickens layouts are covered:
#   1. modern "TAX SALE RESULTS" sheets — header has BIDDER #, SALE/BID PRICE
#   2. historical pre-sale listings ("<date> TAX SALE / OWNER (NOW OR FORMERLY)")
#      — these are also for a past sale; "NOW OR FORMERLY" flags that ownership
#      already changed hands at the auction.
# Filename markers are checked separately (PDF link/href) so we can skip the
# fetch entirely; text markers catch result PDFs whose filename looks innocuous.
_POST_SALE_FILENAME_RE = re.compile(r"result", re.I)
_POST_SALE_TEXT_MARKERS = (
    "bidder #",
    "bidder#",
    "bidder number",
    "sale/bid price",
    "sale-bid price",
    "sale bid price",
    "bid price",
    "tax sale results",
    "now or formerly",
)


def _is_post_sale_filename(url_or_label: str) -> bool:
    """True if a PDF link's href/label marks it as a post-sale RESULTS sheet."""
    return bool(_POST_SALE_FILENAME_RE.search(url_or_label or ""))


def _is_post_sale_text(text: str) -> bool:
    """True if the PDF body shows post-sale RESULT / already-auctioned markers
    (BIDDER #, SALE/BID PRICE, 'NOW OR FORMERLY', etc.)."""
    t = (text or "").lower()
    return any(m in t for m in _POST_SALE_TEXT_MARKERS)


def _extract_from_text(text: str, county: str, source_url: str) -> list["Listing"]:
    """Fallback when table-based PDF extraction fails: scan the raw page text
    for SC TMS parcel numbers + nearby addresses. One Listing per parcel.
    Misses owner / amount but at least captures the property identity."""
    out: list[Listing] = []
    seen_parcels: set[str] = set()
    for m in PARCEL_SC_RE.finditer(text):
        parcel = m.group(0)
        if parcel in seen_parcels:
            continue
        seen_parcels.add(parcel)
        # Look for an address within +/- 200 chars of the parcel
        start = max(0, m.start() - 200)
        end = min(len(text), m.end() + 200)
        addr_m = ADDR_RE.search(text[start:end])
        addr = addr_m.group(1).strip() if addr_m else None
        out.append(
            Listing(
                source="counties_sc.sc_tax_delinquent",
                source_url=source_url,
                listing_type=ListingType.TAX_SALE,
                property_kind=PropertyKind.UNKNOWN,
                state="SC",
                county=county,
                street_address=addr,
                parcel_id=parcel,
                description=f"SC delinquent tax candidate ({county}) — parcel {parcel}",
                first_seen=datetime.utcnow(),
                last_seen=datetime.utcnow(),
                raw={"sc_tax_delinquent": {"source": source_url, "extraction": "text_fallback"}},
            )
        )
    return out


def _classify_lines(text: str) -> ListingType:
    t = text.lower()
    if "tax sale" in t or "tax foreclosure" in t or "tax delinquent" in t:
        return ListingType.TAX_SALE
    return ListingType.TAX_SALE  # default — scraper is delinquent-tax-focused


async def _scrape_pdf(c, url: str, county: str) -> list[Listing]:
    """Pull tax-delinquent rows from a PDF. Returns parsed listings."""
    try:
        r = await c.get(url, follow_redirects=True, timeout=30.0)
        if r.status_code != 200:
            return []
        try:
            import pdfplumber
        except ImportError:
            return []
        out: list[Listing] = []
        text_pages: list[str] = []
        with pdfplumber.open(io.BytesIO(r.content)) as pdf:
            # Pre-read the first page's text to gate post-sale RESULT PDFs
            # before doing any row extraction. These are already-auctioned
            # sheets (BIDDER # / SALE/BID PRICE / "NOW OR FORMERLY") and must
            # NOT be emitted as fresh pre-sale leads.
            try:
                first_text = pdf.pages[0].extract_text() if pdf.pages else ""
            except Exception:
                first_text = ""
            if _is_post_sale_text(first_text or ""):
                log.info("sc_tax_delinquent.skip_post_sale_pdf",
                         county=county, url=url, reason="post-sale RESULT markers in PDF text")
                return []
            for page in pdf.pages:
                # Collect text for fallback extraction
                try:
                    text_pages.append(page.extract_text() or "")
                except Exception:
                    pass
                # Try table extraction first
                for tbl in page.extract_tables() or []:
                    if not tbl or len(tbl) < 2:
                        continue
                    # Heuristic header match. SC §12-51-40 lists use SC-specific
                    # names: "Defaulting Taxpayer" (not Owner), "Map Number"/"PIN"/
                    # "TMS" (not Parcel), "Description" (the property) — accept all.
                    header = [str(c or "").lower() for c in tbl[0]]
                    if not any("addr" in h or "owner" in h or "parcel" in h or "tms" in h
                               or "taxpayer" in h or "map" in h or "descript" in h
                               or "pin" in h for h in header):
                        continue
                    # Find columns
                    addr_col = next((i for i, h in enumerate(header) if "addr" in h or "descript" in h), None)
                    owner_col = next((i for i, h in enumerate(header) if "owner" in h or "name" in h or "taxpayer" in h), None)
                    parcel_col = next((i for i, h in enumerate(header) if "parcel" in h or "tms" in h or "map" in h or "pin" in h), None)
                    amt_col = next((i for i, h in enumerate(header) if "amount" in h or "tax" in h or "due" in h), None)

                    for row in tbl[1:]:
                        if not row or all(not c for c in row):
                            continue
                        addr = str(row[addr_col] or "").strip() if addr_col is not None else ""
                        owner = str(row[owner_col] or "").strip() if owner_col is not None else ""
                        parcel = str(row[parcel_col] or "").strip() if parcel_col is not None else ""
                        amt_text = str(row[amt_col] or "").strip() if amt_col is not None else ""
                        if not addr and not parcel and not owner:
                            continue
                        amount = None
                        am = re.search(r"\$?\s*([\d,]+\.?\d*)", amt_text)
                        if am:
                            try:
                                amount = float(am.group(1).replace(",", ""))
                            except ValueError:
                                pass
                        out.append(
                            Listing(
                                source="counties_sc.sc_tax_delinquent",
                                source_url=url,
                                listing_type=ListingType.TAX_SALE,
                                property_kind=PropertyKind.UNKNOWN,
                                state="SC",
                                county=county,
                                street_address=addr or None,
                                parcel_id=parcel or None,
                                defendant=owner[:200] if owner else None,
                                opening_bid=amount,
                                description=(
                                    f"SC delinquent tax / pre-sale candidate "
                                    f"({county} County). Owner: {owner or '?'}, "
                                    f"Tax due: ${amount:,.2f}" if amount else
                                    f"SC delinquent tax / pre-sale candidate ({county} County)"
                                ),
                                first_seen=datetime.utcnow(),
                                last_seen=datetime.utcnow(),
                                raw={"sc_tax_delinquent": {
                                    "source_pdf": url,
                                    "amount_due": amount,
                                }},
                            )
                        )
        # Fallback: if table-based extraction returned nothing, scan the raw
        # page text for SC TMS parcels + nearby addresses. Misses owner /
        # amount but at least captures the property identity, which is the
        # primary signal for downstream enrichment.
        if not out and text_pages:
            full_text = "\n".join(text_pages)
            out.extend(_extract_from_text(full_text, county, url))
        return out
    except Exception as exc:
        log.debug("sc_tax_delinquent.pdf_fail", county=county, url=url, error=str(exc)[:200])
        return []


async def _scrape_html(c, url: str, county: str) -> list[Listing]:
    """Pull listings from HTML tables when present. Also follows linked PDFs."""
    try:
        r = await c.get(url, follow_redirects=True, timeout=20.0)
        if r.status_code != 200:
            return []
    except Exception:
        return []

    out: list[Listing] = []
    tree = HTMLParser(r.text)

    # Resolve relative links against the page URL, honoring any <base href>
    # in the document (Revize/CMS pages set one; the manual rsplit approach
    # 404s on Pickens). urljoin handles "/abs", "rel", "../up" and absolute
    # hrefs correctly.
    join_base = str(r.url) if getattr(r, "url", None) else url
    try:
        base_nodes = tree.css("base")
        if base_nodes:
            base_href = (base_nodes[0].attributes.get("href") or "").strip()
            if base_href:
                join_base = urljoin(join_base, base_href)
    except Exception:
        pass

    # 1. Direct HTML tables
    for tbl in tree.css("table"):
        rows = tbl.css("tr")
        if len(rows) < 2:
            continue
        headers = [c.text(strip=True).lower() for c in rows[0].css("th, td")]
        # SC §12-51-40 column names (Defaulting Taxpayer / Map Number / PIN / TMS /
        # Description) accepted alongside the generic owner/parcel/address terms.
        if not any("addr" in h or "owner" in h or "parcel" in h or "tms" in h
                   or "delinquent" in h or "taxpayer" in h or "map" in h
                   or "descript" in h or "pin" in h for h in headers):
            continue
        addr_col = next((i for i, h in enumerate(headers) if "addr" in h or "descript" in h), None)
        owner_col = next((i for i, h in enumerate(headers) if "owner" in h or "name" in h or "taxpayer" in h), None)
        parcel_col = next((i for i, h in enumerate(headers) if "parcel" in h or "tms" in h or "map" in h or "pin" in h), None)
        amt_col = next((i for i, h in enumerate(headers) if "amount" in h or "tax" in h or "due" in h), None)
        for row in rows[1:]:
            cells = [c.text(strip=True) for c in row.css("td")]
            if not cells:
                continue
            addr = cells[addr_col] if addr_col is not None and addr_col < len(cells) else ""
            owner = cells[owner_col] if owner_col is not None and owner_col < len(cells) else ""
            parcel = cells[parcel_col] if parcel_col is not None and parcel_col < len(cells) else ""
            amt_text = cells[amt_col] if amt_col is not None and amt_col < len(cells) else ""
            if not addr and not parcel and not owner:
                continue
            amount = None
            am = re.search(r"\$?\s*([\d,]+\.?\d*)", amt_text)
            if am:
                try:
                    amount = float(am.group(1).replace(",", ""))
                except ValueError:
                    pass
            out.append(
                Listing(
                    source="counties_sc.sc_tax_delinquent",
                    source_url=url,
                    listing_type=ListingType.TAX_SALE,
                    property_kind=PropertyKind.UNKNOWN,
                    state="SC",
                    county=county,
                    street_address=addr or None,
                    parcel_id=parcel or None,
                    defendant=owner[:200] if owner else None,
                    opening_bid=amount,
                    first_seen=datetime.utcnow(),
                    last_seen=datetime.utcnow(),
                    raw={"sc_tax_delinquent": {
                        "source_html": url,
                        "amount_due": amount,
                    }},
                )
            )

    # 2. Linked PDFs that look like delinquent tax lists
    for a in tree.css("a[href$='.pdf'], a[href*='.pdf?']"):
        href = a.attributes.get("href", "")
        text = a.text(strip=True).lower()
        if not href:
            continue
        if not any(k in (href.lower() + text) for k in
                   ("delinquent", "tax-sale", "tax sale", "tax-foreclosure", "forfeit")):
            continue
        # Skip post-sale RESULT PDFs by filename/label before fetching — these
        # are already-auctioned sheets, not fresh pre-sale leads. (e.g. Pickens
        # "...TAX SALE RESULTS FOR WEBSITE.pdf" / "2025 Delinquent Tax Sale Results")
        if _is_post_sale_filename(href) or _is_post_sale_filename(text):
            log.info("sc_tax_delinquent.skip_post_sale_link",
                     county=county, href=href[:160], label=text[:80])
            continue
        href = urljoin(join_base, href)
        pdf_listings = await _scrape_pdf(c, href, county)
        out.extend(pdf_listings)

    return out


class SCTaxDelinquent(BaseScraper):
    slug = "counties_sc.sc_tax_delinquent"
    name = "SC County Delinquent Tax / Pre-Sale (7 counties)"
    category = "county_tax"
    expected_min_count = 0
    requires_apify = False
    timeout_s = 480.0

    async def fetch(self) -> Iterable[Listing]:
        out: list[Listing] = []
        seen: set[tuple[str, str, str]] = set()
        async with client(timeout=30.0) as c:
            for county, urls in COUNTY_URLS.items():
                county_count = 0
                for url in urls:
                    try:
                        listings = await _scrape_html(c, url, county)
                        for li in listings:
                            sig = (county, (li.parcel_id or "").upper(),
                                   (li.street_address or "").lower())
                            if sig in seen:
                                continue
                            seen.add(sig)
                            out.append(li)
                            county_count += 1
                    except Exception as exc:
                        log.debug("sc_tax_delinquent.url_fail",
                                  county=county, url=url, error=str(exc)[:200])
                log.info("sc_tax_delinquent.county_done", county=county, count=county_count)
        return out
