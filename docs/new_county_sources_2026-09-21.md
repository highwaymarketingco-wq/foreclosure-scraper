# New county sources, built 2026-09-21

Built from `docs/county_breadth_research_2026-09-21.md` (ranked build list, section 7). Everything here is free and
public: no login, no CAPTCHA, no click-through, no WAF challenge. A robots.txt Disallow is not treated as a wall (owner
decision 2026-09-20). Requests were one at a time with a browser User-Agent, a handful per source. Nothing was scraped
into the board, no `--apply` was run, `load_board` and `write_artifact` were never called, and nothing was staged or committed.

Personal names, mailing addresses and situs of private owners are left out of every sample in this document. Field
names and shapes are real. No workbook, response or owner row was saved in the repository; the tests use invented data.

## 0. Status at a glance

| # | Item | Result | Slug | Listing type |
|---|---|---|---|---|
| 1 | Catalis: Chester, Hampton, Fairfield, Aiken | built, verified live, but NOT the "same schema" the research said | `counties_sc.sc_catalis_delinquent_roll` (extended) | TAX_LIEN (TAX_SALE only with a recorded sale) |
| 2 | Column API: 5 NC counties, 3 SC Pee Dee counties | built, verified live | `counties.column_legal_notices` (extended) | TAX_SALE (NC tax foreclosures), PROBATE_NOTICE |
| 3 | Onslow and Graham tax portals | built, verified live, one shared module | `counties_nc.nc_its_public_tax` (new) | TAX_LIEN |
| 4a | Charleston tax-sale spreadsheet | built, verified live | `counties_sc.charleston_tax_sale_xlsx` (new) | TAX_SALE with the sale date |
| 4b | Horry delinquent spreadsheet | built, verified live | `counties_sc.horry_delinquent_xlsx` (new) | TAX_LIEN |
| 5 | Albemarle Observer lists | built for Tyrrell, Washington (county and Plymouth), Gates, Bertie | `counties_nc.albemarle_observer_tax_lists` (new) | TAX_LIEN |
| 6 | Greenville URL and CivicPlus hosts | fixed, each replacement verified with one request | (existing files) | n/a |
| 7 | Ingest script | built, dry run executed, `--apply` NOT run | `scripts/ingest_new_county_sources.py` | n/a |

Tests: 151 new tests pass, all offline (`tests/test_catalis_new_counties_2026_09_21.py` 32, `test_column_new_counties_2026_09_21.py` 25,
`test_nc_its_public_tax.py` 18, `test_charleston_horry_xlsx.py` 18, `test_albemarle_observer_tax_lists.py` 17,
`test_greenville_civicplus_urls_2026_09_21.py` 7, `test_ingest_new_county_sources.py` 34). The existing suites for the edited files also pass
(Catalis 28, Column 4, Greenville 38). Run: `uv run python -m pytest -q -p no:cacheprovider tests/<file>`.

## 1. REQUIRED edits in files I do not own (two existing tests fail until they land)

`tests/test_source_docs_current.py::test_every_registered_scraper_appears_in_the_register` and
`tests/test_raw_keep_covers_enrichers.py::test_every_scraper_raw_key_survives_publish` fail today for exactly these reasons and
no other. Both are one-line class fixes in files the brief reserves for others.

### 1a. `docs/net_new_source_register.md` (or `SOURCE_REGISTER.md`): four slugs

The register test requires every registered slug to appear in one of those two files. Paste this block:

```
### County breadth build, 2026-09-21 (docs/new_county_sources_2026-09-21.md)
- `counties_sc.sc_catalis_delinquent_roll`: extended to Chester, Hampton, Fairfield, Aiken. API `https://d1ebsyxxbc7tep.cloudfront.net/data/<GUID>/Records`; sites `chestercountysctax.com`, `hamptoncountytax.org`, `fairfieldsctax.com`, `aikencountysctax.com`.
- `counties_nc.nc_its_public_tax`: Onslow `https://tax.onslowcountync.gov/ITSPublicON/TaxBillSearch`, Graham `https://www.bttaxpayerportal.com/ITSPublicGR2.0/TaxBillSearch`. Unpaid property tax, no login.
- `counties_sc.charleston_tax_sale_xlsx`: `https://www.charlestoncounty.gov/departments/delinquent-tax/files/tax_sale/RP-Tax-Sale-Listing.xlsx` and `MH-Tax-Sale-Listing.xlsx`.
- `counties_sc.horry_delinquent_xlsx`: link discovered on `https://www.horrycountysc.gov/departments/treasurer/delinquent-tax/` (dated `delinquent-list-on-website-MMDDYY.xlsx`).
- `counties_nc.albemarle_observer_tax_lists`: `https://albemarleobserver.news/wp-json/wp/v2/posts` (WordPress REST, delinquent-tax list posts for Tyrrell, Washington, Plymouth, Gates, Bertie).
```

### 1b. `src/foreclosure_scraper/web_artifact.py` `RAW_KEEP`: four keys

`_slim_raw` drops any raw key not named there, silently. The source-specific detail blocks of three new scrapers are
otherwise discarded at publish (the Listing fields and `raw["tax_owed"]` still land). Add:

```
    "nc_its_public_tax": "*", "horry_delinquent_xlsx": "*", "albemarle_observer_tax_list": "*",
    "column": "*",   # EXISTING GAP: Column's raw["column"] block (paper, pdfurl, snippet, tax_foreclosure) is dropped at publish today
```

`catalis_roll`, `charleston_delinquent_tax` (reused on purpose for the xlsx rows), `tax_owed`, `two_year_delinquent`,
`probate`, `notice_contact`, `document_url`, `also_seen_in` are already allowlisted. The `raw["column"]["tax_foreclosure"]`
sub-block (multi-parcel list, county tag) rides inside the dropped `column` key; the case number, parcel, plaintiff,
owner and sale date are Listing fields and survive.

### 1c. `src/foreclosure_scraper/main.py` `DATELESS_OK_SOURCES`: three slugs

Only needed for a FULL pipeline run. `_active_only` deletes any dateless row whose source is not listed. The ingest script
does not depend on it (it exempts dateless standing rolls from `_active_only`, section 9). Add:

```
    "counties_nc.nc_its_public_tax",            # Onslow/Graham standing roll, no sale date
    "counties_sc.horry_delinquent_xlsx",        # Horry delinquent list, pay-by deadline not a sale
    "counties_nc.albemarle_observer_tax_lists", # NC annual delinquent lists, no sale date
```

`counties_sc.sc_catalis_delinquent_roll` is already there. The Charleston xlsx rows and the Column tax-foreclosure rows carry
a real sale date, so they pass `_active_only` on their own until the sale plus its window has passed.

### 1d. After landing, not blockers

* Run `scripts/join_parcel_cache_to_board.py` so the new rows pick up mail, value and situs from the parcel caches (Chester and
  Hampton have `PARCEL_LAYERS` caches, Charleston and Horry have overlays, Onslow, Graham, Tyrrell and Bertie join NC OneMap `parno`).
* Fairfield and Aiken publish SC Code 30-2-50 commercial-solicitation notices with their tax-sale materials. It does not block
  fetching; it bears on how the owner mailing addresses from those two counties may be used.

## 2. The owner rule and how each source follows it

Flips (`FORECLOSURE_SALE`, `AUCTION`, `SHERIFF_SALE`, `HOA_SALE`, `REO`) are in scope only in the 18 footprint counties.
Everything else is in scope in all 146 NC and SC counties. `main._in_scope` enforces it at the pipeline; the ingest script runs
the same function on every new row.

| Source | Counties | In footprint? | Types emitted | Never emitted |
|---|---|---|---|---|
| Catalis new counties | Chester, Hampton, Fairfield, Aiken | no | TAX_LIEN; TAX_SALE only when a row carries a `TaxSaleRedemptionDate` | FORECLOSURE_SALE |
| Column NC | Washington, Hertford (tag; carries Northampton), Bertie, Gates, Martin | no | TAX_SALE (tax foreclosure with a sale date), TAX_LIEN (without one), PROBATE_NOTICE | FORECLOSURE_SALE (a mortgage foreclosure there is a flip: counted in the log and dropped) |
| Column SC | Florence, Marion, Marlboro | no | PROBATE_NOTICE | FORECLOSURE_SALE |
| ITS, xlsx, Albemarle | Onslow, Graham, Charleston, Horry, Tyrrell, Washington, Gates, Bertie | no | TAX_LIEN (standing roll); Charleston TAX_SALE (dated 2026-11-09) | any flip type |

Scorer expectations (`distress_score._LISTING_TYPE_SIGNAL`): TAX_LIEN is FINANCIAL 20. A TAX_SALE with no upcoming date is
weighted 20 as well (F10), with an upcoming date 30. So a standing roll typed TAX_LIEN and the existing Pickens rows typed TAX_SALE
score the same; the new sources follow the rule "TAX_LIEN for a standing roll, TAX_SALE only with a real sale date". Every tax
row also writes `raw["tax_owed"] = {balance, kind, source, year, basis}` directly, so the scorer's `recorded_debt` (+12) fires
without waiting for `enrich_tax_owed`. Multi-year sources write the published `raw["two_year_delinquent"]` that `fullmer_rank` reads.

## 3. Catalis: Chester, Hampton, Fairfield, Aiken

**File:** `src/foreclosure_scraper/scrapers/counties_sc/sc_catalis_delinquent_roll.py`. **Tests:** `test_catalis_new_counties_2026_09_21.py` (32), existing `test_catalis_delinquent_roll.py` (28, unchanged).

**Endpoint:** `POST https://d1ebsyxxbc7tep.cloudfront.net/data/<GUID>/Records` with
`{"year":-1,"payStatus":"Unpaid","type":"Property","parameter":"Name","value":"<prefix>"}`, `Referer`/`Origin` set to the county site.

| County | Data GUID | Site |
|---|---|---|
| Chester | `61020303-8d26-4a16-b995-6deb1def7d97` | `https://chestercountysctax.com` |
| Hampton | `38077f99-bf3d-48df-8d9a-467eb4de0d64` | `https://hamptoncountytax.org` |
| Fairfield | `89835e71-6978-4dc5-a0a8-17306a76b81f` | `https://fairfieldsctax.com` |
| Aiken | `27a11acb-7de9-43e7-a078-f98cfb4fc397` | `https://aikencountysctax.com` |
| Pickens (existing) | `c9ab58ea-c187-4c02-ad9d-b18dd6167431` | `https://pickenscountysctax.us` |

**The research note was wrong about the schema.** It said all four share Pickens' record shape and need no parser change.
One request each showed three different shapes, so a config-only add would have returned nothing for Fairfield and Aiken:

| County | Real-property delinquent row |
|---|---|
| Chester, Hampton | `RecordType "Delinquent"` and `RealPropertyType true`, as Pickens. Chester also carries `AssessorData` (the CURRENT owner; on 48 of 71 rows the bill's `OwnerName1` is a different name). |
| Fairfield | `RecordType "Real"`, `RealPropertyType null`, delinquency marked `DelqSw true`; situs is in `Description`. |
| Aiken | `RealPropertyType null` everywhere. Real delinquents are `RecordType "Delinquent"` WITH a `ParcelNumber` and `DelqSw true`. "Delinquent" rows with no parcel and a `BillingID` starting `M` or `P` are business personal property (21 of 47 in one prefix: 19 with an `M` billing id and 2 with `P`; the other 26 are real). 125 of 740 rows were `"Mobile Home"` bills; excluded unless `CATALIS_ROLL_MOBILE_HOMES=1`. |

**Live verification** (2026-09-21, one POST per county, then the same through the real code path):

| County | Prefix | Records | Real delinquent bills | Parcels | Balance read | With mailing | With street |
|---|---|---|---|---|---|---|---|
| Chester | BROWN | 351 | 71 bills (2016 to 2025) | 18 (11 two-year-plus) | $50,868.85 | 18 of 18 | 3 of 18 |
| Hampton | BROWN | 89 | 72 bills (2013 to 2025) | 44 (8 two-year-plus) | $65,710.65 | 44 of 44 | 0 of 44 |
| Fairfield | ALSTON | 51 | 3 | 3 | $1,184.51 | 3 of 3 | 2 of 3 |
| Aiken | BROWN | 740 (3.2 MB) | 26 real, 125 mobile homes excluded | 25 | $13,112.35 | 25 of 25 | 18 of 25 |

Chester's 71 bills read back as 18 bills the first time: Chester and Hampton use the parcel number as the `BillingID` of every tax
year's bill, so the sweep's dedupe key (`BillingID`) collapsed a parcel delinquent since 2016 to one bill. The key now includes
the year, and the four new counties are aggregated to one lead per parcel with the years summed. A live full sweep was NOT run,
so no full-county row count exists. The request count is: 36 first-level prefixes plus 36 per capped prefix; at the 8 s pace
(about 450 an hour) the default 600-request budget is roughly 80 minutes per county and will bind on Chester and Hampton at depth
2. Aiken's responses run about 3 MB, so it is limited to depth 2 and 400 requests and will be INCOMPLETE by design (logged as
`catalis_roll.depth_truncated`). Run one county at a time with `CATALIS_ROLL_BUDGET=1500` overnight if a full roll is wanted.

**Fields mapped:** parcel, owner (current owner where the county gives it, billed name kept in `raw.catalis_roll.billed_owner`),
mailing address (`raw.catalis_roll.owner_mailing`, 100% in every sample), situs (only when it looks like a street address; mobile-home
text and lot descriptions go to `legal_description`), appraised value (`tax_value`), acreage, and the balance
(`Values.AmountDue`, base tax plus penalty plus costs at read time) into `raw.catalis_roll.total_due`, `raw.tax_owed` and
`raw.two_year_delinquent`. Occupancy from the 4% versus 6% assessment ratio is kept, never invented (None when the county gives no split).

**Safety changes:** a 403 now raises `CatalisBlocked`, stops the sweep, cancels sibling tasks and skips the remaining counties (same
host). `scripts/weekend_runner.sh` records the host went 429 then 403 against the Pickens sweep on 2026-09-11 and that working
around a 403 is off the table; the old loop retried a 403 five times with 30 s backoff. Rows also append to `self.partial`, so
the 600 s soft timeout ships what was read instead of `[]`.

**Type:** TAX_LIEN for the new counties. Pickens stays TAX_SALE, per bill, unchanged (its rows are already on the board that way).
**Ingest:** `uv run python scripts/ingest_new_county_sources.py --apply --sources catalis --harvest logs/new_county_catalis.json`
(hours; run alone, one county at a time via `--catalis-counties Chester`).

**Risks:** the host serves `Disallow: /`, rate limits with 429 and escalated to 403 once; the sweep is slow by design and
incomplete under budget; Aiken and Fairfield mailing use is bound by SC Code 30-2-50; amounts are as of read time and include
penalties; `Hampton` real rows have no street address in the sample (situs is a mobile-home text), so they need the parcel cache.
The `parameter: "Parcel"` search exists (`GET .../SearchOptions` returns `["Name","Receipt","Parcel"]`) but is not used: a
2-digit prefix on Chester returned the 1,000 cap with 593 vehicles, so it does not isolate real property.

## 4. Column legal-notice API: five NC counties and the Pee Dee

**File:** `src/foreclosure_scraper/scrapers/newspapers/column_legal_notices.py`. **Tests:** `test_column_new_counties_2026_09_21.py` (25), existing `test_column_notice_contact.py` (4).
**Endpoint:** `POST https://us-central1-enotice-production.cloudfunctions.net/api/search/public-notices`.

**Live verification** (one query per county and type, 365 days for foreclosure, 120 for estates):

| County (Column tag) | Foreclosure Sale notices | Unique | Tax foreclosures | Notes |
|---|---|---|---|---|
| Washington | 16 | 8 | 8 | plaintiff "COUNTY OF WASHINGTON" (and Town of Plymouth), parcels like `6767.12-85-4828` |
| Hertford | 14 | 7 | 5 | ALL are Northampton notices ("COUNTY OF NORTHAMPTON vs."); county re-derived |
| Bertie | 4 | 2 | 0 | both are mortgage foreclosures, dropped |
| Gates | 8 | 4 | 4 | sales Dec 2025 (outside the 120-day window today) |
| Martin | 16 | 8 | 3 | 3 tax foreclosures by the Town of Williamston; 5 mortgage, dropped |
| Florence (SC estates) | 31 | 13 | n/a | 120 days |
| Marion (SC estates) | 94 | 36 | n/a | 120 days |
| Marlboro (SC estates) | 111 | 42 | n/a | 120 days |

Through the real code path (Gates, Washington, Florence only, 8 requests): 1 NC tax_sale after case-and-parcel dedupe, 13 Florence
probate notices with case numbers such as `2026ES2100725`.

**What changed.** `NC_DISTRESSED_ONLY = (Washington, Hertford, Bertie, Gates, Martin)` and `SC_DISTRESSED_ONLY = (Florence, Marion, Marlboro)`
are new tuples beside the footprint tuples. NC "Foreclosure Sale" notices there run through `is_tax_foreclosure` ("TAX FORECLOSURE"
including the OCR break "FORECLO- SURE"); a tax foreclosure becomes a `TAX_SALE` (or `TAX_LIEN` with no date) parsed by
`_parse_nc_tax_foreclosure` (plaintiff, first named defendant cut before "and X's spouse", case `25CV000168-930`, "on the 23rd day of
July, 2026", every `Parcel Identification Number`, county from "District Court of X County" then from the plaintiff); a mortgage
foreclosure is counted in the log (`column.nc_tax_foreclosure ... mortgage_foreclosures_dropped`) and never emitted. Estates in those
counties ride the existing estate lanes; the county of a Hertford-tagged estate is re-read from "NORTH CAROLINA, X COUNTY".
`ColumnLegalNotices.only_new_counties` reads only the new counties and skips the statewide SC query (the ingest script uses it).
The SC case-number regex now accepts the un-dashed form Florence and Marlboro print.

**Footprint check for SC.** SC "Foreclosure Sale" notices are Master-in-Equity mortgage foreclosures, so in non-footprint counties they
are flips. The existing statewide lane still emits them as FORECLOSURE_SALE for Florence and the others and the scope gate drops them;
that is unchanged. SC tax sales are not court foreclosures and do not appear in that notice type.

**Type:** TAX_SALE and PROBATE_NOTICE. **Ingest:** `--apply --sources column`.
**Risks:** tax-foreclosure notices carry sale dates that are mostly past by the time they are read (all 5 in the dry run were past
the 14-day window and would be dropped by `_active_only`), so the durable yield is the estate lane: SC Pee Dee notices are name-only
and need the name-to-property resolver (Florence has a parcel cache; Marion and Marlboro do not); Column's 250-row cap is not reached
at 120 days; the same notice republishes under `-0`, `-1` ids and is collapsed on the base id.
**Not built:** Marion's delinquent tax sale ad (`noticetype "Public Auction"`) has 9,000 characters of OCR text, but the table is
scrambled across columns (names, tax maps and amounts are not aligned), so owner-to-parcel pairing is unreliable; it needs the Gemini
document OCR and is left to that lane.

## 5. Onslow and Graham (ITSPublic tax portals)

**File:** `src/foreclosure_scraper/scrapers/counties_nc/nc_its_public_tax.py` (one class, two portals, same vendor). **Tests:** `test_nc_its_public_tax.py` (18).

* `https://tax.onslowcountync.gov/ITSPublicON/TaxBillSearch`, `https://www.bttaxpayerportal.com/ITSPublicGR2.0/TaxBillSearch`.
* Flow: `GET` the search page (session cookie), `POST .../GetSearchTablePartial {"PageSize":100,"UnpaidBillsOnly":true,"TaxYear":"2025"}`
  (stores the search in the session), then `POST .../GetSearchTableData {"Page":n,"NumRows":100,"Table":"PayTaxBills"}`. `NumRows` 100 is
  honoured (the UI default is 25), so Onslow's 7,428 bills are 75 requests, not 298. Paced 1.5 s.
* **Live verification:** Onslow `numRecords 7428`, 75 pages (matches the research); Graham `numRecords 925`, 10 pages. Through the code
  path with a 100-row cap: Onslow 100 leads, $74,829 due, 84 with a street and all with city and zip; Graham's first page had 74 real bills
  and 26 "Personal Property" rows, which are dropped.
* **Rows:** `["2025","72","496055000","<OWNER>","<parcel>...","2,205.73","2,387.48"]`; the description is `<br/>` separated (Onslow: zero-padded bill number, parcel, situs with city
  state zip, "0.150 AC"; Graham: parcel, alternate id, situs, "0.280 AC"). Real property ends in an AC/LT/UT quantity; personal property
  does not and is dropped. Onslow parcels (`801-154`, `1114E-57`) are the same format the board already holds for Onslow.
* **Years:** NC tax year Y is delinquent from January 6 of Y+1, so the newest delinquent year is (this year minus 1) and a 2026 bill is
  never requested. Three delinquent years are read by default (`ITS_TAX_YEARS_BACK`), summed per parcel.
* **Fields mapped:** parcel, owner, situs split into street, city, zip (Onslow prints no comma, so the county's own place names and street
  suffixes are used; a situs without a house number goes to `legal_description`), acreage, balance (already includes interest), years.
* **Type:** TAX_LIEN. **Ingest:** `--apply --sources its` (about 12 minutes at the pace).
* **Risks:** no mailing address on the list rows (parcel joins NC OneMap); the search state lives in the session, so a lost session raises
  a named error instead of returning an empty roll; Jones (`ITSPublicJN2.0`) returned an empty body in the research and is not configured;
  Onslow's county web pages are behind a Cloudflare challenge, the tax portal is a different host and is not.

## 6. Charleston tax-sale spreadsheet and Horry delinquent spreadsheet

**Files:** `counties_sc/charleston_tax_sale_xlsx.py`, `counties_sc/horry_delinquent_xlsx.py`, the shared stdlib reader `scrapers/_xlsx_stdlib.py`
(openpyxl is not a dependency; the registry skips underscore modules). Workbooks are read into memory and dropped, never written to disk.
**Tests:** `test_charleston_horry_xlsx.py` (18, workbooks built in memory).

**Charleston.** `https://www.charlestoncounty.gov/departments/delinquent-tax/files/tax_sale/RP-Tax-Sale-Listing.xlsx` and `MH-Tax-Sale-Listing.xlsx`,
links discovered on the delinquent-tax page (fallback to those URLs). Live: RP 2,402 PIN rows, MH 1,223, HTTP 200. The title cell carries the
sale date (Monday, November 9, 2026) so rows are TAX_SALE with `sale_date` 2026-11-09. Columns are bound by header name (RP and MH differ).
Mapped: PIN, owner(s), situs (street only with a house number), city, class code to `PropertyKind`, acreage, `TOTAL DUE` to `opening_bid` and
`raw.tax_owed` (a floor: it excludes current-year tax), appraisal to `market_value`. The raw block reuses the existing key
`charleston_delinquent_tax` with the PDF scraper's field names, so it is already published and merges on the PIN with the 1,125 board rows.
Dry-run sample: 25 rows, 24 new, 1 already on the board. **Risk:** the sale is November 9; after the sale plus its window the rows age out by design.

**Horry.** `https://www.horrycountysc.gov/media/b5af14ce/delinquent-list-on-website-081926.xlsx`, link discovered on the treasurer page (the file
is re-dated weekly; the newest by MMDDYY wins). Live: 4,952 rows, 405 with a `New Owner Name`, HTTP 200. The sheet has no amount and no situs and does
not state a sale date (5:00 PM Monday November 30 is the last moment to pay), so rows are TAX_LIEN with `pay_by_deadline` in raw, not a
made-up sale. Mapped: 11-digit PIN (the board's Horry key), item number, billed owner and the new owner (the new owner leads when present),
legal description, mobile-home detection (`14X66`, `STK#`, PIN 998...). Dry-run sample: 25 rows, 2 new, 23 already on the board, which is
honest: the board already carries about 2,460 Horry rows from qPayBill with the balance. This list adds "the treasurer is carrying it to sale",
the changed-owner signal and the legal description.

**Type:** Charleston TAX_SALE (dated), Horry TAX_LIEN. **Ingest:** `--apply --sources charleston,horry`.

## 7. Albemarle Observer lists

**File:** `counties_nc/albemarle_observer_tax_lists.py`. **Tests:** `test_albemarle_observer_tax_lists.py` (17).
WordPress REST is open: `GET https://albemarleobserver.news/wp-json/wp/v2/posts?search=delinquent&per_page=50&_fields=id,date,link,title`, then one
`GET .../posts/<id>?_fields=id,date,link,title,content` per list. Only the newest post per county, only if under 400 days old.

| List | Layout | Rows read live | Keys |
|---|---|---|---|
| Tyrrell | `<li>NAME PARCEL AMOUNT` | 391 | parcel (`T12201001`) |
| Washington (county) | `<li>NAME ACCOUNT AMOUNT [*]` in five `<ul>` under one joint heading | 1,206 | account only |
| Washington (Town of Plymouth) | `<li>NAME $AMOUNT` | 570 (406 owners) | name only |
| Gates | `<p>NAME YEAR SITUS $AMOUNT`, several per paragraph | 1,553 of 1,555 (2 rows are a source glitch: two rows run together) | situs, one row per year, grouped to 620 leads |
| Bertie | `<table>` OWNER, PIN, AMOUNT; PIN is "25A" plus the parcel | 1,537 of 1,574 (PINs of 12 to 13 digits are accepted; the rest did not parse) | parcel |

Bertie's post is titled "personal property", but 4 of 5 sampled PINs matched Bertie parcels in NC OneMap (`parno` after stripping 25A: three
residential, one business), so the rows are real property. Amounts are principal only, as of the date printed in each post (Gates March 31,
Washington June 8). **Fix found while testing:** rows with no parcel and no street all shared one `source_url`, and `Listing.dedupe_key()` falls back to it,
so the board would have collapsed Washington's 1,206 rows to one; each lead now has a per-row `#fragment` and a test pins it.
**Type:** TAX_LIEN. **Ingest:** `--apply --sources albemarle`. **Risks:** the lists re-publish each spring and drift stale; the layouts are the
Observer's, not the county's, and a redesign is logged (`ao_tax.no_rows`) rather than returned as empty; Washington and Plymouth need the
name resolver, Gates joins on `siteadd`.

## 8. URL fixes

**Greenville** (`greenville_hard_distress.py`, still OFF behind `FORECLOSURE_INCLUDE_GREENVILLE`, county still on the flip deny list, neither changed).
The old `https://www.gcgis.org/arcgis/rest/services/GreenvilleJS/Map_Layers_JS/MapServer/52` answers HTTP 200 with
`{"error":{"code":500,"message":"Service GreenvilleJS/Map_Layers_JS/MapServer not found"}}`. Replacement
`https://www.gcgis.org/arcgis3/rest/services/GreenvilleNJ/QueryLayers/MapServer/0`, verified: all 26 `PARCEL_FIELDS` exist, `TOTTAX > 0 AND PAIDDATE IS NULL` returns
**2,855** (the old layer read 5,014), `orderByFields=OBJECTID ASC` with `resultOffset` and `outSR=4326` geometry both work. The service has ONE layer, so the old
sales layer (5) is gone: `SALES_LAYER = None` and the join returns `{}` with no request. The new layer carries `STRPRE, LOCATE, STRTYP, STRSUF`, which the old one
lacked, so the situs is now `209 W PARK AVE` from the parcel row alone. Tests: `test_greenville_civicplus_urls_2026_09_21.py` (7); existing Greenville tests pass unchanged.

**`nc_civicplus_tax_sale.py`.** The four dead hosts fail DNS (curl exit 6). Each replacement fetched once, HTTP 200:
Graham `https://grahamcounty.org` (the `www` form does not resolve), Northampton `https://www.northamptonnc.com`, Tyrrell `http://tyrrellcounty.org` (http only, redirects to `/en/`),
Washington `https://washconc.org`. Only the base hosts were verified; whether each county's site yields a tax-sale page to the sitemap walker was not.

## 9. The ingest script

`scripts/ingest_new_county_sources.py`. Sources: `catalis, column, its, charleston, horry, albemarle`.

**Dry run (default).** Fetches a sample per source, streams `docs/listings.json.gz` ONCE through `board_stream.iter_board_rows`, keeping parcel and address keys only for the
counties in play, and reports per source the rows, coverage, new versus already on the board, what the scope gate would drop, and one sample row (owner masked; `--show-pii` to unmask).
No lock, no `load_board`, no write. Recorded run (2026-09-21, `--limit 25`, 94 s, board scan 170,066 rows in 6.9 s, 15,327 existing rows in the counties in play):

| Source | Fetched | New vs board | Coverage in sample | Notes |
|---|---|---|---|---|
| catalis | 90 | 90 new, 0 on board | 90 parcel, 90 owner, 90 balance, 23 street | Hampton 44, Aiken 25, Chester 18, Fairfield 3 (one surname each); $130,876 due |
| column | 98 | 98 new | 93 probate (SC Marlboro 42, Marion 36, Florence 13, NC Hertford 2), 5 tax_sale (Northampton 2, Martin 2, Washington 1) | the 5 tax sales were past the window: scope gate would drop 5 |
| its | 50 | 50 new | Onslow 25 and Graham 25, 36 with street, all with balance | $20,048 due |
| charleston | 25 | 24 new, 1 on board | dated 2026-11-09, 22 street | $256,306 due |
| horry | 25 | 2 new, 23 on board | parcel and owner only | no amount on the sheet |
| albemarle | 125 | 125 new | Washington 50, Tyrrell 25, Gates 25, Bertie 25 | $70,913 principal |

**`--apply`** (never run): fetches every selected source in full BEFORE the lock (`--apply` with no `--sources` skips Catalis; name it explicitly). `--harvest PATH` writes the rows to a JSON file
under `logs/` (git-ignored) first and reuses it on the next run. Rows outside `main._in_scope` are dropped, and rows with a sale date must also pass `main._active_only`; a dateless standing roll
skips `_active_only`, which would delete it for want of a `DATELESS_OK_SOURCES` entry (1c). Then `with board_lock(...)`: `load_board`, `apply_rows`, `write_artifact`.

**`apply_rows(rows, new_listings, *, merge_matches=False) -> dict`** is importable. It appends to `rows` in place. Matching uses `dedupe_key()` plus the address and case signatures of
`dedupe._strong_sigs`; the state-wide PARCEL signature is left out because it is not county-qualified (a short Onslow parcel like `801-154` can equal a parcel in another NC county and a false match would
silently drop a new lead). Within the batch only exact-key duplicates collapse (dedupe pass 1 with its different-house guard, none of the fuzzy passes). A match leaves the existing row untouched;
`--merge-matches` fills blanks on it and never overwrites a value. It never removes or reorders a row and asserts `len(rows) == before + added` and that every existing row's identity fields are unchanged
(a guard test proves it fires). Returned stats: `before, after, new_in, added, matched_untouched, matched_merged, dup_within_new, added_by_source, existing_rows_unchanged`.

```
uv run python scripts/ingest_new_county_sources.py                                   # dry run, all six sources
uv run python scripts/ingest_new_county_sources.py --sources its,horry --limit 100   # bigger sample
uv run python scripts/ingest_new_county_sources.py --apply --sources its,charleston,horry,albemarle,column
uv run python scripts/ingest_new_county_sources.py --apply --sources catalis --catalis-counties Chester --harvest logs/new_county_catalis.json
```

One board process at a time: `load_board` is about 2.8 GB on the 8 GB Mac. Run the apply while no other board writer holds `logs/.board.lock`.

## 10. Skipped, and why

| Item | Why |
|---|---|
| Aiken and Fairfield mobile-home bills | opt-in (`CATALIS_ROLL_MOBILE_HOMES=1`): a personal-property tax on a unit that may sit on someone else's land, 125 of 740 Aiken rows in one prefix |
| Catalis `Parcel` search mode | matches vehicles as well (Chester "06": 1,000 rows, 593 vehicles), so it does not isolate real property |
| Marion delinquent tax sale ad (Column "Public Auction") | OCR text is a scrambled multi-column table, names and tax maps do not pair; belongs to the document-OCR lane |
| Column SC foreclosure lane per Pee Dee county | SC foreclosure notices in non-footprint counties are flips; the statewide lane already emits and scope drops them |
| Hertford `bcpwa` export, Bertie `webtaxpay`, Jones ITSPublicJN2.0, Onslow county pages | empty export, human-verification wall, empty body plus a 500, Cloudflare challenge (research evidence, not re-tried) |
| Editing `charleston_delinquent_tax.py` | not in my ownership; the xlsx is a separate scraper and merges on the PIN (the research proposed swapping the PDF reader) |
| Edits to `parcel_cache.py`, `arcgis_distress_layers.py`, `distress_score.py`, `main.py`, `web_artifact.py` | not mine; the three needed edits are section 1 |

## 11. Live requests made (audit trail)

Approximate totals, all one at a time: Catalis host 16 POSTs (8 s apart) plus the county page, the app bundle and `SearchOptions`. Column API about 35 POSTs. ITSPublic about 20 (Onslow and Graham).
Charleston about 7 (two workbooks, the landing page, the sample runs), Horry about 6. Albemarle Observer about 18 (the index, five posts, the sample runs). Greenville 7, CivicPlus hosts 11
(4 replacements, 4 old hosts, 3 Graham variants), NC OneMap 1 (Bertie PIN check). No host answered 429 or 403 during any of it.
