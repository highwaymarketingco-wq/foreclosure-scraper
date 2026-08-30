"""Swain County NC — Tax Foreclosure notice (PDF download).

Swain County publishes tax foreclosure notices as a PDF download at
swaincountync.gov.  The PDF contains the list of properties going to
tax sale with owner names and parcel numbers.

Free, public, no login.
Slug: counties_nc.swain_tax_foreclosures
Category: county_tax
ListingType: TAX_SALE
"""
from __future__ import annotations

import io
import re
from datetime import datetime
from typing import Iterable
from urllib.parse import urljoin

import structlog

from ...base_scraper import BaseScraper
from ...http_client import get_bytes, get_text
from ...models import Listing, ListingType, PropertyKind

log = structlog.get_logger()

PAGE_URL = "https://www.swaincountync.gov/"


def _pdf_text(data: bytes) -> str:
    try:
        import pdfplumber
        with pdfplumber.open(io.BytesIO(data)) as pdf:
            return "\n".join((p.extract_text() or "") for p in pdf.pages)
    except Exception as exc:
        log.warning("swain_tax.pdf_parse_fail", error=str(exc)[:160])
        return ""


class SwainTaxForeclosures(BaseScraper):
    slug = "counties_nc.swain_tax_foreclosures"
    name = "Swain County NC Tax Foreclosures"
    category = "county_tax"
    timeout_s = 120.0
    expected_min_count = 0
    optional = True

    async def fetch(self) -> Iterable[Listing]:
        out: list[Listing] = []
        try:
            html = await get_text(PAGE_URL, impersonate=True, timeout=40.0)
        except Exception as exc:
            log.warning("swain_tax.fetch_fail", error=str(exc)[:160])
            return out

        if not html or len(html) < 200:
            return out

        # Find PDF links related to tax foreclosure/sale
        pdf_links = re.findall(r'href="([^"]*(?:tax|foreclos|sale|auction|delinquent)[^"]*\.pdf[^"]*)"', html, re.I)
        # Broader search if no specific links found
        if not pdf_links:
            pdf_links = re.findall(r'href="([^"]*\.pdf[^"]*)"', html, re.I)

        for pdf_url in pdf_links[:5]:
            full_url = urljoin(PAGE_URL, pdf_url)
            try:
                data = await get_bytes(full_url, timeout=60.0)
            except Exception:
                continue
            if not data or data[:4] != b"%PDF":
                continue
            text = _pdf_text(data)
            if not text:
                continue

            # Parse PDF text — look for parcel + owner + address patterns
            for line in text.splitlines():
                line = line.strip()
                if len(line) < 5:
                    continue
                # Skip headers
                if any(h in line.lower() for h in ("notice", "swain county", "tax office", "page ")):
                    continue

                parcel = None
                m = re.search(r"\b(\d{4,}[-\s]?[\d.]+)\b", line)
                if m:
                    parcel = m.group(1)

                amount = None
                m = re.search(r"\$[\d,]+", line)
                if m:
                    try:
                        amount = float(m.group().replace("$", "").replace(",", ""))
                    except ValueError:
                        pass

                addr = None
                m = re.search(r"\d+\s+\w+[\w\s]+", line)
                if m:
                    addr = m.group().strip()

                if not parcel and not addr and not amount:
                    continue

                out.append(Listing(
                    source="counties_nc.swain_tax_foreclosures",
                    source_url=full_url,
                    listing_type=ListingType.TAX_SALE,
                    property_kind=PropertyKind.UNKNOWN,
                    state="NC",
                    county="Swain",
                    parcel_id=parcel,
                    street_address=addr,
                    judgment_amount=amount,
                    description=line[:300],
                    first_seen=datetime.utcnow(),
                    last_seen=datetime.utcnow(),
                    raw={"swain_tax_foreclosures": {"pdf_url": full_url, "line": line[:200]}},
                ))

        log.info("swain_tax.done", count=len(out))
        return out
