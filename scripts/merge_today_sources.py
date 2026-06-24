#!/usr/bin/env python
"""Merge ONLY today's new-source leads into the existing dashboard — NO full re-scrape.

Runs just the scrapers added/changed 2026-06-24 (hubzu, Terry Howe FLC, Spartan
Weekly, NC ROD substitute-trustee [cchs Burke/Cleveland], NC ROD Logan), scope-
filters their leads the same way main.py builds the active board, dedupes them into
the persisted docs/listings.json, re-runs the SC enrichers + the grade-gated
assessor card, recomputes grade + data-quality, and rewrites the dashboard.

Everything NOT in this source set is preserved as-is from the existing dashboard.

Usage: ASSESSOR_CARD_ON=1 python scripts/merge_today_sources.py
"""
import asyncio
import collections
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from foreclosure_scraper.models import Listing  # noqa: E402
from foreclosure_scraper.config import RuntimeConfig  # noqa: E402
from foreclosure_scraper.scrapers._registry import all_scrapers  # noqa: E402
from foreclosure_scraper.dedupe import dedupe  # noqa: E402
from foreclosure_scraper.main import _in_scope, _active_only  # noqa: E402
from foreclosure_scraper.valuation import calc as vcalc, grading as vgrade  # noqa: E402
from foreclosure_scraper.enrichment_sc_cama import enrich_sc_cama  # noqa: E402
from foreclosure_scraper.enrichment_footprint_sqft import enrich_footprint_sqft  # noqa: E402
from foreclosure_scraper.enrichment_data_quality import enrich_data_quality  # noqa: E402
from foreclosure_scraper.enrichment_assessor_card import enrich_assessor_card  # noqa: E402
from foreclosure_scraper.web_artifact import write_artifact  # noqa: E402

DOCS = Path(__file__).resolve().parent.parent / "docs"


def _countyless_national(li: Listing) -> bool:
    return (li.source or "").startswith("national.") and not (li.county or "").strip()


NEW_SOURCES = {
    "national.hubzu",
    "counties_sc.terry_howe_flc",
    "counties_sc.spartan_weekly_legals",
    "counties_nc.nc_rod_substitute_trustee",
    "counties_nc.nc_rod_logan",
}


async def _scrape_new() -> list[Listing]:
    scrapers = [s for s in all_scrapers() if s.slug in NEW_SOURCES]
    print("running new scrapers:", sorted(s.slug for s in scrapers))
    out: list[Listing] = []
    for s in scrapers:
        try:
            leads = list(await s.safe_run())
        except Exception as e:  # noqa: BLE001
            print(f"  {s.slug}: ERROR {str(e)[:80]}")
            continue
        print(f"  {s.slug}: {len(leads)}")
        for li in leads:
            if not li.source:
                li.source = s.slug
            out.append(li)
    return out


def main() -> int:
    cfg = RuntimeConfig.from_env()
    raw = json.loads((DOCS / "listings.json").read_text())
    existing, bad = [], 0
    for d in raw:
        try:
            existing.append(Listing.model_validate(d))
        except Exception:  # noqa: BLE001
            bad += 1
    print(f"existing dashboard: {len(existing)} ({bad} unparseable)")

    new = asyncio.run(_scrape_new())
    keep = [li for li in new
            if _in_scope(li) and not _countyless_national(li)
            and _active_only(li, cfg.sale_horizon_days)]
    print(f"new leads: {len(new)} -> {len(keep)} kept after scope/active filter")

    merged = dedupe(existing + keep)
    merged = [li for li in merged if not _countyless_national(li)]
    print(f"merged+deduped -> {len(merged)} (net new vs existing: {len(merged) - len(existing):+d})")

    print("enrich_sc_cama:", enrich_sc_cama(merged))
    print("enrich_footprint_sqft:", enrich_footprint_sqft(merged))

    vfail = 0
    for li in merged:
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

    s = enrich_assessor_card(merged)
    print("enrich_assessor_card:", s)
    if s:
        touched = [li for li in merged if isinstance(li.raw, dict) and "assessor_card" in li.raw]
        for li in touched:
            try:
                c = vcalc.compute(li)
                g = vgrade.grade(li, c)
                li.raw["calc"] = vcalc.to_dict(c)
                li.raw["grade"] = vgrade.to_dict(g)
            except Exception:  # noqa: BLE001
                pass
        print(f"re-graded {len(touched)} card-enriched leads")

    print("enrich_data_quality:", enrich_data_quality(merged))

    summary = {
        "by_source": dict(collections.Counter(li.source for li in merged if li.source)),
        "notes": "merged today's new-source leads into persisted dataset (no full re-scrape)",
    }
    lp, mp = write_artifact(merged, summary, docs_dir=DOCS)
    print(f"wrote {lp} ({lp.stat().st_size:,} bytes) + {mp.name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
