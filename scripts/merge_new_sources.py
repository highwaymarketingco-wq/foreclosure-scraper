#!/usr/bin/env python3
"""Run new scrapers + enrichers and merge into the existing board.

Runs ONLY:
1. Cherokee SC delinquent tax scraper (new)
2. Derivation flags enricher (new)
3. Burke parcel history enricher (new)
4. Out-of-footprint county filter (new)

Then merges results into the existing published board and writes it back.
This avoids a full 7+ hour engine re-run.
"""
import asyncio
import sys
import json
from pathlib import Path
from collections import Counter

# Setup paths
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from foreclosure_scraper.web_artifact import load_board, write_artifact
from foreclosure_scraper.dedupe import dedupe
from foreclosure_scraper.config import SCOPE_DENY_COUNTIES_NORMALIZED
from foreclosure_scraper.models import Listing


def _in_scope(li: Listing) -> bool:
    """Check if listing is in our county footprint."""
    county = (li.county or "").strip().lower()
    state = (li.state or "").strip().upper()
    key = f"{county}|{state}"
    return key not in SCOPE_DENY_COUNTIES_NORMALIZED


async def main():
    docs_dir = Path(__file__).parent.parent / "docs"

    # 1. Load existing board
    print("Loading existing board...")
    board = load_board(docs_dir)
    print(f"  Board: {len(board)} listings")

    # 2. Run Cherokee SC delinquent tax scraper
    print("\nRunning Cherokee SC delinquent tax scraper...")
    from foreclosure_scraper.scrapers.counties_sc.cherokee_delinquent_tax import CherokeeDelinquentTaxScraper
    cherokee_scraper = CherokeeDelinquentTaxScraper()
    cherokee_listings: list[Listing] = await cherokee_scraper.safe_run()
    slug = cherokee_scraper.slug
    print(f"  Cherokee: {len(cherokee_listings)} listings (slug={slug})")

    # 3. Merge Cherokee listings into board
    # Tag Cherokee listings with source
    for li in cherokee_listings:
        if not li.source:
            li.source = slug

    # Combine and dedupe (fresh Cherokee data wins on conflicts)
    combined = list(cherokee_listings) + list(board)
    print(f"\nMerging: {len(cherokee_listings)} Cherokee + {len(board)} board = {len(combined)} combined")

    try:
        deduped = dedupe(combined)
    except Exception as e:
        print(f"  Dedupe failed: {e}, keeping combined")
        deduped = combined
    print(f"  After dedupe: {len(deduped)}")

    # 4. Filter out-of-footprint counties
    before_filter = len(deduped)
    in_scope = [li for li in deduped if _in_scope(li)]
    removed = before_filter - len(in_scope)
    print(f"\nOut-of-footprint filter: removed {removed}, kept {len(in_scope)}")

    enriched = in_scope

    # 5. Run derivation flags enricher
    print("\nRunning derivation flags enricher...")
    try:
        from foreclosure_scraper.enrichment_derivation_flags import enrich_derivation_flags
        stats = enrich_derivation_flags(enriched)
        if stats:
            print(f"  Derivation flags: {stats}")
    except Exception as e:
        print(f"  ERROR: {e}")

    # 6. Run Burke parcel history enricher
    print("\nRunning Burke parcel history enricher...")
    try:
        from foreclosure_scraper.enrichment_burke_history import enrich_burke_parcel_history
        stats = await enrich_burke_parcel_history(enriched)
        if stats:
            print(f"  Burke history: {stats}")
    except Exception as e:
        print(f"  ERROR: {e}")

    # 7. Build summary and write board
    by_state = Counter(li.state or "?" for li in enriched)
    by_county = Counter(f"{li.county or '?'}/{li.state or '?'}" for li in enriched)
    by_source = Counter(li.source or "?" for li in enriched)

    summary = {
        "total": len(enriched),
        "merged_cherokee": len(cherokee_listings),
        "out_of_footprint_removed": removed,
        "by_state": dict(by_state),
        "by_county_top": by_county.most_common(20),
        "by_source_top": by_source.most_common(20),
        "notes": "incremental merge: cherokee tax sale + derivation flags + burke history + out-of-footprint filter",
    }

    print(f"\nWriting board: {len(enriched)} listings...")
    write_artifact(enriched, summary, docs_dir)
    print(f"Board written to {docs_dir}/listings.json")
    print(f"\nSummary:")
    print(f"  Total listings: {len(enriched)}")
    print(f"  Cherokee added: {len(cherokee_listings)}")
    print(f"  Out-of-footprint removed: {removed}")
    print(f"  Top counties: {by_county.most_common(10)}")


if __name__ == "__main__":
    asyncio.run(main())
