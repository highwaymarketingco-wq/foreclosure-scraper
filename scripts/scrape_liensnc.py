#!/usr/bin/env python3
"""Scrape all LiensNC filings via login + advanced search pagination.
1000 pages × 100 entries = ~100,000 NC lien filings."""
import httpx, asyncio, re, json, os, sys
from selectolax.parser import HTMLParser
from datetime import datetime
from collections import Counter

LIENSNC_USER = os.environ.get("LIENSNC_USER", "cashhigh")
LIENSNC_PASS = os.environ.get("LIENSNC_PASS", "!F8Bb8i8am$NtiZ")

OUTPUT_FILE = "/tmp/liensnc_results.json"
CHECKPOINT_FILE = "/tmp/liensnc_checkpoint.json"
BASE = "https://apps.liensnc.com"
SEARCH_URL = f"{BASE}/scr/filing/advancedSearch.html"
LOGIN_URL = f"{BASE}/scr/login.html"
AUTH_URL = f"{BASE}/scr/j_spring_security_check"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
}

ADDR_RE = re.compile(
    r'(\d{1,5}\s+[A-Z][\w\s\.\'-]+?(?:Street|St\.?|Avenue|Ave\.?|Road|Rd\.?|Drive|Dr\.?|Lane|Ln\.?|Boulevard|Blvd\.?|Way|Place|Pl\.?|Court|Ct\.?|Highway|Hwy\.?))',
    re.MULTILINE
)
CITY_STATE_RE = re.compile(r'([A-Z][\w\s]+?),\s*(?:[A-Z]{2})?\s*(\d{5})?')
PIN_RE = re.compile(r'(?:pin|tms|parcel|tax\s*map)\s*#?\s*:?\s*([\w\-]+)', re.IGNORECASE)


def parse_results(html_text):
    """Parse a page of LiensNC search results."""
    tree = HTMLParser(html_text)
    table = tree.css_first('table.table-striped')
    if not table:
        return []

    results = []
    rows = table.css('tr')
    
    for row in rows[1:]:  # skip header
        cells = row.css('td')
        if len(cells) < 5:
            continue
        
        # Cell 0: Filing type + date + entry number
        cell0 = cells[0].text(separator='\n', strip=True)
        filing_type = cell0.split('\n')[0] if cell0 else ''
        date_match = re.search(r'(\d{2}/\d{2}/\d{4})', cell0)
        filing_date = date_match.group(1) if date_match else ''
        entry_match = re.search(r'Entry\s*#:\s*(\d+)', cell0)
        entry_num = entry_match.group(1) if entry_match else ''
        
        # Cell 1: Filed by
        filed_by = cells[1].text(strip=True)
        
        # Cell 2: Project property (address, project name, etc.)
        cell2 = cells[2].text(separator='\n', strip=True)
        property_text = cell2
        
        # Cell 3: Owner info
        cell3 = cells[3].text(separator='\n', strip=True)
        owner_text = cell3
        
        # Cell 4: Active related filings
        related = cells[4].text(strip=True)
        
        # Extract address from property text
        addr_match = ADDR_RE.search(property_text)
        address = addr_match.group(1).strip() if addr_match else ''
        
        # Extract PIN/TMS
        pin_match = PIN_RE.search(property_text)
        pin = pin_match.group(1) if pin_match else ''
        
        # Extract city/state/zip from property or owner text
        city_state = CITY_STATE_RE.search(property_text + ' ' + owner_text)
        city = city_state.group(1).strip() if city_state else ''
        zip_code = city_state.group(2) if city_state and city_state.group(2) else ''
        
        # Get detail link
        detail_link = ''
        for a in cells[0].css('a'):
            href = a.attributes.get('href', '') or ''
            if 'details.html' in href:
                detail_link = href if href.startswith('http') else f"{BASE}{href}"
                break
        
        result = {
            'entry_number': entry_num,
            'filing_type': filing_type,
            'filing_date': filing_date,
            'filed_by': filed_by,
            'property_text': property_text[:500],
            'owner_text': owner_text[:500],
            'address': address,
            'pin': pin,
            'city': city,
            'zip_code': zip_code,
            'related_filings': related,
            'detail_url': detail_link,
            'source': 'liensnc',
        }
        results.append(result)
    
    return results


async def scrape_all():
    all_results = []
    
    # Load checkpoint
    if os.path.exists(CHECKPOINT_FILE):
        with open(CHECKPOINT_FILE) as f:
            state = json.load(f)
            all_results = state.get('results', [])
            start_page = state.get('last_page', 0) + 1
            print(f"Resuming from page {start_page}, {len(all_results)} results already scraped")
    else:
        start_page = 1
    
    async with httpx.AsyncClient(follow_redirects=True, headers=HEADERS, timeout=30) as c:
        # Login
        print("Logging in to LiensNC...")
        await c.get(LOGIN_URL)
        r = await c.post(AUTH_URL, data={
            "j_username": LIENSNC_USER,
            "j_password": LIENSNC_PASS,
        }, headers={
            "Content-Type": "application/x-www-form-urlencoded",
            "Origin": BASE,
            "Referer": LOGIN_URL,
        })
        if 'login' in str(r.url).lower():
            print(f"LOGIN FAILED! URL: {r.url}")
            return
        print(f"Logged in! URL: {r.url}")
        
        # Search params — broad search, all dates, sorted by date desc
        params = {
            "keywords": "",
            "filingDateFrom": "01/01/2010",
            "filingDateTo": "12/31/2026",
            "sort": "FILING_DATE",
            "sortDesc": "true",
            "pager.middleButtonsCount": "10",
            "showResults": "1",
        }
        
        total_pages = 1000  # confirmed from Last link
        consecutive_empty = 0
        
        for page_num in range(start_page, total_pages + 1):
            params["currentPage"] = str(page_num)
            
            try:
                r = await c.get(SEARCH_URL, params=params)
                text = r.content.decode('utf-8', errors='replace')
            except Exception as e:
                print(f"  Page {page_num}: ERROR - {e}, retrying in 3s...")
                await asyncio.sleep(3)
                try:
                    r = await c.get(SEARCH_URL, params=params)
                    text = r.content.decode('utf-8', errors='replace')
                except Exception as e2:
                    print(f"  Page {page_num}: RETRY FAILED - {e2}")
                    continue
            
            # Check if redirected to login (session expired)
            if 'login' in str(r.url).lower():
                print(f"  Page {page_num}: Session expired, re-logging in...")
                await c.get(LOGIN_URL)
                await c.post(AUTH_URL, data={
                    "j_username": LIENSNC_USER,
                    "j_password": LIENSNC_PASS,
                }, headers={"Content-Type": "application/x-www-form-urlencoded", "Origin": BASE, "Referer": LOGIN_URL})
                # Retry
                r = await c.get(SEARCH_URL, params=params)
                text = r.content.decode('utf-8', errors='replace')
            
            page_results = parse_results(text)
            all_results.extend(page_results)
            
            if len(page_results) == 0:
                consecutive_empty += 1
                if consecutive_empty >= 3:
                    print(f"  Page {page_num}: 3 consecutive empty pages, stopping")
                    break
            else:
                consecutive_empty = 0
            
            if page_num % 10 == 0 or page_num == total_pages:
                print(f"  Page {page_num}/{total_pages}: {len(page_results)} results (total: {len(all_results)})")
                # Checkpoint every 10 pages
                with open(CHECKPOINT_FILE, 'w') as f:
                    json.dump({'results': all_results, 'last_page': page_num}, f)
            
            # Rate limiting — be gentle
            await asyncio.sleep(0.3)
    
    # Final save
    with open(OUTPUT_FILE, 'w') as f:
        json.dump(all_results, f, indent=2)
    
    # Summary
    with_addr = [r for r in all_results if r.get('address')]
    with_pin = [r for r in all_results if r.get('pin')]
    with_city = [r for r in all_results if r.get('city')]
    with_entry = [r for r in all_results if r.get('entry_number')]
    
    print(f"\n{'='*60}")
    print(f"TOTAL LIENSNC FILINGS SCRAPED: {len(all_results)}")
    print(f"  With entry #: {len(with_entry)}")
    print(f"  With address: {len(with_addr)}")
    print(f"  With PIN/TMS: {len(with_pin)}")
    print(f"  With city: {len(with_city)}")
    
    print(f"\nFiling type breakdown:")
    types = Counter(r.get('filing_type', 'Unknown') for r in all_results)
    for t, count in types.most_common(10):
        print(f"  {t}: {count}")
    
    print(f"\nSaved to {OUTPUT_FILE}")
    print(f"{'='*60}")
    
    # Cleanup checkpoint
    if os.path.exists(CHECKPOINT_FILE):
        os.remove(CHECKPOINT_FILE)
    
    return all_results


if __name__ == '__main__':
    asyncio.run(scrape_all())
