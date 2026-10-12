#!/usr/bin/env python3
"""Run Polk production scraper and save results to walled_output."""
import asyncio
import sys
import os
import json

sys.path.insert(0, "src")
os.environ["DISPLAY"] = ":99"

from foreclosure_scraper.scrapers.counties_nc.polk_tax import PolkTaxAuction


async def main():
    scraper = PolkTaxAuction()
    listings = await scraper.fetch()
    print(f"TOTAL LISTINGS: {len(listings)}", flush=True)
    if listings:
        out_path = "data/walled_output/polk_tax.json"
        os.makedirs("data/walled_output", exist_ok=True)
        data = [l.to_dict() if hasattr(l, "to_dict") else l for l in listings]
        with open(out_path, "w") as f:
            json.dump(data, f, indent=2)
        print(f"Saved {len(listings)} listings to {out_path}", flush=True)
        for l in listings[:5]:
            print(f"  Sample: {l}", flush=True)
    else:
        print("No listings collected!", flush=True)
    print("DONE", flush=True)


asyncio.run(main())
