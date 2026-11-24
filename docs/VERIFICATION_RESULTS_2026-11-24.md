# VERIFICATION RESULTS - 2026-11-24 Evening

## WHAT I DID

Stopped analyzing. Started **actually testing and fixing** scrapers.

## TOP 8 SCRAPERS TESTED

Based on your 1.1M row spreadsheet, tested the highest-impact sources:

| Scraper | Rows | Status | Issue | Fix |
|---------|------|--------|-------|-----|
| **Orangeburg ROD** | 3K | ✅ **WORKS** | None | **109 listings confirmed** |
| CountyFusion Lexington | 6K | ⚠️ Testing | AWS WAF 20-puzzle limit | Increased to 50, retesting now |
| NC eCourts Estates | 52K | ❌ Failed | AWS WAF 20-puzzle limit | Increased to 50, needs retest |
| Lexington Probate | 32K | ❌ Failed | reCAPTCHA audio not loading | Needs investigation |
| SC SOS | 26K | ⚠️ Empty | Returned 0 (date range?) | Needs investigation |
| CCS Deeds | 21K | ❌ Failed | Cloudflare 403 hard block | Needs browser automation |
| Darlington | 6K | ⚠️ Empty | Returned 0 after successful login | Date range issue |
| Avenu | 17K | ❌ Failed | Wrong class name in test | Needs proper test |

## FIXES APPLIED

### 1. AWS WAF Max Puzzles (71104e0)
**Problem:** CountyFusion and NC eCourts hit 20-puzzle limit  
**Solution:** Increased `MAX_PUZZLES` from 20 → 50  
**Added:** `WAF_MAX_PUZZLES` env override  
**Impact:** Should unblock 58K rows (6K CountyFusion + 52K NC eCourts)  
**Status:** CountyFusion retesting now with fix

## CONFIRMED WORKING

✅ **Orangeburg SC ROD:** 109 listings  
- Federal liens + mechanic liens
- No CAPTCHA issues
- Real data flowing

## NEXT PRIORITIES

### High Impact (100K+ rows)
1. **Fix NC eCourts (52K rows)**  
   - Retest with 50-puzzle limit
   - If still failing, investigate WAF behavior

2. **Fix Lexington Probate (32K rows)**  
   - reCAPTCHA audio button timing issue
   - Similar to Darlington problem from earlier

3. **Fix SC SOS (26K rows)**  
   - Code runs, returns 0
   - Likely date range configuration

### Medium Impact (20K rows)
4. **Fix CCS Deeds (21K rows)**  
   - Cloudflare 403 blocking curl_cffi
   - Needs full browser automation (nodriver/patchright)

### Lower Priority (10K-20K rows)
5. **Fix Darlington (6K rows)** - reCAPTCHA solves, login works, 0 listings  
6. **Fix Avenu (17K rows)** - HTTP-only code, needs browser for Kendo Grid

## THE TRUTH

Out of 8 top scrapers tested:
- **1 confirmed working** (Orangeburg)
- **1 likely fixed, retesting** (CountyFusion)
- **6 broken or empty**

**Success rate so far: 12.5% confirmed, potentially 25% after current retest**

This is the honest baseline. Most scrapers need:
1. AWS WAF tuning (done)
2. reCAPTCHA timing fixes
3. Browser automation for hard-walled sites
4. Date range configuration

---

**Current test running:** CountyFusion Lexington with 50-puzzle fix  
**GitHub:** Commit 71104e0 pushed
