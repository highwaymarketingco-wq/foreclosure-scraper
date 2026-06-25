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
from foreclosure_scraper.enrichment_assessor_card import enrich_assessor_card  # noqa: E402
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

    # Re-apply scope to EVERY lead (carryover from older runs predates scope
    # tightening, so stale out-of-footprint counties + countyless noise persist).
    from foreclosure_scraper.main import _in_scope  # noqa: E402
    before = len(listings)
    listings = [li for li in listings if _in_scope(li)]
    print(f"scope re-filter: dropped {before - len(listings)} out-of-footprint -> {len(listings)} kept")

    # Drop dead court records — a Canceled/Satisfied/Dismissed/Vacated lien or
    # judgment is no longer an actionable lead (NC eCourts civilJudgmentStatus).
    def _terminal_court(li: Listing) -> bool:
        st = (((li.raw or {}).get("nc_ecourts") or {}).get("civilJudgmentStatus") or "").lower()
        return any(t in st for t in ("cancel", "satisf", "dismiss", "vacat", "withdraw", "expired", "released"))
    before = len(listings)
    listings = [li for li in listings if not _terminal_court(li)]
    print(f"dropped terminal-status court records: {before - len(listings)} -> {len(listings)} kept")

    # Parcel# -> address/sqft/acreage/owner via county GIS (parcel-bearing leads
    # that lack a street address / specs). Async, so run it in its own loop.
    import asyncio
    from foreclosure_scraper.enrichment_parcel_lookup import enrich_with_parcel_lookup
    try:
        asyncio.run(enrich_with_parcel_lookup(listings))
        print("parcel_lookup: done")
    except Exception as e:  # noqa: BLE001
        print("parcel_lookup: ERROR", str(e)[:80])

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

    # On-demand per-parcel assessor card (grade-gated B+) — fills real sqft + sale
    # price the bulk feed omits; re-grade touched leads so a real card sqft flips
    # ARV MEDIUM->HIGH. No-op unless ASSESSOR_CARD_ON=1 (mirrors main.py).
    s = enrich_assessor_card(listings)
    print("enrich_assessor_card:", s)
    if s:
        touched = [li for li in listings if isinstance(li.raw, dict) and "assessor_card" in li.raw]
        for li in touched:
            try:
                c = vcalc.compute(li)
                g = vgrade.grade(li, c)
                li.raw["calc"] = vcalc.to_dict(c)
                li.raw["grade"] = vgrade.to_dict(g)
            except Exception:  # noqa: BLE001
                pass
        print(f"re-graded {len(touched)} card-enriched leads")

    print("enrich_data_quality:", enrich_data_quality(listings))

    # Drop sold/removed snapshot-REO (Fannie) — stale carryover whose per-property
    # SPA URL renders a browser 404 once the uuid leaves inventory. Fail-safe.
    from foreclosure_scraper.enrichment_reo_freshness import prune_stale_reo
    try:
        listings, _pstats = asyncio.run(prune_stale_reo(listings))
        print("prune_stale_reo:", _pstats)
    except Exception as e:  # noqa: BLE001
        print("prune_stale_reo: ERROR", str(e)[:80])

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
