# Comprehensive Completeness Audit — Distressed Property Data Sources
**Date:** 2026-08-24 | **Listings:** 33,615 | **Enrichers:** 142 | **Scrapers:** 215

## What We Have (Working & Covered)

### Property Valuation
- `market_value` (67.0%) — county appraisal/CAD baseline (**THIS IS AS-IS VALUE, not ARV**)
- `assessed_value` (32.0%), `tax_value` (47.8%) — county tax assessment
- `zillow` (97.0%) — Zestimate + Zillow comps
- `comp_median_ppsf` (49.8%), `recorded_comps` (20.9%) — sold comps
- `fhfa_value` (33.9%) — HPI-based valuation
- `foreclosure_sold_comp_summary` (24.6%) — distressed comp sales
- `census_rent` (99.8%), `hud_fmr` (99.8%) — rental estimates

### Owner Info
- `owner_name` (88.4%), `owner_mailing` (69.7%) — GIS owner + mailing address
- `owner_phone` (33.1%) — DNC-scrubbed phones from voter files + bought data
- `skip_trace` (67.8%) — aggregated skip trace
- `tenure` (42.8%) — years of ownership
- Out-of-state detection — `owner_mailing.state` vs property state
- `life_events` (16.5%) — estate/probate/trust/multiple heirs/old owner tags

### Delinquent Tax
- `tax_owed` (39.6%) — 13,295 listings, $19.2M total delinquent balance
- Delinquent tax scrapers for 24+ NC/SC counties
- `sc_state_tax_lien` — SCDOR top delinquent taxpayers
- `sc_dew_lien` — SC Dept of Employment workforce liens
- `sc_dor_delinquent` — SC Dept of Revenue tax liens

### Foreclosure / Lis Pendens
- SC Public Index (ALL 45 non-Charleston counties via nodriver)
- NC eCourts — lis pendens, estates, divorce, case status
- foreclosure.com (3,239 NC/SC listings via curl-cffi)
- Zillow/Realtor/Trulia foreclosure feeds
- Auction.com, Bid4Assets, GovDeals, Hubzu, Xome, Crexi
- Fannie HomePath, Freddie HomeSteps, HUD HomeStore, VA REO
- Tranzon, Terry Howe, Williams, CWS Marketing, Meares auctions
- Sheriff sales (SC county sheriffs)
- 15 law firm scrapers (Zacchaeus, Brock Scott, Finkel, Korn, etc.)

### ROD / Deed History
- `rod` (20.8%) — register of deeds lien existence
- ROD vendors: Cott, Aumentum, CCHS, Logan, Kofile, Acclaim
- `rod_docs` (0.4%) — downloaded deed images with OCR'd amounts
- `dot_ocr` (0.1%) — deed of trust principal via OCR (estimated balance)
- `relationship_deeds` — probate + post-divorce deed patterns
- `last_sale` (35.7%) — most recent sale from GIS
- `recorded_sales` (14.8%), `pulled_sale` (15.0%) — from county records

### Court / Judgment
- `court_record` (1.2%) — SC case detail (NEW: expanded parser ready, 679 lines)
- `courtlistener` (2.2%) — federal court bankruptcies + civil cases
- `judgment_amount` (18.8%), `judgment_detail` enricher
- `nc_case_status` (0.5%) — NC eCourts case status via Tyler
- `court_detail_parser` NOW extracts: parties, judgments, docket, costs, payments, property description, associated cases (14 tests)

### Property Condition
- `condition_tier` (97.2%) — derived condition grade
- `year_built` (24.6%), `living_sqft` (60.9%), `acreage` (63.1%)
- `code_enforcement` (2.6%), `condemned` (2.0%)
- `flood` (91.5%), `epa` (1.2%), `storm_damage` (1.7%)
- `septic` (2.5%), `vacant_lot` (6.0%)

### Risk / Distress Scoring
- `distress_stack` (100%) — multi-signal distress indicator
- `equity` (50.3%) — equity calculation (value - liens - taxes)
- `title_risk` (15.8%) — senior/junior lien priority
- `strategy_fit` (64.8%) — deal strategy match
- `grade` (100%) — overall lead grade
- `intent_score` (99.9%) — owner sale intent score

---

## Critical Gaps — Missing or Low Coverage

### ❌ GAP 1: Child Support Liens — NOT COVERED
**Status:** No enricher, no scraper
**Impact:** Child support judgments follow the person, attach to property
**Free sources:** SC DSS and NC DHHS — require SSN/case number, NOT publicly searchable by name
**Reality:** Appear as judgments in county court records — court_detail_parser now captures judgment_amount
**Action:** Add child_support flag to court_detail_parser — look for "child support" in judgment descriptions

### ❌ GAP 2: HOA Liens — NOT COVERED
**Status:** No enricher, no scraper
**Impact:** HOA liens can be senior or junior — critical for condo/townhome
**Reality:** HOA liens show up in ROD searches (20.8% coverage) but classified generically
**Action:** Add HOA classification to `rod/classify.py` — look for "Homeowners Association", "HOA", "Association Lien"

### ❌ GAP 3: Renovation Loans — NOT COVERED
**Status:** No enricher for renovation/construction loans (203k, HomeStyle, HomeReady)
**Reality:** NOT separately identifiable from ROD records — they're standard mortgages with special terms
**Action:** Boost `dot_ocr` coverage — principal amount IS captured when deed images are OCR'd

### ⚠️ GAP 4: Open Mortgages — CRITICALLY LOW (0.1%)
**Status:** `dot_ocr` (0.1%), `loan_amount` (0.1%)
**Impact:** Without mortgage principal, equity calculations are incomplete. #1 gap for title search.
**Root cause:** `dot_ocr` requires FREE county document image access. Only a few counties serve images free.
**Action:** Expand `DOC_IMAGE_COUNTIES`, add more ROD vendors to `doc_images.py`, increase concurrency/budget

### ⚠️ GAP 5: Lien Stack — CRITICALLY LOW (0.0%)
**Status:** `liens` field exists but has 0.0% coverage (3/33,615)
**Root cause:** Only SCDOR + SC DEW liens are cross-referenced. Almost no matches found.
**Action:** Add NC state tax lien cross-reference. Extract lien amounts from ROD document OCR.

### ⚠️ GAP 6: Delinquent Tax Year — 91.4% MISSING
**Status:** `tax_owed.year` is None for 12,156 of 13,295 (91.4%)
**Impact:** Cannot determine aging >1yr, >2yr for most delinquent properties
**Root cause:** Buncombe NC delinquent tax scraper (889 records) stores balance but not the tax year
**Action:** Fix scrapers to capture delinquent tax year:
- `buncombe_delinquent_tax.py` — parse year from source data
- `nc_ptscloud_delinquent_tax.py` — extract year field
- `nc_county_pdf_delinquent_tax.py` — OCR/parsing should capture year
- `spartanburg_delinquent_tax.py` — extract year from delinquent list

### ⚠️ GAP 7: Deed Chain History — ONLY 6.9%
**Status:** `assessor_card` (6.9%) has sales history. `last_sale` (35.7%) has single sale.
**Impact:** Can't verify: inherited property, quitclaim, will conveyance, break in title chain
**Action:** Build a `deed_chain` enricher that:
1. Queries ROD by parcel/book-page for full deed history
2. Follows the chain backward (grantor → grantee → previous grantor)
3. Classifies conveyance type (warranty deed, quitclaim, will, etc.)
4. Detects breaks in chain, unreleased liens, multiple transfers

### ⚠️ GAP 8: Bankruptcy — LOW (0.6%)
**Status:** `bankruptcy` (0.6%) — CourtListener federal court search
**Action:** Broaden bankruptcy name matching — search variant names (maiden, aliases, business names)

### ⚠️ GAP 9: County Coverage — NC 35/100, SC 39/46
**NC:** ~35 counties covered. Missing ~65 (mostly rural, low volume)
**SC:** ~39 counties covered. Missing 7 rural counties (Greenville OUT OF SCOPE, Horry EXCLUDED)
**Action:** Focus on high-population NC counties: Wake, Mecklenburg, Guilford, Forsyth

---

## Priority Action Plan

### PRIORITY 1 (highest margin impact)
1. Fix delinquent tax year extraction (91.4% missing) → enables aging
2. Expand ROD deed chain enricher (6.9% → target 30%+)
3. Boost dot_ocr mortgage principal coverage (0.1% → target 10%+)
4. Integrate new court_detail_parser into enrichment pipeline (READY)

### PRIORITY 2 (red flag detection)
5. Add HOA classification to rod/classify.py
6. Add child_support flag to court_detail_parser
7. Broaden bankruptcy name matching
8. Add NC state tax lien cross-reference to lien_stack

### PRIORITY 3 (coverage expansion)
9. Expand county coverage for high-population NC counties
10. Expand DOC_IMAGE_COUNTIES for free deed image OCR
11. Add newspaper legal notice IRS lien extraction

---

## As-Is Value vs ARV — CONFIRMED

**User's understanding is CORRECT:** For distressed properties, ARV (After-Repair Value) is NOT the priority.
The `market_value` field on each listing IS the county appraisal/CAD baseline (as-is value).

- `market_value` (67.0% coverage) = county appraisal = as-is value baseline
- Sold comps (`comp_median_ppsf` 49.8%) = market validation
- Zillow (97.0%) = secondary valuation
- Strategy: buy at 10-50 cents on the dollar vs as-is value
- Target: $80-150k gross margin after closing costs, commissions, overhead
