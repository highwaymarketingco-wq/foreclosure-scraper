"""Colleton County SC delinquent-tax / annual tax-sale list (coastal).

Colleton's Delinquent Tax Office publishes the parcels going to the annual
tax sale as a PDF ("Tax Sale Property Listing") linked from the tax-sale page:

    https://www.colletoncounty.org/delinquent-tax
        -> Tax Sale (/delinquent-tax/tax-sale)
            -> /sites/default/files/uploads/del_tax/taxsalelist-MM-DD.pdf

This is strong pre-sale distress: the owner owes back taxes and the property is
headed to auction on the published sale date unless the bill is paid. SC tax
sales carry a ~12-month statutory redemption window (SC Code 12-51-90), so the
owner remains reachable after the sale too.

The PDF is a clean text table:
    Owner Name | Map Number (TMS) | Description | Acres | Total Tax Due
e.g.  ``A H CONCRETE LLC ... 136-00-00-232.000 Lot 21 ... RHODE DR (D 2 497.8``
TMS format is ``NNN-NN-NN-NNN.NNN`` (Schneider/qPublic county map number).
Business-personal-property rows (numeric account id, "Personal" description,
no real-estate TMS) are skipped — they are not parcels.

SEASONAL: SC delinquent-tax lists post in winter (sale ~Feb here), so this is
gated to the Dec–Mar window and lies dormant the rest of the year, auto-resuming
when the next list posts. The current list (verified live) has a Feb 20, 2026
sale date.

The listing-PDF filename embeds the date and changes year to year, so the link
is DISCOVERED from the tax-sale page (ranked: "taxsalelist" / "del_tax" first),
never hardcoded. Free, plain-HTTP PDF (httpx + pdfplumber), no anti-bot,
ToS-OK (county treasurer page).
"""
from __future__ import annotations

import io
import re
from datetime import datetime
from typing import Iterable
from urllib.parse import urljoin

import structlog
from selectolax.parser import HTMLParser

from ...base_scraper import BaseScraper
from ...http_client import get_bytes, get_text
from ...models import Listing, ListingType, PropertyKind

log = structlog.get_logger()

PAGE_URL = "https://www.colletoncounty.org/delinquent-tax"
TAX_SALE_URL = "https://www.colletoncounty.org/delinquent-tax/tax-sale"
BASE = "https://www.colletoncounty.org"

# Colleton/Schneider TMS map number: NNN-NN-NN-NNN.NNN
TMS_RE = re.compile(r"\b(\d{3}-\d{2}-\d{2}-\d{3}\.\d{3})\b")
# Trailing "<Acres> <Total Tax Due>" columns, e.g. "... 2 497.8" / "... 0.4 107.45"
_TAIL_RE = re.compile(r"\s+(\d+(?:\.\d+)?)\s+([\d,]+(?:\.\d{1,2})?)\s*$")
_MONTHS = (
    "january february march april may june july august september "
    "october november december"
).split()
_DATE_RE = re.compile(
    r"\b(" + "|".join(_MONTHS) + r")\s+(\d{1,2}),?\s+(\d{4})\b", re.I
)


def _discover_list_pdf(html: str) -> list[str]:
    """Rank candidate PDF links on the tax-sale page so the actual parcel
    LIST ('taxsalelist' / del_tax) sorts above the bidder/info sheet."""
    cands: list[tuple[int, str]] = []
    for a in HTMLParser(html).css("a[href]"):
        href = a.attributes.get("href") or ""
        if ".pdf" not in href.lower():
            continue
        url = urljoin(BASE, href)
        low = url.lower()
        label = (a.text(strip=True) or "").lower()
        score = 0
        if "taxsalelist" in low or "tax-sale-list" in low or "/del_tax/" in low:
            score += 5
        if "list" in label or "listing" in label or "property" in label:
            score += 3
        if "taxsale" in low or "tax-sale" in low or "tax sale" in label:
            score += 1
        # Bidder/registration/info/results sheets are NOT the parcel list.
        if any(k in (low + " " + label)
               for k in ("bidder", "registration", "result", "info", "procedure", "faq")):
            score -= 4
        cands.append((score, url))
    # de-dup keeping best score, then sort desc
    best: dict[str, int] = {}
    for s, u in cands:
        if u not in best or s > best[u]:
            best[u] = s
    return [u for u, s in sorted(best.items(), key=lambda x: -x[1]) if s > 0]


def _find_sale_date(html: str) -> datetime | None:
    """Pull the sale date (e.g. 'February 20, 2026') from the tax-sale page."""
    text = HTMLParser(html).text(separator=" ") if html else ""
    m = _DATE_RE.search(text or "")
    if not m:
        return None
    try:
        mo = _MONTHS.index(m.group(1).lower()) + 1
        return datetime(int(m.group(3)), mo, int(m.group(2)))
    except (ValueError, IndexError):
        return None


def _pdf_text(data: bytes) -> str:
    try:
        import pdfplumber
        with pdfplumber.open(io.BytesIO(data)) as pdf:
            return "\n".join((p.extract_text() or "") for p in pdf.pages)
    except Exception as exc:  # noqa: BLE001
        log.warning("colleton_tax_sale.pdf_parse_fail", error=str(exc)[:160])
        return ""


def parse_list(text: str, url: str, sale_date: datetime | None) -> list[Listing]:
    """Parse the Colleton tax-sale PDF text into per-parcel Listings.

    Each real row carries a TMS. Owner = text before the TMS; the description
    + acres + tax-due trail after it. Rows without a real-estate TMS (the header
    and business-personal-property accounts) are skipped.
    """
    redemption = None
    if sale_date is not None:
        # SC Code 12-51-90: ~12-month redemption after the tax sale.
        try:
            redemption = sale_date.replace(year=sale_date.year + 1)
        except ValueError:  # Feb 29 guard
            redemption = sale_date.replace(year=sale_date.year + 1, day=28)

    out: list[Listing] = []
    seen: set[str] = set()
    for raw_line in (text or "").splitlines():
        line = re.sub(r"\s+", " ", raw_line).strip()
        if not line:
            continue
        m = TMS_RE.search(line)
        if not m:
            continue  # header row + "Personal" BPP accounts have no TMS
        tms = m.group(1)
        owner = line[: m.start()].strip() or None
        rest = line[m.end():].strip()

        acres = tax_due = None
        tail = _TAIL_RE.search(rest)
        if tail:
            try:
                acres = float(tail.group(1))
            except ValueError:
                acres = None
            try:
                tax_due = float(tail.group(2).replace(",", ""))
            except ValueError:
                tax_due = None
            desc = rest[: tail.start()].strip() or None
        else:
            desc = rest or None

        key = f"{tms}|{owner}"
        if key in seen:
            continue
        seen.add(key)

        out.append(Listing(
            source="counties_sc.colleton_tax_sale",
            source_url=url,
            listing_type=ListingType.TAX_SALE,
            property_kind=PropertyKind.UNKNOWN,
            state="SC", county="Colleton",
            street_address=desc,                 # county "description" is the situs
            defendant=owner,                     # delinquent owner
            parcel_id=tms,
            acreage=acres,
            judgment_amount=tax_due,             # total delinquent tax due
            sale_date=sale_date,
            redemption_deadline=redemption,
            foreclosure_process="tax",
            description=line[:300],
            first_seen=datetime.utcnow(), last_seen=datetime.utcnow(),
            raw={"colleton_tax_sale": {
                "owner": owner, "tms": tms, "acres": acres,
                "total_tax_due": tax_due, "item_line": line[:200],
            }},
        ))
    return out


class ColletonTaxSale(BaseScraper):
    slug = "counties_sc.colleton_tax_sale"
    name = "Colleton SC Delinquent Tax Sale list (annual PDF)"
    category = "county_tax"
    expected_min_count = 0       # seasonal; off-window the list is absent
    requires_apify = False
    timeout_s = 120.0
    active_months = (12, 1, 2, 3)  # SC winter sale cycle; dormant off-season

    async def fetch(self) -> Iterable[Listing]:
        # 1) Load the tax-sale page (preferred); fall back to the landing page.
        page_html = ""
        for u in (TAX_SALE_URL, PAGE_URL):
            try:
                page_html = await get_text(u, headers={"User-Agent": "Mozilla/5.0"}, timeout=45.0)
                if page_html:
                    break
            except Exception:
                continue

        sale_date = _find_sale_date(page_html)
        candidates = _discover_list_pdf(page_html) if page_html else []

        # 2) Fetch ranked candidates; first PDF that parses to >=1 parcel wins.
        out: list[Listing] = []
        seen_url: set[str] = set()
        for url in candidates:
            if url in seen_url:
                continue
            seen_url.add(url)
            try:
                data = await get_bytes(url, timeout=90.0)
            except Exception:
                continue
            if not (data and data[:4] == b"%PDF"):
                continue
            rows = parse_list(_pdf_text(data), url, sale_date)
            if rows:  # the actual parcel list (not an info/bidder sheet)
                out.extend(rows)
                log.info("colleton_tax_sale.list_ok", url=url,
                         count=len(rows), sale_date=str(sale_date))
                break

        log.info("colleton_tax_sale.done", count=len(out))
        return out
