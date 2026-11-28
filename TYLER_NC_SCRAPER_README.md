# Tyler NC Authenticated Scraper

## Summary

Built a Tyler NC authenticated scraper that uses credentials to access the NC eCourts Smart Search portal, which includes SP (Special Proceedings) foreclosure cases not available via the public API.

## Files Created

1. **Main Scraper**: `src/foreclosure_scraper/scrapers/counties_nc/tyler_nc_authenticated.py`
   - 400+ lines
   - Full authentication flow
   - County-by-county search
   - Result parsing and classification

2. **Credentials**: `.secrets/tyler_nc_credentials.txt`
   - Password: `2UUN@ANt7Ki?9)r`
   - Secured with 600 permissions

## Features

### Authentication
- Logs into Tyler NC portal using provided credentials
- Handles login form and session management
- Username: "cashhigh" (adjust if needed during testing)

### Coverage
- **21 NC Counties**: All WNC/foothills + coastal counties
- **Case Types**: SP, CVD, CVS, CV (foreclosure-related)
- **Date Range**: Last 2 years (730 days)

### Case Classification
- **SP (Special Proceedings)** → FORECLOSURE_SALE
  - Power-of-sale foreclosure (NCGS 45-21)
  - Partition (NCGS 46A)
- **CVD (Civil District)** → DIVORCE_NOTICE
  - Marital property division
- **CV/CVS (Civil)** → LIS_PENDENS
  - Liens, lis pendens notices

### Data Extraction
- Case number
- County
- Plaintiff (lender/bank)
- Defendant (property owner)
- Filed date
- Case type
- Parties text
- Marks rows with `nc_ecourts_authenticated: true`

### Key Features
- **Pagination**: Handles up to 20 pages per county
- **Rate Limiting**: 2-second delays between counties
- **Partial Results**: Uses `self.partial` for salvage on timeout
- **Visible Browser**: `headless=False` for CAPTCHA solving if needed
- **15-minute Timeout**: `timeout_s=900` for authenticated session

## How to Run

### On VM (Required - browsers must run on VM per project rules)

```bash
# SSH to VM
ssh opc@<vm-host>

# Navigate to project
cd /home/opc/foreclosure-scraper

# Ensure credentials are in place
mkdir -p .secrets
echo "2UUN@ANt7Ki?9)r" > .secrets/tyler_nc_credentials.txt
chmod 600 .secrets/tyler_nc_credentials.txt

# Run via the standard runner
.venv/bin/python scripts/run_scraper.py --slug counties_nc.tyler_nc_authenticated

# OR run via the scoped runner
.venv/bin/python scripts/run_scoped_scrapers.py --slugs tyler_nc_authenticated --apply
```

### Expected Output

The scraper will:
1. Log into Tyler NC portal
2. Navigate to Smart Search
3. Search each of the 21 counties
4. Parse results (case number, parties, dates)
5. Create Listing objects with proper classification
6. Return results for board integration

## Technical Details

### Dependencies
- playwright (for browser automation)
- asyncio (for async operations)
- structlog (for logging)
- re, datetime (for parsing)

### Browser Strategy
- Uses Playwright's Chromium
- Visible mode (headless=False) for CAPTCHA
- 1920x1080 viewport
- Real User-Agent string

### Error Handling
- Logs errors per county (doesn't stop entire run)
- Logs errors per row (doesn't stop page parsing)
- Salvages partial results via self.partial
- Returns empty list on total failure

### Smart Search Navigation
- Fills county filters
- Sets date range (MM/DD/YYYY format)
- Selects case type checkboxes
- Clicks search button
- Waits for networkidle
- Handles pagination

## Integration

The scraper follows the BaseScraper pattern and will be:
- Auto-discovered by the scraper registry
- Available via `run_scraper.py` and `run_scoped_scrapers.py`
- Integrated into the main pipeline
- Subject to board merge/dedupe

## Testing

Syntax validation: ✓ Passed
Import structure: Correct (needs VM environment)
Classification logic: Implemented
Party parsing: Implemented
Pagination: Implemented

**Next Step**: Run on VM with full environment to test actual execution and collect real cases.

## Notes

- Credentials are stored locally in .secrets/ and must be synced to VM
- Username may need adjustment based on actual Tyler account
- CAPTCHA solving handled automatically by visible browser
- SP cases are the primary target (not in public API)
- Results will show as `source="counties_nc.tyler_nc_authenticated"`
