#!/usr/bin/env python3
"""Re-run FMR enricher on current board (which has OCR data) and write once.
OCR data is already persisted from the last run. FMR needs re-persisting."""
import asyncio
import sys

sys.path.insert(0, 'src')
sys.path.insert(0, '.venv/lib/python3.12/site-packages')

from foreclosure_scraper.web_artifact import load_board, write_artifact
from foreclosure_scraper.enrichment_hud_fmr import enrich_hud_fmr

board = load_board()
print(f"Board: {len(board)} listings")

# Check existing OCR data
ocr_ct = sum(1 for li in board if isinstance(li.raw, dict) and li.raw.get("ocr_extraction"))
sale_ct = sum(1 for li in board if isinstance(li.raw, dict) and li.raw.get("sale_date"))
phone_ct = sum(1 for li in board if isinstance(li.raw, dict) and li.raw.get("owner_phone"))
print(f"Pre-FMR: OCR={ocr_ct}, sale_date={sale_ct}, phone={phone_ct}")

# Run FMR enricher (uses cache, fast)
print("\n=== FMR Enrichment ===")
fmr_stats = asyncio.run(enrich_hud_fmr(board))
print(f"FMR: {fmr_stats}")

# Verify in-memory
fmr_ct = sum(1 for li in board if isinstance(li.raw, dict) and li.raw.get("hud_fmr"))
rent_ct = sum(1 for li in board if isinstance(li.raw, dict) and li.raw.get("census_rent"))
print(f"In-memory: FMR={fmr_ct}, census_rent={rent_ct}")

# Write board once — both FMR + OCR survive via fixed RAW_KEEP
print("\n=== Writing Board ===")
summary = {"enriched": "FMR + OCR persisted", "listings": len(board)}
write_artifact(board, summary, docs_dir="docs")
print("DONE")

# Verify by reloading
print("\n=== Verification ===")
board2 = load_board()
fmr2 = sum(1 for li in board2 if isinstance(li.raw, dict) and li.raw.get("hud_fmr"))
ocr2 = sum(1 for li in board2 if isinstance(li.raw, dict) and li.raw.get("ocr_extraction"))
sale2 = sum(1 for li in board2 if isinstance(li.raw, dict) and li.raw.get("sale_date"))
phone2 = sum(1 for li in board2 if isinstance(li.raw, dict) and li.raw.get("owner_phone"))
email2 = sum(1 for li in board2 if isinstance(li.raw, dict) and li.raw.get("owner_email"))
rent2 = sum(1 for li in board2 if isinstance(li.raw, dict) and li.raw.get("census_rent"))
print(f"Reloaded: {len(board2)} listings")
print(f"  FMR: {fmr2} ({100*fmr2/len(board2):.1f}%)")
print(f"  Census rent: {rent2} ({100*rent2/len(board2):.1f}%)")
print(f"  OCR: {ocr2}")
print(f"  Sale dates: {sale2} ({100*sale2/len(board2):.1f}%)")
print(f"  Owner phone: {phone2} ({100*phone2/len(board2):.1f}%)")
print(f"  Owner email: {email2}")
