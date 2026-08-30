#!/usr/bin/env python3
"""Run OCR enrichment on all listings with PDF/Cloudinary source URLs."""
import sys
sys.path.insert(0, 'src')
sys.path.insert(0, '.venv/lib/python3.12/site-packages')

from foreclosure_scraper.web_artifact import load_board, write_artifact
from foreclosure_scraper.enrichment_ocr import enrich_ocr_extraction

board = load_board()
print(f"Board: {len(board)} listings")

# Filter to only listings with PDF/Cloudinary source URLs
ocr_batch = []
for li in board:
    su = li.source_url or ''
    if any(x in su.lower() for x in ('cloudinary', 'notice_export', '.pdf', 'legal_notice')):
        ocr_batch.append(li)

print(f"OCR candidates: {len(ocr_batch)} listings")
print("Running OCR (this will take a while)...")
print()

result = enrich_ocr_extraction(ocr_batch)
print()
print(f"OCR Results:")
print(f"  Total: {result['total_listings']}")
print(f"  With PDF: {result['with_pdf']}")
print(f"  Already processed: {result['already_processed']}")
print(f"  Processed: {result['processed']}")
print(f"  Case numbers: {result['extracted_case']}")
print(f"  Sale dates: {result['extracted_date']}")
print(f"  Phones: {result['extracted_phone']}")
print(f"  Emails: {result['extracted_email']}")
print(f"  Errors: {result['errors']}")

print()
print("Writing board...")
write_artifact(board, {"ocr_run": True, "ocr_processed": result['processed']})
print(f"DONE: {len(board)} listings persisted")
