#!/usr/bin/env python3
"""Debug what's actually in the 3085-char Polk form page."""
import asyncio
import sys
import os
import re

sys.path.insert(0, "src")
os.environ["DISPLAY"] = ":99"

from foreclosure_scraper.browser_utils import start_browser

SEARCH_URL = "https://cms.revize.com/revize/apps/polkcounty/searchtaxrecord.php"


async def test():
    browser = await start_browser(headless=False)
    page = await browser.get(SEARCH_URL)
    await asyncio.sleep(10)
    content = await page.get_content()
    print(f"Page length: {len(content)}", flush=True)

    # Check for script tags
    scripts = re.findall(r'<script[^>]*src=["\']([^"\']*)["\']', content, re.I)
    print(f"\nScript srcs: {len(scripts)}", flush=True)
    for s in scripts:
        print(f"  {s}", flush=True)

    # Check for inline scripts
    inline = re.findall(r'<script[^>]*>(.*?)</script>', content, re.I | re.S)
    print(f"\nInline scripts: {len(inline)}", flush=True)
    for i, s in enumerate(inline):
        print(f"  [{i}] {s[:200]}", flush=True)

    # Check form tags
    forms = re.findall(r'<form[^>]*>', content, re.I)
    print(f"\nForm tags: {len(forms)}", flush=True)
    for f in forms:
        print(f"  {f}", flush=True)

    # Check for ANY link/style tags
    links = re.findall(r'<link[^>]*>', content, re.I)
    print(f"\nLink tags: {len(links)}", flush=True)
    for l in links:
        print(f"  {l}", flush=True)

    # Print full content
    print("\n=== FULL CONTENT ===", flush=True)
    print(content, flush=True)

    try:
        browser.stop()
    except BaseException:
        pass


asyncio.run(test())
