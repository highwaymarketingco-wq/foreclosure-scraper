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
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from foreclosure_scraper.enrichment_reo_freshness import prune_stale_reo  # noqa: E402
from foreclosure_scraper.web_artifact import write_artifact, load_board  # noqa: E402

DOCS = Path(__file__).resolve().parent.parent / "docs"


def main() -> int:
    # Load through load_board so the lazy-detail sidecar (listings_detail.json:
    # vision/comps/cama/foreclosure_sold_comps/rent_comps) is merged back into
    # each lead's .raw. A plain json.loads of listings.json would let
    # write_artifact re-emit an empty sidecar and wipe the detail.
    listings = load_board(DOCS)
    print(f"loaded {len(listings)}")

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
