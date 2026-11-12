# County breadth research, 2026-09-21

Scope: free, public data for the counties the audit (`docs/AUDIT_2026-09-21.md` sections 4 and 16) shows as empty
or thin. Distressed leads (tax delinquency, tax sale, liens, probate, divorce, code enforcement, vacancy, storm
damage) are wanted in all 146 NC and SC counties; flip leads only in the 18 footprint counties.

Rules held throughout: free and public only, no paid API, no CAPTCHA, login, Cloudflare or WAF challenge bypass,
no click-through terms. A `robots.txt` Disallow is not a wall (owner decision 2026-09-20). One request at a time
with a browser User-Agent. A wall is reported as a wall, with the evidence.

## 1. Result

| Measure | Result |
|---|---|
| Target counties | 30 (18 SC, 12 NC) |
| Counties that gained at least one verified free source | 28 of 30. SC 16 of 18, NC 12 of 12 (Greene and Brunswick are marginal: one stale row and two surplus parcels). Clarendon and Kershaw gained nothing new. |
| SC counties with no parcel cache before | 17. Now: 8 added, Horry gets a situs overlay, Dorchester verified and held back, 8 have no open bulk parcel source. |
| Code shipped (pure config plus small helpers) | 8 new `PARCEL_LAYERS` caches, a situs overlay (Horry, Charleston), 2 new ArcGIS distress layers (Greenville unpaid tax 2,855 leads, Columbia code 1,064 leads), 45 offline tests. |
| Board rows that can now gain mail, value or situs | About 17,600: Charleston 6,457, Horry 4,254, Greenville 2,602, Berkeley 2,325, Florence 2,006, plus a handful in Aiken and Greenwood. Only rows whose `parcel_id` matches the layer's key will fill, so the real number is lower until the join is run. |
| Walled | qPublic (Cloudflare challenge), the WTH "tgis" viewers, five county web sites behind Cloudflare or Akamai, ncnotices and scpublicnotices detail pages. Section 8. |

Top yields, by what they add to the board:

1. Chester, Hampton, Fairfield, Aiken delinquent rolls via the Catalis "Avalon" tax API. Chester, Hampton and Fairfield have zero rows today. One surname-prefix query returned 73 delinquent real-property records for Chester and 86 for Hampton.
2. Onslow unpaid tax bills (7,428 for 2025) and Graham (925) from the ITSPublic tax portals. Onslow has 1,402 board rows and 14% parcel coverage.
3. Column notice API extended to five NC counties and the SC Pee Dee counties: Florence 50 foreclosure cases and 36 estates a year, Marion 19 foreclosure and 90+ estates, Marlboro 63 estates.
4. Charleston tax-sale spreadsheet (2,402 real property rows, 1,224 mobile homes) and Horry delinquent spreadsheet (4,952 rows).
5. Albemarle Observer republished NC delinquent lists: Tyrrell 391, Washington 1,206, Gates 1,555, Bertie 1,565 rows.
6. Greenville unpaid-tax parcels (2,855) and Charleston, Florence, Berkeley, Greenville parcel caches, shipped in this change.

## 2. How to read the verification column

- **V-me**: I fetched it myself this session and saw the count and a real row.
- **V-me (spot)**: a research subagent found it; I re-fetched it and the headline number matched.
- **V-agent**: a research subagent fetched it (four subagents ran: Pee Dee and Lowcountry, Midlands and Upstate, NC thin counties, statewide). I did not re-run it.
- **Not verified**: reachable but not proven end to end.

Personal names, mailing addresses and situs of private owners are left out of every sample below on purpose. Fields and shapes are real.

## 3. What shipped (all verified live by me on 2026-09-21)

Files: `src/foreclosure_scraper/parcel_cache.py` (PARCEL_LAYERS table plus the overlay builder),
`src/foreclosure_scraper/scrapers/counties_generic/arcgis_distress_layers.py`,
`tests/test_parcel_cache_breadth_2026_09_21.py` (34 tests), `tests/test_arcgis_distress_breadth_2026_09_21.py` (11 tests).
The two new files plus the existing parcel cache, NC OneMap, SC parcel mailing, ArcGIS distress, webmap and Greenville tests were re-run together: 303 passed, 1 skipped. Another worker is editing `lookup` in the same file (`lookup_with_tier`, `tests/test_dq_parcel_cache_id_tolerance.py`); its tests and mine pass together (87 passed).

### 3a. Parcel caches added (`PARCEL_LAYERS`)

Every layer is open (no token), returned its count with `returnCountOnly`, and was mapped through the real `_map_val`
on 400 live rows. Field population is measured over a sample spread across the layer.

| County | Layer URL | Rows | Key | Owner | Mailing | Situs | Value | Notes |
|---|---|---|---|---|---|---|---|---|
| Charleston | `https://gisccapps.charlestoncounty.org/arcgis/rest/services/ENERGOV/energov_css/MapServer/4` | 197,677 | `PID` | `OWNER1`,`OWNER2` | `MAIL_ST_NO`,`MAIL_ST_NAME`,`MAIL_ST_TYPE`,`MAIL_2ND_ADDR`,`MAIL_CITY`,`MAIL_STATE`,`MAIL_ZIP` | overlay only | `APPRAISAL` (= `LAND_APPR` + `IMP_APPR`) | maxRecordCount 1000, paging verified. Sale price and date also mapped. |
| Charleston situs overlay | `.../ENERGOV/energov_css/MapServer/0` | 70,072 points | `PID` | | | `WHOLE_ADDRESS`, `UNIT` | | 87 of 250 sampled parcels (35%) get an address. |
| Greenville | `https://www.gcgis.org/arcgis3/rest/services/GreenvilleNJ/QueryLayers/MapServer/0` | 244,178 | `PIN` (13 digit) | `OWNAM1`,`OWNAM2` | `STREET`,`CITY`,`STATE`,`ZIP5` | `STRNUM`,`STRPRE`,`LOCATE`,`STRTYP`,`STRSUF` | `FAIRMKTVAL` (market), `TAXMKTVAL` (capped taxable) | Replaces the removed GreenvilleJS service. 400 of 400 rows filled on every column. |
| Florence | `https://services1.arcgis.com/40L6yX6OtdCifNez/arcgis/rest/services/County_Tax_Parcel/FeatureServer/0` | 70,098 | `TMS` (`00001-04-001`), `TMSNODASH` | `OWNERNAME` | `ADD2`,`ADD3` (`ADD1` is a name or C/O line, left out) | `ADDR_SITE` 74% | none: `TOTBDGVAL` is building only, not mapped | ADD3 arrives as `CITY   SC29080`; the cache splits the state from the ZIP. |
| Berkeley | `https://gis.berkeleycountysc.gov/arcgis/rest/services/internet/MapServer/4` | 123,050 | `O_TMS` | `OwnerName` | `StreetAddress1`,`StreetAddress2`,`City`,`StateProvince`,`Zip` | `GIS_Address` 82% (49% in one window) | `TotalTaxValue` (tracks sale price at about 1.0x) | Berkeley's PayStar rows already carry mail; this adds value, which is 0% today. |
| Aiken | `https://gis.cityofaikensc.gov/arcgis/rest/services/PublicGIS/MapServer/13` | 103,207 | `PARCEL_ASR` (`108-14-04-009`), `PARC_NO` | `OwnerName` | `OwnerMailingAddress`,`OwnerMailingCity`,`OwnerMailingState`,`OwnerMailingZip` | `LocationAddress` 84% | `TotalMarketValue` (98%) | Whole county, served by the City of Aiken's server. The county sells its GIS and hides the assessor map behind qPublic, so this is the only open bulk source. `AssessedValue` is a 4% ratio figure and is not mapped. |
| Greenwood | `https://www.greenwoodsc.gov/arcgis/rest/services/Operational_Layers/CAMA/MapServer/9` | 39,553 | `PIN` (`6913-674-230`) | `Owner` | `MailAddress`,`MailCityState` | `SiteAddress` | `MarketValue_Total`, `TaxValue_Total` | Full CAMA row: also `SqFt` (60%), `YearBuilt`, beds and baths. |
| Hampton | `https://services8.arcgis.com/6eabNhFouHU5vuYk/arcgis/rest/services/Parcels_Published_view/FeatureServer/1` | 14,871 | `Map_Number` (`009-00-00-001.`) | `Name1`,`Name2` | `Address1`,`Address2`,`ZIP_Code` | `Street_Number_E911` 47%, `Street_Name_E911` 71% | `Tot_Market_Appr` (99%, comma strings) | Zero board rows today, so the board's id format is unknown. |
| Chester | `https://services8.arcgis.com/7uCc8YS9s04rg0sr/arcgis/rest/services/Parcels_10_7_24/FeatureServer/0` | 22,300 | `Map_Number` (`047-00-00-066-000`) | `Name_1`,`Name_2` | `Mailing_Ad`,`Mailing__1`,`Zip_Code` | none | sum of `Appraised_` (land) and `Appraised1` (building) | Possibly partial (the county holds more parcels). `state="SC"` is set because Chester is in `DUAL_STATE_COUNTIES`. |
| Horry situs overlay | `https://www.horrycountysc.gov/parcelapp/rest/services/HorryCountyGISApp/MapServer/22` | 242,675 points | `PIN` (float), `TMS` | | | `ADDRESS`, `UNIT` | | Parcel layer 24 has no situs field. From the address side, 194 of 194 sampled parcels matched via TMS. |

Helper changes in `parcel_cache.py`, all covered by tests:

- `address_overlay` config key: a second layer keyed by PIN or TMS that fills `parcels.address` only when the primary layer has none. One address per parcel, preferring the row with no `UNIT`, then the lowest unit (natural order), then the smallest address string so the choice is deterministic. The overlay is held to the same count-verified completeness gate as the primary; a short or failed overlay leaves the existing cache in place instead of replacing it with a worse one.
- `{"sum": [...]}` map spec for a numeric column the county publishes in parts (Chester).
- Whitespace squash on mapped text, and a state-ZIP split on mailing lines only for real two-letter state codes. Several layers pad inside the value (`CHESTER               SC`, `LN      `).
- The pagination loop moved into `_download_rows` unchanged, so the primary path behaves as before.

### 3b. Distress layers added (`arcgis_distress_layers.py`)

| Layer slug | URL | Rows | Filter | Fields | Notes |
|---|---|---|---|---|---|
| `greenville_unpaid_tax_parcels` | `https://www.gcgis.org/arcgis3/rest/services/GreenvilleNJ/QueryLayers/MapServer/0` | 2,855 | `TOTTAX > 0 AND PAIDDATE IS NULL` | `PIN`,`OWNAM1`,`OWNAM2`, situs parts, `TAXMKTVAL`,`TOTTAX`,`ACCTNO`,`PROPTYPE` | Of the first 2,000, 1,926 carry a 2025 bill (`ACCTNO` starts with the tax year), so unpaid since January 2026. Median bill about $825, first-2,000 sum $4.3M. The layer's `CITY`/`STATE`/`ZIP5` are the owner's mailing address and are not requested. On the tolerate list because gcgis.org has already moved this service once. Live run through the real reader returned 2,855 leads. |
| `columbia_code_vacant_boarded` | `https://services1.arcgis.com/Mnt8FoJcogKtoVBs/arcgis/rest/services/CodeViolationProperty/FeatureServer/0` | 1,064 of 8,590 | open case (`In Violation`, `Open`) and problem like boarded building, demolition, vacant building | `CaseNum`,`OpenedDate`,`Problem`,`CaseStatus`,`ADDRESS` | City of Columbia, Richland County. Richland had 9 leads and no code signal. Address only, no owner or parcel. The feed's newest case is 2026-01-15, so treat as a backfill. Live run returned 1,064 leads. |

`Layer` gained an optional `amount` field. It is written to `raw["arcgis_distress"]["amount_owed"]`, the key
`enrichment_tax_owed`'s generic scan already reads, so the Greenville bill reaches `raw["tax_owed"]` and the
debt-aware ranking. The slug must contain "tax" for that scan to fire.

### 3c. Verified and held back

- **Dorchester** `https://gisportal.dorchestercounty.net/hosting/rest/services/General_Data/Parcels_Public/MapServer/0`: open, 80,111 parcels, `maxRecordCount` 90000. Fields `FULL_TMS` (`003-00-00-037.000`), `TMS`, `PARCELNO`, `OWNER`, `MAILING_ADDRESS`, `CITY_STATE_ZIP`, `PROPERTY_LOCATION`, `TAXED_ACRES`, `SALE_PRICE`, `SALE_DATE`. No value. The service's own license text (from `.../MapServer/info/iteminfo`): "Basic Public data - not to be added to any pay for use locations without prior written approval of Dorchester County Assessor or GIS Director." Dorchester has 4 board rows. Held back until the owner decides whether that clause applies. To ship it: `id_fields ["FULL_TMS","TMS","PARCELNO"]`, `owner "OWNER"`, `address "PROPERTY_LOCATION"`, `owner_mailing ["MAILING_ADDRESS","CITY_STATE_ZIP"]`, `acreage "TAXED_ACRES"`, `state "SC"`.
- **Beaufort** `https://gis.beaufortcountysc.gov/server/rest/services/EnerGov/MapServer/1` (141,372 parcels, `GisFile_PIN`, `GisFile_Owner1`, `GisFile_MailingAdd`, `GisFile_SitusAddre`, `GisFile_Appraised`) and **Georgetown** `https://gis1.georgetowncountysc.org/server/rest/services/GCGIS_OpenData/MapServer/7` (57,530 attribute rows: owner, billing address, street, sale; no value). Both open. Not in the target list and no board demand measured, so not added; add when a Beaufort or Georgetown source lands.

### 3d. What I could not verify or did not ship

- No parcel cache for Richland, Kershaw, Marion, Williamsburg, Clarendon, Marlboro, Edgefield, Fairfield (section 8).
- Darlington address coverage (65%): no better field exists. `E911_STNUM` is 64% and `E911_STREE` 67% populated; `DESCRIPT2` is 92% populated but free text ("3744 & 3740 OATES HWY LOTS C/D"). The county's address points (`Darco_AddressPnts` layer 1, 35,108 points) carry latitude and longitude but no parcel key, so filling the rest needs a nearest-point spatial join against the parcel layer's `XCOORD`/`YCOORD`. Not built.
- Horry `tax_value` is mapped from `AssessedProp`, a 4% ratio figure (4,930 on a 123,282 parcel). `tax_value` is the ARV fallback (x1.25), so any Horry parcel with no market value would be priced at a fraction of its worth. I left the existing entry alone and flag it here.

## 4. South Carolina, 18 counties

Categories: (a) delinquent tax or tax sale, (b) parcels with situs, owner, mailing, value, (c) probate, (d) code enforcement or vacancy, (e) foreclosure sale notices.
Catalis means the tax API at `https://d1ebsyxxbc7tep.cloudfront.net/data/<GUID>/Records` (POST JSON, `{"year":-1,"payStatus":"Unpaid","type":"Property","parameter":"Name","value":"<prefix>"}`). It serves `robots: Disallow /` (not a wall per the owner decision) and answers 429 if hit fast; the repo's `sc_catalis_delinquent_roll.py` paces 8 seconds per request.

### Chester (0 rows)
| Cat | Source | Format | V | Detail | Wall |
|---|---|---|---|---|---|
| a | Catalis GUID `61020303-8d26-4a16-b995-6deb1def7d97`, site `chestercountysctax.com` | JSON | V-me | Prefix "BROWN": 351 records, 73 `Delinquent` real property back to 2016. Parcel `061-02-00-021-000` matches the parcel layer's format. Fields: situs in `Description`, owner mailing, `Appraised`, `AmountDue`. Same schema as Pickens, no parser change. | none |
| b | Parcel layer above | ArcGIS | V-me | 22,300, owner, mailing, value; no situs | none |
| c d e | `chestercountysc.gov` | HTML | V-agent | Cloudflare managed challenge | WALLED |

### Fairfield (0 rows)
| Cat | Source | Format | V | Detail | Wall |
|---|---|---|---|---|---|
| a | Catalis GUID `89835e71-6978-4dc5-a0a8-17306a76b81f`, site `fairfieldsctax.com` | JSON | V-agent | Prefix "ALSTON": 51 records, 3 real (`RecordType:"Real"`, `DelqSw:true`), `LastUpdated` 2026-09-18. Needs a small adapter because the type is not `Delinquent`. | none |
| a | `https://www.fairfieldsc.com/uploads/uploads/11-3-2025_Tax_Sale_Listing.pdf` | PDF, 7 pp | V-me (spot: HTTP 200, 243,603 bytes) | 305 TMS in the 2025 list. Lines are name, TMS, size code. 2026 list not posted yet; sale Nov 2, ads Oct 15, 22, 29. Link appears on `fairfieldsc.com/departments/tax-collector`. | none |
| b | qPublic | | V-me | HTTP 403, Cloudflare "Just a moment..." interstitial | WALLED |
| c d e | county pages | | V-agent | no online estate search, no sale list, no code layer. `fairfieldcountyprobate.com` is Fairfield County, Ohio. | none found |

### Hampton (0 rows)
| Cat | Source | Format | V | Detail | Wall |
|---|---|---|---|---|---|
| a | Catalis GUID `38077f99-bf3d-48df-8d9a-467eb4de0d64`, site `hamptoncountytax.org` | JSON | V-me | Prefix "BROWN": 89 records, 86 `Delinquent`, tax years 2013 to 2025. Parcel ids like `069-00-00-078.03`. | none |
| b | Parcel layer above | ArcGIS | V-me | 14,871 | none |
| c d e | `hamptoncountysc.org` pages | HTML | V-agent | no list, no search; the SC Public Index link is the walled domain | none found |

The old Hampton qPayBill note (dead stub) is correct; `hamptoncountytax.org` is the real source.

### Edgefield (1 row)
| Cat | Source | Format | V | Detail | Wall |
|---|---|---|---|---|---|
| a | `https://edgefieldcountysc.qpaybill.com/Taxes/TaxesDefaultType4.aspx` | qPayBill Type4 | V-agent | Name prefix search returns a 25-row page; same form as the other qPayBill counties. Not in the roster in `qpaybill_delinquent_roll.py`. | none |
| a | `edgefieldcounty.sc.gov/tax-collector/` | HTML | V-agent | sale first Monday of December (Dec 7); no list posted | plain HTTP gets 403, WebFetch reads it |
| e | `mcdonaldpatrick.com/foreclosure-sales/edgefield-county-foreclosure-sales/`, PDF `.../2026/08/Sept-1-11-and-Sept-8-2026-Tues-930AM-Edg-sales-list.pdf` | HTML + PDF | V-agent | 3 entries (case number, TMS, address). Firm not in the repo. | none |
| b | qPublic / Equator | | V-me (qPublic class) | Cloudflare challenge | WALLED |
| c d | probate page, code page | | V-agent | no search; `/code-enforcement/` 404 | none found |

### Greenwood (1 row)
| Cat | Source | Format | V | Detail | Wall |
|---|---|---|---|---|---|
| b | CAMA layer above | ArcGIS | V-me | 39,553 | none |
| c | Spartan portal `https://scportal.hostedbyspartan.com/GreenwoodPublicPortal/Handlers/Data.asmx/CaseSearch?sEcho=1&iColumns=5&iDisplayStart=0&iDisplayLength=500&AgencyId=24500&CaseNumber=2026ES` (prime a cookie by loading `pages/CaseSearchPage.aspx`) | JSON in `{"d": "<json>"}` | V-agent | 429 estate cases for 2026 in one call, latest filed 2026-09-18. Detail page `pages/CaseDetailPage.aspx?AgencyId=24500&CaseId=<id>&PartySeq=1` gives date of death, decedent address, personal representative. | none |
| e | `mcdonaldpatrick.com/foreclosure-sales/greenwood-county-foreclosure-sales/`, PDF `.../2026/08/Sept-8-2026-Gwd-sales-list.pdf` | HTML + PDF | V-agent | 8 entries with address, GIS number, case number. Same site lists Abbeville, McCormick, Saluda, Newberry. | none |
| a | none county-hosted | | V-agent | `greenwoodco.corebtpay.com` needs an exact TMS or full name; list runs as Index-Journal ads | none found |

### Marion (1 row)
| Cat | Source | Format | V | Detail | Wall |
|---|---|---|---|---|---|
| a c e | Column API (`https://us-central1-enotice-production.cloudfunctions.net/api/search/public-notices`), county "Marion" | JSON | V-agent | Foreclosure 19 cases a year, estates 90+ (250-row cap, use 120-day windows), delinquent tax as a `Public Auction` notice (about 150 parcels, image-only PDF needs OCR). Sale 2026-11-02, ads Oct 14, 21, 28. | none |
| b | `marionsc.wthgis.com` | proprietary "tgis" viewer | V-me | No ArcGIS REST endpoint; the viewer runs on its own JS protocol | none found |
| d | `marionsc.org/departments/code_enforcement/` | HTML | V-agent | forms and ordinance only | none found |

### Dorchester (4 rows)
| Cat | Source | Format | V | Detail | Wall |
|---|---|---|---|---|---|
| b | Parcel layer, section 3c | ArcGIS | V-me | 80,111, open, but the service license restricts pay-for-use redistribution | held back |
| e | Column API | JSON | V-agent | 3 notices of sale | none |
| a c d | `dorchestercountysc.gov` | | V-agent | every page 403 from AkamaiGHost "Access Denied"; delinquent tax lookup is a disclaimer click-through. GIS servers hold no delinquent, code or foreclosure layer. Sale 2026-10-19. | WALLED |

### Richland (9 rows)
| Cat | Source | Format | V | Detail | Wall |
|---|---|---|---|---|---|
| a | `https://richlandmaps.com/apps/api/layers/load.php?layer=delinquent&fields=owner,tms,address,balance,due1,due2,due3,due4,other1,other2&where=&roi=SRID=4326;POLYGON((-81.5 33.6,-81.5 34.3,-80.5 34.3,-80.5 33.6,-81.5 33.6))&zoom=12&geomtype=wkt&limit=2222` | custom JSON (`{"data":[...]}`) with a WKT polygon per row | V-me | The county's tax-sale parcel layer, updated nightly before the sale. 16 rows today, cap 2,222; sale Nov 2 and 3. TMS form `R19701-04-08`. Owner is HTML-escaped. | none (the viewer shows a client-side disclaimer; the API call needs no acceptance) |
| d | City of Columbia layer, section 3b | ArcGIS | V-me | 1,064 admitted | none |
| c | `https://www7.richlandcountysc.gov/EstateInquiry/main.aspx` | HTML POST | V-agent | name index with date of death, no address; usable only as an owner-name modifier | none |
| b | `richlandmaps.com/apps/dataviewer/` | custom Leaflet and PHP | V-me | Not ArcGIS REST. The API is ROI-and-limit based with no count query, so the cache builder's completeness check cannot run on it. | none found |
| e | Master-in-Equity roster | | V-agent | on publicindex courtrosters (disclaimer click-through) | WALLED |

### Aiken (12 rows)
| Cat | Source | Format | V | Detail | Wall |
|---|---|---|---|---|---|
| b | Parcel layer, section 3a | ArcGIS | V-me | 103,207, whole county | none |
| a | Catalis GUID `27a11acb-7de9-43e7-a078-f98cfb4fc397`, site `aikencountysctax.com` | JSON | V-agent | Heavy: one "BROWN" prefix returned 3.2 MB and 740 records (510 vehicle, 131 mobile home, 47 `Delinquent`, 6 `Real`). Real rows carry parcel and situs but no owner mailing. | none |
| a | `sc-aikencounty.civicplus.com/309/Delinquent-Tax-Sale` | HTML | V-agent | sale Nov 2, ads run in the Aiken Standard; no list on the site. `www.aikencountysc.gov` is Cloudflare-challenged, this CivicPlus host is not. | none |
| c | `southcarolinaprobate.net/search` | | V-agent | 403 from `awselb/2.0` for two agents | see section 8 |
| e | roster on `publicindex.sccourts.org/aiken/courtrosters/` | | V-agent | disclaimer click-through | WALLED |
| d | `/276/Code-Enforcement` | HTML | V-agent | complaint driven, no public list | none found |

### Charleston (6,457 rows, mail 0%)
| Cat | Source | Format | V | Detail | Wall |
|---|---|---|---|---|---|
| b | Parcel layer and overlay, section 3a | ArcGIS | V-me | 197,677 parcels, 70,072 address points | none |
| a | `https://www.charlestoncounty.gov/departments/delinquent-tax/files/tax_sale/RP-Tax-Sale-Listing.xlsx` (mobile homes: `MH-Tax-Sale-Listing.xlsx`) | xlsx | V-me | 2,416 sheet rows. Columns `PIN`,`CLASS CODE`,`OWNER`,`SITUS ADDRESS`,`CITY`,`TAG`,`ACREAGE`,`TOTAL DUE`,`APPRAISAL`. PIN is the same 10-digit key as the parcel cache. The existing scraper reads the PDF and is gated to Oct to Feb; the list is live now (sale 2026-11-09). | none |
| e | `charlestoncounty.gov/foreclosure/runninglist.html` | HTML | V-agent | already scraped (`charleston_mie`) | none |
| c | `southcarolinaprobate.net/charlestonprobatesearch/` | | V-agent | 403 | WALLED from this network |
| d | City, County and pdi hub catalogs | | V-agent | only short-term-rental and new-construction permits | none found |

### Greenville (2,602 rows, address 12%, value 0%, mail 0%)
| Cat | Source | Format | V | Detail | Wall |
|---|---|---|---|---|---|
| b | Parcel layer, section 3a | ArcGIS | V-me | 244,178 | none |
| a | Unpaid-tax layer, section 3b | ArcGIS | V-me | 2,855 | none |
| a | `https://www.greenvillecounty.org/appsAS400/Taxsale/` | HTML | V-agent | now serves the Oct 19-20, 2026 sale (about 1,365 distinct TMS); already scraped | none |
| c | `https://www.greenvillecounty.org/appsAS400/Probate/` | ASP.NET | V-agent | case-number and name search, 2026 cases reach at least #1,800, detail page gives decedent address and date of death | none |
| e | `mie.greenvillejournal.com` | | V-agent | 403 to plain clients; the county roster is a disclaimer click-through | WALLED |
| d | county pages, City `citygis.greenvillesc.gov` | | V-agent | phone driven, no list; only a building-permit layer | none found |

### Florence (2,006 rows, address 2%, value 0%)
| Cat | Source | Format | V | Detail | Wall |
|---|---|---|---|---|---|
| b | Parcel layer, section 3a | ArcGIS | V-me | 70,098 | none |
| a | `https://services1.arcgis.com/otEVSGO5ESloTE5q/arcgis/rest/services/DEL_TAX_POLY/FeatureServer/0` | ArcGIS | V-me | 1,644 delinquent parcels with owner, mailing, situs and building value, refreshed 2026-09-02 per the Pee Dee agent. Overlaps the 2,006 PDF rows; the new parcel cache already supplies these fields, so not added as a lead source. About 160 owner names contain ESTATE or HEIRS. | none |
| a | `https://arc2000.florenceco.org/arcgis/rest/services/DelinqParcRts/FeatureServer/0` | ArcGIS | V-me | 3,668 rows, fields `TMS`,`STATUS` ("POSTED"),`RT_NAME`. A notice-posting route file, no owner. Not added. | none |
| e | `https://s3.us-east-1.amazonaws.com/files.florenceco.org/public/MasterInEquity/foreclosure/septList.pdf` | monthly PDF | V-agent | 9 rows (TMS, address, case number); filename changes monthly, discover it from `florencecountysc.gov/offices/equity/` | none |
| a c e | Column API | JSON | V-agent | 91 + 130 foreclosure and notice-of-sale rows (28 + 22 cases) and 36 estate cases a year | none |
| c | `florencecountysc.gov/offices/elected/probate-court/estate.php` | forms | V-agent | forms only | none found |

### Horry (4,254 rows, address 41%, mail 35%)
| Cat | Source | Format | V | Detail | Wall |
|---|---|---|---|---|---|
| b | Existing parcel cache plus overlay, section 3a | ArcGIS | V-me | overlay 242,675 points | none |
| a | `https://www.horrycountysc.gov/media/b5af14ce/delinquent-list-on-website-081926.xlsx`, linked from `/departments/treasurer/delinquent-tax/` | xlsx, weekly, filename dated | V-agent | 4,952 rows, sale 2026-11-30, 405 rows carry a "New Owner Name". | none |
| a | `https://gisportal.horrycounty.org/server/rest/services/Hosted/DelqTaxUpdates/FeatureServer/0` | ArcGIS | V-me | 1,937 rows, `item_number`,`pin`,`tms`,`owner_name`,`new_owner_name`,`total_tax_due`. Last edited 2026-05-20. Board already has 99% tax balance from qPayBill, so not added. | none |
| e | `https://www.horrycountysc.gov/departments/master-in-equity/principal-sales/` | HTML table | V-me (spot: HTTP 200) | about 21 rows for the Oct 5 sale: case number, address, judgment, lien type, deficiency flag | none |
| c | `https://scportal.hostedbyspartan.com/HorryPublicProbate/pages/CaseSearchPage.aspx` | ASMX JSON | V-agent | 2,968 estates in 2026 (`CaseNumber` prefix `2026ES26`, `AgencyId=26500`). A judicial-assistant-only filter returns nothing. | none |
| d | | | V-agent | none found; GIS servers hold only backing layers | none found |

### Williamsburg (2,390 rows)
| Cat | Source | Format | V | Detail | Wall |
|---|---|---|---|---|---|
| a | `https://williamsburgcounty.sc.gov/DocumentCenter/View/2202/DELINQUENT-TAX-SALE` (2025 list) | PDF, 30 pp | V-me (spot: HTTP 200, 489,441 bytes) | 885 TMS: owner, acres, buildings, district, TMS; no address or amount. 2026 list posts on `/325/Delinquent-Tax-Sale`; the DocumentCenter id will change. Marks which qPayBill rows are heading to sale. | none |
| b | `williamsburgsc.wthgis.com` | tgis viewer | V-me | no REST endpoint | none found |
| c d e | | | V-agent | no notices in Column, no probate, MIE or code source | none found |

### Marlboro (1,061 rows)
| Cat | Source | Format | V | Detail | Wall |
|---|---|---|---|---|---|
| c | Column API | JSON | V-agent | 63 estate cases a year | none |
| a | `https://cms2.revize.com/revize/marlborocosc/Documents/Delinquent%20Tax/Tax%20Sale%20-%202026%20Calendar.pdf` | PDF | V-agent | calendar only: sale 2026-11-09, ads Oct 8, 15, 22 in the Herald-Advocate | none |
| b | `marlborosc.wthgis.com` | tgis viewer | V-me | no REST endpoint | none found |

### Clarendon (1,273 rows)
Nothing new. No county-hosted tax list (the 2024 ad PDF now 404s; `clarendon_tax_auction.py` points at the homepage). qPayBill already used. Column has 5 non-distress notices. Parcels: qPublic (Cloudflare) and a WTH viewer. V-agent.

### Kershaw (1,729 rows)
Nothing usable. `kershawcounty.qpaybill.com` is already in the qPayBill roster. The open `Parcels_view` (`https://services6.arcgis.com/kyYrMHheB5jkAnFA/arcgis/rest/services/Parcels_view/FeatureServer/0`, 43,646 rows) carries only `PRSNTP_ID` and `taxTotalAc`, no owner (V-me). `www.kershaw.sc.gov` is Akamai "Access Denied" (V-agent). Address points (`Addresses_view`, 38,076) have no parcel key (V-me).

### Berkeley (2,325 rows, value 0%)
| Cat | Source | Format | V | Detail | Wall |
|---|---|---|---|---|---|
| b | Parcel layer, section 3a | ArcGIS | V-me | 123,050 | none |
| e | Column API | JSON | V-agent | 9 `Summons` foreclosure complaints in 365 days | none |
| a | `berkeleycountysc.paystar.io/api/search` | JSON | V-agent | already scraped, 3,463 unpaid real property | none |
| a c e | `berkeleycountysc.gov` pages (MIE, tax sale listing) | | V-agent | Cloudflare "Just a moment..." | WALLED |

## 5. North Carolina, 12 counties

NC parcels: the statewide NC OneMap layer is already wired into the cache (`nc_onemap_cfg`) and each of these counties has a cache file. I re-checked the live layer for all 12 (V-me):

| County | OneMap parcels | Owner | Situs | Mailing | Value |
|---|---|---|---|---|---|
| Tyrrell | 4,368 | 99% | 64% | 96% | 98% |
| Washington | 12,608 | 79% | 79% | 79% | 79% |
| Graham | 9,840 | 96% | 94% | 96% | 96% |
| Hertford | 16,102 | 100% | 100% | 100% | 95% |
| Bertie | 18,788 | 100% | 100% | 100% | 100% |
| Gates | 7,997 | 100% | 99% | 100% | 100% |
| Northampton | 20,504 | 100% | 43% | 98% | 100% |
| Martin | 17,415 | 100% | 100% | 100% | 100% |
| Greene | 12,720 | 98% | 98% | 98% | 98% |
| Jones | 9,451 | 100% | 99% | 100% | 99% |
| Onslow | 95,297 | 100% | 100% | 100% | 100% |
| Brunswick | 151,753 | 100% | 70% | 94% | 100% |

The low Onslow and Brunswick parcel numbers on the board are leads with no `parcel_id`, not a cache gap. That needs an address-to-parcel resolver, not another layer.

Join keys from the NC agent (V-agent): Bertie strip `25A` then `parno`; Jones and Martin strip hyphens then `parno`; Washington dotted PIN then `altparno`; Tyrrell strip spaces then `altparno`; Greene 7-digit id then `altparno`; Gates match situs to `siteadd`.

Column API means `POST https://us-central1-enotice-production.cloudfunctions.net/api/search/public-notices` with `state` set to `"North Carolina"`. Column tags a notice by newspaper coverage county, not property county. Northampton notices sit under "Hertford", Jones under "Craven", Tyrrell under "Dare", Greene under "Lenoir". AO means `albemarleobserver.news`, which republishes the annual NCGS 105-369 delinquent lists free (find new posts with `https://albemarleobserver.news/wp-json/wp/v2/posts?search=delinquent&per_page=50&_fields=id,date,link,title,content`).

| County | Cat | Source | V | Detail | Wall |
|---|---|---|---|---|---|
| Tyrrell | a | AO `.../2026/04/27/public-record-tyrrell-county-2025-unpaid-taxes-list/` | V-agent | 391 rows: name, id, amount; no situs. Posts late April. | none |
| Tyrrell | e | Column, tag "Dare" | V-agent | 1 to 2 tax sale notices in 2 years | none |
| Washington | a | AO `.../2026/06/09/washington-county-delinquent-property-tax-list-have-you-paid-your-taxes/` and Plymouth `.../2026/06/11/plymouths-delinquent-tax-list-...` | V-agent | 1,206 and 569 rows: name, account, amount | none |
| Washington | e | Column, tag "Washington" (Roanoke Beacon) | V-me (spot) | returns notices; 18 tax foreclosures in 2 years per agent | none |
| Graham | a | `https://www.bttaxpayerportal.com/ITSPublicGR2.0/TaxBillSearch` | V-agent | 925 unpaid 2025 bills; two POSTs (`GetSearchTablePartial`, `GetSearchTableData`) with one cookie session | none |
| Hertford | e c | Column, tag "Hertford" | V-me | 12 unique foreclosure notices and 2 estate notices in 2 years; also carries most Northampton notices | none |
| Hertford | a | `bcpwa.ncptscloud.com/api/GetTaxpayerDownloadList` (header `X-Tenant: Hertford`) | V-agent | valid tenant, empty export | none found |
| Bertie | a | AO `.../2026/06/05/bertie-county-2025-delinquent-personal-property-tax-list/` | V-agent | 1,565 parcel rows (the title says personal property, the table is real-property PINs), about $460K | none |
| Bertie | e | Column, tag "Bertie" | V-me | 2 to 3 notices in 2 years | none |
| Bertie | a | `bertie.webtaxpay.com` | V-agent | redirects to `secure.webtaxpay.com/challenge.php`, "Verification required, confirming you are human" | WALLED |
| Gates | a | AO `.../2026/05/26/gates-county-delinquent-property-tax-list-have-you-paid-your-taxes/` | V-me (spot: HTTP 200, 457,794 bytes) | 1,555 rows with situs and 11 years of arrears, about $979K | none |
| Gates | e | Column, tag "Gates" | V-me | 5 tax sales, Dec 2025 | none |
| Northampton | e c | Column, tag "Hertford" | V-agent | about 17 to 25 foreclosure notices in 2 years, 1 estate notice | none |
| Martin | a | `https://cms9files.revize.com/martincountync/Document%20Center/Public%20Notices/2025/2024%20Tax%20Liens.pdf` | V-agent | 14 pp, about 2,600 amounts; the 2024 list. Pattern `/Public Notices/<yr>/<taxyear> Tax Liens.pdf`, posted each April. | none |
| Martin | e | Column, tag "Martin" | V-me | 17 in 2 years, sale 2026-09-24 | none |
| Greene | e | `greenecountync.gov/departments/tax/county-foreclosed-properties/` | V-agent | 1 stale row (sale 2025-09-26); Column tag "Lenoir" has 1 | none |
| Greene | a | annual ad | V-agent | not online; Tyler Munis portal redirects to an upgrade page | none found |
| Jones | e | Column, tag "Craven" (Sun Journal) | V-agent | 15 unique tax-sale notices in 2 years; county must be re-derived from "District Court of Jones County" | none |
| Onslow | a | `https://tax.onslowcountync.gov/ITSPublicON/TaxBillSearch` | V-me | 7,428 unpaid 2025 bills (numRecords matched the agent's figure). Mixes real property and personal property; filter on the description. About 300 requests a year. | none |
| Onslow | a | `onslowcountync.gov/DocumentCenter/View/15738/...` and the foreclosure pages | V-agent | 403 Cloudflare "Just a moment..." | WALLED |
| Brunswick | e | `https://bcgis.brunswickcountync.gov/arcgis/rest/services/Mapping/SurplusProperty/MapServer/0` and `/1` | V-agent | 1 row each: county surplus in upset-bid status. Not added. | none |
| Brunswick | a d | | V-agent | no delinquent list online; 104 GIS services hold no code, condemned or demolition layer | none found |
| All 12 | c | | V-agent | no free probate source except the Column notices for Hertford and Northampton; eCourts is walled | none found |
| All 12 | d | | V-agent | no code, condemned or demolition list. Onslow's and Jacksonville's code layers are officer-zone polygons. | none found |

Dead base URLs in `nc_civicplus_tax_sale.py` (fail DNS): `grahamcounty.gov`, `northamptonnc.gov`, `tyrrellcountync.gov`, `washingtoncountync.gov`. Real hosts: `grahamcounty.org`, `northamptonnc.com`, `tyrrellcounty.org` (http only), `washconc.org`.

## 6. Statewide and multi-county sources (V-agent unless noted)

| Category | Source | Format and volume | Wall or caveat |
|---|---|---|---|
| NC probate, divorce, foreclosure, tax notices | `ncnotices.com/Search.aspx` | ASP.NET grid, plain POST sequence works, 1,000 row cap per query, all 97 NC counties in the filter; repo covers 19 | Grid preview is open. Detail pages need a terms click-through and reCAPTCHA, and the written terms ban scraping. Treat as an owner decision, not a clean win. |
| SC probate, family court, foreclosure | `scpublicnotices.com/Search.aspx` | same platform, all 46 SC counties; "divorce" over 365 days is about 200 rows | same as above |
| SC probate, York, Dorchester, Charleston | `southcarolinaprobate.net/search/` | York about 1,400 cases so far in 2026, Charleston about 1,500, Dorchester about 1,000 a year | Exact case-number lookup only; two agents got 403 today, one got 200 with a Safari User-Agent |
| SC probate, Greenville | `greenvillecounty.org/appsas400/Probate/` | case-number or name search; detail page gives decedent address | open |
| SC probate, Anderson | `acpass.andersoncountysc.org/esmain.cgi` | about 1,100 a year, index stops around Aug 2024 | open; `robots.txt` Disallow / |
| SC probate, Horry and Greenwood | Spartan portals (section 4) | JSON | open |
| Bankruptcy, RSS | `ecf.{scb,ncmb,ncwb}.uscourts.gov/cgi-bin/rss_outside.pl` | SC 514 entries and 371 cases in 24 hours; NC Middle 293; NC Western 64; NC Eastern returns an empty body | open; debtor names only |
| Bankruptcy, RECAP | `courtlistener.com/api/rest/v4/search/?type=r&court=...` | 30 days: SC about 500, NC Eastern 484, NC Western about 244, NC Middle about 227 | search open; dockets, parties, bankruptcy information return 401 without a token |
| REO, HUD FHA | `https://services.arcgis.com/VTyQ9soqVukalItT/arcgis/rest/services/SF_REO/FeatureServer/0` | 622 national, NC 11, SC 10 | open; flip type, footprint only |
| REO, HUD Home Store, Fannie, Freddie, VA | `hudhomestore.gov/searchresult?handler=GetFilteredResult`, HomePath, HomeSteps, VRM | JSON and HTML | open; already covered by `hud_homestore.py` and siblings |
| REO, USDA | `properties.sc.egov.usda.gov/resales/public/searchSFH` | SC 1, NC 0 | open; `usdaproperties.com` is Cloudflare-challenged so `usda_properties.py` is dead |
| Storm | NCEM Burke points (`NCEM_Damage_Assessment_BC/.../119`, 456), Transylvania substantial-damage structures (`Helene_SD_Structures/FeatureServer/306`, 44 rows, carries owner names and phones) | ArcGIS | Burke layer already wired; the Transylvania layer holds sensitive fields |
| Storm, area prior | OpenFEMA `HousingAssistanceOwners` (NC 5,221 rows, SC 2,958) and `FimaNfipClaims` (NC 109,539, SC 49,606) | JSON | ZIP or tract only, no addresses |
| Tax, Mecklenburg | `tax.mecknc.gov/Delinquent-Taxpayer-Lists` | 1,087-page PDF, 129,606 rows, about 2,950 look like real estate (agent's estimate) | open; no Mecklenburg scraper in the repo |
| Already covered | SC DOR delinquent lists, SC DEW lien registry, SC DES brownfields, `nchfa_reo.py` | | unchanged |

## 7. Ranked build list (lead yield per effort)

Yields are counts the sources returned, not board estimates. Effort: S is config or a few lines, M is a small scraper or adapter, L is a new scraper with parsing.

| # | Item | Effort | Yield | Where and how |
|---|---|---|---|---|
| 1 | Chester and Hampton via Catalis | S | Two zero-row counties. One prefix returned 73 (Chester) and 86 (Hampton) delinquent real-property records; a full alphabet sweep will be far more. | Add two entries to `CATALIS_COUNTIES` in `scrapers/counties_sc/sc_catalis_delinquent_roll.py` with the GUIDs in section 4; same schema as Pickens, no parser change. Pace 8 seconds a request. The new Chester and Hampton parcel caches join on the same `Map_Number`/`Parcel_polygons_TMS` format. |
| 2 | Fairfield and Aiken via Catalis | M | Fairfield zero-row county; Aiken 47 `Delinquent` plus 6 `Real` in one heavy prefix. | Same module with a small adapter: Fairfield accepts `RecordType == "Real"` with `DelqSw`, situs in `Description`; Aiken responses are about 3 MB per prefix, so depth-limit the name sweep. |
| 3 | Column notice API footprint | S for NC, M for SC | NC: 5 counties, about 60 foreclosure notices in 2 years. SC: Florence 50 foreclosure and 36 estate cases a year, Marion 19 and 90+, Marlboro 63 estates. | `NC_FOOTPRINT` in `scrapers/newspapers/column_legal_notices.py`: add Washington, Hertford, Bertie, Gates, Martin (verified live by me); attribute Northampton, Jones, Tyrrell, Greene by regex on "District Court of X County" from the Hertford, Craven, Dare, Lenoir tags. `SC_FOOTPRINT`: add Florence, Marion, Marlboro, Darlington, Sumter, Berkeley, Dorchester and add a SC foreclosure parser (`TMS:`, `Property Address:`, case number); the module's docstring says SC has no foreclosure type, which is false for these counties. |
| 4 | Onslow and Graham ITSPublic tax portals | M | Onslow 7,428 unpaid 2025 bills, Graham 925. | One new adapter for `tax.onslowcountync.gov/ITSPublicON/TaxBillSearch` and `bttaxpayerportal.com/ITSPublicGR2.0/TaxBillSearch`: GET the search page for the cookie, POST `GetSearchTablePartial` (`{"PageSize":25,"UnpaidBillsOnly":true,"TaxYear":"2025"}`) then page `GetSearchTableData` (`{"Page":n,"NumRows":25,"Table":"PayTaxBills"}`). Drop "Personal Property" rows (Onslow mixes them in). Join on `parno` from the OneMap cache. |
| 5 | Charleston tax-sale xlsx | S | 2,402 real property plus about 1,224 mobile homes a year, with situs and appraisal. | Swap the pdfplumber path in `scrapers/counties_sc/charleston_delinquent_tax.py` for the xlsx (`PIN`,`OWNER`,`SITUS ADDRESS`,`TOTAL DUE`,`APPRAISAL`) and lift the Oct to Feb gate. |
| 6 | Horry delinquent xlsx, MIE table, probate | M each | 4,952 delinquent rows; about 21 principal sales a month; 2,968 estates in 2026. | Delinquent: regex the dated `delinquent-list*.xlsx` link from the treasurer page each run and read it with the stdlib xlsx reader `horry_flc.py` uses. MIE: parse the table rows, TMS from the land-records href. Probate: GET the search page for a cookie, page `Handlers/Data.asmx/CaseSearch` with `CaseNumber=2026ES26`, `AgencyId=26500`. |
| 7 | Albemarle Observer NC lists | M | Tyrrell 391, Washington 1,206 plus Plymouth 569, Gates 1,555 with situs, Bertie 1,565. | One WordPress parser over the `wp-json` posts. Gates has situs. Bertie: strip `25A`, match `parno`. Tyrrell: strip spaces, match `altparno`. Washington: name and account only, so run the name resolver. Republish window April to June. |
| 8 | Greenwood probate (Spartan) | M | 429 estate cases for 2026 in one call; detail page has decedent address, date of death, representative. | Same portal family as Horry. Emit `PROBATE_NOTICE` rows and let the name-to-parcel enricher match; Greenwood parcels now cached. |
| 9 | Tax-sale lists that post in October | M | Fairfield about 300 TMS, Williamsburg about 885, Richland 16 and growing, Marion about 150, Marlboro calendar only. | Fairfield PDF (`Tax_Sale_Listing`, PyMuPDF), Williamsburg PDF (regex `\d{2}-\d{3}-\d{3}`), Richland `load.php` nightly poll until Nov 3, Marion via the Column `pdfurl` and the existing Gemini OCR. Use Williamsburg's list to flag qPayBill rows as sale-bound. |
| 10 | McDonald Patrick foreclosure sale lists | S | 3 to 8 sales a month each for Greenwood, Edgefield, Abbeville, McCormick, Saluda, Newberry. | Fetch the county page, follow `*sales-list.pdf`, parse address, TMS or GIS number, case number. |
| 11 | Edgefield in the qPayBill roster | S | Edgefield's whole unpaid roll (1 row today). | Add `"Edgefield": "edgefieldcountysc"` to the roster in `qpaybill_delinquent_roll.py`. |
| 12 | Statewide life events (needs an owner call on terms) | L | NC notice to creditors and divorce notices across 97 counties; SC divorce summonses; Greenville probate by case-number enumeration. | Extend `nc_notices_counties.py` from 19 to 97 counties with the plain-POST driver (GET, tick county, `btnGo`, page with the image-button coordinates); stop dropping `20YY-DR-CC` family-court notices in `sc_public_notices.py`; new `greenville_probate.py`; rework `sc_probate_net.py` for York, Dorchester, Charleston to use case numbers. The grid is open but the site terms ban scraping and the detail pages are walled, so this is the item to decide on, not just build. |
| 13 | Bankruptcy RSS | M | SC 371 cases in 24 hours, NC Middle 178, NC Western; debtor names only. | New `national/bankruptcy_court_rss.py`; also relieves the CourtListener throttle. |
| 14 | Mecklenburg delinquent PDF | L | about 2,950 real-estate rows. | New scraper reading the signed CDN link from the Widen share page. |
| 15 | Richland, Darlington and Dorchester parcel work | M | Richland has no cache; Darlington situs 65%; Dorchester license. | Richland needs a custom reader for the ROI API; Darlington needs a nearest-point spatial join against `Darco_AddressPnts`; Dorchester needs the owner's license decision. |

Not worth building: Florence `DEL_TAX_POLY` and `DelqTaxUpdates` (Horry) as lead sources (overlap existing rolls, the parcel caches now supply the attributes), Florence `DelinqParcRts` (posting routes, no owner), Brunswick surplus (2 rows), HUD FHA layer (21 rows, flip type).

## 8. Walled, unverified, or none found (with evidence)

### Walled

| Target | Evidence |
|---|---|
| qPublic / Beacon (Fairfield, Chester, Edgefield, Clarendon, Aiken, Hampton and about 20 more SC counties) | I fetched a Fairfield qPublic URL: HTTP 403, body "Just a moment..." with `_cf_chl_opt` (Cloudflare interstitial). The SC DNR table `arcweb.dnr.sc.gov/.../SC_County_Parcel_Viewers/FeatureServer/0` lists 45 county viewer links; Hampton's is marked `login_required: yes`. |
| WTH "tgis" viewers (Marion, Williamsburg, Marlboro, Kershaw, Chesterfield, Dillon, McCormick) | `marionsc.wthgis.com` serves a proprietary viewer (`tgis/tgisServer2.js`). No ArcGIS REST root exists on any `*.wthgis.com` host I tried. Not an access wall; there is no documented endpoint, and reverse engineering the viewer protocol was not attempted. |
| `berkeleycountysc.gov`, `chestercountysc.gov`, `onslowcountync.gov` (some paths) | Cloudflare "Just a moment..." (`cf-mitigated: challenge`) |
| `dorchestercountysc.gov`, `kershaw.sc.gov`, `richlandcountysc.gov` | HTTP 403. Dorchester: AkamaiGHost "Access Denied". I got 403 from Richland and Dorchester with curl myself; Kershaw's Akamai reference came from an agent. |
| SCDOT parcels `smpesri.scdot.org/arcgis/rest/services/GISMapping/SC_Parcels/MapServer/<n>` | I re-checked today: `{"error":{"code":499,"message":"Token Required"}}` on the layer and on `/query` |
| `publicindex.sccourts.org/.../courtrosters` (Aiken, Greenville, Richland Master-in-Equity rosters), Dorchester delinquent tax lookup, `search.florencedeeds.com`, Charleston `jcmsweb.../publicindex` | disclaimer or accept click-throughs |
| `ncnotices.com` and `scpublicnotices.com` `Details.aspx` | "You must complete the challenge in order to continue": terms click-through plus reCAPTCHA; the written terms ban screen scraping and spidering |
| `bertie.webtaxpay.com` | redirect to `secure.webtaxpay.com/challenge.php`, "Verification required, confirming you are human" |
| `zls-nc.com/listings` | "I AGREE" click-through and a Blazor grid; only the public `/clients` counts are readable |
| `horrycounty.org/apps/LandRecords` | redirects to a login: "Requires an Horry County Government account" |
| Lexington probate `lex-co.com/probatesearchapi/api/Estate` | HTTP 401; token comes from `/token` after reCAPTCHA v3 |
| `usdaproperties.com` | Cloudflare "Just a moment..." |
| CourtListener dockets, parties, bankruptcy information | HTTP 401 without a token |
| `southcarolinaprobate.net` (all paths) | HTTP 403 from `awselb/2.0` for two agents; a third got 200 with a Safari User-Agent. Not confirmed as a wall. |
| Richland tax-sale bidder registration | $50 fee, so not used |

### Unverified

- Beaufort, Horry and Calhoun probate portals on `hostedbyspartan.com`: the form accepts a plain POST but returns only the form; the working request needs a captured browser trace (Horry's was captured by the Pee Dee agent).
- Jones portal `bttaxpayerportal.com/ITSPublicJN2.0` (search returned an empty body, data call 500) and Martin's portal (0 rows).
- `taxweb.washconc.org` enumeration.
- `scpublicnotices.com` county checkboxes for Williamsburg and Clarendon as a legal-ad route: not run end to end.

### None found after trying

- Code enforcement, condemned, dilapidated or vacant lists: none in any of the 30 counties except the City of Columbia layer (Richland). Tried: ArcGIS Online search per county and city with eight distress terms, hub catalog scans (City of Charleston, Charleston County, pdi), service listings for Florence, Horry, Berkeley, Dorchester, Brunswick, Onslow, Greenwood, Aiken city, county code pages and commissioner agenda pages. Onslow's and Jacksonville's code layers are officer-zone polygons only.
- County-hosted delinquent lists: none for Clarendon, Marlboro, Greenwood, Marion (October ad only), Graham, Greene, Jones, Northampton, Hertford, Brunswick (annual ad runs in the paper).
- Probate: none online for Williamsburg, Clarendon, Marion, Marlboro, Florence, Chester, Fairfield, Hampton, Edgefield, Kershaw and all NC targets except the Column notices for Hertford and Northampton.
- Free bankruptcy debtor addresses: PACER is paid, the RSS carries names only. 341-meeting calendars and trustee sites were not checked.
- SC family-court dockets with party names, NC DOR tax warrants, SC Master-in-Equity sale lists (only Horry and Florence publish one), NC unsafe-structure registries.

## 9. Defects found in existing code (not changed, for whoever owns them)

- `scrapers/counties_sc/greenville_hard_distress.py`: `GIS` points at `GreenvilleJS/Map_Layers_JS/MapServer`, which now answers `Service ... not found`. The replacement is the layer in section 3a; the parcel fields it reads (`OWNAM1`, `STREET`, `TOTTAX`, `PAIDDATE` and so on) exist there.
- `scrapers/counties_nc/nc_civicplus_tax_sale.py`: four dead hosts (section 5).
- Guessed URLs that do not serve a list: `chester_delinquent_tax.py` (Cloudflare), `kershaw_flc.py` (Akamai), `fairfield_delinquent_tax.py` (real page is `/departments/tax-collector`), `greenwood_delinquent_tax.py` (Wix soft-404 returning HTTP 200), `aiken_delinquent_tax.py` (redirects to a page with no list), `marlboro_delinquent_tax.py` (budget page), `clarendon_tax_auction.py` (homepage).
- `scrapers/newspapers/column_legal_notices.py`: `NC_FOOTPRINT` omits Washington, Hertford, Bertie, Gates, Martin; `SC_FOOTPRINT` omits Florence, Marion, Marlboro, Williamsburg, Clarendon, Berkeley, Dorchester.
- `parcel_cache.py` Horry `tax_value` is the assessed ratio figure (section 3d).
- `sc_public_notices.py` deliberately drops family-court notices, so SC divorce summonses are lost.
- Compliance note from the Midlands agent: Fairfield and Aiken publish SC Code 30-2-50 commercial-solicitation notices alongside their tax-sale materials. It does not block fetching; it bears on how owner contact data from those lists may be used.
