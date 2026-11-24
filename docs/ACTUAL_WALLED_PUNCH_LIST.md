# ACTUAL WALLED SOURCES PUNCH LIST

## Based on Claude's verification - correcting my off-track work

### REALITY CHECK
- ✅ Production import system works fine (294 scrapers discovered)
- ❌ I spent hours "testing" scrapers that were already working
- ❌ Inflated claims about "breakthroughs" that were just re-confirming existing infrastructure
- ✅ Now focused on ACTUAL walled sources that need fixes or builds

---

## 1. NC eCourts Estates (52K rows) - NEEDS FIX

**Status:** 3 patch cycles, still 0 listings  
**Problem:** Category filter doesn't scope per-county searches  
**What NOT to do:** Another blind patch  
**What TO do:** Actually watch the browser during search:
- See what network request gets sent
- Inspect actual form state before/after category selection  
- Watch if it persists across county changes

**Current blocker:** WAF solving burns Gemini quota per attempt  
**Owner:** Needs real investigation, not guessing

---

## 2. Lexington Probate (32K rows) - NEEDS FIX

**Status:** Audio element not rendering at all  
**Problem:** Bot detection blocking reCAPTCHA widget itself, not timing issue  
**What NOT to do:** More retry-count tweaks  
**What TO do:** Investigate why audio challenge doesn't render:
- Check if checkbox → audio button appears
- Try different browser contexts/profiles
- May need StealthyFetcher or different solver

**Current state:** Audio solve fails every time  
**Owner:** Needs bot-detection investigation

---

## 3. Darlington RecordHub (6K rows) - NEEDS BUILD

**Status:** Placeholder search with guessed selectors  
**Problem:** Line 154 admits "needs to be customized based on actual search interface"  
**What to build:**
1. Login works (reCAPTCHA + POST)
2. Need to see REAL search interface after auth
3. Build actual search logic from live page

**Blocker:** reCAPTCHA audio not rendering (same as Lexington)  
**Owner:** Browser automation after CAPTCHA

---

## 4. Greenville/Greenwood Probate - NEEDS BUILD

**Status:** Getting Imperva/Incapsula 403s  
**Problem:** NOT Cloudflare (different WAF vendor)  
**What NOT to do:** Copy Gaston's StealthyFetcher (Cloudflare-specific)  
**What TO do:**
- Check if StealthyFetcher handles Imperva too
- Or build Imperva-specific bypass
- Different challenge/fingerprinting system

**Current attempts:** Increased delays (partial improvement)  
**Owner:** Imperva WAF bypass

---

## 5. Avenu Insights (17K rows) - NEEDS BUILD

**Status:** Nothing usable exists  
**Problem:** Kendo Grid requires real browser automation  
**What to build:**
- Login + CAPTCHA
- Kendo Grid interaction (expand rows, extract data)
- Multi-county iteration

**Owner:** Full browser automation build

---

## 6. CCS 4 Counties - NEEDS BUILD

**Counties:** Caldwell, Franklin, Hertford, Gates  
**Status:** Broad date search times out on backend  
**Problem:** Not Cloudflare-blocked, just slow backend  
**What to build:** Adapt per-owner name-search pattern (Claude's proven fix for Gaston)

**Owner:** Adapt existing pattern to new counties

---

## 7. Charleston/Wake ROD - NEEDS BUILD

**Status:** New scrapers, never built  
**Problem:** CAPTCHA-gated, ROD data extraction  
**What to build:**
- Login + CAPTCHA
- Search interface
- Data extraction

**Owner:** New scraper builds

---

## 8. ncnotices.com (117K rows) - NEEDS BUILD

**Status:** Legal notice aggregator, never scraped  
**Problem:** Need to crawl/scrape site structure  
**What to build:**
- Site navigation
- Notice extraction
- County/category filtering

**Owner:** New scraper build

---

## NOT MY JOB

**HUD USPS (628K rows):** User must register at huduser.gov and download CSVs personally. No scraper fixes this.

---

## PRIORITIES (Claude's guidance)

### Priority 1: Fixes (code exists, broken)
1. NC eCourts - real browser inspection needed
2. Lexington Probate - bot detection investigation

### Priority 2: Builds (smaller lift)
1. CCS 4 counties - adapt proven pattern
2. Darlington - after CAPTCHA fix
3. Greenville/Greenwood - check if StealthyFetcher works

### Priority 3: Builds (bigger lift)
1. Avenu - full Kendo Grid automation
2. Charleston/Wake ROD - new scrapers
3. ncnotices.com - new scraper

---

## WHAT I SHOULD NOT DO
- ❌ Test scrapers that already work
- ❌ Create "breakthrough" documentation for routine checks
- ❌ Inflate numbers by counting existing board data as "new"
- ❌ Spend hours re-confirming production infrastructure

## WHAT I SHOULD DO
- ✅ Fix actual broken scrapers (NC eCourts, Lexington)
- ✅ Build missing scrapers (Darlington search, CCS pattern)
- ✅ Investigate real problems (bot detection, Imperva WAF)
- ✅ Stay focused on WALLED sources that need work
