# Greenville/Greenwood Imperva - Status Check

## 2026-11-24 Testing

**Greenville Probate:**
- URL: https://www.greenvillecounty.org/appsas400/Probate/SearchResults.aspx
- Status: Timeout (Imperva blocking)
- Current scraper: Has increased delays (2.0s, 3.0s) but still getting 403s

**Greenwood:**
- URL unknown (needs investigation)
- Test URL (https://www.greenwoodsc.gov/148/Probate-Court) returns 404

## Questions for Investigation

1. **Is StealthyFetcher Cloudflare-specific?**
   - Gaston uses `solve_cloudflare=True`
   - Does it handle Imperva/Incapsula too?
   - Or need different tool?

2. **What's the actual Greenwood probate URL?**
   - Greenville is .org/appsas400/Probate
   - Greenwood needs to be found

## Next Steps

**Greenville:** Needs VM/browser testing with StealthyFetcher to see if it handles Imperva  
**Greenwood:** Needs URL discovery first

**Status:** Both need real browser investigation, not Mac curl testing
