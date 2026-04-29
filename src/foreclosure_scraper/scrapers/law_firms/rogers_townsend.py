"""Rogers Townsend — direct PDF + HTML fetches.

SC report: clean PDF table.
NC report: 'NC_Listings.pdf' is actually served as HTML despite the .pdf extension.
"""
from __future__ import annotations

import io
import re
from datetime import datetime
from typing import Iterable

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


def _parse_sc_pdf(text: str, slug: str) -> list[Listing]:
    """SC PDF is a tabular list: County | Address | City | Tax Map | Sale Date | DJ Demand | Bid"""
    out: list[Listing] = []
    last_county = None
    # Each row is split across newlines; we look for sale-date pattern as the row anchor
    lines = text.split("\n")
    for i, line in enumerate(lines):
        line = line.strip()
        if not line:
            continue
        date_m = DATE_RE.search(line)
        if not date_m:
            continue
        # Sale date found — parse it
        try:
            sale_date = dateparser.parse(date_m.group(0))
        except (ValueError, TypeError):
            continue

        # Look at a few lines around this for structured data
        ctx = " | ".join(lines[max(0, i - 4) : i + 2])
        addr_m = ADDR_RE.search(ctx)
        parcel_m = PARCEL_RE.search(ctx)
        # County: first capitalized word at start of context (carries from previous row if blank)
        county = None
        for tok in ctx.split():
            if tok and tok[0].isupper() and tok.isalpha() and len(tok) > 3 and tok not in ("State", "South", "North", "Carolina"):
                county = tok
                break
        if not county:
            county = last_county
        else:
            last_county = county

        # Bid amount near end of row
        bid = None
        bm = re.search(r"\$\s*([\d,]+\.?\d*)", ctx)
        if bm:
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
                street_address=addr_m.group(1) if addr_m else None,
                state="SC",
                county=county,
                parcel_id=parcel_m.group(0) if parcel_m else None,
                sale_date=sale_date,
                opening_bid=bid,
                trustee="Rogers Townsend",
                description=ctx[:400],
                first_seen=datetime.utcnow(),
                last_seen=datetime.utcnow(),
            )
        )
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
                if r.status_code == 200:
                    if "pdf" in r.headers.get("content-type", "").lower() or r.content[:4] == b"%PDF":
                        text = _extract_pdf_text(r.content)
                        if text:
                            out.extend(_parse_sc_pdf(text, self.slug))
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
