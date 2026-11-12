#!/usr/bin/env python3
"""Run NC eCourts (Tyler Odyssey) judgment search and save foreclosure-relevant hits."""
import httpx, asyncio, json, os, sys
from datetime import datetime, timedelta
from collections import Counter

SERVICE_URL = "https://portal-nc.tylertech.cloud/app/NCJudgmentSearchService/search"
APP_BASE = "https://portal-nc.tylertech.cloud/app/NCJudgmentSearch/"
OUTPUT_FILE = "/tmp/ncecourts_results.json"

NC_COUNTIES = [
    "Buncombe", "Henderson", "Rutherford", "Cleveland", "Polk",
    "Gaston", "Transylvania", "McDowell", "Lincoln", "Madison",
    "Mitchell", "Burke", "Carteret", "Onslow", "Brunswick",
    "Pender", "New Hanover",
]

FORECLOSURE_CAUSES = {
    "CV - Lis Pendens", "CV - Claim of Lien", "CV - Lien",
    "CV - Possession", "CV - Federal Tax Lien",
}

headers = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
    "Accept": "application/json, text/plain, */*",
    "Content-Type": "application/json",
    "Origin": "https://portal-nc.tylertech.cloud",
    "Referer": APP_BASE,
}


def _build_search(template, counties, from_date, to_date, page_from=0, page_size=200):
    so = json.loads(json.dumps(template))
    so["queryString"] = ""
    so["from"] = page_from
    so["size"] = page_size
    so["parameters"] = {
        "fromDate": from_date.strftime("%Y-%m-%dT%H:%M:%S"),
        "toDate": to_date.strftime("%Y-%m-%dT%H:%M:%S"),
    }
    location_buckets = []
    for cnty in counties:
        for ct in ("District Court", "Superior Court"):
            location_buckets.append({
                "name": f"{cnty} {ct}", "count": 0, "selected": True,
                "rangeFrom": None, "rangeTo": None, "displayOrder": 0,
            })
    so["facets"] = [
        {"name": "Judgment Type", "type": "MultiSelect",
         "indexFieldName": "judgmentType.sort", "displayOrder": 1, "buckets": []},
        {"name": "Sentence Type", "type": "MultiSelect",
         "indexFieldName": "sentenceType.sort", "displayOrder": 2, "buckets": []},
        {"name": "Location", "type": "MultiSelect",
         "indexFieldName": "countyNodes.countyNode.sort",
         "displayOrder": 3, "buckets": location_buckets},
    ]
    return so


def _hit_to_listing(h):
    """Convert Tyler hit to our listing format."""
    # location field is like "Buncombe District Court"
    location = h.get("location", "") or ""
    county = ""
    for cnty in NC_COUNTIES:
        if cnty.upper() in location.upper():
            county = cnty
            break
    
    # debtors list has names
    debtors = h.get("debtors", [])
    creditors = h.get("creditors", [])
    
    debtor_names = [d.get("name", "") for d in debtors if d.get("name")]
    creditor_names = [c.get("name", "") for c in creditors if c.get("name")]
    
    defendant = "; ".join(debtor_names) if debtor_names else ""
    plaintiff = "; ".join(creditor_names) if creditor_names else ""
    
    return {
        "source": "nc_ecourts_judgments",
        "source_url": APP_BASE,
        "case_number": h.get("caseNumber", ""),
        "defendant": defendant,
        "plaintiff": plaintiff,
        "cause_of_action": h.get("causeOfActionDesc", ""),
        "court_name": location,
        "county": county,
        "state": "NC",
        "judgment_date": h.get("orderedDate", ""),
        "judgment_type": h.get("judgmentType", ""),
        "civil_judgment_status": h.get("civilJudgmentStatus", ""),
        "case_id": h.get("caseID", ""),
        "judgment_id": h.get("judgmentId", ""),
        "debtors_raw": debtors,
        "creditors_raw": creditors,
        "raw_tyler": h,
    }


async def run_search():
    print("=== NC eCourts (Tyler Odyssey) Judgment Search ===")
    
    async with httpx.AsyncClient(follow_redirects=True, headers=headers, timeout=30, http2=True) as c:
        # Get session
        await c.get(APP_BASE)
        
        # Get template — CRITICAL: must use content=b"" not json={}
        r = await c.post(SERVICE_URL, content=b"")
        if r.status_code not in (200, 201):
            print(f"FATAL: Template fetch failed: {r.status_code}")
            return
        template = r.json()
        print(f"Template loaded")
        
        # Search past 365 days for maximum coverage
        to_date = datetime.now()
        from_date = to_date - timedelta(days=365)
        
        all_hits = []
        all_fc_hits = []
        page_from = 0
        page_size = 200
        
        while True:
            so = _build_search(template, NC_COUNTIES, from_date, to_date, page_from, page_size)
            r2 = await c.post(SERVICE_URL, json=so)
            if r2.status_code not in (200, 201):
                print(f"Search failed at page_from={page_from}: {r2.status_code}")
                break
            
            data = r2.json()
            total = data.get('searchResult', {}).get('totalHits', 0)
            hits = data.get('searchResult', {}).get('hits', [])
            
            if page_from == 0:
                print(f"Total judgment hits (365 days): {total}")
            
            fc_hits = [h for h in hits if h.get('causeOfActionDesc') in FORECLOSURE_CAUSES]
            all_hits.extend(hits)
            all_fc_hits.extend(fc_hits)
            
            if (page_from // page_size) % 10 == 0:
                print(f"  Page from={page_from}: {len(hits)} hits, {len(fc_hits)} foreclosure (total FC: {len(all_fc_hits)})")
            
            page_from += page_size
            if page_from >= total:
                break
            
            # Be gentle
            await asyncio.sleep(0.3)
    
    # Convert to listing format
    listings = [_hit_to_listing(h) for h in all_fc_hits]
    
    # Save
    with open(OUTPUT_FILE, 'w') as f:
        json.dump(listings, f, indent=2)
    
    # Summary
    print(f"\n{'='*60}")
    print(f"TOTAL JUDGMENT HITS: {len(all_hits)}")
    print(f"FORECLOSURE-RELEVANT: {len(all_fc_hits)}")
    
    causes = Counter(h.get('causeOfActionDesc', '') for h in all_fc_hits)
    print(f"\nBy cause of action:")
    for c, n in causes.most_common():
        print(f"  {c}: {n}")
    
    counties = Counter(l.get('county', 'Unknown') for l in listings)
    print(f"\nBy county:")
    for c, n in counties.most_common():
        print(f"  {c}: {n}")
    
    with_addr = [l for l in listings if l.get('address')]
    print(f"\nWith address: {len(with_addr)}")
    
    print(f"\nSaved {len(listings)} foreclosure listings to {OUTPUT_FILE}")
    print(f"{'='*60}")
    
    return listings


if __name__ == '__main__':
    asyncio.run(run_search())
