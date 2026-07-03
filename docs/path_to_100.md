# Path to 100% — Comprehensive Costed Scope

_Foreclosure / motivated-seller lead engine · 18 counties (Upstate SC + Western NC) · board N=17,003 · generated 2026-07-02._

For every score, factor, source, enrichment, and identity-join: current fill-rate → what 100% requires → FREE routes → REAL 2026 paid-vendor pricing → feasibility (can/can't + why) → recurring cadence & cost → step-by-step manual playbook.

## ⚠️ Round-1 verification corrections (2026-07-02) — these SUPERSEDE figures below
Independent re-fetch of every vendor's live pricing page. Full tables in `path_to_100_deepdive.md`.
- **PropStream** — "free skip-trace" needs **Pro $199/mo** (or a **$30/mo Connect add-on**), NOT the $99 Essentials tier (which pays $0.12/contact). Don't budget "$99 + free tracing."
- **IDI idiCORE** — the gate is **GLBA/DPPA**, and idiCORE is explicitly **NOT** usable for FCRA purposes. The "FCRA gate" wording below is backwards.
- **Spokeo** — it **does** have a bulk/enterprise API (People Intelligence API, quote-only); only the consumer tier is ToS-restricted. "No bulk API" below is wrong.
- **Smarty free tier** — a **one-time 1,000-lookup / 42-day trial**, NOT 250/mo recurring. ($17/1k→$485/170k paid anchors + $45 rooftop-geocode start still hold.)
- **Estated** — dead as a standalone (absorbed into ATTOM); don't quote its legacy $179/$449/$1,799 tiers.
- **HouseCanary** — self-serve API is **$0.50/call, no published minimum** (+ a Pro $79/mo tier missed); the "six-figure minimum" is legacy-enterprise only.
- **CourtListener API** — default rate cut hard **May 2026** (~5 req/min for new/anon users); RECAP archive still permanently free. **PACER 2027:** per-page **$0.10→$0.12**, waiver **$30→$40/qtr**.
- **EDDM** — the "$0.27–$0.52" is postage-only; true all-in loaded ≈ **$0.50–$0.80/piece** (USPS rate rise Jul 12 2026).
- **Google Street View / Google Geocoding** — imagery/geocodes are **caching-ToS-restricted** (can't warehouse). Regrid API is **$500–$2,000/mo** (bulk-nationwide ~$80k/yr is an unverified guess). CoreLogic is now **Cotality**; its "$12k/yr" is one self-reported datapoint, not a median.
- **🚨 ATTOM transactional API is OFF THE TABLE for this architecture (R5 teardown):** its ToS forbids **caching/storing data >24h** and forbids **building a derivative database** — our persistent, disk-cached, self-enriching board would breach the license. Only **ATTOM Bulk/Cloud licensing** (custom-quote, batch-ETL) is compliant, and only worth it at scale. **Substitute RentCast (permissive license, self-serve, wire at $74/mo Foundation) for AVM/value, + Realie for bulk county hydration** wherever the blueprint below says "ATTOM ~$500/mo API." ATTOM also carries **no contact/skip data** and its distress filings **lag our own county scrapers.**
- **R5 integration verdicts (full teardowns in deepdive doc):** WIRE NOW → **Geocodio** (address-less fix, storage-legal), **RentCast** (AVM/rent drop-in). PAID FALLBACK → **BatchData** skip-trace (TCPA/DNC-aware; NOT its property data), **PropertyRadar** ($549–599 Business API — the clean alternative since **PropStream has no API + ToS forbids our use**). WHEN-MAILING → **Stannp** + **TrueNCOA**. PHASE-2 → **Senzing** (stateful entity-resolution service).
- **Verified accurate ✅:** RentCast, Realie, TrueNCOA $20/file, Geocodio ($0.50→$1.00 Feb-2026, storage-allowed), Canopy/MLS Grid/Trestle, HUD SAFMR, Zillow ZORI, DataZapp 3¢, Tracerfy 2¢, PropStream/DealMachine/REsimpli tier prices, PropertyRadar Business, All-The-Leads/US-Probate/Warren-Group, US Title Records $29/$95/$375, Street View tier rates, RVM $0.012–$0.05.

## 🔬 Round-18 adversarial-verification corrections (retractions to deep-dive claims; full tables in deepdive doc)
_Tally: 14 confirmed / 15 need-nuance / 5 wrong / 1 unverifiable — the core held, precision tightened._
- **RETRACT the "Rutherford one-line fix":** `gis.rutherfordcountync.gov` hosts **no parcel/CAMA service at all** — the MapServer/6→7 unlock was wrong. Rutherford stays a real free gap (use NC OneMap / lrcpwa instead).
- **UPGRADE Laurens SC (new free win):** it actually **has** a bulk layer (`Pebble/TaxParcel/MapServer`) carrying Owner + Mailing + **Sale_Price + Sqft** — better than the earlier "cadastral-only" claim.
- **SC lis pendens files with the Clerk of Court, NOT the ROD** (§15-11-10) — fix the earliest-signal plumbing.
- **Senzing is NOT free for production** — 100k is evaluation/PoC only; production is a paid per-DSR subscription. Adjust the Phase-1 "free entity resolution" line.
- **"Recorded satisfaction = exact $0" is too strong** — strongly indicates but doesn't conclusively prove (erroneous/partial releases exist).
- **SC exempt-deed price reconstruction is weaker than stated** — per §12-24-70 exempt deeds state an exemption *reason*, not $0 (value omitted); assessed÷ratio only recovers the county's appraised value, not a sale price. Honest position: distressed SC targets carry **no recoverable stamp value**.
- **MIE sale day varies by court** (statutory default first Monday, but Charleston/Anderson use first Tuesday) — don't hardcode first-Monday.
- **Minor:** the 15%/25% adjustment-guideline retirement is **Fannie-specific** (SEL-2014-16); condition adj is dollar-based not ~5%/step; NC avg assignment fee ≈$22k; transactional funding is greater-of-%-or-flat (not additive); BRRRR 75% needs ~6-mo seasoning + 2026 rates push buy-in toward 65–70% ARV; MERS MIN prints on the DOT only on MERS-as-mortgagee loans.


## Contents

1. Score: ARV / Rehab / Max-Bid / Wholesale-MAO / ROI (the valuation & underwriting engine)
2. Score: Grade + Intent + Signal Stack + Distress Stack + Corroboration + Strategy Fit
3. Owner Phone & Email (Skip-Trace)
4. Owner Mailing Address + Deliverability (NCOA / Absentee / Out-of-State)
5. Property Physical Specs (beds / baths / sqft / year built / lot / structures)
6. Valuation Inputs: Assessed / Market / Tax Value + Full Sale-Price History
7. Sold Comps (the ARV basis)
8. Rent Comps & Cash-Flow (Rents, ZORI, FMR)
9. Mortgage / Deed-of-Trust / Original Loan Amount — 3.6%
10. Live Payoff, Current Lien Balance & the FULL Lien Stack (equity — 6.9%)
11. Court / Legal Foreclosure Status & Timeline
12. Property Condition & Rehab Signal — Path to 100%
13. Distress / Life-Event Sources (Probate, Divorce, Bankruptcy, Incarceration, Death, Vacancy, Eviction, Code)
14. Geospatial: Situs Address, Parcel ID, Lat/Lng & the Address-LESS Lead Problem
15. The PIECING — Identity Resolution & the Data-Join Backbone
16. The "BUY IT ALL" Platform Comparison — One Paid Subscription vs. Our Free Stack
17. Recurring Operating Model & Total Cost of Ownership (Keeping It 100% and Fresh)
18. Completeness Critic — gaps the sections missed


---

## Score: ARV / Rehab / Max-Bid / Wholesale-MAO / ROI (the valuation & underwriting engine)

### What it is & why it matters (for motivated-seller acquisition)
This is the layer that turns a distressed lead into a *number you can offer*. Every acquisition strategy the mission names — wholesale, subject-to, fix-flip, gator, land — lives or dies on three outputs: what the house is worth fixed up (ARV), what it costs to fix (rehab), and the most you can pay and still profit (max-bid / wholesale-MAO). A lead with a name, a phone, and an address is worthless if the underwriting says "PASS" or, worse, produces a confident wrong number that sends an operator to overpay at a courthouse auction. In this engine the Score is not cosmetic: `grading.py` *withholds the overall A–F grade entirely* unless there is an opening bid or a non-proxy (HIGH/MEDIUM) ARV, and it withholds again when ROI > 400% or ARV > $2M (garbage-in guard). So the valuation engine is the gate that decides whether a lead is even *ratable*. That is exactly why the board shows 4,042 "none" grades — those are leads the engine refused to score for lack of trustworthy ARV inputs.

### Current state in the engine (measured fill-rate, how it's sourced now, the exact code files)
The formula (all in `src/foreclosure_scraper/valuation/calc.py`):
- **ARV** picks the best available signal in `_arv_signals()`: **Tier 0** recorded arms-length sales $/sqft × subject sqft (`enrichment_recorded_comps.py` GIS + `enrichment_assessor_comps.py` self-comp), **Tier 1** scraped HomeHarvest sold comps median adjusted-$/sqft × sqft (`enrichment_comps.py`), **Tier 2** Zillow zestimate → FHFA-HPI rescale → **tax_value × 1.25** → **opening_bid × 2.4**. Range = min/max of the adjusted $/sqft series, or expected ±15%. Guardrails: `MAX_PROXY_ARV=$2M`, an assessed-value cross-check (>2.5× or <0.6× → drop to MEDIUM), and an ARV *floor* at county market value / last recorded sale.
- **arv_confidence** = HIGH only when comps are geo-anchored, ≥3 of them, and agree (≤1.6× spread); MEDIUM for zestimate/tax/estimated-sqft; LOW for bid proxy. Measured board dist: **HIGH 399 (2.3%) / MEDIUM 12,479 / LOW 4,125**.
- **Rehab** = `_condition_to_tier()` maps a 4-tier condition (from Vision → `enrichment_comps` text → year-built default) onto 5 $/sqft tiers (`REHAB_TIERS`, cheaper `MOBILE_REHAB_TIERS`), × living_sqft, capped at a tier-appropriate % of ARV. Vision's own photo-derived `rehab_psf` overrides when HIGH/MEDIUM (`enrichment_vision.py`).
- **max_bid_70** = `0.75 × ARV − rehab_with_contingency(×1.125) − senior_liens − surviving_payoff` (the 0.75 and single-fee fix came from the n=266 backtest).
- **wholesale_mao** = max_bid − $10,000 assignment fee; **wholesale_spread** = max_bid − opening_bid.
- **ROI / cash-on-cash / cap-rate** flow from bid + rehab + closing(4%) + holding(velocity-scaled) + selling(7%).

Measured input fill (N=17,003, live from `docs/listings.json`): **living_sqft 6.6%, condition_tier 14.0%, any comp $/sqft 9.7% (recorded 3.1%), vision ~0%.** The three inputs the ARV *trusts* are the three that are nearly empty.

### What reaching 100% actually requires (the data elements + the identity join that must succeed)
For a *trustworthy* ARV on every lead you need three things at 100%, joined to the subject parcel: (1) **true living GLA** (heated sqft), (2) **≥3 geo-anchored arms-length sold comps** within ~1 mile of comparable size/beds/era, (3) **current condition** (photo or field). The identity join is the hard part: comps and sqft key off `parcel_id` (88% filled) or lat/lng (21.8%) — so the ~40% of leads with no geocode and the ~34% with no parcel-linked CAMA sqft *cannot* be valued off comps at all, no matter how good the comp source is. ARV at 100% is therefore gated on the **address/geocode/parcel resolver** succeeding first, then on a sqft source, then a comp source, then condition.

### FREE routes
- **County CAMA/assessor heated-sqft join** — source: each county ArcGIS/qPublic card (`enrichment_assessor_card.py`, `enrichment_recorded_comps.py`). Method: parcel_id → card → `HEATED_AREA`. Coverage ceiling: ~80–85% (parcel_id is 88%, but SC owner layers carry no sqft field — a documented gap). Effort: medium (per-county field config already built for 6 NC counties). Cadence: monthly. Compliant (public GIS).
- **GIS recorded arms-length sales for comps** — already Tier 0; ceiling limited to counties whose layer exposes a sqft field (currently 6 NC; SC blocked). Free, monthly, compliant.
- **Free Vision condition** — `enrichment_vision.py` already pools Gemini (3-key rotation, 750 RPD) + GitHub Models + Groq + NVIDIA NIM (13 lanes) + Ollama local, all $0. Ceiling = **images fill-rate (21.1%)**: Vision can only see leads that have photos, and only 21% do. Effort: already built. Compliant.
- **FHFA-HPI rescale** — already the coarse LOW fallback for comp-thin rural leads; free, statewide, monthly.

### PAID routes
- **RentCast API** — property record (beds/baths/**sqft**/year) + AVM value + sale comps + rent comps in one call. Pricing (as of 2026, verify): free 50/mo; **Foundation $74/mo = 1,000 req ($0.06 over); Growth $199/mo = 5,000 ($0.03 over); Scale $449/mo = 25,000 ($0.015 over)** ([rentcast.io/pricing](https://www.rentcast.io/pricing)). Coverage ~140M properties; realistically fills sqft + a comp-grounded AVM on **80–90%** of in-footprint SFR (thinner on rural mobile/land). Integration: low — one REST call keyed by address, maps straight into `raw.comp_median_ppsf`/`market_value`. ToS: commercial use permitted on paid tiers; not for redistribution of raw records.
- **ATTOM** — assessor sqft/characteristics + AVM + sales history, via API or bulk. Pricing (as of 2026, verify): API from **$95/mo**, Property Navigator **$499/yr**, per-record bulk **quote-only** (7,200 attributes, 158M properties) ([attomdata.com](https://www.attomdata.com/solutions/bulk-data-licensing/)). Best for a one-time **bulk sqft/characteristics backfill** across all 18 counties. Integration: medium (bulk file join on APN). ToS: license restricts redistribution.
- **HouseCanary** — the closest to a true institutional ARV + comps + condition-aware value report. Pricing (as of 2026, verify): Data plans **$19–$199**; Basic **$190/yr = 2 reports/mo**; high-volume = custom enterprise ([housecanary.com/pricing](https://www.housecanary.com/pricing)). Best reserved for *final diligence on A/B leads*, not the whole board. ToS: per-report license.
- **Exterior BPO (human)** — for condition on the un-photographed slice. Pricing (as of 2026, verify): **$30–$100 drive-by, $50–$150 interior** ([experian.com](https://www.experian.com/blogs/ask-experian/what-is-broker-price-opinion/)). Only economical on shortlisted deals.

### Feasibility verdict
**CANNOT hit a genuine 100% HIGH-confidence ARV on every lead — a hard ceiling exists, and it is upstream of this engine.** Two walls: (1) **condition** — an accurate rehab tier requires seeing the property; ~79% of leads have no photo and no vendor sells interior condition without a human visit, so condition is capped at the images fill-rate plus paid BPOs. (2) **comps for the truly unique** — raw land, mobile homes, and micro-markets with <3 nearby arms-length sales have no comp basis at *any* price (RentCast/ATTOM/HouseCanary all thin out there); those legitimately stay MEDIUM/LOW. What CAN reach ~90–95% is a *defensible* ARV (comp- or AVM-grounded) once sqft and geocode are filled. The engine already models this honestly by grading such leads MEDIUM and withholding when it can't.

### Recurring cost & cadence at our scale
17,003 leads, monthly refresh. But you do not re-value 17k every month — most are static. Realistic monthly *new+changed* volume ≈ 3,000–5,000. **RentCast Growth ($199/mo, 5,000 req)** covers a full monthly cycle of sqft+AVM+comps with headroom; **Scale ($449/mo, 25,000)** covers a full 17k re-value at **$0.026/lead**. A one-time **ATTOM bulk sqft backfill** (quote-only, budget $1,500–$5,000 one-time) closes the 6.6%→~85% sqft gap permanently. Vision stays $0. BPOs only on the ~50–100 A/B deals actually pursued: ~$3,000–$5,000/yr. **All-in steady state ≈ $199–$449/mo API + ~$300–$400/mo amortized BPO ≈ $2,900–$5,600/yr.**

### MANUAL PLAYBOOK (per un-automatable lead, for a VA)
1. Open the county assessor/GIS parcel viewer; search the `parcel_id` (or owner name).
2. Record **heated/living sqft, beds, baths, year built** from the property card into the lead's sqft/beds fields.
3. In the county's **recorded-sales/qPublic "sales" tab**, note the 3 most recent nearby arms-length sales (price, date, sqft); compute each $/sqft; take the median → that × subject sqft is the manual ARV.
4. Pull up the address on Google Street View + county aerial; classify condition as move_in_ready / cosmetic / major / gut and log it.
5. If no photo exists and the deal is shortlisted, order an **exterior drive-by BPO** ($30–$100) and paste its value + condition.
6. Enter sqft, median $/sqft, and condition tier into the lead; the calculator recomputes ARV/rehab/max-bid/MAO deterministically.

### Recommended path (closest to 100% for least money)
Fix the *inputs*, not the formula — the formula is already sound and backtested. (1) **One-time ATTOM (or RentCast bulk) sqft/characteristics backfill** to take living_sqft from 6.6% to ~85% — this alone unlocks the $/sqft comp path on the majority of leads and is the single highest-leverage dollar. (2) **RentCast Growth $199/mo** as the standing AVM+comps+rent fallback for every geocoded lead that county GIS can't comp, lifting comp-grounded coverage toward ~90%. (3) **Keep Vision free** and push the *images* fill-rate up (scrape more photo sources) — that is the cheapest lever on condition. (4) **Reserve HouseCanary/BPO for A/B leads only.** Net: ~$200–$450/mo + a one-time backfill moves the board from 2.3% HIGH-confidence ARV to a defensible comp/AVM-grounded value on the large majority, while land/mobile/comp-thin rurals honestly remain MEDIUM — which is the real, non-fabricated 100%.

Sources: [rentcast.io/pricing](https://www.rentcast.io/pricing), [housecanary.com/pricing](https://www.housecanary.com/pricing), [attomdata.com bulk licensing](https://www.attomdata.com/solutions/bulk-data-licensing/), [experian.com BPO](https://www.experian.com/blogs/ask-experian/what-is-broker-price-opinion/).

---

## Score: Grade + Intent + Signal Stack + Distress Stack + Corroboration + Strategy Fit

### What it is & why it matters (for motivated-seller acquisition)
This is the engine's decision layer — the six computed fields that turn 17,003 raw rows into a ranked call list. **Grade** (A–F + 0–100) answers "is this a deal?"; **Intent Score** (0–100) answers "how motivated is this seller?"; **Signal Stack** counts distinct distress lists a property hits; **Distress Stack** tiers it HOT/WARM/COLD; **Corroboration** answers "is the distress court-confirmed or just an aggregator flag?"; **Strategy Fit** tags the exit play (WHOLESALE / SUBJECT_TO / FIX_FLIP / LAND_WHOLESALE / GATOR / BUY_HOLD). For acquisition, these are the whole point: an operator with limited dials works the HOT + high-intent + court-confirmed + high-equity slice first. Every empty score is a lead nobody calls.

### Current state in the engine (measured fill-rate, how it's sourced, exact code files)
All six are **pure-compute, zero-scrape, zero-cost** — they consume upstream fills, never fetch. Grade dist: A1 / B86 / C5407 / D7322 / F145 / **none 4042** (23.8% ungraded). equity computed on **6.9%**; strategy_fit is mostly null because it gates on equity/tenure. Files:
- `valuation/grading.py` — `grade()`: overall = **financial×0.40 + property×0.25 + location×0.20 + risk×0.15**. Financial sub-score is bid-to-ARV banded (≤30%→98, ≤55%→85 "within 70% rule", ≤70%→70, >100%→15) ± ROI bonus; consumes `opening_bid` + `calc.arv_expected`. Property = year_built + beds/baths/sqft + flag keywords. Location = hardcoded county tier (tier-1 88 / tier-2 78 / tier-3 65) + optional Census median income. Risk = listing-type + condition flags + `equity.pct` + judgment-vs-ARV. **Grade is withheld (None) when not `assessable`** = no `opening_bid` AND no HIGH/MEDIUM-confidence ARV (bid fills 4.3%, judgment 1.1%), OR when `anomalous` (ROI>400%, ARV>$2M, or bid<5% of ARV). Those two gates produce the 4,042 nulls: rows with only a LOW (proxy) ARV and no real bid.
- `distress_score.py` — `score_board()`: groups by `parcel_id`, unions signals into 5 categories (FINANCIAL/SALES/LEGAL/LIFE_EVENT/PROPERTY), `stack` = distinct categories, `score` = best weight per category (foreclosure_sale 30, lis_pendens 28, probate 20, +8 absentee). **HOT = stack≥2 AND equity≥med AND mailable AND not senior-survives; WARM = stack≥2 OR (score≥28 AND equity) OR (absentee+stack≥1+score≥20); else COLD.**
- `enrichment_lead_signals.py` — signal_stack = distress signals ∪ facet predicates (tax_owed, liens, code_enforcement, vacant, absentee…). intent_score = **stack×10 (cap 30) + distress_score/90×45 + grade.overall_score/100×25**. Grade None → contributes 0 of 25.
- `enrichment_corroboration.py` — classifies every source slug (primary + `also_seen_in`) into court/government/aggregator by substring; strongest tier wins; court_confirmed if any COURT source.
- `enrichment_strategy_fit.py` — tags off equity band + tenure + condition + listing_type.

### What reaching 100% actually requires (data elements + the identity join)
The scores themselves already run on 100% of rows — they are never "missing," they are **starved**. Three upstream fills starve them: (1) **equity %** (6.9%), which gates HOT, SUBJECT_TO, WHOLESALE, and risk; (2) **a real acquisition figure** (opening_bid 4.3% / judgment 1.1%) or a **HIGH/MEDIUM ARV**, which gates the whole grade; (3) **sale_date, condition, and specs**, which set ARV confidence. Equity itself needs **loan/mortgage balance** (ROD deed-of-trust amount, 3.6%) + **last_sale_price** (12%) + **lien stack**. Every one of those is keyed on a successful **owner→property→parcel identity join** (parcel_id is 88%, so the join spine mostly exists; what's missing is the *dollars* hanging off it).

### FREE routes
- **Census ACS B19013 median-income by ZCTA** — official `api.census.gov` (now key-required, free instant key) or `freecensusapi.com`. Feeds the location sub-score (already referenced in `grading.py`). Coverage ceiling ~99% of ZIPs; effort low (one join); cadence annual; compliant (public API).
- **County ROD deed-of-trust images (loan amount)** — already a known repo route ([ROD document images are FREE]). OCR the recorded note → payoff → equity. Ceiling ~70–85% of parcels with a recorded DT; effort high (per-doc OCR); monthly; compliant.
- **Assessor/CAMA last-sale-price + sqft** (qPublic cards, SCDOT, NC OneMap) — already wired; widening the card gate lifts ARV confidence → un-withholds grades. Ceiling ~60–80%; medium effort; monthly; compliant (public records).
- **On-demand assessor card for graded-B+ only** — already in `main.py`; extend the trigger to the 4,042 None-grades to try to clear the "no ARV" gate. Ceiling: recovers rows that have a card; free.

### PAID routes (real 2026 pricing — verify)
- **BatchData API** — 155M properties, 700+ attributes, AVM, last-sale, loan/mortgage, owner. Property Search from **$0.01/call, plans from $500/mo (20k calls)**; skip-trace/contact enrichment from **$2,000/mo (100k records)** (as of 2026, verify). Fills ARV, equity inputs, phone. Fills the grade AND intent in one shot. Integration: medium (REST). ToS: commercial data license, compliant.
- **ATTOM Property Data API** — ~9,000 attributes, AVM, 10-yr sales comps, mortgage, foreclosure. **From $95/mo entry; enterprise from $499/yr, volume quoted** (as of 2026, verify). Best single source for HIGH-confidence ARV + payoff → clears the grade withhold. Integration medium; licensed data, compliant.
- **Regrid parcel API** — 156M standardized parcels, owner, building. Per-record self-serve on Pro/Team tiers (quote-based) (as of 2026, verify). Strengthens the join spine + property sub-score. Low-medium effort; licensed.
- **PropStream** — Essentials **$99/mo**, Pro **$199/mo** (skip-trace free on Pro), skip-trace **$0.12/result** standalone (as of 2026, verify). Manual/export, not API; good for VA workflow.
- **Skip-trace per-hit** (for owner_PHONE, which lifts *contactability* → the HOT gate, not the score math): **Tracerfy ~$0.02/record; BatchData $0.10–0.15; TLOxp ~$0.50/record; Spokeo ~$1.83/connect** (as of 2026, verify).

### Feasibility verdict
**CAN reach ~100% coverage of *populated* scores, but CANNOT reach 100% *trustworthy* grades from free routes alone.** The scores are computed on every row today; the hard ceiling is **valuation confidence**: a grade is only honest with a real acquisition price or a HIGH/MEDIUM ARV, and HIGH-confidence ARV needs sold-comps + condition + sqft that free county data supplies unevenly (LOW-confidence ARV is 4,125 rows). The grade withhold is a *feature* — forcing it to A–F on proxy data would be lying. So the realistic target is **~95–98% carrying a defensible grade** once equity + ARV are filled; the residual few % are parcels with no recorded sale, no bid, and no comps — an unavoidable data desert, not a code bug.

### Recurring cost & cadence at our scale (17k leads, 18 counties, monthly refresh)
The scoring code is $0/month forever. The cost is in the fills:
- **All-free stack** (Census + ROD OCR + assessor cards): $0 recurring, unlocks equity/ARV on the ~60–80% of parcels with recorded data.
- **ATTOM entry** for HIGH-conf ARV + payoff: ~**$95–$500/mo** flat → clears most of the 4,042 grade nulls. Best value.
- **BatchData enrichment** at 17k records once/month: at $0.02–$0.05 blended ≈ **$340–$850/mo**, or the **$500/mo** search plan (17k << 20k call cap) — one refresh fits one plan tier.
- **Skip-trace for HOT/WARM only** (say ~2,000 leads/mo at $0.02–$0.12): **$40–$240/mo**, and this feeds *contactability* (the HOT gate) more than the score itself.
Blended recommendation lands at **~$500–$700/mo** for near-complete, trustworthy grades + intent.

### MANUAL PLAYBOOK (VA / operator, for the un-automatable slice)
For each ungraded HOT/WARM lead the operator wants scored by hand:
1. Open the county **assessor/GIS card** by parcel_id (link already on the dashboard). Record **last sale price + date, heated sqft, year built, beds/baths**.
2. Open the county **ROD/register of deeds** search; pull the most recent **Deed of Trust**; record the **original loan amount + recording date** (the payoff input).
3. Open **Zillow/Redfin** for the subject; pull **3 sold comps** within ~1 mi / 6 mo / same beds; average $/sqft × subject sqft = **manual ARV**.
4. Compute **equity = ARV − (amortized loan balance) − known liens**; band it (≥40% high, ≥15% med).
5. Enter sale price, sqft, ARV, and loan amount into the lead's fields; the pipeline's `calc` + `grade` recompute automatically on next run (assessable gate now passes → real A–F).
6. For contactability: run the owner name through the free/paid skip-trace of record, add phone, flip the lead toward the HOT gate.
Never bypass a CAPTCHA/anti-bot wall — if a portal blocks automation, the VA gathers it by hand here; that is the compliant fallback.

### Recommended path (closest to 100% for the least money)
1. **Free first, immediately:** wire the **Census ACS** join (location sub-score) and extend the **on-demand assessor-card** trigger to the 4,042 None-grades — pure code, $0, recovers every row that has a public card.
2. **One paid valuation feed:** add **ATTOM entry (~$95–$500/mo)** as the ARV/payoff backstop — this single spend converts the most grade-nulls to real A–F and populates equity, which cascades into HOT tiering, intent's 25-pt grade component, and strategy_fit.
3. **Skip-trace only the HOT/WARM slice** at **$0.02–$0.12/hit (~$40–$240/mo)** to satisfy the contactability gate — don't skip-trace all 17k.
4. **Keep the withhold logic.** Report the residual "no-comp/no-bid/no-deed" desert as an honest ~2–5% unscoreable floor, not a defect. Total ~**$500–$700/mo** buys ~95–98% trustworthy grade + intent coverage.

Sources: [PropStream pricing](https://www.propstream.com/pricing) · [BatchData pricing](https://batchdata.io/pricing) · [ATTOM Property Navigator pricing](https://www.attomdata.com/solutions/property-navigator/pricing/) · [Regrid API plans](https://app.regrid.com/api/plans) · [Tracerfy skip-trace API](https://www.tracerfy.com/skip-tracing-api) · [Census ACS data/API](https://www.census.gov/data/developers/data-sets.html)

---

## Owner Phone & Email (Skip-Trace)

### What it is & why it matters (for motivated-seller acquisition)
A parcel, a name, and a mailing address are inert until you can *reach the owner*. Direct mail alone converts distressed-owner lists at roughly 0.5–1%; adding a phone number and email lets you cold-call, ringless-voicemail, and SMS the same list, which is how wholesalers actually get contracts before the auction/redemption clock runs out. For our HOT tier (imminent sale, short redemption window), a phone is the difference between a deal and a missed one. This is the single highest-leverage gap in the whole engine: we can value 98% of leads but can only *dial* 2.2% of them.

### Current state in the engine (measured fill-rate, how it's sourced now, exact code files)
Measured: `owner_PHONE` 2.2% (381 rows), `owner_email` ~0%, `raw.skip_trace` present on 153. Two code paths do all of it:
- `src/foreclosure_scraper/enrichment_voter_phone.py` — the **only** structured personal-phone source. Loads the free NCSBE bulk voter file (`data/ncvoter/`), builds a `(last,first,house#,street6)` index plus a county-unique-name fallback, and matches active NC voters to owners. `full_phone_number` is ~69% populated in-file; every hit is tagged `source=ncsbe_voter, needs_dnc_scrub=True`. NC-only.
- `src/foreclosure_scraper/enrichment_skip_trace.py` — provider-pluggable (`SKIP_TRACE_PROVIDER` env). Default is `NoopProvider`. `TaxRecordsOnlyProvider`/`FreeProvider` produce the reliable free win (owner + mailing address + absentee flag from `raw.owner_mailing`, feeding the 65.8% mailing fill), and `FreePeopleSearchProvider` best-effort browser-scrapes FastPeopleSearch for the top-40 imminent listings (low-confidence). `BatchSkipTracingProvider` exists but is **untested and disabled** (no key). The human worksheet is `scripts/build_skiptrace_worksheet.py` → `docs/skiptrace_worksheet.csv` (click-ready TruePeopleSearch/FastPeopleSearch links).

### What reaching 100% actually requires (data elements + the identity join)
Elements: 1+ current cell/landline, DNC/litigator flag, ideally an email. The hard part is the **identity join**: our owner string is deed-style (`LAST FIRST`, sometimes an LLC), and the property may be absentee, so name+property-address alone misses out-of-state owners. A credit-header vendor joins on name + *any* historical address and returns the person's current phones — that is exactly the join we cannot do for free at scale. Two structural ceilings: (a) ~10% of owners are LLCs/trusts with no personal phone to find (route to the SoS-agent enricher instead), and (b) SC has no lawful free personal-phone source at all.

### FREE routes
- **NC voter file (NCSBE bulk)** — source: `dl.ncsbe.gov` full voter download; method: already wired in `enrichment_voter_phone.py`; coverage-ceiling: ~35–45% of *NC owner-occupants* (69% of records carry a phone, minus join misses, minus absentees); effort: low (re-download + re-index); cadence: quarterly; compliance: public record, still `needs_dnc_scrub` before any dial.
- **County tax/GIS mailing address** — already 65.8% fill; gives a *mailing* channel, not phone; free, monthly, no compliance issue.
- **TruePeopleSearch / FastPeopleSearch (manual/operator)** — source: the two free people-search sites; method: the click-ready links in `skiptrace_worksheet.csv`, opened by a human (both are Cloudflare/anti-bot-walled — **automated scraping is ToS-gray and bot-blocked**, so the compliant form is operator-gathers-by-hand, not the `FreePeopleSearchProvider` at scale); coverage-ceiling: ~50–70% find *a* number, lower for common names; effort: high (≈1–2 min/lead by hand); cadence: on-demand for HOT tier only; compliance: both sites disclaim FCRA and forbid use for credit/tenant/employment decisions — fine for real-estate outreach, not for tenant screening; still DNC-scrub.
- **SC**: no lawful free personal-phone source exists (SC voter file excludes phone). Free SC path is mailing-address only.

### PAID routes (real 2026 pricing — verify each)
- **BatchData / BatchSkipTracing** — name+address → 12+ points incl. phones, emails, DNC/litigator. **$0.07–$0.18/record** pay-as-you-go, ~$0.02 at Growth-tier volume; standalone plans from **$2,000/mo for 100k** (as of 2026, verify). Match ~60–75%. Integration: low — the `BatchSkipTracingProvider` stub already targets this API; needs a key + response-shape validation. Best fit for our volume.
- **REISkip** — **$0.15–$0.22/match**, pay only for hits, claims 85–90% match (as of 2026, verify). No PI license. Low integration (REST). Strong wholesaler default.
- **DataZapp** — reverse-phone/skip append at **$0.02–$0.03/match**, $125 minimum (≈4,000 records) (as of 2026, verify); accuracy 75–85%. Cheapest per-record; bulk CSV upload, light API. Good for whole-board sweeps.
- **PropStream skip trace** — **$0.12/result**, free on Pro/Elite ($99/mo base) (as of 2026, verify). GUI-first, weak API; better as an operator tool than a pipeline enricher.
- **People Data Labs** — person enrichment **$0.28/credit monthly, ~$0.20 annual**, charged on match only; **emails/phones gated** on lower tiers, enterprise ~$2,500/mo (as of 2026, verify). Built for B2B; weak on residential distressed owners — poor fit.
- **Endato / EnformionGO (PeopleConnect)** — Contact Enrichment API, no minimums/contracts, per-match shown in dashboard (public per-lookup not posted; typically ~$0.05–$0.25, verify). Free trial tiers. Reasonable mid-option.
- **TLOxp (TransUnion)** — **~$1.50/basic, ~$4.50/full** search (as of 2026, verify). Highest quality, but **requires licensed PI / attorney / credentialed collections** with site inspection — **we do not qualify**, so effectively unavailable.
- **LexisNexis Accurint** — from **~$200/mo** + per-search, custom (as of 2026, verify); **DPPA/GLBA permissible-purpose credentialing required** — real-estate marketing is *not* an obvious permissible purpose. Likely unavailable to us.
- **IDI idiCORE** — **$0.50–$2.00/record**, pay-as-you-go, no minimum (as of 2026, verify); FCRA permissible-purpose application required. Gray on eligibility.
- **Ekata / Whitepages Pro (Mastercard)** — identity/phone verification **$0.10–$0.50/lookup**, enterprise custom (as of 2026, verify). It *verifies/reverses* a phone; it is not a name→phone discovery tool — wrong shape for us.
- **Spokeo / BeenVerified-class** — consumer subscriptions ~$20–30/mo, **no bulk API, ToS forbids automated/commercial list use** — not viable at scale.
- **Melissa Personator** — credit-based phone append (2026 per-record not publicly posted, request quote; historically ~$0.01–0.05/append, verify). Address-hygiene strong, residential-phone match weaker.

### Feasibility verdict
**CANNOT** hit a literal 100%. Hard ceilings: (1) **LLC/trust owners (~10%)** have no personal phone in existence — no vendor can invent one; (2) a real slice of individuals are genuinely off-grid (no listed number); credit-header realism is **60–75% get *a* phone, 1–3 numbers each, of which one is often stale/wrong**. Practical ceiling on *usable* reachability is **~70–80% of individual-owner leads**, and getting there for SC/absentee owners *requires paid* data — the free lanes top out around 35–45% (NC-only). "100% dialable" is not an achievable target; **~75% reachable** is.

### Recurring cost & cadence at our scale (17k leads, 18 counties, monthly refresh)
We should not skip-trace 17,003 rows monthly — most never get worked. Tier it:
- **Full-board one-time baseline** via DataZapp @ $0.03: 17,003 × $0.03 = **~$510** (matches only ≈$380–430).
- **Ongoing monthly delta** (new + HOT/WARM re-traces, ~2,000–3,000 leads): BatchData/REISkip @ ~$0.15 = **$300–450/mo**; same volume on DataZapp @ $0.03 = **$60–90/mo**.
- **NC voter file**: $0. Absorbs ~35–45% of NC individuals for free, shrinking the paid pool.
Realistic run-rate: **~$100–450/mo** depending on vendor and how aggressively we re-trace, plus a one-time ~$500 baseline sweep.

### MANUAL PLAYBOOK (operator, per un-automatable lead)
1. Open `docs/skiptrace_worksheet.csv` in Google Sheets; filter `tier = HOT`, then `phone_we_have_free` = blank.
2. Click the row's `truepeoplesearch_link`. Solve the human check if prompted (operator-only — never automate this).
3. Confirm identity: match the middle initial / age / a known relative / the *property or mailing* city against the record. Reject look-alikes.
4. Copy the top 1–2 "Phone Numbers" (wireless first) into `PHONE_found`; copy any email into `EMAIL_found`.
5. If no hit, open `fastpeoplesearch_link` and repeat; if the owner is absentee, search by the **mailing-address** city, not the property city.
6. If it's an LLC/trust name, stop — flag `notes = entity` and route to the SoS registered-agent enricher instead.
7. Before any call: scrub every number against the National DNC Registry, note `needs_dnc_scrub` cleared, and only dial 8am–9pm local, TCPA wireless rules observed.
8. Paste completed rows back so `owner_phone`/`skip_trace` can be re-imported.

### Recommended path
Free first, paid for the gap. (1) Keep and re-index the **NC voter file** every quarter — it's the only free structured phone and covers a big NC slice at $0. (2) Run **one DataZapp bulk sweep (~$500)** across the whole board to establish a phone/email baseline cheaply (2–3¢/match). (3) Wire and enable the existing **BatchSkipTracingProvider** (or REISkip) for the **monthly HOT/WARM delta only** (~$100–300/mo) where match quality and DNC/litigator flags justify the higher per-record cost. (4) Keep the **manual TruePeopleSearch worksheet** as the compliant fallback for high-value HOT leads the APIs miss. Skip TLO/Accurint/idiCORE (credentialing wall), PDL/Ekata (wrong shape), and Spokeo-class (no compliant bulk API). This mix gets us from 2.2% to a realistic **~70–75% reachable** on individual owners for well under **$500/mo**.

Files referenced: `/Users/cashhigh/foreclosure-scraper/src/foreclosure_scraper/enrichment_voter_phone.py`, `/Users/cashhigh/foreclosure-scraper/src/foreclosure_scraper/enrichment_skip_trace.py`, `/Users/cashhigh/foreclosure-scraper/scripts/build_skiptrace_worksheet.py`, `/Users/cashhigh/foreclosure-scraper/docs/skiptrace_worksheet.csv`.

---

## Owner Mailing Address + Deliverability (NCOA / Absentee / Out-of-State)

### What it is & why it matters (for motivated-seller acquisition)
The owner mailing address is the taxpayer-of-record address the county sends the tax bill to — which is exactly where you mail your yellow-letter or postcard. It is the physical backbone of every direct-mail campaign, and direct mail is the dominant, most compliant outreach channel for distressed-owner acquisition (no TCPA/DNC exposure like cold-calling/SMS). Two derived flags make it doubly valuable: **absentee** (mailing ≠ situs) and **out-of-state** — these are the single strongest cheap proxies for motivation. An out-of-state owner of an inherited or tax-delinquent house is a textbook wholesale/subject-to lead. Without a deliverable mailing address, a distress signal is just a name with nowhere to send a letter, and every piece that bounces is wasted postage plus a missed contact.

### Current state in the engine
Measured fill-rate **65.8% (11,192 of 17,003)**. It is sourced 100% free from county ArcGIS/GIS parcel layers in `src/foreclosure_scraper/enrichment_owner_mailing.py` — the "contactability spine." For each listing with a situs address or parcel_id, it queries the county's open ArcGIS REST layer (18 dedicated `COUNTY_GIS` entries) and concatenates the owner-mailing fields (e.g. Henderson `OWNER_MAIL_1..ZIP`, Gaston `CURR_ADDR1..ZIPCODE`). Statewide fallbacks fill gaps: **NC OneMap** (`NC1Map_Parcels`, all 100 NC counties, `mailadd/mcity/mstate/mzip`) and **SCDOT SC_Parcels** (all 46 SC counties, `OWNER_ADDR/CITY/ZIPCODE`). `_is_absentee()` and the `out_of_state` flag are computed here; `enrichment_address_backfill.py` runs the reverse (name→property) for address-less listings. Refresh scripts: `scripts/owner_mailing_refresh.py`, `scripts/patch_owner_mailing.py`, `scripts/address_backfill_delta.py`. Critically, **there is zero CASS standardization and zero NCOA move-update** in the pipeline — the mailing string is raw county text, un-verified and possibly stale (owner moved after the last assessment).

### What reaching 100% actually requires
Two distinct problems: (a) **coverage** — an owner-mailing string for the remaining ~34% (the identity join = listing→parcel record, which fails today when parcel_id is missing/mis-formatted, the county has no ArcGIS layer, or the situs never resolved); and (b) **deliverability** — every string must be CASS-standardized (ZIP+4, DPV-confirmed as a real deliverable point) and NCOA-move-updated (48-month USPS change-of-address). CASS+NCOA is a solved commodity; the coverage join is the hard part, and it degrades gracefully to a human pulling the county card.

### FREE routes
- **County assessor/GIS owner-of-record (current path).** Method: ArcGIS REST `?where=<parcel_or_situs>&outFields=*&f=json`, already built. Coverage ceiling ~**80–85%** of parcels that have a resolved parcel_id or situs; the wall is address-less leads and the ~4 no-ArcGIS counties (Anderson SC, Cherokee SC handled via qPublic stealth). Effort: done. Cadence: monthly. Compliance: open public JSON, clean.
- **qPublic / Schneider parcel cards (Anderson, Cherokee, Union sales table).** Method: per-parcel CARD page, which shows the mailing address as structured text. Coverage: fills the ArcGIS-blank counties, ~2–4% net. Effort: medium (stealth browser, already partly built). Compliance: **anti-bot-walled — ToS-gray**; compliant fallback is operator-parses-offline (manual playbook below), never CAPTCHA evasion.
- **USPS free address tools / ZIP+4 lookup web form.** Method: usps.com Look Up a ZIP Code. Coverage of *standardization* only (not NCOA, not bulk). Ceiling: unusable at 17k scale (rate-limited, no API without a license). Verdict: not viable for automation; manual spot-check only.
- **Free NCOA "try-before-buy" tier (TrueNCOA/freencoa.com).** You upload a file and get a free *report* showing match/move counts and CASS results before paying; the corrected output requires the $20 purchase. Useful to size the move-rate for free, but not a standing free deliverability solution.

### PAID routes (all "as of 2026, verify")
- **TrueNCOA (freencoa.com):** flat **$20 per file, up to 2,000,000 records** — ~**$0.00001/record**, no minimum beyond $20, no output fee. Every file runs NCOA (18- and 48-month) **plus CASS + DPV + RDI** in one pass ([truencoa.com/pricing](https://truencoa.com/pricing/)). Provides both coverage-cleaning and full deliverability. Integration: low — CSV upload / REST API. ToS: standard NCOALink licensee, requires a signed PAF (Processing Acknowledgement Form) per list owner. **Best value by an order of magnitude.**
- **Melissa (Personator / Melissa Direct NCOA):** Melissa Direct NCOA **$2.95/1,000 records (48-mo), $2.25/1,000 (24-mo), $50 minimum** ([tekpon](https://tekpon.com/software/melissa-data/pricing/)). Personator API credits: **$30/10k, $84/30k, $285/100k, ~$1,395/500k**; address-verify/NCOA consume credits per record ([g2](https://www.g2.com/products/melissa-global-address-verification/pricing)). Adds phone/email append (relevant to our 2.2% phone gap). Coverage: same USPS COA universe as everyone. Integration: medium (mature API/SDK). ToS: NCOALink licensee, PAF required.
- **Smarty (US Address Verification):** **CASS/DPV standardization**, ~**$0.60/1k at low volume**, sliding to **$0.001–$0.004/lookup**; **100k lookups ≈ $125/mo**; plans from **$20/mo/500 lookups**, 250 free/mo ([smarty.com/pricing](https://www.smarty.com/pricing)). Best-in-class *verification/geocode* (would also lift our 21.8% geo fill), but **Smarty does NOT do NCOA move-update** — standardization only. Integration: very low (excellent API). ToS: clean, no PAF for verify.
- **AccuZIP (AccuMUV / NCOA48):** **flat annual, unlimited records**; NCOA48 add-on **from ~$396/yr** on an AccuZIP6 subscription ([accuzip.com](https://www.accuzip.com/products/modules/48-ncoalink/)). Runs CASS+NCOALink+ANKLink. Integration: medium (desktop-centric, less API-first). ToS: NCOALink licensee.
- **USPS NCOALink direct license (self-hosting):** Limited Service = 18-mo data weekly; Full Service = 48-mo. Annual fees run **five figures** (MPE Data User tiers **$15,050 / $30,100**; [PostalPro](https://postalpro.usps.com/NCOALink_Service_Providers)). Only rational at millions of records/month — **not us**.

### Feasibility verdict
**You CAN hit ~100% deliverable for the leads that have any owner-mailing string, but you CANNOT guarantee 100% owner-mailing coverage.** Deliverability is a solved commodity: TrueNCOA/AccuZIP will CASS+DPV+NCOA every record we hand them, snapping ~99% of real strings to a USPS-valid, move-updated point and flagging the un-deliverable ones. The hard ceiling is **coverage of the string itself**: the ~34% blank is the intersection of address-less court leads, mis-formatted/missing parcel_ids, and the handful of no-ArcGIS counties. Fixing the parcel-join and adding the qPublic-card operator lane realistically pushes coverage to **~90–93%**; the last ~7–10% (raw-land with no card, sealed/estate parcels, brand-new deeds not yet in the assessor roll) is genuinely un-automatable and only closable one parcel at a time by a human. **Deliverability ceiling ≈ 99% of covered; coverage ceiling ≈ 90–93% automated, ~97% with manual.**

### Recurring cost & cadence at our scale
17,003 leads, monthly refresh. Deliverability is nearly free: **TrueNCOA = $20/file/month = ~$240/yr** for the entire board CASS+DPV+NCOA'd (we are 8,500x under the 2M-record cap, so one $20 file covers everything, forever, monthly). If we prefer Smarty for verification+geocode and layer NCOA elsewhere: **17k Smarty lookups ≈ $20–$60/mo (~$240–$720/yr)** plus TrueNCOA's $20/mo for the move-update. Melissa per-record would be **17,003 × $2.95/1k ≈ $50/month** (hits the $50 floor) = ~$600/yr — 2.5x TrueNCOA for marginally better append. AccuZIP flat-unlimited ≈ **$400–$900/yr** all-in. **Bottom line: full deliverability for the whole engine costs $20–$60/month.** The only real "cost" is human labor on the un-automatable coverage slice.

### MANUAL PLAYBOOK (VA / operator, per un-resolved lead)
1. Open the county assessor's public parcel search (e.g. qPublic.net → select state/county, or the county GIS site). For no-ArcGIS counties use qPublic Anderson/Cherokee or the Schneider card.
2. Search by **parcel_id/TMS** first (paste from the listing); if blank, search by **owner name** (defendant/owner_name from the lead), then by **situs street address**.
3. Open the matching parcel **CARD / Property Detail** page.
4. Locate the **"Owner Mailing Address" / "Mailing Address" / "Taxpayer Address"** block (distinct from the situs/location line).
5. Copy the full mailing line — name, street, city, state, ZIP — into the tracker's owner_mailing column; also copy the parcel_id if the lead was missing it (feeds future auto-joins).
6. Compare mailing vs situs: if the street differs, set **absentee = TRUE**; if the state differs from the property state, set **out_of_state = TRUE**.
7. Paste the string into the free **TrueNCOA "try-before-buy"** upload (batch weekly, not one-at-a-time) to CASS-standardize and catch any move — accept the corrected ZIP+4 it returns.
8. If the card shows **no mailing address** (raw land / new deed), flag the lead `mailing_unavailable` and route to the phone/skip-trace lane instead of mail.

### Recommended path
**Free county GIS for coverage (keep and harden the parcel-join in `enrichment_owner_mailing.py`) + TrueNCOA $20/month for CASS+DPV+NCOA on the entire board + a VA manual-card lane for the un-automatable ~7–10%.** This is the least-money route to the practical ceiling: ~$240/yr gets every mailable lead standardized and move-updated (killing wasted postage), the free GIS path already carries coverage to ~85%, and the manual playbook closes the no-ArcGIS/address-less remainder. Add **Smarty only if** you also want to close the geo(lat/lng) 21.8% gap in the same call — its verify+geocode is worth the extra ~$20–40/mo, but layer TrueNCOA on top for the NCOA move-update Smarty doesn't do. Skip Melissa/AccuZIP/direct-USPS-license unless a phone/email append (Melissa) or unlimited-volume flat fee becomes the deciding factor — at 17k records they cost 2.5–40x more for no coverage gain.

---

## Property Physical Specs (beds / baths / sqft / year built / lot / structures)

### What it is & why it matters (for motivated-seller acquisition)
Physical specs are the deal-math inputs. Living sqft drives ARV (`arv = comp_$/sqft × living_sqft`), so a missing or footprint-estimated sqft caps `arv_confidence` at MEDIUM and pushes leads into the unrated/None grade bucket (4,042 leads today). Year built, condition proxies, beds/baths, lot acreage, and structure count separate a $40k gator wholesale from a $250k subject-to, tell you whether the "distressed" parcel is a house, a mobile home, or raw land, and let you filter out the un-wholesalable. Specs are the difference between a scored, prioritized board and a name-and-address list. This section is squarely the ARV-confidence unlock: real card sqft on the 4,125 LOW / 12,479 MEDIUM leads is what promotes them toward HIGH.

### Current state in the engine (measured fill-rate, how it's sourced now, the exact code files)
Measured (2026-07-02, N=17,003): living_sqft 6.6%, year_built 14.8%, beds/baths 13.5%, acreage/lot 15.1%, condition 14.2%. Three code paths, all free/public:
- **`src/foreclosure_scraper/enrichment_arcgis.py`** — address-LIKE query against per-county ArcGIS FeatureServers (9/11 SC via the shared SCDOT `SC_Parcels` MapServer, one layer per county; 12/14 NC direct county endpoints in `NC_GIS`). Only touches the ~61% with a street_address.
- **`src/foreclosure_scraper/enrichment_gis_attrs.py`** — the workhorse. Point-in-polygon by lat/lng (covers the 21.8% geocoded) with a parcel_id fallback, an expanded value-aware field map (`LIVING_SQFT_FIELDS`, `YEAR_FIELDS`, `ACRE_FIELDS`), a persistent disk cache, and a `_num()` guard that rejects denormalized-float junk. Backfills sqft/year/acreage/land_use missing-only.
- **`src/foreclosure_scraper/enrichment_assessor_card.py`** + `assessor_cards/` adapters — the per-parcel CAMA card path for the fields the bulk GIS omits (heated sqft, beds, baths, sale price). OFF by default (`ASSESSOR_CARD_ON=1`), distress-ranked, capped at `ASSESSOR_CARD_MAX=300`/run. Adapters exist for **13 counties**: Anderson, Cherokee, Georgetown, Greenville, Laurens SC; Buncombe, Cleveland, Gaston, Henderson, Lincoln, Polk, Rutherford NC; plus a `qpublic_render.py` Cloudflare-solving browser for Spartanburg, Oconee, Pickens, Union.

The low fill-rate is not a code gap — it is a **coverage gap in what the free bulk GIS layers publish**. Several SCDOT layers carry value + owner but no heated-sqft column, and several NC layers (Rutherford, Cleveland) expose geometry + parcel ID only.

### What reaching 100% actually requires
Two things must both succeed: (1) the **identity join** — a lead resolved to a specific parcel (parcel_id, or lat/lng landing inside one polygon); today parcel_id is 88% and geo 21.8%, so the join itself already fails on a slice; and (2) a **structured card for that parcel that publishes heated sqft + beds/baths + year + lot**. Element by element: living_sqft and beds/baths are the scarce ones (they live on the CAMA card, not the GIS parcel layer); year_built and acreage are semi-common on the parcel layer; lot/structures are near-universal in GIS. 100% means every one of the 18 counties has a parseable card AND every lead resolves to a parcel — the second condition is the real ceiling.

### FREE routes
- **County GIS FeatureServers (ArcGIS REST)** — already built. Method: `?geometry=<pt>&spatialRel=Intersects&outFields=*&f=json` (PIP) or `?where=<parcelfield>='<id>'`. Coverage ceiling ~**75-85% of resolved leads for year/acreage/land_use**, but only ~**15-25% for living_sqft/beds/baths** because many layers omit those columns. Effort: low (done). Cadence: monthly. Compliance: fully public government REST, no ToS issue.
- **qPublic / Schneider CAMA cards (per-parcel)** — the card that DOES carry heated sqft + beds/baths. Method: per-parcel HTML/browser render (`qpublic_render.py`). Ceiling: **~95% of built parcels in adapter counties**, but slow (~30s-3min/parcel) so it's capped. Cadence: monthly, distress-ranked top-N. Compliance: qPublic Spartanburg/Oconee/Pickens/Union sit behind Cloudflare — **anti-bot-walled**; the compliant path is the capped low-volume render (already in use) or, at true scale, the MANUAL PLAYBOOK below. **Never** bulk-scrape past the wall.
- **Regrid free API tier** — free key, standardized `ll_bldg_footprint_sqft` + building-count fields nationwide. Ceiling: fills structures/footprint sqft (not always *heated* sqft) for ~100% of parcels but the free tier is tiny (evaluation-only). Cadence: as a fallback join. Compliance: clean, licensed.
- **The hard-ceiling counties**: Rutherford and Cleveland NC FeatureServers expose no situs/CAMA on the free layer (parcel geometry + ID only), and the four SC qPublic counties are Cloudflare-walled for bulk. These are where free structured cards do **not** exist at scale.

### PAID routes
- **Realie.ai** — parcel + building attributes (sqft, year, beds/baths, lot), nationwide, self-serve. Pricing (as of 2026, verify): Free 25 req; **Tier 1 $50/mo = 1,250 req ($0.05 overage); Tier 2 $150/mo = 6,000 ($0.03); Tier 3 $350/mo = 30,000 ($0.01)**, 100 parcels/request. Coverage: national county assessor sourced, ~good in our footprint. Integration: low (REST, drop-in enricher). ToS: clean, licensed for commercial use.
- **ATTOM Property Detail API** (Estated is now folded into ATTOM) — full building/assessor detail. Pricing (as of 2026, verify): API "starts at $95/mo," realistic property-detail tiers ~**$500+/mo**; legacy Estated $179/$449/$1,799 mo tiers and **~$0.25/call test rate**; 30-day free trial. Coverage: 158M properties, 7,200+ attributes — effectively 100% of our parcels. Integration: low-medium. ToS: standard commercial license; no redistribution of raw records.
- **Datafiniti** — volume-based records/month, 10% annual discount, custom tiers, trial available; no public per-record number (as of 2026, verify — contact sales). Coverage national. Integration: low. ToS: commercial license.
- **Regrid paid / bulk** — 143+ standardized fields incl. sqft, 183M building footprints. Bulk nationwide license **starts ~$80k/yr**; API tiers custom (as of 2026, verify). Overkill for 18 counties. ToS: clean.
- **CoreLogic (Cotality)** — enterprise CAMA/assessor. No public pricing; **median ~$12,000/yr** per buyer data (as of 2026, verify). Integration: high (enterprise contract). ToS: strict, enterprise. Not worth it at our scale.

### Feasibility verdict
**CAN reach ~100% — but only via a paid vendor, not free routes alone.** The precise why: heated living sqft and beds/baths physically do not exist on the free GIS parcel layers for a large share of counties (SCDOT layers omit the sqft column; Rutherford/Cleveland NC publish geometry only), and the qPublic cards that DO carry them are Cloudflare-walled for bulk in four SC counties. Free routes therefore hit a **hard structural ceiling around 60-70% for sqft/beds/baths** even with perfect parcel resolution. A national assessor vendor (Realie/ATTOM) closes the last third because it has already licensed those same county CAMA files in bulk. The residual gap after that is the parcel-resolution failure (~12% with no parcel_id and no in-polygon geo hit) plus genuinely new/unassessed parcels — a low-single-digit floor.

### Recurring cost & cadence at our scale (17k leads, 18 counties, monthly refresh)
Only the gap needs paying for. Free GIS + the capped card render already fill specs on the resolved, adapter-covered leads. The paid backfill targets the ~**10,000-11,000 leads still missing living_sqft** (93.4% of 17,003), but you only *pay-refresh* net-new/changed parcels monthly (~1,000-3,000), because specs are static once captured and cached.
- **Realie Tier 3 ($350/mo, 30,000 req):** a full one-time backfill of all 17k = **$350** (fits in one month's quota, since 100 parcels/request → 170 requests). Ongoing monthly = **$350/mo** flat (net-new deltas sit far inside 30k). **Annual ≈ $4,200.** This is the cheapest full-coverage answer.
- **Realie Tier 1 ($50/mo, 1,250 req = 125,000 parcels/mo at 100/req):** actually covers the whole board in one call-batch too, so **$50/mo / $600/yr** may suffice — verify the 100-parcels-per-request batching holds for detail fields.
- **ATTOM:** ~$500/mo tier ≈ **$6,000/yr**; Estated-legacy $0.25/call one-time backfill of 11k ≈ **$2,750** then near-zero monthly.
- Free-only path: **$0**, ceiling ~65% sqft.

### MANUAL PLAYBOOK (VA/operator, for the un-automatable slice — the 4 Cloudflare-walled SC qPublic counties + no-parcel leads)
1. Open the county qPublic site in a normal browser (Spartanburg: `qpublic.schneidercorp.com` → select Spartanburg; likewise Oconee/Pickens/Union). Solve any Cloudflare "verify you are human" challenge by hand — this is a human using the site as intended, not automation.
2. Choose **Search → by Parcel Number** (paste the lead's parcel_id) or **by Owner Name** / **by Address** when parcel_id is blank.
3. Open the matched parcel's **Property Card / Summary**.
4. Read the **Residential/Dwelling** panel and record: **Heated Square Feet** (NOT total under roof), **Year Built** (use Actual, not Effective), **Bedrooms**, **Bathrooms**, **Stories**, and **Grade/Condition** if shown.
5. Read the **Land** panel and record **Acreage / Lot Size** and **Land Use**.
6. Record structure count from the **Buildings/Improvements** list (main dwelling vs outbuildings).
7. Paste into the shared intake sheet keyed by parcel_id (columns: living_sqft, year_built, beds, baths, acreage, land_use, condition, source_url, date). The offline parser ingests it and clears the `living_sqft_estimated` flag, re-triggering the ARV/grade pass.
8. For leads with no parcel_id: first resolve the parcel via the county GIS map (search by address/owner, read the PIN off the parcel popup), then go to step 2. Cap the VA's daily list to the distress-ranked top parcels the engine already prioritizes.

### Recommended path
Keep every free route (GIS PIP backfill + capped qPublic render) — they cost nothing and already fill specs on resolved, adapter-covered leads. Then add **one paid enricher — Realie — as the gap-filler**, wired as a new missing-only enricher that runs after `enrichment_gis_attrs` and before the calc/grade pass, querying only leads still missing living_sqft. Start on **Realie Tier 1 ($50/mo)** and verify the 100-parcels-per-request batching covers the full board; if detail-field batching is limited, step to **Tier 3 ($350/mo)**. That buys ~100% sqft/year/beds/baths for **$600-$4,200/yr**, versus ATTOM's ~$6,000/yr for the same job. Reserve the **MANUAL PLAYBOOK** for the four Cloudflare-walled SC qPublic counties and no-parcel leads that even the vendor can't join, and skip CoreLogic/Datafiniti/Regrid-bulk entirely — they are enterprise-priced for a national footprint we don't have.

**Key files:** `/Users/cashhigh/foreclosure-scraper/src/foreclosure_scraper/enrichment_gis_attrs.py`, `/Users/cashhigh/foreclosure-scraper/src/foreclosure_scraper/enrichment_assessor_card.py`, `/Users/cashhigh/foreclosure-scraper/src/foreclosure_scraper/enrichment_arcgis.py`, `/Users/cashhigh/foreclosure-scraper/src/foreclosure_scraper/assessor_cards/` (13 county adapters + `qpublic_render.py`).

---

## Valuation Inputs: Assessed / Market / Tax Value + Full Sale-Price History

### What it is & why it matters (for motivated-seller acquisition)
These four numbers are the spine of the deal math. **Market value** (county appraised) and **assessed value** anchor the ARV floor and the equity screen; **tax value / tax owed** flags delinquency-driven motivation; and the **full deed sale-price history** delivers two things nothing else can: the last arms-length price (the hard ARV floor — after-repair value can never sit below a recent real sale) and, joined to a recorded loan amount, the owner's equity. Equity is the single field that separates a wholesale/subject-to yes from a no. Without a sale-price floor, comp-ARV noise silently produces leads graded above or below their true worth (the "Gosnell bug" the code fights). At 6.9% computed-equity coverage today, most leads are being pursued half-blind on the one metric that decides whether there's a spread.

### Current state in the engine (measured fill-rate, how it's sourced now, the exact code files)
Measured (N=17,003, 2026-07-02): assessed 52.1%, market 75.2%, tax_value 54.5%, tax_owed 47.7%, **last_sale 12%**, equity(computed) 6.9%. Market is the strongest because it's summed from live county GIS; last_sale is the weakest because free SC layers withhold the sale amount.

The pipeline, in order:
- **`enrichment_gis_attrs.py`** — the workhorse. Point-in-polygon query against SCDOT SC_Parcels (SC) and per-county NC FeatureServers using the lead's lat/lng (covers ~97% that have coordinates), `outFields=*`. Value-aware field map (`MARKET_FIELDS`/`ASSESSED_FIELDS`, land+improvement summed when no total) backfills `market_value`/`assessed_value` missing-only. Disk-cached, idempotent.
- **`enrichment_gis_derived.py`** — zero new HTTP; mines the stashed `gis_attrs_full` bag for **last sale** via per-county field tables (Greenville `SLPRICE`/`DEEDDATE`, Charleston `SALE_PRICE`, Spartanburg `SaleAmount`, Pickens `SALEP`, Anderson `SALE_PRICE`/`SALE_YEAR`, Laurens gated on `True_Sale`), plus a generic fallback. **This is where SC dies**: SCDOT numeric sale fields are corrupted (uninitialized doubles ~1.2e9), so SC last-sale amount is mostly unrecoverable here.
- **`enrichment_sc_cama.py` / `sc_assessor_cama.py`** — local SQLite from the free county Assessor CSV; backfills clean SC appraised `market_value` (fixes corrupt SCDOT numbers) + specs. The CSV carries `SaleDate` but **not** `SaleAmount` or heated sqft.
- **`enrichment_assessor_card.py` + `assessor_cards/qpublic_render.py`** — the per-parcel escape hatch. OFF by default (`ASSESSOR_CARD_ON=1`); distress-ranked, capped at 300/run; renders the county card (Cloudflare-solved) to read the **sale-history grid** and heated sqft the bulk feeds omit. `calc.py` ARV floor (`floor_val = max(market_value, gis.last_sale.amount)`) consumes the result.

### What reaching 100% actually requires (data elements + the identity join)
Per parcel: (a) current assessed + market + taxable value, (b) tax billed and tax owed/paid-through, and (c) **every** grantor→grantee transfer with price + date + deed book/page. The join that must succeed is **parcel_id ↔ property**, which we already hold at 88%. So the value/assessment half is largely a coverage-completion problem, not an identity problem. The killer is (c): the complete price-bearing deed chain. In NC the recorder publishes consideration; in **SC it is legally withheld** — §12-24-40 exempt deeds (foreclosure, deed-in-lieu, intra-family, estate) state no value, and the free CAMA/GIS extracts blank `SaleAmount`. That single statute is the reason last_sale can't be free-completed in seven of our counties.

### FREE routes
- **County GIS FeatureServers (current path).** Endpoint: SCDOT SC_Parcels + NC per-county `/query?geometry=<pt>&outFields=*`. Coverage ceiling: assessed/market **~85–90%** (parcels with lat/lng in a mapped county); last-sale amount **NC ~60%, SC ~5%** (corrupt numerics). Effort: built. Cadence: monthly, cached. Compliant: open public ArcGIS, no auth.
- **qPublic / Schneider assessor card, per parcel (current, off).** Portal: `qpublic.schneidercorp.com`. Reads the full sale grid + assessed values for Pickens/Oconee/Spartanburg/Union. Ceiling: near-100% **but only within the ~300/run cap** — a render is 30s–3min behind Cloudflare Turnstile. Effort: built. Cadence: monthly, HOT/graded leads only. Compliance: ToS-gray + anti-bot-walled — this is the compliant-fallback boundary; do not scale it into a bulk scrape, keep it low-volume per-subject like a title search, and route the un-automatable slice to a human.
- **NC Register of Deeds consideration.** Free, published (unlike SC). Ceiling: **~80%** of NC sale amounts. Effort: medium (per-county ROD adapters, several exist). Compliant.
- **Free DOT-image OCR (`project_rod_document_images`).** Spartanburg Logan serves recorded deed-of-trust PDFs free; OCR page 1 for the loan principal → equity. Ceiling: HOT-gated only, fragile render. Compliant (free public record).
- **Manual card read (below).** The compliant fallback for the SC exempt-deed slice.

### PAID routes
- **ATTOM** — assessed + market + AVM + **10-yr sales history** in one call; sources SC sale price from **deed recorders**, not the assessor (the one vendor that beats the SC free wall). Pricing: published entry **$499/yr**; real API contracts commonly **~$500+/mo**, volume/enterprise custom-quoted (as of 2026, verify with ATTOM sales). 30-day trial. Coverage: ~99% nationwide. Integration: low (clean REST, `/attomavm` + sales-history resource). ToS: licensed data, no redistribution.
- **BatchData** — tax assessor (240+ pts), deed history + property-valuation modules. Pricing: **$1,000/mo / 100k records (~$0.01/record)** up to **$5,000/mo / 750k (~$0.0066)**; deed-history and valuation are **paid add-on modules** on top (as of 2026, verify). Coverage ~99%. Integration: low. ToS: per-record license.
- **HouseCanary** — AVM + valuation reports. Pricing: Basic **$19/mo (2 reports)**, Teams **$199/mo (40 reports)** ≈ **$5/report**; API/enterprise custom (as of 2026, verify). Best for HOT-lead precision AVMs, not bulk. ToS: licensed.
- **CoreLogic / ICE (Black Knight)** — the enterprise AVM cascades (QVM-class) + deep assessment/deed. Pricing: **not public; median ~$12,000/yr**, six figures at scale, sales-gated (as of 2026, verify). Coverage ~99%+, highest accuracy. Integration: heavy contract/MSA. ToS: strict enterprise license. **Overkill for 17k leads.**
- **Regrid** — parcel + assessment API. Pricing: **~$500–$2,000/mo** by fields/volume (as of 2026, verify). Note: sale price + sqft are premium/often-blank for SC — weak on our exact gap.
- **Quantarium / Collateral Analytics** — AVM only, custom-quoted, sales-gated (verify). No bulk assessment history advantage over ATTOM for us.

### Feasibility verdict
**Free routes CANNOT hit 100%** — the hard ceiling is **SC §12-24-40**: exempt deeds (exactly our distressed targets — foreclosure, deed-in-lieu, estate) legally state no consideration, and the free SC CAMA/GIS extracts blank the sale amount. No compliant free source recovers those prices at volume. **Paid ATTOM CAN effectively reach ~99% on assessed/market/tax and NC sale history, and materially lift SC** because it pulls SC price from deed recorders — but even ATTOM won't fabricate a price a $0 exempt deed never recorded, so true 100% on the *distressed* SC slice is structurally impossible; those parcels simply have no dollar figure to buy.

### Recurring cost & cadence at our scale (17k leads, 18 counties, monthly refresh)
The 17k board is stable month-to-month; only net-new parcels need a paid hit. Approaches:
- **ATTOM full monthly refresh, 17k records:** if quoted near BatchData-class economics (~$0.01/rec) → **~$170/mo** for the value+sales bundle; if on a flat API contract, **~$500–$1,000/mo** (verify). Annual **~$2k–$12k**.
- **ATTOM delta-only** (net-new + HOT re-price, ~2–3k/mo): **~$25–$300/mo**.
- **HouseCanary reserved for HOT** (~400 HIGH-confidence leads, $5/report): **~$2,000/mo** — too rich; use only for the handful of live-offer parcels.
- **CoreLogic/ICE:** **$12k+/yr floor** — not justified.
Free GIS/CAMA stays the baseline (already sunk cost, $0).

### MANUAL PLAYBOOK (for the un-automatable SC exempt-deed / capped-render slice)
1. Open `qpublic.schneidercorp.com`, pick the county (Spartanburg AppID 857, Oconee 1030, Pickens 927, Union 861).
2. Click **Agree** on the disclaimer gate.
3. Global search: paste the lead's **parcel_id** (dashed map number, e.g. Spartanburg `7-17-02-041.00`) or street address; click the first typeahead suggestion.
4. On the parcel card, read the **Value Summary** row → record Total Market (Appraised) and Assessed.
5. Scroll to the **Sales** grid; copy every row: Sale Date, Sale Price, Deed Book/Page, Reason/Qualification.
6. Keep only rows whose Reason says **QUALIFIED** (skip "Not Qualified," $1/$5, family/estate). The newest qualified row = last_sale amount + date.
7. For SC exempt-deed parcels showing $0/no price: open the **county Treasurer/tax portal** (e.g. Spartanburg qPayBill), search the same TMS, record **tax billed + tax owed / paid-through**.
8. Paste into the skip-trace worksheet columns (`market_value`, `assessed_value`, `last_sale_amount`, `last_sale_date`, `tax_owed`); the offline parser ingests it and re-runs calc/equity.
9. If the card 403s or the deed is truly value-less, mark **"SC exempt — no recorded price"** so it's excluded from the free-completion count (a known ceiling, not a miss).

### Recommended path (closest to 100% for the least money)
Keep the free stack as the always-on baseline: **GIS attrs (value) + gis_derived (NC last-sale) + sc_cama (SC clean appraised)** already deliver assessed/market/tax at 52–75%, and pushing lat/lng coverage up lifts those toward ~85–90% at $0. Turn **`ASSESSOR_CARD_ON=1`** for the monthly HOT/graded slice to recover SC sale history within the 300-cap. Then buy **exactly one paid layer: ATTOM, delta-only** (net-new + HOT re-price), the only vendor that pulls SC price from deed recorders and bundles assessed+market+10-yr sales in one call — budget **~$150–$500/mo (verify)**. Reserve **HouseCanary per-report AVMs (~$5)** strictly for parcels with a live offer where a precise number pays for itself. Skip CoreLogic/ICE, Quantarium, and Regrid — enterprise cost with no advantage on our specific SC gap. Net: **~$2k–$6k/yr** lands assessed/market/tax at ~99% and last_sale at ~70–80% overall (NC ~90%, SC lifted materially), with the residual gap being the SC exempt-deed parcels that carry **no recoverable price by law** — an accepted, documented ceiling.

Sources: [ATTOM Property Data API](https://www.attomdata.com/solutions/property-data-api/), [ATTOM Datarade profile](https://datarade.ai/data-providers/attom/profile), [HouseCanary pricing](https://www.housecanary.com/pricing), [HouseCanary G2 pricing](https://www.g2.com/products/housecanary-data/pricing), [CoreLogic PriceLevel](https://www.pricelevel.com/vendors/corelogic/pricing), [BatchData pricing](https://batchdata.io/pricing), [Regrid API plans](https://app.regrid.com/api/plans), [Quantarium QVM](https://www.quantarium.com/valuation-models/)

---

## Sold Comps (the ARV basis)

### What it is & why it matters (for motivated-seller acquisition)
The After-Repair Value (ARV) is the single most load-bearing number in every acquisition math: max allowable offer = ARV × 0.70 − rehab (the "70% rule"), wholesale spread = ARV − contract price − assignment, subject-to and fix-flip underwriting both hinge on it. ARV is only as good as the **sold comps** it rests on: 3-6 recently-closed, like-kind, nearby sales, adjusted to the subject, expressed as a median $/sqft. Get the comp basis wrong and every downstream grade (A/B/C/D/F), every max-bid, every deal you present to a buyer is wrong. This is why the crux here is not scraping volume — it is *access to sold-price data at true-comp granularity*, which in the US is gate-kept behind the MLS.

### Current state in the engine (measured fill-rate, how it's sourced now, the exact code files)
Live board (N=17,003, verified 2026-07-02): `raw.recorded_comps` on **529 (3.1%)**, `raw.comp_median_ppsf_recorded` **529 (3.1%)**, scraped `raw.comp_median_ppsf` **1,446 (8.5%)**, `raw.pulled_sale` **1,815 (10.7%)** — netting the stated ~9.7% sold-comps coverage. Two sources feed it:
- **`enrichment_recorded_comps.py`** — Tier 0 in `valuation/calc.py`. Queries each county's ArcGIS parcel layer for real recorded arms-length sales within a radius (1 mi default, 2 mi Henderson), filters `price > $10k`, `sqft > 200`, `$20–800/sqft`, medians them. This is the *highest-confidence free path* but is capped: only **6 NC counties** (Burke, Gaston, Henderson, Lincoln, Rutherford, Transylvania) carry a heated-sqft field on the GIS layer. The 3 SC layers (Pickens, Spartanburg, Laurens) have price+date+geometry but **no sqft**, so they compute nothing until a CAMA sqft join lands.
- **`enrichment_comps.py`** — HomeHarvest (Realtor.com public endpoint, $0) pulls a 180-day sold pool per county seat, runs a strict like-for-like matcher (`_pick_3_comps`: same kind → geo-radius 10mi → zip → city → sqft ±20% → beds exact → year ±15 → condition parity) plus an appraisal-style line-item adjustment grid (`_adjust_comp`). Plus `enrichment_assessor_comps.py` scales the parcel's *own* past qualified sale (a self-comp, MEDIUM only).

The gate is structural: recorded deeds give **price but no condition and often no sqft**; HomeHarvest gives listing specs but is a **list-vs-sold, ToS-gray** scrape that thins out fast in rural NC/SC ZIPs. Neither is MLS-grade sold data.

### What reaching 100% actually requires (the data elements + the identity join that must succeed)
Per subject: 3-6 **closed** sales (not list), each with sold price, close date, GLA/sqft, beds/baths, year, lot, and **condition at sale** (the element free recorded deeds never carry), within ~1 mi and ~6 months, same property kind. The join that must succeed is **subject property → MLS closed listings** on geography+attributes. That join only exists cleanly inside an MLS feed keyed to the local board.

### FREE routes
- **County GIS recorded sales** (current Tier 0). Method: ArcGIS `/query` spatial buffer. Ceiling ~**35-40%** of the board (only counties with a sqft field; ~6 of 18 today, extensible via CAMA sqft joins). Effort: medium per-county field-mapping. Cadence: monthly. Compliant (public records).
- **Assessor-card qualified sales** (`enrichment_assessor_comps.py`). The parcel's own arms-length sale scaled to today. Ceiling ~**12%** incremental (only where a card sale + real sqft exist). MEDIUM confidence. Compliant.
- **HomeHarvest / Realtor.com** (current scraped comps). Ceiling ~**10-15%** in this rural footprint before pools thin. Effort: low. Cadence: monthly. **ToS-gray** (public JSON, no auth-evasion). If it ever anti-bot-walls, fallback is operator-parses-offline, never bypass.
- **Public Zestimate/AVM via Bridge** — free *if* you hold an MLS relationship (see below); without one, not accessible. Compliant but relationship-gated.

**Free ceiling ≈ 45-50%.** Free routes give recorded *price* well but structurally cannot supply **condition-at-sale** or reliable **GLA** across all 18 counties, which is why free ARV is capped at MEDIUM confidence and why the HIGH bucket is only 399 leads today.

### PAID routes (real 2026 pricing — verify)
- **Local MLS membership + feed = the real unlock.** For our footprint that means Canopy MLS (Charlotte board; covers Gaston, Lincoln, Cleveland + others) and an Upstate-SC/Western-Carolina board (Spartanburg, Greenville/GGAR, Anderson). **Canopy: $600 one-time firm initiation + $250 one-time subscriber initiation, then $225/quarter (BIC) or $165/quarter (subscriber)** *(as of 2026, verify)* — ~$660-900/yr per person after init. Requires a **licensed agent/broker** and board membership; ToS restricts data to MLS display/analysis rules. Coverage: near-100% of *closed* sales inside that board's territory, with condition.
- **CoreLogic Trestle (RESO Web API)** — the delivery pipe on top of MLS access. **Tech-provider RESO standardized: $100/mo (up to 50 contracts), $110/$125/$150/$175 as contracts scale; Direct-MLO/CRM $125-250/mo. Broker data feed $30/mo. Plus per-MLS data-license fees billed separately.** *(as of 2026, verify — trestle-documentation.corelogic.com/data-pricing)*. Integration: RESO OData, low effort. Still requires the underlying MLS entitlement.
- **MLS Grid** (Canopy is a founding member) — normalized multi-board RESO feed. Pattern (e.g., OneKey via MLS Grid): **$250/mo feed + $20/mo per license** *(as of 2026, verify)*; you still pay each board's license fee. Best fit since Canopy already routes through it.
- **Bridge Interactive (Zillow Group)** — **no Bridge service fee**; license/fees are between you and the MLS. Requires an MLS-affiliated relationship; solo devs are ineligible *(as of 2026, verify)*. Adds free Zestimate/public-record datasets once approved.
- **ATTOM Data property/comps API** — no MLS membership needed; sold history + AVM nationwide. **Starts ~$95-500/mo self-serve; bulk/enterprise is custom with annual minimums; 30-day trial** *(as of 2026, verify)*. Lacks live MLS condition detail but covers all 18 counties uniformly.
- **HouseCanary** — AVM + comps. **Self-serve $19-199/mo (25-property monitoring tier); API/bulk is custom, six-figure annual minimums typical** *(as of 2026, verify)*. Overkill at our scale.
- **RentCast** (already referenced in `valuation/rentcast.py`) — AVM + comparable sales endpoint. **50 free calls/mo, then volume-tiered with per-call overage; no MLS license needed** *(as of 2026, verify)*. Cheap gap-filler for the no-comp slice.
- **Zillow/Redfin** — no public comps API; scraping is **ToS-prohibited / anti-bot-walled**. Not a compliant route.

### Feasibility verdict
**CANNOT hit 100% on free data alone.** The hard ceiling is that US **closed-sale price + condition data is MLS-proprietary**; recorded deeds (free) carry price but no condition and inconsistent sqft, and Realtor.com scraping is thin+ToS-gray. **CAN reach ~95%+ HIGH-confidence** only by adding a **licensed-agent MLS feed** (Canopy/MLS Grid + an Upstate-SC board) — but even that caps near 95%, because the 18 counties span **multiple MLS boards** and a handful of ultra-rural parcels have too few same-kind closings to comp at all (a data-density wall, not an access wall).

### Recurring cost & cadence at our scale
17k leads, monthly refresh, comps are *read at valuation time* not per-lead-billed. Realistic minimal stack:
- **MLS access (the unlock):** one licensed subscriber on Canopy (~$250 init + $165/quarter ≈ **$660/yr**) + one Upstate-SC board (budget similar, **~$700/yr**) + **MLS Grid $250/mo feed + $20/license ≈ $3,240/yr**. **≈ $4,600/yr** covers ~10-12 of 18 counties at HIGH confidence. Boards for the remaining rural NC counties add roughly **$700-1,500/yr each** where a separate board applies.
- **ATTOM or RentCast** as the uniform 18-county backfill for anything outside board coverage: RentCast volume tier is the cheap option (well under **$1,000/yr** at monthly-refresh call counts); ATTOM self-serve **~$1,200-6,000/yr**.
- **Total realistic: ~$5,000-7,000/yr** to move sold comps from 9.7% → ~90%+ at HIGH/MEDIUM confidence. Free-only stays at ~45-50% and mostly MEDIUM.

### MANUAL PLAYBOOK (VA/operator, for the un-automatable slice)
For a specific high-grade lead needing a defensible ARV with no MLS feed:
1. Open the county GIS/qPublic parcel viewer; confirm the subject's sqft, beds, year, kind.
2. Ask the **partner agent** (licensed, board member) to run an MLS "sold" search: same ZIP (relax to same submarket), closed last 6 months, same property kind, sqft ±20%, beds ±0-1.
3. Have the agent pull the **3 best closed comps** and export sold price, close date, sqft, beds/baths, year, and **the listing photos/remarks** (this is the condition data free sources lack).
4. For each comp, compute $/sqft = sold price ÷ sqft; note condition (move-in / cosmetic / major / gut).
5. Drop any comp whose remarks say as-is/investor-special if valuing a renovated exit; median the remaining $/sqft.
6. ARV = median $/sqft × subject sqft. Record the 3 comp addresses + $/sqft in the lead's notes so the number is auditable.
7. Cross-check against the engine's `recorded_comps` and RentCast AVM; if they disagree >15%, flag for a second agent pull. Log all figures back to the board's `raw.comps` shape.

### Recommended path (closest to 100% for least money)
Keep all free layers running (GIS recorded comps + assessor self-comps + HomeHarvest) as the baseline that already delivers ~45%. Then buy **one MLS entitlement per board that covers the most counties — Canopy via MLS Grid first (Gaston/Lincoln/Cleveland), an Upstate-SC board second (Spartanburg/Anderson/+Greenville reciprocity)** — routed through a single licensed partner agent; that alone lifts the majority of leads to HIGH-confidence for **~$4,600/yr**. Backfill the residual out-of-board rural counties with **RentCast's cheap volume API** rather than buying every remaining board. Reserve the **manual partner-agent 3-comp pull** for high-grade (A/B) leads about to go to a buyer, where a defensible, condition-adjusted ARV is worth the 15 minutes. This free + one-or-two-MLS + RentCast-backfill mix reaches ~90%+ sold-comp coverage at HIGH/MEDIUM confidence for roughly **$5,000-7,000/yr**, versus a hard free ceiling of ~45-50% at mostly MEDIUM.

---

## Rent Comps & Cash-Flow (Rents, ZORI, FMR)

### What it is & why it matters (for motivated-seller acquisition)
Rent is the second pillar of the deal after ARV. For the buy-and-hold, subject-to, BRRRR, and gator strategies the engine explicitly targets, a rent number is what converts a distressed address into a *priced* deal: it drives `cap_rate_pct`, `monthly_cashflow_est`, `noi_annual`, the 1%-rule flag, and DSCR-style logic in `valuation/calc.py`. Without a rent estimate, a rental-strategy lead cannot be graded or ranked, and the operator cannot open a conversation with an owner grounded in real numbers ("this rents for $1,450, here's what I can pay"). At 3.8% coverage, ~96% of leads have *no* cash-flow verdict — the single biggest hole in the rental thesis.

### Current state in the engine (measured fill-rate, how it's sourced now, the exact code files)
- **Fill:** `rent_median_ppsf` 648 leads, `estimated_monthly_rent` 456 (≈3.8% / 2.7% of 17,003).
- **Primary source:** `src/foreclosure_scraper/enrichment_comps.py` — `_rent_pool_for_seat()` pulls `for_rent` listings from Realtor.com via **HomeHarvest** (free), then `_pick_3_rent_comps()` does a strict same-kind + same-zip (relax to city) + beds + ±20% sqft match, takes median `rent_per_sqft`, clamps to $0.50–$3.50/sqft, and multiplies by subject `living_sqft` (lines 412–463, 712–727).
- **Fallback:** `enrichment_rent_comps_extra.py` — `_scrape_rent_pool()` re-queries HomeHarvest by zip with `past_days=180` and relaxed filters, writing `estimated_monthly_rent_extra` for leads the strict pass missed.
- **Consumer:** `valuation/calc.py` lines 830–855 reads `rent_median_ppsf`, applies the 50%-rule NOI, a 25%-down/7.5%/30-yr PITI, and emits the hold verdict.
- **Hard dependency:** the estimate needs `living_sqft` (only 6.6% filled) AND a rent pool with a same-zip match. Both failing together is why coverage is 3.8%, not why the *source* is weak.

### What reaching 100% actually requires (the data elements + the identity join that must succeed)
A rent number on every SFR needs: (1) subject **beds** (13.5%) or **sqft** (6.6%) — beds are the stronger rent driver; (2) a **zip** (41.9%) or lat/lng to key a market rent; (3) a rent source that returns a value for that zip+bed even when no active listing exists. The join is easy — everything keys on **zip + bedroom count** — so unlike sale-price comps this does NOT require a per-parcel identity resolve. The binding constraint is (a) filling beds/sqft and (b) swapping a *listings-only* pool (empty in thin rural zips) for a *modeled index* that answers for every zip.

### FREE routes
1. **HUD SAFMR (Small Area Fair Market Rent) — the workhorse.** Source: `huduser.gov/hudapi/public/fmr` REST API, free Bearer token (register at `/hudapi/public/login`) (as of 2026, verify). SAFMRs are 40th-percentile gross rents by **ZIP × bedroom (0–4BR)**, published annually (FY2026 live). Coverage ceiling: **~100% of our zips** — HUD publishes a value for every metro/nonmetro zip. Effort: low (one API call per zip + the free ZIP→FMR-area crosswalk file). Cadence: annual refresh. Compliance: fully public/open-gov, no ToS issue. Caveat: SAFMR is a voucher-payment-standard 40th-percentile number, ~10–20% below market on nicer stock, so use it as a **floor/backstop**, not the headline market rent.
2. **Zillow ZORI (Observed Rent Index).** Source: `zillow.com/research/data` free CSV, `Zip_ZORI_AllHomesPlusMultifamily_SSA` (as of 2026, verify). Smoothed typical market rent by **zip**, monthly. Coverage: high in populated zips, **thins out in rural NC/SC** (many small-county zips are absent — likely 55–70% of our footprint). Effort: low (download + join on zip). Cadence: monthly. Compliance: free research dataset, attribution-only. Limit: zip-level *blended* rent, not bed-segmented — combine with SAFMR's bed curve to shape it.
3. **HomeHarvest (current).** Realtor.com `for_rent`. Free, listing-derived, bed+sqft granular. Ceiling: **~40–50%** of leads — structurally capped because thin rural zips have zero active rentals in any 180-day window. Cadence: monthly. Compliance: public API, already in use.
4. **Census ACS B25064 (median gross rent).** Free API, tract/zip-level. Coverage ~100% but coarse (one median, no bed curve, includes older leases). Effort: low. Best as a sanity band, not primary.

**Free ceiling:** SAFMR + ZORI + HomeHarvest, stacked, gets a defensible rent on **~100% of zip-keyed SFRs** — but the top layer for most rural leads is the SAFMR floor, which is directional, not appraisal-grade.

### PAID routes
1. **RentCast (formerly Realty Mole).** Long-term rent AVM + rent comps, 140M+ properties. Pricing (as of 2026, verify, `rentcast.io/api`): Free 50 req/mo then **$0.20/req**; **Foundation $74/mo** = 1,000 req ($0.06 overage); **Growth $199/mo** = 5,000 req ($0.03); **Scale $449/mo** = 25,000 req ($0.015). One rent estimate = 1 request. Coverage: near-100% address- or zip+bed-level. Integration: trivial REST, matches our async enrichers. ToS: commercial use permitted on paid tiers; no redistribution of raw records.
2. **HelloData.ai.** Rent-comps API, apartment-grade model. Pricing (as of 2026, verify, `hellodata.ai/pricing`): **$0.50/record** pay-as-you-go, search endpoint free, unlimited fixed-cost tier by quote; UI $250/user/mo. Strong on multifamily, thinner on rural SFR. ToS: per-request, custom-quote for volume.
3. **Rentometer API.** Credit-based; API access bundled with **Pro $29/mo** (billed monthly) which includes QuickView estimates + 50 Pro Reports + 50 comp downloads; higher volume via `sales@rentometer.com` quote (per-credit dollar figure not public — verify). Accuracy is explicitly "ballpark" per third-party review. Good as a cheap manual-VA tool, weak as a bulk API at our scale.
4. **Zumper / Apartments (CoStar).** No self-serve public API; enterprise/data-licensing only, 4–5 figure annual contracts (verify). Out of scope for a free-first engine.

### Feasibility verdict
**CAN hit ~100% coverage** on "a rent estimate on every SFR" — but only in the weak sense. The hard ceiling is **accuracy, not coverage**: free SAFMR answers every zip but at a 40th-percentile voucher number; ZORI is market-rate but geographically incomplete in our rural counties; only a paid AVM (RentCast) gives a market-rate, bed-specific rent on 100% of addresses. So 100% *presence* is free and achievable; 100% *appraisal-grade market rent* requires paid. The other real gate is upstream: rent is only as good as beds/sqft, so filling those (GIS/assessor backfill) lifts rent quality more than any rent vendor swap.

### Recurring cost & cadence at our scale
17,003 leads, ~18 counties, monthly refresh.
- **Free stack (SAFMR + ZORI + HomeHarvest):** $0/mo. SAFMR/ZORI key on ~unique zips (a few hundred across 18 counties), so this is a few hundred cached lookups monthly, not 17k — near-instant, annual/monthly refresh.
- **RentCast, full 17k/mo:** exceeds Scale's 25k bucket only across two months, so **$449/mo Scale** covers a full monthly re-run of all 17,003 (17k < 25k included). If you only enrich the ~13k un-covered SFRs, still one Scale plan = **$449/mo ≈ $5,388/yr**.
- **Cost-minimizing hybrid:** free SAFMR/ZORI on all 17k; spend RentCast **only** on the A/B/C-grade rental candidates that reach an operator — say ~1,500/mo → **Foundation $74/mo** (1,000 incl + ~500 × $0.06 = $30) ≈ **$104/mo ≈ $1,250/yr**.
- **HelloData** at $0.50/record for 1,500 leads = $750/mo — pricier than RentCast for our SFR mix.

### MANUAL PLAYBOOK (per-lead, for the un-automatable / high-value slice)
1. Open the lead; confirm **address, zip, bedroom count** (pull beds from the county GIS/assessor card if blank).
2. Go to **rentometer.com**, log into the Pro account, enter the address + bed count; read the **QuickView** median and the 25th–75th band. Record median as `manual_rent_est`.
3. Cross-check on **Zillow** → search the address → note the **Rent Zestimate** if shown; if the exact property has none, pull 3 active `for_rent` comps in the same zip with the same bed count and take their median.
4. Sanity-floor against **huduser.gov** SAFMR: look up the zip, read the matching-bedroom FMR; if your estimate is *below* SAFMR, use SAFMR (rare) — it's the voucher floor.
5. Take the **middle of the three** (Rentometer, Zillow/comp median, SAFMR floor) as the working rent; write it to `raw.rent_manual`, note the source, and flag "operator-verified."
6. For a live negotiation, pull one screenshot of the 3 Zillow rent comps as leave-behind proof for the owner call.
Never bypass a login wall or CAPTCHA — if a portal blocks, the VA reads only what's on screen and moves to the next source.

### Recommended path
Ship the **free triple-stack now**: (1) add a **HUD SAFMR enricher** (free token, ZIP×bed, annual) as the universal backstop so every zip-keyed SFR gets a floor rent — this alone takes coverage from 3.8% toward ~100% *presence*; (2) join **ZORI** monthly to upgrade SAFMR→market-rate wherever ZORI has the zip; (3) keep **HomeHarvest** as the bed/sqft-granular top layer where listings exist. Store all three plus their source so `calc.py` can prefer market-rate (HomeHarvest > ZORI > SAFMR floor) and flag confidence. Fix the real bottleneck in parallel — backfill **beds/sqft** from GIS/assessor, since rent quality is gated on those. Then add **RentCast Foundation ($74/mo, as of 2026, verify)** targeted *only* at operator-facing A/B/C rental candidates (~1,000–1,500/mo) for a true market-rate AVM where a real offer is being made. Total to get from 3.8% to ~100% coverage with market-grade rent on the deals that matter: **~$74–$104/mo**, everything else free.

---

## Mortgage / Deed-of-Trust / Original Loan Amount — 3.6%

### What it is & why it matters (for motivated-seller acquisition)
This is the **original principal** on the recorded first (and any junior) deed-of-trust/mortgage against each owned property — the number printed as "for the principal sum of $X" on page 1 of the security instrument. It is the single most load-bearing input to **equity**, and equity is what decides whether a lead is a deal. ARV − estimated payoff − liens = equity; without a loan figure the payoff is a guess, so `equity(computed)` currently fires on only **6.9%** of the board. It also drives strategy: a low-balance/near-paid-off DOT (recorded 15+ years ago, small principal) is a **subject-to / gator** candidate; a fresh high-LTV loan is a short-sale or thin-margin wholesale at best. Loan age + amount also proxy for distress (cash-out refis, HELOC stacking). This is the difference between "distressed owner" and "distressed owner *with room to make a deal*."

### Current state in the engine (measured fill-rate, how it's sourced now, the exact code files)
Fill is **3.6%** (`loan/mortgage(ROD)`), from `raw.rod` on ~618 leads. The ROD package `src/foreclosure_scraper/rod/` fetches the **index**, not the dollar: `classify.py` buckets instruments (`_MORTGAGE` regex), counts `mortgage_count`/`satisfaction_count`, and emits `open_mortgages_est = max(0, mtg − sat)` — a *count*, never a *balance*. Vendor adapters `cchs.py`, `aumentum.py`, `cott.py`, `acclaim.py`, `kofile.py` return `RodDoc` rows (grantor/grantee/doc_type/book/page/instrument_no) with **no amount field**, because recorder indexes don't carry it. The only path that yields a dollar figure is OCR of the document image itself: `enrichment_doc_ocr.py` (Gemini-first free vision, `OCR_PROMPT` asks for `amount`) and the offline tool `scripts/extract_lien_amounts.py` (pdfplumber text-layer + `_LOAN_CUES` regex on "principal sum of", falling to Gemini OCR on scans). Both are proven and free but only run where a **document URL** or a locally-dropped PDF exists — which today is a thin slice.

### What reaching 100% actually requires (the data elements + the identity join that must succeed)
Two things per property: (1) the **first-DOT original principal** (grantor=owner, grantee=lender, doc_type=deed of trust/mortgage, book/page, recorded date), and (2) the **junior stack** (2nd DOT, HELOC) minus any recorded **satisfaction/release** so we count only *open* liens. The identity join is `owner_name → recorded instrument → document image → OCR'd principal`, anchored on **parcel_id (88% filled)** or book/page. The hard part is not OCR — it's getting the **document image** for all 18 counties (many recorders only expose the index free and paywall the image) and reliably matching the *open, senior* DOT versus satisfied/refinanced ones.

### FREE routes
- **County ROD deed-of-trust image + OCR (already built).** Method: existing `rod/*` adapters find the DOT instrument by owner name → download the image → `extract_lien_amounts.py`/`enrichment_doc_ocr.py` lift "principal sum of $X". Coverage ceiling: **~40–55%** of owned properties, gated entirely by which counties serve the *image* free. AcclaimWeb counties (Pickens `pickensscrod.us`) serve the index browserlessly and free (`acclaim.py`); Aumentum/CCHS/Cott counties vary. Effort: medium (image-download per county already partly wired). Cadence: monthly on the owned-property slice. Compliance: index reads are on open ASP.NET endpoints (`acclaim.py` docstring confirms no CAPTCHA/token); fine.
- **Free document-image recorders (Aumentum/Cott/CCHS counties).** Where the county's own portal streams the recorded PDF without a paywall, OCR is free. Ceiling: the subset of the 18 counties with free images — realistically **8–11 counties**. Effort: low-medium (extend existing adapters to pull the image, not just the row). Cadence: monthly.
- **Kofile `*.publicsearch.us` = WALLED (do not chase for automation).** `kofile.py` documents it: robots.txt is `Allow: /$` + `Disallow: /`, a machine-readable no-automation directive. The index is viewable but the search/API paths are robots-banned, and **document downloads are paid** ($2–4/doc, per the DC/Kofile fee model — as of 2026, verify). Compliant fallback = human/VA buys the doc (see manual playbook).
- **Deed-stamp back-calc (partial, already present).** `rod/deed_stamp.py` infers sale price from transfer-tax stamps — that gives *last sale price*, not loan principal, but on a purchase-money DOT the loan is often ~70–90% of price, so it's a **proxy** when the image is unavailable. Ceiling as a proxy: adds rough estimates on maybe **+10–15%**, flagged low-confidence.

### PAID routes
- **CoreLogic / Cotality — Involuntary/Open-Lien API.** Provides voluntary + involuntary open liens (mortgage principal, HELOC, tax, judgment); tracks 95% of US voluntary liens. Real pricing (buyer-reported): **$11.50/call Involuntary Lien API, $1.30/call Subject Property Detail** (as of 2026, verify — CoreLogic quotes are custom/enterprise, no public rate card). Coverage: ~99% nationwide. Integration: heavy (enterprise contract, often annual minimum ~$30k+). ToS: licensed data, no redistribution.
- **DataTree by First American.** "Title Chain & Lien" and "Legal & Vesting" reports include open-lien/mortgage detail plus **recorded document images** (the exact DOT image, so you get principal directly). Pricing: not public per-report; average First American D&A spend **~$30,500/yr** (Vendr, as of 2026, verify); pay-as-you-go report credits available via sales. Coverage: ~100% of the housing market. Integration: medium (JSON API). ToS: per-report license.
- **ATTOM — Mortgage/Transactions + AVM API.** Open-lien and mortgage-origination fields (loan amount, lender, date). Pricing: API **starts ~$95–500/month** entry, scaled by monthly transaction volume; enterprise custom; 30-day free trial (as of 2026, verify). Coverage: 158M properties. Integration: light (clean REST). ToS: no bulk redistribution.
- **BatchData — Mortgage Transaction & Open Liens.** 140+ mortgage data points (loan amount, rate, maturity, open-lien flag). Pricing (public rate card): **Growth $1,000/mo = 100k records ($0.01/record); Pro $2,500/mo = 300k; Scale $5,000/mo = 750k (~$0.0066/record)** (as of 2026, verify). Coverage: nationwide recorder+mortgage. Integration: light REST, self-serve. ToS: standard data-license, investor-use permitted.
- **TitlePoint (First American) / Black Knight (ICE).** Title-plant grade; TitlePoint returns the DOT image + lien position; Black Knight is enterprise MLS/servicing scale. Both **enterprise-only, custom-quote** (Black Knight realistically 5-figure annual minimums; TitlePoint per-search via reseller). No public number (as of 2026, verify).

### Feasibility verdict
**CAN reach ~95–98%, CANNOT cleanly hit a true 100% for free.** With a paid open-lien API (BatchData or ATTOM) you get a mortgage-origination amount on ~95%+ of owned properties instantly. The residual gap to 100%: **private/seller-financed DOTs and hand-drafted instruments** where the vendor never ingested a clean loan amount, plus a small share of recorder gaps in rural NC/SC counties. Free-only, the hard ceiling is the **paywalled document image** — Kofile counties and any recorder that charges per-doc cap the free OCR route at roughly **50–60%**, because you cannot see the principal without buying (or hand-pulling) the page. There is no free API that returns loan principal nationwide.

### Recurring cost & cadence at our scale (17k leads, 18 counties, monthly refresh)
We only need this on **owned properties with a resolved parcel** (~88% × the deal-worthy slice, not all 17,003). Practical monthly enrichment target ≈ **8,000–10,000 properties**.
- **BatchData Growth:** $1,000/mo flat covers 100k records — 10k/mo fits 10× over → **$1,000/mo ($12k/yr)**, cheapest turnkey path to ~95%.
- **ATTOM:** entry ~$95–500/mo if volume stays in-tier; likely lands **~$500/mo ($6k/yr)** at 10k lookups (verify tier).
- **CoreLogic per-call:** 10k × $11.50 = **$115k/mo** — absurd at our scale; only viable for the handful of HOT leads (e.g. 300 HOT × $11.50 = ~$3,450/mo).
- **DataTree/TitlePoint credits:** ~$1–3/report × the slice you actually need images for.
- **Free OCR:** ~$0 (Gemini free tier + CPU), covers the counties with free images each monthly refresh.

### MANUAL PLAYBOOK (VA / human operator, for the un-automatable paywalled slice)
1. Open the target lead in the dashboard; copy **owner_name**, **parcel_id**, **county**, and any **book/page** from `raw.rod`.
2. Go to that county's Register-of-Deeds public search (Kofile `<county>.<st>.publicsearch.us`, AcclaimWeb, or the county recorder site).
3. Search by **grantor = owner_name** (or by book/page if known). Filter doc type to **Deed of Trust / Mortgage**; sort by recorded date **newest first**.
4. Identify the **senior open DOT**: the most recent purchase-money or refi DOT that has **no matching Satisfaction/Release** recorded after it. Note junior DOTs/HELOCs the same way.
5. If the image is free, open it. If paywalled (Kofile ~$2–4/doc), purchase the single document — do **not** bypass the paywall.
6. On **page 1**, read the clause "…in the principal sum of $______" (or "original principal amount of"). Record that number, the lender (grantee), the recorded date, and book/page.
7. Repeat for any junior DOT; sum open liens.
8. Enter into the lead's `raw.rod.manual` as `{first_dot_amount, junior_dot_amount, lender, recorded_date, book_page, source:"manual"}`; the offline parser (`extract_lien_amounts.py`) will also accept the saved PDF dropped in a folder if they'd rather batch-OCR.
9. Log a screenshot/PDF for the paper trail.

### Recommended path (closest to 100% for the least money)
1. **Keep and widen the free OCR route first** — extend the Aumentum/Cott/CCHS adapters to pull the *document image* wherever the recorder serves it free, then run the existing `extract_lien_amounts.py`/`enrichment_doc_ocr.py` pipeline. Gets the free-image counties to ~50–60% at ~$0.
2. **Add BatchData Growth ($1,000/mo) as the automated backbone** for open-lien/mortgage principal on the parcel-resolved owned slice — one API, self-serve, investor-friendly ToS, lands ~95% for a flat $12k/yr. (ATTOM at ~$6k/yr is the cheaper alternative if 10k/mo lookups stay in an entry tier — verify the quote.)
3. **Reserve CoreLogic per-call ($11.50 Involuntary Lien) for HOT leads only** (~300/mo ≈ $3.5k) where an authoritative, current open-lien read materially changes a live offer.
4. **Route the paywalled-image residual (Kofile counties, private DOTs) to the manual VA playbook** — a few dollars per doc, only on deal-worthy leads.
This mix realistically hits **~95–98%** for ~$12–16k/yr, with the last 2–5% (private/seller-financed paper) accepted as the permanent hard ceiling.

Sources: [ATTOM/Datarade](https://datarade.ai/data-providers/attom/profile), [ATTOM Property Data API](https://www.attomdata.com/solutions/property-data-api/), [CoreLogic PriceLevel](https://www.pricelevel.com/vendors/corelogic/pricing), [BatchData pricing](https://batchdata.io/pricing), [BatchData mortgage/liens](https://batchdata.io/mortgage-transactions-data), [DataTree by First American](https://www.firstam.com/mortgagesolutions/solutions/data-analytics/datatree.html), [First American D&A pricing (Vendr)](https://www.vendr.com/buyer-guides/first-american-data-analytics), [DC Recorder / Kofile fees](https://washington.dc.publicsearch.us/).

---

## Live Payoff, Current Lien Balance & the FULL Lien Stack (equity — 6.9%)

### What it is & why it matters (for motivated-seller acquisition)
Equity is the deal. Every acquisition model — wholesale, subject-to, fix-flip, gator, land — lives or dies on one number: `ARV − current mortgage payoff − every junior lien`. A pre-foreclosure with $120k of real equity is a motivated seller you can buy well below market; the identical house that is underwater is a short-sale grind or a dead lead. Getting equity wrong in either direction is expensive: overstate it and you waste marketing dollars and make offers that can't close; understate it and you skip your best deals. The full lien stack matters specifically because a junior lien the seller forgot to mention (an IRS Notice of Federal Tax Lien, a state income-tax lien, an HOA judgment, a mechanic's lien, a second mortgage) either eats the equity or, at a junior foreclosure sale, survives and wipes out a buyer who thought they were taking clean title. This is why the engine already computes `title_risk` alongside equity.

### Current state in the engine (measured fill-rate, sourcing, exact files)
Equity is computed on **6.9%** of leads (`raw.equity`, ~1,166 rows); `title_risk` classifies **378**. The pipeline is entirely free, pure-compute, no vendor:
- `src/foreclosure_scraper/enrichment_equity.py` — the payoff waterfall: (1) most-recent recorded **Deed of Trust amount + date → amortized current balance** (HIGH conf), (2) `amount_owed`/foreclosure judgment or `opening_bid` as a debt proxy, (3) last arms-length sale price × 0.90 LTV, amortized (LOW), else unknown. Equity = `arv − payoff − senior_liens`.
- `src/foreclosure_scraper/valuation/amortize.py` — amortizes original principal on a 30-yr fixed using Freddie Mac PMMS annual-average rates keyed to the note year.
- `src/foreclosure_scraper/rod/priority.py` + `rod/enrich.py` — build the lien stack from ROD docs (name-searched via CCHS/Aumentum/Cott/Kofile vendors), net out satisfactions, apply NC/SC super-priority (property tax always; NC HOA limited), and emit `lien_priority.total_senior_amount`.
- `enrichment_lien_stack.py` — joins SCDOR state-tax-lien rows to owners by county + 3-token name match (super-priority).
- `enrichment_title_risk.py` — classifies the foreclosing party senior vs junior (bank/servicer vs HOA/CU/municipal/individual).
- `scripts/extract_lien_amounts.py` — OCRs free recorded-PDF images to pull the loan/lien dollar the ROD index omits.

**Why it's stuck at 6.9%:** the payoff estimate needs a recorded DoT *amount* (ROD index rarely carries $ — 3.6% loan fill) or a clean last-sale price+date, AND a valid ARV. Both must land on the same lead. The lien-stack join needs a name match to a lien registry we actually scraped.

### What reaching 100% actually requires
Two things per property: **(a) the current unpaid principal balance (UPB)** of the senior mortgage, and **(b) a complete recorded-encumbrance search** (2nd mortgages, IRS §6323 NFTLs, state tax liens, HOA/COA assessments, abstracts of judgment, mechanic's/materialman's liens, UCC fixture filings). Then a reliable **identity join** — parcel_id or normalized owner-name+county — must connect each lien to the subject property without false positives.

### FREE routes
- **County ROD lien indices (grantor/grantee search).** Source: each county Register of Deeds. Method: the vendor searches already wired (`rod/enrich.py`). Coverage ceiling: index tells you a lien *exists* and its book/page across most of the 18 counties, but the **dollar amount is not in the index** — so this alone can't complete UPB. Effort: already built. Cadence: monthly. Compliant (public index).
- **Free recorded-document PDF images + OCR.** Source: county ROD image viewers (free per the memory note). Method: `extract_lien_amounts.py` pulls "principal sum of $X" from the deed of trust and lien PDFs. Ceiling: recovers the **original** loan amount (not payoff) on maybe 30–50% of properties where images are bulk-downloadable and CAPTCHA-free; the rest are viewer-gated → operator downloads by hand. Cadence: monthly. Compliant.
- **State/federal lien registries.** SCDOR delinquent-taxpayer + DEW lien registry (built), NC has no equivalent centralized registry; IRS NFTLs are recorded at the county ROD (captured in the index sweep). Ceiling: super-priority liens ~good in SC, patchy in NC. Free.
- **Amortization estimate.** The current fallback. Ceiling: an *estimate* of UPB, never the exact figure — good enough to grade a deal, not to close one.

**Free hard ceiling: ~30–45% of leads get a defensible *estimated* payoff + a lien-index list. Zero get an exact live payoff.**

### PAID routes (real 2026 pricing — verify each)
- **Local title company / national O&E ("current-owner search").** Provides: vesting deed, all open mortgages taken by the current owner, judgments and liens against owner+property. **ProTitleUSA residential O&E ≈ $90 avg, range $55.95–$275; ~$87.95–$95.95 in metro examples; commercial ≈ $250; bulk discount + pass/fail dashboard on 20+ orders** ([ProTitleUSA](https://protitleusa.com/services/products/oe_report), [PropertyOnion](https://propertyonion.com/education/full-30-year-title-search-vs-o-e-report-whats-the-difference/) as of 2026, verify). U.S. Title Records: ownership $29 / lien check $95 / full preliminary report $375 ([ustitlerecords.com](https://www.ustitlerecords.com/title-search-cost/), verify). Coverage: ~100% where a searcher covers the county. Integration: manual order or API/bulk upload; a human reads the PDF. ToS: legitimate use, fine.
- **First American DataTree.** Provides: recorded documents, deeds, mortgages, O&E reports, doc images. Pricing: **per-user + per-document, quoted; not public** ([DataTree](https://www.firstam.com/mortgagesolutions/solutions/data-analytics/datatree.html), [Datarade](https://datarade.ai/data-providers/datatree-by-first-american/profile), verify). Effort: enterprise contract. ToS: licensed data, no redistribution.
- **ATTOM (ownership + open-lien / AVM + mortgage-history).** Provides: current owner, mortgage-origination history, open-lien indicator, AVM. Pricing: **not per-record publicly; API reported to start ~$500/mo; Property Navigator Pro $499/yr; bulk = custom quote** ([Dwellsy IQ ATTOM 2026](https://blog.iq.dwellsy.com/attom-data-overview-2026-property-ownership-and-market-data-explained/), [ATTOM pricing](https://www.attomdata.com/solutions/property-navigator/pricing/), verify). Note: ATTOM gives *origination* balances + estimated open liens, **not live payoff**. ToS: licensed, no scraping/resale.
- **TitlePoint (First American).** Automated county title/lien search plant. Pricing: **not published; per-search quoted; industry title searches $100–$250 residential** ([TitlePoint](https://www.titlepoint.com/titlepoint/About.aspx), [ustitlerecords](https://www.ustitlerecords.com/title-search-cost/), verify). Enterprise.

**No paid product sells a live payoff.** They sell *recorded* debt (original amounts + open/satisfied status) and estimates. The exact current balance is not a product anyone can license.

### Feasibility verdict — CANNOT hit 100%
The exact live payoff is **servicer-only PII**. Under **15 U.S.C. §1639g (TILA) and RESPA/Reg X**, a payoff statement is released only to the **borrower or a borrower-authorized third party** (title co, attorney, new lender) within 7 business days ([Cornell LII](https://www.law.cornell.edu/uscode/text/15/1639g), [Nolo](https://www.nolo.com/legal-encyclopedia/what-happens-mortgage-servicer-doesnt-send-me-the-payoff-statement-i-requested.html), verify). No vendor, free or paid, can supply it at scale without the seller's signed authorization — which you only obtain **after** a lead answers you. So the ceiling for the *automated* engine is: **estimated UPB (amortized recorded loan) + a complete recorded-lien list from an O&E.** The exact number is obtainable per-deal only, by hand, once a seller engages. That is the hard wall, and it is legal, not technical.

### Recurring cost & cadence at our scale
Ordering an O&E on all 17,003 leads monthly is nonsensical ($90 × 17,003 ≈ **$1.53M/mo**) and wasteful — most leads never reach negotiation. Tier it. **Free amortization + ROD index runs on the whole board at $0.** Buy O&E only on qualified, contacted, equity-positive leads. Realistic funnel: ~150–300 O&E/mo × ~$85 (bulk residential) = **~$12,750–$25,500/mo**, and in practice far less if you order only when a seller responds (~$85 per live negotiation). One ATTOM API seat (~$500/mo, verify) can pre-screen the whole board with origination-history + open-lien flags to *rank* which leads deserve a paid O&E, cutting wasted orders. Blended realistic monthly: **~$500 (ATTOM screen) + $2,000–$8,000 (O&E on the negotiating slice) ≈ $2.5k–$8.5k/mo.**

### MANUAL PLAYBOOK (per un-automatable property, VA/operator)
1. Open the county **Register of Deeds** grantor/grantee index; search the exact owner name (from `raw.gis.owner`).
2. Record every open instrument: Deed of Trust/mortgage (note grantee=lender, book/page, date), plus any lien, judgment, NFTL, HOA claim, UCC.
3. For each open DoT, open the **free recorded PDF image**; read "principal sum of $___" → that is the **original** balance and date.
4. Run each original amount + date through `amortize.py` (or the standard formula) to get **estimated UPB**.
5. Search the county for **IRS NFTL** and, in SC, cross-check **SCDOR** and **DEW** registries by name; add any hits to the stack.
6. Sum stack: senior mortgage UPB + super-priority (tax) + junior liens. Compute `ARV − stack = estimated equity`.
7. If the lead is worth pursuing, order a **current-owner O&E** ([ProTitleUSA](https://protitleusa.com/services/products/oe_report)/local title co, ~$85) to confirm the recorded stack authoritatively.
8. **For the exact live payoff:** only once the seller engages — have them sign a **third-party authorization**, then you (or your title co) request the payoff statement from the servicer; it arrives within 7 business days.

### Recommended path (closest to 100% for least money)
1. **Keep the free engine as the default screen** (amortized recorded-loan UPB + ROD index + registry joins) — costs $0, grades every lead.
2. **Add one ATTOM API seat (~$500/mo, verify)** to backfill mortgage-origination history + open-lien flags across the whole 17k board — this alone lifts the *estimated*-equity fill dramatically and ranks which leads merit a paid pull.
3. **Order a per-property O&E (~$85 bulk, ProTitleUSA/local title co) only on contacted, equity-positive leads** to lock the authoritative recorded lien stack.
4. **Get the exact live payoff per-deal via seller-signed servicer authorization** — the only lawful path, done at negotiation, never at scale.

This gets ~90%+ *estimated*-equity coverage and 100% *recorded*-stack accuracy on the deals that matter, while accepting that exact live payoff is structurally a per-deal, seller-gated number that no amount of money buys in bulk.

---

## Court / Legal Foreclosure Status & Timeline

### What it is & why it matters (for motivated-seller acquisition)
This is the single most time-sensitive signal in the whole engine. A recorded **lis pendens** (SC) or a filed **Special Proceeding / notice of hearing** (NC) is the *earliest* public marker that an owner is losing the house — months before the auction, while the owner still has equity and a reason to sell fast. The full timeline (filing -> judgment -> notice of sale -> `sale_date` -> upset-bid window -> confirmation) tells you exactly *when* to strike and *what* the deal looks like: a lead 90 days pre-sale is a subject-to/short-sale conversation; a lead inside NC's 10-day upset-bid window (NCGS §45-21.27) or SC's post-sale confirmation gap is a redemption/assignment play. **Case parties** (defendant = distressed owner, plaintiff = lender, substitute trustee = who runs the sale) are the identity spine that lets us skip-trace the right human. Without sale_date and stage, every foreclosure lead is undated and un-prioritizable.

### Current state in the engine (measured fill-rate, how it's sourced now, the exact code files)
Measured: **sale_date 1.7%, case# 18.2%, judgment_amount 1.1%, opening_bid 4.3%**, life-events 1.2%. The court stack is already large and mostly free:
- `enrichment_courts.py` — NC batch match against Tyler's public **NCJudgmentSearchService JSON** (no CAPTCHA, serves lis-pendens + divorce), plus a legal-gated per-case SC Public Index render, both circuit-breaker-protected.
- `enrichment_nc_case_status.py` / `_tyler.py` — timeline/stage inference: authenticated-Tyler docket path when creds set, else a pure-compute **sale_date heuristic** (scheduled -> upset_bid -> pending_confirmation -> confirmed) cross-referenced to recorded Trustee's Deeds.
- `enrichment_court_bid.py` — per-case SC Public Index render (Rule-610-compliant single-case lookup, no bulk crawl) for opening_bid/upset status; NC explicitly reported **not-viable** (Tyler JSON has no amount field, SP file is login-walled).
- `ingest_sc_publicindex_export.py` + `parse_nc_ecourts_export.py` + `scripts/ingest_publicindex_files.py` — the **offline operator lane**: a human saves the WAF-walled result page, the engine parses it with zero network calls.
- `scrapers/national/courtlistener_*` (free CourtListener/PACER mirror), 13 substitute-trustee `law_firms/*` scrapers, 11 `newspapers/*` legal-notice parsers, statewide `public_notices/*`. Runner: `scripts/run_daily_court.sh`. FOIA templates: `docs/foia_court_records.md`.

The low fill-rates are **not** a code failure — they are the two state walls: SC Public Index is scrape-prohibited, NC's rich SP file is login-gated. Free coverage is capped by what the *un-walled* surfaces expose.

### What reaching 100% actually requires (data elements + identity join)
Elements: `case_number`, `filing_date`, `plaintiff`, `defendant`, `substitute_trustee`, `sale_date`, `sale_location`, `opening_bid`/`judgment_amount`, `upset_bid_deadline`, `stage`. The **join** that must succeed: *case -> property*. Court records are **name-indexed** (defendant), not property-indexed; SC embeds the county in the case number (§15-11-10) but rarely the address, NC SP filings omit it too. So 100% requires (a) getting every filing, and (b) resolving defendant-name+county -> parcel/address via the existing name->property resolver. Element completeness is bounded by portal access; the join is bounded by name-match quality.

### FREE routes
- **Substitute-trustee / law-firm sale calendars** (`law_firms/*`): source = 13 firm sites (Hutchens, Brock & Scott, Shapiro & Ingle, Aldridge Pite, etc.) that publish NC/SC sale rosters with owner, address, sale_date, opening_bid. **Coverage-ceiling ~55-70% of NC power-of-sale sales** (these firms run the majority). Effort: low (built). Cadence: weekly. Compliant — public marketing pages. **This is the highest-yield free sale_date source and should be pushed hardest.**
- **NC Tyler Judgment-Search JSON** (built): open API, no CAPTCHA, serves lis-pendens + divorce parties/filing_date. Ceiling ~80% of NC *judgment/LP* cases; **0% of the SP foreclosure amount/sale fields**. Cadence: daily. Compliant (public endpoint).
- **Newspaper + statewide legal-notice portals** (`newspapers/*`, `publicnoticesc.py`, `ncpublicnotices.py`): Notices of Sale carry sale_date + trustee + address. Ceiling ~40-60% of noticed sales (papers vary by county). Weekly. Compliant.
- **CourtListener/RECAP (free PACER mirror)**: federal civil real-property + bankruptcy only — **<3% of our footprint** (foreclosure is state court). Free API; default rate lowered from 5,000/hr in May 2026, EDU tier free *(as of 2026, verify)*. Compliant.
- **Operator manual export -> offline parse** (`ingest_*_export.py`): the compliant route into SC Public Index (Rule-610 scrape-ban) and NC eCourts Smart Search (AWS-WAF). Ceiling ~95% of *targeted* cases the human pulls; bounded by human hours. Weekly. Compliant by construction — engine makes no request.
- **FOIA to Clerk / Master-in-Equity** (`docs/foia_court_records.md`): the ONLY free route to NC/SC **judgment $ amounts** and non-online counties. Ceiling ~90% of requested records; 7-30 day turnaround. Compliant.

### PAID routes
- **ATTOM Data pre-foreclosure/foreclosure API** — NOD, Lis Pendens, Notice of Trustee's Sale, Notice of Foreclosure Sale; 27M+ default records, 3,002 counties, daily. Pricing: API **starts ~$95/mo**, real feeds are custom yearly licenses; Property Navigator seat **$499/yr** *(as of 2026, verify)*. Coverage of our 18 counties: high for LP/NOD/sale, but ATTOM is a public-record aggregator — it inherits the same SC/NC gaps and often *lags* the firm calendars by days. Integration: low (clean REST). ToS: licensed redistribution OK.
- **BatchData / BatchLeads pre-foreclosure API** — full LP->NTS->auction lifecycle, 20+ fields; skip-trace $0.10-$0.15/record; core plan pricing gated, free trial *(as of 2026, verify)*. Coverage similar to ATTOM. Low integration. ToS OK.
- **PropStream** — pre-foreclosure lead lists: Essentials **$99/mo**, Pro **$199/mo**, Elite **$699/mo**; skip-trace $0.10-$0.15/rec, list-automation +$27/mo *(as of 2026, verify)*. UI-first, thin API. Best as a VA cross-check tool, not a pipeline feed.
- **PACER (federal)** — **$0.10/page**, capped **$3/document**, waived if <$30/quarter *(as of 2026, verify)*; **temporary fee increase effective Jan 1, 2027**. Only relevant for federal cases (<3% here). Free via CourtListener anyway.
- **SC Office of Court Administration Rule-610 bulk license** — the *only* lawful bulk SC path: apply to OCA; granted only for scholarly/governmental/journalistic purpose where individual identity is ancillary. **Commercial purpose is expressly barred** — our use does not qualify. Effectively $0-but-denied.

### Feasibility verdict
**CANNOT hit 100% by automation.** The hard ceiling is **legal, not technical**: SC Rule 610 flatly prohibits automated scraping *and* commercial bulk distribution of the Public Index, and NC's SP foreclosure file (with the report-of-sale bid) sits behind AWS-WAF + Tyler login. Even paid aggregators (ATTOM/BatchData) can't sell what those courts don't expose in bulk, and OCA won't license a commercial buyer. The realistic automated ceiling for a *dated, priced, party-complete* foreclosure record across all 18 counties is **~65-75%** (firm calendars + newspapers + Tyler JSON + FOIA judgment $). The last ~25-35% — every case the firms didn't run and the papers didn't print — is reachable **only** through the human-gather/offline-parse lane, which caps at operator hours, not code.

### Recurring cost & cadence at our scale (17k leads, 18 counties, monthly refresh)
The foreclosure-active slice is only the LIS_PENDENS/FORECLOSURE_SALE rows (low hundreds), not all 17k. **Free path stays $0** — firm/newspaper/Tyler scrapers already run monthly (some daily), FOIA is postage/free. **VA manual-gather lane**: ~2 min per (county x lane) search+save; a full 18-county x 3-lane pass = ~54 searches ≈ **90 min/week ≈ 6 hrs/mo** ≈ **$90-150/mo** at $15-25/hr VA. **If paid feed added**: ATTOM API ~**$95-300/mo** blended, or BatchData at ~$0.12/pre-foreclosure record x ~300 active foreclosure leads/mo ≈ **~$36/mo** plus base — the cheapest incremental lift for LP/sale_date. Skip-trace on the newly-dated leads is a separate $0.10-0.15/record line already in the phone section.

### MANUAL PLAYBOOK (VA / operator, click-by-click)
**NC eCourts (portal-nc.tylertech.cloud):**
1. Open the portal in a normal browser; solve the one-time WAF check if shown.
2. Click **Smart Search**. Set **Location = [county]** (e.g. Buncombe).
3. Set **Case Category = Special Proceeding**, **Case Type = Foreclosure**; set a **date range** = last save date -> today.
4. Click **Search**. Let the grid fully load.
5. **File ▸ Save Page As ▸ "Web Page, HTML Only."** Name it `nc_[county]_foreclosure_[date].html`.
6. Repeat step 2-5 for the **Estate** and **Divorce** lanes (secondary triggers).

**SC PublicIndex (publicindex.sccourts.org):**
7. Pick **County**, click **Accept** on the disclaimer.
8. **Court Agency = Common Pleas**; **Case SubType = Foreclosure (420)**. (For sale/judgment $, repeat with **Master In Equity**; for earliest signal use the **Index Search ▸ Lis Pendens** radio.)
9. Set **Date Type = Case Filed**, **Beginning = last-pull date** (first pull: 6 months back), **Ending = today**; leave Last Name blank.
10. Click **Search**. If it overflows the row cap, narrow the date window to ~1 week and walk backward.
11. **Ctrl-S / Save Page As ▸ HTML Only.** Name it `sc_[county]_[lane]_[date].html`.
12. Drop every saved `.html` into `~/foreclosure-scraper/`; the engine batch-parses all of them (no network) into dated, party-tagged leads.
**FOIA fallback (judgment $ / offline counties):** send the county-specific template from `docs/foia_court_records.md` to the Clerk / Master-in-Equity, request **electronic CSV/Excel**, drop the returned file in the repo.

### Recommended path
Free-first, human-topped. **(1)** Lean hardest on the already-built **substitute-trustee firm calendars + newspaper notices + Tyler JSON** — the best free sale_date/party spine, $0. **(2)** Run the **weekly VA manual-gather** on the 3 biggest counties (Buncombe, Gaston, Spartanburg) x 3 lanes, expanding to all 18 monthly — **~$90-150/mo**, closes most of the automated gap legally. **(3)** Fire **FOIA quarterly** for judgment $ amounts (free, the one route to the 1.1% judgment field). **(4)** Only if the dated-lead volume justifies it, add **BatchData's per-record pre-foreclosure API (~$0.12/rec, ~$40/mo at our volume)** as an ATTOM-style cross-check to catch cases the firms miss — do **not** buy a full ATTOM enterprise license for 18 counties; the marginal LP coverage isn't worth $95-300/mo when the firm calendars already carry the majority. Net: ~**$130-190/mo all-in** gets to ~70-75%; the final 25-35% is a legal wall, reachable only through more operator hours, not more spend.

**Files:** `/Users/cashhigh/foreclosure-scraper/src/foreclosure_scraper/enrichment_courts.py`, `enrichment_nc_case_status.py`, `enrichment_nc_case_status_tyler.py`, `enrichment_court_bid.py`, `court_detail_parser.py`, `ingest_sc_publicindex_export.py`; `scripts/parse_nc_ecourts_export.py`, `ingest_publicindex_files.py`, `patch_court_detail.py`, `run_daily_court.sh`; `scrapers/law_firms/*`, `scrapers/newspapers/*`, `scrapers/public_notices/*`, `scrapers/national/courtlistener_*`; `docs/foia_court_records.md`.

---

## Property Condition & Rehab Signal — Path to 100%

### What it is & why it matters (for motivated-seller acquisition)
Condition is the deal. Every downstream number — ARV, rehab budget, max allowable offer, wholesale vs subject-to vs gator vs tear-down routing — hinges on whether the house is move-in, cosmetic, major, or gut. A "Poor/Unsound" appraiser rating or a boarded-window photo is also itself a *motivation* signal: an owner who can't afford to fix a failing structure is a seller. Condition converts a raw address into a bid. Without it we grade a house blind, and a blind grade is why 41% of the board (7,322 D + 145 F + 4,042 none) sits ungraded or bottom-tier. The prize is a defensible per-property rehab-per-square-foot number the acquisitions team can act on same-day.

### Current state in the engine (measured fill-rate, how it's sourced now, exact code files)
Two lanes, both thin:
- **CAMA condition/grade — 14.2% fill**, from `src/foreclosure_scraper/enrichment_cama_condition.py`. Pure free batched ArcGIS `PIN IN (...)` joins. Only **4 counties expose a bulk condition/grade column** (Buncombe, Carteret, Onslow year-only, York SC year-only). Every SC county gates condition behind per-parcel qPublic cards (`enrichment_assessor_card`, ~30s–3min/parcel render, capped at a few hundred). `spartanburg_condemned.py` mines `ConditionFactor IN ('DL','VP')` off the CAMA_Parcels FeatureServer → 681 dilapidated + ~1,842 very-poor parcels flagged `raw['condemned']`/`raw['distressed']`.
- **Vision LLM scoring — 0% on the board** (images exist on 21.1% but Vision hasn't been run to fill `raw['condition_tier']` at scale). `enrichment_vision.py` is a mature multi-backend pool (Gemini rotating keys → GitHub Models → Groq → OpenRouter → Mistral → Cloudflare → 13 NVIDIA NIM lanes → local Ollama floor) that scores photos into `move_in_ready/cosmetic/major/gut` + rehab $/sqft. Images come from `enrichment_images.py`: real listing photos, **Esri World Imagery aerial (free, no key)**, **Mapillary street-level (free)**, OSM fallback.
- **Storm damage** — `enrichment_helene_damage.py` stamps `raw['storm_damage']` from 4 Helene ArcGIS layers (Spartanburg, Henderson, Buncombe). **Code enforcement — effectively 0**; `enrichment_code_enforcement.py` has only Asheville Accela wired and no confirmed second in-footprint feed.

### What reaching 100% actually requires
For all 17,003 leads: (1) an **exterior look** — a photo/aerial/street view of the actual structure, OR an authoritative structured rating (assessor CDU, condemned list, damage assessment); (2) that look **joined to the right parcel** — the identity join that must succeed is `parcel_id` (88% filled) or a rooftop-precise `lat/lng` (only 21.8%). The join is the ceiling: no coordinate = no imagery = no vision. Images currently attach to 21.1%; that gap is a *geocode* problem, not a condition problem.

### FREE routes
- **County CAMA condition/grade (bulk ArcGIS).** Method: `PIN IN (...)` FeatureServer query per county. Coverage ceiling: **~30–40%** of the board — capped because only 4 of 18 counties publish a bulk condition column and SC publishes none. Effort: low (schema mapping per county). Cadence: monthly. Compliant: open REST, no auth.
- **qPublic assessor CARD condition (SC counties).** Per-parcel render (`enrichment_assessor_card`). Ceiling: could reach **~SC 50%** but slow (~30s–3min each) so realistically caps a few thousand/run. Cadence: monthly, prioritized. Compliant, but ToS-gray on volume — throttle, treat CAPTCHA as the human-gather wall (never bypass).
- **Condemned / code-enforcement GIS.** Spartanburg CDU (built); Asheville Accela (built). Ceiling: **low single-digit %** — only a handful of in-footprint cities expose a feed. Cadence: monthly. Compliant.
- **Mapillary street imagery (free API).** Coverage is the killer: crowdsourced, **urban ~8.9% vs rural ~2.7%** road coverage ([arxiv 2409.15386](https://arxiv.org/html/2409.15386v1)); most of our rural WNC/Upstate footprint has no pass. Ceiling for *usable street view*: **~15–25%**. Free. Compliant.
- **Esri World Imagery aerial (free, no key).** Already wired; attaches to any precise point. Aerial shows roof/lot/footprint but **not façade** — good for gut/tear-down and overgrowth, weak on cosmetic. Ceiling: rides the 21.8% geocode fill (raise geocoding and this rises with it).
- **FEMA remotely-sensed building-level damage assessments** ([gis.fema.gov FeatureServer](https://gis.fema.gov/arcgis/rest/services/FEMA/FEMA_Damage_Assessments/FeatureServer/1), open JSON/geoJSON). Post-disaster only; ceiling tiny outside declared events but free and net-new alongside our Helene layers.
- **Free vision-LLM scoring of whatever imagery we have.** This is the multiplier: run `enrichment_vision.py` at full scale over the 21.1% with images → lifts board `condition_tier` from 0% toward ~21%. $0 on the free pool. Compliant.

### PAID routes
- **Google Street View Static API** — a real façade photo for nearly every addressed US property. **2026 SKU (verify): free 10,000 events/mo, then $7.00/1k (10k–100k), $5.60/1k (100k–500k)** ([Google pricing](https://developers.google.com/maps/billing-and-pricing/pricing)). Coverage: **~90%+ of addressed leads** (StreetView drives even rural roads Mapillary misses). Integration: low — swap into `_select_image_urls` as a street source; feed straight to existing Vision pool. ToS note: the Static image may be **cached/stored per Google Maps Platform terms** for your processing; do not build a permanent public photo archive — treat as transient input to Vision.
- **Cape Analytics** — AI roof/condition from aerial, 5-point roof rating + Automated Property Condition Report across 120M+ US homes via API ([capeanalytics.com](https://capeanalytics.com/real-estate-property-intelligence/)). Pricing: **enterprise/quote-only, not public (verify)** — insurance-underwriting contracts, typically annual minimums in the tens of thousands; not a per-record self-serve buy. Coverage ~95% SFR. Integration: medium. ToS: insurance/underwriting-oriented licensing — confirm real-estate-investor use is permitted.
- **ZestyAI (Z-PROPERTY)** — parcel/structure roof condition, vegetation, debris via API ([zesty.ai](https://zesty.ai/products/property-insights)). Pricing: **enterprise/quote-only (verify)**; insurer-focused. Same licensing caveat as Cape.
- **EagleView** — per-report roof/condition. **~$15–$38 standard, up to ~$87 premium per report (verify)** ([roofingsoftwareguide](https://roofingsoftwareguide.com/guides/eagleview-pricing/)); **no public API** — the newer EagleView One is quote-only subscription. Too costly per-unit at 17k scale.
- **Nearmap** — high-res aerial (up to ~1.5–3in/px, 3x/yr) + AI attributes via API ([nearmap.com](https://www.nearmap.com/products)). Pricing: **quote-only annual subscription (verify)**, typically low-five-figures minimum. Better as an imagery *source* for our own free Vision than as a condition vendor.
- **Paid vision LLM (Claude Sonnet)** — fallback scorer, **~$0.01–0.03/listing** (in-code estimate, `enrichment_vision.py`). At 17k = **~$170–510/full pass**; unnecessary while the free pool holds.

### Feasibility verdict
**CANNOT hit a true 100% for free; CAN hit ~95% with one paid imagery buy.** The hard ceiling on the *free* side is geographic: bulk CAMA condition exists in only 4/18 counties and Mapillary skips rural roads, so free structured+street condition tops out near **35–45%** of the board. The single lever that breaks the ceiling is **Google Street View Static + our existing free Vision pool** — a façade for ~90%+ of addressed leads, scored at $0. The residual ~5–10% that stays unreachable are leads with **no usable address/parcel** (the geocode-fill wall) and interior-only condition (no exterior source ever reveals a gutted interior) — that slice is human-gather only.

### Recurring cost & cadence at our scale (17k leads, 18 counties, monthly refresh)
Free CAMA + condemned + Helene + Esri aerial + Mapillary + free Vision pool = **$0/mo**. Add Google Street View Static for the ~90% addressed slice ≈ **~15,000 image pulls/mo**. First 10,000 free, remaining ~5,000 at $7.00/1k = **~$35/mo** (verify). Even pulling a fresh façade for *all* 17k monthly ≈ **~$49/mo** (7k billable × $7). Vision scoring of those stays $0 on the free backend pool. So the entire path-to-95% recurring cost is **≈$35–50/month**, no enterprise contract. Cape/Zesty/Nearmap/EagleView are all quote-only enterprise deals that don't pencil at this scale — skip them.

### MANUAL PLAYBOOK (for the un-automatable slice: interior condition + un-geocoded leads)
1. Open the lead in the dashboard; copy `street_address` + `city` + `state` (or `owner_name`/`parcel_id` if address is blank).
2. In Google Maps, paste the address → drop **Street View pegman** on the front of the parcel. If no blue coverage, note "no street view."
3. Score the façade against the rubric in `enrichment_vision.py`'s SYSTEM_PROMPT: move_in_ready ($5–20/sqft), cosmetic ($15–45), major ($35–80), gut ($110–220). Record roof, siding, windows (boarded?), yard (overgrown/debris), structural lean.
4. Switch to **satellite + 45° aerial** for roof tarps, missing shingles, blue-tarp, debris piles, and lot overgrowth the street view can't show.
5. For a blank address, resolve the parcel first: county GIS parcel viewer → search `parcel_id` → read situs → repeat steps 2–4.
6. Check the county's online **assessor card** for the CDU/condition line and year-built when photos are ambiguous.
7. Search `"[address]" + city` on Zillow/Realtor/Redfin for any **interior listing photos** (the only exterior-blind route to kitchen/bath/floor condition).
8. Enter tier, confidence, rehab $/sqft, and red flags into the lead's condition fields; flag "interior unknown" where no interior photo exists.
9. Never solve a CAPTCHA or bypass a login/paywall — if a portal walls the page, stop and log it as "operator wall," don't evade.

### Recommended path (closest to 100% for least money)
1. **Fix geocoding first** — every 1% of geocode fill is 1% more of *both* free aerial and paid Street View. This is the highest-leverage free move and unlocks everything below.
2. **Run the free Vision pool at full board scale now** — lifts `condition_tier` from 0% to ~21% at $0 immediately, no new spend.
3. **Keep all free structured lanes** — CAMA bulk (4 counties), qPublic cards (SC, throttled), Spartanburg condemned, Asheville code-enf, Helene + FEMA damage layers. Together ~35–45%.
4. **Add Google Street View Static (~$35–50/mo)** as a street source feeding the existing free Vision pool → pushes façade-scored condition to **~90% of addressed leads**. This is the only paid buy worth making.
5. **Skip Cape/Zesty/Nearmap/EagleView** — enterprise quote-only, priced for insurers, no per-record tier that fits a $35/mo budget.
6. **Human playbook** closes the interior-condition and un-geocoded residual (~5–10%). Net: **~$35–50/month for ~90–95% condition coverage.**

Key files: `src/foreclosure_scraper/enrichment_cama_condition.py`, `enrichment_vision.py`, `enrichment_images.py`, `enrichment_helene_damage.py`, `enrichment_code_enforcement.py`, `scrapers/counties_sc/spartanburg_condemned.py`.

---

## Distress / Life-Event Sources (Probate, Divorce, Bankruptcy, Incarceration, Death, Vacancy, Eviction, Code)

### What it is & why it matters (for motivated-seller acquisition)
A life event is the *reason* an owner becomes a seller. Foreclosure and tax delinquency tell you a property is in trouble; a death, divorce, bankruptcy, or incarceration tells you the *person* is in trouble and needs liquidity — often *before* the property hits any distress list. Each event is a distinct lead SOURCE with its own funnel: death → pre-probate heirs who want to liquidate fast; divorce → forced sale of the marital home to split assets; bankruptcy Ch.7/13 → automatic-stay borrowers; incarceration → an owner who can't manage the asset; vacancy → a non-performing, deteriorating asset the owner has physically left; eviction/code → a stressed landlord. These overlay the board with motivations the foreclosure/tax lanes can't see, and they *stack* — a divorce + tax lien on the same parcel is a far hotter lead than either alone.

### Current state in the engine (measured fill-rate, how it's sourced now, exact code files)
Measured: **life_events 1.2%, incarceration 0.1%.** Each facet is wired but thin:
- **Death/probate:** `scrapers/public_notices/gannett_obituaries.py` (8 Gannett papers, plain HTML, name-only decedent leads → resolver pins parcel via GIS owner index); `enrichment_life_events.py` (pure-text name flags: LIFE EST / ESTATE OF / HEIRS / ET AL / TRUST + `gis_exempt` senior/disabled tag); `scrapers/counties_sc/sc_probate_net.py` (southcarolinaprobate.net, NOT bot-walled, PR name+address); `enrichment_relationship_deeds.py` (re-scans ROD for executor/distribution/quitclaim deeds).
- **Divorce:** `enrichment_sc_divorce.py` — **live-verified & default-ON**, SC FCCMS PublicAccess JSON API (SMITH in Spartanburg = 1,449 rows indexed). `enrichment_nc_divorce.py` — logic complete but **gated OFF**; NC eCourts Smart Search is AWS-WAF/CAPTCHA-walled.
- **Bankruptcy:** `enrichment_bankruptcy.py` — CourtListener v4 API (courts ncwb/nceb/scb, 180-day lookback), free with token, strict-subset name match.
- **Incarceration:** `enrichment_incarceration.py` (NC DAC + SC SCDC state prison, name-only) + `enrichment_jail_bookings.py` (Cherokee/Anderson Zuercher, Cleveland/Buncombe P2C, Gaston/Greenville per-name). All **name-only, no DOB → LOW-confidence stack signal**.
- **Vacancy:** `scrapers/counties_sc/spartanburg_vacant.py` (City ArcGIS, 5,014 parcels) — one city only.
- **Eviction:** `enrichment_eviction_market.py` — **aggregate county rate only** (LSC CCDI), market context, NOT per-case leads.
- **Estates/NC probate:** `scrapers/counties_nc/nc_ecourts_estates.py` — WAF-walled, ships a Gemini-vision solver path (**ToS-gray, treat as unavailable**).

### What reaching 100% actually requires
Two things must both succeed: (1) **the event record** — decedent/plaintiff/debtor/inmate name + filing date + county; and (2) **the identity join** — matching that *person* to a *parcel* and then to a *live contact*. Facet #2 is the true ceiling. Court/obituary/roster records are name-indexed with no DOB and no address; our board is parcel-indexed. Every name-only match is inherently ambiguous (24 "Robert Morgan"s), so 100% requires a **DOB or SSN-anchored identity graph** to disambiguate and to reach the owner who has moved, died, or is incarcerated. No free source provides that.

### FREE routes
- **PACER via CourtListener/RECAP** (bankruptcy): CourtListener REST API is free (rate-limited); every doc already in the RECAP Archive is permanently free. **Method:** already wired. **Ceiling ~40-60%** of in-footprint filings (RECAP only has what someone uploaded). **Effort:** low (built). **Cadence:** monthly. **Compliance:** clean, public.
- **PACER direct** (bankruptcy gap-fill): $0.10/page, $3.00/doc cap, **$30/quarter waived** (75% of users pay $0). **Ceiling ~95%** of BK. **Effort:** low. **Compliance:** clean; nearly free at our volume.
- **SC FCCMS** (divorce): live JSON API. **Ceiling ~80%** SC core counties. **Effort:** built. **Cadence:** monthly. **Compliance:** clean, no CAPTCHA on this search.
- **Gannett obituaries + southcarolinaprobate.net + county probate indices** (death/probate): plain HTML/ASP.NET. **Ceiling ~50-70%** of deaths (Gannett papers only) / ~40% probate (few SC courts feed the aggregator). **Effort:** built; add legacy.com + funeral-home RSS to widen. **Cadence:** weekly. **Compliance:** clean.
- **Jail/prison rosters** (incarceration): Zuercher/P2C/Aegis/LANSA + SCDC. **Ceiling ~30%** (snapshot-in-time, name-only, no DOB join). **Effort:** built; Henderson Southern-Software deferred. **Compliance:** clean, no WAF defeat.
- **ROD relationship deeds** (probate/divorce, recorded): free re-scan of existing ROD pool. **Ceiling** limited by ROD fill (loan/deed data 3.6%). **Compliance:** clean.
- **NC eCourts estates/divorce:** **WALLED** (AWS-WAF CAPTCHA). Compliant free ceiling here is **0% automated** — operator-parses-offline only.
- **Eviction per-case & USPS vacancy:** no free per-case eviction feed (seller-side wall); USPS vacancy indicator is licensed-only.

### PAID routes
- **BatchData / BatchLeads** (probate + divorce + vacant filters, all bundled): BatchLeads $71 / $209 / $449 per mo (Growth/Pro/Scale); skip-trace **$0.10-0.15/record**; BatchData standalone lookup **$0.05** *(dealrun.ai / batchdata.io, 2026, verify)*. Life-event filters (probate, divorce, **vacant**) are built in. **Coverage ~70-85%** with contact append. **Integration:** low (CSV/API). **ToS:** resale/redistribution restricted — internal use OK.
- **All The Leads** (probate, per-county courthouse lists): **$249-$1,099/mo/county** *(alltheleads.com, 2026, verify)*. **Coverage ~90%** of filed probate in a covered county, with skip-trace. **Integration:** low. **ToS:** licensed list, internal use.
- **US Probate Leads:** as low as **~$80/mo/county** *(usprobateleads.com, 2026, verify)*. Cheaper, thinner append. **Coverage ~70%.**
- **The Warren Group** (probate + **divorce** lists): **$0.50/record** *(thewarrengroup.com, 2026, verify)* — the only clean paid *divorce* list vendor, fills the NC-WAF gap. **Coverage ~85%.**
- **TLOxp (TransUnion) / idiCORE (LexisNexis)** (the DOB/SSN identity join — deceased, bankruptcy, liens, relatives): **quote-based, several hundred to several thousand $/mo, annual contract** *(g2.com/saasworthy, 2026, verify)*. This is the only tier that *disambiguates* name-only matches. **Integration:** medium (API + credentialing/DPPA gate). **ToS:** GLBA/DPPA permissible-purpose required — the hard gate.
- **USPS DSF2 vacancy:** **$191,000/yr license** *(PostalPro, 2026, verify)* — **out of scope**; get the same flag via BatchData instead.

### Feasibility verdict
**CANNOT hit 100%.** Three hard ceilings: (1) **NC eCourts estates + divorce are AWS-WAF/CAPTCHA-walled** — no compliant automated path exists, only operator-parses-offline. (2) **Per-case eviction is a confirmed seller-side wall** — the tenant is filed against, not the owner-seller; the parcel join fails. (3) **The identity join itself** — every free life-event source is name-only with no DOB, so a meaningful slice of matches stay ambiguous forever unless we buy a DPPA-gated identity graph (TLO/IDI). Realistic all-facets ceiling on the *free+compliant* stack is **~50-60%**; paid append pushes the *contactable* slice to **~85%**, never 100%.

### Recurring cost & cadence at our scale (17k leads, 18 counties, monthly)
- Free stack (PACER waiver, FCCMS, obituaries, rosters, ROD): **~$0/mo** (PACER stays under the $30/qtr waiver; CourtListener free).
- **BatchData life-event + vacancy filter + skip-trace, whole board once:** 17,003 × $0.05 ≈ **$850 one-time**, then re-skip only the ~6.9% equity/HOT slice (1,173 leads) monthly ≈ **$141/mo (~$1,689/yr)**.
- **All The Leads across 18 counties @ $249:** $4,482/mo = **$53,784/yr** (expensive; skip unless probate is the primary play).
- **US Probate Leads 18 counties @ $80:** $1,440/mo = **$17,280/yr.**
- **Warren Group divorce** (fills NC-WAF gap): ~150 rec/county/mo × 18 × $0.50 ≈ **$1,350/mo.**
- **TLO/IDI identity join:** budget **~$300-1,000/mo** metered.

### MANUAL PLAYBOOK (per un-automatable slice — NC eCourts estates/divorce + probate detail)
1. Open `https://portal-nc.tylertech.cloud/Portal/Home/Dashboard/29` in a normal browser; solve the AWS-WAF human-verification grid once (a human may do this; we never automate it).
2. Set **Search Type = Smart Search**, **Case Category = Estate** (for probate) or filter **case type = CVD** (absolute divorce); enter the target county + a blank/date-window or the owner surname.
3. Run the search; for each result row copy **decedent/party name, case number, filed date, and the executor/PR name + address** into the operator CSV (columns: name, role, case_no, county, filed_date, address).
4. **Exclude 50B** (domestic-violence) rows entirely — safety matter, never a lead.
5. Save the results page HTML (File → Save) into the repo's manual court-export lane; the offline parser (`scripts/parse_nc_ecourts_export.py` / `ingest_publicindex_files.py`) ingests it.
6. For SC probate courts that don't feed the aggregator, repeat on the county's own probate portal, capturing decedent + PR mailing address.
7. Hand the CSV to the owner→GIS resolver (name → parcel), which auto-enriches and stacks the `divorce`/`probate` category. Re-run monthly.

### Recommended path (closest to 100% for least money)
Keep the **entire free stack running** (PACER-under-waiver bankruptcy, SC FCCMS divorce, Gannett + SC-probate + ROD death/probate, jail/prison rosters, aggregate eviction context) — this is ~$0/mo and covers ~50-60%. Add **one paid append: BatchData at $0.05/lookup** to filter for probate/divorce/**vacancy** *and* skip-trace in one call (~$850 one-time + ~$141/mo re-skip of the HOT slice) — this simultaneously fixes the vacancy gap (no $191k USPS license) and the contact gap. Add **Warren Group divorce ($0.50/rec)** only for the NC counties the WAF blocks. Defer All The Leads (too costly per county) and TLO/IDI (DPPA-gated) until deal volume justifies the identity graph. The manual playbook covers the WAF-walled NC estate slice a machine can't touch. Total realistic spend to reach ~85% contactable: **under $200/mo.**

Sources: [PACER pricing](https://pacer.uscourts.gov/pacer-pricing-how-fees-work), [CourtListener RECAP API](https://www.courtlistener.com/help/api/rest/v4/recap/), [USPS DSF2 PostalPro](https://postalpro.usps.com/address-quality/dsf2), [All The Leads probate](https://www.alltheleads.com/probate-leads/), [US Probate Leads pricing](https://bulk.usprobateleads.com/pricing/), [The Warren Group probate/divorce](https://www.thewarrengroup.com/solutions/marketing-lists/probate-leads/), [BatchData pricing](https://batchdata.io/pricing), [BatchLeads pricing breakdown](https://dealrun.ai/blog/batchleads-pricing-breakdown), [TLOxp G2](https://www.g2.com/products/tloxp/reviews).

---

## Geospatial: Situs Address, Parcel ID, Lat/Lng & the Address-LESS Lead Problem

### What it is & why it matters (for motivated-seller acquisition)
Geospatial identity is the spine of the whole board. A motivated-seller deal is only actionable once a distressed *person* is tied to a specific *parcel*, and that parcel is tied to a *situs address* (for mail/door-knock/skip-trace), a *lat/lng* (for flood, comps, mapping, photos), and a *parcel_id* (the join key every value/tax/lien enricher reads). Roughly 39% of leads arrive name-only (lis-pendens rolls, SC Public Index civil, divorce, probate, jail rosters) with no recorded property attached — they are ungradable and un-mailable until the `name → parcel → situs → lat/lng` chain closes. Closing it converts dead court rows into first-class acquisition targets, which is the single highest-leverage fill-rate move on the board.

### Current state in the engine (measured fill-rate, how it's sourced now)
Measured 2026-07-02 (N=17,003): `parcel_id` 88%, `street_address` 60.9%, `city` 42.8%, `zip` 41.9%, `lat/lng` 21.8%. Parcel is the strongest link; **lat/lng is the weakest** because the geocode cascade only fires when an address or city already exists. The pipeline is already sophisticated and entirely free/pure-HTTP:
- **`enrichment_geocode.py`** — 4-tier cascade: US Census onelineaddress → Nominatim (1 req/s) → city centroid → county-seat centroid (hard-coded table for 21 counties). A `GEOCODE_BUDGET_S=600` wall-clock cap forces address-less leads onto the instant centroid to avoid the 8.5h full-run hang.
- **`enrichment_parcel_from_geo.py`** — point-in-polygon lat/lng → parcel_id. SC via SCDOT `SC_Parcels` MapServer (per-county field list in `_scdot_parcel`); NC via NC OneMap `NC1Map_Parcels/FeatureServer/1` (`parno`, county-guarded). This is the reverse-direction workhorse.
- **`enrichment_situs_address.py`** — the #1 address unlock: for any address-less lead with a parcel_id or lat/lng, reads the situs street/city/zip out of the matched GIS attribute bag (reusing `gis_attrs_full`, zero new HTTP where possible). Handles split house-number+street-name layers and rejects mailing/PO-box/placeholder junk. Includes placeholder-coordinate detection (a coord shared by 3+ leads is a county centroid, never point-queried).
- **`enrichment_parcel_reverse_geo.py`** — Nominatim reverse-geo on parcel centroid → *approximate* nearest-road address, promoted into `street_address` only behind a surname-match gate (capped `FORECLOSURE_REVERSE_GEO_MAX=300`/run).
- **`enrichment_resolve_name_to_property.py`** + **`enrichment_aggressive_address.py`** — the name-only backbone: owner-name LIKE search against county GIS, best-unique match only, backfilling parcel/address/value. `parcel_resolver.py` adds SCDOT point→assessor-key resolution for 5 SC counties.
The known live bug: Charleston situs is split into `PROP_ST_NO`+`PROP_ST_NA` on SCDOT layer 10, and the official **chascogis `Charleston_County_Addresses` address-point layer (70,019 pts, `WHOLE_ADDRESS`+10-digit PID) is not yet wired into any scraper** — a net-new free resolver.

### What reaching 100% actually requires
Every lead needs four elements — `parcel_id`, `street_address`, `lat/lng`, `city/zip` — and the join that produces them is only as good as its weakest input. The chain: (1) **identity** — a name or parcel or point good enough to uniquely match one property; (2) **parcel geometry** — a polygon layer covering that county; (3) **a situs field** on that layer; (4) **a rooftop coordinate**. 100% therefore fails whenever a lead is name-only *and* the name doesn't uniquely resolve in county GIS (common surnames, LLCs, name variants, out-of-county owners) or the county has no owner-searchable layer. That residual — name-only + non-unique/absent property — is the hard slice.

### FREE routes
- **US Census Geocoder** (`geocoding.geo.census.gov`): batch onelineaddress, no key, no rate limit, storage OK. Ceiling ~85% of *address-bearing* leads; useless for address-less. Effort: already wired. Cadence: every run. Compliant, public-domain.
- **Nominatim/OSM**: free-form + reverse. Ceiling ~90% address-bearing but **1 req/s TOS cap** makes it unusable at 17k scale for anything but the capped reverse-geo pass. Compliant only within the 1/s + attribution rules; self-hosting OSM removes the cap (heavy setup).
- **SCDOT `SC_Parcels`** + **NC OneMap `NC1Map_Parcels`**: point↔parcel↔situs, statewide, free JSON, storage OK. This is the backbone. Ceiling ~95% of SC/NC parcels (Cleveland NC absent from OneMap statewide; some SC county layers lack a situs field). Cadence: every run. Fully compliant public GIS.
- **County ArcGIS address-point + owner-search layers** (e.g. chascogis `Charleston_County_Addresses`, NC OneMap `siteadd`): resolve by parcel_id, lat/lng, *and* owner name. Ceiling: closes ~18% of Charleston's address-less slice; net-new. Effort: 1 resolver per county schema. Compliant.
- **County GIS owner-name search** (already in `resolve_name_to_property`): the only free path for name-only leads. Ceiling ~40–55% of name-only (unique matches only). Compliant.

### PAID routes (real 2026 pricing — "verify")
- **Geocodio** — US+CA rooftop geocode + reverse; **2,500 lookups/day free, then $1.00/1,000** (rose from $0.50 on 2026-02-01) (as of 2026, verify). **Storage explicitly allowed.** Best price/ToS fit; batch API; ~1-day effort. ToS clean.
- **Smarty US Rooftop Geocoding** — rooftop + address verification; **$45/mo for 1,000, $106/mo for 5,000**, up to ~$12,450/yr for 2M/yr (as of 2026, verify). Storage-friendly, highest accuracy. Moderate effort.
- **Mapbox** — 100k free/mo; **temporary $0.75/1,000 but storage-prohibited**; **Permanent (storage-allowed) geocoding $5/1,000** (as of 2026, verify). The $5 permanent tier is the only usable one for a persisted board. ToS: permanent results are own-use, no redistribution.
- **HERE** — Base plan **30k free/mo, then ~$0.83/1,000** (250k free on legacy Freemium); **+6% from 2026-04-01** (as of 2026, verify). Storage allowed on paid. Moderate effort.
- **Google Geocoding** — **$5/1,000 (→$4 >100k), 10k free/mo/SKU** (as of 2026, verify). **Hard ToS wall: geocodes may not be stored/used without display on a Google map** — disqualifying for a private lead board. Do not use.
- **Regrid nationwide parcel geometry/API** — parcels, zoning, situs, owner for all US counties; **custom, "several hundred to several thousand/mo" for API, pro web plans a few hundred/mo** (as of 2026, verify). Would guarantee 100% parcel geometry (incl. Cleveland NC and situs-less counties) in one schema. High value, but overkill vs free SCDOT/OneMap for only 18 counties. ToS: licensed, storage per contract.

### Feasibility verdict
**CANNOT hit a true 100% for lat/lng and situs — but CAN reach ~92–96%.** The hard ceiling is the *name-only-with-no-unique-property* slice: a defendant whose name is common, an LLC/trust, a misspelling, or an owner whose parcel isn't in a searchable county layer simply has no machine-resolvable property, at any price — no geocoder or parcel vendor turns a bare name into a parcel. Paid parcel data (Regrid) closes the *geometry* gap to ~100% but not the *identity* gap. That residual (~4–8%) is inherently manual.

### Recurring cost & cadence at our scale
17k leads, monthly refresh, but only the ~39% address-less + the un-geocoded delta actually need paid calls — call it ~7,000 lookups/refresh, and most resolve free via Census/SCDOT/OneMap first. Realistic paid volume: ~2,000–3,000 rooftop geocodes/month for the residual.
- **Geocodio**: 2,500/day free covers a monthly batch of ~3,000 essentially **$0/mo** (batched over 2 days), or ~$1–3/mo if over. 
- **Smarty**: $106/mo flat (5k lookups) if we want its accuracy.
- **Regrid API**: ~$300–1,000+/mo — only justified if we expand beyond 18 counties.
Free-first, the marginal cost is **~$0–$3/month.** Regrid is the only line item that would move the number, and it's optional.

### MANUAL PLAYBOOK (for the un-automatable name-only slice)
1. Open the lead's county **GIS/assessor property search** (e.g. Charleston chascogis, SC county qPublic, NC OneMap county viewer).
2. Search **Owner Name**, surname-first (e.g. `SMITH JOHN`). If zero hits, try surname-only, then spouse/co-defendant name from the court caption.
3. If multiple parcels return, cross-check the **case address/city** from the court PDF, and prefer an **owner-occupied residential** parcel (not vacant land) matching the county in the caption.
4. Open the matched parcel card; copy the **TMS/PIN (parcel_id)**, **situs/physical address**, **city**, **zip**.
5. Click the parcel on the GIS map; read **lat/lng** from the coordinate readout (or right-click → "what's here").
6. If GIS shows no situs, paste the parcel_id into the county **address-point layer** or reverse-look the centroid in Google Maps to read the rooftop pin, and label the result **approximate**.
7. Enter parcel_id/address/city/zip/lat/lng into the lead's row; set `address_source = manual_gis` and, if approximate, `address_is_approximate = true`.
8. If no unique parcel resolves after steps 2–3, mark `resolution = name_only_unresolved` and route to phone/skip-trace instead of mail.

### Recommended path
Keep the free stack as the default (Census → SCDOT/OneMap point-in-polygon → situs writer), and **add three cheap wins**: (1) **wire the chascogis Charleston address-point layer** and any NC OneMap `siteadd` county gaps — pure-free, closes ~18% of Charleston's address-less; (2) **add Geocodio** ($0–3/mo) as the paid rooftop fallback *after* Census fails, since it is storage-legal and effectively free at our volume — this alone lifts lat/lng from 21.8% toward the mid-90s; (3) **defer Regrid** until a footprint expansion makes statewide parcel geometry worth ~$300+/mo. Explicitly **avoid Google** (storage ToS) and Mapbox temporary (storage-prohibited). Net: ~$0–3/month gets the board from ~22% to ~92–96% geo coverage; the last ~4–8% is name-only-unresolvable and handled by the manual playbook.

Sources:
- [Google Geocoding usage & billing](https://developers.google.com/maps/documentation/geocoding/usage-and-billing)
- [Smarty US Rooftop Geocoding pricing](https://www.smarty.com/pricing/us-rooftop-geocoding)
- [Geocodio pricing](https://www.geocod.io/pricing) / [2026 pricing update](https://www.geocod.io/updates/pricing-updates-2026/)
- [Mapbox pricing](https://www.mapbox.com/pricing)
- [HERE pricing](https://www.here.com/get-started/pricing)
- [Regrid pricing](https://regrid.com/pricing) / [Regrid API](https://regrid.com/api)

---

## The PIECING — Identity Resolution & the Data-Join Backbone

### What it is & why it matters (for motivated-seller acquisition)

Every other fill in this engine is worthless if it lands on the wrong row. The PIECING is the glue: it takes a foreclosure notice ("Loussedes, Hayden"), a tax card (owner "LOUSSEDES HAYDEN", parcel `9678-77-4126`), a deed (loan $142k), a voter record (a cell phone), and an obituary — five different spellings, formats, and name orders — and collapses them onto **one** owner→property→contact object. Get the join right and one scraped phone number makes a $150 skip-trace unnecessary. Get it wrong and you either **split** one lead into three ghosts (over-count, wasted mail) or **merge** two different owners (send the wrong person a "we buy your house at 14 Oak St" letter — a compliance and brand risk). For wholesale/subject-to outreach, the deliverable is literally *name → property → equity → phone*; the PIECING is the spine that threads those four together across ~90 heterogeneous sources.

### Current state in the engine (measured fill-rate, how it's sourced now, the exact code files)

The join runs entirely on **free, deterministic, in-process logic** — no vendor:

- **Address normalization** — `models.py::_normalize_addr`: lowercases, expands a 30-entry suffix map (`Street→st`, directionals `North→n`), strips `Apt/Unit/Lot/#`, drops the city/state tail after the first comma. `dedupe.py::_canon_street` adds a house#-anchored canonical street with a wider suffix table (`cove→cv`, `crossing→xing`).
- **APN normalization** — `_normalize_parcel`: strips all non-alnum, then collapses the county-GIS zero-pad problem (`967877412600000 → 9678774126`) two ways (pure-zero tail past 10 chars, and a legacy `.000` suffix). This is why `parcel_id` fills **88%** and is the strongest join key.
- **Case-number normalization** — `_normalize_case`: strips non-alnum (`24 SP 123 → 24sp123`); deliberately does **not** cross 2-vs-4-digit year forms.
- **Merge + also_seen_in** — `Listing.merge`: prefers non-null, treats `0` as missing for money fields, deep-merges `raw` so nested `raw["gis"]` sidecars survive, keeps earliest `first_seen`, and appends every `{source,url}` to `raw["also_seen_in"]` so the operator can open all sources for one property.
- **The 3-pass join** — `dedupe.py::dedupe`: (1) bucket by `dedupe_key` (parcel > addr+zip > case > url), (2) rapidfuzz `token_set_ratio ≥ 92` cross-merge when zips match, (3) union-find on **strong signatures** (`_strong_sigs`) to stitch a row that has a parcel on one copy and only a case# on another.
- **Entity → humans** — `enrichment_sos_agent.py`: NC-only, Scrapling-stealth NC SoS profile parse yielding registered agent + officers + `best_contact_name/address`, with `agent_is_service` flagging CSC/CT mailboxes. Fills the **SoS-entity-contact 0.3%** line.
- **Name → property** — `enrichment_address_owner_v2.py` handles surname-first vs comma-first vs given-first name order and multi-result tie-breaks. **Name → phone** — `enrichment_voter_phone.py` keys `(county,last,first)` against the NC voter file (only when exactly one active voter matches). **Name → mailing** — the free `tax_records_only` skip-trace reads `raw["owner_mailing"]` for the absentee flag.

Resulting join quality: `owner_name` 89.9%, `owner_mailing` 65.8%, but `owner_PHONE` only **2.2%** and `SoS-entity-contact` 0.3% — the join *backbone* is strong; the *contact leaf* is where it starves.

### What reaching 100% actually requires (the data elements + the identity join that must succeed)

Four joins must each hit ~100%: (a) **address ↔ address** (CASS/DPV-standardized so `123 N Main St #4` == `123 North Main Street Apt 4` == the USPS-canonical form + ZIP+4); (b) **APN ↔ APN** across every county's private format (dashes, check digits, book-map-parcel, zero-pads); (c) **entity ↔ humans** (LLC → members/managers, resolving shell-of-a-shell chains and commercial-agent masking); (d) **person ↔ person** (fuzzy: nicknames, maiden/married surnames, Jr/Sr, transposed tokens, OCR errors). The current engine does (a) and (b) *heuristically* and (c)/(d) *thinly*. True 100% needs a canonical address (USPS CASS), a per-county APN grammar, a real entity-resolution engine, and probabilistic person-matching with a confidence score — not just `token_set_ratio ≥ 92`.

### FREE routes

- **USPS/Census canonicalization** — `geocoding.geo.census.gov/.../onelineaddress` (already wired in `enrichment_geocode.py`) returns the matched, standardized address + lat/lng. **Ceiling ~85%** of *complete* addresses; it silently drops rurals, PO boxes, and no-house-number situs. Effort: low (in place). Cadence: monthly. Compliance: public, TOS-clean, ~1/sec courtesy.
- **Smarty free tier** — 250 CASS lookups/mo + a 42-day / 1,000-lookup trial, no card. Real CASS/DPV canonical + ZIP+4. **Ceiling: 100% accuracy on the tiny slice you can afford (250/mo « 17k)**. Effort: low. Compliance: clean.
- **County GIS APN grammar** — hand-author one `_normalize_parcel` variant per county from the assessor's published parcel-ID key (already partially done for Buncombe's zero-pad). **Ceiling ~95%** of parcel joins. Effort: medium, one-time per county. Compliance: clean.
- **NC SoS entity→officer** (in place) + **SC SoS** is CAPTCHA-walled → operator-parses-offline only. **Ceiling: NC ~70% of LLCs, SC 0% automated.**
- **NC voter file name→phone** (in place): free, but NC-only and single-match-only. **Ceiling ~15–20%** of NC individual owners.
- **rapidfuzz person-matching** (already a dependency): raise recall with `token_sort_ratio` + a nickname table. **Ceiling: good recall, no external identity graph** so it can't resolve maiden↔married or a moved owner.

### PAID routes

- **Smarty US Address Verification** — CASS-certified canonical + DPV + ZIP+4. **~$0.001–$0.004/lookup at volume**; published tiers ~$17/mo (1k) up to ~$485/mo (170k); 100k–500k/mo lands ~$5k–$25k/yr (*as of 2026, verify*). 17k rows once = **~$50–$70**. Integration: low (drop-in for the Census call). ToS: commercial use permitted. [Smarty pricing](https://www.smarty.com/pricing)
- **Melissa Personator (Consumer/Property)** — CASS + name/phone/email append + identity confirm, credit-metered: **$30/10k, $84/30k, $285/100k credits** (a full Personator call burns several credits) (*as of 2026, verify*). 17k full-append runs ≈ **$150–$400/mo** depending on components. Integration: medium. ToS: append allowed; GLBA-permissible-purpose attestation required for phone. [Melissa pricing via Tekpon](https://tekpon.com/software/melissa-data/pricing/)
- **BatchData Skip Trace** — the closest fit to this repo's outreach mission; returns phone+email+mailing+DNC scrub, **76% right-party rate**, **$0.07–$0.18/record** PAYG (Growth ~$0.02, Enterprise ~$0.0066); plans $2k/mo (100k) → $20k/mo (3M) (*as of 2026, verify*). [BatchData pricing](https://batchdata.io/pricing)
- **Tracerfy** — **$0.02/record API**, no subscription, no monthly minimum — the cheapest credible skip trace found. (*as of 2026, verify*). [Tracerfy](https://www.tracerfy.com/skip-tracing-api)
- **DataZapp** — skip trace from **$0.03/lookup** (*as of 2026, verify*). [DataZapp](https://www.datazapp.com/skip-tracing-real-estate-marketing/)
- **REISkip $0.10–0.15**, **PropStream $0.10–0.12** — turnkey but pricier per hit (*as of 2026, verify*).
- **Senzing (entity resolution)** — real LLC→human + person-dedup graph. **First 100,000 records FREE**; paid by DSR count thereafter, quote-only (*as of 2026, verify*). At 17k records this is **$0 forever** — the single highest-leverage free-tier find for join quality. Integration: high (SDK, mapping). [Senzing pricing](https://senzing.com/pricing/)
- **TransUnion TLOxp** — premium credit-header skip trace, 5–20× consumer pricing, gated qualification. Overkill; skip.

### Feasibility verdict

**CANNOT hit a true 100% on the contact leaf; CAN reach ~99% on the structural join (address/APN/entity dedup).** The hard ceiling is the **phone/email leaf**, and it is a *data-existence* ceiling, not a code one: even BatchData's best-in-class product right-party-matches ~76% of owners, so ~1 in 4 owners has **no** obtainable good number at any price. CASS canonicalization *can* hit ~99% of mailable addresses. Entity resolution *can* hit ~99% of dedup/merge via Senzing's free tier. But `owner_PHONE = 100%` is physically impossible — the compliant fallback for the unmatchable ~24% is operator-gathered.

### Recurring cost & cadence at our scale (17k leads, 18 counties, monthly refresh)

- **CASS (Smarty), 17k/mo:** ~17,000 × ~$0.003 ≈ **$51/mo** (or a low monthly tier). One-time full pass ≈ **$50–$70**.
- **Entity resolution (Senzing):** 17k « 100k free → **$0/mo**.
- **Skip trace, only the un-phoned + imminent-sale slice.** Don't trace all 17k. Trace the ~2,000 highest-grade (A/B/HOT-WARM) rows lacking a phone: **Tracerfy** 2,000 × $0.02 = **$40/mo**; **BatchData** 2,000 × ~$0.12 = **$240/mo**. Full 17k on Tracerfy = **$340/mo**; on BatchData PAYG ≈ **$2k/mo**.
- **Blended recommended monthly:** ~**$50 CASS + $0 Senzing + $40–$240 targeted skip = $90–$290/mo**, refreshed monthly.

### MANUAL PLAYBOOK (VA hand-links a name→property→contact)

1. Open the lead in the dashboard; copy `owner_name` (or `defendant`) and `street_address`/`parcel_id`.
2. **Canonicalize the address:** go to `smarty.com/products/single-address` (always-free single tool), paste, record the USPS-standardized line + ZIP+4; paste back into the lead's notes.
3. **Confirm the parcel/owner:** open the county assessor/GIS parcel viewer (e.g. `lrcpwa.ncptscloud.com`, qPublic), search by parcel first, then owner; confirm the situs matches; copy the **owner mailing address** and note if it differs (absentee).
4. **Entity owner?** If the owner ends in LLC/Inc: NC → `sosnc.gov` Business Registration search → open profile → copy registered agent + each officer name/address (ignore the agent if it's CSC/CT/Registered Agents Inc). SC → `businessfilings.sc.gov` (CAPTCHA — solve it yourself, it's a human portal), copy the same.
5. **Name → phone:** search `fastpeoplesearch.com` (or TruePeopleSearch) by `Name, City ST`; open the single best age/location match; record up to 2 cell numbers, mark confidence *low* until a second source agrees.
6. **Cross-check** the phone against the county voter record (NC: `vt.ncsbe.gov/RegLkup`) by name+county; a match promotes confidence to *medium*.
7. Write `owner_mailing`, `best_contact_name`, `phone` into the lead's CRM notes keyed by its `dedupe_key`, so the next automated run's `merge()` preserves it.

### Recommended path (closest to 100% for least money)

1. **Adopt Senzing's free tier as the dedup/entity brain** — $0, resolves the split/merge and LLC→human failures the current union-find can't. Highest ROI move.
2. **Swap the Census geocode step to Smarty CASS** for the full 17k monthly (~$50/mo) — canonical addresses lift *every* downstream address join and mailer deliverability at once.
3. **Keep all free contact rails** (NC SoS, NC voter, tax-records absentee) — they cost nothing and pre-fill before any paid call.
4. **Add Tracerfy ($0.02) as the paid skip-trace of last resort**, fired only on the A/B/HOT-WARM rows still missing a phone (~2k/mo ≈ $40). Escalate a given lead to **BatchData** only when Tracerfy misses and the deal is live — pay the $0.12 for the 76% RPC exactly where the deal justifies it.
5. Accept the ~24% no-contact remainder as the operator-manual slice.

**Net:** ~$90–$110/mo takes structural join to ~99% and contact fill from 2.2% toward the ~76% real-world ceiling, with the manual playbook covering the rest.

Files of record: `/Users/cashhigh/foreclosure-scraper/src/foreclosure_scraper/models.py`, `.../dedupe.py`, `.../enrichment_sos_agent.py`, `.../enrichment_skip_trace.py`, `.../enrichment_address_owner_v2.py`, `.../enrichment_voter_phone.py`, `.../enrichment_geocode.py`.

---

## The "BUY IT ALL" Platform Comparison — One Paid Subscription vs. Our Free Stack

### What it is & why it matters (for motivated-seller acquisition)
Every other section of this blueprint attacks one field at a time. This section asks the blunt question: could a single paid subscription replace most of the 59-scraper free stack and vault us from today's patchy fill-rates to ~90%+ across the three things that actually close a deal — **contact** (phone/email), **value** (comps/ARV/liens/equity), and **distress** (pre-foreclosure/auction/probate)? For a wholesaler, the platform's job is to hand you a skip-traced, comped, distressed lead you can dial today. Our stack already nails distress-sourcing and value for free; where it bleeds is the two fields that convert: `owner_PHONE` (2.2%) and `owner_email` (~0%). That is precisely where paid platforms shine, so the trade is real and worth pricing.

### Current state in the engine (measured fill-rate, how it's sourced now, the exact code files)
We hand-built the equivalent of a mini-ATTOM for 18 counties: assessor/CAMA value at 75.2% market / 52.1% assessed (`enrichment_sc_cama.py`, `build_sc_assessor_cama.py`, `enrichment_lrcpwa_parcel.py`), owner name 89.9% + mailing 65.8% (`enrichment_owner_mailing.py`, `enrichment_address_owner_v2.py`), ARV computed on ~98% (`raw.calc.arv_expected`), and distress sourced from courts/trustees/auction sites. The one field money can trivially fix — **phone** — we source free from the NC voter file only (`enrichment_voter_phone.py`, ~2.2% board-wide because it's NC-owner-occupant-only), plus a human worksheet of TruePeopleSearch/FastPeopleSearch links (`build_skiptrace_worksheet.py`). `enrichment_skip_trace.py` is a stub/absentee-flagger, not a real trace. So the platforms would *replace or exceed*: value+liens+comps (partial overlap, they're broader), and *net-add*: phones/emails at scale (our biggest gap).

### What reaching 100% actually requires (the data elements + the identity join that must succeed)
A single platform gets us to "~90% across contact+value+distress" only if it (a) **covers all 18 counties** for recorded/assessor + foreclosure data, (b) bundles **skip-trace phone/email** at low marginal cost, and (c) exports by **API or bulk**, not UI-only, so it plugs into `merge_today_sources.py`. The join that must succeed is APN/owner→property→contact — the same backbone the free stack already runs. Platforms win because they pre-solve that join nationally.

### FREE routes
- **NC voter file phone** — NCSBE bulk (`enrichment_voter_phone.py`); ceiling ~15-20% board-wide (NC-only, occupant-only, ~69% phone-populated); effort low; monthly; compliant, DNC-gated.
- **Manual people-search** — TruePeopleSearch/FastPeopleSearch links in the VA worksheet; ceiling ~60-70% of *worked* leads but throughput-bound (~40-60/hr/human); recurring; ToS forbids scraping, so **human-only** is the compliant path.
- **County bulk assessor/recorder** — already how we get value; ceiling ~90% value, ~0% phone; ongoing. No free route reaches 90% phone. That is the wall paid platforms exist to break.

### PAID routes (real 2026 pricing — cite + verify)
- **PropStream** — value+comps+liens+pre-foreclosure+auction + **free skip-trace** on Pro/Elite (else **$0.12/result**). Essentials **$99/mo** (25k saves), Pro **$199/mo** (50k), Elite **$699/mo** (100k) *(as of 2026, verify)*. UI + list export; **no true API**. Weak auction detail/liens. Best value-per-dollar.
- **PropertyRadar** — best-in-class foreclosure/lis-pendens + trustee-sale + lien type/position, in-app skip-trace included. Solo **$119/mo** (10k monitored, 250 phones/emails), Team **$249**, Business **$599** (50k, 2,500 contacts); **has API** *(as of 2026, verify)*. Contact allowance is capped — thin for 17k.
- **BatchLeads / BatchData** — BatchLeads UI **$39-$119/mo**; skip **$0.10-0.15/record**. **BatchData API**: property search from **$500/mo (20k calls, ~$0.01/call)**; skip-trace/enrichment API from **$2,000/mo (100k records)**; single lookup **$0.05** *(as of 2026, verify)*. This is the API path.
- **DealMachine** — **unlimited** skip-trace (3 phones/3 emails), list builder, D4D. ~**$99-$232/mo** annual tiers; credits for mail/data can add up *(as of 2026, verify)*. UI-first.
- **REsimpli** — all-in-one CRM+dialer+free skip (10k-50k credits) + list-stacking. **$149 / $299 / $599/mo** *(as of 2026, verify)*. UI-only.
- **Foreclosure.com** — distress listings only, **$39.80/mo** *(verify)*; no phone/comps/API. Redundant with our free distress sourcing.
- **Privy** — MLS comps for investors, **$149/mo** *(verify)*; needs an MLS ID, no skip/distress. Not a fit.
- **ATTOM** — 160M+ properties, assessor/deed/AVM/pre-foreclosure. Property Navigator UI **$499/yr**; **API basic ~$500/mo**, bulk state-file licensing custom (org median ~$12k/yr class); 30-day trial *(as of 2026, verify)*. Enterprise-priced; skip-trace not bundled.
- **CoreLogic / DataTree (First American)** — deepest data + document images; **quote-only**, CoreLogic median ~**$12,000/yr** *(as of 2026, verify)*; enterprise contracts, overkill for 18 counties.

### Feasibility verdict
**A single platform CAN hit ~90% across contact+value+distress — but CANNOT hit 100%.** The hard ceiling is not coverage; it's the same two walls the free stack hits: **(1) live payoff/current loan balance** — no consumer platform sells the servicer's real-time payoff; they show *original* loan amount at best, so true equity stays modeled, not known. **(2) SC early-stage court data** — SC Public Index is ToS-no-scrape and these platforms buy the *same* county feeds, so SC lis-pendens lag/gaps persist regardless of spend. Everything else (phone, email, comps, liens, NC pre-foreclosure) a platform solves to ~85-95%.

### Recurring cost & cadence at our scale (17k leads, 18 counties, monthly refresh)
- **PropStream Pro** $199/mo = **$2,388/yr**, free skip on 17k, 50k export cap covers us. **Cheapest single platform to ~90%.**
- **PropStream Essentials + $0.12 skip**: $99 + one-time 17k×$0.12 = **$2,040 skip + $1,188/yr** ≈ $3,228 yr-1, then ~$99/mo + delta-only skip (~2-3k new/mo = ~$300/mo) ≈ **$4,800/yr** — worse than Pro. Take Pro.
- **BatchData API** to automate into the pipeline: $500/mo property + skip. Skipping the whole board monthly (17k×~$0.15) = **$2,550/mo just in traces** — do **delta-only** (~2,500 new/mo ×$0.15 = ~$375) → ~**$875/mo ≈ $10,500/yr**. API convenience costs ~4× PropStream.
- **PropertyRadar Business** $599/mo = **$7,188/yr**, but 2,500-contact cap throttles 17k — needs add-on contacts.

### MANUAL PLAYBOOK (VA, click-by-click) — for the un-automatable slice (SC early-court + any platform gap)
1. Open `docs/skiptrace_worksheet.csv` in Google Sheets; sort HOT tier, blank `phone_we_have_free` first.
2. In **PropStream** (or the free links): Search → paste `property_address` → open the property detail.
3. Click **Skip Trace** (free on Pro) → copy the top-ranked phone + email into `PHONE_found` / `EMAIL_found`.
4. For SC lis-pendens gaps: open the county Public Index result page the operator saved locally (per the manual court-export lane), read the party/case off the *list* page, paste case# into the sheet — do **not** scrape it.
5. Cross-check owner vs. `owner_mailing_address` to flag absentee; note in `notes`.
6. Tag every number `needs_dnc_scrub=Y`; leave dialing to the gated outreach stack.
7. Batch-paste completed rows back via `ingest_contacts.py` / `contact_ingest.py`.

### Recommended path (closest to 100% for the least money)
**PropStream Pro at $199/mo (~$2,388/yr)** is the single best buy: free unlimited-ish skip-trace on all 17k (fixes the phone/email gap that free routes structurally cannot), plus comps/liens/pre-foreclosure that *broaden* what we already compute — the cheapest route to ~90% on contact+value+distress. Keep the **free stack as the distress-sourcing and value backbone** (it's more granular per-county and $0), and use PropStream purely as the **contact + comps overlay**. If/when the pipeline must run contact enrichment *programmatically* rather than via UI, add **BatchData skip API on delta-only leads (~$375-875/mo)** — but only then, since it's ~4× the cost for automation convenience. Skip ATTOM/CoreLogic/DataTree (enterprise-priced, no bundled skip), Foreclosure.com and Privy (redundant/narrow). The two things **no** amount of spend buys: **live payoff** and **compliant SC early-court data** — those stay modeled and human-gathered.

Sources: [PropStream pricing](https://www.propstream.com/pricing), [PropertyRadar pricing](https://www.propertyradar.com/pricing), [PropertyRadar vs PropStream](https://www.propertyradar.com/compare/propertyradar-vs-propstream), [BatchData pricing](https://batchdata.io/pricing), [BatchLeads pricing](https://dealrun.ai/blog/batchleads-pricing-breakdown), [DealMachine pricing](https://www.dealmachine.com/pricing), [REsimpli pricing](https://resimpli.com/pricing/), [Foreclosure.com](https://realestatebees.com/software/foreclosure-com/), [Privy pricing](https://www.privy.pro/pricing/), [ATTOM (Datarade)](https://datarade.ai/data-providers/attom/profile), [ATTOM Property Navigator](https://www.attomdata.com/solutions/property-navigator/pricing/), [CoreLogic (Datarade)](https://datarade.ai/data-providers/corelogic/profile), [DataTree (First American)](https://www.firstam.com/mortgagesolutions/solutions/data-analytics/datatree.html)

---

## Recurring Operating Model & Total Cost of Ownership (Keeping It 100% and Fresh)

### What it is & why it matters (for motivated-seller acquisition)
A lead board is not a dataset you build once; it is a perishable inventory. Foreclosure auctions get postponed or sold, REO leaves inventory within days, owners move, liens get paid, and probate cases close. "100% fill" is meaningless if it is 100% *stale*. The operating model is the discipline that decides how often each data class is re-pulled, what that costs in machine-hours plus dollars, and — critically — where to *stop spending*. For wholesale/subject-to acquisition, the entire margin lives in the actionable HOT/WARM subset (roughly 1–3k of the 17,003), so the correct model spends free labor on the 17k bulk and concentrates paid dollars on the ~1–3k you will actually dial. Getting the cadence wrong either burns money re-buying data that hasn't moved or, worse, dials a seller whose house already sold at auction.

### Current state in the engine (measured cadence, how it's sourced now, the exact code files)
The engine already runs a tiered, mostly-free cadence enforced by macOS `launchd`, not cloud CI (anti-bot sites need the local Scrapling stealth browser):
- **Weekly full crawl** — `scripts/run_local.sh` + `scripts/install_local_schedule.sh` (Tuesday 09:00; missed runs fire on wake). This is the superset: all scrapers, Vision, comps, grading, publish. Entry point `src/foreclosure_scraper/main.py`, published via `web_artifact.write_artifact`.
- **Daily API refresh** — `scripts/daily_api_refresh.py` / `run_daily_api_refresh.sh`. Re-pulls only browserless JSON sources (Fannie HomePath, HUD, VA REO, foreclosure.com, CourtListener) because REO churns daily and day-old detail pages 404. Merges into `docs/listings.json`, preserving browser-scraped enrichment.
- **Daily court detail** — `run_daily_court.sh` + `patch_court_detail.py`, incremental (NC eCourts cap 150, SC cap 80) so ~3,900 cases build across days; carries the confirmed-sold filter.
- **Daily Vision** — `run_daily_vision.sh`, skips full-run days, rotates free Gemini keys.
- **Noon land-records** — `lrcpwa_refresh.sh`; **Daily 2pm SoS** — `sos_agent_refresh.sh` (+~40 NC LLC contacts/day). All guard against concurrent board-writers via PID locks and commit only on real change. Cost today: **$0 in vendor fees** — the only spend is electricity and the operator's attention.

### What reaching 100% actually requires (the data elements + the identity join)
Freshness is a *join* problem. Every refresh must re-key on `parcel_id` (88% fill, the stable spine) and fall back to normalized `owner_name` + situs. The elements that decay fastest and therefore drive cadence: auction `sale_date`/`sale_status` (perishable in days), `opening_bid`/`judgment_amount`, REO inventory membership, `owner_phone`/`owner_email` (the 2.2%/~0% gap), and lien payoff. Specs, geometry, and year_built are effectively static. So "100% and fresh" = a static tier pulled once, a slow tier monthly, and a perishable tier daily — with contact bought *last*, only after the deal is scored actionable.

### FREE routes (source · method · coverage-ceiling · effort · cadence · compliance)
- **County GIS/assessor (specs, value, owner_mailing)** — ArcGIS/qPublic/lrcpwa JSON. Ceiling ~90% of parcels. Effort: built. Cadence **monthly** (annual reassessment reality; nothing changes weekly). Compliant public data.
- **REO/auction feeds (sale_date, inventory)** — HomePath/HUD/VA/foreclosure.com JSON. Ceiling ~100% *of what they list*. Cadence **daily** (churn). Compliant.
- **Court dockets (case_number, status)** — NC eCourts Judgment JSON, SC PublicIndex. Ceiling bounded by WAF walls → operator-parses-offline for the walled slice. Cadence **weekly incremental**.
- **Free skip-trace (owner + mailing)** — tax records + best-effort voter/people-search phone, `FREE_SKIPTRACE_PHONE_MAX=40`. Ceiling: mailing ~65%, **phone ~2%** — this is the hard free wall. Cadence **on-contact**.
- **Vision condition** — rotating free Gemini/GitHub Models/Groq keys (~6k free calls/day). Ceiling 100% of listings-with-images (21%). Cadence **daily incremental**.

### PAID routes (vendor · what it provides · real 2026 price · coverage · effort · ToS)
- **PropStream** — property data + skip-trace. Pro **$199/mo** (skip-trace free at Pro/Elite), or Essentials **$99/mo** + skip-trace **$0.12/record** *(as of 2026, verify)*. Phone/email coverage ~60–75% match. Effort: manual UI or CSV; no official bulk API. ToS: no scraping/redistribution.
- **BatchData / BatchSkipTracing** — API skip-trace **$0.10–$0.50/record**, subscription **$2,000/mo for 100k traces** up to $20k/mo *(as of 2026, verify)*. True API → cleanest integration. ToS permits programmatic use on-plan.
- **REISkip** — **$0.15/match, no subscription** *(as of 2026, verify)*. Pure per-match, ideal for a small actionable subset.
- **Skip Genie** — **$58/mo incl. 100 searches, ~$0.14–$0.17 each** after, ~75% match *(as of 2026, verify)*.
- **BatchLeads** — list + skip + distress AI, **$71/mo (Growth) → $449/mo (Scale)** *(verify)*. **DealMachine** — **$59/mo** basic *(verify)*.
- **ATTOM** — bulk/append the whole board. API from **$95/mo**; bulk-license and Match&Append are custom-quote (no public per-county price) *(as of 2026, verify)*. Enterprise integration effort; contract + redistribution limits.

### Feasibility verdict
**CAN hit ~100% fresh — but only by paying for the contact layer.** Every non-contact class is reachable free at 90%+ and refreshable on the cadences above. The single hard ceiling is **owner_phone/email (~2% free)**: no compliant free route clears ~5–10% at scale, because carrier/consumer phone data is a licensed product. You cannot scrape your way past it without ToS/anti-bot evasion, which is off the table. So 100% *actionable* contact is a purchase, not an engineering problem.

### Recurring cost & cadence at our scale (17k leads, 18 counties, monthly)
- **Free stack (status quo):** $0 vendor. Labor = ~1 weekly full run (finishes in a sane window since the geocode/comp budget-bail) + daily sub-hour refreshes, effectively autonomous under `launchd`; call it ~2–3 operator hrs/wk of monitoring.
- **Full paid stack:** subscribing every source (PropStream Pro $199 + BatchLeads Scale $449 + ATTOM API $95) ≈ **$743/mo**, *plus* skip-trace on the whole 17k monthly at $0.12 = **$2,040/mo** → **~$2,800/mo**, most of it wasted re-skipping cold leads.
- **Hybrid (recommended):** free bulk + paid skip-trace on the actionable subset only. 2,000 HOT/WARM × $0.15 (REISkip, no subscription) = **$300/mo**. Add one PropStream Pro seat ($199) for manual gap-fill/list QA and you land at **~$300–$500/mo, all-in.** That is a **~5–9x saving** over the full paid stack for the same actionable coverage.

### MANUAL PLAYBOOK (VA/operator, click-by-click for the un-automatable slice)
1. Open the dashboard; filter to grade **A/B** + `distress` HOT/WARM with `owner_phone` empty (the ~1–3k subset). Export CSV.
2. **DNC scrub first:** load the CSV into the skip vendor and confirm its output flags DNC/litigator; skip-scrub against the DNC registry (federal rule: at least every 31 days) *(as of 2026, verify)*.
3. In **REISkip** (or PropStream), paste/upload the CSV, run per-match skip; download the returned phone/email file.
4. Re-key the return to the board by `parcel_id` (or owner_name+situs) and paste phones into `owner_phone`.
5. For court-walled cases: open the saved NC eCourts / SC PublicIndex result page the operator manually saved, run the offline parser (`parse_publicindex_export.py` / `parse_nc_ecourts_export.py`) — never bypass the WAF.
6. Before dialing, **manual-dial cell numbers only** (no autodialer without written consent; TCPA penalties $500–$1,500/call) *(as of 2026, verify)*; log EBR/consent per contact.
7. Re-run steps 1–4 monthly on the *new* actionable rows only, never the whole board.

### Recommended path (cheapest route closest to 100%)
Keep the free `launchd` engine exactly as it is for **everything except phone/email** — it already delivers 90%+ on specs/value/owner/mailing/court and refreshes on the right cadences (static→monthly, court→weekly, REO/Vision→daily). **Buy only the contact layer, only on the actionable subset, per-match** (REISkip $0.15 or PropStream $0.12), gated at contact time — never subscribe a whole-board skip. Add **one PropStream Pro seat ($199/mo)** as the human gap-fill and QA console, and reserve ATTOM bulk-license as a "graduate to" option only if the operation scales past ~10k dials/mo. Realistic monthly to run at 100% on the actionable subset: **~$300–$500.** Bound the cadence by three constraints, monitored automatically: (a) **source-drift** — `run_local.sh` already fires a count-drop alert (RC=2) and low-total (<200) guard; keep those as the drift tripwire and add a per-source zero-result alarm (Column-style silent 200+0 deaths are the known failure mode); (b) **DNC 31-day rescrub**; (c) **manual-dial/consent logging** to stay inside TCPA.

Files: `/Users/cashhigh/foreclosure-scraper/scripts/run_local.sh`, `scripts/install_local_schedule.sh`, `scripts/daily_api_refresh.py`, `scripts/run_daily_court.sh`, `scripts/run_daily_vision.sh`, `scripts/lrcpwa_refresh.sh`, `scripts/sos_agent_refresh.sh`, `src/foreclosure_scraper/main.py`.

Sources: [PropStream pricing](https://www.propstream.com/pricing) · [PropStream skip-trace $0.12](https://updates.propstream.com/skip-tracing-new-low-price) · [BatchData/BatchSkip pricing](https://batchdata.io/blog/batchdata-vs-propstream-property-data-platform-comparison) · [BatchSkipTracing G2 pricing](https://www.g2.com/products/batchskiptracing/pricing) · [Skip-trace cost comparison (REISkip/Skip Genie)](https://skipreach.com/blog/skip-tracing-cost-comparison) · [ATTOM bulk licensing](https://www.attomdata.com/solutions/bulk-data-licensing/) · [ATTOM pricing via Datarade](https://datarade.ai/data-providers/attom/profile) · [BatchLeads/DealMachine pricing](https://www.jamilacademy.com/blog/propstream-vs-batchleads-vs-dealmachine) · [TCPA 2026 / DNC 31-day / one-to-one vacated](https://blog.clickpointsoftware.com/tcpa-one-to-one-consent-can-spam-state-regulations)

---

## Completeness Critic — Gaps the 16 Sections Missed

I now have concrete, current pricing for every operational gap I identified. I have everything I need. Let me compile the completeness critique.

## Gaps the 16 sections missed

Verified against the repo (`valuation/calc.py`, `valuation/grading.py`, `distress_score.py`, `enrichment_strategy_fit.py`, `enrichment_lead_signals.py`, `outreach.py`, `enrichment_skip_trace.py`, `main.py` enrichment chain, `docs/completeness_audit.md`). The 16 sections cover every *data element on the card* but almost none of the machinery that turns a scored row into a closed deal. That's the pattern in the misses below.

**1. DNC / TCPA / litigator scrub — the section that lets you legally DIAL the phone you skip-traced.** The whole engine stamps `needs_dnc_scrub=True` on every number (`enrichment_voter_phone.py`, `contact_ingest.py`, `web_artifact.py`) and never scrubs. Section 3 (skip-trace) delivers a phone; nothing makes it *callable*. Without a federal + state DNC + wireless + known-litigator scrub, one serial-plaintiff dial is a $500–$1,500/violation TCPA suit — this is existential, not cosmetic, and SC §30-2-50 makes off-voter-file solicitation *unlawful at any price*. **Free-vs-paid:** free = honor the flag by mailing-only + manual national DNC lookup (5/day cap, unusable at scale); paid = DNC.com/TextP2P/RingScrub real-time API at ~$0.01/number + a TCPA-litigator list (~$130/mo) — the single cheapest insurance the whole engine can buy.

**2. NCOA / CASS address hygiene & mail-deliverability — owns the "does the letter arrive" half of Section 4.** Section 4 covers *finding* the mailing address; it does not cover *validating* it. 34% of mailings bounce on a stale/uncoded address, and the audit's own escape-route #4 (ASR/Return-Service endorsement) is the free half of exactly this gap but isn't a section. **Free-vs-paid:** free = USPS "Return Service Requested" endorsement (mover's new address comes back free on first mailer) + open USPS ZIP+4 lookups; paid = CASS+NCOALink run ~$0.02–$0.025/record or ~$39 flat per list (Melissa/Experian/AccuZip) — required anyway to get presort postage rates.

**3. Disposition & the buyer side — who you SELL the contract to.** The engine tags `WHOLESALE/LAND_WHOLESALE/GATOR/SUBJECT_TO` (`enrichment_strategy_fit.py`) and does `enrich_buyer_match` against a curated `docs/land_buyers.json`, but there is no section for building/maintaining/scoring the *buyer* list — cash-buyer identification (recent all-cash grantees from ROD deed data you already touch), buyer buy-box matching, or assignment-fee realism. A wholesale lead with no end-buyer is a dead lead. Memo `project_lrcpwa_and_buybox` already flags "no free structured buy box exists." **Free-vs-paid:** free = mine your own recorded-deed cash-grantee list per county (you already parse deeds); paid = PropStream/BatchLeads cash-buyer search bundled in the $99–$119/mo base.

**4. Recurring outreach EXECUTION cost & channel economics — the real TCO the "Operating Model" section will under-price.** `outreach.py` explicitly stops at *generating* content: "Actually SENDING (Gmail/Twilio/print-mail) is left to the operator." Section 17 prices *keeping the data fresh*, not *working the leads*. At current board size the working cost dominates: direct mail $0.50–$1.50/piece fully loaded (or EDDM $0.27–$0.52), skip-trace $0.10–$0.18/hit, RVM $0.012–$0.05/drop, plus 10DLC SMS registration. On 17,003 leads a single mail touch is ~$8.5k–$25k — a number that dwarfs any data-vendor line item and belongs in the TCO. **Free-vs-paid:** unavoidably paid; the lever is channel mix + tight HOT-gating, not free.

**5. Lead-to-deal feedback loop / outcome tracking — the model has no ground truth.** `docs/crm.json` stores a status lifecycle (`new→won/dead`) but nothing feeds *won/dead outcomes back into the intent score or grade weights*. `backtest_arv.py` calibrates ARV against sold prices (good), but the 0-100 intent score, distress weights, and strategy-fit thresholds are all hand-tuned constants with no closed loop. You can't answer "which signal actually predicts a close." **Free-vs-paid:** free — it's a modeling discipline (log dispositions, periodically re-fit weights against `crm.json` outcomes), not a data buy.

**6. Response/mail suppression & re-contact governance.** No section owns a suppression list: already-contacted-this-quarter, "not_interested"/"dead" CRM rows, bankruptcy-automatic-stay owners (dialing them violates the stay), litigators, or deceased owners still name-matched. `distress_score.py` excludes `sold_confirmed` from scoring but nothing suppresses them (or dead CRM rows) from the *outreach* file. Re-mailing a "STOP"/"not_interested" owner is both wasted spend and a TCPA/UDAP exposure. **Free-vs-paid:** free — join CRM status + bankruptcy flag against the mail-merge export before it ships.

**7. Timing/velocity of the LEAD, not just the property.** Sections cover the foreclosure *timeline* (§11) but not lead *freshness decay* or *first-mover advantage*. A lis-pendens is gold at week 1 and worthless the day of the sale; the audit even weights `_HELENE_PLACARD` decay but the board has no "days-until-sale" urgency tier or "new-this-run" priority in the score. Wholesalers win on speed-to-first-contact. **Free-vs-paid:** free — you already have `first_seen`/`sale_date`; add an urgency multiplier.

**8. Mobile/manufactured-home titling & land-vs-home ownership split.** `calc.py` has full `MOBILE_REHAB_TIERS` and the footprint covers rural counties where MH is a huge share, but no section covers the *DMV/title* reality: a manufactured home can be titled as a vehicle (SCDMV/NCDMV) separate from the land, or de-titled as real property. Chasing the parcel owner when the *home* is separately titled to someone else kills the deal at closing. **Free-vs-paid:** free-ish — SC/NC "moving permit" and retirement-of-title records are public but county-clerk-gated; largely a manual verification flag, not a scrape.

**9. HOA / municipal-lien / special-assessment survival at the auction.** `distress_score.py` has a `surviving_senior_debt_risk` penalty and §10 covers the lien *stack*, but nothing models which liens *survive foreclosure* by jurisdiction (HOA super-priority, municipal water/sewer liens that run with the land, SC tax-sale "subject to" other liens). This is a max-bid input, not just a distress signal — the risk_score touches it verbally but `calc.py` never subtracts surviving liens from `max_bid_70`. **Free-vs-paid:** free — encode the state/lien-type survival matrix as a rules table feeding max-bid.

**10. Owner-entity beneficial-ownership & multi-parcel portfolio view.** `enrichment_sos_agent.py` gets the registered agent/officer for LLC-owned parcels, but no section rolls up *one owner → all their distressed parcels* (portfolio seller) or resolves the human behind stacked LLCs. A landlord in default on 6 parcels is one phone call for a bulk deal, invisibly scattered as 6 rows today. **Free-vs-paid:** free — group by normalized owner_name/officer across the board (an identity-resolution job the "PIECING" section §15 should explicitly claim but currently frames only as name→property, not owner→portfolio).

**11. Legal/compliance posture of the SCRAPING itself as an operating risk.** The audit brilliantly documents *source* walls (Rule 610, ToS), but no section owns the engine's own compliance surface as an ongoing operational concern: FCRA (skip-traced data must not be used for tenant/credit decisions), CFPB/UDAAP on distressed-owner solicitation language, state assignment-of-contract and wholesaler-licensing rules (SC and several states now regulate wholesaling), and data-retention of PII on 15k owners. A cease-and-desist or a wholesaling-license action stops the business, not a row. **Free-vs-paid:** free — a compliance checklist + outreach-script review, but it must be *owned* somewhere.

**12. Data provenance, freshness-per-field, and staleness decay.** Fill-rate is measured board-wide, but no section owns *per-field freshness* (a `sale_date` from a 6-month-old crawl is dangerous; a tax balance accrues monthly). `distress_score` is recency-aware for signals but the underlying field timestamps aren't tracked or decayed. This is distinct from §17's "keep it fresh" (which is about re-running scrapers) — it's about *knowing which cells to trust today*. **Free-vs-paid:** free — stamp `*_asof` timestamps and expose a staleness flag.

**13. Deal-source concentration & single-point-of-failure monitoring as a business metric.** `source_health_tracker.py` alarms on per-source drops, but no section frames *lead-source concentration* as a strategic risk: if 40% of HOT leads come from one MIE roster that goes dark (they do — the audit lists many), the pipeline's deal flow craters. This is portfolio risk on the *input* side. **Free-vs-paid:** free — a concentration metric on the HOT tier by source.

---

**Contradiction / double-count flags across the sections:**

- **Distress signal is triple-counted across three sections.** The listing_type (e.g. `foreclosure_sale`) feeds (a) the Grade section's `_financial_score` bid-to-ARV, (b) the Distress-Stack `_LISTING_TYPE_SIGNAL` weight, and (c) the Intent-Score in `enrichment_lead_signals.py`, which *also* folds in the grade. So one foreclosure fact inflates financial-grade → intent-score AND distress-score → intent-score. Sections 1, 2, and the "Signal/Distress Stack" line will double-report the same underlying event as if independent. The code partially guards this (distress caps at one weight per category; grade withholds on proxy ARV) but the *intent score explicitly multiplies grade × distress*, re-entangling them.

- **Equity is computed and consumed in at least four places with different fallbacks.** `raw['equity']['pct']` drives (a) `grading._risk_score`, (b) `distress_score._equity_band`, (c) `strategy_fit._equity_pct`, and (d) the flags. Each has a *different* fallback when equity is null (risk falls back to flags; distress falls back to ROI; strategy falls back to long-tenure proxy). Section 1 (ROI/underwriting), Section 2 (grade), and Section 10 (lien stack/equity) will each claim equity, and they can silently disagree row-to-row. `_risk_score` even has an inline comment fighting this ("PREFER the real equity engine … which can contradict it").

- **"Underwater on foreclosing lien" is penalized twice with an explicit patch.** `grading._risk_score` docks −12 for the `negative_equity` flag and then adds a judgment≥ARV check that *tops up to −15* specifically to avoid double-counting — evidence the double-count is real and hand-patched. Sections 1, 2, and 10 all touch this; whoever owns it must reconcile.

- **Condition is both a valuation input (§12/§1 rehab tier) and a distress signal (§13).** `_condition_to_tier` in `calc.py` and `code_enforcement`/`distressed_condition` in `distress_score.py` read overlapping condition fields; a condemned property lowers ARV *and* raises distress *and* lowers property-grade — legitimate, but three sections will each claim "condition" and the blueprint should state it's one input consumed three ways, not three data gaps.

- **Absentee/out-of-state is claimed by both §4 (mailing) and §2 (score).** `distress_score` adds +8 absentee/+4 OOS to the score AND it's a deliverability attribute in §4 AND a strategy-fit gate — same fact, three owners.

**Net:** the 16 sections are a complete *data-completeness* map but omit the entire *act-on-it* layer (DNC/TCPA scrub, deliverability/NCOA, disposition/buyers, outreach-execution TCO, suppression, feedback-loop calibration) plus several *deal-killer* verifications (MH titling, surviving-lien-at-sale math, owner portfolio roll-up) and the engine's own *legal/compliance posture*. Every one of those blocks a close even when the row is 100% filled.

Sources: [TextP2P scrubs](https://textp2p.com/contact-scrubs/), [DNC.com Litigator Scrub](https://www.dnc.com/litigator-scrub/), [RingScrub pricing](https://ringscrub.com/pricing.html), [AccuZip CASS/NCOA](https://accuzip.com/products/address-data-quality/cass-ncoalink-anklink-software/), [DirectMail.io NCOA/CASS 2026](https://directmail.io/blog/best-ncoa-cass-providers-2026/), [PropStream free skip trace + pricing](https://www.propstream.com/news/propstreams-free-skip-tracing-new-pricing-lead-automator), [REsimpli BatchLeads vs PropStream](https://resimpli.com/blog/batchleads-vs-propstream/), [MPA direct mail cost 2026](https://www.mailpro.org/post/how-much-does-direct-mail-cost/), [LeadsRain RVM pricing](https://leadsrain.com/ringless-voicemail-price)
