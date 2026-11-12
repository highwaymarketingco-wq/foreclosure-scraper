"""One-shot probe: hit each suspect Apify actor with a SMALL test request,
print the item count + first item shape. Goal: figure out why each returned
0 results in the last full run.

Run:
    APIFY_TOKEN=$(cat .secrets/apify_token.txt) uv run python scripts/probe_apify_actors.py
"""
from __future__ import annotations

import asyncio
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from foreclosure_scraper.apify_helper import run_actor_sync
from foreclosure_scraper.budget import fetch_apify_usage


PROBES: list[tuple[str, str, dict]] = [
    (
        "zillow_bulk_county",
        "clearpath/zillow-bulk-search-unlimited-scraper",
        {
            "locations": ["Greenville County, SC"],
            "propertyType": "forSale",
            "homeTypes": ["singleFamily", "condo", "townhome", "multiFamily", "manufactured", "land"],
            "listingTypes": ["auction", "foreclosure", "foreclosed", "preforeclosure"],
            "maxResultsPerLocation": 5,
            "includePendingAndUnderContract": False,
        },
    ),
    (
        "zillow_bulk_city",
        "clearpath/zillow-bulk-search-unlimited-scraper",
        {
            "locations": ["Greenville SC", "Spartanburg SC", "Charlotte NC"],
            "propertyType": "forSale",
            "listingTypes": ["foreclosure", "foreclosed", "preforeclosure"],
            "maxResultsPerLocation": 5,
        },
    ),
    (
        "trulia_old_fp",
        "memo23/trulia-scraper",
        {
            "startUrls": [{"url": "https://www.trulia.com/for_sale/Greenville,SC/fp_y/"}],
            "maxItems": 5,
            "proxy": {"useApifyProxy": True, "apifyProxyGroups": ["RESIDENTIAL"]},
        },
    ),
    (
        "trulia_new_path",
        "memo23/trulia-scraper",
        {
            "startUrls": [{"url": "https://www.trulia.com/for_sale/Greenville,SC/foreclosures/"}],
            "maxItems": 5,
            "proxy": {"useApifyProxy": True, "apifyProxyGroups": ["RESIDENTIAL"]},
        },
    ),
    (
        "realtor_residential_proxy",
        "dz_omar/realtor-scraper",
        {
            "startUrls": [{"url": "https://www.realtor.com/realestateandhomes-search/South-Carolina/show-foreclosures"}],
            "maxResults": 5,
            "proxyConfiguration": {"useApifyProxy": True, "apifyProxyGroups": ["RESIDENTIAL"]},
        },
    ),
    (
        "realtor_default_proxy",
        "dz_omar/realtor-scraper",
        {
            "startUrls": [{"url": "https://www.realtor.com/realestateandhomes-search/South-Carolina/show-foreclosures"}],
            "maxResults": 5,
            "proxyConfiguration": {"useApifyProxy": True, "apifyProxyGroups": []},
        },
    ),
    (
        "propwire_2state",
        "memo23/propwire-leads-scraper",
        {
            "startUrls": [
                {"url": "https://propwire.com/search?filters=%7B%22locations%22%3A%5B%7B%22searchType%22%3A%22T%22%2C%22state%22%3A%22SC%22%2C%22title%22%3A%22South%20Carolina%2C%20USA%22%2C%22stateName%22%3A%22South%20Carolina%22%7D%5D%2C%22lead_type%22%3A%5B%22preforeclosure%22%5D%7D"}
            ],
            "maxItems": 5,
            "proxy": {"useApifyProxy": True, "apifyProxyGroups": ["RESIDENTIAL"]},
        },
    ),
]


async def main() -> int:
    print("=== PRE-PROBE BUDGET ===")
    info = await fetch_apify_usage()
    print(f"used: ${info.get('used_usd'):.2f} / ${info.get('limit_usd'):.2f}  remaining: ${info.get('remaining_usd'):.2f}")
    print()

    for name, actor, run_input in PROBES:
        print(f"=== PROBE: {name}  ({actor}) ===")
        items = await run_actor_sync(actor, run_input, timeout_s=180, estimated_cost_usd=0.10)
        print(f"  -> {len(items)} items returned")
        if items:
            sample = items[0]
            keys = sorted(sample.keys())[:30] if isinstance(sample, dict) else "(non-dict)"
            print(f"  sample keys: {keys}")
            # Show key fields
            if isinstance(sample, dict):
                for k in ("url", "detailUrl", "hdpUrl", "address", "streetAddress", "price", "homeStatus", "status"):
                    if k in sample:
                        v = sample[k]
                        v_short = str(v)[:120]
                        print(f"  {k}: {v_short}")
        print()

    # Re-clear cache to get fresh budget
    import foreclosure_scraper.budget as B
    B._usage_cache = None
    print("=== POST-PROBE BUDGET ===")
    info = await fetch_apify_usage()
    print(f"used: ${info.get('used_usd'):.2f} / ${info.get('limit_usd'):.2f}  remaining: ${info.get('remaining_usd'):.2f}")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
