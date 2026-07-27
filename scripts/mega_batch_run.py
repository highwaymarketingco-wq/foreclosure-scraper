import asyncio, sys, json, traceback
sys.path.insert(0, "/Users/cashhigh/foreclosure-scraper/src")
from foreclosure_scraper.scrapers._registry import all_scrapers

# Already done
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
    "national.courtlistener_bankruptcy",  # still running separately
}

# Scrapers that need a browser/are known to be very slow or broken
SKIP = {
    "counties_nc.nc_ecourts_estates",  # WAF walled, known dead-end
    "counties_nc.nc_ecourts_divorce",  # already done
    "counties_sc.sc_public_index",  # already done
    "counties_sc.sc_public_index_lis_pendens",  # already done
}

async def main():
    scrapers = all_scrapers()
    todo = [s for s in scrapers if s.slug not in DONE and s.slug not in SKIP]
    
    print(f"Total scrapers: {len(scrapers)}")
    print(f"Already done: {len(DONE)}")
    print(f"Skipping: {len(SKIP)}")
    print(f"To run: {len(todo)}")
    print()
    
    all_leads = []
    results_log = []
    
    # Run in batches of 8 (parallel within batch)
    batch_size = 8
    for i in range(0, len(todo), batch_size):
        batch = todo[i:i+batch_size]
        
        async def run_one(s):
            try:
                results = await s.safe_run()
                data = [json.loads(li.model_dump_json()) for li in results]
                return s.slug, len(results), s.last_outcome, data, None
            except Exception as e:
                return s.slug, 0, "ERROR", [], str(e)[:200]
        
        tasks = [run_one(s) for s in batch]
        outcomes = await asyncio.gather(*tasks)
        
        for slug, count, outcome, data, err in outcomes:
            all_leads.extend(data)
            status = f"OK({count})" if outcome == "OK" else outcome
            if err:
                status += f" ERR:{err[:80]}"
            print(f"  {slug}: {status}")
            results_log.append({"slug": slug, "count": count, "outcome": outcome, "error": err})
        
        print(f"  --- Batch {i//batch_size+1}/{(len(todo)-1)//batch_size+1} done. Running total: {len(all_leads)} ---")
    
    # Save everything
    with open("/tmp/mega_batch_leads.json", "w") as f:
        json.dump(all_leads, f, indent=2, default=str)
    
    with open("/tmp/mega_batch_log.json", "w") as f:
        json.dump(results_log, f, indent=2)
    
    print(f"\n=== MEGA BATCH COMPLETE ===")
    print(f"Total leads: {len(all_leads)}")
    ok = sum(1 for r in results_log if r["outcome"] == "OK")
    zero = sum(1 for r in results_log if r["outcome"] == "ZERO_RESULT")
    errors = sum(1 for r in results_log if r["outcome"] == "ERROR")
    print(f"OK: {ok}, ZERO: {zero}, ERROR: {errors}")
    print(f"Saved to /tmp/mega_batch_leads.json")

asyncio.run(main())
