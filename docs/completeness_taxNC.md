## NC TAX DEEP-DIVE — VERIFIED

All URLs below were fetched live (2026-08-02). Working files in `/private/tmp/claude-502/-Users-cashhigh-Desktop/f9f41c0e-c1d7-4991-a803-581317d111fe/scratchpad/` (`hend_delinq.csv`, `kania_json.txt`, `btf.json`, `bunco_bills_probe.json`, `mcd.pdf`, `linc.pdf`, `bun_dc.pdf`).

---

## HEADLINE: the best multi-year source is NOT Buncombe. It's Henderson.

**Henderson County publishes a free, public, no-auth, daily-refreshed CSV covering tax years 1993–2026 in one file.**

NCPTS "Bill PWA" (Farragut/NCPTS cloud), React SPA. Base URL = `window.location.origin`; tenant passed as HTTP header `X-Tenant: <FirstPathSegment>`.

```
GET https://bcpwa.ncptscloud.com/api/GetTaxpayerDownloadList
    -H "X-Tenant: Henderson"
 -> [{"blobName":"BillPWA/TaxpayerDownloads/Delinquent Export/DelinquentExtract.csv",
      "fileSize":5911849,"fileDate":"2026-08-02T06:02:23"}]

GET https://bcpwa.ncptscloud.com/api/DownloadTaxpayerDownloadBlob?fileName=<urlencoded blobName>
    -H "X-Tenant: Henderson"
 -> {"downloadUrl":"https://nlgscpsatppstorage.blob.core.windows.net/henderson/...?<SAS>","expiresAt":...}
```
Gotcha: the blobName contains a literal space; you must percent-encode the SAS URL path or the fetch returns 000.

Verified contents: **25,450 rows, all `BILL_STATUS=UNPAID`, TAX_YEAR 1993–2026 (34 distinct years).**
Columns: `BILL_NUMBER, BILL_TYPE, PARCEL_NUM, TAX_YEAR, OWNER_NAME, MAIL_ADDR1-3, IN_CARE_OF, MAIL_CITY, MAIL_STATE, MAIL_ZIP, ABSTRACT_TAXABLE_VALUE, DESCRIPTION, PROP_SIZE, ABSTRACT_ASSESS_VALUE, BILL_STATUS, BILL_AMOUNT, BILL_DUE_AMT, INTEREST_DUE, TOTAL_DUE_AMOUNT, BILL_DUE_DATE, FLAGS`

- `BILL_TYPE`: IND 18,922 / BUS 4,156 / **REI 2,368** / PUB 4. **REI = real estate** — exactly the 2,368 rows with a populated `PARCEL_NUM`. Filter on that.
- 1,152 distinct real-estate parcels. **367 are delinquent in 2+ years.** Longest run: parcel `9949845`, delinquent **31 consecutive years (1995–2025)**. Four more parcels at 27 years. Total REI owed: **$1,254,878.63**.
- REI per year: 2020:50, 2021:63, 2022:83, 2023:167, 2024:343, **2025:1,065**, 2026:34 (just-issued).
- `FLAGS` is a free distress enrichment: `DLQ`, `UNCOLLECTABLE` (722), **`RM-NOT DELIVERABLE` (471 — return-mail vacancy signal)**, `OWNERSHIP TRANSFER`, `Judgement Filed`, `RM-ATTMPTD NOT KNOWN`, `RM-FWD. TIME EXPIRED`.

Same host also gives `GET /api/GetBillSearchFilters` → `taxYears 2016-2026`, `billStatuses [DEFERRED,PAID,UNPAID]`; `POST /api/AdvancedBillSearch`; `GET /api/SimpleBillSearch?query=`.

**Tenant enumeration** (`GET /api/IsValidTenant` with `X-Tenant`), 40 NC counties tested: only **Henderson, Madison, Forsyth** return `true`. Every other target county returns `false`. Madison is in your wider footprint and has the identical CSV (2.79 MB, refreshed 2026-08-02T06:00:55).

---

## (b) BUNCOMBE ArcGIS — claim VERIFIED, with three material corrections

Org: `services6.arcgis.com/VLA0ImJ33zhtGEaP` (591 services). Owner `GISAdminBC`, all `access: public`, item `modified` = 2026-07-31 for every year (nightly refresh). Officially linked from `buncombenc.gov/604/Tax-Collections` → "Tax Open Data Downloads" → `https://data.buncombecounty.org/search?tags=Tax`. `maxRecordCount` 2000, `capabilities: Query` only.

**Correction 1 — "every year 2009-2026" is true at the item level but 2009–2012 are EMPTY (0 rows).** Real coverage with data = **2013–2026, 14 years**.

**Correction 2 — the service URL names are wrong for 2021/2022.** Resolve by item ID, never by URL string.

**Correction 3 — most rows are NOT real estate.** Rows with blank `pin` are personal-property / business-personal / vehicle bills (`real_value=0`, no acres, no deed). Real estate = `pin <> ''`.

| Item title (authoritative) | rows | rows w/ PIN (real estate) | FeatureServer URL (note the drift) |
|---|---:|---:|---|
| Unpaid Property Bills from 2009 | 0 | 0 | `.../services/Unpaid Property Bills from 2009/FeatureServer` |
| ...2010 | 0 | 0 | `.../Unpaid Property Bills from 2010/FeatureServer` |
| ...2011 | 0 | 0 | `.../Unpaid Property Bills from 2011/FeatureServer` |
| ...2012 | 0 | 0 | `.../Unpaid Property Bills from 2012/FeatureServer` |
| ...2013 | 414 | 16 | `.../Unpaid Property Bills from 2013/FeatureServer` |
| ...2014 | 212 | 21 | `.../Unpaid Property Bills from 2014/FeatureServer` |
| ...2015 | 127 | 17 | `.../Unpaid Property Bills from 2015/FeatureServer` |
| ...2016 | 185 | 19 | `.../Unpaid Property Bills from 2016/FeatureServer` |
| ...2017 | 287 | 34 | `.../Unpaid Property Bills from 2017/FeatureServer` |
| ...2018 | 540 | 33 | `.../Unpaid Property Bills from 2018/FeatureServer` |
| ...2019 | 890 | 52 | `.../Unpaid Property Bills from 2019/FeatureServer` |
| ...2020 | 3,123 | 58 | `.../Unpaid Property Bills from 2020/FeatureServer` |
| ...**2021** | 3,287 | 77 | `.../Unpaid_Property_Bills_from_2021/FeatureServer` ← **underscores** |
| ...**2022** | 4,175 | 114 | `.../Unpaid Property Bills from 2021/FeatureServer` ← **named 2021, contains levy_year 2022** |
| ...2023 | 4,847 | 205 | `.../All Property Unpaid Bills from 2023/FeatureServer` |
| ...2024 | 6,255 | 376 | `.../Buncombe_County_All_Property_Bills_Unpaid_from_2024/FeatureServer` |
| ...2025 | 7,922 | **1,076** | `.../Unpaid Property Bills from 2025/FeatureServer` |
| ...2026 | 125,827 | 103,285 | `.../Unpaid Property Bills from 2026/FeatureServer` |

53 fields confirmed: `bill, owner1_last_name, owner1_first_name, owner1_third_name, owner1_suffix_name, owner2_*, address_line1, address_line2, city, state, postal_code, postal_code_ext, township, city_code, fire_code, school_code, subdivision, pin, sub_lot, house_num, house_suf, street_direction, street_name, street_type, plat_book, plat_page, deed_book, deed_page, deed_date, deed_instrument, acres, mortgage_co, loan_num, real_value, personal_value, deferred_value, exempt_value, total_value, levy_year, original_bill_amount, tax_due, late_due, ad_cost_due, interest_due, cost_due, fees_due, total_due, levy_due, active_flag, OBJECTID`. All numerics are **strings** — `where=total_due>0` returns HTTP 400.

**The 2026 table is the early-detection lever.** 103,285 real-estate bills are "unpaid" simply because 2026 bills were issued 2026-07-08 and aren't due until Sept 1 / delinquent Jan 6, 2027. Poll it monthly: the residual set as January approaches is a pre-delinquency watchlist that precedes the advertisement (published ~June) by six months.

Companion series **"All Property Bills from YYYY" covers 2004–2026** (169k–207k rows from 2011 on) — the full roll, not just unpaid.

**Does any other NC county publish an equivalent?** Searched ArcGIS Online across four query shapes. Result: **no county matches Buncombe's per-year archive.** Two NC counties publish a single current snapshot:
- **Guilford** — `https://services5.arcgis.com/RR1v7NWFfwk98pUn/arcgis/rest/services/Tax_Delinquent_Report_/FeatureServer/0`, 9,749 rows, TAX_YEAR **2016–2025**. Schema is **byte-for-byte the NCPTS `DelinquentExtract` layout** (`PARCEL_NUM, TAX_YEAR, OWNER_NAME, MAIL_ADDR1-3, IN_CARE_OF, MAIL_CITY/STATE/ZIP, ABSTRACT_TAXABLE_VALUE, LEGAL_DESCRIPTION, PROP_SIZE, PROP_ASSESS_VALUE, BILL_STATUS, BILL_AMOUNT, BILL_DUE_AMT, INTEREST_DUE, TOTAL_DUE_AMOUNT, BILL_DUE_DATE`). Proof the extract is a standard NCPTS product some counties republish.
- **Pitt** — `https://gis.pittcountync.gov/gis/rest/services/PittOpenData/Tables/MapServer/9` (`DelinquentTaxesPOD`), 9,170 rows.

Neither is in your 11.

---

## (a) NCGS 105-369 annual advertisement — where each county actually publishes it

| County | Published as | Real URL | Machine-readable? |
|---|---|---|---|
| **Buncombe** | County PDF + ArcGIS | `https://www.buncombenc.gov/DocumentCenter/View/2171` (stable "Latest" URL; 7pp, 2025 tax yr as of 5:00 pm 5/31/2026, BOC order 2/3/2026, **1,650 unique 15-digit PINs**, owner+PIN+$+situs). Prior-year copy: `https://media.buncombenc.gov/common/tax/buncombe-county-tax-department-advertisement-of-tax-liens.pdf` (12pp, 1,163 PINs) | Yes, text layer |
| **McDowell** | County PDF | `https://mcdowellnc.gov/departments/tax-collections/tax-lien-advertisement` → `.../ADVERTISEMENT-LIST-FINAL-2025.pdf` (49pp, OWNER-NAME / PARCEL / TOTAL DUE). Newspaper mirror: `mcdowellnews.com/ads/print_ads/legal/pdfdisplayad_197a3065-eb49-55db-8f9f-5e0fd5e9ed7a.html` | Yes, text layer |
| **Lincoln** | County PDF | `https://www.lincolncountync.gov/DocumentCenter/View/25558/2025-TAXESDelinquentAdvertisementNotice` (33pp; 2025 taxes unpaid as of 4/21/2026; signed Susan Sain 5/1/2026; Parcel ID# + amount) | Yes, text layer |
| **Henderson** | Newspaper, free HTML archive | `https://www.hendersonvillelightning.com/legal-ads/131-tax-notices.html` — carries **2015, 2021 and 2025** ads plus municipal ads (Mills River, Hendersonville, Laurel Park, Saluda). Delimited format: `PRIMARY OWNER; ADDITIONAL OWNERS; DESCRIPTION; PARCEL; $TOTAL;` | Yes, semicolon-delimited |
| Gaston | Newspaper only (no county-hosted list found) | — | No |
| Cleveland | Newspaper (Shelby Star); no county-hosted list found | — | No |
| Rutherford | Newspaper (The Daily Courier); county publishes process pages only | — | No |
| Burke | Newspaper only | — | No |
| Polk | Newspaper only | — | No |
| Transylvania | Newspaper only | — | No |
| **Mitchell** | Newspaper only — **and this is a trap** | WP tags `advertisement-of-2019-tax-liens` (id 365), `tax-liens-advertisement` (1145), `advertise-tax-liens` (1121) each have **count=1 and attach to Board of Commissioners MINUTES**, i.e. the order authorizing advertisement, not the list. `wp-json/wp/v2/media?search=tax lien` returns nothing. | No |

**Statewide fallback:** `https://www.ncnotices.com/` (NC Press Association). Confirmed all 100 counties in its county filter, with keyword/exact-phrase/date advanced search. Architecture: ASP.NET WebForms, session baked into the path (`/(S(...))/default.aspx`), single `aspnetForm` postback — requires `__VIEWSTATE`/`__EVENTVALIDATION` replay. No CAPTCHA observed. This is the only route to the ad for the seven newspaper-only counties.

**Multi-year archive of advertisements: essentially unavailable.** McDowell prior-year filename probes (`ADVERTISEMENT-LIST-FINAL-{2019..2024,2026}.pdf`) all 404. Wayback CDX for `mcdowellnc.gov`, `lincolncountync.gov` and `buncombecounty.org` filtered on delinquent/advertisement/lien returns nothing usable. The ads are current-year-only by design.

---

## (c) Per-parcel tax balance systems

| County | Vendor / host | Unpaid browse? | Blocker class |
|---|---|---|---|
| **Henderson** | **NCPTS Bill PWA** `bcpwa.ncptscloud.com/Henderson` (+ land: `lrcpwa.ncptscloud.com/Henderson/`) | **YES — bulk CSV, 1993-2026, daily** | None. Open JSON API. |
| **Buncombe** | `tax.buncombenc.gov` (Buncombe County Tax Lookup, ASP.NET, form POST `/Search/Results`) | **YES — via the ArcGIS feeds** (county's own "download all paid or unpaid" link) | None |
| **Transylvania** | **ITSPublic** (ASP.NET MVC + NHibernate) `https://tax.transylvaniacounty.org/TaxBillSearch` | **YES in the UI** — `#UnpaidBillsOnly` checkbox + Tax Year `All Years / 2026…2017` | **No CAPTCHA, no WAF.** Plain-curl replay incomplete: `POST /TaxBillSearch/GetSearchTablePartial/` returns HTTP 200 / 0 bytes and `POST /TaxBillSearch/GetSearchTableData` then 500s ("Object reference not set"). `BasicSearch`/`RealEstateSearch` controllers respond fine. It's a session/view-model shape issue — headless browser resolves it. Vendor leaked via error page: `ITSPublic.Core.Domain.QuerySpeedup.PropertyReal` |
| **Gaston** | **DEVNET Wedge** `https://gastonnc.devnetwedge.com/` (v5.1.9691, data updated 2026-07-31 17:15) | **NO.** Enumerated every advanced-search field — `owner_name, parcel_key, property_classes, sale_date_min/max, total_tax_min/max, acreage, year_built…` — there is **no unpaid/delinquent/tax-status filter** | Per-parcel only, by design |
| **Burke** | **Catalis** (avalonCMS) `burkenctax.com` | No | **Google reCAPTCHA on search pages.** Compliance stop. |
| **Cleveland** | **Catalis** `clevelandcountytaxes.com` | No | **reCAPTCHA.** Compliance stop. |
| **Rutherford** | **Catalis** `rutherfordcountync.gov/tax_search/index.php` (embeds `avalon.sturgiswebservices.com`) | No | Catalis stack; per-parcel only |
| **Lincoln** | `lincolncountytax.com` (CivicPlus shell) | No | Per-parcel only |
| **Polk** | **BIS Consultants eSearch** `https://esearch.polk-tax.com/` (also `polknc.gov/tax_search/`) | No | **reCAPTCHA present.** Compliance stop. |
| **Mitchell** | **BIS Consultants** `mitchellcounty.tax` + **Catalis Public Access Now** `nc-mitchell.publicaccessnow.com/Assessor/PropertySearch.aspx` (assessor only, no unpaid) + TrueAutomation `propaccess.trueautomation.com/mapSearch/?cid=29`. `mitchell.webtaxpay.com` fails TLS hostname verification on direct HTTPS | No | Fragmented; per-parcel only |
| **McDowell** | `mcdowellnc.gov/departments/tax-collections/online-search-and-or-payment` | No | Per-parcel only |

---

## (d) Tax foreclosure sale lists

**Kania Law Firm — confirmed working JSON, no auth:**
```
GET https://kanialawfirm.com/wp-admin/admin-ajax.php
    ?action=wp_ajax_ninja_tables_public_action
    &table_id=216745
    &target_action=get-all-data
    &default_sorting=old_first
```
187 rows statewide, 25 counties. Per row: `county, address, parcel, saledatetime, openingbid, currentbid, closedate, propertytype, courtfile, ourfile, salestatus`. Multi-parcel cases embed `<br />` in `address`/`parcel`.

In-footprint: **Burke 12, Rutherford 15, Cleveland 7, Lincoln 7, Polk 1 = 42 rows.** Kania does **not** serve Buncombe, Henderson, Gaston, McDowell, Transylvania or Mitchell.

**Zacchaeus (`zls-nc.com/listings`) — architectural blocker, not a WAF.** Loads `_framework/blazor.server.js`; `blazor.boot.json` 404s (so not WASM); `/_blazor/negotiate` returns 411 to a bodyless POST. It is **Blazor Server over SignalR** — no JSON API exists to call. `robots.txt` allows everything except `/auth/`. Extraction requires a real browser session; there is no HTTP shortcut.

| County | Foreclosure list source | Notes |
|---|---|---|
| **Buncombe** | `https://taxforeclosures.buncombenc.gov/` — powered by a **Trumba** calendar with public feeds | See below. Best structured feed of the eleven. |
| **Gaston** | In-house: `gastongov.com/669/Tax-Foreclosure-Sales` (current) and `gastongov.com/671/Previous-Tax-Foreclosure-Sales` (archive) | Owner, parcel#, physical address, sale date, starting bid, file number |
| **Cleveland** | In-house `clevelandcounty.com/main/departments/find_tax_foreclosures___county_owned_properties_for_sale/index.php` **plus** explicit pointer to Kania | Parcel / file# / address / map-block-lot; flags "in the 10-day upset bid period"; also lists county-owned post-foreclosure inventory |
| **Rutherford** | County in-office page + Kania | `rutherfordcountync.gov/departments/revenue_department_tax_administrator/foreclosure_information/` |
| **Lincoln** | Kania (county page is stale) | `lincolncountync.gov/2368/Foreclosures` says "There are no tax foreclosures at this time" while the Kania feed shows **7 live Lincoln files**. **Trust Kania, not the county page.** |
| **Burke, Polk** | Kania only | No county-hosted list |
| **McDowell** | `mcdowellgov.com/departments/tax-collections/tax-foreclosures/upcoming-tax-foreclosure-sales` | Currently no listings rendered |
| **Henderson** | `hendersoncountync.gov/tax/page/tax-foreclosure-sales` | **No list published** — email notification list only |
| **Transylvania** | `transylvaniacounty.org/news/foreclosure-sale` | **Dead.** Newest item is a Dec 2017 sale. Email notification via tax office. |
| **Mitchell** | None found | — |

**Buncombe Trumba feed (undocumented, works):**
```
https://www.trumba.com/calendars/tax-foreclosures-all.json?startdate=1%2F1%2F2015&days=5000
   (also .rss / .ics / .xml; webName also "tax-foreclosures-details")
```
Without `startdate`+`days` it returns `[]` — that's why it looks empty. With them: **58 events spanning 2022-01 → 2026-04.** `title`=owner, `description`=acreage/legal, `startDateTime`=sale datetime, and customFields: **Opening/Current Bid, Redeemed (Yes/No), Case Number, PIN lookup (15-digit PIN inside `?PINN=`), Property Type, Fire District.** Redeemed split: **33 No / 25 Yes.**

---

## (e) Properties already sold, awaiting upset

There is **no statewide NC feed**. Upset bids are Clerk of Superior Court records, county by county. What exists:

- **Kania JSON** — best coverage. `closedate` = last day to upset, `currentbid` = current standing bid. **74 of 187 rows carry a closedate.** Live examples: Burke 578 E. Settings Blvd (opened $12,500 → current $34,728.75, closes 8/3/2026); Rutherford 185 Jamerson Rd (opened $15,200 → **current $143,325**, closes 8/3/2026).
- **Gaston `/671/`** — the cleanest county-hosted version: *Current Bid, Minimum of Next Upset Bid, Last Day to Upset, File Number,* plus terminal status (`Sale Closed-Property Sold` / `Settled-Property Redeemed`). Archive runs back to mid-2024.
- **Cleveland** — names the specific parcel/file in the 10-day window; notes upset bids **cannot be e-filed** in Cleveland (in-person at Clerk only).
- **Buncombe Trumba** — `Redeemed` flag + `Opening/Current Bid`, but **no upset deadline field**.
- **Henderson, McDowell, Polk, Transylvania, Mitchell, Burke, Rutherford, Lincoln** — nothing county-published; only whatever the outside counsel feed carries.

---

## VERDICT: multi-year delinquency history availability

| Tier | Counties | What you actually get |
|---|---|---|
| **Full history, structured, free** | **Henderson** | **34 years (1993–2026)** in one daily CSV; 1,152 real-estate parcels; 367 with 2+ years; consecutive-year runs up to 31. Plus return-mail/uncollectable flags. |
| **Deep history, structured, free** | **Buncombe** | **14 years with data (2013–2026)** across 18 nightly-refreshed FeatureServers; full mailing + situs + deed + value + mortgage_co. Real-estate volume in old years is thin (16–114/yr) — value is the *repeat-appearance* signal and the 2025/2026 tables. |
| **Current year only, structured** | **McDowell, Lincoln** | One machine-readable PDF per year (owner/parcel/amount). No archive — prior-year filenames 404, Wayback empty. Build history only by snapshotting forward from now. |
| **Current year only, browsable but unextracted** | **Transylvania** | Year-by-year unpaid browse exists 2017–2026 in the UI. Needs headless browser. **Highest-value unbuilt target after Henderson.** |
| **Current year only, newspaper** | **Gaston, Cleveland, Rutherford, Burke, Polk, Mitchell** | 105-369 ad via ncnotices.com or local paper. No county-hosted list, no archive. |
| **Blocked by CAPTCHA — do not pursue** | **Burke, Cleveland, Rutherford (Catalis); Polk (BIS)** | reCAPTCHA on the tax search. Per-parcel lookups are unreachable compliantly. Their delinquency must come from the newspaper ad or the Kania foreclosure feed. |

**Blunt assessment.** For 6 of the 11 counties, multi-year tax-delinquency history **does not exist in any free public form and cannot be obtained by anyone at any price short of a public-records request to the tax office** — the counties don't retain it in a published form, and the statutory advertisement is a once-a-year current-year snapshot that nobody archives. The realistic ceiling is: two counties with true history (Henderson, Buncombe), two more with an annual PDF you snapshot forward (McDowell, Lincoln), one browsable-but-unbuilt (Transylvania), and six where your only recurring signal is the annual newspaper ad plus the Kania foreclosure feed.

**Build order:** (1) Henderson CSV — one HTTP call, delivers more history than everything else combined. (2) Buncombe 14 services, resolved by item ID with `pin <> ''`. (3) Kania JSON — 42 in-footprint files with live upset deadlines, one URL. (4) Buncombe Trumba + Gaston `/671/` for sold-awaiting-upset. (5) Transylvania via headless browser. (6) McDowell/Lincoln/Buncombe PDF parsers on an annual cron.