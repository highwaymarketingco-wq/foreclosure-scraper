# THE REI OPERATOR PLAYBOOK

Every free/cheap source, tool, scraper, and site across every real-estate-investing process and signal, organized so you can act. Footprint bias: Western NC + Upstate SC core (with national fallbacks). Prices are per-month unless noted. Compliance line held throughout: FREE = free + public with no CAPTCHA/WAF/ToS evasion; anything that returns owner phone/email is flagged PII/TCPA (legal to buy, but DNC-scrub and honor consent before any call/text; mail has no TCPA exposure).

Two hard rules that repeat everywhere:
1. Owner NAME + MAILING ADDRESS from public records is free and clean, and it powers direct mail with zero TCPA exposure. Use it as the spine.
2. Phone/email for calling/texting: BUY from a pay-per-hit vendor (cheaper and compliant), never scrape people-search sites (TruePeopleSearch, FastPeopleSearch, Spokeo, etc.). Then scrub Federal DNC + Internal DNC + FCC Reassigned Numbers before dialing. Note for this footprint: neither NC nor SC maintains a separate state DNC registry, so the 31-day federal scrub covers both.

---

## 1. THE PIPELINE MAP

Stages: FIND -> ANALYZE/COMP -> SKIP-TRACE -> CONTACT -> CONTRACT -> FUND -> DISPO. For each: the top FREE tool(s) and the best cheap paid option.

| Stage | Top FREE tool(s) | Best cheap paid option |
|---|---|---|
| **FIND** | County GIS / assessor bulk parcel file + county tax-delinquent list + county court (probate/divorce/foreclosure) indexes. One assessor bulk file derives absentee, out-of-state, senior, high-equity, tired-landlord, and vacant-proxy signals with no vendor. | PropStream ($99/mo; 7-day trial, 50 free leads) for 100+ pre-built distress filters in one place. |
| **ANALYZE / COMP** | Redfin sold data + Zillow (browse only) + New Silver / ArvCalc / DealCheck free ARV calculators + county sold records. | DealCheck (~$14-29/mo) or PropStream comps (in the $99). |
| **SKIP-TRACE** | County owner-of-record NAME + MAILING ADDRESS (free, clean, mail lane). MERS ServicerID (mers-servicerid.org) for current loan servicer. | Tracerfy $0.02/hit (charged only on match) for phones; PropWire $0.10/successful match; PropStream $0.10-0.12/trace. |
| **CONTACT** | Direct mail (owner name+address; no TCPA) sent via a mail house (Yellow Letter HQ / Ballpoint / Open Letter / Lob / USPS EDDM). FB investor groups / Craigslist for buyers. | Mojo Dialer ($89-149) for cold calls + PATLive (entry ~$75 for light minutes; real seller-call volume lands higher) inbound answering. RVM ~$0.0175/msg. |
| **CONTRACT** | Free wholesale purchase + assignment templates (realestateskills.com, BiggerPockets forums, DocuSign template library) + Portant free e-sign (30 docs/mo). | BoldSign (unlimited docs/templates) if you outgrow free e-sign caps. One-time NC/SC attorney review. |
| **FUND** | Transactional/EMD lenders with FREE proof-of-funds letters, no upfront fee (DoubleClose.com, Straightline, Axelrad, Tidal, Levine). | Transactional funding ~0.75-2% of purchase (min ~$750); gap funding = interest + points on the shortfall only. |
| **DISPO** | FB investor groups + Craigslist + county cash-buyer deed pulls (recent no-mortgage purchases). | PropStream cash-buyer search (in the $99; trial = 50 free); InvestorLift ($500+) only at multi-deal/mo volume. |

**Solo-operator floor: ~$250-350/mo** (PropStream + Mojo + PATLive base) plus per-hit skip and per-mail costs. Scale to InvestorLift/Launch Control/FreedomSoft only when deal volume pays for it.

**Two market facts baked in:** (a) PropStream acquired BatchLeads in July 2025 (under Stewart Information Services); as of now the two platforms still run independently with no forced pricing change, so BatchLeads (~$71/mo) and PropStream ($99/mo) are both still live and separately priced -- do not assume the buy has collapsed them into one product yet. (b) Cold SMS blasting is effectively dead post-A2P 10DLC crackdown (carriers suspend cold RE texting accounts) -- plan around cold call + RVM + mail, not text blasts.

---

## 2. SIGNAL SOURCE TABLE

Every motivated-seller signal, its best FREE source/tool, and access method. All feed FIND -> then join the owner name to a parcel via GIS/assessor -> mail.

| Signal | Best FREE source | Access method | Notes / paid alt |
|---|---|---|---|
| **Pre-foreclosure / NOD / lis pendens** | NC: Clerk of Superior Court "Special Proceedings" (SP) files + lis pendens at Register of Deeds + sheriff Notices of Sale. SC: county Master-in-Equity judicial-sale roster. | County court portals + Column legal-notice / newspaper legal sections; NC eCourts JSON. Owner-named, statutory, free. | Beats every national tool for owner names. PropStream trial for one-shot enrichment. |
| **Foreclosure / auction / REO** | Auction.com (browse), Xome, Hubzu, Servicelink (auction-stage: address, sale date, opening bid). HUD HomeStore, Fannie HomePath, Freddie HomeSteps, USDA resales (REO acquisition). | Browse only (ToS no-scrape + bot-walled); cross-reference addresses to county rosters. Gov/GSE portals = free bid/offer. | Auction.com = best free national auction feed. USDA resales good for rural W-NC. |
| **Probate / inherited** | County Clerk of Court / Register of Deeds estate & probate index (decedent, PR/executor, filing date). | NC eCourts estate index (Smart Search browser WAF-walled); SC county Probate sites (PublicIndex ToS-no-scrape = manual-operator lane). Join PR name to parcel via GIS. | US Probate Leads ~$30-100/county/mo (pre-cleaned). |
| **Pre-probate (obituaries)** | Legacy.com + funeral-home RSS feeds + local/Gannett newspaper obits. Earliest possible heir signal. | Read/RSS ingest; match obit name + city to assessor owner search -> decedent-owned parcel -> mail heirs. | Public data; clean name-to-parcel match. |
| **Divorce** | County civil/family court index (domestic filings). | NC eCourts Judgment Search JSON serves divorce (compliant). SC Family Court restricted + Rule 610 limits bulk civil use (wall). Join spouse names to jointly-owned parcel. | Forced sale of jointly-titled property = high motivation. |
| **Tax-delinquent** | County Tax Collector delinquent list / upset-bid / tax-sale roster (annual statutory publication + online unpaid-parcel search). | NC PTS Cloud API + county .gov PDFs; SC Spartanburg qPayBill (join by TMS). Owner mailing address already on the tax record. | Taxes-owed $ = best distress-severity score. |
| **Code violation / condemned / demolition** | Municipal code-enforcement portal / open-data where it exists. 311 / SeeClickFix nuisance feeds. | Asheville code-enforcement (built). Open violation -> parcel -> owner -> mail "we buy as-is." Many small counties have no feed (wall). | Highest as-is-cash motivation. |
| **Vacant** | Parcel-level: county vacant-property registries (address-level, e.g. Spartanburg ~5k). Aggregate: HUD USPS vacancy data + USPS Occupancy Trends (ZIP/route/county). | Registries = direct. HUD aggregate = neighborhood targeting only (gov/nonprofit registration; USPSVacancydata@hud.gov). Assessor "mailing=situs" + no-permit proxies. | Regrid sells parcel-level USPS vacancy (paid). |
| **Absentee / out-of-state** | County assessor bulk parcel file. Owner MAILING <> property SITUS = absentee; mailing-state <> property-state = out-of-state (strongest). | Compare situs vs mailing in the bulk file; tier and mail to the mailing address you already have. Zero skip-trace needed. | Fully in-house, free, clean. |
| **Tired landlord / eviction** | Assessor bulk: owner-name aggregation (3+ non-owner-occupied parcels) + code violations concentrated on one owner + out-of-state 2-4 unit owners. | Eviction filings are largely a wall (landlord is plaintiff; SC magistrate roster retry pending). Use the proxies. | Mail "sell your portfolio, we close on all." |
| **High-equity / free-and-clear** | Register of Deeds + assessor, joined in-house. Free-and-clear = no active deed of trust on record; equity = value minus outstanding lien. | ROD index + FREE ROD document images (OCR loan amount) + assessor sale price. No lien + long tenure + older owner = gold. | Feeds seller-finance/gator lane. |
| **Expired / withdrawn listings** | No fully-free public feed. Licensed-agent/partner MLS login is the only free route. Zillow "off-market" per-property (browse, no bulk). | MLS native search (free to an agent partner). | Vulcan7 / RedX / Landvoice ~$60-150/mo (expired + FSBO + skiptraced phones; PII/TCPA line). |
| **Senior / 55+** | Assessor bulk + county senior/homestead/over-65 exemption flag (age proxy without buying age data). | Senior-exemption flag + long tenure (deed 20+ yrs) + free-and-clear = downsizing seller. | Pairs with probate + creative finance. |
| **Bankruptcy** | PACER federal bankruptcy court ($0.10/page; fees waived if < $30/quarter = effectively free for light use). 341-meeting calendars. | pacer.uscourts.gov; some petitions surface in county lis-pendens/judgment index. Debtor name -> parcel -> equity. | Automatic stay + trustee involvement = specialized lane. |
| **Land-specific** | County tax-delinquent list filtered to land-use = vacant/ag/unimproved + county GIS land-use=vacant + absentee flag. | Filter delinquent roll + GIS by property class; owner mailing on the tax record. | AcreValue / Regrid for rural comps + bulk. |

---

## 3. WHOLESALE TOOLSTACK (named tools, FREE-vs-price, URL)

### List building
- **County pulls / GIS / assessor** -- FREE -- (per-county) -- your spine; no vendor.
- **PropStream** -- PAID $99/mo (7-day trial that has historically included ~50 free leads; confirm the current trial terms before quoting the number to anyone) -- propstream.com -- best single paid buy; stack distress filters, export.
- **BatchLeads** (PropStream-owned since July 2025, still priced independently) -- PAID from ~$71/mo (usage-tiered; verify current tier) -- batchleads.io -- list-pull + stacking + skip in one.
- **REsimpli** list tools -- PAID (bundled $99-149; 14-day trial) -- resimpli.com.
- **ListSource** -- PAID pay-per-record -- listsource.com -- legacy list standard (county GIS + PropStream replaces most of its spend).
- **PropWire** -- FREE core (no card) -- propwire.com -- closest thing to a free PropStream: 157M records, motivated-seller filters, comps, list-stacking.

### Comping / ARV
- **Redfin / Zillow** -- FREE -- redfin.com / zillow.com -- Redfin sold data is cleaner; browse only, no scrape.
- **New Silver ARV Calculator** -- FREE (no login) -- newsilver.com.
- **ArvCalc** -- FREE (30 calcs, no signup) -- arvcalc.com -- ARV, cap rate, DSCR, cash-on-cash, NOI.
- **DealCheck** -- FREE starter; paid ~$14-29/mo -- dealcheck.io -- best free-tier analyzer.
- **BiggerPockets Calculators** -- FREE tier / Pro paid -- biggerpockets.com.
- **PropLab** -- FREE 10 ARV calcs then paid -- proplab.app.
- **Privy** -- PAID -- getprivy.com -- MLS-driven "what flippers are buying" mapping.

### Skip tracing (PII line lives here)
- **County owner-of-record** -- FREE -- name + mailing address; clean for mail.
- **Tracerfy** -- ~$0.02/hit (match-only; confirm it isn't a volume-floor/minimum-commitment rate before treating $0.02 as the flat headline price) -- tracerfy.com -- cheapest, best for volume.
- **PropWire skip** -- $0.10/successful match (pay-as-you-go); PropWire Gold (~$119/mo) bundles thousands of skips if you run volume -- propwire.com -- cleanest pay-as-you-go.
- **BatchSkipTracing** -- ~$0.02/record at Growth volume -- batchdata.io.
- **PropStream skip** -- $0.10-0.12/trace -- propstream.com.
- **Skip Genie** -- $0.14/record -- skipgenie.com.
- **TLO / IDI (LexisNexis)** -- ~$0.10-0.25/hit, gated -- tlo.com / idicore.com -- the source the cheap vendors resell.

### CRM
- **Google Sheets** -- FREE -- sheets.google.com -- start here.
- **Podio** -- FREE up to 5 users -- podio.com -- classic investor DIY CRM.
- **REsimpli** -- PAID $99-149 (14-day trial) -- resimpli.com -- all-in-one (lead, dialer, drip, mail, KPI, cash-buyer search).
- **InvestorFuse** (on Carrot) -- PAID from $69/mo -- investorfuse.com.
- **FreedomSoft** -- PAID $197-497 -- freedomsoft.com.

### Marketing / contact
- **Direct mail** -- FREE data (owner name+address) + print-mail cost -- no TCPA exposure; safest high-volume channel. "No TCPA" is not "no rules": mail still falls under state UDAP / deceptive-solicitation law and NC's own solicitation statutes, so keep a clear return address and non-deceptive copy.
- **Mail houses (the execution layer for the mail spine)** -- PAID per-piece -- Yellow Letter HQ (yellowletterhq.com), Ballpoint Marketing (ballpointmarketing.com), Open Letter Marketing (openlettermarketing.com), PostcardMania (postcardmania.com), Lob (lob.com, API for automated mail from the engine), and USPS EDDM / Click2Mail for saturation routes. Feed them the free owner name+address list; this is what actually mails the spine.
- **DealMachine** -- PAID (7-day trial, then Starter ~$49/mo = 1 driver + 500 skips, Pro ~$99/mo, Elite ~$249/mo on annual billing; +$20/mo add-ons + usage-based mail/call/RVM) -- dealmachine.com -- the category-leading driving-for-dollars / list app; its skip-trace returns phone, so same PII/TCPA lane as the others (FlipMantis is the free substitute for the D4D function).
- **Mojo Dialer** -- $89-149 -- mojosells.com -- triple-line power dialer, ~300 dials/hr, auto-drops VM.
- **PATLive** -- entry ~$75/mo but that tier buys very few minutes; a real seller-call load lands in the several-hundred-per-month range (plans run to ~$1,170) -- patlive.com -- 24/7 US receptionists run your seller script.
- **RVM (Drop Cowboy / Slybroadcast)** -- ~$0.0175/msg -- treat as calls (scrub DNC).
- **Launch Control** -- $497-1,497 -- launchcontrol.us -- cold text (warm/opted-in only in 2026).
- **Smarter Contact** -- $199-499 + ~$0.02-0.03/text -- smartercontact.com.
- **Google Voice (burner number)** -- FREE -- voice.google.com -- keep a separate outbound number for the calling lane so your primary line isn't spam-flagged; does not replace DNC scrubs.

### Compliance stack (run before ANY call/text/RVM)
- Federal DNC scrub every 31 days (dnc.com) -- required. In our footprint this is the whole state layer: neither NC nor SC keeps a separate state DNC list (SC never adopted one; NC's Telephone Solicitations Act enforces against the federal registry), so do NOT waste time hunting a nonexistent NC/SC list -- the federal scrub satisfies both.
- Internal DNC (log every opt-out) -- required.
- FCC Reassigned Numbers Database -- required.
- Litigator / serial-plaintiff scrub (Litigator Scrub) -- best practice, cheap insurance.
- RVM / ringless voicemail is treated as a call under TCPA -- run it through the same DNC scrubs, do not treat it as "not a call."

### Contracts / assignment
- **Free templates** -- FREE -- realestateskills.com, BiggerPockets forums, DocuSign template library -- one-time NC/SC attorney review (NC requires disclosing you assign a contract, not sell the property).
- **Portant** -- FREE 30 docs/mo -- portant.co -- best free e-sign for volume.
- **Jotform Sign** -- FREE tier -- jotform.com.
- **DocuSign / Dropbox Sign** -- FREE 3 docs/mo -- docusign.com / hellosign.com.
- **BoldSign** -- PAID unlimited -- boldsign.com.
- **Dotloop** -- PAID -- dotloop.com -- full transaction management.

### Dispo / cash buyers
- **Facebook investor groups** -- FREE -- facebook.com -- fastest free buyer-list build.
- **Craigslist** -- FREE -- craigslist.org.
- **County cash-purchase deeds** -- FREE -- recent no-mortgage deeds = active cash buyers.
- **PropStream cash-buyer search** -- PAID (in $99; trial 50 free) -- propstream.com.
- **InvestorLift** -- PAID ~$500-4,000+ -- investorlift.com -- national buyer blast; only at multi-deal/mo volume.

**2026 dispo note:** FinCEN residential all-cash reporting is in full effect -- verify a buyer's real closing history (county deeds confirm it free) over screenshotted bank statements.

---

## 4. GATOR / CREATIVE FINANCE

### What it is
"Gator lending" (Pace Morby's brand) = short-term, deal-secured capital that plugs cash gaps at the closing table. The gator does NOT buy the house or do a rehab loan; they front a small, fast, precise amount for 1-7 days, repaid at closing plus a flat fee or per-diem. Money wires directly to the title company / closing attorney, never to the investor -- that control is the whole point. Four distinct products (not interchangeable):

| Product | Funds | Amount | Term | Cost |
|---|---|---|---|---|
| **EMD funding** (core gator use) | Earnest-money deposit to win a deal on speed | $2,500-5,000 | 1-14 days | flat $150-500 or ~$25/day |
| **Transactional funding** | 100% of A->B in a double close (end buyer already lined up) | full price, to ~$1M-10M | 1-3 days | ~0.75-2% (min ~$750) |
| **Gap funding** | Only the shortfall a hard-money lender won't cover | the gap | 6-12 mo (patient) | interest + points, sometimes equity split |
| **Double-close funding** | The A-side leg; B->C proceeds repay it | full A-side price | same day | ~1% |

Lender's #1 risk to know: a non-refundable EMD (goes hard after inspection). Gators favor deals with refundable EMD windows and a real end buyer.

### Where gators + deals live
**Paid communities (list, don't scrape members):**
- Gator Method course/community -- PAID ~$2,997-11,000 -- pacemorby.com.
- SubTo -- PAID ~$7,800 -- subto.com -- where most subject-to/seller-finance deals and JV partners circulate.

**FREE places they congregate:**
- BiggerPockets Creative Real Estate Financing Forum (Forum 50) -- biggerpockets.com/forums/50.
- Facebook: "Creative Finance Real Estate Investing Group" (facebook.com/groups/sellerfinancerealestateinvesting) + local REIA creative-finance groups. Free EMD deals actually clear in the several dedicated "gator lending" / EMD-funding FB groups (search "gator lending," "EMD funding," "transactional funding" -- multiple active groups); those are where a deposit gets funded same-day, not the general creative-finance group.
- Local REIAs (in-footprint): Carolinas REIA, Metrolina REIA (Charlotte), Upstate Carolina REIA (Greenville/Spartanburg) -- highest-trust in-person gator meets.
- Skool: many independent (non-Morby) gator/creative-finance groups, some free.
- Direct transactional lenders (free POF, no upfront fee) -- no community needed (see below).

### Creative-finance deal signals to target
**Subject-to (take over the existing low-rate loan):**
- Low-rate existing mortgage (sub-4%, originated 2020-2022) -- the 2026 goldmine; signal = recorded deed-of-trust date + original amount.
- Inherited property with a current loan (owner won't landlord); divorcing owner who can't refi on one income; relocating/thin-equity owner; pre-foreclosure with a reinstatable loan + some equity.

**Seller-finance (owner acts as the bank):**
- Free-and-clear / high-equity older owners (no lien to work around); tired landlords (long tenure, out-of-state, non-owner-occupied, pre-1980, tax delays, multiple units); expired listings; tax-delinquent-but-equity-rich.

Add a `creative_fit` field per lead: `subto` (loan present, low rate, some/neg equity), `seller_finance` (free-and-clear/high equity), `cash_or_wholesale` (deep discount/distressed), `gap_needed` (deal works, short at close).

### FREE tools to verify mortgage / rate / free-and-clear status
- **County Register of Deeds** -- FREE -- recorded deed of trust gives borrower, lender, original loan amount, recording date, terms. No active DoT (only a satisfied/released one) = free-and-clear.
- **MERS ServicerID** -- FREE -- mers-servicerid.org -- current servicer/investor by address/MIN; confirms the loan is live.
- **County assessor / CAMA** -- FREE -- value, mailing (absentee), year built, last-sale price/date; combine to estimate equity + rate band.
- **In-house equity math** -- FREE -- value minus (recorded loan amount amortized) flags "sub-4% loan present" (subto) vs "no loan" (seller finance).
- Paid list tools (PropStream / BatchLeads / PropertyRadar) have native Free-and-Clear / High-Equity / Adjustable-Rate / Tired-Landlord filters -- same public data, faster; their appended phones cross the TCPA line.

### Plugging leads into gator / creative dispo
FIND -> ANALYZE (equity engine) -> TAG creative_fit -> SKIP-TRACE (free public mailing; buy phones compliantly) -> CONTACT (pitch matches the tag) -> CONTRACT (SubTo templates or a creative-finance attorney) -> **FUND** (EMD/gator for the deposit; transactional for a double close via DoubleClose.com / Straightline / Axelrad / Tidal / Levine / Washington Capital -- all FREE POF, no credit check; gap funding for a shortfall) -> **DISPO** (cash-wholesale leads -> assign to cash buyers; subto/seller-finance leads -> BiggerPockets Forum 50, SubTo Owners Club, creative-finance FB groups, local REIAs -- these buyers pay for terms deals). Your deal flow also makes YOU attractive to gators hunting deals to lend on.

**FREE learning:** BiggerPockets Forum 50; "Get Creative with Pace Morby" podcast; Jerry Norton + Pace Creative Finance MASTERCLASS on YouTube + CreativeFinancingHacks.com; Cody Sperber "Clever Investor Show"; Morby's "Wealth Without Cash" book.

---

## 5. LAND WHOLESALING + BUY-BOX

Land is the one asset class where a pure-free, no-skip-trace pipeline works end to end, because owners (and neighbor-buyers) are reachable by MAILING ADDRESS alone from free county GIS -- no phone data, no people-search sites.

### Land lead sources
- **County tax-delinquent list filtered to land-use = vacant/ag/unimproved** -- FREE -- the single best land source; delinquent + vacant + absentee = highest conviction.
- **County GIS by land-use code = vacant** -- FREE -- query where use in {vacant, unimproved, agricultural, timberland} and improvement_value ~ $0; add absentee flag.
- **LandGlide** -- PAID $9.99/mo or $49.99/yr (7-day trial) -- landglide.com -- in-field parcel + owner name; no phone (does not cross PII line).
- **AcreValue** -- FREEMIUM (3 reports/mo free) -- acrevalue.com -- rural/ag; Pro Plus adds mailing address; Pro Premium adds sold-land back to 2014.
- **Regrid** -- FREEMIUM, Pro from $10/mo -- regrid.com -- ~156M parcels, bulk CSV + API; best-value paid buy for a nationwide exportable vacant-land pull.
- **Land auctions / land banks / tax-deed** -- FREE browse -- Bid4Assets (bid4assets.com/county-tax-sales), GovDeals (govdeals.com/en/real-estate-tax-deed-lien-sales) + county land-bank inventory. Check per-county: many Upstate SC and Western NC counties run their own in-house upset-bid tax-sale process rather than listing on Bid4Assets, so confirm each target county's actual venue (NC/SC = per-county, no statewide portal).

### Buy-box attribute checklist + FREE tool to verify each
| Attribute | Screening for | FREE tool |
|---|---|---|
| County / region | In-footprint | County GIS; Regrid |
| Acreage range | e.g. 0.25-5 ac infill vs 5-40 ac rural | County GIS; AcreValue; LandGlide |
| Price / acre ceiling | Buy under $/acre comps | AcreValue sales; Land.com comps |
| Road access | Public frontage or recorded easement (landlocked = kill) | County GIS + Google Earth trace; ROD easement check |
| Utilities | Power/water/sewer vs well+septic | Google Earth satellite/street; county GIS utility layers |
| Perc / septic | Will it perc (rural, no sewer) | USDA Web Soil Survey -- websoilsurvey.nrcs.usda.gov; SoilWeb (UC Davis, free, mobile) as a faster in-field companion -- casoilresource.lawr.ucdavis.edu/gmap |
| Wetlands | Non-buildable wetland | USFWS National Wetlands Inventory Mapper -- fws.gov/program/national-wetlands-inventory/wetlands-mapper |
| Flood zone | A/AE/VE hurts value; X is clean | FEMA NFHL / MSC -- msc.fema.gov |
| Topography / slope | Steep = unbuildable; streams | USGS The National Map -- apps.nationalmap.gov; Google Earth elevation |
| Zoning / use | Buildable use, min lot, setbacks | County GIS zoning + county planning ordinance |
| Shape / frontage | Buildable footprint | County GIS; Land ID / Google Earth measure |

"Buy-box in one map" free: **Google Earth** (access/utilities/topo) and **QGIS** (free open-source desktop GIS -- load county parcels + FEMA + NWI + soil into one workspace; the free LandVision/Land ID substitute). Land ID (id.land) has a view tier ~$7/user/mo (effectively paid).

### Land comping (FREE)
- **AcreValue Sales** -- FREE tier (Pro Premium for full sold DB) -- best for ag/rural acreage.
- **Land.com Comparable Sales** (LandWatch / Lands of America / Land & Farm) -- FREE browse -- national sold land; network.land.com/resources/land-comps.
- **County sold-land records** -- FREE -- ground-truth comp for infill lots (same data appraisers use).
- **Zillow/Realtor land filter** -- FREE browse -- suburban infill only, weak on raw acreage; no scrape.
- Method: comp by $/acre within same county AND acreage band (0.5 ac and 40 ac are not comps), same access/utility profile, arms-length, < 12 mo.

### Land dispo channels
- **Land.com network (Lands of America / LandWatch / Land & Farm)** -- PAID listing, ~6.8M buyers -- #1 rural-land marketplace.
- **Zillow / Realtor / FSBO** -- FREE/low-cost for infill.
- **Facebook land groups + Marketplace** -- FREE -- strong for cheap/infill lots.
- **Neighbor / adjacent-owner mailer** -- FREE, land-specific -- the neighbor is often the best buyer (assemblage/privacy); pull adjacent owners + mailing from county GIS and mail. Fully compliant, no skip-trace.
- **Your builder/cash-buyer list** -- FREE -- line up a few builders FIRST, get their exact box, then source parcels that fit. Build from county sold-land buyer names, active-listing agents, and SoS registered-agent lookups for LLC buyers.

---

## 6. OPEN-SOURCE / FREE TOOLS / DATASETS / APIs

Each with a one-line why + how it plugs in. Compliance flags kept.

### GitHub repos
- **openaddresses/openaddresses** -- FREE, open -- global address + parcel + building-footprint sources; a second free situs layer beside county resolvers (FIND).
- **analyticsariel/propstream_marketing_skip_trace_list** -- FREE code -- a list-stacking pattern (merge/dedup owner->contact) even if you never touch PropStream (ANALYZE).
- **johnbalvin/pyzill** (`pip install pyzill`) -- FREE code -- maintained Zillow scraper for ARV/DOM cross-check; needs rotating proxies (crosses no-evasion line), so occasional manual comps only.
- **census / cenpy** (PyPI) -- FREE -- Python wrappers over Census/ACS for buy-box + neighborhood scoring (ANALYZE).
- **soapboxbuild/overture-mcp** -- FREE, open -- Overture building footprints for sqft sanity + vacant-lot-vs-structure (ANALYZE).
- Reference-only (don't run as-is, PII/evasion): illwill/skiptracer, robdplatt/SkipTracer (people-search PII = over the line -- study which free public sources exist), plus county-scraper patterns (jziggas/maryland_foreclosure_scraper, jeffschuler/cuyahoga-county-foreclosures) to mine parsing logic. pipeworx-io/mcp-regrid = MCP wrapper over the paid Regrid API.

### Free datasets / APIs (highest-value layer)
- **HUD Aggregated USPS Vacancy Data** -- FREE (gov/nonprofit registration) -- huduser.gov/portal/usps/index.html -- authoritative vacancy signal by ZIP/route/county/tract; a scoring layer, not an address list (FIND).
- **US Census / ACS API** -- FREE, instant key -- api.census.gov -- income, owner-occupancy, vacancy, value, age of housing per tract; buy-box + motivation scoring (ANALYZE).
- **FEMA National Flood Hazard Layer** -- FREE, no key -- msc.fema.gov + hazards.fema.gov ArcGIS REST -- flood zone per lat/lng; flag every lead. In our core Western NC + Upstate SC footprint the driver is riverine/flash-flood zones (very live post-Helene), not coastal surge; coastal matters only if we widen to the coast.
- **FCC Area/Census Block API** -- FREE, no key -- geo.fcc.gov/api/census -- lat/lng -> census block/FIPS; the glue that joins parcels to Census.
- **OpenAddresses** -- FREE -- openaddresses.io -- bulk address/parcel points (FIND).
- **Overture Maps** -- FREE -- overturemaps.org -- footprints + places (ANALYZE).
- **USDA Web Soil Survey / SoilWeb (UC Davis) / USFWS NWI / USGS National Map** -- FREE -- perc, wetlands, topo for land buy-box (SoilWeb = the faster mobile field companion to Web Soil Survey).
- **State unclaimed property** -- FREE -- missingmoney.com, NCCash.com, SC Treasurer -- warm opener + name->address confirm + heir cross-reference (decedent's unclaimed funds -> heirs).
- **NC SoS registered-agent** -- FREE -- entity-owner contact for LLC-owned parcels (cracks the "who's behind the LLC landlord" problem); SC SoS captcha-walled.

### Paid APIs / platforms (labeled)
- **Regrid (Landgrid) Parcel API** -- PAID (1-week trial) -- regrid.com/api -- cleanest paid parcel backbone; no PII/TCPA line (parcel/owner only).
- **ATTOM Property Data API** -- PAID (30-day trial; ~$95/mo entry) -- api.developer.attomdata.com -- AVM + sales + comps; owner data only, no phone.
- **PropWire** -- FREE core + $0.10/match skip -- propwire.com -- free comps/list-stacking; cleanest pay-per-match skip (skip returns phone = TCPA scrub).
- **FlipMantis** -- FREE tier -- flipmantis.com -- genuine free driving-for-dollars app (iOS/Android, offline).
- **Realie.ai / BatchData / PropertyReach** -- PAID -- property + skip bundles (return phone/email = TCPA line).

### Automation / agent tools
- **n8n (self-hosted)** -- FREE, unlimited -- n8n.io -- best-value orchestrator; wire scraper output -> ARV calc -> dedup -> dashboard -> mail/email dispatch. This is the missing "act-on-it" layer. (n8n 2.0 added native LangChain, AI nodes, vector/RAG.)
- **Make** -- freemium -- make.com -- cheaper than Zapier at volume.
- **Zapier** -- free 100 tasks/mo -- too small for production; tiny glue only.

---

## 7. WHAT TO ADOPT FOR OUR ENGINE

We already run ~110 county/court/tax/probate/REO scrapers + NC voter-phone + qPublic cards + obituaries + NC SoS agent + doc-OCR + equity/ARV calc. Ranked shortlist of NEW, compliant (free + public, no PII-scrape) sources/tools from this sweep worth wiring or using. PII/TCPA/ToS-crossing items flagged "operator-optional, not for the auto-engine."

### Tier 1 -- wire into the auto-engine now (free, public, net-new, high value)
1. **n8n (self-hosted)** -- the automation backbone your path_to_100 blueprint flagged as missing. Orchestrates scraper -> calc -> dedup -> dashboard -> mail hand-offs. FREE, you control it, fully compliant.
2. **Census / ACS API (via cenpy)** -- free per-tract buy-box + motivation scoring layer; instant key; we don't have a demographic scoring layer today.
3. **FEMA NFHL API + FCC Area/Census Block API** -- free, no-key per-lead flood flag + tract join. In our Western NC + Upstate SC core the flood driver is riverine/flash-flood (still a real value hit, sharply so post-Helene), coastal surge only if we widen; the FCC call is the missing glue to attach Census to every parcel.
4. **HUD Aggregated USPS Vacancy Data** -- register as our entity (free); authoritative vacancy scoring by ZIP/tract to prioritize mail. Net-new vacancy signal beyond our proxies.
5. **State unclaimed property (NCCash.com + SC Treasurer + missingmoney.com)** -- free heir/probate cross-reference and name->address confirm; a warm-opener signal we don't capture. Public, clean.
6. **OpenAddresses / Overture footprints** -- free second situs layer + sqft/vacant-lot sanity; complements our Charleston/OneMap resolvers and cama sqft.
7. **MERS ServicerID** -- free per-address current-servicer lookup to confirm a live loan before a subject-to conversation; strengthens the creative_fit tag. Public, no PII.
8. **USDA Web Soil Survey + USFWS NWI + USGS National Map + FEMA** -- free land buy-box verification layer (perc/wetlands/topo/flood) if we extend into land leads in the rural W-NC counties.

### Tier 2 -- adopt as free operator tools (not necessarily auto-engine)
9. **PropWire** -- free comps + list-stacking, and its $0.10/successful-match skip is the cleanest pay-as-you-go phone source when we do need to call. (Skip = phone -> TCPA scrub; operator-optional for the calling lane.)
10. **FlipMantis** -- genuine free driving-for-dollars app for any field work.
11. **DealCheck / ArvCalc / New Silver** -- free manual ARV second-opinion tools to spot-check the engine's automated valuation.
12. **QGIS** -- free desktop GIS to load our parcel + FEMA + NWI + soil layers into one analyst workspace (free LandVision substitute).
13. **BiggerPockets Forum 50 + local REIAs (Carolinas/Metrolina/Upstate) + creative-finance FB groups** -- free dispo/JV channels for the subto/seller-finance leads our equity engine already tags; also where gators live.
14. **Auction.com / Xome / Hubzu / Servicelink (browse) + USDA resales** -- free cross-check for auction-stage opening bids/sale dates against our county rosters, and a rural REO acquisition lane. Browse-only, no scrape.

### Tier 3 -- paid, consider at scale (labeled)
15. **Regrid Pro (~$10/mo)** -- best-value paid parcel backbone / bulk exportable vacant-land pull if we outgrow free county GIS. No PII line.
16. **PropStream ($99/mo; 50-lead trial)** -- one-shot county enrichment or paid backbone; replaces several free scrapers with filters. (Its skip returns phone = TCPA.)
17. **ATTOM API (~$95/mo)** -- comps/AVM backbone if we ever license at scale. Owner data only, no phone.

### Operator-optional, NOT for the auto-engine (crosses PII/TCPA/ToS)
- **Any bundled skip-trace that returns phone/email** (PropStream, BatchLeads, DealMachine, Realie/BatchData, RedX/Vulcan7): legal to buy, but keep it in a human-operated calling lane behind Federal + Internal DNC + FCC Reassigned-Numbers scrubs (no separate NC/SC state list exists). Never auto-dial from the engine.
- **pyzill / any Zillow-Redfin scraping** requiring rotating proxies: crosses our no-WAF/CAPTCHA-evasion line. Manual browse only.
- **OSINT people-search skip repos (skiptracer, SkipTracer)** and any people-search site (TruePeopleSearch, FastPeopleSearch, Spokeo): ban automation + PII -- reference-only for understanding free public sources, never wired.
- **Auction.com / Zillow / Redfin / SC PublicIndex / NC eCourts Smart Search**: ToS-no-scrape or WAF-walled -- manual reference/operator lane, not scraper targets (consistent with the manual-court-export lane we already run).

### Confirmed walls (don't re-chase)
MLS expireds (no free feed -- agent/partner only); SC Family Court divorce + Rule 610; SC magistrate evictions (seller-side; retry pending); demolition lists; HECM/reverse; VA-REO (near-dead 2026); federal no-login auction feeds (homesales.gov decommissioned, US Marshals/irsauctions 403, GSA login-gated).
