#!/usr/bin/env python
"""Re-process the persisted dashboard dataset (docs/listings.json) with the
CURRENT code — WITHOUT re-scraping. Applies today's SC enrichers (CAMA value+
specs, footprint sqft estimate), recomputes valuation + grade + data-quality,
drops county-less national records, and rewrites the dashboard artifact.

Use when code/enrichers changed but you don't need a fresh crawl. For brand-new
leads, run the full pipeline (main.py) instead.

Usage: python scripts/regenerate_dashboard.py
"""
import collections
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from foreclosure_scraper.models import Listing  # noqa: E402
from foreclosure_scraper.valuation import calc as vcalc, grading as vgrade  # noqa: E402
from foreclosure_scraper.enrichment_sc_cama import enrich_sc_cama  # noqa: E402
from foreclosure_scraper.enrichment_footprint_sqft import enrich_footprint_sqft  # noqa: E402
from foreclosure_scraper.enrichment_data_quality import enrich_data_quality  # noqa: E402
from foreclosure_scraper.web_artifact import write_artifact  # noqa: E402

DOCS = Path(__file__).resolve().parent.parent / "docs"


def _countyless_national(li: Listing) -> bool:
    return (li.source or "").startswith("national.") and not (li.county or "").strip()


def main() -> int:
    raw = json.loads((DOCS / "listings.json").read_text())
    print(f"loaded {len(raw)} records")

    listings, bad = [], 0
    for d in raw:
        try:
            listings.append(Listing.model_validate(d))
        except Exception as e:  # noqa: BLE001
            bad += 1
            if bad <= 3:
                print(f"  skip (validate): {str(e)[:80]}")
    print(f"re-hydrated {len(listings)} ({bad} unparseable)")

    before = len(listings)
    listings = [li for li in listings if not _countyless_national(li)]
    print(f"dropped county-less national: {before - len(listings)} -> {len(listings)} kept")

    print("enrich_sc_cama:", enrich_sc_cama(listings))
    print("enrich_footprint_sqft:", enrich_footprint_sqft(listings))

    # Recompute valuation + grade with current logic (mirrors main.py).
    vfail = 0
    for li in listings:
        try:
            c = vcalc.compute(li)
            g = vgrade.grade(li, c)
            if not isinstance(li.raw, dict):
                li.raw = {}
            li.raw["calc"] = vcalc.to_dict(c)
            li.raw["grade"] = vgrade.to_dict(g)
        except Exception:  # noqa: BLE001
            vfail += 1
    print(f"recomputed calc+grade ({vfail} failures)")

    print("enrich_data_quality:", enrich_data_quality(listings))

    by_state = collections.Counter(li.state for li in listings if li.state)
    by_county = collections.Counter(f"{li.state}/{li.county}" for li in listings if li.county)
    by_source = collections.Counter(li.source for li in listings if li.source)
    summary = {
        "by_state": dict(by_state),
        "by_county_top": by_county.most_common(15),
        "by_source": dict(by_source),
        "notes": "regenerated in-place from persisted dataset (no re-scrape)",
    }
    lp, mp = write_artifact(listings, summary, docs_dir=DOCS)
    print(f"wrote {lp} ({lp.stat().st_size:,} bytes) + {mp.name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
