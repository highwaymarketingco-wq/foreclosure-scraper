# Audit 2026-10-09: pipeline_gate (the pipeline as a process; the next run not outdated or broken on arrival)

Counts below were computed on 2026-10-08/09 against the 10/7 published board (350,013 rows, streamed,
peak RSS under 450 MB), the VM's logs (read with grep/tail only) and the code at the commits named.
Nothing was run on the VM.

## 1. What was measured and how (repeatable)

| What | Command | Result |
|---|---|---|
| Every invariant of every audit area, one pass | `uv run python scripts/audit_suite.py [--checkpoint DIR]` | all areas' checks in one pass: 126 s, 268 MB peak RSS on the 10/7 board; `suite_result.json` |
| Modules no run path imports, env flags vs code | `uv run python scripts/pipeline_wiring.py` | 30 enrichment modules script-only, 0 dead scrapers; flags below |
| The pre-run gate | `uv run python scripts/prerun_gate.py --pin <sha>` | 14 checks; today: FAIL (dirty ledger mid-sweep, 80 local commits unpushed, no suite record) |
| Swallowed failures of a run | `python3 deploy/oracle/run_failures.py <log>` | 10/6 full run: 0 step failures, about 40 time-capped phases |
| Tail idempotence | the local tail twice on a random 1,451-row sample of the board (scratchpad script, `reconcile_board.reconcile_tail`) | second pass changed 91 rows (6.3%) |

### Phase map (main.run then main.run_enrich_tail, in order)
scrape (budget 3 h) -> lis pendens discovery -> carryover (prior board, streamed since d42058b3) ->
sold-pool partition -> scope, active, flip filters -> dedupe -> **merge_prior_board** (critical,
streamed) -> [GRANDFATHER snapshot, opt-in] -> correct_prior_rows -> scrub_unbound_tax ->
[pulled_sales when no merge] -> link validation (cap 600 s) -> checkpoint `link_validation` -> GIS
(cap 2,400 s) -> checkpoint `gis` -> courts -> zillow -> hud_reac, lincoln, burke, lrcpwa -> geocode ->
parcel_from_geo -> location -> address_backfill -> bk property -> parcel_lookup -> gis_attrs ->
richland -> cama_condition -> gis_derived -> situs -> aggressive address -> lis pendens resolver ->
reverse geo -> case_detail -> address synthesis -> county pin -> county normalize (checkpoint) ->
**dedupe2** -> coastal re-pass -> scope re-pass -> countyless national drop -> situs sanity ->
owner_mailing (checkpoint) -> county_sales -> incarceration, jail, BOP -> nc_case_status -> docket
history -> bankruptcy, stay -> relationship deeds -> skip trace -> recorded comps, assessor comps,
comps, recorded sales -> zestimate -> photos, assessor photo, streetview, images -> vision -> doc_ocr
(checkpoint) -> sold-pool mini pipeline -> sold comps -> hazards group -> SOS -> qPayBill -> rent comps
-> census -> land ratio -> multifamily, property kind, commercial land use -> buildability -> RECAP
-> judgment amount -> amount_owed -> validate -> promote owner -> voter phone, county phone, line
type -> ROD group -> nc_rod_render -> rod_chain -> dot_ocr -> **checkpoint `dot_ocr`** ->
TAIL: jail re-stamp -> divorce -> name resolver -> ACPASS -> resolved catch-up -> tax_owed (scrub) ->
amount_owed promotion -> tax aging -> bankruptcy+tax combo -> tenure -> tax relief -> rollback ->
life events -> upset bid -> process timing -> lien stack -> sc_cama -> footprint -> court bid -> FHFA
-> DEW -> court owner verify -> entity type -> **valuation + grade** -> assessor card -> **equity** ->
deed chain -> title risk -> flags -> vacant land use -> **verification apply** ->
**restore_verified_tax** -> **score_board** -> derived signals ... fullmer -> derivation flags ->
burke history -> lrcpwa photo -> strategy, eviction, corroboration, competition, lead signals, buyer
match -> RentCast -> data_quality -> source health -> new listings -> homepath -> prune REO -> board
quality -> last sale -> board QA -> source link -> FEMA, OZ, USPS -> outreach -> summary ->
[GRANDFATHER restore] -> count guard -> stop_before_publish or publish_tail.

Order scan (static, heuristic; scratchpad `order_scan.py`): 137 places where a step reads a persisted
raw key that a LATER step writes. Most are deliberate (priority by last run's tier) or false
positives. Confirmed by measurement: D1, D2, D7 below. Read from the code, not measured:
`enrichment_fhfa_value` reads `raw['last_sale']` that `enrichment_last_sale` writes at the end of the
tail; `enrichment_foreclosure_sold_comps` reads `raw['upset_bid']` before `enrich_upset_bid` runs;
`enrichment_comps` and `enrichment_property_kind` read `raw['cama']` before `enrich_sc_cama`.

### Env flags, deploy/oracle/vm_lib.sh vs code defaults (src/ only)
- VM on, code off (5): ASSESSOR_CARD_ON, BOARD_PRIOR_MERGE_ALLOW_LARGE, FORECLOSURE_ASSESSOR_PHOTO,
  FORECLOSURE_ROD_CHAIN, FORECLOSURE_STREETVIEW. VM off, code on (1): VISION_USE_OLLAMA. Dead VM flags: 0.
- Read only through registry tables: the 10 FORECLOSURE_*_ROD platform flags, STREETVIEW_MAX/MONTHLY_MAX.
- The intended profile is now declared in `deploy/oracle/run_profile.json`; the gate fails when
  vm_lib.sh drifts from it or when a forbidden setting is present (GRANDFATHER_CARRIED=1,
  FULLRUN_PERSIST=0, FULLRUN_PRIOR_CORRECTION=0, SCORE_BOARD_FAIL_SOFT, VERIFICATION_APPLY=0,
  FORECLOSURE_CHECKPOINT=0, any ENRICH_PHASE_MAX_SECONDS).

### Whole-board loads and memory
- Run path scan (`pipeline_wiring.whole_file_json_loads`): 17 whole-file JSON loads; 16 are small
  files (manifests, run_meta, high-water mark, resume state), 1 is the GRANDFATHER snapshot
  (`main.run`, json.loads of the whole plain board, only with GRANDFATHER_CARRIED=1: forbidden by the profile).
- Watchdog peaks (VM mem logs): full run 10/6 (350,013 rows out) 19,731 MB; publish-only 17,021 MB;
  enrich-only 12,508 MB. Two full runs (10/7 23:37, 10/8 00:38 UTC) were killed at 25,629 / 25,606 MB
  36 minutes in, right after lis-pendens discovery: carryover's json.loads of the 4.1 GB prior board
  (fixed in d42058b3; the scanner flags that exact pattern, test `test_board_loads_catch_the_carryover_pattern`).
- Projection used by the gate: worst measured 57.7 KB per row x prior rows x 1.15 = 22,691 MB for
  402,514 rows; the watchdog (25,600 MB) would kill above about 454,000 rows.

### Swallowed exceptions
`run`, `run_enrich_tail` and `publish_tail` hold 212 exception handlers that do not re-raise. An
enricher failure is visible only in the log: `summary['errors']` lists scrapers only, run_health has
no entry for a step that failed, the digest says nothing, the exit code is 0. Five handlers swallow
with no log line at all (sold-pool validate / county pin / property kind, the GRANDFATHER row
validation, the assessor-card re-grade). The 10/6 full run logged 0 step failures but about 40
time-capped phases (link validation, GIS, parcel_from_geo, gis_attrs, owner_mailing, situs, comps,
recorded comps, zestimate, doc_ocr, flood, environmental, helene, code enforcement, permits, court
bid, name resolver, ...): those phases reached only part of the board, and nothing reported it.
Now printed at the end of every VM run log (`vm_report_swallowed`, `deploy/oracle/run_failures.py`).

### Resume paths
`vm_resume.sh --enrich-only` (whole post-dot_ocr tail, network included, 3 h 12 min on 10/5),
`--publish-only` (pre_publish checkpoint), `scripts/carry_publish_state.py` (full run's publish
inputs onto a re-run: defect D4), and new `--reconcile` (below).

## 2. Defects found

| # | Class, scale | Cause | Fix | Test | Invariant |
|---|---|---|---|---|---|
| D1 | Grade and money fields computed from LAST run's equity: 70,861 of 350,013 rows (20.2%) on the 10/7 board carry a grade whose equity note disagrees with the published equity (63,624 no note, 6,299 another %, 651 note without equity, 287 note under 40%); a re-grade of 1,500 of them with the published equity adds the note to 1,466. Max bid / wholesale MAO also move (calc subtracts the equity payoff). | `run_enrich_tail` runs the valuation loop before `enrich_equity`; both calc and grade read `raw['equity']`. | Wiring W2 (re-grade after equity; valuation loop takes about 40 s for 350K rows per the 10/6 log). Validated in-process on the sample: second-pass changes 91 -> 25 (W1+W2) -> 17 (+W3). | `tests/test_reconcile_board.py::test_a_second_tail_pass_changes_nothing` (strict xfail until W2 is wired) | `pipeline-grade-equity-current` |
| D2 | Equity, combo and calc computed from tax inputs that restore_verified_tax rewrites afterwards: 8 of 343 equity rows in the sample after one tail pass with today's ledgers | `restore_verified_tax` (5d832485) runs after equity, amount_owed, tax aging and the combo | Wiring W1 (verification apply + restore before valuation; combo re-run) | same strict xfail | `pipeline-equity-tax-inputs`, `pipeline-tax-check-binding` |
| D3 | A bankruptcy+tax combo restating another balance: 25 of 414 on the 10/7 board | `enrich_bankruptcy_tax_combo` only ever set the block | Fixed (3acda157): cleared when the tax block or the bankruptcy match is gone | `tests/test_bankruptcy_tax_combo.py` (2 new) | `pipeline-combo-matches-tax` |
| D4 | Published run_health.json shows all 204 sources at count 0 (120 of them beside "OK (n)"); the 10/7 digest had an empty per-source table | `carry_publish_state.py` did not carry `by_source`; a resume's summary has `{}` | Fixed (6ebeb0f3) | `tests/test_carry_publish_state.py` (1 new) | `pipeline-run-health-counts` (120/120 on the live file until the next publish) |
| D5 | Latent whole-board load: `enrichment_pulled_sales._load_previous` json.loads the plain board (4.1 GB on the VM) whenever merge_prior_board did not run | old code | Fixed (2c0e4786): streamed, still all-or-nothing on a damaged file | `tests/test_pulled_sales.py` (6 new) | gate `board-loads` |
| D6 | Two VM full runs killed by the watchdog 36 min in (carryover json.loads of the prior board) | old code | fixed by d42058b3 (not this audit) | `test_board_loads_catch_the_carryover_pattern` | gate `board-loads` + `memory` |
| D7 | Tenure missing or from another sale: 2,099 of 60,739 rows with a known sale year (2,004 none, 95 stale), SC (Anderson, Spartanburg) | `enrich_tenure` runs before `enrich_sc_cama` writes the SC sale dates; tenure is set-only | Wiring W3 | sample: 8 rows change on a second pass, 0 with W3 | `pipeline-tenure-from-sale` |
| D8 | A failed or time-capped step is invisible outside the log | design | Reported at the end of the VM log (ad64406c); canary asserts zero step failures | `tests/test_run_failures.py` | canary `no-swallowed-failures` |
| D9 | 5 handlers swallow with no log | `except Exception: pass` | Wiring W4 | - | canary log scan (once logged) |
| D10 | A run whose pin lacks commits meant for it: the running 10/8 VM run is pinned d42058b3, before the tax-binding scrub (95aed7b0), the verified-tax restore (5d832485, 365f0f0c) and the 10/8 ledgers | no gate | `scripts/prerun_gate.py` (pin == HEAD, pushed, suite green on the pinned code, ledgers committed); for the running run: `vm_resume.sh --reconcile` on its checkpoint after a re-pin | `tests/test_prerun_gate.py` (18) | gate `pin`, `tests`, `ledgers` |
| D11 | 30 enrichment modules built but run only by scripts; 32 published raw keys only they write (frozen on the board: flood_zone, property_category, hud_fmr, census_tract, dnc_scrub, septic, wetlands, ...) | never wired | Each recorded with a reason in `run_profile.json`; the gate fails on a NEW one | `tests/test_prerun_gate.py` | gate `unwired`, `frozen-keys`; canary lists frozen keys |

Not changed (outside this audit's licence): `generate_outreach` runs in the tail and rewrites
`docs/crm.json` and `docs/outreach_maillist.csv` on a stop-before-publish run and on an enrich-only
resume, before anyone reviews the board (W6 moves it into `publish_tail`).

## 3. New tools (how to run)

- **Audit suite**: `uv run python scripts/audit_suite.py` (published board) or `--checkpoint DIR`;
  exit 1 when any check is not ok; `--list`, `--only`, `--limit`. Checks may declare `DETAIL_KEYS`
  and `set_source(kind, path)`.
- **Pre-run gate**: on the Mac before pinning: run `scripts/run_test_suite.py` (full suite in 6
  sequential chunks, writes `data/test_results/latest.json`), push, then
  `uv run python scripts/prerun_gate.py --pin <sha>`. On the VM before `vm_run.sh` (after checking
  the pin out): `.venv/bin/python scripts/prerun_gate.py --pin <sha> --skip tests` (exit 2 = passed except
  the skipped check; the VM's own memory, flags, registry and checkpoint are what it adds there).
- **Canary**: `uv run python scripts/canary_run.py all --stats-baseline <full run resume_state.json>`
  on the VM after the gate, between runs (it is a board job: vm_lib's job check sees it). Polk,
  Mitchell, Union SC, Greenwood; 3,307 prior rows (prepare measured on the Mac: 56 s, 443 MB);
  28 enrichment keys stripped from the prior rows to be re-produced. `--no-stealth` skips the
  browser-rendered court paths. NOT run in this audit (no VM writes allowed; too heavy for the Mac).
- **Reconcile**: after a gated run, on the VM: check the new pin out, then
  `setsid nohup bash deploy/oracle/vm_resume.sh --reconcile >/dev/null 2>&1 < /dev/null &`
  (`--prior-correction` adds `correct_prior_rows`), review (`resume_from_checkpoint.py` preview,
  `board_selfcheck.py --checkpoint`, the suite result it writes beside the checkpoint), then
  `vm_resume.sh --publish-only`. It runs `main.run_enrich_tail` itself with 26 network steps stubbed
  and every socket connect refused, keeps the run's publish switches, health, errors, by_source and
  sold pool, archives the board it replaces, and refuses a checkpoint over 25,000 rows on macOS.
  Estimate on the VM from the 10/6 log: about 30 to 45 minutes (load, footprint 13 min, valuation
  38 s, equity 2 s, verification 47 s, scoring 65 s, save), memory like the enrich-only resume
  (12.5 GB). Not run on the VM. What it cannot do: anything a network step or a pre-dot_ocr step
  (merge, dedupe, gis_attrs, scrapers) would change.

## 4. Wiring for the lead (main.py; anchors are code text)

**W1** (D2) Move the two blocks that start `# Per-listing verification verdicts (docs/HANDOFF.md item 66).`
and `# A tax debt the county's own site CONFIRMED` (they end before `# Stacked-distress score`) to just
before `    # Investor calculator + A-F grades per listing.`, and add right after them:
```python
    try:
        from .enrichment_bankruptcy_tax_combo import enrich_bankruptcy_tax_combo
        enrichment_stats["bankruptcy_tax_combo_after_restore"] = enrich_bankruptcy_tax_combo(enriched)
    except Exception:
        log.error("bankruptcy_tax_combo_after_restore.failed", traceback=traceback.format_exc())
```
**W2** (D1) Directly after the `enrich_equity` try/except (anchor `log.error("equity.failed", ...)`):
```python
    # calc (max bid payoff) and grade (equity notes, risk points) read raw['equity'], which only now
    # exists for this run: re-grade once (audit 2026-10-09; ~40 s for 350K rows).
    _regraded = 0
    for li in enriched:
        try:
            c = valuation_calc.compute(li)
            g = valuation_grading.grade(li, c)
            li.raw["calc"] = valuation_calc.to_dict(c)
            li.raw["grade"] = valuation_grading.to_dict(g)
            _regraded += 1
        except Exception:
            log.warning("valuation.regrade_failed", source_url=li.source_url, traceback=traceback.format_exc())
    enrichment_stats["valuation_regraded_after_equity"] = {"count": _regraded}
```
Then remove the `xfail` marker from `tests/test_reconcile_board.py::test_a_second_tail_pass_changes_nothing`.
**W3** (D7) Move the `# Owner tenure` try/except block to just after the `enrich_footprint_sqft` block.
**W4** (D9) Replace the five `except Exception: pass` with `log.error("<step>.failed", traceback=traceback.format_exc())`:
`_vl(sold_pool)`, `enforce_case_pinned_county(sold_pool)`, `enrich_property_kind(sold_pool)`,
`_grandfather.append(Listing.model_validate(_r))` (count instead of log per row), and the assessor-card re-grade loop.
**W5** (optional) `_await_capped` / `_gather_phases`: log the budget actually used, and let an explicit
`default_s` win over ENRICH_PHASE_MAX_SECONDS (today the env overrides dot_ocr, rod_chain and
nc_rod_render's own budgets; the profile forbids setting it meanwhile).
**W6** (optional) Move `generate_outreach` from `run_enrich_tail` into `publish_tail` (after the board write).
**W7** (optional, vm_run.sh) after `uv sync`: `uv run python scripts/prerun_gate.py --pin "$PIN" --skip tests,suite >>"$LOG" 2>&1 || [[ $? -eq 2 ]] || { echo "==> pre-run gate failed" | tee -a "$LOG"; exit 1; }`.

## 5. Open items
- The 10/6 run time-capped about 40 phases: coverage is capacity-bound (not addressed; now reported).
- Remaining tail non-idempotence after W1-W3 (17 of 1,451 sample rows): equity's withheld-vs-absent
  decision reads the previous equity block, and grade() re-gates equity; needs a valuation owner.
- 30 script-only enrichers / 32 frozen keys: wire or retire, one decision each (owner).
- Canary and reconcile have not run end to end on real data (VM is read-only for this audit; the
  Mac is too small for the canary). Reconcile ran end to end on made-up rows and twice on 1,451
  real sample rows on the Mac.
- The full test suite was not run (brief: targeted tests only); the gate's `tests` check stays FAIL
  until someone runs `scripts/run_test_suite.py` on the commit to pin.

## 6. Outside this area
- block_binding, documents_images and drops_lineage checks are not ok on the 10/7 board (see
  suite_result.json); their owners report them.
- The Mac's data/checkpoint is a 9/25 link_validation checkpoint (197,890 rows), and docs/listings.json
  on the Mac is a stale 10/1 plain file beside the 10/7 parts board.
- `scripts/enrich_board.py` still writes the board through load_board for 350K rows (memory) and is the
  only runner of most script-only enrichers.
