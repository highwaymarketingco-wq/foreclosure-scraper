# ROUND 3 EXECUTIVE LAYER
11 counties, enumerated 2026-08-03. Full register sections filed separately.

---

## 1. SCOREBOARD

| County | Net-new (as filed) |
|---|---|
| Transylvania NC | 38 |
| Pickens SC | 32 |
| Gaston NC | 31 |
| Cleveland NC | 27 |
| McDowell NC | 26 |
| Mitchell NC | 26 |
| Anderson SC | 24 |
| Laurens SC | 23 |
| Union SC | 21 |
| Rutherford NC | 17 |
| Polk NC | 13 |
| **ROUND 3 RAW** | **278** |

**Running total:** R1 251 + R2 ~234 + R3 278 = **763 raw**.
**De-duplicated estimate: ~740** (R3 adjusted to ~255). That adjustment is an **estimate, not verified** — the register tails I was given are truncated, so I cannot audit every row.

### Suspected double-counts (flagged, not silently netted out)

1. **NC OneMap `NC1Map_Parcels`** (`https://services.nconemap.gov/secure/rest/services/NC1Map_Parcels/MapServer/1/query`) is counted as net-new in **Cleveland, McDowell, and Mitchell**. One statewide source, three rows. True over-count +2, and it will recur in every future NC county.
2. **Intra-county parcel mirrors counted as separate sources.** Pickens carries five copies of the same roll (`Pickens_Open_data/6`, `MunisMap/4`, `ArcReaderData/2`, `Energov_AGOL/7`, `Pickens_Open_data_webmap_WFL1/6`). Gaston's own entry admits `NeighborhoodParcels/11` is field-for-field identical to `Parcels/11`. Mitchell's `WebMap/18` and `WebMap2020/18` are identical. Defensible as failover/diff spines, but they are not five discoveries.
3. **Explicit carry-forwards sitting inside net-new tables.** Rutherford's Sturgis Avalon and `lrcpwa`; Pickens `Posting3`, `dqnt_2024`, and the sales index; Polk's `LU_Parcels`, `Public_Lands_Features`, `ParcelNumber`/`TaxParcels`/`Site_Addresses`; Union's WTH dsids 980-988. These are re-verifications of round-1 finds.
4. **Negative and correction rows counted as sources.** Polk's dead `tryon_bulletin.py` URL, Polk's `TOTAL_TAX_OWED` correction, Union's "no delinquent list has ever been posted", Anderson's courts hub, Union's Zuercher robots finding. Valuable intel, but zero rows of data.
5. **Regional hosts that will re-fire.** HCCOG (`services1.arcgis.com/vj28eVZMB2OMIUh5`, found via Mitchell) already carries Avery, Wilkes, Yancey and Ashe parcel rolls. NCEM (`services7.arcgis.com/A1RDxSCO3I0JRCwC`, found via McDowell) is statewide. Both will be re-discovered as "net-new" in the next county unless a shared source registry is kept.
6. **The ArcGIS Hub bulk-CSV download API** is one technique claimed on four tenants (Pickens, Polk, Transylvania, NC OneMap). Four real files, one method.

---

## 2. TOP 12 FROM ROUND 3 (ranked by value ÷ effort)

| # | Source | URL | Effort |
|---|---|---|---|
| 1 | **Laurens SC utility meters, 15,350 accounts at 100% phone fill** (gas 5,926 / electric 3,152 / water 3,850 / sewer 2,422; ACTIVE=I gives 1,498 disconnects) | `https://www.laurenscountygis.org/arcgis/rest/services/Pebble/TaxParcel/MapServer/38/query?where=1%3D1&outFields=ACCTNO,NAME,PHONE,ADDRESS1,CITY,ZIP,ACTIVE,MAXUSG&f=json` | XS |
| 2 | **Anderson SC full-county parcels + owner mailing, 114,516 rows / 113,699 mailing addresses** (8x the city layer round 1 found; fixes the `owner_mailing` breakage) | `https://gis.cityofandersonsc.com/arcgis/rest/services/WaterUtilities/County_Parcels/FeatureServer/0/query?where=1%3D1&outFields=TMS,OWNER,OWNER_ADDR,CITY,ZIPCODE,PHYS_ADDR,SALE_PRICE,MRKT_VALUE,IMPRV&returnGeometry=false&f=json` | S |
| 3 | **McDowell NC pre-computed vacancy flag, 14,300 vacant private parcels with mailing** | `https://services1.arcgis.com/dUkMSguHjSnNcU9J/arcgis/rest/services/Dogwooed_McDowell_Vacant/FeatureServer/0/query?where=Vacant%3D%27Yes%27+AND+Public_%3D%27No%27&outFields=*&f=json` | XS |
| 4 | **Pickens SC whole assessor roll as one CSV, 66,417 parcels / 17.3 MB** (first call returns 202, re-request for 200) | `https://pcgis-pickenscosc.opendata.arcgis.com/api/download/v1/items/558caa53cb1842f298a94983d6a14b9b/csv?layers=6` | XS |
| 5 | **Transylvania NC full CAMA hiding under an ag-district service name, 29,541 rows x 116 fields** including deferred value (833), exemption flags, `MortgageHolder` (4,883) and YoY value drop (6,306) | `https://gis.transylvaniacounty.org/server/rest/services/Voluntary_Ag_District/MapServer/0/query?where=1%3D1&outFields=*&returnGeometry=false&f=json` | S |
| 6 | **Gaston NC free comp spine with grantor + grantee + price, 19,571 sales** | `https://gis.gastoncountync.gov/publicgis/rest/services/DevNet/v_gis_study_ratio_results/MapServer/12/query?where=net_selling_price%3E1000&outFields=parcel_number,site_address,date_of_sale,net_selling_price,grantor,grantee,document_number,ratio&returnGeometry=false&f=json` | S |
| 7 | **Cleveland NC permit + inspection log, 83,367 rows, current to today** (STOP WORK 29, FAILED 104, DEMO 8) | `https://www.clevelandcounty.com/ccbicmts/bicmts_list.php?q=(Comments~contains~STOP%20WORK)` | S |
| 8 | **Pickens SC 6-year delinquency stack, union 1,780 PINs, 66 delinquent three consecutive years, 144 rolled 2024 into the 2025 posting** | `https://services1.arcgis.com/59960rq18IxUcAVI/arcgis/rest/services/dqnt_2024/FeatureServer/0/query?where=1%3D1&outFields=*&returnGeometry=false&f=json` (plus `delinquent_2020`, `del_2021`, `dqnt_2022`, `dqnt_2023`, `Posting3`) | S |
| 9 | **Transylvania NC delinquent bills, solved after round 1 filed it UNVERIFIED. 1,831 true arrears across TY2017-2025** (fix was the trailing slash plus the two-step partial-then-data call) | `POST https://tax.transylvaniacounty.org/TaxBillSearch/GetSearchTablePartial/` then `POST /TaxBillSearch/GetSearchTableData` | M |
| 10 | **Laurens SC rolling probate index, 332 decedents with personal-representative name and mailing address** | `https://www.laurenscountyadvertiser.net/wp-json/wp/v2/posts?categories=7486&per_page=1` | S |
| 11 | **Gastonia NC CityView code enforcement, anonymous, with a hard `AKPAR` parcel join** (round 1 concluded city code enforcement was dead) | `https://devsvcs.gastonianc.gov/CodeEnforcement/LocatorResults?category=CE&searchValue=MAIN&pageNumber=1` | M |
| 12 | **Transylvania NC FEMA Substantial Damage export, 44 owners, all >=50% damaged, all with PIN and mailing address. Layer 306, not 0** | `https://services7.arcgis.com/qkz4LIZAMHN41UKn/arcgis/rest/services/Helene_SD_Structures/FeatureServer/306/query?where=1%3D1&outFields=*&returnGeometry=false&f=json` | XS |

Just missed: Easley SC condemned list (38 structures with PIN), Marion NC blight survey (79 at condition >=4 with owner name and photos), Anderson rollback books (5 years, market-vs-use spread), Laurens ROD Daily Notebook (218 recordings today, disproves `logan.py`), Rutherford retired-911 addresses (1,642 parcel-joinable demolitions).

---

## 3. CONTACT-DATA SWEEP

**Plainly: no. Not one of the 11 publishes owner contact data at Buncombe or Lincoln scale.** Three publish some, and only one uses the same mechanism.

| County | Phones | Emails | Source |
|---|---|---|---|
| **Laurens SC** | **15,350** (100% fill across 4 meter layers) | 0 | LCPW gas/electric/water/sewer meter layers |
| **Anderson SC** | **1,494** | **254** | `City_Businesses` FeatureServer, 1,614 rows, TMS join |
| **Transylvania NC** | **343** (274 storm-debris + 69 needs-collector) | field present, fill **unverified** | Survey123 layers on `services1.arcgis.com/ProOLvsmwpY1RmFG` |
| Pickens, Union, Rutherford, Cleveland, Polk, Gaston, McDowell, Mitchell | 0 | 0 | none found |

Round-3 total: **~17,187 phones, 254 confirmed emails**, against Buncombe 73,965 + Lincoln ~99,000 phones and ~30,000 emails. Round 3 added roughly **10% of the phone supply of two round-1 counties combined**.

Two caveats worth stating: the register tails I was given are truncated, so the 8 zero counties are **unverified for their cut portions**; and Laurens is the only true structural match, because it is the same pattern (a utility billing table published as a GIS layer) rather than a business-license roster or a disaster survey. Anderson's 254 emails are the only email supply in the entire round.

**Operational read:** the Buncombe/Lincoln phone tables are an anomaly, not a template. Fifteen of eighteen counties will need paid skip-trace.

---

## 4. MULTI-YEAR ARREARS (repeat-delinquency scoring)

| County | Verdict | Detail |
|---|---|---|
| **Pickens SC** | **Yes, best in round** | Six discrete year services 2020-2025. Overlaps measured: 2022∩2023=125, 2023∩2024=137, 2022∩2024=281, all-three=66, 2024∩Posting3=144. Union 1,780 distinct PINs. Pre-scored hit list, no join work left. |
| **Transylvania NC** | **Yes** | One endpoint, `TaxYear` parameter 2017-2025. Per-year: 449/306/195/210/80/151/178/205/57 = 1,831 true arrears. Payment cell flags bills already at attorney/foreclosure. |
| **Rutherford NC** | **Yes, deepest** | Sturgis Avalon: 29,319 true-delinquent TY2016-2025 with owner, mailing, situs, parcel, amount, and DELINQUENT / ADVERTISED / OUTSIDE LAW FIRM flags. Tenant re-verified live 2026-08. Zero files in `src/`. |
| Laurens SC | Partial | 2021-2024 overage list exists but is a 4-page image PDF needing OCR. Not a per-year queryable service. |
| Anderson SC | No | No arrears service found. ACPASS is deeds/sales/permits. |
| Union SC | No | WordPress REST (1,053 media items) confirms no delinquent-tax list has ever been posted. |
| Polk NC | No | `TOTAL_TAX_OWED` proven to be the annual levy, not arrears (count=0 outliers at 1.5% and 3%). No arrears source exists. |
| Cleveland, Gaston, McDowell, Mitchell | **Unknown** | Not evidenced in the register excerpts provided; tails truncated. Do not assume no. |

**Three counties confirmed** support repeat-delinquency scoring today. Pickens is the only one where the year-over-year join has actually been executed and counted.

---

## 5. COVERAGE TABLE, ALL 18

Scores are mine, for the 11 counties in this round only. **I was given no round-1 or round-2 scores, so those seven are marked unknown rather than guessed. The identity of the other seven counties is also inferred from project memory, not from the material supplied, and is unverified.**

| County | Score | Biggest remaining gap |
|---|---|---|
| Transylvania NC | 9 | Sales table has no grantor/grantee; every chain-of-title question needs a Logan ROD join on book/page |
| Pickens SC | 9 | Zero owner phone or email, and no probate or estate index of any kind |
| Anderson SC | 8 | No delinquent-tax arrears service; probate API returns 500 to a hand-built GET and needs a real browser session replay |
| Laurens SC | 8 | ROD daily feed cannot be backfilled (no working date param), so it is poll-forward only |
| McDowell NC | 8 | No verified delinquency or arrears service; no contact data |
| Gaston NC | 8 | County-side tax arrears and tax-sale lane not evidenced; DevNet layer IDs are non-obvious and `where=1=1` is unstable |
| Cleveland NC | 7 | Code-enforcement layer is live schema with 4 rows of pilot data; the 20-char mailing truncation is upstream in the CAMA extract and is unfixable by source-switching |
| Rutherford NC | 7 | The county's single deepest source (Avalon, 29,319 arrears) has zero implementation; `rutherford_tax.py` parses a retired format and returns 0 |
| Mitchell NC | 6 | Comp spine is 397 sales from CY2021 only; no delinquency service at all |
| Union SC | 6 | Everything is HTML scrape behind curl_cffi with a 500-row cap; no delinquent-tax list published; jail roster is robots-disallowed |
| Polk NC | 5 | No arrears source exists, sheriff sales are not online, ncnotices county filter throws a server-side 500 |
| Buncombe NC | unknown | unknown (round 1/2 material not supplied) |
| Henderson NC | unknown | unknown |
| Lincoln NC | unknown | unknown |
| Madison NC | unknown | unknown |
| Catawba NC | unknown | unknown |
| Haywood NC | unknown | memory records the NC delinquent-tax gap here as still open, unverified in this round |
| Spartanburg SC | unknown | unknown |

---

## 6. WHAT IS STILL MISSING, AFTER THREE ROUNDS

**1. Contact data.** Fifteen of eighteen counties publish no owner phone and no owner email. Section 3 settles it: Buncombe and Lincoln are outliers. There is no free countywide phone append in this footprint, so skip-trace remains an unpriced, unbudgeted dependency on the whole motivated-seller thesis.

**2. Mortgage balance, therefore true equity.** Transylvania publishes a lender *name* on 4,883 parcels. Nobody publishes a balance. Every loan amount still requires OCR of a scanned deed-of-trust PDF, and the amortized-payoff step that turns a loan amount into equity has not been built anywhere. Three rounds of source hunting have not moved this.

**3. The SC civil court lane.** Evictions, divorce, lis pendens and judgments remain behind the SC Public Index ToS/WAF wall in all five SC counties. Anderson's local Spartan probate index is the only break in that wall, and its backing API still 500s on a hand-built request.

**4. Occupancy truth.** Only McDowell (pre-computed flag), Laurens (utility disconnects) and Marion (survey) have anything real. Everywhere else vacancy is inferred from `BLDGS=0` or `STRUCT='N'`, which is land, not abandonment.

**5. The act-on-it layer, still.** Three rounds have produced sources, not outreach. Nothing in round 3 touches the gap named in `project_path_to_100` and `project_gap_ledger_and_rei_playbook`. The board grows; the ability to contact anyone on it does not.

**6. Build debt now exceeds discovery.** Round 3 found more than the engine can absorb, and it re-confirmed named defects rather than fixing them:
- `src/foreclosure_scraper/scrapers/counties_nc/rutherford_tax.py` parses a retired `***` format and returns 0 against a plain HTML table
- `src/foreclosure_scraper/rod/logan.py` lines 27-30 assert Laurens has no name-less date sweep; `nontemp.php` returns 218 records for today
- `tryon_bulletin.py` has a hard-404 in `SEARCH_URLS` (`/category/legal-notices/`; real slug is `public-notices`)
- `enrichment_arcgis.py:99` still carries the Cleveland situs TODO
- `sc_assessor_cama.py:20` says Laurens is cadastral-only; the consultant-hosted copy carries 16,937 market values and 26,574 sale considerations
- `jail_bookings.py` Cherokee SC and Anderson SC are robots-disallowed and, if the fail-closed check runs, are silently yielding zero
- `d1ebsyxxbc7tep` (Rutherford Avalon) appears in zero files in `src/`

**7. An OCR queue nobody has run.** Laurens overage list (4 pages, image-only), Rutherford's 12 monthly permit PDFs (scanned), Anderson's five rollback books (209 pages each), Laurens deed images (deterministic base64 keys, verified working). All identified, none processed.

**8. No shared source registry.** NC OneMap was independently "discovered" three times in one round. Regional hosts (HCCOG, Land of Sky, NCEM) will re-fire on the next county. Without a registry the net-new count inflates and the same code gets written twice.

**9. Verification is uneven.** Many round-3 rows are live counts. Several are structural discoveries where the harvest was never run: the Anderson probate API (500 on GET), the Beacon spatial bulk export, the Union A-Z alphabet sweep, the Anderson 144-instrument-type ROD crawl, the Union ~18k `getftr` keyspace walk. Those should be treated as **capability proven, data not yet in hand**.