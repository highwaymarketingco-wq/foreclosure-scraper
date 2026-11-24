# MASTER PLAN - Get to 100%

Based on `Hermes_Handoff_Walled_Declined_NA_2026-11-23.xlsx` - 509 cells, 1.1M rows

## CURRENT STATUS (2026-11-12)

### ✅ WORKING NOW (36,606 rows)
1. **CountyFusion Lexington** - 6,606 rows ✅
2. **Tyler Gemini probate** - 30,000 rows ✅

### 🔧 EXISTS BUT NEEDS TESTING (500K+ rows)
These scrapers exist in the codebase but weren't in my immediate focus:

1. **Tyler probate (portal-nc.tylertech.cloud)** - 52K rows, 172 counties
   - File: `nc_tylertech_estates.py`
   - Has Gemini solver already
   - **ACTION:** Test with Gemini keys

2. **Lexington probate** - 32K rows
   - File: `lexington_probate.py`
   - Has reCAPTCHA audio solver
   - **ACTION:** Test live

3. **SC SOS Business Search** - 26K rows, 46 counties (statewide)
   - File: `sc_sos_entity.py` (class: SCSOSBusinessSearch)
   - Has reCAPTCHA solver
   - **ACTION:** Test live

4. **306 other scrapers** - Many may already cover spreadsheet items
   - **ACTION:** Cross-reference spreadsheet sources with existing scrapers

### ❌ CONFIRMED BROKEN (37K rows)
1. **Avenu (Williamsburg/Kershaw/Newberry)** - 17K rows
   - Grid workflow incomplete
   
2. **Greenville/Greenwood CountyFusion** - 14K rows  
   - Server-side search endpoint failures (ERR_ABORTED)
   
3. **Darlington RecordHub** - 6K rows
   - reCAPTCHA audio timing out (HTTP 410)

### 📊 NOT SCRAPER PROBLEMS (628K rows)
1. **HUD USPS vacancy** - 628K rows, 146 counties
   - Requires government/nonprofit registration
   - Enricher exists (`enrichment_usps_vacancy.py`)
   - Supports manual CSV ingest OR bearer token
   - **ACTION:** User needs to register at huduser.gov and download CSVs

2. **ncnotices.com legal notices** - 117K rows, 49 counties
   - Statewide NC legal notice aggregator
   - **ACTION:** Needs investigation if scraper exists

## SYSTEMATIC APPROACH TO 100%

### Phase 1: Test What Exists (est. 2-4 hours)
Run every existing scraper against spreadsheet sources:
- 306 scrapers in `src/foreclosure_scraper/scrapers/`
- Many likely already solve spreadsheet items
- Create test matrix: `scripts/test_all_from_spreadsheet.py`

### Phase 2: Build Missing Platforms (est. 8-16 hours)
Top platforms by impact that need new scrapers:

1. **Charleston County ROD** (27K rows)
   - County-built CAPTCHA site
   - Needs reCAPTCHA solver

2. **Wake Tyler ROD** (27K rows)
   - `rodrecords.wake.gov`
   - Similar to probate Tyler - adapt Gemini solver

3. **Tax portals** (41K rows total):
   - Lincoln: www.lincolncountytax.com (21K)
   - Bertie: bertie.webtaxpay.com (11K)
   - McDowell: www.bttaxpayerportal.com (10K)
   - All use reCAPTCHA - reuse existing solver pattern

4. **CCS ROD** (21K rows, 10+ counties)
   - Courthouse Computer Systems
   - Multiple instances (us5, us6, iredellnc subdomains)
   - reCAPTCHA - build one template, instantiate per county

5. **Brunswick Inttek** (9K rows)
   - Internet Technologies Inc "Recording-Pro"
   - brunswick-live.inttek.net
   - reCAPTCHA

### Phase 3: Fix Broken Ones (37K rows)
1. **Avenu** - Find actual grid trigger sequence
2. **Greenville/Greenwood** - Browser automation full workflow OR wait for county IT
3. **Darlington** - Retry on VM different IP OR use Gemini for image CAPTCHA

### Phase 4: Data Downloads (628K rows)
1. **HUD USPS** - User registers, downloads CSV, places in `data/`

## TEMPLATES TO BUILD

### 1. Generic reCAPTCHA V2 Tax Portal
```python
class GenericTaxPortal(BaseScraper):
    \"\"\"Template for NC/SC tax portals with reCAPTCHA V2\"\"\"
    # Uses existing enrichment_recaptcha_audio.py solver
    # Instantiate with URL + selectors
```

### 2. Generic CCS ROD
```python  
class GenericCCSROD(BaseScraper):
    \"\"\"Template for Courthouse Computer Systems ROD sites\"\"\"
    # us5.courthousecomputersystems.com/County
    # us6.courthousecomputersystems.com/County
    # iredellnc.courthousecomputersystems.com
```

### 3. Tyler ROD (adapt from Tyler probate)
```python
class TylerROD(BaseScraper):
    \"\"\"Adapt Tyler probate Gemini solver for ROD searches\"\"\"
    # rodrecords.wake.gov same AWS WAF as estates
```

## SUCCESS METRICS

| Category | Cells | Rows | Status |
|----------|-------|------|--------|
| **Working now** | ~10 | 37K | ✅ |
| **Exists, needs test** | ~220 | 110K | 🔧 |
| **Need to build** | ~80 | 125K | ❌ |
| **Data download** | 146 | 628K | 📋 |
| **Legal notices** | 49 | 117K | ❓ |
| **Broken (fix)** | ~4 | 37K | 🔧 |
| **TOTAL** | 509 | 1.1M | - |

## NEXT STEPS

1. ✅ **Hermes:** Test the 3 known-good scrapers (Tyler probate, Lexington probate, SC SOS)
2. ✅ **Hermes:** Build test harness that runs all 306 scrapers against spreadsheet
3. ✅ **Hermes:** Build top 5 missing platforms (Charleston, Wake, Tax portals, CCS, Inttek)
4. 📋 **User:** Register for HUD USPS, download NC/SC CSVs
5. 🤝 **Claude:** Fix Avenu/Greenville/Greenwood/Darlington on VM

---

**Bottom line:** We likely already have 30-40% of the spreadsheet working via existing scrapers. Need systematic testing + 5-10 new platform templates to hit 80%. Final 20% is data downloads + broken edge cases.
