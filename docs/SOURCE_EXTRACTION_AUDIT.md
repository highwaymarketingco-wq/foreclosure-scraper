# SOURCE EXTRACTION AUDIT — per-source, is EVERYTHING being pulled?

Auto-generated from the live registry by `scripts/gen_extraction_audit.py`. **239 scrapers**, of which **18 already wire the document harvester** (PDFs/deeds/notices) and **221 do not yet**. Re-run the script any time; it reads `discover()`, so it can never miss a source.

## The audit protocol (do this for EVERY source in the TODO table)

For each source, open the actual page (its real URL) and confirm, with eyes on the page, that the scraper captures EVERYTHING of value, not just the row it currently grabs:

1. **Every data field on the listing/detail page** — address, owner, parcel/TMS, sale date, opening bid, debt/judgment $, case number, attorney/trustee. If a field is on the page but not in the Listing, wire it.
2. **PDFs** — Notice of Sale, deed, contract package, order of sale, tax list. If the page links any, route them through `harvest_document_links()` + `stamp_documents()` so doc-OCR reads them. This is the single most common miss.
3. **Images** — property photos / assessor card images (for the vision tier). Capture the URL, do not skip it.
4. **External links** — links off to a county GIS, an auction platform, a law-firm detail page: follow them if they carry data the row lacks.
5. **Internal links** — a 'details' / 'more info' link on the SAME site that opens a richer page. Detail pages almost always carry fields the list page omits.

Then VERIFY the change three ways: it compiles, `discover()` still lists the slug, and a live `fetch()` returns real Listings with the newly-captured field populated. Never claim a fix you have not run. Stay in-footprint (18 counties, see `MASTER_GAPS_WALLS_AND_MANUAL_LANES.md`) and FREE/compliant (no CAPTCHA/login/WAF defeat).

The `hint` column flags what the CODE mentions (pdf?, img?, detail-page, links) as a starting clue for where to look. It is a hint from static text, NOT proof the source has or lacks these — your eyes on the live page are the authority.

## DONE — already harvest documents (18)

| Slug | already captures | URLs |
|---|---|---|
| `counties.sitemap_walker` | pdf?, deed/notice?, links | https://www.spartanburgcounty.gov<br>https://www.cherokeecountysc.gov |
| `counties_nc.brunswick_legal_notices` | pdf?, deed/notice?, img?, detail-page, links | https://www.brunswickcountync.gov/912/Legal-Notices<br>https://www.brunswickcountync.gov |
| `counties_nc.edgecombe_tax_foreclosure` | pdf?, deed/notice?, detail-page, links | https://www.edgecombe<br>https://www.edgecombecountync.gov/businesses/tax_collector/tax_foreclosure_list.php |
| `counties_nc.haywood_tax_foreclosures` | pdf?, deed/notice?, img?, detail-page, links | https://www.haywoodcountync.gov/337/Tax-Foreclosures<br>https://www.haywoodcountync.gov/Bids.aspx |
| `counties_nc.henderson_foreclosure_parcels` | deed/notice?, img? | https://www.arcgis.com<br>https://hendersoncounty.maps.arcgis.com |
| `counties_nc.nc_bankruptcy_sales` | pdf?, deed/notice?, detail-page, links | https://www.nceb.uscourts.gov/Public-Sales-Notice<br>https://www.ncmb.uscourts.gov/public-sales |
| `counties_nc.nc_coastal_tax_foreclosure` | deed/notice?, img?, detail-page, links | https://www.brunswickcountync.gov/912/Legal-Notices<br>https://www.brunswickcountync.gov |
| `counties_nc.swain_tax_foreclosures` | pdf?, deed/notice?, img?, detail-page, links | https://www.swaincountync.gov/tax-office/ |
| `counties_sc.meares_auctions` | deed/notice?, img?, detail-page, links | https://www.mpa-sc.com/<br>https://maps.google.com/ |
| `counties_sc.terry_howe_auctions` | pdf?, deed/notice?, img?, detail-page | https://terryhowe.com/wp-json/wp/v2/auctions |
| `law_firms.mewborn_deselms` | pdf?, deed/notice?, detail-page, links | https://www.mewbornlaw.biz |
| `law_firms.rogers_townsend` | pdf?, deed/notice? | https://rogerstownsend.com/reports/NC_Listings.pdf<br>https://rogerstownsend.com/reports/ |
| `national.cws_marketing` | deed/notice?, img?, detail-page, links | https://www.cwsmarketing.com/real-estate/<br>https://bid\.cwsmarketing\.com/auctions/catalog/id/\d+ |
| `national.gsa_realproperty` | deed/notice?, img?, detail-page | https://realestatesales.gov<br>https://...jpg |
| `national.irs_judicial_sales` | pdf?, deed/notice?, img?, detail-page, links | https://www.irsauctions.gov |
| `national.servicelink_auction` | deed/notice?, img? | https://ui.exostechnology.com/api/listingsvc/v1/listings<br>https://www.servicelinkauction.com |
| `national.usmarshals_realproperty` | pdf?, deed/notice?, img?, detail-page, links | https://reallook.com/properties<br>https://reallook.com |
| `national.williams` | deed/notice?, img?, detail-page, links | https://bid.auctionnetwork.com/<br>https://bid.auctionnetwork.com |

## TODO — audit each for full extraction (221)

| Slug | code hints (verify on the live page) | URLs |
|---|---|---|
| `city_websites.asheville_min_housing` | deed/notice?, detail-page, links | https://www.ashevillenc.gov/department/development-services/minimum-housing/ |
| `city_websites.charlotte_open_data` | detail-page | https://gis.charlottenc.gov/arcgis/rest/services/HNS/CodeEnforcementCasesAll/MapServer/0<br>https://gis.charlottenc.gov/arcgis/rest/services/HNS/ |
| `city_websites.search` | deed/notice? | (see SOURCE_REGISTER.md) |
| `counties.column_legal_notices` | deed/notice?, detail-page | https://us-central1-enotice-production.cloudfunctions.net/api/search/public-notices<br>https://us-central1-enotice-production.cloudfunctions.net |
| `counties.multi_year_delinquent_tax` | deed/notice?, detail-page | https://services6.arcgis.com/VLA0ImJ33zhtGEaP/arcgis/rest/services<br>https://services1.arcgis.com/UOvRn2Rvzysthh3i/arcgis/rest/services |
| `counties.nod_discovery` | deed/notice? | (see SOURCE_REGISTER.md) |
| `counties_generic.arcgis_distress_layers` | deed/notice?, detail-page | https://services6.arcgis.com/VLA0ImJ33zhtGEaP/arcgis/rest/services/<br>https://www.buncombecounty.org/governing/depts/tax/ |
| `counties_generic.epa_frs_sites` | detail-page | https://data.epa.gov/dmapservice/frs.frs_program_facility<br>https://ofmpub.epa.gov/frs_public2/fii_query_dtl.disp_program_facility |
| `counties_generic.state_contamination` | deed/notice?, detail-page | https://services2.arcgis.com/kCu40SDxsCGcuUWO/arcgis/rest/services<br>https://www.deq.nc.gov/about/divisions/waste-management/underground-storage-tanks |
| `counties_nc.albemarle_observer_tax_lists` | deed/notice? | https://albemarleobserver.news/wp-json/wp/v2/posts<br>https://albemarleobserver.news/wp-json/wp/v2/posts/<id |
| `counties_nc.asheville_code_enforcement` | - | https://gis.ashevillenc.gov/server/rest/services/Permits/<br>https://www.ashevillenc.gov/department/development-services/ |
| `counties_nc.asheville_helene` | img? | https://services.arcgis.com/aJ16ENn1AaqdFlqx/arcgis/rest/services/ |
| `counties_nc.asheville_str_permits` | - | https://gis.ashevillenc.gov/server/rest/services/Permits/<br>https://gis.ashevillenc.gov/server/rest/services/Permits/HomestayPermitsView/MapServer/5 |
| `counties_nc.buncombe_delinquent_tax` | pdf? | https://media.buncombenc.gov/common/tax/buncombe-county-tax-department-advertisement-of-tax-liens.pdf<br>https://media.buncombenc.gov/common/tax/ |
| `counties_nc.buncombe_elderly` | deed/notice? | https://gis.buncombecounty.org/arcgis/rest/services/property_bc_dis/MapServer/1/query |
| `counties_nc.buncombe_tax` | links | https://www.trumba.com/calendars/tax-foreclosures-all.json<br>http://maps.google.com/ |
| `counties_nc.buncombe_tax_foreclosure` | pdf? | https://media.buncombenc.gov/common/tax/foreclosure-listings/fcl.pdf<br>https://taxforeclosures.buncombenc.gov/ |
| `counties_nc.cleveland_tax` | deed/notice?, detail-page | https://www.clevelandcounty.com/main/departments/ |
| `counties_nc.cleveland_tax_foreclosure` | - | https://www.clevelandcounty.com/main/departments/ |
| `counties_nc.cumberland_tax_foreclosure` | detail-page | https://www.co.cumberland.nc.us/departments/tax-group/tax/tax-foreclosure-sales |
| `counties_nc.gaston_surplus_properties` | pdf?, detail-page, links | https://www.gastongov.com/709/Surplus-Properties<br>https://www.gastongov.com |
| `counties_nc.gaston_tax_foreclosures` | detail-page | https://www.gastongov.com/669<br>https://www.gastongov.com/671 |
| `counties_nc.gaston_vacant` | deed/notice?, img? | https://gastonnc.devnetwedge.com/PropertyImages/<br>https://gis.gastoncountync.gov/publicgis/rest/services/ |
| `counties_nc.gastonia_code_enforcement` | deed/notice?, detail-page | https://devsvcs.gastonianc.gov<br>https://gis.gastoncountync.gov/publicgis/rest/services/ |
| `counties_nc.henderson_code_violations` | - | https://services1.arcgis.com/ZfV5vUaX5QvLLBi9/arcgis/rest/services/<br>https://www.hendersoncountync.gov/planning |
| `counties_nc.henderson_tax` | detail-page, links | https://www.hendersoncountync.gov/tax/page/tax-foreclosure-sales |
| `counties_nc.hendersonville_vacant_structures` | deed/notice?, detail-page | https://services1.arcgis.com/UTZTmZoX2rsa9yFA/arcgis/rest/services/<br>https://www.hvlnc.gov/community-development |
| `counties_nc.lincoln_code_violations` | - | https://arcgisserver.lincolncountync.gov/arcgis/rest/services/ |
| `counties_nc.lincoln_vacant` | deed/notice? | https://arcgisserver.lincolncounty.org/arcgis/rest/services/ComDevData/MapServer/25/query |
| `counties_nc.mcdowell_probate` | deed/notice? | https://services9.arcgis.com/ETP7IuCigkUz7iI9/arcgis/rest/services/ |
| `counties_nc.mcdowell_tax_foreclosure` | detail-page | https://mcdowellnc.gov/departments/tax-collections/ |
| `counties_nc.nc_civicplus_tax_sale` | pdf?, img?, links | https://www.alamance-nc.com<br>https://www.alexandercountync.gov |
| `counties_nc.nc_county_csv_delinquent_tax` | - | https://www.nhcgov.com/DocumentCenter/View/11283/Delinquent_Taxpayers_Report_CSV |
| `counties_nc.nc_county_pdf_delinquent_tax` | pdf?, deed/notice? | https://www.lincolncountync.gov/DocumentCenter/View/25558/2025-TAXESDelinquentAdvertisementNotice<br>https://www.catawbacountync.gov/site/assets/files/11653/delinquent_advertisement_list-hdr_2026.pdf |
| `counties_nc.nc_county_tax_foreclosure` | deed/notice?, detail-page | https://www.gastongov.com/669/Tax-Foreclosure-Sales<br>https://www.gastongov.com/671/Previous-Tax-Foreclosure-Sales |
| `counties_nc.nc_deq_dsca` | deed/notice?, detail-page, links | https://www.deq.nc.gov/about/divisions/waste-management/<br>https://www.deq.nc.gov |
| `counties_nc.nc_ecourts_divorce` | deed/notice?, img?, detail-page | https://portal-nc.tylertech.cloud/Portal/Home/Dashboard/29<br>https://portal-nc.tylertech.cloud/Portal |
| `counties_nc.nc_ecourts_estates` | deed/notice?, img?, detail-page | https://portal-nc.tylertech.cloud/Portal/Home/Dashboard/29<br>https://portal-nc.tylertech.cloud/Portal |
| `counties_nc.nc_ecourts_lis_pendens` | deed/notice?, detail-page | https://portal-nc.tylertech.cloud/app/NCJudgmentSearch/<br>https://portal-nc.tylertech.cloud/app/NCJudgmentSearchService/search |
| `counties_nc.nc_govdeals_real_property` | deed/notice?, img?, detail-page | https://maestro.lqdt1.com/search/list<br>https://www.transylvaniacounty.org/news |
| `counties_nc.nc_heir_estate_parcels` | deed/notice? | (see SOURCE_REGISTER.md) |
| `counties_nc.nc_its_public_tax` | - | https://tax.onslowcountync.gov/ITSPublicON/TaxBillSearch<br>https://www.bttaxpayerportal.com/ITSPublicGR2.0/TaxBillSearch |
| `counties_nc.nc_ptscloud_delinquent_tax` | deed/notice? | https://bcpwa.ncptscloud.com |
| `counties_nc.nc_rod_logan` | deed/notice?, img? | (see SOURCE_REGISTER.md) |
| `counties_nc.nc_rod_substitute_trustee` | deed/notice?, img? | https://buncombe-recordings.permitium.com/<br>https://www.nccourts.gov/ |
| `counties_nc.nchfa_reo` | detail-page, links | https://www.nchfa.com/home-buyers/properties-sale |
| `counties_nc.new_hanover_foreclosures` | deed/notice?, detail-page, links | https://www.nhcgov.com/345/Foreclosures |
| `counties_nc.polk_tax` | deed/notice? | https://www.polknc.gov/upcoming_auction.php |
| `counties_nc.rutherford_foreclosure` | detail-page, links | https://www.rutherfordcountync.gov/departments/ |
| `counties_nc.rutherford_tax` | detail-page, links | https://www.rutherfordcountync.gov/<br>https://www.rutherfordcountync.gov/departments/ |
| `counties_nc.rutherford_wildfire_tax` | detail-page | https://www.rutherfordcountync.gov/tax_search/index.php<br>https://d1ebsyxxbc7tep.cloudfront.net |
| `counties_nc.stokes_delinquent_tax` | deed/notice?, detail-page | https://kanialawfirm.com/tax-foreclosures/<br>https://kanialawfirm.com/tax-foreclosures/foreclosure-listings/ |
| `counties_nc.transylvania_delinquent_tax` | detail-page | https://tax.transylvaniacounty.org/TaxBillSearch<br>https://tax.transylvaniacounty.org |
| `counties_nc.transylvania_vacant` | deed/notice? | https://gis.transylvaniacounty.org/server/rest/services/Parcels/FeatureServer/2/query |
| `counties_nc.wake_tax_foreclosure` | deed/notice?, img?, detail-page, links | https://www.wake.gov/departments-government/tax-administration/real-estate/foreclosures<br>https://services.wake.gov/realestate/ |
| `counties_nc.wnc_rod_foreclosure_starts` | deed/notice?, img? | (see SOURCE_REGISTER.md) |
| `counties_nc.wnc_tax_foreclosures` | pdf?, detail-page, links | https://www.wataugacounty.org/<br>https://www.averycountync.gov/ |
| `counties_sc.abbeville_delinquent_tax` | detail-page | https://abbevillecountysc.com/delinquent-tax-collector/ |
| `counties_sc.aiken_delinquent_tax` | detail-page, links | https://sc-aikencounty.civicplus.com/309/Tax-Foreclosures |
| `counties_sc.anderson_acpass_deeds` | deed/notice?, img?, detail-page, links | https://acpass.andersoncountysc.org |
| `counties_sc.anderson_master_in_equity` | pdf?, deed/notice?, links | https://www.andersoncountysc.org/departments-a-z/master-in-equity/ |
| `counties_sc.anderson_sheriff` | detail-page | https://www.andersonsheriff.com/sheriff-sales |
| `counties_sc.bamberg_sheriff` | deed/notice?, detail-page | https://www.bambergcounty.sc.gov/public-safety/sheriffs-office |
| `counties_sc.barnwell_sheriff` | detail-page | http://www.barnwellcountysheriff.com/services.html |
| `counties_sc.beaufort_flc` | deed/notice?, detail-page, links | https://www.proxibid.com/Meares-Property-Advisors-Inc/<br>https://treasurerhelp.zendesk.com/hc/en-us/articles/ |
| `counties_sc.berkeley_paystar_tax` | deed/notice?, detail-page | https://berkeleycountysc.paystar.io/api/search<br>https://berkeleycountysc.paystar.io |
| `counties_sc.charleston_delinquent_tax` | pdf?, detail-page, links | https://charlestoncounty.gov/departments/delinquent-tax/<br>https://www.charlestoncounty.gov/departments/delinquent-tax/files/RP-Tax-Sale-Listing.pdf |
| `counties_sc.charleston_mie` | pdf?, deed/notice? | https://charlestoncounty.gov/foreclosure/runninglist.html<br>https://charlestoncounty.gov/departments/master-in-equity/rosters/ |
| `counties_sc.charleston_tax_sale_xlsx` | detail-page, links | https://www.charlestoncounty.gov/departments/delinquent-tax/files/tax_sale/RP-Tax-Sale-Listing.xlsx<br>https://www.charlestoncounty.gov/departments/delinquent-tax/files/tax_sale/MH-Tax-Sale-Listing.xlsx |
| `counties_sc.cherokee_delinquent_tax` | pdf?, deed/notice?, img?, detail-page | https://www.cherokeecountysc.gov/wp-json/wp/v2/media |
| `counties_sc.cherokee_rod` | deed/notice? | https://www.sclandrecords.com/cherokee/<br>https://www.sclandrecords.com/ |
| `counties_sc.chester_delinquent_tax` | detail-page | https://chestercountysc.gov/<br>https://www.chestercountysc.gov/treasurer/delinquent-tax-sale |
| `counties_sc.clarendon_tax_auction` | pdf?, deed/notice?, links | https://www.clarendoncountysc.gov/ |
| `counties_sc.colleton_tax_sale` | pdf?, detail-page, links | https://www.colletoncounty.org/delinquent-tax<br>https://www.colletoncounty.org/delinquent-tax/tax-sale |
| `counties_sc.darlington_delinquent_tax` | deed/notice?, detail-page | https://www.darcosc.com/government/treasurer/index.php |
| `counties_sc.dillon_delinquent_tax` | pdf?, deed/notice?, detail-page, links | https://www.dilloncountysc.org/departments/treasurer.php<br>https://www.dilloncountysc.org/ |
| `counties_sc.dillon_sheriff` | detail-page | https://dilloncountysc.org/services/public_safety/sheriffs_office.php |
| `counties_sc.dorchester_billtrax_delinquent_tax` | pdf?, deed/notice?, links | https://dorchestercountyscdelinquenttaxapi.billtrax.com<br>https://dorchestercountyscdelinquenttax.billtrax.com/ |
| `counties_sc.edgefield_delinquent_tax` | detail-page | https://edgefieldcounty.sc.gov/treasurer/ |
| `counties_sc.fairfield_delinquent_tax` | detail-page | https://www.fairfieldsc.com/departments/treasurer |
| `counties_sc.florence_delinquent_tax` | pdf?, detail-page, links | https://www.florenceco.org/offices/delinquent-tax/ |
| `counties_sc.georgetown_civicengage` | pdf?, links | https://georgetowncountysctax.com/<br>https://www.gtcountysc.gov |
| `counties_sc.greenville_delinquent_tax` | detail-page, links | https://www.greenvillecounty.org/appsAS400/Taxsale/ |
| `counties_sc.greenville_mie_adverts` | deed/notice?, detail-page | https://mie.greenvillejournal.com |
| `counties_sc.greenville_tax_distress` | deed/notice?, img?, detail-page | https://www.gcgis.org/arcgis3/rest/services/GreenvilleNJ/QueryLayers/MapServer<br>https://www.greenvillecounty.org/appsAS400/Taxsale/ |
| `counties_sc.greenwood_corebtpay_delinquent_tax` | deed/notice?, img?, detail-page | https://greenwoodco.corebtpay.com/egov/apps/payment/center.egov<br>https://greenwoodco.corebtpay.com/egov/apps/bill/pay.egov |
| `counties_sc.greenwood_delinquent_tax` | detail-page | https://www.greenwoodcounty-sc.gov/treasurer/delinquent-tax-sale |
| `counties_sc.horry_delinquent_xlsx` | pdf?, detail-page, links | https://www.horrycountysc.gov/media/b5af14ce/delinquent-list-on-website-081926.xlsx<br>https://www.horrycountysc.gov/departments/treasurer/delinquent-tax/ |
| `counties_sc.horry_flc` | detail-page, links | https://www.horrycountysc.gov/boards-and-commissions/<br>https://www.horrycountysc.gov/media/om1d2bwo/2025-flc-list-42126.xlsx |
| `counties_sc.kershaw_flc` | - | https://www.kershaw.sc.gov/treasurer/forfeited-land-commission |
| `counties_sc.lancaster_delinquent_tax` | pdf?, deed/notice?, detail-page, links | https://www.lancastercountysc.gov |
| `counties_sc.laurens_delinquent_tax` | deed/notice?, img?, detail-page | https://www.laurenscountysc.gov/departments/treasurer/delinquent_taxes.php |
| `counties_sc.lexington_flc` | detail-page, links | https://lex-co.sc.gov/treasurer/forfeited-land-commission<br>https://lex-co.sc.gov/departments/treasurer/forfeited-land-commission/ |
| `counties_sc.marlboro_delinquent_tax` | - | https://www.marlborocounty.sc.gov/government_/meeting_publications.php |
| `counties_sc.mccormick_flc` | pdf?, detail-page, links | https://www.mccormickcountysc.org/departments/treasurer.php |
| `counties_sc.newberry_delinquent_tax` | detail-page | https://www.newberrycounty.gov/delinquent-tax/tax-sales |
| `counties_sc.oconee_flc` | - | https://oconeesc.com/treasurer-home |
| `counties_sc.oconee_flc_assignment` | - | https://services1.arcgis.com/UOvRn2Rvzysthh3i/arcgis/rest/services/<br>https://oconeesc.com/auditor-home/forfeited-land |
| `counties_sc.oconee_forfeited_land` | - | https://services1.arcgis.com/UOvRn2Rvzysthh3i/arcgis/rest/services/<br>https://oconeesc.com/auditor-home/forfeited-land |
| `counties_sc.oconee_tax_sale` | - | https://oconeesc.com/delinquent-tax/sale-list |
| `counties_sc.pickens_delinquent_parcels` | deed/notice? | https://services1.arcgis.com/59960rq18IxUcAVI/arcgis/rest/services<br>https://www.co.pickens.sc.us/departments/delinquent_tax/index.php |
| `counties_sc.pickens_master_in_equity` | pdf?, deed/notice?, links | https://www.co.pickens.sc.us/departments/master_in_equity/sales_rosters.php<br>https://www.co.pickens.sc.us/ |
| `counties_sc.pickens_tax_sale` | pdf?, detail-page, links | https://www.co.pickens.sc.us/departments/delinquent_tax/index.php<br>https://www.co.pickens.sc.us/ |
| `counties_sc.qpaybill_delinquent_roll` | pdf?, deed/notice?, detail-page, links | https://dilloncountysctaxes.qpaybill.com/Taxes/<br>https://edgefieldcountysc.qpaybill.com/ |
| `counties_sc.richland_flc` | deed/notice?, detail-page, links | https://www.richlandcountysc.gov/Property-Business/Taxes/Delinquent-Taxes/Forfeited-Land-Available<br>http://schemas.openxmlformats.org/spreadsheetml/2006/main} |
| `counties_sc.saluda_delinquent_tax` | detail-page | https://saludacounty.sc.gov/departments/tax-collector/delinquent-tax-sale<br>https://saludacounty.sc.gov/departments/tax-collector |
| `counties_sc.sc_catalis_delinquent_roll` | deed/notice?, detail-page | https://d1ebsyxxbc7tep.cloudfront.net/data<br>https://pickenscountysctax.us |
| `counties_sc.sc_coastal_rosters` | deed/notice?, detail-page, links | https://www.horrycounty.org/parcelapp/rest/services/HorryCountyGISApp/MapServer/24/query<br>https://www.horrycounty.org/parcelapp/rest/services/HorryCountyGISApp/MapServer/22/query |
| `counties_sc.sc_county_rosters` | deed/notice?, detail-page, links | https://publicindex.sccourts.org |
| `counties_sc.sc_delinquent_tax_list` | pdf?, detail-page, links | https://cherokeecountysc.gov/delinquent-tax/tax-sale-bidders/ |
| `counties_sc.sc_des_brownfields` | deed/notice?, detail-page, links | https://des.sc.gov/programs/bureau-land-waste-management/<br>https://des.sc.gov/community/community-engagement/environmental-sites-projects |
| `counties_sc.sc_dew_lien_registry` | detail-page | https://uitax.dew.sc.gov/LienRegistry/<br>https://dew.sc.gov/benefit-lien-registry |
| `counties_sc.sc_dor_delinquent_taxpayers` | detail-page | https://mydorway.dor.sc.gov/ |
| `counties_sc.sc_flc` | pdf?, img?, detail-page, links | https://www.spartanburgcounty.gov/216/Tax-Collector<br>https://www.andersoncountysc.org/departments-a-z/treasurer/ |
| `counties_sc.sc_probate_net` | deed/notice?, img?, links | https://www.southcarolinaprobate.net/search/ |
| `counties_sc.sc_probate_notices` | deed/notice? | (see SOURCE_REGISTER.md) |
| `counties_sc.sc_public_index` | deed/notice?, detail-page | https://publicindex.sccourts.org/<County |
| `counties_sc.sc_public_index_lis_pendens` | deed/notice?, detail-page | https://publicindex.sccourts.org/<County |
| `counties_sc.sc_public_notices` | deed/notice?, detail-page | https://www.scpublicnotices.com/Search.aspx |
| `counties_sc.sc_rod_acclaim` | deed/notice? | (see SOURCE_REGISTER.md) |
| `counties_sc.sc_rod_cott` | deed/notice? | (see SOURCE_REGISTER.md) |
| `counties_sc.sc_state_tax_lien` | - | https://dor.sc.gov/delinquent-taxpayers<br>https://mydorway.dor.sc.gov/ |
| `counties_sc.sc_tax_delinquent` | pdf?, deed/notice?, img?, detail-page, links | https://1543.newstogo.us/editionviewer/default.aspx<br>https://www.andersoncountysc.org/departments-a-z/treasurer/ |
| `counties_sc.sc_ust_registry` | detail-page | https://apps.des.sc.gov/USTRegistry/ |
| `counties_sc.spartan_weekly_legals` | deed/notice?, detail-page, links | https://www.spartanweeklyonline.com |
| `counties_sc.spartanburg_city_condemned` | - | https://www.cityofspartanburg.org/robots.txt<br>https://www.cityofspartanburg.org/DocumentCenter/View/1901/ |
| `counties_sc.spartanburg_condemned` | - | https://maps.spartanburgcounty.org/server/rest/services/ |
| `counties_sc.spartanburg_delinquent_tax` | pdf? | https://www.spartanburgcounty.gov/DocumentCenter/View/11161/Real-Property-Tax-Sale-List-PDF<br>https://www.spartanburgcounty.gov/DocumentCenter/View/11161/ |
| `counties_sc.spartanburg_flc` | - | https://www.spartanburgcounty.gov/DocumentCenter/View/104130 |
| `counties_sc.spartanburg_master_in_equity` | pdf? | https://www.spartanburgcounty.gov/DocumentCenter/View/3392/Sale-Results<br>https://www.spartanburgcounty.gov/DocumentCenter/View/11824/Deficiency-Sale |
| `counties_sc.spartanburg_vacant` | - | https://services9.arcgis.com/HoRra3ATPLGmyjn6/arcgis/rest/services/<br>https://services9.arcgis.com/HoRra3ATPLGmyjn6/ |
| `counties_sc.sumter_surplus` | detail-page | https://www.sumtercountysc.gov/online_services/property/surplus_sales.php |
| `counties_sc.terry_howe_flc` | deed/notice? | https://terryhowe.com/wp-json/wp/v2/auctions |
| `counties_sc.union_delinquent_tax` | detail-page | https://gearupunionsc.com/officials/treasurer/ |
| `counties_sc.york_delinquent_tax` | pdf?, detail-page, links | https://www.yorkcountysc.gov/216/Tax-Collection |
| `counties_sc.york_overage_claims` | pdf? | https://www.yorkcountysc.gov/DocumentCenter/View/2828/OVERAGE-CLAIM-LIST |
| `counties_sc.zombie_properties` | deed/notice?, detail-page | (see SOURCE_REGISTER.md) |
| `law_firms.alaw` | deed/notice?, detail-page | https://www.alaw.net/foreclosure-sales/north-carolina/<br>https://www.alaw.net/foreclosure-sales/south-carolina/ |
| `law_firms.aldridge_pite` | deed/notice? | https://aldridgepite.com/sale-day-listings-selection/foreclosure-listings-north-carolina/<br>https://aldridgepite.com/disclaimer-north-carolina/ |
| `law_firms.bell_carrington` | deed/notice?, detail-page | https://docs.google.com/spreadsheets/d/e/<br>https://bellcarrington.com/foreclosure-sales/ |
| `law_firms.brock_scott` | deed/notice?, detail-page | https://www.brockandscott.com/foreclosure-sales/ |
| `law_firms.finkel` | pdf?, deed/notice?, img? | https://www.finkellaw.com/images/Webs.pdf<br>https://www.finkellawcharleston.com/images/Webs.pdf |
| `law_firms.hutchens` | deed/notice?, detail-page | https://sales.hutchenslawfirm.com/NCfcSalesList.aspx<br>https://sales.hutchenslawfirm.com/SCfcSalesList.aspx |
| `law_firms.ingle_firm` | deed/notice? | https://www.theinglefirm.com/Sales.aspx |
| `law_firms.kania` | detail-page, links | https://kanialawfirm.com/tax-foreclosures/foreclosure-listings/<br>https://kanialawfirm.com/wp-admin/admin-ajax.php |
| `law_firms.korn` | deed/notice? | https://www.kornlawfirm.com/foreclosure-sales/<br>https://www.kornlawfirm.com/sales/ |
| `law_firms.mcmichael_taylor_gray` | deed/notice? | https://app.powerbi.com/view |
| `law_firms.shapiro_ingle_powerbi` | deed/notice? | https://www.logs.com/nc-upcoming-sales-report.html<br>https://app.powerbi.com/view |
| `law_firms.zacchaeus` | deed/notice?, detail-page, links | https://www.zls-nc.com/listings<br>https://gis.moorecountync.gov/mooreinfo2010/ |
| `national.auction_bank_reo` | img?, detail-page, links | https://apiweb.realtybid.com/rest/RBIAPI/<br>https://bid.auctionnetwork.com/Auctions |
| `national.auction_dot_com` | img?, detail-page, links | https://www.auction.com/residential/nc/<br>https://www.auction.com/residential/sc/ |
| `national.bid4assets` | deed/notice?, detail-page | https://www.bid4assets.com/v5/search<br>https://www.bid4assets.com/api/search/process |
| `national.cash_buyer_deeds` | deed/notice?, img? | (see SOURCE_REGISTER.md) |
| `national.courtlistener_adversary` | deed/notice?, links | https://www.courtlistener.com |
| `national.courtlistener_bankruptcy` | deed/notice?, links | https://www.courtlistener.com/sign-up/<br>https://www.courtlistener.com/profile/api/ |
| `national.courtlistener_civil` | deed/notice?, links | https://www.courtlistener.com |
| `national.craigslist_fsbo` | detail-page | https://sapi.craigslist.org/web/v8/postings/search/full |
| `national.crexi_multifamily` | detail-page, links | https://www.crexi.com |
| `national.distressed` | deed/notice?, img? | (see SOURCE_REGISTER.md) |
| `national.epa_superfund` | detail-page | https://data.epa.gov/ef/seplan/<br>https://www.epa.gov/superfund/search-superfund-sites |
| `national.estate_sales` | deed/notice?, detail-page, links | https://www.estatesales.net<br>https://www.estatesale.com |
| `national.fannie_homepath` | img?, detail-page | https://homepath.fanniemae.com/cfl/property-inventory/search<br>https://homepath.fanniemae.com/ |
| `national.fdic_failed_banks` | detail-page, links | https://www.fdic.gov/bank-failures/failed-bank-list |
| `national.fema_disasters` | - | https://www.fema.gov/api/open/v2/DisasterDeclarationsSummaries |
| `national.first_citizens_reo` | links | https://www.firstcitizens.com/real-estate |
| `national.foreclosure_dot_com` | img?, detail-page | https://www.foreclosure.com/listing/search<br>https://www.foreclosure.com/listings/charlotte-nc/ |
| `national.freddie_homesteps` | img?, detail-page, links | https://www.homesteps.com/listing/search<br>https://www.homesteps.com/ |
| `national.govdeals` | deed/notice?, img?, detail-page | https://maestro.lqdt1.com/search/list<br>https://www.govdeals.com/auctions/item/detail/ |
| `national.gsa_surplus` | img?, detail-page, links | https://www.gsa.gov/real-estate/real-property-disposition/assets-identified-for-accelerated-disposition<br>https://www.gsa.gov/real-estate/real-property-disposition/ |
| `national.hibid_real_estate` | - | https://hibid.com/graphql<br>https://hibid.com |
| `national.homeharvest` | deed/notice?, img? | https://github.com/ZacharyHampton/HomeHarvest |
| `national.homepath_json` | img?, detail-page | https://homepath.fanniemae.com/cfl/property-inventory/search<br>https://homepath.fanniemae.com/ |
| `national.hubzu` | img? | https://www.hubzu.com/ |
| `national.hud_homestore` | img?, detail-page | https://www.hudhomestore.gov/searchresult<br>https://www.hudhomestore.gov |
| `national.hud_reac_inspection` | detail-page | https://www.hud.gov/sites/default/files/Housing/documents/MF-Inspection-Report.xls<br>https://www.hud.gov/sites/default/files/Housing/documents/ |
| `national.hud_section8_contracts` | - | https://www.hud.gov/hud-partners/multifamily-assist-section8-database<br>https://www.hud.gov/sites/dfiles/Housing/documents/ |
| `national.irs_treasury` | detail-page, links | https://www.irsauctions.gov/auction/items<br>https://www.irsauctions.gov |
| `national.jail_bookings` | img?, detail-page | http://mugshots.spartanburgsheriff.org/<br>https://buncombecountyso.policetocitizen.com|23 |
| `national.landandfarm` | img?, detail-page | (see SOURCE_REGISTER.md) |
| `national.landsofamerica` | img?, detail-page | (see SOURCE_REGISTER.md) |
| `national.landwatch` | img? | (see SOURCE_REGISTER.md) |
| `national.legacy_obituaries` | detail-page, links | https://www.legacy.com |
| `national.liensnc` | deed/notice?, detail-page, links | https://www.liensnc.com |
| `national.loopnet` | detail-page | https://www.loopnet.com/<br>https://www.loopnet.com |
| `national.nc_sos_ucc` | deed/notice? | https://www.sosnc.gov/online_services/search/by_title/_uniform_commercial_code |
| `national.nc_upset_bids` | detail-page, links | https://kanialawfirm.com/tax-foreclosures/foreclosure-listings/<br>https://kanialawfirm.com/wp-admin/admin-ajax.php |
| `national.opencorporates` | - | https://api.opencorporates.com/v0.4/companies/search |
| `national.probate_foreclosure_leads` | deed/notice? | (see SOURCE_REGISTER.md) |
| `national.propwire` | - | (see SOURCE_REGISTER.md) |
| `national.realtor_foreclosures` | deed/notice?, img? | (see SOURCE_REGISTER.md) |
| `national.sc_public_index` | deed/notice?, detail-page, links | https://publicindex.sccourts.org/<county<br>https://jcmsweb.charlestoncounty.org/PublicIndex/ |
| `national.sc_sos_entity` | detail-page, links | https://businessfilings.sc.gov/BusinessFiling/Web/Reporting/SearchByName |
| `national.seeclickfix` | - | https://developer.seeclickfix.com/<br>https://seeclickfix.com/api/v2/issues |
| `national.sheriff_sales` | pdf?, deed/notice?, links | https://www.brunswicksheriff.com<br>https://www.charlestoncounty.org |
| `national.stealth_handoff` | - | (see SOURCE_REGISTER.md) |
| `national.tranzon` | img?, detail-page, links | https://www.tranzon.com/online-real-estate-auctions.aspx |
| `national.trulia` | deed/notice?, img?, links | https://www.trulia.com/foreclosures/<br>https://www.trulia.com/foreclosures/Charlotte,NC/ |
| `national.usda_properties` | img?, detail-page, links | https://usdaproperties.com/property/<state<br>https://www.usdaproperties.com/property/sc/county/<county-slug |
| `national.va_acquired` | img?, detail-page | https://www.va.gov/va-forms/real-property/properties/<br>https://www.benefits.va.gov/homeloans/property/property.asp |
| `national.xome` | deed/notice?, img?, detail-page, links | https://www.xome.com/auctions |
| `national.zillow_bulk` | img?, detail-page | (see SOURCE_REGISTER.md) |
| `national.zillow_foreclosures` | deed/notice?, img?, detail-page | (see SOURCE_REGISTER.md) |
| `newspapers.aiken_standard` | deed/notice?, detail-page | https://www.postandcourier.com/aikenstandard/classifieds/search/ |
| `newspapers.berkeley_independent` | deed/notice?, detail-page | https://www.postandcourier.com/berkeley-independent/classifieds/community/announcements/ |
| `newspapers.carolina_coast` | deed/notice?, detail-page | https://www.carolinacoastonline.com/classifieds/ |
| `newspapers.coastland_times` | deed/notice?, img?, detail-page, links | https://www.thecoastlandtimes.com |
| `newspapers.daily_courier` | deed/notice?, detail-page, links | https://www.thedigitalcourier.com/classifieds/community/announcements/legal/<br>https://www.thedigitalcourier.com |
| `newspapers.hendersonville_lightning` | deed/notice? | https://www.hendersonvillelightning.com/legal-ads/130-foreclosures.html |
| `newspapers.index_journal` | deed/notice?, detail-page | https://www.indexjournal.com/classifieds/community/announcements/legal/ |
| `newspapers.journal_scene` | deed/notice?, detail-page | https://www.postandcourier.com/journal-scene/classifieds/community/announcements/ |
| `newspapers.post_and_courier` | deed/notice?, detail-page | https://www.postandcourier.com/classifieds_new/community/announcements/ |
| `newspapers.shelby_star` | deed/notice?, detail-page, links | https://www.shelbystar.com<br>https://www.shelbystar.com/ |
| `newspapers.tryon_bulletin` | deed/notice?, links | https://tryondailybulletin.com<br>https://tryondailybulletin.com/ |
| `public_notices.funeral_home_rss` | deed/notice? | (see SOURCE_REGISTER.md) |
| `public_notices.gannett_obituaries` | deed/notice?, detail-page | (see SOURCE_REGISTER.md) |
| `public_notices.nc_notices_counties` | deed/notice?, detail-page | https://www.ncnotices.com/Search.aspx |
| `public_notices.ncnotices` | deed/notice?, img?, detail-page, links | https://www.ncnotices.com/ |
| `public_notices.publicnoticesc` | deed/notice?, img?, detail-page | https://www.scpublicnotices.com/(S(<br>https://www.scpublicnotices.com/Search.aspx |
| `reo.treasury_seized` | - | https://www.treasury.gov/auctions/treasury/rp/realprop.shtml |
| `reo.usda_rd` | img?, detail-page, links | https://www.resales.usda.gov/resales/public<br>https://www.resales.usda.gov |
| `reo.vrm_va_reo` | img?, detail-page, links | https://vrmproperties.com/<br>https://vrmproperties.com |
