# Extraction-completeness gaps — tracked queue (2026-08-14)

Class of defect: a scraper **fetches** source content carrying useful data but **drops or
truncates** it before it reaches the Listing/raw. Found by a full per-group audit
(public_notices, newspapers, counties_nc, counties_sc, national ×2). This is the living
queue so gaps are KNOWN, not surprises. Status: `DONE` / `OPEN`.

## Not a gap (verified good)
- **Merge unions, doesn't discard**: `Listing.merge()` keeps first-non-null per field,
  deep-merges `raw`, records every source in `raw["also_seen_in"]`. Duplicate-property
  info from multiple sources IS combined + all sources tracked.

## Cross-cutting
- `PARTIAL 2026-08-17` **Document-artifact harvester BUILT + wired (foundation done, full audit still OPEN).**
  `src/foreclosure_scraper/document_links.py` (`harvest_document_links` + `stamp_documents`) extracts
  deed/notice/instrument PDF+scan URLs from a page's HTML into `raw['documents']`; added `documents`
  to `enrich_doc_ocr` `_DOC_FIELDS`; **compliance denylist excludes the walled/paid ROD image vendors**
  (Logan-walled tenants / Cott / Aumentum / Kofile — those stay handled only by robots-gated
  `rod/doc_images.py`). Tests: `tests/test_document_links.py` (6, incl. compliance). WIRED into 4 scrapers
  where real per-listing doc links exist: `counties_nc/brunswick_legal_notices` (DocumentCenter notice PDFs),
  `counties_nc/nc_coastal_tax_foreclosure` (Brunswick href + Carteret `deed_link`), `law_firms/mewborn_deselms`
  (notice PDFs), `law_firms/rogers_townsend` (NC HTML). ~24 other doc-bearing scrapers audited (code-level)
  and correctly NOT wired: they either consume the linked list-PDF as their data source, fetch PDF bytes
  directly, or build from structured ROD records (no per-listing HTML links).
  - **STILL OPEN — full per-source VISUAL audit of ALL ~247 source pages.** 2026-08-17 I visually inspected
    (browser, rendered DOM) only a REPRESENTATIVE sample (~8) across each category: Brunswick legal-notices
    (2 real notice PDFs → captured), Hutchens / Bell Carrington / Kania foreclosure lists (data tables, 0 docs;
    deed book/page is text not a link), Buncombe tax-foreclosures (JS event app, 0 docs), Oconee + Charleston
    delinquent-tax (aggregate sale-list PDF already consumed + procedural-chrome PDFs = junk), SC PublicIndex
    (ToS-prohibits scrapers + F5 wall + dead postbacks). Pattern was consistent: most public pages don't expose
    per-property documents. BUT this was a SAMPLE, not all — and some sources gate content behind a click-through
    DISCLAIMER (Kania), JS/search loads, or per-case DETAIL pages the scraper never visits, and some genuinely
    have PDFs behind those gates/walls. NEEDS: a page-by-page visual pass over every source (and its per-listing
    detail page where one exists) to confirm nothing document-bearing is missed. **Hermes to deep-dive this.**

- `OPEN` **Document OCR is starved of inputs (NOT broken)** — CORRECTED 2026-08-14. Earlier
  "7,450 deed images un-OCR'd" was WRONG: `raw.rod` is instrument METADATA (mortgage/lien
  counts), not images. `enrich_doc_ocr` is wired (main.py:1676), provider keys ARE set
  (GEMINI_API_KEY + 60 numbered + GITHUB_MODELS_TOKEN + GROQ in run_local.sh), and it OCR'd
  ~1 of its ~5 real targets. Root cause: only **5 leads** carry a document URL in the fields
  doc_ocr scans (`_DOC_FIELDS`: document_url/notice_url/pdf_url/deed_url/instrument_image/...).
  FIX = upstream capture: have scrapers persist the PDF/scan URLs they already see into a
  `_DOC_FIELDS` key — e.g. Carteret `deed_link`→deed_url (nc_coastal_tax_foreclosure), the
  MIE result PDFs, recorded-notice PDFs, tax-bill PDFs. Then doc_ocr has real work.

## CONTACTABILITY (phones/emails on the page, dropped)
- `DONE` `column_legal_notices` — trustee/attorney PHONE (was email-only). Tests: test_column_notice_contact.py.
- `DONE` `national/realtor_foreclosures` — agent_name/email/phones + office_phones (was reading nonexistent `"agent"` key = zero contact).
- `DONE` `counties_sc/charleston_mie` — after the `$` amount `parse_auction_list` now parses the row tail: phone `\d{3}-\d{3}-\d{4}`→`raw["charleston_mie"]["attorney_phone"]`, firm (between lien position and phone)→`trustee`, trailing city→`city` (was hard-set None; bounded to the row by the next MM-DD-YY). Runtime-verified 2026-08-14.
- `DONE` `national/estate_sales` — JSON-LD `organizer.telephone`+`url`+`endDate`+Place address now parsed (added `_parse_jsonld_sale_events` for `@type==SaleEvent`; the old gate keyed on `saleEvents`/`events` only). Runtime-verified.
- `DONE` `newspapers/coastland_times`, `hendersonville_lightning`, `tryon_bulletin`, `shelby_star` — trustee phone/email from the FULL body → `raw["notice_contact"]` (imports `column_legal_notices._notice_email`; PIN-guarded). coastland also adds case_number (NC SP) + grantor→defendant/owner_name. Runtime-verified 2026-08-14.
- `DONE` `national/homeharvest`, `homeharvest_distressed` — agent_name/email/phones + broker/office_phones (+ office_email, half_baths, annual `tax` on homeharvest) added to raw (NaN-guarded via `_clean`/`_num`). Runtime-verified.
- `DONE` `national/courtlistener_bankruptcy` + `courtlistener_adversary` — `trustee_str`→first-class `trustee` (bankruptcy) + attorney/firm/dateTerminated/pacer_case_id/party captured to raw on both. Runtime-verified.
- `DONE` `counties_sc/pickens_master_in_equity` — added `PARTIES_RE` (`Plaintiff v. Defendant` split, digit-free names, run on the text after the case# with a leading attorney-code strip) + `ATTORNEY_LEGEND` scan (firm codes only) → `plaintiff`/`defendant`/`trustee`. Ported from anderson_master_in_equity. Runtime-verified 2026-08-14.
- `DONE` `public_notices/ncpublicnotices` — foreclosure path was hard-setting `defendant=None` despite computing `named_party`; now sets it + runs sibling `nc_notices_counties` regexes on the captured text → `case_number`/`sale_date`/`plaintiff`. Probate detail fetch adds a phone pass (`_notice_email`, PIN-guarded) → `raw["probate"]["phone"]` + stashes `notice_body`. Runtime-verified 2026-08-14.

## VALUATION (amounts/values/dates on the page, dropped)
- `DONE` `national/realtor_foreclosures` — estimated_value→market_value, assessed_value→tax_value, lot_sqft.
- `DONE` `national/homeharvest_distressed` — estimated_value→`market_value`, assessed_value→`tax_value` now first-class (mirrors homeharvest.py:96-97). Runtime-verified.
- `DONE` `national/auction_dot_com` — reads JSON-LD `offers.price` (dict or list; `$`-string via `PRICE_RE` or numeric) → first-class `opening_bid`; `node.image` (str/list) → `raw["auction_dot_com"]["images"]`. No-node/slug-fallback rows stay None (no crash). Runtime-verified.
- `DONE` `national/zillow_foreclosures`, `trulia_foreclosures` — beds/baths/area promoted to first-class `bedrooms`/`bathrooms`/`living_sqft`. Trulia adds a defensive `_num_field` (plain number OR `{value,formattedValue/formattedDimension}`) + keeps raw copies. Runtime-verified.
- `DONE` `counties_sc/spartanburg_vacant` — `cama_specs` now carries `last_sale_date`/`last_sale_amount` (SaleDate/SaleAmount), `half_baths` (HalfBaths) + `property_type` (PropertyTy); TaxpayerNa folded into `owner_mailing` via new `_owner_mailing` ({name,mailing} dict when present). Runtime-verified 2026-08-14.
- `DONE` `counties_sc/spartanburg_condemned` — CurrentTaxableBuildingValue+LandValue summed → first-class `tax_value` (new `_taxable_total`); TaxpayerName folded into `owner_mailing` via new `_owner_mailing`. Runtime-verified; test_spartanburg_condemned green.
- `DONE` `counties_sc/spartan_weekly_legals` — foreclosure sale-notice bodies now promote parsed strings to first-class fields: sale_date→`datetime` (`_parse_notice_date`), amount→`judgment_amount` (`_parse_amount`), plus caption `plaintiff` (`_plaintiff`). Raw strings kept in `raw["public_notice"]`. Runtime-verified; test_spartan_weekly_legals green.
- `DONE` `counties_nc/nc_county_tax_foreclosure` — upset-bid deadline now parsed to datetime + set on typed `upset_bid_deadline` (raw ISO string kept). Runtime-tested; test_nc_county_tax_foreclosure green.
- `DONE` `national/cash_buyer_deeds` — `excise_tax_stamp`→raw + back-computes NC sale price (stamp×500) into `judgment_amount` only when `consideration_amount` is None (`price_from_stamp` flag). Runtime-verified.
- `DONE` `national/sheriff_sales` — dead `_UPSET_BID_RE` now sets typed `upset_bid_deadline` (date near the phrase, else sale_date+10d NC statutory window); `plaintiff` + `judgment_amount` promoted from the row (raw `judgment_raw` kept). Runtime-verified.

## IDENTITY / DEDUP KEYS (names, parcels, legal desc dropped)
- `DONE` **`national/cash_buyer_deeds` — `parcel_id=deed.parcel_id`** now set on the Listing (+ `legal_description=deed.notes`); strongest dedupe key so a cash-buyer row parcel-matches its tax/foreclosure twin. Runtime-verified (populate + None-guard). (`counties_nc/nc_rod_substitute_trustee` half `DONE` below.)
- `DONE` `counties_nc/nc_rod_substitute_trustee` — `parcel_id=doc.parcel_id` + `legal_description=doc.notes` now set on BOTH the pre-sale (`_doc_to_listing`) and post-sale (`_sold_doc_to_listing`) builds. parcel is the strongest dedupe key. Runtime-tested (populates + None-guard); test_nc_rod green.
- `DONE` `newspapers/_townnews` (drives carolina_coast/index_journal/post_and_courier) — SC caption `<Plaintiff>, Plaintiff` / `vs. <Defendant>, Defendant` + NC "PRESENT RECORD OWNER(S)" now populate `plaintiff`/`defendant`/`owner_name` (caption-boilerplate trimmed, boiler-reject guard); SALE_DATE_RE gained a time group → first-class `sale_time`. One fix = 3 papers. Runtime-verified 2026-08-14; test_townnews green.
- `DONE` `counties_nc/nc_ptscloud_delinquent_tax` — now reads DESCRIPTION→`legal_description` (first-class), PROP_SIZE→`acreage` (first-class, via `_acres`), joins MAIL_ADDR1-3 (no truncation) + adds IN_CARE_OF to the mail dict, exposes `in_care_of`/`legal_description`/`prop_size` in raw. Runtime-tested (populate + None-guard); test_nc_ptscloud + test_ptscloud_tenant_outcomes green.
- `DONE` `counties_nc/nc_coastal_tax_foreclosure` (Carteret) — `legal_description=legal` now first-class; deed_book/deed_page/deed_link (href off the anchor) captured to raw; `_apply_onemap` sets `li.acreage` from `gisacres`. Runtime-tested; test_nc_coastal_tax_foreclosure green.
- `DONE` `counties_nc/buncombe_elderly` — `land_use=LandUse` + `acreage=Acreage` (via `_f`) now mapped onto the build (were requested in `_OUT`, dropped). Runtime-tested (populate + None-guard).
- `DONE` `counties_sc/sc_public_index` + `sc_public_index_lis_pendens` — a pre-pass over the grid now collects every defendant-party row per case → `raw["court"]["co_defendants"]` / `raw["sc_public_index"]["co_defendants"]` before the first-party de-dupe (co-owners/heirs preserved as resolvable owner leads). sc_public_index also captures Disposition Date / Judgment# / Court Agency columns when present. Runtime-verified 2026-08-14; test_sc_public_index_lis_pendens green.
- `DONE` `national/jail_bookings` — Zuercher race/sex/cell_block/release_date/mugshot now carried to `raw["jail_booking"]`, and cell_block/release_date refine the release_status (`release_scheduled …` / `in_custody cell_block=…`); full Citizen-Connect `fields` + Tyler `cells` dicts forwarded; charge cap 300→2000 (`_CHARGE_CAP`). Runtime-verified.
- `DONE` `national/courtlistener_bankruptcy` — `party` array (joint filers = co-owners) now captured to raw (alongside attorney/firm/date_terminated/pacer_case_id). Runtime-verified.
- `PARTIAL` `counties_nc/nc_heir_estate_parcels` — spec-declared `care_of` (e.g. Buncombe "CareOf") now read into `raw["heir_estate"]["care_of"]`. Runtime-tested (populate + None-guard). Assessed value/acreage/centroid still dropped: the COUNTY_GIS specs declare no field names for them and `_query` sets `returnGeometry=false` (no centroid), so capturing them would require guessing per-county field names — deliberately skipped per instruction.

## Coverage (not this class, noted): `crexi_multifamily` never fetches detail pages (price/units/broker); `gannett_obituaries` never fetches the per-decedent detail (age/funeral-home/survivors).

## DATA-QUALITY VALIDATOR findings (full board, 2026-08-14) — 55.6% clean; issues are COVERAGE not corruption
Verified CLEAN (0 defects): parcel dedup, numeric junk (NaN/neg), impossible dates, phone-as-PIN, grade-without-ARV. Parsing/enrichment is solid.
Real gaps (ranked):
- `OPEN` **Tax balance missing — 12,071 of 18,456 tax leads (31% of board)** — 6,865 no amount_owed, 5,206 use assessed-value PROXY (`is_actual_debt:false`). Only 35% have real debt. Worst: nc_ptscloud (2,477), nc_county_pdf (1,341), pickens_delinquent (1,259), oconee_flc (556), georgetown (397). FIX: extend the Spartanburg qPayBill balance-join to Pickens/Oconee/ptscloud/Georgetown; UI must NOT render proxy as "owed". #1 ROI. (Known wall — memory project_qpaybill_tax: other SC counties parcel-mismatch.)
- `OPEN` **Unlocatable — 5,565 (14.5%) no address AND no parcel** — name-only court/probate/obit leads the resolver never attached (name→parcel ceiling ~25-30%). FIX: resolve before boarding or tag non-actionable so they don't inflate the actionable count.
- `OPEN` **Sale-type, no date — 4,076 (10.6%)** — SC FLC/forfeited rosters (no per-parcel date) + REO typed as sale. FIX: join county tax-sale calendar; reclassify REO.
- Small clean fixes (queued): auction_status "status:"-prefix + newline leaks (25) → strip in a normalizer; servicer/GSE as owner_name (51: SERVICEMAC/FNMA/case-caption) → owner blocklist + parse defendant from CourtListener caption; nc_ptscloud parcel_id "0"/"61" junk (13) → column-map bug; HUD REAC portfolio-total sqft (7) + equity-on-arv_outlier (35) → withhold. Staleness (2,970 >30d) already tracked by staleness_sweep.
Bottom line: trust risk is COVERAGE (walls/resolver), not garbled parses. Top ROI = the tax-balance join.
- `DONE` `public_notices/funeral_home_rss` — was reading only title/link/pubDate; now captures the RSS `<description>`/`<content:encoded>` body → `raw["obituary"]["summary"]`, regexes age (`\b(\d{1,3})\s+years?\b`, 1-120 guard) + survivors (`survived by ...`), and keeps the Frazer title date (`Name | MM/DD/YYYY`) → `raw["obituary"]["title_date"]` instead of discarding it. Both feedparser + stdlib paths runtime-verified 2026-08-14.
