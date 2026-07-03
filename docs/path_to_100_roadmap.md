# Path to 100% — Phased Build Roadmap (R8 synthesis)

_Synthesis of the 8-round deep-dive (verification → county matrix → outreach layer → net-new sources → vendor teardowns → 13 critic gaps → forum intel). Companion to `path_to_100.md` (the scope) and `path_to_100_deepdive.md` (the research log). Generated 2026-07-02._

## How to read this
Four phases, cheapest-and-highest-leverage first. Each item: **cost · effort · what it closes · expected lift.** Phase 0 is all free and should ship before a single dollar is spent. The **hard walls never move** (live payoff, SC Rule-610 court data, SC exempt-deed prices) — the roadmap gets *around* them, not through them.

**Corrected vendor reality (from R1/R5):** ATTOM's transactional API can't legally power a persistent cached board (ToS: no >24h storage, no derivative DB) → use **RentCast + Realie**. Skip-trace "76%" is marketing → plan **~50–65% effective right-party-mobile** (R7). PropStream has no usable API → **PropertyRadar** is the API-clean alternative.

---

## PHASE 0 — Free wins (ship first, $0, ~1–2 weeks of eng)
Every one of these is free code against sources we already touch. Ordered by leverage.

| # | Item | Effort | Closes | Expected lift |
|---|---|---|---|---|
| 0.1 | **Wire NC OneMap `AddressNC` point layer** (resolve parcel_id/lat-lng → street address for all 11 NC counties) | Low (1 resolver) | address-less leads (~39%) | geo/address **+15–25 pts** across NC |
| 0.2 | **Laurens SC: wire the `Pebble/TaxParcel/MapServer` bulk layer** (Owner+Mailing+Sale_Price+Sqft) — _replaces the RETRACTED Rutherford "one-line fix" (no parcel service exists there; Rutherford stays a real gap → use OneMap/lrcpwa)_ | Low | SC specs+sale for a whole county | free specs where R2 said "cadastral-only" |
| 0.3 | **Henderson NC: map the already-fetched `HEATED_AREA`/`TOTAL_PROP_VALUE`/`PKG_SALE_*`/`PROPERTY_OWNER`** into `_apply_attrs` | Low | sqft/value/sale gap | free specs for a top county |
| 0.4 | **Spartanburg: pull specs/sale/condition from county `CAMA_Parcels` FeatureServer** (clean) instead of corrupt SCDOT | Low-Med | SC sqft/sale/condition | biggest SC county fully specced free |
| 0.5 | **Cleveland NC: parse `clevelandcountytaxes.com`** per-parcel → situs + tax-due + WebGIS pid | Med | situs gap + tax-owed | situs for a no-situs county |
| 0.6 | **Ensure `assessor_cards/polk_nc.py` runs for every Polk lead** (already built) | Trivial | Polk sqft/sale | free per-parcel specs |
| 0.7 | **Run the free Vision pool at full board scale** (Gemini/GitHub/Groq/NIM/Ollama, $0) | Low | condition 0%→~21% | condition on every photo'd lead |
| 0.8 | **HUD SAFMR + Zillow ZORI rent enrichers** (free ZIP×bed) | Low | rent-comps 3.8%→~100% presence | cash-flow verdict on every SFR |
| 0.9 | **FHFA UAD Aggregate + Redfin Data Center + Zillow ZHVI/sqft** as free $/sqft ARV floors for the no-comp slice | Low-Med | ARV confidence on comp-thin rurals | LOW→MEDIUM ARV lift |
| 0.10 | **🚨 DNC/TCPA scrub gate** — add model fields (`dnc_*`, `litigator_flag`, `phone_type`, `last_scrubbed_at`, `consent_basis`) + a hard pre-send gate in `outreach.py` + internal opt-out suppression list | Med | **existential legal exposure** | makes phone outreach *legal* |
| 0.11 | **Pre-send suppression join** (dead / BK-automatic-stay / deceased / litigator / already-contacted-this-quarter) before any mail/dial | Low | wasted spend + legal | cleaner sends |
| 0.12 | **Lead-velocity urgency tier** (days-until-sale multiplier from `first_seen`/`sale_date`) + "new-this-run" priority | Low | first-mover advantage | HOT list ranks by *time* |
| 0.13 | **Owner→portfolio rollup** (group by normalized owner/officer → one landlord's N distressed parcels = one bulk call) | Low-Med | missed bulk deals | net-new deal type |
| 0.14 | **Surviving-lien matrix** (HOA super-priority + municipal water/sewer + SC tax-sale AS-IS) as a rules table feeding `max_bid_70` | Med | over-bidding risk | correct max-bid |
| 0.15 | **MH-titling flag** (no NC G.S. 47-20.6 / SC affixation affidavit at ROD → home likely still DMV-titled separate from land) | Med | closing-table deal-death | flag before you chase |
| 0.16 | **Per-field `*_asof` timestamps + staleness flags**; **source-concentration metric** on the HOT tier | Low | trust-which-cell + input risk | data you can trust |
| 0.17 | **Cash-buyer list from ROD all-cash grantees** (mine deeds we already parse) | Med | disposition (no end-buyer = dead) | the *sell* side, free |
| 0.18 | **Feedback loop**: log won/dead dispositions, periodically re-fit intent-score/distress weights vs outcomes (like `backtest_arv.py` does for ARV) | Med | hand-tuned constants with no ground truth | scores that learn |

**Phase 0 result:** geo/address, specs, rent, and condition all jump toward their ceilings; the board becomes *legally sendable*; and the disposition + learning layers exist — all at **$0 vendor cost**.

---

## PHASE 0.5 — The one non-negotiable paid line ($199/mo)
| Item | Cost | Why it's not optional |
|---|---|---|
| **TCPA Litigator List (Basic)** | **$199/mo** (200k scrubs incl.) | Covers litigator + federal + state DNC for the whole 17k board. Pairs with the 0.10 gate. At $500–$1,500/violation, this is the cheapest insurance the engine can buy. Add the official FCC **Reassigned Numbers DB** (~$0.0025–$0.01/query) once phone volume justifies. |

---

## PHASE 1 — Cheap paid enrichers (<$200/mo, wire when free ceilings hit)
| Item | Cost | Trigger | Closes |
|---|---|---|---|
| **Geocodio** (rooftop geocode, storage-legal) | ~$0–3/mo (free 2,500/day) | after Census/SCDOT/OneMap+AddressNC still leave a gap | last-mile geo → ~92–96% |
| **RentCast** (AVM + rent + sale comps, permissive license) | **$74/mo** Foundation (1,000) → $199 Growth (5,000) | monthly gap-fill volume > ~1,000 | AVM/value/rent on the no-county-data slice |
| **TrueNCOA** (CASS+DPV+NCOA, whole board) | **$20/file/mo** | once you mail | kills the 34% mail bounce |
| **Smarty US Address Verify** (CASS canonical, lifts every join) | ~$50/mo (17k) | when join quality matters | ~99% mailable + dedupe |
| **Senzing** (entity resolution, LLC→human + person-dedup) | **$0** (free ≤100k records) | now — it's free at our size | the split/merge failures union-find can't |

**Phase 1 all-in ≈ $150–350/mo** and takes value/geo/rent/deliverability/dedup to their *practical* ceilings.

---

## PHASE 2 — Skip-trace the ACTIONABLE subset only (variable, HOT/WARM)
Never skip-trace all 17k. Trace the ~1–3k HOT/WARM lacking a phone. **Plan on ~50–65% effective right-party-mobile, not 76%** (R7).
| Item | Cost | Notes |
|---|---|---|
| **DataZapp** whole-board baseline sweep | ~$0.03/rec (~$510 once) | cheap phone/email baseline |
| **BatchData** or **REISkip** monthly HOT/WARM delta | ~$0.02–$0.15/rec (~$40–$300/mo) | TCPA/DNC-aware; track cost-per-**connect**, not per-record |
| **PropertyRadar** (if you want an API-native platform) | $549–599/mo Business (has API) | the clean alternative to PropStream (no API) |
| _Skip TLO/IDI_ | — | gatekept (DPPA/GLBA credentialing) — likely unopenable to a solo op |

---

## PHASE 3 — Send + work the leads (the real TCO)
The working cost **dwarfs** data spend. One mail touch on 2,000 HOT/WARM ≈ **$1,500/mo**; the full 17k ≈ ~$12k.
| Item | Cost | Notes |
|---|---|---|
| **Stannp** direct mail (API, ToS-clean) | $48/mo + **$0.73–0.82/piece** | mail is TCPA-safe — the workhorse for the no-phone slice |
| **Forefront CRM** (bundles phone/dialer) or **REsimpli** | $99–$299/mo | pipeline + disposition |
| **Mojo** single-line dialer | $99/mo unlimited min | manual-dial cold cells; expect permanent spam-flag churn |
| **Cold SMS** | — | **largely NON-compliant** cold (one-to-one consent). Reserve for consented/warm only |
| **RVM** (LeadsRain/VoiceDrop) | $0.012–0.05/drop | check SC/NC — some states treat RVM as a call |

---

## Total Cost of Ownership — three tiers (refreshed)
| Model | Monthly | Coverage |
|---|---|---|
| **A. Free + scrub only** | **~$199/mo** (just the litigator/DNC list) | Phase 0 + 0.5 → ~90% find/value/legal-to-send, phone still ~2–45% |
| **B. Smart hybrid** ⭐ | **~$400–700/mo** all-in (Phase 0–2: scrub + Geocodio + RentCast + TrueNCOA + Smarty + Senzing-free + targeted skip) | actionable ~1–3k to ~90% contact+value+distress |
| **C. + full send/work stack** | **~$2,000–4,000/mo** (adds Phase 3 mail/CRM/dialer + variable send) | a running acquisition operation, not just a lead list |

---

## The walls that never move (no phase closes these)
- **Live mortgage payoff** — servicer-only PII (TILA §1639g); per-deal, seller-signed authorization only.
- **SC early court data at scale** — Rule 610 bans scrape + commercial bulk; human-gather lane only.
- **SC exempt-deed sale prices** — §12-24-40 records $0 on exactly our distressed targets.
- **Owner phone ceiling ~50–65% effective mobile** (R7 reality), interior condition, and name-only-unresolvable leads (~4–8%).

## Legal watch-items (confirm with counsel before scaling outbound)
- **NC (corrected R19):** a **bona-fide contract assignment does NOT require a broker license today** (NCREC Nov-2023 bulletin). Unlicensed *brokerage* (Class 1 misd.) is only the red-line conduct: phantom-buyer/no-intent-to-close, marketing the *property* vs your *contract*, negotiating between the parties, or running a buyers-list as a business. **NC H 797 (2025)** would make *solicitation itself* licensed + add a 30-day homeowner cancel right — **passed House 103-0, stuck in Senate, NOT enacted**; re-check before each campaign. Compliant model: real principal buyer · market the contract not the house · disclose to seller · don't hold others' EMD · double-close when aggressive.
- **SC:** if you market only the *contract*, you may be unable to *show the property* (no address/photos/access) — an operational deal-killer beyond licensing. UTPA governs the mail (no gov/court/bank-mimicking pieces).
- **FCRA:** skip-traced data must **not** be used for tenant/credit/employment decisions.
- **TCPA/DNC:** 31-day rescrub, manual-dial cold cells, retain consent records 5 years.

## Sequencing verdict
Ship **Phase 0 (free) + Phase 0.5 (scrub)** now — that alone is the biggest jump and makes the board legally workable for ~$199/mo. Add **Phase 1** as free ceilings bite. Only turn on **Phase 2/3 spend** on the subset you'll actually work. The engine's edge stays the same: free, granular, per-county depth that the paid platforms can't match — with paid dollars spent *only* where free physically can't reach (phone at scale, mail send, and the legal scrub).

---

# v2 additions — folding in the deep-dive (R9–R19, with R18 corrections applied)

## New FREE wins to add to Phase 0 (each verified in the deep-dive)
| Item | Round | Note |
|---|---|---|
| **NC OneMap `AddressNC` point layer** | R4 | Closes address-less for all 11 NC counties. Highest-leverage free geo add. |
| **SeeClickFix Open311 API** | R15 | Free JSON code/nuisance complaints (address+lat/lng) — Anderson, Spartanburg, Gastonia (+Hickory). |
| **FSBO.com** | R15 | Owner name+phone+email in page JSON, no anti-bot — motivated seller *with* free contact. |
| **NC §160A-314 water-sewer liens** (Clerk of Court) | R15 | Recorded lien w/ owner + exact unpaid amount. |
| **HECM reverse-mortgage DOT detection** at ROD | R15 | Free elderly-owner-likely-to-sell signal. |
| **Spartanburg county CAMA_Parcels FS** | R2 | Clean sqft/beds/sale/condition/mailing — use over corrupt SCDOT. |
| **Henderson unmapped fields** (`HEATED_AREA`/sale/owner) | R2 | Already fetched, just not mapped into `_apply_attrs`. |
| **Laurens SC bulk parcel layer** (`Pebble/TaxParcel/MapServer`) | R18 | Owner+Mailing+Sale_Price+Sqft (corrects earlier "cadastral-only"). |
| **Polk NC card** (`assessor_cards/polk_nc.py`) | R2 | Already built — ensure it runs for every Polk lead. |
| ~~Rutherford MapServer/6→7~~ | R18 | **RETRACTED** — Rutherford hosts no parcel service; genuine gap (use OneMap/lrcpwa). |

## Engine SCORING fixes (free, from R10/R14)
- **GLA double-count bug:** ARV uses raw median $/sqft; the marginal size adjustment is only ~30–60% of average $/sqft → derive coefficients from the local sold pool; add **bracketing** + **weighted reconciliation** (not median).
- **Region-tuned + per-strategy max-bid:** replace flat 0.75 with disc **0.60 rural/mobile · 0.65 default · 0.70 metro**, and add `wholetail_mao` + a strategy router (R14).
- **FSD-based 0–100 arv_confidence** (targets PPE10>75%, MdAPE 5–10%) replacing 3-tier HIGH/MED/LOW (R10).
- **Payoff/equity model (R9, corrected R18):** amortize recorded DOT + a **ROD-index reclassification pass** (detect satisfactions/refis/2nds to re-baseline) + **MERS ServicerID** (MIN off MERS-as-mortgagee DOTs) + prepayment-haircut. A recorded satisfaction *strongly indicates* $0 (not exact). SC exempt-deed price is **not** cheaply reconstructable — accept "no recoverable stamp."
- **Foreclosure-stage enum + urgency multiplier** (R11): SC = pre-sale only (no post-sale redemption), lis pendens filed with the **Clerk of Court** (not ROD); **prune-after-confirmation**; MIE sale day varies by court.

## Architecture prerequisite for paid vendors (R16)
- **License-class gating** (`licensing.py`, fail-closed) at the `_slim_raw`/`RAW_KEEP` chokepoint: PUBLIC persist+publish · PERMISSIVE persist/no-bulk-export (RentCast/Realie) · **RESTRICTED_EPHEMERAL** (ATTOM — raw never persists/publishes, only the *derived grade* survives) · INTERNAL_DERIVED. This is the prerequisite that makes adding ATTOM/paid data *compliant*. Plus delta-refresh tiers, per-vendor budget caps, batch-ETL SQLite-by-APN lane, and silent-death (Column 200+0) alarms.
- **Correction:** Senzing free tier is **evaluation/PoC only** (not free production) — its Phase-1 "free entity resolution" is eval-only; production is paid per-DSR.

## Dashboard build spec (R12/R17 — all free, static JS)
Work-Today daily call list (intent-sorted, self-clearing) · intent-score + "why" reasons (default-sort intent-first) · signal feed w/ NEW badge · quick-list preset chips + saved views · drag-drop Kanban from CRM-lite · ROI-by-list KPI table · client-side CSV import.

## Conversion + legal (R13/R19) — operating guardrails
- Per-lead-type timing/scripts (probate day 30–120 mail-first; vacant/absentee 1–3 days; pre-foreclosure 0–60 by equity; sensitivity + SC/NC UDAP).
- **NC assignment = no license today** (only red-line conduct is brokerage; watch H 797). **SC:** market the contract, not the property. **MH-titling:** flag missing affixation affidavit (chattel lien survives closing). **Surviving liens** feed max-bid. **FCRA:** skip data not for tenant/credit decisions.

_Roadmap v2 sequencing unchanged: Phase 0 free (now bigger) → 0.5 DNC scrub $199 → 1 cheap paid (Geocodio/RentCast/TrueNCOA/Smarty; Senzing only for eval) → 2 targeted skip → 3 send. Add the license-class layer BEFORE any RESTRICTED vendor (ATTOM)._
