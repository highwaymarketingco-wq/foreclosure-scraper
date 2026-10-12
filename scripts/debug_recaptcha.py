#!/usr/bin/env python3
"""Debug reCAPTCHA on a page."""
import asyncio
import re
from playwright.async_api import async_playwright

async def main():
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True, args=["--no-sandbox", "----disable-gpu"])
        page = await browser.new_page()
        await page.goto("https://www.avalontaxonline.com/lincolncounty", timeout=30000)
        await page.wait_for_load_state("networkidle", timeout=15000)
        
        # List all iframes
        frames = page.frames
        for f in frames:
            print(f"Frame: url={f.url} name={f.name}")
        
        # Get page content to find recaptcha
        html = await page.content()
        
        # Find recaptcha-related elements
        for m in re.finditer(r'<iframe[^>]*(?:recaptcha|captcha)[^>]*>', html, re.I):
            print(f"iframe: {m.group()[:200]}")
        for m in re.finditer(r'<div[^>]*(?:recaptcha|g-recaptcha|captcha)[^>]*>', html, re.I):
            print(f"div: {m.group()[:200]}")
        for m in re.finditer(r'class="[^"]*(?:recaptcha|captcha)[^"]*"', html, re.I):
            print(f"class: {m.group()[:200]}")
        
        # Also look for sitekey
        for m in re.finditer(r'data-sitekey="([^"]+)"', html):
            print(f"sitekey: {m.group(1)}")
        
        await browser.close()

asyncio.run(main())
