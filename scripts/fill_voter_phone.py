#!/usr/bin/env python
"""Apply NC voter-file phone enrichment to the persisted board (no re-scrape) + write.
Matches NC owner-occupants (name + property address) to an active voter -> phone, tagged
source=ncsbe_voter + needs_dnc_scrub. Free, ToS-clean, the one free personal-phone source.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from foreclosure_scraper.enrichment_voter_phone import enrich_voter_phone  # noqa: E402
from foreclosure_scraper.web_artifact import write_artifact, load_board    # noqa: E402

DOCS = Path(__file__).resolve().parent.parent / "docs"


def main() -> int:
    listings = load_board(DOCS)
    before = sum(1 for li in listings if isinstance(li.raw, dict) and li.raw.get("owner_phone"))
    s = enrich_voter_phone(listings)
    after = sum(1 for li in listings if isinstance(li.raw, dict) and li.raw.get("owner_phone"))
    print("voter_phone:", s, f"| owner_phone on board: {before} -> {after}")
    lp, _ = write_artifact(listings, {"notes": "NC voter-file phone enrichment (name+address, DNC-gated)"}, docs_dir=DOCS)
    print("wrote", lp)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
