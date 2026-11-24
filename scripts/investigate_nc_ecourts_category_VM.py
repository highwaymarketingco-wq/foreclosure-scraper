#!/usr/bin/env python3
"""
NC eCourts category filter investigation - FOR VM USE ONLY.

This script:
1. Loads Gemini keys from .secrets/
2. Solves AWS WAF
3. Inspects category filter behavior in detail
4. Tests category persistence across multiple county searches

Run on VM where Gemini keys are properly configured.
"""
import asyncio
import os
import sys
from pathlib import Path

# Load Gemini API keys from .secrets/
secrets_dir = Path.home() / ".secrets"
for i in range(1, 11):
    key_file = secrets_dir / f"gemini_api_key_{i}.txt"
    if key_file.exists():
        key = key_file.read_text().strip()
        os.environ[f"GEMINI_API_KEY_{i}"] = key
        print(f"✅ Loaded GEMINI_API_KEY_{i}")

sys.path.insert(0, "/home/opc/foreclosure-scraper/src")

from foreclosure_scraper.scrapers.counties_nc.nc_ecourts_estates import (
    _select_case_category,
    ESTATE_CATEGORY_LABELS,
)
import structlog

log = structlog.get_logger()


async def investigate():
    """Deep investigation of category filter behavior."""
    
    print("\n" + "=" * 70)
    print("NC ECOURTS CATEGORY FILTER INVESTIGATION")
    print("=" * 70)
    
    from playwright.async_api import async_playwright
    from foreclosure_scraper.enrichment_waf_oss import solve_waf_via_browser
    
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page()
        
        print("\n1️⃣ Loading Smart Search...")
        await page.goto("https://portal-nc.tylertech.cloud/Portal/Home/Dashboard/29", timeout=60000)
        
        print("\n2️⃣ Solving AWS WAF...")
        waf_solved = await solve_waf_via_browser(page)
        if not waf_solved:
            print("❌ WAF solve failed - stopping")
            await browser.close()
            return
        print("✅ WAF solved")
        
        print("\n3️⃣ Waiting for search form...")
        await page.wait_for_selector('#caseCriteria_SearchCriteria', timeout=15000)
        print("✅ Form ready")
        
        print("\n4️⃣ Initial category selection...")
        selected = await _select_case_category(page, ESTATE_CATEGORY_LABELS)
        print(f"   Selection result: {selected}")
        
        # Check actual category state
        await asyncio.sleep(2)
        category_state = await page.evaluate("""() => {
            // Check all possible category widget types
            const result = {found: []};
            
            // Native select
            const sel = document.querySelector('select[name*=Category], select[id*=Category]');
            if (sel && sel.offsetHeight > 0) {
                result.found.push({
                    type: 'select',
                    value: sel.value,
                    text: sel.options[sel.selectedIndex]?.text || ''
                });
            }
            
            // Hidden input
            const hidden = document.querySelector('input[type=hidden][name*=Category]');
            if (hidden) {
                result.found.push({
                    type: 'hidden',
                    name: hidden.name,
                    value: hidden.value
                });
            }
            
            // Kendo widget
            const kendo = document.querySelector('.k-multiselect-wrap, .k-dropdown-wrap');
            if (kendo && kendo.offsetHeight > 0) {
                result.found.push({
                    type: 'kendo',
                    text: kendo.innerText.trim()
                });
            }
            
            return result;
        }""")
        
        print(f"   Category widgets found: {category_state['found']}")
        
        print("\n5️⃣ First county search (Rutherford)...")
        await page.fill('#caseCriteria_SearchCriteria', 'Rutherford')
        await page.click('button:has-text("Submit")', timeout=5000)
        await page.wait_for_selector('table, .case-list, :text("No cases")', timeout=30000)
        
        # Get result rows
        rows = await page.evaluate("""() => {
            const links = [...document.querySelectorAll('a.caseLink, a[data-url]')];
            return links.slice(0, 10).map(a => {
                const title = a.getAttribute('title') || a.innerText || '';
                const tr = a.closest('tr') || a.closest('.row');
                const text = tr ? tr.innerText : a.innerText;
                return {
                    caseNum: title.trim(),
                    snippet: text.slice(0, 150)
                };
            });
        }""")
        
        print(f"   Got {len(rows)} rows:")
        for i, row in enumerate(rows[:3], 1):
            print(f"   [{i}] {row['caseNum']}")
            print(f"       {row['snippet'][:100]}")
        
        # Check if category is STILL selected after submit
        await asyncio.sleep(2)
        category_after = await page.evaluate("""() => {
            const sel = document.querySelector('select[name*=Category], select[id*=Category]');
            if (sel) return {type: 'select', value: sel.value, text: sel.options[sel.selectedIndex]?.text};
            
            const hidden = document.querySelector('input[type=hidden][name*=Category]');
            if (hidden) return {type: 'hidden', value: hidden.value};
            
            const kendo = document.querySelector('.k-multiselect-wrap, .k-dropdown-wrap');
            if (kendo) return {type: 'kendo', text: kendo.innerText.trim()};
            
            return {type: 'none'};
        }""")
        
        print(f"\n   Category AFTER submit: {category_after}")
        
        print("\n6️⃣ Re-selecting category before second search...")
        selected2 = await _select_case_category(page, ESTATE_CATEGORY_LABELS)
        print(f"   Selection result: {selected2}")
        
        print("\n7️⃣ Second county search (Cleveland)...")
        await page.fill('#caseCriteria_SearchCriteria', 'Cleveland')
        await page.click('button:has-text("Submit")', timeout=5000)
        await page.wait_for_selector('table, .case-list, :text("No cases")', timeout=30000)
        
        rows2 = await page.evaluate("""() => {
            const links = [...document.querySelectorAll('a.caseLink, a[data-url]')];
            return links.slice(0, 10).map(a => ({
                caseNum: (a.getAttribute('title') || a.innerText || '').trim(),
                snippet: (a.closest('tr') || a.closest('.row') || a).innerText.slice(0, 150)
            }));
        }""")
        
        print(f"   Got {len(rows2)} rows:")
        for i, row in enumerate(rows2[:3], 1):
            print(f"   [{i}] {row['caseNum']}")
            print(f"       {row['snippet'][:100]}")
        
        print("\n8️⃣ Analyzing case number patterns...")
        all_cases = [r['caseNum'] for r in rows + rows2]
        criminal = [c for c in all_cases if any(x in c.upper() for x in ['CR', 'CRS'])]
        estate = [c for c in all_cases if any(x in c.upper() for x in ['ES', 'ESTATE', 'SP'])]
        
        print(f"   Criminal cases: {len(criminal)}")
        print(f"   Estate-like: {len(estate)}")
        print(f"   Other: {len(all_cases) - len(criminal) - len(estate)}")
        
        if criminal:
            print(f"\n   Sample criminal: {criminal[:3]}")
        if estate:
            print(f"   Sample estate: {estate[:3]}")
        
        print("\n" + "=" * 70)
        print("✅ Investigation complete")
        print("=" * 70)
        
        await browser.close()


if __name__ == "__main__":
    asyncio.run(investigate())
