"""Swain County NC — Tax Foreclosure notice (PDF download).

FIXED 2026-10-01 (HERMES sec 8 per-source audit). The old scraper fetched
the county HOMEPAGE (swaincountync.gov/) looking for a PDF link containing
"tax"/"foreclos"/"sale"/"auction"/"delinquent" -- the homepage has never had
any PDF links at all (0 matches, live-confirmed), so this always returned 0
rows. The real path, live-traced 2026-10-01:

  1. swaincountync.gov/tax-office/ -- an accordion/toggle panel titled
     "Notice of Foreclosure Sales" links to...
  2. swaincountync.gov/download/tax-notice-of-foreclosure/ -- a WP Download
     Manager (WPDM) "Document Center" detail page. Its visible
     <a href="#" class="download-on-click" data-downloadurl="...">Download</a>
     button has NO real href -- the file URL lives only in
     data-downloadurl="...?wpdmdl=<id>&refresh=<token>" (a per-page-load
     token; the id is otherwise stable). document_links.harvest_document_links
     was extended the same day to recognize this attribute (it previously
     only looked at href/src/data-url/data-href), since this is a common
     WordPress plugin on NC county sites, not unique to Swain.
  3. That URL serves the real PDF (49,881 bytes, %PDF-1.7 header, confirmed
     live). It is a SCANNED/image notice with no extractable text layer
     (pdfplumber returns ''), so this module cannot itself parse per-property
     fields out of it -- it stamps the document via harvest_document_links /
     stamp_documents so the existing doc-OCR enrichment pass can backfill
     owner/address/debt$ from the scan, same as every other scanned-notice
     source in this codebase. A FUTURE non-scanned notice (text-based PDF)
     is still parsed directly via the line-based extraction kept below.

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
from ...document_links import harvest_document_links, stamp_documents
from ...http_client import get_bytes, get_text
from ...models import Listing, ListingType, PropertyKind

log = structlog.get_logger()

TAX_OFFICE_URL = "https://www.swaincountync.gov/tax-office/"
NOTICE_LINK_RE = re.compile(
    r'href="([^"]*notice-of-foreclosure[^"]*)"', re.I
)


def _pdf_text(data: bytes) -> str:
    try:
        import pdfplumber
        with pdfplumber.open(io.BytesIO(data)) as pdf:
            return "\n".join((p.extract_text() or "") for p in pdf.pages)
    except Exception as exc:
        log.warning("swain_tax.pdf_parse_fail", error=str(exc)[:160])
        return ""


def _parse_text_rows(text: str, pdf_url: str) -> list[Listing]:
    """Line-based extraction for a (hypothetical future) text-layer PDF.
    Kept from the pre-fix version: still useful the day Swain posts a
    non-scanned notice."""
    out: list[Listing] = []
    for line in text.splitlines():
        line = line.strip()
        if len(line) < 5:
            continue
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
            source_url=pdf_url,
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
            raw={"swain_tax_foreclosures": {"pdf_url": pdf_url, "line": line[:200]}},
        ))
    return out


async def _find_notice_page(tax_office_html: str) -> str | None:
    m = NOTICE_LINK_RE.search(tax_office_html)
    if not m:
        return None
    return urljoin(TAX_OFFICE_URL, m.group(1))


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
            office_html = await get_text(TAX_OFFICE_URL, impersonate=True, timeout=40.0)
        except Exception as exc:  # noqa: BLE001
            log.warning("swain_tax.office_fetch_fail", error=str(exc)[:160])
            return out
        if not office_html or len(office_html) < 200:
            return out

        notice_url = await _find_notice_page(office_html)
        if not notice_url:
            log.warning("swain_tax.notice_link_not_found",
                        note="tax-office page layout may have changed")
            return out

        try:
            notice_html = await get_text(notice_url, impersonate=True, timeout=40.0)
        except Exception as exc:  # noqa: BLE001
            log.warning("swain_tax.notice_fetch_fail", error=str(exc)[:160])
            return out
        if not notice_html:
            return out

        doc_urls = harvest_document_links(notice_html, base_url=notice_url)
        # The page's own canonical/breadcrumb/oembed links also contain
        # "notice" (the slug is "tax-notice-of-foreclosure") and rank equally
        # with the real file, so a self-referential link to the page itself
        # can sort first. Prefer an actual WPDM download link (?wpdmdl=...);
        # failing that, drop any candidate that IS the page we just fetched.
        wpdm = [u for u in doc_urls if "wpdmdl=" in u]
        doc_urls = wpdm or [u for u in doc_urls if u.rstrip("/") != notice_url.rstrip("/")]
        if not doc_urls:
            log.warning("swain_tax.no_document_found", notice_url=notice_url)
            return out
        pdf_url = doc_urls[0]

        try:
            data = await get_bytes(pdf_url, timeout=60.0)
        except Exception as exc:  # noqa: BLE001
            log.warning("swain_tax.pdf_fetch_fail", error=str(exc)[:160])
            return out
        if not data or data[:4] != b"%PDF":
            log.warning("swain_tax.not_a_pdf", pdf_url=pdf_url)
            return out

        text = _pdf_text(data)
        if text.strip():
            out = _parse_text_rows(text, pdf_url)
            if out:
                log.info("swain_tax.done", count=len(out), mode="text_layer")
                return out

        # Scanned / no text layer: stamp the document so enrich_doc_ocr can
        # backfill owner/address/debt$, and still surface ONE lead so the
        # board/operator knows a current notice exists rather than silently
        # dropping it (the pre-fix scraper's only failure mode was 0 rows
        # with no trace of WHY).
        li = Listing(
            source="counties_nc.swain_tax_foreclosures",
            source_url=notice_url,
            listing_type=ListingType.TAX_SALE,
            property_kind=PropertyKind.UNKNOWN,
            state="NC",
            county="Swain",
            description="Swain County NC Notice of Foreclosure Sales (scanned PDF, pending OCR)",
            first_seen=datetime.utcnow(),
            last_seen=datetime.utcnow(),
            raw={"swain_tax_foreclosures": {"pdf_url": pdf_url, "notice_url": notice_url,
                                            "scanned_no_text_layer": True}},
        )
        stamp_documents(li, doc_urls)
        log.info("swain_tax.done", count=1, mode="scanned_stamped")
        return [li]
