# Audit 2026-10-09: block binding (every raw block belongs to its row)

The 10/8 tax finding (one county tax debt copied onto 20,185 wrong rows) was one instance of a
general defect: a `raw[...]` block on a row that is another property's, another owner's or another
case's record. This area measured that for every other block on the published 10/7 board
(350,013 rows), found the writers and merge paths that create it, fixed the sources that still
do, and added a scrub that cleans what the prior board already carries, plus invariants.
County property-tax blocks stay with `tax_binding.py` (they are skipped here).

## 1. What was measured and how

Everything streams the board (`board_stream.iter_board_rows_with_detail`, the `cama` and
`vision` detail keys merged); peak RSS 430 MB; no network.

* **Inventory.** 315 distinct top-level raw keys on the board plus 5 lazy-detail keys (comps
  85,061 rows, foreclosure_sold_comps 74,867, rent_comps 22,295, cama 21,653, vision 21,322).
  `block_binding.py` classifies every key: area-level (26: flood, census, comps, FEMA ...),
  derived pipeline outputs (about 130: scores, flags, markers), person blocks (37: owner
  mailing, phone, skip trace, court and person matches), county tax (tax_binding's), and property
  blocks (everything else). There is no `comps_tight`, `heir_candidates` or `rod_chain` on the
  10/7 board (the latter two land with the next full run).
* **Per block, per row** (`block_binding.probe` / `block_verdict`): the county, state, parcel
  ids, situs and owner/person the block states, from per-block field specs (a layer's
  owner-mailing STATE is not the property's state; a jail's county is not the property's), then
  the verdict: `foreign_county` (b), `other_parcel` / `other_address` (c, tax_binding's
  `id_relation` and `address_relation`), `other_person` (d, roll-aware: the row's owner is
  checked against the county-roll owners on the row first), `fallback_point` (a point-looked-up
  block on a row whose point is a shared geocoder fallback and which has no parcel id or
  house-numbered address of its own), `own_source` (the row's own scraper record: never removed).
* **Across rows** (a): canonical JSON of each block (volatile `*_at`, `fetched`, day counts
  dropped), 63-bit fingerprint; a fingerprint on rows of 2+ different properties
  (`tax_binding.count_properties`) is a copy where it does not bind (its parcel or situs is not the
  row's, the owner it names is not the row's owner, or, for a block naming nobody, the row is not
  one of the one owner most copies share: a multi-parcel deed or an HOA's lots stay). Only blocks
  that name one property are compared (a parcel id, a situs, a deed reference, a bill number); a
  mailing address alone is not (one property manager's office mails for many owners).
* **(e) merged rows**: blocks naming two parcels of one numbering system; the row's own source
  record naming a parcel the row does not carry; one parcel id on rows of two counties; the row's
  county against its county-specific source slug.

Repeat with `uv run python scripts/audit_suite.py --only block_binding` (one pass, about 100 s).

### On the published 10/7 board (before any scrub)

| check | rows checked | violations |
|---|---:|---:|
| block-binding-family-gis | 154,733 | 8,212 |
| block-binding-family-owner-contact | 207,632 | 22,317 |
| block-binding-family-deed-sale | 90,708 | 5,288 |
| block-binding-family-photo | 88,957 | 3,726 |
| block-binding-family-court-lien | 105,246 | 367 |
| block-binding-family-person-match | 17,844 | 3,146 |
| block-binding-family-code-site | 93,371 | 313 |
| block-binding-family-resolution | 46,503 | 461 |
| block-binding-family-other | 29,257 | 19 |
| block-binding-a-shared-copy (copies) | 254,601 | 21,663 |
| block-binding-b-foreign-county | 318,590 | 109 |
| block-binding-c-other-parcel | 318,590 | 10,222 |
| block-binding-d-other-person | 318,590 | 21,034 |
| block-binding-fallback-point | 318,590 | 9,016 |
| block-binding-e-fused-rows | 350,013 | 2,964 |
| block-binding-e-parcel-two-counties | 169,286 | 341 |
| block-binding-e-row-county-vs-source | 101,828 | 18 |

(The suite's fallback check uses only flagged points and county seats; the scrub also counts a
point 8 or more rows share, so it finds more.)

### What the scrub removes (replay of `scrub_unbound_blocks` over the 10/7 board)

42,618 rows (HOT 13, WARM 8,554, COLD 34,049), 63,702 blocks (HOT rows 30, WARM rows 15,581):
other_person 26,647, fallback_point 14,092, other_parcel 11,326, shared_copy 6,969,
other_address 3,271, derived from a removed block 1,258, foreign_county 139; plus 2,233 estimated
living areas cleared with the footprint they came from. Top counties by blocks: Buncombe 6,703,
Rutherford 5,194, Spartanburg 5,146, Lincoln 3,614, Gaston 3,598, Anderson 3,409, Charleston 3,386,
Pickens 2,948, Mecklenburg 2,840, McDowell 2,530.

| block | reason | blocks | HOT | WARM | top counties | writer |
|---|---|---:|---:|---:|---|---|
| skip_trace | other_person | 15,507 | 1 | 1,799 | Wake 1,701, Mecklenburg 1,308, Rutherford 1,135 | tax_records_only |
| owner_mailing | other_person | 7,396 | 0 | 1,337 | Spartanburg 1,812, Rutherford 734 | liensnc_filing 4,213, county_gis 1,124 |
| deed_chain | fallback_point | 4,813 | 0 | 158 | Mecklenburg 864, Pickens 582, Anderson 377 | gis.last_sale |
| footprint | fallback_point | 3,176 | 0 | 49 | Charleston 1,613, Pickens 828 | ms_building_footprints |
| sc_state_tax_lien | other_person | 3,035 | 2 | 708 | Horry 997, Spartanburg 804, Charleston 643 | sc_dew_lien_registry |
| owner_mailing | other_parcel | 2,892 | 8 | 1,716 | Buncombe 811, McDowell 456, Lincoln 277 | county_gis 2,156 |
| gis_attrs_full | other_parcel | 2,839 | 1 | 1,544 | Spartanburg 695, Lincoln 490, Henderson 333 | gis_attrs point query |
| owner_mailing | other_address | 2,520 | 0 | 743 | Rutherford 1,271, Buncombe 418 | county_gis 1,241, nc_onemap 1,043 |
| skip_trace | other_parcel | 2,516 | 8 | 1,480 | Buncombe 762, McDowell 451 | tax_records_only |
| ocr_extraction | shared_copy | 2,206 | 2 | 1,585 | McDowell 1,159, Buncombe 941 | enrichment_ocr |
| gaston_gis | other_parcel | 2,103 | 1 | 86 | Gaston 2,103 | gaston_vacant (prior copy) |
| gis_attrs_full | fallback_point | 1,434 | 0 | 217 | Cherokee 391, Pickens 326, Anderson 318 | gis_attrs point query |
| gis | fallback_point | 1,411 | 0 | 343 | Cherokee 357, Anderson 331, Pickens 192 | gis_attrs point query |
| deed_chain | shared_copy | 1,120 | 0 | 340 | Lincoln 527, Henderson 303, Buncombe 251 | gis.last_sale |
| cama | fallback_point | 1,067 | 0 | 156 | Anderson 1,023 | owner_mailing CAMA |
| last_sale | fallback_point | 895 | 0 | 166 | Anderson 801 | cama, cama+assessor |
| parcel_resolution | shared_copy | 609 | 0 | 440 | Buncombe 178, Rutherford 125, McDowell 114 | reverse geocode |
| gis_attrs_full | shared_copy | 604 | 0 | 145 | Rutherford 246, New Hanover 193 | gis_attrs |
| gis | shared_copy | 506 | 0 | 109 | Lincoln 204, Transylvania 87 | gis |
| images | fallback_point | 473 | 0 | 56 | Rutherford 47, Charleston 47 | enrichment_images |
| parcel_from_address | shared_copy | 469 | 0 | 1 | New Hanover 108, Iredell 80 | repair_parcel_from_address |
| owner_phone | other_person | 402 | 2 | 195 | Buncombe 342 | buncombe_accela 286 |
| owner_phone | derived (with ocr / filing) | 372 | 0 | 182 | Buncombe 147, Anderson 76 | ocr_legal_notice 222, liensnc_filing 150 |
| cama | shared_copy | 347 | 0 | 251 | Oconee 208, Buncombe 110 | owner_mailing CAMA |
| divorce | shared_copy | 217 | 0 | 83 | Spartanburg 179 | sc_fccms |

Every HOT-row removal (30 blocks on 13 rows) was read by hand: each is a neighbour's owner
mailing or skip trace at a different house number (for example Buncombe 0617137556 carried the
record of 0617-13-7051 at a different address, 9634775085 that of 9634-77-7232), a business's
state tax lien, another parcel's Gaston GIS bag, or the bulk-roster OCR.

After the scrub every per-row check reads 0; the shared-copy residual is 9 (second-order: a copy
that bound through a block removed in the same pass); fused rows 1,313 (not unfused by anything:
section 3).

## 2. Defects, causes, fixes

| # | class | scale | cause | fix | test | invariant |
|---|---|---|---|---|---|---|
| 1 | prior wins over the fresh scrape, leaf by leaf | every matched row whose scraper re-read a block (Gaston: 2,103 own-scraper `gaston_gis` blocks name another parcel) | `merge_prior_board` folds with `fresh.merge(prior)`; `models._deep_merge_dict` lets the PRIOR leaf win, so a new balance, status, bid or owner lost to last run's copy and a prior copy of another record was blended into the fresh one; missing-only enrichers then never recompute it | `block_binding.keep_fresh_blocks` at all three merge sites (`board_persist._keep_fresh_blocks`): the fresh record wins, the prior only fills keys the fresh lacks, a prior block of a different record (other parcel, county or situs) is dropped whole; enrichment the fresh row does not carry is still carried. Stats `fresh_block_kept`, `fresh_block_whole` | `test_keep_fresh_blocks_lets_the_fresh_record_win`, `test_merge_prior_board_keeps_the_fresh_scraper_block` | `block-binding-e-fused-rows`, `-c-other-parcel` |
| 2 | records looked up at a shared fallback point | 14,092 blocks (Cherokee SC parcel attributes on 407 rows at one centroid, Pickens 362, Anderson CAMA on 775, one Rutherford aerial tile on 243 rows, Georgetown 244) | `enrichment_gis_attrs` queried BY POINT first even with a parcel id, cached the bag by point, and copied its owner/situs; `enrichment_images._has_precise_point` only refused county seats; deed chain, last sale, value, tenure derive from those | gis_attrs: a fallback point (flag, county seat, or 8+ rows on the point) is never queried; a point or parcel bag (also a cached one) naming another parcel of the row's numbering system is dropped and the parcel asked instead (`_bag_binds`); images: `_has_precise_point` refuses a flagged or shared point; scrub reason `fallback_point` (and the footprint's estimated living area with it) | `test_fallback_point_blocks_go_from_rows_with_no_location_of_their_own`, `test_images_do_not_frame_a_fallback_point`, `test_gis_attrs_bag_of_another_parcel_does_not_bind` | `block-binding-fallback-point`, `-family-photo`, `-family-gis` |
| 3 | another parcel's owner record | owner_mailing other_parcel 2,892 (HOT 8), skip_trace 2,516 (HOT 8), gis_attrs_full 2,839, other_address 2,520 + 352 | (a) pre-10/6 address-key merges fused two parcels with one street address in a county (Buncombe 9644-82-9554 with 9701-17-4416; 9677-00-0864 with 9686-92-9563); (b) the gis_attrs point fell in the next lot (Charleston 5351000015 carries 5351000075's bag; Spartanburg 9-03-10-029.14 carries 1-08-03-030.01's); (c) one owner-mailing record (parcel 1656703) on 1,022 Rutherford rows with their own parcels and points, all first seen 2026-08-06 (writer not reproduced from today's code) | today's dedupe refuses (a); #2 stops (b); scrub `other_parcel` / `other_address` / `other_person` / `shared_copy` cleans what the board carries | `test_other_parcel_other_address_and_not_comparable_ids`, `test_scrub_removes_a_copied_mailing_where_the_owner_differs` | `-c-other-parcel`, `-a-shared-copy`, `-family-owner-contact` |
| 4 | one roster's OCR on every row of the roster | 2,206 rows (HOT 2, WARM 1,585), McDowell 1,159, Buncombe 941 | `enrichment_ocr.enrich_ocr_extraction` (script-only: `scripts/enrich_board.py`, `run_ocr_full.py`; kept by RAW_KEEP) OCRs `source_url`, which every row of a bulk list shares, and stamps the county office phone as each row's `owner_phone` (that blocks the voter and county phone lookups, which skip a row that has one) | `enrichment_ocr.shared_documents`: a document more than `DOC_OCR_MAX_SHARE` (3) rows share is skipped; scrub removes the copies and their `ocr_legal_notice` phone and email | `test_ocr_skips_a_document_many_rows_share`, `test_removed_filing_takes_its_contacts_and_bulk_ocr_takes_its_phone` | `-a-shared-copy` |
| 5 | another person's lien or filing contact | sc_state_tax_lien 3,035 (HOT 2, WARM 708); LiensNC filer contact as owner mailing 4,213 and skip traces built from it; jail, BOP, probate, heir-estate, obituary and SOS mismatches 307 | DEW business liens and LiensNC filings merge into a property row by address, though the debtor or filer is not the owner the county roll names | scrub `other_person` (a filing's own contact goes only when the county roll on the row names another owner) | `test_other_person_is_roll_aware`, `test_a_filers_contact_on_its_own_filing_row_goes_only_when_the_roll_names_another_owner` | `-d-other-person`, `-family-person-match` |
| 6 | copied sale history | deed_chain 1,120, last_sale, cama 347, parcel_resolution 609, divorce 217 | one GIS last sale (Henderson: one 2007 deed, book 001314/00524, on 292 rows of distinct parcels and owners) and reverse-geocode records copied across rows; multi-parcel deeds whose total consideration sits on each lot (Anderson USDA lots) | scrub `shared_copy` (one owner's multi-parcel deed stays) and the value/tenure derived from a removed sale | `test_multi_parcel_deed_of_one_owner_stays_but_a_copied_deed_goes` | `-a-shared-copy`, `-family-deed-sale` |
| 7 | removed tax bindings to re-check | 898 same-address-different-account rows, 3,052 wrong-county rows (3,127 blocks) | tax_binding (10/8) | list for the county-site sweep (private, owner's Desktop) | n/a | tax area |

The scrub (`block_binding.scrub_unbound_blocks`) is in place, idempotent, never raises on an odd
row, counts only (`test_scrub_is_idempotent_and_tolerates_odd_rows`), and re-judges a row after a
removal (up to 3 rounds). It must be wired into `main.py` (the lead's change).

### Wiring (main.py, the lead's change)

1. `run()`, right after the `tax_unbound.failed` handler (the tax scrub after the prior merge and
   prior correction, before any enricher):
   ```python
   try:
       from .block_binding import scrub_unbound_blocks
       log.info("orchestrator.blocks_unbound", **scrub_unbound_blocks(deduped))
       if _grandfather:
           log.info("orchestrator.blocks_unbound_grandfather", **scrub_unbound_blocks(_grandfather))
   except Exception:  # noqa: BLE001
       log.error("blocks_unbound.failed", traceback=traceback.format_exc())
   ```
2. `run_enrich_tail()`, inside `if _grandfather:` after its `scrub_unbound_tax(_grandfather)` line:
   `log.info("orchestrator.blocks_unbound_grandfather", **scrub_unbound_blocks(_grandfather))`
   (import `scrub_unbound_blocks` beside `scrub_unbound_tax`).
3. `run_enrich_tail()`, right after the `tax_verified_restore.failed` handler (before the
   stacked-distress score):
   ```python
   try:
       from .block_binding import scrub_unbound_blocks
       enrichment_stats["blocks_unbound_late"] = scrub_unbound_blocks(enriched)
   except Exception:
       log.error("blocks_unbound_late.failed", traceback=traceback.format_exc())
   ```
Cost: one in-memory pass each (verdicts plus a fingerprint index of about 0.5 M entries, about
100 MB while it runs; the streamed replay of the whole board took about 3 minutes per pass).

## 3. Open items

* **Not wired yet** (main.py is the lead's): the scrub after the prior merge (beside the tax
  scrub), on the grandfather snapshot, and once more before scoring (to drop what the enrichers
  still without a fallback guard re-attach in the same run).
* **Writers still without a fallback-point guard** (the late scrub covers their output until
  fixed): `enrichment_footprint_sqft` (county-seat check only), `enrichment_assessor_card` via
  `parcel_resolver` point lookup, the CAMA writer in `enrichment_owner_mailing`
  (`is_target`) and `enrichment_sc_cama`, `enrichment_parcel_reverse_geo` (target filter and the
  stored approximate address it promotes), `enrichment_streetview._location_query`,
  `enrichment_vision._select_image_urls` (another agent is editing enrichment_vision.py; not
  touched).
* **Fused legacy rows** (1,313 after the scrub; 143 whose own source record names another parcel
  than the row's): pre-10/6 address-key merges (elderly mailing-as-property, street-only
  addresses, LiensNC parent PINs) left rows whose top-level parcel and owner are one property's and
  whose source record is another's. Nothing unfuses them; the invariant gates regressions.
* **Owner contradicted by the roll**: 12,063 rows whose owner shares no name with any county-roll
  block on the row (8,104 of them through `raw['gis']`). Either the row's owner is stale (the
  board never refreshes an owner it already has) or the gis record is a neighbour's; `raw['gis']`
  carries no parcel id, so it cannot be bound. Recommended: every gis writer stamps
  `raw['gis']['parcel']`, and an owner-refresh pass. Not scrubbed.
* **Rutherford owner-mailing copy** and **Henderson last-sale copy** (August): the writer that made
  them is not reproduced from today's code; the scrub removes them.
* Not verified: anything against a live county site (all evidence is the board's own fields);
  that each missing-only enricher refills a removed block on the next run.

## 4. Outside this area

* LiensNC parsed PINs land on rows of the wrong county: 341 parcel ids sit on rows of two
  counties (NC 6827-30-5216 on Burke and Forsyth rows).
* 18 rows carry a county other than their county-specific source's (Lincoln code cases as
  Cleveland, Buncombe, Carteret, Caswell leads).
* `tests/test_raw_keep_covers_enrichers.py` fails on another agent's uncommitted
  `doc_ocr_rejected` key (enrichment_doc_ocr.py).
* `skip_trace` (`tax_records_only`) duplicates owner fields and goes stale with them (15,507
  disagree with the row's owner).
