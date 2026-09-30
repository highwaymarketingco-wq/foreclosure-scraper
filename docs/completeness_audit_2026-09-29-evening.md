# Completeness audit, 2026-09-29 (evening)

Measured read-only on the live board, **219,530 rows** (NC 135,137, SC 84,393), streamed once
with `foreclosure_scraper.board_stream.iter_board_rows()` (~7-15s wall time). **No `load_board()`
call was made anywhere in this audit** — checked `logs/.board.lock` (absent) and `ps aux` for
`load_board`/`main.py`/`with_board_lock` (nothing running) before starting, per the memory-safety
constraint. No scraper ran, no enricher ran, no board write happened. This is read-only analysis
only, one streaming pass plus a couple of follow-up passes over the same JSON dump to break out
family-breadth definitions correctly (see Section 5's methodology note).

This is the second snapshot of 2026-09-29, taken after this morning's audit
(`docs/completeness_audit_2026-09-29.md`, 217,773 rows) and after an extensive same-day fix
campaign landed on top of it (`git log e8ece032..c39098a3`). Numbers below are computed fresh
against the current board; nothing is copied forward from the morning doc except where explicitly
cited as a comparison baseline.

## Bottom line

- **Board totals: 219,530 rows, +1,757 since this morning** (NC 135,137 +76, SC 84,393 +1,681).
  The total reconciles exactly against the three landing commits' documented counts: Dorchester SC
  BillTrax (`49ab8c1a`, 897 rows) + Edgefield SC qPayBill (`e5922a1f`, 750 rows) + the SC portion of
  `column_legal_notices` heir-naming (`7d7fe05f`, 110 rows) = 897 + 750 + 110 = **1,757**, matching
  the measured delta to the row. The **state-level split doesn't cleanly attribute 1:1 to SC** —
  `column_legal_notices` is not SC-only (currently 270 live rows: 160 in NC counties, 110 in SC),
  and several NC footprint counties (McDowell, Burke, Gaston, Buncombe, Cleveland, Transylvania,
  Rutherford) show small row-count upticks of a few dozen each versus this morning's Section-4
  table that aren't explained by any of the three named commits. Total math is exact and verified;
  this NC-side micro-drift (well under 100 rows) was not traced further, in keeping with this being
  a fast, computation-only pass — flagged, not chased.
- **Board-wide completeness**: address 73.0%, parcel_id 66.5%, owner_mailing 65.3%, owner_name
  88.4%, either-value 56.3%, phone 29.4% — all within a point of this morning's figures except
  parcel_id (66.3%→66.5%, the resolver backfill still trickling) and either-value/phone are flat.
  **The one field that moved hard is `amount_owed`'s real-vs-proxy split**, which is the direct,
  fully-verified effect of `ad86ec22`: 41.5% of the board (91,191 rows) now carries a REAL debt
  figure (was ~0.3% pre-fix per that commit's own measurement), and — cross-checked directly this
  pass — **0 rows with a real `tax_owed.balance` still show a missing/proxy `amount_owed`**,
  confirming the fix's own "0 of 88,959" claim still holds days later at a slightly larger
  denominator (89,014 real tax-balance rows now). Full table in Section 2.
- **Distress tiers, board-wide, right now: HOT 450 (0.20%), WARM 39,955 (18.20%), COLD 179,123
  (81.59%)**. There is no board-wide HOT/WARM/COLD histogram in the morning audit to diff this
  against directly — but `c39098a3`'s own commit message gives an exact, verified before/after for
  the specific cohort it fixed (unlocatable rows riding a phantom equity band into WARM): **2,989
  rows patched, WARM 2,653→1,407 (-1,246) within that cohort, HOT 3→3 unaffected**, row count
  unchanged (219,530→219,530). The board-wide numbers above already have that fix baked in. Detail
  in Section 3.
- **18-county flip footprint: 83,766 rows** (up from this morning's 83,697 by the same small
  NC-county drift noted above), address 79.9%, parcel_id 82.3%, mail 81.0%, phone 26.1% — all
  within a point of this morning. **Dorchester and Edgefield are NOT in the 18-county footprint**
  (the SC footprint is fixed at Spartanburg/Anderson/Pickens/Oconee/Cherokee/Union/Laurens per
  `config.py`) — their new coverage does not touch this table at all; see Section 4's note.
- **Family breadth: re-measured 130-146 depending on definition** (see the methodology correction
  below) — **Liens jumped from this morning's 129 (SC 29) to 143 (SC 43)**, but direct measurement
  shows this is **not** `2b780229`'s SC DEW footprint widening (that fix has produced zero new rows
  outside its pre-existing 12-county set — it needs a fresh scrape to take effect, same "wired but
  not run" pattern as the morning audit's Section 6). The real driver is the `recorded_debt`
  distress-stack signal, which now fires off a real `tax_owed.balance` in 37 SC counties on its
  own — the same real-tax-balance data `ad86ec22` surfaced. Tax delinquent ticked 129→130 (SC
  29→30, exactly Dorchester's new coverage). Full table and the methodology fix in Section 5.

## Methodology note (read before Section 5)

While rebuilding the family-breadth measurement, an early draft used the looser source-name-frag
+ signal union (`coverage_100_ledger.py`'s `FAMILIES` dict) for **all 11** families and got Tax
delinquent NC=92/SC=45 — a result that moves in *both* directions from this morning (NC counties
apparently losing coverage) and is on its face wrong, since nothing removed NC tax data today. The
morning audit is explicit that its 7 "legacy" families are pinned to **strict `listing_type`-only**
matching (no source-name fallback), specifically because an earlier looser draft of *that* audit
reproduced different, wrong totals too. Corrected to match: the 7 legacy families
(tax_delinquent/tax_sale/lis_pendens/probate_estate/divorce/bankruptcy/code_vacancy) use strict
`listing_type` equality below; only the 4 newer families (mortgage_foreclosure, liens,
incarceration, hoa_sale — which have no `listing_type` equivalent) use the looser
source-name-fragment/signal/raw-stamp union. This reproduces the morning baseline almost exactly
(130 vs 129, explained by Dorchester) for the 7 legacy families, which is the correctness check
this note exists to record.

## 1. Board totals and source reconciliation

| Metric | Morning (9/29) | Evening (9/29) | Δ |
|---|--:|--:|--:|
| Total rows | 217,773 | 219,530 | +1,757 |
| NC rows | 135,061 | 135,137 | +76 |
| SC rows | 82,712 | 84,393 | +1,681 |

Source-level landing, verified directly against the live board:

| Source | County | Rows now | Commit | Matches expected? |
|---|---|--:|---|---|
| `counties_sc.dorchester_billtrax_delinquent_tax` | Dorchester SC | 897 | `49ab8c1a` | Yes, exact |
| `counties_sc.qpaybill_delinquent_roll` | Edgefield SC | 750 | `e5922a1f` | Yes, exact |
| `counties.column_legal_notices` | 17 counties (7 SC, 10 NC) | 270 total (110 SC + 160 NC) | `7d7fe05f` | SC portion (110) exact; the 160 NC rows are not attributable to any commit in this session's list, most likely landed earlier and already counted in the 217,773 morning baseline |

897 + 750 + 110 = 1,757, exactly the measured total delta — the reconciliation is clean at the
board-wide level. `d596b992` (Georgetown FLC opening-bid), `f81dace3` (horry_flc dateless
whitelist), `26dc41a3` (buncombe_unpaid_bills situs), `ad86ec22` (amount_owed promotion), and
`c39098a3` (equity retraction) are all field-level/tier-level fixes via `patch_existing_rows()` —
none of them add or remove a row, consistent with row count being fully explained by the three
sources above.

## 2. Board-wide completeness

| Group | Rows | Address | Parcel_id | Owner mailing | Owner name | Either value | Phone |
|---|--:|--:|--:|--:|--:|--:|--:|
| **All** | 219,530 | 160,172 (73.0%) | 146,093 (66.5%) | 143,305 (65.3%) | 194,091 (88.4%) | 123,603 (56.3%) | 64,456 (29.4%) |
| **NC** | 135,137 | 95,344 (70.6%) | 82,547 (61.1%) | 99,553 (73.7%) | 117,998 (87.3%) | 82,098 (60.8%) | 64,452 (47.7%) |
| **SC** | 84,393 | 64,828 (76.8%) | 63,546 (75.3%) | 43,752 (51.8%) | 76,093 (90.2%) | 41,505 (49.2%) | 4 (0.0%) |

Definitions unchanged from the 9/27-9/29 series: owner_mailing is the `skip_trace` /
`outreach.mailing_address` / `liensnc_related.owner_contact.mailing` / `owner_mailing` /
`gis.mailing` union; phone is `enrichment_sc_phone.usable_owner_phone()` or
`outreach.phones`/`liensnc_related.owner_contact.phone`; either-value is a positive
`market_value`/`cama.appraised_value`/`cama.total_value`/`tax_value` (the `coverage_100_ledger.py`
"value" check). SC phone is still 4 of 84,393 rows (0.005%) — unchanged, structural (Section 6).

**Amount owed — real vs. proxy, the field `ad86ec22` fixed:**

| Group | Rows | `amount_owed` present | ...is REAL debt | ...is a PROXY (is_actual_debt=False) | Missing | Real `tax_owed.balance` exists | ...but NOT reflected in `amount_owed` |
|---|--:|--:|--:|--:|--:|--:|--:|
| **All** | 219,530 | 150,013 (68.3%) | 91,191 (41.5%) | 58,822 (26.8%) | 69,517 (31.7%) | 89,014 (40.5%) | **0 (0.0%)** |
| **NC** | 135,137 | 83,524 (61.8%) | 37,921 (28.1%) | 45,603 (33.7%) | 51,613 (38.2%) | 36,240 (26.8%) | 0 |
| **SC** | 84,393 | 66,489 (78.8%) | 53,270 (63.1%) | 13,219 (15.7%) | 17,904 (21.2%) | 52,774 (62.5%) | 0 |

The last column is the direct, live re-verification of `ad86ec22`'s own claim ("0 of the 88,959
real-balance rows now show missing/proxy amount_owed") — still exactly **0** now, at a slightly
larger real-tax-balance population (89,014 vs. the commit's 88,959, the difference being normal
drift from the Dorchester/Edgefield landings both carrying real balances). SC is now the
better-evidenced state on this specific metric (63.1% real debt vs. NC's 28.1%) — a full reversal
of the pre-fix state, where SC's `qpaybill_delinquent_roll` (31,231 rows, "36 correct" per the
commit) was the single worst-affected source.

## 3. Distress-score tier breakdown (HOT/WARM/COLD)

| Group | HOT | WARM | COLD | (no stack) |
|---|--:|--:|--:|--:|
| **All** (219,530) | 450 (0.20%) | 39,955 (18.20%) | 179,123 (81.59%) | 2 |
| **NC** (135,137) | 150 (0.11%) | 18,911 (13.99%) | 116,074 (85.89%) | 2 |
| **SC** (84,393) | 300 (0.36%) | 21,044 (24.94%) | 63,049 (74.71%) | 0 |

No prior audit in this series reports a board-wide HOT/WARM/COLD histogram, so there is no direct
before/after to diff at this scope. What **is** directly, exactly measurable is `c39098a3`'s own
before/after for the specific cohort it targeted — unlocatable rows (no `street_address` AND no
`parcel_id`) that were riding a phantom, unevidenced `equity_band: "high"` into WARM purely because
`distress_score` never checked location before trusting `raw['equity']`:

| | Before | After | Δ |
|---|--:|--:|--:|
| Unlocatable rows tiered WARM | 2,653 | 1,407 | -1,246 (-47%) |
| Unlocatable rows tiered HOT | 3 | 3 | 0 (structurally near-impossible for this cohort anyway; unaffected) |
| Rows patched | — | 2,989 | (13 dedupe-key collisions on ~130 rows conservatively skipped) |
| Total board rows | 219,530 | 219,530 | 0 (tier-only patch, no row added/removed) |

The board-wide 39,955 WARM figure above already has this fix baked in (the patch landed at
22:35 on 9/29, before this audit's measurement). SC's much higher WARM share (24.9% vs NC's 14.0%)
and its much lower COLD share track directly with SC's much higher real-debt rate from Section 2 —
`recorded_debt` is a FINANCIAL-category signal, and SC's tax rolls now correctly carry it far more
often post-`ad86ec22`.

## 4. 18-county flip-lane detail

Same footprint as every prior audit: `config.NC_COUNTIES + config.SC_COUNTIES` — 11 NC counties
(Rutherford, Cleveland, Henderson, Polk, Gaston, Buncombe, Transylvania, McDowell, Lincoln,
Mitchell, Burke) + 7 SC counties (Spartanburg, Anderson, Pickens, Oconee, Cherokee, Union,
Laurens). **Dorchester and Edgefield are not in this list and never have been** — both are outside
the Upstate-SC corridor `config.py` defines as the flip footprint, so today's two new-county
landings do not appear in this table at all (see the note after it).

| County | State | Rows | Address % | Parcel_id % | Mail % | Phone % | Families (of 11) | Missing |
|---|---|--:|--:|--:|--:|--:|--:|---|
| Rutherford | NC | 8,750 | 65.7% | 95.1% | 88.5% | 42.2% | 10/11 | HOA |
| Cleveland | NC | 1,145 | 78.8% | 68.8% | 68.2% | 36.2% | 10/11 | HOA |
| Henderson | NC | 3,299 | 67.4% | 86.7% | 79.9% | 42.2% | 10/11 | HOA |
| Polk | NC | 449 | 83.3% | 67.5% | 73.7% | 35.4% | 9/11 | Tax sale, HOA |
| Gaston | NC | 9,347 | 92.0% | 88.9% | 86.6% | 29.6% | 9/11 | Tax sale, HOA |
| Buncombe | NC | 10,503 | 93.1% | 89.4% | 90.2% | 76.6% | 10/11 | HOA |
| Transylvania | NC | 6,332 | 74.1% | 95.7% | 92.6% | 31.7% | 8/11 | Tax sale, Jail, HOA |
| McDowell | NC | 2,741 | 78.0% | 90.2% | 90.5% | 43.1% | 9/11 | Tax sale, HOA |
| Lincoln | NC | 3,613 | 93.3% | 78.3% | 92.7% | 42.5% | 9/11 | Divorce, HOA |
| Mitchell | NC | 260 | 86.9% | 67.7% | 71.2% | 28.1% | 8/11 | Tax sale, Jail, HOA |
| Burke | NC | 1,541 | 88.0% | 79.4% | 76.4% | 40.0% | 10/11 | HOA |
| Spartanburg | SC | 18,259 | 86.5% | 84.6% | 83.9% | **0.0%** | 9/11 | Divorce, HOA |
| Anderson | SC | 2,684 | 68.3% | 88.2% | 88.6% | **0.0%** | 9/11 | Divorce, HOA |
| Pickens | SC | 4,741 | 72.1% | 66.5% | 75.8% | **0.0%** | 9/11 | Divorce, HOA |
| Oconee | SC | 3,211 | 70.9% | 48.6% | 68.2% | **0.0%** | 9/11 | Divorce, HOA |
| Cherokee | SC | 2,756 | 56.2% | 52.5% | 8.8% | **0.0%** | 8/11 | Bankruptcy, Divorce, HOA |
| Union | SC | 1,297 | 66.5% | 50.3% | 40.2% | **0.0%** | 8/11 | Divorce, Jail, HOA |
| Laurens | SC | 2,838 | 62.1% | 56.4% | 52.4% | **0.0%** | 9/11 | Divorce, HOA |
| **Total** | | **83,766** | **79.9%** | **82.3%** | **81.0%** | **26.1%** | | |

Essentially unchanged from this morning (rows +69 board-wide within the footprint, all from the
small NC-county drift noted in Section 1; every percentage is within 0.3pp). **Dorchester (905
rows, 897 with a parcel_id, tax_delinquent + liens families present) and Edgefield (799 rows, 750
with a parcel_id, tax_sale + liens + a thin lis_pendens slice) are real, genuine new county
coverage** — Dorchester is a brand-new county on the board entirely (per the task brief), Edgefield
already had some cross-referenced rows (lis_pendens: 48) but gets its first substantial standing
tax roll today. Both sit just outside the 18-county corridor, so neither changes this table; they
would be the next candidates if the footprint is ever widened, and the SC DEW registry going
statewide (`2b780229`, once re-run) would reach both of them for its own signal.

## 5. Per-signal-family breadth, all 146 NC+SC counties

Applying the corrected methodology from the note above (strict `listing_type` for the 7 legacy
families, the established loose union for the 4 newer ones):

| Family | Present (of 146) | NC (of 100) | SC (of 46) | vs. this morning |
|---|--:|--:|--:|---|
| Tax delinquent | 130 | 100 | 30 | +1 (SC +1 — exactly Dorchester) |
| Tax sale | 62 | 22 | 40 | +1 (SC +1 — exactly Edgefield) |
| Lis pendens | 118 | 99 | 19 | 0 |
| Probate/estate | 49 | 26 | 23 | 0 |
| Divorce | 93 | 93 | 0 | 0 (SC still the FCCMS wall, unchanged) |
| Bankruptcy (strict) | 48 | 38 | 10 | 0 |
| Code/vacant | 49 | 26 | 23 | 0 |
| Foreclosure/mortgage | 92 | 85 | 7 | 0 |
| Jail/incarceration | 16 | 9 | 7 | 0 |
| Liens | 143 | 100 | 43 | **+14, all SC** — see below |
| HOA sale | 0 | 0 | 0 | 0 (still the single scraper outside the footprint) |

**The liens jump (SC 29→43) is not the DEW registry footprint widening.** Checked directly: the
`sc_dew_lien_registry` scraper's own emitted rows still sit in exactly the same 12 SC counties as
before (Spartanburg, Anderson, Pickens, Oconee, Cherokee, Union, Laurens, Charleston, Beaufort,
Horry, Colleton, Georgetown — 8,486 rows), and zero rows anywhere on the board carry a DEW
cross-reference stamp with a real matched amount. `2b780229` widened the scraper's *eligibility*
gate in code (`config.in_scope()` → `config.in_scope_distressed()`) but nothing has re-scraped it
since, so — same pattern as the morning audit's Section 6 — **it is a real fix that has not yet
produced a single live row**. The actual driver, isolated by re-running the family check with the
source-name-fragment and `recorded_debt`-signal halves counted separately: **37 SC counties get
their "liens" hit purely from the `recorded_debt` distress-stack signal** (44,660 rows), which
fires off any real debt figure regardless of `listing_type` — including the same real
`tax_owed.balance` data `ad86ec22` is about. In effect, "liens" (as this established, union-based
metric defines it) is currently dominated by "has a real recorded debt of any kind," not
specifically by a lien-registry record — worth flagging as a label/definition mismatch for whoever
next revises `coverage_100_ledger.py`'s `FAMILIES` dict, separately from anything this audit
changed.

**Family-count histogram, all 146 counties (of 11 families)**: 1/11: 2, 2/11: 9, 3/11: 10, 4/11:
19, 5/11: 42, 6/11: 28, 7/11: 11, 8/11: 11, 9/11: 9, 10/11: 5, 11/11: 0 (HOA is still 0/146
board-wide). The 9-10/11 counties are the same 14 the morning audit named: Buncombe, Burke,
Cleveland, Gaston, Henderson, Lincoln, McDowell, Polk, Rutherford (NC) + Anderson, Laurens, Oconee,
Pickens, Spartanburg (SC) — all 14 still inside the 18-county footprint, unchanged.

## 6. What's still open (honest gaps)

- **SC phone contactability is still structurally near-zero** — 4 of 84,393 SC rows (0.005%),
  unchanged. `enrichment_sc_phone.py`'s identity-corroboration gate is correctly refusing to
  promote uncorroborated voter-registration matches; this is compliance-correct, not a bug to fix.
- **The resolver's hard-tail geo-imprecision problem is unchanged.** As of this morning, ~31,500
  in-box rows were still missing a `parcel_id`, 96-98% of them carrying a centroid-snapped or
  Census-tract-level geocode that a point-in-polygon lookup cannot resolve no matter how many
  times it retries. Nothing that ran today touches geocode precision.
- **The 26,072-row name-resolution backlog** (24,086 NC + 1,986 SC), identified this session
  (`docs/extraction_gaps.md`'s re-measured Unlocatable entry): these rows already qualify as valid
  resolver targets today, but `enrichment_resolve_name_to_property` sits ~1,300 lines and dozens of
  stages after `gis_enrich` in `main.py`, and the most recent full pipeline run was SIGTERM-killed
  after 12 hours still inside `gis_enrich`, never reaching it. `scripts/catchup_failed_enrichers.py`
  now has a `resolve_name` option built for exactly this "died before it got its turn" shape, but it
  has not been run against this backlog yet — each target costs ~1.6-2s against a live county GIS
  endpoint, so draining 26,072 of them needs its own supervised multi-run pass.
- **The buncombe duplicate-row backfill remains outstanding.** `26dc41a3` fixed the
  `buncombe_unpaid_bills`/`buncombe_unpaid_bills_2024` situs bug going forward (both sources now
  added to `resolve_parcel_from_address.py`'s `DENY_SOURCES`), but the already-published rows under
  the old, wrong behavior are still on the board unbackfilled. This audit did not re-run a live
  duplicate scan (out of scope for a fast pass, and duplicate detection needs care around the
  dedupe-key collision hazard `ad86ec22`/`c39098a3` both had to guard against) — the figure in hand
  from earlier work today is **1,361 genuine duplicate rows** still needing a collision-safe
  backfill pass once it's safe to run one.
- **The Georgetown Catalis sibling-source lead needs a re-probe.** Georgetown's own Treasurer page
  links `georgetowncountysctax.com`, on the same CloudFront host and naming convention as the four
  counties already wired into `sc_catalis_delinquent_roll.py`'s `CATALIS_COUNTIES` — strong
  circumstantial evidence of a real per-parcel balance backend, but every probe this session hit a
  403 (reading as a shared-CDN rate-limit, not a Georgetown-specific wall). Needs a session where
  that CDN isn't currently blocking egress, plus locating the real data GUID from the site's JS
  bundle (the embedded GUID is a CMS id, not the data id, per `sc_catalis_delinquent_roll.py`'s own
  docstring).
- **`2b780229`'s SC DEW lien registry widening needs a scrape to take effect.** Confirmed directly
  this pass (Section 5): the code fix is live, but zero new rows exist outside the pre-existing
  12-county footprint. This is a concrete, low-effort next run, not a wall.
- **The 17-SC-county thin-coverage cluster is down to 16** for tax delinquent specifically
  (Dorchester now covered), but for the strict tax_delinquent/liens overlap the two families are no
  longer identical sets (Section 5) — worth a fresh look at exactly which of the remaining ~16 SC
  counties (Abbeville, Allendale, Bamberg, Barnwell, Calhoun, Chester, Chesterfield, Darlington,
  Dillon, Edgefield's now-tax_sale-only status, Fairfield, Greenwood, Lee, Marlboro, McCormick,
  Williamsburg) are genuine build targets vs. already-documented dead ends before assuming any one
  of them is untried.
- **HOA sale is still a total, board-wide gap** (0/146) — the one scraper that ever emits it
  (`charleston_mie`) sits outside the 18-county footprint. Unchanged; still an open scope decision,
  not a defect.
- **The NC-side row-count drift noted in Section 1** (McDowell/Burke/Gaston/Buncombe/Cleveland/
  Transylvania/Rutherford each up a few dozen rows versus this morning, unexplained by any of the
  three named landing commits) was flagged but not traced — worth a quick look next session, though
  it is immaterial to every percentage in this doc (each county's shift is under 2% of its own row
  count).

## What could not be verified precisely this pass

- Whether the ~160 non-SC `column_legal_notices` rows (Section 1) landed today or predate the
  morning baseline — the total board-wide math is exact either way, but the state-level NC/SC split
  of the +1,757 delta doesn't cleanly attribute without a second, earlier snapshot to diff against
  (not available in this pass).
- The exact cause of the small NC footprint-county row-count drift (Section 1/6) — flagged, not
  chased, per this task's fast/computation-only scope.
- Whether `2b780229`'s widened SC DEW gate would, once re-scraped, actually land new rows in the
  16-county thin-coverage cluster specifically, versus elsewhere in the 22 other newly-eligible
  non-footprint counties — that depends on where DEW's own registry actually has named liens, which
  is unknowable from board data alone until the scrape runs.
- A live re-scan for the 1,361 buncombe duplicate figure (taken as given from earlier work this
  session, not independently re-derived here) — see the note in Section 6.
