# SC CountyFusion ROD Scraper - Build Summary

## Deliverables

### 1. Scraper Implementation
**File**: `src/foreclosure_scraper/scrapers/counties_sc/sc_countyfusion_rod.py`

- **Coverage**: 5 counties (Lexington, Orangeburg, Greenville, Greenwood, Allendale SC)
- **Platform**: GovOS CountyFusion (countyfusion14.govos.com)
- **Authentication**: Credentials-based login (`.secrets/countyfusion/username.txt` + `password.txt`)
- **Lookback**: 730 days (2 years)
- **Row count**: Targets 20,364 rows from build list

### 2. Test Suite
**File**: `tests/test_sc_countyfusion_rod.py`

- Offline fixture-based tests
- Covers:
  - Token extraction from login page
  - Document type classification
  - Instrument types tree parsing
  - Search results parsing
  - Listing conversion
  - County configuration validation

## Implementation Details

### Counties Covered
All 5 counties verified accessible with provided credentials:

1. **Lexington** - LexingtonSC
2. **Orangeburg** - OrangeburgSC  
3. **Greenville** - GreenvilleSC
4. **Greenwood** - GreenwoodSC
5. **Allendale** - AllendaleeSC (note: AllendaleeSC, not AllendaleSC)

**Note**: Sumter is already covered separately via the existing guest-login `rod/sc_countyfusion.py` adapter.

### Login Flow
1. GET `/countyweb/login.do?countyname={County}SC`
2. GET `/countyweb/loginDisplay.action?countyname={County}SC` - extract Struts token
3. POST `/countyweb/login.action` with:
   - `username`, `password` from `.secrets/countyfusion/`
   - `struts.token.name=token` + extracted token value
   - `public=false`, `guest=false` (authenticated login, not guest)
4. Verify landing on `main.jsp` or page contains "bodyframe"

### Search Flow
1. Accept disclaimer (POST `/countyweb/disclaimer.do` with `cmd=Accept`)
2. Navigate to Advanced Search → All Names form
3. Fetch instrument types tree from `/search/getInstrumentCategories.do`
4. Filter to adverse types (liens, judgments, lis pendens, foreclosures)
5. POST search with date range + selected type IDs
6. Parse results from `/search/{county}SC/docs_SearchResultList.jsp`

### Adverse Document Type Filtering
**Included**:
- Liens (LIEN, JUDGMENT, JUDG, GARNISH, ATTACH, WARRANT)
- Foreclosure notices (LIS PENDENS, FORECLOS, NOTICE OF SALE)
- Estate/probate (DIST, DEATH, ESTATE, HEIR)

**Excluded**:
- Satisfactions/releases (REL, SAT, SATISF, TERM, CANCEL, WITHDRAW)
- Regular deeds and mortgages (unless foreclosure-related)

### Listing Classification
- **TAX_LIEN**: Liens, judgments, garnishments
- **LIS_PENDENS**: Lis pendens, foreclosure notices
- **PROBATE_NOTICE**: Deeds of distribution, estate instruments

Each listing includes:
- Grantor/grantee parties
- Book/page reference
- Instrument number
- Recorded date
- Document type
- Legal description (when available)

## Verification

### Manual Testing Completed
✅ Login flow verified for all 6 counties (including Sumter)  
✅ Instrument types discovery (132 types found in Lexington)  
✅ Adverse type filtering (18 lien-related types identified)  
✅ Token extraction working  
✅ Credentials loading from correct path

### Test Coverage
- Token extraction
- Document type classification
- JSON tree parsing
- HTML results parsing
- Listing conversion
- County configuration

## Known Issues

1. **VEnv Pydantic Issue**: The project venv has a broken pydantic installation preventing pytest from running. Tests are written and syntactically correct, but cannot be executed in the current environment. Recommend:
   - Rebuilding the venv, or
   - Running tests in a different Python environment

2. **First Run**: This is a new scraper with `expected_min_count = 0`. After first successful run, the count should be updated based on actual results.

## Integration Notes

The scraper is auto-discovered by the registry (`_registry.py`) via the `BaseScraper` pattern:
- Slug: `counties_sc.sc_countyfusion_rod`
- Category: `register_of_deeds`
- Requires render: False
- Timeout: 600s (multiple counties)

## Next Steps

1. Fix venv pydantic issue
2. Run pytest to verify all tests pass
3. Execute scraper in full pipeline to get real row counts
4. Update `expected_min_count` based on actual results
5. Add to scheduled runs if desired

## Files Created/Modified

- **Created**: `src/foreclosure_scraper/scrapers/counties_sc/sc_countyfusion_rod.py` (18,750 bytes)
- **Created**: `tests/test_sc_countyfusion_rod.py` (6,198 bytes)

## Coverage Status

| County     | Platform      | Status      | Rows (est) |
|-----------|---------------|-------------|------------|
| Lexington | CountyFusion  | ✅ Built    | ~3,104     |
| Orangeburg| CountyFusion  | ✅ Built    | Unknown    |
| Greenville| CountyFusion  | ✅ Built    | Unknown    |
| Greenwood | CountyFusion  | ✅ Built    | Unknown    |
| Allendale | CountyFusion  | ✅ Built    | Unknown    |
| Sumter    | CountyFusion  | Already covered (guest login) | ~3,612 |

**Total estimated**: 20,364+ rows across all CountyFusion counties
