#!/usr/bin/env python
"""Drop sold/removed snapshot-REO leads (Fannie HomePath) from the live dashboard.

Loads docs/listings.json, re-checks Fannie's current inventory, removes any lead
whose per-property URL is no longer live (= sold, renders a browser 404), and
rewrites the artifact. Preserves all existing enrichment (no re-scrape of other
sources, no re-grade). Fail-safe: an empty/failed Fannie pull prunes nothing.

Usage: python scripts/prune_stale_reo.py
"""
import asyncio
import collections
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from foreclosure_scraper.models import Listing  # noqa: E402
from foreclosure_scraper.enrichment_reo_freshness import prune_stale_reo  # noqa: E402
from foreclosure_scraper.web_artifact import write_artifact  # noqa: E402

DOCS = Path(__file__).resolve().parent.parent / "docs"


def main() -> int:
    raw = json.loads((DOCS / "listings.json").read_text())
    listings, bad = [], 0
    for d in raw:
        try:
            listings.append(Listing.model_validate(d))
        except Exception:  # noqa: BLE001
            bad += 1
    print(f"loaded {len(listings)} ({bad} unparseable)")

    kept, stats = asyncio.run(prune_stale_reo(listings))
    print(f"prune: {stats} -> {len(kept)} kept")

    summary = {
        "by_source": dict(collections.Counter(li.source for li in kept if li.source)),
        "notes": "pruned sold/removed snapshot-REO (Fannie) stale leads in place",
    }
    lp, mp = write_artifact(kept, summary, docs_dir=DOCS)
    print(f"wrote {lp} ({lp.stat().st_size:,} bytes) + {mp.name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
