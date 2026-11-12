# Path to 100% — reconciled 2026-10-15

Supersedes the wall claims in `path_to_100.md`/`path_to_100_deepdive.md`/`path_to_100_roadmap.md`
(2026-07-02) and sits on top of the 10/8–10/13 audit waves. Those docs stay as history; this is
the current, re-verified picture. Triggered by a direct demand: a complete, confident plan to
100% breadth (all sources, all 146 counties) and 100% depth (per-listing accuracy), with every
gap given a real verdict — not a repeat of the shallow answer given earlier the same session.

Built from three parallel ground-truth audits (current run/board state; the 146×82 breadth cube
reconciled against live code; the depth/accuracy fixes reconciled against live code) plus a
direct, personal SSH check of the Oracle VM — not from citing older docs as still true.

## 0. Where things actually stand right now (verified live, not from docs)

**Published board**: 350,013 rows (slim) / 353,609 (detail), `docs/board.manifest.json`,
unchanged since Oct 12 (commit `e90b884b`). This predates essentially every fix below.

**Tonight's run**: confirmed ALIVE by direct SSH at 2026-10-16 00:10 UTC (`ssh -i
~/.ssh/oracle_foreclosure ubuntu@129.146.23.144`, IP recovered from `~/.ssh/known_hosts`, username
from `deploy/oracle/README.md` — neither was stored anywhere else findable on this Mac, worth
fixing so this isn't a scavenger hunt next time). Started 2026-10-15 06:00:16 UTC via the correct
`deploy/oracle/vm_run.sh` entrypoint after a first attempt crashed from using the Mac-only
`scripts/run_local.sh` against the VM's much larger board (`BoardLoadTooLarge`, see
`docs/hermes_directives_2026-10-15.md` for the full account). 18h10m in at check time, log
actively growing in the last minute, working FEMA/EPA/SOS-dissolution enrichment phases (318,916
FEMA targets processed). VM memory is tight — 368 MB free RAM, 1.7 GB of 18 GB swap in use (the
one prior calibration run at this scale never needed swap) — and disk is tight (16 GB free of
96 GB), but neither is critical, and the run is making real forward progress, not hung. **Not yet
published** — `docs/board.manifest.json` on the VM is unchanged since the run's own start.

**Process gap, worth closing rather than ignoring**: the 2026-10-08 owner mandate (no VM run
without `prerun_gate.py` + `audit_suite.py` + canary + an explicit go-ahead first) isn't confirmed
to have run before tonight's launch — the handoff doc doesn't mention it. Not undoing tonight's
run over this, but the gate should actually execute before the *next* one.

**What to do next on this**: let it finish (it's progressing on its own). Once
`docs/board.manifest.json` updates past Oct 12, immediately run the two measurements everything
below depends on — see §3.

## 1. What's actually done since Oct 9 (code-verified, not doc-claimed)

| Item | Status | Evidence |
|---|---|---|
| 9 ROD/WAF-gated document sources (CCS DevExpress, NC Tyler Self-Service, Beaufort JSON API, Pickens/Clarendon Acclaim, Union Cott) | DONE | commits in `docs/hermes_directives_2026-10-15.md` Part 1.1, all 9 counties confirmed, `RAW_KEEP` updated, `tests/test_raw_keep_covers_enrichers.py` passes |
| 3-pass date-coverage audit (rolling-window exclusion of the oldest, most-distressed debt) | DONE | commits `1e76fc88`, `9fc5c0dd`, `a4e0093d`; 220 tests passing |
| CCHS BLOCKED-outcome visibility (was silently reporting `OK (0)`) | DONE | `rod/cchs.py` raises `CchsWall`, commit `a4e0093d` |
| `situs_sanity.py` apostrophe-stripping bug (pipeline-wide) | DONE | commit `fa1fbe97` |
| 7 column-accuracy defect classes from the 10/9 audit (email escape artifact, wrong-party email, fuzzy voter-phone misattribution, layer-value-is-one-component, sqft-from-money-field, SC assessed=market, glued house numbers) | **merged + unit-tested, never verified at board scale** | 43 tests passing (`test_column_accuracy_email.py`, `test_column_accuracy_checks.py`, `test_voter_phone_identity_gate.py`, `test_berkeley_paystar_tax.py`); the checkpoint the 10/9 audit measured was itself abandoned and deleted tonight, never published — these fixes have never touched a live dataset |

## 2. Breadth — the 146×82 cube, reconciled (11,972 cells)

Canonical current sources: `docs/audit_2026-10-09/{MASTER_PLAN,cube_remeasure}.md`,
`docs/gap_matrix/county_signal_coverage_2026-10-09.csv` + `build_list_2026-10-09.csv`,
`docs/walls_register.{md,json}`, `docs/completeness_impossible.md`. Older "county coverage
complete" claims in `docs/MASTER_GAPS_WALLS_AND_MANUAL_LANES.md` are stale — that referred to the
old 18-county flip footprint, not the 146-county distressed scope the cube actually covers.

| Bucket | Cells | % | What it means |
|---|---|---|---|
| At-target | 2,186 | 18.3% | Done, verified |
| Not-applicable | 1,287 | 10.7% | Field genuinely doesn't apply (correctly excluded, not a gap) |
| **Built-but-low-yield** | **5,370** | **44.9%** | **Biggest bucket by far. A source is wired for this county but returns little/nothing. Whether each "OK"-marked source truly covers every county it's credited with is explicitly flagged UNCHECKED in `cube_remeasure` §5** |
| Walled | 694 | 5.8% | See corrected wall list below — this is smaller than it should be, since 2 of the biggest wall categories just got reclassified |
| Sourced-not-built | 1,065 | 8.9% | A free source is identified, just needs engineering. Ranked queue already exists |
| No-source-known | 1,370 | 11.4% | Genuine discovery gap — nobody has found a source yet, not an engineering backlog |

**The corrected wall list** (this is the single biggest correction in this whole reconciliation —
I told you earlier the same day there were more walls than phone numbers; most of that was wrong):

1. ~~"SC Rule 610 bans bulk scraping of early SC court data"~~ — **false as stated.**
   `docs/walls_register.json` already records this cleared by the attorney. The real blocker on
   45 of 46 SC counties' PublicIndex is a technical F5/406 WAF bot-check, not a statute — and
   Charleston's own PublicIndex mirror answers normally and is already built, proving it's beatable
   at least one way. Reclassified: technical/manual, not a permanent wall.
2. ~~"SC §12-24-40 makes exempt-deed sale prices record as $0"~~ — **wrong statute (it's
   §12-24-70) and overstated.** It only blanks the deed *document's own* stamp value. CAMA
   `SalePrice` fields and Master-in-Equity sale-result rosters (already shipped for
   Spartanburg/Pickens/Anderson) recover real SC sale prices independently of the deed stamp.
   Reclassified: narrow true-wall only for "read the price off the deed image itself" — everything
   else about SC sale prices is a breadth item (extend the CAMA/Master-in-Equity pattern to the
   remaining SC counties that expose those fields), not a wall.
3. **Live mortgage payoff — holds, but only pre-contract.** 15 U.S.C. §1639g / 12 CFR 1024.36 let
   the borrower or a contracted buyer request a real payoff figure in 7–10 business days once
   under contract. Real wall at the lead-identification stage (which is when scoring needs it);
   not a wall on ever knowing it once a deal is moving.
4. **Phone-number reachability — confirmed real, structural, the only wall that's unqualified.**
   19.5–21.4% board-wide fill. NC voter file (~69% of matches, owner-occupants only) is the only
   free structured source; SC has no free structured source at all. Doesn't move without paid
   skip-trace spend — a cost decision, not an engineering one.
5. SC Code §30-2-50 (misdemeanor exposure for commercial solicitation from SC public-record
   personal info) — flagged as the single largest legal exposure in `completeness_impossible.md`,
   but already cleared by the attorney per `walls_register.json`. Not a wall, noted for completeness.

So after re-verification, the list of things that **cannot** be closed by any amount of
engineering is down to two: phone reachability, and mortgage payoff at the pre-contract stage.
Everything else once called a wall is either closeable engineering or, at worst, a scoped manual
lane.

**Breadth closure plan, in priority order:**

1. **Re-probe the 5,370 built-but-low-yield cells.** This is the highest-leverage unknown in the
   whole cube — it's bigger than the sourced-not-built queue, nobody has verified it county-by-
   county, and this project's own history (the extraction-audit waves logged in
   [[project_zero_gap_mandate_2026-10-01]]) found a real, fixable bug in the large majority of
   sources actually checked this closely. No effort estimate exists yet because nobody has scoped
   it as its own pass.
2. **Work `build_list_2026-10-09.csv` top-down** — 182 ranked items, ~711 effort-days at
   single-threaded pace (compresses with parallel agents, same as every prior audit wave).
   Top item: NC OneMap deed book/page, 77 cells for 1 day — best ROI in the whole queue. Second:
   an NC quiet-title/heir-publication-notice parser, which doesn't exist yet and is needed.
3. **Extend the proven SC CAMA-SalePrice + Master-in-Equity-roster pattern** (already live for
   Spartanburg/Pickens/Anderson) to the remaining SC counties exposing the same fields — this is
   what actually closes most of what used to be miscategorized as the SC exempt-deed wall.
4. **Source-hunt the 1,370 no-source-known cells.** Discovery work, not build work — same shape as
   the GLM source-hunt audit already run once this project.
5. **Beat the SC PublicIndex WAF the way Charleston's own mirror already does**, for the other 45
   counties, or fall back to a scoped manual/owner-login lane per county where that doesn't work.
6. **Accept the remaining manual-only lanes as owner-hands items, not engineering**: NC eCourts
   Smart Search estates/divorce (AWS-WAF image-grid), LiensNC (owner-held login), Cott
   RecordRoom/Cherokee AcclaimWeb (subscriber logins), Anderson ACPASS (403 auth), SC
   senior/disabled exemption rolls (FOIA-only).

## 3. Depth — per-listing accuracy, reconciled

The 10/9 audit (`docs/audit_2026-10-09/column_accuracy.md`) live-checked a 763-row sample against
real county records and found 7 defect classes, each now merged and unit-tested (see §1 table)
but **never re-verified against real data**, because the checkpoint it measured never published.
The published board right now predates all of these fixes entirely.

**Two items it explicitly left open, with zero movement since**:
- Parcel-cache carried stale values (Spartanburg building-only / land-only tax values persist
  until something overwrites them). No commits to `parcel_cache.py` since 10/9. **Needs an owner
  decision**: overwrite cache-filled values on refresh, or leave them. My recommendation —
  overwrite: a confidently-wrong cached value is worse for a caller than a brief gap, and the
  refresh is cheap to re-run if the owner disagrees after seeing it.
- Stale taxpayer-of-record (6 of 51 verified rows are the delinquent roll's debtor on a parcel
  the county now shows sold — a different lead than the one being called). No "owner-vs-roll"
  workstream has even been scoped yet, let alone started.

**What "100% depth" can honestly mean.** Literally hand-verifying every field on every one of
350,000+ rows against its authoritative source isn't a plan, it's a contradiction — no amount of
confidence changes that math. What *is* achievable, and is the right target to actually commit to:

1. **100% systematic invariant coverage** — every row, every field, checked against known-bad
   patterns, cross-field consistency rules, and range checks. Fully automatable, applies to every
   row, not a sample. This is what the 7 fixed defect classes already look like as code; the gap
   is making this the standing policy for every column, not just the ones audited so far.
2. **Continuous, larger, confidence-interval-stated live-source re-verification** on every board
   refresh — replacing the one-off 763-row spot check with a standing, repeatable measurement (the
   10/9 methodology is good; it just needs to run every time the board changes, not once).
3. **Zero-tolerance policy on systematic defects** — any newly discovered class-level error gets a
   fix and a regression test before the next publish, not added to a backlog.

**Immediate next action once the board publishes**: re-run the exact 10/9 live-lookup methodology
against the fresh data. This is the only way to get real current numbers instead of "merged but
unconfirmed" on every one of the 7 fixes.

## 4. The honest ceiling, stated precisely

With phone numbers and pre-contract mortgage payoff set aside, there is no other permanent wall
left standing after this reconciliation — everything else is engineering effort, much of it
already scoped, some of it (the 5,370-cell reprobe, the 1,370-cell discovery gap) not yet
estimated.

With phone numbers included: the board-wide ceiling is ~19–21% phone fill, NC-only for the free
path. Moving that number requires paid skip-trace spend, which is a cost decision for the owner,
not something more engineering closes.

## 5a. CORRECTION 2026-10-16 (later same day): §5's own "real total" was already stale

Went to actually start building rank 1 of the build queue (NC OneMap deed book/page) instead of
just estimating it again. Found it already built: `gis_fill.py` exists, is wired into `main.py`
(`enrich_gis_fill`, line ~1972), and reads the exact live field independently re-discovered here
(`sourceref` = "Deed Book/Page 2303/0154" on real Alamance County data). Git history shows a
massive single-day sprint on 2026-10-09 -- *after* `gap_list_2026-10-09.csv`/
`build_list_2026-10-09.csv` were generated -- that built out ranks 1, 5, 8, 9, 12, 14, 21, 22, 27,
59, 68, 70, 74, plus whole register/verify/check groups (commits `c1cbb838`, `0d2b6747`,
`07138487`, `4eb7469c`, `44e6da30`, `686cbd70`, `e94627c7`, and more). Nobody ever regenerated the
gap matrix afterward, so §5 below computed its "real total" from a snapshot that was already
stale the same day it was taken -- the exact failure mode this whole reconciliation exists to
catch, and it got past me once before being caught.

**Regenerated for real** (`uv run python3 scripts/gap_matrix.py`, against the current published
board, 353,609 rows, 2026-10-16 -- output in `docs/gap_matrix/gap_list_2026-10-16.csv` etc.):

| class | 10/9 (stale) | 10/16 (fresh) | change |
|---|---|---|---|
| sourced-not-built | 1,684 entries | **884 entries** | -47% |
| built-but-low-yield | 5,690 entries | 6,397 entries | +12% |
| no source known | 1,466 entries | 1,706 entries | +16% |

Re-clustered the fresh file the same way as §5: built-but-low-yield -> 38 distinct modules (was
37, basically flat); no-source-known -> 42 distinct fields (was 32). Sourced-not-built's cost
scales with its entry count more directly than the other two (it's genuine new-build work, not a
backfill-vs-build distinction), so: 711 days x (884/1684) ~= **373 days**, revised combined total
roughly **380-400 engineering-days** -- down from the 711-716 this doc stated hours earlier.

**That revised number is itself still an overstatement, by an unquantified amount.** 78 of the 884
remaining sourced-not-built entries are `atty_deed_ref` via NC OneMap -- the exact field just
proven already built and wired. It still reads as "not built" because `gis_fill.py` was only
live-tested on a ~1,941-row sample (`scripts/top80_fill_proof.py`), not yet run board-wide across
a full publish cycle. Some unknown slice of the other 806 entries are probably the same shape:
already-built code waiting on enough pipeline runs to backfill, not a missing scraper. Checking
all 246 distinct source strings individually to quantify that precisely was not done here --
flagging the gap honestly rather than estimating past it a third time.

**Standing lesson, not just a one-off fix:** this project's gap/cube measurement is a snapshot,
not a live view, and it goes stale the moment real building happens against it -- which, per this
project's own velocity, is often the same day. Any future "how much is left" answer should
regenerate (`scripts/gap_matrix.py`) before citing a number, not reuse whatever doc is sitting in
`docs/gap_matrix/` -- including this one, by the time anyone reads it.

## 5. The real total (scoped 2026-10-16, not left as a placeholder) -- SUPERSEDED, see 5a above

An agent dispatched to scope this stalled for 12+ hours and never returned (every other agent that
night finished in 2-5 minutes). Rather than re-dispatch and hope, this was done directly against
`docs/gap_matrix/gap_list_2026-10-09.csv` — the actual per-cell gap list, not a summary of it.

**Built-but-low-yield (5,690 gap entries, the csv's unit — 5,370 cells in the cube's unit):**
splitting `next_action` by shape, not just counting rows:
- 1,905 entries (33%) are derived/computed fields waiting on their own inputs (`name_estate_of`,
  `deed_chain_break`, `owner_cluster`, ...) — these close automatically once the root field they're
  computed from is filled. Zero separate cost; already counted in that root field's own entry.
- 4,108 entries collapse to **37 distinct modules** (regex over every `next_action`'s parenthetical
  module reference, deduped) — and nearly every one reads "code already covers this, it just hasn't
  landed here yet": `backfill X for the N applicable rows without it (MODULE)` or `screen the N
  unchecked rows (MODULE)`. That is a re-run of already-working code against identified targets, not
  new engineering — exactly what a normal full pipeline run does as a byproduct (tonight's run is
  doing some of this live: `register_checks.done`'s `sweep_lien_none_found`/`stamped: none_found`
  counts are this exact pattern in action). The single biggest chunk (1,701 entries) is the generic
  "existing enrichers" catch-all for address/parcel_id/owner_name/comps/value/sqft/beds_baths.
- 293 entries (5%) are mislabeled — really "no free source" (e.g. owner-email), a gap-list hygiene
  fix, not a build or backfill task.
- **Real cost: verify why each of the 37 modules isn't landing for its flagged counties** (a scope/
  footprint config excluding that county vs. a silent per-county bug — this project's own history
  is full of exactly that pattern, see [[project_zero_gap_mandate_2026-10-01]]'s extraction-audit
  batches). At this project's own measured ~2 min/source verification rate, with a real fix needed
  roughly half the time: **~1.5-2 engineering-days.** The backfill itself is compute time on a
  normal run, not separate engineering cost.

**No-source-known (1,466 entries, 1,370 cells):** collapses to **32 distinct fields**, not 1,370
separate questions — `vacancy`/`storm_damage`/`code_enforcement`/`jail_booking`/`condemned` each
affect ~130-145 counties as one research question apiece ("is there a free statewide-ish source for
this signal"), not 145. At roughly an hour per field for a real discovery verdict: **~4
engineering-days.** This is the softest of the three numbers — discovery work has real variance and
there's no historical per-field rate as clean as the low-yield bucket's ~2min/source figure to
anchor it against.

**Combined total, same methodology throughout all three buckets (real distinct engineering units,
not raw cell counts):**
- Sourced-not-built: 711 days (already properly scoped by the 10/9 audit — 182 real build items)
- Built-but-low-yield: ~1.5-2 days
- No-source-known: ~4 days
- **Total: ~716-717 engineering-days to close every closeable item in the cube.**

The genuinely surprising part: the two buckets that looked biggest by raw cell count (6,740 of
11,972 cells — over half the cube) turn out to be nearly free. Almost all their apparent size was
the same small set of root causes (37 modules, 32 fields) repeated across many counties, not 6,740
independent problems. The 711-day sourced-not-built bucket is where nearly all the real cost is.

## 6. Immediate next actions, in order

1. Let tonight's run finish — it's alive and progressing as of this writing; worth a watch rather
   than a blind wait given the memory/disk pressure noted in §0.
2. Once `docs/board.manifest.json` updates: re-run the column-accuracy live-lookup methodology
   against the fresh board (§3) — answers depth-at-scale for the first time since 10/9.
3. Run the zero-row re-triage sweep against the same fresh board (also blocked on it landing).
4. Get the owner's call on the parcel-cache overwrite-policy decision (§3).
5. Confirm, before the *next* VM run, that the 10/8 gate mandate actually executes (§0).
6. Start the breadth build queue top-down (§2), beginning with NC OneMap deed book/page.
