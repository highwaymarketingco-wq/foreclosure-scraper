# Audit 2026-10-09: source completeness (does every source pull everything it can)

Area `source_completeness`. Public-safe: source slugs, counties, counts and commit ids only.
The per-source table is `docs/audit_2026-10-09/source_completeness_table.csv` (271 rows).

## 1. What was measured, and how

**Inputs (all read-only).**
- Registry (`scrapers._registry.discover()` on HEAD): **265 registered scrapers**, 31 disabled.
  225 run on the VM, 40 are residential-host readers (`source_split.residential_slugs()`) that run
  on the office Mac and reach the board through `national.stealth_handoff`. Six more board labels
  are manual or derived lanes (`liensnc`, `nc_ecourts_judgments`, `courtlistener.recap`,
  `counties_sc.sc_public_index_export`, `derived.probate_deed`, `manual.watchlist`). Four scrapers
  write under sub-labels (`counties_generic.arcgis_distress.*` 26 layers, `.state_contamination.*`
  3, `.epa_frs.*` 2, `counties_sc.sc_probate_notices.*` 3); the table rolls them up.
- The 10/7 published board (350,013 rows, 179 source labels): one streaming pass
  (`board_stream.iter_board_rows`, peak RSS 287 MB) for rows per source and per (source, county),
  listing types, `raw.pulled_sale.consecutive_misses`, `raw.carryover`, `raw.also_seen_in`.
- The gated VM run in progress (`logs/vm-run-20261008T014033.log`, pin d42058b3, role vm,
  stop_before_publish), read with grep only: 225 scrapers scheduled; 198 started, 181 finished,
  26 disabled, 1 off-season, 11 timeouts, 4 partial timeouts, 1 network timeout, 1 connection
  error; 5 carryovers; 26 `orchestrator.source_all_filtered`; per-county events; the run's own
  rolling `docs/source_history.json` (newest count = this run, the one before = the 10/6-10/7
  full run). Nothing on the VM was started, stopped or written.
- The Mac hand-offs: the one this run ingested (generated 2026-10-07 11:31 UTC, 27,888 leads) and
  the newer local one (2026-10-08 11:46 UTC, 51,730 leads), which is NOT in this run.
- A static scan of every scraper module for hard caps (slices `[:N]`, `*MAX/CAP/LIMIT/PAGES/DAYS/
  WINDOW/BUDGET*` constants and their env overrides, `max_pages`/`limit`/`per_page`, `timedelta(days=N)`
  windows, `range(N)` page loops): **992 hits in 245 files** (some false positives).
- **Deep dives on 147 sources**: the top 60 by lead value plus every source that returned 0, fell
  below half its previous count, timed out, or has a zero streak; four parallel reviewers (NC tax,
  SC tax, courts/notices/law firms, code/vacant/REO) and the lead. Per source: the source's own
  total or page count (one polite sample, 2 s or more between requests to a host), every cap in
  the code and whether it binds (133 caps examined, 45 bind, some by design), fields offered vs
  kept (including `web_artifact.RAW_KEEP`), rows dropped by parsing, layout changes. Lead value =
  class weight (foreclosure and lis pendens 5, probate 4, tax, divorce, bankruptcy and jail 3,
  code and REO 2, elderly and other 1, environmental and listing 0.5) x sqrt(rows).

**Table summary (the CSV).** By lead class (own board rows on 10/7): tax 94 sources / 157,071
rows, code 18 / 57,271, environmental 6 / 68,632, lis pendens 18 / 21,522, probate 21 / 10,064,
divorce 1 / 5,777, elderly 1 / 4,322, bankruptcy 2 / 1,051, foreclosure 37 / 946 (most foreclosure
rows merge into other sources' rows), REO 9 / 1,059, jail 1 / 11, listing 8, other 55. Rows on
the board: 149 table rows carry their own rows, 122 carry none (31 disabled, new 10/7 sources not
yet published, merged into another source's row, or zero by a documented cause). Flags against the
previous run: zero now after rows before 9, below half 12, timeout 11, partial timeout 4, zero
streak (two runs or more) 23, below expected_min 9. Verdicts: complete 54, fixed 43, open 62
(wall 22, not enough time 14, owner decision 8, rate limit 7, no free source 6, shared-file
change 5), disabled 28, not deep-dived 84 (below the value line and not flagged).

**Repeatable.** `scripts/audit_checks/source_completeness.py` (three invariants, below) runs in
`scripts/audit_suite.py`; on the 10/7 board: 350,013 rows, 57 s, 197 MB.

## 2. Defects found and fixed

All fixes are in scraper modules (no shared file was edited), each with a fixture test that fails
on the old code; targeted tests: 391 passed in the 45 touched test files, 3,915 passed in the 216
other test files that name a touched module. Live proofs are samples (counts only).

**A. A timeout threw away rows already read (the largest class).**
- `counties_sc.qpaybill_delinquent_roll` (SC tax, 29 counties, 33,180 board rows). The fixed 900 s
  soft timeout let the first 11 counties finish (name order, 4 at a time: 7,028 parcels on 10/8,
  7,118 and 8,027 the runs before), then cancelled fetch(); the other 18 counties' sweeps kept
  requesting from their hosts until 55 minutes after the start and every row they read was
  dropped. On the 10/7 board 25,314 of its 33,180 rows had not been re-read since 9/10-9/15 (two
  consecutive misses; board_persist drops a row after four), and the staged detail pass (follow-up
  6 of the 10/7 extraction audit) never ran because it comes after the sweep. Fix 708630b7:
  timeout = one 480 s county bound per wave of 4 counties + a 900 s detail budget + 120 s (4,860 s
  for 29 counties; `QPAYBILL_ROLL_TIMEOUT_S` overrides); counties start stalest first (median board
  `last_seen`; on the 10/7 board the 19 stale counties now lead); a scraper-level cancel ships what
  unfinished counties read and cancels their sweeps; the detail pass is bounded and keeps details
  parsed before its deadline; the prefix walk start rotates by day so a per-county timeout does
  not cut the same letters every run. Test `tests/test_qpaybill_full_sweep_coverage.py` (9).
  Run cost: the sweep took ~55 minutes on 10/8 (it ran that long anyway, unowned) plus at most
  15 minutes of detail pages, inside the 3 h scrape-phase budget; the 10/8 scrape phase itself
  ended 34 minutes after its start, so the phase gets about 40 minutes longer.
- Same class, smaller: `counties_nc.wnc_rod_foreclosure_starts` (Yancey's 21 minutes zeroed the
  run; ea1ced96), `national.hud_homestore`, `national.freddie_homesteps`, `national.usda_properties`
  (detail pages added 10/4 made them time out with 0; with a forced 20 s timeout: 32 and 27 rows;
  d69dc3ec), `national.cash_buyer_deeds` and `national.usmarshals_realproperty` (019c3fbf),
  `public_notices.funeral_home_rss` (one slow host cost all 11; a896a642), `law_firms.alaw`
  (partial, c074ed87), `national.homeharvest` and `national.distressed` (c743bdc6, f99e0de7),
  `counties_sc.laurens_overage_claims` (ships page by page; ad240e9f), `counties_sc.spartan_weekly_legals`
  (d73f8667), `counties_sc.dillon_delinquent_tax` (its 60 s timeout was shorter than its own
  request timeouts; 1d2a2141), `counties_sc.berkeley_paystar_tax` (600 s read ~2,379 of ~3,036
  invoices; 900 s, one row per parcel with every unpaid year; c74c9a20),
  `national.courtlistener_bankruptcy` (one 600 s budget shared by four courts cut SC: 3,386 of
  4,579 filings; fair share per court, 780 s; 091c0094).

**B. A cap or window bound and cut rows.**
- `counties.column_legal_notices`: one 250-row page per (county, type, 120 days) kept the newest
  250 (Guilford estate notices 250 rows / 79 notices -> 397 / 116); the window is now split until
  every row is read (1e86afe3).
- `counties_sc.sc_probate_notices`: 120 documents a paper applied before de-duplication; Pickens
  207 posts -> 120 read; Gaffney read through the plugin's public route, 212 -> 334 (3eb93c16).
- `counties_sc.sc_probate_net`: only page 1 (20 rows) of each name search; Charleston 'Smith' 20
  -> 98 estates (68431e64). It now also drops closed estates over two years old (owner decision
  below).
- `public_notices.echovita_obituaries`: 12 listing pages a state bound on the first run (576 =
  2 x 12 x 24); 40 (20f91df5). `counties_sc.anderson_master_in_equity`: 6 results PDFs held 5 of
  9 eligible; 12, plus the Sale-List-Results PDFs and the sale hour (7f8bfafa, fdb34eb7).
  `counties_sc.dorchester_billtrax_delinquent_tax`: one bad record skipped its whole 250-bill
  window every run; now only that record (2fdaac38). `national.courtlistener_civil`: paged the whole
  civil docket and rejected '290 Real Property' cases; server-side filter, 0 -> 8 rows (6ec6259d).
- `counties_nc.nc_ecourts_lis_pendens` and `_divorce`: caps do not bind (80,061 of 90,000 and
  104,580 of 120,000 hits on 10/8); the loop now says when they do; divorce keeps judgmentType and
  caseCategoryKey (69c15bb6). The 10/7 to 10/8 hand-off jump (13,654 -> 27,407) is the new
  judgment-lien lane (375b4b72), not a window change.

**C. A parser dropped rows or fields it had fetched.**
- `counties_nc.albemarle_observer_tax_lists`: Pasquotank's list was fetched every run and never
  parsed: 0 -> 1,806 leads (7153eb15).
- `counties_nc.nc_county_pdf_delinquent_tax`: first-wins kept one line per id; Catawba principal
  $4.68M -> $4.70M on 28 accounts with 2+ lines, McDowell 4 (bf1fccdb).
- `counties_sc.greenville_delinquent_tax` (1,137 -> 1,148 rows; 50038bfc) and the shared SC table
  guard `_sc_tax_table.is_label_row` (owner names holding 'owner' or 'office' read as page
  furniture; ad0af113, `tests/test_sc_tax_table_label_row_owner_words.py`).
- `counties_nc.nc_ptscloud_delinquent_tax`: Forsyth sanitation liens (BILL_TYPE SAN) dropped; 603
  roll rows now carry them ($3.05M), not summed into the tax due (0630c787).
- `counties_sc.florence_delinquent_tax` owner_name 0 -> 978 of 978 (fc9dafe2);
  `counties_nc.nc_heir_estate_parcels` value, acreage, sale, legal, deed and record-card fields
  (f1e05d86); `counties_generic.epa_frs_sites` county read from suffixes, city or one close spelling,
  3,714 -> 3,783 of 3,815 kept (c1588339).

**D. An outage read as an empty source.**
- `counties_sc.qpaybill_delinquent_roll` Abbeville: the tenant redirects every request to the
  vendor's Info.aspx ('Please try again'); 36 clean queries logged parcels=0 errors=0 on 10/8
  (542 parcels read on 10/6). A redirect to Info/GenericErrorPage/Error is now an outage
  (a89e66ea; live: Abbeville raises, Lee reads).
- Gemini 503 overload read as an empty scanned list (`laurens_overage_claims`, `sc_flc`,
  `cherokee_delinquent_tax`; ad240e9f, unit-tested only: no Gemini key on the Mac).
  `law_firms.rogers_townsend` clean zero on a failed report (8470e9dd);
  `public_notices.publicnoticesc_estates` all-failed run reported as clean zero (cf044d6f);
  `counties_sc.greenwood_corebtpay_delinquent_tax` now stops in 12 requests when the portal lists
  only paid bills instead of 30 minutes (cd7185a1).

**E. The source moved or changed.**
- Madison NC tax-foreclosure page (the 'Madison endpoint fix'): `wnc_tax_foreclosures` followed
  the vendor app (lrcpwa) and timed out; it reads the county's own Tax Foreclosure Sales page now
  (no sale posted today: a real 0; e9684e7f). New Hanover's CSV endpoint works and the list is
  complete (1,325 parcels = 1,325 leads); no change needed.
- York and Orangeburg overage lists: the county Cloudflare front now refuses a bare 'Mozilla/5.0'
  identity; a complete browser User-Agent gets 119 and 446 rows from the Mac (7b5369ac; the VM
  is unverified). Pickens 'WeekOne2027' layer wired (eee6b69c); Cherokee reads the list its own
  page links (ad240e9f); Georgetown FLC page retried once (f3798eba).

**F. Wrong or unusable data (found while measuring).**
- `national.homepath_json` published ordinary MLS listings as Fannie Mae REO: REO only now,
  2,098 -> 61 rows (aef7c291).
- `counties_nc.transylvania_vacant` used the legal location text as street_address: first page
  2,000 -> 4 street addresses (70079e4f).
- Parcel ids nulled by validation (20,041 rows in the 10/8 run): Durham demolitions use the
  10-digit PIN on the same row, 0 -> 206 (83a2bb95); Burke storm damage and Asheville STR permits
  keep the layer's own point (456 and 657 rows) so the geo parcel step can find the PIN;
  `rutherford_wildfire_tax` publishes the PIN (893 of 896) once a shared alias entry lands
  (62bc81dc, dormant until then). Guilford, Beaufort and Pitt short ids are the counties' own
  numbers: nothing better exists in the source.
- `national.seeclickfix` stored the complaining resident's name block: never kept now (c9fa2365).
- Politeness: `foreclosure_dot_com` stops at the first block (37 URLs x 3 retries before;
  591220eb); TownNews papers stop at the first 429 (095743c6); Gannett obituary pages paced on the
  shared edge (a13c8311). Fixtures with real names from earlier commits were replaced with invented
  ones (78cfb679, d27b43f9).

**Invariants (scripts/audit_checks/source_completeness.py, daa8e2dc, `tests/test_audit_checks_source_completeness.py` 9).**
- `source-county-refreshed`: a (source, county) cell with 20+ rows where more than half the rows
  missed 2+ runs in a row or are carryover replays. 10/7 board: **53 cells, 43,979 rows** (qPayBill
  18 counties, SC DEW lien registry 12, SC Public Index 4 + 4, CourtListener bankruptcy 3,
  foreclosure.com 2, and one each for gannett, York overage, Spartanburg delinquent, sc_flc, Oconee
  forfeited land, Greenville delinquent, Georgetown, Rutherford wildfire, Rutherford tax,
  multi-year delinquent). It would have caught the qPayBill cut on 9/22.
- `source-county-floor`: a high-value (source, county) cell below half its rows on the baseline
  board, or a high-value source with no rows (baseline `docs/audit_2026-10-09/source_completeness_baseline.json`:
  140 sources, 421 county cells from the 10/7 publish; `--write-baseline` after an accepted publish).
  It catches a county that dies silently (Abbeville) once its rows age out.
- `source-cap-not-hit`: a count equal to a scraper's hard cap (heir/estate parcels per county,
  Greenville MIE adverts; the cap values are read from the modules).

## 3. Open items, with the reason

**Walls (recorded; nothing bypassed).** New card `dc_ip_block` in `docs/walls_register.json`:
Rutherford NC tax roll and foreclosure pages (also `national.nc_upset_bids`), Edgecombe, Lee
(`nc_tax_lien_ads`, about 2,700 leads) and Avery answer 403 to the VM's datacenter address on every
run and 200 to a plain request from the office Mac. Spartanburg (`spartanburg_delinquent_tax` 2,171
rows from the Mac, `spartanburg_flc`, `sc_flc` Spartanburg documents, `spartanburg_master_in_equity`)
is the same, card `spartanburg_site` updated; `spartanburg_master_in_equity` now reads hand-saved
PDFs from `SPARTANBURG_MIE_PDF_DIR` (6402fe7e). Exact owner steps are on the cards. Others:
`foreclosure_dot_com` (AWS 'VPN or proxy' 403 from both hosts), `newspapers.mecklenburg_times`,
NC eCourts 'Multiple' cause rows (13.8% of hits; the cause is behind the CAPTCHA), SC Public
Index (stealth lane, record only: `national.sc_public_index` 1,759 -> 280 on the 10/8 hand-off is
the 10/7 Charleston window rewrite), NC DEQ land-use layer (sign-in token), LiensNC (login, the
owner's own lane; the 10/8 hand-off holds 11,483 rows not in this run), detail pages of
ncnotices/scpublicnotices (reCAPTCHA).
**No free source:** McCormick FLC (print only), Greenwood corebtpay (paid bills only until
January), Anderson and Dillon sheriff sales, Asheville code layer (frozen since 2018),
`law_firms.finkel` PDFs gone.
**Rate limit:** Catalis/Avalon SC tax (`sc_catalis_delinquent_roll`: at the safe 8 s pace a run
reaches part of Pickens only; Chester, Hampton, Fairfield and Aiken never), TownNews papers (429
when read in the same minute), two obituary hosts.
**Decided (2026-10-08):** the datacenter-blocked readers are NOT moved to the Mac lane: a firewall
block on the server's address is a wall, so they stay a person's lane (cards `dc_ip_block`,
`spartanburg_site`). **Owner decisions:** retire or date-gate `charleston_delinquent_tax` (it ships last year's list);
`FORECLOSURE_MECKLENBURG_DELINQUENT=1` (about 29,000 parcel-matched rows); HUD Section 8 scope (250
of 1,312 NC/SC properties emitted); whether state-only bankruptcy rows belong on the board (the RSS
lane ships them, the CourtListener lane drops them: 3,767 countyless national rows dropped on
10/8); `sc_probate_net` two-year age cut (`SC_PROBATE_NET_MAX_AGE_DAYS=0` turns it off); purge the
8,288 stale `sc_dew_lien_registry` rows; SeeClickFix (robots names our crawler); SC UST detail
pages (carry operator phones).
**Not enough time / not measured:** per-county 480 s still binds for about 15 large qPayBill
counties (they ship partial rolls; rotation spreads the cut); `nc_its_public_tax` reads 3 tax years
while older unpaid years exist (Onslow 2022: 3,512 records; `ITS_TAX_YEARS_BACK=6` is an env
change, yield unmeasured); Buncombe delinquent and elderly, McDowell probate, Transylvania
delinquent, Iredell, Cleveland, nod_discovery, nc_rod_substitute_trustee, Charleston EnerGov (works
from the Mac, connection dropped on the VM), Williams, `publicnoticesc_estates` live after-run.
**Shared-file changes.** Applied after the coordinator's go: `SNAPSHOT_REO_SOURCES` gains
`homepath_json` (1ec2638b); the Rutherford wildfire PIN alias in `parcel_alias` and `board_persist`
(d3ce856e); `http_client.get_text` retries only transport errors, timeouts and 5xx (82860c43). The
coordinator wires main's `source_all_filtered` labels, the `bk_property` cap and
`DATELESS_OK_SOURCES`. Still open: `daily_courier` probate branch, the bankruptcy property enricher
for `courtlistener_adversary`.

## 4. Outside this area (one line each)
- board_persist marks every prior-only row 'presumed_withdrawn', including standing tax rolls (25,314 qPayBill rows on 10/7).
- 64 qPayBill rows carry a board county different from the source's own county (a Lexington parcel labelled Oconee, and so on).
- `national.sc_public_index`'s 1,999 board rows carry no owner, defendant, address or parcel.
- `validation.parcel_too_short` nulled 20,041 parcel ids in the 10/8 run (10,585 PTS Cloud, 6,092 county PDF lists).
- The gated run ingested a 14-hour-old Mac hand-off; the 10/8 one (51,730 leads) is not in it.
- Charlotte closed code cases stay on the board (1,641 rows last seen 9/15-9/22); retirement logic.
- Transylvania rows already published keep the legal text as street address (the prior wins in merge): a board scrub.
- `enrich_bankruptcy_property` is cut by main's 900 s cap while its own budget is 1,800 s.
- 36 Kania rows with a future upset-bid deadline are dropped by `_active_only` on their old sale date.
- `tests/test_seeclickfix.py` makes a live network call to a robots-named host.

## 5. Not verified
Full live runs of the fixed scrapers (samples only, under the per-host rule); the qPayBill sweep
time with the new order (bounded by the computed timeout, not measured end to end); the VM side of
the York/Orangeburg User-Agent fix; Gemini-dependent fixes (no key on the Mac); the 84 sources
below the value line that were not deep-dived; Mac-lane sources beyond their hand-off counts.
