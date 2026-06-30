#!/usr/bin/env python
"""Apply Gaston NC ROD lien-existence enrichment to the persisted board (no re-scrape) + write.
Searches the free Gaston Register of Deeds name index for each NC/Gaston owner and attaches
raw['rod'] (D/T mortgage + adverse-lien existence). Usage: python scripts/fill_gaston_rod.py
"""
import asyncio
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
os.environ.setdefault("FORECLOSURE_GASTON_ROD", "1")

from foreclosure_scraper.models import Listing                         # noqa: E402
from foreclosure_scraper.enrichment_gaston_rod import enrich_gaston_rod  # noqa: E402
from foreclosure_scraper.web_artifact import write_artifact            # noqa: E402

DOCS = Path(__file__).resolve().parent.parent / "docs"


def main() -> int:
    raw = json.loads((DOCS / "listings.json").read_text())
    listings = []
    for d in raw:
        try:
            listings.append(Listing.model_validate(d))
        except Exception:  # noqa: BLE001
            pass
    s = asyncio.run(enrich_gaston_rod(listings))
    after = sum(1 for li in listings if isinstance(li.raw, dict) and li.raw.get("rod"))
    print("gaston_rod:", s, f"| rod on board: {after}")
    lp, _ = write_artifact(listings, {"notes": "Gaston NC ROD lien-existence by owner name"}, docs_dir=DOCS)
    print("wrote", lp)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
