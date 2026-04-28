"""Spartanburg County (SC) Master in Equity — new .gov domain + PDF roster.

The actual upcoming-sales list lives in the most recent PDF inside DocumentCenter/Index/114.
We fetch the index, find the latest PDF link, parse rows from it.
"""
from __future__ import annotations

import io
import re
from datetime import datetime, timedelta
from typing import Iterable

from dateutil import parser as dateparser
from selectolax.parser import HTMLParser

from ...base_scraper import BaseScraper
from ...http_client import get_bytes, get_text
from ...models import Listing, ListingType, PropertyKind

INDEX_URL = "https://www.spartanburgcounty.gov/313/Foreclosure-Sale"
DOC_INDEX = "https://www.spartanburgcounty.gov/DocumentCenter/Index/114"

CASE_RE = re.compile(r"\b\d{2,4}-CP-\d{2}-\d{4,6}\b", re.I)
ADDR_RE = re.compile(
    r"(\d+\s+[A-Z][\w .'\-]+(?:Road|Rd|Street|St|Drive|Dr|Lane|Ln|Avenue|Ave|"
    r"Highway|Hwy|Boulevard|Blvd|Circle|Cir|Court|Ct|Way|Place|Pl|Trail|Trl|Parkway|Pkwy)\.?)",
    re.I,
)
DATE_RE = re.compile(
    r"\b(?:\d{1,2}/\d{1,2}/\d{2,4}|"
    r"(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\s+\d{1,2},?\s+\d{4})\b",
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


def _parse_rows(text: str, source_url: str, slug: str) -> list[Listing]:
    today = datetime.utcnow()
    horizon = today + timedelta(days=120)
    cutoff = today - timedelta(days=2)
    out: list[Listing] = []
    # Each property block tends to start with a case number
    chunks = re.split(r"(?=\b\d{2,4}-CP-\d{2}-)", text)
    for chunk in chunks:
        chunk = chunk.strip()
        if len(chunk) < 30:
            continue
        case_m = CASE_RE.search(chunk)
        if not case_m:
            continue
        addr_m = ADDR_RE.search(chunk)
        date_m = DATE_RE.search(chunk)
        sale_date = None
        if date_m:
            try:
                sale_date = dateparser.parse(date_m.group(0))
            except (ValueError, TypeError):
                pass
        if sale_date and not (cutoff <= sale_date <= horizon):
            continue  # active-only
        out.append(
            Listing(
                source=slug,
                source_url=source_url,
                listing_type=ListingType.FORECLOSURE_SALE,
                property_kind=PropertyKind.UNKNOWN,
                street_address=addr_m.group(1) if addr_m else None,
                state="SC",
                county="Spartanburg",
                case_number=case_m.group(0),
                sale_date=sale_date,
                description=chunk[:500],
                first_seen=datetime.utcnow(),
                last_seen=datetime.utcnow(),
            )
        )
    return out


class SpartanburgMasterInEquity(BaseScraper):
    slug = "counties_sc.spartanburg_master_in_equity"
    name = "Spartanburg County (SC) Master in Equity"
    category = "county_court"
    timeout_s = 180.0

    async def fetch(self) -> Iterable[Listing]:
        out: list[Listing] = []
        # Walk the document-center index for the latest "Foreclosure Sale List" PDF
        try:
            idx_html = await get_text(DOC_INDEX, timeout=45.0)
        except Exception:
            return out

        tree = HTMLParser(idx_html)
        pdf_links: list[str] = []
        for a in tree.css("a[href*='/DocumentCenter/View/']"):
            href = a.attributes.get("href", "")
            if not href:
                continue
            full = href if href.startswith("http") else "https://www.spartanburgcounty.gov" + href
            label = (a.text(strip=True) or "").lower()
            if any(k in label for k in ("sale list", "foreclosure", "roster")):
                pdf_links.append(full)
        # If nothing labeled, take the most-recent ~3 View links
        if not pdf_links:
            pdf_links = [
                ("https://www.spartanburgcounty.gov" + a.attributes.get("href", ""))
                for a in tree.css("a[href*='/DocumentCenter/View/']")
            ][:3]

        for pdf_url in pdf_links[:5]:
            try:
                data = await get_bytes(pdf_url, timeout=60.0)
            except Exception:
                continue
            text = _extract_pdf_text(data)
            if not text:
                continue
            out.extend(_parse_rows(text, pdf_url, self.slug))
        return out
