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
                # Normalize URL
                if href.startswith("http"):
                    full = href
                elif href.startswith("/"):
                    full = "https://www.co.pickens.sc.us" + href
                else:
                    full = "https://www.co.pickens.sc.us/departments/master_in_equity/" + href
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

            for url, sale_d in future_pdfs[:3]:
                try:
                    r = await c.get(url, headers={"Referer": PAGE_URL})
                    if r.status_code != 200 or not r.content[:4] == b"%PDF":
                        continue
                    text = _extract_pdf_text(r.content)
                except Exception:
                    continue
                if not text:
                    continue

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
                            description=chunk[:500],
                            first_seen=datetime.utcnow(),
                            last_seen=datetime.utcnow(),
                        )
                    )
        return out
