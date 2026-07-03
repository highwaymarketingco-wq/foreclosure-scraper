# Motivated-Seller Playbook: Strategy + Sources + Buyers + Keywords

Companion to the existing tools playbook and gap ledger. Weighted toward FREE and toward the Western NC + Upstate SC footprint. Every process carries all four parts: strategy, sources, buyers, keywords. Compliance frame baked into every lane: **SC HB4754 (enacted May 29, 2024, already in force)** and **NC HB797 (eff. Oct 1, 2025)** both fold residential wholesaling into licensed brokerage, so **land and creative finance are the compliant unlicensed lanes** and residential deals must run as licensed-broker, double-close-and-market-after-title, or (in SC only) contract-assignment structures. See the Compliance Note at the end for the exact statutory nuance, including the NC-vs-SC split on assignment.

---

## 1. PRE-FORECLOSURE

### Strategy / how-to
Pre-foreclosure is the window between the first public filing (in NC/SC that is the notice of hearing / lis pendens, judicial power-of-sale states) and the auction. The owner still holds title and can sell as a normal transaction. The whole game is timing plus follow-up:

- **Outreach window = 14 to 60 days after filing.** Days 0-30 the owner is often in denial ("ostrich effect"); days 31-60 motivation climbs; after 60 competition and overwhelm rise. Do not wait until days-before-auction (you lose leverage and compete with auction buyers).
- **Door-knock first.** High-pain defaulters do not answer phones or open mail. Lead with empathy, position as a backup plan, never say "foreclosure" (say "challenging situation"). Present paths, not pressure: reinstatement, loan mod, short sale, subject-to, short leaseback.
- **Follow-up wins deals.** Most close between the 3rd and 8th touch; the sales research sweet spot is the 6th-12th contact. Cadence: Day 1 call, Day 3 call, Day 5 text, Day 7 call, Day 14 call, Day 21 handwritten mail, monthly until sold or auction.
- **Pick the exit by equity:** 20%+ equity = negotiate purchase/reinstatement; near-zero equity + low locked-in rate = subject-to (only needs the loan reinstated, not paid off); underwater = short sale.
- **NC compliance wall:** NC 75-121 makes a "foreclosure rescue transaction" for gain unlawful unless the buyer pays the owner at least 50% of FMV via a certified appraisal (<=120 days old) delivered 7+ days before the owner is obligated. This kills lowball equity-grabs on NC defaulting owners. Compliant lanes: licensed broker with a >=50% FMV appraised offer, or genuine creative finance where the seller keeps equity/upside (subject-to, seller-carry). In SC, contract assignment stays viable (HB4754 excludes "assigning or offering to assign a contractual right to purchase").

Best free learning resources:
- Pace Morby, "Step-by-Step Guide to Pre-Foreclosure Investing" (2h43m) https://www.youtube.com/watch?v=z3MF3x2fG2Y
- Pace Morby, "What to Say to Sellers on the Phone | Creative Finance" https://www.youtube.com/watch?v=bKMcgnoYXfQ
- BiggerPockets Podcast #527 (Pace Morby, 100% creative financing) https://www.biggerpockets.com/blog/biggerpockets-podcast-527-pace-morby
- FlipMantis pre-foreclosure scripts (copy-paste) https://flipmantis.com/pre-foreclosure-scripts
- DealMachine practitioner walkthrough (backup-plan positioning) https://www.dealmachine.com/blog/how-to-invest-in-pre-foreclosures-real-estate-tips

### Sources
- NC statewide legal notices (search "Foreclosure"): https://www.ncnotices.com/Search.aspx (NC Press Association ASP.NET __doPostBack site; the SAME platform powers county subdomains e.g. legalnotices.guilfordcountync.gov, so one parser generalizes across NC counties)
- SC statewide public notices (Foreclosures / Delinquent Taxes / Tax Sales): https://www.scpublicnotices.com/ (SC Press Association aggregator)
- NC Clerk of Superior Court (foreclosures filed as special proceedings); Register of Deeds for lis pendens/NODs: https://www.nccourts.gov/help-topics/court-records/obtaining-court-records
- SC Master-in-Equity + county Public Index (ToS-no-scrape, so use the newspaper-notice feed + manual court-export lane)
- County register-of-deeds portals: grantor-grantee index, filter doc types NOTICE DEFAULT / LIS PENDENS / NOTICE OF SALE, last 7-30 days
- Bankruptcy (PACER, Chapter 7/13): distressed owners shedding property surface here; PACER is $0.10/page with a fee-waiver under $30/quarter tier, so low-volume pulls are effectively free. Footprint-agnostic distressed signal. https://pacer.uscourts.gov/
- National newspaper-notice aggregator: https://usalegalnotice.com/
- Free-with-delay listing cross-checks: Foreclosure.com, Auction.com, Hubzu, Xome, Zillow pre-foreclosure filter, HUDHomeStore
- Scrapers to extend/study: your own `highwaymarketingco-wq/foreclosure-scraper` (add ncnotices + scpublicnotices parsers); `Cerulean-Web-Consulting/lis_pendens_scraper`; `Zackthehouseguy/jefferson-lis-pendens-scraper`; `Elevated5/PreForeclosure-Scraper`
- Architecture benchmark (validates "scrape the press-association feed daily," FL/NJ/TX/IL only for now): https://noticeregistry.com/

### Buyers / dispo
- **County recorder deeds (top free method):** pull deeds from last 6-12 months with NO concurrent mortgage/deed-of-trust = cash buyer. Grab name/LLC + mailing address, dedupe LLCs, skip-trace.
- Foreclosure-auction winning bidders (cash by definition) via Hubzu/Auction.com/Williams & Williams; look up the LLC registered agent (use the NC SoS agent enricher).
- REIA / BiggerPockets meetups; local FB groups ("[city] real estate investors / wholesalers / house flippers").
- Craigslist + FB Marketplace "we buy houses" advertisers ARE cash buyers; "Google Ninja trick" (search "we buy houses [city]" and email the ranking sites).
- Driving-for-dollars dispo angle (active rehab sites), title company / closing attorney / hard-money-lender referrals, multi-unit landlords.
- Segment A/B/C (proven closers w/ POF first). Tool: `crubinovega/buyer_scraper`.

### Related keywords
what is pre-foreclosure; pre-foreclosure vs foreclosure; notice of default meaning; lis pendens meaning; how does the foreclosure process work; foreclosure timeline by state; pre-foreclosure investing strategy; how to buy a house in pre-foreclosure; subject to real estate explained; reinstatement vs short sale; how to stop foreclosure; North Carolina foreclosure process; South Carolina foreclosure timeline; foreclosure rescue scam laws; door knocking foreclosure script; pre-foreclosure homes for sale [county]; pre-foreclosure list [county]; notice of default list free; lis pendens list [county]; foreclosure listings Upstate SC; we buy houses in foreclosure; sell my house before foreclosure; stop foreclosure [city]; sell house behind on payments; sell house as is [city]; sell house that needs repairs; NC foreclosure notice search; SC public notices foreclosure.

---

## 2. FORECLOSURE / AUCTION / REO

### Strategy / how-to
Three stages, three different plays:

- **Pre-foreclosure** (covered above) is the only stage that maps cleanly onto direct negotiation.
- **Auction (trustee/sheriff/Master-in-Equity sale)** is a cash-and-nerve play: cash within 24-48h, no interior inspection, title as-is, inherit surviving liens/occupants.
  - Max-bid discipline is everything: `Max Bid = ARV - repairs - resale costs - profit (10-20%)`. The 70% rule shorthand: never bid over 70% of ARV minus repairs. Set the number before auction day.
  - Title search BEFORE bidding ($100-250) is the #1 killer to avoid. The foreclosing lien is extinguished; junior liens may survive by priority. Read the opening-bid disclosure to learn whether the 1st (wipes juniors) or a 2nd (senior mortgage survives) is foreclosing. IRS liens carry a 120-day redemption.
  - Drive-by + occupancy check (add ~5% for occupied, watch vacant vandalism/water damage).
  - **Upset-bid mechanics (footprint-specific):** NC has a 10-day upset-bid period (G.S. 45-21.27; raise >=5% or min $750, each upset restarts the clock). SC has a 30-day upset-bid window (SC Code 15-39-720), only if the bank did NOT waive deficiency. SC has NO statutory redemption on mortgage foreclosures. The upset bid is itself a buying channel: enter a 5%+ higher bid at the clerk/Master's office during the window without attending the original sale.
- **REO (bank-owned)** is a paper/process play: speed beats price (7-14 day cash / 21-day financed). Clean offer package = purchase agreement + all bank addenda + current proof of funds + 2-3% earnest money attached + one-page CMA cover letter. Kill contingencies (keep title only, 5-7 day inspection max). Cherry-pick REOs 60+ days on market with price cuts.
- **Wholesale-the-auction / wholesale-REO (compliant nuance):** banks and HUD/Fannie/Freddie prohibit assignment, so double-close (A-B-B-C) via transactional funding (1-3%, min ~$750-2,500, same-day close + same title company). Legal in NC/SC because you actually take title, sidestepping the residential-wholesaling wall. Note: in NC even a plain contract assignment is now brokerage, so double-close is the ONLY compliant residential path there; SC still allows assignment.

Best free learning resources:
- BiggerPockets, "How to Buy a House at Auction" https://www.biggerpockets.com/blog/buying-house-auction
- BiggerPockets, "Buying Foreclosures at Auction: How to Avoid Overpaying" https://www.biggerpockets.com/blog/buying-foreclosures-auction-how-to-avoid-overpaying
- Kris Haskins courthouse-steps ride-along https://www.youtube.com/watch?v=3xVw-ZjTQK8
- Real Estate Skills, "How To Find Houses In Foreclosure (FAST & FREE)" https://www.youtube.com/watch?v=XELN2DDG9t4
- Auction.com guide https://www.auction.com/blog/how-to-buy-foreclosures-at-auction/ and Kiavi's foreclosure guide https://www.kiavi.com/blog/the-reis-guide-to-foreclosures-6-steps-to-finding-auction-properties

### Sources
Free national browse: Auction.com https://www.auction.com/residential ; Xome; Hubzu; HUD HomeStore https://www.hudhomestore.gov/ ; Fannie HomePath; Freddie HomeSteps https://www.homesteps.com/ ; USDA-RD resales https://properties.sc.egov.usda.gov/resales/public/home (rural NC/SC relevant); HUD federal seller hub http://www.hud.gov/helping-americans/homes-for-sale ; https://www.usa.gov/real-estate-sales

Government-surplus / low-competition: county-owned and back-tax surplus property lists (many footprint counties post "county-owned property for sale" pages); GovDeals real-estate category (Akamai-walled, use the curl_cffi impersonate bypass); GSA and municipal surplus rosters. These are free and rarely worked by competitors.

Footprint court sources: NC foreclosures filed with Clerk of Superior Court (notices posted at courthouse + county paper; upset bids filed with clerk). SC foreclosures via county Master-in-Equity rosters on the SC Judicial Public Index (Court Agency = "Master in Equity"); county M-i-E pages post monthly rosters + Sale Books, e.g. https://lex-co.sc.gov/departments/master-equity/judicialforeclosure-sales-information-and-links . SC PublicIndex is ToS-no-scrape (manual court-export lane). Verify per-county before assuming salesweb.civilview.com coverage (public scraper repos only enumerate NJ counties).

Scrapers to study (all target the salesweb.civilview.com vendor pattern; write one parser per vendor, not per county): `alevillada/sheriff-sale-scraper` (Scrapy + scrapy-playwright); `chee86j/prop_pilot` (county->{id,url} registry); `JimLynchCodes/Fork-Lozers`; `ortizdavidg/zillow-dealio-county-foreclosure-scraper`; `mrshoikot/zillow_foreclosure_scraper`; `Elevated5/PreForeclosure-Scraper`.

### Buyers / dispo
1. County recorder/ROD deeds with no concurrent deed-of-trust = cash buyers (reuse existing ROD/deed-mining infra, flip query from grantor to grantee).
2. Absentee-owner pull (owner mailing addr != situs + recent purchase).
3. Flipper signal (bought + resold within 12 months; cross-ref permits).
4. Auction/tax-sale attendees (cash buyers by definition, attend and collect cards).
5. REIA / BiggerPockets forums / ConnectedInvestors / Craigslist / FB "we buy houses" ads / hard-money-lender referrals.
6. iBuyers / institutional buy-box as a floor-price backstop (Offerpad, Opendoor, build-to-rent aggregators buy in Charlotte + Upstate metros).
7. Skip-trace the recorder names. Structure the list by name + contact + zips + price band they buy in (not ARV) + property type + rehab level. Target 50-100 active buyers.

### Related keywords
foreclosure auction investing for beginners; how to buy a house at auction; buying foreclosures at auction; courthouse steps auction; trustee sale vs sheriff sale; how to buy REO properties; bank owned homes for sale; how to make an offer on REO; HUD homes for sale; Fannie Mae HomePath listings; Freddie Mac HomeSteps; USDA REO properties for sale; county owned property for sale [county]; foreclosure listings [county] NC; master in equity foreclosure sale SC; upset bid North Carolina; upset bid period South Carolina; South Carolina foreclosure redemption period; sheriff sale list [county]; how to wholesale foreclosures; wholesale REO double close; transactional funding for double closing; proof of funds letter wholesaling; 70 percent rule foreclosure bidding; how to calculate max bid at auction; title search before auction; do liens survive foreclosure; bank owned properties near me; cheap foreclosed homes; buy foreclosure with cash.

---

## 3. WHOLESALE

### Strategy / how-to
Legal frame first: residential wholesaling now needs a broker license in both states (SC HB4754 in force since May 29, 2024; NC HB797 eff. Oct 1, 2025, unlicensed = Class 1 misdemeanor). Precise scope: SC HB4754 hinges on *marketing property you do not own*, and it explicitly carves out assigning a contractual right to purchase, so a non-licensee can still assign in SC. NC has NO such carve-out, so in NC even the assignment itself is brokerage. What still works unlicensed: **land** (statutes target residential dwellings), **double-close on residential** (you take title, so you sell property you own; the compliance advantage only holds if you market AFTER taking title), **creative finance** (subject-to / seller-finance where you are a principal buyer), and **in SC only, contract assignment**.

Pipeline: FIND -> ANALYZE -> OFFER (MAO) -> CONTRACT -> DISPO.
- `MAO = (ARV x 0.70) - Repair Costs - Your Assignment Fee`. Dial the multiplier 65% (risky) to 75-80% (hot market / rental buyers). Know your buyer's exit before setting MAO.
- Assignment (one closing, fee on the settlement statement, disclosure required) is a licensed residential lane in NC and an unlicensed lane in SC. Double-close (two closings, ~3% cost, needs cash or transactional funding) is the compliant unlicensed residential lane in BOTH states.
- **Dispo failure kills more deals than bad leads.** Have 10-20 cash buyers ready BEFORE you lock a contract. Conversion is ~2-3% lead->contract, 5-8 touches to a response.
- Send deals to a handful of perfect-fit buyers, not a 1,000-blast; scarcity creates a bidding war. Buyers want numbers (address, price, ARV, repairs, photos), not prose. 20-30 proven closers beat 1,000 tire-kickers.

Best free learning resources:
- BiggerPockets, "Wholesaling 101 for Beginners" https://www.biggerpockets.com/forums/12/topics/862964-wholesaling-101-how-to-wholesale-for-beginners
- BiggerPockets, "Building my own wholesaling CRM" (dispo/skip-trace reality) https://www.biggerpockets.com/forums/517/topics/1291602
- Flip With Rick free dispositions playlist https://home.flipwithrick.com/acquisitions-copy-1 + free Zach Dialer/Discord (unlimited free skip-trace) https://dealmachine.com/zach-dialer
- Pace Morby YouTube (creative-finance residential lane)
- DealMachine, "How to Sell Wholesale Deals Fast" https://www.dealmachine.com/blog/how-to-sell-wholesale-real-estate-deals-fast-3-easy-ways
- Deal Run MAO + cash-buyer explainers https://dealrun.ai/glossary/mao and https://dealrun.ai/blog/fastest-way-to-find-cash-buyers

### Sources
- County recorder / register of deeds: recent deeds with no concurrent deed-of-trust = cash purchase (the #1 free verified-buyer source; maps directly onto existing ROD infra).
- County assessor / GIS: ownership transfers, absentee flags, portfolios.
- PropStream (~$100/mo, 7-day trial + 50 free leads): cash + absentee + short-ownership + multi-property filters, built-in skip-trace/dialer.
- BatchLeads (300+ data-point cash-buyer + absentee/empty-nester combined filters, list-stacking): the direct PropStream peer.
- PropWire (free PropStream-style search incl. cash-buyer/absentee filters).
- DealMachine + Zach Dialer (free driving-for-dollars + skip-trace); Lead Mining Pros (~$0.07/lead skip-trace).
- Facebook REI groups; Craigslist "real estate for sale" + FB Marketplace; BiggerPockets marketplace + local forums; investor-friendly title company / closing attorney.

### Buyers / dispo
Tiered by speed (Deal Run): Tier 1 (hours) county cash-buyer pull + skip-trace top 50 + call this week, and blast existing list; Tier 2 (1-3 days) FB REI groups, county clerk cash-transaction records, Craigslist/Marketplace, InvestorLift Lite (free plan, post deals + connect with buyers, no card); Tier 3 (1-2 weeks) REIA/BP meetups, bandit signs.

Vet hard: ask for a HUD-1 / settlement statement from a deal they closed in the last 6 months (they can redact); require a buyer application (markets/zips, purchase-price range not ARV, property types, strategy, funding, deal count); proof of funds for cash claims. Track email opens/clicks — a perpetual-opener-never-buyer is likely another wholesaler spying; prune. Segment by zip + strategy; 100 proven closers > 1,000 names.

### Related keywords
how to wholesale real estate for beginners; what is MAO maximum allowable offer; 70 percent rule real estate wholesaling; how to calculate ARV after repair value; assignment of contract vs double close; what is a double close in wholesaling; how does an assignment fee work; how to find cash buyers for wholesale deals; how to build a cash buyers list free; how to vet a cash buyer; proof of funds real estate; is wholesaling legal in North Carolina; is wholesaling legal in South Carolina; do you need a license to wholesale real estate; how to wholesale land; wholesale real estate dispo strategy; sell my house fast for cash [city]; we buy houses cash [city]; cash home buyers near me; cash buyers list [county]; sell house with tenants [city]; landlord selling problem tenants; wholesale real estate contract template; assignment of contract PDF template; real estate skip tracing service cheap; pull cash buyers from county records; PropStream cash buyer search; investor friendly title company [city]; REIA meetup near me.

---

## 4. LAND WHOLESALE

### Strategy / how-to
Land is the compliant lane, but avoid the "market a contract you don't own" pattern. Two safe structures: **buy-and-resell / wholetail** (take title, light cleanup, list retail; the recommended default) and **double-close** (close A-B then B-C same day). Assignment of a residential-buildable parcel is the risky pattern; take-title-and-resell + owner-financing is also what sells land fastest. Note the edge case: the exemption rests on the property being non-dwelling. Marketing a residential-buildable lot while soliciting its owner is the grey zone an aggressive NC regulator could challenge, so keep the take-title-first guardrail on buildable-lot deals.

Lifecycle (RETipster): research -> mail motivated sellers -> offers -> due diligence (access/zoning/utilities/flood/perc) -> close -> list/promote -> process buyer leads -> close sale -> optional seller-financing -> repeat. Acquisition is the hard half; dispo is easy.

- **Blind-offer mail:** a single specific dollar offer to every vacant-land owner in a target county (never a range). 1-3% response, each reply is pre-negotiated. Target absentee/out-of-state, inherited, tax-delinquent, owned 10+ years.
- **Pricing:** solve retail $/acre from SOLD comps (discount actives 15-25%); $/acre drops as acreage rises so use same-size comps; offer 20-40% of retail (Podolsky's median-comp-divided-by-4 rule). Sanity-check: `Offer = conservative(median) resale - all costs - profit`. Volume solves pricing imperfection (~1,000 mailers ~= $600, yields 1-10 buys at ~$10K avg profit).
- **Timeline:** cash-priced land sits 6-12 months; **owner financing is the biggest speed lever** (30-90 days, 3-5x the buyer pool because banks won't lend on raw land). Fix cold listings in order: photos/headline, then owner-finance terms, then price.

Best free learning resources:
- RETipster (Seth Williams): lifecycle https://retipster.com/land-flipping-lifecycle/ + free templates/5-day course https://tools.retipster.com/land-investing-action-plan/
- Land Academy pricing https://landacademy.com/2020/11/27/how-to-correctly-price-a-land-blind-offer-campaign/ + neighbor letters https://landacademy.com/2025/05/07/neighbor-letters-the-underrated-land-sale-strategy-that-works/
- Pete Reese, Land Conquest (free 100+ video course) https://go.landconquest.com/ , YouTube @turningprofit
- The Land Geek (Mark Podolsky) https://www.thelandgeek.com/land-wholesaling/
- Joe McCall, "Land in 30 Days" https://joemccall.com/if-i-had-to-do-a-land-deal-in-30-days/ + DealMachine land blog https://www.dealmachine.com/blog/how-to-close-100-land-wholesaling-deals-virtually

### Sources
- County tax roll / treasurer (free): tax-delinquent VL (use-code "VL"). Footprint already has per-county tax-delinquency scrapers (Madison/Henderson/Lincoln/Catawba/McDowell + Spartanburg qPayBill).
- County assessor property roll in Excel (free): filter by use code to all vacant land, batch by acreage.
- PropStream / DealMachine / BatchLeads: property type = vacant land, pull by county not city, filter owner age + hold time + ownership count.
- Regrid (limited FREE tier + open parcel-boundary downloads) / AcreValue (free comps): parcel + $/acre context.
- Comps: LandWatch / Lands of America / Land And Farm SOLD data (free browse); PRYCD (~$40-100/mo, purpose-built land valuation) is the best paid buy at scale; county assessed value = floor.
- Neighbor-letter automation: Pebble (auto-pulls surrounding owners + templates); Land ID (formerly MapRight) + county GIS for the aerial overlay.
- Open-source land tooling: no clean drop-in exists; search GitHub for `landwatch scraper` / `lands-of-america scraper` and reuse PebbleAI's public neighbor-list logic as a build reference for the surrounding-owner pull.

### Buyers / dispo
Land buyers are dispersed; build 100-200 contacts segmented by type (builder / flipper / owner-finance / recreational) and geography.
1. **Mine county deed records monthly (highest signal):** flag anyone who bought 3+ parcels in 6-12 months = active land flipper. Test a county's buyer appetite BEFORE mailing sellers there.
2. **Builders/developers (best for buildable lots):** Google "home builders in [City]", call 50/day for 5 days, ask if buying lots + what areas/size/price, get the land-acquisition specialist's email, then reverse the funnel (get criteria first, source lots to match). Target production builders (DR Horton, Lennar, KB, Adams), avoid custom. Verify builder activity within 1 mile before locking any parcel. Enrich via LinkedIn + NAHB/HBA chapter lists + permit filings.
3. **SOLD-listing broker funnel:** on LandWatch / Lands of America, work "sold" listings back to the buyer's agent/broker as a repeat land-buyer channel.
4. **1031-exchange intermediaries / QIs:** qualified intermediaries sit on time-pressured cash buyers under a 45-day identification clock; a standing relationship routes those buyers to your land + small-commercial inventory.
5. Join competitors' buyer lists (Craigslist ghost ads too).
6. Facebook land groups: "Land Investors" (largest), "Wholesale Land Deals", "Land Flipping", "Owner Financed Land", "[State] Land for Sale".
7. Capture every inbound; REIA meetups; land auctions; referring land agents.

Dispo channels ranked: **neighbor letters first** (~35% call-back, ~20% sale in tight rural areas; include both APNs, aerial overlay, cash + owner-finance terms, scarcity line) -> FB Marketplace + land groups (free) -> Craigslist (free) -> Landmodo (owner-finance buyers) -> LandWatch FSBO -> Land.com network ($595-1,295/mo, max exposure) -> LandFlip ($10-300/mo) -> Landydandy ($39/mo) -> flat-fee MLS via a land-friendly broker. HUD stat behind neighbor letters: ~50% of properties sell to someone within a 1-mile radius or their relatives.

### Related keywords
how to flip land for beginners; land wholesaling step by step; how to price vacant land offer; blind offer land campaign; land flipping direct mail response rate; double close vs assignment land; how to do due diligence on vacant land; how to value land without comps; price per acre land valuation; how to sell land with owner financing; neighbor letter to sell land template; how to find cash buyers for land; how to build a land buyer list; how to wholesale land to builders; is land wholesaling legal in NC SC; sell my land fast for cash; cash for vacant land; we buy land; sell vacant lot no realtor; sell inherited land; sell land with back taxes; get cash offer for land; vacant land for sale owner financing; cheap land for sale by owner; buildable lots for sale [county]; recreational land for sale [state]; best place to list land for sale; Western NC land; Upstate SC vacant land; hunting land Carolina.

---

## 5. PROBATE / INHERITED PROPERTY

### Strategy / how-to
Probate is the single highest-intent seller lane: the decision-maker did not choose to own the property, often lives out of state, and frequently "just wants it gone" without repairs. The signer is the personal representative / executor named in Letters Testamentary (or Letters of Administration if there is no will); nothing can sell until the court issues those letters, so timing is opened by the appointment, not the death.

- **Heir psychology:** multiple decision-makers who may disagree, grief overlay, out-of-state distance, and a strong pull toward speed and simplicity over top dollar. Lead with empathy and logistics ("I can take the whole thing as-is, clear it out, close on your timeline"), never price-first.
- **Approach the executor, not the estate:** confirm who holds the letters, then present a single as-is cash path plus a creative-finance option (an estate that needs liquidity but has a low-rate loan is a clean subject-to). Offer to buy out one heir's share when siblings disagree (heir buyout).
- **Timeline:** informal/summary administration can close a sale in weeks; formal administration adds court confirmation. Know whether the county requires court approval of the sale price before you set expectations.
- **Footprint constraint (load-bearing):** NC estate files are a permanent WAF wall, so NC probate acquisition leans on the **obituary -> heir pre-probate lane** (the built Gannett Upstate obituary pipeline) plus Register of Deeds, NOT court records. SC estate records are more workable via the notice feed. Do not plan an NC play around scraping the estates docket.

Best free learning resources:
- US Probate Leads / all-things-probate primer https://www.usprobateleads.com/
- BiggerPockets probate forum threads on approaching executors https://www.biggerpockets.com/forums (search "probate executor")
- Pace Morby creative-finance-on-inherited-property clips (subject-to on a low-rate estate loan)

### Sources
- **Obituaries (pre-probate, NC-critical):** the built Gannett Upstate obituary pipeline + funeral-home RSS; cross-reference decedent -> property owned via Register of Deeds / assessor to reach heirs BEFORE the estate files. Repos: `benashkar/funeral_homes`, `mrkrstphr/obituary-scraper`.
- **SC estate notices:** scpublicnotices.com "notice to creditors" / estate notices feed.
- **County Register of Deeds / assessor:** owner-of-record deceased, estate/heir deeds, "life estate" and "et al" ownership flags, out-of-state mailing address on an owned parcel.
- **NC eCourts note:** Smart Search estates docket is WAF-walled (do not chase); the open Judgment Search JSON does NOT carry estates. Use obituary + ROD instead.
- **PropStream / BatchLeads:** built-in "probate" and inherited/absentee filters as a paid shortcut when the free obituary lane is thin.

### Buyers / dispo
- Same cash / fix-flip buyer list as Wholesale + Foreclosure (county cash-deed pull, absentee owners, Google Ninja "we buy houses [county]").
- Buy-and-hold landlords for dated-but-livable inherited homes (rent-ready with cosmetic work).
- Creative-finance buyers (sub-to / DSCR) when the estate carries a low-rate assumable-in-practice loan; route to the SubTo / creative buyer pool.
- Estate-sale and cleanout partners as a value-add you can bundle into the offer (removes the heirs' biggest friction).
- iBuyer / institutional floor as a backstop for clean suburban inherited homes.

### Related keywords
what is probate real estate; how to sell an inherited house; selling a house in probate NC; selling inherited property South Carolina; executor sell property; do all heirs have to agree to sell; sell inherited property to avoid taxes; probate timeline North Carolina; letters testamentary sell house; how long does probate take SC; we buy inherited houses; sell probate property fast cash; inherited house needs repairs; sell house before probate closes; heir buyout; siblings disagree selling inherited house; probate attorney sell real estate; cash for inherited property [city]; sell deceased parents house; sell house avoid probate; heir property sale [state]; sell my parents house fast; inherited a house I don't want; estate sale real estate [county].

---

## 6. TAX-DELINQUENT / TAX-SALE

### Strategy / how-to
Tax-delinquency is the footprint's most-built source (11.9k+ delinquent leads across Madison/Henderson/Lincoln/Catawba/McDowell + Spartanburg qPayBill balances) but it had no playbook for ACTING on it. Two distinct plays, and the NC/SC mechanics diverge sharply:

- **Direct pre-sale purchase (the motivated-seller play):** an owner behind on taxes with equity is a highly motivated seller you buy from directly, before any sale. Position the tax debt as the pain ("I can pay the county and take this off your plate"). This is the same as any equity deal and is the primary lane.
- **NC = tax-DEED state, not tax-lien.** NC does not sell lien certificates. The county (often via a law firm such as Kania Law Firm, which runs many WNC counties) forecloses and sells the DEED at a tax foreclosure sale, subject to the same 10-day upset-bid rule as mortgage foreclosures. Watch the county/law-firm listing pages. https://kanialawfirm.com/tax-foreclosures/foreclosure-listings/
- **SC = tax-LIEN / tax-DEED state with a 12-month redemption.** SC counties sell at the annual delinquent tax sale; the owner has ~12 months to redeem (pay taxes + interest) before the bidder gets a deed. The **tax-sale overage / surplus-funds** angle is a real sub-lane: when a property sells for more than the taxes owed, the former owner is owed the surplus and is often unaware, which is both a service you can broker and a warm door into a distressed seller.
- **Redemption-period discipline:** in SC do not count on taking title fast; underwrite as a lien with a redemption yield, or work the owner directly before the sale. In NC underwrite the tax-foreclosure deed like any auction buy (title search, surviving liens, upset-bid risk).

Best free learning resources:
- Kania Law Firm tax-foreclosure listings + process pages (WNC-specific) https://kanialawfirm.com/tax-foreclosures/
- Ted Thomas / county-treasurer explainers on NC tax-deed vs SC tax-lien mechanics
- SC county delinquent-tax-office pages (annual sale procedures + redemption rules)

### Sources
- **Footprint tax-delinquency scrapers (already built):** Madison/Henderson/Lincoln/Catawba/McDowell county .gov PDFs + PTS Cloud API (bcpwa tenants) + Spartanburg qPayBill balances (join by TMS). Reuse directly.
- **County tax collector / treasurer delinquent lists:** most NC/SC counties publish the annual delinquent roll and the tax-sale advertisement (also runs in scpublicnotices.com / ncnotices.com under "Delinquent Taxes" / "Tax Sales").
- **NC tax-foreclosure law-firm listings:** Kania Law Firm and peer firms post active foreclosure inventory by county.
- **SC delinquent-tax-office sale lists + overage/surplus rosters** (per-county, published before/after the annual sale).
- Scrapers to study: `akashsakhiya07/jackson-county-tax-delinquent-scraper`, `basepointcollective/MecklenburgNCScraper` (in-footprint, study directly); `TruliSTAT/forclos` (foreclosure + tax-lien app scaffold).

### Buyers / dispo
- Cash / fix-flip list (county cash-deed pull) for improved distressed parcels.
- Land buyers (builders, flippers, owner-finance, recreational) for the large tax-delinquent vacant-land slice — this lane feeds Section 4's dispo channels directly.
- Note / lien investors for SC tax-lien positions carried through redemption.
- iBuyer / landlord backstop for redeemable improved homes.

### Related keywords
what happens if you don't pay property taxes NC; property tax foreclosure North Carolina; tax lien sale South Carolina; tax deed vs tax lien; how to stop tax foreclosure; sell house with back taxes owed; buy tax delinquent property; SC tax sale redemption period; NC tax foreclosure process; Kania tax foreclosure listings; county tax foreclosure list [county]; behind on property taxes sell house; tax sale overage recovery; delinquent tax property for sale [county]; sell house owe back taxes cash; property tax help facing foreclosure; how to buy tax deeds in North Carolina; South Carolina delinquent tax sale; can I sell my house if I owe back taxes; tax delinquent land for sale; surplus funds after tax sale SC; owe back taxes need to sell fast.

---

## 7. DIVORCE

### Strategy / how-to
Divorcing owners frequently must sell fast and split proceeds, and the marital home is often the largest asset to divide. This is a real motivated-seller lane, revived in the engine off the NC eCourts Judgment Search JSON (divorce judgments serve there; the estates docket does not).

- **Two decision-makers, often in conflict:** the script is different from a single distressed owner. Position as the neutral, fast, clean exit that lets both parties move on ("one cash close, no showings, you split and go"). Never take sides; make it about speed and finality.
- **Timing:** the filing signals intent; the pain peaks around the property-division stage. A pending equitable-distribution matter over a jointly owned home is the sweet spot.
- **Structure:** straight cash purchase is cleanest for a fast split; creative finance is harder because both spouses must agree and one may need to be removed from the loan. Subject-to can work when one spouse keeps liability but wants out of the payment.

Best free learning resources:
- BiggerPockets forum threads on marketing to divorce leads (compliance + tone)
- Family-law-adjacent explainers on how the marital home is divided in NC (equitable distribution) vs SC

### Sources
- **NC eCourts Judgment Search JSON** (open, compliant): divorce/equitable-distribution judgments (the revived lane; use this, not WAF-walled Smart Search).
- **County ROD:** deeds transferring one spouse's interest, "quitclaim between spouses," lis pendens on a domestic matter.
- **SC PublicIndex:** domestic/family-court filings (ToS-no-scrape, so manual court-export lane only).
- **PropStream / BatchLeads:** "divorce" lead filter as a paid shortcut.

### Buyers / dispo
- Cash / fix-flip list (shared with Wholesale/Foreclosure) for as-is marital homes needing work.
- Buy-and-hold landlords for rent-ready homes.
- iBuyer / institutional floor for clean suburban homes where both spouses want maximum speed.
- Creative-finance buyers when one spouse stays on the loan and the deal is a subject-to.

### Related keywords
selling a house during divorce; who gets the house in a divorce NC; how to sell house fast in divorce; divorce house buyout; sell marital home quickly; do both spouses have to agree to sell house; sell house before divorce final; cash offer divorce house; equitable distribution house North Carolina; splitting house proceeds divorce; forced sale of house divorce; we buy houses divorce; sell house divorce no realtor; remove spouse from mortgage sell house; divorce sell house as is [city]; quitclaim deed divorce sell; how to divide house in divorce SC; sell house fast after separation.

---

## 8. VACANT / ABSENTEE / DRIVING-FOR-DOLLARS

### Strategy / how-to
Vacant and tired-landlord properties are a primary acquisition lane in their own right, not just a dispo aside. Driving-for-dollars (D4D) is the on-the-ground version: build routes through target neighborhoods and log distress signals, then skip-trace and outreach.

- **Distress signals to log:** overgrown lawn/yard, boarded or broken windows, tarped or failing roof, code-violation stickers, piled mail/newspapers, junk/abandoned vehicles, long-vacant look. Each is a marker of an absentee or overwhelmed owner.
- **Absentee / tired-landlord cut:** owner mailing address != situs, plus long hold time or a rental with problem tenants, flags an owner who may want out. "Landlord fatigue" (bad tenants, deferred maintenance) is a strong motivator.
- **Route + outreach loop:** drive/log -> pull owner via assessor/GIS -> skip-trace -> mail/call/door-knock the same empathy-first cadence as pre-foreclosure. D4D leads are cheap and low-competition because they require legwork.
- **Vacant/condemned overlap:** a code-enforcement or condemnation listing is a highly motivated owner (fix-it-or-lose-it pressure). Asheville code-enforcement is already built; surface those as priority D4D targets.

Best free learning resources:
- DealMachine D4D route + free-skip-trace walkthrough (Zach Dialer) https://dealmachine.com/zach-dialer
- BiggerPockets driving-for-dollars threads (route discipline + list-stacking)

### Sources
- **DealMachine (free route + skip-trace tooling)** for the D4D drive-and-log workflow.
- **County assessor / GIS:** absentee flag (mailing != situs), long hold time, ownership count; the built elderly/heir GIS and absentee pulls apply here.
- **Vacant / code-enforcement lists:** Asheville code-enforcement (built); Spartanburg vacant registry (~5k, build-ready); Asheville STR flags. Vacant-property registries are confirmed walls in some counties, so lean on code-enforcement + assessor absentee where registries are closed.
- **USPS vacancy signal** (via PropStream/BatchLeads "vacant" flag, sourced from USPS delivery data).
- Scrapers to study: `mcclellandjr/AbsenteeOwnership` (Watauga County, in-footprint absentee cut).

### Buyers / dispo
- Cash / fix-flip list is the core buyer here (vacant + distressed = rehab inventory).
- Landlords / BRRRR buyers for tired rentals that are structurally fine.
- Section 4 land buyers for vacant lots surfaced on routes.
- Creative-finance buyers when a tired landlord has a low-rate loan and wants payment relief (subject-to).

### Related keywords
driving for dollars real estate; how to find vacant houses; vacant property list [county]; absentee owner list; how to find absentee owners; tired landlord leads; sell rental property fast; landlord selling problem tenants; sell house with tenants in it; how to skip trace a property owner; sell vacant house [city]; we buy vacant houses; sell house with code violations; sell condemned house; sell hoarder house; sell house with fire damage; abandoned property for sale [county]; sell inherited vacant house; owner out of state sell house; sell house that needs major repairs; how to find distressed properties free; USPS vacant property data.

---

## 9. GATOR / CREATIVE FINANCE

### Strategy / how-to
The lane that survives NC HB797 / SC HB4754: you (or your end-buyer) take title and take over the debt, so you are a principal buyer, not a broker. Weight the business here.

- **Subject-to (sub-to):** take over the seller's existing loan, left in their name. Best when the seller has little/no equity but a low locked-in rate (2-4%). Offer = loan balance + small cash-to-seller ($1k-5k) + you take over PITI. Get a mortgage statement (don't credit-pull), title search for 2nd liens. Docs (attorney-drawn): purchase agreement with explicit "subject to existing mortgage" language, warranty deed, limited POA, payment authorization, full seller disclosure of due-on-sale risk; record the deed. Use a third-party servicer (never pay the seller and hope they forward). **Insurance is where sub-to blows up:** cancel the seller's policy, buy a landlord/non-owner-occupied policy with YOU as First Named Insured, lender as mortgagee; seller only as Additional Interest on the liability cert, never Named Insured on the property policy.
- **Seller finance:** seller owns free-and-clear and IS the bank (promissory note + deed of trust). Cleanest lane (no due-on-sale). Terms: 5-20% down, rate 2-4 points over conventional, amortize 20-30 yrs with a 3-7 yr balloon. Lever = rate arbitrage headroom (offer below-market rate, add the PV savings to price to win). Watch IRS AFR (~5.1% mid-term early 2026) and state usury caps. Present two offers (lower cash vs higher seller-finance).
- **Wraps (AITD):** seller creates a new note wrapping the underlying loan; you pay the seller, seller keeps paying their bank and pockets the spread. Gives reluctant sellers recourse/visibility. Same due-on-sale exposure; mandatory third-party servicer.
- **Gator / EMD / transactional funding:** EMD funding fronts your earnest money; transactional funding fronts the full price for a same-day double close (underwritten on the end-buyer, repaid in hours, flat fee). Being the gator (lending the EMD/transactional capital for fees) is a business itself.
- **Risks to name honestly:** due-on-sale clause (real, rarely called while current, detection usually comes from the insurance change; mitigate with a land trust + flawless payments + refi/sell exit); seller stays liable on sub-to; non-refundable EMD risk; balloon refi risk.

Best free learning resources:
- Pace Morby YouTube https://www.youtube.com/@PaceMorby (No-Money-Down series https://www.youtube.com/watch?v=904lA_6Bxp8 ; Subject-To live https://www.youtube.com/watch?v=7t8ZwM1Z8NQ)
- BiggerPockets Creative Finance forum (due-on-sale reality https://www.biggerpockets.com/forums/50/topics/1164740 ; sub-to insurance https://www.biggerpockets.com/forums/311/topics/1283108)
- Flipping Mastery x Pace Morby "How to Structure Creative Finance" https://www.youtube.com/watch?v=pvgEqb4r4gw
- REInsurePro, "Properly Insuring Your Subject-To Property" https://reinsurepro.com/properly-insuring-subject-to-investment-properties/
- New Path Title, side-by-side of all four structures https://newpathtitle.com/creative-finance-seller-mortgages-subject-to-wrap-around-mortgages-assignments/

### Sources
- Free deal source = your own motivated-seller engine (pre-foreclosure, probate, divorce, tax-delinquent, vacant, low-equity + still-listed). No new tool needed.
- Instant Creative Offer Calculator (free; models down/rate/term/balloon + terms-value headroom) https://goflexi.app/tools/instant-creative-offer-calculator
- Loan servicers (low monthly fee; required for sub-to/wrap).
- Transactional / EMD funders (fee per deal): Cox Property Group https://www.coxpg.com , Duckfund https://www.duckfund.com , Munoz Ghezlan Capital, New Silver; or source a gator inside the funding communities.
- Docs: attorney-drawn per deal (do not wing sub-to/wrap paperwork).

### Buyers / dispo
Creative deals need a different buyer (co-living operators, sub-to/DSCR investors, note buyers):
- SubTo community + Deal Submission Portal https://go.subto.com/learn-about-challenge (paid, highest-density creative buyer pool).
- Skool free tiers: "Wholesaling Real Estate" https://www.skool.com/wholesaling (people post SubTo/seller-finance buy-boxes with zips + PITI caps) and "Transactional Funding Hub" https://www.skool.com/fundinghub .
- SubtoListings.com (verified subject-to buyers/sellers directory).
- Dispo-as-a-service (free, 50/50, no upfront): Dispo Buddy https://dispobuddy.com (subject-to/seller-finance/novation/lease-option checkboxes) and DispoBridge https://dispobridge.com .
- **Facebook "Sniper" method (best free tactic):** join local investor + market-specific "Subject-To" groups, search the deal's zip inside each group, find people who commented "interested" on deals in that zip in the last 12 months, DM them.
- Local REIA meetings.

### Related keywords
subject to real estate; subject to mortgage; how does subject to work; subject to vs assumption; due on sale clause subject to; seller financing; owner financing; how to structure seller financing; seller carry back; seller finance interest rate; seller financing balloon payment; wrap around mortgage; all inclusive trust deed AITD; creative financing real estate; no money down real estate; take over mortgage payments; gator lending; gator method real estate; transactional funding; EMD funding; earnest money deposit funding; double closing; same day funding real estate; Pace Morby subject to; Morby method; novation agreement real estate; lease option; how to find subject to sellers; subject to insurance; creative finance buyers list; land trust due on sale.

---

## CROSS-CUTTING: OUTBOUND CHANNELS (FREE + PAID)

Every process above needs an outbound engine to reach the seller. Four channels, compared by cost / response / compliance. The playbook is FREE-weighted by choice, not by blind spot; the paid note exists so an operator can scale deliberately.

| Channel | Cost | Response | Compliance |
| --- | --- | --- | --- |
| Direct mail (blind offer / yellow letter / postcard) | ~$0.50-0.70/piece | 1-3% (land higher) | Cleanest; no consent needed |
| Cold call | Cheap w/ free skip-trace (Zach Dialer) | Low per dial, high per conversation | DNC scrub required |
| SMS | Very cheap | Highest engagement | STRICT: TCPA consent + STOP + DNC/litigator scrub |
| PPC + pay-per-lead | Highest | Inbound = warmest | TCPA on any form/landing-page capture |

- **Direct mail** is the backbone for land (blind offer) and for absentee/probate/tax-delinquent lists. Volume solves imperfection.
- **Cold call** pairs with the free Zach Dialer skip-trace; call within 5 minutes of any inbound (21x conversion drop by 30 minutes).
- **SMS** is the compliance minefield: prior express consent, "Reply STOP" on every message, immediate removal, DNC + litigator-list scrub. This is the "act-on-it layer" flagged in path_to_100 and it is required, not optional, on the SELLER side too (not just buyer dispo).
- **Paid channel (use deliberately):** Google PPC on "sell my house fast / cash home buyers" runs ~$15-$75+ CPC in competitive metros, roughly $500-$2,000 per lead and $3,000-$8,000 per closed deal; the footprint's secondary markets are cheaper than metros. Pay-per-lead marketplaces (iSpeedToLead, Motivated Leads, GoForClose) sell exclusive seller leads without running your own ads. Any "we buy houses" landing page collecting seller info, and any SMS blast, sits under TCPA and (in NC) the HB797 30-day right-to-cancel disclosure.
  - https://www.realestateskills.com/blog/wholesaling-ppc
  - https://ispeedtolead.com/blog/how-to-find-motivated-seller-leads-in-2026/
  - https://www.goforclose.com/guides/wholesaling-advertising

---

## CROSS-CUTTING: BUYER ACQUISITION MASTER

The operator's flagged gap. A buyer list is a segmented database built BEFORE you need it, so a locked deal filters to the 10-20 buyers who match by submarket + price band + property type + strategy. In secondary markets (this whole footprint), 20-30 active verified buyers is enough. Set a weekly target of 3-5 new qualified buyer conversations.

### Find (free, by buyer type)
- **Cash / fix-flip:** county recorder cash-deed pull (deed with no concurrent DoT; in-footprint confirmed live: Greenville County SC ROD https://greenvillecountysc.gov/rod/searchrecords.aspx ) — same rails as the foreclosure engine, query grantees not grantors. Absentee-owner pull. Google Ninja trick ("we buy houses [county]"). Craigslist/FB Marketplace reverse-engineer. **MLS "sold + cash / conventional-to-LLC" filter** via an investor-friendly agent (fresher than county deeds, and free to you). myhousedeals.com free directory (already lists "Upstate South Carolina" and "Greenville") https://www.myhousedeals.com/cash-buyers/recent.asp . Free dispo marketplaces to post AND harvest: InvestorLift Lite (free plan) https://get.investorlift.com/ , OfferMarket https://www.offermarket.us/wholesalers , Connected Investors https://connectedinvestors.com/features/cash-buyers , PropPipeline https://proppipeline.com .
- **Land:** LandWatch / Lands of America / LandFlip / Land.com / Landmodo; county deed pull for recent VL grantees; SOLD-listing broker funnel; builders/developers direct + plat records + permit records; 1031-exchange QIs for time-pressured cash.
- **Buy-hold / creative / note:** BiggerPockets forums + marketplace; SubtoListings.com; SubTo community + FB/Meetup groups; BP note forums + note FB groups.
- **All types:** local REIAs ("[city] real estate investor association"); FB groups; foreclosure-auction attendees; hard-money-lender borrower lists (a lender's just-funded borrower on an investment property is an active-buyer signal; Vesper has 16,000+ HMLs https://entervesper.com ). Cross-reference HML default/NOD grantees as a second active-buyer signal.

### Build
Continuously, ~10 new vetted buyers/month. Capture every inbound even non-buyers. Segment fields: contact + preferred method, target zips, min/max purchase price (all-in, not ARV), property type, rehab tolerance, strategy (flip/BRRRR/buy-hold/land/creative), funding source, POF on file (y/n + date), last purchase date (from county), last contact date, VIP tier.

### Vet (saves the assignment fee)
- **Proof of funds:** bank/brokerage statement <=30 days showing >= price + buffer, or dated hard-money pre-approval. Red flags: blurry, account numbers fully visible, balance exactly = price (no buffer), stale, generic letter, crypto screenshot. Verify by calling the bank/lender at its publicly-listed number (not a link in the buyer's email).
- **Closing history (the 2026 standard):** cross-reference the buyer's name/entity against county deed records for real transfers in the last 90 days-12 months. Ask "Are you the closing buyer, or do you plan to assign?" (the daisy-chain fraud is the #1 scenario).
- FinCEN BOI reporting now applies to entity cash residential buyers — another reason to weight toward land + creative-finance-as-principal.
- **Tier:** VIP (3+ deals/12mo + POF verified + fast response) get first look; Unverified get nothing.

### Nurture / dispo execution
- Channels: email + SMS. Deal blast subject = address + price + one selling point; body = scannable bullets (asking/ARV/repairs/spread for flippers OR rent/cap-rate/cash-flow for landlords); two versions if the list is mixed; ONE deal per blast; trackable deal-page link; CTA + deadline.
- Cadence (90% of closes happen post-initial-contact): Day 0 blast -> Day 2 bump to non-openers -> Day 3 phone the top 10-15 openers/clickers -> Day 5 SMS -> Day 7 price-adjust -> Day 10 last call.
- Timing Tue-Thu 9-11am local; max 2-3 deals/week to the same list; segment by geo ruthlessly.
- **TCPA/SMS compliance (the "act-on-it layer" flagged in path_to_100):** SMS needs prior express consent (signup checkbox or text-in opt-in), every text carries "Reply STOP", STOP removes immediately, scrub against DNC + litigator lists.
- CRM: spreadsheet to ~20-50 buyers; past that GoHighLevel (tag by market + status, custom buy-box fields, "Under Contract" stage auto-fires the blast). DealRun bundles CRM + blasting + TCPA at ~$99/mo.

### Buyer-acquisition keywords
how to find cash buyers for wholesaling free; build a cash buyers list real estate; where do wholesalers find buyers; find cash buyers on Craigslist; Google ninja trick cash buyers; county deed records cash buyers; absentee owner cash buyer list; MLS sold cash buyer filter; how to verify proof of funds cash buyer; how to spot fake cash buyers; verified closing history buyer; daisy chain wholesale buyer; hard money lender borrower list; how to find land buyers; builder first land wholesaling; find developers buying land; 1031 exchange buyers land; subject to buyers list; note investors buyers list; OfferMarket vs InvestorLift; InvestorLift Lite free; free wholesale dispo platform; deal blast email template wholesale; SMS blast wholesale buyers TCPA; GoHighLevel wholesale buyer list; cash buyers list for sale [state]; join cash buyer list [city]; sell me your wholesale deals; off market deals [city]; we buy wholesale contracts; dispo VA services; real estate deal disposition service.

---

## CROSS-CUTTING: OPEN-SOURCE SCRAPERS + TOOLING

No repo is a drop-in; the value is the patterns. Three are worth an hour each: mcp-atlas (harvest missing NC/SC ArcGIS endpoints), prop_pilot's civilview module (the vendor-not-county pattern), qpublic-scraper (validates the existing Schneider assessor-card stealth flow).

Tier 1 (wire-in / study-worthy):
- `LEOyrh/mcp-atlas` — MCP server, 155 verified county parcel ArcGIS REST endpoints + owner/APN query tools. TS/JS, MIT. Directly matches the ArcGIS-first approach; harvest any NC/SC endpoints we lack. `npx -y @urbankitstudio/mcp-atlas`
- `chee86j/prop_pilot` — https://github.com/chee86j/prop_pilot — full REI platform, civilview sheriff-sale scraper with named-county->countyId map. Python. Best reference architecture (scrape -> DB -> enrich).
- `chee86j/ForeclosureAuctionPyScraper` — Selenium civilview -> SQLite -> CSV -> auto-Zillow-URL enrichment. Python. Clean list->enrich->persist template.
- `bradengoodgame/qpublic-scraper` — https://github.com/bradengoodgame/qpublic-scraper — Schneider qPublic assessor scraper, undetected_chromedriver, 16 variants incl. REST-endpoint discovery. Python. Mirrors the Pickens/Oconee card path. (qPublic/Schneider Geo also publishes a statewide county-coverage index; use it to enumerate which footprint counties expose CARD data before writing a parser.)
- `alevillada/sheriff-sale-scraper` — Scrapy + scrapy-playwright -> civilview -> Postgres. Python. Cleanest Scrapy structure for the vendor.
- `johnbalvin/pyzill` — https://github.com/johnbalvin/pyzill — 101 stars, MIT, the only actively-maintained Zillow scraper; use it only for a comp link, not structured pulls (Zillow direct scraping is a rate-limit treadmill).
- `pipeworx-io/mcp-regrid` — MCP wrapping Regrid Parcel API v2. TS. Connector if we ever pay Regrid (note Regrid has a limited free tier + open boundary downloads before then).

Tier 2 (civilview cluster — same platform, pick the cleanest): `JimLynchCodes/Fork-Lozers`, `ReyterSS/SalesWeb`, `dontbecypher16/burlington`, `Odinson4/property_prowler`, `Piyush8416570/Automated_APP_for_webscrapping`, `BlaneCordes/crisp`.

Tier 3 (adjacent sources):
- Pre-foreclosure signal: `Cerulean-Web-Consulting/lis_pendens_scraper` + `Zackthehouseguy/jefferson-lis-pendens-scraper`.
- Tax-delinquent (in-footprint, study directly): `akashsakhiya07/jackson-county-tax-delinquent-scraper`, `basepointcollective/MecklenburgNCScraper`; `TruliSTAT/forclos` (foreclosure + tax-lien app scaffold).
- Probate / pre-probate (align with the built Gannett obituary lane): `benashkar/funeral_homes`, `mrkrstphr/obituary-scraper`.
- Eviction cluster (REFERENCE ONLY, evictions are a confirmed wall): `sdl60660/cleveland_eviction_scraper`, `NewsappAJC/eviction_scrapers`.

Buyer-side: `crubinovega/buyer_scraper` — "scrape buyers and sellers"; the method that matters is a cash buyer = entity that recently bought with no mortgage, built from the same county records already pulled. `mcclellandjr/AbsenteeOwnership` (Watauga County, in-footprint) shows the absentee/D4D cut.

Standardize dependencies: `undetected_chromedriver`, `puppeteer-extra` + `puppeteer-extra-plugin-stealth`, `curl_cffi` (impersonate, the Akamai/GovDeals bypass), `scrapy` + `scrapy-playwright`, `playwright`. All free/MIT.

---

## MASTER KEYWORD MAP (deduped, grouped by process)

**Pre-Foreclosure**
what is pre-foreclosure; pre-foreclosure vs foreclosure; notice of default meaning; lis pendens meaning; foreclosure process; foreclosure timeline by state; North Carolina foreclosure process; South Carolina foreclosure timeline; reinstatement vs short sale; how to stop foreclosure; foreclosure rescue scam laws; door knocking foreclosure script; pre-foreclosure homes for sale [county]; pre-foreclosure list [county]; notice of default list free; lis pendens list [county]; foreclosure listings Upstate SC; we buy houses in foreclosure; sell my house before foreclosure; stop foreclosure [city]; sell house behind on payments; sell house as is [city]; NC foreclosure notice search; SC public notices foreclosure.

**Foreclosure / Auction / REO**
how to buy a house at auction; buying foreclosures at auction; courthouse steps auction; trustee sale vs sheriff sale; how to buy REO properties; bank owned homes for sale; how to make an offer on REO; HUD homes for sale; Fannie Mae HomePath listings; Freddie Mac HomeSteps; USDA REO properties for sale; county owned property for sale [county]; foreclosure listings [county] NC; master in equity foreclosure sale SC; upset bid North Carolina; upset bid period South Carolina; South Carolina foreclosure redemption period; sheriff sale list [county]; wholesale REO double close; transactional funding for double closing; 70 percent rule foreclosure bidding; how to calculate max bid at auction; title search before auction; do liens survive foreclosure; bank owned properties near me; cheap foreclosed homes; buy foreclosure with cash.

**Wholesale**
how to wholesale real estate for beginners; what is MAO maximum allowable offer; 70 percent rule wholesaling; how to calculate ARV; assignment of contract vs double close; what is a double close; how does an assignment fee work; how to find cash buyers for wholesale deals; how to build a cash buyers list free; how to vet a cash buyer; proof of funds real estate; is wholesaling legal in North Carolina; is wholesaling legal in South Carolina; do you need a license to wholesale real estate; wholesale real estate dispo strategy; sell my house fast for cash [city]; we buy houses cash [city]; cash home buyers near me; cash buyers list [county]; sell house that needs repairs; wholesale real estate contract template; assignment of contract PDF template; real estate skip tracing service cheap; PropStream cash buyer search; investor friendly title company [city]; REIA meetup near me.

**Land Wholesale**
how to flip land for beginners; land wholesaling step by step; how to price vacant land offer; blind offer land campaign; land flipping direct mail response rate; double close vs assignment land; due diligence on vacant land; how to value land without comps; price per acre land valuation; how to sell land with owner financing; neighbor letter to sell land template; how to find cash buyers for land; how to build a land buyer list; how to wholesale land to builders; is land wholesaling legal in NC SC; sell my land fast for cash; cash for vacant land; we buy land; sell vacant lot no realtor; sell inherited land; sell land with back taxes; get cash offer for land; vacant land for sale owner financing; cheap land for sale by owner; buildable lots for sale [county]; recreational land for sale [state]; best place to list land for sale; Western NC land; Upstate SC vacant land; hunting land Carolina.

**Probate / Inherited**
what is probate real estate; how to sell an inherited house; selling a house in probate NC; selling inherited property South Carolina; executor sell property; do all heirs have to agree to sell; sell inherited property to avoid taxes; probate timeline North Carolina; letters testamentary sell house; how long does probate take SC; we buy inherited houses; sell probate property fast cash; inherited house needs repairs; sell house before probate closes; heir buyout; siblings disagree selling inherited house; probate attorney sell real estate; cash for inherited property [city]; sell deceased parents house; sell house avoid probate; heir property sale [state]; inherited a house I don't want; estate sale real estate [county].

**Tax-Delinquent / Tax-Sale**
what happens if you don't pay property taxes NC; property tax foreclosure North Carolina; tax lien sale South Carolina; tax deed vs tax lien; how to stop tax foreclosure; sell house with back taxes owed; buy tax delinquent property; SC tax sale redemption period; NC tax foreclosure process; Kania tax foreclosure listings; county tax foreclosure list [county]; behind on property taxes sell house; tax sale overage recovery; delinquent tax property for sale [county]; sell house owe back taxes cash; property tax help facing foreclosure; how to buy tax deeds in North Carolina; South Carolina delinquent tax sale; can I sell my house if I owe back taxes; tax delinquent land for sale; surplus funds after tax sale SC.

**Divorce**
selling a house during divorce; who gets the house in a divorce NC; how to sell house fast in divorce; divorce house buyout; sell marital home quickly; do both spouses have to agree to sell house; sell house before divorce final; cash offer divorce house; equitable distribution house North Carolina; splitting house proceeds divorce; forced sale of house divorce; we buy houses divorce; sell house divorce no realtor; remove spouse from mortgage sell house; divorce sell house as is [city]; quitclaim deed divorce sell; how to divide house in divorce SC; sell house fast after separation.

**Vacant / Absentee / D4D**
driving for dollars real estate; how to find vacant houses; vacant property list [county]; absentee owner list; how to find absentee owners; tired landlord leads; sell rental property fast; landlord selling problem tenants; sell house with tenants in it; how to skip trace a property owner; sell vacant house [city]; we buy vacant houses; sell house with code violations; sell condemned house; sell hoarder house; sell house with fire damage; abandoned property for sale [county]; owner out of state sell house; sell house that needs major repairs; how to find distressed properties free.

**Gator / Creative Finance**
subject to real estate; subject to mortgage; how does subject to work; subject to vs assumption; due on sale clause subject to; seller financing; owner financing; how to structure seller financing; seller carry back; seller finance interest rate; seller financing balloon payment; wrap around mortgage; all inclusive trust deed AITD; creative financing real estate; no money down real estate; take over mortgage payments; gator lending; gator method real estate; transactional funding; EMD funding; earnest money deposit funding; double closing; same day funding real estate; Pace Morby subject to; Morby method; novation agreement real estate; lease option; how to find subject to sellers; subject to insurance; creative finance buyers list; land trust due on sale.

**Buyer acquisition (cross-cutting)**
how to find cash buyers for wholesaling free; build a cash buyers list real estate; where do wholesalers find buyers; find cash buyers on Craigslist; Google ninja trick cash buyers; county deed records cash buyers; absentee owner cash buyer list; MLS sold cash buyer filter; how to verify proof of funds cash buyer; how to spot fake cash buyers; verified closing history buyer; daisy chain wholesale buyer; hard money lender borrower list; how to find land buyers; builder first land wholesaling; find developers buying land; 1031 exchange buyers land; subject to buyers list; note investors buyers list; OfferMarket vs InvestorLift; InvestorLift Lite free; free wholesale dispo platform; deal blast email template wholesale; SMS blast wholesale buyers TCPA; GoHighLevel wholesale buyer list; cash buyers list for sale [state]; join cash buyer list [city]; sell me your wholesale deals; off market deals [city]; we buy wholesale contracts; dispo VA services; real estate deal disposition service.

**Outbound channels (cross-cutting)**
motivated seller leads; direct mail real estate investing; yellow letter template; blind offer letter; cold calling motivated sellers script; real estate SMS marketing TCPA; DNC scrub real estate; sell my house fast PPC; pay per lead motivated sellers; iSpeedToLead reviews; motivated seller Google Ads cost; cost per lead wholesaling; skip tracing free real estate; how to respond to seller leads fast.

---

## COMPLIANCE NOTE (NC / SC)

Residential wholesaling is regulated brokerage in both states, but they are NOT both new and NOT identical:
- **SC HB4754 — enacted May 29, 2024, ALREADY IN FORCE** (added Article 9 to Title 40, Ch. 57). SC operators have been under this regime for over a year; it is not pending or "2026." It prohibits brokerage firms/agents from marketing real estate they do not own for compensation, BUT its wholesaling definition **excludes "assigning or offering to assign a contractual right to purchase,"** so pure contract assignment remains a lane for a non-licensee in SC. Sources: https://www.scstatehouse.gov/code/t40c057.php and https://screaltors.org/sc-regulates-wholesaling-in-new-re-license-law/
- **NC HB797 — eff. Oct 1, 2025 (the recent one)** folds residential wholesaling into G.S. 93A brokerage; unlicensed wholesaling is a Class 1 misdemeanor; homeowners get a 30-day right to cancel a wholesale/"we buy houses" contract; NC is an attorney-closing state. **NC has NO assignment carve-out** — in NC even assigning a residential purchase contract is brokerage, so the SC assignment lane does NOT exist in NC.
- **NC 75-121** separately bars a foreclosure-rescue transaction for gain unless the buyer pays the owner >=50% of FMV via a certified appraisal (<=120 days old, delivered 7+ days before the owner is obligated) with a written contract.

Compliant lanes for an unlicensed operator:
- **Land** (statutes target residential dwellings, not raw land; sell as buy-and-resell or double-close, not marketing-a-contract-you-don't-own; keep the take-title-first guardrail on residential-buildable lots, which are the grey zone).
- **Creative finance** (subject-to, seller-finance, wraps — you are a principal buyer taking title/debt, not a broker).
- **Residential wholesale specifically:** become a licensed broker, OR double-close and market only AFTER taking title (works in BOTH states), OR assign — but assignment is compliant in **SC only**, not NC.

Weight the business toward land + creative finance, keep the cash-buyer/fix-flip list for when acting as principal, and treat the TCPA/DNC-scrub SMS layer as required (on both seller and buyer sides), not optional. Any PPC "we buy houses" landing page in NC must surface the HB797 30-day right-to-cancel.
