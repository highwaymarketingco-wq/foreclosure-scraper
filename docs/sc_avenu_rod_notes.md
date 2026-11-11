# SC Avenu Insights ROD Scraper

## Overview

Scraper for Williamsburg, Kershaw, and Newberry counties in South Carolina.
All three counties use the same Avenu Insights/Neumo Records Management platform.

**Platform**: https://{county}sc.avenuinsights.com  
**Counties**: williamsburg, kershaw, newberry  
**Estimated rows**: 17,344 total (5,800 + 5,800 + 5,744)

## Authentication

Requires login credentials stored in:
- `.secrets/avenu_insights/email.txt`: cashrandolphhigh@gmail.com
- `.secrets/avenu_insights/password.txt`: 1Caroline

**Login flow**:
1. GET `/Public/{county}sc/Account/Login` to extract `__RequestVerificationToken` CSRF token
2. POST credentials + token to same URL
3. Session cookies persist for subsequent requests

## Data Collection Strategy

The platform uses ASP.NET MVC + Kendo Grid. The grid is populated via:

1. **Search submission**: POST to `/Public/{county}sc/InstrumentGrid/Search` with:
   - `FromDate` / `ToDate` (MM/DD/YYYY format)
   - `SelectedIndexIDs` (comma-separated index type IDs)
   - Kendo Grid pagination params (`take`, `skip`, `page`, `pageSize`)

2. **Grid data retrieval**: After search submission, the grid reads from session state.
   Common Kendo Grid patterns tried:
   - `/Public/{county}sc/InstrumentGrid/GridRead`
   - `/Public/{county}sc/InstrumentGrid/GetGridData`
   - `/Public/{county}sc/InstrumentGrid/Read`

## Instrument Index Types

We search these distress-related indices (from live platform data):

| ID | Name | Purpose |
|----|------|---------|
| 1 | DEED | Foreclosure deeds, sheriff deeds |
| 2 | MORTGAGE | LIS PENDENS may appear here |
| 4 | JUDGEMENT | Foreclosure judgments |
| 5 | TAXLIEN | Tax lien filings |

## Record Structure

Grid returns JSON with records containing:

| Field | Description |
|-------|-------------|
| `InstrumentID` | Unique identifier |
| `InstrumentDateAsString` | Recorded date (MM/DD/YYYY or /Date(ms)/) |
| `DirectName` | Grantor (party conveying) |
| `IndirectName` | Grantee (party receiving) |
| `Act` | Instrument number |
| `Kind` | Instrument type (e.g., "LIS PENDENS", "FORECLOSURE DEED") |
| `Description` | Additional details |
| `Book`, `Volume`, `Page` | Recording location |

## Distress Classification

Filters for instruments matching keywords:
- LIS PENDENS, FC, FORECLOSURE, SHERIFF, TAX
- JUDGMENT, DECREE, NOTICE OF SALE, MASTER IN EQUITY

Maps to ListingType:
- `LIS_PENDENS`: Lis pendens notices
- `FORECLOSURE_SALE`: Foreclosure-related deeds
- `SHERIFF_SALE`: Sheriff sales, master in equity sales
- `TAX_LIEN`: Tax lien filings
- `TAX_SALE`: Tax sale deeds

## Testing

### Unit Tests

```bash
cd /Users/cashhigh/foreclosure-scraper
.venv/bin/python -m pytest tests/test_sc_avenu_rod.py -v
```

Tests cover:
- Date parsing (`/Date(ms)/` and `MM/DD/YYYY` formats)
- Distress instrument detection
- Listing type classification

### Integration Test (Manual)

```bash
cd /Users/cashhigh/foreclosure-scraper
.venv/bin/python scripts/test_login_williamsburg.py
```

Create test script:
```python
import asyncio
from foreclosure_scraper.scrapers.counties_sc.sc_avenu_rod import ScAvenuRod

async def test():
    scraper = ScAvenuRod()
    listings = await scraper.fetch()
    print(f"Found {len(listings)} distress listings")
    if listings:
        print(f"Sample: {listings[0].source_url}")

asyncio.run(test())
```

### Live Run

```bash
.venv/bin/python -m foreclosure_scraper run counties_sc.sc_avenu_rod
```

## Known Gaps

1. **Grid data endpoint not fully confirmed**: The scraper tries common Kendo Grid patterns but the exact endpoint may need live testing to discover.

2. **Pagination**: Current implementation attempts single-page retrieval (500 records). If total > 500, pagination logic will need to be added.

3. **Session timeout**: Unknown session lifetime. May need refresh logic for long runs.

## Troubleshooting

### Login fails
- Verify credentials in `.secrets/avenu_insights/`
- Check CSRF token extraction (ASP.NET regenerates on each page load)
- Ensure httpx client `follow_redirects=True` is set

### No grid data returned
- Login succeeded but grid endpoint is wrong
- Use browser dev tools to capture actual grid read endpoint
- Search may need to be submitted before grid reads

### Empty results
- Distress filter may be too restrictive
- Check `_is_distress_instrument()` keyword list
- Verify date range has data (`_LOOKBACK_DAYS` environment variable)

## Future Enhancements

1. **Document links**: Platform has image viewer at `/Public/{county}sc/InstrumentGrid/Details?InstrumentID={id}`. Could extract PDFs.

2. **Property matching**: Records have `DirectName`/`IndirectName` but no addresses. Needs enrichment via name→property resolution or county GIS.

3. **Multi-page support**: Add pagination if row counts exceed single-page limit.

4. **Monitoring**: Add expected row counts per county for anomaly detection.
