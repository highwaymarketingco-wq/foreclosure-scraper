# Deed-index scoping for the 18 core counties (2026-09-20)

Decision document. Nothing was built. The only file written is this one.

## Read this first

**Core county list.** 18 counties, taken from `NC_COUNTIES` and `SC_COUNTIES` in `src/foreclosure_scraper/config.py`, which matches Part C of `docs/MASTER_SOURCE_AND_COUNTY_REGISTER.md` and the loop in `scripts/county_coverage_matrix.py`.

- SC (7): Spartanburg, Anderson, Pickens, Oconee, Cherokee, Union, Laurens.
- NC (11): Rutherford, Cleveland, Henderson, Polk, Gaston, Buncombe, Transylvania, McDowell, Lincoln, Mitchell, Burke.

**Correction to the brief.** `repeat_tax_loss` is not in `enrichment_derivation_flags.py` (that file holds `free_and_clear`, `tired_landlord`, `divorce`). It lives in `src/foreclosure_scraper/enrichment_repeat_tax_loss.py`. Its first live run (2026-09-17) tagged 0 rows. This scoping confirms the cause (no source carries real deed instrument types). It also found four defects downstream of the data that would keep the signal at 0 even after deed data arrives, and one defect in the CCHS feed that drops trustee's deeds. All five (F1 to F5) are listed in section (d) and are cheap to fix.

**What was done.** Docs read first, then light live probing: `robots.txt` on every recorder host, landing pages, search-form pages, two CCHS instrument-type searches (Burke, Cleveland, 2025 window), and read-only ArcGIS queries on Buncombe's public assessor tables. All requests were plain GETs at 2 to 3 second spacing. Exact request counts are in the appendix.

**What was not done.** No POST of any kind. No disclaimer accepted through a form or button. No login attempted. No CAPTCHA seen or attempted. No board load, no backfill script, no git commit, no edit to any other file. Where a search needs a POST or a disclaimer acceptance (AcclaimWeb, Logan, Aumentum, Gaston), the row says "not exercised today" and rests on the repo's own dated evidence.

**Project rule note.** `CLAUDE.md` permits anti-bot techniques for free sources. This task's rules are stricter (no CAPTCHA, WAF or rate-limit evasion), so the stricter rule governs here. `robots.txt` is treated as a wall the way `src/foreclosure_scraper/rod/kofile.py` already treats it (see decision D1).

---

## (a) Summary

### Counts by verdict (18 counties)

| Verdict | Count | Counties |
|---|---|---|
| BUILD-READY | 3 | Burke NC, Cleveland NC, Pickens SC |
| BUILD-WITH-WORK | 4 | Buncombe NC, Gaston NC, Transylvania NC, Polk NC |
| WALLED | 11 | robots.txt `Disallow: /` (9): Spartanburg, Anderson, Oconee (also needs an account), Union, Laurens, McDowell, Mitchell, Henderson, Lincoln. Login (1): Rutherford. Terms of service (1): Cherokee |
| NOT-FOUND | 0 | none |

### Yield

"Loss-class deeds" means the instruments that prove an owner lost a parcel: trustee's deed (NC power of sale), commissioner's deed (NC tax foreclosure and judicial sales), sheriff's deed, master's deed (SC judicial), and SC tax deed. NC has no separate TAX DEED instrument type in the two indexes I read; tax foreclosure deeds appear as commissioner's deeds.

- Measured this session: Burke 55 documents in 2025 (23 trustee's deeds, 32 commissioner's deeds). Cleveland 39 documents in 2025 (all trustee's deeds). Buncombe 51 to 81 per year in 2022-2024 from the assessor table, an upper bound because the TRD code also covers non-foreclosure trust deeds.
- Estimated for the other 15 counties: about 790 per year across all 18, plus or minus 40 percent. Method in the notes under table (b).
- Buildable now (the 7 BUILD-READY and BUILD-WITH-WORK counties): about 310 per year, 39 percent of the total.
- If decision D1 clears robots-excluded hosts: the 8 robots-only counties add about 380 per year, taking coverage to 87 percent. Oconee is the ninth robots county but stays walled by its account requirement.
- Walled regardless (Rutherford, Cherokee, and Oconee's login): about 100 per year, 13 percent.

### Top 3 builds

1. **CCHS classic adapter for Burke and Cleveland.** 7 hours on top of the 12-hour shared core. Verified live today. 94 loss-class deeds per year measured. The adapter already exists in `rod/cchs.py`; its instrument-code list is wrong (finding F4).
2. **AcclaimWeb for Pickens.** 6 hours. About 52 per year estimated, and every row carries a TMS parcel number, which removes the address-resolution step.
3. **Buncombe history from open data.** 10 hours. Two public ArcGIS tables joined on deed book and page give instrument code plus grantor and grantee names for every deed through January 2025, with no ROD scraping. Gaston (12 hours, about 74 per year) is a close fourth.

If D1 clears, Henderson and Lincoln (same CCHS adapter as Burke, 3 hours, about 78 per year) become build 1b, the best yield per hour on the list.

### Decisions needed from you

- **D1. robots.txt.** The recorder sites of nine of the 18 core counties serve `Disallow: /` (the Logan hosts allow only the front page). `kofile.py` already treats that as a wall, but production modules (`rod/logan.py`, `rod/cott_recordroom.py`, `enrichment_spartanburg_rod.py`) already fetch some of these hosts. Pick one policy and apply it everywhere. Until you do, this document counts them WALLED.
- **D2. Click-through disclaimers.** Pickens (AcclaimWeb) and the Logan sites gate search behind a disclaimer that must be accepted with a POST. The production adapters accept it in code. I did not accept it. Confirm that stays the operator's call.
- **D3. Stage gate.** After build 2, backfill 2010 to date for Burke, Cleveland and Pickens and join offline to board owners. Continue to builds 3 and 4 only if it produces a meaningful number of matches (suggested bar: 10 or more owners across the three counties). One board process at a time on the 8 GB Mac.

---

## (b) Per-county table

Legend for the last two columns. Hours are incremental for the county once the shared core (12 hours, section c) exists. Deeds per year: M is measured this session, E is estimated with a range.

### NC (11)

| County | Platform and host | No-login instrument or date search | Fields per row | Existing modules (do not duplicate) | Verdict | Hours | Loss-class deeds per year |
|---|---|---|---|---|---|---|---|
| Burke | CCHS classic ASP, `us5.courthousecomputersystems.com/BurkeNCNW` | YES. Verified today: date range plus instrument-kind filter run server side, 279 kinds, no login, no CAPTCHA, no robots.txt | date, kind, book, page, doc number, one row per party (grantor or grantee), excise stamp, parcel key, description (holds the foreclosed deed-of-trust book/page) | `rod/cchs.py`, `enrichment_cchs_rod.py` (per owner), `scrapers/counties_nc/nc_rod_substitute_trustee.py` (60 and 90 day windows) | BUILD-READY | 3 | M 55 (2025) |
| Cleveland | same platform, `.../ClevelandNCNW` | YES. Verified today, 365 kinds | same | same modules | BUILD-READY | 4 | M 39 (2025, trustee's deeds only) |
| Buncombe | Aumentum or Cott eSearch v4 (`registerofdeeds.buncombenc.gov`) plus public ArcGIS assessor tables | ROD: guest session works with a cookie jar, "Guest User" and a "Date Range" button verified; search not exercised (POST). Open data lane: verified by query | ROD grid: date, index, type, grantor, grantee, description, file number, book/page. Open data: `deed_instrument` code, book, page, date, price, PIN (table `SalesMaster2025`) plus Grantor1/2 and Grantee1/2 (table `saledata`) | `rod/aumentum.py`, `enrichment_aumentum_rod.py`, `nc_rod_substitute_trustee.py`, `scrapers/national/cash_buyer_deeds.py` (uses `_date_swept_docs`), `enrichment_recorded_sales.py` (uses `saledata` for prices only) | BUILD-WITH-WORK | 10 for history, plus 14 for the ROD lane covering 2025 onward | M 51-81 (2022-2024), upper bound |
| Gaston | CCHS "LRSearch" MVC app, `gastonnc.courthousecomputersystems.com` | Form verified by GET: fields `DocTypes`, `FromDate`, `ToDate`, `TaxFrom`, `TaxTo`, `Given`, `Last`, `MaxRecordCount`; no login, CAPTCHA or robots.txt. The search itself is a POST after a seed GET, not exercised | per repo docs: date, kind, grantor, grantee, description, doc number, book, page | `enrichment_gaston_rod.py` (name search, correct host). `rod/aumentum.py` still maps Gaston to a dead host and `nc_rod_substitute_trustee.py` still lists it, so Gaston returns nothing there | BUILD-WITH-WORK | 12 | E 74 (45-105) |
| Transylvania | Logan "The Lookup", `search.transylvaniadeeds.com` | Front page and terms read by GET: disclaimer only, no restriction language, no robots.txt (the only robots-clean Logan county). The sweep is a POST after an Accept POST, not exercised | book info, doc type, legal description, party type, searched party, reverse party; one row per party; no consideration | `rod/logan.py`, `scrapers/counties_nc/nc_rod_logan.py` | BUILD-WITH-WORK | 8 | E 15 (9-22) |
| Polk | Cott eSearch v4, `cotthosting.com/ncpolkexternal` | Guest session works with a cookie jar, "Date Range" button present (verified). Search not exercised | same grid as Buncombe | `rod/cott.py` (name search, stale viewstate path), listed in `nc_rod_substitute_trustee.py` | BUILD-WITH-WORK | 10 (4 if the Buncombe ROD lane exists) | E 9 (5-13) |
| Rutherford | Cott eSearch v4, `cotthosting.com/NCRUTHERFORDEXTERNAL` | NO. Verified today with a cookie jar: lands on `User/Login.aspx` (eSearch Account Sign In), no guest option. `docs/completeness_deeds.md` says guest access works; that is wrong | n/a | `rod/cott.py` (dead). Tax side is covered elsewhere: Kania feed, `rutherford_wildfire_tax.py` | WALLED (login) | n/a | E 26 (16-38) |
| Henderson | CCHS classic ASP, `us4.courthousecomputersystems.com/HendersonNCNW` | Same platform as Burke. Not probed: us4 `robots.txt` is `Disallow: /` | as Burke | `rod/cchs.py` map, `enrichment_cchs_rod.py` | WALLED (robots). Flips to BUILD-READY on D1 | 1.5 if cleared | E 48 (30-70) |
| Lincoln | CCHS classic ASP, `us4.../LincolnNCNW` | As Henderson | as Burke | same | WALLED (robots). Flips to BUILD-READY on D1 | 1.5 if cleared | E 30 (18-42) |
| McDowell | Logan "The Lookup", `search.mcdowelldeeds.com` | robots.txt: `Allow: /$`, `Disallow: /` | as Transylvania | `rod/logan.py`, `nc_rod_logan.py` | WALLED (robots) | 2 if cleared, after Transylvania | E 18 (11-25) |
| Mitchell | Logan "The Lookup", `search.mitchelldeeds.com` | robots.txt as McDowell | as Transylvania | same | WALLED (robots) | 2 if cleared | E 6 (4-9) |

### SC (7)

| County | Platform and host | No-login instrument or date search | Fields per row | Existing modules (do not duplicate) | Verdict | Hours | Loss-class deeds per year |
|---|---|---|---|---|---|---|---|
| Pickens | Harris AcclaimWeb, `www.pickensscrod.us/AcclaimWeb` | Per repo module: disclaimer POST, then a date range with "all" doc types returns a JSON grid (the module asks for 2,000 rows per page and uses 10-day windows because the portal caps results per search; the cap value is not verified). Verified today by GET: no robots.txt (the path returns the app shell), disclaimer text has no restriction language. Search not exercised | `DirectName`, `IndirectName`, `DocType`, `RecordDate`, `InstrumentNumber`, `BookType`, `BookPage`, `ParcelNumber` (TMS), `Comments` (legal description). No consideration in the grid | `rod/acclaim.py`, `scrapers/counties_sc/sc_rod_acclaim.py` (wired at `main.py:605`, keeps only distress DocTypes, so deed classes are fetched and thrown away) | BUILD-READY | 6 | E 52 (31-73) |
| Spartanburg | Logan "The Lookup" newer AJAX build, `search.spartanburgdeeds.com` | robots.txt `Allow: /$`, `Disallow: /`. Repo evidence: index returned 0 rows for every search type in 2026-06 and the site was hacked around 2026-06-14, so it may also be down | book info, doc type, description, party type, searched party, reverse party, cross-ref, image | `rod/logan_render.py` and `enrichment_spartanburg_rod.py` (per owner, about 25 seconds each, cap 30 per run, `main.py:2596`). Court lane: `spartanburg_master_in_equity.py` | WALLED (robots) plus outage | 14 if cleared and restored | E 140 (85-195) |
| Anderson | ACPASS county CGI, `acpass.andersoncountysc.org` | robots.txt `Disallow: /`. Mechanics fully mapped in `docs/enumeration_r4/r4_deed_mining.md`: date range plus a mandatory type code, 25 rows per page with cursor paging. There is no TAX DEED, foreclosure deed or distribution-deed code; those record as generic DEED (002) | date, instrument number, type, book/page, parties with GRANTOR or GRANTEE role, description; amount blank | None for ROD. Court lane: `anderson_master_in_equity.py`, `anderson_sheriff.py`. `andersondeeds.com` in the registry is Anderson County TENNESSEE (verified today) | WALLED (robots) | 14 if cleared | E 92 (55-130) |
| Oconee | Tyler PublicSearch (Kofile family), `oconee.sc.publicsearch.us` | NO. Free account required per county text, and robots.txt serves `Allow: /$`, `Disallow: /` (verified today) | n/a | `rod/kofile.py` (robots guard returns an empty list by design). Tax side: `oconee_tax_sale.py`, `oconee_forfeited_land.py`, `oconee_flc_assignment.py` | WALLED (account and robots) | n/a | E 47 (28-66) |
| Cherokee | Avenu Insights (Neumo Records Management), `cherokeesc.avenuinsights.com` | Terms forbid data mining, robots and spiders per `docs/ROD_PORTAL_ACCESS.md`. I did not re-read them: they sit behind the app. Verified today: the old `sclandrecords.com/sclr/` landing now sends the Cherokee choice to this host | n/a | `scrapers/counties_sc/cherokee_rod.py` targets the stale `sclandrecords.com/cherokee/` path and can only return nothing | WALLED (terms of service) | n/a | E 26 (16-36) |
| Union | Cott RecordRoom, `recordroom.cottsystems.com/unionsc/guest` | robots.txt `Disallow: /` and `Disallow: *.pdf`, although the guest path opens. Rows per repo: Type, PartyOne, PartyTwo, RecordingDate, Property, FileNumber, BookPage | as listed | `rod/cott_recordroom.py`, `sc_rod_cott.py` (wired at `main.py:606`, keeps only probate and lien kinds) | WALLED (robots) | 4 if cleared | E 13 (8-18) |
| Laurens | Logan older "Online Record System", `search.laurensdeeds.com` | robots.txt `Allow: /$`, `Disallow: /`. Name required for the party search (2,000 name cap). A name-less daily notebook (`nontemp.php`) exists but only shows today's recordings and cannot be backfilled, per `docs/enumeration_r3/r3_Laurens.md` | 89 full-text instrument types including TAX DEED, FORECLOSURE DEED, DEED OF DISTRIBUTION | `rod/logan.py` docstring only. Not in the county set of `enrichment_rod_name_index.py` | WALLED (robots) | 6 if cleared (daily poll, forward only) | E 31 (19-43) |

### Notes under the tables

**Yield method for estimated rows.** Loss-class deeds per year per 1,000 housing units was 1.4 in Burke, at least 0.9 in Cleveland (trustee's deeds only) and at most 0.5 in Buncombe. I applied 0.8 to NC counties and 1.0 to SC counties (SC adds master's and tax deeds on top of judicial foreclosure), with plus or minus 40 percent. Housing units are rounded 2020 Census figures I recalled, not fetched today. Treat estimated rows as order of magnitude. The first live sweep replaces them with counts.

**Burke and Cleveland, what a real row looks like (2025 window, deduplicated to documents).** Burke: 166 party rows collapse to 55 documents, an average of 3.0 rows per document. All 55 carry an excise stamp and a parcel key, 42 carry a description. Stamp times 500 gives consideration: trustee's deeds median $135,000, commissioner's deeds median $16,000 (range $0 to $310,000). Cleveland: 175 party rows collapse to 39 documents, all with stamp, parcel key and description; median $129,500. In trustee's deeds the grantors are a law-firm trustee plus the borrower or borrowers, so the loser's name is on the instrument. In Burke commissioner's deeds the grantors are an attorney commissioner plus the delinquent taxpayer or taxpayers. The party-row explosion is the same one CLAUDE.md warns about for counts: dedupe on book, page, instrument number and kind before counting anything.

**Cleveland shows zero commissioner's deeds.** I searched eight candidate kinds (`TR/D`, `COM/D`, `COMM/D`, `COMM/DEED`, `TR/DEED`, `SHF/D`, `SHERIFFS DEED`, `DEED/CNTY`) for 2025 and only `TR/D` returned rows. Cleveland tax foreclosure deeds are probably recorded as plain DEED. Confirm with one wider query before promising Cleveland tax-loss coverage (2 of the 4 hours).

**Buncombe open-data lane, verified by query.** `SalesMaster2025` (organization `services6.arcgis.com/VLA0ImJ33zhtGEaP`, 369,875 rows) has `deed_instrument`, `deed_book`, `deed_page`, `deed_date`, `sale_price`, PIN. `saledata` (390,946 rows, latest sale date 2026-09-17) has `Grantor1/2`, `Grantee1/2`, `DeedBook`, `DeedPage`, `SellDate`. Joining on book and page worked on two sampled deeds. Two caveats. First, `SalesMaster2025` stops at 2025-01-21, so 2025 and 2026 deeds need the ROD lane. Second, the code meanings are unverified: of two sampled `TRD` rows, one looks like a foreclosure trustee's deed (individual borrowers to an LLC, $289,000) and one is a revocable trust conveying to an individual at $0. Counts 2022-2024: `TRD` 143, `CMD` 61, `SFD` 3 (207 combined, 51 to 81 per year); also `QCD` quitclaim 1,194, `WLL` 162, `EAD` 41, `DTH` 51, `DOG` 32. The `Sales_Grantors_2025` table is not usable for names because `grantor_id` is a numeric hash.

**Registry error found.** `docs/COUNTY_SYSTEMS_REGISTRY.md` lists `https://andersondeeds.com/` as Anderson SC's recorder. Verified today, the page reads "Anderson County Tennessee". Same trap as the two wrong-state hosts already recorded in `docs/HANDOFF.md`.

---

## (c) Recommended build order

Ordered by loss-class deeds per incremental hour, with counties on one platform grouped so one adapter serves many.

| Build | Scope | Platform | Hours | Deeds per year | Per hour | Comment |
|---|---|---|---|---|---|---|
| 0 | Shared core | all | 12 | 0 | n/a | Canonical instrument classifier 3 h, SQLite sidecar with document-level dedupe 3 h, wire into `deed_chain` and `repeat_tax_loss` 4 h, RAW_KEEP registration and tests 2 h. Nothing pays off without it |
| 1 | Burke, Cleveland | CCHS classic ASP | 7 | 94 (M) | 13 | Fix instrument-code list, collapse party rows to documents, add year-window backfill. First measurable signal after 19 hours total |
| 1b | Henderson, Lincoln | CCHS classic ASP | 3 | 78 (E) | 26 | Only if D1 clears us4. Configuration, not code |
| 2 | Pickens | AcclaimWeb | 6 | 52 (E) | 8.7 | Stop discarding deed DocTypes in `rod/acclaim.py`, capture the DocType vocabulary on the first run, persist TMS |
| gate | D3 stage gate | | 0 | | | Backfill Burke, Cleveland, Pickens from 2010 and join offline. Stop or continue |
| 3 | Buncombe history | open ArcGIS tables | 10 | 65 (M, upper) | 6.5 | Verify code meanings against the county's deed-type table. Refresh quarterly. Needs no ROD scraping |
| 4 | Gaston | CCHS LRSearch | 12 | 74 (E) | 6.2 | Capture the `ExecuteSearch` POST with dates and DocTypes once. Remove the dead Aumentum Gaston entry |
| 5 | Transylvania, then McDowell and Mitchell if D1 clears | Logan Lookup | 8, then 4 | 15, then 24 (E) | 1.9, then 6 | Extend code list in `rod/logan.py`, persist rows, verify live before trusting |
| 6 | Buncombe 2025 onward and Polk | Aumentum eSearch v4 | 14, then 4 | 9 (E) plus recency | under 1 | Day-by-day date sweep with paging (current code reads page 1 only). Defer |
| D1 later | Union 4 h, Laurens daily poll 6 h, Anderson 14 h, Spartanburg 14 h once its index is restored | | | 13, 31, 92, 140 (E) | 3, 5, 6.6, 10 | All blocked on D1 |

Cumulative at the end of build 4: about 47 hours, 5 counties, about 285 loss-class deeds per year, roughly 36 percent of the estimated total.

**Where hours hide.** A first-run history backfill is one search per county-year on CCHS (the server filters by kind and date), so 16 years of Burke is 16 searches. Confirm the history reaches back: I confirmed 2015 and 2020 windows return rows on Burke, but only as far as a 20-row cap, so this is a depth check, not a count. AcclaimWeb caps results per search, so keep the 10-day windows `rod/acclaim.py` uses and assert the returned count is below the requested page size. Every one of these caps must be asserted in a test (CLAUDE.md, "silent success").

---

## (d) What each build unlocks, the schema, and the code changes needed

### Signals unlocked

| Signal or synthesis item | Needs | Unlocked by |
|---|---|---|
| `repeat_tax_loss` (Dirty Deeds Tier A #34) | Trustee's, commissioner's, sheriff's, master's or tax deeds with the loser's name on the instrument | Builds 1, 1b, 3, 4 (NC). Build 2 only if Pickens DocTypes include tax or master's deeds (vocabulary unverified). SC others walled |
| Deed chain and chain breaks (`deed_chain`; Tier A #13 index start year) | Every deed-class instrument with grantor and grantee | Same builds. CCHS returns everything when `instrumenttypes` is empty (`cash_buyer_deeds.py` already relies on this). Buncombe `SalesMaster2025` carries every deed code. Index start year per county falls out of `min(recorded_date)` |
| Distribution and estate deeds (Tier B #10 "no executor's deed ever recorded", `relationship_signal`) | NC: kinds `ADM-DEED`, `EXRX-DEED`, `EXR DEED`, `EXRS DEED`, `GDN DEED`. SC: DEED OF DISTRIBUTION | CCHS builds and Buncombe (`EAD`, `WLL`, `DTH`, meaning unverified). SC distribution deeds flow today from Pickens (`sc_rod_acclaim.py`); Laurens, Union and Anderson are walled |
| Quitclaim and divorce deeds (Tier B #20, `enrichment_relationship_deeds.py`) | `QCD`, `D/SEP`, `DEED/SEP`, `M/SEP` | CCHS builds. Buncombe `QCD` had 1,194 rows in 2022-2024 |
| Liens | SC only at the ROD (HOA, mechanics, tax lien, judgment). NC liens sit with the Clerk of Superior Court (`docs/completeness_deeds.md`) | Pickens only among buildable counties. CCHS also lists `LIEN` and `JGMT` kinds, volume unmeasured. Anderson HOA lien code 193 is walled |
| Affidavit of heirship, memorandum of contract, power of attorney (Tier B #17, #18) | `AFFT`, `MEMO`, `P/A` kinds plus description text | CCHS builds. Both dictionaries carry the kinds; volume unmeasured |
| NC sale price from excise stamp (comps) | Stamp field on the deed | CCHS builds: 55 of 55 Burke and 39 of 39 Cleveland documents carry one |
| Not unlocked by an index | Life-estate deeds (#19) need deed body text. Amateur curative instruments (#33) need images. Death certificates (#40) sit in CCHS's separate Vital Index, not the instrument dictionary | none of these builds |

### Existing defects that keep `repeat_tax_loss` at 0 (F1 to F3 and F5 verified by running the normalizer and the three match lists on sample codes; F4 by reading `rod/cchs.py` against the live kind dictionaries)

- **F1. Vendor short codes are dropped everywhere.** `TR/D`, `COM/D`, `SHF/D` pass through `rod/models.normalize_doc_type` unchanged, then fail `rod/classify._KEEP` (so they never reach `raw['rod'].instruments`), fail the `rod_docs` filter in `enrichment_deed_chain._collect_records`, and fail `_LOSS_DOC_TYPES` in `enrichment_repeat_tax_loss.py`.
- **F2. The normalizer erases full-text loss types.** `normalize_doc_type("TAX DEED")` returns `"DEED"` and `normalize_doc_type("SHERIFF DEED")` returns `"DEED"`, because it keeps the shortest bucket key. `"TRUSTEES DEED"` (no apostrophe, as CCHS spells it) survives but does not match `"TRUSTEE'S DEED"` in `_LOSS_DOC_TYPES`. `"COMMISSIONER'S DEED"` is not in `_LOSS_DOC_TYPES` at all, and in NC that is the tax foreclosure deed. Fix: classify once into a canonical `inst_class` and stop matching substrings.
- **F3. `distress_transfers` loses the loser's name.** `enrichment_deed_chain._summarize` appends `{date, price, doc_type, source}` with no grantor. `enrichment_repeat_tax_loss` then falls back to `summary.prior_owner`, the grantor of the most recent transfer that has one, which is rarely the person who lost that parcel. Keep `grantor` and `grantee` in each entry.
- **F4. The CCHS sold-recordings code list is wrong.** `rod/cchs._SOLD_TYPES = "COM/D,FORECLOSURE DEED,SUBTRUSTEE DEED,TRUSTEE"`. Only `COM/D` is a real kind in the Burke and Cleveland dictionaries. `TR/D` is missing, so `nc_rod_substitute_trustee.py`'s 90-day post-sale sweep returns commissioner's deeds only. Correct set: `TR/D,COM/D,SHF/D` (Cleveland also `TR/DEED`, `COMM/D`, `COMM/DEED`, `SHERIFFS DEED`, `DEED/CNTY`).
- **F5. The join only sees losses on parcels already on the board.** Pass 1 of `enrichment_repeat_tax_loss` indexes losers from each listing's own `deed_chain`. A county-wide sweep finds losers on parcels that are not board leads, and those never enter the index. Pass 1 must also read the sidecar below. This is the design change that makes the sweep worth doing.

### Minimal schema

Store instruments in a sidecar SQLite database, `data/deed_index.db`, next to the existing `data/parcel_cache.db` and `data/sc_cama.db`, not on the board. One row per recorded instrument; party rows are collapsed into lists.

```
doc_key          county|state|book|page|instrument_no|inst_code   (primary key)
county, state
source           cchs_classic | cchs_lrsearch | acclaim | aumentum | logan | assessor_open_data
instrument_no, book, page
recorded_date    ISO date
inst_code        vendor code as served (TR/D, COM/D, TRD, ...)
inst_class       canonical: TRUSTEE_DEED | COMMISSIONER_DEED | SHERIFF_DEED | MASTER_DEED | TAX_DEED |
                 QUITCLAIM | DEED | DISTRIBUTION_DEED | EXECUTOR_DEED | DEED_OF_SEPARATION | OTHER
grantors         list of names
grantees         list of names
excise_stamp     float or null      (NC; consideration is at most stamp x 500, never a comp when 0)
parcel_id        vendor parcel key or TMS when served
description      legal description or cross-reference text (Burke puts the foreclosed D/T book/page here)
loss_kind        mortgage_foreclosure | tax_foreclosure | tax_deed | judicial_sale | unknown   (derived)
loser_names      list, derived: see classifier below
fetched_at
```

Classifier rules taken from the 2025 samples. A `TR/D` is a mortgage foreclosure when a trustee-firm party (name ends in LLC, PLLC, P.A., or contains LAW, TRUSTEE) appears beside a natural-person grantor, or the description holds a deed-of-trust cross-reference. The losers are the natural-person grantors. A `TR/D` whose only grantor is a trust is not a loss. A `COM/D` is a tax or judicial foreclosure when an attorney commissioner appears among the grantors. The losers are the other grantors. Buncombe `TRD` rows need the same test through the joined `saledata` names.

**Board keys.** No new board key is required for the core signal. `repeat_tax_loss` is already in `RAW_KEEP` (`web_artifact.py:367`) and `deed_chain`, `rod_docs`, `rod`, `nod`, `relationship_signal` are registered. If you want matched instruments visible on the lead (book, page, kind, date, role), add one key, `deed_index`, shaped as a list of `{inst_class, date, book, page, role, county}`.

**Rule for any new raw key.** Register it in `RAW_KEEP` in `src/foreclosure_scraper/web_artifact.py` before the first run, or every write is silently dropped. Two more gates exist and the code comments at `web_artifact.py:354` and `:1170` record that missing them fails just as silently: `_SLIM_RAW` (the payload phones fetch) and `dashboard.js` `_LEAN_RAW`. `repeat_tax_loss` and `owner_cluster` are currently in `RAW_KEEP` only, so neither reaches the slim payload. Decide whether the dashboard should show `repeat_tax_loss` before the first run, not after.

**Sizing.** About 800 new instruments per year across 18 counties, each with one to three losers. A 16-year backfill of the five counties in builds 1 to 4 is roughly 4,500 instruments. Trivial for SQLite.

**Name-join caveat.** The join is a name string within one county and state. Common surnames will collide. Require surname plus full given name, exclude entities, and keep the existing self-match guard. Expect false positives to dominate until a second key (mailing address or an adjacent parcel) is added.

---

## (e) Walls hit, honestly

| Wall | Where | What I did |
|---|---|---|
| robots.txt `Disallow: /` (Logan hosts `Allow: /$` only) | Spartanburg, Anderson (ACPASS), Oconee, Union, Laurens, McDowell, Mitchell, Henderson (us4), Lincoln (us4) | Fetched only `robots.txt` and, where the rule allows the front page, the front page. No search request to any of them. Counted WALLED pending D1 |
| Login | Rutherford (Cott eSearch sign-in). Oconee (free account, plus robots) | Confirmed Rutherford with a cookie jar. Nothing attempted past the sign-in page |
| Terms of service | Cherokee (Avenu Insights) | Not re-read: the terms live inside the app and I made no request past the home page. Relying on `docs/ROD_PORTAL_ACCESS.md` |
| Disclaimer accepted by POST | Pickens (AcclaimWeb), Logan sites | Did not accept. Read the disclaimer text only. Neither has restriction language on the pages I read. Search on both is unverified today |
| Site outage | Spartanburg | Repo evidence only |
| No CAPTCHA seen | anywhere | A reCAPTCHA v3 script loads on the Buncombe eSearch page. The repo says it gates only the paid image cart. Not verified |

### Things I did that deserve your review

- **CCHS acknowledgement link.** The Burke page says "Click here to acknowledge this disclaimer and enter the site". That is a plain anchor to `application.asp`. I fetched `application.asp` and `realestatesearch.asp` directly, the same as the production adapter does, rather than clicking. The disclaimer sets no cookie or form value that I could see. Per the repo's own notes, Gaston's terms are a client-side dialog, and I likewise fetched its search form without clicking. I scanned the full text of both terms pages for automation, bulk, spider, scrape and redistribution language and found none (Gaston's only hit was the word "copy", in the accuracy disclaimer). If you regard fetching that URL as accepting the terms, treat the two Burke and Cleveland searches as done under that reading.
- **Request volume.** Burke received about 30 GETs over roughly an hour at 2 to 3 second spacing (dictionary dumps, two 2025 searches with their result fetches, two 20-row depth checks). Cleveland about 7. That is more than "a handful" for Burke; it is why Burke's numbers are measured.

### Doc contradictions to fix

| Doc | Says | Verified today |
|---|---|---|
| `docs/completeness_deeds.md` (2026-08-02) | Rutherford opens as a guest | Login wall |
| `docs/blocked_sources_forensic.md` line 56 and `docs/enumeration_r4/r4_deed_mining.md` | CCHS Burke, Cleveland, Henderson, Lincoln "decommissioned" | Burke and Cleveland are live. The 404 those notes recorded is the legacy `searchonline.asp`, which `rod/cchs.py` already documents as dead. Live app: `realestatesearch.asp` and `SearchService.asp` |
| `docs/enumeration_r4/r4_deed_mining.md` | Buncombe and Polk guest menu is Quick Name only | The guest page shows a "Date Range" nav button on both |
| `docs/COUNTY_SYSTEMS_REGISTRY.md` | Anderson SC recorder is `andersondeeds.com` | That is Anderson County, Tennessee |
| `scrapers/counties_sc/cherokee_rod.py` | Cherokee ROD at `sclandrecords.com/cherokee/` | Old landing now redirects to Avenu Insights |
| `enrichment_generic_rod.py` comment | Pickens and Union are covered by the name-index enricher | That enricher's county set is 8 other SC counties |

### Not verified and worth one probe each before promising anything

1. Pickens DocType vocabulary and whether tax or master's deeds have their own types (needs the disclaimer accepted).
2. Gaston `ExecuteSearch` field names for a date plus DocTypes search, and the DocTypes dialog endpoint.
3. Buncombe deed-instrument code dictionary (`TRD`, `CMD`, `SFD`, `DCL`, `LOF`, `DTH`, `WLL`).
4. Cleveland tax-foreclosure deed type.
5. Aumentum date search result cap and paging behavior (the current code reads page 1 only).
6. The Logan sweep on Transylvania, since the 2026-08-02 outage.

---

## Appendix: probe log and reference kinds

### Requests made (all GET, 2 to 3 second spacing, 2026-09-20)

| Host | Requests | Purpose |
|---|---|---|
| 15 recorder hosts | 15 | `robots.txt` |
| `www.pickensscrod.us` | 3 | app root, gated search URL without following the redirect, disclaimer text |
| `www.sclandrecords.com`, `cherokeesc.avenuinsights.com` | 2 and 4 | landing and county-select script; robots, root, home page |
| `registerofdeeds.buncombenc.gov` | 5 | cookieless redirect check, guest session, page structure |
| `cotthosting.com` (Rutherford, Polk) | 4 | cookieless and cookie-jar checks each |
| `us5.courthousecomputersystems.com` Burke | about 30 | pages, kind dictionary, two 2025 searches with result fetches, depth checks |
| `us5...` Cleveland | about 7 | kind dictionary, one 2025 search with result fetch |
| `gastonnc.courthousecomputersystems.com` | 4 | root, terms, `LRIndex` form, plus one dead-host check on `deeds.gastongov.com` |
| Logan front pages (Transylvania, Laurens, Spartanburg) | 3 | disclaimer text |
| `andersondeeds.com`, `americanlandrecords.com` | 3 | wrong-state check, robots |
| `services6.arcgis.com` (Buncombe org, Gaston org) and one Anderson ArcGIS query | about 22 | service list, field lists, grouped counts, one join test, distinct deed types |

### Reference: instrument kinds confirmed in the CCHS classic dictionaries

Burke (279 kinds): `TR/D` trustees deed, `COM/D` commissioner's deed, `SHF/D` sheriff deed, `FCL` foreclosure, `LIS/P` lis pendens, `S/TR` substitution of trustee, `R/TR` resignation of trustee, `QCD` quitclaim, `D/SEP` and `M/SEP` separation, `ADM-DEED`, `EXRX-DEED`, `C/D` corrected deed, `AFFT` affidavit, `MEMO`, `M/ACT`, `P/A`, `LIEN`, `JGMT`, `D/T`, `REL/D`, `CT/O` court order.

Cleveland (365 kinds): the same core plus `TR/DEED`, `COMM/D`, `COMM/DEED`, `SHERIFFS DEED`, `DEED/CNTY`, `DEED/SEP`, `EXR DEED`, `EXRS DEED`, `GDN DEED`, `GDNS DEED`, `FCL/WDRL`, `LISPND`, `MEMO AGMT`, `MEMO OF OPT`.

Neither dictionary has a `TAX DEED` kind.

### Reference: robots.txt results

| Host | Result |
|---|---|
| `search.spartanburgdeeds.com`, `search.laurensdeeds.com`, `search.mcdowelldeeds.com`, `search.mitchelldeeds.com` | `Allow: /$`, `Disallow: /` |
| `oconee.sc.publicsearch.us` | `Allow: /$`, `Disallow: /` |
| `acpass.andersoncountysc.org` | `Disallow: /` |
| `recordroom.cottsystems.com` | `Disallow: /`, `Disallow: *.pdf` |
| `us4.courthousecomputersystems.com` | `Disallow: /`, `Disallow: /ProcessedImages/` |
| `us5.courthousecomputersystems.com`, `gastonnc.courthousecomputersystems.com`, `cotthosting.com`, `registerofdeeds.buncombenc.gov`, `search.transylvaniadeeds.com`, `www.sclandrecords.com`, `cherokeesc.avenuinsights.com` | 404, no directives |
| `www.pickensscrod.us` | no robots.txt (path returns the app shell) |
