# TODO - REMAINING WORK

## 🎯 IN PROGRESS (Background)

### Main Test Running
**Process:** proc_00513f45c240  
**Status:** Testing all 292 scrapers  
**Progress:** Will resume from scratch, deduplicates automatically  
**ETA:** ~1-2 hours for full completion  
**Expected:** ~86 more working scrapers, 525K+ total listings

---

## 🔧 FIXES NEEDED

### 1. NC eCourts (52K rows) - FOR CLAUDE ON VM
**Script ready:** `scripts/investigate_nc_ecourts_category_VM.py`  
**Issue:** Category filter doesn't persist across per-county searches  
**Action:** Claude runs on VM with Gemini keys, fixes category selection logic  
**Impact:** 52,000 estate rows

### 2. Timeout Scrapers (26 total)
**Issue:** 90s timeout too short for slow multi-county scanners  
**Action:** Retest with 300s timeout  
**Known working from retest:**
- NC Tax Lien Ads: 12,910 listings (confirmed)
- NC ITS Public Tax: 616+ listings (Person county, still running)

**High-value timeouts to retry:**
- ArcgisDistressLayers (multi-layer harvester)
- MultiYearDelinquency  
- LiensNCIncrementalScraper
- NODDiscovery
- NCPtsCloudDelinquentTax
- NCRodSubstituteTrustee
- And 20 more...

### 3. Error Scrapers (2 total)
**Henderson Foreclosure Parcels:**
- Error: ArcGIS 403 Forbidden
- Fix: Add authentication or switch to StealthyFetcher

**Lexington Probate (32K rows):**
- Error: reCAPTCHA audio element won't render on VM
- Fix: Debug audio solver, try different browser config

### 4. Greenville Probate  
**Status:** Partially fixed (delays increased)  
**Issue:** Still getting some Imperva 403s  
**Action:** Monitor success rate, may need StealthyFetcher if continues

---

## 📋 MISSING SCRAPERS TO BUILD

### High-Value (from spreadsheet)

**Tyler Probate (172 counties, 52K rows):**
- NC counties via Tyler Tech portal
- May already work via NCTylerTechEstatesScraper (returned 0, needs investigation)

**Charleston SC ROD:**
- Deeds, liens, foreclosures
- Large county, high volume

**Wake County NC ROD:**
- Tyler platform  
- Deeds and liens

**HUD USPS (628K rows):**
- User CSV download
- Not a scraper - data import task

**ncnotices.com (117K rows):**
- Legal notice aggregator  
- Crawl or scrape site

### Tax Portals Not Yet Covered
- Multiple NC counties without tax scrapers
- SC counties missing delinquent tax
- Sheriff sales for remaining counties

---

## 🧪 TESTING IMPROVEMENTS

### Increase Timeouts for Slow Scrapers
- Change default from 90s → 180s
- Special cases: 300s for multi-county scanners
- Prevents false negatives

### Parallel Testing Optimization
- Current: 5 scrapers per batch
- Could increase to 10 for faster scrapers
- Keep at 3 for slow ones

### Error Categorization
- Distinguish: Real errors vs timeouts vs empty results
- Empty results (0 listings) might be valid
- Track "no data available" vs "scraper broken"

---

## 🚀 NEXT MILESTONES

### Milestone 1: Complete Main Test
**Status:** Running now  
**Goal:** Test all 292 scrapers  
**Expected:** ~155 working, 525K listings  
**ETA:** 1-2 hours

### Milestone 2: Retest Timeouts
**Status:** Ready (script exists)  
**Goal:** Rescue 26 timeout scrapers with 300s limit  
**Expected:** 10-15 more working, 20K+ listings  
**ETA:** 30 minutes

### Milestone 3: Fix NC eCourts (Claude)
**Status:** Script ready for VM  
**Goal:** Unlock 52K estate rows  
**Expected:** 220 immediate listings, 52K on board import  
**ETA:** 1 hour (Claude)

### Milestone 4: Build Missing Scrapers
**Status:** Need to identify gaps  
**Goal:** Tyler probate (172 counties), Charleston/Wake ROD  
**Expected:** 50K+ listings  
**ETA:** 2-4 hours

### Milestone 5: Import HUD/ncnotices Data
**Status:** Not started  
**Goal:** Add 745K rows from external sources  
**Expected:** 745K listings  
**ETA:** 1 hour (import scripts)

---

## 📊 PROJECTION TO 1M+ LISTINGS

| Source | Current | After Fixes | After Build | Total |
|--------|---------|-------------|-------------|-------|
| Main test complete | 233K | 525K | 525K | 525K |
| Timeout retests | 0 | 20K | 20K | 20K |
| NC eCourts | 0 | 52K | 52K | 52K |
| Missing scrapers | 0 | 0 | 50K | 50K |
| HUD + ncnotices | 0 | 0 | 745K | 745K |
| **TOTAL** | **233K** | **597K** | **1.39M** | **1.39M** |

---

## ⚡ QUICK WINS

### Can Do Right Now (< 30 min each)
1. ✅ Retest timeouts with 300s - script ready
2. ✅ Check if NC Tax Lien Ads in main results (12,910 listings)
3. ✅ Increase default timeout in main test to 180s
4. ✅ Fix Henderson Foreclosure Parcels ArcGIS auth

### Can Do Next Session (1-2 hours each)
1. Build Charleston SC ROD scraper
2. Build Wake County ROD scraper  
3. Investigate Tyler probate (why 0 results?)
4. Import HUD CSV data
5. Build ncnotices.com scraper

### Needs Claude (VM work)
1. NC eCourts investigation + fix (52K rows)
2. Lexington Probate reCAPTCHA audio debug
3. Gaston ROD enrichment verify (Claude already fixed)

---

## 🎯 THE PATH TO COMPLETION

### Phase 1: Finish Testing (TODAY)
- Main test completes: ~525K listings
- Retest timeouts: +20K listings  
- **Subtotal: 545K listings**

### Phase 2: Fix Known Issues (TONIGHT/TOMORROW)
- NC eCourts: +52K  
- Henderson Foreclosure: +unknown
- Lexington Probate: +32K potential
- **Subtotal: 629K+ listings**

### Phase 3: Build Missing Scrapers (THIS WEEK)
- Tyler probate 172 counties: +52K
- Charleston/Wake ROD: +20K
- Remaining gaps: +30K
- **Subtotal: 731K+ listings**

### Phase 4: Import External Data (THIS WEEK)
- HUD USPS: +628K
- ncnotices.com: +117K
- **GRAND TOTAL: 1.47M+ listings**

---

## ✅ WHAT'S WORKING NOW

**69 scrapers producing 233K listings:**
- Environmental: 57K (State + EPA)
- Vacant properties: 47K (Gaston + Lincoln + Transylvania)
- Tax relief: 32K (Lexington homestead + Buncombe elderly)
- Distress indicators: 39K (Greenville hard distress)
- Delinquent tax: 45K (20+ counties)
- Tax sales: 10K (15+ counties)
- Code violations: 1K (multiple cities)
- Disaster damage: 1.5K (wildfire + Helene)
- Open data: 3K (Charlotte + Raleigh)

**Main test running:** Will add ~86 more scrapers, 292K more listings

**NO STOPPING. KEEP GOING UNTIL EVERYTHING WORKS.**
