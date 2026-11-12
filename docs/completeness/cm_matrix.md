# PER-COUNTY SIGNAL COVERAGE MATRIX — live board, 2026-08-04

Source: `/Users/cashhigh/foreclosure-scraper/docs/listings.json` (144 MB, **25,552 leads**, read-only). Scoring script: `/private/tmp/claude-502/-Users-cashhigh-Desktop/f9f41c0e-c1d7-4991-a803-581317d111fe/scratchpad/matrix.py`; raw output `matrix_out.json` in the same dir. No network calls made.

**24,935 of 25,552 leads (97.6%) fall inside the 18-county footprint.** The other 617 are Charleston (306), Brunswick (112), Onslow (57), Dare (36), Pender (34), Carteret (31), Horry (18), and 17 with a null county.

## Key mapping actually used (derived by inspecting the board, not assumed)

`raw` has 100 distinct keys. Signals were derived from the union of: `listing_type`, `source` slug, every `raw.also_seen_in[].source` slug, `raw.distress_stack.signals`, `raw.signal_stack.signals`, `raw.flags`, `raw.life_events`, and specific enricher keys.

| Signal | Derivation |
|---|---|
| foreclosure_sale | `listing_type∈{foreclosure_sale,auction}` ∪ signals `foreclosure_sale`/`auction` ∪ `raw.nod` |
| upset_bid | `raw.upset_bid` ∪ signal `upset_bid` ∪ top-level `upset_bid_deadline` |
| lis_pendens/pre-fcl | `listing_type=lis_pendens` ∪ signal `lis_pendens` ∪ flag `preforeclosure` ∪ `raw.lis_pendens_resolution` |
| tax_delinq_current | `raw.tax_owed.kind∈{delinquent_tax,state_tax_lien}` ∪ signals `tax_delinquent`/`tax_lien` ∪ `listing_type=tax_lien` ∪ `raw.{nc_county_pdf_delinquent_tax,nc_ptscloud_delinquent_tax,sc_tax_delinquent}` ∪ 8 delinquent-tax source slugs |
| tax_delinq_multiyr | `raw.tax_owed.years` with len>1 |
| tax_sale | `listing_type=tax_sale` ∪ signal `tax_sale` |
| forfeited/county-owned | sources `oconee_forfeited_land`, `spartanburg_flc`, `terry_howe_flc`, `sc_county_rosters`, `nc_govdeals_real_property` ∪ `tax_owed.kind=flc_opening_bid` |
| probate/estate | `listing_type∈{probate_notice,estate_lead}` ∪ signals `probate`/`probate_deed`/`probate_notice` ∪ `life_events∩{estate_probate,trust,life_estate}` ∪ `relationship_signal.kind=probate` ∪ probate sources |
| heirs | `life_events` has `multiple_heirs` ∪ source `nc_heir_estate_parcels` |
| divorce | `listing_type=divorce_notice` ∪ signal `divorce` ∪ `raw.divorce.case_count>0` ∪ `raw.nc_ecourts.cause` contains "Divorce" ∪ `relationship_signal.kind=divorce` ∪ source `nc_ecourts_divorce` |
| bankruptcy | `listing_type=bankruptcy` ∪ signal `bankruptcy` ∪ `raw.bankruptcy` ∪ `raw.courtlistener` ∪ courtlistener sources |
| code_violation | `raw.code_enforcement` truthy ∪ signal `code_enforcement` |
| condemned/unfit | `raw.condemned` ∪ flags `condemned`/`uninhabitable` ∪ source `spartanburg_condemned` ∪ signals `helene_unsafe`/`helene_restricted` |
| vacant | flags `vacant`/`abandoned` ∪ source `spartanburg_vacant` |
| elderly/deferral | `listing_type=elderly_disabled` ∪ `life_events∩{elderly,disabled,disabled_veteran,blind}_exemption` ∪ signals `senior_exemption`/`deferral_rollback` ∪ `raw.gis_exempt` ∪ source `buncombe_elderly` |
| jail/incarceration | `raw.incarceration` ∪ signals `incarceration`/`incarcerated_owner` ∪ source `jail_bookings` |
| obituary/death | any source slug containing `obituar` (`public_notices.gannett_obituaries`) |
| storm/disaster | `raw.storm_damage` ∪ `raw.fema_repetitive_loss` ∪ signals `storm_damage`/`helene_restricted`/`helene_unsafe` ∪ source `asheville_helene` |
| absentee/out-of-state | `owner_mailing.absentee|out_of_state` ∪ `distress_stack.absentee|out_of_state` ∪ signals `absentee_owner`/`out_of_state_owner` ∪ flag `absentee_owner` ∪ `skip_trace.absentee_owner` |
| cash-buyer/investor deed | source `national.cash_buyer_deeds` |
| HOA/muni/other lien | `listing_type=hoa_sale` ∪ `raw.liens` ∪ sources `sc_state_tax_lien`, `charleston_mie` |
| sales-comps | any of `comp_median_ppsf`, `recorded_comps`, `comp_median_ppsf_recorded`, `foreclosure_sold_comp_summary` |

**Two corrections applied before scoring — both are real board bugs:**

1. **`probate_estate` signal is contaminated.** 3,537 of its 4,755 occurrences come from `counties_nc.buncombe_elderly` (`listing_type=elderly_disabled`) — an elderly/disabled *exemption* roster, not probate. 3,535 of the 4,755 carry no probate-ish `life_event` at all. I dropped `probate_estate` from the probate predicate. Uncorrected, Buncombe probate reads **3,943**; corrected it is **445**.
2. **`raw.owner_mailing` is a bare string in 5,100 records** (all Spartanburg) instead of the dict shape used elsewhere (9,442 dicts). The dict-only reader undercounted Spartanburg mailing coverage as 5.0%; corrected it is 62.2%.

## THE MATRIX (cells = lead count; `-` = zero; `n/a` = statute does not exist in that state)

Column key: FCL=foreclosure_sale · UPS=upset_bid · LP=lis_pendens/pre-fcl · TXD=tax_delinq current · TXM=tax_delinq multiyear · TXS=tax_sale · FLC=forfeited/county-owned · PRB=probate/estate · HEI=heirs · DIV=divorce · BKR=bankruptcy · CODE=code_violation · CND=condemned/unfit · VAC=vacant · ELD=elderly/deferral · JAIL=jail/incarceration · OBIT=obituary/death · STRM=storm/disaster · ABS=absentee/out-of-state · CBD=cash-buyer deed · LIEN=HOA/muni/other lien · COMP=sales-comps

| County | Leads | FCL | UPS | LP | TXD | TXM | TXS | FLC | PRB | HEI | DIV | BKR | CODE | CND | VAC | ELD | JAIL | OBIT | STRM | ABS | CBD | LIEN | COMP |
|---|--:|--:|--:|--:|--:|--:|--:|--:|--:|--:|--:|--:|--:|--:|--:|--:|--:|--:|--:|--:|--:|--:|--:|
| Buncombe NC | 5902 | 39 | 13 | 60 | 1203 | – | – | – | 445 | 101 | 40 | 70 | – | 172 | – | 3680 | 3 | 45 | 305 | 1822 | – | – | 3460 |
| Henderson NC | 1321 | 14 | 16 | 47 | 1087 | – | – | – | 158 | 73 | 3 | 48 | – | – | 1 | 1 | 1 | 13 | – | 639 | – | – | 1313 |
| Gaston NC | 299 | 69 | 8 | 8 | 2 | – | 1 | – | 87 | 67 | 1 | 3 | – | 1 | 1 | 1 | 1 | 3 | – | 75 | – | – | 297 |
| Cleveland NC | 165 | 18 | 1 | 34 | 5 | – | 1 | – | 67 | 54 | 1 | 33 | – | – | 3 | – | 1 | 5 | – | 39 | – | – | 157 |
| Rutherford NC | 182 | 10 | 3 | 2 | 5 | – | 8 | – | 138 | 134 | 1 | 2 | – | – | – | – | 1 | 2 | – | 26 | – | – | 181 |
| Burke NC | 172 | 24 | 3 | 21 | 1 | – | – | – | 62 | 52 | – | 16 | – | – | 1 | – | 3 | – | – | 122 | – | – | 172 |
| Lincoln NC | 335 | 16 | 4 | 24 | 200 | – | – | – | 75 | 48 | – | 24 | – | – | 1 | – | – | – | – | 49 | – | – | 331 |
| McDowell NC | 2258 | 12 | 8 | 31 | 2090 | – | – | – | 160 | 83 | 1 | 26 | – | – | – | – | – | – | – | 2169 | 29 | – | 1891 |
| Polk NC | 167 | 2 | 2 | 25 | – | – | – | – | 104 | 96 | 1 | 25 | – | – | – | – | 1 | – | – | 25 | – | – | 73 |
| Transylvania NC | 190 | 4 | 7 | 46 | 5 | – | – | – | 81 | 75 | 9 | 14 | – | – | 1 | – | – | – | – | 35 | – | – | 185 |
| Mitchell NC | 131 | 3 | 1 | 13 | – | – | – | – | 77 | 79 | – | 16 | – | – | 2 | – | – | – | – | 102 | – | – | 7 |
| Spartanburg SC | 8919 | 106 | n/a | 1102 | 2172 | – | 2188 | 15 | 455 | 331 | 12 | 75 | 650 | 1670 | 3459 | – | 2 | 25 | 44 | 380 | – | 6 | 4665 |
| Anderson SC | 1097 | 66 | n/a | 445 | 1 | – | 5 | 2 | 42 | 2 | 8 | 88 | – | – | 1 | – | 2 | 21 | – | 216 | – | 1 | 1036 |
| Pickens SC | 871 | 24 | n/a | 224 | 37 | – | 1 | – | 193 | 28 | 2 | 34 | – | – | – | – | 1 | – | 1 | 168 | – | 2 | 709 |
| Oconee SC | 982 | 16 | n/a | 175 | 130 | – | 505 | 512 | 30 | 5 | 38 | 37 | – | – | – | – | – | – | – | 537 | – | – | 406 |
| Cherokee SC | 565 | 15 | n/a | 259 | – | – | – | – | 4 | – | – | 1 | – | – | – | – | 1 | – | – | – | – | – | 527 |
| Union SC | 477 | 6 | n/a | 145 | – | – | – | – | 4 | 6 | – | 25 | – | – | – | – | – | – | – | 30 | – | – | 450 |
| Laurens SC | 902 | 19 | n/a | 292 | 3 | – | 29 | 33 | 81 | 80 | 6 | 48 | – | – | 1 | – | 2 | – | – | 103 | – | 1 | 722 |
| **Footprint total** | **24935** | **463** | **66** | **2953** | **6941** | **0** | **2738** | **562** | **2263** | **1314** | **123** | **585** | **650** | **1843** | **3471** | **3682** | **19** | **114** | **350** | **6537** | **29** | **10** | **16582** |

`upset_bid` is marked n/a for SC because the upset-bid window is NC statute (NCGS §45-21.27, cited in the board's own `raw.upset_bid.statute`); SC judicial foreclosure has no equivalent. All 66 upset-bid leads are NC — correct behavior, not a gap.

## Per-county score: signals present / signals possible

| County | Score | Leads |
|---|---|--:|
| Spartanburg SC | **18/21** | 8919 |
| Gaston NC | **16/22** | 299 |
| Buncombe NC | 15/22 | 5902 |
| Anderson SC | 15/21 | 1097 |
| Henderson NC | 14/22 | 1321 |
| Cleveland NC | 14/22 | 165 |
| Laurens SC | 14/21 | 902 |
| Rutherford NC | 13/22 | 182 |
| Pickens SC | 13/21 | 871 |
| Burke NC | 11/22 | 172 |
| McDowell NC | 11/22 | 2258 |
| Transylvania NC | 11/22 | 190 |
| Oconee SC | 11/21 | 982 |
| Lincoln NC | 10/22 | 335 |
| Polk NC | 10/22 | 167 |
| Mitchell NC | 9/22 | 131 |
| Union SC | **7/21** | 477 |
| Cherokee SC | **6/21** | 565 |

Board-wide breadth (counties of 18 carrying the signal at all): `sales-comps` 18, `foreclosure_sale` 18, `lis_pendens` 18, `probate/estate` 18, `bankruptcy` 18, `heirs` 17, `absentee` 17, `tax_delinq` 14, `divorce` 13, `jail` 12, `upset_bid` 11(of 11 NC), `vacant` 10, `tax_sale` 8, `obituary` 7, `forfeited` 4, `HOA/muni lien` 4, `condemned` 3, `elderly` 3, `storm` 3, `code_violation` 1, `cash-buyer deed` 1, **`tax_delinq_multiyear` 0**.

## 20 worst county+signal gaps

Gap score = county lead volume × (share of the 18 footprint counties that DO carry that signal). N/A cells excluded.

| # | Score | County | Leads | Missing signal | Counties that have it |
|--:|--:|---|--:|---|---|
| 1 | 3279 | Buncombe NC | 5902 | vacant | 10/18 |
| 2 | 2623 | Buncombe NC | 5902 | tax_sale | 8/18 |
| 3 | 1505 | McDowell NC | 2258 | jail/incarceration | 12/18 |
| 4 | 1486 | Spartanburg SC | 8919 | elderly/deferral | 3/18 |
| 5 | 1312 | Buncombe NC | 5902 | forfeited/county-owned | 4/18 |
| 6 | 1312 | Buncombe NC | 5902 | HOA/muni/other lien | 4/18 |
| 7 | 1254 | McDowell NC | 2258 | vacant | 10/18 |
| 8 | 1004 | McDowell NC | 2258 | tax_sale | 8/18 |
| 9 | 878 | McDowell NC | 2258 | obituary/death | 7/18 |
| 10 | 655 | Oconee SC | 982 | jail/incarceration | 12/18 |
| 11 | 587 | Henderson NC | 1321 | tax_sale | 8/18 |
| 12 | 546 | Oconee SC | 982 | vacant | 10/18 |
| 13 | 534 | Cherokee SC | 565 | heirs | 17/18 |
| 14 | 534 | Cherokee SC | 565 | absentee/out-of-state | 17/18 |
| 15 | 502 | McDowell NC | 2258 | forfeited/county-owned | 4/18 |
| 16 | 502 | McDowell NC | 2258 | HOA/muni/other lien | 4/18 |
| 17 | 496 | Spartanburg SC | 8919 | cash-buyer/investor deed | 1/18 |
| 18 | 484 | Pickens SC | 871 | vacant | 10/18 |
| 19 | 439 | Cherokee SC | 565 | tax_delinq_current | 14/18 |
| 20 | 408 | Cherokee SC | 565 | divorce | 13/18 |

Ranks 13/14 are the standouts by breadth: **Cherokee SC is the only footprint county with zero heirs and zero absentee leads out of 18** — it has 565 leads that are almost entirely lis_pendens (259) with no owner-side enrichment at all.

## Contactability per county

| County | Leads | % with mailing | % with phone | % unreachable |
|---|--:|--:|--:|--:|
| McDowell NC | 2258 | 92.6 | 23.9 | **6.2** |
| Henderson NC | 1321 | 89.3 | 23.7 | 8.8 |
| Buncombe NC | 5902 | 84.1 | **45.8** | 9.1 |
| Spartanburg SC | 8919 | 62.2 | 0.0 | 37.8 |
| Lincoln NC | 335 | 59.1 | 28.4 | 30.7 |
| Oconee SC | 982 | 56.6 | 0.0 | 43.4 |
| Cleveland NC | 165 | 46.7 | 7.9 | 53.3 |
| Gaston NC | 299 | 43.8 | 8.7 | 55.9 |
| Burke NC | 172 | 37.8 | 20.3 | 52.3 |
| Anderson SC | 1097 | 26.3 | 0.0 | 73.7 |
| Polk NC | 167 | 24.0 | 17.4 | 64.1 |
| Mitchell NC | 131 | 20.6 | 16.0 | 66.4 |
| Pickens SC | 871 | 19.7 | 0.0 | 80.3 |
| Transylvania NC | 190 | 18.9 | 14.7 | 70.5 |
| Rutherford NC | 182 | 18.7 | 5.5 | 81.3 |
| Laurens SC | 902 | 14.1 | 0.0 | 85.9 |
| Union SC | 477 | 9.4 | 0.0 | 90.6 |
| Cherokee SC | 565 | 0.0 | 0.0 | **100.0** |

Mailing = `owner_mailing` (dict `.mailing` **or** bare string) ∪ `skip_trace.owner_mailing_address` ∪ `sos_agent.best_contact_address` ∪ `nc_ptscloud_delinquent_tax.mailing.addr`. Phone = `owner_phone.phone` ∪ `skip_trace.phone_numbers`. Unreachable = neither.

**Phone is 0.0% in every SC county, exactly.** All 3,840 phone numbers on the board come from a single source: `ncsbe_voter` (NC State Board of Elections voter file). `skip_trace.phone_numbers` is empty in every one of its 193 records, in both states. This is a structural wall (SC has no free voter file with phones), not a broken scraper.

## Empty ≠ broken — the distinction

**Genuinely absent / structurally impossible (not a bug):**
- `upset_bid` in all 7 SC counties — NC-only statute.
- Phone in all 7 SC counties — no free SC voter-phone equivalent exists.
- `tax_sale` and `forfeited/county-owned` skew SC because the Forfeited Land Commission is an SC institution; NC's analogue (`nc_govdeals_real_property`) exists but returned only 2 leads board-wide.

**Broken or unbuilt (real gaps):**
- **`tax_delinq_multiyear` = 0 in all 18 counties.** Only 2 records board-wide have a `tax_owed.years` array, and 5,077 of 5,078 `tax_owed` records have `year: null`. The delinquent-tax parsers capture a single `principal_tax_due` balance and discard year multiplicity entirely. Multi-year delinquency — the strongest tax signal — is not on the board at all.
- **`code_violation` exists in exactly 1 county** (Spartanburg, 650) and **`condemned` in 3**. Asheville code-enforcement was built per the gap ledger but contributes 0 to Buncombe here.
- **`vacant` exists in exactly 1 county** (Spartanburg's GIS vacant layer, 3,307 + 152 flag-derived). Buncombe's 5,902 leads carry zero vacancy signal.
- **`elderly/deferral` is a Buncombe-only artifact** — 3,680 of 3,682 come from `counties_nc.buncombe_elderly`. Henderson has 1. Spartanburg has 0 despite 8,919 leads.
- **`jail/incarceration` = 19 leads across the whole footprint**, all `confidence: name_only_low` name matches. `national.jail_bookings` produced 4 primary leads and is flagged `carryover.stale: "source produced 0 this run; prior run had 480"` — that source is currently dead, not empty.
- **`cash-buyer/investor deed` exists in 1 county** (McDowell, 29). No investor-deed mining anywhere else.
- **`HOA/muni/other lien` = 10 leads footprint-wide.** Effectively unbuilt.
- **SC delinquent tax is Spartanburg-only in practice** (2,172 of 2,343 SC tax-delinquent leads). Cherokee and Union have zero. Matches the known qPayBill parcel-mismatch wall for non-Spartanburg SC counties.
- **NC delinquent tax collapses outside Buncombe/McDowell/Henderson/Lincoln.** Polk 0, Mitchell 0, Burke 1, Gaston 2, Cleveland 5, Rutherford 5, Transylvania 5.

**Fixable today, with measured yield:**
- The Spartanburg bare-string `owner_mailing` bug (5,100 records) never reaches the absentee logic: **5,002 of them were never absentee-flagged.** Parsing the state token out of those strings yields **442 confirmed out-of-state owners** immediately, and comparing mailing to situs yields **3,912 mail-address-differs-from-situs candidates** (477 same, 711 with no situs to compare). Spartanburg's current absentee count is 380 out of 8,919 leads — this one fix roughly multiplies it by 10.
- Un-contaminating `probate_estate` (it tags the entire Buncombe elderly roster as probate) removes 3,535 false probate leads and makes the probate column trustworthy for scoring/routing.