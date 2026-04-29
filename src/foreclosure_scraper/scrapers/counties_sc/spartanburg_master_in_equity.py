"""Spartanburg County SC Master in Equity — direct PDF View ID 3392."""
from __future__ import annotations

import io
import re
from datetime import datetime, timedelta
from typing import Iterable

from dateutil import parser as dateparser

from ...base_scraper import BaseScraper
from ...http_client import client
from ...models import Listing, ListingType, PropertyKind

PDF_URLS = (
    "https://www.spartanburgcounty.gov/DocumentCenter/View/3392/Sale-Results",
    "https://www.spartanburgcounty.gov/DocumentCenter/View/11824/Deficiency-Sale",
)

CASE_RE = re.compile(r"\b\d{2,4}-\d{3,5}\b")
ADDR_RE = re.compile(
    r"(\d+\s+[A-Z][\w .'\-]+(?:Road|Rd|Street|St|Drive|Dr|Lane|Ln|Avenue|Ave|"
    r"Highway|Hwy|Boulevard|Blvd|Circle|Cir|Court|Ct|Way|Place|Pl|Trail|Trl|Parkway|Pkwy)\.?)",
    re.I,
)
SALE_DATE_RE = re.compile(
    r"(?:Re-?Bid Date|Sale Date|Master[''']s Sale)\s*[:—-]?\s*"
    r"((?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\s+\d{1,2},?\s+\d{4})",
    re.I,
)
BID_RE = re.compile(r"\$\s*([\d,]+(?:\.\d{2})?)")


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


class SpartanburgMasterInEquity(BaseScraper):
    slug = "counties_sc.spartanburg_master_in_equity"
    name = "Spartanburg County (SC) Master in Equity"
    category = "county_court"
    timeout_s = 90.0
    expected_min_count = 5

    async def fetch(self) -> Iterable[Listing]:
        out: list[Listing] = []
        today = datetime.utcnow()
        horizon = today + timedelta(days=120)
        cutoff = today - timedelta(days=2)

        async with client(timeout=45.0) as c:
            for url in PDF_URLS:
                try:
                    r = await c.get(url)
                    if r.status_code != 200 or r.content[:4] != b"%PDF":
                        continue
                    text = _extract_pdf_text(r.content)
                except Exception:
                    continue
                if not text:
                    continue

                # Document-level sale date
                doc_sale_date = None
                sd_m = SALE_DATE_RE.search(text)
                if sd_m:
                    try:
                        doc_sale_date = dateparser.parse(sd_m.group(1))
                    except (ValueError, TypeError):
                        pass

                # Detect "cancelled" rows: column with a check mark or "WD" annotation
                cancelled_indicator = re.compile(r"(✓|cancelled|withdrawn|WD\b)", re.I)

                # Each row anchored on case number
                chunks = re.split(r"(?=\b\d{2,4}-\d{3,5}\b)", text)
                for chunk in chunks:
                    chunk = chunk.strip()
                    if len(chunk) < 30:
                        continue
                    if cancelled_indicator.search(chunk):
                        continue
                    case_m = CASE_RE.search(chunk)
                    if not case_m:
                        continue
                    addr_m = ADDR_RE.search(chunk)

                    # Plaintiff v. Defendant
                    plaintiff = defendant = None
                    pvd = re.search(r"([A-Z][\w &.,'-]{3,80}?)\s+v\.\s+([A-Z][\w &.,'-]{3,80})", chunk)
                    if pvd:
                        plaintiff = pvd.group(1).strip()
                        defendant = pvd.group(2).strip().split("\n")[0]

                    bid = None
                    bm = BID_RE.search(chunk)
                    if bm:
                        try:
                            bid = float(bm.group(1).replace(",", ""))
                        except ValueError:
                            pass

                    if doc_sale_date and not (cutoff <= doc_sale_date <= horizon):
                        continue

                    out.append(
                        Listing(
                            source=self.slug,
                            source_url=url,
                            listing_type=ListingType.FORECLOSURE_SALE,
                            property_kind=PropertyKind.UNKNOWN,
                            street_address=addr_m.group(1) if addr_m else None,
                            state="SC",
                            county="Spartanburg",
                            case_number=case_m.group(0),
                            plaintiff=plaintiff,
                            defendant=defendant,
                            sale_date=doc_sale_date,
                            opening_bid=bid,
                            description=chunk[:500],
                            first_seen=datetime.utcnow(),
                            last_seen=datetime.utcnow(),
                        )
                    )
        return out
