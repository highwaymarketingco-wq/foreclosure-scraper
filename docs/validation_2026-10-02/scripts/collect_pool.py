import sys, json
sys.path.insert(0, "/Users/cashhigh/foreclosure-scraper/src")
from pathlib import Path
from foreclosure_scraper.web_artifact import _iter_board_records

DOCS = Path("/Users/cashhigh/foreclosure-scraper/docs")

pool = []
total_rows = 0
buncombe_total = 0
for rec in _iter_board_records(DOCS):
    total_rows += 1
    county = (rec.get("county") or "").strip()
    state = (rec.get("state") or "").strip().upper()
    if state != "NC" or county.lower() != "buncombe":
        continue
    buncombe_total += 1
    raw = rec.get("raw") or {}
    bd = raw.get("builder_distress")
    if not bd:
        continue
    pool.append({
        "owner_name": rec.get("owner_name"),
        "street_address": rec.get("street_address"),
        "city": rec.get("city"),
        "zip_code": rec.get("zip_code"),
        "listing_type": rec.get("listing_type"),
        "market_value": rec.get("market_value"),
        "tax_value": rec.get("tax_value"),
        "assessed_value": rec.get("assessed_value"),
        "source": rec.get("source"),
        "builder_distress": bd,
        "liensnc": raw.get("liensnc"),
        "owner_mailing": (raw.get("owner_mailing") or {}),
    })

print(f"total board rows streamed: {total_rows}")
print(f"Buncombe NC rows total: {buncombe_total}")
print(f"Buncombe NC builder_distress rows: {len(pool)}")

out_path = Path("/private/tmp/claude-502/-Users-cashhigh-Desktop/b86058dc-f10e-4c7b-a7fd-37f22fac2920/scratchpad/builder_distress_pool.json")
out_path.write_text(json.dumps(pool, indent=2, default=str))
print(f"wrote pool -> {out_path}")
