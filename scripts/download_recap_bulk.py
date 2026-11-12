#!/usr/bin/env python3
"""Download RECAP bankruptcy/foreclosure dockets from CourtListener search API.

Uses the v3 search endpoint which is the only one that works reliably.
Downloads ALL dockets for nceb,ncmb,ncwb,scb with bankruptcy/foreclosure keywords.
"""
import httpx, asyncio, json, os, sys, time
from collections import Counter

TOKEN = open(os.path.expanduser("~/foreclosure-scraper/.secrets/courtlistener_token.txt")).read().strip()
OUTPUT_FILE = "/tmp/recap_bulk_results.json"
CHECKPOINT_FILE = "/tmp/recap_bulk_checkpoint.json"

BASE_URL = "https://www.courtlistener.com/api/rest/v3/search/"
COURTS = "nceb,ncmb,ncwb,scb"
# No keyword filter — get ALL dockets, filter later

headers = {
    "Authorization": f"Token {TOKEN}",
    "Accept": "application/json",
}

async def fetch_all():
    """Page through all results."""
    # Load checkpoint
    page = 1
    all_results = []
    if os.path.exists(CHECKPOINT_FILE):
        cp = json.load(open(CHECKPOINT_FILE))
        page = cp.get("page", 1)
        all_results = cp.get("results", [])
        print(f"Resuming from page {page}, have {len(all_results)} results")
    
    async with httpx.AsyncClient(follow_redirects=True, headers=headers, timeout=30) as c:
        # First request to get total count
        params = {
            "type": "d",
            "court": COURTS,
            "filed_after": "2026-01-01",
            "q": "",  # no keyword filter — get all dockets
            "page": page,
            "order_by": "dateFiled asc",
        }
        r = await c.get(BASE_URL, params=params)
        if r.status_code != 200:
            print(f"FATAL: {r.status_code} {r.text[:300]}")
            return
        
        data = r.json()
        total = data.get("count", 0)
        print(f"Total dockets: {total}")
        print(f"Pages: {data.get('numPages', 0)}")
        
        results = data.get("results", [])
        all_results.extend(results)
        print(f"Page {page}: {len(results)} results (total: {len(all_results)})")
        
        # Check if there's a next page
        next_url = data.get("next")
        
        while next_url:
            page += 1
            try:
                r = await c.get(next_url)
                if r.status_code != 200:
                    print(f"Error on page {page}: {r.status_code}, retrying...")
                    await asyncio.sleep(5)
                    r = await c.get(next_url)
                    if r.status_code != 200:
                        print(f"Failed page {page}, skipping")
                        next_url = None
                        continue
                data = r.json()
                results = data.get("results", [])
                all_results.extend(results)
                next_url = data.get("next")
                
                if page % 10 == 0:
                    print(f"Page {page}: {len(results)} (total: {len(all_results)})")
                    # Checkpoint
                    with open(CHECKPOINT_FILE, 'w') as f:
                        json.dump({"page": page, "results": all_results}, f)
                
                # Rate limit — be nice
                await asyncio.sleep(0.5)
                
            except Exception as e:
                print(f"Exception on page {page}: {e}")
                await asyncio.sleep(5)
                continue
    
    # Save final results
    with open(OUTPUT_FILE, 'w') as f:
        json.dump(all_results, f, indent=2)
    
    # Remove checkpoint
    if os.path.exists(CHECKPOINT_FILE):
        os.remove(CHECKPOINT_FILE)
    
    # Summary
    print(f"\n{'='*60}")
    print(f"TOTAL DOCKETS DOWNLOADED: {len(all_results)}")
    
    courts = Counter(r.get("court_id", "") for r in all_results)
    print(f"\nBy court:")
    for c, n in courts.most_common():
        print(f"  {c}: {n}")
    
    # Check for bankruptcy keywords
    bk_count = sum(1 for r in all_results 
                   if "bankruptcy" in (r.get("caseName", "") + r.get("cause", "")).lower()
                   or "chapter" in (r.get("caseName", "") + r.get("cause", "")).lower())
    print(f"\nBankruptcy-related: {bk_count}")
    
    fc_count = sum(1 for r in all_results 
                   if "foreclos" in (r.get("caseName", "") + r.get("cause", "")).lower()
                   or "lis pendens" in (r.get("caseName", "") + r.get("cause", "")).lower())
    print(f"Foreclosure-related: {fc_count}")
    
    print(f"\nSaved to {OUTPUT_FILE}")
    print(f"{'='*60}")
    
    return all_results


if __name__ == "__main__":
    asyncio.run(fetch_all())
