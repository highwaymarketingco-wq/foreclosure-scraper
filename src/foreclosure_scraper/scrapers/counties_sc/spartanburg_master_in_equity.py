"""Spartanburg County SC Master in Equity — PDF roster from county Document Center.

The county updates `/DocumentCenter/View/3392` each month with the upcoming
sale roster (PDF). Each row has:
  - Status column (Final / Def. Sale / blank=active)
  - Case # (e.g. "25-3616")
  - Attorney firm
  - Plaintiff (lender)
  - Defendant (current owner)
  - Bid amount + winning bidder (when sold)
  - Cancellation marker ("√")
  - Property address (next line, indented)

We use pdfplumber rather than pypdf because pypdf flattens multi-column tables
and we lose row boundaries — verified locally that pdfplumber.extract_tables()
recovers all 25-30 rows per monthly PDF.
"""
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
    r"Highway|Hwy|Boulevard|Blvd|Circle|Cir|Court|Ct|Way|Place|Pl|Trail|Trl|Parkway|Pkwy|"
    r"Real)\.?)",
    re.I,
)
SALE_DATE_RE = re.compile(
    r"(?:Re-?Bid Date|Sale Date|Master[‘’‛'ʼ]s Sale)\s*[:—–-]?\s*"
    r"((?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\s+\d{1,2},?\s+\d{4})",
    re.I,
)
# Spartanburg results PDFs put the actual auction date BEFORE the
# 'Master's Sale' phrase: "May 4, 2026 Master's Sale". The PDF uses a
# curly apostrophe (’) so the regex must include both ASCII '
# and ‘-’ right-single-quote. Pattern lets us prefer the
# actual auction date over the Re-Bid Date (upset-bid window deadline)
# for results PDFs.
MASTERS_SALE_DATE_RE = re.compile(
    r"((?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\s+\d{1,2},?\s+\d{4})"
    r"\s+Master[‘’‛'ʼ]s Sale",
    re.I,
)
BID_RE = re.compile(r"\$\s*([\d,]+(?:\.\d{2})?)")
CANCEL_RE = re.compile(r"(√|✓|cancelled|withdrawn|WD\b)", re.I)
# Deficiency-Sale roster header line, e.g.
#   "2. SouthState Bank v. Christopher Riddle 25-5700"
# Plaintiff/Defendant straddle a " v. " separator; the case# closes the line.
DEF_ENTRY_RE = re.compile(
    r"^\s*\d+\.\s+(?P<plaintiff>.+?)\s+v\.?\s+(?P<defendant>.+?)\s+"
    r"(?P<case>\d{2,4}-\d{3,5})\s*$",
    re.I | re.M,
)


def _is_results_pdf(url: str) -> bool:
    """The 3392/Sale-Results and 11824/Deficiency-Sale PDFs are RESULTS
    PDFs — past-sale data with hammer prices. Other monthly roster PDFs
    are upcoming."""
    return ("sale-results" in url.lower() or
            "deficiency-sale" in url.lower())


def _extract_from_text(
    full_text: str, source_url: str, is_results: bool, doc_sale_date
) -> list[Listing]:
    """Fallback when extract_tables() yields no >=7-col rows (the
    Deficiency-Sale roster collapses to single-cell rows). Mirror
    sc_tax_delinquent._extract_from_text: regex the raw page text for each
    "N. Plaintiff v. Defendant CASE#" entry, then pull the nearby address +
    bid. One case# can legitimately appear twice (different properties), so
    we dedupe by ADDRESS, not case#."""
    out: list[Listing] = []
    seen_addr: set[str] = set()
    matches = list(DEF_ENTRY_RE.finditer(full_text))
    for i, m in enumerate(matches):
        # Block = text between this header and the next entry header.
        block_start = m.end()
        block_end = matches[i + 1].start() if i + 1 < len(matches) else len(full_text)
        block = full_text[block_start:block_end]

        case_clean = m.group("case")
        plaintiff = (m.group("plaintiff") or "").strip()
        defendant = (m.group("defendant") or "").strip()

        addr_m = ADDR_RE.search(block)
        address = addr_m.group(1).strip() if addr_m else None
        # Dedupe by address (case# may repeat across distinct properties).
        addr_key = (address or "").lower()
        if addr_key and addr_key in seen_addr:
            continue
        if addr_key:
            seen_addr.add(addr_key)

        bid = None
        bm = BID_RE.search(block)
        if bm:
            try:
                bid = float(bm.group(1).replace(",", ""))
            except ValueError:
                pass

        raw_payload = {"spartanburg_pdf": {
            "status": "deficiency",
            "attorney": None,
            "bid_by": None,
            "doc_sale_date": doc_sale_date.isoformat() if doc_sale_date else None,
            "is_results_pdf": is_results,
            "extraction": "text_fallback",
        }}
        if is_results and bid is not None:
            raw_payload["actual_sold_price"] = bid

        out.append(
            Listing(
                source="counties_sc.spartanburg_master_in_equity",
                source_url=source_url,
                listing_type=ListingType.FORECLOSURE_SALE,
                property_kind=PropertyKind.UNKNOWN,
                street_address=address,
                state="SC",
                county="Spartanburg",
                case_number=case_clean,
                plaintiff=plaintiff or None,
                defendant=defendant or None,
                sale_date=doc_sale_date,
                opening_bid=bid,
                description=block.strip()[:500] or None,
                auction_status="deficiency",
                first_seen=datetime.utcnow(),
                last_seen=datetime.utcnow(),
                raw=raw_payload,
            )
        )
    return out


def _parse_pdf_tables(data: bytes, source_url: str) -> list[Listing]:
    """Use pdfplumber.extract_tables() — preserves the 9-column row structure:
       [#, Status, Case#, Attorney, Plaintiff, Defendant+Address, Bid, BidBy, Cancelled]
    """
    out: list[Listing] = []
    try:
        import pdfplumber
    except ImportError:
        return out
    is_results = _is_results_pdf(source_url)
    try:
        with pdfplumber.open(io.BytesIO(data)) as pdf:
            full_text = "\n".join((p.extract_text() or "") for p in pdf.pages)
            doc_sale_date = None
            # For RESULTS PDFs, prefer the actual Master's Sale date
            # (when the hammer fell) over the Re-Bid Date (upset-bid
            # window deadline). Investors need the comp anchored to
            # the actual sale event.
            if is_results:
                ms = MASTERS_SALE_DATE_RE.search(full_text)
                if ms:
                    try:
                        doc_sale_date = dateparser.parse(ms.group(1))
                    except (ValueError, TypeError):
                        pass
            if doc_sale_date is None:
                sd_m = SALE_DATE_RE.search(full_text)
                if sd_m:
                    try:
                        doc_sale_date = dateparser.parse(sd_m.group(1))
                    except (ValueError, TypeError):
                        pass

            # Date-window check: upcoming sales must be within the 120-day
            # forward horizon. RESULTS PDFs (Sale-Results.pdf,
            # Deficiency-Sale.pdf) report past sales — accept up to 180
            # days back so they reach the foreclosure_sold_comps pool.
            # Without this branch the scraper was silently emptying the
            # results PDFs and we never saw the hammer prices.
            today = datetime.utcnow()
            horizon = today + timedelta(days=120)
            if is_results:
                cutoff = today - timedelta(days=180)
            else:
                cutoff = today - timedelta(days=2)
            if doc_sale_date and not (cutoff <= doc_sale_date <= horizon):
                return []

            seen: set[str] = set()
            saw_wide_row = False
            for page in pdf.pages:
                for table in page.extract_tables() or []:
                    for row in table:
                        if not row or len(row) < 7:
                            continue
                        saw_wide_row = True
                        # Skip header row
                        joined = " ".join(c or "" for c in row).lower()
                        if "case #" in joined or "attorney" in joined and "plaintiff" in joined:
                            continue
                        # Detect cancelled marker in any cell
                        if any("√" in (c or "") or "✓" in (c or "") for c in row):
                            continue

                        # Status, Case#, Attorney, Plaintiff, Defendant+Addr, Bid, BidBy
                        status = (row[1] or "").strip()
                        case = (row[2] or "").strip()
                        attorney = (row[3] or "").strip()
                        plaintiff = (row[4] or "").strip()
                        def_addr = (row[5] or "").strip()
                        bid_str = (row[6] or "").strip() if len(row) > 6 else ""

                        if not case or not CASE_RE.search(case):
                            continue
                        case_clean = CASE_RE.search(case).group(0)
                        if case_clean in seen:
                            continue
                        seen.add(case_clean)

                        # Defendant column = "Last, First\n<address>"
                        defendant = None
                        address = None
                        if def_addr:
                            lines = def_addr.split("\n")
                            defendant = lines[0].strip() if lines else None
                            if len(lines) > 1:
                                address = lines[1].strip()
                                # Address may include city: "144 Southland Ave., Boiling Springs"
                                # Keep full string; downstream GIS enrichment handles the city.

                        bid = None
                        bm = BID_RE.search(bid_str)
                        if bm:
                            try:
                                bid = float(bm.group(1).replace(",", ""))
                            except ValueError:
                                pass

                        # Build raw payload — when this is a RESULTS PDF
                        # AND we captured a bid, surface as actual_sold_price
                        # at top level so enrichment_foreclosure_sold_comps
                        # treats it as confirmed hammer price (not just an
                        # opening-bid floor).
                        raw_payload = {"spartanburg_pdf": {
                            "status": status,
                            "attorney": attorney,
                            "bid_by": (row[7] or "").strip() if len(row) > 7 else None,
                            "doc_sale_date": doc_sale_date.isoformat() if doc_sale_date else None,
                            "is_results_pdf": is_results,
                        }}
                        if is_results and bid is not None:
                            raw_payload["actual_sold_price"] = bid

                        out.append(
                            Listing(
                                source="counties_sc.spartanburg_master_in_equity",
                                source_url=source_url,
                                listing_type=ListingType.FORECLOSURE_SALE,
                                property_kind=PropertyKind.UNKNOWN,
                                street_address=address,
                                state="SC",
                                county="Spartanburg",
                                case_number=case_clean,
                                plaintiff=plaintiff or None,
                                defendant=defendant,
                                sale_date=doc_sale_date,
                                opening_bid=bid,
                                description=def_addr[:500],
                                auction_status=status.lower() if status else "active",
                                first_seen=datetime.utcnow(),
                                last_seen=datetime.utcnow(),
                                raw=raw_payload,
                            )
                        )

            # TEXT fallback: the Deficiency-Sale roster yields single-cell
            # rows, so extract_tables() never produces a >=7-col row and we
            # drop 100% of it. When no wide row was seen, regex the raw page
            # text for case# + defendant + address + bid instead.
            if not saw_wide_row:
                out.extend(
                    _extract_from_text(full_text, source_url, is_results, doc_sale_date)
                )
    except Exception:
        pass
    return out


class SpartanburgMasterInEquity(BaseScraper):
    slug = "counties_sc.spartanburg_master_in_equity"
    name = "Spartanburg County (SC) Master in Equity"
    category = "county_court"
    timeout_s = 90.0
    expected_min_count = 5

    async def fetch(self) -> Iterable[Listing]:
        out: list[Listing] = []
        async with client(timeout=45.0) as c:
            for url in PDF_URLS:
                try:
                    r = await c.get(url, headers={"User-Agent": "Mozilla/5.0"})
                    if r.status_code != 200 or r.content[:4] != b"%PDF":
                        continue
                except Exception:
                    continue
                out.extend(_parse_pdf_tables(r.content, url))
        return out
