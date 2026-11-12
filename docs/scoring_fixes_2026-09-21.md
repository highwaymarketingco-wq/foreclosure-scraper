# Scoring and signal-logic fixes, 2026-09-21

Implements the findings in `docs/audit_signal_logic_2026-09-21.md` and `docs/AUDIT_2026-09-21.md` under the owner-delegate decisions 1 to 10. Working tree only; nothing is committed. Changes that need files owned elsewhere (main.py, web_artifact.py, board_persist.py, the dashboard) are in `docs/handoff_scorer_to_others_2026-09-21.md`.

## 1. What the owner will see: before and after on 20,000 board rows

**Method.** One pass over `docs/listings.json.gz` with `board_stream.iter_board_rows`; every 8th row kept until 20,000 were collected (file rows 0 to 159,992); the sample was scored in chunks of 2,500 by the committed HEAD scorer (`git show HEAD:src/foreclosure_scraper/distress_score.py`, commit 84bca51, which already has the 4bc5792 debt fix and the 99dd616 context-only list) and by the new scorer, each on its own copy of the same rows, then only counters were kept. Nothing was written, `load_board` was not called, the prior-run price index was off on both sides (`previous_path` did not exist), `today` was the real date. Every stored `distress_stack` was removed before scoring, so both columns are fresh scores.

**Read it as direction, not as a forecast.** Three limits: (1) the file is the SLIM board, which drops raw keys the scorer now reads. In particular `title_risk` is projected to `surviving_senior_debt_risk` only, so no bidder lead can read a known-clean title here (70 of 95 read "missing") and the lane and F18 effects on real HOT foreclosures are understated; `pickens_delinquent` and `vacancy` are absent, so `tax_lien_chronic` and `vacant_structure` cannot fire. (2) Parcel groups that straddle a stride step or a chunk are not reassembled, so cross-listing effects (F5, F9) are understated. (3) The 20,000 rows are 11.8% of the 170,066-row board, in file order, so source mix matches the board; multiply by about 8.5 to compare with board totals.

| | HOT | WARM | COLD | no stack |
|---|--:|--:|--:|--:|
| committed HEAD scorer | 78 | 8,614 | 11,307 | 1 |
| new scorer | 18 | 3,317 | 16,664 | 1 |
| change | -60 (-77%) | -5,297 (-61%) | +5,357 (+47%) | 0 |

5,543 of 20,000 rows (27.7%) change tier; 14,457 do not. Moves: WARM to COLD 5,413; HOT to WARM 50; HOT to COLD 12; COLD to WARM 66; COLD to HOT 2. Nothing moves WARM to HOT.

**One cause per changed row** (first that applies, so each column sums to its transition):

| Transition | Rows | Cause |
|---|--:|---|
| WARM to COLD | 4,795 | liensnc context-only (decision 1, A8) |
| | 255 | delinquent roll typed tax_sale weighs 20, not 30 (F10) |
| | 252 | absentee plus an 8-point attribute is no longer WARM (F16; gaston_vacant 237 of them) |
| | 42 | a name-based category no longer stacks (F6) |
| | 21 + 7 | an ended sale (21) or a closed enforcement event (7) no longer scores (F2) |
| | 19 | a stack of two needs a weight-15 category (F5) |
| | 16 | Pickens boolean is no longer a PROPERTY signal (F5) |
| | 6 | no record-linked signal (4), a bankruptcy stay (2) |
| HOT to WARM | 21 | equity assumed off the assessed value is not evidence (F4) |
| | 16 | a stack of two needs a weight-15 category (F5) |
| | 7 | a name-based category no longer stacks (F6) |
| | 4 | a stayed foreclosure (F3) |
| | 2 | Pickens boolean (1), an ended event (1) |
| HOT to COLD | 7 | a stack of two needs a weight-15 category (F5) |
| | 3 | a name-based category no longer stacks (F6) |
| | 1 + 1 | an ended event (F2), a stayed foreclosure (F3) |
| COLD to WARM | 42 | bankruptcy-typed rows tied to a property now score LEGAL 18 (F11); courtlistener_bankruptcy 43 |
| | 12 + 1 | elderly_disabled and storm_damage now score (F11); buncombe_elderly 12 |
| | 9 | estate_lead scores LIFE_EVENT 20; mcdowell_probate 9 (decision 2) |
| | 2 | storm damage (1), the foreclosure lane (1) |
| COLD to HOT | 1 + 1 | a storm-damage lead with evidenced equity, and a foreclosure in the lane (a sale 14 days out, clean title) |

Where the direction cannot be seen in this sample: F14 (bare-string mailing) only ever moves leads UP and only matters once the other HOT gates pass, and F18 and the lane need the full `title_risk` block (limit 1). F9, F12 and F17 change no tier in the sample.

**Signals present on a row, before and after** (only the ones that changed):

| Signal | HEAD | New | Why |
|---|--:|--:|---|
| tax_lien | 8,623 | 2,749 | 5,874 liensnc rows are context-only |
| tax_sale | 5,715 | 5,609 | county-owned FLC inventory and ended sales drop out |
| foreclosure_sale | 81 | 55 | 26 ended sales no longer score (F2) |
| upset_bid | 19 | 1 | closed windows and filing dates no longer count (F2) |
| lis_pendens | 791 | 785 | ended sales; Greenville adverts scored by source |
| auction | 39 | 38 | an ended auction |
| distressed | 1,355 | 1,327 | mcdowell and Greenville rows are scored by what they are (decision 2) |
| distressed_condition | 419 | 384 | Pickens boolean ignored (F5) |
| code_enforcement | 102 | 101 | a closed case (F12) |
| bankruptcy | 26 | 92 | bankruptcy-typed rows with a property (F11) |
| elderly_disabled | 0 | 374 | F11 |
| estate_lead | 0 | 116 | F11 and decision 2 |
| storm_damage | 0 | 32 | F11 |
| divorce_notice | 0 | 30 | F11 |
| tax_sale_overage | 0 | 14 | F11 |
| hoa_sale | 0 | 1 | F11 |

**How often each new rule binds in the sample** (new scorer, out of 20,000 rows): equity band present on 3,727 rows and ESTIMATED on 3,174 of them (85%), evidenced on 553; 1,877 rows have no signal weighing 12 or more (absentee route closed); 317 rows carry a name-based category that did not count toward the stack; 100 had a stack of two forced to one by the weight-15 rule; 185 have no record-linked signal; 95 are bidder leads (title: 70 missing, 14 clean, 9 junior-lien risk, 2 unknown); 18 are in the foreclosure lane; 35 have an ended sale (`stale_reason`); 10 have a stay in force. Evidence classes attached to signals: divorce name_only 163, estate_lead name_joined 88, bankruptcy name_joined 76, incarceration name_only 64, distressed inferred 32, divorce inferred 31, divorce_notice name_joined 30, bankruptcy name_only 16, lis_pendens name_joined 9.

**Filing-date sources.** 5,874 of the 20,000 rows are `liensnc`, and every one carries a `sale_date`. It is a lien filing date (`scripts/ingest_all.py` maps `filing_date` to `sale_date`), so none of the lifecycle rules may read it; see the next section.

**In plain words.** The measured direction of the whole change is that far fewer leads are WARM (mostly because 29% of the board is a construction-lien source that was WARM by arithmetic), far fewer are HOT (mostly because equity assumed off an assessed value, a category too light to count, a name match, or a stayed sale no longer completes a stack), a few hundred leads that were invisible now score (six listing types and storm damage), and ended sales fall to COLD. Equity numbers are still published unchanged.

## 1a. Filing-date sources: `sale_date` is not an auction date

`liensnc` (46,989 rows) and `nc_sos_ucc` carry the lien FILING date in `sale_date` so that the row survives the dateless filter. It is not an event that can end, so:

- `distress_score.FILING_DATE_SOURCES = frozenset({"liensnc", "nc_sos_ucc"})` is the one shared set (`distress_score.py:384`), with `SALE_EVENT_TYPES` (foreclosure_sale, auction, sheriff_sale, tax_sale, hoa_sale, lis_pendens) and `sale_date_is_event(li)` (`distress_score.py:415`); a court sale notice on any row also makes its date an event date.
- The scorer reads `sale_date` only through `_sale_date_of`, which returns None for a filing-date source and for a row that is not a sale-type lead. So a liensnc-style row (tax_lien, `sale_date` 31 days ago) gets no `stale_reason`, no COLD cap, no `days_to_event`, no lane, whatever its age.
- `enrich_board_quality` stamps no `sale_date_passed`, withholds no verdict and rewrites no status on such a row, and removes a `sale_date_passed` stamp an earlier run left there.
- `enrich_upset_bid` opens no window from a filing date and removes a derived window an earlier run opened. This mattered: a LiensNC row filed in the last 14 days was tagged `in_window` (NC, `sale_date` 0 to 14 days back), which the scorer would have read as an open upset-bid window and a foreclosure-lane event.
- **Consequence to know:** the type rule also applies to non-sale rows from other sources. A `tax_lien`, `reo`, `distressed` or `probate_notice` row that carries a `sale_date` no longer gets sale-date lifecycle handling or the past-sale stamp. If a county source types a real tax-foreclosure sale as `tax_lien`, add `tax_lien` to `SALE_EVENT_TYPES` for it (one line) and exclude the filing sources by slug, which the set already does.
- **Tests:** `test_filing_date_sources_is_one_shared_frozenset`, `test_a_filing_date_is_not_an_event_date_for_the_scorer` (4 slugs, liensnc-style row with `sale_date` 31 days ago), `test_a_filing_date_row_never_reads_as_a_sale_even_when_the_filing_is_recent_or_the_type_is_a_sale_type`, `test_sale_date_is_only_an_event_date_for_sale_type_leads`, `test_board_quality_stamps_no_sale_date_passed_on_a_filing_date_row_and_removes_an_old_stamp`, `test_the_upset_bid_enricher_opens_no_window_from_a_filing_date_and_clears_an_old_one`, `test_a_recent_filing_cannot_open_a_foreclosure_lane_through_the_upset_bid_path`. `tests/test_shared_row_detection.py::_past_sale` (edited: its fixture is now typed foreclosure_sale instead of the default tax_lien).

## 1b. Flips outside the 18 footprint counties

The data-quality pass stamps `raw['scope'] = 'flip_outside_footprint'` on flip-type leads whose county is not one of the 18 (owner rule 2026-09-15; `docs/data_quality_fixes_2026-09-21.md` section 4). Stamped rows still ship, so the scorer reads the stamp:

- A stamped **flip-type** lead (foreclosure_sale, auction, sheriff_sale, hoa_sale, reo, from `FLIP_TYPES`, `distress_score.py:392`) gets a visible COLD stack with `scope_capped: "flip_outside_footprint"`, no signals, and contributes nothing to its parcel (`flip_outside_footprint`, `distress_score.py:428`; the cap at the top of `_derive_tier`, `distress_score.py:863`, so `retract_equity_rank` cannot re-tier it; the group loop in `score_board`).
- A **distressed-type** lead (tax lien, tax sale, lis pendens, probate, and so on) is unaffected, on its own parcel or beside a capped flip. A Charleston tax lien plus an out-of-footprint sale on one parcel scores the lien alone. A stamp on a distressed-type row does nothing.
- Intent is capped at cold for a capped lead. `LAST_STATS["scope_capped"]` counts them.
- `FLIP_TYPES` mirrors `main._FLIP_LISTING_TYPES` (the scorer cannot import main); `test_flip_types_match_the_orchestrators_flip_scope` pins the two together.
- **Tests:** `test_a_stamped_flip_outside_the_footprint_is_capped_cold_with_the_reason`, `test_every_flip_type_is_capped_when_stamped` (5 types), `test_a_distressed_type_lead_is_unaffected_by_the_stamp`, `test_a_capped_flip_adds_nothing_to_a_distressed_lead_on_the_same_parcel`, `test_a_flip_only_parcel_counts_as_one_cold_group_and_a_mixed_parcel_counts_once`, `test_a_stamp_with_any_other_value_does_nothing_and_a_capped_stack_survives_retraction`, `test_the_capped_lead_reads_cold_on_the_chip_and_intent`, `test_flip_types_match_the_orchestrators_flip_scope`.
- **Not in the 20,000-row sample:** the stamp is not on the board yet. The key survives publishing only after the RAW_KEEP entry in the data-quality doc lands (handoff, section 2).

## 2. New fields on `distress_stack`

The dashboard-facing shape is unchanged: `tier`, `stack`, `categories`, `signals`, `score`, `equity_band`, `absentee`, `out_of_state`, `contactable`, `surviving_senior_debt_risk` are all still there with the same meaning. New fields are ADDED and appear only when they differ from the default a reader assumes, because the stack ships in full on the slim board and payload size is tight (O1). A plain lead carries exactly the old keys (`test_the_distress_stack_keeps_its_shape_and_adds_fields_only_when_they_matter`).

| Field | Present when | Meaning |
|---|---|---|
| `evidence` | some signal is not a record | `{signal: "inferred" | "name_joined" | "name_only"}`. Absent entry means `record`. Helper: `distress_score.evidence_of(ds, name)`. |
| `record_linked` | False | No signal on the parcel is a record about the property. HOT is blocked. |
| `uncounted_categories` | non-empty | Name-based categories that added score but not stack. |
| `stack_capped` | the weight-15 rule fired | Text reason; `stack` was forced to 1. |
| `equity_evidenced` | an equity band exists | True when the payoff behind the band is a recorded deed of trust, judgment or opening bid (or confidence medium or better). |
| `non_attribute` | False | Every signal weighs under 12, so the absentee route to WARM is closed. |
| `lane` | "foreclosure" | A foreclosure-type lead with a live date. |
| `days_to_event` | a dated live event exists | Days to the nearest sale or upset-bid deadline. |
| `bidder`, `title_status` | a bidder signal exists | `title_status` is `clean`, `junior_risk`, `unknown` or `missing`. |
| `stale_reason` | an ended sale was dropped and no live enforcement remains | Tier is COLD. |
| `stay` | a bankruptcy stay is in force | `{status, chapter, resume_risk, case}`. |
| `scope_capped` | a flip-type lead carries `raw['scope'] == 'flip_outside_footprint'` | The string is the reason. Tier COLD, no signals, nothing added to the parcel (section 1b). |
| `score_error` | that parcel group failed to score | Tier COLD, and `score_board` raises (F17). |

## 3. Findings, one by one

Line numbers are for the working tree as of this write-up. "Test" names are in `tests/test_scoring_audit_fixes.py` unless another file is named.

### F1. Debt placeholder chip (scorer half already fixed in 4bc5792)
- **Changed:** the lead-signals chip now uses `is_countable_debt`, the predicate the scorer and the equity engine use. `enrichment_lead_signals.py:109-112`.
- **Test:** `test_f1_the_lead_signals_chip_uses_the_same_countable_debt_predicate_as_the_scorer_and_equity`; `tests/test_enrichment_lead_signals.py::test_facet_liens_and_recorded_debt` (edited).
- **Visible:** an assessed-value placeholder no longer adds a `recorded_debt` chip.

### F2. Ended events keep scoring and stay HOT
- **Changed:**
  - The scorer takes `today` (`score_board`, `_signals_for`, default `date.today()`). `distress_score.py:1278, 817`.
  - An upset-bid block counts only when `in_window is True` and its `deadline_iso`, if present, has not passed. `_upset_open`, `distress_score.py:529`.
  - A sale, sheriff sale, auction, HOA sale, lis pendens or tax sale whose date passed more than 14 days ago (NC) or 7 days ago (SC), with no open upset window and, for a tax sale, no redemption period, contributes nothing. `_sale_status`, `distress_score.py:561`. The SC redemption test uses the stored `redemption_deadline`, else sale plus 365 days (SC Code 12-51-90). `_redemption_open`, `distress_score.py:550`.
  - When a parcel's only enforcement events were dropped this way the stack gets a `stale_reason` and the tier is COLD (`_derive_tier`, `distress_score.py:858`). A parcel that still has a live enforcement signal (a newer lis pendens, a standing tax roll row) is not capped, because the property is not dead.
  - The Greenville adverts null `sale_date` on purpose, so the scorer reads the advert's own date from `raw.greenville_mie.sale_date` (`_RAW_SALE_DATE_FALLBACKS`).
  - `enrichment_board_quality` now downranks HOT to WARM on `pulled_sale.presumed_withdrawn` (with the last status still "active") and on a past sale date beyond the 10-day grace that has no open upset window and no SC redemption period, not only on the exact status string. `_stale_reason`, `enrichment_board_quality.py:124`. It sets `stale_case` only for the two withdrawn cases (that flag has always meant "the source stopped listing it"); a passed sale date downranks with `downranked_reason: "sale_date_passed"` and no flag, so thousands of rows with an old tax-roll date do not all become `stale_case`.
  - `enrich_upset_bid` stamps `as_of` on every block it writes and takes an injectable `now`. `enrichment_upset_bid.py:104, 159`.
- **Tests:** `test_f2_*` (11 tests: ended sale, 14/7 day grace boundaries, open window keeps alive, closed window scores nothing, deadline passed with stale flag, SC redemption alive and dead, live sibling not capped, board quality on the pulled-sales marker, on a past sale, on SC redemption, `as_of`).
- **Visible:** foreclosures with an ended sale drop to COLD (52 HOT leads carried a passed sale date on the 9/21 board). Live NC upset windows count for as long as they are open and no longer.
- **Not done here:** F8 (the 22 sources whose sale-day rows are diverted to the sold pool before scoring), the dashboard's `stageOf` truthiness test, and F15's read-time recomputation in the UI. See the handoff.

### F3. A stayed foreclosure ranks higher
- **Changed:** when `bankruptcy_stay.status == "stayed"` and the stay is inside its lifetime, the bankruptcy signal is dropped from the stack (no LEGAL category), the tier is capped at WARM, and `stay` is added to the stack. `_stay_block`, `distress_score.py:602`; the drop, `distress_score.py:1155`; the cap, `distress_score.py:886` and the lane branch at `:871-876`.
- A bankruptcy match now expires: Chapter 7 after 270 days, anything else after 1,095 (`signal_freshness.py:30-31`, `bankruptcy_lapsed`). `enrichment_bankruptcy_stay` writes `status: "lapsed"` instead of "stayed" for an expired match, and no longer treats the catch-all `distressed` type as a foreclosure (it now covers auction and hoa_sale). `enrichment_bankruptcy_stay.py:46, 69`.
- **Tests:** `test_f3_*` (4 tests); `tests/test_bankruptcy_stay.py::test_ch13_old_case_is_elevated_resume_risk` (edited: it used a fixed 2024 date that would lapse on 2027-01-01).
- **Visible:** stayed foreclosures lose HOT. Bankruptcy filings older than the lifetimes above stop scoring.

### F4. Equity gate is arithmetic, not evidence
- **Changed:** `equity_is_evidenced` (`enrichment_equity.py:200`) says whether the payoff came from a recorded deed of trust, a foreclosure judgment or the opening bid, or the engine rated it medium or better. `enrich_equity` stamps `equity.evidenced` (`enrichment_equity.py:656`). The scorer reads it through `_equity_info` (`distress_score.py:920`): an estimated equity still satisfies the WARM route (`score >= 28 and eq_ok`), only an evidenced one opens HOT (`_tier`, `distress_score.py:832`). The ROI fallback is never evidenced. Equity numbers are still published unchanged.
- **Judgment call:** a delinquent-tax balance used as the payoff (`amount_owed:tax_owed`) is excluded from "evidenced" even though amount_owed rates it medium. Equity net of a tax bill only says the mortgage is unknown. Remove `_NON_MORTGAGE_PAYOFF_SOURCES` to follow the decision text literally.
- **Tests:** `test_f4_*` (4 tests, including 10 payoff-source cases).
- **Visible:** leads whose equity is the 40% assessed-value constant can no longer be HOT. This is the largest single cause of HOT loss on delinquent-tax leads.

### F5. One event can make stack 2
- **Changed:**
  - The enforcement chain is one FINANCIAL category: `sheriff_sale` moved from SALES to FINANCIAL (`_LISTING_TYPE_SIGNAL`, `distress_score.py:279`), and an REO or auction on a parcel that also carries an enforcement record folds into FINANCIAL (`distress_score.py:1150`). `_ENFORCEMENT_CHAIN`, `distress_score.py:329`. REO and auction alone stay SALES.
  - `price_cut` needs MLS fields (`_mls_signals`, `distress_score.py:457`). The prior-run price index is only read when some listing has MLS fields, and it now streams the file instead of `json.loads` on 1.1 GB (see F17).
  - The Pickens boolean is removed as a PROPERTY source. The scraper no longer sets `raw["distressed"]` (`pickens_delinquent_parcels.py:418-424`); the scorer ignores it on that source unless the assessor's condition code agrees (`_distressed_flag_counts`, `distress_score.py:789`); a chronic roll (3+ cycles) raises the FINANCIAL weight to 24 as `tax_lien_chronic`.
  - A stack of two must include one category of weight 15 or more, otherwise it is forced to 1 with `stack_capped`. `distress_score.py:1192`.
- **Tests:** `test_f5_*` (6 tests); `tests/test_pickens_delinquent_parcels.py::test_chronic_delinquency_raises_the_tax_weight_and_is_not_a_property_signal` (edited).
- **Visible:** sheriff plus foreclosure, foreclosure plus REO, and two 8-point attributes no longer make stack 2. Pickens rows lose the PROPERTY category (1,854 rows).

### F6. Name-only matches count as full evidence
- **Changed:** every signal carries an evidence class (`distress_score.py:93-103`). Record: type-level signals, debt, code enforcement, storm damage, deed probate, senior exemption, and so on. Inferred: keyword `distressed`, a derived upset window, a deed-pattern divorce, price cut. Name-joined: type-level estate lead, divorce notice and bankruptcy, and any signal on a lead whose parcel came from the name resolver (`resolved_from_name.confidence == "unique_match"`). Name-only: incarceration, the bankruptcy subset match, court divorce. Name-based signals add score but a name-based category never CREATES a stack: it counts only when at least two record-linked categories already exist (`_NAME_BASED_MIN_RECORD_CATEGORIES`, `distress_score.py:103`). HOT requires at least one record-linked signal. A jail booking that says released stops counting. NC divorce dates in MM/DD/YYYY are now read (they scored 0 before).
- **Judgment call (the one to check):** the decision reads "count toward the stack only if a second, record-linked category exists". I read "second" so that audit F6's own example is fixed: foreclosure (record) plus a jail-roster name match is stack 1, not stack 2. Under the looser reading (any one record-linked partner is enough) that example stays HOT. To switch, set `_NAME_BASED_MIN_RECORD_CATEGORIES = 1`; tests `test_f6_a_name_only_match_adds_score_but_cannot_complete_a_stack` and `test_f6_name_based_categories_do_count_once_two_record_categories_exist` pin the current behaviour.
- **Tests:** `test_f6_*` (7 tests).
- **Visible:** 11 of the 31 sample leads that lost HOT lost it here (Rutherford tax leads with a bankruptcy or jail name match, probate with a court divorce match).

### F7. HOT rule built for the wrong lane
- **Changed:** a foreclosure-type lead (foreclosure_sale, auction, sheriff_sale, court sale notice, open upset window) with a live date (sale 0 to 30 days out, or `in_window is True`) gets `lane: "foreclosure"`, `days_to_event`, and is tiered without a mailable owner or equity: HOT if the title risk is known clean, no stay is in force and a record supports it; WARM if the title is unknown, missing, stayed or the parcel came from a name search; COLD on a junior-lien risk. `_derive_tier`, `distress_score.py:858-876`; lane detection `distress_score.py:1237-1242`. Fullmer stamps `lane` and `days_to_event` and flags lane leads `foreclosure_lane_not_judged` (`fullmer_rank.py:393-399`). HOA sales are not in the lane (their junior-lien nature makes them a trap by default).
- **Tests:** `test_f7_*` (10 tests, 4 title-risk cases, 4 window-boundary cases).
- **Visible:** near-term foreclosures get a tier that reflects the deadline. `days_to_event` is also set (informationally) on leads with a further-out or non-lane dated event.
- **Not done here:** the dashboard sort "deadline lane first" (default sort is `_grade`, `docs/dashboard.js:6`). Handoff item.

### F9. Parcel key fuses unrelated properties
- **Changed:** key is state + county + parcel; an id with no digit, under four characters after stripping, or all zeros ungroups. `_parcel_key`, `distress_score.py:999`. Each listing gets its own copy of the stack (`_copy_ds`, used at `distress_score.py:1346`), and `enrich_board_quality` copies before it downranks (`enrichment_board_quality.py:236`).
- **Tests:** `test_f9_*` (4 tests, 9 placeholder cases).
- **Visible:** cross-county collisions and placeholder ids stop stacking. The 369 multi-row keys on the board will re-split where they were false fusions.

### F10. Weights depend on the scraper's listing type
- **Changed:** a `tax_sale` with no upcoming sale date weighs 20, like a tax lien; an upcoming date keeps 30 (`_TAX_SALE_STANDING_ROLL_WEIGHT`, `distress_score.py:298`). County-owned FLC and forfeited-land inventory typed `tax_sale` scores nothing unless a sale is scheduled (`_is_county_owned_inventory`, `distress_score.py:451`). `mcdowell_probate` and `greenville_mie_adverts` score by their real meaning through a source override map, LIFE_EVENT 20 and FINANCIAL 28 (`_SOURCE_OVERRIDE`, `distress_score.py:374`), and the scrapers are retyped for future runs: mcdowell to `ESTATE_LEAD`, resolved Greenville adverts to `LIS_PENDENS` (not a flip type, so the Greenville scope policy is unchanged). No scraper is retyped for the delinquent rolls; the weight is decided by sale date instead, so 40,000 SC rows keep their type.
- **Tests:** `test_f10_*` (4 tests); `tests/test_context_only_distressed.py` (mcdowell moved out of the PROPERTY list into a LIFE_EVENT test); `tests/test_greenville_mie_adverts.py::test_a_past_sale_date_types_as_lis_pendens_not_foreclosure_sale` (edited).
- **Visible:** an SC roll row alone is COLD, not WARM. About 97% of Greenville adverts are past-dated and now score nothing.

### F11. Listing types and signals that never scored
- **Changed:** divorce_notice LIFE_EVENT 15, estate_lead LIFE_EVENT 20, hoa_sale FINANCIAL 25, elderly_disabled LIFE_EVENT 8, tax_sale_overage FINANCIAL 15, bankruptcy LEGAL 18 only when the row has a parcel or street address (`_LISTING_TYPE_SIGNAL`, `distress_score.py:279-296`). `raw.storm_damage` is graded PROPERTY: destroyed 20, major or red 16 (+3 on a FEMA substantial-damage finding), yellow or inundated or landslide 12 (+4 on substantial damage); minor, green and affected score nothing (`_storm_signal`, `distress_score.py:165`). A code-officer-confirmed vacant or boarded structure (`raw.vacancy`) is PROPERTY 12 (`_vacant_structure`, `distress_score.py:801`). USPS vacancy and `vacant_lot` stay unscored (context and land, not distress).
- **Tests:** `test_f11_*` (6 tests).
- **Visible:** the rows of these six types on the 9/21 board (divorce_notice 244, estate_lead 703, elderly_disabled 2,988, tax_sale_overage 108, hoa_sale 2, and bankruptcy 1,378 where a property is attached) now carry a signal. Most stay COLD alone.

### F12. Closed and resolved records score as open
- **Changed:** code enforcement counts only while a case is open (`signal_freshness.code_enforcement_open`, `signal_freshness.py:75`, handles the dict, list and bare shapes); `stamp` and `is_stale` give every stamping enricher a `stamped_at` and `stale_after` (`signal_freshness.py:56, 66`). `enrichment_code_enforcement` stamps its writes with a 120-day lifetime, tells "the city answered with no case" from an outage, and clears only a block it wrote itself. `enrichment_code_enforcement.py:43-46, 165-196`. Incarceration and bankruptcy expiry are under F6 and F3.
- **Tests:** `test_f12_*` (4 tests, 10 shape cases).
- **Visible:** closed code cases stop scoring PROPERTY 14.

### F13. Signal chip counts synonyms
- **Changed:** facet names are the scorer's own names (a real tax balance is `recorded_debt`, an open case or condemnation is `code_enforcement`, a confirmed vacant structure is `vacant_structure`, deed probate is `probate_deed`). `signal_stack.count` is the number of distinct distress categories, excluding ownership context and any category the tier itself did not count; `categories` is added. `enrichment_lead_signals.py:94-215`. TRUST and a bare ESTATE in an owner name are not probate: `life_events` `estate_probate` counts only when the owner name says HEIRS or ESTATE OF (`signal_freshness.owner_names_a_death`, `signal_freshness.py:145`), in both the chip and `enrichment_strategy_fit` (`enrichment_strategy_fit.py:36`). Strategy fit treats "distressed" as WARM or HOT, not any signal (`:77`). Intent is capped at cold when the stack has a `stale_reason`, and below hot when a stay, `downranked_stale` or `stale_case` is present (`enrichment_lead_signals.py:266-270`). The chip's absentee read uses `mailing_of` (F14).
- **Not changed:** the regex in `enrichment_life_events.py` that writes the `estate_probate` and `trust` tags (not a file I own); the handoff has the exact change. The dead `estate_elderly` append is also there.
- **Tests:** `test_f13_*` (9 tests); `tests/test_enrichment_lead_signals.py` (five tests edited, each with a comment).
- **Visible:** one tax delinquency reads as 1 signal, not 3; one Helene placard as 1, not 2.

### F14. Bare-string owner_mailing
- **Changed:** `score_board` reads the mailing block through `mailing_dict` (`distress_score.py:1209-1216`); `mailing_of` (`mailing_shape.py:52`) is a strict accessor that reads only `raw["owner_mailing"]`, because `mailing_dict(raw)` returns the whole raw dict when the key is absent. Fullmer and the chip use it.
- **Tests:** `test_f14_*` (3 tests).
- **Visible:** 5,098 Spartanburg leads become contactable and can be HOT.

### F16. WARM on absentee plus any 8-point attribute
- **Changed:** the absentee route to WARM needs a signal of weight 12 or more (`non_attribute`), instead of raising the floor to 28, so a real 14-point event plus absentee stays WARM. `_tier`, `distress_score.py:832-855`.
- **Tests:** `test_f16_*` (3 tests).
- **Visible:** out-of-state owner plus an elderly exemption alone is COLD.

### F17. Silent failures
- **Changed:** `score_board` scores every group it can, stamps a failed group's rows `score_error` at COLD (so no prior tier survives), then raises `ScoreBoardError` with `.failed`, `.hist` and `.failures` (`distress_score.py:76, 1278-1360`). `LAST_STATS` carries lane, stale, stay and error counts. The prior-run price index streams (plain or `.gz`, preferring the small `.gz` sibling), logs and records a read failure, and treats a truncated snapshot as an error instead of "no prior prices" (`distress_score.py:1017-1117`). `enrich_lead_signals` clears a stale intent score on failure and returns `failed` in its stats. **main.py still swallows the exception**: the change is in the handoff.
- **Tests:** `test_f17_*` (4 tests).
- **Visible:** partial-board scripts that call `score_board(listings)` no longer parse a 1.1 GB file into memory, and only read it at all when a listing has MLS fields.

### F18. Title-risk unknown is treated as clean
- **Changed:** for a bidder lead (foreclosure_sale, auction, sheriff_sale, hoa_sale, court sale, upset bid) an unknown or missing title risk is not HOT-eligible, and a junior-lien risk caps the tier at COLD. `_derive_tier`, `distress_score.py:872-889`; `title_status` on the stack.
- **Tests:** `test_f18_*` (3 tests); `tests/test_arv_sanity.py::test_a_contradicted_lead_cannot_reach_hot_but_its_records_still_rank` (edited: its foreclosure fixture gets a known-clean title risk, and evidenced equity, per F4).
- **Visible:** foreclosure-type HOT leads need a recognised senior-lien plaintiff.

### F19. Legacy equity flags
- **Changed:** `flags.py` no longer derives `high_equity`, `low_equity` or `negative_equity` from a Zestimate minus the last sale price. They come from the gated `raw["equity"]`, `high_equity` only when the equity is evidenced, and stale legacy flags are dropped (`flags.py:38, 73-83`). The grader already prefers `raw.equity` and only reads these flags when it is absent, so the flags it used to fall back to are now simply not emitted.
- **Tests:** `test_f19_*` (2 tests).
- **Visible:** the green "high equity" chip only appears on leads whose equity rests on a recorded fact.

### Decision 1 (audit A8). liensnc context-only
- **Changed:** any source whose slug is `liensnc` adds no listing-type signal, whatever type it carries. `_is_liensnc`, `distress_score.py:443`. A liensnc row with a real tax balance or code case still scores those.
- **Tests:** `test_a8_*` (2 tests, 3 slug spellings).
- **Visible:** about 38,000 leads leave WARM (the audit's own estimate; 1,926 of 2,084 WARM to COLD moves in the sample).

## 4. Existing tests edited (deliberate semantic changes)

| File | Test | Why |
|---|---|---|
| `test_arv_sanity.py` | `test_a_contradicted_lead_cannot_reach_hot_but_its_records_still_rank` | Fixture now carries evidenced equity (F4) and a known-clean title risk (F18). |
| `test_bankruptcy_stay.py` | `test_ch13_old_case_is_elevated_resume_risk` | Fixed 2024 date would lapse on 2027-01-01 under the new lifetime. |
| `test_context_only_distressed.py` | mcdowell_probate | Scores LIFE_EVENT 20, not PROPERTY (decision 2). |
| `test_enrichment_lead_signals.py` | five facet and stack tests | Canonical names and category counts (F13). |
| `test_greenville_mie_adverts.py` | past-dated advert type | LIS_PENDENS, not DISTRESSED (decision 2). |
| `test_pickens_delinquent_parcels.py` | chronic delinquency | No PROPERTY boolean; FINANCIAL weight 24 (F5). |

## 5. Verification

- Reproduction of the audit scenarios against the previous scorer, and the same scenarios after: run `.venv/bin/python` on the scenarios in `tests/test_scoring_audit_fixes.py`, each docstring states the pre-fix result.
- Tests run, all passing: `tests/test_scoring_audit_fixes.py` (170 tests, one or more per finding plus the filing-date and footprint rules), the ten files named in the brief (`test_divorce_signal_score`, `test_recorded_debt_signal`, `test_context_only_distressed`, `test_helene_distress`, `test_enrichment_lead_signals`, `test_equity`, `test_arv_sanity`, `test_pipeline_ordering`, `test_enrichment_order`, plus the upset-bid, bankruptcy-stay, strategy-fit, board-quality, Fullmer, Pickens, Greenville, code-enforcement, tax-owed, RAW_KEEP, owner-mailing, lien-stack, helene and relationship-deed files, and every other file that imports a module I changed). The final run of 38 files: 938 passed, 4 skipped, 0 failed. An earlier run that also included the slow ArcGIS and repeat-tax-loss files (563 passed, 1 skipped) also had 0 failures; those two files do not touch the scorer and were not re-run after the last edits. The whole suite was not run.
- Smoke on real row shapes: 3,000 to 4,000 stride-sampled slim rows through `enrich_upset_bid`, `enrich_bankruptcy_stay`, `enrich_equity`, `compute_flags`, `score_board`, `enrich_lead_signals`, `rank_board`, `enrich_board_quality`, `enrich_strategy_fit` and `retract_equity_rank`: no exceptions, `failed: 0`.

## 6. Interpretation calls to check

1. Name-based categories need two record-linked categories before they count (F6, above).
2. `amount_owed:tax_owed` is not evidence of the mortgage (F4).
3. A stale sale caps the tier at COLD only when the parcel has no live enforcement signal left.
4. Bankruptcy lifetimes: 270 days (Chapter 7), 1,095 days (other).
5. `raw.probate` is a record (an estate case) unless the parcel came from the name resolver.
6. County-owned FLC inventory with a scheduled sale keeps weight 30 (decision 3 for dated tax sales); without one it scores nothing.
7. HOA sales are excluded from the foreclosure lane.
8. `sold_unconfirmed` court sales keep scoring as before (the audit says the property already sold); only a passed date ends them.
