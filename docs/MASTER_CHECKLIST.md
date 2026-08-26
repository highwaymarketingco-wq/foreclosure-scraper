# MASTER CHECKLIST — Ultimate Foreclosure Dashboard
**Board: 53,851 listings | 91 active sources | 209 scraper files | 165+ enrichers | 122 raw keys**
*Last updated: 2026-08-26*

---

## SECTION A: SOURCE COVERAGE AUDIT (91 Active Sources)

### A1. NC County Tax Sources (✅ HAVE)
- [x] NC PTScloud delinquent tax (20,486 listings)
- [x] Rutherford tax (4,288)
- [x] NC county PDF delinquent tax (2,023)
- [x] NC county CSV delinquent tax (1,226)
- [x] Buncombe delinquent tax (954)
- [x] Buncombe elderly exemption (2,996)
- [x] Buncombe tax foreclosure (19)
- [x] Henderson tax (henderson_tax.py)
- [x] Henderson foreclosure parcels (4)
- [x] Cleveland tax (6)
- [x] Wake tax foreclosure (wake_tax_foreclosure.py)
- [x] WNC tax foreclosures (wnc_tax_foreclosures.py)
- [x] Swain tax foreclosures
- [x] Haywood tax foreclosures
- [x] Gaston tax foreclosure
- [x] Edgecombe tax foreclosure
- [x] Cumberland tax foreclosure
- [x] Polk tax
- [x] Stokes delinquent tax
- [x] Rutherford wildfire tax
- [x] NC county tax foreclosure (4)
- [x] NC civicplus tax sale
- [x] NC coastal tax foreclosure
- [x] Multi-year delinquent tax (481)

### A2. SC County Tax Sources (✅ HAVE)
- [x] Pickens delinquent parcels (1,885)
- [x] Spartanburg delinquent tax (1,718)
- [x] Charleston delinquent tax (1,125)
- [x] Cherokee delinquent tax (528)
- [x] SC county rosters (10)
- [x] SC coastal rosters
- [x] SC DOR delinquent
- [x] SC delinquent tax list
- [x] SC tax delinquent
- [x] Oconee tax sale, forfeited land (218)
- [x] Colleton tax sale
- [x] Clarendon tax auction
- [x] Pickens tax sale
- [x] Oconee FLC assignment (495)
- [x] Oconee FLC
- [x] Spartanburg FLC (6)
- [x] SC FLC (73)
- [x] Terry Howe FLC (23)
- [x] Terry Howe auctions
- [x] Lexington FLC
- [x] Kershaw FLC
- [x] Horry FLC (EXCLUDED — do not re-add)
- [x] McCormick FLC
- [x] Anderson master in equity (19)
- [x] Pickens master in equity (10)
- [x] Spartanburg master in equity (3)
- [x] Charleston MIE (54)
- [x] Chester, Greenwood, Laurens, Lancaster, Edgefield, Fairfield, Saluda, Newberry, Marlboro, Aiken, Abbeville, Darlington, Florence, Union delinquent tax
- [x] SC DES brownfields
- [x] SC DEW lien registry

### A3. NC Court / eCourts Sources (✅ HAVE — thin)
- [x] NC eCourts lis pendens (390)
- [x] NC eCourts estates (nc_ecourts_estates.py)
- [x] NC eCourts divorce (152)
- [ ] **NC eCourts — ALL 100 counties not covered** ← GAP: only some counties on Tyler/eCourts
- [ ] **NC eCourts civil cases** ← GAP: not scraping general civil (judgments, liens)
- [ ] **NC eCourts criminal cases** ← GAP: criminal judgments create liens
- [ ] **NC case status Tyler portal** ← enrichment exists (169 listings) but thin

### A4. SC Court / Public Index Sources (✅ HAVE — thin)
- [x] SC public index (3,699)
- [x] SC public index export (592)
- [x] SC public index lis pendens (351)
- [x] SC probate net (265)
- [x] SC probate notices
- [x] SC public notices (151)
- [ ] **SC Public Index — ALL 46 counties** ← PARTIAL: ~26 counties on PublicIndex. MISSING counties (no online portal): Bamberg, Calhoun, Chesterfield, Fairfield, Jasper, Kershaw, Lexington, Lee, McCormick, Marion, Sumter. PublicIndex Cloudflare-blocked but stealth fetch works.
- [ ] **SC Master-in-Equity sales calendars** ← GAP: only 5 counties (Anderson, Pickens, Spartanburg, Charleston, Colleton). Need remaining 41.
- [ ] **SC Sheriff sales** ← GAP: only Barnwell, Bamberg, Dillon, Anderson have scrapers. Need: Greenville, Richland, Charleston, Spartanburg, York, Berkeley, Lexington, Beaufort, Horry(excluded).
- [ ] **SC family court (divorce)** ← GAP: no SC divorce scraper
- [ ] **SC ROD/RMC — deed of trust/mortgage filings** ← GAP: 7 counties have scrapers (sc_rod_acclaim, sc_rod_cott, sc_flc). MISSING: Pickens, Oconee, Anderson, Laurens, Union, Charleston, York, Berkeley, Georgetown, Greenville, Spartanburg, Richland, Lexington, Aiken, Sumter (paper filing only).
- [ ] **SC building permits** ← NO SCRAPER. Cities: Charleston, Greenville, Spartanburg, Columbia, Myrtle Beach(excluded). Access: civicplus/EnerGov/CityGoverment portals.
- [ ] **SC code enforcement** ← NO SCRAPER. Same cities as permits.
- [ ] **SC utility liens** ← NO SCRAPER. No central database. Filed at county level.
- [ ] **SC HOA liens** ← NO SCRAPER. Filed with county ROD/RMC. No central database.
- [ ] **SC zoning GIS layers** ← NO SCRAPER. ArcGIS REST endpoints per county. Free.
- [ ] **SC CAMA (Computer-Assisted Mass Appraisal)** ← NO SCRAPER. County portals for property values, owner info, parcel data. Free.

### A5. Law Firms (✅ HAVE — 15 firms)
- [x] Brock & Scott (71)
- [x] Hutchens & Senter (70)
- [x] Shapiro & Ingle (65)
- [x] Kania (34)
- [x] Rogers Townsend (15)
- [x] Bell Carrington (14)
- [x] McMichael Taylor Gray (9)
- [x] Ingle firm (1)
- [x] Aldridge Pite
- [x] ALAW
- [x] Finkel
- [x] Korn
- [x] Mewborn Deselms
- [x] Zacchaeus
- [ ] **Terry Howe (SC FLC attorney)** ← have auction scraper, not firm scraper
- [ ] **Other NC foreclosure firms** ← GAP: research needed for firms not yet scraped

### A6. REO / Bank-Owned (✅ HAVE)
- [x] Fannie Mae HomePath (497)
- [x] HUD HomeStore (10)
- [x] HUD Section 8 contracts (37)
- [x] HUD REAC inspection (214)
- [x] VA REO / VRM (21)
- [x] USDA RD properties
- [x] First Citizens REO
- [x] Freddie Mac HomeSteps
- [x] HomePath JSON
- [x] NCHFA REO
- [x] GSA surplus / real property
- [x] IRS treasury auctions
- [x] IRS judicial sales
- [x] US Marshals real property
- [x] FDIC failed banks
- [ ] **SBA 504 loan foreclosures** ← GAP: no SBA scraper
- [ ] **Freddie Mac enhanced listings** ← may have more data than we pull

### A7. Auction Platforms (✅ HAVE)
- [x] Auction.com (13)
- [x] Bid4Assets
- [x] Hubzu (16)
- [x] Xome (8)
- [x] GovDeals
- [x] HiBid real estate
- [x] CWS Marketing
- [x] Tranzon auctions
- [x] Williams auctions
- [x] Servicelink auction (23)
- [x] Meares auctions
- [x] Treasury seized
- [ ] **RealtyBid** ← GAP: not scraped
- [ ] **Auction.com API** ← GAP: only web scraping, no API

### A8. National Aggregators (✅ HAVE — thin)
- [x] Zillow foreclosures (27) + bulk (64)
- [x] Trulia foreclosures (3)
- [x] Realtor foreclosures (1)
- [x] PropWire foreclosures
- [x] HomeHarvest (15) + distressed (283)
- [x] Foreclosure.com (75)
- [x] Redfin DataCenter (enrichment only, not scraper)
- [x] LandWatch (264), LandAndFarm (283), LandsOfAmerica
- [x] LoopNet (22)
- [x] Crexi multifamily (22)
- [x] Craigslist FSBO
- [x] Estate sales (25)
- [x] Cash buyer deeds (27)
- [x] CourtListener bankruptcy (646) + adversary (13) + civil
- [x] Jail bookings (8)
- [x] Legacy obituaries
- [x] NC SOS entity / SC SOS entity
- [x] OpenCorporates
- [x] FEMA disasters
- [x] EPA superfund / FRS sites
- [x] SeeClickFix
- [x] NC upset bids (22)
- [x] Sheriff sales (1)
- [x] State contamination sites
- [x] Sitemap walker / NOD discovery (7)

### A9. Newspapers & Public Notices (✅ HAVE)
- [x] Column legal notices (60)
- [x] Post & Courier
- [x] Shelby Star
- [x] Tryon Bulletin
- [x] Hendersonville Lightning
- [x] Index Journal
- [x] Daily Courier
- [x] Coastland Times (1)
- [x] Carolina Coast
- [x] NC public notices counties (114)
- [x] NCNotices (23)
- [x] PublicNotices.com
- [x] Gannett obituaries (136)
- [x] Funeral home RSS
- [x] Spartanburg weekly legals (190)

### A10. City/County Code & Permits (✅ HAVE — VERY thin)
- [x] Asheville STR permits (555)
- [x] Asheville Helene damage (302)
- [x] Asheville min housing (asheville_min_housing.py)
- [x] Charlotte open data
- [x] Greensboro code
- [x] Henderson code violations (154)
- [x] Hendersonville vacant structures (45)
- [x] Lincoln code violations
- [x] New Hanover demolition permits (1,006)
- [x] Spartanburg vacant (1,577) + condemned (1,109) + city condemned (83)
- [x] Georgetown CivicEngage (406)
- [x] Code enforcement enricher (884 total)
- [ ] **Mecklenburg code violations** ← GAP
- [ ] **Wake code violations** ← GAP
- [ ] **Forsyth code violations** ← GAP
- [ ] **Durham code violations** ← GAP
- [ ] **Greenville SC code violations** ← GAP
- [ ] **Building permits for all major cities** ← GAP: only Asheville STR permits

---

## SECTION B: DATA FIELD GAPS (122 raw keys)

### B1. ✅ FULLY COVERED (100%)
| Field | Count | Notes |
|-------|-------|-------|
| amount_owed | 53,851 (100%) | Many estimated, not actual debt |
| equity | 53,851 (100%) | Many estimated (payoff_source: estimated_60pct_arv) |
| flood_zone | 53,851 (100%) | |
| distress_stack | 53,851 (100%) | |
| grade | 53,851 (100%) | |
| calc | 53,851 (100%) | ARV/rehab/rental calcs |
| two_year_delinquent | 53,851 (100%) | Boolean flag |
| assessed_value | 53,851 (100%) | Many estimated |

### B2. 🟡 PARTIAL COVERAGE (10-70%)
| Field | Count | % | Gap | Action Needed |
|-------|-------|---|------|---------------|
| census_rent | 52,134 | 96.8% | 1,717 | Census lookup by tract — near complete |
| comp_median_ppsf | 16,413 | 30.5% | 37,438 | Derive from deed chains + recorded sales |
| opportunity_zone | 31,521 | 58.5% | 22,330 | Census tract lookup |
| hud_fmr | 33,197 | 61.6% | 20,654 | Fair market rent by county |
| strategy_fit | 33,435 | 62.1% | 20,416 | Depends on data completeness |
| property_category | 33,243 | 61.7% | 20,608 | Categorization engine |
| corroboration | 33,243 | 61.7% | 20,608 | Cross-source validation |
| owner_email | 33,243 | 61.7% | 20,608 | Skip trace enrichment |
| tax_owed | 32,410 | 60.2% | 21,441 | Tax data from county |
| eviction_market | 28,152 | 52.3% | 25,699 | Eviction data by county |
| gis | 22,239 | 41.3% | 31,612 | County GIS attributes |
| skip_trace | 22,451 | 41.7% | 31,400 | Phone/email lookup |
| images | 24,260 | 45.0% | 29,591 | Property photos |
| owner_mailing | 23,270 | 43.2% | 30,581 | Owner address |
| fhfa_value | 11,103 | 20.6% | 42,748 | FHFA HPI-based value |
| last_sale | 11,678 | 21.7% | 42,173 | Last sale price/date |
| deed_chain | 17,652 | 32.8% | 36,199 | Ownership history from ROD |
| data_quality | 35,799 | 66.5% | 18,052 | Quality flags |
| red_flags | 27,096 | 50.3% | 26,755 | 27 flag types |
| recorded_comps | 7,031 | 13.1% | 46,820 | Recorded comparable sales |
| recorded_sales | 4,966 | 9.2% | 48,885 | County recorded sales |
| zoning | 17,099 | 31.8% | 36,752 | County zoning data |

### B3. 🔴 CRITICAL GAPS (< 5%)
| Field | Count | % | Gap | Priority | Action |
|-------|-------|---|------|----------|--------|
| **bankruptcy** | 291 | 0.5% | 53,560 | 🔴 CRITICAL | Expand: PACER + name matching |
| **loan_amount** | 27 | 0.1% | 53,824 | 🔴 CRITICAL | Deed of trust filings at county ROD |
| **liens** | 3 | 0.0% | 53,848 | 🔴 CRITICAL | County lien index search |
| **code_enforcement** | 884 | 1.6% | 52,967 | 🔴 CRITICAL | Expand to all counties |
| **owner_mismatch** | 223 | 0.4% | 53,628 | 🔴 CRITICAL | COMPUTE from existing data! |
| **upset_bid** | 183 | 0.3% | 53,668 | 🟡 HIGH | Expand NC upset bid scraping |
| **incarceration** | 267 | 0.5% | 53,584 | 🟡 HIGH | Expand jail booking search |
| **fema_repetitive_loss** | 81 | 0.2% | 53,770 | 🟡 HIGH | Better FEMA data matching |
| **storm_damage** | 578 | 1.1% | 53,273 | 🟡 HIGH | Helene + other storm data |
| **divorce** | 708 | 1.3% | 53,143 | 🟡 HIGH | Link divorce filings → properties |
| **nc_case_status** | 169 | 0.3% | 53,682 | 🟡 HIGH | Expand eCourts case status |
| **title_risk** | 5,325 | 9.9% | 48,526 | 🟡 HIGH | Expand deed chain → title risk |
| **life_events** | 6,130 | 11.4% | 47,721 | 🟡 HIGH | Death/divorce/probate linking |
| **court_bid** | 18 | 0.0% | 53,833 | 🟢 MED | Court auction bid data |
| **rod_name_index** | 7 | 0.0% | 53,844 | 🟢 MED | ROD name-based search |

### B4. 🏆 COMPETITOR FEATURE COMPARISON
| Feature | We Have | PropStream | Goliath | BatchLeads | Gap |
|---------|---------|-----------|---------|-----------|-----|
| Comps (comparable sales) | 30.5% | ✅ 100% | ✅ 100% | ✅ 100% | 69.5% gap |
| Mortgage/loan data | 0.1% | ✅ | ✅ | ✅ | 99.9% gap |
| Skip trace (phone/email) | 41.7% | ✅ 100% | ✅ 100% | ✅ 100% | 58.3% gap |
| Property condition | No | ✅ | ✅ | Partial | 100% gap |
| MLS history | No | ✅ | ✅ | ✅ | 100% gap |
| Building permits | ~1% | ✅ | Partial | No | 99% gap |
| Code violations | 1.6% | ✅ | Partial | No | 98.4% gap |
| Zoning | 31.8% | ✅ | ✅ | No | 68.2% gap |
| HOA liens | No | Partial | No | No | 100% gap |
| Environmental hazards | Enricher exists | ✅ | No | No | Need population |
| School ratings | Enricher exists | ✅ | ✅ | No | Need population |
| Crime stats | Enricher exists | ✅ | No | No | Need population |
| Insurance claims (CLUE) | No | No | No | No | Nobody has this |
| FEMA repetitive loss | 0.2% | No | No | No | WE HAVE — they DON'T |
| Eviction market data | 52.3% | No | No | No | WE HAVE — they DON'T |
| Incarcerated owner | 0.5% | No | No | No | WE HAVE — they DON'T |
| Storm damage | 1.1% | No | No | No | WE HAVE — they DON'T |
| HUD REAC failures | 0.4% | No | No | No | WE HAVE — they DON'T |
| 27 red flag types | 50.3% | 3-5 types | 3-5 | 3-5 | WE WIN |

---

## SECTION C: ACTION PLAN — PRIORITIZED BUILD ORDER

### Tier 1: COMPUTE FROM EXISTING DATA (no new scrapers needed)

- [ ] **C1. Owner mismatch for ALL 53,851** — Compare owner_mailing vs property address. If different → absentee. Currently 223/53,851 (0.4%). Should be near 100%. **EST: 5 min**
- [ ] **C2. Comps from existing deed chains** — We have 17,652 deed chains with transfer prices. Use as comp basis for nearby properties. Populate comp_median_ppsf for all. **EST: 30 min**
- [ ] **C3. Mortgage estimate from deed of trust** — 108 properties have DOT flags. Pull loan amounts. Also estimate from transfer data + assessed value ratio. **EST: 1 hr**
- [ ] **C4. SOS dissolution lookup** — enrichment_sos_dissolution.py EXISTS. Run it. Field exists, 0 data. NC SOS business search is free. **EST: 2 hrs**
- [ ] **C5. Divorce → property link** — We scrape 152 NC divorce filings. Match defendant name → property owner_name. enrichment_nc_divorce.py EXISTS. **EST: 1 hr**
- [ ] **C6. Bankruptcy expansion via name matching** — CourtListener gives 646. Match owner_name against ALL bankruptcy filings in our CourtListener data. enrichment_bankruptcy_property.py EXISTS. **EST: 2 hrs**
- [ ] **C7. Red flags expansion** — 50.3% have flags. Expand to cover more signal types from existing data. build_red_flags.py EXISTS. **EST: 1 hr**

### Tier 2: NEW SCRAPERS NEEDED (feasible, free/public sources)

- [ ] **C8. NC Register of Deeds — deed of trust / mortgage filings** — Major counties: Mecklenburg, Wake, Buncombe, Forsyth, Durham, New Hanover, Buncombe. These give us loan amounts, mortgage chain. **EST: 4 hrs/county**
- [ ] **C9. SC Register of Deeds / RMC — mortgage filings** — Major counties: Charleston, Greenville, Spartanburg, Richland, Horry (excluded). **EST: 4 hrs/county**
- [ ] **C10. Lis pendens expansion — ALL NC counties** — We have 741 (390 NC + 351 SC). Expand to all 100 NC counties via eCourts + all 46 SC counties via public index. **EST: 2 hrs/county batch**
- [ ] **C11. Code violations expansion** — Beyond Asheville (884). Add: Mecklenburg, Wake, Forsyth, Durham, Greenville SC, Spartanburg, Charleston. **EST: 3 hrs/county**
- [ ] **C12. Building permits — major cities** — Asheville, Charlotte, Raleigh, Winston-Salem, Greenville SC, Charleston. **EST: 3 hrs/city**
- [ ] **C13. Zoning — county GIS layers** — Many free. Batch download. **EST: 1 hr/county batch**
- [ ] **C14. NC Sheriff sales — major counties** — Mecklenburg, Wake, Forsyth, Buncombe, Guilford. **EST: 2 hrs/county**
- [ ] **C15. SC Sheriff sales — expand** — Only Barnwell, Bamberg, Dillon, Anderson have scrapers. Add: Spartanburg, Greenville, Richland, Charleston, Horry (excluded). **EST: 2 hrs/county**
- [ ] **C16. SC Master-in-Equity — expand** — Only 5 counties. Add remaining 41. **EST: 1 hr/county**
- [ ] **C17. SBA 504 loan foreclosures** — SBA publishes distressed loan properties. **EST: 2 hrs**
- [ ] **C18. PACER bankruptcy search** — Federal court bankruptcy filings. $0.10/page but free for case search. API available via RECAP. **EST: 4 hrs**
- [ ] **C19. NC HOA liens** — No central database. Check county ROD for HOA lien filings. **EST: Research first**
- [ ] **C20. SC HOA liens** — Same approach. **EST: Research first**

### Tier 3: ENRICHMENT POPULATION (enrichers exist but not run/thin)

- [ ] **C21. Environmental hazards population** — enrichment_envirofacts.py + enrichment_environmental.py EXIST. Run for all properties. EPA free data. **EST: 1 hr**
- [ ] **C22. School ratings** — enrichment_census_rent.py has related data. Need GreatSchools API integration. **EST: 2 hrs**
- [ ] **C23. Crime stats** — enrichment_fbi_ucr.py EXISTS. Run for all counties. FBI UCR free data. **EST: 1 hr**
- [ ] **C24. FEMA repetitive loss expansion** — enrichment_fema_repetitive_loss.py EXISTS. Only 81 matched. Improve matching. **EST: 2 hrs**
- [ ] **C25. Skip trace expansion** — enrichment_skip_trace.py EXISTS (41.7%). Expand free sources (voter, property records, court records). **EST: 4 hrs**
- [ ] **C26. Photos expansion** — enrichment_images.py (45%) + enrichment_streetview.py. Add Google Street View for remaining 55%. **EST: 2 hrs**
- [ ] **C27. Zestimate expansion** — enrichment_zestimate.py EXISTS. Run for all properties. **EST: 1 hr**
- [ ] **C28. Rent comps expansion** — enrichment_rent_comps_extra.py EXISTS. Run for all. **EST: 1 hr**
- [ ] **C29. Opportunity zone expansion** — 58.5% covered. Census tract lookup for remaining 41.5%. **EST: 30 min**
- [ ] **C30. Owner mailing expansion** — 43.2% covered. County assessor + tax records. **EST: 4 hrs**

### Tier 4: REAL-TIME / CONTINUOUS SOURCES

- [ ] **C31. Real-time court filings** — Daily polling of eCourts + SC Public Index for new filings. **EST: 4 hrs**
- [ ] **C32. Real-time auction updates** — Daily polling of auction platforms (Auction.com, Bid4Assets, Hubzu, etc.). **EST: 2 hrs**
- [ ] **C33. Real-time tax delinquency updates** — Daily polling of PTScloud + county tax portals. **EST: 2 hrs**
- [ ] **C34. FEMA disaster declarations** — Real-time feed for new disaster declarations. enrichment_fema_disaster.py EXISTS. **EST: 1 hr**
- [ ] **C35. National Weather Service storm events** — Real-time severe weather → property damage correlation. **EST: 2 hrs**
- [ ] **C36. Fire dispatch / emergency calls** — Research availability. Likely restricted. **EST: Research first**
- [ ] **C37. USPS vacancy data** — enrichment_usps_vacancy.py EXISTS. Run for all. **EST: 2 hrs**

### Tier 5: PAID API INTEGRATIONS (requires budget)

- [ ] **C38. Skip trace API (paid)** — PeopleFinders, WhitePages Pro, BeenVerified. ~$0.10-$0.50/lookup × 53,851 = $5,385-$26,925. **NEEDS USER APPROVAL**
- [ ] **C39. MLS feed (paid)** — Realtor MLS access. Restricted to licensed agents. **NEEDS USER LICENSE**
- [ ] **C40. ATTOM Data Solutions API** — Aggregated property/mortgage data. Paid. **NEEDS USER APPROVAL**
- [ ] **C41. CoreLogic / Black Knight** — Mortgage data feeds. Enterprise pricing. **NEEDS USER APPROVAL**
- [ ] **C42. LexisNexis CLUE** — Insurance claim history. Restricted. **NEEDS USER APPROVAL**
- [ ] **C43. Credit bureau data** — Mortgage payment status. FCRA restricted. **NEEDS USER APPROVAL + LICENSING**

---

### Tier 6: NATIONAL RESEARCH FINDINGS (from subagent research)

**Paid APIs (need budget approval):**
- [ ] **N1. PACER API** — https://www.pacer.gov — Bankruptcy, civil, adversary proceedings, docket docs. Paid ($0.10/25 pages). Case Search API for registered users. CRITICAL for bankruptcy gap.
- [ ] **N2. ATTOM Data Solutions** — https://www.attom.com — Property characteristics, ownership, mortgage, tax, foreclosure. REST API, per-record pricing. HIGH priority.
- [ ] **N3. CoreLogic / Black Knight** — https://www.blackknightinc.com — Mortgage performance, loan servicing, foreclosure filings. Enterprise API, subscription. HIGH priority.
- [ ] **N4. First American Title** — https://www.firstamerican.com — Title reports, ownership, mortgage, lien data. Enterprise API. HIGH priority.
- [ ] **N5. RealtyTrac** — https://www.realtytrac.com — Current & historical foreclosure listings, auction data. REST API after signup. HIGH priority.
- [ ] **N6. Redfin Data Center** — https://www.redfin.com/news/data-center — Market stats, price drops (distress indicator). Enterprise program. MEDIUM priority.
- [ ] **N7. LexisNexis CLUE** — Insurance claim history. Restricted. MEDIUM priority.
- [ ] **N8. Black Knight / ICE Mortgage** — https://www.ice.com/mortgage — Mortgage performance data. Enterprise. MEDIUM priority.

**Free/Public sources not yet scraped:**
- [ ] **N9. SBA 504 loan foreclosures** — https://www.sapexsb.org — SBA distressed loan property auctions. Free public listings. LOW priority.
- [ ] **N10. FEMA Disaster API** — Real-time disaster declarations. We have enrichment_fema_disaster.py but need to run it as real-time feed.
- [ ] **N11. Homes.com** — https://www.homes.com — FSBO listings, limited foreclosure data. Free scrape. LOW priority.
- [ ] **N12. Movoto** — https://www.movoto.com — Property listings, price history. Free scrape. LOW priority.
- [ ] **N13. RealtyBid** — https://realtybid.com — Online foreclosure auction data. Free scrape. LOW priority.
- [ ] **N14. Xome Auctions** — https://www.xome.com/auctions — Online real-estate auctions. Free scrape. LOW priority.
- [ ] **N15. GSA eOffer API** — JSON API available with key registration. We already scrape GSA but could use API for better data.

**Competitor feature comparison (from research):**
- PropStream: ownership, lien history, eviction data, foreclosure status, tax arrears — all via paid ATTOM/CoreLogic data
- Goliath: comparable market analysis, historical sales, owners, liens — same data sources
- BatchLeads: owner contact data, 12-month owner residence, foreclosure alerts — skip trace + MLS data
- DealMachine: owner contact data, ownership chain, property status — skip trace focused
- **Our unique advantages**: 27 red flag types (they have 3-5), FEMA repetitive loss, eviction market data, incarcerated owner detection, storm damage, HUD REAC failures, cash buyer tracking, heir estate parcels

---

## SECTION D: CURRENT SYSTEM INVENTORY

### D1. File Structure
```
foreclosure-scraper/
├── src/foreclosure_scraper/
│   ├── scrapers/                    # 209 scraper files
│   │   ├── counties_nc/             # 39 NC county scrapers
│   │   ├── counties_sc/             # 67 SC county scrapers
│   │   ├── counties_generic/       # 5 cross-county scrapers
│   │   ├── national/               # 57 national platform scrapers
│   │   ├── law_firms/               # 15 foreclosure law firm scrapers
│   │   ├── newspapers/              # 10 newspaper scrapers
│   │   ├── public_notices/          # 6 public notice scrapers
│   │   ├── reo/                     # 4 REO property scrapers
│   │   └── city_websites/           # 3 city scrapers
│   ├── enrichment_*.py              # 165+ enrichment modules
│   ├── web_artifact.py             # Board persistence (RAW_KEEP dict)
│   ├── models.py                    # Pydantic models
│   ├── base_scraper.py             # BaseScraper class
│   ├── http_client.py              # HTTP client with impersonation
│   └── workflow_engine.py          # Orchestrator
├── scripts/                         # Utility scripts
├── docs/                            # Dashboard + board files
│   ├── listings.json.gz            # 53,851 listings (board file)
│   ├── index.html                  # Dashboard
│   └── dashboard.js                # Dashboard JS
└── .venv/                           # Python 3.12 venv
```

### D2. Python Environment
- **Python**: ~/foreclosure-scraper/.venv/bin/python3.12
- **PYTHONPATH**: ~/foreclosure-scraper/src:~/foreclosure-scraper/.venv/lib/python3.12/site-packages
- **Run command**: `PYTHONPATH=~/foreclosure-scraper/src:~/foreclosure-scraper/.venv/lib/python3.12/site-packages:$PYTHONPATH ~/foreclosure-scraper/.venv/bin/python3.12`
- **CRITICAL**: Never use stream_save() — ALWAYS use write_artifact(board, {})
- **RAW_KEEP**: Must add new raw fields to web_artifact.py RAW_KEEP dict or they get stripped

### D3. Board Coverage Summary
| Field | Coverage | % |
|-------|----------|---|
| Core 8 fields (coords, sqft, flood, amount_owed, assessed, equity, tax_aging, 2yr_delinq) | 53,851/53,851 | 100% |
| census_rent | 52,134 | 96.8% |
| data_quality | 35,799 | 66.5% |
| strategy_fit | 33,435 | 62.1% |
| property_category | 33,243 | 61.7% |
| corroboration / owner_email | 33,243 | 61.7% |
| tax_owed | 32,410 | 60.2% |
| opportunity_zone | 31,521 | 58.5% |
| hud_fmr | 33,197 | 61.6% |
| red_flags | 27,096 | 50.3% |
| eviction_market | 28,152 | 52.3% |
| images | 24,260 | 45.0% |
| skip_trace | 22,451 | 41.7% |
| gis | 22,239 | 41.3% |
| owner_mailing | 23,270 | 43.2% |
| zoning | 17,099 | 31.8% |
| comp_median_ppsf | 16,413 | 30.5% |
| deed_chain | 17,652 | 32.8% |
| last_sale | 11,678 | 21.7% |
| fhfa_value | 11,103 | 20.6% |
| owner_phone | 10,979 | 20.4% |
| title_risk | 5,325 | 9.9% |
| life_events | 6,130 | 11.4% |
| code_enforcement | 884 | 1.6% |
| divorce | 708 | 1.3% |
| storm_damage | 578 | 1.1% |
| bankruptcy | 291 | 0.5% |
| incarceration | 267 | 0.5% |
| owner_mismatch | 223 | 0.4% |
| upset_bid | 183 | 0.3% |
| nc_case_status | 169 | 0.3% |
| fema_repetitive_loss | 81 | 0.2% |
| loan_amount | 27 | 0.1% |
| liens | 3 | 0.0% |
| court_bid | 18 | 0.0% |
| rod_name_index | 7 | 0.0% |

### D4. Active Source Breakdown (91 sources producing listings)
Top 20 sources:
1. nc_ptscloud_delinquent_tax: 20,486 (38.0%)
2. rutherford_tax: 4,288 (8.0%)
3. sc_public_index: 3,699 (6.9%)
4. buncombe_elderly: 2,996 (5.6%)
5. nc_county_pdf_delinquent_tax: 2,023 (3.8%)
6. pickens_delinquent_parcels: 1,885 (3.5%)
7. spartanburg_delinquent_tax: 1,718 (3.2%)
8. spartanburg_vacant: 1,577 (2.9%)
9. nc_county_csv_delinquent_tax: 1,226 (2.3%)
10. charleston_delinquent_tax: 1,125 (2.1%)
11. spartanburg_condemned: 1,109 (2.1%)
12. new_hanover_demolition_permits: 1,006 (1.9%)
13. buncombe_delinquent_tax: 954 (1.8%)
14. nc_heir_estate_parcels: 13 (1.3%)
15. courtlistener_bankruptcy: 646 (1.2%)
16. sc_public_index_export: 592 (1.1%)
17. asheville_str_permits: 555 (1.0%)
18. fannie_homepath: 497 (0.9%)
19. oconee_flc_assignment: 495 (0.9%)
20. multi_year_delinquent_tax: 481 (0.9%)

### D5. County Breakdown (15 counties)
| County | Listings | % of Board |
|--------|----------|------------|
| Spartanburg SC | 6,583 | 12.2% |
| Buncombe NC | 5,651 | 10.5% |
| Forsyth NC | 5,650 | 10.5% |
| Rutherford NC | 4,517 | 8.4% |
| Guilford NC | 3,882 | 7.2% |
| Beaufort SC | 3,485 | 6.5% |
| Pickens SC | 2,747 | 5.1% |
| New Hanover NC | 2,373 | 4.4% |
| Pitt NC | 1,973 | 3.7% |
| Henderson NC | 1,910 | 3.5% |
| Charleston SC | 1,455 | 2.7% |
| Anderson SC | 1,230 | 2.3% |
| Cherokee SC | 1,136 | 2.1% |
| Laurens SC | 980 | 1.8% |
| Lincoln NC | 777 | 1.4% |
| All others (~20 counties) | ~13,155 | 24.4% |

---

## SECTION E: RESEARCH STATUS

### E1. Research Subagents Dispatched
- [x] NC sources research — DELEGATED (deleg_fdbc35a6)
- [x] SC sources research — DELEGATED (deleg_c8fb7439)
- [x] National sources research — DELEGATED (deleg_21f77e80)

### E2. Research Questions Still Open
- [ ] Which NC counties are on eCourts/Tyler portal? (all 100? partial?)
- [ ] Does NC have a bulk court data download option?
- [ ] Which SC counties have online ROD/RMC search?
- [ ] Are there NC/SC HOA lien databases?
- [ ] What's the PACER API cost structure?
- [ ] Does ATTOM have a free tier?
- [ ] Can we access MLS data without a real estate license?
- [ ] Are there real-time fire/police dispatch feeds for NC/SC?
- [ ] What specific data fields does PropStream offer? (full feature list)
- [ ] What specific data fields does Goliath offer?
- [ ] What specific data fields does BatchLeads offer?
- [ ] Are there NC/SC utility lien databases?
- [ ] Does RealtyTrac still exist and offer data?
- [ ] Does Redfin have a distressed property API?
- [ ] SBA foreclosure property listings — URL and access method?

---

## SECTION F: ACCOUNTABILITY TRACKER

### F1. Completed Items
- [x] Board restored to 53,851 (from 38,108 stream_save loss)
- [x] All 8 core fields at 100%
- [x] Red flags system built (27 types, 50.3% coverage)
- [x] Title search pipeline (deed chain 17,652, title_risk 5,325)
- [x] Comprehensive audit completed
- [x] GitHub push working (commit 1fbf377 live)
- [x] Dashboard live on GitHub Pages
- [x] 209 scraper files across 9 directories
- [x] 165+ enrichment modules
- [x] 91 active sources producing listings
- [x] Source inventory extracted from board data
- [x] 3 research subagents dispatched for source gap analysis

### F2. In Progress
- [ ] NC source research (deleg_fdbc35a6) — RUNNING
- [ ] SC source research (deleg_c8fb7439) — RUNNING
- [ ] National source research (deleg_21f77e80) — RUNNING
- [ ] Master checklist document created

### F3. Next Actions (when research returns)
- [ ] Cross-reference research findings against Section A checklist
- [ ] Update checklist with newly discovered sources
- [ ] Begin Tier 1 items (owner mismatch, comps, SOS dissolution)
- [ ] Prioritize Tier 2 scraper builds based on research
- [ ] Run existing enrichers that haven't been fully executed (C21-C30)

### F4. Blocked / Needs User Decision
- [ ] C38-C43: Paid API integrations — need budget approval
- [ ] C39: MLS access — need real estate license
- [ ] C42: LexisNexis CLUE — need licensing approval
- [ ] C43: Credit bureau data — need FCRA compliance

---

*This checklist is a LIVING DOCUMENT. It will be updated after every action and included at the end of every message.*
