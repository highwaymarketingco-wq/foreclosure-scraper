## UNDERWRITING DATA — free-source enumeration, 18 NC/SC counties

**Scope confirmed from `src/foreclosure_scraper/config.py`:** SC(7) Spartanburg, Anderson, Pickens, Oconee, Cherokee, Union, Laurens · NC(11) Rutherford, Cleveland, Henderson, Polk, Gaston, Buncombe, Transylvania, McDowell, Lincoln, Mitchell, Burke.

Every URL below was requested this session unless tagged UNVERIFIED. Access classes: **OPEN** = anonymous GET/JSON · **OPEN-COOKIE** = 202-gates a cold request, 200 after a session cookie · **TOKEN** = free registration required · **RESTRICTED** = eligibility-gated, we do not qualify · **MANUAL/WALL** = no programmatic path.

---

## PRIVACY REPORT — required first

I did **not** query `arcgisserver.lincolncountync.gov/.../Server_Tables/MapServer/10`. Separately, while enumerating Lincoln County I found the sales/CAMA export layer `MainSalesImprovmentLand/MapServer/0` on the same public server. It is clean (no SSN/DOB fields) and is listed below on its own merits. **Standing exposure to report to Lincoln County GIS:** `Server_Tables/MapServer/10` publishes `TCSSN1`/`TCSSN2` to anonymous callers on the same host that serves their public tax-parcel viewer. That is a live PII leak, not a data source. Nothing in this report reads it, and no enrichment design should touch it.

---

## 1. ARV / COMPS

### 1a. Dedicated county Sales FeatureServers (the thing you asked me to enumerate)

Three exist in-footprint. Two are net-new to the engine.

| County | URL | Yields | Access | Engine |
|---|---|---|---|---|
| **NC Cleveland** | `https://gis.clevelandcounty.com/arcgis/rest/services/Tax/Vacant_ImprovedLot_Sales/MapServer/1` (Improved) and `/0` (Vacant) | **6,481 improved + 2,765 vacant** sales, tax years 2023–2026. Fields: `Parcel_Number, Deed_Book, Deed_Page, DateSold_YYYYMMDD, Deed_Stamp_Amount, Sales_Amount, Sum_LND_Acres/Acres, Tax_Year`. Polygon geometry → spatial radius query works. Verified row: stamp 280.0 ↔ price 140,000 (exact $2/$1,000) | OPEN | **NEW.** Cleveland has no `RECORDED_COMP_CONFIG` entry at all |
| **SC Anderson** | `https://propertyviewer.andersoncountysc.org/arcgis/rest/services/Parcel_Sales/MapServer/0` | **40,427 rows**, `SALEYEAR` distinct = 2022,2023,2024,2025,2026,2027 (rolling, live). Fields: `TMS, SALEDATE (epoch-ms), SAPRIC, SADEBK, SADEPG, SATYPE (Vacant\|Improved), SALOCA, SAACRE` | OPEN | **NEW.** Anderson has no `COUNTY_GIS` entry and no comp config; it currently falls through to the token-walled SCDOT layer |
| **NC Lincoln** | `https://arcgisserver.lincolncountync.gov/arcgis/rest/services/MainSalesImprovmentLand/MapServer/0` | Full CAMA+sales export. `AMDTSL` (sale date, YYYYMMDD int), `AMSLAM` (sale amount), **`AMQFCD` (sale-qualification code)**, **`AHFNAR` (heated floor area)**, `AHBTH_` (baths), `NEIGHBORHOOD`, `VACANT`, `ZONING`, `IMPROVALUE/LANDVALUE/TOTALVALUE`, `DEEDBK/PG/YR` | OPEN | **UPGRADE.** Engine's Lincoln config reads `Server_TaxParcelViewerSP/0` with `date_kind:"year"` on `DEEDYR` — year granularity and no qualification filter. This layer gives day-level dates and a qual code |

I probed the ArcGIS service root of every other county host in footprint (Buncombe, Henderson, Rutherford, Gaston, Transylvania, Mitchell, Burke/Morganton, Pickens, Oconee, Laurens, Union, Spartanburg). **No other dedicated Sales service exists.** Don't go looking again.

### 1b. Sales embedded in the parcel/CAMA layer (price + date on the main layer)

| County | URL | Price/date fields | Engine |
|---|---|---|---|
| NC Buncombe | `https://gis.buncombecounty.org/arcgis/rest/services/property_bc_dis/MapServer/1` | **`Stamps` (77,058 parcels >0)**, `SalePrice`, `DeedDate` (YYYYMMDD string), **`Reason`** (18 sale-qualification codes: A,O,T,N,W,E,X,D,F,P,L,U,Q,R,C,B,V), `NeighborhoodCode`, `Class`, `Improved`, `TotalMarketValue`. Verified: Stamps 670 ↔ SalePrice 335,000 | Used for owner/mailing only. **Sales + Reason + NeighborhoodCode unexploited.** No comp config |
| SC Spartanburg | `https://maps.spartanburgcounty.org/server/rest/services/GIS/CAMA_Parcels/FeatureServer/0` (181,369) | `SaleDate, SaleAmount, DeedBook, DeedPage, InstrumentNumber` | Comp config exists but `sqft:None` → **inactive** |
| SC Spartanburg (CAMA-joined subset) | `https://services9.arcgis.com/HoRra3ATPLGmyjn6/arcgis/rest/services/Parcel_and_CAMA_Feb_1_2021/FeatureServer/0` (29,402; 16,976 with SaleAmount>1000) | Same + full building spec | Used for owner/mailing |
| SC Pickens | `https://services1.arcgis.com/59960rq18IxUcAVI/arcgis/rest/services/Pickens_Open_data/FeatureServer/6` | `SALEDT, SALEP, IMPVAC, SubDivisio` | Comp config `sqft:None` → inactive |
| SC Laurens | `https://laurenscountygis.org/arcgis/rest/services/Pebble/TaxParcel/MapServer/5` | `Sale_Price, Sale_Date, Deed_Book/Page, Neighborhood` | Comp config `sqft:None` → inactive |
| NC (all 11, statewide fallback) | `https://services.nconemap.gov/secure/rest/services/NC1Map_Parcels/FeatureServer/1` | `saledate`, `saledatetx`, `improvval`, `landval`, `parval`, `structyear`, `struct`, `multistruc` — **NO sale price field** | Used for Cleveland owner lookup |

**Blunt:** NC OneMap is the only statewide NC parcel layer and it carries sale *date* but not sale *price*. For Polk, Mitchell, McDowell, Burke, Gaston, Transylvania, Henderson, Rutherford the only free price is the county's own layer or the deed stamp. There is no shortcut.

### 1c. Deed stamps → price (the NC lever)

- **NC G.S. 105-228.30** — verified at `https://www.ncleg.gov/EnactedLegislation/Statutes/PDF/BySection/Chapter_105/GS_105-228.30.pdf`. $1.00 per $500 of consideration. **price = stamps × 500.** Confirmed empirically twice (Buncombe 670→335,000; Cleveland 280→140,000). Engine already has `src/foreclosure_scraper/rod/deed_stamp.py` implementing exactly this — it is written for trustee's-deed text blobs and is **not** wired to the two GIS layers that publish `Stamps`/`Deed_Stamp_Amount` as a structured numeric field.
- **SC 12-24-70** — verified via Justia (`https://law.justia.com/codes/south-carolina/title-12/chapter-24/section-12-24-70/`). For exempt deeds "the value is not required to be stated on the affidavit," only the exemption reason. **This is why SC recorded-index $/sqft cannot be built from the ROD index.** It is not a scraper bug and no amount of engineering fixes it. SC price has to come from the assessor's own sale table (Anderson `Parcel_Sales`, Pickens `SALEP`, Laurens `Sale_Price`, Spartanburg `SaleAmount`) or the qPublic card.

### 1d. Assessor sale tables / cards
- **SC Cherokee** — county GIS page (`https://cherokeecountysc.gov/gis-mapping/gis-parcel-map/`) routes to `https://qpublic.schneidercorp.com/Application.aspx?App=CherokeeCountySC&Layer=Parcels&PageType=Search` (URL as published on the county page; not independently fetched — **UNVERIFIED**). Engine already drives `qpublic.schneidercorp.com` in `enrichment_assessor_card.py`.
- **SC Oconee** — `https://arcserver2.oconeesc.com/arcgis/rest/services/CitizenServe/MapServer/4` (`GISDATA.dbo.assessordata`, 68,145 rows) carries only `pin, current_owner, owner_street/citystate/zip, fire_district, deed_book, deed_page, legal_descr, proval_acres`. **No price, no sqft, no condition.** Oconee is qPublic-card-only for value.
- **SC Spartanburg bulk roll** — `https://www.arcgis.com/sharing/rest/content/items/1f190ebd48c1402a918c3bc315431a1b/data` (weekly Assessor_Extract CSV, ~123 MB; documented in `docs/enumeration/enum_Spartanburg.md`). This is the **only** free source of Spartanburg living-area sqft — see §2.

### 1e. Time-adjustment index (stale-comp correction)

| Source | URL | Gives | Access | Engine |
|---|---|---|---|---|
| FHFA annual **county** HPI | `https://www.fhfa.gov/hpi/download/annual/hpi_at_county.xlsx` | 5.33 MB. Columns State / County / **FIPS code** / Year / Annual Change % / three base-indexed values. Verified present: Buncombe, Spartanburg, Mitchell | OPEN | **NEW** |
| FHFA annual **ZIP5** HPI | `https://www.fhfa.gov/hpi/download/annual/hpi_at_zip5.xlsx` | 39.75 MB | OPEN | **NEW** |
| FHFA annual **tract** HPI | `https://www.fhfa.gov/hpi/download/annual/hpi_at_tract.csv` | 89.89 MB | OPEN | **NEW** |
| FHFA quarterly metro/state | `.../quarterly_datasets/hpi_at_metro.csv`, `hpi_at_state.csv` | 4.17 MB / 187 KB | OPEN | **HAVE** (`enrichment_fhfa_value.py`) |

The engine time-adjusts rural WNC comps with a **state** index. County/ZIP5 exist, are free, and are one download away. Note the county file is explicitly labelled "developmental" and reports `.` where the Fannie/Freddie sample is thin — expect gaps in Mitchell/Polk.

### 1f. MLS-free listing comps
`HomeHarvest` → Realtor.com public JSON, already wired (`enrichment_comps.py`, `scrapers/national/homeharvest*.py`). **Blunt:** this is list-side-heavy, ToS-gray, and thin in Mitchell/Polk/McDowell. It should stay Tier-2 behind recorded sales, which is how `valuation/calc.py` already ranks it.

---

## 2. CONDITION

| Input | URL | Yields | Access | Engine |
|---|---|---|---|---|
| **SC Spartanburg CDU + condition factor** | `https://maps.spartanburgcounty.org/server/rest/services/GIS/CAMA_Parcels/FeatureServer/0` | 181,369 parcels. `CDUC` ∈ {DELAPITATED, POOR, FAIR, FAIR-AVG, AVERAGE, AVG-GOOD, GOOD, GOOD-VG, EXCELLENT}; **4,232 rows POOR or DELAPITATED**. Plus `ConditionFactor` (coded: PR/FA/AV/GD/EX/DL/AG/GV/FR), `BuildingGrade`, `YearBuilt`, `Foundation`, `Frame`, `RoofStructure`, `RoofCover`, `HeatType/HeatFuel`, `Basement`, `Garage`, `Attic`, `RoadType`, `Topo` | OPEN | Layer is hit by `spartanburg_condemned.py` only. **Condition/spec fields unexploited** |
| Same fields, CAMA-joined subset | `https://services9.arcgis.com/HoRra3ATPLGmyjn6/arcgis/rest/services/Parcel_and_CAMA_Feb_1_2021/FeatureServer/0` | 29,402 rows; 28,269 with non-blank CDUC | OPEN | owner/mailing only |
| **Buncombe Helene damage** | `https://gis.buncombecounty.org/arcgis/rest/services/Accela/MapServer/7` | **10,723 parcels**, keyed by `pin`. `DamageType` ∈ {MINOR DAMAGE/AFFECTED, LANDSLIDE, INUNDATED, MAJOR DAMAGE, **DESTROYED**} | OPEN | **NEW.** `enrichment_helene_damage.py` uses three other AGOL orgs, not this one |
| **Asheville damage assessment Ph.II** | `https://services.arcgis.com/aJ16ENn1AaqdFlqx/arcgis/rest/services/Helene_Property_Damage_Assessment_Phase_II_Public_View/FeatureServer/0` | 1,616 inspections: `building_damage`, **`current_posting` / `previous_posting`** (red/yellow tag), `building_type`, `building_primary_occupancy`, `building_number_res_units`, `inspect_date` | OPEN | **NEW** |
| **Asheville permit history (full)** | `https://gis.ashevillenc.gov/server/rest/services/Permits/AccelaPermitsView/MapServer/**2**` | **65,453 permits.** `record_type_type` ∈ {Residential, Commercial, Over The Counter, Fire, Stormwater, Sign, Right of Way, …}, plus `record_type_subtype`, `description`, `job_value`, `date_opened/closed/completed`, `status`, **`parcel_number`/`apn`** (direct parcel join), `license_number`, `business_name` | OPEN | **NEW.** Engine reads only `AccelaServicesView/MapServer/0` (2,738 **code cases**) in `enrichment_code_enforcement.py`. Layer id is 2, not 0 — 0/1 return "Invalid or missing input parameters" |
| **Asheville Helene trade permits** | `https://services.arcgis.com/aJ16ENn1AaqdFlqx/arcgis/rest/services/Helene_Building_Trade_Permits/FeatureServer/0` | 1,153 rows: `permit_type`, `permit_subtype`, `permit_category`, `job_value`, `building_value`, `total_project_valuation`, **`total_sq_feet`**, `fees`, `site_address`, **`pinnum`** | OPEN | **NEW** |
| Tyler EnerGov Citizen Self Service | `https://rutherfordcountync-energovweb.tylerhost.net/apps/selfservice` (200) · `https://spartanburgcountysc-energovweb.tylerhost.net/apps/selfservice` (200) | Permit + code-case search UI | OPEN-HTML, **yield UNVERIFIED** (search is a POST to an undocumented schema) | **NEW** |
| Spartanburg permit fields on CAMA | `PermitType/PermitDate/PermitValue/PermitNumber` on the CAMA layer above | **Dead in practice** — `PermitValue > 0` returns **0 rows** countywide; `PermitDate` is default-filled (`-2208988800000` = 1900-01-01) | OPEN but empty | do-not-build |
| Street View / assessor photos | — | — | — | **HAVE** (`enrichment_streetview.py`, `enrichment_assessor_photo.py`, `enrichment_lrcpwa_photo.py`, `docs/parcel_photos/` ~2,072 files) |

**Engine bug found:** `enrichment_building_permits.py` line 35 hardcodes `https://services.arcgis.com/ZTvQ9NuewyLypkyr/arcgis/rest/services/Building_Permits/FeatureServer/0/query`. That AGOL org is **dead** — the org root itself returns `{"error":{"code":400,"message":"Invalid URL"}}`. It was Charlotte/Mecklenburg (out of footprint anyway), so the permit enricher currently has **zero live endpoints**.

**Blunt on permits:** I swept `{county}-energovweb.tylerhost.net` across all 18 counties. Only **2 of 18** answer. Of the other 16, **Mitchell, Polk, McDowell, Burke, Transylvania, Union, Cherokee, Oconee, Laurens have no free permit feed of any kind.** Pickens publishes `Energov_History_AGOL`/`Energov_AGOL` services (org `services1.arcgis.com/59960rq18IxUcAVI`) — the `Energov_AGOL/FeatureServer/0` layer I probed is an address-point layer, not permits; the `_History_` service is **UNVERIFIED**. Roof/HVAC/electrical permit history at parcel level is a **city-of-Asheville-only** capability in this footprint. Everywhere else, CDU code + year built + Street View is all you get.

---

## 3. OCCUPANCY

| Input | URL | Yields | Access | Engine |
|---|---|---|---|---|
| **SC 4% vs 6% assessment ratio — the direct owner-occupancy tell** | `https://maps.spartanburgcounty.org/server/rest/services/GIS/CAMA_Parcels/FeatureServer/0` field `AssessmentCode` | 55 distinct codes. **`LIKE '4% OO%'` = 100,594 parcels** (legal residence / owner-occupied). **`LIKE '6% RES%'` = 54,382** (non-owner-occupied residential). Also `6% MOBILE HM`, `4% OO MH`, `4 AG …` (agricultural), `0 EX …` (exempt), `DOR …`, `FILOT` | OPEN | **NEW — highest-value unexploited field in the footprint** |
| Same, CAMA subset | `.../Parcel_and_CAMA_Feb_1_2021/FeatureServer/0` field `Assessment` | 29,350 of 29,402 non-blank; same taxonomy | OPEN | **NEW** |
| Other 6 SC counties' ratio | Pickens `/FeatureServer/6`, Oconee `PARCELDATA_owner_Assr/MapServer/1` + `CitizenServe/MapServer/4`, Laurens `Pebble/TaxParcel/MapServer/5`, Union `UNION_SC_PARCELS_WFL1/FeatureServer/2` — **all four field lists dumped, none carries an assessment-ratio or legal-residence field** | — | — | **Wall.** Anderson/Cherokee: ratio not in GIS; would have to come off the qPublic/assessor card per parcel |
| NC elderly/disabled + present-use exclusion | `https://gisweb.hendersoncountync.gov/arcgis/rest/services/Parcels/MapServer/0`; `https://services6.arcgis.com/VLA0ImJ33zhtGEaP/arcgis/rest/services/Property_2025/FeatureServer/0` | Exemption flags | OPEN | **HAVE** (`enrichment_tax_relief.py`) — but only 2 of 11 NC counties |
| Spartanburg `HomesteadNumber` | same CAMA layer | **Do not use.** Prior enumeration measured only 32 populated rows out of 181,369 | OPEN but empty | do-not-build |
| Mailing-vs-situs mismatch | `COUNTY_GIS` registry in `enrichment_owner_mailing.py` | out-of-state / off-parcel mailing address | OPEN | **HAVE** |
| **HUD USPS Vacancy** | `https://www.huduser.gov/portal/datasets/usps.html` → `https://www.huduser.gov/apps/public/usps/register` | Quarterly **aggregate** vacant/no-stat counts by census geography | **RESTRICTED** | Engine has `enrichment_usps_vacancy.py` pointed at it |

**Blunt on USPS vacancy — two independent killers, quoted from the page I fetched:** (1) *"HUD can make the data accessible only to governmental entities and non-profit organizations registered as users."* A for-profit REI operation does not qualify; the sublicense also restricts use to a declared "stated purpose." (2) Even if you qualified, the data is *"aggregate vacancy and no-stat counts"* by tract/ZIP — **it can never tell you a specific house is vacant.** `enrichment_usps_vacancy.py` is aimed at a source that is both ineligible and structurally incapable of the job. **There is no free per-address vacancy signal in the United States.** Your real free proxies are: mailing≠situs, SC 6% ratio, utility-disconnect (not public in either state), Street View, and CDU=POOR/DELAPITATED. Paid floor for address-level vacancy/occupancy: PropStream-class subscription (see `docs/path_to_100.md`, which already priced the hybrid stack at ~$300–500/mo).

**Rental registration:** none of the 18 counties operates one. Asheville's `STVRHomestayPermits` service exists in the city AGOL org (short-term-rental permits only, name observed in the 412-service listing, **schema UNVERIFIED**).

---

## 4. EQUITY INPUTS

The engine is **strongest here** — do not rebuild.

| Input | Where | Status |
|---|---|---|
| Recorded DOT original principal + date → amortized payoff | `src/foreclosure_scraper/valuation/amortize.py` — amortizes original principal from the recording date using the Freddie Mac PMMS annual-average 30-yr rate table | **HAVE** |
| Deed stamp → consideration | `src/foreclosure_scraper/rod/deed_stamp.py` | **HAVE** (text-blob path; not wired to the structured `Stamps` fields — see §1c) |
| ROD document retrieval (deeds, DOTs, assignments, satisfactions, judgments, tax liens) | `src/foreclosure_scraper/rod/{acclaim,aumentum,cchs,cott,cott_recordroom,kofile,logan}.py` + `enrichment_lien_stack.py`, `enrichment_relationship_deeds.py`, `enrichment_judgment_amount.py`, `enrichment_dew_liens.py` | **HAVE** |
| OCR of scanned DOT PDFs for loan amount | `enrichment_doc_ocr.py`, `enrichment_dot_ocr.py` | **HAVE** |
| **Lien-priority engine** | `src/foreclosure_scraper/rod/priority.py` — computes foreclosing-lien position, senior (survives) vs junior (wiped), with per-state `SUPER_PRIORITY` table | **HAVE, with one substantive error** |

### Lien-priority rules — verified against statute

- **NC property tax: super-priority.** G.S. 105-356(a)(1), fetched from `https://www.ncleg.gov/EnactedLegislation/Statutes/HTML/BySection/Chapter_105/GS_105-356.html`: the tax lien is *"superior to all other liens, assessments, charges, rights, and claims of any and every kind … regardless of the claimant and regardless of whether acquired prior or subsequent to the attachment of the lien for taxes,"* and (a)(3) is unaffected by transfer of title, death, receivership, or bankruptcy. **Engine's `NC.tax_lien: True` is correct.**
- **SC property tax: super-priority.** SC Code Title 12 Chapter 49 — `https://www.scstatehouse.gov/code/t12c049.php`. **Engine's `SC.tax_lien: True` is correct.**
- **NC mechanics lien: RELATION-BACK — engine is wrong.** G.S. 44A-10, fetched from `https://www.ncleg.gov/EnactedLegislation/Statutes/HTML/BySection/Chapter_44A/GS_44A-10.html`: *"A claim of lien on real property … shall relate to and take effect from the time of the first furnishing of labor or materials at the site of the improvement."* A mechanics lien **recorded after** a deed of trust still **primes** it if first-furnishing predates the DOT. `priority.py` sets `NC: {"mechanics_lien": False}` with the comment "priority from work-start, not recording" — the comment states the rule correctly and the flag then discards it. On a Buncombe/Asheville rehab-in-progress foreclosure this under-states senior debt and over-states equity. **Fix: treat an NC mechanics lien as senior when first-furnishing (or, as a proxy, the earliest related permit `date_opened` from the Asheville permits layer) predates the foreclosing DOT.**
- **SC mechanics lien: junior — engine is right.** SC Code 29-5-20, fetched from `https://www.scstatehouse.gov/code/t29c005.php`: the lien attaches *"subject to existing liens of which he has actual or constructive notice."* A recorded prior mortgage is constructive notice. `SC.mechanics_lien: False` is correct.
- **NC HOA limited super-priority** (G.S. 47F-3-116) — engine sets `NC.hoa_lien: True`. Statute text **UNVERIFIED this session**; I did not fetch Chapter 47F. Worth a confirming read before relying on it, since NC's HOA priority is narrower than the flat `True` implies.
- NC power-of-sale foreclosure procedure: `https://www.ncleg.gov/EnactedLegislation/Statutes/HTML/ByArticle/Chapter_45/Article_2A.html` (live, 98 KB) — the upset-bid mechanics the engine already models in `enrichment_upset_bid.py`.

**Blunt:** the one equity input with **no** free structured source anywhere in the footprint is the **current** payoff balance. No county, state, or federal free source publishes it. Amortizing the recorded original principal is the ceiling of what free data can do, and that is already built. Anything better requires a title search or a paid title-data subscription.

---

## 5. COST-TO-CURE

| Input | URL | Yields | Access | Engine |
|---|---|---|---|---|
| **Septic vs sewer / well vs public water** | `https://maps.spartanburgcounty.org/server/rest/services/GIS/CAMA_Parcels/FeatureServer/0` fields `Utility1/2/3` | Domain ∈ {ALL PUBLIC, PUBLIC SEWER, PUBLIC WATER, SEPTIC, WELL, GAS}. **63,704 Spartanburg parcels on SEPTIC** | OPEN | **NEW** |
| Same, other 17 counties | — | **Wall.** No other county in footprint publishes a utility field on its parcel layer (all 17 field lists dumped) | — | — |
| **Floodplain — FEMA NFHL REST** | `https://hazards.fema.gov/arcgis/rest/services/public/NFHL/MapServer` | Live (9.5 KB service doc). Per-point flood-zone query | OPEN | **HAVE** (`enrichment_flood.py`, `enrichment_flood_zone.py`) |
| **Floodplain — NFHL bulk** | `https://hazards.fema.gov/nfhlv2/output/State/NFHL_37_20260101.zip` | **185.1 MB** statewide NC geodatabase (swap `37`→`45` for SC) | OPEN | **NEW** (bulk path; removes per-parcel API round-trips) |
| Local flood layers | Pickens `bfe_wgs84`, `bldgs_fld`, `pickens_county_sc_flood_layer`; Oconee `S_Fld_Haz_Ar`; Morganton `Planning/Morganton_Area_Flood_Zones_Map` | county-refined SFHA | OPEN | redundant with NFHL |
| **Soils / slope** | `https://sdmdataaccess.sc.egov.usda.gov/Tabular/post.rest` (USDA Soil Data Access; GET→400 = live POST-only route) — SSURGO septic-suitability + slope class | OPEN (POST) | **NEW** |
| Local soils | `https://arcserver2.oconeesc.com/arcgis/rest/services/SOILS/MapServer/0` | Oconee soils polygons | OPEN | **NEW** |
| Slope | Buncombe `PERCENTSLOPE`, `DEM`; Henderson `Percent_Slope`, `Digital_Elevation_Model_2017_LIDAR`, `LIDAR_Elevation_2025_Multidirectional_Hillshade`; Lincoln `Server_Elevation`; Transylvania `Contour_Lines`. Buncombe also publishes `Protected Ridges` (`permits/MapServer/35`) — a hard buildability constraint in WNC | OPEN | **NEW** |
| Onsite/well inspection districts | `https://gis.buncombecounty.org/arcgis/rest/services/permits/MapServer` layers 37 (`WellInspectionDistrict`), 38 (`OnsiteInspectionDistrict`) | routing geography only — **not** per-parcel septic permits | OPEN | low value |
| **NC general contractor licensing** | `https://portal.nclbgc.org/Public/Search` (200, 18.3 KB) | License #, status, classification, monetary limit. NC requires a GC license at **$30,000+** project value | OPEN-HTML | **NEW** |
| NC electrical contractors | `https://www.ncbeec.org/` (200) | NCBEEC licensee lookup | OPEN-HTML | **NEW** |
| **SC contractor licensing (LLR)** | `https://llr.sc.gov/` (200). Residential Builders board: `https://www.llr.sc.gov/POL/ResidentialBuilders/` (200) | board rosters | OPEN-HTML | **NEW** |
| SC LLR license verification app | `https://verify.llronline.com/LicLookup/` | **WALL** — 302 → `?AspxAutoDetectCookieSupport=1` → **403** to non-browser clients; ASP.NET cookie/UA gate | classify as browser-only | — |
| Contractor names already in your data | Asheville permits layer `license_number` + `business_name` (65,453 rows) | who actually pulls permits in Buncombe, and at what `job_value` — a **real** local cost-per-job calibration set | OPEN | **NEW** |

**Blunt on permit fee schedules:** these are PDFs on 18 separate county/municipal websites, revised annually, with no machine-readable form anywhere. There is no free API and building 18 PDF parsers for a line item that is 1–3% of a rehab budget is not worth it. **Use the Asheville permit `job_value` + `total_sq_feet` distribution as your rehab $/sqft prior and treat fees as a flat percentage.** That is the only defensible free move.

---

## 6. EXIT

| Input | URL | Yields | Access | Engine |
|---|---|---|---|---|
| **HUD FY2026 FMR (county / FMR-area)** | `https://www.huduser.gov/portal/datasets/fmr/fmr2026/FY26_FMRs.xlsx` | 376,572 B xlsx, 0–4BR by FMR area | **OPEN-COOKIE** — cold GET returns 202/0 bytes; 200 after fetching `https://www.huduser.gov/portal/datasets/fmr.html` into a cookie jar with a browser UA + referer | **NEW** |
| **HUD FY2026 Small Area FMR (by ZIP)** | `https://www.huduser.gov/portal/datasets/fmr/fmr2026/fy2026_safmrs_revised.xlsx` | 4,382,259 B xlsx, ZIP-level | OPEN-COOKIE | **NEW** |
| HUD FMR API | `https://www.huduser.gov/hudapi/public/fmr/statedata/NC` | Returns `{"error":"Unauthenticated"}` HTTP **401** | **TOKEN** (free registration) | — |
| Section 8 payment standards | — | Set by each PHA, published as PDFs, **not** aggregated anywhere free | MANUAL | — |
| RentCast | `https://api.rentcast.io/v1` | Free tier **50 requests/month**, no card; rent estimate + 5 nearby rental comps. Paid floor **$74/mo** (1,000 req) → $199 → $449 | TOKEN (free tier) | **HAVE** (`valuation/rentcast.py`) |
| Rent comps via Realtor.com | HomeHarvest rent pool | list-side rents | OPEN-ish | **HAVE** (`enrichment_comps.py`, `enrichment_rent_comps_extra.py`) |
| **Buyer activity / cash-buyer concentration by grantee frequency** | Your own ROD modules: `rod/{acclaim,aumentum,cchs,cott,cott_recordroom,kofile,logan}.py`; `enrichment_buyer_match.py`, `enrichment_competition.py`; curated registry in `docs/land_buyers.json` (149 KB) | repeat-grantee counts → who is actually buying, at what price, how often | OPEN | **HAVE** |
| Foreclosure-sale outcome pool | `docs/foreclosure_sold_pool.json` (157 KB), `enrichment_foreclosure_sold_comps.py` | realized hammer prices | — | **HAVE** |

**Blunt on rent:** HUD FMR is a **program payment ceiling for an entire FMR area**, not a rent comp. In Buncombe it is one number for Asheville MSA; in Mitchell/Polk it is one number for a non-metro county. Using it as an ARV-rent input will systematically misprice anything that is not median. The only free property-level rent signal is RentCast's 50/month and Realtor.com rental listings. **At 30,003 board leads, 50 requests/month is a rounding error.** If rental exit matters, the honest floor is RentCast at **$74/mo**; there is no free substitute.

---

## WHERE THE FREE ANSWER DOES NOT EXIST

1. **Current mortgage payoff.** Nowhere, free, in either state. Ceiling = amortized original principal (built).
2. **Per-address vacancy/occupancy.** HUD USPS is gov/nonprofit-only *and* aggregate-only. SC's 4%/6% ratio is the best free tell and only exists in Spartanburg's GIS. Paid floor: PropStream-class.
3. **Interior condition.** Assessor CDU is the only proxy, exists in **1 of 18** counties (Spartanburg), is a mass-appraisal grade, and can be a decade stale.
4. **Permit history.** City of Asheville only. 16 of 18 counties have nothing.
5. **SC recorded sale price from the deed index.** Statutorily impossible for exempt deeds (12-24-70). Assessor tables only.
6. **NC sale price statewide.** OneMap has date, not price. Per-county layer or deed stamps only.
7. **Septic/well per parcel.** Spartanburg only.
8. **Rent comps at property level.** RentCast 50/mo free, $74/mo floor.
9. **Section 8 payment standards.** Per-PHA PDFs, not aggregated.
10. **Permit fee schedules.** 18 PDFs, no API, not worth building.

## RANKED BUILD QUEUE (all free, all verified)

1. **SC Anderson `Parcel_Sales`** (40,427 rows, 2022–2027) — new county unlocked for comps, and Anderson currently has no parcel layer at all since SCDOT token-walled.
2. **Spartanburg `AssessmentCode`** — 100,594 vs 54,382 owner-occupancy split across 181,369 parcels, from a layer you already call.
3. **NC Cleveland `Vacant_ImprovedLot_Sales`** — 9,246 stamped sales, new county unlocked.
4. **Asheville `AccelaPermitsView/MapServer/2`** (layer id 2, not 0) — 65,453 permits with parcel join; fixes the dead `ZTvQ9NuewyLypkyr` endpoint at the same time.
5. **Buncombe `Stamps`** → price on 77,058 parcels + `Reason` codes for arms-length filtering; unlocks the largest county in footprint.
6. **NC mechanics-lien relation-back fix** in `rod/priority.py` — correctness, not coverage.
7. **Lincoln `MainSalesImprovmentLand`** — swaps year-granularity `DEEDYR` for real dates + `AHFNAR` heated sqft + `AMQFCD` qualification.
8. **FHFA county/ZIP5 HPI** — replaces the state index in `enrichment_fhfa_value.py`.
9. **Spartanburg `CDUC` + `Utility1`** — 4,232 POOR/DELAPITATED, 63,704 septic.
10. **Buncombe Helene `Accela/MapServer/7`** — 10,723 damage-graded parcels including DESTROYED.
11. HUD FY26 FMR/SAFMR xlsx (cookie-jar fetch pattern required).

**Sources:** [SC 12-24-70](https://law.justia.com/codes/south-carolina/title-12/chapter-24/section-12-24-70/) · [NC G.S. 105-228.30](https://www.ncleg.gov/EnactedLegislation/Statutes/PDF/BySection/Chapter_105/GS_105-228.30.pdf) · [NC G.S. 105-356](https://www.ncleg.gov/EnactedLegislation/Statutes/HTML/BySection/Chapter_105/GS_105-356.html) · [NC G.S. 44A-10](https://www.ncleg.gov/EnactedLegislation/Statutes/HTML/BySection/Chapter_44A/GS_44A-10.html) · [SC Code 29-5-20](https://www.scstatehouse.gov/code/t29c005.php) · [SC Title 12 Ch.49](https://www.scstatehouse.gov/code/t12c049.php) · [FHFA HPI datasets](https://www.fhfa.gov/data/hpi/datasets) · [HUD USPS Vacancy](https://www.huduser.gov/portal/datasets/usps.html) · [HUD FMR](https://www.huduser.gov/portal/datasets/fmr.html) · [RentCast billing](https://developers.rentcast.io/reference/billing-and-pricing) · [NCLBGC](https://portal.nclbgc.org/Public/Search) · [SC LLR](https://llr.sc.gov/) · [Cherokee County SC GIS](https://cherokeecountysc.gov/gis-mapping/gis-parcel-map/)