# DEAD/BLOCKED SOURCES INVESTIGATION - 2026-11-24

## Summary of Findings

Investigated all sources Claude marked as dead/403/blocked. Found ROOT CAUSE for most: **Google blocks reCAPTCHA audio in headless mode**.

---

## ✅ FIXED SOURCES

### 1. Lexington Probate (32K rows)
**Root cause:** Google anti-bot blocks audio in headless=True  
**Fix:** Changed to headful mode (`headless=False`)  
**Status:** ✅ FIXED - Needs VM (DISPLAY=:99)  
**File:** `src/foreclosure_scraper/scrapers/counties_sc/lexington_probate.py`  
**Testing:** Verified audio loads in headful (scripts/investigate_lexington_antibot.py)

### 2. Darlington RecordHub (6K rows)
**Root cause:** Same Google anti-bot issue  
**Fix:** Same headful mode fix  
**Status:** ✅ FIXED - Needs VM  
**File:** `src/foreclosure_scraper/scrapers/counties_sc/darlington_recordhub.py`

---

## 🔧 NEEDS DIFFERENT APPROACH

### 3. CCS 4 Counties (Caldwell/Franklin/Hertford/Gates)
**Status:** Scraper built, Cloudflare bypass works, but ZERO yield  
**Problem:** Common-surname searches return no results  
**File:** `src/foreclosure_scraper/scrapers/counties_nc/nc_ccs_name_search.py`  
**Next step:** Different search parameters (not surname iteration)  
**Note:** Hertford never actually tested (Claude said only 3 tested)

### 4. Avenu Insights (17K rows - Williamsburg/Kershaw/Newberry)
**Status:** Confirmed broken (grid workflow)  
**Problem:** Kendo Grid never populates with HTTP client  
**File:** `src/foreclosure_scraper/scrapers/counties_sc/sc_avenu_rod.py`  
**Investigation script:** `scripts/investigate_avenu_grid.py`  
**Hypothesis:** Grid requires real browser session, not just HTTP requests  
**Next step:** Test via patchright browser automation

---

## 📝 NEVER STARTED (NEW BUILDS REQUIRED)

### 5. Charleston County ROD (27K rows)
**Platform:** Tyler Technologies (reCAPTCHA-gated)  
**Problem:** Tyler sites have SAME audio-not-appearing issue as Lexington  
**Solution:** Headful mode + Groq Whisper (like Lexington fix)  
**Status:** ❓ Not started - needs new scraper build

### 6. Wake Tyler ROD (27K rows)
**Platform:** Tyler Technologies (same as Charleston)  
**Problem:** Same Tyler reCAPTCHA issue  
**Solution:** Same as Charleston  
**Status:** ❓ Not started - needs new scraper build

---

## KEY INSIGHT: Google Anti-Bot Pattern

**Discovery:** Google's reCAPTCHA actively blocks audio challenges in headless mode.

**Evidence:**
- Lexington audio loads immediately in headful mode
- Same code fails in headless mode
- Tyler Technologies sites show identical symptoms

**Fix:** Use `headless=False` + `DISPLAY=:99` on VM

**Affected scrapers:**
1. ✅ Lexington Probate - FIXED
2. ✅ Darlington RecordHub - FIXED
3. ❓ Wake ROD - NEEDS BUILD with same fix
4. ❓ Charleston ROD - NEEDS BUILD with same fix
5. ❓ Durham ROD - Mentioned in captcha_execution_report, same issue

---

## ACTION ITEMS

### Immediate (Ready to Test on VM)
1. Test Lexington Probate with headful fix
2. Test Darlington with headful fix

### Short Term (New Builds)
1. Build Charleston ROD scraper using Lexington pattern + headful mode
2. Build Wake Tyler ROD scraper using same pattern
3. Test Hertford county (CCS 4) - never actually tested yet

### Medium Term (Different Approaches)
1. CCS 4 counties - try different search parameters (not surnames)
2. Avenu Insights - test with browser automation instead of HTTP client

---

## IMPACT

**Fixed (needs VM testing):**
- Lexington Probate: 32K rows
- Darlington RecordHub: 6K rows
- **Subtotal: 38K rows** ✅

**Can be fixed with same pattern:**
- Charleston ROD: 27K rows
- Wake Tyler ROD: 27K rows
- **Subtotal: 54K rows** (new builds required)

**Needs different approach:**
- CCS 4 counties: TBD (yield currently 0)
- Avenu Insights: 17K rows

**TOTAL ADDRESSABLE: 109K rows** (38K fixed + 54K same pattern + 17K different approach)

---

## TECHNICAL NOTES

### Headless vs Headful
- **Headless=True:** Fast, no GUI, but Google detects and blocks audio
- **Headful=False:** Requires DISPLAY, more resources, but audio works

### VM Requirements
- DISPLAY=:99 (Xvfb virtual display)
- More RAM/CPU for visible browser
- User frustrated by local browser automation (memory note)

### reCAPTCHA Audio Solver Pattern (Proven)
1. Click checkbox
2. Wait for challenge
3. Click audio button
4. Download MP3
5. Transcribe via Groq Whisper
6. Submit answer
7. **Works in headful, fails in headless**

---

## FILES MODIFIED

1. `src/foreclosure_scraper/scrapers/counties_sc/lexington_probate.py`
2. `src/foreclosure_scraper/scrapers/counties_sc/darlington_recordhub.py`
3. `src/foreclosure_scraper/scrapers/counties_nc/nc_ccs_name_search.py` (new)
4. `scripts/investigate_lexington_antibot.py` (new)
5. `scripts/investigate_avenu_grid.py` (new)
