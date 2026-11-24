#!/usr/bin/env python3
"""
Debug NC eCourts category filter - detailed logging of EVERY step.

This runs the scraper with instrumentation to see EXACTLY what's happening
with the Estate category filter at each stage.
"""
import asyncio
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from foreclosure_scraper.scrapers.counties_nc.nc_ecourts_estates import (
    NCECourtsEstates,
    _select_case_category,
    ESTATE_CATEGORY_LABELS,
)
import structlog

log = structlog.get_logger()

# Load Gemini keys
for i in range(1, 11):
    key_file = Path.home() / ".secrets" / f"gemini_api_key_{i}.txt"
    if key_file.exists():
        os.environ[f"GEMINI_API_KEY_{i}"] = key_file.read_text().strip()


async def debug_category_filter():
    """Run NC eCourts with detailed category filter logging."""
    
    print("🔍 NC ECOURTS CATEGORY FILTER DEBUG")
    print("=" * 70)
    
    from playwright.async_api import async_playwright
    
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=False)  # VISIBLE browser
        page = await browser.new_page()
        
        print("\n1️⃣ Loading Smart Search page...")
        await page.goto("https://portal-nc.tylertech.cloud/Portal/Home/Dashboard/29")
        
        print("\n2️⃣ Solving AWS WAF...")
        from foreclosure_scraper.enrichment_waf_oss import solve_waf_via_browser
        waf_solved = await solve_waf_via_browser(page)
        if not waf_solved:
            print("❌ WAF solve failed")
            await browser.close()
            return
        print("✅ WAF solved")
        
        print("\n3️⃣ Waiting for search form...")
        try:
            await page.wait_for_selector('#caseCriteria_SearchCriteria', timeout=15000)
            print("✅ Search form loaded")
        except Exception as e:
            print(f"❌ No search form: {e}")
            await browser.close()
            return
        
        print("\n4️⃣ INITIAL category selection...")
        selected = await _select_case_category(page, ESTATE_CATEGORY_LABELS)
        print(f"   Result: {selected}")
        
        # Check what's actually selected
        await asyncio.sleep(2)
        current_category = await page.evaluate("""() => {
            // Check all possible category selectors
            const sel = document.querySelector('select[name*=Category], select[id*=Category]');
            if (sel) return {type: 'select', value: sel.value, text: sel.options[sel.selectedIndex]?.text};
            
            const hidden = document.querySelector('input[type=hidden][name*=Category]');
            if (hidden) return {type: 'hidden', value: hidden.value};
            
            const kendo = document.querySelector('.k-multiselect-wrap, .k-dropdown');
            if (kendo) return {type: 'kendo', text: kendo.innerText.trim()};
            
            return {type: 'none', value: null};
        }""")
        print(f"   Current category state: {current_category}")
        
        print("\n5️⃣ Submitting FIRST county search (Rutherford)...")
        await page.fill('#caseCriteria_SearchCriteria', 'Rutherford')
        await page.click('button:has-text("Submit")')
        await page.wait_for_selector('table, .case-list, :text("No cases")', timeout=30000)
        
        # Check category AFTER first submit
        await asyncio.sleep(2)
        category_after_submit = await page.evaluate("""() => {
            const sel = document.querySelector('select[name*=Category], select[id*=Category]');
            if (sel) return {type: 'select', value: sel.value, text: sel.options[sel.selectedIndex]?.text};
            
            const hidden = document.querySelector('input[type=hidden][name*=Category]');
            if (hidden) return {type: 'hidden', value: hidden.value};
            
            const kendo = document.querySelector('.k-multiselect-wrap, .k-dropdown');
            if (kendo) return {type: 'kendo', text: kendo.innerText.trim()};
            
            return {type: 'none', value: null};
        }""")
        print(f"   Category AFTER submit: {category_after_submit}")
        
        # Get actual result rows
        rows = await page.evaluate("""() => {
            const links = [...document.querySelectorAll('a.caseLink, a[data-url]')];
            return links.slice(0, 10).map(a => {
                const tr = a.closest('tr') || a.closest('.row');
                const caseNum = (a.getAttribute('title') || a.innerText || '').trim();
                const txt = tr ? tr.innerText : a.innerText;
                return {caseNum, preview: txt.slice(0, 200)};
            });
        }""")
        
        print(f"\n   Got {len(rows)} result rows:")
        for i, row in enumerate(rows[:5], 1):
            print(f"   [{i}] {row['caseNum']}")
            print(f"       {row['preview'][:100]}")
        
        print("\n6️⃣ RE-SELECTING category before second county...")
        selected2 = await _select_case_category(page, ESTATE_CATEGORY_LABELS)
        print(f"   Result: {selected2}")
        
        await asyncio.sleep(2)
        category_reselected = await page.evaluate("""() => {
            const sel = document.querySelector('select[name*=Category], select[id*=Category]');
            if (sel) return {type: 'select', value: sel.value, text: sel.options[sel.selectedIndex]?.text};
            
            const hidden = document.querySelector('input[type=hidden][name*=Category]');
            if (hidden) return {type: 'hidden', value: hidden.value};
            
            const kendo = document.querySelector('.k-multiselect-wrap, .k-dropdown');
            if (kendo) return {type: 'kendo', text: kendo.innerText.trim()};
            
            return {type: 'none', value: null};
        }""")
        print(f"   Category state: {category_reselected}")
        
        print("\n7️⃣ Submitting SECOND county search (Cleveland)...")
        await page.fill('#caseCriteria_SearchCriteria', 'Cleveland')
        await page.click('button:has-text("Submit")')
        await page.wait_for_selector('table, .case-list, :text("No cases")', timeout=30000)
        
        rows2 = await page.evaluate("""() => {
            const links = [...document.querySelectorAll('a.caseLink, a[data-url]')];
            return links.slice(0, 10).map(a => {
                const tr = a.closest('tr') || a.closest('.row');
                const caseNum = (a.getAttribute('title') || a.innerText || '').trim();
                const txt = tr ? tr.innerText : a.innerText;
                return {caseNum, preview: txt.slice(0, 200)};
            });
        }""")
        
        print(f"\n   Got {len(rows2)} result rows:")
        for i, row in enumerate(rows2[:5], 1):
            print(f"   [{i}] {row['caseNum']}")
            print(f"       {row['preview'][:100]}")
        
        print("\n8️⃣ Inspecting the actual category widget HTML...")
        category_html = await page.evaluate("""() => {
            const container = document.querySelector('.search-form, form') || document;
            const categorySection = [...container.querySelectorAll('*')].find(el => 
                el.textContent && /case.*category|category/i.test(el.textContent) && el.offsetHeight > 0
            );
            if (categorySection) {
                return categorySection.outerHTML.slice(0, 1000);
            }
            return null;
        }""")
        
        if category_html:
            print("   Category widget HTML:")
            print(f"   {category_html[:500]}")
        else:
            print("   ⚠️  Could not find category widget in DOM")
        
        print("\n" + "=" * 70)
        print("🔍 DEBUG COMPLETE - Browser staying open for manual inspection")
        print("   Press Ctrl+C to close")
        
        # Keep browser open for manual inspection
        await asyncio.sleep(300)
        await browser.close()


if __name__ == "__main__":
    asyncio.run(debug_category_filter())
