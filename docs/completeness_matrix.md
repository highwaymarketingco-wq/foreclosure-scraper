# COMPLETENESS REPORT
## Foreclosure lead engine, 18-county footprint, 2026-08-04

**Basis.** Board = `/Users/cashhigh/foreclosure-scraper/docs/listings.json`, verified independently: 144,377,381 bytes, mtime 2026-08-03 14:01 EDT (= 2026-08-03T18:01Z), 25,552 leads. Its scrape content is the **2026-07-31 full run**; the 08-02 and 08-03 commits were enrichment passes, not re-scrapes. A full run (pid 9499, `local-run-20260804T111456`) finished all 124 started scrapers between 15:15Z and 15:33Z today and is in enrichment now. **It has not written the board yet.** Every "pending / lands this run" verdict below is therefore unproven.

Registry = **132 wired scrapers** (`discover()` run live). 124 started today, 8 dormant.

---

# 1. THE MATRIX

**24,935 of 25,552 leads (97.6%) fall inside the 18-county footprint.** The other 617 are Charleston 306, Brunswick 112, Onslow 57, Dare 36, Pender 34, Carteret 31, Horry 18, and 17 with a null county.

Column key: FCL=foreclosure_sale · UPS=upset_bid · LP=lis_pendens/pre-fcl · TXD=tax_delinq current · TXM=tax_delinq multiyear · TXS=tax_sale · FLC=forfeited/county-owned · PRB=probate/estate · HEI=heirs · DIV=divorce · BKR=bankruptcy · CODE=code_violation · CND=condemned/unfit · VAC=vacant · ELD=elderly/deferral · JAIL=jail/incarceration · OBIT=obituary/death · STRM=storm/disaster · ABS=absentee/out-of-state · CBD=cash-buyer deed · LIEN=HOA/muni/other lien · COMP=sales-comps

| County | Leads | FCL | UPS | LP | TXD | TXM | TXS | FLC | PRB | HEI | DIV | BKR | CODE | CND | VAC | ELD | JAIL | OBIT | STRM | ABS | CBD | LIEN | COMP |
|---|--:|--:|--:|--:|--:|--:|--:|--:|--:|--:|--:|--:|--:|--:|--:|--:|--:|--:|--:|--:|--:|--:|--:|
| Buncombe NC | 5902 | 39 | 13 | 60 | 1203 | – | – | – | 445 | 101 | 40 | 70 | – | 172 | – | 3680 | 3 | 45 | 305 | 1822 | – | – | 3460 |
| Henderson NC | 1321 | 14 | 16 | 47 | 1087 | – | – | – | 158 | 73 | 3 | 48 | – | – | 1 | 1 | 1 | 13 | – | 639 | – | – | 1313 |
| Gaston NC | 299 | 69 | 8 | 8 | 2 | – | 1 | – | 87 | 67 | 1 | 3 | – | 1 | 1 | 1 | 1 | 3 | – | 75 | – | – | 297 |
| Cleveland NC | 165 | 18 | 1 | 34 | 5 | – | 1 | – | 67 | 54 | 1 | 33 | – | – | 3 | – | 1 | 5 | – | 39 | – | – | 157 |
| Rutherford NC | 182 | 10 | 3 | 2 | 5 | – | 8 | – | 138 | 134 | 1 | 2 | – | – | – | – | 1 | 2 | – | 26 | – | – | 181 |
| Burke NC | 172 | 24 | 3 | 21 | 1 | – | – | – | 62 | 52 | – | 16 | – | – | 1 | – | 3 | – | – | 122 | – | – | 172 |
| Lincoln NC | 335 | 16 | 4 | 24 | 200 | – | – | – | 75 | 48 | – | 24 | – | – | 1 | – | – | – | – | 49 | – | – | 331 |
| McDowell NC | 2258 | 12 | 8 | 31 | 2090 | – | – | – | 160 | 83 | 1 | 26 | – | – | – | – | – | – | – | 2169 | 29 | – | 1891 |
| Polk NC | 167 | 2 | 2 | 25 | – | – | – | – | 104 | 96 | 1 | 25 | – | – | – | – | 1 | – | – | 25 | – | – | 73 |
| Transylvania NC | 190 | 4 | 7 | 46 | 5 | – | – | – | 81 | 75 | 9 | 14 | – | – | 1 | – | – | – | – | 35 | – | – | 185 |
| Mitchell NC | 131 | 3 | 1 | 13 | – | – | – | – | 77 | 79 | – | 16 | – | – | 2 | – | – | – | – | 102 | – | – | 7 |
| Spartanburg SC | 8919 | 106 | n/a | 1102 | 2172 | – | 2188 | 15 | 455 | 331 | 12 | 75 | 650 | 1670 | 3459 | – | 2 | 25 | 44 | 380 | – | 6 | 4665 |
| Anderson SC | 1097 | 66 | n/a | 445 | 1 | – | 5 | 2 | 42 | 2 | 8 | 88 | – | – | 1 | – | 2 | 21 | – | 216 | – | 1 | 1036 |
| Pickens SC | 871 | 24 | n/a | 224 | 37 | – | 1 | – | 193 | 28 | 2 | 34 | – | – | – | – | 1 | – | 1 | 168 | – | 2 | 709 |
| Oconee SC | 982 | 16 | n/a | 175 | 130 | – | 505 | 512 | 30 | 5 | 38 | 37 | – | – | – | – | – | – | – | 537 | – | – | 406 |
| Cherokee SC | 565 | 15 | n/a | 259 | – | – | – | – | 4 | – | – | 1 | – | – | – | – | 1 | – | – | – | – | – | 527 |
| Union SC | 477 | 6 | n/a | 145 | – | – | – | – | 4 | 6 | – | 25 | – | – | – | – | – | – | – | 30 | – | – | 450 |
| Laurens SC | 902 | 19 | n/a | 292 | 3 | – | 29 | 33 | 81 | 80 | 6 | 48 | – | – | 1 | – | 2 | – | – | 103 | – | 1 | 722 |
| **Footprint total** | **24935** | **463** | **66** | **2953** | **6941** | **0** | **2738** | **562** | **2263** | **1314** | **123** | **585** | **650** | **1843** | **3471** | **3682** | **19** | **114** | **350** | **6537** | **29** | **10** | **16582** |

`UPS` is n/a in SC: the upset-bid window is NC statute (NCGS 45-21.27, cited in the board's own `raw.upset_bid.statute`). All 66 upset-bid leads are NC. Correct behavior, not a gap.

**Board-wide breadth** (how many of the 18 counties carry the signal at all): sales-comps 18, foreclosure_sale 18, lis_pendens 18, probate/estate 18, bankruptcy 18, heirs 17, absentee 17, tax_delinq 14, divorce 13, jail 12, upset_bid 11 (of 11 NC), vacant 10, tax_sale 8, obituary 7, forfeited 4, HOA/muni lien 4, condemned 3, elderly 3, storm 3, code_violation 1, cash-buyer deed 1, **tax_delinq_multiyear 0**.

**Two board bugs corrected before scoring.** (1) The `probate_estate` signal is contaminated: 3,537 of its 4,755 occurrences come from `counties_nc.buncombe_elderly` (`listing_type=elderly_disabled`), an exemption roster, not probate. Uncorrected, Buncombe probate reads 3,943; corrected it is 445. (2) `raw.owner_mailing` is a bare string in 5,100 records (all Spartanburg) instead of the dict shape used everywhere else; the dict-only reader undercounted Spartanburg mailing coverage as 5.0% when it is 62.2%.

**What the matrix shows at a glance:** three signals exist in exactly one county (code_violation Spartanburg only, cash-buyer deed McDowell only), one signal exists nowhere (multi-year tax delinquency, 0 of 18), elderly/deferral is 99.9% one county (Buncombe 3,680 of 3,682), and vacant is 99.7% one county (Spartanburg 3,459 of 3,471). Those are not county characteristics. They are single-source coverage.

---

# 2. COUNTY SCORECARD

"Biggest gap" is mechanical: county lead volume x the share of the 18 footprint counties that DO carry the missing signal. N/A cells excluded. Contactability is from the audit's per-county table; the footprint-weighted aggregates are derived by me from that table, not independently measured.

| County | Score | Leads | % mailable | % phone | % unreachable | Single biggest gap (score) |
|---|--:|--:|--:|--:|--:|---|
| Spartanburg SC | 18/21 | 8919 | 62.2 | 0.0 | 37.8 | elderly/deferral (1,486) |
| Gaston NC | 16/22 | 299 | 43.8 | 8.7 | 55.9 | forfeited + HOA/muni lien (66 each); see note |
| Buncombe NC | 15/22 | 5902 | 84.1 | 45.8 | 9.1 | **vacant (3,279)** |
| Anderson SC | 15/21 | 1097 | 26.3 | 0.0 | 73.7 | condemned / elderly / storm (183 each); see note |
| Henderson NC | 14/22 | 1321 | 89.3 | 23.7 | 8.8 | tax_sale (587) |
| Cleveland NC | 14/22 | 165 | 46.7 | 7.9 | 53.3 | forfeited + HOA/muni lien (37 each) |
| Laurens SC | 14/21 | 902 | 14.1 | 0.0 | 85.9 | obituary/death (351) |
| Rutherford NC | 13/22 | 182 | 18.7 | 5.5 | 81.3 | vacant (101) |
| Pickens SC | 13/21 | 871 | 19.7 | 0.0 | 80.3 | vacant (484) |
| Burke NC | 11/22 | 172 | 37.8 | 20.3 | 52.3 | divorce (124) |
| McDowell NC | 11/22 | 2258 | 92.6 | 23.9 | 6.2 | **jail/incarceration (1,505)** |
| Transylvania NC | 11/22 | 190 | 18.9 | 14.7 | 70.5 | jail/incarceration (127) |
| Oconee SC | 11/21 | 982 | 56.6 | 0.0 | 43.4 | jail/incarceration (655) |
| Lincoln NC | 10/22 | 335 | 59.1 | 28.4 | 30.7 | divorce (242) |
| Polk NC | 10/22 | 167 | 24.0 | 17.4 | 64.1 | tax_delinq current (130) |
| Mitchell NC | 9/22 | 131 | 20.6 | 16.0 | 66.4 | tax_delinq current (102) |
| Union SC | 7/21 | 477 | 9.4 | 0.0 | 90.6 | tax_delinq current (371) |
| Cherokee SC | **6/21** | 565 | **0.0** | 0.0 | **100.0** | **heirs + absentee (534 each)** |
| **Footprint** | — | **24935** | **62.5** | **15.3** | **35.3** | — |

Mailable = `owner_mailing` (dict `.mailing` or bare string) OR `skip_trace.owner_mailing_address` OR `sos_agent.best_contact_address` OR `nc_ptscloud_delinquent_tax.mailing.addr`. Phone = `owner_phone.phone` OR `skip_trace.phone_numbers`. Unreachable = neither. The source audit's definition line for "unreachable" was truncated in transmission; the arithmetic across all 18 rows is consistent with "neither mailing nor phone", so that is what is stated here. **Unverified as a literal quote of the audit's definition.**

**Notes where the mechanical score understates the real gap:**
- **Gaston.** Score says forfeited/HOA lien. The real gap is that Gaston sits in **no property-tax-arrears module at all**: not a PTS Cloud tenant, not in the Lincoln/Catawba/McDowell PDF set, not in `multi_year` (Buncombe/Oconee/Pickens only). It shows TXD=2 out of 299 leads. It is the only one of the four heavily-audited NC counties with no tax-arrears lane.
- **Anderson.** Score says condemned/elderly/storm. The real gap is the same shape: **no source of any kind wired to Anderson's delinquent-tax roll** (TXD=1 of 1,097).
- **Cherokee SC.** The standout by breadth. It is the only footprint county with **zero heirs and zero absentee** out of 18, and the only county at **100% unreachable**. Its 565 leads are almost entirely lis pendens (259) with no owner-side enrichment attached to any of them.

**Two structural contactability facts, larger than any per-county gap:**
1. **Phone coverage in South Carolina is 0.0% across all seven SC counties, 13,813 leads.** Not low. Zero. Every phone number on the board is in North Carolina.
2. **35.3% of the footprint (8,795 leads) has neither a mailing address nor a phone.** The known cause for a large share of it is the `owner_mailing` string-vs-dict crash that killed the mail spine, plus the resolver `_CAP=400` that starves `sc_public_index`.

---

# 3. ARE WE CAPTURING EVERYTHING?

**No.** Honest per-class answer:

| Source class | Verdict |
|---|---|
| County GIS / ArcGIS parcel layers | Best-performing class. Exact or near-exact capture where wired (Spartanburg delinquent tax 2,171 of 2,171, FLC 7 of 7). Losses here are dedupe artifacts and missing county wiring, not parser failure. |
| County tax-arrears rolls (PDF / PTS Cloud) | Highest raw volume, most fragile. One confirmed schema drift (Lincoln), one 9,328-row rewrite that has never reached the board (Rutherford), two counties with no lane at all (Gaston, Anderson). |
| Master-in-Equity / county rosters | Systematically broken by one filter. All three Upstate MIE scrapers sit outside `DATELESS_OK_SOURCES`; Spartanburg's now fails 100%. |
| Register of Deeds (Cott / CCHS / Logan) | Worst class. One vendor went behind login (Rutherford), one form silently vanished (Polk), one collapses 39 rows to 1 on dedupe (Union), one has not landed in 5 weeks (Burke). |
| Law firm trustee feeds | Whitelist-gated. Kania, ALAW, Ingle all scraped rows and landed zero. Kania's cause is dated and self-healing; ALAW's is not fixed. |
| Newspapers / legal notices | Mostly genuinely empty today, with three dead URLs and one real missing-lane bug. |
| Court (eCourts / SC Public Index) | Accumulating correctly. Board frequently exceeds today's upstream, which is carryover working as intended. |
| Jail bookings | Broken twice over. 1,728 rows fetched per run, 4 rows on the board. |
| National / commercial | Two policy stubs, two Akamai/Cloudflare walls, one silent 220-rows-per-run regression (Crexi), two with dead pagination. |

## 3a. Every source where upstream has rows and the board has ZERO

**REAL LOSSES (code or config defect, will not self-heal):**

| Source | County | Upstream | Board | Cause |
|---|---|--:|--:|---|
| `counties_nc.nc_county_pdf_delinquent_tax` | Lincoln | 1,406 | 199 | **ID-column drift.** Board keys are 10-12-digit GIS PINs (`2656983646`); upstream now emits 4-6-digit IDs (`00116`). **Zero key overlap** across 168 board PINs vs 1,406 upstream. All 1,406 pass scope/active/flip and survive dedupe unchanged. Loss 1,205. |
| `counties_sc.pickens_tax_sale` | Pickens | 160 | 0 | `Listing(...)` has **no `sale_date=` kwarg at all** and the slug is not in `DATELESS_OK_SOURCES`, so `_active_only` returns False for all 160. Logged all-filtered on **both** 07-31 and 08-04. |
| `national.jail_bookings` | Anderson | 530 | 1 | `sale_date=booking_date` means `sale_date` is never None, so `_active_only` never reaches the `DATELESS_OK` branch and applies now-14d..now+horizon. Every inmate booked >14 days ago drops. Whitelist membership is inert. |
| `national.jail_bookings` | Cherokee | unmeasured (1,728 across 6 portals) | 1 | **Second, independent defect:** listings carry no parcel, address or case number, so `dedupe_key()` falls to `url:<portal root>`, identical for every inmate. Verified by execution: 3 distinct inmates collapse to 1. |
| `counties_sc.sc_rod_cott` | Union | 39 | 1 | Same url-fallback collapse. Parcel (`072-00-00-048 000`) and situs are present in `legal_description` / `raw['cott']` but not promoted to `parcel_id` / `street_address`. Union's only county-specific source. |
| `counties_sc.spartanburg_master_in_equity` | Spartanburg | 19 | 0 (1 stale, last_seen 07-22) | Not in `DATELESS_OK_SOURCES`; roster rows carry stale/unparsed sale dates so `_active_only` drops 100%. All-filtered on 07-31 (22 scraped) and 08-04 (19 scraped). |
| `national.cash_buyer_deeds` | Burke 62, Lincoln 45, Transylvania 94 | 201 | 0 | **Cause not determined.** Slug IS in `DATELESS_OK_SOURCES`, counties are in-footprint, rows carry no `opening_bid` so `_flip_candidate` keeps them. None of the three visible filters explains it. McDowell is the only county where it lands at all (148 upstream, 24 board). ~330 rows/run. **Single largest unexplained loss in the audit.** |
| `newspapers.hendersonville_lightning` | Henderson | 5 | 0 | Parser sets `sale_date=None` when no date parses; slug is in neither `DATELESS_OK_SOURCES` nor `FORECLOSURE_SALE_SOURCES`, so the rows have no lane. All-filtered on 07-31 **and** 08-04. |
| `law_firms.alaw` | NC 18 / SC 8 | 26 | 0 | Same no-lane shape. County split **unmeasured**. ALAW is a statewide NC trustee firm that could carry any footprint county. |
| `counties_nc.nc_rod_substitute_trustee` | Burke | 11 | 0 (+1 also_seen) | Board-wide the source has 3 rows, `last_seen 2026-07-01`. Has not landed in 5 weeks despite 19 fetched on 08-02. |
| `counties_sc.terry_howe_flc` | Oconee 5, Union 18, Laurens 59 | 82 TMS | 0 | `_county_of()` title gate accepts only `<County> County, SC`. Drops "Union, SC", "Westminster, SC", "44 Properties in South Carolina". Second issue: fetches `per_page=100` once with no pagination, reading 100 of 515 auctions (`X-WP-Total: 515`). |
| `counties_nc.nc_heir_estate_parcels` | Oconee | 60 | 0 | Oconee is deliberately excluded from `_HEIR_COUNTIES` with the comment "owner field does not retitle -> 0". Measured live today on `arcserver2.oconeesc.com/.../MapServer/5`: that comment is false. |
| Cherokee WP media index | Cherokee | 529+ unique TMS | 0 | `Tax-Sale-List-2024` and `2023 Delinquent Tax List` are uploaded to `wp-json/wp/v2/media` but never anchored in a page, so the PDF-anchor scraper structurally cannot see them. |
| `public_notices.nc_notices_counties` | all 7 mid-NC counties | unmeasured (512 statewide today) | 0 board-wide | Absent entirely from the 2026-08-02 `run_health`, one of 10 registry slugs missing from it. `expected_min_count = 0` so it never alarms. |
| `law_firms.ingle_firm` 1, `city_websites.search` 159, `counties.sitemap_walker` 30, `public_notices.funeral_home_rss` 50 | unattributed | 240 | 0 | Same missing-lane shape as ALAW. County attribution **unmeasured**. |

**EXPLAINED, PENDING FIRST LANDING** (built or fixed after the 07-31 scrape that produced this board; running clean today; unproven until the live run writes):

| Source | County | Upstream | Cause |
|---|---|--:|---|
| `counties_nc.rutherford_tax` | Rutherford | **9,328 bills / $5,639,937.64** | Rewrite committed 08-03 16:38. The 5 board rows are the retired frozen-mirror parse. |
| `counties_sc.pickens_delinquent_parcels` | Pickens | 2,161 | Slug added 08-03 00:02. |
| `counties.multi_year_delinquent_tax` | Buncombe 2,078 raw / Oconee 1,561 / Pickens unmeasured | see conflict note | Created 08-03 (commit 8c51651). Never merged. Zero rows globally. |
| `counties_sc.sc_public_notices` | Spartanburg 391 / Anderson 227 / Pickens 334 grid rows today; 71 statewide scraped on the 07-31 run | see conflict note | Scraper rewrite and `DATELESS_OK` entry both landed 07-31 20:47, after the running process had imported `main.py`. Slug is absent from the board entirely. |
| `counties_sc.oconee_flc_assignment` | Oconee | 583 buyable of 657 | Entered the registry only in commit 07b04cf (08-04, the "registry bug dropping 27 scrapers" fix); DATELESS entry 58b48d2 (08-04). |
| `counties_nc.henderson_code_violations` 156, `hendersonville_vacant_structures` 51, `henderson_foreclosure_parcels` 15 | Henderson | 222 | All created 08-03. |
| `counties_sc.spartanburg_city_condemned` | Spartanburg | 91 | Slug added 08-03 20:55. In `DATELESS_OK`, returned OK/91 today. |
| `law_firms.kania` | Burke 17, Rutherford 9, Lincoln 8, Cleveland 7, Polk 1 | 42-59 | Added to `DATELESS_OK_SOURCES` 07-31 **21:11**; the 07-31 run started **11:08**. Not in today's all-filtered list. |
| `national.nc_upset_bids` | Rutherford 25, Burke 3, Lincoln 2, Polk 1 | 31 (35 today board-wide) | Fix committed 08-02 15:33, after the run that built the board. |
| `counties_nc.buncombe_tax` | Buncombe | 33 | Date-window regression fixed 08-02 plus `DATELESS_OK` entry. |
| `counties_sc.sc_flc` | Anderson | 44 (2 real estate + 42 mobile home, OCR'd) | `ZERO_RESULT` on 07-31; errored 08-04 01:57 on a Gemini key quota; clean at 11:14. |
| `counties_nc.polk_tax` | Polk | 1 (`P65-38`, sale 2026-09-01, bid `$TBD`) | `$TBD` regression fixed 08-02 15:33; `run_health` predates it. |

**EXPLAINED, NOT LOSSES:**
- **Dedupe merges.** McDowell `nc_ecourts_divorce` 4 upstream / 0 primary but 7 in `also_seen_in`. Buncombe `asheville_helene` 652 upstream, 172 primary but 242 in `also_seen_in` plus 74 under ncnotices and 44 under buncombe_elderly. `column_legal_notices` McDowell 5 primary + 69 also_seen. Rutherford obituaries 0 primary + 17 also_seen. Exact reconciliation of the Helene case is **unmeasured**.
- **Carryover / accumulation.** Board exceeds upstream on `sc_public_index` (Anderson +403, Pickens +389), `nc_heir_estate_parcels` (Rutherford +54, Polk +25), `spartan_weekly_legals` (+39), `sc_rod_acclaim` (+72). Correct behavior.
- **Scope filters.** `law_firms.zacchaeus` 142 rows dropped, coastal-scoped (Onslow/Dare). NC Cherokee and NC Union are in `SCOPE_DENY_COUNTIES`, so SC-only rows are correct. `newspapers.index_journal` is a Greenwood paper and Greenwood is a deny county.
- **Deliberate exclusions.** `sc_flc` skips Spartanburg (owned by `spartanburg_flc`), `sc_county_rosters` skips Anderson (dedicated MIE scraper), `nc_rod_substitute_trustee` skips Lincoln (different CCHS install).

## 3b. Design decision to review, not a bug

`counties_nc.henderson_tax`: 15 rows on the county page, 0 on the board, 9 in `also_seen_in`, **all 15 in `docs/foreclosure_sold_pool.json`**. The only date on the page is "May 27, 2026 at 10:00am", 69 days past, so `is_sold_pool_candidate` routes all 15 to the max-bid comp pool before the board filter ever runs. That is by design, but the design assumes a past batch date means the sale finished. If Henderson has simply not refreshed the page, 15 live leads are filed as comps. **The page gives no way to tell.** Needs a human look.

## 3c. Contradictions between the four audits, unresolved

1. **`multi_year_delinquent_tax` counts do not add up.** Buncombe alone is reported at 2,078 raw rows (2013-2025 layers) and Oconee alone at 1,561, but the source total is reported as 2,095 across all three counties. The 2,095 is a post-filter emit count and the 2,078/1,561 are raw layer features. **Unreconciled.** Pickens' share is not logged at all.
2. **`sc_public_notices` upstream is two different numbers.** 391/227/334 grid rows measured live today vs 71 rows scraped statewide in the 07-31 log. Different measurement bases. True per-county upstream is **unmeasured**.
3. **`counties_nc.buncombe_tax_foreclosure` is labeled both BROKEN and UPSTREAM-EMPTY.** Both audits probed it, both got 200 OK / valid VCALENDAR / 225 bytes / zero VEVENTs. One reads that as a past-window bug identical to the one fixed in its `.json` twin; the other reads it as a genuinely exhausted feed. Both agree on **zero net lead loss** because `buncombe_tax` covers the identical Trumba inventory.
4. **`kania` and `nc_upset_bids` are labeled BROKEN in one audit and self-healing in another.** Both are the same fact from different angles: the fix or whitelist entry postdates the board. The BROKEN label is correct about the board's state; the self-healing label is a prediction. Verify after this run writes.

---

# 4. WHAT IS BROKEN

## SEASONAL (no fix needed, will auto-resume)

| Source | Window | Action |
|---|---|---|
| `counties_sc.charleston_delinquent_tax` | Oct-Feb | none |
| `counties_sc.cherokee_delinquent_tax` | Oct-Jan | none |
| `counties_sc.colleton_tax_sale` | Dec-Mar | none |
| `counties_sc.sc_delinquent_tax_list` | Oct-Jan | none |
| `counties_sc.oconee_tax_sale` | list posts Oct 21 2026, sale Nov 9 2026 | set `active_months=(10,11)` so it reports DORMANT instead of a false zero |
| `counties_sc.sc_tax_delinquent` | mixed seasonal + dead URL | set `active_months=(10,11,12,1)` and re-point Spartanburg + Union (below) |

## BROKEN PARSER / FILTER (code fix, ranked by rows recoverable)

| Source | Rows | One-line fix |
|---|--:|---|
| `counties_nc.nc_county_pdf_delinquent_tax` (Lincoln) | 1,205 | Handle the Lincoln PDF's new 4-6-digit ID column, or key on address instead of parcel ID. |
| `national.jail_bookings` | 529 Anderson + Cherokee unmeasured | `sale_date=None` in `scrapers/national/jail_bookings.py`; the booking date is already in `raw['jail_booking']['booking_date']`. |
| `national.jail_bookings` (second defect) | same rows | Promote a per-inmate identifier into `parcel_id`/`case_number` so `dedupe_key()` stops falling back to `url:<portal root>`. |
| `counties_sc.pickens_tax_sale` | 160 | Add `"counties_sc.pickens_tax_sale"` to `main.DATELESS_OK_SOURCES` (~line 302). One line. |
| `counties_sc.terry_howe_flc` | 82 + pagination | Route the title through the engine's existing `_upstate_city_to_county` lookup instead of requiring literal `<County> County, SC`; add pagination past page 1 of 6. |
| `counties_sc.spartanburg_master_in_equity` | 19 | Add to `DATELESS_OK_SOURCES` (same for `anderson_master_in_equity` 14 and `pickens_master_in_equity` 4). |
| `counties_sc.sc_rod_cott` (Union) | 38 | Promote `legal_description` parcel and situs into `parcel_id` / `street_address`. Fixes Union's only county-specific source outright. |
| `newspapers.hendersonville_lightning` | 5 | Add `"newspapers.hendersonville_lightning"` to `DATELESS_OK_SOURCES` (~line 302). One line. |
| `law_firms.alaw`, `law_firms.ingle_firm`, `city_websites.search`, `counties.sitemap_walker`, `public_notices.funeral_home_rss` | 266 | Same: give each a lane (`DATELESS_OK_SOURCES` or `FORECLOSURE_SALE_SOURCES`). |
| `national.cash_buyer_deeds` | ~330/run | **No fix known.** Cause not determined. Needs its own investigation; this is the largest unexplained loss on the board. |
| `national.crexi_multifamily` | ~220/run | Teach the parser the `/search/multifamily-properties-for-sale/{st}` card DOM. Currently treats the permanent 30x redirect as `no_grid`. Produced 226/227/169/228 through 07-10, **0 since 07-24, with no alarm.** |
| `counties_nc.nc_rod_substitute_trustee` (Burke/CCHS) | 11 | Fetches 19 on 08-02, board has 3 rows last seen 07-01. Diagnose the write path. |

## NOT WIRED (build, not fix)

| Gap | Rows | Note |
|---|--:|---|
| Cherokee SC delinquent-tax ledgers | 529+ TMS | PDFs live in `wp-json/wp/v2/media`, never anchored. Needs a media-index reader, not an anchor scraper. |
| `nc_heir_estate_parcels` Oconee | 60 | Exclusion comment is factually wrong; layer returns heir/estate parcels today. |
| Gaston NC property-tax arrears | unmeasured | In no tax module at all. |
| Anderson SC delinquent-tax roll | unmeasured | No source of any kind wired. |
| Cherokee SC parcel layer | 12,764 polys / 7,116 address points on `canoewood/SC_GaffneyCity_01` | The county's only free parcel layer, unwired. Would address Cherokee's 100%-unreachable and zero-heirs/zero-absentee status. |
| `counties_nc.nc_ptscloud_delinquent_tax` Buncombe | n/a | Buncombe is not a tenant. Correct. |
| `counties_sc.sc_dew_lien_registry` | n/a | Cross-reference only, feeds `enrichment_dew_liens`. By design. |
| `counties_sc.greenville_tax_distress` | n/a | Disabled by operator scope policy (`FORECLOSURE_INCLUDE_GREENVILLE` unset). |

## DEAD URL

| Source | Evidence | Fix |
|---|---|---|
| `law_firms.korn` | `kornlawfirm.com/foreclosure-sales/` returns 200 at **1,130 bytes**, a domain-parking shim | Retire the slug. |
| `newspapers.shelby_star` | `/legal-notices/` **404**; `/public-notices` is a Gannett Next.js shell whose only content is links to ncnotices.com | Retire. `nc_notices_counties` pulled 512 rows from ncnotices today. |
| `newspapers.tryon_bulletin` | `/category/legal-notices/` **404**; WP search returns only editorial articles | Retire or re-point once the paper's legals vendor is identified. |
| `national.estate_sales` | `estatesale.com/search?zip=` **404 on all 4 zips**; only `estatesales.net` works | Drop the dead host. |
| `counties_nc.nc_rod_substitute_trustee` + `cash_buyer_deeds` (Polk, Cott) | `SrchDocType.aspx` and `SrchName.aspx` return the **identical 54,258-byte body** titled "eSearch | Quick Name Search". The doc-type form is gone, so the POST binds to nothing and `cott.py` swallows it silently. | Re-point at the surviving form; add a log on the empty return. |
| `counties_sc.sc_tax_delinquent` (Spartanburg, Union) | Spartanburg `/delinquent-tax` **404** and `/treasurer` **404**; Union `countyofunion.com` **connection reset** | Re-point both to their live CivicEngage paths. |
| `counties_nc.gaston_surplus_properties` | Not broken. The anchor correctly resolves to the new id `/DocumentCenter/View/9608`; the PDF says "There are no surplus properties at this time. July 2026" | Update the stale `SURPLUS_PDF_FALLBACK` (1686 to 9608) so the fallback is not a dead id. |

## WALLED (no compliant free fix)

| Source | Wall | Inventory behind it |
|---|---|--:|
| `counties_nc.rutherford_wildfire_tax` | Both `d1ebsyxxbc7tep.cloudfront.net` and `avalon.sturgiswebservices.com` publish `User-agent: * / Disallow: /`. Robots guard fails closed by design. | **29,319** rows (vendor's own `TotalRecords`) |
| `national.cash_buyer_deeds` / `nc_rod_substitute_trustee` (Rutherford) | `cotthosting.com/NCRUTHERFORDEXTERNAL` now returns "eSearch | Account Sign In". **New wall.** | unmeasured |
| `law_firms.mewborn_deselms` | Cloudflare, 4x HTTP 403 across all three tiers today. Correctly raises as BLOCKED. | unmeasured |
| `national.landsofamerica` | Akamai. `landsofamerica.com` and `land.com` both 403 with `_abck` in the body. Stealth gets ~414 bytes and hits the `len(html) < 5000` guard **with no log at all.** | never produced |
| `public_notices.publicnoticesc` | Cloudflare. Documented stub, no network issued. | unmeasured |
| `national.foreclosure_dot_com` | Edge WAF 403 to GET/impersonate/stealth, plus paid preview | redundant with auction.com/Xome |
| `counties_nc.nc_ecourts_estates` | AWS WAF CAPTCHA, unsolvable | NC estates partly covered via Column |
| SC Public Index / `sc_county_rosters` | Disclaimer Accept click is a terms acceptance; deliberately not automated in the audits | unmeasured, **not zero** |

## FILTERED (working as designed)

- `national.gsa_realproperty`: index returns 200, **12 active asset ids nationwide, 0 in NC/SC**. Keep as a watcher.
- `national.probate_foreclosure_leads`, `national.propwire`: policy stubs, paid, deliberately return `[]`. Retire or gate behind an explicit paid flag.

## GENUINELY EMPTY (verified upstream, no action)

`counties_nc.buncombe_tax_foreclosure` (0 VEVENTs), `newspapers.daily_courier` (3 index pages, 10 detail ads fetched, all NOTICE TO CREDITORS), `newspapers.index_journal` (9 legal items, all NOTICE TO CREDITORS; `q=foreclosure` returns 0 items), `law_firms.aldridge_pite` (tbody 0 rows; add an explicit "empty table" log so a parser break cannot hide here), `counties_sc.oconee_tax_sale`, `counties_sc.cherokee_delinquent_tax` (3 PDFs, all procedural), `nc_ptscloud` Rutherford and Burke (valid tenants, `GetTaxpayerDownloadList` returns `[]`; Henderson on the same host returns a 5.9 MB blob dated today, so the probe is sound), `nc_rod_logan` Mitchell (host responds, 0 distress in 60 days, county pop ~15k), `newspapers.shelby_star` (**CAPTURING-unverified**: returns nothing two runs running, and nobody independently confirmed the page has no legals).

---

# 5. PARTIAL-DATA RISK

Static AST scan found **97 swallow sites across 66 modules** (82 in 55 scrapers, 15 in 11 enrichers): loops over declared endpoint/layer/county/page/feed sets containing a handler that continues, passes or breaks without re-raising. Only **4 modules** have adopted `LayerHarvest` (`pickens_delinquent_parcels`, `oconee_flc_assignment`, `oconee_forfeited_land`, `enrichment_helene_damage`).

Ranked by rows actually at risk today:

| # | Source | Rows shipped | Exposure | Fix |
|--:|---|--:|---|---|
| 1 | `counties_nc.nc_ptscloud_delinquent_tax` | **21,463** | Declares **17** tenants, logged **8** `tenant_done`. The other 9 (Burke, Cumberland, Durham, Hertford, Mecklenburg, Randolph, **Rutherford**, Stokes, Wayne) produced **zero log lines**. `_download_delinquent_csv` has **5 silent `return None` exits** and `if not text: continue` logs nothing. Three probed live today return 200 with an empty blob list, so today's data is intact, but a broken endpoint and an empty one are indistinguishable on the largest source in the board. | `LayerHarvest` over `TENANTS`; log `tenant_empty` vs `tenant_fail` distinctly. |
| 2 | Spartanburg `0 <STREET>` dedupe merge | suppresses ~1,216 | `dedupe._strong_sigs` builds `("s", canon_street, county, state)` and union-merges on it. Vacant parcels publish situs as `0 <STREET>`: 33 parcels on `0 southport rd`, 33 on `0 pine st`, 22 on `0 caulder ave`. 4,590 addressed rows collapse to 3,374 canonical streets (predicted 3,443 groups vs 3,460 observed). All 5,014 TAXPINs are distinct, so this is not intra-source parcel dedupe. **Will do the same to `pickens_delinquent_parcels` (2,161 rows, same shape) the moment it lands.** | Blacklist a `0` house number in `_strong_sigs`, which already blacklists `vacant` / `lis pendens` / `property in`. |
| 3 | `national.landwatch` + `national.landandfarm` | 650 + 650 | **Pagination is dead.** All ~26 counties logged exactly `found:25, new:25` then stopped; no page-2 `page_done` anywhere. `f"{base_url}?page={page}"` against a site whose pagination is a **path segment**, so page 2 re-serves page 1, `new == 0`, silent break. The docstring itself says "most counties have 2-5 pages". Rows behind pages 2+ are **unmeasured**. | Use the real page path; make the `new == 0` break logged and guarded. |
| 4 | `national.auction_dot_com` | 388 | Same dead pagination: NC page 2 `found:309, new:0`, SC page 2 `found:79, new:0`. Capped at page 1 per state. Counts drifting 516 to 495 to 471 to 443 to 388. | Fix the page param; alarm when page N returns an identical id set. |
| 5 | `national.crexi_multifamily` | 0 (was ~220) | Went from 228 to 0 between 07-10 and 07-24 with **no alarm**, because the `/search/` redirect is swallowed as `no_grid`. | See section 4. |
| 6 | `counties_nc.nc_heir_estate_parcels` (Laurens) | 78 | `_PER_COUNTY_CAP = 80` against 169 upstream. **54% of Laurens' heir inventory never leaves the scraper.** | Raise or remove the cap for high-inventory counties. |
| 7 | `national.courtlistener_adversary` | 158 | **4 of 15** court x phrase searches truncated today (scb/lift stay, scb/363 sale, scb/abandonment, ncwb/relief from stay), each a `break` out of pagination. The `error` field is an **empty string** on all four, so the cause is not even recorded. | Retry the search page the way `brock_scott._page` does; log `type(exc).__name__` when `str(exc)` is blank. |
| 8 | `counties.sitemap_walker` | 30 | **13** endpoint failures absorbed: polknc.gov 404 x3, hendersoncountync.gov 403 x5, co.pickens.sc.us 404 x3, spartanburgcounty.gov 404 x2. | Declare the host set and hard-fail on a shrunken sweep. |
| 9 | `counties_sc.sc_public_index` | 1,743 | 2 swallow sites over `SEARCHES`; no failures logged today, but a dropped search is invisible. **This source has previously vanished whole (3,628 rows) with no alarm.** | `LayerHarvest` over `SEARCHES`. |
| 10 | `counties_nc.nc_county_pdf_delinquent_tax` | 8,922 | 1 swallow site over a county/PDF set. No failures today, but a dropped county is a 4-figure silent hole, and Lincoln proves this source drifts. | `LayerHarvest`. |
| 11 | `counties_sc.spartanburg_condemned` | 1,668 | 1,830 emitted, 1,753 accounted for, same street-collapse family. Per-row split **unmeasured**. | Same as #2. |
| 12 | `link_validator` (cross-cutting) | tags 3,819 bankruptcy rows | Self-inflicted: 24-way concurrent HEADs drew **1,043 of 3,349 `429`s** from courtlistener.com (31%). No rows drop, but ~1,000 leads get `link_check.status="auth"` purely from our own rate pressure. | Lower concurrency against courtlistener. |

---

# 6. THE HONEST BOTTOM LINE

## The number

**Measured floor: we are capturing 53.7% of the leads we have actually measured upstream.**

24,935 footprint leads on the board against 46,456 measured-available (24,935 + 21,521 quantified rows that exist upstream and are not on the board). Not rounded up.

That 21,521 splits:

| | Rows | Confidence |
|---|--:|---|
| Built or fixed after the 07-31 scrape, running clean today, awaiting first board write | **17,146** | Predicted, **unproven**. Includes rutherford_tax 9,323, pickens_delinquent_parcels 2,161, buncombe multi_year 2,078, oconee multi_year 1,561, sc_public_notices 952, oconee_flc_assignment 583, henderson trio 222. |
| Confirmed broken, will not self-heal without a code change | **4,375** | Measured. Includes Spartanburg street-collapse 1,216, Lincoln ID drift 1,205, Anderson jail 529, Cherokee media 529, cash_buyer_deeds 320, pickens_tax_sale 160. |

**If everything pending lands intact, capture rises to 90.6%.** Treat that as a ceiling, not a forecast: `pickens_delinquent_parcels` alone will hit the `0 <STREET>` merge bug on arrival, and the pending figure carries known double-counting (Buncombe `multi_year` 2,078 overlaps `buncombe_delinquent_tax` 1,181; Pickens `multi_year` overlaps `pickens_delinquent_parcels` by design; `rutherford_tax` 9,328 is tax **bills**, not distinct parcels). A realistic post-run capture is materially below 90.6% and **cannot be stated until the run writes.**

## What is genuinely unknown

**The single largest unknown is not a scraper.** The 07-31 run logged `orchestrator.board_persist merged_count=32143`. The artifact committed two days later was 25,576, and today's is 25,552. **Roughly 6,500 leads disappeared between persist and commit. The mechanism is unmeasured.** This caps capture rate for every source in every audit above, regardless of scraper health, and it should be investigated before any of the one-line fixes.

Everything else that is unmeasured, stated plainly:

- **`national.cash_buyer_deeds`, ~330 rows/run.** Slug whitelisted, counties in scope, no filter explains the loss, board `first_seen` for the 24 surviving rows spans 5 dates so it is not one bad run. **Cause not determined.**
- **`public_notices.nc_notices_counties` per-county split.** 512 rows statewide today across 11 ticked counties. How many are footprint is unmeasured. The 900s Playwright flow was declined while the live run was hitting the same host.
- **`counties_sc.sc_public_notices` true upstream.** Two audits produced 952 and 71 by different methods. Unreconciled.
- **`counties.multi_year_delinquent_tax` real per-county yield.** The reported totals are internally inconsistent (see 3c.1). Pickens' share is not logged at all.
- **SC Public Index and `sc_county_rosters` upstream.** Behind a disclaimer Accept click, deliberately not automated. **Unmeasured, not zero.** These already contribute 1,743+ board rows via the manual saved-page lane.
- **Cherokee Zuercher roster size.** Not re-fetched: the endpoint returns DOB in every record and cannot be column-limited. The dedupe collapse is proven regardless of roster size.
- **`landwatch` / `landandfarm` / `auction_dot_com` pages 2 and beyond.** Confirmed unreachable by dead pagination, volume unmeasured. The landwatch docstring says most counties have 2-5 pages, so the shipped 1,300 rows may be roughly a quarter to a fifth of what is there.
- **`law_firms.alaw` county split.** 26 rows (18 NC / 8 SC) with no lane. Statewide NC trustee firm, could carry any footprint county.
- **`counties_nc.asheville_helene` exact reconciliation.** 652 upstream, 172 primary, 216 anywhere, with 242+74+44 traceable across three `also_seen_in` paths. The arithmetic has not been closed.
- **Whether Henderson's "May 27, 2026" tax-foreclosure table is finished or stale.** 15 leads hinge on it and the page gives no signal.
- **`newspapers.shelby_star`.** Marked CAPTURING-unverified. Two consecutive runs of zero, with no independent confirmation that the page carries no legals.

## What is known and is not a gap

- 29,319 delinquent rows behind Rutherford's robots wall are **not free-obtainable**. Ask Rutherford or Sturgis for access.
- `upset_bid` absent in SC is statute, not coverage.
- NC Cherokee and NC Union are scope-denied, so SC-only rows are correct.
- Six of the 21 zero-producers from the last complete run are already healthy today: `buncombe_tax` 0 to 33, `polk_tax` 0 to 1, `hutchens` 0 to 86, `nc_upset_bids` 0 to 35, `sc_flc` 0 to 44, `treasury_seized` 0 to 1.

## The two sentences that matter

We can account for where nearly every missing lead is, and roughly four-fifths of the shortfall is code that has already been written and is sitting one board write away from landing. The part that should worry you is not the 4,375 confirmed-broken rows, it is that a full run persisted 32,143 leads and the committed artifact holds 25,552, and nobody has measured why.