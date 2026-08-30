#!/usr/bin/env python3
"""Test TruePeopleSearch with stealth browser."""
import asyncio
import re
import sys
sys.path.insert(0, 'src')
sys.path.insert(0, '.venv/lib/python3.12/site-packages')

from foreclosure_scraper.render import fetch_rendered

async def test():
    url = 'https://www.truepeoplesearch.com/results?name=John+Smith&city=Spartanburg&state=SC'
    html = await fetch_rendered(url)
    if html:
        print(f'HTML length: {len(html)}')
        phones = re.findall(r'\(?\d{3}\)?[-.\s]\d{3}[-.\s]\d{4}', html)
        print(f'Phone patterns: {phones[:10]}')
        if 'Too many' in html:
            print('Still too many results')
        # Look for detail links
        links = re.findall(r'href="(/details[^"]+)"', html)
        print(f'Detail links: {len(links)}')
        for l in links[:5]:
            print(f'  {l}')
    else:
        print('No HTML returned')

asyncio.run(test())
