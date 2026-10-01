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

2026-09-28 re-verification: cherokeecountysc.gov/delinquent-tax/ (the page a
MASTER_GAPS re-probe pointed at) is NOT Cloudflare-403'd -- clean HTTP 200,
271KB, no challenge. That doc's "Cherokee SC delinquent tax: Cloudflare 403"
entry is stale (the block cleared before 2026-08-18, when this scraper was
already switched to the wp-json media API below). The delinquent-tax/ page
itself carries no table -- it just links out to the SAME PDFs this scraper's
wp-json search already discovers (confirmed: its "TAX-SALE-TAB.pdf" link is
byte-identical in URL to the 2026/08 media item below), so no URL change is
needed here.

Isolated fetch() re-test 2026-09-28: 14 media items found, 528 unique-TMS
Listings returned (OK). BUT the two most recent parseable years found were
2024 (639 raw rows each of "Tax-Sale-List-2024[-1].pdf", deduped to 528) --
every 2025 PDF ("2025-tax-sale.pdf", "Delinquent-Tax-Sale-2025[-1].pdf") is
just a 1-2 page sale-date/bidder-registration NOTICE with no parcel table
(0 rows, correctly), and the CURRENT 2026 list, "TAX-SALE-TAB.pdf" (linked
from the delinquent-tax/ page as the live list), is a SCANNED-IMAGE PDF --
pypdf and pdfplumber both extract 0 chars / 0 tables from it. Closing that
gap needed OCR (see project_doc_ocr.md's Gemini-first scanned-PDF
enricher) -- added below (_ocr_pdf_text) as a text-under-40-chars fallback
that feeds Gemini's transcription straight through the SAME _parse_pdf_text
regex, rather than porting the whole enrichment_doc_ocr.py per-lead pipeline
in.

2026-09-28 OCR fallback verified: the wp-json media item's own "modified"
timestamp is 2026-08-25, and rendering TAX-SALE-TAB.pdf to an image (pymupdf)
confirms it is NOT the scanned table the "5 raster images" note above assumed
-- it is a single-page announcement flyer ("THE CHEROKEE COUNTY, SC,
DELINQUENT TAX SALE IS SCHEDULED FOR MONDAY, NOVEMBER 9, 2026 ... WE DO NOT
PROVIDE A COPY OF THE LIST IN THE DELINQUENT TAX OFFICE ... DELINQUENT
PROPERTIES ... WILL BE POSTED ON THIS SITE, THREE WEEKS BEFORE THE SALE
DATE"). Gemini OCR read it correctly and reported (accurately) that there is
no parcel table on the page -- 0 rows is the CORRECT answer for this specific
PDF today, not an OCR failure; same pattern already seen on the (correctly
zero-row) 2025 notice PDFs and on 2023's identically-worded flyer
("Delinquent-Tax-Sale-2023.pdf", same "we do not provide a list" text,
rendered + OCR'd to confirm). The actual 2026 parcel list will not exist at
this URL until roughly 2026-10-19 (three weeks before the Nov 9 sale).
The OCR mechanism itself (scanned PDF -> Gemini transcription -> the existing
row regex) was validated separately against a synthetic image-only PDF built
with 5 known rows in this exact column layout: all 5 rows round-tripped
through _ocr_pdf_text() + _parse_pdf_text() with the TMS/owner/description
values intact. Re-run this scraper after ~2026-10-19 to pick up the real
2026 list once the county posts it.
"""
from __future__ import annotations

import asyncio
import io
import json
import os
import re
from typing import Iterable

import structlog

from ...base_scraper import BaseScraper, OUTCOME_OK, OUTCOME_ZERO
from ...http_client import get_bytes, get_text
from ...models import Listing, ListingType, PropertyKind
from ...enrichment_doc_ocr import DOC_OCR_ENABLED
from ...enrichment_vision import GEMINI_VISION_MODEL, _parse_gemini_keys

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


# --- OCR fallback for scanned/image tax-sale PDFs ---------------------------
#
# 2026-09-28: the CURRENT year's list (e.g. TAX-SALE-TAB.pdf) started shipping
# as a scanned/raster-image PDF with no text layer -- pypdf and pdfplumber
# both extract 0 chars from it, so _extract_pdf_text() above silently returns
# "" and this scraper falls back to whatever older PDF still has real text
# (the 2024 list), running a year stale forever without ever erroring.
#
# This reuses the project's existing Gemini-first scanned-document OCR
# infrastructure (enrichment_doc_ocr.py / enrichment_vision.py): the same
# GEMINI_API_KEY_1..N multi-account key rotation, the same google-genai SDK
# call shape used by enrichment_doc_ocr._gemini_call() (Gemini accepts a raw
# application/pdf Part directly -- no image conversion needed, and it reads
# every page/embedded image in one call), and the same FORECLOSURE_DOC_OCR
# on/off gate (DOC_OCR_ENABLED) so a global OCR kill-switch also covers this
# path. It does NOT reuse enrichment_doc_ocr's OCR_PROMPT / apply_ocr(),
# because that prompt extracts ONE owner/address from a single per-property
# notice -- this PDF is a multi-hundred-row TABLE, so the model is asked to
# transcribe every row back into the same "<item#> <owner> <TMS> <desc>"
# layout _parse_pdf_text() already parses, rather than to extract one record.
_OCR_TRANSCRIBE_PROMPT = (
    "This is a scanned page (or pages) from a South Carolina county's "
    "delinquent tax sale list. It is a table with columns, in order: Item "
    "Number, Owner Name, Map Number (a TMS parcel number formatted like "
    "099-01-00-022.000), and a Description or address. Transcribe EVERY "
    "data row exactly as printed in the scanned image -- do not skip any, "
    "do not summarize, do not correct spelling. Output ONE row per line, "
    "in exactly this format:\n"
    "<item number> <owner name> <TMS map number> <description>\n"
    "Example output line:\n"
    "1 A AND R PROPERTY MANAGEMENT 099-01-00-022.000 946 N LOGAN ST\n"
    "Do not include the header row, page numbers, or any commentary/"
    "markdown/code fences. Output only the transcribed data rows."
)

# Text extraction below this many characters is treated as "no text layer" --
# i.e. a scanned/raster PDF worth spending an OCR call on. A handful of stray
# chars (a stamped date, a page footer pypdf occasionally lifts off a raster
# page) should not by itself count as "has a text layer".
_OCR_TEXT_FLOOR = 40

# Per-key vision-call timeout and the hard ceiling for the whole fallback
# (tried across every configured Gemini key). Bounded well under this
# scraper's timeout_s so a bad run degrades to "OCR skipped", not a hang.
_OCR_CALL_TIMEOUT_S = 45.0
_OCR_TOTAL_TIMEOUT_S = 180.0


def _is_quota_error(msg: str) -> bool:
    m = msg.lower()
    return any(s in m for s in
                ("quota", "rate limit", "429", "resource_exhausted",
                 "exceeded", "too many requests"))


async def _ocr_pdf_text(pdf_bytes: bytes) -> str:
    """OCR a scanned/image-only PDF into transcribed table text via Gemini.

    Rotates across every GEMINI_API_KEY_N configured (same key-loading as the
    rest of this project's vision/doc-OCR pipeline), moving to the next key
    on quota exhaustion. Returns "" if no key is configured, the google-genai
    SDK isn't installed, or every key fails/times out -- callers must treat
    that as "OCR unavailable" and keep whatever real text was already
    extracted, never raise.
    """
    keys = _parse_gemini_keys()
    if not keys:
        log.warning("cherokee_delinquent_tax.ocr_no_gemini_key")
        return ""
    try:
        from google import genai
        from google.genai import types as gt
    except ImportError:
        log.warning("cherokee_delinquent_tax.ocr_sdk_missing",
                    hint="pip install google-genai")
        return ""

    model = os.environ.get("DOC_OCR_MODEL", GEMINI_VISION_MODEL)

    async def _one_key(key: str) -> str:
        client = genai.Client(api_key=key)
        contents = [
            gt.Part.from_bytes(data=pdf_bytes, mime_type="application/pdf"),
            _OCR_TRANSCRIBE_PROMPT,
        ]
        resp = await client.aio.models.generate_content(
            model=model, contents=contents,
            config=gt.GenerateContentConfig(max_output_tokens=8000),
        )
        text = ""
        try:
            text = (resp.text or "").strip()
        except Exception:
            for cand in getattr(resp, "candidates", []) or []:
                for p in getattr(getattr(cand, "content", None), "parts", []) or []:
                    text += getattr(p, "text", "") or ""
        return text

    async def _try_all_keys() -> str:
        for key in keys:
            try:
                text = await asyncio.wait_for(_one_key(key), timeout=_OCR_CALL_TIMEOUT_S)
            except asyncio.TimeoutError:
                log.warning("cherokee_delinquent_tax.ocr_call_timeout", key=key[:8])
                continue
            except Exception as exc:
                msg = str(exc)
                if _is_quota_error(msg):
                    log.info("cherokee_delinquent_tax.ocr_quota_exhausted", key=key[:8])
                else:
                    log.warning("cherokee_delinquent_tax.ocr_error",
                                key=key[:8], error=msg[:160])
                continue
            if text:
                return text
        return ""

    try:
        return await asyncio.wait_for(_try_all_keys(), timeout=_OCR_TOTAL_TIMEOUT_S)
    except asyncio.TimeoutError:
        log.warning("cherokee_delinquent_tax.ocr_total_timeout")
        return ""


class CherokeeDelinquentTaxScraper(BaseScraper):
    slug = "counties_sc.cherokee_delinquent_tax"
    name = "Cherokee SC Delinquent Tax Sale"
    category = "tax_sale"
    # 120s -> 300s: leaves headroom for the OCR fallback (up to
    # _OCR_TOTAL_TIMEOUT_S=180s) on top of the normal wp-json + PDF fetches.
    timeout_s = 300.0
    expected_min_count = 0  # annual list, may be empty off-season

    async def fetch(self) -> Iterable[Listing]:
        # Step 1: Fetch the wp-json media listing.
        #
        # 2026-09-24: this used to be a synchronous urllib.request.urlopen()
        # call -- part of the same event-loop-starvation sweep that found and
        # fixed counties_sc.zombie_properties (confirmed live: froze every
        # sibling scraper for 41m50s) and national.irs_treasury_auctions (an
        # unbounded blocking loop). A single bounded 20s call is much lower
        # risk than those two, but still froze the whole event loop for every
        # other concurrent scraper for as long as this WordPress site took to
        # answer. Switched to http_client.get_text(), which is genuinely
        # async (this file's own get_bytes() calls below already use the same
        # module) and adds retry-on-transient-error for free.
        try:
            text = await get_text(
                WP_MEDIA_URL,
                timeout=20,
                headers={"Accept": "application/json"},
            )
            media_items = json.loads(text)
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

                # OCR fallback: a text layer under _OCR_TEXT_FLOOR chars means
                # this PDF is scanned/raster (e.g. the county switched the
                # current tax-sale list to an image scan), not empty of
                # rows -- pypdf/pdfplumber structurally cannot recover text
                # that was never embedded. Without this, the scraper silently
                # falls back to whatever older PDF still has real text and
                # never errors. See the OCR fallback block above for why this
                # doesn't reuse enrichment_doc_ocr's single-record prompt.
                if len(text.strip()) < _OCR_TEXT_FLOOR and DOC_OCR_ENABLED:
                    log.info("cherokee_delinquent_tax.ocr_fallback_start",
                             url=pdf_url[-50:], text_chars=len(text.strip()))
                    ocr_text = await _ocr_pdf_text(pdf_bytes)
                    if ocr_text:
                        ocr_rows = _parse_pdf_text(ocr_text)
                        log.info("cherokee_delinquent_tax.ocr_fallback_parsed",
                                 url=pdf_url[-50:], rows=len(ocr_rows),
                                 ocr_chars=len(ocr_text))
                        rows = ocr_rows
                    else:
                        log.warning("cherokee_delinquent_tax.ocr_fallback_empty",
                                    url=pdf_url[-50:])

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

            # Audited 2026-10-01: owner_name and street_address were never
            # set here even though both are already correctly parsed --
            # owner only reached `defendant` (owner_name is the field most
            # enrichers across this codebase read, e.g. the name->parcel
            # resolver, skip-trace, GIS backfill; defendant alone is not a
            # universal substitute), and `description` (which the module's
            # own docstring example shows IS the situs, e.g. "946 N LOGAN
            # ST") was only kept in raw. Live-verified before the fix:
            # 0/528 rows had owner_name or street_address despite both being
            # correctly parsed into the row dict already. Not every
            # description is house-number-led (e.g. "GREEN ST", "W BIRNIE
            # ST" for a lot with no visible number), so this does not gate
            # on a leading digit -- Spartanburg's FLC list audit this same
            # session found that guard incorrectly nulls real situs text.
            desc = row.get("description")
            yield Listing(
                source=self.slug,
                source_url=WP_MEDIA_URL,
                county="Cherokee",
                state="SC",
                parcel_id=tms,
                owner_name=owner,
                defendant=owner,
                street_address=desc,
                listing_type=ListingType.TAX_SALE,
                property_kind=PropertyKind.UNKNOWN,
                raw={
                    "sale_type": "delinquent_tax",
                    "description": desc,
                    "item_number": row.get("item"),
                },
            )

        self.last_outcome = OUTCOME_OK if all_rows else OUTCOME_ZERO
