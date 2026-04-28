"""Finkel Law Firm (SC) — publishes upcoming-sales as a monthly PDF.

Two offices, both follow the same format: Webs.pdf gets overwritten in place.
"""
from __future__ import annotations

import io
import re
from datetime import datetime
from typing import Iterable

from dateutil import parser as dateparser

from ...base_scraper import BaseScraper
from ...http_client import get_bytes
from ...models import Listing, ListingType, PropertyKind

PDF_URLS = (
    "https://www.finkellaw.com/images/Webs.pdf",
    "https://www.finkellawcharleston.com/images/Webs.pdf",
    "https://www.finkellaw.com/documents/Sales.pdf",  # fallback / legacy
)

# Verified regex against actual Finkel PDF content
DEFENDANT_RE = re.compile(r"Defendant Name:\s*(.+?)(?=\n[A-Z0-9]|\nTMS|\nProperty)", re.S)
TMS_RE = re.compile(r"TMS Number:\s*([\w\-\.]+)")
ADDR_RE = re.compile(r"Property Address:\s*(.+?)(?=\n|Sale Date)", re.S)
SALE_DATE_RE = re.compile(r"Sale Date:\s*(\d{1,2}/\d{1,2}/\d{4})")
COUNTY_RE = re.compile(r"County:\s*([A-Z][a-z]+(?:\s[A-Z][a-z]+)?)")
SALE_TIME_RE = re.compile(r"Sale Date:\s*\d{1,2}/\d{1,2}/\d{4}[\s\S]{0,80}?(\d{1,2}:\d{2}\s*[AP]\.?M\.?)")
DOCKET_RE = re.compile(r"Docket Number:\s*(\d{4}\s*CP\s*\d{4,9})")
SALE_LOC_RE = re.compile(r"Sale Location:\s*(.+?)(?=Property Address|Plaintiff|\n[A-Z])", re.S)
MAX_BID_RE = re.compile(r"Plaintiff (?:Maximum |Max(?:imum)? )?Bid Amount:\s*\$?([\d,]+(?:\.\d{2})?)")


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


def _parse_block(block: str, source_url: str, slug: str) -> Listing | None:
    addr_m = ADDR_RE.search(block)
    sale_m = SALE_DATE_RE.search(block)
    if not addr_m and not sale_m:
        return None
    sale_date = None
    if sale_m:
        try:
            sale_date = dateparser.parse(sale_m.group(1))
        except (ValueError, TypeError):
            pass
    addr_text = addr_m.group(1).strip().replace("\n", " ") if addr_m else ""

    # Address line is usually "<street>, <city>, SC <zip>"
    street = addr_text
    city = None
    zip_code = None
    m = re.match(r"^(.+?),\s*([A-Za-z .'-]+),\s*SC\s+(\d{5})", addr_text)
    if m:
        street = m.group(1).strip()
        city = m.group(2).strip()
        zip_code = m.group(3).strip()

    bid = None
    bm = MAX_BID_RE.search(block)
    if bm:
        try:
            bid = float(bm.group(1).replace(",", ""))
        except ValueError:
            pass

    return Listing(
        source=slug,
        source_url=source_url,
        listing_type=ListingType.FORECLOSURE_SALE,
        property_kind=PropertyKind.UNKNOWN,
        street_address=street,
        city=city,
        state="SC",
        zip_code=zip_code,
        county=(COUNTY_RE.search(block) or [None, None])[1] if COUNTY_RE.search(block) else None,
        parcel_id=(TMS_RE.search(block) or [None, None])[1] if TMS_RE.search(block) else None,
        sale_date=sale_date,
        sale_time=(SALE_TIME_RE.search(block) or [None, None])[1] if SALE_TIME_RE.search(block) else None,
        sale_location=(SALE_LOC_RE.search(block).group(1).strip().replace("\n", " ") if SALE_LOC_RE.search(block) else None),
        case_number=(DOCKET_RE.search(block).group(1).replace(" ", "") if DOCKET_RE.search(block) else None),
        defendant=(DEFENDANT_RE.search(block).group(1).strip().replace("\n", " ") if DEFENDANT_RE.search(block) else None),
        opening_bid=bid,
        plaintiff="Finkel Law Firm (trustee)",  # Finkel is the substitute trustee
        first_seen=datetime.utcnow(),
        last_seen=datetime.utcnow(),
    )


class Finkel(BaseScraper):
    slug = "law_firms.finkel"
    name = "Finkel Law Firm"
    category = "law_firm"
    timeout_s = 180.0

    async def fetch(self) -> Iterable[Listing]:
        out: list[Listing] = []
        for url in PDF_URLS:
            try:
                data = await get_bytes(url, timeout=60.0)
            except Exception:
                continue
            text = _extract_pdf_text(data)
            if not text:
                continue
            # Each block starts with "Defendant Name:" — split on that anchor
            blocks = re.split(r"(?=Defendant Name:)", text)
            for block in blocks:
                if "Defendant Name:" not in block:
                    continue
                li = _parse_block(block, url, self.slug)
                if li:
                    out.append(li)
        return out
