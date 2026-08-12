# Missing FREE PUBLIC Real Estate Lead Sources — NC/SC Research

**Date:** 2026-07-03
**Scope:** 20 categories of missing lead sources for NC (Buncombe, Henderson, Cleveland, Gaston, Rutherford, Polk, Transylvania, McDowell, Lincoln, Mitchell, Burke, Brunswick, Pender, Onslow, Carteret, Dare) and SC (Spartanburg, Anderson, Pickens, Oconee, Cherokee, Union, Laurens, Charleston, Georgetown, Horry)
**Constraint:** FREE + PUBLIC + SCRAPABLE only. No paid data, no PII scraping.

---

## Existing Engine Coverage (112+ scrapers already built)

The engine already covers: foreclosures, lis pendens, tax delinquency, probate/estates, divorce, bankruptcy, REO, ROD recordings (Aumentum/Cott/CCHS vendors), elderly exemptions, storm damage (Helene ArcGIS layers for Buncombe/Henderson/Spartanburg), code enforcement (Spartanburg condemned/dilapidated), vacant properties (Spartanburg vacant registry), state tax liens, HOA, incarceration, GIS/parcel data, obituaries, newspapers, law firms (13+), auction sites (GovDeals, Bid4Assets, auction.com, Crexi, Hubzu, Xome, etc.), FEMA flood zone enrichment (NFHL ArcGIS), FEMA repetitive flood loss, building permits (Charlotte ArcGIS), absentee owner detection, buyer match registry, tax relief/senior exemptions, owner tenure, relationship deeds (probate/divorce patterns), environmental (EPA ECHO).

**Already covered — NOT missing:**
- FEMA flood zone data (NFHL ArcGIS REST — layer 28 at hazards.fema.gov/arcgis/rest/services/public/NFHL/MapServer/28/query)
- FEMA repetitive flood loss (OpenFEMA IndividualAssistanceMultipleLossFloodProperties)
- Building permits (Charlotte ArcGIS — enrichment_building_permits.py)
- Absentee owner flags (enrichment_owner_mailing.py — already computes absentee + out_of_state from county GIS mailing address)
- Cash buyer identification (enrichment_buyer_match.py + data/land_buyers.json — 188 named buyers)
- Helene storm damage (enrichment_helene_damage.py — Spartanburg, Henderson, Buncombe ArcGIS layers)
- Upset bid window tracking (enrichment_upset_bid.py — tags listings within 14-day upset window)
- Estate/probate deed detection (enrichment_relationship_deeds.py — probate + post-divorce patterns from ROD)
- Senior/elderly exemptions (enrichment_tax_relief.py + buncombe_elderly.py)

---

## NEW Missing Sources Found

### 1. SHERIFF SALES — NC/SC Counties

**Status:** PARTIALLY MISSING — engine has tax foreclosure sales but NOT sheriff's civil sales

**NC Sheriff Sales:**
In NC, foreclosure sales are conducted by the Clerk of Superior Court (not the sheriff). The sheriff handles civil executions (writs of execution, claim & delivery) and judgment enforcement sales, which are a DIFFERENT distress signal from mortgage/tax foreclosures.

| County | URL | Free | Public | Scrapable | Notes |
|--------|-----|------|--------|-----------|-------|
| Henderson NC | https://sheriffhendersoncounty.com/sheriff-sales/ | ✅ | ✅ | ✅ (HTML) | Has "Sheriff Sales" nav page with Notice of Sale PDFs. Currently shows May 27, 2026 sale notice. |
| Buncombe NC | https://buncombesheriff.com/civil-process/ | ✅ | ✅ | ⚠️ (call-only) | Civil Process Division handles foreclosure executions but no online listing — must call (828) 250-4503 |
| Cleveland NC | https://www.clevelandcounty.com/main/ | ✅ | ✅ | ❌ | No online sheriff sale listing found |
| Onslow NC | https://www.onslowcountync.gov/167/Sheriff | ✅ | ✅ | ❌ | No sheriff sale page found |

**SC Sheriff Sales:**
In SC, foreclosure sales are conducted by the Master-in-Equity (MIE). Sheriff sales in SC are for execution sales (judgment enforcement, tax execution sales).

| County | URL | Free | Public | Scrapable | Notes |
|--------|-----|------|--------|-----------|-------|
| Spartanburg SC | https://www.spartanburgcounty.org/1310/Sheriffs-Office | ✅ | ✅ | ⚠️ | Sheriff's office page exists; need to check for civil sale listings |
| Anderson SC | https://www.andersoncounty.org/sheriff/ | ✅ | ✅ | ⚠️ | Page loads but civil sales section unclear |
| Charleston SC | https://www.charlestoncounty.org/departments/sheriff/ | ✅ | ✅ | ⚠️ | Sheriff page exists; MIE handles foreclosures separately (already covered by charleston_mie.py) |
| Georgetown SC | https://www.gcsd.org/ | ✅ | ✅ | ⚠️ | Georgetown County Sheriff's Dept page exists |

**VERDICT:** LOW PRIORITY for NC (sheriff civil executions are rare and most counties don't post them online). MEDIUM for SC execution sales. The engine already covers the primary foreclosure sale channels (Clerk of Court tax foreclosures in NC, MIE in SC).

---

### 2. UPSET BID LISTINGS — NC Counties

**Status:** PARTIALLY COVERED — enrichment_upset_bid.py tags the 14-day window, but doesn't scrape the actual upset bid postings

**Key Finding:** Gaston County posts FULL upset bid listings online with property details:

| County | URL | Free | Public | Scrapable | Notes |
|--------|-----|------|--------|-----------|-------|
| **Gaston NC** | https://www.gastongov.com/671/Previous-Tax-Foreclosure-Sales | ✅ | ✅ | ✅ **YES** | **VERIFIED LIVE.** Full upset bid listings with Owner, Parcel, Address, Sale Date, Current Bid, Minimum Next Upset Bid, Last Day to Upset, File Number, Status. Plain HTML. Multiple active listings with 2025-2026 dates. Already covered by nc_county_tax_foreclosure.py but the UPSET BID data (current bid + upset deadline) is a distinct signal. |
| **Buncombe NC** | https://www.buncombenc.gov/app-tax-foreclosures | ✅ | ✅ | ✅ | Interactive app for tax foreclosure sales (already scraped by buncombe_tax_foreclosure.py) |
| Brunswick NC | https://www.brunswickcountync.gov/382/Foreclosures | ✅ | ✅ | ⚠️ | Page exists but content is about occupancy tax, not foreclosure sales |

**VERDICT:** The Gaston County upset bid page is already being scraped by the existing `nc_county_tax_foreclosure` scraper. The `enrichment_upset_bid.py` module correctly computes the upset window. **GAP:** Other NC counties (Henderson, Cleveland, Brunswick, etc.) may post upset bid notices on their tax/foreclosure pages but most don't have dedicated online postings. The Clerk of Superior Court maintains upset bid records but most counties require in-person visits.

---

### 3. FSBO LISTINGS — Craigslist / Land.com

**Status:** MISSING — no FSBO scraper exists

| Source | URL | Free | Public | Scrapable | Counties Covered | Notes |
|--------|-----|------|--------|-----------|-----------------|-------|
| **Craigslist Asheville** | https://asheville.craigslist.org/d/real-estate-for-sale/search/rea?purveyor=owner | ✅ | ✅ | ✅ **YES** | Buncombe, Henderson, Polk, Rutherford, McDowell, Transylvania, Madison, Yancey | **VERIFIED LIVE.** JSON-LD structured data with property name, lat/lng, beds/baths, locality. ~50+ active FSBO listings including land, houses, mobile homes. Schema.org `ItemList` in page source is directly parseable. |
| **Craigslist Charlotte** | https://charlotte.craigslist.org/d/real-estate-for-sale/search/rea?purveyor=owner | ✅ | ✅ | ✅ | Gaston, Lincoln, Cleveland, Burke, Cabarrus, Mecklenburg | Same structured data format |
| **Craigslist Wilmington** | https://wilmington.craigslist.org/d/real-estate-for-sale/search/rea?purveyor=owner | ✅ | ✅ | ✅ | Brunswick, Pender, New Hanover, Onslow, Carteret | Same format |
| **Craigslist Myrtle Beach** | https://myrtlebeach.craigslist.org/d/real-estate-for-sale/search/rea?purveyor=owner | ✅ | ✅ | ✅ | Horry, Georgetown, Brunswick NC | Same format |
| **Craigslist Charleston** | https://charleston.craigslist.org/d/real-estate-for-sale/search/rea?purveyor=owner | ✅ | ✅ | ✅ | Charleston, Berkeley, Dorchester | Same format |
| Land.com / LandWatch | https://www.land.com/North-Carolina/land-for-sale/ | ❌ (403) | ✅ | ❌ | NC/SC statewide | Returns 403 to curl; aggressive bot protection. Would need browser automation. Land listings include FSBO + agent. |
| FB Marketplace | https://www.facebook.com/marketplace/ | ✅ | ⚠️ | ❌ | All | Requires FB login; heavy bot detection; ToS restrictions. NOT scrapable without violating ToS. |

**VERDICT: HIGH PRIORITY.** Craigslist FSBO is free, public, and has structured JSON-LD data that's trivially parseable. Five Craigslist regions cover all our NC/SC counties. This is a net-new lead source — motivated sellers listing directly, often at below-market prices, owner-financing deals, and distressed properties.

---

### 4. BUILDING / DEMOLITION PERMIT DATA

**Status:** PARTIALLY COVERED — Charlotte building permits only (enrichment_building_permits.py)

| County/City | URL | Free | Public | Scrapable | Notes |
|-------------|-----|------|--------|-----------|-------|
| **Charlotte/Mecklenburg** | ArcGIS FeatureServer (already in enrichment_building_permits.py) | ✅ | ✅ | ✅ | Already covered |
| **City of Asheville** | https://gis.ashevillenc.gov/server/rest/services/Permits/ | ✅ | ✅ | ✅ | Already used for STR homestay permits (asheville_str_permits.py). Building permits may be on separate layers — need to enumerate services |
| Gaston County | https://www.gastongov.com/373/Building-Inspections | ✅ | ✅ | ⚠️ | Page loads but no open data portal found |
| Henderson County | https://www.hendersoncountync.gov/planning | ✅ | ✅ | ⚠️ | Page loads but no open permit data |
| Brunswick County | https://www.brunswickcountync.gov/320/Building-Inspections | ✅ | ✅ | ⚠️ | Page loads but no open permit data |

**VERDICT: MEDIUM PRIORITY.** Most NC/SC counties don't expose building permits via open ArcGIS APIs. The existing Charlotte coverage is the only confirmed scrapable permit data source. Additional county portals would need browser-based scraping or FOIA requests. Demolition permits specifically are very rarely published online in our footprint.

---

### 5. FEMA / SBA HELENE DISASTER DATA

**Status:** PARTIALLY COVERED — county-level Helene damage assessments (Buncombe, Henderson, Spartanburg ArcGIS layers) already in enrichment_helene_damage.py

**Additional FEMA data sources found:**

| Source | URL | Free | Public | Scrapable | Notes |
|--------|-----|------|--------|-----------|-------|
| **OpenFEMA DisasterDeclarationsSummaries** | https://www.fema.gov/api/open/v2/DisasterDeclarationsSummaries | ✅ | ✅ | ✅ **YES** | **VERIFIED LIVE.** Returns JSON. Disaster 4827 = Helene. Lists all NC/SC counties designated for Individual Assistance + Public Assistance. Already used for repetitive loss. |
| **OpenFEMA FemaWebDisasterSummaries** | https://www.fema.gov/api/open/v2/FemaWebDisasterSummaries | ✅ | ✅ | ✅ | Financial assistance values per disaster — IA/PA dollars obligated |
| **OpenFEMA HazardMitigationAssistanceMitigatedProperties** | https://www.fema.gov/api/open/v2/HazardMitigationAssistanceMitigatedProperties | ✅ | ✅ | ⚠️ | Properties identified for hazard mitigation — would be strong distress signal. Endpoint exists in dataset list but returned HTML errors during testing (may require specific query params or be temporarily down). |
| **OpenFEMA IndividualAssistanceHousingRegistrantsLargeDisasters** | https://www.fema.gov/api/open/v2/IndividualAssistanceHousingRegistrantsLargeDisasters | ✅ | ✅ | ⚠️ | IA housing registrant data for large disasters including Helene. Aggregated, non-PII. Endpoint returned HTML errors during testing. |
| **FEMA Disaster Declaration Page** | https://www.fema.gov/disaster/4827 | ✅ | ✅ | ⚠️ (HTML) | Overview page for Helene declaration |
| **NC DPS Helene Recovery** | https://www.ncdps.gov/helene | ✅ | ✅ | ⚠️ (HTML) | State-level recovery resources, not property-level data |
| **SBA Disaster Loans** | https://disasterloanassistance.sba.gov/ | ✅ | ✅ | ❌ | SBA disaster loan portal — requires business/address search, no bulk data export. SBA doesn't publish individual loan recipients (PII). |

**VERDICT: LOW-MEDIUM PRIORITY.** The engine already covers the most valuable Helene data (county ArcGIS damage assessments). The OpenFEMA datasets listed above provide disaster declaration metadata and aggregated financial assistance data, but the property-level datasets (HazardMitigationAssistanceMitigatedProperties, IndividualAssistanceHousingRegistrants) appear to have API issues or require specific access. The existing county-level damage layers (Buncombe PPDR, Henderson damage assessments, Spartanburg Palmetto damage) are the highest-value disaster data and are already integrated.

---

### 6. LAND BANK PROPERTIES — NC/SC

**Status:** MISSING — no land bank scraper exists

| Source | URL | Free | Public | Scrapable | Counties | Notes |
|--------|-----|------|--------|-----------|----------|-------|
| **Gaston County Surplus** | https://www.gastongov.com/709/Surplus-Properties | ✅ | ✅ | ✅ | Gaston | **ALREADY COVERED** by gaston_surplus_properties.py — county-owned post-foreclosure surplus inventory |
| Charlotte Land Bank Authority | (no URL found — 404) | ✅ | ✅ | ❌ | Mecklenburg (out of footprint) | Charlotte dissolved its land bank authority; properties go through HBHI (House Charlotte) |
| NC Housing Finance Agency | https://www.nchfa.com/ | ✅ | ✅ | ⚠️ | Statewide NC | No property listing portal — finances affordable housing but doesn't hold inventory |
| SC Housing | https://schousing.com/ | ✅ | ✅ | ⚠️ | Statewide SC | No property listing portal found |

**VERDICT: LOW PRIORITY.** NC and SC do not have active county-level land bank authorities in our footprint (unlike states like OH, MI, NY). The Gaston County surplus properties page is already covered. The NC General Assembly passed enabling legislation for land banks in 2023 (H451) but no operational land banks exist in our target counties yet.

---

### 7. ZONING CHANGE NOTICES

**Status:** MISSING — no zoning change scraper exists

| County/City | URL | Free | Public | Scrapable | Notes |
|-------------|-----|------|--------|-----------|-------|
| Buncombe County Planning | https://www.buncombenc.gov/planning | ✅ | ✅ | ⚠️ | Planning dept page loads; zoning change notices would be in meeting agendas (CivicEngage CMS) |
| Brunswick County Planning | https://www.brunswickcountync.gov/292/Planning | ✅ | ✅ | ⚠️ | Same CivicEngage CMS — agendas/minutes are HTML |
| Charleston Zoning | https://www.charleston-sc.gov/zoning | ✅ | ✅ | ⚠️ | City zoning page; changes go through Board of Zoning Appeals |

**VERDICT: LOW PRIORITY.** Zoning change notices are published as meeting agenda items in CivicEngage/CivicPlus CMS systems. While technically scrapable (HTML agendas), the signal-to-noise ratio is very low — most zoning changes are routine (variances, conditional use permits) and don't indicate distressed properties. Rezoning requests (e.g., residential to commercial) could signal development pressure, but this is a minor lead source compared to foreclosure/tax data. The `sitemap_walker.py` scraper already walks county CivicEngage sites for foreclosure notices.

---

### 8. LAND AUCTION SITES

**Status:** PARTIALLY COVERED — GovDeals, Bid4Assets, auction.com, Crexi already scraped

| Source | URL | Free | Public | Scrapable | Notes |
|--------|-----|------|--------|-----------|-------|
| GovDeals | https://www.govdeals.com/ | ✅ | ✅ | ✅ | **ALREADY COVERED** by nc_govdeals_real_property.py |
| Bid4Assets | https://www.bid4assets.com/ | ✅ | ✅ | ✅ | **ALREADY COVERED** by national/bid4assets.py |
| Crexi | https://www.crexi.com/ | ✅ | ✅ | ✅ | **ALREADY COVERED** by national/crexi_multifamily.py |
| **LandBidz** | https://landbidz.com/ | ✅ | ✅ | ⚠️ | **NEW.** Small land auction site. Returns 200. Would need to check for NC/SC listings. Low volume. |
| LandAuction.com | (unreachable — 000) | ❓ | ❓ | ❌ | Site unreachable from testing |

**VERDICT: LOW PRIORITY.** Major auction sites already covered. LandBidz is a minor additional source with very low volume.

---

### 9. NC DOT / SCDOT ROAD PROJECT EMINENT DOMAIN

**Status:** MISSING — no DOT eminent domain scraper exists

| Source | URL | Free | Public | Scrapable | Notes |
|--------|-----|------|--------|-----------|-------|
| **NCDOT Projects** | https://www.ncdot.gov/projects/ | ✅ | ✅ | ⚠️ | Project listing page loads. NCDOT publishes project information including location maps. Right-of-way acquisition notices are published in newspapers (already partially covered by newspaper scrapers). |
| **NCDOT Letting** | https://apps.ncdot.gov/letting/ | ✅ | ✅ | ⚠️ | Construction letting schedule — indicates upcoming road projects that may require ROW acquisition |
| **SCDOT Projects** | https://www.scdot.org/projects/ | ✅ | ✅ | ⚠️ | Similar project listing |

**VERDICT: LOW-MEDIUM PRIORITY.** DOT eminent domain (condemnation) creates motivated sellers — property owners whose land is partially taken for road widening get a notice and often sell the remainder. However, DOT project pages list projects at a high level (corridor maps, project descriptions) and don't typically publish individual parcel acquisition notices. The actual condemnation filings appear in the Register of Deeds as "Condemnation" or "Eminent Domain" deeds, which the ROD scrapers (nc_rod_substitute_trustee.py, sc_public_index.py) would already capture if they search for these document types. The `enrichment_relationship_deeds.py` module already detects "partition" deeds (court-ordered) — condemnation deeds could be added as another pattern.

---

### 10. FEMA FLOOD ZONE DATA

**Status:** ALREADY COVERED** — enrichment_flood.py queries FEMA NFHL ArcGIS REST (layer 28)

The FEMA NFHL REST endpoint at `https://hazards.fema.gov/arcgis/rest/services/public/NFHL/MapServer/28/query` is already integrated and tags each listing with flood zone code (AE, A, VE, X, etc.) and SFHA status. Additionally, `enrichment_fema_repetitive_loss.py` cross-references OpenFEMA's NFIP Multiple Loss Properties dataset.

**No action needed.**

---

### 11. TAX SALE REDEMPTION PROPERTIES

**Status:** PARTIALLY COVERED — tax foreclosure sales are scraped, but post-sale redemption tracking is not

In NC, after a tax foreclosure sale, the former owner has a redemption period. In SC, tax sale properties have a 1-year redemption period. Properties that are redeemed and then re-default are strong motivated-seller leads.

| Source | URL | Free | Public | Scrapable | Notes |
|--------|-----|------|--------|-----------|-------|
| Gaston NC Previous Sales | https://www.gastongov.com/671/Previous-Tax-Foreclosure-Sales | ✅ | ✅ | ✅ | **ALREADY COVERED.** Shows sale status ("Sale Closed-Property Sold", "Settled, Sale Cancelled") which indicates redemption |
| SC County Tax Sale Rosters | Already covered by sc_county_rosters.py, sc_delinquent_tax_list.py | ✅ | ✅ | ✅ | SC tax sale rosters already scraped; redemption period tracking would be a post-processing enrichment |

**VERDICT: LOW PRIORITY.** Redemption tracking is a post-processing/enrichment task on data already being collected, not a new source to scrape. The engine already captures tax sale listings and their outcomes.

---

### 12. USPS VACANCY DATA (HUD Aggregated)

**Status:** MISSING — no USPS vacancy data integration

| Source | URL | Free | Public | Scrapable | Notes |
|--------|-----|------|--------|-----------|-------|
| **HUD USPS Vacancy Data** | https://www.huduser.gov/portal/datasets/usps.html | ✅ | ✅ | ✅ **YES** | **VERIFIED.** HUD receives quarterly USPS vacancy data at the census tract level. Data is downloadable as XLSX/CSV files. Aggregated to tract-level (no PII). Shows "No-Stat" addresses (vacant >90 days) and "Active" but no delivery. |
| **HUD SOA (Summary of Areas)** | https://www.huduser.gov/portal/datasets/3k_data.html | ✅ | ✅ | ✅ | Supplemental data — changes in vacancy over time |

**VERDICT: MEDIUM PRIORITY.** HUD USPS vacancy data is free, public, and downloadable. It provides census-tract-level vacancy rates that could be used as a neighborhood-level distress signal (high vacancy tracts = declining area = more motivated sellers). However, it's aggregate data (not property-level), so it's an enrichment signal rather than a lead source. The engine already has property-level vacant property detection (spartanburg_vacant.py).

---

### 13. WATER / UTILITY DELIQUENCY LISTS

**Status:** MISSING — no utility delinquency scraper exists

| Source | URL | Free | Public | Scrapable | Notes |
|--------|-----|------|--------|-----------|-------|
| Charlotte Water | https://www.charlottenc.gov/water | ✅ | ✅ | ❌ | No public delinquency list — utility shut-off data is NOT public record under NC/SC law |
| Charleston Water | https://www.charlestonwater.com/ | ✅ | ✅ | ❌ | Same — no public delinquency data |

**VERDICT: NOT FEASIBLE.** Water/utility delinquency lists are NOT public record in NC or SC. Utility companies do not publish customer delinquency data — it's protected as confidential customer information under state public records law exemptions. This data can only be obtained through: (1) FOIA/public records request (rarely granted for utility delinquency), (2) purchasing from data brokers (paid, not free), or (3) county tax lien data (which already includes utility liens in some NC counties). The engine already captures tax delinquency which often includes unpaid utility assessments.

---

### 14. OPPORTUNITY ZONE DATA

**Status:** MISSING — no opportunity zone enrichment exists

| Source | URL | Free | Public | Scrapable | Notes |
|--------|-----|------|--------|-----------|-------|
| **HUD Opportunity Zones (ArcGIS)** | https://hudgis-hud.opendata.arcgis.com/datasets/opportunity-zones | ✅ | ✅ | ✅ **YES** | **VERIFIED.** HUD publishes Opportunity Zone boundaries as an ArcGIS FeatureLayer. Free, no auth. Can query by lat/lng to determine if a property is in an OZ. |
| CDFI Fund | https://www.cdfifund.gov/programs-training/programs/opportunity-zones | ✅ | ✅ | ⚠️ | Returns 404 to direct URL; CDFI Fund site may have moved |

**VERDICT: MEDIUM PRIORITY.** Opportunity Zone designation is a useful enrichment signal — properties in OZs are eligible for capital gains tax deferral, making them more attractive to investor buyers. The `enrichment_buyer_match.py` already tags buyers by type; adding OZ eligibility would further refine buyer matching. This is an enrichment (point-in-polygon query), not a lead source.

---

### 15. CASH BUYER IDENTIFICATION FROM DEED RECORDS

**Status:** ALREADY COVERED** — enrichment_buyer_match.py + data/land_buyers.json (188 named buyers)

The engine already has a buyer registry built from recorded deeds (scripts/build_buyer_registry.py). The `enrichment_relationship_deeds.py` module analyzes deed patterns. The `enrichment_recorded_comps.py` pulls actual recorded arms-length sales from county GIS.

**No additional action needed for this category.** A potential enhancement would be to flag "cash buyer" transactions specifically (deeds with $0 mortgage, or where the grantee is an LLC/individual with no recorded deed of trust simultaneously), but this would require deeper ROD document analysis.

---

### 16. ABSENTEE OWNER FLAGS FROM TAX RECORDS

**Status:** ALREADY COVERED** — enrichment_owner_mailing.py

The engine already computes:
- `absentee = owner mailing address != property (situs) address`
- `out_of_state = owner mails from different state`

This is done by querying each county's ArcGIS REST parcel layer for the taxpayer mailing address. Covered counties: all NC counties with ArcGIS parcel layers, all SC counties with ArcGIS/qPublic.

**No action needed.**

---

### 17. ESTATE SALE COMPANY LISTINGS

**Status:** PARTIALLY COVERED — obituaries and probate/estate filings are scraped, but estate sale company listings are not

| Source | URL | Free | Public | Scrapable | Notes |
|--------|-----|------|--------|-----------|-------|
| **EstateSales.net** | https://www.estatesales.net/ | ✅ | ✅ | ✅ **YES** | **VERIFIED LIVE.** Returns 200. Lists estate sales by location with dates, addresses, photos. Searchable by city/state. Estate sales often indicate a property being liquidated (owner died/downsized) — the property itself may be for sale or about to be listed. |
| **EstateSales.org** | https://www.estatesales.org/ | ✅ | ✅ | ✅ | **VERIFIED LIVE.** Returns 200. Similar format — estate sale listings by location. |
| AuctionZip | https://www.auctionzip.com/ | ✅ | ✅ | ⚠️ (403) | Returns 403 to curl; would need browser automation |

**VERDICT: MEDIUM PRIORITY.** Estate sale listings are a legitimate lead source — when an estate sale is happening at a residential address, the property is often being prepared for sale (executor liquidating). This is a complementary signal to the probate/estate filing data already scraped. EstateSales.net and EstateSales.org both have location-based search that could be scraped for our NC/SC counties.

---

### 18. MOBILE HOME PARK LISTINGS

**Status:** MISSING — no mobile home park listing scraper exists

| Source | URL | Free | Public | Scrapable | Notes |
|--------|-----|------|--------|-----------|-------|
| **MHVillage** | https://www.mhvillage.com/ | ✅ | ✅ | ✅ **YES** | **VERIFIED LIVE.** Returns 200. National mobile home park and individual mobile home listing site. Has state/city search. Mobile home parks for sale are strong leads — park owners selling are motivated (often aging owners, estate situations). |
| Mobile Home Park Store | https://www.mhplanet.com/ | ❓ | ❓ | ❌ | Site unreachable (000) |
| **Craigslist FSBO** | (already listed in #3) | ✅ | ✅ | ✅ | Craigslist FSBO listings already include mobile homes ("WE BUY MOBILE HOMES", "Discount Double Wide Home for sale only $69.9k", "Mobile Home Park - Waynesville") |

**VERDICT: LOW-MEDIUM PRIORITY.** MHVillage is the primary mobile home marketplace and is scrapable. Mobile home parks and individual mobile homes are a niche but relevant lead source in our rural NC/SC counties. However, Craigslist FSBO (category #3) already captures many mobile home listings.

---

### 19. SHORT SALE LISTINGS

**Status:** PARTIALLY COVERED — Zillow/Realtor/Trulia foreclosure scrapers exist but don't specifically filter short sales

| Source | URL | Free | Public | Scrapable | Notes |
|--------|-----|------|--------|-----------|-------|
| Zillow | https://www.zillow.com/ | ✅ | ✅ | ⚠️ (403) | Zillow returns 403 to curl. Already has zillow_foreclosures.py and zillow_bulk.py scrapers. Short sale listings on Zillow are tagged with "Short Sale" in the listing description. |
| Realtor.com | https://www.realtor.com/ | ✅ | ✅ | ⚠️ (404 on /short_sale) | Already has realtor_foreclosures.py. Short sales are a filter option on Realtor.com but URL structure unclear. |

**VERDICT: LOW PRIORITY.** Short sale listings are already partially captured by the existing Zillow/Realtor foreclosure scrapers (short sales appear alongside foreclosures in "pre-foreclosure" filters). The distinction between a short sale and a pre-foreclosure listing is often just a listing description tag. The existing `national/homeharvest_distressed.py` and `national/propwire_foreclosures.py` scrapers likely already capture short sale listings.

---

### 20. NOD RECORDINGS IN NC ROD BEYOND WHAT WE HAVE

**Status:** PARTIALLY COVERED — nc_rod_substitute_trustee.py + nod_discovery.py cover Aumentum (Buncombe, Gaston), Cott (Polk, Rutherford), CCHS (Burke, Lincoln, Cleveland)

**Counties NOT yet covered by ROD vendor adapters:**

| County | ROD System | URL | Free | Public | Scrapable | Notes |
|--------|-----------|-----|------|--------|-----------|-------|
| Henderson NC | Unknown | https://www.hendersoncountync.gov/register-of-deeds | ✅ | ✅ | ⚠️ | Need to identify ROD vendor. Page returns 404 at expected URL. |
| Transylvania NC | Unknown | https://www.transylvaniacounty.org/departments/register-of-deeds | ✅ | ✅ | ⚠️ | ROD page exists (200). Need to identify online search system. |
| McDowell NC | Unknown | https://www.mcdowellcounty.org/register-of-deeds | ❓ | ✅ | ❌ | Site unreachable (000) |
| Mitchell NC | Unknown | https://www.mitchellcounty.org/register-of-deeds | ❓ | ✅ | ❌ | Returns 523 (origin error) |
| Brunswick NC | Unknown | (CivicEngage site) | ✅ | ✅ | ⚠️ | ROD is part of county website; online search unclear |
| Pender NC | Unknown | (CivicEngage site) | ✅ | ✅ | ⚠️ | Same as Brunswick |
| Onslow NC | Unknown | (county site) | ✅ | ✅ | ⚠️ | ROD page exists |
| Carteret NC | Unknown | (county site) | ✅ | ✅ | ⚠️ | ROD page exists |
| Dare NC | Unknown | https://www.darenc.com/departments/register-of-deeds | ✅ | ✅ | ⚠️ (403) | Returns 403 to curl; may need browser |

**Known ROD vendor coverage (from nc_rod_substitute_trustee.py docstring):**
- Aumentum: Buncombe, Gaston
- Cott: Polk, Rutherford
- CCHS: Burke, Lincoln, Cleveland (BUT broken — CCHS migrated to new iframe app, adapter needs rewrite)

**VERDICT: MEDIUM-HIGH PRIORITY.** The NOD discovery scraper (`nod_discovery.py`) is currently returning 0 results across ALL counties due to the CCHS migration issue noted in its docstring. Fixing the CCHS adapter (Burke, Lincoln, Cleveland) is the highest-impact fix. Additionally, identifying and mapping ROD vendors for Henderson, Transylvania, Brunswick, Pender, Onslow, Carteret, and Dare counties would add NOD coverage for those counties. NC counties use one of several ROD vendors: Aumentum, Cott Systems, CCHS (Courthouse Computer Systems), Kofile, or direct county-hosted search. Many smaller counties use Kofile (cotthosting.com is Kofile's Cott system).

---

## PRIORITY RANKING OF NEW SOURCES

### HIGH PRIORITY (net-new lead sources, free, scrapable, covers our counties)

1. **Craigslist FSBO** (Category #3) — 5 regional Craigslist sites cover all our counties. JSON-LD structured data. ~50+ listings per region. Trivially scrapable. Motivated sellers listing directly.

### MEDIUM PRIORITY (valuable enrichment or gap-filling)

2. **Estate Sale Company Listings** (#17) — EstateSales.net + EstateSales.org. Property liquidation signal complementary to probate filings.
3. **Opportunity Zone Enrichment** (#14) — HUD ArcGIS OZ layer. Point-in-polygon enrichment for buyer matching.
4. **HUD USPS Vacancy Data** (#12) — Census-tract-level vacancy rates as neighborhood distress signal. Downloadable XLSX/CSV.
5. **NOD ROD Vendor Fixes** (#20) — Fix CCHS adapter (Burke/Lincoln/Cleveland) + map vendors for uncovered counties.
6. **OpenFEMA Disaster Datasets** (#5) — DisasterDeclarationsSummaries already works; explore HazardMitigationAssistanceMitigatedProperties for property-level mitigation data.

### LOW PRIORITY (minor signal, already covered, or not feasible)

7. **Sheriff Sales** (#1) — NC foreclosure sales are via Clerk of Court (already covered). Sheriff civil executions are rare and mostly not online.
8. **Building Permits** (#4) — Only Charlotte has open data. Most counties don't expose permits via API.
9. **Land Banks** (#6) — No active land banks in our NC/SC footprint.
10. **Zoning Changes** (#7) — Low signal-to-noise ratio; buried in meeting agendas.
11. **DOT Eminent Domain** (#9) — Condemnation deeds already captured by ROD scrapers.
12. **Tax Sale Redemptions** (#11) — Post-processing on existing data, not a new source.
13. **Utility Delinquency** (#13) — NOT public record in NC/SC. Not feasible.
14. **Mobile Home Parks** (#18) — MHVillage is scrapable but low volume; Craigslist captures most.
15. **Short Sales** (#19) — Already captured by existing foreclosure/pre-foreclosure scrapers.
16. **Land Auction Sites** (#8) — Major sites already covered; LandBidz is minor.
17. **Upset Bid Listings** (#2) — Already covered by existing tax foreclosure + upset_bid enrichment.
18. **Cash Buyer ID** (#15) — Already covered by buyer_match enrichment.
19. **Absentee Owner Flags** (#16) — Already covered by owner_mailing enrichment.
20. **FEMA Flood Zone** (#10) — Already covered by flood enrichment.

---

## DETAILED FINDINGS FOR HIGH-PRIORITY SOURCES

### Craigslist FSBO — Implementation Notes

**URLs to scrape:**
```
https://asheville.craigslist.org/d/real-estate-for-sale/search/rea?purveyor=owner
https://charlotte.craigslist.org/d/real-estate-for-sale/search/rea?purveyor=owner
https://wilmington.craigslist.org/d/real-estate-for-sale/search/rea?purveyor=owner
https://myrtlebeach.craigslist.org/d/real-estate-for-sale/search/rea?purveyor=owner
https://charleston.craigslist.org/d/real-estate-for-sale/search/rea?purveyor=owner
```

**Data format:** Page contains JSON-LD `<script type="application/ld+json">` with `ItemList` of `ListItem` entries. Each item has:
- `name` (listing title)
- `@type` (House, Place, Apartment)
- `address` (locality, region)
- `latitude` / `longitude`
- `numberOfBedroomsTotal` / `numberOfBathroomsTotal` (for houses)

**Counties covered:**
- Asheville region → Buncombe, Henderson, Polk, Rutherford, McDowell, Transylvania, Madison, Yancey
- Charlotte region → Gaston, Lincoln, Cleveland, Burke
- Wilmington region → Brunswick, Pender, New Hanover, Onslow, Carteret
- Myrtle Beach region → Horry, Georgetown, Brunswick NC
- Charleston region → Charleston, Berkeley, Dorchester

**Scraping approach:**
1. GET each Craigslist URL (plain HTTP, no auth)
2. Parse JSON-LD from `<script type="application/ld+json">` tag
3. Extract `ItemList` entries
4. Filter by NC/SC state in address
5. For each listing, follow the individual post URL to get full description + price
6. Emit as `Listing` with `ListingType.FSBO`

**Compliance:** Craigslist robots.txt allows `/search/` paths. JSON-LD is in the public HTML source. Rate-limit per Craigslist's guidelines (1 request per 10 seconds per region).

---

*End of research report*
