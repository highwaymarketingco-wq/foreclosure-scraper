# EXTRACTION AUDIT PLAN — comprehensive, all 139 unaudited sources

**Companion to:** `docs/SOURCE_EXTRACTION_AUDIT.md` (the generated TODO table)
**Goal:** For every scraper, confirm with eyes on the live source that it captures
EVERYTHING of value: all listing fields, all PDFs (via `harvest_document_links` +
`stamp_documents`), all images, and all detail/external links. Then wire what's
missing and verify the fix returns real data.

---

## How sources are grouped (by infrastructure pattern)

Sources that share the same fetch + parse infrastructure have the same audit
procedure. Working by pattern (not by slug) means we learn the extraction shape
once and apply it across the whole batch. 14 patterns, 139 sources:

| # | Pattern | Count | Audit focus |
|---|---|---|---|
| A | County HTML pages | 35 | PDF harvest, detail-page follow, field regex |
| B | Auction/REO platforms | 18 | Detail-page follow, image capture, field extraction |
| C | ArcGIS REST layers | 15 | Layer schema, attachment endpoints, field mapping |
| D | Specialty/other | 14 | Varies per source; each is unique |
| E | Law firm sites | 12 | PDF harvest, detail-page follow, field extraction |
| F | JSON/XML API | 12 | Response field coverage, doc URLs in payload |
| G | Newspaper sites | 8 | PDF harvest, full notice text, detail-page follow |
| H | Public notice/obituary | 7 | Full notice text, probate case fields, detail links |
| I | ROD vendor adapters | 6 | RodDoc field mapping, document image URLs |
| J | eCourts (WAF-walled) | 3 | Manual saved-HTML lane; field extraction from HTML |
| K | Courtlistener API | 3 | API field coverage, docket document links |
| L | PDF parsers | 3 | Column mapping, table detection, full text fields |
| M | Contamination/EPA | 2 | API field coverage, facility detail URLs, lat/lng |
| N | CSV parsers | 1 | Column mapping, field coverage |

---

## Priority tiers (execution order)

### TIER 1 — highest revenue impact (42 sources)

These sources carry actual foreclosure/tax-sale listings with sale dates,
addresses, and dollar amounts. Every missed field or PDF here is a lost lead.

**1A. County HTML pages with PDF rosters (20 sources)**
County tax-sale and MIE pages almost always link PDF rosters (sale lists,
bidder info, deficiency lists). The `harvest_document_links()` + `stamp_documents()`
call is the single most common miss.

- `counties_sc.anderson_master_in_equity`
- `counties_sc.charleston_delinquent_tax`
- `counties_sc.charleston_mie`
- `counties_sc.cherokee_delinquent_tax`
- `counties_sc.colleton_tax_sale`
- `counties_sc.pickens_master_in_equity`
- `counties_sc.pickens_tax_sale`
- `counties_sc.spartanburg_delinquent_tax`
- `counties_sc.spartanburg_master_in_equity`
- `counties_sc.spartanburg_flc`
- `counties_sc.sc_flc`
- `counties_sc.sc_delinquent_tax_list`
- `counties_sc.sc_coastal_rosters`
- `counties_sc.sc_county_rosters`
- `counties_sc.horry_flc`
- `counties_sc.georgetown_civicengage`
- `counties_sc.oconee_tax_sale`
- `counties_sc.terry_howe_flc`
- `counties_nc.gaston_surplus_properties`
- `counties_nc.new_hanover_foreclosures`

**Audit procedure per source:**
1. Open the live URL in browser. Confirm what the page actually shows.
2. Identify all PDF links on the page (sale rosters, bidder lists, deficiency lists).
3. Check if the scraper already calls `harvest_document_links()` + `stamp_documents()`.
4. If not: add the import, call `stamp_documents(li, harvest_document_links(html, base_url=url))`
   right after each Listing is built.
5. Check for detail-page links ("Click for more info", "View property"). If present
   and not followed, add a follow-fetch to extract owner, parcel, case_number.
6. Check for fields on the page not currently captured (opening_bid, sale_location,
   attorney, judgment_amount).
7. Verify: compile, `discover()` lists slug, live `fetch()` returns rows with the
   new fields populated.

**1B. PDF parsers (3 sources)**
These download and parse PDF documents directly. The audit checks column mapping
and full-text field extraction.

- `counties_nc.buncombe_delinquent_tax` — Buncombe tax lien advertisement PDF
- `counties_nc.nc_county_pdf_delinquent_tax` — Lincoln, Catawba delinquent tax PDFs
- `counties_sc.sc_tax_delinquent` — SC newspaper tax sale edition viewer

**Audit procedure:**
1. Download the PDF. Open it. Confirm column layout.
2. Check if all columns are mapped (owner, address, parcel, amount owed, years
   delinquent, sale date).
3. Check if multi-page PDFs are fully parsed (not just page 1).
4. Check if the PDF URL itself is stamped via `stamp_documents()` for OCR.
5. Verify: live `fetch()` returns rows with all fields populated.

**1C. JSON/XML API with document URLs (4 sources)**
API responses often include document/PDF URLs that scrapers drop.

- `counties.column_legal_notices` — The Column API returns `pdfurl` per notice
- `counties_nc.buncombe_tax` — Trumba calendar JSON
- `counties_nc.buncombe_tax_foreclosure` — Trumba calendar ICS
- `national.servicelink_auction` — Exos API listings

**Audit procedure:**
1. Call the API endpoint directly. Inspect the full JSON/XML response.
2. Identify all fields in the response that are not mapped to Listing fields.
3. Check if the response includes document/PDF URLs. If so, stamp them.
4. Check if the response includes image URLs. If so, capture them.
5. Verify: live `fetch()` returns rows with new fields populated.

**1D. Law firm sites with PDFs (12 sources)**
Law firm foreclosure listing pages link to PDF sale packages and detail pages.

- `law_firms.alaw`
- `law_firms.aldridge_pite`
- `law_firms.bell_carrington`
- `law_firms.brock_scott`
- `law_firms.finkel`
- `law_firms.hutchens`
- `law_firms.ingle_firm`
- `law_firms.kania`
- `law_firms.korn`
- `law_firms.mcmichael_taylor_gray`
- `law_firms.shapiro_ingle_powerbi`
- `law_firms.zacchaeus`

**Audit procedure per source:**
1. Open the live URL. Confirm page structure (table, list, PowerBI embed).
2. Identify PDF links (sale packages, NOS copies, attorney affidavits).
3. Check if scraper calls `harvest_document_links()`. If not, wire it.
4. Identify detail-page links (per-property pages with more fields). If present
   and not followed, add follow-fetch.
5. Check for fields not captured: attorney phone/email, opening_bid, case_number,
   trustee, sale_location.
6. For PowerBI embeds (`mcmichael_taylor_gray`, `shapiro_ingle_powerbi`): check
   if the underlying API endpoint is being hit or just the rendered HTML.
7. Verify: compile, discover, live fetch.

**1E. Newspaper legal notices (3 sources, highest-text-value)**
Newspaper sites publish full foreclosure notice text. The richest field source
after The Column.

- `newspapers.coastland_times`
- `newspapers.post_and_courier`
- `newspapers.shelby_star`

**Audit procedure:**
1. Open the live legal notices section.
2. Check if full notice text is extracted (not just headline/summary).
3. Check if PDF scans of the notice are linked and harvested.
4. Check if detail-page links to individual notices are followed.
5. Verify field extraction: case_number, sale_date, trustee, attorney, address,
   parcel, opening_bid.

### TIER 2 — motivated-seller signals (33 sources)

These don't carry foreclosure listings per se, but they identify properties
where the owner is likely to sell: code violations, storm damage, lapsed permits,
contamination, jail bookings, estate sales. Every field captured here enriches
the distress score.

**2A. ArcGIS REST layers (15 sources)**
All use the same pattern: query an ArcGIS FeatureServer/MapServer layer, parse
attributes + geometry into Listings.

- `counties.multi_year_delinquent_tax`
- `counties_generic.arcgis_distress_layers`
- `counties_nc.asheville_helene`
- `counties_nc.asheville_str_permits`
- `counties_nc.buncombe_elderly`
- `counties_nc.henderson_code_violations`
- `counties_nc.henderson_foreclosure_parcels`
- `counties_nc.hendersonville_vacant_structures`
- `counties_nc.lincoln_code_violations`
- `counties_sc.greenville_tax_distress`
- `counties_sc.oconee_flc_assignment`
- `counties_sc.oconee_forfeited_land`
- `counties_sc.pickens_delinquent_parcels`
- `counties_sc.spartanburg_condemned`
- `counties_sc.spartanburg_vacant`

**Audit procedure per source (batch-able since they share infrastructure):**
1. Hit the layer's `?f=json` metadata endpoint. List ALL fields the layer exposes.
2. Compare to the scraper's `outFields` list. Identify unmapped fields.
3. Check for fields that map to Listing model fields: `owner_name`, `parcel_id`,
   `street_address`, `city`, `zip_code`, `assessed_value`, `acreage`,
   `year_built`, `zoning`, `legal_description`.
4. Check the `/{layerId}/attachments/{objectId}` endpoint for each layer. ArcGIS
   layers can have photo/document attachments (code violation photos, inspection
   reports). If present, capture attachment URLs into `raw['attachments']`.
5. Check if `source_url` points to a human-facing page (not just the API URL).
6. Verify: live `fetch()` returns rows with newly mapped fields.

**Shared utility to build first:** An ArcGIS layer-schema inspector script that
hits `?f=json` for each layer URL and dumps the field list. This eliminates
manual URL construction for 15 sources.

**2B. Contamination/EPA (2 sources)**
- `counties_generic.epa_frs_sites`
- `counties_generic.state_contamination`

**Audit procedure:**
1. Call the EPA FRS API / NC DEQ ArcGIS endpoint. Inspect full response.
2. Check if `latitude`/`longitude` are captured (likely missing on EPA FRS).
3. Check if facility detail page URLs are constructed (EPA registry_id -> detail URL).
4. Check if NC DEQ layers have deed book/page fields that aren't wired.
5. Check ArcGIS attachment endpoints for site assessment documents.
6. Verify: live `fetch()` returns rows with lat/lng and detail URLs.

**2C. Estate/probate/obituary sources (9 sources)**
- `public_notices.funeral_home_rss`
- `public_notices.gannett_obituaries`
- `public_notices.nc_notices_counties`
- `public_notices.ncnotices`
- `public_notices.publicnoticesc`
- `counties_sc.sc_probate_net`
- `counties_sc.sc_probate_notices`
- `counties_nc.nc_heir_estate_parcels`
- `national.probate_foreclosure_leads`

**Audit procedure:**
1. Open the live source. Confirm what data is published.
2. Check if probate case numbers are extracted.
3. Check if decedent name, PR/appointment date, estate value are captured.
4. Check if obituary RSS feeds capture property address or county of the deceased.
5. Check if detail-page links to full probate/obituary pages are followed.
6. Verify: live `fetch()` returns rows with probate fields populated.

**2D. Specialty distress signals (5 sources)**
- `national.estate_sales` — estate sale listings (motivated seller signal)
- `national.jail_bookings` — incarceration -> distressed property
- `counties_sc.spartanburg_city_condemned` — condemned properties list
- `counties_nc.nc_ptscloud_delinquent_tax` —PTS Cloud delinquent tax portal
- `counties_nc.buncombe_elderly` — elderly tax relief (motivated seller)

**Audit procedure:**
1. Open live source. Confirm data structure.
2. Check if all available fields are mapped.
3. Check if images/photos are captured (mugshots, property photos).
4. Check if detail-page links are followed.
5. Verify: live `fetch()` returns rows with all fields populated.

### TIER 3 — REO and auction platforms (18 sources)

National auction and REO platforms. These carry REO and foreclosure listings
but are lower priority because they're competitive (other investors see them too)
and many require JS rendering or have anti-bot measures.

**3A. Auction platforms (10 sources)**
- `national.auction_dot_com`
- `national.bid4assets`
- `national.auction_bank_reo`
- `national.hibid_real_estate`
- `national.xome`
- `national.nc_upset_bids`
- `national.sheriff_sales`
- `national.servicelink_auction`
- `national.craigslist_fsbo`
- `national.crexi_multifamily`

**3B. REO platforms (8 sources)**
- `national.fannie_homepath`
- `national.first_citizens_reo`
- `national.foreclosure_dot_com`
- `national.freddie_homesteps`
- `national.gsa_realproperty`
- `national.hud_homestore`
- `reo.treasury_seized`
- `reo.usda_rd`
- `reo.vrm_va_reo`

**Audit procedure per source:**
1. Open the live site. Confirm listing page structure.
2. Check if the scraper follows detail-page links (most platforms have a list
   page -> detail page pattern). The detail page usually has beds/baths/sqft,
   opening bid, auction date/time, property condition, photo gallery.
3. Check if property images are captured (URLs to photo galleries).
4. Check if all fields are mapped: `opening_bid`, `bedrooms`, `bathrooms`,
   `living_sqft`, `year_built`, `assessed_value`, `auction_status`.
5. Check if the scraper handles pagination (most platforms paginate results).
6. Verify: live `fetch()` returns rows with detail fields populated.

**Compliance note:** Several of these (auction.com, foreclosure.com, xome) may
have ToS restrictions or anti-bot measures. Check robots.txt and ToS before
fetching. If blocked, mark as `disabled=True` with `disabled_reason` and route
to the manual lane. Do NOT bypass CAPTCHAs or WAFs.

### TIER 4 — court and ROD sources (12 sources)

These are higher-effort because of WAF walls, vendor auth, and complex parsing.
They're important for lead generation (NOD, lis pendens, estate filings) but
require careful compliance handling.

**4A. eCourts WAF-walled (3 sources)**
- `counties_nc.nc_ecourts_divorce`
- `counties_nc.nc_ecourts_estates`
- `counties_nc.nc_ecourts_lis_pendens`

**Audit procedure:**
1. These hit `portal-nc.tylertech.cloud` which is AWS-WAF walled.
2. Per compliance rules: NO CAPTCHA solving, NO WAF defeat.
3. The Judgment Search JSON API (`portal-nc.tylertech.cloud/app/NCJudgmentSearchService/search`)
   is open and keyless. Check if the scraper uses this open endpoint or the
   WAF-walled Smart Search.
4. If using the open endpoint: audit field coverage (case_number, party names,
   judgment amount, filing date).
5. If using the WAF-walled endpoint: the scraper should be `disabled=True` or
   route to the manual saved-HTML lane. Check this is the case.
6. Verify: open-endpoint scrapers return real data; walled scrapers are dormant.

**4B. ROD vendor adapters (6 sources)**
- `counties.nod_discovery` — orchestrates CCHS/Aumentum/Cott/Kofile
- `counties_nc.nc_rod_logan`
- `counties_nc.nc_rod_substitute_trustee`
- `counties_nc.wnc_rod_foreclosure_starts`
- `counties_sc.sc_rod_acclaim`
- `counties_sc.sc_rod_cott`

**Audit procedure:**
1. Check which ROD vendor each adapter targets.
2. Inspect the `RodDoc` model for fields not mapped to Listing (document_type,
   legal_description, address, parcel_id, document_image_url).
3. Check if document image URLs are captured. Per compliance, ROD image vendor
   routes are explicitly excluded from `harvest_document_links()`. Check if
   there's a compliant path (robots.txt-gated, public access).
4. Check if book/page numbers are wired to Listing fields.
5. Verify: adapter returns RodDocs with all available fields; Listing mapping
   is complete.

**4C. Courtlistener API (3 sources)**
- `national.courtlistener_adversary`
- `national.courtlistener_bankruptcy`
- `national.courtlistener_civil`

**Audit procedure:**
1. Call the Courtlistener API. Inspect the full response schema.
2. Check if docket document URLs are captured (Courtlistener links to filed
   documents that can be OCR'd).
3. Check if party information (debtor, creditor, trustee) is fully extracted.
4. Check if case fields (case_number, filing_date, chapter, asset info) are mapped.
5. Verify: live `fetch()` returns rows with docket links and party fields.

### TIER 5 — lower-priority / aggregation sources (34 sources)

These are either aggregators (pull from other sources), have low volume, or
are secondary signals. Audit last.

**5A. Sitemap walker + city website search (2 sources)**
- `counties.sitemap_walker` — walks 12 county sitemaps
- `city_websites.search` — searches ~55 city websites

**Audit procedure:**
1. Check if `harvest_document_links()` is called on every fetched page.
2. Check if detail-page links are followed.
3. Check if field regex captures owner, parcel, case_number, sale_date, bid.
4. Consider adding `fetch_rendered` fallback for JS-heavy pages.

**5B. Newspaper sites (remaining 5)**
- `newspapers.carolina_coast`
- `newspapers.daily_courier`
- `newspapers.hendersonville_lightning`
- `newspapers.index_journal`
- `newspapers.tryon_bulletin`

Same procedure as Tier 1E but lower volume.

**5C. SC public index (3 sources)**
- `counties_sc.sc_public_index`
- `counties_sc.sc_public_index_lis_pendens`
- `counties_sc.sc_public_notices`

**Audit procedure:**
1. Check if ASP.NET form submission (POST with __VIEWSTATE) is handled.
2. Check if detail-page links to case detail are followed.
3. Check if all case fields are mapped (case_number, parties, filing_date,
   case_type, status).
4. Verify: live `fetch()` returns rows with case fields populated.

**5D. SC state sources (4 sources)**
- `counties_sc.sc_state_tax_lien` — SC DOR delinquent taxpayers
- `counties_sc.sc_dew_lien_registry` — SC DEW benefit lien registry
- `counties_sc.sc_ust_registry` — SC DES UST registry
- `counties_sc.spartanburg_vacant` — Spartanburg vacant properties ArcGIS

**Audit procedure:**
1. Open live source. Confirm data structure.
2. Check field coverage (owner, address, amount, lien type, status).
3. Check if detail-page links are followed.
4. Verify: live `fetch()` returns rows with all fields.

**5E. NC county sources (remaining 10)**
- `counties_nc.cleveland_tax`
- `counties_nc.henderson_tax`
- `counties_nc.nc_county_csv_delinquent_tax`
- `counties_nc.nc_county_tax_foreclosure`
- `counties_nc.polk_tax`
- `counties_nc.rutherford_tax`
- `counties_nc.rutherford_wildfire_tax`
- `counties_nc.nc_govdeals_real_property`
- `counties_nc.nc_ptscloud_delinquent_tax`
- `counties_nc.buncombe_elderly`

**5F. National aggregator/land sources (7 sources)**
- `national.homeharvest`
- `national.propwire`
- `national.distressed`
- `national.hubzu`
- `national.landandfarm`
- `national.landsofamerica`
- `national.landwatch`

**5G. HUD data sources (2 sources)**
- `national.hud_reac_inspection`
- `national.hud_section8_contracts`

**5H. Cash buyer / distressed deeds (1 source)**
- `national.cash_buyer_deeds`

---

## Execution strategy

### Batching by pattern, not by slug

Work pattern-by-pattern, not slug-by-slug. Sources in the same pattern share:

- The same fetch mechanism (ArcGIS REST, HTML scrape, JSON API, PDF parse)
- The same field-mapping audit (check Listing model field coverage)
- The same document-harvest check (PDF/image link capture)
- The same verification method

This means we learn the extraction shape once per pattern and apply it to all
sources in the batch. For ArcGIS layers (15 sources), the entire batch can be
audited with a single schema-inspection script.

### Shared utilities to build first

1. **ArcGIS layer schema inspector** — hits `?f=json` for each layer, dumps all
   field names + types. Eliminates manual URL construction for 15 sources.

2. **ArcGIS attachment checker** — hits `/{layerId}/attachments` for a sample
   of objectIds per layer. Reports which layers have photos/documents attached.

3. **Document-harvest linter** — static-analysis script that checks every
   scraper file for the `harvest_document_links` / `stamp_documents` import and
   call. Flags sources that fetch HTML but don't harvest. This can be added to
   `gen_extraction_audit.py` to make the DONE/TODO split self-updating.

4. **Field-coverage checker** — for each scraper, reports which Listing model
   fields are actually set (not just defaulted to None). Flags sources that set
   fewer than N fields. This is the "is everything being pulled?" answer in
   automated form.

### Verification protocol (for every source)

1. **Compile:** `python -c "from foreclosure_scraper.scrapers.<module> import *"`
2. **Discover:** `python -c "from foreclosure_scraper.scrapers._registry import discover; print([s.slug for s in discover() if '<slug>' in s.slug])"`
3. **Live fetch:** Run the scraper's `safe_run()` and confirm:
   - Returns > 0 Listings (or `last_outcome == ZERO_RESULT` with a reason)
   - Newly wired fields are populated (not None) on at least some rows
   - `raw['documents']` is populated if PDFs were found
4. **No silent success:** If the scraper returns 0 rows, check `last_outcome`.
   If it's `OK` with 0 rows, that's suspicious. If it's `BLOCKED` or `ERROR`,
   that's a real problem to investigate.

### What "done" looks like

A source is fully audited when:
- [ ] Live page has been opened and visually inspected
- [ ] All available fields on the page/API are mapped to Listing model fields
- [ ] PDFs (if any) are harvested via `stamp_documents()`
- [ ] Images (if any) are captured in `raw['images']` or equivalent
- [ ] Detail-page links (if any) are followed for richer data
- [ ] External links (if any) are evaluated for follow-worthy data
- [ ] `fetch()` has been run live and returns real data with new fields populated
- [ ] Entry moved from TODO to DONE in `SOURCE_EXTRACTION_AUDIT.md`

---

## Estimated effort

| Pattern | Sources | Est. hours/source | Est. total hours |
|---|---|---|---|
| County HTML pages | 35 | 0.5 | 17.5 |
| ArcGIS REST layers | 15 | 0.3 (batch-able) | 4.5 |
| Law firm sites | 12 | 0.5 | 6.0 |
| Auction/REO platforms | 18 | 0.7 | 12.6 |
| JSON/XML API | 12 | 0.4 | 4.8 |
| Newspaper sites | 8 | 0.5 | 4.0 |
| Public notice/obituary | 7 | 0.4 | 2.8 |
| ROD vendor adapters | 6 | 1.0 (complex) | 6.0 |
| eCourts (WAF-walled) | 3 | 0.5 (likely dormant) | 1.5 |
| Courtlistener API | 3 | 0.5 | 1.5 |
| PDF parsers | 3 | 0.7 | 2.1 |
| Contamination/EPA | 2 | 0.5 | 1.0 |
| CSV parsers | 1 | 0.3 | 0.3 |
| Specialty/other | 14 | 0.5 | 7.0 |
| **Shared utilities** | — | — | 4.0 |
| **Total** | **139** | | **~76 hours** |

At a pace of 4-6 sources per session, this is roughly 25-35 working sessions.
The shared utilities (ArcGIS inspector, doc-harvest linter, field-coverage
checker) cut the per-source time significantly for the pattern batches.

---

## Session sequencing

Each session should:

1. Pick one pattern batch (e.g., "ArcGIS REST layers" or "Law firm sites")
2. Build/refine any shared utility needed for that batch
3. Audit 4-6 sources in that batch
4. Update `SOURCE_EXTRACTION_AUDIT.md` (move slugs from TODO to DONE)
5. Update this plan with any new findings or procedure refinements
6. Commit changes

**Recommended session order:**
1. Shared utilities (doc-harvest linter, ArcGIS inspector, field-coverage checker)
2. TIER 1A: County HTML pages with PDF rosters (20 sources, ~5 sessions)
3. TIER 1B: PDF parsers (3 sources, 1 session)
4. TIER 1C: JSON/XML API with document URLs (4 sources, 1 session)
5. TIER 1D: Law firm sites (12 sources, ~3 sessions)
6. TIER 1E: Newspaper legal notices (3 sources, 1 session)
7. TIER 2A: ArcGIS REST layers (15 sources, ~3 sessions)
8. TIER 2B-2D: Contamination, probate, specialty (16 sources, ~4 sessions)
9. TIER 3: Auction/REO platforms (18 sources, ~4 sessions)
10. TIER 4: Court/ROD sources (12 sources, ~4 sessions)
11. TIER 5: Lower-priority sources (34 sources, ~7 sessions)
