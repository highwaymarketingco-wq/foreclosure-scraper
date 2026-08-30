#!/usr/bin/env python3
"""Test SC court case detail pages for phone numbers."""
import asyncio
import re
import sys
sys.path.insert(0, 'src')
sys.path.insert(0, '.venv/lib/python3.12/site-packages')

from foreclosure_scraper.render import fetch_rendered

async def main():
    url = 'https://publicindex.sccourts.org/Spartanburg/PublicIndex/CaseDetails.aspx?CaseNum=2026-CP-42-03548'
    print(f"Fetching: {url}")
    html = await fetch_rendered(url)
    print(f"HTML length: {len(html) if html else 0}")

    if html:
        phones = re.findall(r'\(?\d{3}\)?[-.\s]\d{3}[-.\s]\d{4}', html)
        print(f"Phones found: {phones[:10]}")
        
        emails = re.findall(r'[\w.+-]+@[\w-]+\.[\w.-]+', html)
        print(f"Emails found: {emails[:10]}")
        
        for kw in ['Attorney', 'Counsel', 'Defendant', 'Plaintiff', 'Phone', 'Contact']:
            idx = html.find(kw)
            if idx >= 0:
                snippet = html[idx:idx+300].replace('\n', ' ').replace('\r', '')
                print(f"\n{kw}: {snippet[:250]}")
    else:
        print("fetch_rendered returned None/empty")

asyncio.run(main())
