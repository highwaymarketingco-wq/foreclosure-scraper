import asyncio, sys, json
sys.path.insert(0, "/Users/cashhigh/foreclosure-scraper/src")
from foreclosure_scraper.scrapers._registry import all_scrapers

all_sc = {s.slug: s for s in all_scrapers()}

TO_RUN = [
    "national.sheriff_sales",
    "national.craigslist_fsbo", 
    "national.estate_sales",
    "national.cash_buyer_deeds",
    "national.landwatch",
    "national.landandfarm",
    "national.landsofamerica",
    "national.nc_upset_bids",
]

async def main():
    all_leads = []
    log = []
    
    for slug in TO_RUN:
        if slug not in all_sc:
            print(f"SKIP {slug} (not in registry)", flush=True)
            # Try importing directly
            continue
        s = all_sc[slug]
        try:
            results = await s.safe_run()
            data = [json.loads(li.model_dump_json()) for li in results]
            all_leads.extend(data)
            print(f"{slug}: {len(results)} leads ({s.last_outcome})", flush=True)
            log.append({"slug": slug, "count": len(results), "outcome": s.last_outcome})
        except Exception as e:
            print(f"{slug}: ERROR {str(e)[:100]}", flush=True)
            log.append({"slug": slug, "count": 0, "outcome": "ERROR", "error": str(e)[:200]})
    
    with open("/tmp/new_scraper_leads.json", "w") as f:
        json.dump(all_leads, f, indent=2, default=str)
    with open("/tmp/new_scraper_log.json", "w") as f:
        json.dump(log, f, indent=2)
    
    print(f"\nTOTAL: {len(all_leads)} leads from {len(log)} scrapers", flush=True)

asyncio.run(main())
