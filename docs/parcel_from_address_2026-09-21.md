# Address to parcel resolver, 2026-09-21

`scripts/resolve_parcel_from_address.py` gives a parcel_id to leads that have a street address and none, by matching
the address against the county parcel cache's situs column. It is offline, dry-run by default, and one step
(`parcel`) of `scripts/apply_board_fixes.py`. Every count below is a dry run on the 170,066-row board of 15:51 on
2026-09-21 (a saved extract, so the ablation and the comparisons use the same rows); a later dry run of the CLI on the
republished 182,388-row board (section 9) gave the same picture.

## 1. Summary

| | |
|---|---|
| Leads with a street address and no parcel_id | 47,718 (1,608 have no county and are skipped, 556 come from sources whose "street" is not a situs, section 5.4) |
| Eligible | 45,554 |
| **Resolved (unique, precision-gated match)** | **19,277** (NC 15,805, SC 3,472) |
| Ambiguous (two parcels at the address) | 299 |
| No match in the cache | 22,685 |
| Road-only, legal, range or unit rejected | 1,140 |
| Rejected for a ZIP conflict or a shared placeholder id | 371 |
| County with no cache file | 1,782 (Beaufort SC 873, Cherokee SC 370, Georgetown 212, Union SC 203, Orangeburg 96) |
| **Hold-out precision** (parcel hidden, resolved by street, compared with the true parcel) | **99.86%** (26,548 of 26,585); recall 93.6% of 28,350 verified leads |
| Hold-out precision by class | liensnc 99.97% (2,884 of 2,885), county tax lists 99.92%, other sources 99.66% |
| False-match rate when the true parcel is NOT in the cache | 0.22% with this rule, 5.21% with the older one-shared-word rule |
| Expected lift (after the existing join runs) | NC parcel coverage 55.4% to 72.4%, market value +14.8 pp, acreage +15.3 pp, mailing +2.3 pp; SC parcel 71.4% to 75.9%, mailing +4.4 pp, owner +2.5 pp, market value +3.9 pp |
| Owner agreement on the 19,277 | agrees 7,349, differs 9,424, unknown 2,504 (recorded, never required) |

What blocks or shapes the apply is in section 9. Short list: one RAW_KEEP line for the lead to add, a decision on the join for
leads whose parcel owner differs from the lead's owner, and a separate finding: about 4,000 liensnc leads already carry a
parcel that sits at a different address than their own (section 5.5).

## 2. The rule

Precision beats recall. A wrong parcel means a wrong owner, mailing address and value, so a lead is resolved only when
all of the following hold, and otherwise nothing is written.

1. **Population.** `parcel_id` empty, street address present, county present and a real county of the lead's state,
   not `tax_sale_overage`, source not in `DENY_SOURCES`. A lead with no county cannot be resolved (the `county` step runs
   before this one). Existing parcel ids are never replaced.
2. **The county's own cache.** The cache is keyed by the lead's own county and state. Dual-state names (Cherokee, Union,
   Lee, Beaufort, Anson, Chester) use the state-qualified file. Never lat/lng.
3. **One numbered street address.** No range ("831-833"), no half number, no road-only or legal text, no sentinel ("0 X").
4. **Full street name.** Cache situs and lead must have the same house number (leading zeros ignored, a letter suffix such
   as 12C must match) and the same street name, every word, after USPS spelling normalisation (STREET/ST, FIRST/1ST,
   SAINT/ST, MOUNTAIN/MTN, and the local spellings BV, CR, WY, TL, PY, LP). The older Burke rule took one shared word.
5. **Suffix, direction, town.** Two different suffixes never agree (ST is not CT); one side may leave its suffix off
   ("3270 BEAVER CREEK" is "3270 BEAVER CREEK DR"). A direction must be the same on both sides ("N MAIN ST" is not
   "MAIN ST"); the only exception is a compound quadrant (NE NW SE SW) that the cache states and the lead does not
   (Brunswick appends them to every address). When the cache situs carries a town ("1101 PARTRIDGE RD SPARTANBURG") and
   the lead names its own (city column, or the tail of its street), the two must agree; "UNINC" is no town.
6. **Units.** A lead with a unit resolves only to the one parcel carrying that unit, or to the one unit-less parcel when every
   candidate is unit-less. A lead without a unit never resolves to a unit parcel.
7. **Unique.** Each parcel sits in the cache under 2 to 3 id spellings with identical owner, situs, mailing and values, so
   candidates are grouped by their attributes. Two different groups at one address is ambiguous. Two groups that share a
   specific id (one PIN published twice) are one parcel.
8. **A specific id.** An id is written only if every cache row that carries it belongs to the matched parcel. Placeholder
   ids are refused (Cumberland `37051` sits on 6,886 rows, Spartanburg `41`). This is the poisoned-id guard of the first
   version of this script.
9. **ZIP.** When the owner mails to the property (the mailing address begins with the situs) its ZIP is the property's ZIP,
   and a lead ZIP that differs rejects the match.

Which id is written. The spelling the county's other board leads already use for that parcel when one is on the board
(146 of the 19,277 today; a lien lead then groups with the tax-roll lead on the same parcel), otherwise the cache spelling
whose length is the most common among the county's board ids (digits first, then shorter).

Provenance, on every resolved lead:

```json
"parcel_from_address": {"source": "parcel_cache_situs_address", "verified": "address_exact_unique", "county": "Wake",
  "state": "NC", "matched_situs": "5918 FALLOWFIELD LN", "cache_owner": "MERITAGE HOMES LLC", "owner_agrees": true,
  "id_basis": "cache_form", "cache_ids": ["1736642838", "0448960", "371830695327712"]}
```

`owner_agrees` is `true`, `false` or `null` (blank owner on either side; placeholders such as UNKNOWN OWNER count as blank).
It uses `promote_ptscloud_block.owners_agree` (two shared name tokens, one when a side has a single token). For liensnc the
lead's owner is the owner of the property being built on, and the cache owner can be a new owner or the builder, so
agreement is recorded, not required.

## 3. Running it

```
python scripts/resolve_parcel_from_address.py                      # dry run over the live board: ONE streaming pass, about 2 minutes, under 500 MB
python scripts/resolve_parcel_from_address.py --rows-file X.jsonl  # same over a saved board-format extract
python scripts/resolve_parcel_from_address.py --no-holdout         # skip the hold-out measurement (about 50 s)
python scripts/resolve_parcel_from_address.py --apply              # standalone apply: ONLY board process
python scripts/apply_board_fixes.py --apply                        # the whole chain in one load (parcel now sits between flip and address)
python scripts/apply_board_fixes.py --steps county,parcel,address,join --apply
```

`apply_rows(rows, *, dry_run=False)` follows the contract in `docs/data_quality_fixes_2026-09-21.md` section 0: it mutates
Listing objects in place, never changes `len(rows)`, never writes a file, returns counters, replaces nothing (so no
`_backup`), and a real run raises `RuntimeError` before touching a row if `parcel_from_address` is not in RAW_KEEP.
The dry run streams the board through `board_stream.iter_board_rows`; the apply path uses only the rows it is given.
The default step order is `resolver, ptscloud, accounts, county, flip, parcel, address, join`: the resolver needs the
county, and `address` and `join` need the parcel it writes. Running `parcel` alone fills nothing else; the owner, mailing,
value and sqft in section 7 arrive when the existing `join` step runs after it.

Note for the lead: `scripts/resolve_parcel_from_address.py` already existed (commit b24474f: an exact normalised-address
match with its own `load_board` main and no `apply_rows`). Nothing imported it. This is a replacement at the same path; the
old version is in git. `resolve_parcel_from_address_fuzzy.py` is untouched. The old `--dry-run` flag is still accepted; a dry
run is now the default and `--apply` is required to write.

## 4. Results by county

Columns: leads with an address and no parcel; whether a cache file exists; how the eligible leads ended; and the share of the
cache's rows whose situs starts with a house number (a cache with no situs cannot resolve anything).

| State | County | Leads (address, no parcel) | Cache file | Unique match | Ambiguous | No match | Street rejected (road-only, legal, range, unit) | Other rejected (ZIP, shared id) | Cache rows with a numbered situs |
|---|---|--:|:-:|--:|--:|--:|--:|--:|--:|
| NC | Wake | 4,518 | yes | 3,171 | 5 | 1,323 | 19 | 0 | 100% |
| NC | Mecklenburg | 3,444 | yes | 710 | 32 | 2,459 | 98 | 145 | 83% |
| SC | Charleston | 3,375 | yes | 283 | 0 | 3,065 | 24 | 3 | 32% |
| SC | Spartanburg | 2,815 | yes | 1,871 | 17 | 811 | 116 | 0 | 91% |
| NC | Brunswick | 2,589 | yes | 1,688 | 0 | 814 | 87 | 0 | 84% |
| NC | Buncombe | 2,071 | yes | 1,388 | 49 | 539 | 67 | 28 | 100% |
| SC | Horry | 1,749 | yes | 976 | 57 | 702 | 4 | 10 | 61% |
| NC | Durham | 1,324 | yes | 1,050 | 1 | 265 | 2 | 6 | 100% |
| NC | Gaston | 1,194 | yes | 673 | 24 | 394 | 103 | 0 | 86% |
| NC | Johnston | 1,104 | yes | 446 | 4 | 652 | 2 | 0 | 100% |
| NC | Union | 1,022 | yes | 547 | 3 | 459 | 11 | 2 | 97% |
| NC | Harnett | 1,021 | yes | 574 | 0 | 447 | 0 | 0 | 78% |
| SC | Beaufort | 873 | no | 0 | 0 | 0 | 0 | 0 | - |
| NC | Onslow | 865 | yes | 332 | 5 | 526 | 2 | 0 | 88% |
| NC | Guilford | 857 | yes | 0 | 0 | 851 | 6 | 0 | 0% |
| NC | Forsyth | 783 | yes | 367 | 4 | 405 | 4 | 3 | 100% |
| NC | Catawba | 661 | yes | 440 | 9 | 210 | 2 | 0 | 88% |
| SC | Anderson | 632 | yes | 75 | 17 | 459 | 80 | 1 | 39% |
| NC | Alamance | 559 | yes | 167 | 2 | 387 | 1 | 2 | 85% |
| NC | Cabarrus | 548 | yes | 0 | 0 | 537 | 11 | 0 | 0% |
| NC | Henderson | 512 | yes | 284 | 0 | 177 | 51 | 0 | 100% |
| SC | Laurens | 491 | yes | 75 | 2 | 368 | 46 | 0 | 50% |
| SC | Pickens | 489 | yes | 169 | 12 | 252 | 55 | 1 | 86% |
| SC | Oconee | 472 | yes | 0 | 0 | 445 | 27 | 0 | 0% |
| NC | Davidson | 468 | yes | 268 | 6 | 191 | 3 | 0 | 82% |
| NC | Lincoln | 457 | yes | 203 | 0 | 193 | 53 | 8 | 75% |
| NC | Cumberland | 424 | yes | 142 | 2 | 171 | 0 | 109 | 100% |
| NC | Rowan | 420 | yes | 63 | 1 | 355 | 0 | 1 | 100% |
| NC | Moore | 392 | yes | 226 | 4 | 153 | 6 | 3 | 75% |
| SC | Cherokee | 370 | no | 0 | 0 | 0 | 0 | 0 | - |
| NC | Orange | 368 | yes | 0 | 0 | 363 | 5 | 0 | 0% |
| NC | Pitt | 367 | yes | 241 | 0 | 120 | 3 | 3 | 100% |
| NC | Franklin | 344 | yes | 0 | 0 | 343 | 1 | 0 | 0% |
| NC | New Hanover | 342 | yes | 219 | 7 | 108 | 0 | 8 | 100% |
| NC | Chatham | 331 | yes | 128 | 1 | 202 | 0 | 0 | 78% |
| NC | Nash | 326 | yes | 221 | 0 | 102 | 3 | 0 | 82% |
| NC | Rutherford | 308 | yes | 96 | 8 | 163 | 41 | 0 | 100% |
| NC | Burke | 305 | yes | 110 | 1 | 145 | 48 | 1 | 100% |
| NC | Craven | 281 | yes | 125 | 0 | 136 | 13 | 7 | 84% |
| NC | McDowell | 277 | yes | 91 | 1 | 155 | 30 | 0 | 56% |
| NC | Randolph | 273 | yes | 135 | 0 | 136 | 2 | 0 | 74% |
| NC | Hoke | 251 | yes | 0 | 0 | 250 | 1 | 0 | 0% |
| NC | Wayne | 242 | yes | 64 | 0 | 177 | 1 | 0 | 72% |
| NC | Stanly | 225 | yes | 50 | 0 | 170 | 1 | 4 | 70% |
| NC | Transylvania | 222 | yes | 0 | 0 | 209 | 13 | 0 | 1% |
| NC | Iredell | 214 | yes | 143 | 0 | 69 | 2 | 0 | 85% |
| SC | Georgetown | 212 | no | 0 | 0 | 0 | 0 | 0 | - |
| NC | Cleveland | 211 | yes | 31 | 0 | 123 | 38 | 19 | 79% |
| SC | Union | 203 | no | 0 | 0 | 0 | 0 | 0 | - |
| | 79 other counties (under 200 leads each) | 3,753 | mixed | 1,435 | 25 | 2,104 | 58 | 7 | |
| | **Total** | **45,554** | | **19,277** | **299** | **22,685** | **1,140** | **371** | |

Reading the table.

* **Eleven caches hold no usable situs** and resolve nothing: Guilford (857 leads), Cabarrus (548), Oconee (472), Orange (368),
  Franklin (344), Hoke (251), Transylvania (222; 1%, lot text such as `LOT 2 Whitewater Cove`), Richmond (44), Perquimans (36),
  Bladen (30) and Avery (27). That is 3,199 leads, and it is the same gap `docs/data_quality_fixes_2026-09-21.md` section 3
  describes for the leads that have a parcel. An address overlay per county (`data/address_points/`) is what fixes it.
* **No cache file** (Beaufort SC, Cherokee SC, Georgetown, Union SC, Orangeburg): 1,782 leads. Greenwood is still pending.
* **Charleston** has a situs on 32% of its cache rows (the county publishes address points for structures only), so 3,065 of
  3,375 leads have no candidate.
* **Wake and Mecklenburg** have a full situs column, and 1,323 and 2,459 leads still do not match: the address-only
  population is skewed to addresses the county data does not hold yet. A liensnc lead is a construction filing, and many are
  new streets. Hold-out recall on parcels the cache does hold is 94 to 97% in the same counties.
* The 8 new SC caches contribute little here because their leads already carry parcels: Horry 976 resolved, Charleston 283,
  Greenville 5, Berkeley 4, Florence 1, Aiken 0, Hampton and Chester none. Their value is in the join (section 8).

By source (largest 14; leads, unique, ambiguous, no match, street or unit rejected, no cache):

| Source | Leads | Unique | Ambiguous | No match | Rejected | No cache |
|---|--:|--:|--:|--:|--:|--:|
| liensnc | 29,457 | 13,713 | 125 | 14,956 | 340 | 15 |
| sc_dew_lien_registry | 7,424 | 1,313 | 69 | 4,771 | 37 | 1,221 |
| nc_ust_incidents | 2,903 | 1,287 | 47 | 1,145 | 385 | 0 |
| spartanburg_property_cleanup | 1,900 | 1,748 | 11 | 136 | 5 | 0 |
| sc_ust_registry | 1,424 | 159 | 16 | 741 | 264 | 243 |
| nc_dam_safety | 442 | 205 | 3 | 227 | 4 | 0 |
| usda_properties | 317 | 115 | 2 | 111 | 1 | 87 |
| buncombe_landslide_damage | 314 | 266 | 3 | 45 | 0 | 0 |
| terry_howe_auctions | 231 | 8 | 0 | 210 | 5 | 8 |
| buncombe_hmgp_buyout | 196 | 164 | 5 | 26 | 0 | 0 |
| nc_inactive_hazardous | 128 | 48 | 2 | 43 | 35 | 0 |
| distressed | 111 | 52 | 1 | 31 | 2 | 25 |
| acres | 99 | 37 | 4 | 40 | 11 | 6 |
| qpaybill_delinquent_roll | 93 | 0 | 0 | 0 | 0 | 93 |

## 5. Precision

### 5.1 Method

Take leads that already have both a parcel and a street, hide the parcel, resolve by street alone, and compare with the lead's
own parcel (the resolved group's id set must contain one of the true parcel's id spellings). Leads whose street was itself
copied from a cache or GIS layer (`raw.situs_address_source`), and leads whose parcel came from coordinates or a name search
(`parcel_from_geo`, `resolved_from_name`), are left out, and so are the denied sources.

**The truth is trusted only where the lead's own parcel sits at the lead's address.** Many sources' parcel_id does not describe their
street_address: a delinquent-tax list prints the taxpayer's mailing address, a permit list carries a neighbour's parcel, and
59% of the liensnc rows that the address can check carry a parcel a few doors away (section 5.5). Scoring the resolver against those would punish it for being right. A hold-out lead therefore counts only when
its own parcel's cache situs has the same house number and the same street name (suffix, direction and town ignored). Of 54,544
candidate leads, 28,350 verify; 16,620 have their parcel at another address and 9,574 have no cache row for their parcel or a
cache row with no situs. With the looser
Burke test (same number and one shared word) there are 30,688 leads and precision is 99.76%; the extra misses are permit and
vacant-lot sources whose parcel is on another street.

### 5.2 Result

Overall: 28,350 verified leads, 26,585 resolved, 26,548 correct, 37 wrong. **Precision 99.86%, recall 93.6%.** Of the 37 wrong,
30 have a different owner and 7 the same owner or mailing. By class: liensnc 2,884 of 2,885 (recall 92.3%), county tax lists
16,932 of 16,945 (93.9%), other sources 6,732 of 6,755 (93.5%).

| State | County | Verified hold-out leads | Resolved | Correct | Wrong | Precision | Recall |
|---|---|--:|--:|--:|--:|--:|--:|
| NC | Buncombe | 3,405 | 3,193 | 3,192 | 1 | 100.0% | 93.7% |
| SC | Spartanburg | 3,283 | 3,015 | 3,011 | 4 | 99.9% | 91.7% |
| NC | Rutherford | 2,831 | 2,795 | 2,795 | 0 | 100.0% | 98.7% |
| NC | Mecklenburg | 2,209 | 2,077 | 2,077 | 0 | 100.0% | 94.0% |
| NC | New Hanover | 2,104 | 1,963 | 1,963 | 0 | 100.0% | 93.3% |
| SC | Sumter | 2,104 | 1,804 | 1,802 | 2 | 99.9% | 85.6% |
| SC | Pickens | 1,973 | 1,881 | 1,875 | 6 | 99.7% | 95.0% |
| SC | Berkeley | 1,467 | 1,420 | 1,416 | 4 | 99.7% | 96.5% |
| SC | Darlington | 1,154 | 1,122 | 1,122 | 0 | 100.0% | 97.2% |
| SC | Lexington | 960 | 917 | 916 | 1 | 99.9% | 95.4% |
| SC | Laurens | 623 | 581 | 578 | 3 | 99.5% | 92.8% |
| NC | Cleveland | 496 | 425 | 421 | 4 | 99.1% | 84.9% |
| NC | Gaston | 467 | 457 | 457 | 0 | 100.0% | 97.9% |
| NC | Henderson | 446 | 443 | 443 | 0 | 100.0% | 99.3% |
| SC | Anderson | 432 | 412 | 412 | 0 | 100.0% | 95.4% |
| NC | Wake | 322 | 313 | 313 | 0 | 100.0% | 97.2% |
| SC | Lancaster | 302 | 274 | 270 | 4 | 98.5% | 89.4% |
| NC | Burke | 287 | 273 | 269 | 4 | 98.5% | 93.7% |
| SC | Calhoun | 242 | 234 | 234 | 0 | 100.0% | 96.7% |
| NC | McDowell | 239 | 230 | 230 | 0 | 100.0% | 96.2% |
| SC | Barnwell | 207 | 198 | 198 | 0 | 100.0% | 95.7% |
| SC | Charleston | 199 | 197 | 197 | 0 | 100.0% | 99.0% |
| SC | Greenville | 199 | 169 | 168 | 1 | 99.4% | 84.4% |
| SC | Saluda | 181 | 180 | 180 | 0 | 100.0% | 99.4% |
| SC | Colleton | 176 | 170 | 170 | 0 | 100.0% | 96.6% |
| | 27 smaller counties (25 to 149 leads each) | 1,572 | 1,429 | 1,426 | 3 | 99.8% | 90.7% |

Counties under 99% with at least 100 verified leads: Lancaster 98.5% (4 wrong, all with the same owner) and Burke 98.5% (4, different owners). The
37 wrong answers are one kind: the source's parcel has the same number and street name as the lead but a different suffix,
town, direction or unit (`341 Allen St.` against a parcel at `341 ALLEN CT`; `133 LAVERNE AVE` against `133 LAVERNE AVE, Unit A`).
They are cases where the source's own parcel and address disagree, so which side is right is not settled by the data.

### 5.3 Why this rule

The hold-out above cannot see the main danger: a lead whose true parcel is not in the cache (new construction, a parcel the
county has not published a situs for) and a different parcel that shares its number and one street word. So a second test
hides the lead's own parcel from the index and counts how often each rule still returns a unique parcel; every such answer
is wrong. Both tests run on the same hold-out (capped at 1,500 leads per county, 17,150 leads). In the second test a sibling parcel
at an identical situs is not counted as a false match, because in real use both parcels would be present and the answer would be ambiguous.

| Rule | Precision, true parcel present | Recall | False match, true parcel absent |
|---|--:|--:|--:|
| A. Older Burke rule: house number and one shared word | 99.92% | 83.8% | 5.21% |
| B. House number and full street name | 99.91% | 93.4% | 2.54% |
| C. B and suffix agrees when both state one | 99.86% | 94.4% | 1.63% |
| D. C and direction agrees (quadrant may go unstated) | 99.83% | 94.4% | 0.34% |
| **E. D and town agrees when both state one (chosen)** | **99.83%** | **93.3%** | **0.22%** |

With the true parcel present every rule clears 99.8% because a second parcel at the address makes the match ambiguous. The
rules differ in what they do when the true parcel is missing: the older rule hands back a wrong parcel about 24 times as often.
The direction rule removes most of the remainder (1.63% to 0.34%: "125 MAIN ST" is not "125 W MAIN ST") and costs no recall
here (it turns some ambiguous answers into unique ones and rejects others). The town rule costs 1.1 points of recall for 0.34% to
0.22%. Before the last change a direction could go unstated on one side: that resolved 26,901 of the 28,350 verified leads (94.8%
recall) with a 0.6% false-match rate; the final rule resolves 26,585 (93.6%) at 0.2%. Precision beats recall, so the strict
version stays.

### 5.4 Source fidelity and the deny list

For each source, the share of its parcel-bearing rows whose own parcel sits at its own street (same measure as 5.1).
`DENY_SOURCES` in the script skips a source whose street is measured not to be the parcel's situs:

| Source | Hold-out rows | Street at own parcel | Why |
|---|--:|--:|---|
| nc_county_pdf_delinquent_tax | 1,029 | 7% | the street is the taxpayer's mailing address |
| buncombe_unpaid_bills | 401 | 23% | bill mailing address |
| lincoln_vacant | 1,903 | 30% | vacant-lot list carries an address that is not the lot |
| hud_reac_inspection | 112 | 31% | apartment complexes, many parcels per address |
| nc_ptscloud_delinquent_tax | 247 | 44% | taxpayer mailing address |
| landwatch | 171 | 50% | land-listing address is approximate |
| asheville_helene | 102 | 49% | permit address, neighbouring parcel |
| landandfarm | 186 | 59% | land-listing address is approximate |
| asheville_str_permits | 537 | 59% | permit address, neighbouring parcel |
| gaston_vacant | 6,957 | 62% | vacant-lot list |
| sc_rod_acclaim | 118 | 62% | register-of-deeds party addresses |
| nc_ecourts_lis_pendens, sc_flc, shapiro_ingle_powerbi | 62, 51, 63 | 39%, 39%, 64% | notice addresses |

Of these only nc_county_pdf_delinquent_tax (150), landwatch (230) and landandfarm (128) have address-only leads today (556
leads skipped in all, including the small ones). Borderline and not denied: courtlistener_bankruptcy 70%, brock_scott 67% (10
address-only leads). Not on the list on purpose: liensnc (29%, because its existing parcels are often a neighbour's, section 5.5), and the
Transylvania sources (their cache holds lot text; they simply do not match).

### 5.5 liensnc: the existing parcels are the problem

liensnc is 29,457 of the targets, and its hold-out truth is the weakest: 14,602 liensnc rows already carry a parcel, and of the
11,572 whose parcel has a cache situs only 29% sit at the row's own address. Sampling shows why. `4116 Balsam Drive` (Revolution Homes) carries the parcel of `4028 BALSAM DR`;
`2924 Hinsdale Street` (Eric & Lindy Andresen) carries `2906 HINSDALE ST` owned by Norman K Cook, while the address resolves to
`2924 HINSDALE ST`, owner ERIC ANDRESEN. The existing parcel is a neighbour's; it looks to have been picked from approximate
coordinates (the rows carry no provenance stamp for it).

Of the 11,234 liensnc rows whose parcel is in the cache: 6,779 have an address that resolves uniquely. In 2,779 (41%) that
parcel is the row's existing one. **In 4,000 (59%) it is not, and the existing parcel's situs is at a different address (3,999
of them).** Owner agreement with the lead separates the two: the existing parcel's owner agrees with the lead on 126 of the 4,000 (3.2%),
the address-resolved parcel's owner on 1,803 (45.1%). So the existing parcel is the wrong one in these cases. Second, the resolved
set is not visibly diluted by wrong parcels: owner agreement over all 13,713 resolved liensnc leads is 51.1%, against 50.4% for the
2,779 where the existing parcel independently confirms the address. The 4,000 differing leads sit 5 points lower (45.1%). That
gap is consistent with about 10% wrong parcels there, and equally with lots whose cache owner is still the seller or the
builder's predecessor, so read it as a ceiling on the error in that group, not an estimate. This is indirect evidence, not a measurement.

Consequence for the board, outside this script: those 4,000 leads currently take mailing, value, sqft and acreage from a neighbour's parcel when `join_parcel_cache_to_board` runs.
A repair in the shape of `repair_burke_storm_damage_parcels.py` (replace the parcel when the existing parcel's situs disagrees
with the row's address and the address resolves uniquely, keep the old id in `backups/`) would fix them. It is not done here
because this script never replaces an existing parcel.

### 5.6 Expected precision on the real target

The target differs from the hold-out: its parcels are often absent from the cache (22,685 of 45,554 do not match). The two
measured error rates apply to different leads: the present-truth error to leads whose parcel is in the cache, the absent-truth
error (a unique parcel returned when the true one is missing) to the leads whose parcel is not. Upper-bound estimate, treating
every non-match as an absent parcel:

| Class | Resolved | Present-truth error | Absent-truth error x non-matches | Expected wrong | Precision |
|---|--:|--:|--:|--:|--:|
| liensnc | 13,713 | 0.03% (1 of 2,885) | 0.03% x 14,956 | about 9 | 99.9% |
| all other sources | 5,564 | 0.34% (23 of 6,755) | 0.76% x 7,729 | about 78 | 98.6% |
| **Total** | **19,277** | | | **about 87** | **99.55%** |

The floor (no absent-parcel error at all) is 99.86% overall and 99.7% for the other sources. So liensnc clears 99% with room, the
hold-out clears it, and the sources other than liensnc are the ones that can fall a little under it: use the owner-agreement tier below
where a contact or a bid depends on them. The liensnc rates rest on one wrong answer in 2,885 and are soft.

## 6. Trust tiers and what the join does with them

| Tier | Leads | What it means |
|---|--:|---|
| `owner_agrees: true` | 7,349 (liensnc 7,004) | address and owner name both agree: treat as confirmed |
| `owner_agrees: null` | 2,504 (liensnc 3, spartanburg_property_cleanup 1,746) | the lead has no owner name; address only |
| `owner_agrees: false` | 9,424 (liensnc 6,706, nc_ust_incidents 1,169, sc_dew_lien_registry 1,254) | the lead's party is a builder, a tenant, a business or a debtor, or the parcel has a new owner; the parcel is right about the property and may be wrong about the person |

`join_parcel_cache_to_board.py` copies the parcel owner's mailing into `raw.gis.mailing` and, when the lead has none, into
`raw.owner_mailing`. For a lead whose owner differs, that puts a stranger's mailing address under the lead's name. Value, sqft and
acreage are property facts and are safe. Suggested change to the join (not made: not my file), inside the `if hit.get("owner_mailing"):`
condition:

```python
        pfa = li.raw.get("parcel_from_address") if isinstance(li.raw, dict) else None
        owner_differs = isinstance(pfa, dict) and pfa.get("owner_agrees") is False
        ...
        if hit.get("owner_mailing") and not owner_differs:
```

Withholding those mailings costs 2,704 of the 5,468 new mailing fills (NC 1,328 of 2,090, SC 1,376 of 3,378); the safe
lift is then NC +762 (0.8 pp) and SC +2,002 (2.6 pp). Whether to withhold is a decision for the owner: for UST and DEW leads the
parcel owner may be exactly the person to write to.

## 7. Expected lift

If the existing join runs on the resolved leads (fill-only, so it adds only what the lead lacks and the parcel row has):

| State | Rows | Resolved | Parcel | Mailing | Owner name | Market value | Tax value | Sqft | Acreage |
|---|--:|--:|--:|--:|--:|--:|--:|--:|--:|
| NC | 93,030 | 15,805 | 55.4% to 72.4% (+17.0 pp) | +2,090, 89.8% to 92.0% (+2.25 pp) | +496 (+0.53 pp) | +13,744, 51.2% to 66.0% (+14.77 pp) | +12,799 | +755 (+0.81 pp) | +14,247 (+15.31 pp) |
| SC | 77,036 | 3,472 | 71.4% to 75.9% (+4.5 pp) | +3,378, 44.8% to 49.2% (+4.38 pp) | +1,928 (+2.50 pp) | +2,991, 30.3% to 34.2% (+3.88 pp) | +1,694 | +11 (+0.01 pp) | +1,615 (+2.10 pp) |

Board-wide, parcel coverage goes from 106,510 to 125,787 rows (62.6% to 74.0%). New mailing fills by owner agreement, NC: agrees
266, differs 1,328, unknown 496; SC: agrees 74, differs 1,376, unknown 1,928. NC gains value and acreage far more than mailing
because liensnc rows already carry the mailing from the filing. Sqft barely moves: the NC caches carry it for few parcels and
almost no SC cache carries it at all.

Where the fills land (resolved, and what the join adds): Wake 3,171 (market value 2,984), Spartanburg SC 1,871 (mailing 1,854,
owner 1,810, value 1,654), Brunswick 1,688 (value 1,449), Buncombe 1,388 (mailing 1,156, value 1,171), Durham 1,050 (value 825),
Horry 976 (mailing 974, value 969), Mecklenburg 710, Gaston 673 (mailing 377), Harnett 574, Union 547.

## 8. Two diagnoses from the brief

### 8a. Florence SC shows 0% value after the join

Florence: 2,006 board rows, 2,005 with a parcel, 688 that hit the cache (34%), no value on any of them. There are two separate causes.

**Value is not a join or id problem and not a mapping bug.** The Florence cache holds 140,049 index rows (70,098 parcels) and
`market_value`, `tax_value`, `living_sqft`, `land_use`, `sale_price` and `sale_date` are NULL on every one of them. The layer
publishes `TOTBDGVAL` (building value only; land and total value are not published on it), and
`PARCEL_LAYERS["Florence"]["map"]` leaves it unmapped on purpose (its own comment, and `docs/county_breadth_research_2026-09-21.md`).
Nothing in that table can produce a value. Mapping `TOTBDGVAL` to `market_value` would put a building-only figure on every improved parcel
and 0 on vacant land, which understates ARV. The only real fix is another value source for Florence (the county assessor). I did not edit the table.

**Two thirds of the board ids do not hit the cache, and that is fixable.** Measured on all 2,005:

| Board id | Rows | Hit now | Why |
|---|--:|--:|---|
| `21000-35-305` shape (NN000-SS-TTT), `is_mobile_home: true` in the raw block | 444 | 0 | mobile-home personal-property accounts from the "Mobile Homes" tax sale list, not parcels; nothing to resolve |
| 5-2-3 TMS with a full 5-digit first segment (`90073-05-005`) | 688 | 688 | fine |
| TMS with an unpadded first segment: `47-03-060`, `151-01-137`, `1012-01-215` | 817 | 0 | the cache holds the dashed 5-2-3 form `00047-03-060`, so the id must be left-padded |
| other, not in the cache | 56 | 0 | |

Padding the first segment to 5 digits makes 817 of them hit, and the delinquent taxpayer's name agrees with the cached owner on
658 of the 817 (80.5%; the rest are mostly sold parcels, for example taxpayer ALEXANDER ASHLEY F against current owner MILLS BENJAMIN T).
Florence would go from 688 hits (34% mailing) to 1,505 (75%). Exact fix, in `src/foreclosure_scraper/parcel_cache.py`, scoped to Florence
because the pattern could hit an unrelated parcel in another county's numbering:

```python
_ZERO_PREFIX_TMS = re.compile(r"\s*(\d{1,4})[-.\s](\d{2})[-.\s](\d{3})\s*")

def _zero_prefix_candidates(v) -> list[tuple[str, str]]:
    m = _ZERO_PREFIX_TMS.fullmatch(str(v or ""))
    return [(f"{int(m.group(1)):05d}{m.group(2)}{m.group(3)}", "zero_prefix")] if m else []

# in lookup_with_tier(), where it loops over candidates:
    cands = _lookup_candidates(parcel_id)
    if county == "Florence":
        cands = cands + _zero_prefix_candidates(parcel_id)
    for k, tier in cands:
        ...
```

This resolves ids, not values: after it, Florence mailing rises and value stays at 0% until a value source exists. The same
padding is cheaper than a crosswalk because the delinquent list itself prints the TMS without its leading zeros.

### 8b. Horry SC mail stays at 35%

It is not an id-format mismatch. Horry has 4,254 board rows and 1,486 with a mailing (34.9%).

| Horry rows | Rows | With a mailing |
|---|--:|--:|
| No parcel_id at all (1,765 of them have a street) | 1,769 | 0 |
| 11-digit PIN that hits the cache | 1,494 | 1,486 |
| 11-digit id starting `99` (`99800029462`, owner `A & B MOBILE HOME PARK`, legal `OAKEY SWAMP MHP LT`) | 927 | 0 |
| other 11-digit or short ids not in the cache | 64 | 0 |

The board's 11-digit legacy PIN matches the cache's `PINtext` ids exactly: 1,494 of the 1,558 ids that do not start with `99`
(96%), and 1,486 of those 1,494 hits already have their mailing (the cache holds 744,488 mailing addresses). What holds the rate down is that 42% of Horry rows have
no parcel to join on, and that 22% carry `99...` account numbers for manufactured-home-park lots, which are not parcels and are not in
the parcel layer (the qpaybill scraper writes `is_account_id_not_parcel: False` on them). This script gives 976 of the 1,765
address-only Horry leads a parcel and 974 of them take a mailing: **Horry mail 34.9% to 57.8%.** The 927 `99...` rows have no street
address either, and need the scraper to stop presenting the account number as a parcel_id.

## 9. Apply, blockers, follow-ups

1. **RAW_KEEP (blocker, one line).** `web_artifact._slim_raw` drops keys not in `RAW_KEEP`. Add after `"resolver_conflict_undone": "*",`
   (line 1476 today) in `src/foreclosure_scraper/web_artifact.py`:

   ```python
       "parcel_from_address": "*",        # parcel resolved from the lead's own street address {source, verified, county, state, matched_situs, cache_owner, owner_agrees, id_basis, cache_ids}
   ```

   Until it is added, `tests/test_required_raw_keys_registered.py::test_every_required_raw_key_is_in_raw_keep[resolve_parcel_from_address.py]`
   fails on purpose and `apply_rows` refuses a real run. `_SLIM_RAW` and `dashboard.js` `_LEAN_RAW` are needed only if the dashboard should show
   `owner_agrees`.
2. **Apply.** `python scripts/apply_board_fixes.py --apply` (all steps in one load; `parcel` runs after `county` and `flip`, before `address` and
   `join`). Or `--steps county,parcel,address,join --apply`. Then `recompute_valuation.py` and `rank_board_standalone.py`. Run it as the only board process.
3. **Decision: the join and `owner_agrees: false`** (section 6): 2,704 of the new mailing fills go under a different party's name.
4. **Follow-up, separate task: repair the existing liensnc parcels** (section 5.5): about 4,000 rows carry a neighbour's parcel.
5. **Follow-up: situs overlays** for the caches with none (Guilford, Cabarrus, Oconee, Orange, Franklin, Hoke, Transylvania, Richmond, Perquimans, Bladen, Avery: 3,199 leads) and
   for Charleston (32%); caches for Beaufort SC, Cherokee SC, Georgetown, Union SC, Orangeburg (1,782 leads); Greenwood is pending.
6. **Follow-up: Florence** id padding (section 8a) and Horry `99...` ids (section 8b).
7. **Residual risks the measurements cannot see.** The county on a liensnc row is the county the filer picked; a filer's wrong county
   (about 1% by the county-backfill measurement) can only produce a wrong match when the same number and street exist in that county's cache, and the
   ZIP guard catches some of them. A cache that is weeks behind the county (new construction) produces no match, not a wrong one, except for the 0.22% above.
   Sources not in `DENY_SOURCES` with few hold-out rows (usda_properties, buncombe_hmgp_buyout, buncombe_landslide_damage) are assumed to print the site address.

Confirmation on the current board: the CLI run at the end of this work, on the republished 182,388-row board (NC 99,438, SC 82,950), gave 45,964 eligible leads,
19,619 resolved, 336 ambiguous, 22,716 no match, hold-out 28,461 of 28,498 correct (99.87%), recall 93.8%. The board grew by about 12,300 rows between the extract and that run,
so the county table above is the 15:51 snapshot.

## 10. Files, tests, budget

* `scripts/resolve_parcel_from_address.py` (replaces the earlier exact-match script, section 3).
* `tests/test_dq_resolve_parcel_from_address.py`: 46 tests, offline, synthetic caches in a temp dir. Parsing, the agreement rule
  (full name, suffix, direction, quadrant, town), uniqueness over duplicate id rows, placeholder ids, units, ZIP, id choice, source and county guards,
  dual-state caches, the `apply_rows` contract (dry run mutates nothing, real run fills and stamps, idempotent, RAW_KEEP refusal), the hold-out and the lift.
* `scripts/apply_board_fixes.py`: step `parcel` added (one line); `tests/test_apply_board_fixes.py`: order assertions added.
* Tests run: `tests/test_dq_resolve_parcel_from_address.py` (46 passed), `tests/test_apply_board_fixes.py` and `tests/test_dq_apply_rows_contract.py` (passed), and the
  raw-key test for this script (fails until section 9.1).
* Board passes: three full streaming passes of `docs/listings.json.gz` (an extract, a side capture for the Florence and Horry blocks, the final CLI run) and two partial reads; `load_board`
  and `write_artifact` never called, nothing applied, no network, nothing staged or committed.
