"""Finkel Law Firm (SC) — monthly PDF parser.

PDF layout puts the property address at the END of one record and the date+county
at the TOP of the next, so consecutive records overlap. We anchor on the docket
number (2024CP3204157 pattern) and reconstruct each block by looking at the
date line that precedes it and the property address line ABOVE that date line.
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
)

DOCKET_RE = re.compile(r"\b(\d{4}CP\d{6,9})\b")
# Date+county concatenated, then time: "05/05/2025Lexington 11:00 A.M"
DATE_COUNTY_TIME_RE = re.compile(
    r"^(\d{1,2}/\d{1,2}/\d{4})([A-Z][a-zA-Z]+)\s+(\d{1,2}:\d{2}\s*[AP]\.?M\.?)",
    re.M,
)
ADDRESS_LINE_RE = re.compile(
    r"^(\d+\s+[A-Z][\w .'\-]+,\s*[A-Za-z .'-]+,\s*SC\s+\d{5})\s*$",
    re.M,
)
DEFENDANTS_RE = re.compile(r"^v\.\s+(.+?)(?=\n[A-Z]|$)", re.M | re.S)
BID_RE = re.compile(r"^([\d,]+(?:\.\d{2})?)\s*$", re.M)


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


def _parse(text: str, source_url: str, slug: str) -> list[Listing]:
    out: list[Listing] = []
    lines = text.split("\n")
    n = len(lines)

    # Find every docket-number line index
    docket_idxs = [i for i, line in enumerate(lines) if DOCKET_RE.search(line)]
    if not docket_idxs:
        return out

    for k, di in enumerate(docket_idxs):
        docket_m = DOCKET_RE.search(lines[di])
        if not docket_m:
            continue
        docket = docket_m.group(1)

        # Find the date+county line above this docket (within a small window)
        date_idx = None
        for j in range(max(0, di - 30), di):
            if DATE_COUNTY_TIME_RE.search(lines[j]):
                date_idx = j
        if date_idx is None:
            continue
        date_m = DATE_COUNTY_TIME_RE.search(lines[date_idx])
        date_str, county, time_str = date_m.group(1), date_m.group(2), date_m.group(3)
        try:
            sale_date = dateparser.parse(date_str)
        except (ValueError, TypeError):
            sale_date = None

        # Property address is the line immediately ABOVE the date line
        addr_line_idx = date_idx - 1
        addr_line = lines[addr_line_idx].strip() if addr_line_idx >= 0 else ""
        addr_m = ADDRESS_LINE_RE.search(addr_line + "\n")
        if not addr_m:
            # Walk up further
            for j in range(date_idx - 1, max(date_idx - 10, -1), -1):
                if ADDRESS_LINE_RE.search(lines[j] + "\n"):
                    addr_line = lines[j].strip()
                    addr_m = ADDRESS_LINE_RE.search(addr_line + "\n")
                    break
        if not addr_m:
            continue
        full_addr = addr_m.group(1)
        # Parse "<street>, <city>, SC <zip>"
        m2 = re.match(r"^(.+?),\s*([A-Za-z .'-]+),\s*SC\s+(\d{5})", full_addr)
        if not m2:
            continue
        street, city, zip_code = m2.group(1).strip(), m2.group(2).strip(), m2.group(3)

        # Sale location: the text between date line and docket line (cleaned)
        sale_loc_text = " ".join(lines[date_idx + 1 : di]).strip()
        sale_loc = re.sub(r"\s+", " ", sale_loc_text)[:400] or None

        # Defendants + plaintiff: the next 3-5 lines after docket
        defendants = None
        plaintiff = None
        bid = None
        # Look for "v. ..." line
        for j in range(di + 1, min(di + 6, n)):
            line = lines[j].strip()
            if line.startswith("v. "):
                # Collect multi-line defendants
                end = j
                while end + 1 < n and not lines[end + 1].strip().startswith(("PIC ", "Lakeview", "U.S. Bank", "Wells", "Bank ", "Mortgage", "Master", "Capital", "Federal")) and not BID_RE.search(lines[end + 1]) and not lines[end + 1].strip().startswith("County:"):
                    end += 1
                    if end - j > 5:
                        break
                defendants = " ".join(lines[j : end + 1]).replace("v. ", "").strip()[:300]
                # Plaintiff line is right after the multi-line defendants
                if end + 1 < n:
                    p_line = lines[end + 1].strip()
                    if p_line and not BID_RE.search(p_line) and not p_line.startswith("County:"):
                        plaintiff = p_line[:200]
                break

        # Bid amount: numeric line near the docket
        for j in range(di + 1, min(di + 12, n)):
            bm = BID_RE.search(lines[j])
            if bm:
                try:
                    bid = float(bm.group(1).replace(",", ""))
                    break
                except ValueError:
                    pass

        out.append(
            Listing(
                source=slug,
                source_url=source_url,
                listing_type=ListingType.FORECLOSURE_SALE,
                property_kind=PropertyKind.UNKNOWN,
                street_address=street,
                city=city,
                state="SC",
                zip_code=zip_code,
                county=county,
                sale_date=sale_date,
                sale_time=time_str,
                sale_location=sale_loc,
                case_number=docket,
                opening_bid=bid,
                plaintiff=plaintiff,
                defendant=defendants,
                trustee="Finkel Law Firm",
                description=(sale_loc or "")[:500] or None,
                first_seen=datetime.utcnow(),
                last_seen=datetime.utcnow(),
            )
        )
    return out


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
            out.extend(_parse(text, url, self.slug))
        return out
