# Where the Data Lives — every confirmed gap + every missing signal, sourced

Written 2026-08-13. Scope: for the 30-county NC+SC footprint (Horry excluded),
for each confirmed coverage GAP/WALL and for each motivated-seller SIGNAL the
engine does not yet have, answer one question: **does a source exist, and where
does the data physically live** — free-alternate, manual/FOIA, or paid vendor.

This builds on (does not restate) the free/manual analysis already in
`coverage_gaps.md`, `walls_register.md`, `gap_ledger.md`,
`road_to_100_alternates_courts.md`, `_rod_tax.md`, `_signals.md`, and the costed
`path_to_100*` blueprint. The NEW layer here is the **paid-vendor mapping**: the
operator asked where the info is, not only where the free path is, so paid
aggregators are in scope.

**Distinction that runs through both tables:**
- **ACCESS-GAP** — the data provably exists; it is walled (ToS/CAPTCHA/token),
  FOIA-only, or paid. A check written to the right vendor closes it.
- **TRUE VOID** — the data is not collected/published anywhere for this
  footprint by anyone, free or paid. No check closes it; only a proxy exists.

Paid-vendor coverage verified live 2026-08-13: **Regrid** carries all 46 SC
counties incl. the 4 walled ones (Cherokee/Union/Oconee/Anderson);
**PropertyRadar**, **ATTOM**, **DataTree/First American** are nationwide incl.
NC+SC. **TaxNetUSA is TX+FL only — it does NOT cover this footprint** (do not
propose it, despite the task's example list).

Cost legend: $ = <$100/mo · $$ = $100–500/mo · $$$ = $500–2k/mo or enterprise ·
¢ = per-record/per-report metered · FOIA = records-request fee only.

---

## PART A — the confirmed gaps / walls, and where each one's data lives

| # | Gap / wall | Data exists? | Where the data lives (specific domain / vendor) | Access | Closes gap? | Notes |
|---|---|:--:|---|---|---|---|
| A1 | **SC resolver walls — Cherokee, Union** (name→owner+situs; both fully walled) | YES | **Regrid** `app.regrid.com/us/sc/cherokee`,`/union` (owner+boundary, sourced from county assessor); also **PropStream**, **DataTree**, **ATTOM**, **PropertyRadar** `/coverage/south-carolina` | paid $ (Regrid app/API) → $$$ (ATTOM/DataTree bulk) | **FULLY** | Regrid is the cheapest full fix — licenses the same assessor owner table SCDOT token-walled. Closes S12 + every downstream signal for these two counties. |
| A2 | **SC resolver — Oconee (situs-missing)** owner-only layer, no property address | YES | Regrid / PropStream / DataTree Oconee parcel record carries owner **and** situs together | paid $–$$ | **FULLY** | County-native layer has owner but no situs; the aggregators join both. |
| A3 | **SC resolver — Anderson (owner-masked)** situs+value present, owner null | YES | Regrid / PropStream / DataTree Anderson owner field (unmasked in the licensed assessor feed); paid ROD `americanlandrecords.com` also carries grantee | paid $–$$ (or free ROD candidate, unmapped) | **FULLY** | Aggregators carry the owner the public GIS masks. Verify `americanlandrecords.com` first as a free lane. |
| A4 | **NC state/federal tax liens (S5)** — no free NC registry; state (SoS) + county-ROD paths both walled | YES | **NC SoS Data Subscription** (paid bulk UCC/federal-tax-lien, the SoS's own product); **DataTree**/**ATTOM** involuntary-lien + federal-tax-lien search; **Accurint/LexisNexis** & **TLOxp** lien search | paid $$ (SoS sub) / ¢ (DataTree/Accurint per-search) | **PARTIAL→FULLY** | SoS ToS forbids scraping but SELLS the bulk file — that is the compliant paid path. DataTree/ATTOM carry recorded federal + state liens nationwide. Narrow signal (mostly entity/LLC liens). |
| A5 | **SC divorce (S7)** — FCCMS Rule 610 ToS, statewide | PARTIAL | SC Family Court records are public-but-access-restricted; **UniCourt / LexisNexis CourtLink** cover SC common-pleas but **generally NOT FCCMS family court** (Rule 610 restricts bulk); no vendor reliably resells SC divorce | manual-save (operator) only; paid = thin/none | **NO** (manual only) | Closest to a TRUE VOID on the automated/paid side: the restriction is on the index itself, so paid aggregators inherit the same wall. Manual FCCMS save-lane is the only path. |
| A6 | **Senior/disabled/veteran exemption (S11)** — FOIA-only except Buncombe (roster) + Beaufort/Pender (parcel field) | YES | County tax office **FOIA** (NC G.S. 105-277.1 / 105-277.1C roll); paid assessor-extract vendors (**DataTree**, **ATTOM**, **CoreLogic**) sometimes carry a homestead/tax-relief flag but usually suppress the elderly/disabled sub-code | FOIA (clean) / paid $$$ (partial, flag may be absent) | **PARTIAL** | The specific age/disability code is PII-suppressed even in most licensed bulk. FOIA per county is the reliable close. Do not chase in GIS. |
| A7 | **NC eCourts Smart Search — SP foreclosure filings (behind AWS-WAF)** | YES | Free notice lane already covers existence (`ncnotices.com` + ROD S/T + law-firm dockets). Paid depth: **ATTOM foreclosure feed**, **PropStream** pre-foreclosure/auction, **RealtyTrac**, **Foreclosure.com** — carry NC SP with address+parcel+sale date | free (name/case) / paid $$ (address-complete) | **FULLY** | Free lane gives name+case+county; the walled BODY (address/parcel/sale-date) closes via manual-save OR any paid foreclosure feed. |
| A8 | **NC eCourts Smart Search — estates/probate (WAF + CAPTCHA)** | YES | Free: Column API + `ncnotices` notice-to-creditors + obits already cover it. Paid: **US Probate Leads** (per-county subscription), **DataTree** probate/heir search | free (covers it) / paid $ (US Probate Leads) | **FULLY (free)** | Already substantially solved free; paid only adds PR mailing completeness. |
| A9 | **Municipal code-enforcement / vacant / demolition — FOIA-walled cities** (Shelby, Morganton, Forest City, Wilmington, Charleston city, Gaffney, SC-coastal EnerGov, rural unincorporated) | PARTIAL | **FOIA** to each city code/building dept (active-violations, condemnation, demo lists) is the only source of the CODE-CASE itself. Paid vendors do NOT aggregate code enforcement; they DO carry the **vacancy** proxy (USPS vacancy via **ATTOM**, **PropStream**, **Melissa**) | FOIA (code cases) / paid $$ (vacancy proxy only) | **PARTIAL** | Code-violation case lists = FOIA/void for automation. Vacancy (a strong substitute) is a paid strength. Split the signal: buy vacancy, FOIA the violations. |
| A10 | **Currituck + thin coastal (Dare/Hyde) — geometry-only GIS, CAPTCHA tax/ROD** | YES | **Regrid**/**ATTOM**/**PropStream**/**DataTree** carry Currituck+Dare+Hyde owner+mailing+assessed+tax — the exact fields the open REST layers omit | paid $–$$$ | **FULLY** | The near-beach GATE (config) is separate and free to widen; the underlying owner/tax VOID for these counties closes only via a paid parcel feed. |
| A11 | **Recorded liens — HOA/mechanic/judgment (S9)** — every ROD front-end walled; ~10 leads footprint-wide | YES | **DataTree** (99% HOA + lien releases, recorded doc images), **ATTOM** involuntary-lien feed, **Accurint/TLOxp** lien search; free = ROD rebuild (blocked) | paid ¢/$$$ | **FULLY** | DataTree explicitly advertises 99% HOA-lien + assignment/release coverage nationwide — the single cleanest close for the whole S9 column. |
| A12 | **NC delinquent-tax roll holes — Gaston/Polk/Transylvania (newspaper subset only), Mitchell (HTTP 523, no host), Anderson SC (ACPASS login), Rutherford/Cherokee/Union balance walls** | YES | Paid assessor+tax vendors (**DataTree**, **ATTOM**, **CoreLogic**, **PropStream** tax-delinquent list) carry the full delinquent roll + balance for all these counties | paid $–$$$ | **FULLY** | Free lane maxes at the newspaper ad subset; the full 105-369 roll + balance number lives in the paid assessor extracts. PropStream's "tax delinquent" list is the cheapest close. |

---

## PART B — motivated-seller signals BEYOND the current 12, and where each lives

Current 12 (for reference): foreclosure, lis-pendens, sale-rosters/upset,
tax-delinquency, tax-liens, probate/estates, divorce, bankruptcy, recorded-liens,
code-enforcement/vacant, senior-exemption, absentee/cash-buyer.

| Signal (new) | Source exists? | Where the data lives (domain / vendor) | Access | Notes |
|---|:--:|---|---|---|
| **Death / obituary** | YES | Free: Gannett obits + funeral-home RSS (BUILT), Legacy.com, tributes.com. Paid: **LexisNexis** deceased/SSDI, **ATTOM** does not carry it | free (built) / paid ¢ | Name-only → feeds heir-parcel index. Already partly wired. Free suffices. |
| **Eviction filings** | PARTIAL | NC = eCourts (WAF wall); SC = magistrate court (per-court, mostly walled). Paid: **LexisNexis Risk**, **TransUnion SmartMove**, court-data resellers — but tenant-screening data is DPPA/FCRA-gated and rarely property-keyed to the OWNER | manual / paid ¢ (credentialed, FCRA) | Landlord-distress angle. Data exists but is FCRA-restricted and keyed to tenant not owner — weak fit, effectively a wall for this use. |
| **High-equity / free-and-clear** | YES | **PropStream**, **PropertyRadar**, **DataTree**, **ATTOM** all compute equity = AVM − open mortgage balance. Free proxy: assessed value + no recent deed-of-trust | paid $–$$$ | Paid strength. This is the single most-wanted "would they sell" filter and it is cheap on PropStream. |
| **Absentee / out-of-state owner** | YES | Free: GIS owner-mailing vs situs mismatch (partly wired). Paid: **PropStream**/**Regrid**/**ATTOM**/**PropertyRadar** all flag absentee + out-of-state directly | free proxy / paid $ | Closes fully free where a parcel layer exists; paid fills the walled/geometry-only counties. |
| **Inherited / heir property** | YES | Free: `nc_heir_estate_parcels` GIS name-sweep + probate notices (BUILT). Paid: **US Probate Leads**, **PropStream** probate list, **DataTree** heir search | free (built) / paid $ | Well-covered free; paid adds depth in walled counties. |
| **Long-vacant / zombie** | YES | **USPS vacancy indicator** resold by **ATTOM**, **PropStream**, **Melissa**, **BatchData**. Free proxy: code-enf vacant registries (Spartanburg/Hendersonville BUILT) + utility-off | paid ¢/$$ | USPS vacancy is the authoritative national vacant flag; only sold through licensed resellers. |
| **Job-loss / WARN layoffs** | YES | **Free & public**: NC Commerce WARN list (`commerce.nc.gov`), SC DEW WARN list (`dew.sc.gov`). Statewide, no wall | free | But NOT property-keyed — employer address only, not employee homes. Macro signal, not a lead list. Can't join to a parcel → low direct value. |
| **Structural damage / storm / insurance claim** | PARTIAL | Storm/disaster free: FEMA, NOAA, `asheville_helene` (BUILT). Insurance CLAIMS = carrier PII, sold only in aggregate risk products (**ATTOM/CoreLogic hazard**), never per-property claim | free (storm) / paid $$$ (hazard, not claims) | Storm-damage footprint = free & buildable. Individual insurance claim = **TRUE VOID** (PII). |
| **Expired / withdrawn MLS listing** | YES | **PropStream** carries MLS status incl. expired/withdrawn/cancelled; **Realtor**/**Redfin** feeds; direct MLS via an agent | paid $ (PropStream) | "Tried to sell, failed" = strong motivation. PropStream is the practical source (no direct MLS license needed). |
| **FSBO (for sale by owner)** | YES | **Zillow FSBO**, **FSBO.com**, **Craigslist**, **Facebook Marketplace**; paid aggregation via **PropStream**/**BatchLeads** FSBO lists | free scrape / paid $ | Scrapeable free; paid saves the plumbing. |
| **Reverse-mortgage / senior (HECM)** | YES | HECM = an FHA deed-of-trust recorded at ROD (lender = HUD/FHA). **DataTree**/**ATTOM** loan-type search flags HECM; free = ROD (walled) | paid ¢/$$ | Elderly + tappable-equity proxy. Lives in the paid mortgage-type field. |
| **Medical debt / liens** | PARTIAL | Historically recorded at ROD; but medical liens/judgments are being removed from public credit + many states restrict. **DataTree/ATTOM** carry recorded judgment liens generally, not "medical" tagged | paid ¢ (untagged) / mostly void | Cannot isolate "medical" reliably — folded into general judgment-lien (A11). Near-**VOID** as a distinct signal. |
| **HOA super-lien** | YES | **DataTree** (99% HOA-lien coverage) + **ATTOM**; free = ROD-walled | paid ¢/$$$ | Same close as recorded-liens A11 — DataTree is the source. |
| **Pre-probate (elderly + sole owner)** | DERIVED | No single source — CONSTRUCT it: age proxy (exemption roll / voter file) + sole-owner deed + owner-occupied. Inputs: FOIA exemption + **DataTree/Regrid** deed vesting | build from paid+FOIA inputs | Not a feed anywhere; it is a MODEL over other signals. Highest-intent, lowest-availability — the "would they sell before they die" cut. |

---

## Access-gaps vs true voids — the tally

**Part A (12 gaps/walls):**
- **ACCESS-GAP (data exists, obtainable free/FOIA/paid): 11** — A1, A2, A3, A4,
  A6, A7, A8, A9, A10, A11, A12. Every one closes with either a FOIA request or a
  paid parcel/tax/lien feed.
- **TRUE VOID / no obtainable source: 1** — **A5 SC divorce**. The Rule 610
  restriction sits on the index itself, so even paid court-data vendors inherit
  the wall; only the per-lead manual FCCMS save-lane exists. (A6 exemption and A9
  code-cases are PARTIAL access-gaps — FOIA-obtainable, just not automatable.)

**Part B (15 new signals):**
- **Obtainable (free or paid): 12** — death, high-equity, absentee, heir,
  long-vacant, WARN(*), storm-damage, expired-MLS, FSBO, reverse-mortgage,
  HOA-lien, pre-probate(derived). (*WARN is free but not parcel-joinable.)
- **PARTIAL / VOID: 3** — eviction (FCRA-gated, tenant-keyed), insurance-claims
  (carrier PII = void; storm is the free substitute), medical-debt (untaggable =
  near-void, folds into judgment liens).

**Bottom line:** of ~27 gaps/signals examined, roughly **23 are ACCESS-gaps** a
purchase or FOIA closes, and only **~4 are true voids** (SC divorce index,
per-property insurance claims, medical-debt tagging, and utility-shutoff which no
vendor resells). The footprint is far more a "who-do-we-pay" problem than a
"data-doesn't-exist" problem.

---

## Ranked shortlist — the single source that closes the most at once

1. **Regrid — statewide SC (+NC) parcel/owner license.** ~$ (app) to low-$$$
   (bulk). **One buy closes all four SC resolver walls (Cherokee, Union, Oconee
   situs, Anderson owner) simultaneously** — the single biggest lever on the
   ~25–30% resolver ceiling — and delivers absentee + owner-mailing for Currituck
   and the geometry-only coastal counties. Cheapest fix for the highest-value
   structural gap. **Buy first.**

2. **PropStream — $99/mo, nationwide.** In one $99 subscription closes, for all
   30 counties at once: **high-equity/free-and-clear, absentee, tax-delinquent
   roll+balance (A12), pre-foreclosure/foreclosure depth (A7), vacant (A9 proxy),
   expired-MLS, FSBO, probate/heir**. The best breadth-per-dollar and the fastest
   way to convert a dozen PARTIAL signals to GOOD. Overlaps Regrid on owner data
   but adds the equity/MLS/vacancy layers Regrid lacks. **Buy second.**

3. **DataTree (First American) — metered/enterprise.** The recorded-document
   spine: **99% deeds/mortgages/foreclosures, 99% HOA + involuntary liens (A11 +
   HOA-super-lien), recorded-doc images, loan-type (reverse-mortgage/HECM)**.
   Closes the entire S9 recorded-lien column and the loan-level signals that
   PropStream summarizes but doesn't document. Use per-report, not subscription,
   for HOT leads. **Buy third / à la carte.**

4. **FOIA program (not a vendor) — county tax + city code offices.** The only
   clean close for **A6 senior/disabled exemption** and **A9 code-enforcement
   cases** — both PII/records-request by nature, obtainable but not purchasable.
   Standing quarterly FOIA to each county's exemption roll + each FOIA-walled
   city's violation/condemnation list. Near-zero cost, just process.

**What NONE of them buy:** SC divorce (A5), per-property insurance claims,
utility-shutoff — the true voids. Accept these as manual/proxy-only.

Not recommended for this footprint: **TaxNetUSA** (TX+FL only, confirmed
2026-08-13) — despite appearing in the task's example vendor list, it does not
cover a single footprint county.
