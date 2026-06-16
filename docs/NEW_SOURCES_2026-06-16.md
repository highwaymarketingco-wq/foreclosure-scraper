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
