#!/usr/bin/env python3
"""Mega batch runner v2 - smaller batches, skip browser-heavy scrapers."""
import asyncio
import json
import sys
import traceback

sys.path.insert(0, "/Users/cashhigh/foreclosure-scraper/src")
from foreclosure_scraper.scrapers._registry import all_scrapers

DONE = {
    "counties_nc.nc_ecourts_lis_pendens",
    "counties_nc.nc_ecourts_divorce",
    "counties_sc.sc_public_index",
    "counties_sc.sc_public_index_lis_pendens",
    "law_firms.brock_scott",
    "law_firms.hutchens",
    "law_firms.bell_carrington",
    "law_firms.ingle_firm",
    "counties_sc.sc_probate_net",
    "public_notices.gannett_obituaries",
    "counties_sc.sc_flc",
    "counties_sc.sc_delinquent_tax_list",
    "counties_sc.sc_county_rosters",
    "newspapers.shelby_star",
    "newspapers.daily_courier",
    "newspapers.index_journal",
    "counties.column_legal_notices",
    "national.courtlistener_bankruptcy",
}

# Skip browser-heavy or known-broken scrapers to avoid EPIPE
SKIP = {
    "counties_nc.nc_ecourts_estates",  # WAF walled
    "counties_sc.sc_public_index",  # already done
    "counties_sc.sc_public_index_lis_pendens",  # already done
    "counties_sc.sc_rod_acclaim",  # browser heavy
    "counties_sc.sc_rod_cott",  # browser heavy
    "counties_nc.nc_rod_logan",  # browser heavy
    "counties_nc.nc_rod_substitute_trustee",  # browser heavy
    "counties_sc.sc_coastal_rosters",  # browser heavy
    "counties_sc.spartanburg_vacant",  # browser heavy
    "counties_sc.spartanburg_condemned",  # browser heavy
    "counties_nc.asheville_helene",  # browser heavy
    "counties_nc.asheville_str_permits",  # browser heavy
    "counties_nc.buncombe_elderly",  # browser heavy
    "counties_nc.nc_heir_estate_parcels",  # browser heavy (GIS)
    "city_websites.search",  # browser heavy
    "counties.sitemap_walker",  # browser heavy
    "counties.nod_discovery",  # browser heavy
}


async def run_one(s):
    try:
        results = await s.safe_run()
        data = [json.loads(li.model_dump_json()) for li in results]
        return s.slug, len(results), s.last_outcome, data, None
    except Exception as e:
        return s.slug, 0, "ERROR", [], str(e)[:200]


async def main():
    scrapers = all_scrapers()
    todo = [s for s in scrapers if s.slug not in DONE and s.slug not in SKIP]

    print(f"To run: {len(todo)}")
    print(f"Skip: {len(SKIP)}")
    print()

    all_leads = []
    results_log = []
    batch_size = 4

    for i in range(0, len(todo), batch_size):
        batch = todo[i:i + batch_size]
        slugs = [s.slug for s in batch]
        print(f"Batch {i//batch_size+1}: {', '.join(slugs)}")

        tasks = [run_one(s) for s in batch]
        outcomes = await asyncio.gather(*tasks)

        for slug, count, outcome, data, err in outcomes:
            all_leads.extend(data)
            status = f"OK({count})" if outcome == "OK" else outcome
            if err:
                status += f" ERR:{err[:80]}"
            print(f"  {slug}: {status}")
            results_log.append({"slug": slug, "count": count, "outcome": outcome, "error": err})

        print(f"  Running total: {len(all_leads)} leads")
        print()

        # Small pause between batches
        await asyncio.sleep(1)

    with open("/tmp/mega_batch_leads.json", "w") as f:
        json.dump(all_leads, f, indent=2, default=str)
    with open("/tmp/mega_batch_log.json", "w") as f:
        json.dump(results_log, f, indent=2)

    print(f"=== MEGA BATCH COMPLETE ===")
    print(f"Total leads: {len(all_leads)}")
    ok = sum(1 for r in results_log if r["outcome"] == "OK")
    zero = sum(1 for r in results_log if r["outcome"] == "ZERO_RESULT")
    errors = sum(1 for r in results_log if r["outcome"] == "ERROR")
    print(f"OK: {ok}, ZERO: {zero}, ERROR: {errors}")
    print(f"Saved to /tmp/mega_batch_leads.json")


if __name__ == "__main__":
    asyncio.run(main())
