#!/usr/bin/env python3
"""Quick scan: how many Henderson County NC rows carry a code-enforcement/vacancy
signal on the live board, broken out by originating source. Streams the board via
_iter_board_records (never list()) per the project's own memory-safety pattern.
"""
import sys
import time

sys.path.insert(0, "/Users/cashhigh/foreclosure-scraper/src")

from pathlib import Path
from foreclosure_scraper.web_artifact import _iter_board_records

DOCS = Path("/Users/cashhigh/foreclosure-scraper/docs")

t0 = time.time()
n_total = 0
n_henderson = 0
counts_by_source = {}
sample_rows = {"code_enforcement": [], "vacancy": [], "slug_match": []}

for rec in _iter_board_records(DOCS):
    n_total += 1
    county = (rec.get("county") or "").strip().lower()
    state = (rec.get("state") or "").strip().upper()
    if county != "henderson" or state != "NC":
        continue
    n_henderson += 1
    raw = rec.get("raw") or {}
    source = rec.get("source") or ""

    hit = False
    if raw.get("code_enforcement"):
        hit = True
        counts_by_source[source] = counts_by_source.get(source, 0) + 1
        if len(sample_rows["code_enforcement"]) < 3:
            sample_rows["code_enforcement"].append(rec)
    if raw.get("vacancy"):
        hit = True
        if len(sample_rows["vacancy"]) < 3:
            sample_rows["vacancy"].append(rec)
    if source == "counties_nc.henderson_code_violations":
        hit = True

    if hit:
        pass

    if n_total % 50000 == 0:
        print(f"...scanned {n_total} rows ({time.time()-t0:.1f}s)", file=sys.stderr)

print(f"\nTotal board rows scanned: {n_total}")
print(f"Henderson County NC rows: {n_henderson}")
print(f"By source (code_enforcement truthy): {counts_by_source}")
print(f"Elapsed: {time.time()-t0:.1f}s")

for key, rows in sample_rows.items():
    print(f"\n--- sample {key} ---")
    for r in rows:
        print({
            "source": r.get("source"),
            "county": r.get("county"),
            "state": r.get("state"),
            "parcel_id": r.get("parcel_id"),
            "street_address": r.get("street_address"),
            "raw_keys": list((r.get("raw") or {}).keys()),
        })
