# Audit 2026-10-09, area valuation: ARV moves, outlier ARVs, lost comps, accuracy

Counts, county names, source slugs and parcel ids only. The row-level samples (with addresses) are
in the private audit folder, not here.

## 1. What was measured and how

* Both boards streamed once each into a scratch SQLite file (valuation fields only, peak RSS under
  300 MB): the live 10/7 board (`docs/`, 350,013 rows, comps and cama merged from the detail
  sidecar) and the 2026-10-08 gated run's `pre_publish` checkpoint (pin d42058b3, 383,378 rows, read
  as `compare_boards.BoardInput` reads it). Rows were joined on `compare_boards.join_keys` (parcel,
  numbered address, case, then the as-scraped fingerprint; a key four or more live addresses share
  is never a join key): 346,149 joined. The join reproduces compare_boards' comps figures exactly
  (69,706 rows in both with comps, 1,599 lost, 2,600 gained).
* The VM run logs, read only (grep): `vm-run-20261006T175148.log` (the 10/7 board's run) and
  `vm-run-20261008T014033.log` (the checkpoint's run), comps / recorded comps phase events.
* `git log 7d5b7ae1..d42058b3` over `valuation/`, `enrichment_comps.py`, `enrichment_equity.py`,
  `enrichment_recorded_comps.py`, `enrichment_assessor_comps.py`, `enrichment_fhfa_value.py`,
  `enrichment_foreclosure_sold_comps.py`, `data/arv_calibration.json`: no commits. The 10/7 board's
  comps came from pin 7d5b7ae1 and its valuation from the tail re-run on 1947db81; the checkpoint ran
  d42058b3. The valuation code was the same; every move came from the data it was given (and the code that
  fills those inputs: parcel-cache land use and values, county layers, the 10-digit PINs).
* Every checkpoint row re-priced by `valuation.calc` / `grading` at this commit, with and without
  the new outlier guard, feeding the new invariants (one pass, under 1 GB).
* `scripts/valuation_accuracy.py --checkpoint DIR`: ARV against the parcel's own recorded sale (see
  section 4). Two passes, 50 MB peak.

## 2. Defects found

### 2.1 The selfcheck's "arv_expected changed on 21,987 matched leads" is mostly a join artifact
`board_selfcheck.movement()` matches rows on `_key()` (parcel, else address, else a composite that
includes the source), and a dict keyed that way pairs different properties that share a key. On the
identity join: **4,197 ARVs changed, 2,595 appeared and 925 vanished** (7,717 of 346,149 rows). The
"largest moves" it printed were collisions: the rows at $4,253,500 and $3,473,200 carried the same
ARV on both boards; the $1,631,100 -> $8,000,000 row is a real move (below). (Outside this area:
`movement()` should join like compare_boards; nothing was changed there.)

### 2.2 What moved the ARVs (changed rows, primary cause; median and p90 absolute move)

| cause | rows | median | p90 | up 2x+ | down 2x+ | verdict |
|---|---|---|---|---|---|---|
| ARV method changed (e.g. tax x1.25 -> county market value 431, FHFA -> market value 190, land -> market value 169, market value -> listing comps 134) | 1,212 | 20% | 136% | 163 | 124 | mostly improvement (a county value or comps replaced a proxy) |
| property kind changed (single family -> land 3,601 rows board-wide, land -> single family 1,265; parcel-cache land use) | 1,000 | 10% | 47% | 21 | 61 | improvement |
| recorded-sales basket refreshed | 589 | 1.5% | 3.8% | 0 | 0 | noise |
| listing comps re-picked from a smaller sold pool | 566 | 18% | 88% | 44 | 102 | noise |
| ARV floor moved (a new recorded sale or market value) | 499 | 36% | 269% | 155 | 6 | defect-prone (below) |
| the parcel's recorded sale changed | 152 | 20% | 85% | 7 | 19 | mixed |
| county value / sqft / lot changed | 118 | 9-20% | | 7 | 5 | data update |

Appeared: bid-proxy ARVs on rows that gained an opening bid 834 (CONTRADICTED, no money), market
value where a withheld recorded-comps ARV had been 612, new county values 509. Vanished: a recorded
basket that the hard gates then withheld 539, land re-typing 212.

### 2.3 Sample: 40 largest moves and 40 random (`arv_move_sample.tsv`, private folder)
Each row checked against its own county record (100%-basis value, lot, sqft, kind) and the comps it
cites. **Largest 40: 14 improvements, 6 noise, 20 defects.** The defects: 12 ARVs raised to a
recorded deed far above the county value (a $8.0M deed on a 12.8-acre Charleston parcel valued at
$1.04M, a $1.4M deed on three Greenville 0.2-acre lots valued at $274K-$470K, Charleston commercial
deeds at 3-5x value); all 12 were CONTRADICTED (10 by `floor_raise_large`; no money published) and
by the new rule 9 are withheld. 3 fell 10-100x to a new county market value that disagrees with the
parcel's own tax value (Burke $1.19M -> $24,800, Lincoln $1.01M -> $11,100; weak flags at most). 3 floor to a county value that looks like another parcel's (a
1,430-sqft house on 6.8 acres at $3.76M while its comps sold at $1.3-1.45M; a Lincoln lot carrying
$6.7M). 1 recorded basket at $36/sqft beside $1.0-1.9M comps (`floor_rejected_extreme`, no money),
1 house $/sqft priced on a lot (now withheld). **Random 40: 21 improvements (mostly
single-family -> land re-typing), 15 noise, 4 defects** (two deed floors, an 8.6x-county land ARV now
withheld, one row that lost its recorded basket, below).
Defect counts over all 4,197 changed rows: floor or sale moves of 2x+ up: 162 (100 flagged); 2x+
down with the county values disagreeing: 10; recorded basket lost: 778 of the 13,485 joined rows
that had one.

### 2.4 Outlier ARVs (task 2): guard + flag
Fixed in `valuation/calc.py` (`_arv_sanity` HARD 3, `arv_basis_check`, flag
`arv_unexplained_outlier`, CONTRADICTED in `grading.py`). An ARV over $1M, over 8x the largest
100%-basis county value, or over 5x the highest cited comp keeps `arv_basis_check = {triggers,
basis, verdict}`; with no basis (county value within 2.5x, 6x for land; a cited comp at half the ARV
or more; the seller's own ask) it is withheld and the note says why. The parcel's own sale is not a
basis (one deed can cover several parcels). On the checkpoint re-priced: **4,508 outliers, 3,705
explained (county 2,770, county+comp 552, comp 320, ask 63), 803 withheld** (581 already
CONTRADICTED, 222 had published a max bid; 227 WARM, 576 COLD, 0 HOT; NC 481, SC 322). Typical
withheld: small-house comps times a 6,000-7,500 sqft subject, one FHFA rescale stamped on several
rows, deed floors, bid proxies. Tests: `tests/test_valuation_outlier_guard.py` (9).
Invariant: `valuation-outlier-explained` (stored checkpoint 4,508 violations; re-priced 0).

### 2.5 Comps lost on 1,599 rows (task 3)
* **1,160: identity changed, comps phase capped.** Lincoln vacant 710, PTS Cloud delinquent 267,
  county PDF delinquent 67, heir parcels 55, ...: the 10/7 row had no parcel id (Lincoln) or another
  key; the fresh row has the county's new 10-digit PIN, so `merge_prior_board` never folded the old
  row onto it (different first_seen on every one) and nothing carried its comps. The comps phase
  then stopped at its 2,400 s cap (`comps.time_capped` on both runs; the 10/8 loop ran 24 minutes
  after a 15.5-minute pool build and never logged `comps.done`) before reaching them. 12,368 Lincoln
  vacant rows carry first_seen 2026-10-06 and 25 of them have comps. The same mechanism took the
  recorded-sales basket from 778 rows (Lincoln vacant 724).
* **410: right to go.** The subject is land and the 10/7 comps were single-family (76 Buncombe
  elderly, 67 Pickens, 67 heir parcels, ...): `validation._validate_comps` drops a comp of another
  kind. Measured on the 10/7 board itself: 120 rows carried comps of a kind that does not fit.
* 29 other.
* Not the cause: kind filters in the matcher (unchanged), comps deleted by code (nothing clears
  `raw.comps`). Context: the 10/8 sold pool was 119,897 sales against 162,882 on 10/6 (-26%), the
  rent pool 0 against 5,578, and the recorded-comps pass refreshed 6,439 of 80,070 rows before its
  1,800 s cap.
* HOT+WARM comps share 40.8% -> 26.6% is mostly dilution: of the 18,560 live HOT+WARM rows with
  comps, 16,741 are HOT+WARM with comps on the checkpoint, 1,314 were demoted to COLD (717 kept
  comps), 172 lost comps, 333 left; 23,311 rows entered HOT+WARM (13,554 new, 9,757 promoted) and 920
  of them have comps. 22,363 have none and only 9 carry the matcher's "no like-for-like" note: the
  capped loop never reached them (or their county pool came back empty).

Fixed in `enrichment_comps.py`: every picked comp is stamped `picked_on`; the matcher loop runs rows
without comps first, then HOT/WARM, then the oldest picks, so the cap falls on rows that keep what
they have; `age_comps()` (after the phase, capped or not) keeps a not-refreshed comp only within
`COMPS_CARRY_MAX_AGE_DAYS` = 365 days of its sale and marks it `carried` with `age_days`;
`carry_forward_from_board()` gives a row with no comps (or no recorded basket) the previous board's
for the same parcel / numbered address / fingerprint in the same county, kind-checked, inside the
window, marked `carried_from`; a stale `comp_median_ppsf` no longer survives beside unanchored new
comps; each county pool's same-kind subset is computed once (identical picks, 30% less matcher time
on a synthetic pool). Dashboard: the comps table shows "(Nd)" or "(Nd, carried)" after the sale
date. Simulated on the two boards: 1,189 of the 1,599 get comps back (84 HOT/WARM); the 410 kind
mismatches stay dropped. Tests: `tests/test_comps_carry_forward.py` (11). Invariants:
`valuation-comps-age` (2 rows on the checkpoint), `valuation-comps-kind-fits` (120 on the 10/7
board, 0 on the checkpoint).

## 3. Accuracy where truth exists (task 4)
Truth: the parcel's own sale recorded within 18 months of the board date, $20,000 or more, not
marked unqualified, at least 25% of the county value, and not a deed whose amount and date sit on
two or more parcels (1,903 such multi-parcel deeds). 1,348 truth rows on the checkpoint (comps_tight,
the +sqft +beds match: 106). The published ARV is circular (the floor raises it to that very sale:
median error 6%), so each row is re-priced with the sale removed:

| slice | truth rows | priced | median signed | median abs. error | p90 abs. error | within 20% |
|---|---|---|---|---|---|---|
| all, before guard | 1,348 | 1,148 | -17.0% | 52.6% | 99.8% | 26.5% |
| all, after guard | 1,348 | 1,143 | -17.3% | 52.4% | 99.8% | 26.6% |
| improved (not land), before = after | 631 | 562 | +2.1% | 34.7% | 136% | 37.4% |
| single family SC | 318 | 303 | +2.1% | 24.1% | 126% | 45.9% |
| single family NC | 283 | 238 | +2.5% | 43.9% | 171% | 26.5% |
| comps_tight | 106 | 99 | +13.4% | 32.8% | 139% | 37.4% |
| land NC (after) | 643 | 517 | -66.0% | 70.3% | 98% | 13.2% |
| land SC | 74 | 64 | 0.0% | 27.6% | 96% | 40.6% |
| recorded-sales ARVs, before -> after | 202 | 103 -> 98 | +28.7 -> +25.1% | 50.9 -> 47.3% | 184 -> 171% | 21 -> 22% |

Improved property: unbiased at the median and noisy, as the June backtest found (+1.7%). The guard
withholds five truth rows (all recorded-sales ARVs). Land: an NC land ARV without the
sale (county value x1.10) sits about 65% under the sales; either NC land values lag badly or many of
these sales are of parcels the roll still calls land after a house went up. Not resolved.

## 4. Open items
* Downward defects are not guarded: a new county market value 10-100x under the parcel's tax value
  publishes as the ARV with only the weak `county_values_disagree` (10 rows moved 2x+ down this
  way). Owner decision whether `county_values_disagree` should withhold money.
* A deed floor under the three thresholds still publishes its number (an $800,000 ARV on a 920-sqft
  mobile home valued at $128,200, flagged `floor_raise_large`, no money). MAX_FLOOR_RAISE_MULT (6x)
  is unchanged.
* Identity changes between runs (PIN migrations) also drop other carried enrichment; the regressions
  area owns the merge.
* The recorded-comps pass re-queries all 80K targets every run under a 30-minute cap and reaches 8%;
  a skip for recently queried rows was not built.
* Tier and equity were not re-scored after the guard (withheld ARVs remove equity evidence from 227
  WARM rows). The dashboard change was syntax-checked, not viewed in a browser. Sample rows were
  checked against the row's own county record, not re-fetched from county sites.

## 5. main.py wiring (the lead applies)
`src/foreclosure_scraper/main.py`, right after the comps phase block that ends
`log.error("comps.failed", traceback=traceback.format_exc())` (before the "FREE COMP SPINE" comment):

```python
    # Comp age + carry-forward (audit 2026-10-09 valuation): runs whether or not the phase was capped.
    try:
        from .enrichment_comps import age_comps, carry_forward_from_board
        enrichment_stats["comps_age"] = age_comps(enriched)
        enrichment_stats["comps_carry_forward"] = carry_forward_from_board(enriched)
    except Exception:
        log.error("comps_carry.failed", traceback=traceback.format_exc())
```
The invariants need no wiring (`scripts/audit_suite.py` discovers `scripts/audit_checks/valuation.py`).

## 6. Outside this area (one line each)
* `scripts/board_selfcheck.py movement()` joins on `_key()` and reports collisions as ARV moves (2.1).
* The 10/8 run's rent pool was empty for every county (`total_rent: 0`, 5,578 on 10/6): rent comps
  were not refreshed.
* Three Henderson LiensNC rows with different sqft carry one market value ($3,473,200) and one
  acreage (10.19): a shared county record (block-binding family).
* Working tree, not mine: `scripts/audit_checks/additions.py` fails to import
  (`tests/test_audit_suite.py::test_the_real_checks_dir_loads`), and
  `tests/test_dashboard_lead_state_js.py` fails on the call-ready slim-field edit in progress.
