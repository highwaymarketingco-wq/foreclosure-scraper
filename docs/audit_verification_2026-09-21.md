# Audit verification, 2026-09-21

A second, read-only look at the claims in `docs/AUDIT_2026-09-21.md` and `docs/audit_signal_logic_2026-09-21.md` that were quoted from other files, measured on a different board, or marked unverified. Every number below was measured on the board, not quoted.

## Basis and limits

- **Boards.** The live board `docs/listings.json.gz` as written by the 10:10 daily refresh: 170,066 rows, HOT 2,081, WARM 73,224. To decide whether a mismatch is a wrong number or a different board, I also streamed the previous committed board (commit 6d41e4e, the 170,528-row board the audit measured, extracted with `git show` into the session scratchpad). Both were scored by the pre-fix scorer.
- **What I did not do.** No `load_board`, no `write_artifact`, no board-writing script, no network, no edit outside this file and `docs/scraper_registry_reconciliation_2026-09-21.md`, no git add, commit, push or stash.
- **Passes.** Four streaming passes over the live board and two over the 09:34 board, each 10 s and about 350 MB peak: six streams against a budget of five, and the sixth was over the older board. A few partial reads of the first rows (schema checks) are not counted. Scripts are in the session scratchpad under `verify/`.
- **The working tree is moving.** Uncommitted edits by another session already contain fixes for F3, F4, F5, F6, F7, F9, a divorce date parser and a `load_board` drop guard. Nothing here re-scores the board. Measurements use the tiers and `distress_stack` stored on the board; where I call code I say whether it is committed HEAD (84bca51) or the working tree.
- **Equity is row-level.** The scorer takes the best equity across every listing sharing a parcel key, so a row's own `raw.equity` can differ from the equity that set its tier. That is why 152 HOT rows have no equity figure of their own (item 1).

## Summary

### Corrections (the audit number was wrong or misread)

| # | Audit said | Measured | Note |
|---|---|---|---|
| C1 | 209 registered scrapers | **229** | 209 is the 8/29 run's count; 9/8 logged 218. See the registry report. |
| C2 | WARM "at least 71,010", "about 71,000" | **73,791** on the 09:34 board, 73,224 now | The lower bound is true and understates by 2,781. |
| C3 | 5,098 bare-string `owner_mailing` leads can never be HOT | **2,071** now (2,137 on 09:34), all WARM, none HOT | 5,098 is the 8/3 figure. The conclusion holds. |
| C4 | 369 multi-row parcel keys (1,132 rows) as the size of the F9 fusion risk | Reproduced as **368 keys, 1,130 rows** of same-county duplicates. Actual cross-county fusion is **35 keys, 71 rows**; placeholder fusion is **3 keys, 304 rows** | The 369 are mostly legitimate second rows on one parcel. "65,261 distinct keyed properties" was not reproduced (53,707 by parcel, 74,524 by `dedupe_key`). |
| C5 | Ledger "debt-known" rose 29,274 to 63,806 | 63,806 is the count with a real `tax_owed.balance`. Countable debt under the new definition is **65,367** on the same board (65,344 now) | The ledger column does not share the F1 flaw, but it understates by 1,561. |
| C6 | 16,142 of 33,259 `recorded_debt` signals are estimates | 33,259 exact; **16,037** under the committed `is_countable_debt` | 105 judgment or opening-bid proxies now count. |
| C7 | A7: "no reconciliation of the registry" | `docs/SOURCE_REGISTER.md` (9/15) and `scripts/triage_zero_row_sources.py` exist | Both stale; replaced by the registry report. |
| C8 | F2: "52 HOT leads carry a passed sale date" | 52 is exact, but **21 of the 52 are New Hanover demolition-permit dates** | Now 196, of which 129 are liensnc filing dates. |

### New findings

| # | Finding | Size |
|---|---|---|
| N1 | One placeholder parcel id, `ROW`, fuses 130 unrelated Carteret County properties into a single HOT stack. It explains the audit's untraced "liensnc 131 new HOT". | 130 of 2,081 HOT (6.2%) |
| N2 | `Escrow :` fuses 119 unrelated Transylvania tax liens into one WARM stack carrying an `upset_bid` signal that belongs to one of them; `BOGUE SOUND` fuses 55. | 174 WARM rows |
| N3 | 80% of HOT rests on the assumed payoff (equity exactly the arithmetic 40%); only 15 HOT leads have a recorded deed of trust. | 1,668 of 2,081 |
| N4 | Sold leads stay on the board unlabelled: 54 rows sold within 14 days, 49 with empty `auction_status`, none with an `upset_bid` window. | 54 rows |
| N5 | `sc_tax_delinquent` scraped 1,334 rows on two runs and none landed; `run_meta` calls it EMPTY (verified). | 1,334 rows |
| N6 | Per-source run health is wrong for every scraper that emits child slugs; and `rutherford_wildfire_tax` (29,319 delinquent bills) is held back by a robots gate the owner retired on 9/20. | see registry report |
| N7 | The middle-name rule cannot resolve any of the 2,484 unverified divorce hits. A cross-check against other name strings on the row resolves 165 (6.6%). | 2,484 hits |
| N8 | Freshness figures depend on how a day is counted; the audit's table is exact under calendar days and 21% off in the first bucket under elapsed hours. | see item 7 |

### Confirmed

Validation drops (0 of 170,066), the NC divorce date bug on committed code, no county 4,503, flip leaks 102, generic `distressed` tag 23,722, liensnc WARM 38,289, WARM 73,224, HOT 2,081, freshness buckets, divorce 34/21/45, F1 and A3 stack effects (within 5%), F2 prevalence.

---

## 1. HOT and WARM equity: assumed payoff or evidence

**Question.** How many current HOT and WARM leads have equity whose payoff is the arithmetic assumption, against evidenced (deed of trust, judgment, opening bid)?

**Method.** One pass. For each HOT or WARM row (`raw.distress_stack.tier`), read `raw.equity`: `payoff_source`, `confidence`, `pct`. "Evidenced" is `enrichment_equity.equity_is_evidenced` from the working tree (payoff from a recorded deed of trust, judgment, opening bid, foreclosure proxy, or confidence medium or better; a tax balance is not evidence of the mortgage). I also report the raw `payoff_source` so the result does not depend on that function.

**Numbers, current board.**

| Tier | Rows | Evidenced | Assumed or low-confidence | No equity figure on the row |
|---|--:|--:|--:|--:|
| HOT | 2,081 | 261 (12.5%) | 1,668 (80.2%) | 152 (7.3%) |
| WARM | 73,224 | 2,749 (3.8%) | 9,289 (12.7%) | 61,186 (83.6%) |

Payoff source, HOT: `assessed_value_estimate` 1,461 (70.2%), `last_sale_amortized` 184, `amount_owed:judgment` 85, `foreclosure_proxy:opening_bid` 64, `amount_owed:opening_bid` 63, `foreclosure_proxy:judgment_amount` 34, `amount_owed:tax_owed` 23, `recorded_deed_of_trust` 15. Confidence: low 1,743, high 183, medium 3.

Payoff source, WARM: `assessed_value_estimate` 7,988, `amount_owed:judgment` 848, `amount_owed:opening_bid` 768, `amount_owed:tax_owed` 635, `foreclosure_proxy:opening_bid` 623, `last_sale_amortized` 666, `foreclosure_proxy:judgment_amount` 503, `recorded_deed_of_trust` 7.

Every HOT lead has an equity band of high (1,886) or med (195), as the HOT rule requires. Of those, 1,820 (87.5%) are not evidenced. The `assessed_value_estimate` percentages are the constants the audit predicted: 40.0% on 133 HOT and 1,160 WARM rows, and other fixed values (66.9%, 73.2%, 78.6%) where the ARV is anchored to the county appraisal.

The 152 HOT rows with no equity figure of their own take their band from a parcel-mate: 127 are in the `ROW` group (item 2), 25 elsewhere. None has an ROI fallback.

HOT resting on assumed equity, by source: New Hanover demolition permits 645, Spartanburg delinquent tax 193, NC heir-estate parcels 191, liensnc 129, HUD REAC inspection 108, Spartanburg city condemned 63, Spartanburg condemned 48, Henderson code violations 44.

Same measure on the 09:34 board: HOT 1,646, of which 1,392 assumed (84.6%), 225 evidenced (13.7%), 29 no figure.

**Verdict.** CONFIRMED (F4). The HOT equity gate is met by an assumption for 80% of HOT, 87.5% counting rows with no figure. Only 261 HOT leads (12.5%) have equity that rests on a fact about the debt.

**Fix implied.** The `eq_evidenced` gate that is in the working tree removes about 1,820 leads from HOT if it lands as written. Land it, then re-measure. Publish estimated equity as "unverified" on the card.

## 2. Parcel-key collisions and placeholders

**Question.** How many parcel ids occur in more than one county, how many are placeholders, and how many current stacks fuse unrelated properties?

**Method.** Recreate the committed scorer key (`p:{state}:{alphanumeric parcel, lower case}`, no county) over every row with a parcel id. Group by it. Count groups spanning more than one known county. Flag a placeholder as an id with no digit, fewer than four alphanumerics, or all zeros (the working-tree rule).

**Numbers, current board.**

| Measure | Value |
|---|--:|
| Rows with a parcel id | 106,603 (63,463 have none) |
| Distinct scorer keys | 103,634 |
| Keys with 2 or more rows | 967 (3,936 rows) |
| Keys spanning 2 or more counties | **35** (71 rows; 2 HOT, 53 WARM). 39 keys, 79 rows if a blank county counts as a county |
| Placeholder rows | **322** (NC 314, SC 8), 20 distinct values |
| Placeholder keys with 2 or more rows | 3 keys, 304 rows |
| Rows whose stack is shared across unrelated properties | 375 (71 + 304), in 38 groups |
| Of those, HOT | 132 (130 + 2), 6.3% of HOT |

On the 09:34 board the cross-county count was 45 keys, 91 rows (6 HOT, 55 WARM).

The three placeholder groups:

| Parcel id | County | Rows | Distinct owners | Sources | Shared stack | Tier |
|---|---|--:|--:|---|---|---|
| `ROW` | Carteret | 130 | 115 | liensnc 127, Brock & Scott foreclosure sale 1, HUD Section 8 1, Crexi multifamily 1 | FINANCIAL + PROPERTY, score 48; signals `distressed`, `foreclosure_sale`, `recorded_debt`, `tax_lien` | **HOT (130)** |
| `Escrow :` | Transylvania | 119 | 119 | Transylvania delinquent tax | FINANCIAL, score 34; includes `upset_bid` | WARM (119) |
| `BOGUE SOUND` | Carteret | 55 | 35 | liensnc | FINANCIAL, score 28 | WARM (55) |

All 35 cross-county groups carry one identical shared stack. Typical case: NC parcel `6827305216` puts Burke and Forsyth liensnc rows on one stack; SC `1360002001` puts a Spartanburg tax sale and an Anderson DEW lien on one.

The literal placeholders the audit listed ("N/A", "0", "TBD", "UNKNOWN") do not occur on the board. The real ones are `ROW`, `Escrow :` and `BOGUE SOUND`; the other 17 flagged values are short lot-style numbers (`82-4`, `843`) that may be legitimate.

**The 369.** The (state, county, alphanumeric parcel) key over the 18 footprint counties gives 368 multi-row keys and 1,130 rows on the 09:34 board, against 369 and 1,132 in the audit, out of 53,707 distinct keys. `Listing.dedupe_key()` gives 376 keys and 1,029 rows out of 74,524. The audit's 65,261 distinct properties is not reproduced by either. These are same-county duplicates (one parcel appearing in more than one source), which is what the scorer's grouping is meant to merge. They are not the F9 fusion risk.

**Why `ROW` is HOT.** At 09:34 the same 130 rows were WARM (0 HOT); after the 10:10 rescore all 130 are HOT. The shared stack has two categories: FINANCIAL (the liensnc tax liens and one Brock & Scott foreclosure sale dated 2026-07-16, 67 days ago) and PROPERTY (the generic `distressed` tag on the HUD and Crexi records), plus an equity band of high and a mailable owner taken from group-mates. I did not trace which member changed between the two boards. Either way, 127 liensnc rows that contribute only a tax lien inherit a foreclosure and a distress tag from three other properties. That accounts for the audit's untraced "liensnc 131 new HOT" (3 to 131) and about 6% of all HOT.

**Verdict.** F9 CONFIRMED and now measured: small across counties (35 keys), large in three placeholder groups (304 rows, 130 of them HOT). C4 and N1, N2 above.

**Fix implied.** The county-scoped key with placeholder rejection in the working tree ungroups all 38 groups; with liensnc context-only the 130 `ROW` rows leave HOT. `scripts/clear_junk_parcel_ids.py` already clears ids with no digit or under four characters (measured 9/13 at 1,258 liensnc rows), so `ROW`, `Escrow :` and `BOGUE SOUND` came back after it ran, or it was not re-run. Its docstring says the dedupe guards refuse to merge on a digitless parcel and so "they are not fusing rows"; that holds for dedupe and not for the scorer, which had no such guard. Re-run the script and add the same guard at ingest.

## 3. F8: sold-pool sources and the upset-bid window

**Question.** Among rows from the 22 sources in `FORECLOSURE_SALE_SOURCES`, how many have a sale within the last 14 days, are they still on the board as active, and how many have an empty `auction_status` with a past sale date?

**Method.** The 22-slug set from `enrichment_foreclosure_sold_comps.py` (22 slugs, same at HEAD and in the working tree). One pass. Days since `sale_date` against today; `auction_status`, `raw.upset_bid`, `raw.sale_date_passed`, `last_seen`.

**Numbers, current board.** 15 of the 22 sources have rows (4,988 rows). Seven have none: `aldridge_pite`, `korn`, `finkel`, `henderson_tax`, `polk_tax`, `sc_tax_delinquent`, `bid4assets`.

| Days since sale | Rows | Empty status | Other statuses | Tier | `upset_bid` block | Seen in last 7 days |
|---|--:|--:|---|---|--:|--:|
| Future | 62 | 56 | pending 4, active 1, active - postponed 1 | WARM 43, COLD 18, HOT 1 | | |
| 0 to 14 | **54** | **49 (91%)** | referred to master 2, presumed_withdrawn 2, sale_date_passed 1 | WARM 46, COLD 5, **HOT 3** | **0** | 4 |
| 15 to 180 | 219 | 90 | presumed_withdrawn 118, sale_date_passed 7, other 4 | WARM 123, COLD 91, HOT 5 | 29 (23 in window) | 16 |
| Over 180 | 24 | 15 | presumed_withdrawn 9 | WARM 18, COLD 6 | | |
| No date | 4,629 | 4,340 | | | | |

Rows with a past sale date and an empty `auction_status`: 49 + 90 + 15 = **154**. Law-firm rows overall (9 `law_firms.*` sources): 339, of which 110 (32%) have an empty status; 191 are past-dated and 62 of those (32%) have an empty status. The 0-to-14-day rows come from Hutchens 25, Brock & Scott 16, Rogers Townsend 7, Bell Carrington 5, McMichael Taylor Gray 1. All 54 carry `sale_date_passed`; 10 have an `nc_case_status` block.

**Reading it.** The HEAD partition (diverting `0 <= days <= 180` before the upset window) cannot be seen firing here, because no full run has written this board since 8/29. What the board shows is the other half of the F8 question: yes, the prior-row carry keeps a sold lead visible through the 14-day window, and past it (219 rows), but it does not label it. Nothing on 54 rows says "sold" or "in upset window": 49 have no status, none has an `upset_bid` block, only 4 were refreshed in the last week, and the scorer ignores `sale_date_passed` (F2), so 3 are HOT and 46 WARM.

**Verdict.** CORRECTED framing, NEW FINDING (N4). The hazard on the current board is stale sold leads scored as live, not a vanished window.

**Fix implied.** The state-window partition in the working tree is right. In addition, stamp `auction_status` (or a `sold` flag) from `sale_date_passed`, and let the scorer cap on it (F2). `presumed_withdrawn` is the carry's guess and is wrong for a lead that sold.

## 4. Silent row loss in `load_board`

**Question.** Does `except Exception: pass` around `Listing.model_validate` drop rows?

**Method.** `Listing.model_validate(row)` on every streamed row, counting failures and keeping the first messages.

**Numbers.** **0 failures of 170,066** (0 of 170,528 on the 09:34 board). No error messages to report. `logs/board_load_dropped.jsonl` holds 11 lines, all from unit tests (sources `x`, `src.1`).

**Caveat.** I validated the slim rows. `load_board` merges the detail sidecar into `raw` first; `raw` is `dict[str, Any]`, so that cannot introduce a failure, but I did not run it.

**Verdict.** CONFIRMED: no loss today. Committed HEAD still has the bare `except Exception: pass`; the counted, logged and rate-limited drop guard is in the working tree only.

**Fix implied.** Commit the guard (`BoardLoadDropError` at 0.1%). The risk is latent: a new scraper writing an unexpected `listing_type` would drop its rows silently on the next writer pass.

## 5. NC divorce date format

**Question.** Does `_divorce_signal` return nothing for an NC hit filed `MM/DD/YYYY`?

**Method.** Call `_divorce_signal` on a synthetic hit (`today = 2026-09-21`, party role Plaintiff) at three code versions. The two older versions were loaded from `git show` into throwaway modules.

| Version | NC `03/15/2025` | NC `11/02/2022` | NC ISO `2025-03-15` | SC ISO `2025-03-15` |
|---|---|---|---|---|
| 77d7131 (audit basis) | **None** | **None** | `('divorce','LIFE_EVENT',12)` | same |
| HEAD 84bca51 | **None** | **None** | same | same |
| Working tree (uncommitted) | `('divorce','LIFE_EVENT',12)` | `('divorce','LIFE_EVENT',6)` | same | same |

The board has no NC divorce hit: all 5,510 are `sc_fccms`, and all 15,781 case dates are ISO.

**Verdict.** CONFIRMED on committed code, latent on the board. Already fixed in the working tree with `signal_freshness.to_date`.

**Fix implied.** Commit it, with a test for the slash format.

## 6. Divorce hits: can the 45% unverified be checked offline

**Question.** How many of the court-divorce hits carry a case number or party middle name that would let the unverified ones be checked offline?

**Method.** `name_normalize.party_middle_verdict` on every hit, split the unverified by reason, then test what else on the row could decide them.

**Numbers.** 5,510 hits now (5,523 on 09:34; the 462 rows dropped by the daily refresh took 13 hits).

| Verdict | Current | 09:34 (audit) |
|---|--:|--:|
| agrees | 1,877 (34.1%) | 1,882 |
| conflict | 1,149 (20.9%) | 1,153 |
| unverified | 2,484 (45.1%) | 2,488 |

No hit carries the `match` stamp yet (0 of 5,510). Proven wrong-person hits still stand on 44 HOT and 587 WARM leads until a rescore applies the conflict rule.

The 2,484 unverified, by why:

| Reason | Hits | Share |
|---|--:|--:|
| Owner has no middle initial | 1,222 | 49.2% |
| Matched party has no middle name | 1,003 | 40.4% |
| No party matches the owner's first and last name | 148 | 6.0% |
| Owner name not parseable | 111 | 4.5% |

What is on the record for those 2,484: a case number 100%, a parties string 100%, a filed date 100%, the same county as the property 100%. A party side with a middle name: 2,010 (80.9%), but the middle-initial test needs a middle on both sides, so it can decide none of them as it stands.

What would decide some of them offline:

- **Another name string on the same row** (`qpaybill_roll`, `owner_cluster`, `skip_trace` and others) carrying the owner's first and last name with a middle initial: 1,308 hits (52.7%). With one consistent middle, re-running the verdict gives 28 agrees and 137 conflicts, 165 hits (6.6%). The rest stay unverified because the party has no middle. This is a heuristic; a co-owner with the same name would fool it.
- **Both parties are the two joint owners** (`SMITH JOHN & MARY` against a case `MARY SMITH vs. JOHN SMITH`): 50 hits (2.0%). That is corroboration, not a name coincidence.
- **The case number** is the only route for the remaining roughly 90%: a case-detail fetch (network, SC court site), 2,484 lookups. It is present on every hit.

Also: 45 hits are attorney or guardian-only (the role filter already excludes them), cases per hit run 1 to 6+ (3,013 have one case, 424 have six or more), and where a hit has several cases the verdict function returns unverified as soon as one party lacks a middle name.

**Verdict.** CONFIRMED (34/21/45, within 5 hits of the audit on the same board). NEW FINDING: offline resolution is possible for about 8% at most.

**Fix implied.** Apply `scripts/annotate_divorce_match.py --apply` as the only board process to stamp the verdict. Add the spouse-pair test as a fourth verdict, `corroborated`. Decide whether 2,484 polite case-detail fetches are worth it; until then keep the unverified hits at a lower weight or out of the stack count (F6).

## 7. Re-measured audit numbers

| Audit figure | Current board | 09:34 board | Verdict |
|---|--:|--:|---|
| Rows with no county 4,503 (NC tax_lien 3,745; SC bankruptcy 397; NC bankruptcy 340; REO 21) | 4,503, same split | 4,503, same | CONFIRMED. By source: liensnc 3,745, `courtlistener.recap` 737, `vrm_va_reo` 21. |
| 64 more labelled statewide | 64 (all SC) | 64 | CONFIRMED |
| 102 flip rows outside the 18 counties | 102 | 102 | CONFIRMED; county and source splits match exactly (Charleston 33, Pender 24, Georgetown 15, Dare 11, Onslow 7, Carteret 6, other 6; Fannie 46, Charleston MIE 24, Georgetown 11). A further 21 flip rows (VRM REO) have no county at all. |
| 369 multi-row keys, 1,132 rows | 306 keys, 884 rows (`dedupe_key`), 298 keys, 985 rows (county key) | 368 / 1,130 (county key) | CORRECTED in meaning, see item 2 |
| 23,722 leads with the generic distressed tag | 23,318 (`distressed` in `ds.signals`); 23,253 by listing type | **23,722** | CONFIRMED on the 09:34 board |
| 806 WARM and 772 HOT reach stack 2 only through that tag | 602 and 947 | 800 and 767 | CONFIRMED within 1% (my PROPERTY-name list is an approximation). 47% of HOT: 767 of 1,646 is 46.6%. New Hanover permits 645 of 1,646 HOT is 39.2%. |
| liensnc 38,289 WARM, 131 HOT, 52% of WARM | 38,289, 131, 52.3% | 38,416, 3 | CONFIRMED; the 131 is item 2's `ROW` group. |
| WARM 73,224, HOT 2,081 | exact | WARM 73,791, HOT 1,646 | CONFIRMED. "WARM at least 71,010" is a lower bound that understates (C2). |
| Last seen ≤7 / 8-30 / 31-90 / 91-180 days: 58,709 / 86,680 / 24,806 / 333 | 58,472 / 86,577 / 24,685 / 332 | **58,709 / 86,680 / 24,806 / 333** | CONFIRMED exactly on the 09:34 board when a day is a calendar day (`today - last_seen.date()`). Counted in elapsed 24-hour periods the first bucket is 46,503 and the second 98,819, because the 9/14 batch falls just over 7 days old. |
| 85% of rows seen in 30 days | 85.3% | 85.3% | CONFIRMED |
| 19 stale sources, 18,284 rows (section 3c) | 18 sources, 17,039 rows | **19, 18,284** | CONFIRMED; `spartanburg_vacant` (1,232) was refreshed at 10:10. |
| F2: 52 HOT with a passed sale date; 667 HOT last seen over 30 days ago | 196; 913 | **52; 667** | CONFIRMED (667 on calendar days, 672 elapsed). Sources of the 52: New Hanover permits 21, ServiceLink 10, Hubzu 4, Asheville STR permits 2, others. Now 129 of 196 are liensnc, whose `sale_date` is a filing date. |
| F14: 5,098 bare-string mailing | 2,071 (all WARM) | 2,137 | CORRECTED (C3) |
| F1: 16,142 of 33,259 `recorded_debt` signals are estimates | 15,985 of 33,193 | 16,037 of 33,259 | CONFIRMED to within the 105 proxy rows (C6) |
| F1: about 4,364 WARM and 341 HOT fall below stack 2 | 3,933 and 519 | 4,141 and 321 | CONFIRMED within 5% (stack 2 whose FINANCIAL category rests only on estimated debt; my financial-signal list is an approximation) |

**Fix implied.** State the freshness convention in the audit ("calendar days"). Change "WARM at least 71,010" to 73,791. Replace 5,098 with 2,071 and date it.

## 8. Debt-known: the ledger figure against the new definition

**Question.** How many leads have a countable debt under the new definition (`is_countable_debt(raw.amount_owed)` or a real `tax_owed.balance` above zero), against the 63,806 quoted after commit bc5919b?

**Method.** Three counts per board, plus the composition of `amount_owed`.

| Definition | Current | 09:34 |
|---|--:|--:|
| `tax_owed.balance` above zero | 63,797 | **63,806** |
| Ledger "actual debt" (tax balance, or `amount_owed` with `is_actual_debt` True) | 65,239 | 65,262 |
| **New: tax balance or `is_countable_debt`** | **65,344** (38.4% of rows) | 65,367 |
| Of the new count: SC / NC | 52,393 / 12,951 | |
| In the 18 footprint counties, ledger / new | 24,706 / 24,807 | |

The quoted 63,806 is exactly the number of leads with a positive tax balance on the board it was measured on. It is not a count of all debt: 1,561 more leads have a judgment or opening bid as their only debt. The 105-row difference between the ledger definition and the new one is `amount_owed.source = opening_bid` with `is_actual_debt` False, which the committed fix counts (the lender opens at about the payoff).

What is not counted, correctly: `amount_owed` values that are estimates, 22,485 rows (`assessed_value` 14,111, `estimated_tax_2yr` 8,072, `sqft_based_estimate` 302). The ledger's debt column is keyed on `is_actual_debt`, so it does not share the F1 flaw.

Two caveats on the 63,806. The rise from 29,274 was mostly `balance_owed` being copied into `raw.tax_owed` (63,479 rows stamped by bc5919b), which relabels a balance the qPayBill and Transylvania rows already carried; it is not new knowledge. And 327 of the tax balances are `basis = parcel_cross_ref`, joined from another record.

**Verdict.** CORRECTED. Report **65,344** leads with a countable debt (63,797 tax balances plus 1,547 with a judgment or opening bid only), and keep the tax-balance count as its own column.

**Fix implied.** Split the ledger column into "tax balance" and "judgment or bid", drop the "was 29,274" comparison, and label the 327 cross-referenced balances.

---

## Fixes implied, in order of effect

1. Land the county-scoped parcel key with placeholder rejection (item 2). Removes 130 HOT and ungroups 375 rows.
2. Land the `eq_evidenced` gate (item 1). Removes about 1,820 HOT; keep `ROW`-style borrowed equity out of it.
3. Commit the `load_board` drop guard and the divorce date parser (items 4 and 5).
4. Stamp sold leads and let the scorer cap on `sale_date_passed` (item 3).
5. Land `sc_tax_delinquent`, fix per-source run health for child slugs, retire the robots gate on `rutherford_wildfire_tax` (registry report).
6. Apply the divorce verdict stamp; decide on case-detail fetches (item 6).
7. Correct the audit and ledger figures in items 7 and 8.

## Reproduction

Scripts, in the session scratchpad `verify/`: `pass1.py` and `pass2.py` (all counters, `BOARD_PATH` and `NOW_OVERRIDE` select the board and the reference time), `pass4.py` (placeholder groups, F8 rows, divorce case counts), `pass5.py` (A3 and F1 stack effects, divorce date formats), `divorce_unit.py` (item 5), `dump_registry.py`, `parse_logs.py`, and their JSON outputs. The 09:34 board copy is `verify/board_0134.json.gz` (88 MB, from `git show 6d41e4e:docs/listings.json.gz`).
