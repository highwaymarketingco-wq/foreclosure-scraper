# CCS 4 Counties Update - NOW Cloudflare Blocked

## Status: 2026-11-24

**Problem:** All 4 counties NOW return 403 (Cloudflare)

```bash
$ curl -I https://caldwellnc.courthousecomputersystems.com/
HTTP/2 403

$ curl -I https://franklinnc.courthousecomputersystems.com/
HTTP/2 403

$ curl -I https://hertfordnc.courthousecomputersystems.com/
HTTP/2 403

$ curl -I https://gatesnc.courthousecomputersystems.com/
HTTP/2 403
```

**When audit happened:** 2026-10-13 (nc_cchs_deeds.py docstring) — these 4 were NOT Cloudflare-blocked then  
**Now:** 2026-11-24 — ALL 4 are Cloudflare-blocked

## Fix Required

Need to adapt enrichment_gaston_rod.py's **StealthyFetcher** approach:
- Gaston already has this working (2026-11-24 fix by Claude)
- Uses `scrapling.fetchers.StealthyFetcher` with `solve_cloudflare=True`
- 3-step session runs as in-page fetch() calls from solved browser

## Implementation

The nc_ccs_name_search.py scraper I built is CORRECT for the name-search pattern, but needs:
1. StealthyFetcher browser instance
2. Run GET/POST as in-page fetch() (like Gaston)
3. Same 3-step + name-search pattern

**This is now identical complexity to Gaston ROD** — not a "smallest lift" anymore since Cloudflare changed posture.

## Alternative

Could be combined with Gaston enrichment pattern - same StealthyFetcher setup, just 4 more county URLs to iterate.

**Status:** Scraper built, needs StealthyFetcher integration (VM task like other Cloudflare fixes)
