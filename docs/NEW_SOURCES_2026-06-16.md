# Verified Net-New Source Map — 18-County Discovery (2026-06-16)

Every source below was VERIFIED LIVE by a per-county research agent. Excludes
already-covered sources (NC eCourts, SC Public Index lis-pendens, statewide law
firms, national aggregators, federal REO, existing county tax/MIE scrapers).

## CROSS-CUTTING HIGH-VALUE (build these first)

1. **scpublicnotices.com** (SC Press Association) — ONE portal, filterable by
   county + category (Foreclosures, Tax Sales). Covers ALL 7 SC counties'
   foreclosure + tax-sale legal notices in a single scraper. Free, no login.
   NOTE: our existing `publicnoticesc` stub points at the WRONG domain
   (publicnoticesc.com); the real one is **scpublicnotices.com**. Session-based
   search (POST form, set County dropdown).
2. **GovDeals county storefronts** — county-run tax-foreclosure REAL-ESTATE
   auctions (403/JS — needs stealth):
   - Burke NC: seller 29265 (`govdeals.com` — county confirms all Burke tax
     foreclosures run here)
   - Rutherford NC: agency 554
   - Buncombe NC: `govdeals.com/buncombecountync`
   - Cherokee SC: `govdeals.com/en/cherokeecounty`
   - Henderson NC: City of Hendersonville seller (surplus, occasional RE)
3. **Terry Howe & Associates** (`terryhowe.com/auctions/` + `bid.terryhowe.com`)
   — online FLC/tax-forfeited property auctions, per-property catalog w/ photos:
   - Spartanburg SC (recurring, 8–170+ parcels)
   - Laurens SC (~16 parcels)
   - (probe other SC counties — firm runs 200+/yr across SC/NC/GA)

## NC COUNTIES

- **Gaston**: `gastongov.com/669/Tax-Foreclosure-Sales` (HTML, in-rem tax
  foreclosure: addr, parcel, sale date, current/upset bid, file#). Companion
  `/671` = history. TOP.
- **Rutherford**: `rutherfordcountync.gov/departments/revenue_department_tax_administrator/foreclosure_sale_dates.php`
  (HTML: parcel, addr, acreage, file#, current bid, upset deadline, photos) +
  GovDeals agency 554 + `thedigitalcourier.com/classifieds/community/announcements/legal/`
  (BLOX legal index — separate scrape surface from ncnotices) + Cott deeds.
  New substitute-trustee firm name: **Trustee Services of Carolina, LLC** (no own site).
- **McDowell**: `mcdowellnc.gov/departments/tax-collections/tax-foreclosures/upcoming-tax-foreclosure-sales`
  (HTML: parcel, bid, file#, upset deadline; daily updated) + `mcdowellnews.column.us/search` (JS).
- **Transylvania**: `marketplace.transylvaniatimes.com/brevard-nc/public-notices/search`
  (foreclosure + execution/sheriff + tax sales; searchable portal). Tax sales also
  posted to county news feed.
- **Mitchell**: `mitchellnews.com/classified/legals` (newspaper legals; tax
  collector hosts NO online list — this paper is the only web surface). NOTE
  mitchellnewsjournal.com is DEAD.
- **Burke**: GovDeals seller 29265 (all Burke tax foreclosures) + `morganton.column.us/search` (JS notices).
- **Cleveland**: Register of Deeds `us5.courthousecomputersystems.com/clevelandnc/`
  (enrichment, not a listing). NO GovDeals foreclosure. Mostly already covered.
- **Henderson**: `classifieds.gannettclassifieds.com/marketplace/category/legals/public-notices`
  (Gannett iPublish — Times-News legals, filter Hendersonville/28792) +
  City of Hendersonville GovDeals + HiBid (Ramsey Auctions, estate RE).
  Firm: **Law Firm Carolinas** (HOA/COA foreclosures, statewide).
- **Polk**: `marketplace.tryondailybulletin.com/AdHunter/Tryon/Home` (AdHunter —
  foreclosure/trustee notices, per-notice permalinks). Search endpoint
  `/AdHunter/Tryon/Home/Search?Keyword=foreclosure`.
- **Buncombe**: GovDeals `buncombecountync` storefront. ACTION: re-point existing
  Buncombe tax scraper to new domain `taxforeclosures.buncombenc.gov` +
  `media.buncombenc.gov/common/tax/foreclosure-listings/fcl.pdf`.
- **Lincoln**: NONE net-new (all routes through Kania + eCourts, already covered).

## SC COUNTIES (all also covered by scpublicnotices.com)

- **Spartanburg**: Real Estate Tax Sale List PDF (`spartanburgcounty.gov/DocumentCenter/View/104130`)
  + MIE DocumentCenter index 114 (Foreclosure Sale + Cancellations + Results) +
  Terry Howe FLC auctions + Spartan Weekly legals (`spartanweeklyonline.com/id12.html`)
  + ROD `search.spartanburgdeeds.com` + qPublic GIS.
- **Anderson**: direct MIE Sale-List PDFs (`andersoncountysc.org/wp-content/uploads/YYYY/MM/<Month>-<D>-<YYYY>-Sale-List.pdf`)
  + annual tax-sale roster (PostingPro) + `thejournalonline.com` legals +
  `andersonobserver.com/legal-notices` + ACPASS case search.
- **Pickens**: `pickenscountysctax.us` (structured tax-sale portal: parcel, owner,
  amount, sale time, ROR — JS) + `co.pickens.sc.us/departments/delinquent_tax/`
  (tax-sale + FLC PDF) + `yourpickenscounty.com` (Courier + Easley Progress legals)
  + qPublic GIS.
- **Oconee**: `oconeesc.com/delinquent-tax/sale-list` (Google Sheet roster + GIS map)
  + Auditor FLC ArcGIS (`oconeesc.com/auditor-home/forfeited-land`) +
  `upstatetoday.com/classifieds/legal_notices/` (The Journal).
- **Cherokee**: `cherokeecountysc.gov/delinquent-tax/` (annual tax-sale list PDFs)
  + `gaffneyledger.com/classifieds/` (foreclosure + tax notices) + GovDeals
  `cherokeecounty` storefront.
- **Union**: `gearupunionsc.com/departments/delinquent-tax-office/` (tax sale + FLC,
  list via newspaper) + WTH GIS export (`unionsc.wthgis.com`) + Union County News
  (via scpublicnotices). 
- **Laurens**: Terry Howe FLC auctions (Laurens) + `laurenscountyadvertiser.net/delinquent-tax-notices/`
  + `myclintonnews.com` (Clinton Chronicle) + `laurensdeeds.com` ROD.

## BUILD PRIORITY
Tier 1 (max coverage): scpublicnotices.com (all SC), GovDeals multi-county (NC tax
foreclosure), Terry Howe (SC FLC).
Tier 2 (clean HTML): Gaston, McDowell, Rutherford NC tax-foreclosure pages; re-point
Buncombe to new domain.
Tier 3 (newspaper portals): Transylvania Times, Tryon AdHunter, Gannett iPublish
(Henderson), Mitchell News, Column.us (McDowell/Burke), Gaffney Ledger,
Spartanburg/Anderson/Pickens/Oconee/Cherokee tax PDFs + portals.

## BUILD STATUS (updated during build)
- ✅ NC county tax-foreclosure (Gaston/McDowell/Rutherford) — BUILT + tested (nc_county_tax_foreclosure.py), 9 live listings.
- ⏳ scpublicnotices.com — VIABLE via stealth (search "foreclosure"/"tax sale" returns results; 100 pages). Mechanics: fill input[type=text], press Enter, results in GridView #ctl00_ContentPlaceHolder1_WSExtendedGridNP1_GridView1; per-row view button onclick=location.href='Details.aspx?SID=<session>&ID=<id>'. Row cells (title/publication/date) need nested-table parse; detail pages are session-bound. Needs focused iteration — NOT yet shipped.
- ⏳ GovDeals county auctions — reachable via stealth (200, not blocked), BUT it's a React SPA: lot titles render into card components not tied to the asset anchor (/en/asset/<cat>/<id>). Correct approach = hit GovDeals' JSON search API (XHR the SPA calls), filter category=Real Estate, per county seller (Burke 29265 / Rutherford agency 554 / Buncombe buncombecountync / Cherokee). Storefronts are episodic — currently ~0 real estate listed, so live verification needs a cycle with RE present. NOT shipped (don't ship an unverifiable DOM parser).
- ⏳ Terry Howe (SC FLC), Transylvania Times, Tryon AdHunter, Gannett iPublish (Henderson), Mitchell News, Column.us (McDowell/Burke), Gaffney Ledger, SC county tax portals (Pickens/Oconee/Cherokee/Spartanburg/Anderson) — DISCOVERED + URL-verified, NOT yet built. Each is an individual fiddly live-site build.

## NATIONAL / FEDERAL / BANK SOURCES (verified 2026-06-16)

### Worth building (net-new, public, scrapeable, NC/SC inventory)
- **CWS Marketing Group** `cwsmarketing.com/auctions/real-estate/north-carolina-real-estate-auctions/` — US Treasury/IRS/US-Marshals SEIZED real estate. Public (browse free), clean static HTML state pages, confirmed NC inventory. Dedupe vs existing treasury_seized (same program; CWS is the working front-end). TOP federal find.
- **RealtyBid.com** `realtybid.com/auction/NorthCarolina.cfm` + `/auction/southcarolina/` — independent REO/foreclosure auctions, live NC+SC inventory, public, clean ColdFusion pages w/ `?page=N` pagination. TOP national-auction find.
- **Bank of America foreclosures** `foreclosures.bankofamerica.com/search` — public JSON API (session + __RequestVerificationToken POST), state filter, SC inventory now. ONLY viable bank-direct REO (all other banks agent-gated/dead). Low volume but clean.
- **Williams & Williams** `williamsauction.com/real-estate-auction/south-carolina` (backend `bid.auctionnetwork.com`) — auctions, SC residential + NC/SC land, public.
- **RealtyTrac** `realtytrac.com/sc/...` `/nc/...` — high-volume pre-foreclosure/auction/REO, public (not paywalled for listings). Overlaps court/MLS data — dedupe.
- **FDIC** `fdicrealestatelistings.com` — public + scrapeable but ZERO inventory now; build as a dormant monitor (only matters on bank failures).

### Dead ends (do NOT build)
- Bank REO agent-gated/dead: Wells Fargo PAS (offline), Truist/PNC/Citi (res.net login), Chase/US Bank/PennyMac/First Citizens/United Community (no public inventory → MLS/agents). Mr. Cooper = Xome (covered).
- USMS = Bid4Assets (covered). SBA = no portal (GovDeals/Bid4Assets). GSA = surplus not distressed, sparse. IRS irsauctions.gov = timeout-prone + tiny volume + overlaps CWS.
- **Tax platforms have NO NC/SC footprint** (important): RealAuction/GovEase/Zeus serve other states. NC = courthouse-step sales via county law firms (Kania/ZLS); SC = in-house county treasurers. That inventory is county-level, not a national platform.
- ForeclosureListings.com / TaxSaleResources = paywalled re-aggregators.

## REGIONAL BANK / CREDIT UNION REO (verified 2026-06-16 — owner lead)
Big nationals are gated, but regional Carolina institutions post REO publicly:
- ✅ **First Citizens Bank** `firstcitizens.com/real-estate` — BUILT (first_citizens_reo.py). Clean HTML table (Location=<th>), stealth-fetched, NC/SC filtered. Live: 4 NC/SC. 61 scrapers.
- ⏳ **First Bank** `localfirstbank.com/about-us/bank-owned-properties/` — JS-rendered table + map + ZIP-radius search, NC inventory. Needs stealth + structure parse. QUEUED.
- ⏳ **Founders FCU** (upstate SC) `foundersfcu.com/foreclosures` — JS carousel (~9 props, live NC), needs slide-iteration. QUEUED.
- 🔁 **United Community Bank** (Greenville SC) `ucbi.com/properties-for-sale` — Angular list, infra live but EMPTY now; dormant monitor.
- 🔁 **Sharonview FCU** — REO page retired (was live); re-check.
- 🔴 No public REO: SECU (rentals only), SC Federal CU (404), Truliant, Coastal, Self-Help, Allegacy, Greenville FCU, Pinnacle, FNB, Bank OZK.

## CLOUD FEASIBILITY (honest, 2026-06-16)
The local-only constraint = datacenter-IP + headless fingerprint getting blocked on hard anti-bot sites (NOT "cloud can't"). Options:
- Free + full coverage → must run local (Mac residential IP). [current]
- Cloud + full coverage → needs PAID residential proxy (~$50-500/mo) or paid scraping API. Against free rule.
- FREE middle ground: self-hosted GitHub Actions runner ON the Mac — GitHub schedules it, executes on Mac's IP, no 4h cap. Best automation+IP combo; consider later.
- The 4h GitHub cap alone is solvable (split sub-4h jobs / self-hosted runner); the IP is the real constraint.
