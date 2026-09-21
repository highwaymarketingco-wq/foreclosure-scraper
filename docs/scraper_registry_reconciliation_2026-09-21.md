# Scraper registry reconciliation, 2026-09-21

Audit item A7: which registered scrapers produce board rows, which do not, and why. Read-only. Measured by one streaming pass over `docs/listings.json.gz` (170,066 rows, written 2026-09-21 10:10) joined to `scrapers/_registry.discover()`, the run logs in `logs/local-run-*.log`, `docs/run_meta.json`, each module's docstring and the repo docs named in the evidence column.

## 1. Headline numbers and one correction

- **Registered scrapers: 229**, not 209. The 209 in the audit is the scraper count logged by the 8/29 runs (`orchestrator.start scrapers=209`). The 9/8 run logged 218, and the registry has grown since (`docs/SOURCE_REGISTER.md`, generated 9/15, already said 229). Slugs are unique and none is empty. 2 carry a `disabled` class flag, 18 carry `active_months`.
- **Board sources: 156**, 124 of them exactly equal to a registered slug, 32 not. Registered scrapers therefore explain 107,473 rows (63%); the 32 unregistered sources hold 62,593 (37%). The board `source` string is whatever the scraper (or ingest script) wrote into `Listing.source`; it equals the registry slug for 124 scrapers and differs for the rest (section 4).
- **Registered scrapers with zero rows under their own slug: 105** (`SOURCE_REGISTER.md` on 9/15 said 100 of 229). Four of the 105 are MIS-NAMED and are in fact landing rows under child slugs, so the true zero-row count is 101.
- **The zero-row causes are not what the alarm surfaces suggest.** Only 10 are walled and 3 are dead. The largest groups are EMPTY (22), FILTERED (18: the scraper fetched rows and the post-scrape filters removed every one), DORMANT (17, seasonal) and TIMEOUT (11). Five scrapers fetched rows that passed the filters in the last two runs and never landed because neither run wrote the board (NOT LANDED), one of them 1,334 rows.
- **Run health is wrong for every dynamic-slug scraper.** The orchestrator keys per-source health on the scraper slug, but the listings carry child slugs. `orchestrator.source_all_filtered` therefore reports 'OK with rows but 0 reached the dashboard' for arcgis_distress_layers (8,772 rows scraped), state_contamination (5,572) and epa_frs_sites (269) while the board holds 10,126 of their rows. `run_meta.source_status` is frozen at 8/29 and contradicts the logs in both directions (sc_tax_delinquent 'EMPTY (verified)' against 1,334 rows scraped).
- **17 registered scrapers with at least 100 rows are 80% or more stale** (16,448 rows); they are marked `stale` in the table. Board-wide the count is 18 sources and 17,039 rows now, and 19 sources and 18,284 rows on the 09:34 board, which reproduces audit section 3c exactly (`spartanburg_vacant` was refreshed by the 10:10 run).

### Zero-row classes

The first seven classes are the ones asked for. FILTERED, NOT LANDED, DORMANT and NOT A LEAD SOURCE are added because they hold 44 of the 105 and none of the seven fits them.

| Class | Count | Meaning |
|---|--:|---|
| EMPTY | 22 | source ran clean and has no current records |
| FILTERED | 18 | fetched rows, every one removed by scope, date or footprint filters before the board |
| DORMANT | 17 | seasonal `active_months`, skipped off-season |
| TIMEOUT | 11 | killed by the soft timeout (8/28 and 9/8 runs were under heavy swap; several were OK on 8/29) |
| DISABLED | 11 | feature flag, or a 9/15 soft-disable recorded in the docstring |
| WALLED | 10 | login, Cloudflare, Akamai, 403 or a stale robots gate |
| NOT LANDED | 5 | rows passed the filters in the last runs but no run wrote the board since |
| MIS-NAMED | 4 | rows exist under child slugs |
| DEAD | 3 | source gone or parser broken |
| NOT A LEAD SOURCE | 4 | enrichment helper or cloud-split ingest, zero by design |
| NEVER RUN | 0 (1 partial) | `sc_catalis_delinquent_roll` was added 9/10, after the last full-scrape log, so no orchestrator run has ever included it; it is listed under WALLED because its manual runs ended in 429 then 403 |


Two filters are the likely causes of FILTERED; the logs do not say which one fired. First, `main._active_only` drops a row with no `sale_date` unless its slug is in `DATELESS_OK_SOURCES` (147 slugs); the evidence column says whether each slug is. Second, flip-type rows (foreclosure sale, sheriff sale, auction, HOA sale, REO) are limited to the 18 footprint counties. The 9/8 and 8/29 logs predate the 9/15 change that admits every other lead type in all 146 counties, so an 'outside the footprint' reading of a tax, lien, FLC or surplus source may be out of date: the next full run could land some of them.

Logged runs used for the evidence: 9/8 (218 scrapers started, board write refused by the count guard), 8/29 evening (209; killed), 8/28 (209; the run that wrote the board on 8/29 05:43). No full run has landed since 8/29, so every 'last run' below is history.

## 2. Ranked: zero-row scrapers most worth reviving

Ranked by expected lead yield among scrapers that are not walled. Yield figures are quoted from the module docstrings and run logs; none was re-fetched (no network was used).

| # | Scraper | Class | Expected yield | Notes |
|---|---|---|---|---|
| 1 | `counties_nc.rutherford_wildfire_tax` | WALLED by a stale gate | Up to 29,319 delinquent bills (TY2016 to TY2025, real and personal property; the server's own `TotalRecords` on 2026-08-03) for Rutherford, a footprint county whose current roll `rutherford_tax` (4,164 rows) is 98% stale (2% seen in 30 days). | The only barrier is a robots preflight that fails closed. The owner decided on 9/20 that robots.txt is not a wall, so the gate contradicts current policy. Risk: the shared CDN host 429 then 403'd for the Pickens roll on 9/11, so run one polite probe before changing code. Filter to real property. |
| 2 | `counties_sc.sc_tax_delinquent` | NOT LANDED | 1,334 SC delinquent-tax rows, scraped OK on 8/29 and 9/8, zero on the board. | Not walled. Land it with a scoped run, and correct run_meta, which calls it EMPTY (verified). It is also in the F8 sold-pool source list. |
| 3 | `counties_sc.greenville_tax_distress` | DISABLED by flag | Up to 3,409 hard-distress parcels (docstring, 8/3). Also gives a situs address to the 2,287 `greenville_delinquent_tax` rows that have none (audit section 16: 100% missing). | Open ArcGIS, no CAPTCHA. The flag encodes a pre-9/15 scope decision; distressed leads are now in scope in all 146 counties. The 9/8 run hit 'service not started' (HTTP 500), so re-check the service first. |
| 4 | 14 seasonal SC delinquent-tax scrapers | DORMANT until 10/1 | Each county's annual delinquent list; yield unmeasured. Laurens (3,203 rows on the board) and Union (1,368) are footprint counties. | They wake in nine days. Smoke-test the parsers now rather than learning on 10/1 that one broke. `lancaster_delinquent_tax` is already in season and returns zero (list posted closer to the sale). |
| 5 | `counties_nc.gaston_tax_foreclosures` | NOT LANDED | 81 rows on 9/8 (active and previous sales with upset status) for Gaston, the second-largest footprint county. | Not walled. Bid-able flip-lane rows; needs a run that writes the board. |
| 6 | `counties_sc.anderson_sheriff` | TIMEOUT 3 of 3 | Small (tens of rows) but real sheriff-sale flips in a footprint county. | Diagnose the 120 s timeout; the other two sheriff scrapers return zero legitimately. |
| 7 | `newspapers.daily_courier` | DEAD (regressed) | Rutherford legal notices, about 9 before it broke; partly closes the Rutherford upset-bid gap in project memory. | run_meta flags REGRESSED and it returns zero in every run: re-fit the parser to the current page. |
| 8 | `public_notices.funeral_home_rss` | FILTERED | 40 to 50 obituary rows per pass, all dropped because they carry no county. | Route them through the name-to-property resolver instead of the scope gate. Pre-probate estate leads. |
| 9 | `national.craigslist_fsbo` | TIMEOUT / dropped | 255 rows were on the 9/15 board and are gone; 288 scraped on 8/29. | Weak distress signal. Only if FSBO leads are wanted. |
| 10 | `counties_nc.wnc_tax_foreclosures` | TIMEOUT 3 of 3 | Multi-county low-volume pages (Watauga, Avery and others). | A bounded wait_for landed 9/15 and has not been run since; test before doing more. |

Not worth reviving: the ten WALLED scrapers (govdeals, landsofamerica, loopnet, mewborn_deselms, nc_sos_ucc, publicnoticesc, usmarshals_realproperty, national.liensnc, and the Catalis Pickens roll, which now answers 403), the three DEAD, the paid services (propwire, probate_foreclosure_leads), the 9/15 garbage emitters, and every scraper whose ZERO is a true empty (`EMPTY`). `sc_probate_notices` is not zero (873 rows under child slugs) but its timeout still discards work; the 9/8 run salvaged 655 rows after a timeout, so the partial-ship fix matters there.

## 3. Board sources that are not in the registry, and how they refresh

32 sources, 62,593 rows. None is refreshed by a scheduled job: the launchd plists in `~/Library/LaunchAgents` (vision, lrcpwa, parcelcache, sosagent, the Tue/Fri popup, the Hermes gateway, a disabled dailycourt) name no ingest script, and no plist names the `scripts/run_family_*.sh` wrappers, which exist but run only when someone starts them. Their `last_seen` values are recent because a process rebuilt the rows, not because the source was re-read.

| Board source | Rows | HOT | WARM | Seen 30d | Last seen | Written by |
|---|--:|--:|--:|--:|---|---|
| `counties_generic.liensnc` | 40,909 | 129 | 33,665 | 100% | 2026-09-21 | `scripts/ingest_liensnc.py`: operator-saved LiensNC result pages parsed offline (site is login-gated, ToS bars automation). Manual only. |
| `liensnc` | 6,080 | 2 | 4,624 | 100% | 2026-09-21 | same manual lane, older bare slug |
| `nc_ecourts_judgments` | 3,273 | 1 | 273 | 100% | 2026-09-21 | `scripts/scrape_ncecourts.py` via `run_family_nc_ecourts.sh` and `family_merge.py`, plus `fix_nc_ecourts_judgments.py`. Manual, not scheduled. |
| `counties_generic.state_contamination.nc_ust_incidents` | 3,254 | 0 | 44 | 100% | 2026-09-21 | child of a registered scraper, landed once by `scripts/ingest_counties_generic_never_run.py` (9/15); no scheduler calls it |
| `counties_generic.arcgis_distress.spartanburg_property_cleanup` | 1,927 | 0 | 1 | 100% | 2026-09-21 | child of a registered scraper, landed once by `scripts/ingest_counties_generic_never_run.py` (9/15); no scheduler calls it |
| `counties_generic.arcgis_distress.new_hanover_demolition_permits` | 1,308 | 645 | 404 | 99% | 2026-09-21 | child of a registered scraper, landed once by `scripts/ingest_counties_generic_never_run.py` (9/15); no scheduler calls it |
| `courtlistener.recap` | 737 | 0 | 0 | 100% | 2026-08-27 | orphaned pre-rename slug of `national.courtlistener_bankruptcy`; `scripts/fix_courtlistener_recap.py`. Last touched 8/27, not refreshed. |
| `counties_generic.arcgis_distress.spartanburg_infill_eligible` | 730 | 0 | 82 | 100% | 2026-09-15 | child of a registered scraper, landed once by `scripts/ingest_counties_generic_never_run.py` (9/15); no scheduler calls it |
| `counties_sc.sc_public_index_export` | 591 | 7 | 495 | 2% | 2026-09-21 | manual court-export lane (`ingest_saved.sh`, `finalize_integration.py`, `prune_stale_court.py`). 2% seen in 30 days. |
| `counties_sc.sc_probate_notices.yourpickenscounty` | 510 | 0 | 0 | 100% | 2026-09-15 | child of `sc_probate_notices`, landed once by `scripts/ingest_sc_never_run_cluster.py` (9/15); no scheduler calls it |
| `counties_generic.state_contamination.nc_dam_safety` | 504 | 0 | 4 | 100% | 2026-09-21 | child of a registered scraper, landed once by `scripts/ingest_counties_generic_never_run.py` (9/15); no scheduler calls it |
| `counties_generic.arcgis_distress.buncombe_unpaid_bills` | 418 | 0 | 326 | 100% | 2026-09-21 | child of a registered scraper, landed once by `scripts/ingest_counties_generic_never_run.py` (9/15); no scheduler calls it |
| `counties_generic.arcgis_distress.burke_storm_damage` | 397 | 0 | 5 | 100% | 2026-09-15 | child of a registered scraper, landed once by `scripts/ingest_counties_generic_never_run.py` (9/15); no scheduler calls it |
| `counties_generic.arcgis_distress.buncombe_landslide_damage` | 316 | 0 | 0 | 100% | 2026-09-21 | child of a registered scraper, landed once by `scripts/ingest_counties_generic_never_run.py` (9/15); no scheduler calls it |
| `counties_generic.arcgis_distress.pickens_flood_damage` | 292 | 0 | 18 | 100% | 2026-09-15 | child of a registered scraper, landed once by `scripts/ingest_counties_generic_never_run.py` (9/15); no scheduler calls it |
| `counties_sc.sc_probate_notices.gaffneyledger` | 228 | 0 | 1 | 100% | 2026-09-15 | child of `sc_probate_notices`, landed once by `scripts/ingest_sc_never_run_cluster.py` (9/15); no scheduler calls it |
| `counties_generic.arcgis_distress.buncombe_hmgp_buyout` | 196 | 0 | 0 | 100% | 2026-09-15 | child of a registered scraper, landed once by `scripts/ingest_counties_generic_never_run.py` (9/15); no scheduler calls it |
| `counties_generic.state_contamination.nc_inactive_hazardous` | 145 | 0 | 3 | 100% | 2026-09-15 | child of a registered scraper, landed once by `scripts/ingest_counties_generic_never_run.py` (9/15); no scheduler calls it |
| `counties_sc.sc_probate_notices.laurenscountyadvertiser` | 135 | 0 | 0 | 100% | 2026-09-15 | child of `sc_probate_notices`, landed once by `scripts/ingest_sc_never_run_cluster.py` (9/15); no scheduler calls it |
| `counties_generic.epa_frs.acres` | 109 | 0 | 0 | 100% | 2026-09-15 | child of a registered scraper, landed once by `scripts/ingest_counties_generic_never_run.py` (9/15); no scheduler calls it |
| `counties_generic.arcgis_distress.hendersonville_flood_zone_structures` | 93 | 0 | 0 | 100% | 2026-09-15 | child of a registered scraper, landed once by `scripts/ingest_counties_generic_never_run.py` (9/15); no scheduler calls it |
| `counties_generic.arcgis_distress.transylvania_damage_assessment` | 84 | 0 | 5 | 100% | 2026-09-15 | child of a registered scraper, landed once by `scripts/ingest_counties_generic_never_run.py` (9/15); no scheduler calls it |
| `counties_generic.epa_frs.sems` | 79 | 0 | 0 | 100% | 2026-09-21 | child of a registered scraper, landed once by `scripts/ingest_counties_generic_never_run.py` (9/15); no scheduler calls it |
| `counties_generic.arcgis_distress.buncombe_county_owned` | 78 | 0 | 0 | 100% | 2026-09-15 | child of a registered scraper, landed once by `scripts/ingest_counties_generic_never_run.py` (9/15); no scheduler calls it |
| `counties_generic.arcgis_distress.laurens_county_owned` | 48 | 0 | 0 | 100% | 2026-09-15 | child of a registered scraper, landed once by `scripts/ingest_counties_generic_never_run.py` (9/15); no scheduler calls it |
| `counties_generic.arcgis_distress.spartanburg_city_tax_sale` | 47 | 0 | 36 | 100% | 2026-09-15 | child of a registered scraper, landed once by `scripts/ingest_counties_generic_never_run.py` (9/15); no scheduler calls it |
| `counties_generic.arcgis_distress.buncombe_unpaid_bills_2024` | 47 | 0 | 34 | 100% | 2026-09-15 | child of a registered scraper, landed once by `scripts/ingest_counties_generic_never_run.py` (9/15); no scheduler calls it |
| `counties_generic.arcgis_distress.lincoln_county_owned` | 34 | 0 | 0 | 100% | 2026-09-15 | child of a registered scraper, landed once by `scripts/ingest_counties_generic_never_run.py` (9/15); no scheduler calls it |
| `counties_generic.arcgis_distress.burke_county_owned` | 11 | 0 | 0 | 100% | 2026-09-15 | child of a registered scraper, landed once by `scripts/ingest_counties_generic_never_run.py` (9/15); no scheduler calls it |
| `counties_generic.arcgis_distress.pickens_county_owned` | 9 | 0 | 0 | 100% | 2026-09-15 | child of a registered scraper, landed once by `scripts/ingest_counties_generic_never_run.py` (9/15); no scheduler calls it |
| `derived.probate_deed` | 3 | 1 | 2 | 0% | 2026-08-17 | derived inside `main.py`; 3 rows, last seen 8/17. |
| `manual.watchlist` | 1 | 0 | 0 | 100% | 2026-09-13 | `scripts/add_watchlist_property.py`; 1 row. |

The 'Seen 30d' figure says a process rewrote the row recently, not that the source still lists it (`last_seen` is reset when a Listing is rebuilt, audit section 2).

## 4. Source strings that differ from the registry slug

| Scraper | Emits | Rows on board |
|---|---|--:|
| `counties_generic.arcgis_distress_layers` | `counties_generic.arcgis_distress.<name>` (17 children) | 6,035 |
| `counties_generic.state_contamination` | `counties_generic.state_contamination.<name>` (3 children) | 3,903 |
| `counties_generic.epa_frs_sites` | `counties_generic.epa_frs.<name>` (2 children) | 188 |
| `counties_sc.sc_probate_notices` | `counties_sc.sc_probate_notices.<name>` (3 children) | 873 |
| `national.liensnc` | nothing (dead, login-gated); the board's `liensnc` and `counties_generic.liensnc` come from a manual ingest, not this class | 0 |
| `city_websites.search` | `city_websites.<domain>`; no such child is on the board (disabled 9/15 as a garbage emitter) | 0 |

Three scrapers appear on the board only as secondary provenance (`raw.also_seen_in`): `gaston_tax_foreclosures` 1, `henderson_tax` 3, `polk_tax` 1.

## 5. Every registered scraper

Columns: rows on the current board by exact slug, HOT and WARM rows, share of rows with `last_seen` within 30 days, status, and the outcome of the two most recent logged runs (9/8, then 8/29 evening). `stale` = at least 100 rows and 20% or less seen in 30 days. Zero-row rows carry their class and evidence.


### national (58 registered, 28 with zero rows)

| Slug | Module | Rows | HOT | WARM | Seen 30d | Status | 9/8 | 8/29 | Evidence |
|---|---|--:|--:|--:|--:|---|---|---|---|
| `national.auction_bank_reo` | `auction_bank_reo` | 0 | 0 | 0 | | **TIMEOUT** | timeout | OK 2 (all filtered) | TIMEOUT 9/8 and 8/28; 8/29 OK 2 rows, all filtered; United Community Bank answers 403 at the edge |
| `national.auction_dot_com` | `auction_dot_com` | 13 | 7 | 6 | 23% | mixed | timeout | OK 117 | |
| `national.bid4assets` | `bid4assets` | 0 | 0 | 0 | | **DISABLED** | timeout | OK 4 (all filtered) | 9/15 docstring: confirmed garbage emitter; TIMEOUT on 9/8 |
| `national.cash_buyer_deeds` | `cash_buyer_deeds` | 23 | 0 | 22 | 9% | mixed | timeout | OK 262 | |
| `national.courtlistener_adversary` | `courtlistener_adversary` | 13 | 0 | 12 | 0% | mixed | timeout | OK 239 | |
| `national.courtlistener_bankruptcy` | `courtlistener_bankruptcy` | 641 | 11 | 327 | 15% | stale | OK 560 | OK 3,587 | |
| `national.courtlistener_civil` | `courtlistener_civil` | 0 | 0 | 0 | | **TIMEOUT** | timeout | blocked | TIMEOUT 9/8 and 8/28, BLOCKED 8/29; run_meta says EMPTY (verified) |
| `national.craigslist_fsbo` | `craigslist_fsbo` | 0 | 0 | 0 | | **TIMEOUT** | timeout | OK 288 (all filtered) | TIMEOUT 9/8 and 8/28; 8/29 OK 288 rows, all filtered (county unknown before geocode). 255 rows were on the 9/15 board, 0 now |
| `national.crexi_multifamily` | `crexi_multifamily` | 21 | 6 | 15 | 5% | mixed | timeout | zero | |
| `national.cws_marketing` | `cws_marketing` | 0 | 0 | 0 | | **TIMEOUT** | timeout | OK 15 (all filtered) | TIMEOUT 9/8 and 8/28; 8/29 OK 15 rows, all filtered |
| `national.distressed` | `homeharvest_distressed` | 364 | 59 | 209 | 100% | fresh | OK 310 | OK 305 | |
| `national.epa_superfund` | `epa_superfund` | 0 | 0 | 0 | | **DISABLED** | timeout | zero | 9/15 docstring: the endpoint route no longer exists (403 MissingAuthenticationTokenException) and the FRS scraper covers it |
| `national.estate_sales` | `estate_sales` | 25 | 1 | 6 | 4% | mixed | timeout | OK 53 | |
| `national.fannie_homepath` | `fannie_homepath` | 243 | 19 | 224 | 12% | stale | OK 8,169 | OK 8,229 | |
| `national.fdic_failed_banks` | `fdic_failed_banks` | 0 | 0 | 0 | | **TIMEOUT** | timeout | OK 8 (all filtered) | TIMEOUT 9/8 and 8/28; 8/29 OK 8 rows, all filtered (a bank list, not properties) |
| `national.fema_disasters` | `fema_disasters` | 19 | 0 | 0 | 100% | fresh | timeout | blocked | |
| `national.first_citizens_reo` | `first_citizens_reo` | 0 | 0 | 0 | | **TIMEOUT** | timeout | OK 4 (all filtered) | TIMEOUT 9/8 and 8/28; 8/29 OK 4 rows, all filtered; page 403s plain HTTP (Akamai) and needs the local stealth render |
| `national.foreclosure_dot_com` | `foreclosure_dot_com` | 23 | 2 | 17 | 100% | fresh | OK 5,581 | zero | |
| `national.freddie_homesteps` | `freddie_homesteps` | 1 | 0 | 1 | 100% | fresh | OK 29 | OK 28 | |
| `national.govdeals` | `govdeals` | 0 | 0 | 0 | | **WALLED** | zero | zero | maestro.lqdt1.com: embedded API key rotated (HTTP 400/401) behind Akamai; ZERO in all runs (MASTER_GAPS row: CANT) |
| `national.gsa_surplus` | `gsa_surplus` | 0 | 0 | 0 | | **EMPTY** | zero | zero | ZERO in all runs since the 9/15 rewrite (old URL 404); 1 row was on the 9/15 board |
| `national.hibid_real_estate` | `hibid_real_estate` | 0 | 0 | 0 | | **NOT LANDED** | OK 16 | OK 17 | OK 16-17 rows every run, not flagged filtered; 5 rows were on the 9/15 board, 0 now; slug is NOT in DATELESS_OK_SOURCES |
| `national.homeharvest` | `homeharvest` | 15 | 3 | 11 | 100% | fresh | OK 20 | OK 19 | |
| `national.homepath_json` | `homepath_json` | 2 | 0 | 0 | 100% | fresh | OK 20 (all filtered) | OK 22 (all filtered) | |
| `national.hubzu` | `hubzu` | 16 | 6 | 10 | 31% | mixed | OK 113 | OK 119 | |
| `national.hud_homestore` | `hud_homestore` | 11 | 4 | 6 | 100% | fresh | OK 33 | OK 41 | |
| `national.hud_reac_inspection` | `hud_reac_inspection` | 212 | 111 | 101 | 13% | stale | STARTED_NEVER_FINISH | OK 852 | |
| `national.hud_section8_contracts` | `hud_section8_contracts` | 37 | 17 | 20 | 22% | mixed | OK 250 | OK 250 | |
| `national.irs_judicial_sales` | `irs_judicial_sales` | 0 | 0 | 0 | | **EMPTY** | zero | zero | ZERO in all runs; docstring 8/17: portal live, no NC/SC sale active |
| `national.irs_treasury` | `irs_treasury_auctions` | 0 | 0 | 0 | | **EMPTY** | zero | zero | ZERO in all runs; docstring 8/20: 18 auctions nationally, 0 in NC/SC |
| `national.jail_bookings` | `jail_bookings` | 6 | 0 | 5 | 17% | mixed | OK 2,604 | OK 2,069 | |
| `national.landandfarm` | `landandfarm` | 393 | 0 | 128 | 76% | mixed | partial 25 | OK 650 | |
| `national.landsofamerica` | `landsofamerica` | 0 | 0 | 0 | | **WALLED** | timeout | zero | Akamai behavioral challenge; TIMEOUT 9/8 and 8/28 (run_meta ALARM, 600 s); MASTER_GAPS lists land.com as Akamai-walled |
| `national.landwatch` | `landwatch` | 487 | 0 | 133 | 65% | mixed | partial 50 | OK 650 | |
| `national.legacy_obituaries` | `legacy_obituaries` | 0 | 0 | 0 | | **DISABLED** | OK 665 (all filtered) | OK 703 (all filtered) | 9/15 docstring: state filter silently ignored, returns other states; pre-disable runs scraped 665-703 rows, all dropped |
| `national.liensnc` | `liensnc` | 0 | 0 | 0 | | **WALLED** | zero | zero | login-gated ('Sign Up ... or login', docstring 9/15). Superseded by the operator-saved manual lane (counties_generic.liensnc, 47K rows on the board) |
| `national.loopnet` | `loopnet` | 0 | 0 | 0 | | **WALLED** | zero | zero | hard 403 / login per MASTER_GAPS; ZERO 9/8 and 8/29, TIMEOUT 8/28 |
| `national.nc_sos_ucc` | `nc_sos_ucc` | 0 | 0 | 0 | | **WALLED** | zero | zero | sosnc.gov Cloudflare managed challenge; ZERO in all runs |
| `national.nc_upset_bids` | `nc_upset_bids` | 20 | 0 | 15 | 70% | mixed | OK 45 | OK 44 | |
| `national.opencorporates` | `opencorporates` | 0 | 0 | 0 | | **NOT A LEAD SOURCE** | zero | zero | entity-enrichment API (free tier); ZERO by design |
| `national.probate_foreclosure_leads` | `probate_foreclosure_leads` | 0 | 0 | 0 | | **DISABLED** | zero | zero | paid Apify actor; owner opted out of paid services (docstring); run_meta EMPTY (verified) |
| `national.propwire` | `propwire_foreclosures` | 0 | 0 | 0 | | **DISABLED** | zero | zero | paid service (about $0.007 per record); owner opted out (docstring); memory notes DataDome on the site |
| `national.realtor_foreclosures` | `realtor_foreclosures` | 2 | 0 | 2 | 100% | fresh | OK 19 | OK 17 | |
| `national.sc_public_index` | `sc_public_index` | 1,506 | 0 | 0 | 100% | fresh | error | timeout | |
| `national.sc_sos_entity` | `sc_sos_entity` | 0 | 0 | 0 | | **NOT A LEAD SOURCE** | zero | zero | entity-enrichment lookup; ZERO by design (memory: SC SoS is captcha-walled) |
| `national.seeclickfix` | `seeclickfix` | 0 | 0 | 0 | | **DISABLED** | timeout | OK 1,484 (all filtered) | 9/15 docstring: garbage emitter (geo filter ignored); pre-disable 8/29 run scraped 1,484 rows, all dropped |
| `national.servicelink_auction` | `servicelink_auction` | 23 | 11 | 12 | 39% | mixed | OK 37 | OK 45 | |
| `national.sheriff_sales` | `sheriff_sales` | 1 | 0 | 1 | 100% | fresh | OK 6 | OK 6 | |
| `national.stealth_handoff` | `stealth_handoff` | 0 | 0 | 0 | | **NOT A LEAD SOURCE** | zero | not run | cloud-split ingest of docs/handoff/stealth_leads.json; unused on the single-host Mac run; absent from the 8/28-8/29 runs |
| `national.tranzon` | `tranzon_auctions` | 0 | 0 | 0 | | **FILTERED** | OK 1 (all filtered) | OK 1 (all filtered) | OK 1 row every run, removed post-filter (no in-scope NC/SC auction); slug is NOT in DATELESS_OK_SOURCES |
| `national.trulia` | `trulia_foreclosures` | 6 | 0 | 5 | 67% | mixed | timeout | OK 2 | |
| `national.usda_properties` | `usda_properties` | 317 | 0 | 0 | 100% | fresh | OK 336 | OK 336 | |
| `national.usmarshals_realproperty` | `usmarshals_realproperty` | 0 | 0 | 0 | | **WALLED** | blocked | blocked | HTTP 403, BLOCKED in all three runs (blocked_sources_forensic: 'blocked, no public feed') |
| `national.va_acquired` | `va_acquired` | 0 | 0 | 0 | | **EMPTY** | zero | zero | ZERO in all runs |
| `national.williams` | `williams_auctions` | 0 | 0 | 0 | | **EMPTY** | zero | zero | ZERO in all runs; docstring 8/20: none in the NC/SC footprint |
| `national.xome` | `xome` | 8 | 1 | 5 | 62% | mixed | partial 19 | OK 74 | |
| `national.zillow_bulk` | `zillow_bulk` | 61 | 12 | 49 | 11% | mixed | timeout | OK 82 | |
| `national.zillow_foreclosures` | `zillow_foreclosures` | 74 | 0 | 27 | 82% | fresh | timeout | OK 407 | |

### public_notices (5 registered, 2 with zero rows)

| Slug | Module | Rows | HOT | WARM | Seen 30d | Status | 9/8 | 8/29 | Evidence |
|---|---|--:|--:|--:|--:|---|---|---|---|
| `public_notices.funeral_home_rss` | `funeral_home_rss` | 0 | 0 | 0 | | **FILTERED** | OK 50 (all filtered) | OK 50 (all filtered) | OK 40-50 obituary rows every run, all removed post-filter (rows carry no county); slug is NOT in DATELESS_OK_SOURCES |
| `public_notices.gannett_obituaries` | `gannett_obituaries` | 131 | 21 | 110 | 3% | stale | OK 125 | OK 146 | |
| `public_notices.nc_notices_counties` | `nc_notices_counties` | 694 | 12 | 78 | 87% | fresh | timeout | OK 608 | |
| `public_notices.ncnotices` | `ncpublicnotices` | 34 | 3 | 19 | 38% | mixed | timeout | OK 139 | |
| `public_notices.publicnoticesc` | `publicnoticesc` | 0 | 0 | 0 | | **WALLED** | zero | zero | Cloudflare challenge defeats plain and stealth fetch (docstring); ZERO in all runs |

### law_firms (14 registered, 5 with zero rows)

| Slug | Module | Rows | HOT | WARM | Seen 30d | Status | 9/8 | 8/29 | Evidence |
|---|---|--:|--:|--:|--:|---|---|---|---|
| `law_firms.alaw` | `alaw` | 0 | 0 | 0 | | **TIMEOUT** | timeout | OK 26 (all filtered) | TIMEOUT 9/8 and 8/28; 8/29 OK 26 rows, all removed post-filter (run_meta OK (26)) |
| `law_firms.aldridge_pite` | `aldridge_pite` | 0 | 0 | 0 | | **EMPTY** | zero | zero | run_meta EMPTY (verified); NC list served, no in-scope rows; the firm left SC (docstring) |
| `law_firms.bell_carrington` | `bell_carrington` | 14 | 1 | 11 | 14% | mixed | OK 38 | OK 63 | |
| `law_firms.brock_scott` | `brock_scott` | 71 | 1 | 63 | 27% | mixed | zero | OK 78 | |
| `law_firms.finkel` | `finkel` | 0 | 0 | 0 | | **FILTERED** | blocked | OK 8 (all filtered) | 8/29 OK 8 rows, all removed post-filter (run_meta OK (8)); 9/8 BLOCKED once; slug is NOT in DATELESS_OK_SOURCES |
| `law_firms.hutchens` | `hutchens` | 78 | 1 | 61 | 64% | mixed | OK 86 | OK 86 | |
| `law_firms.ingle_firm` | `ingle_firm` | 1 | 0 | 1 | 0% | mixed | OK 2 | zero | |
| `law_firms.kania` | `kania` | 31 | 1 | 20 | 45% | mixed | OK 52 | OK 55 | |
| `law_firms.korn` | `korn` | 0 | 0 | 0 | | **DEAD** | zero | zero | domain parked, site gone (docstring 2026-05-13); the module is a stub that returns [] without a request |
| `law_firms.mcmichael_taylor_gray` | `mcmichael_taylor_gray` | 9 | 1 | 6 | 44% | mixed | OK 85 | OK 85 | |
| `law_firms.mewborn_deselms` | `mewborn_deselms` | 0 | 0 | 0 | | **WALLED** | blocked | blocked | Cloudflare challenge: HTTP 403 with cf-mitigated: challenge, BLOCKED in all three runs; the retry-until-it-relents fix was removed on compliance grounds (docstring) |
| `law_firms.rogers_townsend` | `rogers_townsend` | 15 | 1 | 12 | 60% | mixed | OK 27 | OK 25 | |
| `law_firms.shapiro_ingle_powerbi` | `shapiro_ingle_powerbi` | 65 | 0 | 8 | 9% | mixed | OK 107 | OK 84 | |
| `law_firms.zacchaeus` | `zacchaeus` | 55 | 0 | 21 | 100% | fresh | OK 137 (all filtered) | OK 134 (all filtered) | |

### counties_sc (76 registered, 36 with zero rows)

| Slug | Module | Rows | HOT | WARM | Seen 30d | Status | 9/8 | 8/29 | Evidence |
|---|---|--:|--:|--:|--:|---|---|---|---|
| `counties_sc.abbeville_delinquent_tax` | `abbeville_delinquent_tax` | 0 | 0 | 0 | | **DORMANT** | off-season | off-season | off-season: active months [10, 11, 12, 1]; skipped in all three logged runs |
| `counties_sc.aiken_delinquent_tax` | `aiken_delinquent_tax` | 0 | 0 | 0 | | **DORMANT** | off-season | off-season | off-season: active months [10, 11, 12, 1]; skipped in all three logged runs |
| `counties_sc.anderson_master_in_equity` | `anderson_master_in_equity` | 19 | 0 | 9 | 21% | mixed | OK 21 (all filtered) | OK 19 | |
| `counties_sc.anderson_sheriff` | `anderson_sheriff` | 0 | 0 | 0 | | **TIMEOUT** | timeout | timeout | TIMEOUT (120 s soft limit) in all three runs; Anderson is a footprint county |
| `counties_sc.bamberg_sheriff` | `bamberg_sheriff` | 0 | 0 | 0 | | **EMPTY** | zero | zero | ZERO in all runs; rural county outside the footprint |
| `counties_sc.barnwell_sheriff` | `barnwell_sheriff` | 0 | 0 | 0 | | **EMPTY** | zero | zero | ZERO in all runs; rural county outside the footprint |
| `counties_sc.berkeley_paystar_tax` | `berkeley_paystar_tax` | 2,310 | 0 | 1,700 | 100% | fresh | not run | not run | |
| `counties_sc.charleston_delinquent_tax` | `charleston_delinquent_tax` | 1,125 | 0 | 831 | 100% | fresh | OK 1,760 (all filtered) | OK 1,760 (all filtered) | |
| `counties_sc.charleston_mie` | `charleston_mie` | 54 | 0 | 9 | 4% | mixed | OK 37 | OK 48 | |
| `counties_sc.cherokee_delinquent_tax` | `cherokee_delinquent_tax` | 528 | 0 | 419 | 37% | mixed | OK 528 | OK 528 | |
| `counties_sc.cherokee_rod` | `cherokee_rod` | 0 | 0 | 0 | | **NOT A LEAD SOURCE** | zero | zero | enrichment helper for ROD lookups; ZERO by design |
| `counties_sc.chester_delinquent_tax` | `chester_delinquent_tax` | 0 | 0 | 0 | | **DORMANT** | off-season | off-season | off-season: active months [10, 11, 12, 1]; skipped in all three logged runs |
| `counties_sc.clarendon_tax_auction` | `clarendon_tax_auction` | 0 | 0 | 0 | | **DISABLED** | OK 23 (all filtered) | off-season | 9/15 docstring: disabled, keyword link follower emits junk; 9/8 run scraped 23 rows, all dropped |
| `counties_sc.colleton_tax_sale` | `colleton_tax_sale` | 0 | 0 | 0 | | **DORMANT** | off-season | off-season | off-season: active months [12, 1, 2, 3]; skipped in all three logged runs |
| `counties_sc.darlington_delinquent_tax` | `darlington_delinquent_tax` | 0 | 0 | 0 | | **DORMANT** | off-season | off-season | off-season: active months [10, 11, 12, 1]; skipped in all three logged runs |
| `counties_sc.dillon_delinquent_tax` | `dillon_delinquent_tax` | 809 | 0 | 3 | 100% | fresh | not run | not run | |
| `counties_sc.dillon_sheriff` | `dillon_sheriff` | 0 | 0 | 0 | | **FILTERED** | OK 1 (all filtered) | OK 1 (all filtered) | OK 1 row every run, removed post-filter (Dillon outside the footprint); slug is NOT in DATELESS_OK_SOURCES |
| `counties_sc.edgefield_delinquent_tax` | `edgefield_delinquent_tax` | 0 | 0 | 0 | | **DORMANT** | off-season | off-season | off-season: active months [10, 11, 12, 1]; skipped in all three logged runs |
| `counties_sc.fairfield_delinquent_tax` | `fairfield_delinquent_tax` | 0 | 0 | 0 | | **DORMANT** | off-season | off-season | off-season: active months [10, 11, 12, 1]; skipped in all three logged runs |
| `counties_sc.florence_delinquent_tax` | `florence_delinquent_tax` | 2,005 | 0 | 0 | 100% | fresh | off-season | off-season | |
| `counties_sc.georgetown_civicengage` | `georgetown_civicengage` | 365 | 0 | 28 | 1% | stale | OK 417 | OK 418 | |
| `counties_sc.greenville_delinquent_tax` | `greenville_delinquent_tax` | 2,287 | 0 | 162 | 100% | fresh | not run | not run | |
| `counties_sc.greenville_mie_adverts` | `greenville_mie_adverts` | 308 | 0 | 21 | 100% | fresh | not run | not run | |
| `counties_sc.greenville_tax_distress` | `greenville_hard_distress` | 0 | 0 | 0 | | **DISABLED** | error | disabled | feature flag FORECLOSURE_INCLUDE_GREENVILLE unset (a pre-9/15 scope decision); the 9/8 run also hit 'Greenville GIS service not started' (HTTP 500) |
| `counties_sc.greenwood_delinquent_tax` | `greenwood_delinquent_tax` | 0 | 0 | 0 | | **DORMANT** | off-season | off-season | off-season: active months [10, 11, 12, 1]; skipped in all three logged runs |
| `counties_sc.horry_flc` | `horry_flc` | 22 | 0 | 12 | 100% | fresh | OK 20 (all filtered) | OK 20 (all filtered) | |
| `counties_sc.kershaw_flc` | `kershaw_flc` | 0 | 0 | 0 | | **TIMEOUT** | timeout | blocked | TIMEOUT 9/8 and 8/28, BLOCKED 8/29 (county-owned FLC, outside the footprint) |
| `counties_sc.lancaster_delinquent_tax` | `lancaster_delinquent_tax` | 0 | 0 | 0 | | **EMPTY** | zero | zero | in season (Aug to Jan) and ZERO in all runs; the list is posted closer to the sale; URL repointed 9/10 after a 404 |
| `counties_sc.laurens_delinquent_tax` | `laurens_delinquent_tax` | 0 | 0 | 0 | | **DORMANT** | off-season | off-season | off-season: active months [10, 11, 12, 1]; skipped in all three logged runs |
| `counties_sc.lexington_flc` | `lexington_flc` | 0 | 0 | 0 | | **EMPTY** | zero | zero | ZERO in all runs (FLC page links a PDF list; none current) |
| `counties_sc.marlboro_delinquent_tax` | `marlboro_delinquent_tax` | 0 | 0 | 0 | | **DORMANT** | off-season | off-season | off-season: active months [10, 11, 12, 1]; skipped in all three logged runs |
| `counties_sc.mccormick_flc` | `mccormick_flc` | 0 | 0 | 0 | | **FILTERED** | OK 2 (all filtered) | OK 2 (all filtered) | OK 2 rows every run, all removed post-filter (county-owned FLC inventory, outside the footprint); slug is NOT in DATELESS_OK_SOURCES |
| `counties_sc.meares_auctions` | `meares_auctions` | 0 | 0 | 0 | | **EMPTY** | zero | zero | ZERO 9/8 and 8/29, OK 1 on 8/28; no current upstate auctions on the site |
| `counties_sc.newberry_delinquent_tax` | `newberry_delinquent_tax` | 0 | 0 | 0 | | **DORMANT** | off-season | off-season | off-season: active months [10, 11, 12, 1]; skipped in all three logged runs |
| `counties_sc.oconee_flc` | `oconee_flc` | 0 | 0 | 0 | | **FILTERED** | OK 2 (all filtered) | OK 2 (all filtered) | OK 2 rows every run, all removed post-filter (Oconee is in the footprint; county-owned FLC inventory); slug is NOT in DATELESS_OK_SOURCES |
| `counties_sc.oconee_flc_assignment` | `oconee_flc_assignment` | 490 | 1 | 452 | 6% | stale | OK 585 | OK 585 | |
| `counties_sc.oconee_forfeited_land` | `oconee_forfeited_land` | 208 | 0 | 201 | 23% | mixed | OK 533 | OK 533 | |
| `counties_sc.oconee_tax_sale` | `oconee_tax_sale` | 0 | 0 | 0 | | **EMPTY** | zero | zero | run_meta EMPTY (verified); annual Google Sheet is empty between cycles |
| `counties_sc.pickens_delinquent_parcels` | `pickens_delinquent_parcels` | 1,854 | 37 | 1,225 | 10% | stale | OK 2,161 | OK 2,161 | |
| `counties_sc.pickens_master_in_equity` | `pickens_master_in_equity` | 16 | 1 | 9 | 50% | mixed | OK 32 | OK 32 | |
| `counties_sc.pickens_tax_sale` | `pickens_tax_sale` | 23 | 0 | 18 | 100% | fresh | OK 160 (all filtered) | OK 160 (all filtered) | |
| `counties_sc.qpaybill_delinquent_roll` | `qpaybill_delinquent_roll` | 33,527 | 1 | 9,016 | 100% | fresh | not run | not run | |
| `counties_sc.richland_flc` | `richland_flc` | 3 | 0 | 0 | 100% | fresh | not run | not run | |
| `counties_sc.saluda_delinquent_tax` | `saluda_delinquent_tax` | 0 | 0 | 0 | | **DORMANT** | off-season | off-season | off-season: active months [10, 11, 12, 1]; skipped in all three logged runs |
| `counties_sc.sc_catalis_delinquent_roll` | `sc_catalis_delinquent_roll` | 0 | 0 | 0 | | **WALLED** | not run | not run | NEVER RUN by the orchestrator (added 9/10, after the 9/8 run). Manual runs 9/10-9/11: 0 rows, then 429, then hard 403 on Pickens (build_queue W4, logs/catalis_*.log) |
| `counties_sc.sc_coastal_rosters` | `sc_coastal_rosters` | 0 | 0 | 0 | | **TIMEOUT** | zero | OK 4 (all filtered) | run_meta ALARM: TIMEOUT 1,200 s; 9/8 ZERO, 8/29 OK 4 rows all filtered; needs the stealth render of publicindex.sccourts.org |
| `counties_sc.sc_county_rosters` | `sc_county_rosters` | 9 | 0 | 9 | 22% | mixed | timeout | OK 2 | |
| `counties_sc.sc_delinquent_tax_list` | `sc_delinquent_tax_list` | 0 | 0 | 0 | | **DORMANT** | off-season | off-season | off-season: active months [10, 11, 12, 1]; skipped in all three logged runs |
| `counties_sc.sc_des_brownfields` | `sc_des_brownfields` | 64 | 0 | 0 | 100% | fresh | OK 71 (all filtered) | OK 71 (all filtered) | |
| `counties_sc.sc_dew_lien_registry` | `sc_dew_lien_registry` | 8,810 | 24 | 773 | 100% | fresh | disabled | disabled | |
| `counties_sc.sc_dor_delinquent_taxpayers` | `sc_dor_delinquent` | 0 | 0 | 0 | | **EMPTY** | zero | zero | ZERO in all runs; the MyDORWAY portal is a JS grid this module does not render (build_queue S-13) |
| `counties_sc.sc_flc` | `sc_flc` | 73 | 16 | 55 | 1% | mixed | zero | zero | |
| `counties_sc.sc_probate_net` | `sc_probate_net` | 265 | 0 | 265 | 2% | stale | timeout | OK 236 | |
| `counties_sc.sc_probate_notices` | `sc_probate_notices` | 0 | 0 | 0 | | **MIS-NAMED** | partial 655 | timeout | emits counties_sc.sc_probate_notices.<paper>: 873 rows (yourpickenscounty 510, gaffneyledger 228, laurenscountyadvertiser 135). 9/8 run: PARTIAL, 655 salvaged after timeout |
| `counties_sc.sc_public_index` | `sc_public_index` | 5,050 | 23 | 1,607 | 39% | mixed | timeout | timeout | |
| `counties_sc.sc_public_index_lis_pendens` | `sc_public_index_lis_pendens` | 373 | 16 | 281 | 25% | mixed | timeout | OK 153 | |
| `counties_sc.sc_public_notices` | `sc_public_notices` | 688 | 2 | 136 | 88% | fresh | timeout | timeout | |
| `counties_sc.sc_rod_acclaim` | `sc_rod_acclaim` | 173 | 10 | 158 | 2% | stale | OK 91 | OK 98 | |
| `counties_sc.sc_rod_cott` | `sc_rod_cott` | 1 | 0 | 1 | 0% | mixed | zero | OK 31 | |
| `counties_sc.sc_state_tax_lien` | `sc_state_tax_lien` | 66 | 0 | 4 | 98% | fresh | OK 80 | OK 80 | |
| `counties_sc.sc_tax_delinquent` | `sc_tax_delinquent` | 0 | 0 | 0 | | **NOT LANDED** | OK 1,334 | OK 1,334 | OK 1,334 rows on 8/29 and 9/8 (8/28 run timed out) and 0 on the board: neither run wrote the board. run_meta says 'EMPTY (verified)', which the logs contradict; slug is in DATELESS_OK_SOURCES |
| `counties_sc.sc_ust_registry` | `sc_ust_registry` | 2,342 | 11 | 209 | 100% | fresh | OK 3,331 (all filtered) | OK 3,330 (all filtered) | |
| `counties_sc.spartan_weekly_legals` | `spartan_weekly_legals` | 188 | 7 | 172 | 2% | stale | timeout | OK 134 | |
| `counties_sc.spartanburg_city_condemned` | `spartanburg_city_condemned` | 83 | 63 | 20 | 25% | mixed | OK 92 | OK 91 | |
| `counties_sc.spartanburg_condemned` | `spartanburg_condemned` | 1,070 | 48 | 1,022 | 16% | stale | OK 1,830 | OK 1,830 | |
| `counties_sc.spartanburg_delinquent_tax` | `spartanburg_delinquent_tax` | 1,707 | 196 | 1,341 | 27% | mixed | OK 2,171 | OK 2,171 | |
| `counties_sc.spartanburg_flc` | `spartanburg_flc` | 6 | 0 | 5 | 83% | fresh | OK 5 | OK 5 | |
| `counties_sc.spartanburg_master_in_equity` | `spartanburg_master_in_equity` | 2 | 0 | 0 | 0% | mixed | OK 32 (all filtered) | OK 19 (all filtered) | |
| `counties_sc.spartanburg_vacant` | `spartanburg_vacant` | 1,232 | 42 | 1,190 | 21% | mixed | OK 4,659 | OK 4,659 | |
| `counties_sc.sumter_surplus` | `sumter_surplus` | 0 | 0 | 0 | | **FILTERED** | OK 2 (all filtered) | OK 2 (all filtered) | OK 2 rows every run, all removed post-filter (Sumter outside the footprint; county surplus sales); slug is NOT in DATELESS_OK_SOURCES |
| `counties_sc.terry_howe_auctions` | `terry_howe_auctions` | 296 | 6 | 32 | 100% | fresh | OK 897 | OK 897 | |
| `counties_sc.terry_howe_flc` | `terry_howe_flc` | 23 | 2 | 17 | 26% | mixed | OK 23 | OK 23 | |
| `counties_sc.union_delinquent_tax` | `union_delinquent_tax` | 0 | 0 | 0 | | **DORMANT** | off-season | off-season | off-season: active months [10, 11, 12, 1]; skipped in all three logged runs |
| `counties_sc.york_delinquent_tax` | `york_delinquent_tax` | 0 | 0 | 0 | | **DORMANT** | off-season | off-season | off-season: active months [10, 11, 12, 1]; skipped in all three logged runs |
| `counties_sc.york_overage_claims` | `york_overage_claims` | 108 | 0 | 0 | 100% | fresh | not run | not run | |
| `counties_sc.zombie_properties` | `zombie_properties` | 0 | 0 | 0 | | **EMPTY** | zero | zero | ZERO in all runs; a derived signal (lis pendens over 12 months old with no sale) that finds none |

### counties_nc (51 registered, 20 with zero rows)

| Slug | Module | Rows | HOT | WARM | Seen 30d | Status | 9/8 | 8/29 | Evidence |
|---|---|--:|--:|--:|--:|---|---|---|---|
| `counties_nc.asheville_helene` | `asheville_helene` | 115 | 34 | 81 | 13% | stale | OK 652 | OK 652 | |
| `counties_nc.asheville_str_permits` | `asheville_str_permits` | 555 | 9 | 232 | 8% | stale | OK 678 | OK 678 | |
| `counties_nc.brunswick_legal_notices` | `brunswick_legal_notices` | 0 | 0 | 0 | | **FILTERED** | OK 2 (all filtered) | OK 2 (all filtered) | OK 2 rows every run, all removed post-filter (Brunswick is outside the 18-county flip footprint); slug is in DATELESS_OK_SOURCES |
| `counties_nc.buncombe_delinquent_tax` | `buncombe_delinquent_tax` | 937 | 3 | 652 | 25% | mixed | OK 1,181 | OK 1,181 | |
| `counties_nc.buncombe_elderly` | `buncombe_elderly` | 2,988 | 24 | 632 | 5% | stale | OK 4,344 | OK 4,344 | |
| `counties_nc.buncombe_tax` | `buncombe_tax` | 13 | 0 | 10 | 8% | mixed | OK 37 | OK 35 | |
| `counties_nc.buncombe_tax_foreclosure` | `buncombe_tax_foreclosure` | 0 | 0 | 0 | | **FILTERED** | OK 4 (all filtered) | zero | 9/8 OK 4 rows, all removed post-filter; ZERO on the 8/28-8/29 runs (run_meta OK (2)); slug is NOT in DATELESS_OK_SOURCES |
| `counties_nc.cleveland_tax` | `cleveland_tax` | 6 | 0 | 6 | 0% | mixed | OK 17 | OK 14 | |
| `counties_nc.cleveland_tax_foreclosure` | `cleveland_tax_foreclosure` | 1 | 0 | 1 | 100% | fresh | OK 17 | not run | |
| `counties_nc.cumberland_tax_foreclosure` | `cumberland_tax_foreclosure` | 0 | 0 | 0 | | **DORMANT** | off-season | OK 5 (all filtered) | active Jan to Aug; 8/28-8/29 OK 5 rows, all removed post-filter (Cumberland outside the footprint) |
| `counties_nc.edgecombe_tax_foreclosure` | `edgecombe_tax_foreclosure` | 17 | 0 | 0 | 100% | fresh | off-season | OK 20 (all filtered) | |
| `counties_nc.gaston_surplus_properties` | `gaston_surplus_properties` | 0 | 0 | 0 | | **EMPTY** | zero | zero | run_meta EMPTY (verified); the page reads 'There are no surplus properties at this time' |
| `counties_nc.gaston_tax_foreclosures` | `gaston_tax_foreclosures` | 0 | 0 | 0 | | **NOT LANDED** | OK 81 | zero | 9/8 run scraped 81 rows and they passed the filters; 0 on 8/28-8/29 runs; no run has written the board since, so none landed (1 row on the 9/15 board, 1 as also_seen_in); slug is NOT in DATELESS_OK_SOURCES |
| `counties_nc.gaston_vacant` | `gaston_vacant` | 7,035 | 3 | 1,816 | 100% | fresh | OK 21,289 | not run | |
| `counties_nc.haywood_tax_foreclosures` | `haywood_tax_foreclosures` | 1 | 0 | 0 | 100% | fresh | zero | zero | |
| `counties_nc.henderson_code_violations` | `henderson_code_violations` | 154 | 45 | 109 | 28% | mixed | OK 167 | OK 159 | |
| `counties_nc.henderson_foreclosure_parcels` | `henderson_foreclosure_parcels` | 4 | 0 | 2 | 50% | mixed | OK 15 | OK 15 | |
| `counties_nc.henderson_tax` | `henderson_tax` | 0 | 0 | 0 | | **FILTERED** | OK 15 (all filtered) | OK 15 (all filtered) | OK 15 rows every run, all removed post-filter (batch sale date passed or dateless); 3 rows survive only as also_seen_in provenance; slug is NOT in DATELESS_OK_SOURCES |
| `counties_nc.hendersonville_vacant_structures` | `hendersonville_vacant_structures` | 45 | 20 | 25 | 22% | mixed | OK 51 | OK 51 | |
| `counties_nc.lincoln_code_violations` | `lincoln_code_violations` | 32 | 0 | 1 | 100% | fresh | OK 63 | OK 63 | |
| `counties_nc.lincoln_vacant` | `lincoln_vacant` | 2,189 | 0 | 15 | 100% | fresh | OK 14,814 | not run | |
| `counties_nc.mcdowell_probate` | `mcdowell_probate` | 227 | 15 | 101 | 100% | fresh | OK 414 | not run | |
| `counties_nc.mcdowell_tax_foreclosure` | `mcdowell_tax_foreclosure` | 0 | 0 | 0 | | **FILTERED** | OK 2 (all filtered) | not run | 9/8 OK 2 rows, all removed post-filter (module added 8/30, absent from the earlier runs); slug is NOT in DATELESS_OK_SOURCES |
| `counties_nc.nc_bankruptcy_sales` | `nc_bankruptcy_sales` | 0 | 0 | 0 | | **FILTERED** | OK 8 (all filtered) | OK 8 (all filtered) | OK 8 rows every run, all removed post-filter; slug is NOT in DATELESS_OK_SOURCES |
| `counties_nc.nc_civicplus_tax_sale` | `nc_civicplus_tax_sale` | 0 | 0 | 0 | | **EMPTY** | zero | zero | ZERO in all runs (sitemap discovery finds no matching pages) |
| `counties_nc.nc_coastal_tax_foreclosure` | `nc_coastal_tax_foreclosure` | 0 | 0 | 0 | | **NOT LANDED** | OK 5 | OK 5 | OK 5 rows every run and not flagged all-filtered (run_meta OK (2)), yet 0 on the board; cause not evidenced (coastal county, oceanfront re-pass is the likely drop); slug is in DATELESS_OK_SOURCES |
| `counties_nc.nc_county_csv_delinquent_tax` | `nc_county_csv_delinquent_tax` | 1,222 | 4 | 618 | 8% | stale | OK 1,404 | OK 1,440 | |
| `counties_nc.nc_county_pdf_delinquent_tax` | `nc_county_pdf_delinquent_tax` | 1,772 | 40 | 1,035 | 19% | stale | OK 8,922 | OK 8,922 | |
| `counties_nc.nc_county_tax_foreclosure` | `nc_county_tax_foreclosure` | 5 | 0 | 3 | 100% | fresh | OK 86 | OK 86 | |
| `counties_nc.nc_deq_dsca` | `nc_deq_dsca` | 0 | 0 | 0 | | **DISABLED** | OK 4 (all filtered) | OK 4 (all filtered) | 9/15 docstring: 'DISABLED, NOT JUST DORMANT'; scraped 4 rows every run, all dropped |
| `counties_nc.nc_ecourts_divorce` | `nc_ecourts_divorce` | 241 | 0 | 75 | 81% | fresh | timeout | OK 197 | |
| `counties_nc.nc_ecourts_estates` | `nc_ecourts_estates` | 0 | 0 | 0 | | **DISABLED** | disabled | disabled | feature flag: 'NC eCourts AWS-WAF CAPTCHA unsolvable; NC estate covered via Column' (also WALLED) |
| `counties_nc.nc_ecourts_lis_pendens` | `nc_ecourts_lis_pendens` | 493 | 2 | 126 | 71% | mixed | timeout | OK 481 | |
| `counties_nc.nc_govdeals_real_property` | `nc_govdeals_real_property` | 1 | 0 | 1 | 0% | mixed | OK 1 | OK 1 | |
| `counties_nc.nc_heir_estate_parcels` | `nc_heir_estate_parcels` | 678 | 216 | 462 | 22% | mixed | timeout | OK 873 | |
| `counties_nc.nc_ptscloud_delinquent_tax` | `nc_ptscloud_delinquent_tax` | 1,154 | 1 | 739 | 85% | fresh | partial 5819 | timeout | |
| `counties_nc.nc_rod_logan` | `nc_rod_logan` | 14 | 0 | 14 | 14% | mixed | OK 18 | timeout | |
| `counties_nc.nc_rod_substitute_trustee` | `nc_rod_substitute_trustee` | 2 | 0 | 2 | 0% | mixed | timeout | timeout | |
| `counties_nc.nchfa_reo` | `nchfa_reo` | 0 | 0 | 0 | | **EMPTY** | zero | zero | ZERO in all runs (state-agency REO page lists none) |
| `counties_nc.new_hanover_foreclosures` | `new_hanover_foreclosures` | 0 | 0 | 0 | | **FILTERED** | OK 1 (all filtered) | OK 1 (all filtered) | OK 1 row every run, removed post-filter (coastal, outside the footprint); slug is NOT in DATELESS_OK_SOURCES |
| `counties_nc.polk_tax` | `polk_tax` | 0 | 0 | 0 | | **EMPTY** | zero | OK 1 | ZERO 9/8 (1 row earlier); the Kania page shows only a past March 2026 sale; 1 row survives as also_seen_in |
| `counties_nc.rutherford_foreclosure` | `rutherford_foreclosure` | 4 | 0 | 4 | 100% | fresh | OK 20 | not run | |
| `counties_nc.rutherford_tax` | `rutherford_tax` | 4,164 | 48 | 2,110 | 2% | stale | timeout | OK 9,328 | |
| `counties_nc.rutherford_wildfire_tax` | `rutherford_wildfire_tax` | 0 | 0 | 0 | | **WALLED** | zero | zero | fetch() runs a robots preflight that fails closed (Disallow: / on both hosts) and never reaches the API. Robots is no longer a wall (owner decision 9/20), so the gate is stale. The shared CDN host also 429 then 403'd for the Pickens roll on 9/11: needs one polite live probe |
| `counties_nc.stokes_delinquent_tax` | `stokes_delinquent_tax` | 0 | 0 | 0 | | **DORMANT** | off-season | zero | active Jan to Aug; ZERO on the 8/28-8/29 runs (Stokes is outside the footprint) |
| `counties_nc.swain_tax_foreclosures` | `swain_tax_foreclosures` | 0 | 0 | 0 | | **EMPTY** | zero | zero | ZERO in all runs (no current notice PDF) |
| `counties_nc.transylvania_delinquent_tax` | `transylvania_delinquent_tax` | 203 | 0 | 194 | 100% | fresh | timeout | not run | |
| `counties_nc.transylvania_vacant` | `transylvania_vacant` | 5,332 | 0 | 0 | 100% | fresh | timeout | not run | |
| `counties_nc.wake_tax_foreclosure` | `wake_tax_foreclosure` | 4 | 0 | 4 | 100% | fresh | off-season | zero | |
| `counties_nc.wnc_rod_foreclosure_starts` | `wnc_rod_foreclosure_starts` | 0 | 0 | 0 | | **FILTERED** | OK 4 (all filtered) | OK 5 (all filtered) | OK 4-6 rows every run, all removed post-filter (Clay, Haywood, Yancey: none is in the 18-county footprint); slug is NOT in DATELESS_OK_SOURCES |
| `counties_nc.wnc_tax_foreclosures` | `wnc_tax_foreclosures` | 0 | 0 | 0 | | **TIMEOUT** | timeout | timeout | TIMEOUT in all three runs (Madison's lrcpwa.ncptscloud.com host ConnectTimeouts); a bounded wait_for was added 9/15 and has not been run since |

### counties_generic (6 registered, 4 with zero rows)

| Slug | Module | Rows | HOT | WARM | Seen 30d | Status | 9/8 | 8/29 | Evidence |
|---|---|--:|--:|--:|--:|---|---|---|---|
| `counties.multi_year_delinquent_tax` | `multi_year_delinquent_tax` | 457 | 0 | 241 | 42% | mixed | OK 2,100 | OK 2,131 | |
| `counties.nod_discovery` | `nod_discovery` | 5 | 0 | 3 | 20% | mixed | blocked | blocked | |
| `counties.sitemap_walker` | `sitemap_walker` | 0 | 0 | 0 | | **FILTERED** | OK 30 (all filtered) | OK 30 (all filtered) | OK 30 rows every run; 'OK with rows but 0 reached the dashboard post-filter' in all three logs; slug is NOT in DATELESS_OK_SOURCES |
| `counties_generic.arcgis_distress_layers` | `arcgis_distress_layers` | 0 | 0 | 0 | | **MIS-NAMED** | OK 8,772 (all filtered) | OK 8,794 (all filtered) | emits counties_generic.arcgis_distress.<layer>: 6,035 rows under 17 child slugs on the board. Run log shows a false 'all filtered' (8,772 scraped) because health is keyed on the parent slug |
| `counties_generic.epa_frs_sites` | `epa_frs_sites` | 0 | 0 | 0 | | **MIS-NAMED** | OK 268 (all filtered) | OK 269 (all filtered) | emits counties_generic.epa_frs.<program>: 188 rows (acres 109, sems 79). Log shows false 'all filtered' (269 scraped) |
| `counties_generic.state_contamination` | `state_contamination` | 0 | 0 | 0 | | **MIS-NAMED** | OK 5,572 (all filtered) | OK 5,572 (all filtered) | emits counties_generic.state_contamination.<layer>: 3,903 rows (nc_ust_incidents 3,254, nc_dam_safety 504, nc_inactive_hazardous 145). run_meta ALARM: PartialHarvest, lost nc_land_use_restrictions, 5,572 rows discarded by the scraper; the board rows came from an ingest script |

### newspapers (12 registered, 5 with zero rows)

| Slug | Module | Rows | HOT | WARM | Seen 30d | Status | 9/8 | 8/29 | Evidence |
|---|---|--:|--:|--:|--:|---|---|---|---|
| `counties.column_legal_notices` | `column_legal_notices` | 78 | 12 | 40 | 45% | mixed | OK 127 | OK 126 | |
| `newspapers.aiken_standard` | `aiken_standard` | 11 | 0 | 0 | 100% | fresh | not run | not run | |
| `newspapers.berkeley_independent` | `berkeley_independent` | 9 | 0 | 0 | 100% | fresh | not run | not run | |
| `newspapers.carolina_coast` | `carolina_coast` | 0 | 0 | 0 | | **NOT LANDED** | zero | zero | 8/28 run OK 6 rows, then ZERO on 8/29 and 9/8; 1 row on the 9/15 board, 0 now; slug is in DATELESS_OK_SOURCES |
| `newspapers.coastland_times` | `coastland_times` | 1 | 0 | 0 | 0% | mixed | OK 2 (all filtered) | OK 2 (all filtered) | |
| `newspapers.daily_courier` | `daily_courier` | 0 | 0 | 0 | | **DEAD** | zero | zero | run_meta REGRESSED (expected at least 1), ZERO in all runs; it yielded about 9 Rutherford notices before, so the page or parser changed |
| `newspapers.hendersonville_lightning` | `hendersonville_lightning` | 0 | 0 | 0 | | **FILTERED** | OK 5 (all filtered) | OK 5 (all filtered) | OK 5 rows every run, all removed post-filter (Henderson County notices, sale dates past); slug is NOT in DATELESS_OK_SOURCES |
| `newspapers.index_journal` | `index_journal` | 1 | 0 | 0 | 100% | fresh | OK 2 (all filtered) | OK 6 (all filtered) | |
| `newspapers.journal_scene` | `journal_scene` | 4 | 0 | 0 | 100% | fresh | not run | not run | |
| `newspapers.post_and_courier` | `post_and_courier` | 1 | 0 | 0 | 100% | fresh | OK 1 (all filtered) | OK 12 (all filtered) | |
| `newspapers.shelby_star` | `shelby_star` | 0 | 0 | 0 | | **EMPTY** | zero | zero | run_meta EMPTY (verified); Gannett site has no public-notice index |
| `newspapers.tryon_bulletin` | `tryon_bulletin` | 0 | 0 | 0 | | **EMPTY** | zero | zero | run_meta EMPTY (verified); legal notices are mixed into the news feed |

### reo (4 registered, 3 with zero rows)

| Slug | Module | Rows | HOT | WARM | Seen 30d | Status | 9/8 | 8/29 | Evidence |
|---|---|--:|--:|--:|--:|---|---|---|---|
| `national.gsa_realproperty` | `gsa_realproperty` | 0 | 0 | 0 | | **EMPTY** | zero | zero | run_meta EMPTY (verified); no NC/SC property active; the site's JSON API is login-walled so only the HTML index is read |
| `reo.treasury_seized` | `treasury_seized` | 0 | 0 | 0 | | **FILTERED** | OK 1 (all filtered) | OK 1 (all filtered) | OK 1 row every run, removed post-filter; slug is in DATELESS_OK_SOURCES |
| `reo.usda_rd` | `usda_rd` | 0 | 0 | 0 | | **FILTERED** | OK 1 (all filtered) | OK 1 (all filtered) | OK 1 row every run, removed post-filter; slug is in DATELESS_OK_SOURCES |
| `reo.vrm_va_reo` | `vrm_va_reo` | 25 | 2 | 16 | 96% | fresh | OK 173 | OK 176 | |

### city_websites (3 registered, 2 with zero rows)

| Slug | Module | Rows | HOT | WARM | Seen 30d | Status | 9/8 | 8/29 | Evidence |
|---|---|--:|--:|--:|--:|---|---|---|---|
| `city_websites.asheville_min_housing` | `asheville_min_housing` | 0 | 0 | 0 | | **DEAD** | zero | zero | 9/15 docstring: the page is informational, no published case registry; ZERO in all runs |
| `city_websites.charlotte_open_data` | `charlotte_open_data` | 2,910 | 0 | 641 | 100% | fresh | zero | zero | |
| `city_websites.search` | `cities` | 0 | 0 | 0 | | **DISABLED** | OK 183 (all filtered) | OK 147 (all filtered) | 9/15 docstring: garbage emitter (takes any address-shaped string on a search page); pre-disable runs scraped 147-183 rows and all were dropped |

## 6. Method and limits

- Registry: `foreclosure_scraper.scrapers._registry.discover()` imported in a subprocess, no scraper instantiated or run. Rows per source: one `iter_board_rows` pass. The board file was not loaded through `load_board`.
- A scraper's board `source` was matched to its registry slug by exact string. Prefix children were matched by hand (section 4). A scraper whose module builds `source` from a variable was checked by reading the module.
- Log evidence comes from `scraper.*` and `orchestrator.source_all_filtered` events. The 9/8 and 8/28 runs were under heavy memory pressure, so a TIMEOUT there is weaker evidence of a dead site than a ZERO_RESULT; several TIMEOUT scrapers were OK on 8/29.
- `source_all_filtered` is computed against that run's own final board, and none of those boards is the current one. It says the rows were removed in that run, not why. FILTERED reasons named in the table (footprint, past sale date, no county) are the likely ones, not measured per scraper.
- WALLED classifications use the current policy: CAPTCHA, login, 403 and click-through terms are walls, robots.txt alone is not (owner decision 2026-09-20). `rutherford_wildfire_tax` is the one scraper whose docstring wall is robots only.
- Not done: no live fetch of any source, so 'source has no current records' rests on the last logged run and the docstring date, not on today's page.
