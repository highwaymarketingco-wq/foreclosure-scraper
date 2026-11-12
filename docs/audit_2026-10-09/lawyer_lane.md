# Audit 2026-10-09: the lawyer lane (lane C, the attorney's quiet-title list)

Stephen (the attorney) asks, per lead: the parcel number, the legal description off the latest deed, the
deed chain, the taxpayer of record, the possible heirs with their relation, and which records were checked
(register of deeds, tax, probate, obituaries). Code: `src/foreclosure_scraper/lawyer_lane.py`,
`county_deed_ref.py`, `enrichment_rod_chain.py` (binding), `call_ready.py` (lane C), `scripts/lawyer_packages.py`,
`scripts/lawyer_lane_coverage.py`. Invariants: `scripts/audit_checks/lawyer_lane.py`. Tests: `tests/test_lawyer_lane.py`,
`tests/test_call_ready.py`.

## 1. What was measured and how

**Per-item coverage** (`uv run python scripts/lawyer_lane_coverage.py --board <board> --out <json>`; one streamed
pass, 63 MB peak). An item counts only when a record on the row supplies it AND dates it (`lawyer_lane.items`).
Groups: the call-ready lanes as stamped on the row, and three quiet-title candidate classes: `heir_estate` (a
record or marker says the owner died), `elderly_long` (an elderly marker on a parcel held 20+ years),
`tax2_unclear` (2+ years delinquent and an unclear title). Counts by county are in
`lawyer_lane_coverage.json` (reconciled checkpoint of 2026-10-09 14:01 UTC, 383,378 rows).

| Group (checkpoint) | Rows | Parcel | Legal desc. | Chain | Taxpayer | Heirs | ROD checked | Tax checked | Probate checked | Obits | Complete |
|---|---|---|---|---|---|---|---|---|---|---|---|
| Lane C | 21,426 | 15,751 | 0 (5,499 walled) | 34 | 4,143 | 82 | 250 | 916 | 312 (20,019 walled) | 82 | 0 |
| Lane B | 6,235 | 153 | 0 | 2 | 119 | 1,800 | 11 | 25 | 5,878 | 0 | 0 |
| Quiet-title candidates (any) | 33,408 | 18,672 | 0 | 36 | 6,342 | 1,883 | 1,602 | 1,067 | 6,197 (25,272 walled) | 83 | 0 |
| heir_estate | 27,867 | 16,080 | 0 | 36 | 4,409 | 1,883 | 275 | 949 | 6,197 | 83 | 0 |
| elderly_long | 1,782 | 1,775 | 0 | 0 | 1,239 | 0 | 1,189 | 60 | 0 | 0 | 0 |
| tax2_unclear | 6,504 | 2,962 | 0 | 22 | 2,001 | 147 | 326 | 679 | 26 | 0 | 0 |

Live board (2026-10-07 publish, no `call_ready` block yet): 24,932 candidates; parcel 14,117, taxpayer 6,267,
heirs 1,499, register 1,733, probate 2,171, chain 42, tax 44, legal description 0, obituaries 0, complete 0.

Largest candidate counties (checkpoint): Horry SC 4,105, Buncombe 2,191, Gaston 1,836, Lincoln 1,341,
Pickens SC 1,319, Spartanburg SC 1,174, Rutherford 1,041, Laurens SC 924, Charleston SC 841, Anderson SC 800.

**Chain precision** (30 chains with a deed per state, run live through the plain-HTTP register adapters on
quiet-title candidates, one lead per owner, 2 s per host; compared with the county parcel record read live:
NC OneMap `sourceref`, SC the county's own parcel layer; private rows in `~/Desktop/Audit_2026-10-09/lawyer_lane/`):

| | NC | SC |
|---|---|---|
| Chains with a last deed | 30 (56 tried: 15 owner not found, 6 partial, 5 adapter errors) | 30 (44 tried) |
| Name-found chain is the parcel's deed (decidable) | 13 / 25 = 52% | 10 / 19 = 53% |
| Bound by the old rule (row's own sale date) | 4, all right (4 of 13 right ones) | 5, all right (5 of 10) |
| Bound by the new rule (county record's book/page) | 12, all right (12 of 13 right ones) | 10, all right (10 of 10) |
| Wrong chain bound | 0 | 0 |

Replay on the checkpoint: 57 chains stamped before the binding existed; `stamp_deed_latest` re-bound all 57
(no network): 7 bound (raw.deed_latest written), 5 turned `unbound`, the rest name-only.

**Ten real lane C leads end to end** (live intake sheet + the pipeline path: register chain, county deed
reference, binding, deed_latest; private results `e2e10_results.json`). P = sourced and dated, M = missing,
W = walled (a person pulls it):

| County | Parcel | Legal | Chain | Taxpayer | Heirs | ROD | Tax | Probate | Obits |
|---|---|---|---|---|---|---|---|---|---|
| Buncombe | P | P | P | P | M | P | P | W | M |
| Rutherford | P | P (bound chain) | P | P | M | P | M | W | M |
| Jackson | P | P | M | P | M | P | W | W | M |
| Durham, McDowell, Haywood, Transylvania | P | M | M | P | M | P | M | W | M |
| Polk (2) | P | M | M | P | M | P | W | W | M |
| Mecklenburg | P | M | M | P | M | M | M | W | M |

None is complete. Every one lacks the estate search (NC eCourts CAPTCHA), heirs with a relation and a dated
obituary search.

## 2. Defects found

| Class | Scale | Cause | Fix | Test | Invariant |
|---|---|---|---|---|---|
| Register chain is another parcel's deed or misses a later one | 48% of name-found chains (NC 12/25, SC 9/19) | chains are found by owner name; the old binding needed a county sale date the row lacks on 65% of sampled candidates (594 of 912) | bind by the book/page the county parcel record cites (`county_deed_ref.py`: NC OneMap, 6 SC county layers, fetched before binding); a same-day different book/page is name-only | test_lawyer_lane, test_rod_run_shape | `lawyer-chain-book-page`, `lawyer-deed-latest-bound` |
| Chains stamped before the binding treated as the lead's | 46 status-ok chains on the checkpoint | the binding was added after they were stamped; refresh is 30 days | `stamp_deed_latest` re-binds with no network (wire below) | test_lawyer_lane | `lawyer-rod-chain-bound` |
| No latest deed or legal description on any row | 0 of 21,426 lane C | nothing wrote one | `raw.deed_latest` {doc id, book/page, recorded, grantor, grantee, index description, source URL, read at, bound} from bound chains only | test_lawyer_lane, test_call_ready | `lawyer-deed-latest-bound` |
| Lawyer list said "ok" without a source or date | 18,191 lane B/C blocks | roll legal + any deed reference, GIS sale history counted as a chain, a death-index check counted as a probate search | items must be sourced and dated; walled items named apart (`lawyer_<item>_walled`) | test_call_ready | `lawyer-lane-c-ready-sourced`, `lawyer-list-shape` |
| Intake: Buncombe 10-digit PIN not found; open Cott registers not read; dateless cited deed and quitclaims not taken | 1 of 1 Buncombe, 8 Cott counties | 15-digit layer key; only Buncombe/Polk adapters | pad; `adapters/cott_onemap.py`; vesting rules | test_lawyer_lane | none (the intake is not on the board; tests only) |

## 3. Open items

* **Wall, every NC county:** estate files (eCourts picture CAPTCHA). No NC lane C lead can be complete without the
  owner's dated estate search. Owner card `lawyer_owner_pulls` (docs/walls_register.json); the owner saves
  `items.json` per parcel and `scripts/lawyer_packages.py` regenerates the package.
* **Wall:** full legal description text (deed images paid or bot-checked); the item uses the register index's
  description of the bound deed. Greenwood SC's parcel layer links a free deed PDF (not read here).
* **Owner decision:** per-lead obituary lookups are off; heirs and the obituary check stay missing.
* **No reader yet (a script could):** Greenville and Greenwood SC estate indexes are open. With a reader and
  obituary lookups on, these are the only counties where a complete package needs no hand step.
* **Switches:** `FORECLOSURE_ROD_CHAIN` and most register platform flags ship off; lane C can only grow when the
  lead turns them on for the run.
* **Not verified:** the new binding was not run inside a pipeline run; the county record's deed reference is
  taken as the authority (a record that lags a newer deed reads as name-only or stale, never bound).

## 4. Outside this area

* nc_lookup: Haywood 2 of 4 chains failed ("the session holds '' names"), Transylvania 3 of 3 not found in under 1 s.
* NC OneMap `sourceref`: Avery garbage, blank or placeholder in Ashe, Bertie, Davidson, Graham, Robeson, Union;
  board PINs for Buncombe, Onslow, Anson, Macon do not match `parno`.
* Polk: OneMap deed dates do not match the register entry at the cited book/page (2 of 2 intakes).
* tests/test_raw_keep_covers_enrichers.py fails on identity.py keys (owner_conflict, twins_collapsed, unfused).
