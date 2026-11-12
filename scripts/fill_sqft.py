#!/usr/bin/env python
"""Surgical sqft backfill — runs ONLY the qPublic assessor-CARD enricher on the persisted
board, re-grades touched leads, writes. The #1 ARV-accuracy lever: a real heated/living
sqft clears the footprint-ESTIMATE flag and flips ARV confidence MEDIUM->HIGH. No re-scrape,
no slow GIS chain.

ASSESSOR_CARD_ON is forced on. Defaults to SKIP_RENDER (fast HTML/JSON counties only —
Anderson/Laurens/Cherokee SC + Cleveland/Gaston/Henderson/Lincoln/Polk/Rutherford NC).
Drop ASSESSOR_CARD_SKIP_RENDER + raise ASSESSOR_CARD_MAX to include the slow render
counties (Oconee/Pickens/Spartanburg/Union) on a stable connection.
"""
import collections
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
os.environ.setdefault("ASSESSOR_CARD_ON", "1")
os.environ.setdefault("ASSESSOR_CARD_SKIP_RENDER", "1")

from foreclosure_scraper.models import Listing                          # noqa: E402
from foreclosure_scraper.enrichment_assessor_card import enrich_assessor_card  # noqa: E402
from foreclosure_scraper.valuation import calc as vcalc, grading as vgrade     # noqa: E402
from foreclosure_scraper.web_artifact import write_artifact, load_board # noqa: E402

DOCS = Path(__file__).resolve().parent.parent / "docs"


def _real_sqft(li: Listing) -> bool:
    return bool(li.living_sqft) and not getattr(li, "living_sqft_estimated", False)


def main() -> int:
    listings = load_board(DOCS)
    before = sum(1 for li in listings if _real_sqft(li))
    print(f"loaded {len(listings)} | real sqft before: {before} | MAX={os.environ.get('ASSESSOR_CARD_MAX','300')} skip_render={os.environ.get('ASSESSOR_CARD_SKIP_RENDER')}")

    stats = enrich_assessor_card(listings)
    print("enrich_assessor_card:", stats)

    touched = [li for li in listings if isinstance(li.raw, dict) and "assessor_card" in li.raw]
    regraded = 0
    for li in touched:
        try:
            c = vcalc.compute(li)
            g = vgrade.grade(li, c)
            li.raw["calc"] = vcalc.to_dict(c)
            li.raw["grade"] = vgrade.to_dict(g)
            regraded += 1
        except Exception:  # noqa: BLE001
            pass
    after = sum(1 for li in listings if _real_sqft(li))
    print(f"re-graded {regraded} touched | real sqft after: {after} (+{after - before})")

    if os.environ.get("FILL_SQFT_WRITE", "1") == "1":
        summary = {"notes": "sqft backfill via per-parcel assessor cards (no re-scrape)",
                   "by_source": dict(collections.Counter(li.source for li in listings if li.source))}
        lp, mp = write_artifact(listings, summary, docs_dir=DOCS)
        print(f"wrote {lp}")
    else:
        print("(dry-run, not written)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
