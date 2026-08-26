# SOURCE EXTRACTION AUDIT — per-source, is EVERYTHING being pulled?

Auto-generated from the live registry by `scripts/gen_extraction_audit.py`. **147 scrapers**, of which **8 already wire the document harvester** (PDFs/deeds/notices) and **139 do not yet**. Re-run the script any time; it reads `discover()`, so it can never miss a source.

## The audit protocol (do this for EVERY source in the TODO table)

For each source, open the actual page (its real URL) and confirm, with eyes on the page, that the scraper captures EVERYTHING of value, not just the row it currently grabs:

1. **Every data field on the listing/detail page** — address, owner, parcel/TMS, sale date, opening bid, debt/judgment $, case number, attorney/trustee. If a field is on the page but not in the Listing, wire it.
2. **PDFs** — Notice of Sale, deed, contract package, order of sale, tax list. If the page links any, route them through `harvest_document_links()` + `stamp_documents()` so doc-OCR reads them. This is the single most common miss.
3. **Images** — property photos / assessor card images (for the vision tier). Capture the URL, do not skip it.
4. **External links** — links off to a county GIS, an auction platform, a law-firm detail page: follow them if they carry data the row lacks.
5. **Internal links** — a 'details' / 'more info' link on the SAME site that opens a richer page. Detail pages almost always carry fields the list page omits.

Then VERIFY the change three ways: it compiles, `discover()` still lists the slug, and a live `fetch()` returns real Listings with the newly-captured field populated. Never claim a fix you have not run. Stay in-footprint (18 counties, see `MASTER_GAPS_WALLS_AND_MANUAL_LANES.md`) and FREE/compliant (no CAPTCHA/login/WAF defeat).

The `hint` column flags what the CODE mentions (pdf?, img?, detail-page, links) as a starting clue for where to look. It is a hint from static text, NOT proof the source has or lacks these — your eyes on the live page are the authority.

## DONE — already harvest documents (8)

| Slug | already captures | URLs |
|---|---|---|
| `counties_nc.brunswick_legal_notices` | pdf?, deed/notice?, img?, detail-page, links | https://www.brunswickcountync.gov/912/Legal-Notices<br>https://www.brunswickcountync.gov |
| `counties_nc.nc_coastal_tax_foreclosure` | deed/notice?, img?, detail-page, links | https://www.brunswickcountync.gov/912/Legal-Notices<br>https://www.brunswickcountync.gov |
| `counties_sc.meares_auctions` | deed/notice?, img?, detail-page, links | https://www.mpa-sc.com/<br>https://maps.google.com/ |
| `counties_sc.terry_howe_auctions` | pdf?, deed/notice?, img?, detail-page | https://terryhowe.com/wp-json/wp/v2/auctions |
| `law_firms.mewborn_deselms` | pdf?, deed/notice?, detail-page, links | https://www.mewbornlaw.biz |
| `law_firms.rogers_townsend` | pdf?, deed/notice? | https://rogerstownsend.com/reports/SC_Listings.pdf<br>https://rogerstownsend.com/reports/NC_Listings.pdf |
| `national.cws_marketing` | deed/notice?, img?, detail-page, links | https://www.cwsmarketing.com/real-estate/<br>https://bid\.cwsmarketing\.com/auctions/catalog/id/\d+ |
| `national.irs_judicial_sales` | pdf?, deed/notice?, img?, detail-page, links | https://www.irsauctions.gov |

## TODO — audit each for full extraction (139)

| Slug | code hints (verify on the live page) | URLs |
|---|---|---|
| `city_websites.search` | deed/notice? | (see SOURCE_REGISTER.md) |
| `counties.column_legal_notices` | deed/notice?, detail-page | https://us-central1-enotice-production.cloudfunctions.net/api/search/public-notices<br>https://us-central1-enotice-production.cloudfunctions.net |
| `counties.multi_year_delinquent_tax` | deed/notice?, detail-page | https://services6.arcgis.com/VLA0ImJ33zhtGEaP/arcgis/rest/services<br>https://services1.arcgis.com/UOvRn2Rvzysthh3i/arcgis/rest/services |
| `counties.nod_discovery` | deed/notice? | (see SOURCE_REGISTER.md) |
| `counties.sitemap_walker` | deed/notice? | https://www.spartanburgcounty.gov<br>https://www.cherokeecountysc.gov |
| `counties_generic.arcgis_distress_layers` | deed/notice?, detail-page | https://services6.arcgis.com/VLA0ImJ33zhtGEaP/arcgis/rest/services/<br>https://www.buncombecounty.org/governing/depts/tax/ |
| `counties_generic.epa_frs_sites` | - | https://data.epa.gov/dmapservice/frs.frs_program_facility<br>https://www.epa.gov/frs |
| `counties_generic.state_contamination` | deed/notice?, detail-page | https://services2.arcgis.com/kCu40SDxsCGcuUWO/arcgis/rest/services<br>https://www.deq.nc.gov/about/divisions/waste-management/underground-storage-tanks |
| `counties_nc.asheville_helene` | - | https://services.arcgis.com/aJ16ENn1AaqdFlqx/arcgis/rest/services/ |
| `counties_nc.asheville_str_permits` | - | https://gis.ashevillenc.gov/server/rest/services/Permits/<br>https://gis.ashevillenc.gov/server/rest/services/Permits/HomestayPermitsView/MapServer/5 |
| `counties_nc.buncombe_delinquent_tax` | pdf? | https://media.buncombenc.gov/common/tax/buncombe-county-tax-department-advertisement-of-tax-liens.pdf<br>https://media.buncombenc.gov/common/tax/ |
| `counties_nc.buncombe_elderly` | - | https://gis.buncombecounty.org/arcgis/rest/services/property_bc_dis/MapServer/1/query |
| `counties_nc.buncombe_tax` | - | https://www.trumba.com/calendars/tax-foreclosures-all.json<br>https://taxforeclosures.buncombenc.gov/ |
| `counties_nc.buncombe_tax_foreclosure` | detail-page | https://www.trumba.com/calendars/tax-foreclosures-all.ics<br>https://taxforeclosures.buncombenc.gov/ |
| `counties_nc.cleveland_tax` | deed/notice? | https://www.clevelandcounty.com/main/departments/ |
| `counties_nc.gaston_surplus_properties` | pdf?, detail-page, links | https://www.gastongov.com/709/Surplus-Properties<br>https://www.gastongov.com |
| `counties_nc.henderson_code_violations` | - | https://services1.arcgis.com/ZfV5vUaX5QvLLBi9/arcgis/rest/services/<br>https://www.hendersoncountync.gov/planning/page/ |
| `counties_nc.henderson_foreclosure_parcels` | deed/notice? | https://www.arcgis.com<br>https://hendersoncounty.maps.arcgis.com |
| `counties_nc.henderson_tax` | - | https://www.hendersoncountync.gov/tax/page/tax-foreclosure-sales |
| `counties_nc.hendersonville_vacant_structures` | deed/notice?, detail-page | https://services1.arcgis.com/UTZTmZoX2rsa9yFA/arcgis/rest/services/<br>https://www.hvlnc.gov/departments/development-assistance |
| `counties_nc.lincoln_code_violations` | - | https://arcgisserver.lincolncountync.gov/arcgis/rest/services/ |
| `counties_nc.nc_county_csv_delinquent_tax` | - | https://www.nhcgov.com/DocumentCenter/View/11283/Delinquent_Taxpayers_Report_CSV |
| `counties_nc.nc_county_pdf_delinquent_tax` | pdf?, deed/notice? | https://www.lincolncountync.gov/DocumentCenter/View/25558/2025-TAXESDelinquentAdvertisementNotice<br>https://www.catawbacountync.gov/site/assets/files/11653/delinquent_advertisement_list-hdr_2026.pdf |
| `counties_nc.nc_county_tax_foreclosure` | detail-page | https://www.gastongov.com/669/Tax-Foreclosure-Sales<br>https://www.gastongov.com/671/Previous-Tax-Foreclosure-Sales |
| `counties_nc.nc_ecourts_divorce` | deed/notice?, img?, detail-page | https://portal-nc.tylertech.cloud/Portal/Home/Dashboard/29<br>https://portal-nc.tylertech.cloud/Portal |
| `counties_nc.nc_ecourts_estates` | deed/notice?, img?, detail-page | https://portal-nc.tylertech.cloud/Portal/Home/Dashboard/29<br>https://portal-nc.tylertech.cloud/Portal |
| `counties_nc.nc_ecourts_lis_pendens` | deed/notice?, detail-page | https://portal-nc.tylertech.cloud/app/NCJudgmentSearch/<br>https://portal-nc.tylertech.cloud/app/NCJudgmentSearchService/search |
| `counties_nc.nc_govdeals_real_property` | deed/notice?, detail-page | https://maestro.lqdt1.com/search/list<br>https://www.transylvaniacounty.org/news |
| `counties_nc.nc_heir_estate_parcels` | deed/notice? | (see SOURCE_REGISTER.md) |
| `counties_nc.nc_ptscloud_delinquent_tax` | - | https://bcpwa.ncptscloud.com |
| `counties_nc.nc_rod_logan` | deed/notice? | (see SOURCE_REGISTER.md) |
| `counties_nc.nc_rod_substitute_trustee` | deed/notice? | https://buncombe-recordings.permitium.com/<br>https://www.nccourts.gov/ |
| `counties_nc.new_hanover_foreclosures` | deed/notice?, detail-page | https://www.nhcgov.com/345/Foreclosures |
| `counties_nc.polk_tax` | - | https://www.polknc.gov/upcoming_auction.php |
| `counties_nc.rutherford_tax` | detail-page, links | https://www.rutherfordcountync.gov/<br>https://www.rutherfordcountync.gov/departments/ |
| `counties_nc.rutherford_wildfire_tax` | deed/notice?, detail-page | https://www.rutherfordcountync.gov/tax_search/index.php<br>https://d1ebsyxxbc7tep.cloudfront.net |
| `counties_nc.wnc_rod_foreclosure_starts` | deed/notice? | (see SOURCE_REGISTER.md) |
| `counties_sc.anderson_master_in_equity` | pdf?, deed/notice?, links | https://www.andersoncountysc.org/departments-a-z/master-in-equity/ |
| `counties_sc.charleston_delinquent_tax` | pdf?, detail-page, links | https://charlestoncounty.gov/departments/delinquent-tax/<br>https://www.charlestoncounty.gov/departments/delinquent-tax/files/RP-Tax-Sale-Listing.pdf |
| `counties_sc.charleston_mie` | pdf?, deed/notice? | https://charlestoncounty.gov/foreclosure/runninglist.html<br>https://charlestoncounty.gov/departments/master-in-equity/rosters/ |
| `counties_sc.cherokee_delinquent_tax` | pdf?, detail-page, links | https://cherokeecountysc.gov/delinquent-tax/<br>https://cherokeecountysc.gov/delinquent-tax/tax-sale-bidders/ |
| `counties_sc.colleton_tax_sale` | pdf?, detail-page, links | https://www.colletoncounty.org/delinquent-tax<br>https://www.colletoncounty.org/delinquent-tax/tax-sale |
| `counties_sc.georgetown_civicengage` | pdf?, links | https://www.gtcountysc.gov |
| `counties_sc.greenville_tax_distress` | deed/notice? | https://www.gcgis.org/arcgis/rest/services/GreenvilleJS/Map_Layers_JS/MapServer<br>https://www.greenvillecounty.org/appsAS400/Taxsale/ |
| `counties_sc.horry_flc` | detail-page, links | https://www.horrycountysc.gov/boards-and-commissions/<br>https://www.horrycountysc.gov/media/om1d2bwo/2025-flc-list-42126.xlsx |
| `counties_sc.oconee_flc_assignment` | - | https://services1.arcgis.com/UOvRn2Rvzysthh3i/arcgis/rest/services/<br>https://oconeesc.com/auditor-home/forfeited-land |
| `counties_sc.oconee_forfeited_land` | - | https://services1.arcgis.com/UOvRn2Rvzysthh3i/arcgis/rest/services/<br>https://oconeesc.com/auditor-home/forfeited-land |
| `counties_sc.oconee_tax_sale` | - | https://oconeesc.com/delinquent-tax/sale-list |
| `counties_sc.pickens_delinquent_parcels` | - | https://services1.arcgis.com/59960rq18IxUcAVI/arcgis/rest/services<br>https://www.co.pickens.sc.us/departments/delinquent_tax/index.php |
| `counties_sc.pickens_master_in_equity` | pdf?, deed/notice?, links | https://www.co.pickens.sc.us/departments/master_in_equity/sales_rosters.php<br>https://www.co.pickens.sc.us/ |
| `counties_sc.pickens_tax_sale` | pdf?, detail-page, links | https://www.co.pickens.sc.us/departments/delinquent_tax/index.php<br>https://www.co.pickens.sc.us/ |
| `counties_sc.sc_coastal_rosters` | deed/notice?, detail-page, links | (see SOURCE_REGISTER.md) |
| `counties_sc.sc_county_rosters` | detail-page, links | https://publicindex.sccourts.org |
| `counties_sc.sc_delinquent_tax_list` | pdf?, detail-page, links | https://cherokeecountysc.gov/delinquent-tax/tax-sale-bidders/ |
| `counties_sc.sc_dew_lien_registry` | - | https://uitax.dew.sc.gov/LienRegistry/<br>https://dew.sc.gov/benefit-lien-registry |
| `counties_sc.sc_flc` | pdf?, img?, detail-page, links | https://www.spartanburgcounty.gov/216/Tax-Collector<br>https://www.andersoncountysc.org/departments-a-z/treasurer/ |
| `counties_sc.sc_probate_net` | deed/notice? | https://www.southcarolinaprobate.net/search/ |
| `counties_sc.sc_probate_notices` | deed/notice? | (see SOURCE_REGISTER.md) |
| `counties_sc.sc_public_index` | deed/notice?, detail-page | https://publicindex.sccourts.org/<County |
| `counties_sc.sc_public_index_lis_pendens` | deed/notice?, detail-page | https://publicindex.sccourts.org/<County |
| `counties_sc.sc_public_notices` | deed/notice?, detail-page | https://www.scpublicnotices.com/Search.aspx |
| `counties_sc.sc_rod_acclaim` | deed/notice? | (see SOURCE_REGISTER.md) |
| `counties_sc.sc_rod_cott` | deed/notice? | (see SOURCE_REGISTER.md) |
| `counties_sc.sc_state_tax_lien` | - | https://mydorway.dor.sc.gov/<br>https://dor.sc.gov/delinquent-taxpayers |
| `counties_sc.sc_tax_delinquent` | pdf?, deed/notice?, img?, detail-page, links | https://1543.newstogo.us/editionviewer/default.aspx<br>https://www.andersoncountysc.org/departments-a-z/treasurer/ |
| `counties_sc.sc_ust_registry` | detail-page | https://apps.des.sc.gov/USTRegistry/ |
| `counties_sc.spartan_weekly_legals` | deed/notice?, detail-page, links | https://www.spartanweeklyonline.com |
| `counties_sc.spartanburg_city_condemned` | - | https://www.cityofspartanburg.org/robots.txt<br>https://www.cityofspartanburg.org/DocumentCenter/View/1901/ |
| `counties_sc.spartanburg_condemned` | - | https://maps.spartanburgcounty.org/server/rest/services/ |
| `counties_sc.spartanburg_delinquent_tax` | pdf? | https://www.spartanburgcounty.gov/DocumentCenter/View/11161/Real-Property-Tax-Sale-List-PDF<br>https://www.spartanburgcounty.gov/DocumentCenter/View/11161/ |
| `counties_sc.spartanburg_flc` | - | https://www.spartanburgcounty.gov/DocumentCenter/View/104130 |
| `counties_sc.spartanburg_master_in_equity` | pdf? | https://www.spartanburgcounty.gov/DocumentCenter/View/3392/Sale-Results<br>https://www.spartanburgcounty.gov/DocumentCenter/View/11824/Deficiency-Sale |
| `counties_sc.spartanburg_vacant` | - | https://services9.arcgis.com/HoRra3ATPLGmyjn6/arcgis/rest/services/<br>https://services9.arcgis.com/HoRra3ATPLGmyjn6/ |
| `counties_sc.terry_howe_flc` | - | https://terryhowe.com/wp-json/wp/v2/auctions |
| `law_firms.alaw` | deed/notice?, detail-page | https://www.alaw.net/foreclosure-sales/north-carolina/<br>https://www.alaw.net/foreclosure-sales/south-carolina/ |
| `law_firms.aldridge_pite` | deed/notice? | https://aldridgepite.com/sale-day-listings-selection/foreclosure-listings-north-carolina/<br>https://aldridgepite.com/disclaimer-north-carolina/ |
| `law_firms.bell_carrington` | deed/notice?, detail-page | https://docs.google.com/spreadsheets/d/e/<br>https://bellcarrington.com/foreclosure-sales/ |
| `law_firms.brock_scott` | deed/notice?, detail-page | https://www.brockandscott.com/foreclosure-sales/ |
| `law_firms.finkel` | pdf?, deed/notice?, img? | https://www.finkellaw.com/images/Webs.pdf<br>https://www.finkellawcharleston.com/images/Webs.pdf |
| `law_firms.hutchens` | deed/notice?, detail-page | https://sales.hutchenslawfirm.com/NCfcSalesList.aspx<br>https://sales.hutchenslawfirm.com/SCfcSalesList.aspx |
| `law_firms.ingle_firm` | deed/notice? | https://www.theinglefirm.com/Sales.aspx |
| `law_firms.kania` | deed/notice?, detail-page, links | https://kanialawfirm.com/tax-foreclosures/foreclosure-listings/<br>https://kanialawfirm.com/wp-admin/admin-ajax.php |
| `law_firms.korn` | deed/notice? | https://www.kornlawfirm.com/foreclosure-sales/<br>https://www.kornlawfirm.com/sales/ |
| `law_firms.mcmichael_taylor_gray` | deed/notice? | https://app.powerbi.com/view |
| `law_firms.shapiro_ingle_powerbi` | deed/notice? | https://www.logs.com/nc-upcoming-sales-report.html<br>https://app.powerbi.com/view |
| `law_firms.zacchaeus` | deed/notice?, links | https://www.zls-nc.com/listings |
| `national.auction_bank_reo` | - | https://apiweb.realtybid.com/rest/RBIAPI/<br>https://bid.auctionnetwork.com/Auctions |
| `national.auction_dot_com` | img?, detail-page, links | https://www.auction.com/residential/nc/<br>https://www.auction.com/residential/sc/ |
| `national.bid4assets` | links | https://www.bid4assets.com/storefront/index.cfm |
| `national.cash_buyer_deeds` | deed/notice?, img? | (see SOURCE_REGISTER.md) |
| `national.courtlistener_adversary` | deed/notice?, links | https://www.courtlistener.com |
| `national.courtlistener_bankruptcy` | deed/notice?, links | https://www.courtlistener.com/sign-up/<br>https://www.courtlistener.com/profile/api/ |
| `national.courtlistener_civil` | deed/notice?, links | https://www.courtlistener.com |
| `national.craigslist_fsbo` | detail-page | https://sapi.craigslist.org/web/v8/postings/search/full |
| `national.crexi_multifamily` | detail-page, links | https://www.crexi.com |
| `national.distressed` | deed/notice?, img? | (see SOURCE_REGISTER.md) |
| `national.estate_sales` | deed/notice?, detail-page, links | https://www.estatesales.net<br>https://www.estatesale.com |
| `national.fannie_homepath` | img?, detail-page | https://homepath.fanniemae.com/cfl/property-inventory/search<br>https://homepath.fanniemae.com/ |
| `national.first_citizens_reo` | - | https://www.firstcitizens.com/real-estate |
| `national.foreclosure_dot_com` | img?, detail-page | https://www.foreclosure.com/listings/north-carolina/<br>https://www.foreclosure.com/listings/south-carolina/ |
| `national.freddie_homesteps` | detail-page, links | https://www.homesteps.com/listing/search<br>https://www.homesteps.com/ |
| `national.gsa_realproperty` | detail-page | https://realestatesales.gov |
| `national.hibid_real_estate` | - | https://hibid.com/graphql<br>https://hibid.com |
| `national.homeharvest` | deed/notice?, img? | https://github.com/ZacharyHampton/HomeHarvest |
| `national.hubzu` | - | https://www.hubzu.com/ |
| `national.hud_homestore` | img?, detail-page | https://www.hudhomestore.gov/searchresult<br>https://www.hudhomestore.gov |
| `national.hud_reac_inspection` | detail-page | https://www.hud.gov/sites/default/files/Housing/documents/MF-Inspection-Report.xls<br>https://www.hud.gov/sites/default/files/Housing/documents/ |
| `national.hud_section8_contracts` | - | https://www.hud.gov/hud-partners/multifamily-assist-section8-database<br>https://www.hud.gov/sites/dfiles/Housing/documents/ |
| `national.jail_bookings` | img?, detail-page | http://mugshots.spartanburgsheriff.org/<br>https://buncombecountyso.policetocitizen.com|23 |
| `national.landandfarm` | img?, detail-page | (see SOURCE_REGISTER.md) |
| `national.landsofamerica` | img?, detail-page | (see SOURCE_REGISTER.md) |
| `national.landwatch` | img? | (see SOURCE_REGISTER.md) |
| `national.nc_upset_bids` | detail-page, links | https://kanialawfirm.com/tax-foreclosures/foreclosure-listings/<br>https://kanialawfirm.com/wp-admin/admin-ajax.php |
| `national.probate_foreclosure_leads` | deed/notice? | (see SOURCE_REGISTER.md) |
| `national.propwire` | - | (see SOURCE_REGISTER.md) |
| `national.realtor_foreclosures` | deed/notice?, img? | (see SOURCE_REGISTER.md) |
| `national.servicelink_auction` | deed/notice? | https://ui.exostechnology.com/api/listingsvc/v1/listings<br>https://www.servicelinkauction.com |
| `national.sheriff_sales` | deed/notice?, links | https://www.brunswicksheriff.com<br>https://www.charlestoncounty.org |
| `national.trulia` | deed/notice?, img?, links | https://www.trulia.com/foreclosures/ |
| `national.usda_properties` | img?, detail-page, links | https://usdaproperties.com/property/<state<br>https://www.usdaproperties.com/property/sc/county/<county-slug |
| `national.xome` | deed/notice?, img?, detail-page, links | https://www.xome.com/auctions/bank-owned<br>https://www.xome.com/auctions/foreclosure-homes |
| `national.zillow_bulk` | img?, detail-page | (see SOURCE_REGISTER.md) |
| `national.zillow_foreclosures` | deed/notice?, img?, detail-page | (see SOURCE_REGISTER.md) |
| `newspapers.carolina_coast` | deed/notice?, detail-page | https://www.carolinacoastonline.com/classifieds/ |
| `newspapers.coastland_times` | deed/notice?, img?, detail-page, links | https://www.thecoastlandtimes.com |
| `newspapers.daily_courier` | deed/notice?, detail-page, links | https://www.thedigitalcourier.com/classifieds/community/announcements/legal/<br>https://www.thedigitalcourier.com |
| `newspapers.hendersonville_lightning` | deed/notice? | https://www.hendersonvillelightning.com/legal-ads/130-foreclosures.html |
| `newspapers.index_journal` | deed/notice?, detail-page | https://www.indexjournal.com/classifieds/community/announcements/legal/ |
| `newspapers.post_and_courier` | deed/notice?, detail-page | https://www.postandcourier.com/classifieds_new/community/announcements/ |
| `newspapers.shelby_star` | deed/notice?, detail-page, links | https://www.shelbystar.com<br>https://www.shelbystar.com/ |
| `newspapers.tryon_bulletin` | deed/notice?, links | https://tryondailybulletin.com<br>https://tryondailybulletin.com/ |
| `public_notices.funeral_home_rss` | deed/notice? | (see SOURCE_REGISTER.md) |
| `public_notices.gannett_obituaries` | deed/notice? | (see SOURCE_REGISTER.md) |
| `public_notices.nc_notices_counties` | deed/notice?, detail-page | https://www.ncnotices.com/Search.aspx |
| `public_notices.ncnotices` | deed/notice?, detail-page, links | https://www.ncnotices.com/ |
| `public_notices.publicnoticesc` | deed/notice? | (see SOURCE_REGISTER.md) |
| `reo.treasury_seized` | - | https://www.treasury.gov/auctions/treasury/rp/realprop.shtml |
| `reo.usda_rd` | img?, detail-page, links | https://www.resales.usda.gov/resales/public<br>https://www.resales.usda.gov |
| `reo.vrm_va_reo` | img?, detail-page, links | https://vrmproperties.com/<br>https://vrmproperties.com |
