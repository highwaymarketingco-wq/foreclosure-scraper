"""Cherokee SC delinquent tax sale PDFs via WordPress wp-json media API.

Cherokee County SC publishes its annual delinquent tax sale list as PDFs on
its WordPress site. The wp-json media endpoint exposes all attachments
matching a search query, returning direct PDF URLs without HTML scraping.

PDF layout (verified from 2024 Tax Sale List):
    Item Number Owner Name Map Number Description
    1 A AND R PROPERTY MANAGEMENT 099-01-00-022.000 946 N LOGAN ST
    2 A.T.O. 21 LLC 081-12-00-025.000 W FAIRVIEW AVE//800 1/2

No dollar amounts in the PDF rows. The TMS (Map Number) is the parcel_id.

FREE, no login, no CAPTCHA. Endpoint verified live 2026-08-18:
  12 tax sale PDFs found (2021-2025).
"""
from __future__ import annotations

import io
import json
import re
import urllib.request
from typing import Iterable

import structlog

from ...base_scraper import BaseScraper, OUTCOME_OK, OUTCOME_ZERO
from ...http_client import get_bytes
from ...models import Listing, ListingType, PropertyKind

log = structlog.get_logger()

WP_MEDIA_URL = (
    "https://www.cherokeecountysc.gov/wp-json/wp/v2/media"
    "?search=tax%20sale&per_page=100&mime_type=application/pdf"
)

# Cherokee TMS format: NNN-NN-NN-NNN.NNN (e.g. 099-01-00-022.000)
_TMS_RE = re.compile(r"\b(\d{3}-\d{2}-\d{2}-\d{3}\.\d{3})\b")

# Row: <item#> <owner name> <TMS> <description/address>
# Item number is 1-4 digits at the start of the line
_ROW_RE = re.compile(
    r"^\s*(\d{1,4})\s+"        # item number
    r"(.+?)\s+"                 # owner name (non-greedy)
    r"(\d{3}-\d{2}-\d{2}-\d{3}\.\d{3})\s+"  # TMS
    r"(.+)$"                    # description
)


def _parse_pdf_text(text: str) -> list[dict]:
    """Parse Cherokee tax sale PDF text into rows.

    Each data row: <item#> <owner name> <TMS> <description>
    Returns list of dicts with keys: tms, owner, description, item.
    """
    rows: list[dict] = []
    for ln in text.splitlines():
        s = ln.strip()
        if not s or len(s) < 15:
            continue
        # Skip header lines
        if "Item Number" in s or "DELINQUENT" in s.upper() or "NOTICE" in s.upper():
            continue

        m = _ROW_RE.match(s)
        if m:
            item = int(m.group(1))
            owner = re.sub(r"\s+", " ", m.group(2)).strip()
            tms = m.group(3)
            desc = re.sub(r"\s+", " ", m.group(4)).strip()
            if owner and len(owner) > 1:
                rows.append({
                    "item": item,
                    "tms": tms,
                    "owner": owner,
                    "description": desc,
                })

    return rows


def _extract_pdf_text(pdf_bytes: bytes) -> str:
    """Extract text from PDF bytes using pypdf."""
    from pypdf import PdfReader
    reader = PdfReader(io.BytesIO(pdf_bytes))
    parts = []
    for page in reader.pages:
        parts.append(page.extract_text() or "")
    return "\n".join(parts)


class CherokeeDelinquentTaxScraper(BaseScraper):
    slug = "counties_sc.cherokee_delinquent_tax"
    name = "Cherokee SC Delinquent Tax Sale"
    category = "tax_sale"
    timeout_s = 120.0
    expected_min_count = 0  # annual list, may be empty off-season

    async def fetch(self) -> Iterable[Listing]:
        # Step 1: Fetch the wp-json media listing (sync urllib, free, no auth)
        req = urllib.request.Request(
            WP_MEDIA_URL,
            headers={
                "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                              "AppleWebKit/537.36 (KHTML, like Gecko) "
                              "Chrome/120.0.0.0 Safari/537.36",
                "Accept": "application/json",
            },
        )
        try:
            with urllib.request.urlopen(req, timeout=20) as resp:
                media_items = json.loads(resp.read().decode("utf-8"))
        except Exception as e:
            log.error("cherokee_delinquent_tax.media_fetch_error", error=str(e)[:120])
            self.last_outcome = OUTCOME_ZERO
            return

        if not media_items:
            self.last_outcome = OUTCOME_ZERO
            return

        log.info("cherokee_delinquent_tax.media_found", count=len(media_items))

        # Step 2: Download and parse each PDF
        all_rows: list[dict] = []
        for item in media_items:
            pdf_url = item.get("source_url", "")
            if not pdf_url or not pdf_url.endswith(".pdf"):
                continue
            # Skip bidder lists and legal descriptions (no parcels)
            title = ""
            if isinstance(item.get("title"), dict):
                title = item["title"].get("rendered", "")
            else:
                title = str(item.get("title", ""))
            title_lower = title.lower()
            if "bidder" in title_lower or "legal-description" in title_lower:
                continue

            try:
                pdf_bytes = await get_bytes(pdf_url, timeout=60)
                text = _extract_pdf_text(pdf_bytes)
                rows = _parse_pdf_text(text)
                log.info("cherokee_delinquent_tax.pdf_parsed",
                         url=pdf_url[-50:], rows=len(rows))
                all_rows.extend(rows)
            except Exception as e:
                log.warning("cherokee_delinquent_tax.pdf_error",
                            url=pdf_url[-50:], error=str(e)[:100])
                continue

        # Step 3: Emit listings (dedupe by TMS)
        seen: set[str] = set()
        for row in all_rows:
            tms = row.get("tms", "")
            owner = row.get("owner", "")
            if not tms or not owner:
                continue
            if tms in seen:
                continue
            seen.add(tms)

            yield Listing(
                source=self.slug,
                source_url=WP_MEDIA_URL,
                county="Cherokee",
                state="SC",
                parcel_id=tms,
                defendant=owner,
                listing_type=ListingType.TAX_SALE,
                property_kind=PropertyKind.UNKNOWN,
                raw={
                    "sale_type": "delinquent_tax",
                    "description": row.get("description"),
                    "item_number": row.get("item"),
                },
            )

        self.last_outcome = OUTCOME_OK if all_rows else OUTCOME_ZERO
