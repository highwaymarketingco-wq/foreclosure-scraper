# Social-Research Addendum to the REI Operator Playbook

Net-new tools, sources, communities, and tactics from practitioner and community channels (Reddit, BiggerPockets, forums, YouTube, GitHub) that are NOT already in `rei_operator_playbook.md` / `gap_ledger.md`. Deduped against the known list. Two uses throughout: **AUTO-ENGINE** = our free/compliant lead-sourcing + enrichment pipeline (free-only rule applies here, so anything paid is a fallback note, not an engine feed); **OPERATOR** = the human-run wholesaling/creative-finance business (paid tools allowed, cost stated).

**Free-vs-paid labels are strict:** *Free* = usable at zero cost indefinitely with no card. *Freemium* = a permanent-but-capped free tier. *Trial* = free only until a credit/day cap runs out, then paid. *Paid* = costs money to use.

> **Platform-coverage note (this pass).** Reddit + web/GitHub/YouTube carried this pass. **Instagram read returned HTTP 401** (session expired; needs a re-login in the OpenCLI-connected Chrome profile before IG can be read). **Facebook group + search came back empty** (no results returned this pass). Both IG and FB are therefore **pending a session fix** and were not sampled directly. The IG account list in Section 4 is carried over from the web/YouTube sweep, not verified against live IG. Re-run IG/FB once the Chrome session is re-authenticated.

Known-and-skipped (already in playbook, not repeated): ReadyDeals, FlipMantis, PropStream, DealMachine, BatchLeads, InvestorLift, TruePeopleSearch, FastPeopleSearch, Regrid, LandGlide, ParcelFact, Land id / MapRight, DataTree / First American, DoubleClose / Straightline / Axelrad / Tidal (POF funders), n8n orchestration, NC-voter-file free skip, BiggerPockets Forum 50, and the gator-as-dispo-lane / mail-is-the-TCPA-free-spine reframes.

---

## 1. Headline net-new finds

| # | Name / URL | Cost (strict) | What + why it matters | Sentiment | Use |
|---|---|---|---|---|---|
| 1 | **RealEstateAPI** - developer.realestateapi.com | Paid, usage-based (free tier = trial credits, not free) | Programmatic property-data + skip API: PropertyDetailBulk (1,000/req, up to 1M/day) and SkipTraceBatch (1,000/req); same distressed filters as PropStream (absentee, pre-fc, tax-delinquent, high-equity); ships an `llms.txt`. Most engine-relevant find: a structured fallback where our free county scrapers thin out (non-disclosure gaps). | Low Reddit chatter (dev-facing); backs DIY "$0 pipeline" builds on their Discord. | AUTO-ENGINE (paid fallback only) |
| 2 | **Apify Distressed Property AI Scraper** (dominvo) - apify.com/dominvo/distressed-property-ai-scraper | Paid, $0.06/enriched lead (first 20 rows free = trial) | Pulls tax-delinquent / pre-fc / sheriff-sale / tax-lien / code-violation / vacant-registry / probate direct from county+city open data (Socrata SODA, ArcGIS REST, recorder feeds) across 17+ metros, dedupes, distress-scores, skip-traces. Source-direct, not a reseller. Note: Apify is on our do-not-buy list per free-only, so this is a benchmark of our own scraper, not a buy. | New (May 2026), no independent chatter, unproven. | AUTO-ENGINE (benchmark only) |
| 3 | **Land Portal API** - landportal.com | Paid (~$99/mo Advanced) | Nationwide parcel+owner with land filters (AI vacant-lot detect, road-access, frontage, slope, FEMA, wetlands, soil, MLS comps, one-click skip). Seth Williams (RETipster) documented handing Claude a 900-row delinquent-tax list and enriching every row via the API with zero manual entry: our name→property→equity backbone, agent-drivable, for land. | RETipster flagship rec; PRYCD's review calls it a legit list source. | AUTO-ENGINE (paid fallback) |
| 4 | **mcp-atlas** (UrbanKit Studio) - github.com/LEOyrh/mcp-atlas | Free (MIT, OSS) | MCP server with 150+ manually-verified county-parcel ArcGIS REST endpoints, each with the exact owner/taxpayer field name + a ready `build_owner_query`. Supplements our `_STREET_NUM/NAME_FIELD_CANDIDATES` + Charleston-resolver work: a curated owner-field lookup so we stop re-deriving each county by hand. | New (Jun 2026), 0 stars; value is the verified field list, not the code. | AUTO-ENGINE |
| 5 | **OfferMarket** - offermarket.us/wholesalers | Free for wholesalers (their business is the lending arm) | 10,000+ POF-verified cash buyers, buyer messaging, POF screening, trackable QR yard sign; pays up to $1,000 referral when your listed deal is funded by their lending arm. Contrast InvestorLift (~$1,750+/mo). | r/WholesaleRealestate: "free for wholesalers, the marketplace is a funnel for their private lending." Dispo tooling itself is genuinely $0. | OPERATOR (dispo) |
| 6 | **InsulaCRM** - github.com/InsulaCRM/InsulaCRM / insulacrm.com | Free (MIT, self-hosted) | The only OSS CRM scoped to wholesaling: motivated-seller pipeline, buyer dispo, multi-tenant, per-tenant REST API `/api/v1`, embeddable branded lead form, BYOK AI (OpenAI/Anthropic/Gemini/Ollama), Docker/Laravel 12. The genuinely-free, API-first Podio/REsimpli replacement that fits our own-your-infra pattern; our engine can push leads straight into it. | Young project, low stars, but specifically REI-shaped. | OPERATOR (CRM) |
| 7 | **Smarter Contact** - smartercontact.com | Paid (~$899/mo unlimited-markets tier cited) | Bulk SMS with built-in national + internal DNC scrub, 2-day 10DLC approval, unlimited markets. Named as the tool multiple wholesalers switched to from Launch Control (slow 10DLC, offshore support, 2-market cap). The DNC-scrub feature addresses our flagged missing act-on-it/DNC layer. | Positive switch-from-LC sentiment on r/WholesaleRealestate. | OPERATOR (contact, heavy TCPA) |
| 8 | **CreativeFinance.app** - creativefinance.app | Paid (marketplace) | P2P micro-lending marketplace connecting investors with micro-lenders for EMDs, option fees, transactional funding ($200-$2,000), funded in 24-48h, AI risk analysis + automated docs. The disintermediated version of gator lending: a marketplace instead of a $3k-8k course + FB group. | New/unproven; vet before routing real deals; AI-doc/auto-contract needs a state-specific attorney check. | OPERATOR (fund) |
| 9 | **8020REI (BuyBox IQ + Rapid Response)** - 8020rei.com | Paid | Two mechanics worth copying: (a) BuyBox IQ trains on YOUR closed deals to surface "Hidden Gems" generic models miss; (b) Rapid Response = event-triggered direct mail the instant a qualifying distress event records, "set criteria once, runs on autopilot," with territory exclusivity. The "act on the event the moment it records" pattern is exactly our missing act-on-it layer. | Cited by a DataFlik defector as their primary marketing channel. | AUTO-ENGINE (pattern to copy, not buy) |
| 10 | **land-acquisition-intel** (Gonzih) - github.com/Gonzih/land-acquisition-intel | Free (no paid APIs, runs local) | Claude skill scoring parcels for a use-case (solar/warehouse/datacenter/ag/industrial) from free ArcGIS + OSM Overpass; pulls infrastructure layers (highways, rail, substations, transmission lines, water) into ranked CSVs. Ships `references/state-endpoints.md` with ArcGIS parcel endpoints including NC ("Best coverage: North Carolina"). The transmission/substation/rail OSM layers are a net-new buy-box facet for solar/industrial land. | New, thin usage; architecture mirrors ours (local, stealth-free, OSM+ArcGIS). | AUTO-ENGINE |
| 11 | **USDA NASS $/acre baseline** - quickstats.nass.usda.gov/api (wrappers: agriterra.io, placeacre.com, haystackland.com) | Free (USDA NASS is a public API) | County-level $/acre farmland baseline appraisers/ag-lenders use. AgriTerra's "Scout" queries six federal APIs in parallel (productivity, solar/wind, cash-rent, drought/water, grain-elevator bids, farmland value), no account. A free rural-ARV floor for our thin-comp SC/NC counties: reverse-engineer the 6-API list, skip the $39 PDF. | Legit public-data wrappers. | AUTO-ENGINE (valuation) |
| 12 | **PRYCD** ("priced") - prycd.com | Paid (Bronze $24.99/mo, Gold $499/yr; owner export $0.08/rec, skip $0.09/rec, comp $2; list scrubbing free) | The land PropStream for pricing: First American + 2.3M land comps, sub-county geo pricing zones, blind-offer/bulk pricing, KML export. Purpose-built for the rural/vacant thin-comp problem where Zillow/PropStream AVMs throw 40-60% error, our exact valuation-calibration pain. | Consensus land-pricing tool on BP/Reddit/RETipster; "not gospel" but best-in-class; complaints = state data gaps + learning curve. | OPERATOR (pricing); free scrub only for engine |
| 13 | **LienSuite** - liensuite.com | Freemium (free county breakdowns via r/DistressedRE; scored data is the paid product) | Scores tax-delinquent properties across **75+ Texas counties** (heir / curative-title / tax-deed niches). Founder "Nick" runs r/DistressedRE and posts county-by-county data breakdowns. TX-only today, so it is a **benchmark of our own tax-delinquent scoring model**, not a footprint feed, but the scoring-from-raw-tax-rolls approach is exactly ours. | Practitioner-run, data-first, explicitly anti-guru ("no $997 course links"). | AUTO-ENGINE (benchmark / model reference) |

---

## 2. Use 1 - auto lead engine (free public/compliant only; paid items flagged as fallback)

**Net-new distress SIGNAL sources (free public-record, some FOIA-gated):**
- **Water / utility shutoff + delinquency lists** - the most-cited net-new signal. A municipal water/electric shutoff (or unpaid-while-on delinquency) is an early distress flag preceding foreclosure, signaling vacancy/abandonment/probate/landlord collapse. Pull direct from Western NC + Upstate SC municipal water/electric authorities (public record; some require a records request). A vendor exists (usleadlist.com, paid) but the source is free. Stack with absentee + code-violation.
- **Eviction filings / eviction court calendars as a LANDLORD-seller signal** - our notes flag tenant-side evictions as a wall, but landlords with recurring evictions are a tired-landlord cash-out source. Free via county courthouse / public eviction calendar.
- **Fire/water-damaged property** - high-motivation, underworked; no clean free feed. Chase via fire-department incident reports, condemned/unsafe-structure code citations, insurance-claim adjacencies. Pairs with our existing code-enf work.
- **Failed / expired / withdrawn MLS listings** - highest-conversion reality-check signal (REDX: expireds re-list 44.4%; iSpeedToLead: failed-listing sellers convert ~4x fresh). Net-new tactic: skip fresh expireds (competitor call rush), work 6-12 month-old expireds where competition vanished. Dependency: needs MLS access or a licensed partner.
- **High-equity SENIOR owner combo** - 20+ yr ownership + owner age 60+ + 50%+ equity. We already have equity + ownership-length; owner-age is the one missing field (PropertyRadar / ATTOM carry it, both paid, so this stays a gap unless a free age source appears).
- **311 code-violation open-data feeds + stack-multiplier scoring** - from the DEV.to "$0 Texas Wholesale Pipeline" (dev.to, Load Bearing Capital): scrape county tax-delinquent + 311 code-violation, load to Postgres, score with stack multipliers, free skip, AI callers, on Railway. The 311/open-data portal is the workaround where county code-enf is walled. Code-violation stacking is called the #1 underworked lane; filter for 3+ open violations, structural (not tall-grass), open 6+ months, fines accruing.
- **County Clerk-of-Courts + Recorder's cloud-search pre-foreclosure scrape (net-new tactic, from r/WholesaleRealestate)** - a practitioner asking about Franklin County OH names the exact free path: scrape the **Clerk of Courts CIO** and **Recorder's cloud search** directly, filtered by **civil case-type codes** for lis-pendens / foreclosure complaints. This is the same court-index lane our NC eCourts / SC PublicIndex work runs; the transferable ask is "which civil case-type / civil-code keywords flag a foreclosure filing early" per county. Add a per-county case-code map to our court scrapers.

**Event-driven / marketplace sources to evaluate (all paid or trial, so reference only):**
- **FirstLeads** - firstleads.co - Trial then paid. Real-time fire/flood/water-damage incident monitor (property + owner + est. damage + optional skip), filters ~85% junk. Maps to our "fire = wall"; verify data legitimacy before relying.
- **REFAX** - refax.pro - Freemium (free browse + free 4-method AVM; full report $39.99/property). The free AVM over ~1M off-market REO/HUD/pre-fc/tax-delinquent/probate/vacant/absentee is a per-property ARV cross-check.
- **PropertyReach + PropPulse AI** - propertyreach.com - Paid. 150M properties, 130+ filters, search by phone/LLC/trust to pull whole portfolios; PropPulse scores 0-100 likelihood-to-sell-90-days.

**Open-source repos worth wiring or studying (all free):**
- **asreynolds1000/gc-property-search** - github.com/asreynolds1000/gc-property-search - IN-FOOTPRINT (Greenville SC) MCP: GIS owners/zoning/flood, tax assessment with sale history + valuations, ROD index + document-page-as-PNG, historical court records (probate, common pleas, general sessions, sheriff) 1780s-present, personal-property tax. Most tools need no auth. Probate + sheriff + sale-price for a core county in one place.
- **basepointcollective/MecklenburgNCScraper** - github.com/basepointcollective/MecklenburgNCScraper - Fresh tax-delinquent scraper for Mecklenburg NC (borders our core, large metro). Property-keyed tax-delinquency = our preferred lane.
- **camreon/property-pipeline** - github.com/camreon/property-pipeline - Blueprint: obituaries (Legacy.com) + public-notice, validate against county tax portals (DevNet/GIS/ArcGIS), skip, Sheets. PA-scoped but mirrors our obituary/pre-probate heir lane + adds a public-notice validator; mine `config/counties.yaml`.
- **biglocalnews/court-scraper** - github.com/biglocalnews/court-scraper - 83★, ISC. Most-starred county-court scraper framework (Big Local News/Stanford); parser reference for lis-pendens/civil-judgment (last push 2022, some drift).
- **freelawproject/juriscraper** - github.com/freelawproject/juriscraper - 603★, actively maintained. Gold-standard court/PACER scraper (powers CourtListener); reference if we chase federal foreclosure/bankruptcy.
- **robdplatt/SkipTracer** - github.com/robdplatt/SkipTracer - PoC map of free OSINT skip-source endpoints to port into the enricher (small/stale; PII/DNC still applies).

**Free tactics to mirror in the engine:**
- **County-treasurer email pull** - phone/email the Treasurer/Collector for the vacant-land tax-delinquent roll in Excel; many just send it. Free version of our delinquent-tax lane where portals are walled; tag by amount-due + delinquency-age, mail oldest-delinquency + lowest-amount first.
- **Liquidity-ratio pre-screen** - require Redfin Sold(12mo) ≥ 50% of For-Sale before entering a market (proves absorption before mailing).
- **Gold-standard triple stack = Absentee + High Equity + Tax Delinquent** converges on 5-8% conversion (highest documented). Stack-depth curve: 1 layer = 0.5-1% response / 1-3% convert; 4 layers = 5-10% response / 8-15% convert. Don't 4-stack too early (a 15-property list can't test marketing); start 2-stack. Rank by a model trained on your own closed/graded outcomes, not raw overlap count.

---

## 3. Use 2 - operator business, per stage (paid allowed, cost stated)

**FIND:**
- **XLeads** - xleads.com - Paid (~$79-160/mo). All-in-one: AI search, bundled skip (unlimited view, export-capped 25k-60k/mo), white-labeled GHL CRM, dialer, SMS, e-sign, AI SkyDrive satellite-distress, D4D app; handles non-disclosure states (TX) better than PropStream. Sentiment: legit (Ginn family, ~8k users) but recurring complaints of outdated data + learning curve; "free skip" is bundled, not free. Not an engine feed (bulk-export likely violates ToS).
- **LeadDeck.ai** - leaddeck.ai - Freemium (PAYG + 50 credits + 20 gifted leads, then paid). Mobile prospecting for pre-fc/inherited/vacant/tax-delinquent/high-equity + cash-buyer discovery by portfolio; one-tap skip via BatchData; CRM webhook/CSV.
- **Paxiv** - paxiv.com - Freemium (free nationwide core; paid only for unlimited AI/skip; $40/mo single-state). Parcel maps + owner records + validated zoning w/ source verification + real-time skip + NL parcel search. Free tier is materially cheaper than known tools; could seed the engine.
- **Land Owl** - landowl.com - Freemium (free plan, no card, 20 parcel views/mo). 160M parcels, 15+ layers (flood, wetlands, soil, transmission lines, gas pipelines, substations), county-verified w/ direct county links, export.
- **Land Insights Toolkit** (Chrome extension) - chromewebstore.google.com (search "Land Insights Toolkit") - Free. Overlays $/acre + sold-data + "Market Score" on Zillow/Redfin/Land.com.

**COMP / underwrite:**
- **DispoBridge ARV estimator** - dispobridge.com/tools/arv-estimator/ - Free, no login. Publishes exact weights: recency `max(0.5, 1-months×0.083)`, distance `max(0.6, 1-miles×0.4)`, 3-5 comps. Port into calc.py as a defensible free ARV fallback + cross-check.
- **RealEstateStackHub** - realestatestackhub.com - Free, no account, in-browser: cap rate, CoC, DSCR, BRRRR 5-phase, 5-yr projection (metrics DealCheck paywalls; manual comp entry).
- **Real Estate Investor Toolkit** - realestateinvestortoolkit.com - Free, no sign-up. ARV/MAO/rehab/BRRRR.
- **ARV Analyzer** - arvanalyzer.com - Trial (10 lifetime free, no card). Address/Zillow-URL to weighted-median ARV + confidence + MAO + 0-10 score + risk flags. Peers: **PropLab** (proplab.ai, 3 free = trial, claims MLS comps), **InvestorVI** (investorvi.com, AI filters out foreclosure/estate/non-arm's-length comps).
- **Listing Wand land calculator** - listingwand.com - Free, comp-anchored (normalizes access/utilities/buildability/terrain).
- **LeadSharks Wholesale & Profit Calculator** - leadsharks.io/real-estate-calculators/ - Free, no login (named by a part-time wholesaler on r/REIWholesaleVault as their MAO/profit tool). Another free calc.py cross-check.
- Skip **Propelio** (propelio.com) for our footprint: free tier + real MLS comps but only strong in TX/OK.

**SKIP (net-new; strict cost labels):**
- **Skipify.ai** - skipify.ai - Freemium (500 free property records, then $0.14/skip, no card). Only genuinely free-to-start entry on 2025 roundups; discount the "97%" claim.
- **Quality Skips** - qualityskips.com - Trial then $0.07/rec (free trial, no card, no signup). Rare zero-friction test bed.
- **REISkip** - reiskip.com - Paid (~$0.07-0.12). **Skip Matrix** - skipmatrix.com - Paid (~$0.05-0.10). **dataskip.io** - Paid (Reddit-endorsed "high connect rates"). **REI Data Solution** - reidatasolution.com - Paid (cleaner off-market numbers). **Goliath Data** - goliathdata.com - Paid (bundles TCPA-safe consent + life-event filtering). "$0.10/record is the sweet spot" refrain; pay only when free hit-rates cost deals.
- **Commercial/entity-owner lane** (MF/coastal LLC targets): **Proptracer** - proptracer.com - Paid. **PrimeTracers** - primetracers.com - Freemium (100 free credits). **AlphaMap** - alphamap.com - Paid. Paid equivalents of our free NC SoS-agent enricher.

**CONTACT (all heavy TCPA):**
- **smrtPhone** - smrtphone.io - Paid. Power-dialer/VoIP, deep Podio/REISift sync, partners with Launch Control.
- **Enzo Dialer** - maxenzo.com - Paid (~$180/mo, 50 free numbers = trial). Up to 14-line AI multi-dialer (auto-throttles by answer rate). Hyped in the Ginn/Dier ecosystem; discount.
- **Fusion REI** - fusionrei.com - Paid ("cheaper and better than Launch"). **LeadSherpa** - leadsherpa.com - Paid (list+skip+SMS in one). **BatchDialer** - batchdialer.com - Paid (voicemail-drop + predictive + DNC scrub).
- **Dial Master Solutions** - Paid (cold-calling VA staffing, named by a part-time operator on r/REIWholesaleVault - "hire cold-calling VAs that don't suck"). A VA-labor lane rather than a dialer, pairs with the "VA dials during the day, you follow up at night" part-time model.
- **AI cold-callers** (usage ~$0.05-0.13/min): **VAPI** - vapi.ai - Paid (lowest cost/most control, needs a dev; `silenceDurationMs: 700` interrupt fix is the recurring gotcha). **Bland.ai** - bland.ai - Paid (fastest no-code). **Retell** - retellai.com - Paid (best analytics). **AgentVoice** - agentvoice.com - Paid (most stable/lowest-latency in real calls). Consensus: good for quick follow-ups/booking, can't hold a long conversation. Wrappers: **White Space Solutions** - whitespacesolutions.ai (publishes an honest $0.18-0.28/min vs CallPorter/VA/W-2 cost table), **LeadAttractor.ai**, **iando.ai**.

**CONTRACT / CRM:**
- **InsulaCRM** (Free, OSS, self-hosted, Headline #6) is the standout.
- **HQFLO** - hqflo.com - Paid. **Pathwaize** - pathwaize.com - Paid. **REI BlackBook** - reiblackbook.com - Paid. GHL-based investor CRMs, "no 100-add-on-fees."
- **Bigin by Zoho** - bigin.com - Paid ($15/mo). **HubSpot** - hubspot.com - Freemium (free ~500 contacts). **SuiteCRM** - suitecrm.com - Free (self-host). **EspoCRM** - espocrm.com - Free (self-host).
- Land CRMs: **Stride CRM** - stridecrm.co - Paid (Seth Williams; API + AI voice agents, pairs with Land Portal API). **Pebble** - pebblerei.com - Paid. **Investment Dominator** - investmentdominator.com - Paid. **LandVu** - landvu.com - Paid.

**FUND (gator / creative-finance / transactional):**
- Blunt verdict: being the gator EMD lender is a bad business (tiny market, tiny dollars, unsecured against a broke borrower); the $3k-8k course is where the money goes; the post-course PCS / "Corporate Financial Program" business-credit-stacking upsell is the recurring soft-scam. Our leverage = deal originator feeding verified contracts into funder networks for a JV/assignment split, never fronting EMD.
- **Net-new transactional funders** (100% of A-B, fee on close, none in the known list): **Requity Group** - requitygroup.com - 2%, $50K-$5M, 24h. **Key Partners Funding** - keypartnersfunding.com - $1,000 flat under $100K / 1% to $1M. **Premier Transactional Funding** - premiertransactionalfunding.com - 1%, min $750, ~2h. **Y2 Lending** - y2lending.com. **Best Transaction Funding** - besttransactionfunding.com. **Coastal Funding** - coastalfunding.us. **Fund That Flip** (now Upright) - upright.us. Best free directory = your investor-friendly title company.
- **Gap / Morby-Method (2nd-position) funders:** **Levine Capital** - levinecapital.com - most community-embedded (Morby-Method + gap + DSCR 80% LTV). **Gap Funded** - gapfunded.com - unsecured gap + 0% business-credit stacking (same PG-risk mechanism as the PCS upsell).
- **CreativeFinance.app** (Headline #8) - the P2P EMD/option/transactional marketplace.

**DISPO (note the sub-400k-market caveat that hurts Western NC / Upstate SC):**
- **OfferMarket** - offermarket.us - Free (Headline #5). **Rezzie** - rezzie.com - Paid ($250/mo, buyer-side free). **Real Estate Bees** - realestatebees.com - Freemium. **InvestorBase** - investorbase.com - Paid (practitioner: "I sell 85-90% through Bees + InvestorBase"). Caveat: these need metros of 400k+; velocity lags in our sub-400k footprint.
- **DispoKey** - dispokey.com - Split-only ($0 upfront), supports Land. **DispoBridge** - dispobridge.com - Split-only ($0 upfront), supports Land, covers 19 NC cities incl. Charlotte, Asheville, Wilmington, Gastonia, Hickory, Concord. Cheaper than InvestorLift.
- Land dispo (net-new facet): **BuyerBridge.AI** - buyerbridge.ai - permit-backed matching to builders who filed permits in the last 12 months. **LANDFLIP network** - landflip.com (+ lotflip/farmflip/ranchflip) - auto-cross-lists by acreage. **Land Buyers Alliance** - landbuyersalliance.com - free builder/mobile-home/tiny-home buyer network. **LandsBuy** - landsbuy.com - owner-financed exits. **iFinderOffers** - ifinderoffers.com - agent-vetted off-market to vetted investors, free to join.

**Predictive / prioritization (concept to steal):**
- **DataFlik → DataSift** - datasift.ai - Paid (acquired by REISift 2025-07-01). **iSpeedToLead + DealPredictor** - ispeedtolead.com - Paid (top 19% of scored leads to ~40% of outcomes; failed-listing sellers ~4x). **HeyWalt.ai** - heywalt.ai - Paid (propensity scoring of a warm database). **Parcyl** - parcyl.ai - Paid (0-100 land screening + LOI/memo gen). Takeaway: rank by a model trained on closed-deal features, not raw stacking.

---

## 4. Communities (Carolinas lean)

**Carolinas REIAs (in-footprint, highest value):**
- **Upstate Carolina REIA (UCREIA)** - upstatecreia.com - Greenville SC, 3rd Monday, Embassy Suites 670 Verdae Blvd, members free / guests $20. Focus groups map to source/dispo lanes: Mobile Home, Private Lender, Rental, tax-lien/tax-deed, and the "Haves, Needs & Wants" barter/deal-matching meeting. Single most on-target Upstate community.
- **Carolinas REIA (CREIANC)** - creianc.org - Asheville NC, 3rd Tuesday, Highland Brewing, $197/yr. Membership includes a BOGO free affiliate membership with UCREIA Greenville (one payment gets both rooms). Weekly member "available properties" email = built-in dispo. Free "Newbys for Newbies" focus group is open.
- **WNC REIA** - wncreia.com - Zirconia NC, second WNC touchpoint (smaller, founded 2021).
- **Dealmaker WNC** - meetup.com/dealmaker-wnc - Asheville, genuinely free, "we do not sell anything," run by private-lender/attorney Mary Hart + MLO Haley Gant. Best low-friction first stop in WNC + private-lending relationships.
- **Metrolina REIA** - metrolinareia.com - Charlotte, $197/yr. Deepest cash-buyer pool in the Carolinas = the dispo room for Charlotte-metro contracts.
- **Charlotte REIA** - charlottereia.com - weekly Wed 8am IHOP breakfast + a Multi-Family/Commercial subgroup (2nd Monday) useful for our MF-source gaps.
- REIA sentiment: main-stage meetings are vendor-pitch-heavy; the focus groups and barter meetings are where deals actually move (Dealmaker WNC's no-sell policy is the exception).

**Reddit subs (firsthand, this pass):**
- **r/DistressedRE** - net-new, data-first sub for tax-delinquent / heir / curative-title / tax-lien-deed investors. Explicit ground rules: "no guru pitches or $997 course links," "specific numbers > vague advice." Founder-moderated (LienSuite's Nick). Closest sub to our actual sourcing thesis.
- **r/WholesaleRealestate** - most active practitioner sub; heavy self-promo + "DM me" funnels (mods now permaban for it), but real deal-flow, dialer, and legal threads surface here. Best single sub to monitor for footprint chatter.
- **r/TheWholesalersToolbox**, **r/REIWholesaleVault** - smaller tool/tactic subs (cash-buyer-list and part-time-wholesaling guides came from these).

**FB / Skool wholesaling communities (free tiers):**
- **Wholesaling Real Estate (Zach & Rick Ginn)** - skool.com/wholesaling-real-estate - Free tier (course + daily motivated-seller lists + MAO calc + repair estimator + contract generator; upsell is a separate $226/mo "PUMP"). Best single free wholesaling plug-in.
- **Wholesale Hackers** - wholesalehackers.com - Free (FB-ad seller-lead focus). **Real Estate Wholesaling / Tadi** - skool.com/virtual-wholesaling-8362 - Free (lists + JV). **REI Game Changers** - high-pitch, scout only.

**Land-investing communities (free tiers):**
- **Landman Community (Clay)** - skool.com/landman-community - Free tier, has a Funded Deals Board + Deal Funding channel (land FUND lane) + "Dispo Decoded." Best free land operator room.
- **High Value Land Group (Jonathan Duong)** - skool.com/value - Free tier, ~1.7k, monthly masterclass + JV deal opportunities (strongest land DISPO/JV).
- **The Land Lab** - skool.com/thelandlab - Free tier. **The Land Profits Community (Ella Hardy)** - skool.com - Free tier (EDU/sourcing front-end).

**Creative-finance communities (free alternatives to the $20k SubTo / $3-8k Gator):**
- **Creative Real Estate Academy / Acquisition Architects** - skool.com/acquisition-architects - Free tier, ~1.5k, "find motivated sellers without paying for lists" + deal structuring. Best free SubTo/creative alternative.
- **Seller Finance Freedom Academy** - skool.com/sellerfinancefree - Free (dispo Craigslist template). **Broke Millionaires** - skool.com/brokemillionaires - Free (weekly office hours). **BiggerPockets Creative Financing + Subject-To forums** - biggerpockets.com/forums - Free (the honest counterweight to guru Skools).
- **Creative TC / Caleb Christopher** - calebchristopher.io - Free 15-min consult; publishes real (including losing) financials. A safe/legal subject-to operational resource, not sourcing.

**YouTube channels (free):**
- **Flip With Rick** - youtube.com/@FlipWithRick - teaches government data lists (probate, tax-delinquent) + nationwide dispo. **Real Estate Skills** - youtube.com/@RealEstateSkills - best free cash-buyer/dispo tutorial + MLS-as-source. **Flipping Mastery TV** - youtube.com/@FlippingMastery - deal analysis/MAO. **Pace Morby** - youtube.com/@PaceMorby - most-watched free creative-finance library (treat the paid Subto/Gator upsell with skepticism).
- **The Koerner Office** (podcast, named in r/WholesaleRealestate) - ran a detailed land-wholesaling-to-spec-builders episode (avg $8,600/deal, "iPhone + willingness to cold call"). The playbook is solid; the caution (see Section 6 firsthand intel) is that it recommended Wilmington NC without mentioning NC's Oct-2025 wholesaling-is-brokerage law.

**Instagram accounts (PENDING - carried from web sweep, NOT verified live; IG read 401'd this pass):**
- **@pacejordanmorby** - instagram.com/pacejordanmorby (creative finance/subto). **@investorfreed** - instagram.com/investorfreed (Andrew Freed, candid portfolio building). **@janelle.and.don.invest** - instagram.com/janelle.and.don.invest (Airbnb + wholesale + flip). **@cre_capital** - instagram.com/cre_capital (Rachel Garcia, commercial financing, relevant to MF gap). Skip luxury-agent/TV lists (Serhant, Oppenheim, Cardone), not off-market sourcing. Re-verify once IG session is fixed.

---

## 5. Compliance flags (operator-optional, NOT for the auto-engine)

Everything here is human-operator activity; the auto-engine's free mail-spine + owner-name/address stays the compliant scaled lane per the known playbook.

- **NC + SC WHOLESALING IS NOW BROKERAGE ACTIVITY (footprint-critical, firsthand from r/WholesaleRealestate).** **South Carolina HB 4754 is effectively closed to the unlicensed.** **North Carolina made wholesaling brokerage activity as of October 2025** - "its definition is broad enough that double closing isn't a workaround" - and Wilmington NC is one of the markets gurus still recommend. This directly hits our OPERATOR footprint (Upstate SC + Western NC). Practical read: the unlicensed operator can still SOURCE and originate, but assigning/marketing a contract in NC/SC now needs a license or a licensed partner, and double-close does not cure it. Verify current statute with a SC/NC RE attorney before any operator marketing. **This does not touch the AUTO-ENGINE** - sourcing public-record distress data and mailing owners is not brokerage - but it reshapes what the human business can legally do with a contract.
- **All bulk-SMS tools** (Smarter Contact, Fusion REI, LeadSherpa, Launch Control) require A2P 10DLC registration + federal DNC scrub (re-scrub ≥31 days) before any send. Cold SMS is the most-litigated wholesaler channel. Smarter Contact's built-in DNC scrub is the "act-on-it/DNC layer" our path_to_100 flagged, but the obligation, not the feature, is the point.
- **AI cold-callers (VAPI/Bland/Retell/AgentVoice) = highest TCPA risk.** The FCC's 2024 ruling treats AI/prerecorded voice to cell phones as "artificial voice," prohibited without prior express consent. Do NOT point an AI caller at a cold, non-consented list. Multi-line/predictive dialers (Enzo, BatchDialer) are the exact pattern regulators target.
- **Every skip-trace source** (Skipify, Quality Skips, dataskip, REISkip, Goliath, RealEstateAPI SkipTraceBatch, Apify output, SkipTracer OSINT) still triggers DNC scrub + TCPA before any dial/text. Free/OSINT data does not remove the compliance layer.
- **ToS / bot-wall (auto-engine boundary):** programmatic scraping of TruePeopleSearch/FastPeopleSearch and bulk-exporting XLeads/DataSift/paid-platform data for an automated pipeline violates their terms and crosses our bot-wall line. Those are operator-manual/low-volume tools, never engine feeds. (Reconfirms the known note: no free automatable name+address to mobile path exists; NC voter file remains the one free source.)
- **Sensitive-niche timing:** probate outreach sweet spot is 30-90 days post-filing (too early reads as insensitive); water-shutoff and code-violation data are public but some counties require a formal FOIA/records request rather than a portal pull. Divorce/fire outreach carries sensitivity/timing rules.
- **Creative-finance structural/legal risk** (operator, not engine): SubTo/Morby-Method deals carry due-on-sale-clause + seller-credit-damage exposure. Order a $50-60 title report per deal, use escrow not table closings, record the deed properly, keep reserves, don't hide in a land trust, and never over-promise "zero down / no risk" in outreach. The PCS / business-credit-stacking upsells (Gap Funded, Credit-to-RE VIP) are legitimate mechanisms but oversold with personal-guarantee risk. Gator/EMD arrangements sourced from strangers in FB groups are the single highest-fraud-risk activity in this map; verify every counterparty, use a closing attorney comfortable with simultaneous closings.

---

## 6. Firsthand Reddit intel

Direct practitioner sentiment sampled this pass from Reddit search + subreddit hot posts (Instagram/Facebook pending a session fix, so this section is Reddit-only). Attributed to the sub. Short quotes; either validates/corrects Source A above or surfaces something it missed.

**Foreclosure-tool honesty check (validates our free-first stance).** A r/HouseBuyers teardown, "I tested 5 foreclosure tools so you don't have to waste $300," on the paid-tool churn: *"I genuinely lost track of how much money I spent just subscribing to things"* and, bluntly, *"I AM NOT RECOMMENDING ANY OF THESE... THEY'RE ALL PIECES OF SHIT."* On PropStream specifically it corrects the marketed price: *"it starts at $99/month and skip tracing is only free on the more expensive plans, so you're probably looking at $199/month,"* and *"it is NOT a foreclosure-specific tool. Foreclosures are just one filter among a hundred."* Operational takeaway that maps to our free-only engine rule: *"you can get a free trial with almost any of these... The main thing is just not to forget to cancel."* Reinforces that paid tools stay OPERATOR-side trials, never engine feeds.

**r/DistressedRE + LienSuite (NEW community + NEW benchmark).** The sub's pinned post is the clearest statement of our own thesis from someone else: it is *"for investors who work distressed real estate - tax delinquent properties, heir properties, curative title deals,"* with ground rules *"no guru pitches or $997 course links"* and *"specific numbers > vague advice."* Founder Nick runs **LienSuite**, which *"scores tax delinquent properties across 75+ Texas counties."* TX-only, so it is a model/benchmark for our scoring, plus the single best sub to monitor. (Added as Headline #13.)

**NC/SC is now a licensing wall (CORRECTS the guru playbooks; footprint-critical).** From r/WholesaleRealestate on the Koerner Office land-wholesaling episode: the model is *"find a builder's buy box, call landowners in the same zip codes, sign an assignable contract, collect the spread... Average profit per deal: $8,600. Startup cost: genuinely zero."* But the poster flags what the episode omitted: *"South Carolina (HB 4754) is effectively closed to the unlicensed"* and *"North Carolina - including Wilmington, one of the markets this exact episode recommends - made wholesaling brokerage activity as of October 2025, and its definition is broad enough that double closing isn't a workaround."* This is the single most important operator finding of the pass (promoted into Section 5).

**Buyer-first is the real bottleneck (validates dispo emphasis).** A land wholesaler's cautionary post, "Almost blew my earnest money on a 3-acre FL lot": *"Signed the contract, cracked a beer, and then it hit me. I had no actual buyer lined up... I ended up assigning it for a tiny scrap of profit."* Echoed by the r/TheWholesalersToolbox guide: *"Your cash buyers list is your business... build your buyers list first."* Validates prioritizing OfferMarket/DispoBridge dispo tooling and the "buyer buy-box before you lock up" discipline, especially in our thin sub-400k markets.

**Creative-finance dispo pain is buyer-education, not buyer-supply (nuance Source A missed).** A subject-to operator in r/WholesaleRealestate: *"Finding motivated sellers and structuring subject-to deals... hasn't really been the hard part. Where I keep running into friction is on the buyer side... finding investors who already understand these structures."* On why they avoid public marketing: *"I try not to blast deals over facebook... over saturated with scammers and other wholesalers looking to steal deals,"* and *"sellers in my experience don't respond favorably seeing their property advertised online."* Reframes the creative-finance-community value: the win is a small vetted capital-partner circle (CPAs, wealth managers, business-owner networks), not a bigger blast list.

**Part-time / VA-driven cold-calling stack (NEW named tools).** A decade-long part-time wholesaler on r/REIWholesaleVault names their actual stack: lead flow via **iSpeedToLead** (validates Source A's predictive entry) and *"Dial Master Solutions for Cold Calling"* (VA staffing, net-new), plus a free **LeadSharks** MAO/profit calculator (leadsharks.io). Their model: *"Have a VA dial for you during the day... follow up on hot leads after work... a drip campaign for cold."* The sober line worth keeping: *"It's a SIMPLE business model, not EASY... if you treat it like a hobby, it'll pay like a hobby."*

**Franklin County pre-foreclosure scrape (NEW free tactic).** A r/WholesaleRealestate post asks exactly how we source: *"If you are scraping raw data directly from the county sites (Clerk of Courts CIO or Recorder's Cloud Search), what are the best case type codes, civil codes, or keywords you look up to spot [pre-foreclosures] early?"* Confirms the free court-index lane is live practice and gives us the concrete to-do: build a per-county civil-case-type-code map for early foreclosure-filing detection (added to Section 2).

**DealMachine free skip (validates known tool).** r/TheWholesalersToolbox: DealMachine offers *"free skip tracing and 96.5% owner data accuracy"* and *"DealMachine's Cash Buyer Data - instantly pull a list of verified investors buying in your market."* DealMachine is already in our known list; the net is that its free skip + cash-buyer pull is a legit OPERATOR D4D entry, not the bulk-export engine feed.

**Community self-promo hygiene (context for monitoring).** r/WholesaleRealestate mods now permaban for harassment and *"'DM me!' stuff in posts... considered funnels to get people off the sub for products or services being shilled."* Practical filter: on Reddit, weight data-first posts (r/DistressedRE style) and discount anything routing to a DM or a Skool/Discord upsell.

---

## 7. Adopt for our engine - ranked

Top net-new items to actually wire or use, deduped against the known playbook. Split by use. PII/TCPA/ToS flags called out.

**AUTO-ENGINE (free + public + compliant only):**
1. **mcp-atlas** (free, MIT) - pull the 150+ verified county-parcel ArcGIS endpoint + owner-field list; fills our `_STREET_NUM/NAME_FIELD_CANDIDATES` gaps directly. No PII/ToS issue (public GIS field metadata). Highest-value, zero-cost, wire first.
2. **land-acquisition-intel** NC endpoint file + OSM layers (free, local) - adopt `references/state-endpoints.md` (NC = best coverage) and add the OSM transmission/substation/rail buy-box facet for solar/industrial land. Runs local, no paid API, no ToS risk.
3. **USDA NASS $/acre** public API (free) - wire as the rural-ARV floor for thin-comp SC/NC counties; reverse-engineer AgriTerra's 6-federal-API "Scout" list instead of buying the $39 PDF. Fully public data.
4. **DispoBridge ARV weights** (free, published) - port the exact recency/distance weights into calc.py as a defensible free ARV cross-check. No login, no data pull, just the formula.
5. **Per-county civil-case-type-code map for pre-foreclosure** (free tactic, from the Franklin County thread) - extend our NC eCourts / SC PublicIndex scrapers with a case-code lookup so foreclosure filings surface early. Public court index; keep to the compliant court-JSON endpoints we already use, not the WAF-walled browsers.
6. **LienSuite / r/DistressedRE as a scoring benchmark** (freemium/free) - mirror their raw-tax-roll → distress-score approach for our TX-model calibration and monitor the sub. Benchmark only (TX-only footprint); no data buy.
7. **Study repos (free):** `asreynolds1000/gc-property-search` (Greenville SC probate + sheriff + sale-price in one MCP) and `camreon/property-pipeline` (obit → public-notice → tax-portal validator). Mine the endpoints/validator patterns; `robdplatt/SkipTracer` OSINT map is portable but **PII/DNC still applies to any skip output**.

*Explicitly NOT for the engine (paid or ToS-walled): RealEstateAPI, Land Portal API, PRYCD, Apify Distressed scraper - all OPERATOR paid fallbacks only, never engine feeds. TruePeopleSearch/FastPeopleSearch/XLeads bulk export = ToS bot-wall, stays manual.*

**OPERATOR (paid OK; flags noted):**
1. **NC/SC licensing reality first** - before any operator marketing, confirm SC HB 4754 / NC Oct-2025 status with a RE attorney. This gates the entire operator dispo motion in our footprint (source freely; assign/market needs a license or licensed partner; double-close does not cure). **Legal, not a purchase - do this before spending on any contact tooling.**
2. **InsulaCRM** (free, OSS, self-hosted) - stand up as the wholesaling CRM; our engine pushes leads straight into its `/api/v1`. Own-your-infra, BYOK AI. No recurring cost.
3. **OfferMarket** (free dispo) + **DispoBridge/DispoKey** ($0-upfront split) - list contracts free; DispoBridge already covers 19 NC cities incl. Asheville/Charlotte/Wilmington/Hickory/Concord. Best fit for our sub-400k markets where InvestorLift velocity lags.
4. **CREIANC membership** ($197/yr, free UCREIA BOGO) - one payment opens both the Asheville and Greenville rooms; **Dealmaker WNC** (free, no-sell) is the low-friction first stop and a private-lending on-ramp.
5. **Skipify.ai / Quality Skips** (freemium/trial, ~$0.07-0.14/rec) - cheapest zero-friction skip test beds when free hit-rates cost deals. **PII + DNC scrub + TCPA apply to every record before any dial/text.**
6. **iSpeedToLead + Dial Master Solutions + LeadSharks calc** (mixed: paid lead flow / paid VA / free calc) - the validated part-time stack; VA-dial-by-day, follow-up-by-night. **All outbound calling is heavy-TCPA; scrub DNC and honor consent.**
7. **Paid data fallbacks only if free county coverage genuinely thins:** RealEstateAPI (structured skip/property, ships llms.txt), Land Portal API (agent-drivable land enrichment), PRYCD (best-in-class rural land pricing, free list-scrub usable standalone). Keep all three OPERATOR-side; **bulk export into an automated pipeline would cross their ToS.**

*Highest-value net-new to act on this week: (1) wire mcp-atlas + land-acquisition-intel + USDA NASS (all free AUTO-ENGINE), (2) port DispoBridge ARV weights into calc.py, (3) resolve the NC/SC wholesaling-license question before any operator dispo spend.*

---

## Instagram firsthand sweep (seated as @cash_high, 2026-07-03)

IG search is not geo-filtered, so these are national creative-finance / wholesale EDUCATORS, useful for the operator-side network and the "investor/buyer education is the real dispo bottleneck" point from Reddit, not local lead sources. Ranked by followers:

| Account | Followers | Verified | Focus |
|---|---|---|---|
| @creativefinanceguy (Evan Ragsdale) | 4,743 | Yes | Creative finance, 120+ deals closed, free training funnel |
| @123wholesalingcoach | 1,876 | Yes | Wholesaling coaching, claims 1,000+ deals |
| @subjecttorealestateinvesting | 704 | No | Subject-to (take over the mortgage + get the deed) + site |
| @therealmikeymartin | 545 | No | Documents a creative-finance journey to 100 units |
| @907creativefinance | 82 | No | Connects distressed sellers with creative solutions |
| @creativefinancerealestate | 79 | No | Cash / creative buyer (FL metros) |
| @realestatewholesaling | 55 | No | Wholesaling education, partner-with-investors angle |

(@daily_wholesaling shows 2,362 followers but only 2 posts, effectively inactive, skip.)

Takeaway: Instagram is an education/network channel for the creative-finance dispo lane, not a sourcing channel. Facebook groups would be the higher-value social channel (local Carolinas REI groups + Marketplace cash-buyers), but the Facebook session is not seated yet.
