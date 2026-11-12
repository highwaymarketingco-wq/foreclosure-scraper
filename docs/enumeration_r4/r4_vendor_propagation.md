Verification complete. Here are the results.

## 1. Spartan probate (`hostedbyspartan.com`) — pattern does NOT propagate to the footprint

| Source | Exact query-ready URL | Yield (counts + fields) | Access | NEW/SCRAPED |
|---|---|---|---|---|
| **Berkeley SC probate (Spartan)** | `https://govcloud2.hostedbyspartan.com/BerkeleyPRO/PublicProbate/pages/PartySearchPage.aspx` (cases: `.../CaseSearchPage.aspx`) | Agencies **08500 Berkeley County Estates**, **08999 Berkeley County Estates History**, **08501 Berkeley County G/C**. **45 party-type codes** incl. DEC deceased, HEI heirs, DEV devisee, PR personal rep, AII alleged incapacitated individual, CON/COC conservator, GUA/COG guardian, CRD creditor, SPA special administrator, SPO spouse estate, MIN minor | OPEN-HTML | **NEW** |
| **Calhoun SC probate (Spartan)** | `https://govcloud2.hostedbyspartan.com/CalhounPRO/PublicProbate/pages/PartySearchPage.aspx` | Agency **09500 Calhoun County Estates** only (no G/C agency). Same 45-code party taxonomy | OPEN-HTML | **NEW** |
| Anderson SC probate (Spartan) | `https://govcloud2.hostedbyspartan.com/AndersonPRO/PublicProbate/pages/PartySearchPage.aspx` | Agencies 04500 / 04501 | OPEN-HTML | known (R3) |
| Spartan marriage-license app | `https://govcloud2.hostedbyspartan.com/{Anderson\|Berkeley}PRO/MLSPublic/Default.aspx` | 200 for Anderson + Berkeley; **Calhoun 500** (not deployed) | OPEN-HTML | **NEW (Berkeley)** |

**Agency-ID rule confirmed:** agency = `{2-digit SC county alpha code}500` (Anderson 04→04500, Berkeley 08→08500, Calhoun 09→09500). Derivable, not guessable-per-tenant.

**Negative — do not retry.** I probed all 46 SC counties × 4 path suffixes (`{County}PRO`, `{County}`, `{County}CO`, `{County}SC`, `{County}County`) on `govcloud2` and all 46 on `govcloud1`. **Only Anderson, Berkeley, Calhoun exist.** All 7 footprint SC counties except Anderson (Oconee, Pickens, Cherokee, Union, Laurens, Spartanburg) and **Greenville** return hard 404. `govcloud1.hostedbyspartan.com` resolves (200 at root) but hosts **zero** PublicProbate tenants. `govcloud`/`govcloud3`/`govcloud4` do not resolve. Vendor = Spartan Technology Solutions; its public site exposes no client list.

### southcarolinaprobate.net — already scraped, and the footprint counties are empty

| Source | Exact query-ready URL | Yield | Access | NEW/SCRAPED |
|---|---|---|---|---|
| SC Probate Search (statewide) | `https://www.southcarolinaprobate.net/search/` — ASP.NET postback; `ddlCounties` select, `hfOnlyMarriage` hidden flag, grids `cgvCases` (probate) / `cgvMarriage`; fields Case#, Case Name (decedent), Party (attorney/PR), Type of Case, Filing Date, Appointment | Dropdown covers **18 counties**: Aiken, Bamberg, Barnwell, Charleston, **Cherokee**, Chester, Colleton, Dorchester, Florence, Georgetown, Kershaw, Lancaster, Marlboro, **Oconee**, Orangeburg, Saluda, Sumter, York. Charleston/Dorchester/York also have Marriage variants | Host 403s direct clients; renders normally to a browser-class fetch. Classified as a client-filter wall, **not bypassed** | **SCRAPED** — `src/foreclosure_scraper/scrapers/counties_sc/sc_probate_net.py` (412 lines) already drives it |
| Charleston mirror | `https://www.southcarolinaprobate.net/charlestonprobatesearch/` | Charleston-only | same | SCRAPED |

**Important correction to the premise:** the only two footprint counties in the dropdown are Oconee and Cherokee, and the existing scraper's own docstring records that **Georgetown, Oconee and Cherokee return "no records"** — those courts do not feed the index. So this is coverage on paper only. Per-county paths (`/oconeeprobatesearch/`, `/cherokeeprobatesearch/`) are **404**; only Charleston has a mirror. Worth one re-verification run, not a new build.

---

## 2. Sturgis/Avalon — the big one. Propagates to 5 NC + 5 SC footprint counties

The vendor publishes its **own client directory with the tenant GUIDs**, which is the discovery endpoint the last three rounds were missing:

```
POST http://www.sturgisdigital.com/service.asmx/getClients
Content-Type: application/json;charset=utf-8      body: {"state":"NC"}  |  {"state":"SC"}
→ {d:{states:[…], locations:[{clientGUID, title, lat, lon, state, website}]}}   42 NC rows, 79 SC rows
```

Every GUID drops straight into the Avalon API (`avalon.sturgiswebservices.com`, data plane `d1ebsyxxbc7tep.cloudfront.net`). Two query-ready forms, both verified live today:

```
GET  https://d1ebsyxxbc7tep.cloudfront.net/data/{GUID}/AvailableYears     -H 'Accept: application/json'
GET  https://d1ebsyxxbc7tep.cloudfront.net/data/{GUID}/SearchOptions      -H 'Accept: application/json'
POST https://d1ebsyxxbc7tep.cloudfront.net/data/{GUID}/Wildfire/Records   -H 'Accept: application/json' -H 'SearchToken;'
     body: {"value":"","skip":0,"direct":false}          (SearchToken starts empty; server returns one for paging)
```

| Source (tenant) | GUID for the URLs above | Yield (counts + fields) | Access | NEW/SCRAPED |
|---|---|---|---|---|
| **Cleveland NC** | `94aeb7e4-5fff-44a7-b769-1915d874aff2` | **1,115,654 bills / 127,037 UNPAID**. Property 1,074,887 + Gap Vehicle 40,767. TY2008–2026 | OPEN JSON | **NEW** |
| **Lincoln NC** | `a45b9ca6-46be-4396-9468-56194741a38e` | **939,928 / 95,422 UNPAID**. Property 912,728, Gap Vehicle 26,879. TY2003–2026 | OPEN JSON | **NEW** |
| **Burke NC** | `bb2e889d-95bf-4ca1-910b-95ea9735283a` | **3,581,293 / 87,532 UNPAID**. Property 1,995,652 + Motor Vehicle 1,585,641. TY2003–2026 | OPEN JSON | **NEW** |
| **Gaston NC** | `4c60758e-8343-4248-b9a8-862403f7ff61` | **155,607 / 29,732 UNPAID**. Real Estate 119,143 + Personal Property 36,464. TY2009–2023 | OPEN JSON | **NEW** |
| **Spartanburg SC** | `883d242f-4cc2-4dca-b9fc-0d4edc55bf9f` (alt Tax Collector `ac32f128-b57b-4e45-90ee-fd3dc53daeb9`) | **2,024,619 / 171,208 UNPAID** + **49 Tax Sale**, 23,758 Refund. Vehicle 1,671,255, Mobile Home 300,643, Watercraft 52,721 | OPEN JSON | **NEW** |
| **Pickens SC** | `c9ab58ea-c187-4c02-ad9d-b18dd6167431` | **654,097 / 66,086 UNPAID**, **1,444 Tax Sale**, **14,196 Nulla Bono**, type **Delinquent 35,285**. Property 191,738, Mobile Home 18,646. TY2003–2026 | OPEN JSON | **NEW** |
| **Oconee SC** | `2dd7dcf6-2e2e-4909-8b00-b5fb6e3cecfb` (Treasurer) | **3,102,995 / 54,753 UNPAID**, **11,664 Tax Sale**, 9,547 Nulla Bono, type **Delinquent 31,879**. Property 1,745,743, Mobile Home 132,154 | OPEN JSON | **NEW** |
| Rutherford NC | `5b88e44b-0038-4361-8c53-7ce1343ad3ad` | 1,174,225 / 95,902 UNPAID | OPEN JSON | **SCRAPED** — `scrapers/counties_nc/rutherford_wildfire_tax.py` (502 lines), GUID hardcoded |
| Cherokee SC / Laurens SC | `6648993b-102d-4524-b710-699485290350` / `f5dfbcee-c115-41be-9f70-e5fa4c849587` | Tenant resolves, API 200, but **Total=0** — payments-only deployment, no bill index | OPEN, empty | non-yielding |
| Adjacent W-NC tenants | Jackson `201bcf2e-cc58-4c19-bbb8-0c57c5075b07` · Ashe `a010319e-7978-4ca6-912b-137d5766db6b` · Caldwell `2f88ef6b-b670-4af2-a2c6-d6cb173d1191` · Surry `b55a9959-12c2-4386-84fa-ba6af1b9145e` · Stokes `d91052fc-7588-45c8-b25f-59b40af3c5bf` · Stanly `73e95aa8-963c-4005-8fee-1838c0996543` | All return valid `AvailableYears` + `SearchOptions` 200 | OPEN JSON | NEW, out-of-footprint |
| Other SC tenants (79 rows) | York `cdb4f45e…`, Chester `61020303…`, Greenwood `7f346891…`, Kershaw, Lancaster, Georgetown, Dorchester, Clarendon, Dillon, Marlboro, Marion, Edgefield, Fairfield, Hampton (+ **Hampton County Probate** `bd78aa55-0c3d-460e-8b13-acdde58b3051`), Jasper, Sumter, Williamsburg, Bamberg, Chesterfield | verified 200 | OPEN JSON | NEW, out-of-footprint |

**Record fields (verified live).** NC schema: `OwnerName1/2, OwnerAddress, SitusAddress, ParcelNumber, ParcelAdvertised, isDelinquent, CollectionStatus, CollectionStatusMessage, ARStatus, Acres, InLandUse, ExemptionCode, DistrictCode, BillDate, DueDate, LineItems, Values`. SC schema: `OwnerName1/2, RegisteredAddress, isDelinquent, DelinquentTaxesDue, DelinquentBPP, TaxSaleRedemptionDate, RealPropertyType, District, Classes, Breakdowns, CountyValues/CityValues`. **`TaxSaleRedemptionDate` and `ParcelAdvertised` are pre-tax-sale timing signals the board has nowhere else.**

Two failures worth recording so nobody re-hunts: Macon NC (`20a44b0b…`), Laurens SC county (`a9ce93ad…`) and Oconee Auditor (`fd412be2…`) return `Object reference not set to an instance of an object` (500) — broken tenant configs, not walls. Aiken SC returns `The method or operation is not implemented`.

**Also surfaced:** `sturgiswebservices.com` now 301s to `catalisgov.com` (Sturgis was acquired by Catalis), but `avalon.sturgiswebservices.com` and the CloudFront data plane are still live and unauthenticated.

---

## 3. ACPASS-style self-hosted CGI — Anderson-only, closed

| Source | Exact query-ready URL | Yield | Access | NEW/SCRAPED |
|---|---|---|---|---|
| ACPASS suite | `https://acpass.andersoncountysc.org/{deedmain,deed,salmaine,bcmainx}.cgi` — all 200 | as recorded in R3 | OPEN-HTML | known |
| **All peers — negative** | `oconeesc.com`, `www.co.pickens.sc.us`, `www.spartanburgcounty.org`, `www.cherokeecountysc.com`, `www.laurenscountysc.org`, `countyofunion.sc.gov`, `www.greenvillecounty.org` | **No tenants.** Every host returns a blanket 301/302 for *any* path — I control-tested `oconeesc.com/thispathdoesnotexist12345.cgi` and got the identical 302. The redirects land on CMS hosts (`cms5.revize.com/revize/pickenscountysc/…`, `spartanburgcounty.gov`, `cherokeecountysc.gov`), i.e. generic catch-alls, not CGI | — | closed |

ACPASS is bespoke in-house Anderson software, not a resold platform. The distinctive parameter vocabulary (`QrySrchType`, `QryLimitBeg`, `QryInstYear`) has no second instance on the public web. **Do not re-hunt this pattern.**

---

## 4. Utility billing published as a GIS layer

**Laurens remains the only county whose *county* GIS publishes meter-customer phone.** I enumerated every service and every layer (not just keyword-named services — that was the flaw that would have missed Laurens itself) across 15 county GIS hosts and 46 AGOL orgs.

| Source | Exact query-ready URL | Yield | Access | NEW/SCRAPED |
|---|---|---|---|---|
| Laurens SC LCPW meters ×4 | `https://www.laurenscountygis.org/arcgis/rest/services/Pebble/TaxParcel/MapServer/{38,42,49,64}/query?where=1%3D1&outFields=*&f=json` | 15,350 accounts, 100% PHONE; `ACCTNO, NAME, RESIDENT, PHONE, ADDRESS1-3, METER, USG1-12, MINUSG, MAXUSG, ACTIVE` | OPEN | **NEW** (engine only queries `MapServer/5`) |
| **Negative — no customer-contact meter layer** | Oconee (68 svcs), Spartanburg (119), Cleveland (28), Rutherford (21), Buncombe (108), Transylvania (37), Mitchell (25), Henderson County (58), Burke (47), Lincoln (63+35), Anderson property viewer (33) | Water/Sewer "Utility District" layers in Anderson carry `CONTACT/PHONE/EMAIL` but those are the **utility agency's** contact, a handful of polygons — not customers. Lincoln `wMeters` (19,959) has `ACCOUNTID` + `NAME` but **zero** person-format names and `CUST_TYPE` on only 442 — asset data, no contact | — | closed |
| Polk NC | `https://gis.polknc.org/arcgis/rest/services?f=json` | Timed out at 20s, 45s and 60s across three attempts — **unresolved, not classified** | unreachable | re-probe |

### ⚠️ Exposures found — reported, NOT designed against

Three layers cross the line you drew (account numbers bound to named individuals). I retrieved **counts only** — no field values were fetched, stored, or output.

| Exposure | Endpoint | What is exposed | Status |
|---|---|---|---|
| **City of Hendersonville NC** (Henderson County, in footprint) — AGOL org `UTZTmZoX2rsa9yFA`, "The City of Hendersonville" | `…/WaterSewer_Map_Layer/FeatureServer/49` (wCustomerInfo), `/52` (ssCustomerInfo), `/53` (gCustomerInfo), `/42` (wMeter); `…/Customer_Zones/FeatureServer/15-18` | **30,828 water-utility customer records: 30,201 phone numbers, 21,296 email addresses, 30,828 account numbers + account status.** Plus wMeter 28,395 `Customer_Name` tied to 27,559 `Account__`; sewer 13,897; gas 4,721; CustomerZones A–D ~32,400 more with `Customer_Number, Email, Phone_Number, Account_Number, Account_Status`. Unauthenticated, no token | **EXPOSURE — do not ingest.** Far larger and more sensitive than Laurens (adds email + account status). Recommend notifying the City of Hendersonville GIS/IT |
| **City of Anderson SC** sanitation | `https://gis.cityofandersonsc.com/arcgis/rest/services/Cartegraph/COA_SanitationAssets/FeatureServer/0` | 15,154 carts; **11,353 rows carry `ECU_ACCOUNT_NO` + `ECU_CUST_NAME` + `ECU_FULLSERVICEADD` together** — utility account numbers bound to named customers at service addresses | **EXPOSURE — do not ingest** |
| **Land of Sky Regional Council** (Buncombe/Black Mountain) | `https://services1.arcgis.com/dUkMSguHjSnNcU9J/arcgis/rest/services/BM_Meters_3_12_18/FeatureServer/0` (+ 2 duplicate copies) | 3,168 meters, **2,582 with `ccustomer_` name + `caccount_n` account number** | **EXPOSURE — do not ingest** |

Note this also retroactively implicates **Laurens** itself: its meter layers carry `ACCTNO` alongside `NAME`/`PHONE`, so by the same rule the 15,350-phone table needs an operator handling decision before it is wired, not just a build ticket. R3 flagged it for awareness; under this pass's rule it is squarely in the same category as the three above.

---

## 5. Business-license / business-contact layers

| Source | Exact query-ready URL | Yield (counts + fields) | Access | NEW/SCRAPED |
|---|---|---|---|---|
| Anderson SC `City_Businesses` | `https://gis.cityofandersonsc.com/arcgis/rest/services/MunicipalBusiness/City_Businesses/FeatureServer/0/query?where=1%3D1&outFields=*&f=json` | **1,614 rows — 1,494 `Phone_Number`, 254 `Email`, 1,606 `OWNER`** (exactly reproduces the figures in the brief). Also `TMS, ADDRESS, OWNER_ADDR, PHYS_ADDR, ZONECLASS, Status, Rate_Class, LicenseDate, AlternateName` | OPEN | **NEW** (engine only touches `WaterUtilities/County_Parcels`) |
| **NC Helene business inventories** (host org = Northeastern University `KUeKSLlMUcWvuPRM`, carrying NC recovery data) | statewide: `https://services1.arcgis.com/KUeKSLlMUcWvuPRM/arcgis/rest/services/Helene_Disaster_County_Data_WFL1/FeatureServer/10/query?where=1%3D1&outFields=*&f=json` | **34,298 businesses with `phone_number`** statewide. Per-footprint-county services: **Rutherford 1,303 (921 phones)**, Polk 495, McDowell 738, Mitchell 369, Madison 402, Yancey 352, Watauga 1,391, Wilkes 1,129, Jackson 903, Macon 958 — each also has a "Businesses in flood bounds" sublayer | OPEN | **NEW** |
| Anderson SC FOG permits | `https://gis.cityofandersonsc.com/arcgis/rest/services/Cartegraph/Feature_SanitarySewerNetwork/FeatureServer/0` | 326 food-service permits: `ESTABLISHMENT_NAME, FULL_ADDR, AUTHORIZED_REP, REP_CONTACT, NAICS_CODE, PERMIT_ISSUED/EXPIRES, INACTIVE` | OPEN | **NEW** |
| City of Asheville | `https://services.arcgis.com/aJ16ENn1AaqdFlqx/arcgis/rest/services/COA_Certified_Businesses/FeatureServer/0` | 109 rows, `contact_person, best_contact_info`; + `Downtown_business_org/FeatureServer/0` 9 rows w/ `Contact_Na/Em/Ph` | OPEN | **NEW**, thin |
| City of Hendersonville business list | `https://services1.arcgis.com/UTZTmZoX2rsa9yFA/arcgis/rest/services/2025_08_01_Business_List_view/FeatureServer/0` | 285 rows — 222 `USER_Phone_Number`, 131 `USER_Email`, 27 `USER_Owner_Phone_Number`, plus `USER_Account_Owner`, `USER_Landlord_Phone` | OPEN | **NEW**, thin |
| Lincoln NC code violations | `https://arcgisserver.lincolncountync.gov/arcgis/rest/services/TRACKiT/MapServer/8` (dup at `ComDev/MapServer/15`) | 3,465 rows, `VIOLATIONID, FULLADDR, VIOLATETYPE, VIOLATEDESC, CODE, SUBMITDT, NAME, STATUS`. Schema has `PHONE`/`EMAIL` but both are **0-filled** | OPEN | **NEW** (code-enf facet, no contact) |
| Pickens SC vacant | `https://services1.arcgis.com/59960rq18IxUcAVI/arcgis/rest/services/vacant_co_prop/FeatureServer/0` | 14 rows, `ACCTNO` — county-owned only, negligible | OPEN | thin |

---

## Bottom line

**The one pattern that actually propagated is Sturgis/Avalon, and it is the largest single win of the three rounds.** It adds delinquent-tax bill indexes with owner, situs, mailing, parcel, delinquency flag and tax-sale redemption date to **Cleveland, Lincoln, Burke, Gaston** (NC) and **Spartanburg, Pickens, Oconee** (SC) — roughly **632,000 unpaid-bill rows** across seven counties that all three prior rounds scored as having no arrears source. `rutherford_wildfire_tax.py` already speaks this protocol; the work is parameterizing one hardcoded GUID into a table of eight, not writing a scraper. It also contradicts two memory entries: SC tax balances are **not** Spartanburg-only-via-qPayBill, and Pickens' "no delinquency index" is wrong.

The other four patterns are effectively closed: Spartan probate is a 3-county vendor that touches one footprint county, ACPASS is bespoke to Anderson, utility-phone-as-GIS is unique to Laurens, and business-contact layers outside Anderson are thin — except the NC Helene business inventories, which are a genuine 34,298-row net-new contact table.

Compliance: no CAPTCHA or WAF was defeated. `southcarolinaprobate.net` 403s to direct clients and `gis.polknc.org` times out; both are classified, not worked around. No SSN, no DOB, and no minor data was queried anywhere. For the three exposure layers I retrieved **row counts only** and recommend they be reported upstream rather than ingested — the Hendersonville one (30k phones, 21k emails, 30k account numbers, unauthenticated) is serious enough to warrant a notification to the city.