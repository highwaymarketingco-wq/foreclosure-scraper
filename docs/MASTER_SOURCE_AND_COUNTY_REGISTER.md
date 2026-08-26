# MASTER SOURCE & COUNTY REGISTER — the whole picture

_Generated 2026-08-17. Everything: 140 built sources (working + dead + walled sub-lanes), the walls we won't/can't do, and the county footprint._

## PART A — BUILT SOURCES (in the pipeline)


### city_websites
- `city_websites.search` — (composed / no external domain)

### counties
- `counties.column_legal_notices` — us-central1-enotice-production.cloudfunctions.net
- `counties.multi_year_delinquent_tax` — services6.arcgis.com, services1.arcgis.com, www.buncombecounty.org, oconeesc.com
- `counties.nod_discovery` — (composed / no external domain)
- `counties.sitemap_walker` — www.spartanburgcounty.gov, www.cherokeecountysc.gov, www.andersoncountysc.org, www.co.pickens.sc.us

### counties_generic
- `counties_generic.arcgis_distress_layers` — services6.arcgis.com, www.buncombecounty.org, arcgisserver.lincolncountync.gov, www.lincolncountync.gov
- `counties_generic.epa_frs_sites` — data.epa.gov, www.epa.gov
- `counties_generic.state_contamination` — services2.arcgis.com, www.deq.nc.gov

### counties_nc
- `counties_nc.asheville_helene` — services.arcgis.com
- `counties_nc.asheville_str_permits` — gis.ashevillenc.gov
- `counties_nc.brunswick_legal_notices` — www.brunswickcountync.gov, services.nconemap.gov
- `counties_nc.buncombe_delinquent_tax` — media.buncombenc.gov
- `counties_nc.buncombe_elderly` — gis.buncombecounty.org
- `counties_nc.buncombe_tax` — www.trumba.com, taxforeclosures.buncombenc.gov
- `counties_nc.buncombe_tax_foreclosure` — www.trumba.com, taxforeclosures.buncombenc.gov
- `counties_nc.cleveland_tax` — www.clevelandcounty.com
- `counties_nc.gaston_surplus_properties` — www.gastongov.com
- `counties_nc.henderson_code_violations` — services1.arcgis.com, www.hendersoncountync.gov
- `counties_nc.henderson_foreclosure_parcels` — www.arcgis.com, hendersoncounty.maps.arcgis.com, experience.arcgis.com
- `counties_nc.henderson_tax` — www.hendersoncountync.gov
- `counties_nc.hendersonville_vacant_structures` — services1.arcgis.com, www.hvlnc.gov
- `counties_nc.nc_coastal_tax_foreclosure` — www.brunswickcountync.gov, www.onslowcountync.gov, www.carteretcountync.gov, services.nconemap.gov
- `counties_nc.nc_county_csv_delinquent_tax` — www.nhcgov.com
- `counties_nc.nc_county_pdf_delinquent_tax` — www.lincolncountync.gov, www.catawbacountync.gov, mcdowellnc.gov
- `counties_nc.nc_county_tax_foreclosure` — www.gastongov.com, mcdowellnc.gov, www.rutherfordcountync.gov
- `counties_nc.nc_ecourts_divorce` — portal-nc.tylertech.cloud  **[DISABLED — AWS-WAF CAPTCHA (won't solve)]**
- `counties_nc.nc_ecourts_estates` — portal-nc.tylertech.cloud  **[DISABLED — AWS-WAF CAPTCHA (won't solve)]**
- `counties_nc.nc_ecourts_lis_pendens` — portal-nc.tylertech.cloud
- `counties_nc.nc_govdeals_real_property` — maestro.lqdt1.com, www.transylvaniacounty.org, www.govdeals.com
- `counties_nc.nc_heir_estate_parcels` — (composed / no external domain)
- `counties_nc.nc_ptscloud_delinquent_tax` — bcpwa.ncptscloud.com
- `counties_nc.nc_rod_logan` — (composed / no external domain)
- `counties_nc.nc_rod_substitute_trustee` — buncombe-recordings.permitium.com, www.nccourts.gov
- `counties_nc.new_hanover_foreclosures` — www.nhcgov.com
- `counties_nc.polk_tax` — www.polknc.gov
- `counties_nc.rutherford_tax` — www.rutherfordcountync.gov
- `counties_nc.rutherford_wildfire_tax` — www.rutherfordcountync.gov, d1ebsyxxbc7tep.cloudfront.net
- `counties_nc.wnc_rod_foreclosure_starts` — (composed / no external domain)

### counties_sc
- `counties_sc.anderson_master_in_equity` — www.andersoncountysc.org
- `counties_sc.charleston_delinquent_tax` — charlestoncounty.gov, www.charlestoncounty.gov
- `counties_sc.charleston_mie` — charlestoncounty.gov
- `counties_sc.cherokee_delinquent_tax` — cherokeecountysc.gov
- `counties_sc.colleton_tax_sale` — www.colletoncounty.org
- `counties_sc.georgetown_civicengage` — www.gtcountysc.gov
- `counties_sc.greenville_tax_distress` — www.gcgis.org, www.greenvillecounty.org
- `counties_sc.horry_flc` — www.horrycountysc.gov
- `counties_sc.oconee_flc_assignment` — services1.arcgis.com, oconeesc.com
- `counties_sc.oconee_forfeited_land` — services1.arcgis.com, oconeesc.com
- `counties_sc.oconee_tax_sale` — docs.google.com, oconeesc.com
- `counties_sc.pickens_delinquent_parcels` — services1.arcgis.com, www.co.pickens.sc.us
- `counties_sc.pickens_master_in_equity` — www.co.pickens.sc.us
- `counties_sc.pickens_tax_sale` — www.co.pickens.sc.us
- `counties_sc.sc_coastal_rosters` — (composed / no external domain)
- `counties_sc.sc_county_rosters` — publicindex.sccourts.org
- `counties_sc.sc_delinquent_tax_list` — cherokeecountysc.gov
- `counties_sc.sc_dew_lien_registry` — uitax.dew.sc.gov, dew.sc.gov  **[NOT A BOARD SOURCE — cross-ref only]**
- `counties_sc.sc_flc` — www.spartanburgcounty.gov, www.andersoncountysc.org, www.pickenscountysc.gov, cherokeecountysc.gov
- `counties_sc.sc_probate_net` — www.southcarolinaprobate.net
- `counties_sc.sc_probate_notices` — (composed / no external domain)
- `counties_sc.sc_public_index` — publicindex.sccourts.org  **[SUB-LANE ONLY — broad scrape F5/ToS-walled]**
- `counties_sc.sc_public_index_lis_pendens` — publicindex.sccourts.org  **[COMPLIANT LANE — sanctioned CP-Foreclosure only]**
- `counties_sc.sc_public_notices` — www.scpublicnotices.com
- `counties_sc.sc_rod_acclaim` — (composed / no external domain)
- `counties_sc.sc_rod_cott` — (composed / no external domain)
- `counties_sc.sc_state_tax_lien` — mydorway.dor.sc.gov, dor.sc.gov
- `counties_sc.sc_tax_delinquent` — 1543.newstogo.us, www.andersoncountysc.org, www.spartanburgcounty.gov, cherokeecountysc.gov
- `counties_sc.sc_ust_registry` — apps.des.sc.gov
- `counties_sc.spartan_weekly_legals` — www.spartanweeklyonline.com
- `counties_sc.spartanburg_city_condemned` — www.cityofspartanburg.org
- `counties_sc.spartanburg_condemned` — maps.spartanburgcounty.org
- `counties_sc.spartanburg_delinquent_tax` — www.spartanburgcounty.gov
- `counties_sc.spartanburg_flc` — www.spartanburgcounty.gov
- `counties_sc.spartanburg_master_in_equity` — www.spartanburgcounty.gov
- `counties_sc.spartanburg_vacant` — services9.arcgis.com
- `counties_sc.terry_howe_flc` — terryhowe.com

### law_firms
- `law_firms.alaw` — www.alaw.net
- `law_firms.aldridge_pite` — aldridgepite.com
- `law_firms.bell_carrington` — docs.google.com, bellcarrington.com
- `law_firms.brock_scott` — www.brockandscott.com
- `law_firms.finkel` — www.finkellaw.com, www.finkellawcharleston.com
- `law_firms.hutchens` — sales.hutchenslawfirm.com
- `law_firms.ingle_firm` — www.theinglefirm.com
- `law_firms.kania` — kanialawfirm.com
- `law_firms.korn` — www.kornlawfirm.com  **[DEAD — domain parked, returns []]**
- `law_firms.mcmichael_taylor_gray` — app.powerbi.com
- `law_firms.mewborn_deselms` — www.mewbornlaw.biz
- `law_firms.rogers_townsend` — rogerstownsend.com
- `law_firms.shapiro_ingle_powerbi` — www.logs.com, app.powerbi.com, wabi-us-north-central-h-primary-api.analysis.windows.net
- `law_firms.zacchaeus` — www.zls-nc.com

### national
- `national.auction_bank_reo` — apiweb.realtybid.com, bid.auctionnetwork.com, www.williamsauction.com, www.foundersfcu.com
- `national.auction_dot_com` — www.auction.com
- `national.bid4assets` — www.bid4assets.com
- `national.cash_buyer_deeds` — (composed / no external domain)
- `national.courtlistener_adversary` — www.courtlistener.com
- `national.courtlistener_bankruptcy` — www.courtlistener.com
- `national.courtlistener_civil` — www.courtlistener.com
- `national.craigslist_fsbo` — sapi.craigslist.org
- `national.crexi_multifamily` — www.crexi.com
- `national.distressed` — (composed / no external domain)
- `national.estate_sales` — www.estatesales.net, www.estatesale.com
- `national.fannie_homepath` — homepath.fanniemae.com
- `national.first_citizens_reo` — www.firstcitizens.com
- `national.foreclosure_dot_com` — www.foreclosure.com  **[DISABLED — edge-WAF 403; redundant]**
- `national.freddie_homesteps` — www.homesteps.com
- `national.gsa_realproperty` — realestatesales.gov
- `national.homeharvest` — (composed / no external domain)
- `national.hubzu` — www.hubzu.com
- `national.hud_homestore` — www.hudhomestore.gov  **[DEAD — site decommissioned]**
- `national.hud_reac_inspection` — www.hud.gov
- `national.hud_section8_contracts` — www.hud.gov
- `national.jail_bookings` — mugshots.spartanburgsheriff.org, buncombecountyso.policetocitizen.com, 74.218.167.200, tepsweb.cityofgastonia.com
- `national.landandfarm` — www.landandfarm.com
- `national.landsofamerica` — www.land.com
- `national.landwatch` — www.landwatch.com
- `national.nc_upset_bids` — kanialawfirm.com, www.rutherfordcountync.gov
- `national.probate_foreclosure_leads` — (composed / no external domain)
- `national.propwire` — (composed / no external domain)  **[WALLED — DataDome; returns [] (won't bypass)]**
- `national.realtor_foreclosures` — (composed / no external domain)
- `national.servicelink_auction` — ui.exostechnology.com, www.servicelinkauction.com
- `national.sheriff_sales` — www.brunswicksheriff.com, www.charlestoncounty.org, www.sheriffclevelandcounty.com
- `national.trulia` — www.trulia.com
- `national.xome` — www.xome.com
- `national.zillow_bulk` — www.zillow.com
- `national.zillow_foreclosures` — www.zillow.com

### newspapers
- `newspapers.carolina_coast` — www.carolinacoastonline.com
- `newspapers.coastland_times` — www.thecoastlandtimes.com
- `newspapers.daily_courier` — www.thedigitalcourier.com
- `newspapers.hendersonville_lightning` — www.hendersonvillelightning.com
- `newspapers.index_journal` — www.indexjournal.com
- `newspapers.post_and_courier` — www.postandcourier.com
- `newspapers.shelby_star` — www.shelbystar.com
- `newspapers.tryon_bulletin` — tryondailybulletin.com, tryondailybulletin

### public_notices
- `public_notices.funeral_home_rss` — www
- `public_notices.gannett_obituaries` — www
- `public_notices.nc_notices_counties` — www.ncnotices.com
- `public_notices.ncnotices` — www.ncnotices.com
- `public_notices.publicnoticesc` — (composed / no external domain)

### reo
- `reo.treasury_seized` — www.treasury.gov
- `reo.usda_rd` — www.resales.usda.gov  **[DISABLED — froze concurrent run (perf hang)]**
- `reo.vrm_va_reo` — vrmproperties.com


## PART B — WALLS: sources we WON'T or CAN'T do (never built; not in Part A)
_Full detail (exact blocker + manual step per row) in `docs/blocked_sources_forensic.md`._


### The three categories

### Court portals
- NC eCourts / Tyler Odyssey Smart Search — **Estates** ()  _(CANT)_
- NC eCourts — **Divorce** (same portal)  _(CANT)_
- NC eCourts — power-of-sale / SP foreclosure lane (same portal)  _(WONT)_
- SC PublicIndex — civil+criminal broad sweep ()  _(WONT)_
- SC PublicIndex — Foreclosure/Lis Pendens (the ONE running lane)  _(runs)_
- SC PublicIndex — per-case DETAIL (TMS + judgment $)  _(ABSENT)_
- SC Magistrate / summary-court EVICTION rosters ()  _(ABSENT)_
- SC Family Court divorce (case-level / bulk)  _(ABSENT / WONT )_
- SC Probate / estates (case-level)  _(ABSENT)_
- Civil money judgments — SC Upstate  _(ABSENT-deferred (buildable) )_
- NC power-of-sale debt $ / SC counties not online  _(ABSENT)_

### Taxes
- Cherokee SC delinquent-tax page  _(CANT)_
- Spartanburg / Laurens delinquent-tax URLs (same file)  _(CANT)_
- Union delinquent-tax (same file)  _(CANT)_
- Pickens delinquent-tax (same file)  _(ABSENT)_
- Anderson tax balance ()  _(CANT)_
- Pickens tax balance  _(ABSENT)_
- Spartanburg tax-sale-list PDF $  _(ABSENT → SOLVED )_
- Spartanburg CAMA FTP (published creds exist)  _(WONT)_
- Beaufort SC county portal  _(CANT)_
- Owner mortgage payoff / current loan balance  _(ABSENT)_

### Deeds / ROD
- Cherokee SC ROD ()  _(WONT)_
- CCHS ROD — Burke / Lincoln / Cleveland / Henderson NC ()  /  _(CANT)_
- Rutherford / Polk — Cott RecordRoom ()  _(WONT)_
- Kofile / Oconee SC ROD ()  _(CANT)_
- AcclaimWeb consideration / sale price (Pickens)  _(ABSENT)_
- AcclaimWeb / Logan document IMAGES (lien $) — some counties  _(WONT)_
- Aumentum ROD — Buncombe / Gaston  _(CANT)_
- Buncombe / Charleston deeds portal — instrument-type SELECT-ALL  _(CANT)_
- Recorded lien / loan $ from ANY ROD index (, )  _(ABSENT)_
- SC deed-stamp OCR → sale price  _(ABSENT)_
- SC sale price + heated sqft from county GIS/assessor (Tier-0)  _(ABSENT (bulk) )_
- Mechanic's liens / distribution ($0 love-and-affection) deeds / in-footprint HOA assessment liens  _(ABSENT)_

### Contact / skip-trace
- Consumer people-search: TruePeopleSearch / FastPeopleSearch / Radaris / Whitepages  _(WONT)_
- Forward phone/skip-trace APIs (batchskiptracing / Spokeo / SearchBug)  _(WONT)_
- Owner email  _(ABSENT)_
- SC voter file (phone)  _(ABSENT / WONT )_
- Aggregator scrapers (Thunderbit / Apify / Outscraper for mobiles)  _(ABSENT)_
- Paid data brokers (PropStream / ATTOM / Regrid-premium / RentCast / NCOALink)  _(WONT)_
- OpenCorporates API  _(WONT)_
- NC SoS entity owner ()  _(runs)_
- NC SoS bulk business data  _(WONT)_
- SC SoS entity owner ()  _(WONT)_
- PropWire (skip-trace / freemium)  _(WONT)_

### Comps / valuation
- SC recorded $/sqft comps  _(ABSENT)_
- SC foreclosure sold-price comps  _(ABSENT)_
- Universal ~13% explicit-debt ceiling  _(ABSENT)_

### Federal / auction
- homesales.gov (HUD/FHA)  _(CANT)_
- US Marshals real-property sales ()  _(WONT)_
- irsauctions.gov  _(CANT)_
- GovDeals real property  _(CANT)_
- LoopNet (residential)  _(CANT)_
- Fannie HomePath search endpoint  _(CANT)_

### Business (`~/business-scraper`)
- DealStream  _(CANT)_
- LoopNet (businesses) (same file)  _(CANT)_
- BizQuest — cash_flow / revenue (memory: )  _(WONT)_
- BusinessesForSale.com — JSON-LD financials (same file)  _(CANT)_
- Murphy Business (same file)  _(CANT)_
- Google Business Profile review_count ()  _(ABSENT / CANT )_
- SC LLR contractor roster ( / ) ()  _(CANT)_
- Anderson SC business-license roster  _(ABSENT)_
- Mewborn & DeSelms (Onslow tax)  _(CANT)_

### Multifamily / coastal
- LoopNet (MF)  (docstring)  _(CANT)_
- HUD MF weekly list  _(ABSENT)_
- CMBS special-servicing (Trepp / CRED-iQ)  _(WONT)_
- Crexi MF (the ONE working source)  _(runs)_

### SoS / entity, legal-notice, law-firm rosters
- publicnoticesc.com (SCPA)  _(CANT)_
- scpublicnotices.com per-county advanced search  _(CANT)_
- ncpublicnotices.com probate detail body  _(WONT)_
- ncnotices.com / scpublicnotices.com per-notice RSS/JSON  _(ABSENT)_
- legacy.com / echovita / tributearchive (obituaries)  _(CANT)_
- RAS Crane (rascranesalesinfo.com)  _(ABSENT)_
- Tromberg-Morris-Poulin / Marinosci  _(ABSENT)_
- Meares (mearesauctions.com)  _(CANT)_
- 6 firms w/ no public sale list (Crawford & von Keller, Scott & Corley, Grimsley, Nodell Glass & Haskell, Godda  _(ABSENT)_
- Aldridge Pite  _(CANT)_
- Hubzu  _(CANT)_
- LiensNC.com (code-enforcement violations)  _(WONT)_
- Code enforcement / vacant registries / demolition orders  _(ABSENT)_

### Misc — loan/debt figure, buy-box, Reddit intel, agency tooling
- Current mortgage PAYOFF balance  _(ABSENT)_
- NC power-of-sale Notice of Sale — debt figure  _(ABSENT)_
- DOT principal (loan amount) from ROD index  _(ABSENT)_
- Structured buy box (county/zip + acreage + price) for WNC / Upstate-SC  _(ABSENT)_
- Reddit MCP tools ( / )  _(CANT)_
- Apify Reddit scraper actors (trudax/reddit-scraper-lite)  _(CANT)_
- reddit.com direct (WebFetch / WebSearch / .json)  _(CANT)_
- DuckDuckGo lite / html / Bing / Mojeek  _(CANT)_
- Bright Data (recommended paid fix for Reddit)  _(WONT)_
- SearchAtlas KRT tracked-keyword quota (sa-2)  _(ABSENT (quota exhausted) )_
- SearchAtlas PPC connector — Tillmann live campaigns  _(ABSENT (stale) )_


## PART C — COUNTIES

**SC — Upstate target (7):**
- Spartanburg, SC (FIPS 45083, seat Spartanburg)
- Anderson, SC (FIPS 45007, seat Anderson)
- Pickens, SC (FIPS 45077, seat Pickens)
- Oconee, SC (FIPS 45073, seat Walhalla)
- Cherokee, SC (FIPS 45021, seat Gaffney)
- Union, SC (FIPS 45087, seat Union)
- Laurens, SC (FIPS 45059, seat Laurens)

**NC — Western/foothills target (11):**
- Rutherford, NC (FIPS 37161, seat Rutherfordton)
- Cleveland, NC (FIPS 37045, seat Shelby)
- Henderson, NC (FIPS 37089, seat Hendersonville)
- Polk, NC (FIPS 37149, seat Columbus)
- Gaston, NC (FIPS 37071, seat Gastonia)
- Buncombe, NC (FIPS 37021, seat Asheville)
- Transylvania, NC (FIPS 37175, seat Brevard)
- McDowell, NC (FIPS 37111, seat Marion)
- Lincoln, NC (FIPS 37109, seat Lincolnton)
- Mitchell, NC (FIPS 37121, seat Bakersville)
- Burke, NC (FIPS 37023, seat Morganton)

**TARGET TOTAL: 18 core counties.**

**Coastal/other counties that appear on the board via statewide/coastal sources (outside core):** Hyde, Georgetown, Charleston, Horry, Brunswick, Onslow, Dare, Pender, Carteret, New Hanover, Beaufort.

**Explicitly DENIED (pruned, can't leak in):**
- Mecklenburg, NC
- Madison, NC
- Yancey, NC
- Haywood, NC
- Abbeville, SC
- Wake, NC
- Forsyth, NC
- Guilford, NC
- Durham, NC
- Cumberland, NC
- Alamance, NC
- Iredell, NC
- Cabarrus, NC
- Union, NC
- Pitt, NC
- Johnston, NC
- Rowan, NC
- Swain, NC
- Macon, NC
- Jackson, NC
- Graham, NC
- Clay, NC
- Cherokee, NC
- Stanly, NC
- Davidson, NC
- Anson, NC
- Newberry, SC
- Greenwood, SC
- Greenville, SC
- Horry, SC
- New Hanover, NC
- Brunswick, NC
- Onslow, NC
- Pender, NC
- Sampson, NC