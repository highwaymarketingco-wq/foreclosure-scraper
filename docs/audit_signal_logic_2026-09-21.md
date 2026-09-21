# Signal and scoring logic audit, 2026-09-21

Independent, read-only audit of how the engine turns collected records into a HOT / WARM / COLD tier and a rank, judged from the seat of someone who bids money off it. Scope: `distress_score.py`, `enrichment_derivation_flags.py`, `enrichment_lead_signals.py`, `enrichment_strategy_fit.py`, `fullmer_rank.py`, `enrichment_equity.py`, `valuation/grading.py` (trust gates), `enrichment_board_quality.py`, `enrichment_board_qa.py` (retraction path), `enrichment_data_quality.py`, and the enrichers that write the signals.

## Audit basis (read this first)

- Method: code read, plus synthetic `Listing` objects run through the real functions with `.venv/bin/python`. No board file was loaded, `load_board` was not called, no network was touched, nothing in the repo was edited except this file. Reproduction scripts live in the session scratchpad, not in the repo.
- The repo moved while I worked. HEAD went from the e7df338 era to 77d7131 (09:47, divorce middle-initial skip). Then another session edited `distress_score.py`, `enrichment_equity.py` and added `tests/test_recorded_debt_signal.py` (09:50 to 09:52 uncommitted, committed at 09:59 as 4bc5792, "an estimated amount_owed is not recorded debt"). Line numbers below for those two files refer to commit 77d7131 (`git show 77d7131:src/foreclosure_scraper/<file>`), so they will not match the current tree after 4bc5792. Every other file was unmodified during the audit and is cited as it stands.
- F1 reproduced on the code as I first read it and does NOT reproduce on the 09:52 working tree (that edit is the fix, since committed as 4bc5792). Every other finding still reproduced on the 09:52 tree. I did not re-run anything after 4bc5792.
- 75 existing tests pass (`test_divorce_signal_score`, `test_helene_distress`, `test_enrichment_lead_signals`, `test_equity`, `test_pipeline_ordering`, `test_enrichment_order`). Only one test drives `score_board` end to end (`tests/test_arv_sanity.py:964-975`, ARV gating). Nothing tests the tier rule, stale dates, cross-listing, or stack composition.

## (a) The eight findings that matter most to a bidder, ranked

Ranked by risk to someone bidding off the tier. F1 sits third only because a fix landed (4bc5792) while I was auditing; before it, F1 was the widest-reaching defect on the board.

| # | Finding | Severity | One line |
|---|---|---|---|
| 1 | F2 Ended events keep scoring and stay HOT | critical | The scorer has zero date logic. A foreclosure whose sale was 200 days ago stays HOT. A closed upset-bid window still scores 22 points because the flag is a truthy dict. `sale_date_passed` is written and read by nothing. |
| 2 | F3 A stayed foreclosure ranks higher, not lower | high | A bankruptcy match adds a whole LEGAL category (stack 2, HOT). The stay the engine itself derived (`bankruptcy_stay`, "foreclosure paused") is read by no scorer and no dashboard code. |
| 3 | F1 An assessed value was scored as debt (fixed in commit 4bc5792) | critical | `amount_owed.value` from the "not debt" assessed-value fallback created a FINANCIAL category. An out-of-state house with a county appraisal and no distress reached WARM. Parallel measurement: 49% of `recorded_debt` signals were estimates. |
| 4 | F4 The equity gate is arithmetic, not evidence | high | With no recorded debt the engine assumes payoff = 60% of assessed value, so equity is exactly 40% ("high") for every such lead (30% "med" if tax-aging). The HOT equity condition is satisfied by construction. `equity.confidence` is never read by the tier. |
| 5 | F5 One event can make stack 2 | high | Sheriff sale plus foreclosure sale, foreclosure plus REO, a paid-down tax balance or lowered bid read as a "price cut", Pickens multi-year delinquency setting a PROPERTY flag. Weight is ignored by the stack rule, so any 8-point item counts as a full category. |
| 6 | F6 Name-only matches count as full evidence and no confidence reaches the tier | high | Incarceration, bankruptcy, court divorce and name-resolved probate stack exactly like a court record. Measured on divorce: 21% proven wrong person, 45% unverified, 34% agree. |
| 7 | F7 The HOT rule and the ranking are built for the wrong lane | high | HOT needs a mailable owner and equity, neither of which matters at an auction. There is no days-to-sale term: a sale in 3 days is WARM at best (COLD with no equity figure), a dateless tax lien plus a senior exemption plus a closed code case is HOT. |
| 8 | F8 The actionable window is removed before scoring | high | For 22 named trustee, Master-in-Equity and tax sources, any sale from today back 180 days is diverted to the sold-comp pool before `_active_only`, so the NC upset-bid window and sale-day leads never reach a fresh board. |

F9 (parcel key fuses unrelated properties across counties and on placeholder parcel ids) is the ninth by risk but its prevalence is unmeasured, so it sits outside the top eight.

## (b) Signal table: everything that reaches the score

Scoring mechanics (`distress_score.py`, HEAD 77d7131): signals are grouped by parcel (`_parcel_key`, 436-440), bucketed into 5 categories, `stack` = number of distinct categories (`score_board` 502-579), `score` = best weight per category (line 535) + absentee 8 + out-of-state 4 - 20 if a senior lien survives. `_tier` (307-320): HOT = stack >= 2 and equity band high/med and mailable and no senior risk; WARM = stack >= 2, or score >= 28 with equity, or absentee with stack >= 1 and score >= 20; else COLD. The stack counts categories, never weights.

Evidence vocabulary. record: a public record about this property or case. record, name-joined: a record about a party, attached to a property by owner-name search. name-only: a party name matched in a roster with no second identifier. inferred: derived from text, a heuristic, or an estimate.

| Signal | Category | Weight | Recency treatment | Evidence type | Where set (file:line) | Flag |
|---|---|---|---|---|---|---|
| foreclosure_sale | FINANCIAL | 30 | none in scorer | record | distress_score.py:174 | scraper-dependent; the row's date is only gated upstream (F2, F8) |
| lis_pendens | FINANCIAL | 28 | none | record | :175 | scored below foreclosure_sale though it precedes it |
| sheriff_sale | SALES | 25 | none | record | :176 | same event chain as foreclosure_sale, different category (F5) |
| tax_sale | FINANCIAL | 30 | none | record | :177 | also emitted for standing delinquent rolls and FLC inventory (F10) |
| tax_lien | FINANCIAL | 20 | none | record | :178 | same fact as tax_sale, 10 points lower (F10) |
| auction | SALES | 18 | none | record or platform listing | :179 | |
| reo | SALES | 15 | none | record (bank listing) | :180 | seller is a lender; also the outcome of a foreclosure (F5) |
| distressed | PROPERTY | 10 | none | inferred (description keywords) | :181 | |
| probate_notice | LIFE_EVENT | 20 | notice date not read | record, name-joined | :182 | estate has no close signal |
| helene_restricted / unsafe / destroyed | PROPERTY | 12 / 16 / 20, +2 or +3 for damage %, +2 for 3+ buildings | none (2024 placards never age, repairs invisible) | record | :44-83 | only via source `counties_nc.asheville_helene`; `raw['storm_damage']` from the Helene enricher is unread (F11) |
| mls_withdrawn_expired | SALES | 18 | snapshot at fetch | record (MLS feed) | :204 | status date not read |
| stale_on_market | SALES | 14 | days_on_mls >= 2 x MOI x 30 (fallback MOI 6 = 360 days) | record | :221 | |
| price_cut | SALES | 16 | cross-run diff, >= 4% and >= $2,500 | inferred | :226-229 | not gated to MLS listings (F5) |
| court_sale | FINANCIAL | 25 | none | record (docket) | :252-253 | `sold_unconfirmed` means the property already sold |
| upset_bid | FINANCIAL | 22 | none; scored while the dict is truthy, even `in_window: False` | record if published, else inferred (sale + 14 d) | :254-255 | F2 |
| recorded_debt | FINANCIAL | 12 | none | at 77d7131: record only when source is judgment / opening_bid / tax_owed, otherwise an estimate | :256-257 | F1, fixed in 4bc5792 |
| str_permit_lapsed | FINANCIAL | 12 | none | record | :258-261 | |
| senior_exemption | LIFE_EVENT | 8 | none | record (assessor exemption) | :267 | an attribute, not an event |
| deferral_rollback | FINANCIAL | 6 | none | record | :270 | farm/forest programme status, not distress |
| bankruptcy | LEGAL | 18 | 180-day lookback when matched, then permanent | name-only | :272-273 | F3, F6 |
| incarceration | LEGAL | 8 | permanent once set | name-only | :274-275 | F6 |
| probate (raw.probate) | LIFE_EVENT | 20 | none | record, name-joined | :277-278 | `raw.estate` has no writer |
| probate_deed | LIFE_EVENT | 20 | none | record (ROD instrument) or owner-of-record contains HEIRS/ESTATE | :285-286 | same weight as a court-noticed estate |
| divorce (deed) | LIFE_EVENT | 15, or 8 for zero-consideration quitclaim | none | inferred (deed pattern) | :287-291 | |
| partition | SALES | 12 | none | record | :292-294 | usually already sold |
| divorce (court) | LIFE_EVENT | 12 if newest filing <= 3 y, 6 if <= 7 y, else none | age decay on filing date | name-only | :121-152 | no disposition read; NC date format unparseable (F17) |
| code_enforcement / condemned | PROPERTY | 14 | none; closed cases count | record | :300-301 | F12 |
| distressed_condition | PROPERTY | 8 | none | record (assessor condition code) or a boolean a scraper sets | :302-303 | Pickens sets it for 3+ delinquency cycles (F5) |
| absentee | bonus | +8 | none | record-derived | :553 | roughly half the board (`fullmer_rank.py:343-359`) |
| out_of_state | bonus | +4 | none | record-derived | :555 | |
| senior lien survives | penalty | -20 and HOT blocked | none | inferred from party text | :559-565 | unknown party is treated as clean (F18) |

Weights that look arbitrary or inconsistent with neighbours:

- tax_sale 30 vs tax_lien 20 for the same underlying fact, chosen by which scraper wrote the row (F10).
- sheriff_sale 25 sits in a different category from foreclosure_sale 30 although it is the execution of it.
- bankruptcy 18 vs incarceration 8: both name-only, 10 points apart, and the stack rule makes the difference irrelevant.
- code_enforcement 14 is flat for a demolition order, a closed grass complaint, and everything between.
- probate 20 is identical for a court notice, a deed instrument, and an owner-of-record name that may be decades old.
- `docs/path_to_100_deepdive.md:8985` already calls the weights hand-set and proposes fitting them.

## (c) Findings

### F1. An assessed value was scored as a debt (critical; fixed by commit 4bc5792 during the audit)

Evidence: `distress_score.py:256-257` (HEAD) scored `recorded_debt` FINANCIAL 12 on `(r.get("amount_owed") or {}).get("value")`. `enrichment_amount_owed.py:78-85` fills that field from `assessed_value` / `tax_value` as a last resort and labels it "Tax-assessed value (not debt)", `is_actual_debt=False`. Equity already refused to treat it as debt (`enrichment_equity.py:385-386`); the scorer did not. `enrichment_lead_signals.py:85-86` has the same predicate for the chip.

Failure scenario (reproduced): a NC house, out-of-state absentee owner, county appraisal only, no distress evidence at all: `recorded_debt` 12 + absentee 8 + out-of-state 4 = 24, tier WARM. Add a senior exemption (LIFE_EVENT 8) and any equity and it is HOT, stack 2. A code-enforcement-only lead with an appraisal reached HOT the same way. A plain vacant parcel with an appraisal was tagged `LAND_WHOLESALE: vacant land + distress signal` because `enrichment_strategy_fit.py:59` treats any signal as distress. Published counts corroborate scale: `docs/MASTER_GAPS_WALLS_AND_MANUAL_LANES.md:79` lists `recorded_debt` (22,806) as the most common signal on a 40,702-lead board against foreclosure_sale (521) and upset_bid (84). The other session's docstring (`tests/test_recorded_debt_signal.py`, working tree) reports 16,142 of 33,259 signals (49%) resting on an estimate and 644 of 1,646 HOT leads being a generic demolition-permit tag plus one such estimate. I did not re-measure those.

Downstream cost: tier drives spend. `enrichment_photos.py:189`, `enrichment_lrcpwa_photo.py:61`, `enrichment_sos_agent.py:282`, `enrichment_parcel_reverse_geo.py:48`, `enrichment_buyer_match.py:121`, and `scripts/build_skiptrace_worksheet.py:43` all prioritise by tier.

Fix: one shared predicate for "countable debt" used by scorer, equity and the lead_signals facet (4bc5792 adds `is_countable_debt` for the first two). Effort: done for scorer and equity; 15 minutes for the lead_signals facet at `enrichment_lead_signals.py:85`; 1 hour for a regression test that the unit is pinned at the tier level, not just `_signals_for`. Note for the new `_real_tax` branch: `enrichment_tax_owed.py:56-59` lets generic keys `opening_bid`, `fll_bid`, `flc_bid` become `tax_owed.balance`, so a county FLC sale price can read as an owner's tax debt. Not audited in depth.

### F2. Ended events keep scoring and stay HOT (critical)

Evidence:
- The scorer has no date input. `grep -c "sale_date|upset_bid_deadline|redemption"` on `distress_score.py` at HEAD returns 0. The only aged inputs are court divorce (filing age, 121-152), `stale_on_market` and cross-run `price_cut`.
- `enrichment_upset_bid.py:158-170` closes a window by writing `{**existing, "in_window": False, ...}`, which is still a non-empty dict. `distress_score.py:254` tests truthiness. Reproduced: window closed at day 60, `upset_bid` FINANCIAL 22 still scored. The dashboard does the same: `dashboard.js:1183` puts any lead with a truthy `raw.upset_bid` in the "foreclosure" stage.
- `enrichment_board_quality.py:149-178` marks `sale_date_passed`, withholds the deal verdict, and rewrites a stale "active" status after 10 days, but it never touches the tier. The only demotion is HOT to WARM at `:181-188` and it requires `auction_status == "presumed_withdrawn"` exactly. `enrichment_pulled_sales.py:164-165` and `board_persist.py:212-213` only set that status when `auction_status` is empty, so a vanished lead whose last status was "active" keeps HOT. Reproduced: `pulled_sale.presumed_withdrawn=True` with status "active" stays HOT, `stale_case` never set.
- `sale_date_passed` has no reader. `grep -c` on `docs/dashboard.js` and `docs/index.html` returns 0, and the writer's own comment (`enrichment_board_quality.py:70-74`) says so.
- `sold_confirmed`, the only exclusion the scorer honours (`distress_score.py:520`), is set in four places: `enrichment_case_detail.py:306-307`, `enrichment_nc_case_status_tyler.py:1131-1132`, `scrapers/counties_nc/buncombe_tax_foreclosure.py:199`, `scrapers/counties_nc/nc_county_tax_foreclosure.py:121`. The date-based `nc_case_status` label "confirmed" (`enrichment_nc_case_status.py:61-105`, any sale > 30 days past) does not set it.
- Ageing exists only in `main.run()` (`board_persist.py:196-216`) and counts runs, not days: `max_misses` 4 (`:111-113`), terminal only when `upset_bid_deadline < now` or the sale is more than 365 days past (`:86-91`). The partial-board scripts (`scripts/recompute_valuation.py:115-142`, `daily_api_refresh.py:290-298`, `merge_today_sources.py:383`, `patch_distress_score.py`) re-run `score_board` without ageing anything.

What is NOT handled anywhere in scoring: an SC redemption period that ended (`redemption_deadline` is read only by the dashboard, `dashboard.js:1137-1160`), a lis pendens that resolved (only the `TERMINAL_AUCTION_STATUSES` drop at `main.py:922` on freshly scraped rows; `court_bid.sale_status`/`upset_status` and `nc_case_status.status` are read by nothing in scoring), a tax delinquency that was paid (only source roll-off plus the four-miss counter), a probate estate that closed (no status field exists).

Failure scenario (reproduced): `foreclosure_sale`, sale date 200 days ago, absentee, equity 0.5, plus a probate flag: HOT. After `enrich_board_quality` the card says `sale_date_passed`, the verdict is gone, the status reads `sale_date_passed`, and the tier is still HOT. In production such a row can survive as a prior-only row (up to four run counts) or because the last full run predates the sale; I did not measure how many do.

Fix: (1) treat a dict as an open window only when `in_window is True` in both the scorer and `stageOf`. (2) In `_signals_for`, take `today` and apply lifecycle rules: sale date passed more than 14 days (NC) with no open window drops `foreclosure_sale`/`court_sale`/`upset_bid` from the score and caps the tier at COLD, with a `stale_reason` on the stack. (3) Downrank on `sale_date_passed` or `pulled_sale.presumed_withdrawn`, not on one exact status string. Effort: 0.5 to 1 day including tests; rule (2) touches `_tier` inputs.

### F3. A stayed foreclosure ranks higher, not lower (high)

Evidence: `enrichment_bankruptcy_stay.py:34-88` derives `bankruptcy_stay` ("foreclosure paused", resume risk by chapter and age). `distress_score.py:272-273` scores any `raw.bankruptcy` as LEGAL 18, a whole extra category, and never reads `bankruptcy_stay`. `web_artifact.py:521` ships the block; `grep bankruptcy_stay docs/dashboard.js` returns nothing, and the dashboard banner at `dashboard.js:4855-4858` says "HIGH-PRIORITY signal". The match itself is a token-subset name match against the last 180 days of three districts (`enrichment_bankruptcy.py:32, 169, 222`), chapter "?" allowed, then the block never expires.

Failure scenario (reproduced): `foreclosure_sale` sale in 5 days, absentee, equity 0.5, plus `raw.bankruptcy` chapter 13: stack 2, score 56, HOT. The automatic stay means the sale will not be held. A bidder drives to the courthouse for a sale the engine itself flagged as paused.

Fix: if `bankruptcy_stay.status == "stayed"` on a foreclosure-type row, do not count BK as a category, cap the tier at WARM, and show "sale stayed" beside the sale date; expire the block on dismissal or discharge (needs a docket recheck) or at a fixed age. Effort: 2 hours for the scorer and dashboard, 1 day for the docket recheck.

### F4. The equity gate is arithmetic, not evidence (high)

Evidence: `enrichment_equity.py:183-211` (`_arv`) uses `assessed_value` first when calc has no ARV (`:205`), and `_payoff` path 5 (`:470-478`) sets payoff = 0.60 x assessed value (0.70 if `tax_aging_high`), confidence "low". Equity is therefore (1 - 0.60) = exactly 40%, or 30% with tax aging. `_equity_band` (`distress_score.py:421-427`) maps `pct >= 0.40` to "high" and `>= 0.15` to "med", and never reads `equity.confidence`. Reproduced for assessed values 80,000 / 150,000 / 333,333: pct 0.400 each, source `assessed_value_estimate`, band high; with `tax_aging_high` 0.300, band med. Where calc ARV is the county figure times a constant (`grading.py:187-194`: `anchor_not_independent`, 15,988 leads, 64% of ARVs) the ratio is still a constant. The weak tier keeps its equity by design (`enrichment_equity.py:63-76`).

The two gates also disagree in the other direction: `enrich_equity` publishes equity for a lead whose calc ran without an ARV when an assessed value exists (`enrichment_equity.py:540`), while `_equity_band` returns None for the same lead (`valuation_ran_without_arv`, inside `distress_score.py:356-433`). The card shows equity, the tier ignores it.

Failure scenario: any delinquent-tax lead with an assessed value and no recorded deed of trust, judgment or last sale shows "equity high" and passes the HOT equity condition without any fact about the mortgage. HOT is then decided by stack and mailability alone.

Fix: make `_equity_band` return a separate `eq_ok` that requires `payoff_source` in {recorded_deed_of_trust, amount_owed judgment or opening_bid} or `confidence` >= medium; publish the estimated band as "unverified" and let it satisfy WARM but not HOT. Effort: 0.5 day plus a test per payoff source.

### F5. One event can make stack 2 (high)

The stack rule counts categories and ignores weight and confidence, so any signal at all completes a category.

Concrete paths, each reproduced with a synthetic listing unless noted:

- Sheriff sale plus foreclosure sale, same parcel: FINANCIAL + SALES, HOT (`distress_score.py:174, 176`). A sheriff sale is the enforcement of the foreclosure. Cross-listing survives when `dedupe` does not merge the rows; `Listing.merge` keeps only the base row's `listing_type` (`models.py:356-430`).
- Foreclosure sale plus REO on one parcel: HOT (`:174, 180`). The REO is the outcome of the foreclosure and the seller is now a lender.
- Tax sale plus `auction` (a county tax sale advertised on an auction platform): same shape (`:177, 179`).
- `price_cut` (SALES 16) at `:226-229` is not gated to MLS listings. A tax lien whose `opening_bid` fell from 9,000 to 4,000 (the owner paying it down, for any source that stores the balance in `opening_bid`; I did not enumerate which do) reached stack 2 and HOT. A foreclosure whose opening bid was revised from 250,000 to 230,000 did too. The docstring at `:187-197` says realtor feeds; the code applies to any listing with `opening_bid`.
- `raw["distressed"] = True` is set by Pickens for 3+ delinquency cycles on a `TAX_LIEN` row (`scrapers/counties_sc/pickens_delinquent_parcels.py:418-420, 433`). The scorer reads it as PROPERTY 8 (`distress_score.py:302-303`). One delinquency record makes FINANCIAL 20 + PROPERTY 8 = stack 2. Not run; read from code.
- Court-verified divorce, deed divorce, `relationship_signal` divorce all land in LIFE_EVENT and collapse to one category. That part is correct.

Fix: (1) collapse the enforcement chain (lis pendens, foreclosure, court_sale, sheriff_sale, upset_bid, REO after a foreclosure) into one category, and keep SALES for market symptoms only (MLS withdrawn, stale, price cut). (2) Gate `price_cut` on `_mls_fields(li)` being non-empty. (3) Remove the Pickens boolean or route it into FINANCIAL severity. (4) Require `stack >= 2` to include at least one category with weight >= 15. Effort: 0.5 to 1 day with tests.

### F6. Name-only matches count as full evidence and no confidence reaches the tier (high)

Evidence and false-positive mechanism per signal:

- Incarceration, state roster (`enrichment_incarceration.py:134-210`): a match is one exact last+first row in the whole DAC/SCDC database. The code never parses status, so "unique name in the database" is treated as "this owner is in custody". The stamp is permanent (`:329` skips already-flagged leads). Jail rosters (`enrichment_jail_bookings.py:395, 537`): `index.setdefault` keeps the first record and there is no uniqueness gate at all; `raw.setdefault("incarceration", ...)` at `:451` promotes the hit into the scored key; `:468` never rechecks, so a release is invisible although `release_status` is stored.
- Bankruptcy (`enrichment_bankruptcy.py:169, 222`): two or more distinctive tokens, subset match, 180-day window, up to 4,000 cases per court. Common two-token names collide. `match_strategy` is stored and unread.
- Court divorce: 5,523 hits, per the 77d7131 message 34% agree on middle initial, 21% conflict (a different person), 45% unverified. The scorer now skips proven conflicts (`distress_score.py:121-130`), leaves the unverified 45% at 12 or 6 points, and never reads disposition. NC filing dates are `MM/DD/YYYY` (`enrichment_nc_divorce.py:117, 202-208`) and `_divorce_signal` uses `date.fromisoformat` inside `except (TypeError, ValueError): continue`, so any NC hit would silently score 0. Latent: that enricher is WAF-walled today.
- Name-resolved probate/court leads: the resolver documents that uniqueness "came from who owns property, not from the name being distinctive" and that 2 of the first 6 Buncombe resolutions were another person (`enrichment_resolve_name_to_property.py`, comment at the `_drop_middle_name_conflicts` docstring, about lines 955-975). `resolved_from_name.confidence` is read by nothing in scoring.
- Owner-name tokens (`HEIRS`, `ESTATE OF`) are record-linked (the name is the record) but undated: a county that never updates the owner leaves a decades-old estate flagged.

Disclosure downstream: the `distress_stack` dict (`distress_score.py:570-575`) carries signal names only. `incarceration.confidence = "name_only_low"` (`enrichment_incarceration.py:168, 205`, `enrichment_jail_bookings.py:451-453`) is stored and unread. The dashboard labels only incarceration "(name match)" and only in the detail panel (`dashboard.js:5084`); the tier badge tooltip lists signal names (`dashboard.js:1793-1798`), so a name match and a court record look identical.

Failure scenario: foreclosure (FINANCIAL) plus a jail-roster name collision (LEGAL 8) is stack 2, HOT with equity and a mailing address. That is the whole premise of a stacked lead resting on a coincidence of names.

Fix: give each signal an `evidence` field (record / name_joined / name_only / inferred) and a `confirmed` flag; name-only signals add score but count toward `stack` only when a second, record-linked category exists; require one record-linked signal for HOT; re-verify or expire incarceration and jail stamps after N days; render evidence type in the badge tooltip. Effort: 1 to 2 days.

### F7. The HOT rule and the ranking are built for the wrong lane (high)

Evidence: `_tier` (`distress_score.py:307-320`) requires `mailable` (`:551`, any truthy `owner_mailing.mailing`) and an equity band (`:545`). A foreclosure auction bidder needs neither an owner's mailing address nor seller equity; the numbers that matter are days to sale, the opening bid against ARV, and lien priority. There is no urgency term anywhere in the Python scorer: `enrich_upset_bid` (`days_remaining`) and `deadlineInfo` in the dashboard (`dashboard.js:1137-1160`, 45-day window, live clock) are separate, and the default sort is `_grade` (`dashboard.js:6`), not tier or deadline.

Reproduced: a foreclosure with a sale in 3 days, owner-occupied, no equity figure: COLD, score 30. Same with equity 0.6 and a mailing address: WARM. A dateless `tax_lien` with a senior exemption and a closed code-enforcement case: HOT, stack 3, score 42. `fullmer_rank.py:39-45` says it "deliberately does not judge the foreclosure lane", yet `rank_board` (`:401-426`) stamps every lead including foreclosures.

Board mix: `docs/MASTER_GAPS_WALLS_AND_MANUAL_LANES.md:79` shows foreclosure_sale 521 and upset_bid 84 against tax_lien 11,442 and recorded_debt 22,806 on a 40,702-lead board. The distressed lane is nearly all of it, so the tier is tuned to the lane where the bug in F1 lived.

Is an upcoming-sale foreclosure ranked above an old delinquent-tax lead? No. Not by tier, and not by any intended design I can find. The stated docstring goal is stacking ("a property hit by multiple distinct categories"), which favours the lead with more record types, not the lead with a deadline.

Fix: two lanes. Foreclosure lane tier = f(days_to_sale or days_left in window, title_risk known and clean, spread vs ARV), `mailable` not required. Distressed lane keeps the stack, with F5 and F6 applied. Sort key: deadline lane first when a live deadline exists. Effort: 2 to 3 days.

### F8. The actionable window is removed before scoring (high)

Evidence: `main.py:1150-1153` partitions `is_sold_pool_candidate` rows out of the active board before `_active_only` (`main.py:915-961`, which grants a 14-day grace precisely to keep the upset-bid window). `enrichment_foreclosure_sold_comps.py:142-170` returns True for the 22 sources in the set at `:108-139` when `0 <= days_since <= 180`. Reproduced with a pinned `now`: a sale yesterday, 5 days ago (inside the NC upset-bid window) and today at 00:00 go to the sold pool; only "today 10:00" and future dates stay active.

Consequence: for law-firm trustee, Master-in-Equity and county tax sources the lead can vanish on the sale day (date-only sale dates) and never appear during the 10 to 14 day window when a bidder can still act. The prior copy may hang on as "presumed_withdrawn" (`board_persist.py:212-213`), which is the opposite of what happened (it sold). Only the published `nc_upset_bids` feed avoids this (`scrapers/national/nc_upset_bids.py:293-324`, dateless lane).

Related: SC tax sales get `redemption_deadline = sale_date + 365` (`enrichment_process_timing.py:57-59`), but `_active_only` drops such rows 14 days after the sale, so the redemption clock is visible for two weeks (except Pickens, `main.py:652`).

Related: `enrichment_nc_case_status_tyler.py:1141-1148` overwrites `sale_date` with the docket's last event date when a sold price is found, so `sale_date` stops meaning the auction date and `enrich_upset_bid` opens a fresh 14-day window from it.

Not verified: whether the carried prior row keeps the lead alive through the window in practice; that depends on run cadence and on how many law-firm rows have an empty `auction_status`.

Fix: partition only when `days_since` exceeds the state window (14 NC), keep SC tax sales active with the redemption clock, and store the true auction date separately from the last docket date. Effort: half a day plus a test with a pinned `now`.

Field usage map for the foreclosure lane (audit question 6):

| Field | Read by | Not read by |
|---|---|---|
| `sale_date` | `_active_only` window (`main.py:947-961`), sold-pool partition (`enrichment_foreclosure_sold_comps.py:164-170`), `enrich_upset_bid` (sale + 14 d), `enrich_board_quality` (`sale_date_passed`), `enrichment_nc_case_status.py:61-105` (date-only status guess), `enrichment_process_timing.py:57-59`, dashboard `deadlineInfo` / `stageOf` (`dashboard.js:1137-1185`) | `score_board`, `_tier`, `intent_score`, `fullmer_rank` |
| `upset_bid_deadline` | written by `enrich_upset_bid`, `enrichment_nc_case_status_tyler.py:939`, `gaston_tax_foreclosures.py:216`, `mcdowell_tax_foreclosure.py:236`; read by `board_persist._is_terminal` (`:86-88`) and the dashboard deadline column | the scorer, which tests `raw.upset_bid` truthiness instead (F2) |
| `redemption_deadline` | written by `enrichment_process_timing.py:57-59` and three scrapers (`pickens_tax_sale`, `spartanburg_delinquent_tax`, `horry_flc`); read by the dashboard only (`dashboard.js:1141, 5087`) | `_active_only`, `_is_terminal`, the scorer |
| `sale_time` | display only (`sheets.py:48`, `dashboard.js:4319`) | everything else |
| `opening_bid` | payoff proxy in equity (`enrichment_equity.py` HEAD `:404-414`, confidence low), `amount_owed` "opening_bid" source, calc bid and ROI, the scorer's `price_cut` (F5, the only scorer read), `enrichment_court_bid` fill | title risk, urgency |
| `judgment_amount` | `amount_owed` (source judgment, high), equity payoff, `fullmer_rank.py:337-338` (+6) | the scorer directly |
| `case_number` | `Listing.dedupe_key` case branch (`models.py:339-345`), `dedupe._strong_sigs`, NC and SC court lookups, `fullmer_rank.py:298` (`case_number and "tax" in src` adds 20 points) | the scorer |
| days to sale | `upset_bid.days_remaining` and `nc_case_status.days_since_sale` (both frozen at build), `enrichment_nc_case_status_tyler.py:1034-1044` orders court lookups by proximity, dashboard `deadlineInfo` and the `days_to_auction` export column (`dashboard.js:5204, 5262`, live) | any ranking in Python; the default sort is `_grade` |

### F9. The parcel key fuses unrelated properties (high in principle, prevalence unmeasured)

Evidence: `_parcel_key` (`distress_score.py:436-440`) is `p:{state}:{parcel_id stripped to alphanumerics}`. No county, no rejection of digitless or placeholder ids. Reproduced: Anderson and Pickens sharing parcel "123-45-6" fuse a tax lien with a probate notice and both read HOT; "N/A", "0", "TBD", "UNKNOWN" each map to one key per state. `dedupe.py` has its own digitless guard for exactly this ("'ehurst' linked 122 Pinehurst properties"); the scorer does not use it. `score_board` then assigns one shared `ds` dict to every listing in the group (`:577`), and `enrichment_board_quality.py:184-188` mutates it in place, so a downrank on one sibling re-tiers the others (contrast `retract_equity_rank`, which copies first, `:323-353`).

Fix: key on (state, county, parcel) and reject ids with no digit or under 4 characters; copy `ds` per listing. Effort: 1 hour plus a test.

### F10. Weights depend on the scraper's choice of listing type (medium)

Evidence: standing delinquent rolls are emitted as `TAX_SALE` (30) by `scrapers/counties_sc/qpaybill_delinquent_roll.py:827` (19 counties, on the order of 40,000 rows), `spartanburg_delinquent_tax.py:155`, `sc_tax_delinquent.py:186`, and county-owned FLC inventory by `sc_flc.py` and `terry_howe_flc.py`. The NC rolls (`nc_ptscloud_delinquent_tax`, `buncombe_delinquent_tax`, `transylvania_delinquent_tax`, `nc_county_csv_delinquent_tax`, `rutherford_tax`) use `TAX_LIEN` (20).

Consequence: an SC roll row (year-one delinquent, maybe already paid) scores 30 and reaches WARM alone through `score >= 28 and eq_ok`, and F4 supplies the equity. The same NC fact needs an absentee bonus. An FLC parcel is county-owned; the "distressed owner" no longer holds title but the row can still be HOT.

Fix: one type for "delinquent roll"; weight by years delinquent and amount (the ripeness ramp exists in `fullmer_rank.py:204-217` but the script that writes the years is not in the pipeline, see F17); exclude FLC from owner-motivation scoring. Effort: 0.5 day.

### F11. Six listing types and many collected signals never reach the score (medium)

Never scored by listing type (reproduced, all return no signals): `divorce_notice`, `estate_lead`, `hoa_sale`, `bankruptcy`, `elderly_disabled`, `tax_sale_overage`. The first NC divorce path (`scrapers/counties_nc/nc_ecourts_divorce.py:198-232`) emits `DIVORCE_NOTICE` with no `relationship_signal`; the judgments path (`:633-664`) does set one and scores 15. A bankruptcy filing on an owner resolved to a parcel is unscored, while the name-subset cross-reference onto a foreclosure row scores 18 (F3). An HOA foreclosure with a sale date scores nothing.

Collected, written, never read by the tier: `raw['storm_damage']` (`enrichment_helene_damage.py:543`; `enrichment_lead_signals.py:116-120` reads `raw['helene']`, a different key), `liens` / `lien_priority` (equity only), `derivation_flags` (free_and_clear, tired_landlord), `owner_cluster`, `repeat_tax_loss`, `vacant` / `vacancy` / `vacant_lot` / `builder_distress` (chip only), `owner_name_signal` (Fullmer only), `court_bid`, `nc_case_status`, `bankruptcy_stay`, `deed_chain.distress_transfers`. `usps_vacancy` is ZIP-level market context and correctly unscored. `tax_owed` was unscored at 77d7131; 4bc5792 now credits a real balance.

Dead or off-pipeline code: `enrichment_probate_search.py` is not called by `main.py` (only by `scripts/enrich_board.py`). `enrich_life_events` appends `estate_elderly` to `distress_stack.categories` (`enrichment_life_events.py:43-47`) but runs at `main.py:2773`, before `score_board` (`:3000`) creates the stack, so the append lands on a stale prior-run dict that is then overwritten; `enrichment_sc_divorce.py:340-344` and `enrichment_nc_divorce.py:270-273` do the same with `divorce`. `distress_score.py:277` reads `raw.estate`, which nothing writes.

Fix: decide per item: score it, label it display-only in one place, or delete it. Effort: half a day for the ledger, 1 day if any are scored. Storm damage and vacancy are the two that most plausibly deserve a category.

### F12. Closed and resolved records score as open (medium)

Evidence: `enrichment_code_enforcement.py:239-246` writes the block even when every violation is closed (`has_open` False, `open_violations` 0); `distress_score.py:300` tests truthiness (reproduced: closed block scores PROPERTY 14). Nothing clears the block when the feed stops returning the case. Bankruptcy `date_filed` is unused for age; jail `release_status` / `scheduled_release` (`enrichment_jail_bookings.py:441-449`) are stored and unused; probate has no closure state; Helene placards carry no repair state.

Fix: gate code enforcement on `has_open`; add a `stale_after` per signal and clear positives on the enrichers that stamp them (only `derivation_flags` and `upset_bid` clear today). Effort: half a day.

### F13. "N signals" chip and `signal_stack` count synonyms (medium)

Evidence: `_facet_signals` (`enrichment_lead_signals.py:72-129`) adds facet names on top of the distress signals. Reproduced: one Helene placard reads 2 signals (`helene_unsafe`, `storm_damage`); one tax delinquency reads 3 (`tax_lien`, `tax_delinquent`, `recorded_debt`); one probate notice reads 4 (`probate`, `probate_deed`, `probate_notice`, `probate_estate`). The dashboard prints "N distinct distress signals" when N >= 2 (`dashboard.js:1752-1760`), so every tax-delinquent lead advertises a stack. `enrichment_life_events.py:16-21` also tags `TRUST` and `\bESTATE\b` (so "ACME REAL ESTATE HOLDINGS LLC") as `estate_probate`, which becomes `probate_estate` in the chip and `probate` in `enrichment_strategy_fit.py:63`. `intent_score` is computed before board quality and QA run (`main.py:3155` vs `:3318`) and ignores `stale_case` and `sale_date_passed`, so `intent_band` can stay "hot".

Fix: canonicalise facets to the scorer's signal names, count distinct categories, drop `trust` and bare `ESTATE` from probate. Effort: 2 hours.

### F14. Bare-string `owner_mailing` makes 5,098 leads un-HOT-able (medium)

Evidence: `distress_score.py:548` keeps only dict mailing blocks. `mailing_shape.py` (docstring) records that `spartanburg_vacant`, `spartanburg_condemned` and `spartanburg_delinquent_tax` write a bare string, 5,098 leads on the 2026-08-03 board; `enrichment_lead_signals.py:123` uses `mailing_dict`, the scorer does not. Those leads get no absentee bonus, `contactable` False, no HOT. Under-ranks core-county SC leads, the opposite direction to F1.

Fix: use `mailing_dict` in `score_board`. Effort: 15 minutes plus a test.

### F15. Relative-time fields are frozen at build time (medium)

Evidence: `in_window`, `days_remaining` (`enrichment_upset_bid.py:141-150`), `sale_date_passed_days` (`enrichment_board_quality.py:152-154`) and the tier are computed when a script runs. The dashboard renders the stored "Upset-bid window: OPEN (Nd left)" (`dashboard.js:5081`) beside a live deadline column (`:1137-1160`) that recomputes. Several partial-board scripts write the board without re-running these enrichers, and the git log shows the board being patched by targeted passes (`6d41e4e`, `0549327`, `57e931d`).

Fix: compute open/closed and days at read time from `upset_bid_deadline` / `sale_date` and delete the stored counters; re-derive tier when a date crosses. Effort: half a day.

### F16. WARM is reachable on absentee status plus any 8-point attribute (medium)

Evidence: `_tier` (`distress_score.py:318-319`): `absentee and stack >= 1 and score >= 20`. Absentee 8 + out-of-state 4 = 12, so any single 8-point item finishes it: `senior_exemption`, `distressed_condition`, `incarceration`, a zero-consideration quitclaim. Reproduced on the 09:52 tree (F1 already fixed): out-of-state owner with an elderly exemption and nothing else is WARM. Absentee is roughly half the board (`fullmer_rank.py:343-359`).

Fix: raise the floor to 28, or require a non-attribute signal. Effort: 15 minutes.

### F17. Silent-failure inventory (medium)

- `main.py:3009-3010`: `score_board` failure is logged and the run continues with prior-run tiers still on the rows; `enrich_lead_signals` and Fullmer then read them. No alarm.
- `enrichment_lead_signals.py:240-242`: per-listing exception swallowed with a warning; a stale `intent_score` survives.
- `distress_score.py:443-457`: `_prior_price_index` returns `{}` on any read error (price_cut silently off) and reads and parses the whole board JSON to do it (`docs/listings.json` is 1,159,462,490 bytes).
- `main.py:964-976, 1165-1166`: `_safe_pred(..., False)` drops a lead on any predicate exception with only a log line.
- `enrichment_derivation_flags.py:118-119, 132-133`: `except Exception: pass` turns a bad date into "no tenure, no flag".
- Positives are stamped and never cleared: bankruptcy, incarceration, jail, probate, code enforcement, storm damage.
- Writer with no reader: `sale_date_passed`, `bankruptcy_stay`, `court_bid`, `storm_damage`, `nc_case_status`, `owner_cluster`, `repeat_tax_loss`. Reader with no writer: `raw.estate`, `raw.vacant`.
- `tax_aging_surfaced`, `two_year_delinquent`, `tax_aging_high` are read by `fullmer_rank.py:186-201` and `enrichment_equity.py` (0.70 payoff branch) but written only by one-shot scripts (`scripts/surface_tax_aging.py`, `scripts/backfill_tax_aging.py`) for one source, so years-delinquent goes stale and new leads never get it.
- Two copies of the active filter: `scripts/ingest_fresh_court_leads.py:96-115` (`_active_keep`) differs from `main._active_only` (keeps all dateless leads).
- No test of `_tier`, `score_board` composition, stale dates or cross-listing (only `tests/test_arv_sanity.py:964-975`).

Fix: raise a run-health error when `score_board` fails; return "stamped_at" on each positive and a shared expiry helper; move the tax-aging derivation into the pipeline. Effort: 1 day.

### F18. Title-risk "unknown" is treated as clean (low to medium)

Evidence: `enrichment_title_risk.py:329-354` returns `{"kind": "unknown"}` for an unrecognised party and nothing at all when no party text exists. `distress_score.py:559-565` reads only `surviving_senior_debt_risk`, so unknown and missing pass the HOT gate, and even a proven junior-lien trap stays WARM with only -20. Fix: unknown or missing party on a foreclosure type is not HOT-eligible; junior-lien risk caps at COLD for a bidder view. Effort: 15 minutes.

### F19. Parallel rankings and a legacy equity flag (low)

Four scores rank the same row from different inputs: tier, `intent_score`, `fullmer.rank`, `grade`. Default sort is `_grade`. `flags.py:60-73` still computes `high_equity` from a Zestimate or `tax_value * 1.25` minus last sale or judgment and the dashboard renders it as a green chip (`dashboard.js` badge regex), outside the ARV trust gate. Fix: choose one primary ordering and retire the legacy flag. Effort: 1 hour for the flag, a decision for the rest.

## (d) Checked and found sound

- Distinct-category stack with best-weight-per-category: liens and repeat filings do not triple-count (`distress_score.py` score sum). The foreclosure chain lis pendens, court_sale, upset_bid, foreclosure_sale correctly collapses into FINANCIAL.
- ARV trust gate: one definition (`grading.py:337`, `ARV_TRUST_BLOCKS_DERIVED`) used by calc, `enrich_equity` and `_equity_band`, plus the `withheld` marker and the no-ARV guard. Reading and the passing tests agree.
- `retract_equity_rank` copies the stack before editing and re-derives through the single `_tier`; a late retraction cannot re-promote to HOT.
- `sold_confirmed` excludes a parcel from scoring and from lead signals and is honoured by persistence.
- `_active_only`: terminal court statuses drop fresh rows; the state-aware 14-day grace is reasoned against the statute; the dateless whitelist is documented row by row.
- `enrichment_board_quality`: withholding the verdict on day one after the sale date and preserving the source wording in `auction_status_reported` is right, and refusing to set `sold_confirmed` on a date alone is the correct call.
- Court divorce: role filter, attorney and guardian rows excluded, recency decay, and the new middle-initial skip, with 16 tests.
- Helene severity weights are graded and tested.
- `enrich_upset_bid` uses 14 days as a conservative reading of NCGS 45-21.26/27 and skips published deadlines so stacked upsets are not deleted; `nc_upset_bids` withholds `sale_date` to keep an open window through `_active_only`.
- `fullmer_rank`: never drops a lead (asserted), refuses to treat judgments or opening bids as tax arrears (`:165-183`), and avoids double-counting one death via the `blob_probate` guard (`:324-327`).
- Incarceration state lookups: failed lookups are never stamped as "checked, no match", host blocks stop the run, single-exact-row gate on state rosters.
- `mailing_shape.mailing_dict` is the right normaliser (used by lead signals).
- `enrichment_derivation_flags` clears stale blocks and guards the surname-first ROD parser era.
- `enrichment_title_risk` checks senior parties before junior patterns so a bank trustee carrying "association" is not misread.
- `enrichment_data_quality` flags contain no signal-recency claims to contradict, and the ARV caveat ordering is asserted by `tests/test_enrichment_order.py`.

## (e) What I could not verify

- Live-board prevalence of anything. I did not load the board. Counts quoted from other files are quoted, not re-measured: the signal histogram (`MASTER_GAPS_WALLS_AND_MANUAL_LANES.md:79`, 2026-08-18 board), the 5,098 bare-string leads (`mailing_shape.py`, 2026-08-03), the divorce verdicts (77d7131 commit message), and the 16,142 / 33,259 and 644 / 1,646 figures (the other session's docstring). Unmeasured: how many HOT leads carry a past sale date, how many HOT leads rest on `assessed_value_estimate` equity, how many parcel ids collide across counties, how often law-firm rows have an empty `auction_status`.
- Whether F8's prior-row carry actually keeps a sold lead visible through its upset window. That depends on run cadence, which I did not trace.
- Commit 4bc5792 (`is_countable_debt`, `_real_tax`, `tests/test_recorded_debt_signal.py`). I smoke-tested the 09:52 working-tree version and saw F1 stop reproducing; I did not audit the `_real_tax` branch beyond the generic-key concern in F1, and I did not re-run anything against the committed result.
- Rendered dashboard behaviour. I read `docs/dashboard.js` but did not render it.
- NC DAC OPI semantics (does the result list include released offenders). Inferred from the absence of any status parsing in the code; not checked live, no network use.
- `valuation/calc.py` (2,552 lines) beyond the flag classification the gates consume; `enrichment_board_qa.py` beyond the retraction path; `enrichment_data_quality.py` by search only.
- Which of Fullmer's `tax_aging_*` inputs are still populated on the live board.
