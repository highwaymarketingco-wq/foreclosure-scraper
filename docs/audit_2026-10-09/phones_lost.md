# phones_lost: owner phones the reconciled board lost against the live board

Comparison `logs/compare-20261009T023221` (VM): reconciled checkpoint (pin aa680fba, 383,378 rows)
against the live 10/7 board (350,013). Field `phone` (`raw.owner_phone.phone`, a valid NANP number):
1,124 of the 80,363 rows in both lost it (blocker: more than 1%). accepted_drops.md left 350 of
them unexplained by the block_binding counts. Counts, county names, source slugs and parcel ids
only; the per-row list with refs is private (`~/Desktop/Audit_2026-10-09/phones_lost/`).

## 1. What was measured, and how (repeatable)

1. The 1,124 best-of-both phone entries (`compare-...best_of_both.jsonl`, field `phone`), each a
   baseline ref and a candidate ref (`compare_boards.row_ref`: parcel id, else a hash of the row's
   join keys).
2. One streaming pass of the live board and one of the checkpoint (read as compare_boards reads it:
   `Listing.model_validate` + `web_artifact._to_dict`), keeping only the rows behind those refs and
   a count of rows per phone number (peak RSS 433 MB and 257 MB).
3. Per entry: the live row's `owner_phone` block put back on the candidate row and judged by
   `block_binding` (per-row verdicts and `scrub_row`), the source block it came from (LiensNC
   filing, bulk OCR), whether the number sits on rows of other owners, whether the row's owner or
   parcel changed between the boards. Every entry got exactly one cause.
4. By hand, field by field against the row's own blocks: 43 rows across the buckets (12 of the
   first "unexplained" pass, 8 LiensNC, 8 other-person, 3 replaced, 6 Henderson re-joined, 6 scrub
   order, the 11 remaining unexplained), plus the 45 LiensNC rows the address fix would restore,
   plus 16 builder / filer-line phone groups.

## 2. Result: the 1,124 lost phones by cause

| cause | rows | verdict |
|---|---|---|
| the phone names another person, or the row's owner changed between the boards (`other_person`; Buncombe Accela permit contacts 269, voter-file matches, Lincoln taxpayer) | 524 | correct |
| the row's LiensNC filing is another house or parcel, or the filing names another person (a builder) as owner; the phone goes with it | 269 | correct |
| the county office phone OCR'd from a bulk roster many rows share (`ocr_legal_notice`; Buncombe 137, Anderson 75) | 220 | correct |
| a filing phone on the filings of 3+ different owners: the filer's line (pool company, permit service) | 17 | correct |
| a phone identical on rows of different owners (`shared_copy`) | 15 | correct |
| not lost: the same property's other row on the checkpoint holds the phone (join pairing) | 11 | no loss |
| **D1** address normalizer: the row's own filing read as another address | 28 | bug, fixed |
| **D2** Lincoln AKPAR rows: the PIN copy was dropped, its phone with it | 19 | bug, fixed |
| **D4** scrub order: a person judged on a block removed in the same round | 6 | bug, fixed |
| lost with the row's resolver-attached parcel (identity changed between runs: Henderson PTS Cloud, divorce, UST rows) | 13 | merge-precedence family (regressions W3, landed after the run's pin; not re-verified here) |
| unresolved (a Buncombe row whose parcel changed format; a Lincoln code-violation row) | 2 | open |

1,045 correct removals, 11 non-losses, 53 phones lost by the three bugs below, 13 by the identity
family W3 already covers, 2 open.

## 3. Defects

| # | class | scale | cause | fix | test | invariant |
|---|---|---|---|---|---|---|
| D1 | a block for the row's own house read as another address | 28 good phones in the lost set; 164 LiensNC filings re-bind; on the checkpoint 1,404 of the 1,422 rows whose address ends in its own "CITY NC (ZIP)" read as another house than the same address without that tail | `verification.core.address_key` kept a comma-less city as a street word, did not know Mecklenburg's AV/BV/CR/WY/PY/TR/LP/HY, read a unit after the suffix and a route number after the city as street words; block_binding then removed the row's LiensNC filing (other_address) and the owner's phone as derived from it | `_drop_city_tail`, `_drop_unit_tail`, aliases (core.py) | `test_comma_less_city_state_zip_tail_is_not_part_of_the_street`, `test_av_is_avenue`, `test_a_different_house_still_conflicts...`, `test_the_owners_own_filing_phone_stays...` | `phones-address-tail-normalizer` (1,404 -> 11 on the checkpoint, max 15: streets with no suffix) |
| D2 | Lincoln delinquent-tax rows keyed by the county's short AKPAR id | 19 phones; 262 accounts on both a PIN row and a parcel-less row on the 10/7 board (188 on the checkpoint); 878 Lincoln nc_county_pdf rows on the checkpoint parcel-less although the bulk roll knows their PIN | validation nulls an id under 7 characters; `nc_lincoln_bulk` matched the AKPAR but never gave the row the PIN; the 10/7 run published a parcel-less copy beside the PIN row, the 10/8 run kept only the copy | `nc_lincoln_bulk.adopt_pin` (PIN + `raw.parcel_id_alias`); `parcel_alias.ALIAS_SOURCES` registers the source (county_id, Lincoln-length only: `SHORT_ID_MAX_LEN`, so McDowell/Catawba ids never become a second id) | `test_adopt_pin...`, `test_alias_source_registered_for_lincoln_akpar`, `test_the_next_scrape_folds_the_pin_row_and_keeps_its_phone` (merge_prior_board) | `phones-lincoln-akpar-unkeyed`, `phones-lincoln-akpar-duplicate` |
| D3 | a LiensNC filing's phone kept on rows of someone else | live board: 4,353 filing phones whose filing names an owner the county roll contradicts (was 17); 4,310 rows carry a filer's line; 8,190 rows in all (10.1% of the 81,294 phone rows; checkpoint 8,439) | the filing's phone block carries no name, so block_binding's person test never ran on it (it did on the same filing's mailing: 7,396 removed); the shared test skips filing blocks | `block_binding.filing_persons` (the owner the filing names), `filing_line_rows` (one number on the filings of 3+ owners with no owner on half: removed everywhere; a dominant owner keeps it on their rows only) | `test_a_filing_phone_that_names_the_builder...`, `..._on_its_own_liensnc_row...`, `test_one_filing_phone_on_rows_of_three_owners...`, `test_an_owner_and_their_company...`, `test_a_builder_line_stays...` | `phones-filing-line-shared`; `block-binding-d-other-person` now sees these too |
| D4 | person verdict taken from a block leaving in the same round | 6 phones (Buncombe STR permits) | `scrub_row` removed other_person blocks in the round that also removed the unbound block that made the row's owner look rolled | defer other_person one round (MAX_ROUNDS 3 -> 4) | `test_the_roll_owners_phone_stays...` | covered by the scrub tests (no board-level trace once removed) |

D3 is a correction in the other direction: the next scrub REMOVES about 8,200 filing phones (contractor
and builder numbers on homeowners' rows). The next comparison's `lost:phone` will exceed 1% for
this reason; an accepted-drops entry is needed (below).

## 4. Restoring the good phones (best-of-both)

`scripts/restore_best_of_both_phones.py` (streams the live board and the checkpoint, writes a NEW
checkpoint directory; never the input, docs/ or the VM): for each best-of-both phone entry it puts the
live `owner_phone` (and the LiensNC filing it came from) on the candidate row only when the current
rules keep it, the owner did not change, the number is no other owner's on the checkpoint, it is not
a filer's line and not a scrubbed roster's office number. On a Mac copy of the aa680fba checkpoint:
1,124 entries -> 67 restored (LiensNC filing 31, Lincoln taxpayer 21, Buncombe Accela 6, voter 9),
23 candidate already has a phone, 220 roster office numbers, 386 shared with another owner, 176
owner changed, 252 removed by the current rules. Output 383,378 rows (= manifest), marked
`owner_phone.restored`. Not run on the VM (read-only for this audit).

## 5. Open items

- Accepted drop for D3 on the next comparison: `field phone`, reason "block_binding filing contacts
  (filing names another owner; filer's line)", bound 9,500 (8,190 measured on 10/7, 8,439 on aa680fba).
  Owner decision whether builder phones on builder-owned lots stay (they do: dominant owner rule).
- 13 phones of the W3 identity family and 2 unresolved rows: not re-verified after the W3 fix.
- 11 suffix-less street addresses still read the city as a street word (no way to tell them apart).

## 6. Outside this area (one line each)

- Henderson `nc_ptscloud_delinquent_tax`: on 26 lost-phone rows the live row's resolved parcel names an
  owner other than the fresh roll taxpayer (6 read by hand, all differ); W3's "prior valid parcel wins" may re-attach another property to those rows.
- LiensNC `address` fields with a lot description on line 1 and the street on line 2 are read as one
  street by address_key (up to 93 live rows whose own filing conflicts with them; sampled 15, all
  lot descriptions).
- The live board publishes 262 Lincoln delinquent-tax accounts twice (PIN row + parcel-less row).
