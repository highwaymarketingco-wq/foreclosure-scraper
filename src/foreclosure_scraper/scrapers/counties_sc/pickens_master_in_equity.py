"""Pickens County SC Master in Equity — session-aware PDF fetch.

The county lists PDFs at sales_rosters.php; clicking a link redirects to
cms5.revize.com which 404s direct curl requests. We solve it by using a
single httpx.AsyncClient session that loads the listing page first (seeding
cookies + referer) and then GETs the PDF.
"""
from __future__ import annotations

import io
import re
from datetime import datetime, timedelta
from typing import Iterable
from urllib.parse import urljoin

from dateutil import parser as dateparser
from selectolax.parser import HTMLParser

from ...base_scraper import BaseScraper
from ...http_client import client
from ...models import Listing, ListingType, PropertyKind

PAGE_URL = "https://www.co.pickens.sc.us/departments/master_in_equity/sales_rosters.php"

CASE_RE = re.compile(r"\b\d{2,4}-CP-\d{2}-\d{4,6}\b", re.I)
ADDR_RE = re.compile(
    r"(\d+\s+[A-Z][\w .'\-]+(?:Road|Rd|Street|St|Drive|Dr|Lane|Ln|Avenue|Ave|"
    r"Highway|Hwy|Boulevard|Blvd|Circle|Cir|Court|Ct|Way|Place|Pl|Trail|Trl|Parkway|Pkwy)\.?)",
    re.I,
)
DATE_RE = re.compile(r"\b(?:\d{1,2}/\d{1,2}/\d{2,4})\b")
MONTH_HEADER_RE = re.compile(
    r"\b((?:January|February|March|April|May|June|July|August|September|October|November|December))\s+(\d{4})\b",
    re.I,
)

# Sold-price patterns commonly used in SC MIE results PDFs. Order
# matters — most-specific first.
SOLD_PRICE_PATTERNS = [
    # "High Bid: $45,000" / "high bid of $45,000"
    re.compile(r"high\s+bid(?:\s+of)?\s*[:=]?\s*\$\s*([\d,]+(?:\.\d{2})?)", re.I),
    # "Sold for $45,000" / "Sold to XYZ LLC for $45,000" — the buyer
    # can be multi-word, so we match anything up to "for $" non-greedily,
    # but cap the gap to ~80 chars so we don't bridge across cases.
    re.compile(r"sold\s+(?:to\s+[^$\n]{1,80}?\s+)?for\s*\$\s*([\d,]+(?:\.\d{2})?)", re.I),
    # "Final Bid: $45,000"
    re.compile(r"final\s+bid\s*[:=]?\s*\$\s*([\d,]+(?:\.\d{2})?)", re.I),
    # "Bid Amount: $45,000" / "Successful Bid: $45,000"
    re.compile(r"(?:successful\s+)?bid\s+amount\s*[:=]?\s*\$\s*([\d,]+(?:\.\d{2})?)", re.I),
    # "Sale Price: $45,000"
    re.compile(r"sale\s+price\s*[:=]?\s*\$\s*([\d,]+(?:\.\d{2})?)", re.I),
    # "$45,000 SOLD" — money-amount immediately followed by SOLD keyword
    re.compile(r"\$\s*([\d,]+(?:\.\d{2})?)\s+SOLD\b", re.I),
]

# Phrases indicating an upset bid was filed (Pickens results sometimes
# show successive upset bids; we want the FINAL one).
UPSET_BID_RE = re.compile(
    r"(?:upset|upset\s+bid|advanced\s+bid)\s*[:=]?\s*\$\s*([\d,]+(?:\.\d{2})?)",
    re.I,
)

# Result-status words. If the chunk has "WITHDRAWN" / "POSTPONED" /
# "DISMISSED" we don't trust the sold price (no actual sale happened).
NON_SALE_STATUS_RE = re.compile(
    r"\b(WITHDRAWN|POSTPONED|DISMISSED|RESCINDED|CANCELLED|CANCELED|"
    r"NO\s+SALE|NOT\s+SOLD|NO\s+BID)\b",
    re.I,
)


def _is_results_pdf(url: str, label: str = "") -> bool:
    """RESULTS PDFs report past sales (with sold prices). Upcoming-sale
    rosters list scheduled sales with opening bids only. The link label
    + URL fragment both reliably mark RESULTS PDFs at Pickens."""
    haystack = f"{url} {label}".upper()
    return "RESULTS" in haystack


def _extract_sold_price(chunk: str) -> tuple[float | None, str]:
    """Parse the highest credible sold-price figure from a Pickens
    RESULTS-PDF chunk. Prefers explicit upset-bid (final hammer) over
    the initial bid when multiple amounts appear in the same chunk.

    Returns (price, source_pattern_name). Price is None when:
      * No matching pattern found
      * Chunk has a NON_SALE_STATUS marker (withdrawn/postponed/etc.)
      * Parsed amount is implausible (<$100 or >$10M)
    """
    if NON_SALE_STATUS_RE.search(chunk):
        return None, "non_sale_status"

    # Upset bids are always the final word — prefer them when present.
    upset_amounts = []
    for m in UPSET_BID_RE.finditer(chunk):
        try:
            upset_amounts.append(float(m.group(1).replace(",", "")))
        except ValueError:
            continue
    if upset_amounts:
        amt = max(upset_amounts)  # final upset is the largest
        if 100 <= amt <= 10_000_000:
            return amt, "upset_bid"

    for pat in SOLD_PRICE_PATTERNS:
        m = pat.search(chunk)
        if not m:
            continue
        try:
            amt = float(m.group(1).replace(",", ""))
        except ValueError:
            continue
        if 100 <= amt <= 10_000_000:
            return amt, pat.pattern[:30]

    return None, "no_match"


def _extract_pdf_text(data: bytes) -> str:
    try:
        from pypdf import PdfReader
    except ImportError:
        return ""
    try:
        reader = PdfReader(io.BytesIO(data))
        return "\n".join((p.extract_text() or "") for p in reader.pages)
    except Exception:
        return ""


class PickensMasterInEquity(BaseScraper):
    slug = "counties_sc.pickens_master_in_equity"
    name = "Pickens County (SC) Master in Equity"
    category = "county_court"
    timeout_s = 120.0
    # Pickens publishes monthly rosters as PDFs. They legitimately have
    # months with no active sales — verified 2026-05-06 with the live
    # "MAY 2026 -NO ACTIVE SALES" PDF. expected_min_count=0 prevents
    # false REGRESSED alerts on dry months; a real regression here looks
    # like a code-level error (PDF parser broken), not an empty count.
    expected_min_count = 0

    async def fetch(self) -> Iterable[Listing]:
        out: list[Listing] = []
        today = datetime.utcnow()

        async with client(timeout=45.0) as c:
            # Step 1: Load the listing page to seed cookies. If direct httpx
            # returns a JS-shell, fall back to Scrapling stealth.
            html = ""
            try:
                r = await c.get(PAGE_URL)
                if r.status_code == 200:
                    html = r.text
            except Exception:
                pass

            # If no PDF links visible in the direct fetch, try Scrapling
            if html and "pdf" not in html.lower():
                html = ""
            if not html:
                try:
                    from scrapling.fetchers import StealthyFetcher
                    result = await StealthyFetcher.async_fetch(
                        PAGE_URL, headless=True, network_idle=True, timeout=60000,
                    )
                    body = getattr(result, "body", b"")
                    html = body.decode("utf-8", errors="replace") if isinstance(body, bytes) else str(body or "")
                except ImportError:
                    return out
                except Exception:
                    return out

            if not html:
                return out

            tree = HTMLParser(html)
            # The page declares <base href="https://www.co.pickens.sc.us/">, so
            # bare relative PDF hrefs resolve against the DOMAIN ROOT, not the
            # /departments/master_in_equity/ path. Honor the declared <base> if
            # present; otherwise default to the domain root.
            base_href = "https://www.co.pickens.sc.us/"
            base_el = tree.css_first("base[href]")
            if base_el:
                bh = (base_el.attributes.get("href") or "").strip()
                if bh:
                    base_href = bh
            pdf_links: list[tuple[str, datetime | None]] = []
            for a in tree.css("a[href$='.pdf'], a[href*='.pdf?']"):
                href = a.attributes.get("href", "")
                label = a.text(strip=True) or ""
                # Try to extract month/year from the link label
                mh = MONTH_HEADER_RE.search(label)
                sale_d = None
                if mh:
                    try:
                        sale_d = dateparser.parse(f"{mh.group(1)} 1, {mh.group(2)}")
                    except (ValueError, TypeError):
                        pass
                # Normalize URL. Bare relative hrefs (e.g. "JULY 2026 6.2.26.pdf")
                # must resolve against the declared <base href> (domain root),
                # NOT the page path — resolving against the path 404s.
                if href.startswith("http"):
                    full = href
                else:
                    full = urljoin(base_href, href)
                pdf_links.append((full, sale_d))

            # Pick the latest PDF — Pickens posts past sale results too,
            # so accept anything within the last 365 days (covers their full
            # publishing cadence — typically monthly).
            future_pdfs = [(u, d) for u, d in pdf_links if d and d >= today - timedelta(days=365)]
            if not future_pdfs:
                # Last resort: try the most recent few PDFs by URL ordering
                future_pdfs = pdf_links[:5]
            future_pdfs.sort(key=lambda x: x[1] or today, reverse=True)
            # Cap at top 6 (covers ~6 months of monthly rosters)
            future_pdfs = future_pdfs[:6]

            # Track which PDFs are RESULTS (past sales w/ prices) vs upcoming
            # rosters. Carries through to the chunk loop so we can tag listings.
            for url, sale_d in future_pdfs[:6]:  # bumped 3 -> 6 so we get more results PDFs
                try:
                    r = await c.get(url, headers={"Referer": PAGE_URL})
                    if r.status_code != 200 or not r.content[:4] == b"%PDF":
                        continue
                    text = _extract_pdf_text(r.content)
                except Exception:
                    continue
                if not text:
                    continue

                is_results = _is_results_pdf(url)

                # Extract a per-document sale date from the PDF header if any
                doc_date = sale_d
                if not doc_date:
                    md = MONTH_HEADER_RE.search(text)
                    if md:
                        try:
                            doc_date = dateparser.parse(f"{md.group(1)} 1, {md.group(2)}")
                        except (ValueError, TypeError):
                            pass

                # Each row anchored on case number
                for chunk in re.split(r"(?=\b\d{2,4}-CP-\d{2}-)", text):
                    chunk = chunk.strip()
                    if len(chunk) < 30:
                        continue
                    case_m = CASE_RE.search(chunk)
                    if not case_m:
                        continue
                    addr_m = ADDR_RE.search(chunk)

                    # RESULTS-PDF specifics: extract sold price + tag as
                    # foreclosure-sale RESULT (already past, in the sold pool).
                    sold_price = None
                    sold_source_pattern = None
                    raw_extras: dict = {}
                    if is_results:
                        sold_price, sold_source_pattern = _extract_sold_price(chunk)
                        if sold_price is not None:
                            raw_extras["actual_sold_price"] = sold_price
                            raw_extras["sold_price_pattern"] = sold_source_pattern
                            raw_extras["sale_result_pdf"] = url

                    out.append(
                        Listing(
                            source=self.slug,
                            source_url=url,
                            listing_type=ListingType.FORECLOSURE_SALE,
                            property_kind=PropertyKind.UNKNOWN,
                            street_address=addr_m.group(1) if addr_m else None,
                            state="SC",
                            county="Pickens",
                            case_number=case_m.group(0),
                            sale_date=doc_date,
                            opening_bid=sold_price,  # also surface as opening_bid so calc/dashboard reads it
                            description=chunk[:500],
                            first_seen=datetime.utcnow(),
                            last_seen=datetime.utcnow(),
                            raw=(
                                {
                                    # actual_sold_price at top level so
                                    # enrichment_foreclosure_sold_comps reads it
                                    # via _opening_or_judgment.
                                    "actual_sold_price": raw_extras["actual_sold_price"],
                                    "pickens_mie": raw_extras,
                                }
                                if raw_extras else {}
                            ),
                        )
                    )
        return out
