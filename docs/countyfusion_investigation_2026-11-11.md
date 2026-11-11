# CountyFusion Investigation - 2026-11-11

## Status

✅ **Lexington SC: 100 REAL listings (6,606 total rows)**  
❌ **Other 4 counties failing at login**

## Technical Finding

The original login flow works ONLY for Lexington:
1. GET `/countyweb/login.do?countyname=LexingtonSC` 
2. GET `/countyweb/loginDisplay.action?countyname=LexingtonSC` - Returns HTML with token
3. POST `/countyweb/login.action` with token

For Orangeburg/Greenville/Greenwood/Allendale:
- Step 2 returns **empty response** (not HTML)
- Calling `login.jsp` directly returns HTML but has NO token in it

## Root Cause

LoginDisplay.action endpoint only exists/works for Lexington. Other counties use different login mechanism (possibly guest-only or browser-required).

## Alternatives Tried

1. ❌ Call login.jsp instead of loginDisplay.action → No token in HTML
2. ❌ Try logging in without token → Login fails

## Recommendation

1. **Ship Lexington as-is** (6,606 rows proven working)
2. **Other 4 counties** (13,758 rows) either:
   - Need browser automation to handle JS-based login
   - OR are guest-only (check if guest works)
   - OR need different host/endpoint

## Files

- `src/foreclosure_scraper/scrapers/counties_sc/sc_countyfusion_rod.py` - Working for Lexington
- `scripts/test_countyfusion_quick.py` - Proves 100 listings work

## Next Steps

Move to Avenu browser automation (17,344 rows) - higher ROI than debugging 4 counties.
