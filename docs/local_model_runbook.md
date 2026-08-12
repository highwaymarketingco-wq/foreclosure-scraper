# Local Model (Qwen 2.5) Daily Run Runbook

This runbook tells the local Qwen 2.5 Abliterated model (via Ollama) exactly
how to run the foreclosure scraper engine daily. No Claude needed for these tasks.

## Prerequisites

The project is at ~/foreclosure-scraper. Python 3.12 venv is at .venv/.
Always use this prefix when running Python:

```
cd ~/foreclosure-scraper && PYTHONPATH=~/foreclosure-scraper/.venv/lib/python3.12/site-packages:$PYTHONPATH ~/foreclosure-scraper/.venv/bin/python3.12
```

## Step 1: Run the full engine (daily)

```bash
cd ~/foreclosure-scraper && PYTHONPATH=~/foreclosure-scraper/.venv/lib/python3.12/site-packages:$PYTHONPATH ~/foreclosure-scraper/.venv/bin/python3.12 -m foreclosure_scraper.main
```

This runs all 121 scrapers, enrichment, scoring, and writes the board.
Wall-clock: 15-45 minutes depending on network conditions.
Output: docs/listings.json (the board) + docs/run_meta.json (run stats).

## Step 2: Run individual scrapers on demand

Using the CrewAI tools:

```python
import sys
sys.path.insert(0, "src")
from foreclosure_scraper.crewai_tools import RunScraperTool, ListScrapersTool

# List all available scrapers
list_tool = ListScrapersTool()
print(list_tool._run())

# Run a specific scraper
run_tool = RunScraperTool()
result = run_tool._run('{"slug": "national.landwatch"}')
print(result)
```

## Step 3: Run enrichment modules on demand

```python
from foreclosure_scraper.crewai_tools import RunEnrichmentTool

tool = RunEnrichmentTool()
# Available: flood_zone, fema_disaster, opportunity_zone, usps_vacancy,
# owner_mailing, jail_bookings, buyer_match, lis_pendens_resolver,
# gis_attrs, equity, distress_score
result = tool._run('{"module": "owner_mailing"}')
print(result)
```

## Step 4: Merge new leads into the board

```python
from foreclosure_scraper.crewai_tools import MergeLeadsTool

tool = MergeLeadsTool()
result = tool._run('{"file": "docs/fresh_court_leads.json"}')
print(result)
```

## Step 5: Parse saved HTML files (when operator saves court pages)

```python
from foreclosure_scraper.crewai_tools import ParseSavedHTMLTool

tool = ParseSavedHTMLTool()
result = tool._run('{"directory": "/Users/cashhigh/foreclosure-scraper", "type": "auto"}')
print(result)
```

## Step 6: Run tests after any code change

```bash
cd ~/foreclosure-scraper && PYTHONPATH=~/foreclosure-scraper/.venv/lib/python3.12/site-packages:$PYTHONPATH ~/foreclosure-scraper/.venv/bin/python3.12 -m pytest tests/ -x -q --ignore=tests/porsche
```

Expected: 1405 passed, 35 skipped, 0 failed.

## Known issues (do not try to fix, just skip)

1. Aumentum ROD (Buncombe, Gaston): date-range sweep returns empty grid.
   The ASP.NET WebForms submission needs manual browser debugging.
   Logan counties (McDowell, Transylvania, Mitchell) work fine.

2. CCHS ROD (Henderson, Cleveland, Burke, Lincoln): same pattern.
   May work intermittently; if no_docs, skip.

3. LandsofAmerica: Akamai behavioral challenge blocks stealth browser.
   Use LandWatch and LandAndFarm instead (same data, different site).

4. NC eCourts Smart Search / Search Hearings: Angular SPA won't hydrate
   under Playwright. Operator must save pages manually from their browser.

5. SC PublicIndex CaseDetails: F5 wall blocks direct access.
   The HKey postback script (scripts/fetch_sc_case_details_hkey.py) works
   through the browser console but not headless.

6. FEMA flood zone: NFHL REST endpoint behind Tivoli portal.
   The existing enrichment_flood.py module may work (different layer).

## What the operator does manually (not automatable)

- Save NC eCourts Smart Search / Search Hearings pages as HTML
- Save SC PublicIndex case detail pages (for judgment amounts)
- Solve CAPTCHAs in the headed browser (if running Playwright scripts)
- Save DOT (deed of trust) images for OCR (Spartanburg only, free)
- Google search owner names for phone numbers (manual, not automated)
- Register for HUD USPS vacancy data (free registration at huduser.gov)

## Compliance rules (never break these)

1. FREE + PUBLIC only. No paid data.
2. No CAPTCHA solving via AI vision or automated solvers.
3. No scraping PII from people-search sites (FastPeopleSearch, etc.).
4. One board-writer at a time. Always load_board() first.
5. Don't widen the frozen court stealth scrapers.
6. Mail is the TCPA-free spine. Phones are bought then DNC-scrubbed.
7. When data is ABSENT, stop. Route to FOIA/manual/paid.

## File locations

- Board: docs/listings.json + docs/listings_detail.json
- Run metadata: docs/run_meta.json
- Dashboard: docs/index.html + docs/dashboard.js
- Fresh leads: docs/fresh_court_leads.json
- Tests: tests/
- Scripts: scripts/
- Scrapers: src/foreclosure_scraper/scrapers/
- Enrichment: src/foreclosure_scraper/enrichment_*.py
- ROD adapters: src/foreclosure_scraper/rod/
- CrewAI tools: src/foreclosure_scraper/crewai_tools.py
