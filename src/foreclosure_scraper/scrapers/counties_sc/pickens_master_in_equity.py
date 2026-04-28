"""Pickens County (SC) Master in Equity — new domain at co.pickens.sc.us, PDF rosters."""
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

INDEX_URL = "https://www.co.pickens.sc.us/departments/master_in_equity/sales_rosters.php"

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


class PickensMasterInEquity(BaseScraper):
    slug = "counties_sc.pickens_master_in_equity"
    name = "Pickens County (SC) Master in Equity"
    category = "county_court"
    timeout_s = 180.0

    async def fetch(self) -> Iterable[Listing]:
        out: list[Listing] = []
        try:
            html = await get_text(INDEX_URL, timeout=45.0)
        except Exception:
            return out

        tree = HTMLParser(html)
        # Pull most recent ~3 PDF links
        pdfs = []
        for a in tree.css("a[href$='.pdf']"):
            href = a.attributes.get("href", "")
            if not href:
                continue
            full = href if href.startswith("http") else "https://www.co.pickens.sc.us" + (
                href if href.startswith("/") else "/departments/master_in_equity/" + href
            )
            pdfs.append(full)
        pdfs = pdfs[:3]  # most recent first by listing order

        today = datetime.utcnow()
        horizon = today + timedelta(days=120)
        cutoff = today - timedelta(days=2)

        for pdf_url in pdfs:
            try:
                data = await get_bytes(pdf_url, timeout=60.0)
            except Exception:
                continue
            text = _extract_pdf_text(data)
            if not text:
                continue
            for chunk in re.split(r"(?=\b\d{2,4}-CP-\d{2}-)", text):
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
                    continue
                out.append(
                    Listing(
                        source=self.slug,
                        source_url=pdf_url,
                        listing_type=ListingType.FORECLOSURE_SALE,
                        property_kind=PropertyKind.UNKNOWN,
                        street_address=addr_m.group(1) if addr_m else None,
                        state="SC",
                        county="Pickens",
                        case_number=case_m.group(0),
                        sale_date=sale_date,
                        description=chunk[:500],
                        first_seen=datetime.utcnow(),
                        last_seen=datetime.utcnow(),
                    )
                )
        return out
