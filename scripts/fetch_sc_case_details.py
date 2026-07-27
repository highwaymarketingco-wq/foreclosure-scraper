import asyncio, json, os, sys
sys.path.insert(0, "/Users/cashhigh/foreclosure-scraper/src")
from foreclosure_scraper.http_client import client
from selectolax.parser import HTMLParser

REPO = "/Users/cashhigh/foreclosure-scraper"

async def fetch_case_detail(county, case_number):
    """Fetch a CaseDetails page via curl_cffi (tries first), fall back to noting it needs stealth."""
    url = f"https://publicindex.sccourts.org/{county}/PublicIndex/CaseDetails.aspx?CaseNum={case_number}"
    try:
        async with client(timeout=15.0) as c:
            r = await c.get(url)
            if r.status_code == 200 and len(r.text) > 2000:
                return r.text
    except:
        pass
    return None

async def main():
    with open("/tmp/sc_case_list.json") as f:
        cases = json.load(f)
    
    print(f"Total cases to process: {len(cases)}")
    
    # Prioritize: lis_pendens and foreclosure first
    # We'll process in batches of 50 with a short delay
    results = []
    batch_size = 50
    success = 0
    failed = 0
    
    for i in range(0, len(cases), batch_size):
        batch = cases[i:i+batch_size]
        tasks = [fetch_case_detail(c["county"], c["case_number"]) for c in batch]
        pages = await asyncio.gather(*tasks, return_exceptions=True)
        
        for j, (case, page) in enumerate(zip(batch, pages)):
            if isinstance(page, Exception) or not page:
                failed += 1
                continue
            
            # Parse the detail page for key fields
            tree = HTMLParser(page)
            
            # Extract all visible text fields
            detail = {
                "case_number": case["case_number"],
                "county": case["county"],
                "html_length": len(page),
                "has_detail": "Case Details" in page or "CaseInformation" in page or "PartyInformation" in page,
            }
            
            # Look for judgment amount, party info, case status
            for label in ["Judgment Amount", "Judgment", "Amount", "Filed Date", "Case Status", 
                          "Plaintiff", "Defendant", "Disposition", "Subtype", "Court Type"]:
                # Try to find label: value pairs
                import re
                pattern = rf"{label}[^<]*</[^>]+>[^<]*<[^>]+>([^<]+)"
                m = re.search(pattern, page, re.I)
                if m:
                    detail[label.lower().replace(" ", "_")] = m.group(1).strip()
            
            # Save the raw HTML for Claude to process
            safe_case = case["case_number"].replace("/", "_").replace("-", "_")
            county = case["county"] or "unknown"
            html_path = os.path.join(REPO, "sc_case_details", f"{county}_{safe_case}.html")
            os.makedirs(os.path.dirname(html_path), exist_ok=True)
            with open(html_path, "w") as f:
                f.write(page)
            
            results.append(detail)
            success += 1
        
        print(f"  Batch {i//batch_size + 1}/{(len(cases)-1)//batch_size + 1}: {success} ok, {failed} failed")
        
        if i % 200 == 0 and i > 0:
            # Save progress
            with open("/tmp/sc_case_details_progress.json", "w") as f:
                json.dump(results, f, indent=2)
    
    # Save final results
    with open("/tmp/sc_case_details.json", "w") as f:
        json.dump(results, f, indent=2)
    
    print(f"\nDone: {success} detail pages saved, {failed} failed")
    print(f"HTML files in: {REPO}/sc_case_details/")

asyncio.run(main())
