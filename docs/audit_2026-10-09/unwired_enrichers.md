# Audit 2026-10-09: unwired_enrichers (D11: 30 modules only scripts ran, 32 frozen board keys)

Counts were computed on 2026-10-08 against the 10/7 published board (350,013 rows), streamed with
`board_stream.iter_board_rows` (two passes, 281 MB peak, about 30 s each) and the new invariants
(`uv run python scripts/audit_suite.py --only unwired_enrichers`: 30 s, 326 MB). Nothing ran on the VM.
Live checks were 7 sampled requests (one at a time, 3 s apart): 5 to the two wetlands hosts, 2 to the Realtor research files.

## 1. The 30 modules: what each does, what it costs, what it is worth, the decision

Board = rows of the 10/7 board carrying the module's key, and how old. "Wire" lines are in section 3.

| Module | What / source | Cost per run | Worth to a lead | Board | Decision |
|---|---|---|---|---|---|
| dnc | Do Not Call scrub of every phone; local files only | 1 s + 0.33 s per million registry lines (measured) | calling at all (TCPA) | 0 of 81,294 phone rows scrubbed | **WIRE** UE1 (rewritten, below) |
| property_category | dashboard category (foreclosure / pre-foreclosure / tax / distressed); offline | ~3 s / 350K rows (measured on 5,001) | the dashboard's category filter and badge | 155,116 rows (9/16); 194,897 rows have none; 4.3% of a 1-in-50 sample stale | **WIRE** UE3 |
| source_consistency | self-contradiction qa_flags; offline | in the 3 s above | flags a row whose own fields disagree | 389 of 420 rows that trip a check lack the flag: enrich_board_qa reassigns qa_flags every run | **WIRE** UE3 |
| flood_zone | FEMA NFHL zone; free ArcGIS, 1 call a row | 0 calls (mirror) | flood risk on a flip | 131,221 rows (9/16 backfill); 34,473 disagree with or lack the run's raw['flood'] (18,428 stored failures) | **WIRE as a local mirror** of raw['flood'] (enrichment_flood already reads the same layer); its own fetcher is not run |
| hud_fmr | HUD Fair Market Rent; HUD API with token, one table | 0 calls in the run (cached table); refresh about 100 calls | rent floor for a rental / Section 8 exit | 26,550 rows (FY2026 table of 8/20); 259,442 of 285,270 covered rows lack it or differ | **WIRE** UE1 (offline) + **SCHEDULE** the table refresh monthly on the Mac (`scripts/refresh_fmr_cache.py`) |
| septic_status | Buncombe septic permits; one county ArcGIS layer (~80K rows, ~40 pages) | layer at most weekly (cached, data/cache/septic_buncombe.json.gz) | adverse / stalled septic on rural and land deals | 779 rows, none dated; 7 land_distress rows with no adverse block | **WIRE** UE1 (apply from cache) + UE4 (weekly refresh) |
| bt_appraisal_card | assessor appraisal-card PDF, 14 NC counties; free portal | <=300 cards, <=600 s | heated sqft (the ARV gap), appraised value, recorded sale | 39 rows; 3,834 rows eligible (no sqft) | **WIRE** UE2 (before valuation) |
| usfws_wetlands | NWI wetland polygons near the point | <=5,000 points, <=600 s (0.25 s a query measured) | buildability of land and lots | 0 rows; 112,216 rows eligible (HOT/WARM or land) | **WIRE** UE4; the module's www.fws.gov address answered 403 "excessive crawling" to one request, the public NWI service answers |
| census_geocoder | Census geocoder per row | 1 call a row | tract / FIPS | 0 rows | RETIRE: the run geocodes (enrichment_geocode); its merge shifts results onto the wrong rows after a miss |
| charlotte_code, greensboro_code | city code cases | up to 3 calls a row | code violations | 0 | RETIRE: FeatureServer URL without /query (never a case), 403 workaround headers; the run's enrichment_code_enforcement covers code cases |
| email_extract | e-mails found anywhere in raw | offline | owner e-mail | 46,963 scan blocks, 46,961 classed "other" | RETIRE: owner_email_of() reads the primary sources at read time; the scan's class bug made the copy useless |
| envirofacts | EPA facilities within 1 mile | 1 call a row | contamination nearby | 0 | RETIRE: duplicates enrichment_environmental; unit and marker bugs |
| fbi_ucr | county crime | up to 11 calls a row, key needed | county context | 0 | RETIRE: wrong rate metric, {} stamped forever |
| free_phones | people-search phones | stealth browser | phone | (owner_phone shared) | RETIRE: CAPTCHA 403 wall; those phones are do_not_dial by policy |
| irs_lien | CourtListener federal tax liens by name | <=300 calls | senior lien | 0 | RETIRE until rebuilt: wrong name order, dead keywords, no amount; a false lien would reach equity |
| lexington_assessment | Lexington SC value + 4%/6% ratio | 1 call a row | value, owner-occupancy | 1,159 rows (9/13), kept | RETIRE: parcel_cache (lex-co layer) and the qPayBill roll already carry both |
| marriage_license | spouse from the ROD index | <=50 searches | heirs / divorce | 27 rows, kept | RETIRE: the same search enrichment_aumentum_rod runs, through curl_cffi impersonation |
| nc_doj, nc_sos | AG alerts / SOS entity | 3 calls a row | entity owner contact | 0 | RETIRE: 403 workarounds; nc_doj would flag every NC row; the SOS lane runs on the Mac |
| nc_onemap | NC parcel / flood / zoning | 3 calls a row | duplicate | 0 | RETIRE: same layers the run reads elsewhere |
| ncpts_lrc | NC land-records CAMA | 2 calls a row | value, sqft | 0 | RETIRE: house-number-only search writes another parcel's owner and value; enrichment_lrcpwa_parcel reads the same host by parcel |
| ocr | notice PDF OCR (EasyOCR) | heavy (torch) | case facts | 2,220 rows (8/20), kept | RETIRE: enrichment_doc_ocr reads the same notices in the run |
| probate_search | probate case lookup | stealth browser | estate lane | (probate shared) | RETIRE: F5 anti-bot workaround (BRIEF); invalid SC URL, NC false positives would overwrite raw['probate'] |
| realtor_data | county market TSV | 1 download | liquidity context | 0 | RETIRE: URL answers 404 (checked); nothing reads housing_market |
| redfin_datacenter | ZIP market TSV | 1 download | liquidity context | 0 | RETIRE: dead URL; live file is a 1.5 GB gzip |
| rod_name_index | SC ORS name index | <=15 lookups | deeds | 7 rows, kept | RETIRE: curl_cffi impersonation; enrichment_generic_rod reads the same counties (FORECLOSURE_SC_ORS_ROD=1) |
| sc_voter_xref | NC voter phone for SC owners | 565 MB index | phone | 1,458 phones: 3 corroborated, 1,172 unverified, 283 contradicted | RETIRE: the phone gate makes the rest do_not_dial |
| surface_contacts | phones/e-mails copied from raw | offline | contact | (shared keys) | RETIRE: puts agent phones in owner_phone, which stops the voter-file owner match on that row |
| usda_ers | county RUCC / poverty | 3 downloads | context | 0 | RETIRE: FIPS padding bug gives {} on every row; census_demographics covers income |

Retired keys stay on the board as they are (never deleted); the modules carry a RETIRED note at the
top of their docstring and their reason in `deploy/oracle/run_profile.json` `unwired_allowlist`.
Readers of the retired keys (grep of src/, scripts/, docs/dashboard.js): only RAW_KEEP, api_server's
keep list, block_binding's audit list and `export_board`'s envirofacts column (blank since the module
wrote a bool, now documented); no scorer, gate or dashboard renderer reads any of them.
Frozen keys left (24, `frozen_keys_known` with a reason each in `frozen_keys_why`): those of the
retired modules, workflow_engine's four (retired, 0 rows) and two operator lanes outside the run
(bankruptcy_petition from the petition sweep, contact from the contact import; 0 rows each).

## 2. Defects found and fixed

| # | Defect, scale | Fix | Test | Invariant |
|---|---|---|---|---|
| U1 | DNC: no phone on the board scrubbed (0 of 81,294 phone rows); the loader cached "no file" as an EMPTY registry, so a second call in one process scrubbed every new phone "clear"; an "unverified" entry was never re-scrubbed once a registry arrived; no 31-day rule; the whole registry loaded into memory | enrichment_dnc rewritten: registry streamed against the board's phones (0.33 s per million lines), statuses clear / on_registry / on_internal_dnc / unverified (+ do_not_dial / not_owner_contact), company list data/internal_dnc.csv on every run, re-scrub after 31 days or a new registry file, a read cut short or a file under 1,000 numbers never proves clear; call_ready reads the status (one DNC_BLOCKED set; a clear older than 31 days reads unverified) | tests/test_dnc_scrub.py (14) | unwired-dnc-every-phone-scrubbed, -status-valid, -call-ready-agrees |
| U2 | property_category missing on 194,897 rows, stale on 4.3% | wired UE3 | tests/test_tail_extras.py | unwired-property-category-present, -current |
| U3 | source-consistency flags wiped by enrich_board_qa each run (389 of 420) | wired after board_qa (UE3) | same | unwired-source-consistency-flags |
| U4 | flood_zone disagrees with raw['flood'] on 34,473 rows | local mirror (UE1) | same | unwired-flood-zone-mirrors-flood |
| U5 | hud_fmr on 26,550 of 285,270 coverable rows; its census_rent copy blocked the ACS rent enricher; a failed refresh saved an EMPTY table for 30 days | offline apply of the cached table on every covered row, no census_rent write (UE1); refresh never saves an empty table; `scripts/refresh_fmr_cache.py`; refdata_check lists the table | same | unwired-hud-fmr-matches-table |
| U6 | septic blocks undated and never cleared (779 rows; 7 orphan land_distress) | weekly cached layer, applied every run, cleared when the parcel has no case (UE1/UE4) | same | unwired-septic-current |
| U7 | bt cards: misses never recorded (the same 300 rows every run) | "no_card" recorded, 30-day recheck, HOT/WARM first (UE2) | same | unwired-bt-card-applied |
| U8 | wetlands: dead address (403), list shape export_board could not read | public NWI service, 60 m radius, {has_wetlands, features, checked_at} (UE4) | same | unwired-wetlands-shape |
| U9 | a retired script run by hand would silently re-grow a frozen key | baseline counts | tests/test_audit_checks_unwired_enrichers.py | unwired-retired-keys-not-growing |

All local tail steps were run twice on a 5,001-row sample of the real board: the second pass changed
0 rows. Under `reconcile_board.network_blocked()` they run without a connection (test).

## 3. Wiring for the lead (main.py, `run_enrich_tail`; anchors are code text)

**UE1** directly before `    # Call-ready gate (call_ready.py, docs/call_ready.md): lane, tier, reason and unmet conditions per`:
```python
    # DNC scrub of every phone (enrichment_dnc; audit 2026-10-09 unwired_enrichers): data/dnc_registry.csv
    # and data/internal_dnc.csv when present, 31-day re-scrub; no file = every phone 'unverified'.
    try:
        from .enrichment_dnc import enrich_dnc_scrub
        enrichment_stats["dnc_scrub"] = enrich_dnc_scrub(enriched)
    except Exception:
        log.error("dnc_scrub.failed", traceback=traceback.format_exc())
    # flood_zone mirror, HUD FMR and Buncombe septic from local tables (no network)
    try:
        from .enrichment_tail_extras import enrich_local_pre_gate
        enrichment_stats["tail_extras_local_pre_gate"] = enrich_local_pre_gate(enriched)
    except Exception:
        log.error("tail_extras_local_pre_gate.failed", traceback=traceback.format_exc())
```
**UE2** directly before `    # SC DEW lien cross-reference`:
```python
    # BT appraisal cards (sqft / value / last sale) before the valuation loop reads them
    try:
        from .enrichment_tail_extras import enrich_network_pre_value
        s = await _await_capped(enrich_network_pre_value(enriched), "tail_extras_network_pre_value", default_s=660)
        if s:
            enrichment_stats["tail_extras_network_pre_value"] = s
    except Exception:
        log.error("tail_extras_network_pre_value.failed", traceback=traceback.format_exc())
```
**UE3** directly before `    # Classify source links (record vs search-only) so the dashboard never shows a dead link.`:
```python
    # self-contradiction flags (enrich_board_qa just reassigned qa_flags) and the property category
    try:
        from .enrichment_tail_extras import enrich_local_after_qa
        enrichment_stats["tail_extras_local_after_qa"] = enrich_local_after_qa(enriched)
    except Exception:
        log.error("tail_extras_local_after_qa.failed", traceback=traceback.format_exc())
```
**UE4** directly before `    _geo_results = await _gather_phases(_geo_flag_phases)`:
```python
    try:
        from .enrichment_tail_extras import enrich_network_geo
        _geo_flag_phases["tail_extras_geo"] = enrich_network_geo(enriched)
    except Exception:
        log.error("tail_extras_geo.failed", traceback=traceback.format_exc())
```
and directly after `        enrichment_stats["usps_vacancy"] = _uv`:
```python
    if _geo_results.get("tail_extras_geo"):
        enrichment_stats["tail_extras_geo"] = _geo_results["tail_extras_geo"]
```
Then: empty `AWAITING_MAIN_WIRING` in scripts/reconcile_board.py and drop the strict xfail markers on
`tests/test_reconcile_board.py::test_awaiting_steps_are_wired` and
`tests/test_prerun_gate.py::test_the_real_profile_has_nothing_pending`; tidy `unwired_wire_pending`
in run_profile.json (the gate prints which entries are now wired).

## 4. Budgets and run time

| Step | Kind (reconcile) | Budget | Measured / bound |
|---|---|---|---|
| UE1 dnc | local (runs) | DNC_SCRUB_MAX_SECONDS 600 for the registry read | 1 s for 350K rows without a file; +0.33 s per million registry lines |
| UE1 local_pre_gate | local (runs) | none needed | 4.4 s per 350K rows |
| UE2 network_pre_value | network (stub) | TAIL_BT_CARD_BUDGET_S 600, cap 660 | <=10 min, sequential |
| UE3 local_after_qa | local (runs) | none needed | 3.3 s per 350K rows |
| UE4 network_geo | network (stub) | TAIL_GEO_EXTRAS_BUDGET_S 600 inside the group's 900 s cap | <=10 min, concurrent with FEMA / OZ / USPS |

Added run time: about 10 s of local work plus the registry read (about 10 s for 30 million numbers),
plus up to 10 min (UE2) and up to 10 min overlapped with the geographic group (UE4): at most about
20 min, and no step can hold the run past its cap. Memory: the new blocks measure 1.2 KB (hud_fmr),
0.8 KB (property_category), 0.66 KB (dnc_scrub) and 0.6 KB (flood_zone) per row in Python, about
+0.5 GB on the VM for the rows that gain them (+2.7% of the 19.7 GB peak); about +90 MB of plain board.

Gate: `prerun_gate` `unwired` and `frozen-keys` now FAIL as "wiring pending" until UE1-UE4 are in
(they name the lines), and `unwired` also checks that run_enrich_tail calls the five steps
(`tail_calls_required`): call_ready imports a DNC helper, so the import graph alone already counts
enrichment_dnc as reached. vm_lib.sh needs no change (every new knob has a code default). The
operator copies `data/dnc_registry.csv` (and `data/internal_dnc.csv`) and `data/fmr_cache/` to the VM
with the reference data.

## 5. Open items
- DNC registry and company list files: the owner is getting them; until then every phone stays
  unverified exactly as before (owner).
- HUD token on the Mac for the monthly refresh; the table is FY2026 (8/20) and FY2027 takes effect
  October 1 (owner: run `scripts/refresh_fmr_cache.py --force`, then copy data/fmr_cache).
- The wired steps have not run on the VM or a checkpoint (VM read-only for this audit); the network
  steps ran only against fakes in tests, plus the 7 sampled live requests above.
- property_category's own rules have two bugs left as they are (an HOA lien alone makes a row
  "foreclosure"; "fp" is a substring match); irs_lien needs a rebuild before any wiring.

## 6. Outside this area
- `export_board.py` reads `envirofacts.facilities_count` (always blank) and `census_rent.median_gross_rent`
  (blank for HUD-sourced blocks).
- `scripts/enrich_board.py` still runs every retired module (the retired-keys invariant catches it).
