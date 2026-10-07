# Extraction audit 2026-10-07: fetched-but-dropped and never-fetched data

Goal: every scraper captures everything its source shows for each item (list columns, data
behind expandable rows, detail pages, popouts, linked PDFs/images, every listing on every page).
This pass covers the 30 highest-volume sources on the live board (`run_meta.json`
`by_source_on_board`, 350,013 rows) plus the sources the earlier docs flag
(`docs/extraction_gaps.md`, `docs/SOURCE_EXTRACTION_AUDIT.md`, `docs/EXTRACTION_AUDIT_PLAN.md`
Tier 1, the 2026-09-29 completeness audits). Field NAMES and COUNTS only, never values.

Method: read each scraper; one polite live look at its source (ArcGIS `?f=json` field list and
`returnCountOnly` with the scraper's own `where`; JSON hit/field lists; xlsx/PDF headers; HTML
columns and detail links), at most about 12 requests per host, at least 1.6 s apart, ordinary
browser User-Agent, no browser launched; board-side fill from a constant-memory
`board_stream.iter_board_rows()` profile; and a static scan of every scraper's `raw` keys against
`web_artifact.RAW_KEEP` (a key not in RAW_KEEP is dropped at publish). Sources behind a CAPTCHA,
login, paywall, WAF/bot check or click-through are listed as walled and were not touched.

## 1. Inventory

Columns: board rows | page type | paging complete? | fields the source shows that the row did
not carry (before this pass) | RAW_KEEP drop | status.

| source | rows | page type | paging | dropped / never-fetched fields (names) | RAW_KEEP | status |
|---|---|---|---|---|---|---|
| counties_generic.liensnc / liensnc | 39,644 / 5,449 | login-gated site; rows come from operator-saved pages (`scripts/ingest_liensnc.py`) | n/a | n/a | none | WALLED (login, terms); scraper `disabled` |
| state_contamination.nc_ust_incidents | 39,642 | ArcGIS FeatureServer, offset pages of 1,000 | yes (44,371 match the where; 1,366 more have a blank/misspelled county); offset order was on IncidentNumber, empty on ~10k rows | USTNum, FacilID, Comm, ConfRisk, LandUse, Reg, RRADate, RRARisk, RRARank, RRAAbate | none | FIXED |
| counties_sc.qpaybill_delinquent_roll | 33,180 | ASP.NET search grid (25/page, owner-prefix enumeration) + per-bill detail page | NO: no stated total; prefix depth 4 / 2,500 requests / 480 s per county; 33-48 prefixes unread in 4 counties on 9/14 | detail page only in an opt-in pass (detail on 42% of rows): Total Appraisal, assessment ratio, assessed value, acres, legal, penalty/cost/fees; detail labels never parsed: lblTaxYr, lblDistrict, lblCity, lblDesc2; per-year amounts collapsed | none | remaining |
| counties_nc.gaston_vacant | 21,797 | ArcGIS MapServer, pages of 2,000 | yes (21,759 stated) | DEEDQUAL_CODEDESC, EXEMPT_COD, PRVYRNAME1/2, FLOODAREA; owner mailing kept only in `raw.gaston_gis` (the scorer reads `raw.owner_mailing`) | none | FIXED |
| counties_nc.nc_ptscloud_delinquent_tax | 19,548 | JSON API handing out a per-tenant CSV | yes | per-year bills collapsed to the newest (TAX_YEAR, BILL_NUMBER, BILL_AMOUNT, BILL_DUE_AMT, INTEREST_DUE, TOTAL_DUE_AMOUNT, BILL_STATUS, BILL_DUE_DATE per year) | none | FIXED |
| counties_sc.sc_ust_registry | 16,104 | static HTML list (one POST per county) + per-row detail page | yes (no stated total) | Details link (buildable from Permit); detail page: tank counts and status, releases, land owner, last inspection, category | none | remaining (detail not fetched by design: it carries phones; ~18.4k requests) |
| counties_nc.lincoln_vacant | 16,068 | ArcGIS MapServer (1,000/page, follows exceededTransferLimit) | yes (14,718 stated) | LANDVALUE, ACRE, MAPPEDACRE, LANDEFERRED, QUALIFIEDCODE, ZONING, TAXYEAR; standard mailing keys; parcel_id is the 5-6 char PARCELID (nulled by validation) while the 10-digit PIN is in raw | none | FIXED (fields); parcel identity remaining |
| counties_nc.transylvania_vacant | 10,972 | ArcGIS FeatureServer | yes (11,109 stated) | low-value only; LEGAL_ADDR (a legal description) is used as street_address | none | remaining (accuracy) |
| counties_nc.nc_ecourts_lis_pendens | 10,761 | open Tyler Judgment Search JSON | at risk: 80,191 hits in 90 days vs a 90,000 page cap | debtor nameID, searchBusinessName; hits whose causeOfActionDesc is "Multiple" (~14%) are dropped whole | none | remaining |
| counties_nc.nc_county_pdf_delinquent_tax | 8,582 | PDF notices (Lincoln, Catawba, McDowell) | Catawba first-wins drops 42 bill rows; 16 McDowell lines unparsed | McDowell owner sits on the line BEFORE the parcel line; ~1,716 rows carry the wrong owner | none | remaining (correctness) |
| counties_sc.sc_dew_lien_registry | 8,288 | 17 MB export, cross-reference only | capped at 8,000 of ~29,341 | board rows lack the whole `sc_dew_lien_registry` block | none | remaining (disabled by design; stale rows) |
| state_contamination.nc_dam_safety | 7,612 | ArcGIS FeatureServer | yes (7,538 stated); ordered by non-unique Dam_Name | CONDITION_ASSESSMENT, NOD_RESOLVED, NOD_DEADLINE_DATE, NOV_RESOLVED, DSO_RESOLVED, DSO_DEADLINE, LAST/NEXT_INSPECTION_DATE, STATE_ID, EAP, EAP_DATE, HAZARD_DATE, YEAR_CONSTRUCTED, DAM_TYPE, DAM_PURPOSE, SURFACE_AREA | none | FIXED |
| counties_nc.albemarle_observer_tax_lists | 7,511 | WordPress REST posts | posts complete (35) | one county's 2026 list (~1,820 rows, dot-leader text) has no parser | none | remaining |
| counties_nc.nc_ecourts_divorce | 5,777 | open Judgment Search JSON | as lis pendens | judgmentType, caseCategoryKey, owner_name; "Multiple" rows dropped | none | remaining |
| counties_sc.sc_public_index | 5,540 | court index behind an F5 challenge + terms | grid caps at 250/search | case detail never fetched | none | WALLED |
| counties_nc.rutherford_tax | 5,109 | xlsx (6 columns, all captured) | yes; file dated 1/31/2026, not reposted | 2,622 six-digit parcel ids nulled by validation | none | remaining |
| city_websites.charlotte_open_data | 4,538 | ArcGIS | yes (3,139 open) | DateClosed, Conclusion (would retire ~1,400 closed cases) | none | remaining |
| counties_sc.spartanburg_vacant | 4,438 | ArcGIS FeatureServer | yes (5,014 stated, government owners dropped) | StreetZip (situs zip), LegalDescr, Acreage, DEEDACREAG, PreviousAp/Ta/As, DeedBook, DeedPage, Instrument, PreviousOw, CDUC, Assessment, ReviewDate, AccountNum, LandSizeDe, StreetComm, Utility1, RoadType, Topo | none | FIXED |
| counties_nc.nc_heir_estate_parcels | 4,437 | 19 county ArcGIS layers + NC OneMap fallback | NO: `_PER_COUNTY_CAP=80`, no offset/order (~10,868 match, at most 1,243 return); `NOT LIKE` on a nullable column drops NULL-second-owner rows; 20 s timeout returns silently | values, acreage, centroid, sale, deed and card-link columns already fetched with outFields=* but unmapped | none | remaining |
| counties_nc.buncombe_elderly | 4,322 | ArcGIS MapServer | yes (4,352 stated) | propcard, LandValue, BuildingValue, AppraisedValue, ImprovementValue, SubName, SubLot, SubBlock, SubSect, PlatBook, PlatPage, Stamps, Reason, Improved, NeighborhoodCode, Township | none | FIXED |
| counties_nc.rutherford_wildfire_tax | 3,435 | Sturgis Wildfire API | n/a | interest, penalty, total cost, tax relief value, deferred/use/exempt values, last payment, situs city/zip, line items | none | WALLED today (CloudFront 403); 914 rows collapse to the shared URL key |
| counties_sc.horry_delinquent_xlsx | 3,009 | two xlsx workbooks since October 2026 | NO: one file read; the MMDDYYYY stamp was misread so the real-estate list (2,720 PINs) would be skipped | FLC Bid Amount (every row); sale-list year and kind | none | FIXED |
| arcgis_distress.greenville_unpaid_tax_parcels | 2,722 | ArcGIS MapServer | yes (2,310 live) | SLPRICE, DEEDDATE, CUBOOK, CUPAGE, FAIRMKTVAL, LANDVAL, BLDGVAL, SQFEET, BEDROOMS, BATHRMS, HALFBATH, POWNNM, GIS_ACRES, NAMECO, SUBDIV, LANDUSE, IMPROVED; owner mailing STREET/CITY/STATE/ZIP5 | none | FIXED |
| counties_sc.charleston_tax_sale_xlsx | 2,402 | xlsx (RP + MH) | yes (9 of 9 columns) | none | none | complete |
| counties_sc.berkeley_paystar_tax | 2,364 | JSON list + one detail call per invoice | yes (3,037 live) | TaxesDue, TaxPenalties, DLQPenalties, TaxTotal, BillTotal, TaxesDuePenalty1-3, Penalty1-3Date, HomesteadExemption/Percentage/ApplicationYear, OT*/Ag* values, building/lot counts, codes, districts, account/receipt; appraisal summed QR only; one row per invoice (years not grouped) | none | FIXED (fields); year grouping remaining |
| nc_ecourts_judgments | 2,244 | legacy one-shot `scripts/scrape_ncecourts.py` ingest | frozen | includes evictions, no status filter | n/a | remaining (legacy) |
| arcgis_distress.spartanburg_property_cleanup | 2,213 | ArcGIS (last edited 2024-11) | yes | contact fields (rightly excluded), PlaceName | none | complete (stale layer) |
| counties_nc.nc_its_public_tax | 2,199 | jqGrid list API | yes (73 pages < 400 cap) | no mailing/detail on rows; only 3 tax years read | none | complete for what the page shows |
| epa_frs.sems / epa_frs.acres | 2,022 / 1,586 | EPA JSON, one GET per state/program | yes | 64 SEMS rows dropped on county "NOT DEFINED", 19 ACRES on a " COUNTY" suffix; no coordinates/NPL status in this table | none | remaining |
| national.sc_public_index | 1,999 | as sc_public_index | | parser reads 6 of 10 grid columns; role is captured but owner/defendant/plaintiff are empty on all rows | none | WALLED (code-only notes) |
| counties_sc.florence_delinquent_tax | 1,829 | fixed-width PDF | yes | owner_name and acreage not first-class | none | remaining (small) |
| counties_sc.spartanburg_delinquent_tax | 1,770 | PDF | n/a | heir/co-owner change not yet on the board | none | WALLED today (Cloudflare challenge) |
| counties_sc.charleston_delinquent_tax | 1,760 | PDF | parser reads ~834 of ~2,416 rows of the RP PDF; both PDFs are last year's list | Tag | none | remaining (stale lane) |
| counties_sc.spartanburg_condemned | 1,754 | ArcGIS CAMA layer | yes (1,778) | StreetCommunity, LegalDescription, SaleDate, CurrentAssessed*, DeedBook, DeedPage, InstrumentNumber, PreviousOwnerName, Units, Acreage, building facts | condemned_signal | FIXED |
| counties.column_legal_notices | 1,564 | JSON API | NO for big counties: one 250-row page per county/type/120 days (one county has 391) | full notice text past 800 chars; personal-representative mailing and attorney block; `pdfurl` on 96 of 1,534 rows | none | remaining |
| state_contamination.nc_inactive_hazardous | 1,550 | ArcGIS | yes (2,025) | Update_Dat | none | FIXED |
| national.distressed (homeharvest_distressed) | 1,440 | library DataFrame | `past_days=120` drops long-on-market listings | last_sold_date/price, pending_date, last_status_change_date, hoa_fee, unit, mls_id | none | remaining |
| counties_sc.pickens_delinquent_parcels | 1,403 | 9 ArcGIS layers | NO: the 2026 cycle layer (801 parcels) not wired | NAME2, TAXAREA, SubDivisio, ACCOUNTNO (unused) | 12 sub-keys of `pickens_delinquent` (tuple allowlist) | FIXED (layer + RAW_KEEP) |
| arcgis_distress.new_hanover_demolition_permits | 1,378 | ArcGIS | yes (1,745); where admits void/withdrawn/interior | DESCRIPTION, PERMIT_TYPE, ISSUE/FINALED/EXPIRATION/LAST_INSPECTION_DATE, UNIT, MAIN_ZONE, Lat/Lon | none | FIXED (fields); filter remaining |
| public_notices.nc_notices_counties | 786 | paged ASP.NET grid; Details.aspx reCAPTCHA | unknown: page caps 6/3/2 with no warning when more pages exist | all grid columns captured | none | grid fine; detail WALLED |
| counties_sc.sc_public_notices | 768 | paged grid; detail walled | probably not for the tax lane (3-page cap) | owner_name not set | none | remaining (small) |
| counties_sc.sc_probate_notices | 909 | WordPress JSON + articles | NO for one paper (cap applied before de-dupe; 20 posts unread), another fetches 120 of 557-718 hits | estate attorney name/address, post date | none | remaining |
| counties_sc.terry_howe_auctions | 351 | WordPress API + detail pages | 527 posts < 600 cap; detail only for newest 30 | none parsed beyond | whole `terry_howe_auction` block | FIXED (RAW_KEEP) |
| counties_sc.greenville_mie_adverts | 324 | sitemap + advert pages | NO: 773 sitemap URLs vs a 400 cap | plaintiff attorney/firm contact, judgment PDF link, deposit %, bid-stays-open, mortgage book/page | none | remaining |
| law_firms.kania (+ national.nc_upset_bids) | 177 (+29) | table behind a disclosure popup (checkbox + Submit); scrapers call the data endpoint directly | n/a | all 11 columns captured | none | COMPLIANCE QUESTION (see 4) |
| law_firms.zacchaeus | 43 | browser clicks "I AGREE" | n/a | Notice of Sale button | none | COMPLIANCE QUESTION (see 4) |
| law_firms.shapiro_ingle_powerbi, brock_scott, hutchens | 77 / 45 / 43 | Power BI / paged table / grid | yes | firm file number and SC deficiency only in description | none | complete |
| counties_sc.anderson_master_in_equity / pickens_master_in_equity | 28 / 20 | PDFs | only newest list; a results PDF and a deficiency-sale PDF not matched | hammer prices; real sale date/time | none | remaining |
| counties_nc.henderson_foreclosure_parcels | 14 | ArcGIS roster | yes | | whole `tax_foreclosure` block | FIXED (RAW_KEEP) |
| national.crexi_multifamily | 0 | Cloudflare-challenged pages | n/a | detail pages | n/a | WALLED |

## 2. Ranked fix list (rows affected x useful fields lost) and the 12 fixed

Ranked by board rows x fields recovered (approximate products: 1 ~380k, 2-3 ~125-130k each, 4 ~88k, 5 ~84k, 6 ~69k, 7 ~62k, 8 ~49k, 9 ~33k, 10 ~27k, 11-12 ~14k each). Live proofs are single bounded runs (the first page,
or the whole source when it is one or two requests), HEAD code ("before") against the working
tree ("after"), same session. Counts only.

| # | fix | rows x fields | live proof (before -> after) | commit |
|---|---|---|---|---|
| 1 | state_contamination: 10 UST, 16 dam, 1 hazardous columns; paging ordered by each layer's objectIdField; drop_sensitive on the attribute bag | ~44k x 6 + 7.5k x 16 + 2k x 1 | first page per layer: UST raw fields 16 -> 22, dams 18 -> 34, hazardous 12 -> 13 (same rows) | 68b3f84a |
| 2 | gaston_vacant: DEEDQUAL_CODEDESC, EXEMPT_COD, PRVYRNAME1/2, FLOODAREA; standard top-level owner_mailing | ~21.8k x 5 + 14.5k mailing | first page (2,000): raw fields 18 -> 31; owner_mailing 0 -> 1,994 | a6641c5d |
| 3 | lincoln_vacant: LANDVALUE, ACRE, MAPPEDACRE, LANDEFERRED, QUALIFIEDCODE, ZONING, TAXYEAR; standard mailing keys | ~14.7k x 9 | first page (1,000): Listing fields 15 -> 17 (acreage, zoning 0 -> 1,000), raw fields 29 -> 38 | f82d5189 |
| 4 | nc_ptscloud_delinquent_tax: every delinquent year kept (years_unpaid, years_delinquent, oldest_year, unpaid_bill_amount, by_year[]); feeds raw.tax_owed via enrichment_tax_owed | ~17.6k x 5 | one tenant export (1,080 rows): raw fields 17 -> 22; rows stating 2+ years 0 -> 524 | 08d7d432 |
| 5 | spartanburg_vacant: 20 columns (situs zip, legal, acreage, values, deed, prior owner, site facts) | ~4.4k x 19 | first page (960): Listing 21 -> 24 (legal 0 -> 960, zip 0 -> 583, acreage 0 -> 204), cama_specs 9 -> 25 | 6686b5fa |
| 6 | buncombe_elderly: propcard, land/building/appraised value, plat, subdivision, stamps | ~4.3k x 16 | first page (2,000): raw.gis_exempt 3 -> 19 fields (propcard on 2,000) | 406a1062 |
| 7 | berkeley_paystar_tax: bill breakdown, homestead exemption, all-class appraisal, districts | ~2.4k x 26 | 10 invoices (8 kept): raw fields 12 -> 38, appraised_value 1 -> 2 of 8 | 4fb61f14 |
| 8 | arcgis_distress Greenville: 17 columns + owner mailing (kept out of the property block) | ~2.7k x 18 | first page (1,000): raw +17 fields, owner_mailing 0 -> 1,000 | f8e49a47 |
| 9 | spartanburg_condemned: situs city, legal, assessed value, deed/sale facts; `condemned_signal` published | ~1.75k x 19 | one request (1,764 rows): Listing 20 -> 24 (city 0 -> 1,764, legal 0 -> 1,764, assessed 0 -> 1,722), cama_specs 11 -> 26 | a9b501d5 (*) |
| 10 | horry_delinquent_xlsx: both October workbooks (8-digit date stamp), FLC Bid Amount -> opening_bid + tax_owed | 2.7k rows kept + 3.6k x 3 | whole source: 842 rows / 9 raw fields -> 3,562 rows / 12 (flc_bid_amount on all 3,562) | ac602822 |
| 11 | arcgis_distress New Hanover: permit description/type/dates/unit/zoning + own Lat/Lon (new Layer.lat_field/lon_field) | ~1.4k x 10 | first page (994): raw 12 -> 22, latitude/longitude 0 -> 941 | f8e49a47 |
| 12 | pickens_delinquent_parcels: 2026 cycle layer; 8 more published sub-keys | 801 parcels + 1.4k x 8 | whole source: 2,161 -> 2,560 rows (777 on the 2026 roll, 399 new); published fields 6 -> 14 | 03f6428a |

(*) The RAW_KEEP entries for `condemned_signal`, `terry_howe_auction` and `tax_foreclosure`, and
the RAW_KEEP scan's new handling of annotated `raw: dict = {...}` assignments
(`tests/test_raw_keep_covers_enrichers.py`, which is how those three went unregistered), were
swept into commit bb9355a2 by a concurrent session that staged the same files; the content is
the same.

Tests: 43 new test functions across 11 files (canned fixtures, made-up names), 4 existing tests
updated where they pinned an exact shape that grew. The touched files run 433 passed, 2 skipped.

## 3. What remains, with the reason

| source | what is still dropped | why not fixed in this pass |
|---|---|---|
| counties_sc.qpaybill_delinquent_roll | detail page for ~19k rows; 4 unparsed detail labels; per-year amounts; prefix enumeration limits | needs a run decision: a detail pass for every row is ~19k requests (8+ hours at 1.6 s); parsing 4 labels only helps the 42% already detailed |
| counties_nc.lincoln_vacant | parcel_id is the short PARCELID (nulled), PIN unused as identity | `board_persist` restores this source's prior identity from PARCELID and refuses two ids from one source: switching to PIN would duplicate every row on the next merge. Needs a coordinated identity migration (`_SOURCE_PARCEL_FIELDS` + the merge) |
| counties_nc.nc_heir_estate_parcels | ~9.6k matching parcels never fetched (cap 80/county); NULL-unsafe `NOT LIKE`; value/acreage/centroid/sale/deed/link columns unmapped | the cap is the source's existing cap (rule: keep caps); the mapping needs per-county field names for 19 layers; a null-safe SQL where drew a 403 from one county host, so the filter must move into Python |
| nc_ecourts lis pendens / divorce | "Multiple" cause rows (~14% of hits) dropped; page cap headroom 11% | the cause is unknown without the case page (Smart Search is CAPTCHA-walled); admitting them blindly adds non-foreclosure cases. Raising MAX_PAGES is a cap change |
| counties_nc.nc_county_pdf_delinquent_tax | wrong owner on ~1,716 McDowell rows; 42 Catawba bills; 16 unparsed lines | correctness fix to the PDF parser, next pass |
| counties_nc.albemarle_observer_tax_lists | one county's 2026 list (~1,820 rows) | needs a new dot-leader text parser |
| counties.column_legal_notices | text past 800 chars; personal-representative address/attorney; Guilford window cut at 250 | the PR's address is a private individual's address, a new category for the public dashboard: owner decision; paging needs a query split |
| counties_sc.greenville_mie_adverts | 373 oldest sitemap URLs; attorney contact, judgment PDF, deposit, mortgage book/page | cap is the source's existing cap; parsing is next pass |
| counties_sc.sc_ust_registry | detail page (tanks, releases, inspection) | detail carries owner/operator phones (module policy: never stored) and is ~18.4k requests; a capped subset (estate-owned rows) is possible |
| counties_sc.berkeley_paystar_tax | invoices not grouped by parcel (years) | structural change to one row per parcel, next pass |
| counties_nc.transylvania_vacant | LEGAL_ADDR published as street_address on ~8k rows | a removal/accuracy change, not additive; flagged |
| arcgis_distress.new_hanover_demolition_permits | where admits Void/Withdrawn/Interior permits | tightening the filter removes rows; status now in raw so the scorer can filter |
| national.distressed | last sold, pending/status dates, hoa, unit, mls id; 120-day window | next pass (window is a cap) |
| epa_frs.sems / acres | 83 rows dropped on county name variants; coordinates, NPL status | next pass; per-facility detail host rate-limits (429) |
| counties_sc.charleston_delinquent_tax | re-emits last year's list; parser reads ~834 of ~2,416 RP rows | the current list is the xlsx lane (complete); retire or date-gate this lane: owner call |
| counties_sc.sc_dew_lien_registry | 8,288 stale rows without the registry block | disabled by design (cross-reference only); purge/refresh is a board action |
| counties_nc.rutherford_tax | 2,622 six-digit parcel ids nulled; file 8 months old | identity change (same risk as Lincoln) |
| state_contamination | open/closed incident fields can mix when two incidents share an address and merge | dedupe-merge behavior, outside the scraper |
| city_websites.charlotte_open_data | closed cases stay on the board | retirement logic, not extraction |
| counties_sc.florence_delinquent_tax, sc_public_notices | owner_name not first-class | small, next pass |
| anderson / pickens MIE, nc_upset_bids | results/deficiency PDFs, real sale time | small volume, next pass |
| WALLED, not touched | liensnc (login, terms), sc_public_index x2 (F5 + terms), rutherford_wildfire_tax (CloudFront 403 today), spartanburg_delinquent_tax PDF (Cloudflare today), ncnotices Details.aspx and SC notice details (reCAPTCHA), crexi (Cloudflare), Georgetown Catalis (CDN 403) | walls |
| not individually audited | the rest of `docs/SOURCE_EXTRACTION_AUDIT.md`'s TODO table | below the top-30 volume line; covered by the 2026-10-03/04 batch audit |

## 4. Decisions for the owner

1. Kania (`law_firms.kania`, ~177 rows, and most of `national.nc_upset_bids`): the listings page
   opens a disclosure popup (checkbox + Submit) in front of the table; both scrapers read the
   site's data endpoint directly. Zacchaeus (`law_firms.zacchaeus`, 43 rows) clicks "I AGREE" in a
   browser, and its code says aldridge_pite uses the same consent pattern. Under the 2026-09-20
   rule a click-through is a wall. Not disabled here (instruction); flagged for the wall audit.
2. Pickens: the 2025 posting layers are still marked current beside the new 2026 layer, so
   `pre_sale` is true for parcels on either cycle. Say when the 2025 cycle should stop counting.
3. qpaybill detail pass for every row (~19k polite requests) or keep it opt-in.
4. Lincoln (and Rutherford) parcel identity: approve a coordinated PIN migration.
5. Column notices: whether a personal representative's mailing address may be published.
