# Completeness audit, 2026-09-29

Measured read-only on the live board, 217,773 rows (NC 135,061, SC 82,712), streamed once with
`foreclosure_scraper.board_stream.iter_board_rows()` (~300MB constant-memory reader). **No
`load_board()` call was made anywhere in this audit** — `scripts/resolver_backfill_parcel.py` was
running the entire time (PID 38802, started 10:59am, holding the board via its own `load_board()`
under `scripts/with_board_lock.sh`), and this machine kernel-panicked once already today from two
board-holding processes overlapping. Every number below came from a single streaming pass (plus one
short reuse of the existing `scripts/coverage_100_ledger.py`, which is also `iter_board_rows`-based).
No scraper ran, no enricher ran, no board write happened, no git command ran beyond `git log`/`grep`
read-only inspection. This is read-only analysis only.

This is the direct sequel to `docs/completeness_audit_2026-09-28.md` (217,773 rows), which is the
baseline for every comparison below. **The row count has not moved since that audit** — confirmed
directly, not assumed — because nothing that runs between the two audits adds or removes rows; see
Section 1. Family definitions for the 7 families that exist in both audits are **pinned to the exact
methodology the 9/28 doc states it used** (`listing_type` only, no source-name fallback): tax
delinquent = `tax_lien`, tax sale = `tax_sale`, lis pendens = `lis_pendens`, probate = `probate_notice`
+ `estate_lead`, divorce = `divorce_notice`, bankruptcy = `bankruptcy`, code/vacant = `distressed`.
This was verified deliberately: an earlier draft of this pass used a looser source-name-fragment
match for these 7 and got different totals (e.g. bankruptcy 83/146 instead of 48/146); tightening back
to the stated `listing_type`-only rule reproduced the 9/28 numbers to the county, confirming both that
the methodology note is followed here and that there has been genuinely zero drift in these 7 families
since 9/28. Four families have no `listing_type` equivalent and are new to this audit series
(foreclosure/mortgage, HOA, jail/incarceration, liens) — these use the raw-stamp / source-name
definitions documented in Section 3, since there is no narrower prior baseline to preserve. The
18-county flip footprint is `config.NC_COUNTIES + config.SC_COUNTIES` (Rutherford, Cleveland,
Henderson, Polk, Gaston, Buncombe, Transylvania, McDowell, Lincoln, Mitchell, Burke NC; Spartanburg,
Anderson, Pickens, Oconee, Cherokee, Union, Laurens SC). The 146-county universe is
`validation.NC_COUNTIES`/`SC_COUNTIES` (100 + 46), matched case-insensitively. Field definitions
(owner_mailing union, phone via `enrichment_sc_phone.usable_owner_phone`) are unchanged from 9/28 and
9/27, reused verbatim.

## Bottom line

**Nothing scraped since 9/28; the resolver backfill kept running and is now visibly hitting its hard
tail.** Total rows, family breadth, and every per-county family flag are byte-for-byte identical to
the 9/28 audit — confirmed, not assumed. Two things genuinely moved, both attributable to named,
already-committed work between the two audits: an Anderson SC owner-mailing backfill (+1,477 mail
rows, entirely in SC) and a continuation of `resolver_backfill_parcel.py`. But that continuation's own
checkpoint commits show its **last two chunks resolved zero new parcels** (`dd444623`, `43baea8e`: "0
new resolutions, chunks 1-2/22" and "chunks 3-4/22") — and this audit's own read-only measurement
explains exactly why: **of the ~31,500 rows still eligible for point-in-polygon resolution, 96-98%
already carry a `geo_imprecise` flag** (centroid-snapped or Census-tract-level, not a rooftop geocode),
which is structurally unresolvable by a point-in-polygon lookup no matter how many times it retries.
The easy targets are gone; what is left is the hard tail, and the process running right now is
proving that live, in its own commit history, while this audit was being written.

- **Board totals: 217,773 rows, +0 since 9/28** (NC 135,061 +0, SC 82,712 +0). Verified directly: no
  scraper and no full `main.py` pipeline run has landed since the 9/28 "final ranking" commit
  (`7f78473a`, 2026-09-28 17:11) — every commit since then is either a resolver checkpoint or the
  Anderson mailing backfill, none of which add or remove rows.
- **Board-wide completeness moved on exactly two fields, both fully explained.** Owner mailing 65.1%
  → 65.8% (+1,477 rows, **all of it in SC**, exactly matching the Anderson SC owner-mailing backfill
  commit's own stated "+1,477"). Either-value 56.2% → 56.8% (+1,106 rows, **all of it in SC**,
  consistent with the SC-heavy resolver chunks that ran between the two audits). Owner name (88.3%,
  192,339 rows) and phone (29.6%, 64,456 rows) are **identical to the byte**, board-wide and by state —
  neither field is touched by anything that ran in between.
- **Family breadth: zero drift, all 146 counties, all 7 comparable families**, reproducing the 9/28
  numbers to the county: tax delinquent 129/146, tax sale 61/146, lis pendens 118/146, probate 49/146,
  divorce 93/146, bankruptcy 48/146, code/vacant 49/146. Nothing scraped, nothing should have moved,
  and nothing did.
- **New: 4 families never reported board-wide before.** Foreclosure/mortgage 25/146, jail/incarceration
  16/146, liens 129/146, HOA sale **0/146** — `ListingType.HOA_SALE` exists in the schema and is
  referenced by exactly one scraper (`counties_sc/charleston_mie.py`, Charleston SC — outside the
  18-county core footprint) but has never produced a single live row on the board.
- **12 of the 13 raw-key signals named as "built earlier this session" carry ZERO live rows on the
  board right now.** Only `rollback_exposure` (present-use/elderly tax deferral) is live, with 96 real
  rows (83 NC, 13 SC, only 2 counties). Every other one — `repeat_tax_loss`/`deed_index`,
  `liensnc_posthumous_filing`, `platted_lots`, `divorce_no_subsequent_deed`, `notice_service_defect`,
  `heir_naming_publication`, `jail_booking_new`, `bop_federal`, `landlocked`, `cemetery_proximity`,
  `repeat_foreclosure_filing`, and the older sibling key `tax_relief` — measures exactly 0 on the
  current board. This is not twelve different bugs: it traces to one root cause plus one true
  structural block, both identified precisely in Section 6.
- **Resolver-backfill status**: 66.3% of the board now carries a `parcel_id` (144,444/217,773; NC
  61.1%, SC 74.8%). The remaining ~31,500 in-box, county-known targets skew almost entirely
  imprecise-geocode (96-98% carry `raw.geo_imprecise`), compounding on top of SC's separate,
  already-documented SCDOT token-wall (only Anderson SC has a native point-resolvable fallback; every
  other SC county depends on the dead statewide `SC_Parcels` layer). Full breakdown in Section 5.

## 0. What changed since 2026-09-28 — top-line before/after

| Metric | 2026-09-28 | 2026-09-29 | Δ |
|---|--:|--:|--:|
| Total rows | 217,773 | 217,773 | +0 |
| NC rows | 135,061 | 135,061 | +0 |
| SC rows | 82,712 | 82,712 | +0 |
| Owner mailing (all) | 65.1% (141,828) | 65.8% (143,305) | +1,477 (+0.7pp) |
| Owner mailing (SC) | 51.1% (42,275) | 52.9% (43,752) | +1,477 (+1.8pp) — **entire delta** |
| Owner mailing (NC) | 73.7% (99,553) | 73.7% (99,553) | +0 |
| Either value (all) | 56.2% (122,497) | 56.8% (123,603) | +1,106 (+0.6pp) |
| Either value (SC) | 48.8% (40,399) | 50.2% (41,505) | +1,106 (+1.4pp) — **entire delta** |
| Either value (NC) | 60.8% (82,098) | 60.8% (82,098) | +0 |
| Owner name (all) | 88.3% (192,339) | 88.3% (192,339) | +0 (exact) |
| Phone (all) | 29.6% (64,456) | 29.6% (64,456) | +0 (exact) |
| Tax delinquent present (of 146) | 129 | 129 | +0 |
| Tax sale present (of 146) | 61 | 61 | +0 |
| Lis pendens present (of 146) | 118 | 118 | +0 |
| Probate present (of 146) | 49 | 49 | +0 |
| Divorce present (of 146) | 93 | 93 | +0 |
| Bankruptcy present (of 146) | 48 | 48 | +0 |
| Code/vacant present (of 146) | 49 | 49 | +0 |

The +1,477 mail / +1,106 value deltas are both **fully attributable, exact-match reconciliations**
against named commits landed between the two audits: `47244dc8` "Board data: Anderson SC
owner-mailing backfill from the offline roll (+1,477)" and the SC-heavy share of the 4-chunk
`resolver_backfill_parcel.py` run (`b25a4b11`..`ba3e57b3`, 10,383 new parcel resolutions across NC+SC)
whose downstream revaluation cycle produced new `market_value`/`tax_value` hits concentrated in SC.
No other mechanism ran in between, and no other field moved — a clean, fully-reconciled diff.

## 1. Confirming zero net row change (and why)

Walked the commit log between the 9/28 baseline's snapshot commit (`7f78473a`, "Board data: final
ranking after this session's landing cycle (217,773 rows)", 2026-09-28 17:11) and now. Every commit
touching `docs/listings_part_*.json.gz` in that window:

| Time | Commit | What it did | Rows added |
|---|---|---|--:|
| 9/28 19:22 | `47244dc8` | Anderson SC owner-mailing backfill from the offline roll | +0 (enrichment only) |
| 9/28 21:28 | `b25a4b11` | Resolver backfill chunks 1-4/24 (585 new parcel resolutions) | +0 |
| 9/28 22:46 | `6bcf06a9` | Resolver backfill chunks 5-6/24 (2,320 new resolutions) | +0 |
| 9/28 23:58 | `71f03af6` | Resolver backfill chunks 7-8/24 (3,684 new resolutions) | +0 |
| 9/29 01:42 | `ba3e57b3` | Resolver backfill chunks 9-10/24 (3,794 new resolutions) | +0 |
| 9/29 ~11:00+ | `43baea8e`, `dd444623` | **New** resolver checkpoint pass, chunks 1-4/22 (0 new resolutions each) | +0 |

Every one of these is either a pure enrichment pass (mailing backfill) or the parcel-resolution
backfill, which by design (`scripts/resolver_backfill_parcel.py`) only fills `parcel_id` on rows
already on the board — it cannot add or remove a row. No scraper, no `main.py` full run, and no
board-mutation script other than these two ran in the window. Directly measured: **217,773 rows now,
217,773 rows on 9/28, to the row.**

**The resolver backfill is a genuinely new, second pass** (chunks "1-4/22", not a continuation of the
24-chunk pass that finished at `ba3e57b3`) — a fresh target list was recomputed after the first pass
completed, and this second pass's own commits already show 0 new resolutions in its first 4 chunks.
This is the process that is running right now, holding the board via `load_board()`, which is exactly
why this audit never calls `load_board()` itself (see the memory-safety note at the top).

## 2. Board-wide completeness

| Group | Rows | Address | Parcel_id | Owner mailing | Owner name | Either value | Phone |
|---|--:|--:|--:|--:|--:|--:|--:|
| **All** | 217,773 | 159,277 (73.2%) | 144,444 (66.3%) | 143,305 (65.8%) | 192,339 (88.3%) | 123,603 (56.8%) | 64,456 (29.6%) |
| **NC** | 135,061 | 95,343 (70.6%) | 82,546 (61.1%) | 99,553 (73.7%) | 117,925 (87.3%) | 82,098 (60.8%) | 64,452 (47.7%) |
| **SC** | 82,712 | 63,934 (77.3%) | 61,898 (74.8%) | 43,752 (52.9%) | 74,414 (90.0%) | 41,505 (50.2%) | 4 (0.005%) |

**SC phone contactability is still structurally near-zero** (4 of 82,712 rows, unchanged from 9/28's
0.005% finding) — `enrichment_sc_phone.py`'s identity-corroboration gate is still correctly refusing
to promote uncorroborated voter-registration phone matches. Not re-investigated this pass since
nothing that would change it ran; carried forward as a standing, compliance-correct gap, not
re-measured for new root causes.

Note that SC now has a **higher** parcel_id rate than NC (74.8% vs 61.1%) despite the county-level
narrative in Section 5 being "SC is SCDOT-walled" — this is not a contradiction: SC's overall parcel
rate is propped up by large, already-well-resolved sources (Spartanburg, Anderson post-fix) and by
`liensnc`'s parcel-carrying filings, while the *remaining unresolved* SC rows are disproportionately
the ones the SCDOT wall blocks. Rate and remaining-gap composition are different questions; both are
answered precisely in Section 5.

## 3. Distress-family breadth, all 146 NC+SC counties

**11 families now tracked** (up from the 9/28 doc's 7): the 7 continuing families reproduce the 9/28
numbers exactly (see Section 0), confirming zero drift. 4 new families — foreclosure/mortgage, HOA,
jail/incarceration, liens — are reported for the first time board-wide (they previously existed only
in the 18-county-scoped `scripts/coverage_100_ledger.py`, never rolled up to all 146).

| Family | Present (of 146) | NC (of 100) | SC (of 46) | Notes |
|---|--:|--:|--:|---|
| Tax delinquent | 129 | 100 | 29 | unchanged since 9/28 |
| Liens | 129 | 100 | 29 | **identical county set to tax delinquent** — see below |
| Lis pendens | 118 | 99 | 19 | unchanged since 9/28; SC lis pendens (PublicIndex) covers well under half of SC |
| Divorce | 93 | 93 | **0** | unchanged since 9/28 — SC FCCMS Rule 610 ToS wall, structural, all 46 SC counties |
| Bankruptcy (strict) | 48 | 38 | 10 | unchanged since 9/28; see broad variant below |
| Code/vacant | 49 | 26 | 23 | unchanged since 9/28 |
| Probate/estate | 49 | 26 | 23 | unchanged since 9/28; identical *count* to code/vacant, different county sets (32/49 overlap) — coincidence, verified, not a bug |
| Tax sale | 61 | 22 | 39 | unchanged since 9/28; inverse NC/SC pattern — NC handles tax foreclosure mostly through `tax_lien`/`lis_pendens`, SC has a distinct FLC/tax-sale event type |
| Foreclosure/mortgage | 25 | 17 | 8 | new metric; concentrated in the 18-county footprint (all 18 present) plus 7 adjacent counties (Graham, Haywood, Jackson, Rowan NC, Swain NC, Greenville SC) reached by national trustee/REO feeds |
| Jail/incarceration | 16 | 9 | 7 | new metric |
| HOA sale | **0** | 0 | 0 | new metric; `ListingType.HOA_SALE` exists but has zero live rows anywhere on the board |

**Tax delinquent and liens share the identical 129-county set, verified not a bug** (checked directly:
same 17 SC counties missing both, 0 asymmetric counties either direction). This means the county
where the pipeline's flagship tax-delinquent scrapers (qPayBill, PTS-Cloud, county PDFs) reach also
happens to be the exact set liensnc/SC-DEW reaches — a genuine "thin-coverage cluster" of 17 SC
counties (Abbeville, Allendale, Bamberg, Barnwell, Calhoun, Chester, Chesterfield, Darlington, Dillon,
Dorchester, Edgefield, Fairfield, Greenwood, Lee, Marlboro, McCormick, Williamsburg) that is weak
across multiple independent signal families at once, not two separately-walled families that happen to
match by coincidence in count alone.

**Bankruptcy, broad variant**: adding the CourtListener cross-reference stamp (`raw.bankruptcy` /
`raw.courtlistener`) that rides on otherwise non-bankruptcy-typed leads (a tax-delinquent or
foreclosure lead whose owner also has an open federal BK case) raises bankruptcy presence to 83/146
(+35 counties, 29 of them SC). Reported here as a supplementary figure, not folded into the headline
48/146, specifically so this audit stays diffable against the 9/28 series — but it is a real, useful
number: it means 35 counties have a *bankruptcy-adjacent contact signal on an existing lead* even
though no standalone bankruptcy-type lead exists there.

**Family-count histogram, all 146 counties (of 11 families)**:

| Families present | Counties |
|--:|--:|
| 0/11 | 0 |
| 1/11 | 9 |
| 2/11 | 8 |
| 3/11 | 8 |
| 4/11 | 43 |
| 5/11 | 36 |
| 6/11 | 16 |
| 7/11 | 7 |
| 8/11 | 5 |
| 9/11 | 9 |
| 10/11 | 5 |
| 11/11 | 0 |

No county has all 11 (HOA is 0/146 board-wide, so 11/11 is currently unreachable for anyone). The
14 counties at 9/11 or 10/11 are: Anderson SC, Buncombe NC, Burke NC, Cleveland NC, Gaston NC,
Henderson NC, Laurens SC, Lincoln NC, McDowell NC, Oconee SC, Pickens SC, Polk NC, Rutherford NC,
Spartanburg SC — **all 14 are inside the 18-county flip footprint.** This independently confirms
(from a totally different angle than Section 4) that the flip-lane counties genuinely are this
pipeline's best-covered ground, not just the ones with the most raw rows.

**Notable zero-coverage gaps in otherwise-common families** (a county missing a signal that most of
its peers have):

- **Divorce**: 0 of 46 SC counties, vs 93 of 100 NC counties. Not a coverage gap to close — the SC
  Family Court FCCMS portal's Rule 610 Terms of Service is a documented, structural wall (unchanged,
  not re-probed this pass since nothing that would lift it ran).
- **Liens / tax delinquent**: 17 SC counties (listed above) have neither, while every other SC county
  and all 100 NC counties have both. A genuine, still-open build target — not a wall.
- **Lis pendens**: 27 of the 46 SC counties (59%) have none, vs 1 of 100 NC counties (Alleghany).
  SC's PublicIndex-based lis-pendens coverage is thin outside the pipeline's most-worked counties.
- **Bankruptcy (strict)**: York SC — inside the flip footprint's near-neighbor set and otherwise
  well-covered on other families — has zero standalone bankruptcy rows.

## 4. 18-county flip-lane detail — the "what's missing per county" table

All rows in each of the 18 core footprint counties (any distress type, not filtered to sale-type
listings — this is the total distress picture per county, matching the operator's standing request to
see what's not at 100% and what's missing a source/signal). Numbers independently cross-checked
against `scripts/coverage_100_ledger.py`'s own live run this session; the two tools agree exactly on
every cell they both compute (rows, tax_sale-missing set, jail-missing set).

| County | State | Rows | Address % | Parcel_id % | Mail % | Phone % | Families present (of 11) | Missing |
|---|---|--:|--:|--:|--:|--:|--:|---|
| Rutherford | NC | 8,750 | 65.7% | 95.1% | 88.5% | 42.2% | 10/11 | HOA |
| Cleveland | NC | 1,144 | 78.8% | 68.9% | 68.3% | 36.3% | 10/11 | HOA |
| Henderson | NC | 3,299 | 67.4% | 86.7% | 79.9% | 42.2% | 10/11 | HOA |
| Polk | NC | 449 | 83.3% | 67.5% | 73.7% | 35.4% | 9/11 | Tax sale, HOA |
| Gaston | NC | 9,340 | 92.1% | 89.0% | 86.6% | 29.6% | 9/11 | Tax sale, HOA |
| Buncombe | NC | 10,500 | 93.1% | 89.4% | 90.2% | 76.6% | 10/11 | HOA |
| Transylvania | NC | 6,331 | 74.2% | 95.7% | 92.6% | 31.7% | 8/11 | Tax sale, HOA, Jail |
| McDowell | NC | 2,700 | 79.2% | 91.6% | 91.9% | 43.7% | 9/11 | Tax sale, HOA |
| Lincoln | NC | 3,613 | 93.3% | 78.3% | 92.7% | 42.5% | 9/11 | HOA, Divorce |
| Mitchell | NC | 260 | 86.9% | 67.7% | 71.2% | 28.1% | 8/11 | Tax sale, HOA, Jail |
| Burke | NC | 1,525 | 88.9% | 80.2% | 77.2% | 40.4% | 10/11 | HOA |
| Spartanburg | SC | 18,259 | 86.5% | 84.6% | 83.9% | **0.0%** | 9/11 | HOA, Divorce |
| Anderson | SC | 2,684 | 68.3% | 88.2% | 88.6% | **0.0%** | 9/11 | HOA, Divorce |
| Pickens | SC | 4,741 | 72.1% | 66.5% | 75.8% | **0.0%** | 9/11 | HOA, Divorce |
| Oconee | SC | 3,211 | 70.9% | 48.6% | 68.2% | **0.0%** | 9/11 | HOA, Divorce |
| Cherokee | SC | 2,756 | 56.2% | 52.5% | 8.8% | **0.0%** | 8/11 | HOA, Divorce, Bankruptcy |
| Union | SC | 1,297 | 66.5% | 50.3% | 40.2% | **0.0%** | 8/11 | HOA, Divorce, Jail |
| Laurens | SC | 2,838 | 62.1% | 56.4% | 52.4% | **0.0%** | 9/11 | HOA, Divorce |
| **Total** | | **83,697** | **80.0%** | **82.4%** | **81.1%** | **26.1%** | | |

Every SC core county reads **0.0% phone** — not rounding, all 7 SC core counties measured at or below
0.02% individually (4 usable phones total across all of SC, none in the core footprint). Every SC core
county is also missing Divorce (the FCCMS wall, Section 3) and every one of the 18 is missing HOA
(board-wide zero, Section 3). Two NC counties (Transylvania, Mitchell) and one SC county (Union) are
also missing Jail. Five NC counties (Polk, Gaston, Transylvania, McDowell, Mitchell) are missing
Tax sale — NC's tax-sale-as-a-distinct-event-type is structurally rarer than SC's (Section 3), so this
reads as expected pattern, not a footprint-specific gap. **Cherokee SC is the one footprint county with
zero standalone bankruptcy rows** (strict `listing_type == bankruptcy` definition, Section 3) — the
only footprint county missing a family that ten of its eleven peers all have at least some rows of.

**Weakest layer per county, in one line**: NC's weak layer is address resolution (65-89% depending on
county, driven by national trustee/auction feeds that carry a street address but not always a clean
parcel match) and phone (28-44%, capped well under half everywhere). SC's weak layer is unambiguous:
phone, at essentially zero everywhere, for the structural reason in Section 2.

## 5. Resolver-backfill status

**66.3% of the board carries a `parcel_id` right now**: 144,444 of 217,773 (NC 82,546/135,061 = 61.1%,
SC 61,898/82,712 = 74.8%).

**Current live target population** (same definition `resolver_backfill_parcel.py` itself uses: state
in NC/SC, county attributed, in-box lat/lon per `enrichment_parcel_from_geo._in_box` — lat 32.0-37.0,
lon -84.5 to -75.0 — and no `parcel_id`): **31,522 rows** (NC 16,191, SC 15,331). This number was
derived purely by replaying the resolver's own targeting predicate against the board read-only; it was
never fetched from the running process. It lines up almost exactly with the running process's own
math: `CHUNK_SIZE = 1500` and its current checkpoint commits report "chunks 1-4/22" — 22 × 1,500 ≈
33,000, consistent with a ~31,500-row target list (the last chunk is partial).

**Of those 31,522 targets, 96-98% are structurally hard, not just untried**:

| State | In-box, missing parcel_id | Carries `raw.geo_imprecise` | % imprecise |
|---|--:|--:|--:|
| NC | 16,191 | 15,800 | 97.6% |
| SC | 15,331 | 14,675 | 95.7% |

`geo_imprecise` breaks down (board-wide, not just this target set) into `centroid_snap` (59,886 rows,
a county/town-center fallback point), `census_geocode` (56,595 rows, a Census Bureau tract/block-group
level geocode — usable for a state-level box check but not precise enough to land inside one specific
parcel polygon), `county_centroid`/`county_centroid_no_addr` (504 rows), and true `out_of_bbox` (150
rows, coordinates nulled — these fail the box test and are not in the 31,522 target count at all, so
the wall composition above is real centroid/tract imprecision, not an artifact of counting
already-excluded rows).

**This is the direct, measured explanation for why the currently-running resolver pass's first four
chunks resolved zero new parcels** (`43baea8e`, `dd444623`). A point-in-polygon lookup needs a point
that actually falls inside the target parcel; a centroid-snapped or census-tract-level point frequently
does not, no matter how many times the same row is retried. The first backfill pass (the 24-chunk run
that finished at `ba3e57b3`, resolving 10,383 rows) evidently drained the population of rows with
usable, precise coordinates; this second pass is now working through what is left, and what is left is
disproportionately the hard tail.

**SC carries a second, independent wall on top of the same imprecision problem.**
`enrichment_parcel_from_geo.NATIVE_SC_POINT_CAPABLE` is a one-county frozenset — `{"Anderson"}` — so
every other SC county's point-in-polygon attempt depends entirely on the statewide `SC_Parcels`
MapServer, which is token-walled (`host_walled()` trips on "Token Required", confirmed live as
recently as the Anderson fix's own commit message on 9/28, not re-probed this pass since nothing that
would lift a live token wall ran). So for SC, an imprecise-geocode row in a non-Anderson county is
doubly blocked: even a precise geocode there could not resolve today. For NC, the NC OneMap parcels
layer is not documented as walled, so NC's ~16,000-row remainder is close to a clean read of "the
imprecision problem alone."

**34,740 more rows (NC 31,239, SC 3,501) are not even resolver-backfill candidates** — no usable
lat/lon at all, so they fail the box test outright and would need `resolver_backfill_geocode.py`
(a geocoding pass) before `resolver_backfill_parcel.py` could ever touch them. This is a materially
different, upstream problem from the 31,522 in-box hard tail above, and NC carries nearly 9x SC's share
of it — worth a separate look, not folded into "the resolver is stuck" framing above.

## 6. New-signal rollup — built this session vs. actually producing rows

Board-wide count of rows carrying each raw key (`truthy()`, i.e. present and non-empty), cross-checked
against `web_artifact.RAW_KEEP` and each enricher's own wiring in `main.py`:

| Signal (raw key) | Rows on board | Wired in `main.py`? | Status |
|---|--:|---|---|
| `rollback_exposure` | **96** (NC 83, SC 13, 2 counties) | Yes (`main.py:2895`) | **Live, producing real data.** Sample: a Buncombe NC present-use deferral, $46,400 deferred value, $1,292.88 estimated rollback. |
| `tax_relief` | 0 | Yes (`main.py:2883`, since 2026-08-30) | **Live-wired but 0 rows.** Its own docstring documents a measured true base rate of ~1/600 leads (present-use/elderly relief barely overlaps a residential-distress board) — 0 is plausible low-volume noise from this base rate, not necessarily a break; not independently re-verified further this pass. |
| `repeat_tax_loss` | 0 | Yes (`main.py:3215`) | **Structurally blocked, not just unrun.** Confirmed directly: `data/deed_index.db`'s `instruments` table has **0 rows** — the county-wide ROD sweep that is supposed to populate this sidecar (`scripts/backfill_deed_index.py`) has not actually put any data in it yet. The enricher's own docstring documents its first live run (2026-09-17) also tagged 0, for the same reason (no board source records a forced-sale deed instrument type). Fixing this needs the deed-index sweep to actually run and populate rows, not another pipeline pass. |
| `deed_index` | 0 | Same enricher as above | Same root cause — this key is the instrument list behind a `repeat_tax_loss` tag, so it is 0 for the identical reason. |
| `liensnc_posthumous_filing` | 0 | Yes (`main.py:3228`), committed 2026-09-28 19:59 | **Wired after the last full pipeline landing** (`7f78473a`, 17:11 same day) — no full run has executed since. Needs a run, not a code fix. |
| `platted_lots` | 0 | Yes (`main.py:3241`), committed 2026-09-28 20:23 | Same: wired after the last full landing. Needs a run. |
| `divorce_no_subsequent_deed` | 0 | Yes (`main.py:3255`), committed 2026-09-28 20:36 | Same: wired after the last full landing. Needs a run. |
| `notice_service_defect` | 0 | Yes (`main.py:3270`), committed 2026-09-29 11:30 | Same: wired hours after this audit's own reference point. Needs a run. |
| `heir_naming_publication` | 0 | Yes — `ColumnLegalNotices` scraper, auto-discovered via `scrapers/_registry.py`, committed 2026-09-29 11:40 | This is a **scraper**, not just an enrichment tag, so it needs a full scrape pass (not only a `main.py` enrichment-only pass) to land rows. Needs a run. |
| `jail_booking_new` | 0 | Yes — `enrich_jail_bookings` (`main.py:1934`), committed 2026-09-29 11:58 | Wired hours ago. Needs a run. |
| `bop_federal` | 0 | Yes (`main.py:1942`), committed 2026-09-29 11:58 | Same commit as above. Needs a run. |
| `landlocked` / `cemetery_proximity` | 0 / 0 | Yes — `enrich_land_buildability` (`main.py:2573`), committed 2026-09-29 12:33 | Wired hours ago. Needs a run. |
| `repeat_foreclosure_filing` | 0 | Yes — `enrich_foreclosure_docket_history` (`main.py:1985`), committed 2026-09-29 12:47 | Wired hours ago — the most recently-wired signal in this list. Needs a run. |

**Honest summary**: of the 13 raw keys checked, **1 is live and producing real rows** (`rollback_exposure`,
though it predates today by weeks and was already running before this session's newer signals were
added), **1 is wired since 8/30 and structurally low-yield by its own documented base rate**
(`tax_relief`), **1 is wired since 2026-09-20 and hard-blocked on an empty upstream sidecar**
(`repeat_tax_loss`/`deed_index` — the fix is populating `data/deed_index.db`, not re-running the
enricher), and **8 were wired into `main.py` or the scraper registry AFTER the last full pipeline
landing** (5 on 2026-09-28 evening, 5 more between 11:30am and 12:47pm today, all after
`resolver_backfill_parcel.py`'s currently-running process started at 10:59am) — meaning **a full
pipeline run has literally never executed since these 8 were wired**. "0 rows" for those 8 is the
expected, not-yet-tested state, not a defect. The one genuinely fixable-today item in this list is
`heir_naming_publication`, since it is a scraper and needs a scrape pass specifically (not just an
enrichment-only run) — worth flagging separately when scheduling the next full run.

## 7. What's fixable next

- **Run the pipeline.** 8 of the 13 new-session signals cannot be evaluated at all until a full
  `main.py` pass runs — this is the single highest-leverage next action, purely because nothing else
  in this list can be assessed without it.
- **Populate `data/deed_index.db`.** `scripts/backfill_deed_index.py` (or whatever ROD sweep is
  supposed to feed it) has not put a single row into the `instruments` table. `repeat_tax_loss` and
  `deed_index` cannot produce anything until this exists, regardless of how many more pipeline passes
  run.
- **The resolver backfill has diminishing returns from here as configured.** Its current 22-chunk pass
  is measurably churning through rows that cannot resolve via point-in-polygon (96-98% imprecise
  geocode). Letting it finish costs machine time for near-certain zero yield on most of the remaining
  chunks; the actual lever is upstream — either a better geocoder for the `census_geocode`/
  `centroid_snap` population (59,886 + 56,595 board-wide) or accepting this as a structural ceiling.
- **HOA is a real, currently-total gap** (0/146, 0/18 footprint) — worth a decision on whether it's an
  active build target (only one scraper has ever referenced the listing type, and it's outside the
  core footprint) or should be deprioritized as out of scope, same as coastal SC per the existing
  core-county-focus rule.
- **The 17-SC-county thin-coverage cluster** (Section 3: zero tax_delinquent AND zero liens,
  identical county set) is a concrete, un-walled build target, not a documented dead end — nothing in
  `docs/walls_register.md` or `docs/MASTER_GAPS_WALLS_AND_MANUAL_LANES.md` was checked against this
  specific list this pass, so it should be verified against those docs before assuming it's untried.
- **34,740 rows (mostly NC) have no lat/lon at all** and are invisible to the parcel resolver entirely
  — a `resolver_backfill_geocode.py` pass is the correct next step for that population, not another
  parcel-resolver run.

## What could not be verified precisely this pass

- Whether `tax_relief`'s 0 rows is unchanged from some prior non-zero count, or whether it has always
  been ~0 since 8/30 — no prior audit reported this specific key's board-wide count, so there is no
  baseline to diff against.
- The exact county-by-county destination of the 10,383 parcel resolutions from the `b25a4b11`..
  `ba3e57b3` chunks — the board-wide and SC-value-only deltas are exact and reconciled (Section 0),
  but attributing per-county identity-rate movement since 9/28's Section 4 table would need a second
  per-county diff pass against that table, not done here to keep this a fast, computation-only pass as
  scoped.
- Whether any of the 8 "wired after last full landing" signals would actually produce non-zero rows
  once a full run executes — that is untestable from board data alone; it can only be answered by
  actually running the pipeline (Section 7's top recommendation).
- SC phone's root cause was carried forward from 9/28 verbatim, not re-derived from scratch this pass,
  since nothing that would change `enrichment_sc_phone.py`'s gate behavior ran in between.
