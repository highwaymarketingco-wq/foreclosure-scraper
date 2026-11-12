# Audit 2026-10-09, area cube_remeasure: the 82-column x 146-county grid, remeasured

## 1. What was measured and how

`scripts/gap_matrix.py` (one streaming pass, peak RSS 231 MB) over:

- the reconciled pre-publish checkpoint of the gated full run (VM `data/checkpoint`, manifest saved
  2026-10-09T14:01Z, reconciled from the 02:18Z pre_publish save; 383,378 rows), copied read-only
  with scp. gap_matrix now reads a checkpoint directory the way `compare_boards.py --candidate`
  does (`board_selfcheck._checkpoint_rows`: validated to a Listing, `web_artifact._to_dict`);
- the live published board (350,013 rows, published 2026-10-07), for the data-versus-definition split.

Repeat:

    uv run python scripts/gap_matrix.py --board <checkpoint dir> --screens <screen_ledger.json> \
        --date 2026-10-09 --baseline docs/gap_matrix/county_signal_coverage_2026-10-07.csv \
        --baseline-label 2026-10-07 --desktop ~/Desktop

The screen ledger for this checkpoint was built from its own `resume_state.json` (the run's
`summary.source_status` and `enrichment_stats`, exactly what the publish writes into
run_health.json): 226 sources, 613 (column, county) screens.

### The 10/7 headline numbers were gap ENTRIES, not cells

The 10/7 README's "6,268 / 1,719 / 1,617 / 1,031 / 690" counts gap-list entries: they include the
verification-layer entries (a cell can appear twice) and the UNKNOWN-county rows. "647 of 11,972 at
target" was 11,972 minus that sum. Counted as cells (146 named counties x 82 columns, one class per
cell, fill/check layer), 1,968 cells were at target on 10/7. Both views below; the README now prints
the cell view too.

| class (cells, 146 x 82 = 11,972) | 10/7 published | 10/9 live board, new definitions | 10/9 checkpoint, new definitions | 10/9 checkpoint + its screen ledger |
|---|---|---|---|---|
| at target | 1,968 | 1,865 | 1,943 | **2,186** |
| not applicable | 673 | 1,238 | 1,287 | **1,287** |
| walled | 733 | 715 | 695 | **694** |
| no source known | 1,525 | 1,498 | 1,370 | **1,370** |
| sourced-not-built | 1,111 | 1,104 | 1,069 | **1,065** |
| built-but-low-yield | 5,962 | 5,552 | 5,608 | **5,370** |
| carries a verdict (first four) | 4,899 (40.9%) | 5,316 | 5,295 | **5,537 (46.2%)** |

Gap entries (the 10/7 headline's unit): built-but-low-yield 6,268 -> 5,690; sourced-not-built
1,719 -> 1,684; no source known 1,617 -> 1,466; walled 1,031 -> 1,007; not applicable 690 -> 1,304.

Fill moved too (10/1 definitions, all rows): owner_name 92.6 -> 93.1%, parcel_id 53.2 -> 59.5%,
deed history 22.8 -> 30.2%, taxpayer of record 44.9 -> 52.9%, phone 22.4 -> 19.5% (the binding
rules removed numbers that were not the owner's; accepted_drops.md).

## 2. Defects found and fixed

| defect | scale | cause | fix | test | invariant |
|---|---|---|---|---|---|
| no "screened, none found" for county/state/feed signals | 613 screens this run; 652 cells still unscreened without a ledger | the board shows a screen only through a hit | `screen_ledger.py`: per-source status -> (column, county) screens; written beside run_health.json by `run_health.write_health_artifact`; gap_matrix `--screens` | tests/test_screen_ledger.py, test_gap_matrix.py | `cube-unscreened-county-signal-cells` (ratchet 652) |
| flip feed columns counted as gaps in the 113 counties where the owner's rule drops flips | 565 cells | the cube ignored main._FLIP_LISTING_TYPES / _flip_outside_footprint | applies only in config.in_scope counties + OCEANFRONT_COASTAL_COUNTIES (33 counties) | test_flip_feed_columns_apply_only_in_flip_scope | `cube-flip-row-outside-flip-scope` (0 on the checkpoint) |
| heir_naming_publication / quiet_title declared statewide via NC notices | 200 NC cells | no NC parser exists (SC Column estate lane only) | NC = source known, not read | test_quiet_title_is_sourced_not_built_in_nc | (same ratchet) |
| undated marriage_license no-match counted as checked | 5 rows | retired module leftovers | checked only with checked_at / a license | (gap_matrix) | `cube-negative-wrapper-dated` (max 5) |

Which signal families now stamp a negative: incarceration (`incarceration_check`), federal prison
(`bop_check`), divorce (wrapper with `case_count` 0), marriage license (`status: no_match` +
`checked_at`), SoS (`sos_agent.checked`): per row, dated. County delinquent rolls (tax family),
jail rosters, SC probate index, Spartanburg condemned roll, county-named feeds, national auction /
REO / bankruptcy feeds: per county via the screen ledger. Not stamped and not stampable as a
screen: city-only registries (Spartanburg city vacant/condemned, Charlotte, Hendersonville),
qPayBill (budgeted enumeration), code_enforcement and vacancy (a list only names violators, no
county-complete list exists in most counties), owner e-mail (no negative wrapper; a field).

Wiring: none needed in main.py (run_health.write_health_artifact writes the ledger; the payload list
in board_payload.sh carries docs/screen_ledger.json). The VM must run this commit at publish time;
if the publish runs older code, after it: `uv run python -c "import json; from pathlib import Path;
from foreclosure_scraper.screen_ledger import write_ledger; write_ledger(json.load(open('docs/run_health.json')), Path('docs/screen_ledger.json'))"`.

## 3. Where the 6,435 open cells go (checkpoint + ledger)

| bucket | cells | who closes it |
|---|---|---|
| field fill below 100% (phone, address, sqft, deeds...) | 1,948 | fill work; one unfilled row keeps a cell open, so 100% fill is not reachable for phone/e-mail/sqft |
| derived column, inputs missing on some rows | 1,808 | follows its input field (owner_name, deed chain, notice text) |
| code covers the county, nothing on the board | 1,253 | final run: at most 379 (producer changed since pin 7d5b7ae1 and names the county; minus 164 NC quiet-title cells with no parser, so about 215 realistic); 874 will not close by a run (incarceration/BOP capped at 150 lookups a run, divorce, SoS, comps) |
| sourced-not-built | 1,065 (1,684 entries with verify layer) | us: `docs/gap_matrix/build_list_2026-10-09.csv`, 182 items, ranked by lead value per effort-day, about 711 effort-days in all |
| screening partial / capped | 361 | lift caps (tax rolls partially read, liens, SoS) |
| walled | 694 | owner (walls_register.json manual lanes) |
| no source known | 1,370 | research verdict per cell, then "no free source exists" |

Top of the build list: NC OneMap deed book/page field (77 NC cells, 1 day); an NC quiet-title /
heir-publication parser for NC public notices (20 cells each column, 1 day); comps verifier (85
cells); county-GIS deed book/page (13) and heir-estate owner scans (76 cells, ~11 days); register
adapters for liens per platform.

## 4. What 100% is reachable for, and what not

Reachable: every county/state/feed signal cell (screen ledger + build list + research verdicts),
the tax family in counties with a complete free roll, the attorney checklist fields that a statewide
layer carries (deed ref, legal description) once read. Not reachable as "100% filled": phone,
e-mail, sqft/beds, comps (no free source for every row); those need an owner decision to accept a
per-row "searched, none found" verdict as the field's 100%. Derived cells reach 100% only when
their inputs do. Incarceration/BOP need an uncapped or bulk source (150 lookups a run against
~265k people).

## 5. Not verified / outside the area

- Not verified: that each OK-status source really covered every county the ledger credits it with
  (coverage comes from the producer's own configuration, not a live re-check); CourtListener's
  completeness for NC/SC bankruptcy filings.
- The run pin (7d5b7ae1) is from memory notes; the "final run closes" estimate depends on it.
- Phone fill fell 2.9 points between the 10/7 board and this checkpoint (binding rules; already in
  accepted_drops.md).
- gap_matrix's "built in code" rule counts a county as built when a producer file merely names it
  (column_legal_notices names NC counties for other lanes); the cell then reads built-but-low-yield
  instead of sourced-not-built.
