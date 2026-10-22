# Built-but-low-yield work queue

Generated from `gap_list_2026-10-22.csv`. Regenerate with `python scripts/low_yield_queue.py` any time the gap list changes -- this file is a derived view, not hand-maintained.

Every row here already has a working reader/enrichment/verifier -- the gap is coverage, not code. `next_action` names the existing script/sweep to run; `check-before-building` still applies if the next_action text is wrong or stale (it's a heuristic guess, not ground truth) -- confirm what's actually wired before assuming a rewrite is needed.

**6,500 cells, 8,388,391 total est_rows_affected.**

## Top 150 by est_rows_affected

| state | county | column | pct done | est_rows left | next_action |
|---|---|---|---|---|---|
| NC | Gaston | tax_aging_surfaced | 0.0% | 26,619 | screen the 26,619 unchecked rows (enrichment_tax_aging); write a negative result per row |
| NC | Gaston | atty_deed_ref | 1.5% | 26,209 | backfill atty_deed_ref for the 26,209 applicable rows without it (existing enrichers) |
| NC | Gaston | liens | 2.6% | 25,915 | screen the 25,915 unchecked rows (enrichment_dew_liens, enrichment_irs_lien); write a negative result per row |
| NC | Gaston | atty_rod_lien_checked | 2.7% | 25,896 | backfill atty_rod_lien_checked for the 25,896 applicable rows without it (enrichment_aumentum_rod, enrichment_cchs_rod) |
| NC | Gaston | code_enforcement | 5.6% | 25,129 | screen the 25,129 unchecked rows (enrichment_code_enforcement, enrichment_charlotte_code); write a negative result per r |
| NC | Gaston | atty_taxpayer_of_record | 7.7% | 24,564 | backfill atty_taxpayer_of_record for the 24,564 applicable rows without it (parcel_cache, enrichment_qpaybill_tax) |
| NC | Gaston | email | 4.5% | 24,408 | no free owner-email source: e-mails come only from notices and filings; research a lawful source |
| NC | Gaston | phone | 18.4% | 20,845 | backfill phone for the 20,845 applicable rows without it (existing enrichers) |
| SC | Spartanburg | phone | 0.0% | 19,191 | backfill phone for the 19,191 applicable rows without it (existing enrichers) |
| SC | Spartanburg | liens | 2.9% | 18,822 | screen the 18,822 unchecked rows (enrichment_dew_liens, enrichment_irs_lien); write a negative result per row |
| SC | Spartanburg | atty_rod_lien_checked | 3.0% | 18,809 | backfill atty_rod_lien_checked for the 18,809 applicable rows without it (enrichment_aumentum_rod, enrichment_cchs_rod) |
| NC | Lincoln | liens | 0.0% | 18,668 | screen the 18,668 unchecked rows (enrichment_dew_liens, enrichment_irs_lien); write a negative result per row |
| NC | Lincoln | atty_rod_lien_checked | 0.1% | 18,662 | backfill atty_rod_lien_checked for the 18,662 applicable rows without it (enrichment_aumentum_rod, enrichment_cchs_rod) |
| NC | Lincoln | code_enforcement | 0.4% | 18,606 | screen the 18,606 unchecked rows (enrichment_code_enforcement, enrichment_charlotte_code); write a negative result per r |
| NC | Mecklenburg | atty_rod_lien_checked | 0.0% | 18,552 | backfill atty_rod_lien_checked for the 18,552 applicable rows without it (enrichment_aumentum_rod, enrichment_cchs_rod) |
| NC | Mecklenburg | liens | 0.0% | 18,552 | screen the 18,552 unchecked rows (enrichment_dew_liens, enrichment_irs_lien); write a negative result per row |
| NC | Mecklenburg | repeat_tax_loss | 0.0% | 18,552 | 18,552 rows lack the inputs repeat_tax_loss is computed from: fill the inputs, then recompute |
| NC | Mecklenburg | rollback_exposure | 0.0% | 18,552 | code covers this county (enrichment_rollback_deferral, enrichment_tax_relief) but nothing landed here: run it for this c |
| SC | Spartanburg | multi_year_delinquent_tax | 4.7% | 18,475 | screen the 18,475 unchecked rows (enrichment_tax_owed, multi_year_delinquent_tax); write a negative result per row |
| SC | Spartanburg | code_enforcement | 4.8% | 18,447 | screen the 18,447 unchecked rows (enrichment_code_enforcement, enrichment_charlotte_code); write a negative result per r |
| NC | Lincoln | two_year_delinquent | 1.9% | 18,325 | screen the 18,325 unchecked rows (albemarle_observer_tax_lists, nc_its_public_tax); write a negative result per row |
| SC | Spartanburg | atty_legal_description | 6.7% | 18,078 | backfill atty_legal_description for the 18,078 applicable rows without it (existing enrichers) |
| NC | Gaston | atty_deed_chain_fetched | 32.2% | 18,037 | backfill atty_deed_chain_fetched for the 18,037 applicable rows without it (enrichment_deed_chain) |
| NC | Gaston | deed_chain_break | 32.2% | 18,037 | 18,037 rows lack the inputs deed_chain_break is computed from: fill the inputs, then recompute |
| NC | Gaston | deed_chain_distress_transfer | 32.2% | 18,037 | 18,037 rows lack the inputs deed_chain_distress_transfer is computed from: fill the inputs, then recompute |
| NC | Gaston | deed_chain_has_history | 32.2% | 18,037 | backfill deed_chain_has_history for the 18,037 applicable rows without it (enrichment_deed_chain) |
| NC | Mecklenburg | atty_deed_ref | 3.5% | 17,900 | backfill atty_deed_ref for the 17,900 applicable rows without it (existing enrichers) |
| NC | Lincoln | email | 2.6% | 17,890 | no free owner-email source: e-mails come only from notices and filings; research a lawful source |
| NC | Mecklenburg | atty_legal_description | 4.1% | 17,788 | backfill atty_legal_description for the 17,788 applicable rows without it (existing enrichers) |
| NC | Mecklenburg | atty_deed_chain_fetched | 5.0% | 17,630 | backfill atty_deed_chain_fetched for the 17,630 applicable rows without it (enrichment_deed_chain) |
| NC | Mecklenburg | deed_chain_break | 5.0% | 17,630 | 17,630 rows lack the inputs deed_chain_break is computed from: fill the inputs, then recompute |
| NC | Mecklenburg | deed_chain_distress_transfer | 5.0% | 17,630 | 17,630 rows lack the inputs deed_chain_distress_transfer is computed from: fill the inputs, then recompute |
| NC | Mecklenburg | deed_chain_has_history | 5.0% | 17,630 | backfill deed_chain_has_history for the 17,630 applicable rows without it (enrichment_deed_chain) |
| NC | Lincoln | vacant_lot | 6.2% | 17,509 | 17,509 rows lack the inputs vacant_lot is computed from: fill the inputs, then recompute |
| NC | Mecklenburg | atty_taxpayer_of_record | 6.0% | 17,433 | backfill atty_taxpayer_of_record for the 17,433 applicable rows without it (parcel_cache, enrichment_qpaybill_tax) |
| NC | Lincoln | parcel_id | 6.9% | 17,391 | backfill parcel_id for the 17,391 applicable rows without it (existing enrichers) |
| NC | Lincoln | atty_legal_description | 7.0% | 17,363 | backfill atty_legal_description for the 17,363 applicable rows without it (existing enrichers) |
| NC | Lincoln | tax_aging_surfaced | 8.6% | 17,064 | screen the 17,064 unchecked rows (enrichment_tax_aging); write a negative result per row |
| NC | Lincoln | repeat_tax_loss | 9.7% | 16,864 | 16,864 rows lack the inputs repeat_tax_loss is computed from: fill the inputs, then recompute |
| SC | Spartanburg | tax_aging_surfaced | 18.9% | 15,723 | screen the 15,723 unchecked rows (enrichment_tax_aging); write a negative result per row |
| SC | Spartanburg | atty_deed_ref | 21.7% | 15,169 | backfill atty_deed_ref for the 15,169 applicable rows without it (existing enrichers) |
| NC | Mecklenburg | code_enforcement | 18.8% | 15,063 | screen the 15,063 unchecked rows (enrichment_code_enforcement, enrichment_charlotte_code); write a negative result per r |
| NC | Lincoln | divorce | 0.0% | 14,330 | screen the 14,330 unchecked rows (enrichment_nc_divorce, enrichment_sc_divorce); write a negative result per row |
| NC | Lincoln | bop_federal | 0.0% | 14,329 | screen the 14,329 unchecked rows (enrichment_bop_federal); write a negative result per row |
| NC | Lincoln | incarceration | 0.1% | 14,318 | screen the 14,318 unchecked rows (enrichment_incarceration); write a negative result per row |
| NC | Lincoln | marriage_license | 0.1% | 14,310 | screen the 14,310 unchecked rows (enrichment_register_checks, register_checks); write a negative result per row |
| NC | Gaston | bop_federal | 0.0% | 14,061 | screen the 14,061 unchecked rows (enrichment_bop_federal); write a negative result per row |
| NC | Gaston | divorce | 0.0% | 14,061 | screen the 14,061 unchecked rows (enrichment_nc_divorce, enrichment_sc_divorce); write a negative result per row |
| NC | Gaston | jail_booking_new | 0.0% | 14,061 | code covers this county (enrichment_jail_bookings) but nothing landed here: run it for this county and stamp 'screened,  |
| NC | Gaston | incarceration | 0.1% | 14,042 | screen the 14,042 unchecked rows (enrichment_incarceration); write a negative result per row |
| NC | Gaston | marriage_license | 0.3% | 14,024 | screen the 14,024 unchecked rows (enrichment_register_checks, register_checks); write a negative result per row |
| SC | Spartanburg | atty_deed_chain_fetched | 27.9% | 13,983 | backfill atty_deed_chain_fetched for the 13,983 applicable rows without it (enrichment_deed_chain) |
| SC | Spartanburg | deed_chain_break | 27.9% | 13,983 | 13,983 rows lack the inputs deed_chain_break is computed from: fill the inputs, then recompute |
| SC | Spartanburg | deed_chain_distress_transfer | 27.9% | 13,983 | 13,983 rows lack the inputs deed_chain_distress_transfer is computed from: fill the inputs, then recompute |
| SC | Spartanburg | deed_chain_has_history | 27.9% | 13,983 | backfill deed_chain_has_history for the 13,983 applicable rows without it (enrichment_deed_chain) |
| SC | Spartanburg | bop_federal | 0.0% | 13,848 | screen the 13,848 unchecked rows (enrichment_bop_federal); write a negative result per row |
| SC | Spartanburg | incarceration | 0.2% | 13,830 | screen the 13,830 unchecked rows (enrichment_incarceration); write a negative result per row |
| NC | Mecklenburg | phone | 25.4% | 13,754 | backfill phone for the 13,754 applicable rows without it (existing enrichers) |
| NC | Mecklenburg | comps_tight | 0.0% | 13,239 | backfill comps_tight for the 13,239 applicable rows without it (existing enrichers) |
| NC | Lincoln | phone | 29.0% | 13,040 | backfill phone for the 13,040 applicable rows without it (existing enrichers) |
| NC | Mecklenburg | sqft | 1.7% | 13,022 | backfill sqft for the 13,022 applicable rows without it (existing enrichers) |
| NC | Mecklenburg | beds_baths | 1.7% | 13,019 | backfill beds_baths for the 13,019 applicable rows without it (existing enrichers) |
| NC | Mecklenburg | comps | 1.9% | 12,996 | backfill comps for the 12,996 applicable rows without it (existing enrichers) |
| NC | Wake | rollback_exposure | 0.0% | 12,941 | code covers this county (enrichment_rollback_deferral, enrichment_tax_relief) but nothing landed here: run it for this c |
| NC | Wake | two_year_delinquent | 0.0% | 12,940 | screen the 12,940 unchecked rows (albemarle_observer_tax_lists, nc_its_public_tax); write a negative result per row |
| NC | Wake | multi_year_delinquent_tax | 0.0% | 12,937 | screen the 12,937 unchecked rows (enrichment_tax_owed, multi_year_delinquent_tax); write a negative result per row |
| NC | Wake | tax_aging_surfaced | 0.0% | 12,937 | screen the 12,937 unchecked rows (enrichment_tax_aging); write a negative result per row |
| NC | Wake | repeat_tax_loss | 0.0% | 12,936 | 12,936 rows lack the inputs repeat_tax_loss is computed from: fill the inputs, then recompute |
| NC | Wake | atty_deed_ref | 1.2% | 12,779 | backfill atty_deed_ref for the 12,779 applicable rows without it (existing enrichers) |
| NC | Mecklenburg | assessed_value | 31.7% | 12,670 | backfill assessed_value for the 12,670 applicable rows without it (existing enrichers) |
| NC | Transylvania | liens | 0.1% | 12,440 | screen the 12,440 unchecked rows (enrichment_dew_liens, enrichment_irs_lien); write a negative result per row |
| NC | Buncombe | code_enforcement | 0.0% | 12,436 | screen the 12,436 unchecked rows (enrichment_code_enforcement, enrichment_charlotte_code); write a negative result per r |
| NC | Mecklenburg | email | 32.6% | 12,416 | no free owner-email source: e-mails come only from notices and filings; research a lawful source |
| NC | Transylvania | atty_rod_lien_checked | 0.4% | 12,412 | backfill atty_rod_lien_checked for the 12,412 applicable rows without it (enrichment_aumentum_rod, enrichment_cchs_rod) |
| NC | Wake | comps_tight | 0.0% | 12,392 | backfill comps_tight for the 12,392 applicable rows without it (existing enrichers) |
| NC | Wake | atty_legal_description | 4.3% | 12,388 | backfill atty_legal_description for the 12,388 applicable rows without it (existing enrichers) |
| NC | Wake | atty_taxpayer_of_record | 5.0% | 12,294 | backfill atty_taxpayer_of_record for the 12,294 applicable rows without it (parcel_cache, enrichment_qpaybill_tax) |
| NC | Guilford | atty_rod_lien_checked | 0.1% | 12,266 | backfill atty_rod_lien_checked for the 12,266 applicable rows without it (enrichment_aumentum_rod, enrichment_cchs_rod) |
| NC | Guilford | liens | 0.1% | 12,266 | screen the 12,266 unchecked rows (enrichment_dew_liens, enrichment_irs_lien); write a negative result per row |
| NC | Wake | comps | 1.2% | 12,246 | backfill comps for the 12,246 applicable rows without it (existing enrichers) |
| NC | Wake | beds_baths | 1.2% | 12,243 | backfill beds_baths for the 12,243 applicable rows without it (existing enrichers) |
| NC | Guilford | multi_year_delinquent_tax | 0.3% | 12,241 | screen the 12,241 unchecked rows (enrichment_tax_owed, multi_year_delinquent_tax); write a negative result per row |
| NC | Wake | sqft | 1.2% | 12,241 | backfill sqft for the 12,241 applicable rows without it (existing enrichers) |
| NC | Guilford | two_year_delinquent | 0.6% | 12,209 | screen the 12,209 unchecked rows (albemarle_observer_tax_lists, nc_its_public_tax); write a negative result per row |
| NC | Guilford | atty_deed_ref | 1.4% | 12,098 | backfill atty_deed_ref for the 12,098 applicable rows without it (existing enrichers) |
| NC | Transylvania | email | 1.5% | 12,098 | no free owner-email source: e-mails come only from notices and filings; research a lawful source |
| NC | Mecklenburg | bop_federal | 0.0% | 11,886 | screen the 11,886 unchecked rows (enrichment_bop_federal); write a negative result per row |
| NC | Mecklenburg | divorce | 0.0% | 11,886 | screen the 11,886 unchecked rows (enrichment_nc_divorce, enrichment_sc_divorce); write a negative result per row |
| NC | Mecklenburg | incarceration | 0.0% | 11,886 | screen the 11,886 unchecked rows (enrichment_incarceration); write a negative result per row |
| NC | Transylvania | atty_deed_ref | 4.6% | 11,882 | backfill atty_deed_ref for the 11,882 applicable rows without it (existing enrichers) |
| NC | Mecklenburg | marriage_license | 0.2% | 11,862 | screen the 11,862 unchecked rows (enrichment_register_checks, register_checks); write a negative result per row |
| NC | Transylvania | repeat_tax_loss | 5.2% | 11,815 | 11,815 rows lack the inputs repeat_tax_loss is computed from: fill the inputs, then recompute |
| NC | Buncombe | multi_year_delinquent_tax | 6.0% | 11,685 | screen the 11,685 unchecked rows (enrichment_tax_owed, multi_year_delinquent_tax); write a negative result per row |
| NC | Guilford | code_enforcement | 5.1% | 11,649 | screen the 11,649 unchecked rows (enrichment_code_enforcement, enrichment_charlotte_code); write a negative result per r |
| NC | Wake | atty_deed_chain_fetched | 10.5% | 11,578 | backfill atty_deed_chain_fetched for the 11,578 applicable rows without it (enrichment_deed_chain) |
| NC | Wake | deed_chain_break | 10.5% | 11,578 | 11,578 rows lack the inputs deed_chain_break is computed from: fill the inputs, then recompute |
| NC | Wake | deed_chain_distress_transfer | 10.5% | 11,578 | 11,578 rows lack the inputs deed_chain_distress_transfer is computed from: fill the inputs, then recompute |
| NC | Wake | deed_chain_has_history | 10.5% | 11,578 | backfill deed_chain_has_history for the 11,578 applicable rows without it (enrichment_deed_chain) |
| NC | Guilford | atty_deed_chain_fetched | 5.7% | 11,572 | backfill atty_deed_chain_fetched for the 11,572 applicable rows without it (enrichment_deed_chain) |
| NC | Guilford | deed_chain_break | 5.7% | 11,572 | 11,572 rows lack the inputs deed_chain_break is computed from: fill the inputs, then recompute |
| NC | Guilford | deed_chain_distress_transfer | 5.7% | 11,572 | 11,572 rows lack the inputs deed_chain_distress_transfer is computed from: fill the inputs, then recompute |
| NC | Guilford | deed_chain_has_history | 5.7% | 11,572 | backfill deed_chain_has_history for the 11,572 applicable rows without it (enrichment_deed_chain) |
| NC | Buncombe | atty_legal_description | 8.1% | 11,431 | backfill atty_legal_description for the 11,431 applicable rows without it (existing enrichers) |
| SC | Spartanburg | two_year_delinquent | 41.6% | 11,318 | screen the 11,318 unchecked rows (albemarle_observer_tax_lists, nc_its_public_tax); write a negative result per row |
| NC | Mecklenburg | vacant_lot | 39.0% | 11,308 | 11,308 rows lack the inputs vacant_lot is computed from: fill the inputs, then recompute |
| NC | Buncombe | tax_aging_surfaced | 9.4% | 11,265 | screen the 11,265 unchecked rows (enrichment_tax_aging); write a negative result per row |
| NC | Transylvania | atty_taxpayer_of_record | 10.1% | 11,205 | backfill atty_taxpayer_of_record for the 11,205 applicable rows without it (parcel_cache, enrichment_qpaybill_tax) |
| NC | Mecklenburg | lot_size | 40.1% | 11,109 | backfill lot_size for the 11,109 applicable rows without it (existing enrichers) |
| SC | Charleston | atty_deed_ref | 2.0% | 10,980 | backfill atty_deed_ref for the 10,980 applicable rows without it (existing enrichers) |
| NC | Guilford | phone | 9.5% | 10,950 | backfill phone for the 10,950 applicable rows without it (existing enrichers) |
| NC | Buncombe | email | 11.1% | 10,913 | no free owner-email source: e-mails come only from notices and filings; research a lawful source |
| NC | Mecklenburg | parcel_id | 41.7% | 10,817 | backfill parcel_id for the 10,817 applicable rows without it (existing enrichers) |
| NC | Forsyth | atty_rod_lien_checked | 0.1% | 10,679 | backfill atty_rod_lien_checked for the 10,679 applicable rows without it (enrichment_aumentum_rod, enrichment_cchs_rod) |
| NC | Forsyth | liens | 0.1% | 10,679 | screen the 10,679 unchecked rows (enrichment_dew_liens, enrichment_irs_lien); write a negative result per row |
| NC | Rutherford | email | 2.9% | 10,649 | no free owner-email source: e-mails come only from notices and filings; research a lawful source |
| NC | Guilford | vacant_lot | 14.0% | 10,562 | 10,562 rows lack the inputs vacant_lot is computed from: fill the inputs, then recompute |
| NC | Forsyth | atty_deed_ref | 1.4% | 10,535 | backfill atty_deed_ref for the 10,535 applicable rows without it (existing enrichers) |
| NC | Guilford | email | 13.2% | 10,512 | no free owner-email source: e-mails come only from notices and filings; research a lawful source |
| SC | Charleston | atty_legal_description | 6.8% | 10,449 | backfill atty_legal_description for the 10,449 applicable rows without it (existing enrichers) |
| NC | Buncombe | comps_tight | 5.4% | 10,290 | backfill comps_tight for the 10,290 applicable rows without it (existing enrichers) |
| NC | Buncombe | divorce | 0.0% | 10,165 | screen the 10,165 unchecked rows (enrichment_nc_divorce, enrichment_sc_divorce); write a negative result per row |
| NC | Guilford | parcel_id | 17.3% | 10,151 | backfill parcel_id for the 10,151 applicable rows without it (existing enrichers) |
| NC | Buncombe | incarceration | 0.3% | 10,133 | screen the 10,133 unchecked rows (enrichment_incarceration); write a negative result per row |
| NC | Buncombe | marriage_license | 0.6% | 10,105 | screen the 10,105 unchecked rows (enrichment_register_checks, register_checks); write a negative result per row |
| NC | Forsyth | atty_deed_chain_fetched | 6.7% | 9,970 | backfill atty_deed_chain_fetched for the 9,970 applicable rows without it (enrichment_deed_chain) |
| NC | Forsyth | deed_chain_break | 6.7% | 9,970 | 9,970 rows lack the inputs deed_chain_break is computed from: fill the inputs, then recompute |
| NC | Forsyth | deed_chain_distress_transfer | 6.7% | 9,970 | 9,970 rows lack the inputs deed_chain_distress_transfer is computed from: fill the inputs, then recompute |
| NC | Forsyth | deed_chain_has_history | 6.7% | 9,970 | backfill deed_chain_has_history for the 9,970 applicable rows without it (enrichment_deed_chain) |
| NC | Buncombe | bop_federal | 2.1% | 9,954 | screen the 9,954 unchecked rows (enrichment_bop_federal); write a negative result per row |
| NC | Rutherford | atty_deed_ref | 9.8% | 9,937 | backfill atty_deed_ref for the 9,937 applicable rows without it (existing enrichers) |
| NC | Buncombe | beds_baths | 8.7% | 9,933 | backfill beds_baths for the 9,933 applicable rows without it (existing enrichers) |
| SC | Spartanburg | repeat_tax_loss | 48.9% | 9,899 | 9,899 rows lack the inputs repeat_tax_loss is computed from: fill the inputs, then recompute |
| SC | Charleston | comps_tight | 0.1% | 9,788 | backfill comps_tight for the 9,788 applicable rows without it (existing enrichers) |
| NC | Transylvania | bop_federal | 0.0% | 9,769 | screen the 9,769 unchecked rows (enrichment_bop_federal); write a negative result per row |
| NC | Transylvania | divorce | 0.0% | 9,769 | screen the 9,769 unchecked rows (enrichment_nc_divorce, enrichment_sc_divorce); write a negative result per row |
| NC | Transylvania | jail_booking_new | 0.0% | 9,769 | code covers this county (enrichment_jail_bookings) but nothing landed here: run it for this county and stamp 'screened,  |
| NC | Transylvania | marriage_license | 0.1% | 9,761 | screen the 9,761 unchecked rows (enrichment_register_checks, register_checks); write a negative result per row |
| NC | Transylvania | incarceration | 0.1% | 9,760 | screen the 9,760 unchecked rows (enrichment_incarceration); write a negative result per row |
| SC | Charleston | comps | 0.8% | 9,714 | backfill comps for the 9,714 applicable rows without it (existing enrichers) |
| NC | Transylvania | phone | 21.0% | 9,703 | backfill phone for the 9,703 applicable rows without it (existing enrichers) |
| SC | Charleston | beds_baths | 1.1% | 9,684 | backfill beds_baths for the 9,684 applicable rows without it (existing enrichers) |
| SC | Spartanburg | lot_size | 50.4% | 9,620 | backfill lot_size for the 9,620 applicable rows without it (existing enrichers) |
| SC | Spartanburg | comps_tight | 12.8% | 9,583 | backfill comps_tight for the 9,583 applicable rows without it (existing enrichers) |
| SC | Spartanburg | atty_taxpayer_of_record | 50.6% | 9,565 | backfill atty_taxpayer_of_record for the 9,565 applicable rows without it (parcel_cache, enrichment_qpaybill_tax) |
| NC | Rutherford | atty_tax_verified_confirmed | 4.9% | 9,544 | screen the 9,544 unchecked rows (existing enrichers); write a negative result per row |
| NC | Forsyth | phone | 11.6% | 9,339 | backfill phone for the 9,339 applicable rows without it (existing enrichers) |
| NC | Rutherford | divorce | 0.0% | 9,279 | screen the 9,279 unchecked rows (enrichment_nc_divorce, enrichment_sc_divorce); write a negative result per row |
| NC | Rutherford | bop_federal | 0.1% | 9,271 | screen the 9,271 unchecked rows (enrichment_bop_federal); write a negative result per row |
| NC | Rutherford | incarceration | 0.2% | 9,263 | screen the 9,263 unchecked rows (enrichment_incarceration); write a negative result per row |
| NC | Brunswick | atty_rod_lien_checked | 0.0% | 9,223 | backfill atty_rod_lien_checked for the 9,223 applicable rows without it (enrichment_aumentum_rod, enrichment_cchs_rod) |

## Rolled up by column (which existing readers have the most unswept rows)

| column | cells | total est_rows_affected |
|---|---|---|
| atty_deed_ref | 126 | 365,971 |
| atty_deed_chain_fetched | 148 | 316,036 |
| deed_chain_break | 148 | 316,036 |
| deed_chain_distress_transfer | 148 | 316,036 |
| deed_chain_has_history | 148 | 316,036 |
| atty_legal_description | 138 | 311,947 |
| bop_federal | 148 | 311,351 |
| incarceration | 148 | 310,934 |
| atty_rod_lien_checked | 93 | 282,763 |
| tax_aging_surfaced | 139 | 277,648 |
| phone | 104 | 271,975 |
| comps_tight | 149 | 271,351 |
| liens | 89 | 263,749 |
| email | 102 | 262,181 |
| vacant_lot | 120 | 260,484 |
| beds_baths | 141 | 249,647 |
| repeat_tax_loss | 137 | 248,571 |
| divorce | 115 | 244,869 |
| comps | 149 | 235,405 |
| assessed_value | 135 | 231,797 |
| atty_taxpayer_of_record | 146 | 219,334 |
| lot_size | 140 | 212,744 |
| two_year_delinquent | 133 | 207,379 |
| sqft | 143 | 202,051 |
| multi_year_delinquent_tax | 104 | 199,103 |
| marriage_license | 100 | 196,464 |
| parcel_id | 145 | 193,297 |
| address | 148 | 134,431 |
| atty_tax_verified_confirmed | 62 | 131,189 |
| code_enforcement | 13 | 118,510 |
| lt_tax_lien | 106 | 77,427 |
| sos_dissolution | 102 | 63,018 |
| heir_estate | 111 | 51,679 |
| jail_booking_new | 12 | 44,941 |
| name_care_of | 148 | 43,628 |
| name_deceased | 148 | 43,628 |
| name_estate_of | 148 | 43,628 |
| name_et_al | 148 | 43,628 |
| name_heirs | 148 | 43,628 |
| name_life_estate | 148 | 43,628 |
