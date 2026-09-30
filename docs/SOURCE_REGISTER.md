# MASTER SOURCE REGISTER

Generated 2026-09-28 09:05 UTC by `scripts/gen_source_register.py`. **Re-run it instead of editing this file** — the built half is read from the live registry and the live board, so hand edits are overwritten and go stale.

**One row hand-added 2026-09-30** (`counties_sc.greenwood_corebtpay_delinquent_tax`,
in section 2 below) to keep `tests/test_source_docs_current.py` green without
re-running the generator — which streams the full live board into memory, and
this session was scoped to stay off the board entirely for memory-safety
reasons (two other agent sessions were active on an 8GB Mac; see the scraper's
own commit message). Re-run `scripts/gen_source_register.py` in a later session
to fold this back into a real regeneration; the counts below include the hand-add.

- Scrapers in the registry: **236**
- Producing rows on the board: **129**
- Registered but contributing ZERO rows: **107**
- Confirmed real and not yet built: **3**
- Board read: `data/checkpoint/board.json.gz` (197,890 rows)

Sections: [1 Built and producing](#1-built-and-producing) · [2 Built but zero rows](#2-built-but-producing-zero-rows) · [3 Not built yet](#3-not-built-yet) · [4 Will not / cannot build](#4-will-not-build-cannot-build-not-published) · [5 Checked and rejected](#5-checked-and-rejected-not-a-distress-signal)

---

## 1. Built and producing

Live row counts are what the source actually contributed to the board read above, not a capacity estimate.

| Slug | Rows | Top counties | URLs in the module |
|---|---:|---|---|
| `counties_sc.qpaybill_delinquent_roll` | 30,329 | Spartanburg SC (3209), Sumter SC (3074), Darlington SC (2505) | `https://dilloncountysctaxes.qpaybill.com/Taxes/`<br>`https://edgefieldcountysc.qpaybill.com/`<br>`https://{sub` |
| `counties_sc.sc_dew_lien_registry` | 8,475 | Charleston SC (3328), Horry SC (1688), Spartanburg SC (1106) | `https://uitax.dew.sc.gov/LienRegistry/`<br>`https://dew.sc.gov/benefit-lien-registry`<br>`https://uitax.dew.sc.gov/CoreServices/Lien/TaxLienRegistry.svc/SearchTaxLienRegistry`<br>_+1 more_ |
| `counties_nc.nc_ptscloud_delinquent_tax` | 7,604 | Forsyth NC (4655), Orange NC (1231), Henderson NC (1180) | `https://bcpwa.ncptscloud.com` |
| `counties_nc.gaston_vacant` | 7,142 | Gaston NC (7142) | `https://gis.gastoncountync.gov/publicgis/rest/services/` |
| `counties_nc.rutherford_tax` | 6,725 | Rutherford NC (6725) | `https://www.rutherfordcountync.gov/`<br>`https://www.rutherfordcountync.gov/departments/` |
| `counties_nc.transylvania_vacant` | 5,319 | Transylvania NC (5319) | `https://gis.transylvaniacounty.org/server/rest/services/Parcels/FeatureServer/2/query` |
| `counties_sc.horry_delinquent_xlsx` | 4,949 | Horry SC (4949) | `https://www.horrycountysc.gov/media/b5af14ce/delinquent-list-on-website-081926.xlsx`<br>`https://www.horrycountysc.gov/departments/treasurer/delinquent-tax/` |
| `counties_sc.sc_public_index` | 4,896 | Spartanburg SC (1008), Anderson SC (888), Laurens SC (816) | `https://publicindex.sccourts.org/`<br>`https://publicindex.sccourts.org/{county` |
| `national.courtlistener_bankruptcy` | 4,717 | Buncombe NC (60), Henderson NC (47), Anderson SC (36) | `https://www.courtlistener.com/sign-up/`<br>`https://www.courtlistener.com/profile/api/`<br>`https://www.courtlistener.com/api/rest/v4`<br>_+1 more_ |
| `counties_nc.buncombe_elderly` | 3,894 | Buncombe NC (3894) | `https://gis.buncombecounty.org/arcgis/rest/services/property_bc_dis/MapServer/1/query` |
| `city_websites.charlotte_open_data` | 3,521 | Mecklenburg NC (3521) | `https://gis.charlottenc.gov/arcgis/rest/services/HNS/CodeEnforcementCasesAll/MapServer/0`<br>`https://gis.charlottenc.gov/arcgis/rest/services/HNS/`<br>`https://gis.charlottenc.gov/arcgis/rest/services/HNS/CodeEnforcementCasesAll/MapServer/0/{case_num` |
| `counties_sc.spartanburg_vacant` | 3,479 | Spartanburg SC (3479) | `https://services9.arcgis.com/HoRra3ATPLGmyjn6/arcgis/rest/services/`<br>`https://services9.arcgis.com/HoRra3ATPLGmyjn6/` |
| `counties_sc.sc_ust_registry` | 2,774 | Spartanburg SC (971), Anderson SC (660), Pickens SC (332) | `https://apps.des.sc.gov/USTRegistry/` |
| `counties_nc.nc_county_pdf_delinquent_tax` | 2,450 | McDowell NC (1763), Lincoln NC (455), Catawba NC (228) | `https://www.lincolncountync.gov/DocumentCenter/View/25558/2025-TAXESDelinquentAdvertisementNotice`<br>`https://www.catawbacountync.gov/site/assets/files/11653/delinquent_advertisement_list-hdr_2026.pdf`<br>`https://mcdowellnc.gov/departments/tax-collections/tax-lien-advertisement/ADVERTISEMENT-LIST-FINAL-2025.pdf` |
| `counties_sc.berkeley_paystar_tax` | 2,336 | Berkeley SC (2336) | `https://berkeleycountysc.paystar.io/api/search`<br>`https://berkeleycountysc.paystar.io/api/invoices/{invoiceNumberHash`<br>`https://berkeleycountysc.paystar.io` |
| `counties_sc.charleston_tax_sale_xlsx` | 2,210 | Charleston SC (2210) | `https://www.charlestoncounty.gov/departments/delinquent-tax/files/tax_sale/RP-Tax-Sale-Listing.xlsx`<br>`https://www.charlestoncounty.gov/departments/delinquent-tax/files/tax_sale/MH-Tax-Sale-Listing.xlsx`<br>`https://www.charlestoncounty.gov/departments/delinquent-tax/` |
| `counties_nc.lincoln_vacant` | 2,118 | Lincoln NC (2117), Cleveland NC (1) | `https://arcgisserver.lincolncounty.org/arcgis/rest/services/ComDevData/MapServer/25/query` |
| `counties_sc.greenville_delinquent_tax` | 2,108 | Greenville SC (2108) | `https://www.greenvillecounty.org/appsAS400/Taxsale/` |
| `counties_sc.pickens_delinquent_parcels` | 2,070 | Pickens SC (2070) | `https://services1.arcgis.com/59960rq18IxUcAVI/arcgis/rest/services`<br>`https://www.co.pickens.sc.us/departments/delinquent_tax/index.php` |
| `counties_sc.florence_delinquent_tax` | 1,988 | Florence SC (1988) | `https://www.florenceco.org/offices/delinquent-tax/` |
| `counties_sc.spartanburg_delinquent_tax` | 1,986 | Spartanburg SC (1986) | `https://www.spartanburgcounty.gov/DocumentCenter/View/11161/Real-Property-Tax-Sale-List-PDF`<br>`https://www.spartanburgcounty.gov/DocumentCenter/View/11161/`<br>`https://www.spartanburgcounty.gov/640/2025-Tax-Sale-Info` |
| `counties_sc.spartanburg_condemned` | 1,768 | Spartanburg SC (1768) | `https://maps.spartanburgcounty.org/server/rest/services/` |
| `counties_nc.albemarle_observer_tax_lists` | 1,756 | Bertie NC (1076), Gates NC (409), Tyrrell NC (270) | `https://albemarleobserver.news/wp-json/wp/v2/posts?search=delinquent&per_page=50`<br>`https://albemarleobserver.news/wp-json/wp/v2/posts/`<br>`https://albemarleobserver.news/wp-json/wp/v2/posts` |
| `counties_nc.nc_county_csv_delinquent_tax` | 1,321 | New Hanover NC (1321) | `https://www.nhcgov.com/DocumentCenter/View/11283/Delinquent_Taxpayers_Report_CSV` |
| `national.hud_reac_inspection` | 1,260 | Mecklenburg NC (134), Richland SC (83), Wake NC (82) | `https://www.hud.gov/sites/default/files/Housing/documents/MF-Inspection-Report.xls```<br>`https://www.hud.gov/sites/default/files/Housing/documents/`<br>`https://www.hud.gov/stat/mfh/inspection-scores` |
| `counties_sc.charleston_delinquent_tax` | 1,217 | Charleston SC (1217) | `https://charlestoncounty.gov/departments/delinquent-tax/`<br>`https://www.charlestoncounty.gov/departments/delinquent-tax/files/RP-Tax-Sale-Listing.pdf`<br>`https://www.charlestoncounty.gov/departments/delinquent-tax/files/MH-Tax-Sale-Listing.pdf` |
| `public_notices.nc_notices_counties` | 925 | Buncombe NC (242), Gaston NC (121), Brunswick NC (83) | `https://www.ncnotices.com/Search.aspx`<br>`https://www.ncnotices.com/Details.aspx?ID={` |
| `counties_sc.dorchester_billtrax_delinquent_tax` | 897 | Dorchester SC (897) | `https://dorchestercountyscdelinquenttaxapi.billtrax.com`<br>`https://dorchestercountyscdelinquenttax.billtrax.com/` |
| `national.fannie_homepath` | 874 | Spartanburg SC (343), Laurens SC (122), Anderson SC (100) | `https://homepath.fanniemae.com/cfl/property-inventory/search`<br>`https://homepath.fanniemae.com/`<br>`https://homepath.fanniemae.com/property/{uuid` |
| `counties_nc.buncombe_delinquent_tax` | 828 | Buncombe NC (828) | `https://media.buncombenc.gov/common/tax/buncombe-county-tax-department-advertisement-of-tax-liens.pdf`<br>`https://media.buncombenc.gov/common/tax/` |
| `counties_sc.sc_public_notices` | 824 | Cherokee SC (142), Charleston SC (135), Pickens SC (128) | `https://www.scpublicnotices.com/Search.aspx`<br>`https://www.scpublicnotices.com/Details.aspx?ID={n[` |
| `counties_sc.dillon_delinquent_tax` | 822 | Dillon SC (822) | `https://www.dilloncountysc.org/departments/treasurer.php`<br>`https://www.dilloncountysc.org/` |
| `counties_sc.greenville_tax_distress` | 766 | Greenville SC (766) | `https://www.gcgis.org/arcgis3/rest/services/GreenvilleNJ/QueryLayers/MapServer`<br>`https://www.greenvillecounty.org/appsAS400/Taxsale/`<br>`https://www.greenvillecounty.org/appsAS400/Probate/`<br>_+1 more_ |
| `counties_nc.nc_ecourts_lis_pendens` | 757 | Brunswick NC (145), New Hanover NC (89), Onslow NC (84) | `https://portal-nc.tylertech.cloud/app/NCJudgmentSearch/`<br>`https://portal-nc.tylertech.cloud/app/NCJudgmentSearchService/search`<br>`https://portal-nc.tylertech.cloud` |
| `counties_nc.nc_heir_estate_parcels` | 672 | Rutherford NC (146), Polk NC (93), Laurens SC (66) | _(no literal URL in module)_ |
| `national.usda_properties` | 662 | Anderson SC (118), Laurens SC (113), Pickens SC (110) | `https://usdaproperties.com/property/`<br>`https://www.usdaproperties.com/property/sc/county/`<br>`https://www.usdaproperties.com`<br>_+1 more_ |
| `counties_sc.oconee_flc_assignment` | 585 | Oconee SC (585) | `https://services1.arcgis.com/UOvRn2Rvzysthh3i/arcgis/rest/services/`<br>`https://oconeesc.com/auditor-home/forfeited-land` |
| `counties_nc.asheville_str_permits` | 583 | Buncombe NC (583) | `https://gis.ashevillenc.gov/server/rest/services/Permits/`<br>`https://gis.ashevillenc.gov/server/rest/services/Permits/HomestayPermitsView/MapServer/5` |
| `national.landandfarm` | 562 | Polk NC (44), Henderson NC (43), Gaston NC (41) | `https://www.landandfarm.com/search/{state_slug` |
| `counties_nc.nc_its_public_tax` | 530 | Graham NC (511), Onslow NC (19) | `https://tax.onslowcountync.gov/ITSPublicON/TaxBillSearch`<br>`https://www.bttaxpayerportal.com/ITSPublicGR2.0/TaxBillSearch`<br>`https://tax.onslowcountync.gov/ITSPublicON`<br>_+1 more_ |
| `counties_sc.cherokee_delinquent_tax` | 528 | Cherokee SC (528) | `https://www.cherokeecountysc.gov/wp-json/wp/v2/media` |
| `national.landwatch` | 488 | Burke NC (46), Brunswick NC (37), Pender NC (35) | `https://www.landwatch.com/{state_slug` |
| `counties_sc.oconee_forfeited_land` | 451 | Oconee SC (451) | `https://services1.arcgis.com/UOvRn2Rvzysthh3i/arcgis/rest/services/`<br>`https://oconeesc.com/auditor-home/forfeited-land` |
| `counties.multi_year_delinquent_tax` | 418 | Buncombe NC (366), Oconee SC (49), Pickens SC (3) | `https://services6.arcgis.com/VLA0ImJ33zhtGEaP/arcgis/rest/services`<br>`https://services1.arcgis.com/UOvRn2Rvzysthh3i/arcgis/rest/services`<br>`https://services1.arcgis.com/59960rq18IxUcAVI/arcgis/rest/services`<br>_+3 more_ |
| `counties_sc.georgetown_civicengage` | 397 | Georgetown SC (397) | `https://www.gtcountysc.gov` |
| `counties_nc.rutherford_wildfire_tax` | 367 | Rutherford NC (367) | `https://www.rutherfordcountync.gov/tax_search/index.php`<br>`https://d1ebsyxxbc7tep.cloudfront.net`<br>`https://{m.group(1` |
| `counties_nc.transylvania_delinquent_tax` | 336 | Transylvania NC (335), Henderson NC (1) | `https://tax.transylvaniacounty.org/TaxBillSearch`<br>`https://tax.transylvaniacounty.org` |
| `counties_sc.sc_public_index_lis_pendens` | 325 | Anderson SC (126), Spartanburg SC (95), Laurens SC (27) | `https://publicindex.sccourts.org/`<br>`https://publicindex.sccourts.org/{county` |
| `counties_nc.nc_ecourts_divorce` | 304 | Buncombe NC (48), New Hanover NC (43), Gaston NC (40) | `https://portal-nc.tylertech.cloud/Portal/Home/Dashboard/29`<br>`https://portal-nc.tylertech.cloud/Portal`<br>`https://portal-nc.tylertech.cloud` |
| `counties_nc.mcdowell_probate` | 297 | McDowell NC (297) | `https://services9.arcgis.com/ETP7IuCigkUz7iI9/arcgis/rest/services/` |
| `counties_sc.terry_howe_auctions` | 293 | Laurens SC (118), Spartanburg SC (109), Anderson SC (34) | `https://terryhowe.com/wp-json/wp/v2/auctions` |
| `counties_sc.greenville_mie_adverts` | 285 | Greenville SC (285) | `https://mie.greenvillejournal.com` |
| `national.distressed` | 283 | Gaston NC (41), Anderson SC (34), Henderson NC (33) | _(no literal URL in module)_ |
| `counties_sc.sc_probate_net` | 280 | Charleston SC (280) | `https://www.southcarolinaprobate.net/search/```<br>`https://www.southcarolinaprobate.net/search/` |
| `national.craigslist_fsbo` | 261 | - | `https://sapi.craigslist.org/web/v8/postings/search/full`<br>`https://{host` |
| `national.courtlistener_adversary` | 255 | Macon NC (1), Wilson NC (1), Catawba NC (1) | `https://www.courtlistener.com` |
| `national.hud_section8_contracts` | 244 | Gaston NC (26), Spartanburg SC (26), Charleston SC (19) | `https://www.hud.gov/hud-partners/multifamily-assist-section8-database`<br>`https://www.hud.gov/sites/dfiles/Housing/documents/`<br>`https://www.hud.gov/hud-partners/` |
| `public_notices.gannett_obituaries` | 226 | Buncombe NC (47), Spartanburg SC (45), Anderson SC (38) | `https://www.{host` |
| `counties_sc.sc_rod_acclaim` | 192 | Pickens SC (192) | _(no literal URL in module)_ |
| `national.zillow_foreclosures` | 186 | Onslow NC (19), Horry SC (14), Gaston NC (8) | `https://www.zillow.com/{state.lower(` |
| `counties_nc.henderson_code_violations` | 182 | Henderson NC (182) | `https://services1.arcgis.com/ZfV5vUaX5QvLLBi9/arcgis/rest/services/`<br>`https://www.hendersoncountync.gov/planning` |
| `national.foreclosure_dot_com` | 170 | Buncombe NC (66), Anderson SC (48), Spartanburg SC (18) | `https://www.foreclosure.com/listing/search?q=North%20Carolina&pa=100000&view=list`<br>`https://www.foreclosure.com/listing/search?q=South%20Carolina&pa=100000&view=list`<br>`https://www.foreclosure.com/listings/charlotte-nc/`<br>_+35 more_ |
| `counties.column_legal_notices` | 140 | Marlboro SC (39), Marion SC (32), McDowell NC (25) | `https://us-central1-enotice-production.cloudfunctions.net/api/search/public-notices`<br>`https://us-central1-enotice-production.cloudfunctions.net` |
| `counties_sc.spartan_weekly_legals` | 112 | Spartanburg SC (112) | `https://www.spartanweeklyonline.com` |
| `counties_sc.york_overage_claims` | 107 | York SC (107) | `https://www.yorkcountysc.gov/DocumentCenter/View/2828/OVERAGE-CLAIM-LIST` |
| `counties_nc.asheville_helene` | 102 | Buncombe NC (102) | `https://services.arcgis.com/aJ16ENn1AaqdFlqx/arcgis/rest/services/` |
| `counties_sc.spartanburg_city_condemned` | 91 | Spartanburg SC (91) | `https://www.cityofspartanburg.org/robots.txt`<br>`https://www.cityofspartanburg.org/DocumentCenter/View/1901/`<br>`https://www.cityofspartanburg.org/` |
| `counties_sc.sc_state_tax_lien` | 82 | Horry SC (15), Berkeley SC (9), Lexington SC (8) | `https://mydorway.dor.sc.gov/?link=delinquentind`<br>`https://dor.sc.gov/delinquent-taxpayers` |
| `law_firms.shapiro_ingle_powerbi` | 74 | Gaston NC (23), Buncombe NC (17), Cleveland NC (11) | `https://www.logs.com/nc-upcoming-sales-report.html`<br>`https://app.powerbi.com/view?r=`<br>`https://wabi-us-north-central-h-primary-api.analysis.windows.net`<br>_+2 more_ |
| `counties_sc.sc_flc` | 73 | Anderson SC (73) | `https://www.spartanburgcounty.gov/216/Tax-Collector`<br>`https://www.andersoncountysc.org/departments-a-z/treasurer/`<br>`https://www.pickenscountysc.gov/treasurer/tax-sale`<br>_+6 more_ |
| `counties_sc.sc_des_brownfields` | 64 | Statewide SC (64) | `https://des.sc.gov/programs/bureau-land-waste-management/`<br>`https://des.sc.gov/community/environmental-sites-projects` |
| `law_firms.hutchens` | 59 | Spartanburg SC (14), Gaston NC (6), Cherokee SC (6) | `https://sales.hutchenslawfirm.com/NCfcSalesList.aspx`<br>`https://sales.hutchenslawfirm.com/SCfcSalesList.aspx` |
| `law_firms.zacchaeus` | 59 | Guilford NC (8), Cabarrus NC (8), Robeson NC (7) | `https://www.zls-nc.com/listings` |
| `national.auction_dot_com` | 57 | Anderson SC (7), Spartanburg SC (6), McDowell NC (2) | `https://www.auction.com/residential/nc/`<br>`https://www.auction.com/residential/sc/`<br>`https://www.auction.com/details/{slug` |
| `national.estate_sales` | 57 | Cleveland NC (11), Buncombe NC (8), Mecklenburg NC (8) | `https://www.estatesales.net`<br>`https://www.estatesale.com`<br>`https://{host` |
| `national.zillow_bulk` | 55 | Spartanburg SC (2), Gaston NC (1), Greenville SC (1) | `https://www.zillow.com/{state.lower(` |
| `public_notices.funeral_home_rss` | 54 | Anderson SC (21), Cleveland NC (20), Buncombe NC (13) | `https://www.{host` |
| `counties_nc.hendersonville_vacant_structures` | 47 | Henderson NC (47) | `https://services1.arcgis.com/UTZTmZoX2rsa9yFA/arcgis/rest/services/`<br>`https://www.hvlnc.gov/community-development` |
| `counties_sc.terry_howe_flc` | 44 | Chester SC (18), Laurens SC (14), Spartanburg SC (6) | `https://terryhowe.com/wp-json/wp/v2/auctions?per_page=100&_fields=id,title,link,content` |
| `law_firms.kania` | 44 | Burke NC (19), Rutherford NC (11), Cleveland NC (8) | `https://kanialawfirm.com/tax-foreclosures/foreclosure-listings/`<br>`https://kanialawfirm.com/wp-admin/admin-ajax.php` |
| `counties_sc.sc_tax_delinquent` | 42 | Pickens SC (42) | `https://1543.newstogo.us/editionviewer/default.aspx?Edition=`<br>`https://www.andersoncountysc.org/departments-a-z/treasurer/`<br>`https://www.spartanburgcounty.gov/640/2025-Tax-Sale-Info`<br>_+10 more_ |
| `national.cash_buyer_deeds` | 42 | McDowell NC (40), Burke NC (2) | `https://{host` |
| `public_notices.ncnotices` | 41 | Buncombe NC (28), Polk NC (5), Mecklenburg NC (4) | `https://www.ncnotices.com/`<br>`https://www.ncnotices.com{raw_href` |
| `national.sc_public_index` | 37 | Charleston SC (37) | `https://publicindex.sccourts.org/`<br>`https://publicindex.sccourts.org/{county`<br>`https://jcmsweb.charlestoncounty.org/PublicIndex/`<br>_+1 more_ |
| `national.servicelink_auction` | 28 | Spartanburg SC (6), Anderson SC (5), Buncombe NC (4) | `https://ui.exostechnology.com/api/listingsvc/v1/listings?limit=100&state={ST`<br>`https://ui.exostechnology.com/api/listingsvc/v1/listings`<br>`https://www.servicelinkauction.com`<br>_+1 more_ |
| `counties_sc.charleston_mie` | 27 | Charleston SC (27) | `https://charlestoncounty.gov/foreclosure/runninglist.html`<br>`https://charlestoncounty.gov/departments/master-in-equity/rosters/` |
| `law_firms.brock_scott` | 27 | Spartanburg SC (15), Oconee SC (2), Pickens SC (2) | `https://www.brockandscott.com/foreclosure-sales/` |
| `counties_nc.buncombe_tax` | 21 | Buncombe NC (21) | `https://www.trumba.com/calendars/tax-foreclosures-all.json`<br>`https://taxforeclosures.buncombenc.gov/` |
| `national.nc_upset_bids` | 21 | Rutherford NC (21) | `https://kanialawfirm.com/tax-foreclosures/foreclosure-listings/`<br>`https://kanialawfirm.com/wp-admin/admin-ajax.php`<br>`https://www.rutherfordcountync.gov/departments/` |
| `national.fema_disasters` | 20 | Brunswick NC (2), Swain NC (2), Transylvania NC (2) | `https://www.fema.gov/api/open/v2/DisasterDeclarationsSummaries`<br>`https://www.fema.gov/disaster/{row.get(` |
| `national.xome` | 18 | Anderson SC (3), Laurens SC (2), Spartanburg SC (2) | `https://www.xome.com/auctions/bank-owned`<br>`https://www.xome.com/auctions/foreclosure-homes`<br>`https://www.xome.com/auctions/foreclosuresales`<br>_+1 more_ |
| `counties_nc.edgecombe_tax_foreclosure` | 17 | Edgecombe NC (17) | `https://www.edgecombecountync.gov/businesses/tax_collector/tax_foreclosure_list.php` |
| `national.trulia` | 17 | Spartanburg SC (10) | `https://www.trulia.com/foreclosures/`<br>`https://www.trulia.com/foreclosures/Charlotte,NC/`<br>`https://www.trulia.com/foreclosures/Raleigh,NC/`<br>_+6 more_ |
| `counties_sc.pickens_master_in_equity` | 16 | Pickens SC (16) | `https://www.co.pickens.sc.us/departments/master_in_equity/sales_rosters.php`<br>`https://www.co.pickens.sc.us/` |
| `counties_sc.anderson_master_in_equity` | 14 | Anderson SC (14) | `https://www.andersoncountysc.org/departments-a-z/master-in-equity/`<br>`https://www.andersoncountysc.org{href` |
| `national.hubzu` | 14 | Spartanburg SC (5), Laurens SC (2), Transylvania NC (1) | `https://www.hubzu.com/portal/auctions?state={state`<br>`https://www.hubzu.com/`<br>`https://www.hubzu.com{url` |
| `law_firms.bell_carrington` | 11 | Spartanburg SC (6), Pickens SC (3), Cherokee SC (1) | `https://docs.google.com/spreadsheets/d/e/`<br>`https://bellcarrington.com/foreclosure-sales/` |
| `newspapers.aiken_standard` | 11 | Aiken SC (11) | `https://www.postandcourier.com/aikenstandard/classifieds/search/` |
| `counties_nc.henderson_foreclosure_parcels` | 10 | Henderson NC (10) | `https://www.arcgis.com`<br>`https://hendersoncounty.maps.arcgis.com`<br>`https://experience.arcgis.com/experience/` |
| `national.jail_bookings` | 10 | Anderson SC (2), Buncombe NC (1), Cleveland NC (1) | `http://mugshots.spartanburgsheriff.org/`<br>`https://buncombecountyso.policetocitizen.com|23`<br>`http://74.218.167.200/p2c`<br>_+10 more_ |
| `newspapers.berkeley_independent` | 9 | Berkeley SC (9) | `https://www.postandcourier.com/berkeley-independent/classifieds/community/announcements/` |
| `law_firms.mcmichael_taylor_gray` | 6 | Spartanburg SC (2), Gaston NC (1), Cherokee SC (1) | `https://app.powerbi.com/view?r=eyJrIjoiOTQwOTdiYWYtOGQwMy00OGUzLWI4MjktOTczNDc0ODE2ZGY1IiwidCI6IjEzZDFlNzhjLTgyNDgtNGVlYS04OWY3LWQzNGIzZWJkOGM3OSIsImMiOjN9`<br>`https://app.powerbi.com/view?r=eyJrIjoiOTQwOTdiYWYtOGQwMy00OGUzLWI4MjktOTczNDc0ODE2ZGY1Ii` |
| `law_firms.rogers_townsend` | 6 | Spartanburg SC (4), Oconee SC (1), Anderson SC (1) | `https://rogerstownsend.com/reports/SC_Listings.pdf`<br>`https://rogerstownsend.com/reports/NC_Listings.pdf` |
| `counties_nc.nc_county_tax_foreclosure` | 5 | Rutherford NC (3), Gaston NC (2) | `https://www.gastongov.com/669/Tax-Foreclosure-Sales`<br>`https://www.gastongov.com/671/Previous-Tax-Foreclosure-Sales`<br>`https://mcdowellnc.gov/departments/tax-collections/tax-foreclosures/upcoming-tax-foreclosure-sales`<br>_+1 more_ |
| `national.homeharvest` | 5 | Burke NC (3), Anderson SC (2) | `https://github.com/ZacharyHampton/HomeHarvest` |
| `national.realtor_foreclosures` | 5 | Spartanburg SC (3), Buncombe NC (1), Catawba NC (1) | _(no literal URL in module)_ |
| `reo.vrm_va_reo` | 5 | Spartanburg SC (2), Gaston NC (1), Laurens SC (1) | `https://vrmproperties.com/`<br>`https://vrmproperties.com` |
| `counties_nc.nc_coastal_tax_foreclosure` | 4 | Brunswick NC (4) | `https://www.brunswickcountync.gov/912/Legal-Notices`<br>`https://www.brunswickcountync.gov`<br>`https://www.onslowcountync.gov/DocumentCenter/View/6521/FORECLOSURE-SALES`<br>_+4 more_ |
| `counties_nc.nc_rod_logan` | 4 | Transylvania NC (3), McDowell NC (1) | _(no literal URL in module)_ |
| `counties_sc.spartanburg_flc` | 4 | Spartanburg SC (4) | `https://www.spartanburgcounty.gov/DocumentCenter/View/104130` |
| `national.hud_homestore` | 4 | Gaston NC (2), Lincoln NC (1), Oconee SC (1) | `https://www.hudhomestore.gov/searchresult?handler=GetFilteredResult`<br>`https://www.hudhomestore.gov` |
| `newspapers.journal_scene` | 4 | Dorchester SC (4) | `https://www.postandcourier.com/journal-scene/classifieds/community/announcements/` |
| `counties.nod_discovery` | 3 | Cleveland NC (2), Buncombe NC (1) | `https://{host`<br>`https://{kofile.KOFILE_COUNTIES[(state`<br>`https://example.invalid/` |
| `counties_nc.cleveland_tax` | 3 | Cleveland NC (3) | `https://www.clevelandcounty.com/main/departments/` |
| `counties_nc.wake_tax_foreclosure` | 3 | Wake NC (3) | `https://www.wake.gov/departments-government/tax-administration/real-estate/foreclosures`<br>`https://services.wake.gov/realestate/Account.asp?id={tax_id` |
| `counties_sc.horry_flc` | 3 | Horry SC (3) | `https://www.horrycountysc.gov/boards-and-commissions/`<br>`https://www.horrycountysc.gov/media/om1d2bwo/2025-flc-list-42126.xlsx`<br>`https://www.horrycountysc.gov` |
| `counties_sc.richland_flc` | 3 | Richland SC (3) | `https://www.richlandcountysc.gov/Property-Business/Taxes/Delinquent-Taxes/Forfeited-Land-Available`<br>`https://www.richlandcountysc.gov` |
| `counties_sc.sc_county_rosters` | 3 | Oconee SC (2), Laurens SC (1) | `https://publicindex.sccourts.org` |
| `national.freddie_homesteps` | 3 | - | `https://www.homesteps.com/listing/search?search=NC`<br>`https://www.homesteps.com/listing/search?search=SC`<br>`https://www.homesteps.com/`<br>_+1 more_ |
| `national.courtlistener_civil` | 2 | - | `https://www.courtlistener.com` |
| `national.hibid_real_estate` | 2 | Lincoln NC (1) | `https://hibid.com/graphql```<br>`https://hibid.com/graphql`<br>`https://hibid.com`<br>_+2 more_ |
| `national.sheriff_sales` | 2 | Cleveland NC (2) | `https://www.brunswicksheriff.com`<br>`https://www.charlestoncounty.org`<br>`https://www.sheriffclevelandcounty.com`<br>_+1 more_ |
| `counties_nc.haywood_tax_foreclosures` | 1 | Haywood NC (1) | `https://www.haywoodcountync.gov/337/Tax-Foreclosures`<br>`https://www.haywoodcountync.gov/Bids.aspx` |
| `counties_sc.sc_rod_cott` | 1 | Union SC (1) | _(no literal URL in module)_ |
| `counties_sc.spartanburg_master_in_equity` | 1 | Spartanburg SC (1) | `https://www.spartanburgcounty.gov/DocumentCenter/View/3392/Sale-Results`<br>`https://www.spartanburgcounty.gov/DocumentCenter/View/11824/Deficiency-Sale` |
| `law_firms.ingle_firm` | 1 | Gaston NC (1) | `https://www.theinglefirm.com/Sales.aspx` |
| `national.gsa_surplus` | 1 | - | `https://www.gsa.gov/real-estate/real-property-disposition/assets-identified-for-accelerated-disposition`<br>`https://www.gsa.gov/real-estate/real-property-disposition/` |
| `newspapers.daily_courier` | 1 | Rutherford NC (1) | `https://www.thedigitalcourier.com/classifieds/community/announcements/legal/`<br>`https://www.thedigitalcourier.com` |
| `newspapers.index_journal` | 1 | Greenwood SC (1) | `https://www.indexjournal.com/classifieds/community/announcements/legal/?f=rss` |

## 2. Built but producing zero rows

Registered and importable, contributing nothing to the board read above. A zero here is NOT automatically a bug: it can mean the upstream is genuinely empty right now, the source is seasonal, it is gated off, it is blocked (see section 4), or it simply was not in the last run's source list.

| Slug | URLs in the module |
|---|---|
| `city_websites.asheville_min_housing` | `https://www.ashevillenc.gov/department/development-services/minimum-housing/` |
| `city_websites.search` | `https://{domain` |
| `counties.sitemap_walker` | `https://www.spartanburgcounty.gov`<br>`https://www.cherokeecountysc.gov`<br>_+10 more_ |
| `counties_generic.arcgis_distress_layers` | `https://services6.arcgis.com/VLA0ImJ33zhtGEaP/arcgis/rest/services/`<br>`https://www.buncombecounty.org/governing/depts/tax/`<br>_+32 more_ |
| `counties_generic.epa_frs_sites` | `https://data.epa.gov/dmapservice/frs.frs_program_facility`<br>`https://www.epa.gov/frs` |
| `counties_generic.state_contamination` | `https://services2.arcgis.com/kCu40SDxsCGcuUWO/arcgis/rest/services`<br>`https://www.deq.nc.gov/about/divisions/waste-management/underground-storage-tanks`<br>_+2 more_ |
| `counties_nc.brunswick_legal_notices` | `https://www.brunswickcountync.gov/912/Legal-Notices`<br>`https://www.brunswickcountync.gov`<br>_+1 more_ |
| `counties_nc.buncombe_tax_foreclosure` | `https://media.buncombenc.gov/common/tax/foreclosure-listings/fcl.pdf`<br>`https://taxforeclosures.buncombenc.gov/` |
| `counties_nc.cleveland_tax_foreclosure` | `https://www.clevelandcounty.com/main/departments/` |
| `counties_nc.cumberland_tax_foreclosure` | `https://www.co.cumberland.nc.us/departments/tax/tax-administration/tax-foreclosures` |
| `counties_nc.gaston_surplus_properties` | `https://www.gastongov.com/709/Surplus-Properties`<br>`https://www.gastongov.com`<br>_+1 more_ |
| `counties_nc.gaston_tax_foreclosures` | `https://www.gastongov.com/669`<br>`https://www.gastongov.com/671` |
| `counties_nc.henderson_tax` | `https://www.hendersoncountync.gov/tax/page/tax-foreclosure-sales` |
| `counties_nc.lincoln_code_violations` | `https://arcgisserver.lincolncountync.gov/arcgis/rest/services/` |
| `counties_nc.mcdowell_tax_foreclosure` | `https://mcdowellnc.gov/departments/tax-collections/` |
| `counties_nc.nc_bankruptcy_sales` | `https://www.nceb.uscourts.gov/Public-Sales-Notice`<br>`https://www.ncmb.uscourts.gov/public-sales` |
| `counties_nc.nc_civicplus_tax_sale` | `https://www.alamance-nc.com`<br>`https://www.alexandercountync.gov`<br>_+65 more_ |
| `counties_nc.nc_deq_dsca` | `https://www.deq.nc.gov/about/divisions/waste-management/science-data-and-reports/dsca-site-listsfacility-inventories` |
| `counties_nc.nc_ecourts_estates` | `https://portal-nc.tylertech.cloud/Portal/Home/Dashboard/29`<br>`https://portal-nc.tylertech.cloud/Portal`<br>_+1 more_ |
| `counties_nc.nc_govdeals_real_property` | `https://maestro.lqdt1.com/search/list`<br>`https://www.transylvaniacounty.org/news`<br>_+3 more_ |
| `counties_nc.nc_rod_substitute_trustee` | `https://buncombe-recordings.permitium.com/```<br>`https://www.nccourts.gov/` |
| `counties_nc.nchfa_reo` | `https://www.nchfa.com/home-buyers/properties-sale` |
| `counties_nc.new_hanover_foreclosures` | `https://www.nhcgov.com/345/Foreclosures` |
| `counties_nc.polk_tax` | `https://www.polknc.gov/upcoming_auction.php` |
| `counties_nc.rutherford_foreclosure` | `https://www.rutherfordcountync.gov/departments/` |
| `counties_nc.stokes_delinquent_tax` | `https://www.co.stokes.nc.us/departments/foreclosures.php` |
| `counties_nc.swain_tax_foreclosures` | `https://www.swaincountync.gov/` |
| `counties_nc.wnc_rod_foreclosure_starts` | _(no literal URL in module)_ |
| `counties_nc.wnc_tax_foreclosures` | `https://www.wataugacounty.org/`<br>`https://www.averycounty.com/`<br>_+3 more_ |
| `counties_sc.abbeville_delinquent_tax` | `https://abbevillecountysc.com/delinquent-tax-collector/` |
| `counties_sc.aiken_delinquent_tax` | `https://sc-aikencounty.civicplus.com/309/Tax-Foreclosures` |
| `counties_sc.anderson_sheriff` | `https://www.andersonsheriff.com/sheriff-sales` |
| `counties_sc.bamberg_sheriff` | `https://www.bambergcounty.sc.gov/public-safety/sheriffs-office` |
| `counties_sc.barnwell_sheriff` | `https://www.barnwellcounty.com/sheriff/sheriff-sales` |
| `counties_sc.beaufort_flc` | `https://www.proxibid.com/Meares-Property-Advisors-Inc/` |
| `counties_sc.cherokee_rod` | `https://www.sclandrecords.com` |
| `counties_sc.chester_delinquent_tax` | `https://www.chestercountysc.gov/treasurer/delinquent-tax-sale` |
| `counties_sc.clarendon_tax_auction` | `https://www.clarendoncountysc.gov/` |
| `counties_sc.colleton_tax_sale` | `https://www.colletoncounty.org/delinquent-tax`<br>`https://www.colletoncounty.org/delinquent-tax/tax-sale`<br>_+1 more_ |
| `counties_sc.darlington_delinquent_tax` | `https://www.darcosc.com/government/treasurer/index.php` |
| `counties_sc.dillon_sheriff` | `https://dilloncountysc.org/services/public_safety/sheriffs_office.php` |
| `counties_sc.edgefield_delinquent_tax` | `https://edgefieldcounty.sc.gov/treasurer/` |
| `counties_sc.fairfield_delinquent_tax` | `https://www.fairfieldsc.com/departments/treasurer` |
| `counties_sc.greenwood_corebtpay_delinquent_tax` | `https://greenwoodco.corebtpay.com/egov/apps/bill/pay.egov` |
| `counties_sc.greenwood_delinquent_tax` | `https://www.greenwoodcounty-sc.gov/treasurer/delinquent-tax-sale` |
| `counties_sc.kershaw_flc` | `https://www.kershaw.sc.gov/treasurer/forfeited-land-commission` |
| `counties_sc.lancaster_delinquent_tax` | `https://www.lancastercountysc.gov` |
| `counties_sc.laurens_delinquent_tax` | `https://www.laurenscountysc.gov/departments/treasurer/delinquent_taxes.php` |
| `counties_sc.lexington_flc` | `https://lex-co.sc.gov/treasurer/forfeited-land-commission`<br>`https://lex-co.sc.gov/departments/treasurer/forfeited-land-commission/`<br>_+2 more_ |
| `counties_sc.marlboro_delinquent_tax` | `https://www.marlborocounty.sc.gov/government_/meeting_publications.php` |
| `counties_sc.mccormick_flc` | `https://www.mccormickcountysc.org/departments/treasurer.php` |
| `counties_sc.meares_auctions` | `https://www.mpa-sc.com/```<br>`https://maps.google.com/?q=`<br>_+1 more_ |
| `counties_sc.newberry_delinquent_tax` | `https://www.newberrycounty.gov/delinquent-tax/tax-sales` |
| `counties_sc.oconee_flc` | `https://oconeesc.com/treasurer-home` |
| `counties_sc.oconee_tax_sale` | `https://docs.google.com/spreadsheets/d/e/{_PUB_ID`<br>`https://oconeesc.com/delinquent-tax/sale-list` |
| `counties_sc.pickens_tax_sale` | `https://www.co.pickens.sc.us/departments/delinquent_tax/index.php`<br>`https://www.co.pickens.sc.us/` |
| `counties_sc.saluda_delinquent_tax` | `https://saludacounty.sc.gov/departments/tax-collector/delinquent-tax-sale`<br>`https://saludacounty.sc.gov/departments/tax-collector` |
| `counties_sc.sc_catalis_delinquent_roll` | `https://d1ebsyxxbc7tep.cloudfront.net/data`<br>`https://pickenscountysctax.us`<br>_+4 more_ |
| `counties_sc.sc_coastal_rosters` | _(no literal URL in module)_ |
| `counties_sc.sc_delinquent_tax_list` | `https://cherokeecountysc.gov/delinquent-tax/tax-sale-bidders/`<br>`https://cherokeecountysc.gov/wp-content/uploads/{year` |
| `counties_sc.sc_dor_delinquent_taxpayers` | `https://mydorway.dor.sc.gov/?link=delinquentind` |
| `counties_sc.sc_probate_notices` | `https://{paper.host` |
| `counties_sc.sumter_surplus` | `https://www.sumtercountysc.gov/online_services/property/surplus_sales.php` |
| `counties_sc.union_delinquent_tax` | `https://gearupunionsc.com/officials/treasurer/` |
| `counties_sc.york_delinquent_tax` | `https://www.yorkcountysc.gov/216/Tax-Collection`<br>`https://www.yorkcountysc.gov{doc_url` |
| `counties_sc.zombie_properties` | _(no literal URL in module)_ |
| `law_firms.alaw` | `https://www.alaw.net/foreclosure-sales/north-carolina/`<br>`https://www.alaw.net/foreclosure-sales/south-carolina/` |
| `law_firms.aldridge_pite` | `https://aldridgepite.com/sale-day-listings-selection/foreclosure-listings-north-carolina/`<br>`https://aldridgepite.com/disclaimer-north-carolina/` |
| `law_firms.finkel` | `https://www.finkellaw.com/images/Webs.pdf`<br>`https://www.finkellawcharleston.com/images/Webs.pdf` |
| `law_firms.korn` | `https://www.kornlawfirm.com/foreclosure-sales/`<br>`https://www.kornlawfirm.com/sales/` |
| `law_firms.mewborn_deselms` | `https://www.mewbornlaw.biz` |
| `national.auction_bank_reo` | `https://apiweb.realtybid.com/rest/RBIAPI/`<br>`https://bid.auctionnetwork.com/Auctions`<br>_+2 more_ |
| `national.bid4assets` | `https://www.bid4assets.com/storefront/index.cfm?searchstate=NC&searchprop=Real+Estate`<br>`https://www.bid4assets.com/storefront/index.cfm?searchstate=SC&searchprop=Real+Estate`<br>_+1 more_ |
| `national.crexi_multifamily` | `https://www.crexi.com` |
| `national.cws_marketing` | `https://www.cwsmarketing.com/real-estate/`<br>`https://bid` |
| `national.epa_superfund` | `https://data.epa.gov/ef/seplan/`<br>`https://data.epa.gov/ef/seplan/SEPLAN/ROWS/0:200/JSON?search={state`<br>_+1 more_ |
| `national.fdic_failed_banks` | `https://www.fdic.gov/bank-failures/failed-bank-list` |
| `national.first_citizens_reo` | `https://www.firstcitizens.com/real-estate` |
| `national.govdeals` | `https://maestro.lqdt1.com/search/list`<br>`https://www.govdeals.com/index.cfm?fa=Main&searchText=&category=&keyword=`<br>_+4 more_ |
| `national.gsa_realproperty` | `https://realestatesales.gov` |
| `national.homepath_json` | `https://homepath.fanniemae.com/cfl/property-inventory/search-listings`<br>`https://homepath.fanniemae.com/cfl/property-inventory/search`<br>_+2 more_ |
| `national.irs_judicial_sales` | `https://www.irsauctions.gov` |
| `national.irs_treasury` | `https://www.irsauctions.gov/auction/items`<br>`https://www.irsauctions.gov` |
| `national.landsofamerica` | `https://www.land.com/{county`<br>`https://www.land.com{url` |
| `national.legacy_obituaries` | `https://www.legacy.com` |
| `national.liensnc` | `https://www.liensnc.com` |
| `national.loopnet` | `https://www.loopnet.com` |
| `national.nc_sos_ucc` | `https://www.sosnc.gov/online_services/search/by_title/_uniform_commercial_code` |
| `national.opencorporates` | `https://api.opencorporates.com/v0.4/`<br>`https://api.opencorporates.com/v0.4/companies/search` |
| `national.probate_foreclosure_leads` | _(no literal URL in module)_ |
| `national.propwire` | _(no literal URL in module)_ |
| `national.sc_sos_entity` | `https://businessfilings.sc.gov/BusinessFiling/Web/Reporting/SearchByName`<br>`https://businessfilings.sc.gov{href` |
| `national.seeclickfix` | `https://developer.seeclickfix.com/`<br>`https://seeclickfix.com/api/v2/issues` |
| `national.stealth_handoff` | _(no literal URL in module)_ |
| `national.tranzon` | `https://www.tranzon.com/online-real-estate-auctions.aspx` |
| `national.usmarshals_realproperty` | `https://www.usmarshals.gov/what-we-do/asset-forfeiture/real-property`<br>`https://www.usmarshals.gov/what-we-do/asset-forfeiture/real-property/`<br>_+1 more_ |
| `national.va_acquired` | `https://www.va.gov/va-forms/real-property/properties/`<br>`https://www.benefits.va.gov/homeloans/property/property.asp` |
| `national.williams` | `https://www.williamsauction.com` |
| `newspapers.carolina_coast` | `https://www.carolinacoastonline.com/classifieds/?f=rss&q=foreclosure`<br>`https://www.carolinacoastonline.com/classifieds/?f=rss&q=substitute+trustee`<br>_+1 more_ |
| `newspapers.coastland_times` | `https://www.thecoastlandtimes.com` |
| `newspapers.hendersonville_lightning` | `https://www.hendersonvillelightning.com/legal-ads/130-foreclosures.html` |
| `newspapers.post_and_courier` | `https://www.postandcourier.com/classifieds_new/community/announcements/` |
| `newspapers.shelby_star` | `https://www.shelbystar.com`<br>`https://www.shelbystar.com/`<br>_+4 more_ |
| `newspapers.tryon_bulletin` | `https://tryondailybulletin.com`<br>`https://tryondailybulletin.com/?s=foreclosure+sale`<br>_+3 more_ |
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
- **Why / caveats**: The only free source found that carries total judgment debt keyed to a TMS. Only 27 of 47,125 board rows currently have a judgment amount. UPDATED 2026-09-15: the flat "blocked by policy, Greenville is in SCOPE_DENY_COUNTIES" framing predates that day's scope-policy fix (user-confirmed: flip-type leads stay narrow-footprint-only; DISTRESSED-type leads are admitted anywhere in NC/SC, no deny-list applied). "MIE" = Master In Equity, SC's foreclosure-sale judicial officer -- if this source's rows are genuine sale notices (FORECLOSURE_SALE), the Greenville denial is still correct under the new policy too (flip scope didn't change). If the judgment-debt data can be captured as its own DISTRESSED-type record (a debt/lien signal distinct from the sale itself), that half would now be admittable statewide. Type each row correctly rather than assume the old blanket denial still applies uniformly.

### Senior / disabled exemption rolls beyond Buncombe

- **URL**: `county ArcGIS parcel layers carrying ELD/DIS/BLD/VET exemption codes`
- **Counties**: all footprint counties except Buncombe NC
- **Signal**: elderly_disabled
- **Estimated volume**: Buncombe alone yields 3,548
- **Why / caveats**: The elderly_disabled lane is 3,548 rows and 100% ONE county. The generic reader already exists in enrichment_gis_attrs.py and already runs against 17 counties returning zero, so this is pointing it at layers that carry the field, not 15 new scrapers. Caveat: 2,864 of the Buncombe 3,548 are cold single-signal, so it multiplies weak volume unless stacked.

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
- RealtyBid (its own Angular SPA resolves an API base at apiweb.realtybid.com/rest/RBIAPI/ that points to RFC1918 PRIVATE addresses -- unreachable from the public internet; site's own search sits on 'Searching...' forever -- found 2026-09-15 while auditing the NOT_BUILT list, moved here from a stale 'not yet built' entry, see national/auction_bank_reo.py's docstring)
- Bank of America REO (realestatecenter.bankofamerica.com robots.txt is a blanket 'User-agent: * / Disallow: /' -- moved here 2026-09-15, same source as above)
- United Community Bank / UCBI REO (ucbi.com 403s at the edge for both robots.txt and the homepage, no free path -- moved here 2026-09-15, same source as above)
- First Bank REO (localfirstbank.com publishes articles about buying bank-owned homes and no actual inventory feed -- moved here 2026-09-15, same source as above)

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

