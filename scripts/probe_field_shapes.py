"""Probe: dump full first item from each actor so we see exact field types.

Need to know:
- Propwire `lead_type` value type (list, dict, or string?)
- Zillow rawData inner shape (what's inside)
- Realtor 'type-foreclosure' URL pattern - does it return any items?
"""
from __future__ import annotations

import asyncio
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from foreclosure_scraper.apify_helper import run_actor_sync


async def main() -> int:
    print("=== PROPWIRE FULL ITEM ===")
    items = await run_actor_sync(
        "memo23/propwire-leads-scraper",
        {
            "startUrls": [
                {"url": "https://propwire.com/search?filters=%7B%22locations%22%3A%5B%7B%22searchType%22%3A%22T%22%2C%22state%22%3A%22SC%22%2C%22title%22%3A%22South%20Carolina%2C%20USA%22%2C%22stateName%22%3A%22South%20Carolina%22%7D%5D%2C%22lead_type%22%3A%5B%22preforeclosure%22%5D%7D"}
            ],
            "maxItems": 2,
            "proxy": {"useApifyProxy": True, "apifyProxyGroups": ["RESIDENTIAL"]},
        },
        timeout_s=180,
        estimated_cost_usd=0.05,
    )
    if items:
        print(json.dumps(items[0], indent=2, default=str)[:3500])
    print()

    print("=== ZILLOW rawData INNER ===")
    items = await run_actor_sync(
        "clearpath/zillow-bulk-search-unlimited-scraper",
        {
            "locations": ["Greenville SC"],
            "propertyType": "forSale",
            "listingTypes": ["foreclosure", "foreclosed", "preforeclosure"],
            "maxResultsPerLocation": 2,
        },
        timeout_s=180,
        estimated_cost_usd=0.05,
    )
    if items:
        wrapped = items[0]
        print("WRAPPED keys:", list(wrapped.keys()) if isinstance(wrapped, dict) else "(non-dict)")
        if isinstance(wrapped, dict) and isinstance(wrapped.get("rawData"), dict):
            inner = wrapped["rawData"]
            print("rawData keys:", sorted(inner.keys())[:40])
            print("rawData hdpUrl:", inner.get("hdpUrl"))
            print("rawData detailUrl:", inner.get("detailUrl"))
            print("rawData zpid:", inner.get("zpid"))
        else:
            print("FULL ITEM:", json.dumps(wrapped, indent=2, default=str)[:1500])
    print()

    print("=== REALTOR type-foreclosure URL ===")
    items = await run_actor_sync(
        "dz_omar/realtor-scraper",
        {
            "startUrls": [{"url": "https://www.realtor.com/realestateandhomes-search/South-Carolina/type-foreclosure"}],
            "maxResults": 3,
            "proxyConfiguration": {"useApifyProxy": True, "apifyProxyGroups": []},
        },
        timeout_s=180,
        estimated_cost_usd=0.05,
    )
    print(f"got {len(items)} items")
    if items:
        s = items[0]
        print("flags:", s.get("flags"))
        print("status:", s.get("status"))
        print("href:", s.get("href"))
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
