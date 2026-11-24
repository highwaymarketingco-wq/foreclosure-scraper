# CCS 4 Counties - Adapt Name-Search Pattern

## Context (from Claude's guidance)

**Counties:** Caldwell, Franklin, Hertford, Gates (NC)  
**Current status:** Broad date-range search times out (Cloudflare 524)  
**Proven fix:** Adapt Gaston ROD's per-owner name-search pattern

## Technical Details (from nc_cchs_deeds.py docstring)

**Current broken approach:**
- Broad date-range POST with no name filter
- Backend can't handle this (times out every time)
- Returns Cloudflare 524 "A timeout occurred"

**Working approach (from enrichment_gaston_rod.py):**
- 3-step session: GET / → GET /LRSearch/LRIndex → POST /LRSearch/ExecuteSearch
- Search by owner name (last + first)
- Fast, reliable, proven in production

**Key difference from Gaston:**
- These 4 counties are NOT Cloudflare-blocked
- curl_cffi gets clean 200s
- Don't need StealthyFetcher

## Implementation Plan

###  1. Adapt name-search for discovery mode

Instead of enrichment (looking up ONE known owner), we need DISCOVERY (finding ALL distress owners).

**Strategy:** Iterate common surnames
- Use census/phonebook common last names
- Search each surname: Smith, Johnson, Williams, etc.
- Extract instruments with distress indicators (LIEN, JUDG, etc.)

### 2. Reuse Gaston's proven code

**From enrichment_gaston_rod.py:**
- `_body()` - POST body builder (line 87-100)
- `parse_rows()` - DevExpress grid parser (line 103-112)
- `_ROW` / `_CELL` regex (line 79-80)

**Adapt for each county:**
```python
BASE = "https://{subdomain}.courthousecomputersystems.com"

SUBDOMAINS = {
    "caldwell": "caldwellnc",
    "franklin": "franklinnc",
    "hertford": "hertfordnc",
    "gates": "gatesnc",
}
```

### 3. Filter for distress signals

**Look for these Kind codes / Description patterns:**
- LIEN, JUDG, TAX (judgment/lien indicators)
- LIS PEND, LIS PENDENS (pre-foreclosure)
- DEED + court case number (MIE deed)
- FORECLOS, TRUSTEE (foreclosure-related)

### 4. Build as discovery scraper

Create new file: `src/foreclosure_scraper/scrapers/counties_nc/nc_cchs_name_search.py`

**Key functions:**
1. `_seed_session(county_base)` - 3-step session setup
2. `_search_surname(session, surname)` - POST with name
3. `_parse_instruments(html)` - extract rows
4. `_filter_distress(rows)` - keep only distress signals
5. `fetch()` - iterate counties × common surnames

### 5. Common surname list

Top 100 US surnames should cover ~15-20% of population:
```python
COMMON_SURNAMES = [
    "SMITH", "JOHNSON", "WILLIAMS", "BROWN", "JONES",
    "GARCIA", "MILLER", "DAVIS", "RODRIGUEZ", "MARTINEZ",
    # ... top 100
]
```

## Expected Impact

**Current:** 0 listings (always times out)  
**After fix:** Estimated 2K-5K listings across 4 counties

**Why this will work:**
- Gaston ROD proves the endpoint works for name searches
- Same DevExpress app, same endpoints
- These counties aren't even Cloudflare-blocked
- Just need to search names instead of dates

## Next Steps

1. Create `nc_cchs_name_search.py` with adapted Gaston code
2. Test against one county (Caldwell) with 10 surnames
3. Verify distress filtering works
4. Expand to all 4 counties with full surname list
5. Run and verify real listings

**This is a REAL build task with proven pattern to follow.**
