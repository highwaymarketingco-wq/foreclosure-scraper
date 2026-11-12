"""End-to-end probe: invoke each fixed scraper class on a tiny dataset and
print how many Listing objects survive the parser. This is the test that the
last run failed: actors returned items but parsers silently dropped them.

Run:
    APIFY_TOKEN=$(cat .secrets/apify_token.txt) uv run python scripts/probe_apify_parsers.py
"""
from __future__ import annotations

import asyncio
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from foreclosure_scraper.scrapers.national.zillow_bulk import ZillowBulkForeclosures
from foreclosure_scraper.scrapers.national.propwire_foreclosures import PropwireForeclosures
from foreclosure_scraper.scrapers.national.trulia_foreclosures import TruliaForeclosures
from foreclosure_scraper.scrapers.national.realtor_foreclosures import RealtorForeclosures


async def probe(name: str, scraper, cap_env: str, cap_value: int) -> None:
    os.environ[cap_env] = str(cap_value)
    print(f"=== {name}  (cap={cap_value}) ===")
    listings = await scraper.safe_run()
    print(f"  -> {len(listings)} listings parsed")
    for li in listings[:3]:
        print(f"  • {li.source_url}")
        print(f"    {li.street_address!s:.60s}  | {li.city!s}, {li.state!s} {li.zip_code!s}")
        print(f"    type={li.listing_type.value}  beds={li.bedrooms} baths={li.bathrooms}"
              f" sqft={li.living_sqft} yr={li.year_built} bid={li.opening_bid}")


async def main() -> int:
    # Tiny caps for the probe — we only need to verify parsers, not crawl fully.
    await probe("ZILLOW_BULK", ZillowBulkForeclosures(), "CAP_ZILLOW_BULK_FORECLOSURES", 5)
    await probe("PROPWIRE",    PropwireForeclosures(),   "CAP_PROPWIRE", 10)
    await probe("TRULIA",      TruliaForeclosures(),     "CAP_TRULIA_FORECLOSURES", 5)
    await probe("REALTOR",     RealtorForeclosures(),    "CAP_REALTOR_FORECLOSURES", 10)
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
