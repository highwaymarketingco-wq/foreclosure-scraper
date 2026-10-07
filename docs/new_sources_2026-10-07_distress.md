# New distress sources, NC and SC, 2026-10-07

Every public source found on 2026-10-07 that shows a property is distressed, vacant, neglected or about to change hands, for every NC and SC county and every municipality of 5,000 people or more. Walled sources (CAPTCHA, login, paywall, bot check, terms) are recorded with what a person does by hand; none was solved or bypassed. Machine-readable twin: `docs/new_sources_2026-10-07_distress.json` (every record, the full grid, and the 249-row unlock counts). Companion doc from a parallel session the same day: `docs/new_sources_2026-10-07_liens_courts.md` (liens and court filings); overlaps are marked there, not counted twice.

Public repo: no owner names, phone numbers or private addresses appear here. Field names, counts and URLs only.

## 1. Totals

- Source records: **304**. New (not ingested by any module and not in an earlier doc): **216**.
- By access class, all records: open 207, bot-check 30, absent 24, JS-app 15, public-records-request 12, login 6, terms-only 4, disclaimer-click 4, CAPTCHA 1, paid 1.
- By access class, new records: open 141, bot-check 25, absent 22, public-records-request 10, JS-app 10, login 3, terms-only 2, disclaimer-click 2, paid 1.
- By category: tax_sale 63, code_enforcement 55, delinquent_tax 40, county_surplus 34, condemned_demolition_unsafe 30, building_permits 16, auction 12, vacant_registry 8, sheriff_or_mie_sale 8, str_registration 7, eviction 7, fire_incident 6, flood_storm_damage 4, utility_shutoff 3, absentee_owner 2, municipal_tax_or_fee_lien 2, other 2, land_bank 2, probate 1, usps_vacancy 1, hoa 1.

Coverage grid (section 5): agol_none 1199, not_checked 607, none_found 586, built 337, open 276, walled 215, absent 23 cells over 146 counties and 213 municipalities.

How the search ran:
- ArcGIS Online item search over the NC/SC extent for 45 distress terms (5,584 items, 949 inside NC/SC, 556 distress-titled), then ?f=json + returnCountOnly probes on 100 candidate layers
- research subagents reading city/county sites and REST roots directly: NC 102 towns, SC 66 cities + county code programs, NC 100 counties (tax/surplus/sheriff), SC 46 counties (tax sale/MIE/sheriff/surplus); the NC 45-largest-cities pass was still running when this doc was written, so those cities rest on the ArcGIS sweep and earlier repo work (grid codes n / -)
- statewide lanes checked by the lead agent (evictions, fire, flood, USPS, utilities, HOA, sheriff, auctions)
- polite: >= 1.6 s between requests to one host, ordinary browser UA, <= 4 requests per source; no CAPTCHA, login, paywall, WAF or bot check touched

## 2. Built today (four scrapers, tests, bounded live proof)

| Module | Source | Rows on the live run (counts only) | Signal written | Why it ranked |
|---|---|---|---|---|
| `counties_sc.york_tax_sale_parcels` | York County SC 'Tax Sale Properties 2026 View' ArcGIS layer | 853 parcels, all dated sale 2026-10-12; 791 with situs; 508 absentee, 121 out-of-state owners; 330 vacant lots | TAX_SALE (sale_date set; SC 12-month redemption keeps it active), raw owner_mailing, vacant_lot | Largest fresh, dated, open list not read; York had 0 tax-sale rows because the county site is Cloudflare-walled |
| `counties_nc.rocky_mount_blight_survey` | Rocky Mount 2025 condition survey, 6 ArcGIS layers (Nash + Edgecombe) | 651 layer rows folded to 618 parcels: 216 dilapidated, 211 deteriorated, 224 vacant+boarded; 564 absentee, 137 out-of-state | DISTRESSED; raw condemned (dilapidated), distressed (deteriorated), vacancy boarded_up, owner_mailing | Physical distress + owner mailing on every row, two counties with almost no property-condition signal |
| `city_websites.raleigh_structure_fires` | Raleigh Open Data fire incidents (daily) | 397 addresses / 411 building-fire incidents in the last 730 days | DISTRESSED, raw fire_incident + distressed; address only (resolver adds owner) | First fire-damage source in the repo; live daily feed in the largest NC city without one |
| `counties_nc.kinston_proposed_demolition` | Kinston 2026 proposed demolition ArcGIS layer | 45 parcels, all with situs; 41 absentee, 9 out-of-state; 2 with utility cut-offs, 2 heirs property | DISTRESSED, raw condemned, utility_cutoff + vacancy (when cut), heir_property, owner_mailing | Strongest per-row signal found (city demolition list) and the only published utility cut-off flags |

Rows ship under `counties_sc.york_tax_sale_parcels` (dated) and the `counties_generic.arcgis_distress.` prefix (dateless; already whitelisted in `main.DATELESS_OK_SOURCES`, so `main.py` was not touched). Every attribute bag passes `sensitive_fields.drop_sensitive`; outFields are explicit. New raw keys are registered in `web_artifact.RAW_KEEP`. Tests: `tests/test_new_sources_2026_10_07.py` (27, hand-written fixtures, made-up names). The Mecklenburg and Guilford tax-foreclosure layers ranked higher but were built the same day by a parallel session (`mecklenburg_tax_foreclosures`, `guilford_tax_foreclosures`). Rowan and Cumberland delinquent lists rank above Kinston by volume but are dateless non-ArcGIS lists: their rows would be dropped by `main._active_only` until a one-line `DATELESS_OK_SOURCES` entry is added, and `main.py` was off-limits for this task.

## 3. Top 10 by value

Value = net-new distressed rows the source would put on the board, weighted by how strong and how fresh the signal is. Rows are measured counts from 2026-10-07 unless marked as estimates.

| # | Source | Where | Rows / signals | Access | Status | Build effort | Why |
|---|---|---|---|---|---|---|---|
| 1 | Charleston County EnerGov history: code cases + demolition permits | Charleston County SC | 3,899 code cases (1,871 Building Services) + ~3,200 demolition permits in 386,386 rows, updated daily | open | not built | 6 h (no address field: join points to the parcel layer by location) | Largest live code/demolition feed found in SC; Charleston has 6,457 board rows and no code signal |
| 2 | York County SC 2026 tax sale layer | York County SC | 853 parcels, sale 2026-10-12 | open | BUILT today (york_tax_sale_parcels) | done | Dated, imminent transfer; county site is Cloudflare-walled so the layer is the only open route |
| 3 | Rocky Mount 2025 condition survey | Nash + Edgecombe NC | 618 parcels (216 dilapidated, 224 vacant+boarded, 211 deteriorated) | open | BUILT today (rocky_mount_blight_survey) | done | Physical distress plus owner mailing on every row |
| 4 | NC annual tax-lien advertisements not yet read (Hoke, Lee, Davidson, Randolph; also Davie, Pasquotank, Martin) | 7 NC counties | about 11,500 bills (Hoke ~2,780, Lee ~2,740, Davidson ~3,000, Randolph ~3,000; estimates from file sizes/first pages) | open | not built | 2-3 h each as config in nc_county_pdf_delinquent_tax | Same shape the repo already parses; fills counties with no tax rows |
| 5 | Cumberland County 2025 delinquent real estate list | Cumberland County NC | 3,755 bills | open | not built | 3 h (PDF) + one DATELESS_OK_SOURCES line in main.py | Fayetteville area; ptscloud tenant returns no export |
| 6 | Rowan County delinquent taxpayer XLSX (2019-2025) | Rowan County NC | 2,699 real-estate bills in the 2025 file (6,542 total), 117 heirs + 56 estate owner types, 7 years of history | open | not built | 3 h + one DATELESS_OK_SOURCES line in main.py | Balance, parcel, owner mailing and repeat-year history in one file |
| 7 | Mecklenburg TaxCollections 'Back Bills' layer | Mecklenburg County NC | 93,916 unpaid prior-year bills (+18,468 '2024 Bills'); real-estate share not measured | open | not built | 4 h | Biggest single roll found; overlaps in part with the advertisement workbooks a parallel session built today |
| 8 | Iredell DelinquentTaxes map layer | Iredell County NC | 2,391 parcels, as-of 2026-10-06 (weekly) | open | not built | 4 h (geometry only: spatial join to parcels) | Overturns the earlier 'no Iredell delinquent feed' note |
| 9 | Sumter vacant registries (county VacantPropertyPoint + City of Sumter registry) | Sumter County SC | 3,385 points with condition code (2023) + 1,168 registry rows, 1,027 vacant (2020) | open | not built | 2 h | Large vacancy backfill; must exclude the registry's phone/email columns; age needs a spot check |
| 10 | Raleigh structure fires | Raleigh, Wake County NC | ~200 burned buildings a year (397 addresses / 2 years) | open | BUILT today (raleigh_structure_fires) | done | First fire-damage signal in the repo, daily feed |

## 4. Walled and absent sources: what a person does by hand

| Source | Where | Wall | Evidence | Manual step |
|---|---|---|---|---|
| Kinston heirs-property layer | Kinston, Lenoir, NC | login | ArcGIS Online item search (45 distress terms, NC/SC extent, 2026-10-07) then layer ?f=json + returnCountOnly; 499 Token Required | Ask the City of Kinston for the heirs-property list (layer answers 499 Token Required). |
| Salisbury chronic abatement layer | Salisbury, Rowan, NC | login | ArcGIS Online item search (45 distress terms, NC/SC extent, 2026-10-07) then layer ?f=json + returnCountOnly; 499 Token Required | Request the chronic-abatement list from Salisbury code services (layer answers 499 Token Required). |
| Iredell County delinquent taxes layer | Iredell, NC | absent | ArcGIS Online item search (45 distress terms, NC/SC extent, 2026-10-07) then layer ?f=json + returnCountOnly; old service answers HTTP 500 | Old host only: the live layer is maps.iredellcountync.gov/server/rest/services/Data/DelinquentTaxes/MapServer/0 (2,391 parcels, see its own record). |
| Craven County foreclosure parcels layer | Craven, NC | absent | ArcGIS Online item search (45 distress terms, NC/SC extent, 2026-10-07) then layer ?f=json + returnCountOnly; 404 Service not found | Check the Craven tax office foreclosure page by hand. |
| Dorchester County parcel layer (owner + mailing, open, licence clause) | Dorchester, SC | terms-only | 2026-10-07: FULL_TMS IN (17 target TMS) returnCountOnly = 17, all with MAILING_ADDRESS | Owner decision: the service licence says 'not to be added to any pay for use locations without prior written approval'; ask the Dorchester GIS Director for approval, then add the PARCEL_LAYERS entry … |
| NERIS Public Incident Basics | national, US | terms-only | Item 241c7985c3b14da39ae67d2925a677e0 licenseInfo + neris.fsri.org/terms-of-use: 'agree not to ... systematically retrieve data ... through… | A person can look up structure fires per county in the NERIS Explorer (neris.fsri.org/public/incident-basics) in a browser, or ask FSRI for written permission/licence; the terms forbid automated retr… |
| NC eCourts Smart Search: summary ejectment filings | statewide, NC | CAPTCHA |  | A person searches Smart Search by case type 'Summary Ejectment' and county in a browser and solves the image check. |
| SC Public Index magistrate (summary court) cases | statewide, SC | terms-only |  | A person searches each county's Public Index by party name for a held lead (Rule 610 per-case use); bulk sweeps are barred by the terms. |
| HUD Aggregated USPS vacancy data | national, US | login | huduser.gov USPS page: 'accessible only to governmental entities and non-profit organizations registered as users' | Only government and non-profit users can register and sign the sublicense; data is tract-level, never addresses. |
| Utility disconnect / water shut-off lists (NC) | statewide, NC | absent |  | Closed by statute (public-enterprise billing records are not public records). Exception found: Kinston publishes per-building cut-off flags on its demolition layer (built). |
| Utility disconnect lists (SC) | statewide, SC | public-records-request |  | File a FOIA request with the city utility for inactive residential service addresses; expect a personal-information exemption. |
| Public Surplus (NCACC partner) government auctions | statewide, NC | JS-app |  | A person opens the real-estate category for NC/SC agencies in a browser. |
| Mecklenburg Sheriff public auctions (execution sales) | Charlotte, Mecklenburg, NC | bot-check | curl 2026-10-07: HTTP 403 'Attention Required! / Cloudflare' on the page and on a notice PDF | A person opens mecksheriff.com/publicauctions in a browser (Cloudflare check) and downloads the notice PDFs. |
| York County SC county website (tax sale notice, delinquent tax page) | York, SC | bot-check | curl 2026-10-07: HTTP 403 'Enable JavaScript and cookies to continue' | Open in a browser; the open ArcGIS layer (built today) carries the list itself. |
| Kinston condemnation list and citywide/corridor demolition project li… | Kinston, Lenoir, NC | public-records-request | WebSearch 'Kinston NC condemned dilapidated structures demolition list' -> neusenews.com 2026-01-02 (118 remain), witn.com 2026-04-21/22; '… | Email Kinston Planning/Code Enforcement (or the City Clerk) a public-records request for the current condemned-structures spreadsheet (address, PIN, condemnation date, status). Agenda packets: open k… |
| Kinston city-owned vacant lot sale list (annual December surplus list) | Kinston, Lenoir, NC | absent | WebSearch 'Kinston NC city-owned lots for sale surplus property list' -> witn.com 2022-10-19, wnct.com; kinstonnc.gov/294/Surplus-Property-… | Ask Kinston Purchasing Manager for the current council-approved surplus real-property list; or watch kinstonnc.gov news each December. |
| Smithfield vacant building registry (commercial, 90-day) | Smithfield, Johnston, NC | public-records-request | smithfield-nc.com/page/planning_code_enforcement fetched 200: links 'Annual Vacant Property Registration Form' and 'Vacant Building Mainten… | Request the current Annual Vacant Property Registration roster from Smithfield Planning. |
| Albemarle minimum-housing demolition ordinances / program updates (co… | Albemarle, Stanly, NC | bot-check | curl 403 Akamai 'Access Denied' (errors.edgesuite.net reference) on showpublisheddocument/3921; WebSearch 'Albemarle NC city condemned prop… | Open https://albemarlenc.gov/home/showpublisheddocument/3921/637375765523830000 in a normal browser (or the town's agenda center) and save the PDFs/pages; or ask the City/Town Clerk for the current l… |
| Eden Human Habitation Standards demolition memos / ordinances | Eden, Rockingham, NC | bot-check | curl 403 Akamai 'Access Denied' on showpublisheddocument/4189; WebSearch 'Eden NC city minimum housing demolition ordinance properties list… | Open https://edennc.us/home/showpublisheddocument/4189/638013561974570000 in a normal browser (or the town's agenda center) and save the PDFs/pages; or ask the City/Town Clerk for the current list of… |
| Reidsville code enforcement (outstanding dilapidated building and nui… | Reidsville, Rockingham, NC | bot-check | curl 403 Cloudflare 'Just a moment...' challenge; gis.reidsvillenc.gov resolves but no REST root (no response). | Open https://www.reidsvillenc.gov/planning-and-community-development/page/code-enforcement in a normal browser (or the town's agenda center) and save the PDFs/pages; or ask the City/Town Clerk for th… |
| Nashville (Nash Co.) demolition ordinances for abandoned/derelict str… | Nashville, Nash, NC | bot-check | curl 403 'Access Denied' on the code-enforcement page; WebSearch surfaced the 2025-07 ordinance PDF URL. | Open https://www.townofnashville.com/Departments/Planning-Development/Code-Enforcement in a normal browser (or the town's agenda center) and save the PDFs/pages; or ask the City/Town Clerk for the cu… |
| Creedmoor code enforcement page | Creedmoor, Granville, NC | bot-check | curl 403 'Access Denied'. | Open https://www.cityofcreedmoor.org/departments-and-services/community-development/code-enforcement in a normal browser (or the town's agenda center) and save the PDFs/pages; or ask the City/Town Cl… |
| Hillsborough code enforcement page | Hillsborough, Orange, NC | bot-check | curl 403 'Access Denied' (www.hillsboroughnc.gov). | Open https://hillsboroughnc.gov/about-us/regulations/code-enforcement in a normal browser (or the town's agenda center) and save the PDFs/pages; or ask the City/Town Clerk for the current list of pro… |
| City of Lexington website (code enforcement / council) | Lexington, Davidson, NC | bot-check | curl 403 'Access Denied' on homepage. | Open https://www.lexingtonnc.gov/ in a normal browser (or the town's agenda center) and save the PDFs/pages; or ask the City/Town Clerk for the current list of properties under minimum-housing or dem… |
| Dare County / Kill Devil Hills monthly building permit reports | Kill Devil Hills, Dare, NC | bot-check | curl 403 Akamai 'Access Denied'. | Open https://darenc.gov/home/showpublisheddocument/12118/638173355970670000 in a normal browser (or the town's agenda center) and save the PDFs/pages; or ask the City/Town Clerk for the current list … |
| Elizabeth City council condemnation / demolition ordinances | Elizabeth City, Pasquotank, NC | public-records-request | WebSearch 'Elizabeth City NC condemned structures demolition list minimum housing' -> elizabethcitync.gov/vertical/sites/.../uploads counci… | Ask the Elizabeth City Clerk or code-enforcement office for the current list of properties under minimum-housing, unsafe-building or demolition orders (address, PIN, order date, status). |
| Washington (Beaufort Co.) council demolition / title-search lists | Washington, Beaufort, NC | public-records-request | WebSearch -> thewashingtondailynews.com (2012-2015 condemnations) and wnct.com (Oct-2024 demolitions, ~30 more awaiting). | Ask the Washington Clerk or code-enforcement office for the current list of properties under minimum-housing, unsafe-building or demolition orders (address, PIN, order date, status). |
| Lumberton council demolition approvals (inspections director requests) | Lumberton, Robeson, NC | public-records-request | WebSearch -> robesonian.com 'city to demolish 5 unsafe structures', cbs17 (council members keep precinct lists, one with 40 homes). lumbert… | Ask the Lumberton Clerk or code-enforcement office for the current list of properties under minimum-housing, unsafe-building or demolition orders (address, PIN, order date, status). |
| Mebane condemnation/demolition actions and demolition fund | Mebane, Alamance, NC | public-records-request | WebSearch -> alamancenews.com (condemnation of a vacant dilapidated house, demolition lien), prismnews ($738,551 set aside); cityofmebanenc… | Ask the Mebane Clerk or code-enforcement office for the current list of properties under minimum-housing, unsafe-building or demolition orders (address, PIN, order date, status). |
| Lenoir (Caldwell) council demolish / vacate-and-close ordinances | Lenoir, Caldwell, NC | public-records-request | WebSearch -> newstopicnews.com (5-0 vote to demolish unsafe nonresidential structure), thepaper.media (vacate-and-close of a theater). Cald… | Ask the Lenoir Clerk or code-enforcement office for the current list of properties under minimum-housing, unsafe-building or demolition orders (address, PIN, order date, status). |
| Oak Island code-enforcement sweep results | Oak Island, Brunswick, NC | public-records-request | WebSearch -> stateportpilot.com: town-wide inspection logged 424 ROW obstructions, 345 junk piles, 317 overgrown lots; 33 high priority; he… | Ask the Oak Island Clerk or code-enforcement office for the current list of properties under minimum-housing, unsafe-building or demolition orders (address, PIN, order date, status). |
| Weddington code enforcement (Centralina contract) | Weddington, Union, NC | public-records-request | WebSearch -> centralina.org success story: reactive enforcement, 5-10 active cases per month. | Ask the Weddington Clerk or code-enforcement office for the current list of properties under minimum-housing, unsafe-building or demolition orders (address, PIN, order date, status). |
| Lincoln County / Lincolnton eTRAKiT code complaint search | Lincolnton, Lincoln, NC | login | Per r2: all /Search/*.aspx 302 -> login.aspx; not re-probed. | Request a code-complaint export from Lincoln County Planning & Inspections. |
| Marion OpenGov/ViewPoint permitting (code violation + demolition reco… | Marion, McDowell, NC | JS-app | Per r3: record types public (incl. Report Code Violation, Demolition Permit Application); records themselves not shown as public. |  |
| Morganton city website | Morganton, Burke, NC | bot-check | Per walls_register.md / r2: Cloudflare 403 on every path; city ArcGIS (gis.morgantonnc.gov) has no code/vacant/demolition layer. | Browser visit or records request to Morganton Development & Design Services. |
| Forest City SmartGov portal | Forest City, Rutherford, NC | login | Per r2: public notice board empty, reports need permit number. |  |
| WPCOG regional code enforcement (Sawmills, Long View and other member… | Sawmills, Caldwell, NC | public-records-request | WebSearch 'Sawmills NC town code enforcement dilapidated structure condemned' -> townofsawmillsnc.gov/179 (WPCOG officer handles nuisance +… | Request member-town case lists from WPCOG Code Enforcement. |
| Greenville County Unfit Structure Search | Greenville, SC | bot-check | CodeEnforcement page 200 links PublicRecords.aspx?DirURL=UnfitStructures (disclaimer page 200); r4_greenville.md records the target behind … | Open greenvillecountysc.gov/CodeEnforcement, click 'Unfit Structure Search', accept the disclaimer by hand, save the result page to the manual court-export lane |
| Town of Summerville code cases (CitizenServe portal, installation 301) | Summerville, Dorchester, SC | JS-app | Code-Enforcement page 200 says the department condemns dilapidated/unsafe structures and links CitizenServe installationID=301; portal home… | Open the portal, choose Code Complaints, search an address; for a bulk list file a FOIA with Summerville Code Enforcement (843-695-6511) asking for open IPMC/condemnation cases |
| Mount Pleasant town GIS (maps.tompsc.com + AGOL lzpM6epdQtzxVX5J) | Mount Pleasant, Charleston, SC | absent | maps.tompsc.com root 200 (19 folders) enumerated Planning, PublicService, Parcel_Search_New, OPAL_services; hub gis-tomp data.json has 0 da… | FOIA to Mount Pleasant Planning (Code Enforcement Officer, IPMC/Chapter 93 nuisance) for open property-maintenance cases |
| North Charleston code enforcement (no public list) | North Charleston, Charleston, SC | absent | code_enforcement page 200: no list, no portal link; public_notices.php 200 shows only meeting notices; gis.northcharleston.org does not res… | FOIA to North Charleston Code Enforcement (843-740-2680) for condemned/Indemnification-program addresses; demolition bid packets from Procurement also name addresses |
| SC Press Association public notices: keyword lane for unfit/unsafe/de… | statewide, SC | JS-app | not fetched by this agent (browser-only form); module docstring documents the grid as open and detail pages as CAPTCHA-walled; Florence not… | In the existing browser-driven module, add a free-text search ('unfit for human habitation' OR 'unsafe structure' OR 'demolish') per county; Details.aspx stays off-limits (CAPTCHA) |
| Goose Creek GIS (EnerGov / OpenGov folders) | Goose Creek, Berkeley, SC | login | gis.cityofgoosecreek.com folders EnerGov/OpenGov/Data2022 -> 499 Token Required; newer gis.goosecreeksc.gov/server folders OpenGovEGDB/Host… | Ask Goose Creek GIS/Code Enforcement for a public view of open code cases, or FOIA the case list |
| Myrtle Beach code enforcement / Quality of Life Court (no public list) | Myrtle Beach, Horry, SC | absent | GIS division page 200 links only comb.maps.arcgis.com; AGOL org 650sW8BhgpAHhq6u (services2) 77 services, no code layer (IndividualAssistan… | Read City Council meeting documents (government/boards_and_committees/city_council_documents.php) for 'unfit and unsafe' demolition resolutions; FOIA Neighborhood Services for open property-maintenan… |
| City of West Columbia blight removal program | West Columbia, Lexington, SC | absent | page 200 with captions only; hub data.json 0 datasets; service requests via civicweb portal | FOIA West Columbia Code Compliance for dilapidated-structure and cleanup-lien properties; city hub (city-of-west-columbia-gis...hub.arcgis.com) data.json has 0 datasets |
| Woodruff code-enforcement portal (iWorQ) | Woodruff, Spartanburg, SC | bot-check | all three iWorQ portal hosts return HTTP 403 Forbidden to a plain browser-UA GET | FOIA Woodruff code enforcement for open property-maintenance, unsafe-structure and condemnation cases |
| Fountain Inn code-enforcement portal (iWorQ) | Fountain Inn, Greenville, SC | JS-app | code page links only a new-case intake form; Property Maintenance Board page (187) has no case list | FOIA Fountain Inn code enforcement for open property-maintenance, unsafe-structure and condemnation cases |
| Tega Cay code-enforcement portal (Evolve) | Tega Cay, York, SC | JS-app | code page links 'Report A Violation' only | FOIA Tega Cay code enforcement for open property-maintenance, unsafe-structure and condemnation cases |
| Simpsonville code-enforcement portal (Evolve) | Simpsonville, Greenville, SC | JS-app | portal home 200, only 'Project Portal' link; no public case list | FOIA Simpsonville code enforcement for open property-maintenance, unsafe-structure and condemnation cases |
| Seneca code-enforcement portal (CitizenServe) | Seneca, Oconee, SC | JS-app | building-codes page links CitizenServe; Building Codes Enforcement Officer seat vacant | FOIA Seneca code enforcement for open property-maintenance, unsafe-structure and condemnation cases |
| Greenwood code-enforcement portal (CitizenServe) | Greenwood, Greenwood, SC | JS-app | code page says abatement costs become a lien recorded with the Clerk of Court; links CitizenServe intake only | FOIA Greenwood code enforcement for open property-maintenance, unsafe-structure and condemnation cases |
| Beaufort code-enforcement portal (Brightly) | Beaufort, Beaufort, SC | JS-app | Code-Enforcement-Process page links Brightly portal; surplus page is GovDeals equipment only | FOIA Beaufort code enforcement for open property-maintenance, unsafe-structure and condemnation cases |
| North Myrtle Beach code-enforcement portal (OpenGov) | North Myrtle Beach, Horry, SC | JS-app | homepage links OpenGov category page; OpenGov portals are SPA shells (r3_Union.md shows wildcard behaviour) | FOIA North Myrtle Beach code enforcement for open property-maintenance, unsafe-structure and condemnation cases |
| Orangeburg code-enforcement portal (AccessGov) | Orangeburg, Orangeburg, SC | absent | building inspection page lists permit forms only; no code/condemned list | FOIA Orangeburg code enforcement for open property-maintenance, unsafe-structure and condemnation cases |
| City websites behind Cloudflare / bot challenge (code pages unreadabl… | statewide, SC | bot-check | curl with Safari UA: Columbia/Aiken/York/Clover/Hollywood/Central/Batesburg-Leesville 403 'Just a moment' challenge-platform; Lancaster 403… | Open each city's code-enforcement / building page in a normal browser and look for a condemned, unsafe or vacant-building list; save any list PDF to the manual lane. Their ArcGIS hosts were checked s… |
| City of Darlington vacant building registration program (no public ro… | Darlington, Darlington, SC | public-records-request | codes-enforcement page 200 describes the Vacant Building Registration Program approved 2021-06-08 and links 4 PDFs (forms/fees), no roster | FOIA Darlington Codes Enforcement (843-398-4029) for the vacant building registry (addresses, owners, registration dates) |
| Durham 2025 tax-lien advertisement (Spatialest delinquent list) | Durham, NC | disclaimer-click | main.js shows getData.php qtype=delinquint_list after a cookie 'del_list_view' disclaimer; disclaimer template text is the 105-369 advertis… |  |
| Union County delinquent tax lien advertisement + property tax foreclo… | Union, NC | bot-check | curl GET -> HTTP 403 'Access Denied' from AkamaiGHost (reference #18.40c0ce17...); HEAD on property-tax-foreclosure-auction page also 403 s… | Open unioncountync.gov in a normal browser (Akamai blocks scripted clients), go to Taxes & Property > Collection & Payment > Delinquent Tax Lien Advertisement and Property Tax Foreclosure Auction, an… |
| Craven/Pender/Moore/Martin/Chowan/Robeson/Guilford ZLS listings | statewide, NC | JS-app | county pages for Craven, Moore, Martin, Chowan, Robeson, Guilford link here |  |
| taxsaleresources.com NC county tax deed sale pages | statewide, NC | paid | HTTP 200, 'Start 7-Day Trial for $1.99', addresses shown as 'Click to see the address' | Subscriber logs in to see addresses; alternatively a person checks the courthouse notice board or the county attorney. |
| Warren County tax foreclosures (ZLS) | Warren, NC | JS-app | HTTP 200 resolves to 'Property Listings / Zacchaeus Legal Services' |  |
| Cabarrus County website (tax foreclosure / delinquent / surplus pages) | Cabarrus, NC | bot-check | HTTP 403 'Access Denied' (Akamai edgesuite reference) to curl and urllib on 2026-10-07 | Open https://www.cabarruscounty.us in a normal browser, go to the Tax department pages (Collections / Tax Foreclosures / Delinquent Taxes / Surplus Property) and download any posted lists; the annual… |
| Chatham County website (tax foreclosure / delinquent / surplus pages) | Chatham, NC | bot-check | HTTP 403 'Access Denied' (Akamai) on 2026-10-07 | Open https://www.chathamcountync.gov in a normal browser, go to the Tax department pages (Collections / Tax Foreclosures / Delinquent Taxes / Surplus Property) and download any posted lists; the annu… |
| Dare County website (tax foreclosure / delinquent / surplus pages) | Dare, NC | bot-check | HTTP 403 'Access Denied' (Akamai) on 2026-10-07 | Open https://www.darenc.gov in a normal browser, go to the Tax department pages (Collections / Tax Foreclosures / Delinquent Taxes / Surplus Property) and download any posted lists; the annual lien a… |
| Person County website (tax foreclosure / delinquent / surplus pages) | Person, NC | bot-check | HTTP 403 'Access Denied' (Akamai) on 2026-10-07 | Open https://www.personcountync.gov in a normal browser, go to the Tax department pages (Collections / Tax Foreclosures / Delinquent Taxes / Surplus Property) and download any posted lists; the annua… |
| Sampson County website (tax foreclosure / delinquent / surplus pages) | Sampson, NC | bot-check | HTTP 403 'Access Denied' (Akamai) after redirect to www.sampsoncountync.gov on 2026-10-07 | Open https://www.sampsonnc.com in a normal browser, go to the Tax department pages (Collections / Tax Foreclosures / Delinquent Taxes / Surplus Property) and download any posted lists; the annual lie… |
| Wilson County website (tax foreclosure / delinquent / surplus pages) | Wilson, NC | bot-check | HTTP 403 'Access Denied' (Akamai) on 2026-10-07 | Open https://www.wilsoncountync.gov in a normal browser, go to the Tax department pages (Collections / Tax Foreclosures / Delinquent Taxes / Surplus Property) and download any posted lists; the annua… |
| Buncombe County website (tax foreclosure / delinquent / surplus pages) | Buncombe, NC | bot-check | HTTP 403 Cloudflare 'Attention Required!' block page on 2026-10-07 | Open https://www.buncombenc.gov in a normal browser, go to the Tax department pages (Collections / Tax Foreclosures / Delinquent Taxes / Surplus Property) and download any posted lists; the annual li… |
| Franklin County website (tax foreclosure / delinquent / surplus pages) | Franklin, NC | bot-check | HTTP 403 Cloudflare 'Attention Required!' on 2026-10-07 | Open https://www.franklincountync.gov in a normal browser, go to the Tax department pages (Collections / Tax Foreclosures / Delinquent Taxes / Surplus Property) and download any posted lists; the ann… |
| Granville County website (tax foreclosure / delinquent / surplus page… | Granville, NC | bot-check | HTTP 403 Cloudflare 'Attention Required!' on 2026-10-07 | Open https://www.granvillecounty.org in a normal browser, go to the Tax department pages (Collections / Tax Foreclosures / Delinquent Taxes / Surplus Property) and download any posted lists; the annu… |
| Hyde County website (tax foreclosure / delinquent / surplus pages) | Hyde, NC | bot-check | HTTP 403 Cloudflare 'Attention Required!' (cms2.revize.com/revize/hydecounty) on 2026-10-07 | Open https://www.hydecountync.gov in a normal browser, go to the Tax department pages (Collections / Tax Foreclosures / Delinquent Taxes / Surplus Property) and download any posted lists; the annual … |
| Onslow County website (tax foreclosure / delinquent / surplus pages) | Onslow, NC | bot-check | HTTP 403 Cloudflare 'Attention Required!' on 2026-10-07 | Open https://www.onslowcountync.gov in a normal browser, go to the Tax department pages (Collections / Tax Foreclosures / Delinquent Taxes / Surplus Property) and download any posted lists; the annua… |
| Rockingham County website (tax foreclosure / delinquent / surplus pag… | Rockingham, NC | bot-check | HTTP 403 Cloudflare 'Just a moment...' JS challenge on 2026-10-07 | Open https://www.rockinghamcountync.gov in a normal browser, go to the Tax department pages (Collections / Tax Foreclosures / Delinquent Taxes / Surplus Property) and download any posted lists; the a… |
| Charlotte city properties for sale (upset bid) | Charlotte, Mecklenburg, NC | bot-check | HTTP 403 Akamai 'Access Denied' (edgesuite reference) on 2026-10-07; search snippet describes the upset-bid list | Open the page in a normal browser and read the current list. |
| Fayetteville surplus real property | Fayetteville, Cumberland, NC | bot-check | HTTP 403 Akamai 'Access Denied' on 2026-10-07 | Open the page in a normal browser. |
| Bamberg County overage claims page | Bamberg, SC | absent | 2026-10-07: HTTP 200; text is claim procedure and a release form PDF; no list of overages. | Ask the Delinquent Tax Office for the overage list by FOIA. |
| Colleton County public nuisance page | Colleton, SC | absent | 2026-10-07: HTTP 200, last updated 2022-03-17; abatement-agreement FAQ, ordinance PDF, officer contact; no list. | FOIA the Code Enforcement Officer for open nuisance/abatement liens. |
| Fairfield County Forfeited Land Commission page | Fairfield, SC | absent | 2026-10-07: HTTP 200; statutory description, no property list. | Call the Treasurer/FLC for available FLC parcels. |
| Lexington County Master-in-Equity judicial sale roster | Lexington, SC | disclaimer-click | 2026-10-07: county page lex-co.sc.gov/master-equity/judicialforeclosure-sales-information-and-links HTTP 200: sales first Monday 11:00, not… | Accept the Public Index disclaimer in a browser, open the Master-in-Equity roster for the month, save the page into the manual-export folder. |
| Laurens County delinquent tax notice (newspaper e-edition) | Laurens, SC | terms-only | 2026-10-07: linked from laurenscountysc.gov delinquent_taxes.php as 'Delinquent Tax Notice of Properties'; viewer HTTP 200, shows 'Log In /… |  |
| Union County tax sale / FLC assignment notice | Union, SC | absent | 2026-10-07: HTTP 200; sale 2026-11-10; FLC bid assignments for unsold 2025 parcels from 2026-01-14 with the list 'available at the Union Co… | Visit or call the Auditor's office for the FLC list; read the sale ad in the Union County newspaper three weeks before 2026-11-10. |
| Abbeville County delinquent tax sale (newspaper only) and FLC mobile-… | Abbeville, SC | JS-app | 2026-10-07: delinquent-tax-collector page HTTP 200: list 'advertised in The Press & Banner for three consecutive weeks prior to the tax sal… | Read the Press & Banner tax-sale ad; open the Acrobat link in a browser and save the PDF. |
| Aiken County tax collector overage claims | Aiken, SC | disclaimer-click | 2026-10-07: HTTP 200; 'To access Overage Claim Forms, you must agree to the following: Delinquent Tax Disclaimer'. Tax sale page /309: 2026… | Open the page in a browser, accept the disclaimer, save any overage list shown. |
| Darlington County Delinquent Tax Collector page | Darlington, SC | absent | 2026-10-07: HTTP 200; list 'advertised in the Darlington News & Press' three weeks (real) / two weeks (other) before sale; no file links. | Read the News & Press ad (or Column/SC public notices if the paper syndicates). |
| McCormick County tax sale (newspaper only) | McCormick, SC | absent | 2026-10-07: HTTP 200; sale first Monday in October (2026-10-05, already held); ads in The McCormick Messenger three weeks prior. | Read the Messenger ad in September. |
| Jasper County FLC and delinquent real property pages | Jasper, SC | absent | 2026-10-07: FLC page HTTP 200 links /media/0kwpcys3/flc-none-available.pdf; /services/taxes/delinquent-tax-collection/real-property/ HTTP 2… | Read the newspaper ad in October. |
| Greenwood County Tax Collector page | Greenwood, SC | absent | 2026-10-07: /tax-collector HTTP 200 (822 KB JS shell) and /treasurer/delinquent-tax-sale HTTP 200: redemption payment info only, no list fi… | List runs as Index-Journal ads. |
| Chesterfield County Tax Collector FAQ | Chesterfield, SC | absent | 2026-10-07: HTTP 200 (found via Wix pages-sitemap.xml); FAQ: delinquent properties 'advertised in one or more county newspapers for 3 conse… | Read the newspaper ad. |
| Barnwell County Tax Sales Information | Barnwell, SC | absent | 2026-10-07: HTTP 200 (found via /sitemap.xml; www.barnwellcounty.sc.gov and barnwellcounty.sc.gov did not answer, barnwellcountysc.gov does… | Read the newspaper ad. |
| Lee County Delinquent Tax page | Lee, SC | absent | 2026-10-07: HTTP 200; sale 'normally held in November' in the courthouse; no list links. | Read the newspaper ad. |
| Clarendon County 2026 tax sale registration notice | Clarendon, SC | absent | 2026-10-07: HTTP 200, posted 2026-10-01; links only 2026-tax-sale-registration.pdf on media-002-us.cdn.govstack.com. | Read the Manning Times ad. |
| Sumter County Master-in-Equity page | Sumter, SC | absent | 2026-10-07: HTTP 200; sales first Monday monthly at noon, Room 211; no sale list link. | Use the Public Index MIE roster (disclaimer-click) or the Item newspaper ads. |
| Beaufort County MIE foreclosure list information | Beaufort, SC | disclaimer-click | 2026-10-07: HTTP 200; page explains selecting Master in Equity rosters on publicindex.sccourts.org/beaufort/courtrosters/. |  |
| Beaufort County Code Enforcement | Beaufort, SC | absent | 2026-10-07: HTTP 200; complaint process and ordinance list; no case list. | FOIA for open code cases. |
| Orangeburg County website (tax sale, overage) | Orangeburg, SC | bot-check | 2026-10-07: HTTP 403, 5,485 bytes, title 'Attention Required! / Cloudflare'. | Open orangeburgcounty.org in a browser, find the Delinquent Tax / Overage pages, save the list PDFs into the manual-export folder. |
| Anderson County Environmental Code Enforcement (OpenGov portal) | Anderson, SC | JS-app | 2026-10-07: department page HTTP 200 links the OpenGov portal and complaint topics (trash, dumping, debris); no public case list. Anderson … | Search the OpenGov portal in a browser for code cases; FOIA for a case export. |
| Bamberg / Jasper / Dillon / Newberry code enforcement pages | Bamberg, Jasper, SC | absent | 2026-10-07: Bamberg HTTP 200 (litter officer, ordinance PDF, litter gallery); Jasper /public-safety-offices/code-enforcement-and-litter-con… | FOIA. |

## 5. Coverage grid

Codes: **B** built (a module reads it), **O** open source found, not built, **W** walled (CAPTCHA, login, bot check, terms, records request), **A** absent by law, **N** nothing found after a real search (the searched routes are in the JSON grid's `_notes`), **n** nothing on the ArcGIS Online route only (the 45-term sweep found no public item for this place; its own web pages were not read for this category), **-** not checked this round.

Statewide lanes applied to every county: NC eviction = O (NC Judgment Search summary-ejectment money judgments, open JSON, not built; filings themselves are CAPTCHA-walled); SC eviction = W (Public Index terms); NC absentee = B (NC OneMap parcels in the parcel cache); fire = statewide NFIRS public data release (open, annual, not built) and NERIS (terms-walled), not stamped per cell.

### 5.1 NC counties

| County | delinq | taxsale | surplus | sheriff/MIE | code | condemn | permits | fire | flood | evict | STR | absentee |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| Alamance | N | O | N | - | N | W | n | n | n | O | n | B |
| Alexander | N | N | N | N | N | n | n | n | n | O | n | B |
| Alleghany | N | N | O | N | N | n | n | n | n | O | n | B |
| Anson | N | B | N | N | N | n | n | n | n | O | n | B |
| Ashe | O | N | N | N | N | n | n | n | n | O | n | B |
| Avery | N | B | N | - | - | n | n | n | n | O | n | B |
| Beaufort | B | N | N | N | N | W | n | n | n | O | n | B |
| Bertie | B | - | - | - | - | n | n | n | n | O | n | B |
| Bladen | N | N | O | - | - | n | n | n | n | O | n | B |
| Brunswick | N | B | O | B | W | N | O | n | O | O | n | B |
| Buncombe | B | B | B | W | - | n | n | n | B | O | B | B |
| Burke | B | B | B | N | B | n | n | n | B | O | n | B |
| Cabarrus | W | B | W | W | O | n | n | n | n | O | n | B |
| Caldwell | N | N | N | N | W | W | N | n | n | O | n | B |
| Camden | N | N | B | N | N | n | n | n | n | O | n | B |
| Carteret | N | B | N | N | N | N | N | n | n | O | n | B |
| Caswell | N | N | N | - | - | n | n | n | n | O | n | B |
| Catawba | B | B | N | O | N | n | n | n | n | O | n | B |
| Chatham | W | O | W | W | W | n | n | n | n | O | n | B |
| Cherokee | N | B | N | N | N | n | n | n | n | O | n | B |
| Chowan | N | B | O | - | - | n | n | n | n | O | n | B |
| Clay | N | N | N | - | - | n | n | n | n | O | n | B |
| Cleveland | N | B | B | B | O | n | n | n | n | O | n | B |
| Columbus | N | N | N | - | - | n | n | n | n | O | n | B |
| Craven | N | O | O | - | N | N | N | n | n | O | O | B |
| Cumberland | B | B | W | - | O | n | n | n | O | O | n | B |
| Currituck | N | O | N | N | N | n | n | n | n | O | n | B |
| Dare | W | W | W | W | W | n | W | n | n | O | n | B |
| Davidson | O | B | N | N | W | n | n | n | n | O | n | B |
| Davie | O | B | N | N | N | - | O | n | n | O | n | B |
| Duplin | N | O | N | N | N | n | n | n | n | O | n | B |
| Durham | B | O | N | - | B | n | n | n | n | O | n | B |
| Edgecombe | O | B | B | - | N | B | N | n | n | O | n | B |
| Forsyth | B | O | N | O | N | n | O | n | n | O | n | B |
| Franklin | W | W | W | W | W | n | n | n | n | O | n | B |
| Gaston | N | B | B | N | B | n | O | n | n | O | n | B |
| Gates | B | N | O | - | - | n | n | n | n | O | n | B |
| Graham | B | - | - | - | - | n | n | n | n | O | n | B |
| Granville | W | W | W | W | W | n | n | n | n | O | n | B |
| Greene | N | O | O | - | - | n | n | n | n | O | n | B |
| Guilford | B | B | O | - | B | n | n | n | n | O | O | B |
| Halifax | N | O | W | N | N | O | n | n | n | O | n | B |
| Harnett | N | O | N | - | O | O | - | n | n | O | n | B |
| Haywood | N | B | N | N | N | N | N | n | n | O | n | B |
| Henderson | B | B | N | N | B | n | n | n | B | O | n | B |
| Hertford | B | N | O | - | - | n | n | n | n | O | n | B |
| Hoke | O | O | O | N | N | n | n | n | n | O | n | B |
| Hyde | B | W | W | W | W | n | n | n | n | O | n | B |
| Iredell | O | W | O | N | O | n | n | O | n | O | n | B |
| Jackson | N | N | N | N | N | n | n | n | n | O | n | B |
| Johnston | N | O | N | - | O | n | n | n | n | O | n | B |
| Jones | N | N | N | N | N | n | n | n | n | O | n | B |
| Lee | O | N | O | - | - | n | n | n | n | O | n | B |
| Lenoir | N | N | O | N | N | B | n | n | n | O | n | B |
| Lincoln | B | B | B | N | B | n | n | n | n | O | n | B |
| Macon | N | N | O | N | N | n | n | n | n | O | n | B |
| Madison | B | B | O | - | - | n | n | n | n | O | n | B |
| Martin | O | B | N | - | N | N | N | n | n | O | n | B |
| McDowell | B | B | N | - | W | O | n | n | n | O | n | B |
| Mecklenburg | B | B | O | W | B | O | O | n | n | O | n | B |
| Mitchell | N | N | - | - | - | n | n | n | n | O | n | B |
| Montgomery | N | N | N | N | N | n | n | n | n | O | n | B |
| Moore | N | B | N | N | N | N | N | O | n | O | n | B |
| Nash | O | N | W | N | N | B | n | n | n | O | n | B |
| New Hanover | B | B | - | N | N | n | B | n | n | O | n | B |
| Northampton | N | N | N | N | N | n | n | n | n | O | n | B |
| Onslow | B | B | W | W | O | N | O | n | n | O | n | B |
| Orange | B | - | O | N | W | n | n | n | n | O | n | B |
| Pamlico | N | N | N | - | - | n | n | n | n | O | n | B |
| Pasquotank | O | N | N | - | - | W | n | n | n | O | n | B |
| Pender | N | N | B | N | O | n | n | n | n | O | n | B |
| Perquimans | B | O | N | - | - | n | n | n | n | O | n | B |
| Person | W | W | W | W | O | - | O | n | n | O | n | B |
| Pitt | B | N | - | N | N | n | n | n | n | O | n | B |
| Polk | N | B | - | - | - | n | n | n | n | O | n | B |
| Randolph | B | N | - | N | N | n | n | n | n | O | n | B |
| Richmond | N | N | N | N | N | N | N | n | n | O | n | B |
| Robeson | N | B | N | - | - | W | n | n | n | O | n | B |
| Rockingham | W | N | W | W | W | W | n | n | n | O | n | B |
| Rowan | O | B | - | - | O | n | n | n | n | O | n | B |
| Rutherford | B | B | - | - | - | n | W | n | n | O | n | B |
| Sampson | W | W | W | W | W | n | n | n | n | O | n | B |
| Scotland | N | N | N | N | N | n | n | n | n | O | n | B |
| Stanly | N | N | N | N | N | W | n | n | n | O | n | B |
| Stokes | B | B | O | - | - | n | n | n | n | O | n | B |
| Surry | N | N | - | - | - | n | n | n | n | O | n | B |
| Swain | N | B | N | N | N | n | n | n | n | O | n | B |
| Transylvania | B | N | B | N | N | n | n | n | B | O | n | B |
| Tyrrell | B | N | N | - | - | n | n | n | n | O | n | B |
| Union | W | W | W | W | W | n | n | n | n | O | n | B |
| Vance | N | O | O | - | N | O | - | n | n | O | n | B |
| Wake | N | B | O | - | N | n | O | B | n | O | n | B |
| Warren | N | B | N | N | N | n | n | n | n | O | n | B |
| Washington | B | N | O | - | - | n | n | n | n | O | n | B |
| Watauga | N | B | B | - | - | n | n | n | n | O | n | B |
| Wayne | B | O | B | N | N | n | n | n | n | O | n | B |
| Wilkes | N | N | N | N | N | n | n | n | n | O | n | B |
| Wilson | W | W | W | W | W | n | n | n | n | O | n | B |
| Yadkin | N | O | N | N | N | n | n | n | n | O | n | B |
| Yancey | N | B | N | N | N | n | n | n | n | O | n | B |

### 5.2 SC counties

| County | delinq | taxsale | surplus | sheriff/MIE | code | condemn | permits | fire | flood | evict | STR | absentee |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| Abbeville | B | W | N | O | - | - | - | n | n | W | n | - |
| Aiken | B | W | - | W | W | W | - | n | n | W | n | B |
| Allendale | B | N | - | - | - | - | - | n | n | W | n | - |
| Anderson | - | N | B | B | W | B | - | n | n | W | n | B |
| Bamberg | B | O | - | B | A | - | - | n | n | W | n | - |
| Barnwell | B | A | - | B | N | N | - | n | n | W | n | B |
| Beaufort | - | N | B | B | W | N | O | n | n | W | O | B |
| Berkeley | B | W | - | W | W | W | W | n | n | W | n | B |
| Calhoun | B | O | - | - | - | - | - | n | n | W | n | B |
| Charleston | B | B | O | B | O | O | O | n | n | O | O | B |
| Cherokee | B | B | B | B | N | N | - | n | n | W | n | - |
| Chester | B | W | - | W | N | N | - | n | n | W | n | B |
| Chesterfield | B | A | - | - | - | - | - | n | n | W | n | - |
| Clarendon | B | A | N | N | N | N | - | n | n | W | n | - |
| Colleton | B | B | - | B | A | N | - | n | n | W | n | B |
| Darlington | B | A | - | - | O | O | - | O | n | W | n | B |
| Dillon | B | B | - | B | - | - | - | n | n | W | n | - |
| Dorchester | B | W | O | W | W | N | - | n | n | W | n | W |
| Edgefield | B | W | - | O | N | - | - | n | n | W | n | - |
| Fairfield | B | B | A | - | N | - | - | n | n | W | n | - |
| Florence | B | B | O | O | N | O | - | n | n | W | n | B |
| Georgetown | B | - | - | B | N | N | - | n | n | W | n | - |
| Greenville | B | B | - | B | O | O | O | n | n | W | n | B |
| Greenwood | B | A | - | O | B | B | - | n | n | W | n | B |
| Hampton | B | N | N | N | N | N | - | n | n | W | n | B |
| Horry | B | B | B | B | O | A | - | n | n | W | n | B |
| Jasper | B | N | A | - | A | - | - | n | n | W | n | B |
| Kershaw | B | W | W | - | N | N | O | n | n | W | n | - |
| Lancaster | B | O | O | - | O | N | - | n | n | W | n | B |
| Laurens | B | O | - | B | N | N | - | n | n | W | n | B |
| Lee | B | A | - | - | - | - | - | n | n | W | n | - |
| Lexington | B | O | B | W | N | A | - | n | n | W | n | B |
| Marion | - | O | B | - | N | - | - | n | n | W | n | - |
| Marlboro | B | N | - | - | N | N | - | n | n | W | n | - |
| McCormick | - | A | B | O | - | - | - | n | n | W | n | - |
| Newberry | B | N | O | O | N | N | - | n | n | W | n | - |
| Oconee | B | B | B | B | W | N | W | n | n | W | n | B |
| Orangeburg | B | W | - | - | A | - | - | n | n | W | n | - |
| Pickens | B | B | B | B | O | O | - | n | B | W | n | B |
| Richland | - | B | B | O | B | W | - | n | n | W | O | O |
| Saluda | B | B | - | O | N | N | - | n | n | W | n | B |
| Spartanburg | B | B | B | B | B | B | - | n | B | W | n | B |
| Sumter | B | - | B | A | O | O | - | n | n | W | n | B |
| Union | B | A | N | B | N | N | - | n | n | W | n | - |
| Williamsburg | B | O | - | N | N | N | - | n | n | W | n | - |
| York | - | B | - | W | B | B | - | n | n | W | n | B |

### 5.3 NC municipalities of 5,000+

| City | code | condemn | vacant reg | permits | fire | STR | city-owned |
|---|---|---|---|---|---|---|---|
| Charlotte | B | O | n | n | n | n | W |
| Raleigh | n | n | n | O | B | n | O |
| Greensboro | B | n | n | n | n | O | n |
| Durham | B | n | n | n | n | n | n |
| Winston-Salem | n | n | n | n | n | n | n |
| Fayetteville | O | n | n | n | n | n | W |
| Cary | n | n | n | n | n | n | n |
| Wilmington | n | n | n | B | n | n | n |
| High Point | n | n | n | n | n | n | n |
| Concord | n | n | n | n | n | n | n |
| Greenville | n | n | n | n | n | n | n |
| Asheville | n | n | n | n | n | B | n |
| Gastonia | n | n | n | n | n | n | n |
| Apex | n | n | n | n | n | n | n |
| Jacksonville | n | n | n | n | n | n | n |
| Huntersville | n | n | n | n | n | n | n |
| Chapel Hill | n | n | n | n | n | n | n |
| Burlington | n | n | n | n | n | n | n |
| Kannapolis | O | n | n | n | n | n | n |
| Wake Forest | n | n | n | n | n | n | n |
| Rocky Mount | n | B | B | n | n | n | n |
| Mooresville | n | n | n | n | n | n | n |
| Holly Springs | n | n | n | n | n | n | n |
| Wilson | n | n | n | n | n | n | n |
| Fuquay-Varina | n | n | n | n | n | n | n |
| Hickory | n | n | n | n | n | n | n |
| Indian Trail | n | n | n | n | n | n | n |
| Monroe | n | n | n | n | n | n | n |
| Garner | n | n | n | n | n | n | n |
| Salisbury | O | n | n | n | n | n | n |
| Goldsboro | n | n | n | n | n | n | n |
| Leland | n | n | n | n | n | n | n |
| Cornelius | n | n | n | n | n | n | n |
| New Bern | n | n | n | n | n | O | O |
| Sanford | n | n | n | n | n | n | n |
| Morrisville | n | n | n | n | n | n | n |
| Matthews | n | n | n | n | n | n | n |
| Clayton | n | n | n | n | n | n | n |
| Statesville | O | n | n | n | O | n | n |
| Mint Hill | n | n | n | n | n | n | n |
| Kernersville | n | n | n | n | n | n | n |
| Asheboro | n | n | n | n | n | n | n |
| Thomasville | n | n | n | n | n | n | n |
| Waxhaw | n | n | n | n | n | n | n |
| Shelby | n | n | n | n | n | n | n |
| Clemmons | N | N | - | - | n | n | - |
| Knightdale | N | N | - | - | n | n | - |
| Carrboro | N | N | - | - | n | n | - |
| Mebane | N | W | - | - | n | n | - |
| Harrisburg | N | N | - | - | n | n | - |
| Boone | N | N | - | - | n | n | - |
| Lexington | W | N | - | - | n | n | - |
| Kinston | N | B | - | - | n | n | A |
| Graham | N | N | - | - | n | n | - |
| Elizabeth City | N | W | - | - | n | n | N |
| Lumberton | N | W | - | - | n | n | N |
| Mount Holly | N | N | - | - | n | n | - |
| Pinehurst | N | N | - | - | O | n | - |
| Lenoir | N | W | - | - | n | n | - |
| Hope Mills | N | N | - | - | n | n | - |
| Morganton | B | W | - | - | n | n | - |
| Stallings | N | N | - | - | n | n | - |
| Havelock | N | N | - | - | n | n | - |
| Albemarle | N | W | - | - | n | n | - |
| Southern Pines | N | N | - | - | n | n | - |
| Wendell | N | N | - | - | n | n | - |
| Davidson | N | N | - | - | n | n | - |
| Belmont | N | N | - | - | n | n | - |
| Hendersonville | - | B | B | - | n | n | - |
| Eden | N | W | - | - | n | n | N |
| Laurinburg | N | N | - | - | n | n | - |
| Henderson | N | O | - | - | n | n | O |
| Reidsville | W | N | - | - | n | n | N |
| Roanoke Rapids | N | O | - | - | n | n | - |
| Weddington | W | N | - | - | n | n | - |
| Lewisville | N | N | - | - | n | n | - |
| Newton | N | N | - | - | n | n | - |
| Smithfield | N | N | W | - | n | n | - |
| Lincolnton | B | - | B | W | n | n | N |
| Archdale | N | N | - | - | n | n | - |
| Rolesville | N | N | - | - | n | n | - |
| Kings Mountain | O | N | - | W | n | n | - |
| Pineville | N | N | - | - | n | n | - |
| Spring Lake | N | N | - | - | n | n | - |
| Summerfield | N | N | - | - | n | n | - |
| Elon | N | N | - | - | n | n | - |
| Tarboro | N | N | - | - | n | n | - |
| Winterville | N | N | - | - | n | n | - |
| Waynesville | N | N | - | - | n | n | - |
| Mount Airy | N | N | - | - | n | n | - |
| Zebulon | N | N | - | - | n | n | - |
| Morehead City | N | N | - | - | n | n | - |
| Hillsborough | W | N | - | - | n | n | - |
| Gibsonville | N | N | - | - | n | n | - |
| Washington | N | W | - | - | n | n | N |
| Aberdeen | N | N | - | - | n | n | - |
| Wesley Chapel | N | N | - | - | n | n | - |
| Oak Island | W | N | - | O | n | n | - |
| Oxford | N | N | - | - | n | n | - |
| Rockingham | N | N | - | - | n | n | - |
| Conover | N | N | - | - | n | n | - |
| Dunn | N | N | - | - | n | n | - |
| Black Mountain | N | N | - | - | n | n | - |
| Clinton | N | N | - | - | n | n | - |
| Roxboro | O | N | - | O | n | n | - |
| Angier | N | N | - | - | n | n | - |
| Fletcher | O | N | - | - | n | n | - |
| Woodfin | N | N | - | - | n | n | - |
| Butner | N | N | - | - | n | n | - |
| Siler City | N | N | - | - | n | n | - |
| Brevard | N | N | - | - | n | n | - |
| Oak Ridge | N | N | - | - | n | n | - |
| King | N | N | - | - | n | n | - |
| Kill Devil Hills | N | N | - | W | n | n | - |
| Marion | W | O | - | - | n | n | - |
| Mills River | N | N | - | - | n | n | - |
| Forest City | N | N | - | W | n | n | - |
| St. James | N | N | - | O | n | n | - |
| Unionville | N | N | - | - | n | n | - |
| Selma | O | O | - | - | n | n | - |
| Trinity | N | N | - | - | n | n | - |
| Marvin | N | N | - | - | n | n | - |
| Carolina Beach | N | N | - | - | n | n | - |
| Boiling Spring Lakes | N | N | - | O | n | n | - |
| Cherryville | N | N | - | - | n | n | - |
| Dallas | N | N | - | - | n | n | - |
| Mocksville | N | N | - | O | n | n | - |
| Stokesdale | N | N | - | - | n | n | - |
| Walkertown | N | N | - | - | n | n | - |
| Locust | N | N | - | - | n | n | - |
| Hamlet | N | N | - | - | n | n | - |
| Nashville | N | W | - | - | n | n | - |
| Holly Ridge | N | N | - | - | n | n | - |
| Bessemer City | N | N | - | - | n | n | - |
| Cramerton | N | N | - | - | n | n | - |
| Archer Lodge | N | N | - | - | n | n | - |
| Carolina Shores | N | N | - | O | n | n | - |
| Whispering Pines | N | N | - | - | n | n | - |
| Long View | N | N | - | - | n | n | - |
| Ayden | N | N | - | - | n | n | - |
| Shallotte | N | N | - | O | n | n | - |
| Pleasant Garden | N | N | - | - | n | n | - |
| Williamston | N | N | - | - | n | n | - |
| Sawmills | W | N | - | - | n | n | - |
| Midway | N | N | - | - | n | n | - |
| Creedmoor | W | N | - | - | n | n | - |
| Midland | N | N | - | - | n | n | - |

### 5.4 SC municipalities of 5,000+

| City | code | condemn | vacant reg | permits | fire | STR | city-owned |
|---|---|---|---|---|---|---|---|
| Charleston | O | N | N | O | n | O | - |
| Columbia | B | B | O | - | n | O | O |
| North Charleston | N | A | N | - | n | n | - |
| Mount Pleasant | A | N | N | - | n | n | - |
| Rock Hill | B | B | N | O | n | n | - |
| Greenville | N | N | N | O | n | n | - |
| Summerville | W | N | N | - | n | n | - |
| Goose Creek | W | W | N | W | n | n | - |
| Greer | O | O | N | O | n | n | - |
| Sumter | O | O | O | - | n | n | O |
| Florence | N | O | O | - | n | n | - |
| Myrtle Beach | N | A | N | - | n | n | N |
| Spartanburg | N | B | B | - | n | n | O |
| Hilton Head Island | N | N | N | O | n | O | - |
| Fort Mill | N | N | N | - | n | n | - |
| Bluffton | N | N | N | - | n | n | - |
| Aiken | W | W | W | - | n | n | - |
| Anderson | O | B | N | W | n | n | - |
| Mauldin | N | N | N | - | n | n | - |
| Conway | O | N | N | - | n | n | - |
| Simpsonville | W | N | N | - | n | n | - |
| Easley | N | O | N | - | n | n | - |
| North Augusta | W | W | W | - | n | n | - |
| Lexington | N | N | N | - | n | n | - |
| Greenwood | W | B | N | - | n | n | - |
| Hanahan | N | N | N | - | n | n | - |
| North Myrtle Beach | W | N | N | - | n | n | - |
| Clemson | W | - | O | - | n | n | - |
| West Columbia | N | A | N | - | n | n | - |
| Moncks Corner | N | N | N | - | n | n | - |
| Port Royal | N | N | N | - | n | n | - |
| Beaufort | W | N | N | - | n | O | N |
| Tega Cay | W | N | N | - | n | n | - |
| Hardeeville | N | N | N | - | n | n | - |
| Fountain Inn | W | N | N | - | n | n | - |
| Cayce | N | N | N | - | n | n | - |
| Orangeburg | A | N | N | - | n | n | - |
| Gaffney | N | N | N | - | n | n | - |
| James Island | N | N | N | - | n | n | - |
| Irmo | N | N | N | - | n | n | - |
| Newberry | N | N | N | - | n | n | - |
| Forest Acres | N | N | N | - | n | n | - |
| York | W | W | W | - | n | n | - |
| Lancaster | W | W | W | - | n | n | - |
| Laurens | N | N | N | - | n | n | - |
| Seneca | W | N | N | - | n | n | - |
| Travelers Rest | N | N | N | - | n | n | - |
| Camden | W | N | W | - | n | n | - |
| Georgetown | N | N | N | - | n | n | - |
| Union | W | W | W | - | n | n | - |
| Clinton | N | N | N | - | n | n | B |
| Bennettsville | N | N | N | - | n | n | - |
| Clover | W | W | W | - | n | n | - |
| Hartsville | W | W | W | - | n | n | - |
| Lyman | N | N | N | - | n | n | - |
| Blythewood | N | N | N | - | n | n | - |
| Dillon | N | N | N | - | n | n | - |
| Marion | N | N | N | - | n | n | - |
| Darlington | N | O | W | - | n | n | - |
| Lake City | N | N | N | - | n | n | - |
| Hollywood | W | W | W | - | n | n | - |
| Walterboro | N | N | N | - | n | n | - |
| Central | W | W | W | - | n | n | - |
| Batesburg-Leesville | W | W | W | - | n | n | - |
| Chester | N | N | N | - | n | n | - |
| Woodruff | W | N | N | W | n | n | - |

## 6. The 249 big-old tax rows with no mailing address and no phone

big_old_unlock_targets.csv (249 property-tax rows, $7,000+ and 2+ years late, no mailing and no phone): per-source count of rows it would supply a mailing address for. Measured where a join was run; otherwise an upper bound from county overlap.

| Source | County | Rows it would unlock | How measured |
|---|---|---|---|
| Dorchester County parcel layer (owner + mailing, open, licence clause) | Dorchester SC | 17 | measured join (FULL_TMS) |

None of the four new scrapers unlocks any of the 249 rows: none of the 249 sits in York, Nash, Edgecombe, Wake or Lenoir. The one source that measurably unlocks rows is the Dorchester parcel layer (all 17 Dorchester rows matched on FULL_TMS, all with a mailing address), held back since 2026-09-21 by its licence clause. Guilford's 34 rows carry no parcel id, so no layer can join them by parcel; Kershaw's open parcel layer has no owner field (15 rows stay locked).

## 7. Every source

Short form; the JSON carries fields, cadence, evidence and notes for each row. `new` = not ingested and not in an earlier doc.

| Source | Where | Category | Access | Volume (2026-10-07) | Ingested by | Effort h | New | Found by |
|---|---|---|---|---|---|---|---|---|
| Mebane condemnation/demolition actions and demolition fund | Mebane, Alamance, NC | condemned_demolition_unsafe | public-records-request |  | - |  | yes | subagent: NC towns 5k-22k (10… |
| Alamance in-rem tax foreclosures (future sales + upset bids) | Alamance, NC | tax_sale | open | 8 future-sale cases on 2026-10-07 (7 mention heirs) | - | 2 | yes | subagent: NC counties (100) t… |
| Alleghany County 2025 surplus properties list | Alleghany, NC | county_surplus | open | 1 page, ~31 text lines (a handful of parcels) | - | 1 | yes | subagent: NC counties (100) t… |
| Anson County foreclosures (Kania mirror) | Anson, NC | tax_sale | open |  | law_firms.kania | 0 | no | subagent: NC counties (100) t… |
| Ashe delinquent taxpayer list and pending tax foreclosures (stale 2018) | Ashe, NC | delinquent_tax | open | not opened (2018 files) | - | 0 | yes | subagent: NC counties (100) t… |
| Washington (Beaufort Co.) council demolition / title-search lists | Washington, Beaufort, NC | condemned_demolition_unsafe | public-records-request |  | - |  | yes | subagent: NC towns 5k-22k (10… |
| Bladen County-owned property for sale list | Bladen, NC | county_surplus | open | ~14 parcels on 2026-10-07 | - | 2 | yes | subagent: NC counties (100) t… |
| Brunswick County current building inspections layer | Brunswick, NC | building_permits | open | 519 rows on 2026-10-07; permitType Residential 453, Commerc… | - | 2 | yes | subagent: NC towns 5k-22k (10… |
| Oak Island code-enforcement sweep results | Oak Island, Brunswick, NC | code_enforcement | public-records-request |  | - |  | yes | subagent: NC towns 5k-22k (10… |
| Brunswick SurplusProperty layers | Brunswick, NC | county_surplus | open | 1 row each in /0 and /1 per repo doc | - | 1 | no | subagent: NC counties (100) t… |
| Brunswick County residential damage assessments (Florence 2018) | Brunswick, NC | flood_storm_damage | open | 5,777 | - | 1 | yes | lead agent: ArcGIS Online sea… |
| Buncombe County website (tax foreclosure / delinquent / surplus pages) | Buncombe, NC | delinquent_tax | bot-check |  | - |  | yes | subagent: NC counties (100) t… |
| Morganton city website | Morganton, Burke, NC | code_enforcement | bot-check |  | city_websites.cities |  | no | subagent: NC towns 5k-22k (10… |
| Burke tax foreclosure e-auctions on GovDeals | Burke, NC | tax_sale | open |  | nc_govdeals_real_property | 0 | no | subagent: NC counties (100) t… |
| Cabarrus County website (tax foreclosure / delinquent / surplus pages) | Cabarrus, NC | delinquent_tax | bot-check |  | - |  | yes | subagent: NC counties (100) t… |
| Kannapolis code enforcement Q1 2023 + North Kannapolis | Kannapolis, Cabarrus; Rowan, NC | code_enforcement | open | 252 (+66 North Kannapolis) | - | 1 | yes | lead agent: ArcGIS Online sea… |
| WPCOG regional code enforcement (Sawmills, Long View and other member towns) | Sawmills, Caldwell, NC | code_enforcement | public-records-request |  | - |  | no | subagent: NC towns 5k-22k (10… |
| Lenoir (Caldwell) council demolish / vacate-and-close ordinances | Lenoir, Caldwell, NC | condemned_demolition_unsafe | public-records-request |  | - |  | yes | subagent: NC towns 5k-22k (10… |
| Carteret tax foreclosure sales | Carteret, NC | tax_sale | open |  | nc_coastal_tax_foreclosure | 0 | no | subagent: NC counties (100) t… |
| Emerald Isle vacant parcels (2021) | Emerald Isle, Carteret, NC | vacant_registry | open | 619 | - | 1 | yes | lead agent: ArcGIS Online sea… |
| Catawba Clerk of Court mortgage-foreclosure upset-bid sheet | Catawba, NC | other | open | ~5 live files on 2026-10-07 (13 non-empty sheet rows incl. … | - | 2 | yes | subagent: NC counties (100) t… |
| Catawba County sheriff execution sale notices | Catawba, NC | sheriff_or_mie_sale | open |  | - | 2 | yes | lead agent: web search + dire… |
| Catawba Sheriff execution sales | Catawba, NC | sheriff_or_mie_sale | open | 1 notice on 2026-10-07 | - | 2 | yes | subagent: NC counties (100) t… |
| Catawba tax foreclosure sales search | Catawba, NC | tax_sale | open |  | nc_civicplus_tax_sale (generic) | 0 | no | subagent: NC counties (100) t… |
| Chatham County website (tax foreclosure / delinquent / surplus pages) | Chatham, NC | delinquent_tax | bot-check |  | - |  | yes | subagent: NC counties (100) t… |
| Chatham County tax foreclosures (active & sold) | Chatham, NC | tax_sale | open | 182 (+18 county-owned) | - | 1 | yes | lead agent: ArcGIS Online sea… |
| Chowan County upset-bid notice (county-owned tax-foreclosed property) | Chowan, NC | county_surplus | open | 1 active notice on 2026-10-07 | - | 1 | yes | subagent: NC counties (100) t… |
| Kings Mountain Citizen Problem Reporter (Blight -> Dilapidated Building) | Kings Mountain, Cleveland, NC | code_enforcement | open | 30 rows (per r2) | - |  | no | subagent: NC towns 5k-22k (10… |
| New Bern surplus sites / sellable property | New Bern, Craven, NC | county_surplus | open | 68 (+64 in Sellable_Prop2) | - | 1 | yes | lead agent: ArcGIS Online sea… |
| New Bern / Craven short-term rental parcels (2021) | New Bern, Craven, NC | str_registration | open | 58,185 parcels (registered subset unknown) | - | 2 | yes | lead agent: ArcGIS Online sea… |
| Craven County foreclosure parcels layer | Craven, NC | tax_sale | absent |  | - |  | yes | lead agent: ArcGIS Online sea… |
| Craven County property tax foreclosure list | Craven, NC | tax_sale | open | 3 parcels on 2026-10-07 (sales 2026-07-31 and 2026-09-25) | - | 2 | yes | subagent: NC counties (100) t… |
| Fayetteville code enforcement cases (2016 export) | Fayetteville, Cumberland, NC | code_enforcement | open | 15,410 (+135 demolitions layer) | - | 1 | yes | lead agent: ArcGIS Online sea… |
| Fayetteville surplus real property | Fayetteville, Cumberland, NC | county_surplus | bot-check |  | - |  | yes | subagent: NC counties (100) t… |
| Cumberland 2025 delinquent real estate taxes grid | Cumberland, NC | delinquent_tax | open | 3,755 rows on 2026-10-07 (pager 'Item 1 to 20 of 3755') | - | 3 | yes | subagent: NC counties (100) t… |
| Fayetteville substantial damage determinations (Hurricane Matthew) | Fayetteville, Cumberland, NC | flood_storm_damage | open | 47 | - | 1 | yes | lead agent: ArcGIS Online sea… |
| Currituck tax foreclosures page + execution sale notice | Currituck, NC | tax_sale | open | 0 sales ('There are NO ...') on 2026-10-07 | - | 1 | yes | subagent: NC counties (100) t… |
| Dare County / Kill Devil Hills monthly building permit reports | Kill Devil Hills, Dare, NC | building_permits | bot-check |  | - |  | no | subagent: NC towns 5k-22k (10… |
| Dare County website (tax foreclosure / delinquent / surplus pages) | Dare, NC | delinquent_tax | bot-check |  | - |  | yes | subagent: NC counties (100) t… |
| City of Lexington website (code enforcement / council) | Lexington, Davidson, NC | code_enforcement | bot-check |  | - |  | yes | subagent: NC towns 5k-22k (10… |
| Davidson 2025 tax lien advertisement list | Davidson, NC | delinquent_tax | open | 19 pages, ~3,170 amount-bearing lines on 2026-10-07 (est. ~… | - | 4 | yes | subagent: NC counties (100) t… |
| Davidson current and pending tax foreclosures PDF | Davidson, NC | tax_sale | open | 35 pages, ~55 amount lines on 2026-10-07 | nc_civicplus_tax_sale (pypdf path, 21 rows p… | 0 | no | subagent: NC counties (100) t… |
| Davie County monthly demolition permit reports (Residential / Commercial) | Mocksville, Davie, NC | building_permits | open | Jan-2026 residential PDF: ~3 rows (RDEM-26-2, -3 ...); sear… | - | 4 | yes | subagent: NC towns 5k-22k (10… |
| Davie tax liens listing (105-369 notice) | Davie, NC | delinquent_tax | open | 4 pages, ~475 lines x 2 entries (est. ~950 liens) on 2026-1… | - | 3 | yes | subagent: NC counties (100) t… |
| Duplin County tax foreclosure sale list | Duplin, NC | tax_sale | open | 3 parcels on 2026-10-07 | - | 1 | yes | subagent: NC counties (100) t… |
| Durham 2025 tax-lien advertisement (Spatialest delinquent list) | Durham, NC | delinquent_tax | disclaimer-click | 2,748 rows on 2026-10-07 (Count field) | - | 3 | yes | subagent: NC counties (100) t… |
| Durham Neighborhood Compass summary ejectments | Durham, Durham, NC | eviction | open |  | - |  | yes | lead agent: web search + dire… |
| Durham property tax foreclosure sale list | Durham, NC | tax_sale | open | 1 parcel 'For Sale' updated 9/16/2026 on 2026-10-07 | - | 2 | yes | subagent: NC counties (100) t… |
| Rocky Mount dilapidated + tax-delinquent parcels (council map) | Rocky Mount, Edgecombe, NC | condemned_demolition_unsafe | open | 110 | - | 1 | yes | lead agent: ArcGIS Online sea… |
| Edgecombe tax foreclosure list | Edgecombe, NC | tax_sale | open |  | edgecombe_tax_foreclosure | 0 | no | subagent: NC counties (100) t… |
| Forsyth County building permits (EnerGov) | Forsyth, NC | building_permits | open | 179,012 | - | 3 | yes | lead agent: ArcGIS Online sea… |
| Forsyth 105-369 tax lien advertisement (A-F, G-O, P-Z PDFs) | Forsyth, NC | delinquent_tax | open |  | nc_ptscloud_delinquent_tax (same roll via Fo… | 0 | no | subagent: NC counties (100) t… |
| Forsyth delinquent tax parcels (2024 copy) | Forsyth, NC | delinquent_tax | open | 5,623 | superseded by counties_nc.nc_ptscloud_delinq… | 0 | yes | lead agent: ArcGIS Online sea… |
| Forsyth eviction petitions (2021 research layer) | Winston-Salem, Forsyth, NC | eviction | open | 337 | - | 0 | yes | lead agent: ArcGIS Online sea… |
| Forsyth County Sheriff auctions | Winston-Salem, Forsyth, NC | sheriff_or_mie_sale | open | 4 auctions listed (all vehicles) on 2026-10-07; real proper… | - | 2 | yes | lead agent: web search + dire… |
| Forsyth tax foreclosure properties page | Forsyth, NC | tax_sale | open | 7 cases on 2026-10-07 (5 upset-bid period, 2 pending confir… | - | 2 | yes | subagent: NC counties (100) t… |
| Franklin County website (tax foreclosure / delinquent / surplus pages) | Franklin, NC | delinquent_tax | bot-check |  | - |  | yes | subagent: NC counties (100) t… |
| Gaston County 2026 building permits | Gaston, NC | building_permits | open | 1,990 | - | 2 | yes | lead agent: ArcGIS Online sea… |
| Gaston surplus properties listing | Gaston, NC | county_surplus | open |  | gaston_surplus_properties | 0 | no | subagent: NC counties (100) t… |
| Mount Holly property listings (marketed sites) | Mount Holly, Gaston, NC | other | open | 12 rows (per r2) | - |  | no | subagent: NC towns 5k-22k (10… |
| Gaston tax foreclosure sales (current + previous) | Gaston, NC | tax_sale | open |  | nc_county_tax_foreclosure | 0 | no | subagent: NC counties (100) t… |
| Gates County surplus land parcels | Gates, NC | county_surplus | open | 3 parcels on 2026-10-07 (1 in upset-bid process as of 10.01… | - | 1 | yes | subagent: NC counties (100) t… |
| Creedmoor code enforcement page | Creedmoor, Granville, NC | code_enforcement | bot-check |  | - |  | yes | subagent: NC towns 5k-22k (10… |
| Granville County website (tax foreclosure / delinquent / surplus pages) | Granville, NC | delinquent_tax | bot-check |  | - |  | yes | subagent: NC counties (100) t… |
| Greene County foreclosed and county-owned properties | Greene, NC | tax_sale | open | 1+ parcel listed on 2026-10-07 | - | 1 | yes | subagent: NC counties (100) t… |
| Guilford city/county owned properties | Guilford, NC | county_surplus | open | 500 | - | 1 | yes | lead agent: ArcGIS Online sea… |
| Guilford Tax_Delinquent_Report_ ArcGIS table | Guilford, NC | delinquent_tax | open | 9,749 rows per repo doc (2026-08-02); not re-fetched | nc_ptscloud_delinquent_tax (Guilford tenant … | 0 | no | subagent: NC counties (100) t… |
| UNCG housing study tax-delinquent / eviction layers (Greensboro) | Greensboro, Guilford, NC | delinquent_tax | open | 31 / 96 | - | 0 | yes | lead agent: ArcGIS Online sea… |
| Greensboro NC short-term rental registry | Greensboro, Guilford, NC | str_registration | open | 790 | - | 2 | yes | lead agent: ArcGIS Online sea… |
| Guilford ForeclosuresPublic tax-foreclosure layer | Guilford, NC | tax_sale | open | 931 parcels on 2026-10-07: Assigned To Attorney 895, Notice… | - | 3 | yes | subagent: NC counties (100) t… |
| Roanoke Rapids Minimum Housing Actions page | Roanoke Rapids, Halifax, NC | condemned_demolition_unsafe | open | 0 listings on 2026-10-07 (heading 'Minimum Housing Action D… | - | 1 | yes | subagent: NC towns 5k-22k (10… |
| Harnett County code-enforcement cases (TRAKiT) layer | Harnett, NC | code_enforcement | open | 118 rows on 2026-10-07; newest STARTED 2026-09-10 | - | 3 | yes | subagent: NC towns 5k-22k (10… |
| Harnett County code-enforcement case attachments directory (unsafe-building ord… | Harnett, NC | condemned_demolition_unsafe | open | 1,064 case folders on 2026-10-07: CEEH 524 (newest 2026-10-… | - | 6 | yes | subagent: NC towns 5k-22k (10… |
| Harnett tax foreclosures table | Harnett, NC | tax_sale | open | ~9 rows (11 table rows incl header) on 2026-10-07, auction … | - | 2 | yes | subagent: NC counties (100) t… |
| Haywood tax foreclosures + bid postings | Haywood, NC | tax_sale | open |  | haywood_tax_foreclosures | 0 | no | subagent: NC counties (100) t… |
| Fletcher code-enforcement tracker (Survey123 results) | Fletcher, Henderson, NC | code_enforcement | open | 10 live cases (per r2) | - | 2 | no | subagent: NC towns 5k-22k (10… |
| Henderson tax foreclosure sales page + map | Henderson, NC | tax_sale | open |  | henderson_foreclosure_parcels | 0 | no | subagent: NC counties (100) t… |
| Hendersonville vacant / condemned structures registry | Hendersonville, Henderson, NC | vacant_registry | open | 47 rows on SOURCE_REGISTER | counties_nc.hendersonville_vacant_structures | 0 | no | subagent: NC towns 5k-22k (10… |
| Hertford County-owned foreclosure properties | Hertford, NC | county_surplus | open | 0 rows in HTML table on 2026-10-07 (list moved to StoryMap,… | - | 2 | yes | subagent: NC counties (100) t… |
| Hoke County surplus properties for sale | Hoke, NC | county_surplus | open | ~6 rows (7 <tr>) on 2026-10-07 | - | 1 | yes | subagent: NC counties (100) t… |
| Hoke County 2025 delinquent tax ad lists (non-transferred + transferred) | Hoke, NC | delinquent_tax | open | non-transferred: 53 pages, ~2,667 amount rows; transferred:… | - | 3 | yes | subagent: NC counties (100) t… |
| Hoke County upcoming tax foreclosure sales | Hoke, NC | tax_sale | open | 23 rows on 2026-10-07 | - | 2 | yes | subagent: NC counties (100) t… |
| Hyde County website (tax foreclosure / delinquent / surplus pages) | Hyde, NC | delinquent_tax | bot-check |  | - |  | yes | subagent: NC counties (100) t… |
| Statesville code enforcement by ward | Statesville, Iredell, NC | code_enforcement | open | 76 (ward 1) | - | 1 | yes | lead agent: ArcGIS Online sea… |
| Iredell County surplus real property listings | Iredell, NC | county_surplus | open | ~13 listing rows (16 table rows incl. headers) on 2026-10-07 | - | 1 | yes | subagent: NC counties (100) t… |
| Iredell County delinquent taxes layer | Iredell, NC | delinquent_tax | absent |  | - |  | no | lead agent: ArcGIS Online sea… |
| Iredell DelinquentTaxes parcel layer | Iredell, NC | delinquent_tax | open | 2,391 parcels on 2026-10-07, ASOF 2026-10-06 | - | 4 | yes | subagent: NC counties (100) t… |
| Statesville fire call data by ward (2024, 2025) | Statesville, Iredell, NC | fire_incident | open | 1,412 (2024) + 1,543 (2025) in ward 1 alone | - | 2 | yes | lead agent: ArcGIS Online sea… |
| Selma open code violations / blighted properties monthly lists | Selma, Johnston, NC | code_enforcement | open | 45 PDFs found via WP media API on 2026-10-07; newest blight… | - | 3 | yes | subagent: NC towns 5k-22k (10… |
| Johnston County tax foreclosure auctions + county-owned surplus | Johnston, NC | tax_sale | open | 0 rows on 2026-10-07 ('No Sale Scheduled At This Time'); su… | - | 1 | yes | subagent: NC counties (100) t… |
| Smithfield vacant building registry (commercial, 90-day) | Smithfield, Johnston, NC | vacant_registry | public-records-request |  | - | 1 | yes | subagent: NC towns 5k-22k (10… |
| Lee County surplus property upset-bid notices | Lee, NC | county_surplus | open | 5 posts in news list on 2026-10-07 | - | 1 | yes | subagent: NC counties (100) t… |
| Lee County 2025 delinquent real property list | Lee, NC | delinquent_tax | open | 77 pages, ~2,740 amount rows on 2026-10-07 | - | 3 | yes | subagent: NC counties (100) t… |
| City of Kinston 2026 proposed demolition list | Kinston, Lenoir, NC | condemned_demolition_unsafe | open | 45 (2026-10-07, last edit 2026-06-04) | counties_nc.kinston_proposed_demolition (bui… | 2 | no | lead agent: ArcGIS Online sea… |
| Kinston condemnation list and citywide/corridor demolition project lists | Kinston, Lenoir, NC | condemned_demolition_unsafe | public-records-request | news 2026-01-02: 118 properties remain on the condemnation … | - | 4 | yes | subagent: NC towns 5k-22k (10… |
| Kinston city-owned vacant lot sale list (annual December surplus list) | Kinston, Lenoir, NC | county_surplus | absent | news 2022-10: ~40 lots listed; city owns ~1,000 vacant parc… | - | 2 | yes | subagent: NC towns 5k-22k (10… |
| Lenoir County surplus real property (land) | Lenoir, NC | county_surplus | open | 0 structured rows on 2026-10-07 (narrative only) | - | 1 | yes | subagent: NC counties (100) t… |
| Kinston heirs-property layer | Kinston, Lenoir, NC | probate | login |  | - |  | yes | lead agent: ArcGIS Online sea… |
| Lincoln County / Lincolnton eTRAKiT code complaint search | Lincolnton, Lincoln, NC | code_enforcement | login |  | - |  | no | subagent: NC towns 5k-22k (10… |
| Lincoln County code violations (covers Lincolnton area) | Lincolnton, Lincoln, NC | code_enforcement | open |  | counties_nc.lincoln_code_violations | 0 | no | subagent: NC towns 5k-22k (10… |
| Lincoln tax foreclosure sale notice (2026-10-22) | Lincoln, NC | tax_sale | open | 3 pages (a few parcels) | law_firms.kania (Lincoln files) | 0 | no | subagent: NC counties (100) t… |
| Macon County surplus real property for sale | Macon, NC | county_surplus | open | ~18 parcel rows (21 table rows incl. layout/header) on 2026… | - | 1 | yes | subagent: NC counties (100) t… |
| Madison County surplus real property | Madison, NC | county_surplus | open | ~2 parcels in the 0826 PDF on 2026-10-07 | - | 1 | yes | subagent: NC counties (100) t… |
| Marion OpenGov/ViewPoint permitting (code violation + demolition record types) | Marion, McDowell, NC | code_enforcement | JS-app |  | - |  | no | subagent: NC towns 5k-22k (10… |
| Marion building-condition survey (xbEbU) | Marion, McDowell, NC | condemned_demolition_unsafe | open | 123 rows, 79 at condition >=4 (per r3) | - | 2 | no | subagent: NC towns 5k-22k (10… |
| McDowell 105-369 lien advertisement PDF | McDowell, NC | delinquent_tax | open |  | nc_county_pdf_delinquent_tax | 0 | no | subagent: NC counties (100) t… |
| Mecklenburg building permit locations | Mecklenburg, NC | building_permits | open | 482,399 | - | 3 | yes | lead agent: ArcGIS Online sea… |
| Charlotte code enforcement orders to demolish | Charlotte, Mecklenburg, NC | condemned_demolition_unsafe | open | 15 | likely inside city_websites.charlotte_open_d… | 0.5 | yes | lead agent: ArcGIS Online sea… |
| Charlotte city properties for sale (upset bid) | Charlotte, Mecklenburg, NC | county_surplus | bot-check |  | - |  | yes | subagent: NC counties (100) t… |
| Mecklenburg County owned parcels | Mecklenburg, NC | county_surplus | open | 2,449 | - | 1 | yes | lead agent: ArcGIS Online sea… |
| Mecklenburg TaxCollections Back Bills layer | Mecklenburg, NC | delinquent_tax | open | 93,916 rows on 2026-10-07; sibling layer 0 '2024 Bills' 18,… | - | 4 | yes | subagent: NC counties (100) t… |
| Mecklenburg delinquent taxpayer publication (annual 105-369 ad) | Mecklenburg, NC | delinquent_tax | open | per repo doc: 1,087-page PDF, 129,606 rows, ~2,950 real-est… | - | 6 | no | subagent: NC counties (100) t… |
| Mecklenburg Sheriff public auctions (execution sales) | Charlotte, Mecklenburg, NC | sheriff_or_mie_sale | bot-check |  | - |  | no | lead agent: web search + dire… |
| Mecklenburg TaxForeclosures parcel layer | Mecklenburg, NC | tax_sale | open | 618 parcels on 2026-10-07 (UNASSIGNED 363, RBCWB 116, KANIA… | - | 3 | yes | subagent: NC counties (100) t… |
| Mecklenburg in-rem tax foreclosures (County Attorney) | Mecklenburg, NC | tax_sale | open | 66 INREM parcels in the TaxForeclosures layer on 2026-10-07 | - | 1 | yes | subagent: NC counties (100) t… |
| Mecklenburg tax foreclosure attorney assignments | Mecklenburg, NC | tax_sale | open | 314 (+81 floodplain subset) | - | 1 | yes | lead agent: ArcGIS Online sea… |
| RBCWB Mecklenburg tax foreclosure listings | Mecklenburg, NC | tax_sale | open | 24 rows on 2026-10-07 | - | 2 | no | subagent: NC counties (100) t… |
| Pinehurst fire incidents (FirstDue) | Pinehurst, Moore, NC | fire_incident | open | 462 | - | 1 | yes | lead agent: ArcGIS Online sea… |
| Nashville (Nash Co.) demolition ordinances for abandoned/derelict structures | Nashville, Nash, NC | condemned_demolition_unsafe | bot-check |  | - |  | yes | subagent: NC towns 5k-22k (10… |
| Rocky Mount Nash dilapidated parcels (city, 2023) | Rocky Mount, Nash, NC | condemned_demolition_unsafe | open | 142 | - | 1 | yes | lead agent: ArcGIS Online sea… |
| Nash County delinquent tax list page (stale 2017 lien ad) | Nash, NC | delinquent_tax | open |  | - | 0 | yes | subagent: NC counties (100) t… |
| Rocky Mount 2025 parcel condition survey (dilapidated / deteriorated / vacant-b… | Rocky Mount, Nash; Edgecombe, NC | condemned_demolition_unsafe | open | 651 layer rows / 618 parcels (2026-10-07) | counties_nc.rocky_mount_blight_survey (built… | 3 | no | lead agent: ArcGIS Online sea… |
| Rocky Mount urban delinquent taxes (city layer) | Rocky Mount, Nash; Edgecombe, NC | delinquent_tax | open | 3,985 | - | 2 | yes | lead agent: ArcGIS Online sea… |
| New Hanover delinquent real estate CSV/Excel | New Hanover, NC | delinquent_tax | open |  | nc_county_csv_delinquent_tax | 0 | no | subagent: NC counties (100) t… |
| New Hanover foreclosures page (Kania) | New Hanover, NC | tax_sale | open |  | law_firms.kania | 0 | no | subagent: NC counties (100) t… |
| Onslow County residential issued permits | Onslow, NC | building_permits | open | 661 | - | 1 | yes | lead agent: ArcGIS Online sea… |
| Onslow County website (tax foreclosure / delinquent / surplus pages) | Onslow, NC | delinquent_tax | bot-check |  | - |  | yes | subagent: NC counties (100) t… |
| Hillsborough code enforcement page | Hillsborough, Orange, NC | code_enforcement | bot-check |  | - |  | yes | subagent: NC towns 5k-22k (10… |
| Orange County property for sale (county-owned, upset bid) | Orange, NC | county_surplus | open | 2 PINs on 2026-10-07 | - | 1 | yes | subagent: NC counties (100) t… |
| Orange County 2025 tax liens (PDF + Excel) | Orange, NC | delinquent_tax | open | 1,803 data rows on 2026-10-07 | nc_ptscloud_delinquent_tax (Orange tenant ex… | 1 | no | subagent: NC counties (100) t… |
| Elizabeth City council condemnation / demolition ordinances | Elizabeth City, Pasquotank, NC | condemned_demolition_unsafe | public-records-request |  | - |  | yes | subagent: NC towns 5k-22k (10… |
| Pasquotank 2026 delinquent taxes notice | Pasquotank, NC | delinquent_tax | open | 3 pages, ~480 rows on 2026-10-07 | - | 2 | yes | subagent: NC counties (100) t… |
| Pender County auction of surplus property - tax foreclosures | Pender, NC | county_surplus | open |  | - | 1 | yes | subagent: NC counties (100) t… |
| Surf City code enforcement map | Surf City, Pender; Onslow, NC | code_enforcement | open | 941 parcels | - | 1 | yes | lead agent: ArcGIS Online sea… |
| Perquimans tax foreclosure sale notices | Perquimans, NC | tax_sale | open | 1 current notice | - | 1 | yes | subagent: NC counties (100) t… |
| Person County / City of Roxboro EnerGov permit history (demolition permits) | Roxboro, Person, NC | building_permits | open | 12,771 permit points on 2026-10-07; CaseType='Demolition' 4… | - | 3 | yes | subagent: NC towns 5k-22k (10… |
| Person County / Roxboro EnerGov code-case points | Roxboro, Person, NC | code_enforcement | open | 19 rows on 2026-10-07 | - | 1 | yes | subagent: NC towns 5k-22k (10… |
| Person County minimum housing cases 2023 | Roxboro, Person, NC | code_enforcement | open | 222 | - | 1 | yes | lead agent: ArcGIS Online sea… |
| Person County website (tax foreclosure / delinquent / surplus pages) | Person, NC | delinquent_tax | bot-check |  | - |  | yes | subagent: NC counties (100) t… |
| Pitt DelinquentTaxesPOD open-data table | Pitt, NC | delinquent_tax | open | 9,170 rows per repo doc (2026-08-02); not re-fetched | nc_ptscloud_delinquent_tax (Pitt tenant) | 0 | no | subagent: NC counties (100) t… |
| Randolph 2026 tax lien advertisement PDFs (by surname letter) | Randolph, NC | delinquent_tax | open | 'A' file alone: 5 pages, 198 amount rows, 199 PIN-like toke… | - | 4 | yes | subagent: NC counties (100) t… |
| Archdale-area geocoded liens | Archdale (inferred), Randolph, NC | municipal_tax_or_fee_lien | open | 66 | - | 1 | yes | lead agent: ArcGIS Online sea… |
| Lumberton council demolition approvals (inspections director requests) | Lumberton, Robeson, NC | condemned_demolition_unsafe | public-records-request |  | - |  | yes | subagent: NC towns 5k-22k (10… |
| Robeson County tax public auctions | Robeson, NC | tax_sale | open | ~4 parcels on 2026-10-07 | law_firms.zacchaeus (partial; ZLS runs Robes… | 2 | no | subagent: NC counties (100) t… |
| Reidsville code enforcement (outstanding dilapidated building and nuisance prop… | Reidsville, Rockingham, NC | code_enforcement | bot-check |  | - |  | yes | subagent: NC towns 5k-22k (10… |
| Eden Human Habitation Standards demolition memos / ordinances | Eden, Rockingham, NC | condemned_demolition_unsafe | bot-check |  | - |  | yes | subagent: NC towns 5k-22k (10… |
| Rockingham County website (tax foreclosure / delinquent / surplus pages) | Rockingham, NC | delinquent_tax | bot-check |  | - |  | yes | subagent: NC counties (100) t… |
| Salisbury chronic abatement layer | Salisbury, Rowan, NC | code_enforcement | login |  | - |  | yes | lead agent: ArcGIS Online sea… |
| Salisbury minimum housing violations (2017) | Salisbury, Rowan, NC | code_enforcement | open | 61 | - | 1 | yes | lead agent: ArcGIS Online sea… |
| Rowan delinquent taxpayer lists (annual XLS + PDF, 2019-2025) | Rowan, NC | delinquent_tax | open | 2025 file: 6,542 rows on 2026-10-07 (REAL 2,699 / PP 3,839 … | - | 3 | yes | subagent: NC counties (100) t… |
| Rowan tax foreclosures page (Kania) | Rowan, NC | tax_sale | open |  | law_firms.kania | 0 | no | subagent: NC counties (100) t… |
| Forest City SmartGov portal | Forest City, Rutherford, NC | building_permits | login |  | - |  | no | subagent: NC towns 5k-22k (10… |
| Rutherford TR-452 delinquent bills report (XLS) | Rutherford, NC | delinquent_tax | open |  | rutherford_tax | 0 | no | subagent: NC counties (100) t… |
| Sampson County website (tax foreclosure / delinquent / surplus pages) | Sampson, NC | delinquent_tax | bot-check |  | - |  | yes | subagent: NC counties (100) t… |
| Albemarle minimum-housing demolition ordinances / program updates (council PDFs) | Albemarle, Stanly, NC | condemned_demolition_unsafe | bot-check |  | - |  | yes | subagent: NC towns 5k-22k (10… |
| Stokes County-owned surplus property | Stokes, NC | county_surplus | open | 0 data rows (header only) on 2026-10-07 | - | 1 | yes | subagent: NC counties (100) t… |
| Weddington code enforcement (Centralina contract) | Weddington, Union, NC | code_enforcement | public-records-request |  | - |  | yes | subagent: NC towns 5k-22k (10… |
| Union County delinquent tax lien advertisement + property tax foreclosure aucti… | Union, NC | delinquent_tax | bot-check |  | - |  | yes | subagent: NC counties (100) t… |
| Henderson Code Compliance Notice of Hearing page | Henderson, Vance, NC | condemned_demolition_unsafe | open | 0 notices on 2026-10-07 (page body empty) | - | 1 | yes | subagent: NC towns 5k-22k (10… |
| Vance County surplus properties - land (incl. parcels jointly owned with City o… | Henderson, Vance, NC | county_surplus | open | 0 parcels listed on 2026-10-07 (procedure + offer form only… | - | 1 | yes | subagent: NC towns 5k-22k (10… |
| Raleigh building permits | Raleigh, Wake, NC | building_permits | open | 184,461 | - | 3 | yes | lead agent: ArcGIS Online sea… |
| Wake County building permits | Wake, NC | building_permits | open | 197,477 | - | 3 | yes | lead agent: ArcGIS Online sea… |
| City of Raleigh owned undeveloped property | Raleigh, Wake, NC | county_surplus | open | 946 | - | 1 | yes | lead agent: ArcGIS Online sea… |
| City of Raleigh fire incidents (structure fires) | Raleigh, Wake, NC | fire_incident | open | 323,778 incidents total; 210 building fires in 2025; 142 st… | city_websites.raleigh_structure_fires (built… | 3 | no | lead agent: ArcGIS Online sea… |
| Wake tax foreclosures (sheriff auctions) | Wake, NC | tax_sale | open |  | wake_tax_foreclosure | 0 | no | subagent: NC counties (100) t… |
| Warren County tax foreclosures (ZLS) | Warren, NC | tax_sale | JS-app |  | law_firms.zacchaeus | 0 | no | subagent: NC counties (100) t… |
| Washington County surplus real property listings | Washington, NC | county_surplus | open | 0 listings visible on 2026-10-07 | - | 1 | yes | subagent: NC counties (100) t… |
| Blowing Rock abandoned water service points | Blowing Rock, Watauga; Caldwell, NC | utility_shutoff | open | 74 | - | 1 | yes | lead agent: ArcGIS Online sea… |
| City of Goldsboro special assessments & nuisance abatements | Goldsboro, Wayne, NC | municipal_tax_or_fee_lien | open |  | - | 2 | yes | subagent: NC counties (100) t… |
| Wayne County tax foreclosure sales (CivicAlerts posts) | Wayne, NC | tax_sale | open | 3 sale posts listed on 2026-10-07 (next sale 2026-10-21) | - | 2 | yes | subagent: NC counties (100) t… |
| Wilson County website (tax foreclosure / delinquent / surplus pages) | Wilson, NC | delinquent_tax | bot-check |  | - |  | yes | subagent: NC counties (100) t… |
| Iron Horse Auction Co. (Rockingham NC) real estate auctions | statewide, NC | auction | open | 45 auction links on the home page incl. NC and SC land/hous… | - | 3 | no | lead agent: web search + dire… |
| Public Surplus (NCACC partner) government auctions | statewide, NC | auction | JS-app |  | - |  | no | lead agent: web search + dire… |
| Rogers Auction Group (Mount Airy NC) | statewide, NC | auction | open | about 40 auction detail links (2026-10-07) | - | 3 | no | lead agent: web search + dire… |
| LSC Civil Court Data Initiative (NC eviction counts) | statewide, NC | eviction | open |  | - |  | yes | lead agent: web search + dire… |
| NC Judgment Search: summary ejectment money judgments | statewide, NC | eviction | open |  | - | 4 | no | lead agent: web search + dire… |
| NC eCourts Smart Search: summary ejectment filings | statewide, NC | eviction | CAPTCHA |  | - |  | no | lead agent: web search + dire… |
| Craven/Pender/Moore/Martin/Chowan/Robeson/Guilford ZLS listings | statewide, NC | tax_sale | JS-app |  | law_firms.zacchaeus | 0 | no | subagent: NC counties (100) t… |
| Kania Law Firm tax foreclosure listings (county pointers) | statewide, NC | tax_sale | open |  | law_firms.kania | 0 | no | subagent: NC counties (100) t… |
| taxsaleresources.com NC county tax deed sale pages | statewide, NC | tax_sale | paid | Iredell 2026-08-17 sale: 2 parcels; 2026-04-13: 10 parcels;… | - |  | yes | subagent: NC counties (100) t… |
| Utility disconnect / water shut-off lists (NC) | statewide, NC | utility_shutoff | absent |  | - |  | no | lead agent: web search + dire… |
| Abbeville County delinquent tax sale (newspaper only) and FLC mobile-home assig… | Abbeville, SC | tax_sale | JS-app |  | - | 0 | yes | subagent: SC counties (46) ta… |
| Aiken County tax collector overage claims | Aiken, SC | tax_sale | disclaimer-click |  | - | 0 | yes | subagent: SC counties (46) ta… |
| Anderson County Environmental Code Enforcement (OpenGov portal) | Anderson, SC | code_enforcement | JS-app |  | - | 0 | yes | subagent: SC counties (46) ta… |
| Upstate cities already documented (Anderson, Clemson, Spartanburg, Clinton, Gre… | Anderson, Anderson, SC | condemned_demolition_unsafe | open | Anderson code layer re-checked 2026-10-07: still 10 rows | spartanburg_city_condemned, spartanburg_vaca… | 2 | no | subagent: SC cities (66) + SC… |
| Bamberg County overage claims page | Bamberg, SC | tax_sale | absent |  | - | 0 | yes | subagent: SC counties (46) ta… |
| Bamberg County tax sale list (annual PDF) | Bamberg, SC | tax_sale | open | 698 distinct TMS in the 2025 list (PDF created 2025-11-17) | - | 3 | yes | subagent: SC counties (46) ta… |
| Bamberg / Jasper / Dillon / Newberry code enforcement pages | Bamberg, Jasper, SC | code_enforcement | absent |  | - | 0 | yes | subagent: SC counties (46) ta… |
| Barnwell County Tax Sales Information | Barnwell, SC | tax_sale | absent |  | - | 0 | yes | subagent: SC counties (46) ta… |
| Charleston/Beaufort/Georgetown/Greenwood/Oconee county EnerGov or CitizenServe … | Beaufort, SC | building_permits | open | Beaufort permits 900 rows; Georgetown GCGIS_Energov, Greenw… | - | 0 | yes | subagent: SC cities (66) + SC… |
| Hilton Head Island EnerGov permits / SeeClickFix (ArcGIS) | Hilton Head Island, Beaufort, SC | building_permits | open | 7,467 permit rows; no demolition or code type in Type values | - | 0 | yes | subagent: SC cities (66) + SC… |
| Beaufort County Code Enforcement | Beaufort, SC | code_enforcement | absent |  | - | 0 | yes | subagent: SC counties (46) ta… |
| Beaufort code-enforcement portal (Brightly) | Beaufort, Beaufort, SC | code_enforcement | JS-app |  | - |  | yes | subagent: SC cities (66) + SC… |
| Beaufort County MIE foreclosure list information | Beaufort, SC | sheriff_or_mie_sale | disclaimer-click |  | counties_sc.sc_coastal_rosters | 0 | no | subagent: SC counties (46) ta… |
| City of Beaufort SC short-term rentals | Beaufort, Beaufort, SC | str_registration | open | 280 | - | 1 | yes | lead agent: ArcGIS Online sea… |
| Hilton Head Island STR business licenses | Hilton Head Island, Beaufort, SC | str_registration | open | 4,785 | - | 2 | yes | lead agent: ArcGIS Online sea… |
| Goose Creek GIS (EnerGov / OpenGov folders) | Goose Creek, Berkeley, SC | code_enforcement | login |  | - |  | no | subagent: SC cities (66) + SC… |
| Calhoun County 2026 tax sale list (to be posted on the Tax Collector page) | Calhoun, SC | tax_sale | open | not yet posted on 2026-10-07 | - | 3 | yes | subagent: SC counties (46) ta… |
| Charleston County 2025 building permits | Charleston, SC | building_permits | open | 1,781 | - | 2 | yes | lead agent: ArcGIS Online sea… |
| City of Charleston open-data hub (data-charleston-sc) | Charleston, Charleston, SC | building_permits | open | 147 datasets 2026-10-07; 0 code/condemned/vacant/demolition… | - | 0 | no | subagent: SC cities (66) + SC… |
| Charleston County EnerGov history: code cases + demolition permits (ArcGIS) | Charleston, SC | code_enforcement | open | 386,386 rows on 2026-10-07. CodeManagement: Building Servic… | - | 4 | yes | subagent: SC cities (66) + SC… |
| Charleston Municipal Court Livability docket (upcoming / disposed PDFs) | Charleston, Charleston, SC | code_enforcement | open | docket dated 2026-09-28, 9 pages | - | 3 | yes | subagent: SC cities (66) + SC… |
| City of Charleston Citizen Services monthly request dashboards | Charleston, Charleston, SC | code_enforcement | open | Sept 2026 service: 57 request types; 'Overgrown yard or vac… | - | 3 | yes | subagent: SC cities (66) + SC… |
| City of Charleston Livability daily log (Survey123) | Charleston, Charleston, SC | code_enforcement | open | 14,719 rows 2021-01-20 to 2026-10-07 (Trash_removal_dumpout… | - | 2 | yes | subagent: SC cities (66) + SC… |
| Mount Pleasant town GIS (maps.tompsc.com + AGOL lzpM6epdQtzxVX5J) | Mount Pleasant, Charleston, SC | code_enforcement | absent | 0 code/condemned/vacant layers | - | 0 | yes | subagent: SC cities (66) + SC… |
| North Charleston code enforcement (no public list) | North Charleston, Charleston, SC | condemned_demolition_unsafe | absent |  | - | 0 | yes | subagent: SC cities (66) + SC… |
| Charleston County Government Owned Parcels | Charleston, SC | county_surplus | open |  | - | 2 | yes | subagent: SC cities (66) + SC… |
| Eviction Lab Eviction Tracking System (Charleston SC) | Charleston, Charleston, SC | eviction | open | 11,384 filings in 12 months (Charleston) | - |  | yes | lead agent: web search + dire… |
| City of Charleston SC short-term rental permits | Charleston, Charleston, SC | str_registration | open | 886 | - | 2 | no | lead agent: ArcGIS Online sea… |
| Isle of Palms STR licenses (Jan 2024) | Isle of Palms, Charleston, SC | str_registration | open | 1,827 | - | 1 | yes | lead agent: ArcGIS Online sea… |
| Chesterfield County Tax Collector FAQ | Chesterfield, SC | tax_sale | absent |  | - | 0 | yes | subagent: SC counties (46) ta… |
| Clarendon County 2026 tax sale registration notice | Clarendon, SC | tax_sale | absent |  | - | 0 | yes | subagent: SC counties (46) ta… |
| Colleton County public nuisance page | Colleton, SC | code_enforcement | absent |  | - | 0 | yes | subagent: SC counties (46) ta… |
| Colleton County tax sale list PDF | Colleton, SC | tax_sale | open | 373 Map Numbers (PDF created 2026-01-29, sale 2026-02-20, t… | counties_sc.colleton_tax_sale | 0 | no | subagent: SC counties (46) ta… |
| Darlington County codes enforcement service (address base) | Darlington, SC | code_enforcement | open | 34,568 address points; 0 cases | - | 0 | yes | subagent: SC cities (66) + SC… |
| City of Darlington demolition bid notices (parcel lists) | Darlington, Darlington, SC | condemned_demolition_unsafe | open | 3 parcels per notice (2022: 3+, 2024: 3) | - | 1 | yes | subagent: SC cities (66) + SC… |
| Darlington County fire incidents | Darlington, SC | fire_incident | open | 50 | - | 1 | yes | lead agent: ArcGIS Online sea… |
| Darlington County Delinquent Tax Collector page | Darlington, SC | tax_sale | absent |  | - | 0 | yes | subagent: SC counties (46) ta… |
| City of Darlington vacant building registration program (no public roster) | Darlington, Darlington, SC | vacant_registry | public-records-request |  | - |  | yes | subagent: SC cities (66) + SC… |
| Dillon County delinquent tax sale list (PAPER.xlsx) | Dillon, SC | tax_sale | open | 343 rows (2026-09-22 export, per module docstring); link ti… | counties_sc.dillon_delinquent_tax | 0 | no | subagent: SC counties (46) ta… |
| Dorchester County parcel layer (owner + mailing, open, licence clause) | Dorchester, SC | absentee_owner | terms-only | 80,111 parcels | - | 1 | no | lead agent: ArcGIS Online sea… |
| Town of Summerville code cases (CitizenServe portal, installation 301) | Summerville, Dorchester, SC | code_enforcement | JS-app |  | - |  | yes | subagent: SC cities (66) + SC… |
| Dorchester County Lands (county-owned parcels) | Dorchester, SC | county_surplus | open | 631 rows (2026-10-07) | - | 1 | yes | subagent: SC cities (66) + SC… |
| Dorchester County delinquent tax 2025 (real property + mobile homes) ArcGIS | Dorchester, SC | delinquent_tax | open | RP_2025 584 rows; MH_2025 263 rows (2026-10-07) | - | 2 | yes | subagent: SC cities (66) + SC… |
| Fairfield County Forfeited Land Commission page | Fairfield, SC | county_surplus | absent |  | - | 0 | yes | subagent: SC counties (46) ta… |
| Fairfield County 2026 tax sale schedule (list posts Oct 15 on Tax Collector pag… | Fairfield, SC | tax_sale | open | 2025 list 305 TMS (per breadth doc); 2026 list not posted y… | - | 2 | no | subagent: SC counties (46) ta… |
| Fairfield County tax sale overage list | Fairfield, SC | tax_sale | open | 60 TMS (PDF created 2026-09-15) | counties_sc.fairfield_overage_claims | 0 | no | subagent: SC counties (46) ta… |
| City of Florence unfit-dwelling hearing notices (newspaper legals) | Florence, Florence, SC | condemned_demolition_unsafe | open | search snippets show 3 notices 2025-08 to 2026-01; ad pages… | - |  | yes | subagent: SC cities (66) + SC… |
| Florence County delinquent-tax posting routes (TMS posting status) | Florence, SC | delinquent_tax | open | 3,668 points: POSTED 2,972, PROCESSING 636, SKIP 59, NO DIR… | - | 1 | no | subagent: SC cities (66) + SC… |
| City of Florence vacant properties snapshot (utility accounts, 2021) | Florence, Florence, SC | vacant_registry | open | 1,632 rows | - | 2 | yes | subagent: SC cities (66) + SC… |
| City of Greenville SC building permits (prior two years) | Greenville, Greenville, SC | building_permits | open | 4,056 | - | 2 | no | lead agent: ArcGIS Online sea… |
| City of Greer code cases opened 2023 (+ Q4 2022) snapshots | Greer, Greenville, SC | code_enforcement | open | 1,743 rows: CONDEMNATION 37, BUILDING VIOLATIONS EXTERIOR 1… | - | 2 | yes | subagent: SC cities (66) + SC… |
| Fountain Inn code-enforcement portal (iWorQ) | Fountain Inn, Greenville, SC | code_enforcement | JS-app |  | - |  | yes | subagent: SC cities (66) + SC… |
| Simpsonville code-enforcement portal (Evolve) | Simpsonville, Greenville, SC | code_enforcement | JS-app |  | - |  | yes | subagent: SC cities (66) + SC… |
| Greenville County Unfit Structure Search | Greenville, SC | condemned_demolition_unsafe | bot-check |  | - |  | no | subagent: SC cities (66) + SC… |
| Greenville County monthly Planning Report (code enforcement narrative) | Greenville, SC | condemned_demolition_unsafe | open | Feb 2026 report: 1 unfit hearing address, 1 demolition addr… | - | 3 | yes | subagent: SC cities (66) + SC… |
| Greer code cases Q4 2022 | Greer, Greenville; Spartanburg, SC | code_enforcement | open | 292 | - | 1 | yes | lead agent: ArcGIS Online sea… |
| Greenwood code-enforcement portal (CitizenServe) | Greenwood, Greenwood, SC | code_enforcement | JS-app |  | - |  | yes | subagent: SC cities (66) + SC… |
| Greenwood County Tax Collector page | Greenwood, SC | tax_sale | absent |  | - | 0 | yes | subagent: SC counties (46) ta… |
| Saluda/Greenwood/Edgefield/Laurens special-referee sale lists (McDonald Patrick) | Greenwood, Laurens, Saluda, Edgefield (pages… | sheriff_or_mie_sale | open | 4 PDFs dated 2026-09-21 for Oct 5-6, 2026 sales; Laurens li… | - | 3 | no | subagent: SC counties (46) ta… |
| Conway citizen Blight Problem reports | Conway, Horry, SC | code_enforcement | open | 156 rows 2020-08 to 2026-02; 'Dilapidated Building' 5, tall… | - | 1 | yes | subagent: SC cities (66) + SC… |
| Horry County EnerGov history projection (CodeEnforcement folder) | Horry, SC | code_enforcement | open | 0 rows on 2026-10-07 (layers 21-23 history point/line/poly) | - | 0.5 | no | subagent: SC cities (66) + SC… |
| North Myrtle Beach code-enforcement portal (OpenGov) | North Myrtle Beach, Horry, SC | code_enforcement | JS-app |  | - |  | yes | subagent: SC cities (66) + SC… |
| Myrtle Beach code enforcement / Quality of Life Court (no public list) | Myrtle Beach, Horry, SC | condemned_demolition_unsafe | absent |  | - | 0 | yes | subagent: SC cities (66) + SC… |
| Horry County owned properties | Horry, SC | county_surplus | open | 397 | - | 1 | yes | lead agent: ArcGIS Online sea… |
| Horry delinquent tax parcels 2025 (FLC bids) | Horry, SC | tax_sale | open | 47 | - | 1 | yes | lead agent: ArcGIS Online sea… |
| Jasper County FLC and delinquent real property pages | Jasper, SC | county_surplus | absent |  | - | 0 | yes | subagent: SC counties (46) ta… |
| Lancaster County violation points (2022) | Lancaster, SC | code_enforcement | open | 330 rows | - | 2 | yes | lead agent: ArcGIS Online sea… |
| Lancaster County Forfeited Properties Available | Lancaster, SC | county_surplus | open | 0 rows on 2026-10-07 (list area empty) | - | 1 | yes | subagent: SC counties (46) ta… |
| Lancaster County Delinquent Tax Collection page (2026 tax sale notice) | Lancaster, SC | tax_sale | open | 0 parcels on page 2026-10-07 | - | 2 | yes | subagent: SC counties (46) ta… |
| Laurens County delinquent tax notice (newspaper e-edition) | Laurens, SC | tax_sale | terms-only | Nov 12, 2025 edition titled 'Delinquent Tax Notices', 4 pag… | - | 4 | yes | subagent: SC counties (46) ta… |
| Lee County Delinquent Tax page | Lee, SC | tax_sale | absent |  | - | 0 | yes | subagent: SC counties (46) ta… |
| City of West Columbia blight removal program | West Columbia, Lexington, SC | condemned_demolition_unsafe | absent | no addresses listed | - | 0 | yes | subagent: SC cities (66) + SC… |
| Lexington County Master-in-Equity judicial sale roster | Lexington, SC | sheriff_or_mie_sale | disclaimer-click |  | - | 0 | no | subagent: SC counties (46) ta… |
| Lexington County 2026 delinquent tax sale files (real estate + mobile home) | Lexington, SC | tax_sale | open | links not live yet on 2026-10-07 | - | 4 | no | subagent: SC counties (46) ta… |
| Marion County FLC list 2022 and tax sale info form | Marion, SC | county_surplus | open |  | - | 0 | no | subagent: SC counties (46) ta… |
| McCormick County tax sale (newspaper only) | McCormick, SC | tax_sale | absent |  | - | 0 | yes | subagent: SC counties (46) ta… |
| Newberry County Forfeited Land Commission property listing | Newberry, SC | county_surplus | open | 2 parcels (list dated June 2025) | - | 1 | yes | subagent: SC counties (46) ta… |
| Seneca code-enforcement portal (CitizenServe) | Seneca, Oconee, SC | code_enforcement | JS-app |  | - |  | yes | subagent: SC cities (66) + SC… |
| Orangeburg code-enforcement portal (AccessGov) | Orangeburg, Orangeburg, SC | code_enforcement | absent |  | - |  | yes | subagent: SC cities (66) + SC… |
| Orangeburg County website (tax sale, overage) | Orangeburg, SC | tax_sale | bot-check |  | - | 0 | yes | subagent: SC counties (46) ta… |
| City of Easley condemnation list (PDF) | Easley, Pickens, SC | condemned_demolition_unsafe | open | 37 address rows / 38 parcel numbers, dates 2023 to 2026-01 | - | 2 | no | subagent: SC cities (66) + SC… |
| Columbia SC rental property registry | Columbia, Richland, SC | absentee_owner | open | 33,396 | - | 3 | yes | lead agent: ArcGIS Online sea… |
| City of Columbia Code Violation Case Status + Rental Properties (CodeRental ser… | Columbia, Richland, SC | code_enforcement | open | layer 0: 9,009 rows (Open 7,991, Under Investigation 127, P… | - | 2 | yes | lead agent: ArcGIS Online sea… |
| City of Columbia code violation cases (CodeViolationProperty) - built | Columbia, Richland, SC | code_enforcement | open | 9,776 rows, newest OpenedDate 2026-09-27 (checked 2026-10-0… | columbia_code_vacant_boarded | 0 | no | subagent: SC cities (66) + SC… |
| City of Columbia city-held vacant properties / land bank lots (CityVacantProper… | Columbia, Richland, SC | land_bank | open | 63 rows (CityVacantProperties); 63 (VacantLotsCoC); 17 (Vac… | - | 1 | yes | subagent: SC cities (66) + SC… |
| Columbia SC short-term rental registry | Columbia, Richland, SC | str_registration | open | 365 non-owner-occupied + 81 owner-occupied | - | 2 | yes | lead agent: ArcGIS Online sea… |
| City of Columbia residential vacant lots inventory | Columbia, Richland, SC | vacant_registry | open | 3,642 rows | - | 2 | yes | subagent: SC cities (66) + SC… |
| Saluda County delinquent tax sale list (web posting) | Saluda, SC | tax_sale | open | not posted yet (page updated 2026-07-31) | counties_sc.saluda_delinquent_tax | 0 | no | subagent: SC counties (46) ta… |
| Woodruff code-enforcement portal (iWorQ) | Woodruff, Spartanburg, SC | code_enforcement | bot-check |  | - |  | yes | subagent: SC cities (66) + SC… |
| Spartanburg city-owned delinquent-tax parcels | Spartanburg, Spartanburg, SC | county_surplus | open | 48 | - | 1 | yes | lead agent: ArcGIS Online sea… |
| City of Sumter Code Enforcement Zones | Sumter, Sumter, SC | code_enforcement | open | zones only, no cases | - | 0 | yes | subagent: SC cities (66) + SC… |
| Sumter County Penny for Progress demolition of distressed structures | Sumter, SC | condemned_demolition_unsafe | open | 9 properties demolished 2020-2021; marked COMPLETED | - | 0 | yes | subagent: SC counties (46) ta… |
| Sumter dilapidated house survey 2021 | Sumter, Sumter, SC | condemned_demolition_unsafe | open | 141 | - | 1 | yes | lead agent: ArcGIS Online sea… |
| City of Sumter NIP parcel status (ArcGIS) | Sumter, Sumter, SC | land_bank | open | 100 rows on 2026-10-07 | - | 1 | yes | subagent: SC cities (66) + SC… |
| Sumter County Master-in-Equity page | Sumter, SC | sheriff_or_mie_sale | absent |  | - | 0 | yes | subagent: SC counties (46) ta… |
| City of Sumter Vacant Property Registry (ArcGIS) | Sumter, Sumter, SC | vacant_registry | open | 1,168 rows on 2026-10-07: 580 Vacant Registered, 447 Vacant… | - | 2 | yes | subagent: SC cities (66) + SC… |
| Sumter vacant property survey points | Sumter, Sumter, SC | vacant_registry | open | 3,385 | - | 2 | yes | lead agent: ArcGIS Online sea… |
| Union County tax sale / FLC assignment notice | Union, SC | tax_sale | absent |  | - | 0 | yes | subagent: SC counties (46) ta… |
| Williamsburg County 2026 tax sale page | Williamsburg, SC | tax_sale | open | 2025 list 885 TMS (documented); 2026 not yet | - | 0 | no | subagent: SC counties (46) ta… |
| Rock Hill open code enforcement cases (Housing / Demolition / Exterior Major) -… | Rock Hill, York, SC | code_enforcement | open | Board (layer 4) 0 rows and Unsecured Property (layer 12) 0 … | rockhill_code_housing / rockhill_code_demoli… | 0.5 | no | subagent: SC cities (66) + SC… |
| Tega Cay code-enforcement portal (Evolve) | Tega Cay, York, SC | code_enforcement | JS-app |  | - |  | yes | subagent: SC cities (66) + SC… |
| York County code enforcement districts / Stuck Family Properties | York, SC | code_enforcement | open | 3 polygons; Stuck_Family_Properties 11 rows (lastEdit 2020-… | - | 0 | yes | subagent: SC cities (66) + SC… |
| York County SC county website (tax sale notice, delinquent tax page) | York, SC | tax_sale | bot-check |  | counties_sc.york_delinquent_tax (0 rows; old… |  | no | lead agent: web search + dire… |
| York County SC tax sale properties 2026 (ArcGIS) | York, SC | tax_sale | open | 853 (2026-10-07, last edit 2026-09-29) | counties_sc.york_tax_sale_parcels (built 202… | 3 | no | lead agent: ArcGIS Online sea… |
| City websites behind Cloudflare / bot challenge (code pages unreadable) | statewide, SC | code_enforcement | bot-check |  | - |  | yes | subagent: SC cities (66) + SC… |
| SC Press Association public notices: keyword lane for unfit/unsafe/demolition n… | statewide, SC | condemned_demolition_unsafe | JS-app |  | sc_public_notices (foreclosure/tax/estate ca… | 4 | no | subagent: SC cities (66) + SC… |
| SC Public Index magistrate (summary court) cases | statewide, SC | eviction | terms-only |  | - |  | no | lead agent: web search + dire… |
| SC Department of Consumer Affairs HOA complaint reports | statewide, SC | hoa | open | 452 complaints in 2025 | - | 2 | yes | lead agent: web search + dire… |
| Utility disconnect lists (SC) | statewide, SC | utility_shutoff | public-records-request |  | - |  | no | lead agent: web search + dire… |
| Bid4Assets (NC/SC real estate) | national, US | auction | open |  | national.bid4assets (0 rows) |  | no | lead agent: web search + dire… |
| GovDeals (NC/SC real estate) | national, US | auction | open |  | national.govdeals (0 rows) |  | no | lead agent: web search + dire… |
| HiBid (NC/SC real estate) | national, US | auction | open |  | national.hibid_real_estate |  | no | lead agent: web search + dire… |
| Hubzu (NC/SC real estate) | national, US | auction | open |  | national.hubzu |  | no | lead agent: web search + dire… |
| ServiceLink Auction (NC/SC real estate) | national, US | auction | open |  | national.servicelink_auction |  | no | lead agent: web search + dire… |
| Tranzon (NC/SC real estate) | national, US | auction | open |  | national.tranzon_auctions (0 rows) |  | no | lead agent: web search + dire… |
| Williams & Williams (NC/SC real estate) | national, US | auction | open |  | national.williams_auctions (0 rows) |  | no | lead agent: web search + dire… |
| Xome (NC/SC real estate) | national, US | auction | open |  | national.xome |  | no | lead agent: web search + dire… |
| auction.com (NC/SC real estate) | national, US | auction | open |  | national.auction_dot_com |  | no | lead agent: web search + dire… |
| NERIS Public Incident Basics | national, US | fire_incident | terms-only |  | - |  | yes | lead agent: ArcGIS Online sea… |
| NFIRS Public Data Release (1980-2025) | national, US | fire_incident | open | national, NC/SC subset unknown | - | 8 | yes | lead agent: web search + dire… |
| OpenFEMA HMA mitigated properties | national, US | flood_storm_damage | open | 99,927 national (2026-09-08) | - | 2 | yes | lead agent: web search + dire… |
| OpenFEMA NFIP multiple-loss properties | national, US | flood_storm_damage | open | 240,651 national | - | 2 | yes | lead agent: web search + dire… |
| HUD Aggregated USPS vacancy data | national, US | usps_vacancy | login |  | - |  | yes | lead agent: web search + dire… |

## 8. What could not be determined

- The real-estate share of Mecklenburg's 93,916 'Back Bills' (the layer refuses statistics queries; needs a paged read).
- Freshness of the Sumter (2023 / 2020), Rocky Mount (2025) and other one-off survey layers: no per-row 'still vacant' field exists; only a re-check of the property or a newer layer settles it.
- Whether Charlotte's 15 'orders to demolish' are already inside charlotte_open_data's all-cases layer (likely; not joined).
- Owner of some ArcGIS items (Archdale-area 'Geocoded_Liens', Isle of Palms and New Bern STR layers): inferred from map extent; the organisation name is not readable anonymously.
- Sites behind Cloudflare/Akamai (Mecklenburg Sheriff auctions, yorkcountygov.com, Union, Cabarrus, Chatham, Dare, Person, Sampson, Wilson, Buncombe, Franklin, Granville, Hyde, Onslow and Rockingham county sites, Albemarle, Eden, Reidsville, Nashville, Creedmoor, Hillsborough, Lexington NC, and Columbia, Aiken, York, Lancaster SC city sites): their lists are unknown until a person opens them.
- SC counties with no GIS host found for code enforcement (Abbeville, Allendale, Bamberg, Calhoun, Chesterfield, Dillon, Edgefield, Fairfield, Jasper, Lee, Marion, McCormick, Orangeburg).
- The session-wide web-search budget ran out part way through; most town-level cells got one search plus a direct site check, and 'land bank' and 'municipal fee lien' were not checked town by town.
- NFIRS public-data-release address coverage for NC/SC departments (not downloaded: a multi-GB national file; run on the VM only with the owner's go-ahead).
- Short-term-rental, fire and permit cells for most towns rest on the ArcGIS Online sweep only (grid code 'n').
