# Path-to-100% — Deep-Dive Rounds (sustained research log)

_Companion to path_to_100.md. Each round appends new research. Round 1 = adversarial verification of every price/claim. Started 2026-07-02 20:49, target +4h._

---

# Deep-Dive Round 1 — Adversarial Price/Claim Verification (2026-07-02)


## Skip-trace vendors

| Vendor / claim | Blueprint says | VERIFIED 2026 | Verdict | Corrected figure | Source URL | ToS / gotcha |
|---|---|---|---|---|---|---|
| BatchData / BatchSkipTracing | $0.07–0.18/rec PAYG, ~$0.02 at Growth, plans from $2,000/mo for 100k; 76% RPC | Growth plan **$2,000/mo = 100k records = $0.02/rec** confirmed on live pricing page; higher tiers drop to $0.0067. PAYG $0.07–0.18 and 76% RPC are NOT on the pricing page (marketing/3rd-party claims only) | ⚠️drifted | Subscription math ✅ ($0.02 @ Growth, $2,000/mo/100k). PAYG range plausible but unverified on-site; 76% RPC is a marketing stat, not published | https://batchdata.io/pricing | Pricing page is **subscription-tier only** — no PAYG rate or match-rate shown. "76% right-party" is unsourced marketing. Skip-trace and property-data are separate priced products. |
| REISkip | $0.15–0.22/match, pay per hit, 85–90% match, no PI license | Live page shows **$0.15/match "introductory"** on both Bulk (50 min) and Volume (1,001 min) tiers; standard rack rate is $0.22 (Bulk) / $0.19 (Volume). Pay-per-returned-result confirmed. Match rate & "no PI license" NOT stated on pricing page | ⚠️drifted | Current live price is **$0.15 flat (intro)**; $0.22 is the non-promo Bulk rate. Range is right but today's real price is the $0.15 floor | https://www.reiskip.com/pricing/ | You pay only for returned matches (not the whole list). **50-match minimum** on Bulk. 85–90% match rate is not published on-site. |
| DataZapp | $0.02–0.03/match, $125 min, 75–85% accuracy | **3¢ PAYG, drops to 2.5¢ ($1k prepay) / 2¢ ($2k prepay)**; **$125 minimum order** for PAYG; phone accuracy **"75%–85%"** stated | ✅match | As claimed | https://www.datazapp.com/skip-tracing-real-estate-marketing/ | Two thresholds: $125 min *order* (PAYG) vs $75 min *balance* to use any service. Prepay ($1k/$2k) waives the minimum. Homepage cites a 62% match-rate example — accuracy ≠ match rate. |
| Tracerfy | $0.02/rec API, no subscription, no minimum | **$0.02/hit (Normal, 1 credit)**, $0.04/hit Advanced; "no subscription, no monthly fee"; misses free; API = same price as web app | ✅match | As claimed | https://www.tracerfy.com/pricing | Pay-per-hit; **misses are free**. $0.02 is the *Normal* tier — "Advanced" is $0.04. Volume (100k+/mo) can go below $0.02. No match rate published. |
| PropStream skip trace | $0.12/result, free on Pro/Elite ($99/mo base) | **12¢/contact on Essentials** add-on; **free on Pro ($199/mo) and Elite ($699/mo)**; base Essentials plan is **$99/mo** | ⚠️drifted | $0.12 ✅ and $99 base ✅, but "free skip trace" is on **Pro ($199) / Elite ($699), NOT the $99 base**. The $99 Essentials tier still pays 12¢ | https://www.propstream.com/pricing | The $99 figure and the "free skip trace" apply to *different* tiers — free tracing requires the $199+ Pro plan, not the $99 base. Annual billing lowers to $81/$165/$583. |
| TLOxp (TransUnion) | ~$1.50 basic / ~$4.50 full; requires licensed PI/attorney | Multiple 2026 sources cite **$1.50/basic search, $4.50/full (relatives & associates)**; officially **quote-based**. Requires credentialing + **permissible-purpose / licensed-investigator gate + site visit** | ⚠️drifted (unverifiable at source) | $1.50/$4.50 is credible 3rd-party 2026 figure but TransUnion does not publish it; a 2015 rate notice listed $2.00/$10.00 transactional. Treat as **quote-only** | https://www.transunion.com/business-needs/investigations-tloxp | **Quote-only, no public price.** Credentialing is strict: DPPA/GLBA permissible purpose, physical site inspection of your premises, monthly minimums historically apply. Not open self-serve. |
| IDI idiCORE | $0.50–2.00/record, FCRA permissible-purpose gate | Third-party sources cite **$0.50–$2.00/record, no monthly minimums**. **Not a CRA / not FCRA consumer reports** — but requires strict application verifying a permissible purpose (GLBA/DPPA, not FCRA) | ⚠️drifted | Price range plausible (quote-based, unpublished). The gate is **GLBA/DPPA permissible-purpose credentialing, NOT FCRA** — idiCORE explicitly is *not* FCRA-regulated | https://www.ididata.com/solutions/idicore/ | **Quote-only.** Key correction: it's *not* an FCRA gate — IDI states its data may **not** be used for FCRA purposes (credit/insurance/employment). Credentialing + use-case vetting still required. |
| Endato / EnformionGO | no minimums, ~$0.05–0.25/match | Live page: **Starter "starting at $0.25/match"** (up to 5k/mo, no minimums/contracts), **Pro "as low as $0.01/match"** (unlimited, custom), **free tier 100 matches/mo** | ⚠️drifted | Published range is **$0.01–$0.25/match** (Pro floor $0.01, Starter ceiling $0.25). "$0.05" low-end is not the published number | https://go.enformion.com/pricing/ | "No minimums, contracts, or hidden fees" confirmed; pay per successful match. Note: endato.com now **redirects to go.enformion.com** (rebrand). Per-endpoint cost varies; check dashboard "Keys" tab. |
| People Data Labs | $0.28/credit monthly, ~$0.20 annual; enterprise ~$2,500/mo | **$0.28/credit on Pro monthly ($98/mo, 350 credits)**; annual drops to **~$0.224 (12k) → $0.20 (30k credits)**; enterprise custom, est. **~$2,500/mo** starting | ✅match | As claimed | https://www.peopledatalabs.com/pricing/person | $0.28 is the *monthly Pro* rate; $0.20 requires a large *annual* commitment (~30k credits). Enterprise ($2,500/mo) is an estimate, not published. Enrichment/contact data — not a real-estate skip-trace tool per se. |
| Spokeo / BeenVerified | ~$20–30/mo, no bulk API | Spokeo consumer plans **$19.95–$24.95/mo** (up to ~$69.95 pro). **BUT Spokeo now HAS a "People Intelligence API" + Spokeo Enterprise** with 300M+ adults, bulk/API data | ❌wrong | Consumer price ~$20–25/mo ✅, but **"no bulk API" is false** — Spokeo operates a production People Intelligence API + Enterprise bulk offering (custom-quoted) | https://docs.spokeo.com/ ; https://checkthat.ai/brands/spokeo/pricing | Material error: Spokeo **does** have a bulk/enterprise API (docs.spokeo.com, sales-quoted). Consumer tier has aggressive auto-renew/billing traps. BeenVerified remains UI-subscription, weak at scale. |
| Melissa Personator | credit-based, ~$0.01–0.05/append historically | **Credit-based**; published credit tiers: $30/10k, $84/30k, $285/100k, $1,395/500k credits → **~$0.003/credit at volume**. Personator consumes variable credits per service (address/email/phone) | ⚠️drifted | Credit model ✅; effective *per-credit* cost is **~$0.003–$0.01**, but a full Personator *append* consumes **multiple credits** per record, so real per-record cost lands roughly in the ~$0.01–0.05 range depending on services invoked | https://tekpon.com/software/melissa-data/pricing/ | Not a flat per-record price — **credits ≠ records**. One Personator call can burn several credits (each of address/email/phone/name = separate credit draw). Budget by mapping your specific append workflow. |

**Corrections that matter:**
- **Spokeo "no bulk API" is flat wrong (❌).** Spokeo runs a production People Intelligence API (docs.spokeo.com) plus a Spokeo Enterprise bulk-data offering. If the blueprint routed around Spokeo for lacking an API, that premise is invalid.
- **PropStream's "free skip trace on $99 base" conflates two tiers.** Free tracing requires **Pro ($199/mo)** or **Elite ($699/mo)** — the $99 Essentials plan still pays **12¢/contact**. Don't budget "$99 + free tracing."
- **IDI idiCORE gate is GLBA/DPPA, NOT FCRA.** idiCORE explicitly is *not* an FCRA consumer report and **may not** be used for credit/insurance/employment. Calling it an "FCRA permissible-purpose gate" is legally backwards.
- **TLOxp and idiCORE are quote-only** — the $1.50/$4.50 and $0.50–$2.00 figures are credible third-party numbers but are **not published by the vendors**; both require heavy credentialing (TLOxp adds a physical **site visit** + historical monthly minimums). Treat as estimates, not contracted rates.
- **REISkip's real current price is $0.15 flat (intro promo)**, not the $0.22 rack rate; the $0.22 only applies to the non-promo Bulk tier and has a **50-match minimum**.
- **BatchData's page is subscription-only** — the $0.07–0.18 PAYG rate and "76% right-party" are marketing/third-party claims not shown on the pricing page; only the **$2,000/mo = 100k = $0.02/rec** tier is vendor-verified.
- **Endato's published floor is $0.01 (Pro), ceiling $0.25 (Starter)** — the blueprint's "$0.05" low-end isn't a real published number. Also note endato.com now redirects to go.enformion.com.
- **Melissa is credits, not records** — one Personator append draws multiple credits, so "$0.01–0.05/append" is only true after you account for how many credit-draws your specific address/email/phone workflow triggers.


## Property / valuation vendors

| Vendor / claim | Blueprint says | VERIFIED 2026 | Verdict | Corrected figure | Source URL | ToS / gotcha |
|---|---|---|---|---|---|---|
| ATTOM | API from $95/mo; Property Navigator $499/yr; bulk quote-only; 7,200 attributes; 30-day trial | API "starts at $95/mo" per third-party writeups (not on ATTOM's own page, which is contact-sales only); Property Navigator Professional = $499/yr; bulk = quote-only; 7,200 discrete attributes confirmed; 30-day trial on ATTOM Cloud accounts confirmed | ⚠️drifted | $95/mo figure is real but NOT published by ATTOM directly (secondary sources); Property Navigator trial is **7 days**, not 30 — the 30-day trial applies to ATTOM Cloud/API, not Navigator | https://www.attomdata.com/solutions/property-navigator/pricing/ ; https://api.developer.attomdata.com/home | ATTOM's own site publishes no API price — "$95/mo" is unconfirmable on-site; Property Navigator is annual-only, 1 seat, 200 reports/mo + 2,000 list exports/mo; overage exports cost extra |
| RentCast | free 50/mo; Foundation $74/mo=1,000; Growth $199/mo=5,000; Scale $449/mo=25,000; overage $0.06/$0.03/$0.015 | Developer free $0=50/mo ($0.20 over); Foundation $74=1,000 ($0.06); Growth $199=5,000 ($0.03); Scale $449=25,000 ($0.015) | ✅match | none | https://www.rentcast.io/api | Exact match on every tier and overage. Note free-tier overage is $0.20/req (blueprint omitted it) |
| Realie.ai | free 25; Tier1 $50=1,250 ($0.05); Tier2 $150=6,000 ($0.03); Tier3 $350=30,000 ($0.01); 100 parcels/request | Free $0=25 ($0.15 over); Tier1 $50=1,250 ($0.05); Tier2 $150=6,000 ($0.03); Tier3 $350=30,000 ($0.01); 100 parcels/request | ✅match | none | https://docs.realie.ai/api-reference/pricing | Exact match. Free-tier overage is $0.15/req (blueprint omitted). Unused requests do NOT roll over |
| HouseCanary | Basic $19/mo=2 reports; Teams $199/mo=40 (~$5/report); $190/yr basic; API six-figure minimums | Basic $19=2 reports; Teams $199=40 reports + 40 AVM PDFs + 50-property monitoring; Basic annual $190/yr; there is ALSO a Pro $79/mo=15 tier the blueprint skipped | ⚠️drifted | Add Pro $79/mo tier; API on the self-serve site is **$0.50/successful call, no stated minimum** — the "six-figure minimums" claim is unsupported on the public pricing page | https://www.housecanary.com/pricing | Self-serve API starts at $0.50/call with no published minimum; six-figure minimums likely refer to legacy/enterprise DataDNA contracts, not the current self-serve page. Per-report overage: Basic $12, Pro $11, Teams $9 |
| Estated (folded into ATTOM) | legacy $179/$449/$1,799 mo; ~$0.25/call test | Estated.com now redirects to "Estated is now part of ATTOM Data"; standalone pricing page 404s; legacy $179/$449/$1,799 tiers no longer published anywhere | ❓unverifiable | Legacy tiers are dead/unpublishable; Estated is fully absorbed into ATTOM — route to ATTOM API pricing instead | https://estated.com/ | Estated no longer sells standalone; old pricing is historical only. Do not quote it as live. Acquisition ~2024 |
| Regrid | API custom several-hundred-thousand/mo; bulk nationwide ~$80k/yr | Self-serve API tiers ~$500–$2,000/mo (Standard/Premium schemas); enterprise licensing kicks in above 10,000 records/mo; bulk nationwide = custom quote only | ❌wrong | API is **$500–$2,000/mo**, not "several hundred thousand/mo" — off by ~100–1000x; bulk nationwide is quote-only (the ~$80k/yr figure is unpublished/unverifiable) | https://regrid.com/api ; https://app.regrid.com/plans | The "several-hundred-thousand/mo" figure is a gross error. 30-day free API sandbox. Bulk nationwide price not public — $80k/yr is a guess, not confirmed |
| CoreLogic/Cotality | no public pricing, median ~$12,000/yr | No public pricing (rebranded CoreLogic→Cotality, 2025); PriceLevel reports a single buyer datapoint at $12,000/yr | ⚠️drifted | "$12,000/yr" is ONE reported contract (small company, 900 calls/yr), not a true median — treat as anecdotal, not representative | https://www.pricelevel.com/vendors/corelogic/pricing | Now branded "Cotality." $12k is a single self-reported buyer, per-call rates range $0.005–$11.50 depending on endpoint. No published rate card |
| Quantarium / Collateral Analytics | AVM custom-quote | Quantarium publishes no pricing; B2B enterprise sales; quoted by volume/config/contract. Collateral Analytics also custom | ✅match | none | https://www.quantarium.com/valuation-models/ ; https://datarade.ai/data-providers/quantarium/profile | Correct — fully quote-only. No public number exists to verify against |
| BatchData property | Growth $1,000/mo=100k ($0.01/rec); Pro $2,500/mo=300k; Scale $5,000/mo=750k | Growth $1,000=100k ($0.01); **Professional** $2,500=300k; Scale $5,000=750k; plus new Enterprise $10,000=3M tier. Domain moved batchdata.com→**batchdata.io** | ⚠️drifted | Record counts/prices match; "Pro" is now labeled "Professional"; add Enterprise $10k=3M tier; note domain is now batchdata.io | https://batchdata.io/pricing | Prices and record caps are accurate. Tier is "Professional" not "Pro." Bulk/enterprise adds SLA + custom terms. Confirm you're on batchdata.io (the .com 301-redirects) |

**Corrections that matter**
- **Regrid API is badly wrong (❌):** blueprint says "several hundred-thousand/mo" — actual self-serve API is **$500–$2,000/mo**. This is a 100–1000x error and the single biggest budgeting risk in the group. Bulk nationwide (~$80k/yr) remains an unverified guess (quote-only).
- **ATTOM trial length is conflated:** the 30-day trial is on **ATTOM Cloud/API**, but **Property Navigator's trial is only 7 days**. Also, ATTOM's own site publishes no API price — the "$95/mo" comes only from secondary sources, so treat it as indicative, not quotable.
- **Estated is dead as a standalone (❓):** estated.com redirects to an ATTOM acquisition notice and the pricing page 404s. Stop quoting the legacy $179/$449/$1,799 tiers as live — route buyers to ATTOM.
- **HouseCanary "six-figure API minimums" is unsupported:** the current self-serve page lists API at **$0.50/successful call with no stated minimum**, and the blueprint also missed the **Pro $79/mo (15 reports)** tier. The minimums claim likely reflects legacy enterprise DataDNA deals, not today's self-serve product.
- **BatchData is on batchdata.io now** (the .com redirects), "Pro" is officially "Professional," and there's a new **Enterprise $10k/mo = 3M records** tier; the three cited tiers are otherwise accurate.
- **CoreLogic's "$12,000/yr median" is a single self-reported datapoint**, not a real median — and the brand is now **Cotality**. Directionally fine for "expect five figures," but don't present $12k as a firm/representative number.
- **Exact matches:** RentCast, Realie, and Quantarium/Collateral Analytics all check out (✅). Minor add: both RentCast and Realie have free-tier overage rates ($0.20 and $0.15/req respectively) the blueprint omitted.


## Deliverability / geocode / identity

| Vendor / claim | Blueprint says | VERIFIED 2026 | Verdict | Corrected figure | Source URL | ToS / gotcha |
|---|---|---|---|---|---|---|
| TrueNCOA (freencoa.com) | $20/file, up to 2M records, incl CASS+DPV+NCOA, PAF required | $20 per file, pay-as-you-go; site states "no file size limitations" (nonprofit tier phrased as "$20 per 2M records/file"); includes CASS & DPV, 18/48-mo moves, vacant + RDI. PAF not surfaced on pricing page but is a USPS NCOALink requirement all providers enforce at signup. | ⚠️drifted | $20/file flat; the "2M records" cap is not a hard published limit (nonprofit framing). PAF still required in practice. | https://truencoa.com/ncoa-pricing-and-feature-comparison/ | Free to process + preview full report; you only pay $20 to download. PAF (Processing Acknowledgement Form) signed at account setup — real, just not on the price page. |
| Smarty (US address verify) | ~$0.001–0.004/lookup; ~$17/mo(1k)→~$485/mo(170k); 100k ~$125/mo; 250 free/mo; rooftop geocode $45/mo(1k), $106/mo(5k); no NCOA | US addr verify starts $17/mo (1k) → $485/mo (170k); tiers 1k/5k/10k/25k/50k/85k/170k. US rooftop geocoding starts $45/mo (1k). No NCOA product. Free trial = 1,000 lookups over 42 days (not a recurring 250/mo). | ⚠️drifted | Ranges + $17/$485 anchors + $45 geocode confirmed. Free tier is a one-time 1,000-lookup/42-day trial, NOT 250/mo recurring. 100k=$125, geocode $106@5k, per-lookup band unconfirmed on live page (JS-rendered). | https://www.smarty.com/pricing ; https://www.smarty.com/pricing/us-rooftop-geocoding | Geocoding billed separately from address verify. No NCOA — confirmed. Subscription (monthly volume), not true per-lookup PAYG. |
| Melissa Direct NCOA | $2.95/1k (48-mo), $2.25/1k (24-mo), $50 min; Personator credits $30/10k, $84/30k, $285/100k | 48-mo $2.95/1k, 24-mo $2.25/1k confirmed. Minimum: $50 (48-mo) / $40 (24-mo). Personator credits: $30/10k, $84/30k, $285/100k all confirmed. | ✅match | Add nuance: min is $50 for 48-mo but $40 for 24-mo. | https://truencoa.com/truencoa-an-alternative-to-melissa-data/ ; https://tekpon.com/software/melissa-data/pricing/ | melissa.com blocks automated fetch (verified via reseller-comparison + Tekpon). Credits are consumed per-feature/component, not 1:1 per record — budget accordingly. |
| AccuZIP NCOA48 | Flat annual unlimited, add-on from ~$396/yr | Confirmed: NCOA48 (48-mo Link) is flat-fee, real-time unlimited record/file processing; add-on "as low as $396/yr" if already on NCOA+ANK. Standalone 18-mo NCOALink unlimited = $795/yr. | ✅match | $396/yr is an add-on-to-existing-subscription price, not standalone. | https://www.accuzip.com/products/modules/48-ncoalink/ | Requires an AccuZIP6 base subscription; $396 assumes you already run their CASS/ANK. Flat = no per-record charge (unlike Melissa/TrueNCOA). |
| Geocodio | 2,500/day free, then $1.00/1k (rose from $0.50 on 2026-02-01), storage allowed | 2,500 lookups/day free; $1.00/1,000 PAYG. Price DID rise from $0.50→$1.00 effective Feb 1, 2026. Forward-geocode storage/reuse allowed (only UK reverse restricted). | ✅match | All three points confirmed. | https://www.geocod.io/pricing ; https://x.com/Geocodio/status/1995803009670857093 | No storage restriction on forward geocoding (rare — most competitors restrict). Unlimited plans also rose (Self-Service Unlimited $1,000→$1,350/mo for new customers). |
| Mapbox | 100k free/mo; temp $0.75/1k storage-prohibited; permanent $5/1k storage-allowed | Temp Geocoding: 100k free/mo, then $0.75/1k (100k–500k), $0.60/1k, $0.45/1k — no permanent storage. Permanent Geocoding: $5.00/1k (→$4.00/1k >500k), storage allowed for own use. | ✅match | Both prices + storage rules confirmed. Permanent has no free tier and requires contacting sales. | https://www.mapbox.com/pricing | Permanent API is sales-gated (not self-serve). Permanent results "own personal/business use only — no distribution or sublicense." |
| HERE | 30k free/mo then ~$0.83/1k; +6% from 2026-04-01 | Base Plan free tier ≈ 30k/mo (some sources cite 250k on Freemium — plan-dependent). Overage commonly ~$0.83–$1.00/1k. Confirmed: +6% increase on Base Plan & pay-per-transaction from Apr 1, 2026 (new/renewed contracts; existing unchanged till renewal). | ⚠️drifted | +6% Apr-2026 confirmed. Free-tier figure is murky: 30k (Base w/ payment info) vs 250k (Freemium) — HERE's own page shows no numbers; ~$0.83/1k is a third-party estimate, not a posted rate. | https://www.here.com/get-started/pricing ; https://coordable.co/provider/here-geocoding-api/ | HERE's official pricing page publishes NO per-unit numbers (CTA-only) — the $0.83/1k is inferred. Treat the exact overage rate as effectively quote/plan-dependent. |
| Google Geocoding | $5/1k (→$4 >100k), 10k free/mo/SKU, storage-prohibited-without-map-display | Geocoding $5.00/1k confirmed. Free = 10k events/mo per Essentials SKU (Geocoding is Essentials). Caching restricted + display-on-non-Google-map prohibited by ToS. The "→$4 >100k" volume break is NOT the current structure. | ⚠️drifted | Base $5/1k + 10k free/SKU + caching/display ToS all correct. Volume discounts start at 20% above 100k monthly (not a flat drop to $4/1k); the old pooled-$200-credit model was replaced by per-SKU free caps (Mar 2025). | https://mapsplatform.google.com/pricing/ ; https://developers.google.com/maps/documentation/geocoding/usage-and-billing | ToS: results may be cached only ~30 days and may NOT be displayed on a non-Google map. Discounts are % tiers, not a clean $4 step. |
| Senzing entity resolution | First 100,000 records FREE, then quote-only | Confirmed: Desktop Eval / QuickStart supports up to 100,000 records free (can request up to 1M free eval). Beyond that = quote-only, priced on current DSR (Data Source Record) count, up-front full-term payment + EULA. AWS Marketplace path offers a separate 250k-record free trial. | ✅match | 100k free + quote-only beyond confirmed. Note AWS Marketplace free trial is larger (250k). | https://senzing.com/pricing/ ; https://senzing.com/try-senzing/ | Production pricing genuinely quote-only — no public per-record rate. Priced on live DSR count in your DB; requires up-front full-term payment and standard EULA. |

**Corrections that matter:**
- **Smarty free tier is NOT 250/mo recurring** — it's a one-time 1,000-lookup, 42-day trial. Anyone budgeting on "250 free lookups every month" is wrong. ($17/1k → $485/170k anchors and the $45 rooftop-geocode start price do hold.)
- **Google's "→$4 >100k" is outdated** — current model is $5/1k with 10k free per SKU and *percentage* volume discounts starting at 20% above 100k monthly, not a flat step to $4. Also the old $200 pooled credit is gone (replaced Mar 2025 by per-SKU free caps).
- **HERE per-unit pricing is effectively unverifiable** — HERE's official page publishes no numbers; the "~$0.83/1k" and even the "30k free" are third-party estimates (Freemium plans elsewhere cite 250k free). The only firmly confirmed fact is the +6% increase from Apr 1, 2026 (new/renewed contracts only). Treat rate as quote/plan-dependent.
- **TrueNCOA "2M records" is not a hard cap** — pricing is $20/file flat with "no file size limitations"; the 2M figure comes from the nonprofit tier's phrasing. PAF is still required (USPS mandate at signup), just not shown on the price page.
- **Melissa min charge splits by term** — $50 minimum for 48-mo but $40 for 24-mo (blueprint only cited $50). Personator credits ($30/10k, $84/30k, $285/100k) confirmed, but credits are consumed per-feature-component, not 1 credit = 1 record.
- **AccuZIP $396/yr is add-on-only** — it assumes you're already an AccuZIP6 CASS/ANK subscriber; standalone unlimited NCOA (18-mo) is $795/yr. Flat annual = no per-record cost, the real differentiator vs Melissa/TrueNCOA.
- **Senzing free tier is larger via AWS** — 100k free on Desktop/QuickStart is right, but the AWS Marketplace trial is 250k; everything past eval is genuinely quote-only (DSR-count based, up-front full-term payment).
- Fully clean (✅) as claimed: **Melissa NCOA per-1k**, **AccuZIP flat-annual**, **Geocodio (incl. the $0.50→$1.00 Feb-1-2026 rise and storage-allowed)**, **Mapbox temp/permanent split + storage rules**, **Senzing 100k-free/quote-only**.


## MLS / comps / rent

| Vendor / claim | Blueprint says | VERIFIED 2026 | Verdict | Corrected figure | Source URL | ToS / gotcha |
|---|---|---|---|---|---|---|
| Canopy MLS | $600 one-time firm init + $250 subscriber init; $225/qtr BIC or $165/qtr subscriber; licensed agent required | Nov 2025 fee schedule: $600 one-time firm (Participant) init, $250 subscriber init; $225/qtr Participant (BIC/head of firm), $165/qtr subscriber | ✅ match | none | [Canopy MLS Fee Schedule PDF](https://apps.carolinarealtors.com/files/MLS%20Fee%20Schedule.pdf) | Must hold active real estate license + join Canopy (Realtor/MLS) to subscribe; billed quarterly, prorated on join date. UI/board membership gate, not an API. |
| MLS Grid | $250/mo feed + $20/mo per license + each board's license fee | Vendor pricing confirmed: $250/mo feed + $20/mo per data license; individual MLS/board license fees are separate and passed through | ✅ match | none | [MLS Grid FAQ](https://www.mlsgrid.com/faq) · [OneKey Data Delivery](https://support.onekeymls.com/hc/en-us/articles/27251536794644-Data-Delivery-Resources) | The "$20/license" is per MLS-market license, not per user; each MLS still charges its own data-access/licensing fee on top, so real cost scales with # of boards. RESO Web API; signed MLS agreement required. |
| CoreLogic Trestle | $100/mo (up to 50 contracts), scaling $110/$125/$150/$175; broker feed $30/mo | RESO Standardized feeds: $100 (≤50), $110 (51–100), $125 (101–500), $150 (501–1,000), $175 (1,001+)/mo. Broker feed $30/mo | ✅ match | none | [Trestle Data Pricing](https://trestle-documentation.corelogic.com/data-pricing.html) | "Contracts" = active MLS-market authorizations, not API keys. Direct/MLO feeds are a separate, higher tier ($125→$250) and MLO license fees vary by market on top. Now branded Cotality. |
| Bridge Interactive (Zillow) | No Bridge service fee; MLS relationship required; solo devs ineligible | Confirmed: Bridge charges no service fee; fees are between you and the data provider/MLS; requires MLS membership, IDX vendor role, or approved partnership; solo/indie devs without an MLS relationship don't qualify | ✅ match | none | [Bridge – Zillow Group Data](https://www.bridgeinteractive.com/developers/zillow-group-data/) · [Zillow MLS Listings](https://www.zillowgroup.com/developers/api/mls-broker-data/mls-listings/) | "Free" only on Bridge's side — the MLS/data provider may still charge. Zillow-owned data requires separate eligibility review (~10+ business days) and its own ToU; approval is discretionary. |
| HUD FMR/SAFMR API | Free Bearer token at huduser.gov/hudapi; SAFMR by ZIP × bedroom; FY2026 live | Free registration → Bearer token at huduser.gov/hudapi/public/register; token shown once; FMR + SAFMR endpoints; FY2026 FMRs published | ✅ match | none | [HUD FMR API docs](https://www.huduser.gov/portal/dataset/fmr-api.html) · [register](https://www.huduser.gov/hudapi/public/register) | Genuinely free/no-cost. SAFMR is keyed by ZIP (returns all bedroom sizes 0–4BR); base FMR endpoint is by county/metro FIPS, not ZIP. Token only displayed once — save it. Rate-limited but no fee. |
| Zillow ZORI | Free CSV at zillow.com/research/data | ZORI CSVs present and free to download on the Research Data page | ✅ match | none | [Zillow Research Data](https://www.zillow.com/research/data/) | Free, but download paths change frequently — Zillow now steers scripted users to the Econ Data API. Data is for informational/non-commercial-ish use under Zillow's terms; attribution expected. Not an official ToS-blessed redistribution license. |
| HelloData.ai | $0.50/record PAYG; UI $250/user/mo | $0.50/record PAYG corroborated; live pricing page no longer lists a public UI/user rate — Standard "Per User Pricing" is now **Chat with Sales**; Portfolio = per-unit + $0.10/API call | ⚠️ drifted | PAYG $0.50/record still stated in third-party listings; UI $250/user/mo is now **quote-only** (not published) | [HelloData Pricing](https://www.hellodata.ai/pricing) · [G2 pricing](https://www.g2.com/products/hellodata-ai/pricing) | The $250/user/mo figure is no longer on the live page (sales-gated), so treat it as stale/unverifiable. Portfolio tier advertises "unlimited API" but still meters $0.10/call. Per-record vs subscription are distinct products — don't blend. |
| Rentometer | Pro $29/mo incl QuickView + 50 reports; higher volume by quote | Pro = $29/mo (monthly) incl QuickView, API access, and 50–500 Pro reports/comp downloads (scales within Pro); annual ≈ $16/mo ($199/yr). Team + custom tiers exist | ⚠️ drifted | Pro is $29/mo **monthly**, but the report allotment is a 50–500 range (not fixed 50); $199/yr if annual. API is included in Pro, not a separate quote-only add-on | [Rentometer Pricing](https://www.rentometer.com/pricing) | "$29/mo incl 50 reports" is the entry point of the Pro band, not the whole story — report count is a slider up to 500. API access is bundled into Pro (contradicts "higher volume by quote" framing). Watch promo pricing (e.g., USA20 20% off) skewing headline rate. |

**Corrections that matter**
- **HelloData UI $250/user/mo is no longer publicly listed** — the Standard/interface tier is now "Chat with Sales." Only the $0.50/record PAYG survives in public sources; treat the $250 as stale. Also note the Portfolio tier still charges $0.10/API call despite "unlimited" language.
- **Rentometer Pro is a 50–500 report band, not a flat 50, and API access is already bundled into the $29/mo Pro plan** — so "higher volume by quote" is misleading; you scale within Pro (up to 500) before needing Team/custom. Annual pricing roughly halves it (~$199/yr).
- **Trestle "contracts" and MLS Grid "licenses" both mean per-MLS-market authorizations, not API keys or users** — cost scales with how many boards you pull, and each MLS layers its own data-license fee on top of Trestle/MLS Grid's platform fee. Trestle Direct/MLO feeds are a separate, pricier tier ($125–$250) than the RESO Standardized tier quoted.
- **Every MLS-comps vendor here (Canopy, MLS Grid, Trestle, Bridge) is gated on an MLS relationship/license, not just money** — Bridge/Trestle "no/low service fee" understates true cost because the MLS charges separately, and Zillow-owned data via Bridge needs a discretionary eligibility review.
- **HUD and ZORI are the only truly free, no-relationship sources** — both verified. Caveats: HUD base FMR endpoint is by county/metro FIPS (only SAFMR is ZIP-keyed), token is shown once; ZORI CSV paths change often (Zillow pushes you to its Econ Data API) and carry Zillow's own terms, not an open redistribution license.


## Court / distress / probate / life-event

| Vendor / claim | Blueprint says | VERIFIED 2026 | Verdict | Corrected figure | Source URL | ToS / gotcha |
|---|---|---|---|---|---|---|
| ATTOM pre-foreclosure API + Property Navigator | "from ~$95/mo; 27M default records; Property Navigator $499/yr" | API entry ~$95/mo but effectively quote-only/enterprise; Property Navigator Professional = **$499/yr** confirmed (annual only, 1 user, 200 reports/mo, 2,000 exports/mo). Couldn't independently confirm the "27M default records" count on the live page. | ⚠️drifted | $499/yr confirmed; API "$95/mo" is a floor, real pricing is custom-quote; 27M figure unverified | https://www.attomdata.com/solutions/property-navigator/pricing/ | API is quote-only/licensed, not self-serve at $95; Navigator has hard report/export caps and is annual-billing only (no monthly). |
| PropStream | "Essentials $99/mo (25k saves), Pro $199/mo (50k), Elite $699/mo (100k)" | Essentials **$99/mo / 25k**, Pro **$199/mo / 50k**, Elite **$699/mo / 100k** — all exact. | ✅match | — | https://www.propstream.com/pricing | Saves DON'T roll over (monthly reset). Skip trace not free on Essentials ($0.12/contact); "free" skip trace requires PropStream Connect add-on ($30/mo). Documents $5 each. |
| PropertyRadar | "Solo $119 (10k, 250 phones/emails), Team $249, Business $599 (50k, 2,500 contacts); has API" | Solo **$119/10k/250**, Team **$249** (but **25k props / 500 contacts**, not stated), Business **$599** but **50k props / 2,500 contacts**. API = **Business only**. | ⚠️drifted | Business = **50k monitored / 2,500 contacts** (blueprint's "50k, 2,500" is actually the Business tier, correct); Team tier specs (25k/500) were omitted | https://www.propertyradar.com/pricing | API gated to Business ($599) only. Contacts/phones are metered monthly allotments, then $0.04–$0.08 each. "Monitored" ≠ pulls; overage billed per-record. |
| All The Leads (probate) | "$249–$1,099/mo per county" | Range **$249–$1,099/mo** per county confirmed by third-party comparison; official page is quote-only ("check your county"). | ✅match | — | https://probatemastery.com/the-top-5-probate-lead-companies-and-comparison-chart/ | Official site publishes NO prices — must quote per county via my.alltheleads.com. Range comes from resellers/comparisons, not ATL's own page. Bundles marketing tools. |
| US Probate Leads | "as low as ~$80/mo per county" | "as cheap as **$80/mo**" confirmed; bulk leads $0.45–$0.65/lead; county subs require 15+ probates/mo. | ✅match | — | https://probatemastery.com/the-top-5-probate-lead-companies-and-comparison-chart/ | $80 is a floor for small counties only. Per-lead model ($0.45–$0.65) or block buys (25/50/100). County must have >15 probates/mo to qualify. |
| The Warren Group (probate/divorce) | "$0.50/record" | **$0.50/record** confirmed; volume discounts; models = one-off/monthly/yearly/usage. | ✅match | — | https://datarade.ai/data-providers/the-warren-group/profile | Per-record, not subscription. Quote-based; $0.50 is list. Volume discounts negotiable. Datarade is the pricing source (not TWG's own page). |
| PACER | "$0.10/page, $3/doc cap, $30/quarter waived; fee increase effective Jan 1 2027" | Currently **$0.10/page, $3.00 cap, $30/qtr waiver** — all correct for 2026. Jan 1 2027: **per-page rises to $0.12** and **waiver rises to $40/qtr** (blueprint mentioned the increase but not the specifics). | ⚠️drifted | Add: 2027 = **$0.12/page + $40/qtr waiver**, a 5-year temporary increase (first change since 2012) | https://pacer.uscourts.gov/announcements/2026/06/26/temporary-fee-increase-effective-jan-1-2027 | The 2027 change is a per-page rate hike ($0.10→$0.12), not just a threshold move. $3 cap applies to docs/most reports but NOT to search results (search billed per page, uncapped). |
| CourtListener / RECAP | "free REST API, rate-limited; RECAP archive permanently free" | REST API still free with an account; **RECAP archive still free**. BUT as of **May 2026** default anonymous/new-token rate dropped hard (reported ~**5 req/min**, was 5,000 req/hr); higher rates now tied to membership. | ⚠️drifted | API free but new-user rate limit slashed May 2026; generous rates now require a (free-to-join) membership; 1,000+ prior-request users grandfathered | https://free.law/2026/05/07/api-included-in-memberships/ | "Free REST API" now heavily rate-limited for new/anonymous users (~5/min per reports). RECAP archive remains permanently free. Bulk/high-volume effectively needs membership. |
| DealMachine | "~$99–$232/mo, unlimited skip-trace" | Starter **$99**, Pro **$149**, Pro Plus **$232/mo**; unlimited skip trace on **all plans**. | ✅match | — | https://www.dealmachine.com/pricing | "Unlimited" skip trace = up to 3 phones + 3 emails per owner, refreshed monthly — not truly uncapped depth. Dialer minutes, AI voicemail, and mail billed separately as usage. |
| REsimpli | "$149 / $299 / $599/mo" | Basic **$149**, Pro **$299**, Enterprise **$599/mo** — exact. (Note: top tier is named "Enterprise," not a 4th "Advanced" tier.) | ✅match | — | https://resimpli.com/pricing/ | Base price excludes usage: calling minutes, SMS, skip tracing, direct mail all metered on top. 30-day free trial. Annual billing discounts base. |

**Corrections that matter:**
- **PACER 2027 is a rate hike, not just a threshold tweak** — per-page goes $0.10 → **$0.12** and the waiver goes $30 → **$40/quarter**, effective Jan 1 2027 for 5 years. The blueprint flagged "an increase" but implied only the $30 threshold; the load-bearing number is the per-page jump.
- **CourtListener's "free REST API" materially degraded May 2026** — new/anonymous default rate limits were cut to roughly **5 requests/minute** (from 5,000/hr), and usable throughput now hinges on a membership. RECAP archive stays permanently free, so half the claim holds, but "free, rate-limited API" now understates the friction for any new integration.
- **ATTOM "$95/mo API" is a floor, effectively quote-only** — the API is licensed/enterprise with custom pricing; only Property Navigator ($499/yr, annual-only, with 200-report/2,000-export monthly caps) is genuinely self-serve. Don't budget the API at $95 flat.
- **PropStream and DealMachine "free/unlimited skip trace" both carry asterisks** — PropStream's free skip trace requires the **$30/mo PropStream Connect** add-on (Essentials pays $0.12/contact otherwise); DealMachine's "unlimited" caps at **3 phones + 3 emails per owner**. Neither is unconditionally free/unlimited.
- **PropertyRadar API is Business-tier ($599) only**, and its Team tier (25k props / 500 contacts) was omitted from the blueprint — the "50k / 2,500 contacts" figures actually describe the Business tier, which is correct but was mislabeled as a general spec.
- **All The Leads and The Warren Group are quote-only on their own sites** — the $249–$1,099 and $0.50/record figures come from third-party comparisons/Datarade, not the vendors' published pages. Treat as directional, confirm by quote.


## Outreach / lien / title / condition

| Vendor / claim | Blueprint says | VERIFIED 2026 | Verdict | Corrected figure | Source URL | ToS / gotcha |
|---|---|---|---|---|---|---|
| DNC/litigator scrub (per-number + list) | TextP2P, RingScrub ~$0.01/number; litigator list ~$130/mo | TextP2P = $0.01/number, $5.00 min charge. RingScrub litigator list = $130/mo (inbound filtering) if you lack Scrub Package A/B/C; DNC.com itself is quote-only (no public price). | ✅match | ~$0.01/number (TextP2P, $5 min); $130/mo litigator list (RingScrub, only if no scrub package) | [textp2p.com/contact-scrubs](https://textp2p.com/contact-scrubs/) · [ringscrub.com/pricing](https://ringscrub.com/pricing.html) | The $130/mo is RingScrub's, not DNC.com's (DNC.com is sales-quote only). RingScrub bundles the litigator list free with paid scrub packages, then $0.001/scrub after 2.4M included; TextP2P has a $5 floor. |
| ProTitleUSA O&E | ~$90 avg, range $55.95–$275; commercial ~$250; bulk discount 20+ | Confirmed avg ~$90, range $55.95–$275. Bulk discount exists but no 20+ threshold published. Commercial O&E page shows no public $250 — "commercial zoning incurs additional fees," price not stated. | ⚠️drifted | $55.95–$275 (avg ~$90) ✅; commercial = quote/surcharge, NOT a public ~$250; bulk = "available," threshold unstated | [protitleusa.com/services/products/oe_report](https://protitleusa.com/services/products/oe_report) | Hidden surcharges: +fee if vesting deed >30 yrs old; tax-cert fees in NY/MA/NJ/PA; +$35 expedite. Two-Owner (foreclosure) search is a separate product ($99.95–$375). |
| US Title Records | ownership $29 / lien check $95 / full preliminary $375 | Property Detail (ownership) $29 ✅; Property Lien Report $95 ✅; Expanded/preliminary title search $375 ✅. Note their page titled "Preliminary Title Report" is a separate $295 SKU. | ✅match | $29 / $95 / $375 all confirmed | [ustitlerecords.com/title-search-cost](https://www.ustitlerecords.com/title-search-cost/) | Per-record à la carte, no subscription. Watch naming: the $375 "Expanded Title Search" ≠ their $295 page literally called "Preliminary Title Report"; $195 full-lien adds owner UCC/BK; name search jumps $75 statewide → $535 nationwide. |
| DataTree (First American) | per-user + per-doc quoted; avg First American D&A spend ~$30,500/yr | Model confirmed per-user + per-doc/à-la-carte or prepaid monthly; no public rate card. Vendr buyer-guide avg for First American D&A ≈ $30,500/yr (max ~$31k). | ✅match | Quote-only; ~$30,500/yr avg (3rd-party benchmark, not vendor-published) | [vendr.com/buyer-guides/first-american-data-analytics](https://www.vendr.com/buyer-guides/first-american-data-analytics) · [datatree.com](https://web.datatree.com/) | The $30,500 is a Vendr negotiation-benchmark, not a First American list price — treat as directional. Pay-as-you-go download option exists for low volume; enterprise/API is contract + per-doc. |
| TitlePoint | per-search quoted; residential title searches $100–$250 | TitlePoint itself publishes no public per-search price (quote/enterprise, B2B for title co's). The $100–$250 is a general market range for residential title searches, not a TitlePoint rate. | ❓unverifiable | TitlePoint = quote-only; $100–$250 is generic market range, not TitlePoint's | [orchard.com/blog/how-much-does-a-title-search-cost](https://orchard.com/blog/posts/how-much-does-a-title-search-cost) | Gotcha: TitlePoint (First American/Old Republic-style back office) is credentialed B2B for title/escrow operators, not a walk-up per-search retail product; the $100–$250 figure is what end title searches cost generally, not what TitlePoint charges you. |
| Google Street View Static API | free 10k/mo, then $7.00/1k (10k–100k), $5.60/1k (100k–500k); image caching ToS | Free 10,000 events/mo ✅. $7.00/1k (0–100k), $5.60/1k (100k–500k), then $4.20 (500k–1M), $2.10 (1M–5M), $0.53 (5M+). SKU 9BD0-A2EE-44C3. | ✅match | 10k free; $7.00 / $5.60 / $4.20 / $2.10 / $0.53 per 1k across tiers | [developers.google.com/maps/billing-and-pricing/pricing](https://developers.google.com/maps/billing-and-pricing/pricing) | ToS: Maps Platform License Restrictions bar caching/storing imagery except limited short-term/tiling exceptions — you generally can't warehouse Street View images. $200/mo legacy credit is gone; free tier is now per-SKU event allowances. |
| Cape Analytics / ZestyAI | enterprise quote-only | Both confirmed: no public pricing; custom enterprise contracts, API/batch. ZestyAI notes ~half of top-50 US P&C carriers. | ✅match | Quote-only (confirmed) | [capeanalytics.com](https://capeanalytics.com/) · [zesty.ai](https://zesty.ai/) | Insurance-underwriting-oriented; access typically gated to carriers/enterprise with volume commitments — not realistically a self-serve buy for a solo investor. |
| EagleView | ~$15–$38 standard, up to ~$87 premium per report; no public API | Pay-as-you-go widely cited ~$15–$38 standard, up to ~$87 premium (all 3rd-party; EagleView publishes NO dollar figures). Now pushing "EagleView One" subscription. No public self-serve API. | ⚠️drifted | Range directionally right but vendor-unpublished; some sources cite standard residential nearer $40–$60. No public API confirmed. | [roofingsoftwareguide.com/guides/eagleview-pricing](https://roofingsoftwareguide.com/guides/eagleview-pricing/) | EagleView's own site shows zero prices; rates vary by market/account and there's upsell pressure into report tiers + the EagleView One subscription (aimed at 15+ reports/mo). Treat $15–$87 as a 3rd-party estimate band, not a rate card. |
| Nearmap | quote-only annual, low-5-figure min | Confirmed quote-only, custom annual; no public rate card. "Low-5-figure minimum" is plausible/consistent with reseller anecdotes but NOT vendor-published. | ⚠️drifted | Quote-only annual ✅; the "low-5-figure min" is unverified (no published minimum) | [nearmap.com/products](https://www.nearmap.com/products) | Annual subscription, seat/area-based; imagery refresh 2–3x/yr in covered metros only (rural gaps). The specific minimum is not confirmable from public sources — present as estimate. |
| Direct mail (loaded) | $0.50–$1.50/piece loaded; EDDM $0.27–$0.52 | Loaded direct-mail all-in commonly $0.30–$3.00/piece by format; postcard campaigns land ~$0.50–$0.80/piece all-in → $0.50–$1.50 is reasonable. EDDM postage alone $0.242–$0.247 (rising to ~$0.254–$0.260 on Jul 12, 2026); all-in EDDM ~$0.50–$0.80. | ⚠️drifted | Loaded $0.50–$1.50 ✅ (within broader $0.30–$3.00); EDDM postage $0.242–$0.26/piece, all-in ~$0.50–$0.80 (not $0.27–$0.52) | [mailpro.org/post/how-much-does-direct-mail-cost](https://www.mailpro.org/post/how-much-does-direct-mail-cost/) · [crst.net/services/eddm](https://crst.net/services/eddm/how-much-does-eddm-cost) | The $0.27–$0.52 EDDM figure conflates postage-only with all-in. Postage ≈ $0.24–$0.26; add printing/production and true all-in EDDM ≈ $0.50–$0.80/piece. USPS rate increase effective Jul 12, 2026. |
| RVM | $0.012–$0.05/drop | Confirmed: Drop.co $0.05→$0.012/drop by volume; MyRinglessVoicemail ~$0.01; LeadsRain ~$0.015; Drop Cowboy from $125/mo or BYOC $0.004/drop. | ✅match | $0.012–$0.05/drop confirmed (goes as low as $0.004 BYOC) | [voicedrop.ai/pricing](https://www.voicedrop.ai/pricing/) · [dropcowboy.com/messaging-pricing](https://www.dropcowboy.com/messaging-pricing) | Add-on carrier/compliance pass-throughs (~$0.0031/msg on Drop Cowboy) sit on top of the per-drop rate; some platforms have monthly platform fees. RVM legality/TCPA exposure varies by state — a real gotcha beyond price. |

**Corrections that matter**
- **The ~$130/mo "litigator list" is RingScrub's, not DNC.com's** — DNC.com (the branded "Litigator Scrub") is entirely sales-quote with no public price. Don't attribute the $130 to DNC.com.
- **ProTitleUSA "commercial ~$250" is not on the page** — commercial is a surcharge/quote, and there are hidden add-ons (>30-yr-old vesting deed, tax certs in NY/MA/NJ/PA, +$35 expedite). Bulk discount exists but the "20+" threshold is not published.
- **TitlePoint's "$100–$250" is a generic market range, not TitlePoint's price** — TitlePoint is credentialed B2B back-office for title/escrow operators, effectively unverifiable/quote-only for an investor; don't budget it as a retail per-search tool.
- **DataTree $30,500/yr is a Vendr benchmark, not a First American list price** — directional only; low-volume users can go pay-as-you-go per-doc instead of a $30k contract.
- **EagleView $15–$38 / $87 are third-party estimates; EagleView publishes no prices** and is steering buyers to the "EagleView One" subscription. Some sources put standard residential closer to $40–$60. No public self-serve API.
- **EDDM $0.27–$0.52 mixes up postage-only vs all-in** — postage is ~$0.24–$0.26/piece (USPS increase Jul 12, 2026), but true loaded EDDM (print + production) is ~$0.50–$0.80/piece.
- **Nearmap "low-5-figure minimum" is unverified** — the quote-only annual model is confirmed, but no published minimum exists; flag as estimate.
- **Google Street View Static caching is ToS-restricted** — you generally cannot store/warehouse the imagery, which matters if the plan was to build a persistent photo library; the pricing tiers themselves (10k free, then $7.00/$5.60/$4.20/$2.10/$0.53 per 1k) are exact matches.


---

# Deep-Dive Round 2 — Per-County Free-Source Matrix (18 counties, 2026-07-02)


### Spartanburg, SC
County seat: Spartanburg. Assessor/GIS platform: **county-hosted Esri ArcGIS** (`maps.spartanburgcounty.org`, full-CAMA FeatureServer) + shared SCDOT layer 42 + qPublic-Schneider card (AppID 857). Register of Deeds = Logan Systems ("The Lookup").

| Layer | Free endpoint / portal (URL or repo const) | Access | heated sqft | beds/baths | sale $ | condition/CDU | owner-mailing | Notes / wall |
|---|---|---|---|---|---|---|---|---|
| (1) Assessor/CAMA bulk | Open-Data CSV `sc_assessor_cama.SC_CAMA["Spartanburg"].csv_url` (`arcgis.com/.../1f190ebd48c1402a918c3bc315431a1b/data`) **and** live FeatureServer `spartanburg_condemned.LAYER` = `maps.spartanburgcounty.org/server/rest/services/GIS/CAMA_Parcels/FeatureServer/0` | open JSON/CSV | ✅ `LivingArea` | ✅ `BedRooms`/`FullBaths`+`HalfBaths` | ✅ `SaleAmount` (live) / `SaleDate` | ✅ `ConditionFactor`+`CDUC`/`BuildingGrade` | ✅ `TaxpayerName`+mailing `StreetAddress/City/State/Zip` | The single best SC bulk layer. This county FeatureServer is CLEAN — use it over SCDOT. |
| (2) qPublic/Schneider CARD | `qpublic_render._CFG["Spartanburg"]` AppID=857 LayerID=16069 card PageID=7149; KeyValue = dashed MAP (`7170204100`→`7-17-02-041.00`) | browser (stealth) — Cloudflare Turnstile + "Agree" gate | ✅ heated/finished sqft | ✅ | ✅ sales grid | ⚠️ grade only | ❌ | Redundant here: the open CSV/FeatureServer already give the same fields without rendering. |
| (3) GIS parcel polygon + situs | SCDOT shared `enrichment_arcgis.SCDOT_BASE` layer **42**; county polygon = CAMA_Parcels FS/0 | open JSON | ✅ (county FS) / ❌ SCDOT | ✅ (county FS) | ⚠️ **SCDOT `SaleAmount` is corrupt** (uninitialized doubles ~$1.07–1.27B; capped by `_MAX_PLAUSIBLE_SALE`) | ✅ (county FS) | ✅ | Situs split on SCDOT (`StreetNumber`+`StreetName`); county FS has full attrs — prefer it. |
| (4) GIS address-point | Not separately wired; situs comes from CAMA_Parcels polygon centroid | open JSON | n/a | n/a | n/a | n/a | n/a | No dedicated address-point layer needed — polygon situs is complete. |
| (5) Register of Deeds index | `rod/logan_render.py` → `search.spartanburgdeeds.com` (Logan "The Lookup", DataTables AJAX) | browser (render, guest session) | ❌ | ❌ | ❌ (index carries no $) | ❌ | grantor/grantee names | Browserless Logan path is reverse-engineered but county index sits in an empty-index/QC state for date-sweeps → name-search render only (`enrichment_spartanburg_rod`, ~25s/owner, capped). |
| (6) ROD document images | Same Logan portal, per-document image view | browser | ❌ | ❌ | ❌ | ❌ | ❌ | Images viewable; loan amount only via OCR of the deed-of-trust PDF (`enrichment_doc_ocr`). |
| (7) Tax bill / delinquent-tax | `spartanburg_delinquent_tax.PDF_URL` (`spartanburgcounty.gov/DocumentCenter/View/11161`) + FLC `spartanburg_flc.PDF_URL` (View/104130); **balances SOLVED via qPayBill** (memory `project_qpaybill_tax`, +408, join by TMS) | open PDF + browser (qPayBill) | ❌ | ❌ | ❌ | ❌ | owner name on list | Only SC county where per-parcel tax-owed $ is reliably captured. |
| (8) Condemned/code/vacant | Condemned FS `maps.spartanburgcounty.org/.../GIS/Condemned_Properties/MapServer` (`spartanburg_condemned.py`); vacant registry `spartanburg_vacant.LAYER` (`services9.arcgis.com/HoRra3ATPLGmyjn6/...`, ~5k) | open JSON | via CAMA join | via CAMA join | — | ✅ condemned flag | ✅ | Both live-wired. Vacant-registry ~5k parcels is a strong distress signal. |

**Biggest free gap here:** Recorded loan/mortgage balance (equity denominator) — the ROD index has no $ and the date-sweep index is in a county-side empty state, so payoff must be OCR'd per-deed.
**Cheapest fix:** Run the existing name-search render (`logan_render`) HOT/WARM-first, feed the deed-of-trust PDF to `enrichment_doc_ocr` for the original loan amount, then amortize.

---

### Anderson, SC
County seat: Anderson. Assessor/GIS platform: **county-hosted Esri ArcGIS** (`propertyviewer.andersoncountysc.org`) + shared SCDOT layer 4; assessor card = ACPASS (login-walled); Register of Deeds = `andersondeeds.com` public-access portal (no repo adapter yet).

| Layer | Free endpoint / portal (URL or repo const) | Access | heated sqft | beds/baths | sale $ | condition/CDU | owner-mailing | Notes / wall |
|---|---|---|---|---|---|---|---|---|
| (1) Assessor/CAMA bulk | `sc_assessor_cama.SC_CAMA["Anderson"].layer_url` = `propertyviewer.andersoncountysc.org/arcgis/rest/services/NewPropertyViewer/MapServer/5` (117,435 parcels, `MRKT_VALUE>0`) + `Parcel_Sales/MapServer/0` | open JSON (self-signed cert → repo uses `CERT_NONE`) | ❌ **no heated-sqft field on ANY Anderson GIS layer** | ❌ | ✅ `SALE_PRICE`/`SAPRIC`, `SALEDATE` epoch-ms, `SATYPE` | ❌ | ✅ owner + `PHYS_ADDR` | `assessor_cards/anderson_sc.py` is intentionally **price-only**. TMS = 10-char zero-padded parcel_id. |
| (2) qPublic/Schneider CARD | ❌ Anderson is NOT on Schneider qPublic | n/a | — | — | — | — | — | Assessor card lives in ACPASS instead (row below). |
| (3) GIS parcel polygon + situs | SCDOT shared layer **4** (auto-detects `PHYS_ADDR`); value alias `MRKT_VALUE`, `SALE_PRICE`, `SALE_YEAR`, `DBOOK/DPAGE` | open JSON | ❌ | ❌ | ✅ (SCDOT value/sale aliases wired) | ❌ | ✅ | `parcel_resolver._SC_KEY_FIELD["Anderson"]=("TMS",)` resolves parcel key from lat/lng. SCDOT sale numerics OK here (unlike Spartanburg). |
| (4) GIS address-point | Situs from parcel polygon (`PHYS_ADDR`); no separate point layer wired | open JSON | n/a | n/a | n/a | n/a | n/a | Polygon situs is clean; no gap. |
| (5) Register of Deeds index | `andersondeeds.com` public-access (TMS / name / street search, images back to ~1980) | browser | ❌ | ❌ | ⚠️ deed shows consideration/stamps but no $ in the index grid | ❌ | grantor/grantee | **No repo adapter** — not Acclaim/Cott/Aumentum/Logan. Net-new build candidate. |
| (6) ROD document images | Same `andersondeeds.com` portal, unofficial image view free | browser | ❌ | ❌ | ❌ | ❌ | ❌ | Loan amount only via OCR of the recorded deed-of-trust image. |
| (7) Tax bill / delinquent-tax | ACPASS tax search `acpass.andersoncountysc.org/p_tax_search.htm`; MIE roster `anderson_master_in_equity.PAGE_URL` (`andersoncountysc.org/departments-a-z/master-in-equity/`) | browser / open PDF | ❌ | ❌ | ❌ | ❌ | owner | Tax-owed $ per parcel not yet captured for Anderson (unlike Spartanburg qPayBill). |
| (8) Condemned/code/vacant | ❌ no free condemned/vacant ArcGIS layer found | — | — | — | — | — | — | Anderson publishes no queryable code-enforcement/vacant feed. |

**Biggest free gap here:** Heated square feet — it exists ONLY inside the ACPASS assessor card, which is login/registration-walled (`real_prop_search.htm` renders a login gate); no Anderson GIS/CAMA layer carries `LivingArea`.
**Cheapest fix:** Derive footprint sqft from the parcel-polygon/building geometry (`enrichment_footprint_sqft`) as a proxy, and pull true beds/year-built opportunistically if an ACPASS guest session is achievable; otherwise accept price-only + footprint.

---

### Pickens, SC
County seat: Pickens. Assessor/GIS platform: **qPublic-Schneider** (AppID 927) for GIS + card; shared SCDOT layer 39; separate `pickensassessor.org`; Register of Deeds = Harris **AcclaimWeb** (`pickensscrod.us`).

| Layer | Free endpoint / portal (URL or repo const) | Access | heated sqft | beds/baths | sale $ | condition/CDU | owner-mailing | Notes / wall |
|---|---|---|---|---|---|---|---|---|
| (1) Assessor/CAMA bulk | ❌ no free bulk CAMA — `sc_assessor_cama` notes Pickens GIS parcel layers are **cadastral only** (no value/sqft table); not in `SC_CAMA` | — | ❌ | ❌ | ❌ | ❌ | ❌ | Bulk value/specs are NOT downloadable; only per-parcel via the qPublic card (row 2). |
| (2) qPublic/Schneider CARD | `qpublic_render._CFG["Pickens"]` AppID=927 LayerID=18058 card PageID=8077, search 8076; KeyValue = **R-account** (e.g. `R0022220`) resolved via address typeahead | browser (stealth) — **Cloudflare Turnstile + "Agree" gate** | ✅ (heated/finished sqft on card) | ✅ | ✅ sales grid | ⚠️ grade | ❌ | Per memory (`project_sc_deed_ocr_yield`): Pickens qPublic CARD exposes heated sqft + full sale-price/book-page history as structured text (live-verified). This is the ONLY structured path to Pickens sqft. |
| (3) GIS parcel polygon + situs | SCDOT shared layer **39** (auto-detects `LOCADD`); value `ACTUALVAL`, sale `SALEP`, `SALEDT` epoch-ms | open JSON | ❌ | ❌ | ✅ (SCDOT `SALEP`/`SALEDT` wired) | ❌ | ✅ | `parcel_resolver` **omits Pickens** — its assessor key is an R-account not carried in SCDOT, so card must resolve via address search, not lat/lng→key. |
| (4) GIS address-point | Situs from SCDOT polygon `LOCADD`; no separate point layer | open JSON | n/a | n/a | n/a | n/a | n/a | Polygon situs sufficient. |
| (5) Register of Deeds index | `rod/acclaim.ACCLAIM_COUNTIES["Pickens"]` = `pickensscrod.us/AcclaimWeb` — search by Record Date, Document Type, **Consideration** (`sc_rod_acclaim.py`) | open (cookies required, no login, no Cloudflare) | ❌ | ❌ | ⚠️ **Consideration searchable** (LowerBound/UpperBound) but GridResults JSON **omits the $** (memory) | ❌ | grantor/grantee | Best-behaved SC ROD of the three — browserless httpx works. |
| (6) ROD document images | Same AcclaimWeb portal — recorded images free-downloadable | open | ❌ | ❌ | ❌ | ❌ | ❌ | Deed-of-trust loan amount via OCR (`enrichment_doc_ocr` / `extract_lien_amounts.py`). |
| (7) Tax bill / delinquent-tax | `pickens_tax_sale.PAGE_URL` (`co.pickens.sc.us/departments/delinquent_tax/`, PDF via Revize 301) + MIE roster `pickens_master_in_equity.PAGE_URL` (`.../master_in_equity/sales_rosters.php`) | open PDF (impersonate) / browser | ❌ | ❌ | ❌ | ❌ | owner on list | Delinquent-tax list + MIE sold-price rosters both wired. Per-parcel tax-owed $ not captured. |
| (8) Condemned/code/vacant | ❌ no free condemned/vacant layer found | — | — | — | — | — | — | Pickens publishes no queryable code-enforcement/vacant feed. |

**Biggest free gap here:** Bulk CAMA (value + heated sqft at scale) — every free Pickens GIS layer is cadastral-only, so the ONLY structured value/sqft/sale source is the qPublic card, which is behind Cloudflare Turnstile and requires per-parcel stealth rendering (~expensive, R-account resolution).
**Cheapest fix:** Grade-gate the qPublic render to HOT/WARM leads only and resolve the R-account via the address typeahead (already built in `qpublic_render`); take value/sale from the free SCDOT layer 39 (`ACTUALVAL`/`SALEP`) as the cheap first pass, reserving the card for sqft on qualified leads.

---
Key repo paths referenced: `src/foreclosure_scraper/enrichment_arcgis.py` (`SCDOT_BASE`, `SC_LAYER`, `FIELD_ALIASES`, `_MAX_PLAUSIBLE_SALE`), `sc_assessor_cama.py` (`SC_CAMA`), `parcel_resolver.py` (`_SC_KEY_FIELD`), `assessor_cards/anderson_sc.py`, `assessor_cards/qpublic_render.py` (`_CFG`), `rod/acclaim.py` (`ACCLAIM_COUNTIES`), `rod/logan_render.py`, `enrichment_spartanburg_rod.py`, and `scrapers/counties_sc/{spartanburg_condemned,spartanburg_vacant,spartanburg_delinquent_tax,spartanburg_flc,pickens_tax_sale,pickens_master_in_equity,anderson_master_in_equity}.py`.


### Oconee, SC
County seat Walhalla. Assessor/GIS platform: **SCDOT shared MapServer** (SC_Parcels layer 37, value-bearing) + **qPublic-Schneider** SPA card (AppID 1030) for sqft.

| Layer | Free endpoint / portal (URL or repo const) | Access | heated sqft | beds/baths | sale $ | condition/CDU | owner-mailing | Notes / wall |
|---|---|---|---|---|---|---|---|---|
| 1. Assessor/CAMA bulk | SCDOT layer 37 (`SCDOT_BASE` + `SC_LAYER["Oconee"]=37`); fields `CURRENT_VA`, `TOTALASMT`, `RESIDENTIA`, `OWNERNAME`, `FullAdd`, `TMS_NUMBER` | ✅ open JSON | ❌ no sqft field on layer | ❌ | ❌ (no SALEP/SALEDT column present) | ❌ | ⚠️partial (`ADDRESS1-3`/`CITY`/`STATE`/`ZIP` = owner-mail, but no ArcGIS owner adapter wired) | Live-verified: `CURRENT_VA>0` on **61,608** parcels — value IS free here. `sc_assessor_cama` calls Oconee "NOT VIABLE for bulk" but that predates finding value on SCDOT; sqft/sale still absent → card needed |
| 2. qPublic/Schneider CARD | `qpublic.schneidercorp.com` AppID=1030 LayerID=21692 PageID=9258 (`qpublic_render.py` Oconee cfg; `_RENDER_COUNTIES`) | ⚠️ browser-render (Cloudflare Turnstile + "Agree"); plain curl **403** (JA3 block) | ✅ (Total Heated SF) | ✅ | ✅ (Sales grid) | ✅ (grade/CDU) | ⚠️partial | Per-parcel render ~30s–3min, hard-capped; keyed by dashed TMS (already dashed in feed). Fixture `oconee_card.html` proves parser fills sqft + arms-length price |
| 3. GIS parcel polygon + situs | SCDOT layer 37; situs = `FullAdd` (single) or `HOUSE_NO`+`STREET_NAM` | ✅ open JSON | — | — | — | — | — | Auto-detects cleanly (not in `SC_SITUS` overrides). `parcel_resolver` keys on `TMS_NUMBER`/`PARCEL_NO` for lat/lng→TMS |
| 4. GIS address-point layer | ❌ none wired; SCDOT parcel centroid (`X`/`Y`) is the only point | ⚠️partial | — | — | — | — | — | No dedicated county address-point FeatureServer found; parcel centroid suffices for resolver |
| 5. Register of Deeds index | Kofile `oconee.sc.publicsearch.us` | ⚠️ browser + free account | ❌ | ❌ | ⚠️ consideration on some deeds | ❌ | grantor/grantee names | Index from 1957. No repo adapter (repo ROD path is Acclaim/Cott only; Oconee is on Kofile publicsearch) |
| 6. ROD document images | `oconee.sc.publicsearch.us` (images 1/1/2002→present) | ⚠️ browser + free account | — | — | scanned deed $ (OCR) | — | — | Image OCR is the free loan-amount path but gated behind login/render; not wired |
| 7. Tax bill / delinquent-tax | qPayBill `oconeesctax.qpaybill.com/Taxes/TaxesDefaultType4.aspx` (`QPAYBILL_COUNTIES["Oconee"]`); + tax-sale PDF (`oconee_tax_sale.py`) + FLC FeatureServer (`Assignment_Availability/FeatureServer` layers 0/1, `oconee_forfeited_land.py`) | ✅ open (portal ASP.NET + FS JSON) | ❌ | ❌ | ❌ | ❌ | owner name on tax-sale list | qPayBill delinquent **balance** joins by dashed TMS (verified live); numeric idents = mfd-home. FLC FS is the "Oconee free CSV/JSON" from memory |
| 8. Condemned/code/vacant | ❌ none found free | ❌ | — | — | — | — | — | No public condemned/vacant registry endpoint located (unlike Spartanburg) |

**Biggest free gap here:** heated sqft — SCDOT layer 37 carries value but no living-area field, so sqft only comes from the per-parcel qPublic card, which is 403-walled to plain HTTP and needs a slow Cloudflare-solving render.
**Cheapest fix:** run the existing `qpublic_render` Oconee adapter on-demand for grade-gated leads (already built + capped); no new endpoint needed.

### Cherokee, SC
County seat Gaffney. Assessor/GIS platform: **SCDOT shared MapServer** (layer 11, **cadastral-only**) + **qPublic-Schneider** server-rendered HTML card (AppID 908 — separate app from the SPA counties).

| Layer | Free endpoint / portal (URL or repo const) | Access | heated sqft | beds/baths | sale $ | condition/CDU | owner-mailing | Notes / wall |
|---|---|---|---|---|---|---|---|---|
| 1. Assessor/CAMA bulk | SCDOT layer 11 (`SC_LAYER["Cherokee"]=11`) | ✅ open JSON but ⚠️ cadastral-only | ❌ | ❌ | ❌ | ❌ | ⚠️partial (`MailingAdd`, `ZipCode` only) | Live-verified: fields are `SHEET1__*` cryptic sub-columns + `Acres` + `MailingAdd` — **no value, no sqft, no sale price**. `owner_mailing` explicitly **skips Cherokee (qPublic-only)**; `parcel_resolver` omits it ("cryptic sheet sub-fields") |
| 2. qPublic/Schneider CARD | `qpublic.schneidercorp.com` AppID=908 LayerID=17379 PageID=7808 (`assessor_cards/cherokee_sc.py`, `_CARD`) | ⚠️ server-rendered HTML — fetchable via **curl_cffi chrome impersonation** (plain httpx 403 = JA3, not real CF); falls back to StealthyFetcher | ✅ (Total Heated SF) | ⚠️partial | ✅ (Sales grid: date/price/deed book/grantor) | ✅ | ❌ | Best-case: NOT a full SPA, so cheaper than Oconee/Union render. Keyed by dashed TMS `NNN-NN-NN-NNN.NNN`; address-only lead → None (ASP.NET viewstate search, no clean GET) |
| 3. GIS parcel polygon + situs | SCDOT layer 11 | ⚠️partial | — | — | — | — | `MailingAdd` (mail, not situs) | **No situs street field** on the layer — layer 11 has mailing addr only, so situs must come from card or elsewhere |
| 4. GIS address-point layer | ❌ none wired | ❌ | — | — | — | — | — | No county address-point FeatureServer located |
| 5. Register of Deeds index | SC Land Records `sclandrecords.com` (Cherokee); repo `cott_recordroom` slug `cherokeesc` **302'd** (not confirmed) | ⚠️ browser | ❌ | ❌ | ⚠️ consideration on some | ❌ | grantor/grantee | Index from 1/3/1995, images from 9/25/2002. Repo's Cott RecordRoom is wired only for Union, not Cherokee |
| 6. ROD document images | `sclandrecords.com` (images 2002→present) | ⚠️ browser | — | — | scanned deed $ (OCR) | — | — | Free viewable but not wired; OCR path unbuilt for Cherokee |
| 7. Tax bill / delinquent-tax | qPayBill `cherokeecountysctax.qpaybill.com` (`QPAYBILL_COUNTIES["Cherokee"]`) + delinquent PDF (`cherokee_delinquent_tax.py`, `cherokeecountysc.gov/delinquent-tax/`) | ✅ open (portal + plain-HTTP .gov PDF) | ❌ | ❌ | ❌ | ❌ | owner name on list | qPayBill needs Cherokee-specific re-dash (`_norm_cherokee_pid`: 13-digit numeric → `NNN-NN-NN-NNN.NNN`) or numeric board parcels never join. PDF list only published ~Oct–Dec |
| 8. Condemned/code/vacant | ❌ none found free | ❌ | — | — | — | — | — | No public endpoint located |

**Biggest free gap here:** everything structured except tax — Cherokee's SCDOT layer is cadastral-only (no value/sqft/sale/situs), so value, sqft, sale price AND situs all funnel through the one qPublic card; there is no bulk fallback.
**Cheapest fix:** the card is server-rendered HTML, so run `cherokee_sc.py` via curl_cffi chrome impersonation (already built, no browser) — cheapest render in the trio; only needs a resolved dashed TMS, which the tax-sale PDF and lis-pendens feed supply.

### Union, SC
County seat Union. Assessor/GIS platform: **SCDOT shared MapServer** (layer 44 — schema-rich but data-sparse) + **qPublic-Schneider** SPA card (AppID 861) + **Cott RecordRoom** ROD.

| Layer | Free endpoint / portal (URL or repo const) | Access | heated sqft | beds/baths | sale $ | condition/CDU | owner-mailing | Notes / wall |
|---|---|---|---|---|---|---|---|---|
| 1. Assessor/CAMA bulk | SCDOT layer 44 (`SC_LAYER["Union"]=44`); fields incl. `SQFT_TOTAL`,`SQFT_BASEM`,`TOT_MARKET`,`STREET_NUM`,`STREET_NAM`,`NAME_1`,`Address_1-3` | ✅ open JSON | ⚠️partial → effectively ❌ | ❌ | ❌ | ❌ | ⚠️partial (`Address_1-3` owner-mail present) | Live-verified: schema **lists** `SQFT_TOTAL` but `SQFT_TOTAL>0` = **1 of 18,745** (all-null/garbage) → no usable sqft. `TOT_MARKET>0` = **4,579 (~24%)** → partial value. This is exactly memory's "sqft column but no data" |
| 2. qPublic/Schneider CARD | `qpublic.schneidercorp.com` AppID=861 LayerID=16112 PageID=7168 (`qpublic_render.py` Union cfg) | ⚠️ browser-render (SPA + Cloudflare); plain curl **403** | ✅ ("Living Area" incl. basement) | ⚠️partial | ⚠️ (memory: sqft yes but **no sales table** on Union card) | ⚠️partial | ⚠️partial | `key:"search"` — resolve by **address search** (no clean parcel GET), the hardest key strategy of the three. Render-class, hard-capped |
| 3. GIS parcel polygon + situs | SCDOT layer 44; situs = `STREET_NUM`+`STREET_NAM` (split) | ✅ open JSON | — | — | — | — | `Address_1` is `C/O` owner-mail (test guards against picking it as situs) | Live: `STREET_NAM` populated on **15,171 (~81%)** → situs IS free here. `parcel_resolver` keys `Map_Number`/`ParcelID` |
| 4. GIS address-point layer | ❌ none wired | ❌ | — | — | — | — | — | Parcel `CentroidX/Y` only; no dedicated address-point FS found |
| 5. Register of Deeds index | Cott RecordRoom `recordroom.cottsystems.com/unionsc` (`COTT_RR_COUNTIES[("SC","Union")]="unionsc"`, `cott_recordroom.py` / `sc_rod_cott.py`) | ✅ browserless — DataTables JSON, guest access (HTTP 200 live) | ❌ | ❌ | ❌ (index has no $) | ❌ | grantor/grantee | Wired + tested: sweeps deeds-of-distribution/probate + liens. **No consideration $ in index** |
| 6. ROD document images | RecordRoom doc images (`unionsc`) | ⚠️ viewable | — | — | scanned deed $ (OCR) | — | — | Images free but OCR loan-amount path not wired for Union |
| 7. Tax bill / delinquent-tax | qPayBill `uniontreasurer.qpaybill.com` (`QPAYBILL_COUNTIES["Union"]`) + `sc_tax_delinquent`/roster | ✅ open (portal ASP.NET) | ❌ | ❌ | ❌ | ❌ | owner name | Delinquent **balance** joins by dashed parcel — verified live joining |
| 8. Condemned/code/vacant | ❌ none found free | ❌ | — | — | — | — | — | No public endpoint located |

**Biggest free gap here:** heated sqft — SCDOT layer 44 dangles `SQFT_TOTAL` in the schema but only 1 parcel is populated, and the Union qPublic card is resolve-by-address-search (no parcel GET) behind a Cloudflare SPA, making sqft the single hardest free field in this county.
**Cheapest fix:** pull partial value + situs free from SCDOT layer 44 (`TOT_MARKET`/`STREET_NAM`, ~24%/~81% coverage) to cut card demand, and reserve the address-search `qpublic_render` Union render only for high-grade leads that still lack sqft.

Repo memory correction worth noting: the "Oconee free CSV" is the **FLC/forfeited-land FeatureServer JSON** (`Assignment_Availability/FeatureServer`), not a CAMA extract; Oconee CAMA **value** is actually free from SCDOT layer 37 (`CURRENT_VA`, 61,608 parcels), which post-dates the `sc_assessor_cama` "NOT VIABLE" note.

Sources: [Oconee ROD publicsearch](https://oconee.sc.publicsearch.us/), [Oconee ROD dept page](https://oconeesc.com/departments/register-of-deeds), [SC Land Records (Cherokee ROD)](https://www.sclandrecords.com/), [Cherokee ROD dept page](https://cherokeecountysc.gov/register-of-deeds/)


### Laurens, SC
County seat Laurens; assessor/GIS = SCDOT shared statewide layer (SC_LAYER=30) + county-hosted Laurens ArcGIS ("Pebble" — `laurenscountygis.org/arcgis`). No CAMA building layer on GIS; heated sqft is qPublic-only.

| Layer | Free endpoint / portal (URL or repo const) | Access | heated sqft | beds/baths | sale $ | condition/CDU | owner-mailing | Notes / wall |
|---|---|---|---|---|---|---|---|---|
| (1) Assessor/CAMA bulk layer | ❌ none — SCDOT `SC_LAYER["Laurens"]=30` + Pebble parcel layer carry parcel attrs only | open JSON | ❌ | ❌ | ✅ | ❌ | ⚠️ | No building/CAMA table published bulk; SC has no bulk Condition anywhere (per `enrichment_cama_condition.py`). SCDOT gives value/deed only. |
| (2) qPublic/Schneider parcel CARD | ⚠️ Laurens qPublic per-parcel card (Schneider) — no bulk API | browser / per-parcel | ✅ | ✅ | ✅ | ⚠️(card only) | ✅ | The ONLY free path to heated sqft + beds/baths here; one parcel at a time, not batched. Repo `assessor_cards/laurens_sc.py` deliberately uses ArcGIS instead and stays price-only. |
| (3) GIS parcel polygon + situs | `laurenscountygis.org/arcgis/.../Pebble/TaxParcel/MapServer/5` (situs `Property_A`/`Property_Address`); `.../Pebble/PropertyParcel/MapServer/5` = card const | open JSON | ❌ | ❌ | ✅ (`Sale_Price`,`Deed_Book/Page`) | ❌ | ✅ (`Owner`,`Mailing_Address`,`Mailing_City_State_ZIP`) | Live-verified: parcel layer fields = TMS/Owner/Mailing/Sale_Price/Sale_Date/Deed_Book/Deed_Page/Property_Address. Repo situs override `SC_SITUS["Laurens"]="Property_A"`. |
| (4) GIS address-point layer | `Pebble/PropertyParcel/MapServer/0` = `AddressPoint` | open JSON | ❌ | ❌ | ❌ | ❌ | ❌ | Live-verified layer 0 exists (situs point geocode); no attributes beyond address. |
| (5) Register of Deeds index | Logan "The Lookup" — `search.laurensdeeds.com` (NameSearch.php) | browser / name-required | ❌ | ❌ | ⚠️ (deed type only) | ❌ | ❌ | Older Logan = NAME-REQUIRED, no name-less instrument-type sweep (`rod/logan.py` note). SC foreclosure is judicial → ROD holds only POST-sale/probate/tax deeds. Not yet in `LOGAN_COUNTIES`. |
| (6) ROD document images | Logan image order via same host | browser, pay-per-image | ❌ | ❌ | ❌ | ❌ | ❌ | Index free; scanned images pay-walled. Repo policy: never order images. |
| (7) Tax bill / delinquent-tax portal | `laurenstreasurer.qpaybill.com/Taxes/TaxesDefaultType4.aspx` — `QPAYBILL_COUNTIES[("SC","Laurens")]` | open ASP.NET form (no login) | ❌ | ❌ | ❌ | ❌ | ✅ (name) | Live-verified 200. Joins by exact dashed TMS = board `parcel_id`; delinquent balance = sum of Unpaid rows. Low Laurens yield (mostly non-tax leads) but exact-match, no false positives. |
| (8) Condemned/code/vacant layer | ❌ none free published | — | ❌ | ❌ | ❌ | ❌ | ❌ | No county code-enforcement / vacant-registry feed found (matches statewide SC finding). |

**Biggest free gap here:** heated sqft + beds/baths — SC publishes no bulk CAMA layer, so square footage exists only on the per-parcel qPublic card (can't be batched), while GIS is price/owner-only.
**Cheapest fix:** add a Laurens qPublic-card adapter under `assessor_cards/` (mirror the Pickens/Greenville pattern) to pull heated sqft + beds/baths per-parcel for the handful of Laurens leads, keeping the existing ArcGIS card for the price side.

### Buncombe, NC
County seat Asheville; assessor/GIS = county-run ArcGIS (`gis.buncombecounty.org`) + hosted CAMA FeatureServer + Spatialest record card. Richest NC county — the one NC county with a **bulk CAMA Condition column**.

| Layer | Free endpoint / portal (URL or repo const) | Access | heated sqft | beds/baths | sale $ | condition/CDU | owner-mailing | Notes / wall |
|---|---|---|---|---|---|---|---|---|
| (1) Assessor/CAMA bulk layer | `services6.arcgis.com/VLA0ImJ33zhtGEaP/.../Real Estate Appraisal Residential Building 2024/FeatureServer/0` — `CAMA_SOURCES[("NC","Buncombe")]` | open JSON, no render | ✅ (`SqFeet`) | ✅ (`Bedroom`,`FullBath`,`HalfBath`) | ❌ (no sale on this table) | ✅ (`Condition` N/G/R/F/P/U + `Grade`) | ❌ | Live-verified all fields present. PIN-join (pad to 15). This is the CDU/condition column that makes Buncombe the richest NC county. |
| (2) qPublic/Schneider parcel CARD | ❌ N/A — Buncombe uses **Spatialest** record card, not qPublic | render-walled | ✅ | ✅ | ✅ | ⚠️ | ❌ | `prc-buncombe.spatialest.com/api/v1/recordcard/{PIN}` returns 403 "Direct API access not permitted" + Laravel 419 CSRF to httpx → repo uses StealthyFetcher SPA render (`assessor_cards/buncombe_nc.py`). Gives `TotalFinishedArea`+specs+transfer history but is the slow path; prefer layer (1)+(3). |
| (3) GIS parcel polygon + situs | `gis.buncombecounty.org/.../property_bc_dis/MapServer/1` (situs `Address`); PIN-resolve layer `bcmap_vt/MapServer/0` (`pinnum`,`propcard`) | open JSON | ❌ | ❌ | ⚠️ | ⚠️ | ✅ | `NC_GIS["Buncombe"]` addr_field `Address`; owner-mailing layer = `property_bc_dis/MapServer/1` in `enrichment_owner_mailing.py`. Value fields (TotalMarketValue/AppraisedValue) present. Live-verified layers Property(1)+Centerline(12). |
| (4) GIS address-point layer | Buncombe hosted addresses org `services.arcgis.com/aJ16ENn1AaqdFlqx` (200) + Street Centerline (`property_bc_dis/12`) | open JSON | ❌ | ❌ | ❌ | ❌ | ❌ | Situs point/centerline geocode; PIN resolution already handled via `bcmap_vt/0`. |
| (5) Register of Deeds index | `registerofdeeds.buncombenc.gov/External/LandRecords/protected/v4` — Aumentum/Cott eSearch v4, `AUMENTUM_COUNTIES[("NC","Buncombe")]` | open (no login/CAPTCHA) | ❌ | ❌ | ⚠️ (deed type/book-page) | ❌ | ⚠️ (grantor/grantee names) | Live 302→app. Free name/date index; grid Type column renders full words (`rod/aumentum.py`). Lien EXISTENCE only. |
| (6) ROD document images | Same Aumentum host, image viewer | browser, free-view/scanned | ⚠️ | ❌ | ❌ | ❌ | ❌ | NC recorded deed-of-trust PDFs are free-downloadable (per memory `project_rod_document_images`); OCR for loan amount. Index carries no $. |
| (7) Tax bill / delinquent-tax portal | `tax.buncombecounty.org` (bill search / property record) | browser (301→portal) | ❌ | ❌ | ❌ | ❌ | ✅ | Public tax-bill lookup; `enrichment_tax_owed` has no bulk-balance API for Buncombe (taxes-owed remains a gap per `project_enrichment_pipeline_facts`). |
| (8) Condemned/code/vacant layer | ⚠️ Asheville code-enforcement (city) — built per `project_gap_analysis_2026-07-01`; countywide vacant registry ❌ | open/scrape | ❌ | ❌ | ❌ | ❌ | ❌ | City of Asheville code-enf covered; no county-wide vacant/condemned feed. |

**Biggest free gap here:** owner-occupancy / delinquent-tax BALANCE — the CAMA + GIS + ROD stack is unusually complete, but no free bulk API returns the actual dollars-owed on the tax bill (only per-parcel browser lookup).
**Cheapest fix:** none needed for structure/condition (layer 1 is best-in-footprint); for tax balance, add a per-parcel `tax.buncombecounty.org` bill-search parse for the small lead set, or accept the existing owner-mailing absentee flag as the occupancy proxy.

### Gaston, NC
County seat Gastonia; assessor/GIS = direct county ArcGIS (`cogserver.gastonianc.gov`) + Spatialest card (plain httpx) + DevNet Wedge tax site. Unusually self-contained: one parcel layer carries situs+sqft+sale+value+owner.

| Layer | Free endpoint / portal (URL or repo const) | Access | heated sqft | beds/baths | sale $ | condition/CDU | owner-mailing | Notes / wall |
|---|---|---|---|---|---|---|---|---|
| (1) Assessor/CAMA bulk layer | `cogserver.gastonianc.gov/serverweb/rest/services/Parcels/GastonCountyParcels/MapServer/0` — `NC_GIS["Gaston"]` | open JSON | ⚠️ (`SQFT`, often 0 on vacant/exempt) | ❌ | ✅ (`SALESAMT`,`SALEDATE`,`DEED_BOOK/PAGE`,`DEEDTYPE`) | ❌ | ✅ (`CURR_ADDR1/2`,`PHYSSTRADD`) | Live-verified 51 fields incl `TOTVAL`. One layer does situs+sqft+sale+value+owner. `SQFT` unreliable (sample row = 0) → repo pairs with Spatialest for authoritative finished area. |
| (2) qPublic/Schneider parcel CARD | ❌ N/A — Gaston uses **Spatialest** card, no render needed | open JSON (CSRF-primed) | ✅ (`AREA_GROSS`=heated) | ✅ (`XBEDRM`,`XBATHS`,`XHBATHS`) | ⚠️ (card omits sales) | ❌ | ❌ | `property.spatialest.com/nc/gaston/api/v1/recordcard/{PID}` — plain httpx, CSRF token from SPA root (`assessor_cards/gaston_nc.py`). Best heated-sqft + specs source here. |
| (3) GIS parcel polygon + situs | Same `GastonCountyParcels/MapServer/0` (situs `PHYSSTRADD`) | open JSON | see (1) | ❌ | ✅ | ❌ | ✅ | Live sample: `PHYSSTRADD='1516 N WELDON ST'`. Owner-mailing layer in `enrichment_owner_mailing.py` = this same MapServer/0. |
| (4) GIS address-point layer | `cogserver.gastonianc.gov/serverweb/rest/services/MAD/GastoniaAddressPoints` (+ `MAD/CityRes_AdrSrch`) | open JSON | ❌ | ❌ | ❌ | ❌ | ❌ | Live-verified MAD folder = Master Address Data address points; situs geocode fallback. |
| (5) Register of Deeds index | `deeds.gastongov.com/external/LandRecords/protected/v4` — Aumentum eSearch v4, `AUMENTUM_COUNTIES[("NC","Gaston")]`; also free name-index at `gastonnc.courthousecomputersystems.com` (`enrichment_gaston_rod.py`) | open (no login/CAPTCHA) | ❌ | ❌ | ⚠️ (deed type/book-page) | ❌ | ⚠️ (grantor/grantee) | Two free ROD paths. CCHS path needs 3-step session seed (GET / → GET LRIndex → POST ExecuteSearch); gated `FORECLOSURE_GASTON_ROD=1`. Gaston Type codes are terse (per `rod/aumentum.py`). Lien existence only. |
| (6) ROD document images | Aumentum/CCHS image viewer | browser, free-view scanned | ⚠️ | ❌ | ❌ | ❌ | ❌ | NC deed-of-trust PDFs free-downloadable (OCR for loan amount, `project_rod_document_images`); index has no $. |
| (7) Tax bill / delinquent-tax portal | `gastonnc.devnetwedge.com/parcel/view/{PID}/{YEAR}` — `_DEVNET` in `assessor_cards/gaston_nc.py` | open HTML | ⚠️ (Base Living Area fallback) | ❌ | ✅ (Transfer History table) | ❌ | ⚠️ | Live 200. DevNet Wedge = the sales-history + tax-bill source the Spatialest card lacks; parsed by `_parse_devnet_sales`. Delinquent-balance column is on the tax-bill tab (per-parcel). |
| (8) Condemned/code/vacant layer | ❌ none free published (Gaston `Planning`/`PubSafety` ArcGIS folders exist but no vacant/condemned feed confirmed) | — | ❌ | ❌ | ❌ | ❌ | ❌ | `cogserver` has Planning + PubSafety folders; no verified condemned/vacant layer. Not chased. |

**Biggest free gap here:** appraiser CONDITION/CDU — Gaston publishes sqft, sale, value, and specs freely, but no bulk (or even card) Condition rating like Buncombe's, so structural distress must come from the Vision photo classifier instead.
**Cheapest fix:** none for data completeness (Gaston is the most self-contained of the three via GIS + Spatialest + DevNet); to firm up `SQFT`, always prefer the Spatialest `AREA_GROSS` over the flaky parcel-layer `SQFT`, which the card adapter already does.

---
Repo files grounding this: `assessor_cards/{laurens_sc,buncombe_nc,gaston_nc}.py`, `enrichment_arcgis.py` (SC_LAYER/SC_SITUS/NC_GIS), `enrichment_owner_mailing.py`, `enrichment_cama_condition.py` (`CAMA_SOURCES`), `enrichment_qpaybill_tax.py` (`QPAYBILL_COUNTIES`), `enrichment_gaston_rod.py`, `rod/{aumentum,logan}.py`. All portal endpoints live-verified 2026-07-02.


### Henderson, NC
County seat: Hendersonville. Assessor/GIS platform: **ArcGIS Hosted (county-run `gisweb.hendersoncountync.gov`)** — a full CAMA-joined parcel FeatureServer; assessor card via Spatialest Laravel API; ROD via CCHS classic-ASP.

| Layer | Free endpoint / portal (URL or repo const) | Access | heated sqft | beds/baths | sale $ | condition/CDU | owner-mailing | Notes / wall |
|---|---|---|---|---|---|---|---|---|
| 1. Assessor/CAMA bulk layer | `gisweb.hendersoncountync.gov/arcgis/rest/services/Parcels/FeatureServer/0` (repo `NC_GIS["Henderson"]`) | ✅ open ArcGIS JSON | ✅ `HEATED_AREA` | ❌ no beds/baths on layer | ✅ `PKG_SALE_PRICE`+`PKG_SALE_DATE`+`DEED_BOOK/PAGE` | ❌ no CDU/condition | ✅ `PROPERTY_OWNER`+`OWNER_MAIL_1..ZIP` | 91-field CAMA layer, live-verified. Repo **under-uses it** — only maps `addr_field=LOCATION_ADDR`; sqft/value/sale/owner all present and should be wired. Bonus: `DEED_URL`/`PLAT_URL` deep-links, `Centroid_Lat/Long`. |
| 2. qPublic/Schneider parcel CARD | ❌ n/a — Henderson uses Spatialest, not qPublic. Card = `property.spatialest.com/nc/henderson/api/v1/recordcard/{REID}` (repo `assessor_cards/henderson_nc.py`) | ⚠️ browser-ish (plain httpx once Laravel CSRF primed) | ✅ `HEATED_AREA` | ⚠️ baths only (`BATH_FULL/HALF`); no beds | ✅ full `SALE_PRICE`/`DEED_DATE`/`BOOK`/`PAGE`/`STAMPS` history | ❌ | ⚠️ owner name in sales rows | Needs 419-avoiding CSRF prime; REID≠PIN, resolved via `api/v2/search`. Redundant with the FeatureServer for most fields. |
| 3. GIS parcel polygon + situs | Same FeatureServer/0 (`LOCATION_ADDR` + `PHYADDR_STR_*` split fields) | ✅ open JSON | — | — | — | — | ✅ | Situs both as full `LOCATION_ADDR` and component `PHYADDR_STR_NUM/DIR/STR/TYPE`. Polygon geometry → centroid for map pins. |
| 4. GIS address-point layer | Not needed (situs on parcel layer). County E911 address points exist under `gisweb.hendersoncountync.gov` but parcel layer already resolves address | ✅ open (parcel layer) | — | — | — | — | — | No separate point layer required; situs auto-resolves. |
| 5. Register of Deeds index | CCHS `us4.courthousecomputersystems.com/hendersonncnw/` (repo `rod/cchs.py` → `("NC","Henderson"):("us4","HendersonNCNW","hendersonnc")`) | ⚠️ browser flow (classic-ASP `SearchService.asp`, free, plain httpx) | ❌ | ❌ | ⚠️ excise/`mo` (money) per instrument | ❌ | ✅ grantor/grantee | Session-bootstrap → search by instrument type (FCL/LIS-P/trustee deeds). Index only, no $ price (excise only). |
| 6. ROD document images | CCHS `application.asp?cmd=image_link&…&tif2pdf=true` — surfaced directly in FeatureServer's `DEED_URL` field | ✅ open (deep-linked PDF) | — | — | — | — | — | Deed image PDFs are FREE (matches memory `project_rod_document_images`); OCR for loan amount. `DEED_URL` gives a ready book/page image link per parcel. |
| 7. Tax bill / delinquent-tax portal | Foreclosure sales: `hendersoncountync.gov/tax/page/tax-foreclosure-sales` (repo `henderson_tax.py`). Delinquent roll: **NC PTS Cloud** `bcpwa.ncptscloud.com` X-Tenant `Henderson` (repo `nc_ptscloud_delinquent_tax.py`) | ✅ open (HTML table + JSON blob API) | ❌ | ❌ | ⚠️ opening bid on FCL sales | ❌ | ⚠️ owner on rolls | Henderson is a **live valid tenant** on bcpwa; delinquent CSV auto-lights when county posts a blob. Amount-owed IS captured here (rare — most counties don't expose $). |
| 8. Condemned/code/vacant layer | ❌ none free-verified | ❌ | — | — | — | — | — | No public condemned/vacant registry or code-enforcement feed found for Henderson (matches the confirmed NC-wide vacancy/code wall in memory). |

**Biggest free gap here:** beds/baths — the CAMA FeatureServer omits room counts and the Spatialest card only gives baths, so bedroom count never resolves free.
**Cheapest fix:** wire the already-open Henderson FeatureServer's `HEATED_AREA`/`TOTAL_PROP_VALUE`/`PKG_SALE_*`/`PROPERTY_OWNER` into `_apply_attrs` (they're fetched but unmapped today); accept baths-only from the Spatialest card and leave beds null.

---

### Rutherford, NC
County seat: Rutherfordton. Assessor/GIS platform: **ArcGIS (county-run `gis.rutherfordcountync.gov`, VTS/NCPTS-backed)**; assessor card + parcel resolve via NCPTS Cloud `lrcpwa.ncptscloud.com`; ROD via Cott Systems.

| Layer | Free endpoint / portal (URL or repo const) | Access | heated sqft | beds/baths | sale $ | condition/CDU | owner-mailing | Notes / wall |
|---|---|---|---|---|---|---|---|---|
| 1. Assessor/CAMA bulk layer | **NET-NEW:** `gis.rutherfordcountync.gov/server/rest/services/MapMetricsServiceRutherford/MapServer/7` (`PS_VIEW`) | ✅ open ArcGIS JSON, live-verified | ✅ `Heated_Area` | ❌ no beds/baths | ✅ `Package_Sale_Price/Date`+`Deed_Book/Page`+`Revenue_Stamp` | ❌ no CDU | ✅ `Property_Owner`+`Owner_Mailing_Address_1..Zip` (out-of-state = absentee) | **Refutes repo TODO.** Repo points at layer 6 (geometry+MBL/PIN/REID only, `addr_field=None`); layer 7 is a full CAMA polygon layer that closes the whole Rutherford situs+value+sqft+owner gap in one endpoint. Address-LIKE confirmed working. |
| 2. qPublic/Schneider parcel CARD | ❌ n/a — no qPublic. Card = `lrcpwa.ncptscloud.com/api/getParcelDetails?ParcelId=` (repo `assessor_cards/rutherford_nc.py`, header `X-Tenant: Rutherford`) | ✅ open JSON (X-Tenant required; bare call 500s) | ✅ `heatedArea` | ✅ `bedrooms`+`bathFull/bathHalf` | ✅ `packageSalePrice`+full `deeds[]` history | ❌ | ✅ mailing via lrcpwa parcel enricher | This card is the ONLY free source that gives **beds** for Rutherford. Key = internal `ParcelId` (small int), resolved via `SimpleParcelSearch`. |
| 3. GIS parcel polygon + situs | `MapServer/7` (PS_VIEW, situs) or `MapServer/6` (Parcel Polygons, geometry+PIN only per repo `NC_GIS["Rutherford"]`) | ✅ open JSON | — | — | — | — | ✅ (layer 7) | Repo uses layer 6 (no situs). Switch situs/geometry source to layer 7. |
| 4. GIS address-point layer | `MapServer/0` (`Structures`, `FullAddress`+`TAXPIN`+`MBL`+`Lat/Long`) | ✅ open JSON | ❌ | ❌ | ❌ | ❌ | ❌ | E911 structure points; useful to reverse-resolve address↔PIN and get precise lat/long. Also `MapServer/3` `SALES_FINAL` (point) has `PHYSICAL_ADDR`+`YEAR_BUILT`+`BLDG_SIZE`+`PRICE`+`SALE_DATE`. |
| 5. Register of Deeds index | Cott `cotthosting.com/NCRUTHERFORDEXTERNAL/LandRecords/protected/v4` (repo `rod/cott.py`) | ⚠️ browser flow (ASP.NET viewstate form, free) | ❌ | ❌ | ⚠️ excise/consideration per doc | ❌ | ✅ grantor/grantee | Name-search over recorded instruments (FCL/lis-pendens/substitute-trustee). Index only. |
| 6. ROD document images | Cott RecordRoom (`cott_recordroom.py`) / Cott v4 image viewer | ⚠️ browser | — | — | — | — | — | Recorded deed/DoT PDFs downloadable free via Cott viewer; OCR for loan amount. |
| 7. Tax bill / delinquent-tax portal | Foreclosure sales: `rutherfordcountync.gov/departments/revenue_department_tax_administrator/foreclosure_sale_dates.php` (repo `rutherford_tax.py`). Delinquent: bcpwa X-Tenant `Rutherford` (repo `nc_ptscloud_delinquent_tax.py`) | ✅ open (HTML + JSON API) | ❌ | ❌ | ⚠️ current/upset bid on FCL | ❌ | ⚠️ owner | Rutherford is a **valid bcpwa tenant standing by** — no delinquent export blob posted yet, auto-lights when county publishes. |
| 8. Condemned/code/vacant layer | ❌ none free-verified | ❌ | — | — | — | — | — | No public condemned/vacant/code feed found. |

**Biggest free gap here:** condition/CDU — no free source (GIS layers, lrcpwa card, or ROD) exposes a condition/CDU grade for Rutherford, so as-is-vs-renovated can't be inferred without a photo.
**Cheapest fix:** re-point `NC_GIS["Rutherford"]` from `MapServer/6` (`addr_field=None`) to `MapServer/7` PS_VIEW with `addr_field="Physical_Address"` — one-line change unlocks situs+sqft+value+sale+owner-mailing for the whole county; keep the lrcpwa card as the beds source.

---

### Cleveland, NC
County seat: Shelby. Assessor/GIS platform: **ArcGIS (county `gis.clevelandcounty.com`, geometry-only Tax layer)**; assessor card via WebGIS/Hurt&Proffitt static PropertyCard; ROD via CCHS classic-ASP.

| Layer | Free endpoint / portal (URL or repo const) | Access | heated sqft | beds/baths | sale $ | condition/CDU | owner-mailing | Notes / wall |
|---|---|---|---|---|---|---|---|---|
| 1. Assessor/CAMA bulk layer | `gis.clevelandcounty.com/arcgis/rest/services/Tax/Tax/MapServer/1` (`Parcel Area`; repo `NC_GIS["Cleveland"]`) | ✅ open JSON, but CAMA-poor | ❌ | ❌ | ⚠️ `GIS_DeedBook_Page` only (no $) | ❌ | ⚠️ `GIS_Owner1/Owner2` (no mailing addr) | Repo comment ("GIS_PID/GIS_PIN only") is slightly stale — layer actually adds `GIS_Owner1/2`, `GIS_DeedBook_Page`, `GIS_Calculated_Acres`, `GIS_X/Y_Coord`. **Still no situs, no sqft, no value, no sale $.** Only 3 layers in whole Tax service; no CAMA layer exists free. |
| 2. qPublic/Schneider parcel CARD | ❌ n/a — no qPublic. Card = `webgis.net/nc/cleveland/PropertyCard.php?pid={PID}` (repo `assessor_cards/cleveland_nc.py`) | ✅ open (static server-rendered `<pre>` text) | ✅ `MAIN FIN AREA` | ✅ `#BED`+`#BTH`/`#HBTH` | ✅ full SALES HISTORY (book/page/date/instrument/**amount**/disqualified) | ⚠️ market-adjust factor in FMV line (not a true CDU) | ❌ | **Best free card of the three** — sqft+beds+baths+FMV+arms-length-flagged sale $. BUT keyed by WebGIS internal `pid` (small int); **no static address→pid endpoint** (search is a JS/ArcGIS SPA), so address-only leads can't resolve → this is the county's core wall. |
| 3. GIS parcel polygon + situs | `Tax/MapServer/1` (polygon geometry + PIN; **no situs field**) | ✅ open JSON | — | — | — | — | ⚠️ owner only | Geometry + parcel-id + centroid usable; situs must come from elsewhere (tax portal / ROD / card). |
| 4. GIS address-point layer | ❌ none exposed — only `Tax`, `Basemap`, `Imagery`, `Planning`, `Utilities` folders; no queryable address-point service (root lists only `SampleWorldCities`) | ❌ | — | — | — | — | — | No free E911 address-point service → no address↔pid bridge, which is what blocks the WebGIS card for address-only leads. |
| 5. Register of Deeds index | CCHS `us5.courthousecomputersystems.com/clevelandnc/` (repo `rod/cchs.py` → `("NC","Cleveland"):("us5","ClevelandNCNW","clevelandnc")`) | ⚠️ browser flow (classic-ASP `SearchService.asp`, free, plain httpx) | ❌ | ❌ | ⚠️ excise/`mo` per instrument | ❌ | ✅ grantor/grantee | Same CCHS pattern as Henderson (shared `us5` install with Burke). Name/instrument search; index only. |
| 6. ROD document images | CCHS `application.asp?cmd=image_link…tif2pdf=true` (clevelandnc app) | ✅ open (deep-linked PDF) | — | — | — | — | — | Deed image PDFs free; OCR for loan amount. |
| 7. Tax bill / delinquent-tax portal | `clevelandcountytaxes.com` / `taxes.clevelandcountytreasurer.org` (search by acct/owner/parcel/address). Foreclosure sales: `clevelandcounty.com/.../find_tax_foreclosures…/index.php` (repo `cleveland_tax.py`) | ⚠️ browser (public lookup, no login) | ❌ | ❌ | ⚠️ opening bid on FCL; tax due on portal | ❌ | ⚠️ owner | Cleveland is **NOT a bcpwa tenant** (repo note: runs Government Window / DEVNET Wedge lineage). Delinquent-tax lookup is a public web search, not a bulk API → per-parcel only, no free bulk roll. Foreclosure page carries situs+parcel+file# (partly closes the situs gap for distressed leads). |
| 8. Condemned/code/vacant layer | ❌ none free-verified | ❌ | — | — | — | — | — | No public condemned/vacant/code-enforcement feed found. |

**Biggest free gap here:** situs address for non-distressed leads — the GIS parcel layer has no situs field and there's no free address-point service, so a PIN or owner name can't be turned into a street address (and the rich WebGIS card can't be reached) without the county's JS-only address search.
**Cheapest fix:** scrape the public `clevelandcountytaxes.com` per-parcel lookup (owner/parcel/address → situs + tax due + the WebGIS `pid`), then feed that `pid` into the already-built `PropertyCard.php` card for sqft/beds/baths/sale $ — bridges the missing address-point layer without touching the JS SPA.

---

**Cross-county note for the pipeline:** the two highest-value, lowest-effort wins are both one-line registry edits in `enrichment_arcgis.py` `NC_GIS`: (1) Rutherford → re-point to `MapServer/7` `PS_VIEW` with `addr_field="Physical_Address"` (unlocks situs+sqft+value+sale+owner-mailing, currently `None`); (2) Henderson → its FeatureServer already returns `HEATED_AREA`/`TOTAL_PROP_VALUE`/`PKG_SALE_*`/`PROPERTY_OWNER` but only `LOCATION_ADDR` is consumed — those aliases just need adding so the open data is actually applied. Cleveland remains genuinely CAMA-poor at the GIS layer; its value lives in the WebGIS card, gated only by the missing address→pid bridge.


### Burke, NC
County seat: Morganton. Assessor/GIS platform: **Farragut/NCPTS Cloud (lrcpwa land-records SPA)** + a hosted Esri Tax_Parcels layer + a separate Morganton city ArcGIS Server. Burke is a live `X-Tenant` on the lrcpwa cluster (verified 441 hits for "main").

| Layer | Free endpoint / portal (URL or repo const) | Access | heated sqft | beds/baths | sale $ | condition/CDU | owner-mailing | Notes / wall |
|---|---|---|---|---|---|---|---|---|
| (1) Assessor/CAMA bulk layer | lrcpwa `getParcelDetails?ParcelId=` (X-Tenant: Burke), repo `enrichment_lrcpwa_parcel.BASE` + rutherford_nc card `_DETAILS` | ✅ open JSON | ✅ `heatedArea`/`buildings[0].heatedArea` (live: id=763→1089, id=2000→1443) | ❌ null in Burke feed (Rutherford has them; Burke's CAMA leaves beds/bath/yearBuilt empty) | ✅ `packageSalePrice`+`packageSaleDate`+`deedBook/Page` (live: id=406→$110k 2017) | ❌ no CDU/condition field exposed | ✅ owner + full mailing via lrcpwa `mailingAddress*` | Best single free source here; card-quality data behind one header |
| (2) qPublic/Schneider parcel CARD | ❌ Burke is not a qPublic/Schneider county | n/a | — | — | — | — | — | Not on Schneider; lrcpwa is the equivalent |
| (3) GIS parcel polygon + situs | Hosted `services3.arcgis.com/axQ4OCSpcxALIQsV/.../Tax_Parcels/FeatureServer/0` (repo `enrichment_arcgis` Burke, addr_field `LOCATION_ADDR`) | ✅ open JSON, polygon | ❌ no sqft field | ❌ | ⚠️partial `DEED_DATE/BOOK/PAGE` only (no price) | ❌ | ✅ `PROPERTY_OWNER`+`OWNER_MAIL_1..ZIP` | Full situs in `LOCATION_ADDR` (also split PHYADDR_* fields) |
| (4) GIS address-point layer | Morganton `gis.morgantonnc.gov/.../General/Parcels_Only/FeatureServer/0` (repo `enrichment_owner_mailing` NC:Burke) | ✅ open JSON, polygon (not points) | ❌ | ❌ | ❌ | ❌ | ✅ `Property_Owner`+`Owner_MA*` | No true address-point layer found; situs = `Property_Address`/`PA_*` split |
| (5) Register of Deeds index | CourtComp Systems `us5.courthousecomputersystems.com/BurkeNC2/` (also `burke.courtcompsys.com/burkeNC/`) | ⚠️partial browser (HTTP 200, ASP index UI, no JSON API) | — | — | ⚠️ consideration sometimes indexed | — | grantor/grantee names | Free public index; must be screen-scraped/manual, no bulk feed |
| (6) ROD document images | Same CourtComp portal (image view per instrument) | ⚠️partial browser | — | — | — | — | — | Images free to view; per-doc, no bulk download API |
| (7) Tax bill / delinquent-tax portal | `burkenctax.com/TaxSearch/` (bills); delinquent roll via lrcpwa/bcpwa `X-Tenant: Burke` (repo `nc_ptscloud_delinquent_tax` — valid tenant, no live export blob yet) | ✅ tax-search browser; ✅ delinquent auto-lights-up when county posts extract | — | — | — | — | owner | Delinquent-$ present when bcpwa blob appears; today yields 0 |
| (8) Condemned/code/vacant layer | ❌ none found free | ❌ | — | — | — | — | — | No public code-enforcement/vacant GIS feed for Burke |

**Biggest free gap here:** beds/baths — Burke's CAMA feed leaves them null even though the same lrcpwa platform serves them for Rutherford, so there's no free structured bed/bath anywhere in-county.
**Cheapest fix:** parse the free CourtComp ROD deed text or accept sqft-only; beds/baths aren't worth a paid data buy at this county's volume.

### Lincoln, NC
County seat: Lincolnton. Assessor/GIS platform: **County-hosted ArcGIS Server** (`arcgisserver.lincolncountync.gov`, "RevalLayers" CAMA + "Server_TaxParcelViewerSP" parcels). NOT an lrcpwa/Farragut tenant and NOT qPublic.

| Layer | Free endpoint / portal | Access | heated sqft | beds/baths | sale $ | condition/CDU | owner-mailing | Notes / wall |
|---|---|---|---|---|---|---|---|---|
| (1) Assessor/CAMA bulk layer | `arcgisserver.lincolncountync.gov/.../RevalLayers/MapServer/24` (repo card `lincoln_nc.py` `_QUERY`; alias "Appraised Parcels") | ✅ open JSON | ✅ `MAINAREASQFT` (heated/main area) | ❌ layer has no bed/bath/yearBuilt fields | ✅ `SALEPRICE`+`SDATE`+`DEEDBK/PG/YR`+`QUALIFIEDCODE` | ⚠️partial `QUALIFIEDCODE` (sale qualification, not a CDU condition grade) | ✅ `NAME1/NAME2`+`ADDRESS1/2/CITY/STATE/ZIP` | One row/parcel (current owner + most-recent recorded sale); has a `VACANT` flag |
| (2) qPublic/Schneider parcel CARD | ❌ not a Schneider county | n/a | — | — | — | — | — | RevalLayers is the CAMA equivalent |
| (3) GIS parcel polygon + situs | `arcgisserver.lincolncountync.gov/.../Server_TaxParcelViewerSP/MapServer/0` (repo `enrichment_arcgis` + `owner_mailing` NC:Lincoln, situs `PHYSICALADDR`, parcel `PIN`) | ✅ open JSON, polygon | ❌ (sqft lives on RevalLayers/24) | ❌ | ⚠️partial deed refs only | ❌ | ✅ owner + mailing | Primary situs/parcel resolver layer |
| (4) GIS address-point layer | ❌ no dedicated point layer wired; situs comes from parcel `PHYSICALADDR` | ❌ | — | — | — | — | — | Parcel-centroid geometry is used as the point |
| (5) Register of Deeds index | CourtComp/CourtHouseComputerSystems `courthousecomputersystems.com/lincolnnc/` (also lincolnrod.com land-records) | ⚠️partial browser (HTTP 200, ASP UI) | — | — | ⚠️ consideration sometimes | — | grantor/grantee | Free public index, no bulk/JSON |
| (6) ROD document images | Same CourtComp portal | ⚠️partial browser | — | — | — | — | — | Free per-doc view; no bulk API |
| (7) Tax bill / delinquent-tax portal | Bills: `lincolncountytax.com` / lincolncountync.gov Online Payments. Delinquent roll: **county .gov PDF** `lincolncountync.gov/DocumentCenter/View/25558/2025-TAXES...` (repo `nc_county_pdf_delinquent_tax` layout `name_id_amt`, id=4-6-digit PIN) | ✅ bills browser; ✅ delinquent PDF open (parsed) | — | — | — | — | owner (from PDF) | Not an ncptscloud tenant, so no API roll; the annual PDF advert is the free delinquent source |
| (8) Condemned/code/vacant layer | ⚠️partial — RevalLayers/24 exposes a `VACANT` field (land-vacancy flag, not condemnation) | ✅ open JSON | — | — | — | — | — | No code-enforcement/condemned feed; `VACANT` ≠ distressed condition |

**Biggest free gap here:** beds/baths + structure condition — the Reval CAMA layer simply omits those columns, and there's no qPublic card to fall back on, so only sqft/value/sale come free.
**Cheapest fix:** none needed for sqft/sale/value (all free on RevalLayers/24); for beds/baths, defer to the paid/estimated path rather than the ROD.

### McDowell, NC
County seat: Marion. Assessor/GIS platform: **Esri ArcGIS Online hosted parcel layer** (`services9.arcgis.com/ETP7IuCigkUz7iI9/.../McDowell_Parcels`) + BTServices tax portal + custom ROD. NOT lrcpwa, NOT qPublic.

| Layer | Free endpoint / portal | Access | heated sqft | beds/baths | sale $ | condition/CDU | owner-mailing | Notes / wall |
|---|---|---|---|---|---|---|---|---|
| (1) Assessor/CAMA bulk layer | Hosted `services9.arcgis.com/ETP7IuCigkUz7iI9/.../McDowell_Parcels/FeatureServer/0` (repo `enrichment_arcgis`/`owner_mailing` NC:McDowell, parcel `parno`) | ✅ open JSON | ❌ no sqft field (only `struct`/`structno`/`structyear` counts) | ❌ | ❌ `saledate`/`transfdate` present but **no price field** | ❌ | ✅ `ownname/ownname2`+`mailadd/munit/mcity/mstate/mzip` | Thin GIS-only CAMA; value via `parval`/`presentval` (land+imp) |
| (2) qPublic/Schneider parcel CARD | ❌ not Schneider — county runs `webgis.net/nc/McDowell` (WebGIS/GoMaps) | ⚠️partial browser | ⚠️ card may show sqft in WebGIS viewer | ⚠️ possibly | ⚠️ possibly | ⚠️ possibly | owner | WebGIS.net has no clean JSON API; the richer CAMA card is only in the HTML viewer, not the hosted layer |
| (3) GIS parcel polygon + situs | Same `McDowell_Parcels` layer, situs `siteadd` (+ split `sadd*` fields) | ✅ open JSON, polygon | ❌ | ❌ | ❌ | ❌ | ✅ | Best free situs/owner source |
| (4) GIS address-point layer | ❌ no separate point layer in this org (services9 is a shared Esri org; only the one McDowell parcel layer) | ❌ | — | — | — | — | — | Use parcel centroid; NC OneMap `siteadd` is the statewide fallback |
| (5) Register of Deeds index | `search.mcdowelldeeds.com/index.php` ("The Lookup", records from 1971) | ⚠️partial browser (HTTP 200, custom PHP search) | — | — | ⚠️ consideration sometimes | — | grantor/grantee | Free public index; no bulk/JSON, must screen-scrape |
| (6) ROD document images | `mcdowelldeeds.com` image view per instrument | ⚠️partial browser | — | — | — | — | — | Free per-doc; no bulk download API |
| (7) Tax bill / delinquent-tax portal | Bills: BTServices `bttaxpayerportal.com/itspublicmd` (HTTP 200). Delinquent roll: **county .gov PDF** `mcdowellnc.gov/departments/tax-collections/.../ADVERTISEMENT-LIST-FINAL-2025.pdf` (repo `nc_county_pdf_delinquent_tax` layout `parcel_amt_owner`) | ✅ tax portal browser; ✅ delinquent PDF open (parsed) | — | — | — | — | owner + amount owed (from PDF) | Delinquent lane already built; BT portal has current bills but no clean bulk export |
| (8) Condemned/code/vacant layer | ❌ none found free | ❌ | — | — | — | — | — | `struct=0`/no-structure in the parcel layer is the only vacancy proxy |

**Biggest free gap here:** sale price AND heated sqft — the hosted parcel layer carries `saledate` but no price and no sqft, and there's no qPublic card or lrcpwa feed to recover them, so distressed-equity math has no free structured comp/size input in-county.
**Cheapest fix:** OCR the free `mcdowelldeeds.com` recorded-deed images for consideration (existing `enrichment_doc_ocr`) and/or read sqft off the WebGIS.net HTML card per parcel; both are free but slower than a JSON pull.


### Polk, NC
County seat **Columbus**. Assessor/GIS platform: **ArcGIS Hosted (Esri Online org `23uf7jKvz6SRPFWJ`)** for parcels + a per-parcel PDF "Property Record Card" off the county GIS box; ROD is **Cott Systems (cotthosting.com)**.

| Layer | Free endpoint / portal (URL or repo const) | Access | heated sqft | beds/baths | sale $ | condition/CDU | owner-mailing | Notes / wall |
|---|---|---|---|---|---|---|---|---|
| (1) Assessor/CAMA bulk layer | `services1.arcgis.com/23uf7jKvz6SRPFWJ/.../Parcels/FeatureServer/0` (repo `enrichment_owner_mailing.COUNTY_GIS["NC:Polk"]` / `assessor_cards.polk_nc._BASE`) | ✅ open JSON | ❌ not on layer | ❌ | ⚠️ `DEED_BOOK`/`DEED_PAGE`/`DEED_YEAR` only, no price | ⚠️ `NEIGHBORHOOD_CLASS` only | ✅ `OWNAM1-3`+`OWADR1/OWCITY/OWSTA/OWZIPA` | Carries `LAND_VALUE`, `BUILDING_VALUE`, `TOTAL_TAX_VALUE`, and rare **`TOTAL_TAX_OWED`** (delinquent-$ direct). No structural specs. |
| (2) qPublic/Schneider parcel CARD | none | ❌ | — | — | — | — | — | Polk is not on qPublic/Schneider (probe 403 = not that platform). Card = the PDF below, not qPublic. |
| (3) GIS parcel polygon + situs | same FeatureServer/0, `addr_field=PHYSICAL_STREET_ADDRESS` (repo `enrichment_arcgis.NC_GIS["Polk"]` -> `.../TaxParcels/FeatureServer/0`) | ✅ open JSON, polygon geom | ❌ | ❌ | ❌ | ❌ | ✅ | Situs via `PHYSICAL_STREET_ADDRESS` / `PHYSICAL_LOCATION`. |
| (4) GIS address-point layer | not separately used | ⚠️partial | — | — | — | — | — | Repo resolves situs off the parcel polygon; no dedicated address-point layer wired. |
| (5) Register of Deeds index | `cotthosting.com/ncpolkexternal/LandRecords/protected/v4` (repo `rod/cott.py COTT_COUNTIES["NC:Polk"]`) | ⚠️ browser-form (ASP.NET viewstate; repo posts it browserless) | — | — | ⚠️ deed book/page, no $ in index | — | grantor/grantee names | Cott/Manatron name-search flow; `SrchName.aspx` 302s (session bootstrap). Shares parser w/ `aumentum.py`. |
| (6) ROD document images | Cott image viewer (same tenant) | ⚠️ browser/paywall-ish | — | — | — | — | — | Scanned deed/DoT PDFs reachable per-doc; loan $ only via OCR of the DoT image (repo `enrichment_doc_ocr.py`). No $ in index. |
| (7) Tax bill / delinquent-tax portal | `polknc.gov/upcoming_auction.php` (repo `counties_nc/polk_tax.py`, Kania Law Firm list) ✅; **`TOTAL_TAX_OWED` on GIS layer (1)** ✅ | ✅ open (auction HTML + GIS field) | — | — | — | — | — | Best-in-cohort: tax-owed is a live GIS field, no portal scrape needed. `polknc.org/tax_administration` = 404 (stale link in `stale_link_fallback`; use `.gov`). |
| (8) Condemned/code/vacant layer | none found | ❌ | — | — | — | — | — | No public condemned/code-enforcement/vacant feature service for Polk. |

**Biggest free gap here:** heated sqft + beds/baths — absent from every JSON layer; only obtainable by fetching and OCR/parsing the per-parcel `PropertyRecordCard` PDF (`http://parcels.polknc.org:8080/<TMS>.pdf`), which is slow and page-by-page.
**Cheapest fix:** already built — `assessor_cards/polk_nc.py` resolves the PDF URL from GIS and pdfplumber-parses "Finished Area" + the sales-price block; just ensure it runs for every Polk lead.

### Transylvania, NC
County seat **Brevard**. Assessor/GIS platform: **county-hosted Esri ArcGIS Server** (`gis.transylvaniacounty.org`) — the single richest layer in this cohort; ROD is **Logan Systems ("The Lookup")**.

| Layer | Free endpoint / portal (URL or repo const) | Access | heated sqft | beds/baths | sale $ | condition/CDU | owner-mailing | Notes / wall |
|---|---|---|---|---|---|---|---|---|
| (1) Assessor/CAMA bulk layer | `gis.transylvaniacounty.org/server/rest/services/Parcels/MapServer/2` (repo `enrichment_owner_mailing.COUNTY_GIS["NC:Transylvania"]` + `enrichment_recorded_comps` config) | ✅ open JSON | ✅ `HEATED_SQ_` (populated on 19,397/31,765 = every improved parcel) | ✅ `BEDROOMS`,`BATHS`,`HALF_BATHS` | ✅ `SALE_PRICE`+`SALE_DATE` (yyyymm) + `SALE_QUALI`/`SALE_INST` | ✅ `QualityFactor`,`EYB`,`AYB`,`EXT_WALL_1/2`,`ROOF_COVER`,`HEAT_CODE`,`AIR_COND_C` | ✅ `OWNER_NAME`+`ADDRESS_1/2/3` (ADDRESS_3=situs, ADDRESS_1=owner) | Full CAMA in one open layer. `ASSESSED_V`,`LAND_VALUE`,`BUILDING_V` present. This is the county with recoverable $/sqft comps (`RECORDED_COMP_CONFIG`). |
| (2) qPublic/Schneider parcel CARD | none | ❌ | — | — | — | — | — | Not on qPublic (probe 403). CAMA card data is already inline in layer (1), so no card needed. |
| (3) GIS parcel polygon + situs | same MapServer/2, `addr_field=ADDRESS_3` (repo `enrichment_arcgis.NC_GIS["Transylvania"]`) | ✅ open JSON, polygon geom | ✅ | ✅ | ✅ | ✅ | ✅ | Situs = `ADDRESS_3` / `LEGAL_ADDR`. Same layer as (1). |
| (4) GIS address-point layer | not separately needed | ⚠️partial | — | — | — | — | — | Situs is on the parcel layer; no separate address-point layer wired. |
| (5) Register of Deeds index | `search.transylvaniadeeds.com` (repo `rod/logan.py LOGAN_COUNTIES["NC:Transylvania"]`) | ✅ browserless (200; repo drives instrument-type date-range sweep w/ `DISTRESS_CODES`) | — | — | ⚠️ deed stamp only, not sale price | — | grantor/grantee names | Logan pick-list loads cleanly — supports the name-less distress sweep (FCL/LIS-P/TR-D…). |
| (6) ROD document images | Logan doc viewer (same host) | ⚠️ per-doc render | — | — | — | — | — | Scanned deed/DoT PDFs; loan-$ via OCR only. Index has no $. `Report_URL` on GIS is null (0/31,765) — no per-parcel card link. |
| (7) Tax bill / delinquent-tax portal | `tax.transylvaniacounty.org` (live, 200); auction PINs via `transylvaniacounty.org/news` (repo `nc_govdeals_real_property.parse_transylvania_notices`) | ⚠️ portal browser / ✅ news-feed HTML | — | — | — | — | — | Not a nc_ptscloud/PTS tenant (repo note: runs Government Window / DEVNET). Tax-owed $ not exposed on GIS (unlike Polk). |
| (8) Condemned/code/vacant layer | none found | ❌ | — | — | — | — | — | No public condemned/vacant service; Helene damage layer also unavailable for this county. |

**Biggest free gap here:** current delinquent tax-owed dollars — there's no open field (GIS layer has value but not tax owed) and the county tax portal is Government Window (browser/bot-walled), so per-parcel balances aren't free-scrapable.
**Cheapest fix:** parse the county legal-notice/news feed (already wired) for tax-foreclosure PINs, then read the sale/opening-bid from the notice text — it substitutes for a delinquent-balance pull for the parcels that actually matter.

### Mitchell, NC
County seat **Bakersville**. Assessor/GIS platform: **county-hosted Esri ArcGIS Server** (`mapping.mitchellcountync.gov`, WebMapNew); ROD is **Logan Systems**; tax billing is **Government Window**.

| Layer | Free endpoint / portal (URL or repo const) | Access | heated sqft | beds/baths | sale $ | condition/CDU | owner-mailing | Notes / wall |
|---|---|---|---|---|---|---|---|---|
| (1) Assessor/CAMA bulk layer | `mapping.mitchellcountync.gov/arcgis/rest/services/WebMapNew/MapServer/12` (repo `enrichment_owner_mailing.COUNTY_GIS["NC:Mitchell"]`) | ✅ open JSON | ❌ not on layer | ❌ | ⚠️ `Deed_Date`+`DeedBook`/`DeedPage`, no price | ⚠️ `PropClas` only | ✅ `Owner1/2`+`MailAddr/City/State/Zip` | Value present as `Land`/`Dwelling`/`Total`. No structural specs, no sale price — thinnest CAMA of the three. |
| (2) qPublic/Schneider parcel CARD | none | ❌ | — | — | — | — | — | Not on qPublic (probe 403); `mitchell.northcarolinaassessors.com` dead (000). No third-party CAMA card. |
| (3) GIS parcel polygon + situs | same MapServer/12, `addr_field=LocAddr` (repo `enrichment_arcgis.NC_GIS["Mitchell"]`) | ✅ open JSON, polygon geom | ❌ | ❌ | ❌ | ❌ | ✅ | Situs `LocAddr` sometimes street-name-only; repo `enrichment_parcel_reverse_geo` uses this layer for lat/lng→parcel. |
| (4) GIS address-point layer | not separately wired | ⚠️partial | — | — | — | — | — | No dedicated address-point layer identified; situs off parcel polygon only. |
| (5) Register of Deeds index | `search.mitchelldeeds.com` (repo `rod/logan.py LOGAN_COUNTIES["NC:Mitchell"]`) | ✅ browserless (200; pick-list loads, distress sweep supported) | — | — | ⚠️ deed book/page, no $ | — | grantor/grantee names | Standard Logan distress codes work here. |
| (6) ROD document images | Logan doc viewer (same host) | ⚠️ per-doc render | — | — | — | — | — | Scanned deed/DoT PDFs; loan-$ via OCR only. |
| (7) Tax bill / delinquent-tax portal | `mitchellnctax.governmentwindow.com` (403 to httpx = live but bot-walled); GIS `Total` = assessed, not owed | ⚠️ walled (Government Window bot-block) | — | — | — | — | — | NOT a PTS/nc_ptscloud tenant (repo note). No free delinquent-$ path; `mitchellcounty.org` returns 523 (Cloudflare). |
| (8) Condemned/code/vacant layer | none found | ❌ | — | — | — | — | — | No public condemned/code/vacant service. |

**Biggest free gap here:** structural specs (heated sqft, beds/baths) and sale price — none exist on any Mitchell free JSON layer, and there is no qPublic card or PDF property-record card to fall back to (unlike Polk).
**Cheapest fix:** value the property from GIS `Total`/`Dwelling` assessed values (already captured) and borrow $/sqft from a Transylvania/Burke recorded-comps median, since Mitchell has no free per-parcel sqft or sale source to build its own comps from.


---

# Deep-Dive Round 3 — Outreach-Execution Layer Priced (2026-07-02)


## Direct Mail (yellow letters / postcards)

### Why it matters + where it fits in the funnel
Direct mail is the highest-trust, lowest-competition touch for distressed-property owners — the exact profile in this board (elderly, probate, tax-delinquent, incarcerated, pre-foreclosure). Many of these sellers are unreachable or unresponsive by phone/text (bad numbers, DNC, screening), but a physical yellow letter or postcard lands in the mailbox of the *property-of-record address* even when we have no phone at all. That makes mail the **primary channel for the "name→property, no-contact" slice** the pipeline can't skip-trace, and the warm-up layer that makes a later call/text land ("you sent me a letter…"). Funnel position: top-of-funnel first-touch + multi-touch nurture (industry response for investor mail runs ~1-1.5% on handwritten/yellow letters, lower on postcards, and lifts materially on touch 3-5). It's slower and pricier per piece than SMS/RVM but converts a segment nothing else reaches, and it's TCPA-exempt.

### Vendors

Two tiers: **(A) API/programmable print-and-mail houses** (plug straight into the CSV export — mail-merge, address verification, webhooks) and **(B) investor-niche mail houses** (better handwritten/yellow-letter craft, UI/CSV upload, weaker API). Prices are all-in per piece (print + first-class or standard postage) unless noted. All "as of 2026, verify at order."

- **Lob** — Enterprise-grade print & mail API; real-time address verification, NCOA, tracking webhooks, template engine. **4x6 postcard $0.582 / first-class letter $0.606 (Growth plan); $0.872 / $0.806 on the free Developer plan.** Subscription: Developer free (≤500/mo, 1 user), Startup $260/mo (≤3,000), Growth $550/mo (≤6,000), Enterprise custom. **Integration: full REST API + CSV/UI.** Best-in-class dev tooling; postcard base only 4x6 (small).
- **PostGrid** — Direct competitor to Lob; strong API + address verification + PDF/HTML templates. Public per-piece is quote-gated but reported **~$0.86 postcard, letters from ~$0.55 + postage**; EDDM flat ~$0.223/piece retail. Three tiers: pay-per-piece (no commitment), subscription (platform fee + discounted per-piece), enterprise (annual). **Integration: full REST API + CSV/UI.** Quote-only for firm per-piece — verify.
- **Click2Mail (Mailing Online Pro)** — Long-running USPS-partner mail-on-demand; no subscription, pure pay-per-piece. **Postcard from $0.55 (standard) / $0.64-$0.73 (with image/5x8); letter w/ picture $1.45 first sheet + $0.75/added sheet.** Built-in CASS + NCOA cleansing, Intelligent Mail tracking, 1/3/7-day production discounts. **Integration: REST / Batch XML / SOAP API + UI upload.** No monthly fee is the draw; letter pricing runs high.
- **Stannp (US)** — Transparent self-serve UI + API, no minimums, postage included. **Letters $0.95 (free tier) down to $0.69/piece at 50k+ (Premium); postcards priced similarly by size tier.** Subscription: Free $0, Starter $12/mo, Growth $48/mo, Premium $315/mo. **Integration: API + CSV/UI + Zapier.** Cheap monthlies, genuinely usable free tier; postcard per-piece not fully public — verify size/tier.
- **Ballpoint Marketing** — Investor-focused; robotic true-pen "handwritten" letters, hybrid greeting cards, door hangers. **Hybrid Greeting Letter $0.74/piece; range $0.65-$2.00+ by format; door hangers from $0.45 (250 min).** Reported 1-1.5% response on greeting letters. **Integration: UI/CSV upload + some CRM integrations (REsimpli, InvestorFuse); no open public API.** Best craft for the "yellow letter" play; per-piece higher.
- **Yellowletters.com / Yellow Letter HQ** — Original real-estate handwritten-letter shop. **Per-piece varies by paper/envelope/postage; comparable "true handwritten" letters run ~$1.50/piece all-in** (e.g., Yellow Letter charges $1.52/letter incl. first-class). **Integration: UI/CSV upload only.** Premium handwritten; priciest per piece; quote-driven.
- **Open Letter Marketing** — Investor mail house (founder is an investor); professional letters, "Real Penned" letters, StreetView postcards; transparent published tiers. **Professional letter: standard-class $0.78 (10k+) to $1.09 (200-499); first-class $1.05-$1.36.** List access add-on ~$0.035/lead. **Integration: UI/CSV upload; integrates with common REI CRMs; no open API.** Clear volume pricing, investor-tuned copy.
- **Wise Pelican** — Realtor/investor postcard specialist, no minimum. **Mailed-for-you 6x9 jumbo postcard $1.04 all-in; print-and-ship-to-you $0.86.** Automated seller-valuation postcards +$0.05. **Integration: UI/CSV upload + some CRM hooks.** Simple, no-minimum postcards; higher per-piece (jumbo + retail postage).
- **PostcardMania** — Full-service agency (design + list + mail), best economics only at scale. **Postcards land ~$0.15-$0.45/piece all-in at volume; $0.05/piece addressing; flat $199 design; ~500-1,000 piece practical minimum.** Frequent promos (1,000 free). **Integration: UI/account-managed; API via partners; not self-serve programmatic.** Cheapest at true volume but sales-managed, not API-native.
- **ProspectBoss** — Primarily a CRM/dialer + ringless-voicemail vendor that bolts on direct mail; useful only if consolidating channels. **RVM PAYG 1,000/$49, 5,000/$199, 10,000/$299; direct-mail postcards quote-based (~$0.55-$0.90 benchmark).** **Integration: their CRM/UI; no standalone mail API worth wiring.** Skip for mail-only; relevant only if you also want their RVM/CRM.
- **Stannp vs the niche shops summary:** API houses (Lob/PostGrid/Click2Mail/Stannp) win on automation + cost; niche shops (Ballpoint/OLM/Yellowletters/Wise Pelican) win on handwritten craft + investor copy but are CSV-upload-bound.

**Handwritten-font premium:** printed "handwriting-style font" (Lob/PostGrid/Stannp) is essentially free — it's just a font. **True robotic-pen or real-ink handwriting (Ballpoint, Yellowletters, OLM Real Penned) adds roughly $0.30-$0.80/piece** over a printed letter and pushes all-in to $1.00-$2.00. For a 17k-owner cold list, printed yellow-letter font is the rational default; reserve true-pen for the HOT re-touch.

**First-class vs standard vs EDDM:** First-class (~$0.73 postage 2026) = fastest, forwards free, returns free, best for time-sensitive pre-foreclosure. Standard/Marketing Mail (presort, ~$0.35-$0.45 postage) = ~$0.30/piece cheaper but slower and needs a permit/500-piece minimum. **EDDM = un-addressed saturation by carrier route (~$0.22/piece postage), useless here** — our value is targeted named owners, not whole routes. Use first-class for HOT, standard for the WARM bulk.

### Compliance / legal gotchas
- **TCPA / DNC do NOT apply to physical mail.** This is the single biggest reason mail is the safe workhorse for this list — no consent, no 10DLC registration, no RVM state bans, no call-time windows. (10DLC and RVM state bans are SMS/voice problems, not mail problems.)
- **CAN-SPAM does NOT apply to postal mail** (it's an email statute). No unsubscribe requirement on letters.
- **No federal "do not mail" registry.** DMAchoice (dmachoice.org) is a voluntary industry suppression list — honoring it is best practice, not law; scrub opt-outs you receive.
- **SC & NC specifics — no special "advertising letter" licensing for buying houses**, but two concrete traps: (1) **Deceptive-form / "official-looking" mail:** both states enforce UDAP (SC Unfair Trade Practices Act; NC G.S. 75-1.1) — do **not** design pieces to mimic government, court, or bank notices (common with foreclosure mail). Clearly identify yourself as a private buyer. (2) **Foreclosure-rescue / equity-purchase disclosure:** when mailing owners already in active foreclosure, avoid any "we'll save your home / stop foreclosure" framing — that can trip foreclosure-consultant statutes. Stick to "we buy houses / cash offer." (3) **Wholesaler licensing note (operational, not mail-law):** SC in particular has tightened on unlicensed wholesaling — the letter content should offer to *buy*, not advertise an assignable contract.
- **Accuracy of claims:** any "cash offer / close in X days" must be truthful (UDAP). Keep a copy of every mailed piece and the list version for records.
- **Return-address hygiene:** use a real, deliverable return address (needed anyway for the NCOA trick below).

### The return-service-requested free-NCOA trick
USPS **Move Update** compliance normally requires paid NCOALink processing (~$0.01-$0.05/record via a processor). The workaround: **mail First-Class with the ancillary endorsement "Return Service Requested."** First-Class mail gets **free forwarding and free return service regardless of endorsement**, and RSR returns undeliverable pieces to you **with the USPS-known new address or the reason it failed, at no charge.** Practically, this means the **first First-Class drop doubles as a free skip-trace / list-cleaning pass** — movers, vacants, and deceased-forwarded addresses come back with corrected data you fold into the CSV. It only works on **First-Class (not Standard/Marketing Mail),** so run the *first* touch of a new list First-Class-with-RSR, capture the corrections, then move the cleaned survivors to cheaper Standard for follow-ups. This is why First-Class is worth the extra ~$0.30 on drop one.

### Recurring cost at our scale
Assume **HOT/WARM ≈ 2,000 pieces/mo**, printed yellow-letter-font first-class letter (best converter for distressed owners), all-in per-piece by vendor:

- **Stannp (Growth $48/mo):** 2,000 × ~$0.82 = **$1,640 + $48 = ~$1,688/mo**
- **Lob (Growth $550/mo):** 2,000 × $0.606 = $1,212 + $550 = **~$1,762/mo** (postcard route: 2,000 × $0.582 + $550 = ~$1,714)
- **Click2Mail (no sub):** postcard 2,000 × ~$0.64 = **~$1,280/mo**; letter route ~$2,900/mo (letters run expensive here)
- **Open Letter (standard-class letter):** 2,000 × ~$0.89 = **~$1,780/mo** (first-class ~$2,320)
- **Ballpoint hybrid greeting:** 2,000 × $0.74 = **~$1,480/mo** (but UI-upload, not API)

**Practical planning number for a 2k first-class letter drop: ~$1,650-$1,800/mo.** Going postcard-only drops it to **~$1,150-$1,300/mo**. Adding the ~$0.30/piece first-class premium only on drop-one (for the RSR NCOA cleanse) is ~$600 one-time per new list, recovered by not mailing dead addresses again.

**Full 17,003-piece single drop** (one-time saturation of the whole board):
- Postcard, cheapest credible (Click2Mail/Stannp/Lob 4x6, ~$0.58-$0.64): **~$9,900-$10,900**
- First-class printed letter (Stannp @ $0.82 / Lob @ $0.606): **~$10,300-$13,900**
- Standard-class letter (Open Letter @ $0.78): **~$13,300**
- Handwritten hybrid (Ballpoint @ $0.74): **~$12,600**
- At 17k you clear PostcardMania's/Open Letter's real volume breaks — a managed postcard run can land **~$0.35-$0.45 all-in ≈ $6,000-$7,700**, the floor if you sacrifice API automation.

### Integration path into the engine
1. **CSV → API house (recommended).** The pipeline already exports scored leads with owner name + property/mailing address. Add a small `mail_export()` step that maps board columns → the vendor's recipient schema and POSTs each HOT/WARM record to **Lob/PostGrid/Stannp** (all take JSON with `to.name/address_line1/city/state/zip` + a saved template ID). Gate it on `grade in (HOT,WARM)` and a `last_mailed_at` field to enforce touch cadence. Address verification runs server-side on send.
2. **Webhook back into the board.** Lob/PostGrid/Click2Mail return per-piece status + (with RSR) address corrections; write those to a `mail_status` / `corrected_address` sidecar so the dashboard shows delivered/returned and the enrichment layer ingests the free NCOA corrections — this closes the loop with the existing resolver.
3. **CSV-upload fallback for craft.** For the HOT re-touch where handwritten converts better (**Ballpoint / Open Letter**), export the same HOT subset as their CSV template and upload via UI — no API, just a scheduled hand-off. Track `mailed_via` per lead so both lanes reconcile in one place.
4. **Cadence fits the weekly run** already in the repo: new HOT/WARM each week → first-class-RSR drop one → corrections back → standard follow-ups on survivors at day 21/45.

### Recommended pick + why
**Primary: Stannp (Growth plan, $48/mo) for the automated bulk lane.** It's the cheapest *credible* API-native option — printed letters at **$0.73-$0.82/piece all-in incl. postage**, no minimums, a real REST API + CSV/UI + Zapier, and trivial monthly fee ($48 vs Lob's $550). At 2k/mo it's **~$1,688** — roughly break-even-to-cheaper than Lob while avoiding Lob's $550 platform tax until volume justifies it. Postage is bundled, so no separate USPS permit to manage.

**Runner-up / graduate to: Lob** once monthly volume clears ~5-6k pieces (its $0.58-$0.61 per-piece + mature webhooks/address-verification amortize the $550 and its tracking is best-in-class for closing the loop).

**Craft lane (HOT re-touch only): Ballpoint Marketing** at $0.74 hybrid greeting letters — reserve true-handwritten spend for leads already scored HOT, upload by CSV, don't pay the pen premium on cold 17k.

**Do this:** run the **first touch of every new list First-Class with "Return Service Requested"** through Stannp to get the free NCOA cleanse, then push cleaned survivors to Standard-class for follow-ups. Net budget at 2k HOT/WARM/mo ≈ **$1,650-$1,700**; a full one-time 17k postcard saturation ≈ **$10k** (or ~$6-7.7k if handed to PostcardMania at managed volume, sacrificing automation).

Sources: [Lob pricing](https://www.lob.com/pricing) · [PostGrid pricing](https://www.postgrid.com/pricing-print-mail/) · [Click2Mail MOL Pro API](https://click2mail.com/by-service/mol-pro-api) · [Stannp detailed pricing](https://www.stannp.com/us/detailed-pricing) · [Ballpoint Marketing 2026 cost guide](https://ballpointmarketing.com/blogs/investing/direct-mail-real-estate-investors) · [Open Letter Marketing professional letters](https://openlettermarketing.com/product/professional-letters) · [Wise Pelican pricing](https://wisepelican.com/products/direct-mail-pricing-and-cost/) · [PostcardMania pricing](https://www.postcardmania.com/price/) · [ProspectBoss RVM](https://www.prospectboss.com/ringless-messages-old/) · [USPS Move Update / Return Service Requested](https://about.usps.com/publications/pub632/pub632_014.htm) · [PI World – USPS Move Update methods](https://www.piworld.com/article/three-usps-direct-mail-move-update-methods/) · [Direct Mail cost 2026 – MPA](https://www.mailpro.org/post/how-much-does-direct-mail-cost/)


## SMS / Text (10DLC)

### Why it matters + where it fits in the funnel
SMS is the highest-response cold outreach channel in real estate investing: motivated-seller texting typically pulls 5-15% response vs sub-1% for direct mail, and it is fast and cheap per touch. It sits at the **top of the funnel** — first-touch on HOT/WARM scored leads to open a conversation, then hand a warm reply to a human (or the CRM's inbox) to qualify and set an appointment. It is the natural next step after `outreach.py` generates the message body: SMS is the "send" layer this project currently leaves to the operator. **Critical caveat up front (see compliance): cold, non-consented SMS to distressed homeowners is the single most legally exposed channel in this stack.** It is the cheapest to run and the most expensive to get wrong.

### Vendors

Two tiers: **raw CGP/carrier APIs** (you own compliance + build the app) and **REI-vertical platforms** (built-in skip-trace, drip, list management, but the same TCPA exposure). All prices "as of 2026, verify."

- **Twilio** (raw API) — Programmable Messaging. **$0.0079-$0.0083 per SMS segment** (160 GSM-7 chars) + carrier pass-through fees; local number **~$1.15/mo**, toll-free ~$2.15/mo. 10DLC: brand reg **~$4.50 one-time**, campaign **~$15 verification + $1.50-$10/mo** per campaign. Integration = **full REST API** (best for plugging into a CSV/dashboard pipeline). No CRM, no skip-trace, no drip — you build all of it. As of 2026, verify.
- **Launch Control** (REI vertical, the category leader) — subscription only, includes the number pool, drip, list mgmt: **Lite $497/mo (12,500 msgs), Core $797/mo (25,000), Pro $1,497/mo (60,000), Pro Plus $2,297/mo (90,000)**. Integration = **UI-first + Zapier/webhooks**; CSV import of lead lists. No public per-message a-la-carte. As of 2026, verify.
- **Smarter Contact** (REI vertical) — **Starter $149/mo (2,500 msgs @ ~$0.03), Pro $299/mo (unlimited @ ~$0.025), Elite $379/mo (unlimited @ ~$0.02)**. Built-in skip-trace add-on, drip, inbox. Integration = **UI + Zapier/webhook + CSV**. Cheapest credible REI-vertical entry point. As of 2026, verify.
- **REI Reply** (REI vertical, GoHighLevel-based white-label) — public 2026 per-seat pricing is **quote-only** (historically ~$99-$299/mo tiers on a GHL backbone). Includes CRM + SMS + workflows. Integration = **full GHL API + webhooks + CSV**. Treat pricing as quote-only, verify.
- **Roor** (REI vertical) — **quote-only / demo-gated**; no public 2026 price card. Positioned against Launch Control/Lead Sherpa on deliverability. Integration = UI + CSV. Quote-only, verify.
- **Batch Leads / BatchDialer SMS** (REI vertical, part of BatchService) — SMS is credit-based; historically **~$0.02-$0.025 per segment** bundled into platform plans (roughly **$99-$299/mo** tiers) with skip-trace and list-stacking in the same tool. Exact 2026 card is **quote-only**, verify.
- **Textedly** (general business SMS) — free Starter up to **Business $299/mo**; credit-based, extra messages ~**$25 per 500-pack**, +~$8/mo telecom surcharge per number. Integration = **UI + API + CSV**. Not REI-specific and not built for cold prospecting — carrier registration will scrutinize the use case. As of 2026, verify.
- **SimpleTexting** (general business SMS) — **$39/mo (500 credits)** up to **$909/mo (50,000 credits)**; overage ~**$0.055/credit**; includes a local number + 3 seats. Integration = **UI + API + CSV/Zapier**. Same caveat as Textedly: designed for opt-in lists, not cold seller blasts. As of 2026, verify.

### Compliance / legal gotchas — read this before spending a dollar
This is the channel where the project's "free + compliant" mandate collides hardest with reality.

- **The consent wall is the whole ballgame.** The TCPA requires **prior express written consent** for autodialed/automated marketing texts. A foreclosure/probate/tax-delinquent list is, by definition, **people who never gave you consent.** Cold texting them with a platform's mass-send tool is a textbook TCPA marketing text without consent. Statutory damages are **$500-$1,500 per text** — one 1,000-message blast is $500K-$1.5M of theoretical exposure, and real-estate cold texting is a heavily-litigated, serial-plaintiff area.
- **The one-to-one repeal does NOT help you.** The 11th Circuit vacated the FCC's one-to-one consent rule (Jan 24, 2025) and the FCC formalized the elimination in Sept 2025. This only removed a *stricter* proposed layer — it did **not** create any permission to text people who never consented. The baseline prior-express-consent requirement is fully intact. Do not read "one-to-one is dead" as "cold texting is legal." It is not.
- **DNC (federal + state).** Federal DNC applies to marketing; **North Carolina runs its own DNC list** (NC AG) *and* as of **Oct 1, 2025** graduated civil penalties **$500 first offense → up to $5,000** for repeats within two years — you must scrub against both federal and NC state lists. **South Carolina** uses the national registry (no separate list) but has a pending **Telephone Solicitation Act (Bill 3323)** modeled on Florida's "mini-TCPA," which if enacted adds a state private right of action for texts — watch it. Both states also carry the federal **$500-$1,500/violation** private right of action.
- **10DLC registration is mandatory and gatekept.** Since Feb 2025 **all major US carriers fully block unregistered 10DLC traffic** (not throttle — block). You must register a Brand (~$4.50) and a Campaign (~$15 + monthly). Carriers vet the **use case**, and a "cold prospecting / lead generation" campaign to non-opted-in numbers is exactly what T-Mobile/AT&T campaign review is designed to reject or low-trust-score.
- **Throughput / carrier filtering makes brute force impossible anyway.** CTIA guidance: keep each long code under **~15-60 msg/min and under ~200 unique recipients/day**; **T-Mobile actively monitors and fines snowshoeing / number-swapping ($1,000)** — the exact evasion tactic REI platforms lean on to blast lists. Low trust score = throttle or block. So even setting aside TCPA, you cannot legally-and-reliably fire 1-3k cold texts/day through one compliant brand.
- **CAN-SPAM is the email statute, not SMS** — the SMS analog is the TCPA/CTIA regime above, plus every message must include clear sender ID and **STOP opt-out honored immediately**.
- **Bottom line, blunt:** *Cold, mass SMS to distressed owners is not compliant.* The defensible use of SMS here is **(a)** texting only numbers where you have a prior business relationship or captured consent (e.g., a lead who filled out your "sell my house" form), or **(b)** manual, one-at-a-time, non-automated texts (arguably outside the autodialer definition, but still DNC-exposed). Anything that looks like a list blast is the liability.

### Recurring cost at our scale
Assume the compliant path (manual/consented sends) and price the raw-API floor, since REI platforms charge for volume you largely can't legally send in bulk.

- **10DLC one-time + fixed:** Brand ~$4.50 + Campaign ~$15 + number ~$1.15/mo + campaign ~$1.50-$10/mo ≈ **~$20 to start, ~$3-11/mo carrying**.
- **HOT/WARM 1-3k/mo, ~2 segments each (skip-trace numbers + reply handling), Twilio floor ~$0.0083 + ~$0.004 carrier ≈ ~$0.0125/segment:**
  - 1,000 leads × 2 seg = **~$25/mo**
  - 3,000 leads × 2 seg = **~$75/mo**
  - Add number rental/campaign fees → **~$30-$90/mo all-in on raw API.**
- **Whole 17,003 board once** × 2 seg × ~$0.0125 = **~$425 in message cost** (plus you'd need multiple numbers to respect the ~200/number/day cap → ~85 number-days of sending; this is where it stops being a one-shot and becomes a metered drip — and where the TCPA exposure scales linearly with volume).
- **REI-platform path for comparison:** Smarter Contact Pro **$299/mo unlimited** or Launch Control Core **$797/mo** — you're paying for skip-trace + drip + deliverability tooling, not per-message. At 1-3k/mo the raw API is 3-10x cheaper; the platforms only win if you value their built-in list/skip-trace/inbox and accept their (identical) compliance risk.

### Integration path into the engine
- **CSV export → send layer.** The board already produces a scored CSV/dashboard with phone numbers (from the resolver/skip-trace lane). `outreach.py` already generates the message body. The missing piece is the API call.
- **Raw Twilio path (recommended technically):** add a thin `sms_send.py` that reads the HOT/WARM CSV, pulls `outreach.py`'s text, and POSTs to Twilio's Messaging API — with a **hard gate**: a `consent` / `dnc_scrubbed` boolean column that must be true before send, a per-number-per-day counter to respect the ~200/day cap, and immediate STOP-list write-back. This mirrors the existing "budget-bail / rate-limit" patterns already in the scraper stack.
- **REI-platform path:** push the same CSV in via **Zapier/webhook or native CSV import** (Launch Control, Smarter Contact, REI Reply, Batch all take CSV); replies land in their inbox/CRM rather than your dashboard, so you'd lose the single-pane view unless you webhook responses back.
- Either way, wire STOP/opt-out and DNC status back into the board as lead fields so a texted-and-opted-out owner is never re-contacted across channels.

### Recommended pick + why (cheapest credible option)
**Twilio raw API**, wired as a gated `sms_send.py`, is the cheapest credible option — **~$30-$90/mo at 1-3k HOT/WARM**, full REST integration into the existing CSV/dashboard, and no forced subscription for volume you can't legally blast anyway. It keeps the "own your pipeline, pay per real unit" philosophy of the rest of the engine.

But the honest recommendation is to **use SMS narrowly and manually**: reserve it for **inbound/consented leads** (people who responded to a mailer, ad, or web form) and one-at-a-time human texts, not list blasts. If the team wants push-button list texting with skip-trace bundled, **Smarter Contact Pro ($299/mo unlimited)** is the cheapest *vertical* option — but understand you are paying for convenience while inheriting the full, unresolved TCPA/DNC exposure of cold-texting distressed owners. For a free-and-compliant engine, SMS should be the **consented-lead** channel, with cold first-touch carried by lower-risk channels (mail, and manual calls) instead.

Sources:
- [Tuco AI — A2P 10DLC 2026 costs](https://tuco.ai/a2p-10dlc) · [Calilio — 10DLC pricing 2026](https://www.calilio.com/blogs/10dlc-pricing) · [Twilio A2P 10DLC pricing](https://help.twilio.com/articles/1260803965530-What-pricing-and-fees-are-associated-with-the-A2P-10DLC-service-)
- [Twilio US SMS pricing](https://www.twilio.com/en-us/sms/pricing/us) · [CostBench — Twilio 2026](https://costbench.com/software/sms-marketing/twilio/)
- [Launch Control review + pricing 2026](https://www.realestateskills.com/blog/launch-control) · [Smarter Contact review 2026](https://www.realestateskills.com/blog/smarter-contact-review) · [Smarter Contact vs Launch Control](https://smartercontact.com/launch-control-vs-smarter-contact/)
- [SimpleTexting / Textedly pricing 2026](https://www.salesmessage.com/blog/sms-marketing-pricing)
- [11th Cir. vacates one-to-one consent rule — Perkins Coie](https://perkinscoie.com/insights/update/fccs-one-one-consent-rule-vacated-whats-next-tcpa-compliance) · [FCC final rule eliminating one-to-one — CFI](https://www.consumerfinanceinsights.com/2025/09/15/the-fcc-issues-final-rule-formally-eliminating-the-one-to-one-consent-requirement/)
- [NC G.S. 75-102 telephone solicitations](https://www.ncleg.gov/EnactedLegislation/Statutes/PDF/BySection/Chapter_75/GS_75-102.pdf) · [SC Bill 3323 Telephone Solicitation Act](https://www.scstatehouse.gov/sess126_2025-2026/bills/3323.htm) · [NC/SC robocall penalties — Commoner Law](https://commoner-law.com/rights/consumer-rights/robocall-rights/north-carolina)
- [Carrier filtering / trust score / snowshoe limits](https://help.salesmessage.com/en/articles/4979694-a2p-10dlc-faqs) · [CTIA daily limits & carrier blocking](https://talk-q.com/sms-messaging-regulation-in-the-us)


## Ringless Voicemail (RVM)

### Why it matters + where it fits in the funnel
RVM sits at the **top of the outreach funnel**, immediately after a lead is scored HOT/WARM and skip-traced to a phone number. It drops a pre-recorded (or AI-cloned) audio message straight into the seller's voicemail without ringing the phone — a lower-friction, higher-answer-rate touch than a cold call, and one that carries a human voice that raw SMS cannot. For motivated-seller work (probate heirs, elderly owners, absentee landlords, pre-foreclosure) the voice touch outperforms text on the demographic that still listens to voicemail. The realistic role: **first or second touch in a multi-channel sequence** (RVM → SMS → call), where the drop plants your name/number and the inbound callback is the conversion. Do not treat it as a standalone channel; its whole value is generating warm inbound calls that your operator then closes into a contract. Typical callback rates run 1–3% of drops, so at our volume it feeds a handful of live conversations per batch, not a flood.

### Vendors (each: what it does, real 2026 price, integration, "as of 2026, verify")

**Drop Cowboy** — RVM + SMS platform, the most operator-friendly of the group. All-inclusive monthly plans (currently published 2025 rate card, still live in 2026): **Prime $125/mo (~62,762 msgs/yr ≈ 5,200/mo), Large $250/mo (~137K/yr), XL $500/mo (~301K/yr)**. Overage 1.2¢–2.1¢/msg. **BYOC (bring your own carrier) as low as $0.004/drop + carrier fees**, no monthly minimum. A **$0.0031/message compliance fee applies on top of every drop**, and "Mimic" AI voice-clone TTS adds $0.005/100 chars. Unused funds roll over. Integration: **full REST API + CSV upload + UI + Zapier**. As of 2026, verify.

**Slybroadcast** — the incumbent, dead-simple, charged only on delivered drops. **Pay-as-you-go: $10/100 drops ($0.10) scaling to $400/10,000 drops ($0.04). Monthly plans: $8/100 up to ~$500/13,000 drops/mo (~$0.038).** No standalone platform fee — the subscription IS the drop bucket. AI personalization roughly doubles per-drop cost. Integration: **API + CSV/UI**, plus a mobile app; thinner CRM connectors than Drop Cowboy. As of 2026, verify.

**VoiceDrop.ai** — the "AI-native" option, unit/credit-based (1 unit ≈ 150 chars, SMS-style). **Budget $95/mo (1,000 voicemails / 500 units); usage-based tiers $495/mo (6,500 units), Growth $995, Scale $1,995.** Key lever: **static (pre-recorded) RVM costs 0.5 units per drop**, so a $495 plan's 6,500 units = **~13,000 static drops (~$0.038/drop effective)**; AI-personalized drops burn 2–3 units and get expensive fast. Credits expire 90 days. Integration: **strong API + native HubSpot/CRM/Zapier** — the best fit if you want programmatic firing from the engine. As of 2026, verify.

**LeadsRain** — pure pay-as-you-go, cheapest sticker price. **$0.015 per successful drop (1.5¢), charged only on delivery.** DNC scrubbing add-on $0.002/number. Hawaii/Alaska priced separately at $0.20/min. Credits expire 90 days. No monthly platform fee. Integration: **API + CSV/UI**. As of 2026, verify. (Note: 1.5¢ is a headline rate; confirm whether carrier/compliance pass-throughs are added on top — quote-only in practice.)

**Stratics Networks** — flat-rate "unlimited" SaaS model rather than per-drop. **Plans from $99/mo**, marketed as 100% unlimited messaging at one fixed monthly cost; Basic / Professional / Enterprise-White-Label tiers, exact drop caps and per-drop economics are **quote-only** (their own FAQ still quotes the industry 2¢–20¢/drop range). Volume-based custom pricing. Integration: **API + UI**; also sells voice broadcast and SMS. Best only if you scale into tens of thousands of drops where flat-rate beats per-drop. As of 2026, verify.

### Compliance / legal gotchas
This is the channel's real cost, and it is **material** — do not skip.

- **The FCC has ruled RVM is a "call" under the TCPA** (FCC 22-85, in force). A voicemail drop to a wireless number is a prerecorded/artificial-voice call and requires **Prior Express Written Consent (PEWC)** for any marketing message. Cold RVM to a scored-but-non-consented seller list — which is exactly what our engine produces — is **the highest-liability channel of any in this stack.** Statutory damages are **$500–$1,500 per drop**, and TCPA class actions rose ~112% YoY in Q1 2025. A 2,000-drop cold blast is theoretical exposure of $1M–$3M.
- **DNC scrubbing is mandatory.** Scrub every batch against the National DNC Registry (and state DNC lists) before sending; two touches to a registered number in 12 months is a violation. LeadsRain sells scrubbing at $0.002/number — budget it.
- **Revocation:** FCC April 2025 rules let a recipient revoke consent by any reasonable means (STOP, verbal, etc.); the "revoke-all" mandate lands April 2026. You must honor opt-outs and suppress across all channels.
- **State mini-TCPAs stack on top.** 15+ states now enforce mini-TCPAs. **Florida (FTSA), Oklahoma, Washington, and Maryland have no B2B exemption and extend consumer protections broadly** — treat any drop into those states as full-consent-required. Texas SB 140 ties violations to the Deceptive Trade Practices Act (treble damages + attorney fees). This matters less for us geographically (our footprint is **SC + NC**), but note:
  - **SC:** follows the federal TCPA baseline with a state telephone-solicitation statute (SC Code §16-17-445) — prerecorded solicitations to residences are restricted; consent/relationship exemptions mirror federal. No blanket RVM carve-out.
  - **NC:** the NC "no-rings" telephone-solicitation law (NCGS §75-100 et seq.) and Do Not Call provisions apply; prerecorded messages face restrictions and NC AG actively enforces. Neither SC nor NC gives RVM a safe harbor.
- **CAN-SPAM does not apply** (that's email), but keep records: audio content, timestamp, consent basis, and suppression per number.
- **Practical stance for a cold motivated-seller list:** RVM is defensible **only** on numbers where you can argue an established business relationship or hold consent — which a raw foreclosure/probate scrape does not give you. The compliant path is to use RVM **after** first-party opt-in (e.g., a lead who replied to SMS or a web form), not as the cold first touch. If used cold, it should be a deliberate, documented risk decision by the operator, and messages must be identifying, non-deceptive, and honor opt-out.

### Recurring cost at our scale
Target HOT/WARM volume ~1,000–3,000/mo; model the midpoint **2,000 drops/mo** (per the task), and note the whole-17,003 figure. RVM bills on **delivered** drops (~85–90% deliverability), so gross the numbers up ~12% in practice; below uses billed = attempted for a clean comparison.

| Vendor | Per-drop basis | 2,000 drops/mo | Whole board (17,003) |
|---|---|---|---|
| **LeadsRain** | $0.015 + $0.002 DNC scrub | ~$34/mo ($30 drops + $4 scrub) | ~$289/mo one-time-style blast |
| **VoiceDrop.ai** (static, 0.5 unit) | $495/mo = 6,500 units ≈ 13,000 static drops | $495/mo (huge headroom) | covered inside $495/mo |
| **Slybroadcast** | ~$0.04 PAYG at volume | ~$80/mo | ~$680 |
| **Drop Cowboy** (monthly + compliance) | Prime $125/mo covers ~5,200/mo, +$0.0031/msg compliance | ~$125/mo + ~$6 compliance ≈ **$131/mo** | covered by Prime (17K < 62K/yr cap) at $125/mo + ~$53 compliance |
| **Drop Cowboy BYOC** | $0.004 + $0.0031 compliance + carrier | ~$14–20/mo + carrier fees | ~$120–170 + carrier |
| **Stratics** | flat "unlimited" | from $99/mo (quote-only) | $99/mo flat |

At 2,000/mo, **LeadsRain (~$34) and Drop Cowboy BYOC (~$15–20 + carrier) are the cheapest**; Drop Cowboy Prime (~$131) buys convenience and headroom to 5,200/mo. The whole-17K board is cheap to blast on any of them (**$120–$680**) — cost is not the constraint here, **TCPA exposure is.** Add ~$0.002/number for DNC scrubbing across all vendors if not bundled (~$4/mo at 2K, ~$34 for the full board).

### Integration path into the engine
1. **CSV export → drop list.** The engine already exports scored leads; add an RVM-ready view filtered to HOT/WARM with a **valid, DNC-scrubbed, consent-flagged mobile number** and columns `[phone, first_name, property_address, campaign_id]`. Every vendor ingests CSV via UI as the zero-code path.
2. **API firing (preferred).** `outreach.py` already generates content; add a `send_rvm()` adapter that POSTs the scrubbed list + an audio asset URL to the vendor API. **VoiceDrop.ai or Drop Cowboy** have the cleanest REST APIs for this; wire the adapter behind the same interface as the SMS/email senders so the operator triggers one "run outreach" step.
3. **Suppression + callback loop.** Maintain a single cross-channel `suppression` table (opt-outs, DNC hits, bad numbers) the RVM adapter reads before every send. Pipe delivery/callback webhooks back to the lead record so a callback flips the lead to a "contacted / engaged" stage on the dashboard — the callback is the conversion event this whole channel exists to produce.
4. **Consent gate.** Add a hard pre-send check: only fire RVM on rows where `consent_basis` is populated (form opt-in, prior SMS reply, or documented EBR). Cold rows route to a compliant first touch instead.

### Recommended pick + why
**LeadsRain** for cold/low-commitment sending, **VoiceDrop.ai** if you want the drops fired programmatically from the engine.

- **Cheapest credible option: LeadsRain at $0.015/drop, pay-as-you-go, no monthly fee, delivered-only billing, built-in $0.002 DNC scrub.** At 2,000 drops/mo that's ~$34 all-in, and the whole 17K board is ~$289 — the lowest true cost with a real API and no subscription lock-in. It's the right pick while volume is spiky and you're proving the channel.
- **Scale/automation upgrade: VoiceDrop.ai $495/mo.** Its 0.5-unit static-RVM pricing yields ~13,000 drops inside the base plan (~$0.038 effective) with the best native API/CRM integration, so once you're consistently firing from `outreach.py` and want callback webhooks wired to the dashboard, it's the cleanest programmatic home. Below ~10K drops/mo, LeadsRain is cheaper; above it, VoiceDrop's plan economics win.

Skip Stratics (quote-only, flat-rate only pays off at high volume) and treat Slybroadcast as a fallback (simple but pricier per drop and thinner integrations). **Whichever you pick, the binding constraint is not price — it is TCPA consent.** Budget the DNC scrub, gate sends on documented consent, and use RVM as a warm follow-up rather than the cold first touch.

Sources: [Drop Cowboy pricing](https://www.dropcowboy.com/messaging-pricing) · [Slybroadcast pricing](https://prospeo.io/s/slybroadcast-pricing-reviews-pros-and-cons) · [VoiceDrop.ai pricing](https://www.voicedrop.ai/pricing/) · [LeadsRain pricing](https://leadsrain.com/ringless-voicemail-price) · [Stratics Networks (Capterra)](https://www.capterra.com/p/155761/Stratics-Networks/) · [FCC ruling: RVM is a call under TCPA](https://www.fcc.gov/document/fcc-finds-ringless-voicemails-are-subject-robocalling-rules) · [2026 TCPA/state-law guide](https://blog.clickpointsoftware.com/tcpa-one-to-one-consent-can-spam-state-regulations) · [AI voicemail legal 2026](https://www.jeeva.ai/blog/ai-voicemail-legal-2026-tcpa-guide)


## Outbound Dialers (Power / Predictive)

### Why it matters + where it fits in the funnel

This is the highest-conversion contact channel for distressed-seller outreach and the single biggest labor bottleneck. Your pipeline scores and enriches leads with phone numbers; the dialer is what turns a row in the CSV into a live human conversation. It sits at the **top-of-funnel contact step** — right after `outreach.py` generates the script/talking points, and right before a CRM logs the disposition. A manual, one-at-a-time cell phone is ~40–60 dials/hour; a power/predictive dialer pushes one operator to 150–300+ dials/hour, so this channel is what lets a single operator actually work the 1–3k HOT/WARM subset every month instead of a few hundred. For motivated-seller (foreclosure/probate/tax-delinquent) lists, phone is where the deal actually gets negotiated — SMS/RVM/mail warm the lead, the call closes the appointment.

### Vendors

- **Mojo Dialer** — Purpose-built for real estate / investor cold calling; copper-line-backed dialer prized for connection quality and lowest dropped-call reputation. Single-Line ~85 calls/hr, Triple-Line ~300 calls/hr. **2026 price:** required **Agent Access $10/user/mo**, plus **Single-Line $89/license/mo** or **Triple-Line $139/license/mo** (so **$99 or $149/mo all-in** for one seat). **Unlimited minutes included** (no per-minute charge). Add-ons: Mojo Voice $30/mo, call recording $25/mo, skip-trace $49/mo unlimited, data feeds $25–$50 each. **Integration:** CSV import (native), plus a documented API and Zapier; UI-driven calling. *As of 2026, verify.*
- **BatchDialer** — Investor/wholesaler-focused with built-in spam/reputation monitoring and DNC + litigator scrubbing on every plan; tight sibling of BatchLeads. **2026 price (repriced Mar 12 2026):** **Starter $119/agent/mo** (10 numbers), **Pro $189/agent/mo** (Smart Local Presence + auto number replacement + AI coaching/summaries), Enterprise = quote-only. Predictive + preview dialing all tiers; unlimited calling; extra numbers $2 each. **Integration:** API + CSV + native BatchLeads sync. *As of 2026, verify.*
- **PhoneBurner** — Single-line **power** dialer positioned explicitly as *not an ATDS* (agent on the line from first ring, human-initiated). Best compliance story of the group for cold cells. **2026 price:** **Standard $165/user/mo** ($140 annual), Professional $195 ($165 annual), Premium $215 ($183 annual). SMS capped 1,000/mo then $15 per 1,000; Numbers/ARMOR (spam-remediation)/Connect Scores are quote-only add-ons. **Integration:** strong REST API, native CRM + Zapier, CSV import. UI + API. *As of 2026, verify.*
- **CallTools** — Cloud predictive/power dialer, unlimited minutes, does not publish pricing. **2026 price:** roughly **$102/user/mo annual, ~$120/user/mo month-to-month** per aggregator data; setup fees $500–$1,500 reported, SMS ~$0.015/msg, complex CRM integration surcharges $2,000–$5,000. **Integration:** API + CSV; quote-only. *As of 2026, verify — get an all-in quote at your real volume.*
- **ReadyMode (formerly XenCall)** — Call-center-grade predictive dialer with built-in CRM; built for multi-seat floors, heavier than a 1-operator shop needs. **2026 price:** **Starter ~$125/license/mo annual ($150 monthly)**, iQ tier ~$199–$249/user; setup fee $500–$2,000. **Integration:** API + CSV; UI-heavy. *As of 2026, verify.* (XenCall is the legacy name — same product.)
- **REISift-adjacent note** — REISift itself is a lead-management/list-stacking CRM, **not a dialer**; it feeds cleaned/skip-traced lists *into* the dialers above (commonly Mojo/BatchDialer/PhoneBurner). Treat it as an upstream data layer, not an outbound channel.

### Compliance / legal gotchas (be concrete)

- **ATDS / manual-dial is the whole ballgame for cold cells.** Under *Facebook v. Duguid*, an ATDS must use a random/sequential number generator. Calling a **known distressed-owner number from your list is not random/sequential**, so a **power dialer with an agent live on the line (PhoneBurner, Mojo single-line, preview mode)** is the defensible posture for cold cells without prior express written consent. **Predictive/multi-line auto-dialing** (BatchDialer/CallTools/ReadyMode predictive, Mojo triple-line) raises "human intervention" questions and the dropped-call / abandonment rules — safer for numbers you have consent for or for landlines. For your HOT/WARM cold cells, **run in single-line/preview/manual mode.**
- **Federal DNC.** Scrub against the National DNC Registry **every 31 days**; calling a registered number without an EBR or consent is a per-call violation. Litigator scrubbing (BatchDialer bundles it; others via add-on) matters because TCPA plaintiffs seed these lists.
- **Calling hours:** 8am–9pm **called party's local time** (federal). NC/SC both mirror this.
- **South Carolina (Telephone Privacy Protection Act, T37 Ch.21):** prohibits automated-system dialing / recorded messages without prior express written consent; honor internal opt-outs **5 years**; must ID yourself + give callback number. **Real-estate-licensee carve-out exists** — a SC-licensed broker/agent/property manager soliciting within license scope has room a non-licensed investor does not. If your operator isn't licensed, don't lean on it.
- **North Carolina (G.S. 75-102 et seq.):** private right of action with **statutory damages $500 / $1,000 / $5,000** per violation escalating; mandatory internal-DNC written procedures, training, and honoring do-not-call requests.
- **RVM (ringless voicemail):** FCC classifies RVM to a wireless number as a "call" — **needs the same consent as an autodialed call**, so RVM to cold cells is **not** a compliance shortcut. Not banned outright in NC/SC, but FL/OK mini-TCPAs treat it as a call and IL/IN/PA restrict it for debt-collection contexts. Keep RVM off your cold-cell cadence unless you have consent.
- **10DLC:** only relevant to the SMS features bolted onto these dialers, not the voice channel — but if you enable dialer-SMS you must register a 10DLC brand/campaign or carriers filter you.
- **The 2026 shift:** the FCC "one-to-one consent" / lead-generator-loophole rule was **vacated by the 11th Circuit (Jan 2025)**, so the pre-existing prior-express-written-consent standard still governs — no new consent burden landed, but don't rely on purchased "consented" lead consent transferring to you.

### Recurring cost at our scale (1 operator, 1–3k HOT/WARM/mo)

One operator can only dial one line at a time, so **scale is one seat, not one-seat-per-lead** — 1–3k dials/mo is comfortably one seat's monthly throughput (a single operator does 2–4k+ dials/mo at power-dialer speed).

- **Mojo single-line, all-in:** $99/mo (Agent Access $10 + Single-Line $89) + $49 skip-trace if used = **~$99–$150/mo**. Triple-line if you want raw speed on landline-heavy batches: **$149/mo**.
- **PhoneBurner Standard (annual):** **$140/mo** — cleanest compliance for cold cells.
- **BatchDialer Pro:** **$189/mo** (spam remediation + local presence baked in).
- **CallTools / ReadyMode:** **~$102–$150/mo** base but quote-gated with $500–$2,000 setup — overkill for one seat.

**Working the whole 17,003-lead board:** still **one seat** — it's the same monthly subscription (~$100–$190/mo), you just spread the 17k across ~4–8 months of dialing or add a second seat to parallelize. A **second operator seat roughly doubles the line item** (dialers charge per concurrent seat/license), e.g. two Mojo single-line seats ≈ $198/mo, two PhoneBurner ≈ $280/mo. **There is no per-lead or per-minute meter on the recommended tools — unlimited minutes — so cost is flat per seat regardless of whether you dial 1k or 3k.** Budget line-item: **~$100–$190/mo for the channel.**

### Integration path into the engine

1. **CSV export is the universal on-ramp** — every vendor here ingests a CSV. Add a dialer-shaped export from the dashboard: `first_name, last_name, phone, property_address, lead_source, score_tier, equity, notes` (map notes to the `outreach.py`-generated script/talking points). Mojo/BatchDialer/PhoneBurner all map these columns in their UI import.
2. **HOT/WARM filter at export** so the operator only loads the actionable subset, not all 17k.
3. **Disposition round-trip:** PhoneBurner and BatchDialer expose REST APIs — pull call dispositions (no-answer / callback / appointment / DNC) back into the lead record so a called lead doesn't get re-dialed and DNC requests write back to your suppression list. Mojo/CallTools/ReadyMode do this via API or CSV re-import.
4. **Suppression sync (required, not optional):** maintain a master DNC/opt-out table in the engine; export it into the dialer's internal DNC before every batch, and import dispositions after. This is what keeps the NC $500–$5,000 exposure off you.
5. Keep skip-trace **upstream in the pipeline** (you already flag absentee owners / have contact enrichment) rather than paying Mojo's $49/mo skip-trace, unless you need it as a gap-filler.

### Recommended pick + why (cheapest credible option)

**Mojo Dialer, Single-Line, at $99/mo all-in** is the cheapest credible pick for one operator working cold distressed-seller cells. Reasons: (1) lowest true cost with **unlimited minutes and no metered per-minute/per-lead charge**, so 1–3k or the full 17k costs the same flat seat; (2) **single-line = agent-on-the-line power dialing**, the defensible non-ATDS posture for cold cells in NC/SC; (3) copper-backed line quality means fewer spam-flagged/dropped calls, which directly protects contact rate on a list you can't easily re-scrape; (4) native CSV import matches your export with zero integration spend.

**One caveat / close runner-up:** if spam-flagging of your outbound numbers becomes the bottleneck (common at 2–3k dials/mo from one number), **BatchDialer Pro at $189/mo** bundles spam-reputation monitoring, Smart Local Presence, and automatic number replacement that Mojo charges extra for — pay the ~$90/mo premium only once answer rates drop. For the **strictest cold-cell compliance narrative**, **PhoneBurner Standard at $140/mo annual** (explicitly marketed as not-an-ATDS, single-line human-initiated) is the safest choice if a licensed-broker carve-out isn't available to your operator.

Sources: [Mojo pricing (Ringover)](https://www.ringover.com/blog/mojo-dialer-pricing), [Mojo pricing/skip-trace (REsimpli)](https://resimpli.com/blog/mojo-dialer-pricing/), [BatchDialer pricing](https://batchdialer.com/pricing), [BatchDialer 2026 repricing (REsimpli)](https://resimpli.com/blog/batchdialer-pricing/), [PhoneBurner pricing](https://www.phoneburner.com/pricing), [PhoneBurner TCPA/not-autodialer](https://www.phoneburner.com/homepage/sales-terminology/tcpa-compliance), [CallTools pricing (ITQlick)](https://www.itqlick.com/calltools/pricing), [ReadyMode/XenCall pricing (CloudTalk)](https://www.cloudtalk.io/blog/readymode-pricing/), [TCPA autodialer/manual-dial (ActiveProspect)](https://activeprospect.com/blog/tcpa-autodialer/), [Ringless voicemail rules 2026 (LeadCompliant)](https://leadcompliant.com/articles/tcpa-compliance/tcpa-ringless-voicemail-rules-2026), [SC Telephone Privacy Protection Act](https://www.scstatehouse.gov/code/t37c021.php), [NC G.S. 75-102](https://www.ncleg.gov/EnactedLegislation/Statutes/PDF/BySection/Chapter_75/GS_75-102.pdf)


## DNC / Litigator / TCPA Scrub

### Why it matters + where it fits in the funnel
This is the compliance gate that sits **between the scored lead and every phone touch** (SMS, RVM, cold call). Motivated-seller data — foreclosure defendants, probate heirs, tax-delinquent owners — is skip-traced to cell numbers, and cell numbers are exactly where TCPA liability lives. A single number on the federal DNC or, worse, belonging to a serial TCPA plaintiff is a $500–$1,500 statutory-damages event per call/text (trebled to $1,500 for willful), and professional litigators farm distressed-property outreach specifically because wholesalers text first and check later. Scrub runs **after** the CSV export / skip-trace step and **before** the number is written back to the CRM as "dialable." It is not optional infrastructure — one plaintiff who receives 3 texts is a $4,500 claim, which dwarfs the entire annual scrub budget. Numbers must be re-scrubbed continuously because the registry updates daily and the safe-harbor clock is 31 days (see below).

### Vendors

- **DoNotCallDNC (donotcalldnc.com)** — Web UI + API scrub against National DNC, state DNC, and internal suppression. **Real 2026 price:** pay-per-scrub $0.00070/number (1–50k band) sliding to $0.00058 at 2M+, $15 minimum; OR unlimited plans at **$69/mo (annual), $99/mo (6-mo), $149/mo (quarterly), $199/mo month-to-month**, unlimited plan includes full API. Integration = **API + CSV/UI**. *Note: strong on DNC/wireless/suppression; litigator coverage is thinner than the dedicated litigator vendors.* (as of 2026, verify)
- **RingScrub (ringscrub.com)** — Bundled scrub + inbound litigator call-filtering. **Real 2026 price:** Package A **$150/mo = 200k rows**, Package B **$300/mo = 2M rows**, Package C **$700/mo = 10M rows**; overage $20/100k (A). **TCPA Litigator List is included free with any A/B/C package** (or $130/mo standalone). Integration = **UI + custom lists**; API on higher tiers. (as of 2026, verify)
- **TextP2P (textp2p.com)** — Scrub feature inside an SMS platform (relevant if you also buy their sending). **Real 2026 price:** **$0.01/number, $5.00 minimum**, covers TCPA litigator + Federal DNC + your suppression list, database updated daily, results emailed. Integration = **UI-only inside TextP2P** (no standalone scrub API). Cheapest to start, most expensive per-unit at volume. (as of 2026, verify)
- **TCPA Litigator List (tcpalitigatorlist.com)** — The dedicated serial-plaintiff / "troll" database, plus Federal DNC + suppression via a "scrub coin" model (1 coin = 1 number). **Real 2026 price:** Monthly — Basic **$199/mo (200k coins)**, API Silver **$299/mo (300k)**, API Gold **$499/mo (500k)**, API Platinum **$799/mo (1M)**; Annual — Basic **$2,029/yr (2.4M coins)**, API Gold **$4,191/yr (6M)**. Overage $0.0006–$0.002/scrub. Single-number lookups also sold à la carte. Integration = **real-time API (Silver+) or CSV/UI (Basic)**. This is the strongest litigator-specific coverage per dollar. (as of 2026, verify)
- **Blacklist Alliance (tcpablacklist.com)** — Proprietary continuously-updated litigator/serial-plaintiff DB + DNC + "litigation firewall" + caller-ID reputation; ~1,000 calling-industry clients. **Real 2026 price: quote-only** (plans scale by team size and call volume; single-number and bulk CSV both supported). Integration = **API + UI**. Premium/enterprise positioning — likely overkill and over-budget for 1–3k/mo. (quote-only, as of 2026, verify)
- **Contact Center Compliance — DNCScrub / DNC.com litigator scrub** — Enterprise standard; matches every number against real litigator case files (claims 70B+ scrubs, "zero client violations"). **Real 2026 price: quote-only** (tiered by record volume, monthly recurring + one-time options; **requires a separate active National DNC Registry subscription** to run federal scrubs). Integration = **API + UI + dialer marketplace integrations (e.g., Five9)**. Enterprise-priced. (quote-only, as of 2026, verify)
- **Gryphon (gryphon.ai / Gryphon ONE)** — Fully managed GRC/contact-governance platform (real-time in-line DNC/consent enforcement at dial time, not batch scrub). **Real 2026 price:** ~**$50/user/mo** with volume discounts (10 users ≈ $450/mo) + **$1,000–$5,000 implementation**. Integration = **deep dialer/CRM integration, API**. Built for large managed call centers — wrong shape and price for a lean wholesaler. (as of 2026, verify)

*Underlying government cost (applies to whichever DNC-scrub vendor you use):* the **FTC National DNC Registry** subscription is a separate required fee for federal-list access — **FY2026 = $82/area code**, first **5 area codes free**, nationwide cap **$22,626/yr**. Upstate SC + Western NC spans roughly **10–15 area-code-relevant regions but only ~4 actual area codes (803/864 SC, 828/704 NC)** — so your footprint sits **at or near the 5 free area codes → likely $0–$82/yr** in direct FTC fees. Some vendors bundle/resell this; confirm whether the quote includes registry access.

### Compliance / legal gotchas (be concrete)
- **The 31-day rule = safe harbor, not best practice.** FTC requires you access DNC data no more than **31 days** before a call/text; an older scrub forfeits the safe-harbor defense. Because the registry updates *daily*, **re-scrub immediately before every send**, not monthly. A number scrubbed clean 25 days ago can now be a $1,500 claim.
- **Litigator scrub is separate from DNC scrub.** The federal DNC list does NOT contain serial plaintiffs; a number can be off-DNC and still belong to a professional litigator. You need **both** a DNC pass and a litigator pass. Litigators drive ~⅓ of TCPA suits and target distressed-property texters.
- **TCPA damages:** $500/violation, up to **$1,500 for willful**, per call or text, no cap, private right of action. Three texts to one plaintiff = $4,500.
- **Ringless voicemail (RVM) is a "call"** under the 2022 FCC ruling — requires prior express (written, if marketing) consent. Cold RVM to skip-traced sellers is effectively unusable without consent; do not treat RVM as a DNC-scrub workaround.
- **10DLC:** any A2P SMS to these numbers must run on a registered 10DLC brand/campaign (carrier layer, separate from scrub) — scrub does not exempt you from carrier registration.
- **CAN-SPAM** governs email only; irrelevant to phone scrub but relevant if you add an email channel (must honor opt-outs, include physical address).
- **South Carolina — Telephone Privacy Protection Act (Title 37, Ch. 21):** **$1,000/violation private right of action**, up to **$5,000 for willful**; requires **prior express written consent** for automated/recorded commercial solicitation calls **and texts**. There **is a licensed-real-estate-professional exemption**, but it covers licensed brokers/agents acting within their license — **an unlicensed wholesaler does NOT reliably qualify.** Treat SC as strict-liability territory: scrub against SC state DNC + litigators every time.
- **North Carolina — G.S. 75-102 et seq.:** bans unsolicited "telephone solicitations" (defined to include **text**) to numbers on the DNC registry, with a private right of action. **Brokers may text/call without prior written consent** *only if* no random/sequential dialer, no prerecorded/artificial voice, and DNC rules are followed — again a **licensed-broker** carve-out, not a wholesaler shield. Manually-sent, one-to-one, non-autodialed texts to non-DNC numbers are the compliant lane.
- **Practical takeaway for a wholesaler:** you likely can't rely on the real-estate exemptions in either state, so the scrub stack (Federal DNC + SC/NC state DNC + litigator + your own suppression/opt-out list) is the *entire* legal defense. Log every scrub result with a timestamp for the safe-harbor paper trail.

### Recurring cost at our scale
Assume **2,000–3,000 HOT/WARM numbers/mo**, re-scrubbed before each send (budget ~1 scrub pass/number/mo; heavy campaigns may re-scrub weekly → 2–4×).

| Vendor | 3,000/mo, 1 pass | If re-scrubbed weekly (~12k scrubs/mo) | Whole 17,003 list, 1 pass |
|---|---|---|---|
| **DoNotCallDNC** unlimited annual | **$69/mo flat** | $69/mo flat | $69/mo flat (unlimited) |
| DoNotCallDNC pay-per-scrub | 3,000 × $0.0007 = $2.10 → **$15 min** | 12k × $0.0007 = **$15 min** | 17,003 × $0.0007 = **$15 min** |
| **TextP2P** $0.01 + $5 min | 3,000 × $0.01 = **$30/mo** | 12k × $0.01 = **$120/mo** | 17,003 × $0.01 = **$170** |
| **TCPA Litigator List** Basic | **$199/mo** (200k coins, wildly over-provisioned) | $199/mo | $199/mo |
| **RingScrub** Pkg A | **$150/mo** (200k rows, litigator incl.) | $150/mo | $150/mo |

Litigator coverage is the cost driver: the pure-DNC scrubbers (DoNotCallDNC) are effectively free at this volume, but **you still must pay for a litigator pass.** The cheapest credible *litigator-inclusive* number is **RingScrub Pkg A at $150/mo** (litigator list bundled free, 200k rows covers you even at weekly re-scrub of the whole 17k). TextP2P is cheapest raw ($30/mo) but is UI-only and locks you into their sender.

### Integration path into the engine
The scrub step is a **filter transform between skip-trace and CRM write-back**:
1. Pipeline emits the HOT/WARM CSV with skip-traced phone columns (already exists).
2. New `scrub.py` module POSTs the phone array to the vendor **API** (DoNotCallDNC or TCPA Litigator List API tier), or, for UI-only vendors (TextP2P/RingScrub), uploads the CSV and ingests the returned results file.
3. Response flags each number: `dnc_federal`, `dnc_state`, `litigator`, `wireless`, `clean` → merge back onto the lead row.
4. **Only `clean` numbers get written to the dashboard/CRM as `dialable=true`;** flagged numbers are suppressed with the reason + a **scrub timestamp** (needed for 31-day safe-harbor logging). Maintain a persistent local **suppression/opt-out table** that is unioned into every scrub so you never re-contact an opt-out.
5. Because leads persist and auto-enrich, add a **`scrubbed_at` staleness check** — any number older than ~7 days (well inside the 31-day ceiling) is re-scrubbed on the next run before it can be surfaced as dialable. API-based vendors (DoNotCallDNC unlimited, TCPA Litigator List Silver) fit this automated cadence; UI-only vendors force a manual step and break the "sending is the gap" goal.

### Recommended pick + why
**Primary: DoNotCallDNC unlimited annual ($69/mo, full API) for the DNC/state/wireless/suppression pass, paired with TCPA Litigator List Basic ($199/mo) — or, to consolidate, RingScrub Package A ($150/mo, litigator list bundled).**

- If you want the **single cheapest fully-API automated stack**: **DoNotCallDNC unlimited ($69/mo)** handles Federal + state DNC + wireless + suppression via API at unlimited volume (covers all 17k trivially), and it's the only vendor whose flat rate doesn't punish re-scrubbing. Add a litigator pass on top.
- If you want **one vendor, litigator included, minimal ops**: **RingScrub Package A at $150/mo** — 200k rows/mo (10×+ headroom for weekly re-scrubs of the whole board) with the TCPA Litigator List bundled at no extra cost. Best value for the litigator-inclusive requirement.
- **Avoid** Blacklist Alliance / DNCScrub / Gryphon at this stage — all quote-only or enterprise-priced (Gryphon ~$450/mo + $1k–$5k implementation) and built for managed call centers, not a lean wholesaler doing 3k numbers/mo.

**Net recommendation: run DoNotCallDNC unlimited ($69/mo) + TCPA Litigator List Basic ($199/mo) = $268/mo for a fully-API, litigator-aware, re-scrub-on-every-send stack; or RingScrub Pkg A ($150/mo) alone if you'll tolerate a lighter API and want one invoice.** Either way the whole-year cost is under ~$3,200 — trivially cheaper than a single $4,500 three-text plaintiff claim, which is why this gap is existential. Add the FTC registry subscription only if your vendor doesn't bundle it; your 803/864/828/704 footprint likely sits within the 5 free area codes ($0–$82/yr).


## CRM / Disposition + Cash-Buyer Sourcing

### Why it matters + where it fits in the funnel
The pipeline scores and ranks leads; `outreach.py` generates the message. Everything *after* "seller says yes" is currently manual. This channel owns the back half of the funnel: (1) an **acquisition CRM** to hold the ~1-3k HOT/WARM leads/mo, track status (New → Contacted → Appointment → Contract), automate follow-up, and route dials/texts/e-sign; and (2) **disposition** — the moment you have a property under contract, you assign it to a cash buyer. A deal is only worth money once it's *sold*. Most solo operators lose their spread because they can contract a house but have no vetted buyer to flip it to. The unfair advantage here is that **we already parse ROD deed data**, which is the exact raw material a $99/mo tool like PropStream sells back to you: recent all-cash grantees. We can build the buyer list for $0 and only pay for a CRM to run the process.

### Vendors

**Part A — Acquisition CRM / Disposition (pipeline, dispo, dialer, e-sign)**

- **REsimpli** — All-in-one investor CRM (built for this exact use case: motivated-seller pipeline, list stacking, driving-for-dollars, built-in dialer/SMS/RVM, direct mail, KPI dashboards, and a **built-in "Dispo" feature to blast deals to your buyer list**). **2026 price:** Basic **$149/mo** (1 user), Pro **$299/mo** (5 users), Enterprise **$599/mo** (unlimited users, advanced dialing); ~29% off annual; 30-day free trial, $0 setup. Calling/SMS/mail are usage-metered on top. **Integration: API + CSV import + UI.** (*as of 2026, verify*)
- **InvestorFuse** — Workflow-first investor CRM (lead-action based; owned by Carrot). **2026 price:** Essentials **$147/mo** (1 user), Pro **$247/mo** (5 users), Premium Beta **$377/mo** (10 users); additional users **$20/mo** each; 15% annual savings. No built-in phone system — you bring Twilio/CallRail. **Integration: API + CSV + Zapier.** (*as of 2026, verify*)
- **Podio + GlobiFlow (Citrix Podio)** — The DIY route. Podio itself is cheap (free up to 5 users; paid tiers historically ~$14-$24/user/mo) but useless for REI until you buy a prebuilt investor template + GlobiFlow automation + Twilio. **Real all-in cost lands ~$250+/mo** after customization, plus your build time. **Integration: full API, but you're the integrator.** Only worth it if you want total control. (*as of 2026, verify — Podio's own roadmap has been shaky, factor platform risk*)
- **FreedomSoft** — All-in-one (CRM + lead gen + list pulling + websites + comping + e-sign). **2026 price:** Start (annual) **$147/mo**, Basic **$197/mo**, Grow **$297/mo** (8 users), Scale **$497/mo** (12 users); phone numbers + lead downloads bundled per tier. **Integration: API + CSV.** (*as of 2026, verify*)
- **Forefront CRM** — Lightweight investor CRM focused on follow-up sequences + "seller-scoring." **2026 price:** Starter **$99/mo** (5 phone #s, 500 min, 500 SMS), Pro **$199/mo** (6 users), Elite **$299/mo** (20 users); 75% off first month; overage à la carte. **Cheapest all-in-one with a built-in phone system.** **Integration: API + CSV + Zapier.** (*as of 2026, verify*)
- **Follow Up Boss** — Best-in-class CRM *engine* (speed-to-lead, dialer, routing) but built for retail agents, not investor dispo. **2026 price:** Grow **$69/user/mo** (calling add-on +$39/user/mo), Pro **$499/mo** (10 users, unlimited calling), Platform **$1,000/mo** (30 users). No native contract/dispo tooling. **Integration: excellent open API + Zapier.** Overkill/mis-fit for a 1-2 person shop. (*as of 2026, verify*)
- **E-sign layer (if your CRM lacks it):** **DocuSign** Real Estate ~**$45/mo** (envelope-metered) or Personal **$15/mo** (5 envelopes/mo); **Dotloop** **$29/user/mo** Plus / **$49** Pro — **unlimited loops/signatures, no per-envelope fee** = cheaper for deal volume. REsimpli/FreedomSoft include e-sign, so this is only a line item if you pick InvestorFuse/Forefront/Podio. (*as of 2026, verify*)

**Part B — Cash-Buyer Sourcing (build the list to assign to)**

- **FREE — our own ROD deed data (the recommended primary):** We already parse recorded deeds. A **cash buyer = a grantee on a recent deed with no accompanying deed-of-trust/mortgage recorded** (arms-length purchase, no lien = paid cash). Filter our parsed ROD index for the last 12-24 months where `grantee` appears with **no matching mortgage instrument**, then rank by **repeat-grantee count** (an LLC/name on 3+ cash deeds = an active investor/landlord = your best buyer). This reproduces exactly what PropStream's "Cash Buyers" lead list sells. Grantee names → run through the **SoS registered-agent enricher** (already built) and free skip-trace flag to get contact info. **Cost: $0, integration: native — it's a new query over data we hold.**
- **PropStream** — Paid cash-buyer search (Lead List → "Cash Buyers," stackable with 160+ filters: equity, LTV, # properties, non-owner-occupied; in-app skip trace with DNC scrub). **2026 price:** **$99/mo** Essentials (25k saves/exports); skip trace + direct mail metered on top (~$0.12/record). **Integration: UI + CSV export; no true open API on base plan.** Good as a *cross-check* against our free list. (*as of 2026, verify*)
- **BatchLeads** — List building + cash-buyer/skip-trace credits. **2026 price:** Growth **$71-$119/mo**, Professional **$209/mo**, Scale **$449/mo**; skip credits bundled per tier. **Integration: API + CSV.** (*as of 2026, verify*)
- **DealMachine** — D4D + cash-buyer lists with **unlimited skip tracing included** (no per-lookup fee — its standout). **2026 price:** Starter **$99/mo** (20k leads), Pro **$149/mo** (3 users, 60k leads). **Integration: API + CSV.** (*as of 2026, verify*)

### Compliance / legal gotchas
- **SC wholesaling is now regulated (this is the big one).** SC Code **§40-57-30(44)** (new RE license law) defines "wholesaling" as contracting to buy residential real estate then **marketing the *property*** to another buyer before you own it — and **that is prohibited without a license.** What's still legal: **assigning (or offering to assign) your *contractual right***, as long as you market **the contract position, not the property.** Practical rule for disposition messaging to buyers: advertise "**I have a contract/equitable interest to assign**," never "house for sale." The SC LLR published explicit [Wholesaling & Assignment guidance](https://llr.sc.gov/re/News/Wholesaling-Assignment-of-Contracts-Guidance.pdf) — read it before any dispo blast. Disclose your role and equitable interest in writing. (*as of 2026, verify current LLR guidance*)
- **NC:** Assigning contracts is legal; **brokering (marketing property you don't own for a fee) without a license is the line.** NCREC treats marketing the property vs. assigning the contract the same way SC now does — keep buyer-facing copy on the *contract*.
- **TCPA / DNC (applies when you dispo by phone/text to buyers):** cash-buyer numbers you skip-trace are cold B2B/consumer contacts. Scrub against the **National DNC Registry** before dialing (PropStream/REsimpli do this in-app), honor opt-outs, respect 8am-9pm local calling windows, and for SMS you need **10DLC brand/campaign registration** (~$4/mo + one-time ~$4-$44 vetting via your CRM's carrier). The 2024-25 FCC one-to-one consent rule tightened express written consent for autodialed marketing — buyer dispo texts to purchased lists are the riskiest; prefer **manual/one-to-one first-touch** to a buyer, then they opt in.
- **RVM (ringless voicemail):** FCC treats RVM as a "call" under TCPA — same consent rules; several state AGs are hostile. Use sparingly to buyers you have a relationship with.
- **CAN-SPAM (email dispo blasts):** legit physical address in every email, honest subject line, working one-click unsubscribe honored within 10 business days.

### Recurring cost at our scale
The CRM is a **flat seat cost, not per-lead** — 1-3k HOT/WARM/mo sits comfortably inside any of these plans, and even the whole 17,003-lead board is just a bigger import (watch only the *dialer/SMS usage* and *skip-trace* meters, which scale with contacts *actioned*, not stored).

- **Recommended stack cost:** **Forefront CRM Starter $99/mo** (or REsimpli Basic $149/mo) = the CRM + built-in phone.
- **Cash-buyer list: $0** (built from our ROD data). Optional PropStream cross-check **$99/mo** if you want a second source in month one, then cancel.
- **Skip-trace on buyers:** only skip the ~50-200 *repeat* cash grantees you actually want to reach, not all 17k — at ~$0.12/record that's **~$6-$24 one-time**, or **$0** if you use DealMachine's unlimited skip within its $99 plan.
- **All-in monthly: ~$99-$149** for the CRM + phone, **+$0** for the buyer list. Whole-17k board changes nothing about the subscription — only add metered SMS/dial cost when you mass-contact, and 10DLC (~$4/mo) if you text.

### Integration path into the engine
1. **CSV export from the dashboard → CRM import.** Every CRM above ingests CSV. Map our board columns (address, owner, equity, ARV, max-bid, grade, source) to CRM lead fields; push **HOT/WARM** on a schedule. REsimpli/BatchLeads/DealMachine/Follow Up Boss also expose a **REST API** so a cron job can `POST` new-scored leads straight into the pipeline with tags (`hot`, `sc`, `probate`, etc.) — no manual upload.
2. **Status write-back (optional):** poll the CRM API for `status=Under Contract` and flip a flag on our board so the disposition query fires.
3. **Buyer-list module (net-new, free):** add a script that queries the parsed ROD index for **cash grantees (deed w/ no mortgage) in the last 18 mo**, aggregates by grantee name, ranks by deed count, enriches via the existing SoS agent + skip-trace flag, and writes a `cash_buyers` sidecar / CSV. That CSV loads into the **same CRM as a separate "Buyers" list/tag**, so when a property goes under contract you filter buyers by county + property type and blast the assignment. This reuses `load_board`/`web_artifact` and the SoS enricher already in the repo.

### Recommended pick + why (cheapest credible option)
**Forefront CRM Starter ($99/mo) as the CRM + a free ROD-derived cash-buyer list.** It's the cheapest all-in-one that still bundles a phone system (5 numbers, 500 min, 500 SMS), so at our 1-2 operator scale you get pipeline + dialer + follow-up + basic dispo without stacking Twilio. If you want a purpose-built **Dispo blast feature** and don't mind $50 more, **REsimpli Basic ($149/mo)** is the stronger single-vendor answer (native dispo-to-buyer-list is exactly this channel's gap). **Skip the paid cash-buyer data tools as a recurring line** — PropStream/BatchLeads/DealMachine are selling us data we already parse from ROD deeds; keep one ($99 PropStream) only as a one-month cross-check to validate our free list, then cancel. **Total recommended run rate: $99-$149/mo, buyer list $0.**

Sources: [REsimpli pricing](https://resimpli.com/pricing/) · [InvestorFuse pricing](https://www.investorfuse.com/pricing) · [FreedomSoft pricing](https://freedomsoft.com/pricing/) · [Forefront CRM pricing](https://forefrontcrm.com/pricing/) · [Follow Up Boss pricing](https://www.followupboss.com/pricing) · [PropStream pricing](https://www.propstream.com/pricing) · [PropStream cash-buyer list](https://www.propstream.com/news/how-to-find-cash-buyers-using-propstreams-quick-list) · [DealMachine pricing](https://www.dealmachine.com/pricing) · [BatchLeads pricing](https://www.g2.com/products/batchleads/pricing) · [DocuSign/Dotloop pricing](https://www.pandadoc.com/blog/docusign-vs-dotloop/) · [SC LLR wholesaling guidance](https://llr.sc.gov/re/News/Wholesaling-Assignment-of-Contracts-Guidance.pdf) · [SC Realtors on new wholesaling law](https://screaltors.org/sc-regulates-wholesaling-in-new-re-license-law/)


---

# Deep-Dive Round 4 — Net-New Source Hunt (2026-07-02)


## Contact / phone / email (net-new free)

| Source | What it provides | Free? / cost | Access (API/scrape/portal/bulk) | Footprint coverage | Already in repo? | Net-new value |
|---|---|---|---|---|---|---|
| **FCC ULS amateur-radio license DB (EN.dat)** | Licensee full name + **Phone (pos 13)** + Fax + **Email (pos 15)** + street address, joinable to HD/AM files by call sign/FRN | **Free** weekly full + daily bulk zips | Bulk .zip download (no login, no anti-bot); pipe-delimited .dat | Nationwide; filter by ZIP/state to the 18 counties. Phone+email present for a real subset of licensees (rural/mountain WNC has meaningful ham density) | **No** | The ONLY verified source here that carries a real **email AND phone** in a clean free bulk file. Address-join to your parcel/owner backbone by name+address; net-new direct-contact rows for a niche-but-real slice |
| **FEC individual contributions bulk file** | Name, city, state, ZIP, **employer, occupation**, gift amount/date — NO phone, NO email | Free | Bulk .zip / OpenFEC API (no key needed for browse) | Nationwide; filter contributor city/ZIP to footprint | **No** | Low-moderate. Adds employer/occupation (income + reachability-at-work signal) and confirms an owner is alive/local, but you must still skip-trace for the phone. Best as an *enrichment* layer, not a contact source |
| **NCSBE campaign-finance transactions** | Contributor full name + **complete mailing address + job title + employer** (>$50 gifts) — NO phone/email | Free | Portal search + **CSV export** per query (no full bulk; scripted search discouraged) | NC counties only (10 of 18) | **No** | Same profile as FEC but NC-specific and includes full street address (FEC only gives city/ZIP). Useful as an address+employer enrichment join; not a phone/email source |
| **NC Real Estate Commission licensee DB** | Broker name, license status, **business/firm address** (phone/email not exposed in public lookup) | Free | Public web lookup (no login); per-record, not bulk | NC only | **No** | Low. Only relevant when an owner is themselves a licensed broker; contact fields are firm-level, not personal. Narrow |
| **SC LLR licensee lookup** | Licensee name, city, license status; contact fields largely withheld; **bulk = paid** | Lookup free; bulk verification is **paid** | Per-record portal; bulk behind paywall | SC only | **No** | Low. Personal phone/email not in the free tier; the paid bulk product returns status only, not contacts |
| **Out-of-state voter files (absentee owners)** | For an owner who lives out-of-state, their home-state voter file may add address/party — **but the phone field is confidential in most big states** (MI, FL, and typically OH/CA restrict phone) | Mostly free-to-cheap ($0–$37) where offered | State-by-state bulk request | Only helps for absentee owners whose home state publishes phone (a minority) | **No** | Low-moderate and fragmented. The states most likely to hold your absentee owners (MI/FL) mask the phone. Not worth a per-state build |
| **Legacy.com / funeral-home obituaries (relatives + guestbook)** | "Survived by" relative names + hometowns; guestbook signers give name + relationship (email captured but **not publicly displayed**) | Free to read | Scrape (obituaries BUILT for Gannett Upstate already); Legacy has ToS + is JS-heavy | Footprint funeral homes | **Partially** (obituaries facet already built) | Moderate but it's a *name-graph* source, not a contact source: it yields heir NAMES to then skip-trace, not phones/emails. Already partly tapped |
| **TruePeopleSearch / FastPeopleSearch** | Name → current/past addresses, **phones, emails, relatives** | Free UI | Scrape only | Nationwide | **No** | High data value BUT **hard anti-bot + ToS-no-scrape wall** (Cloudflare/queue, FCRA/CCPA cautions). Flagging as a wall — do not build a scraper against it |

**Top pick to build next:** The **FCC ULS amateur-radio EN.dat bulk file** is the single genuinely net-new, verified source that delivers a real **phone + email** at scale in a free, no-login, weekly bulk download (fields confirmed: Phone pos 13, Email pos 15, Street Address pos 16). Build a small ingester that pulls the weekly `l_amat.zip`, filters EN records to your 18-county ZIP set, and joins to the owner backbone by name+address to stamp direct contact fields — a clean win for the niche slice of owners who are hams (non-trivial in rural WNC). Everything else here is either **enrichment-only** (FEC / NC-SBE campaign finance add employer+occupation+address but zero phone/email — treat as income/aliveness signals feeding your existing skip-trace, not as contact sources) or a **confirmed wall** (TruePeopleSearch/FastPeopleSearch anti-bot + ToS — do not scrape). Bottom line: for *direct* phone/email, this facet is largely tapped out beyond the FCC file; the durable path remains name→skip-trace, and these public files are best used to *enrich the name graph*, not to replace the trace.


## Comps / value (net-new free)

| Source | What it provides | Free? / cost | Access | Footprint coverage | Already in repo? | Net-new value |
|---|---|---|---|---|---|---|
| **FHFA UAD Aggregate Statistics** (uad/aggregate-statistics-dashboards) | Aggregated appraisal-report stats: appraised value, contract price, sale-vs-appraisal gap, GLA/sqft, lot size, condition/quality ratings, age — grouped by property/site/neighborhood traits | Free, zipped CSV/TXT bulk + dashboards | Bulk file download + data.gov catalog | National/state/MSA/**county**/**census tract** — all 18 counties covered | **No** (repo has FHFA-HPI, not UAD) | High. Only free source of actual appraiser sqft/condition/quality distributions and contract-vs-appraisal gap per tract — a real ARV calibration input distinct from HPI index |
| **Zillow Median Sale Price + ZHVI files** (research/data) | Median sale price and ZHVI (incl. **ZHVI per square foot**), by home type/bedroom tier; monthly, back to ~1996 | Free public CSV | Direct CSV download | Neighborhood/**ZIP**/city/**county**/metro | Partial — repo has **ZORI (rent) only**; sale-price + ZHVI-per-sqft are separate files not ingested | Medium-high. ZHVI/sqft at ZIP is a clean $/sqft anchor for the ARV floor; median sale price gives a market-trend multiplier the rent index can't |
| **Redfin Data Center downloads** (news/data-center) | Median sale price, **median $/sqft**, homes sold, inventory, sale-to-list, days-on-market; weekly + monthly | Free gzipped TSV | Direct download (S3-backed) | National/state/metro/**county**/city/**ZIP**/neighborhood | **No** | Medium-high. County/ZIP median $/sqft + sale-to-list ratio (a distress/negotiation signal) that neither FHFA nor the repo's current mix provides; weekly cadence beats monthly |
| **Realtor.com Research inventory file** (realtor.com/research/data) | Median **listing** price, median listing $/sqft, active count, days-on-market, price-reduced share | Free CSV (also mirrored on FRED) | Direct CSV / FRED | National/state/metro/**county**/**ZIP** | **No** | Low-medium. Listing-side (not sold) — but "price-reduced share" and DOM at ZIP are supply/softness signals for adjusting comps; complements the sold-price sources |
| **qPublic SC Sales Search / Sales List** (qpublic.net/sc/scassessors) | Individual qualified **sale price + parcel specs** (heated sqft, year built, beds/baths, book/page) per parcel | Free portal | Per-parcel search / Sales-List query (**403 to plain fetch — Cloudflare/anti-bot wall**) | Covers SC qPublic counties incl. Pickens/Oconee/Union (already noted live in memory) | **Partial** — repo already pulls Pickens/Oconee CARD; the *Sales-List query* (multi-parcel comp pull) is not | Low. Mostly overlaps existing per-parcel CARD scraping; flag: bulk Sales-List path is anti-bot walled, do not evade |
| **Wake-style county "Qualified Sales" annual xlsx** (per-county assessor) | Reviewed arms-length **sale price + specs**, trailing 24 months, as a clean spreadsheet | Free xlsx where offered | Direct file download | Only counties that publish it (Wake does; **need to check each of the 18** — most publish per-parcel not bulk) | **No** | Medium *if* any of the 18 publish it. Pre-vetted arms-length flag saves the repo's own qualified-sale filtering; worth a one-time per-county check |

**Top pick to build next:** FHFA UAD Aggregate Statistics — it is a genuinely net-new free bulk download (county + census-tract) that no other repo source replicates: appraiser-reported sqft/condition/quality distributions plus the contract-price-vs-appraised-value gap, which is a direct ARV-calibration and over/under-appraisal signal rather than another price index. Pair it with the Zillow Median Sale Price / ZHVI-per-sqft files (trivial to ingest since the ZORI loader already exists — just point it at two more CSVs) to get a ZIP-level $/sqft anchor for the ARV floor. Skip iBuyer offer data (no clean free dataset, and Opendoor/Offerpad have negligible presence in western NC / upstate SC), and do not attempt the qPublic Sales-List bulk path — it is Cloudflare-walled.

Sources: [Redfin Data Center](https://www.redfin.com/news/data-center/), [FHFA UAD Aggregate Statistics](https://www.fhfa.gov/data/uad/aggregate-statistics-dashboards), [Zillow Research Data](https://www.zillow.com/research/data/), [Realtor.com Research](https://www.realtor.com/research/data/), [Wake County qualified sales files](https://www.wake.gov/departments-government/tax-administration/data-files-statistics-and-reports/real-estate-property-data-files), [qPublic SC assessors](https://qpublic.net/sc/scassessors/body-g.html).


## Condition / imagery (net-new free)

| Source | What it provides | Free? / cost | Access (API/scrape/portal/bulk) | Footprint coverage | Already in repo? | Net-new value |
|---|---|---|---|---|---|---|
| **USDA NAIP Plus ImageServer** (`imagery.nationalmap.gov/arcgis/rest/services/USGSNAIPPlus/ImageServer`) | 0.6m 4-band leaf-off aerial ortho + on-the-fly NDVI/false-color; roof/yard/overgrowth condition | Free, no login | ArcGIS ImageServer REST (`exportImage` by bbox/parcel) + EarthExplorer bulk | All 18 counties (NC+SC statewide) | No (Esri/Mapillary/StreetView only) | Programmatic per-parcel ortho you host yourself; NDVI band flags vacant/overgrown lots that StreetView can't. Not a browser viewer = scriptable |
| **Henderson County Pictometry oblique (Reveal)** + 3-inch ortho | True oblique (4-directional) + 3" leaf-off ortho; roof damage, additions, outbuildings visible obliquely | Free public viewer | County GIS viewer + ArcGIS REST (hendersoncountync.gov/gis-layers) | Henderson (1 of 18); check-pattern for Buncombe/Gaston | No | Oblique angle reveals roof/structure condition an overhead ortho hides; net-new imagery *type* |
| **Buncombe County `permits` ArcGIS REST** (`gis.buncombecounty.org/arcgis/rest/services/permits/MapServer`) + Accela ACA portal | Building/remodel/repair permits w/ address, type, date — renovation & distress signal (or *absence* of permits on old roofs) | Free, no registration to search | ArcGIS REST query + Accela Citizen Access scrape | Buncombe (Accela pattern also Cabarrus/Meck-adjacent) | No (permit feed is a distinct facet from assessor/CAMA) | "Last permit = 1998" is a strong deferred-maintenance / motivated-seller proxy; renovation permits flag flips-in-progress to avoid |
| **Anderson County SC OpenGov code-enforcement portal** (`countyofandersonsc.portal.opengov.com`) | Property-maintenance / IPMC violation cases: address, violation type, status | Free public portal | OpenGov portal (JSON API behind portal) | Anderson (1 of 18) | No | Direct condition/distress signal at parcel level — open violation = motivated seller + verified poor condition |
| **Spartanburg County Property Maintenance (IPMC) complaints** | Residential IPMC violations in unincorporated areas; report/track system w/ case status | Free | Web form + account-based case tracking (FormCenter); check for map/list export | Spartanburg (1 of 18) | No | Same distress signal as Anderson; Spartanburg is your #1 SC county by volume |
| **EOX Sentinel-2 Cloudless 2024 (WMTS/WMS)** | Annual 10m cloud-free mosaic; change-detection vs prior year (new tarps, cleared lots, fire scars) | Free, CC-BY-SA 4.0 | WMTS/WMS tile service (`s2maps.eu`), OGC-compliant | All 18 counties (global) | No (FEMA/Helene damage is event-specific, not annual baseline) | Cheap annual baseline for automated change-detection; complements one-time FEMA Helene layer with recurring signal |
| **Asheville / Gastonia city Compliance (unsafe/condemned structures)** | Unsafe-building & condemnation actions, demolition-permit referrals | Free | City open-data portal (data-avl.opendata.arcgis.com) + records request | Asheville (Buncombe), Gastonia (Gaston) | No | Condemned/unsafe list = highest-distress condition tier; city layer sits *under* your county coverage |

**Top pick to build next:** The **Buncombe `permits` ArcGIS REST feed** is the single best build — it's a no-auth structured endpoint (not a portal scrape), and "years since last permit" is a genuinely net-new, property-keyed deferred-maintenance proxy that pairs directly onto your existing parcel backbone. Right behind it, wire the **USDA NAIP Plus ImageServer** as your self-hosted per-parcel ortho + NDVI layer (scriptable `exportImage` by parcel bbox across all 18 counties in one integration), then enumerate the **OpenGov/IPMC code-enforcement portals** county-by-county (Anderson SC and Spartanburg confirmed live) for direct violation-level distress signal. Honest caveat: pure fire/EMS (NFIRS) is a dead end here — the OpenFEMA public release is address-less/aggregate, so it adds no parcel-level condition value.


## Distress / life-event (net-new free)

| Source | What it provides | Free? / cost | Access (API/scrape/portal/bulk) | Footprint coverage | Already in repo? | Net-new value |
|---|---|---|---|---|---|---|
| **County Master-in-Equity offices (SC)** — e.g. Anderson MIE, Spartanburg MIE | County-published monthly **foreclosure Sale List + Deficiency + Sale Results PDFs**, plus ACPASS case-file lookup (address, party, judgment) | Free | Scrape: monthly PDF roster + ACPASS portal query per case | Direct fit for all 7 SC counties (Spartanburg, Anderson, Pickens, Oconee, Cherokee, Union, Laurens) | **Partially** — repo has "law-firm trustee calendars" + "newspaper legal notices" but NOT the *county MIE office's own* structured roster + ACPASS join | High. Court-of-record source (not a law-firm aggregator); "Sale Results" gives outcome/upset data the trustee calendars lack; ACPASS resolves owner + judgment amount |
| **SC Forfeited Land Commission (FLC) surplus rolls** — county Auditor/Treasurer FLC pages + Terry Howe Auctions | County-owned tax-**deed** inventory: parcels that got NO bid at delinquent tax sale, now held by county through the 1yr+1day redemption window (opening bid = taxes) | Free (list); Terry Howe portal free to view | Scrape county Auditor FLC page + Terry Howe auction listings | In-footprint: Anderson (90+ parcels live), Spartanburg (Terry Howe), Oconee, likely Pickens/Laurens | **No** — repo has SC delinquent-tax *balances* (qPayBill) but not the FLC post-sale owned inventory | High. These owners are maximally distressed (already lost title, in redemption) and reachable; distinct from pre-sale tax-delinquent lane |
| **NC tax-foreclosure PDFs — county Tax Collector "Properties Scheduled for Sale"** (Buncombe, Henderson, Cherokee, Rutherford, etc.) | County in-rem / mortgage-style **tax foreclosure** sale schedule: parcel, owner, upset-bid status, sale date | Free | Scrape county tax dept "Tax Foreclosure Sales" page (HTML/PDF) | Most NC-11 counties post these (Henderson, Cherokee confirmed; Buncombe via courthouse) | **Likely partial** — "newspaper legal notices" + Column may catch some; the county tax-dept schedule page itself is a cleaner structured source | Medium-High. Tax foreclosure ≠ mortgage foreclosure; owner has equity but is losing to the county — high-motivation, and upset-bid window gives a live actionable window |
| **NC Uniform Partition of Heirs Property Act sales — Clerk of Superior Court Special Proceedings** | Court-ordered **partition/heir-property forced sales** (SP file): commissioner sale of inherited land where heirs can't agree; Notice of Sale w/ property + date | Free | **Portal-limited** — notices posted on courthouse bulletin board; SP index searchable at Clerk, no unified feed | All 11 NC counties (statewide SP process) | **No** — distinct from probate/estate lane (this is post-death *forced partition*, not administration) | Medium. Textbook motivated seller (heirs want out, court is forcing it). Access is the catch: bulletin-board posting, not a data feed — needs on-site/clerk-index pull. Flag as build-with-caveat |
| **Zacchaeus Legal Services** (zls-nc.com) — statewide NC gov't tax-foreclosure firm | "Properties for Sale" portal aggregating tax-foreclosure sales for 49 NC local governments | Free (JS portal; errored on plain fetch — needs stealth browser) | Scrape SPA (client-rendered; anti-fragile, not walled) | **Mostly OUT of footprint** — enumerated clients are eastern NC + Forsyth/Guilford/Iredell; **none of our NC-11** | No | **Low for us.** Documented so it's not re-chased: great source, wrong counties. Revisit only if a target county ever contracts them |

**Walls / dead-ends (do NOT chase):** LIHEAP / utility-disconnection recipient lists are **Privacy-Act protected** (HUD SORN + state admin) — not obtainable. **Business-license-lapse for landlord distress** is tapped out in-footprint: NC has no county business licenses (municipal-only, no searchable lapsed/revoked feed), SC city licenses expose no public delinquency list. SSA Death Master File full file is now fee-gated (NTIS) and state death indexes are restricted — your existing Gannett obituaries lane already covers the death life-event more cheaply. IRS/US-Marshals/Treasury/GSA/USDA/HUD-GSE REO are already logged as federal dead-ends or in-repo.

**Top pick to build next:** The **SC Forfeited Land Commission surplus rolls** — free, structurally simple (county Auditor FLC page + Terry Howe listings), in-footprint, and it targets the single most distressed seller class in the whole engine: owners who already lost title at tax sale and are inside the one-year redemption window, still contactable and desperate to recover equity. It's a clean net-new SOURCE that plugs directly into the existing name→property→equity→contact backbone, and it complements (doesn't duplicate) the pre-sale tax-delinquent balances already captured via qPayBill. Second priority is the **county Master-in-Equity "Sale Results + ACPASS"** join, which upgrades your existing SC foreclosure coverage from law-firm-calendar quality to court-of-record quality with owner/judgment resolution.


## Geo / parcel / address (net-new free)

| Source | What it provides | Free? / cost | Access (API/scrape/portal/bulk) | Footprint coverage | Already in repo? | Net-new value |
|---|---|---|---|---|---|---|
| **NC OneMap AddressNC** (`services.gis.nc.gov/.../AddressNC/NC1Map_Addresses/MapServer/4`) | Statewide E911 address *points* — `st_address`, muni, county, point geometry; NG911-derived, updated ~monthly | Free, public | ArcGIS REST query (JSON/GeoJSON/PBF, 2k/page) + bulk GeoJSON/CSV download | All 11 NC counties | Repo has NC OneMap *parcels* only; the address-point layer is a **distinct** endpoint not wired | HIGH — this is the direct address-less-gap closer for NC (parcel_id or lat/lng → real street address), same trick chascogis gives Charleston but statewide NC |
| **NAD — National Address Database** (USDOT, data.gov text file) | ~80M nationwide address records; NC is a confirmed participating state (street num/name, city, zip, lat/lon, county) | Free, public domain | Bulk state text file / GDB via data.gov + ArcGIS item | NC: yes (11 counties). SC: **not** a participating state — gap | No | MED for NC (redundant with AddressNC but carries ZIP, which AddressNC lacks — good ZIP backfill join). Zero for SC |
| **County ArcGIS Open Data Hubs (enumerated)** | Per-county address points + parcels as clean FeatureServers | Free, public | ArcGIS Hub REST + CSV/GeoJSON/Shapefile download | Confirmed live hubs: Buncombe (`data.buncombecounty.org`), Gaston (`gis.gastoncountync.gov`), Henderson (`hendersoncountync.gov/gis-layers`), Rutherford, Spartanburg (`spartanburg-county-open-data-spartco`), Oconee (`data-oconeesc`), Pickens (`pcgis-pickenscosc`) | Partly — Spartanburg/Charleston addresses tapped; the rest are new | HIGH for **SC** counties (Spartanburg/Oconee/Pickens have native address-point layers → covers the SC side that NAD/AddressNC miss). Also gives per-county attribute fields richer than SCDOT layer10 |
| **SC RFA statewide 911 address structures** (rfa.sc.gov 911 program) | Statewide SC address-point/structure layer feeding the composite locator | Free but **not self-serve** — request from RFA GIS (803-734-3793) | Email/request; no public REST/download link found | All 7 SC counties | No | MED — would be the SC analog to AddressNC, but gated behind a request. Worth one email; do not scrape |
| **Microsoft / Bing US Building Footprints** (`microsoft/GlobalMLBuildingFootprints`) | 125M US building-outline polygons w/ centroids (CDLA-Permissive 2.0) | Free | Bulk quadkey GeoJSON (`.csv.gz`) via GitHub; also Esri ArcGIS Hub feature layer | All 18 counties | No (repo has Esri/Mapillary *imagery*, not footprints) | MED — not an address source, but a structure-presence/centroid layer: confirms a parcel is improved (vacant-land filter) and gives a rooftop point to snap situs to when only parcel polygon exists |
| **OpenAddresses (US-South / batch.openaddresses.io)** | Aggregated open address points sourced from the same county portals | Free, openly licensed | Bulk download (Kaggle "US South", batch.openaddresses.io) | NC + SC, county-dependent | No | LOW — mostly re-packages the county hubs + NAD already listed above; useful only as a convenience mirror, not a new signal |
| **Regrid free tier** | Parcel boundary tile layer; click reveals address + size + APN | Free tile layer only; full attribute files are **paid** by county/state | Tileserver (free) / API + bulk (paid) | All 18 | No | LOW — free tier is view-only per-click, not bulk-pullable; the paid parcel files duplicate assessor/GIS you already have. Not worth building against |

**Top pick to build next:** Wire the **NC OneMap AddressNC point layer** — it is the single highest-leverage free add, closing the address-less gap for all 11 NC counties the same way chascogis does for Charleston (resolve `parcel_id` or `lat/lng` → real `st_address`), and it is a clean queryable REST endpoint distinct from the parcel layer already in the repo. Pair it with a one-time **NAD NC text-file** join purely to backfill ZIP codes (AddressNC has no zip field), and stand up the three SC county open-data address-point hubs (**Spartanburg, Oconee, Pickens**) to cover the SC side that NAD/AddressNC don't reach. Note: SC has no free self-serve statewide address layer — RFA's is request-only, and Regrid's free tier is view-only, so both are dead-ends for automated pulls.


## Foreclosure-specific feeds (net-new free)

| Source | What it provides | Free? / cost | Access (API/scrape/portal/bulk) | Footprint coverage | Already in repo? | Net-new value |
|---|---|---|---|---|---|---|
| **NC eCourts Portal — Smart Search "Special Proceedings" (SP) filter** (portal-nc.tylertech.cloud, Odyssey Enterprise Justice) | Power-of-sale **mortgage** foreclosure filings at the notice-of-hearing stage (case #, parties, county, filing date) — the earliest possible distress signal, months before the trustee sale | Free, no login for public view | Scrape (Tyler Odyssey portal; SmartSearch is JS/WAF-guarded — needs stealth browser, same class as the estates wall) | All 18 NC counties (statewide since Oct 2025) | **No** — repo hits only the open Judgment Search JSON (lis-pendens/divorce) + math-only upset-bid window; SP notice-of-hearing filings are explicitly NOT captured | **Highest.** Catches mortgage foreclosures at filing, not at sale — the whole non-tax foreclosure lane currently only enters via law-firm calendars (which appear ~30 days pre-sale). |
| **Henderson County NC Tax Collector — direct foreclosure-sale table** (hendersoncountync.gov/tax/page/tax-foreclosure-sales) | In-rem tax foreclosures: owner name, parcel #, court file #, description, opening bid, sale date, upset-bid link | Free | Scrape (static HTML table on county site) | Henderson (in-footprint) | **No** — generic NC scraper covers only Gaston/McDowell/Rutherford; Henderson is handled in-house, not by Kania/Zacchaeus | Medium-high. Net-new in-footprint county not routed through any covered law firm. |
| **Lincoln / Burke / Polk County NC — direct tax-foreclosure pages** | Same in-rem tax-foreclosure detail (parcel, file #, opening bid, sale date) posted on each county's own tax page | Free | Scrape (add county URLs to existing `nc_county_tax_foreclosure.COUNTY_PAGES`) | Lincoln, Burke, Polk (in-footprint) | **No** — not in COUNTY_PAGES dict | Medium. Cheap to add; each is a distinct in-house-foreclosing county missed today. |
| **NC clerk-of-court Report-of-Sale / confirmed upset-bid amounts** (per-county Clerk of Superior Court, e.g. Buncombe 828-259-3400, Gaston 1st-floor) | The **confirmed hammer price** and true 10-day upset-bid deadline (from report-of-sale filing date), plus who currently holds the high bid | Free (public record; some counties phone/in-person only) | Portal where posted; otherwise phone/in-person — no unified online feed | 18 counties (availability varies; many are in-person only) | **No** — repo estimates the window at sale_date+14 but never scrapes the actual report-of-sale filing | Medium. Turns the estimated upset window into an exact deadline + real bid-to-beat, but data access is uneven and partly offline. |
| **DeedFlex — NC tax-deed live aggregator** (deedflex.com/states/NC) | Scored NC tax-deed listings: address, opening bid, est. market value, county-record verification links | Freemium — 5 listings free, full = $89/mo | Portal (paywalled beyond preview; no API) | ~10 NC counties, currently active: Mecklenburg, Rowan, Caldwell (little in-footprint overlap yet) | No | Low. Overlaps county-direct + Kania/Zacchaeus data we already get free; paywall + weak footprint overlap. Watch, don't build. |
| **GovEase — online tax-lien/deed auction platform** (govease.com/tax-sale-property-auctions) | Live/upcoming county tax-sale rosters where the county runs its sale on GovEase | Free to browse upcoming auctions (bidding needs account) | Portal (per-county auction pages) | Some NC counties; in-footprint SC counties run their own systems (not GovEase) | No | Low-medium. Verify whether any of the 18 counties actually host on GovEase; most in-footprint SC counties self-host, so likely thin. |

**Top pick to build next:** The **NC eCourts SP (power-of-sale) foreclosure filings** — it's the only source that surfaces *mortgage* foreclosures at the notice-of-hearing stage across all 18 NC counties, months earlier than the law-firm sale calendars that are the sole current path. It shares the exact stealth-browser pattern the repo already uses for the NC eCourts estates wall, so it's an incremental build on known infrastructure (accept it may hit the same Tyler SmartSearch WAF — compliant stealth only, no evasion). Immediate cheap win alongside it: add **Henderson, Lincoln, Burke, Polk** to the existing `nc_county_tax_foreclosure.COUNTY_PAGES` dict — four in-footprint in-house-foreclosing counties currently missed, using code that already exists. Everything else (Bid4Assets NC, trustee-foreclosuresalesonline, Anderson SC MIE PDFs, Rogers Townsend, Zacchaeus/Kania, ServiceLink/Xome, tax-deed aggregators) is either already covered, out-of-footprint, login/paywalled, or in-person-only.

Relevant repo files: `/Users/cashhigh/foreclosure-scraper/src/foreclosure_scraper/scrapers/counties_nc/nc_ecourts_lis_pendens.py` (extend for SP), `/Users/cashhigh/foreclosure-scraper/src/foreclosure_scraper/scrapers/counties_nc/nc_county_tax_foreclosure.py` (add 4 counties to `COUNTY_PAGES`), `/Users/cashhigh/foreclosure-scraper/src/foreclosure_scraper/enrichment_upset_bid.py` (upgrade estimate→confirmed if report-of-sale is added).


---

# Deep-Dive Round 5 — Vendor Teardowns (integration-grade, 2026-07-02)


## ATTOM Data

### What we'd use it for (in this engine)
ATTOM is the "fill-the-gaps" property-fundamentals layer, not a lead source. It maps cleanly onto our missing-only backfill: given a resolved `parcel_id`/`fips+APN`, `lat/lng`, or address, hydrate assessed/market value, 10-year sales history, current sale, deed/mortgage records, foreclosure/pre-foreclosure filings, and an AVM. It is strongest exactly where our county scrapers are weakest or walled — the SC recorded-$/loan-amount gaps, the "no sale price on distressed deeds" §12-24-70 dead-end, cross-county AVM comps, and the taxes-owed-adjacent assessment values. The persistent **ATTOM ID** is a genuinely useful join key across our county-fragmented records.

What it does **not** do: no phone/skip-trace/homeowner-contact data (explicitly absent — competitors flag this as ATTOM's biggest gap). So it is a valuation/liens/history enricher, never the contact leg of `name→property→equity→contact`.

### Exact plans/tiers + per-unit overage (2026, verify)
Three distinct products — do not conflate them:

- **Property Data API (transactional):** Pay-per-use. Billed on **API Reports produced, not calls made**. Example from ATTOM's own help doc: **$1,000/mo for 100,000 reports = $0.10/report**; overage bills at the **same $0.10/report**, no step-up. Third-party listings cite an entry point "around $500/mo," but real price is a **custom quote** after the trial. Only HTTP 200 responses count toward the quota.
- **ATTOM Cloud / Bulk Licensing:** Custom-quoted. Snowflake/Databricks delivery, or **bulk CSV over FTP** (weekly/monthly/quarterly/annual). This is the only path that lets you **store data past 24h** (see ToS below).
- **Property Navigator (UI tool, not API):** **$499/yr** Professional, annual only — **200 reports/mo + 2,000 list exports/mo**, 1 seat. Enterprise = custom. **No API access on either Navigator tier.** Irrelevant to us except as a cheap manual spot-check console.

Critical billing gotcha: an "API Report" = **one property returned**, not one HTTP call. A radius/geo AVM call returning 1,000 properties = **1,000 reports**. Pagination is your cost lever (default/max 1,000 per page; docs elsewhere say 100 max per page — verify against your account).

### API shape
- **Base URL:** `https://api.gateway.attomdata.com/propertyapi/v1.0.0/`
- **Auth:** static API key in header **`APIKey`** (no OAuth), plus `Accept: application/json` (or xml). Trivial to wire.
- **Key endpoints:** `/property/detail`, `/property/expandedprofile`, `/assessment/detail`, `/sale/detail`, `/saleshistory/detail` (10-yr), `/attomavm/detail`, `/allevents/detail` (assessment+AVM+sales combined — cheapest way to get multiple facets per property). Foreclosure/pre-foreclosure filings live in separate foreclosure endpoints/packages (often gated to specific data packages — confirm on quote).
- **Request:** GET with query params. Identify a property by `attomid`, `fips`+`APN`, `address1`+`address2`, or `postalcode`; geo by `latitude`+`longitude`+`radius`. Pipe-delimited multi-values (`propertytype=sfr|apartment`). Date windows via `startCalendarDate`/`endCalendarDate`.
- **Response:** JSON/XML with a `status{code,total,page,pagesize}` envelope.
- **Batch:** **No batch/bulk lookup on the transactional API** — it's one-property-per-call (geo endpoints return many, but you can't POST a list of parcels). True batch = the Bulk/Cloud product.
- **Pagination:** `page` + `pageSize`, `orderBy` (e.g. `saleAmt+desc`, `distance`).

### Rate limits + throughput
ATTOM publishes **no explicit calls/sec or daily cap** in the docs or FAQ — throughput is governed by your contracted monthly report quota, and quota is only decremented on 200s. Practically, plan for low-concurrency, polite request pacing (our httpx enricher's existing per-lead sequential pattern is fine); confirm any burst ceiling with your rep since it's account-specific.

### ToS for OUR use — this is the decisive section
- **Caching/storage:** The API ToS **prohibits "caching or otherwise storing the ATTOM Content provided through the ATTOM API for a period of greater than twenty-four (24) hours."** Our pipeline is **disk-cached and persists resolved leads that auto-enrich indefinitely** — that is a **direct violation of the transactional API license.** This is the headline finding.
- **Derivative DBs / redistribution:** Explicitly forbidden to "use the ATTOM Products to create, enhance or structure any database," to resell, sub-license, or publish any portion. Our board *is* a persistent database enhanced with enrichment — again, incompatible with the API tier.
- **Marketing/owner outreach:** No explicit prohibition on contacting owners or marketing use found in the API terms (unlike credit-header/FCRA data, ATTOM property data isn't permissible-purpose-gated). So the *outreach* use is fine; the *storage* is the problem.
- **Credentialing gate:** None. Trial access is granted for "internal evaluation" only.
- **The clean path:** **Bulk/Cloud licensing explicitly exists to "store data for more than 24 hours"** and run your own calculations locally. For a persistent, cached, self-enriching board, **Bulk/Cloud is the only compliant ATTOM integration** — the API is only compliant for true real-time, throw-away-in-24h lookups.

### Integration effort (Low/Med/High) + where it slots + build estimate
- **API path: Low.** Static-key header auth, REST+JSON, mirrors our existing httpx enrichers exactly. Slots in as a new `attom_enricher` gated on missing value/sales/AVM, keyed on `fips+APN` (best) or address. **~0.5–1 day** to wire, map fields, and handle the `status.code` cases. But you'd have to **disable disk-caching and persistence for ATTOM fields specifically** to stay legal — which fights the whole architecture.
- **Bulk/Cloud path: Medium–High.** CSV-over-FTP or Snowflake ingest, schedule a periodic pull, join on ATTOM ID/APN into the sidecar. **~2–4 days** plus a procurement/quote cycle. This is the architecturally correct fit but adds a batch-ETL lane we don't currently have.

### Real-user gotchas / complaints
- **Rating is genuinely mixed:** **Trustpilot 2.2/5 (15 reviews)**, **G2 ~3.8/5 (34)** — not the rosy 4.6 a first-glance search suggests. Complaints cluster on **customer service** ("staff blaming each other," per Trustpilot) and **pricing opacity**.
- **No contact/phone data** — competitor BatchData marks ATTOM with an "X" on Homeowner Contact Information and on Phone/Address-Verification/Geocoding APIs. Independently corroborated by the neutral Dwellsy 2026 overview (no skip-trace mentioned). *(BatchData is a paid competitor — treat its framing as biased, but the contact-data gap checks out across neutral sources.)*
- **Staleness reality:** ATTOM's own cadence is honest but slow: assessor/deed data follows **county release cycles** (variable, can lag months), sales trends **quarterly**, API data **weekly**. For our distress use case, ATTOM's foreclosure filings will often **trail our own county scrapers**, which hit the source directly.
- **Pricing is sales-gated in practice:** despite "self-serve" marketing and a real 30-day API trial via cloud.attomdata.com, production pricing is a **custom quote** — you cannot get a firm production number without talking to sales.

### Verdict: worth wiring? at what trigger volume?
**Not worth wiring via the transactional API** — its 24-hour storage cap and no-derivative-database clause are fundamentally incompatible with our disk-cached, persistent, self-enriching board. Using it as designed would be a license breach.

**Conditionally worth it via Bulk/Cloud licensing, but only at scale.** ATTOM adds no contact data (our actual bottleneck) and its distress signals lag our direct county scrapers, so it's a *valuation/history/liens* backfill, not a lead source. The trigger to license Bulk: when our free county+GIS+ROD stack has genuinely plateaued on **valuation/sales-history coverage** across the core WNC/Upstate-SC footprint AND lead volume is high enough that a **low-four-figure/month** ATTOM Cloud spend beats the analyst-hours of per-county card scraping — realistically **only if we outgrow the core footprint into statewide/multi-state**, where per-county scraping stops scaling. Below that, the **free 30-day API trial is worth burning purely to benchmark ATTOM's AVM and sales-history against our own comps engine** on a sample of the board — a valuation-calibration exercise, not a production integration.

Sources: [ATTOM API docs](https://api.developer.attomdata.com/docs) · [API Report billing](https://cloud-help.attomdata.com/article/684-api-report) · [API Legal/ToS](https://api.developer.attomdata.com/legal) · [Bulk data](https://api.developer.attomdata.com/bulk) · [Property Navigator pricing](https://www.attomdata.com/solutions/property-navigator/pricing/) · [Property API FAQ](https://www.attomdata.com/solutions/property-data-api/faqs/) · [Dwellsy IQ 2026 overview](https://blog.iq.dwellsy.com/attom-data-overview-2026-property-ownership-and-market-data-explained/) · [BatchData comparison (competitor)](https://batchdata.io/attom-data-vs-batchdata) · [G2](https://www.g2.com/sellers/attom-data-solutions) · [TrustRadius pricing](https://www.trustradius.com/products/attom-data-solutions/pricing)


## BatchData

### What we'd use it for (in this engine)
Two distinct jobs, and it's important to keep them separate:

- **Skip trace (primary use):** the `name → property → equity → contact` backbone's final leg. Feed it a `parcel_id` or owner name + situs address, get back phone numbers (mobile/landline/VoIP with a reachability score), emails, current mailing address, plus DNC/litigator/bankruptcy/death flags. This is the paid fallback for the ~missing-contact rows that our free lanes (GIS owner, SoS agent, unclaimed-property) don't resolve. It slots in as a per-lead, missing-only enricher exactly like the existing httpx/curl_cffi enrichers.
- **Property lookup/search (secondary, probably skip):** their property product overlaps almost entirely with what we already pull free from county GIS/CAMA/assessor cards and SCDOT. Their differentiators (nationwide 150M-property normalized schema, 300+ data points, mortgage/lien estimates, pre-foreclosure flags) are conveniences we've largely rebuilt county-by-county. The one genuinely additive property field is their **open-mortgage / estimated-equity** estimate, but we already compute `ARV − payoff − liens` from recorded docs, so paying for it is redundant in-footprint.

Net: wire the **skip-trace endpoint only**; ignore property-search.

### Exact plans/tiers + per-unit overage (2026, verify)
Two separate price sheets — property data and skip tracing are billed independently.

**Skip Tracing (subscription):**
| Plan | Monthly | Included traces | Effective per-trace |
|---|---|---|---|
| Growth | $2,000 | 100,000 | $0.020 |
| Professional | $5,000 | 300,000 | $0.0167 |
| Scale | $10,000 | 750,000 | $0.0133 |
| Enterprise 3M | $20,000 | 3,000,000 | $0.0067 |

**Property Data (separate subscription):** Growth $1,000/100k → Enterprise $10,000/3M records.

**Pay-as-you-go (the tier that actually matters for us):** ~**$0.02–$0.25 per record** self-serve, no monthly commitment — sign up free, pay per hit. Public sources cluster the PAYG skip-trace rate around **$0.02–$0.07/record at low volume**, sliding toward the $0.0067 floor only at 3M/mo. **Overage on subscription plans is not publicly disclosed** — this is a stated gap; you must get the per-record overage rate in writing before committing to a tier, because "included volume then silence" is where these contracts bite. **Match-based billing is the key ToS question to confirm:** several sources imply you pay per record *submitted*, not per *hit* — verify whether no-match rows are billed (industry norm is you pay for the query regardless of match).

VERIFY all numbers live before quoting to anyone — the tier structure is stable across sources but the PAYG rate and overage terms are the soft spots.

### API shape
- **Base URL:** `https://api.batchdata.com/api/v1/`
- **Auth:** `Authorization: Bearer <token>` + `Content-Type: application/json`. Token is generated from the dashboard (not OAuth — a static bearer key, trivial to drop into an env var alongside the existing enricher keys). `Accept: application/json` expected.
- **Key endpoints:**
  - `POST /api/v1/property/skip-trace` — **synchronous**, up to **100 properties/request**, returns results inline.
  - `POST /api/v1/property/skip-trace-async` — **asynchronous**, returns immediately with only a `status` object; results delivered via webhook or polled.
  - `GET /queue/:id` — poll async job results by job id.
  - `POST /api/v1/phone/dnc` (a.k.a. `/dnc/scrub/`) — standalone DNC/litigator scrub on raw phone numbers.
  - `POST /api/v1/property/search`, `/property/lookup` — the property product (skip for us).
- **Request format (verified from a live payload):**
  ```json
  { "requests": [
      { "propertyAddress": { "street": "1011 Rosegold St", "city": "Franklin Square", "state": "NY", "zip": "11010" } }
  ] }
  ```
  APN and owner name are optional fields that materially improve match rate — **we have both** (`parcel_id`, owner), so we should always send them.
- **Response format (verified):**
  ```json
  { "status": { "code": 200, "text": "OK" },
    "results": {
      "persons": [ {
        "name": { "first": "...", "last": "..." },
        "emails": [ { "email": "..." } ],
        "phoneNumbers": [ { "number": "...", "carrier": "...", "type": "Mobile",
                            "tested": true, "reachable": true, "score": 100 } ],
        "dnc": ..., "litigator": ..., "bankruptcy": {...}, "death": {...},
        "mailingAddress": {...}, "meta": { "matched": true, "error": false } } ],
      "meta": { "results": { "requestCount": 1, "matchCount": 1, "noMatchCount": 0, "errorCount": 0 } }
  } }
  ```
  The per-phone `score` (0–100) + `type` (Mobile/Landline/VoIP) + `reachable` is exactly what you want for ranking outreach targets and for TCPA-safe cold-call vs text routing.
- **Batch:** 100 records/request (sync). For our board-scale runs you chunk to 100 and either loop sync or use the async endpoint.
- **Pagination:** skip-trace itself isn't paginated (it's request-array in, results-array out, 1:1 by index). Property-search uses `take`/`skip`-style params. `meta.results` gives you `matchCount/noMatchCount/errorCount` for reconciliation.

### Rate limits + throughput
Officially **undocumented** — this is the single biggest integration unknown. What's known: 100 records/sync request; they explicitly tell high-volume users to use the async endpoint to avoid timeouts and to "stagger exports 30–60 min apart." Rate-limit responses exist (429-style) but no published calls/sec or daily cap. Claimed 99.8% uptime. Practically: treat throughput as unknown, build a token-bucket limiter + retry/backoff on 429, and start conservative (a few sync req/sec) until you observe their actual ceiling. Do NOT assume you can fire the whole board at once.

### ToS for OUR use
- **Skip-trace / marketing permissible:** Yes — this is their core market (real-estate investors cold-calling/texting property owners). They bake in DNC-registry checking, TCPA-litigator flagging, and mobile/landline distinction specifically so customers can run compliant outreach. Our motivated-seller outreach is squarely the intended use.
- **Redistribution:** Standard for this category — you can *use* contacts for your own outreach, but **reselling/redistributing the raw data is prohibited**. Confirm the exact clause; if any client-facing product would expose BatchData contacts to a third party, that's a redistribution question.
- **Storage/caching:** No explicit caching prohibition surfaced in docs, **but skip-trace data is perishable and you're likely contractually expected not to hoard/resell it.** Our disk cache is fine for de-duping re-queries; just don't treat a cached contact as fresh forever (see staleness below) and don't expose the cache as a dataset.
- **Credentialing gate:** Skip-trace vendors increasingly gate PII behind a permissible-purpose attestation (GLBA/DPPA-style). BatchData is more self-serve than the credit-bureau-backed vendors, but **verify whether they require a signed permissible-use / end-user certification** before enabling the API — this can add days to onboarding. This is the most likely hidden onboarding friction.

### Integration effort (Low/Med/High) + where it slots in + build estimate
**Low.** It's a bearer-key JSON POST that maps 1:1 onto our existing enricher pattern — same shape as the httpx enrichers we already run.

- Slots in as a new missing-only enricher in the resolved-lead enrichment pipeline, gated to fire **only** when (a) owner/parcel is resolved AND (b) free contact lanes returned nothing. Source-agnostic, exactly like the current gates.
- Key on `parcel_id` (fallback owner+address) into the existing disk cache so a lead is never re-traced.
- Send `propertyAddress` + APN + owner name (all fields we hold) to maximize match rate.
- Persist `phoneNumbers[].score/type/reachable`, `dnc`, `litigator` so the outreach layer can rank and route (text VoIP/mobile, respect DNC).

**Build estimate:** ~**0.5–1 day** for the sync path (client, cache key, gate, response mapper, 429 backoff, `meta` reconciliation, cost counter). **+0.5–1 day** if we need the async/webhook path for full-board runs (queue POST → webhook receiver or `GET /queue/:id` poller). Add unknown lead time for any permissible-use paperwork.

### Real-user gotchas / complaints (cited)
- **Is 76% RPC real? Treat it as a marketing ceiling, not your number.** The 76% "right-party contact" figure comes entirely from [BatchData's own site](https://batchdata.io/skip-tracing), which even independent comparison content restates uncritically. Independent framings put BatchLeads/BatchData in a **65–85% match-rate** band, and note match rate ≠ *good* rate ([Tracerfy comparison](https://www.tracerfy.com/Skip-Tracing-Comparison-Tool-Tracerfy-vs-PropStream-vs-BatchLeads)). Real-world "phone actually reaches the right person" will be well under 76% — budget on **effective cost per *valid* contact**, not per record.
- **Accuracy complaints are real and specific.** A Trustpilot reviewer: *"Genuinely DOES NOT WORK. Phone numbers are all wrong, and even the owners are wrong a third of the time"* ([Trustpilot](https://www.trustpilot.com/review/batchskiptracing.com)). Overall Trustpilot skews positive, but the negative reviews cluster on wrong numbers + wrong owner identification and difficulty getting refunds. The independent [Real Estate Skills review](https://www.realestateskills.com/blog/batchskiptracing-review) is soft/promotional and provides **no verified match rate** and no head-to-head test data — don't rely on it.
- **"Pricey for small users"** and **no built-in list-stacking** are the recurring structural gripes ([Real Estate Skills](https://www.realestateskills.com/blog/batchskiptracing-review)) — irrelevant to us since we're API-only, not using their UI.
- **Hidden-fee risk = overage + no-match billing.** Overage rates aren't published and it's unclear whether no-match rows bill — both must be pinned in writing.
- **Data staleness:** contact data is enriched from tier-one aggregators + a user feedback loop, but skip-trace PII decays fast (numbers reassigned, people move). The `tested`/`reachable`/`score` fields help, but re-trace stale rows on a cadence rather than trusting a cached hit indefinitely.
- **Rebrand confusion:** BatchSkipTracing → BatchData, sister product BatchLeads. Docs, reviews, and blog examples inconsistently use `/v1/skiptrace`, `/api/v1/property/skip-trace`, and Stoplight mock URLs — **verify the exact live path against the current dashboard**, don't trust a blog snippet.

### Verdict: worth wiring?
**Yes for skip-trace, as a gated paid fallback — no for property data.** It's a Low-effort, well-shaped API that fills the one lane our free stack genuinely can't (owner phone/email at scale) and comes TCPA/DNC-aware out of the box, which we'd otherwise have to bolt on.

**Trigger volume:** Stay **pay-as-you-go** until we're consistently skip-tracing **>~100k contacts/month**. The Growth subscription only breaks even vs PAYG at ~100k traces/mo ($2,000 ÷ $0.02); below that, subscription is dead money. Concretely:
- **< ~5k/mo missing-contact rows:** PAYG, no contract. Wire it, cap it with a per-run spend limit, done.
- **~100k+/mo sustained:** move to Growth/Professional — but only after getting **overage rate, no-match billing, and permissible-use requirements** in writing first.

Because the pipeline is missing-only + cached + gated, our actual paid volume is a small fraction of the board, which keeps us firmly in PAYG territory and caps downside while we validate their real (not marketing) match rate on a live sample before scaling spend.


## RentCast

### What we'd use it for (in this engine)
Primary gap-filler for **sqft + AVM (value) + long-term rent** on leads where the county GIS/assessor path came back null. Three independent single-property endpoints (`/properties`, `/avm/value`, `/avm/rent/long-term`) map cleanly to the missing-only backfill: call `/properties` when `square_footage`/`year_built`/`bedbath` is null, call `/avm/value` when `arv`/assessed fallback failed, call `/avm/rent/long-term` when you want a rent number for DSCR/hold underwriting. Each returns the comps array too, so it can also feed the comp-accuracy layer where your ROD/qPublic comps are thin. It is a genuine drop-in because it accepts a free-text `address` OR `latitude`/`longitude` — matching your parcel_id/owner/address keying (you resolve address or lat/lng, then pass it straight through).

### Exact plans/tiers + per-unit overage (2026, verify)
- **Developer** — $0/mo, 50 requests/mo, then $0.20/request
- **Foundation** — $74/mo, 1,000 requests/mo, then $0.06/request
- **Growth** — $199/mo, 5,000 requests/mo, then $0.03/request
- **Scale** — $449/mo, 25,000 requests/mo, then $0.015/request
- Enterprise custom above 25k.

Billing unit = **one successful API request** (any 2xx). A `/properties` area call returning up to 500 records still counts as **one** request, which is the cheap way to bulk-pull. Each AVM estimate is one request. Verify current numbers at rentcast.io/api — they last revised AVM/pricing Aug 2025.

### API shape
- **Base URL:** `https://api.rentcast.io/v1`
- **Auth:** API key in header `X-Api-Key: YOUR_KEY`. Self-serve key from the dashboard, no approval gate. JSON in/out, all GET.
- **Key endpoints:**
  - `GET /properties` — property records. Params: `address` (single-property exact match) OR area (`city`/`state`/`zipCode`, or `latitude`+`longitude`+`radius` ≤100mi), plus filters `propertyType`, `bedrooms`, `bathrooms`, `squareFootage`, `lotSize`, `yearBuilt`, `saleDateRange`. Returns `squareFootage`, `lotSize`, `yearBuilt`, `bedrooms`, `bathrooms`, sale history, owner name/mailing (owner-occupied flag), features, tax assessments.
  - `GET /avm/value` — value estimate. Params: `address` OR `latitude`/`longitude`; `propertyType`; optional `bedrooms`/`bathrooms`/`squareFootage`, `compCount` (5–25, default 15), `maxRadius`, `daysOld`, `lookupSubjectAttributes` (default true — it self-fills subject attributes so you can pass address-only). Returns point estimate + `priceRangeLow`/`priceRangeHigh` + comparables[].
  - `GET /avm/rent/long-term` — same param shape, returns rent estimate + range + rental comps[].
  - Plus `/listings/sale`, `/listings/rental`, `/markets` (zip-level trend).
- **Batch support:** **None.** No bulk/POST-array endpoint — one property per AVM call. The only "batch" lever is `/properties` area search (`limit` up to 500) when you can express the target as a geography rather than N discrete addresses.
- **Pagination:** `limit` (1–500, default 50) + `offset`; `includeTotalCount` header for totals.

### Rate limits + throughput
**20 requests/second**, hard. No documented daily cap beyond your monthly quota. At 20 rps your ceiling is high enough that quota, not rate, is the binding constraint. Async httpx with a semaphore of ~15 concurrent is safe.

### ToS for OUR use
Strongly favorable — and note there are **two** documents; the one that governs the API is **rentcast.io/terms-api**, not the consumer platform EULA at /terms (the /terms EULA reads restrictive and is the wrong doc for this decision). The API License explicitly grants: (i) **"lawful direct marketing purposes"**; (ii) **store the API Data within your internal systems** (caching your disk cache is fine); (iii) **create derivative works** within internal systems; (iv) **"sublicensure, disclosure, display, resale and distribution of the API Data to third parties."** No attribution required. Restrictions that matter to us: don't use it in a jurisdiction that prohibits marketing use of public info, and **"do not send automated queries to any website"** (this targets scraping-through-the-API, not normal high-volume API calls — your pipeline usage is fine). Self-serve key, no credentialing gate.

### Integration effort (Low/Med/High) + slot-in + build estimate
**Low.** One async httpx client class, `X-Api-Key` header, three thin methods mirroring your existing enricher signature, keyed on the address/lat-lng you already resolve. Fits behind your missing-only gates exactly like the GIS/assessor enrichers, and its disk-cache key is just `(endpoint, normalized_address)`. **Build estimate: half a day** including cache wiring, 429/5xx retry with backoff, and a smoke test against 20 real NC/SC leads. The map is 1:1 with fields you already store (`square_footage`, `arv`, add `rent_estimate`+`rent_low`/`rent_high`).

### Real-user gotchas / complaints
- **Rural/low-density comps thin out.** The most consistent complaint across r/realestateinvesting and an independent BNBCalc review is that in rural/low-density markets comps thin out and rent/AVM usefulness drops — directly relevant to Western NC + Upstate SC core counties. AVM will return a wide `priceRangeLow/High`; treat a wide band as low confidence, same as your `arv_confidence` gating (source: bnbcalc.com RentCast Review 2026; r/realestateinvesting).
- **No polygons/boundary data** and update cadence "not as frequent as some competitors" (noted even by Realie's own comparison piece).
- **No STR/Airbnb, no MLS/PM integrations** — irrelevant to us (we only want sqft/AVM/rent numbers).
- Independent reviews report rent estimates track local listings **better than Zillow's Zestimate** in metro/suburban markets; no published % error figure, so backtest against your own sold set before trusting it.
- No reports of hidden fees or billing surprises; billing is transparent (1 request = 1 unit).

### Verdict: worth wiring?
**Yes — this is the better drop-in of the two.** Clean single-address AVM + rent endpoints, permissive marketing/caching/resale license, self-serve, 1:1 field map. Wire it at the **Foundation ($74) tier** the moment monthly gap-fill volume crosses ~1,000 lookups (below that the free 50 or pay-as-you-go $0.20 covers a smoke test). At **Growth ($199 / 5k @ $0.03 overage)** it's the natural home once you're backfilling a full board weekly. Rent estimate is a genuine net-new capability for the engine (you capture no rent anywhere today). Gate low-confidence AVMs by the returned price range, especially in rural core counties.

---

## Realie.ai

### What we'd use it for (in this engine)
Bulk **parcel + ownership + mortgage + sqft** enrichment, keyed the way your engine already keys: **by parcel_id (county APN/assessor ID), owner name, or address** — plus map-bounds/geo search. Its structural strength over RentCast is the **100-parcels-per-request area pull**, which is attractive for hydrating a whole county of leads in one call and for the name→property→owner backbone. AVM is a **secondary, still-rolling-out** product, so treat Realie primarily as a sqft/ownership/mortgage filler and only opportunistically as an AVM source.

### Exact plans/tiers + per-unit overage (2026, verify)
- **Free** — $0/mo, 25 requests/mo, then $0.15/request
- **Tier 1** — $50/mo, 1,250 requests/mo, then $0.05/request
- **Tier 2** — $150/mo, 6,000 requests/mo, then $0.03/request
- **Tier 3** — $350/mo, 30,000 requests/mo, then $0.01/request

All tiers include the same endpoints and data types and **up to 100 parcels per request**; overage is per-call above the included amount; unused requests do not roll over. Billing unit = **one API request**, and a request returning 100 parcels is billed as one — so at Tier 2, 6,000 requests × 100 parcels ≈ up to 600k parcels/mo, dramatically more records-per-dollar than RentCast **if** your targets can be expressed as area/bounds pulls rather than N single addresses. Verify at realie.ai/pricing and docs.realie.ai/api-reference/pricing.

### API shape
- **Base URL:** not published on the open docs pages I could reach; auth is "include this key in the headers of all requests" (header name not exposed publicly — confirm the exact header, likely `Authorization`/`x-api-key`, with support@realie.ai before build).
- **Key endpoints (all JSON):**
  - **Property Search** — paginated pull across a geographic area (the 100-parcels/request workhorse).
  - **Address Lookup** — single address, "optimized for lower latency, real-time" (their headline is sub-10ms server-side).
  - **Parcel ID Lookup** — by county parcel/assessor ID (maps to your `parcel_id` key).
  - **Location Search** — lat/long + radius geospatial.
  - **Premium Comparables Search** — comps for valuation/underwriting.
  - Owner-name search to surface linked parcels/portfolios.
- **Fields:** parcel geometry/polygons (a RentCast gap Realie fills), ownership, mortgage, zoning, building attributes incl. square footage, assessed/market value; **AVM** value estimate where covered.
- **Batch support:** the **100-parcels-per-request** area/bounds pull is the batch mechanism — better than RentCast for wide geographic hydration. No documented POST-array of arbitrary addresses.
- **Pagination:** cursor/page-based through large areas (Property Search is explicitly "pagination through large geographic areas"); exact param names not published — confirm at build.

### Rate limits + throughput
**1,200 requests/minute (20 rps)**, 429 on exceed; enterprise can raise it. Same effective ceiling as RentCast. Claimed server-side latency ~9.5ms (vendor benchmark, treat skeptically) is well below RentCast's cited ~439ms — if real, meaningfully faster per call under concurrency.

### ToS for OUR use
**Mixed / a real caution.** Their **/terms** contains an explicit anti-competition + anti-resale clause: you may **not** "aggregate, repackage, or resell our data or derived data products," nor build any product/API/database that "directly or indirectly competes." For an internal enrichment-and-outreach engine that consumes the data privately, that's likely fine, but the language is broad enough that **shipping enriched leads to third parties (e.g., selling a lead list) is a redistribution risk** — the opposite of RentCast's explicit resale grant. Caching/storage and marketing-use permissions are **not stated on the public pages I could reach** (only the competition/resale restriction is). If downstream resale or list-brokering is on the roadmap, get written confirmation from Realie (hello@realie.ai) on internal caching, marketing/solicitation use, and lead redistribution before committing. Attribution required if you ever publicly display their content.

### Integration effort (Low/Med/High) + slot-in + build estimate
**Medium.** The blocker isn't code complexity, it's **undocumented specifics** on the open docs: exact base URL, auth header name, pagination param names, and per-field response schema aren't publicly exposed (several doc/endpoint pages 404 or omit them), and the site rate-limited my requests. So there's a discovery/confirmation loop with support before the client is safe to build. Once confirmed, it slots in as (a) a `parcel_id`/`owner`-keyed enricher for the name→property backbone, and (b) a per-county bulk hydrator that pulls 100 parcels/call and updates many leads at once — a different shape from your current one-lead-at-a-time enrichers, so it needs a small "area pull → fan out to leads by parcel_id" adapter. **Build estimate: 1.5–2 days** (0.5 day support/schema confirmation + 1–1.5 day client, the area-pull adapter, cache keying, and smoke test).

### Real-user gotchas / complaints
- **AVM is limited and still rolling out** (their own materials describe AVM as "limited states, rolling out" — do not assume rural NC/SC AVM coverage; verify per-county before relying on it for ARV).
- **AI-collected data** — they collect county records "using AI" across 3,100+ counties / 180M+ parcels; their own site carries the caveat that "responses generated using AI may contain mistakes." For rural NC/SC counties, coverage exists on paper but **field completeness (esp. sqft, mortgage) is the risk** — spot-check match rate on your actual core counties, because AI-parsed county data is exactly where nulls creep in.
- **Thin independent review footprint** — reviews are dominated by Realie's own blog/comparison pages and a sparse Trustpilot; no independent match-rate benchmarks found. The 9.5ms latency and coverage claims are vendor-sourced.
- Public docs are incomplete/gated (404s, rate-limiting) — a mild signal about developer-experience polish vs RentCast's fully open OpenAPI/`llms.txt`.

### Verdict: worth wiring?
**Conditionally, and second in line.** Realie wins on **records-per-dollar for bulk county hydration** (100 parcels/request) and adds **parcel polygons + mortgage + owner-portfolio** that RentCast lacks — genuinely useful for the name→property→equity backbone. But for the specific ask here (**drop-in sqft + AVM + rent gap-filler**), it's weaker: **AVM is partial/rolling-out, there is no rent estimate at all**, the resale/competition ToS is a redistribution risk, and the integration needs a support round-trip because public docs omit auth/base-URL/schema. **Wire RentCast first as the sqft+AVM+rent drop-in.** Add Realie only if/when you need (a) high-volume **per-county bulk** parcel/owner/mortgage hydration (trigger ~6,000 req/mo → Tier 2 $150), or (b) polygons/mortgage/owner-portfolio data — and only after confirming caching + lead-redistribution rights in writing.

**Bottom line for the drop-in decision:** RentCast is the better gap-filler — it's the only one of the two with a rent estimate, has clean single-address AVM matching your keying, a permissive marketing/caching/resale license, self-serve keys, and fully open docs. Realie is the better *bulk parcel/ownership/mortgage* tool but is not a rent source, is only a partial AVM source, and carries redistribution ToS friction.

Sources: [RentCast API pricing](https://www.rentcast.io/api) · [RentCast API docs/OpenAPI](https://developers.rentcast.io/) · [RentCast API License](https://www.rentcast.io/terms-api) · [BNBCalc RentCast Review 2026](https://www.bnbcalc.com/reviews/rentcast-review-2026) · [Realie pricing](https://www.realie.ai/pricing) · [Realie API docs](https://docs.realie.ai/api-reference/property-data) · [Realie pricing tiers doc](https://docs.realie.ai/api-reference/pricing) · [Realie ToS](https://www.realie.ai/terms) · [Realie best-APIs blog](https://blog.realie.ai/blog/exploring-the-best-u-s-property-data-apis-and-their-drawbacks)


## TrueNCOA

### What we'd use it for (in this engine)
CASS standardization + DPV + NCOALink move-update on the mailing addresses we already resolve (owner name + situs/mailing address per lead). Concretely: before we drop a direct-mail piece on a motivated-seller lead (probate/divorce/tax-delinquent/absentee), run the owner's mailing address through TrueNCOA to (a) get a USPS-standardized, DPV-confirmed deliverable address, (b) catch the ~12%/yr who filed a change-of-address and forward to the new address, and (c) suppress undeliverable/vacant/moved-no-forward records so we stop paying postage on dead mail. This is a **batch, mail-prep step**, not a per-lead real-time enricher — it fits a "flush the outreach queue" job, not the missing-only inline backfill loop.

### Exact plans/tiers + per-unit overage (2026, verify)
- **Flat $20 per file, all-inclusive.** No recurring fee, no file-size limit, no per-record charge. CASS, DPV, both 18-month and 48-month NCOA are all bundled in that $20. (Source: TrueNCOA product pages; verify current price at checkout.)
- Billing model is **charge-on-download**: you can submit, process, and view match stats for free; you are only charged the $20 when you export/download the finished file (`download=true` / `charge=` on the export call). No credits consumed until then.
- No tiers, no overage table — it's genuinely one price per file regardless of 100 or 1,000,000 records. The only "unit" is a file.
- Hard floor: **a file must contain at least 100 distinct records** to process (enforced in the CLI and API).

### API shape — base URL, auth, endpoints, format, batch, pagination
Reverse-engineered from the official CLI source (`github.com/truencoa/cli`, `Program.cs`) plus the Postman collection (`documenter.getpostman.com/view/2009332/UUxzA7SU`), since the marketing docs omit specifics.

- **Base URL:** `https://api.truencoa.com/` (production), `https://api.testing.truencoa.com/` (sandbox). HTTPS required.
- **Auth:** two custom request headers on every call — `user_name` and `password` (your account email + password, or API id + API key). No OAuth, no bearer token. Trivial to set in httpx headers.
- **Format:** originally tab-delimited field POSTs; the API now also **accepts JSON on POST**, and supports CSV/JSON output.
- **File-submit → poll → export → download flow** (the pattern you asked about):
  1. **Add records:** `POST files/{file_name}/records?mailer={listOwnerName}` — body carries the record fields. Call repeatedly to append batches or single records into a named file you invent client-side (e.g. `outreach_{ticks}`). Required fields: `individual_id`, `individual_first_name`, `individual_last_name` (or `individual_full_name`), `address_line_1`, `address_line_2`, `address_city_name`, `address_state_code`, `address_postal_code`; optional `address_country_code`.
  2. **Check ready-to-submit:** `GET files/{file_name}` → returns `{Name, Status, Id, RecordCount}`. Must be `Status == "Mapped"` and `RecordCount >= 100` before submit.
  3. **Submit:** `PATCH files/{file_name}?status=submit`.
  4. **Poll:** `GET files/{file_name}` in a loop. Status lifecycle: `Processing` → terminal `Processed` (success) / `Cancelled` / `Errored`. (CLI polls until status leaves `Processing`.) Typical completion **4–7 minutes**.
  5. **Export:** `PATCH files/{file_name}?status=export&suppress={n}` → returns an export file `Id`; poll `GET files/{exportId}` until it leaves `Export`/`Exporting`.
  6. **Download (paginated):** `GET files/{exportId}/records?page={n}&charge={0|1}` — **this is where pagination lives.** Page from 1, each response is `{Records:[...]}`; keep incrementing `page` until a page returns zero records. `charge=1` (or `download=true` in CLI) is what actually bills the $20.
  7. **Reports (optional):** `GET files/{file_name}/reports?report_name={r}&format=pdf` for the USPS 3553/summary PDF.
- **Batch support:** yes — you assemble the whole list into one named file via repeated record POSTs, then process as a batch. There is no synchronous "one address in, one address out" call; everything is file-oriented and async.

### Rate limits + throughput
No published per-second/per-minute rate limit — throughput is governed by the **async file model**, not call rate. End-to-end latency is dominated by the 4–7 min processing wait per file plus your record-upload loop. Practical shape: one file per outreach batch, a handful of files a day. This is not a high-QPS API and shouldn't be treated like one.

### ToS for OUR use — this is the deciding constraint
- **NCOALink is USPS-licensed and contractually restricted to mailing/mail-preparation purposes.** Per USPS: "NCOALink is used only for the purposes of mailing." COA (change-of-address) data carries Privacy-Act restrictions enforced through the PAF.
- **Using NCOA move-data as a skip-trace / people-locator to *find where someone moved to* for phone/door outreach is outside the permitted use.** If your intent is "owner moved, get me their new address so I can chase them," that is the prohibited use case. The compliant use is: clean/forward/suppress addresses **on a list you are about to mail**.
- **PAF (Processing Acknowledgment Form):** required by USPS for every processing. TrueNCOA **auto-generates and auto-fills the PAF** from your registration — no wet signature, no manual gating step before your first file. If you operate as an **agency/mailer on behalf of a client** (e.g. HighWay running mail for a client), USPS requires the **list owner / mailer name** on the PAF; you pass it either as `?mailer=` on the records POST or by embedding `[List Owner Name]` in the file name. Renewal is handled at the licensee (TrueNCOA) level; you re-attest via the registration on file. Verify the current PAF language in your account before going live.
- **Storage/caching:** the deliverable is your list back — you keep and store the standardized/updated addresses. The restriction is on *purpose of use*, not on retention. (Verify no contractual re-distribution limit in your specific PAF.)

### Integration effort (Low/Med/High) + slot-in + build estimate
**Low–Medium.** Two custom headers, ~6 endpoints, a poll loop, and pagination — no OAuth, no SDK needed. It does **not** slot into the missing-only inline async enricher; it slots into a **separate batched "mail-prep" job** that runs against the outreach queue right before a mail campaign. Add a small async client (`submit → poll → export → paginate`), an `ncoa_status` / `deliverable_address` / `moved_flag` set of fields on the lead, and disk-cache keyed on normalized input address so you don't re-submit unchanged addresses. **Realistic build: 0.5–1 day** for the client + poll/pagination + field mapping; add ~half a day for the 100-record-minimum batching logic and PAF/mailer-name handling.

### Real-user gotchas / complaints
- **NCOA only catches movers who filed a USPS change-of-address.** TrueNCOA's own material concedes it "will NOT catch moves for consumers who did not complete a Change of Address form." NCOA matches ~94% of *forwarding-address filers*, but a large share of real-world moves (especially distressed/probate/vacant owners — exactly our targets) never file one, so **expect a low move-match rate on this population.** The value here is mostly CASS/DPV cleanup + suppressing undeliverables, not finding forwardings.
- **100-record minimum** blocks ad-hoc small runs — you must batch.
- **Charge-on-download** is a footgun in automation: set `charge`/`download` deliberately, or you'll either fail to get records (no credits) or bill yourself unexpectedly. (Documented in the CLI README's Payment note.)
- API "docs" are effectively a Postman collection + the open-source CLI; there's no polished REST reference, so **the CLI source is the real spec.** Support is email/phone (`support@truencoa.com`); reviews are sparse (SaaSHub/G2 low volume) but positive on price and turnaround.
- Sources: [How to get started with the NCOA API](https://truencoa.com/how-to-get-started-with-our-ncoa-api/); [TrueNCOA CLI (Program.cs)](https://github.com/truencoa/cli); [Postman collection](https://documenter.getpostman.com/view/2009332/UUxzA7SU); [PAF details](https://truencoa.com/processing-acknowledgment-form-paf-details/); [USPS NCOALink / PostalPro](https://postalpro.usps.com/mailing-and-shipping-services/NCOALink).

### Verdict: worth wiring? at what trigger volume?
**Only if/when we run our own physical direct mail.** For a mailing pipeline it's a no-brainer: $20/file flat, bundles CASS+DPV+NCOA, kills postage waste. But it is a **mail-hygiene tool, not a skip-trace lever** — using it to locate moved distressed owners is both low-yield (our targets rarely file COAs) and outside the permitted-use ToS. **Wire it when we commit to a mail channel and have ≥100 addresses per drop**; below that, or if outreach stays phone/digital only, skip it. Do **not** put it in the inline enrichment loop.

---

## Geocodio

### What we'd use it for (in this engine)
Rooftop-accurate forward geocoding of the ~18% of leads that arrive address-only / lat-lng-less, and reverse-geocoding of parcels we only have coordinates for — the exact gap our Charleston/SCDOT situs resolver leaves. Also a cheap, storage-legal source of **appended geo attributes** in the same call: Census tract/block + FIPS (`census`), timezone, congressional/state-leg district, and ACS demographics — useful for buy-box filtering and territory routing. It's a clean drop-in for the missing-only backfill pattern: if a lead has an address but no `(lat,lng)` or no census geo, call Geocodio; cache the result.

### Exact plans/tiers + per-unit overage (2026, verify)
Prices **changed Feb 1, 2026** (verify against your account email):
- **Free tier (unchanged):** 2,500 lookups/day, no card. Does not roll over.
- **Pay-as-you-go:** **$1.00 per 1,000 lookups** for US/CA/MX — **doubled from $0.50** on Feb 1, 2026. First 2,500/day still free.
- **Flex (monthly):** Flex 350 $325/mo (350k credits) • Flex 650 $600/mo (650k) • Flex 850 $775/mo (850k); +250k credits per additional user. Annual = 2 months free + 10–20% off top-up credits.
- **Self-Service Unlimited:** raised to **$1,350/mo** for new customers (was $1,000); additional instances **$1,000/mo** (was $700). Customers active as of Jan 31 2026 keep a **$100/mo legacy discount**. North-America+UK Unlimited starts ~$1,600/mo.
- **Critical overage mechanic — appends are billed as lookups:** **Total lookups = addresses × (1 + number of appended field-categories).** One address + census + timezone = **3 lookups**. This silently triples cost if you request appends carelessly. (Verify: [pricing](https://www.geocod.io/pricing), [Feb 2026 update](https://www.geocod.io/updates/pricing-updates-2026/).)

### API shape — base URL, auth, endpoints, format, batch, pagination
- **Base URL:** `https://api.geocod.io/v1.9/` (current major; docs also show `/v2/`-style paths — pin the version you build against).
- **Auth:** API key, either `?api_key=KEY` query param or `Authorization: Bearer KEY` header. Multiple keys per account for per-project usage tracking. Dead simple in httpx.
- **Single forward (GET):** `GET /geocode?q=1109+N+Highland+St,Arlington+VA&api_key=…` — or component params `street/city/state/postal_code/country`.
- **Batch forward (POST):** `POST /geocode` with a JSON array (or keyed object) of addresses — **up to 10,000 per request**; array input returns results in input order; keyed-object input returns keyed results (best for joining back to `parcel_id`). ~600s for a full 10k batch.
- **Reverse:** `GET /reverse?q=38.9,-76.9` (single) and `POST /reverse` (batch up to 10,000 coords) — coords as `"lat,lng"`.
- **Lists API (file jobs):** `POST/GET/DELETE /lists` — CSV/TSV/Excel, up to **10M lookups/list**, 1GB file cap, `{{A}} {{B}}` column-mapping templates, optional completion **webhook**. Note list-job data is auto-deleted 72h after processing (that's the *job artifact*, not a restriction on the results you keep).
- **Response:** `results[]` each with `address_components`, `formatted_address`, `location:{lat,lng}`, `accuracy` (0–1 score), `accuracy_type` (`rooftop`, `range_interpolation`, `street_center`, `place`, `nearest_rooftop_match`, `intersection`, etc.), `source`, and a `stable_address_key`.
- **Appends:** `&fields=census,timezone,cd,stateleg,acs-demographics,zip4,…` (comma-sep). Each category = +1 lookup (see billing note above).
- **Pagination:** none in the classic sense — batch is bounded by the 10k/request cap; you chunk your own input into ≤10k blocks. For files, the Lists API is the async lane.

### Rate limits + throughput
- **Pay-as-you-go / Flex: 1,000 requests/minute** on the single-lookup endpoint. This counts **API calls, not lookups** — so a batch POST of 10,000 addresses is *one* request against the limit, which is how you go fast without tripping it.
- **Unlimited plan: no rate limit**, dedicated resources, throughput capped only by hardware (~3,333 lookups/min observed).
- No hard daily cap beyond the free tier's 2,500/day; on paid you just accrue billable lookups. For our volumes (batching the ~18% address-less), batch POSTs keep us far under any limit. (Source: [Geocodio rate-limit guide](https://www.geocod.io/what-happens-when-you-exceed-the-google-geocoding-api-rate-limit).)

### ToS for OUR use
- **Storage/caching is explicitly ALLOWED — this is Geocodio's headline differentiator.** Unlike Google/most geocoders, "there are no data storage restrictions on forward geocoding… use and re-use the data as needed." That means our disk-cache and permanent persistence of `(lat,lng)`/census on the lead is fully compliant. **One exception: UK reverse geocoding** carries upstream-licensing storage limits (irrelevant to us — we're US-only).
- No mailing/marketing-purpose restriction; geocoding + skip-trace/marketing enrichment use is fine. No special credentialing gate — self-serve key.
- Redistribution of raw geocodes as a competing dataset would be the only gray area; internal enrichment/outreach is squarely permitted. (Verify current [Terms](https://www.geocod.io/terms-of-use/).)

### Integration effort (Low/Med/High) + slot-in + build estimate
**Low.** One key, one header/param, JSON in/out, order-preserving or keyed batch that maps straight to `parcel_id`. Slots **directly into the missing-only inline enricher** (gate: address present AND lat/lng missing → call), and just as easily as a nightly **batch** job that collects all address-less leads and fires one ≤10k POST. Disk-cache keyed on normalized address (you already do this). **Realistic build: 2–4 hours** for the enricher + response mapping + cache + accuracy-threshold gate (drop/flag results with `accuracy < 0.8`). Add ~1 hour if you wire the Lists API + webhook for large recurring files.

### Real-user gotchas / complaints
- **The Feb 2026 100% price hike ($0.50 → $1.00/1k)** is the big one — budget the doubled rate and confirm whether any legacy discount applies. (Only Unlimited subscribers active by Jan 31 2026 got a grandfather discount; pay-as-you-go got none.)
- **Appends-as-lookups billing** is the most common cost surprise: requesting several `fields` multiplies spend per record. Only append what you'll use.
- **Accuracy reality:** on a random US sample expect **~70% rooftop, ~20% range-interpolated, ~10% other**; accuracy is best in dense metros and degrades on rural/new-construction/PO-box-style addresses — relevant since our footprint (Western NC / Upstate SC, rural parcels) skews toward the harder cases. **Gate on `accuracy_type == "rooftop"` and `accuracy >= 0.8`;** treat interpolated results as approximate for point-in-parcel work. Reviewers (G2/Capterra) confirm "great most of the time, occasional inaccurate address," and ask for better map-based verification and non-US/CA coverage.
- Coverage is **US/CA/MX/UK only** — fine for us. Support is well-regarded (email, responsive); docs are genuinely good, which is the opposite of TrueNCOA.
- Sources: [Geocodio API docs](https://www.geocod.io/docs/); [pricing](https://www.geocod.io/pricing); [Feb 2026 pricing update](https://www.geocod.io/updates/pricing-updates-2026/); [accuracy types & scores](https://www.geocod.io/guides/accuracy-types-scores); [G2 reviews](https://www.g2.com/products/geocodio/reviews); [Capterra reviews](https://www.capterra.com/p/239419/Geocodio/reviews/).

### Verdict: worth wiring? at what trigger volume?
**Yes — wire it now.** It's the cleanest fix for the ~18% address-less / lat-lng-less resolver gap, storage is legal (unlike Google), integration is a few hours, and free tier (2,500/day) likely covers steady-state — you'd only pay the $1/1k when a big backlog runs. **Trigger:** any run where the local SCDOT/Charleston resolver returns no coordinates → Geocodio fallback; batch the rest nightly. Even at paid rates the cost is trivial versus the leads it unlocks. Guardrails: request appends only when needed, and gate downstream logic on `accuracy_type`/`accuracy` so interpolated points don't pollute point-in-parcel matches.


## Senzing

### What we'd use it for (in this engine)
Three specific jobs our current union-find can't do well:

1. **LLC / trust / estate → human owner resolution.** When a foreclosure or tax-delinquent parcel is owned by "123 MAIN ST LLC" or "THE SMITH FAMILY TRUST," Senzing links that org record to the humans behind it (registered agent, officers, principals) via **disclosed relationships** — but only if we *feed* it those links (from our NC SoS agent enricher, ROD grantor/grantee, etc.). It does not scrape ownership; it resolves and persists the graph once we supply the edges.
2. **Cross-source person dedup.** The core value. Right now our backbone keys on `parcel_id / owner / address` and joins with heuristics. Senzing takes the same John/Jon/J. Smith at three address variants across foreclosure + probate + tax-delinquent + obituary + SoS feeds and collapses them into **one persistent entity with a stable ENTITY_ID**, with no training and no hand-tuned rules — fuzzy name (Rob/Robert/Bob), phone `+1` normalization, partial/missing fields, DOB/SSN when present. This is exactly the person-dedup our union-find approximates and gets wrong on messy real-world variants.
3. **Household / known-associate derived relationships.** Same-address, shared-phone → Senzing surfaces derived relationships (heirs living together, co-owners, spouses) that feed the motivated-seller scoring.

Slots in as a **resolution layer that sits AFTER enrichment**, consuming the same per-lead records we already build, and emits an `entity_id` we write back to the board as a new join key.

### Exact plans/tiers + per-unit overage (2026, verify)
- **Evaluation / free:** Load and resolve **up to 100,000 DSRs free** (self-serve). Extendable to **1,000,000 free** by emailing [email protected] for a larger non-production license. This is the "free-100k" the brief references — it is the **Non-Production License**, explicitly limited to integration/testing, not production use ([EULA](https://senzing.com/end-user-license-agreement/)).
- **Production:** Annual subscription priced on **Data Source Records (DSRs)**, billed **annually, upfront for the full term**. Only one public figure is posted: **$58,560/yr at 10M DSRs (~$5.86/DSR/yr)**, on a slider that runs 10M → 1B. No public per-tier table below 10M; you request a quote ([pricing](https://senzing.com/pricing/)).
- **Overage / DSR counting mechanics (integration-critical):** A DSR = one mapped record loaded (one `DATA_SOURCE` + `RECORD_ID`). **Re-loading/updating a record with the same key REPLACES it and does NOT increment the count.** Searches and updates are excluded. **Deletes reduce** the count. So the free 100k is a *distinct-record* ceiling, not a call ceiling — our per-lead missing-only backfill pattern (idempotent re-writes) costs nothing extra ([DSRs explained](https://senzing.zendesk.com/hc/en-us/articles/115002897308-Data-Source-Records-DSRs-Explained)).
- **Verify at quote time:** the sub-10M price curve and whether an "unlimited" support-style license exists (referenced in older docs, not on the current pricing page).

**Reality for our footprint:** Western NC + Upstate SC distressed-lead volume is nowhere near 100k *distinct* people/orgs per year. We very likely live **entirely inside the free tier indefinitely**, which reframes the whole "is it worth the High effort" question — the cost is engineering time, not license dollars.

### API shape
Senzing is **not a hosted REST API you call over the network** — it's an **embedded engine (native C library + language bindings)** you run yourself. This is the single most important integration fact.

- **No base URL / no vendor auth.** There is no API key, no OAuth, no rate limit imposed by a vendor. You link the SDK into your own process (or run their optional REST server / Docker container in *your* infra).
- **Bindings:** Python, Java, .NET/C#, Go, C++ (v4). For us: the **Python SDK** (`sz-sdk-python-core`), which fits our async pipeline as a synchronous library wrapped in a thread executor.
- **Backing store:** the engine **requires a database it owns** — PostgreSQL for the Docker quickstart (SQLite for tiny local eval). This is a real dependency: Senzing persists its resolved-entity graph in Postgres; it is *not* stateless.
- **Key SDK calls (the "3 calls" model):**
  - `add_record(data_source, record_id, json_record)` — upsert one record. `add_record_with_info(...)` returns JSON of which entities were affected/merged/split.
  - `search_by_attributes(json_criteria)` — fuzzy search, returns candidate entities + match scores.
  - `get_entity_by_entity_id(entity_id)` / `get_entity_by_record_id(...)` — pull the resolved entity, its member records, and relationships.
  - `delete_record(...)`, `reevaluate_entity(...)`.
- **Request format — the Senzing "entity spec" JSON** (this is where the real work is). Flat `FEATURES` array, one feature object per value:
  ```json
  {
    "DATA_SOURCE": "FORECLOSURE",
    "RECORD_ID": "parcel-0553-14-2201",
    "FEATURES": [
      { "RECORD_TYPE": "PERSON" },
      { "NAME_TYPE": "PRIMARY", "NAME_FIRST": "Robert", "NAME_LAST": "Smith" },
      { "ADDR_TYPE": "HOME", "ADDR_LINE1": "123 Main St", "ADDR_CITY": "Asheville", "ADDR_STATE": "NC", "ADDR_POSTAL_CODE": "28801" },
      { "PHONE_NUMBER": "702-555-1212" },
      { "DATE_OF_BIRTH": "1968-03-14" }
    ]
  }
  ```
  Orgs use `{"RECORD_TYPE":"ORGANIZATION"}` + `NAME_ORG`. Multiple names/addresses/phones = multiple objects, never nested lists; never mix parsed (`NAME_FIRST/LAST`) with unparsed (`NAME_FULL`) in one object ([entity spec](https://senzing.com/docs/entity_specification/index.html)).
- **LLC→human via disclosed relationships (this is how it beats union-find):** you load the **company record AND each person record separately**, then link them with `REL_ANCHOR_*` / `REL_POINTER_*` features. The pointing record carries `REL_POINTER_DOMAIN`, `REL_POINTER_KEY`, `REL_POINTER_ROLE` (standardized roles: `PRINCIPAL_OF`, `OWNER_OF`, `EMPLOYED_BY`, `DIRECT_PARENT`, `ULTIMATE_PARENT`, `SPOUSE_OF`, etc.); the target carries `REL_ANCHOR_DOMAIN` + `REL_ANCHOR_KEY`. Once the person is its own record, Senzing **automatically resolves that same human across every other dataset we load** — so "principal of 123 MAIN ST LLC" gets fused with the same person appearing in a probate filing or obituary. That auto-fusion is the thing our union-find fundamentally cannot do without bespoke rules ([disclosed relationships](https://senzing.zendesk.com/hc/en-us/articles/360051209553-How-to-create-disclosed-relationships)).
- **Batch/pagination:** batch load via their `sz-file-loader` reading **JSONL** (one entity-spec record per line), or loop `add_record` yourself. Search returns capped candidate lists; you page by tightening criteria. No cursor-based REST pagination because there's no REST layer by default.

### Rate limits + throughput
- **No vendor-imposed limits** — it's your process and your Postgres. Throughput is bound by **your CPU cores and DB tuning**. Senzing is genuinely built for scale (hundreds to thousands of records/sec/node with a tuned Postgres; near-real-time single-record `add_record`).
- Practical caveat for us: the engine is **synchronous and stateful against a shared DB**. In our async httpx/curl_cffi pipeline it must run **behind a thread-pool executor / dedicated worker**, and concurrent `add_record` writes contend on the same Senzing datastore — you don't fan it out per-coroutine the way you do HTTP enrichers.

### ToS for OUR use
- **Skip-trace / marketing use:** Not contractually prohibited by the EULA — Senzing is source-agnostic infrastructure; it resolves whatever you load and takes no position on downstream marketing use. **The compliance obligation lives on OUR input data and OUR outreach** (same DNC/consent/state-solicitation rules that already govern the motivated-seller engine), not on Senzing. Senzing itself **ships no data** — there is nothing to redistribute from them.
- **Redistribution:** You may not redistribute or let third parties access/copy the **Senzing software**; no reverse-engineering, no derivative works ([EULA](https://senzing.com/end-user-license-agreement/)). Nothing bars you from using or distributing **your own resolved output** — the entities are your data.
- **Storage / caching:** Fully compatible with our model — Senzing is *designed* to persist resolved entities in your own DB indefinitely; caching entity_ids on our board is the intended pattern, not a violation.
- **Credentialing gate:** **None for the free/eval tier** — self-serve download, no gatekeeping, no "who are you / what's your use case" wall for 100k. The **1M extension and production license are quote-gated** (email/contact required). No professional-license or data-broker credential is required to run the engine.

### Integration effort (High) + where it slots + build estimate
**High — and it's the correct call to flag it as the High-effort one.** The effort is *not* API glue (there's no API); it's:

1. **Stand up + own a stateful service.** Add a Postgres instance and the Senzing runtime to our infra (Docker: `init-database` → `senzingsdk-runtime`). This alone breaks our "stateless free-only local scrapers" pattern — it's the first component that needs a managed DB and a long-lived process. Air-gapped/on-prem is supported but that's not our need.
2. **Data mapping — the real cost.** Every source (foreclosure, probate, tax-delinquent, SoS, obituary, ROD) must be transformed from our internal lead schema into **Senzing entity-spec JSON**, with correct `DATA_SOURCE` codes, `RECORD_TYPE`, parsed name/addr/phone features, and — for LLC→human — the `REL_ANCHOR`/`REL_POINTER` disclosed-relationship edges wired from our SoS-agent and grantor/grantee data. Third-party and vendor guidance converge: **"Senzing does not fix bad data; it evaluates what it receives"** — accuracy comes from *our* profiling, cleansing, standardization, and threshold tuning, not from install ([Match Data Pro](https://matchdatapro.com/how-to-achieve-accurate-senzing-entity-resolution-in-2026/)). There is an AI-assisted mapping tool + MCP server now that reduces this, but the per-source mapping + relationship modeling is still the bulk of the work.
3. **Wire-back.** After enrichment, push each lead as a record, read back `entity_id` + relationships, write to the board (respecting `load_board()` so the vision/comps/cama sidecar isn't wiped), and re-key downstream dedup on `entity_id`.

**Realistic build estimate:** ~**1 week to a working single-source POC** on the free tier (Docker + Postgres + Python bindings + map foreclosure records + prove person-dedup on real data — Senzing markets this as a one-day POC, budget a week for our reality). **~3–4 weeks to production-grade** across all sources with disclosed-relationship LLC→human wiring, standardization pass, threshold tuning, async-worker integration, and board write-back. Plus ongoing: it's a **continuous** system (re-tune as sources are added), not fire-and-forget.

### Real-user gotchas / complaints
- **"Works out of the box" is half-true.** G2 reviewers do praise accuracy and say it rarely needs reconfiguration — but the same body of guidance stresses **accuracy is NOT guaranteed by install**; it "requires focus on data preparation, configuration, validation, and ongoing optimization" (G2 via [search](https://www.g2.com/products/senzing/reviews); [Match Data Pro](https://matchdatapro.com/how-to-achieve-accurate-senzing-entity-resolution-in-2026/)). Expect false positives from over-loading weak attributes and false negatives from dirty input. (Note: G2's review page returned HTTP 403 to direct fetch; specifics here are from the indexed summary, worth re-reading live before committing.)
- **Data mapping to JSONL was the historic #1 pain** — repeatedly cited as "the hardest part." Senzing added an AI mapping tool + MCP server specifically to blunt this, which tells you how common the complaint was.
- **Pricing rigidity.** The recurring G2 gripe is wanting "a more flexible pricing model" — the DSR-volume model and upfront-annual billing don't suit everyone. Irrelevant to us if we stay under 100k free, very relevant if we ever scale past 1M.
- **Setup varies / DB dependency.** "Setup can be challenging but documentation is very good." The unspoken cost for us: it drags in a **PostgreSQL dependency and a stateful runtime**, which is a genuine architectural shift from our current free-only local-scraper posture.
- **No data staleness risk from Senzing** — it holds no reference data; staleness is entirely a function of how fresh *our* feeds are. That's a point in its favor.

### Verdict: worth wiring? at what trigger volume?
**Worth wiring — but as a Phase-2 backbone upgrade, not a quick enricher, and only once volume/complexity justifies owning a stateful service.**

- The **license cost is almost certainly $0** for us (Western NC + Upstate SC distressed leads sit well under 100k distinct entities/yr). So the decision is purely **engineering-time vs. capability**, not dollars — which materially improves the case.
- **The unique capability is real and not replicable cheaply:** automatic, training-free cross-source person dedup + LLC/trust→human via disclosed relationships is exactly the `name→property→equity→contact` backbone weakness. Our union-find approximates it and mis-merges on real-world name/address noise; Senzing is purpose-built for precisely this.
- **Trigger to build:** wire it when **(a)** we're routinely running **3+ overlapping person-indexed sources** (foreclosure + probate + tax-delinquent + SoS + obituary — we now are), AND **(b)** union-find mis-merges/mis-splits are demonstrably costing outreach quality (duplicate mailers, wrong-person contacts, missed heir links). That threshold is essentially met today.
- **Do NOT build it** if the near-term win is just "one more field on existing leads" — the Postgres + stateful-runtime + per-source mapping overhead only pays off when entity resolution *itself* is the product, i.e., you're unifying the whole motivated-seller graph. Given the backbone is explicitly the mission, **recommend a 1-week free-tier POC** on the foreclosure + SoS + probate slice to measure lift over union-find before committing the 3–4 week production build.

**Sources:** [Senzing pricing](https://senzing.com/pricing/) · [DSRs explained](https://senzing.zendesk.com/hc/en-us/articles/115002897308-Data-Source-Records-DSRs-Explained) · [EULA](https://senzing.com/end-user-license-agreement/) · [v4 Docker quickstart](https://senzing.com/docs/quickstart/quickstart_docker/) · [Entity specification](https://senzing.com/docs/entity_specification/index.html) · [Disclosed relationships how-to](https://senzing.zendesk.com/hc/en-us/articles/360051209553-How-to-create-disclosed-relationships) · [Match Data Pro accuracy guide](https://matchdatapro.com/how-to-achieve-accurate-senzing-entity-resolution-in-2026/) · [G2 reviews](https://www.g2.com/products/senzing/reviews) · [SDK deployment options](https://senzing.com/senzing-sdk-deployment-options/)


## PropStream

### What we'd use it for (in this engine)
PropStream is a nationwide property-data + skip-trace UI (assessor/deed/MLS/foreclosure aggregation, owner phones/emails, comps, mail). In our pipeline the *only* plausible role is as a **human-operator research console** for one-off list-pulls and manual comps — NOT as a programmatic enricher. It does not fit the "per-lead missing-only backfill keyed on parcel_id/owner/address, disk-cached, called from async httpx" model at all, because there is no data API to call.

### Exact plans/tiers + per-unit overage (2026, verify)
- Base subscription ~**$99/mo** (annual) / higher month-to-month; "50 imports/exports of properties" included in the free trial.
- **PropStream Connect** add-on: included on Pro & Elite; **$30/mo** add-on on Essentials. Bundles Skip Tracing, Click-to-Dial, Dialer Campaigns (up to 150 call attempts/day, 3 phone numbers), **Lead Automator** (monitor up to 50,000 properties, expandable to 1,200,000 for more), and **discounted Direct Mail (postcards "as low as 48¢")**.
- Skip trace is priced per-record (historically ~$0.10–0.12/hit); direct mail per-piece. All UI-metered, not exposed as billable API units. *(Verify current per-record skip cost in-app — PropStream doesn't publish it cleanly.)*

### API shape — base URL, auth, endpoints, format, batch, pagination
**There is no public REST data API for subscribers.** Confirmed across the FAQ, ToS, and product pages: data comes OUT only via **manual CSV export from the UI** (My Properties / My Contacts → Export). The one "API" that exists is a **native outbound push to BatchDialer** ("Push-to-BatchDialer") that sends already-skip-traced records from the UI into a dialer — one-directional, to a specific partner, not a general data endpoint you can pull from. Zapier is not offered either; integration is CSV + BatchDialer push only.
- Note: the `prostream.app` "Prostream API" that surfaces in search is an unrelated European product — do not confuse it with PropStream.
- **No base URL, no auth token, no endpoints, no batch, no pagination** for our purposes. Programmatic path = **none**.

### Rate limits + throughput
N/A (no API). Practical constraint is UI export cadence + PropStream's **active anti-scraping monitoring** (see ToS). Skip trace and Lead Automator have their own daily/monthly UI caps tied to plan.

### ToS for OUR use
This is the disqualifier. PropStream's Terms of Use explicitly prohibit, for the standard subscription: **"marketing or telemarketing uses,"** "reproduction, reformatting, publication, distribution or dissemination… to any third party," **"extracting, selecting or drawing out any data element for any use,"** and "World Wide Web, Internet or online uses." They also state they **monitor search volume to prevent "data mining" and non-customary usage patterns.** A property-keyed enrichment pipeline that extracts data elements and feeds outreach is squarely against these terms; automating export would risk account termination. Skip-trace/marketing at scale requires "the appropriate subscription allowing such expanded use" — i.e., not the base plan.

### Integration effort + where it slots + build estimate
**Effort: High / effectively N/A.** The only automatable path is headless-browser UI scraping of exports, which the ToS forbids and which PropStream actively watches for. It does not slot into the async enricher layer. If used at all, it's an **operator tool** sitting *outside* the pipeline: a human pulls a CSV, drops it in an inbox dir, and an existing offline parser ingests it (the same manual-court-export lane pattern already in the repo). Build estimate for a compliant, non-API integration: **~0.5 day** to write a CSV-ingest normalizer mapping PropStream columns → our parcel/owner/address schema. Building a real programmatic enricher: **not viable**.

### Real-user gotchas / complaints
- **Skip-trace match rate is the recurring complaint.** BiggerPockets practitioners report ~**650 hits on a 5,000-record run** after stripping LLCs, and "**30 accurate numbers out of 100**"; match accuracy pegged at **60–80%** with stale numbers (>30 days) so a large share don't connect ([BiggerPockets: "Propstream Skip Trace sucks"](https://www.biggerpockets.com/forums/48/topics/1088608-propstream-skip-trace-sucks)). PropStream's own Feb-2026 "multi-sourced skip tracing" update ([PropStream news](https://www.propstream.com/news/updated-skip-tracing-experience-in-propstream-what-changed-and-how-to-use-it)) is an implicit admission of the historical accuracy gap.
- No-refund posture on skip-trace misses.
- Strength is breadth/price of the *underlying property data* and the built-in filters, not contact accuracy.

### Verdict: worth wiring?
**Do not wire into the pipeline — no API, and the ToS forbids exactly our use.** Keep it, if at all, as a **manual operator console** for ad-hoc comps and list QA, with any CSV brought in through the existing manual-ingest lane. Trigger volume to justify even that: only if an operator is already living in PropStream daily. For programmatic owner→contact enrichment, PropertyRadar (below) is the correct tool; PropStream is the wrong shape entirely.

---

## PropertyRadar

### What we'd use it for (in this engine)
This is the one of the three that's a **true programmatic enricher** and fits our model directly. Two high-value roles:
1. **Address/parcel → owner + property enrichment**: feed a distressed address or APN, get owner name(s), mailing address, absentee flag, equity, value, beds/baths/sqft, tax status — backfilling the exact fields our GIS/assessor fallbacks miss.
2. **Owner → phone/email append (skip trace)**: the `Persons`/append endpoints return contact info, and BiggerPockets consensus is these numbers are **"much more accurate than PropStream."**
Slots cleanly as a `httpx` enricher gated on missing fields, disk-cached by RadarID/parcel/owner.

### Exact plans/tiers + per-unit overage (2026, verify)
| Plan | Price (annual/monthly) | Users | Included exports/mo | Included phone/email/mo | Export overage | Phone/email overage | API |
|---|---|---|---|---|---|---|---|
| Solo | $99 / $119 | 1 | 10,000 | 250 | 2¢/rec | 8¢/contact | ❌ |
| Team | $199 / $249 | 3 | 25,000 | 500 | 1.5¢/rec | 6¢/contact | ❌ |
| **Business** | **$549 / $599** | 10 | 50,000 | 2,500 | **1¢/rec** | **4¢/contact** | ✅ **Included** |

Add-on discount: Team 25% off, Business 50% off. **API access is gated to the Business tier** — this is the real cost of entry (~$549–599/mo). Every property record returned with data = **1 export**, whether you pull 1 field or 50. *(Verify tiers/quotas at signup — PR adjusts these.)*

### API shape — base URL, auth, endpoints, format, batch, pagination
- **Base URL:** `https://api.propertyradar.com/v1`
- **Auth:** Bearer token — `Authorization: Bearer {token}` (key from Account Settings). REST, JSON in/out, `Content-Type: application/json`.
- **Key endpoints (tags):** **Properties** (search/purchase), **Persons** (owner + phone/email append), **Lists** (create/add/remove, saved criteria), **Imports** (address-match import → append owner data to your address list), plus Monitors/automations.
- **Request format:** criteria array — `Criteria: [{ "name": "FieldName", "value": [...] }]`, 250+ fields (e.g. `ZipFive`, `AvailableEquity` as range `[[100000,null]]`, `PropertyType`, `Pool`). Range fields use nested `[[min,max]]`.
- **The critical billing control:** `Purchase=0` returns **count only, free, no quota hit**; `Purchase=1` returns actual data and **bills as exports**. This maps perfectly to our missing-only pattern: preview with `Purchase=0`, then purchase only the records we actually need.
- **Batch:** yes — the Import endpoint takes a list of addresses for bulk match/append; search returns thousands per request for bulk enrichment.
- **Pagination:** `Start` + `Limit` offset paging (JSON REST). *(Exact `Limit` max lives in the interactive reference behind login; treat "thousands per request" as the design intent and page conservatively.)*

### Rate limits + throughput
PR does not publish a hard numeric req/sec cap in the public help center; the docs stress **quota discipline over rate discipline** — the binding constraint is your monthly export/append allowance and the no-refund rule ("accidentally return 10,000 records → 10,000 exports, non-refundable"). Practical guidance: single-threaded or low-concurrency, always preview with `Purchase=0` first, and let our disk cache prevent re-pulls. *(Confirm any per-second throttle in the authenticated reference before parallelizing.)*

### ToS for OUR use
Materially friendlier than PropStream for skip-trace/marketing (PR explicitly markets itself for list-building and direct-mail/marketing). **The catch is redistribution:** *"the PropertyRadar API is intended for end-users only — you can not use it to build applications you sell to others."* OAuth exists only for partner apps acting on behalf of shared PR customers. **Storage/caching for our own use is fine; reselling the data or exposing it in a product we sell is not.** Since our engine consumes contacts for our own outreach, we're inside the lines — but if this were ever productized for clients, each client would need their own PR credential (credentialing gate).

### Integration effort + where it slots + build estimate
**Effort: Low–Medium.** Clean REST + bearer + JSON is a natural fit for the existing `httpx` enricher base. Slots as a new enricher after GIS/assessor fallback, gated on missing owner/contact/equity, keyed on parcel/owner/address, disk-cached by RadarID. Build: **~1–1.5 days** — client wrapper (auth, `Purchase=0` preview → `Purchase=1` purchase, Start/Limit paging, quota-aware backoff, cache), field-mapping to our schema, and a quota guard so a bad run can't torch the monthly allowance. Add ~0.5 day to wire the Import/address-match path for bulk backfill.

### Real-user gotchas / complaints
- **G2 4.5/5 (34 reviews), Trustpilot 4.2/5** — strongest marks for data accuracy and monitoring ([G2](https://www.g2.com/products/propertyradar/reviews)).
- Phone accuracy **"much more accurate than PropStream"** per BiggerPockets — the main reason to prefer it as our skip source.
- Complaints: **~10–20% of foreclosure/auction records don't actually go through** (list staleness at the event level, not data-field error); occasional wrong owner/property fields; **strict no-refund policy even on reported data errors**; UI learning curve; one reviewer wanted "an open API instead of relying on Zapier."
- **The financial gotcha is the export-counting model**: every returned record burns quota regardless of fields, and overages/purchases are non-refundable — so the `Purchase=0` preview discipline is not optional.

### Verdict: worth wiring?
**Yes — this is the enricher to build of the three.** It's the only one with a real, well-shaped data API and skip-trace-permissible ToS, and its contact accuracy beats PropStream. Economic trigger: the **$549–599/mo Business tier is the floor** (API-gated), so it's worth wiring once monthly enrichment volume clears roughly **3,000–5,000 property/contact pulls** (where the included 50k exports / 2,500 contacts + cheap 1¢/4¢ overages beat per-lookup one-off vendors). Below a few hundred leads/mo, the Business subscription is dead weight — stay on cheaper per-hit skip vendors until volume justifies it.

---

## Stannp

### What we'd use it for (in this engine)
Stannp is a **direct-mail execution API** — the "send a physical letter/postcard to this owner" step at the very *end* of the funnel, after a lead is scored, owner+mailing-address resolved, and selected for outreach. It's not an enricher (it adds no data to a lead); it's the **outbound action** the pipeline fires once a lead qualifies. Fits as a terminal step / side-effect, triggered per-lead, not part of the missing-only backfill.

### Exact plans/tiers + per-unit overage (2026, verify)
Pay-per-dispatched-item; **price includes print + postage + envelope** (color standard). US letter (8.5×11) pricing by plan × volume:

| Volume | Free | Starter | Growth | Premium |
|---|---|---|---|---|
| ≤1,000 | $0.95 | $0.89 | $0.89 | $0.89 |
| 1k–9,999 | $0.95 | $0.82 | $0.82 | $0.82 |
| 10k–49,999 | $0.95 | $0.82 | $0.73 | $0.73 |
| 50,000+ | $0.95 | $0.82 | $0.73 | **$0.69** |

Add-ons: extra 1-sided sheet **+$0.08**, extra 2-sided **+$0.10**, **non-USPS-matched (unverified) address +$0.20**. Postcards run cheaper (PropStream quotes Stannp-class postcards "as low as 48¢"); *(verify postcard tier table + First Class upgrade in-app — the detailed-pricing page loads its calculator client-side).* Plan tier also sets your **rate limit** (below), so plan choice is driven by throughput, not just price.

### API shape — base URL, auth, endpoints, format, batch, pagination
- **Base URL:** `https://api-us1.stannp.com/v1` (US region; EU is `api-eu1`).
- **Auth:** API key via **HTTP Basic** (`{API_KEY}:` as username, blank password) **or** `?api_key=` GET param. Simple, no OAuth.
- **Format:** **multipart/form-encoded** (not JSON) — supports file uploads. Recipient as nested fields `recipient[firstname]`, `recipient[address1]`, etc.
- **Key endpoints:**
  - `POST /v1/letters/create` — create+send one letter. Params: `test` (bool → returns sample PDF, no charge), `recipient` (existing ID or new array), `template` (int, for mail-merge) OR `file` (PDF/DOC, ≤25 pp, as binary/URL/base64), `size` (`US-LETTER` / `US-LETTER-XL-WINDOW`), `duplex`, `clearzone`, `post_unverified`, `tags`, `addons` (`FIRST_CLASS`,`CONFIDENTIAL`).
  - `POST /v1/letters/post` — post a pre-merged letter.
  - `GET /v1/letters/get/:id` — retrieve status/record.
  - `POST /v1/letters/cancel` — cancel before dispatch.
  - Parallel `POST /v1/postcards/create` for postcards; group/mailing-list endpoints for uploading recipient batches.
- **Response:** JSON — `{ "success": true, "data": { "id", "pdf", "cost", "status", "format", ... } }`; errors `{ "success": false, "error": "..." }`. Test mode returns `status:"test"` and the proof PDF URL.
- **Batch:** two patterns — (a) one API call per recipient (fine at our volumes), or (b) upload a group/recipient list then run a campaign against a template. There's no single "bulk-array-in-one-call" letters endpoint; loop per-recipient or use the campaign/group flow.
- **Webhooks:** yes — delivery, returned-mail, and QR-scan callbacks for status tracking (maps to our per-lead outreach state).

### Rate limits + throughput
Published and plan-tiered: **Free 60 req/min, Starter 300, Growth 600, Premium 2,000, Enterprise 3,000.** Every response carries `X-RateLimit-Limit` / `-Remaining` / `-Reset`. Since one call = one mailpiece in the per-recipient pattern, 300–600/min is ample for our lead volumes. Async fire from the pipeline with a small concurrency cap and honor the reset header.

### ToS for OUR use
Cleanest of the three. Direct mail to property owners for real-estate outreach is Stannp's core, explicitly-supported use case — **no skip-trace/marketing-permission problem** because Stannp is the *sender*, not a data provider. No redistribution issue (we're not reselling their data — there is none). We're responsible for the mailing list and CAN-SPAM/UOCAVA-style compliance of our own content; Stannp handles print/postage/USPS. `post_unverified` / +$0.20 unverified-address surcharge is the only nuance — feed it USPS-matched mailing addresses (which our resolver already produces) to avoid the fee and reduce returns.

### Integration effort + where it slots + build estimate
**Effort: Low.** Form-encoded + Basic auth over `httpx` is trivial. Slots as a **terminal outreach action** (not an enricher): after a lead is graded and an operator/rule approves mailing, call `letters/create` (or postcards), store the returned `id`, and reconcile status via `letters/get` or the webhook. Build: **~0.5–1 day** — client (auth, form-encode, `test=true` proofing path, cost capture, rate-limit header handling), a template or PDF-generation step for the mail piece, idempotency to avoid double-sends (Stannp has a dedupe guide), and webhook receiver for delivery/return status. Start every integration in `test=true` to validate the proof PDF before spending postage.

### Real-user gotchas / complaints
- **Trustpilot ~4+/47 reviews, mixed** ([Trustpilot](https://www.trustpilot.com/review/stannp.com)). Print/paper quality and support (named reps) praised; ease of use good.
- **Delivery-time variance is the real risk**: one reviewer reported letters promised "within a week" taking **~2 months**, arriving after a time-limited offer expired — for time-sensitive foreclosure outreach, build in slack and don't put hard deadlines in the mail copy.
- UI list-building clunky for tiny manual sends (45 min for 5 recipients) — irrelevant for us since we send via API, not the UI.
- Watch the **+$0.20 unverified-address** surcharge and returns if mailing addresses aren't USPS-matched.

### Verdict: worth wiring?
**Yes, when the funnel actually mails.** It's the correct, low-effort, ToS-clean execution endpoint for physical outreach, and the per-piece economics ($0.69–0.89 letters incl. postage) are competitive. Trigger: wire it **once we're sending even ~50–100 pieces/mo** — the API pays for itself immediately vs. manual mail-merge, and there's no subscription floor (pay per item; plan tier only buys higher rate limits). Below a handful of pieces, hand-send; the moment mailing is recurring, Stannp is the automation.

---

### Bottom line for the pipeline
- **PropertyRadar** = the only real *enricher* — wire it (Business tier, API-gated, ~$549+/mo) once contact/property backfill volume clears a few thousand pulls/mo. Best contact accuracy of the three.
- **Stannp** = the *action* endpoint — wire it as the terminal direct-mail step; low effort, clean ToS, no subscription floor.
- **PropStream** = **no programmatic path and ToS actively forbids our use**; keep only as a manual operator console feeding CSVs through the existing manual-ingest lane, never as an automated enricher.
