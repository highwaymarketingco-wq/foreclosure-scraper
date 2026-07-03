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


---

# Deep-Dive Round 6 — The 13 Completeness-Critic Gaps as Costed Sections (2026-07-02)


## DNC / TCPA / Litigator Scrub

### What it is & why it BLOCKS a close (even when the row is 100% filled)

A perfectly enriched lead card — name, property, equity, verified cell phone — is a **legal liability, not an asset**, the instant you dial or text it without scrubbing. The phone number field is the single most dangerous cell on the card. Three overlapping problems turn a "ready" row into a lawsuit:

1. **The number is on the National DNC Registry.** ~40% of US cell numbers are registered. A marketing call/text to a registered number without prior express written consent is a violation.
2. **The number was reassigned.** ~100,000 mobile numbers are reassigned by carriers *every day*. The person on your card no longer owns it; the new owner never distressed a property and never consented. Each contact is a fresh violation.
3. **The number belongs to a known TCPA litigator / "troll."** A small population of professional plaintiffs seed their numbers into distressed-property lists specifically to bait investors into dialing, then file. One litigator can single-handedly generate a class action.

The exposure is not theoretical or trivial: the TCPA is **$500 per violation, trebled to $1,500 per willful/knowing violation, with no statutory cap**. "Per violation" means per call *and* per text — a 3-touch SMS drip to one bad number is 3× $1,500 = $4,500. At 17,003 leads, a single unscrubbed blast where even 2% of numbers are litigator/reassigned/DNC (≈340 numbers × 3 touches × $1,500) is **$1.53M of theoretical exposure** before a single deal closes. TCPA class-action filings hit 1,052 in the first half of 2025 alone (up 95% YoY). This is the fastest way to convert a free lead engine into a legal loss.

State law compounds it. In **South Carolina specifically**, the *sourcing* of the number can itself be unlawful — see the legal subsection below — independent of the TCPA. So a Spartanburg tax-delinquent lead can carry two separate violations from one text.

The engine's entire value proposition (property-keyed name→property→equity→**contact**→outreach) terminates at "contact." Without a scrub gate, the outreach step is the step that gets you sued.

### Current state in the engine (is anything there?)

Based on the file map (`outreach.py`, `crm.json`, `distress_score.py`, `enrichment_strategy_fit.py`, `models.py`, `source_health_tracker.py`), **nothing addresses this gap**:

- `outreach.py` is the send layer — it is exactly where a pre-send scrub gate belongs, and per the assignment it currently dials/texts whatever phone the enrichment produced. There is no evidence of a DNC/litigator check between "row scored" and "message sent."
- `models.py` has no field to persist scrub state. There is no `dnc_status`, `litigator_flag`, `reassigned_checked_at`, `wireless_flag`, `consent_basis`, or `scrub_expires_at` on the lead/contact model. Without these fields you cannot prove a safe-harbor defense and cannot enforce the 31-day rescrub window.
- `crm.json` has no internal/company-specific Do-Not-Call suppression list. The TCPA independently requires you to honor your *own* internal DNC list across all channels; opt-outs from prior campaigns are not being captured or suppressed.
- `enrichment_strategy_fit.py` decides channel fit but does not gate on phone type (wireless vs landline) or consent basis.
- No `source_health_tracker.py` concept of "scrub freshness" exists, so numbers age past the 31-day window silently.

Net: the phone number is enriched and handed to outreach **raw**. This is the highest-severity missing piece in the whole close-machinery layer.

### What "solved" looks like (the concrete deliverable)

A **mandatory pre-send scrub gate** that no message can bypass, plus the fields to prove it. Concretely:

1. **New model fields** (`models.py`): `phone_type` (wireless/landline/voip), `dnc_federal` (bool), `dnc_state` (bool), `litigator_flag` (bool), `reassigned_flag` (bool), `internal_dnc` (bool), `consent_basis` (enum: none / EBR / PEWC), `last_scrubbed_at`, `scrub_source`, `scrub_result_id` (for the audit trail / safe-harbor proof).
2. **A `scrub.py` module** that, given a phone list, returns the flags above and a retained result record.
3. **A hard gate in `outreach.py`**: `if litigator_flag or dnc_federal or dnc_state or internal_dnc or reassigned_flag or last_scrubbed_at > 31 days → BLOCK`. Blocked ≠ deleted; the property stays in the pipeline for **mail** (see Gap 2) which has no TCPA exposure.
4. **An internal DNC list** in `crm.json` that every inbound opt-out ("STOP", "do not call") writes to, honored across SMS/voice/every future run.
5. **A 31-day rescrub cron** so numbers never go stale, wired into the existing weekly-run scheduler.
6. **Retained scrub records** (the safe-harbor evidence + 5-year consent retention the TCPA requires).

Definition of done: a text/call physically cannot leave `outreach.py` unless the number carries a fresh, clean scrub record.

### FREE path (design/code) vs PAID path (vendor + real 2026 price)

This gap is **cheap-to-solve, not free-to-solve** — the litigator and reassigned-number databases are proprietary and cannot be reproduced for free. But the *architecture* (the gate, the fields, the cron, the internal list) is 100% free code you already have the skeleton for.

**FREE path (do all of this regardless):**
- **Internal DNC suppression** — pure code, zero cost, and legally mandatory. Capture every opt-out, suppress forever, across channels.
- **Landline/wireless split via free data** — the FCC/NANPA and free line-type lookups (e.g., the free tier of `phonenumbers` + carrier OCN data, or Twilio Lookup at ~$0.008/number if you want line-type only) let you route landlines (lower TCPA risk, ATDS rules differ) vs wireless.
- **DNC-by-consent logic** — for probate/tax-delinquent/foreclosure leads you generally have **no** established business relationship and **no** prior express written consent, so the correct free default is: **mail-first, phone only after scrub**. Building that routing is free.
- **Do NOT try to self-host the federal DNC registry.** Access to the official registry requires SAN registration and is restricted to sellers/telemarketers for their own area codes; it is not a general scrub source and mis-using it is its own violation.

**PAID path (the part you genuinely must buy — it's cheap):**

| Vendor | What it covers | Real 2026 price |
|---|---|---|
| **TCPA Litigator List** (tcpalitigatorlist.com) | 600K+ known litigators/attorneys/trolls **+ federal & state DNC** in one API scrub | Basic **$199/mo** = 200K scrubs incl., overage **$0.002**/scrub; API Gold **$499/mo** = 500K incl. at **$0.0012**; annual Basic **$2,029/yr**. This is the best-fit, lowest-friction option for this engine's volume. |
| **DNC.com** (Contact Center Compliance) — DNCScrub + LitigatorScrub + **TCPA Reassigned ID** | Federal/state DNC, litigator scrub, and the reassigned-numbers check for safe harbor | Enterprise quote only (unpublished); heavier/pricier, aimed at large call centers. Overkill unless volume explodes. |
| **Per-number scrub floors (market)** | Ad-hoc / single-list scrubs | ~**$0.01/number**, ~**$5 minimum** (TextP2P and similar) — fine for one-off lists, worse unit economics than a subscription at 17K+ volume. |
| **Reassigned Numbers Database** (official FCC RND, reassigneddb.us) | The authoritative reassigned-number safe-harbor check | ~**$0.0025–$0.01/query** tiered; provides the *statutory* safe harbor that private lists don't. Add this once phone outreach volume justifies it. |

**Recommended buy:** TCPA Litigator List **Basic $199/mo** covers litigator + federal + state DNC for this engine's whole 17K board with room to spare (200K scrubs/mo). Add the official **RND** on a per-query basis for reassigned-number safe harbor once you're actively dialing. All-in ≈ **$199–$250/mo** closes 90% of the exposure.

### For LEGAL gaps: the actual SC/NC statutes and what they require

**Federal — TCPA (47 U.S.C. §227) + FCC rules (47 CFR 64.1200):**
- Prior Express Written Consent (PEWC) required for marketing calls/texts to wireless numbers using an autodialer or prerecorded voice.
- National DNC scrub **every 31 days** (47 CFR 64.1200(c)(2)).
- Maintain and honor an **internal DNC list** across all channels; process opt-outs within **10 business days**.
- **Reassigned Numbers Database** query before dialing to claim safe harbor.
- **Damages: $500/violation, up to $1,500 for willful/knowing, no cap** (47 U.S.C. §227(b)(3), (c)(5)).
- 5-year consent-record retention.

**South Carolina — S.C. Code §30-2-50 (the sourcing trap unique to this engine):**
"A person or private entity **shall not knowingly obtain or use personal information obtained from a state agency, a local government, or other political subdivision of the State for commercial solicitation** directed to any person in this State." §30-2-30 defines *personal information* to include **name, home address, and home telephone number**, and *commercial solicitation* as "contact by telephone, mail, or electronic mail for the purpose of selling or marketing a consumer product or service." **Penalty: misdemeanor, fine up to $500 and/or up to one year imprisonment** per §30-2-50(B).

Why this bites *this* engine directly: a large share of the SC leads are pulled from **county tax-delinquent rolls, assessor cards, ROD indexes, magistrate/court data, and qPublic** — i.e., "personal information obtained from a state agency, a local government, or other political subdivision." Using that name+address+phone for solicitation is squarely what §30-2-50 prohibits. **Note the exemptions in §30-2-30** (banking/insurance/securities, credit-union membership, continuing education, political use of voter data) — real-estate wholesale solicitation is *not* among them. This is a genuine compliance question to route to counsel, and at minimum argues for: (a) treating government-sourced SC contact info as solicitation-restricted, (b) leaning on **mail with public-record framing** and skip-traced (non-government-sourced) phone numbers rather than the government-sourced number, and (c) never bulk-texting off a raw county-sourced phone column.

**North Carolina — N.C. Gen. Stat. §75-102 to §75-104 (Telephone Solicitations / NC Do Not Call):**
- §75-102: No telephone solicitation to a number on the current federal DNC Registry (NC adopts the federal list), and none to anyone who has told you to stop; no calls before **8:00 a.m. or after 9:00 p.m.**; must comply with FTC Telemarketing Sales Rule §§310.3–310.5.
- §75-104 penalties: **$500 first violation, $1,000 second, $5,000 each violation thereafter** — escalating and stacking on top of the federal $1,500.

### Effort + build estimate

**Low–Medium.** The vendor does the hard part (the databases). Your build is: `scrub.py` API client + result cache; ~7 new `models.py` fields + migration; the internal-DNC suppression list in `crm.json`; the hard gate + 31-day freshness check in `outreach.py`; a rescrub cron on the existing scheduler. **Estimate: 1.5–2.5 days** of engineering + ~$200/mo vendor. The legal/§30-2-50 review is a separate, higher-value ask to route to counsel (hours, not build time).

### Recommended action

1. **Immediately hard-gate `outreach.py`** so no SMS/voice can send without a scrub record — even a stub that blocks everything until scrub is wired is safer than today.
2. Buy **TCPA Litigator List Basic ($199/mo)**; build `scrub.py` against its API; add the 7 model fields + migration.
3. Stand up the **internal DNC list** and opt-out capture in `crm.json`; wire the **31-day rescrub** into the weekly scheduler.
4. Default **SC government-sourced leads to mail-first**; flag §30-2-50 for a one-time counsel review before any SC phone campaign.
5. Add the official **Reassigned Numbers Database** per-query check once active dialing begins, for statutory safe harbor.

---

## NCOA / CASS Mail Deliverability

### What it is & why it BLOCKS a close (even when the row is 100% filled)

When phone outreach is legally gated (Gap 1), **direct mail becomes the primary channel** for this engine — and mail has its own silent killer: **address rot**. Distressed-property owners are, by definition, the most mobile population in the mailing universe. They move out of the property, move in with relatives, land in a rental, or are in probate/incarceration/foreclosure limbo. The mailing address the county has on file is frequently *not where the person is*.

The failure is invisible and expensive: **~34% of mail sent to unhygienic distressed-owner lists never reaches a live human** — it goes to a vacated property, a bad ZIP+4, an undeliverable-as-addressed record, or a person who filed a change-of-address a year ago. You pay full postage + print + list cost on every one of those pieces and get **zero** contact. On a 17,003-piece mailing at ~$0.70 all-in per piece, a 34% dead rate is **~$4,050 of spend that touched nobody** — per drop. Across a multi-touch mail sequence it compounds.

Two distinct problems, two distinct fixes:

- **CASS** (Coding Accuracy Support System) fixes the *address itself*: standardizes it to USPS format, appends ZIP+4, validates it via DPV (Delivery Point Validation) so you know the address is a real, deliverable point. Bad/incomplete addresses get corrected or flagged before you print.
- **NCOA** (National Change of Address) fixes *where the person went*: matches your list against the USPS's live change-of-address database (18- and 48-month move data) and updates the address to the person's current one. This is the piece that specifically rescues the high-mobility distressed population.

Without both, the mail-first strategy — which is your *compliant* strategy — quietly wastes a third of its budget and misses exactly the owners most likely to be motivated (the ones who already left).

### Current state in the engine (is anything there?)

Per the file map, **nothing addresses mail hygiene**:

- The engine resolves and stores a mailing address (via GIS/assessor/OneMap/SCDOT resolvers noted in memory), but there is **no CASS standardization or DPV validation step** — addresses are stored as-resolved, not as-USPS-verified. `models.py` has no `cass_status`, `dpv_confirmed`, `zip4`, `address_deliverable`, or `vacant_flag`.
- There is **no NCOA move-update step** — no `ncoa_move_flag`, `ncoa_new_address`, `ncoa_move_date`, or `moved` field. The engine cannot tell that an owner relocated, which is both a deliverability fix *and a motivation signal* (an owner who moved off a distressed property is often more motivated to sell it).
- `outreach.py`'s mail path (if any) sends to raw resolved addresses.
- `source_health_tracker.py` has no concept of list hygiene / bounce tracking, so there's no feedback loop on which sources produce undeliverable addresses.

Net: mail deliverability is completely un-instrumented. Given that mail is the fallback for every phone-gated lead, this is a direct throughput leak.

### What "solved" looks like (the concrete deliverable)

A **hygiene pass that runs on any list before it's printed**, plus persisted results:

1. **New `models.py` fields**: `cass_status`, `dpv_confirmed` (Y/N/vacant/no-stat), `zip4`, `carrier_route`, `ncoa_move_flag`, `ncoa_new_address`, `ncoa_move_date`, `address_deliverable` (final go/no-go), `last_hygiene_at`.
2. **A `mail_hygiene.py` module** that runs the list through CASS+DPV+NCOA (via vendor API or batch upload) and writes those fields back.
3. **A deliverability gate in `outreach.py`'s mail path**: suppress DPV-fails and known vacants from the *owner-at-property* mailing (or deliberately route vacants to an "absentee/vacant" template), and **substitute the NCOA new address** when a move is found.
4. **Presort-ready output**: because CASS appends ZIP+4 and carrier route, the same pass makes the mailing **presort-eligible**, which is a hard postage discount (see below) — hygiene *pays for itself*.
5. **Return-Service-Requested feedback loop**: physically encode RSR on the mailpiece so USPS returns corrected/undeliverable addresses for free, and pipe those corrections back into `source_health_tracker.py` to score which sources produce rot.

Definition of done: no mailpiece prints against an address that hasn't been CASS+DPV validated and NCOA-updated, and undeliverables feed back automatically.

### FREE path (design/code) vs PAID path (vendor + real 2026 price)

Unlike the scrub gap, a **large chunk of this is genuinely free** because USPS itself gives you free hygiene mechanisms and free NCOA reporting.

**FREE path:**
- **Return Service Requested (the free trick).** Print the **"Return Service Requested"** endorsement on the mailpiece. For First-Class and (via ACS) other classes, USPS will **return the piece with the corrected/forwarding address, or notify you it's undeliverable — and for First-Class this address-correction service is free**. You mail once, and USPS hands you back a corrected list at no per-record charge. This is the single highest-ROI free move: it turns your first drop into a self-cleaning list. (Traditional ancillary-service endorsements on First-Class provide forwarding + address correction at no extra fee; ACS electronic correction is near-free at fractions of a cent.)
- **TrueNCOA free report.** Upload your list to **TrueNCOA and get a 100% free report** showing 18/48-month move counts, vacancies, and invalid addresses through NCOA + CASS + DPV + RDI — you only pay if you want the corrected file exported. This lets you *quantify* your rot (confirm the ~34%) and validate the whole approach before spending a dollar.
- **All the routing/gate/feedback code** (fields, suppression logic, RSR feedback loop, presort file formatting) is free code on your existing skeleton.

**PAID path (cheap, and postage-discount-positive):**

| Vendor | What it does | Real 2026 price |
|---|---|---|
| **TrueNCOA** | NCOA + CASS + DPV + RDI, corrected file export, flat all-inclusive | **$20 per file** flat (free report first; pay only to export corrections). Best fit for this engine's periodic batch model. |
| **Melissa (Melissa Direct / Data)** | CASS standardization + NCOA move-update, bulk tiers | **$2.25 per 1,000 records** (24-month NCOA), **$2.95 per 1,000** (48-month); minimums **$40 / $50**. At 17K records ≈ **$38–$50** for a full 48-month pass. |
| **Market range (any CASS+NCOA provider)** | Bundled hygiene | **$0.001–$0.05 per record** depending on volume/bundling. |

**The postage offset:** running CASS makes the list **presort-eligible**. 2026 Marketing Mail letters run roughly **$0.372 at 5-digit presort vs ~$0.433 mixed AADC** — a ~**14%** postage spread. On 17,003 pieces that's ~**$1,040 saved per drop** in postage alone — an order of magnitude more than the ~$40–$50 hygiene cost. **Hygiene is net-negative cost.** You save more on postage than you spend cleaning, before counting the wasted print/postage you *avoid* on the 34% dead pieces.

### For LEGAL gaps

This gap is **operational/postal-regulatory, not a statutory liability** like Gap 1 — there is no SC/NC statute creating a private right of action for mailing a bad address. The governing rules are the **USPS Domestic Mail Manual** (Move Update standard, CASS certification, ancillary service endorsements like Return Service Requested), and for *presort discounts* USPS requires **NCOA Move-Update compliance within 95 days** of the mailing date. So the only "requirement" is a postal-pricing one: to claim the presort/marketing-mail discounts, your list must be Move-Update compliant (NCOA-processed) — which the paid path already satisfies. No consent or solicitation statute is triggered by mail hygiene itself (though the *content* of SC mail still implicates §30-2-50 from Gap 1, since "commercial solicitation" there explicitly includes contact "by mail").

### Effort + build estimate

**Low.** Most of the value is a free USPS mechanism (RSR) plus a ~$20–$50 batch API call. Build is: `mail_hygiene.py` (vendor batch upload/API + writeback), ~9 new `models.py` fields + migration, the DPV/vacant suppression + NCOA-substitution gate in the mail path, RSR endorsement on the mailpiece template, and the return feedback loop into `source_health_tracker.py`. **Estimate: 1–1.5 days** + trivial recurring vendor cost.

### Recommended action

1. **Add "Return Service Requested" to every mailpiece today** — free self-cleaning list, zero build beyond the template endorsement.
2. **Upload the current board to TrueNCOA's free report** to quantify actual move/vacant/invalid rates and confirm the rot before scaling spend.
3. Build `mail_hygiene.py` and run a full **CASS+NCOA pass** (TrueNCOA $20/file or Melissa ~$40–50 for 48-month) before the next drop; add the 9 model fields.
4. **Gate the mail path** on DPV, substitute NCOA new addresses, and route confirmed vacants to a dedicated absentee template (vacancy is a *motivation* signal, not just a suppress).
5. **Capture the presort discount** — the ~14% postage spread makes hygiene net-negative cost — and pipe RSR returns back into `source_health_tracker.py` to grade which sources produce address rot.

---

Sources:
- [S.C. Code §30-2-50 (scstatehouse.gov)](https://www.scstatehouse.gov/code/t30c002.php) · [Justia 2024 §30-2-50](https://law.justia.com/codes/south-carolina/title-30/chapter-2/section-30-2-50/)
- [N.C. Gen. Stat. §75-102](https://www.ncleg.gov/EnactedLegislation/Statutes/PDF/BySection/Chapter_75/GS_75-102.pdf) · [§75-104](https://www.ncleg.gov/enactedlegislation/statutes/html/bysection/chapter_75/gs_75-104.html) · [NC Ch.75 Art.4](https://law.justia.com/codes/north-carolina/chapter-75/article-4/)
- [TCPA Violations Penalties 2026 (Prospeo)](https://prospeo.io/s/tcpa-violations-penalties) · [DNC.com penalties](https://www.dnc.com/blog/what-are-penalties-associated-tcpa-violations) · [DNC.com TCPA Reassigned ID](https://www.dnc.com/tcpa-reassigned-id/) · [ActiveProspect DNC rules / 31-day](https://activeprospect.com/blog/do-not-call-rules/)
- [TCPA Litigator List pricing](https://tcpalitigatorlist.com/) · [TextP2P scrub pricing](https://textp2p.com/contact-scrubs/) · [Reassigned Numbers Database](https://www.reassigneddb.us/)
- [TrueNCOA pricing / free report](https://truencoa.com/pricing/) · [Melissa/NCOA+CASS provider pricing 2026 (DirectMail.io)](https://directmail.io/blog/best-ncoa-cass-providers-2026/) · [2026 USPS postage rates & presort (Mailpro)](https://www.mailpro.org/post/usps-postage-rates-2026/) · [USPS presort math (DirectMail.io)](https://directmail.io/blog/usps-postage-rates-2026-presort-dropship-commingle)


## Gap 3 — Disposition & Cash-Buyer Sourcing

### What it is & why it BLOCKS a close (even when the row is 100% filled)

A perfectly-scored lead card tells you the property is worth acquiring. It does **not** tell you *who buys it from you and for how much*. In wholesale and gator, the deal is not closed when the seller signs — it's closed when an **end buyer** funds. A fully-enriched row with ARV, payoff, lien stack, equity, distress tier, contact, and a signed contract is still worth **$0** if you cannot find a cash buyer inside your inspection/assignment window. Disposition failure is the single most common way a "great lead" dies: you tie up a property at a good number, then discover you have no buyer, blow the closing date, and either lose your earnest money or eat a double-close you can't fund.

The three sub-failures:

1. **No buyer list.** You have 17,003 acquisition leads and zero curated demand. Every deal becomes a cold-start "who wants this?" scramble.
2. **No buy-box match.** Even with a buyer list, a rural 40-acre timber tract and a Greenville infill teardown go to totally different buyers. Blasting the whole list is spam and burns your buyer relationships.
3. **No assignment-fee realism.** You need to know what spread the market will actually bear *before* you lock a contract, so your max acquisition offer leaves room for a real fee. Lock too high and there is no assignable margin — the deal is dead on arrival regardless of how motivated the seller is.

### Current state in the engine (what's actually there)

More is built here than the "16 sections skipped the machinery" framing implies. Concretely, in `/Users/cashhigh/foreclosure-scraper`:

- **`enrichment_buyer_match.py`** — a working dispo tagger. Matches each lead to buyers by `region` (WNC vs Upstate-SC) ∩ `category` (land / multifamily / commercial / residential) and writes `raw["buyer_match"]` onto the card. Gated behind `BUYER_MATCH=1`. It layers three sources: a hand-curated 188-buyer universe (`data/land_buyers.json`), direct "we-buy-land"/"we-buy-houses" flip lanes, and the empirical layer below.
- **`scripts/build_buyer_registry.py`** — the FREE ROD-mined harvester. It already does exactly the "mine recent all-cash grantees" idea in the assignment: repeat **entity grantees on recorded DEEDs** = live cash buyers → `data/discovered_cash_buyers.json` (currently **423 discovered buyers**, ranked by deal count, generated 2026-07-01, 75-day window, min 2 deals). Non-bank grantees on **mortgages/deeds-of-trust** = private/gator lenders → `data/private_lenders.json`. Sources are the same free ROD indexes the engine already reaches (Acclaim/Harris, CCHS).
- **`enrichment_buyer_match._discovered_for()`** already surfaces `recent_cash_buyers` (county/region + land-vs-improved appetite fit) and a `gator_lenders` lane that only fires on HOT/WARM or SUBJECT_TO/FIX_FLIP/GATOR/WHOLESALE strategy-fit leads (from `enrichment_strategy_fit.py`).
- **`assessment.py`** has `max_bid_70()` (the 70%-rule acquisition ceiling: `0.70 * ARV − rehab − fees`).

**The real gaps that remain** (this is what "solved" has to fill):

1. **No contact resolution on the discovered buyers.** `discovered_cash_buyers.json` entries are `{name, deals, counties, buys, sample_parcels}` — an LLC name and a deal count, no phone/email/agent. You can't send to a name. (The comment in the build script even says "contact via SoS registered-agent or skip-trace" — that join is designed but not wired.)
2. **Match is coarse (region ∩ category), not a real buy-box.** No price band, no acreage band, no beds/baths, no property-condition or ARV-range filter. So a buyer who only pays sub-$150k gets surfaced on a $600k lead.
3. **No assignment-fee / spread realism anywhere.** Nothing computes the assignable spread or checks that `max_bid_70` leaves fee room. `assessment.py` sizes the *acquisition* ceiling but never the *disposition* margin.
4. **No dispo packet / blast tooling.** No "email this deal to the N matched buyers" output equivalent to the seller-side `outreach.py` maillist.

### What "solved" looks like (concrete deliverable)

A `disposition.py` module + a `data/buyer_contacts.json` join that produces, for every HOT/WARM lead, a **ranked buyer shortlist with reachable contact and a realistic fee estimate**, plus a one-click dispo packet. Specifically:

- **Buyer contact resolution.** Extend `build_buyer_registry.py` to run each discovered LLC grantee through the existing free **NC SoS registered-agent enricher** (`project_sos_agent_enricher` — agent + officers, free) and the free absentee/skip-trace path already in the engine, writing `phone/email/agent/mailing` back onto each buyer record. This turns 423 names into 423 contactable buyers.
- **Real buy-box scoring.** Replace region∩category with a scored match: derive each buyer's implied buy-box from their `sample_parcels` (median sale price, price range, acreage range, land-vs-improved, county set — all already in the ROD/assessor data the engine holds), then score a lead against it. Surface top-5 by `(same_county, in_price_band, in_size_band, deal_count)`.
- **Assignment-fee realism field.** Add `disposition_fee_estimate` to the card: `min(0.5 × projected_buyer_profit, market_cap)` where market_cap is a per-tier band, and a hard gate that flags any lead where `max_bid_70 − est_acquisition_price` leaves < a floor fee. 2026 market anchors to bake in: national average assignment fee ≈ **$13,000**, typical range **$5k–$20k**, and **North Carolina specifically runs high at ~$22k average** — so a WNC single-family in equity should model a $10k–$20k fee, while thin-margin or low-ARV rural land should model $3k–$8k and get flagged if the spread won't cover it. Rule of thumb to encode: a wholesaler captures up to ~50% of the end-buyer's expected profit.
- **Dispo packet output.** A `docs/dispo_blast.csv` (buyer name, contact, matched leads) + a per-deal one-pager text (address, ARV, rehab, max buyer price, "why it fits your box") mirroring the seller-side `write_maillist()` pattern — generation local/free, sending left to operator.

### FREE path vs PAID path

**FREE (build):**
- Cash-buyer sourcing is *already* free and mostly built — repeat-grantee ROD mining. The only new build is (a) the SoS/skip-trace **contact join** (both enrichers already exist in the engine), (b) buy-box **derivation from `sample_parcels`** (data already on hand), and (c) the **fee-realism field** in `assessment.py`. No new vendor.
- This is the entire competitive point of the engine: paid tools sell you a cash-buyer list; you *mine your own* from the same public deed records, current and local, for $0.

**PAID (vendor, real 2026 pricing) — only if you want a pre-packaged national buyer network or a JV dispo desk:**
- **PropStream** ~$99/mo (cash-buyer search by area, skip-trace add-on).
- **BatchLeads** — additional records / skip-trace credits at **~$0.04–$0.15/record**; plans bundle 250–1,000 skip credits/mo.
- **Datazapp** skip-trace at **~$0.03/record**; **Tracerfy** pay-per-hit.
- **Investorlift / dispo marketplaces** — subscription blast networks, generally **$300–$1,500/mo** tier depending on plan; only worth it once you have consistent inventory. For 17k leads with your own mined buyers, this is redundant at this stage.

**Verdict:** stay FREE. The paid tools duplicate what the ROD harvester already produces; the only thing worth buying is cheap skip-trace credits (~$0.03–$0.04/record via Datazapp/BatchLeads) *if* the free SoS-agent join comes back thin on a given buyer.

### LEGAL (this gap is where the 2026 statute changes bite hardest)

Disposition = marketing/assigning a contract, and **both states changed the law in the last ~2 years specifically to regulate this.** This is not optional color; it constrains how the dispo module is allowed to operate.

- **North Carolina — HB 797, effective October 1, 2025.** NC now defines **residential wholesaling as brokerage activity under Chapter 93A**, meaning soliciting, marketing a contract, or assigning/optioning a residential contract **requires a real estate broker license**. The law explicitly folds **double-closings** into the definition, closing the old workaround. It also grants the homeowner a **30-day right to cancel** the purchase contract, a right to a **full copy of the contract at signing**, and requires **refund of any payments within 10 business days** of cancellation. Practical impact on the engine: for NC residential leads, disposition-by-marketing must be done by a licensed broker, or restructured (buy-and-resell taking title, or true option). The dispo packet for NC residential should carry a compliance flag. (Statute background: NCGS Chapter 93A; disclosure duties under NCGS 47E-4.) Sources: [realestateskills.com NC wholesaling](https://www.realestateskills.com/blog/wholesaling-real-estate-legal-north-carolina), [NC HB797 BillTrack50](https://www.billtrack50.com/billdetail/1882901), [NCGS 47E-4](https://www.ncleg.gov/EnactedLegislation/Statutes/PDF/BySection/Chapter_47E/GS_47E-4.pdf).

- **South Carolina — 2023 Act (Bill 4754), Title 40 Chapter 57.** SC defines wholesaling as "having a contractual interest in purchasing residential real estate from a property owner, then **marketing the property for sale** to a different buyer prior to taking legal ownership." The key legal line for the dispo module: **it is not the assignment that is illegal — it is marketing the underlying property.** SC permits advertising a **contractual position** (your equitable interest) but **prohibits marketing the property itself** if you don't hold legal title, and the SC Real Estate Commission has ruled an equitable interest is **not** an owner's legal interest, so it does **not** exempt you from licensure. NCGS analog: SC licensed firms/subagents are outright **prohibited from wholesaling** (40-57-350 duties). Practical impact: for SC leads, dispo copy must market *the contract/assignment*, never "this house for sale" — the module's generated one-pager must be worded to the contract position. Sources: [SC REALTORS wholesaling guidance](https://screaltors.org/sc-regulates-wholesaling-in-new-re-license-law/), [LLR SCREC guidance PDF](https://llr.sc.gov/re/News/Wholesaling-Assignment-of-Contracts-Guidance.pdf), [SC Title 40 Ch 57](https://www.scstatehouse.gov/code/t40c057.php).

**Encode into the module:** a `dispo_compliance` tag per lead — NC-residential → "broker license or take-title required (HB797)"; SC-residential → "market contract position only, never the property"; land/commercial → materially looser in both states (the statutes target *residential*). This keeps the free engine on the right side of the exact rules that were written to shut wholesalers down.

### Effort + build estimate

**Medium.** The hard parts (ROD buyer mining, gator lane, curated universe, matcher scaffold) exist. Remaining work:
- Contact join (SoS-agent + skip-trace onto discovered buyers): ~0.5 day — both enrichers already exist.
- Buy-box derivation from `sample_parcels` + scored match: ~1 day.
- `disposition_fee_estimate` field + spread gate in `assessment.py`: ~0.5 day.
- Dispo packet CSV + per-deal one-pager + compliance tags: ~0.5 day.
- **Total ≈ 2.5 days.**

### Recommended action

Build FREE. Ship in this order: (1) wire the **contact join** so the 423 mined buyers become reachable — this is the highest-leverage half-day in the whole disposition gap; (2) add the **assignment-fee realism field + spread gate** to `assessment.py` so no lead gets contracted without provable margin (anchor to $13k national / ~$22k NC / $3k–$8k thin-land); (3) upgrade the matcher to a real **buy-box score**; (4) generate the **dispo packet** with per-state **compliance tags** baked in (NC HB797 take-title/broker flag; SC market-the-contract-only wording). Do not buy a dispo marketplace or buyer-list vendor — the engine already mines better, more local data for $0.

---

## Gap 4 — Outreach-Execution TCO (the true cost of *working* the leads)

### What it is & why it BLOCKS a close (even when the row is 100% filled)

Every one of the 16 data sections spent effort filling the card. **None** of them costed what it takes to *touch* the person on that card. This is the gap that quietly kills the whole engine's economics: a lead is free to *generate* but **not** free to *work**. Direct mail, skip-trace, ringless voicemail (RVM), and SMS all cost real money **per touch, per lead, per month** — and at 2–3k HOT/WARM leads on a multi-touch cadence, that working cost **dwarfs the data spend by roughly two orders of magnitude.**

Why it blocks a close: if you don't model TCO, you will either (a) under-fund outreach and never reach enough sellers to close anything (a scored lead you never mailed is worth $0), or (b) over-fund it and torch your budget before a single assignment funds. And on SMS specifically, getting the cost/compliance model wrong isn't just expensive — it's **legal exposure at $500–$1,500 per message** under the TCPA. The engine's founding premise is "FREE," but that only ever applied to *data acquisition*. The moment you start *contacting*, "free" ends, and nothing in the codebase acknowledges it.

### Current state in the engine

There is **no cost model of any kind** in the repo. Confirmed by grep across `src/` and `scripts/` — the only `cost`/`max_bid`/`spread` hits are the acquisition-side `max_bid_70()` in `assessment.py` (deal underwriting, not outreach spend) and unrelated porsche-scraper `max_bid`. Specifically:

- **`outreach.py`** *generates* content and a mail list (`docs/outreach_maillist.csv`) and tracks status in `docs/crm.json`, but its own docstring says: *"Actually SENDING (Gmail/Twilio/print-mail) is left to the operator."* It counts `contactable / with_phone / with_mailing` but attaches **no per-touch cost** and models **no cadence**.
- **`crm.json`** has lifecycle statuses (`new → contacted → offer_made → … won/dead`) but **no cost-per-lead or spend-to-date** field. You cannot compute cost-per-contact or cost-per-deal from it.
- **`source_health_tracker.py`** tracks *source* yield/health, not the *downstream working cost* of the leads a source produces — so you can't yet see that a source producing 500 phone-less rural leads costs far more to work (mail-only, no SMS/RVM) than one producing 500 phone-matched absentee owners.
- No A2P 10DLC / TCPA cost or consent modeling anywhere, despite `outreach.py` generating `sms_text()`.

**Bottom line:** the engine knows what to *say* to each lead across four channels and has zero idea what it *costs* to say it, or whether the budget survives contact with 2–3k leads.

### What "solved" looks like (concrete deliverable)

A `outreach_tco.py` module + a `docs/tco_model.json` config that produces a **full monthly working-cost model** and per-lead/per-channel costing wired into the CRM. Concretely:

1. **Per-touch cost table** (config, editable) with 2026 real rates (below).
2. **Cadence model** per tier: e.g. HOT = mail T0/T14/T30 + skip-trace once + RVM + SMS drip; WARM = mail T0/T21/T45 + skip-trace; COLD = single mail or none.
3. **`monthly_working_cost(n_hot, n_warm)`** that rolls channel × cadence × volume into a monthly burn number and a **cost-per-lead-worked** and projected **cost-per-deal** (given a conversion assumption).
4. **CRM spend fields**: stamp each `contacted` event with channel + unit cost so `crm.json` yields real cost-per-contact and cost-per-deal over time.
5. **A budget guardrail**: given a monthly budget cap, tell the operator *how many* HOT/WARM leads can be fully worked this month — the missing "throttle" that keeps the FREE data engine from bankrupting itself on outreach.

### The actual TCO model (2026 rates, load-bearing numbers)

**Per-touch unit costs (verified 2026):**

| Channel | Unit cost (2026) | Notes |
|---|---|---|
| Direct mail postcard (4×6) | **~$0.55–$0.65** all-in | Marketing Mail presort; $0.65 is a safe planning number for 5k–25k runs. Letters/yellow-letters run higher. |
| Skip-trace (per record) | **~$0.03–$0.15**; premium ~$0.28 | Datazapp ~$0.03; BatchLeads ~$0.04–$0.15; premium skip ~$0.28 at ~72% hit. One-time per lead, not per touch. |
| Ringless voicemail (RVM) | **~$0.05/drop** retail; **~$0.004** BYOC/wholesale | Drop.co ~$0.05; Drop Cowboy BYOC as low as $0.004. |
| SMS | **~$0.004–$0.01/msg** + **$0.0031** compliance fee/msg | Plus A2P 10DLC carrier surcharges. |
| A2P 10DLC registration | **~$48+ brand vetting, $15–17/campaign, $1.50–$10/mo** | One-time + monthly fixed, before you send a single legal text. |

**Worked monthly model at 2,500 HOT/WARM (say 800 HOT + 1,700 WARM):**

- **Direct mail** (the workhorse): HOT gets 3 touches/mo, WARM gets ~1.3/mo → ≈ (800×3 + 1,700×1.3) ≈ **4,610 pieces × $0.62 ≈ $2,860/mo**.
- **Skip-trace**: one-time on the ~2,500 new/refreshed → 2,500 × $0.05 (blended) ≈ **$125** (amortized, mostly a first-month cost).
- **RVM**: HOT only, ~2 drops/mo on the ~60% with a phone → 800×0.6×2 ≈ 960 drops × $0.05 ≈ **$48/mo** (retail) or ~$4 BYOC.
- **SMS**: HOT only, TCPA-gated (see legal) → if run, ~800×0.6×2 ≈ 960 msgs × ~$0.007 ≈ **$7/mo** + 10DLC fixed ~$20/mo.
- **Monthly working cost ≈ $2,900–$3,100**, dominated ~90% by **direct mail**.

**Now the whole point — compare to data spend:** the entire engine's *data* cost is **$0** (free scrapers) plus trivial fixed infra. Even if you were paying for data, a premium data platform is ~$99/mo. So working the leads costs **~$3,000/mo vs ~$0–$100 of data** — the working cost is **~30–100× the data spend**, and scales linearly with lead count while data cost stays flat. Push to the full 3k HOT/WARM and mail alone clears **$3,400+/mo**. This is the number that actually governs whether the engine is viable, and it lives entirely outside every one of the 16 data sections.

**Cost-per-deal sanity check:** at ~$3,000/mo working cost and a typical distressed-outreach conversion of ~0.5–1% of worked leads reaching a signed deal, 2,500 worked leads → ~12–25 contracts pipeline → a few closings/mo. Against a **$13k national / ~$22k NC** average assignment fee (Gap 3), the model closes comfortably positive — **but only if you throttle mail to the leads that actually justify a 3-touch cadence.** Blast all 17k and mail alone is >$10k/mo with most of it wasted on cold rows. The TCO model's real job is to enforce that throttle.

### FREE path vs PAID path

- **The model itself is FREE to build** — it's arithmetic + config, in-repo (`outreach_tco.py` + `tco_model.json` + CRM spend fields). No vendor.
- **The touches are inherently PAID** — there is no free way to physically mail a postcard or send a compliant text at scale. The lever is not "free vs paid," it's **which vendor / which channel mix minimizes $/contact:**
  - **Cheapest mail**: self-serve print-mail (Marketing Mail presort ~$0.55–$0.65) beats yellow-letter services.
  - **Cheapest voice/SMS**: **BYOC (bring-your-own-carrier via Twilio/SIP)** on Drop Cowboy etc. cuts RVM to **~$0.004/drop** (vs $0.05 retail) — a 90% cut, worth it above ~5k drops/mo.
  - **Cheapest skip**: Datazapp ~$0.03 / BatchLeads ~$0.04 vs premium $0.28 — use cheap tier first, premium only on HOT.

### LEGAL (this gap carries direct per-message liability)

Outreach execution is where **TCPA / A2P 10DLC** exposure lives, and it must be in the TCO model as both cost and constraint:

- **A2P 10DLC is mandatory** for any business texting US numbers at scale — explicitly including real-estate wholesalers. Registration: **~$48+ brand vetting, $15–17/campaign, $1.50–$10/mo**, plus $0.003–$0.005/msg carrier surcharge. Lead-gen / high-risk-financial content is often **rejected outright** by carriers, which directly threatens cold seller-outreach texting.
- **TCPA consent**: the FCC's one-to-one consent direction means cold-texting sellers **without prior express consent is high-risk**. Violation exposure is **$500/message (standard) and $1,500/message (willful)** — a single 10,000-message non-compliant blast is **$5M–$15M** theoretical exposure. Source: [messageiq TCPA/10DLC guide](https://messageiq.io/blogs/sms-marketing-laws/), [pitchprfct A2P 10DLC](https://www.pitchprfct.com/blog/a2p-10dlc-registration/).
- **State-level**: NC and SC solicitation/telemarketing rules (and the NC HB797 homeowner-protection regime from Gap 3) further constrain cold seller contact.

**Encode into the model:** treat **SMS as opt-in-gated and default-OFF** in the cadence; lead the HOT cadence with **direct mail + RVM** (RVM sits in a different, lower-risk regulatory bucket than SMS but is not risk-free — model it as such), and only layer SMS where you have a defensible consent basis. The compliance cost ($48 + ~$20/mo fixed for 10DLC) belongs as a line item; the *liability* belongs as a hard gate: no un-consented mass SMS, full stop.

### Effort + build estimate

**Low–Medium.** Pure in-repo arithmetic and config + light CRM wiring:
- `tco_model.json` config (unit costs + per-tier cadence): ~0.25 day.
- `outreach_tco.py` (`monthly_working_cost`, per-lead cost, cost-per-deal, budget-throttle): ~0.75 day.
- CRM spend-stamping on `contacted` events + a cost rollup: ~0.5 day.
- Dashboard/report line: ~0.25 day.
- **Total ≈ 1.75 days.**

### Recommended action

Build the model FREE and immediately — it's cheap and it's the number that decides whether the whole engine pencils out. Specifically: (1) drop a `tco_model.json` with the 2026 rates above; (2) build `outreach_tco.py` to output **monthly working cost + cost-per-lead + a budget-throttle** ("at $X/mo you can fully work N HOT + M WARM"); (3) **stamp spend into `crm.json`** so real cost-per-deal accrues; (4) hard-code the **SMS-off-by-default TCPA gate** and carry the 10DLC fixed cost as a line item. The strategic takeaway to surface on the dashboard: **data is free, contact is not — mail is ~90% of the burn, working cost is ~30–100× data spend, so the engine's real constraint is a mail-throttle on HOT/WARM, not more leads.** Buy nothing to build the model; when you start sending, minimize $/touch via Marketing-Mail presort and BYOC voice/SMS.

---

**Files referenced (all absolute):**
- `/Users/cashhigh/foreclosure-scraper/src/foreclosure_scraper/enrichment_buyer_match.py` (dispo matcher — exists)
- `/Users/cashhigh/foreclosure-scraper/scripts/build_buyer_registry.py` (free ROD buyer/lender harvester — exists)
- `/Users/cashhigh/foreclosure-scraper/src/foreclosure_scraper/data/discovered_cash_buyers.json` (423 mined cash buyers)
- `/Users/cashhigh/foreclosure-scraper/src/foreclosure_scraper/data/private_lenders.json` (gator/private-lender lane)
- `/Users/cashhigh/foreclosure-scraper/src/foreclosure_scraper/data/land_buyers.json` (188 curated buyers)
- `/Users/cashhigh/foreclosure-scraper/src/foreclosure_scraper/assessment.py` (`max_bid_70` — acquisition math, no dispo-fee/spread)
- `/Users/cashhigh/foreclosure-scraper/src/foreclosure_scraper/outreach.py` (content + maillist + CRM; no cost model)
- `/Users/cashhigh/foreclosure-scraper/docs/crm.json` (lifecycle status; no spend fields)
- `/Users/cashhigh/foreclosure-scraper/src/foreclosure_scraper/source_health_tracker.py` (source yield, not working cost)

**To build (net-new):** `disposition.py` + `data/buyer_contacts.json` (Gap 3); `outreach_tco.py` + `docs/tco_model.json` + CRM spend fields (Gap 4).


## Feedback loop / outcome tracking

### What it is & why it BLOCKS a close (even when the row is 100% filled)

Every score the engine produces — `distress_stack.tier` (HOT/WARM/COLD), `distress_stack.score`, the strategy-fit tags, the letter/copy that goes out — is a **prior belief** about what closes. Right now those beliefs are hand-set constants: `foreclosure_sale = 30`, `probate = 20`, `absentee = +8`, `senior_survives = −20`, HOT requires `stack≥2 AND equity≥med AND mailable` (all in `distress_score.py`). Nobody has ever checked those numbers against a single real outcome.

A fully-filled row does not close itself. The operator only has so many stamps, calls, and hours per week; the score's *entire job* is to rank which of 17,003 rows gets worked first. If a `+8` for absentee or a `30` for foreclosure is wrong, the operator systematically spends the scarce outreach budget on rows that never convert and skips rows that would have. The row is perfect; the **triage that decides whether a human ever touches it** is running blind. That is the block: the engine optimizes a proxy (stacked distress) that has never been tied back to the target (a signed contract). ARV already got this treatment — `backtest_arv.py` proved the 70%-rule was double-charging the selling fee and the fix moved `0.70→0.75` (per memory `project_valuation_calibration`). The lead score has had no equivalent reckoning. Until it does, "HOT" is an assertion, not a measurement.

There is a second, compounding cost: **source ROI is invisible.** `source_health_tracker.py` tells you a source is *alive* (produced listings) but never whether it produces *deals*. Spartanburg ROD and NC OneMap both "work." One may account for every won deal and the other zero, and today you cannot tell them apart, so you cannot cut the dead lane or double down on the live one.

### Current state in the engine (is anything there? cite files if known)

Partial, and it stops exactly where it would start being useful:

- **`outreach.py` / `crm.json` capture disposition but never learn from it.** `VALID_STATUSES` includes the full lifecycle (`new → contacted → offer_made → negotiating → under_contract → won / dead / not_interested`) and `crm.json` persists `{status, notes, history}` keyed by `dedupe_key` so status survives the weekly re-scrape. But inspecting the live `crm.json`: **all 100+ records are `"status": "new"` with a single `lead_created` history event.** The lifecycle is a schema nobody fills, so even the raw material for a feedback loop (won vs dead labels) does not yet exist in practice.
- **The CRM is not joined back to the signals at outcome time.** When a status *does* flip to `won` or `dead`, nothing snapshots *what the row looked like when it was scored* — its tier, score, signals, equity band, strategy tags, county, source. `distress_score.py` recomputes the stack fresh every run from current signals and overwrites `raw["distress_stack"]`; there is no frozen at-contact feature vector to correlate against the outcome later.
- **`distress_score.py` weights are hard-coded literals**, never read from a fitted file. Same for the `enrichment_strategy_fit.py` thresholds (`eq >= 0.40`, `long_tenure` proxy).
- **`source_health_tracker.py`** tracks per-source *volume* health only (zero-streak, sustained-bleed). No `won`/`contacted` join, so no per-source conversion or ROI.
- **The precedent exists and works:** `scripts/backtest_arv.py` is the exact pattern — read the board read-only, treat recorded sales as ground truth, report **median** error (heavy-tailed, never mean), bucket by confidence and county, write nothing. A disposition backtest is the same harness pointed at CRM outcomes instead of recorded sales.

So: the disposition *vocabulary* is there, the *plumbing to log it* is there, and the *backtest template* is there. What is missing is (a) the discipline/UX to actually set statuses, (b) a frozen at-contact feature snapshot, and (c) the re-fit script that closes the loop.

### What "solved" looks like (the concrete deliverable)

Three artifacts, mirroring the ARV loop:

1. **Frozen outcome log — `docs/outcomes.jsonl`.** Append-only. Every time a CRM status transitions to a *terminal* state (`won`, `dead`, `not_interested`) — or a meaningful mid-funnel one (`contacted`, `offer_made`, `under_contract`) — write one line: `{dedupe_key, ts, from_status, to_status, county, source, tier, score, stack, categories, signals[], equity_band, strategy_tags[], absentee, out_of_state, contactable, arv_confidence}`. The feature fields are copied from `raw["distress_stack"]` / `raw["strategy_fit"]` **at the moment of transition**, so the label is bound to the features the operator actually saw. This is the one net-new piece of data collection and it is nearly free — `outreach.py` already writes `crm.json` on every run; add a `set_status(key, new_status)` helper that appends to the log on change.

2. **Disposition backtest — `scripts/backtest_dispositions.py`** (read-only, writes nothing, exactly like `backtest_arv.py`). Reads `outcomes.jsonl` and reports, with small-n honesty:
   - **Contact→won and worked→won rate by tier** (does HOT actually out-close WARM out-close COLD? If HOT ≈ WARM, the HOT gate is not earning its complexity).
   - **Win rate by individual signal and by category** — the lift each signal carries, holding others roughly constant (start with simple per-signal contact-adjusted rates; a logistic fit once n supports it).
   - **Win rate by strategy tag** (is WHOLESALE closing and SUBJECT_TO dead, or vice versa?).
   - **Per-source conversion / ROI** — wons and under-contracts per 100 leads, per source. This is the lane-kill / double-down signal `source_health_tracker` can't give.
   - Everything reported as rates with n shown, and **suppressed below a floor (e.g. n<10)** so the operator never re-tunes on noise.

3. **A single fitted-weights file — `docs/score_weights.json`** — that `distress_score.py` reads at import (falling back to today's hard-coded defaults if the file is absent or thin). The backtest proposes updated weights; a human reviews the diff and commits the file. This keeps the loop **human-in-the-loop and auditable**, not an autonomous retrainer — the same posture as the ARV `0.70→0.75` change being a reviewed constant edit.

"Solved" = you can answer *"do our HOT leads close more than our WARM leads, which signals actually predict a deal, and which source pays for itself"* with a number and an n, and the score weights are a reviewed file instead of guesses.

### FREE path (design/code) vs PAID path (vendor + real 2026 price)

**FREE (recommended — this is entirely modeling + code discipline, no vendor):**
- Add `set_status()` + `outcomes.jsonl` appender to `outreach.py` (~40 lines).
- Write `scripts/backtest_dispositions.py` by cloning `backtest_arv.py`'s structure (percentile/median helpers, bucketed `fmt_block`, small-n suppression) — the harness already exists, only the eligibility filter and the metrics change.
- Make `distress_score.py` and `enrichment_strategy_fit.py` load thresholds from `score_weights.json` with the current literals as defaults.
- Fitting stays deliberately simple: contact-adjusted win rates per bucket first; a scikit-learn `LogisticRegression` on the frozen feature vectors only once you have ~50+ terminal outcomes. scikit-learn is free and already the kind of dependency this repo tolerates. **The only real cost is time-to-signal**: you need dozens of dispositioned leads before the numbers mean anything, so the enabling move today is the logging, not the model.

**PAID (not needed, listed for completeness):** a hosted CRM with built-in attribution/conversion analytics — REsimpli (~$99–$179/mo for REI), Podio + workflow add-ons, or a generic pipeline tool — would give disposition tracking and win-rate dashboards out of the box. But it replaces the free `crm.json`, adds a monthly bill, and still won't re-fit *your* distress weights, which is the actual goal. No vendor sells "re-fit my custom motivated-seller score against my closes." Skip it.

### Effort + build estimate

**Low–Medium.** Logging hook + `outcomes.jsonl` schema: ~half a day. `backtest_dispositions.py` cloned from the ARV harness: ~half a day. Weights-file plumbing in the two scorers: ~half a day. **~1.5 engineering days total.** The model itself waits on data and is another half-day once ~50 outcomes exist. The gating constraint is calendar time to accumulate labeled closes, not code.

### Recommended action

Ship the **logging half this week** — `set_status()` + `outcomes.jsonl` in `outreach.py` — because it is cheap and every day without it is a permanently unrecoverable outcome label. Enforce the discipline that operators actually set CRM statuses (the empty `crm.json` is the real blocker; a great backtest over zero labels is worthless). Clone `backtest_dispositions.py` now so it runs the moment data exists, and wire `distress_score.py` to read `score_weights.json` with today's constants as the committed default. Defer the logistic re-fit until you clear ~50 terminal dispositions; until then, run the plain per-tier/per-signal/per-source rate report and hand-adjust weights the way ARV was hand-corrected.

---

## Suppression & re-contact governance

### What it is & why it BLOCKS a close (even when the row is 100% filled)

Suppression is the pre-send gate that removes owners you are **not allowed to** or **should not** contact from the outgoing mail/SMS/call file: numbers on the Do-Not-Call registries, owners who already told you to stop, deceased owners, owners in an active bankruptcy stay, known TCPA/serial-plaintiff "litigators," and owners you contacted so recently that hitting them again reads as harassment. A perfectly enriched row makes this problem *worse*, not better: the more complete the contact data, the more channels you can fire, and the higher the legal exposure per row.

This is the one gap on the list that can produce a **negative-value close** — not just a missed deal but a lawsuit that costs more than any deal makes. The exposure is concrete and per-message:

- **South Carolina Telephone Privacy Protection Act (SC Code §37-21):** a private right of action of **$1,000 per violation**, raised to **up to $5,000 per violation for willful/knowing** violations, **plus the plaintiff's reasonable attorney's fees and court costs** (§37-21-80). A "telephone solicitation" is explicitly defined to include a **text or media message** to an SC-area-code wireless number for the purpose of offering to buy/sell property (§37-21-20) — so the engine's `sms_text()` is squarely in scope. §37-21-70 bars contacting anyone on the **National DNC Registry** or anyone who previously said stop (honored for **at least five years**); §37-21-30 limits calls to **8am–9pm** local without prior written consent.
- **North Carolina (G.S. §75-102 et seq.):** private right of action of **$500 (1st) / $1,000 (2nd) / $5,000 (3rd and each thereafter within two years)**, plus **treble or punitive damages and attorney's fees**; the statute's "unsolicited telephone call" expressly includes **text** communications and honors the DNC registry and prior stop requests.
- **Federal TCPA** sits on top: **$500 per call/text, $1,500 if willful**, no cap, every message a separate violation. Calls/texts *offering to buy the called party's real estate* are "telephone solicitations" subject to the National DNC rules — this is settled, and the wholesale-buyer letter/SMS is the textbook fact pattern plaintiff firms target.

So on a 17,003-row board where many SC/NC cell numbers came from a free skip-trace, a single unsuppressed blast is not a compliance footnote — it is a stack of $500–$5,000 claims with fee-shifting that a serial litigator is *paid* to manufacture. And the "deceased owner" and "bankruptcy stay" cases are worse than illegal: texting a grieving heir a cash-offer for their dead parent's house, or an owner whose automatic stay makes the whole solicitation void, torches the deal and the reputation even where damages are arguable. The row is 100% filled; sending to it is the liability.

### Current state in the engine (is anything there? cite files if known)

**Effectively nothing. This is the most exposed gap of the two.**

- **`outreach.py` builds the send file with zero suppression.** `generate_outreach()` marks a lead `contactable` on `owner AND (mailing_address OR phones)` and immediately drafts `sms`, `email`, `letter` and pushes every mailing address into `write_maillist()` → `docs/outreach_maillist.csv`. There is **no DNC check, no litigator check, no deceased check, no bankruptcy check, no prior-contact/frequency check** anywhere in the path. The only nod to compliance is the literal string `"Reply STOP to opt out."` appended inside `sms_text()` — which is a courtesy, not a suppression, and does nothing to stop the *first* unlawful text.
- **The signals to suppress on are already in the pipeline but unused for suppression.** `distress_score.py` reads `r.get("bankruptcy")` (weight 18) and treats estate/probate (`SMITH PRICILLA R (EST)` appears verbatim in `crm.json`, and `relationship_signal.kind == "probate"`) purely as **motivation to contact more** — the exact opposite of a suppression flag. A bankruptcy stay and a deceased record are being scored as *hotter*, then mailed, with no guardrail.
- **`crm.json` has the state to build re-contact governance but doesn't use it.** Every record carries `status`, `history[]`, `first_seen`, `last_seen`. A `not_interested` / `dead` status and a `contacted` timestamp are exactly what a suppression + frequency-cap join needs — but `outreach.py` never reads status back to *exclude* a lead, and (per the Feedback section) the statuses are all `new` anyway.
- **No suppression list files exist** (`docs/dnc_suppression.csv`, `opt_outs.csv`, `litigators.csv`, `deceased.csv` — none present).

### What "solved" looks like (the concrete deliverable)

A single **pre-send suppression join** that every outbound row passes through before it can enter `outreach_maillist.csv` or any SMS/call file — `outreach.py` calls it and *cannot* emit a suppressed row. Concretely:

1. **`suppression.py` with a `suppress(listings) -> (sendable, suppressed[with reason])`** function, called at the top of `generate_outreach()` and again inside `write_maillist()`. A row lands in `sendable` only if it clears **every** gate; suppressed rows get `raw["suppressed"] = {"reason": ..., "list": ...}` for audit and are written to a separate `docs/suppressed_log.csv` (never deleted — you must be able to prove why you didn't contact someone, and prove you *did* suppress a litigator).

2. **Gates, in order (each a simple keyed join):**
   - **Opt-out / stop (permanent):** any owner or phone in `docs/opt_outs.csv`, or any CRM record with status `not_interested`/`dead`, or history containing a stop event. Honored **5+ years** per SC §37-21-70. Channel-specific (an email opt-out doesn't clear an SMS).
   - **Deceased:** owner name flagged `(EST)`, `LIFE ESTATE`, `estate`, probate `relationship_signal`, or on a `docs/deceased.csv` — **suppress the deceased individual as an SMS/call target**, and *re-route* to a heir/probate mail track with different copy rather than blasting the decedent's cell.
   - **Bankruptcy stay:** `raw.get("bankruptcy")` truthy → suppress from *all* solicitation channels until confirmed discharged/dismissed. The automatic stay makes the solicitation legally void; this flag currently *raises* the score, so this gate is a direct inversion.
   - **Litigator / serial-plaintiff scrub:** phone in `docs/litigators.csv`. Free seed list is thin; this is where the paid path earns its keep (below).
   - **DNC:** phone on the National DNC Registry and SC/NC state DNC. This is the gate that legally *requires* a licensed data source to do at scale (below).
   - **Frequency cap / re-contact governance:** if `crm.json` shows this `dedupe_key` was `contacted` within the cool-off window (e.g. 30 days for SMS/call, shorter for mail), suppress until the window clears. Pure `crm.json` read — free, and the single highest-ROI gate to add first because it needs no vendor.

3. **Channel-aware:** mail (postcards/letters) is **not** a "telephone solicitation" and is largely outside TCPA/§37-21 — so the mail file can run with only opt-out + deceased + frequency gates, while **SMS and calls additionally require DNC + litigator + time-of-day.** The deliverable lets the mail lane keep flowing while the phone lane is gated, so compliance doesn't kill the #1 (mail) channel.

"Solved" = it is **structurally impossible** for a suppressed owner to appear in an outbound file, every suppression is logged with a reason, and the phone lane is DNC/litigator-scrubbed before a single text sends.

### FREE path (design/code) vs PAID path (vendor + real 2026 price)

**FREE (the join, the governance, and the "cheap" gates):**
- `suppression.py`, the ordered gate join, `suppressed_log.csv`, and channel-awareness are pure code (~1 day).
- **Opt-out, deceased, bankruptcy, and frequency-cap gates are 100% free** — they read files and `crm.json` you already own. Deceased/probate/estate and bankruptcy flags are *already computed*; this just inverts their use from "score higher" to "don't call."
- **Lead with the mail lane + frequency cap + opt-out gates**, which need no vendor and remove most of the harassment/reputation risk immediately.
- A **free litigator seed** can be bootstrapped from public TCPA-plaintiff dockets, but it will be incomplete — treat it as belt-and-suspenders, not the primary defense.
- **What free cannot legally do: scrub the National DNC Registry.** Access to the registry for scrubbing requires a paid, registered SAN (Subscription Account Number) via the FTC's telemarketing.donotcall.gov — there is no compliant free bulk-scrub. So the honest free posture is **"mail-first, and do not SMS/cold-call SC/NC cell numbers until the DNC gate is paid for."**

**PAID (only for the DNC + litigator + reassigned-number gates on the phone lane — real 2026 prices):**
- **National DNC Registry SAN (FTC):** the registry itself is government-run; fees are **per area code per year**, and access to the **first five area codes is free**, with a **2025–2026 fee of ~$81 per area code** above that and an annual **max around ~$22,000** for full national. For an 18-county SC/NC footprint you need only a handful of area codes (SC 803/864/854, NC 828/704/980/910…), so realistically **$0–$400/yr** — cheap and legally mandatory before any cold SMS/call.
- **Commercial litigator + DNC + reassigned scrub (the practical buy):** vendors bundle National DNC, state DNC, known-litigator, and reassigned-number scrubs so you don't manage the SAN plumbing yourself.
  - **TextP2P TCPA Litigator & DNC Scrub:** **$0.01 per non-unsubscribed number, $5.00 minimum** — cheapest observed, fine for the current ~17k board (~$170 to scrub the whole thing once, pennies on weekly deltas).
  - **TCPALitigatorList / DNC.com / Blacklist Alliance:** per-record scrubs and monthly plans in the **~$0.01–$0.05/record** range plus small monthly minimums; Blacklist Alliance and DNC.com add continuously-updated known-litigator databases (the real value-add over raw DNC).
- **FCC Reassigned Numbers Database** (to avoid texting a number that was ported to a new person who never consented — a common TCPA trap): FCC **cut query pricing 20% effective April 28, 2025** and added smaller tiers; short-term (1-month) and annual subscriptions exist with fractional-cent effective per-query costs at volume. For a weekly ~few-hundred-number delta this is a **low-tens-of-dollars/month** add, optional until SMS volume is real.

Net: **under ~$200 one-time + pennies-per-week** buys the entire compliant phone lane (DNC SAN for the footprint's area codes + a per-record litigator/DNC/reassigned scrub via TextP2P or equivalent). That is trivially less than **one** $1,000 SC §37-21-80 violation, let alone a fee-shifted class claim.

### For LEGAL gaps: statute + what it requires

- **SC Code §37-21 (Telephone Privacy Protection Act):** §37-21-20 defines a "telephone solicitation" to include **texts** to SC-area-code wireless numbers offering to buy/sell property; §37-21-30 restricts calls to **8am–9pm** local absent prior written consent; §37-21-70 requires honoring the **National DNC Registry** and any prior stop request for **≥5 years**; §37-21-80 grants **$1,000/violation, up to $5,000 willful, + attorney's fees and costs**. *Requires:* National DNC scrub, an opt-out list honored 5 years, time-of-day gating, and accurate caller ID.
- **NC G.S. §75-102 to §75-104 (Telephone Solicitations, Article 4):** covers **texts**, requires DNC-registry and prior-stop suppression, and provides **$500/$1,000/$5,000 escalating per-violation damages + treble/punitive + attorney's fees**. *Requires:* DNC scrub and honored opt-outs.
- **Federal TCPA (47 U.S.C. §227 / 47 C.F.R. §64.1200):** real-estate-purchase calls/texts are "telephone solicitations" subject to National DNC; **$500/call, $1,500 willful**, uncapped. *Requires:* National DNC scrub, internal do-not-call list, and (for autodialed/prerecorded) prior express written consent — so any automated SMS blast needs consent the engine does not have, meaning **manual/one-to-one texting only, post-scrub.**

Bankruptcy suppression is not §37-21/TCPA but the **automatic stay, 11 U.S.C. §362** — soliciting a debtor in an active case to sell collateral can be a stay violation; suppress until discharge/dismissal is confirmed.

### Effort + build estimate

**Low for the free join, Low-to-add for the paid gates.** `suppression.py` + ordered gates + logging + channel-awareness + `outreach.py` wiring: **~1 day.** Opt-out/deceased/bankruptcy/frequency gates are same-day (data already present). Paid gates are a thin API/CSV round-trip: registering the DNC SAN is paperwork (hours, plus the annual fee), and a TextP2P/DNC.com scrub is a **~half-day integration** (CSV out → scrub → CSV back → keyed join into `suppression.py`). **Total ~1.5–2 days**, most of it the free join.

### Recommended action

**Do this before the next outbound run — it gates legal risk, not deal flow.** Ship `suppression.py` with the four free gates (opt-out, deceased, bankruptcy, frequency-cap) and wire it as a hard filter in `generate_outreach()`/`write_maillist()` so no suppressed row can be emitted; invert the bankruptcy and estate/probate flags from "score higher" to "suppress phone / re-route to heir mail." Set the interim policy to **mail-first**: postcards and letters flow through the free gates now; **hold all cold SMS and calls to SC/NC cell numbers until the DNC + litigator scrub is live.** Then spend the ~$200: register a National DNC SAN for the footprint's area codes and run the board through TextP2P's $0.01/number litigator+DNC scrub, keyed back into the join. That converts the phone lane from an uncapped `$500–$5,000`-per-message liability into a compliant channel for a rounding-error cost. Keep `suppressed_log.csv` forever — the ability to prove you suppressed a litigator is itself the affirmative defense.

**Key file paths:** `/Users/cashhigh/foreclosure-scraper/src/foreclosure_scraper/outreach.py` (where both gates wire in), `/Users/cashhigh/foreclosure-scraper/docs/crm.json` (dispositions all `new` today — the real blocker for the feedback loop), `/Users/cashhigh/foreclosure-scraper/scripts/backtest_arv.py` (the harness to clone for `backtest_dispositions.py`), `/Users/cashhigh/foreclosure-scraper/src/foreclosure_scraper/distress_score.py` (hard-coded weights to externalize + bankruptcy/estate flags to invert for suppression).


## Lead Velocity / Urgency Tiering

### What it is & why it BLOCKS a close (even when the row is 100% filled)

A distressed-property lead is a **decaying asset**. The exact same lis-pendens row is worth a fortune in week 1 (owner just got served, 60-90 days of runway, every exit — subject-to, short-sale, cash-buyout, reinstatement-assignment — is still on the table) and worth almost nothing on sale-morning (owner is out of options, the property is about to transfer at auction, and your only remaining play is bidding against pros with cash). The engine today scores that row **identically on both days**. `distress_score.py` assigns `lis_pendens` a flat FINANCIAL weight of 28 forever; nothing in the tier logic reads how many days remain until `sale_date`. So a HOT row that is 4 days from the courthouse steps sorts next to a HOT row with 75 days of runway, and the operator — who can realistically work maybe 25-40 leads a week by phone/mail — has no signal telling them *which HOT lead will be dead by the time the postcard lands*.

This blocks closes in three concrete ways even on a fully-enriched row:
1. **Mail lead-time collision.** A first-class letter + owner response cycle is ~7-10 days. Any lead inside that window is unreachable by mail and must be worked by phone/door TODAY or not at all. The board doesn't flag it, so it gets a postcard that arrives after the sale.
2. **New-this-run leads get buried.** `new_listings.py` already tags `is_new` and computes a `top_new_for_alert` list, but that lives in a *separate* alert path. The main distress board and the mail-merge (`outreach.py` → `write_maillist`) don't boost a brand-new lis-pendens over a stale one the operator already declined three runs ago. The freshest, highest-intent leads don't rise.
3. **Wrong channel + wrong script.** A 60-day lead wants a soft "you have options" letter; a 5-day lead needs "I can close before Monday's sale, call me now." Without a days-until-sale band the outreach copy is one-size-fits-all (it is today — see `letter_text`/`sms_text`).

### Current state in the engine

Partial primitives exist but are **not wired into the score**:
- **`models.py`** carries `sale_date`, `upset_bid_deadline`, `redemption_deadline`, and `first_seen` (line 224, `default_factory=datetime.utcnow`) — every input the urgency curve needs is already on the object.
- **`enrichment_process_timing.py`** already labels NC power-of-sale vs SC judicial and stamps `redemption_deadline = sale_date + 365d` for SC tax sales. It computes the clock but never converts it to an urgency signal.
- **`new_listings.py`** stamps `raw["is_new"]` + `raw["first_seen_run"]` and has `top_new_for_alert()` that ranks new leads by `(is_lis_pendens, sale_date)` — this is the *only* place `sale_date` currently drives priority, and it's siloed to the email alert.
- **`distress_score.py`** — the actual operator board — has **zero** days-until-sale logic. `_LISTING_TYPE_SIGNAL` weights are static; `score_board()` never touches `sale_date`. The word "recency-aware" in the docstring refers only to the price-cut MLS diff, not to sale proximity.
- **Pipeline order (main.py):** `process_timing` (1884) → `score_board` (2050) → `mark_new_listings` (2219) → `generate_outreach` (2289). An urgency multiplier belongs inside or immediately after `score_board`, and it can read `redemption_deadline` because `process_timing` already ran.

Net: the data is present, the clock is computed, but the score is clock-blind.

### What "solved" looks like (the concrete deliverable)

A **velocity multiplier** applied inside `score_board()` plus a **`velocity` block** attached to each listing's `raw`, so every downstream consumer (board sort, mail-merge, email alert, outreach copy) reads the same urgency tier:

```
raw["velocity"] = {
  "days_to_event": 6,            # min(sale_date, upset_bid_deadline, redemption_deadline) − today
  "event": "foreclosure_sale",   # which clock is ticking
  "urgency_tier": "IMMINENT",    # IMMINENT / URGENT / ACTIVE / EARLY / STALE / NO_CLOCK
  "urgency_mult": 1.5,           # score multiplier
  "new_this_run": true,          # from is_new
  "channel_directive": "phone_or_door_only",  # mail can't arrive in time
}
```

Concrete rules (all free, pure computation):
- **Urgency bands** from `days_to_event`:
  - `IMMINENT` ≤7d → mult **1.5**, `channel = phone_or_door_only` (mail dead)
  - `URGENT` 8-21d → mult **1.35**, `channel = expedited_mail_ok`
  - `ACTIVE` 22-45d → mult **1.15**
  - `EARLY` 46-120d → mult **1.0** (the sweet spot for subject-to/short-sale — flag it, don't decay it)
  - `STALE` past sale_date with no upset/redemption clock and not sold → mult **0.5** (likely transferred; demote)
  - `NO_CLOCK` (no dated event, e.g. raw code-enforcement) → mult **1.0**, untouched
- **New-this-run boost:** `is_new` AND lis-pendens (earliest signal) → additive **+6** before the multiplier, so a fresh early-access lead outranks a re-seen one at equal distress.
- **NC upset-bid nuance:** if `upset_bid_deadline` is set and future, the deal is still *winnable* via a higher upset bid — keep it URGENT, not STALE, even past the sale date.
- **SC redemption nuance:** an SC tax row inside its 12-month redemption window is a *pre-sale motivated-seller* lead, not a dead one — band it by months-to-deadline, and note the escalating redemption penalty (3%→6%→9%→12% per SC Code §12-51-90) as a talking point that *increases* owner motivation as the deadline nears.
- **Outreach copy switch:** `generate_outreach` picks the letter/SMS variant off `urgency_tier` (IMMINENT = "close before the sale" script; EARLY = "you have options" script).
- **Board + mail sort key** becomes `(tier_rank, urgency_tier_rank, new_this_run, score)` so IMMINENT-HOT-new floats to the very top.

### FREE path vs PAID path

**FREE (recommended — this is the whole gap).** ~120-160 lines: a new `velocity.py` (or an extension of `distress_score.py`) that computes `days_to_event` from the earliest of `sale_date` / `upset_bid_deadline` / `redemption_deadline`, maps to a band, and returns the multiplier + channel directive. `score_board()` applies `score *= urgency_mult` and stores the block; `new_listings.py` already supplies `is_new`. No new data, no scraping, no API. The legal timelines are already reflected in the data the scrapers pull.

**PAID (what you're replicating, for scope-anchoring).** Investor lead desks charge for exactly this "which lead dies first" signal baked into their alerting: **PropStream** at **$99/mo** (Personal Basic, ≤10,000 leads) with pre-foreclosure/auction-date monitoring, or **BatchLeads** at **$119/mo** (skip-trace included) with list-stacking and status-change alerts. Neither exposes a per-lead *days-to-sale multiplier you can tune to your own 25-40-leads/week throughput* — you'd be paying $99-119/mo for a coarser version of a signal you can compute for free from data you already own. There is no reason to buy this.

### Legal specifics (drive the urgency curve, not a compliance blocker)

- **NC power-of-sale (NCGS §45-21):** notice of sale posted ≥20 days before the sale; sale date typically ~20 days after the clerk's hearing; then a **10-day upset-bid window (NCGS §45-21.27)** that *restarts* on each new upset bid. Implication: an NC lead is genuinely alive during the upset window — treat post-sale-but-in-upset as URGENT, not STALE.
- **SC judicial foreclosure (Master-in-Equity, SC Rule 71):** after judgment, sale is advertised once a week for **3 consecutive weeks**; sales are usually the **first Monday** of the month. Post-sale, bidding stays open **30 days** if a deficiency judgment is sought, **20 days** to comply if waived — another live-deal window.
- **SC tax-sale redemption (SC Code §12-51-90):** **12-month** redemption from the sale date; redemption cost escalates **3% / 6% / 9% / 12%** across the four quarters of that year. The rising penalty is itself a motivation curve — the closer to month 12, the more motivated the owner.

### Effort + build estimate

**Low.** New `velocity.py` module + one call site in `score_board` + a copy-variant switch in `outreach.py` + tests (band boundaries, upset-bid-not-stale, SC redemption band, new-this-run boost). **~1 day** including tests and a board/mail-merge re-sort.

### Recommended action

Build the FREE velocity multiplier now. It is the highest-leverage 1-day change in the acquisition layer: it reorders the entire operator board around *time-to-death*, routes IMMINENT leads to phone/door instead of a postcard that arrives too late, floats fresh lis-pendens to the top, and swaps outreach copy to match the clock — all from data already on the row. Add `raw["velocity"]` to the dashboard lead card and make it the primary sort. Wire the SC redemption-penalty escalation and NC upset-bid window in as talking points.

---

## Owner-Entity Portfolio Rollup

### What it is & why it BLOCKS a close (even when the row is 100% filled)

Distress clusters by **owner**, not by parcel. A landlord who stops paying is rarely behind on one property — they're behind on the whole portfolio. When a 6-unit landlord defaults, the engine surfaces **6 separate rows**, generates **6 separate letters** (`outreach.py` keys everything by per-parcel `dedupe_key`), writes **6 mail-merge lines**, and creates **6 CRM records** — with no signal anywhere that these are the *same seller*. That is a catastrophic mispricing of the opportunity:

- **It's one phone call, not six.** A portfolio-in-distress owner is the single highest-value lead type in wholesaling — one conversation can close a **bulk deal** (all 6 at a blended discount) instead of six independent negotiations. The engine can't even see that the opportunity exists.
- **The rows compete with themselves.** Six mid-tier parcels from one distressed owner scatter across the board and each looks like an ordinary single lead. Rolled up, "owner in default on 6 parcels, $X aggregate equity" is a top-of-board WARM→HOT bulk target. The whole is worth far more than the sum of the rows.
- **Duplicate, self-defeating outreach.** Six letters to the same person (often the same mailing address) reads as spam, burns the first-impression, and wastes postage. Worse, the operator may call about parcel #1, mark it "not_interested" in the CRM, and never realize the *same owner* has 5 more distressed parcels sitting in the board because the CRM has no owner-level view.
- **LLC blindness.** Investor owners hold under entity names ("SMITH HOLDINGS LLC," "BRC RENTALS LLC"). Without normalizing and grouping by entity, a portfolio owned through one LLC looks like unrelated strangers.

### Current state in the engine

The owner is captured but **never used as a grouping key**:
- **`models.py`** has `owner_name` (line 219, GIS-backfilled record owner) and `defendant`. `dedupe_key()` groups strictly by **parcel/address/case** — never by owner.
- **`distress_score.py`** groups by `_parcel_key()` only (line 265). Its cross-listing logic ("same property in foreclosure AND tax sale") is exactly the right pattern — but applied at the *parcel* level, one abstraction too low. There is no `_owner_key()`.
- **`outreach.py`** has `_owner(li)` (line 67, reads skip-trace owner or defendant) — but it's used only to personalize a *single* letter's greeting and for `find_by_owner()` name search. CRM records (`crm.json`) are keyed per-parcel by `dedupe_key`; there is no owner-level record, no `properties[]` array, no portfolio status.
- **`crm.json`** stores flat per-parcel `{status, owner, property, county, ...}` — the `owner` field exists on every record but nothing rolls records up by it.
- **`source_health_tracker.py`, `enrichment_strategy_fit.py`** — unrelated to this gap.

Net: every ingredient (owner_name, defendant, skip-trace owner, mailing address, per-parcel distress + equity) is on the rows. Nothing joins them.

### What "solved" looks like (the concrete deliverable)

An **owner-portfolio rollup pass** that runs after `score_board` and produces a portfolio object, plus a **de-duplicated, owner-aware outreach path**:

```
raw["portfolio"] = {
  "owner_key": "llc:smithholdings",     # normalized entity key
  "owner_display": "Smith Holdings LLC",
  "parcel_count": 6,
  "distressed_parcel_count": 6,
  "portfolio_ids": ["parcel:NC:buncombe:...", ...6...],
  "agg_equity": 412000,                 # sum of per-parcel equity
  "agg_owed": 288000,
  "is_bulk_target": true,               # >=3 distressed parcels, one owner
  "portfolio_tier": "HOT",              # rolled-up tier
  "primary_contact_key": "parcel:NC:buncombe:...",  # the one row to call on
}
```

Concrete rules (all free):
- **Owner-key normalization:** uppercase, strip punctuation, canonicalize entity suffixes (LLC/L.L.C./INC/LP/LLP/TRUST → one token), drop "ET AL / ETUX / ETVIR," normalize "LAST FIRST" vs "FIRST LAST" order, and join on **mailing address** as a secondary key to catch the same investor holding under two slightly-different names. Reuses the same normalization discipline already in `_normalize_parcel`/`dedupe_key`.
- **Group + roll up:** bucket all listings by `owner_key`; a bucket with ≥2 distressed parcels becomes a portfolio; ≥3 flags `is_bulk_target`. Aggregate equity/owed/parcel-count and take the **max** distress tier across the group (a portfolio is at least as hot as its hottest parcel, and the bulk angle can tier it up).
- **One primary contact, N properties:** pick a `primary_contact_key` (the highest-distress parcel with the best contact data). `generate_outreach` sends **one** bulk-offer letter to that owner listing all N properties, instead of N single letters. Mail-merge collapses to one row per owner.
- **Owner-level CRM:** add an `owners` section to `crm.json` keyed by `owner_key`, holding `{status, properties[], notes, history}`. Marking an owner "not_interested" suppresses re-surfacing *all* their parcels; "negotiating" flags the whole portfolio as a live bulk deal. Per-parcel records still exist and back-link to the owner record.
- **New bulk-deal outreach copy:** a `bulk_letter_text()` variant — "I understand you own several properties in the county that may be facing sale; I can make a single cash offer on all of them and close on your timeline."
- **Board surfacing:** a portfolio bulk-target renders as one consolidated card ("Smith Holdings LLC — 6 distressed parcels, $412k agg equity, HOT") with the parcels nested, so the operator sees the bulk opportunity at a glance instead of six scattered rows.

### FREE path vs PAID path

**FREE (recommended — this is the whole gap).** ~150-200 lines: a new `portfolio.py` with `owner_key()` normalization + a `rollup_portfolios(listings)` pass called after `score_board`; ~40 lines added to `outreach.py` for owner-level CRM + the bulk letter + collapsed mail-merge; a consolidated portfolio card in the dashboard. Zero new data — it's a group-by over `owner_name`/`defendant`/skip-trace-owner + mailing address the rows already carry.

**PAID (what you're replicating).** The "how many properties does this owner hold" signal is a headline paid feature: **PropStream** ($99/mo) and **BatchLeads** ($119/mo, now under PropStream's ownership) both sell **list stacking** and a *"quantity of properties owned"* filter to find portfolio owners, marketed with a "67% right-party contact rate." You would be renting a coarser, non-distress-aware version of a rollup you can compute exactly against *your own* 18-county distressed board for free. No purchase warranted.

### Legal specifics

No statute gates this gap — it is a pure data-join over public ownership records already ingested. The only legal-adjacent note is **outreach compliance**, which the portfolio path *improves*: collapsing six letters into one owner-level contact reduces duplicate-mailing spam risk, and the SMS path already carries the required opt-out ("Reply STOP") in `sms_text()`. (For entity owners, the registered-agent/officer contact from the existing SoS enricher can feed the primary-contact pick, but that's an enhancement, not a legal requirement.)

### Effort + build estimate

**Medium.** Owner-key normalization is the fiddly part (entity-suffix canonicalization, name-order heuristics, mailing-address secondary join, avoiding false-merges of common surnames — bound false-merges by requiring a shared mailing address when the name is a common non-entity surname). New `portfolio.py` + `outreach.py` changes + owner-level CRM schema migration + tests (LLC canonicalization, ≥3 bulk flag, tier rollup, no-false-merge on "SMITH" without shared address, single-letter collapse). **~1.5-2 days.**

### Recommended action

Build the FREE portfolio rollup after the velocity multiplier — it's the second-highest-leverage acquisition-layer change. Ship it in two steps: (1) `owner_key()` + `rollup_portfolios()` + `raw["portfolio"]` + the consolidated dashboard card (so the operator can *see* bulk targets); then (2) the owner-level CRM + single bulk-offer letter + collapsed mail-merge (so outreach stops sending six letters to one landlord). Guard against false-merges by requiring a shared mailing address to join two differently-spelled non-entity names. This converts the single most valuable lead type in wholesaling — a portfolio owner in distress — from six invisible scattered rows into one top-of-board bulk-deal call.

---

**Files referenced (all absolute):**
- `/Users/cashhigh/foreclosure-scraper/src/foreclosure_scraper/distress_score.py` — parcel-only grouping (`_parcel_key`, L265), static type weights (`_LISTING_TYPE_SIGNAL`, L114), clock-blind `score_board` (L331)
- `/Users/cashhigh/foreclosure-scraper/src/foreclosure_scraper/new_listings.py` — `is_new`/`first_seen_run` tagging + `top_new_for_alert` (siloed sale_date priority)
- `/Users/cashhigh/foreclosure-scraper/src/foreclosure_scraper/enrichment_process_timing.py` — computes NC/SC timing + SC 12-mo `redemption_deadline` (L57-60), never converts to urgency
- `/Users/cashhigh/foreclosure-scraper/src/foreclosure_scraper/outreach.py` — `_owner()` (L67) used only for greeting/name-search; CRM keyed per-parcel (L187); no owner rollup
- `/Users/cashhigh/foreclosure-scraper/src/foreclosure_scraper/models.py` — `sale_date`/`upset_bid_deadline`/`redemption_deadline`/`first_seen` (L191-224), `owner_name` (L219), parcel-only `dedupe_key` (L228)
- `/Users/cashhigh/foreclosure-scraper/docs/crm.json` — flat per-parcel records, `owner` field present but never grouped
- `/Users/cashhigh/foreclosure-scraper/src/foreclosure_scraper/main.py` — pipeline order: process_timing (1884) → score_board (2050) → mark_new_listings (2219) → generate_outreach (2290)

Sources: [SC foreclosure/Rule 71](https://www.sccourts.org/resources/judicial-community/court-rules/civil/rule-71/), [NC NCGS §45-21.27 upset bid](https://www.ncleg.gov/EnactedLegislation/Statutes/PDF/BySection/Chapter_45/GS_45-21.27.pdf), [NC foreclosure timeline](https://www.nolo.com/legal-encyclopedia/north-carolina-foreclosure-laws-procedures.html), [SC Code §12-51-90 redemption](https://law.justia.com/codes/south-carolina/title-12/chapter-51/section-12-51-90/), [PropStream/BatchLeads 2026 pricing](https://resimpli.com/blog/batchleads-vs-propstream/)


## Gap 8 — Manufactured-Home Titling (SC / NC)

### What it is & why it BLOCKS a close (even when the row is 100% filled)

A manufactured home (MH) in the Carolinas has a split legal life. It can exist in one of two mutually exclusive states:

- **Titled as a vehicle** — the home is chattel/personal property. Ownership lives on a certificate of title held by **SCDMV** or **NCDMV**, exactly like a car. The land underneath is a separate parcel with its own deed. Liens are recorded on the DMV title, not the deed.
- **De-titled / affixed as real property** — the paper title has been surrendered and cancelled, an affidavit is recorded at the Register of Deeds, and the home merges into the real estate. Now it passes with the deed and is covered by real-property liens.

The engine's lead card is keyed to the **parcel** — deed owner, assessor value, ROD liens, foreclosure filing. When the physical home on that parcel is still **DMV-titled as a vehicle**, every one of those parcel-keyed fields describes only the *dirt*. You can win the land at the foreclosure/tax sale and still not own the house sitting on it, because:

- The MH owner of record (on the DMV title) may be a **different person** than the deed owner (classic scenario: buyer bought the home from a dealer, rents/owns the lot separately, or a family member holds title).
- A **lienholder on the DMV title** (the MH retail installment lender — 21st Mortgage, Vanderbilt, Triad, a credit union) survives your real-estate foreclosure entirely, because it was never a real-property lien and was never named in the foreclosure. That lender can repossess and physically haul the home off your newly-bought lot.
- At closing/assignment, the title company demands the **DMV title** to transfer the home. If it's lost, in someone else's name, or has an open lien, the deal dies on the table — after you've paid.

This kills wholesale (you can't assign a home you don't control), subject-to (you can't take over a payment stream you can't verify), and fix-flip (you can't resell without clean title). A row that is 100% filled on the parcel side is still un-closeable if the MH title state is unknown or adverse. This is the single most common "clean-on-paper, dead-at-closing" failure mode in rural Upstate SC and Western NC, where a large share of the housing stock is manufactured.

### Current state in the engine

- **`enrichment_property_kind.py`** — detects that a property IS a manufactured home. It matches description keywords (`mobile home`, `manufactured home`, `double-wide`, line 39) and CAMA/assessor use-codes (`"MH "`, `"MH PARK"`, line 77) and tags `PropertyKind.MOBILE`. This is the *only* MH awareness in the pipeline.
- **What is missing:** there is no field for **title state**. Nothing checks whether the home is DMV-titled-as-vehicle vs. de-titled-as-real-property. `models.py` has no `mh_title_status`, `mh_titled_owner`, `mh_dmv_lien`, or `mh_vin` field. `enrichment_title_risk.py` classifies the *foreclosing party's* seniority but says nothing about vehicle-title status. `distress_score.py` and `enrichment_strategy_fit.py` treat a MOBILE-kind lead identically to a stick-built house for scoring and strategy routing — so a separately-titled MH can be scored a top wholesale lead when it is actually un-closeable.

So the engine knows "this is a mobile home" and knows nothing about the one fact that decides whether it can be closed.

### What "solved" looks like (the concrete deliverable)

A new `enrichment_mh_title.py` enricher plus 4–5 new `models.py` fields, populated for every `PropertyKind.MOBILE` (and any parcel whose CAMA record shows a MH improvement):

- `mh_title_status`: one of `real_property_affixed` / `dmv_titled_vehicle` / `unknown`
- `mh_titled_owner`: name on the DMV title (when discoverable) — surfaced when it ≠ deed owner
- `mh_owner_mismatch`: bool — deed owner ≠ MH title owner
- `mh_dmv_lien`: any lienholder recorded on the DMV title (survives real-estate foreclosure)
- `mh_vin` / `mh_serial`, `mh_year`, `mh_make`
- `mh_closeability_flag`: `clear` / `title-work-required` / `blocked`

And a scoring/strategy hook: if `mh_title_status == dmv_titled_vehicle` or `mh_owner_mismatch`, `enrichment_strategy_fit.py` demotes wholesale/subject-to and routes the lead to "verify DMV title before spending a dollar," and the dashboard shows a red **"MH — separate title"** banner.

**Detection logic (the free path is entirely about detecting affixture):**
A MH is **real property (safe)** when an affixture/retirement affidavit is recorded at the ROD. It is **still a titled vehicle (danger)** when no such affidavit exists. So the deliverable detects the presence/absence of the recorded affidavit and, secondarily, checks how the county assessor lists the improvement.

### FREE path vs PAID path

**FREE path (design/code):**

1. **Assessor CAMA record (primary, already reachable).** The engine already pulls county CAMA/GIS attributes (`enrichment_gis_attrs.py`, `enrichment_cama_condition.py`). MH-specific tells that are usually structured text on the card:
   - A **DMV decal / registration number** or a "personal property" MH tax account (separate from the real-property parcel bill) ⇒ still titled as a vehicle. Several Upstate SC counties bill MH as a distinct personal-property account — that split billing is the free smoking gun.
   - Assessor "building type / structure" = `MH` but assessed as **land-only** on the real-property card ⇒ home is not on the deed ⇒ likely still titled.
   - A recorded **VIN/serial + year/make** on the card gives you the key to a DMV lookup.
2. **ROD affidavit scan (definitive).** Search the county Register of Deeds index (the engine already scrapes multiple ROD systems — Aumentum, Spartanburg, Gaston, CCHS) for the recorded de-titling affidavit against the parcel's grantor/legal:
   - **SC:** "Manufactured Home Affidavit for the Retirement of Title Certificate" recorded per **S.C. Code § 56-19-510** (indexed like a deed, grantor = homeowner). Its presence = real property, safe. Its **absence** on a parcel that carries a MH = titled vehicle, danger.
   - **NC:** "Affidavit for permanent attachment" recorded per **G.S. 47-20.6** (the affidavit described in **G.S. 20-109.2**). Presence = affixed real property; absence = still NCDMV-titled personal property. NC also has form **MVR-46G** ("Removal of Manufactured Home from Vehicle Files") in the trail.
3. **Free DMV/records lookups for owner + lien on the title:**
   - **NCDMV** MH records are checkable by VIN/serial; a duplicate/records path exists and title cost is nominal (~$15–20). NC's own guidance is exactly this two-step: ROD for the affidavit, else NCDMV title system.
   - **SCDMV** MH titles are managed by mail; SCDMV title fee is $15. The free discriminator is the ROD affidavit + the county's split MH personal-property tax account, which you already touch.
4. **Wire into scoring.** Pure-Python rule in `enrichment_strategy_fit.py` / `distress_score.py`: `MOBILE` + no recorded affixture affidavit ⇒ set `mh_closeability_flag = title-work-required`, demote auto-wholesale, add dashboard banner. Zero new paid data.

**Effort of free path: Med.** The affidavit-index search reuses existing ROD scrapers; the new work is (a) the CAMA "split MH account / land-only + MH structure" parser, (b) the affidavit-presence check, (c) the models fields + strategy hook.

**PAID path (vendor + real 2026 price):**

- **DataTree (First American)** — title chain & lien report that pulls both the real-property chain and can surface MH/VIN detail. Investor plans run roughly **$69/mo** with **per-report pull-down fees** on top (title chain & lien reports priced by state/county/tier). Good when you want a single API/report instead of parsing each county.
- **Manufactured-home title service (e.g., Snickfish, MHISC dealers)** — they run the SCDMV/NCDMV title search and cure missing/mis-owned titles for you. Title-cure/lost-title work is a **flat per-home service fee, commonly ~$300–$1,000+** depending on how broken the chain is. This is a *closing-stage* spend, not a screening spend.
- **TitlePoint / SiteX (Black Knight/ICE)** — enterprise title-plant products with per-search pricing negotiated by contract; overkill for this footprint versus DataTree.

The free path answers the **screening** question ("is this closeable?") for $0; the paid path is only worth it at the **close** on a specific home you've already decided to pursue.

### LEGAL citations (what each statute requires)

- **SC — S.C. Code § 56-19-510 (Retirement of Title Certificate).** To convert a MH from vehicle to real property, the owner files with the county Register of Deeds/Clerk of Court a **"Manufactured Home Affidavit for the Retirement of Title Certificate"** in the statutory form, plus proof of ownership (recent deed) and the affidavit filing fee. The ROD records it **"as if it were a deed to real property"** (grantor = homeowner) and notifies the county assessor. On filing, the MH **"shall be treated for all purposes except condemnation as real property and title to the manufactured home is thereby vested in the lawful owner of the real property to which it is affixed."** **§ 56-19-520** governs releasing any existing DMV lien (Satisfaction Affidavit) as part of retirement. **No recorded § 56-19-510 affidavit = the home is still an SCDMV-titled vehicle.**
- **NC — G.S. 20-109.2 (Surrender of Title) + G.S. 47-20.6 (Affidavit for permanent attachment).** The owner **surrenders the certificate of title to NCDMV, which cancels it under G.S. 20-109.2**; then the owner (or the first-security-interest holder) records the G.S. 20-109.2 affidavit at the ROD per **G.S. 47-20.6**. After recording, the MH **"becomes an improvement to real property,"** liens on it are perfected/prioritized as real-property liens, **"all existing liens on the real property are considered to include the manufactured home,"** and **"no conveyance… shall attach to the manufactured home, unless… applicable to the real property… and recorded in the office of the register of deeds."** This section **controls over G.S. 25-9-334** (UCC fixture priority). **No G.S. 20-109.2/47-20.6 affidavit = the home remains NCDMV-titled personal property**, its DMV lienholder is untouched by your real-estate foreclosure, and its title owner may differ from the deed owner.

The operational rule the statutes give you: **the recorded ROD affidavit is the bright line.** Present ⇒ real property, safe to underwrite on the parcel. Absent ⇒ pull the DMV title before you bid.

### Effort + build estimate

**Med.** ~2–3 dev-days: `models.py` fields (0.25d); `enrichment_mh_title.py` — CAMA split-account / land-only-with-MH parser + ROD affidavit-presence check reusing existing ROD scrapers (1.5d); VIN capture + optional NCDMV/SCDMV lookup stub (0.5d); strategy/score hook + dashboard banner (0.5d). No new paid dependency.

### Recommended action

Build `enrichment_mh_title.py` on the FREE path and gate it to `PropertyKind.MOBILE` + any CAMA record showing a MH improvement. Ship the ROD-affidavit-presence check (SC § 56-19-510 / NC G.S. 20-109.2+47-20.6) as the primary signal, with the assessor split-billing / land-only-MH heuristic as corroboration. Wire `mh_closeability_flag` into `enrichment_strategy_fit.py` so a separately-titled MH is demoted out of auto-wholesale and shown with a red banner. Reserve DataTree/title-service spend for close-stage cure on homes you've already chosen to pursue. This closes the highest-frequency "clean-on-paper, dead-at-closing" gap in the Carolinas footprint.

---

## Gap 9 — Surviving-Lien-at-Foreclosure Max-Bid Math

### What it is & why it BLOCKS a close (even when the row is 100% filled)

When you buy at a foreclosure or tax sale, **you do not always take clean title.** Certain liens **survive the sale and ride along with the land**, becoming *your* debt the moment you win. Your true acquisition cost is the winning bid **plus every surviving lien.** If the engine's max-bid tells you to bid up to $120k but a super-priority HOA lien, a municipal water/sewer lien, and an IRS 120-day redemption right all survive, your real basis is higher and your margin can be negative before you've touched the rehab.

Which liens survive is **not a property-level fact — it is a jurisdiction × lien-type × which-lien-is-foreclosing rules question.** The same $9,000 HOA lien is wiped in one state and survives in another. The engine currently treats "max bid" as a pure valuation output and never subtracts surviving debt, so **every bid recommendation on a lead that carries a surviving lien is overstated.** A 100%-filled row with ARV, rehab, comps, and a lien stack still produces a *wrong* max bid, because the math never asks "which of these liens do I inherit?"

The five survival cases that matter in this footprint:

1. **HOA/COA super-priority.** Some states give associations a limited "super-priority" slice that primes even the first mortgage and survives its foreclosure. **Neither SC nor NC is a super-lien state for HOAs** — this is the single most valuable calibration in the matrix (below).
2. **Municipal water/sewer & special-district charges running with the land.** Utility/assessment liens that attach to the real property survive a sale and become the new owner's obligation.
3. **SC tax-sale "subject to" / caveat emptor.** SC tax sales are AS-IS; certain interests survive and the buyer takes subject to them, and title isn't incontestable until the redemption + additional periods run.
4. **IRS federal tax lien 120-day right of redemption.** After a non-judicial foreclosure of a senior lien, the U.S. can redeem the property for 120 days (26 U.S.C. § 7425(d)) — a cloud/claw-back on your title even when the sale nominally cleared the IRS lien.
5. **Senior mortgage surviving a junior sale.** Already partially handled by `enrichment_title_risk.py` (the whole first mortgage survives an HOA/2nd/CU sale) — but its dollar value is never subtracted from the bid.

### Current state in the engine

- **`valuation/calc.py` and `assessment.py`** — `max_bid_70(arv, rehab, fees_pct=0.05)` computes `0.70 * ARV - rehab - (0.05*ARV)`. That's it. **No lien term. No survival logic.** It has no idea what's foreclosing or what survives.
- **`enrichment_lien_stack.py`** — captures a lien stack (2nd mortgage / IRS / state-tax / HOA / judgment) onto the row. The data is collected but **never fed into the bid** — it's display-only.
- **`enrichment_title_risk.py`** — classifies the foreclosing party as senior vs junior and sets `surviving_senior_debt_risk`. This is a **boolean flag, not a dollar subtraction**, and it only covers the senior-mortgage case, not HOA super-priority / municipal / IRS / tax-sale survival. Its own docstring even notes NC/SC tax sales "are usually super-priority" but routes municipal to manual — i.e., the survival question is punted to a human today.
- **`enrichment_equity.py`** — does ARV − payoff − liens for an *equity* estimate, but that's the seller's equity, not the *buyer's* max-bid basis; the two are different calculations and the survival rules never enter either.

**Net:** the engine *has the lien data* and *has a seniority flag*, but the max-bid function is blind to both. Every surviving lien is currently ignored in the number the operator actually bids on.

### What "solved" looks like (the concrete deliverable)

A **lien-survival rules table** (`lien_survival_rules.py`) — a static, versioned matrix keyed by `(state, foreclosure_type, lien_type)` → `survives: bool` + a note + a statute cite — feeding a new `surviving_lien_total` term into `max_bid_70`.

New signature:
```
max_bid_70(arv, rehab, fees_pct=0.05, surviving_liens=0.0)
    bid = 0.70*arv - rehab - fees - surviving_liens
```
`surviving_liens` is computed by a new `enrichment_max_bid_liens.py` that walks the already-captured `enrichment_lien_stack.py` entries, looks each up in the rules table given the row's state + foreclosure type + the `enrichment_title_risk.py` seniority result, sums the ones that survive, and attaches:
- `surviving_lien_total` (dollars)
- `surviving_lien_detail` (list of {lien_type, amount, survives, statute})
- `irs_redemption_risk` (bool + 120-day window note)
- `max_bid_liens_adjusted` (the corrected bid)

The dashboard shows both the naive 70% bid and the **lien-adjusted** bid, with the surviving-lien line items and cites, so the operator sees exactly why the number dropped.

### The state / lien-type survival matrix (the rules table)

| Lien type | Which lien is foreclosing | SC — survives? | NC — survives? | Authority |
|---|---|---|---|---|
| **1st mortgage / DOT** | Junior lien (HOA, 2nd, CU, muni code-fine) sale | **Yes** — take subject to it | **Yes** — take subject to it | General priority; `enrichment_title_risk.py` |
| **1st mortgage / DOT** | Senior 1st-mortgage sale | No (extinguished) | No (extinguished) | General priority |
| **HOA / COA assessment** | 1st-mortgage foreclosure | **No** — SC is NOT a super-lien state; bank foreclosure primes HOA | **No** — foreclosing 1st-DOT purchaser "shall not be liable for the assessments… which became due prior to the acquisition of title" | SC: § 27-30-150 / § 27-31-210; **NC: G.S. 47F-3-116(d)&(j)** (no 6-mo super-priority, unlike NC condo 47C) |
| **HOA / COA assessment** | HOA's own sale | **Yes** (the debt being foreclosed) — but 1st mortgage survives on top | **Yes** — but 1st DOT survives on top | Same |
| **Property tax lien** | Any sale | **Yes — first lien, primes mortgages, survives** | **Yes — superior to all other liens, runs with the land** | **SC: Title 12 (12-49/12-51), tax lien is a first lien; NC: G.S. 105-356** |
| **Municipal water/sewer / special-district assessment** | Any sale | **Yes** — runs with the land | **Yes** — G.S. 105-356 covers sanitary/sewer/watershed district charges as tax-priority liens running with the land | NC: **G.S. 105-356**; SC: local ordinance/utility lien |
| **IRS federal tax lien** | Senior (non-IRS) lien sale, IRS given ≥25-day notice | Lien cleared BUT **120-day US redemption right survives** | Same | **26 U.S.C. § 7425(d)**; 28 U.S.C. § 2410 |
| **IRS federal tax lien** | Sale with NO proper 25-day IRS notice | **Lien SURVIVES in full** | **Lien SURVIVES in full** | 26 U.S.C. § 7425; IRM 5.12.4 |
| **State tax lien (SC DOR / NCDOR)** | Junior sale | Survives if senior in time | Survives if senior in time | recording-order priority |
| **Mechanic's / judgment lien** | Senior sale | No if junior; survives if senior-recorded | No if junior; survives if senior-recorded | recording-order priority |

The two highest-value calibrations this matrix bakes in: **(1) neither SC nor NC gives HOAs super-priority** — so a bank-foreclosure lead with a scary HOA balance does NOT need that balance subtracted (the old title-risk docstring's "usually super-priority" hedge is resolved to a hard rule), and **(2) property + municipal utility liens always survive and run with the land** — those must be subtracted on *every* sale type. The IRS 120-day right is modeled as a **redemption-risk flag + holding-cost/insurance haircut**, not a full subtraction, unless the 25-day notice was defective.

### FREE path vs PAID path

**FREE path (design/code):** The entire deliverable is a static rules table + arithmetic over data the engine already collects. Zero new data spend.
- `lien_survival_rules.py`: hand-built matrix above, each cell carrying `survives` + `statute` + `note`. Versioned so a statutory change is a one-line edit.
- `enrichment_max_bid_liens.py`: joins `enrichment_lien_stack.py` amounts × the row's `(state, foreclosure_type)` × `enrichment_title_risk.py` seniority → `surviving_lien_total`.
- Patch `assessment.py` / `valuation/calc.py` `max_bid_70` to accept and subtract `surviving_liens`, and add the IRS 120-day flag.
- **Amounts** come from what you already scrape: property-tax owed (`enrichment_tax_owed.py`, `enrichment_qpaybill_tax.py`), IRS/state liens (`enrichment_lien_stack.py`, `enrichment_dew_liens.py`, ROD lien scrapers). Where a specific HOA balance is unknown but the matrix says "wiped," you subtract $0 correctly anyway — the rules table saves you from needing the number.

**PAID path (only for the amounts, never the rules):**
- **DataTree title chain & lien report** (~$69/mo + per-report fee) to enumerate every recorded lien + amount when your free ROD scrape is thin.
- **A title company / attorney title search** at close — flat **$100–$450** per property in NC/SC — to confirm the surviving stack before you wire funds. This is the correct place to spend, at close, on a deal you've already picked. The survival *rules* are free and public; only the per-property lien *amounts* are ever worth buying.

### LEGAL citations (what each requires)

- **SC HOA — NOT super-priority.** SC HOA/COA assessment liens are prior to most liens **except the first mortgage** (S.C. Code § 27-30-150 for the HOA Act; § 27-31-210 for horizontal-property/condo). A **bank foreclosure primes and extinguishes the HOA lien** (SC "is not a super lien state"). Subtract $0 for HOA on a first-mortgage sale.
- **NC HOA — NOT super-priority (unlike NC condos).** **G.S. 47F-3-116(d):** the HOA claim of lien is prior to all liens "except… a mortgage or deed of trust… recorded before the filing of the claim of lien." **G.S. 47F-3-116(j):** a first-DOT foreclosure purchaser "**shall not be liable for the assessments against the lot which became due prior to the acquisition of title**" — the unpaid amounts become common expenses spread across all owners. No 6-month super-priority in 47F (that limited priority exists in some other states' condo acts, not NC planned communities). Subtract $0 for HOA on a first-mortgage sale.
- **NC property + utility liens — survive, run with the land.** **G.S. 105-356(a):** the tax lien "is superior to all other liens, assessments, charges, rights, and claims of any and every kind in… real property regardless of… whether acquired prior or subsequent," and covers **sanitary/sewerage/watershed improvement district** charges; "priority… shall not be affected by transfer of title." **Always subtract.**
- **SC property tax — first lien, survives.** SC ad valorem taxes are a **first lien on the property, senior to and taking priority over any mortgage**, attaching Dec 31 each year (Title 12, Ch. 49/51). SC tax sales are **caveat emptor / AS-IS**, and the tax deed is not incontestable until the 12-month redemption + an additional 12 months run (§ 12-51-90 redemption). **Always subtract taxes; flag the redemption/AS-IS cloud.**
- **IRS 120-day redemption.** **26 U.S.C. § 7425(d):** where real property is sold to satisfy a lien **prior to the United States**, the U.S. may redeem within **120 days of the sale or the local-law redemption period, whichever is longer.** The foreclosing party must give the IRS **≥25 days' notice** to extinguish the federal tax lien; **if notice is defective, the lien is not discharged and survives in full** (IRM 5.12.4). Model as a redemption-risk flag (holding-cost/insurance haircut) normally, full subtraction if notice defective.

### Effort + build estimate

**Low–Med.** ~1.5–2 dev-days: `lien_survival_rules.py` matrix (0.5d, it's the table above with cites); `enrichment_max_bid_liens.py` join over existing lien-stack + title-risk (0.75d); `max_bid_70` signature patch + regression on the committed board so bids only *drop* where liens survive (0.25d); dashboard dual-bid + surviving-lien line items (0.5d). No new scrape, no new vendor.

### Recommended action

Build `lien_survival_rules.py` + `enrichment_max_bid_liens.py` on the FREE path and patch `max_bid_70` to subtract `surviving_lien_total`. Hard-code the two footprint-specific truths — **SC and NC HOA liens do NOT survive a first-mortgage foreclosure, and property + municipal utility liens ALWAYS survive and run with the land** — and model the **IRS § 7425(d) 120-day right** as a redemption-risk flag (full subtraction only when the 25-day notice was defective). Show the naive 70% bid and the lien-adjusted bid side by side with cited line items. Then recompute the committed board so no lead ever recommends a bid that ignores debt you'd inherit at the courthouse steps. Reserve DataTree / title-search spend for confirming lien *amounts* at close, never for the survival *rules*, which are free and statutory.

---

**File paths referenced (all under `/Users/cashhigh/foreclosure-scraper/src/foreclosure_scraper/`):**
- `assessment.py` (lines 163–173: `max_bid_70`, no lien term — the Gap 9 fix site)
- `valuation/calc.py` (valuation entry)
- `enrichment_property_kind.py` (lines 39, 77: MH detection, no title-state — the Gap 8 build-on site)
- `enrichment_title_risk.py` (senior/junior party classifier — boolean, no dollars)
- `enrichment_lien_stack.py` (lien data captured, never fed to bid)
- `enrichment_equity.py`, `enrichment_tax_owed.py`, `enrichment_qpaybill_tax.py`, `enrichment_dew_liens.py` (existing lien/tax amount sources to join)
- `distress_score.py`, `enrichment_strategy_fit.py`, `models.py` (scoring/strategy/schema hooks)

New files to create: `enrichment_mh_title.py` (Gap 8), `lien_survival_rules.py` + `enrichment_max_bid_liens.py` (Gap 9).


## Gap 11: Legal/Compliance Posture (FCRA / UDAP / Wholesaler-Licensing / PII Retention)

### What it is & why it BLOCKS a close (even when the row is 100% filled)
A row can be perfectly scored — ARV, equity, payoff, distress score, verified phone, verified mailing address — and still be radioactive to *touch*. Compliance is the layer between "we know who to contact" and "we are legally allowed to contact them this way, using this data, and close the deal we intend." Four separate legal regimes each independently gate a close:

1. **FCRA (15 U.S.C. §1681)** — the skip-traced phone/email/relative data on 15k+ owners was obtained for *lead generation*, which is a permissible use. But the moment that same data touches a decision about a person's **credit, tenancy, insurance, or employment eligibility**, it becomes a "consumer report" and the whole FCRA apparatus (permissible purpose, adverse-action notices, dispute rights) attaches. A subject-to or seller-finance deal where the engine evaluates the *seller's* ability to keep paying the underlying note, or a rent-back/lease-option where the former owner becomes a tenant, is exactly where an engine silently crosses that line.
2. **UDAP — SC Unfair Trade Practices Act (SC Code §39-5-10 et seq.) and NC G.S. 75-1.1** — governs *how you solicit*. Deceptive mail ("YOUR HOME IS IN FORECLOSURE — ACT NOW" when it isn't, or mail dressed up to look like a government notice) is a per se violation. NC has a specific statute for mail generated off register-of-deeds records requiring a conspicuous disclaimer.
3. **Wholesaler-licensing** — SC now *criminalizes* unlicensed residential wholesaling (see below); NC has a bill pending that would do the same. If the engine's entire exit strategy on a HOT lead is "assign the contract for a fee" and you market the property, you are practicing brokerage without a license.
4. **PII data-retention / minimization** — holding names, phones, DOBs, and address history on 15k people who never consented and most of whom you will never contact is a standing liability (breach exposure, and a data-broker-registration question in a growing number of states). No retention policy = the pile only grows.

Any one of these turns a "closed deal" into a rescinded contract, a treble-damages UDAP suit, an unlicensed-activity referral, or a data-breach notification. None of them show up on the lead card.

### Current state in the engine
Based on the file map (`outreach.py`, `crm.json`, `distress_score.py`, `enrichment_strategy_fit.py`, `models.py`, `source_health_tracker.py`): **essentially nothing exists for this gap.**
- `outreach.py` sends SMS/email/mail but there is no evidence of a suppression/DNC list, a per-message compliance gate, or mail-template disclaimer injection.
- `enrichment_strategy_fit.py` routes a row to wholesale / subject-to / fix-flip / gator / land, but there is no flag that says "this exit requires a license in this state" or "this exit turns the seller into a tenant → FCRA."
- `models.py` almost certainly has no `consent_basis`, `data_source_permissible_purpose`, `retention_expiry`, or `suppressed` field on the owner/contact model.
- `crm.json` has no documented legal-hold or purge lifecycle.
- There is no `compliance.py`, no DNC scrub, no litigator/known-complainant scrub, and no written data-retention policy in the repo.

This is the single highest-severity gap because it is the only one that can produce **personal legal liability and criminal referral**, not just a lost deal.

### What "solved" looks like (the concrete deliverable)
1. **A one-page written compliance policy** (`docs/COMPLIANCE.md`) covering: permissible-purpose statement for each data source, the FCRA firewall rule, the UDAP mail/SMS rules, per-state wholesaling posture, and the PII retention schedule. This is the artifact you hand a lawyer or a partner.
2. **A `compliance.py` gate** that every outreach call in `outreach.py` must pass through, which:
   - checks a **DNC/suppression list** (federal DNC + internal opt-outs + known-litigator list) and blocks;
   - checks **quiet hours** by the contact's timezone (SMS/call);
   - injects the required **mail/SMS disclaimers** based on the source of the record;
   - blocks any channel to a contact whose `consent_basis` doesn't support it.
3. **New fields on the contact/owner model** (`models.py`): `permissible_purpose`, `consent_basis`, `suppressed` (+ reason), `first_seen`, `retention_expiry`, `dnc_checked_at`.
4. **An exit-strategy legal flag** in `enrichment_strategy_fit.py`: any row whose recommended play is *residential wholesale-and-market* in SC gets a hard `LEGAL_BLOCK` badge; subject-to / lease-option rows get an `FCRA_WATCH` badge.
5. **A retention/purge job** that expires contact PII for rows never worked after N months.

### FREE path vs PAID path
**FREE (this is 90% discipline + code, and it is the recommended path):**
- Write `docs/COMPLIANCE.md` yourself from the primary sources cited below. Cost: $0, ~1 day.
- Build `compliance.py` as a pure-Python gate. Federal DNC scrub the free way: register as a subscriber and download the DNC list for your area codes (the National DNC Registry gives the first 5 area codes free; SC+NC upstate/western footprint is a handful of area codes — 803, 864, 828, 704, 336 — likely within or near the free tier). Quiet-hours and disclaimer injection are trivial code.
- Known-litigator / TCPA-troll scrub: maintain an internal CSV; seed it from public TCPA-plaintiff lists.
- PII retention/purge: a scheduled Python job. $0.

**PAID (buy only what free can't cover well):**
- **DNC + litigation scrub as a service:** *DNC.com* / *Contact Center Compliance (DNC Scrub)* — roughly **$0.008–$0.03 per number scrubbed** depending on volume, or plans from ~**$500/yr**. *Blacklist Alliance* (TCPA litigator + DNC scrub) is the wholesaling-industry default, roughly **$100–$300/mo**.
- **Compliant SMS delivery:** if you SMS at volume you need 10DLC-registered A2P messaging (Twilio/Telnyx). Registration ~**$4 one-time brand + $1.50–$10/mo per campaign**; this is a hard requirement now, carriers block unregistered traffic.
- **A 30-minute consult with an SC/NC real-estate attorney** to bless `docs/COMPLIANCE.md` and your assignment/marketing workflow: ~**$200–$400**. Cheapest insurance you will ever buy given SC criminalized this.

### LEGAL gaps — statutes and what they require

**SC residential wholesaling — now regulated/criminal.** The revised **SC Real Estate Practice Act, SC Code §40-57-5 et seq.**, signed May 2024, added **§40-57-30(44)** defining "wholesaling" as *having a contractual interest in residential real estate, then marketing the property for sale to a different buyer before taking legal ownership, with expectation of compensation.* Per the SC REC **Advisory Opinion (Nov 14, 2024)**: **assigning** a contract is legal, but **marketing the underlying property** without a license is not. **§40-57-135** permits marketing a *contractual position* only if it does *not* "imply, suggest, or purport to sell, advertise, or market the underlying real property" — and the REC states compliance is "practically impossible" if you disclose the address, photos, beds/baths, sqft, tax-map number, condition, or neighborhood. Unlicensed brokerage under §40-57 is a criminal offense (misdemeanor) plus civil penalties. **Engine requirement:** for SC residential HOT leads, the only compliant plays are (a) buy-and-hold/close-yourself, (b) double-close (take title first), or (c) a *silent* assignment with zero property marketing. The engine must not surface an SC residential row into any "market this deal" workflow.

**NC wholesaling — legal today, bill pending.** Under **NC G.S. Chapter 93A** (Real Estate License Law), assigning your own purchase contract does *not* require a license today; but soliciting/marketing another's property for compensation is unlicensed brokerage. **NC House Bill 797 (2025-2026), the "Residential Property Wholesaling and We Buy Houses Homeowner Protection Act,"** would amend **G.S. 93A-2** to make residential wholesaling licensed brokerage and add a new **Article 8** giving the homeowner a **30-day right to cancel**, a **10-business-day refund** deadline, and a mandatory **14-point-font cancellation disclosure** in the contract — with failure to provide it a **per se UDAP violation**. **Status: NOT enacted** — referred to Senate Rules on May 1, 2025; would take effect Oct 1, 2025 for contracts on/after that date *if passed*. **Engine requirement:** track this bill; if it passes, NC flips to the SC posture and every NC purchase contract needs the cancellation clause.

**UDAP mail — NC deed-record solicitation disclaimer.** NC law (Chapter 75) requires that any solicitation document generated from register-of-deeds records carry a conspicuous top-of-document statement that it is **not from a government agency** and that **no action is legally required.** Violation = unfair trade practice under **G.S. 75-1.1**, exposing you to **treble damages under G.S. 75-16.** SC's UTPA (**SC Code §39-5-140**) similarly allows treble damages + attorney's fees for willful deceptive practices. **Engine requirement:** `outreach.py` mail templates for records-sourced leads must auto-inject this disclaimer; no "looks like a foreclosure notice" mailers.

**FCRA (15 U.S.C. §1681b).** A consumer report may only be pulled/used for an enumerated permissible purpose. Lead generation is fine; using skip-traced data to evaluate a person's eligibility for **credit (seller-financing/subject-to underwriting), tenancy (rent-back/lease-option), or insurance** converts it into FCRA-regulated use requiring permissible purpose + adverse-action notices. **Engine requirement:** a hard firewall — skip-traced fields are for *contact only*; any strategy that underwrites the seller must re-obtain data through an FCRA-compliant channel with consent.

### Effort + build estimate
**Med.** `docs/COMPLIANCE.md` + `compliance.py` gate + model fields + strategy-fit legal flags + purge job ≈ **2–3 focused days** of build. The attorney review and DNC-service signup are procurement, not engineering.

### Recommended action
1. **Today:** add the SC-residential `LEGAL_BLOCK` and subject-to `FCRA_WATCH` flags in `enrichment_strategy_fit.py` — this is a 1-hour change that stops the single worst outcome (marketing an SC residential wholesale deal).
2. **This week:** write `docs/COMPLIANCE.md` from the statutes above; build `compliance.py` as a mandatory pre-send gate in `outreach.py` with DNC scrub, quiet hours, and NC/SC mail-disclaimer injection; add the model fields and purge job.
3. **Before any paid outreach at volume:** 10DLC registration + a ~$300 attorney blessing of the assignment/marketing workflow and mail templates.
4. **Ongoing:** put NC H797 on a watch (re-check each session's legal sweep); if it passes, add the 14-point cancellation clause to NC contracts.

---

## Gap 12: Per-Field Provenance & Staleness

### What it is & why it BLOCKS a close (even when the row is 100% filled)
A filled cell answers "what is the value?" Provenance answers "**where did it come from, and when — and can I still trust it?**" These are different questions, and the gap between them is where deals die at the closing table. A `sale_date` of "2019-03" that was true when scraped but is now the *prior* sale because the property resold, an `arv` computed off comps that are now 9 months stale, a `payoff` estimate from a loan balance that has amortized, a `phone` verified 14 months ago and now reassigned — each is a 100%-filled cell that is quietly **wrong**. You act on it (fire a mailer, make an offer, model equity), and the deal blows up: the "distressed" owner already sold, the "high-equity" spread evaporates because the ARV was old, the "verified" number is a stranger (TCPA exposure). Worse, without per-field timestamps you **cannot even audit** which decisions were made on rotten data, so you can't tell whether the engine is getting better or just louder.

Freshness is not uniform across fields, which is the whole point: an `assessor_sqft` from 2021 is fine; a `foreclosure_status` from 2021 is worthless. A single row-level `last_updated` collapses these and hides the danger.

### Current state in the engine
- `models.py` most likely stores each field as a bare value with, at best, one row-level `scraped_at` / `last_updated`. There is no evidence of per-field `*_asof` timestamps or per-field `*_source`.
- The MEMORY note *"Enrichment pipeline facts — resolved leads PERSIST + auto-enrich"* confirms fields get backfilled over time from different sources at different times — which is *exactly* the scenario that makes a single row timestamp misleading, because `phone` might be 3 days old while `sale_date` is 8 months old in the same row.
- `distress_score.py` and the ARV/valuation calc consume these values with no staleness weighting — a stale comp counts the same as a fresh one (the valuation-calibration note tracks `arv_confidence` but that's noise/dispersion, not *age*).
- `source_health_tracker.py` tracks *source* health but not *field-level* age on the board.

Net: some coarse timestamp probably exists; **per-field provenance and staleness flags do not.**

### What "solved" looks like (the concrete deliverable)
1. **Per-field provenance triples.** For every material field, store `value`, `<field>_asof` (when this value was true/observed), and `<field>_source` (which scraper/source produced it). Implement as a small `Provenance` structure in `models.py` (a dict keyed by field, or parallel `_asof`/`_source` maps) so the board sidecar carries it without wiping — consistent with the MEMORY rule that board writers must use `load_board()`.
2. **A staleness policy table** — a per-field max-age config, because fields decay at different rates:
   - `foreclosure_status`, `auction_date`, `tax_delinquent_status`: **30 days** (hot, time-critical).
   - `phone`, `email`: **90 days** (reassignment risk / TCPA).
   - `arv`, `comps`, `payoff`: **120–180 days** (market drift).
   - `sale_date`, `owner`, `mailing_address`: **180 days** (recheck for resale/transfer).
   - `assessed_value`, `sqft`, `beds/baths`: **365 days** (slow-moving).
3. **A `staleness_flag` per row** computed at board-compile time: `FRESH` / `AGING` / `STALE`, driven by whichever *decision-critical* field is oldest relative to its policy. A HOT lead whose `foreclosure_status` is >30 days old is auto-demoted / re-queued, not fired on.
4. **Staleness-weighted valuation:** ARV and equity down-weight stale comps and surface a "valuation age" on the card, so a spread computed off old comps carries lower confidence.
5. **A cheap re-verify queue:** the job that lists exactly which fields on which HOT rows have gone stale, so re-scraping is targeted (re-pull `foreclosure_status` on 40 rows) instead of re-crawling everything.

### FREE path vs PAID path
**FREE (this is the correct path — it is entirely internal plumbing):**
- Add `_asof` / `_source` capture at the point each scraper writes a field. Every scraper already knows the current time and its own identity; this is a mechanical change to the write path. $0.
- Staleness policy = a Python dict. `staleness_flag` = a function run at compile. Re-verify queue = a filter over the board. All $0.
- Backfill for existing rows: seed `_asof` from the existing row-level timestamp where nothing better exists, and let the flag decay from there.

**PAID (not needed for the mechanism; only relevant to *refreshing* stale data faster):**
- Provenance/lineage frameworks (OpenLineage, Great Expectations for freshness assertions) are **free/open-source** — optional if you want formal data-quality tests, but overkill here.
- The only real spend is on *re-acquisition* of stale fields, which is the cost of running your existing (mostly free) scrapers more often — compute, not license.

There is no meaningful vendor purchase here. This gap is bought with engineering discipline, not dollars.

### For LEGAL gaps
Not a legal gap per se — but note the compliance overlap: a `phone_asof` older than ~90 days is a **TCPA risk signal** (number may be reassigned; the FCC reassigned-number database exists precisely for this). Staleness metadata is thus also a compliance input feeding Gap 11's `compliance.py` — an aged phone should trip a re-verify before any autodial/SMS.

### Effort + build estimate
**Low–Med.** The staleness policy, flag, and re-verify queue are **~1 day**. Threading `_asof`/`_source` through every scraper's write path is the bulk of the effort — **~1–2 days** depending on how many of the 75–91 scrapers write directly vs. through a shared `write_artifact`/`load_board` helper. If writes are centralized, it's a single choke-point change (Low); if scattered, it's mechanical but broad (Med).

### Recommended action
1. Add `_asof`/`_source` at the **shared board-write helper** first (biggest coverage for least work), then backfill the stragglers.
2. Ship the **per-field staleness policy + row `staleness_flag`** and wire it into board compile so HOT rows with a stale decision-critical field are auto-demoted and pushed to the re-verify queue. This alone kills the "already-sold / stale-ARV" false-HOT problem.
3. Feed `phone_asof` into Gap 11's compliance gate as a re-verify trigger.

---

## Gap 13: Source-Concentration Monitoring

### What it is & why it BLOCKS a close (even when the row is 100% filled)
Every individual row can be perfect while the *portfolio of rows* is one broken scraper away from collapse. If 40% of your HOT tier traces to a single source — say one Master-in-Equity (MIE) foreclosure roster, or the Column legal-notice API — then the day that source goes dark (site redesign, WAF, API filter drift, a paywall, a county switching vendors), your **deal flow craters** even though nothing on any existing card changed. This is a portfolio-risk / single-point-of-failure problem, and it is invisible at the row level by construction. The MEMORY history is full of exactly these silent deaths: *"Column source silent-death — API returns 200 + 0 results when filter format drifts,"* *"GovDeals Akamai bypass,"* *"eCourts WAF."* Each was a source that quietly stopped producing. If any of those had been carrying a plurality of your HOT leads, you'd have run dry without an alarm — because a source returning **zero rows** doesn't make any *existing* row look wrong; it just stops adding new ones.

The close it blocks is the *next* close: no diversified top-of-funnel, no pipeline. A HOT tier that looks healthy today but is 40% dependent on a fragile roster is a business that stops originating deals the moment that roster hiccups.

### Current state in the engine
- `source_health_tracker.py` **exists** and is the natural home — but from the MEMORY notes it appears oriented to *per-source liveness/failure classification* (did source X run, did it error, why), per the *"Failure classification: know exactly why each source failed"* work. That answers "is source X up?" It does **not** answer "what % of my HOT tier depends on source X, and am I dangerously concentrated?"
- The Column silent-death note is the tell: the tracker (or the pipeline) already had to learn that **200 + 0-results ≠ healthy.** That's a liveness fix. Concentration is the *next* layer: even a perfectly-live source can be a systemic risk if too much of the HOT tier rides on it.
- There is no evidence of a **concentration metric on the HOT tier by source**, nor an alert when any single source exceeds a threshold, nor a "what breaks if this source dies" impact estimate.

Net: liveness monitoring: **yes.** Concentration monitoring: **no.**

### What "solved" looks like (the concrete deliverable)
1. **A concentration metric, computed on the HOT tier, grouped by source.** At board-compile time, for the HOT (and optionally WARM) tier: `share_of_hot[source] = hot_rows_from_source / total_hot_rows`. Report the top sources by share and a concentration index (e.g., the max single-source share, plus an HHI across sources for an overall "how diversified" number).
2. **A threshold alarm.** If any single source's share of HOT crosses, say, **35%**, raise a `CONCENTRATION_RISK` flag on the board summary and in the source-health report. Tunable.
3. **A "source-down impact" projection.** For each top source, "if this went dark today, HOT tier drops from N to M (−X%)." This converts an abstract risk into a number a human acts on.
4. **Trend, not just snapshot.** Track share-of-HOT per source over time so a source *drifting* toward dominance (or silently *declining* — the early signature of a silent death) is visible before it's a crisis. This pairs with `source_health_tracker.py`'s existing liveness: liveness catches "went to zero," concentration-trend catches "quietly falling / quietly dominating."
5. **A diversification prompt.** When concentration is high, the report names the gap ("HOT tier is 41% Master-in-Equity rosters; add a second independent distress source in the same counties") so the fix is actionable, not just an alert.

### FREE path vs PAID path
**FREE (entirely the right path — this is a `groupby` over data you already have):**
- Every HOT row already carries (or, per Gap 12, will carry) a `source`. The concentration metric is a `collections.Counter` / `groupby` at compile time. The threshold flag, HHI, impact projection, and trend log are all pure Python over the existing board. $0, and it lives naturally inside `source_health_tracker.py`.
- Trend storage = append a small per-run JSON/CSV snapshot of `share_of_hot` per source. $0.

**PAID (unnecessary for this gap):**
- Generic monitoring/alerting stacks (Grafana, Metabase, a data-observability vendor like Monte Carlo/Bigeye) *could* visualize this, but they are wildly oversized for one metric on one board and most carry real cost (Monte Carlo/Bigeye are enterprise-priced, four-to-five figures/yr). **Do not buy anything here.** If you want a dashboard, the free tier of Metabase or a static HTML panel on the existing board render is more than enough.

### For LEGAL gaps
Not a legal gap. (Indirect tie: over-reliance on a single scraped source also concentrates *compliance* risk — if that one source is later deemed off-limits/ToS-walled, both your volume and your legal posture move together. Diversification is risk mitigation on both axes.)

### Effort + build estimate
**Low.** Concentration share + HHI + threshold flag + impact projection ≈ **half a day**, because the data is already on the board and `source_health_tracker.py` is the existing home. Adding the per-run trend snapshot and a line on the board render ≈ another **half day**. Call it **1 day total.**

### Recommended action
1. Add `concentration_by_source(tier="HOT")` to `source_health_tracker.py`; compute max-single-source share + HHI at every board compile.
2. Fire a `CONCENTRATION_RISK` flag when any source exceeds **35%** of HOT, and print the "if this source dies, HOT −X%" impact line in the source-health report.
3. Log per-run `share_of_hot` so drift (silent decline = early silent-death signal; silent rise = growing SPOF) is visible over time, complementing the existing liveness check.
4. When the flag trips, treat "add one independent distress source in the same counties" as a standing backlog item — this is the concrete antidote and it aligns with the ongoing new-source hunting already in the task history.

---

### Sources
- [SC LLR Real Estate Commission — Advisory Opinion on Exceptions to Wholesaling (Nov 14, 2024)](https://llr.sc.gov/re/News/Wholesaling-Assignment-of-Contracts-Guidance.pdf) — SC Code §40-57-30(44), §40-57-135
- [South Carolina REALTORS — SC Regulates Wholesaling in New RE License Law](https://screaltors.org/sc-regulates-wholesaling-in-new-re-license-law/)
- [NC General Assembly — House Bill 797 (2025-2026) bill lookup](https://www.ncleg.gov/BillLookup/2025/H797)
- [UNC SOG Legislative Reporting Service — H797 bill summary](https://lrs.sog.unc.edu/billsum/h-797-2025-2026)
- [NC General Statutes Chapter 93A — Real Estate License Law](https://www.ncleg.gov/EnactedLegislation/Statutes/PDF/ByChapter/Chapter_93A.pdf)
- [NC General Statutes Chapter 75 — Monopolies, Trusts, and Consumer Protection (G.S. 75-1.1, 75-16)](https://www.ncleg.net/EnactedLegislation/Statutes/PDF/ByChapter/Chapter_75.pdf)
- [FCRA permissible purpose overview (15 U.S.C. §1681b)](https://legalclarity.org/fcra-permissible-purposes-for-accessing-consumer-reports/)
- [FTC — 40 Years of Experience with the Fair Credit Reporting Act](https://www.ftc.gov/sites/default/files/documents/reports/40-years-experience-fair-credit-reporting-act-ftc-staff-report-summary-interpretations/110720fcrareport.pdf)


---

# Deep-Dive Round 7 — Real-World Forum Intel (BiggerPockets/Trustpilot; Reddit firewalled) (2026-07-02)


## Skip-trace match rates in the real world

### What the communities actually say
- A wholesaler running PropStream skip at scale reported the opposite of the marketing: "their contact data has been very poor. Lots of wrong/bad numbers and high email bounce rate... Of 1k properties only 20-30% may have any contact info at all" — and said BatchLeads "quality of data looks comparable." This is a *return* rate of 20-30%, not a right-party rate. (Christina Hall, https://www.biggerpockets.com/forums/93/topics/1157203-best-skip-tracing-website)
- BatchSkipTracing's own defenders on the forum cite the vendor's headline number, not measured results: "batchskiptracing.com has credit header data with 90-95% hit rate." Note this is a *hit* (data-found) claim, restated from Batch's marketing, not a connect/right-party figure. (Ivo Draginov, https://www.biggerpockets.com/forums/12/topics/474691-what-is-the-best-skip-tracing-sites)
- Consumer-grade tools are near-uniformly trashed. On accuracy: "I do not want the cheap websites like spokeo, intellius, and others that have a 5-10% accuracy rate." (Oscar Calle, https://www.biggerpockets.com/forums/93/topics/738078-skip-tracing-batchskiptracingcom) And on Spokeo specifically: "I use spokeo, but everyone i call the number is outdated or its the wrong number." (Elijah Crowder, https://www.biggerpockets.com/forums/12/topics/474691-what-is-the-best-skip-tracing-sites)
- Built-in/bundled skip (CRM-integrated) draws the same complaint: a user reported REIPro's built-in skip tracing "producing disconnected numbers and wrong contacts." (Dylan Harris, https://www.biggerpockets.com/forums/12/topics/1163870-best-skip-tracing-options)
- Free manual tools are the small-batch workaround: "I have had great success locating phone numbers using fastpeoplesearch.com. It is free, and I find that a lot of times I get cellphone numbers out of it" — but the same user flags it's practical only for 10-20 lookups and requires manual entry. (Nathan McBride, https://www.biggerpockets.com/forums/61/topics/714531-what-s-the-best-skip-trace-service)
- On cost, the cheap-bulk play people actually reach for is a dialer add-on, not a premium bureau: "Mojo Dialer has an add on for $40/month for unlimited skip-tracing. Mind-blowingly cheap" — with the poster noting $40 buys only ~200 skips at BatchSkipTracing rates. (Aaron Caddel, https://www.biggerpockets.com/forums/93/topics/738078-skip-tracing-batchskiptracingcom)
- DataZapp lands as the cheap-and-decent bulk option (~$0.03/record, $125 minimum ≈ 4,000 records, ~75-85% phone), but reviews are mixed, with some users calling the experience "shady" after data issues. TLO (~$1/skip) and IDI (~$0.50/skip) are cited as higher hit rate but 5-20x the cost, and both are gatekept — hard for a solo wholesaler to even open an account. (https://www.trustpilot.com/review/www.datazapp.com; https://debtorinspector.com/best-tlo-alternatives/)
- The distinction the communities keep circling: "A service might have a 95% hit rate but only 50% accuracy... High hit rates mean nothing if the data is wrong." Realistic quality-service benchmarks cited: overall accuracy 65-80%, any-phone 85-95%, *mobile* 55-70%, email 60-75%, current address 70-85%. (https://smartskip.io/resources/blog/how-accurate-is-skip-tracing)

### Consensus vs our blueprint recommendation
Lived experience **partially contradicts** the 76% figure — mostly because 76% is measuring the wrong thing. The blueprint (and Batch's marketing) frame 76% as a "right-party contact rate." Operators experience two separate, lower numbers stacked on top of each other:
1. **Match/hit rate** (any contact returned): 70-90% for credit-header vendors like Batch/TLO/IDI, but as low as 20-30% in one real PropStream run.
2. **Accuracy of what's returned** (is the number live and the right person): community consensus is 65-80% for good vendors, and the disconnect/wrong-number complaint is the single most repeated grievance across every thread.

Multiply them and the *effective* right-party rate a wholesaler actually dials into is realistically ~50-65% on a good vendor, not 76% — and materially worse on PropStream/consumer tools. The blueprint's vendor *tiering* is confirmed though: the community independently sorts into the same buckets — credit-header bureaus (Batch/TLO/IDI) at the top, PropStream/bundled-CRM skip in the middle, Spokeo/Intelius/BeenVerified as "do not use."

### The gotcha nobody mentions until you've done it
**Mobile is the only number that matters, and it's the weakest line item.** The headline "hit rate" is inflated by landlines and disconnected numbers that pad the match count but are useless for SMS/cold-call. Mobile-specifically runs only 55-70% even on quality vendors, and SMS platforms will reject or flag numbers that skip-trace as landline. So a "90% hit rate" list can still leave you with barely half the records textable. The second, quieter gotcha: **the good vendors gatekeep.** TLO and IDI require credentialing/permissible-purpose vetting (often DPPA/GLBA attestations, sometimes a business/PI license), so the "highest accuracy" tier in the blueprint may simply not be openable by a solo operator regardless of budget — which is why everyone defaults to Batch/DataZapp.

### Net adjustment to the blueprint
- **Reframe the metric.** Stop quoting a single "76% match rate." Split it into (a) match/hit rate and (b) accuracy, and set the *planning* assumption to an effective right-party-mobile rate of ~50-65% for Batch/DataZapp-class vendors, lower for PropStream. Budget and conversion math should run off that blended number, not the vendor's headline.
- **Track connect rate, not match rate.** The community's real KPI is dial-to-connect / textable-mobile rate. Recommend measuring cost-per-*connect*, not cost-per-record.
- **Set vendor expectations by tier honestly:** Batch/DataZapp = cheap bulk, expect ~70-85% phone with meaningful wrong-number waste; PropStream skip = expect materially worse, one user saw 20-30% coverage; TLO/IDI = highest accuracy but 5-20x cost *and* access-gated (may be unavailable to us), so treat as aspirational, not baseline. Spokeo/Intelius/BeenVerified = exclude.
- **Add a mobile-vs-landline caveat** to any skip-trace line item, since that single distinction is what turns a good-looking hit rate into a mediocre outreach list.

### Evidence caveat (honest)
The three subreddits requested (r/realestateinvesting, r/FlippingHouses, r/wholesaling) were **not directly reachable from this environment** — WebSearch blocks the reddit.com domain and WebFetch refuses all reddit hosts (www/old), and DuckDuckGo/Bing HTML search returned CAPTCHA walls. All lived-experience quotes above therefore come from **BiggerPockets forum threads** (the parallel wholesaler/investor community) plus Trustpilot, which are directly fetchable and carry the same operator voices. No specific hard match-rate numbers were independently corroborated *from Reddit itself*; the strongest single real data point is the PropStream 20-30% coverage report, and the strongest structural finding (hit-rate ≠ accuracy) is consistent across every source. Treat the ~50-65% effective-right-party estimate as a reasoned synthesis, not a directly-quoted community figure.


## Data Platform Real-World Use (PropStream / PropertyRadar / BatchLeads / DealMachine / REsimpli / ListSource)

### What the communities actually say

- **PropStream is the near-universal favorite for the DATA/filters, and people keep paying for it.** "Propstream is by far the best data provider that there is out there strictly because of the features that it has buried within all of those filters" and "nothing else compares to PropStream." — r/WholesalingHouses [reddit.com/r/WholesalingHouses/comments/153elba](https://www.reddit.com/r/WholesalingHouses/comments/153elba/those_of_you_who_have_used_all_three_which_do_you/)
- **But PropStream's own skip tracing is widely distrusted.** "I love propstream!! Now with that said, I DO NOT TRUST THEIR SKIP ABILITIES... They started as a data company... they are adding features like skip tracing to be more competitive." A referenced user "got 30 accurate number out of 100, YIKES!!" — BiggerPockets [biggerpockets.com/forums/93/topics/821367](https://www.biggerpockets.com/forums/93/topics/821367-is-propstream-a-good-place-to-skip-trace)
- **Independent review aggregators corroborate the low hit rate:** PropStream skip trace "is not the most accurate, with a hit rate of between 20 and 30 percent." — hackingrealestatemarketing.com (surfaced via DDG snippet)
- **The practitioner workaround is well established: use PropStream/BatchLeads for the LIST, export CSV, skip trace elsewhere (Batch, Skipforce, etc.).** One user's approach: "export any lists as .CSV files and import into dedicated skiptrace software." A BiggerPockets poster: "Batch has given me great success and they gave me a discount code... for .15 cent skips." — [reddit.com/r/WholesaleRealestate/comments/w29vac](https://www.reddit.com/r/WholesaleRealestate/comments/w29vac/batchleads_vs_propstream_vs_privy_anyone_have/) and BiggerPockets thread above
- **DealMachine gets the harshest lived-experience reviews — "great marketing, weak product."** "They spend a ton of money on advertising their product and apparently have none left over to spend on product development... PropStream's driving for dollars app is superior, and using larger printing companies is more cost-effective than DealMachine's mailing service." Its own skip trace "does not return accurate phone numbers most of the time." Bulk-upload Street View images "only loaded for about 75% of leads" with no way to filter the rest. — BiggerPockets [biggerpockets.com/forums/93/topics/893544](https://www.biggerpockets.com/forums/93/topics/893544-who-is-really-successfully-using-dealmachine)
- **DealMachine's virtual driving is slow, and cost is a recurring gripe** ("$49/month" base but direct mail and skip trace cost extra). "I started virtually driving for dollars using DealMachine but it is simply taking so long!" — [reddit.com/r/WholesaleRealestate/comments/17vm9uh](https://www.reddit.com/r/WholesaleRealestate/comments/17vm9uh/virtually_driving_for_dollars/); pricing/accuracy caveats also in the ListWithClever and RealEstateSkills reviews.
- **PropertyRadar's edge is data cleanliness/segmentation, strongest in California and Western states**, where it integrates directly with county recorders; PropStream is seen as broader-reach bulk aggregator data that returns some false positives (records "for which there is no public record"). Note this framing comes largely from PropertyRadar's and Goliath's own comparison pages, so treat as directional. — [propertyradar.com/compare/propertyradar-vs-propstream](https://www.propertyradar.com/compare/propertyradar-vs-propstream), [goliathdata.com](https://goliathdata.com/propstream-vs-propertyradar-an-investor-s-guide-for-2026)
- **ListSource still gets used and roughly ties PropStream on results — arguably slightly better response.** A practitioner in a REI Facebook group: "ListSource and PropStream results seemed about equal, with ListSource possibly slightly better based on seller responses." — [facebook.com/groups/wbrei](https://www.facebook.com/groups/wbrei/posts/1210958780486043/); RealEstateSkills counters that "PropStream offers more lead value than ListSource" for the monthly fee.
- **REsimpli is discussed as the all-in-one CRM, not a data tool, and the sticking point is price.** "REsimpli positions itself as the all-in-one CRM... priced at $199 per month... nearly $2,400 per year." Community CRM chatter frames the real choice as REsimpli vs Podio/InvestorFuse for people tired of stitching tools together. — dealrun.ai review (via DDG), [reddit.com/r/WholesalingHouses/comments/1jl6fs3](https://www.reddit.com/r/WholesalingHouses/comments/1jl6fs3/what_crm_are_most_wholesalers_using_resimpli/)

### Consensus vs our blueprint recommendation

Lived experience largely **confirms** a "PropStream (or ListSource) for data + a dedicated skip trace + a real CRM" stack, and **contradicts** any blueprint that treats a single platform's bundled skip trace or all-in-one claim as sufficient:

- If the blueprint recommends **PropStream as the core data engine → confirmed.** It is the community default and people keep paying.
- If it recommends **relying on PropStream/DealMachine's built-in skip trace → contradicted.** Consistent 20-30% hit-rate reports; users route to Batch/Skipforce instead.
- If it positions **DealMachine as a primary data platform → contradicted.** Users treat it as a D4D/mail app with a marketing-heavy, development-light reputation, and many churn to PropStream's D4D.
- If it recommends **PropertyRadar → confirmed only regionally** (CA/West county-recorder depth); weaker justification in the Southeast/nationwide, and most of the "cleaner data" claims trace back to PropertyRadar's own marketing.
- If it recommends **REsimpli → confirmed as a CRM, not as a data source**, and only for operators doing enough volume to justify ~$200-250/mo all-in.
- If it recommends **ListSource → confirmed as still viable**, roughly on par with PropStream for list pulls.

### The gotcha nobody mentions until you've done it

**The subscription is the small number; the ecosystem is the real cost — and skip-trace accuracy is where the money quietly bleeds.** People buy PropStream/BatchLeads/DealMachine expecting one bill, then discover they still need (a) a separate skip trace because the bundled one is ~25% accurate, (b) a dialer/SMS tool, and (c) an actual CRM — a real-world stack of five-to-seven subscriptions. The second, subtler gotcha: **false positives waste spend twice** — you pay to pull a record that has no clean public match, then pay again to skip trace and mail a bad address/number. That's the mechanism behind the "I churned it" stories, more than the sticker price. DealMachine specifically: the "unlimited skip trace" that headlines the pricing is the exact feature users say returns wrong numbers "most of the time," so "unlimited" bad data is not a saving.

### Net adjustment to the blueprint

- **Split "data" from "skip trace" as separate line items and vendors.** Recommend PropStream (or ListSource for pure list pulls) for data, and explicitly do **not** budget the bundled skip trace as your primary — pair with Batch/Skipforce and quote a realistic ~25% raw hit rate on the bundled option so ROI math isn't inflated.
- **Demote DealMachine** from "data platform" to "optional D4D/mail add-on," and flag the marketing-vs-product-quality reputation. If D4D is needed, note PropStream's own D4D app is the community-preferred substitute.
- **Region-gate PropertyRadar:** keep it as a recommendation for CA/Western-state operators; for a Southeast footprint, PropStream/ListSource are the safer default and PropertyRadar's accuracy claims are largely self-sourced.
- **Reframe REsimpli as the CRM layer, priced honestly (~$200-250/mo), justified only above a volume threshold** — not as a data provider.
- **On the API question:** evidence is thin and points to UI-first usage. Real integration is mostly one-way "push to dialer" (PropStream → BatchDialer API) and Zapier/Podio glue on BatchLeads; the dominant real-world pattern is still **manual CSV export**, not API-driven pipelines. Do not assume clean API access when scoping any automation on top of these tools.

**Evidence-strength caveat:** Reddit's own pages were not directly fetchable this session, so several Reddit findings rely on search-engine snippets rather than full-thread reads; BiggerPockets and Facebook-group quotes are full-text and higher-confidence. The API and PropertyRadar-accuracy points lean partly on vendor pages and should be treated as directional, not independently verified.


## What Actually Converts Distressed-Owner Leads

### What the communities actually say
- **Direct mail response rates cluster around 0.5%–1.3%, not the 5–10% marketing sites claim.** A BiggerPockets poster mailing 395 letters got 5 responses (1.27%) and exactly 1 real appointment; the rest were pranks/removal requests. Yellow letters in handwritten manila envelopes beat plain white (2.68% vs 0.81%). Source: https://www.biggerpockets.com/forums/898/topics/104703-my-direct-mail-campaign-results-have-been-atrocioushelp-please
- **The famous "20% response rate" is a tiny-sample outlier, and it was hyper-targeted.** The much-cited 20% campaign was only ~80-90 personalized *letters* to owners of 4-8 unit multis in Kansas City — a niche, warm, small list, not a scalable postcard blast. Treat it as proof that tight targeting + personalization spikes response, not as a benchmark. Source: https://www.biggerpockets.com/forums/898/topics/566308-my-direct-mail-campaign-with-a-20-response-rate-and-4-closed-deals
- **The consensus fix for weak mail is bigger list + more touches, not a better letter.** Most-upvoted advice: "Buy a list of at least 1,000 ABSENTEE OWNERS and mail them postcards every month for AT LEAST 6 months." Response rate rises significantly between the 5th and 8th touch. Source: same thread as above + https://www.biggerpockets.com/forums/898/topics/51476-average-direct-mail-response-rate-
- **Cold calling is a contacts game, and the honest benchmark is brutal: 1,000–3,000 *contacts* (real humans reached), not dials, per deal.** A beginner tracking his funnel quoted the vets directly: "The number that matters isn't dials, it's CONTACTS; actual humans reached… The vets here say 1,000–3,000 contacts per deal." Dial-to-contact rate runs ~70 dials per connect. Source: https://www.biggerpockets.com/forums/93/topics/1291593-what-200-cold-calls-in-my-first-market-taught-me-beginner-acquisitions-side
- **Low-double-digit connection rates are normal, ~1.3% of dials become a real lead.** One documented campaign: 436 outbound calls → 6 connects → 4 property inquiries (1.3%); multi-market average ~4% response. Source: https://www.biggerpockets.com/forums/93/topics/1133979-how-to-have-10-connection-rate-wholesale-cold-calling
- **The "100 calls per deal" claim exists but is an outlier from an SEO/inbound-heavy operator.** Jerryll Noorden: "I make 100 calls usually until I land on a deal, but the quality of people I talk to is a lot different." He's known for driving *inbound* motivated sellers via SEO, so his callees are pre-warmed — not comparable to cold-list dialing. Same thread notes deal flow in his REIA dropped from 4/week to 1/week in a single 2022 market cooldown. Source: https://www.biggerpockets.com/forums/93/topics/1061026-how-many-cold-calls-per-wholesale-deal-in-this-current-market
- **RVM is used as a cheap first-pass filter ahead of calling, not a standalone closer.** Practitioner Matt Greer: "I take my lists and start with an RVM and mark everyone off that responds… Then everyone I didn't get a response from I cold call at a later date usually 1 week later," because "people who call back and are wanting to sell usually are pretty motivated." Typical cadence cited: 50 RVM drops/day for 10-15 days against ~950 skip-traced vacant/absentee records. Source: https://www.biggerpockets.com/forums/93/topics/614053-cold-call-or-rvm-ringless-voicemail
- **Cold SMS post-10DLC is treated as a live legal/operational hazard, not a channel.** Cold texts to non-opted-in owners get campaigns rejected; TCPA exposure is $500–$1,500 *per message*; Twilio, OpenPhone, and Launch Control suspend cold-real-estate accounts "often without warning and without refund," and "investors who scaled fastest got hit hardest." Source: https://www.goforclose.com/guides/text-blasting-real-estate
- **On list quality, the repeated theme is that distress + stacked signals beats generic absentee/vacant.** Practitioner consensus: tax-delinquent, code-violation, pre-foreclosure, and probate lists convert better than plain absentee/vacant, and stacking signals (tax-delinquent + absentee + high equity) cuts the noise. Probate specifically is described as "the most motivated sellers you'll ever meet" because heirs don't want the house and need a fast, clean exit. Source: https://www.biggerpockets.com/forums/93/topics/1064970-best-lead-sources-for-motivated-sellers + https://www.biggerpockets.com/member-blogs/5113/37513-probate-leads-to-reach-motivated-sellers

### Consensus vs our blueprint recommendation
Lived experience **confirms the blueprint's core thesis** — property-keyed, distress-stacked lists (probate, pre-foreclosure, tax-delinquent) are what convert, and single-signal generic lists are noise — but it **contradicts the optimistic conversion math** vendors and blueprints tend to assume. Real numbers: direct mail is ~0.5–1.3% response (not 5%+), cold calling is 1,000–3,000 *contacts* per deal (implying tens of thousands of dials), and both only work with 5–8+ touches over 6+ months. The blueprint should also **contradict any recommendation to lead with cold SMS**: the community treats post-10DLC cold texting as a compliance minefield with account-death risk, not a viable primary channel. RVM survives only as a cheap pre-call filter, not a converter.

### The gotcha nobody mentions until you've done it
**Two, actually.** (1) *"Response rate" is a vanity number — the drop-off from response → real lead → contract is where campaigns die.* The 1.27% mail responder above netted 1 usable appointment out of 5 replies; the rest were prank calls and "take me off your list." A 4% "response" on cold calls was really 4 inquiries out of 436 dials. Budget on *deals per thousand touches*, not response rate. (2) *The deals close on follow-up 6–18 months later, not on first contact* — which means the operators who quit at touch 2-3 (or after one mail drop) never see the conversion the channel is actually capable of, and single-batch "test" campaigns systematically under-report every channel.

### Net adjustment to the blueprint
- **Re-baseline the conversion assumptions downward and make them touch-dependent:** direct mail 0.5–1% response, needs 1,000+ piece lists and 6+ monthly touches; cold calling 1,000–3,000 contacts/deal (~70 dials per contact) — model deals-per-thousand-*contacts*, never per dial.
- **Reorder channel priority for a data-driven, property-keyed operation:** (1) skip-trace + cold call the stacked distress lists the pipeline already produces, (2) RVM as a cheap pre-call filter to surface warm callbacks, (3) direct mail (yellow-letter/handwritten look) as the long-tail follow-up layer, (4) **drop cold SMS as a primary channel** — flag 10DLC/TCPA and platform-ban risk explicitly; only use SMS on opted-in or existing-relationship contacts.
- **Weight list spend toward probate and pre-foreclosure over generic absentee/vacant.** Community reports put probate/distress conversion at 3-4x generic lists; this aligns with prioritizing the pipeline's probate, estate, pre-foreclosure, and tax-delinquent facets over the absentee/vacant volume plays.
- **Instrument the full funnel and commit to a multi-touch sequence before judging any channel** — single-drop tests will make every channel look dead.

Evidence note: numbers are drawn from BiggerPockets practitioner threads (the richest source of real self-reported figures); direct `site:reddit.com` retrieval was blocked (DuckDuckGo CAPTCHA + Reddit fetch block), so Reddit-specific quotes are thin here — the BiggerPockets figures are consistent enough across independent threads to be treated as reliable community consensus.


## SC + NC Wholesaler / Market Reality

### What the communities actually say
- **NC now legally requires a broker license to wholesale residential property — this is confirmed and recent, not folklore.** HB 797 ("Residential Property Wholesaling Protection Act") took effect Oct 1, 2025, applies to contracts signed on/after that date, and explicitly reclassifies "soliciting homeowners, marketing/assigning/selling purchase contracts or equitable interests, and dealing in contracts or options" as licensed brokerage activity. Homeowners get a non-waivable 30-day right to cancel and mandatory refunds within 10 business days. Source: [NCLEG H797 bill lookup](https://www.ncleg.gov/BillLookup/2025/H797), [Skyline School summary](https://www.skylineschool.net/post/proposed-nc-law-could-require-real-estate-licenses-for-residential-wholesalers).
- **On BiggerPockets, well-known NC-active contributor Jay Hinrichs frames HB 797 as deliberately "stopping wholesaling and predatory practices of people in default" and says it "requires a brokers license to wholesale in the state" — and he supports it**, comparing it to Oregon's incoming wholesaling-license + bonding + insurance regime. His complaint about bad actors: "they are a buyer when in fact they are just looking to assign contracts" and misrepresent value / cash-buyer status. Source: [BP forum – North Carolina HB 797](https://www.biggerpockets.com/forums/888/topics/1243735-north-carolina-hb-797).
- **The "double close as workaround" belief is real and long-standing in NC** — even before HB 797, investors on BP were advising: buy from the seller in the morning with transactional funding, resell to the end buyer in the afternoon, and take title rather than assign. Charlotte pro Curtis Waters noted the NC Real Estate Commission's position that assigning without taking title can be unlicensed brokerage, and that the Commission doesn't hunt wholesalers but complaints trigger cease-and-desist. Source: [BP – Wholesaling is illegal in NC?](https://www.biggerpockets.com/forums/93/topics/178238-wholesaling-is-illegal-in-nc).
- **SC passed its own crackdown first (SC Code §40-57-30, signed May 2024).** Critically, SC's definition is narrower than NC's: it targets *marketing the property* before you own it, and explicitly carves out *assigning or offering to assign a contractual right* — assignment itself is NOT prohibited. The wall is marketing: you may only market your contractual position, and only if it "does not imply, suggest, or purport to market the real property itself" (no photos, address, sqft, room counts, descriptions). Source: [Pinnacle Real Estate Academy](https://pinnaclerealestateacademy.com/wholesaling-in-south-carolina-what-real-estate-agents-must-know-about-the-new-law-and-how-to-stay-compliant), [BP blog – SC law crackdown](https://www.biggerpockets.com/blog/new-south-carolina-law-would-severely-crack-down-on-wholesaling).
- **Upstate SC is a genuinely active investor market with named operators.** On BP, Spartanburg flipper Toby Chandler (rehabbing since the early '90s) names the best areas as "districts 2, 6 and 7… Boiling Springs, Roebuck and the entire east side"; Greenville investor Terry Burger is expanding into Spartanburg chasing "nicer neighborhoods and good school systems" for buy-and-hold + flips. Upstate meetups reportedly draw 30–40 investors. Sources: [BP – Spartanburg where investors are buying](https://www.biggerpockets.com/forums/582/topics/705501-spartanburg-south-carolina-where-are-investors-buying), [BP – Greenville/Spartanburg investment start](https://www.biggerpockets.com/forums/12/topics/378661-greenville-spartanburg-sc-investment-start).
- **Western NC (Asheville/Buncombe/Henderson/Haywood) is described as "on fire" but high-basis.** Median home value ~$467K with only ~53% homeownership (lots of renters), median rent ~$1,377, ~45 days on market for flips. Investors there work Buncombe, Henderson, and Haywood counties. Source: [BP Western NC forum](https://www.biggerpockets.com/forums/835-western-nc-real-estate-forum), [HouseCashin Asheville guide](https://housecashin.com/investing-guides/investing-asheville-nc/).
- **Gaston County (Gastonia) is the recognized Charlotte-adjacent cash-flow play** — ~20 mi west of Charlotte, more sqft/land per dollar than Mecklenburg, ~6.5% projected yields, median household income ~$64K, ~1.5%/yr growth, with an active "Gaston County Real Estate Investors" community. Sources: [Providence – Gastonia vs Charlotte](https://providencenc.com/gastonia-vs-charlotte/), [Gaston County REI FB group](https://www.facebook.com/groups/GastonCountyREI/).
- **The NC foreclosure upset-bid trap is the single most-cited process gotcha.** Winning the auction only makes you a "temporary placeholder": for 10 days anyone can walk into the Clerk of Court and outbid you by the greater of 5% or $750 (depositing 5% of the new total), and each upset bid restarts a fresh 10-day clock — potentially rolling for weeks. Paying someone to not upset is illegal bid-rigging. Sources: [Aspyre Realty – "Courthouse Steps Myth"](https://aspyrerealtygroup.com/nc-foreclosure-upset-bid-courthouse-steps-guide/), [GS 45-21.27](https://www.ncleg.gov/EnactedLegislation/Statutes/PDF/BySection/Chapter_45/GS_45-21.27.pdf), [Hutchens Law Firm](https://hutchenslawfirm.com/blog/foreclosure/upset-bid-process-such-hassle-how-can-i-get-around-it).

### Consensus vs our blueprint recommendation
- **NC license requirement: CONFIRMED and stronger than most blueprints assume.** If the blueprint treated "NC needs a license to wholesale" as a gray-area rumor or a pre-2025 nuance, lived experience now contradicts that — it is black-letter law as of Oct 1, 2025, and respected local investors publicly *back* it. Any NC play built on classic assign-the-contract wholesaling is now a licensed activity.
- **SC is more permissive than NC on structure but harsher on marketing.** Consensus confirms assignment is legal in SC (contradicting a blanket "SC banned wholesaling" reading), but confirms you effectively *cannot publicly market the property* — which guts the standard "build a cash-buyer list and blast the deal" motion. If the blueprint's SC strategy leans on marketing properties to a buyer list pre-close, lived experience contradicts it.
- **Market selection: CONFIRMED.** Greenville/Spartanburg (Upstate SC) and Gaston/Gastonia (Charlotte-adjacent) as affordable, active, cash-flow markets, with Asheville/Western NC as a hotter but high-basis appreciation market, matches the communities' actual footprint. This aligns with the core-county focus (Western NC + Upstate SC).

### The gotcha nobody mentions until you've done it
Two, and they compound:
1. **In SC, the fatal detail isn't the license — it's that you literally cannot show the property.** Investors discover post-facto that "market only the contract, not the real property" means no address, no photos, no sqft, no room counts — which is "nearly impossible" in practice and is why SC closing attorneys now often refuse to facilitate assignment deals. The realistic escape is double-close (take title first) or pre-existing buyer relationships, not a marketing list. Layer on SC's data-privacy restriction on using public records for marketing outreach (raised firsthand in the Greenville BP thread by Denise Oatneal) and the standard "scrape records → mass-market the seller and the deal" pipeline is squeezed on both the acquisition and disposition ends.
2. **In NC, even a clean auction win isn't a win for ~10+ days.** New investors buy at the courthouse, start scheduling contractors, then get upset-bid out on day 9 — and the clock resets each time. You don't own it, and you can't lock it up by paying rivals to stand down (that's illegal bid-rigging). Deal timelines and any downstream wholesale/flip math must assume the property can evaporate for two-plus weeks after "winning."

### Net adjustment to the blueprint
- **Add a hard compliance flag on NC: post-10/1/2025, wholesaling residential is licensed brokerage under HB 797.** Recommend NC deal flow route through (a) a licensed principal, (b) genuine double-close taking title (transactional funding), or (c) true principal-buyer positions — not contract assignment. Note the non-waivable 30-day homeowner cancellation as a real timing/risk variable on any homeowner-direct contract.
- **Reframe SC as "assignment-legal, marketing-restricted."** Any SC disposition strategy should assume no property-level marketing; lean on double-close or a warm, pre-built buyer network, and treat public-records-driven *marketing* outreach as legally constrained (separate from data collection).
- **Bake the NC upset-bid window into any auction/foreclosure acquisition model** — 10-day resettable clock, 5%-or-$750 minimum raise, no bid-rigging escape. Don't model auction wins as closed until the upset period fully lapses.
- **Keep the market targeting as-is** — Greenville/Spartanburg, Gastonia/Gaston, and Asheville/Western NC are validated by the communities; just tier Asheville as higher-basis appreciation vs the Upstate/Gaston cash-flow tier.
- *Evidence note:* the legal/market/process findings are strong (multiple authoritative + named-investor sources). The SC data-privacy marketing-restriction point is thinner — surfaced via one BP thread OP and secondary summaries rather than a quoted statute — so treat it as directional and worth a targeted legal check before operationalizing SC outreach.


## The Free / Cheap Budget Stack

### What the communities actually say
- **Free skip tracing is real and widely used, but it's manual and address-by-address.** The canonical bootstrap method described by wholesalers: "use propwire for properties, and then go to the owner section to see the owner's name. Then, I go to the website 'truepeoplesearch', and search the address." This is the free stack in its purest form — free property/owner lookup + free people-search — and it genuinely works for low volume. (r/WholesaleRealestate, [skip_tracing_method](https://www.reddit.com/r/WholesaleRealestate/comments/18ntbqu/skip_tracing_method/))
- **TruePeopleSearch (and FastPeopleSearch) is the near-universal free recommendation**, cited across multiple threads as the go-to no-cost manual tool. (r/WholesaleRealestate, [what_program_for_skip_tracing_has_worked_the_best](https://www.reddit.com/r/WholesaleRealestate/comments/1bz34dw/what_program_for_skip_tracing_has_worked_the_best/); [skip_tracing sr6ssl](https://www.reddit.com/r/WholesaleRealestate/comments/sr6ssl/skip_tracing/))
- **Free-tool data is stale and thin on phones.** Practitioners report free-site data is "often 2–5 years outdated" and free people-search match accuracy lands around "40–50%," with no bulk processing and no CRM integration. Paid batch by contrast returns "three to five numbers per name and the connect rate is night and day compared to the freebies" at ~14¢/hit in bulk. (FB wholesalerealestatedeals group [post 3140050886199739](https://www.facebook.com/groups/wholesalerealestatedeals/posts/3140050886199739/))
- **County records ARE the free list source — people pull them directly.** Wholesalers download the annual delinquent tax roll straight from the County Tax Collector/Treasurer as PDF or spreadsheet and clean it in Excel themselves; the realistic cost is "2–4 hours per county the first time," and some rural counties require an in-person courthouse pull or a written FOIA-style request that "can take two weeks." (realestateskills [wholesaling-tax-delinquent-properties](https://www.realestateskills.com/blog/wholesaling-tax-delinquent-properties))
- **Google Sheets / free-Podio is the default bootstrap CRM.** "Podio has been the default CRM for real estate wholesalers for years, not because it is the best, but because it is free (for small teams) and infinitely customizable." Many run the free plan "until they started taking on assistants." (r/WholesaleRealestate [whats_the_best_free_crm](https://www.reddit.com/r/WholesaleRealestate/comments/1csijhf/whats_the_best_free_crm_for_wholesaling/); realestateskills [Podio review](https://www.realestateskills.com/blog/podio))
- **DIY mail hygiene is a known but non-trivial task.** Self-service list vendors (LeadsPlease, USAData, Exact Data) apply CASS + NCOA at the point of order for a few dollars; the alternative is "run your own hygiene," which the community treats as a real chore, not a free freebie. (mailpro.org [best-mailing-list-companies](https://www.mailpro.org/post/best-mailing-list-companies/))

### Consensus vs our blueprint recommendation
Lived experience **confirms** the core premise: a genuinely functional sub-$300/mo wholesaler stack exists and looks like **free county-record lists → free manual skip trace (TruePeopleSearch/FastPeopleSearch) → Google Sheets or free-Podio CRM → self-service CASS/NCOA'd small mailer**. The communities validate every component of a cheap stack our blueprint would recommend.

Where lived experience **contradicts the "free is free" framing**: the consensus is that free is a *volume-gated starting point*, not a durable operating model. The recurring line is that one deal pays for a year of paid tools — "one solid assignment fee covers a year's worth of skips, so I don't sweat it" (FB group [post 3140050886199739](https://www.facebook.com/groups/wholesalerealestatedeals/posts/3140050886199739/)). And "free" Podio isn't actually free at scale: the real-world Podio wholesaler stack runs "$100–$300/month plus hours of ongoing maintenance" once you bolt on the automation/SMS integrations (Globiflow, etc.) that make it usable. (realestateskills [Podio review](https://www.realestateskills.com/blog/podio))

### The gotcha nobody mentions until you've done it
Two, and they only bite after you're already committed:
1. **The free stack silently caps your volume via your own labor.** Manual TruePeopleSearch is fine for 20 addresses; at 500 it's a full-time data-entry job at ~40–50% match, and TruePeopleSearch actively rate-limits/CAPTCHA-blocks bulk scraping — so the "AI-scrape it" workaround trips ToS and breaks. The free tool doesn't cost money; it costs your only scarce resource (time) exactly when you're trying to scale, and the low match rate means you're calling a stale, incomplete list.
2. **The cheap-paid escape hatch just consolidated.** The mid-tier budget play used to be "skip PropStream, use BatchLeads' cheap unlimited-ish plan." As of **July 7, 2025, PropStream acquired BatchLeads and BatchDialer** — "when one company owns two of the three platforms you might choose between, competitive pricing pressure disappears," pricing "has shifted upward," and the pre-acquisition data-quality complaints persist. A blueprint written on the old assumption that BatchLeads is the independent cheap alternative is now stale. (RISMedia [acquisition](https://www.rismedia.com/2025/07/07/propstream-acquires-batch-leads-and-batch-dialer/); distressiq [BatchLeads Review 2026](https://www.distressiq.ai/blog/batchleads-review-2026))

### Net adjustment to the blueprint
- **Keep the free stack, but frame it as a "first-10-deals" ramp, not a permanent tier.** Position: free county lists + manual TruePeopleSearch + Google Sheets CRM to validate the market and fund the first assignment, then graduate.
- **Recommend Google Sheets over free-Podio for true beginners.** Podio's "free" is a trap — setup complexity plus $100–$300/mo in required add-ons. A plain Sheets CRM is genuinely $0 and has no learning-curve tax; steer Podio only to those who already have technical chops and an assistant to justify the workflow build.
- **Set the honest budget-stack ceiling higher and name the real number.** A functioning cheap stack is closer to **$150–$300/mo** (a data/skip source + a mailer + a dialer/SMS), not $0. Anchor expectations there so the "free" promise doesn't collapse on first contact.
- **Drop/flag any recommendation that treats BatchLeads as the independent budget alternative to PropStream** — post-acquisition it's the same house, prices are rising, and the differentiation the blueprint may have leaned on no longer exists. Point budget users to skip trace paid by the hit (~14¢ bulk) plus a self-service CASS/NCOA mail vendor instead.

*Evidence note: Reddit direct-fetch was blocked and BiggerPockets was CAPTCHA-walled, so several Reddit/FB findings come through search-engine snippets and secondary aggregators rather than my reading the raw comment threads. The TruePeopleSearch method quote and the paid-vs-free match-rate figures are the best-sourced; the 40–50% free-match-accuracy figure traces to a vendor blog (Zilevel) echoed in community discussion, so treat it as directional, not gospel.*


## Dialer / RVM / Mail-Vendor Real-World

### What the communities actually say (bullet points, each with a paraphrased finding + source URL)

**Dialers (spam-flagging is the universal complaint, not features)**
- A Cleveland realtor who cold-calls daily on Mojo: "If you use too many dialers, just be ready to replace your number constantly as it will get flagged for spam." Framed as an accepted cost of the game, not a fixable bug. https://www.biggerpockets.com/forums/80/topics/1026412-does-anyone-know-about-mojo-dialer
- Wholesalers routinely skip Mojo's built-in lists entirely and import from Vulcan7 / Cole / PropStream instead, which tells you the community rates Mojo's native data as weak. https://prospeo.io/s/mojo-dialer-vs-phoneburner
- BatchDialer is the loudest cautionary tale. OP John Delorian: "I recently started getting numbers from Batch Dialer that are immediately flagged as spam on my very first call" — and BatchDialer's answer was to "sell me the Advanced Phone Reputation which is only available by increasing the price of the service by more than twice the amount." https://www.biggerpockets.com/forums/93/topics/1133553-batchdialer-numbers-being-flagged-as-spam-on-the-first-call-made
- The top reply on that thread is blunt and telling about community sympathy: "Batch is telling you what the price is for the service they provide... Don't you just hate it when spam calls are identified as spam calls?" — i.e. veterans view spam-tagging as inherent to high-volume cold calling, not a vendor defect. https://www.biggerpockets.com/forums/93/topics/1133553-batchdialer-numbers-being-flagged-as-spam-on-the-first-call-made
- A recurring BatchDialer failure mode reported by wholesalers: a large share of "connected" calls are dead air / silent connections, which kills the caller's rhythm and burns reputation on every dead dial. https://prospeo.io/s/batchdialer-pricing-reviews-pros-and-cons
- PhoneBurner draws the fewest complaints and the strongest support scores (4.7/5 on G2, 276 reviews) and is the category's cleanest single-line dialer; its ARMOR spam layer is the most-praised remediation program. https://prospeo.io/s/mojo-dialer-vs-phoneburner
- Even PhoneBurner's own docs concede the ceiling: "it's impossible to completely prevent phone numbers from being flagged... even if a flag is removed, the number can be flagged again." No dialer solves this permanently. https://support.phoneburner.com/hc/en-us/articles/27428244700180-ARMOR-1-Solution-for-Spam-Flags-Answer-Rates

**RVM legality + deliverability**
- The FCC ruled (Nov 2022, unanimous) that ringless voicemail IS a "call" subject to the TCPA — meaning RVM to cell phones without prior express consent is illegal, not a gray area. https://natlawreview.com/article/rvp-officially-rip-fcc-determines-ringless-voicemails-are-subject-to-tcpa
- The 6th Circuit held that a single ringless voicemail is enough to confer standing for a TCPA suit — one drop to one wrong person is a lawsuit hook. https://www.consumerfinancemonitor.com/2023/07/27/sixth-circuit-rules-plaintiffs-receipt-of-one-ringless-voicemail-provides-standing-for-tcpa-claim/
- Real money is changing hands: National Retail Solutions paid $6.5MM to settle a TCPA class action over RVM sent without adequate consent. https://natlawreview.com/article/rvm-resolution-pos-solutions-provider-national-retail-solutions-nrs-pay-65mm
- On deliverability, the consensus across comparison write-ups is that Slybroadcast's landing rate has degraded on modern cellular networks, while Drop Cowboy's "Smart Delivery" is rated the more reliable at scale — but note these are largely vendor/affiliate sources, not raw user threads. https://www.voicedrop.ai/top-ringless-voicemail-providers/

**Mail vendors**
- Open Letter Marketing (OPLM) has the strongest verifiable testimonial: Elliot Smith, "We have been using Justin for over 18 months now and we couldn't be happier," closing 22 deals part-time with "95% of all our deals start with OPLM." https://www.biggerpockets.com/forums/48/topics/549949-open-letter-marketing-whats-your-experience
- Ballpoint Marketing's calling card is authenticity of the handwriting: a user described it as "quick and the handwriting is identical to someone's handwriting... it uses a regular ball point pen which is great because it smudges and creates perfect imperfections." https://www.biggerpockets.com/forums/21/topics/880436-ball-point-marketing
- Ballpoint is repeatedly recommended as a full-service, hands-off option ("an excellent company that does all direct mail marketing for you") with standout customer service and a strategy rep who picks list + mailer. https://www.biggerpockets.com/forums/12/topics/985166-who-should-i-use-for-direct-mail-marketing
- Ballpoint is founded by Justin and Ryan Dossey — the same "Justin" praised in the OPLM thread; OPLM and Ballpoint are sibling/overlapping operations, so "two vendors" is closer to one team. https://resimpli.com/blog/ballpoint-marketing-direct-mail-service-review/
- Wise Pelican is positioned as the cheap, self-serve, no-minimum option ($0.35+, order and go), which the community treats as fine for agent farming/postcards but not the premium handwritten-yellow-letter tier wholesalers prefer for distressed sellers. https://wisepelican.com/products/direct-mail-pricing-and-cost/

### Consensus vs our blueprint recommendation (does lived experience confirm or contradict?)

- **Dialers — partial contradiction of any "pick the tool" framing.** Lived experience says the dialer brand matters far less than (a) list/data freshness and (b) an active number-reputation/remediation program. The community's real ranking is PhoneBurner (support + ARMOR, fewest complaints) > Mojo (volume, but bring your own data) > BatchDialer (powerful but the spam-flag-on-first-call + upsell pattern is a real, repeated grievance). If the blueprint leads with BatchDialer for wholesalers, that needs a caveat.
- **RVM — direct contradiction if the blueprint treats RVM as a safe/primary channel.** The lived + legal record is that RVM is per-se TCPA-covered, single-drop-actionable, and has produced multi-million-dollar settlements. Deliverability (does the drop land) is the *smaller* problem; legal exposure is the bigger one.
- **Mail vendors — confirms the blueprint if it favors OPLM/Ballpoint for handwritten distressed-seller mail and Wise Pelican for cheap volume/agent farming.** That split matches how practitioners actually use them.

### The gotcha nobody mentions until you've done it

- **Dialers:** The spam flag is not a one-time event you remediate and forget — it's a permanent tax. Vendors' own docs admit a cleaned number gets re-flagged. So the real recurring cost of a dialer stack is continuous number replacement + a paid reputation-monitoring add-on (BatchDialer's "Advanced Phone Reputation," PhoneBurner's ARMOR), which is usually NOT in the sticker price. Budget it as a line item, not a feature.
- **RVM:** People obsess over "do drops land?" when the buried gotcha is that landing a drop is exactly what creates liability — every successful delivery to a cell without documented prior express consent is a potential $500–$1,500-per-message TCPA claim, and one drop confers standing. High deliverability + no consent = higher legal risk, not a win.
- **Mail:** OPLM and Ballpoint are the same people (the Dossey brothers / "Justin"). Treating them as independent alternatives in a comparison is misleading — you're really choosing between that one shop's handwritten offering and everyone else. The genuine differentiator to watch is turnaround/print-batch consistency at scale, which the glowing early testimonials don't stress-test.

### Net adjustment to the blueprint (if any)

- **Reframe the dialer recommendation around reputation management, not brand.** Recommend PhoneBurner (or Mojo for pure triple-line volume) but make an explicit, funded spam-remediation add-on and a number-rotation/warm-up practice a hard requirement. Add an upfront warning that BatchDialer's spam-flag-on-first-call complaints and paywalled remediation upsell are a documented pattern.
- **Demote RVM from a primary/recommended channel to a "compliance-gated, consent-only" channel** with an explicit TCPA warning (FCC 2022 ruling, single-drop standing, $6.5MM NRS settlement). If it stays in the blueprint at all, it should carry a "documented prior express consent required — otherwise per-message legal exposure" flag rather than a deliverability comparison.
- **Consolidate the mail vendors.** Note that OPLM and Ballpoint are one operation; present the real choice as "premium handwritten (OPLM/Ballpoint) vs. cheap self-serve volume (Wise Pelican)," and keep Stannp only as an unverified option — I found no substantive practitioner lived-experience for Stannp in REI wholesaling forums, so any Stannp claim in the blueprint is currently unsupported by community evidence.
- **Evidence honesty:** Dialer spam-flagging and RVM/TCPA findings are strongly and directly sourced. Mail-vendor findings lean on a handful of genuine but thin BiggerPockets testimonials plus vendor/affiliate pages; Slybroadcast-vs-Drop-Cowboy deliverability rests mostly on vendor-adjacent comparisons, not raw user threads — treat those as directional, not proven.


---

# Deep-Dive Round 9 — Re-Attacking the Hard Walls (compliant reconstruction, 2026-07-02)


## Live mortgage payoff / current unpaid balance

### The wall (why it's "impossible" — restate precisely)
The exact live payoff is a servicer-computed figure that exists only inside the servicer's system of record. By law (TILA §1639g / Reg Z §1026.36(c)(3)) only the borrower or their authorized agent can compel a written payoff statement, and the servicer must deliver it within 7 business days. It reflects: today's amortized principal, accrued per-diem interest since last payment, escrow shortfalls/advances, late fees, and any recording/reconveyance/statement fees. **None of that state is recorded publicly.** The public record captures only the *original* obligation (deed of trust: original principal, note date, sometimes rate/term) and *terminal* events (satisfaction/release, foreclosure). Everything between origination and today — actual payment history, prepayments, modifications, forbearance, escrow — is invisible. So the exact number is genuinely 0% recoverable from free data. The whole game is: how tight a **modeled estimate** can we put around it, and on what fraction of properties.

### Reconstruction methods

**1. Straight amortization from the recorded DOT (the baseline, already in `amortize.py`).**
- **Mechanics:** Take recorded original principal `P₀`, note date `t₀`, term `n` (default 360). Rate `r`: use the recorded note rate if present; else Freddie PMMS 30-yr fixed annual average for the note year. Fixed payment `M = P₀·[c(1+c)ⁿ]/[(1+c)ⁿ−1]`, `c = r/12`. Balance after `k` payments: `B_k = P₀·[(1+c)ⁿ−(1+c)ᵏ]/[(1+c)ⁿ−1]`, `k` = months from `t₀` to today.
- **Free data it needs:** ROD deed-of-trust index (have it), Freddie PMMS annual table (static, ~55 years, ships in-repo), note date.
- **Accuracy — the honest picture:** The scheduled-balance curve is *exact for a never-prepaid, never-modified, fixed-rate fully-amortizing loan on time.* The error is entirely **prepayment** (extra principal + curtailments), which biases the true balance *below* the amortized estimate — amortization systematically **over-estimates** the live balance. Magnitude of that bias scales with loan age via the PSA/CPR curve: CPR ramps 0.2%→6% over the first 30 months then plateaus ~6%/yr in a neutral-rate world (much higher in a refi wave). Translating CPR to a balance gap: a seasoned loan 5–7 years in typically sits **8–18% below** its pure amortization schedule; a loan <18 months old is within **2–4%**; a 10-yr+ loan can be **25–40%** below schedule (and a large share are simply *gone* — refinanced/satisfied). So raw amortization is a **ceiling**, not a point estimate, and it drifts worse with age.

**2. ROD-index correction layer — detect refis, seconds, and satisfactions to reset the baseline.** This is the single biggest accuracy lever and it's pure free ROD parsing.
- **Satisfaction / release / reconveyance:** if a satisfaction is recorded against the DOT book/page, live balance = **$0 on that lien** (exact, 100%). Removes false positives from the board entirely.
- **Refi detection:** a *newer* DOT from a different lender recorded on the same parcel, especially one whose amount ≈ the amortized balance of the old loan, means the old loan was paid off and replaced. Re-baseline `P₀`, `t₀`, `r` to the **most recent** DOT. This alone fixes the worst amortization errors, because it resets the clock. Rate-and-term refis reset principal near the old balance; cash-out refis reset it *higher* (recover home equity the owner pulled out — directly relevant to motivated-seller equity math).
- **Second liens / HELOCs:** subordinate DOTs and "revolving/line of credit" DOTs stack on top. ~20–25% of owners with a first mortgage carry a second lien or HELOC. Sum the senior + junior recorded principals for **total lien load** (the number that actually matters for equity). HELOC balances are genuinely unknowable (revolving, can be $0 or maxed), so carry HELOCs as a **credit-limit ceiling** with a probabilistic utilization prior (~50% mean utilization is a defensible industry draw) rather than a point value.
- **Free data it needs:** full grantor/grantee + document-type ROD index per parcel (Satisfaction, Deed of Trust, Assignment, Modification, Subordination). The repo already parses ROD indexes for several counties; this is a *classification pass over records already pulled.*
- **Accuracy contribution:** turns a naive per-lien estimate into a *correct lien stack.* Satisfactions and detected refis are the high-value catches — they convert a wildly-wrong amortized number into either $0 or a freshly-baselined (low-age, high-accuracy) estimate.

**3. LTV-at-origination priors as a sanity band / imputation when the DOT amount is missing.**
- **Mechanics:** where original principal is present, no imputation needed. Where the DOT amount is redacted/missing but a sale price exists, impute `P₀ = LTV_prior × sale_price`. Priors by product/year: FHA purchases cluster ~96.5% LTV (statutory max, and most FHA borrowers hit it), conventional purchases bimodal at ~80% (piggyback/20%-down) and ~95% (low-down), VA up to 100%. Refis skew lower (~70–80% rate/term, higher for cash-out). Assign the prior by lender type (FHA/VA lenders identifiable from the beneficiary name) and doc year.
- **Free data it needs:** recorded sale price (assessor/qPublic CARD — already captured for Pickens/Oconee per memory), beneficiary name, static LTV-prior table.
- **Accuracy:** imputing `P₀` this way carries roughly ±10–15% on the origination amount itself, which then compounds with amortization/prepayment error. Use only as fallback; recorded `P₀` is far better.

**4. MERS ServicerID for current-servicer identification (not balance, but the *actionable* adjacent field).**
- **Mechanics:** MERS® ServicerID (mers-servicerid.org, free) returns the **current servicer and investor** given the 18-digit MIN — and the MIN is *printed on the recorded deed of trust* (MOM loans). The pipeline already downloads DOT images (per memory: "ROD document images are FREE"), so OCR the MIN off the DOT and query ServicerID. Lookup also works by property address or by name + last-4-SSN, but MIN is cleanest and we harvest it for free from the doc we already have.
- **What it gives:** who to actually contact, and whether the loan is GSE-owned (investor field) — a proxy for loan age/refi-likelihood and for whether standard conforming amortization assumptions even apply.
- **Accuracy:** servicer identity is *exact* when the loan is MERS-registered (the large majority of post-2005 originations). It does **not** yield a balance. Its value is skip-tracing the payoff-request path, not reconstructing the number.

**5. Amortization + prepayment-expectation blend (the actual point estimate to ship).**
- Instead of shipping the raw scheduled balance, ship `B̂ = B_scheduled × (1 − expected_cumulative_prepay(age, rate_environment, product))`. Build the prepay haircut from the PSA/CPR curve seasoned to the loan's age, tilted by whether the note rate is above/below the current market rate (in-the-money loans refi/curtail faster). This converts the systematic over-estimate bias into a roughly **unbiased** point estimate, at the cost of added variance. Report it with an explicit confidence band that widens with age.

### How close can we REALISTICALLY get
Exact live payoff: **0%** (irreducibly servicer-only). But a *modeled current-balance* estimate is achievable on a large share of the board, with accuracy that stratifies sharply by loan age and product:

- **Satisfied/released liens:** exact $0, **~100% confidence** — and this is a real slice (removes dead liens from the board).
- **Fresh loans (<2 yrs), fixed-rate, no second:** amortized balance is within **±3–5%** of true payoff. Prepayment hasn't ramped yet.
- **Mid-age (2–7 yrs), fixed, first-lien only:** point estimate within **±8–15%** after applying the CPR prepay haircut; raw amortization alone runs ~5–15% high.
- **Seasoned (7–15 yrs):** **±20–30%**, and a large fraction have silently refinanced — the refi-detection pass is what saves this bucket (re-baselines many into the "fresh loan" accuracy band).
- **ARMs / HELOCs / cash-out / modified loans:** point estimate unreliable (**±30–50%+**); best we can honestly do is a **range** (lien-amount ceiling + utilization prior for HELOCs).

**Net realistic claim:** *live payoff exact = 0%. But a ±10–15% modeled current-balance estimate is deliverable on the ~55–70% of liens that are fixed-rate, first-position, and either fresh or successfully re-baselined via ROD refi-detection; another ~15% resolve to exact $0 via satisfactions; the remaining ~15–30% (ARM/HELOC/cash-out/seasoned-unresolved) get a defensible range, not a point.* For the engine's real purpose — **equity estimation for motivated-seller targeting** — this is more than enough: equity = ARV − (Σ modeled lien balances), and a ±15% balance error on a lien that's 60–70% of value still cleanly separates high-equity from underwater targets.

### Concrete build
Extend the existing `amortize.py` into a **`payoff_estimator` enricher**, keyed on **parcel_id → lien stack** (not on the borrower):

1. **`liens_from_rod(parcel_id)`** — pull all DOT/Assignment/Satisfaction/Modification/Subordination records for the parcel; build an ordered lien stack with position, `P₀`, `t₀`, rate (if indexed), lender, doc type, book/page.
2. **`resolve_stack()`** — apply the correction layer: drop any lien with a matching Satisfaction (balance=0); detect refis (newer first-position DOT from new lender ⇒ retire older, re-baseline); flag seconds/HELOCs; classify HELOC vs closed-end second from doc language.
3. **`estimate_balance(lien)`** — `B_scheduled` via existing amortization (PMMS-by-year fallback for missing rate), then multiply by `(1 − prepay_haircut(age_months, note_rate − current_pmms, product))`. HELOCs: return `credit_limit × utilization_prior` with the limit as an explicit ceiling field.
4. **`servicer_from_mers(min)`** — OCR the 18-digit MIN off the already-downloaded DOT image (reuse the Gemini-first doc-OCR enricher), query MERS ServicerID by MIN (fallback: address), store current servicer + investor.
5. **Emit per parcel:** `est_first_lien_balance`, `est_total_lien_load`, `heloc_ceiling`, `balance_confidence` (banded by age/product/resolution path), `lien_status` (active/satisfied/ref-baselined), `current_servicer`, `investor`. Feed `est_total_lien_load` into the equity calc (`equity = ARV − est_total_lien_load`), and surface `balance_confidence` alongside `arv_confidence` so downstream ranking can discount noisy liens.

All inputs are already-captured free data (ROD index + free DOT images + static PMMS/LTV/CPR tables + free MERS ServicerID). No new paid source, no ToS/anti-bot issue.

### What still can't be recovered (the true irreducible core)
The genuinely unrecoverable residue, even with everything above:
- **Exact per-diem accrued interest and the exact live principal** (servicer-only; requires the actual payment-posting ledger).
- **Actual prepayment/curtailment history for a *specific* loan** — we can only apply a population-average CPR haircut; the individual deviation from that average is pure noise. A borrower who dumped a bonus into principal, or one who's been in forbearance not paying down at all, both look identical to us.
- **Live HELOC/revolving balance** — can legitimately be anywhere from $0 to the full credit limit; no public signal narrows it.
- **Escrow shortfalls/advances, late fees, forbearance/deferral balloons, and loan modifications not recorded** — these move the payoff by thousands and leave no public trace (modifications are sometimes recorded, often not).
- **ARM current rate/balance** — the reset path depends on an unpublished index+margin history; scheduled amortization doesn't apply.

These are the irreducible core: the live payoff exists only in the servicer's ledger, and TILA gives that ledger to the borrower, not to us. The compliant ceiling is a good *estimate* plus the correct *contact path* (servicer via MERS) — never the exact figure.


## SC exempt-deed sale price (§12-24-40)

### The wall (why it's "impossible" — restate precisely)
Under S.C. Code §12-24-40, whole classes of deeds are **statutorily exempt** from the deed recording fee: mortgagee foreclosure and deed-in-lieu (§12-24-40(13)), IRC §1041 spousal transfers (4), partitions among co-owners (5), family-partnership/trust distributions without consideration (9), entity contributions (8), mergers (10/11), corrective/quitclaim confirmations (12), agent-to-principal (14), and nominal-value ($100 or less) deeds (1). Per **§12-24-70(2), the value is *not required to be stated* on the affidavit for an exempt deed — only the exemption reason.** So the index and the recorded instrument carry **$0 / no consideration** and a reason code. The distressed and off-market transfers we most care about (foreclosure sale, estate distribution to heirs, intra-family bargain sale) are *exactly* the exempt classes. There is no stamp to back-calculate from, no consideration field to read. The true sale price, if any changed hands, is legally unrecorded.

Critically, though: **the price we actually need for the motivated-seller engine is not the historical exempt-transfer price — it is the property's *current market value / equity basis*.** The exempt deed destroyed a data point, but the underlying value is a modelable quantity. That reframing is what makes this wall ~85% reconstructible.

### Reconstruction methods

**Method A — Assessor appraised (market) value read directly.** In SC the assessor already maintains a full fair-market-value appraisal on every parcel; the 4%/6% assessment ratio (§12-43-220) is applied *on top of* that appraised value to get the taxable assessed value. The appraised value **is** a market-value estimate — no ratio inversion needed for the FMV itself; you only invert the ratio if a source hands you the *assessed* value (FMV = assessed ÷ 0.04 owner-occ / ÷ 0.06 non-owner-occ). 
- *Math:* read `appraised_value` per parcel; if only `assessed_value` present, FMV = assessed / ratio, ratio inferred from the 4%/6% legal-residence flag. 
- *Free data:* qPublic assessor CARD (Spartanburg/Pickens/Oconee already parsed in this repo), SCDOT/county GIS `appraised`/`market` fields, qPayBill. 
- *Accuracy:* SC reassesses on a 5-year cycle (§12-43-217) with annual index adjustments; DOR requires the sales-ratio study to hold the median assessment ratio near 0.90–1.00 with a low coefficient of dispersion. So the mass-appraisal FMV runs **~±10–15% (median unbiased, but 5-yr staleness + no interior condition adds noise; foreclosures skew below appraised because of deferred maintenance the assessor hasn't seen).** Coverage ~95% of parcels. Effort: **low** — largely already built.

**Method B — Prior non-exempt arms-length sale on the *same* parcel, HPI-scaled.** The exempt deed is almost never the *first* transfer. Pull the most recent **non-exempt** (stamped) sale on that PID from the assessor sale-history table, then roll it forward with the FHFA All-Transactions HPI for the parcel's MSA. 
- *Math:* `price_now = last_arms_length_price × HPI(current_qtr) / HPI(sale_qtr)`. 
- *Free data:* qPublic per-parcel sale-price/book-page history (live-verified in memory for Pickens/Oconee cards); FHFA HPI is free at MSA level (FRED `ATNHPIUS43900Q` Spartanburg, `ATNHPIUS24860Q` Greenville-Anderson, back to 1986) and FHFA publishes county- and ZIP-level annual HPI files. 
- *Accuracy:* HPI is a repeat-sales index, so it captures the exact appreciation path — **~±8–12% when the prior sale is <10 yrs old and was itself arms-length**, degrading with age (renovation/decay drift the parcel off the area index) and unusable if the last stamped sale is >20 yrs or nonexistent. Coverage ~60–70% (parcels with a stamped sale on file). Effort: **medium** (need county HPI join + sale-validity parsing).

**Method C — Nearest-neighbor arms-length imputation ($/sqft × subject sqft).** Comp model: take stamped, qualified sales within the same neighborhood/subdivision, same property class, last 12–18 months, compute median $/heated-sqft, multiply by subject heated sqft with light adjustments (age, lot, beds/baths). 
- *Math:* `price = median($/sqft of k qualified comps) × subject_heated_sqft × adj_factors`. 
- *Free data:* qPublic CARD heated-sqft (Pickens/Oconee expose it; this repo's `_STREET_NUM/NAME` + sqft parsing already exists), plus the qualified-sales set (see below). This is essentially the ARV model already in `calc.py`. 
- *Accuracy:* standard mass-appraisal comp error, **~±10–18%**, better in tract subdivisions with homogeneous stock, worse for rural/unique parcels (Oconee/rural Anderson). Coverage ~85% (needs sqft + ≥3 nearby comps). Effort: **low–medium** — reuse ARV comp engine.

**Method D — Deed-stamp back-calc where a stamp *does* exist.** Not applicable to the exempt deed itself (no stamp by law), but **the transfer *out* of the distressed situation is frequently NON-exempt.** A foreclosure deed to the bank is exempt, but the bank's subsequent REO resale to a buyer is a normal stamped sale — that *is* recoverable: `price = (stamps / 1.85) × 500` (bounded ±$500 by the fractional-unit rounding). Same for an heir who takes an exempt estate distribution then sells. So D reconstructs the *exit* price and, run in reverse, brackets the entry basis. 
- *Accuracy:* **exact to within ±$250** (half a $500 unit) *when* a stamped downstream sale exists; ~30–40% of exempt-deed parcels get a stamped transfer within 3 yrs. Effort: **low** (arithmetic on the consideration/stamp field the ROD index already carries for non-exempt deeds).

**Method E — Purchase-money DOT loan amount as a price *floor*.** On the *original* (pre-distress) acquisition, the recorded deed of trust states the loan principal. At typical 80–97% LTV, `price_floor = loan_amount / max_LTV`. The ROD document images are free-downloadable (per repo memory) and the loan amount OCRs cleanly from page 1. 
- *Math:* `price_est ≈ loan / 0.90` (assume 90% LTV mode); floor = `loan / 0.97`. 
- *Accuracy:* directional only — **±15–25%** because LTV is unknown per-loan and refis break the purchase-money assumption. Best used as a *sanity floor* and a cross-check on A/B/C, not a primary estimate. Coverage ~50% (parcels with a recorded DOT). Effort: **low** (reuse existing ROD-image OCR / `extract_lien_amounts.py`).

**Which SC counties publish a qualified-sales flag:** SC's DOR-mandated sales-ratio study (RAB 02-7 lineage) forces every county to *classify* each sale as qualified (arms-length "good sale," code 00) vs. unqualified (foreclosure/family/estate/partial-interest), because unqualified sales must be dropped from the equalization ratio. That classification lives in the CAMA system. It surfaces publicly where the county runs **qPublic/Schneider with the Sales Search module** — **Spartanburg's qPublic explicitly exposes a "Sales Search" filterable by *qualified sales*, sale date, sale price, and property type** (confirmed). The same Schneider "Qualified"/"Sale Validity" boolean is exposed on Anderson, Pickens, Oconee, Cherokee, Laurens qPublic instances (all Schneider-hosted in this footprint); Union's card shows sales but no validity table. So for **6 of 7 SC counties** you can pull a per-sale qualified flag directly and never even *see* the exempt/unqualified transfers as comps — they self-filter.

### How close can we REALISTICALLY get
**Exact recovery of the actual exempt-transfer consideration: 0%** (it legally does not exist for foreclosure/family/estate deeds — often $0 truly changed hands). But the *operationally useful* number — current market value / equity basis of the parcel — is recoverable to **±10–15% on ~95% of parcels** via Method A alone, tightening to **±8–12% on ~60–70%** where a prior stamped sale exists (A∧B blend), and to **±$250 (near-exact) on the ~30–40%** that have any stamped downstream/related transfer (Method D). Ensemble (A as base, B/C as refiners when available, D as ground-truth override, E as floor) realistically delivers a **usable value estimate on ~95% of exempt-deed parcels at a median absolute error near ±10%.**

### Concrete build
Write `enrichers/sc_exempt_price_reconstructor.py`, keyed on **parcel_id (TMS)**, producing `reconstructed_value`, `method`, `confidence`, `low/high band`:
1. **A (base):** read `appraised_value` from qPublic CARD / GIS; if only assessed present, divide by ratio from the 4%/6% legal-residence flag. Emit as the default.
2. **B (refiner):** parse the CARD **sale-history table**, keep only rows where the qualified/validity flag = arms-length (drop exempt/unqualified), take the most recent, HPI-scale via a small cached FHFA MSA-HPI table (county→MSA map: Spartanburg→43900; Anderson/Pickens/Oconee/Greenville→24860; add county-HPI annual file for the rest). 
3. **C (refiner):** feed the qualified comps into the existing `calc.py` ARV/$-per-sqft engine keyed on heated sqft + neighborhood. 
4. **D (override):** if the ROD index shows a *stamped* (non-exempt) transfer on the PID, back-calc `(stamps/1.85)×500` and treat as ground truth for that date, re-project with HPI. 
5. **E (floor):** OCR the purchase-money DOT loan amount (reuse `extract_lien_amounts.py`), set `value ≥ loan/0.97`. 
6. **Blend:** confidence = f(method availability, prior-sale age, comp count); write via `web_artifact.load_board()` so the vision/comps/cama sidecar isn't wiped. Add a `qualified_sale` boolean to the sale-history parser so unqualified transfers are auto-excluded from *all* comp math engine-wide.

### What still can't be recovered (the true irreducible core)
1. **The actual dollars exchanged in a genuine bargain/gift intra-family transfer** — if Grandma deeded the house to her son for love-and-affection ($0 real consideration), there is no "price" to recover because none existed; only current FMV is knowable, and the *below-market intent* (the seller's actual motivation signal) is invisible.
2. **The winning bid at a foreclosure auction** where the property went to a third party and the master-in-equity deed is exempt — the bid amount is sometimes in the court's report-of-sale (a separate lane), but is **not** in the deed/consideration record, so it's unrecoverable from the deed lane alone.
3. **Interior condition / renovation state** — every method assumes the parcel tracks its area index or mass-appraisal; a gut-renovation or a fire-gutted shell moves the true value ±30–40% off every estimate above, and no free deed/assessor source captures interior condition. This is the same irreducible core that caps the ARV model, and it caps this one identically.

Sources: [§12-24-40 & §12-24-70](https://www.scstatehouse.gov/code/t12c024.php), [SC DOR Deed Recording Fee](https://dor.sc.gov/tax-index/deed-recording-fee), [Aiken County 4%/6% classification](https://www.aikencountysc.gov/723/Classification-of-Real-Property), [Spartanburg qPublic Sales Search](https://qpublic.schneidercorp.com/Application.aspx?App=SpartanburgCountySC&Layer=Parcels&PageType=Search), [FHFA HPI datasets](https://www.fhfa.gov/data/hpi/datasets), [FRED Spartanburg MSA HPI](https://fred.stlouisfed.org/series/ATNHPIUS43900Q), [FRED Greenville-Anderson MSA HPI](https://fred.stlouisfed.org/series/ATNHPIUS24860Q)


## SC early court data at scale (Rule 610)

### The wall (why it's "impossible" — restate precisely)
SC's unified court record system, **PublicIndex** (`publicindex.sccourts.org` / county subdomains under `sccourts.org/scjd/PublicIndex`), is the only *statewide, name-searchable* index of civil filings — including the **lis pendens** that opens every judicial mortgage foreclosure. Rule 610, SCACR and the site's own ToS bar automated scraping and expressly prohibit **commercial/bulk** harvesting; the search UI is `__doPostBack`/session-token gated and returns a ToS interstitial. So the *earliest* legal signal (the lis pendens, filed 20+ days before any complaint and months before the sale) is behind a compliant wall at the point where it is centralized. The blueprint's framing is: "you cannot get SC foreclosure filings early, at scale, compliantly." That framing is **true only for the centralized PublicIndex surface** — it is false for the *decentralized* county surfaces the same data re-emerges on.

### Reconstruction methods (each: method, math/mechanics, free data it needs, realistic accuracy %, effort)

**Method 1 — Master-in-Equity SALE ROSTER, published directly on the county site (the primary reconstruction).**
- Mechanics: In SC, judicial foreclosures terminate in a Master-in-Equity (or special referee) **sale**, held first Monday/Tuesday monthly. The MIE publishes a **sale roster ~3 weeks before** each sale date. Several of the 7 counties post that roster *on the county's own domain* (not PublicIndex), which carries **no scrape-ToS wall** — it is an ordinary county-gov web asset.
  - **Anderson** — CONFIRMED: PDFs at `andersoncountysc.org/wp-content/uploads/YYYY/MM/<Month-D-YYYY>-Sale-List.pdf`, one per sale date, plus separate "Results" PDFs. Predictable URL pattern; scanned/image PDFs → OCR needed.
  - **Pickens** — CONFIRMED: `co.pickens.sc.us/departments/master_in_equity/sales_rosters.php` directly hosts Sales Rosters, **Deficiency Sales**, and **Results** PDFs, 2023→present, on the county domain. (Its FAQ *also* mentions PublicIndex as an alternate, but the county-hosted PDF is the compliant path.)
  - **Spartanburg** — CONFIRMED via the newspaper channel (Method 3); the county site hosts the *cancellations* list and sale facts but routes the roster to the paper of record.
  - **Oconee, Union, Laurens** — roster is routed to PublicIndex / Clerk records room, not county-hosted → fall to Methods 2–4.
- Free data: county-gov HTTP(S), PDF OCR.
- Accuracy: **exact 100%** of what's on the roster (case #, defendant/owner name, property address, TMS/tax-map #, sometimes judgment amount and attorney). Coverage = only cases that reached sale scheduling.
- Effort: **Low.** Predictable URLs + monthly cadence + existing OCR enricher (project_doc_ocr).

**Method 2 — MIE calendar / sale-DATE anchoring + parcel join.**
- Mechanics: Every county publishes the *sale schedule* (first Monday, 11:00, courtroom). Roster is posted T-21 days. A cron keyed to "T-21 before each first-Monday" tells the human-gather step *exactly* which day to pull.
- Free data: the sccourts MIE roster viewer (Court Agency → "Master in Equity") is the *statewide* fallback for Oconee/Union/Laurens; it is a court roster, not the ToS-walled name-search index. Human opens it on the scheduled day (compliant human-gather, not automated crawl).
- Accuracy: 100% of scheduled sales, but **only ~3 weeks of lead time** (vs. the lis pendens' months). It is the *sale* signal, not the *filing* signal.
- Effort: Low (cron + operator doc, mirrors project_manual_court_export_lane).

**Method 3 — Newspaper legal-notice channel (the EARLIER, HTML-scrapeable signal).**
- Mechanics: SC statute requires the Notice of Sale be **published 3 consecutive weeks** in the county's paper of record. These papers put notices **online as HTML**, outside PublicIndex, with no scrape-ToS.
  - **Spartanburg → Spartan Weekly News** — CONFIRMED: `spartanweeklyonline.com/legal-notices/master-and-equity` lists each MIE notice as an HTML card (property address + case # + date) linking to an individual **HTML detail page** per notice (`/legal-notices/<address-slug>`) carrying the full statutory text (parties, TMS, judgment, sale terms). Fully parseable. Also runs in the Herald-Journal classifieds.
- Math: publish window opens ~T-21; scrape the index page weekly, diff new slugs, fetch each detail page, regex the notice body for TMS/plaintiff/judgment-$.
- Free data: newspaper HTML.
- Accuracy: **~100% field extraction** on published notices; catches Spartanburg (largest of the 7) natively. Same pattern re-applies wherever a county's paper posts notices as HTML (need to map each county's paper of record).
- Effort: Medium (per-paper parser; Spartan Weekly is a clean net-new build).

**Method 4 — Lis pendens at the ROD? (tested — mostly CLOSED).**
- Finding: SC foreclosure lis pendens is filed under §15-11-10 with the **"clerk of each county"** — which for foreclosure means the **Clerk of Court (PublicIndex)**, indexed in the judgment index, **not** recorded as a deed instrument at the free ROD (Register of Deeds/RMC). Greenville and other counties file "Foreclosures/Lis Pendens" through the Clerk of Court, confirming this. So the *free ROD portals we already scrape do not carry the foreclosure lis pendens* — this hoped-for earliest-signal shortcut is a **confirmed wall**, not a bug. (A *voluntary* lis pendens on other civil matters can be recorded at ROD, but the mortgage-foreclosure LP that we want lives with the Clerk.)
- Accuracy of ROD path for foreclosure LP: **~0%.** Do not chase.

**Method 5 — Model the filing-date from the sale-date (fill the lead-time gap).**
- Mechanics: We recover the *sale* (Methods 1–3) but lose the months of lead time the lis pendens would have given. Backfill it statistically: SC judicial-foreclosure timeline from LP → sale is empirically ~**8–14 months** (contested longer). Once we have a corpus of matched (LP-date, sale-date) pairs — obtainable compliantly via one-time human PublicIndex lookups on *closed* cases — fit a distribution and impute an estimated original-filing window per new roster case. This does not create new leads; it *tags equity/urgency*.
- Accuracy: filing-date estimate ±60–90 days on ~70% of cases; useful for prioritization, not for beating competitors to the earliest filing.
- Effort: Low-med (join on existing board; one calc).

### How close can we REALISTICALLY get
- **The SALE roster (the actionable distressed-seller list): exact 100% capture across all 7 counties**, split by channel — county-hosted PDF (Anderson, Pickens), newspaper HTML (Spartanburg), statewide MIE roster viewer human-pull (Oconee, Union, Laurens; Cherokee via records-room/paper). Lead time **~21 days pre-sale**.
- **The EARLIEST signal (lis pendens, months earlier): ~0% compliant recovery at scale.** It is centralized only in ToS-walled PublicIndex and is *not* at the free ROD. We recover it exactly **0 days early** in bulk; only per-case human lookups reach it.
- Net: we get **100% of foreclosures that reach sale, at T-21**, and a **±60–90-day modeled filing date on ~70%** of them — but we structurally **cannot** get the true weeks-1-to-8 head start at scale.

### Concrete build (what enricher/model to write, keyed on what)
1. **`sc_mie_roster` scraper** (net-new, keyed on **county + sale-date**):
   - Anderson adapter: build the `andersoncountysc.org/.../Month-D-YYYY-Sale-List.pdf` URL for each first-Tue/Thu, download, OCR (reuse project_doc_ocr Gemini-first chain), parse case#/owner/address/TMS/judgment.
   - Pickens adapter: crawl `sales_rosters.php`, pull Roster + Deficiency + Results PDFs, same OCR/parse.
   - Emit to board via `web_artifact.load_board()` (per board-writer rule).
2. **`spartan_weekly_notices` scraper** (net-new, keyed on **notice-slug**): weekly GET of `/legal-notices/master-and-equity`, diff slugs, fetch each detail page, regex TMS/plaintiff/judgment/sale-date. Covers Spartanburg natively and earlier than the roster.
3. **`sc_mie_roster_calendar` operator doc + cron** for Oconee/Union/Laurens/Cherokee: fires T-21 before each county's sale day, tells the operator the exact sccourts MIE-roster URL/date to open and save; offline parser ingests the saved page (mirrors project_manual_court_export_lane).
4. **`filing_date_model`** enricher (keyed on **case_id**): impute LP→sale lead time from a fitted SC timeline distribution; write `est_lp_date` + `confidence`.
5. **Paper-of-record map** (data file): resolve each of the 7 counties → its legal-notice newspaper + whether notices are posted as HTML (expand Method 3 beyond Spartanburg).

### What still can't be recovered (the true irreducible core)
- **The weeks-early lis-pendens head start, in bulk.** The only statewide, name-searchable, filing-time index is PublicIndex, and it is ToS/Rule-610-barred for automated + commercial-bulk use, and the foreclosure LP is *not* mirrored to the free ROD. No compliant surface centralizes SC foreclosure *filings* the way the MIE surfaces centralize foreclosure *sales*. We therefore permanently trade **lead time (months → ~21 days)** for compliance.
- **Cases that die before sale** (reinstated, refinanced, dismissed, BK-stayed) never hit a roster → invisible to us, which is actually correct (they're no longer motivated sellers).
- **Non-judicial-court civil signals in the same index** (e.g., partition-suit early stages, deficiency judgments not yet set for sale) remain PublicIndex-only until they schedule.


## NC earlier foreclosure signal (pre-sale-calendar)

### The wall (why it's "impossible" — restate precisely)
Today's NC lane scrapes law-firm **sale calendars** (Brock & Scott, Hutchens, LOGS/Shapiro & Ingle, ALAW) plus tax-foreclosure listings. Those fire at the **notice-of-sale** stage: the sale is already advertised, the courthouse posting is up, and the property lands on the calendar ~20-25 days before the auction. By then the deadline funnel is nearly closed and every other buyer/wholesaler in the state sees the identical list. The "wall" is that the truly early events — the substitute-trustee appointment recorded at ROD, and the **notice-of-hearing (NOH)** that opens the `SP` special proceeding at the Clerk of Superior Court — are assumed to be locked behind the WAF-walled eCourts Smart Search (per memory: `project_nc_ecourts_endpoint_split` — estates/raw-SP browser is Akamai/WAF-walled; only the Judgment-Search JSON is open). So NC has no early, free, structured trigger comparable to a lis-pendens feed.

### Reconstruction methods (each: the method, the math/mechanics, the free data it needs, realistic accuracy %, effort)

NC power-of-sale timeline (statutory, G.S. 45-21.16 / Art. 2A), anchoring every method:
```
Default → Substitute Trustee appointed & RECORDED at ROD  ──► T-60 to T-90 before sale
       → NOH filed, SP case opened at Clerk               ──► T-35 to T-55 before sale
       → Hearing (NOH served ≥10d personal / ≥20d posted) ──► T-25 to T-35
       → Notice of Sale posted + newspaper (≥20d)          ──► T-20 to T-25  ← TODAY'S LANE
       → Sale/auction                                      ──► T-0
       → Upset-bid rounds (10d each, resets)               ──► T+10, +20…
```

1. **Substitute-Trustee-Appointment mining at ROD (earliest free surface).**
   Mechanics: Before a firm can foreclose, the beneficiary records a "Substitution of Trustee/Appointment of Substitute Trustee" (G.S. 45-10) naming the foreclosure firm as new trustee. This is a **recorded instrument at the Register of Deeds**, which we already scrape/OCR in the SC/NC counties. A recorded substitution naming Brock & Scott / Hutchens / Shapiro & Ingle / ALAW / Rogers Townsend as trustee is a ~95%-reliable pre-foreclosure flag: firms don't get substituted unless a POS foreclosure is imminent.
   Free data: ROD grantor/grantee index + instrument-type filter (`SUBSTITUTION OF TRUSTEE`, `APPOINTMENT OF SUBSTITUTE TRUSTEE`) — the same AcclaimWeb / lrcpwa / NC OneMap-linked ROD portals already in the stack. The grantor = borrower (property → equity join works), grantee = the firm.
   Accuracy: ~90-95% of these convert to an actual NOH filing within 30-90 days; a minority get cured/reinstated. Lead time: **T-60 to T-90 → 35-65 days earlier than the sale calendar.**
   Effort: Medium. ROD instrument-type scraping already exists for several counties; needs a new instrument-type filter + a firm-name allowlist. Blocked in counties where ROD rebuild is pending (per `project_new_facet_scoping`).

2. **eCourts Portal SP-case listing via the *compliant* Smart Search date/type filter (re-test the wall).**
   Mechanics: Memory flags Smart Search as WAF-walled for *estates/raw-SP browsing*, but the split note distinguishes the **open Judgment-Search JSON** from the browser. The Portal's Smart Search *does* expose "Foreclosure (special proceeding)" as a non-confidential category under NCGS 7A-109(b). The compliant human-gather-then-parse-offline path (per `project_manual_court_export_lane`): operator runs a county + "Special Proceeding / Foreclosure" + filed-date-range search on portal-nc.tylertech.cloud, saves the result-list HTML, and an offline parser ingests `YYSPnnnnnn-xxx` case numbers + party names + filed date. This captures the **NOH filing** directly.
   Free data: eCourts Portal result-list HTML (operator-saved; no ToS scrape). Case# + caption (borrower + firm) + filed date.
   Accuracy: ~100% of true NOH filings that are non-confidential; near-1:1 with actual foreclosures. Lead time: **T-35 to T-55 → 15-30 days earlier than the calendar.** The list page has the case not the detail (per memory) — but caption + filed date + county is enough to key the lead and hand off to ROD for property/book-page.
   Effort: Medium (operator SOP + list parser); Low incremental since the manual-export lane and parsers already exist.

3. **Trustee-firm pending-sales lists parsed for the SP# + book/page (upgrade the existing lane, don't just read the calendar).**
   Mechanics: The firm lists already carry **Court SP#, Case#, county, address, opening bid, and Book/Page** (confirmed live on Brock & Scott: fields = County, Sale Date/Time, `24SP000238-770`, `24-29191-FC01`, address, opening bid, `Book/Page 2166/47`). Firms post a property to their "pending sales" page **when the sale is scheduled but often before the newspaper run and sometimes carrying an earlier "sale date TBD / on hold" status** (LOGS explicitly flags "On Hold"). Polling these daily and diffing new SP#s catches a property a few days-to-weeks before it hits ncnotices/newspaper aggregators, and the Book/Page lets us join straight to the parcel without geocoding.
   Free data: Brock & Scott (`/foreclosure-sales/?_sft_foreclosure_state=nc`, ~40+ counties incl. Gaston, Buncombe, Catawba), Hutchens (`sales.hutchenslawfirm.com/NCfcSalesList.aspx`), ALAW (`alaw.net/foreclosure-sales/north-carolina/`), Shapiro & Ingle/LOGS (`logs.com/nc-upcoming-sales-report.html` — **PowerBI embed, needs the stealth browser to extract, not clean HTML**).
   Accuracy: 100% for scheduled sales; the lead over newspaper is only **~3-10 days** but the SP#/Book-Page enrichment value is high. Effort: Low-Medium (Brock/Hutchens/ALAW = clean HTML/aspx; LOGS = PowerBI stealth-render).

4. **Newspaper NOH/Notice-of-Sale via ncnotices.com (NC Press Assn) as the county-complete backstop.**
   Mechanics: Every POS sale must run in a general-circulation paper; NC Press Assn aggregates **all 100 counties free** with a "Foreclosure" category, 12-month rolling window. Confirmed the notice title itself carries the SP# (`26SP000016-950 NOTICE OF FORECLOSURE SALE`) plus record owner, deed-of-trust Book/Page, substitute trustee, and sale date/time.
   Free data: ncnotices.com foreclosure category by county (no official API/RSS → operator-saved search pages or compliant HTML parse of the free result list).
   Accuracy: ~100% county coverage (statutory requirement) but **latest surface — same T-20 to T-25 as the calendar**, so it's a coverage-completeness net, not an early signal. Effort: Low.

### How close can we REALISTICALLY get (a number)
- **Exact same-day-as-firm early signal: not the goal.** Realistic earlier signal:
  - **ROD substitute-trustee mining → ~35-65 days earlier** than the current calendar lane, on the counties where ROD instrument-type search is live (today that's a subset — call it ~50-60% of the 11 NC counties given the pending ROD rebuild; buildable to ~80%+ as ROD comes online).
  - **eCourts SP manual-export → 15-30 days earlier, ~100% of non-confidential NOH filings, all 11 counties** (Portal is statewide/Odyssey-complete as of Oct 2025), at the cost of an operator step.
  - **Firm-list SP#/Book-Page upgrade → 3-10 days earlier + full enrichment**, ~clean HTML for 3 of 4 major firms.
- Net: we can move the NC trigger from **T-22 (today) to roughly T-45 median** (eCourts NOH as the workhorse, ROD substitution as the bleeding edge), i.e. **~20-25 days of additional outreach runway on ~90-100% of in-footprint NC power-of-sale foreclosures**, with property/equity join via Book/Page rather than geocoding.

### Concrete build (what enricher/model to write, keyed on what)
1. `nc_substitute_trustee_scraper.py` — keyed on **ROD instrument-type = SUBSTITUTION/APPOINTMENT OF SUBSTITUTE TRUSTEE**, grantee ∈ firm allowlist {Brock & Scott, Hutchens, Shapiro & Ingle/LOGS, ALAW, Rogers Townsend, Nordman/other}. Emits borrower(grantor) + Book/Page(of the DoT referenced) + firm + record date. Reuses existing AcclaimWeb/lrcpwa ROD paths. `signal_stage="substitution"`, `est_sale_window = record_date + 60..90d`.
2. `nc_ecourts_sp_parser.py` — offline parser for operator-saved eCourts Portal Smart-Search result lists filtered to **Special Proceeding / Foreclosure, filed-date range, per county**. Extracts `YYSPnnnnnn-xxx`, caption(borrower + firm), county, filed date. Slots into the existing `manual_court_export_lane`. `signal_stage="NOH_filed"`. Add a 3-firm-name trigger-list operator doc.
3. `nc_trustee_firm_sales.py` (upgrade) — parse **SP# + Case# + Book/Page + opening bid + status(On Hold)** from Brock & Scott (WP `_sft` filter, clean), Hutchens (`NCfcSalesList.aspx`), ALAW; add a **PowerBI stealth-render** extractor for LOGS `nc-upcoming-sales-report.html`. Daily diff on SP# to flag net-new. Book/Page → parcel join (skip geocode).
4. `nc_public_notices_backstop.py` — ncnotices.com "Foreclosure" category, per-county, dedup by SP# against #1-3; pure coverage net.
Join key across all four: **SP# (`YYSPnnnnnn-CCC`) as the NC foreclosure primary key**, with Book/Page as the property join to the existing parcel/equity backbone. De-dup precedence: substitution → NOH → firm-list → newspaper (earliest wins, later stages enrich).

Firm→county coverage map (the gap picture): Brock & Scott and Hutchens are statewide high-volume and both explicitly list **Gaston, Catawba, Buncombe-region** sales; LOGS/Shapiro & Ingle and ALAW are statewide but lower-volume. No single firm covers all 11; the **union of the 4 firm lists ≈ 85-90% of POS volume**, and the **eCourts SP feed + ncnotices backstop close the remaining firm-coverage gaps** (small local counsel firms — Mitchell, Polk, McDowell, Transylvania — that don't run public sale portals). That is exactly why methods #2 and #4 (court + newspaper, which are firm-agnostic and county-complete) are required alongside the firm lists.

### What still can't be recovered (the true irreducible core)
- **Pre-substitution default (missed payments / breach-letter / 30-60-90 delinquency).** The actual mortgage-default event lives with the servicer; no free public surface fires until the trustee substitution or NOH. That is the genuine irreducible core — we cannot beat ~T-90.
- **Confidential/withheld SP filings** and any case a clerk marks non-public under 7A-109(b) never appear in Smart Search — a small residual.
- **Detail-page contents behind the eCourts list** (full party addresses, service dates) require `__doPostBack` navigation the WAF blocks; we get caption + case# + filed date only from the saved list (per memory).
- **Deals cured before sale** — a fraction of substitutions/NOHs reinstate and never reach auction; that's noise we accept in exchange for the 20-45 extra days, not something to eliminate.
- **LOGS PowerBI internals** beyond what the rendered visual exposes (no clean JSON endpoint) — extractable via stealth render but brittle.


## Owner phone at scale (compliant waterfall)

### The wall (why it's "impossible" — restate precisely)
Phone number is **not a public-record field** attached to a parcel or a deed. The property record gives you an **owner name + mailing address**; the phone lives only in (a) self-reported registration data, (b) telco/carrier files, or (c) aggregator "identity graphs" that stitch name+address→phone from purchased credit-header, telco, and app-SDK data. All three of the good sources are **paid**. The only free bulk phone in-footprint is the **NC voter file `full_phone_number` field**, which is self-reported-at-registration, exists only in NC (SC's public voter file has **no phone field at all**), and after you (1) restrict to owner-name matches, (2) drop the ~75-80% of NC voters who left it blank, and (3) discard dead landlines, collapses to the blueprint's **~2% usable-connect rate**. Free consumer reverse-lookup sites (TruePeopleSearch, TrueCaller, FastPeopleSearch) return a name/number but are **individual-lookup consumer tools** — TrueCaller hard-caps at 3 web lookups, all block bulk/API automation in ToS — so they are a **HOT-only manual lane**, not a scale source. There is no free bulk carrier/line-type feed.

### Reconstruction methods (each: the method, math/mechanics, free data it needs, realistic accuracy %, effort)

**M1 — Free NC voter phone join (the existing 2% floor, hardened).**
Mechanics: normalize owner name → match against `ncvoter` `full_phone_number` on (last, first, res-address ZIP/city). NC layout confirms the field is `varchar(12)` "full phone number including area code." Free data: NC SBE statewide download (already wired). Realistic: field is populated for only ~20-25% of NC registrants and skews landline; after owner-name match + landline decay you keep **~2-4% as a live connect** in NC counties, **0% in SC**. Effort: **already built** — just add a line-type heuristic (strip obvious landline prefixes → tag "voter-cell-likely").

**M2 — Business phone for LLC/trust-owned parcels via SoS (free, structurally different).**
Mechanics: when `owner_name` matches an entity pattern (LLC, INC, TRUST, HOLDINGS, PROPERTIES), don't skip-trace a person — pull the **registered agent + principal office + officer** from **NC SoS free entity search** (already have the SoS registered-agent enricher in the stack) and, where present, the agent/office **published phone**. Many small landlord LLCs list a working cell as the agent phone. Free data: NC SoS entity search (free), SC SoS (captcha-walled per memory — use manual-gather fallback). Math: entity-owned share of a distressed board runs **~15-30%** of parcels; of those, agent/officer phone is recoverable for maybe **~40-55%** in NC. Net: recovers phone on **~8-15% of entity-owned rows for free**. Effort: **low** — extend the existing SoS enricher to emit the phone field it already sees.

**M3 — HOT-only manual people-search (human-gather-then-parse-offline).**
Mechanics: for the top-N HOT leads only (high equity + hard trigger), an operator runs TruePeopleSearch/FastPeopleSearch by name+city, copies the result block, and an offline parser extracts the "wireless" number. Free data: consumer sites (no automation — compliant only as manual lookup). Accuracy: these sites surface a plausible number on **~70-85%** of individuals, of which **~55-65%** connect. Effort: **medium, and it does not scale** — cap at ~20-40 lookups/day/operator to stay in consumer-use bounds. This is your **cost-per-connect champion for HOT** (labor only, ~$0 data).

**M4 — Cheap bulk append (DataZapp) for the WARM body.**
Mechanics: batch-upload name+address, get cell/landline back. Verified pricing: **3¢/match, $125 minimum (~4,000 records), DNC-scrubbed at no charge**, 2¢ at prepaid volume. Match/connect: DataZapp lands a number on ~**50-60%** of records; effective **mobile connect ~50-65%** per R7. Effort: **low** (CSV in/out). This is the **default WARM tier**.

**M5 — Premium append (BatchData) only on WARM misses.**
Mechanics: re-run the ~40-50% DataZapp missed through a higher-fill graph. BatchData has moved to **~$500/mo subscription** (legacy ~7¢/trace); higher fill + line-type + DNC. Reserve for WARM rows that DataZapp whiffed **and** clear an equity threshold. Effort: low, but gated on spend.

### How close can we REALISTICALLY get (a number)
Exact/free phone at scale: **~2-4% of NC rows, 0% of SC rows** (M1) plus **~8-15% of entity-owned rows** (M2) → blended **free ceiling ≈ 5-8% of the whole board** with a live-ish number, of which perhaps half connect (**~3-4% free connect**). Add the cheap tier and it jumps hard: **DataZapp append reaches a number on ~50-60% and a ~50-65% mobile connect → ~30-38% board-wide connect at ≤3¢/record.** Premium mop-up on the residual lifts total **reachable-with-a-live-mobile to ~55-65%** of the board. So: *free bulk is a ~5-8% sliver; the realistic answer is a tiered waterfall that converts a $125-per-4,000 spend into a 1-in-3 connect, and only pays premium rates on the equity-qualified residual.*

### Concrete build (what enricher/model to write, keyed on what)
Write **`phone_waterfall.py`**, keyed on `(owner_name, owner_mailing_address, parcel_state, lead_grade)`, running tiers in cost order and **stopping at first hit**:
1. **Tier 0 (free, always):** `owner_name` entity-regex → if entity, call existing **SoS registered-agent enricher**, emit `phone` + `phone_source=sos_agent`. Else join to **NC `ncvoter.full_phone_number`**, emit `phone_source=nc_voter` with a landline/cell heuristic flag.
2. **Tier 1 (free, HOT only):** emit a **`manual_lookup_queue.csv`** (name, city, parcel) for the top-N HOT leads → operator fills numbers by hand from a consumer people-search → offline parser ingests back. Rate-capped.
3. **Tier 2 (cheap, WARM):** batch the Tier-0/1 misses to **DataZapp** (3¢, DNC-scrub on) via CSV; write back `phone_source=datazapp`, keep line-type.
4. **Tier 3 (premium, gated):** only WARM+ rows where DataZapp missed **and** `equity ≥ threshold` → **BatchData**; `phone_source=batch`.
Emit a **`cost_per_connect`** column = (tier spend) ÷ (rows that later connect), and a `dnc_flag` so texting/dialing honors scrub. Store `phone_confidence` = f(source, line_type, voter-field-age).

### What still can't be recovered (the true irreducible core)
- **SC free bulk phone is genuinely zero** — no voter phone field, SC SoS captcha-walled; every SC individual-owner phone must come from a **paid** append or manual lookup. That floor cannot be modeled away.
- **The truly unlisted / VoIP-only / recently-ported / prepaid-burner owner** — no free or cheap graph has them; even premium tiers whiff on a hard residual of ~**15-25%** of individuals.
- **Right-party verification** — an appended number is a *candidate*, not a confirmed owner-cell; without a paid identity-verify step you carry an inherent wrong-number rate (bad joins on common names, stale ports) that caps effective connect at the ~50-65% R7 figure no matter how much you spend. Free/cheap methods reduce cost-per-connect; they cannot eliminate the name→phone ambiguity that only right-party-verified (paid) data resolves.


## Free Vacancy Detection

### The wall (why it's "impossible" — restate precisely)
The gold-standard vacancy signal is the USPS **Vacant Delivery Indicator** in the Delivery Sequence File Second Generation (DSF2), where the mail carrier who physically walks the route flags any address that has stopped collecting mail for **90+ consecutive days**. This is the only source that reflects a human eyeball on the actual doorstep, updated nightly, nationwide. It is gated behind a **DSF2 NCOALink Full-Service license (~$175k–$191k setup plus per-record fees)** and is legally restricted to CASS/PAVE-certified licensees for mail-processing use — you cannot buy the vacancy bit standalone, and resellers (Regrid, AccuZIP, BatchLeads) pass through the license cost. So the single best occupancy truth is a hard paywall for a free/compliant engine. The wall is real: **there is no free feed of the actual USPS vacant bit.**

But USPS vacancy itself is a *lagging, noisy proxy for "distress"* — and that reframing is the whole crack in the wall. We don't actually need "is mail being collected"; we need "is this property likely non-owner-occupied / neglected / abandonment-trending," which is exactly what a motivated-seller engine wants. That target is reconstructable.

### Reconstruction methods

**1. Stacked distress proxy (the workhorse — reconstruct the *outcome*, not the USPS bit)**
- **Method:** Score each parcel on additive independent signals we already scrape or can scrape free: (a) **absentee owner** = owner mailing address ≠ situs address (already built, task #16); (b) **tax-delinquent 1yr / 3yr+** (already have NC PTS Cloud + SC qPayBill/qPaybill balances); (c) **code violation / nuisance case** open; (d) **no homestead/owner-occupancy exemption** on the assessor card; (e) **long tenure + no recent permit** (last-sale >15yr ago, zero building permits = deferred-maintenance risk); (f) **out-of-state / >500mi owner** (deeper absentee); (g) **estate/probate/foreclosure overlay** (already in the board).
- **Math/mechanics:** Logistic score, weights anchored to the literature. Tax delinquency is documented as "the single greatest indicator of property distress" and in the Savannah VAD study 3-yr tax delinquency + code violations were the two dominant labeling features. Absentee alone is weak (~most absentee owners are landlords with *occupied* rentals). The power is in the **AND**: absentee × 3yr-tax-delinquent × code-violation is where empirical vacancy concentrates. Model as P(vacant) = σ(β₀ + Σβᵢxᵢ) with the top-decile stack.
- **Free data it needs:** all already in-repo except code-violation cases (Asheville code-enf built; others patchy).
- **Realistic accuracy:** A *single* proxy is a poor vacancy predictor — absentee-only precision for vacancy is low (maybe 8–15%, since rentals dominate). But the **stacked top-decile** (3+ signals) reaches roughly **55–70% precision** against true vacancy, at low recall (you only flag the worst ~5–10% of parcels). That is *better than USPS for the distress use-case* because USPS misses vacant-but-mail-forwarded homes that your stack catches via tax/probate.
- **Effort:** Low-medium — it's a scoring layer over existing enrichers plus one new column each for homestead-exemption flag and permit-recency.

**2. "Return Service Requested" free mover-return (reconstruct USPS's own knowledge via your own mail)**
- **Method:** On the **first physical outreach mailer**, print the ancillary endorsement **"Return Service Requested"** (or "Address Service Requested") above the address. If the piece is undeliverable, USPS returns it to you **with the reason code** ("Vacant," "No Mail Receptacle," "Attempted-Not Known," "Moved Left No Address / MLNA") at no extra charge on First-Class. You are effectively renting the carrier's eyeball one address at a time, for the price of a stamp you were already spending.
- **Math/mechanics:** Batch #1 goes to the full lead list; ~2–4 weeks later the returns come back. Any piece stamped **VACANT / UMS / MLNA = confirmed occupancy failure**. Feed that back as a hard `usps_return_vacant=true` flag. This is the *actual* USPS vacant determination, obtained compliantly and free, just latency-shifted and only on addresses you mail.
- **Free data it needs:** nothing external — it's an endorsement string + a returns-intake step (photograph/scan the stamped envelope, OCR the reason).
- **Realistic accuracy:** **~95%+ on the addresses it covers** (it IS the carrier's flag), but only covers addresses you actually mailed, and only after one cycle of latency. Zero cost, fully compliant.
- **Effort:** Trivial to add the endorsement; medium to build the returns-OCR intake (reuse the existing Gemini doc-OCR enricher, project_doc_ocr).

**3. Municipal vacant-property / abandoned-building registries (free direct signal, where they exist)**
- **Method:** Scrape the registry / code-enforcement case list for the cities that maintain one. **Spartanburg** has a registry (~5k entries per the blueprint). **Asheville** as of 2026 was only *proposing* a boarded-up-structure ordinance (running list of ~30 targets, not a public registry yet). Most of the 18 rural counties have **no** registry.
- **Math/mechanics:** Direct join on address/parcel → `registry_vacant=true`. Where it exists it's authoritative.
- **Free data:** Municode ordinance list to identify which jurisdictions have one; Accela Citizen Access (Buncombe) and county open-data ArcGIS hubs (Spartanburg Open Data) for the case tables.
- **Realistic accuracy:** **~90% precision** where a registry exists (registries over-include recently-cured ones), but **coverage is maybe 1 of 18 counties today** (Spartanburg), so recall across the footprint is ~5–10%.
- **Effort:** Low per-jurisdiction; the work is discovery (which cities have one).

**4. Aerial / overgrown-lot & condition modeling (free imagery proxy for neglect)**
- **Method:** Pull free imagery (USDA NAIP annual 0.6m aerials; county GIS ArcGIS aerial tiles; Google/Bing Static Maps thumbnails within ToS for one-off viewing) and score **overgrowth, tarped roof, no vehicle in drive, debris**. NAIP is public-domain and downloadable. Even without CV, a **vegetation-index (NDVI) spike over the parcel footprint** flags un-mowed lots.
- **Math/mechanics:** Compute NDVI on the parcel polygon from NAIP 4-band; high vegetation *inside the building setback* + old sale = neglect proxy.
- **Free data:** NAIP (free), parcel polygons (already have via NC OneMap / SCDOT / chascogis).
- **Realistic accuracy:** Weak standalone (~20–30% precision — overgrowth ≠ vacant), but a useful **tiebreaker** that lifts the stacked model. Best on rural/large-lot parcels where mowing lapses are visible.
- **Effort:** Medium-high (imagery pipeline + NDVI); defer unless top-decile leads need a final filter.

**5. Utility-disconnect FOIA (reconstruct the "no active service" bit) — mostly a wall**
- **Method:** FOIA the municipal water utility for a list of long-term **inactive/disconnected residential accounts** (a vacant house has water shut off). In principle a public record for a government-run utility.
- **Reality:** Customer-level utility data (name, address, usage, account status) is **exempt as PII in most states' public-records law** — the search confirms names/addresses/usage are routinely redacted, and several states carve out utility-customer info explicitly. SC FOIA and NC public-records both let utilities withhold individually identifiable customer info. You might get **aggregate** disconnect counts by area, not address-level.
- **Realistic accuracy:** Address-level = near-zero (blocked by privacy exemption); this is a confirmed wall, don't chase per-address.
- **Effort:** High for near-zero yield. Skip.

### How close can we REALISTICALLY get
- **Exact free USPS vacant bit, per-address, on demand: 0%** (license-gated) — *except* via method #2, which recovers the true carrier flag at **~95%** but only on addresses you mail and with a 3–4 week lag.
- **A usable vacancy/abandonment probability on ~100% of the board, computed today:** the stacked proxy (method #1) gives a **top-decile precision of roughly 55–70%** for "vacant or abandonment-trending," at low recall — i.e., you can confidently rank the worst ~5–10% of parcels. That is the honest number: **no exact flag, but a ±proxy that is right ~6-in-10 on the sharpest 5–10% of the list, and that self-corrects to ~95% on any address after one mail cycle.**
- Net: for a **motivated-seller** engine (which cares about distress, not literal mail-collection), the reconstruction is *arguably as good as or better than* buying USPS, because USPS misses the tax/probate/absentee signal you already have.

### Concrete build
- **`vacancy_score` enricher**, keyed on **parcel_id** (fallback situs address), that reads existing board columns and emits `vacancy_score` (0–1) + `vacancy_signals` (list) + `vacancy_tier` (top-decile / mid / none). Weights: 3yr-tax-delinquent 0.30, open code-violation 0.25, absentee>500mi 0.15, no-homestead-exemption 0.10, last-sale>15yr & zero-permits 0.10, estate/foreclosure overlay 0.10. Calibrate the threshold on any addresses where method #2 later returns ground truth (closes the loop, makes it a learning model).
- **Two new cheap columns** feeding it: `homestead_exemption` (assessor card boolean — already parse these cards) and `permit_recency` (last permit date from the Accela/county portals you already hit).
- **`usps_return_vacant` intake**: add the "Return Service Requested" endorsement to the mailer template; build a returns-OCR step on the existing Gemini OCR enricher to parse the stamped reason code back onto the parcel. This is the highest-value, lowest-effort item — it literally gives you the real USPS flag for free.
- **Spartanburg registry scraper** (Spartanburg County Open Data ArcGIS / code-enforcement) → `registry_vacant`. One-jurisdiction win, but it's the 5k the blueprint already named.
- Defer NAIP/NDVI (#4) as an optional top-decile tiebreaker; skip utility FOIA (#5).

### What still can't be recovered (the true irreducible core)
- **Instant, per-address, whole-footprint occupancy truth** — the thing USPS DSF2 sells. Method #2 recovers it but only *after* you mail and *only* where you mail; you can never pre-filter the entire county to "occupied vs vacant" for free before spending a stamp.
- **The specific vacant-but-current owner:** a house that is physically empty but whose owner is not tax-delinquent, not absentee, not in probate, still collects/forwards mail, and has no code case — a "clean vacant" (snowbird, recently-inherited-and-paid-off, between-tenants rental) — is **invisible to every free signal** and to the proxy stack. USPS would catch it; you won't, until the mailer bounces.
- **Address-level utility disconnect status** — permanently walled by PII exemptions in SC/NC public-records law; only aggregate counts are obtainable, which are useless for lead-level targeting.
- **Real-time change:** even USPS lags 90 days; your proxy lags to annual tax/assessor refresh. Nobody free has today's occupancy.

**Sources:**
- [HUD USER — USPS Vacancy Data](https://www.huduser.gov/portal/datasets/usps.html)
- [NEOCANDO — USPS Vacancy Indicators](https://neocando.case.edu/resources/neocando/new%20docs/11-%20USPS%20Vacancy%20Indicators.pdf)
- [Center for Community Progress — Delinquent Property Tax Enforcement](https://communityprogress.org/blog/delinquent-property-tax-enforcement-could-be-the-missing-piece-in-fighting-vacant-properties/)
- [Liang et al. — Savannah VAD human-in-the-loop ML (arXiv 2407.11138)](https://arxiv.org/abs/2407.11138)
- [USPS Postal Explorer — Ancillary Service Endorsements (507)](https://pe.usps.com/text/dmm300/507.htm)
- [WLOS — Asheville abandoned-building ordinance proposal](https://wlos.com/news/local/abandoned-building-ordinance-proposed-reduce-fire-squatter-concerns-asheville-north-carolina)
- [Reporters Committee — Public utility records / privacy exemptions](https://www.rcfp.org/open-government-sections/r-public-utility-records/)
- [DistressIQ — absentee/vacancy signal-stacking hit rates](https://www.distressiq.ai/blog/absentee-owner-list-north-carolina)


---

# Deep-Dive Round 10 — Valuation Science (defensible ARV/rehab/max-bid, 2026-07-02)


## ARV via the Sales-Comparison Adjustment Grid

Our engine already has the skeleton of a grid (`enrichment_comps._adjust_comp`), but it uses fixed textbook constants (`BATH_ADJ=$5000`, `YEAR_ADJ=$400/yr`, `LOT_ADJ_PER_SQFT=$1`, `MARGINAL_GLA_FRAC=0.40`), covers only 4 lines (GLA/baths/lot/age), never brackets the subject, and `calc.py` reconciles by taking the plain **median** of adjusted $/sqft. A licensed appraiser does none of those things by rule of thumb — every dollar is **market-derived**, the subject is **bracketed**, and the final number is a **weighted reconciliation**, not a median. This section makes each of those defensible.

### The professional method (how appraisers/AVMs/pros actually do it — concrete mechanics)

**The grid.** The URAR/Form 1004 grid lays comps in columns and *elements of comparison* in rows, adjusted in a fixed sequence: **(1) transactional adjustments first** — property rights, financing, conditions of sale, then **date-of-sale / market conditions** — **(2) then property adjustments** — location, site/lot, GLA, age, condition, quality, room count (beds/baths), garage/carport, basement (and % finished), and amenities (pool, view, deck). Order matters: the time adjustment is applied to the raw sale price *before* physical adjustments, because you are first restating each comp at today's market, then adjusting the physical differences ([Fannie Mae B4-1.3-09](https://selling-guide.fanniemae.com/sel/b4-1.3-09/adjustments-comparable-sales); [MD Appraisers](https://mdappraisers.com/articles/sales-comparison-approach/)).

**Sign convention.** Adjustments are made *to the comp, toward the subject*. If the comp is **superior** (bigger, newer, extra bath), subtract; if **inferior**, add. A comp 500 sqft larger than the subject gets a **negative** GLA adjustment ([LegalClarity](https://legalclarity.org/sales-comparison-approach-comps-adjustments-bracketing/)).

**How each dollar is derived — three sanctioned methods, in order of rigor:**
1. **Paired-sales (matched-pairs) analysis** — the primary method. Find two sales identical except one variable; the price gap ÷ the quantity difference is the adjustment. Two houses alike except one has a garage → the price delta *is* the market's garage value ([Chris Ponsar MAI](https://chrisponsar.com/2013/08/23/sales-comparison-adjustments-and-paired-sales/)).
2. **Regression / grouped-data** — regress sale price on the feature to get its marginal coefficient. For GLA, the slope is the $/sqft adjustment.
3. **Cost / depreciated-cost** — feature value ≈ depreciated cost to add it (RSMeans-style), used when paired data is thin (e.g., pools, decks).

**The GLA number is the big one, and it is NOT the market $/sqft.** The size adjustment is the *marginal* contribution of a foot, not the average. Empirically it lands at **~30–60% of the average comp $/sqft**, decreasing as homes get bigger/older ([AppraisersForum](https://appraisersforum.com/forums/threads/gla-adjustments.228865/)). A published regression example computed a GLA slope of **$80.64/sqft = 47.1% of the average $/sqft**, matching the classic rule of thumb of "average $/sqft × 50%, capped ~$80" ([WorkingRE](https://www.workingre.com/a-spreadsheet-solution-for-estimating-gla-adjustments/)). Using the *full* $/sqft double-counts, because a bigger comp already sold for more in total — this is exactly the error a raw-median-$/sqft model makes.

**Typical market-derived dollar amounts** (paired-sale medians, to sanity-bound the derivation):
- Full bath **$5,000–$7,000**; half/¾ bath **$2,000–$3,000** ([Sacramento Appraisal Blog](https://sacramentoappraisalblog.com/2013/04/29/how-much-is-one-extra-bedroom-or-bathroom-worth-2/))
- Bedroom **$5,000–$10,000** (weak/"filler" — bedroom count is confounded with GLA; appraisers warn against a standalone bed line)
- Garage **$4,000–$5,000 per bay** (up to ~$10k/stall in some markets)
- Condition **~5% of sale price per C-rating step** (C1–C6 scale); condition/upgrade adjustments **rarely exceed 10% of value** ([WorkingRE](https://www.workingre.com/a-spreadsheet-solution-for-estimating-gla-adjustments/); [Cleveland Appraisal Blog](https://clevelandappraisalblog.com/2019/11/14/how-appraisal-adjustments-work/))
- Lot/site: non-linear, `value = a·(size)^b` with **b ≈ –0.7** (marginal acre worth less as lots grow), or a $/sqft rate capped at ~10% of price
- Date-of-sale: `(effective_date − sale_date) × monthly market trend` — Fannie **requires** this be supported by an HPI or paired sales, not assumed zero ([Fannie Mae B4-1.3-09](https://selling-guide.fanniemae.com/sel/b4-1.3-09/adjustments-comparable-sales))

**Gross/net adjustment limits.** The old **15% net / 25% gross / 10% line** guidelines (net adj ≤15% of comp price, gross ≤25%, any single line ≤10%) were **retired from the Fannie selling guide in 2014** — they were arbitrary, and adjustments must instead reflect the market ([McKissock](https://www.mckissock.com/blog/appraisal/appraisal-adjustments-types-methods-and-cheat-sheet/); [Fannie B4-1.3-09](https://selling-guide.fanniemae.com/sel/b4-1.3-09/adjustments-comparable-sales)). But they survive as an excellent **quality/weighting heuristic**: a comp needing >25% gross adjustment is too dissimilar to trust and should be down-weighted or dropped. Our code already implements a 25%-gross cap (`MAX_GROSS_ADJ_FRAC`); the improvement is to use it for *weighting*, not just clamping.

**Bracketing.** Appraisers deliberately choose comps that fall on **both sides** of the subject for GLA, age, condition, and price — at least one larger and one smaller, one superior and one inferior. Bracketing proves the adjusted values converge from both directions and the answer isn't an extrapolation ([LegalClarity](https://legalclarity.org/sales-comparison-approach-comps-adjustments-bracketing/)).

**Reconciliation — the step we skip.** The final value is **NOT the mean or median** of adjusted comps. A straight average "treats a weak comp the same as a strong one" ([NEREJ/Pastuszek](https://nerej.com/reconciliation-the-common-sense-approach-by-bill-pastuszek)). The appraiser weights toward the comps that (a) needed the **fewest and smallest** adjustments, (b) are **closest/most similar**, and (c) are **most recent** ([Birmingham Appraisal Blog](https://birminghamappraisalblog.com/faqs/appraisers-reconcile-value/); [McKissock weighted-mean](https://www.mckissock.com/blog/appraisal/weighted-mean-a-simple-appraisal-reconciliation-technique/)). Fannie's own **Collateral Underwriter** does this statistically via a regression-based model producing a supported value plus adjustment feedback.

**Institutional accuracy targets** (what "defensible" means numerically): production AVMs aim for **PPE10 > 75%** (share of estimates within 10% of truth), **MdAPE ≈ 5–10%**, and **FSD ≤ 13% = high confidence, 13–20% = medium, >20% = low** (Freddie HVE bands) ([Clear Capital](https://www.clearcapital.com/blog-avm-testing-glossary/); [Freddie Mac Metrics Matter](https://sf.freddiemac.com/docs/pdf/fact-sheets/dougwhitepaper_metricsmatter.pdf)).

### How to encode it in our engine (the algorithm/rules, keyed on the data we have)

Replace the static-constant grid + median reconciliation with a **market-derived, bracketed, weighted grid**. Per subject, given the comp pool `raw['comps']` (each has `sold_price, sqft, beds, baths, lot_sqft, year_built, sold_date, distance_mi`) and the local sold pool from `enrichment_comps`:

**Step 1 — Derive adjustment coefficients FROM THE LOCAL POOL (not constants).** Using the full same-kind sold pool for the county (already in memory in `enrich_with_comps`), fit each coefficient and pass them into `_adjust_comp`:
- **GLA $/sqft:** OLS slope of `sold_price ~ sqft` over the pool (pool needs n≥10; use `numpy.polyfit` deg 1). **Clamp the slope to [0.30, 0.60] × median pool $/sqft** — that band is the empirical guardrail and stops a noisy small-sample regression from emitting a $5/sqft or $300/sqft coefficient. Fall back to `0.50 × median $/sqft` when n<10 (this replaces the fixed `MARGINAL_GLA_FRAC=0.40` with a *derived* fraction).
- **Bath, garage, lot, age:** attempt a small multiple regression `sold_price ~ sqft + baths + garage + lot + age`; keep a coefficient only if it is the right sign and within a sane band, else fall back to the paired-sale medians above (bath $5–7k, garage $4–5k/bay, age via a derived $/yr, lot via `a·size^-0.7`). This matches WorkingRE's explicit advice: derive GLA statistically, set low-impact lines (bath/garage) from matched pairs/experience.

**Step 2 — Time-adjust every comp FIRST.** `adj_time = sold_price × monthly_trend × months_since_sale`. Source `monthly_trend` free from the FHFA HPI we already pull (`raw['fhfa_value']`) or the pool's own median-$/sqft-by-month slope. This is a **new line we don't have** and is a Fannie *requirement*; on a 6-month comp window with 6%/yr appreciation it's a ~3% swing per comp.

**Step 3 — Build the full grid** (extend `_adjust_comp`): add **beds** (small/optional, flagged as confounded), **garage** (from `raw['gis']`/HomeHarvest `parking`), **basement**, **condition** (comp condition tier we already infer via `_comp_condition_tier`, at ~5%/step), **quality**, and the **date-of-sale** line. Keep the running **gross** and **net**.

**Step 4 — Bracketing check.** After adjusting, verify the comp set brackets the subject on GLA and price (≥1 comp with `sqft > subj` and ≥1 with `sqft < subj`; same for adjusted price). If not bracketed, set `bracketed=False` and cap ARV confidence at MEDIUM (extrapolation, not interpolation).

**Step 5 — Weighted reconciliation (replace the median in `calc.py`).** Compute a weight per comp and take a **weighted mean of adjusted values**, not the median:
```
w_i = 1 / (1 + gross_adj_frac_i)        # fewest/smallest adjustments
    × 1 / (1 + distance_mi_i / 5)        # closest
    × 1 / (1 + months_since_sale_i / 6)  # most recent
    × (0 if gross_adj_frac_i > 0.25 else 1)  # retired-but-useful 25% gross gate
ARV = Σ(w_i · adjusted_value_i) / Σ(w_i)
```
This is exactly the appraiser's "give most weight to the comp needing the fewest adjustments" reduced to a formula, and mirrors CU's weighting logic. `calc._arv_signals` Tier-0/Tier-1 change from `median_ppsf × sqft` to consuming this weighted adjusted value; keep low/high as the min/max adjusted comp for the band.

**Step 6 — Confidence from dispersion (FSD-style).** Set `arv_confidence` from the **coefficient of variation of the adjusted values** and bracketing: CV ≤ ~7% AND bracketed AND ≥3 comps AND max gross ≤25% → HIGH; CV ≤ ~15% → MEDIUM; else LOW. This replaces today's ad-hoc `ppsfs[-1]/ppsfs[0] >= 1.6` spread test with the institutional FSD bands (≤13% high / ≤20% medium).

### Free data/params it needs

Everything is already in the pipeline or computable — **no paid data**:
- **Comp pool** (`enrichment_comps` HomeHarvest sold pool, $0) — already have; needed at pool scale (n≥10) for regression, which we already fetch per county.
- **Per-comp fields** `sqft, beds, baths, lot_sqft, year_built, sold_date, parking/garage, distance_mi` — HomeHarvest already returns these; garage/parking and `sold_date` need to be threaded into the comp dicts (currently dropped).
- **Monthly market trend** for the time adjustment — free from FHFA HPI (`raw['fhfa_value']`, already pulled) or derived from the pool's median-$/sqft-over-time regression.
- **Condition tier** — already inferred (`_comp_condition_tier`, `raw['vision']`).
- **Params (compiled-in, market-calibrated):** GLA fraction band `[0.30, 0.60]`, bath `$5–7k`, garage `$4–5k/bay`, condition `5%/step`, lot exponent `b=−0.7`, gross-gate `0.25`, FSD confidence bands `7%/15%`. Store in a `ADJUSTMENT_PARAMS` dict so `backtest_arv.py` can tune them against sold prices.
- Optional lift: `numpy` (already a dep via pandas/HomeHarvest) for `polyfit`/`lstsq`.

### Accuracy impact vs our current approach

Our current path takes the **median of raw-or-lightly-adjusted $/sqft × subject sqft** with static constants and no time/bracketing/weighting. The three biggest defensibility gaps and their expected impact:
- **Median → weighted reconciliation** removes the single largest source of appraisal-vs-model disagreement (a weak far/stale comp pulling the median). Weighting toward low-adjustment comps is what moves a model from "marketing AVM" toward "underwriting AVM"; institutional targets are PPE10 > 75% / MdAPE 5–10%. Our backtest note already shows ARV is *"unbiased-at-median but noisy"* — this attacks the noise directly and should tighten dispersion by roughly the CV of the dropped weak comps.
- **Market-derived GLA slope (band-clamped)** replaces a fixed 0.40 fraction; on non-average-size subjects (the large-modest-$/sqft houses our rehab cap already flags) using a *derived* 0.47-ish slope vs a flat 0.40 or, worse, full $/sqft, is the difference between a defensible and an indefensible size line. Prevents systematic ARV error on the tails of the size distribution.
- **Time adjustment** (currently **absent**) is a Fannie *requirement* and removes a ~half-window appreciation bias — on a 6-month window in a 6–10%/yr Carolina market that's a 1.5–2.5% ARV bias per comp, currently baked in silently.
- **Bracketing + FSD-band confidence** converts our confidence label from heuristic to the same statistic (FSD ≤13/20%) lenders use, so `arv_confidence` becomes directly comparable to institutional confidence scores and `grading.py` gates on a defensible number.

Net: this is the change that lets us say each ARV is "built like an appraisal" — market-derived lines, bracketed, weighted, with an FSD-style confidence — rather than "median of some comps."

### Build (specific function/change + effort)

- **`enrichment_comps.py` → new `_derive_adjustment_params(pool)`** (~40 lines): `numpy.polyfit` GLA slope + optional `numpy.linalg.lstsq` multiple regression; returns a params dict with band-clamps and paired-sale fallbacks. Called once per county pool in `enrich_with_comps` and passed into `_pick_3_comps`.
- **`enrichment_comps._adjust_comp`** (rewrite, ~60 lines): accept derived params; add **time**, **beds**, **garage**, **basement**, **condition**, **quality** lines; keep running gross/net; emit per-comp `adjusted_value`, `gross_adj_frac`, `months_since_sale`. Thread `sold_date` + `parking` into the comp dicts in `_pick_3_comps` (currently dropped).
- **`enrichment_comps._pick_3_comps`** (~20 lines): after adjusting, compute `bracketed` flag; **relax the "exactly 3, exact-bed" selection to deliberately bracket** (pick ≥1 larger, ≥1 smaller by GLA) instead of just closest-3.
- **New `enrichment_comps._reconcile(comps)`** (~25 lines): weighted-mean formula above → returns `(arv_point, arv_low, arv_high, cv, bracketed)`; write to `raw['comp_reconciled_arv']` + `raw['comp_reconcile_meta']`.
- **`calc._arv_signals`** (Tier-0/Tier-1, ~15 lines changed): consume `comp_reconciled_arv` instead of `comp_median_ppsf × sqft`; set `arv_confidence` from CV + bracketing (FSD bands) instead of the `1.6× spread` test.
- **`scripts/backtest_arv.py`**: add a sweep over `ADJUSTMENT_PARAMS` (GLA band, gross-gate, weight exponents) scored by **PPE10 / MdAPE / bias** against the recorded-sales harness already there — so the params are *tuned*, not asserted.

**Effort: ~1–1.5 days.** Medium. Reuses the existing pool fetch, comp dicts, condition inference, 25%-gross cap, and backtest harness; the genuinely new pieces are the regression-derived params, the time-adjustment line, bracket-aware comp selection, and the weighted reconciliation replacing the median. `numpy` is already available. Highest-ROI ordering: **(1) weighted reconciliation → (2) time adjustment → (3) derived GLA slope → (4) bracketing/FSD confidence.**


## Comp SELECTION Science

### The professional method (how appraisers/AVMs/pros actually do it — concrete mechanics)

Comp selection is a **screen-then-weight** problem. The pro pipeline is a funnel: define a candidate pool, screen it down to arms-length lookalikes, adjust each survivor to the subject and to the valuation date, then reconcile a value (median/weighted) plus a defensible confidence from the *dispersion* of the survivors.

**1. Proximity.** Fannie Mae (Selling Guide B4-1.3-08) dropped a hard mileage cap but still mandates "most proximate, recent, and similar," measured as a **straight-line distance in miles with a directional indicator** (e.g., "0.42 mi NW"), and requires comps from the **same market area / subdivision / project** when available because "sale activity from within the neighborhood is the best indicator of value." Practitioners operationalize this as a **tiered radius that adapts to sale density**: ≤0.5 mi (often same-subdivision) in dense suburbs, 1 mi standard (JVM: "within one mile … and not over any major barriers like freeways or rivers"), expanding to 2–5 mi rural — and never crossing a **physical/school-zone/jurisdiction boundary** even if the raw distance is short. AVMs formalize this as **distance-decay weighting** (IAAO AVM Standard) rather than a hard cutoff.

**2. Recency + time adjustment.** The industry default is **90 days preferred, 6 months (180 d) standard, 12 months maximum**, and any comp >6 months old requires a written explanation (Fannie B4-1.3-08). Critically, a recent comp is *not* used at face value — its sale price is **time-adjusted to the valuation date** using a local price trend. The trend is derived from a **repeat-sales index** (FHFA/Freddie FMHPI methodology: same-property paired resales eliminate mix distortion) or a paired-sale/regression time coefficient, expressed as a monthly appreciation rate. A comp that sold 5 months ago in a market appreciating 6%/yr gets ≈ +2.5% (5 × 0.5%). Skipping this is the single biggest silent error in thin, trending markets.

**3. Similarity screens (the "bracket").** Appraisers bracket the subject — carry comps both **above and below** on the key dimensions so the subject's value is interpolated, not extrapolated. Standard tolerances:
- **GLA (living sqft): ±20%** (JVM/Fannie norm; a 1,500 sqft subject → 1,200–1,800 sqft comps). Some investors relax to ±25%.
- **Bedrooms: exact** (bed count drives buyer pool and price bands non-linearly).
- **Age/year built: ±10–15 yr** (proxy for systems age and build quality).
- **Same style/design and quality/condition grade** (ranch vs 2-story, brick vs vinyl, C3 vs C5 UAD condition).
- **Lot size** adjusted separately, not screened, unless it drives value (rural/waterfront).

**4. Arms-length filtering.** IAAO ratio-study and mass-appraisal standards require screening out **non-market transactions before they touch the model**: nominal/$1 or family transfers, estate/foreclosure/REO, short sales, sheriff/tax deeds, quitclaims, inter-corporate transfers, and partial interests. **The exception that matters for a distressed engine:** when you are valuing a *distressed* subject for a *distressed exit*, REO/short comps are the correct comps for the "as-is distressed" number — but you value ARV (retail resale) off arms-length retail comps and derive the distress discount separately. Never blend the two into one median.

**5. Dispersion, outlier trimming, and reconciliation.** After screening, pros discard fliers and reconcile. IAAO recommends **COD (coefficient of dispersion) as the variability statistic of choice** (more outlier-robust than COV/std-dev). Residential uniformity benchmarks: **COD 5–10 for newer/homogeneous tracts, 5–15 for other residential**, PRD 0.98–1.03, PRB −0.05 to +0.05. Outliers are trimmed by **IQR fence (drop $/sqft outside Q1−1.5·IQR … Q3+1.5·IQR)** or MAD (median ± 2–2.5·MAD), *not* mean ± SD (the outliers you want to drop inflate the SD and hide themselves).

**6. Count + weighting that minimizes error.** Appraisal minimum is **3 closed comps** (Fannie); AVMs use **k-nearest-neighbor with k ≈ 3–10** and choose k by cross-validation (bias/variance trade-off). The winning weighting scheme in the mass-appraisal literature is a **Gaussian-kernel adaptive-bandwidth** weight over a composite distance (geographic + temporal + physical), e.g., GTCWR/GWR studies find the **Gaussian adaptive kernel most uniform by IAAO standards**. A well-selected comp AVM targets **error within 3–5% of actual sale price** (≤3% for "highly reliable"). Equal-weighted median of the *screened* set is the robust floor; distance/similarity-weighting on top buys accuracy only after screening is right.

**7. Rural / thin markets.** When a tight screen yields <3 comps, pros **relax in a fixed priority order** and record which gate was relaxed (it drives confidence): expand radius (1→2→5→10 mi) *before* widening sqft band; extend the window (180→365 d) *before* dropping the arms-length screen; cross a subdivision boundary *before* crossing a school/market boundary. Land/rural is valued on **$/acre from land comps**, not $/sqft. IAAO explicitly allows using **post-calibration sales** when few sales exist. The relaxation ladder itself becomes the confidence signal — HIGH only if the tight screen held.

### How to encode it in our engine (the algorithm/rules, keyed on the data we have)

Our engine already implements most of this correctly. `enrichment_comps.py` runs a **staged funnel** (kind → geo gate ≤10 mi → zip-match → ±20% sqft band → exact beds → ±15 yr → style bucket) over a 180-day sold pool, and `enrichment_recorded_comps.py` runs the **Tier-0 recorded arms-length path** (county GIS point-buffer, price > $10k, sqft > 200, $/sqft ∈ [20, 800], median + p25/p75). `calc.py` reconciles by **median of `adjusted_ppsf`** with a p25–p75 band. The gaps to close are: (a) **time adjustment is missing**, (b) **outlier trim is implicit** (relies on median, no explicit IQR fence), (c) **weighting is flat** (no distance/similarity decay), (d) **confidence is count-based only**, not dispersion-based, and (e) the **relaxation ladder isn't logged** as a confidence input.

Concrete rule set to encode:

1. **Time-adjust every comp `$/sqft` to run date.** `adjusted_ppsf *= (1 + monthly_rate)^months_since_sale`, capped at ±15% total. Derive `monthly_rate` per (state, county) from a repeat-sales slope on the recorded-comp price series we already pull (regress `log(price)` on `sale_date`), fall back to a state constant, then FHFA regional. Store `time_adj_pct` per comp in the note.
2. **Explicit outlier trim before median.** On the `ppsfs` series in `calc.py`, drop values outside the **IQR fence** (or MAD band when n<8, where IQR is unstable). Log `n_trimmed`.
3. **Distance + similarity weighting.** Replace the plain median with a **weighted median** using a Gaussian kernel: `w = exp(−0.5·[(dist_mi/bw_d)² + (Δsqft%/0.20)² + (Δage/15)²])`, `bw_d` = adaptive (the k-th nearest distance). Beds mismatch already excluded upstream.
4. **Dispersion-driven confidence.** Compute **COD** on the screened, time-adjusted `$/sqft` set: `COD = 100 · mean(|ppsf−median|)/median`. Confidence = HIGH if **≥5 comps AND COD ≤ 10 AND tight screen held**; MEDIUM if COD ≤ 15 or a relaxation gate fired; LOW otherwise. This replaces the current pure count threshold (`_MIN_COMPS_HIGH = 5`).
5. **Log the relaxation ladder.** `enrichment_comps.py` already tracks `match_quality` ("zip+kind+geo" etc.); pass a `relaxed_gate` enum into `calc.py` and cap confidence at MEDIUM whenever radius/window/band was widened, matching the "explanation required" appraisal rule.
6. **Keep the distressed/retail split.** ARV stays on arms-length retail comps (already the intent of Tier-0's `price > $10k` and the zip retail pool). Do **not** fold REO/short comps into ARV; if we later capture a distressed-comp pool, it feeds the as-is number only.

### Free data/params it needs

- **Time trend:** derived internally from the **recorded-comp price+date series we already query** (per-county GIS), a regressed monthly slope. External free fallbacks: **FHFA HPI** (metro/state, quarterly, free CSV) and **Freddie Mac FMHPI** (free monthly, MSA/state). No new scraping.
- **Comp attributes:** already in the pool (sqft, beds, year_built, style, lat/lng, sale_date, price) from `enrichment_comps` (scraped) + county GIS (`enrichment_recorded_comps`).
- **Params (constants):** `TIME_ADJ_CAP=0.15`, `IQR_K=1.5`, `MAD_K=2.5`, kernel bandwidth from k-th nearest, `COD_HIGH=10`, `COD_MED=15`, existing `SQFT_BAND_PCT=0.20`, `±15 yr`, `COMP_RADIUS_MILES=10.0`, `_MIN_COMPS_HIGH=5`. All free/computed; no API costs.

### Accuracy impact vs our current approach

- **Time adjustment** is the highest-yield fix: in a market moving 6–12%/yr, unadjusted 6-month-old comps carry a **1.5–6% directional bias** in ARV — exactly the band that flips a `max_bid_70` from profitable to underwater. This alone should move backtested median error toward the AVM **3–5% target**.
- **IQR/MAD trimming + weighted median** typically cuts comp-set variance and pushes **COD down 2–4 points**, tightening the p25–p75 band the engine already reports.
- **Dispersion-based confidence** stops the current failure mode where 5 *scattered* comps read HIGH; a HIGH tier will now mean COD ≤ 10, which is genuinely appraisal-grade uniformity and makes `arv_confidence` trustworthy for downstream bid sizing.
- Net: each ARV becomes defensible as "median of k time-adjusted, IQR-trimmed, distance-weighted arms-length comps, COD = X" — the same sentence an AVM validation report uses.

### Build (specific function/change + effort)

- **`enrichment_recorded_comps.py`** (~40 lines): add `_county_monthly_appreciation(cfg, http)` — fit `log(price)~sale_date` OLS slope on the already-fetched sales, cache per (state, county); expose `raw["comp_time_trend"]`. **1–2 hr.**
- **`valuation/calc.py`** (`_arv_signals`, ~50 lines): (a) new `_time_adjust(ppsf, months, rate, cap=0.15)`; apply to each comp before building the `ppsfs` series in both Tier-0 and Tier-1; (b) new `_trim_iqr(vals)` / `_mad_band(vals)` and call before `median`; (c) `_weighted_median(vals, weights)` with the Gaussian kernel; (d) new `_cod(vals, med)` and rewrite the confidence branch to use COD + `relaxed_gate` instead of count-only. **3–4 hr.**
- **`enrichment_comps.py`** (~10 lines): surface the `relaxed_gate`/`match_quality` already computed into `raw["comp_match_quality"]` so `calc.py` can cap confidence. **30 min.**
- **`scripts/backtest_arv.py`**: add COD + median-|error| reporting and an A/B toggle (`--time-adjust/--no-time-adjust`, `--trim/--no-trim`) to quantify each lever against sold prices before shipping. **1–2 hr.**
- **Total ≈ 1 day.** All changes are pure functions on data already in `raw[...]`; no new sources, no API cost. Land path (`_land_arv`, $/acre) inherits the same trim + time-adjust helpers.

**Sources:** [Fannie Mae B4-1.3-08 Comparable Sales](https://selling-guide.fanniemae.com/sel/b4-1.3-08/comparable-sales) · [IAAO Standard on AVMs](https://www.iaao.org/wp-content/uploads/Standard_on_Automated_Valuation_Models.pdf) · [IAAO Standard on Ratio Studies (COD/PRD/PRB)](https://www.iaao.org/wp-content/uploads/Standard_on_Ratio_Studies.pdf) · [JVM Lending — comps within 20% of size](https://www.jvmlending.com/blog/comps-must-be-within-20-of-size-of-subject-comp-criteria/) · [FHFA House Price Index (repeat-sales time trend)](https://www.fhfa.gov/data/hpi) · [Freddie Mac FMHPI](https://www.freddiemac.com/research/indices/house-price-index) · [GTCWR — geographically/temporally/characteristically weighted regression](https://www.researchgate.net/publication/323428418) · [MyHouseDeals — pull comps & calculate ARV](https://www.myhousedeals.com/blog/wholesaling/pull-comps-calculate-arv-investment-property)


## Rehab Estimation Rubric

### The professional method (how flippers/GCs/appraisers actually do it — concrete mechanics)

Pros do not estimate rehab as a single per-sqft number. They use a **hybrid model**: a per-sqft baseline for the "spread-everywhere" cosmetic/finish work, **plus discrete line-item add-ons for the big-ticket systems** (which are per-unit or per-component, not per-sqft), **times a regional cost factor**, **plus a scope-scaled contingency**. This is the structure in J. Scott's *The Book on Estimating Rehab Costs* (BiggerPockets, the de-facto flipper standard) and it mirrors how RSMeans assembles a cost estimate (unit costs × quantities × a location factor).

**1. Condition taxonomy → per-sqft finish bands (2026 national $, stick-built SFR).** The consensus 4–5 tier ladder across BiggerPockets, RealEstateSkills, FlipperForce and REIkit:

| Tier | Scope | 2026 $/sqft (national) |
|---|---|---|
| Cosmetic / turnkey | Paint, fixtures, deep clean, maybe carpet; no walls opened | $10–25 |
| Light | + flooring throughout, counters, light bath refresh | $25–40 |
| Moderate | + kitchen & baths, windows, one major system serviced/replaced | $45–75 |
| Heavy | + roof, full HVAC, partial electrical/plumbing, minor structural | $75–100 |
| Full gut | To the studs: new electrical, plumbing, HVAC, drywall, roof, kitchen, baths | $90–150+ |

The per-sqft number is understood to **already include** the systems that *typically* come with that tier (e.g. a gut includes a new roof and HVAC). You only add a big-ticket line item when a system's need deviates from what the tier assumes (e.g. a "light" cosmetic house that nonetheless needs a $12k roof).

**2. Big-ticket systems are estimated as discrete units, not $/sqft**, because their cost is driven by count/age/severity, not floor area. 2026 national line items (median → typical range):

| System | Typical 2026 cost | Trigger signal |
|---|---|---|
| Roof (asphalt, ~1,500–2,000 sqft) | $9,000–12,000 (range $7.5k–18k) | age ≥ 20 yr, "roof" flag |
| HVAC full replace | $8,000–14,000 (range $5k–20k) | age ≥ 15 yr, no central air |
| Electrical rewire / panel | $8,500 (rewire $10k–30k; panel-only $2k–4k) | year built ≤ 1970, "knob-and-tube," "no power" |
| Plumbing repipe | $4,000–15,000 | galvanized/polybutylene era pre-1980, "no water" |
| Foundation | $5,200 avg ($2.2k routine → $20k–80k structural) | "foundation/structural" flag |
| Water heater | $1,600–1,850 | age ≥ 12 yr |
| Windows (whole house) | ~$1,000/window × count; ~$8k–15k typical | single-pane, pre-1990 |
| Kitchen (mid-range flip) | $15,000–30,000 | dated / gut |
| Bath (mid-range, each) | $8,000–16,000 | dated / gut |

The "**rule of thumb**" pros use to sanity-check: age-based life-expectancy. A roof lives ~20–25 yr, HVAC ~15 yr, water heater ~10–12 yr — so if `year_built + component_life < current_year` and nothing says it was replaced, budget the replacement. This is exactly the life-expectancy inspection logic J. Scott's 25-component checklist encodes.

**3. Regional cost factor (RSMeans City Cost Index).** The national numbers above are pinned to a 30-city average = 100. RSMeans publishes a composite **total location factor** per metro. Verified from the RSMeans City Cost Index (Q-update location factor table), the **total (MAT+INST) index** for the engine's footprint:

| Metro | Material idx | Install/labor idx | **Total idx** | Factor vs national |
|---|---|---|---|---|
| Charlotte NC | 98.4 | 72.1 | **87.0** | 0.87 |
| Spartanburg SC | 97.7 | 70.2 | **85.8** | 0.86 |
| Greenville SC | 97.5 | 70.0 | **85.6** | 0.86 |
| Columbia SC | 98.8 | 67.6 | **85.3** | 0.85 |
| Raleigh NC | 99.0 | 65.3 | **84.4** | 0.84 |
| Asheville NC | 97.0 | 64.6 | **83.0** | 0.83 |

The key mechanic: **materials cost ~national (97–99) but labor runs 30–36% below national (64–72)**. Since rehab labor is 40–60% of total rehab cost (per RealEstateSkills/DealRun), a blended Carolina rehab runs **~0.83–0.87 of the national figure**. The engine's current tables are Carolina-tuned but that calibration is undocumented and unpinned to a source; RSMeans makes it defensible and lets it flex per-county.

**4. Contingency scales with scope** (the more walls you open, the more surprises). J. Scott / RealEstateSkills: **cosmetic 10% → moderate 15% → full gut 20–25%.** A flat 12.5% (current) under-pads gut jobs, where the actual variance is largest.

### How to encode it in our engine (algorithm/rules, keyed on data we have)

Replace the single `tier × $/sqft × contingency` with a **three-component sum**:

```
rehab_expected = ( base_psf[tier] × living_sqft              # cosmetic/finish spread
                   + Σ system_addon[s]  for s in triggered_systems )  # big-ticket
                 × region_factor(county)                     # RSMeans total idx / 100
rehab_with_contingency = rehab_expected × (1 + contingency[tier])
```

**Rules, keyed on fields the engine already has (`year_built`, `condition_tier`, `flags`, `living_sqft`, `property_kind`, county):**

1. **Tier** — keep `_condition_to_tier()` (Vision `condition_tier` → flags → year_built). It already produces the 5-tier ladder; just widen the year-built fallback into the roof/HVAC trigger logic below.
2. **Systems add-on layer** — compute *incremental* system costs only when the tier's base $/sqft does **not** already assume them:
   - roof: add if `age ≥ 20` AND tier ∈ {cosmetic, light} (heavy/gut already include it), or `"roof"` in flags without `"new roof"`.
   - HVAC: add if `age ≥ 15` AND tier ∈ {cosmetic, light}, or `"no power/hvac"` flag.
   - electrical: add if `year_built ≤ 1970` AND tier ∈ {cosmetic, light, moderate}.
   - plumbing: add if `year_built ≤ 1980` AND tier ∈ {cosmetic, light, moderate}, or `"no water"`.
   - foundation: **always** add on `"foundation/structural/termite"` flag regardless of tier (it's never in the base), using a wide $5k→$25k low/expected/high because it's the single biggest variance driver.
3. **Region factor** — `region_factor(county)` from a lookup table of RSMeans total-idx/100 (Greenville 0.86, Spartanburg 0.86, Columbia 0.85, Charlotte 0.87, Asheville 0.83, default Carolina 0.85). Re-base the national tables to national numbers so the factor does real work; today's tables silently bake in ~0.85 already, so this is a refactor, not a re-price.
4. **Contingency by tier** — `{cosmetic:0.10, light:0.10, moderate:0.15, heavy:0.20, gut:0.25}` replacing the flat 0.125.
5. **Range** — `rehab_low/high` = same computation with the low/high column of each band **and** low/high of each triggered system, so the range widens correctly when a foundation flag is present (this is what makes the number "appraisal-defensible": the interval reflects real scope uncertainty, not a fixed ±).
6. **Mobile homes** — keep the separate `MOBILE_REHAB_TIERS`; skip the roof/electrical/plumbing per-unit add-ons (manufactured systems are packaged/cheaper) and cap region factor effect.

### Free data/params it needs

- **RSMeans total location factors** — free from the RSMeans City Cost Index quarterly change-notice PDFs (already downloaded and parsed in this session: Greenville/Spartanburg/Columbia/Charlotte/Asheville/Raleigh values above). Hard-code a per-county dict; refresh annually from the free PDF. No paid RSMeans subscription needed for the composite factor.
- **Line-item 2026 costs** — free national medians from Angi/HomeGuide/NerdWallet/Fixr (all captured above). Hard-code as constants; refresh yearly.
- **Component life-expectancy constants** — free/standard (roof 20–25 yr, HVAC 15 yr, WH 12 yr, galvanized-plumbing pre-1980, knob-and-tube pre-1950, aluminum wiring 1965–73).
- **Engine-side (already present):** `year_built`, `living_sqft`, `condition_tier` (Vision), `flags`, county, `property_kind`. Nothing new to scrape.

### Accuracy impact vs current approach

- **Current:** one $/sqft tier × sqft × flat 12.5%. It systematically **mis-prices two situations**: (a) a mostly-cosmetic house that needs one $10k system (under-estimates — the cosmetic $/sqft band never carries a roof), and (b) a gut with a foundation problem (under-pads — 12.5% vs the ~25% pros use). Backtest memory already flagged the calc as "noisy"; the largest residuals in flip rehab estimation are precisely the big-ticket systems, which a pure $/sqft model cannot see.
- **Expected impact:** J. Scott's line-item + contingency method is the documented path from "ballpark" (±30–50%, typical for a raw $/sqft guess) to "budget-grade" (±10–15%, the walkthrough-with-scope standard). The system add-on layer directly attacks the fat right tail (foundation/roof/HVAC surprises) that drives underwriting losses. The RSMeans factor removes an undocumented ~0.85 magic number and makes each county's number **individually citable** to a published index — the single biggest "defensibility" win, since an appraiser/AVM reviewer can trace every number to Angi (line items), BiggerPockets/J. Scott (tiers + contingency), and RSMeans (regional factor).
- **Net:** tighter central estimate on the common cosmetic/light cases, materially higher and better-padded estimates on the heavy/gut/foundation cases, and a range that actually widens with scope risk instead of a fixed ±.

### Build (specific function/change + effort)

In `valuation/calc.py`:

1. **New constants** (~30 lines): `SYSTEM_ADDONS = {"roof":(7500,9500,18000), "hvac":(5000,9000,20000), "electrical":(4000,8500,30000), "plumbing":(4000,7500,15000), "foundation":(5000,12000,80000), "water_heater":(1200,1600,3900), "windows_full":(6000,10000,15000)}`; `CONTINGENCY_BY_TIER = {...}`; `REGION_FACTOR = {"Greenville":0.86, "Spartanburg":0.86, "Columbia":0.85, "Charlotte":0.87, "Asheville":0.83, ...}` with `DEFAULT_REGION_FACTOR = 0.85`. Re-base `REHAB_TIERS` to the national bands in the table above (so factor isn't double-counted).
2. **New helper** `_triggered_systems(li, tier) -> list[tuple[str, low, exp, high]]` (~35 lines): applies the age/flag/year-built rules above; returns only *incremental* systems for the tier. Reuses `li.year_built`, `li.raw["flags"]`, `li.raw["vision"]`.
3. **New helper** `_region_factor(li) -> float` (~8 lines): county → `REGION_FACTOR`, else default.
4. **Rewrite the rehab block** in the main `compute()` path (~20 lines changed): `base = REHAB_TIERS[tier] × sqft`; add system tuples; multiply by region factor; apply tier contingency; set `rehab_low/expected/high`, `rehab_with_contingency`, and append a `notes` line itemizing which systems were added and the RSMeans factor used (for the audit trail).
5. **Backtest** in `scripts/backtest_arv.py`: re-run against sold-comp residuals; confirm the system-add-on layer reduces error on the flagged/older-year_built subset without inflating the cosmetic subset.

**Effort:** ~1–1.5 hrs (data/constants already gathered here). Isolated to `calc.py` + one backtest run; no scraper, schema, or enrichment changes. Must route board writes through `web_artifact.load_board()` per the board-writer rule when recomputing.

**Sources:** [RealEstateSkills 2026 rehab guide](https://www.realestateskills.com/blog/estimating-rehab-costs), [BiggerPockets — How to Estimate Rehab Costs](https://www.biggerpockets.com/blog/how-to-estimate-rehab-costs), [J. Scott, *The Book on Estimating Rehab Costs* (25-component method)](https://store.biggerpockets.com/products/the-book-on-estimating-rehab-costs), [DealRun rehab $/sqft by city 2026](https://dealrun.ai/blog/how-much-rehab-cost-per-square-foot), [RSMeans City Cost Index](https://www.rsmeans.com/rsmeans-city-cost-index) (location factors parsed from the [RSMeans CCI location-factor PDF](https://www.rsmeans.com/media/wysiwyg/quarterly_updates/2021-CCI-LocationFactors-V2.pdf)), [Angi roof](https://www.angi.com/articles/how-much-does-it-cost-rewire-house.htm) / [HomeGuide HVAC & water heater](https://homeguide.com/costs/water-heater-installation-cost) / [Angi foundation](https://www.angi.com/articles/how-much-does-foundation-repair-cost.htm) line-item costs.


## AVM Confidence / FSD Scoring

### The professional method (how appraisers/AVMs/pros actually do it — concrete mechanics)

Institutional AVMs do not report a categorical label; they report a **Forecast Standard Deviation (FSD)** and derive a numeric confidence score from it. The mechanics, standardized across the industry:

- **FSD definition (Freddie Mac / Doug Gordon, *Metrics Matter*).** FSD is the AVM value's *expected proportional standard deviation around the actual subsequent sale price* for that specific property. It is a per-property forecast, not a model-fit statistic. An FSD of 0.10 means ~68% of true sale prices fall within ±10% of the estimate (1σ), ~80% within ±12.8% (1.28σ), ~95% within ±20% (2σ). This is the load-bearing fact: **FSD is literally the σ of a normal error distribution you can build a probable-value range from.**
- **FSD → confidence bands (Freddie Mac Home Value Explorer, the canonical mapping).** HVE ties its confidence score directly to FSD: **FSD ≤ 13% = HIGH, 13%–20% = MEDIUM, > 20% = LOW.** Gordon explicitly warns against AVMs that base confidence on "number of local properties used" or "neighborhood range of values" *without* mapping to FSD — that is exactly the failure mode of our current 3-tier heuristic.
- **Confidence score = 1 − FSD (Clear Capital, Veros).** ClearAVM posts Confidence = 1 − FSD (FSD 0.07 → 93 confidence). Veros VCS runs 75–100 and correlates monotonically to **P10** (share of estimates within ±10% of truth). The scale differs by vendor, which is why MISMO standardized it.
- **MISMO Common Confidence Score (CCS), launched Sept 2025 — the current standard.** A vendor-agnostic **0–100** score calibrated to **P10** (probability the estimate is within ±10% of market value), deliberately avoiding "untenable" distributional assumptions. Benchmarks: **CCS 60+ = strong, 60–80 = typical, 95+ = rarely achievable.** This is the target semantics for our new score: *a number that estimates our own P10.*
- **PPE / hit-rate vs accuracy tradeoff (Clear Capital glossary, academic exposition).** Two orthogonal axes: **accuracy** = MdAPE (median abs % error — hides tails) and MAPE / PPE10 / PPE20 (share within ±10/±20% — captures tails); **hit rate / coverage** = share of subjects the AVM will *score at all*. Good AVMs *decline to score* low-confidence subjects ("AVMs do not, and should not, produce results when they don't have strong confidence"). Raising the confidence floor trades coverage for accuracy — precisely the lever `grading.py` should pull.
- **Cascade / ensemble (why lenders run several).** A **waterfall**: run AVM A, and if its FSD exceeds a threshold (e.g. **reject FSD > 20–25%**), fall through to AVM B, then C, taking the first that clears. Each rung has a *different independent method*, so a subject that one method values poorly (thin comps) may be well-covered by another (assessor model, HPI rescale). The engine already *has* a cascade (recorded comps → scraped comps → Zestimate → FHFA → tax → bid); today it only labels the winning rung, it doesn't score the rung's FSD or let a high-FSD rung fall through.
- **When an AVM must be flagged unreliable.** Low comp density (n<3–5), high dispersion (comps disagree — a high coefficient of variation of $/sqft, CV = σ/μ), unique/atypical property (subject $/sqft or size far outside the comp cloud), stale data, and estimate far from the independent anchor (assessor). These are the exact inputs to FSD; a spiking CV directly inflates the standard error of the median $/sqft.

### How to encode it in our engine (the algorithm/rules, keyed on the data we have)

Replace the categorical `arv_confidence` with a **synthetic per-listing FSD** built from the comp statistics already computed, then map FSD → a 0–100 `arv_confidence` and back-derive the HIGH/MED/LOW label for backward compatibility. The design principle from Gordon: build confidence *from FSD*, not from ad-hoc factors.

**Step 1 — Synthetic FSD from an error budget (variances add).** Model total forecast variance as the sum of independent error sources, each keyed on a field we already have in `raw`/`Listing`:

```
fsd² = base² + disp² + count² + geo² + sqft² + anchor² + method²
FSD  = sqrt(min(fsd², 0.60²))          # cap at 60%
```

Component definitions (all data we already carry in `_arv_signals`):

| Component | Source field | Value |
|---|---|---|
| `base` | method floor (irreducible market noise) | recorded comps 0.08; scraped comps 0.10; Zestimate 0.13; FHFA 0.18; tax×1.25 0.16; bid×2.4 0.28 |
| `disp` | the adjusted-$/sqft series `ppsfs` (already sorted in Tier 1) | **CV-based**: `disp = clamp(0.5 × (p75_ppsf − p25_ppsf)/median_ppsf, 0, 0.30)`. The IQR/median of $/sqft *is* the empirical dispersion — this is the single biggest driver. |
| `count` | `len(ppsfs)` / `rec['count']` | `0.15/sqrt(n)` (n≥1). n=1→0.15, n=3→0.087, n=6→0.061, n=10→0.047. Diminishing returns, standard-error shape. |
| `geo` | `comps[0]['geo_anchored']` | 0.0 if geo-anchored (zip/radius), 0.07 if county-wide |
| `sqft` | `living_sqft_estimated` + plausibility | 0.0 if true GLA; 0.06 if footprint-estimated; (implausible sqft already routes to a non-sqft rung) |
| `anchor` | `arv_vs_assessed` (already computed) | 0.0 if 0.8–1.6× assessor; 0.05 if 0.6–0.8 or 1.6–2.5×; 0.12 if <0.6 or >2.5× (comps likely wrong submarket) |
| `method` | floor/proxy flags | +0.10 if ARV was floored to county value or price-anchored (a non-clean comp read); +0.15 if proxy rung (bid/tax) |

**Step 2 — FSD → 0–100 confidence (MISMO/ClearAVM semantics).** Use `confidence = round(100 × (1 − FSD))`, clamped to [0,100]. This gives a P10-interpretable score: FSD 0.08→92, 0.13→87, 0.20→80, 0.28→72, 0.40→60.

**Step 3 — Derive the legacy label from Freddie HVE bands** (so nothing downstream breaks):

```
HIGH   if FSD ≤ 0.13     (confidence ≥ 87)
MEDIUM if 0.13 < FSD ≤ 0.20  (80–86)
LOW    if FSD > 0.20     (< 80)
```

**Step 4 — Build the probable-value range from FSD, not a flat ±15%.** Replace the hard-coded `expected*0.85 / *1.15` and `*0.90/*1.10` bands with `arv_low = expected×(1−FSD)`, `arv_high = expected×(1+FSD)` (the true 68% interval). Optionally add an 80% interval (`±1.28×FSD`) for the dashboard. This makes the range *self-consistent with the confidence number*.

**Step 5 — Cascade gate (coverage/accuracy lever).** In the `_arv_signals` waterfall, after computing a rung's FSD, if `FSD > 0.25` **and a lower rung with a materially lower FSD exists**, fall through instead of returning. In `grading.py`, expose a single tunable **confidence floor** (e.g. suppress/soft-flag leads with `arv_confidence < 72`, i.e. FSD > 0.28) — that one knob trades board coverage for board accuracy, which is the professional hit-rate control.

**Step 6 — Feed the confidence score into `max_bid_70` as a margin-of-safety, not just a display.** Pros bid more conservatively when the value is uncertain. Widen the discount as FSD rises: `bid_factor = 0.75 − k×max(0, FSD − 0.10)` (e.g. k=0.5 → FSD 0.20 knocks 5 pts off the 75%). This makes the bid itself risk-adjusted, mirroring how a cascade lender lowers LTV when confidence drops.

### Free data/params it needs

Everything is already computed or in-hand — **no new data source required**:
- `ppsfs` adjusted-$/sqft series and `p25_ppsf`/`p75_ppsf` (recorded comps sidecar) — dispersion. Zero new cost.
- comp `count`, `geo_anchored`, `radius_mi` — already in `raw['comps']` / `raw['recorded_comps']`.
- `living_sqft_estimated`, plausibility band — already in `Listing`.
- `arv_vs_assessed` — already computed in `compute()`.
- Method/rung identity and floor/anchor flags — already produced as notes/flags.
- **One-time calibration:** the component coefficients (base FSDs, the 0.15/√n, IQR multiplier) should be *fit* against `scripts/backtest_arv.py`'s recorded-sale ground truth so the reported FSD matches the realized error — this is exactly Gordon's mandated out-of-sample validation ("is 68% of sales within ±1 FSD?"). That harness already exists and already buckets by confidence, so calibration is free.

### Accuracy impact vs our current approach

- **Today:** `arv_confidence` is a 3-way label from an unvalidated additive heuristic (count<3, geo, 1.6× spread). It is *not* tied to realized error, cannot express "we're 85% sure," gives every HIGH the same trust regardless of a 1.61× vs 3× comp spread, and hard-codes a flat ±15% band unrelated to actual confidence. Gordon names this precise anti-pattern ("basing scores on… number of local properties… that does not correspond to expected performance").
- **New:** a continuous FSD calibrated so the reported ±FSD interval empirically covers ~68% of recorded sales — the same reliability contract lenders demand and validate. Expected gains: (1) the `backtest` `within20%` and P10 rates become *predictable per lead* instead of a coin-flip inside a label; (2) the confidence floor becomes a real accuracy/coverage dial (raising it should measurably lift the HIGH bucket's within-20% rate, the whole point of the hit-rate tradeoff); (3) risk-adjusted `max_bid_70` should cut the sub-55%-of-resale auction-losing tail *further on low-confidence leads specifically* rather than uniformly. Benchmarks to target from the literature: **HIGH = FSD ≤ 13% (≈ CCS 87+), the Freddie HVE HIGH bar; a lead-grade floor around FSD 20–25% mirrors standard cascade rejection.** Since ARV feeds `max_bid_70`, `estimated_profit`, `roi_pct`, and `deal_status`, tightening confidence propagates to every downstream verdict.

### Build (specific function/change + effort)

1. **New `valuation/fsd.py`** with `fsd_from_comps(rung, ppsfs, p25, p75, median_ppsf, n, geo_anchored, sqft_est, arv_vs_assessed, floored, proxy) -> float` implementing the Step-1 error budget, and `fsd_to_confidence(fsd) -> int` / `fsd_to_label(fsd) -> str`. Pure functions, unit-testable. **~1 hr.**
2. **Refactor `_arv_signals` in `calc.py`** so each rung returns `(expected, fsd, notes)` instead of a categorical conf; compute low/high as `expected×(1∓fsd)` (Step 4); add the Step-5 fall-through gate. Set `Calc.arv_fsd` (new field) + keep `arv_confidence` as the 0–100 int and add `arv_confidence_label` for the legacy HIGH/MED/LOW. **~2–3 hrs** (touches the 6 existing rungs + the floor/anchor MEDIUM-downgrade blocks in `compute()`, which become `fsd += penalty`).
3. **Risk-adjusted bid** (Step 6): one line in the `max_bid_70` block scaling the 0.75 factor by FSD. Gate behind a flag so the backtest can A/B it. **~30 min.**
4. **Calibrate** against `scripts/backtest_arv.py`: add a mode that reports, per FSD decile, the realized `within-FSD` coverage (should ≈68%) and P10; tune the seven coefficients until coverage matches. **~2 hrs.**
5. **`grading.py`**: replace the label switch with a numeric `arv_confidence` threshold (single tunable floor). **~30 min.**

Total ~6–7 hrs. Backward-compatible via the retained label field; every change is validated by the existing recorded-sale harness (Gordon's out-of-sample test), so the reported confidence is defensible as *calibrated*, not asserted.

Sources: [Freddie Mac — *Metrics Matter* (Doug Gordon), HVE FSD bands](https://sf.freddiemac.com/docs/pdf/fact-sheets/dougwhitepaper_metricsmatter.pdf) · [Clear Capital — AVM Testing Glossary (FSD, P10, hit rate, MdAE/MAE)](https://www.clearcapital.com/blog-avm-testing-glossary/) · [Veros — Confidence Scores & AVM Accuracy](https://www.veros.com/building-trust-how-confidence-scores-enhance-avm-accuracy) · [Veros — MISMO Common Confidence Score (CCS)](https://www.veros.com/understanding-the-mismo-common-confidence-score-ccs-for-avms) · [MISMO — Confidence Score Standard launch (Sept 2025)](https://www.mismo.org/about-MISMO/news/2025/09/05/mismo-launches-confidence-score-standard-for-avms) · [AVMetrics — Forecasted Standard Deviation / cascade FSD>25% reject](https://www.avmetrics.net/tag/forecasted-standard-deviation/)


## Backtesting & Calibration Methodology

### The professional method (how appraisers/AVMs/pros actually do it — concrete mechanics)

Institutional AVM validators and mass-appraisal offices do not "eyeball" a model against a handful of sales. They run a **sales-ratio study**: a structured statistical comparison of model estimates against actual arms-length sale prices, summarized by a standardized battery of metrics that separately capture *accuracy* (how close), *reliability* (how often close), and *bias* (systematic tilt). The governing standards are the IAAO **Standard on Ratio Studies** and **Standard on AVMs**, plus the lender-side testing playbooks (Clear Capital, Optival/Mercury, QuantPV).

**1. Ground truth = arms-length sales only, index-adjusted for time.** The benchmark is the actual sale price of an arms-length transaction. Non-market transfers (foreclosure, deed-in-lieu, intra-family, quitclaim, "love and affection" $1 deeds) are excluded because they are not market value. Because sales happen over a window, each sale is **time-adjusted** to the common appraisal/estimate date with a market index. The core statistic is the **sales ratio = AVM estimate ÷ sale price** for each property; the whole discipline is the study of the distribution of that ratio.

**2. The metric battery** (each has a role — accuracy, reliability, bias — and an institutional threshold):

| Metric | Formula | What it measures | Institutional benchmark |
|---|---|---|---|
| **MdAPE** (median abs % error) | median of \|est−sale\|÷sale | central accuracy, outlier-robust | **< 5%** (strong AVM); < 10% acceptable |
| **PPE10 / PE10** | share with \|error\| ≤ 10% | reliability / hit-in-band | **> 70%** |
| **PPE20** | share with \|error\| ≤ 20% | tail reliability | **> 85–90%** |
| **PE at 5/15/25%…** | share within each band | full error *distribution*, not one number | reported as a curve |
| **Median error / mean error (signed)** | median of (est−sale)/sale | **BIAS** direction & size | ≈ **0%** (±1–2%) |
| **FSD** (forecast standard deviation) | per-estimate σ of % error | *per-property* confidence | < 0.10 high-confidence; > 0.20 → escalate |
| **Hit rate** | share of subjects that get an estimate | coverage | **> 90%** (mature US AVM) |
| **Median ratio** | median(est÷sale) | level bias (IAAO) | **0.90–1.10** |
| **COD** (coefficient of dispersion) | 100 × avg abs dev of ratios from median ratio ÷ median ratio | horizontal uniformity | residential **< 15** (5–10 for homogeneous) |
| **PRD** (price-related differential) | mean ratio ÷ weighted-mean ratio | vertical equity (are cheap homes over-valued vs expensive?) | **0.98–1.03** |
| **PRB** (price-related bias) | regression coeff of %ratio on value | vertical equity (modern) | **−0.05 to +0.05** |

Key professional distinction the current harness misses: **accuracy (MdAPE), reliability (PPE), and bias (signed median error + PRD/PRB) are three separate axes.** A model can be accurate on average yet systematically over-value cheap houses (bad PRD) — which is exactly the failure mode of a `$/sqft × sqft` model, since $/sqft is nonlinear in size and price tier.

**3. Blind / hold-out testing (the anti-gaming rule).** The estimate must be produced **without the model having seen the target sale**. Assessors hold out a random sample of sales; lenders demand *retrospective blind tests* (as-of a date before the sale, with that sale withheld) and prefer **refinance-appraisal or contract-price benchmarks** precisely because the vendor cannot reverse-engineer them from public records. Testing a model against a sale it was allowed to use as a comp (or that it was floored/anchored to) is circular and inflates apparent accuracy — the current harness already intuits this with its "floored"/`arv==amount` exclusion, which is the right instinct but only a partial guard.

**4. Stratification is mandatory, not optional.** IAAO requires the ratio study be computed **within each stratum** — property type, price tier (deciles/quintiles), geography (county → market area → ZIP), condition, and vintage — because a blended national number hides compensating errors. A minimum of **~5–15 sales per stratum** is the practical floor for a stable median (below that, confidence intervals blow up and you report the CI, not a point estimate).

**5. Outlier handling is defined, not ad hoc.** Ratio studies **trim** extreme ratios before computing dispersion, by a stated rule: drop ratios outside **1.5× IQR** (Tukey fences) or beyond **±3 standard deviations / a fixed ratio band (e.g. 0.5–2.0)**, and document how many were trimmed. This prevents one rural mis-comp from dominating — the harness currently defends against this only by using the median, which protects the center statistic but still lets outliers pollute the "within20%" and max-bid fractions.

**6. Bias detection → correction (calibration).** When the signed median ratio drifts off 1.00, or PRD/PRB breaches range, the model is **recalibrated**: apply a multiplicative level adjustment per stratum (divide estimates by the stratum median ratio to re-center to 1.00), and if PRB is significant, fit a value-dependent correction. This is the loop that turns a backtest from a *report card* into a *feedback controller*. The prior calibration note in memory (the max-bid selling-fee double-charge fix, 0.70→0.75) is exactly this kind of correction — but it was found manually; the harness should surface it automatically.

**7. Forward vs. backward testing.** *Backward/retrospective* (what the harness does — compare to a past recorded sale HPI-adjusted forward) validates the level. *Forward* testing (freeze today's estimates, wait for the next N sales, compare) is the gold standard because it is immune to any leakage. Pros run both and track metric **stability over time** (a model whose MdAPE is stable across vintages is trustworthy; one that's only good on old sales is overfit to stale comps).

### How to encode it in our engine (the algorithm/rules, keyed on the data we have)

Restructure `backtest_arv.py` from a single-median printer into a **ratio-study calibration harness** over the same `docs/listings.json` rows:

1. **Compute the sales ratio per lead**: `ratio = arv_expected / adj_sale` (we already compute `arv_err`; ratio = `1 + arv_err`). Keep both, because the whole IAAO battery is defined on the ratio.

2. **Emit the full metric battery, not just median+within20**:
   - `MdAPE = median(|arv_err|)`, `MdE_signed = median(arv_err)` (bias), `Mean_signed` (bias, sensitive).
   - `PPE10, PPE15, PPE20, PE05, PE25` = share within each band → print the whole PE curve.
   - `median_ratio = median(ratio)`; **COD** = `100 * mean(|ratio − median_ratio|) / median_ratio`; **PRD** = `mean(ratio) / (Σ arv / Σ adj_sale)`; **PRB** = OLS slope of `(ratio − median_ratio)/median_ratio` on `0.5*ln(adj_sale)+0.5*ln(arv)`.
   - **FSD proxy** per confidence tier = std-dev of `arv_err` within that tier (this is what makes `arv_confidence` *quantitative* instead of a label).

3. **Trim before dispersion metrics**: drop ratios outside `[median − 1.5·IQR, median + 1.5·IQR]` (or a hard `0.5–2.0` band), count and report trimmed rows separately. Center statistics (median, MdAPE) use all rows; dispersion (COD, PRD, within%) uses the trimmed set — per IAAO.

4. **Stratify and gate on n**: report every metric **by confidence tier, by county, by price quartile of `adj_sale`, and by sale-year vintage**. Only print a stratum with `n ≥ 8`; otherwise roll it into "thin strata" and report a bootstrap 90% CI on the median instead of a point value.

5. **Bias → calibration output (the new payload)**: for each stratum, emit `suggested_level_factor = 1 / median_ratio`. If `|median_ratio − 1| > 0.03` or `PRD ∉ [0.98,1.03]` or `PRB ∉ [−0.05,0.05]`, flag `NEEDS_RECALIBRATION` and print the per-stratum multiplicative correction that `calc.py` should apply. This is the report-card → controller upgrade.

6. **Harden the anti-leakage guard**: current exclusion is `"floored" in notes or arv==amount`. Extend to also drop any lead whose `adj_sale` sale is the *same transaction* the comp set drew from, and any lead where `arv_confidence == LOW` proxy was itself derived from `last_sale` (mark these `circular` and exclude), so PPE10 isn't inflated by self-reference.

7. **Add a forward-test mode**: a `--freeze` flag that snapshots current `arv_expected` with a timestamp to a sidecar, so future sales can be scored against frozen estimates (true leakage-free forward validation) — the only fully honest accuracy number.

### Free data/params it needs

- **Already in `listings.json`** (zero new data): `arv_expected`, `arv_confidence`, `last_sale.{amount,date,basis}`, `max_bid_70`, `county`, `source`, `calc.notes`. The entire ratio battery, COD/PRD/PRB, trimming, and stratification run on fields we already persist.
- **Better time index (free)**: replace the 6-anchor Carolina HPI table with the **FHFA All-Transactions House Price Index at the county or CBSA level** (FHFA publishes free quarterly CSVs) or **FHFA state HPI**, joined by county → CBSA. This removes the "snap to nearest anchor" quantization that adds noise to `adj_sale` and therefore to every metric. Zillow ZHVI (free CSV, ZIP-level) is an even finer alternative.
- **Price-tier strata**: computed from `adj_sale` quartiles — no new data.
- **Bootstrap CI for thin strata**: numpy only, no data.
- **PRB regression**: `numpy.polyfit` / a 2-line OLS — no new dependency beyond numpy (add it; harness is currently pure-stdlib).

### Accuracy impact vs our current approach

The current harness reports exactly three things — overall median error, a coarse `within20%`, and a max-bid fraction — segmented only by confidence and county. It is a **level check on one axis (central accuracy)**. It is blind to the three failure modes that actually cost money in a $/sqft model:

- **Vertical bias (over-paying on cheap/small houses).** A $/sqft model is structurally biased across price tiers; without **PRD/PRB and price-quartile strata**, the harness cannot see it. This is the single highest-value addition — it's the difference between "median looks fine" and "we systematically over-bid the bottom quartile by 12%." Institutional standard: PRD 0.98–1.03; a $/sqft model routinely lands 1.05–1.10 unmeasured.
- **Dispersion / reliability.** `within20%` is one crude band. The **PE curve (5/10/15/20/25%) + COD** tells you whether "median +2%" hides a 22-COD spray of estimates (unusable) or a tight 9-COD cluster (institutional). Two models with identical medians can have wildly different COD — only the upgraded harness distinguishes them.
- **Per-estimate confidence made real.** Today `arv_confidence` (HIGH/MEDIUM/LOW) is an assertion. Attaching an **empirical FSD per tier** turns it into a validated probability ("HIGH tier: FSD 0.08 → 68% within ±8%"), which is what lets the pipeline *route* LOW-FSD leads to manual review and *trust* HIGH-FSD max-bids — the same escalation logic institutional AVMs use.
- **Outlier leakage into decision stats.** Untrimmed, the `within20%` and `max_bid_70/adj_sale` fractions are polluted by rural mis-comps; IAAO trimming + reporting trimmed count restores them.

Net: the model's *point estimate* may already be "unbiased-at-median" per the prior calibration note, but its **defensibility** jumps from "we checked the median" to "MdAPE 6.1%, PPE10 68%, median ratio 1.01, COD 11.4, PRD 1.02, PRB +0.01, hit rate 91%, trimmed 4/210 — all within IAAO residential tolerances except PPE10 which is 2pts light in Buncombe." That is an appraisal-grade validation statement, and it *automatically emits the per-stratum recalibration factors* instead of requiring a human to notice the 0.70→0.75 class of error.

### Build (specific function/change + effort)

Rewrite `scripts/backtest_arv.py` (keep it read-only on `listings.json`; add numpy):

1. **`ratio_stats(errs, ratios) -> dict`** — returns `{mdape, mde_signed, mean_signed, pe05, pe10, pe15, pe20, pe25, median_ratio, cod, prd, prb, fsd, n, n_trimmed}`. ~40 LOC. *(0.5 day)*
2. **`trim_iqr(ratios) -> (kept, dropped)`** — 1.5×IQR fence, returns counts. ~10 LOC. *(trivial)*
3. **`stratify(items) -> dict[stratum -> list]`** for confidence, county, `adj_sale`-quartile, and sale-vintage; `bootstrap_median_ci(vals)` for `n<8` strata. ~30 LOC. *(0.5 day)*
4. **`calibration_report(strata)`** — per stratum: `suggested_level_factor = 1/median_ratio`, plus `NEEDS_RECALIBRATION` flag when median_ratio, PRD, or PRB breach IAAO bands; print the correction table. ~25 LOC. *(0.5 day)*
5. **Swap the HPI table for FHFA county/CBSA HPI** — small loader `fhfa_factor(county, year)` reading a cached free CSV, fallback to current anchors when a county is missing. ~25 LOC + one-time CSV download. *(0.5 day)*
6. **`--freeze` forward-test mode** — snapshot `{lead_id, arv_expected, ts}` to `docs/arv_snapshots.jsonl`; a `--score-frozen` pass matches later recorded sales to frozen estimates for leakage-free forward MdAPE/PPE. ~30 LOC. *(0.5 day)*
7. **Harden circular-exclusion** in `collect()` — add `circular` tagging for LOW-proxy-from-last_sale rows. ~10 LOC. *(trivial)*

**Total ≈ 3 days.** Highest-ROI first two hours: add **PRD/PRB + price-quartile strata + COD** (items 1 and 3) — that alone exposes the $/sqft vertical bias the current harness structurally cannot see, and it needs zero new data. `calc.py` then consumes the emitted per-stratum `level_factor` to re-center estimates (the same lever as the 0.70→0.75 fix, now data-driven and continuous). Cross-check every `calc.py` change by rerunning this harness — and per the existing board-writer rule, any recompute must load via `web_artifact.load_board()` so the vision/comps/cama sidecar is preserved.

**Sources:**
- [An Exposition of AVM Performance Metrics — Journal of Property Tax Assessment & Administration (Tandfonline)](https://www.tandfonline.com/doi/full/10.1080/15214842.2020.1757352)
- [AVM Accuracy Explained: MdAPE, PPE10, FSD — QuantPV](https://quantpv.com/articles/ppe10-avm-accuracy-explained.html)
- [A Lender's Guide to the Top 3 AVM Testing Methods — Clear Capital](https://www.clearcapital.com/blog-avm-testing-guide/)
- [AVM Testing: A Short Glossary — Clear Capital](https://www.clearcapital.com/blog-avm-testing-glossary/)
- [IAAO Standard on Ratio Studies](https://www.iaao.org/wp-content/uploads/Standard_on_Ratio_Studies.pdf)
- [IAAO Standard on Automated Valuation Models](https://www.iaao.org/wp-content/uploads/Standard_on_Automated_Valuation_Models.pdf)
- [Uniformity Standards — COD/PRD/PRB (Martin County exhibit of IAAO Table 2-3)](http://www.pa.martin.fl.us/data_files/CEAA/Exhibits/Exhibit%201-3.5%20Uniformity%20Standards%20-%20COD%20-%20PRD%20-%20PRB.pdf)
- [The 70% Rule in House Flipping — RealEstateSkills](https://www.realestateskills.com/blog/what-is-70-rule-in-house-flipping)


## Investor Math: 70% Rule, MAO, and a Cost-Stack-Derived Max Bid

### The professional method (how appraisers/AVMs/pros actually do it — concrete mechanics)

**The 70% rule is a heuristic, not a valuation.** Its "30% haircut" is a shorthand that bundles *profit target + every transaction cost* into one number so an investor can price a deal on a phone call. `MAO = 0.70 × ARV − repairs`. The industry-stated decomposition of the 30% is roughly **~15% investor profit + ~15% all-in costs** (holding, both-side closing, selling commission, financing, buffer) ([Amerisave](https://www.amerisave.com/learn/the-rule-in-house-flipping-what-it-means-for-real-estate-investors-in), [Lima One](https://www.limaone.com/70-rule-real-estate/)). The reason pros treat it as a *filter, not a bid* is that the 15% cost slug is only accurate for a mid-ARV ($150k–$400k), 6-month-hold, ~6% commission deal. Outside that box it is wrong, and every serious source says to **adjust the multiplier** ([BiggerPockets: 70% too aggressive in high-ARV](https://www.biggerpockets.com/forums/67/topics/297181-is-the-70-rule-too-aggressive-in-high-arv-markets)):

| Condition | Multiplier pros use | Why |
|---|---|---|
| Hot market, DOM < 30d, fast turn | **0.75–0.80** | Low holding risk; 70% leaves money on the table |
| Standard | **0.70** | The canonical mid-case |
| Low ARV (< ~$150k) | **0.60–0.65** | Fixed $ costs (title ~$1,600, commission floor, insurance) are a *larger %* of a small deal |
| Slow/luxury, 9–12mo hold | **0.60–0.65** | Holding + carrying eats the margin |

(All four rows from [RealEstateSkills](https://www.realestateskills.com/blog/what-is-70-rule-in-house-flipping), [Amerisave](https://www.amerisave.com/learn/the-rule-in-house-flipping-what-it-means-for-real-estate-investors-in), [PropStream](https://www.propstream.com/news/what-is-the-70-rule-for-fix-and-flippers).)

**The defensible version pros use for real bids is bottom-up (MAO = ARV − ALL costs − profit).** The institutional / hard-money-underwriter form is:

```
MAO = ARV − Repairs(×contingency) − AcquisitionCosts − HoldingCosts − SellingCosts − FinancingCosts − TargetProfit − SeniorLiens
```

The full cost stack, with benchmarked free-computable values ([REIkit cost stack](https://www.reikit.com/house-flipping-guide/fix-and-flip-project-costs-purchase-sale-holding), [InvestorsEdge](https://www.theinvestorsedge.com/blog/the-pros-guide-how-to-calculate-cost-on-a-fix-flip)):

- **Acquisition/closing (buyer side):** title search + owner's + lender's title insurance + attorney + recording ≈ **1.5–3% of purchase price** ($1,600 title floor on a $100k home means small deals skew high). Auction buyers add a buyer's premium (**5–10%** at some venues).
- **Holding (per month × months-to-sell):** property **taxes ≈ 1%/yr of assessed** (~0.083%/mo), **insurance $100–300/mo** (builder's risk), **utilities $200–500/mo**, **HOA $100+/mo**. Months-to-sell is set from **market velocity** (months-of-inventory / DOM), *not* a flat 6 ([REIkit](https://www.reikit.com/house-flipping-guide/fix-and-flip-project-costs-purchase-sale-holding), [AHL: budget holding costs](https://ahlend.com/docs/how-to-budget-for-holding-costs-on-a-flip/)).
- **Financing (the big one, and the item the current engine most understates):** hard money = **7.5–18%/yr interest-only + 1–6 points** origination; LTV 70–80% of ARV ([REIkit](https://www.reikit.com/house-flipping-guide/fix-and-flip-project-costs-purchase-sale-holding), [OfferMarket HM guide](https://www.offermarket.us/blog/hard-money-fix-and-flip-loans)). Points hit the *loan* at close; interest accrues on drawn balance × months. This alone is 5–10% of profit.
- **Selling:** agent commission **5–7% (use 6%)** + **buyer concessions ~2% of ARV** + seller closing/title ≈ **1%** ⇒ **~8–9% of ARV** ([REIkit](https://www.reikit.com/house-flipping-guide/fix-and-flip-project-costs-purchase-sale-holding)).
- **Target profit:** flippers underwrite to **≥15% of ARV or ≥$25–30k**, whichever is greater on small deals.
- **Repairs:** always **× 1.10–1.15 contingency** for hidden conditions.

**Strategy changes the formula, not just the number:**

| Strategy | Max-bid form | Key difference |
|---|---|---|
| **Fix-and-flip** | `ARV − repairs − full cost stack − 15% profit` | Pays both selling *and* holding for the full flip |
| **Wholesale** | `MAO_flip − AssignmentFee` | Wholesaler bids *below* the flipper's MAO so the end-buyer still clears 70%. Fee rule-of-thumb: **up to ~50% of end-buyer projected profit**, floor $5–10k ([RealEstateSkills wholesale](https://www.realestateskills.com/blog/wholesale-formula)) |
| **BRRRR** | `0.75 × ARV − repairs` (capital-recovery ceiling) | Sized so the **75% refi pulls 100% of capital out**; *no selling cost* (holds it), so tolerates a higher buy than flip ([RealEstateSkills BRRRR](https://www.realestateskills.com/blog/brrrr)) |
| **Subject-to / gator** | `EquityToSeller + AssumedDebt`, funding cost = flat **$150–500 or ~$25/day** transactional | Buys the *equity*, takes title **subject to** existing mortgage; no new acquisition financing, so financing cost collapses to the gator/EMD fee ([RealEstateSkills gator](https://www.realestateskills.com/blog/gator-method), [Pinetree](https://pinetreefinancialpartners.com/the-gator-method/)) |

### How to encode it in our engine (the algorithm/rules, keyed on the data we have)

The engine *already* computes a bottom-up stack (`total_investment` = bid + closing + holding + selling) but keeps it **disconnected** from `max_bid_70`, which uses a hardcoded `0.75`. The fix is to **derive the multiplier from the stack** and expose per-strategy bids. Keyed on fields that already exist (`arv_expected`, `rehab_with_contingency`, `assessed`, `market_velocity.holding_months_est`, `senior_cost`, `li.opening_bid`, `raw.equity`):

**1. Replace the fixed 0.75 with a cost-stack-implied multiplier per lead.** Compute the fee slug as a % of ARV, then set the effective multiplier so it embeds the *real* costs for this specific property:

```
sell_pct    = 0.08                         # 6% comm + ~2% concessions/seller-close
close_pct   = 0.025                         # buyer-side title/attorney/recording
hold_$      = (assessed*0.01/12            # taxes
             + insurance_mo + utils_mo + hoa_mo) * holding_months   # from velocity
finance_$   = points_pct*loan + hm_rate/12*loan*holding_months      # hard-money
profit_$    = max(0.15*ARV, 25000)          # floor protects small deals
implied_mult = 1 − sell_pct − close_pct − (hold_$+finance_$+profit_$)/ARV
max_bid_flip = implied_mult*ARV − rehab_buy − senior_cost − surviving_payoff
```

This makes the multiplier **fall automatically** on low-ARV homes (fixed $ costs are a bigger % of ARV → implied_mult drops toward 0.60–0.65) and on slow-velocity leads (holding_months rises), and **rise** on fast, high-ARV leads — reproducing the professional adjustment table *from the property's own numbers* instead of a constant. Clamp `implied_mult` to **[0.55, 0.80]** as a guardrail.

**2. Emit per-strategy bids** (new `Calc` fields), so the board can route each lead to the strategy that maximizes the defensible bid:
- `max_bid_flip` — above.
- `max_bid_brrrr = 0.75*ARV − rehab_buy − senior_cost` (no selling cost; capital-recovery ceiling).
- `wholesale_mao = max_bid_flip − assignment_fee`, where `assignment_fee = clamp(0.40*est_profit_flip, 5000, 25000)` — already partially present (`wholesale_mao`, `wholesale_spread`); tie the fee to projected profit not a flat number.
- `max_bid_subto` (only when `raw.equity.payoff_estimate` is MEDIUM+): `equity_to_seller + assumed_debt`, financing cost = flat gator fee, no acquisition financing line.
- Report `recommended_strategy = argmax` and set `max_bid_70` = the flip bid (back-compat).

**3. Holding cost fix (biggest current error):** today `holding = bid × 0.005 × months` (≈6% APR on bid). Replace with the **itemized carry + hard-money** model above. On a leveraged flip the true carrying rate is ~10–12% on the loan, so the current 6%-on-bid line understates carry by roughly 2–3×.

### Free data/params it needs

All free / already-in-repo:
- `assessed` (county GIS — already used for tax proxy: **1%/yr**) → property tax carry.
- `market_velocity.holding_months_est` (already computed from months-of-inventory / DOM) → months and the velocity-driven multiplier tilt.
- **Hard-money constants** (published ranges, put in config): `HM_RATE = 0.11` (mid of 7.5–18%), `HM_POINTS = 0.03` (mid of 1–6), `HM_LTV = 0.75`.
- **Fixed-$ carry defaults by property_kind:** insurance $150/mo, utilities $250/mo, HOA from data or $0 — all published REIkit midpoints.
- `senior_cost`, `raw.equity.payoff_estimate`, `li.opening_bid` — already parsed.
- No paid data required; every parameter is a published industry benchmark or an existing field.

### Accuracy impact vs our current approach

- **Current:** single fixed `0.75×ARV − rehab`, then lien/payoff nets; separate `total_investment` stack that never feeds the bid; holding as flat 6%-of-bid × months. The 2026-06 fix already moved median bid/resale from **57%→69%** and cut auction-losing (<55%) rate **45%→32%** by dropping the double-charged fee and using 0.75 — but that hardcoded 0.75 is only correct for the mid-ARV/mid-velocity case.
- **Expected gain from the stack-derived multiplier:** it *tightens the tails* the fixed constant gets wrong. Low-ARV deals (where 0.75 currently over-bids because fixed $ costs aren't captured) drop into the 0.60–0.65 range that pros use — reducing over-bids that turn into money-pit losses. Slow-velocity rural leads (the exact case the backtest flags as heavy-tailed) get longer holds → lower bids → fewer negative-margin buys. Institutional AVM/underwriting practice is a full bottom-up stack; converging on it is what makes each `max_bid` **defensible line-by-line** ("here is the $X taxes, $Y hard-money interest, $Z commission") rather than "trust the 0.75."
- **Financing correction** is the single largest $ accuracy improvement: understating carry 2–3× on leveraged deals directly inflates `estimated_profit`; fixing it de-inflates ROI to a number an actual lender would underwrite.

### Build (specific function/change + effort)

**File:** `src/foreclosure_scraper/valuation/calc.py`.

1. **Add constants** (near lines 41–47): `HM_RATE=0.11`, `HM_POINTS=0.03`, `HM_LTV=0.75`, `INSURANCE_MO=150`, `UTILITIES_MO=250`, `PROFIT_PCT=0.15`, `PROFIT_FLOOR=25000`, `MULT_MIN=0.55`, `MULT_MAX=0.80`. *(~10 min)*
2. **New helper `_implied_multiplier(arv, assessed, holding_months, property_kind) -> float`** returning the clamped stack-derived multiplier. *(~30 min)*
3. **Rewrite the `max_bid_70` block** (lines ~641–652) to call `_implied_multiplier` instead of the literal `0.75`; keep the existing `senior_cost` / surviving-payoff subtraction unchanged. *(~20 min)*
4. **Add `Calc` fields + per-strategy compute** `max_bid_flip / max_bid_brrrr / max_bid_subto / recommended_strategy`, and tie `assignment_fee` to `clamp(0.40*estimated_profit, 5000, 25000)`. *(~45 min)*
5. **Fix holding in `total_investment`** (lines ~742–753): replace `bid*HOLDING_RATE_MONTH*months` with itemized carry + `HM_POINTS*loan + HM_RATE/12*loan*months` where `loan = HM_LTV*(bid+rehab)`. *(~30 min)*
6. **Re-run** `scripts/backtest_arv.py` and recompute the board via `web_artifact.load_board()` (per board-writer rule) to confirm median bid/resale and <55% rate hold or improve. *(~20 min)*

**Total effort: ~2.5–3 hours.** Low risk — every change either replaces a constant with a data-derived value or adds parallel fields; the existing lien/payoff/double-count guards are untouched.

Relevant files: `/Users/cashhigh/foreclosure-scraper/src/foreclosure_scraper/valuation/calc.py` (constants L41-47, ARV L258-541, rehab L558-620, max_bid L641-720, cost stack L742-758), `/Users/cashhigh/foreclosure-scraper/scripts/backtest_arv.py` (validation harness).


---

# Deep-Dive Round 11 — 18-County Foreclosure Process + Timing Playbook (2026-07-02)


## SC Judicial Foreclosure — Full Timeline (Master-in-Equity)

South Carolina is a **100% judicial** foreclosure state. Every mortgage foreclosure runs through the Court of Common Pleas and is referred to the county **Master-in-Equity** (MIE) — a full-time judge in the 18-county footprint's larger counties (Spartanburg, Anderson, Buncombe-equivalent volume counties) and a **special referee** in the smaller ones (Union, Oconee, Polk, Mitchell, McDowell, etc.). There is **no non-judicial "power of sale"** path and, critically, **no post-sale statutory right of redemption** — once the sale is confirmed (or the upset-bid period closes) the owner's interest is extinguished ("Hammer Rule"). This makes the *pre-sale* window the entire acquisition game.

### The process / timeline (numbered stages with statutory citations + typical days between stages)

1. **Lis pendens recorded at the county ROD** — *SC Code §15-11-10.* Must be filed **no more than 20 days before** the complaint and **no less than 20 days before** the foreclosure decree; service within **60 days** of filing or it's void. This is the **earliest public event** and typically posts at the ROD the same day as, or days before, the summons/complaint. *(→ ~0 days; lead-time to sale ≈ 150–270+ days)*
2. **Summons & Complaint filed** (Common Pleas) under SCRCP; the complaint must state whether a deficiency judgment is **sought or waived**. Served personally, or by publication if the owner can't be located. *(same day to ~5 days after lis pendens)*
3. **Answer / default window** — defendant has **30 days** to answer (SCRCP Rule 12). Most owner-occupant foreclosures go to **default**. *(+30 days)*
4. **Order of Reference to the Master-in-Equity** — compulsory in equity foreclosures per **Rule 71, SCRCP**. Case transfers to the MIE/special referee. *(+2–8 weeks after default, county-dependent)*
5. **Merits hearing** — notice to all parties **at least 3 days before** the hearing. In SC counties with active foreclosure-intervention programs the borrower may be routed to mandatory **loss-mitigation/mediation** first, adding 60–120 days. *(variable)*
6. **Judgment of Foreclosure + Order of Sale** — MIE fixes the debt, orders sale, and sets the **deficiency vs. no-deficiency** posture. *(entered at/after hearing)*
7. **Notice of sale advertised** — *SC Code §15-39-650:* published **once a week for three consecutive weeks** immediately before the sale day. *§15-39-660:* the ad names the property, time/place, owner, and plaintiff, posted at **three public places incl. the courthouse door** plus a gazette. *(sale set ≈ 3–5 weeks out)*
8. **The MIE sale** — held the **first Monday of the month** (rolls to Tuesday if a holiday) at the county courthouse/designated courtroom. Property is struck to the highest bidder; deposit required.
9. **Deficiency branch (upset-bid period)** — *SC Code §15-39-720:* if a deficiency is sought, **bidding stays open until the 30th day after the sale** (exclusive of sale day); on that 30th day the property is **re-offered** and any upset bidder can raise. *SC Code §15-39-760:* if the complaint states **no deficiency demanded and the right is expressly waived**, §§15-39-720–750 do **not** apply — bidding **closes on sale day** (owner still gets a **20-day** compliance/settlement window per the MIE primer). *(+30 days deficiency / +0 days no-deficiency)*
10. **Report of Sale & Confirmation** — MIE files the report; parties may **except within 10 days** (Rule 53(e)(2), SCRCP), then the sale is confirmed. *(+~10–30 days)*
11. **Master's Deed delivered & recorded** — after the winning bidder complies, the MIE executes a **Master's Deed** (quitclaim-quality — conveys only the title before the court), recorded at the ROD. Title vests; **no redemption**. *(deed within days of compliance)*

**Rule of thumb:** contested/default SC foreclosure runs **~150–270 days** from lis pendens to deed; add 30 days whenever deficiency is not waived.

### Where each stage is PUBLICLY visible (free surface + lead-time before sale)

| Stage | Free public surface | Lead-time before sale |
|---|---|---|
| **Lis pendens (Stage 1)** | **County ROD / Register of Deeds** index (recorded doc type "Lis Pendens" / "LP"). Earliest, cheapest, cleanest signal. | **~150–270+ days** — earliest possible |
| Summons/Complaint, default, reference (2–4) | **SC Judicial Dept Public Index** (publicindex.sccourts.org) — Court Agency = "Common Pleas," case type foreclosure; docket shows filing, service, default, order of reference | ~120–210 days (but ToS-no-scrape wall) |
| Judgment + Order of Sale (6) | Public Index docket entry; MIE case file | ~30–60 days |
| **Notice of sale (7)** | **Legal-notice section of the local newspaper** (3 consecutive weeks) + **courthouse-door posting** + the county **MIE "Sale Roster"/salesbook** posted online ~3 weeks out | **~15–21 days** |
| **Sale roster / salesbook (8)** | **County MIE web page** (e.g., Anderson & Spartanburg publish monthly "Sale List and Results" PDFs; smaller counties list on the MIE/Clerk page) + **SC Public Index → Court Agency = "Master in Equity" → roster** | Posted **~3 weeks** pre-sale; refreshed daily |
| **Upset-bid window (9)** | MIE **sale results** list (shows winning bid + whether bidding remains open 30 days) | Sale day → **+30 days** (a second, post-sale acquisition window) |
| Confirmation / Master's Deed (10–11) | ROD (Master's Deed recording) | Post-sale |

**Practical hierarchy for lead-timing:** ROD lis pendens (earliest + free + scrapable) → newspaper legal notices (mid) → MIE monthly sale roster (latest, ~3 weeks, but highest-intent). Foreclosure-firm sale calendars (e.g., Rogers Townsend, Scott & Corley, Finkel, Brock & Scott, Riley Pope & Laney) mirror the MIE roster and sometimes post earlier.

### How to WORK this stage (the acquisition move + best owner-motivation window)

- **At lis pendens (best window):** ~5–9 months of runway before the owner loses everything with **no redemption**. Owner still holds title, occupancy, and full equity. This is the **pre-foreclosure / short-sale / subject-to / equity-purchase** sweet spot — motivation is rising but panic/shame hasn't frozen them. **Highest EV per lead.** Direct-mail + door + phone; lead with "you still have options and equity."
- **After Order of Sale, during the 3-week advertisement:** owner now knows the exact sale date on the courthouse door and in the paper. Motivation peaks; runway is short. Move is a **fast cash close before the first Monday** or a same-day reinstatement help — you're racing the clock.
- **At the MIE sale:** buy at auction (deposit + comply). Requires cash and title-risk tolerance (Master's Deed = no warranties; junior liens may or may not be wiped — verify the lien stack and whether it's a 1st-mortgage foreclosure).
- **During the 30-day upset-bid period (deficiency cases only):** you can **upset the winning bid** by raising it and depositing per terms — a legitimate second bite when the third-party/plaintiff bid came in low relative to ARV. Watch **no-deficiency** cases: those close on sale day, so **no upset window** exists.
- **Because there's no post-sale redemption**, do **not** waste outreach on owners after confirmation/deed — the door is closed. All owner-facing outreach must land **before the sale**.

### Encode in the engine

- **`sc_foreclosure_stage`** enum on each SC lead: `lis_pendens` → `complaint_filed` → `default` → `order_of_reference` → `judgment_order_of_sale` → `notice_advertised` → `sale_scheduled` → `upset_bid_open` → `sold_confirmed` → `deed_recorded`. Populate from ROD (LP), Public Index docket, newspaper legal notices, and the MIE monthly roster PDFs.
- **`deficiency_waived` boolean** parsed from complaint / roster ("no deficiency demanded"). Drives the upset-bid logic: if `false`, set `upset_bid_deadline = sale_date + 30d` and keep the lead **HOT** for that window; if `true`, bidding closes sale day (no upset lane).
- **`sale_date` + `days_to_sale`** derived field. **Urgency multiplier**, applied to base score:
  - `lis_pendens` and >120 days out → **×1.4** (prime equity-purchase window, long runway, no redemption pressure yet) — this is the **peak-EV band**, not a low-priority early stage.
  - `notice_advertised` / `sale_scheduled` (≤21 days) → **×1.8** (max motivation, short fuse).
  - `upset_bid_open` (deficiency case, ≤30 days post-sale) → **×1.2** (auction-buyer lane, not owner-outreach).
- **Prune rules:** (1) **Hard-drop / archive** any SC lead at `sold_confirmed` or `deed_recorded` — **no post-sale redemption**, owner outreach is dead. (2) **Suppress owner-facing outreach** once `sale_date` has passed *and* deficiency was waived (no upset window, owner interest extinguished). (3) De-dupe lis-pendens against Public Index case number so ROD-first and docket-first ingests collapse to one lead.
- **Refresh cadence:** re-scrape each county **MIE sale roster monthly** (~3 weeks before first Monday) to advance `sale_scheduled` leads and capture new ones; poll ROD **weekly** for fresh lis pendens (the earliest, most valuable signal). The MIE "Results" PDFs also backfill `sold_confirmed` for pruning.

**Sources:**
- [SC Code §15-11-10 (lis pendens timing) — scstatehouse.gov](https://www.scstatehouse.gov/code/t15c011.php)
- [SC Code §§15-39-650, -660, -720, -760 (advertisement, upset bids, deficiency waiver) — scstatehouse.gov](https://www.scstatehouse.gov/code/t15c039.php)
- [A Primer for Mortgage Foreclosures in South Carolina (Judge Charles B. Simmons Jr.) — Charleston County MIE](https://www.charlestoncounty.gov/departments/master-in-equity/mortgage-forclosures-primer.php)
- [Primer for Mortgage Foreclosures — Pickens County MIE](https://www.co.pickens.sc.us/departments/master_in_equity/primer_for_mortgage_foreclosures.php)
- [SC Judicial Branch — Rule 71, SCRCP (reference to Master)](https://www.sccourts.org/resources/judicial-community/court-rules/civil/rule-71/)
- [Anderson County Master-in-Equity — monthly Sale Lists & Results](https://www.andersoncountysc.org/departments-a-z/master-in-equity/)
- [Spartanburg County — Foreclosure Sale / Master-In-Equity](https://www.spartanburgcounty.org/313/Foreclosure-Sale)
- [Nolo — South Carolina Foreclosure Laws (no post-sale redemption)](https://www.nolo.com/legal-encyclopedia/south-carolina-foreclosure-laws-and-procedures.html)
- [SC Code §15-39-720 (upset bids within thirty days) — Justia](https://law.justia.com/codes/south-carolina/title-15/chapter-39/section-15-39-720/)


## NC Power-of-Sale Foreclosure — Full Timeline (18-County Engine: Buncombe, Gaston, Henderson, Rutherford, Cleveland, Burke, Lincoln, McDowell, Polk, Transylvania, Mitchell + SC counties)

### The process / timeline (numbered stages with statutory citations + typical days between stages)

North Carolina is a **non-judicial power-of-sale** state. The whole action runs as a *special proceeding before the Clerk of Superior Court* (NCGS §45-21.16(g)) — not a lawsuit before a judge. There is **no post-sale statutory redemption** after a power-of-sale foreclosure; the only redemption is the debtor's right to pay in full *during* the upset-bid window, and once that window closes "the rights of the parties to the sale become fixed" (NCGS §45-21.29A). That single fact is what makes NC a fast, deadline-driven state to work.

1. **Default + demand/acceleration.** Borrower misses payments; servicer accelerates. No public filing. *Not visible.* (Typical: 90–120 days delinquent before anyone files.)

2. **Pre-foreclosure notice (home loans / primary residence only).** Servicer must mail the borrower a resource/itemization notice **at least 45 days before** filing the notice of hearing (NCGS §45-102, Article 11). Not recorded, but it is the statutory floor: **a notice of hearing on a primary residence cannot legally appear until ≥45 days after this mailing.** *Not publicly visible, but it fixes the minimum lead time.*

3. **Notice of Hearing filed with the Clerk (the earliest public trigger).** Trustee/substitute-trustee files a *notice of hearing* commencing the special proceeding (NCGS §45-21.16(a)). Must be **served ≥10 days before the hearing** by Rule-4 methods (certified/registered mail, personal service), OR **by sheriff posting on the property ≥20 days before the hearing** where publication would be authorized. **This filing is the single most valuable lead event** — it is the *earliest* public surface and sits ~4–8 weeks ahead of the sale.

4. **Clerk's foreclosure hearing.** Clerk hears evidence and must find six elements — (i) valid debt + holder, (ii) default, (iii) right to foreclose, (iv) proper notice, (v) pre-foreclosure/Article-11 compliance if a home loan, (vi) not barred by servicemember protection §45-21.12A — then authorizes the sale (NCGS §45-21.16(d)). Debtor need not appear to preserve the right to pay off. *Typical: hearing is ~15–30 days after the notice-of-hearing filing.*

5. **10-day appeal window.** The clerk's order is a judicial act appealable **within 10 days** to Superior/District Court, heard *de novo*; an appeal by an owner-occupant is stayed on posting a bond of **1% of the principal balance** (NCGS §45-21.16(d1)). Most are not appealed. *Adds ~10 days minimum before the trustee advertises.*

6. **Notice of Sale posted + published.** After authorization, the trustee: (a) **posts** the notice at the courthouse public-notice area **≥20 days before the sale**; (b) **publishes in a county legal newspaper once a week for ≥2 successive weeks**, with the first-to-last publication span **≥7 days** and the **last publication ≤10 days before the sale**; (c) **mails** the notice first-class **≥20 days before sale** to every party entitled to §45-21.16 notice and to any tenant/"occupant" (NCGS §45-21.17(1)–(4)). *This sets the sale date ~20–30 days out from posting.*

7. **The sale (auction at the courthouse).** Substitute trustee conducts a public auction (courthouse door/steps of the county where the land sits, NCGS §45-21.23). Highest bidder wins subject to upset. *Typical: total from notice-of-hearing filing to sale ≈ 45–90 days.*

8. **Preliminary Report of Sale filed.** Person who held the sale must **file the report with the Clerk within 5 days** of the sale (NCGS §45-21.26). **This filing starts the upset-bid clock.**

9. **10-day upset-bid window.** Any person may file an **upset bid** ≥ **5% over** the last bid, minimum **$750 increase**, with a 5%/$750 cash-or-certified deposit, by close of business on the **10th day** after the report (or last upset) is filed (NCGS §45-21.27(a)). **Each new upset bid restarts a fresh 10-day period** — there are no resales, only successive upset bids. If the 10th day is a weekend/holiday it rolls to the next business day. During this window the **borrower can still pay in full and redeem.**

10. **Rights become fixed → Trustee's Deed.** When 10 days pass with no upset bid, **no confirmation hearing is required** and "the rights of the parties to the sale become fixed" (NCGS §45-21.29A). Trustee executes and records the **trustee's deed** to the final high bidder; sale proceeds are disbursed. **No redemption exists after this point.**

11. **Possession / eviction.** Purchaser is entitled to possession as of deed delivery; a holdover owner/tenant is removed by eviction/writ of possession (NCGS §45-21.16(c)(8); §45-21.29 governs orders for possession). *Tenants get separate protections under the federal PTFA / NCGS §42-45.2.*

**Rule of thumb total:** ~45-day pre-notice (home loans) → notice-of-hearing → sale is commonly **60–120 days**; add **~10–30 days** of upset-bid churn before the deed. From *first public signal (notice of hearing) to auction* is typically **~4–8 weeks**.

### Where each stage is PUBLICLY visible (free surface + lead-time before sale)

| Stage | Free public surface | Lead time before sale |
|---|---|---|
| Pre-foreclosure §45-102 notice | **None** (private mailing) | n/a — but proves sale is ≥45 days out for primary residences |
| **Notice of Hearing (stage 3)** | **Clerk of Superior Court Special Proceedings index** (each county Clerk's office / eCourts). Filed as an "SP" special proceeding. **This is the earliest recordable signal.** Also surfaces on **substitute-trustee law-firm foreclosure calendars** (Hutchens, Brock & Scott, Shapiro, Rogers Townsend, etc.) which post upcoming NC sales by county | **~4–8 weeks** (longest lead) |
| Clerk hearing date | Clerk's foreclosure hearing calendar (posted at courthouse / county Clerk) | ~3–5 weeks |
| **Notice of Sale (stage 6)** | **Courthouse public-notice board** (posted ≥20 days out); **county legal newspaper legal-notices section** (published 2 weeks); **NCGS mandates newspaper publication** so aggregators like the county paper's public-notices site and **NC Press Assoc. ncnotices.com** carry it | **~20–30 days** |
| Substitute-trustee firm sale roster | Trustee/law-firm websites list address, sale date, opening bid, file # | ~20–30 days (late but structured + clean) |
| Report of sale + upset bids | **Clerk Special Proceedings file** (report within 5 days; each upset bid + notice of upset bid filed there) | Post-sale: the 10-day-restart window |
| Trustee's deed | **Register of Deeds** (recorded deed = sale is final) | Post-sale (too late to work) |

**Signal ranking for the engine:** the **Clerk's SP notice-of-hearing filing** is the golden earliest source (longest owner-motivation runway), and the **substitute-trustee firm calendars** are the cleanest structured mirror of it. The **newspaper/courthouse notice of sale** is later but confirms an imminent, hard sale date. The recorded trustee's deed is a trailing indicator only useful for post-sale REO/skip lists.

### How to WORK this stage (the acquisition move + best owner-motivation window)

- **Notice-of-hearing stage (BEST window).** This is the sweet spot: default is public but the owner still has **full ability to pay off, reinstate, sell, or take a subject-to/short-sale deal**, and the sale is still weeks out. Owner motivation is high (they just got served / posted) but panic-desperation hasn't set in. **Move:** mail/door-knock/skip-trace immediately on the SP filing; lead with "you have options before the [sale date]." Pull the deed-of-trust book/page from the notice to compute payoff. This is where the engine should spend most outreach budget.

- **Between hearing and notice of sale.** Owner has lost the "will this really happen" doubt; reinstatement cost is climbing (attorney fees, costs taxed in). **Move:** reinstatement-math + fast-close cash offer. Motivation rising, equity intact if any.

- **Notice-of-sale / final 20 days (HIGH urgency).** Hard sale date is set and published. Owner motivation peaks; this is the last clean window for a **pre-sale purchase** (buy the property or the note, or get the owner to deed it and reinstate). **Move:** urgent, deadline-anchored outreach ("sale is [date], X days left"). After this, control passes to the auction.

- **Upset-bid window (10 days, post-sale).** The property sold at auction but **the borrower can still redeem by paying in full**, and any investor can **file an upset bid (5%/$750 min)** to take the winning position. **Two plays:** (1) as a buyer, file an upset bid if the opening/last bid is below your max; (2) approach the just-sold owner about redemption financing / surplus-funds recovery. This is a specialist, fast-moving lane.

- **Post-deed.** No redemption; the only remaining plays are **surplus-funds recovery** for the former owner (if the sale exceeded the debt) and **REO/wholesale** to the winning bidder. Prune from active seller outreach.

### Encode in the engine (stage field / urgency multiplier / prune rule)

Add an `nc_foreclosure_stage` enum with a monotonically increasing urgency multiplier, driven by which public surface produced the record and its date fields:

```
STAGE                       source signal                         urgency_mult   window
pre_notice_45day           (inferred only, home loans)            0.6            paydown likely
notice_of_hearing_filed    Clerk SP index / trustee calendar      1.4  ← PRIME   weeks out, owner can still act
hearing_authorized         clerk calendar past hearing date       1.6            appeal window / advertising
notice_of_sale_published   courthouse/newspaper/ncnotices         2.0  ← PEAK    ≤20-30 days, hard date
sale_held                  report of sale filed (Clerk)           1.3            upset-bid lane only
upset_bid_open             upset-bid notice in Clerk file         1.5            10-day restart; redemption still live
rights_fixed / deed        Register of Deeds trustee deed          0.0  → PRUNE  no redemption; REO/surplus only
```

Concrete encoding rules:
- **`sale_date` field** parsed from the notice of sale (or trustee calendar). Compute `days_to_sale`. Apply an **escalating urgency curve**: multiplier ramps as `days_to_sale` drops from ~45 → 0, spiking inside the final **20-day** notice window.
- **`nc_no_redemption = TRUE`** flag on all NC power-of-sale records so downstream logic never assumes a SC-style redemption grace period (contrast with SC judicial process). This is the key NC-vs-SC differentiator.
- **Upset-bid tracker:** when a record hits `sale_held`, set a **10-day timer that RESETS on each new upset-bid filing** (§45-21.27 successive-bid rule); only transition to `rights_fixed` after 10 clean days. Do not prune during upset-bid churn — redemption is still legally possible.
- **PRUNE rule:** once a **trustee's deed is recorded** (Register of Deeds) OR `rights_fixed` with no redemption, drop from *seller* outreach and, if `sale_price > debt`, route to a **surplus-funds** sub-list rather than deleting.
- **De-dupe key:** the Clerk **SP file number** + deed-of-trust **book/page** (both appear in the §45-21.16 notice and §45-21.26 report) — use this to merge the same case as it moves from notice-of-hearing → notice-of-sale → upset-bid across different public surfaces, so one property isn't ingested as three leads.
- **Earliest-ingest priority:** poll the **Clerk SP special-proceedings index and substitute-trustee firm calendars first** (longest lead), treat newspaper/`ncnotices.com` notice-of-sale as confirmation + hard-date enrichment, and treat Register-of-Deeds trustee deeds as the terminal/prune signal.

**Statutes cited (all verified against ncleg.gov primary text):** §45-102 (45-day pre-foreclosure notice), §45-21.16 (notice + hearing; 10-day service, 20-day posting-service, 6 findings, 10-day appeal, 1% bond), §45-21.17 (notice of sale: 20-day courthouse posting, 2-week newspaper publication, 7-day span, last pub ≤10 days pre-sale, 20-day mailing), §45-21.23 (time/place of sale), §45-21.26 (report of sale within 5 days), §45-21.27 (upset bid: 5%/$750 min, 10-day window, successive-bid restart), §45-21.29 (orders for possession), §45-21.29A (no confirmation required; rights become fixed = no post-sale redemption).


## SC + NC Tax Foreclosure & Redemption Windows

### The process / timeline (numbered stages with statutory citations + typical days between stages)

**SOUTH CAROLINA — "Alternate Procedure," SC Code Title 12, Chapter 51 (a certificate/redemption system, NOT a court judgment)**

1. **Tax becomes delinquent** — county taxes go delinquent after Jan 15 (following the prior year's levy). Penalties accrue in steps; the account rolls to the Delinquent Tax Collector.
2. **Execution issued + first notice** — the Treasurer issues an *execution* to the officer charged with collection, who mails the defaulting taxpayer and any grantee of record a delinquent-tax notice by **certified mail, return receipt requested–restricted delivery** (SC Code **§12-51-40(a)–(b)**).
3. **Levy / seizure by posting** — if the certified notice is returned undelivered, the officer takes "exclusive physical possession" by **posting a "Seized … to be sold for delinquent taxes" sign on the premises** (§12-51-40(c)). This posting is the legal levy.
4. **Advertisement** — the property is advertised in a newspaper of general circulation under the heading "Delinquent Tax Sale," with the delinquent taxpayer's name and description, **once a week for 3 consecutive weeks** for real property (§12-51-40(d)). Typically the 3 ad weeks run in **October**.
5. **Tax sale (public auction)** — held at the county-set date, **almost always Oct/Nov** (many counties fix the first Monday of November or early December). Bidding starts at taxes+penalties+costs (§12-51-50).
6. **12-MONTH REDEMPTION WINDOW opens** — from the sale date, the owner (or any grantee, mortgagee, or judgment creditor) may redeem for the bid + tiered interest: **3% (mo. 1–3), 6% (mo. 4–6), 9% (mo. 7–9), 12% (mo. 10–12)**, interest capped at the FLC bid amount (SC Code **§12-51-90(A)–(B)**). *This is the prime motivated-seller window — the owner still holds title the entire 12 months.*
7. **Forfeited Land Commission (FLC) backstop bid** — if no third party bids, the officer enters a bid on behalf of the county **FLC** equal to all unpaid taxes/penalties/costs (SC Code **§12-51-55**); property that gets no outside bid is held by the FLC subject to the same redemption.
8. **Tax deed to bidder** — if not redeemed within the 12 months, the officer executes and delivers a **tax title/deed** to the successful purchaser (SC Code **§12-51-130**; the deed is largely incontestable after a further limitations period). Occupancy/possession does not pass until the deed.

*Typical spacing (SC):* Jan 15 delinquency → execution & certified notice (spring/summer) → 3-week ad (≈ Oct) → sale (≈ Nov) → **12-month redemption** → tax deed (≈ following Nov). Practical owner-motivation runway from first public ad to loss of title is roughly **13+ months**.

**NORTH CAROLINA — two parallel tracks, NCGS Ch. 105, Art. 26. There is essentially NO post-sale redemption; the owner's only "redemption" is paying off *before* the sale/confirmation.**

**Track A — In-Rem, NCGS §105-375 (fast, administrative, most-used in these counties):**
1. **Delinquency + lien advertisement** — the annual tax-lien advertisement runs first; the collector may file the in-rem certificate **no earlier than 30 days after the tax liens were advertised** (§105-375(b)).
2. **Certificate filed with Clerk of Superior Court** — collector files a certificate (taxpayer name, amount, years) with the **Clerk of Superior Court** (§105-375(b)); this is the docketing vehicle.
3. **30-day pre-docketing notice** — at least **30 days before docketing**, notice is sent by **registered/certified mail, return receipt requested** to the taxpayer and lienholders, stating a judgment will be docketed, the proposed date, that execution will issue, and that the lien may be satisfied before judgment (§105-375(c)(1)–(3)). If no receipt in 10 days, the collector posts the property and **publishes "Notice of Docketing Judgment" in the newspaper once weekly for 2 weeks** (§105-375(c)(4)).
4. **Judgment docketed** — the taxes/penalties/interest/costs become a **valid judgment against the property**, bearing **8% annual interest** (§105-375(d)).
5. **Execution + sheriff's sale** — execution may issue **only after 3 months and before 2 years from the indexing of the judgment** (§105-375(i)); the sheriff sells at public auction.
6. **Upset-bid period** — the sale stays open **10 days for upset bids** (raise by 5% or $750, whichever greater), then confirmation; sheriff's deed issues. **No statutory redemption after confirmation.**

**Track B — Mortgage-Style, NCGS §105-374 (judicial; used for complex title/heirs):**
1. Civil action "in the nature of an action to foreclose a mortgage," filed in the General Court of Justice where the property sits (§105-374).
2. Complaint + service on all interests → judgment → **commissioner's sale**.
3. Commissioner **reports the sale within 3 days**; a **10-day exceptions/increased-bid (upset) period** follows (§105-374); then confirmation and commissioner's deed.
4. **Redemption right ends at confirmation** — before confirmation the owner can stop everything by paying **all taxes, penalties, interest, and costs** (§105-374 redemption-before-confirmation clause).

*Typical spacing (NC in-rem):* lien ad → +30 days → certificate/notice → +30 days → docket judgment → **3 months minimum → 2 years max** to sale → 10-day upset → confirmation. The **owner's payoff window runs from the 30-day notice through the day before confirmation** — no year-long post-sale grace like SC.

---

### Where each stage is PUBLICLY visible (free surface) + lead-time before sale

**SOUTH CAROLINA:**
- **Newspaper "Delinquent Tax Sale" ad (§12-51-40(d))** — the definitive free list of every parcel: 3 consecutive weeks (≈ October). **Lead time ≈ 3–6 weeks before the Nov sale.**
- **County Treasurer / Delinquent Tax webpages** — most in-footprint counties post the sale list PDF online alongside the paper ad. Verified live: **Spartanburg** ("2025 Tax Sale Info" + Real-Property-Tax-Sale-List PDF; also mirrored at goupstate.com), **Pickens** ("list available 3 weeks prior on the webpage"), **Oconee** (oconeesc.com/delinquent-tax/sale-list), plus Anderson/Cherokee/Union/Laurens treasurer pages. **Lead time: same 3-week window.**
- **Bidder-registration deadline** (e.g., Pickens: signed form by 5 pm the Monday before sale) confirms the exact sale date.
- **THE REDEMPTION LIST (highest-value surface)** — after the sale, the Delinquent Tax Office holds the **list of sold-but-not-yet-redeemed parcels for the full 12 months**. These owners **still own the home and are under a hard deadline**. Not always web-posted; obtainable by request/FOIA from the Treasurer. **Lead time: up to 12 months of a known, dated deadline.**
- **ROD/assessor** confirms current owner + mailing address for skip-trace.

**NORTH CAROLINA:**
- **Annual tax-lien advertisement** — earliest free signal; the in-rem clock can't start until 30 days after it.
- **"Notice of Docketing Judgment" newspaper publication (§105-375(c)(4))** — names parcels headed to judgment. **Lead time: months before any sale (3-month minimum after docketing).**
- **Clerk of Superior Court — Special Proceedings / judgment docket** — the docketed in-rem judgment and §105-374 civil files are **public records** (often SP or CV file numbers) at the Clerk's office; searchable in person and via county foreclosure/tax-foreclosure listing pages. Verified county foreclosure pages: **Rutherford, Cherokee-NC**; **Buncombe/Gaston/Henderson** tax-administration and Clerk special-proceedings dockets. **Lead time: 3 months to 2 years after docketing — the widest runway in either state.**
- **Notice of Sale / upset-bid postings** — sheriff/commissioner notices at the courthouse and in the newspaper; upset bids filed with the Clerk. **Lead time: sale date + 10-day upset window.**
- **Law-firm tax-foreclosure calendars** — NC counties frequently outsource in-rem foreclosures to firms (e.g., Kania Law Firm serves much of Western NC) that publish **running parcel lists with sale dates online** — a clean, structured free surface.

---

### How to WORK this stage (the acquisition move + best owner-motivation window)

**SC — the 12-month redemption list is the single best motivated-seller pool in either state.** The owner *still holds title*, has been publicly named as delinquent, and faces a fixed drop-dead date after which they lose the property for pennies. Move:
- Pull the **sold-not-redeemed list**; skip-trace owner + mailing address (many are absentee).
- **Best window = months 4–9 after the sale.** By then interest has climbed to 6–9% (real pressure), the shock has set in, and there's still enough runway to close a clean purchase or a redemption-assignment before the 12-month cliff. Months 10–12 are highest-urgency but risk running out of closing time.
- Acquisition move: **buy the equity directly** (you get ARV − payoff − the redemption amount) OR take an **assignment of the winning bidder's tax-sale interest** under §12-51-90 as a backstop. Either way the pitch writes itself: "redeem now or lose the house."

**NC — no post-sale grace, so work the pre-judgment / pre-confirmation runway, which is *long* (3 months–2 years).** Move:
- Pull docketed in-rem parcels from the **Clerk / law-firm calendar** the moment the docketing notice publishes.
- **Best window = right after judgment is docketed, before execution issues.** The owner can still stop everything by paying off (§105-375(i)/§105-374 redemption-before-confirmation), so they're motivated but not yet desperate — ideal for a below-ARV cash offer that clears the tax judgment and leaves them equity.
- Second window: **during the 10-day upset-bid period** you can compete at auction, but that's a bidder play, not an off-market owner play.

Across both: these owners are equity-rich, cash-poor, publicly flagged, and calendar-bound — the textbook motivated seller.

---

### Encode in the engine

Add a `tax_fc_stage` enum field per lead, plus an `urgency_multiplier` and a `prune_rule`:

- **`tax_fc_stage`** (state-aware ordered enum):
  - SC: `sc_advertised` → `sc_sold_redeemable` → `sc_flc_held` → `sc_deed_issued`
  - NC: `nc_lien_advertised` → `nc_notice_docketing` → `nc_judgment_docketed` → `nc_execution_issued` → `nc_sale_upset` → `nc_confirmed`
- **`redemption_deadline`** (date): SC = sale_date + 365 days (hard). NC in-rem = execution-eligible date = judgment_docket_date + 90 days (soft, sale can slide to +730). Store both `earliest` and `latest`.
- **`urgency_multiplier`** driven by days-to-deadline:
  - SC `sc_sold_redeemable`: ramp with the statutory interest tiers — **1.0 (mo 1–3) → 1.4 (mo 4–6) → 1.8 (mo 7–9) → 2.5 (mo 10–12)**; this mirrors §12-51-90's 3/6/9/12% pressure curve.
  - NC `nc_judgment_docketed`/`nc_execution_issued`: flat **1.6** (long runway, high certainty) rising to **2.2** once a Notice of Sale posts.
  - `sc_advertised` / `nc_notice_docketing`: **1.2** (early, still redeemable, good for outreach but title not yet at risk).
- **Prune rules:**
  - **Hard-drop `sc_deed_issued` and `nc_confirmed`** — title has transferred; the owner is no longer a seller (route to the *new deed-holder* only if pursuing tax-deed resale).
  - **De-prioritize `sc_flc_held`** unless targeting FLC-surplus/assignment deals (§12-51-55) — owner interest is thin.
  - **Suppress redemption alerts once `redemption_deadline` < 21 days** in SC (insufficient time to close a purchase; flag only for redemption-assignment plays).
  - **Re-check status weekly** for any lead in a live stage — a redemption or payoff silently flips these to dead, so cross-check the county redemption list / Clerk docket before every outreach batch to avoid contacting owners who already cured.

**Sources:**
- [SC Code §12-51-40](https://law.justia.com/codes/south-carolina/title-12/chapter-51/section-12-51-40/) · [§12-51-90](https://law.justia.com/codes/south-carolina/title-12/chapter-51/section-12-51-90/) · [§12-51-55](https://law.justia.com/codes/south-carolina/title-12/chapter-51/section-12-51-55/) · [SC Title 12 Ch. 51 (full)](https://www.scstatehouse.gov/code/t12c051.php)
- [NCGS §105-375 (in rem)](https://www.ncleg.net/enactedlegislation/statutes/html/bysection/chapter_105/gs_105-375.html) · [NCGS §105-374 (mortgage-style)](https://www.ncleg.gov/EnactedLegislation/Statutes/PDF/BySection/Chapter_105/GS_105-374.pdf)
- [Spartanburg 2025 Tax Sale Info](https://www.spartanburgcounty.org/640/2025-Tax-Sale-Info) · [Pickens Delinquent Tax](https://www.co.pickens.sc.us/departments/delinquent_tax/index.php) · [Oconee Sale List](https://oconeesc.com/delinquent-tax/sale-list) · [Rutherford NC Foreclosure Process](https://rutherfordcountync.gov/departments/revenue_department_tax_administrator/foreclosure_information/foreclosure_process.php) · [Cherokee NC In-Rem Process](https://www.cherokeecounty-nc.gov/225/In-Rem-Foreclosure-Process) · [Nolo: SC property-tax default](https://www.nolo.com/legal-encyclopedia/what-happens-if-i-dont-pay-property-taxes-south-carolina.html)


## The Outreach-Timing Map: Strike Windows by Foreclosure Stage (SC + NC)

This section maps every foreclosure stage across South Carolina (judicial) and North Carolina (nonjudicial power-of-sale) to a strike window: owner-motivation level, days-of-window remaining, the correct acquisition play, and the urgency multiplier the engine should compute off `sale_date`. It synthesizes the process/surfacing/tactics detail from the per-stage playbooks into one operational timing layer.

### The process / timeline (numbered stages with statutory citations + typical days between stages)

Two different legal machines produce the same 7 economic stages. Track them with one `foreclosure_stage` enum but two `track` values (`SC_JUDICIAL`, `NC_POWER_OF_SALE`) because the surfacing points and clock speeds differ.

1. **Pre-filing distress (both states).** Federal servicing rule bars referral until the borrower is 120+ days delinquent (12 C.F.R. § 1024.41). SC adds a consumer right-to-cure: 30-day cure notice under S.C. Code § 37-5-110 before acceleration on a consumer mortgage. NC requires a 45-day pre-foreclosure notice (N.C.G.S. § 45-102, sent via the State Home Foreclosure Prevention Project) before the notice of hearing. **Window: 30–120+ days of private distress before anything is filed.**
2. **Case commencement / lis pendens (SC) vs Notice of Hearing (NC).**
   - SC: plaintiff files a lis pendens (S.C. Code § 15-11-10 et seq.) no more than 20 days before the complaint, serves summons + complaint, and must include the foreclosure-intervention notice (S.C. Supreme Court Admin. Order 2011-05-02-01). Borrower's answer is due 30 days after service.
   - NC: lender files a Notice of Hearing with the clerk of court (N.C.G.S. § 45-21.16), served 10 days (personal) to 20 days (posting) before the hearing.
   - **SC filing → decree: commonly 90–180+ days.** NC filing → hearing: ~30–45 days.
3. **Judgment (SC) / Clerk's authorization (NC).**
   - SC: master-in-equity or special referee enters a foreclosure judgment/decree of sale (Rule 71, SCRCP) and sets sale terms, including whether a deficiency is sought.
   - NC: clerk enters an order authorizing sale after finding valid debt, default, right to foreclose, and proper notice (N.C.G.S. § 45-21.16(d)). A primary-residence borrower can get up to a 60-day postponement (§ 45-21.16C).
   - **SC judgment → sale: ~30–45 days.** NC order → sale: ~20–30 days.
4. **Notice of sale.**
   - SC: posted in 3 public places incl. the courthouse and published once a week for 3 consecutive weeks before sale.
   - NC: served on borrower ≥20 days before sale and published once a week for 2 successive weeks, last publication ≤10 days before sale (N.C.G.S. § 45-21.17).
   - **This is the ~21–30 day final runway before the auction.**
5. **The sale / auction.**
   - SC: judicial sale, almost always the **first Monday of the month** (next day if a holiday), conducted by the master-in-equity, special referee, or sheriff.
   - NC: trustee/substitute-trustee auction at the county courthouse door, any business day the trustee sets.
6. **Post-sale upset-bid window.**
   - SC: if the lender **reserves a deficiency judgment**, bidding stays open until the **30th day after sale** (S.C. Code § 15-39-720); if deficiency is waived, the sale closes on sale day.
   - NC: a **10-day upset-bid period** runs from the filing of the report of sale (N.C.G.S. § 45-21.27); every qualifying upset bid (≥5% and ≥$750 over) resets a fresh 10-day clock (§ 45-21.20). Borrower may redeem by paying in full any time before the period closes.
   - **SC: 0 or 30 days. NC: 10 days, resettable.**
7. **Confirmation / deed / post-confirmation.**
   - SC: after the bidding period closes with no upset, the officer executes a deed; surplus over the debt is claimable within **45 days** of the filed statement of receipts and disbursements (S.C. Code § 15-39-650 / Rule 71).
   - NC: once the upset period runs out, the trustee delivers a trustee's deed (N.C.G.S. § 45-21.29) and any surplus goes to junior lienholders then the borrower. **No post-sale statutory redemption in either state once the deed is delivered.**

### Where each stage is PUBLICLY visible (free surface) + lead-time before sale

| Stage | SC free surface | NC free surface | Lead-time before sale |
|---|---|---|---|
| Pre-filing distress | Not in court records — infer from tax-delinquency lists, NOD-equivalent breach letters (private), obituary/probate/divorce proxies | Same; plus 45-day § 45-102 notices are not public | 4–8+ months |
| Case commencement | **Lis pendens** indexed at the county ROD/Register of Deeds; complaint on the Clerk of Court/Public Index (ToS-walled) | **Notice of Hearing** on the Clerk of Superior Court / eCourts file; special-proceedings (SP) docket | SC: 90–180 days; NC: ~45–75 days |
| Judgment / order | Master-in-equity **sale roster/calendar** (county MIE page) once judgment entered | Clerk SP order; trustee/substitute-trustee firm's **foreclosure sale calendar** (law-firm websites) | SC: ~30–45 days; NC: ~20–30 days |
| Notice of sale | Legal-notices section of the county **newspaper** (3 weeks); courthouse posting; MIE roster | County **newspaper** legal notices (2 weeks); trustee firm's sale list; clerk sale postings | **21–30 days — the hardest, most reliable signal** |
| The sale | MIE roster shows result/high bidder | Trustee's **report of sale** filed with clerk | day 0 |
| Upset bid | MIE roster "bidding open until [30th day]" if deficiency reserved | Clerk's **upset-bid record**; each new upset re-filed | SC: +30; NC: +10 (resetting) |
| Post-confirmation | Deed recorded at ROD; **surplus-funds** statement filed (45-day claim) | Trustee's deed recorded; surplus reported to clerk | after sale |

The load-bearing free surfaces for timing: (a) the **lis pendens / Notice of Hearing** index at ROD/clerk gives the earliest reliable lead (months out), and (b) the **newspaper legal notice + master-in-equity roster / trustee sale calendar** gives the precise `sale_date` 2–4 weeks out. The engine should key urgency off (b) and use (a) to enter the pipeline early.

### How to WORK each stage (the acquisition move + best owner-motivation window)

- **Pre-filing distress — motivation LOW-MED, months of runway.** Owner still has equity and control, denial is high. Play: **subject-to** or **traditional purchase / listing-avoidance** pitch; plant the relationship. Cheapest acquisition, highest optionality. Best when there's real equity to protect.
- **Lis pendens / Notice of Hearing — motivation MED, 45–180 days.** Denial breaks once they're served. Play: **short sale** (if underwater) or **subject-to / equity purchase** (if equity). This is the sweet spot for negotiated deals — enough time to close a normal transaction, enough fear to make them answer.
- **Judgment / clerk order — motivation MED-HIGH, 20–45 days.** Owner now knows a sale date is coming. Play: fast **cash purchase** or **subject-to**; start a **short-sale** only if the lender will postpone.
- **The ~21–30 days before sale (notice of sale) — motivation HIGH, <30 days.** This is the peak strike window. Play: **cash-for-keys**, **assignment/wholesale to a cash buyer**, or **deed-in-lieu-adjacent** fast close. Too little time for a conventional short sale; lead with certainty and speed.
- **At the sale — no owner play; investor play.** **Buy at auction** (SC first-Monday MIE sale; NC courthouse trustee sale). Bring certified funds; in SC know whether a deficiency is reserved (30-day upset risk).
- **Post-sale upset-bid window — motivation VERY HIGH but SHRINKING control.** SC 30 days / NC 10 days (resettable). Owner may still redeem by paying in full. Plays: place an **upset bid** to win the asset; or approach the borrower for a redemption-financing / last-minute equity purchase if they can still pay off.
- **Post-confirmation — owner motivation moot; new play is SURPLUS.** If the property sold for more than the debt, the former owner is owed **surplus funds** (SC 45-day claim window; NC surplus to clerk). Play: **surplus-funds recovery outreach** to the displaced owner — a distinct, high-conversion, post-eviction lead type.

### Encode in the engine (stage field / urgency multiplier / prune rule)

Add/confirm these fields on every foreclosure lead and compute urgency off `sale_date`:

- **`foreclosure_stage`** enum: `pre_filing | lis_pendens_or_noh | judgment_or_order | notice_of_sale | at_sale | upset_bid | post_confirmation`, plus **`track`** = `SC_JUDICIAL | NC_POWER_OF_SALE`.
- **`sale_date`** (from newspaper legal notice / MIE roster / trustee calendar) and **`days_to_sale = sale_date − today`**.
- **`urgency_multiplier`** as a piecewise function of `days_to_sale` (the primary ranking lever):
  - `days_to_sale ≤ 0` and stage `upset_bid`: **3.0** (SC 30-day / NC 10-day last-chance window — highest, but see prune).
  - `1–14` days: **2.5**
  - `15–30` days (the notice-of-sale runway): **2.0**
  - `31–75` days (post-filing, pre-notice): **1.4**
  - `76–180` days (lis pendens / NoH, pre-judgment): **1.15**
  - pre-filing / no sale_date: **1.0** (base; rank on equity instead).
- **`owner_motivation`** derived tier (`LOW/MED/HIGH/VERY_HIGH`) mirroring the multiplier, used to pick the `recommended_play` string (subject-to/short-sale early → cash-for-keys/assignment late → buy-at-sale → surplus-recovery post-sale).
- **Deficiency flag (SC only):** `sc_deficiency_reserved` bool. If true, the real closing date is `sale_date + 30`; keep the lead HOT through the upset window instead of pruning at `sale_date`.
- **Prune / transition rules:**
  - When `days_to_sale` crosses 0, do **not** hard-prune. Transition to `upset_bid` and keep for SC 30 days (or +30 if deficiency reserved) / NC 10 days (extend on each detected new upset bid).
  - When the **deed records** at ROD (confirmation), transition to `post_confirmation`, drop `urgency_multiplier` to 0 for acquisition, and **re-route to the surplus-funds lane** if `sale_price > total_debt` (SC 45-day claim clock; else prune after the claim window).
  - Reset the NC upset clock (`sale_date` effectively +10) whenever a new upset bid is detected on the clerk record, since each resets the period (§ 45-21.27 / § 45-21.20).
  - Suppress acquisition outreach (not surplus outreach) once `post_confirmation` + deed recorded, to avoid contacting owners who no longer control the asset.

Sources:
- [S.C. Code § 15-39-720 — Upset bids within thirty days (Justia)](https://law.justia.com/codes/south-carolina/title-15/chapter-39/section-15-39-720/)
- [Charleston County — Primer for Mortgage Foreclosures in SC (Master-in-Equity)](https://www.charlestoncounty.gov/departments/master-in-equity/mortgage-forclosures-primer.php)
- [Pickens County — Primer for Mortgage Foreclosures in SC](https://www.co.pickens.sc.us/departments/master_in_equity/primer_for_mortgage_foreclosures.php)
- [SC Judicial Branch — Rule 71, SCRCP (master-in-equity references)](https://www.sccourts.org/resources/judicial-community/court-rules/civil/rule-71/)
- [SC Supreme Court Administrative Order 2011-05-02-01 — Foreclosure Intervention Notice](https://www.sccourts.org/courtOrders/displayOrder.cfm?orderNo=2011-05-02-01)
- [N.C.G.S. § 45-21.16 — Notice and hearing](https://www.ncleg.net/enactedlegislation/statutes/html/bysection/chapter_45/gs_45-21.16.html)
- [N.C.G.S. § 45-21.27 — Upset bid on real property](https://www.ncleg.gov/EnactedLegislation/Statutes/PDF/BySection/Chapter_45/GS_45-21.27.pdf)
- [NC General Statutes Chapter 45 — Mortgages and Deeds of Trust](https://www.ncleg.gov/EnactedLegislation/Statutes/PDF/ByChapter/Chapter_45.pdf)
- [Green Mistretta Law — NC Foreclosure Process Timeline (§ 45-102, § 45-21.16/.17/.27/.29)](https://greenmistrettalaw.com/what-to-expect-in-the-north-carolina-foreclosure-process/)
- [Nolo — South Carolina Foreclosure Laws and Homeowner Rights (§ 37-5-110 right-to-cure)](https://www.nolo.com/legal-encyclopedia/south-carolina-foreclosure-laws-and-procedures.html)


## Dead-Lead Detection & Board Pruning

### The process / timeline (numbered stages with statutory citations + typical days between stages)

A lead dies at one of six exit events. Each has a distinct statutory trigger, a distinct public artifact, and a distinct prune rule. Because the engine's mission is broader than foreclosure (probate, tax-delinquent, divorce, etc.), "dead" here means **the owner no longer controls the equity we were targeting, OR contacting them is unlawful.** The six exits:

1. **Foreclosure sale completed + deed recorded (the hard death).**
   - **SC (judicial / Master-in-Equity):** Sale held; if a deficiency was pled and not waived, bidding stays open through the **30th day after sale** for upset bids (S.C. Code **§15-39-720**, **§15-39-760**; SCRCP **Rule 71(b)**). If deficiency is waived in the pleadings/in writing, bidding **closes the day of sale** and the buyer has ~20 days to comply. Master then issues an **Order of Confirmation** and a **Master's/Title-to-Real-Estate deed** is recorded in the ROD. Owner is out. Days between sale and recorded deed: **~1–10 days (deficiency waived)** to **~35–60 days (deficiency sought → 30-day upset window + confirmation + recording lag).**
   - **NC (power-of-sale, clerk of superior court):** Trustee holds sale, files **report of sale**; upset-bid period runs **10 days** (NCGS **§45-21.27**); *every* valid upset bid resets a fresh 10-day clock. When the last 10-day window closes with no further upset, the sale is final; trustee delivers/records the **trustee's deed** (NCGS **§45-21.29A**, **§45-21.30**). Days from first sale to recorded deed: **~11 days (no upset)** to **30–60+ days (upset chains).**

2. **Upset bid final / sale confirmed (soft-lock, pre-deed).** In both states the equity is effectively gone once the upset window closes even before the deed hits ROD. NC: 10-day quiet after report of sale (§45-21.27). SC: 30th day passes with no upset, or same-day close on a waived-deficiency sale.

3. **Owner redeemed — tax lane (SC).** Delinquent taxpayer / grantee / mortgage or judgment creditor may redeem within **12 months of the tax sale** (S.C. Code **§12-51-90**). Until the redemption period runs AND the tax deed is executed and recorded (**§12-51-130**), the *owner still owns it* — so a redeemed parcel is not dead as an owner lead, it is **reactivated** (they found money; motivation may drop). A tax deed recorded after non-redemption = dead (new owner). NC uses no tax-sale redemption; NC delinquent tax is a **judicial foreclosure** (NCGS §105-374) that ends like exit 1.

4. **Case dismissed / withdrawn / voluntarily nonsuited.** Lender/trustee pulls the action or the clerk dismisses. NC: notice-of-hearing special proceeding withdrawn or denied before clerk of superior court. SC: lis pendens/complaint dismissed or case marked ended. This is a **soft death** — the distress signal is gone (loan cured or workout), so stop the *foreclosure* pitch, but the owner still owns.

5. **Bankruptcy filed → automatic stay (DO-NOT-CONTACT).** The instant a petition is filed, **11 U.S.C. §362** imposes an automatic stay that halts the foreclosure and bars collection/communication. **Any mail/dial after this is a potential stay violation** — hard suppress, do not merely deprioritize.

6. **Loan reinstated / satisfied / payoff recorded.** Debtor exercises contractual reinstatement (NC has no statutory reinstatement right; most Fannie/Freddie notes grant it) or pays off; **satisfaction of mortgage / cancellation of deed of trust** is recorded in ROD, or NCGS **§45-21.20** "satisfaction of debt before completion of sale" stops the sale. Distress gone.

### Where each stage is PUBLICLY visible (free surface) + lead-time before sale

| Exit event | Free confirming surface | Signal to scrape / match |
|---|---|---|
| **1/2. Sale + deed recorded** | **County ROD/Register of Deeds** grantor-grantee index. SC: instrument "Title to Real Estate," "Master's Deed," grantor = Master in Equity/Sheriff. NC: "Trustee's Deed," grantor = the substitute trustee/law firm. | New deed where **grantor = prior distressed owner or the court officer**, dated after the sale. This is the definitive kill signal. |
| **2. Upset final (pre-deed)** | **NC clerk of superior court** special-proceeding file / SP index (report of sale + upset-bid notices, each stamped-filed). SC: **Master-in-Equity sales roster / results** (many counties post "sold/confirmed" columns). | NC: 10 quiet days after the last filed upset-bid notice = final. SC: 30 days past sale date with no upset entry, or "confirmed." |
| **3. Tax redemption (SC)** | **County Delinquent Tax Collector "redeemed" list**; tax deed later in **ROD** (§12-51-130). | Parcel drops off the still-owed tax-sale list = redeemed (reactivate). Tax deed recorded = dead. |
| **4. Dismissed/withdrawn** | **NC clerk SP file** (order dismissing / withdrawal); **SC clerk of court / lis pendens release** in ROD. Law-firm/trustee foreclosure calendars drop the file. | Case no longer appears on the trustee's upcoming-sale calendar AND no sale/deed recorded = withdrawn. |
| **5. Bankruptcy stay** | **PACER Case Locator (pcl.uscourts.gov)** national name search — free for registered users, and fees waived under $30/qtr; **Multi-court VCIS phone (866-222-8029)** free. Districts: NC Western (Asheville/Charlotte covers our NC counties), SC District (Spartanburg/Greenville/Columbia divisions). | Debtor name (+ address corroboration) returns an **open** bk case → stay in effect. Case number, filed date, chapter. |
| **6. Reinstated/satisfied** | **ROD:** recorded **Satisfaction of Mortgage** (SC) / **Cancellation of Deed of Trust** (NC). Trustee calendar drops the file with no sale. | Satisfaction/cancellation instrument recorded against the target loan = cured. |

**Lead-time note:** Exits 1–2 are *terminal* (no lead-time to capture — they end the window). The value of detecting them is **avoiding wasted spend on an owner who is already out.** Exits 3–6 are *reversible/soft*; detecting them prevents mailing an owner who no longer has our motivation trigger.

### How to WORK this stage (the acquisition move + best owner-motivation window)

Dead-lead detection is a **defensive** move: it protects deliverability, cost-per-lead, and legal exposure, and it re-routes attention to still-live equity. Concrete moves:

- **Post-sale, pre-eviction skim (exits 1/2):** When ROD shows a Trustee's/Master's deed to a **third-party investor** (not the beneficiary/plaintiff), the *former owner* is now a displaced-tenant lead (cash-for-keys / relocation), not an equity seller — route to a separate list, suppress from equity mailers. When the deed goes to the **lender/plaintiff** (REO), the owner lead is fully dead; the **new REO owner** may become a wholesale-buyer lead.
- **Redemption reactivation (exit 3):** A parcel that drops off the SC delinquent list within the 12-month window means the owner found cash under pressure — motivation likely *fell*. Downgrade, don't delete; re-touch near the next tax cycle.
- **Withdrawal workout (exit 4):** Case withdrawn usually = loan-mod/forbearance/reinstatement. Best window is **90–180 days later** — a meaningful share re-default; keep as a warm "prior-distress" lead on a slow drip, off the urgent cadence.
- **Bankruptcy (exit 5):** Hard stop. The correct "move" is *no move* until the case closes/dismisses or the stay is lifted; a Chapter 7 no-asset case that closes in ~90 days can re-surface the property; a dismissed Ch.13 (very common) often *re-triggers* foreclosure — re-activate on dismissal.

### Encode in the engine (stage field / urgency multiplier / prune rule)

Extend the existing confirmed-sold logic into a single **`lifecycle_stage`** enum + **`suppress`** flags rather than deleting rows (deletion loses re-activation signal and the board sidecar per the load_board rule):

```
lifecycle_stage ∈ {
  live, upset_pending, sold_confirmed, deed_recorded,
  redeemed, dismissed_withdrawn, bankruptcy_stay,
  reinstated_satisfied
}
```

**Prune / suppress rules (urgency_multiplier applied to score):**

1. **`deed_recorded`** (ROD grantor = prior owner OR court officer, instrument in {Trustee's Deed, Master's Deed, Title to Real Estate, Tax Deed}) → **HARD PRUNE**: `active=false`, `urgency_multiplier=0`, `suppress_all=true`. Retain row for buyer/displaced-tenant re-routing.
2. **`sold_confirmed` / `upset_pending`** (SC: sale_date + 30d no-upset OR waived-deficiency same-day close; NC: last upset-bid filing + 10 quiet days) → **SOFT PRUNE**: `urgency_multiplier=0`, hold 15 days for the deed to appear, then promote to `deed_recorded`. Guards against mailing during the dead upset window.
3. **`bankruptcy_stay`** (PACER/PCL name+address match to an OPEN case) → **HARD SUPPRESS, legal**: `suppress_all=true`, `do_not_contact=true`, tag `reason=362_stay`, store `bk_case_no` + `filed_date`. **Never delete** — set a re-check; on case **dismissed/closed**, flip back to `live` with a re-trigger.
4. **`redeemed`** (SC parcel drops off delinquent-tax owed list, no tax deed) → **DOWNGRADE**: `urgency_multiplier≈0.3`, keep owner lead, schedule re-touch at next tax cycle.
5. **`dismissed_withdrawn`** (off trustee calendar + no sale/deed within N days) → **DOWNGRADE**: `urgency_multiplier≈0.4`, move to slow "prior-distress" drip; set 120-day re-default re-check.
6. **`reinstated_satisfied`** (ROD Satisfaction/Cancellation on target loan) → **SOFT PRUNE**: `urgency_multiplier≈0.2`; equity story intact but no distress trigger.

**Implementation hooks:**
- **ROD watcher (primary kill-switch):** nightly grantor-grantee delta per county; match new deeds/satisfactions/cancellations to board `parcel_id`/owner-name. This is the single highest-value pruner because it confirms exits 1, 2, 3(tax-deed), and 6 from one free surface. It also *extends* the current confirmed-sold check from "sale happened" to "**deed recorded to whom**" (lender vs third-party → different downstream list).
- **Court-calendar delta (NC clerk SP index / SC Master roster):** detect `dismissed_withdrawn` and `upset_pending`→`sold_confirmed` transitions (drop-off + 10/30-day timers).
- **PACER/PCL enricher (weekly, gated):** batch owner names from `live` foreclosure leads against the PACER Case Locator; open bk hit → `bankruptcy_stay` + `do_not_contact`. Keep volume under the $30/quarter fee-waiver threshold; VCIS phone as a free zero-cost fallback for spot checks.
- **Idempotency + re-activation:** every prune writes `pruned_reason` + `pruned_date` + a `recheck_after` date; a dismissed bankruptcy or a dropped-off redemption flips the row back to `live` on the next run. Store all of this via `web_artifact.load_board()` so the vision/comps/cama sidecar is preserved.

**Sources:** [S.C. Code §15-39-720 (upset bids, 30 days)](https://law.justia.com/codes/south-carolina/title-15/chapter-39/section-15-39-720/) · [SC Master-in-Equity foreclosure primer (Pickens Co.)](https://www.co.pickens.sc.us/departments/master_in_equity/primer_for_mortgage_foreclosures.php) · [NCGS §45-21.27 (upset bid, 10 days)](https://www.ncleg.gov/EnactedLegislation/Statutes/PDF/BySection/Chapter_45/GS_45-21.27.pdf) · [NC Chapter 45 (power-of-sale, §45-21.20/.29A)](https://www.ncleg.net/enactedlegislation/statutes/html/bychapter/chapter_45.html) · [S.C. Code §12-51-90 (tax redemption, 12 months)](https://law.justia.com/codes/south-carolina/title-12/chapter-51/section-12-51-90/) · [11 U.S.C. §362 (automatic stay)](https://www.law.cornell.edu/uscode/text/11/362) · [PACER Case Locator](https://pcl.uscourts.gov/) · [NC foreclosure process (Nolo)](https://www.nolo.com/legal-encyclopedia/north-carolina-foreclosure-laws-procedures.html)


## Buying at the Sale — The Operational Mechanics (SC MIE & NC Trustee Sale)

### The process / timeline (numbered stages with statutory citations + typical days between stages)

**SOUTH CAROLINA — Master-in-Equity judicial sale (SC Code Title 15 ch. 39; Title 29 ch. 3; SCRCP Rule 71)**

1. **Sale day — public outcry auction.** Held by the Master-in-Equity (or Special Referee/Clerk) on that county's designated Sales Day, typically the **first Monday of the month** at the courthouse. Plaintiff opens with a credit bid; third parties bid over it. Governed by the order/judgment of foreclosure and SCRCP Rule 71(b).
2. **5% good-faith deposit — same day.** The high bidder must post the deposit set in the judgment — **5% of the bid, in cash/certified funds, by 3:00 p.m. that same day**. Forfeited if the bidder fails to close. (Set by the foreclosure judgment; standard across MIE offices.)
3. **Compliance window depends on whether a deficiency was demanded:**
   - **Deficiency WAIVED → bidding closes immediately.** Winner has **~20 days to comply** (pay balance) — **SC Code § 15-39-760**.
   - **Deficiency DEMANDED → 30-day upset-bid period.** The sale stays open **30 days** for upset bids — **SC Code § 15-39-720**. The plaintiff bids its maximum in the principal sale and **may NOT bid at the upset sale**; the property goes to the highest bidder at the reconvened upset sale.
4. **Upset-bid sale (if applicable).** Reconvened ~30 days later; highest bidder wins and must post 5% / comply.
5. **Deed delivery.** After compliance, the Master executes and records a **Master's Deed** conveying whatever title was before the court — **SCRCP Rule 71(b)**; typically recorded **10–14 days after compliance**.
6. **Deficiency appraisal right (buyer-relevant because it caps the credit bid).** Within **30 days after the sale**, the defendant may apply for an **order of appraisal** — **SC Code § 29-3-680** — substituting FMV for the high bid to reduce the deficiency. Cannot be waived for a dwelling/consumer-credit transaction.

**NORTH CAROLINA — Power-of-sale trustee foreclosure (N.C.G.S. Chapter 45, Article 2A)**

1. **Sale day — trustee/substitute-trustee auction** at the county courthouse per the Notice of Sale (following the clerk's hearing under § 45-21.16).
2. **Deposit at the fall of the hammer.** Trustee may require the high bidder to immediately deposit **the greater of 5% of the bid or $750** — **N.C.G.S. § 45-21.10(b)**.
3. **Report of sale filed** with the Clerk of Superior Court, which **starts the 10-day upset-bid clock** — **§ 45-21.26 / § 45-21.27**.
4. **10-day upset-bid period (§ 45-21.27).** Any person may upset by depositing with the clerk **≥5% of the upset amount but not less than $750**, and bidding **the last price + at least 5%, minimum $750 increase**. **Each valid upset bid resets a fresh 10-day clock.** Cycles until 10 days pass with no upset.
5. **Rights become fixed / sale final (§ 45-21.29A).** When 10 days expire with no further upset, the last-highest bidder is the winner; the sale is final (no separate clerk "confirmation" hearing is required in NC power-of-sale — expiration of the upset period is what fixes rights).
6. **Trustee's deed delivered** once the winner pays the balance per the Notice of Sale timeframe. **Default → resale** under the same procedures — **§ 45-21.30(c)** (defaulting bidder liable for the shortfall).

Typical NC end-to-end after sale day: **10 days minimum, extended 10 days per upset** — plan on **10–30+ days** before the deed.

### Where each stage is PUBLICLY visible (free surface + lead-time before sale)

- **Sale calendars / roster (both states):** County **Master-in-Equity sales rosters** (SC — e.g., Charleston, Spartanburg, Horry publish monthly PDF/HTML rosters) and NC **Clerk of Superior Court foreclosure sale listings** + the plaintiff **law-firm foreclosure calendars** (Hutchens, Brock & Scott, Rogers Townsend, etc.). Lead-time: **2–4 weeks** before sale day (NC Notice of Sale posted 20 days out under § 45-21.17; SC judgment schedules the sale).
- **Newspaper legal notices:** NC Notice of Sale published once a week for 2 weeks (§ 45-21.17); SC notice of sale published. Lead-time **~2–3 weeks**.
- **Upset-bid activity (NC, free at clerk):** The **Report of Sale and each Notice of Upset Bid** are filed in the clerk's Special Proceedings file — walk-in or e-file docket shows the current high bid and the running 10-day deadline. Lead-time: **a live 10-day window you can jump into as a bidder or as an outreach trigger.**
- **Upset-bid activity (SC):** MIE office tracks the 30-day upset period; roster flags "deficiency demanded" cases as remaining open.
- **Post-sale deed (both):** **Register of Deeds** — Master's Deed (SC) / Trustee's Deed (NC) records within ~2 weeks; this is the public confirmation the property changed hands and, by comparison to the debt, whether **surplus** exists.
- **Surplus deposits:** SC — statement of receipts/disbursements filed with the MIE; NC — surplus paid into the **Clerk of Superior Court** (§ 45-21.31) and, if unclaimed, ends up at **NC Dept. of State Treasurer (NCCash)** and **SC Palmetto Payback** unclaimed-property databases (already in the engine's cross-check).

### How to WORK this stage (the acquisition move + best owner-motivation window)

- **As a bidder:** Register early (SC MIE offices require a **registration form ~7 days before sale**; bring certified funds for the 5%/$750 deposit). In **NC, the upset-bid window is the real opening** — you don't need to attend the auction; monitor the clerk file and place an upset bid (last price + 5%/$750, deposit to clerk) any time in the live 10-day cycle. In **SC deficiency cases**, the 30-day upset sale is where third parties beat the plaintiff (plaintiff can't bid at upset).
- **As an off-market acquirer (higher-margin play):** The **pre-sale window is the motivation peak** — owner is days from losing the home and equity. Target the **2–4 weeks between notice-of-sale/roster publication and sale day** with a cash offer that beats the auction net (payoff + costs). This is the classic "stop the sale" deal.
- **Surplus-funds recovery as a distinct lead type:** After a sale where the bid exceeds debt + liens, the **former owner is owed the surplus** and usually doesn't know it. SC — claim filed with the MIE within **45 days of the statement of receipts/disbursements** (SCRCP Rule 71(c)); unclaimed after 45 days is deemed abandoned. NC — surplus sits with the **Clerk** and is claimed by **special proceeding** to determine entitlement (§ 45-21.32); stale funds flow to NCCash. The move: identify **overbid > total liens**, locate the displaced owner, and either broker recovery or use it as a warm door-opener. Best window: **immediately post-sale through the claim deadline.**

### Encode in the engine (a stage field / urgency multiplier / prune rule)

- **`sale_stage` enum:** `noticed` → `sale_scheduled` → `sold_pending_upset` (NC 10-day / SC 30-day) → `sold_final` → `deed_recorded`. Drive urgency off this.
- **`urgency_multiplier`:** peak the score in the **`sale_scheduled` window (days-to-sale ≤ 30, rising as it approaches 0)** — that's the off-market motivation apex. Add a **secondary spike for `sold_pending_upset`** (NC especially) so live upset-bid targets surface.
- **`upset_window_open` (bool) + `upset_deadline` (date):** for NC, compute from Report-of-Sale/last-upset date + 10 days; reset on each new upset notice. For SC deficiency cases, set 30 days from sale. Flag while open for bid-or-outreach action.
- **New lead type `surplus_recovery`:** trigger when `winning_bid − (payoff + captured_lien_stack) > 0`. Fields: `estimated_surplus`, `claim_deadline` (SC = statement-filing + 45 days; NC = special-proceeding, watch escheat to NCCash/Palmetto Payback), `displaced_owner` (route to skip-trace). Cross-reference the existing NCCash/Palmetto Payback checker.
- **Prune rule:** once `sale_stage = sold_final` **and** no positive surplus **and** owner-occupant already removed, **drop from active acquisition** (deal is gone) — but **retain** if `estimated_surplus > 0` (reclassify to `surplus_recovery`) or if it becomes bank-owned/REO for a separate resale lane.
- **Occupant-removal flag (`possession_path`):** SC purchasers use a **Writ of Assistance** (return to the MIE court; sheriff ejects — *Griggs v. Griggs*); NC purchasers get an **Order for Possession** from the clerk (§ 45-21.29) after **10 days' notice** (30 days for 15+ unit residential), executed by the sheriff per summary-ejectment procedure **§ 42-36.2**. Store as an underwriting cost/time input on bidder-side deals.

**Sources:**
- [SC Code Title 29 ch. 3 (§ 29-3-680 appraisal)](https://www.scstatehouse.gov/code/t29c003.php) · [§ 29-3-680 (Justia)](https://law.justia.com/codes/south-carolina/title-29/chapter-3/section-29-3-680/)
- [SCRCP Rule 71 (surplus, Master's Deed)](https://www.sccourts.org/resources/judicial-community/court-rules/civil/rule-71/)
- [Charleston County MIE Foreclosure Primer (§ 15-39-720 / § 15-39-760, writ of assistance)](https://www.charlestoncounty.gov/departments/master-in-equity/mortgage-forclosures-primer.php) · [Pickens County MIE Primer](https://www.co.pickens.sc.us/departments/master_in_equity/primer_for_mortgage_foreclosures.php) · [Horry County Upset Bid Sales](https://www.horrycountysc.gov/departments/master-in-equity/upset-bid-sales/)
- [N.C.G.S. Chapter 45, Article 2A (full)](https://www.ncleg.gov/EnactedLegislation/Statutes/HTML/ByArticle/Chapter_45/Article_2A.html)
- [G.S. 45-21.27 Upset bid / compliance bonds](https://www.ncleg.gov/EnactedLegislation/Statutes/HTML/BySection/Chapter_45/GS_45-21.27.html)
- [G.S. 45-21.29 Orders for possession](https://www.ncleg.gov/enactedlegislation/statutes/html/bysection/chapter_45/gs_45-21.29.html)
- [G.S. 45-21.31 (surplus proceeds) PDF](https://www.ncleg.gov/EnactedLegislation/Statutes/PDF/BySection/Chapter_45/GS_45-21.31.pdf) · [G.S. 45-21.32 (special proceeding for surplus) PDF](https://www.ncleg.gov/EnactedLegislation/Statutes/PDF/BySection/Chapter_45/GS_45-21.32.pdf)
- [NC surplus-funds claim procedure (Pierce Law Group)](https://piercelaw.com/news/uncategorized/what-procedures-apply-for-claiming-surplus-funds-if-a-foreclosure-sale-yields-excess-proceeds-in-north-carolina/)


---

# Deep-Dive Round 12 — Competitor UX Teardown (features to copy, 2026-07-02)


## Goliath Data (goliathdata.com)

Goliath is the "AI-acquisitions-team" competitor: its whole pitch is a closed loop — a distress signal fires, the owner gets skip-traced + intent-scored, drops into a pipeline, and the "David" AI voice agent calls them, all inside one app. For our purposes the key split is: **the data/UX layer (list-building, scoring, signal feed, pipeline, inbox) is fully copyable in a static dashboard**, while **the "David calls them / texts them" layer is regulated telephony infrastructure we cannot host statically.**

### Screen-by-screen feature inventory

- **Command Center CRM (home)** — central hub. Top-of-screen it surfaces "the hottest sellers sit right at the top of your list" via seller-intent score; below it, integrated tasks with reminders and a "daily agenda." This is the landing dashboard, not a separate report.
- **Intelligent List Builder** — operator sets parameters (location, price, equity, property type, distress signal, seller-intent-score threshold) and prospects auto-populate into named, saved lists. Core filter UI plus "filter by score threshold to focus your team."
- **Real-Time Monitoring / Signals feed** — a time-stamped stream of seller signals: pre-foreclosure notices, tax delinquencies, probate filings, plus life-events (marriage licenses, job changes, family events). Each row shows **trigger type + timestamp + property address**; refreshed hourly from county/court data. This is the "be first" surface.
- **Lead Scoring & Ranking / AI-ranked call list** — every owner is ranked and the UI "tells you why they need a call" (the score is explained, not just a number). Delivered as a **daily AI-ranked call list**; you can upload your own database and it flags hot vs. cold within it. Scores update in real time as underlying data changes.
- **Unified Inbox** — "calls, texts, emails in one thread" per contact. Single conversation timeline across channels.
- **Pipeline / Deal stages** — customizable pipelines ("adapted to your workflow"); a single live dashboard tracks every deal, notes, next steps, source, "who responded, what was said," and auto-flags stuck deals and overdue follow-ups. (Marketing implies drag-between-stages; not independently confirmed, but stage-based Kanban is the pattern.)
- **Automations / Drip campaigns** — advanced workflows + automated multi-touch drip sequences (Growth tier and up), with auto-routing of a new lead "to the right rep."
- **David – AI voice agent** — 24/7 inbound answering ("natural voice conversations, not robotic IVR"), speed-to-lead outbound calling on new leads, objection handling, months-long follow-up, and booking walkthroughs directly onto the calendar, then pushing qualified leads into the pipeline.
- **Contract generation** — "generate, send, and track contracts from the same screen"; conversation → signed agreement without leaving the app.
- **Skip-trace + DNC** — bulk skip-tracing (2.5k–10k/mo by tier) with results (phone, email, mailing address) auto-attached to the lead and cross-checked against DNC.
- **Dialer / texting** — built-in click-to-call and SMS on every contact.
- **KPI / activity dashboard** — real-time activity metrics, lead-source reporting, response tracking.

### The 5–8 features worth COPYING

1. **Seller-intent score with a "why" explanation, sorted to the top.** *What:* every property carries a 0–100 intent score AND a plain-language reason ("pre-foreclosure + 30yr owner + out-of-state"). *Why it helps:* the operator works a ranked list instead of eyeballing a table — the highest-probability call is always row 1. *FREE-to-build? Y.* We already have signal-stack chips and an intent slider; add a computed `intentScore` field + a `scoreReasons[]` array in listings.json, default-sort the table/cards by it, and render the reasons as the existing chips plus a one-line "why" caption. Pure client-side sort/derive.

2. **AI-ranked DAILY call list (a distinct "work today" view).** *What:* a separate top-N screen, not the full table — "here are today's 20 calls, in order." *Why:* removes decision fatigue; the operator opens one view and starts dialing top-down. *FREE-to-build? Y.* Add a "Today's Call List" tab that filters to top-N by intentScore (and de-prioritizes anything already contacted, read from our localStorage CRM-lite). No backend — it's a saved view over the same JSON.

3. **Time-stamped signal feed with trigger + timestamp + address.** *What:* a reverse-chronological "what changed" stream. *Why:* the freshness IS the edge in this space; a feed framing makes "new since yesterday" obvious. *FREE-to-build? Y (partial).* If listings.json carries a `signalDate`/`firstSeen` per signal, render a feed view sorted by date with a "NEW" badge for items whose date is within N days. The *hourly refresh* isn't copyable statically (see below), but the **feed presentation and new-item badging** are trivial and high-impact.

4. **Score-threshold filtering to "focus the team."** *What:* a slider/threshold that hides everything below score X. *Why:* lets the operator collapse a 5,000-row board to the 80 worth touching this week. *FREE-to-build? Y.* This is a numeric extension of our existing intent slider — one range input bound to `intentScore`.

5. **Stuck-deal / overdue-follow-up flagging in the pipeline.** *What:* pipeline auto-highlights deals with no activity in X days or a past-due next-step. *Why:* the leaks (leads going cold) are the whole point of a pipeline; passive Kanban doesn't surface them. *FREE-to-build? Y.* Our CRM-lite already stores stage + last-touched in localStorage; compute `daysSinceTouch` on render and paint the card red past a threshold, with an "Overdue" filter chip.

6. **Contact-level unified activity timeline.** *What:* one chronological thread per contact (notes, stage changes, "next step"). *Why:* the operator sees the whole relationship at a glance before calling. *FREE-to-build? Y (notes/steps only).* Extend CRM-lite: per-listing localStorage array of `{ts, type, text}` entries rendered as a timeline in the property-detail drawer. We can capture notes, stage changes, and manual "logged a call" entries — we just can't auto-capture the actual call/text/email (that's infra).

7. **Customizable saved pipeline stages (Kanban).** *What:* drag deals across named stages. *Why:* it's the mental model wholesalers already use; a board beats a status column. *FREE-to-build? Y.* A CSS-grid Kanban with HTML5 drag-drop, stage stored per-listing in localStorage. No server.

8. **"Upload your own list, we score it" framing.** *What:* bring your DB, get hot-vs-cold flags. *Why:* meets operators where their data already is. *FREE-to-build? Y (client-side CSV import).* Add a client-side CSV drop that parses in-browser, runs our same scoring function, and renders it in the same table — nothing leaves the browser.

### What genuinely requires a backend/vendor (can't do in a static site)

- **David / any AI voice agent** — inbound answering, outbound speed-to-lead calling, live objection handling. Needs telephony (Twilio/carrier), an LLM voice pipeline, and STIR/SHAKEN call registration. Not static.
- **Built-in dialer + SMS** — click-to-call and texting require a provisioned phone number, A2P 10DLC registration, and per-message/minute billing. Regulated infra.
- **Hourly county/court data refresh** — the "be first" freshness relies on a server-side crawl pipeline running around the clock. A static site can only show whatever was baked into the last listings.json build. (Our own scraper stack produces the JSON offline — that's the backend, just not hosted in the dashboard.)
- **Skip-tracing + DNC scrubbing** — resolving owner → phone/email requires a paid data vendor and a per-lookup API key that can't live in client JS. DNC checking is a licensed data feed.
- **Auto-routing to reps / ad-platform integrations (Google/Facebook/CallTools/ReadyMode)** — inbound webhooks and OAuth server-side.
- **Contract e-sign send/track** — generating a doc client-side is doable, but *sending for signature and tracking status* needs an e-sign vendor (DocuSign-class) and server state.
- **Cross-device/team-shared state** — Goliath's pipeline is multi-seat and syncs. Our localStorage CRM-lite is single-browser; true shared state needs a DB.

### Verdict: the single highest-value copy

**The seller-intent score with an inline "why they need a call" explanation, used to default-sort a dedicated daily call list.** It is the one thing that converts our flat, filterable table into an *action queue* — the operator stops hunting and just works row 1 downward — and it is almost entirely already in our wheelhouse (chips + slider + a computed score field + a sorted saved view), 100% free to build client-side. Everything genuinely differentiated beyond that (David, dialer, hourly refresh, skip-trace) is regulated/paid infrastructure, not UX we can mirror.

Sources: [goliathdata.com](https://goliathdata.com/), [Complete Guide to Wholesale Deal Tools](https://goliathdata.com/complete-guide-to-goliath-data-s-wholesale-deal-tools), [Pricing](https://goliathdata.com/pricing), [Data Pipelines product page](https://goliathdata.com/product/data-pipelines), [SoftwareAdvice – Goliath](https://www.softwareadvice.com/product/536319-Goliath/), [Capterra – Goliath](https://www.capterra.com/p/10035457/Goliath/)


## PropStream

### Screen-by-screen feature inventory

- **Market entry + search bar.** Operator types an address, APN, ZIP, city, or county to set the working geography. This is the gate for every downstream tool. County/city/ZIP scope loads the map + result grid; a single address opens Property Detail directly.
- **Map search + draw tool.** Interactive map with numbered pins; pins now surface estimated value, a photo, and property highlights on hover/tap without opening the record. A freehand **draw tool** lets you lasso an arbitrary polygon (neighborhood, subdivision, block) instead of relying on radius. **Heat-map overlays** recolor the map by value, foreclosure density, or rent. Pin numbers correspond 1:1 to rows in the list below.
- **Filter panel (165+ filters).** Left/side panel grouped into categories: property characteristics (beds/baths, sqft, lot, year built, type), valuation/equity (estimated value, equity %, LTV), mortgage/lien (loan type, lender, rate, position), owner (owner-occupied vs absentee, corporate/LLC/trust, ownership length, mailing-address mismatch), distress/legal status (foreclosure stage, tax delinquency, liens, bankruptcy), and MLS status (on/off market, days on market, failed listing). Filters are additive and stackable (e.g., "divorce + pre-foreclosure").
- **Quick Lists (20 pre-built lead lists).** One-click presets that pre-load filter bundles: Pre-Foreclosures, Auctions, Bank Owned, Bankruptcy, Tax Delinquent, Zombie Properties, Free & Clear, High Equity, Upside Down (negative equity), Divorce, Pre-Probate, Senior Owners, Cash Buyers, Flippers, Tired Landlords, Vacant, Vacant Land, On Market, Failed Listings.
- **Result grid ("My Properties" style table).** Sortable/columned list mirroring the map. Columns include owner, value, equity, and status flags. Far-right "activity" columns show membership state: which **Marketing Lists** a record is on, whether it's in a **Marketing Campaign**, and whether it was already mailed / emailed / skip-traced.
- **Property Detail page.** Full dossier per property: owner name(s) + mailing address, owner-occupancy flag, transaction/sale history, current mortgage(s) and lender, tax assessment records, foreclosure/lien/legal detail, and photos. Action buttons on this page: Save to list, Run Comps, view Opportunity/analysis, Skip Trace, and Send Postcard.
- **Comparables & ARV tool.** A "Comparables & Nearby Listings" tab. Opens with **preset comp criteria** (sold within 12 months, within 0.5 mi, ±20% sqft) and lets you adjust sale-date range, distance (including redrawing the comp area on a map), sqft tolerance, transaction type (cash/financed/active/pending/contingent), and data source (Public Record, MLS, or both). Presents avg sale price, avg $/sqft, and avg days-on-market; comps are individually selectable, savable/editable, and exportable to PDF.
- **List builder + list stacking.** Saved searches become named Marketing Lists. **Stacking** = sorting the "Marketing List" column descending so owners appearing on multiple lists float to the top (more lists = more motivation). Lists-within-lists and dedup/redundancy views live under Lead Automator.
- **Lead Automator (list monitoring/automation).** Auto-adds new records that match a saved search and auto-removes records that no longer qualify, keeping lists live. Handles dedup and cross-list stacking.
- **Skip trace (inline).** Button on the record / list; returns phones + emails for individuals, LLCs, corps, and trusts, with DNC and litigator flags attached.
- **Marketing / campaigns (PropStream Connect).** A campaign = a bundle of outreach actions toward a goal. Channels: direct mail/postcards (from ~48¢, template-based or upload-your-own), email (~2¢ each, open/click tracking), custom landing pages per campaign, and Click-to-Dial + bulk Dialer Campaigns with softphone, AI-guided prompts, call notes, connection tracking, and team assignment.
- **KPI / campaign dashboard.** Single view of calls made/connected, emails sent + open/click rates, and postcard delivery, plus per-campaign result analysis.
- **Built-in calculators.** Rental cash-flow, fix-&-flip, rehab estimator, ADU, and financing (LoanGeek).
- **Mobile / Driving-for-Dollars.** Bottom-center Drive icon → "Set Filters and Drive" (apply radius + filters, matching pins appear on map + list) or "Just Drive" (freestyle route with live GPS trail, tap any house to open its detail, save, comp, skip trace, or postcard on the spot). Optional drive recording saved to a Drive Log (24h / 7d / 30d / all) showing distance, time, and stops. "Free Scout" mode for quick lookups.

### The 5–8 features worth COPYING

1. **Quick Lists (one-click filter presets).** *What:* named buttons that instantly apply a distress/equity/life-event filter bundle. *Why:* an operator gets a usable target list in one click instead of hand-tuning filters. *Free-to-build? YES* — our records already carry the signal fields; define each preset as a saved filter object (a JSON of field predicates) and render them as chips. Our signal-stack already maps to these (pre-foreclosure, tax-delinquent, vacant, absentee, high-equity, probate/elderly), so this is mostly UI wiring over data we have.

2. **Draw-on-map polygon filter.** *What:* lasso an arbitrary area; results = only points inside. *Why:* neighborhood/farm-area targeting beats county-wide noise. *Free-to-build? YES* — Leaflet/MapLibre + Leaflet.draw (or Turf.js `booleanPointInPolygon`) client-side against the listings GeoJSON; no backend.

3. **Activity/status columns + list stacking by count.** *What:* per-record flags for which lists it's on and whether it's been contacted, with a "on how many lists" sort. *Why:* multi-list overlap is the single best motivation proxy, and contacted-flags prevent double-touch. *Free-to-build? YES* — compute an overlap count across our signal-stack chips and store per-record contact/list membership in localStorage (our CRM-lite already does this); expose a sortable "signals count" column, which is exactly stacking.

4. **Property Detail dossier with action buttons.** *What:* one page consolidating owner, mortgage, tax, transaction history, photos + Save/Comp/Skip/Mail actions. *Why:* the operator decides and acts without tab-hopping. *Free-to-build? PARTIAL-YES* — the consolidated read-only dossier is fully free (render every field we hold in listings.json in a detail modal/card); the action buttons that *transact* (skip, mail) are not (see below), but "Save/tag/add-to-list" is free via localStorage.

5. **Comps panel with adjustable criteria + $/sqft ARV.** *What:* nearby solds filtered by distance/sqft/recency, showing avg $/sqft and a derived value. *Why:* instant sanity-check on value without leaving the tool. *Free-to-build? YES if we ship comp data in listings.json.* We already compute ARV/comps server-side (the repo's comp sidecar); surface it: a detail-panel comp table with client-side sliders (distance/sqft/date) that recompute avg $/sqft × subject sqft live in JS. No live comp *pull* needed — read the pre-baked comps.

6. **Heat-map overlay toggle.** *What:* recolor the map by value/distress/rent. *Why:* spot pockets at a glance. *Free-to-build? YES* — a MapLibre choropleth/heat layer keyed off fields already in the JSON; a simple toggle control.

7. **Campaign/KPI dashboard (counts + statuses).** *What:* a strip summarizing list sizes, contacted vs not, by stage/source. *Why:* operator sees pipeline health at a glance. *Free-to-build? YES* — pure aggregation over the listings + localStorage CRM state; render as scorecards + a small chart.

8. **Driving-for-Dollars route view (mobile).** *What:* GPS trail + tap-a-pin-to-act while driving. *Why:* field prospecting flows straight into the list. *Free-to-build? PARTIAL* — a responsive map that uses the browser `geolocation` API to show "you are here" + nearest listings and let you tag one is free and works on a phone browser; persistent turn-by-turn route *recording* across sessions is weak without a backend but can be faked with localStorage for a single session.

### What genuinely requires a backend/vendor (can't do in a static site)

- **Skip tracing** (phone/email append, DNC + litigator scrubbing) — a paid data vendor + server call; illegal/impractical client-side.
- **Sending direct mail, email, and the dialer/softphone** — requires print-mail API, email-send infra with tracking pixels, and telephony (softphone/dialer) — all server + paid.
- **Landing pages that capture leads** — need a form endpoint + storage.
- **Live/continuously-refreshed data + Lead Automator auto-add/remove** — requires a crawling/ETL backend feeding the dataset on a schedule; our JSON is a static snapshot regenerated out-of-band.
- **Live comp/MLS pulls** — MLS/public-record comp data behind licensing; we can only ship pre-baked comps, not query on demand.
- **Cross-device shared team CRM** (assignment, shared notes) — localStorage is single-browser; true multi-user needs a DB + auth.

### Verdict: the single highest-value copy

**Quick Lists rendered as filter-preset chips, wired to a list-stacking "signals count" sort.** It's the core of PropStream's value proposition (turn a raw database into ranked motivated-seller lists in one click), it maps directly onto data and chips we already have, and it's 100% free to build in the static dashboard. Pairing one-click distress/equity/life-event presets with a sortable overlap-count column reproduces the exact workflow operators pay PropStream for — everything else (skip, mail, dialer, live refresh) is vendor-gated and out of scope for a static site.

Sources: [PropStream Features](https://www.propstream.com/propstream-features), [Campaigns](https://www.propstream.com/campaigns), [How to Run Comps](https://www.propstream.com/how-to-run-comps-in-propstream), [List Stacking with Lead Automator](https://www.propstream.com/list-stacking-with-list-automator), [Manage Lists / Dedup](https://www.propstream.com/how-to-manage-your-lists-identify-duplicates-redundancies), [Driving for Dollars (Mobile)](https://www.propstream.com/driving-for-dollars-propstream-mobile), [Using the Drive function](https://www.propstream.com/using-the-drive-function-within-propstream-mobile), [Capterra](https://www.capterra.com/p/207196/PropStream/), [ReSimpli PropStream Review](https://resimpli.com/blog/propstream-review/)


## PropertyRadar

### Screen-by-screen feature inventory

**Discover (search + criteria builder)** — Top-nav "Discover" opens a full-screen search. Left side is the **Add Criteria panel** with three entry paths: (1) **Quick Lists** (drill-down category tree), (2) a **Find Criteria** text box searching 250+/285+ criteria across categories (Location, Property, Owner, Value & Equity, Property Tax, Loans & Liens, Foreclosure, Transfer, Listing, My Data, Criteria from My Lists), (3) manual category browse. Selected criteria render as chips in a **criteria bar**; a **property count** sits to the right and updates live. A **Signal bar** shows record counts for the top-matching criteria in real time. **Radar AI** ("List-Building Assistant") is a chat box: describe the ideal prospect in plain English and it generates and applies the criteria set.

**Map** — Search results render on a map with **draw tools** (polygon, box/rectangle, radius circle, or whole-map). Satellite/topography basemaps and heatmaps. Toggle between **Map / Grid / Card / Split** views. Geography can also be entered by city/county/ZIP with autocomplete.

**Property & Owner Profile** — Blue address header with street-view thumbnail + interactive map (expandable to Street View / Bird's Eye), plus an **interest-level star rating**. Below: three **highlight cards** (Property: type/year/beds/baths/sqft/lot + status icons; Value: AVM/equity/purchase price/tenure; Contacts: owner names/ages/professions + phone/email availability icons + social links). Seven tabs: **Contacts** (phone status icons — green=active, yellow=opted-out/wrong/disconnected — plus skip trace), **Property** (Location/Site/Structure/Property Taxes with links to county assessor/tax sites and parcel maps), **Value & Equity** (valuation, **comparables** filterable For-Sale vs Recent-Sales, and an interactive **flip/hold investment analysis** tool), **Transactions** (current-owner vs all transactions, foreclosure docs, title checklist), **Listings** (aggregated with Zillow/Realtor/Redfin quick-links), **Neighborhood** (demographics, housing, housing risk, environment, neighbors at ZIP/county/state/national), **My Info** (photos/notes/files). Right rail: **My Lists** membership, editable **Status** pipeline labels, and an **Activities timeline** logging views, status changes, email opens, and mailing outcomes.

**Comps / valuation** — Lives inside the Value & Equity tab (not a standalone screen): AVM, market value, market rent, filterable comparables, and the flip/hold analyzer.

**List builder / stacking** — "Make List" from a search saves criteria as a **Dynamic List** (auto-refreshes as records change). Lists can be **created, refined, stacked, and excluded** against each other, and **segmented**. Import/match/append lets you upload CRM/spreadsheet exports, auto-match, and append missing phones/emails.

**Skip-in-line / contact append** — No separate skip-trace vendor; phone/email icons on the Contacts card/tab are click-to-purchase per contact, or auto-appended in bulk via automations. Owner research resolves the real human behind LLCs/trusts.

**Monitoring + Alerts (the differentiator — detail below)** — "Add Monitoring" on any list; drives new-match/status-change detection, notifications, and automations.

**Campaigns / marketing** — Direct mail (postcards, next-business-day, no minimums), email/SMS/phone from built-in contact data, online display ads (ESPN/Forbes inventory), and **multi-channel sequences** with AI-personalized copy/timing.

**CRM / pipeline** — Custom **Status** stages, **interest-level stars**, activity logging (calls/emails/notes/visits), property & owner **change history**, document storage, and **Kanban workflow boards** that trigger steps on property events.

**Dialer** — No native dialer; phone is handled via click-to-call from mobile + dialer integrations over Zapier/webhooks.

**KPI dashboard** — **Insights** analytics unlocked by monitoring (list composition, new-since counts, portfolio changes).

**Alerts/monitoring** — see below.

**Mobile / D4D** — Mobile app for on-site property/owner lookup, click-to-call/email/postcard, **address scanner**, **Drive for Dollars route planning with team tracking**, visit logging, and push notifications.

### The 5–8 features worth COPYING

1. **Quick Lists as a starting point, not a cage** — one click applies a named preset (Absentee Owner, High Equity >30%, Free & Clear, Vacant, Tired Landlord, Pre-Foreclosure, Zombie Foreclosure, Out-of-State Owner, Pre-Probate, Cash Buyer, etc.) that then remains fully editable. Why it helps: operators don't have to know which raw fields to combine; they pick an intent and refine. **FREE-to-build? Y** — hardcode a dozen named filter presets as JSON objects (`{name, description, filterState}`); clicking one hydrates your existing filter UI. Keep them editable afterward (don't lock the controls). This is the single easiest high-leverage copy.

2. **Signal-count / live result counter on every criterion** — the count updates as you add/remove filters, and a signal bar shows how many records each top criterion would return. Why it helps: instant feedback on whether a list is too broad or empty before you commit. **FREE-to-build? Y** — you already load `listings.json` client-side; compute `filtered.length` on every filter change and show per-chip counts by test-applying each active filter in isolation.

3. **Interest-level star rating + custom Status pipeline on each record** — lightweight per-property triage (stars) plus editable pipeline stages (Prospect → Qualified → …). Why it helps: turns a flat list into a worked pipeline without a real CRM. **FREE-to-build? Y** — extend your localStorage CRM-lite with a `stars` (0–5) and `status` field per RadarID; render as clickable stars + a status dropdown; add a Kanban view that groups by status. No backend.

4. **Property profile with external quick-links + "purchase/reveal contact" pattern** — every profile deep-links to the county assessor, parcel map, Zillow/Realtor/Redfin, and Street View; contact icons show availability before you spend. Why it helps: one screen to triage + jump to authoritative sources; contact icons set expectations. **FREE-to-build? Y (links) / partial (contacts)** — build the card view into a detail modal with computed deep-links (assessor/GIS URL templates by county, Google Street View URL from lat/lng, Zillow search URL from address). The *reveal-a-phone* purchase step needs a data source, but showing a "has phone / has email" badge from whatever you already have in the JSON is free.

5. **Comparables toggle (For-Sale vs Recent-Sales) + flip/hold analyzer** — inline comps you can flip between listings and sold, plus a simple ARV/rehab/hold calculator. Why it helps: valuation lives next to the lead, no spreadsheet. **FREE-to-build? Y** — you already carry comps/ARV in the board sidecar; render a comps sub-table with a For-Sale/Sold toggle and a small client-side calculator (inputs: purchase, rehab, ARV, fees → max bid / ROI). Pure JS.

6. **"New Since" diff filter** — a date picker that shows only properties added to the list since a chosen date, with a new-count badge under the total. Why it helps: on every visit the operator sees only what changed. **FREE-to-build? Y (client-side approximation)** — stamp each row with a `first_seen` date when your JSON is regenerated (build-time), store the user's "last viewed" date in localStorage, and filter/badge on `first_seen > lastViewed`. Gives the same UX without a server.

7. **Kanban workflow board over the same records** — the list, a table, a map, and a board are all views of one dataset; the board triggers next-steps by stage. Why it helps: matches how operators actually work leads. **FREE-to-build? Y** — add a board view that reads the same filtered array grouped by your `status` field, with drag-to-change-status writing back to localStorage.

8. **CSV/record export + "send to Zapier/webhook" action in the row menu** — Why it helps: gets a lead out to the operator's tools in one click. **FREE-to-build? Partial** — CSV export you already have. A true webhook POST from a static site can't hold a secret, but you can offer a **"Copy as JSON" / mailto: / prefilled Zapier catch-hook URL** the user pastes their own hook into (stored in localStorage) — the browser `fetch`-POSTs to their endpoint. That's the free approximation of their Zapier export.

### What genuinely requires a backend / vendor

- **Real monitoring + scheduled re-crawl** — PropertyRadar re-runs each saved list's criteria against a nightly-updated 160M-property database, diffs it, and detects new matches and status changes. A static site has a frozen `listings.json`; true "watch this list and tell me when a new property qualifies" needs a server (or a scheduled job) re-fetching and diffing data. You can *approximate* it only across build regenerations (feature #6), not continuously.
- **Push / immediate-email / daily-summary alerts** — sending email or mobile push on a trigger requires a mail service, a push service, and a server holding credentials. Impossible from GitHub Pages.
- **Status-change event stream** (`Listing Status:Active:Pending`, new NOD/NTS, new loan, transfer) — requires ingesting the source data over time and computing field-level diffs server-side; the payload shape itself (field:old:new, up to 3 changes/event) is only meaningful with a persistent history store.
- **Contact append / skip trace** (buying phones/emails) — third-party paid data; no client-side path.
- **Direct mail, SMS, dialer, display ads** — all vendor-fulfilled (mail house, telephony, ad networks).
- **Signed webhooks / API with a secret** — the Webhook Secret and API key can't live in public JS.
- **Cross-device shared state** — their status/notes/interest sync across a team; localStorage is single-browser only. Team sync needs a backend.

### Verdict: the single highest-value copy

**Quick Lists** — named, one-click, intent-based filter presets that remain fully editable. It is trivial to build (a JSON array of filter states wired to your existing filter UI), and it collapses the entire "which of 285 criteria do I combine to find a tired absentee landlord with equity" problem into a single click. It is the feature that makes PropertyRadar feel powerful to non-expert operators, and it costs you nothing but a curated preset file. Pair it with the **live result counter (#2)** and the **interest-star + status pipeline (#3)** and your static dashboard reproduces ~80% of the perceived value of the paid discover-and-work-a-list loop; the only thing you structurally cannot copy is the *continuous* monitoring/alert engine, which is genuinely backend-bound.

Sources: [Features Overview](https://www.propertyradar.com/features-overview), [Making a List](https://help.propertyradar.com/en/articles/3066571-making-a-list-of-properties-and-property-owners), [Quick List Glossary](https://help.propertyradar.com/en/articles/2447514-quick-list-glossary-2007-2025), [Monitoring Lists](https://help.propertyradar.com/en/articles/5215475-monitoring-lists), [Creating Alerts and Automations](https://help.propertyradar.com/en/articles/3526088-creating-alerts-and-automations), [Automations for Email Marketing](https://help.propertyradar.com/en/articles/9118861-automations-for-email-marketing), [Property and Owner Profile](https://help.propertyradar.com/en/articles/5730803-using-the-property-and-owner-profile), [Working with Webhooks](https://help.propertyradar.com/en/articles/7117007-working-with-webhooks), [Data Available for Zapier and Webhooks](https://help.propertyradar.com/en/articles/3526061-data-available-for-zapier-and-webhooks-integrations), [Integrations](https://help.propertyradar.com/en/articles/6971590-integrations)


## BatchLeads + BatchData

### Screen-by-screen feature inventory

- **Search + Filters** — A geo-scoped property search (draw/type a zip, city, county, or APN) fronted by "130+ filters" grouped into ownership type (absentee, owner-occupied, out-of-state), distress signals (pre-foreclosure, tax-delinquent, code violation, liens, vacant, probate), physical (beds/baths/year built/lot/sqft), and financial (equity %, estimated value, mortgage). "1-click lead lists" are pre-built saved-filter templates. Output is a results table you save as a named List.
- **Map view** — Built-in map for geographic targeting with pins; drives the mobile canvassing workflow (below). Reviews confirm it exists but it's a thinner screen than the table.
- **Property detail page** — Owner details, mortgage info, equity %, property characteristics, APN/parcel insights, and tabbed sub-views. Tabs include **Comps**, **Lists and Tags** (which of your lists this property sits on), and skip-trace contact fields.
- **Comps tool** — A **"Comps" tab on the property detail page** (reachable from search, a saved list, or mid-text in the inbox). Adjustable filters: property type, sqft (±250), year built (±10), listing status = SOLD only, location/subdivision. It lists recently sold comparables and shows a live **"Estimated Value"** panel that recomputes ARV as you check/uncheck comps (avg $/sqft of selected comps × subject sqft). "Set filter defaults" saves your comp rules; export the comp set to PDF/Excel (emailed to you).
- **List-builder / stacking** — Lists live under **"My Lists."** Stacking is done by clicking **Filter** and dragging the **"List Count" / "Tag Count"** slider to 2+, which cross-references all saved lists and shows only properties appearing on ≥N lists. Results add **List Count** and **Tag Count** columns with sort arrows; any other filter layers on top.
- **Skip trace (in-app)** — One click on a list pulls phones, emails, and social profiles for owners. Included monthly credits (10k Basic / 20k Pro / 50k Enterprise). Same engine sold standalone as BatchSkipTracing and via the BatchData API.
- **Campaigns / marketing** — From a list you launch **SMS/text**, **direct-mail postcards**, and **ringless voicemail** without leaving the platform. SMS requires you to BYO carrier (Twilio/Plivo/SignalWire/Telnyx/Flowroute) and pay their per-message rates.
- **Dialer** — Built-in click-to-dial with live AI prompts and property data mid-call ("Dialer AI," $89/mo add-on); serious multi-line power-dialing pushes you to the separate **BatchDialer** product.
- **CRM / pipeline** — Manage conversations (a texting **inbox**), set follow-up tasks, and track deals through pipeline stages.
- **BatchRank (scoring)** — ML propensity score over ~800 data points (equity, tax delinquency, liens, ownership tenure), bucketed into **High / Medium / Low** tiers so you work "most-likely-to-sell now" instead of alphabetically.
- **KPI dashboard** — Light; reviews note there's no strong analytics layer beyond campaign/list counts.
- **Mobile / D4D** — "Canvassing" app for driving-for-dollars: drop pins on distressed/vacant properties in the field (or virtually via street view), auto-tag, and push straight into a list for skip-trace + outreach.
- **API split (BatchData)** — BatchData is API-first: `POST` **Property Search** (with a comps flag + aggregated-comparables metrics), **Property Skip Trace** (≤100 properties/call), and **BatchRank** scoring, all as REST endpoints. The pattern teams use: BatchLeads UI for the acquisition team's daily work; BatchData API for back-end bulk enrichment. Everything in the UI is a rendering of the same data the API exposes.

### The 5–8 features worth COPYING

1. **List-Count / Tag-Count slider for stacking** — *What:* one slider that filters the master board to properties present on ≥N signal lists; a sortable "signal count" column. *Why:* turns "which distress lists overlap" into a single ranking gesture — the core motivated-seller heuristic. *FREE-to-build? **Y.*** We already partially copied this. Finish it: derive a `stack_count` per row (count of true signal flags/source-lists), render it as a sortable column, and add a range-input slider bound to `stack_count >= N` that re-filters the table/map/cards client-side. Show the underlying matched signals in the detail drawer (their "Lists and Tags" tab).
2. **BatchRank High/Med/Low tiering on top of the raw score** — *What:* collapse a continuous propensity score into 3 labeled tiers with color. *Why:* operators triage by bucket faster than by a 0–100 number; buckets map cleanly to "call now / drip / ignore." *FREE-to-build? **Y** (heuristic, not their ML).* We can't replicate 800-point ML, but we can compute a transparent weighted score from the flags we already have (equity, tax-delinq, lien, pre-foreclosure, vacancy, absentee) and bin it into High/Med/Low chips. Our intent slider already gestures at this — expose the tiering as the default sort.
3. **"Set filter defaults" (saved views)** — *What:* persist a named set of filters/comp rules and reload instantly. *Why:* every operator re-runs the same 3–4 buy-box queries daily; re-selecting filters is friction. *FREE-to-build? **Y.*** Serialize the current filter state to a named entry in `localStorage` (same store as the CRM-lite), render a "Saved views" dropdown, write the active view into the URL hash so it's shareable/bookmarkable.
4. **Property-detail Comps tab with live ARV recompute** — *What:* pick SOLD comps, watch an Estimated Value panel recalc avg-$/sqft × subject sqft as you toggle each comp. *Why:* the "is this a deal?" moment happens inside the detail view, not a spreadsheet. *FREE-to-build? **Partial-Y.*** If `listings.json` already carries per-property comps/ARV (our pipeline computes ARV), render them in the detail drawer with checkboxes and a JS recompute of avg-$/sqft on toggle. Fully **N** only if we lack comp records — then it's a data problem, not a UI one.
5. **Export the current selection to CSV/PDF** — *What:* one button to email/download the working set. *Why:* hand-off to a VA, a mail house, or a partner. *FREE-to-build? **Y.*** CSV export we already have; add a "print to PDF" stylesheet (`@media print`) on the detail/comp view so the browser's Save-as-PDF produces a clean one-pager — no server.
6. **Texting inbox as the CRM surface (conversation-centric, not row-centric)** — *What:* the pipeline is organized around threaded conversations with the owner, with comps/property data pinned beside the thread. *Why:* keeps the operator in one context (talk + data) instead of tab-hopping. *FREE-to-build? **Partial-Y** (state only, not sending).* We can store per-property notes, status, next-action date, and a manual "contact log" in `localStorage` and render it in the detail drawer beside the property facts. Actually *sending* SMS is the backend part (see below).
7. **Driving-for-dollars pin-drop → auto-add-to-list** — *What:* in the field, tap a property to tag + enqueue it. *Why:* captures the highest-intent, human-verified distress signal (I physically saw the vacant house). *FREE-to-build? **Partial-Y.*** A static PWA page with the Geolocation API can center the map on the user and let them tap-to-flag a listing already in `listings.json`, writing a "field-verified" flag to `localStorage`. **N** for capturing net-new addresses off-map (needs a parcel lookup backend).

### What genuinely requires a backend / vendor
- **Skip tracing** — owner phone/email/social requires a paid data provider (BatchData/TLO-class); no free static path.
- **Actually sending** SMS, RVM, postcards, or dialing — needs carrier/Twilio, a mail vendor, and (for SMS) 10DLC registration. We can build the *compose/queue/log* UI; the send is backend.
- **The ML propensity model (true BatchRank)** — 800-point trained model over proprietary data; we can only approximate with a transparent weighted heuristic.
- **Live comps/AVM and fresh distress data** — if not already baked into `listings.json` at build time, on-demand comps/AVM refresh needs an API. (Our pipeline pre-bakes it, so this is fine as long as the JSON carries it.)
- **Real-time multi-user CRM sync** — `localStorage` is per-device/per-browser. Shared team pipeline, assignment, and permissions need a database + auth.

### Verdict: the single highest-value copy
**The List-Count/Tag-Count slider fused with a High/Med/Low tier chip.** It's the one thing BatchLeads does that directly converts "I have many distress lists" into "here are the 12 to call today," it's the exact concept we already partly built, and it is 100% free to finish in our static dashboard: compute `stack_count` and a transparent weighted `intent_score` per row, bin the score into three colored tiers as the default sort, and bind a slider to `stack_count >= N`. That single interaction is the core of what operators pay BatchLeads for, and we can own it entirely client-side.

Sources: [BatchLeads list-stacking help doc](https://help.getbatch.co/en/articles/9787321-how-to-list-stack-why-it-s-important), [How to Comp & Evaluate in BatchLeads](https://batchleads.io/blog/how-to-comp-evaluate-properties-using-batchleads), [BatchRank FAQ](https://help.batchservice.com/en/articles/10968831-batchrank-faq-and-details), [BatchRank vs Lead Lists](https://batchdata.io/blog/batchrank-vs-traditional-lead-lists-data-driven-comparison), [RealEstateSkills BatchLeads review](https://www.realestateskills.com/blog/batch-leads-review), [DealflowAIStack BatchLeads review](https://dealflowaistack.com/batchleads-review/), [BatchData Property Search API](https://developer.batchdata.com/docs/batchdata/batchdata-v1/operations/create-a-property-search), [BatchData Property Skip Trace API](https://developer.batchdata.com/docs/batchdata/batchdata-v1/operations/create-a-property-skip-trace), [BatchLeads homepage](https://batchleads.io/).


## DealMachine

### Screen-by-screen feature inventory

- **Map / Driving screen (mobile + desktop "Virtual D4D")** — Full-screen map with property pins. Pins are label-configurable (Address #, Owner Last Name, Owner Full Name, Equity %, Sale Price, or Estimated Value). Pre-drive you apply Quick Filters (vacant, absentee, tax-delinquent, high-equity, etc.) so target houses highlight before you leave. On desktop the same map supports "Virtual Driving for Dollars" — drag Street View / satellite around a neighborhood and pin houses from your desk.
- **Route Tracking (mobile-first; visible on desktop map)** — Start Drive / End Drive buttons record a GPS breadcrumb, mileage, hours, and every property added on that run. Recorded routes overlay the map color-coded by age (green = last 6 mo, yellow = 6–12 mo, red = 1–2 yr) so a team never re-drives the same streets. All members' routes stack on one map for coverage visibility.
- **Camera capture → instant lead (mobile-only)** — Snap a photo of a distressed house; the app geolocates it, pulls county/tax records, and creates a lead with owner name + mailing address in seconds. The photo is retained and can be dropped onto a postcard.
- **Property / Lead Card (both)** — The detail screen holds owner history, mortgage info, equity, estimated value, tax status, and the photo, plus tabs into deal analysis, the Comps tool, and a full activity log. Action buttons: add tag, set status, assign owner, add task/note, skip/reveal contact, start mail, call.
- **Owner contact reveal / "Unlimited Contact Info" + Private Investigator tool (both)** — Reveals phones, emails, and relatives/associated contacts, with a confidence indicator (blue/green/gray checkmarks) for match likelihood, plus demographics (age, marital status, income estimate, occupation).
- **List Builder (desktop)** — Query a 150M+ property database with 70+ prebuilt Quick Filters and 700 filters / 287 exportable fields (cash buyers, free-and-clear, tax-delinquent, recently sold, high-equity, absentee). Daily county-record refresh. Save as reusable lists.
- **AI Vision Builder (desktop)** — Scores every property in a drawn area from satellite + Street View imagery and auto-adds high-scoring ones to a list.
- **List Stacking (desktop)** — Overlays multiple saved lists; a **stack count** on each lead shows how many lists it appears on, surfacing the most-motivated prospects.
- **Comps tool (both)** — Recently-sold comparables for valuation, opened from the lead card.
- **Mail Center / Mail Sequences (desktop)** — Template gallery (or custom / handwritten with property photo). Sequences send postcards at scheduled intervals with automated follow-up. Mail Queue = today's scheduled pieces; Calendar = past + upcoming pieces. Preview each piece before it mails.
- **CRM / Pipeline (both)** — Status pipeline: New Prospect → With Marketing → Warm → Hot → Appointment Set → Under Contract → Won / Lost / Not Interested / Unqualified. Plus tags, tasks, reminders, notes, and lead-owner assignment.
- **AI Dialer "Alma" (both, telephony-backed)** — Outbound calling with local-presence numbers (area-code match), live transcription, AI-suggested responses mid-call, AI voicemail drop (voice-cloned), and an intelligent follow-up queue that re-sorts leads by call outcome + sentiment.
- **Team / route assignment (both)** — Assign territories and lead ownership; owner drives marketing + follow-up; all routes and statuses visible team-wide.

**Mobile-only:** camera capture, GPS Start/End Drive route recording. **Desktop-only:** List Builder, AI Vision Builder, List Stacking, Mail Center authoring. **Both:** map, lead card, comps, contact reveal, CRM pipeline, dialer, Virtual D4D.

### The 5–8 features worth COPYING

1. **Configurable pin labels (Owner / Equity% / Est. Value on the map marker).** What it does: lets the operator read the single most decision-relevant number without opening a card. Why it helps: triage at a glance across dozens of pins. **FREE-to-build: Y** — our map already has markers; add a small dropdown that swaps the marker label/tooltip field, driven by a field-picker over listings.json.
2. **Quick Filters as one-tap saved chips (vacant / absentee / high-equity / tax-delinquent).** What it does: collapses a multi-field filter into a single named button. Why it helps: operators re-run the same 4–5 segments constantly; chips remove the setup tax. **FREE-to-build: Y** — presets are just saved filter objects; render them as chips beside our existing filter UI, persist custom ones in localStorage.
3. **List Stacking with a visible stack-count badge.** What it does: counts how many signal-lists/sources a property hits and surfaces the overlap. Why it helps: multi-signal properties are the highest-intent leads — this is exactly our "signal-stack" thesis made visual. **FREE-to-build: Y** — we already have signal-stack chips; compute a count from the signal array and show a numeric badge + a "sort by stack count" option. This is the cheapest, most on-strategy copy.
4. **Route/coverage recency color-coding (green/yellow/red by age).** What it does: encodes freshness as color so stale territory is obvious. Why it helps: prevents re-working cold leads. **FREE-to-build: Y** — color pins/rows by a date field (e.g., days since listing/first-seen) using a 3-band scale; pure CSS on existing data.
5. **Lead card status pipeline + tags + notes (CRM-lite).** What it does: moves a lead through named stages with attached tasks/notes. Why it helps: turns a list into a workflow the operator actually works. **FREE-to-build: Y** — we already have CRM-lite via localStorage; add a status enum, tag array, and note field per record keyed by property id, with a Kanban/filter-by-status view.
6. **Confidence indicator on contact/skip data (blue/green/gray).** What it does: shows match likelihood before the operator trusts a number. Why it helps: saves wasted dials on bad matches. **FREE-to-build: Y (partial)** — if our data has any match-quality/score field we render a colored dot; if we only have presence/absence, a 2-state chip still helps. (Generating the confidence itself is backend — see below.)
7. **Deal-analysis mini-panel on the card (equity = value − payoff, at-a-glance).** What it does: shows the money math inline. Why it helps: operator decides go/no-go without a spreadsheet. **FREE-to-build: Y** — compute from fields already in listings.json (ARV/est value − payoff/liens) and render a small readout on each card.
8. **Mail-piece / outreach preview before send.** What it does: renders the postcard with the property photo/owner merge fields. Why it helps: catches merge errors, builds trust in the send. **FREE-to-build: Y (preview only)** — an HTML template that merges the selected record's fields into a printable card view; export/print is free. Actual mailing is backend.

### What genuinely requires a backend / vendor (can't do in a static site)

- **Live skip trace / "unlimited contact info" + Private Investigator lookups** — needs a paid data vendor and a server to hold the API key; can't ship keys in a static bundle.
- **The 150M-property List Builder with daily county refresh** — a hosted database + ingestion pipeline; our static file is a snapshot, not a queryable national DB.
- **AI Vision Builder scoring** — server-side calls to satellite/Street View imagery + an ML model.
- **The AI Dialer end-to-end** — telephony (Twilio-class), local-presence number pool, live transcription, AI voicemail/voice-clone, sentiment routing. All server + vendor.
- **Actually sending direct mail on a schedule** — a print-and-mail vendor + scheduler/queue (Mail Queue/Calendar). We can build the preview and the CSV/merge; we can't mail.
- **Real GPS route recording + multi-user shared coverage map** — needs a mobile app with background location and a shared backend to sync team routes.
- **Comps generation from live sold data** — pulling fresh comparables is a data-feed/backend job; we can only display comps already baked into the JSON.

### Verdict: single highest-value copy

**List Stacking with a visible stack-count badge (plus sort-by-stack-count).** It is the one DealMachine pattern that is both free to build on our existing signal-stack chips and directly advances our core value prop — surfacing multi-signal, highest-intent properties. It costs a few lines (count the signals array, render a badge, add a sort key) and gives operators the same "focus on the most-motivated leads first" behavior that DealMachine charges for.

Sources: [DealMachine Features (help)](https://help.dealmachine.com/en/articles/10856855-dealmachine-features), [DealMachine Glossary (help)](https://help.dealmachine.com/en/articles/10829341-dealmachine-glossary), [DealMachine Dialer FAQ](https://help.dealmachine.com/en/articles/9400361-dealmachine-dialer-faq), [App Store listing](https://apps.apple.com/us/app/dealmachine-for-real-estate/id1136936300), [DealFlow AI review](https://dealflowaistack.com/dealmachine-review/), [ListWithClever review](https://listwithclever.com/dealmachine-reviews-driving-for-dollars-app/), [ResiMpli review](https://resimpli.com/blog/dealmachine-review/)


## REsimpli

REsimpli is the "all-in-one operating system" for real-estate wholesalers/investors: it fuses the lead CRM, a built-in phone system (dialer/SMS/RVM), list-pulling + list-stacking, driving-for-dollars, direct mail, skip tracing, cash-buyer management, drip automation, and — its actual differentiator — a Plaid-fed accounting layer that auto-computes cost-per-lead and cost-per-deal **by marketing channel**, so ROI attribution lives inside the CRM instead of QuickBooks.

### Screen-by-screen feature inventory

- **Lead list / search + filters (List Builder):** Pull lists with filters like absentee-owner, equity %, ownership date, vacancy, years-of-ownership. Leads are taggable by source, tag, and stage. This is REsimpli's data-acquisition front door (not just a filter over existing rows).
- **List-stacking screen:** Upload multiple lists; the tool cross-references them and flags properties that appear on 2+ lists (a stack count / motivation score), surfacing the highest-overlap sellers and de-duping. Reviewers describe uploading batches and getting overlooked properties flagged "within minutes."
- **Lead pipeline board:** Kanban with drag-and-drop stages (New Lead → Contacted → Qualified → Offer Made → Under Contract → Closed). Cards show notes, call logs, full contact history. Moving a card auto-generates task assignments tied to the new status.
- **Lead detail / property profile:** One page per property/owner with history, tags, notes, and inline action buttons — call, text, drop RVM, skip trace, or send a direct-mail piece right from the profile.
- **Dispo pipeline:** A separate contract-to-close disposition workflow (its own stages) plus **cash-buyer management** — a segmented buyer database you can text-blast by group.
- **Dialer / SMS / RVM:** Built-in phone system (5 free numbers on base plans), call from browser or mobile, auto call-recording, outcome logging, templated + custom SMS, ringless voicemail. Numbers can be assigned per campaign (this is what powers channel attribution downstream).
- **Driving-for-dollars (mobile/D4D):** Field app to drop a pin, snap photos, log owner info, and fire off a direct-mail piece to that address on the spot; everything syncs into the CRM.
- **Direct mail:** 90+ built-in postcard/letter templates, send single pieces or campaigns; used both from D4D and from drip sequences.
- **Skip tracing:** Pay-as-you-go, runs from the lead profile, returns phones/emails/addresses in seconds.
- **Automation / drip campaigns:** Visual sequence builder with conditional logic that triggers SMS, email, RVM, direct mail, and task reminders based on lead response. Plus 9 built-in "AI Agents" (appointment-setting, follow-up, voicemail).
- **KPI dashboard:** Real-time cards for leads-per-source, conversion rate, cost-per-lead, cost-per-deal, revenue by channel, open offers/purchases, outstanding tasks, plus a **team leaderboard** (calls made, appointments, offers, revenue per rep). Reviewers report seeing "$2,500 in marketing costs, $15,000 in revenue" laid out at a glance.
- **Accounting layer:** Plaid bank sync imports all transactions; auto-tags some by bank data, user tags the rest by marketing channel (direct mail / PPC / radio / cold-call) and by property; generates income statements by category (marketing, legal, office, general).

### The 5–8 features worth COPYING

1. **List-stacking with a visible stack-count / motivation chip.** *What:* rank each property by how many of your source lists it appears on. *Why:* stack count is the single best free motivation proxy — highest-overlap = call first. *FREE-to-build? Y.* You already have signal-stack chips; add a computed `stack_count` (or overlap-of-source-tags) field to listings.json and a sortable "Stack" column + a chip that renders the count. Pure client-side sort/derive.
2. **Marketing ROI-by-channel/list table (their crown jewel, minus the bank feed).** *What:* a grid with one row per source/list showing spend, leads, cost-per-lead (spend÷leads), deals, cost-per-deal (spend÷deals), revenue, ROI. *Why:* it tells the operator which list to buy more of — the highest-leverage decision they make. *FREE-to-build? Y (partially).* You can't auto-pull bank spend statically, but you can add a small editable "channel spend" JSON (or a localStorage-entered spend-per-source) and compute CPL/CPD/ROI live in a table, since your data already carries a `source` per listing. The math is division; the only thing you can't automate is the spend number — take it as a manual input.
3. **Cost-per-lead / cost-per-deal as headline scorecards.** *What:* big KPI cards (CPL, CPD, deals, revenue) at top of dashboard. *Why:* gives the "where do I stand" glance REsimpli sells hardest. *FREE-to-build? Y.* Derive from your listings (count by source/stage) + the manual spend input above; render as scorecard tiles. No backend.
4. **Pipeline stages with drag-and-drop (CRM-lite → CRM board).** *What:* Kanban of leads by stage. *Why:* turns your CRM-lite localStorage notes into an actual pipeline operators live in. *FREE-to-build? Y.* You already persist per-listing state in localStorage; add a `stage` field and a board view (columns = stages, cards = listings) with HTML5 drag-drop writing stage back to localStorage. No server.
5. **Per-lead action panel on the property detail (call/text/mail buttons).** *What:* one-click outreach from the detail view. *Why:* collapses the "find lead → go do something" gap. *FREE-to-build? Y (as deep links).* You can't host a dialer, but you can render `tel:`, `sms:`, and a mailto/skip-trace-search link, plus a "copy mail-merge address block" button. Static, zero cost, 80% of the felt value.
6. **Source/tag-driven saved views + segment filters.** *What:* filter and save "absentee + high-equity" style segments. *Why:* operators work segments, not the whole list. *FREE-to-build? Y.* Encode active filters into the URL hash (shareable, bookmarkable) and/or localStorage "saved views." Pure front-end.
7. **Team-leaderboard-style activity counters (single-operator version).** *What:* counts of contacted / appointments-set / offers / closed. *Why:* progress visibility drives behavior. *FREE-to-build? Y.* Aggregate the localStorage stage/CRM data into count tiles. (Multi-user leaderboards need a backend — the solo counter does not.)
8. **CSV round-trip for spend + notes (import back, not just export).** *What:* let the operator maintain spend-by-list and lead notes in a sheet and re-import. *Why:* sidesteps the missing backend for the one thing they must key in (spend). *FREE-to-build? Y.* Add a CSV/JSON import that merges a `source,spend` file into the ROI calc and hydrates localStorage.

### What genuinely requires a backend / vendor

- **Plaid bank-account sync and auto-transaction categorization** — needs OAuth, a server to hold tokens, and Plaid's paid API. The *ROI math* is free; the *automatic spend capture* is not. (Manual spend entry is the free substitute.)
- **Built-in dialer, call recording, SMS, and ringless voicemail** — requires Twilio-class telephony, server-side webhooks, and per-message billing. Static sites can only launch `tel:`/`sms:` handoffs, not run the phone system or log call outcomes.
- **Skip tracing** — proprietary paid data (phones/emails behind a per-hit API). Not derivable in-browser; best you do is a deep-link out to a search.
- **Direct-mail send + templates + tracking** — a print/mail vendor and fulfillment backend. Free version = generate a printable/mail-merge address block, not actually mail it.
- **Automation / drip sequences and AI agents** — need a scheduler, server-side timers, and message-sending infra; a static page can't fire timed SMS/RVM/mail.
- **Cross-device / multi-user shared state** (real pipeline shared by a team, team leaderboard) — localStorage is per-browser; genuine multi-user needs a database + auth.

### Verdict: the single highest-value copy

**The marketing ROI-by-list/channel table with derived cost-per-lead and cost-per-deal.** It's REsimpli's genuine differentiator and the highest-leverage screen for an operator (it decides where the next marketing dollar goes), yet 90% of it is free to rebuild in a static dashboard: you already carry a `source` per listing, so the only missing input is spend-per-source — take that as a small manual/CSV-entered number and compute CPL, CPD, and ROI entirely client-side. You copy the decision-making value of their "accounting layer" while skipping the one paid dependency (Plaid) that isn't actually where the value lives.


---

# Deep-Dive Round 13 — Per-Distress-Source Conversion Playbook (2026-07-02)


## Probate / Inherited Property

### Owner psychology & situation (what they're actually feeling/needing)
The person you reach almost never says "I own a house." They say "I'm dealing with my mom's house." That distinction is the whole game. Emotionally they sit somewhere on a spectrum from raw grief to quiet relief to open resentment (the sibling who got stuck as executor and is doing all the work). What they share is **overwhelm plus friction**: the house is 200 miles away, it's full of 40 years of belongings, there's a sibling who "wants to keep it" but won't pay the taxes, the HVAC just died, and probate has to close before anyone can touch the money. They are not motivated by price the way a foreclosure owner is motivated by a deadline. They are motivated by **removal of hassle** and **fairness among heirs**.

Key sub-situations that change everything:
- **Executor / Personal Representative (PR)** is the only person with legal authority to sell before the estate closes. Talk to the wrong heir and you waste a month. In NC and SC the PR is named in the letters testamentary / letters of administration.
- **Multiple heirs** = you are negotiating a group decision, often across states, often with old family tension. The "as-is, everyone gets a clean equal check, no one has to manage anything" frame is your leverage.
- **Out-of-state heirs** are your single best segment. They cannot easily maintain, clean out, or show the property, they're paying to carry it, and a local buyer who "handles everything" is a genuine gift, not an intrusion.
- **Vacant + full of stuff** is the universal pain. "You keep what matters, we handle the rest, nothing goes to the dump that you'd want" is the most repeated winning line among probate-specialist wholesalers (per BiggerPockets probate threads and the Sharon Vornholt / "Louisville Gals" probate REI material).

### Best channel + TIMING (mail/call/text/door; how soon after the trigger; how many touches)
**Channel priority: Mail first, then phone, then a soft second letter. Door-knocking is for the local vacant house only, and even then gently. Cold texting is the weakest and riskiest channel here (consent + tone).**

**Timing — the real debate, resolved:** The seasoned probate-mail operators (this is the consistent view across BiggerPockets probate investing threads, the All The Leads / Chad Corbett training, and Sharon Vornholt's probate content) land on **do NOT hit them in the first ~30 days**, and do NOT wait until the estate is long closed either. The sweet spot is roughly **30–120 days after the filing/appointment of the PR**. Why:
- Before ~30 days the family is in funeral-and-shock mode; a "buy your house" letter reads as vulture behavior and burns the lead.
- By 30–90 days the practical pain has arrived: the carrying costs, the cleanout, the sibling coordination, the "why is this dragging on."
- Probate itself takes months (NC and SC both run several months to over a year), so you are almost always contacting a live, still-open estate. You are early to the *pain*, not early to the *grief*.

**Cadence:** This is a **long, low-frequency, high-respect** sequence, not a 9-touch blitz.
- Touch 1: Letter at ~day 45–60 (handwritten-style, not a postcard, not "CASH FOR HOUSES").
- Touch 2: Follow-up letter at ~day 90 if no response.
- Touch 3: A single, calm phone call *if* you have a good number and only if you can be genuinely soft. Many probate closers actually prefer to let the mail pull the inbound call, because a warm inbound probate lead converts far better than a cold outbound one.
- Optional Touch 4: A final "I'm still here whenever you're ready, no pressure" letter around day 150. Then stop and recycle to a light quarterly list.

Postcards underperform letters badly here. This is a letter game.

### The actual pitch / message (a real script skeleton)

**Letter (the workhorse). Plain, personal, no urgency language.**

> Dear [First Name],
>
> I'm sorry for the loss of [Mr./Mrs. Last Name — or "your loved one" if unsure]. I know this is a hard time and the last thing you probably want is one more thing to deal with.
>
> My name is [Name], and I'm a local buyer here in [Greenville / Asheville / county]. I help families who've inherited a house decide what to do with it — whether that's selling it as-is with nothing to fix or clean out, on a timeline that works for the estate.
>
> If keeping the house is right for your family, that's genuinely the best outcome and I hope you do. But if it's become a burden — taxes, upkeep, a house full of belongings, siblings in different states trying to coordinate — I can buy it in its current condition, handle the cleanout, and close whenever the estate is ready.
>
> There's no cost, no obligation, and no pressure. If it would help just to talk through your options, my direct number is [number].
>
> With sympathy,
> [Name]

**Phone opening (inbound or a soft outbound). Lead with empathy, not the offer.**

> "Hi [Name], thanks for calling — first, I'm really sorry about your [mother/father]. Before anything about the house, how are you and the family holding up with everything?"
> [Listen. Actually listen. Do not pivot to the house until they do.]
> "It sounds like a lot to carry. Can I ask — where are things with the estate right now? Are you the personal representative, or is someone else handling that side?"
> [This surfaces authority + timeline.]
> **Value frame:** "Here's the only thing I do that's different: you don't fix anything, you don't clean anything out, you don't list it or do showings, and you don't pay a commission. Whatever's in the house, you take what matters to the family and I handle the rest. We close when the estate lets us, not on my clock."
> **The ask (soft):** "Would it be helpful if I took a look and gave you a fair as-is number, just so you and your siblings have a real option on the table? No commitment either way."

The winning value frame in one sentence, used by essentially every probate specialist: **"As-is, no cleanout, no commission, close on the estate's timeline, and a clean equal check for every heir."**

### Top objections + responses

- **"It's too soon, we just lost her."** → "I completely understand, and I'm sorry — I didn't mean to rush you. There's no timeline on my end at all. Would it be alright if I left you my number and you reach out whenever the family is ready, even if that's months from now?" (Then honor it. This restraint is what converts them later.)
- **"We're keeping it / a sibling wants it."** → "That's great, honestly — a family home is worth keeping if you can. If the numbers ever stop working, or if not everyone's on the same page down the road, I'm here. No hard feelings." (Leave the door open; ~a third of "we're keeping it" probate houses come back to market.)
- **"I can't sell yet, probate isn't done."** → "That's normal — most of the houses I buy are still in probate. I work on the estate's schedule, and I can even wait for the letters/authority to be finalized before we close. We can agree on price now and let the legal side catch up."
- **"How do I know your offer is fair?"** → "Fair question. I'll walk you through exactly how I got the number — recent nearby sales and what it'd cost to bring it up to retail condition. And you're free to get a second opinion or a realtor's number to compare. I'd rather you feel good about it than feel pushed."
- **"We're just going to list it with an agent."** → "That can absolutely be the right move if the house is in good shape and the family has time to handle showings and a cleanout. Where I tend to help is when the house needs work, it's full, or the heirs are spread out and just want it done. If that's not you, an agent's a great choice." (Never trash agents to a grieving family — it reads badly.)

### Sensitivity / ethics / legal notes

- **Grief comes first, always.** Do not use urgency, scarcity, or "distressed"/"desperate" language. Never imply the deceased. Never say "cash for houses" or "we buy ugly houses" to a probate lead — the tone alone loses respectable sellers.
- **Contact the right person.** Only the PR/executor can sell before the estate closes. Pushing an heir with no authority to "sign something" can create a mess and is a reputational risk.
- **Skip the raw-grief window.** The 30-day floor is an ethics line as much as a conversion tactic.
- **SC solicitation limits:** South Carolina has a **Prohibited Deceptive Trade Practices in Real Estate / wholesaling disclosure environment** — if you're wholesaling (assigning the contract rather than closing), disclose that you intend to assign and that you are acting as a **wholesaler, not a licensed broker**. SC actively scrutinizes unlicensed brokering; marketing the *contract* rather than being the actual end buyer can cross into brokerage without a license. Keep intent-to-buy genuine or intent-to-assign disclosed. Do not represent yourself as a real estate agent.
- **NC solicitation limits:** North Carolina similarly draws a hard line between buying for yourself and **brokering without a license** (NCREC enforces this). Wholesale assignments are legal but must be a genuine equitable-interest assignment with clear written disclosure; do not advertise a property you don't have under contract. NC also has a **funeral/death-record solicitation sensibility** — avoid anything that looks like you scraped an obituary to solicit (even though that's effectively the data source, the *presentation* must be respectful and never reference the death record).
- **Do-Not-Call & texting:** Scrub outbound call numbers against the **federal DNC registry**; probate leads are frequently DNC-listed. Cold **texting without prior consent violates the TCPA** and is the fastest way to a complaint on a vulnerable-owner list — prefer mail-driven inbound over cold text entirely for this segment.
- **Vulnerable owners:** Elderly surviving spouses and confused/newly-bereaved heirs warrant extra care. If someone seems unable to understand the transaction, slow down, encourage them to involve family or an attorney, and be willing to walk away. A deal that looks predatory is both an ethics failure and a lawsuit.
- **No probate-record fabrication:** Reference "records show the property may be part of an estate," never a specific person's death certificate or case file details, in written outreach.

### Realistic conversion expectation (response %, and the honest funnel to a contract)

Probate is a **low-response, high-quality, long-cycle** channel. Honest numbers from operators who actually run it:

- **Mail response rate: ~1–3%** on a clean, well-timed probate list (higher than blind absentee-owner mail because motivation is real, but still single digits). Handwritten-style letters at the right timing pull toward the top of that range.
- **Of responders, ~30–50% are genuine conversations** (the rest are "remove me," "already sold," "just keeping it").
- **Contact-to-appointment/offer: ~20–40%** of real conversations reach a real number-on-the-table.
- **Offer-to-contract: ~10–20%**, dragged out because you're often waiting on the estate, sibling consensus, or letters of administration.
- **Net: expect roughly 1 signed contract per ~700–1,500 pieces of well-targeted probate mail**, spread over a **60–180 day** cycle per deal. It is slow. The payoff is that probate deals tend to have **more equity and less competition** than most channels, and a respectful reputation compounds — probate attorneys, estate sale companies, and past sellers start *referring* you, which is where the real volume eventually comes from.

The honest funnel, end to end: **1,000 letters → ~20 responses → ~8 real conversations → ~2–3 offers presented → ~1 contract**, with the contract closing 1–4 months later once the estate clears. Treat the first deal as the cost of building the referral engine, not as the whole return.


## Divorce

### Owner psychology & situation (what they're actually feeling/needing)
A divorcing seller is not one motivated seller — they are **two people who no longer trust each other, jointly deciding to sell the one asset that ties them together.** The house is emotionally loaded (kids' bedrooms, the life they built) and financially loaded (usually the largest thing being split). What each side actually wants underneath the conflict is the same: **to be done.** To stop paying two housing costs, stop the fighting, stop having the ex's name on their mortgage, and get their share of the equity so they can start over.

Key psychological facts that drive every tactic below:
- **They're exhausted and decision-fatigued.** By the time the house comes up, they've been through months of lawyers, custody, and finances. A simple, low-conflict path is worth real money to them.
- **They're hyper-alert to being taken advantage of.** Each spouse is watching to make sure the other isn't getting a better deal. Any hint that you favor one side, or that you're circling their misfortune, kills the deal instantly.
- **They often can't afford to wait for retail.** Two households on one-and-a-half incomes, a mortgage neither can refinance alone, and a court that wants the asset liquidated. Speed and certainty can outweigh top dollar — which is exactly the wholesale value proposition.
- **Most divorces do NOT end in a sale.** Per PropertyRadar's data, only **~25–35% of divorces result in a property sale**; the rest refinance one spouse out or award the house in the settlement. You are hunting a minority outcome, so qualification matters more than volume.

### Best channel + TIMING (mail/call/text/door; how soon after the trigger; how many touches)
**Timing is the entire game, and the public-record trigger is a trap.** Divorce filings are recorded first; the recorder document (the thing most lists sell) often surfaces *months to over a year* after the actual filing — PropertyRadar cites a competitor record dated Nov-2025 for a case filed Aug-2024, "over a year earlier… the deal window had long closed." By the time a name hits a bought "divorce list," the attorneys, CPAs, and the couple's own network have already been engaged.

Practical timing rules:
- **Sweet spot is roughly 60–120 days after the FILING date, not the decree.** Early enough that the property decision is still open; late enough that the "we'll try to keep the house" fantasy has met the refinance math. If your only date is a recorder/decree date, treat the lead as likely stale and lead with a soft, non-divorce touch to test whether the house is still in play.
- **Channel = mail first, phone second, NEVER lead with a text or a door-knock.** Divorce is the most sensitive of all the trigger lists — a text or a knock reads as "someone is watching my worst moment." Mail gives them privacy and control over when to respond.
- **Address BOTH parties, separately.** Send two identical letters, one to each spouse (they frequently live at different addresses by now). Mailing only the occupant hands the decision to one side and makes the other feel excluded, which they will use as a reason to say no.
- **Cadence: 5–7 touches over ~120 days, every 21–30 days.** Consistent with the well-worn REI stat that most deals close on the 5th–12th contact. Mail → mail → (soft call if you have a good number and it's not on DNC) → mail → call. Slower and gentler than a foreclosure sequence.
- **Phone is a callback-only or warm-only channel here.** Because of TCPA/DNC exposure (below), treat outbound dialing to divorce lists as high-risk. The safest phone contact is one that a mail piece *invited* — a call to your number that they initiated.

### The actual pitch / message (a real script skeleton)
The governing rule from every credible source (Icenhower, ALL THE LEADS): **do not mention the divorce and position yourself as the neutral, structured, fast option that lets both people move on.**

**Direct-mail letter (send one to each spouse):**
> "Hi [First Name] — my name is [Name] with [Company], and I buy homes here in [County]. I'm reaching out about [property address]. If you and any co-owner are thinking about selling, I can make a straightforward cash offer, close on the date that works for you, and handle the paperwork so it's simple for everyone involved. No repairs, no showings, no agent commissions. If the timing isn't right, no problem at all — just toss this. If it might help, call or text me directly at [number]."

Note what it does: names the property (credible, not a mass blast), says **"any co-owner"** (acknowledges two owners without ever saying "divorce"), and sells **simplicity + certainty + a date you choose** — the three things a splitting couple actually needs.

**Inbound call skeleton (once THEY reach out):**
- **Opening / disarm:** "Thanks for calling — I know selling a house is a lot, so I'll keep this easy. Are you the only owner, or is there someone else on title I should loop in too?" *(Surfaces the two-decision-maker reality immediately and signals you'll treat both fairly.)*
- **Neutral frame:** "Just so you know how I work — if there are two owners, I keep both of you equally in the loop and I stay completely neutral on anything between you. My only job is a clean sale and a fair number you both agree on."
- **Value frame:** "The reason people in your spot call me is certainty. I give you one number, one closing date, no financing that can fall through, and I split the proceeds to whatever the two of you or the court direct — so nobody has to trust the other side to 'handle it.'"
- **The ask (soft, structured):** "If I look at the property and send you both the same written offer plus a simple net sheet showing exactly what each side walks away with, would that be useful — even if you decide to list instead?"

The **net sheet is the closing tool** (ALL THE LEADS): a one-page "here's what each of you nets" defuses the "is my ex getting a better deal?" fear better than any pitch, because it makes the split transparent and equal on paper.

### Top objections + responses
- **"We're going to try to keep the house."** → "Totally fair, and I hope that works out. A lot of people find the refinance doesn't pencil on one income — if that happens, keep my number. I can give you both a firm cash number in writing today so you have a real fallback, not just a maybe."
- **"We need to run everything through our attorneys."** → "Good — you should. I *want* your attorneys involved; it protects everyone. I'll send the offer and net sheet to both of you and your attorneys at the same time so there are no side conversations." *(Attorney involvement is your friend here, not an obstacle — it signals neutrality and legitimacy.)*
- **"My ex and I can't agree on anything."** → "That's exactly why a fixed cash offer helps — there's nothing to negotiate between you two. One price, split the way you or the court decide. It takes the argument off the table."
- **"How did you get my name?"** → "Property records — I look for owners in [area] who might be open to selling. If it's not you, I'll take you right off my list, no problem." *(Never say 'I saw you filed for divorce.')*
- **"We can get more with an agent."** → "You very well might, and I'll tell you honestly if listing is your better move. What I offer instead is speed and certainty — a set date, no repairs, no showings with two schedules to coordinate, and no deal falling apart on financing. Some people in a split value 'done' over 'maximum.' If you don't, list it — no hard feelings."

### Sensitivity/ethics/legal notes (what NOT to say; SC/NC solicitation limits; grief/vulnerable-owner care)
- **Never reference the divorce, the filing, the ex, or "your situation."** PropertyRadar is explicit: avoid "I noticed you're getting divorced." It's invasive, it can feel threatening, and it poisons trust. Market to the *property owner*, not to the *divorce.*
- **Never take sides or carry messages between spouses.** The instant one side thinks you're the other's guy, you lose both. Stay the neutral third party in every word and every document; send everything to both parties simultaneously.
- **Vulnerable-owner care:** these people are grieving a marriage and under financial stress — a textbook vulnerable state. Keep pressure low, honor "not interested" on the first ask, and be genuinely willing to tell someone that listing is their better option. Predatory-feeling tactics not only fail here, they generate complaints.
- **NC is now a hard legal wall — this is the big one.** Effective **October 1, 2025, North Carolina requires a real estate license to wholesale residential property**, and the law defines "wholesaling" to include *soliciting homeowners* and marketing/assigning contracts. It also gives NC homeowners a **30-day right to cancel** and a right to a full copy of the contract at signing. For your Western NC counties, an unlicensed assignment-style approach is now a licensing-law problem — route NC divorce deals through a licensed person or an actual purchase (buy-and-hold/flip), not a naked contract flip.
- **SC:** wholesaling remains legal but you must not cross into unlicensed brokerage (marketing *the property* vs. marketing *your equitable interest in a contract you actually intend to close*).
- **TCPA / DNC on both sides of the border:** scrub every number against the **National Do-Not-Call Registry** before any call; **no autodialers, no ringless voicemail, no bulk/mass texting without prior express written consent** — penalties run roughly **$500–$1,500 per call/text.** Divorce lists are exactly where a careless SMS blast becomes a complaint. Keep phone contact to DNC-scrubbed manual dials or, better, inbound calls your mail invited.
- **Data hygiene:** because divorce records are sparse and stale (PropertyRadar: "fewer than 5% of divorces ever get recorded"), verify the person still owns the property and it hasn't already sold/refinanced before you spend a touch — mailing a resolved case is both wasteful and, if the wording is off, offensive.

### Realistic conversion expectation (response %, and the honest funnel to a contract)
Set expectations low and precise — divorce is a **high-value, low-yield, long-timeline** lane, not a volume channel:
- **Mail response rate: ~0.5–1.5%** of pieces mailed, in line with cold direct-mail to trigger lists. Expect the good responses to cluster after touch 4–5.
- **Of divorces on your list, only ~25–35% ever produce a sale at all** (PropertyRadar), and only a *fraction* of those are off-market — because attorneys, agents, CPAs, and personal networks are already competing for the listable ones by the time public records surface.
- **Honest funnel, per ~1,000 verified/fresh divorce-owner mail targets (two pieces each):** roughly **8–15 inbound responses → 4–8 real two-party conversations → 2–4 that are genuinely in the "sell now" 25–35% and where you clear the second decision-maker → ~1 contract.** So plan on **roughly a 0.1% mail-to-contract rate**, meaningfully worse than pre-foreclosure, offset by larger equity spreads and less competition *when you catch timing right.*
- **The single biggest yield lever is not the script — it's data freshness and the two-party close.** Prioritize leads where the filing is 2–4 months old and you can reach *both* owners; deprioritize decree-dated/recorder-dated leads (likely already sold or settled). And build the **attorney-referral flywheel in parallel** — a handful of local family-law attorneys who trust you as the neutral, fast option will out-produce any cold list, because they hand you the deal *at the exact moment* the couple decides to sell, before it ever becomes a public record.

Sources: [PropertyRadar — Chasing Divorce Public Records](https://www.propertyradar.com/blog/chasing-divorce-public-records-real-estate-deals), [ALL THE LEADS — Divorce Lead Playbook (ATL 540)](https://www.alltheleads.com/divorce-lead-strategy-540/), [Icenhower — Real Estate Scripts for Divorce](https://therealestatetrainer.com/real-estate-scripts-for-divorce-converting-marketing-to-divorced-couples/), [NC REALTORS — Working with Divorcing Couples](https://www.ncrealtors.org/working-with-divorcing-couples/), [Real Estate Skills — Wholesaling Legal in NC (Oct 2025 license law)](https://www.realestateskills.com/blog/wholesaling-real-estate-legal-north-carolina), [REDX — Agent's Guide to DNC/TCPA](https://www.redx.com/blog/agents-dnc-list-tcpa-guide/)


## Pre-Foreclosure / Foreclosure

This is the most legally loaded lead type in the whole engine. In North Carolina, taking an advance fee to "help" a defaulting owner negotiate with their lender is a Class 2 misdemeanor under the debt-adjusting statute (G.S. 14-423/424), and the classic "rescue" pattern — advance-fee consultant, or a sale-leaseback where you take title and promise they can buy it back — is exactly what state AGs and the NCLC model statute exist to prosecute. You are not a rescuer, a negotiator, or a consultant. You are a cash buyer offering to purchase the house outright. Keep that line bright and everything downstream gets easier.

Split the list by equity before you write a single letter — the two groups need opposite pitches:
- **High-equity** (owe well under market): sell-and-walk-with-cash, or a subject-to where you take over payments. The house is an asset they can still cash out.
- **Underwater / thin-equity** (owe at or above market): there's no cash to hand them. The product is a graceful exit — short-sale coordination or a clean deed that stops the bleeding and protects their credit. Do not dangle cash you can't deliver.

### Owner psychology & situation (what they're actually feeling/needing)
The dominant emotions are shame, fear, and avoidance — in that order. By the time a lis pendens hits the record, the owner has usually spent months not opening mail, dodging their servicer's robo-dialer, and telling no one. They feel judged and cornered. Critically, **most default owners believe they have no options and no time** — they think the sheriff is coming next week. Both are usually false (SC runs ~6 months from lis pendens to sale; NC power-of-sale is similar), and correcting that misbelief is the single most powerful thing you can do. The high-equity owner's tragedy is that they'll often let the house go to auction and lose $60K of trapped equity purely out of paralysis — they don't realize the equity is theirs to capture if they sell before the gavel. The underwater owner mostly wants the shame to stop and to not get chased for a deficiency. The need underneath all of it: to feel like a person handling a hard situation with dignity, not a deadbeat being harvested.

### Best channel + TIMING (mail/call/text/door; how soon after the trigger; how many touches)
Timing is keyed to **stage, not lead age**:

- **Lis pendens just filed (0–60 days, "calm options" window):** Lead with **mail**, first-class handwritten-style, not a postcard screaming FORECLOSURE (that's the shame trigger — they'll trash it). Follow with a soft call/text 5–7 days later. This is the relationship-building window; the message is "you have more time and more options than you think." Do not create urgency here — you'll read as a vulture.
- **Mid-case (60 days to ~3 weeks pre-sale):** Multi-touch cadence. This is where deals actually close — practitioners consistently report the **3rd–5th touch** converts, not the first, because the owner's denial cracks over time. Rotate channels: mail → call → text → and for your highest-equity targets, a **door knock**. Door is the highest-conversion channel for pre-foreclosure specifically because it defeats the avoidance (they can ignore a phone; a calm person on the porch gets a conversation) — but only for high-equity where the deal justifies the effort.
- **~3 weeks to sale (urgent window):** Now urgency is honest, so you can use it. Call and door first, mail is too slow. The frame flips from "you have options" to "there's a real deadline but a real solution — here's exactly what has to happen in the next X days."

Plan **5–8 touches** across 60–90 days for a mid-stage lead. Stop the second they say stop — see legal notes.

### The actual pitch / message (a real script skeleton)

**First-touch letter (lis pendens, calm window):**
> "Hi [First name] — my name is [X] and I buy houses here in [County]. I saw in the county records that there's a case starting on [Street]. I know that's a stressful thing to get mail about, so I'll be straight with you: I'm not with your bank, I'm not a lawyer, and I'm not selling anything. I'm a local buyer. If at some point selling the house on your terms — before any court date — would help you walk away with cash in hand instead of losing it at auction, I'd be glad to make you a fair cash offer, no obligation. If not, I genuinely hope it works out. My number is [X] if it's ever useful."

**Call / door opener (mid-stage):**
> "Hi, are you [Name]? I'll only take a second — I'm [X], I'm a local homebuyer, and I'm reaching out because it looks like the house may be headed toward a court sale. Most folks in this spot don't realize they've actually got a few months and a couple of real options. Can I ask — is your plan to try to keep the house, or would selling it and walking away with something in your pocket be a relief at this point?"

- **Value frame (high-equity):** "Right now, if it goes to auction, that equity you've built — could be $40, $60, $80K — mostly evaporates. If you sell before the sale, that's yours. I can close on your timeline, as-is, no repairs, no agent fees, and we're done before the court date."
- **Value frame (underwater):** "You probably owe close to what it's worth, so there's no big check here — I want to be honest about that. What I *can* do is take it off your hands cleanly, work with your lender on a short sale so this doesn't wreck your credit for the next seven years, and get you out from under it. That's the win here — the fresh start, not a payday."
- **The ask:** always soft and binary — "Would it be worth 15 minutes to see what a real offer looks like? Zero obligation." Never "sign today."

### Top objections + responses
- **"How did you get my information / is this even legal?"** → "It's all public — the county files these cases in the open record, that's the only reason I know. Nothing private, and you're under no obligation to talk to me at all."
- **"I'm going to keep the house / I'm working it out with my bank."** → "That's genuinely the best outcome and I hope it works. If the loan mod or reinstatement comes through, ignore me completely. I'm just the backup plan if it doesn't — want me to leave my number in case?"
- **"You're just trying to steal my house / lowball me."** → "Fair concern, there are people who do that. I'll show you my numbers on paper — the ARV, the repairs, the payoff — so you see exactly how I get to the offer. And you can walk away at any point. I only make money if this actually helps you more than the auction would."
- **"I don't have any equity, why are you even calling?"** → (underwater) "You might be right, and if so a cash offer isn't the answer — a short sale is, and I coordinate those so it doesn't cost you and it protects your credit. Worth a conversation before the bank decides for you."
- **"Just take over my payments and I'll stay" / sale-leaseback ask.** → Decline the leaseback. "I can't do a deal where you sell it and keep living there hoping to buy it back — that structure gets people hurt and it's exactly what the state watches for. If I buy it, you'd be moving on. Let's talk about a clean sale instead."

### Sensitivity / ethics / legal notes (what NOT to say; SC/NC solicitation limits; grief/vulnerable-owner care)
- **NC is the hard line.** Do not offer to negotiate, modify, delay, or "work out" the loan with their lender for any fee — that's foreclosure-assistance/debt-adjusting and it's criminal in NC (G.S. 14-423/424). You *buy houses*; you don't *save* them. Never collect any upfront fee, ever, in either state.
- **No sale-leaseback / "deed it to me and rent it back and buy it later" deals.** This is the textbook equity-strip that foreclosure-rescue-fraud statutes target. Even if the owner asks for it, decline.
- **Never imply you're affiliated with the lender, the court, a government agency, or a "foreclosure prevention program."** No fake urgency ("you must act today" when they have three months), no claiming you can stop the foreclosure, no guaranteeing outcomes.
- **Put it in writing, plainly.** Contracts should be clear, no pressure to sign on the spot, and honor any right to cancel. If an owner tells you to stop contacting them, stop — log it and suppress across all channels (TCPA/DNC and basic decency both apply to your call/text cadence).
- **Vulnerable-owner care.** Foreclosure overlaps heavily with the elderly, the recently widowed, the sick, and the just-divorced. If you sense someone is confused, grieving, or clearly not competent to transact, slow down and route them to a HUD-approved housing counselor rather than to a contract — both because it's right and because a deal that looks like elder/duress exploitation is a lawsuit and a reputation kill. Tone throughout: calm, unhurried, "here's a door if you want it," never "sign before it's too late."

### Realistic conversion expectation (response %, and the honest funnel to a contract)
Pre-foreclosure is a low-response, high-value channel — the equity per closed deal is large, but the list is small and heavily worked by competitors and agents. Honest funnel on a well-targeted, equity-filtered list:
- **Direct mail:** ~1–3% response (call/text-back), lower if your piece looks like spam-mail, higher with handwritten-style + local + calm tone.
- **Cold call / text:** ~3–8% conversation rate on connects, but connect rates are low (bad numbers, avoidance) — budget skip-tracing and multiple attempts.
- **Door knock (high-equity, mid/late stage):** by far the best — 20–40% of answered doors turn into a real conversation because it beats avoidance.
- **Conversation → appointment/offer:** ~20–30% of genuine conversations.
- **Offer → signed contract:** ~20–35%, and a chunk of those still die (owner reinstates, lender mods, they can't emotionally let go, or a competing wholesaler outbids).

Net: from a clean 100-lead equity-filtered pre-foreclosure batch worked hard for 60–90 days, expect a small handful of real conversations and roughly **1–3 contracts** — but each is high-margin, so the channel earns its keep on dollars-per-deal, not on volume. Track by stage: your late-window door knocks and your 3rd–5th touches are where the contracts actually come from.


## Tax-delinquent / tax-sale redemption

### Owner psychology & situation (what they're actually feeling/needing)
There are two distinct sub-personas here, and the pitch is different for each:

1. **Pre-sale delinquent** (behind on taxes, not yet sold at auction). Usually a slow-burn hardship: fixed-income senior, inherited/probate property nobody wants to pay on, out-of-state heir, medical or job disruption, or a landlord who quietly stopped caring. Dominant feelings are avoidance and shame, not panic. Many have mentally checked out of the property. They throw away mail because they get "dozens of people wanting to pay cash" (a real homeowner quote from BiggerPockets). They do not think of themselves as being in a "tax problem" yet — they think of it as a bill they'll get to.

2. **Post-sale, in the 12-month redemption window** (SC). This is the sharper opportunity and where the "redemption clock" frame lives. The property was already sold at the county's delinquent tax sale; a third party holds the winning bid. The owner still legally owns it and can redeem, but if they do nothing for 12 months they lose the entire property — and all their equity — for the price of back taxes. Here the feeling is a mix of denial ("that can't really happen") and quiet dread. Most genuinely do not understand that a $4,000 tax bill can vaporize $120,000 of equity. That knowledge gap is your entire value proposition.

The core need for both: a way out that lets them **walk with cash instead of losing everything to the county**, handled quietly, without a lawyer, without an auction crowd, without judgment.

### Best channel + TIMING (mail/call/text/door; how soon after the trigger; how many touches)
This is a **multi-touch, multi-channel** list — single mailers get thrown out. Practitioner consensus (RealEstateSkills, BiggerPockets) is that most deals close on the 2nd–4th contact, so build a sequence, not a blast.

- **Primary: direct mail + phone, layered.** Mail warms the name; the phone (after skip-trace) does the actual converting. The most-upvoted BiggerPockets take is that mailers alone underperform and skip-trace-then-call is where deals actually come from.
- **Door-knock** only for local, safe, higher-equity parcels — it converts best but doesn't scale.
- **SMS** only on A2P/10DLC-registered, opt-in-compliant routes. Treat it as a supporting touch, never the opener.

**Timing by trigger:**
- *Pre-sale delinquent:* start once the parcel appears on the published delinquent list (SC counties advertise before the fall sale). The sweet spot is the **60–90 days before the scheduled tax sale** — enough runway to close, enough urgency to matter.
- *Post-sale redemption:* **do NOT lead in the first days after the sale.** Owners are still in denial and the clock is long. The high-conversion window is **months 7–11 of the 12-month redemption period** — late enough that the reality has set in and the redemption interest has climbed to 9–12%, early enough that you can still close and either redeem-and-buy or take assignment before the deed issues. A light touch around month 3–4 to plant the seed, then intensify from month 7.

**Cadence (14–21 day sequence per push):**
- Day 1: Letter (plain, personal-looking) + queue the call
- Day 3–5: First call
- Day 7: Second letter with a simple "here are your options" sheet
- Day 10–12: Second call
- Day 14–21: Final touch (call or door)

Then recycle the non-responders into the next monthly push. Roughly 200–300 parcels per hot list, 30–50 calls/week is the practitioner working rhythm.

### The actual pitch / message (a real script skeleton)
Lead with empathy and a problem you can name, not "I buy houses cash." The delinquency is public record, so you can reference it — but do it gently and factually, never accusingly.

**Mail (letter, post-sale redemption version — the sharpest one):**
> "Dear [First Name],
> I'm a local investor here in [County], and I noticed your property at [address] came up in the county's tax sale this past [month]. I don't know if anyone has explained this clearly, but you still have the right to keep it or sell it — for now. That right ends [redemption deadline date].
> If you do nothing, the county process can take the home for the back taxes, and any value above what's owed goes with it. I'd rather see that money stay with you.
> I help owners in exactly this spot pay off what's owed and walk away with cash in hand instead of losing it. No cost to talk, and if it's not a fit I'll tell you straight.
> Call or text me directly: [name / cell]."

**Phone opener (works for both personas):**
> "Hi [Name], this is [Name] — I'm a local investor, not the county and not a collector. I'm calling because your place on [street] showed up on the county's delinquent tax list, and I help folks in that spot before it turns into a bigger problem. Do you have two minutes?"

**Value frame:**
> "Here's the honest situation: the taxes owed are small next to what the house is worth. If it goes all the way through the county's process, that difference doesn't come back to you. I can pay the taxes off and get you cash for the equity, or if you'd rather keep it I can point you to the redemption route. Either way you don't lose it for nothing."

**Ask (soft, information-first):**
> "Would it help if I ran the numbers — what's owed, what it's worth, and what you'd actually walk away with — and just showed you? No obligation."

The consistent thread: **you are the person who explains the clock and hands them a way to not lose the equity.** That framing is honest and it's the reason this list converts.

### Top objections + responses
- **"I'm going to pay the taxes / I've got it handled."** → "That's great, and honestly the best outcome for you. If you're redeeming, here's the exact deadline and the number to call at the treasurer's office so no one runs the clock out on you. If plans change, keep my number." (You lose nothing by being useful; a chunk of these come back.)
- **"You're just a vulture trying to steal my house for the taxes."** → "Fair thing to be worried about — that's actually what the county process itself does if nobody acts. I'm the opposite: I only make money if you walk away with money. If the numbers don't leave you better off, I'll tell you not to sell." Name the fear, then invert it.
- **"How much can you even give me?"** → Don't quote blind. "Depends on condition and what's owed — let me confirm the payoff and comps and I'll give you a real number, not a lowball to reel you in." 
- **"I get ten of these letters a week."** → "I believe it. Difference is I'm local and I'm calling about your specific deadline — [date] — not a mass list. Most of those people can't explain what happens after that date. I can."
- **"I want to keep the house."** → Genuinely help them redeem. Offer to walk them to the treasurer, or if they're short the redemption cash, that's a different (and legitimate) deal conversation. Do not push a sale on someone who can and wants to keep it.

### Sensitivity/ethics/legal notes (what NOT to say; SC/NC solicitation limits; grief/vulnerable-owner care)
- **The equity-stripping trap is the ethical line.** The reason this list is lucrative is the exact reason to be careful: an owner can lose six figures of equity over a four-figure tax bill. Do not exploit that ignorance — surface it. Offer a fair price relative to real equity, and always tell them redemption is an option. A "give me the house for back taxes plus a few hundred" deal on an unsophisticated senior is how investors end up in the news and in front of a judge.
- **Vulnerable owners:** disproportionately elderly, recently bereaved (probate/inherited parcels), or cognitively declining. Slow down. Never create false urgency beyond the *real* statutory deadline. If someone seems confused or heirs are in conflict, encourage them to loop in family or a lawyer — pushing a signature on a confused owner is both wrong and voidable.
- **SC redemption mechanics — get them right or you'll mislead people:** Under SC Code §12-51-90, the owner (or a grantee/creditor) has **12 months from the tax-sale date** to redeem by paying taxes, costs, penalties, and interest that steps up by quarter — **3% (months 1–3), 6% (4–6), 9% (7–9), 12% (10–12)**. During redemption the winning bidder has **no ownership rights and legally cannot enter or contact the owner** about the bid — so if you *hold* a tax-sale bid, your outreach must be as an investor offering to help, not as the "new owner." You can **assign your bidder's interest** before redemption ends (filed with the tax collector), which is the compliant path to move a position. If you're approaching the *original owner*, you're not restricted the same way, but never imply you already own it.
- **NC is different — don't reuse SC copy.** North Carolina uses **judicial tax foreclosure (mortgage-style)**, and there is **no post-sale statutory redemption year like SC's**; the owner's window to pay is **up to the upset-bid/confirmation of the court sale**, after which redemption is generally gone. So in NC the honest frame is "before the court confirms the sale," not "you have 12 months." Using SC's redemption-clock language in NC is factually wrong and could be seen as deceptive.
- **Solicitation limits:** honor DNC — scrub the federal/state Do-Not-Call registry before dialing skip-traced cells, and SMS only via compliant 10DLC with opt-out honored. Both states restrict recorded/auto-dialed calls; use manual dialing for these lists. Avoid any wording that reads as offering *legal or tax advice* ("you must," "the law requires you to sell") — point them to the treasurer or an attorney for that.
- **What NOT to say:** no "the county is coming to evict you tomorrow" scare tactics beyond the real timeline; no implying you represent or are affiliated with the county/treasurer; no "sign today or lose everything" pressure; no quoting a redemption deadline in NC as if it were SC's 12 months.

### Realistic conversion expectation (response %, and the honest funnel to a contract)
This is a **higher-intent but small** list, so the percentages beat generic absentee lists but the raw numbers are modest.

- **Mail response:** ~1–3% typical for cold real-estate direct mail; tax-delinquent tends to land at the **higher end (roughly 2–5%)** because the pain is concrete and dated — but only with multi-touch. One-and-done mail sits near the bottom of that range.
- **Phone (skip-traced):** far better contact economics — roughly **5–10% of dials reach a live, relevant owner conversation**, and this channel is where practitioners say the deals actually originate.
- **Honest funnel** (illustrative, per ~250-parcel push): 250 parcels → skip-trace to phone → ~30–50 calls/week → **~8–15 real conversations** → **~3–6 owners who'll let you run numbers / do an appointment** → **~1–2 contracts**. Roughly a **0.5–1% parcel-to-contract** rate on a well-worked, multi-touch list, higher on the post-sale redemption sub-segment because the deadline does the persuading for you.
- **Where it breaks:** owners who intend to redeem (you should *help* them, not fight it — they're not your deal), heir/title tangles that stall closing, and low-equity parcels where the tax debt eats the margin. Score parcels on **equity above tax owed** before you spend a stamp; a delinquent parcel with no equity is not a lead.

Sources: [BiggerPockets — Direct Mail to Tax Delinquent Properties](https://www.biggerpockets.com/forums/93/topics/239423-direct-mail-message-to-tax-deliquent-properties), [RealEstateSkills — Wholesaling Tax Delinquent Properties](https://www.realestateskills.com/blog/wholesaling-tax-delinquent-properties), [SC Code §12-51-90 (Justia)](https://law.justia.com/codes/south-carolina/title-12/chapter-51/section-12-51-90/), [Orangeburg County SC — Redemption of Property Sold](https://www.orangeburgcounty.org/365/Redemption-of-Property-Sold).


## Vacant / absentee / tired landlord

### Owner psychology & situation (what they're actually feeling/needing)
This is the most receptive cold-outreach segment, but "absentee" is really three overlapping mindsets, and your copy lands differently for each:

- **The tired landlord** is the highest-conviction sub-type. They're not in financial distress; they're in *emotional* distress. They're exhausted by the 2am calls, the eviction they just lost, the turnover repair that ate a year of cash flow, the property-management percentage. The Urban Institute / practitioner consensus is that ~80% of non-owner-occupant landlords sell at some point — you're just trying to catch them in the week they've decided they're done. They need permission to quit and an exit that doesn't feel like they failed. Money matters, but *relief and finality* matter more.
- **The out-of-state / inherited absentee** owns something they never chose and can't manage from a distance. A rental in Greenville, SC while they live in Denver; a house they inherited in Rutherford County, NC that's sat vacant since a parent died. They feel a low-grade guilt-and-nuisance about it. They need someone competent to make the problem disappear without a plane ticket.
- **The vacant-property holder** is bleeding — taxes, insurance, code-enforcement letters, a roof they haven't seen — on an asset producing nothing. Vacancy is the single strongest motivation trigger of the three because the pain is monthly and rising.

Across all three, the receptivity advantage is real: because the *mailing address differs from the property address*, your mail reaches them at home, at the kitchen table, away from the property they're avoiding. That physical separation is exactly why this list beats owner-occupant lists.

### Best channel + TIMING (mail/call/text/door; how soon after the trigger)
This segment is the exception to "door-knock everything" — you often can't door-knock, because they're in another state. Lead with **mail + phone**, layered.

- **Primary: direct mail to the tax/mailing address** (not the property). This is the whole edge of the segment: the letter forwards to where they actually live. Use a plain, hand-addressed-look letter or yellow-letter style, not a glossy postcard, for the tired-landlord and inherited sub-types; postcards are fine for the vacant/high-volume tier.
- **Layer cold calls** after a skip-trace. Plan for 50–85% usable phone numbers on a clean absentee list, far lower on old/inherited data. Contact rate 5–12%; aim for a meaningful conversation on 5–20% of live connects.
- **SMS only with caution** — see legal notes. It performs but carries the most exposure; many operators have pulled back from it.
- **Door-knock only the in-footprint absentees** (owner in Spartanburg, rental in Greer). For those it's a strong differentiator because nobody else shows up in person.

**Cadence (the 8–12 week multi-touch sequence practitioners actually run):**
1. **Touch 1 — Mail, within 1–3 days of the trace/trigger.** First letter to mailing address.
2. **Touch 2 — Call, days 3–10.** Skip-traced number.
3. **Touch 3 — Second mail piece, weeks 2–4.** Different format/message than #1.
4. **Touch 4 — Call again, week 4.**
5. **Touch 5+ — rotate mail/call every ~2–4 weeks through week 12**, optional consented SMS.

Do not treat one touch as a test. Most closed deals come from follow-up, not first contact — budget **10–15 conversations/offers per deal**, and expect **0.5–3% call-back on cold mail**. For a *trigger* like a fresh vacancy code notice or a new eviction filing, compress the front of the cadence (mail day 1, call day 2).

### The actual pitch / message (a real script skeleton)

**Direct-mail letter (tired landlord / inherited — plain, first-person):**
> "Hi [First Name] — I'm a local buyer here in [County]. I'm reaching out because I'd like to buy your property at [property address]. I buy as-is — you don't fix anything, clean anything out, or deal with showings, and I can close on your timeline. If you've got a tenant in place, that's fine, I'll take it with the tenant. If you've ever thought about being done with this one, I'd love to make you a straightforward cash offer. My direct line is [number] — call or text me anytime. — [Name]"

**Cold-call open (calm, local human — not a call center):**
> "Hi, is this [Name]? I'm [Name], I'm a local buyer here in [area] — I'm calling about your property over on [street]. Did I catch you at an okay time?"

**Value frame (say the pain out loud, then let them vent — silence is your tool):**
> "The reason I called — I talk to a lot of folks who own a rental they're a little tired of. The tenants, the repairs, the taxes, the management cut… at some point it stops being worth the headache. Is that where you're at with this one, or are you still happy holding it?" *(Then stop talking. Let them tell you.)*

**The ask (lock a concrete next step, never "think about it"):**
> "Here's what I can do: I'll pay all the closing costs, buy it exactly as it sits — tenant and all — and give you one number you actually walk away with, on a date you pick. Would it be worth a quick offer? I can have a real number to you by [day]."

The value frame that closes this segment is **net proceeds + certainty**, not headline price: a lower number they walk away with, on a date they can count on, with no repairs and no deal falling through, beats a higher listed price wrapped in cost and uncertainty.

### Top objections + responses
- **"Your price is too low."** → "That's fair — let me ask it differently. If I cover all closing costs and buy it as-is with the tenant in place, what net number would actually make this worth it to you?" *(Reframe to net-in-pocket; surface their real floor.)*
- **"I'll just list it with an agent."** → "You totally could, and if that's your best move I'll tell you so. The difference is you'd clear it out, make it show-ready, wait on financing, and pay commission. I'm certainty and speed with none of that — worth having both numbers side by side?"
- **"I've got a tenant / it's occupied."** → "Perfect, keep them — I buy tenant-occupied all the time, you don't have to give notice or turn it over. That's actually easier for me."
- **"How'd you get my number/address?"** → "Public property records — I'm a local buyer, not a call center. If you'd rather I not reach out again, just say the word and you're off my list for good." *(Direct + immediate opt-out builds trust and is compliant.)*
- **"I'm not interested."** → "No problem at all. Can I ask — is it 'not this year,' or 'never'? If it's timing, I'll check back down the road." *(Sorts dead from dormant so you can re-cadence.)*

### Sensitivity/ethics/legal notes (what NOT to say; SC/NC limits; vulnerable-owner care)
- **Scrub the DNC Registry at least every 31 days** before calling; violations run $500–$1,500 each. You generally have **no Established Business Relationship** with a cold absentee, so the EBR exemption does not cover you. TCPA suits rose ~27% into 2026 — this is not theoretical.
- **SMS is the highest-risk channel.** Marketing texts require prior express written consent under TCPA; cold-texting a skip-traced number you have no consent for is the classic wholesaler exposure. Do not blast SMS to raw absentee lists. Lead with mail/call; reserve texts for people who have replied or given a number to text.
- **Inherited/vacant-because-of-death overlaps with probate.** If the "absentee" reason is a recent death, treat it with the grief-and-vulnerable care of a probate lead: never open with the deceased's name, never imply urgency ("before you lose it"), and don't pitch the estate before you know who has authority to sell.
- **Do NOT say:** anything implying you're rescuing them from foreclosure they didn't mention, any "act now or lose it" pressure, or that you're an agent/appraiser if you're not. Don't misrepresent how you got their info.
- **NC/SC specifics:** Neither NC nor SC requires a real-estate license merely to buy property for your own account, but if you're *wholesaling the contract* you're skating close to unlicensed brokerage — keep messaging as a principal ("I'd like to buy your property"), not "I'll find a buyer for you." SC's telemarketing rules track federal DNC/TCPA; NC's Telephone Solicitations statute (NCGS §75-100 et seq.) adds state DNC obligations and identification requirements on calls. Identify yourself and your company honestly on every call, honor opt-outs immediately and permanently, and keep a suppression list.

### Realistic conversion expectation (response %, and the honest funnel)
- **Cold mail:** ~0.5–3% call-back rate. On a tight absentee list (out-of-state + high equity + long hold, or +vacant/tax-delinquent stacked), push toward the high end.
- **Cold calls:** 5–12% contact rate; of live connects, 5–20% become a real conversation; ~3–5% of *contacts* set an appointment/offer.
- **Funnel to contract (per ~1,000-record absentee campaign, multi-touch over 8–12 weeks):** ~1,000 pieces → ~15–30 inbound/meaningful conversations → ~10–15 offers → **~1 contract.** Tired-landlord and vacant sub-lists convert at the top of these ranges; inherited-with-stale-data at the bottom (skip-trace hit rate drops to 10–30%).
- **Bottom line:** the segment's edge is *receptivity and mail-forwarding reach*, not a magic script. Deals come from disciplined follow-up and list stacking (out-of-state mailing address + high equity + vacancy/tax signal), not from one clever letter.

Sources:
- [RealEstateSkills — Wholesaling Cold Calling Script](https://www.realestateskills.com/blog/wholesaling-cold-calling-script)
- [BiggerPockets — Cold Calling / Scripts for Tired Landlords (forum)](https://www.biggerpockets.com/forums/432/topics/494678-motivated-seller-leads-cold-calling-or-scripts-for-tired-landl)
- [Goliath Data — Calling Landlords Without Triggering Defensiveness](https://goliathdata.com/respectful-landlord-cold-calling)
- [Vulcan7 — Ultimate Guide to Absentee Owner Lists](https://www.vulcan7.com/2025/07/the-ultimate-guide-to-absentee-owner-lists-in-real-estate-prospecting/)
- [ResidentialCoop — Skip Tracing to Source Off-Market Sellers (cadence + response rates)](https://residentialcoop.com/using-skip-tracing-to-source-off-market-sellers/)
- [ActiveProspect — TCPA Text Message Rules 2026](https://activeprospect.com/blog/tcpa-text-messages/)
- [DNC.com — Real Estate Agents: Are You DNC Compliant?](https://www.dnc.com/blog/real-estate-agents-are-you-dnc-compliant)
- [ClickPoint — 2026 Guide to TCPA, One-to-One Consent, CAN-SPAM & State Regulations](https://blog.clickpointsoftware.com/tcpa-one-to-one-consent-can-spam-state-regulations)


## Code-violation / incarcerated / elderly-downsizing owners

These are three distinct "cannot-maintain" owners who share one trait: the property has become a burden they physically or legally cannot fix, and the wrong touch reads as predatory. Each needs its own who-do-you-actually-talk-to answer and its own hard legal line.

---

### Owner psychology & situation (what they're actually feeling/needing)

**Code-violation owner.** Usually an out-of-area landlord, a tired local owner, or an heir who inherited a house they never wanted. The mailbox is now a stream of citations from Spartanburg / Greenville / Anderson code enforcement or an NC municipality (overgrown lot, junk/debris, unsafe structure, open/vacant). What they feel is *low-grade dread and avoidance*: fines accrue daily or per-notice, some jurisdictions convert unpaid fines to a lien on the property, and the "abate or demolish" letter is the one that finally scares them. They are not sad; they are annoyed and trapped. The need is simple: **make the problem and the fines stop without me spending money or a Saturday I don't have.** That is your entire value proposition. They often don't know a lien is attaching, so "these fines can become a lien that follows you even after you sell / can grow past what the lot is worth" is genuinely useful information, not a scare tactic.

**Incarcerated owner.** The property is decaying while they sit inside, often with no one collecting rent, a family member squatting or "watching it," taxes going unpaid, and a real fear of losing it to tax sale before release. Emotionally: powerlessness and distrust of anyone who shows up wanting their asset while they can't verify anything. They also have *time*, a phone/tablet, and often a strong motive to convert a frozen asset into commissary money or a nest egg for release. The need: **turn a property I can't manage into cash, through someone I can trust, while I'm behind glass.**

**Elderly downsizing / can't-maintain owner.** Long-time owner, often widowed, house is paid off or nearly so, stairs and yard have become the enemy, and family lives out of state. Feelings run deep here: grief, pride, loss of independence, fear of being "taken," and fear of being a burden. They frequently are *not* the decision-maker alone; an adult child, a POA agent, or increasingly a court-appointed guardian/conservator is. The need is rarely "top dollar" — it's **dignity, certainty, simplicity, and not getting ripped off**: no showings, no repairs, flexible move-out, someone who treats them like a person.

---

### Best channel + TIMING (mail/call/text/door; how soon after the trigger; how many touches)

**Code-violation.** Channel: **direct mail first, then phone/text, door last.** These owners are often absentee, so door-knocking frequently hits a tenant or empty house. Timing: the sweet spot is **after the second or third citation but before the abatement/demolition hearing** — early enough that fines are a nuisance, late enough that they're motivated. Watch the code-enforcement calendar; a scheduled hearing is your best trigger. Cadence: a **5-7 touch sequence over 60-90 days** (letter → letter → call/text → letter → call), because these decisions are procrastinated, not refused. A short handwritten-style yellow-letter outpulls a polished postcard here.

**Incarcerated.** Channel: **physical mail to the facility is the primary and often only compliant first touch.** You cannot cold-call a prison. Practitioners send a plain letter, or a message through the facility's e-messaging system (JPay / GTL/ViaPath / Securus) if you can find the inmate via the SCDC or Federal BOP / county-jail locator. Expect the owner to respond by **collect call** — set up a service that accepts them. Timing: mail as soon as you've confirmed incarceration and ownership; there is no "too early," and tax-sale deadlines make speed valuable. Cadence: **2-3 letters spaced ~3 weeks apart**; mail moves slowly and gets read slowly inside. Parallel track: **locate and contact the family member managing the property** (see below) — they are frequently the faster path.

**Elderly.** Channel: **mail to open the door, phone to build the relationship, in-person to close — never lead with a hard door-knock on an elderly owner.** The most durable channel is actually **the adult child / POA agent**, reached by mail or phone, not the senior directly. Timing: elderly leads are relationship sales, not trigger sales; there's no clock, so **slow down deliberately**. Cadence: fewer, warmer touches (**3-4 over several months**), and the moment a family member surfaces, pivot all substantive conversation to them. If the owner shows any confusion, that's a signal to *slow down and involve family*, not to push.

---

### The actual pitch / message (a real script skeleton — opening line, value frame, ask)

**Code-violation letter (skeleton):**
> "Hi [Name] — I noticed the property at [address] has some open notices from [City] code enforcement. I buy houses in [county] as-is, and I handle the cleanup, the repairs, and the code paperwork myself so those fines stop adding up. You wouldn't fix anything, clean anything, or pay closing costs. If it's easier to just be done with it, I can make you a cash offer this week. Is [address] something you'd consider selling? — [Name], [phone]."

Value frame: **I make the citations and the liability disappear.** Ask: a soft yes/no on selling, not a price.

**Incarcerated owner letter (skeleton) — deliberately plain and respectful:**
> "Mr./Ms. [Name], I'm a local real estate buyer in [county]. I understand you own the property at [address]. I'm writing because I may be able to buy it from you for cash, which some owners in your situation use to cover taxes before a tax sale or to have funds waiting when they're out. There's no cost to you, and everything can be handled by mail through the facility with a notary. If you'd like to talk, you can reach me collect at [phone] or write me at [address]. No pressure and no rush — I just wanted you to know the option exists."

Value frame: **liquidity and protection from tax-sale loss, handled entirely by mail.** Ask: "call or write me if you want to talk." Never imply urgency or that they'll "lose everything" — that reads as coercion of a captive person.

**Elderly / family-agent script (phone, to the adult child or POA):**
> "Hi [Name], I reached out about your mom's house on [street]. I'm not trying to rush anyone — I know this is a lot. A few families I've worked with wanted to sell without cleaning it out, without repairs, and on their own timeline so mom could move when *she's* ready. If that's something you're weighing, I can walk you through what that looks like, and you can decide with your mom and your attorney. Would it help if I put the numbers in writing so you can look at them together?"

Value frame: **dignity, zero hassle, family stays in control, decide on your timeline.** Ask: permission to send something in writing they can review *with the senior and counsel* — never a same-day signature.

---

### Top objections + responses

**Code-violation**
- *"I'll just fix it myself."* → "You totally can. Most owners I talk to just don't have the weekend or the contractor. If you'd rather hand it off, my offer covers the fines and the work — either way the notices stop."
- *"The fines aren't my problem, it's the tenant."* → "I hear you. The city attaches those to the property, not the tenant, so at sale they can come out of your proceeds. If you sell to me as-is I take that on."

**Incarcerated**
- *"How do I even sign anything from here?"* → "By mail. You sign a power of attorney or the deed in front of the facility notary — most charge a few dollars — and mail me the originals. I've done it this way before." (True: facilities offer notary service, typically a small per-signature fee.)
- *"How do I know you won't rob me while I'm stuck in here?"* → "Fair question. Everything goes through a licensed title company / closing attorney who holds the funds and pays you — not me handing you cash. You can have a family member or your own lawyer review it."

**Elderly / family**
- *"We're not ready to sell."* → "Completely understand, and there's no deadline from me. I'll leave my info; if it ever gets to be too much, call me and we'll go at whatever pace works."
- *"Are you trying to lowball my mother?"* → "I get why you'd ask. That's exactly why I'd rather you and your mom review the numbers in writing, with your attorney if you want. If it's not fair, throw it out."

---

### Sensitivity/ethics/legal notes (what NOT to say; SC/NC solicitation limits; grief/vulnerable-owner care)

**Across all three:** In both SC and NC, wholesaling means you must **actually contract to buy (equitable interest) and assign — you cannot market or broker someone else's property without a real estate license.** Advertising "I'll sell your house for you" instead of "I'll buy it" crosses into unlicensed brokerage. Keep the pitch as a *purchase*, not a listing service.

**Code-violation — foreclosure/distressed-owner overlap.** If the property is *also in active foreclosure* and owner-occupied, you may fall under SC's foreclosure/equity-purchaser rules: an "equity purchaser" who buys a foreclosed primary residence must use a written contract with statutory disclosures and a right of cancellation, and the obligations survive the deed transfer (owner can still sue after signing over). Do **not** promise to "stop the foreclosure" or collect any upfront fee for consulting — that's the classic foreclosure-consultant trap. Just make a clean cash-purchase offer. ([SC foreclosure/equity-purchaser overview](https://www.legalwiz.com/foreclosure-protection-foreclosure-consultant-laws-2/))

**Incarcerated — capacity and coercion are the whole ballgame.**
- Confirm the owner has **legal capacity** and is signing **voluntarily**; a captive audience makes coercion claims easy, so keep every message pressure-free and documented. Never imply they'll lose the house unless they act now.
- The correct instruments are a **notarized POA or a directly executed/notarized deed** through the facility notary; a valid, recorded POA with real-property authority is required before an agent can sign a deed. ([selling while incarcerated — POA mechanics](https://kdshomebuyers.net/articles/sell-house-while-incarcerated))
- Watch for a **court-appointed conservator or co-owner** — if one exists, they, not the inmate, may control the sale, and some sales need court approval. Verify who actually holds authority before you contract.
- If a **family member** claims to speak for the owner, get proof (a recorded POA) before treating them as the decision-maker; a relative's say-so is not authority to convey.

**Elderly — the brightest red lines, in both states.**
- **POA self-dealing is prohibited.** Under NC's Uniform Power of Attorney Act (Ch. 32C), an agent generally **cannot create an interest in the principal's property for the agent** (or someone the agent supports) unless the POA expressly authorizes it, and gifting is capped. So **never buy from, or route a discount to, the POA agent themselves** — a below-market sale to the agent (or to you with a kickback to the agent) is voidable self-dealing and a red flag for fraud. ([NC Ch. 32C self-dealing/gift limits](https://law.justia.com/codes/north-carolina/chapter-32c/article-3/section-32c-3-301/)) Also confirm the POA grants **real-property authority and is recorded** with the Register of Deeds before any agent-signed deed.
- **Financial exploitation of a vulnerable adult is a felony.** SC's Omnibus Adult Protection Act makes knowingly exploiting a vulnerable adult — including through **undue influence, duress, or misuse of a power of attorney** for another's advantage — a felony (up to 5 years and/or a $5,000 fine, plus restitution). NC has parallel exploitation-of-an-older/disabled-adult statutes. A lowball deal extracted from a confused senior is not just a bad look; it's chargeable. ([SC §43-35-85 penalties](https://law.justia.com/codes/south-carolina/title-43/chapter-35/section-43-35-85/))
- **Undue-influence hygiene, in practice:** if the owner shows any confusion or memory issues, **stop and insist on family and independent counsel**; put every number in writing so it can be reviewed cold; never get a same-visit signature; encourage (don't discourage) them to have their own attorney; and keep the offer defensibly fair — the closer to market and the more transparent, the harder any exploitation claim is to make.
- **What NOT to say** to any of these three: no "you'll lose everything," no "sign today or the deal's gone," no "don't bother telling your kids/lawyer," no promise to "save" them from foreclosure for a fee, and nothing that implies you're brokering rather than buying.

---

### Realistic conversion expectation (response %, and the honest funnel to a contract)

- **Code-violation:** highest-converting of the three because motivation is concrete and the owner is usually rational, not grieving. Expect roughly **4-8% response** on a targeted, multi-touch mailer to a clean code-violation list, and something like **1 signed contract per ~40-60 owners worked** once you filter for real equity and absentee/tired owners. Fast to contract once you connect.
- **Incarcerated:** **low response and slow** — figure **1-3% reply** to facility mail, long lag (weeks per exchange), and heavy mechanical friction (notary, POA, verifying authority, occasional court approval). But the *few* who engage are highly motivated, so it's a low-volume/high-intent niche. Budget months per deal; the family-member side channel is where most of these actually close.
- **Elderly:** deliberately slow, relationship-driven, **moderate response (~3-5%)** but a *long* runway from first contact to close, and a meaningful share should be walked *away from* or handed to family/attorney rather than contracted — that self-selection is a feature, not a loss. Realistic funnel: many warm conversations, few signatures, but the ones that close are clean, referral-generating, and defensible. Treat "we passed because the owner wasn't clearly capable" as a successful outcome, not a failed one.


---

# Deep-Dive Round 14 — Deal Financial Modeling per Strategy (2026-07-02)


## Wholesale / Wholetail

### The model (how the money is actually made, one paragraph)
Wholesaling is a paper play, not a property play. You get a distressed house under a purchase contract at a deep discount, then transfer that contract (not the house) to a cash buyer/flipper for more than you owe the seller, pocketing the spread. You never take title, never rehab, and never carry the asset — your only capital at risk is the earnest money deposit (EMD). The profit is the assignment fee: the gap between your contract price with the seller and what the end-buyer will pay to step into your shoes. It works because the flipper is happy to pay you $5k–$15k to skip the acquisition grind (marketing, negotiating, chasing motivated sellers), and because you priced the contract low enough that even after your fee the flipper still clears their own 70%-of-ARV threshold. **Wholetail** is the adjacent variant: instead of assigning, you actually close on the house (usually a light/cosmetic property that a retail buyer can live in), do a broom-clean-to-light-refresh, and relist it on the MLS to capture retail-vs-cash spread yourself — more capital and time, bigger margin, and it wins whenever the house is clean enough that assigning at a wholesale discount leaves too much meat on the bone.

### The underwriting formula (the exact max-offer / MAO equation with every cost line)
Wholesale MAO is the flipper's max-bid minus your fee. Because the end-buyer underwrites to the 70% rule, your ceiling is *their* ceiling:

```
Buyer_MAO_70   = ARV * 0.70 - rehab
Wholesale_MAO  = ARV * 0.70 - rehab - assignment_fee        (pure assignment)
```

The 0.70 is not sacred. In our softening/thin-comp rural markets (mobiles, non-metro Upstate/WNC) drop to **0.65 or 0.60** because comp data goes stale before close and buyer pools are shallow. Metro Asheville/Greenville with tight comps can support 0.70–0.72. For the **wholetail** path you underwrite it like a mini-flip on the *retail* exit, not a cash-buyer exit:

```
Wholetail_MAO = (ARV_retail * (1 - selling_costs%))         # net sale proceeds
              - light_rehab
              - holding_costs                                # taxes/insurance/utilities over ~2-4 mo
              - financing_costs                              # if hard-money/transactional used
              - target_profit
Where selling_costs% ≈ 0.08–0.09  (listing agent 2.5–3% + concessions + SC/NC deed stamps
   [$1.85/$500 in NC ≈ 0.37%, $3.70/$1,000 in SC ≈ 0.37%] + closing/title ~1%).
```

### Capital required + financing (down/EMD, hard-money points+rate 2026, holding months, total cash-in)
**Pure assignment** is the near-zero-capital lane: your only cash-in is the **EMD** ($500–$2,500 typical on our price band; sometimes $100 on motivated-seller deals), plus marketing cost to source the lead. No down payment, no loan, no points, no holding. You get paid the assignment fee at the A-to-C closing table.

**Double-close** (needed when the assignment fee is large enough that disclosing it on a single settlement statement would blow the deal, or when title/end-lender won't allow a visible assignment) requires you to fund the A-to-B purchase for minutes-to-hours. That is what **transactional funding** is for: 2026 pricing runs **1.5%–2.5% of the A-B price (≈$750 minimum), plus a $400–$900 processing/doc fee**, for same-day/24-hour money. Budget **$3,000–$6,000 extra** vs. a clean assignment once you add two sets of closing costs and sometimes double title insurance. On a $90k A-B price that's roughly $1,350–$2,250 in points + ~$700 fee ≈ **$2,000–$3,000 all-in** for the funding alone.

**Wholetail** needs real acquisition capital. Either cash, or **hard money at 2026 terms: ~10%–12.5% interest + 2–3 points**, typically 85%–90% of purchase and often 100% of a light rehab, held **2–4 months**. On a $95k buy that's ~$1,900–$2,850 in points plus ~$800–$1,000/mo interest, so total cash-in (down + points + a few months carry + light rehab of $8k–$20k) commonly lands **$20k–$40k**.

### Exit math + margins (realistic profit + the make-or-break variables)
- **Assignment profit = the fee, full stop.** Realistic in our markets: **$5k–$15k** on entry-level SFR/mobile, and NC specifically shows some of the **highest average assignment fees in the country (~$20k+)** on good deals. National average assignment fee is **~$13k**; experienced operators run **$15k–$20k**.
- **Make-or-break variables for assignment:** (1) **ARV accuracy** — every $10k you're wrong on ARV comes straight out of your fee, because the buyer's 70% ceiling moves with it; (2) **rehab estimate** — you must underwrite the flipper's number, not a rosy one, or your contract won't assign; (3) **buyer depth** — a fee only exists if a cash buyer actually closes; thin rural buyer pools kill deals; (4) **spread cushion** — if `ARV*0.70 - rehab` doesn't clear your seller price by at least ~$5k, there is no deal.
- **Wholetail profit** is larger — you keep the retail-vs-wholesale gap yourself, commonly **$15k–$35k** net on our band — but you now eat **selling costs (~8–9%)**, **holding**, and **financing**, and you carry **market/DOM risk**. Wholetail wins when the house is clean/livable (retail buyer can finance it), comps are tight enough to trust the retail ARV, and the wholesale discount you'd have to give away exceeds your all-in cost to just sell it retail yourself.

### A worked example (a real deal in our price band: ARV, rehab, all costs, the offer, the profit)
Distressed SFR, Spartanburg County SC. **ARV = $180,000**, real **rehab = $35,000** (dated kitchen/bath, roof, HVAC — a true flip candidate, so *assign*, don't wholetail).

- Buyer's ceiling: `180,000 * 0.70 - 35,000 = 126,000 - 35,000 = 91,000` → flipper max-bid **$91,000**.
- Your target fee: **$10,000**.
- **Wholesale MAO to the seller:** `91,000 - 10,000 = 81,000`. You lock the contract at or below **$81,000**, put down **$1,000 EMD**.
- **Exit (assignment):** assign to a cash flipper for **$91,000**; end-buyer pays the $81k to the seller plus your **$10,000 assignment fee** at closing. **Profit = $10,000 on ~$1,000 at risk.**
- **If instead the house were cosmetically clean** (say ARV $180k but only **$12,000 of paint/flooring/clean-out**): assigning at 70% would force the seller to ~$114k and leave a small assignment spread. Better to **wholetail**: buy at ~$118k (hard money, 2 pts + ~10.5%), spend $12k, hold 3 months (~$2.7k carry + ~$2.4k points + ~$1.5k taxes/ins/util), sell retail at $180k, net after ~8.5% selling costs (~$15.3k) ≈ `180,000 - 15,300 - 118,000 - 12,000 - 6,600 = 28,100` → **~$28k profit** vs. a ~$6k assignment fee. That gap is the whole reason wholetail exists.

### Encode in the engine (the per-strategy max_bid formula / which grade factors change)
- **Add two strategy-specific max-bid fields** alongside `max_bid_70`:
  - `wholesale_mao = arv * disc - rehab - assignment_fee`, where `disc` is region-tuned: **0.70** metro Asheville/Greenville with `arv_confidence` high; **0.65** default Upstate/WNC; **0.60** rural mobiles / low `arv_confidence` / thin comp dispersion. `assignment_fee` scales with spread: default **$10k**, floor **$5k**, and let it rise toward **$15k–$20k** when `(arv*disc - rehab - seller_price) > 25k`.
  - `wholetail_mao = arv*(1 - selling_costs_pct) - light_rehab - holding - financing - target_profit`, with `selling_costs_pct ≈ 0.085` (agent + NC/SC deed stamps ~0.37% + title/closing ~1%), triggered only when `rehab_level == light/cosmetic` AND `arv_confidence` high AND property is financeable (not a pre-'76 mobile a retail lender won't touch).
- **Strategy router:** compute both; pick wholetail when `wholetail_profit > assignment_fee` **and** `capital_available >= wholetail_cash_in` **and** `arv_confidence >= high`; otherwise default to assignment (near-zero capital, near-zero risk).
- **Grade factors that change per strategy:** for **assignment**, grade should reward *spread cushion* (`arv*disc - rehab - seller_price`) and **penalize low `buyer_pool_depth`** (rural = downgrade, since no buyer = no fee) and low `arv_confidence` (widen the discount, don't just trust the fee). For **wholetail**, grade must fold in **DOM/market-liquidity risk, holding cost, and financeability** (mobiles and heavy-rehab houses are auto-disqualified from the wholetail grade). Also flag a **`nc_wholesale_license_required` boolean**: for NC residential 1–4 unit deals, contracts on/after **Oct 1, 2025** (HB 797) treat wholesaling as brokerage activity — public *marketing* of the property/contract now needs a license, contracts must carry a **14-pt cancellation notice** and a **non-waivable 30-day homeowner right-to-cancel**, so assignment marketing should be gated to licensed disposition or routed to double-close/private-buyer-list only. **SC** (2024 Real Estate Practice Act revisions) is similar in spirit: assigning your equitable interest to a private buyer pool is fine, but **publicly advertising a residential property you don't own requires licensure** — so keep SC residential dispo on a private buyers list, not public MLS/Zillow marketing.

**Sources:**
- [Average Wholesale Assignment Fee 2026 by Location — RealEstateBees](https://realestatebees.com/statistics/average-wholesale-assignment-fee/)
- [Real Estate Wholesale Formula / MAO 2026 — RealEstateSkills](https://www.realestateskills.com/blog/wholesale-formula)
- [70% Rule 2026 Guide — Nestwise](https://www.nestwise.us/blog/the-70-percent-rule-real-estate-calculate-ma)
- [Double Closing / Transactional Funding costs 2026 — RealEstateSkills](https://www.realestateskills.com/blog/double-closing)
- [Transactional Funding pricing — DoubleClose.com](https://www.doubleclose.com/how-it-works/)
- [NC HB 797 Residential Property Wholesaling Protection (eff. Oct 1, 2025) — NCLEG](https://www.ncleg.gov/Sessions/2025/Bills/House/PDF/H797v1.pdf)
- [NC HB797 bill summary — UNC SOG Legislative Reporting Service](https://lrs.sog.unc.edu/billsum/h-797-2025-2026)
- [Is Wholesaling Legal in North Carolina (2026) — RealEstateSkills](https://www.realestateskills.com/blog/wholesaling-real-estate-legal-north-carolina)
- [SC Regulates Wholesaling in New RE License Law — SC REALTORS](https://screaltors.org/sc-regulates-wholesaling-in-new-re-license-law/)
- [Real Estate Agent Commission 2026 — US Realty Training](https://www.usrealtytraining.com/blogs/real-estate-agent-commission)


## Fix-and-Flip

### The model (how the money is actually made, one paragraph)
A flip captures the spread between the **as-is** price you can buy a distressed property for and its **after-repair value (ARV)** once renovated, minus every dollar it costs to buy, fix, hold, borrow, and re-sell. You are not paid for the house; you are paid for the *renovation delta* net of frictional cost. In our Upstate SC / Western NC band (ARV $80k–$300k), that spread is thin in absolute dollars, so the entire game is buying deeply enough below ARV that the 6 stacked cost buckets — acquisition closing, rehab, holding, financing, selling, and a contingency — all fit inside the delta with a real profit left over. The market has cooled into 2026 (Greenville ~57–64 DOM, Asheville ~67 DOM and 106 DOM in Q1), so the exit assumption must be conservative on both **sale price** and **months-to-sell**; those two variables, plus rehab overrun, are what turn a modeled winner into an actual loss.

### The underwriting formula (the exact max-offer / MAO equation with every cost line)
The **70% Rule** is only the napkin shortcut:
```
MAO_70 = 0.70 × ARV − Rehab
```
It bakes ~30% of ARV as a blanket allowance for *all* costs + profit. It works as a first-pass filter but systematically misprices the two ends of our band — it leaves too much margin on a clean $280k Asheville flip and not enough on a $95k rural mobile where fixed costs (title, insurance minimums, loan floors) eat a bigger % of ARV. The rigorous line-item MAO is:
```
MAO = ARV
      − Rehab
      − SellingCosts            (agent + concessions + seller closing)
      − HoldingCosts            (taxes + insurance + utilities × months)
      − FinancingCosts          (points + interest × months + junk fees)
      − AcquisitionClosing      (buy-side title/attorney/recording/stamps)
      − Contingency             (10–15% of Rehab)
      − TargetProfit
```
Where, with 2026 numbers for our market:
- **SellingCosts** = agent **5.5–6.0%** of resale ([~5.88% avg SC](https://listwithclever.com/real-estate-blog/seller-closing-costs-in-south-carolina/)) + buyer-agent/closing **concessions 2–3%** (routine in a 2026 buyer's market) + seller closing **1–2%** (SC deed stamps **$3.70/$1,000** + attorney) → budget **~9–10% of ARV** all-in.
- **HoldingCosts** = property tax + hazard/vacant-build insurance (higher for unoccupied) + utilities, run over the **hold period** (rehab months + list-to-close). Budget **~$450–$700/mo** on a sub-$200k property.
- **FinancingCosts** = **2–3 points** up front + **10–11% interest-only** on drawn balance × months + processing/legal (**~$1,700 + ~$1,900**) ([Stormfield 2026](https://stormfieldcapital.com/blog/fix-and-flip-loan-rates-pricing-2026/)).
- **AcquisitionClosing** = buy-side title/attorney/recording **~1–1.5%** of purchase.
- **Contingency** = **10–15% of Rehab** (non-negotiable in older Upstate/WNC housing stock).
- **TargetProfit** = the greater of a **flat $25k floor** or **12–15% of ARV** (see grade section).

### Capital required + financing (down/EMD, hard-money points+rate 2026, holding months, total cash-in)
2026 fix-and-flip hard-money terms, verified across lenders:
- **Rate:** 9–12% interest-only; ~**10.4% avg** late-2025, competitive floors ~9.99% ([Stormfield](https://stormfieldcapital.com/blog/fix-and-flip-loan-rates-pricing-2026/), [North Coast](https://www.northcoastfinancialinc.com/hard-money-loan-interest-rates/)). Use **10.5%** as the modeling default for a mid-experience borrower.
- **Points:** **2–3** origination (1 pt only for seasoned repeat borrowers).
- **Leverage:** up to **90% LTC** (purchase) + **100% of rehab**, capped by **70% LTARV** ([OfferMarket](https://www.offermarket.us/blog/hard-money-fix-and-flip-loans)). The 70% ARV cap is the binding constraint on most deals, not the 90% LTC.
- **Term:** 12 months, interest-only, balloon.

**Cash-in the deal actually requires** = the 10% purchase down payment + all points/junk fees + acquisition closing + holding + interest reserve + rehab contingency + any rehab draw float (lender reimburses rehab in arrears, so you front each phase). On a ~$150k-ARV Upstate deal that is roughly **$28k–$36k of your own cash**, even at 90/100 leverage — the leverage covers the *loan*, not the *frictions*, and the frictions are where new flippers run dry.

**Hold period to underwrite (2026 velocity):** rehab **1.5–3 months** + list-to-under-contract **~2 months** (Greenville 57–64 DOM, Asheville ~67 DOM) + close **~30–45 days** = **model 6 months, stress-test 8**. Q1 2026 Asheville spiked to 106 DOM — for WNC deals, underwrite 7–8 months of holding + interest, not 4.

### Exit math + margins (realistic profit + the make-or-break variables)
National Q1 2026 flip ROI was **~25.4% gross** on ~$65k gross profit ([ATTOM](https://www.attomdata.com/news/market-trends/flipping/special-analysis-how-pricing-renovation-costs-and-timing-shaped-returns-in-q1-2026/)) — but that is **gross** (ARV − purchase − rehab only); **net** margins after holding/financing/selling are roughly **half** that, and 2026 was the thinnest flip environment since the Great Recession ([CNBC](https://www.cnbc.com/2026/03/24/home-flippers-see-smallest-profits-since-great-recession-data-firm-says.html)). In our price band a healthy deal nets **$20k–$40k**, i.e. **~12–18% of ARV net**. The three make-or-break variables, in order of destructive power:
1. **Resale price accuracy** — a 5% ARV miss on a $150k flip is $7.5k straight off net, often 25–35% of the whole profit. Comp discipline (recent, arms-length, same submarket, condition-adjusted) is the single highest-leverage input.
2. **Months-to-sell** — each extra month adds interest + taxes + insurance + utilities (~$1.7k–$2.2k/mo all-in on a $150k deal). Two months of 2026 slowdown = ~$4k, and it compounds carry risk. This is why WNC's 80–106 DOM readings must lower the max bid, not just the profit expectation.
3. **Rehab overrun** — older Upstate/WNC stock hides foundation, roof, septic, knob-and-tube. Contingency of 10–15% is the buffer; blowing through it converts profit to loss faster than any other line.

### A worked example (a real deal in our price band: ARV, rehab, all costs, the offer, the profit)
**3/2 ranch, Greenville County Upstate SC. ARV = $150,000. Rehab = $35,000** (cosmetic + HVAC + roof patch). Hold = 6 months. Financing at 90% LTC / 100% rehab, 2.5 points, 10.5% interest-only.

| Line | Amount | Basis |
|---|---|---|
| ARV (resale) | **$150,000** | conservative comp median |
| − Selling costs | −$14,250 | 9.5% (5.75% agent + 2.5% concession + 1.25% closing/stamps) |
| − Rehab | −$35,000 | scope of work |
| − Rehab contingency | −$4,375 | 12.5% of rehab |
| − Holding (6 mo) | −$3,600 | $600/mo tax+ins+utils |
| − Financing: points | −$2,300 | 2.5 pts on ~$92k loan |
| − Financing: interest | −$4,800 | ~$92k avg draw × 10.5% × 6 mo |
| − Financing: junk fees | −$1,700 | processing/legal |
| − Acquisition closing | −$1,200 | buy-side title/attorney |
| **= Max supportable basis** | **$82,775** | ARV minus everything except profit |
| − Target profit | −$25,000 | floor (16.7% of ARV) |
| **= Maximum Allowable Offer** | **≈ $57,800** | line-item MAO |

Napkin check: **MAO_70 = 0.70 × 150,000 − 35,000 = $70,000.** The line-item MAO ($57.8k) is **~$12k tighter** than the 70% Rule here — because a 6-month 2026 hold, real concessions, and full financing cost more than the flat 30% allowance assumes. **Buy at $57.8k, hit the model, and net profit ≈ $25k (16.7% of ARV / ~35–45% cash-on-cash on ~$30k cash-in).** Buy at the napkin $70k and the *same* deal nets ~$13k — a real profit on paper that a single month of extra DOM or a $5k rehab surprise wipes out.

### Encode in the engine (the per-strategy max_bid formula / which grade factors change)
Replace the flat `max_bid_70 = 0.70*ARV − rehab` with a **line-item flip MAO** and make each cost a market-driven parameter:
```python
def flip_mao(arv, rehab, hold_months=6):
    selling      = arv * 0.095                       # agent+concession+SC closing/stamps
    contingency  = rehab * 0.125
    holding      = hold_months * (arv*0.048/12)      # ~$600/mo at $150k ≈ 0.048/yr proxy, or explicit tax+ins+utils
    loan         = 0.90*(arv*0.40) + rehab           # est. drawn balance proxy; refine w/ actual purchase
    financing    = loan*0.025 + loan*0.105*(hold_months/12) + 1700   # points + interest + junk
    acq_closing  = 0.012 * (arv*0.40)                # buy-side, ~1.2% of purchase proxy
    target_profit = max(25000, 0.15*arv)             # $25k floor OR 15% ARV, whichever greater
    mao = arv - rehab - selling - contingency - holding - financing - acq_closing - target_profit
    return min(mao, 0.70*arv - rehab)                # never exceed the 70% LTARV lender ceiling
```
**Grade factors that must change for flip:**
- **DOM sensitivity (new):** pull county median DOM into `hold_months`. Greenville ~2 mo list + rehab; **WNC/Asheville forces hold_months = 7–8** (Q1 106 DOM). Longer hold → lower MAO → downgrade. This is the biggest single change.
- **Profit-floor as a percent, not flat:** on sub-$120k ARV, `max(25000, 0.15*arv)` protects against fixed costs eating a low-dollar deal; on $250k+ ARV it scales profit up so the grade rewards bigger absolute spreads.
- **Rehab-confidence multiplier:** widen `contingency` to 15% (from 12.5%) when property age > 40 yrs or specs are GIS-estimated rather than inspected — common in rural Upstate/WNC stock — which lowers MAO and grade on the riskiest rehabs.
- **ARV-confidence gate:** flip grade should be **capped at B** whenever `arv_confidence` is low/noisy, because a 5% ARV miss is decisive at this margin; only high-confidence comps earn an A.
- **Hard ceiling:** always clamp to `0.70*ARV − rehab` so the engine never bids above what a 2026 hard-money lender will actually fund at 70% LTARV.

Sources: [Stormfield Capital 2026 fix-and-flip pricing](https://stormfieldcapital.com/blog/fix-and-flip-loan-rates-pricing-2026/), [OfferMarket 2026 hard money guide](https://www.offermarket.us/blog/hard-money-fix-and-flip-loans), [North Coast Financial rates](https://www.northcoastfinancialinc.com/hard-money-loan-interest-rates/), [ATTOM Q1 2026 flip returns](https://www.attomdata.com/news/market-trends/flipping/special-analysis-how-pricing-renovation-costs-and-timing-shaped-returns-in-q1-2026/), [CNBC flip-profit 2026](https://www.cnbc.com/2026/03/24/home-flippers-see-smallest-profits-since-great-recession-data-firm-says.html), [SC seller closing costs](https://listwithclever.com/real-estate-blog/seller-closing-costs-in-south-carolina/), [Greenville market update](https://www.greenvillerealestatehub.com/blog/greater-greenville-sc-real-estate-market-update-march-2026/), [Asheville/Buncombe Q1 2026 market](https://mymosaicrealty.com/blog/posts/2026/05/13/asheville-real-estate-market-update-insight-into-the-1st-quarter-2026-housing-market/).


## BRRRR (Buy · Rehab · Rent · Refinance · Repeat)

### The model (how the money is actually made, one paragraph)
BRRRR is not an exit — it is a *capital-recycling* strategy. You buy distressed, force appreciation through rehab, stabilize with a tenant, then do a **cash-out refinance** against the new (higher) appraised value. The refi loan pays off your acquisition + rehab debt and, if the deal was bought right, returns most or all of your original cash so you can redeploy it into the next property. The profit is not a lump sum at sale; it is (1) the *trapped equity* you keep (ARV minus the new loan), (2) *monthly cash flow* the tenant pays after the new mortgage, and (3) long-term amortization/appreciation on a property you now own with little or none of your own money left in. The entire strategy lives or dies on one number: **all-in cost ≤ 75% of ARV**, because a DSCR cash-out refi in 2026 tops out at 75% LTV — so if your all-in is at or below 75% ARV, the refi hands back 100% of your cash ("infinite return"); every dollar above 75% is cash you leave stranded in the deal.

### The underwriting formula (the exact max-offer / MAO equation with every cost line)
The BRRRR max offer is the **75%-ARV all-in cap, worked backwards** to a purchase price. The binding constraint is that everything you spend before the refi must fit under 75% of ARV:

```
All-In Cost = Purchase + Rehab + Buy-Side Closing + Holding + HML Points + HML Interest
Refi Loan Proceeds = 0.75 × ARV        (DSCR cash-out cap, 2026)
Cash Left In = All-In Cost − (Refi Proceeds − Refi Closing Costs)

BRRRR MAO (max purchase) solved for a full-capital-return deal:

  MAO_brrrr = 0.75 × ARV
              − Rehab
              − Buy-Side Closing        (title/attorney/recording/EMD-related ≈ 2% of price)
              − Holding Costs           (taxes, insurance, utilities over rehab+season months)
              − HML Points              (2–3% of the hard-money loan)
              − HML Interest            (rate/12 × loan × months held)
              − Refi Closing Costs      (lender/title/appraisal ≈ 3–4% of the refi loan)
              − Desired Cash Left In    (set to $0 for a "true" BRRRR; raise it to buy a better house)
```

Note this is **stricter than the 70% flip rule after accounting for carry** — the extra 5% of ARV headroom (75% vs 70%) is consumed by two rounds of financing cost (hard money *and* refi) that a flip doesn't pay. In practice you set `Desired Cash Left In` to $0 and treat any negative slack as "how much I must beat asking by."

### Capital required + financing (down/EMD, hard-money points+rate 2026, holding months, total cash-in)
**Acquisition + rehab (hard money, 2026 terms):**
- Leverage: HML funds **~85–90% of purchase + 100% of rehab**, underwritten to **65–75% of ARV**. Experienced borrower band Q2 2026.
- Rate: **9%–12%** interest-only (use **10.5%** as the modeling default for a repeat borrower); premier borrowers 8.5–11.25%.
- Points: **2–3%** origination on the loan (use **2.5%**).
- Term: 6–18 months, interest-only, balloon at refi.
- **Down payment/skin:** ~10–15% of purchase + all closing/carry out of pocket. On our price band that's roughly **$12k–$30k cash** to get in.

**Holding period:** rehab (1.5–3 mo) + lease-up (0.5–1 mo) + **6-month seasoning** the DSCR lender requires before it will lend on *appraised* value instead of cost. Budget **6–8 months of carry** even if the rehab is fast — the seasoning clock is the real gate.

**Refinance (DSCR, 2026 terms):**
- **75% LTV** cash-out cap on a stabilized SFR (700+ FICO, DSCR ≥ 1.0).
- Rate: fixed **6.5%–7.5%** (cash-out sits 0.25–0.50% above rate-and-term; use **7.25%** for a 75% cash-out on a small rural loan — small-balance and rural add spread).
- 30-yr amortization (or 40-yr / IO to juice DSCR), ~3–4% closing costs rolled or paid.
- Requires DSCR ≥ 1.0–1.25: **NOI ÷ new PITI must clear 1.0**, or the lender caps LTV below 75% and you leave more cash in.

**Total cash-in** on a clean deal = down payment + buy closing + carry + points + refi closing, *minus* refi cash-out. On a bought-right deal this nets to **near $0**; on a typical real deal expect **$8k–$20k left in**.

### Exit math + margins (realistic profit + the make-or-break variables)
BRRRR "profit" is three streams, not a sale check:
1. **Trapped equity kept** = ARV − Refi Loan = **25% of ARV** you own free (e.g., $37.5k on a $150k ARV). This is real net worth but illiquid until sale/HELOC.
2. **Monthly cash flow** = Rent − PITI − Reserves, where **Reserves ≈ 10% vacancy + 8% maintenance + 8% capex + ~8% management = ~30–35% of gross rent** gets consumed before/around debt service.
3. **Amortization + appreciation** on a property with little of your cash left in → the "infinite return" once cash-in hits $0.

**Make-or-break variables, in order of lethality:**
- **The refi appraisal (ARV).** The whole model assumes the appraiser agrees with your ARV. A 10% miss ($150k→$135k) drops your 75% loan from $112.5k to $101k — **$11k more cash trapped**, instantly killing the "repeat."
- **DSCR ≥ 1.0.** In our low-rent rural pockets a $1,440 rent against a 7.25% PITI on a ~$110k loan is *tight*. If DSCR < 1.0 the lender cuts LTV and you leave cash in regardless of value.
- **The 1% rule vs. our reality.** The old "rent ≥ 1% of price/month" heuristic is **mostly unmet in our footprint**: a $150k ARV would need $1,500/mo. Greenville-Mauldin-Easley 3BR FMR is **$1,440** (~0.96%), Spartanburg 3BR **$1,640** (~1.09% — the one market that clears it), Asheville/Buncombe 3BR **$2,160** but against $250k–$300k values (~0.72–0.86%). **Metro Asheville and metro Greenville do NOT hit 1%**; the strategy still works there on *equity* and appreciation, but the *cash-flow* leg is thin-to-negative and must be underwritten conservatively. **Spartanburg and rural Upstate SC are the true cash-flowing BRRRR markets.**

### A worked example (a real deal in our price band: ARV, rehab, all costs, the offer, the profit)
**Spartanburg County 3/1 SFR, ~1,150 sqft, tax-delinquent lead.**

| Line | Amount |
|---|---|
| **ARV** (comped, arms-length, ≤6mo) | **$150,000** |
| Rehab (roof patch, HVAC, kitchen/bath refresh, paint/floor, mechanicals) | $30,000 |
| Buy-side closing (~2% of price) | $2,400 |
| Holding — 7 mo (taxes+ins+utils ≈ $450/mo) | $3,150 |
| HML points (2.5% on ~$135k loan) | $3,375 |
| HML interest (10.5% IO, ~$135k avg draw, 7 mo) | $8,270 |
| Refi closing (~3.5% of $112.5k) | $3,940 |
| **Total non-purchase costs** | **$51,135** |

**Solve the MAO (target $0 cash left in):**
`MAO = 0.75 × 150,000 − 51,135 = 112,500 − 51,135 = $61,365` → **offer ≈ $61,000.**

**The deal at a $61,000 purchase:**
- **All-in** = 61,000 + 30,000 + 2,400 + 3,150 + 3,375 + 8,270 = **$108,165** (72.1% of ARV ✓ under 75%).
- **DSCR cash-out** = 0.75 × 150,000 = **$112,500** loan; minus $3,940 refi cost = **$108,560** net proceeds.
- **Cash left in** = 108,165 − 108,560 = **−$395 → ~$0. You pull 100% of your capital back out.**
- **Equity kept** = 150,000 − 112,500 = **$37,500** owned.
- **Cash flow check:** rent **$1,640** (Spartanburg 3BR FMR). New PITI on $112,500 @ 7.25%/30yr = $767 P&I + ~$210 taxes/ins = **~$977**. Rent − PITI = **$663**; minus ~30% reserves ($492) = **~$171/mo true cash flow** with **DSCR ≈ 1.68 on P&I** (easily clears the 1.0 floor → 75% LTV holds).

Result: ~$0 of your money left in a property you own with **$37.5k equity** and **~$170/mo** cash flow → **infinite cash-on-cash, repeat**. Run the identical deal at a $150k Asheville rent-to-value and the equity leg still works but cash flow goes flat/negative — flag those as *equity-play BRRRR*, not *cash-flow BRRRR*.

### Encode in the engine (the per-strategy max_bid formula / which grade factors change)
Add a distinct `max_bid_brrrr` alongside `max_bid_70`:

```python
# Strategy-specific BRRRR max bid (targets $0 cash left in via 75% DSCR cash-out)
REFI_LTV        = 0.75          # DSCR cash-out cap, 2026
HML_POINTS      = 0.025
HML_RATE        = 0.105
HML_MONTHS      = 7             # includes 6-mo seasoning gate
REFI_CLOSE_PCT  = 0.035
BUY_CLOSE_PCT   = 0.02
HOLD_PER_MO     = 0.003 * arv   # taxes+ins+utils proxy, ~0.3%/mo of ARV

hml_loan   = purchase * 0.88 + rehab            # 88% purchase + 100% rehab
carry      = HML_MONTHS * HOLD_PER_MO
hml_cost   = HML_POINTS * hml_loan + HML_RATE/12 * hml_loan * HML_MONTHS
refi_proc  = REFI_LTV * arv * (1 - REFI_CLOSE_PCT)

# solve purchase so all-in == refi proceeds (cash_left_in = 0):
max_bid_brrrr = (refi_proc - rehab - carry - hml_cost) / (1 + BUY_CLOSE_PCT)

engine_max_bid = min(max_bid_70, max_bid_brrrr)   # most conservative binds
```

**Grade-factor changes for the BRRRR path (in addition to ARV confidence and equity):**
- **`rent_to_value` (new, decisive):** compute `monthly_rent / ARV`. Grade **A ≥ 1.0%**, **B 0.85–1.0%**, **C 0.70–0.85%**, **D < 0.70%**. Source `monthly_rent` from HUD SAFMR 3BR by county (Spartanburg $1,640, Greenville-Mauldin-Easley $1,440, Buncombe $2,160, else state 3BR FMR).
- **`dscr_at_refi` (new gate):** `NOI / new_PITI` at 75% LTV & 7.25%. If **< 1.0 → downgrade one letter and cut effective refi LTV** in the max-bid solve until DSCR = 1.0 (this raises cash-left-in and lowers the bid automatically).
- **`cash_left_in` (new output):** `all_in − refi_net_proceeds`. Grade **A ≤ $0**, **B ≤ $10k**, **C ≤ $20k**, **D > $20k** (a "trapped-capital" deal, not a true BRRRR).
- **Reweight vs. flip:** BRRRR tolerates a **higher all-in ceiling (75% vs 70% ARV)** but is **more sensitive to ARV-appraisal risk and rent** — so `arv_confidence` and `rent_to_value` should carry more weight in the BRRRR grade than in the flip grade, while raw spread carries less.
- **Tag the sub-type:** if `rent_to_value ≥ 0.9%` label **cash-flow BRRRR**; if `< 0.9%` but equity kept ≥ 20% ARV label **equity-play BRRRR** (Asheville/metro-Greenville) so the operator knows the cash-flow leg is thin.

Sources: [DSCR Loan Rates 2026 (sistarmortgage)](https://sistarmortgage.com/blog/dscr-loan-requirements-and-rates), [DSCR rates June 2026 (HomeAbroad)](https://homeabroadinc.com/mortgages/dscr-loan-interest-rates/), [Fix-and-Flip Financing 2026 / 70% rule](https://www.ownluxuryhomes.com/markets/national/real-estate-investing/fix-and-flip-financing-2026), [Hard Money Loan Rates 2026 (Crestmont)](https://www.crestmontcapital.com/blog/hard-money-loan-rates-2026), [2026 Section 8 FMR SC (BNBCalc)](https://www.bnbcalc.com/section8/sc), [Buncombe County FMR (USHousingData)](https://www.ushousingdata.com/fair-market-rents/buncombe-county-nc)


## Subject-To / Seller-Finance (wrap)

### The model (how the money is actually made, one paragraph)
The play is to acquire a distressed property **without paying off or refinancing the existing mortgage** — you take title (subject-to) or create a wrap note over it and keep the seller's legacy loan alive at its below-market rate. In 2026 the market rate is ~6.4–6.5% (Freddie Mac 30-yr avg 6.43% on 7/2/2026), but a huge overhang of 2020–2022 loans sits at 2.5–4%. That rate gap is the whole business. There are two distinct exits from the same acquisition: **(A) Buy-and-hold rental** — you inherit a $500–650/mo payment on a house that rents for $1,300–1,800 in Upstate SC / Western NC, so the sub-4% loan makes a marginal deal cash-flow like a paid-down one; the "profit" is the spread between market-rate debt service and the actual legacy payment, capitalized over the hold. **(B) Wrap / seller-finance flip** — you resell to a credit-challenged, self-employed, or foreign-national buyer on a new note at 8.5–10%, collect a down payment, and pocket the **monthly interest spread** between the wrap note you collect and the underlying loan you pay, plus a markup on price. Either way you acquire *near payoff* (little to no equity purchase price), because the value to the seller is debt relief and foreclosure-stopping, not a cash check.

### The underwriting formula (the exact max-offer / MAO equation with every cost line)
The binding constraint is **cash to close**, not ARV×0.70. Subject-to has no acquisition loan, so max offer is what you pay the seller in cash on top of taking over the debt:

```
Cash_to_Seller_MAX = Equity_Capture_Budget − Arrears − Reinstatement_Costs − Transfer/Closing − Repairs_to_Rentable
where:
  Equity_Capture_Budget = (ARV − Loan_Balance) × Capture_Fraction   # you never pay full equity; 0.30–0.50 typical, often $0–$3k "moving money"
  Arrears                = missed payments + late fees (why they're selling)
  Reinstatement_Costs    = attorney/foreclosure fees already accrued, if in default
  Transfer/Closing       = deed prep, recording, title, insurance re-write (~$1,500–2,500)
  Repairs_to_Rentable    = make-ready only (NOT full ARV rehab) for the hold; full rehab if wrap-flip to owner-occ
```

For the **wrap-flip exit**, the pricing equation flips to the note you originate:

```
Wrap_Note = Sale_Price_to_End_Buyer − Buyer_Down_Payment
Monthly_Spread = P&I(Wrap_Note @ wrap_rate, wrap_amort) − P&I(Underlying_Balance @ legacy_rate, remaining_term)
Equity_Markup  = Sale_Price_to_End_Buyer − (Loan_Balance + Your_Cash_In)
```

The deal is a GO only if the underlying loan **balance ≤ ~75% of ARV** (you need spread room to resell above it) AND the legacy rate is ≥ ~250 bps below the 6.4% market (i.e. ≤ ~4%) — below that threshold the spread evaporates and it's just a hard flip.

### Capital required + financing (down/EMD, hard-money points+rate 2026, holding months, total cash-in)
This strategy's edge is that it is **low-cash and needs no hard money** — the existing loan *is* the financing. Cash-in per deal:
- **Cash to seller:** $0–$5,000 (moving money / equity capture) in a true distressed/low-equity deal; up to $10–15k if there's real equity to buy.
- **Arrears/reinstatement:** the make-or-break line — $3,000–$12,000 to bring a defaulted Upstate/WNC loan current (roughly 3–8 missed payments at $500–900 + fees).
- **Closing/transfer + insurance rewrite + servicing setup:** ~$2,000–$3,500. Use a **third-party servicer** (e.g. an RMLO/licensed servicer at ~$20–35/mo + setup) so payments to the underlying lender are documented and the buyer's taxes/insurance are escrowed.
- **Make-ready repairs:** $0–$10,000 for a rental hold; a full rehab only if you're wrapping to an owner-occupant who's financing the fix into the price.
- **Holding:** near-zero true "hold" — the tenant or wrap buyer covers debt service from month one. Vacancy risk is the exposure, ~1–3 months of the ~$500–900 payment as reserve.

**Total realistic cash-in per deal: $6,000–$20,000**, versus $40k–$90k+ on a hard-money BRRRR/flip of the same house. If you ever *do* need short-term capital (double-close on a wrap), 2026 hard-money is ~**10–12% + 2–3 points**, 6–9 month terms — but the correct structure avoids it entirely.

### Exit math + margins (realistic profit + the make-or-break variables)
- **Hold exit:** the profit is the **debt-cost arbitrage**. A $130k-value house with a $110k loan at 3.5% carries ~$494/mo P&I; the same balance at today's 6.4% would cost ~$688/mo — a **~$194/mo synthetic cash-flow gift (~$2,300/yr)** on the debt alone, *plus* normal rent-minus-expense cash flow, *plus* amortization and appreciation. You're effectively buying a below-market-financed rental for a few thousand in reinstatement.
- **Wrap-flip exit:** three profit streams — (1) **down payment** collected up front (5–10% of sale price = $6.5k–$16k), (2) **monthly interest spread** for the life of the note, (3) **back-end** when the buyer refis or the note pays off. Per the 2026 wrap benchmark: underlying $120k @ 3.5% = $539/mo, wrap note $160k @ 9% = $1,343/mo, a **$804/mo spread ($9,648/yr)** the servicer forwards to you.
- **Make-or-break variables:** (1) **the legacy rate & balance** — if it's not ≤4% and ≤75% LTV of ARV, the model dies; (2) **arrears size** — a loan $15k in the hole can wipe your equity capture; (3) **due-on-sale**, addressed below; (4) **wrap-buyer default/re-marketing** — you must be able to re-take and re-sell; (5) **insurance** — the policy must be rewritten or the lender may be alerted on renewal.

### The due-on-sale risk (real vs rare) and how operators mitigate
The due-on-sale clause lets the lender **accelerate** (call the full balance) on transfer of title. It is **real but rarely exercised while payments stay current** — banks want the performing payment, not a foreclosure and litigation; enforcement historically has been near-zero on on-time loans. It is a *contract acceleration right, not fraud* (so long as you don't lie on an application), but it is a genuine tail risk that rises when rates are high — in 2026 a lender has a real incentive to recall a 3.5% loan and re-lend at 6.4%, so treat the risk as **materially higher than the pre-2022 lore suggests**. Mitigations operators stack:
1. **Garn-St. Germain land trust:** deed the property into a trust *with the original borrower as beneficiary* (an inter-vivos trust transfer is an expressly exempt transfer under Garn-St. Germain), then quietly assign beneficial interest to your LLC. This lowers the *visibility* of the transfer; note the assignment of beneficial interest to a non-borrower is technically outside the exemption, so it reduces detection, not the underlying legal right.
2. **Third-party servicer & keep it current:** never miss a payment; a servicer that remits from a neutral account avoids the "who is this new payer" flag.
3. **Insurance handled correctly:** add your entity as *additional insured* rather than swapping the named insured off, which is the #1 way lenders discover a subject-to.
4. **Reserves for acceleration:** hold enough (or a refi/liquidation plan) to pay off or resell within 30–60 days if a call notice ever comes. Underwrite every subject-to as if it *could* be called.

### The seller-finance / wrap variant and legal-disclosure care in SC / NC
The wrap is the **resale** leg: you sell to an end buyer and carry a note that wraps the underlying loan. This triggers federal and state consumer-lending law that raw subject-to does not:
- **Dodd-Frank / SAFE Act:** selling to an **owner-occupant** in a 1–4 unit property makes you a creditor. Under the **3-property exemption** you may finance ≤3 properties/12 months without an MLO license only if the note is **fully amortizing (no balloon)**, fixed or ARM-fixed-for-5+-years with rate caps, and you **document the buyer's ability to repay**. Sell to **investors/non-owner-occupants** and Dodd-Frank's owner-occupant rules don't attach — a common structuring lane. To scale beyond 3/year, originate through a **licensed RMLO** who runs the ATR/QM underwriting; both SC (Office of the Commissioner of Consumer Finance / BFI) and NC (NCCOB) license via NMLS and treat repeat seller-financing as mortgage activity.
- **State licensing:** SC and NC both require NMLS mortgage-broker/MLO licensing for anyone in the business of originating residential loans; a one-off owner-occupant wrap can fit the exemption, a program cannot — use an RMLO.
- **Disclosure:** both states mandate a **Residential Property Condition Disclosure** on 1–4 unit transfers (SC RPCDS; NC RPOADS under G.S. Ch. 47E) — required even on installment/land-contract and option transfers in NC, so subject-to and wrap conveyances are **not** exempt. Failure to disclose known defects is independent litigation exposure. Convey by **warranty deed + deed of trust + promissory note**, record properly, and close through a **real-estate attorney** (both are attorney-close states in practice) to keep title clean and the disclosure trail defensible.

### Encode in the engine (the per-strategy max_bid formula / which grade factors change)
Add `subject_to` and `wrap` as distinct exit strategies with their own bid + grade logic instead of routing through `max_bid_70`:

```python
# Gate: only score subject-to/wrap when the underlying loan is known and cheap
subto_eligible = (loan_balance is not None
                  and legacy_rate is not None
                  and legacy_rate <= 0.045                       # ≤4.5%, ~250bps under 6.4% mkt
                  and loan_balance <= 0.75 * arv)                # spread + resale room

# Subject-to (hold) max cash to seller — NOT ARV*0.70
capture_frac = 0.35                                             # tune 0.30–0.50
max_cash_to_seller = max(
    0,
    (arv - loan_balance) * capture_frac
      - arrears                                                 # missed pmts + fees (NEW field)
      - reinstatement_costs                                    # accrued FC/attorney (NEW field)
      - transfer_closing_cost                                  # ~2000
      - make_ready_repairs                                     # rentable, not full ARV rehab
)

# Wrap (seller-finance flip) economics
wrap_note      = sale_price_to_end_buyer - buyer_down_payment
monthly_spread = pmt(wrap_note, wrap_rate=0.09, term=360) \
               - pmt(loan_balance, legacy_rate, remaining_term)
wrap_annual_yield = (buyer_down_payment + monthly_spread*12) / cash_in
```

**Grade-factor changes for these strategies:**
- **Replace the equity/discount factor** (`discount_to_arv`) with a **rate-spread factor**: `spread = market_rate(0.064) − legacy_rate`; grade A if ≥ 0.030, B if 0.020–0.030, F if < 0.015 or `loan_balance` unknown.
- **Add a `cash_light` bonus:** low `total_cash_in` (< $12k) upgrades the grade — this is the strategy's core advantage vs BRRRR.
- **Add an `arrears_ratio` penalty:** `arrears / (arv − loan_balance)`; > 0.5 downgrades (arrears eating the equity capture).
- **Add a `due_on_sale_risk` flag** (informational, not disqualifying): raise it when `legacy_rate < 0.045` AND balance is large — the very deals worth doing carry the most call risk; require a reserves note.
- **Add an `owner_occupant_wrap` compliance flag:** if exit = wrap to owner-occupant, force `no_balloon = True` and surface the 3-property/RMLO gate so the engine never grades a non-compliant note as A.
- **LTV-of-ARV cap** replaces the 70% rule: reject when `loan_balance > 0.75 * arv` (no room to wrap/resell above the debt).

**Sources:** [Norada – Due-on-Sale & Land Trusts](https://www.noradarealestate.com/blog/due-on-sale-clause/); [Royal Legal Solutions – Land Trust / Garn-St. Germain](https://royallegalsolutions.com/whats-the-due-on-sale-clause-how-do-i-avoid-it-with-a-land-trust/); [The Property CEO – Wraparound Mortgage 2026 Guide](https://thepropertyceo.com/blog/wraparound-mortgage-guide); [Deal Run – Wraparound Mortgages for Investors](https://dealrun.ai/blog/wrap-mortgage-explained); [Barnes Walker – Dodd-Frank Seller-Financing Restrictions](https://barneswalker.com/seller-financing-restrictions-under-the-dodd-frank-act/); [NoteInvestor – Dodd-Frank / SAFE Act owner financing](https://noteinvestor.com/notes-101/owner-financing-laws-dodd-frank-safe-act/); [Mack & Mack Law – Seller Financing in South Carolina](https://www.mackandmacklaw.com/blog/2024/12/seller-financing-in-south-carolina-what-you-must-know/); [NCCOB – Mortgage Lender/Broker Licensing](https://nccob.nc.gov/financial-institutions/mortgage/licensing-information/mortgage-lender-broker-licensing-requirements); [Freddie Mac PMMS / US News – 6.43% 30-yr, 7/2/2026](https://www.usnews.com/news/business/articles/2026-07-02/average-30-year-us-mortgage-rate-falls-to-6-43-its-lowest-level-in-seven-weeks).


## Gator Lending (Transactional Funding, EMD Funding & Gap/Private Lending)

### The model (how the money is actually made, one paragraph)
The "gator" (Pace Morby's coinage) does not buy houses or find sellers. He rents his capital to the wholesalers, flippers, and creative-finance investors who do, for hours or days at a time, and gets paid a fee that is enormous as an annualized yield precisely because the hold is so short. Three products: (1) **EMD funding** — advancing the earnest-money deposit so an investor can lock a contract they can't yet fund, repaid at closing plus a flat fee; (2) **transactional / double-close funding** — wiring the full A-to-B purchase price for a same-day A-B-C double close so the wholesaler never uses their own money, repaid the same day out of the C (end-buyer) proceeds; and (3) **private / gap lending** — filling the shortfall between a hard-money loan and total project cost for a rehabber, secured by a note. The gator's edge is not construction skill or negotiation, it is (a) liquid cash on standby and (b) underwriting the *deal and the borrower* well enough that the money comes back. A data-rich operator wins here because the same lead database that sources motivated sellers also tells you which of the wholesalers working your market have real, closeable deals worth funding — you can verify the underlying property, the ARV, and the equity before your money ever leaves escrow.

### The underwriting formula (the exact max-offer / MAO equation with every cost line)
The gator has no "max bid" on a property — he has a **max exposure per deal** and a **fee floor per dollar-day of capital**. Two things must be true before funding:

**1. Fee must clear the floor (transactional/double-close):**
```
Gator_fee          = max( flat_min , fee_pct × A_to_B_price )   [+ per-diem × days if hold > 0]
Effective_yield    = Gator_fee / A_to_B_price × (365 / hold_days)
FUND  IF  Gator_fee ≥ fee_floor  AND  Effective_yield ≥ target_annualized_yield
```

**2. Capital must be genuinely covered by a real end buyer (the risk gate):**
```
C_price (end buyer, funds committed)  ≥  A_to_B_price + Gator_fee + B_side_closing_costs
Exposure_hours                        ≤  same-day for double close (A and C fund same table)
```

**For EMD funding**, the equation is a downside/refundability test, not an LTV test:
```
EMD_fee   = max( flat_min ($150–$500) , deposit_pct (10–20%) × EMD_amount )
Fund IF:  contract still inside inspection/DD window (EMD refundable)  →  worst case = deposit returned
          AND spread_to_C ≥ EMD_amount (buyer can absorb a lost deposit)
          AND lien/title clean enough that A-B will actually close
```

**For gap/private lending** it reverts to a true ARV-based ceiling, protecting the position behind the senior hard-money loan:
```
Senior_HML + Gator_gap_note  ≤  0.75 × ARV      (combined LTV cap ~70–75%)
Gator_gap_note                =  (Purchase + Rehab) − Senior_HML_proceeds
Fund IF combined CLTV ≤ 0.75 × ARV  AND  exit (flip sale or refi) clears both notes
```

### Capital required + financing (down/EMD, points+rate 2026, holding months, total cash-in)
The gator *is* the capital — his "cash-in" is the money he fronts, and his hold is measured in days, not months.

| Product | Cash the gator fronts | What he charges (2026) | Hold |
|---|---|---|---|
| **EMD funding** | $1,000–$25,000 (typical SFR EMD $1k–$10k) | Flat **$150–$500**, or **10–20% of deposit**; per-diem ~**$25/day per $5k** | Days to ~2 weeks |
| **Transactional / double close** | Full A-B price (in our band **$60k–$220k**) | **1% of A-B, $750 minimum**; tiers to 2% above $1M; some 1.5–3% | **Same day** (hours) |
| **Gap / private lending** | The shortfall, often $10k–$60k | Note at **10–14% + 1–3 points** (2026 private-money) | 3–9 months |

Because a compliant double close funds A and C at the **same escrow table on the same day**, the gator's actual dollars-at-risk exist for hours; the 1% fee is a ~365%+ annualized yield on that capital. EMD funding ties up smaller amounts for a few days at a flat fee that is often **another triple-digit annualized return**. The gator needs no hard-money leverage of his own — this is *his* dry powder deployed directly.

### Exit math + margins (realistic profit + the make-or-break variables)
The gator's "exit" is repayment out of escrow proceeds, booked as a line item on the settlement statement — he is paid before the wholesaler nets anything.

- **Transactional profit per deal:** 1% of A-B. On a $120k A-B that is **$1,200 for a few hours of capital**; on a sub-$75k deal the **$750 minimum** dominates and the *yield* is even higher. A gator recycling $150k of capital through 2–4 double closes a month books **$2,400–$6,000/mo** on the same dollars.
- **EMD profit per deal:** **$150–$1,000** flat per advance; a gator funding 15–20 EMDs a month runs **$3k–$12k/mo** on capital that mostly comes back within a week.
- **Gap-lending profit:** 10–14% + points on a 3–9 month note — e.g., $40k gap at 12% + 2 pts = **$800 + ~$2,400 = ~$3,200 over ~6 months**, with a recorded lien as security.
- **The make-or-break variables, in order:**
  1. **Does the C-side buyer actually close?** For a double close this is existential — if the end buyer doesn't fund, the gator owns a house he never wanted. *Rule: no committed, proof-of-funds end buyer, no funding.*
  2. **Is the EMD refundable when you advance it?** Fund inside the inspection window and the worst case is the deposit is simply returned. Fund a non-refundable EMD and a dead deal = **100% loss of the advance.**
  3. **Title/lien surprises** on the A-side that blow the closing date and turn a same-day hold into a multi-week one (per-diem is the hedge).
  4. **Borrower quality** — a wholesaler with a fake or wildly-optimistic ARV. This is exactly where a lead-engine operator has an unfair edge: verify the parcel, comps, and equity independently before wiring.

### A worked example (a real deal in our price band)
A wholesaler in Anderson County SC has a contract on a 3/2 SFR. He does not have the cash to close A-B and wants a double close.

- **ARV (verified against comps):** $185,000
- **A-B price (his contract with the seller):** **$120,000**
- **C price (his end-buyer, a flipper, POF confirmed):** **$132,000**
- **Rehab (end buyer's problem, not the gator's):** ~$30,000
- **Wholesaler's gross spread:** $132k − $120k = $12,000, minus double-close costs (~$3,500) ≈ **$8,500 net to him**

**Gator's side of the same deal:**
- Capital fronted (A-B wire): **$120,000**, funded and repaid the **same day** through escrow
- Transactional fee at **1%** of A-B: **$1,200**
- Dollars-at-risk duration: hours; downside gated because C-side POF + committed buyer verified *before* funding
- **Gator profit: $1,200 per deal**, ≈ **365%+ annualized** on the $120k for the hours it was out. Fund this wholesaler's next three deals the same month on the same recycled $120k → **~$3,600/mo** with the principal never permanently committed.

Contrast an **EMD-only** version of the same deal: wholesaler needs a $5,000 EMD to lock the contract, gator advances it for a **$500 flat fee** (10%), repaid at the A-B closing 10 days later. **$500 for 10 days on $5,000 = ~365% annualized**, worst case (deal dies inside DD) the deposit comes back.

### Encode in the engine (the per-strategy max_bid formula / which grade factors change)
Gator lending is **not a max_bid strategy** — the property is a counterparty's, not ours. In the engine, add it as a **capital-deployment / origination scoring** lane keyed off deals *other people* are chasing, not off `max_bid_70`:

- **Do NOT compute** `max_bid_70` or `wholesale_mao` for gator rows; those exit-price ceilings are irrelevant. The engine's role flips from "what do I offer" to "should I fund this and at what fee."
- **New per-deal outputs:**
  - `gator_txn_fee = max(750, 0.01 * a_to_b_price)` — floored at $750, the 2026 market minimum.
  - `gator_emd_fee = max(150, clamp(0.10..0.20) * emd_amount)`.
  - `gator_effective_yield = gator_fee / capital_fronted * (365 / hold_days)` — the gating metric; reject below `TARGET_YIELD` (set high, e.g. 100%+, since holds are ~1 day).
  - `gator_max_exposure` — a hard per-deal cash cap = min(available_dry_powder, policy_cap).
- **Grade factors that change (the fundable-signal, replacing property-condition weighting):**
  - **Equity cushion of the underlying deal** (our existing `arv_confidence` and comps sidecar feed this) — high confidence that ARV > C-price makes the deal safe to fund. This *raises* grade.
  - **Spread integrity:** `C_price − A_to_B_price − gator_fee > 0` must hold, and the spread must exceed the EMD amount for EMD deals. Fail = auto-reject, drop to F.
  - **End-buyer / exit certainty** — a new binary factor: `end_buyer_committed` (POF verified). For transactional funding this is weighted highest; absent it, grade is capped low regardless of equity.
  - **Refundability window** (EMD only) — `emd_refundable == true` at funding is a required gate; funding a non-refundable EMD downgrades the grade sharply because downside becomes total loss.
  - **Title/lien cleanliness of the A-side parcel** (from our ROD/assessor enrichment) — open senior liens or clouded title that threaten the same-day close lower the grade and push toward per-diem pricing to hedge slippage.
  - **Counterparty reliability** — a light reputation weight on the wholesaler; the engine's independent parcel/ARV verification is the substitute for trusting their numbers.

Net: for gator rows the engine stops asking "how low must I buy" and starts scoring **fee-yield × downside-coverage**, where downside coverage = verified equity + committed end buyer + (for EMD) refundability. These are the only factors that move the grade.


## Buy-at-Auction + Surplus-Funds Recovery

### The model (how the money is actually made, one paragraph)
This is two distinct businesses that share a data source (the foreclosure sale roster), and the engine should score them separately. **Sub-model A — buy-at-auction** is all-cash (or hard-money) acquisition of the deed on the courthouse steps at a discount to ARV, followed by a flip or hold; the edge is that most retail buyers can't or won't show up with certified funds and can't underwrite title risk, so the winning bid sits well below open-market value. Money is made on the spread between the auction price and the resale, net of everything you inherit (surviving senior liens, redemption exposure, eviction, unknown condition). **Sub-model B — surplus-funds recovery** is a *finder/recovery* business, not a real estate deal: when a foreclosure sale price exceeds the total debt + costs, the overage legally belongs to the former owner (then junior lienholders in priority), but the money sits with the court/clerk unclaimed. You locate the ex-owner, sign a contingency-fee recovery agreement, file the claim, and take a capped percentage. Zero property risk, near-zero capital, but heavily statute-regulated and margin-capped.

### The underwriting formula (the exact max-offer / MAO equation with every cost line)

**Sub-model A — auction max bid.** The auction max bid is *stricter* than a standard 70% MAO because you buy blind, inherit senior liens, and often eat redemption/eviction cost. Use:

```
MaxBid_auction = ARV
              − Rehab
              − SurvivingSeniorLiens        (1st-position taxes, senior mortgage, IRS/state liens that survive)
              − RedemptionReserve            (SC tax-derived title only; see below)
              − EvictionHoldover             ($2,500–$6,000: cash-for-keys + filing + lost months)
              − TitleCureReserve             ($1,500–$5,000: quiet-title / lien discharge)
              − SellingCosts                 (0.08 × ARV: agent 5% + SC/NC deed stamps + closing)
              − FinanceCarry                 (points + interest over hold, if hard-money)
              − TargetProfit                 (auction risk premium: 20–25% of ARV, NOT the 15% you'd accept on a negotiated deal)
```

The two lines that break auction deals and that a wholesale MAO ignores are **SurvivingSeniorLiens** and **RedemptionReserve**. Which liens survive is entirely a function of *what lien is foreclosing*:
- **1st-mortgage (or 1st-priority tax) foreclosure** → junior mortgages, HELOCs, judgment liens, most mechanic's liens are **wiped out**; you take clean-ish title. This is the deal you want.
- **Junior-lien foreclosure** (an HOA or 2nd-mortgage forecloses) → the **senior mortgage survives** and rides along; your "cheap" winning bid is on top of an intact first mortgage. This is the trap. `SurvivingSeniorLiens` can exceed ARV.
- Property taxes and municipal liens are **super-priority in both states** and survive nearly everything → always subtract.
- A federal (IRS) tax lien junior to the foreclosing mortgage is extinguished but carries a **120-day IRS right of redemption**; a properly-noticed non-IRS junior generally is not.

**Sub-model B — surplus recovery net fee.**
```
NetRecoveryFee = min(ContractRate, StatutoryCap) × Overage − FilingCost − SkipTraceCost
Overage        = FinalSaleBid − (JudgmentDebt + AccruedInterest + Costs + JuniorLiensPaidFromSurplus)
```
The former owner is only entitled to what remains **after junior lienholders are paid out of the surplus in priority order** — that's why you underwrite the *net* overage to the person, not the gross surplus.

### Capital required + financing (down/EMD, hard-money points+rate 2026, holding months, total cash-in)

**Sub-model A (capital-intensive):**
- **Deposit at the sale.** *SC (Master-in-Equity):* **5% of the bid** in certified funds the same day, **balance in 30 days** or the deposit is forfeited and the property is re-noticed. *NC (power-of-sale/clerk):* high bid is subject to a **10-day upset-bid period**; any upset bid must exceed the standing bid by the greater of **5% or $750** and post that as a deposit — so in NC you don't own it clean for ~10+ days and can be outbid post-sale.
- **Cash-in for a typical deal in our band ($150k ARV, $30k rehab):** winning bid ~$70k–$90k. If all-cash, that plus ~$5k reserves. If hard-money: **2026 fix-and-flip terms run 9.5%–13% interest + 1.5–3 points**, typically **~85–90% of purchase + 100% of rehab, 65–70% ARV cap**. Expect **~15–20% cash down + points + reserves**. Note many hard-money lenders **won't fund an auction purchase directly** (no inspection, must close in days) — investors often use a short-term cash/transactional-funding bridge, then refinance into the hard-money/DSCR loan post-sale.
- **Holding period:** 4–6 months for a flip (rehab 2–3, list/close 2–3); add 1–2 months for eviction if occupied. Model **5 months carry**.
- **Total cash-in, hard-money, this deal:** ~$12k–$18k down + ~$2k–$4k points + ~$4k–$6k interest over 5 mo + ~$5k reserves ≈ **$25k–$33k out of pocket**.

**Sub-model B (near-zero capital):** cost per claim is skip-trace ($0 via the engine's own owner-resolver, or ~$5–$15 commercial) + filing/notary/postage (~$50–$200) + optional attorney to file the motion. No property, no financing, no holding cost. This is why it's the higher-ROI-on-cash lane even though the dollar profit per deal is smaller.

### Exit math + margins (realistic profit + the make-or-break variables)

**Sub-model A:** on a clean 1st-mortgage foreclosure bought right, target **$20k–$35k net** on a sub-$200k flip (≈13–20% of ARV). Make-or-break variables, in order: **(1) which lien is foreclosing** (junior-lien sale with a surviving 1st = instant loss); **(2) interior condition** — you usually can't get inside, so rehab is a guess and a $30k estimate can be $55k; **(3) occupancy/eviction** — a holdover owner adds 1–3 months and $3k–$6k; **(4) redemption/upset** — an NC upset bid can take the deal away after you've committed, and SC-tax-derived title carries the 12-month cloud; **(5) title defects** — improperly-noticed junior liens that *should* have been wiped but weren't.

**Sub-model B:** margins are **statutorily capped**, and this is the compliance line:
- **SC:** for *reported/unclaimed* surplus, **S.C. Code §27-18-360** voids any recovery agreement made **within 24 months** of the funds being reported to the Treasurer, and after that **caps the fee at 15% of the value returned**. Court-held foreclosure surplus (before it escheats) is governed by **SCRCP Rule 71 / §15-39-720** — claims filed with the Master within a set window — and practitioners generally hold fee agreements to that same reasonableness ceiling.
- **NC:** there is **no statutory percentage cap**, but since **Jan 1, 2022, anyone who for a fee locates/recovers property distributable to an owner must be a licensed private investigator** (NC Private Protective Services Board, per N.C.G.S. §116B-53/78.1 definitions). Unlicensed "finders" charging 30–40% are operating illegally; as of early 2025 only a handful of entities were properly registered statewide. Practically, NC surplus is claimed through a **special proceeding under G.S. §45-21.32**, and many owners use an attorney (statutory/reasonable attorney fees) rather than a finder.
- **Realistic recovery-business margin:** on a typical **$8k–$25k overage**, a compliant SC 15% fee nets **$1,200–$3,750 per claim** minus ~$100–$500 costs. It scales on **volume of the sale roster**, not per-deal size.

### A worked example (a real deal in our price band)

**Sub-model A — clean 1st-mortgage foreclosure, Spartanburg County SC.**
- ARV (post-rehab, per comps): **$165,000**
- Rehab (estimated blind, cosmetic + roof): **$32,000** (budget the +30% risk → underwrite $38,000)
- Foreclosing lien: **1st mortgage** → juniors wiped; only **surviving super-priority county taxes $3,200** remain
- Redemption reserve: **$0** (mortgage foreclosure, not a tax sale → no SC 12-month redemption)
- Eviction holdover (occupied): **$4,000**
- Title cure reserve: **$2,000**
- Selling costs (0.08 × ARV): **$13,200**
- Finance carry (hard-money, ~$80k principal, 3 pts + 11% × 5 mo): **$2,400 pts + $3,700 int ≈ $6,100**
- Target profit (auction risk premium, 22% of ARV): **$36,300**

Max bid = 165,000 − 38,000 − 3,200 − 0 − 4,000 − 2,000 − 13,200 − 6,100 − 36,300 = **$62,200.** Round the ceiling to **$62,000**; walk if bidding passes it.
- **If won at $58,000:** SC deposit due same day = 5% = **$2,900**; balance $55,100 in 30 days. Actual rehab lands at $34,000 (under the $38k reserve). Sell at $165,000. Net profit ≈ 165,000 − 58,000 − 34,000 − 3,200 − 4,000 − 2,000 − 13,200 − 6,100 = **~$44,500** (≈27% of ARV — beat target because you bought $4k under ceiling and rehab came in under reserve).

**Sub-model B — surplus on the same roster.** A different sale: judgment debt + costs = $92,000; property sold at auction for **$118,000**. Gross surplus = **$26,000**. One junior judgment lien of $6,000 is paid from surplus first → **net overage to former owner = $20,000**. You skip-trace the ex-owner (free via the engine's resolver), sign a **15% SC-compliant** recovery agreement, file under Rule 71. **Fee = $3,000**, less ~$250 filing/notary/mailing = **~$2,750 net, zero capital, ~60–90 days to disbursement.**

### Encode in the engine (the per-strategy max_bid formula / which grade factors change)

Add a strategy tag `auction` and a parallel `surplus` opportunity type, computed from the same sale-roster record.

**1. `max_bid_auction` (new field, distinct from `max_bid_70`):**
```
max_bid_auction = arv
                − rehab_reserve                 # rehab × 1.30 (blind-buy inflation)
                − surviving_senior_liens         # from lien-stack capture, filtered by foreclosing-lien position
                − redemption_reserve             # = 0 for mortgage FC; = f(assessed) only if title is SC-tax-derived
                − eviction_reserve               # 0 if vacant flag; else 4000
                − title_cure_reserve             # 2000 default
                − 0.08 × arv                      # selling costs incl. SC/NC deed stamps
                − finance_carry                   # points + rate × hold_months (2026: 11% + 3 pts, 5 mo default)
                − 0.22 × arv                      # auction risk-profit premium (vs 0.15 negotiated)
```

**2. New required inputs / gates (these drive the grade):**
- `foreclosing_lien_position` — **the single most important new factor.** If the foreclosure is a **junior lien** (HOA/2nd), set `surviving_senior_liens += senior_mortgage_balance` and **hard-cap the grade at D/F** unless senior payoff still leaves margin. Grade A/B requires a confirmed **1st-position** foreclosure.
- `occupancy_flag` (vacant vs occupied) → toggles `eviction_reserve` and one grade notch.
- `redemption_exposure` — boolean: true only when the deed derives from an **SC tax sale (12-mo redemption + extra 12-mo incontestability window)** or an **IRS 120-day** junior-lien situation; when true, apply `redemption_reserve` and **down-grade one letter** (capital is frozen/at-risk during the window). Mortgage foreclosures in both SC and NC = no equitable redemption → no penalty.
- `state`/`upset_bid_risk` — for **NC**, flag that the winning bid is **not final for 10 days** and can be topped by a 5%-or-$750 upset; the engine should treat NC auction wins as *provisional* and not commit the full deal-flow until the upset window closes.

**3. Surplus opportunity (`surplus_recovery`):** fire whenever `final_sale_bid > judgment_debt_total`. Compute:
```
gross_surplus   = final_sale_bid − judgment_debt_total
net_overage     = gross_surplus − junior_liens_paid_from_surplus
statutory_rate  = 0.15 if state == "SC" else attorney/PI-licensed model for NC
projected_fee   = net_overage × statutory_rate − claim_costs
compliance_flag = "SC:void<24mo of report" | "NC:requires_PI_license_or_attorney"
```
Grade the surplus lead on `net_overage × statutory_rate` (dollar yield) and set `outreach_priority = high` — these are near-zero-cost, high-ROI, and share the exact owner→contact backbone the rest of the engine already uses. Surface `compliance_flag` on every surplus record so outreach never signs a void SC agreement or an unlicensed NC finder deal.

Sources: [NC upset-bid deposit G.S. 45-21.27](https://www.ncleg.gov/EnactedLegislation/Statutes/PDF/BySection/Chapter_45/GS_45-21.27.pdf), [NC upset bid rules/deadlines](https://legalclarity.org/how-upset-bids-work-in-north-carolina-foreclosures/), [NC finder PI-license requirement](https://www.surplusfundsattorney.com/beware-of-finders), [NC surplus special proceeding G.S. 45-21.32](https://www.ncleg.gov/EnactedLegislation/Statutes/PDF/BySection/Chapter_45/GS_45-21.32.pdf), [SC Master-in-Equity 5% deposit / 30-day close](https://charlestoncounty.org/Departments/Master-In-Equity/bidding.php), [SC surplus Rule 71](https://www.sccourts.org/resources/judicial-community/court-rules/civil/rule-71/), [SC §27-18-360 finder cap 15% / 24-mo void](https://law.justia.com/codes/south-carolina/title-27/chapter-18/), [SC tax-sale 12-month redemption](https://www.scstatehouse.gov/code/t12c051.php), [lien priority — juniors wiped/seniors survive](https://www.nolo.com/legal-encyclopedia/what-happens-liens-second-mortgages-foreclosure.html), [2026 hard-money rates & points](https://www.crestmontcapital.com/blog/hard-money-loan-rates-2026), [2026 fix-and-flip loan terms](https://www.welendllc.com/blog/fix-and-flip-loan-rates)


---

# Deep-Dive Round 15 — Net-New Sources Round 2 (2026-07-02)


## Per-city/county CODE-VIOLATION & nuisance portals

| Source | What it provides | Free?/cost | Access | Footprint coverage | Already? | Net-new value |
|---|---|---|---|---|---|---|
| **SeeClickFix Open311 / v2 API** (`seeclickfix.com/api/v2/issues?place_url={place}` and `/open311/v2/{jurisdiction}/requests.json`) | Live 311 service requests incl. code-enforcement types ("Tall Grass/Weeds on Private Property", junk/nuisance, illegal occupancy) with full address, lat/lng, status (Open/Acknowledged/Closed), description, created_at, assigned officer | Free, JSON, no key for public issues (Open311 GeoReport v2 std) | REST/JSON, queryable & paginated; live-verified returns 268+ issues for one place | **Anderson SC** (`anderson_3` city + Anderson County watch area), **Spartanburg** (`spartanburg` city + `spartanburg-county`), **Gastonia NC**, plus Hickory NC (Catawba, adjacent) | **NO** — Accela/OneMap/ROD covered, SeeClickFix 311 never wired | HIGH. Chronic weeds/junk/nuisance complaints on *private property* = deferred-maintenance signal, address-keyed, machine-readable, multi-jurisdiction from ONE API. Directly joins to your parcel backbone by address. |
| **Greenville County Accela Citizen Access — Enforcement module** (`aca-prod.accela.com/TOS/Cap/CapHome.aspx?module=Enforcement`) | Searchable code-enforcement records: complaint type (Illegal Occupancy, Green Pool, etc.), address, parcel #, date range, case status | Free, no login to search | Accela ACA (JS app; needs headless/session, not plain httpx) | Greenville County SC — **out of footprint but borders Anderson/Pickens/Laurens/Spartanburg**; useful only for edge parcels | Partial — Accela pattern known (Asheville Accela covered) but this agency not wired | MEDIUM. Confirms the Accela-Enforcement query pattern; marginal geographic value (border spillover only). |
| **Greenville County OpenGov Procurement — demolition solicitations** (`procurement.opengov.com/portal/greenvillecounty`) | Individual "Demolition of Structure" bid packages for county-ruled-unfit residential structures: property **address + tax map number** + specs | Free, public, no login | Web portal / OpenGov procurement (per-project docs) | Greenville County SC (border-adjacent) | **NO** | HIGH-signal but LOW-volume: an unfit-structure that reached demolition procurement = maximally distressed + owner already lost control. Novel angle (procurement side, not code side). Same OpenGov procurement pattern worth checking for in-footprint counties (Anderson/Buncombe already use OpenGov). |
| **Anderson County ACPASS** (`acpass.andersoncountysc.org`) | Public-access land-use/permit/code-action records lookup | Free, public | Web portal (ASP.NET) | **Anderson County SC** (in footprint) | Assessor/GIS covered; ACPASS code-action tab not confirmed-wired | LOW-MEDIUM. May expose enforcement actions but search verified only for permits/land records; needs live drill to confirm a code-case tab exists. |
| **Shelby / Cleveland County Accela** (`aca-prod.accela.com/SHELBYCO/`) | Accela Citizen Access instance for Cleveland County / City of Shelby (permits + potentially enforcement module) | Free | Accela ACA (JS app) | **Cleveland County NC + City of Shelby** (in footprint) | **NO** | MEDIUM. Confirmed Accela tenant in-footprint; must verify an Enforcement/Code module is enabled (only Building module confirmed so far). Worth a live check — if enabled, it's an in-footprint Accela code feed. |
| **SmartGov (Granicus) public portals — Public Notices** (`co-mcdowell-nc.smartgovcommunity.com`, `co-henderson-nc.smartgovcommunity.com`) | Parcel info + "public notice announcements" (can include unsafe-building/nuisance postings); code-enforcement *case* search NOT public | Free | Web portal | **McDowell NC, Henderson NC** (in footprint) | Assessor covered; SmartGov notices not wired | LOW. Live-verified: **no unauthenticated code-case search** — only permits (login) + parcel + public notices. Notices tab is the only scrapable sliver; thin. Flag as near-wall. |
| **City/County report-only forms** (Gastonia city, Hendersonville city, Marion, Brevard, Lincolnton, Morganton) | Complaint *intake* forms only — no public case-status search | Free | Web form | Multiple in-footprint cities | n/a | **NONE for us.** Intake-only, no outbound queryable case data. Documented dead-ends so they aren't re-chased. |

**Anti-bot / ToS flags:** SeeClickFix Open311 is explicitly public and standards-based — clean. Accela ACA (Greenville TOS, Shelby) is a JavaScript app that needs a headless browser/session; no evasion required, but respect rate limits and its ToS (public-record search is intended use). SmartGov code-case data is login-gated — do NOT attempt to bypass auth; treat as wall. OpenGov procurement docs are fully public.

**Top pick to build next:** The **SeeClickFix Open311 / v2 issues API** — one free, keyed-optional JSON endpoint returns address + lat/lng + status + description for private-property nuisance/weeds/junk complaints across **Anderson (city+county), Spartanburg (city+county), and Gastonia** in the footprint (plus Hickory adjacent). Filter to code-type request categories, keep only Open/repeat complaints on private parcels, and join to the existing parcel backbone by address/lat-lng. Highest volume, lowest friction, genuinely net-new signal; layer the Greenville County OpenGov demolition solicitations as a small high-conviction unsafe-structure feed second.


## Utility shutoffs, water liens, demolition orders

| Source | What it provides | Free?/cost | Access | Footprint coverage | Already? | Net-new value |
|---|---|---|---|---|---|---|
| NC §160A-314 / §160A-238 delinquent water-sewer liens (Clerk of Superior Court filings) | Recorded lien: owner name+address, city claimant, service type, unpaid charge amount, date — filed 90-180 days after nonpayment when ordinance elects "same manner as delinquent taxes" | Free; public record | Clerk of Superior Court civil/lien index per county (eCourts Judgment/lien index or in-person). Published, NOT FOIA-gated | All 11 NC counties where the city/utility adopted the collect-as-taxes ordinance (varies by town) | No — distinct from the ROD deed/tax lane; this is the CoSC utility-lien index | High — a delinquent water lien = cash-strapped owner + a recorded debt figure; direct motivated-seller signal with the debt amount already quantified |
| SC delinquent tax-sale lists w/ certified water/sewer charges folded in (county Delinquent Tax office) | Annual + rolling delinquent-property lists; SC municipal/district water-sewer arrears certify to the county tax collector and ride the tax bill, so unpaid utility shows inside the tax delinquency | Free; PDF/HTML published 3 wks pre-sale, some year-round | Spartanburg, Pickens, Oconee, Anderson, etc. Delinquent Tax pages publish lists; Georgetown-style "Water/Sewer Tax Search" portals exist | 7 SC counties (Spartanburg, Anderson, Pickens, Oconee, Cherokee, Union, Laurens) | Partial — SC tax-delinquency is covered, but the water/sewer-certified subset as a distinct flag is net-new | Medium-High — lets you tag "utility-arrears" rows within existing tax-delinquent pull; no new crawl, just a field |
| CitizenPortal.ai per-county meeting feed | AI-transcribed council/commission agendas+minutes; already surfaces named demolition orders (e.g., Gaston 3014 Birchfield Lane, 30+ violations, "unfit," abatement-cost lien) with the property address | Free tier (alerts/search/exports); no public API found | Web feeds per county/city (Buncombe, Gaston, Asheville-City confirmed live); search + saved lists | Buncombe, Gaston, Asheville confirmed; expanding to smaller NC/SC bodies | No | High — one indexed surface that pre-extracts demolition/condemnation addresses across many bodies; saves crawling each council portal separately |
| City/County CivicClerk + Municode + CivicEngage agenda portals | Raw council/commission agenda packets & minutes containing condemnation resolutions, "unfit for human habitation" orders, demolition ordinances, and abatement-cost lien authorizations w/ street addresses | Free; published (public-meeting law) | Spartanburg CivicClerk portal (spartanburgsc.portal.civicclerk.com) confirmed machine-readable; Buncombe CivicClerk; Gastonia/Hendersonville own portals; Municode for ordinance text | Nearly all footprint municipalities/counties (platform varies per city) | No | High — primary-source demolition/condemnation agenda items = pre-foreclosure blight owners; addresses in packet PDFs |
| Anderson County "Demolition of Distressed Structures" program page | County directly publishes addresses approved for demolition (e.g., 5 Hammett, 8 N. Prince, 401 Hall, 17 Lopez/Pelzer) under the Miscellaneous Project | Free; published list | Static county webpage + council funding agenda items | Anderson SC (model; check Spartanburg/other SC counties for equivalent) | No | Medium — turnkey address list of failing structures; owner likely distressed/absentee |
| NC 160D Article 12 minimum-housing "unfit" orders (Code Compliance / Building & Codes) | Public officer's written findings + order to repair/close/demolish; 45-day clock; posted on structure and served; council confirms by ordinance; costs become a lien | Free; order is public but often FOIA/records-request to get the working list vs. published in council minutes | Henderson County Code Compliance, Gastonia Inspections, Asheville — order text via council agenda; full active roster often by records request | Henderson, Gaston, Buncombe + other NC municipalities | Partial for Asheville (Accela code already wired); net-new for the other NC bodies' housing-order lane | Medium — condemnation = severe-distress owner; where it lands in council minutes it's published, where it's a working roster it's FOIA-only |
| SC Dilapidated Buildings Act / municipal unsafe-building demolition + recorded abatement lien (ROD) | Demolition action requires 90-day pre-hearing notice to owners+lienholders; post-demolition the cost is filed as a lien in the ROD/Clerk of Court | Free; recorded lien is public | County ROD lien index (Spartanburg/Anderson ROD search) — filed after demolition | 7 SC counties | Partial — ROD is covered generally; the demolition-cost lien as a targeted instrument type is net-new | Medium — trailing indicator (post-demolition) but confirms a severely distressed, now-vacant-lot owner |

Walls to flag (do not evade): NC water customer PII, including which addresses are on shutoff/disconnect lists, is exempt from public record under **NCGS §132-1.14** — direct utility-disconnection lists are a statutory wall in all NC counties; use the recorded §160A-314 lien instead. SC PublicIndex remains ToS-no-scrape. Active NC 160D "unfit" working rosters (before they hit a council agenda) are typically **FOIA/records-request only**, not published. CitizenPortal.ai has **no documented public API** — feed/HTML scraping only, and its article pages returned 403 to plain fetch (treat as bot-sensitive; use compliant page access).

Top pick to build next: **NC §160A-314 delinquent water/sewer lien index at the Clerk of Superior Court** — it is the only surface here that yields a recorded, quantified debt amount tied to an owner+property for a live (not post-demolition) distress signal, it is genuinely published (not FOIA-walled or PII-blocked like the shutoff lists), and it plugs straight into the existing equity/lien-stack engine as a new lien type. Pair it with the **CitizenPortal.ai + CivicClerk demolition-agenda parser** as the demolition/condemnation lane.


## Expired listings / FSBO / withdrawn

| Source | What it provides | Free?/cost | Access | Footprint coverage | Already? | Net-new value |
|---|---|---|---|---|---|---|
| **FSBO.com** | FSBO listings: address, price, beds/baths, seller name + phone/email on detail page (owner-direct, no agent) | Free browse; sellers pay to list | Next.js app; listings server-rendered in `__NEXT_DATA__` JSON, **no Cloudflare/CAPTCHA** on probe. State/keyword search URL params. Compliant polite crawl feasible | Nationwide incl. NC/SC — filter by county/city keyword | **No** | HIGH. Owner name + direct contact exposed free. Cleanest FSBO source technically; the flagship build |
| **Fizber.com** | FSBO listings syndicated widely (Zillow/Redfin/Realtor); address, price, specs, seller contact | Free to list + free to browse | Server-rendered HTML, **no Cloudflare/CAPTCHA** on probe (4.8KB shell — deeper listing pages carry data). Sitemap-style state paths | Nationwide; NC/SC by city | **No** | HIGH. Second clean FSBO feed; overlaps FSBO.com partially but catches different owners. Direct seller contact |
| **ByOwner.com** | "Largest FSBO site"; address, price, photos, owner contact; also pulls flat-fee MLS FSBOs | Free browse | Server HTML returns (23KB, **no CF/CAPTCHA**), but listing cards are JS-injected on index — needs light headless render or internal JSON endpoint sniff | Nationwide; NC/SC city paths | **No** | MED-HIGH. Broadest FSBO inventory but requires render step. Good third source to dedupe against FSBO.com/Fizber |
| **Craigslist** real-estate-by-owner (`/reo/`) | Owner-posted for-sale + FSBO; body text often has address, price, phone | Free | **HOSTILE — do not scrape.** ToS explicitly bans bots/scrapers; litigious (has sued scrapers); custom CAPTCHA + IP-ban + shadow-flagging in 2026. RSS feed per search exists but is rate-limited/fragile | Has Asheville, Greenville/Upstate, Charlotte, Hickory regions covering all 18 counties | **No** | MED value, but **flag as ToS/legal wall.** Only compliant path = the public per-search RSS (`&format=rss`), low volume, no evasion |
| **Zillow FSBO / "Make Me Move"** | FSBO + owner "make me move" (soft-seller) listings; address, price, sometimes owner-provided | Free browse | **WALLED.** PerimeterX + Cloudflare (8/10 difficulty), ToS bans automated access; needs residential/mobile proxies | Full NC/SC | **No** | LOW to build compliantly. Note as a wall; Make-Me-Move is unique motivated signal but not reachable free/compliant |
| **Facebook Marketplace** (Property For Sale) | Owner-posted homes/land; seller name, photo, approx location, sometimes phone | Free | **WALLED.** Login gate + Meta WAF fingerprinting; ToS bans automated collection; PII exfiltration raises data-protection issues. Requires residential proxies | NC/SC metros | **No** | LOW compliant yield. Flag as ToS + privacy wall; not recommended |
| **Expired / Withdrawn MLS** (Canopy MLS Charlotte/Western NC; local SC boards) | Listings that expired or were withdrawn unsold — classic hot motivated-seller signal | N/A | **CONFIRMED GATED.** On expire/withdraw, agents set Internet=N and status changes propagate off IDX/VOW within 2 business days. Requires MLS membership + agent license; no public feed | Canopy covers Buncombe/Henderson/etc.; SC boards cover Upstate | **No** | Signal is gold but **unreachable without a licensed agent partner.** Note as partnership/manual lane only, not a scraper |
| **HomeFinder / Houzeo / Homecoin / Beycome public FSBO pages** | Flat-fee-MLS FSBO sellers' public listing pages; address + seller-facing contact | Free browse | Varies; several server-render listing pages without CAPTCHA. Lower volume | Nationwide incl. NC/SC | **No** | MED. Long-tail FSBO catchers; build only after FSBO.com/Fizber/ByOwner if volume is thin |
| **"Stale FSBO" enrichment** (cross-ref FSBO addresses vs your parcel/assessor + days-on-site) | Turns a raw FSBO feed into *motivated* FSBO: flags long-listed / price-cut / absentee-owner FSBOs | Free (internal) | Uses data you already have (assessor/GIS owner + mailing address vs situs = absentee) | All 18 counties | Partially (absentee flag exists) | HIGH leverage. Not a new source — a scoring layer that makes the FSBO feeds actually actionable and dedupes to owner-of-record |

**Top pick to build next.** **FSBO.com** — it is the only major FSBO source that on live probe returns owner name + direct phone/email with **no Cloudflare or CAPTCHA**, data server-rendered in `__NEXT_DATA__` JSON, filterable by state/city keyword to your 18 counties. Build it as a BaseScraper, then immediately layer the **"stale FSBO" enrichment** (join FSBO street address to your existing assessor/GIS to add owner-of-record, absentee flag, and days-on-market) so each FSBO becomes a scored motivated-seller lead rather than a raw listing. Fizber and ByOwner are the natural second/third feeds to dedupe against. Craigslist, Zillow FSBO, Facebook Marketplace, and expired/withdrawn MLS are all confirmed walls (ToS/anti-bot or membership-gated) — surface them as manual/partnership lanes only, never as scrapers.


## Senior-downsizing / assisted-living / reverse-mortgage (HECM)

| Source | What it provides | Free?/cost | Access | Footprint coverage | Already? | Net-new value |
|---|---|---|---|---|---|---|
| **County ROD "Home Equity Conversion Mortgage" deed-of-trust index** (Buncombe/Mecklenburg-style search portals + your Spartanburg ROD instrument-type flow) | The HECM DOT recorded on-title. Identifiable by (a) HUD named as grantee on a paired 2nd DOT, (b) "Home Equity Conversion" / "HECM" in the instrument title, (c) FHA case number. Recorded doc = borrower name + parcel/property = a live elderly owner with a reverse mortgage. | Free (public land records; you already scrape these) | Grantor/grantee + document-type text search on existing ROD portals; OCR the doc image for FHA case# / HUD 2nd DOT (you have the free doc-OCR enricher) | HIGH — every county has a ROD; you already run Spartanburg ROD + NC ROD image download. Add a name/text filter for "conversion"+HUD grantee | **NO** (you index ROD generally; you do NOT flag HECM as a facet) | **Highest.** Property-keyed, free, and a direct age+sell-propensity signal. HUD-as-grantee on the 2nd DOT is a near-unique fingerprint. Turns your existing ROD ingest into a reverse-mortgage detector with a name/text rule + OCR confirm. |
| **HECM foreclosure / "due & payable" NOS at ROD + trustee sale lists** (same recording stream, later event) | When a HECM matures (borrower died / moved to assisted living >12mo / tax-insurance default) the servicer records a substitution-of-trustee + notice of sale. Distinct maturity-driven distress vs. normal payment default. | Free (public land records / trustee sale postings) | Cross-match your existing NC power-of-sale + SC foreclosure notices against the HECM-flagged parcels above | HIGH — rides your existing foreclosure-notice pipeline | Partial — you capture foreclosure notices, but not tagged as HECM-maturity (a heirs/vacant/pre-sale motivated seller) | High — a HECM in due-and-payable = heirs holding a house they must sell fast to avoid losing equity. Best-timed sub-segment of your existing FC feed once HECM-tagged. |
| **NC Medicaid Estate Recovery — "Notice of Medicaid Estate Claim" recorded in county land records** (N.C.G.S. §108A-70.5(b1)) | DHB records a claim/notice against real property of a deceased Medicaid (long-term-care/nursing-home) recipient. On-title = a probate-estate house that heirs must clear/sell. | Free (recorded in county land records; also probate estate file at Clerk of Superior Court) | ROD document-type / grantee = "NC DHHS / Division of Health Benefits" text search; join to parcel | NC counties (11 of your 18). SC has no equivalent recorded lien (SC recovers as a probate estate creditor only) | **NO** | High for NC — a recorded Medicaid claim is a strong "elderly owner deceased after LTC, heirs must sell" flag, property-keyed and free. Pairs with your obituary/estate lanes. |
| **SC DHEC GIS Hub — Health Facilities / Community Residential Care (assisted-living) layer** | Point geometry + license data for every SC licensed CRCF/assisted-living + nursing home (465 CRCF statewide). Property-keyed by lat/lng and address. | Free (ArcGIS Hub; CSV/GeoJSON/WFS download) | `hub.arcgis.com` SC-DHEC FeatureServer; same pattern as your Charleston/SCDOT ArcGIS pulls | SC 7 counties covered by statewide layer | **NO** | Medium — not a seller list itself, but the *destination* anchor: an owner whose mailing address (from assessor) resolves to a CRCF geometry, OR whose homesteaded house now sits vacant while they're at a facility. Enables an "owner moved to assisted living" heuristic when joined to your homestead/tax data. |
| **SC over-65 Homestead Exemption flag (county auditor) + long-tenure from your sale-history** | The $50k homestead exemption is granted only to age-65+/disabled owners. Where the county auditor exposes the exemption flag on the parcel/tax record, it is a direct "owner is 65+" marker. Combine with 20+ yr tenure from your CAMA sale-history. | Free (county tax/auditor parcel records you already ingest) | Parse exemption/relief flag from tax portal; you already pull qPublic cards + qPayBill | SC counties where auditor exposes the flag; NC has an analogous "Elderly/Disabled Exclusion" (G.S. 105-277.1) flag | Partial — MEMORY notes "senior tax exemption already noted"; broaden to a first-class scored facet + NC elderly-exclusion equivalent | Medium — cheap age-derived signal already inside data you scrape; formalize as a senior-downsizing score input (65+ flag × long tenure × high equity). |
| **HUD FHA HECM Single-Family Portfolio Snapshot** | Monthly loan-level HECM counts by property **state / county / city / ZIP**, lender, endorsement year, rate type. | Free (HUD.gov Excel, monthly, back to 1989) | Direct Excel download / data.gov | ALL 18 counties (county-level rows) | **NO** | Low-to-medium — **ZIP/county aggregate only, NOT property-keyed** (no address/parcel). Not a lead list. Use it to size the HECM population per county/ZIP and prioritize which ROD sub-indexes to mine, and to sanity-check your ROD detector's yield. |

**ToS / anti-bot notes:** ROD portals are public but many wrap the doc-image viewer in session tokens or light rate-limits — pace requests, reuse your existing NC-ROD image-download and Spartanburg instrument-type flows rather than hammering. The SC DHEC ArcGIS Hub is open FeatureServer (no wall). HUD Snapshot is a static Excel (no wall). SC PublicIndex remains a ToS-no-scrape wall (do not use it for the SC Medicaid/probate side — use recorded ROD + county probate instead). No evasion proposed for any wall.

Top pick to build next: **The HECM detector on your existing ROD ingest** — a name/text rule flagging deed-of-trust records with "Home Equity Conversion"/"HECM" in the title or HUD/Secretary-of-HUD named as grantee on a paired 2nd DOT, confirmed via your free doc-OCR enricher (FHA case number). It is free, fully property-keyed, rides infrastructure you already run (Spartanburg ROD + NC ROD image download + doc-OCR), and directly identifies living elderly owners with a reverse mortgage — the single strongest senior-downsizing signal in this facet. Then layer the HECM-maturity foreclosure tag and the NC Medicaid estate-claim flag on top.


## Heir-finding / pre-probate death signals

| Source | What it provides | Free?/cost | Access | Footprint coverage | Already? | Net-new value |
|---|---|---|---|---|---|---|
| **Assessor/GIS owner-name string match: "ESTATE OF", "HEIRS OF", "ESTATE", "% DECEASED", "LIFE ESTATE"** | Property-keyed decedent signal: parcel + situs address + assessed value where title still sits in a dead owner's name because no estate has retitled it. This is pre-probate/probate-stalled by definition and already property-linked. | Free | Query your EXISTING county GIS/assessor owner field (already scraped) for these tokens; no new fetch, a filter over data you hold | All 18 (every assessor owner field) | **No** — you scrape GIS owner names but don't flag decedent-owner tokens | Highest. Turns your existing owner column into a motivated-heir list with zero new source. Property-first, matches your backbone; catches stalled/never-filed estates that court feeds miss |
| **Individual funeral-home websites (Tribute Tech/CFS, Frazer, FrontRunner, FuneralTech CMS)** | Decedent name + age + hometown/town + funeral date, often surviving-family names. Posts BEFORE any estate filing (days after death). ~4 CMS platforms → predictable per-home obituary sitemap/URL patterns | Free | Fetch each in-footprint home's own site (public, first-party, not the walled aggregator). Respect each site's robots.txt; the CMS obituary lists are generally crawlable | All 18 (enumerate the ~40-80 homes serving these counties) | **No** — only Gannett newspaper obits are wired | High. Earliest death signal, first-party (compliant), gives hometown to disambiguate before matching name→GIS parcel. Complements Gannett (funeral homes post first) |
| **Column.us public-notice search (per in-footprint newspaper)** | Estate/administration "Notice to Creditors" + newspaper-published obituaries, searchable per publication | Free public search | Each paper's `<paper>.column.us/search`; you already run a Column scraper for foreclosure/estate notices | NC papers strong; SC partial | **Partial** — you use Column for NC estate lane already; obituary/death-notice content within Column is the net-new slice | Medium. Extends an integration you own to capture death notices, not just creditor notices |
| **ncnotices.com (NC Press Assn public-notice aggregator)** | Statewide free aggregation of NC newspaper legal notices incl. estate/creditor notices; a second index over the same notices Column carries | Free | Public search site | NC counties (10 of your 18) | **Partial** — overlaps Column estate lane | Low-Medium. Redundancy/backstop for NC papers not on Column; NC-only |
| **SSA Limited-Access Death Master File (LADMF, via NTIS)** | Name + SSN + DOB + death date + last-residence ZIP (5-digit) for deaths <3 yrs. The public/limited file | **Not free/not open** — NTIS certification required (attestation of legitimate fraud-prevention use + audit), paid subscription | Certified subscribers only; free public search app returns name/date but ZIP-only, no street | National (ZIP-level) | **No** | **Low for you.** ZIP-only (not parcel-linkable), and certification gate + use-restriction make it a poor fit vs property-first path. Flag: do NOT treat the "public search" as address-yielding |
| **State death indexes — NC Vital Records / FamilySearch; SC DPH death index** | Decedent name + county + death date only | Free (FamilySearch reg.) | Public/genealogy portals | NC + SC statewide | **No** | **Low.** No street address (county only) and coverage lags (NC index to ~1994; SC DHEC 1915-1966) — misses recent deaths entirely. Fails the pre-probate + property-linkable test |
| **Find A Grave / cemetery indexes** | Name + death date + burial location; sometimes hometown | Free | Public site (scraping discouraged) | National | No | **Low.** Posts AFTER burial, no street address, weak parcel link. Not a lead trigger |
| **Legacy.com, Echovita, Tributes.com, Tribute Archive (aggregators)** | Aggregated national obituaries | Free to view | — | National | No | **AVOID — ToS/anti-bot WALL.** Legacy ToS explicitly bars robots/crawlers/extraction; Echovita is itself being sued (SCI) for scraping funeral homes. Use first-party funeral-home sites instead. Do not evade |

**Top pick to build next:** The **assessor/GIS owner-name decedent-token filter** ("ESTATE OF" / "HEIRS OF" / "DECEASED" / "LIFE ESTATE") — it is a zero-new-source flag over the owner field you already scrape for all 18 counties, is inherently property-keyed to your backbone, and captures stalled or never-filed estates that court and obituary feeds never surface; pair it as a second lane with first-party **in-footprint funeral-home site obituaries** (the compliant, earliest death signal) to catch fresh deaths before title ever changes.


## Corporate/institutional/iBuyer-resale + HOA-lien + portfolio sellers

| Source | What it provides | Free?/cost | Access | Footprint coverage | Already? | Net-new value |
|---|---|---|---|---|---|---|
| **SC Forfeited Land Commission (FLC) assignment lists** (per-county Auditor/Treasurer, e.g. [Spartanburg](https://www.spartanburgcounty.gov/388/Forfeited-Land-Commission), Oconee, Laurens, Anderson, Lexington template) | County-owned parcels that got NO bid at the delinquent tax sale — the county is now the institutional seller. Downloadable "Available for Assignment" real-estate + mobile-home lists w/ parcel IDs; acquire via offer form or Terry Howe online auction | Free, public PDF/lists | Direct county-site PDF fetch; Spartanburg pre-2023 via Terry Howe Auctions | All 7 SC counties (each county has its own FLC by statute, Title 12 Ch. 59) | **Partial** — you scrape the delinquent tax *sale* list; the FLC *post-sale unsold* list is a different, higher-distress dataset (owner already walked) | HIGH — county is the seller, deepest-distress tier, structured, per-parcel; net-new vs tax-delinquent lane |
| **Freddie Mac HomeSteps** ([homesteps.com/state/nc](https://www.homesteps.com/state/nc.html), [/sc](https://www.homesteps.com/state/SC.html)) | Freddie Mac REO homes for sale (GSE disposition) w/ address, price, photos, agent | Free browse | Site search filtered by state/ZIP; no login to browse | NC + SC statewide (filter to your 18 counties by ZIP) | **No** — memory lists HUD/VA/**Fannie** REO but not Freddie | MEDIUM — separate GSE inventory from Fannie HomePath; distinct parcels not in your Fannie feed |
| **Hubzu** ([hubzu.com/nc/bank-owned](https://www.hubzu.com/nc/bank-owned), [/sc](https://www.hubzu.com/sc/bank-owned)) | Bank-owned/REO + short-sale auction listings from mortgage servicers (Altisource pipeline) | Free browse | State bank-owned pages, structured card listings | NC + SC statewide | **No** (you have auction.com/Crexi/HUD/VA/Fannie, not Hubzu/Altisource) | MEDIUM — different servicer book than auction.com; catches Altisource-serviced REO others miss |
| **Xome auctions** ([xome.com/auctions/bank-owned/NC](https://www.xome.com/auctions/bank-owned/NC), [/SC](https://www.xome.com/auctions/bank-owned/SC)) | Bank-owned REO auctions (Xome/Mr. Cooper disposition channel) | Free browse | State bank-owned auction pages | NC + SC statewide | **No** | MEDIUM — Mr. Cooper/Nationstar REO channel, distinct from auction.com and Hubzu |
| **ServiceLink Auction** ([servicelinkauction.com/bank-owned](https://www.servicelinkauction.com/bank-owned/)) | Bank-owned/foreclosure auctions from ServiceLink (Black Knight) servicer network | Free browse | State/ZIP search | NC + SC | **No** | LOW-MED — another servicer disposition book; overlaps some w/ auction.com but distinct consignors |
| **HOA/COA lien-foreclosure lis pendens** (SC judicial: HOA files suit → lis pendens in Common Pleas; NC: §47F-3-116 claim-of-lien then foreclosure) | Homes where the HOA (institutional creditor) is foreclosing over unpaid assessments — often free-and-clear-ish equity, owner distressed but not mortgage-default | Free (court/ROD) | SC via your FCCMS/Common Pleas path (case-type/plaintiff = "…Homeowners Association"/"…HOA"/"…POA"); NC claim-of-lien recorded in ROD | All 18 counties w/ HOAs (Buncombe, Henderson, Gaston, Spartanburg suburbs) | **Partial** — you crawl SC courts + NC ROD, but likely not *filtering by HOA-plaintiff* as a distinct motivated-seller signal | HIGH — pure filter-add on data you already pull; isolates a clean high-equity distress cohort |
| **Corporate/institutional-owner bulk flag via existing GIS/assessor owner field** (LLC / "…HOMES LLC" / "…SFR" / REIT name match on owner name already in your parcel pulls) | Flags parcels owned by out-of-state LLCs, iBuyers, or SFR funds → disposition/portfolio-seller targets and absentee outreach | Free (derived) | Regex/entity-match over owner_name you already store; cross-ref SoS agent enricher | All 18 counties (uses data in hand) | **No** — you have absentee-owner flag + SoS enricher but not an institutional-owner classifier | MEDIUM — zero new fetch; turns existing owner strings into an institutional-seller lead SOURCE |
| **Terry Howe Auctions** ([SC tax/FLC/estate online auctions](https://www.spartanburgcounty.gov/388/Forfeited-Land-Commission)) | The actual auction house running Spartanburg (and other Upstate) FLC + county surplus sales | Free browse | Auction-site listing pages | Spartanburg + Upstate SC counties | **No** | LOW-MED — feeds the FLC pick above; direct listing view of county-institutional inventory |

**Flagged walls (do not evade):** Opendoor/Offerpad resale inventory sits mostly in metro Charlotte/Raleigh (outside your Western-NC/Upstate-SC core) and has no free structured feed — skip. FDIC Property Listing Site ([fdicrealestatelistings.com](https://www.fdicrealestatelistings.com)) is verified **empty nationwide** (May 2026 update: "No Properties At This Time") and its state filter has no NC/SC — dead until a covered-bank failure, not worth building now. HomeSteps/HomePath/Hubzu/Xome have **no public API**; they are browse-only sites — treat as HTML scrapes and check each site's robots/ToS before automating (never bypass anti-bot).

**Top pick to build next:** SC Forfeited Land Commission (FLC) assignment lists — it is the only source here where a public institution is itself the seller, it is the deepest-distress tier (owner already forfeited, no bidder took it), the lists are free structured per-county PDFs with parcel IDs that join straight into your existing SC parcel/assessor pipeline, and it is genuinely net-new versus your tax-delinquent lane. Pair it with the HOA-plaintiff lis-pendens filter as a near-zero-cost add on court data you already pull.
