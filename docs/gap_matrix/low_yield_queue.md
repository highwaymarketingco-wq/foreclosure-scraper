# Built-but-low-yield work queue

Generated from `gap_list_2026-10-22.csv`. Regenerate with `python scripts/low_yield_queue.py` any time the gap list changes -- this file is a derived view, not hand-maintained.

Every row here already has a working reader/enrichment/verifier -- the gap is coverage, not code. `next_action` names the existing script/sweep to run; `check-before-building` still applies if the next_action text is wrong or stale (it's a heuristic guess, not ground truth) -- confirm what's actually wired before assuming a rewrite is needed.

**6,493 cells, 8,409,574 total est_rows_affected.**

## Top 150 by est_rows_affected

| state | county | column | pct done | est_rows left | next_action |
|---|---|---|---|---|---|
| NC | Gaston | tax_aging_surfaced | 0.0% | 26,619 | screen the 26,619 unchecked rows (enrichment_tax_aging); write a negative result per row |
| NC | Gaston | atty_deed_ref | 1.5% | 26,209 | backfill atty_deed_ref for the 26,209 applicable rows without it (existing enrichers) |
| NC | Gaston | liens | 2.6% | 25,915 | screen the 25,915 unchecked rows (enrichment_dew_liens, enrichment_irs_lien); write a negative result per row |
| NC | Gaston | atty_rod_lien_checked | 2.7% | 25,896 | backfill atty_rod_lien_checked for the 25,896 applicable rows without it (enrichment_aumentum_rod, enrichment_cchs_rod) |
| NC | Gaston | code_enforcement | 5.6% | 25,129 | screen the 25,129 unchecked rows (enrichment_code_enforcement, enrichment_charlotte_code); write a negative result per r |
| NC | Gaston | email | 4.5% | 24,408 | no free owner-email source: e-mails come only from notices and filings; research a lawful source |
| NC | Gaston | phone | 18.4% | 20,845 | backfill phone for the 20,845 applicable rows without it (existing enrichers) |
| SC | Spartanburg | phone | 0.0% | 19,191 | backfill phone for the 19,191 applicable rows without it (existing enrichers) |
| NC | Lincoln | liens | 0.0% | 18,836 | screen the 18,836 unchecked rows (enrichment_dew_liens, enrichment_irs_lien); write a negative result per row |
| NC | Lincoln | atty_rod_lien_checked | 0.1% | 18,830 | backfill atty_rod_lien_checked for the 18,830 applicable rows without it (enrichment_aumentum_rod, enrichment_cchs_rod) |
| SC | Spartanburg | liens | 2.9% | 18,822 | screen the 18,822 unchecked rows (enrichment_dew_liens, enrichment_irs_lien); write a negative result per row |
| SC | Spartanburg | atty_rod_lien_checked | 3.0% | 18,809 | backfill atty_rod_lien_checked for the 18,809 applicable rows without it (enrichment_aumentum_rod, enrichment_cchs_rod) |
| NC | Lincoln | code_enforcement | 0.4% | 18,774 | screen the 18,774 unchecked rows (enrichment_code_enforcement, enrichment_charlotte_code); write a negative result per r |
| NC | Mecklenburg | atty_rod_lien_checked | 0.0% | 18,552 | backfill atty_rod_lien_checked for the 18,552 applicable rows without it (enrichment_aumentum_rod, enrichment_cchs_rod) |
| NC | Mecklenburg | liens | 0.0% | 18,552 | screen the 18,552 unchecked rows (enrichment_dew_liens, enrichment_irs_lien); write a negative result per row |
| NC | Mecklenburg | repeat_tax_loss | 0.0% | 18,552 | 18,552 rows lack the inputs repeat_tax_loss is computed from: fill the inputs, then recompute |
| NC | Lincoln | two_year_delinquent | 1.9% | 18,493 | screen the 18,493 unchecked rows (albemarle_observer_tax_lists, nc_its_public_tax); write a negative result per row |
| NC | Mecklenburg | atty_deed_chain_fetched | 0.3% | 18,490 | backfill atty_deed_chain_fetched for the 18,490 applicable rows without it (enrichment_deed_chain) |
| NC | Mecklenburg | deed_chain_break | 0.3% | 18,490 | 18,490 rows lack the inputs deed_chain_break is computed from: fill the inputs, then recompute |
| NC | Mecklenburg | deed_chain_distress_transfer | 0.3% | 18,490 | 18,490 rows lack the inputs deed_chain_distress_transfer is computed from: fill the inputs, then recompute |
| NC | Mecklenburg | deed_chain_has_history | 0.3% | 18,490 | backfill deed_chain_has_history for the 18,490 applicable rows without it (enrichment_deed_chain) |
| SC | Spartanburg | multi_year_delinquent_tax | 4.7% | 18,475 | screen the 18,475 unchecked rows (enrichment_tax_owed, multi_year_delinquent_tax); write a negative result per row |
| SC | Spartanburg | code_enforcement | 4.8% | 18,447 | screen the 18,447 unchecked rows (enrichment_code_enforcement, enrichment_charlotte_code); write a negative result per r |
| NC | Gaston | atty_deed_chain_fetched | 31.6% | 18,205 | backfill atty_deed_chain_fetched for the 18,205 applicable rows without it (enrichment_deed_chain) |
| NC | Gaston | deed_chain_break | 31.6% | 18,205 | 18,205 rows lack the inputs deed_chain_break is computed from: fill the inputs, then recompute |
| NC | Gaston | deed_chain_distress_transfer | 31.6% | 18,205 | 18,205 rows lack the inputs deed_chain_distress_transfer is computed from: fill the inputs, then recompute |
| NC | Gaston | deed_chain_has_history | 31.6% | 18,205 | backfill deed_chain_has_history for the 18,205 applicable rows without it (enrichment_deed_chain) |
| SC | Spartanburg | atty_legal_description | 6.7% | 18,078 | backfill atty_legal_description for the 18,078 applicable rows without it (existing enrichers) |
| NC | Lincoln | email | 2.6% | 18,058 | no free owner-email source: e-mails come only from notices and filings; research a lawful source |
| NC | Mecklenburg | atty_deed_ref | 3.5% | 17,900 | backfill atty_deed_ref for the 17,900 applicable rows without it (existing enrichers) |
| NC | Mecklenburg | atty_legal_description | 4.1% | 17,788 | backfill atty_legal_description for the 17,788 applicable rows without it (existing enrichers) |
| NC | Lincoln | vacant_lot | 6.2% | 17,677 | 17,677 rows lack the inputs vacant_lot is computed from: fill the inputs, then recompute |
| NC | Lincoln | parcel_id | 6.8% | 17,559 | backfill parcel_id for the 17,559 applicable rows without it (existing enrichers) |
| NC | Lincoln | atty_legal_description | 7.0% | 17,531 | backfill atty_legal_description for the 17,531 applicable rows without it (existing enrichers) |
| NC | Lincoln | tax_aging_surfaced | 8.5% | 17,232 | screen the 17,232 unchecked rows (enrichment_tax_aging); write a negative result per row |
| NC | Lincoln | repeat_tax_loss | 9.6% | 17,032 | 17,032 rows lack the inputs repeat_tax_loss is computed from: fill the inputs, then recompute |
| SC | Spartanburg | tax_aging_surfaced | 18.9% | 15,723 | screen the 15,723 unchecked rows (enrichment_tax_aging); write a negative result per row |
| SC | Spartanburg | atty_deed_ref | 21.8% | 15,162 | backfill atty_deed_ref for the 15,162 applicable rows without it (existing enrichers) |
| NC | Mecklenburg | code_enforcement | 18.8% | 15,063 | screen the 15,063 unchecked rows (enrichment_code_enforcement, enrichment_charlotte_code); write a negative result per r |
| NC | Lincoln | divorce | 0.0% | 14,498 | screen the 14,498 unchecked rows (enrichment_nc_divorce, enrichment_sc_divorce); write a negative result per row |
| NC | Lincoln | bop_federal | 0.0% | 14,497 | screen the 14,497 unchecked rows (enrichment_bop_federal); write a negative result per row |
| NC | Lincoln | incarceration | 0.1% | 14,486 | screen the 14,486 unchecked rows (enrichment_incarceration); write a negative result per row |
| NC | Lincoln | marriage_license | 0.1% | 14,478 | screen the 14,478 unchecked rows (enrichment_register_checks, register_checks); write a negative result per row |
| SC | Spartanburg | atty_deed_chain_fetched | 27.4% | 14,067 | backfill atty_deed_chain_fetched for the 14,067 applicable rows without it (enrichment_deed_chain) |
| SC | Spartanburg | deed_chain_break | 27.4% | 14,067 | 14,067 rows lack the inputs deed_chain_break is computed from: fill the inputs, then recompute |
| SC | Spartanburg | deed_chain_distress_transfer | 27.4% | 14,067 | 14,067 rows lack the inputs deed_chain_distress_transfer is computed from: fill the inputs, then recompute |
| SC | Spartanburg | deed_chain_has_history | 27.4% | 14,067 | backfill deed_chain_has_history for the 14,067 applicable rows without it (enrichment_deed_chain) |
| NC | Gaston | bop_federal | 0.0% | 14,061 | screen the 14,061 unchecked rows (enrichment_bop_federal); write a negative result per row |
| NC | Gaston | divorce | 0.0% | 14,061 | screen the 14,061 unchecked rows (enrichment_nc_divorce, enrichment_sc_divorce); write a negative result per row |
| NC | Gaston | jail_booking_new | 0.0% | 14,061 | code covers this county (enrichment_jail_bookings) but nothing landed here: run it for this county and stamp 'screened,  |
| NC | Gaston | incarceration | 0.1% | 14,042 | screen the 14,042 unchecked rows (enrichment_incarceration); write a negative result per row |
| NC | Gaston | marriage_license | 0.3% | 14,024 | screen the 14,024 unchecked rows (enrichment_register_checks, register_checks); write a negative result per row |
| SC | Spartanburg | bop_federal | 0.0% | 13,848 | screen the 13,848 unchecked rows (enrichment_bop_federal); write a negative result per row |
| SC | Spartanburg | incarceration | 0.2% | 13,830 | screen the 13,830 unchecked rows (enrichment_incarceration); write a negative result per row |
| NC | Mecklenburg | phone | 25.4% | 13,754 | backfill phone for the 13,754 applicable rows without it (existing enrichers) |
| NC | Mecklenburg | comps_tight | 0.0% | 13,239 | backfill comps_tight for the 13,239 applicable rows without it (existing enrichers) |
| NC | Lincoln | phone | 28.8% | 13,208 | backfill phone for the 13,208 applicable rows without it (existing enrichers) |
| NC | Mecklenburg | sqft | 1.7% | 13,022 | backfill sqft for the 13,022 applicable rows without it (existing enrichers) |
| NC | Mecklenburg | beds_baths | 1.7% | 13,019 | backfill beds_baths for the 13,019 applicable rows without it (existing enrichers) |
| NC | Mecklenburg | comps | 1.9% | 12,996 | backfill comps for the 12,996 applicable rows without it (existing enrichers) |
| NC | Wake | two_year_delinquent | 0.0% | 12,941 | screen the 12,941 unchecked rows (albemarle_observer_tax_lists, nc_its_public_tax); write a negative result per row |
| NC | Wake | multi_year_delinquent_tax | 0.0% | 12,938 | screen the 12,938 unchecked rows (enrichment_tax_owed, multi_year_delinquent_tax); write a negative result per row |
| NC | Wake | tax_aging_surfaced | 0.0% | 12,938 | screen the 12,938 unchecked rows (enrichment_tax_aging); write a negative result per row |
| NC | Wake | repeat_tax_loss | 0.0% | 12,937 | 12,937 rows lack the inputs repeat_tax_loss is computed from: fill the inputs, then recompute |
| NC | Wake | atty_deed_ref | 1.2% | 12,780 | backfill atty_deed_ref for the 12,780 applicable rows without it (existing enrichers) |
| NC | Mecklenburg | assessed_value | 31.7% | 12,670 | backfill assessed_value for the 12,670 applicable rows without it (existing enrichers) |
| NC | Transylvania | liens | 0.1% | 12,511 | screen the 12,511 unchecked rows (enrichment_dew_liens, enrichment_irs_lien); write a negative result per row |
| NC | Transylvania | atty_rod_lien_checked | 0.4% | 12,483 | backfill atty_rod_lien_checked for the 12,483 applicable rows without it (enrichment_aumentum_rod, enrichment_cchs_rod) |
| NC | Buncombe | code_enforcement | 0.0% | 12,446 | screen the 12,446 unchecked rows (enrichment_code_enforcement, enrichment_charlotte_code); write a negative result per r |
| NC | Mecklenburg | email | 32.6% | 12,416 | no free owner-email source: e-mails come only from notices and filings; research a lawful source |
| NC | Wake | comps_tight | 0.0% | 12,393 | backfill comps_tight for the 12,393 applicable rows without it (existing enrichers) |
| NC | Wake | atty_legal_description | 4.3% | 12,389 | backfill atty_legal_description for the 12,389 applicable rows without it (existing enrichers) |
| NC | Guilford | atty_rod_lien_checked | 0.1% | 12,266 | backfill atty_rod_lien_checked for the 12,266 applicable rows without it (enrichment_aumentum_rod, enrichment_cchs_rod) |
| NC | Guilford | liens | 0.1% | 12,266 | screen the 12,266 unchecked rows (enrichment_dew_liens, enrichment_irs_lien); write a negative result per row |
| NC | Wake | atty_taxpayer_of_record | 5.2% | 12,264 | backfill atty_taxpayer_of_record for the 12,264 applicable rows without it (parcel_cache, enrichment_qpaybill_tax) |
| NC | Wake | comps | 1.2% | 12,247 | backfill comps for the 12,247 applicable rows without it (existing enrichers) |
| NC | Wake | beds_baths | 1.2% | 12,244 | backfill beds_baths for the 12,244 applicable rows without it (existing enrichers) |
| NC | Wake | sqft | 1.2% | 12,242 | backfill sqft for the 12,242 applicable rows without it (existing enrichers) |
| NC | Guilford | multi_year_delinquent_tax | 0.3% | 12,241 | screen the 12,241 unchecked rows (enrichment_tax_owed, multi_year_delinquent_tax); write a negative result per row |
| NC | Mecklenburg | atty_taxpayer_of_record | 34.0% | 12,241 | backfill atty_taxpayer_of_record for the 12,241 applicable rows without it (parcel_cache, enrichment_qpaybill_tax) |
| NC | Guilford | two_year_delinquent | 0.6% | 12,209 | screen the 12,209 unchecked rows (albemarle_observer_tax_lists, nc_its_public_tax); write a negative result per row |
| NC | Transylvania | email | 1.5% | 12,169 | no free owner-email source: e-mails come only from notices and filings; research a lawful source |
| NC | Guilford | atty_deed_ref | 1.4% | 12,098 | backfill atty_deed_ref for the 12,098 applicable rows without it (existing enrichers) |
| NC | Transylvania | atty_deed_ref | 4.6% | 11,953 | backfill atty_deed_ref for the 11,953 applicable rows without it (existing enrichers) |
| NC | Mecklenburg | bop_federal | 0.0% | 11,886 | screen the 11,886 unchecked rows (enrichment_bop_federal); write a negative result per row |
| NC | Mecklenburg | divorce | 0.0% | 11,886 | screen the 11,886 unchecked rows (enrichment_nc_divorce, enrichment_sc_divorce); write a negative result per row |
| NC | Mecklenburg | incarceration | 0.0% | 11,886 | screen the 11,886 unchecked rows (enrichment_incarceration); write a negative result per row |
| NC | Transylvania | repeat_tax_loss | 5.1% | 11,886 | 11,886 rows lack the inputs repeat_tax_loss is computed from: fill the inputs, then recompute |
| NC | Mecklenburg | marriage_license | 0.2% | 11,862 | screen the 11,862 unchecked rows (enrichment_register_checks, register_checks); write a negative result per row |
| NC | Buncombe | multi_year_delinquent_tax | 6.0% | 11,695 | screen the 11,695 unchecked rows (enrichment_tax_owed, multi_year_delinquent_tax); write a negative result per row |
| NC | Guilford | code_enforcement | 5.1% | 11,649 | screen the 11,649 unchecked rows (enrichment_code_enforcement, enrichment_charlotte_code); write a negative result per r |
| NC | Wake | atty_deed_chain_fetched | 10.3% | 11,603 | backfill atty_deed_chain_fetched for the 11,603 applicable rows without it (enrichment_deed_chain) |
| NC | Wake | deed_chain_break | 10.3% | 11,603 | 11,603 rows lack the inputs deed_chain_break is computed from: fill the inputs, then recompute |
| NC | Wake | deed_chain_distress_transfer | 10.3% | 11,603 | 11,603 rows lack the inputs deed_chain_distress_transfer is computed from: fill the inputs, then recompute |
| NC | Wake | deed_chain_has_history | 10.3% | 11,603 | backfill deed_chain_has_history for the 11,603 applicable rows without it (enrichment_deed_chain) |
| NC | Guilford | atty_deed_chain_fetched | 5.7% | 11,572 | backfill atty_deed_chain_fetched for the 11,572 applicable rows without it (enrichment_deed_chain) |
| NC | Guilford | deed_chain_break | 5.7% | 11,572 | 11,572 rows lack the inputs deed_chain_break is computed from: fill the inputs, then recompute |
| NC | Guilford | deed_chain_distress_transfer | 5.7% | 11,572 | 11,572 rows lack the inputs deed_chain_distress_transfer is computed from: fill the inputs, then recompute |
| NC | Guilford | deed_chain_has_history | 5.7% | 11,572 | backfill deed_chain_has_history for the 11,572 applicable rows without it (enrichment_deed_chain) |
| NC | Buncombe | atty_legal_description | 8.1% | 11,441 | backfill atty_legal_description for the 11,441 applicable rows without it (existing enrichers) |
| SC | Spartanburg | two_year_delinquent | 41.6% | 11,318 | screen the 11,318 unchecked rows (albemarle_observer_tax_lists, nc_its_public_tax); write a negative result per row |
| NC | Mecklenburg | vacant_lot | 39.0% | 11,308 | 11,308 rows lack the inputs vacant_lot is computed from: fill the inputs, then recompute |
| NC | Buncombe | tax_aging_surfaced | 9.4% | 11,275 | screen the 11,275 unchecked rows (enrichment_tax_aging); write a negative result per row |
| NC | Mecklenburg | lot_size | 40.1% | 11,109 | backfill lot_size for the 11,109 applicable rows without it (existing enrichers) |
| SC | Charleston | atty_deed_ref | 2.0% | 10,982 | backfill atty_deed_ref for the 10,982 applicable rows without it (existing enrichers) |
| NC | Guilford | phone | 9.5% | 10,950 | backfill phone for the 10,950 applicable rows without it (existing enrichers) |
| NC | Buncombe | email | 11.1% | 10,923 | no free owner-email source: e-mails come only from notices and filings; research a lawful source |
| NC | Rutherford | email | 2.8% | 10,844 | no free owner-email source: e-mails come only from notices and filings; research a lawful source |
| NC | Mecklenburg | parcel_id | 41.7% | 10,817 | backfill parcel_id for the 10,817 applicable rows without it (existing enrichers) |
| NC | Forsyth | atty_rod_lien_checked | 0.1% | 10,679 | backfill atty_rod_lien_checked for the 10,679 applicable rows without it (enrichment_aumentum_rod, enrichment_cchs_rod) |
| NC | Forsyth | liens | 0.1% | 10,679 | screen the 10,679 unchecked rows (enrichment_dew_liens, enrichment_irs_lien); write a negative result per row |
| NC | Guilford | vacant_lot | 14.0% | 10,562 | 10,562 rows lack the inputs vacant_lot is computed from: fill the inputs, then recompute |
| NC | Forsyth | atty_deed_ref | 1.4% | 10,535 | backfill atty_deed_ref for the 10,535 applicable rows without it (existing enrichers) |
| NC | Guilford | email | 13.2% | 10,512 | no free owner-email source: e-mails come only from notices and filings; research a lawful source |
| SC | Charleston | atty_legal_description | 6.8% | 10,451 | backfill atty_legal_description for the 10,451 applicable rows without it (existing enrichers) |
| NC | Buncombe | comps_tight | 5.4% | 10,300 | backfill comps_tight for the 10,300 applicable rows without it (existing enrichers) |
| NC | Buncombe | divorce | 0.0% | 10,175 | screen the 10,175 unchecked rows (enrichment_nc_divorce, enrichment_sc_divorce); write a negative result per row |
| NC | Guilford | parcel_id | 17.3% | 10,151 | backfill parcel_id for the 10,151 applicable rows without it (existing enrichers) |
| NC | Buncombe | incarceration | 0.3% | 10,143 | screen the 10,143 unchecked rows (enrichment_incarceration); write a negative result per row |
| NC | Rutherford | atty_deed_ref | 9.6% | 10,130 | backfill atty_deed_ref for the 10,130 applicable rows without it (existing enrichers) |
| NC | Buncombe | marriage_license | 0.6% | 10,115 | screen the 10,115 unchecked rows (enrichment_register_checks, register_checks); write a negative result per row |
| NC | Forsyth | atty_deed_chain_fetched | 6.7% | 9,970 | backfill atty_deed_chain_fetched for the 9,970 applicable rows without it (enrichment_deed_chain) |
| NC | Forsyth | deed_chain_break | 6.7% | 9,970 | 9,970 rows lack the inputs deed_chain_break is computed from: fill the inputs, then recompute |
| NC | Forsyth | deed_chain_distress_transfer | 6.7% | 9,970 | 9,970 rows lack the inputs deed_chain_distress_transfer is computed from: fill the inputs, then recompute |
| NC | Forsyth | deed_chain_has_history | 6.7% | 9,970 | backfill deed_chain_has_history for the 9,970 applicable rows without it (enrichment_deed_chain) |
| NC | Buncombe | bop_federal | 2.1% | 9,964 | screen the 9,964 unchecked rows (enrichment_bop_federal); write a negative result per row |
| NC | Buncombe | beds_baths | 8.7% | 9,943 | backfill beds_baths for the 9,943 applicable rows without it (existing enrichers) |
| SC | Spartanburg | repeat_tax_loss | 48.9% | 9,899 | 9,899 rows lack the inputs repeat_tax_loss is computed from: fill the inputs, then recompute |
| NC | Transylvania | bop_federal | 0.0% | 9,840 | screen the 9,840 unchecked rows (enrichment_bop_federal); write a negative result per row |
| NC | Transylvania | divorce | 0.0% | 9,840 | screen the 9,840 unchecked rows (enrichment_nc_divorce, enrichment_sc_divorce); write a negative result per row |
| NC | Transylvania | jail_booking_new | 0.0% | 9,840 | code covers this county (enrichment_jail_bookings) but nothing landed here: run it for this county and stamp 'screened,  |
| NC | Transylvania | marriage_license | 0.1% | 9,832 | screen the 9,832 unchecked rows (enrichment_register_checks, register_checks); write a negative result per row |
| NC | Transylvania | incarceration | 0.1% | 9,831 | screen the 9,831 unchecked rows (enrichment_incarceration); write a negative result per row |
| SC | Charleston | comps_tight | 0.1% | 9,790 | backfill comps_tight for the 9,790 applicable rows without it (existing enrichers) |
| NC | Transylvania | phone | 20.9% | 9,774 | backfill phone for the 9,774 applicable rows without it (existing enrichers) |
| SC | Charleston | comps | 0.8% | 9,716 | backfill comps for the 9,716 applicable rows without it (existing enrichers) |
| SC | Charleston | beds_baths | 1.1% | 9,686 | backfill beds_baths for the 9,686 applicable rows without it (existing enrichers) |
| SC | Spartanburg | lot_size | 50.4% | 9,620 | backfill lot_size for the 9,620 applicable rows without it (existing enrichers) |
| SC | Spartanburg | comps_tight | 12.8% | 9,583 | backfill comps_tight for the 9,583 applicable rows without it (existing enrichers) |
| NC | Rutherford | atty_tax_verified_confirmed | 4.9% | 9,544 | screen the 9,544 unchecked rows (existing enrichers); write a negative result per row |
| NC | Rutherford | divorce | 0.0% | 9,474 | screen the 9,474 unchecked rows (enrichment_nc_divorce, enrichment_sc_divorce); write a negative result per row |
| NC | Rutherford | bop_federal | 0.1% | 9,466 | screen the 9,466 unchecked rows (enrichment_bop_federal); write a negative result per row |
| NC | Rutherford | incarceration | 0.2% | 9,458 | screen the 9,458 unchecked rows (enrichment_incarceration); write a negative result per row |
| NC | Forsyth | phone | 11.6% | 9,339 | backfill phone for the 9,339 applicable rows without it (existing enrichers) |
| NC | Brunswick | atty_rod_lien_checked | 0.0% | 9,223 | backfill atty_rod_lien_checked for the 9,223 applicable rows without it (enrichment_aumentum_rod, enrichment_cchs_rod) |
| NC | Gaston | sos_dissolution | 3.4% | 9,208 | screen the 9,208 unchecked rows (enrichment_sos_dissolution); write a negative result per row |
| NC | Gaston | two_year_delinquent | 65.5% | 9,172 | screen the 9,172 unchecked rows (albemarle_observer_tax_lists, nc_its_public_tax); write a negative result per row |
| NC | Forsyth | email | 13.5% | 9,135 | no free owner-email source: e-mails come only from notices and filings; research a lawful source |
| NC | Rutherford | tax_aging_surfaced | 3.9% | 9,124 | run the tax_lien / lien_registry_wall sweep over the 9,124 unverified hit rows |
| NC | Rutherford | lt_tax_lien | 4.6% | 9,026 | run the tax_lien / lien_registry_wall / nc_ecourts_case sweep over the 9,026 unverified hit rows |

## Rolled up by column (which existing readers have the most unswept rows)

| column | cells | total est_rows_affected |
|---|---|---|
| atty_deed_ref | 126 | 368,751 |
| atty_deed_chain_fetched | 148 | 321,867 |
| deed_chain_break | 148 | 321,867 |
| deed_chain_distress_transfer | 148 | 321,867 |
| deed_chain_has_history | 148 | 321,867 |
| bop_federal | 148 | 315,129 |
| incarceration | 148 | 314,712 |
| atty_legal_description | 138 | 314,704 |
| atty_rod_lien_checked | 93 | 285,126 |
| tax_aging_surfaced | 139 | 280,466 |
| comps_tight | 149 | 275,129 |
| phone | 104 | 273,023 |
| liens | 89 | 266,565 |
| email | 102 | 262,897 |
| vacant_lot | 120 | 262,365 |
| beds_baths | 141 | 252,456 |
| repeat_tax_loss | 137 | 252,338 |
| divorce | 115 | 246,142 |
| comps | 149 | 239,183 |
| assessed_value | 135 | 233,207 |
| lot_size | 140 | 214,316 |
| two_year_delinquent | 133 | 210,326 |
| sqft | 143 | 205,209 |
| multi_year_delinquent_tax | 104 | 201,330 |
| marriage_license | 100 | 197,180 |
| parcel_id | 145 | 194,640 |
| atty_taxpayer_of_record | 146 | 172,540 |
| address | 148 | 136,908 |
| atty_tax_verified_confirmed | 62 | 131,189 |
| code_enforcement | 13 | 118,838 |
| lt_tax_lien | 106 | 77,424 |
| sos_dissolution | 102 | 63,018 |
| name_care_of | 148 | 47,306 |
| name_deceased | 148 | 47,306 |
| name_estate_of | 148 | 47,306 |
| name_et_al | 148 | 47,306 |
| name_heirs | 148 | 47,306 |
| name_life_estate | 148 | 47,306 |
| name_trust | 148 | 47,306 |
| owner_name | 148 | 47,306 |
