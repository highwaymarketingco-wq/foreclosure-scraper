## VERDICT: the method reproduces. 7 of 11 NC counties run an ArcGIS Enterprise Portal whose item index was never queried, and every county's AGOL org is structurally invisible to the on-prem REST directory. Nothing was written to the repo; no git; no engine run.

### Step 1 — `owningSystemUrl` results (the pointer)

| County | Server probed | `owningSystemUrl` | Portal found? |
|---|---|---|---|
| Buncombe | `gis.buncombecounty.org/arcgis` | `https://gis.buncombenc.gov/arcgis` | **YES** |
| Gaston | `gis.gastoncountync.gov/publicgis` | `https://gis.gastoncountync.gov/portal` | **YES** |
| Gaston (Gastonia city) | `cogserver.gastonianc.gov/serverweb` | `https://cogportal.gastonianc.gov/portalweb` | **YES** |
| Burke | `gis.burkenc.org/arcgis` | `https://gis.burkenc.org/portal` | **YES** |
| Burke (Morganton) | `gis.morgantonnc.gov/server` | `https://gis.morgantonnc.gov/portal` | **YES** |
| Lincoln | `gis.lincolncountync.gov/server` | `https://gis.lincolncountync.gov/portal` | **YES** |
| Transylvania | `gis.transylvaniacounty.org/server` | `https://gis.transylvaniacounty.org/portal` | **YES** |
| Henderson | `gisweb.hendersoncountync.gov/arcgis` | absent (standalone 11.3) | no |
| Cleveland | `gis.clevelandcounty.com/arcgis` | absent (standalone 11.3) | no |
| Rutherford | `gis.rutherfordcountync.gov/server` + `/arcgis` | absent on both | no |
| Mitchell | `mapping.mitchellcountync.gov/arcgis` | absent (standalone 10.9.1) | no |
| McDowell / Polk | no live county ArcGIS Server (`gis.polknc.org` dead) | n/a | no |

**Query form gotcha:** `q=*` returns `total:0` on every one of these portals. `q=owner:*` and `q=title:*` also return 0. The forms that actually work anonymously are `q=type:"Feature Service"` and `q=-type:"Code Attachment"`. Anderson's `owner:<name>` worked only because the owner name was already known.

### Step 2 — Portal item index vs REST folder listing

| County portal | Portal local items | REST services | Services hidden from REST | Portal-only item types (no REST equivalent) |
|---|---|---|---|---|
| Buncombe `gis.buncombenc.gov/arcgis` | **247** | 108 | 6 (`Hosted/Property` VTS, `Hosted/ElectionPrecinct` FS, `Hosted/ElectionPrecinctCache` VTS, `LOCATIONGEOCODESET_Zip`, `Utilities/PrintingTools`) — all return **499 Token Required** | 37 Vector Tile Package, 3 Service Definition, 1 OGCFeatureServer, 1 WMS |
| Gaston `gis.gastoncountync.gov/portal` | **249** | 114 | 0 real (20 were AGOL basemap proxies) | **48 Web Map, 16 Web Experience, 9 Dashboard**, 1 Form, 1 Site App |
| Burke `gis.burkenc.org/portal` | **60** | 47 | **5** — `CitizenReporter` FS+MS, `BurkeMapMetricsService2`, `BurkeMapMetricsServiceTest` | 7 Web Map, 1 Web Experience, 2 Data Store |
| Morganton `gis.morgantonnc.gov/portal` | **142** | 65 | **16** — incl. an entire second server host `gis.morgantonnc.gov/image` | 29 Web Map, 9 Web Experience, 6 WFS, 6 WMS, 2 StoryMap |
| Transylvania `gis.transylvaniacounty.org/portal` | **78** | 37 | **11** — all cross-host (Brevard AGOL org, NC DEQ landslides, NC OneMap, NPS) | 8 Web Map, 6 Web Mapping App, 7 Document Link, 2 StoryMap |
| Lincoln `gis.lincolncountync.gov/portal` | 37 | 94 (2 hosts) | 0 | — |
| Gastonia `cogportal.gastonianc.gov/portalweb` | 57 | 55 | 0 | 1 Web Map, 1 Web Mapping App |

### Step 3 — Hosted AGOL FeatureServer roots (2,879 services, none linked from any page)

| Source | Exact query-ready URL | Yield (counts + fields) | Access | NEW/SCRAPED |
|---|---|---|---|---|
| **Burke tax-sale parcels** | `https://services3.arcgis.com/axQ4OCSpcxALIQsV/arcgis/rest/services/Tax_Sales_FS/FeatureServer/158/query?where=1%3D1&outFields=*&returnGeometry=false&f=json` | **1,669 rows**, 67 flds: REID, PIN, PROPERTY_OWNER, OWNER_MAIL_1-3/CITY/STATE/ZIP, LOCATION_ADDR, PHYADDR_*, TOTAL_LAND/BLDG_VALUE_ASSESSED, TOTAL_PROP_VALUE, DEED_DATE | OPEN | SCRAPED (r1/r2) |
| **Burke vacant-parcel spine** | `https://services1.arcgis.com/HFXT3ZVvUhhNGNnw/arcgis/rest/services/Undeveloped_Burke_Parcels_20Acres/FeatureServer/2/query?where=1%3D1&outFields=*&returnGeometry=false&f=json` | **21,879 vacant Burke parcels** (`Vacant_BurkeCo`): PARCEL_PK, REID, PIN, LOCATION_A, TOWNSHIP, LAND_CLASS, ZONING. Layer 0 = 580 parcels >20ac w/ full owner mailing + DEED_BOOK/PAGE | OPEN | **NEW** |
| **4-county gov-owned property (Burke/Caldwell/Catawba/Alexander)** | `https://services1.arcgis.com/HFXT3ZVvUhhNGNnw/arcgis/rest/services/LocalGovtOwnedProperties/FeatureServer/0/query?where=CNTYNAME%3D%27Burke%27&outFields=*&returnGeometry=false&f=json` | **1,963 rows**: PARNO, ALTPARNO, OWNNAME/2, SITEADD, GISACRES, PARUSECODE/DESC, GOVERNMENT, LANDUSE, FACNAME | OPEN | **NEW** |
| **Gaston full CAMA** | `https://services6.arcgis.com/qnm8JRPoNeQjgcLi/arcgis/rest/services/DevNetCAMA/FeatureServer/0/query?where=1%3D1&outFields=*&returnGeometry=false&resultRecordCount=2000&f=json` | **115,365 parcels**, 86 flds: PIN/oldPIN/AKPAR, WHOLE_ADDR, JAN1_NAME1/2, CURR_NAME1/2, CURR_ADDR1/2/CITY/STATE/ZIP, DEED_BOOK/PAGE, DEEDTYPE, CALCAC, VAD | OPEN | SCRAPED (r3) |
| **Buncombe tax-history stack** | `https://services6.arcgis.com/VLA0ImJ33zhtGEaP/arcgis/rest/services/Real_Estate_Appraisal_Tax_History_2024/FeatureServer/0/query?where=1%3D1&outFields=*&returnGeometry=false&f=json` | **2,890,069 rows**: PIN, TaxYear, Owner1, Acreage, LandValue, BuildingValue, ImprovementValue, ExemptValue, DeferredValue, Exemption | OPEN | SCRAPED (r1/r2) |
| **Buncombe grantor/grantee sales index** | `https://services6.arcgis.com/VLA0ImJ33zhtGEaP/arcgis/rest/services/Real_Estate_Appraisal_Sales_Grantors_2025/FeatureServer/0/query?where=1%3D1&outFields=*&f=json` | **466,531 rows** (transferid, grantor_id) + matching `..._Grantees_2025` | OPEN | SCRAPED (r1/r2) |
| **Buncombe county-owned** | `https://services6.arcgis.com/VLA0ImJ33zhtGEaP/arcgis/rest/services/County_Owned_Over_Half_Acre/FeatureServer/0/query?where=1%3D1&outFields=*&returnGeometry=false&f=json` | **98 parcels**, 58 flds: pin, owner, DeedBook/Page, DeedDate, Stamps, Instrument, **Reason** (values null/""/"P"), Acreage, AccountNumber, full situs + mailing | OPEN | SCRAPED (r2) |
| **Buncombe jail bookings geocoded to address** | `https://services6.arcgis.com/VLA0ImJ33zhtGEaP/arcgis/rest/services/BookingsByAddress/FeatureServer/0/query?where=1%3D1&outFields=*&returnGeometry=false&f=json` | **4,043 rows**: Match_addr, StAddr, City, Postal, X/Y, `USER_Full_` (name), `USER_Stree/city/state/zip`. **No DOB, no SSN** | OPEN | SCRAPED (r1) |
| **Hendersonville vacant/condemned register** | `https://services1.arcgis.com/UTZTmZoX2rsa9yFA/arcgis/rest/services/VACANT_STRUCTURES_7_24_24/FeatureServer/0/query?where=1%3D1&outFields=*&returnGeometry=false&f=json` | **52 rows**: ADDRESS, OCCUPIED, **BOARDED_UP, CONDEMNED, DELINQUENT_TAX, UTILITIES, NOV___CONTACT_LETTER_SENT**, OWNER, MAILING_ADDRESS, PHONE__, EMAIL, NOTES | OPEN | SCRAPED (r2) |
| **Hendersonville citizen blight reports** | `https://services1.arcgis.com/UTZTmZoX2rsa9yFA/arcgis/rest/services/CitizenProblems_blight_99ec8bbe33bb47789ea037362040a7b5/FeatureServer/0/query?where=1%3D1&outFields=*&f=json` | L0 = **1** case, L1 Comments = **6**, L2 Surveys = 0. Flds: probtype, details, locdesc, pocphone, pocemail, status, resolution | OPEN, thin | SCRAPED (r2) |
| **Cleveland minimum-housing code enforcement** | `https://services5.arcgis.com/e0FcENYfYZslNJVM/arcgis/rest/services/CodeEnforcement_MinimalHousing/FeatureServer/0/query?where=1%3D1&outFields=*&returnGeometry=false&f=json` | **4 cases**: CaseStatus, ParcelNum, Address, Inspection_Date, Hearing_Date, Order_NumDays, Order_ExpDate, Reinspection_Date, Resolution, Comments | OPEN, thin — **poll** | SCRAPED (r3) |
| **Mitchell parcel + mail spine** | `https://services1.arcgis.com/vj28eVZMB2OMIUh5/arcgis/rest/services/Mitchell_County_Parcels/FeatureServer/0/query?where=1%3D1&outFields=*&returnGeometry=false&resultRecordCount=2000&f=json` | **4,557 parcels** (vintage 2025-10-07), 72 flds: PARNO, OWNNAME/2, OWNFRST/OWNLAST, MAILADD, MCITY/MSTATE/MZIP, LANDVAL, IMPROVVAL, PARVAL, GISACRES, PARUSECODE, MULTISTRUC | OPEN | SCRAPED (r3) |
| **Lincoln county-owned property** | `https://services8.arcgis.com/TaX0xkzgvxdv4n56/arcgis/rest/services/County_Owned_Property/FeatureServer/1/query?where=1%3D1&outFields=*&returnGeometry=false&f=json` | **169 parcels**: PID, PHYSICALADDR, NAME1_1/NAME2_1, USE_, Class, ZONING_1, DEEDBK_1/DEEDPG_1 | OPEN | SCRAPED (r1/r2) |
| **Lincoln permits** | `https://services8.arcgis.com/TaX0xkzgvxdv4n56/arcgis/rest/services/PermitData_May15th2026/FeatureServer/1/query?where=1%3D1&outFields=*&f=json` | **3,056**: Permit_Number, Permit_Type/Subtype, Issued_Date, Status, Parcel_ID, X/Y | OPEN | SCRAPED (r2) |
| **Gaston residential building permits** | `https://services6.arcgis.com/qnm8JRPoNeQjgcLi/arcgis/rest/services/BuildingPermits_2026/FeatureServer/0/query?where=1%3D1&outFields=*&returnGeometry=false&f=json` | **1,990**: PERMIT_NUMBER, ISSUE_DATE, OWNER_1/2, WORK_CLASS, ADDRESS, PROJECT_VALUE, STATUS, 4 contractor fields | OPEN | SCRAPED (r3) |
| **Burke 2023 arms-length sales** | `https://services3.arcgis.com/axQ4OCSpcxALIQsV/arcgis/rest/services/Parcel_Sales_2023_FS/FeatureServer/87/query?where=1%3D1&outFields=*&returnGeometry=false&f=json` | **1,008 sales**, same 66-fld Burke tax schema incl. DEED_DATE + assessed values | OPEN | SCRAPED (r1/r2) |
| **Burke disposable county-owned** | `https://services3.arcgis.com/axQ4OCSpcxALIQsV/arcgis/rest/services/Disposable_BC_Owned_Parcels_FS/FeatureServer/194/query?where=1%3D1&outFields=*&returnGeometry=false&f=json` | **11 parcels**: **Acq_Type, Acq_Cost, Acq_Year, Notes** + full owner/situs/deed | OPEN | SCRAPED (r2) |
| **Burke `CitizenReporter` (portal-index only)** | `https://gis.burkenc.org/arcgis/rest/services/CitizenReporter/FeatureServer?f=json` | Item exists in portal index, absent from REST folder listing. Server replies `Service CitizenReporter/MapServer not started` | **STOPPED — poll** | **NEW** |
| **Morganton hidden second server** | `https://gis.morgantonnc.gov/image/rest/services?f=json` | Folders: `Burke_Orthos` (10 Burke ImageServers 1993→2022, open), `Neighbors_Orthos`, `Map_Room`, `Mylars`, `Scans_Other` | Orthos OPEN; **`Map_Room`/`Mylars`/`Scans_Other` = 499 Token Required (LOGIN wall)** | **NEW** |
| **Gaston/Cleveland/Lincoln blight reports** | `https://services3.arcgis.com/u6Nvh8zpOQRNNRJi/arcgis/rest/services/BlightProblemReports/FeatureServer/0/query?where=1%3D1&outFields=*&f=json` | Schema live (LOCDESC, PROBTYPE, DETAILS, PHONE, EMAIL, STATUS, RESOLUTION) but **0 rows** on both layers | OPEN, empty — poll | SCRAPED (r1) |
| **Henderson ordinance-violation tracker** | `https://services1.arcgis.com/ZfV5vUaX5QvLLBi9/arcgis/rest/services/OrdinanceViolationTracking_PublicFormView/FeatureServer?f=json` | L1 `OrdinanceViolationsTracking` (caseID, parcelOwner, PIN, violationType, dispositionStatus), L4 `minimumHousingComplaints` (landlord/tenant names+phones, evictionStatus). `capabilities: Create,Editing` → **`returnCountOnly` = "This operation is not supported."** | **WALL — write-only form view, no read.** Do not write to it | SCRAPED (r2) |
| **Polk hosted org root** | `https://services1.arcgis.com/23uf7jKvz6SRPFWJ/arcgis/rest/services?f=json` | **72 services**; `TaxParcels`, `Parcels`, `Site_Addresses`, `SiteAddresses`, `LU_Parcels`, `20260428LAParcels`, `Zoning1` | OPEN | org SCRAPED; most services unenumerated |
| **Transylvania Tax Administration app** | `https://gis.transylvaniacounty.org/taxadminportal/` | HTTP 200. Portal-index item `Tax & Land Records` → `…/portal/apps/webappviewer/index.html?id=072e71230d03460898f502e66961d5cf` | OPEN-HTML | **NEW** (app entry point) |
| **Rutherford County "GIS" AGOL org** | `https://rcgis.maps.arcgis.com/sharing/rest/portals/self?f=json` → id `36I6IHIdr660pAyH`, 182 services | **WRONG STATE.** `LaVergne_Zoning`, `Smyrna_Zoning`, `CVTTXCD`/`PRVWNTTXOD`/`PRVSMRTXOD` (winter/summer tax) = **Rutherford County, TENNESSEE** | n/a | **NEGATIVE — do not ingest** |

### Per-county answer to "portal? items? hidden? new?"

- **Buncombe** — portal YES, 247 items vs 108 REST, 6 hidden but all token-walled. Real catalog is `services6.arcgis.com/VLA0ImJ33zhtGEaP` (**591 hosted services**, 85 distress-relevant), invisible from `gis.buncombecounty.org`. Org already known; the *portal* is new.
- **Henderson** — no portal. `services1.arcgis.com/ZfV5vUaX5QvLLBi9` (98) + City of Hendersonville `services1.arcgis.com/UTZTmZoX2rsa9yFA` (**595**) + Land of Sky `services1.arcgis.com/dUkMSguHjSnNcU9J` (433, carries `Buncombe_Vacant`, `Dogwood_Health_Vacant_Occ`, `VacantProperties`, `WorkforceDistressed`).
- **Gaston** — 2 portals (county + Gastonia). 249 items vs 114 REST; **73 portal-only Web Maps/Experiences/Dashboards**, zero of which the REST directory can show. 3 AGOL orgs: 24 + 6 + 565.
- **Cleveland** — no portal; org `services5.arcgis.com/e0FcENYfYZslNJVM` (33) is the only catalog and it holds the county's only code-enforcement layer.
- **Rutherford** — no portal on either server, no NC AGOL org. Round-1's "nothing here" stands. The `rcgis` org is Tennessee.
- **Burke** — portal YES (60 vs 47, 5 hidden incl. `CitizenReporter`). Morganton portal exposes a **second server host** nobody had. Orgs: `axQ4OCSpcxALIQsV` (143) + **WPCOG `HFXT3ZVvUhhNGNnw` (137, entirely new)**.
- **Lincoln** — portal YES but thin (37 items, 0 hidden). Org `services8.arcgis.com/TaX0xkzgvxdv4n56` (166) is the real catalog.
- **McDowell** — no portal; `services9.arcgis.com/ETP7IuCigkUz7iI9` (81) known, **`services8.arcgis.com/5knkNBxW7TdB9mgC` (McDowell 911, 8) new** — see PII flag below.
- **Polk** — `gis.polknc.org` dead; org (72) is the whole surface.
- **Transylvania** — portal YES, 78 vs 37; the 11 "hidden" are cross-host pointers that reveal Brevard's org `services7.arcgis.com/qkz4LIZAMHN41UKn` (31).
- **Mitchell** — no portal; the county publishes nothing itself. **HCCOG `services1.arcgis.com/vj28eVZMB2OMIUh5` (114)** carries the entire Mitchell parcel + owner-mailing spine.

### PRIVACY EXPOSURE — reporting and stopping

`https://services8.arcgis.com/5knkNBxW7TdB9mgC/arcgis/rest/services/Address_Points/FeatureServer/0` — **McDowell County 911 addressing service, 19,969 points, public, no authentication.** Field-level counts (I retrieved counts only, never values):

- `Last_name` populated on **8,011** records
- `First_name` populated on **7,730** records
- `Phone` populated on **7,078** records
- plus `Mail_Add2 / Mail_City / Mail_State / Mail_Zip` and `PHOTO`

That is a resident name-and-telephone directory keyed to home address, published from a 911 system with no access control. No SSN and no DOB fields are present, but this is private-individual contact data that almost certainly was not meant to be public. **I stopped there: I did not pull records, and I am not proposing an enricher against it.** Recommended action is to notify McDowell County 911/GIS of the exposure. Use `services9.arcgis.com/ETP7IuCigkUz7iI9/.../McDowell_Parcels/0` for McDowell situs instead — it carries `siteadd` with no personal contact data.

Two other services hold complainant/tenant contact data (`minimumHousingComplaints` landlord+tenant names/phones/eviction status; `CitizenProblems_blight` `pocphone`/`pocemail`). The Henderson one is read-blocked anyway; the Hendersonville one has 1 record. Neither should be harvested for contact data — the property-condition fields are the usable signal.

### Compliance notes
Everything above was reached with plain unauthenticated GETs. Four classes of wall were hit and left alone, not worked around: `499 Token Required` (Buncombe `Hosted/*`, Morganton `Map_Room`/`Mylars`/`Scans_Other`), `capabilities: Create,Editing` with query disabled (Henderson ordinance tracker), `Service not started` (Burke `CitizenReporter`), and Cloudflare `error code: 1033` (`gisproxy.hendersoncountync.gov`).

### Highest-value follow-ups
1. `Vacant_BurkeCo` — 21,879 vacant parcels, no vacancy source previously existed for Burke.
2. WPCOG `LocalGovtOwnedProperties` — 1,963 gov-owned parcels across 4 counties in one call.
3. Morganton `/image` — poll `Map_Room`/`Mylars` in case the token requirement is a misconfiguration rather than policy; the orthos beneath it are already open.
4. Poll `CitizenReporter` (Burke) and `BlightProblemReports` (GCLMPO) — both are provisioned-but-idle code-enforcement pipes.

Scratch artifacts (delete freely): `/private/tmp/claude-502/-Users-cashhigh-Desktop/f9f41c0e-c1d7-4991-a803-581317d111fe/scratchpad/` — `portal_*.jsonl` (877 portal items), `hosted.txt` (2,879 hosted services), `rest_walk.txt`, `orghunt.txt`, and the four probe scripts `agolenum.py` / `walk.py` / `diff.py` / `probe.py`.