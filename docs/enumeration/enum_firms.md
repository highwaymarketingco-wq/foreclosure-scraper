Verified 2026-08-03 against the live web. Footprint read from `/Users/cashhigh/foreclosure-scraper/src/foreclosure_scraper/config.py`: **SC (7)** Spartanburg, Anderson, Pickens, Oconee, Cherokee, Union, Laurens; **NC (11)** Rutherford, Cleveland, Henderson, Polk, Gaston, Buncombe, Transylvania, McDowell, Lincoln, Mitchell, Burke. Already-scraped status cross-checked against `scrapers/{law_firms,newspapers,public_notices,national,reo}` and the 25,552-row board in `docs/listings.json`.

Access classes: **A**=free static, no auth/CAPTCHA · **B**=free but form/session postback · **C**=free but JS-rendered, needs API or browser · **D**=WAF/403 · **E**=dead/parked · **F**=ToS click-gate

| # | Publisher | Cat | Query-ready URL | Fields / yield (verified) | Access | Status |
|---|---|---|---|---|---|---|
|1|Hutchens/Foundation|Firm|`sales.hutchenslawfirm.com/SCfcSalesList.aspx` · `/NCfcSalesList.aspx`|Case No, Case Docket#, County, Sale Date, Property Address, CSZ, **DoT Book/Page**, Bid Amount, Deficiency. 32 SC counties incl. Anderson/Cherokee/Oconee/Pickens/Spartanburg. No CAPTCHA|A|SCRAPED (38 rows)|
|2|Brock & Scott|Firm|`brockandscott.com/foreclosure-sales/`|200, 480KB, NC+SC|A|SCRAPED (70)|
|3|Shapiro & Ingle / LOGS|Firm|`logs.com/nc-upcoming-sales-report.html` + PowerBI `app.powerbi.com/view?r=eyJrIjoiOTQwOTdiYWY…`|200, 53KB|A/C|SCRAPED (42)|
|4|ALAW (Albertelli)|Firm|`alaw.net/foreclosure-sales/north-carolina/` · `/south-carolina/`|200, 304KB. **Footprint hits today: Cleveland ×2 only**|A|SCRAPED, thin|
|5|Aldridge Pite|Firm|`aldridgepite.com/sale-day-listings-selection/foreclosure-listings-north-carolina/`|200, 128KB. **Zero footprint counties today**|A|SCRAPED, nil|
|6|Rogers Townsend|Firm|`rogerstownsend.com/reports/SC_Listings.pdf`|101KB PDF, monthly ~18th, bid added day-before. **`NC_Listings.pdf` returns 404 — NC leg is dead, firm is SC-only now**|A|SCRAPED + **BUG**|
|7|Bell Carrington Price & Gregg|Firm|`bellcarrington.com/foreclosure-sales/`|200, 77KB|A|SCRAPED (17)|
|8|Finkel Law|Firm|`finkellaw.com/images/Webs.pdf`|55KB PDF, monthly SC pre-sale list|A|SCRAPED, 0 board rows|
|9|McMichael Taylor Gray|Firm|Google Sheets export|—|A|SCRAPED (13)|
|10|The Ingle Firm|Firm|`theinglefirm.com/Sales.aspx`|200, 28KB. Footprint: Union ×1, Rutherford ×1|A|SCRAPED, thin|
|11|Kania Law (NC tax fc)|Firm|`kanialawfirm.com/tax-foreclosures/foreclosure-listings/` (WP `admin-ajax.php`)|200, 109KB|C|SCRAPED, 0 rows|
|12|Korn Law Firm|Firm|`kornlawfirm.com/sales/`|`/foreclosure-sales/` is a **1.1KB empty stub**; `/sales/` shows no footprint county|A|SCRAPED, 0 rows|
|13|Zacchaeus Legal Services|Firm|`zls-nc.com/listings`|200, 24KB, 0 footprint counties|A|SCRAPED, 0 rows|
|14|Mewborn & DeSelms|Firm|`mewbornlaw.biz`|**403 WAF**|D|SCRAPED, blocked|
|15|**Scott & Corley → McCalla Raymer Leibert Pierce**|Firm|`scottandcorley.com` **301→** `mccalla.com`; sales at `foreclosurehotline.net/Foreclosure.aspx`|SC firm absorbed. Hotline state picker = **AL, GA, IL, MS, TX only. No SC, no NC**|A|**NEW, nil yield**|
|16|**RAS Crane / Robertson Anschutz Schneid**|Firm|`raslegalgroup.com` → `rascranesalesinfo.com/Default.aspx`|All 50 states displayed but only **CA, GA, TN, TX are clickable** (`redirectToState()`). 15 "RAS" mentions in board text, so they file here but publish nothing|A|**NEW, nil yield**|
|17|Rubin Lublin → RLS|Firm|`rlselaw.com/property-listing`|ToS click-gate before listings; NC/SC coverage unconfirmed|F|NEW, low|
|18|Padgett Law Group|Firm|`padgettlawgroup.com/foreclosure`|`/sales/` and `/foreclosure-sales/` both 404. **No public list.** 9 board mentions|—|NEW, no list|
|19|Riley Pope & Laney|Firm|`rplfirm.com`|NC+SC default servicing, **no sale list**. 14 board mentions|—|NEW, no list|
|20|Crawford & von Keller|Firm|`crawfordvk.com/foreclosures/`|Now SC+NC+TN. **No sale list.** 20 board mentions|—|NEW, no list|
|21|Sottile & Barile|Firm|`sottileandbarile.com`|`/sales/` 404|—|NEW, no list|
|22|Trustee Services of Carolina|Firm|`trusteeservicesofcarolina.com`|**Parked domain (`/lander`)**|E|DEAD|
|23|Substitute Trustee Services Inc|Firm|`substitutetrusteeservices.com`|**Does not resolve.** Named constantly in NC notices, publishes nothing|E|DEAD|
|24|Nationwide Trustee Services|Firm|`nationwidetrustee.com`|**Does not resolve**|E|DEAD|
|25|Hunoval Law|Firm|`hunovallaw.com`|114-byte stub|E|DEAD|
|26|Goddard & Peterson · Grimsley · Nodell Glass & Haskell · Ward & Smith|Firm|—|Confirmed prior finding: publish no sale list|—|no list|
|27|**scpublicnotices.com (SC Press Assn SmartSearch)**|Notices|`scpublicnotices.com/Search.aspx` (county checkbox `lstCounty$N` + `dateRange` + `ddlPopularSearches`)|**114 SC publications**, every footprint paper. Taxonomy: Foreclosures, Delinquent Taxes, **Notice to Creditors**, Probate Notices, Tax Sales, Public sales, Forfeitures/Seizure. Spartanburg/Cherokee/Laurens confirmed in county list. No login, no CAPTCHA. **Same ASP.NET engine as ncnotices.com, which the repo already drives**|B|**NEW — biggest gap**|
|28|ncnotices.com (NC Press Assn)|Notices|`ncnotices.com/Search.aspx`, `/Details.aspx?ID=`|141 NC publications|B|SCRAPED|
|29|Column|Notices|`us-central1-enotice-production.cloudfunctions.net/api/search/public-notices`|`publicnoticesc.com` and `notices.column.us` are the same Column SPA|C|SCRAPED|
|30|**publicnoticeads.com**|Notices|—|**Parked domain, serves `/lander`. Named in the task brief but it is gone.** `mypublicnotices.com` also dead|E|**DEAD**|
|31|**Laurens County Advertiser**|Paper (Laurens SC)|`laurenscountyadvertiser.net/wp-json/wp/v2/posts?categories=17&per_page=100` (Obituaries, **2,343 posts**) · `categories=7486` (Notice To Creditors)|Open WP REST, **serving real content** (verified decedent names + ISO dates + permalinks). Only free Laurens SC route|A|**NEW**|
|32|**Tryon Daily Bulletin**|Paper (Polk NC)|`tryondailybulletin.com/wp-json/wp/v2/posts?categories=35` (Obituaries, **5,675 posts**) · `categories=263` (Public Notices)|Open WP REST. Repo already scrapes this host for foreclosure legals via `?s=` search only — the obit category is untouched|A|**NEW (partial host)**|
|33|The Gaffney Ledger|Paper (Cherokee SC)|`gaffneyledger.com/wp-json/wp/v2/categories?slug=obituaries` → id 44, **17,856 posts**|WP REST exposes **taxonomy counts only**; `/wp/v2/posts` returns `[]` for every query incl. unfiltered. Content is REST-gated. `/feed/` works (32KB) but is news, not legals|A/F|NEW, metadata only|
|34|The Easley Progress|Paper (Pickens SC)|`theeasleyprogress.com/wp-json/wp/v2/posts?search=`|WP REST open, **zero legal/obit content**|A|NEW, nil|
|35|Transylvania Times · McDowell News · Morganton News Herald · Lincoln Times-News|Papers (4 NC cos.)|`/classifieds/community/announcements/legal/?f=rss` and 6 slug variants|**All TownNews/TNCMS, all return 0 `<item>`.** Only `/search/?f=rss&q=foreclosure&t=article` works and it returns **editorial articles, not notices**. The online legal-classified lane does not exist for these four counties|—|**NEW, confirmed nil**|
|36|Mitchell News-Journal · Union Daily Times · Union County News · Clinton Chronicle · Pickens County Courier · Keowee Courier · Westminster News · The Journal (Seneca/upstatetoday) · Woodruff Times · The Journal (Williamston) · Hendersonville Tribune · Mountain Xpress|Papers (12)|—|**No WP REST, no legal RSS.** uniondailytimes.com 404s every path. Reachable only through #27/#28|—|NEW, nil|
|37|Gannett papers (citizen-times, blueridgenow, gastongazette, shelbystar, thedigitalcourier, goupstate, greenvilleonline, independentmail)|Papers|`/obituaries/` Tukios HTML|8 hosts|A|SCRAPED (108 rows)|
|38|Shelby Star · Daily Courier · Hendersonville Lightning · Index-Journal · Post & Courier · Coastland Times · Carolina Coast|Papers|TownNews legal RSS `?f=rss&q=foreclosure`|—|A|SCRAPED|
|39|Spartan Weekly News|Paper (Spartanburg)|repo module|150 rows|A|SCRAPED|
|40|Auction.com|Auction|`auction.com/residential/nc/` · `/sc/`|—|C|SCRAPED (14)|
|41|Bid4Assets|Auction|`bid4assets.com/storefront/index.cfm?searchstate=NC&searchprop=Real+Estate` (+SC)|—|A|SCRAPED|
|42|Hubzu|Auction|`hubzu.com/portal/auctions?state={ST}&pageSize=200`|—|A|SCRAPED (23)|
|43|Xome|Auction|`xome.com/auctions/foreclosure-homes` · `/bank-owned`|—|A|SCRAPED (9)|
|44|ServiceLink Auction (**= Hudson & Marshall**, now redirects here)|Auction|`ui.exostechnology.com/api/listingsvc/v1/listings?limit=100&state={ST}`|**hudsonandmarshall.com now 301s to servicelinkauction.com — not a separate source**|A|SCRAPED (21)|
|45|GovDeals|Auction|repo `nc_govdeals_real_property`|Akamai, needs `curl_cffi impersonate=chrome`|D→A|SCRAPED|
|46|**AllSurplus**|Auction|`allsurplus.com/assets?categories=Real%20Estate&locations=North%20Carolina`|**403.** Liquidity Services sibling of GovDeals, same real-property inventory already captured|D|NEW, redundant|
|47|**Ten-X**|Auction|`ten-x.com`|**403 to plain HTTP.** Commercial-only since the Auction.com split|D|NEW, wall|
|48|**RealtyBid**|Auction|`realtybid.com/search?state=NC`|200 but **11KB SPA shell**, all inventory behind an XHR|C|**NEW**|
|49|**Municibid**|Auction|`municibid.com/search/?q=real+estate&state=North+Carolina`|200, 224KB server-rendered|A|**NEW, low-med**|
|50|**PublicSurplus**|Auction|`publicsurplus.com/sms/all,nc/browse/cataucs?catid=15`|200, 75KB but **JS grid, 0 static `auc=` links**. Government sellers, mostly vehicles|C|NEW, low|
|51|**Concierge Auctions**|Auction|`conciergeauctions.com`|200, 547KB. Luxury-only, effectively zero WNC/Upstate distress|A|NEW, nil|
|52|**Tranzon**|Auction|`tranzon.com/buy-residential-property-auctions.aspx` · `/buy-commercial-property-auctions.aspx`|200. Regional network with NC affiliates; bank-ordered, estate and bankruptcy-trustee real estate|A|**NEW**|
|53|**Iron Horse Auction Co.** (Rockingham NC)|Auction|`ironhorseauction.com`|200, 70KB. Bankruptcy-trustee and bank-ordered NC real estate. `www.` variant fails, use apex|A|**NEW**|
|54|**Rogers Realty & Auction** (Mount Airy NC)|Auction|`rogersrealty.com`|200, 53KB|A|**NEW**|
|55|**Williams & Williams**|Auction|`williamsauction.com` (`/Search/State/NC` 404)|200, 1.4MB home; correct search path not yet found|A|NEW, unverified|
|56|Fannie HomePath · Freddie HomeSteps · HUD HomeStore · First Citizens REO · VRM/VA · USDA RD · GSA · Treasury seized|REO|repo modules|—|A|SCRAPED|
|57|**legacy.com**|Obits|`legacy.com/us/obituaries/local/north-carolina/asheville` (per city/county, both states)|909KB **server-rendered**, `/obituaries/name/{slug}-obituary` per decedent, 2× `application/ld+json`. **robots.txt disallows `/newspaper/obituaries/`, `/obituaries/name2/`, `/obituaries/*/api/` — the `/us/obituaries/local/` browse path is NOT disallowed.** Aggregates every funeral home in all 18 counties|A|**NEW**|
|58|**echovita.com**|Obits|`echovita.com/us/obituaries/nc/asheville`|137KB, **83 obit permalinks on one city page**, name+id slugs. robots.txt is almost entirely commented out; only `obituary-pdf-*` disallowed|A|**NEW**|
|59|tributearchive.com|Obits|—|**Cloudflare 403 on robots.txt itself**|D|NEW, wall|
|60|dignitymemorial.com|Obits|`/obituaries/asheville-nc`|**403 (Akamai)**|D|NEW, wall|
|61|Funeral-home RSS (Frazer `/feed`, WP `?feed=rss2&post_type=ltobits`)|Obits|3 hosts: grocefuneralhome, cecilmburtonfuneralhome, sullivanking|Pattern works; only 3 of ~60 footprint homes wired|A|SCRAPED, expandable|
|62|estatesales.net|Estate|`estatesales.net/NC/Asheville/28801`|200, 290KB. robots allows listing pages (blocks `/api/user-view-details`, `/v2`, `/v3`)|A|SCRAPED (9 rows)|
|63|estatesale.com|Estate|`estatesale.com`|**Returns a 212-byte shell now** — companion scraper likely dead|C|SCRAPED, check|
|64|**auctionzip.com**|Estate|auctioneer/catalog pages only|200, 131KB, but **robots.txt disallows `/search` and `/search-results`** — keyword search is off-limits, only per-auctioneer catalog pages are compliant|A (constrained)|**NEW**|

## Top 5 net-new

1. **scpublicnotices.com — SC Press Association SmartSearch.** The single largest hole in the whole map. All 7 SC footprint counties, 114 publications, with a first-class notice taxonomy (Foreclosures / Delinquent Taxes / Notice to Creditors / Probate Notices / Tax Sales / Public sales / Forfeitures). Free, no login, no CAPTCHA, county checkbox filter and date range. It runs the identical ASP.NET SmartSearch engine as ncnotices.com, which `public_notices/ncpublicnotices.py` already drives, so this is a parameterization of existing code rather than a new parser. It is also the only free route to legals for the 12 SC/NC papers that expose no API at all (Union Times, Pickens County Courier, Keowee Courier, The Journal Seneca, Westminster News, Woodruff Times, and others).

2. **legacy.com local obituary browse.** Biggest expansion of the death signal, which is the earliest motivated-seller trigger in the estate funnel. Server-rendered HTML with per-decedent name slugs and JSON-LD, covering every town in all 18 counties, versus the 8 Gannett papers plus 3 funeral-home RSS feeds currently wired. robots.txt permits the `/us/obituaries/local/` browse path. Feeds straight into the existing name-to-parcel resolver.

3. **Laurens County Advertiser open WP REST.** `?categories=17` returns 2,343 obituaries with clean names and dates; `?categories=7486` is a dedicated Notice To Creditors category. Laurens SC has no Gannett obit page and no working paper API otherwise, so this is the only free county-level route. Verified serving live content, not just taxonomy counts.

4. **Tryon Daily Bulletin Obituaries category (id 35, 5,675 posts).** The repo already hits this host for foreclosure legals through `?s=` string search but never touched the REST obituary category. Polk NC death signal for the cost of one additional endpoint on a host already in the crawl plan.

5. **echovita.com.** Second independent obituary aggregator, 83 permalinks on a single city page, permissive robots.txt, different funeral-home coverage than legacy.com. Cheap redundancy against the two walled competitors (tributearchive and dignitymemorial are both hard-403).

**One bug worth fixing regardless:** `rogerstownsend.com/reports/NC_Listings.pdf` now returns 404. `law_firms/rogers_townsend.py` still requests it. The firm is SC-only now; the SC PDF is healthy at 101KB.

**Anti-category result worth recording so it is not re-searched:** McCalla (which absorbed Scott & Corley) and RAS Crane both operate a public sale portal and both **exclude NC and SC** from it. Padgett, Riley Pope & Laney, Crawford & von Keller and Sottile & Barile all litigate in the footprint and publish no list at all. Trustee Services of Carolina, Substitute Trustee Services Inc, Nationwide Trustee Services and Hunoval Law have no live site. The four Lee/TownNews WNC papers (Transylvania Times, McDowell News, Morganton News Herald, Lincoln Times-News) return zero items on every legal-classifieds RSS slug tried. publicnoticeads.com and mypublicnotices.com are parked domains.

No repo writes, no git operations, no scraping beyond public unauthenticated pages and published robots-permitted paths.