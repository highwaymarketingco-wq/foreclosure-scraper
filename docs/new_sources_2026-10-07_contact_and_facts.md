# New sources for contact and property facts, NC and SC (2026-10-07)

Companion data file: `docs/new_sources_2026-10-07_contact_and_facts.json` (one record per source with every field asked for: owner, URL, geography, fields, access class, price, legal notes, measured coverage, ingestion status, build hours, lift for the weakest 10 counties, manual steps, how it was verified).

Method: read-only `iter_board_rows()` passes, counts only, one at a time (about 35 s and 290 MB each): the baseline over 350,013 rows (run three times, twice to fix my own mail predicate), one for parcel-id shapes, and one for the live proof of the two builds. Sources were checked with at most 4 requests each, 1.6 s or more apart per host, an ordinary browser User-Agent. No CAPTCHA, login, paywall, WAF or bot check was solved or routed around, no person's name was searched, and nothing here names an owner. The session's web-search budget ran out early, so discovery leaned on the ArcGIS Online catalog search, layer metadata and vendor pages fetched directly.

## 1. Bottom line

1. **121 sources catalogued**: 88 the repo does not ingest at all, 50 of those never named in any repo doc. 91 were checked by a fetch today; the others rely on earlier repo research or are marked not verified.
2. **The weakest 10 counties are all in South Carolina** and sit at 0 to 0.2 percent owner mail and 0 percent phone. Every one of them is walled at the county (qPublic Cloudflare, WTH viewers, an Akamai county site) except Beaufort, Dorchester (license clause), Richland (viewer disclaimer) and Newberry (service stopped today). There is no open statewide SC parcel layer: the state GIS server carries none and SCDOT's needs a token.
3. **Built and proved: two open county parcel layers** (Jasper SC via a city-hosted copy, Beaufort SC via the county EnerGov service), committed with tests. Measured on the board: Jasper mail 0.5% -> 48.6%, value 0% -> 51.4%; Beaufort value 0.2% -> 41.6%, last sale 0.1% -> 38.2%, mail 0.2% -> 5.5%. Nothing was written to the board.
4. **The biggest free lift needs no new source: 36,469 board rows** (Gaston 15,899, Transylvania 5,439, Charleston 2,201, ...) have a parcel id and no mailing while the county cache on disk already holds their mailing. Running the existing join on the VM would add up to about 10 points of board-wide mail (its shared-parcel guard may skip some).
5. **SC phone has exactly one large free source**, and the repo already chose not to read it: the SC DES tank registry detail page shows the tank owner's phone (30 of 30 in the repo sample), about 3,125 rows in the weakest 10, mostly business lines. Everything else that moves SC phone is paid (Tracerfy $0.02 per hit, the cheapest verified today).
6. **Compliance flag for the owner**: the NC Secretary of State's business registration page now says automated or scripted searches are not permitted and points bulk users to a paid subscription ($750 setup + $2,000 per year). The repo's automated NC SoS entity lookups run against that term.

## 2. The weakest 10 counties

Counties with at least 900 board rows, ranked by owner-contact coverage (mail or usable phone), lowest first. Board of 2026-10-07, 350,013 rows, one read-only iter_board_rows pass.

| County | Rows | Mail | Phone | Parcel id | Value | Sqft |
|---|--:|--:|--:|--:|--:|--:|
| Williamsburg SC | 2,476 | 0.0% | 0.0% | 91.0% | 0.0% | 0.0% |
| Richland SC | 2,229 | 0.0% | 0.0% | 0.2% | 0.0% | 59.8% |
| Dorchester SC | 1,735 | 0.0% | 0.0% | 75.3% | 0.0% | 31.6% |
| Clarendon SC | 1,649 | 0.0% | 0.0% | 86.4% | 0.0% | 0.0% |
| Chesterfield SC | 1,011 | 0.0% | 0.0% | 71.7% | 0.0% | 0.0% |
| Newberry SC | 977 | 0.0% | 0.0% | 54.2% | 0.3% | 0.0% |
| Edgefield SC | 921 | 0.0% | 0.0% | 81.4% | 0.0% | 0.0% |
| Marlboro SC | 1,250 | 0.2% | 0.0% | 81.8% | 0.1% | 0.0% |
| Beaufort SC | 1,695 | 0.2% | 0.0% | 1.5% | 0.2% | 45.6% |
| Kershaw SC | 1,927 | 0.2% | 0.0% | 88.1% | 68.7% | 0.0% |

Next tier: Jasper SC (989 rows, 0.5% mail), Dillon SC (1,502, 0.8%), Hyde NC (2,652, 1.7%), Washington NC (1,744, 0.6%). Most rows are qPayBill delinquent-roll rows (owner name and parcel id, nothing else) and SC tank-registry rows (mostly entity owners). Board-wide: NC phone 77,748 of 241,423 (32.2%), SC phone 4 of 108,590; NC mail 47.3%, SC mail 40.7% (mail counted as the coverage audits' union, which includes `gis.mailing`).

## 3. What was built, and what it measurably adds

Commit: `parcel_cache: Jasper SC ... and Beaufort SC ...` (local only, not pushed).

| | Jasper SC | Beaufort SC |
|---|---|---|
| Source | County parcel layer as published by the City of Hardeeville on ArcGIS Online (public, no license text, last edited 2025-08-12) | County EnerGov MapServer layer 1 (open, no license text) |
| Where in code | `parcel_cache.PARCEL_LAYERS['Jasper']` | `parcel_cache.SC_DUAL_LAYERS['Beaufort']` (new table for the SC half of the six two-state county names) |
| Parcels cached | 20,258 of 20,258 | 141,367 of 141,367 |
| Fields kept | owner, mailing, E911 situs, market appraisal, acreage, consideration | owner, mailing, situs, appraised value, acreage, residential sqft, class, sale price and date |
| Board rows | 989 (821 with a parcel id) | 1,695 (25 with a parcel id) |
| Parcel-id join hits | 465 (owner name agrees on 302) | 25 (owner agrees on 1) |
| Address-resolver unique parcels | 49 | 712 (owner agrees on 54; the rest are lien debtors and tank operators renting the parcel) |
| Mail | 5 -> 481 (0.5% -> 48.6%) | 3 -> 94 (0.2% -> 5.5%) |
| County value | 0 -> 508 (0% -> 51.4%) | 3 -> 705 (0.2% -> 41.6%) |
| Last sale | 0 -> 331 (0% -> 33.5%) | 2 -> 647 (0.1% -> 38.2%) |
| Sqft | 0 -> 0 (the layer has none) | 773 -> 841 |

How it was measured: `scripts/measure_parcel_cache_lift.py --counties SC:Jasper,SC:Beaufort` (one streaming pass, counts only). It applies the same fill-only rules as `scripts/join_parcel_cache_to_board.py` and the situs rules of `scripts/resolve_parcel_from_address.py`, and counts a mailing from an address match only when the resolver's owner check is not False, exactly as the join withholds it. The id-join mail figure does not check owner agreement (the join does not either): for Jasper 163 of 465 hits name a different owner than the delinquent-roll row, because the layer is 14 months old and roll names differ in form. A conservative Jasper mail lift is +302.

Supporting changes in the same commit: `_download_rows` sleeps `page_delay_s` before each page (1.7 s on both new layers) and passes every attribute dict through `sensitive_fields.drop_sensitive`; a test pins that no configured layer maps a field that looks like an SSN, licence or birth date. `_tidy_mailing` turns Jasper's ten-digit `0`+ZIP5+ZIP4 and its `S C` state spelling back into a normal ZIP line. `resolve_layer_cfg` and `refresh_county` take an optional state; without one they behave exactly as before, so the weekly NC OneMap refresh of `beaufort_nc.sqlite` is unchanged. `scripts/refresh_parcel_cache.py Beaufort:SC` builds the SC file, and the default run now includes it. Tests: `tests/test_parcel_cache_new_sources_2026_10_07.py` (60, offline, invented values); all 40 test files that touch the parcel cache, the new one included, pass (1,090 tests).

To put it on the board (owner's call, VM): `scripts/apply_board_fixes.py --steps parcel,address,join --apply` as the only board process, after the weekly refresh has the two caches. Nothing in this work wrote the board.

Why these two: among OPEN sources not yet read, Beaufort is the only readable owner layer for any of the weakest 10 (Newberry's service is stopped, Kershaw's layer has no owner fields, the rest are walled), and Jasper (11th weakest) had the largest measurable parcel-id join of any open layer found. Dorchester would beat both on mail but carries a license clause, so it is ranked, not built.

## 4. Top 10 by lift for the weakest 10 counties

Ranked by rows in the 10 counties (15,870 rows) that would gain a missing contact or value field. Estimates marked guess rest on stated assumptions.

| # | Source | Access | Field gained | Rows gained (est.) | Basis | Cost |
|--:|---|---|---|--:|---|---|
| 1 | Tracerfy skip tracing | paid | phone | 9,500 to 11,900 | guess: 60-75% match on all 15,870 rows | $0.02 per hit, at most $317 |
| 2 | SCDOT statewide SC_Parcels MapServer | login | mail | up to 9,700 | guess: rows with a parcel id and no mail, if a token is granted and the layers carry mailing | free, needs a data-sharing request |
| 3 | Regrid nationwide parcel data | paid | mail, value | up to 9,700 | guess: same base, coverage unverified | price not verified |
| 4 | County assessor roll export by public records request | paid | mail, value | up to 8,395 | rows with a parcel id and no mail in 7 counties | copy fees (not verified) |
| 5 | qPayBill tax bill detail pages (Total Appraisal, Building Appraisal, Buildings, assessment ratio) | open | value | 6,000 to 6,900 | qPayBill rows at 0% value in 6 counties; detail page carries Total Appraisal | free, about 3 hours of polite requests |
| 6 | SC DES underground storage tank registry: facility Details page (Tank Owner Phone) | open | phone | about 3,125 | UST rows in the 10 counties; 30/30 phone fill in the repo sample | free; held by repo policy |
| 7 | Richland County SC data viewer API (GetParcelData, RCGeoGetParcelAtLatLon, RCGeoSearchData) | disclaimer-click | mail, sqft, beds, baths | 900 to 1,800 | guess: share of Richland rows whose parcel is the lead | free; viewer disclaimer |
| 8 | Dorchester County SC Parcels_Public | terms-only | mail, last sale | about 1,306 | board ids share the layer's TMS shape | free; license clause |
| 9 | Beaufort County SC EnerGov parcel layer | open | value, sale, mail | 705 value, 647 sale, 91 mail | MEASURED (built today) | free |
| 10 | Newberry County SC PropertyParcel MapServer | open | mail | up to 530 | rows with a parcel id and no mail, when the service runs | free |

Outside the weakest 10, the measured or near-certain levers are larger: the unapplied cache join (36,469 rows of mail), a cache schema change for year built/beds/baths (about 23,300 Gaston and 11,500 Transylvania year-built fills from layers already downloaded), and dedicated CAMA layers for Mecklenburg (6,800 parcel-id rows at 0.1% sqft), Wake (4,766), Onslow (1,178) and Cumberland (537).

## 5. Levers that need a decision, not a source

- **Cached mailing not yet joined: 36,469 rows.** Board rows with a parcel id and no owner mailing whose county parcel cache (data/parcel_cache) already holds a mailing for that parcel. The cache join (scripts/join_parcel_cache_to_board.py, or apply_board_fixes.py --steps join) has not been applied since the caches gained mailing. No new source needed. Top counties: NC:Gaston 15,899, NC:Transylvania 5,439, SC:Charleston 2,201, NC:Perquimans 1,518, NC:Onslow 1,087, SC:Horry 914, NC:Chowan 878, NC:Mecklenburg 726, NC:Forsyth 581, SC:Jasper 460, NC:McDowell 451, NC:Rutherford 426, NC:Bertie 418, SC:Greenville 370.
- **Cache schema drops facts the layers publish.** Already-downloaded layers publish year built, beds, baths, condition or grade in Gaston, Transylvania, Greenville, Lexington, Greenwood, Darlington, York, Barnwell, Saluda, McDowell and Chester; parcel_cache has no columns for them, so the weekly refresh drops them. One schema change unlocks about 23,000 Gaston and 11,000 Transylvania year-built fills. Build: add `year_built`, `beds`, `baths`, `condition` columns, map them per county, extend the join; about 8 hours with tests.
- **qPayBill detail pass is built but off** for the weak counties (`QPAYBILL_ROLL_DETAIL=1`). It is the only free value source for Williamsburg, Clarendon, Marlboro, Chesterfield, Edgefield and Newberry.
- **NC SoS terms.** sosnc.gov business registration page, 2026-10-07: 'Automated or scripted searches may degrade system performance and are not permitted. For bulk access to public data, please use our Data Subscription Services.' The repo's automated NC SoS entity lookups (enrichment_sos_agent, sos_agent hand-off) run against that stated term; the Master Files subscription ($750 setup + $2,000/yr) is the compliant route.
- **SC tank-registry phones.** SC DES UST registry detail pages carry Tank Owner Phone (30 of 30 in the repo's sample); sc_ust_registry.py fetches the list only, by policy. It is the largest free SC phone source found (about 3,125 rows in the weakest 10, mostly business lines). Owner decision, not code.
- **Dorchester license clause** and **Richland viewer disclaimer**: two owner calls that would open the 4th and 2nd largest counties of the weakest 10.
- **SC Code 30-2-50** still governs any outbound mail or calls built on SC assessor data, new or old (docs/sc_phone_research_2026-09-21.md section 4).

## 6. Sources by access class

| Access class | Count | Sources |
|---|--:|---|
| open | 50 | Jasper County SC parcel layer (city-hosted copy), Beaufort County SC EnerGov parcel layer, Newberry County SC PropertyParcel MapServer, Kershaw County Parcel Boundaries (Parcels_view), Jasper County Parcels (county ArcGIS Online org), Georgetown County SC GCGIS parcel data, Union County SC parcels (UNION_SC_PARCELS_WFL1), qPayBill tax bill detail pages (Total Appraisal, Building Appraisal, Buildings, assessment ratio), SC DES underground storage tank registry: facility Details page (Tank Owner Phone), SC RFA statewide geocoder (RFA_MultiRole GeocodeServer), SC state GIS server (gis.state.sc.us), Gaston parcel layer fields the cache does not keep, Transylvania parcel layer fields the cache does not keep, Greenville parcel layer fields the cache does not keep, Lexington parcel layer fields the cache does not keep, Greenwood parcel layer fields the cache does not keep, Darlington parcel layer fields the cache does not keep, York parcel layer fields the cache does not keep, Barnwell and Saluda parcel layer fields the cache does not keep, McDowell (NC) and Chester (SC) parcel layer fields the cache does not keep, Mecklenburg County TaxParcel_camadata, Wake County Property/Parcels MapServer, Cumberland County NC Tax/Parcels, Onslow County 'Parcels - Full Data', Guilford County GC_Parcels, Durham County Parcels (Town of Chapel Hill open data copy), Forsyth parcels (City of Winston-Salem Property2 layer 3), New Hanover County PropertyOwners, Wayne County NC appraisal data file, NC State Board of Elections voter file (statewide), FAA releasable airmen database download, FAA aircraft registry download (ReleasableAircraft.zip), IRS Exempt Organizations Business Master File (state extracts), SBA PPP loan-level FOIA data, FMCSA company census, NPPES NPI registry, FCC ULS amateur licence file, OpenStreetMap / Overture Places phone tags, NC 911 Board address points (NC OneMap), Overture Maps buildings (height, num_floors), Estate notices to creditors: personal representative name and address, HUD Small Area Fair Market Rents (ZIP level), Census ACS 5-year API (2024 release), Redfin Data Center, Realtor.com research data, FHFA house price index, County building-permit job values, Guilford County historical parcel snapshots (2016-2025), Wake County parcel address points, Charlotte Residential Parcel Revaluation and Tax Change |
| terms-only | 13 | Dorchester County SC Parcels_Public, SEC EDGAR company submissions API, Spokeo, Whitepages, That's Them, USPhoneBook, BeenVerified, FastPeopleSearch, FamilyTreeNow, Radaris, Legacy.com obituaries, Find a Grave, Echovita obituaries |
| disclaimer-click | 1 | Richland County SC data viewer API (GetParcelData, RCGeoGetParcelAtLatLon, RCGeoSearchData) |
| CAPTCHA | 1 | SC Secretary of State business filings search |
| login | 6 | SCDOT statewide SC_Parcels MapServer, Concealed handgun permit holders, NC DMV / SC DMV owner records, Municipal and county utility customer accounts, TLOxp, IDI idiCORE, LexisNexis Accurint, Tracers, HUD-USPS aggregated vacancy |
| paid | 31 | County assessor roll export by public records request, SC Election Commission voter list, NC Secretary of State Business Registration Master Files subscription, NC Secretary of State Federal Tax Lien data files, NC Secretary of State UCC data files, SC LLR licensee lists, NC court records remote public access (bulk/remote program), NC Wildlife Resources Commission boat registrations, SC DNR watercraft and outboard registrations, Twilio Lookup (line type, caller name, Identity Match), National Do Not Call Registry access, Tracerfy skip tracing, REISkip, BatchData property and skip-trace API, EnformionGO (formerly Endato) people/contact API, PropertyRadar, DealMachine, BatchLeads, Melissa address and identity APIs, Regrid nationwide parcel data, ReportAll USA parcel API, ATTOM property data API, RealEstateAPI.com property and skip-trace API, Skip Genie, DirectSkip, SkipForce, Data Axle consumer and business lists, SSA Death Master File (limited access), RentCast property and rent API, Rentometer, RSMeans Data Online, Craftsman National Construction Estimator 2026, NC Secretary of State Notary Public and Charitable Solicitation data files |
| bot-check | 14 | qPublic / Beacon county property sites (Schneider), Cherokee County SC parcels, NC Licensing Board for General Contractors licensee search, ATF federal firearms licensee listing, USDOT National Address Database, CyberBackgroundChecks, PeopleFinders, Intelius, ZabaSearch, TruePeopleSearch, SC probate index (southcarolinaprobate.net), Zillow research data (ZHVI, ZORI CSVs), Remodeling Cost vs Value report, OpenFEMA NFIP redacted claims |
| JS-app | 5 | WTH 'tgis' county map viewers, NC Real Estate Commission licensee search, NC Cash unclaimed property search, SC State Treasurer unclaimed property search, OpenAddresses |

## 7. Full catalog

Status: `no` = not ingested, `partial` = ingested in part, `yes` = ingested (two of them built today). Hours are build estimates. The JSON has fields, legal notes, coverage, manual steps and verification for every row.

| Source | Geography | Category | Access | Price | Ingested | Hours | Lift, weakest 10 | Lift elsewhere |
|---|---|---|---|---|---|--:|---|---|
| Tracerfy skip tracing | US | contact_commercial | paid | $0.02 per skip-trace hit (misses free); $0.10 per property record | partial | 2 | Phone +9,500 to +11,900 rows across the weakest 10 for at most $317 (guess) |  |
| SCDOT statewide SC_Parcels MapServer | SC statewide (one layer per county; Kershaw 27, Williamsburg 44, Clarendon 13, Chesterfield 12, Marlboro 33, Edgefield 18, Dillon 16, Newberry 35) | property_facts | login |  | partial | 4 | Up to +9,700 rows mail across the weakest 10 if a token is granted and the layers carry mailing (guess) |  |
| Regrid nationwide parcel data | US | property_facts | paid | not verified (pricing page carried no plain prices) | no | 6 | Up to +9,700 rows mail in the weakest 10 if Regrid carries these counties' owner mailing (guess) |  |
| County assessor roll export by public records request | SC: per county | contact_public_record | paid | Not verified: actual cost of the copy, usually small; varies by county | no | 4 | Up to +8,395 rows mail in 7 of the weakest 10 (guess) |  |
| qPayBill tax bill detail pages (Total Appraisal, Building Appraisal, Buildings, assessment ratio) | SC: 19+ counties incl. Williamsburg, Clarendon, Marlboro, Chesterfield, Edgefield, Newberry, Kershaw | valuation_input | open |  | partial | 1 | Value +6,000 to +6,900 rows in 6 of the weakest 10; no contact (guess) |  |
| SC DES underground storage tank registry: facility Details page (Tank Owner Phone) | SC statewide (46 counties) | contact_public_record | open |  | partial | 3 | Phone +3,125 rows in the weakest 10 (mostly business lines of tank owners) (guess) |  |
| Dorchester County SC Parcels_Public | SC: Dorchester | property_facts | terms-only |  | no | 1 | Dorchester: mail 0% -> about 75% (+1,306), plus last sale on the same rows (guess) |  |
| Richland County SC data viewer API (GetParcelData, RCGeoGetParcelAtLatLon, RCGeoSearchData) | SC: Richland | property_facts | disclaimer-click |  | no | 8 | Richland: mail and facts up to +900 to +1,800 rows (guess) |  |
| Beaufort County SC EnerGov parcel layer | SC: Beaufort | property_facts | open |  | yes | 4 | Beaufort SC: value 0.2% -> 41.6% (+702), last sale 0.1% -> 38.2% (+645), sqft 45.6% -> 49.6%, mail 0.2% -> 5.5% (+91) |  |
| Newberry County SC PropertyParcel MapServer | SC: Newberry | property_facts | open |  | no | 3 | Newberry: mail up to +530 rows when the service runs (guess) |  |
| Overture Maps buildings (height, num_floors) | US | property_facts | open |  | partial | 6 | +0 to +5 pts sqft estimate in the weakest 10 (guess) (guess) |  |
| Estate notices to creditors: personal representative name and address | NC, SC | contact_heir | open |  | yes |  | Small: Marlboro 63 estates a year via Column (guess) |  |
| FMCSA company census | US | contact_public_record | open |  | no | 4 | +0 to +0.3 pts phone (guess) |  |
| IRS Exempt Organizations Business Master File (state extracts) | NC, SC | contact_public_record | open |  | no | 3 | +0 to +50 rows mail (guess) (guess) |  |
| OpenStreetMap / Overture Places phone tags | US | contact_commercial | open |  | no | 6 | +0 to +0.3 pts (guess) |  |
| SBA PPP loan-level FOIA data | US | contact_public_record | open |  | no | 3 | +0 to +30 rows (guess) (guess) |  |
| FAA releasable airmen database download | US | contact_public_record | open |  | no | 3 | +0 to +20 rows mail (guess) (guess) |  |
| FAA aircraft registry download (ReleasableAircraft.zip) | US | contact_public_record | open |  | no | 3 | ~0 |  |
| FCC ULS amateur licence file | US | contact_public_record | open |  | no |  | 0 |  |
| NC State Board of Elections voter file (statewide) | NC statewide | contact_public_record | open |  | partial | 3 | 0 (SC) | NC non-footprint counties: phone up to +20 pts on owner-occupied rows (guess) |
| NPPES NPI registry | US | contact_public_record | open |  | no | 4 | ~0 |  |
| NC 911 Board address points (NC OneMap) | NC statewide | open_dataset | open |  | no | 4 | 0 (NC) (guess) |  |
| SC RFA statewide geocoder (RFA_MultiRole GeocodeServer) | SC statewide | open_dataset | open |  | no | 4 | Indirect: better points for the 2,229 Richland and 1,672 Beaufort address-only rows (guess) |  |
| SC state GIS server (gis.state.sc.us) | SC statewide | open_dataset | open |  | no | 0 | 0 |  |
| Wake County parcel address points | NC: Wake | open_dataset | open |  | no | 2 | 0 (NC) (guess) |  |
| Barnwell and Saluda parcel layer fields the cache does not keep | SC: Barnwell and Saluda | property_facts | open |  | partial | 8 | 0 (none of these counties is in the weakest 10) | Barnwell + Saluda: year/sqft/beds up to +1,500 |
| Cumberland County NC Tax/Parcels | NC: Cumberland | property_facts | open |  | no | 3 | 0 (NC) | Cumberland: +537 facts by id |
| Darlington parcel layer fields the cache does not keep | SC: Darlington | property_facts | open |  | partial | 8 | 0 (none of these counties is in the weakest 10) | Darlington SC: year/beds up to +2,514 |
| Durham County Parcels (Town of Chapel Hill open data copy) | NC: Durham | property_facts | open |  | no | 3 | 0 (NC) | Durham: values/mail |
| Forsyth parcels (City of Winston-Salem Property2 layer 3) | NC: Forsyth | property_facts | open |  | no | 2 | 0 (NC) | Forsyth: mail |
| Gaston parcel layer fields the cache does not keep | NC: Gaston | property_facts | open |  | partial | 8 | 0 (none of these counties is in the weakest 10) | Gaston: year built up to +23,301, last sale up to +16,167 |
| Georgetown County SC GCGIS parcel data | SC: Georgetown | property_facts | open |  | no | 3 | 0 (not in the weakest 10); Georgetown up to +355 mail by id plus address joins (guess) | Georgetown SC: up to +355 mail |
| Greenville parcel layer fields the cache does not keep | SC: Greenville | property_facts | open |  | partial | 8 | 0 (none of these counties is in the weakest 10) | Greenville SC: beds/baths/grade up to +3,300 |
| Greenwood parcel layer fields the cache does not keep | SC: Greenwood | property_facts | open |  | partial | 8 | 0 (none of these counties is in the weakest 10) | Greenwood SC: year/beds/condition up to +719 |
| Guilford County GC_Parcels | NC: Guilford | property_facts | open |  | no | 3 | 0 (NC) | Guilford: mail/situs for up to +998 by id |
| Jasper County Parcels (county ArcGIS Online org) | SC: Jasper | property_facts | open |  | no | 0 | 0 |  |
| Jasper County SC parcel layer (city-hosted copy) | SC: Jasper | property_facts | open |  | yes | 3 | 0 in the weakest 10 (Jasper is 11th); Jasper itself: mail 0.5% -> 48.6%, value 0% -> 51.4%, sale 0% -> 33.5% | Jasper SC: +476 mail, +508 value, +331 last sale (measured) |
| Kershaw County Parcel Boundaries (Parcels_view) | SC: Kershaw | property_facts | open |  | no | 0 | 0 |  |
| Lexington parcel layer fields the cache does not keep | SC: Lexington | property_facts | open |  | partial | 8 | 0 (none of these counties is in the weakest 10) | Lexington SC: year/beds/baths up to +1,477 |
| McDowell (NC) and Chester (SC) parcel layer fields the cache does not keep | NC/SC: McDowell (NC) and Chester (SC) | property_facts | open |  | partial | 8 | 0 (none of these counties is in the weakest 10) | McDowell: year built up to +2,875 |
| Mecklenburg County TaxParcel_camadata | NC: Mecklenburg | property_facts | open |  | partial | 4 | 0 (NC) | Mecklenburg: sqft/year/beds/sale up to +6,800 |
| Onslow County 'Parcels - Full Data' | NC: Onslow | property_facts | open |  | partial | 3 | 0 (NC) | Onslow: facts up to +1,178 |
| Transylvania parcel layer fields the cache does not keep | NC: Transylvania | property_facts | open |  | partial | 8 | 0 (none of these counties is in the weakest 10) | Transylvania: beds/baths up to +11,000 |
| Union County SC parcels (UNION_SC_PARCELS_WFL1) | SC: Union | property_facts | open |  | no | 3 | 0 (not in the weakest 10) | Union SC: up to +132 mail by id |
| Wake County Property/Parcels MapServer | NC: Wake | property_facts | open |  | no | 3 | 0 (NC) | Wake: sqft/year/sale up to +4,766 |
| Wayne County NC appraisal data file | NC: Wayne | property_facts | open |  | no |  | 0 (NC) (guess) |  |
| York parcel layer fields the cache does not keep | SC: York | property_facts | open |  | partial | 8 | 0 (none of these counties is in the weakest 10) | York SC: small |
| County building-permit job values | NC, SC | repair_cost | open |  | yes |  | Already in |  |
| Guilford County historical parcel snapshots (2016-2025) | NC: Guilford | sale_transfer | open |  | no | 4 | 0 (NC) (guess) | Guilford: tenure/prior-owner signal |
| New Hanover County PropertyOwners | NC: New Hanover | sale_transfer | open |  | no | 3 | 0 (NC) | New Hanover: last sale up to +3,476 |
| Census ACS 5-year API (2024 release) | US | valuation_input | open |  | yes |  | Already in |  |
| Charlotte Residential Parcel Revaluation and Tax Change | NC: Mecklenburg (Charlotte) | valuation_input | open |  | no | 2 | 0 (NC) |  |
| FHFA house price index | US | valuation_input | open |  | yes |  | Already in |  |
| HUD Small Area Fair Market Rents (ZIP level) | US | valuation_input | open |  | partial | 3 | Rent estimate precision in all 10 counties (guess) |  |
| Realtor.com research data | US | valuation_input | open |  | yes |  | Already in |  |
| Redfin Data Center | US | valuation_input | open |  | yes |  | Already in |  |
| BeenVerified | US | contact_commercial | terms-only |  | no |  | 0 (excluded) |  |
| FamilyTreeNow | US | contact_commercial | terms-only |  | no |  | 0 (excluded) |  |
| FastPeopleSearch | US | contact_commercial | terms-only |  | no |  | 0 (excluded) |  |
| Radaris | US | contact_commercial | terms-only |  | no |  | 0 (excluded) |  |
| Spokeo | US | contact_commercial | terms-only |  | no |  | 0 (excluded) |  |
| That's Them | US | contact_commercial | terms-only |  | no |  | 0 (excluded) |  |
| USPhoneBook | US | contact_commercial | terms-only |  | no |  | 0 (excluded) |  |
| Whitepages | US | contact_commercial | terms-only |  | no |  | 0 (excluded) |  |
| Echovita obituaries | US | contact_heir | terms-only |  | no | 4 | 0 contact (guess) |  |
| Find a Grave | US | contact_heir | terms-only |  | no |  | 0 contact (guess) |  |
| Legacy.com obituaries | US | contact_heir | terms-only |  | no |  | 0 contact (names only) |  |
| SEC EDGAR company submissions API | US | contact_public_record | terms-only |  | no | 2 | ~0 |  |
| NC Cash unclaimed property search | NC statewide | contact_heir | JS-app |  | no |  | 0 |  |
| SC State Treasurer unclaimed property search | SC statewide | contact_heir | JS-app |  | no |  | 0 |  |
| NC Real Estate Commission licensee search | NC statewide | contact_public_record | JS-app |  | no |  | 0 |  |
| OpenAddresses | US | open_dataset | JS-app |  | no | 4 | 0 |  |
| WTH 'tgis' county map viewers | SC: Williamsburg, Marlboro, Chesterfield, Dillon, McCormick, Marion | property_facts | JS-app |  | no |  | 0 automated; manual card lookups only |  |
| TLOxp, IDI idiCORE, LexisNexis Accurint, Tracers | US | contact_commercial | login | subscription after credentialing (not verified) | no |  | Highest match rates and heir relatives, if the business qualifies (guess) |  |
| Concealed handgun permit holders | NC, SC | contact_public_record | login |  | no |  | 0 |  |
| Municipal and county utility customer accounts | NC, SC | contact_public_record | login |  | no |  | 0 |  |
| NC DMV / SC DMV owner records | NC, SC | contact_public_record | login |  | no |  | 0 |  |
| HUD-USPS aggregated vacancy | US | valuation_input | login | free with a HUD USER account | yes |  | Already in |  |
| SC Secretary of State business filings search | SC statewide | contact_public_record | CAPTCHA |  | no |  | 0 |  |
| CyberBackgroundChecks | US | contact_commercial | bot-check |  | no |  | 0 (excluded) |  |
| Intelius | US | contact_commercial | bot-check |  | no |  | 0 (excluded) |  |
| PeopleFinders | US | contact_commercial | bot-check |  | no |  | 0 (excluded) |  |
| TruePeopleSearch | US | contact_commercial | bot-check |  | no |  | 0 (excluded) |  |
| ZabaSearch | US | contact_commercial | bot-check |  | no |  | 0 (excluded) |  |
| SC probate index (southcarolinaprobate.net) | SC | contact_heir | bot-check |  | partial |  | 0 contact |  |
| ATF federal firearms licensee listing | US | contact_public_record | bot-check |  | no |  | ~0 |  |
| NC Licensing Board for General Contractors licensee search | NC statewide | contact_public_record | bot-check |  | no |  | 0 |  |
| USDOT National Address Database | US | open_dataset | bot-check |  | no |  | 0 |  |
| Cherokee County SC parcels | SC: Cherokee | property_facts | bot-check |  | no |  | 0 (not in the weakest 10) | Cherokee SC: up to +1,646 mail by a roll file |
| qPublic / Beacon county property sites (Schneider) | SC: about 30 counties | property_facts | bot-check |  | no |  | 0 automated |  |
| Remodeling Cost vs Value report | US regions | repair_cost | bot-check |  | no | 2 | Rough ARV uplift per project (guess) |  |
| OpenFEMA NFIP redacted claims | US | valuation_input | bot-check |  | partial |  | Condition/flood context (guess) |  |
| Zillow research data (ZHVI, ZORI CSVs) | US | valuation_input | bot-check |  | no | 2 | ZIP-level value/rent trend (guess) |  |
| BatchData property and skip-trace API | US | contact_commercial | paid | Growth $1,000/mo for 100,000 records; Professional $2,500/mo 300,000; Scale $5,000/mo 750,000; Enterprise $10,000/mo | no | 4 | Phone, as Tracerfy (guess) |  |
| BatchLeads | US | contact_commercial | paid | Growth $119/mo; Professional $349/mo; Scale $749/mo | no |  | Operator export (guess) |  |
| Data Axle consumer and business lists | US | contact_commercial | paid | not verified | no |  | Unknown (guess) |  |
| DealMachine | US | contact_commercial | paid | Basic $99/seat/mo (10,000 data credits); Pro $149/seat/mo (20,000) | no |  | Operator export (guess) |  |
| EnformionGO (formerly Endato) people/contact API | US | contact_commercial | paid | Starter from $0.25 per match (up to 5,000 searches); Pro as low as $0.01 per match | no | 4 | Phone, as Tracerfy (guess) |  |
| Melissa address and identity APIs | US | contact_commercial | paid | Address: pay-as-you-go from $40 for 10,000 credits (10 credits/address); free 250 records/month | partial | 2 | 0 coverage; mail deliverability |  |
| National Do Not Call Registry access | US | contact_commercial | paid | per-area-code annual fee (not verified today) | partial |  | 0 |  |
| PropertyRadar | US | contact_commercial | paid | Solo $119/mo ($99 annual); team $249/mo ($199 annual) | no |  | Phone/mail by export (guess) |  |
| REISkip | US | contact_commercial | paid | $0.15 per match (introductory; minimum 50) | no | 1 | Same rows as Tracerfy at 7.5x the price (guess) |  |
| RealEstateAPI.com property and skip-trace API | US | contact_commercial | paid | not verified (prices rendered by JavaScript) | no | 4 | As Tracerfy (guess) (guess) |  |
| Skip Genie, DirectSkip, SkipForce | US | contact_commercial | paid | not verified (404, 404, TLS error on the pricing URLs tried) | no |  | As Tracerfy (guess) |  |
| Twilio Lookup (line type, caller name, Identity Match) | US | contact_commercial | paid | $0.01 per request for one US-only package; Identity Match $0.10 per request; tiered $0.02 to $0.003 for another package by volume | partial | 4 | 0 new phones; verifies existing ones |  |
| SSA Death Master File (limited access) | US | contact_heir | paid | certified subscriber fee (not verified) | no |  | 0 contact |  |
| NC Secretary of State Business Registration Master Files subscription | NC statewide | contact_public_record | paid | $750 one-time setup + $2,000 per state fiscal year | no | 6 | 0 (NC) | NC entity-owned rows: registered agent/officer contact for all, without scripted searches |
| NC Secretary of State Federal Tax Lien data files | NC statewide | contact_public_record | paid | $1,600 per year (no images), plus the $750 setup | no | 4 | 0 (NC) (guess) |  |
| NC Secretary of State Notary Public and Charitable Solicitation data files | NC statewide | contact_public_record | paid | $2,400 per year each (no images), plus the $750 setup | no |  | ~0 |  |
| NC Secretary of State UCC data files | NC statewide | contact_public_record | paid | $4,000 per year (no images); images $5,200 per year | no | 4 | 0 (NC) (guess) |  |
| NC Wildlife Resources Commission boat registrations | NC statewide | contact_public_record | paid | not verified (records request) | no |  | ~0 |  |
| NC court records remote public access (bulk/remote program) | NC statewide | contact_public_record | paid | not verified | no |  | 0 (NC) (guess) |  |
| SC DNR watercraft and outboard registrations | SC statewide | contact_public_record | paid | not verified | no |  | ~0 |  |
| SC Election Commission voter list | SC statewide | contact_public_record | paid | $25 to $2,500 | no |  | 0 phone; mail already comes from the roll |  |
| SC LLR licensee lists | SC statewide | contact_public_record | paid | $10 per board list by mailed check | no |  | 0 |  |
| ATTOM property data API | US | property_facts | paid | not verified (enterprise) | no | 6 | As Regrid (guess) (guess) |  |
| ReportAll USA parcel API | US | property_facts | paid | not verified | no | 6 | As Regrid (guess) (guess) |  |
| Craftsman National Construction Estimator 2026 | US | repair_cost | paid | $117.50 paperback; $58.75 PDF; cloud $13.99/mo or $167.88/yr | no | 4 | Repair-cost table for the rehab estimate (guess) |  |
| RSMeans Data Online | US (city cost indexes) | repair_cost | paid | Core from $408/yr; Complete from $1,049/yr; Complete Plus from $5,973/yr | no | 6 | Repair-cost precision (guess) |  |
| RentCast property and rent API | US | valuation_input | paid | Developer $0 (50 requests/mo); Foundation $74/mo (1,000); Growth $199/mo (5,000); Scale $449/mo (25,000); overage $0.20 to $0.015 per request | partial | 4 | Rent and sale comps for HOT leads in the weakest 10 (guess) |  |
| Rentometer | US | valuation_input | paid | Basic $59/yr (10 estimates); Essential $16/mo or $96/yr (unlimited estimates, 3 reports) | no |  | Manual rent checks (guess) |  |

## 8. What a person does by hand for the walled ones

- **Dorchester County SC Parcels_Public** (terms-only): Owner decision on the license clause, then add the ready config (one dict) and run refresh_parcel_cache.py Dorchester.
- **Richland County SC data viewer API (GetParcelData, RCGeoGetParcelAtLatLon, RCGeoSearchData)** (disclaimer-click): Open richlandmaps.com/apps/dataviewer, accept the disclaimer, search the address, read owner and mailing off the parcel dialog.
- **WTH 'tgis' county map viewers** (JS-app): Open the county's wthgis.com viewer, search the TMS from the board row, copy owner and mailing.
- **qPublic / Beacon county property sites (Schneider)** (bot-check): Open qpublic.schneidercorp.com in a browser, pick the county, search the parcel id, read owner, mailing and the building card.
- **SCDOT statewide SC_Parcels MapServer** (login): Email SCDOT GIS (the layer owner) asking for read access for parcel attributes under a data-sharing agreement; if granted, store the token as an environment secret.
- **County assessor roll export by public records request** (paid): Send each assessor a written FOIA request for the current real-property roll (TMS, owner, mailing address, values) as CSV; pay the copy fee; drop the file in data/ and load it with a sc_parcel_mailing-style reader.
- **Cherokee County SC parcels** (bot-check): Records request for the roll, or qPublic by hand.
- **NC Secretary of State Business Registration Master Files subscription** (paid): Email the SoS data-subscription contact, sign the contract, pay $2,750 for year one, load the file.
- **SC Secretary of State business filings search** (CAPTCHA): Search the entity by hand in a browser.
- **NC Licensing Board for General Contractors licensee search** (bot-check): Look the builder up by hand.
- **SC LLR licensee lists** (paid): Mail the request form with a check.
- **NC court records remote public access (bulk/remote program)** (paid): Ask NCAOC about the current remote/bulk data program and its licence.
- **NC Cash unclaimed property search** (JS-app): Search an owner or estate name by hand; unclaimed funds in an estate name hint at heirs.
- **SC State Treasurer unclaimed property search** (JS-app): Search by hand.
- **ATF federal firearms licensee listing** (bot-check): Download the monthly file in a browser.
- **NC Wildlife Resources Commission boat registrations** (paid): File a records request.
- **SC DNR watercraft and outboard registrations** (paid): File a records request.
- **USDOT National Address Database** (bot-check): Download in a browser.
- **Tracerfy skip tracing** (paid): Export the rows, upload to Tracerfy, import the result through contact_ingest.
- **PropertyRadar** (paid): Operator export lane.
- **DealMachine** (paid): Operator export lane.
- **BatchLeads** (paid): Operator export lane.
- **Regrid nationwide parcel data** (paid): Buy a county or state extract; load it like an assessor roll.
- **TLOxp, IDI idiCORE, LexisNexis Accurint, Tracers** (login): Apply for an account; credentialing is a business decision.
- **Legacy.com obituaries** (terms-only): Read by hand.
- **Find a Grave** (terms-only): Read by hand.
- **SC probate index (southcarolinaprobate.net)** (bot-check): Search by hand.
- **Zillow research data (ZHVI, ZORI CSVs)** (bot-check): Download the CSVs in a browser and drop them in data/.
- **Rentometer** (paid): Operator checks rent for HOT leads.
- **Remodeling Cost vs Value report** (bot-check): Download the South Atlantic report by hand.
- **People-search sites** (13 classified from robots.txt or a challenge page only, none searched): excluded by the repo compliance rule; a person may look a name up in their own browser and enter the result through the skip-trace worksheet.

## 9. What could not be determined

- Prices for Regrid, ReportAll, ATTOM, RealEstateAPI, Skip Genie, DirectSkip, SkipForce, the credentialed aggregators, Data Axle, the National DNC fee and the NCAOC remote-access program (pages without plain prices, 404s, a TLS error, or not fetched).
- Whether Regrid or the token-walled SCDOT layers carry owner mailing for the walled SC counties today, and what an SC FOIA roll request costs per county.
- SC match rates for any skip-trace vendor (the 60-75% range is an assumption; a 25-lead pilot settles it for about $0.50).
- Field content of Richland's parcel API (field names read from its JavaScript, no record requested), Newberry's stopped service, Guilford's historical snapshots and Wake's address points.
- Whether Wayne County NC still publishes its appraisal file (no link on the county home page; search budget spent).
- FAA aircraft file size (HEAD 503), the ATF list, USDOT NAD, Zillow research, Cost vs Value and FEMA claims pages (bot checks on a plain GET).
- Legal: whether a cash offer to buy a house is commercial solicitation under SC Code 30-2-50; the public-records status of NC and SC boat registrations; SC's rule for concealed-carry lists. These need counsel, not a fetch.
- Jasper's 276 board ids with a letter suffix (likely sub-accounts or mobile homes) have no match in the layer; whether the county keys them elsewhere is unknown.

## 10. Limits

- The Jasper layer is a city's copy last edited 2025-08-12; owners and mailing can trail the county roll by a year. Its values pass the cache's 10-day freshness gate because the gate reads the file date, not the data date.
- Lift estimates outside the two builds are arithmetic on board counts times an assumed hit rate; each is marked as a guess in the JSON.
- Board numbers are from the published board of 2026-10-07 and move with every run.

## 11. Update, later on 2026-10-07: what landed and the re-measured lift

Five changes, each committed locally (pathspec commits, nothing pushed, nothing written to the board). Every figure below is a count from one read-only streaming pass of the 350,013-row board (`scripts/measure_cache_facts_lift.py`), unless marked as a projection.

**1. The cache join now runs over every row in a normal pipeline run.** The 36,469 rows (36,638 on the board re-read this evening) had a parcel id and no mailing while their cache held one because `enrich_gis_attrs` read the cache only inside its per-lead coroutine: behind the "core attrs complete" skip gate (11,436 of the gap rows returned before the lookup), behind the batch loop that the 2,400 s `RESOLVER_PHASE_MAX_SECONDS` cap stops part way through a 350k-row board (the other 25,033 rows never reached the lookup; most were added by scoped ingests after the last full run), and writing only `raw["gis"]["mailing"]`, never the canonical `raw["owner_mailing"]` block. Fix: one shared, fill-only join (`src/foreclosure_scraper/parcel_cache_join.py`: overage rows skipped, over-shared parcel ids refused, dual-state names need a state, the mailing withheld when the address resolver said the parcel's owner differs) that `enrich_gis_attrs` runs over every listing before its live loop; `scripts/join_parcel_cache_to_board.py` uses the same code plus its numbered-situs rule. **No main.py change is needed** (main already calls `enrich_gis_attrs`); `FORECLOSURE_CACHE_JOIN=0` turns it off. Bounded proof (`scripts/prove_cache_join_prepass.py`, 5,000 gap rows from 51 counties): mail 0 -> 3,694; the other 1,306 were withheld by the owner-differs rule. Board-wide, the join fills **owner mailing on 35,512 rows** (NC Gaston 15,641, Transylvania 5,439, SC Charleston 1,932, NC Perquimans 1,518, Onslow 1,087, Chowan 878, SC Dorchester 841, NC Mecklenburg 726, Forsyth 581, SC Jasper 460), last sale on 3,958 and county value on 997. It lands on the board at the next full pipeline run, or sooner with `scripts/apply_board_fixes.py --steps join --apply` as the only board process (owner's call, VM).

**2. Fact columns.** `parcel_cache` gained `year_built`, `bedrooms`, `bathrooms`, `stories` (the table DDL is now built from `_COLS`), a `{"baths": [full, half]}` spec (a half bath counts 0.5), `FACT_MAPS` for the eleven already-downloaded layers whose field names were verified live today (Gaston, McDowell, Spartanburg, Darlington, Greenville, York, Lexington, Greenwood, Barnwell, Saluda, Chester; Gaston and McDowell also gain last sale), and `structyear` -> year built on the NC OneMap fallback (every NC county it serves). Migration: a cache file written before the columns existed stays readable (columns are read per file); `parcel_cache.ensure_columns()` adds them in place for a writer. Measured after refreshing Gaston and Transylvania today: Gaston year built **+1,653**, bedrooms +1,345, bathrooms +1,346, last sale +1,221; Transylvania year built +128. The earlier "about 23,300 Gaston year-built fills" counted every Gaston row without a year; most Gaston board rows are vacant land from `gaston_vacant`, which has no building. The other nine layers and every OneMap county fill at the next weekly refresh.

**3. Dorchester SC parcel layer**, built on the owner's decision. The licence wording ("not to be added to any pay for use locations without prior written approval of Dorchester County Assessor or GIS Director") is kept beside the config in `parcel_cache.py`: the board is free and public; putting it behind a paywall would need that approval first. 80,311 parcels cached. Measured: mail **0 -> 841 of 1,735 rows (48.5%)**, last sale 0 -> 616 (1,306 rows carry a parcel id; 841 hit). It also supplies a mailing for all 17 Dorchester rows of the 249 big-old tax rows with no contact.

**4. Richland SC map-viewer reader** (`src/foreclosure_scraper/enrichment_richland_parcel.py`), built on the owner's decision (the viewer's disclaimer is a click-through). Per row: the viewer's address search (high-confidence hit, same house number and street words) then its parcel-at-point call; fills TMS, owner, owner mailing, value, heated sqft, beds, baths, year built, acreage, last sale. OptedOut owners keep name and mailing off; a different owner name withholds the mailing. One request at a time, 1.7 s apart, 300 rows per run, 30-day retry. Bounded live proof on 12 board rows: 9 matched, 9 mailing fills. 2,028 of the 2,229 Richland rows are eligible; at the proof rate that is **about 1,500 rows of mail (projection)** over seven capped runs. **main.py wiring (for the coordinator), right after the `enrich_gis_attrs` block (main.py, the `# CAMA per-parcel condition` comment is the next block):**

```python
    try:
        from .enrichment_richland_parcel import enrich_richland_parcel
        s = await asyncio.wait_for(
            enrich_richland_parcel(enriched),
            timeout=float(os.environ.get("RESOLVER_PHASE_MAX_SECONDS", "2400")))
        if s:
            enrichment_stats["richland_parcel"] = s
    except asyncio.TimeoutError:
        log.warning("richland_parcel.time_capped")
    except Exception:
        log.error("richland_parcel.failed", traceback=traceback.format_exc())
```

**5. County roll loader** for the records-request files: `scripts/ingest_county_roll.py --county <name> --state SC|NC --file <path> [--file ...] [--map <json>] [--dry-run] [--report]` (code in `src/foreclosure_scraper/county_roll.py`). Reads CSV, TSV, pipe or semicolon text, fixed-width text (layout from the mapping JSON or inferred from the header), .xlsx and a .zip holding one of those; legacy .xls is refused with a save-as instruction. Every SSN, licence or birth-date column is dropped before any value is read (`sensitive_fields.is_sensitive_field` now treats spaces, dots and hyphens as underscores, so "DATE OF BIRTH" is caught). Auto-detects parcel/TMS/PIN/REID/account/bill ids (all of them become keys, which is the crosswalk Hyde, Washington and Perquimans need), owner, mailing parts, situs, land use, market and assessed value, acreage, sqft, year built, beds, baths, stories, last sale. It writes a SIDECAR, `data/parcel_cache/<county>.roll.sqlite`, with provenance `county_roll_request` and the file's date: the weekly layer refresh cannot wipe it, and `parcel_cache.lookup` lets it fill only what the layer cache lacks (Beaufort SC merges with `beaufort_sc.sqlite` instead of replacing it). Roll values are handed out for 400 days after the file date; owner and mailing without a limit. Re-running the same file gives the same sidecar. Synthetic proof on the real board (made-up owners keyed by the 15 real Kershaw parcel ids of the 249 list, written to a scratch cache dir): mail, value and year built 0 -> 15 each. Tests: one fixture per format.

### The weakest 10, re-measured

| County | Rows | Parcel-id rows | Mail before | Mail after (measured) | What moves it next |
|---|--:|--:|--:|--:|---|
| Williamsburg SC | 2,476 | 2,252 | 0 | 0 | roll request (2,252 rows join by id the day it lands) |
| Richland SC | 2,229 | 4 | 0 | 0 (about 1,500 projected) | wire `enrich_richland_parcel` into main.py |
| Dorchester SC | 1,735 | 1,306 | 0 | **841 (48.5%)** | done; roll request for the 465 misses |
| Clarendon SC | 1,649 | 1,424 | 0 | 0 | roll request |
| Chesterfield SC | 1,011 | 725 | 0 | 0 | roll request |
| Newberry SC | 977 | 530 | 0 | 0 | roll request (county layer service stopped) |
| Edgefield SC | 921 | 750 | 0 | 0 | roll request |
| Marlboro SC | 1,250 | 1,023 | 3 | 3 | roll request |
| Beaufort SC | 1,695 | 25 | 3 | 28 by id (94 with the address resolver, section 3) | roll request merges with the layer |
| Kershaw SC | 1,927 | 1,697 | 4 | 4 | roll request (its open layer has no owner) |

Next tier: Jasper SC 5 -> 465 by id (built earlier today); Hyde NC 538 parcel-id rows, 34 cache hits, none with a new mailing (the roll's account/REID columns are the crosswalk); Washington NC 6 parcel-id rows. Year-built, bedroom and bathroom fills in these counties stay at 0 until a roll lands: none of them has a layer that publishes them.
