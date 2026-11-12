"""Find actual duplicate rows on the board (same dedupe_key appearing 2+ times).
This tells us exactly which rows the dedup missed.
"""
import json
import sys
import os
import collections
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
os.environ.setdefault("BOARD_LOAD_ALLOW_LARGE", "1")
os.environ.setdefault("BOARD_APPEND_ALLOW_LARGE", "1")

from foreclosure_scraper.web_artifact import _iter_board_records, _append_dict_sigs
from foreclosure_scraper.models import Listing

docs = ROOT / "docs"

# Stream the board, compute dedupe_key for each row, track duplicates
print("Streaming board to find duplicate dedupe_keys...", flush=True)
key_to_rows = collections.defaultdict(list)
sig_to_rows = collections.defaultdict(list)

total = 0
for rec in _iter_board_records(docs):
    total += 1
    if not isinstance(rec, dict):
        continue
    
    # Compute dedupe_key via model_construct (same as _append_dict_sigs)
    light = Listing.model_construct(**{k: rec.get(k) for k in 
        ("state", "county", "parcel_id", "street_address", "zip_code",
         "case_number", "source_url", "listing_type")})
    
    try:
        dk = light.dedupe_key()
    except:
        dk = "ERROR"
    
    key_to_rows[dk].append(total - 1)  # 0-indexed row number
    
    # Also track strong sigs
    for sig in _append_dict_sigs(rec):
        sig_to_rows[sig].append(total - 1)
    
    if total % 50000 == 0:
        print(f"  Scanned {total} rows...", flush=True)

print(f"\nTotal rows: {total}", flush=True)

# Find dedupe_keys that appear more than once
dupes = {k: rows for k, rows in key_to_rows.items() if len(rows) > 1}
print(f"Duplicate dedupe_keys: {len(dupes)} (affecting {sum(len(r) for r in dupes.values())} rows)", flush=True)

# Show first 30 duplicate groups
print(f"\n=== First 30 duplicate groups ===", flush=True)
for i, (dk, rows) in enumerate(sorted(dupes.items(), key=lambda x: -len(x[1]))):
    if i >= 30:
        break
    print(f"  [{len(rows)}x] key={dk} rows={rows[:5]}", flush=True)

# Also check for duplicate strong sigs
sig_dupes = {k: rows for k, rows in sig_to_rows.items() if len(rows) > 1}
print(f"\nDuplicate strong sigs: {len(sig_dupes)}", flush=True)
for i, (sig, rows) in enumerate(sorted(sig_dupes.items(), key=lambda x: -len(x[1]))):
    if i >= 10:
        break
    print(f"  [{len(rows)}x] sig={sig} rows={rows[:5]}", flush=True)
