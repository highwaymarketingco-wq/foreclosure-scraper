# Full-run execution audit, 2026-09-23

Audit of the local full pipeline run started 2026-09-22 11:14 EDT, finished 2026-09-23 04:50 EDT
(17.6h), exit=0, published 192,805 listings. Read-only: no `load_board`, no scraper or
board-writing script run, nothing committed. Evidence is the run's own log,
`logs/local-run-20260922T111425.log` (147,623 lines, 38.5MB), streamed with `grep`/`python`
line-by-line (never loaded whole), plus two streaming passes over the live board via
`board_stream.iter_board_rows` for cross-checks the log alone couldn't answer. Baseline is
`docs/scraper_registry_reconciliation_2026-09-21.md` (229 registered scrapers, 105 zero-row) and
`docs/scraper_revival_2026-09-21.md` (six scrapers fixed but not yet landed as of 9/21).

The orchestrator itself logged **233** registered scrapers this run (`orchestrator.start
scrapers=233`), not 229 — four more than the 9/21 baseline census. Every number below uses the
run's own count.

## 1. Outcome table — all 233 scrapers

Every registered scraper resolves to exactly one of these seven outcomes; the counts foot
exactly to 233 (verified by joining `scraper.start`/`scraper.ok`/`scraper.timeout`/
`scraper.net_timeout`/`scraper.dormant_off_season`/`scraper.disabled` events by slug).

| Outcome | Count | % of 233 | Meaning |
|---|--:|--:|---|
| OK, rows > 0 | 141 | 60.5% | scraper.ok, outcome=OK, count>0 |
| ZERO_RESULT | 52 | 22.3% | scraper.ok, outcome=ZERO_RESULT, ran clean, returned 0 |
| BLOCKED | 7 | 3.0% | scraper.ok, outcome=BLOCKED — returned 0 AND the shared HTTP client recorded a 401/403/406/409/429 on that scraper's own requests this run (`take_block_signal`); base_scraper promotes a silently-swallowed block to BLOCKED |
| TIMEOUT (no salvage) | 14 | 6.0% | exceeded its soft `timeout_s`, no `self.partial` rows to ship |
| NET_TIMEOUT | 1 | 0.4% | httpx timeout exception (ConnectTimeout) propagated, not caught by the soft-timeout path |
| DISABLED | 2 | 0.9% | feature-flagged off by design, not a board source |
| DORMANT (off-season) | 16 | 6.9% | `active_months` excludes September |

One scraper — `national.fannie_homepath` — has **two** `scraper.start` events: it timed out in
the main scrape phase (15:23 UTC) and was re-run 17h later, near the end of the pipeline, by the
`enrichment_reo_freshness.prune_stale_reo` freshness check (08:08 UTC 9/23), which re-invokes the
scraper directly. That retry succeeded (8,244 rows). It is counted once, under OK, in the table
above; see section 3 for why the retry doesn't actually fix the timeout's effect on the board.

### By namespace

| Namespace | OK rows>0 | ZERO_RESULT | BLOCKED | TIMEOUT | NET_TIMEOUT | DISABLED | DORMANT | Total |
|---|--:|--:|--:|--:|--:|--:|--:|--:|
| national | 32 | 19 | 1 | 7 | 0 | 0 | 0 | 59 |
| counties_sc | 37 | 16 | 4 | 5 | 1 | 1 | 14 | 78 |
| counties_nc | 39 | 8 | 1 | 2 | 0 | 1 | 2 | 53 |
| law_firms | 10 | 4 | 0 | 0 | 0 | 0 | 0 | 14 |
| newspapers | 9 | 2 | 0 | 0 | 0 | 0 | 0 | 11 |
| public_notices | 4 | 1 | 0 | 0 | 0 | 0 | 0 | 5 |
| counties_generic | 3 | 0 | 0 | 0 | 0 | 0 | 0 | 3 |
| counties (misc) | 3 | 0 | 1 | 0 | 0 | 0 | 0 | 4 |
| reo | 3 | 0 | 0 | 0 | 0 | 0 | 0 | 3 |
| city_websites | 1 | 2 | 0 | 0 | 0 | 0 | 0 | 3 |
| **Total** | **141** | **52** | **7** | **14** | **1** | **2** | **16** | **233** |

The 16 DORMANT and 2 DISABLED are exactly the sets the 9/21 baseline names (14 SC seasonal
delinquent-tax counties, `cumberland_tax_foreclosure`, `stokes_delinquent_tax`;
`sc_dew_lien_registry`, `nc_ecourts_estates`) — no change.

### Revival-doc scrapers: did the 9/21 fixes land?

| Scraper | 9/21 revival-doc prediction | This run | Verdict |
|---|---|--:|---|
| `counties_nc.rutherford_wildfire_tax` | walled by a stale robots gate; fix removes it | scraped 3,406, **499 landed on board** | WORKED — first real yield ever from this source, though landing rate (14.6%) is well below the ~63% net-new rate the doc estimated from a small TY2025-heavy sample (the full multi-year sweep overlaps the existing 4,164-row `rutherford_tax` history far more) |
| `counties_sc.sc_tax_delinquent` | rewritten to emit only open-redemption sales; expect ~42 rows, 0 net new | scraped 42, **13 landed** | WORKED as designed (near-zero net-new was the intended outcome) |
| `counties_nc.gaston_tax_foreclosures` | 0 today, no live sale | scraped 81, **0 landed**, all filtered as closed history | WORKED as predicted |
| `public_notices.funeral_home_rss` | main.py DATELESS_OK_SOURCES line lands 50/pass | scraped 50, **50 landed** | WORKED exactly as designed — confirmed in `main.py:727` |
| `newspapers.daily_courier` | parser re-fit; 2 live sales expected | scraped 1, **1 landed** | WORKED (1 of the 2 Sept-22 notices was still live/new by run time) |
| `counties_sc.greenville_tax_distress` | other agent's GIS repoint + DATELESS_OK_SOURCES line (confirmed present, `main.py:728`) | scraped 2,709, **0 landed under this slug** | Scraper itself works. 0 net-new under its own source label is consistent with the revival doc's note #3 that this endpoint mostly re-covers the existing 2,287-row `greenville_delinquent_tax` parcels and was expected to enrich their addresses rather than create new rows — plausible but **not independently confirmed** (would need a follow-up check of `greenville_delinquent_tax` address coverage) |
| `counties_sc.anderson_sheriff` | host is dead, expect fast-fail not timeout | fast NET_TIMEOUT in ~8s (ConnectTimeout), 0 rows | WORKED as predicted — fails fast now instead of burning 120s |

Four of seven revival fixes delivered real net-new board rows this run (rutherford_wildfire_tax
+499, funeral_home_rss +50, daily_courier +1, sc_tax_delinquent netted as designed); the
Greenville fix scrapes cleanly but its board impact is unverified; anderson_sheriff and
gaston_tax_foreclosures behaved exactly as predicted (0 yield, by design).

## 2. New zero-result / blocked / timeout failures not explained by 9/21's known walls

Cross-referencing all 74 non-OK, non-dormant, non-disabled slugs against the 9/21 registry
doc's per-scraper class and the two logged prior runs (9/8, 8/29) named there: **67 of 74 are
consistent with an already-documented wall, EMPTY/DEAD status, or previously-observed flakiness**
(full list of the 52 ZERO_RESULT and 7 BLOCKED slugs was pulled and checked individually — e.g.
`national.usmarshals_realproperty` BLOCKED matches its documented permanent 403 wall;
`counties_sc.kershaw_flc` BLOCKED matches its documented TIMEOUT/BLOCKED history;
`national.sc_public_index` TIMEOUT matches its documented error/timeout history in both prior
logged runs). **7 are genuinely new this run**, ranked by impact:

| Scraper | This run | Baseline (9/21) history | Why it's new | Impact |
|---|---|---|---|---|
| `counties_sc.spartanburg_delinquent_tax` | **BLOCKED**, 0 rows, block signal at 15:33:33Z | OK 2,171 on both 9/8 and 8/29 — never failed in either logged run | first-ever failure for a footprint-county source that normally returns real rows | **HIGH** — 1,707 rows on the board; protected this run only by carryover (see below), no fresh capture |
| `counties_sc.qpaybill_delinquent_roll` | **TIMEOUT** after exactly 901s (900s budget) | "not run" in both prior logs — no precedent either way, but this is the single largest SC tax-roll source (33,527 board rows, 19 counties) | largest SC source in the whole registry got zero fresh capture | **HIGH** — matches the standing memory note that qPayBill's pager is "lossy and silent"; worth a dedicated timeout-budget or per-county-chunking fix |
| `counties_sc.berkeley_paystar_tax` | **TIMEOUT** after 300s | "not run" in both prior logs, no precedent | 2,310-row source, no fresh capture | **HIGH-ish** — protected by carryover, but no new leads this cycle |
| `counties_sc.spartanburg_master_in_equity` | **BLOCKED**, 0 rows, same second (15:33:32Z) as spartanburg_delinquent_tax above | OK 32/19 (rows scraped, all post-filtered) in both prior runs — scraper itself never failed before | status change from "OK-but-filtered" to "blocked at the HTTP layer" | MODERATE — only 2 rows on the board already, low current value |
| `counties_sc.york_overage_claims` | **ZERO_RESULT**, clean | "not run" in both prior logs, 108 rows on the board | first observed zero; could be a legitimate between-cycles gap for an annual claims list, or a real break | MODERATE — protected by carryover |
| `counties_nc.wnc_rod_foreclosure_starts` | **ZERO_RESULT** (scraper itself returned nothing) | documented FILTERED class — historically the scraper always returned 4-6 rows, which the footprint filter then dropped | the scraper used to at least fetch something; now it fetches nothing | LOW — already worthless to the board either way |
| `national.xome` | **ZERO_RESULT**, clean | "partial 19" (9/8) / OK 74 (8/29) — always returned at least some rows before | first clean zero | LOW — 8 rows on the board |

Two of the "new" BLOCKED cases (`spartanburg_delinquent_tax`, `spartanburg_master_in_equity`)
were blocked within the same second. The other four Spartanburg-family scrapers
(`spartanburg_condemned` 1,763 rows, `spartanburg_vacant` 4,659, `spartanburg_flc` 5,
`spartanburg_city_condemned` 92) all succeeded in the same time window, so this is **not** a
general Spartanburg-host rate-limit collision — it points at something specific to the
tax-delinquent-list / master-in-equity endpoint(s) rather than the county's GIS/condemned-property
system.

No error text is available for the BLOCKED cases beyond the outcome tag: `base_scraper.safe_run`
promotes a silent zero-with-block-signal to BLOCKED without logging the underlying HTTP status
code on the `scraper.ok` line itself (only `count` and `outcome` are logged there) — a real
observability gap worth a one-line fix (log the captured block code/host alongside the outcome).

The remaining 67 (52 ZERO_RESULT − 5 new, 7 BLOCKED − 2 new, 14 TIMEOUT − 0 new beyond what's
counted above, 1 NET_TIMEOUT) are unchanged from documented walls: govdeals (Akamai key
rotation), landsofamerica/loopnet/mewborn_deselms/publicnoticesc (Cloudflare/Akamai),
liensnc/nc_sos_ucc (login/Cloudflare), usmarshals_realproperty (403), the paid-service opt-outs
(propwire, probate_foreclosure_leads), the DORMANT-adjacent EMPTY sources (irs_judicial_sales,
irs_treasury, va_acquired, williams, gsa_surplus/gsa_realproperty, bamberg/barnwell_sheriff,
lexington_flc, oconee_tax_sale, meares_auctions, zombie_properties, shelby_star, tryon_bulletin,
asheville_min_housing, nchfa_reo, swain_tax_foreclosures, gaston_surplus_properties, polk_tax),
the NOT-A-LEAD-SOURCE enrichment helpers (opencorporates, sc_sos_entity, cherokee_rod), and the
already-chronically-flaky mixed sources (auction_dot_com, cash_buyer_deeds,
courtlistener_adversary, courtlistener_civil, crexi_multifamily, trulia, sc_public_index (both
slugs), sc_public_index_lis_pendens, spartan_weekly_legals, nc_rod_logan, haywood_tax_foreclosures,
brock_scott, aldridge_pite, korn).

## 3. Time-capped phases

**20 distinct enrichment phases** hit their wall-clock budget this run via the generic
`_await_capped`/`_gather_phases` wrapper (default 900s = 15 min each, `ENRICH_PHASE_MAX_SECONDS`):
`lrcpwa_parcel`, `bk_property`, `county_sales`, `with_address_photos`, `assessor_photo`,
`with_images`, `sold_photos`, `environmental`, `code_enforcement`, `building_permits`,
`gaston_rod`, `cchs_rod`, `aumentum_rod`, `spartanburg_rod`, `dot_ocr`, `resolve_name`,
`court_bid`, `burke_parcel_history`, `lrcpwa_photo`, `opportunity_zone`. Plus 9 more with
custom budgets/names:

| Phase | Budget | Completion evidence | What's left undone |
|---|--:|---|---|
| `orchestrator.link_validate_time_capped` | 600s | **0%** — `validate()` returns a new list; on timeout the code discards any partial work and falls back to `valid = deduped` (223,689 rows), i.e. dead-link checking ran for none of them this run, by explicit design ("a stale link beats a 3h stall") | every link this run is unvalidated |
| `gis_enrich.time_capped` | 2,400s (40 min) | unknown fraction — `enrich_gis` mutates listings in place so partial fills persist, but the log only records the total pool size (223,689), not how many got GIS data before the cap | unmeasured; the event itself is only a warning that the phase didn't finish |
| `parcel_lookup.time_capped` | 1,800s | elapsed 1,811s. Of 19,238 total candidates: 12,457 skipped outright, 6,781 queried (35.2%), 220 matched, 10 address-resolved, 5,485 synthesized | 65% of candidates never got a lookup attempt at all |
| `recorded_comps.time_capped` | 1,800s | elapsed 1,816s. 39,811 candidates, 34,119 budget-skipped (85.7%), 5,052 enriched (12.7%) | 85.7% of comp candidates kept prior/no comps |
| `parcel_from_geo.time_capped` | 2,400s | "proceeding; unresolved leads keep prior fields" — no count | unmeasured |
| `address_backfill.time_capped` | not logged | "proceeding; unenriched leads keep prior fields" — no count | unmeasured |
| `gis_attrs.time_capped` | not logged | same pattern, no count | unmeasured |
| `situs_address.time_capped` | not logged | same pattern, no count | unmeasured |
| `owner_mailing.time_capped` | not logged | same pattern, no count | unmeasured |
| `recorded_sales.time_capped` | not logged | "proceeding; uncomped leads keep prior comps" — no count | unmeasured |
| `zestimate.time_capped` | not logged | "proceeding; leads keep prior valuation data" — no count | unmeasured |
| `rent_comps_extra.time_capped` | 1,200s | no count | unmeasured |
| 20 generic `enrich.time_capped` phases | 900s each | phase name + budget only, no candidate/done count | unmeasured for all 20 |

**Finding:** for 24 of the ~29 time-capped events this run, the log records only that the phase
hit its budget, not how much of its candidate pool it actually got through. Where a count *is*
available (link validation, GIS enrich pool size, parcel lookup, recorded comps), completion
ranged from 0% to ~35%. This is by design — every one of these phases is fail-open ("keep prior
fields") specifically so a timeout degrades enrichment freshness rather than dropping rows or
stalling the run — but the lack of a per-phase done/total counter is a real monitoring gap: there
is no way from this log alone to know whether, say, `resolve_name` got through 90% of its pool or
9%.

### fannie_homepath fix — did it behave as expected?

**No.** The task description's expectation ("should no longer time out") did not hold: it timed
out in the main scrape phase at 15:23:19Z, 9 minutes in, exactly as it used to. What's different is
that `enrichment_reo_freshness.prune_stale_reo` (a separate, later pipeline step whose whole
purpose is snapshot-REO freshness pruning, not fresh-lead capture) independently re-invokes the
`national.fannie_homepath` scraper near the very end of the run (08:07:46Z, ~17h later) to build a
live-URL set for pruning stale carryover rows. That retry succeeded (8,244 rows,
`reo_freshness.live`), and used those 8,244 rows only to prune 24 stale board entries
(`reo_freshness.done pruned={'national.fannie_homepath': 24}`) — **it does not land any of the
8,244 fresh rows as new listings.** The final board (verified via `board_stream`) carries only
**124** `national.fannie_homepath` rows, down from the 243 documented on 9/21. Fannie Mae's own
live inventory today is 8,244 properties. The board is capturing **1.5%** of it. This is an
unresolved, and currently invisible, coverage gap: nothing in the run's exit code, alerts, or the
`reo_freshness.done` log line signals that the source is 98.5% under-covered — from the log's
point of view it looks like a routine freshness-prune.

### Parcel-fusion fix (`dedupe.suspicious_primary_key` / house-number guard) — did it behave as expected?

**Partially — contained, not eliminated.** The house-number guard (the fix referenced in
project memory for the PIN_RE fake-parcel fusion bug) ran three times this run (once per dedupe
pass) and blocked a large and *growing* number of would-be bad merges:

| Dedupe pass | `house_number_guard` (strict signature) blocked | `house_number_guard_pass2` (fuzzy address) blocked | `suspicious_primary_key` residual (keys / addresses fused) |
|---|--:|--:|--:|
| 1 (15:53-15:59, first fresh-run dedupe) | 1,112 | 43,858 | 66 keys / 486 addresses |
| 2 (16:01-16:12, board-persist merge) | 2,481 | 112,508 | 81 keys / 795 addresses |
| 3 (23:09-23:26, second global dedupe2) | 2,519 | 110,973 | 93 keys / 1,281 addresses |

The guard is doing real work (blocking over 110,000 fuzzy-match merges by pass 3 that would have
silently fused distinct properties). But `dedupe.suspicious_primary_key` — a different,
parcel-key-level check — still flags a growing residual: by the third pass, 93 parcel keys are
each associated with more than one distinct address (worst case: `parcel:NC:pender:3208905620`
fused across **216** distinct addresses). One `dedupe.suspicious_fusion` event also fired (3
groups, 17 rows fused, all mobile-home-park-style shared-parcel signatures in SC). There is no
prior-run baseline for this exact counter to compare against, so it is not possible to say whether
93/1,281 is better or worse than before the fix — only that a real, sizeable class of
suspicious parcel-level fusion still exists after the fix, growing across the run's own three
internal dedupe passes as more rows accumulate.

## 4. Tracebacks / exceptions

**Exactly one** traceback in the entire 147,623-line log (`grep -c Traceback` = 1), and it is the
already-known Google Sheets export failure:

```
gspread.exceptions.APIError: APIError: [500]: Internal error encountered.
  main.py:3631 run -> sheets.py:125 write_listings -> gspread/worksheet.py:1246 update
  -> gspread/http_client.py:173 values_update -> gspread/http_client.py:128 request
event: sheets.failed, level=error, 2026-09-23T08:48:33Z
```

Checking all `level=error` events independently (not just ones containing the literal word
"Traceback") turns up only one other: `sc_public_index.nodriver_error` (×2, both for Spartanburg
County) — "Failed to connect to browser ... could be when you are running as root" — a known
nodriver/browser-launch failure consistent with `counties_sc.sc_public_index`'s documented
"mixed" history, not a new exception class. `scraper.error`, `scraper.http_error`,
`scraper.conn_error`, `orchestrator.scraper_task_failed`, `carryover.failed`,
`reo_freshness.failed`, and `reo_freshness.scrape_failed` — every other exception-catching path
in the orchestrator — logged **zero** events this run. No unhandled exceptions beyond the known
Sheets failure.

## 5. Dedupe / merge math

Full accounting, traced end-to-end through the run's own logged counters:

```
scrape phase:  195,089 raw (incl. 4,564 replayed via orchestrator.carryover_applied
               for 5 zeroed sources: brock_scott 66, spartanburg_delinquent_tax 1,707,
               york_overage_claims 108, berkeley_paystar_tax 2,310, sc_public_index_lis_pendens 373)
  -> partitioned:        active 194,800 / sold_pool 289
  -> in_scope:           187,074  (pruned 7,726)
  -> active_only:        184,241  (pruned 2,833)
  -> flip_filtered:      183,920  (pruned 321)
  -> dedupe (1st pass):  121,367  (pruned 62,553)             <- "fresh_count"

board_persist (merges fresh vs. the prior persisted board):
  fresh_count 121,367, prior_count 183,808
  matched 78,268, fresh_only 42,259, prior_only_kept 103,162
  aged_out_terminal 53, aged_out_misses 585
  merged_count 223,689

  identity check: prior_only_kept + matched + fresh_only
                = 103,162 + 78,268 + 42,259 = 223,689 = merged_count  EXACT MATCH
  fresh accounting: matched + fresh_only = 120,527 vs fresh_count 121,367
                -> 840 rows (0.7%) unaccounted for on the fresh side
  prior accounting: matched + prior_only_kept = 181,430 vs prior_count 183,808
                -> 2,378 rows (1.3%) unaccounted for on the prior side, of which only
                   638 are named (aged_out_terminal 53 + aged_out_misses 585); ~1,740
                   rows (0.95% of the prior board) leave no logged trace of why they
                   are neither matched nor kept

  -> valid_links:            223,689 (unchanged; link-validation was fully time-capped, section 3)
  -> dedupe2 (2nd global pass): 202,484  (collapsed 21,205)
  -> oceanfront_repass:      194,444  (dropped 8,040)
  -> scope_repass:           193,810  (dropped 634)
  -> drop_countyless_national: 192,828  (dropped 982)
  -> graded:                 192,829  (1-row rounding vs. the arithmetic above; negligible)
  -> reo_freshness prune:    192,829 - 24 (stale fannie_homepath URLs) = 192,805

FINAL PUBLISHED TOTAL: 192,805  <- matches run_local.sh's own web_artifact.written total exactly
```

**Verdict on the merge math: it checks out.** The `merged_count = prior_only_kept + matched +
fresh_only` identity is exact, and the full chain from `merged_count` (223,689) down to the
published total (192,805) is traceable step-by-step through six further named filters/passes with
no unexplained jumps — the one open question is the ~1,740-row (0.95%) gap in the *prior-board*
accounting at the board_persist step, where the two named "aged out" counters (aged_out_terminal
53, aged_out_misses 585) don't fully explain how many prior rows were dropped outright rather than
carried or matched. That gap is too small to change the headline conclusion but is worth a named
counter so it isn't silently absorbed next time it's 10x larger.

**No evidence of double-counting.** `matched` (rows present on both the fresh scrape and the
prior board) is counted exactly once in the `merged_count` identity above; there is nothing in
the four dedupe-related counters (`orchestrator.deduped`, `orchestrator.dedupe2`,
`dedupe.house_number_guard*`, `dedupe.suspicious_primary_key`) that suggests a row surviving two
passes was added to the total twice.

**Board-side spot checks** (one `board_stream` pass, 192,805 rows confirmed, matching the
published total exactly):

| Source | Board rows | Note |
|---|--:|---|
| `counties_sc.qpaybill_delinquent_roll` | 30,481 | preserved via `prior_only_kept` despite this run's TIMEOUT — down slightly from the 33,527 documented 9/21, not zeroed |
| `counties_sc.spartanburg_delinquent_tax` | 1,568 | preserved via explicit `carryover_applied` (1,707 replayed) despite BLOCKED this run |
| `counties_sc.berkeley_paystar_tax` | 2,105 | preserved via carryover despite TIMEOUT |
| `national.fannie_homepath` | 124 | down from 243 (see section 3) — the freshness prune plus upstream dedupe/repass losses outpaced what little fresh data got in |
| `counties_nc.rutherford_wildfire_tax` | 499 | net-new from the revival fix |
| `counties_sc.greenville_tax_distress` | 0 | scraped 2,709, landed 0 under its own slug (section 1) |

Neither timeout nor block this run caused a source to disappear from the board — the carryover
mechanism and the broader prior-board-preservation in `board_persist` both did their job.

## 6. Verdict

**"All sources worked" and "everything executed perfectly" — no, on both counts, though the run
was healthy overall and several long-standing walls came down.**

- **141 of 233 registered scrapers (60.5%) returned real rows this run.**
- **18 were correctly idle by design** (16 seasonal-dormant, 2 disabled), not failures.
- **67 of the remaining 74 zero/blocked/timeout outcomes are unchanged from documented walls**
  (Cloudflare/Akamai/login/403 walls, paid-service opt-outs, genuinely-empty sources, or sources
  already known to be flaky in both prior logged runs) — not new problems.
- **7 are new-this-run failures worth investigating**, three of them high-impact:
  `spartanburg_delinquent_tax` (BLOCKED, first-ever failure for a 1,707-row footprint source),
  `qpaybill_delinquent_roll` (TIMEOUT, the single largest SC source at 33,527 rows), and
  `berkeley_paystar_tax` (TIMEOUT, 2,310 rows). All three were protected from board damage by
  carryover/prior-row preservation, so no leads were lost — but no fresh leads were captured from
  them either this cycle.
- **The revival-doc fixes mostly worked**: rutherford_wildfire_tax (+499 net-new, first real
  yield ever), funeral_home_rss (+50 exactly as designed), daily_courier (+1), sc_tax_delinquent
  (netted as designed), anderson_sheriff and gaston_tax_foreclosures (0 yield, exactly as
  predicted). greenville_tax_distress scrapes cleanly but its board impact is unverified.
- **The fannie_homepath fix did not hold** — it timed out in the main phase exactly as before; a
  late, unrelated freshness-pruning pass recovered enough to avoid mass-deleting stale rows but
  did not backfill fresh ones, leaving the board at 124 of Fannie's 8,244 currently-live
  properties (1.5% coverage), with no alert surfacing that gap.
- **The parcel-fusion guard is working but not complete** — it blocked over 110,000 risky merges
  by the final dedupe pass, yet 93 parcel keys / 1,281 addresses still show up as suspiciously
  fused after all three passes.
- **Exactly one traceback in the whole run**, the already-known, non-fatal Sheets export
  failure; no other unhandled exceptions.
- **The dedupe/merge/publish math is internally consistent end-to-end**, down to matching the
  published 192,805 total exactly, with one small (~1%) unexplained gap in the prior-board
  accounting worth a named counter.

## Top 5 fixes, ranked by lead-yield impact

1. **`counties_sc.qpaybill_delinquent_roll` timeout** — the single largest SC source (33,527
   rows, 19 counties) got zero fresh capture this run. Matches the standing memory note about its
   lossy/silent pager; worth a per-county-chunked run or a longer/segmented budget so one slow
   county doesn't blank the other 18.
2. **`counties_sc.spartanburg_delinquent_tax` newly BLOCKED** — first-ever failure for a
   1,707-row footprint-county source that has never failed in either prior logged run. Needs a
   live probe of whatever endpoint it hits (distinct from the 4 other Spartanburg scrapers that
   succeeded in the same window) to see if it's a new WAF/rate-limit or a one-off.
3. **`national.fannie_homepath` still times out, and its late-pipeline "retry" doesn't backfill
   rows** — the board is capturing 1.5% of Fannie's live REO inventory (124 of 8,244) with no
   alert. Either fix the main-phase timeout (raise its budget or split its bbox grid into smaller
   chunks) or have `prune_stale_reo`'s 8,244-row fetch actually land as fresh listings instead of
   being used for pruning only.
4. **`counties_sc.greenville_tax_distress` lands 0 rows under its own slug despite scraping
   2,709** — either confirm this is intentionally folding into `greenville_delinquent_tax`'s
   address coverage (in which case it's working as designed and should be documented as such) or
   find out why a whitelisted, in-scope, dateless TAX_LIEN source nets zero.
5. **`counties_sc.berkeley_paystar_tax` timeout (2,310 rows, no fresh capture)** — lower urgency
   than #1/#2 since it's smaller and fully carryover-protected, but it and qpaybill both timing
   out in the same run suggests SC tax-roll sources broadly need more budget or better
   incremental/resumable fetching, not just a one-off retry.

Secondary, lower-yield-impact items: log the captured block-code/host on `scraper.ok`
BLOCKED lines (section 2); add a done/total counter to the ~24 time-capped enrichment phases that
currently log only `{phase, budget_s}` (section 3); add a named counter for the ~1,740-row gap in
the board_persist prior-side accounting (section 5).
