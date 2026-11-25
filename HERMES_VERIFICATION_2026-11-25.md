# HERMES INDEPENDENT VERIFICATION - 2026-11-25

## Quick Wins - Sources That Actually Work

### ✅ CONFIRMED WORKING (Claude said working, I verified):

1. **ncnotices.com** (~101K rows)
   - STATUS: WORKING
   - Evidence: Fetching detail pages successfully (200 status)
   - Just slow (each county takes time)
   - NO CAPTCHA

2. **SC DOR Tax Lien Registry** (~14K rows potential)
   - URL: https://mydorway.dor.sc.gov/?link=LienRegistry
   - STATUS: LIVE, FREE, NO CAPTCHA
   - Search modes: Lien ID, Individual name, Business name
   - Date range filtering
   - Active/Satisfied checkboxes
   - **ACTION NEEDED: Build new scraper for this source**

### ✅ NEWLY DISCOVERED - Brief Was WRONG:

3. **Wake County NC ROD** (~26K rows)
   - URL: https://rodrecords.wake.gov/web/
   - STATUS: **FULLY ACCESSIBLE, NO CAPTCHA**
   - Brief claimed "completely unreachable" - **FALSE**
   - Loads fine, Tyler Self-Service platform
   - Search interface:
     - Book/Page
     - Recording date range  
     - Grantor/Grantee name search
     - Document type
     - Legal description
   - Indexes from July 2, 1785 through Nov 24, 2026
   - **ACTION NEEDED: Build scraper (might already exist, needs testing)**

## Anti-Bot Walls (Confirmed Blocked on Mac)

### ❌ York County SC Tax (~406K rows)
- Hard Cloudflare block
- Alternative GIS portal empty/loading issue
- **NEED VM TEST**

### ❌ Charleston County SC ROD (~27K rows)
- reCAPTCHA Enterprise v3 (brief correct)
- My Claude vision solver might work on VM
- **NEED VM TEST with better fingerprint**

## Sources to Investigate Next

### High Priority (From Brief):

1. **Franklin County NC CCS** - Bug fixed but times out
   - Test with pacing/delays
   - Might just be slow server

2. **NC OneMap** - Statewide parcels, all 100 counties, free
   - https://beaconcarolinas.com/data-sources
   - https://www.arcgis.com/home/search.html

3. **HUD USPS ZIP crosswalk** - Free alternative to restricted vacancy
   - https://www.huduser.gov/portal/datasets/usps.html
   - https://marketplace.databricks.com/details/73fac669-4c80-4097-b17d-b19eef80cdc8/Rearc_USPS-Zip-Code-Crosswalk-HUD

4. **Wake County open data portal**
   - https://data-wake.opendata.arcgis.com/
   - Alternative/supplement to ROD search

5. **SC Probate multi-county portal**
   - https://www.southcarolinaprobate.net/search/
   - Charleston, Chester, Dorchester confirmed
   - Check which other counties are on it

## Research Claims to Re-Verify

### Need Independent Testing:

- Florence & Dorchester SC deed portals - legal description as text?
- Lincoln County NC - claimed "alternative" was wrong per Claude
- Caldwell County NC - multiple systems, need clarity
- CCS various instances - some fixed, some still broken

## Summary

**3 QUICK WINS FOUND:**
1. ncnotices.com - working (brief correct)
2. SC DOR Tax Liens - new source to build
3. **Wake County ROD - brief was WRONG, it's fully accessible!**

**Total immediate opportunity: ~141K rows + whatever Wake actually has**

**Next Steps:**
1. Build SC DOR Tax Lien scraper
2. Test/build Wake County ROD scraper  
3. Investigate NC OneMap statewide data
4. Test Franklin County CCS with delays
5. VM testing for anti-bot sources
