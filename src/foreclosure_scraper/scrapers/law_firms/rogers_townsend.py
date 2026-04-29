"""Rogers Townsend — direct PDF + HTML fetches via pdfplumber for structured tables.

SC report: clean PDF table parsed via pdfplumber.extract_tables().
NC report: 'NC_Listings.pdf' is actually served as HTML despite the .pdf extension.
"""
from __future__ import annotations

import io
import re
from datetime import datetime
from typing import Iterable

import pdfplumber
from dateutil import parser as dateparser
from selectolax.parser import HTMLParser

from ...base_scraper import BaseScraper
from ...http_client import client
from ...models import Listing, ListingType, PropertyKind

SC_URL = "https://rogerstownsend.com/reports/SC_Listings.pdf"
NC_URL = "https://rogerstownsend.com/reports/NC_Listings.pdf"

PARCEL_RE = re.compile(r"\b\d{2,3}-\d{2,3}-\d{2,3}-\d{1,4}(?:-\d+)?\b")
DATE_RE = re.compile(r"\b\d{1,2}/\d{1,2}/\d{2,4}\b")
ADDR_RE = re.compile(
    r"^(\d+\s+[A-Z][\w .'\-]+(?:Road|Rd|Street|St|Drive|Dr|Lane|Ln|Avenue|Ave|"
    r"Highway|Hwy|Boulevard|Blvd|Circle|Cir|Court|Ct|Way|Place|Pl|Trail|Trl|Parkway|Pkwy)\.?)",
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


def _parse_sc_pdf_with_pdfplumber(data: bytes, slug: str) -> list[Listing]:
    """SC PDF: 7-column tabular list. Use pdfplumber for structured row extraction.
    Columns: County | Street Address | City | Tax Map No. | Sale Date | DJ Demand | Bid
    """
    import structlog
    log = structlog.get_logger()
    out: list[Listing] = []
    try:
        pdf = pdfplumber.open(io.BytesIO(data))
        log.info("rt.pdf.open", pages=len(pdf.pages), bytes=len(data))
    except Exception as exc:
        log.warning("rt.pdf.open_failed", error=str(exc)[:120], bytes=len(data))
        return out

    last_county = None
    total_rows = 0
    for page_idx, page in enumerate(pdf.pages):
        try:
            tables = page.extract_tables() or []
        except Exception as exc:
            log.warning("rt.pdf.extract_failed", page=page_idx, error=str(exc)[:80])
            continue
        log.info("rt.pdf.page", page=page_idx, tables=len(tables))
        for table in tables:
            total_rows += len(table)
            for row in table:
                if not row or len(row) < 5:
                    continue
                # Skip header row
                if (row[0] or "").strip().lower() == "county":
                    continue
                county = (row[0] or "").strip() or last_county
                if county:
                    last_county = county
                street = (row[1] or "").strip() or None
                city = (row[2] or "").strip() or None
                parcel = (row[3] or "").strip() or None
                date_raw = (row[4] or "").strip()
                bid_raw = (row[6] or "").strip() if len(row) > 6 else ""

                if not date_raw or not street:
                    continue

                sale_date = None
                try:
                    sale_date = dateparser.parse(date_raw)
                except (ValueError, TypeError):
                    continue

                bid = None
                bm = re.search(r"\$?\s*([\d,]+(?:\.\d{2})?)", bid_raw)
                if bm and bm.group(1):
                    try:
                        bid = float(bm.group(1).replace(",", ""))
                    except ValueError:
                        pass

                out.append(
                    Listing(
                        source=slug,
                        source_url=SC_URL,
                        listing_type=ListingType.FORECLOSURE_SALE,
                        property_kind=PropertyKind.UNKNOWN,
                        street_address=street,
                        city=city,
                        state="SC",
                        county=county,
                        parcel_id=parcel,
                        sale_date=sale_date,
                        opening_bid=bid,
                        trustee="Rogers Townsend",
                        first_seen=datetime.utcnow(),
                        last_seen=datetime.utcnow(),
                    )
                )
    pdf.close()
    log.info("rt.pdf.parsed", total_rows=total_rows, listings_extracted=len(out))
    return out


def _parse_nc_html(html: str, slug: str) -> list[Listing]:
    out: list[Listing] = []
    tree = HTMLParser(html)
    for tbl in tree.css("table"):
        for row in tbl.css("tr"):
            cells = [c.text(strip=True) for c in row.css("td")]
            if len(cells) < 4:
                continue
            text = " | ".join(cells)
            date_m = DATE_RE.search(text)
            if not date_m:
                continue
            try:
                sale_date = dateparser.parse(date_m.group(0))
            except (ValueError, TypeError):
                continue
            addr_m = ADDR_RE.search(text)
            bid = None
            bm = re.search(r"\$\s*([\d,]+\.?\d*)", text)
            if bm:
                try:
                    bid = float(bm.group(1).replace(",", ""))
                except ValueError:
                    pass
            # First cell is usually county
            county = cells[0].replace(" County", "").strip() if cells else None
            out.append(
                Listing(
                    source=slug,
                    source_url=NC_URL,
                    listing_type=ListingType.FORECLOSURE_SALE,
                    property_kind=PropertyKind.UNKNOWN,
                    street_address=addr_m.group(1) if addr_m else None,
                    state="NC",
                    county=county,
                    sale_date=sale_date,
                    opening_bid=bid,
                    trustee="Rogers Townsend",
                    description=text[:400],
                    first_seen=datetime.utcnow(),
                    last_seen=datetime.utcnow(),
                )
            )
    return out


class RogersTownsend(BaseScraper):
    slug = "law_firms.rogers_townsend"
    name = "Rogers Townsend"
    category = "law_firm"
    timeout_s = 120.0
    expected_min_count = 10

    async def fetch(self) -> Iterable[Listing]:
        out: list[Listing] = []
        async with client(timeout=45.0) as c:
            # SC: real PDF
            try:
                r = await c.get(SC_URL)
                if r.status_code == 200 and r.content[:4] == b"%PDF":
                    out.extend(_parse_sc_pdf_with_pdfplumber(r.content, self.slug))
            except Exception:
                pass
            # NC: served as HTML even though .pdf extension
            try:
                r = await c.get(NC_URL)
                if r.status_code == 200:
                    ct = r.headers.get("content-type", "").lower()
                    if "html" in ct or r.content[:6].lower().startswith(b"<!doct"):
                        out.extend(_parse_nc_html(r.text, self.slug))
                    elif r.content[:4] == b"%PDF":
                        text = _extract_pdf_text(r.content)
                        if text:
                            out.extend(_parse_sc_pdf(text, self.slug))  # same parser shape works
            except Exception:
                pass
        return out
