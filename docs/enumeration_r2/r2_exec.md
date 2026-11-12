# ROUND-2 EXECUTIVE LAYER

## 1. ROUND-2 SCOREBOARD

| Block | Net-new | Basis |
|---|---|---|
| Buncombe NC | 34 | stated in section header |
| Lincoln NC | 38 | stated |
| Spartanburg SC | 23 | stated |
| Oconee SC | 21 | stated |
| Cherokee SC | 19 | stated |
| Burke NC | 17 | stated |
| Henderson NC (redo) | 19 | counted from rows marked NEW; the table I received was truncated, so treat 19 as a floor |
| NC/SC state + federal | 16 usable | plus 1 NEW-but-unusable (SCDOT Displacements). 2 of the 16 are UNVERIFIED (OpenFEMA IHP + HMA, HTTP 503 on 4 retries) |
| Municipal WNC | 9 | 8 usable, 1 empty (Hendersonville Citizen Problem Reporter) |
| Municipal Gaston/Cleveland/Lincoln/Burke/Rutherford | 21 enumerated / 6 usable | the rest are login walls, WAF, or non-distress |
| Municipal Upstate SC (34 towns) | 18 enumerated / 11 usable | 3 of 34 towns publish anything |
| Underwriting + signal map | 7 | Cleveland sales, Anderson sales, Lincoln sales upgrade, FHFA county/ZIP5/tract HPI, NC AOC filings xlsx |

Raw round-2 sum: **242**. Known double-counts: 5 Spartanburg city layers appear in both the county block and the Upstate SC municipal block, Hendersonville VACANT_STRUCTURES appears in both the Henderson redo and the WNC municipal block, plus 1-2 Asheville/Buncombe overlaps. De-duplicated round 2: **~234**.

**Running total with round 1's 251: ~485.** Call it 480-490, not a precise number, because the Henderson table was truncated and the municipal blocks mix live sources with documented walls.

## 2. TOP 15 NET-NEW FROM ROUND 2

| # | Source | URL | Effort |
|---|---|---|---|
| 1 | Buncombe parcel owner + **73,965 phones** | `https://gis.buncombenc.gov/arcgis/rest/services/Accela/MapServer/6/query?where=Phone+IS+NOT+NULL+AND+Phone+<>+''&outFields=ParcelNumber,OwnerFullName,Phone,Phone2,MailAddress1,MailCity,MailState,MailZip&returnGeometry=false&f=json` | S |
| 2 | Spartanburg weekly Assessor_Extract (whole 181k roll + only free sqft) | `https://www.arcgis.com/sharing/rest/content/items/1f190ebd48c1402a918c3bc315431a1b/data` | S |
| 3 | Oconee countywide owner + mailing (68,145) | `https://arcserver2.oconeesc.com/arcgis/rest/services/CitizenServe/MapServer/5/query?where=1%3D1&outFields=*&resultOffset=0&resultRecordCount=1000&f=json` | S |
| 4 | Oconee delinquent tax rolls w/ $ owed (645 + 476 + 440) | `https://services1.arcgis.com/UOvRn2Rvzysthh3i/arcgis/rest/services/DT2025/FeatureServer/0/query?where=1%3D1&outFields=*&returnGeometry=false&f=json` | XS |
| 5 | Buncombe unpaid property bills 2026/2025/2024 (servicer + loan no.) | `https://services6.arcgis.com/VLA0ImJ33zhtGEaP/arcgis/rest/services/Unpaid%20Property%20Bills%20from%202025/FeatureServer/0/query?where=1%3D1&outFields=*&returnGeometry=false&f=json` | S |
| 6 | Hendersonville vacant/condemned register (52 rows, owner + mailing + delinquency notes) | `https://services1.arcgis.com/UTZTmZoX2rsa9yFA/arcgis/rest/services/VACANT_STRUCTURES_7_24_24/FeatureServer/0/query?where=1%3D1&outFields=ADDRESS,OWNER,MAILING_ADDRESS,OCCUPIED,BOARDED_UP,CONDEMNED,DELINQUENT_TAX,UTILITIES,NOTES&returnGeometry=false&f=json` | XS |
| 7 | Henderson live code violations (163 live / 3,231 history, daily) | `https://services1.arcgis.com/ZfV5vUaX5QvLLBi9/arcgis/rest/services/OVT_PublicDashboard_View/FeatureServer/1/query?where=1%3D1&outFields=caseID,dateReceived,parcelOwner,address,violationType,PIN,dispositionStatus&returnGeometry=false&f=json` | XS |
| 8 | Spartanburg City Master Condemnation List (92-94 fully resolved leads) | `https://www.cityofspartanburg.org/DocumentCenter/View/1901/City-of-Spartanburg-Master-Condemnation-List-` | S |
| 9 | Burke disposable county-owned parcels w/ live BidLink | `https://services3.arcgis.com/axQ4OCSpcxALIQsV/arcgis/rest/services/Disposable_BC_Owned_Parcels_FS/FeatureServer/194/query?where=1%3D1&outFields=*&returnGeometry=false&f=json` | XS |
| 10 | Oconee FLC richer service (468 rows, full money trail) | `https://services1.arcgis.com/UOvRn2Rvzysthh3i/arcgis/rest/services/Assignment_FLC/FeatureServer/1/query?where=Status%3D%27NONE%27&outFields=*&returnGeometry=false&f=json` | XS |
| 11 | Anderson SC sales roll (40,427, county had no comp config) | `https://propertyviewer.andersoncountysc.org/arcgis/rest/services/Parcel_Sales/MapServer/0` | XS |
| 12 | Cleveland NC sales (6,481 improved + 2,765 vacant, stamp-verified) | `https://gis.clevelandcounty.com/arcgis/rest/services/Tax/Vacant_ImprovedLot_Sales/MapServer/1` | XS |
| 13 | Buncombe voter file, 26,741 aged 75+ **with phone** | `https://gis.buncombenc.gov/arcgis/rest/services/opendata/MapServer/8/query?where=AgeAtYearEnd>=75+AND+TelephoneFullNumber<>''&outFields=*&returnGeometry=false&f=json` | S |
| 14 | Spartanburg cleanup requests, 2,349 owner phones | `https://services6.arcgis.com/YJV3IFNXuNHJDIvn/arcgis/rest/services/Private_Property_Cleanup_Locations/FeatureServer/13/query?where=USER_Phone+IS+NOT+NULL&outFields=*&f=json` | XS |
| 15 | Burke full CAMA (59,433; 3,171 out-of-state, 1,560 deferred) | `https://gis.burkenc.org/arcgis/rest/services/ProdParcelViewFC/MapServer/0/query?where=1%3D1&outFields=*&returnGeometry=false&resultOffset=0&resultRecordCount=1000&f=json` | S |

Honorable mentions that missed the cut: Gastonia CityView bulk code-enforcement POST (1,781 cases carrying county PIN, effort M), the 15 anonymous Tyler Register-of-Actions deep links for Henderson tax foreclosures, and the NC AOC foreclosure-filings xlsx as a free per-county-per-month denominator for scraper-death QA (`https://www.nccourts.gov/documents/publications/foreclosure-filings`).

## 3. THE MUNICIPAL LAYER

**Worth it, but narrowly, and it should not be repeated at this breadth.** Roughly 50 municipalities were probed across three sweeps; about 26 usable sources came back, and 80% of the value sits in four cities.

Publish real distress data:
- **Spartanburg SC** by far the richest. The only municipality in either state publishing a named condemned-property roster, plus tax-sale parcels, infill list, city-owned layer 4, and a fresh CAMA snapshot.
- **Hendersonville NC** a code officer's working vacant/condemned register published raw, with owner mailing and free-text delinquency notes.
- **Asheville NC** its own 36-folder ArcGIS server: real-property disposition pipeline at layer 25 (Strategize/REVIEW/Monitor, with deed URLs and acquisition cost) and Accela code-enforcement categories usable as a source rather than a match-only enricher.
- **Gastonia NC** CityView bulk polygon query, the only real distress channel in Gaston, and it carries the county PIN so it skips the resolver.

Thin but real: Fletcher NC (10 live cases with owner name and address), Anderson SC (perfect schema, 10 stale rows, worth a quarterly re-probe), Clinton SC (parcels, city-owned), Kings Mountain NC (7,902-parcel owner master, hazard not distress), Mount Holly NC (12 marketed sites).

Publish nothing usable: 20 named Upstate SC towns, 5 with no web presence at all, plus Belmont, Bessemer City, Cherryville, Forest City, Valdese, Lake Lure, Rutherfordton, Brevard, Marion, Morganton. Every one runs a minimum-housing or nuisance program; none publishes a case, lien, or condemnation list. That is a closed question now, not a gap to re-probe.

Two compliance outputs matter as much as the data: Fletcher's tracker exposes complainant name/phone/contact, Hendersonville's registry carries owner phone/email, Kings Mountain's reporter carries name/phone/email, and Lincoln County's `Server_Tables/MapServer/10` publishes SSN columns anonymously. Any wiring must whitelist columns and never use `outFields=*`. Lincoln and Fletcher should be notified.

## 4. EARLIEST PRE-FORECLOSURE SIGNAL

**NC tax delinquency, 1 to 3 years ahead of sale, and we can get it today.** The statutory artifact is the G.S. 105-369 tax lien advertisement published March 1 to June 30 with owner name, parcel description, and dollar amount. Round 2 found something better than the ad in Buncombe: the live levy files themselves, `Unpaid Property Bills from 2026` (125,827 rows), `2025` (7,922 survivors of a full collection cycle), `2024` (6,255), and annual services back to 2009. Those carry `total_due`, `mortgage_co`, and `loan_num`, so they fire before the ad is even compiled and identify the servicer. Oconee's DT2025/24/23 stack is the SC analog with a repeat-delinquency score across three years.

For mortgage foreclosure specifically the earliest thing that exists is not obtainable. G.S. 45-102 is private correspondence, the 45-103 filing goes to the AOC, and the SHFPP database is closed by statute. Those are walls, not scraper failures. The earliest **free** mortgage artifact in NC is the recorded substitution of trustee under G.S. 45-10, roughly 60 to 120 days out, available through the county ROD grantor index. There is no NC notice of default and no lis pendens in power-of-sale, so any vendor list claiming either is relabeled.

In SC the earliest artifact is the lis pendens under 15-11-10 at 150 to 365 days, which beats everything in NC except tax. We cannot reliably get it: the Public Index is ToS-gated and whether the ROD side carries lis pendens is flagged UNVERIFIED and is the single highest-value open question in the map.

## 5. WHAT IS STILL MISSING

- **Enumeration has outrun ingestion.** ~485 sources catalogued across two rounds and none of round 2 is wired. Every count above is a claim about what exists, not about what the board contains.
- **SC court side.** Lis pendens, mortgages, deeds of distribution and MIE rosters remain manual-lane for Oconee, Cherokee and peers. sccourts ToS wall plus Kofile login. The ROD-lis-pendens question is unverified.
- **Burke has no delinquent-tax balance lane at all.** bcpwa returns false, burkenctax.com is a dead SPA, no 105-369 list is published. Deferred value and absentee status are the only arrears proxies.
- **Unverified claims to close:** OpenFEMA IHP and HMA Mitigated Properties (both 503, county counts never confirmed), the Cherokee SC qPublic route (URL taken from a county page, not fetched), Buncombe's stale fcl.pdf content (21CVD/21CV cases), and the Trumba details feed currently at zero events.
- **Standing walls unbroken:** NC SoS UCC and federal tax lien index (403 WAF), NC eCourts Smart Search estates, SCDOT SC_Parcels now token-walled, HUD Home Store site-wide robots disallow, US Marshals 403, Oconee CitizenServe and Host Compliance STR, Anderson ViewPointCloud, Lincoln eTRAKiT, Forest City SmartGov, Kings Mountain OpenGov, Marion AvailableProperties token.
- **Program-confirmed, list-not-published:** Asheville abandoned-structures list (~30 properties, staff-held), Greer demolition liens, Pendleton IPMC cases, Inman vacant-building registry. Only routes are records requests and minutes parsing, neither built.
- **Coverage honesty.** The material I received contains dedicated round-2 registers for Buncombe, Burke, Lincoln, Henderson, Spartanburg, Oconee and Cherokee only. Anderson, Pickens, Union, Laurens, Rutherford, Cleveland, Polk, Gaston, Transylvania, McDowell and Mitchell appear only incidentally through the state, municipal and underwriting sweeps. Either their registers are filed elsewhere or those 11 counties have not had a round-2 pass. That should be resolved before anyone treats ~485 as footprint-complete.