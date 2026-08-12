# Coverage Gap Analysis: Missing Lead Sources (2026-07-03)

Style: no em dashes; colons, parentheses, and periods only.

## Current Coverage (22 categories, 112 scrapers)

The engine covers: judicial foreclosure (SC), power-of-sale foreclosure (NC, partial), pre-foreclosure/lis pendens, tax delinquency (16 counties), probate/estates, divorce, bankruptcy, REO (8 feeds), ROD recordings, elderly exemptions (Buncombe only), storm damage (Asheville only), code enforcement (Asheville only), vacant properties (Spartanburg only), state tax liens, HOA (Charleston only), incarceration (SCDC only), GIS/parcel, phone matching (NC voter file), auction sites (5), newspapers (8+Column), NOD recordings (partial).

## Missing Sources (25 gaps, ranked by value and feasibility)

### BUILD_NOW (free, public, scrapable, high-value)

1. **Sheriff sales.** NC sheriffs post foreclosure sale notices on county sheriff websites. SC sheriffs handle execution sales. These are separate from clerk/MIE sales. URL: per-county sheriff office websites. Status: not built.

2. **Upset bid listings.** NC has a 10-day upset bid period after foreclosure sale (NCGS 45-21.27). Counties post upset bid properties online. Currently only detected via Judgment Search orderedDate, not from county upset bid pages. URL: per-county clerk of court websites. Status: not built.

3. **FEMA flood zone data.** FEMA NFHL ArcGIS REST service (hazards.fema.gov/gis/nfhl/rest/services/public/NFHL/MapServer) is free, no key. Post-Helene flood maps changed. Per-lead flood flag for prioritization. Status: not built. Listed in blueprint Section 7 as BUILD-READY.

4. **Land auction sites.** Have Bid4Assets and Auction.com. Missing: LandWatch.com, LandAndFarm.com, LandsofAmerica.com, GovernmentAuction.com. Critical for land wholesale play. Status: not built.

5. **Greenville SC probate.** Standalone ASP.NET index at greenvillecounty.org/appsas400/Probate/SearchResults.aspx?LastName=X. Plain GET, no viewstate, live-tested 5,637 rows, zero WAF. Upstate hub bordering core. Currently 0 leads. Status: BUILD-READY (blueprint Section 7 item 9).

6. **SC case detail pages (HKey).** CaseDetails.aspx popouts have judgment amounts, full party info, disposition, case history. Need HKey postback mechanism (server-generated key from ViewState POST). The JavaScript approach from the operator guide works: extract case numbers from results table, fire parallel POST requests to get HKey URLs, then fetch detail pages. Status: mechanism understood, not built.

7. **Opportunity zone data.** IRS/HUD opportunity zone maps are free. Not a lead source per se, but a flag for dispo marketing to developers. Status: not built. Listed in blueprint Section 7.

8. **FEMA disaster declarations.** Public FEMA API (www.fema.gov/api/open/v2/DisasterDeclarationsSummaries). Helene declarations are public. SBA disaster loan data is also public. Status: not built.

9. **Cash buyer deed pulls.** Recent no-mortgage purchases from ROD index = active cash buyers = dispo targets. ROD index already accessed for NODs. Would query recent deeds where deed type = warranty/special warranty and no simultaneous DOT recorded. Status: not built.

10. **USPS vacancy data.** HUD aggregated USPS vacancy data (huduser.gov, free gov/nonprofit registration, USPSVacancydata@hud.gov). Authoritative vacancy scoring by ZIP/tract. Status: not built. Listed in blueprint Section 7.

### BUILD_READY (endpoints identified, needs code)

11. **Jail bookings.** P2C jqGrid (Cleveland), Zuercher (Cherokee/Anderson SC), Southern Software Citizen Connect (Henderson), Buncombe CentralSquare P2C (open JSON, 540 in custody, live-verified), Greenville SC LANSA WEBEVENT, Gaston New World WebForms. Some carry full DOB. Status: BUILD-READY (blueprint Section 7 item 12).

12. **Senior exemption diversification.** 100% Buncombe concentration (3,505 leads = 20% of board on one county). BUILD-READY endpoints identified for more counties. Status: priority fragility item.

13. **Partition actions (NC).** Ride the Judgment JSON if a partition cause label exists. Check the live cause_distribution log. Low effort. Status: verify label, then wire.

### PARTIAL (have some coverage, gaps remain)

14. **FSBO listings.** Craigslist is scrapable (robots.txt allows for most cities). Zillow FSBO filter works. Land.com for land FSBO. Free listings by owners = motivated sellers. Status: not built.

15. **Building/demolition permits.** Some cities have open portals (Spartanburg, Asheville, Hendersonville). Most need probing. Permits indicate construction activity, distress, or tear-downs. Status: not built (except Asheville STR permits).

16. **NOD recordings (NC).** Logan ROD + substitute trustee deeds only. Not all counties covered. Status: partial.

17. **Estate sale companies.** EstateSale.com and Estatesales.net list companies handling estate liquidations. Properties being sold. Status: not built.

18. **Zoning change notices.** Planning board agendas indicate upzoning/rezoning = developer opportunity. Vary by county. Status: not built.

19. **Road projects / eminent domain.** NCDOT and SCDOT publish project lists. Properties in path of road widening = forced sellers. Need per-county project mapping. Status: not built.

20. **Land bank properties.** NC has land banks (Asheville, Charlotte area). SC has county land bank authorities. Discounted properties. Need to find URLs. Status: not built.

21. **Tax sale redemption properties.** NC: 10-day upset bid. SC: 1-year redemption. Properties in redemption period are leads. Status: not built.

### FOIA_REQUIRED (free but needs records request)

22. **Water/utility delinquency.** City water departments have delinquent lists. Properties with shut-off water = distress signal. Usually requires FOIA. Status: not built.

23. **Code violation/lien databases.** Beyond Asheville, most counties need FOIA for code violation data. Status: not built.

### WALL (not free/public/compliant)

24. **MLS expired/withdrawn listings.** Agent/partner only. Not public. Status: wall.

25. **Short sale listings.** MLS only, not separately published. Partially caught by Realtor.com distressed filter. Status: wall.

26. **FB Marketplace.** Requires login, ToS prohibits scraping. Status: wall.

## Priority Build Order

Ranked by (value x feasibility x lead volume):

1. SC case detail pages (HKey) - enriches 2,649 existing cases with judgment amounts
2. Greenville SC probate - 5,637 rows tested, zero WAF, zero new code pattern
3. Sheriff sales - NC counties post these free
4. Upset bid listings - NC counties post these free, 10-day window
5. FEMA flood zone data - free ArcGIS REST, per-lead flag
6. Jail bookings - endpoints verified, skip-trace gold (DOB)
7. Land auction sites (LandWatch, LandAndFarm, LandsofAmerica) - land wholesale
8. Cash buyer deed pulls - dispo target identification
9. USPS vacancy data - free HUD registration, vacancy prioritization
10. Senior exemption diversification - de-risk 20% board concentration
11. FSBO (Craigslist + Zillow) - motivated sellers
12. FEMA disaster declarations - Helene data
13. Estate sale companies - estate liquidation properties
14. Opportunity zone data - dispo marketing flag
15. Road projects (NCDOT/SCDOT) - eminent domain leads
16. Building permits - distress/tear-down signal
17. Zoning change notices - developer opportunity
18. Land bank properties - discounted properties
19. Tax sale redemption - redemption period leads
20. NOD recordings expansion - more NC counties
