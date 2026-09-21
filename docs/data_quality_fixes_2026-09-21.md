# Board data-quality fixes, 2026-09-21

Six fixes from audit sections 9 and 16, each written as a dry-run-first script with an in-memory `apply_rows`
function. Nothing here has been applied. Every count below is from a dry run over the live board
(`docs/listings.json.gz`, 170,066 rows, unchanged since 10:10 on 2026-09-21). The dry runs took six streaming
passes in total, all through `board_stream.iter_board_rows`, one at a time. `map_account_ids_to_parcels` was
replayed from the first pass's saved extract, which holds every Laurens and Rutherford row, so its numbers are the
same as a live pass.

## 0. Run order and the apply contract (read this first)

Every script exposes

```python
def apply_rows(rows: list, *, dry_run: bool = False) -> dict
```

`rows` is the `load_board` list. The function mutates the Listing objects in place, never changes `len(rows)`,
never writes a file (it reads the parcel caches only), and returns a counter dict. Two conventions:

* When a script replaces or removes a value, the old values come back under the key `"_backup"`. Pop it before
  treating the result as counters and write it with `_dq_common.write_backup(mod.BACKUP_NAME, backup)`.
* A real run (`dry_run=False`) first checks that every raw key it stamps is in `web_artifact.RAW_KEEP` and raises
  `RuntimeError` before touching any row if not (`write_artifact` drops an unregistered key silently). Each module
  lists them in `REQUIRED_RAW_KEYS`. **Three keys are not registered today, see section 1.**

Extra keyword arguments are optional: `backfill_missing_county.apply_rows(rows, evidence=...)` and
`quarantine_flip_leaks.apply_rows(rows, derive_county=..., evidence=...)` accept a shared `Evidence`
(`backfill_missing_county.build_evidence(rows)`, a 15 second scan of the parcel caches);
`promote_ptscloud_block` and `map_account_ids_to_parcels` accept `cache_lookup`.

Order, with the reason for each dependency:

| Step | Module (`scripts/`) | Must come after | Why |
|---|---|---|---|
| 1 | `undo_resolver_middle_conflicts` | nothing | It withdraws wrong parcels and streets. It reads per-source "does this source name properties" rates from the board as it stands, so run it before anything adds parcels or streets. Every later step then sees a wrong resolution as a name-only lead again. |
| 2 | `promote_ptscloud_block` | 1 | Swaps 686 Henderson PTS numbers for real PINs so the cache join in step 6 can hit them. |
| 3 | `map_account_ids_to_parcels` | 1 | Swaps 386 Laurens account numbers for TMS ids and 12 Rutherford PINs for REIDs, same reason. |
| 4 | `backfill_missing_county` | 1 | Gives 1,873 rows a county. The parcel-cache join and the address fill both key on county, and step 5 needs it. |
| 5 | `quarantine_flip_leaks` | 4 | A flip with no county cannot be judged against the footprint. After step 4 the 4 county-less REO rows that resolve to Rowan or Union NC become ordinary known-county leaks, so `derive_county` can stay False in a chain. |
| 6 | `fill_address_from_parcel` | 2, 3, 4, 1 | Needs the promoted parcel ids and the county, and must not see a wrong resolver parcel. |
| 7 | `join_parcel_cache_to_board.py` (existing script) | 2, 3, 4, 6 | Owner mailing, value, sqft. Its blind street copy is now gated (section 3), so order against step 6 no longer risks junk addresses. It has no `apply_rows`; its loop is in `main()`. |
| 8 | `recompute_valuation.py`, `rank_board_standalone.py` | 1 to 7 | Steps 1 and 6 change parcels and values. The scorer must also read `raw['scope']` (section 4) or the quarantine changes nothing. |

Steps 2 and 3 are independent of each other; steps 4 and 5 are independent of 2, 3 and 6 apart from the ordering above.

## 1. RAW_KEEP registrations (blocker, 3 lines)

`web_artifact._slim_raw` keeps only the keys in `RAW_KEEP`. These three are written by the scripts and are not in
it, so without them the stamp is silently lost at publish:

```python
    # 2026-09-21 data-quality fixes (docs/data_quality_fixes_2026-09-21.md)
    "county_backfill": "*",            # county filled from ZIP / city / parcel evidence {county, evidence, basis}
    "scope": "*",                      # 'flip_outside_footprint': a flip outside the 18 counties, scorer excludes it
    "resolver_conflict_undone": "*",   # withdrawn name-to-property resolution {action, query_name, matched_owner, removed}
```

Add them inside the `RAW_KEEP` dict (after `"berkeley_paystar_tax": "*",`). `_SLIM_RAW` and dashboard.js `_LEAN_RAW`
are not needed unless the dashboard should show them. `tests/test_raw_keep_covers_enrichers.py` scans `src/`, not
`scripts/`, so it does not need an entry. Every other key the scripts write (`owner_mailing`, `parcel_from_geo`,
`owner_mismatch`, `situs_address_source`, `situs_road_only`, `qpaybill_roll`, `gis_attrs_full`,
`resolved_from_name`, `nc_ptscloud_delinquent_tax`) is already registered.

## 2. Summary

| # | Fix | Script | Rows affected (live dry run) | Apply | Risk |
|---|---|---|---|---|---|
| 1 | Street address from the parcel cache, id tolerance, city and zip | `fill_address_from_parcel.py` | 18,267 leads have a parcel and no address (34,010 have no address, 15,743 of those have no parcel either). **7 street fills**, 2 city, 0 zip. 976 road-only names stashed in `raw['situs_road_only']`. Id tolerance adds 24 cache hits (7,154 to 7,178). Street-name-only to numbered upgrades: 144 in the live run, at least 2 fewer after two refinements made afterwards (section 3) | `python scripts/fill_address_from_parcel.py --apply` | Low. Numbered addresses only, fill-only, never across states. |
| 2 | County for rows with none | `backfill_missing_county.py` | 4,503 rows with no county: 1,873 resolved, 1,018 ambiguous, 1,612 none (737 are `recap` bankruptcy rows, court district is not a county). Hold-out precision 99.0%, recall 54% | `python scripts/backfill_missing_county.py --apply` | Low to medium. About 1 in 100 resolved counties would be wrong. Needs the `county_backfill` RAW_KEEP key. |
| 3 | Flip leaks outside the footprint | `quarantine_flip_leaks.py` | 102 flip rows outside the 18 counties, plus 21 REO rows with no county (4 of them resolve outside the footprint): **106 stamps**. Nothing removed | `python scripts/quarantine_flip_leaks.py --apply` | Low for the stamp. The scorer must read it, and the owner must confirm the rule beats the older coastal carve-out (section 4). Needs the `scope` RAW_KEEP key. |
| 4a | Henderson PTS numbers | `promote_ptscloud_block.py` | 871 Henderson rows carry a PTS number: **686 swapped to the real PIN**, 90 flagged `owner_mismatch` (the coordinates put a stranger's parcel on the lead), 29 owner mailings built from the block, 4 PIN not in cache, 91 with no usable PIN in the row | `python scripts/promote_ptscloud_block.py --apply` | Low to medium. A replaced id, backed up. Only when the cache owner shares a name token with the taxpayer. |
| 4b | Laurens account numbers | `map_account_ids_to_parcels.py` | 389 six-digit account ids: **386 have the TMS in the same raw block** (`qpaybill_roll.detail.map_number`) | `python scripts/map_account_ids_to_parcels.py --apply` | Low. Replaced id backed up and kept in `qpaybill_roll.identification_no`. |
| 4c | Rutherford PINs | same script | 367 Rutherford rows miss the cache: **12 map to a REID** through their own GIS bag. 295 carry a bag for a different parcel, 56 no bag, 4 no REID. The rest need the cache to index `PIN` (section 5) | same | Low. |
| 5 | Resolver middle-name conflicts | `undo_resolver_middle_conflicts.py` | 1,337 committed name resolutions, **125 proven conflicts** (the audit counted 57): 95 blanked, 30 flag-only | `python scripts/undo_resolver_middle_conflicts.py --apply` | Medium. Blanks parcel, street and value on 95 leads, all kept in `raw['resolver_conflict_undone']` and `backups/`. Needs the `resolver_conflict_undone` key. |
| 6 | Transylvania house numbers | `fill_address_from_parcel.py` plus `build_transylvania_address_points.py` | The cache cannot upgrade them (section 3). The county's own address layer would upgrade about 3% of vacant leads and 18% of the others | overlay is not built; build it with `python scripts/build_transylvania_address_points.py` | Low. |

Before and after, on the live board:

| Measure | Before | After (dry run) |
|---|--:|--:|
| Leads with a street address | 136,056 | 136,063 |
| Leads with a house-numbered address | 124,905 | 125,054 to 125,056 (7 fills, 142 to 144 upgrades) |
| Leads with no county | 4,503 | 2,630 |
| Flip rows outside the footprint with no scope stamp | 102 (plus 21 county-less) | 0 |
| Henderson leads keyed by a PTS number | 871 | 185 |
| Laurens leads keyed by an account number | 389 | 3 |
| Committed resolutions with a proven middle-name conflict standing | 125 | 0 (95 blanked, 30 flagged) |

Files added: `scripts/_dq_common.py`, `fill_address_from_parcel.py`, `build_transylvania_address_points.py`,
`backfill_missing_county.py`, `quarantine_flip_leaks.py`, `promote_ptscloud_block.py`,
`map_account_ids_to_parcels.py`, `undo_resolver_middle_conflicts.py`, and seven test files `tests/test_dq_*.py`
(115 tests, all passing). Files edited: `src/foreclosure_scraper/parcel_cache.py` (`lookup` now calls `lookup_with_tier`;
`_id_variants` and the cache build are unchanged, so no cache needs rebuilding) and
`scripts/join_parcel_cache_to_board.py` (the street copy now goes through `classify_situs`).

## 3. Fix 1 and fix 6: address from the parcel

### Why the 18,267 do not fill

The audit expected about 16,000 parcel-bearing address-less leads to be fillable by the cache join. The join runs,
and 7 fill. The gap is the data, not a format problem:

* **No cache for the county: 8,954 leads (49%).** Greenville 2,061, Florence 1,966, Williamsburg 830, Berkeley 735,
  Allendale 517, Marlboro 471, Cherokee SC 345, Jasper 345, Clarendon 321, Georgetown 253, McCormick 208, Kershaw 208,
  Chesterfield 194, Lee SC 163, Dillon 139 and others. Being researched by another agent.
* **The cache has the parcel but no address: 4,355 (24%).** Horry 1,522 (the Horry cache has no address column at
  all), Darlington 697, Oconee 579, Laurens 391, Pickens 305, Barnwell 297, McDowell 267, Saluda 54. These are rural
  and vacant parcels with no situs in the county data. They need an address-point layer, like the one described for
  Transylvania below.
* **The cache "address" is not a street: 1,840 legal descriptions or junk, 976 road names with no house number.**
  Examples of what the caches hold in that column: `SPLIT FROM 116-00-01-048` (Darlington), `OFF SR 1151 EXT`
  (Transylvania), `S-6-65` (Barnwell), `PINEWOOD ACRES    3101 CAMDEN DR` (Anderson), `1163` (McDowell),
  `0 CALHOUN TRL` (Rutherford, "0" is the county's no-number sentinel, 678 rows), `0 NO ADDRESS ASSIGNED` (Henderson).
* **The id does not match: 2,110 (12%).** Horry 963 (ids such as `99800029462`), Henderson 375 (PTS numbers, fix 4a),
  Spartanburg 141 (no relation to any cached id), Barnwell 95 and Darlington 49 (sub-parcels like `.01`, `.012`),
  Laurens 58 (account numbers, fix 4b), Rutherford 68 (PINs, fix 4c), New Hanover 71 (alphanumeric ids).

Per county (counties with 100 or more leads with a parcel and no address; "hits after id fix" includes the id
tolerance described below):

| State | County | Leads with a parcel and no address | Cache file | Hits now (exact id) | Hits after id fix | Street filled | Road only | Legal text or junk | Cache row has no address | Id miss |
|---|---|--:|:-:|--:|--:|--:|--:|--:|--:|--:|
| SC | Horry | 2,485 | yes | 1,522 | 1,522 | 0 | 0 | 0 | 1,522 | 963 |
| SC | Greenville | 2,061 | no | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| SC | Florence | 1,966 | no | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| NC | Transylvania | 1,433 | yes | 1,428 | 1,428 | 1 | 0 | 1,422 | 5 | 5 |
| SC | Williamsburg | 830 | no | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| SC | Darlington | 752 | yes | 690 | 703 | 3 | 1 | 2 | 697 | 49 |
| NC | Rutherford | 746 | yes | 678 | 678 | 0 | 678 | 0 | 0 | 68 |
| SC | Berkeley | 735 | no | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| SC | Oconee | 606 | yes | 579 | 579 | 0 | 0 | 0 | 579 | 27 |
| SC | Allendale | 517 | no | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| SC | Marlboro | 471 | no | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| SC | Laurens | 451 | yes | 393 | 393 | 0 | 0 | 2 | 391 | 58 |
| SC | Barnwell | 394 | yes | 299 | 299 | 0 | 0 | 2 | 297 | 95 |
| NC | Henderson | 385 | yes | 10 | 10 | 0 | 1 | 9 | 0 | 375 |
| SC | Cherokee | 345 | no | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| SC | Jasper | 345 | no | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| NC | McDowell | 324 | yes | 285 | 285 | 0 | 0 | 18 | 267 | 39 |
| SC | Clarendon | 321 | no | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| SC | Pickens | 318 | yes | 305 | 305 | 0 | 0 | 0 | 305 | 13 |
| SC | Colleton | 296 | yes | 241 | 241 | 0 | 138 | 85 | 18 | 55 |
| SC | Georgetown | 253 | no | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| SC | McCormick | 208 | no | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| SC | Kershaw | 208 | no | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| SC | Chesterfield | 194 | no | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| NC | Lincoln | 180 | yes | 178 | 178 | 0 | 0 | 146 | 32 | 2 |
| SC | Lee | 163 | no | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| SC | Spartanburg | 153 | yes | 12 | 12 | 0 | 0 | 9 | 3 | 141 |
| NC | New Hanover | 150 | yes | 79 | 79 | 0 | 21 | 58 | 0 | 71 |
| SC | Dillon | 139 | no | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| | 61 other counties | 838 | mixed | 455 | 466 | 3 | 137 | 87 | 239 | 149 |
| | **Total** | **18,267** | | **7,154** | **7,178** | **7** | **976** | **1,840** | **4,355** | **2,110** |

Full output: 90 counties. Outcome counts across all 18,267 leads: no cache 8,954; cache row has no address 4,355;
legal text or junk 1,840; road name only 976; id miss 2,110; street filled 7 (Harnett 2, Darlington 3, Pender 1,
Transylvania 1).

### What was changed, and why it is safe

* **Id tolerance (`parcel_cache.lookup`, +24 hits, 7 fills).** Two forms are tried only after every exact form has
  missed, so an existing hit never changes: a delimited all-zero sub-parcel suffix (`052-00-02-212.000`,
  `151-06-01-006-000`, `6844-24-1309.000` resolve to the bare parcel), and zero-padding differences on all-numeric
  ids of 10 or more digits (`0546-74-1638` against `0546741638000`; Harnett, Watauga, Transylvania, Pender, Lee,
  Forsyth). Zero-padding needs an unambiguous answer: every candidate row must be the same owner, address and mailing.
  Short internal ids are excluded (Rutherford's `616146` and `6161460` are two parcels). A non-zero sub-parcel
  (`.01`, `.012`, ` 001`, `A`) is deliberately **not** resolved to its parent: the parent can be a different lot.
  64 of the 2,110 misses are such sub-parcels whose parent has a numbered address; that count is information only.
* **A street is written only from a numbered address** (`classify_situs`). Numbered means a real house number and a
  street word; `000141 LEVI DR` becomes `141 LEVI DR`; a trailing acreage (`12C TOXAWAY FALLS DR .86`) is dropped;
  `831/833 N Oak St` counts as numbered. A sentinel (`0 X`, `99999 X`) becomes `raw['situs_road_only']`, the
  convention `enrichment_situs_address` already uses, and never `street_address`.
* **City and zip only when the owner mails to the property.** If the cached owner mailing address begins with the
  property's own street and ends `CITY ST ZIP` with the lead's state, that city and zip are the property's. Live: 2
  cities, 0 zips (few caches carry a mailing that begins with the situs).
* **State-qualified and county-checked.** A `(county, state)` pair that is not a real county of that state is
  skipped (20 leads), `tax_sale_overage` is skipped (the cache owner is not the claimant), and dual-state county
  names still need a state.
* **Street-name-only upgrade.** A lead whose street has no house number is upgraded to the parcel's numbered
  address only when both name the same street (number, suffix and direction ignored) and no directional word
  conflicts (`S CHESTER ST` is not `1501 N CHESTER ST`). The replaced street is kept in `raw['situs_road_only']` and
  in `backups/`. **144 upgrades in the live run**, sampled before applying: all but two were correct. The two
  bad ones (a `831/833 N Oak St` unit range read as name-only, and the `S`/`N` Chester St case) are fixed in the
  code and tested. The live count after that is 142 or fewer; it was not re-streamed because the pass budget was
  spent.

### The join script had a real hazard

`join_parcel_cache_to_board.py` copied `hit["address"]` into `street_address` without looking at it. Some of that
text passes `web_artifact._is_valid_street_address` (`COMMON AREA-WHITEWATER COVE` ends in a road word) and would be
published as the property's address. I edited its situs branch to call `classify_situs` (numbered only). It is the
only edit to an existing script. Its owner mailing, value and sqft fills are unchanged.

### Fix 6, Transylvania

Transylvania vacant has a street on 75% of leads and a house number on 10%. Measured:

* 3,880 of 5,332 vacant leads carry a `street_address` equal to their `legal_description`
  (`COMMON AREA-WHITEWATER COVE`). The scraper writes the county layer's `LEGAL_ADDR` field into
  `street_address`. The 10% with a number are lot-and-acreage strings such as `1324 2.00`.
* The Transylvania parcel cache is built from NC OneMap `siteadd` and its address column is `LEGAL_ADDR`
  text as well. Numbered addresses in it: 1% of rows. Verified on the live layers with one query each: NC OneMap
  has `saddno` on 0 of 31,755 Transylvania parcels, and the county parcel layer
  (`gis.transylvaniacounty.org .../Parcels/MapServer/2`) has no situs number field, only `LEGAL_ADDR`.
* So the join cannot upgrade them. The upgrade rule above is implemented and tested, and finds 0 to 10 cases from
  the cache.
* The county does publish a real situs source: `.../Addresses/MapServer/0`, 28,144 points, 27,985 with a
  `PARCELNUM` (13 digits, undashed, the same form `parcel_cache` normalizes board ids to) and `ADDRNUM`,
  `FULLADDR`, `POSTALCOM`, `POSTALZIP`. A one-request sample of board parcels: 4 of 150 vacant parcels (3%) have an
  address point, 27 of 150 non-vacant Transylvania parcels (18%). Parcels with two addresses (a duplex) exist and are
  left out on purpose. Expected yield is a few hundred leads with a number, city and zip.
* `scripts/build_transylvania_address_points.py` builds `data/address_points/transylvania.sqlite` (about 30
  requests to the county server). It is not built, because the brief allowed one verification sample only.
  `fill_address_from_parcel` reads that file as an overlay when it exists and prefers it over the cache.
* The root fix is in the scraper (`transylvania_vacant`): stop writing `LEGAL_ADDR` into `street_address`.
  Not my file.

The same overlay pattern (one small sqlite of `id, address, city, zip` per county in `data/address_points/`) is
what the counties in the "cache has no address" group need. The other agent's Horry overlay can use it, or
`_lookup` in `fill_address_from_parcel.py` can be pointed at theirs.

## 4. Fix 3: flip leaks

**Rule.** `main._FLIP_LISTING_TYPES` (foreclosure_sale, auction, sheriff_sale, hoa_sale, reo): only in the 18
footprint counties. Every other type is anywhere in NC and SC.

**Measured.** 102 flip rows outside the 18 counties. By county: Charleston 33, Pender 24, Georgetown 15, Dare 11,
Onslow 7, Carteret 6, Currituck 2, Beaufort SC 2, Brunswick 1, New Hanover 1. By source: fannie_homepath 46,
charleston_mie 24, georgetown_civicengage 11, column_legal_notices 5, brock_scott 5, hutchens 4, sc_public_notices 2,
nc_notices_counties 2, hubzu 1, zillow_bulk 1, coastland_times 1. By type: foreclosure_sale 53, reo 47, hoa_sale 2.
Plus 21 REO rows with no county (`reo.vrm_va_reo`, 12 NC and 9 SC).

**Root cause.** The 2026-09-15 rule was wired into exactly two places in `main.py`: `_county_in_scope` (which
sends flips to `in_scope`, the 18-county check) and the deny check in `_in_scope` (line 338). Everything that
admits a coastal row runs before both and never asks whether the row is a flip:

1. `_in_scope`, the oceanfront override (about line 271): a coastal county plus a passing `_check_oceanfront`
   returns True. Beach-town Fannie HomePath REO (Surf City, Rodanthe, North Topsail, Garden City, Isle of Palms)
   and law-firm rows at Atlantic Beach, Folly Beach, Ocean Isle come in here. About 56 of the 102.
2. `_in_scope`, `_coastal_county_source` (line 291): any row from `COASTAL_COUNTY_BYPASS_SOURCES` (charleston_mie,
   georgetown_civicengage, column_legal_notices, coastland_times and others) in an `OCEANFRONT_COASTAL_COUNTIES`
   county returns True, every listing type. About 41.
3. `_in_scope`, `_is_downtown_charleston` and the downtown-Charleston provisional (lines 305 to 318). About 5.
4. `_denied_now` in the post-enrichment re-pass (about line 1757) then exempts the same rows a second time: it
   returns False for `raw.oceanfront`, `raw.downtown_charleston`, `raw.coastal_county`, and for any county in
   `OCEANFRONT_COASTAL_COUNTIES`, before the footprint test.
5. The county-less REO rows: `_in_scope` admits a row with no county by ZIP prefix (`280`, `281`, `287`, `288`,
   `293`, `296`), and `_countyless_national` in the re-pass would drop `reo.*` rows, but the standalone ingest
   scripts (`scripts/ingest_national_reo_cluster.py` and the other `ingest_*.py`) call only `_in_scope`, and the full
   run has not landed since 8/29.

**Change needed in `main.py` for future runs (not edited by me).**

```python
def _flip_outside_footprint(li: Listing) -> bool:
    """A flip whose county is known and is not one of the 18 footprint counties."""
    return (_is_flip(li) and bool((li.county or "").strip()) and bool(li.state)
            and not in_scope(li.county, li.state))
```

* In `_in_scope`, make this the first statement, before the oceanfront override:
  `if _flip_outside_footprint(li): return False`.
* In `_denied_now` (the re-pass), make it the first statement, before the `raw.get("oceanfront")` carve-out:
  `if _flip_outside_footprint(li): return True`.
* In the same re-pass, drop a flip that still has no county after enrichment (it cannot be routed to the 18
  counties): `if _is_flip(li) and not (li.county or "").strip(): return True`. Today only `national.*` and `reo.*`
  are dropped for having no county.
* Optionally `_coastal_county_source`: `if _is_flip(li): return False` as its first line.

**Owner decision needed.** The oceanfront override and the coastal-source bypass were added in 2026-06 to 2026-08
on the owner's direction to surface coastal foreclosures. The 2026-09-15 rule ("if its a flip, its only in the
counties we talked about") is later and, read literally, supersedes them for flips. Confirm before changing
`main.py`. Distressed leads in the coastal counties are unaffected by any of this.

**What the script does now.** It stamps `raw['scope'] = 'flip_outside_footprint'` on the 102 leaks and on county-less
flips whose county resolves (by the same evidence as fix 2) to a county outside the footprint (4 of the 21). It is
idempotent and self-correcting (a stamp on a row now in the footprint, or no longer a flip, is cleared). It moves,
drops and changes nothing else. Stamped rows still ship; the scorer must read the stamp.

### Handoff note for the scorer owner

The scorer is `src/foreclosure_scraper/distress_score.py`; the tier comes out of `score_board` (the group loop near
line 1207) and `_derive_tier`. Read `li.raw.get("scope") == "flip_outside_footprint"`. Recommended, mirroring the
existing `sold_confirmed` exclusion:

```python
_OUT = "flip_outside_footprint"
active = [li for li in group
          if not (li.raw or {}).get("sold_confirmed") and (li.raw or {}).get("scope") != _OUT]
# a group with no active row is unscored (its old distress_stack is popped), exactly like a sold parcel
```

That keeps a parcel that also carries an in-scope lead (a Charleston tax lien plus an out-of-footprint sale) scored
on the lead alone, and takes a flip-only parcel out of HOT and WARM. If a visible COLD is preferred, instead set
`ds["scope_capped"] = True` and `return "COLD"` at the top of `_derive_tier` when it is set, so
`retract_equity_rank` cannot re-tier it. The key survives `write_artifact` only after the RAW_KEEP entry in section 1.

## 5. Fix 4: junk parcel ids

### Henderson `nc_ptscloud_delinquent_tax` (871 rows; 4 more are Hyde and left alone)

The live pass gave 699 swaps and 79 flags under a looser first version of the owner test. The figures below use the
final test (two shared name tokens, more placeholder names), measured by replaying the saved extract, which holds
every Henderson row.

The audit said the raw block "already has owner and mailing" so they could be promoted. Measured, they mostly are
already: all 871 have `owner_name` and a value, 842 have an `owner_mailing`, because the row's coordinates were
point-in-polygon joined to a `county_gis` or `nc_onemap` parcel and its owner and mailing were attached, with that
parcel's real PIN inside `raw['owner_mailing']['parcel_id']`. So the script does three things:

1. Fills from the block only what is blank: 29 owner mailings (the taxpayer's bill address). `owner_name`,
   value, acreage and legal description were already present on the rows here.
2. **Swaps the PTS number for the PIN** in `owner_mailing.parcel_id` when that PIN is a 10-digit Henderson PIN in
   the Henderson cache and the cache owner shares two name tokens with the taxpayer (one when a side has a single token; a shared
   surname alone does not count, and placeholders like `UNKNOWN OWNER` or `MAPPING WORK IN PROGRESS` never agree). 686 of 871. The PTS number stays in the block (`parcel`), in `raw['parcel_from_geo']` and in
   `backups/`.
3. **Flags 90 rows `raw['owner_mismatch']`** where the parcel the coordinates resolved to has a different owner.
   Their owner, mailing and street are a stranger's. Flag only, nothing removed, so the existing `owner_mismatch`
   red flag surfaces them. The other 91 have no usable PIN in the row and 4 have a PIN that is not in the cache.

These delinquencies are old (tax years 1993 to 1995), so the bill mailing address is stale by decades; that is why
the block mailing is only used when the row has none.

### Laurens qpaybill account numbers (389 six-digit ids)

The crosswalk exists. The treasurer roll's `identification_no` is an account number (`000789`); the same raw block
carries `qpaybill_roll.detail.map_number`, the parcel (`094-00-00-036.002`). 386 of 389 carry a TMS-shaped
`map_number` and `parcel_id` becomes it; the account number stays in `identification_no`. 39 of them then hit the
Laurens cache exactly; 348 hit at the parent parcel only, because the `.002` is a sub-parcel (a mobile home on the
map parcel), and in 230 of those the parent's owner agrees with the taxpayer. Parent fallback is not applied. Three
rows have an `LH` suffix or no `map_number` and are left alone.

### Rutherford (338 in the audit; 367 rows miss the cache in the live run)

* `rutherford_tax` 209 rows with 7-digit ids that are not in the cache, `nc_heir_estate_parcels` 123 rows with
  10-digit PINs, a few `kania` dashed PINs and liensnc rows.
* The cache is keyed by the 6 to 7 digit `Parcel_Number` (REID). PINs never match.
* Crosswalk in the raw block: 289 rows carry `gis_attrs_full` with `PIN`, `LEGACY_PIN`, `REID`, `TAXPIN`, but for
  295 of the 367 the bag is a **different parcel** (approximate coordinates), so it is only trusted when its own PIN,
  legacy PIN or REID equals the row's id. That is 16 rows, 12 of which resolve, so 12 are mapped.
* **What is missing for the rest is in the cache config, not the board.** Verified with one query, the cached layer
  (`gis.rutherfordcountync.gov/arcgis/rest/services/TaxParcels/MapServer/0`) publishes a `PIN` field
  (`Parcel_Number 419510` has `PIN 1549378423`), but `parcel_cache.PARCEL_LAYERS["Rutherford"]["id_fields"]` is
  `["Parcel_Number"]`. Adding `"PIN"` and refreshing the cache (one pull of about 57,000 parcels) makes every PIN-keyed
  Rutherford row resolvable, about 130 more. That table belongs to the other agent, so I did not edit it. The same
  layer also carries `Physical_Address_City` and `Physical_Address_Zip`, which the cache schema (no city or zip
  column) cannot hold.

## 6. Fix 5: resolver middle-name conflicts

`enrichment_resolve_name_to_property` commits a unique surname plus first-name hit. Its own middle-name check
(`middle_conflict`) only compared spelled-out middles, and the older path committed anyway and set
`middle_conflict=True` in the provenance.

Re-judged from each lead's own provenance (the name searched, `query_name`, against the GIS owner matched,
`matched_owner`): 1,337 committed resolutions. Verdicts: 703 agree, 409 unverifiable (no middle on one side), 92
different name, 8 unparsed, **125 proven conflicts**. Proven means the same surname and first name with a middle
initial on both sides that differs (`name_normalize.owner_last_first_middle`, the reader `party_middle_verdict` is
built on), or `middle_conflict` (spelled-out middles that differ). 50 of the 125 were already flagged by the
resolver; 75 were not. The audit's 57 counted a narrower set.

Of the 125, 95 are resolver-owned leads (a name-only source such as `sc_public_index` 59, `nc_ecourts_judgments` 20,
whose parcel and street can only have come from the resolver): those are blanked. 30 are merged with a
parcel-native source (`spartanburg_vacant`, a tax roll: the parcel and street may be the other source's own): those
are only stamped. Blanked fields, with counts on the 95: street_address 94, parcel_id 93, living_sqft 72,
market_value 71, tax_value 69, assessed_value 68, acreage 34, year_built 21, owner_name 20 (only when it equals the
matched owner), land_use 18; plus the parcel-derived raw blocks `gis`, `gis_attrs_full`, `owner_mailing`,
`situs_address_source`, `parcel_from_geo`. All of it is kept in `raw['resolver_conflict_undone']['removed']` and
`backups/`, so any single lead can be restored. `raw['resolved_from_name']['confidence']` becomes
`middle_conflict_undone`.

Not undone, and worth knowing: city, zip and coordinates (cannot be proven resolver-written, right at county level);
and on the 30 merged leads, signals such as `raw['divorce']` that a wrong-person name match attached to the parcel.

## 7. Fix 2: county for rows with none

Evidence, in order, and a conflict skips the row:

1. **Parcel id found in exactly one county's cache**, decisive only where the state's caches cover nearly every
   county (NC 98 of 100). In SC it is corroboration only: TMS numbers repeat across counties
   (`115-00-00-100.000` is a Cherokee parcel and a Colleton one) and most SC counties have no cache. A hold-out
   check that let SC parcel evidence decide got 449 wrong in 13,329, all of this kind.
2. **ZIP.** A table built from the parcel caches: every cached parcel whose owner mailing address begins with its own
   situs street is an owner-occupant, so the mailing ZIP is the parcel's ZIP and the cache's county is the truth
   (780,435 parcels, 1,007 ZIPs, 2,666 cities). A ZIP that appears under two counties is ambiguous and skipped. The
   board's own `(zip, county)` pairs are a cross-check only, because a county whose cached mailing carries no ZIP
   (Henderson) or puts it before the city (Mecklenburg) contributes nothing, so its ZIPs look unique to the
   neighbour (28732 is Buncombe 533 in the cache; the board has Henderson 218 of 362). The board must agree, and
   cache-only evidence needs at least 20 parcels.
3. **City**, the same way, and it must sit inside a multi-county ZIP's own county set.

Result on 4,503 rows: resolved 1,873 (zip and city 1,263, zip 419, city 107, parcel 84), ambiguous 1,018 (577 ZIP
spans two counties, 277 board disagrees), none 1,612 (737 have no evidence at all: the `recap` bankruptcy rows carry
no ZIP, city or parcel, and a court district is not a county). By source: liensnc 1,859 of 3,745, vrm_va_reo 14 of
21. Top resolved counties: Brunswick 426, Union 148, Currituck 97, Pender 61, Moore 54.

**Measured precision.** 10,888 liensnc, vrm, fannie and zillow rows that already carry a county were resolved as if
they did not (their own board contribution removed): 5,844 right, 59 wrong, 4,027 ambiguous, 958 none. **Precision
99.0%, recall 54%.** Some of the 59 are the board being wrong, not the resolver: liensnc takes the county the
filer picked, and an `Anson` row for Marshville (a Union County town) is the filer's error.

## 8. Blockers and decisions

1. **RAW_KEEP: 3 keys** (section 1). Without them `apply_rows` refuses the three scripts that need them.
2. **Owner decision** on flip scope against the older coastal carve-out, then the `main.py` change and the scorer
   change in section 4. Until both land, the quarantine stamp changes nothing on the published board.
3. **Rutherford `id_fields`** needs `"PIN"` added and a cache refresh (other agent's table, network).
4. **Address overlays** are where the real address gain is: no-cache counties (8,954 leads) and caches with no situs
   (4,355). Transylvania's county layer is verified; `build_transylvania_address_points.py` is ready but not run.
5. **Pass budget.** The six streaming passes were spent, so after the last two refinements to the street-name
   upgrade the live count of 144 was not re-measured (142 or fewer). The offline replay of the saved extract, which
   holds every relevant row, shows the two known bad cases now excluded.
6. `join_parcel_cache_to_board.py` was edited (situs gate) although it was not on the list of files I own; the brief
   allowed extending it. Its dry run uses `load_board`, so I did not run it.
7. I changed `parcel_cache.lookup` (now a wrapper over `lookup_with_tier`). I ran only my new test files, as
   instructed; the existing `tests/test_parcel_cache*.py` files were not run and should be, before the chain.
