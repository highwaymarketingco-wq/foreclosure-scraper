"""Diagnostic: check why append_new_rows() dedup isn't catching duplicates.

Loads walled output rows, computes their _append_row_sigs(), then streams
the board computing _append_dict_sigs(). Reports which new rows match
existing board rows and which don't, with the actual field values.
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

from foreclosure_scraper.models import Listing, ListingType, PropertyKind
from foreclosure_scraper.web_artifact import _append_row_sigs, _append_dict_sigs, _iter_board_records

WALED_DIR = ROOT / "data" / "walled_output"

# 1. Load walled output
print("=== Loading walled output ===", flush=True)
new_rows = []
for f in sorted(WALED_DIR.glob("*_data.json")):
    with open(f) as fh:
        data = json.load(fh)
    listings = data.get("listings", [])
    for row in listings:
        new_rows.append(row)
    print(f"  {f.name}: {len(listings)} rows", flush=True)
print(f"Total walled rows: {len(new_rows)}", flush=True)

# 2. Compute signatures for each new row
print("\n=== Computing signatures for new rows ===", flush=True)
new_sigs = []
new_fields = []
for i, row in enumerate(new_rows):
    # Reconstruct a Listing the same way wire_walled_to_board.py does
    clean = {k: v for k, v in row.items() if k not in ("raw_keys",)}
    if "raw" not in clean:
        clean["raw"] = {}
    source = clean.get("source", "walled_unknown")
    clean.setdefault("source", source)
    if not clean.get("source_url"):
        clean["source_url"] = f"walled://{source}"
    
    lt = clean.get("listing_type")
    if isinstance(lt, str):
        name = lt.replace("ListingType.", "").strip()
        try:
            clean["listing_type"] = ListingType(name)
        except ValueError:
            try:
                clean["listing_type"] = ListingType[name]
            except KeyError:
                clean["listing_type"] = ListingType.UNKNOWN
    elif lt is None:
        clean["listing_type"] = ListingType.UNKNOWN
    
    pk = clean.get("property_kind")
    if isinstance(pk, str):
        try:
            clean["property_kind"] = PropertyKind(pk)
        except (ValueError, KeyError):
            clean["property_kind"] = PropertyKind.UNKNOWN
    elif pk is None:
        clean["property_kind"] = PropertyKind.UNKNOWN
    
    from datetime import datetime, timezone
    for dt_field in ("sale_date", "upset_bid_deadline", "redemption_deadline",
                      "first_seen", "last_seen"):
        v = clean.get(dt_field)
        if isinstance(v, str) and v:
            try:
                clean[dt_field] = datetime.fromisoformat(v)
            except ValueError:
                clean[dt_field] = None
        elif v is None:
            if dt_field in ("first_seen", "last_seen"):
                clean[dt_field] = datetime.now(timezone.utc)
            else:
                clean[dt_field] = None
    
    try:
        li = Listing.model_validate(clean)
    except Exception as e:
        print(f"  Row {i}: validation failed: {e}")
        continue
    
    sigs = _append_row_sigs(li)
    new_sigs.append(sigs)
    
    # Track identity fields
    fields = {
        "source": li.source,
        "state": li.state,
        "county": li.county,
        "parcel_id": li.parcel_id,
        "street_address": li.street_address,
        "zip_code": li.zip_code,
        "case_number": li.case_number,
        "source_url": li.source_url,
        "dedupe_key": li.dedupe_key(),
        "sigs": sigs,
    }
    new_fields.append(fields)

# 3. Summarize what identity fields the new rows have
print("\n=== Identity field summary ===", flush=True)
has_parcel = sum(1 for f in new_fields if f["parcel_id"])
has_addr = sum(1 for f in new_fields if f["street_address"])
has_zip = sum(1 for f in new_fields if f["zip_code"])
has_case = sum(1 for f in new_fields if f["case_number"])
has_none = sum(1 for f in new_fields if not f["parcel_id"] and not f["street_address"] and not f["case_number"])
print(f"  Has parcel_id: {has_parcel}")
print(f"  Has street_address: {has_addr}")
print(f"  Has zip_code: {has_zip}")
print(f"  Has case_number: {has_case}")
print(f"  Has NONE (parcel/addr/case): {has_none}")

# 4. Group by signature pattern
sig_patterns = collections.Counter()
for sigs in new_sigs:
    # Just count the types of sigs
    types = tuple(sorted(set(s[0] for s in sigs)))
    sig_patterns[types] += 1
print(f"\n=== Signature patterns ===", flush=True)
for pattern, count in sig_patterns.most_common():
    print(f"  {pattern}: {count} rows")

# 5. Check for rows that only have ("k", ...) signature (no strong sigs)
weak_rows = [(i, f) for i, (sigs, f) in enumerate(zip(new_sigs, new_fields)) 
             if all(s[0] == "k" for s in sigs)]
print(f"\n=== Rows with ONLY dedupe_key signature (no strong sigs): {len(weak_rows)} ===", flush=True)
for i, f in weak_rows[:10]:
    print(f"  Row {i}: source={f['source']} case={f['case_number']} addr={f['street_address']} parcel={f['parcel_id']} dedupe_key={f['dedupe_key']}")

# 6. Stream board and check matches
print(f"\n=== Streaming board to check matches ===", flush=True)
docs = ROOT / "docs"
cand_sigs = collections.defaultdict(list)
for i, sigs in enumerate(new_sigs):
    for sig in sigs:
        cand_sigs[sig].append(i)

hit = {}
existing_total = 0
for rec in _iter_board_records(docs):
    existing_total += 1
    if cand_sigs and isinstance(rec, dict):
        src = str(rec.get("source") or "?")
        for sig in _append_dict_sigs(rec):
            for i in cand_sigs.get(sig, ()):
                hit.setdefault(i, src)
    if existing_total % 50000 == 0:
        print(f"  Scanned {existing_total} board rows, {len(hit)} matches so far...", flush=True)

print(f"\n=== Results ===", flush=True)
print(f"  Board rows scanned: {existing_total}", flush=True)
print(f"  New rows: {len(new_fields)}", flush=True)
print(f"  Matched (would be skipped as dupes): {len(hit)}", flush=True)
print(f"  NOT matched (would be added): {len(new_fields) - len(hit)}", flush=True)

# 7. Show the NOT-matched rows — these are the ones that slip through
not_matched = [(i, f) for i, f in enumerate(new_fields) if i not in hit]
print(f"\n=== Not-matched rows (first 20) ===", flush=True)
for i, f in not_matched[:20]:
    print(f"  Row {i}: source={f['source']} case={f['case_number']} addr={f['street_address']} parcel={f['parcel_id']} dedupe_key={f['dedupe_key']} sigs={f['sigs']}", flush=True)
