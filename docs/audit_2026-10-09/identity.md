# Audit 2026-10-09: identity (one row = one property, its own record, an owner the roll backs)

Area: duplicate properties, fused rows, owners the county roll contradicts. Code:
`src/foreclosure_scraper/identity.py` (rules + the pipeline pass), invariants:
`scripts/audit_checks/identity.py`, tests: `tests/test_identity.py` (made-up rows). Per-row detail
(names, addresses, the 40-row owner sample) is on the owner's Desktop, `Audit_2026-10-09/identity/`.

## 1. What was measured and how

Board: the reconciled pre_publish checkpoint on the VM (383,378 rows, saved 2026-10-09 14:01 UTC),
copied to the Mac and streamed (`audit_suite.checkpoint_rows`, the published shape); the live 10/7
board (350,013) for comparison. Peak RSS 665 MB. Repeat:
`uv run python scripts/audit_suite.py --checkpoint <dir> --only identity` (about 100 s).

| check | checkpoint | live 10/7 |
|---|---:|---:|
| old selfcheck "no duplicate identifiable properties" | 896 (83 fused keys, 1,060 rows) | 809 |
| identity-no-duplicate-properties | 375 | 348 |
| identity-multi-address-parcels (informational) | 666 keys | 595 |
| identity-fused-own-record | 127 | 4,306 (tax blocks before the tax scrub) |
| identity-owner-conflict-stamped | 9,389 | 10,752 |

Replay of the full identity pass on the checkpoint (`run_identity_pass` on every row whose
identity key has 2+ rows after unfusing, 3,191 rows as Listings): duplicates 375 -> 0; 127 rows
unfused, 487 rows merged into the row of their property (179 aged copies absorbed, 308 live records
merged, among them the unfused rows meeting their own record's row), no property merged with
another (the invariant re-run on the result reads 0 duplicates and the same 666 multi-property
keys plus the 7 the unfused rows created).

## 2. Defects

### D1 duplicates (896 -> 375 real -> 0 after the pass)
The old invariant grouped by any parcel string or any address whose first token has a digit and
counted every 2-3-address group as duplicates. Partitioned by property (`identity.partition`):

* 666 keys hold 2+ DIFFERENT properties: one parcel id with 2-3 real house numbers or units, each
  named by its own record (apartment complexes' code cases, a parcel's two damaged structures, a
  LiensNC master PIN's lots, a mobile-home bill beside the land bill). dedupe's identity rule refuses
  these merges on purpose; they are reported, never merged. (A 4th address already made the old
  check call the key "fused": the two rules disagreed.)
* digits without a house number ('6th Avenue', an interstate exit) name no property.
* 375 real duplicates, four causes: 185 one numbered address with no parcel (dedupe's fuzzy pass
  scored under 92, or the rows never met: UST incidents, SEMS / ACRES sites); 118 an aged copy of
  the same parcel and address (Catawba nc_county_pdf: the short account is nulled, the name resolver
  adds the PIN in the tail AFTER dedupe2, so the copy and the re-scrape never meet); 47 an aged copy
  at another address (the owner's MAILING address, Buncombe elderly / unpaid bills before the 9/29
  fix, or the same source record re-addressed by the county); 25 live rows of one parcel and address
  (not traced to one writer). Members of the 367 clusters: COLD 499, WARM 243 (call-ready A 1, B 3, C 3).
* Fix: `collapse_twins` merges exactly one property's rows: live base; an aged copy gives only
  `placeholder_twins.COPY_ALLOWLIST`; a second live record merges as dedupe would, the base keeps
  its own blocks (`keep_fresh_blocks`) and the absorbed record's own blocks stay in
  `raw['merged_records']`. Two rows stay apart when a source published two different ids for them
  (dedupe's source-parcel rule) or when one source's two non-identical records name owners with no
  name in common (units / tenants of one building). The Rutherford URL-fusion guard (dedupe roll URL
  keys) is untouched; its tests pass.
* `board_selfcheck` now counts duplicates with the same partition (and reports multi-address keys).
* Tests: `test_two_house_numbers_on_one_parcel_are_two_properties_not_duplicates`, `..._aged_copy_and_its_rescrape_...`,
  `..._owners_mailing_address_...`, `..._owner_occupied_house_...`, `..._same_record_at_a_new_county_address_...`,
  `..._two_owners_of_one_source_...`, `..._two_ids_of_one_source_roll_...`, `test_short_account_aged_copy_and_resolved_rescrape_collapse`,
  `test_collapse_is_idempotent_and_never_drops_a_property`. Invariant: `identity-no-duplicate-properties` (max 0).

### D2 fused rows (1,313 / 1,489 -> 127 real -> 0 after the pass)
`block-binding-e-fused-rows` read 1,489 on the checkpoint; 1,312 of them are "blocks name two
parcels" and are detector noise, not fused rows: 787 are `parcel_from_address.cache_ids` (an address
lookup's CANDIDATE list), 144 a row's own PIN beside its own short id (`lincoln_bulk` / `lincoln_vacant`),
the rest other-parcel blocks the block scrub removes. A real fused row is one whose OWN source record
names another valid parcel of the row's numbering system (`identity.fused_record`; a LiensNC parent
PIN, a candidate list, a short county account and another layer merged into the row are not): 127 on
the checkpoint (call-ready A 7, B 7). `unfuse` re-keys the row to its own record (parcel, the situs the
record states, its owner when the names disagree; a changed address clears the point) and records
what it displaced in `raw['unfused']`; nothing is deleted; the late block scrub then removes the
blocks of the displaced parcel. 61 of the 127 change address, 18 change owner. Tests:
`test_fused_row_is_rekeyed_to_its_own_record`, `test_not_fused_parent_pins_candidates_short_ids_and_other_layers`.
Invariant: `identity-fused-own-record` (max 0).

### D3 owner contradicted by every roll block (9,389 rows)
40 rows sampled (stratified by the contradicting block), checked against NC OneMap's parcel layer
by the row's own parcel id (26 NC rows) and Spartanburg's CAMA layer (4), 2.2 s apart; 18 had a third
source. Rule (`identity.owner_verdict`), scored on those 18:

| contradicting claim | decision | checked | right |
|---|---|---:|---:|
| no parcel id (`raw['gis']` from a point or the cache), a tax bill's historical taxpayer (qpaybill), another parcel's record | keep the row's owner | 9 | 9 |
| the county record of the row's own parcel (gis_attrs_full parno, lrcpwa reid, roll mailing with the parcel), row owner never refreshed | the roll's owner replaces it | 2 | 2 |
| same, but the row's owner carries a refresh stamp | undecided, kept | 7 | 3 row / 4 roll |

The refresh stamp `owner_name_as_of` is not proof: Listing.merge carries it in raw while the top-level
owner comes from the merge base (a HUD facility name carried a parcel-cache stamp). OneMap's Rutherford
data is dated 2024, so the 4 "roll" undecided cases are not settled either. Every contradicted row gets
`raw['owner_conflict'] = {decision, reason, block, loser}`. On the checkpoint (after unfusing):
row 7,238, roll 1,048 (owner changes: WARM 510, COLD 538, call-ready C 2, no A/B, no HOT),
undecided 1,105 (call-ready B 4, C 8). Call-ready rows whose owner the roll contradicts but the rule
keeps: A 37, B 29. Tests: `test_unbound_roll_owner_loses_...`, `test_bound_roll_record_replaces_...`,
`test_bound_record_against_a_refreshed_owner_is_undecided`, `test_historical_taxpayer_and_foreign_...`.
Invariant: `identity-owner-conflict-stamped` (max 0).

## 3. Wiring (main.py, the lead's change)

1. `run_enrich_tail()`, right after the `tax_verified_restore.failed` handler and BEFORE the
   block_binding late scrub (`blocks_unbound_late`, block_binding.md wiring 3), so the scrub drops the
   blocks of a parcel `unfuse` displaced and scoring sees one row per property:
   ```python
   try:
       from .identity import run_identity_pass
       enrichment_stats["identity"] = run_identity_pass(enriched)
   except Exception:
       log.error("identity_pass.failed", traceback=traceback.format_exc())
   ```
   It must run after `tax_binding.scrub_unbound_tax` (it does: that runs in `run()` after the prior
   merge): a copied foreign tax block would otherwise read as the row's own record.
2. When `GRANDFATHER_CARRIED=1`: right after the grandfather restore (`enriched.extend(_restored)`),
   `from .identity import collapse_twins; collapse_twins(enriched)` (restored prior rows are aged
   copies; idempotent).

Cost (measured on the 3,191-row subset only): the pass is one in-memory grouping of identity keys
(about 300k small views on a full board, estimated under 300 MB) plus a merge per cluster.

## 4. Open items

* Not wired (main.py is the lead's). Until it is, the three invariants fail on any new board.
* Root causes left upstream: the name resolver runs after dedupe2 (Catawba twins); dedupe's fuzzy
  threshold misses one numbered address written two ways; `owner_name_as_of` travels with raw on a
  merge (the owner_freshness writer's). The pass catches all three at the end of the tail.
* 22 of the 40 owner samples had no free third source checked (SC counties other than Spartanburg,
  rows without a parcel id). The undecided class (1,105) needs a person or a dated county record.
* call_ready could treat `owner_conflict.decision == 'undecided'` as "confirm identity first" (call_ready's).
* 666 multi-property keys stay as separate rows by design; a reader of the parcel sees several rows.

## 5. Outside this area

* `block-binding-e-fused-rows` counts `parcel_from_address.cache_ids` candidates and a row's own
  PIN / short-id pair as two parcels (931 of its 1,489 on the checkpoint).
* `own_source_block` matches every `arcgis_distress` layer to any `counties_generic.arcgis_distress.*`
  source: a merged county-owned record on a flood-damage row reads as the row's own record.
* The live 10/7 board still carries 4,306 own tax blocks of another parcel (tax_binding's, scrubbed
  on the checkpoint).
