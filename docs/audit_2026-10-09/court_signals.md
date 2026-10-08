# Audit 2026-10-09, area court_signals: court and notice signals, rechecked at their source

Public-safe: counts, county names, source slugs and verifier names only. The per-row tables (with
names) are on the owner's Desktop: `Audit_2026-10-09/court_signals/` (one TSV per signal and
state, `README.txt`, `coverage.json`).

## 1. What was measured and how (repeatable)

* Board: the 2026-10-08 pre_publish checkpoint (383,378 rows), read as `scripts/compare_boards.py`
  reads a checkpoint (`board_selfcheck._checkpoint_rows`: each row validated to a Listing and passed
  through `web_artifact._to_dict`), one streaming pass, peak RSS under 100 MB. 90,136 rows that score
  a court or notice signal (or carry the claim) were kept in a private scratch file for the offline
  counts below.
* Signals: the scorer names in `distress_stack.signals`: lis_pendens, foreclosure_sale, upset_bid,
  tax_sale, divorce, divorce_notice, probate, probate_notice, estate_lead, probate_deed, bankruptcy
  (none of court_sale, sheriff_sale, hoa_sale, partition, judgment_lien scored on this board).
* Sample: 30 rows per signal and state, seeded random (seed 20261009), 600 distinct rows.
* Live checks (sample, never a crawl; 2.5 s minimum between requests to one host, one at a time per
  host, ordinary browser User-Agent): NC Judgment Search open JSON (109 + 13 requests), county
  parcel layers and NC OneMap (73 + 25), CourtListener (17, the existing `bankruptcy_stay`
  verifier), the firms' own sale lists (Hutchens NC + SC, Shapiro & Ingle Power BI, Bell Carrington
  sheet, Rogers Townsend PDF, Kania listings JSON: one read each per process). Nothing walled was
  touched; the SC Public Index was not contacted. Verdicts went to a scratch ledger directory
  (`--ledger-dir` style), never to `docs/handoff/verification/`.

## 2. Precision per signal and state (sample of 30 unless noted)

"Real" = the event exists at its source; "live" = still in force; "this property" = the record's
party is the row's owner of record, on a row that names a property.

| signal | state | source checked | real | live | this property | notes |
|---|---|---|---|---|---|---|
| lis_pendens | NC | NC Judgment Search | 30/30 | 25/30 (5 Canceled; 4 of them already Canceled in the row's own block) | 1/30 match, 28/30 no property | only 6/30 are a "CV - Lis Pendens"; 22 are claims of lien, 2 transcripts of judgment |
| divorce | NC | NC Judgment Search | 30/30 | 30/30 | 1/30 match, 29/30 no property | a granted divorce (judgment), not a pending case |
| divorce_notice | NC | NC Judgment Search | 30/30 | 30/30 | 1 conflict (a namesake's parcel), 29/30 no property | |
| upset_bid | NC | NC Judgment Search | 25/25 of the eCourts rows are a judgment, 0/25 a sale | n/a | 25/25 no property | the upset-bid window was opened from a judgment ORDER date (defect D1); 2 nc_upset_bids rows confirmed on Kania's list; 2 Zacchaeus rows walled |
| foreclosure_sale | NC | firm lists | 8 firm rows: 8 real | 7/8 still listed, same date; 1 removed before its 2026-11-17 sale | 8/8 same address | 21/30 walled (ncnotices bodies 11, Brock & Scott 4, Zillow 3, Realtor 2, foreclosure.com 1), 1 not checked |
| foreclosure_sale | SC | firm lists | 4 firm rows: 4 real | 4/4 listed, same date | 4/4 | 23/30 walled (scpublicnotices bodies 12, foreclosure.com 11), 3 not checked (MIE results PDFs, Spartan weekly legals) |
| tax_sale | NC | Kania list | 14 Kania rows: 14 real | 14/14 listed | 14/14 (multi-parcel cases matched by address) | 4 walled (Zacchaeus), 12 county pages not read |
| tax_sale | SC | tax_lien ledger (tax area) | 3 of 30 have a ledger verdict: 3 confirmed | | | 27 not yet swept by the tax verifiers; not fetched here (a tax sweep was running on the same vendor) |
| estate_lead | NC | county roll / NC OneMap | 22/22 roll still says HEIRS / ESTATE | | parcel-keyed | 8 not this verifier's (Buncombe 3, McDowell probate 4, no parcel 1) |
| estate_lead | SC | county roll | 29/29 | | parcel-keyed | |
| probate_deed | NC / SC | county roll | 20/20, 2/2 | | | the other 38 are notice / obituary / tax rows (not read) |
| probate, probate_notice | NC | none (estate file is NC eCourts Smart Search: CAPTCHA) | notices exist | wall | sample: probate 7 rows with a property (3 share a name with the owner, 2 do not, 2 name no decedent), probate_notice 3 (2 share, 1 no decedent); 50/60 no property | board-wide: 36 of 111 notice-probate rows with a property and an owner name name someone else (D6) |
| probate, probate_notice, probate_deed | SC | none | Horry rows are the probate court's own index records | not exposed by the open search | 0 of 3,997 Horry rows has a parcel | |
| bankruptcy | NC | CourtListener (existing verifier) | 12 decidable: 2 confirmed, 8 refuted (7 no positional name match, 1 middle-name conflict), 2 unconfirmed | | | 18/30 have no property (D3) |
| bankruptcy | SC | CourtListener | 2 decidable: 2 confirmed | | | 28/30 have no property |
| lis_pendens | SC | none: SC Judicial Public Index refuses scripts at its edge | wall 29/30 | | | 1 scpublicnotices row; Charleston's own (open) index copy holds 1,330 of the 5,507 rows (7 WARM): no verifier yet |
| divorce | SC | none (SC Family Court index) | wall 30/30 | | | |

## 3. Defects found

| # | class | scale (2026-10-08 checkpoint) | cause | fix | test | invariant |
|---|---|---|---|---|---|---|
| D1 | upset_bid scored on court judgments | 1,146 rows (12 HOT, 1,111 WARM, 23 COLD), all counties_nc.nc_ecourts_lis_pendens, 100 NC counties | the scraper opened a 14-day upset-bid window from a judgment's orderedDate; NC sales are special proceedings this index does not hold; enrich_upset_bid skipped rows with no sale date, so carried stamps were never re-judged | scraper no longer stamps it; `enrichment_upset_bid.is_ecourts_order_date_window` removes a carried stamp (runs in `run_enrich_tail` and `reconcile_board.py`) | `test_court_signals_upset_bid.py` (4), `test_nc_upset_bid.py` and `test_nc_ecourts_active_filter.py` updated (they asserted the defect) | `court-upset-bid-needs-sale` |
| D2 | an ended judgment still scored | 762 rows (43 WARM): 760 from the legacy `nc_ecourts_judgments` lane (it kept every status), 2 from the scraper | no reader of the row's own status | `distress_score.court_record_ended` (eCourts rows only) ends the type signal; `nc_ecourts_case` answers stale | `test_court_signals_scoring.py` | `court-ended-record-not-scored` |
| D3 | a bankruptcy filing with no property scored | 755 bankruptcy filing rows scored with no parcel and no numbered address, 751 of them with '<debtor name> — <case>' as street_address | F11 tested the truthiness of street_address | `distress_score.has_property_address` | `test_court_signals_scoring.py` | `court-bankruptcy-has-property` |
| D4 | HOT court leads with no property | 14 HOT (13 are D1) | D1 | D1 | | `court-hot-has-property` |
| D5 | NC "lis_pendens" is mostly liens | of 8,795 NC lis_pendens rows with an eCourts block: claim of lien 6,229, transcript of judgment 1,435, lis pendens 763, lien 273, condemnation 78, possession (evictions, legacy lane) 16 | the scraper mapped every lien cause to LIS_PENDENS (weight 28) | coordinator decision (section 10): claims of lien are ListingType `lien_claim` (signal lien_claim, weight 10, name-only evidence: never record-linked, never completes a HOT stack), transcripts are judgment liens; scraper + the tail retypes carried rows; dashboard label, Type filter, lane | `test_court_signals_scoring.py`, `test_court_signals_binding.py` | `court-lis-pendens-is-lis-pendens` |
| D6 | an estate notice put on someone else's parcel | 36 of 111 rows (NC 21, SC 15) by token overlap; 80 by the name rule now applied | many were the personal representative's own house (the address the notice prints for the representative) | coordinator decision (section 10): the tail binds a notice to a parcel only by name, else keeps it as an unbound county-level lead | `test_court_signals_binding.py` | `court-probate-decedent-binds` |
| D7 | court leads with no property at all | WARM court rows with no parcel and no numbered address: 2,241 (HOT 14); in the sample 28/30 NC lis pendens, 29/30 NC divorce, 46/60 bankruptcy, 50/60 NC probate notices | name-only court records that never resolved | D1/D3 remove most WARM ones; the rest is the call-ready gate's (wave 2 F) | | `court-hot-has-property` |
| D8 | two cases fused on one row | 203 rows whose case_number differs from their own eCourts block's (153 legacy lane) | merges | `nc_ecourts_case` answers unconfirmed `case_number_conflict` (never verifies the wrong case) | `test_verification_nc_ecourts_case.py` | (block_binding area) |

## 4. Verifiers built (auto-discovered; nothing to register)

| module | SIGNAL | source | TTL / retry | verdicts | GOVERNS (per record) |
|---|---|---|---|---|---|
| `nc_ecourts_case` | nc_ecourts_case (case-scoped) | NC Judgment Search open JSON, by county + the row's own order date (the free-text query does not match case numbers) | 14 / 3 d | confirmed (in force, owner not someone else), stale (Canceled, Satisfied, ...), refuted (the parties share no surname with the owner of record of the row's property), unconfirmed (not in window, case_number_conflict, surname_only, service errors: transient) | lis_pendens + upset_bid; judgment_lien; divorce_notice + divorce |
| `heir_roll` | heir_roll | the county layer the row came from, or NC OneMap, by the row's own parcel (exact id, not LIKE) | 30 / 7 d | confirmed (roll still names the heirs), stale (conveyed to an unrelated owner), refuted (no death word on the roll then or now), unconfirmed (titled to family, heirs of another, parcel not found, layer error: transient) | estate_lead (+ probate_deed when it is the same roll's tag) |
| `foreclosure_sale_list` | foreclosure_sale_list (case-scoped) | the firm's own current list (Hutchens NC/SC, Shapiro & Ingle, Bell Carrington, Rogers Townsend SC, Kania) with the scraper's own parser | 7 / 2 d | confirmed (listed; a new date is shown), stale (removed before the row's sale date), refuted (the case is listed for another house), unconfirmed (not listed after the date, unreadable list: transient) | foreclosure_sale + upset_bid + court_sale; tax_sale + upset_bid |
| `court_walls` | court_wall (WALL) | none (never fetches) | 365 d | wall, with the walls_register card | nothing |

Existing ones measured, not changed: `bankruptcy_stay` (CourtListener), `probate_heir_buncombe`,
`foreclosure_rod_buncombe`, `divorce_sc_wall`. `verification/fetch.py` gained `post_json` (form
session + replay, `json_key`). The firm lists are read by the scrapers' own fetch paths (the
http_client throttle), not through the Fetcher, so `--capture-dir` does not record them; tests
replace `foreclosure_sale_list.PROVIDERS`.

Privacy: no names in any evidence (initials and categories only); a refuted `nc_ecourts_case`
record drops the case number and ids; ROW_SUMMARY_EXCLUDE owner_name everywhere (court_wall also
street_address).

Live proof (scratch ledger, all 55 HOT court rows of the checkpoint): nc_ecourts_case 12 confirmed
(all no property); heir_roll 24 confirmed, 1 titled_to_family; foreclosure_sale_list 2 confirmed.
On the samples (distinct rows): nc_ecourts_case 115 (108 confirmed, 6 stale, 1 refuted),
heir_roll 73 (73 confirmed), foreclosure_sale_list 28 (27 confirmed, 1 stale), bankruptcy_stay 14
(4 confirmed, 8 refuted, 2 unconfirmed). The VM apply step
(`apply_verification` on Listings, scratch ledger) attached all 8 stale/refuted records and the
scorer dropped exactly the governed signals (divorce + divorce_notice; foreclosure_sale;
lis_pendens + upset_bid).

## 5. Coverage: share of board hits a verifier covers (applies and GOVERNS the signal)

| signal | state | rows | before | after | wall label | HOT+WARM rows | before | after |
|---|---|---|---|---|---|---|---|---|
| tax_sale | SC | 46,710 | 77.9% | 77.9% | 190 | 15,936 | 10,315 | 10,315 |
| probate_deed | NC | 9,471 | 4.9% | 61.1% | 1,909 | 5,034 | 175 | 3,812 |
| lis_pendens | NC | 9,054 | 1.4% | 98.2% | 0 | 1,187 | 8 | 1,137 |
| divorce_notice | NC | 7,255 | 0% | 99.9% | 0 | 7 | 0 | 7 |
| probate_deed | SC | 7,130 | 0% | 7.4% | 249 | 561 | 0 | 182 |
| probate_notice | SC | 6,546 | 0% | 0% | 195 | 79 | 0 | 0 |
| estate_lead | NC | 6,197 | 3.2% | 89.0% | 0 | 4,296 | 144 | 3,781 |
| divorce | NC | 5,794 | 0% | 99.9% | 0 | 7 | 0 | 6 |
| lis_pendens | SC | 5,507 | 0% | 0% | 3,819 | 1,243 | 0 | 0 |
| probate | SC | 4,200 | 0% | 0% | 9 | 9 | 0 | 0 |
| probate_notice | NC | 2,557 | 10.4% | 10.4% | 1,923 | 66 | 11 | 11 |
| upset_bid | NC | 1,257 | 0% | 96.7% | 3 | 1,221 | 0 | 1,188 |
| probate | NC | 1,130 | 10.1% | 10.1% | 1,001 | 58 | 2 | 2 |
| bankruptcy | NC | 634 | 45.7% | 45.7% | 0 | 115 | 113 | 113 |
| estate_lead | SC | 560 | 0% | 94.1% | 0 | 184 | 0 | 182 |
| bankruptcy | SC | 425 | 5.4% | 5.4% | 0 | 8 | 8 | 8 |
| foreclosure_sale | SC | 356 | 0% | 9.8% | 151 | 205 | 0 | 23 |
| tax_sale | NC | 350 | 7.4% | 68.0% | 0 | 250 | 21 | 173 |
| divorce | SC | 350 | 0% | 0% | 350 | 168 | 0 | 0 |
| foreclosure_sale | NC | 322 | 21.4% | 43.2% | 103 | 93 | 16 | 30 |

"Covered" is checkable, not checked: verdicts exist once the Mac sweep has run (section 7).
Bankruptcy's uncovered rows are the no-property filings D3 stops scoring.

## 6. Walls (recorded, never bypassed; manual steps are the walls_register cards)

SC Judicial Public Index (lis pendens, foreclosure, judgments outside Charleston; card
`sc_publicindex`) and SC Family Court divorce (`divorce_sc_wall`); NC eCourts Smart Search: special
proceedings (`nc_sp`: hearing, sale, report of sale, upset bids) and estates (`nc_est`); notice
bodies on ncnotices.com (`nc_notice_body`) and scpublicnotices.com (`sc_notice_body`); Brock &
Scott (answers 'Forbidden' to a plain client; its scraper's browser fallback was not run);
Zacchaeus (stealth browser only); SC probate indexes on southcarolinaprobate.net and the county
logins (`sc_probate_net`, `anderson_probate`, `lexington_probate`). Aggregators (foreclosure.com,
Zillow, Realtor) are not a primary source. The `court_walls` verifier labels the first four groups
on the rows so the wall shows where the lead is read.

## 7. Wiring (exact lines; main.py needs no edit)

* Verifiers: auto-discovered by `verification/registry.py`; the VM's `apply_verification` (main.py
  `run_enrich_tail`, before `score_board`) attaches whatever ledgers exist and the scorer drops the
  governed signals. No code change on the VM side.
* Ledgers (Mac, the sweep owner runs it; not run here):
  `HANDOFF_PUSH=0 uv run python scripts/verification_sweep.py --signal nc_ecourts_case,heir_roll,foreclosure_sale_list,court_wall --tier HOT,WARM --max-rows 6000 --budget-s 7200`
  then the usual push. HOT+WARM covered rows: about 1,140 eCourts (one search per county and day,
  cached), 3,960 heir parcels (one request each), 200 firm rows (six list reads). TTLs 14 / 30 / 7
  days, so a weekly sweep of the three keeps them current.
* upset_bid cleanup: already in the tail (main.py `run_enrich_tail` calls `enrich_upset_bid` before
  `apply_verification` and `score_board`) and in `scripts/reconcile_board.py`, so a reconcile on
  the checkpoint applies D1 without a new scrape. D2/D3 are in `distress_score` (every scoring).
* Invariants: `scripts/audit_checks/court_signals.py`, picked up by `scripts/audit_suite.py`. On the
  2026-10-08 checkpoint all six fail (1,146 / 762 / 755 / 14 / 45 of 46 / 36 violations), as they
  should before a re-score and a sweep. `court-probate-decedent-binds` stays red until the resolver
  binding (D6) is fixed or the owner accepts it.

## 8. Open items

* D5 and D6: done (section 10).
* The 16 'CV - Possession' rows of the legacy lane (evictions) are still typed lis_pendens.
* SC lis pendens in Charleston (1,330 rows, 7 WARM): the county's own index copy is open; a
  verifier is buildable (about half a day) and was not built.
* NC estate status, NC SP sale status, SC Public Index, notice bodies: walls (section 6).
* Horry probate (3,997 rows): no property on any row; the open search exposes no case status.
* tax_sale accuracy belongs to the tax verifiers (27 of 30 SC samples had no ledger verdict yet).
* Not verified by me: the full suite (targeted tests only: 2,105 scorer-related, 49 new, 85
  upset-bid, 365 verification); the sweep itself at volume; Shapiro and Kania list reads beyond one
  read each.

## 9. Outside this area (one line each)

* `tests/test_raw_keep_covers_enrichers.py` fails on `call_ready` (untracked `call_ready.py`, wave 2 F).
* `tests/test_audit_suite.py::test_the_real_checks_dir_loads` fails on `additions:import` (untracked `scripts/audit_checks/additions.py`).
* `law_firms.hutchens` keeps 42 of 252 NC rows (footprint `keep()`), so most of the firm's NC sales never reach the board.
* `law_firms.rogers_townsend` NC page answers 404.
* The tax_lien ledger has entries for 3 of 30 sampled SC tax_sale rows.

## 10. Coordinator decisions (2026-10-09), applied

All three live in `enrichment_court_owner_verify.enrich_court_owner_verify` (the existing court tail
step: `run_enrich_tail` before verification and scoring, and `scripts/reconcile_board.py` as a local
step), so no main.py line is needed. Counts below are from the 2026-10-08 pre_publish checkpoint:
the affected rows and every row sharing their parcel group (8,195 rows) scored before and after the
change with the same code otherwise.

1. **Claims of lien are not lis pendens.** `ListingType.LIEN_CLAIM` ('CV - Claim of Lien', 'CV -
   Lien'): signal lien_claim, FINANCIAL, weight 10, name-only evidence (never record-linked, never
   completes a HOT stack; not a lane kind). 'CV - Transcript of Judgment' becomes a judgment lien
   (distressed + nc_ecourts.signal judgment_lien, weight 12, the docketed money-judgment
   convention). 'CV - Lis Pendens' and 'CV - Condemnation' stay lis_pendens. The scraper types new
   hits; the tail retypes carried rows (raw.retyped records it; rows are kept); the scorer maps a
   carried row the retype has not reached. Dashboard: its own type pill and Type filter option,
   SIGNAL_CATEGORY, and the stage lane is 'outbound', never 'prefore'. **Moved: 7,947 rows**
   (6,511 lien claims, 1,436 transcripts); none scores lis_pendens after; 5,763 score lien_claim
   (748 do not: their own block says the judgment ended). **Tier changes: WARM to COLD 109, COLD to
   WARM 2, HOT none.**
2. **Estate notices bind by name.** A row whose estate notice names a property keeps it only when
   the decedent agrees with an owner of record (surname and first name, middle initials not in
   conflict; '<decedent> HEIRS' agrees; the row's owner_name counts only when it is not the
   notice's own decedent or representative copied), or the representative does on a property that
   is not the representative's printed address. Otherwise: a notice row loses its parcel, address,
   values and property-signal blocks (kept under raw.unbound_property_blocks; raw.estate_unbound
   says why) and stays a county-level estate lead; a notice merged onto another source's row moves
   to raw.probate_unbound. **Unbound: 80** (75 notice rows, 5 merged notices; reasons: decedent not
   the owner 52, no owner of record 29 on the first pass). **Tier changes: WARM to COLD 10.**
3. **Bankruptcy filings bind by name.** The same agreement between a debtor of the case and an owner
   of record (a county-roll owner, or owner_name when it is not the case name copied). **Unbound:
   165 filing rows** (all 'debtor not the owner of record'). **Tier changes: WARM to COLD 52.** The
   rule unbinds all 8 links the CourtListener re-check refuted on the sample and keeps the confirmed
   ones.

Group mates (other rows on the same parcels): WARM to COLD 2. Invariants added or changed:
`court-lis-pendens-is-lis-pendens`, `court-bankruptcy-filing-binds`, `court-probate-decedent-binds`
(now the tail's own rule). Tests: `test_court_signals_binding.py` (13), `test_court_signals_scoring.py`
(+4), `test_audit_checks_court_signals.py` (+2), `test_verification_nc_ecourts_case.py` (+1;
nc_ecourts_case v2 governs lien_claim). Not verified: the dashboard in a browser (the JS file
parses; `tests/js/phone_gate.test.mjs` fails on a phone-gate assertion unrelated to these lines).
