"""Board-writer: stamp the confirmation/corroboration flag on every lead.

For each lead, records whether the distress is CONFIRMED by a court/authoritative
filing (public index / eCourts / master-in-equity / law-firm roster / ROD /
legal notice) vs. only flagged by a single MLS/aggregator (realtor.com etc.),
using the lead's full source set (li.source + raw['also_seen_in']). Writes
raw['corroboration'] {court_confirmed, tier, source_count, sources, multi_source,
label}.

Board-writer — run alone. Loads via load_board() so the lazy comps/vision
sidecar round-trips (write_artifact would otherwise rebuild the sidecar from raw
and drop it). Corroboration reads only source attribution, so no network + no
rescore needed.
"""
from __future__ import annotations

from pathlib import Path

from foreclosure_scraper.enrichment_corroboration import enrich_corroboration
from foreclosure_scraper.web_artifact import write_artifact, load_board

DOCS = Path(__file__).resolve().parent.parent / "docs"


def main() -> int:
    listings = load_board(DOCS)
    print(f"loaded {len(listings)} listings", flush=True)

    stats = enrich_corroboration(listings)
    print("corroboration:", stats, flush=True)

    write_artifact(listings, {"notes": "board-wide corroboration / court-confirmation flag"}, docs_dir=DOCS)
    print(
        f"wrote board | court_confirmed={stats.get('court_confirmed', 0)} "
        f"government={stats.get('government', 0)} aggregator_only={stats.get('aggregator_only', 0)} "
        f"multi_source={stats.get('multi_source', 0)}",
        flush=True,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
