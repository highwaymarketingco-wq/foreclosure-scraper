#!/usr/bin/env python3
"""Debug reCAPTCHA on Lincoln county tax site."""
import asyncio
import re
from playwright.async_api import async_playwright

async def main():
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True, args=["--no-sandbox", "--disable-gpu"])
        page = await browser.new_page()
        
        url = "https://www.lincolncountytax.com/List/Delinquent"
        print(f"Navigating to {url}")
        await page.goto(url, timeout=30000)
        await page.wait_for_load_state("networkidle", timeout=15000)
        
        print(f"Page URL: {page.url}")
        print(f"Page title: {await page.title()}")
        
        # List all iframes
        frames = page.frames
        for f in frames:
            print(f"Frame: url={f.url[:200]} name={f.name}")
        
        # Get page content
        html = await page.content()
        print(f"Page length: {len(html)}")
        
        # Find recaptcha-related elements
        for m in re.finditer(r'<iframe[^>]*>', html, re.I):
            tag = m.group()
            if 'recaptcha' in tag.lower() or 'captcha' in tag.lower() or 'google' in tag.lower():
                print(f"CAPTCHA iframe: {tag[:300]}")
        
        for m in re.finditer(r'class="[^"]*(?:recaptcha|captcha|g-recaptcha)[^"]*"', html, re.I):
            print(f"CAPTCHA class: {m.group()[:200]}")
        
        for m in re.finditer(r'data-sitekey="([^"]+)"', html):
            print(f"sitekey: {m.group(1)}")
        
        # Check for Turnstile
        if 'turnstile' in html.lower() or 'cf-turnstile' in html.lower():
            print("Turnstile detected!")
        
        # Print first 2000 chars of body text
        body_text = await page.inner_text("body")
        print(f"\nBody text (first 1000):\n{body_text[:1000]}")
        
        await browser.close()

asyncio.run(main())
