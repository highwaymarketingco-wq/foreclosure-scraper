# Column accuracy (audit 2026-10-09, area column_accuracy)

Does every FIELD column mean what its name says, and is the value right? Measured on the reconciled
pre_publish checkpoint (VM `data/checkpoint`, saved 2026-10-09T14:01Z, 383,378 rows) read the way
it would publish (`board_selfcheck._checkpoint_rows`, i.e. through `web_artifact._to_dict`).

## 1. How it was measured (repeatable)

1. **Pass 1** (one stream of the checkpoint): per column, how many rows have a value and how many of
   those are placeholders (`column_accuracy.placeholder_class`), overall and for HOT / WARM /
   call-ready (call_ready tier A or B); plus a stratified reservoir per (state, column) by source,
   by county and HOT/WARM.
2. **Selection**: 30 rows per column per state (NC, SC), up to 8 HOT/WARM first, then alternating
   the biggest counties and random sources; for parcel-record columns only rows whose county has a
   layer the repo reads (`parcel_cache.PARCEL_LAYERS` / `resolve_layer_cfg`, NC OneMap statewide).
   763 distinct rows.
3. **Live lookup** of each row on that layer: by the row's parcel id (stored form, then normalized),
   by the row's point, and (no hit) by the situs house number + street. One request at a time per
   host, at least 2 s apart, browser User-Agent. Nothing walled was touched.
4. **Judging** per column against the county record (names by token overlap, addresses by house
   number + street word, values within 2 %, lot within 10 %, sqft within 5 %, year within 1).
   Phones against the NCSBE voter files the enricher itself read (`data/ncvoter`) and the Buncombe
   county owner-contact index; e-mails by provenance.
5. **Board scale** of each class found: passes 2 and 3 and the new checks over the whole checkpoint.

Scripts and the row-level evidence (names) are outside the repo, in the owner's audit folder.

## 2. Precision per column (verified rows only; the rest had no county field to compare)

| column | NC right / verified | SC right / verified | unverifiable NC / SC | commonest error |
|---|---|---|---|---|
| address (situs) | 24/24 | 16/17 | 6 / 13 | situs of another house on the parcel record |
| parcel_id | 25/28 | 28/28 | 2 / 2 | id not on the county layer (2), owner+situs disagree (1) |
| owner_name | 23/24 | 18/19 | 6 / 11 | a notice party, not the roll owner |
| owner mailing | 14/15 | 24/28 | 15 / 2 | glued house number (2, fixed), older mailing (3) |
| assessed / tax value | 14/20 | 14/16 | 10 / 14 | stale year (pre-revaluation), land value as tax value |
| sqft | 0/1 | 1/1 | 29 / 29 | layers publish no heated area for most counties |
| beds / baths | 3/3 | 12/14 | 27 / 16 | listing figure differs from CAMA |
| lot size | 22/22 | 20/24 | 8 / 6 | deed vs GIS acreage, one parent tract |
| year built | 7/8 | 13/13 | 22 / 17 | one listing year vs CAMA |
| legal description | 10/10 | 12/14 | 20 / 16 | a street name in the legal column (Charleston tax sale) |
| taxpayer of record | 21/25 | 24/26 | 5 / 4 | STALE OWNER: the delinquent roll's owner, sold since (6) |
| phone (usable) | 12/21 | 0 usable of 30 | 9 / 0 | another person's phone via a Soundex voter match (7) |
| email | 0/30 | 0/28 | 0 / 0 | escape artifact ('npat@' for 'pat@'), agent/contractor address |

Small samples: the right-hand counts are what could be checked, so a 1-of-1 is not a rate.

## 3. Defects found and fixed

| class | scale on the 10/9 checkpoint | cause | fix | test | invariant |
|---|---|---|---|---|---|
| e-mail escape artifact | 41,196 rows | `enrichment_surface_contacts` regex over `json.dumps(raw)`: a newline became `\n` and the `n` joined the address | scan string by string (`emails_in_raw`); repair carried blocks at publish | test_column_accuracy_email | column-email-owner-only |
| e-mail not the owner's | the other 5,782 best_emails | best_email = first address found (agent, contractor, lien agent) | best_email = `owner_email_of` or empty, at source and in `_to_dict` (`normalized_owner_email_block`); others kept in `emails` | same | same (after: 0 of 46,382) |
| fuzzy voter phone of another person | 9,527 Soundex-tier phones, 7,829 dialable, 123 call-ready | `matched_name` on a Soundex match is the owner's own name, so the identity gate compared the owner with himself | gate checks the voter file: the phone must sit on a voter with the owner's name, else do-not-dial (`identity_basis` stamped); legacy fuzzy blocks re-gated | test_voter_phone_identity_gate (3 new) | column-phone-fuzzy-rechecked (fails until the next run's voter_phone step) |
| layer value = one component | Spartanburg market/tax = building only; Rutherford, McDowell, Mitchell, NC OneMap tax_value = land value | parcel_cache field map | sums / removed | parcel_cache suites | column-layer-map-semantics |
| sqft from a money field | Polk `BUILDING_VALUE`, Mitchell `Dwelling` (dwelling value, 420,900 seen live) | field map | removed | test_column_accuracy_checks | column-layer-map-semantics |
| SC assessed = market | 2,224 rows | `enrichment_owner_mailing` wrote the appraisal into all three value columns | SC skipped at source; withheld at publish | test_column_accuracy_email | column-sc-assessed-not-market |
| glued house number | 1,540 Berkeley PayStar mailings (+36 other rows) | the invoice text | `mailing_shape.unglue_house_number` in the scraper | test_berkeley_paystar_tax | column-house-number-glued (Berkeley 0, rest max 40) |
| agent phone in owner_phone | 174 blocks | surface_contacts | already blocked by role everywhere it is shown; kept as an invariant | - | column-phone-agent-not-usable |

## 4. Fill on the call list (column-fill-call-list; filled / placeholder)

HOT (39 rows): address 29/1, parcel 37/0, owner 37/0, mailing 37/0, value 34/0, sqft 27/0, beds/baths
13/0, lot 33/0, year 11/0, legal 17/0, taxpayer 32/0, phone 9/0, email 0/0.
WARM (59,268): address 44,748/4,630 (street only), parcel 54,300/12, owner 59,025/28, mailing
56,637/632, value 44,752/1,098 (under $1,000), sqft 20,880/2, beds/baths 3,571/1, lot 48,793/0,
year 4,992/0, legal 19,759/532, taxpayer 55,183/26, phone 5,921/19, email 203/0.
Call-ready (799): address 787/134 (street only), parcel 790/0, owner 799/0, mailing 703/0, value
799/2, sqft 659/0, legal 572/48, phone 799/6 (not NANP).

## 5. Open items

- Carried values: the parcel-cache join is fill-only, so rows that already hold a building-only
  (Spartanburg) or land-only tax value keep it until something overwrites them. Not measured per
  row (the cache stores the mapped value, not the field it came from). Needs a cache refresh of the
  changed counties and an owner decision on overwriting cache-filled values.
- Stale taxpayer: 6 of 51 verified taxpayer names are the delinquent roll's owner of a parcel the
  county now shows sold. Not fixed here (the roll owner is the debtor of the bill; the current owner
  is a different lead). Belongs to owner-vs-roll (wave 2 G).
- Stale values: assessed values from before a county revaluation (Buncombe, Rutherford). Not fixed.
- 6 call-ready rows with a non-NANP phone (column-call-ready-phone-nanp fails, max 0): call_ready
  area.
- 54,614 street-only addresses (38,084 land, 16,157 single-family): the county record had a house
  number in the one SC case checked; not resolved at scale.
- Gaston vacant: 12,995 rows carry the county's building sqft on parcels the county flags vacant
  (live: real CAMA building records, years 1921-2026). Left as the county publishes it.
- sqft, beds/baths, year built: most layers publish none, so 22-29 of 30 per state were
  unverifiable; LiensNC filing phones and e-mails were not re-fetched (source not re-read).
