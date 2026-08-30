"""OCR enricher — extract text from legal notice PDFs and images.

Uses EasyOCR (pure Python, no system binary needed) to extract text from:
  - Legal notice PDFs (3,388 unprocessed)
  - Notice of sale documents
  - Court filing images

Extracted text is searched for:
  - Case numbers (e.g. 25-CVS-12345, 24-SP-678)
  - Sale dates (e.g. "January 15, 2026", "01/15/2026")
  - Attorney contact info (name, phone, email)
  - Property descriptions (legal description, parcel ID)
  - Deficiency amounts
  - Opening bid amounts

Output: writes extracted data to li.raw["ocr_extraction"]
"""
from __future__ import annotations

import io
import os
import re
import structlog
from datetime import datetime
from pathlib import Path
from typing import Sequence

from .models import Listing

log = structlog.get_logger()

# Regex patterns for extraction
_CASE_NUMBER_PATTERNS = [
    re.compile(r'(\d{2}-[A-Z]{3}-\d{3,5})', re.IGNORECASE),
    re.compile(r'(\d{2}-CVS-\d{4,5})', re.IGNORECASE),
    re.compile(r'(\d{2}-SP-\d{4,5})', re.IGNORECASE),
    re.compile(r'(\d{2}-RE-\d{4,5})', re.IGNORECASE),
    re.compile(r'(Case\s*No\.?\s*:?\s*(\d{2}-[A-Z]{2,3}-\d{3,5}))', re.IGNORECASE),
    re.compile(r'((20\d{2})\s*[A-Z]{3}\s*(\d{3,5}))', re.IGNORECASE),
    re.compile(r'(File\s*No\.?\s*:?\s*(\d{2,4}-?[A-Z]{2,3}-?\d{3,5}))', re.IGNORECASE),
]

_SALE_DATE_PATTERNS = [
    re.compile(r'((January|February|March|April|May|June|July|August|September|October|November|December)\s+\d{1,2},?\s+20\d{2})', re.IGNORECASE),
    re.compile(r'(\d{1,2}/\d{1,2}/20\d{2})', re.IGNORECASE),
    re.compile(r'(\d{1,2}-\d{1,2}-20\d{2})', re.IGNORECASE),
    re.compile(r'(sale\s*(?:date|on|shall\s*be)[:\s]+([^\.]{10,40}))', re.IGNORECASE),
]

_PHONE_RE = re.compile(r'\(?\b\d{3}\)?[-.\s]\d{3}[-.\s]\d{4}\b')
_EMAIL_RE = re.compile(r'\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b')
_OPENING_BID_RE = re.compile(r'(?:opening\s*bid|upset\s*bid|minimum\s*bid)[:\s]*\$?([\d,]+)', re.IGNORECASE)
_DEFICIENCY_RE = re.compile(r'(?:deficiency|deficient\s*amount)[:\s]*\$?([\d,]+)', re.IGNORECASE)
_PARCEL_RE = re.compile(r'(?:parcel|pin|tax\s*id|tmk)\s*(?:no|number)?[:\s]*([A-Z0-9-]{6,20})', re.IGNORECASE)

# Cache the OCR reader (heavy to initialize)
_reader = None


def _get_reader():
    """Lazily initialize EasyOCR reader. Uses English + GPU if available."""
    global _reader
    if _reader is None:
        import easyocr
        # Try GPU first, fall back to CPU
        try:
            _reader = easyocr.Reader(['en'], gpu=True)
        except Exception:
            _reader = easyocr.Reader(['en'], gpu=False)
        log.info("ocr.reader_initialized", gpu=_reader.gpu if hasattr(_reader, 'gpu') else 'unknown')
    return _reader


def _pdf_to_images(pdf_path: str) -> list[bytes]:
    """Convert PDF pages to images using pdf2image or pymupdf."""
    try:
        import fitz  # PyMuPDF
        doc = fitz.open(pdf_path)
        images = []
        for page in doc:
            pix = page.get_pixmap(dpi=200)
            img_bytes = pix.tobytes("png")
            images.append(img_bytes)
        doc.close()
        return images
    except ImportError:
        pass
    
    # Fallback: try pdf2image (requires poppler)
    try:
        from pdf2image import convert_from_bytes
        with open(pdf_path, 'rb') as f:
            pdf_bytes = f.read()
        pages = convert_from_bytes(pdf_bytes, dpi=200)
        results = []
        for page in pages:
            buf = io.BytesIO()
            page.save(buf, format='PNG')
            results.append(buf.getvalue())
        return results
    except ImportError:
        pass
    
    # Last resort: try to read raw text from PDF
    try:
        import fitz
        doc = fitz.open(pdf_path)
        text = ""
        for page in doc:
            text += page.get_text()
        doc.close()
        # Return text as a single "image" (will be handled by caller)
        if text.strip():
            return [text.encode()]
    except Exception:
        pass
    
    return []


def _extract_structured(text: str) -> dict:
    """Extract structured data from raw OCR/text output."""
    result = {
        "case_numbers": [],
        "sale_dates": [],
        "phones": [],
        "emails": [],
        "opening_bid": None,
        "deficiency": None,
        "parcel_ids": [],
        "raw_text_preview": text[:500] if text else "",
    }
    
    # Case numbers
    seen_cases = set()
    for pattern in _CASE_NUMBER_PATTERNS:
        for m in pattern.finditer(text):
            cn = m.group(1).upper().strip()
            if cn not in seen_cases:
                seen_cases.add(cn)
                result["case_numbers"].append(cn)
    
    # Sale dates
    seen_dates = set()
    for pattern in _SALE_DATE_PATTERNS:
        for m in pattern.finditer(text):
            d = m.group(1).strip()
            if d not in seen_dates:
                seen_dates.add(d)
                result["sale_dates"].append(d)
    
    # Phones
    for m in _PHONE_RE.finditer(text):
        p = re.sub(r'\D', '', m.group())
        if len(p) == 10 and p not in result["phones"]:
            result["phones"].append(p)
    
    # Emails
    for m in _EMAIL_RE.finditer(text):
        e = m.group().lower().strip()
        if e not in result["emails"]:
            result["emails"].append(e)
    
    # Opening bid
    m = _OPENING_BID_RE.search(text)
    if m:
        result["opening_bid"] = m.group(1)
    
    # Deficiency
    m = _DEFICIENCY_RE.search(text)
    if m:
        result["deficiency"] = m.group(1)
    
    # Parcel IDs
    for m in _PARCEL_RE.finditer(text):
        pid = m.group(1).upper().strip()
        if pid not in result["parcel_ids"]:
            result["parcel_ids"].append(pid)
    
    return result


# Cache processed PDF results so multiple listings sharing the same PDF
# don't re-OCR it. Keyed by (pdf_path, mtime).
_PDF_CACHE: dict[tuple[str, float], dict] = {}


def _process_pdf(pdf_path: str, max_pages: int = 10) -> dict | None:
    """Process a single PDF/image and return extracted data.

    Results are cached per (path, mtime) so that multiple listings
    sharing the same PDF only trigger one OCR pass.
    """
    if not os.path.exists(pdf_path):
        return None

    # Check cache
    try:
        mtime = os.path.getmtime(pdf_path)
        cache_key = (pdf_path, mtime)
        if cache_key in _PDF_CACHE:
            return _PDF_CACHE[cache_key]
    except OSError:
        cache_key = None

    result = None
    try:
        # Fast path: if it's a text PDF, extract directly (no OCR)
        import fitz
        doc = fitz.open(pdf_path)
        text = ""
        for i, page in enumerate(doc):
            if i >= max_pages:
                break
            text += page.get_text()
        doc.close()

        # If we got good text from the PDF directly, use it
        if len(text.strip()) > 50:
            result = _extract_structured(text)
    except Exception as exc:
        log.debug("ocr.pdf_text_extract_error", path=pdf_path, error=str(exc)[:80])

    # OCR path for scanned PDFs / images (only if text extraction failed)
    if result is None:
        try:
            images = _pdf_to_images(pdf_path)
            if not images:
                result = None
            else:
                reader = _get_reader()
                full_text = ""
                for i, img_bytes in enumerate(images[:max_pages]):
                    if isinstance(img_bytes, bytes) and len(img_bytes) < 50:
                        # It's actually text, not an image
                        full_text += img_bytes.decode('utf-8', errors='ignore')
                        continue
                    # OCR the image
                    import numpy as np
                    from PIL import Image
                    img = Image.open(io.BytesIO(img_bytes))
                    arr = np.array(img)
                    results = reader.readtext(arr)
                    for detection in results:
                        if len(detection) >= 2:
                            full_text += detection[1] + " "

                if full_text.strip():
                    result = _extract_structured(full_text)
        except Exception as exc:
            log.debug("ocr.ocr_error", path=pdf_path, error=str(exc)[:80])

    # Cache the result
    if cache_key is not None:
        _PDF_CACHE[cache_key] = result
    return result


def _find_pdf_for_listing(li: Listing) -> str | None:
    """Find the legal notice PDF path for a listing."""
    raw = li.raw if isinstance(li.raw, dict) else {}
    
    # Check various raw fields for PDF path/URL
    notice_url = (
        raw.get("notice_url")
        or raw.get("legal_notice_url")
        or raw.get("source_pdf")
        or li.source_url
        or (raw.get("distressed", {}).get("url") if isinstance(raw.get("distressed"), dict) else None)
        or (raw.get("notice_contact", {}).get("pdf_url") if isinstance(raw.get("notice_contact"), dict) else None)
    )
    
    if not notice_url or not isinstance(notice_url, str):
        return None
    
    # Only process if it looks like a PDF or cloudinary notice
    if not any(x in notice_url for x in ('cloudinary', 'notice_export', '.pdf', 'legal_notice')):
        return None
    
    # If it's a URL, download to local cache
    if notice_url.startswith("http"):
        local_name = re.sub(r'[^A-Za-z0-9]', '_', notice_url)[-80:]
        local_path = os.path.join("data", "notice_pdfs", local_name)
        if os.path.exists(local_path):
            return local_path
        # Download to cache
        try:
            import urllib.request
            from urllib.parse import quote
            # URL-encode spaces and other special chars in the path
            parsed = urllib.parse.urlparse(notice_url)
            encoded_path = quote(parsed.path, safe='/')
            encoded_url = urllib.parse.urlunparse((
                parsed.scheme, parsed.netloc, encoded_path,
                parsed.params, parsed.query, parsed.fragment
            ))
            os.makedirs(os.path.dirname(local_path), exist_ok=True)
            urllib.request.urlretrieve(encoded_url, local_path)
            log.info("ocr.downloaded_pdf", url=notice_url[:80], path=local_path)
            return local_path
        except Exception as exc:
            log.debug("ocr.download_failed", url=notice_url[:80], error=str(exc)[:80])
            return None
    
    if os.path.exists(notice_url):
        return notice_url
    
    # Check relative to project root
    project_root = Path(__file__).resolve().parent.parent.parent
    full_path = project_root / notice_url
    if full_path.exists():
        return str(full_path)
    
    return None


def enrich_ocr_extraction(listings: Sequence[Listing]) -> dict:
    """Run OCR on legal notice PDFs and extract structured data.
    
    Only processes listings that have a PDF path/URL and don't already
    have OCR extraction data.
    """
    stats = {
        "total_listings": 0,
        "with_pdf": 0,
        "already_processed": 0,
        "processed": 0,
        "extracted_case": 0,
        "extracted_date": 0,
        "extracted_phone": 0,
        "extracted_email": 0,
        "errors": 0,
        "unique_pdfs": 0,
        "cached_pdfs": 0,
    }

    seen_pdfs: set[str] = set()

    for li in listings:
        stats["total_listings"] += 1
        raw = li.raw if isinstance(li.raw, dict) else {}
        
        # Skip if already processed
        if raw.get("ocr_extraction"):
            stats["already_processed"] += 1
            continue
        
        pdf_path = _find_pdf_for_listing(li)
        if not pdf_path:
            continue
        
        stats["with_pdf"] += 1
        
        # Track unique PDFs for progress logging
        if pdf_path not in seen_pdfs:
            seen_pdfs.add(pdf_path)
            stats["unique_pdfs"] += 1
            log.info("ocr.processing_pdf", path=pdf_path[-60:], unique=stats["unique_pdfs"], listing=f"{li.owner_name}"[:30] if li.owner_name else "?")
        else:
            stats["cached_pdfs"] += 1
        
        try:
            result = _process_pdf(pdf_path)
            if result:
                if not isinstance(li.raw, dict):
                    li.raw = {}
                li.raw["ocr_extraction"] = {
                    **result,
                    "ocr_at": datetime.utcnow().isoformat() + "Z",
                    "source_pdf": pdf_path,
                }
                stats["processed"] += 1
                
                # Surface case number if missing
                if result["case_numbers"] and not li.case_number:
                    li.case_number = result["case_numbers"][0]
                    stats["extracted_case"] += 1
                
                # Surface sale date if missing
                if result["sale_dates"]:
                    if not raw.get("sale_date"):
                        li.raw.setdefault("sale_date", result["sale_dates"][0])
                        stats["extracted_date"] += 1
                
                # Surface phones
                if result["phones"]:
                    if not raw.get("owner_phone"):
                        li.raw["owner_phone"] = {
                            "phone": f"({result['phones'][0][:3]}) {result['phones'][0][3:6]}-{result['phones'][0][6:]}",
                            "source": "ocr_legal_notice",
                            "line_type": "unknown",
                            "needs_dnc_scrub": True,
                            "match": "attorney_in_notice",
                        }
                        stats["extracted_phone"] += 1
                
                # Surface emails
                if result["emails"]:
                    if not raw.get("owner_email"):
                        li.raw["owner_email"] = {
                            "emails": result["emails"],
                            "best_email": result["emails"][0],
                            "best_classification": "attorney",
                            "source": "ocr_legal_notice",
                        }
                        stats["extracted_email"] += 1
                
                # Opening bid
                if result["opening_bid"]:
                    li.raw.setdefault("opening_bid", result["opening_bid"])
                
                # Deficiency
                if result["deficiency"]:
                    li.raw.setdefault("deficiency_amount", result["deficiency"])
        except Exception as exc:
            stats["errors"] += 1
            log.debug("ocr.listing_error", key=str(li.dedupe_key())[:30], error=str(exc)[:80])
    
    log.info("ocr_extraction.complete", **stats)
    return stats
