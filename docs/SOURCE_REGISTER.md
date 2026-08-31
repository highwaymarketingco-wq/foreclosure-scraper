# MASTER SOURCE REGISTER

Generated 2026-08-20 03:17 UTC by `scripts/gen_source_register.py`. **Re-run it instead of editing this file** — the built half is read from the live registry and the live board, so hand edits are overwritten and go stale.

- Scrapers in the registry: **205**
- Producing rows on the board: **87**
- Registered but contributing ZERO rows: **118**
- Confirmed real and not yet built: **9**
- Board read: `docs/listings.json.gz` (40,008 rows)

Sections: [1 Built and producing](#1-built-and-producing) · [2 Built but zero rows](#2-built-but-producing-zero-rows) · [3 Not built yet](#3-not-built-yet) · [4 Will not / cannot build](#4-will-not-build-cannot-build-not-published) · [5 Checked and rejected](#5-checked-and-rejected-not-a-distress-signal)

---

## 1. Built and producing

Live row counts are what the source actually contributed to the board read above, not a capacity estimate.

| Slug | Rows | Top counties | URLs in the module |
|---|---:|---|---|
| `counties_nc.rutherford_tax` | 4,458 | Rutherford NC (4458) | `https://www.rutherfordcountync.gov/`<br>`https://www.rutherfordcountync.gov/departments/` |
| `counties_sc.sc_public_index` | 3,733 | Anderson SC (673), Spartanburg SC (656), Laurens SC (642) | `https://publicindex.sccourts.org/`<br>`https://publicindex.sccourts.org/{county` |
| `counties_nc.buncombe_elderly` | 3,560 | Buncombe NC (3560) | `https://gis.buncombecounty.org/arcgis/rest/services/property_bc_dis/MapServer/1/query` |
| `counties_sc.spartanburg_vacant` | 3,443 | Spartanburg SC (3443) | `https://services9.arcgis.com/HoRra3ATPLGmyjn6/arcgis/rest/services/`<br>`https://services9.arcgis.com/HoRra3ATPLGmyjn6/` |
| `counties_nc.nc_county_pdf_delinquent_tax` | 3,349 | McDowell NC (2050), Lincoln NC (1299) | `https://www.lincolncountync.gov/DocumentCenter/View/25558/2025-TAXESDelinquentAdvertisementNotice`<br>`https://www.catawbacountync.gov/site/assets/files/11653/delinquent_advertisement_list-hdr_2026.pdf`<br>`https://mcdowellnc.gov/departments/tax-collections/tax-lien-advertisement/ADVERTISEMENT-LIST-FINAL-2025.pdf` |
| `counties_sc.spartanburg_delinquent_tax` | 1,966 | Spartanburg SC (1966) | `https://www.spartanburgcounty.gov/DocumentCenter/View/11161/Real-Property-Tax-Sale-List-PDF`<br>`https://www.spartanburgcounty.gov/DocumentCenter/View/11161/`<br>`https://www.spartanburgcounty.gov/640/2025-Tax-Sale-Info` |
| `counties_sc.pickens_delinquent_parcels` | 1,930 | Pickens SC (1930) | `https://services1.arcgis.com/59960rq18IxUcAVI/arcgis/rest/services`<br>`https://www.co.pickens.sc.us/departments/delinquent_tax/index.php` |
| `counties_sc.spartanburg_condemned` | 1,649 | Spartanburg SC (1649) | `https://maps.spartanburgcounty.org/server/rest/services/` |
| `counties_nc.nc_county_csv_delinquent_tax` | 1,406 | New Hanover NC (1406) | `https://www.nhcgov.com/DocumentCenter/View/11283/Delinquent_Taxpayers_Report_CSV` |
| `counties_nc.buncombe_delinquent_tax` | 1,153 | Buncombe NC (1153) | `https://media.buncombenc.gov/common/tax/buncombe-county-tax-department-advertisement-of-tax-liens.pdf`<br>`https://media.buncombenc.gov/common/tax/` |
| `counties_nc.nc_ptscloud_delinquent_tax` | 1,040 | Henderson NC (1002), Hyde NC (38) | `https://bcpwa.ncptscloud.com` |
| `counties_nc.nc_heir_estate_parcels` | 976 | Rutherford NC (181), Polk NC (122), Gaston NC (79) | _(no literal URL in module)_ |
| `counties.multi_year_delinquent_tax` | 725 | Buncombe NC (589), Oconee SC (135), Pickens SC (1) | `https://services6.arcgis.com/VLA0ImJ33zhtGEaP/arcgis/rest/services`<br>`https://services1.arcgis.com/UOvRn2Rvzysthh3i/arcgis/rest/services`<br>`https://services1.arcgis.com/59960rq18IxUcAVI/arcgis/rest/services`<br>_+3 more_ |
| `national.courtlistener_bankruptcy` | 711 | Anderson SC (109), Buncombe NC (104), Henderson NC (72) | `https://www.courtlistener.com/sign-up/`<br>`https://www.courtlistener.com/profile/api/`<br>`https://www.courtlistener.com/api/rest/v4`<br>_+1 more_ |
| `national.fannie_homepath` | 667 | Spartanburg SC (262), Laurens SC (91), Anderson SC (54) | `https://homepath.fanniemae.com/cfl/property-inventory/search`<br>`https://homepath.fanniemae.com/`<br>`https://homepath.fanniemae.com/property/{uuid` |
| `counties_nc.asheville_str_permits` | 639 | Buncombe NC (639) | `https://gis.ashevillenc.gov/server/rest/services/Permits/`<br>`https://gis.ashevillenc.gov/server/rest/services/Permits/HomestayPermitsView/MapServer/5` |
| `counties_sc.oconee_flc_assignment` | 584 | Oconee SC (584) | `https://services1.arcgis.com/UOvRn2Rvzysthh3i/arcgis/rest/services/`<br>`https://oconeesc.com/auditor-home/forfeited-land` |
| `counties_sc.cherokee_delinquent_tax` | 528 | Cherokee SC (528) | `https://www.cherokeecountysc.gov/wp-json/wp/v2/media` |
| `counties_sc.oconee_forfeited_land` | 453 | Oconee SC (453) | `https://services1.arcgis.com/UOvRn2Rvzysthh3i/arcgis/rest/services/`<br>`https://oconeesc.com/auditor-home/forfeited-land` |
| `counties_sc.georgetown_civicengage` | 406 | Georgetown SC (406) | `https://www.gtcountysc.gov` |
| `counties_nc.nc_ecourts_lis_pendens` | 399 | New Hanover NC (90), Brunswick NC (86), Onslow NC (48) | `https://portal-nc.tylertech.cloud/app/NCJudgmentSearch/`<br>`https://portal-nc.tylertech.cloud/app/NCJudgmentSearchService/search`<br>`https://portal-nc.tylertech.cloud` |
| `counties_sc.sc_public_index_lis_pendens` | 360 | Anderson SC (141), Spartanburg SC (124), Laurens SC (29) | `https://publicindex.sccourts.org/`<br>`https://publicindex.sccourts.org/{county` |
| `national.distressed` | 338 | Gaston NC (54), Spartanburg SC (49), Anderson SC (44) | _(no literal URL in module)_ |
| `counties_nc.asheville_helene` | 313 | Buncombe NC (313) | `https://services.arcgis.com/aJ16ENn1AaqdFlqx/arcgis/rest/services/` |
| `national.landandfarm` | 294 | Gaston NC (25), Henderson NC (22), Cleveland NC (21) | `https://www.landandfarm.com/search/{state_slug` |
| `national.landwatch` | 270 | McDowell NC (37), Burke NC (36), Buncombe NC (22) | `https://www.landwatch.com/{state_slug` |
| `counties_sc.sc_probate_net` | 265 | Charleston SC (265) | `https://www.southcarolinaprobate.net/search/```<br>`https://www.southcarolinaprobate.net/search/` |
| `national.hud_reac_inspection` | 220 | Spartanburg SC (44), Gaston NC (24), Anderson SC (23) | `https://www.hud.gov/sites/default/files/Housing/documents/MF-Inspection-Report.xls```<br>`https://www.hud.gov/sites/default/files/Housing/documents/`<br>`https://www.hud.gov/stat/mfh/inspection-scores` |
| `counties_sc.spartan_weekly_legals` | 205 | Spartanburg SC (205) | `https://www.spartanweeklyonline.com` |
| `counties_sc.sc_rod_acclaim` | 197 | Pickens SC (197) | _(no literal URL in module)_ |
| `counties_nc.henderson_code_violations` | 163 | Henderson NC (163) | `https://services1.arcgis.com/ZfV5vUaX5QvLLBi9/arcgis/rest/services/`<br>`https://www.hendersoncountync.gov/planning/page/` |
| `counties_sc.sc_public_notices` | 155 | Pickens SC (39), Cherokee SC (25), Laurens SC (25) | `https://www.scpublicnotices.com/Search.aspx`<br>`https://www.scpublicnotices.com/Details.aspx?ID={n[` |
| `counties_nc.nc_ecourts_divorce` | 153 | New Hanover NC (46), Buncombe NC (38), Brunswick NC (25) | `https://portal-nc.tylertech.cloud/Portal/Home/Dashboard/29`<br>`https://portal-nc.tylertech.cloud/Portal`<br>`https://portal-nc.tylertech.cloud` |
| `public_notices.nc_notices_counties` | 143 | Buncombe NC (78), Rutherford NC (26), Gaston NC (15) | `https://www.ncnotices.com/Search.aspx`<br>`https://www.ncnotices.com/Details.aspx?ID={` |
| `public_notices.gannett_obituaries` | 142 | Buncombe NC (60), Spartanburg SC (38), Anderson SC (26) | `https://www.{host` |
| `national.foreclosure_dot_com` | 91 | Gaston NC (20), Anderson SC (17), Spartanburg SC (16) | `https://www.foreclosure.com/listings/north-carolina/`<br>`https://www.foreclosure.com/listings/south-carolina/` |
| `counties_sc.spartanburg_city_condemned` | 90 | Spartanburg SC (90) | `https://www.cityofspartanburg.org/robots.txt`<br>`https://www.cityofspartanburg.org/DocumentCenter/View/1901/`<br>`https://www.cityofspartanburg.org/` |
| `law_firms.brock_scott` | 75 | Spartanburg SC (25), Gaston NC (10), Anderson SC (7) | `https://www.brockandscott.com/foreclosure-sales/` |
| `counties_sc.sc_flc` | 74 | Anderson SC (74) | `https://www.spartanburgcounty.gov/216/Tax-Collector`<br>`https://www.andersoncountysc.org/departments-a-z/treasurer/`<br>`https://www.pickenscountysc.gov/treasurer/tax-sale`<br>_+5 more_ |
| `law_firms.hutchens` | 72 | Spartanburg SC (13), Gaston NC (11), Buncombe NC (8) | `https://sales.hutchenslawfirm.com/NCfcSalesList.aspx`<br>`https://sales.hutchenslawfirm.com/SCfcSalesList.aspx` |
| `national.zillow_bulk` | 69 | Spartanburg SC (17), Gaston NC (13), Anderson SC (10) | `https://www.zillow.com/{state.lower(` |
| `counties.column_legal_notices` | 68 | McDowell NC (29), Burke NC (9), Gaston NC (7) | `https://us-central1-enotice-production.cloudfunctions.net/api/search/public-notices`<br>`https://us-central1-enotice-production.cloudfunctions.net` |
| `law_firms.shapiro_ingle_powerbi` | 65 | Gaston NC (23), Buncombe NC (15), Cleveland NC (7) | `https://www.logs.com/nc-upcoming-sales-report.html`<br>`https://app.powerbi.com/view?r=`<br>`https://wabi-us-north-central-h-primary-api.analysis.windows.net`<br>_+2 more_ |
| `counties_sc.charleston_mie` | 54 | Charleston SC (54) | `https://charlestoncounty.gov/foreclosure/runninglist.html`<br>`https://charlestoncounty.gov/departments/master-in-equity/rosters/` |
| `counties_nc.hendersonville_vacant_structures` | 51 | Henderson NC (51) | `https://services1.arcgis.com/UTZTmZoX2rsa9yFA/arcgis/rest/services/`<br>`https://www.hvlnc.gov/departments/development-assistance` |
| `law_firms.kania` | 39 | Burke NC (16), Lincoln NC (8), Cleveland NC (7) | `https://kanialawfirm.com/tax-foreclosures/foreclosure-listings/`<br>`https://kanialawfirm.com/wp-admin/admin-ajax.php` |
| `national.hud_section8_contracts` | 39 | Gaston NC (9), Spartanburg SC (6), Anderson SC (5) | `https://www.hud.gov/hud-partners/multifamily-assist-section8-database`<br>`https://www.hud.gov/sites/dfiles/Housing/documents/`<br>`https://www.hud.gov/hud-partners/` |
| `counties_sc.terry_howe_flc` | 37 | Laurens SC (29), Spartanburg SC (8) | `https://terryhowe.com/wp-json/wp/v2/auctions?per_page=100&_fields=id,title,link,content` |
| `national.zillow_foreclosures` | 30 | Spartanburg SC (6), Buncombe NC (5), Gaston NC (4) | `https://www.zillow.com/{state.lower(` |
| `national.cash_buyer_deeds` | 29 | McDowell NC (24), Burke NC (5) | `https://{host` |
| `national.estate_sales` | 27 | Cleveland NC (8), Buncombe NC (7), Gaston NC (5) | `https://www.estatesales.net`<br>`https://www.estatesale.com`<br>`https://{host` |
| `public_notices.ncnotices` | 25 | Buncombe NC (17), Polk NC (3), Lincoln NC (1) | `https://www.ncnotices.com/`<br>`https://www.ncnotices.com{raw_href` |
| `counties_nc.nc_rod_logan` | 24 | Transylvania NC (13), McDowell NC (11) | _(no literal URL in module)_ |
| `national.servicelink_auction` | 23 | Gaston NC (5), Spartanburg SC (5), Buncombe NC (3) | `https://ui.exostechnology.com/api/listingsvc/v1/listings?limit=100&state={ST`<br>`https://ui.exostechnology.com/api/listingsvc/v1/listings`<br>`https://www.servicelinkauction.com`<br>_+1 more_ |
| `counties_nc.buncombe_tax` | 22 | Buncombe NC (22) | `https://www.trumba.com/calendars/tax-foreclosures-all.json`<br>`https://taxforeclosures.buncombenc.gov/` |
| `national.crexi_multifamily` | 22 | Spartanburg SC (3), Polk NC (2), Gaston NC (2) | `https://www.crexi.com` |
| `national.nc_upset_bids` | 22 | Rutherford NC (19), Cleveland NC (2), Burke NC (1) | `https://kanialawfirm.com/tax-foreclosures/foreclosure-listings/`<br>`https://kanialawfirm.com/wp-admin/admin-ajax.php`<br>`https://www.rutherfordcountync.gov/departments/` |
| `counties_sc.anderson_master_in_equity` | 21 | Anderson SC (21) | `https://www.andersoncountysc.org/departments-a-z/master-in-equity/`<br>`https://www.andersoncountysc.org{href` |
| `reo.vrm_va_reo` | 18 | - | `https://vrmproperties.com/`<br>`https://vrmproperties.com` |
| `national.homeharvest` | 16 | Anderson SC (5), Spartanburg SC (4), Burke NC (3) | `https://github.com/ZacharyHampton/HomeHarvest` |
| `national.hubzu` | 16 | Spartanburg SC (4), Anderson SC (2), Laurens SC (2) | `https://www.hubzu.com/portal/auctions?state={state`<br>`https://www.hubzu.com/`<br>`https://www.hubzu.com{url` |
| `law_firms.rogers_townsend` | 15 | Spartanburg SC (9), Anderson SC (3), Laurens SC (1) | `https://rogerstownsend.com/reports/SC_Listings.pdf`<br>`https://rogerstownsend.com/reports/NC_Listings.pdf` |
| `law_firms.bell_carrington` | 14 | Spartanburg SC (7), Pickens SC (2), Anderson SC (2) | `https://docs.google.com/spreadsheets/d/e/`<br>`https://bellcarrington.com/foreclosure-sales/` |
| `national.courtlistener_adversary` | 14 | Buncombe NC (5), Cleveland NC (3), Lincoln NC (2) | `https://www.courtlistener.com` |
| `national.auction_dot_com` | 13 | Spartanburg SC (3), Cherokee SC (2), Lincoln NC (2) | `https://www.auction.com/residential/nc/`<br>`https://www.auction.com/residential/sc/`<br>`https://www.auction.com/details/{slug` |
| `counties_sc.pickens_master_in_equity` | 11 | Pickens SC (11) | `https://www.co.pickens.sc.us/departments/master_in_equity/sales_rosters.php`<br>`https://www.co.pickens.sc.us/` |
| `counties_sc.sc_county_rosters` | 11 | Oconee SC (7), Laurens SC (4) | `https://publicindex.sccourts.org` |
| `counties_nc.henderson_foreclosure_parcels` | 10 | Henderson NC (10) | `https://www.arcgis.com`<br>`https://hendersoncounty.maps.arcgis.com`<br>`https://experience.arcgis.com/experience/` |
| `national.hud_homestore` | 10 | Gaston NC (3), Spartanburg SC (3), Cleveland NC (2) | `https://www.hudhomestore.gov/searchresult?handler=GetFilteredResult`<br>`https://www.hudhomestore.gov` |
| `law_firms.mcmichael_taylor_gray` | 9 | Anderson SC (3), Spartanburg SC (2), McDowell NC (1) | `https://app.powerbi.com/view?r=eyJrIjoiOTQwOTdiYWYtOGQwMy00OGUzLWI4MjktOTczNDc0ODE2ZGY1IiwidCI6IjEzZDFlNzhjLTgyNDgtNGVlYS04OWY3LWQzNGIzZWJkOGM3OSIsImMiOjN9`<br>`https://app.powerbi.com/view?r=eyJrIjoiOTQwOTdiYWYtOGQwMy00OGUzLWI4MjktOTczNDc0ODE2ZGY1Ii` |
| `national.jail_bookings` | 8 | Buncombe NC (2), Anderson SC (2), Cleveland NC (1) | `http://mugshots.spartanburgsheriff.org/`<br>`https://buncombecountyso.policetocitizen.com|23`<br>`http://74.218.167.200/p2c`<br>_+8 more_ |
| `national.xome` | 8 | Anderson SC (3), Cleveland NC (2), Spartanburg SC (1) | `https://www.xome.com/auctions/bank-owned`<br>`https://www.xome.com/auctions/foreclosure-homes`<br>`https://www.xome.com/auctions/foreclosuresales`<br>_+1 more_ |
| `counties.nod_discovery` | 7 | Cleveland NC (6), Buncombe NC (1) | `https://{host`<br>`https://{kofile.KOFILE_COUNTIES[(state`<br>`https://example.invalid/` |
| `counties_sc.sc_state_tax_lien` | 7 | Spartanburg SC (3), Pickens SC (1), Anderson SC (1) | `https://mydorway.dor.sc.gov/?link=delinquentind`<br>`https://dor.sc.gov/delinquent-taxpayers` |
| `counties_nc.cleveland_tax` | 6 | Cleveland NC (6) | `https://www.clevelandcounty.com/main/departments/` |
| `counties_sc.spartanburg_flc` | 6 | Spartanburg SC (6) | `https://www.spartanburgcounty.gov/DocumentCenter/View/104130` |
| `counties_nc.nc_rod_substitute_trustee` | 5 | Cleveland NC (3), Henderson NC (1), Transylvania NC (1) | `https://buncombe-recordings.permitium.com/```<br>`https://www.nccourts.gov/` |
| `counties_nc.nc_county_tax_foreclosure` | 4 | Rutherford NC (3), Gaston NC (1) | `https://www.gastongov.com/669/Tax-Foreclosure-Sales`<br>`https://www.gastongov.com/671/Previous-Tax-Foreclosure-Sales`<br>`https://mcdowellnc.gov/departments/tax-collections/tax-foreclosures/upcoming-tax-foreclosure-sales`<br>_+1 more_ |
| `national.trulia` | 4 | Spartanburg SC (4) | `https://www.trulia.com/foreclosures/`<br>`https://www.trulia.com/foreclosures/Charlotte,NC/`<br>`https://www.trulia.com/foreclosures/Raleigh,NC/`<br>_+6 more_ |
| `counties_sc.spartanburg_master_in_equity` | 3 | Spartanburg SC (3) | `https://www.spartanburgcounty.gov/DocumentCenter/View/3392/Sale-Results`<br>`https://www.spartanburgcounty.gov/DocumentCenter/View/11824/Deficiency-Sale` |
| `counties_nc.nc_govdeals_real_property` | 1 | Anderson SC (1) | `https://maestro.lqdt1.com/search/list`<br>`https://www.transylvaniacounty.org/news`<br>`https://www.govdeals.com/asset/{asset_id`<br>_+2 more_ |
| `counties_sc.sc_rod_cott` | 1 | Union SC (1) | _(no literal URL in module)_ |
| `law_firms.ingle_firm` | 1 | Gaston NC (1) | `https://www.theinglefirm.com/Sales.aspx` |
| `national.freddie_homesteps` | 1 | Spartanburg SC (1) | `https://www.homesteps.com/listing/search?search=NC`<br>`https://www.homesteps.com/listing/search?search=SC`<br>`https://www.homesteps.com/`<br>_+1 more_ |
| `national.realtor_foreclosures` | 1 | Spartanburg SC (1) | _(no literal URL in module)_ |
| `national.sheriff_sales` | 1 | Cleveland NC (1) | `https://www.brunswicksheriff.com`<br>`https://www.charlestoncounty.org`<br>`https://www.sheriffclevelandcounty.com`<br>_+1 more_ |
| `newspapers.coastland_times` | 1 | Dare NC (1) | `https://www.thecoastlandtimes.com` |
| `national.irs_treasury` | 0 | _(none yet — seasonal)_ | `https://www.irsauctions.gov/auction/items`<br>`https://www.irsauctions.gov` |
| `national.sc_public_index` | 0 | _(none yet — requires nodriver)_ | `https://publicindex.sccourts.org/{county}/publicindex/`<br>`https://jcmsweb.charlestoncounty.org/PublicIndex/PISearch.aspx` |
| `national.tranzon` | 0 | _(none yet — empty upstream)_ | `https://www.tranzon.com/online-real-estate-auctions.aspx` |
| `national.williams` | 0 | _(none yet — empty upstream)_ | `https://www.williamsauction.com` |

## 2. Built but producing zero rows

Registered and importable, contributing nothing to the board read above. A zero here is NOT automatically a bug: it can mean the upstream is genuinely empty right now, the source is seasonal, it is gated off, it is blocked (see section 4), or it simply was not in the last run's source list.

| Slug | URLs in the module |
|---|---|
| `counties_nc.gaston_vacant` | `https://gis.gastoncountync.gov/publicgis/rest/services/PublicGIS/Parcels/MapServer/11/query` _(2026-08-30 build: 21,288 vacant parcels + owner/mailing/value/sqft/sale)_ |
| `counties_nc.rutherford_foreclosure` | `https://www.rutherfordcountync.gov/` _(2026-08-30 build: NEW foreclosure feed, board had 0% — 20 rows)_ |
| `counties_nc.mcdowell_tax_foreclosure` | `https://mcdowellnc.gov/departments/tax-collections/tax-foreclosures/upcoming-tax-foreclosure-sales` _(read_html upset+pending)_ |
| `counties_nc.cleveland_tax_foreclosure` | `https://www.clevelandcounty.com/main/departments/` _(county tax-foreclosure HTML table — 14 rows)_ |
| `counties_nc.lincoln_vacant` | `https://arcgisserver.lincolncounty.org/arcgis/rest/services/ComDevData/MapServer/25/query` _(14,798 vacant; expired-cert host, verify=False)_ |
| `counties_nc.transylvania_vacant` | `https://gis.transylvaniacounty.org/server/rest/services/Parcels/FeatureServer/2/query` _(11,131 vacant-land)_ |
| `counties_nc.transylvania_delinquent_tax` | `https://tax.transylvaniacounty.org/TaxBillSearch` _(443 unpaid, 3-step JSON cookie chain)_ |
| `counties_nc.mcdowell_probate` | `https://services9.arcgis.com/ETP7IuCigkUz7iI9/arcgis/rest/services/McDowell_Parcels/FeatureServer/0/query` _(414 deceased-owner probate/heir leads)_ |
| `city_websites.asheville_min_housing` | `https://www.ashevillenc.gov/department/development-services/minimum-housing/` |
| `city_websites.charlotte_open_data` | `https://data.charlottenc.gov/resource/c6er-5c2c.json`<br>`https://data.charlottenc.gov/resource/6jx5-894j.json`<br>_+1 more_ |
| `city_websites.search` | `https://{domain` |
| `counties.sitemap_walker` | `https://www.spartanburgcounty.gov`<br>`https://www.cherokeecountysc.gov`<br>_+10 more_ |
| `counties_generic.arcgis_distress_layers` | `https://services6.arcgis.com/VLA0ImJ33zhtGEaP/arcgis/rest/services/`<br>`https://www.buncombecounty.org/governing/depts/tax/`<br>_+22 more_ |
| `counties_generic.epa_frs_sites` | `https://data.epa.gov/dmapservice/frs.frs_program_facility`<br>`https://www.epa.gov/frs` |
| `counties_generic.state_contamination` | `https://services2.arcgis.com/kCu40SDxsCGcuUWO/arcgis/rest/services`<br>`https://www.deq.nc.gov/about/divisions/waste-management/underground-storage-tanks`<br>_+2 more_ |
| `counties_nc.brunswick_legal_notices` | `https://www.brunswickcountync.gov/912/Legal-Notices`<br>`https://www.brunswickcountync.gov`<br>_+1 more_ |
| `counties_nc.buncombe_tax_foreclosure` | `https://www.trumba.com/calendars/tax-foreclosures-all.ics`<br>`https://taxforeclosures.buncombenc.gov/` |
| `counties_nc.cumberland_tax_foreclosure` | `https://www.co.cumberland.nc.us/departments/tax/tax-foreclosures` |
| `counties_nc.edgecombe_tax_foreclosure` | `https://www.edgecombecountync.gov/departments/tax/foreclosures` |
| `counties_nc.gaston_surplus_properties` | `https://www.gastongov.com/709/Surplus-Properties`<br>`https://www.gastongov.com`<br>_+1 more_ |
| `counties_nc.gaston_tax_foreclosures` | `https://www.gastongov.com/668/Tax-Foreclosures` |
| `counties_nc.haywood_tax_foreclosures` | `https://www.haywoodcountync.gov/337/Tax-Foreclosures` |
| `counties_nc.henderson_tax` | `https://www.hendersoncountync.gov/tax/page/tax-foreclosure-sales` |
| `counties_nc.lincoln_code_violations` | `https://arcgisserver.lincolncountync.gov/arcgis/rest/services/` |
| `counties_nc.nc_bankruptcy_sales` | `https://www.nceb.uscourts.gov/Public-Sales-Notice`<br>`https://www.ncmb.uscourts.gov/public-sales` |
| `counties_nc.nc_civicplus_tax_sale` | `https://www.alamance-nc.com`<br>`https://www.alexandercountync.gov`<br>_+65 more_ |
| `counties_nc.nc_coastal_tax_foreclosure` | `https://www.brunswickcountync.gov/912/Legal-Notices`<br>`https://www.brunswickcountync.gov`<br>_+5 more_ |
| `counties_nc.nc_deq_dsca` | `https://www.deq.nc.gov/frac/dry-cleaning-solvent-cleanup-act-dsca/dsca-sites` |
| `counties_nc.nc_ecourts_estates` | `https://portal-nc.tylertech.cloud/Portal/Home/Dashboard/29`<br>`https://portal-nc.tylertech.cloud/Portal`<br>_+1 more_ |
| `counties_nc.nchfa_reo` | `https://www.nchfa.com/home-buyers/properties-sale` |
| `counties_nc.new_hanover_foreclosures` | `https://www.nhcgov.com/345/Foreclosures` |
| `counties_nc.polk_tax` | `https://www.polknc.gov/upcoming_auction.php` |
| `counties_nc.rutherford_wildfire_tax` | `https://www.rutherfordcountync.gov/tax_search/index.php`<br>`https://d1ebsyxxbc7tep.cloudfront.net`<br>_+1 more_ |
| `counties_nc.stokes_delinquent_tax` | `https://www.co.stokes.nc.us/tax/delinquent-taxes` |
| `counties_nc.swain_tax_foreclosures` | `https://www.swaincountync.gov/` |
| `counties_nc.wake_tax_foreclosure` | `https://www.wake.gov/departments-government/tax-administration/real-estate/foreclosures`<br>`https://services` |
| `counties_nc.wnc_rod_foreclosure_starts` | _(no literal URL in module)_ |
| `counties_nc.wnc_tax_foreclosures` | `https://www.wataugacounty.org/`<br>`https://www.averycounty.com/`<br>_+3 more_ |
| `counties_sc.abbeville_delinquent_tax` | `https://abbevillecountysc.com/delinquent-tax-collector/` |
| `counties_sc.aiken_delinquent_tax` | `https://sc-aikencounty.civicplus.com/309/Tax-Foreclosures` |
| `counties_sc.anderson_sheriff` | `https://www.andersonsheriff.com/sheriff-sales` |
| `counties_sc.bamberg_sheriff` | `https://www.bambergcounty.sc.gov/sheriff/sheriff-sales` |
| `counties_sc.barnwell_sheriff` | `https://www.barnwellcounty.com/sheriff/sheriff-sales` |
| `counties_sc.charleston_delinquent_tax` | `https://charlestoncounty.gov/departments/delinquent-tax/`<br>`https://www.charlestoncounty.gov/departments/delinquent-tax/files/RP-Tax-Sale-Listing.pdf`<br>_+1 more_ |
| `counties_sc.cherokee_rod` | `https://www.sclandrecords.net` |
| `counties_sc.chester_delinquent_tax` | `https://www.chestercounty.org/treasurer/delinquent-tax-sale` |
| `counties_sc.clarendon_tax_auction` | `https://www.clarendoncountysc.gov/` |
| `counties_sc.colleton_tax_sale` | `https://www.colletoncounty.org/delinquent-tax`<br>`https://www.colletoncounty.org/delinquent-tax/tax-sale`<br>_+1 more_ |
| `counties_sc.darlington_delinquent_tax` | `https://www.darcosc.com/treasurer/delinquent-tax-sale` |
| `counties_sc.dillon_sheriff` | `https://www.dilloncountysheriff.com/sheriff-sales` |
| `counties_sc.edgefield_delinquent_tax` | `https://www.edgefieldcountysc.com/treasurer/delinquent-tax-sale` |
| `counties_sc.fairfield_delinquent_tax` | `https://www.fairfieldsc.com/treasurer/delinquent-tax-sale` |
| `counties_sc.florence_delinquent_tax` | `https://www.florenceco.org/` |
| `counties_sc.greenville_tax_distress` | `https://www.gcgis.org/arcgis/rest/services/GreenvilleJS/Map_Layers_JS/MapServer`<br>`https://www.greenvillecounty.org/appsAS400/Taxsale/`<br>_+2 more_ |
| `counties_sc.greenwood_delinquent_tax` | `https://www.greenwoodsc.gov/treasurer/delinquent-tax-sale` |
| `counties_sc.horry_flc` | `https://www.horrycountysc.gov/boards-and-commissions/`<br>`https://www.horrycountysc.gov/media/om1d2bwo/2025-flc-list-42126.xlsx`<br>_+1 more_ |
| `counties_sc.kershaw_flc` | `https://www.kershaw.sc.gov/treasurer/forfeited-land-commission` |
| `counties_sc.lancaster_delinquent_tax` | `https://www.lancastercountysc.gov/government/tax-office`<br>`https://www.lancastercountysc.gov{pdf_url` |
| `counties_sc.laurens_delinquent_tax` | `https://www.laurenscountysc.us/treasurer/delinquent-tax-sale` |
| `counties_sc.lexington_flc` | `https://lex-co.sc.gov/treasurer/forfeited-land-commission`<br>`https://lex-co.sc.gov/central-stores-auction-items`<br>_+1 more_ |
| `counties_sc.marlboro_delinquent_tax` | `https://www.marlborocountysc.us/treasurer/delinquent-tax-sale` |
| `counties_sc.mccormick_flc` | `https://www.mccormickcountysc.org/treasurer/forfeited-land-commission` |
| `counties_sc.meares_auctions` | `https://www.mpa-sc.com/```<br>`https://maps.google.com/?q=`<br>_+1 more_ |
| `counties_sc.newberry_delinquent_tax` | `https://www.newberrycounty.net/treasurer/delinquent-tax-sale` |
| `counties_sc.oconee_flc` | `https://www.oconeecounty.com/treasurer/forfeited-land-commission` |
| `counties_sc.oconee_tax_sale` | `https://docs.google.com/spreadsheets/d/e/{_PUB_ID`<br>`https://oconeesc.com/delinquent-tax/sale-list` |
| `counties_sc.pickens_tax_sale` | `https://www.co.pickens.sc.us/departments/delinquent_tax/index.php`<br>`https://www.co.pickens.sc.us/` |
| `counties_sc.saluda_delinquent_tax` | `https://www.saludacountysc.us/treasurer/delinquent-tax-sale` |
| `counties_sc.sc_coastal_rosters` | _(no literal URL in module)_ |
| `counties_sc.sc_delinquent_tax_list` | `https://cherokeecountysc.gov/delinquent-tax/tax-sale-bidders/`<br>`https://cherokeecountysc.gov/wp-content/uploads/{year` |
| `counties_sc.sc_des_brownfields` | `https://des.sc.gov/programs/bureau-land-waste-management/`<br>`https://des.sc.gov/community/environmental-sites-projects` |
| `counties_sc.sc_dew_lien_registry` | `https://uitax.dew.sc.gov/LienRegistry/`<br>`https://dew.sc.gov/benefit-lien-registry`<br>_+2 more_ |
| `counties_sc.sc_dor_delinquent_taxpayers` | `https://mydorway.dor.sc.gov/?link=delinquentind` |
| `counties_sc.sc_probate_notices` | `https://{paper.host` |
| `counties_sc.sc_tax_delinquent` | `https://1543.newstogo.us/editionviewer/default.aspx?Edition=`<br>`https://www.andersoncountysc.org/departments-a-z/treasurer/`<br>_+11 more_ |
| `counties_sc.sc_ust_registry` | `https://apps.des.sc.gov/USTRegistry/` |
| `counties_sc.sumter_surplus` | `https://www.sumtercountysc.gov/online_services/property/surplus_sales.php` |
| `counties_sc.terry_howe_auctions` | `https://terryhowe.com/wp-json/wp/v2/auctions` |
| `counties_sc.union_delinquent_tax` | `https://www.unioncountysc.org/treasurer/delinquent-tax-sale` |
| `counties_sc.york_delinquent_tax` | `https://www.yorkcountysc.gov/216/Tax-Collection`<br>`https://www.yorkcountysc.gov{pdf_url` |
| `counties_sc.zombie_properties` | _(no literal URL in module)_ |
| `law_firms.alaw` | `https://www.alaw.net/foreclosure-sales/north-carolina/`<br>`https://www.alaw.net/foreclosure-sales/south-carolina/` |
| `law_firms.aldridge_pite` | `https://aldridgepite.com/sale-day-listings-selection/foreclosure-listings-north-carolina/`<br>`https://aldridgepite.com/disclaimer-north-carolina/` |
| `law_firms.finkel` | `https://www.finkellaw.com/images/Webs.pdf`<br>`https://www.finkellawcharleston.com/images/Webs.pdf` |
| `law_firms.korn` | `https://www.kornlawfirm.com/foreclosure-sales/`<br>`https://www.kornlawfirm.com/sales/` |
| `law_firms.mewborn_deselms` | `https://www.mewbornlaw.biz` |
| `law_firms.zacchaeus` | `https://www.zls-nc.com/listings` |
| `national.auction_bank_reo` | `https://apiweb.realtybid.com/rest/RBIAPI/`<br>`https://bid.auctionnetwork.com/Auctions`<br>_+2 more_ |
| `national.bid4assets` | `https://www.bid4assets.com/storefront/index.cfm?searchstate=NC&searchprop=Real+Estate`<br>`https://www.bid4assets.com/storefront/index.cfm?searchstate=SC&searchprop=Real+Estate`<br>_+1 more_ |
| `national.courtlistener_civil` | `https://www.courtlistener.com` |
| `national.craigslist_fsbo` | `https://sapi.craigslist.org/web/v8/postings/search/full`<br>`https://{host` |
| `national.cws_marketing` | `https://www.cwsmarketing.com/real-estate/`<br>`https://bid` |
| `national.epa_superfund` | `https://ejscreen.epa.gov/mapper`<br>`https://enviro.epa.gov`<br>_+3 more_ |
| `national.fdic_failed_banks` | `https://www.fdic.gov/bank-failures/failed-bank-list` |
| `national.fema_disasters` | `https://www.fema.gov/disaster/declarations` |
| `national.first_citizens_reo` | `https://www.firstcitizens.com/real-estate` |
| `national.govdeals` | `https://www.govdeals.com/api/esolutions/search`<br>`https://www.govdeals.com/esolutions/auction/`<br>_+1 more_ |
| `national.gsa_realproperty` | `https://realestatesales.gov` |
| `national.gsa_surplus` | `https://www.gsa.gov/about-us/organization/office-of-governmentwide-policy/`<br>`https://www.gsa.gov/real-estate/real-estate-listings`<br>_+1 more_ |
| `national.hibid_real_estate` | `https://hibid.com/graphql```<br>`https://hibid.com/graphql`<br>_+3 more_ |
| `national.homepath_json` | `https://homepath.fanniemae.com/cfl/property-inventory/search-listings`<br>`https://homepath.fanniemae.com/`<br>_+1 more_ |
| `national.irs_judicial_sales` | `https://www.irsauctions.gov` |
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
| `national.usda_properties` | `https://usdaproperties.com/property/`<br>`https://www.usdaproperties.com/property/sc/county/`<br>_+2 more_ |
| `national.usmarshals_realproperty` | `https://www.usmarshals.gov/what-we-do/asset-forfeiture/real-property`<br>`https://www.usmarshals.gov/what-we-do/asset-forfeiture/real-property/`<br>_+1 more_ |
| `national.va_acquired` | `https://www.va.gov/va-forms/real-property/properties/`<br>`https://www.benefits.va.gov/homeloans/property/property.asp` |
| `newspapers.carolina_coast` | `https://www.carolinacoastonline.com/classifieds/?f=rss&q=foreclosure`<br>`https://www.carolinacoastonline.com/classifieds/?f=rss&q=substitute+trustee`<br>_+1 more_ |
| `newspapers.daily_courier` | `https://www.thedigitalcourier.com/classifieds/community/announcements/legal/`<br>`https://www.thedigitalcourier.com` |
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

