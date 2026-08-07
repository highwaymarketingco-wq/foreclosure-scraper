# MASTER SOURCE REGISTER

Generated 2026-08-07 00:13 UTC by `scripts/gen_source_register.py`. **Re-run it instead of editing this file** — the built half is read from the live registry and the live board, so hand edits are overwritten and go stale.

- Scrapers in the registry: **137**
- Producing rows on the board: **86**
- Registered but contributing ZERO rows: **51**
- Confirmed real and not yet built: **9**
- Board read: `data/checkpoint/board.json.gz` (47,125 rows)

Sections: [1 Built and producing](#1-built-and-producing) · [2 Built but zero rows](#2-built-but-producing-zero-rows) · [3 Not built yet](#3-not-built-yet) · [4 Will not / cannot build](#4-will-not-build-cannot-build-not-published) · [5 Checked and rejected](#5-checked-and-rejected-not-a-distress-signal)

---

## 1. Built and producing

Live row counts are what the source actually contributed to the board read above, not a capacity estimate.

| Slug | Rows | Top counties | URLs in the module |
|---|---:|---|---|
| `counties_nc.rutherford_tax` | 6,830 | Rutherford NC (6830) | `https://www.rutherfordcountync.gov/`<br>`https://www.rutherfordcountync.gov/departments/` |
| `national.courtlistener_bankruptcy` | 4,215 | Anderson SC (105), Laurens SC (49), Buncombe NC (47) | `https://www.courtlistener.com/sign-up/`<br>`https://www.courtlistener.com/profile/api/`<br>`https://www.courtlistener.com/api/rest/v4`<br>_+1 more_ |
| `counties_nc.nc_county_pdf_delinquent_tax` | 3,839 | McDowell NC (2247), Lincoln NC (1592) | `https://www.lincolncountync.gov/DocumentCenter/View/25558/2025-TAXESDelinquentAdvertisementNotice`<br>`https://www.catawbacountync.gov/site/assets/files/11653/delinquent_advertisement_list-hdr_2026.pdf`<br>`https://mcdowellnc.gov/departments/tax-collections/tax-lien-advertisement/ADVERTISEMENT-LIST-FINAL-2025.pdf` |
| `counties_sc.sc_public_index` | 3,796 | Anderson SC (673), Spartanburg SC (665), Laurens SC (663) | `https://publicindex.sccourts.org/`<br>`https://publicindex.sccourts.org/{county` |
| `counties_nc.buncombe_elderly` | 3,548 | Buncombe NC (3547), Gaston NC (1) | `https://gis.buncombecounty.org/arcgis/rest/services/property_bc_dis/MapServer/1/query` |
| `counties_sc.spartanburg_vacant` | 3,310 | Spartanburg SC (3310) | `https://services9.arcgis.com/HoRra3ATPLGmyjn6/arcgis/rest/services/`<br>`https://services9.arcgis.com/HoRra3ATPLGmyjn6/` |
| `counties_nc.nc_ptscloud_delinquent_tax` | 2,880 | Henderson NC (1513), Hyde NC (1367) | `https://bcpwa.ncptscloud.com` |
| `counties_sc.spartanburg_delinquent_tax` | 2,082 | Spartanburg SC (2082) | `https://www.spartanburgcounty.gov/DocumentCenter/View/11161/Real-Property-Tax-Sale-List-PDF`<br>`https://www.spartanburgcounty.gov/DocumentCenter/View/11161/`<br>`https://www.spartanburgcounty.gov/640/2025-Tax-Sale-Info` |
| `counties_sc.pickens_delinquent_parcels` | 1,928 | Pickens SC (1928) | `https://services1.arcgis.com/59960rq18IxUcAVI/arcgis/rest/services`<br>`https://www.co.pickens.sc.us/departments/delinquent_tax/index.php` |
| `counties_sc.spartanburg_condemned` | 1,658 | Spartanburg SC (1658) | `https://maps.spartanburgcounty.org/server/rest/services/` |
| `counties_nc.buncombe_delinquent_tax` | 1,155 | Buncombe NC (1155) | `https://media.buncombenc.gov/common/tax/buncombe-county-tax-department-advertisement-of-tax-liens.pdf`<br>`https://media.buncombenc.gov/common/tax/` |
| `counties_nc.nc_heir_estate_parcels` | 982 | Rutherford NC (149), Polk NC (135), Gaston NC (79) | _(no literal URL in module)_ |
| `counties_nc.asheville_helene` | 823 | Buncombe NC (823) | `https://services.arcgis.com/aJ16ENn1AaqdFlqx/arcgis/rest/services/` |
| `counties.multi_year_delinquent_tax` | 731 | Buncombe NC (595), Oconee SC (135), Pickens SC (1) | `https://services6.arcgis.com/VLA0ImJ33zhtGEaP/arcgis/rest/services`<br>`https://services1.arcgis.com/UOvRn2Rvzysthh3i/arcgis/rest/services`<br>`https://services1.arcgis.com/59960rq18IxUcAVI/arcgis/rest/services`<br>_+3 more_ |
| `counties_nc.asheville_str_permits` | 640 | Buncombe NC (640) | `https://gis.ashevillenc.gov/server/rest/services/Permits/`<br>`https://gis.ashevillenc.gov/server/rest/services/Permits/HomestayPermitsView/MapServer/5` |
| `counties_nc.nc_ecourts_lis_pendens` | 597 | Brunswick NC (122), Onslow NC (83), Henderson NC (63) | `https://portal-nc.tylertech.cloud/app/NCJudgmentSearch/`<br>`https://portal-nc.tylertech.cloud/app/NCJudgmentSearchService/search`<br>`https://portal-nc.tylertech.cloud` |
| `counties_sc.oconee_flc_assignment` | 585 | Oconee SC (585) | `https://services1.arcgis.com/UOvRn2Rvzysthh3i/arcgis/rest/services/`<br>`https://oconeesc.com/auditor-home/forfeited-land` |
| `national.landwatch` | 478 | Burke NC (38), Dare NC (32), Carteret NC (26) | `https://www.landwatch.com/{state_slug` |
| `counties_sc.oconee_forfeited_land` | 454 | Oconee SC (454) | `https://services1.arcgis.com/UOvRn2Rvzysthh3i/arcgis/rest/services/`<br>`https://oconeesc.com/auditor-home/forfeited-land` |
| `national.distressed` | 444 | Spartanburg SC (72), Anderson SC (61), Gaston NC (57) | _(no literal URL in module)_ |
| `counties_sc.georgetown_civicengage` | 408 | Georgetown SC (408) | `https://www.gtcountysc.gov` |
| `public_notices.nc_notices_counties` | 393 | Buncombe NC (152), Gaston NC (82), Henderson NC (40) | `https://www.ncnotices.com/Search.aspx`<br>`https://www.ncnotices.com/Details.aspx?ID={` |
| `counties_sc.sc_public_index_lis_pendens` | 382 | Anderson SC (143), Spartanburg SC (131), Laurens SC (37) | `https://publicindex.sccourts.org/`<br>`https://publicindex.sccourts.org/{county` |
| `national.hud_reac_inspection` | 381 | Spartanburg SC (63), Buncombe NC (35), Gaston NC (31) | `https://www.hud.gov/sites/default/files/Housing/documents/MF-Inspection-Report.xls```<br>`https://www.hud.gov/sites/default/files/Housing/documents/`<br>`https://www.hud.gov/stat/mfh/inspection-scores` |
| `national.landandfarm` | 378 | Gaston NC (28), Henderson NC (27), Mitchell NC (26) | `https://www.landandfarm.com/search/{state_slug` |
| `counties_sc.sc_public_notices` | 349 | Cherokee SC (116), Laurens SC (62), Oconee SC (57) | `https://www.scpublicnotices.com/Search.aspx`<br>`https://www.scpublicnotices.com/Details.aspx?ID={n[` |
| `counties_sc.sc_probate_net` | 250 | Charleston SC (250) | `https://www.southcarolinaprobate.net/search/```<br>`https://www.southcarolinaprobate.net/search/` |
| `national.hud_section8_contracts` | 245 | Spartanburg SC (29), Gaston NC (25), Buncombe NC (18) | `https://www.hud.gov/hud-partners/multifamily-assist-section8-database`<br>`https://www.hud.gov/sites/dfiles/Housing/documents/`<br>`https://www.hud.gov/hud-partners/` |
| `counties_nc.nc_ecourts_divorce` | 197 | Buncombe NC (42), Gaston NC (41), Brunswick NC (31) | `https://portal-nc.tylertech.cloud/Portal/Home/Dashboard/29`<br>`https://portal-nc.tylertech.cloud/Portal`<br>`https://portal-nc.tylertech.cloud` |
| `national.fannie_homepath` | 188 | Spartanburg SC (49), Pickens SC (29), Laurens SC (27) | `https://homepath.fanniemae.com/cfl/property-inventory/search`<br>`https://homepath.fanniemae.com/`<br>`https://homepath.fanniemae.com/property/{uuid` |
| `public_notices.gannett_obituaries` | 188 | Buncombe NC (58), Henderson NC (32), Spartanburg SC (32) | `https://www.{host` |
| `counties_sc.spartan_weekly_legals` | 187 | Spartanburg SC (187) | `https://www.spartanweeklyonline.com` |
| `counties_sc.sc_rod_acclaim` | 179 | Pickens SC (179) | _(no literal URL in module)_ |
| `counties_nc.henderson_code_violations` | 156 | Henderson NC (156) | `https://services1.arcgis.com/ZfV5vUaX5QvLLBi9/arcgis/rest/services/`<br>`https://www.hendersoncountync.gov/planning/page/` |
| `counties.column_legal_notices` | 134 | McDowell NC (54), Burke NC (27), Gaston NC (19) | `https://us-central1-enotice-production.cloudfunctions.net/api/search/public-notices`<br>`https://us-central1-enotice-production.cloudfunctions.net` |
| `national.courtlistener_adversary` | 122 | Buncombe NC (6), Cleveland NC (3), Polk NC (2) | `https://www.courtlistener.com` |
| `law_firms.brock_scott` | 108 | Spartanburg SC (22), Anderson SC (11), Gaston NC (10) | `https://www.brockandscott.com/foreclosure-sales/` |
| `national.foreclosure_dot_com` | 94 | Gaston NC (21), Anderson SC (17), Spartanburg SC (16) | `https://www.foreclosure.com/listings/north-carolina/`<br>`https://www.foreclosure.com/listings/south-carolina/` |
| `law_firms.hutchens` | 93 | Horry SC (14), Buncombe NC (8), Gaston NC (8) | `https://sales.hutchenslawfirm.com/NCfcSalesList.aspx`<br>`https://sales.hutchenslawfirm.com/SCfcSalesList.aspx` |
| `counties_sc.spartanburg_city_condemned` | 90 | Spartanburg SC (90) | `https://www.cityofspartanburg.org/robots.txt`<br>`https://www.cityofspartanburg.org/DocumentCenter/View/1901/`<br>`https://www.cityofspartanburg.org/` |
| `national.zillow_bulk` | 86 | Spartanburg SC (17), Gaston NC (12), Anderson SC (10) | `https://www.zillow.com/{state.lower(` |
| `national.zillow_foreclosures` | 86 | Buncombe NC (6), Spartanburg SC (6), Gaston NC (5) | `https://www.zillow.com/{state.lower(` |
| `national.cash_buyer_deeds` | 66 | McDowell NC (66) | `https://{host` |
| `counties_sc.charleston_mie` | 60 | Charleston SC (60) | `https://charlestoncounty.gov/foreclosure/runninglist.html`<br>`https://charlestoncounty.gov/departments/master-in-equity/rosters/` |
| `law_firms.shapiro_ingle_powerbi` | 57 | Gaston NC (19), Buncombe NC (15), Cleveland NC (5) | `https://www.logs.com/nc-upcoming-sales-report.html`<br>`https://app.powerbi.com/view?r=`<br>`https://wabi-us-north-central-h-primary-api.analysis.windows.net`<br>_+2 more_ |
| `counties_nc.hendersonville_vacant_structures` | 50 | Henderson NC (50) | `https://services1.arcgis.com/UTZTmZoX2rsa9yFA/arcgis/rest/services/`<br>`https://www.hvlnc.gov/departments/development-assistance` |
| `public_notices.ncnotices` | 42 | Buncombe NC (32), Polk NC (5), Lincoln NC (1) | `https://www.ncnotices.com/`<br>`https://www.ncnotices.com{raw_href` |
| `national.auction_dot_com` | 35 | Spartanburg SC (3), Henderson NC (2), Cherokee SC (2) | `https://www.auction.com/residential/nc/`<br>`https://www.auction.com/residential/sc/`<br>`https://www.auction.com/details/{slug` |
| `law_firms.kania` | 34 | Burke NC (13), Cleveland NC (8), Lincoln NC (6) | `https://kanialawfirm.com/tax-foreclosures/foreclosure-listings/`<br>`https://kanialawfirm.com/wp-admin/admin-ajax.php` |
| `counties_sc.terry_howe_flc` | 31 | Laurens SC (29), Spartanburg SC (2) | `https://terryhowe.com/wp-json/wp/v2/auctions?per_page=100&_fields=id,title,link,content` |
| `counties_nc.nc_rod_logan` | 28 | Transylvania NC (15), McDowell NC (13) | _(no literal URL in module)_ |
| `counties_sc.sc_state_tax_lien` | 28 | Horry SC (14), Charleston SC (5), Spartanburg SC (3) | `https://mydorway.dor.sc.gov/?link=delinquentind`<br>`https://dor.sc.gov/delinquent-taxpayers` |
| `law_firms.bell_carrington` | 28 | Spartanburg SC (7), Anderson SC (4), Horry SC (4) | `https://docs.google.com/spreadsheets/d/e/`<br>`https://bellcarrington.com/foreclosure-sales/` |
| `national.nc_upset_bids` | 28 | Rutherford NC (20), Cleveland NC (4), Lincoln NC (2) | `https://kanialawfirm.com/tax-foreclosures/foreclosure-listings/`<br>`https://kanialawfirm.com/wp-admin/admin-ajax.php`<br>`https://www.rutherfordcountync.gov/departments/` |
| `national.crexi_multifamily` | 24 | Spartanburg SC (3), Polk NC (2), Gaston NC (2) | `https://www.crexi.com` |
| `national.servicelink_auction` | 24 | Gaston NC (5), Buncombe NC (4), Spartanburg SC (4) | `https://ui.exostechnology.com/api/listingsvc/v1/listings?limit=100&state={ST`<br>`https://ui.exostechnology.com/api/listingsvc/v1/listings`<br>`https://www.servicelinkauction.com`<br>_+1 more_ |
| `counties_sc.horry_flc` | 23 | Horry SC (23) | `https://www.horrycountysc.gov/boards-and-commissions/`<br>`https://www.horrycountysc.gov/media/om1d2bwo/2025-flc-list-42126.xlsx`<br>`https://www.horrycountysc.gov` |
| `counties_nc.buncombe_tax` | 21 | Buncombe NC (21) | `https://www.trumba.com/calendars/tax-foreclosures-all.json`<br>`https://taxforeclosures.buncombenc.gov/` |
| `national.hubzu` | 21 | Spartanburg SC (5), Buncombe NC (2), Anderson SC (2) | `https://www.hubzu.com/portal/auctions?state={state`<br>`https://www.hubzu.com/`<br>`https://www.hubzu.com{url` |
| `law_firms.mcmichael_taylor_gray` | 20 | New Hanover NC (3), Anderson SC (3), Charleston SC (2) | `https://app.powerbi.com/view?r=eyJrIjoiOTQwOTdiYWYtOGQwMy00OGUzLWI4MjktOTczNDc0ODE2ZGY1IiwidCI6IjEzZDFlNzhjLTgyNDgtNGVlYS04OWY3LWQzNGIzZWJkOGM3OSIsImMiOjN9`<br>`https://app.powerbi.com/view?r=eyJrIjoiOTQwOTdiYWYtOGQwMy00OGUzLWI4MjktOTczNDc0ODE2ZGY1Ii` |
| `national.xome` | 20 | Anderson SC (3), Gaston NC (2), Cleveland NC (2) | `https://www.xome.com/auctions/bank-owned`<br>`https://www.xome.com/auctions/foreclosure-homes`<br>`https://www.xome.com/auctions/foreclosuresales`<br>_+1 more_ |
| `national.homeharvest` | 18 | Anderson SC (5), Spartanburg SC (3), Burke NC (3) | `https://github.com/ZacharyHampton/HomeHarvest` |
| `counties.nod_discovery` | 17 | Cleveland NC (8), Burke NC (7), Lincoln NC (2) | `https://{host`<br>`https://{kofile.KOFILE_COUNTIES[(state`<br>`https://example.invalid/` |
| `counties_nc.nc_rod_substitute_trustee` | 17 | Cleveland NC (8), Burke NC (7), Henderson NC (1) | `https://buncombe-recordings.permitium.com/```<br>`https://www.nccourts.gov/` |
| `counties_nc.henderson_foreclosure_parcels` | 14 | Henderson NC (14) | `https://www.arcgis.com`<br>`https://hendersoncounty.maps.arcgis.com`<br>`https://experience.arcgis.com/experience/` |
| `national.estate_sales` | 13 | Spartanburg SC (4), Cleveland NC (3), Buncombe NC (2) | `https://www.estatesales.net`<br>`https://www.estatesale.com`<br>`https://{host` |
| `counties_sc.pickens_master_in_equity` | 12 | Pickens SC (12) | `https://www.co.pickens.sc.us/departments/master_in_equity/sales_rosters.php`<br>`https://www.co.pickens.sc.us/` |
| `reo.vrm_va_reo` | 12 | - | `https://vrmproperties.com/`<br>`https://vrmproperties.com` |
| `counties_sc.anderson_master_in_equity` | 11 | Anderson SC (11) | `https://www.andersoncountysc.org/departments-a-z/master-in-equity/`<br>`https://www.andersoncountysc.org{href` |
| `counties_sc.sc_county_rosters` | 11 | Oconee SC (7), Laurens SC (4) | `https://publicindex.sccourts.org` |
| `law_firms.rogers_townsend` | 9 | Spartanburg SC (4), Anderson SC (3), Oconee SC (1) | `https://rogerstownsend.com/reports/SC_Listings.pdf`<br>`https://rogerstownsend.com/reports/NC_Listings.pdf` |
| `national.jail_bookings` | 9 | Buncombe NC (2), Cleveland NC (2), Anderson SC (2) | `http://mugshots.spartanburgsheriff.org/`<br>`https://buncombecountyso.policetocitizen.com|23`<br>`http://74.218.167.200/p2c`<br>_+8 more_ |
| `national.trulia` | 8 | Spartanburg SC (5) | `https://www.trulia.com/foreclosures/`<br>`https://www.trulia.com{href` |
| `counties_nc.nc_county_tax_foreclosure` | 6 | Rutherford NC (3), Gaston NC (2), McDowell NC (1) | `https://www.gastongov.com/669/Tax-Foreclosure-Sales`<br>`https://www.gastongov.com/671/Previous-Tax-Foreclosure-Sales`<br>`https://mcdowellnc.gov/departments/tax-collections/tax-foreclosures/upcoming-tax-foreclosure-sales`<br>_+1 more_ |
| `national.freddie_homesteps` | 6 | Spartanburg SC (1) | `https://www.homesteps.com/listing/search?search=NC`<br>`https://www.homesteps.com/listing/search?search=SC`<br>`https://www.homesteps.com/`<br>_+1 more_ |
| `counties_nc.cleveland_tax` | 5 | Cleveland NC (5) | `https://www.clevelandcounty.com/main/departments/` |
| `counties_sc.spartanburg_flc` | 5 | Spartanburg SC (5) | `https://www.spartanburgcounty.gov/DocumentCenter/View/104130` |
| `national.hud_homestore` | 5 | Spartanburg SC (3), Burke NC (1), Gaston NC (1) | `https://www.hudhomestore.gov/searchresult?handler=GetFilteredResult`<br>`https://www.hudhomestore.gov` |
| `national.realtor_foreclosures` | 3 | Spartanburg SC (2), Burke NC (1) | _(no literal URL in module)_ |
| `counties_nc.nc_govdeals_real_property` | 2 | Anderson SC (2) | `https://maestro.lqdt1.com/search/list`<br>`https://www.transylvaniacounty.org/news`<br>`https://www.govdeals.com/asset/{asset_id`<br>_+2 more_ |
| `national.sheriff_sales` | 2 | Cleveland NC (2) | `https://www.brunswicksheriff.com`<br>`https://www.charlestoncounty.org`<br>`https://www.sheriffclevelandcounty.com`<br>_+1 more_ |
| `newspapers.carolina_coast` | 2 | Onslow NC (2) | `https://www.carolinacoastonline.com/classifieds/?f=rss&q=foreclosure`<br>`https://www.carolinacoastonline.com/classifieds/?f=rss&q=substitute+trustee`<br>`https://www.carolinacoastonline.com/classifieds/?f=rss&q=trustee+sale` |
| `counties_sc.sc_rod_cott` | 1 | Union SC (1) | _(no literal URL in module)_ |
| `counties_sc.spartanburg_master_in_equity` | 1 | Spartanburg SC (1) | `https://www.spartanburgcounty.gov/DocumentCenter/View/3392/Sale-Results`<br>`https://www.spartanburgcounty.gov/DocumentCenter/View/11824/Deficiency-Sale` |
| `national.courtlistener_civil` | 1 | - | `https://www.courtlistener.com` |
| `newspapers.coastland_times` | 1 | Dare NC (1) | `https://www.thecoastlandtimes.com` |

## 2. Built but producing zero rows

Registered and importable, contributing nothing to the board read above. A zero here is NOT automatically a bug: it can mean the upstream is genuinely empty right now, the source is seasonal, it is gated off, it is blocked (see section 4), or it simply was not in the last run's source list.

| Slug | URLs in the module |
|---|---|
| `city_websites.search` | `https://{domain` |
| `counties.sitemap_walker` | `https://www.spartanburgcounty.gov`<br>`https://www.cherokeecountysc.gov`<br>_+10 more_ |
| `counties_generic.arcgis_distress_layers` | `https://services6.arcgis.com/VLA0ImJ33zhtGEaP/arcgis/rest/services/`<br>`https://www.buncombecounty.org/governing/depts/tax/`<br>_+20 more_ |
| `counties_generic.epa_frs_sites` | `https://data.epa.gov/dmapservice/frs.frs_program_facility`<br>`https://www.epa.gov/frs` |
| `counties_generic.state_contamination` | `https://services2.arcgis.com/kCu40SDxsCGcuUWO/arcgis/rest/services`<br>`https://www.deq.nc.gov/about/divisions/waste-management/underground-storage-tanks`<br>_+2 more_ |
| `counties_nc.brunswick_legal_notices` | `https://www.brunswickcountync.gov/912/Legal-Notices`<br>`https://www.brunswickcountync.gov`<br>_+1 more_ |
| `counties_nc.buncombe_tax_foreclosure` | `https://www.trumba.com/calendars/tax-foreclosures-all.ics`<br>`https://taxforeclosures.buncombenc.gov/` |
| `counties_nc.gaston_surplus_properties` | `https://www.gastongov.com/709/Surplus-Properties`<br>`https://www.gastongov.com`<br>_+1 more_ |
| `counties_nc.henderson_tax` | `https://www.hendersoncountync.gov/tax/page/tax-foreclosure-sales` |
| `counties_nc.nc_coastal_tax_foreclosure` | `https://www.brunswickcountync.gov/912/Legal-Notices`<br>`https://www.brunswickcountync.gov`<br>_+4 more_ |
| `counties_nc.nc_ecourts_estates` | `https://portal-nc.tylertech.cloud/Portal/Home/Dashboard/29`<br>`https://portal-nc.tylertech.cloud/Portal`<br>_+1 more_ |
| `counties_nc.new_hanover_foreclosures` | `https://www.nhcgov.com/345/Foreclosures` |
| `counties_nc.polk_tax` | `https://www.polknc.gov/upcoming_auction.php` |
| `counties_nc.rutherford_wildfire_tax` | `https://www.rutherfordcountync.gov/tax_search/index.php`<br>`https://d1ebsyxxbc7tep.cloudfront.net`<br>_+1 more_ |
| `counties_sc.charleston_delinquent_tax` | `https://charlestoncounty.gov/departments/delinquent-tax/`<br>`https://www.charlestoncounty.gov/departments/delinquent-tax/files/RP-Tax-Sale-Listing.pdf`<br>_+1 more_ |
| `counties_sc.cherokee_delinquent_tax` | `https://cherokeecountysc.gov/delinquent-tax/`<br>`https://cherokeecountysc.gov/delinquent-tax/tax-sale-bidders/` |
| `counties_sc.colleton_tax_sale` | `https://www.colletoncounty.org/delinquent-tax`<br>`https://www.colletoncounty.org/delinquent-tax/tax-sale`<br>_+1 more_ |
| `counties_sc.greenville_tax_distress` | `https://www.gcgis.org/arcgis/rest/services/GreenvilleJS/Map_Layers_JS/MapServer`<br>`https://www.greenvillecounty.org/appsAS400/Taxsale/`<br>_+2 more_ |
| `counties_sc.oconee_tax_sale` | `https://docs.google.com/spreadsheets/d/e/{_PUB_ID`<br>`https://oconeesc.com/delinquent-tax/sale-list` |
| `counties_sc.pickens_tax_sale` | `https://www.co.pickens.sc.us/departments/delinquent_tax/index.php`<br>`https://www.co.pickens.sc.us/` |
| `counties_sc.sc_coastal_rosters` | _(no literal URL in module)_ |
| `counties_sc.sc_delinquent_tax_list` | `https://cherokeecountysc.gov/delinquent-tax/tax-sale-bidders/`<br>`https://cherokeecountysc.gov/wp-content/uploads/{year` |
| `counties_sc.sc_dew_lien_registry` | `https://uitax.dew.sc.gov/LienRegistry/`<br>`https://dew.sc.gov/benefit-lien-registry`<br>_+2 more_ |
| `counties_sc.sc_flc` | `https://www.spartanburgcounty.gov/216/Tax-Collector`<br>`https://www.andersoncountysc.org/departments-a-z/treasurer/`<br>_+6 more_ |
| `counties_sc.sc_probate_notices` | `https://{paper.host` |
| `counties_sc.sc_tax_delinquent` | `https://1543.newstogo.us/editionviewer/default.aspx?Edition=`<br>`https://www.andersoncountysc.org/departments-a-z/treasurer/`<br>_+11 more_ |
| `counties_sc.sc_ust_registry` | `https://apps.des.sc.gov/USTRegistry/` |
| `law_firms.alaw` | `https://www.alaw.net/foreclosure-sales/north-carolina/`<br>`https://www.alaw.net/foreclosure-sales/south-carolina/` |
| `law_firms.aldridge_pite` | `https://aldridgepite.com/sale-day-listings-selection/foreclosure-listings-north-carolina/`<br>`https://aldridgepite.com/disclaimer-north-carolina/` |
| `law_firms.finkel` | `https://www.finkellaw.com/images/Webs.pdf`<br>`https://www.finkellawcharleston.com/images/Webs.pdf` |
| `law_firms.ingle_firm` | `https://www.theinglefirm.com/Sales.aspx` |
| `law_firms.korn` | `https://www.kornlawfirm.com/foreclosure-sales/`<br>`https://www.kornlawfirm.com/sales/` |
| `law_firms.mewborn_deselms` | `https://www.mewbornlaw.biz` |
| `law_firms.zacchaeus` | `https://www.zls-nc.com/listings` |
| `national.bid4assets` | `https://www.bid4assets.com/storefront/index.cfm?searchstate=NC&searchprop=Real+Estate`<br>`https://www.bid4assets.com/storefront/index.cfm?searchstate=SC&searchprop=Real+Estate`<br>_+1 more_ |
| `national.craigslist_fsbo` | `https://{subdomain`<br>`https://{host` |
| `national.first_citizens_reo` | `https://www.firstcitizens.com/real-estate` |
| `national.gsa_realproperty` | `https://realestatesales.gov` |
| `national.landsofamerica` | `https://www.land.com/{county`<br>`https://www.land.com{url` |
| `national.probate_foreclosure_leads` | _(no literal URL in module)_ |
| `national.propwire` | _(no literal URL in module)_ |
| `newspapers.daily_courier` | `https://www.thedigitalcourier.com/classifieds/community/announcements/legal/`<br>`https://www.thedigitalcourier.com`<br>_+2 more_ |
| `newspapers.hendersonville_lightning` | `https://www.hendersonvillelightning.com/legal-ads/130-foreclosures.html` |
| `newspapers.index_journal` | `https://www.indexjournal.com/classifieds/community/announcements/legal/?f=rss` |
| `newspapers.post_and_courier` | `https://www.postandcourier.com/classifieds_new/community/announcements/` |
| `newspapers.shelby_star` | `https://www.shelbystar.com`<br>`https://www.shelbystar.com/`<br>_+4 more_ |
| `newspapers.tryon_bulletin` | `https://tryondailybulletin.com`<br>`https://tryondailybulletin.com/?s=foreclosure+sale`<br>_+3 more_ |
| `public_notices.funeral_home_rss` | `https://www.{host` |
| `public_notices.publicnoticesc` | _(no literal URL in module)_ |
| `reo.treasury_seized` | `https://www.treasury.gov/auctions/treasury/rp/realprop.shtml` |
| `reo.usda_rd` | `https://www.resales.usda.gov/resales/public`<br>`https://www.resales.usda.gov` |

## 3. Not built yet

Each of these survived an adversarial refutation pass whose DEFAULT was "refuted". A candidate only appears here if a verifier failed to kill it on every one of: already built, ToS/robots blocked, not a distress signal, duplicate of an existing source, upstream dead. 14 other doc-claimed candidates were killed by that pass and are deliberately absent.

### Greenville Journal MIE adverts

- **URL**: `https://mie.greenvillejournal.com/wp-sitemap-posts-advert-1.xml`
- **Counties**: Greenville SC
- **Signal**: foreclosure + JUDGMENT DEBT
- **Estimated volume**: ~722 notices 2016-2026, ~170/yr
- **Why / caveats**: The only free source found that carries total judgment debt keyed to a TMS. Only 27 of 47,125 board rows currently have a judgment amount. BLOCKED BY POLICY, NOT TECH: Greenville is in SCOPE_DENY_COUNTIES, so it ships zero leads until the operator widens the footprint.

### Senior / disabled exemption rolls beyond Buncombe

- **URL**: `county ArcGIS parcel layers carrying ELD/DIS/BLD/VET exemption codes`
- **Counties**: all footprint counties except Buncombe NC
- **Signal**: elderly_disabled
- **Estimated volume**: Buncombe alone yields 3,548
- **Why / caveats**: The elderly_disabled lane is 3,548 rows and 100% ONE county. The generic reader already exists in enrichment_gis_attrs.py and already runs against 17 counties returning zero, so this is pointing it at layers that carry the field, not 15 new scrapers. Caveat: 2,864 of the Buncombe 3,548 are cold single-signal, so it multiplies weak volume unless stacked.

### RealtyBid

- **URL**: `https://www.realtybid.com`
- **Counties**: NC + SC statewide
- **Signal**: reo / auction
- **Estimated volume**: unstated
- **Why / caveats**: Whole REO/auction lane is thin (311 reo + 69 auction rows). Two conflicting build profiles in the docs: one says clean ColdFusion pagination, three later probes say SPA with unmapped XHR. Effort M.

### Williams & Williams auctions

- **URL**: `https://www.williamsauction.com`
- **Counties**: NC + SC
- **Signal**: auction
- **Estimated volume**: unstated
- **Why / caveats**: Same thin REO/auction lane.

### Bank of America REO public JSON

- **URL**: `https://bankofamerica.reo.com`
- **Counties**: SC confirmed
- **Signal**: reo (bank-direct)
- **Estimated volume**: low volume
- **Why / caveats**: Bank-direct REO, no equivalent source built.

### Regional bank / CU REO: First Bank, Founders FCU, United Community Bank

- **URL**: `localfirstbank.com / foundersfcu.com / ucbi.com`
- **Counties**: NC + Upstate SC
- **Signal**: reo (owner-lead)
- **Estimated volume**: Founders ~9 properties
- **Why / caveats**: Small but these are owner-direct leads. UCBI currently empty.

### Burke parcel-history snapshots

- **URL**: `https://gis.burkenc.org/arcgis/rest/services/Hosted/Burke_Parcel_History_v3/FeatureServer`
- **Counties**: Burke NC
- **Signal**: ownership-change / structure-loss diffing
- **Estimated volume**: 11 annual layers over a 59,433-row CAMA base
- **Why / caveats**: VERIFIED LIVE 2026-08-06: service responds, layers 0-10 are '2025 Parcels' through '2015 Parcels'. Build as ENRICHMENT, not a lead scraper. Burke has 260 leads and its NCPTS delinquent tenant now returns zero blobs. NOTE the host is gis.burkenc.org, NOT the services3.arcgis.com URL the backlog recorded.

### Cherokee SC wp-json media search

- **URL**: `https://www.cherokeecountysc.gov/wp-json/wp/v2/media?search=tax%20sale`
- **Counties**: Cherokee SC
- **Signal**: tax_sale
- **Estimated volume**: 529-parcel 2024 ledger
- **Why / caveats**: Cherokee's tax cell is 1 lead. THIN: the only known ledger is the Nov-2024 sale, already past SC's 12-month redemption, so live yield may be 0.

### Transylvania CAD calls for service

- **URL**: `ArcGIS CAD_Calls_For_Service_Closed_view (exact URL NOT yet resolved)`
- **Counties**: Transylvania NC
- **Signal**: distress proxy
- **Estimated volume**: 305,856 geocoded calls
- **Why / caveats**: WEAK SIGNAL and the URL in the backlog is wrong: probing it on 2026-08-06 returned ArcGIS error 400 'Invalid URL'. Emergency-call volume is a proxy, not a distress event, and 305k rows would swamp the board. Build only as a scoring input, if at all.

## 4. Will not build, cannot build, not published

Summary only. The full forensic table lives in **`docs/blocked_sources_forensic.md`** (123 rows), with columns: Source | Category | Bypass that would work | Exact error/blocker | Why I didn't | Your manual step. That doc is the authority; this is the index.

### WONT

Compliance choice. A bypass exists and would work (CAPTCHA solver, login, paid API, subscriber wall) but riding it to sustain automation is off-limits. Fingerprinting stealth that runs the page's own JS is permitted; defeating a CAPTCHA, login, WAF bot-check or ToS scraper-prohibition is not.

- SC PublicIndex broad sweep (ToS prohibits automated/repetitive querying; Rule 610 is per-held-case)
- NC eCourts power-of-sale lane (real browser works; won't ride a human-solved CAPTCHA)
- Sites whose robots.txt names ClaudeBot / anthropic-ai / GPTBot: SeeClickFix (511 code cases), Transylvania Times TNCMS (2,301 notices)
- Kofile / Oconee ROD, Anderson ACPASS, Rutherford Sturgis+Avalon (all robots Disallow: /)
- landwatch / land.com (Akamai; its robots.txt itself 403s)

### CANT

Technical. 403 / dead / SPA with bot-protected backend / challenge-response, no free path found.

- NC eCourts Smart Search estates + divorce (AWS-WAF escalating image-grid CAPTCHA; the vision solver clears 2 puzzles and the WAF issues more)
- Cherokee SC delinquent tax (Cloudflare 403)
- Spartanburg / Laurens delinquent-tax URLs (404, CivicEngage migration)
- Union SC delinquent tax (DNS failure)
- SCDOT SC_Parcels (now token-walled, returns silent 200 + error)
- Transylvania TaxBillSearch (endpoint answers 200 with a ZERO-length body to every model shape, including bounded single-surname searches)
- PropWire (DataDome), mewborn_deselms (Cloudflare 403)

### ABSENT

The data is legally or structurally not published. Nobody, free or paid, extracts what does not exist.

- SC deed sale price on exempt deeds (SC 12-24-70 states no value)
- NC power-of-sale debt $ (notices legally state only terms/deposit/upset bid; the SP file dollar lives at the Clerk's office, not online)
- SC magistrate eviction rosters (portal exposes only Circuit roster types; magistrate courts are county-operated with no free bulk feed)
- Live mortgage payoff balance (servicer PII)
- SC Family Court divorce (separate access-restricted system, not on the public portal at all)

### DEAD

Decommissioned. Do not re-chase.

- homesales.gov (gone), US Marshals (403), IRS auctions (403), GSA /api/properties (302 to login), SBA REO (no portal exists)
- Gaston 'delinquent taxes' document (it is a library storytime flyer)
- Burke NCPTS delinquent tenant (valid tenant, now returns ZERO blobs)
- Aggregator dropdown probate for Cherokee/Oconee/Georgetown/Colleton (0 records; a dropdown is not data)

## 5. Checked and rejected (not a distress signal)

Investigated, found real and reachable, and deliberately NOT turned into leads. Recorded so they are not re-chased.

- **Burke County BurkeNC_2026_Billing.zip** (`https://www.burkenc.org/DocumentCenter/View/5147/BurkeNC_2026_BillingZIP`) — A print-image feed for the bill-printing vendor holding EVERY 2026 tax bill (56,536 REI + 9,095 IND + 3,330 BUS sampled), all tax year 2026, billed 07/01/2026 with a delinquency date of 01/06/2027 that has not arrived. No paid/unpaid flag, no prior-year balance. An apparent 'PAID' match is the phrase 'if paid' in the discount line. Being sent a tax bill is not distress. STILL USEFUL AS ENRICHMENT: owner name, owner mailing address, situs, parcel, assessed value and acreage for every Burke parcel.
- **Mitchell News-Journal legals** (`https://www.mitchellnews.com/classified/legals`) — Redundant. Mitchell NC probate is already carried by nc_notices_counties, ncpublicnotices and column_legal_notices, and the page held one notice.
- **Spartanburg tarp requests (2,096 rows)** (`(ArcGIS)`) — Deliberately not built. Disaster victims who requested aid. A business call, not a technical one.

---

### Related docs

- `docs/blocked_sources_forensic.md` — the full 123-row blocked/dead/manual forensic table.
- `docs/gap_ledger.md` — per-signal gap ledger, the do-not-re-chase list, and the discards with evidence.
- `docs/manual_playbook_and_limits.md` — what stays manual and the exact operator steps for each manual lane.
- `docs/net_new_source_register.md` — deep per-county URL register. **WARNING: physically truncated** — it begins mid-table-row and its sections 1.1 through 1.14 (all 11 NC counties) do not exist anywhere.

