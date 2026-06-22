"""Anderson County SC Master in Equity — corrected URL + WordPress uploads PDF discovery."""
from __future__ import annotations

import io
import re
from datetime import datetime, timedelta
from typing import Iterable

from dateutil import parser as dateparser
from selectolax.parser import HTMLParser

from ...base_scraper import BaseScraper
from ...http_client import client
from ...models import Listing, ListingType, PropertyKind

PAGE_URL = "https://www.andersoncountysc.org/departments-a-z/master-in-equity/"

PDF_HREF_RE = re.compile(
    r"/wp-content/uploads/(\d{4})/(\d{2})/([A-Za-z]+)-(\d+)-(\d{4})-Sale-List(?:-\d+)?\.pdf",
    re.I,
)
# Anderson also publishes Sale-Results and Deficiency-Sale-Results PDFs
# with hammer prices — these feed the foreclosure_sold_comps pool.
RESULTS_HREF_RE = re.compile(
    r"/wp-content/uploads/(\d{4})/(\d{2})/"
    r"([A-Za-z]+)-(\d+)-(\d{4})-(?:Deficiency-Sale-Results|Sale-Results)(?:-\d+)?\.pdf",
    re.I,
)
# Sold-price patterns observed in Anderson results PDFs.
# Examples:
#   "To Third Party $228,500.00"
#   "To Plaintiff $164,000.00"
#   "Plaintiff bid $78,000.00"
ANDERSON_SOLD_RE = re.compile(
    r"(?:to\s+third\s+party|to\s+plaintiff|plaintiff\s+bid)\s*\$\s*"
    r"([\d,]+(?:\.\d{2})?)",
    re.I,
)
ANDERSON_NON_SALE_RE = re.compile(r"\b(WD|WD/BR|BR\b|withdrawn)", re.I)
CASE_RE = re.compile(r"\b\d{2,4}-\d{3,5}\b")
ADDR_RE = re.compile(
    r"(\d+\s+[A-Z][\w .'\-]+(?:Road|Rd|Street|St|Drive|Dr|Lane|Ln|Avenue|Ave|"
    r"Highway|Hwy|Boulevard|Blvd|Circle|Cir|Court|Ct|Way|Place|Pl|Trail|Trl|Parkway|Pkwy)\.?)",
    re.I,
)
ATTORNEY_LEGEND = {
    "B&S": "Brock & Scott",
    "BCP": "Bell Carrington Price & Gregg",
    "BR": "Bankruptcy",
    "WD": "Withdrawn",
    "HSB": "Haynsworth Sinkler Boyd",
    "RPL": "Riley Pope & Laney",
    "RT": "Rogers Townsend",
    "S&C": "Scott & Corley",
}

MONTHS = {"january": 1, "february": 2, "march": 3, "april": 4, "may": 5, "june": 6,
          "july": 7, "august": 8, "september": 9, "october": 10, "november": 11, "december": 12}


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


def _parse_results_pdf(text: str, source_url: str, slug: str,
                       sale_date: datetime) -> list[Listing]:
    """Anderson Sale-Results / Deficiency-Sale-Results PDFs report past
    sales with hammer prices. Each row's price appears as 'To Third
    Party $X' / 'To Plaintiff $X' / 'Plaintiff bid $X'. Rows tagged
    WD or WD/BR didn't actually sell — skip those."""
    out: list[Listing] = []
    # Split on numbered-row markers ("1. 25-733", "2. 24-1352", etc.) —
    # the upcoming-sale-list parser splits on "<case#> <atty-code>" but
    # results PDFs sometimes have full attorney names ("Hutchens" 8 chars,
    # outside the original regex's [A-Z]{1,4} window). Splitting on the
    # numbered-row-with-case-number marker is more robust.
    chunks = re.split(r"(?=\b\d+\.\s+\d{2}-\d{3,5}\b)", text)
    for chunk in chunks:
        chunk = chunk.strip()
        if len(chunk) < 30:
            continue
        case_m = CASE_RE.search(chunk)
        if not case_m:
            continue
        if ANDERSON_NON_SALE_RE.search(chunk):
            continue  # withdrawn / bankruptcy — no sale happened
        sold_m = ANDERSON_SOLD_RE.search(chunk)
        if not sold_m:
            continue  # no price extractable — skip (would just be noise)
        try:
            price = float(sold_m.group(1).replace(",", ""))
        except ValueError:
            continue
        if not (100 <= price <= 10_000_000):
            continue

        addr_m = ADDR_RE.search(chunk)
        atty = None
        for code, full in ATTORNEY_LEGEND.items():
            if re.search(rf"\b{re.escape(code)}\b", chunk):
                atty = full
                break

        plaintiff = defendant = None
        m = re.search(r"([A-Z][\w &.,'-]{3,80}?)\s+v\.\s+([A-Z][\w &.,'-]{3,80})", chunk)
        if m:
            plaintiff, defendant = m.group(1).strip(), m.group(2).strip().split("\n")[0]

        out.append(Listing(
            source=slug,
            source_url=source_url,
            listing_type=ListingType.FORECLOSURE_SALE,
            property_kind=PropertyKind.UNKNOWN,
            street_address=addr_m.group(1) if addr_m else None,
            state="SC",
            county="Anderson",
            case_number=case_m.group(0),
            plaintiff=plaintiff,
            defendant=defendant,
            trustee=atty,
            sale_date=sale_date,
            opening_bid=price,
            description=chunk[:500],
            first_seen=datetime.utcnow(),
            last_seen=datetime.utcnow(),
            raw={
                # Top-level so enrichment_foreclosure_sold_comps reads it
                # as confirmed hammer price (not opening-bid floor).
                "actual_sold_price": price,
                "anderson_mie_results": {
                    "source_pdf": source_url,
                    "raw_chunk_excerpt": chunk[:400],
                },
            },
        ))
    return out


def _parse_pdf(text: str, source_url: str, slug: str) -> list[Listing]:
    out: list[Listing] = []
    today = datetime.utcnow()
    horizon = today + timedelta(days=120)
    cutoff = today - timedelta(days=2)

    # Each row: case# | atty | "Plaintiff v. Defendant" | description (lot, plat, address) | notes
    chunks = re.split(r"(?=\b\d{2}-\d{3,5}\s+[A-Z]{1,4}\b)", text)
    for chunk in chunks:
        chunk = chunk.strip()
        if len(chunk) < 30:
            continue
        case_m = CASE_RE.search(chunk)
        if not case_m:
            continue
        addr_m = ADDR_RE.search(chunk)

        # Try to identify attorney by short code
        atty = None
        for code, full in ATTORNEY_LEGEND.items():
            if re.search(rf"\b{re.escape(code)}\b", chunk):
                atty = full
                break

        # Plaintiff v. Defendant
        plaintiff = defendant = None
        m = re.search(r"([A-Z][\w &.,'-]{3,80}?)\s+v\.\s+([A-Z][\w &.,'-]{3,80})", chunk)
        if m:
            plaintiff, defendant = m.group(1).strip(), m.group(2).strip().split("\n")[0]

        out.append(
            Listing(
                source=slug,
                source_url=source_url,
                listing_type=ListingType.FORECLOSURE_SALE,
                property_kind=PropertyKind.UNKNOWN,
                street_address=addr_m.group(1) if addr_m else None,
                state="SC",
                county="Anderson",
                case_number=case_m.group(0),
                plaintiff=plaintiff,
                defendant=defendant,
                trustee=atty,
                description=chunk[:500],
                first_seen=datetime.utcnow(),
                last_seen=datetime.utcnow(),
            )
        )
    return out


class AndersonMasterInEquity(BaseScraper):
    slug = "counties_sc.anderson_master_in_equity"
    name = "Anderson County (SC) Master in Equity"
    category = "county_court"
    timeout_s = 120.0
    expected_min_count = 5

    async def fetch(self) -> Iterable[Listing]:
        out: list[Listing] = []
        today = datetime.utcnow()
        async with client(timeout=45.0) as c:
            try:
                r = await c.get(PAGE_URL)
                if r.status_code != 200:
                    return []
            except Exception:
                return []

            tree = HTMLParser(r.text)

            # ---- Sale-List PDFs (upcoming sales — the original behavior) ----
            best_pdf_url = None
            best_sale_date = None
            for a in tree.css("a[href*='Sale-List']"):
                href = a.attributes.get("href", "")
                m = PDF_HREF_RE.search(href)
                if not m:
                    continue
                month_name, day, year = m.group(3).lower(), int(m.group(4)), int(m.group(5))
                month_num = MONTHS.get(month_name)
                if not month_num:
                    continue
                try:
                    sale_date = datetime(year, month_num, day)
                except ValueError:
                    continue
                if sale_date < today - timedelta(days=30):
                    continue
                if best_sale_date is None or sale_date > best_sale_date:
                    best_sale_date = sale_date
                    best_pdf_url = (
                        href if href.startswith("http")
                        else f"https://www.andersoncountysc.org{href}"
                    )

            if best_pdf_url:
                try:
                    r2 = await c.get(best_pdf_url)
                    if r2.status_code == 200:
                        upcoming_text = _extract_pdf_text(r2.content)
                        listings = _parse_pdf(upcoming_text, best_pdf_url, self.slug)
                        for li in listings:
                            li.sale_date = best_sale_date
                        out.extend(listings)
                except Exception:
                    pass

            # ---- Sale-Results / Deficiency-Sale-Results PDFs (past sales
            # with hammer prices — feed the foreclosure_sold_comps pool) ----
            results_pdfs: list[tuple[str, datetime]] = []
            for a in tree.css("a[href*='Sale-Results'], a[href*='Deficiency-Sale-Results']"):
                href = a.attributes.get("href", "")
                m = RESULTS_HREF_RE.search(href)
                if not m:
                    continue
                month_name, day, year = m.group(3).lower(), int(m.group(4)), int(m.group(5))
                month_num = MONTHS.get(month_name)
                if not month_num:
                    continue
                try:
                    sale_date = datetime(year, month_num, day)
                except ValueError:
                    continue
                # Only include results within the foreclosure-sold-comps
                # lookback (180d) — older than that adds little signal.
                if sale_date < today - timedelta(days=180):
                    continue
                full_url = (
                    href if href.startswith("http")
                    else f"https://www.andersoncountysc.org{href}"
                )
                results_pdfs.append((full_url, sale_date))

            # Cap at the most-recent 6 results PDFs (covers ~3 months
            # of monthly sale + deficiency PDFs)
            results_pdfs.sort(key=lambda x: x[1], reverse=True)
            for url, sale_date in results_pdfs[:6]:
                try:
                    r3 = await c.get(url)
                    if r3.status_code != 200:
                        continue
                    text = _extract_pdf_text(r3.content)
                    if not text:
                        continue
                    out.extend(_parse_results_pdf(text, url, self.slug, sale_date))
                except Exception:
                    continue

        return out
