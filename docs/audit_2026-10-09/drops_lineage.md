# Audit 2026-10-09: drops and column lineage (area `drops_lineage`)

What the pipeline removes, nulls or never publishes, whether each removal is right, and whether
each of the owner's 82 columns counts what the scorer acts on. Public-safe: counts, county names,
source slugs and parcel-id shapes only. Row-level detail (the withheld address strings, the id
table) is in `~/Desktop/Audit_2026-10-09/drops_lineage/` (private).

## 1. What was measured, and how (repeatable)

Inputs, all read-only:
* the 2026-10-08 gated run's log on the VM (`logs/vm-run-20261008T014033.log`, grep only) for every
  removal count and the 21,914 `validation.*` warning lines (source, id, value);
* that run's `dot_ocr` checkpoint (383,373 rows, full pre-publish raw), copied once to the Mac
  scratchpad and streamed (`board_parts.iter_gz_rows`, peak 65 MB);
* the published 10/7 board (350,013 rows, `board_stream.iter_board_rows`, peak 308 MB);
* the Mac stealth hand-off of 10/8 (`docs/handoff/stealth_leads.json`, 51,730 rows): fresh rows
  BEFORE the pipeline's filters, the only fresh rows on disk;
* the county parcel caches (`data/parcel_cache/*.sqlite`: NC OneMap parno/altparno/nparno and the
  county layers) to judge whether a nulled parcel id is the county's own parcel number;
* a static AST scan of every module for raw-key writes, diffed against `web_artifact.RAW_KEEP`.

Re-run: `uv run python scripts/audit_suite.py --only <the 8 names below>` (board), or with
`--checkpoint DIR`.

### The 10/8 run, every stage that removes a row or nulls a field

| stage (log event) | 10/8 count | verdict |
|---|---|---|
| `orchestrator.partitioned` sold pool | 221 rows | routed, not lost |
| `orchestrator.in_scope` | 3,564 rows | not measured row by row (fresh rows are not persisted); hand-off replay below |
| `orchestrator.active` (`_active_only`, DATELESS_OK) | 2,824 rows | on the board only 1 dateless row of a non-whitelisted live source; see 2.6 |
| `orchestrator.flip_filtered` | 277 rows | not measured |
| `orchestrator.source_all_filtered` | 26 warnings | 8 false alarms (2.4) |
| `orchestrator.deduped` / `dedupe2` | 28,084 / 1,778 merged | guarded (2.65 M fuzzy pairs refused); see section 4 |
| `board_persist` aged out | 13 terminal + 422 misses | 961 rows sit at the miss limit (2.6) |
| `orchestrator.oceanfront_repass` | 79 rows | not measured |
| `orchestrator.scope_repass` | 126 rows | 0 of the 10/7 board's rows are denied by today's rule: the 126 were fresh rows |
| `orchestrator.drop_countyless_national` | 3,767 rows | false drops for rows with a known city (2.3) |
| `orchestrator.situs_sanity_nulled` | 8,606 addresses | 82 real locations (2.2) |
| `validation` county_nulled_cross_state | 80 | right: all are the pseudo-county 'Statewide' (sc_des_brownfields 62, bankruptcy RSS 18) |
| `validation` parcel_nulled_too_short | 20,030 | 1,704 county parcel numbers wrongly nulled (2.1) |
| `validation` opening_bid_zeroed / too_large | 1 / 0 | right |
| `validation` tax_value_too_low | 1,791 | owner decision (3) |
| `validation` sqft / beds / baths out of range | 260 / 10 / 9 | not sampled |
| `validation` comps_dropped_kind_mismatch / price | 1,679 / 67 | not measurable: dropped comps are kept nowhere (3) |
| `web_artifact._slim_raw` (RAW_KEEP) | 27 keys on 10/8 rows | lost keys (2.5) |

## 2. Defects found and fixed

### 2.1 Short parcel ids that ARE the county's parcel number were nulled
* Class: false null. `validation._validate_parcel_id` nulls every id under 7 characters.
* Scale: 21,248 checkpoint rows carry `raw.parcel_id_nulled` (too_short). Each id was looked up in
  its county's parcel cache and the cache's situs house number compared with the row's.
  Confirmed parcel numbers, now kept: Cleveland 4-5 digits 648 rows (100% in the county layer;
  544 same house, 27 another), Onslow 6 digits and map-block forms 752 (99.3%; 646 / 8), Nash 6
  digits 237 (100%; 235 / 1), Rowan 6 digits 67 (100%; 67 / 0): **1,704 rows (8.0%)**; by source
  LiensNC 662, nc_its_public_tax 355, Rocky Mount blight survey 229, NC UST incidents 167, ...
  Rightly nulled (not the GIS parcel id): Catawba tax accounts 5,376 (0% in the layer), PTS Cloud
  Guilford / Beaufort / Madison about 7,300 (0%), Buncombe STR permit ids 620, Burke storm-layer
  ids 419. Genuine but left by owner decision (10-digit PIN + alias, `parcel_alias.py`): Lincoln
  1,074 (98%), Rutherford 943 (99.7%). Undecided: Pitt and Hyde PTS ids (about 2,900; Pitt 5-digit
  95% in the layer but 4-digit 0%, Hyde 64-94%; the rows carry no house number and the 13 Pitt
  rows that do all disagree), Polk map forms (97% in the layer, 11% at another house), Durham
  6 digits (86%).
* Fix: `validation.COUNTY_NATIVE_SHORT_PARCEL` + `county_native_short_parcel()`; a matching id is
  kept, a carried row's nulled one is restored, a stale nulled record of the same id is removed;
  new stats `parcel_kept_county_native`, `parcel_restored_county_native`.
* Tests: `tests/test_drops_lineage.py` (6 tests). Invariant: `drops-short-parcel-county-native`
  (10/7 board 1,443, 10/8 checkpoint 1,633, max 0).

### 2.2 SITUS SANITY withheld real road locations
* Class: false null. `main._situs_is_junk` treated a road as a road only when the suffix is the
  last word, so a house number after the street, a trailing direction or acreage, or an
  intersection fell through to the business-word test ('church', 'club', 'golf', 'academy', ...).
* Scale: 82 of 8,606 (0.95%): Dorchester BillTrax 13 of 13, Transylvania vacant 27 of 78, NC UST
  incidents 22 of 44, Lincoln vacant 7 of 7, NC inactive hazardous 3 of 11, SC UST 4 of 453,
  HomePath 2 of 2, qPayBill 2 of 1,423, Gaston vacant 1 of 1, EPA SEMS 1 of 32. The other 8,524 are
  title placeholders (6,218) and owner/entity names (2,306 incl. ones with a road word): right.
* Fix: `src/foreclosure_scraper/situs_sanity.py` (the old rule plus one exemption: a road word or
  numbered route in the first comma part, no corporate word, not a title placeholder). Main.py
  must import it (wiring below). Tests: 3 in `tests/test_drops_lineage.py`; the existing
  `tests/test_situs_sanity_and_terminal.py` cases all hold. Invariant: `drops-situs-road-nulled`
  (checkpoint 82, max 0). `raw.situs_nulled` now publishes, so the check sees published boards.

### 2.3 Countyless national rows dropped although their county is known
* Class: false drop. main.run has no ZIP/city to county step; `drop_countyless_national` removed
  3,767 rows. In the 10/8 hand-off, 906 national rows had no county, all with a city, 898 with an
  NC/SC ZIP (landandfarm 645, zillow_foreclosures 199, xome 27, trulia 13, ...).
* Fix: `drop_audit.fill_county_from_city()` (the 146-county gazetteer already used by
  fdic_failed_banks and the obituary matcher; places 395 of the 906, stamps `raw.county_backfill`)
  run BEFORE the scope re-pass, so a placed flip is still judged against the footprint;
  `drop_audit.count_by_source()` for the drop's log line. Test in `tests/test_drops_lineage.py`.
* Open: a ZIP table would place most of the remaining 511 (2.7 below).

### 2.4 `source_all_filtered` warned about sources that kept their rows
* Class: false alarm hiding real ones. Survivors were counted by `li.source == slug`. 8 of the 26
  warnings on 10/8 are scrapers whose rows carry other source strings: state_contamination (53,827
  scraped), stealth_handoff (27,888), arcgis_distress_layers (14,538), epa_frs_sites (3,714),
  sc_probate_notices (890), rocky_mount_blight_survey (618), raleigh_structure_fires (396),
  kinston_proposed_demolition (45); all have rows on the checkpoint. The real ones (all rows
  filtered): gaston_tax_foreclosures 81, cws_marketing 17, henderson_tax 15, fdic_failed_banks 9,
  williams 6, seeclickfix 6, hendersonville_lightning 5, buncombe_tax_foreclosure 4, and 1-3 row
  sources (not investigated).
* Fix: `drop_audit.all_filtered_sources()` counts by row identity. Test in `tests/test_drops_lineage.py`.

### 2.5 Raw keys computed and then dropped at publish (RAW_KEEP)
The publish keeps only RAW_KEEP keys. On the 10/8 checkpoint 25 keys outside it were on rows;
`tests/test_raw_keep_covers_enrichers.py` scanned only `enrich*.py` and `scrapers/` for the literal
`raw["k"] =` form. Now registered (row counts from the checkpoint):
* read back by the pipeline on a reloaded board: `parcel_id_alias` 680 (tax_binding.row_ids decides
  which tax debts are the row's own from it), `burke_spine` 533 (read by enrichment_lrcpwa_parcel),
  `withdrawn_case_type_other` 260 (the reversal of correction 6 needs it),
  `_land_buildability_checked` 292 (the enricher takes the first 300 unstamped land rows; with the
  stamp dropped every run re-checked the same rows and never reached the rest);
* audit trails of a removal: `situs_nulled` / `situs_quality` 8,606, `mailing_address_not_inherited`
  683, `auction_status_reported` (written after the checkpoint by enrichment_board_quality);
* provenance: `lincoln_bulk` 14,893, `sqft_source`, `derived_from`, `sp_case` (a conditional
  `raw={...} if ... else None` literal), the coastal admission tags `coastal_county` 6,207,
  `oceanfront` / `oceanfront_signals` 356, `downtown_charleston` 296, `near_beach_drive` 58;
* `gis` sub-keys the tuple dropped: `absentee` 15,377, `vacant` 14,912, `owner_occupied` 1,838,
  `deed_age` 55, `owner_changed` 18, `source`, `owner_match_strategy`;
* written only by enrichers that `scripts/enrich_board.py` runs (it cannot load today's board):
  census geocoder, envirofacts, crime stats, NC DOJ, NC OneMap, NC SOS entity, ncpts_lrc,
  USDA ERS, wetlands, realtor / Redfin market, address_owner_v2, ocr deficiency, bankruptcy
  petition, RentCast (main.run, key-gated), workflow engine state.
* Internal on purpose, with the reason in the test: `detail_page` (court page text: privacy),
  `obituary_match` / `obituary_private` (privacy), the two coastal `*_pending` tags (resolved in the
  run), `_equity_amortization`, raw copies of top-level fields.
* Newest enrichers checked: deed_chain, rod_chain, heir_candidates, richland_parcel, verification,
  tax_county_check, foreclosure_judgment_entered were already registered; nc_rod_render and
  generic_rod write `raw.rod` (registered); obituary_match stays internal (privacy rule).
* Test: `test_every_module_raw_key_survives_publish` (every module; raw_update / setdefault /
  update / conditional literals / module constants), plus a guard test of the scan and a pin of
  the read-back keys. The publish transform itself is guarded by pipeline_gate's `pipeline-raw-keep`;
  `lineage-gis-subkeys` adds the sub-key tuple.

### 2.6 Age-out and DATELESS_OK
* Dateless rows of a live source that `_active_only` drops when dateless: 1 on the 10/7 board
  (newspapers.index_journal). The retired DEW registry (`disabled=True`, cross-reference only) has
  8,288 published rows at 2 misses: they leave the board within three full runs (owner decision 3).
* Rows at the miss limit (removed next run unless re-scraped): 467 on the 10/7 board, 961 on the
  checkpoint (PTS Cloud 475, courtlistener_bankruptcy 109, asheville_helene 77, nc_notices 53,
  eCourts lis pendens 46, landandfarm 39, ...). Not verified one by one.
* Invariants: `drops-dateless-filtered-source` (max 25), `drops-age-out-imminent` (max 2,500).

### 2.7 Column lineage: the owner's 82 columns
Every column was traced writer -> raw -> RAW_KEEP -> scorer -> dashboard/CSV (static, file:line in
the lead's copy). Every raw key the 82 predicates read is published. Columns whose 10/1 presence
rule counts something the scorer does not act on (rows on the 10/7 board; the scorer's own count
in brackets):

| column | 10/1 counts, scorer does not | cause |
|---|---|---|
| `lt_tax_lien` | 45,093 (71,110) | LiensNC lien-agent filings typed tax_lien; the scorer treats them as context |
| `title_risk` | 6,537 (1,682) | any classification counted; scorer: surviving senior debt only |
| `divorce` | 4,761 (344) | any name match; scorer: middle-initial agreement, party role, 7 years |
| `phone` | 3,546 (77,748) | do-not-dial / agent / people-search phones; scorer, CSV and dashboard use the phone gate |
| `code_enforcement` | 1,668 (6,139) | expired TTL and non-vacancy cases counted, list-shaped blocks missed |
| `storm_damage` | 499 (751) | 'unaffected' / minor records counted |
| `email` | 210 (46,777) | attorney / agent / broker addresses counted; the LiensNC owner e-mail (46,953 rows classified 'other') not recognised as the owner's |
| `incarceration` / `jail_booking` / `bop_federal` | 68 / 27 / 33 | ended custody and orphan jail flags counted |
| `vacancy` / `bankruptcy_stay` | 7 / 3 | free-text utility status; lapsed stays |

Fixed (second view of `scripts/gap_matrix.py`; the 10/1 rule is kept for comparability):
`SCORER_GATES` / `scorer_consistent_hits()` call the scorer's own predicates (one source of truth)
for the 12 columns above plus `lien_priority`, `usps_vacancy` and `probate`; a gated block that is present
still counts as checked. Attorney columns: `atty_heir_candidates` reads `raw.heir_candidates`,
`atty_obituary_match` needs an obituary block (probate notices stamp `life_event` too),
`atty_deed_ref` reads the `instrument` key the register scrapers write, `atty_probate_case` reads
`probate.case_number`, `atty_taxpayer_of_record` no longer counts a LiensNC filing's owner block or
a probate notice's representative. Writers fixed: `enrichment_email_extract.owner_email_of()` /
`liensnc_owner_email()` (the filing's owner block only, never the contractor's or claimant's
address), `enrichment_surface_contacts` classifies that address 'owner', `campaign_export` reads it
(it read `skip_trace.owner_email`, which no provider writes: its e-mail column was always blank).
Tests: 10 in `tests/test_drops_lineage.py`. Invariant: `lineage-scorer-gated-columns` (max 0; its
detail reports the 10/1 gap above on every board).

Documented, not changed (other areas or the owner): `builder_distress` is counted by the 10/1 rule
but the lead-signal tagger skips LiensNC rows, its only writer, so it is never scored;
`two_year_delinquent` writers disagree (nc_its_public_tax and albemarle_observer_tax_lists count
every unpaid year, sc_catalis_delinquent_roll only late years); the Spartanburg vacant registry
writes `raw.vacant` without `vacant: True`, so the scorer never reads it as a vacant structure
(it scores `distressed` instead); `sc_dew_lien_registry` writes under `sc_state_tax_lien`;
`lien_priority` is a dict but the lead-signal tagger and dashboard test for a list, so they never
fire; `quiet_title` equals `heir_naming_publication` by construction.

## 3. Open items

1. DONE (decision 2026-10-09) tax_value_too_low (1,791 rows): the values are the counties' own
   figures (Greenville TAXMKTVAL median $500, qPayBill appraised median $810, Rutherford about
   $3,300); the row's kind is what is wrong. validation now keeps the figure in
   `raw.tax_value_low` {value, county, source, reason: kind_unverified} and sets
   `raw.low_value_parcel`; Listing.tax_value stays empty; `valuation.calc` withholds the
   single-family ARV on a flagged non-land row (flag `low_value_parcel`, arv_trust 'withheld', so
   no equity, bid or ROI is built on it); a carried flag clears when the row becomes land or shows a
   house-sized county value; property_kind is not changed (no clear rule). Tests: 3 in
   `tests/test_drops_lineage.py`. Invariant: `drops-low-value-parcel` (max 0).
2. Lincoln and Rutherford short ids (2,017 rows) are genuine but stay nulled under the 10/7 owner
   decision (PIN + alias). Pitt / Hyde PTS, Polk and Durham need a house-number check per row first.
3. DONE (decision 2026-10-09) the retired DEW registry's 8,288 rows age out as designed. Before
   they go, every row was exported privately (`~/Desktop/Audit_2026-10-09/dew_registry_rows.csv`):
   8,288 rows in 12 SC counties (Charleston 3,244, Horry 1,629, Spartanburg 1,107, Beaufort 844,
   Anderson 406, Pickens 300, ...), all with an address, 2,459 with a parcel id.
4. DONE ZIP to county: `scripts/build_zip_county_table.py` builds `_zip_to_county.py` offline from
   the parcel caches and the board with backfill_missing_county.py's rules (543 one-county ZIPs: NC
   364, SC 179; a ZIP that spans counties is left out). `fill_county_from_city` uses the city first,
   then the ZIP, and leaves a row whose two disagree. On the 906 countyless hand-off rows: 605
   placed (city 156, ZIP 213, both agreeing 236), 3 conflicts left, 298 still without a county.
5. Not measured: in_scope / active / flip removals row by row (fresh rows are not persisted; the
   wiring below logs them per source from the next run), comps dropped for kind, sqft out of range,
   the 961 rows at the miss limit.
6. `dedupe.parcel_key` treats ids under 7 characters as untrusted, so the kept county-native ids do
   not act as identity evidence in dedupe (same as today in-run). Left for the dedupe area.
7. The pre-run gate runs the suite on the LAST checkpoint, which predates these fixes:
   `drops-short-parcel-county-native` (1,633) and `drops-situs-road-nulled` (82) fail on it by
   design until a run on the fixed pin.

## 4. Outside this area (one line each)

* dedupe: 107 primary keys cover 4+ distinct addresses, several are placeholder-title address keys
  ('parcel — hyde county 2025 delinquent property tax list ...') produced by nulled parcel ids.
* `campaign_export` and `scripts/enrich_board.py` have no caller that can run on today's board.
* `tests/test_pickens_delinquent_parcels.py::test_the_week_one_republication_adds_its_parcels_and_newer_amounts`
  failed once inside a 93-file run and passes alone (order-dependent).
* LiensNC's 45,093 tax_lien-typed rows inflate every tax column of the gap matrix's 10/1 view.

## Wiring for main.py (the lead applies; I did not edit main.py)

1. After `def _situs_is_junk(...)` (ends `return bool(_SITUS_ENTITY_RE.search(first))`, about line
   1134), add:
   `from .situs_sanity import situs_is_junk as _situs_is_junk  # noqa: E402,F811 (audit 2026-10-09)`
2. Replace the block under `# Silent-drop warning` (from `survived_by_source: Counter = ...` to the
   end of its `for` loop, about lines 1521-1526) with:
   ```python
       from .drop_audit import all_filtered_sources
       for slug, scraped_n in all_filtered_sources(results, by_source, active):
           log.warning("orchestrator.source_all_filtered",
                       source=slug, scraped=scraped_n,
                       note="OK with rows but 0 reached the dashboard post-filter")
   ```
3. Immediately before `_pre_scope = len(enriched)` (the scope re-pass, about line 2129), add:
   ```python
       try:
           from .drop_audit import fill_county_from_city
           _cf = fill_county_from_city(enriched)
           if _cf["filled"]:
               log.info("orchestrator.countyless_national_placed", **_cf)
       except Exception:
           log.error("countyless_fill.failed", traceback=traceback.format_exc())
   ```
4. In the countyless drop, before `_pre_natl = len(enriched)`, add
   `from .drop_audit import count_by_source, is_countyless_national` and
   `_natl_by_src = count_by_source(enriched, is_countyless_national)`, and add
   `by_source=dict(list(_natl_by_src.items())[:15])` to the `orchestrator.drop_countyless_national`
   log call.
5. (2026-10-09, after the decisions) per-source counts for the three ingest filters. In the block
   under `# Filter to scope`, add `from .drop_audit import removed_by_source`, then add a keyword to
   each log call:
   * `orchestrator.in_scope`: `removed_by_source=removed_by_source(active_raw, in_area),`
   * `orchestrator.active`: `removed_by_source=removed_by_source(in_area, active),`
   * `orchestrator.flip_filtered`: `removed_by_source=removed_by_source(active, flip_able),`
     (before `active = flip_able`).

