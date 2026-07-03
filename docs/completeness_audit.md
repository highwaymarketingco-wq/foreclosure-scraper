# Completeness / Reconstruction Audit — Free Public-Only Motivated-Seller Engine

_18-county footprint (SC: Spartanburg, Anderson, Pickens, Oconee, Cherokee, Union, Laurens; NC: Buncombe, Gaston, Henderson, Rutherford, Cleveland, Burke, Lincoln, McDowell, Polk, Transylvania, Mitchell). Verdict synthesized from 5 adversarial escape-analyses (SC Public Index, NC eCourts Smart Search, 4 blocked $-fields, owner-contact, condition/vacancy/code). Date: 2026-07-02._

---

## 1. BOTTOM LINE

**No — we cannot hit "100% of all foreclosures + pre-foreclosure + full property enrichment" for free, and that ceiling is not reachable at any effort because three of the required inputs are legally absent or vendor-gated, not merely un-scraped.** Realistically the free stack reaches **~90-95% of foreclosure *sales* events, ~35-55% of true *pre-foreclosure* early-warning, and ~70-80% of per-property enrichment weighted by what actually drives a deal (owner, mailing address, value, taxes-owed, sale price, condition).** The dominant free-coverage losses are structural: (a) SC routes the defining foreclosure **lis pendens through the walled Clerk-of-Court index**, not the open ROD [§15-11-10; Greenville Clerk of Court], so the pre-auction window is only partially reconstructable; (b) NC **eviction case detail has no publication requirement** and sits entirely behind the CAPTCHA/WAF Smart Search post-Oct-2025 cutover [Portal FAQ; NC eCourts 10/13/25 cutover]; and (c) a hard PII/servicer/paywall band — **exact mortgage payoff, live lien balance, owner phone/email, and address-level USPS vacancy** — is unobtainable free at *any* effort, and in SC owner phone is unobtainable at any *lawful price* [§30-2-50; HUD USPS FAQ]. The irreducible residual with **no free path at any effort** is therefore small but permanent: exact live loan/payoff balances, address-level vacancy, per-owner phone/email at scale, SC magistrate eviction detail, SC exempt-deed sale prices [§12-24-40], and paywalled ROD document images (AcclaimWeb counties). Everything else the escape analyses proved is *reconstructable* to a usable degree from sources we already run or can build cheaply.

---

## 2. PER-BLOCKED-SOURCE VERDICT TABLE

| Blocked source | Non-gated free back-door? (Y/N + what) | Reconstruction from free sources (which + est. coverage %) | True residual gap (never-free) |
|---|---|---|---|
| **SC Public Index — foreclosure (sale stage)** | **N** (no API/bulk; C-Track is appellate-only; Rule 610 bars commercial) [sccourts case-records; Rule 610] | MIE rosters + trustee feeds + **scpublicnotices.com** 3-week sale ads (triangulate) → **~90-95% of sales** | Sale detail beyond the ad (rare); trivial |
| **SC pre-foreclosure / lis pendens** | **Partial** — LP is *optionally* also recordable at ROD (Spartanburg/Anderson portals free), but statutory notice runs through walled Clerk index [§15-11-10] | ROD-recorded LP where firm double-records → **~15-40% of pre-foreclosure only**; highly firm-dependent | The 60-70% of LPs filed Clerk-only; the early-warning window is the core hole. Compliant fill = **manual court-export lane** |
| **SC partition actions** | **N** — Common Pleas filing, no ROD/newspaper analog until sale ordered | Surfaces as a foreclosure-style sale ad only at the *end* → **~0% pre-sale, ~85% at sale** via scpublicnotices/MIE | Pre-sale partition intent; dark until ordered-sale |
| **SC / NC evictions (magistrate/summary ejectment)** | **N** — SC magistrate no ROD/notice; NC 100% behind Smart Search post-10/13/25 [NC cutover]; no publication requirement | NC Judgment-Search JSON catches only *money-judgment* evictions → **~25-35% NC, ~0-5% SC** | Possession-only + all case detail (address/tenant/disposition). **Confirmed hard wall** |
| **NC estates / probate** | **Partial** — estates absent from open Judgment-Search categories; only in walled Smart Search [Portal FAQ] | **Obituaries** (built) + **ncnotices.com** notice-to-creditors (decedent + PR + file#) + name→GIS join → **~55-65%** | Estate **inventory / real-property schedule** (Smart Search / in-person only) |
| **NC SP-foreclosure detail** | **Partial** — Judgment-Search JSON carries Foreclosure-SP + Lis Pendens rows at *index* depth [NC Bar Odyssey doc] | Judgment index + **ncnotices.com/Column** sale notices (address+date) + trustee + MIE + ROD LP → **~85-90%** | Filed-document detail / exact legal description (~10-15%) |
| **Taxes-owed $** | **Y** — **qPayBill** treasurer unpaid search (public, no login), join on dashed parcel_id; NC tax-bill portals (Buncombe/Gaston/Henderson) | qPayBill + tax-sale "Total Tax Due" lists (Oconee sheet) → **~70-90% of the delinquent subset** (exact balance) | Anderson SC (403), Cherokee SC (parcel-format join fail), Pickens (no bulk); penalty-accrual-forward |
| **Mortgage payoff $ (live)** | **N** — servicer-only PII; MERS returns servicer *name* only | Stated judgment/opening-bid (~20-25%) + amortized DOT lower-bound → estimate only; scalable to ~55% w/ DOT-OCR | **Exact mid-month payoff, arrears, escrow, HELOC draw — permanent wall at any price short of servicer** |
| **Sale price (SC — exempt deeds hide it)** | **Y** — assessor/qPublic **CAMA card** exposes structured sale-price + book/page history as text (not the deed) | Pickens/Oconee cards live-verified; Spartanburg last_sale ~91% → **~85-91%** | SC parcels never-sold (long-held family land); exempt-deed transfers themselves [§12-24-40] carry no price by law |
| **Lien / loan $ (recorded)** | **Partial** — free name INDEX has doc-type/lender/book-page but **NO $**; the "$X principal" is only on the scanned **image**. Spartanburg Logan image = free PDF, OCR-able | DOT image → OCR page 1 (Gemini-first stack) → original principal → amortize → **majority of hot Spartanburg leads** | **AcclaimWeb counties: images paywalled** (real wall); HELOC max ≠ drawn; original ≠ current balance |
| **Owner phone** | **N** — every reverse service is teaser→paywall or Cloudflare/ToS-walled | **NC voter-file** name+addr match → **~2.4% of NC now, ~5-8% ceiling** if loosened; **SC = 0%** | All SC phone (also unlawful to solicit off voter file [§30-2-50]); NC beyond voter match. **Skip-trace vendor territory** |
| **Owner email** | **N** — no free source either state | None | **100% residual. No free email anywhere** |
| **USPS vacancy** | **N** — HUD dataset is **census-tract aggregate only**, gov/nonprofit-sublicensed [HUD USPS FAQ]; address-level all paid NCOA resale | Proxy stack (absentee + no-homestead + tax-delinquent 2yr + poor-condition) → **~55-70% precision, poor recall** on flagged subset | **Address-level confirmed vacancy — permanent paid wall.** Utility-shutoff proxy also unavailable free |
| **Code-enforcement** | **Y (2 of 18)** — Asheville Accela open REST (2,738 recs, but frozen 2016-2018); Gaston EnerGov CSS live form-search | Asheville (stale) + Gaston (form-scrape) → **~2 of 18 counties**; rest ACA/EnerGov form or absent | Standing renewable county-wide open code feeds for the other 16 counties |
| **Condemned / demolition** | **N** open feed — orders live in council minutes (PDF) | Council-agenda OCR (Gemini stack) → **all 18 in principle, low yield/manual**; ~handful per city/quarter | No structured demolition feed; per-document OCR only |

---

## 3. NEW FREE ESCAPE ROUTES DISCOVERED (ranked, build-worthy)

1. **Assessor `Condition`/`Grade` CAMA field as a universal condition layer.** Buncombe live-verified: 98,170 residential parcels with per-PIN Condition (Poor=1,011, Unsound=323, Fair=2,926) + Grade + YearBuilt, PIN-joinable to owner/mailing we hold, refreshed annually. This converts "property condition" from a gap into a near-universal free layer. **Highest-ROI new build: replicate the CAMA condition/grade pull across the other 17 counties' assessor tables/qPublic cards** (we already touch these for sqft). Durable and renewable, unlike disaster snapshots.

2. **Run `sos_agent_refresh.py` across all ~946 NC entity leads.** The NC SoS registered-agent enricher works (Scrapling past Cloudflare, returns agent + officers + principal address, flags service-agents) but only 53 leads carry it — coverage is *throttle*-limited, not wall-limited. This is the single biggest free **mailable-human** unlock; turns LLC-owned parcels into a named-officer mailing contact.

3. **Hurricane Helene public damage layers (harvest now — time-limited).** Parcel/address-keyed structural-damage feeds are live and public: Spartanburg (Property_Damage_Assessments 1,531 + Palmetto_Property_Damage 696, w/ Building_Damage + Estimated_Loss + Occupancy_type), Henderson (HC_DamageAssessments2024_PublicView, 19,571 recs, maintained to Feb 2026), Buncombe (FEMA/SARCOP + PPDR). Rutherford/McDowell/Polk likely inside the same FEMA/SARCOP datasets — targeted pull warranted. Richest free *condition* signal in-footprint right now; decays over 12-24 months.

4. **"Address Service Requested" / "Return Service Requested" mail endorsement as the free NCOALink substitute.** USPS returns the mover's new forwarding address free on the first mailer — self-cleaning the list without licensing the paid NCOA feed. Not currently in the stack; pure-mechanism, zero data cost, closes part of the absentee "current address" gap.

5. **SC LLC business-address mailing lane (legally clean).** §30-2-50 explicitly *excludes* business addresses filed with DOR from the solicitation ban, so SC entity-owned parcels (572 leads) can lawfully be mailed at their GIS business mailing address — the one compliant SC contact lane where individual phone is both unavailable and unlawful. Already partially done via GIS-mailing; formalize it.

6. **Manual court-export lane as the *only* compliant SC pre-foreclosure fill.** Not a scraper, but the sole way to reach Clerk-of-Court lis-pendens (the real early-warning data) without tripping the automated-query ban. Operator saves Public Index result pages → offline parser ingests. Already scaffolded; this is the honest answer to the SC pre-foreclosure hole, so prioritize the operator workflow over hunting a nonexistent free endpoint.

7. **DOT-image OCR for Spartanburg lien $ (proven-free image → OCR).** Logan portal `view_image.php` returns a free PDF (no cart/login); OCR page-1 principal via the Gemini-first stack. Best-effort HOT/WARM-gated (fragile ~30-40s/lead render), not bulk — but it is the *only* free lever for recorded loan amounts and it works where the image is free.

---

## 4. THE IRREDUCIBLE LIST (impossible to get free at any effort)

1. **Exact live mortgage payoff / current loan balance** — servicer-held PII, mid-month-dependent; MERS gives servicer name only. Best free label is "lower-bound estimate."
2. **Current recorded-lien balance** — even a clean DOT-image OCR yields the *original* principal, never today's balance; and in AcclaimWeb counties the image itself is paywalled.
3. **Owner phone at scale** — no free reverse path exists; SC additionally unobtainable at any *lawful* price (§30-2-50 solicitation ban + no phone column in the paid voter file).
4. **Owner email** — no free source, either state, full stop.
5. **Address-level USPS vacancy** — HUD releases tract-aggregate only, gov/nonprofit-sublicensed; every address-level product is paid NCOA resale.
6. **SC magistrate eviction case detail** — no ROD recording, no publication requirement, and the Public Index carrying it is a ToS/bar-discipline wall.
7. **SC exempt-deed sale prices** — legally absent: §12-24-40 exempt transfers (foreclosure/deed-in-lieu/intra-spouse) state no value by statute, and those are exactly our distressed targets. (Non-exempt SC sale price is recoverable via CAMA — this residual is only the exempt subset with no prior qualified sale.)
8. **NC estate real-property inventory** — the court-file schedule of a decedent's parcels is Smart Search / in-person only; we recover property by name→GIS join, not from the file.

---

## 5. COMPLETENESS SCORECARD

| Dimension | Free coverage TODAY | After building §3 escape routes |
|---|---|---|
| **All foreclosures (sale stage)** | **~90-95%** — MIE + trustee + scpublicnotices/ncnotices/Column triangulate nearly every actual sale (SC judicial + NC power-of-sale) | **~93-96%** — marginal; this lane is effectively solved. Manual-export lane closes stray Clerk-only cases |
| **All pre-foreclosure signals** | **~35-55%** blended — NC SP-foreclosure index strong (~85%), SC LP weak (~15-40%, ROD-double-record only), evictions barely (NC ~25-35% money-judgment / SC ~0%), estates ~55-65% | **~45-60%** — manual court-export lane lifts SC LP; obit+creditor-notice+SoS lift estates. **Evictions + SC Clerk-only LP stay the permanent drag** — no free scaling |
| **Full per-property enrichment** | **~70-80%** weighted — owner/mailing/absentee/sqft strong; taxes-owed ~70-90% (delinquent subset); sale price SC ~85-91% / NC ~90%; **but** phone ~2% NC / 0% SC, email 0%, condition sparse, vacancy proxy-only, payoff estimate-only | **~80-88%** — CAMA-condition (near-universal) + Helene damage + SoS-agent mailing + ASR forwarding materially lift enrichment. **Phone/email/live-payoff/address-vacancy remain the hard ceiling** and cap this below ~90% for free |

**One-line honest carry-forward:** the engine is a near-complete *foreclosure-sale + property-enrichment* machine and a *partial* pre-foreclosure + *mail-only* outreach machine; the ~10-20 points it can never buy for free are the PII/servicer/paywall band (phone, email, live loan balance, address-level vacancy) plus SC's legally-walled early-stage court data — that band, and only that band, is where a human-gather or a paid vendor is the sole option.
