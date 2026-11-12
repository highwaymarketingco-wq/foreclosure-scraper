#!/usr/bin/env python3
"""Scrape all foreclosure notices from scpublicnotices.com (100 pages of results)."""
import httpx, asyncio, re, json, sys, os
from selectolax.parser import HTMLParser
from collections import Counter
from datetime import datetime

OUTPUT_FILE = "/tmp/publicnoticesc_results.json"
CHECKPOINT_FILE = "/tmp/publicnoticesc_checkpoint.json"
BASE_URL = "https://www.scpublicnotices.com/Search.aspx"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
}

SIMPLE_ADDR_RE = re.compile(
    r'\b(\d{1,5}\s+[A-Z][\w\s\.]+?(?:Street|St\.?|Avenue|Ave\.?|Road|Rd\.?|Drive|Dr\.?|Lane|Ln\.?|Boulevard|Blvd\.?|Way|Place|Pl\.?|Court|Ct\.?|Highway|Hwy\.?))\b',
    re.MULTILINE
)
CASE_RE = re.compile(r'(?:C/A|CIVIL ACTION)\s*(?:NO\.?|No\.?)\s*:?\s*([\w\-]+)', re.IGNORECASE)
DEBTOR_RE = re.compile(r'(?:v\.|vs\.|versus)\s+([A-Z][\w\s,\.]+?)(?:;|,|aka|\)|\n|Defendant)', re.IGNORECASE)
TMS_RE = re.compile(r'(?:TMS|PIN|Parcel|Tax\s+Map)\s*(?:#|No\.?|Number)?\s*:?\s*([\w\-]+)', re.IGNORECASE)


def parse_page_results(html_text):
    """Parse a single page of ASP.NET GridView results."""
    tree = HTMLParser(html_text)
    results_table = tree.css_first('table.wsResultsGrid')
    if not results_table:
        return []

    notices = []
    current_meta = {}
    rows = results_table.css('tr')

    for row in rows:
        cells = row.css('td')
        for cell in cells:
            cell_text = cell.text(strip=True)
            if not cell_text or len(cell_text) < 10:
                continue

            # Meta row: newspaper + day + city + county
            day_match = re.search(r'(\w+day,\s+\w+\s+\d+,\s+\d{4})', cell_text)
            if day_match and 'City:' in cell_text and 'County:' in cell_text:
                newspaper = cell_text.split(day_match.group(1))[0].strip()
                city_match = re.search(r'City:\s*(\w+)', cell_text)
                county_match = re.search(r'County:\s*(\w+)', cell_text)
                current_meta = {
                    'newspaper': newspaper,
                    'date': day_match.group(1),
                    'city': city_match.group(1) if city_match else '',
                    'county': county_match.group(1) if county_match else '',
                }
            elif len(cell_text) > 80:
                # Notice text
                case_m = CASE_RE.search(cell_text)
                debtor_m = DEBTOR_RE.search(cell_text)
                addr_m = SIMPLE_ADDR_RE.search(cell_text)
                tms_m = TMS_RE.search(cell_text)

                notice = {
                    **current_meta,
                    'text': cell_text[:3000],
                    'case_number': case_m.group(1) if case_m else '',
                    'debtor': debtor_m.group(1).strip() if debtor_m else '',
                    'address': addr_m.group(1).strip() if addr_m else '',
                    'tms': tms_m.group(1).strip() if tms_m else '',
                    'source': 'publicnoticesc',
                    'source_url': 'https://www.scpublicnotices.com/Search.aspx',
                }
                notices.append(notice)

    return notices


def get_hidden_fields(html_text):
    """Extract all hidden form fields from ASP.NET page."""
    tree = HTMLParser(html_text)
    data = {}
    for inp in tree.css('input[type="hidden"]'):
        name = inp.attributes.get('name', '')
        val = inp.attributes.get('value', '') or ''
        if name:
            data[name] = val
    return data


async def scrape_all():
    all_notices = []

    # Load checkpoint if exists
    if os.path.exists(CHECKPOINT_FILE):
        with open(CHECKPOINT_FILE) as f:
            state = json.load(f)
            all_notices = state.get('notices', [])
            start_page = state.get('last_page', 0) + 1
            print(f"Resuming from page {start_page}, {len(all_notices)} notices already scraped")
    else:
        start_page = 1

    async with httpx.AsyncClient(follow_redirects=True, headers=HEADERS, timeout=45) as c:
        if start_page == 1:
            # Step 1: GET search page
            r = await c.get(BASE_URL)
            session_url = str(r.url)
            text = r.content.decode('utf-8', errors='replace')
            form_data = get_hidden_fields(text)

            # Step 2: POST to trigger Foreclosures dropdown
            data = dict(form_data)
            data['__EVENTTARGET'] = 'ctl00$ContentPlaceHolder1$as1$ddlPopularSearches'
            data['__EVENTARGUMENT'] = ''
            data['ctl00$ContentPlaceHolder1$as1$ddlPopularSearches'] = '4'
            data['ctl00$ContentPlaceHolder1$as1$txtSearch'] = ''
            data['ctl00$ContentPlaceHolder1$as1$rdoType'] = 'OR'

            r2 = await c.post(session_url, data=data, headers={
                **HEADERS,
                "Content-Type": "application/x-www-form-urlencoded",
                "Origin": "https://www.scpublicnotices.com",
                "Referer": session_url,
            })
            text = r2.content.decode('utf-8', errors='replace')

            # Parse page count
            page_match = re.search(r'(\d+)\s*</span>\s*<span[^>]*>\s*of\s*(\d+)\s*Pages', text)
            total_pages = int(page_match.group(2)) if page_match else 1
            print(f"Total pages: {total_pages}")

            page_notices = parse_page_results(text)
            all_notices.extend(page_notices)
            print(f"  Page 1: {len(page_notices)} notices (total: {len(all_notices)})")

            # Checkpoint
            with open(CHECKPOINT_FILE, 'w') as f:
                json.dump({'notices': all_notices, 'last_page': 1, 'total_pages': total_pages}, f)

            next_page = 2
        else:
            # Resume — need to re-establish session and navigate to the right page
            # Simpler: restart from page 1 and skip to the checkpoint page
            print(f"Re-establishing session to resume at page {start_page}...")
            r = await c.get(BASE_URL)
            session_url = str(r.url)
            text = r.content.decode('utf-8', errors='replace')
            form_data = get_hidden_fields(text)

            # Trigger foreclosures search
            data = dict(form_data)
            data['__EVENTTARGET'] = 'ctl00$ContentPlaceHolder1$as1$ddlPopularSearches'
            data['__EVENTARGUMENT'] = ''
            data['ctl00$ContentPlaceHolder1$as1$ddlPopularSearches'] = '4'
            data['ctl00$ContentPlaceHolder1$as1$txtSearch'] = ''
            data['ctl00$ContentPlaceHolder1$as1$rdoType'] = 'OR'

            r2 = await c.post(session_url, data=data, headers={
                **HEADERS,
                "Content-Type": "application/x-www-form-urlencoded",
                "Origin": "https://www.scpublicnotices.com",
                "Referer": session_url,
            })
            text = r2.content.decode('utf-8', errors='replace')

            page_match = re.search(r'(\d+)\s*</span>\s*<span[^>]*>\s*of\s*(\d+)\s*Pages', text)
            total_pages = int(page_match.group(2)) if page_match else 1

            # Fast-forward by clicking Next until we reach start_page
            # This is unavoidable with ASP.NET GridView paging
            for p in range(2, start_page + 1):
                new_form = get_hidden_fields(text)
                new_form['__EVENTTARGET'] = ''
                new_form['__EVENTARGUMENT'] = ''
                new_form['ctl00$ContentPlaceHolder1$WSExtendedGridNP1$GridView1$ctl01$btnNext'] = 'Next'
                new_form['ctl00$ContentPlaceHolder1$as1$txtSearch'] = ''
                new_form['ctl00$ContentPlaceHolder1$as1$rdoType'] = 'OR'
                new_form['ctl00$ContentPlaceHolder1$as1$ddlPopularSearches'] = '4'

                r3 = await c.post(session_url, data=new_form, headers={
                    **HEADERS,
                    "Content-Type": "application/x-www-form-urlencoded",
                    "Origin": "https://www.scpublicnotices.com",
                    "Referer": session_url,
                })
                text = r3.content.decode('utf-8', errors='replace')
                if p % 10 == 0:
                    print(f"  Fast-forwarding to page {start_page}, at page {p}...")
                await asyncio.sleep(0.2)

            next_page = start_page + 1
            print(f"  Resumed at page {start_page}, continuing from {next_page}")

        # Paginate through remaining pages
        for page_num in range(next_page, min(total_pages + 1, 101)):
            new_form = get_hidden_fields(text)
            new_form['__EVENTTARGET'] = ''
            new_form['__EVENTARGUMENT'] = ''
            new_form['ctl00$ContentPlaceHolder1$WSExtendedGridNP1$GridView1$ctl01$btnNext'] = 'Next'
            new_form['ctl00$ContentPlaceHolder1$as1$txtSearch'] = ''
            new_form['ctl00$ContentPlaceHolder1$as1$rdoType'] = 'OR'
            new_form['ctl00$ContentPlaceHolder1$as1$ddlPopularSearches'] = '4'

            try:
                r3 = await c.post(session_url, data=new_form, headers={
                    **HEADERS,
                    "Content-Type": "application/x-www-form-urlencoded",
                    "Origin": "https://www.scpublicnotices.com",
                    "Referer": session_url,
                })
                text = r3.content.decode('utf-8', errors='replace')
            except Exception as e:
                print(f"  Page {page_num}: ERROR - {e}, retrying...")
                await asyncio.sleep(2)
                continue

            page_notices = parse_page_results(text)
            all_notices.extend(page_notices)

            if page_num % 5 == 0 or page_num == total_pages:
                print(f"  Page {page_num}/{total_pages}: {len(page_notices)} notices (total: {len(all_notices)})")

                # Checkpoint every 5 pages
                with open(CHECKPOINT_FILE, 'w') as f:
                    json.dump({'notices': all_notices, 'last_page': page_num, 'total_pages': total_pages}, f)

            if len(page_notices) == 0 and page_num > 2:
                print(f"  No more results at page {page_num}, stopping")
                break

            await asyncio.sleep(0.3)

    # Final save
    with open(OUTPUT_FILE, 'w') as f:
        json.dump(all_notices, f, indent=2)

    # Summary
    with_case = [n for n in all_notices if n.get('case_number')]
    with_debtor = [n for n in all_notices if n.get('debtor')]
    with_address = [n for n in all_notices if n.get('address')]
    with_county = [n for n in all_notices if n.get('county')]
    print(f"\n{'='*60}")
    print(f"TOTAL NOTICES SCRAPED: {len(all_notices)}")
    print(f"  With case #: {len(with_case)}")
    print(f"  With debtor name: {len(with_debtor)}")
    print(f"  With address: {len(with_address)}")
    print(f"  With county: {len(with_county)}")
    print(f"\nCounty breakdown:")
    counties = Counter(n.get('county', 'Unknown') for n in all_notices)
    for county, count in counties.most_common(30):
        print(f"  {county}: {count}")
    print(f"\nSaved to {OUTPUT_FILE}")
    print(f"{'='*60}")

    # Clean up checkpoint
    if os.path.exists(CHECKPOINT_FILE):
        os.remove(CHECKPOINT_FILE)

    return all_notices


if __name__ == '__main__':
    asyncio.run(scrape_all())
