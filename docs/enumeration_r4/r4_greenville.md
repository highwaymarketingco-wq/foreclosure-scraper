Enumeration complete. All seven sweeps run; every URL below was fetched and verified this session.

## Greenville County SC — source enumeration

| Source | Exact query-ready URL | Yield (counts + fields) | Access | NEW/SCRAPED |
|---|---|---|---|---|
| **Tax Parcel (master roll)** | `https://www.gcgis.org/arcgis/rest/services/GreenvilleJS/Map_Layers_JS/MapServer/52/query?where=1%3D1&outFields=*&returnGeometry=false&resultOffset=0&resultRecordCount=5000&f=json` | **243,750** parcels. PIN, OWNAM1/2, STREET+CITY+STATE+ZIP5 (mailing), NAMECO (in-care-of), POWNNM (prev owner), DEEDDATE, CUBOOK/CUPAGE, LANDUSE, DESCR, STRNUM/LOCATE (situs), SLPRICE, FAIRMKTVAL, TAXMKTVAL, **TOTTAX + PAIDDATE**, TACRES, SQFEET, BEDROOMS, BATHRMS, PROPTYPE, IMPROVED. Pagination verified to offset 240,000 (49 GETs) | OPEN, no key | NEW |
| **Sales / transactions** | `.../Map_Layers_JS/MapServer/5/query?where=SALEDATE+%3E+date+%272024-01-01%27&outFields=*&returnGeometry=false&f=json` | **361,562** total; 46,075 since 2024; 25,288 since 2025. PIN, SALEDATE, SALEPRICE, **PURNAME, SELLNAME**, DEEDBOOK/PAGE, TRUESALE (domain is `YES`/`NO`, 158,173 YES — *not* `Y`), SALETYPE, LOTSIZE, SQFEET, beds/baths. Layers 1-4 are this split by type (Res 335,879 / Com 12,411 / MF 2,174 / MH 11,098) | OPEN | NEW |
| **Ownership History** (chain of title) | `https://www.gcgis.org/arcgis/rest/services/GreenvilleJS/QueryLayers_JS/MapServer/1/query?where=PIN%3D%270560120107600%27&outFields=*&f=json` | **1,127,578** rows. PIN, OWNER, DEEDBOOK, DEEDPAGE, SALESPRICE. 473,859 rows at $0 (nominal/quitclaim/heir signal). **Gotcha: SALESDATE is epoch-zero on every row — unusable, use layer 5 for dated sales** | OPEN | **NEW** |
| **Assessment History** | `.../QueryLayers_JS/MapServer/2/query?where=PIN%3D%27...%27&outFields=*&f=json` | **5,276,520** rows. PIN, TAXYEAR, OWNAM1, TAXMKTVAL, TOTTAX — multi-year tax/value trend per parcel | OPEN | **NEW** |
| **Delinquent tax sale list** | `https://www.greenvillecounty.org/appsAS400/Taxsale/` | **3,700** rows, single GET, 2.5 MB. Item #, Map #, Owner Name, Amount Due. Cross-checks the GIS (3,600 unpaid >$500) | OPEN HTML | NEW |
| **Probate index (full dump)** | `https://www.greenvillecounty.org/appsAS400/Probate/SearchResults.aspx` | **447,435** party rows in ONE GET (252 MB, no POST/viewstate). Case #, Name, Party Type. **155,503 Deceased Person**, 120,252 Personal Representative, 17,356 Creditor. Year encoded in case # (`2024ES23…`); ES 314,714 / GC 33,134. **No property link, no date column** | OPEN HTML | NEW (docs had only 5,637 via `?LastName=`) |
| **Master-in-Equity foreclosure ads** | `https://mie.greenvillejournal.com/wp-sitemap-posts-advert-1.xml` → `https://mie.greenvillejournal.com/advert/2026-cp-23-01899/` | **722** notices (2016-2026; 220 in '23, 136 '24, 171 '25). Per case: plaintiff, defendant, junior lienholders, sale date, **TMS parcel ID**, street address, **total judgment debt $**, interest rate, bid-close date. robots-permitted | OPEN HTML | NEW (documented in `r2_preforeclosure_signals.md`, never built) |
| **Site Addresses** | `.../Map_Layers_JS/MapServer/36/query?where=1%3D1&outFields=*&f=json` | **306,949** address points (ADDRESS, ZIPCODE + geometry) — situs resolution for address-less parcels | OPEN | **NEW** |
| **Geocoders (4)** | `https://www.gcgis.org/arcgis/rest/services/Address_Locators/GVL_PARCEL/GeocodeServer` (+ `GVL_ADDPNT_W_ZIP`, `GVL_STREETCL_W_ZIP`, `GVL_COMPOSITE_LOC`) | Free county-grade geocoding incl. **parcel-ID locator** — no rate limit, no key | OPEN | **NEW** |
| Subdivision / Zoning / FIRM flood | `.../Map_Layers_JS/MapServer/51` (7,223 subdivisions), `/64` FIRM zone, `/68` zoning | Underwriting context layers | OPEN | NEW |
| City of Greenville AGOL org | `https://services.arcgis.com/s8BzdTejnTIG3ix6/arcgis/rest/services?f=json` | **163 feature services**, org `s8BzdTejnTIG3ix6`. Swept for distress: **no** code-enforcement, vacancy, condemnation or permit layer. Stormwater/utility/addresses only | OPEN | **NEW (low value)** |

### Walls — classified, not bypassed

| Wall | URL | Type |
|---|---|---|
| ROD official records | `https://greenville.sc.publicsearch.us/` | Migrated to Tyler PublicSearch. `robots.txt` = `Allow: /$` + `Disallow: /` → **policy wall, do not crawl**. No deed/mortgage mining in Greenville |
| Legacy ROD | `https://rod.greenvillecounty.org/countyweb/loginDisplay.action?countyname=Greenville` | Redirects to login |
| Unfit structures (condemned) | `https://app.greenvillecounty.org/unfit_structures.htm` | Imperva/Incapsula |
| Permits issued | `https://app.greenvillecounty.org/permits_issued.htm` | Imperva/Incapsula |
| SC Public Index (civil/lis pendens/divorce) | `https://www2.greenvillecounty.org/scjd/publicindex/` | Imperva **and** `robots.txt Disallow: /SCJD/` — double wall; falls into the existing manual saved-page lane |
| Code enforcement | `https://www.greenvillecounty.org/CodeEnforcement/` | No bulk list; phone/e-service only |
| County open-data Hub | `https://data-greenvillecounty.opendata.arcgis.com/` | Unprovisioned 8 KB shell, no org |

**Resolved:** the brief's UNPROVEN item — `greenvillecounty.org/rod/SearchRecords.aspx` has **no result grid at all**. It is a portal page (`__VIEWSTATE` 68 bytes, zero form inputs); search was outsourced to the Tyler tenant. There is nothing to parse.

## Answers

**Net-new sources: 10 usable + 6 walled.** Six are genuine discoveries not in any repo doc — Ownership History (1.13 M), Assessment History (5.28 M), Site Addresses (307 K), the 4 geocoders, the Tyler ROD migration, and the City AGOL org. The rest verify/upgrade the brief.

**Lead counts (all live-queried, not estimated):**

| Segment | Count |
|---|---|
| Delinquent (TOTTAX>0, PAIDDATE null) | **5,014** |
| Absentee (mailing outside county) | **25,627** (15,413 out-of-state + 10,214 out-of-county SC) |
| overlap | −918 |
| **Delinquent ∪ absentee** | **29,723** |
| Probate decedents 2023-2026 | **12,284** → ~3,100-3,700 after name→parcel match at the known 25-30% ceiling |
| Foreclosure adverts | 722 banked, **~170/yr** live flow |
| **Total distinct property leads** | **≈ 32,800** |

**Is it worth it? Yes — but scope it, and settle the legal question first.**

The case for: Greenville alone would roughly **double the 30,003-lead board** from four GETs' worth of infrastructure (49 paginated parcel calls, 1 tax-sale, 1 probate, 722 adverts). More important than volume, the MIE adverts hand you **total judgment debt against a TMS that joins cleanly to the parcel roll** — I verified the join end to end: `0560.12-01-076.00` → strip punctuation → PIN `0560120107600` → `CHILDS KATRINA`, FMV $330,050 vs judgment $242,079.31 = **$88 K equity, computed with no deed OCR**. That directly attacks the engine's worst metric (equity coverage at 11.7%), and it works here precisely *because* the ROD is walled — the newspaper publishes what the deed would have told you.

The case against, and it is real: Greenville is SC, so **§ 30-2-50** applies — the misdemeanor bar on using local-government records for commercial solicitation, already flagged in `honest_operator_manual.md` as needing an SC attorney's opinion. Adding the largest SC county concentrates exposure in exactly the jurisdiction where that question is unresolved. Also note the absentee 25,627 is an *ownership* signal, not distress; the hard-distress core is ~8,500 (5,014 delinquent + ~3,400 matched probate + 170/yr foreclosure).

Versus deepening the existing 18: deepening means grinding deed-of-trust OCR county by county to lift equity. Greenville delivers dated sales, tax balances, FMV, beds/baths, mailing address **and** judgment-debt equity from open endpoints with zero OCR — better marginal return per hour than the OCR grind. Recommend building the parcel + tax-sale + MIE-advert trio (highest value, ~1 day), deferring probate until the name→parcel resolver improves, and **holding SC mail volume until counsel rules on § 30-2-50** — which is a decision you already owe on Spartanburg, Anderson, Pickens and Laurens regardless of what you do with Greenville.

Working files: `/private/tmp/claude-502/-Users-cashhigh-Desktop/f9f41c0e-c1d7-4991-a803-581317d111fe/scratchpad/` (`taxsale.html`, `probate_head.html`, `adverts.xml`, `city_svcs.json`). No repo files written, no git, engine not run.