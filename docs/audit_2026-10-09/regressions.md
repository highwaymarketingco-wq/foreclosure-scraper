# regressions: every HOLD blocker of the gated d42058b3 run, root-caused

The comparison of the finished gated run (pin d42058b3, checkpoint `pre_publish`, 383,378 rows)
with the live 10/7 board (350,013 rows) returned HOLD with 23 blockers. This area traced each one to
its cause, fixed the causes that are still open in HEAD, and left invariants that would have caught
them. Counts, slugs, county names and parcel-free row references only; per-row detail stays in
`~/Desktop/Audit_2026-10-09/regressions/`.

## 1. What was measured and how (repeatable)

1. One streaming pass per board into a scratch SQLite file (the live board through
   `compare_boards.BoardInput`, the checkpoint record by record, validated as `checkpoint.load` does):
   per row compare_boards' own facts (`join_keys`, `row_ref`, `field_values`, tier, signals) and the
   whole row compressed. Peak RSS 243 MB (live) and 98 MB (checkpoint).
2. The greedy join of `compare_boards.Comparison.add` replayed on the dumps: 346,149 matched, exactly
   the report's number, so every count below is on the report's own pairing.
3. Each missing row and each lost value was then checked at the PROPERTY level: is the row's parcel,
   numbered address, case, or the id its source keeps in its raw block (Lincoln PARCELID/PIN, the
   PTS Cloud account, the Rutherford Parcel_Number, the nc_county_pdf county id, `parcel_id_nulled`)
   on any candidate row, and does that row carry the value.
4. Causes were reproduced with HEAD's code on the live rows (dedupe on the Rutherford replay rows and
   on all 25,578 URL-only rows; the scorer on both sides of every lost signal with `today` fixed).
5. The run log of the gated run was read on the VM with grep only (carryover, collected, dedupe,
   board_persist, dedupe2, validation, comps events).

## 2. Blockers: cause, status, fix

| blocker (report) | what it really is | cause | status |
|---|---|---|---|
| rutherford_tax 5,109 -> 4,468 (581 unexplained) | 580 tax-roll rows fused into ONE row, plus 1 fold | the county site refuses the VM (403); carryover replayed the 5,109 published rows; 580 had no parcel (short id nulled), no situs, no case, so `dedupe_key()` was the roll URL and URL evidence merges two unnumbered rows with no parcel. Reproduced with HEAD: 5,109 -> 4,528 | FIXED NOW (dedupe roll URL keys) |
| buncombe_delinquent_tax 1,182 -> 827 | relabel: 1,181 of 1,182 rows on the candidate, 354 under another primary source (buncombe_unpaid_bills 278, multi_year 30, ...) | merge base = first row; `main.run()` builds `results` from `asyncio.wait`'s `done` SET, so the order (and every merged row's source, listing_type and top-level fields) changes every run | OPEN in main.py: wiring W1; compare and invariant now count attribution |
| multi_year_delinquent_tax 1,115 -> 436 | relabel: all 1,115 present, 740 now under pickens_delinquent_parcels; 149 also lost the attribution | as above, and `Listing.merge` kept one also_seen_in entry per URL (both sources cite the county's page) | FIXED NOW (merge keeps one entry per source+url) + W1 |
| kania 177 -> 150 | relabel (34 under nc_upset_bids); 0 missing | as above | W1 |
| sc_catalis_delinquent_roll 63 -> 53 | relabel (10 under pickens_delinquent_parcels); 0 missing | as above | W1 |
| small sources (homeharvest, vrm_va_reo, edgecombe, brunswick_legal_notices, hud_section8, rockhill, stokes, publicnoticesc, post_and_courier, hibid, lincoln_code_violations) | relabels | as above | W1 |
| anderson MIE, rogers_townsend, mcmichael, sc_county_rosters, hud_homestore, courtlistener_adversary | aged out (miss limit / sale passed) plus relabels | board_persist aging, by design | correct |
| 1,877 unexplained missing | about 1,316 are on the candidate under their PIN or account (the comparison could not follow them; 696 Lincoln, most of 467 PTS Cloud); about 549 are gone: the Rutherford fusion (580 rows, 367 whose ids are on no other row), PTS Cloud 94 (aged rows of Madison, Beaufort, Guilford, Pitt and Hyde fused across counties on one portal URL), about 90 small (rows whose only identity was a geocoder fallback-point address the prior correction cleared: obituaries, notices, DEQ sites) | dedupe URL fusion; compare could not follow a short id that became a PIN | FIXED NOW (dedupe; compare joins on the source's own id) |
| 1,696 folded into another row | correct folds: 2,717 of the 3,053 missing-but-present rows met a candidate row with the SAME parcel or source id (the 10/7 board held Lincoln twice: short-id row + PIN row), 198 consistent by case/address; the ~138 "conflicts" sampled are one account whose PIN was re-resolved (Henderson) | the 10/7 PIN migration (owner decision) folding duplicates | correct; no two real properties fused among them. The real fusions (URL) were the "unexplained" ones |
| 279 aged out | miss limit (200 Henderson PTS Cloud accounts) and terminal sales | board_persist aging | correct (see open item 3) |
| lost comps 1,599 | 862 of them still on the property (the fingerprint join paired different lots). Counted by property (parcel or source id) over the whole live board: 832 properties lost comps, 370 dropped by `validation._validate_comps` after the subject's kind changed (sfr comps on land, land comps on a house: correct), 462 not carried because the row's identity changed between runs (PTS Cloud 425, nc_county_pdf 23, Lincoln 14) and the comps loop hit its cap before reaching it | identity change + COMPS_PHASE_MAX_SECONDS | the carry-forward is the valuation area's (enrichment_comps carry_forward_from_prior, in progress); compare artifact FIXED NOW |
| lost tax_levy_year 712 / tax_balance 715 | 711 / 714 still on the property | compare join artifact (Lincoln PIN migration) | FIXED NOW (compare) |
| parcel_id 145, phone 61, mailing 51, assessed 74, address 25 | on the property: 59 / 43 / 42 / 60 / 6 still there; really lost: parcel 76, phone 13, mailing 1, assessed 5, address 8 | the merge keeps the FRESH row's parcel id: a short county id (Lincoln nc_county_pdf county ids, 27 rows) or a re-resolved resolver parcel (PTS Cloud, Burke storm-damage, heir parcels, about 45) displaced the prior valid parcel and validation nulled it; 5 fallback-point parcels withdrawn on purpose; 11 of the 13 lost phones are on the same nc_county_pdf rows | OPEN: merge precedence (the board_persist agent's), see W3 |
| HOT+WARM coverage: comps 40.8% -> 26.6%, multi_year, divorce, atty_rod_lien_checked, storm_damage (all, NC, SC) | dilution, not loss: on the 43,201 rows HOT+WARM in BOTH boards comps 16,913 -> 16,790, multi_year 2,031 -> 2,031, divorce 2,018 -> 2,025, atty_rod_lien_checked 1,683 -> 1,755, storm_damage 560 -> 560. HOT+WARM grew by 13,554 new rows and 9,757 COLD rows promoted (comps on 2% and 7% of them) | new sources + promotions; the comps loop runs in board order and was capped at 2,400 s, so the 13,251 new HOT+WARM rows without a condition tier were never reached | real loss on like-for-like rows: -123 comps (validation); open item 2 (comps order) |
| signals lost on rows in both | upset_bid 149 of 151: the window closed (the live row loses it too when scored on 10/8); tax_lien_chronic 82: Pickens prior-cycle-only (owner decision 10/7); lis_pendens 261 of 266: SC Public Index cases dismissed (withdrawn_case_type_other); tax_lien 774 of 1,205 and recorded_debt 839: verification refuted/stale; distressed_condition 290 of 296: the Pickens F5 rule (tax cycles are not physical distress); estate_lead 125 and distressed 106: the merge base flipped to a tax-roll record | verification and owner rules doing their job, except estate_lead / distressed (merge base) | estate_lead FIXED NOW (absorbed life-event types score); distressed: W1 |
| duplicates 809 -> 900; 83 fused keys | 702 groups carried from the live board; 113 new groups: 79 are one parcel at two house numbers (refused by the identity rule on purpose) or an aged copy beside its re-scrape; the 83 fused keys are placeholder/master ids (4 new: two Cumberland master parcels from the new cumberland_delinquent_tax roll, two Charlotte open-data ids), excluded by design | identity rule; aging | correct; no fix |
| 7 HOT that dropped, 25 that became HOT | see section 4 | 3 of 7 drops and 9 of 25 rises are merge-base flips | W1 + absorbed types |
| audit checks newly failing (drops-situs-road-nulled, pipeline-row-valued, pipeline-countyless-national, source-county-floor) and the Pages size | other areas' checks and fixes after the pin (drops_lineage, pipeline_gate, source_completeness; docs/handoff excluded from Pages) | | not this area |

## 3. Defects fixed in this area (code, test, invariant)

| # | defect | scale | fix | test | invariant |
|---|---|---|---|---|---|
| R1 | dedupe fuses every row of a county roll that shares only the roll URL | 580 Rutherford + 109 PTS Cloud on this run; replay of all 25,578 URL-only rows of the 10/7 board as aged copies: 6,881 rows left with the old rule (PTS Cloud 10,010 -> 1, Catawba 4,927 -> 2, UST 2,127 -> 1), 25,362 with the fix (216 exact repeats). Any carryover of PTS Cloud or Catawba would have collapsed them | `dedupe.identity_of` reads the id validation nulled (`nulled_source_parcel`); pass 1 buckets URL-keyed rows by county, owner, source id and the as-scraped fields (`url_bucket_key`); `url_key_conflict` | tests/test_dedupe_roll_url_keys.py | regressions-roll-records-kept |
| R2 | also_seen_in kept one entry per URL; absorbed record types not kept | 149 rows lost multi_year attribution | `Listing.merge`: one entry per (source, url), each with the absorbed listing_type | tests/test_absorbed_life_types.py | regressions-source-held |
| R3 | a life-event record folded under another record loses its signal | estate_lead lost on 125 rows; rows raised to HOT only by the base flip | `distress_score.absorbed_life_types` credited in `_collect` | tests/test_absorbed_life_types.py | regressions-absorbed-life-types |
| R4 | compare_boards: relabels read as source loss; short id -> PIN rows unjoinable, fingerprint pairs different lots; the HOT+WARM lens read tier churn as loss | 4 false source blockers, 1,311 rows wrongly "unexplained" (523 now joined, the rest seen as folded duplicates), false field losses (tax levy 620, tax balance 620, comps 373), 11 false coverage blockers | sources judged on rows held (live - missing + new), relabels a note; `source_id_keys` join; HOT+WARM judged on rows HOT or WARM on both boards | tests/test_compare_boards_regressions.py | (the comparison itself; section 8) |

Invariants (scripts/audit_checks/regressions.py, baseline docs/audit_2026-10-09/regressions_baseline.json
written from the 10/7 board: counts plus 64-bit record hashes, no ids):
- `regressions-roll-records-kept`: roll records the baseline held with < 3 misses that are gone, over
  max(10, 0.2%) per roll. Live board 0; d42058b3 candidate: rutherford_tax 579 of 7,294,
  nc_ptscloud 87 of 18,869 (rutherford_wildfire 5, lincoln_vacant 2, nc_county_pdf 1 pass).
- `regressions-source-held`: a source (>= 200 baseline rows) under 90% of its baseline counting
  primary OR also_seen_in. Live 0; candidate: multi_year_delinquent_tax 1,443 -> 1,292.
- `regressions-absorbed-life-types`: an absorbed life-event record the scorer credits but the
  published stack lacks. 0 on both (no board carries the typed entries yet).

## 4. HOT movement (all 7 drops and all 25 rises judged)

Drops (7): right by rule 4: a USDA REO not re-listed (presumed withdrawn), a Carteret listing whose
price cut aged out, an STR-permit row whose equity is no longer evidenced (score 28 -> 36 but the HOT
gate needs evidenced equity), and an obituary probate notice not re-listed (presumed withdrawn; a
death notice is not withdrawn by not being re-listed, see open item 4). Wrong 3: a Gaston
lis-pendens listing and two land listings whose merge base flipped to a code-enforcement or
land-listing record typed `unknown`, losing lis_pendens, distressed and price_cut (W1).
Rises (25): right 16: a sale re-listed in its window (2), a real price cut (2: an REO at 80,000 from
134,900; a condemned house 94,500 -> 84,500), heir-estate rows re-scraped after being presumed
withdrawn (9), an owner newly contactable and absentee (2, same signals, Bertie and Jackson), a Fannie
Mae REO re-listed (1). Defensible 3: national listings and an elderly-exemption row that took in a new
heir-estate record (estate_lead + probate_deed are new facts; the elderly signal went with the old
base). Order-driven 6: Rutherford tax-roll rows whose base flipped to the heir-estate record (COLD or
WARM with tax_lien on 10/7, HOT with estate_lead now, tax_lien gone). The estate fact is real; with
R3 the estate record scores whichever record is the base, and W1 keeps the base stable. New HOT rows
(3): one heir-estate parcel, two eCourts lis pendens with an open upset-bid window: right.

## 5. Open items

1. W1 (main.py, the lead wires it): sort scraper results by registry order so the merge base is
   stable run to run. Until wired, relabels continue (attribution only; R2-R4 keep data and scores).
2. Comps reach order: `enrich_with_comps` walks the board in order and is capped; new and HOT/WARM rows
   should go first. enrichment_comps.py is being changed by the valuation area (uncommitted edits);
   left to it. Why 425 PTS Cloud prior rows did not fold their comps onto their own re-scrape was NOT
   found: replayed with the pin's code on the PTS Cloud rows alone (19,548 prior, 10,351 fresh) the
   prior row folds and carries its comps; in the full run it did not (the re-scraped row carries
   neither the prior first_seen nor the comps). The comps carry-forward the valuation area is adding
   covers the value; the merge cause stays open.
3. 200 Henderson PTS Cloud accounts aged out together (miss limit). The 10/7 board held 1,828 Henderson
   rows of that source, 670 of them unread for 3 or 4 runs; the candidate holds 1,602, 445 at 4 misses
   (they leave next run). Whether the Henderson tenant stopped returning them or the taxes were paid
   was not verified (no live fetch done); source_completeness' refresh check (50% stale) does not fire
   at 37%.
4. Presumed-withdrawn on notice sources (obituaries): a death notice that is not re-listed is not
   withdrawn; aging caps it out of HOT. Owner decision whether notice sources join AGE_EXEMPT_SOURCES.
5. W3 (merge precedence, the board_persist agent): a fresh short county id must not displace a prior
   valid PIN (validation nulls the short one): 76 parcel ids, 13 phones on this run.

## 6. Seen outside this area

- block contamination: Rutherford rows whose rutherford_tax block names another taxpayer (fused in
  earlier runs) - block_binding's.
- 25,578 live rows (7.3%) have no parcel, no address and no case: identity only by URL (10,010 PTS
  Cloud, 4,923 Catawba, 2,127 UST incidents); they are safe from fusion now but cannot be verified.
- the comps rent pool built 0 rent rows on the gated run (5,578 on the 10/7 run): valuation's.

## 7. Wiring (not made here: main.py is the lead's, board_persist.py the merge-precedence agent's)

W1, src/foreclosure_scraper/main.py, right after the `for t in done:` loop that fills `results` (before
`raw: list[Listing] = []`):

```python
    # Deterministic merge base (audit 2026-10-09 regressions): `done` is a set, so results arrived in
    # a different order every run and dedupe()'s first row (source, listing_type, top-level fields)
    # flipped between runs.
    _slug_order = {s.slug: i for i, s in enumerate(scrapers)}
    results.sort(key=lambda r: _slug_order.get(r[0], len(_slug_order)))
```

W2, src/foreclosure_scraper/board_persist.py, merge_prior_board's signature loop, after
`if _provably_different_dict(rec, fresh_deduped[i]): continue` (with `from .dedupe import
url_key_conflict`): a prior row matched to a fresh row by a shared URL key alone must name the same
county and owner (dedupe's rule; different source ids are already refused through identity_of):

```python
                    if (sig[0] == "k" and str(sig[1]).startswith("url:")
                            and url_key_conflict(rec, fresh_deduped[i])):
                        continue
```

W3 (merge precedence): after `merged = fresh.merge(prior)`, a prior VALID parcel
(placeholder_twins.parcel_key) beats a fresh short id or a resolver-attached parcel of the same row;
keep the fresh short id in raw (as parcel_alias does). 76 parcel ids and 11 phones on this run.

Then: `uv run python scripts/audit_checks/regressions.py --write-baseline` after every accepted
publish (the baseline is the 10/7 board today).

## 8. The same candidate compared again with the fixed tool (HEAD, 2026-10-08 evening)

`scripts/compare_boards.py --baseline docs --candidate <the d42058b3 pre_publish checkpoint>
--no-size-estimate --skip-artifact-scan` on the Mac (16 min, peak RSS 281 MB). HOLD with 18 blockers
(was 23), every one now a real finding:

- rows: 346,672 matched (27,986 by the new source-id key), 3,341 missing (was 3,864): unexplained 566
  (was 1,877), folded 2,570, aged out 205. Source blockers: rutherford_tax only (5,109 -> 4,563 held,
  89%: the URL fusion R1). buncombe_delinquent_tax, multi_year, kania, sc_catalis and seven small
  sources are notes ("relabeled").
- coverage, judged on the 43,801 rows HOT or WARM on both boards: the 11 HOT+WARM blockers are gone;
  three remain. NC comps 41.14% -> 40.63% (109 rows: comps a kind change made invalid, see
  the comps row of section 2). tax_aging_surfaced ALL 68.0% -> 67.27% and NC 75.94% -> 71.59% (917 rows): 515 Lincoln
  vacant rows whose tax record moved from the 2025 bill (1 year late) to the 2026 bill, which is not
  late yet (distress_score.tax_not_yet_late, the tax calendar): the rule is right; whether the 2025
  bills were paid was not verified.
- fields lost on rows in both: tax balance 95 (was 715), tax levy year 92 (was 712), comps 1,226
  (was 1,599; blocker: validation drops plus the carry gap, open item 2), parcel 298, address 206,
  mailing 149 (the new join pairs more rows; all under the 1% line).
- invariants: regressions-roll-records-kept (rutherford_tax 579, nc_ptscloud 87) and
  regressions-source-held (multi_year attribution) hold the publish as they should; the others
  (additions, docs, drops, pipeline, repo-privacy, source-county-floor) are other areas' checks.
