## Avenu Insights ROD Scraper - Status and Next Steps

### ✅ Completed

1. **Scraper structure** (`src/foreclosure_scraper/scrapers/counties_sc/sc_avenu_rod.py`):
   - Multi-county support (Williamsburg, Kershaw, Newberry)
   - ASP.NET MVC login flow with CSRF token handling
   - Credentials from `.secrets/avenu_insights/`
   - Distress instrument classification
   - Date parsing for Avenu's formats
   - Listing type mapping

2. **Tests** (`tests/test_sc_avenu_rod.py`):
   - Unit tests for date parsing, classification, distress detection

3. **Documentation** (`docs/sc_avenu_rod_notes.md`):
   - Platform architecture
   - Authentication flow
   - Index types and distress filtering

4. **Test script** (`scripts/test_avenu_login.py`):
   - ✓ Login works successfully
   - ✓ CSRF token extraction
   - ✓ Search submission returns "Success"

### ⚠️ Remaining Work - Grid Data Endpoint Discovery

**The blocker**: The Kendo Grid data endpoint is not at the standard locations tried:
- `/Public/{county}sc/InstrumentGrid/GridRead` → 404
- `/Public/{county}sc/InstrumentGrid/GetGridData` → 404  
- `/Public/{county}sc/InstrumentGrid/Read` → 404

**Search submission works**: POST to `/Search` returns `{"status": "Success", "search": {...}}` which suggests search criteria are stored in session state.

**Next steps to complete**:

1. **Manual browser inspection**:
   - Open https://williamsburgsc.avenuinsights.com in browser
   - Login with credentials from `.secrets/avenu_insights/` (see below)
   - Open Dev Tools → Network tab
   - Submit a search on the InstrumentGrid page
   - Look for XHR/Fetch requests after clicking "Search" button
   - Identify the endpoint that returns actual grid data (look for JSON with "Data" array)

2. **Update `_read_grid_data()` function** in `sc_avenu_rod.py`:
   - Add the correct endpoint URL
   - Confirm request payload structure
   - Add pagination logic if needed

3. **Test end-to-end**:
   ```bash
   cd /Users/cashhigh/foreclosure-scraper
   .venv/bin/python -m foreclosure_scraper run counties_sc.sc_avenu_rod
   ```

### Alternative Approach (if grid endpoint is unavailable)

If the grid data is only client-side JavaScript populated:

1. **Use headless browser** (nodriver/patchright):
   - Load InstrumentGrid page after login
   - Submit search via JavaScript
   - Wait for grid to populate
   - Extract data from DOM table elements

2. **Reference pattern**: `sc_rod_walled.py`'s `_fetch_clarendon()` method shows how to:
   - Use nodriver to bypass Cloudflare
   - Execute JavaScript to interact with page
   - Extract data from rendered HTML

### File Locations

| File | Path |
|------|------|
| Scraper | `src/foreclosure_scraper/scrapers/counties_sc/sc_avenu_rod.py` |
| Tests | `tests/test_sc_avenu_rod.py` |
| Docs | `docs/sc_avenu_rod_notes.md` |
| Test script | `scripts/test_avenu_login.py` |
| Credentials | `.secrets/avenu_insights/email.txt` + `password.txt` |

### Credentials Status

✓ Stored in `.secrets/avenu_insights/` (gitignored, values never committed):
- email.txt
- password.txt

✓ Login tested and working for williamsburgsc.avenuinsights.com

### Estimated Completion Time

Once the grid endpoint is discovered:
- Update endpoint URL in code: 5 minutes
- Test scraper run: 10 minutes
- **Total remaining**: ~15 minutes

The scraper structure is complete and follows existing patterns (anderson_acpass_deeds.py). Only the grid data endpoint URL needs to be identified through browser inspection.
