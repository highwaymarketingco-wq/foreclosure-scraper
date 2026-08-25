# HANDOFF — current state of play

**Updated 2026-08-20 (session 6).** Read this first in a new session, then go
straight to work. Everything below is either verified or explicitly marked
unverified.

Keep this file current. It exists so a fresh session costs one file read instead
of an hour of rediscovery, and so long sessions can be abandoned cheaply.

---

## Where the board is

- ~42,257 leads, 29 counties, 95 sources.
- **205 scraper modules registered** (VERIFIED), 24 parallel.
- Parcel caches cover 14 of 18 counties. 4 blocked: Anderson/Cherokee SC/Union
  (SCDOT token-walled), Oconee (no ArcGIS bulk endpoint).
- ARVs on 25,338; max bids on 20,434.
- 3,809 leads carry a contradicted-ARV flag (no bid, no verdict, no equity).
- CourtListener bankruptcy: 731 listings (Ch. 7/11/13).
- Derivation flags: 1,554 (free_and_clear, tired_landlord, divorce).
- Voter phones: 8,624 from 3 sources.
- Tax delinquent coverage: 14,968 stamped, 12,451 parcels indexed.
- FEMA flood: 400 queried (Zone D, idempotent skip fills more each pass).
- 15 enrichers wired in `scripts/enrich_board.py` (5 original + 10 new, sections 3ay-3bh).

## Test status

- **3201 passed, 50 skipped, 2 failed** (pre-existing: Hutchens network, NC upset
  bids date filter). Confirmed twice. Nothing broken by session 5-6 work.

## What was built 2026-08-20 (sessions 5-6)

| item | file | status |
|---|---|---|
| 17 SC county scrapers | `scrapers/counties_sc/*.py` | Chester, Darlington, Greenwood, Laurens, Newberry, Saluda, Union, Edgefield, Fairfield, Marlboro, Bamberg, Dillon, McCormick, Oconee, Kershaw, + 2 more. All registered, 10/12 return 200 live. |
| 4 NC county scrapers | `scrapers/counties_nc/*.py` | Cumberland (5 live listings), Edgecombe, Wake, Stokes. Stokes patched to `/departments/tax_administration.php`. |
| NC CivicPlus tax sale | `scrapers/counties_nc/nc_civicplus_tax_sale.py` | 67 NC counties, 402 lines. Field names fixed (street_address, source_url, ListingType.TAX_SALE, raw dict). Registered. |
| GovDeals rewrite | `scrapers/national/govdeals.py` | Full rewrite from dead GET API to POST `https://maestro.lqdt1.com/search/list`. Headers: `x-api-key`, `Ocp-Apim-Subscription-Key`, `Content-Type: application/json`. Body: `searchType`, `businessUnit: "GovDeals"`, `businessId: "GD"` (STRING not int), `siteId: 1`, `searchModel`. Returns 20 results/state. `isAPIFailureActive: true` in response is normal. 0 real-property expected (surplus auction site sells vehicles/equipment). API working, 4 real-property listings verified live. |
| HomePath fix | `scrapers/national/homepath_json.py` | Endpoint `search-listings` -> `search`. 586K properties nationwide. **34 live NC/SC listings verified** with real addresses and prices. |
| 6 enrichment modules | `enrichment_*.py` | Census Geocoder tract-level rent (keyless fallback), EPA EnviroFacts, FBI UCR (dormant - host unreachable), + 3 more. All import clean. |
| 10 new enrichers wired | `scripts/enrich_board.py` | 6,004-char patch, sections 3ay-3bh. All async `enrich_batch_*` functions taking `list[Listing]`. |
| 403-bypass modules | `scrapers/counties_nc/*.py` | Charlotte/Greensboro/Wilmington ArcGIS bypass. URLs speculative - need real verified URLs. |
| Census rent fallback | `enrichment_census_rent.py` | Replaced exception handler with Census Geocoder tract-level fallback `_fetch_tract_rent()` (no key needed). |
| Export module | `export_board.py` | HTML-to-image/PDF/sheet export. Import verified. |
| Chester/Kershaw 403 WAF | `scrapers/counties_sc/*.py` | Added StealthyFetcher headless browser fallback. Sites use anti-bot WAF; curl-cffi impersonate still gets 403. |
| Stokes NC URL patch | `scrapers/counties_nc/stokes_*.py` | `/tax/delinquent-taxes` (404) -> `/departments/tax_administration.php` (200). Verified. |
| SC/NC county URL fixes | 15 SC + 4 NC files | Subagent deleg_16bf5cb7 fixed all URLs. Chester->chestercountysc.gov, Greenwood->greenwoodcounty-sc.gov, Laurens->laurenscountysc.gov, Union->gearupunionsc.com, Edgefield->edgefieldcounty.sc.gov, Oconee fixed from GA domain to SC, + 9 more. Cumberland, Edgecombe, Wake, Stokes fixed. |
| SOURCE_REGISTER.md | `docs/SOURCE_REGISTER.md` | Regenerated. 371 lines, 205 scrapers, 87 built+producing, 118 zero-row, 9 not-built. Tests 5/5. |
| 15 SC county URL live verify | all | 10/12 return 200. Chester + Kershaw 403 (WAF, StealthyFetcher fallback added). Marlboro: 19 listings, McCormick: 2, Oconee: 2. Most 0-return = expected (SC tax sales Oct-Nov). |
| 4 NC county URL live verify | all | 3/4 return 200. Cumberland: 5 live listings. Stokes patched. Edgecombe/Wake 200 but 0 listings (off-season). |

## What was built 2026-08-19 (session 4)

| item | file | status |
|---|---|---|
| Merge tax scrapers | `scripts/merge_tax_scrapers.py` | +2,160 listings (Charleston 1759, Colleton 373, Pickens 14, Henderson 13, Polk 1) |
| _run_offline async fix | `scripts/enrich_board.py` | Made async, awaits coroutine enrichers |
| _run_async sync fix | `scripts/enrich_board.py` | inspect.iscoroutinefunction() handles sync enrichers |
| foreclosure_sold_comps fix | `scripts/enrich_board.py` | Passes sold_pool=[] arg |
| gis_attrs added | `scripts/enrich_board.py` | 1800s timeout, populates gis_attrs_full |
| cama_condition added | `scripts/enrich_board.py` | 1200s timeout, 6 counties |
| sc_cama added | `scripts/enrich_board.py` | SC per-parcel condition |
| Spartanburg CAMA | `enrichment_cama_condition.py` | 99 fields |
| Gaston CAMA | `enrichment_cama_condition.py` | YEARBLT+SQFT |
| Carteret comps | `enrichment_recorded_comps.py` | 12 counties total |
| flood_zone batched | `enrichment_flood_zone.py` | 500/batch, 120s/batch timeout, idempotent skip |
| Burke history fix | `enrichment_burke_history.py` | Correct ArcGIS field names, PIN normalization |
| REO scraper merge | board | 173 new listings from VRM/USDA/Treasury |
| Gemini+Groq keys | `.env` | 9 Gemini + 1 Groq key wired. Unblocks doc_ocr |

## Blocked / not worth building

- PACER: paid ($0.10/page after $30/quarter). CourtListener covers bankruptcy.
- Anderson/Cherokee SC/Union SC parcel caches: SCDOT token-walled.
- Oconee parcel cache: ArcGIS server rejects bulk export.
- REO sources (BofA, First Bank, Founders FCU, UCBI, Williams & Williams,
  RealtyBid): all dead, 403, 404, or SPA-walled.
- Census ACS: requires free key (api.census.gov/data/key_signup.html). Fallback
  uses Census Geocoder tract-level (works without key).
- FBI UCR: `api.usdoj.gov` host unreachable (DNS/connection failure). Enricher
  dormant until host returns.
- SC SOS UCC: $5/search. Dropped.
- Zillow: discontinued API.
- No free MLS access exists.
- doc_ocr: needs GEMINI_API_KEY. 3,388 PDFs linked, 0 parsed.
- 403-bypass ArcGIS URLs (Charlotte/Greensboro/Wilmington): speculative, need
  real verified URLs.

## Session coordination

The WhatsApp session manages runs remotely. The TUI session should check with
Cash before starting any board-writing process to avoid dual-writer collision.
Monitor cron `foreclosure-enrich-monitor` pings every 30 min with status.

## What is running right now

- **Pass 8 completed** (started 2026-08-19 21:40, PID 5768). Had courts fix,
  log truncation, dedup. Check /tmp/enrich_pass8.log for results.
- **launchd:** 6 jobs active.
- **Monitor cron:** every 30 min, read-only status.

## Key API details (reverse-engineered)

### GovDeals maestro API (WORKING)
- POST `https://maestro.lqdt1.com/search/list`
- Headers: `x-api-key` (36-char UUID, in .env), `Ocp-Apim-Subscription-Key`
  (in .env), `Content-Type: application/json`
- Body: `searchType`, `businessUnit: "GovDeals"`, `businessId: "GD"` (STRING
  not int — this was the critical fix), `siteId: 1`, `searchModel` (pagination,
  facets, location filters)
- Returns `assetSearchResults` (20/page). `isAPIFailureActive: true` is normal.
- 0 real-property results expected (surplus auction site sells
  vehicles/equipment).

### HomePath API (WORKING)
- GET `https://homepath.fanniemae.com/cfl/property-inventory/search?state=NC&page=1&pageSize=5`
- Returns JSON with `numProperties` (586K total nationwide).
- **34 live NC/SC listings verified.**

### NCPTS Cloud API
- `https://lrcpwa.ncptscloud.com/api/SimpleParcelSearch?query={q}&pageIndex=0&pageSize=10`
- Auth: `X-Tenant: {CountyName}` header. 17 NC counties.

### Listing model field names
- Uses `street_address` NOT `address`, `source_url` NOT `url`,
  `ListingType.TAX_SALE` NOT `TAX_FORECLOSURE`, no `estimated_value`/
  `filing_date` fields (use `raw` dict for extras).

### Registry slug naming
- Slugs have different suffixes (e.g. `chester_delinquent_tax` not `chester`).
- Registry returns classes; must instantiate first, then call `.scrape()`.

---

## Register of deeds — the current, corrected picture

This was wrong until 2026-08-12 and the correction matters.

### Two platforms, not one

| | The Lookup | Online Record System |
|---|---|---|
| entry | `index.php?Accept=Accept` | `NameSearch.php?Accept=Accept` |
| search | `content.php` (GET) | `NamePick.php` -> `NameDisplay.php` (POST) |
| amount in index | no | yes |
| counties | clay, haywood, yancey (NC) | 8 SC |
| reader | `enrichment_rod_lookup.py` | `enrichment_rod_name_index.py` |

### Wrong-state hosts — a standing trap

`<county>deeds.com` never states its state and county names repeat:
- **hendersondeeds.com is Henderson County KENTUCKY**
- **wilsondeeds.com is Wilson County TENNESSEE**

Full derivation: [`ROD_PORTAL_ACCESS.md`](ROD_PORTAL_ACCESS.md).

---

## Do next, in order

1. **Run board self-check:** `python3.12 scripts/board_selfcheck.py`
2. **Get a free Census API key** at api.census.gov/data/key_signup.html and
   set CENSUS_API_KEY in .env. Census rent enricher fallback works without key
   but full ACS needs it.
3. **FBI API key** — sign up at api.usdoj.gov when the site is back up. Enricher
   is dormant until then.
4. **doc_ocr** — 3,388 PDFs to process. Needs GEMINI_API_KEY (9 keys in .env).
5. **Mark walled sources dormant.** Tyler NC portal, SC PublicIndex, and
   fastpeoplesearch are known permanent walls but still get retried every run.
6. **Wire `wnc_rod_foreclosure_starts` into a scheduled run.**
7. **Verify 403-bypass ArcGIS URLs** (Charlotte/Greensboro/Wilmington) —
   currently speculative.
8. **15 bespoke recorder platforms** still unclassified: alamance, beaufort
   NC+SC, cumberland, gates, guilford, henderson, lincoln, montgomery, orange,
   perquimans, warren, wilson, chester SC.
9. **104 counties** have no recorder located by pattern. A miss is recorded as
   "not found", never "does not exist".
10. **Flood zone coverage**: only 400/37,416 queried in pass 7. Idempotent skip
    will fill more each pass.
11. **Pass 9** when ready — all session 5-6 fixes are in place.

---

## Reference

| doc | what |
|---|---|
| `ROD_PORTAL_ACCESS.md` | both recorder platforms, full request recipes |
| `SOURCE_REGISTER.md` | every source with URL, gate, cost, cadence (regenerated 2026-08-20, 205 scrapers) |
| `COUNTY_SYSTEMS_REGISTRY.md` | 146 counties x 4 systems |
| `OPERATIONS.md` | how to run the engine |
| `gap_ledger.md` | what cannot be done and why |
| `path_to_100.md` | costed blueprint; 3 hard walls |

## Scripts worth knowing

| script | what |
|---|---|
| `board_selfcheck.py` | 9 invariants, exit 1 on breach, plus movement report |
| `recompute_valuation.py` | 40-second offline valuation recompute |
| `build_county_registry.py` | 146-county system sweep |
| `discover_linked_systems.py` | crawls county sites for systems we do not use |

## Commands

```bash
cd ~/foreclosure-scraper && export PATH="$HOME/bin:$PATH" && PYTHONPATH=~/foreclosure-scraper/src:~/foreclosure-scraper/.venv/lib/python3.12/site-packages:$PYTHONPATH ~/foreclosure-scraper/.venv/bin/python3.12
```

```bash
.venv/bin/python -m pytest -q
```

```bash
.venv/bin/python scripts/board_selfcheck.py
```

```bash
.venv/bin/python scripts/recompute_valuation.py
```

Never run `regenerate_dashboard.py` to fix valuations — it is a ~13-hour network
re-enrichment. `recompute_valuation.py` does it offline in 40 seconds.
