# Accepted drops: what the comparison may stop holding on, and why

Source: the comparison of the reconciled board (pin aa680fba, 383,378 rows) with the live 10/7 board
(350,013), 2026-10-09 (`logs/compare-20261009T023221.md` on the VM): HOLD, 38 blockers. Every blocker
is classified below as (a) intended correction, (b) real loss / defect to fix, or (c) tool artefact.

The (a) entries live in `docs/board_versions/accepted_drops.json`, which `scripts/compare_boards.py`
reads by default whenever the baseline is the live board (`--accept-file` names another,
`--no-accept-file` ignores it). Each entry carries its reason and a BOUND (`max_loss`, about 15% above
the observed loss): a larger loss of the same column still blocks. Command-line equivalents:

```
--accept-coverage-drop lt_lis_pendens --accept-coverage-drop multi_year_delinquent_tax
--accept-coverage-drop sc_state_tax_lien --accept-coverage-drop tax_aging_surfaced
--accept-coverage-drop x_tax_balance --accept-coverage-drop x_tax_years_late
--accept-coverage-drop atty_legal_description --accept-coverage-drop atty_deed_ref
--accept-coverage-drop atty_taxpayer_of_record
--accept-field-loss tax_balance --accept-field-loss tax_years --accept-field-loss tax_levy_year
--accept-field-loss mailing_address
```
(the flags are unbounded; prefer the file).

Proof counts: the reconcile log (`tax_owed.done`: unbound_rows 19,570, unbound_blocks 19,602;
`verification_apply.applied`: tax_lien refuted 751, stale 1,522), block_binding's scrub measured on
the 10/7 board (docs/audit_2026-10-09/block_binding.md: 42,618 rows, 63,702 blocks), court_signals D5.

## (a) intended corrections: 23 blockers

| blocker(s) | observed loss | proof | bound |
|---|---|---|---|
| coverage lt_lis_pendens (ALL, NC) | 8,072 rows in both | 6,511 NC claims of lien + 1,436 transcripts of judgment reclassified (court_signals D5) = 7,947 | 9,000 |
| coverage multi_year_delinquent_tax (ALL, NC, SC) | 3,167 | the block is parcel-bound (tax_binding); tax scrub 19,602 blocks | 3,600 |
| coverage sc_state_tax_lien (ALL, SC) | 3,033 | block_binding: another person's (business) state lien removed from 3,035 rows | 3,500 |
| coverage tax_aging_surfaced (ALL, NC, SC) | 11,004 | derived from tax_owed: tax scrub 19,570 rows + verification 2,273 | 12,500 |
| coverage x_tax_balance (ALL, NC, SC) | 11,021 | tax scrub + verification, as above | 12,500 |
| coverage x_tax_years_late (SC) | 3,737 | tax scrub, as above | 4,300 |
| coverage atty_legal_description (ALL, SC) | 429 HOT+WARM rows | block_binding: gis_attrs_full other_parcel 2,839, fallback_point 1,434; gis fallback 1,411 | 600 |
| coverage atty_deed_ref (ALL, SC) | 192 HOT+WARM rows | block_binding: deed_chain fallback_point 4,813, shared_copy 1,120 | 300 |
| coverage atty_taxpayer_of_record (SC) | 1,004 | block_binding: owner_mailing other_person 7,396, other_parcel 2,892; cama 1,414 | 1,200 (SC) |
| field tax_balance / tax_years / tax_levy_year | 13,029 / 5,121 / 9,097 | tax scrub 19,570 rows + verification 2,273 | 15,000 / 6,000 / 10,500 |
| field mailing_address | 13,343 | block_binding owner_mailing removals 12,808 (other_person, other_parcel, other_address) | 15,000 |

## (b) real losses or defects: 15 blockers

| blocker | cause | fix |
|---|---|---|
| source rutherford_tax 5,109 -> 4,563 held | dedupe fused 580 roll rows on the roll URL (carryover replay) | FIXED in HEAD (145ae136, regressions R1); takes effect on the next run |
| regressions-roll-records-kept (3), regressions-source-held (1) | the same fusion (rutherford_tax, PTS Cloud) and multi_year attribution lost to the one-entry-per-URL merge | FIXED in HEAD (R1, R2) |
| coverage NC comps (HOT+WARM on both, 120 rows), field comps 1,226 | comps not carried when a row's identity changed between runs (462 properties) + validation drops after a kind change (370, correct) | the valuation area's comps carry-forward (enrichment_comps); comps loop to take new and HOT/WARM rows first |
| field phone 1,124 | block_binding removed 774 phones (owner_phone other_person 402, derived 372); 350 are not explained by any count | NOT accepted: check the 350 rows (sample from the report's best-of-both list) before the next publish |
| tax-claim-has-checker 1,129 -> 21,506 | the reconcile stamped 124,021 tax claims; most counties have no county-site checker yet | the tax_checkers area (its threshold was set on the old board) |
| additions-alias-is-pin 53, addition-apr-homepath-reo-only 1, docs-processed-has-ledger-entry 100, docs-ocr-tax-not-judgment 1, drops-situs-road-nulled 82, pipeline-countyless-national 18, source-county-floor 5, unwired-bt-card-applied 1 | defects of the pinned run's code; each area's report says its fix landed after the pin (not re-verified here) | the owning areas; they clear only on a run of the fixed code |

## (c) tool artefacts: 0

The artefacts of the 10/8 comparison (relabels read as loss, short ids read as missing, HOT+WARM tier
churn read as coverage loss) were fixed in compare_boards before this run of it.
