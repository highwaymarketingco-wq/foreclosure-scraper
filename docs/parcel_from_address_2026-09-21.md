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
| **Repair of parcels at another address** (sections 11 and 12) | 6,342 disagreeing parcels in 7 repairable sources: **3,644 replaced** (liensnc 3,623), **2,323 withdrawn** (the street resolves to nothing unique: the neighbour's values blanked and the parcel_id cleared), 375 kept by an owner guard; hold-out precision 99.8% |

What blocks or shapes the apply is in section 9. Short list: one RAW_KEEP line for the lead to add, a decision on the join for
leads whose parcel owner differs from the lead's owner, and a separate finding: about 4,000 liensnc leads already carry a
parcel that sits at a different address than their own (section 5.5, repaired in section 11).

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
`resolve_parcel_from_address.py` never replaces an existing parcel. The repair is a separate script,
`repair_parcel_from_address.py` (section 11), which replaces the parcel when the existing parcel's situs disagrees with the row's address
and the address resolves uniquely, and keeps the old id in `backups/`.

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

1. **RAW_KEEP (done by the lead, line 1477 today).** `web_artifact._slim_raw` drops keys not in `RAW_KEEP`. The line is:

   ```python
       "parcel_from_address": "*",        # parcel resolved from the lead's own street address {source, verified, county, state, matched_situs, cache_owner, owner_agrees, id_basis, cache_ids}
   ```

   Without it `tests/test_required_raw_keys_registered.py` fails on purpose and `apply_rows` refuses a real run. `_SLIM_RAW` and `dashboard.js`
   `_LEAN_RAW` are needed only if the dashboard should show `owner_agrees` or `replaced_parcel`. The repair (section 11) stamps the same key, so it needs no new line.
2. **Apply.** `python scripts/apply_board_fixes.py --apply` (all steps in one load; `parcel` runs after `county` and `flip`, before `address` and
   `join`). Or `--steps county,parcel,address,join --apply`. Then `recompute_valuation.py` and `rank_board_standalone.py`. Run it as the only board process.
3. **Decision: the join and `owner_agrees: false`** (section 6): 2,704 of the new mailing fills go under a different party's name.
4. **Done: repair of the existing liensnc parcels** (section 11): 3,644 replaced. **Done: withdrawal** of the neighbour's parcel and copied values on 2,323 more (section 12).
   **Open:** a guard in `enrichment_parcel_from_geo` so a full pipeline run does not re-attach the same parcel from coordinates (section 12.4).
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
* Board passes for sections 1 to 9: three full streaming passes of `docs/listings.json.gz` (an extract, a side capture for the Florence and Horry blocks, the final CLI run) and two partial reads; `load_board`
  and `write_artifact` never called, nothing applied, no network, nothing staged or committed.
* Section 11 adds `scripts/repair_parcel_from_address.py`, `tests/test_dq_repair_parcel_from_address.py` (54 tests), the `parcel_repair` step in `scripts/apply_board_fixes.py` and its order assertions in `tests/test_apply_board_fixes.py`, and a
  one-line change to `scripts/resolve_parcel_from_address.py` (its hold-out leaves out parcels it wrote). Its board passes: four streaming dry runs, one at a time (each after a code change; the numbers in section 11 are the last) and one early-exit
  read of a few rows to see the `gis_attrs_full` bag, plus one more streaming dry run for section 12; `load_board` and `write_artifact` never called, `--apply` never run.

## 11. Repair of parcels that sit at another address

`scripts/repair_parcel_from_address.py`, step `parcel_repair` of `scripts/apply_board_fixes.py` (right after `parcel`, before `address` and
`join`). Function `apply_rows(rows, *, dry_run=False)`, also exported as `repair_rows`. Every count below is a streaming dry run of the live
board after the resolver was applied (182,388 rows, one pass, 83 s, 709 MB). Nothing was applied and `load_board` was not called.

### 11.1 The rule

A parcel is replaced only when all of these hold; otherwise it is left exactly as it is.

1. **The parcel is not the source's own.** Only sources whose scraper never sets a `parcel_id` are repaired (`REPAIRABLE_SOURCES`, section 11.2).
   Denied sources, tax-sale overage claims, parcels the name resolver or the address resolver wrote, and streets that were copied from a parcel
   cache are skipped.
2. **The existing parcel clearly disagrees.** Its id is in the cache, its situs parses as a numbered street (every part of a multi-address situs
   does), and it fails all three agreement tests: same number and street name; the resolver's full rule with the town ignored; the older Burke
   test (same number and one shared word). So a different house number on the same street, or a different street, is a disagreement, and these are
   not: a different suffix, a unit, a leading zero, a direction, a missing or legal-text situs, an id that is not in the cache, a lead street that is
   a range or road-only.
3. **The address resolves uniquely to a different parcel** under the resolver's acceptance rule (full name, suffix, direction, town, unit, ZIP,
   specific id, exactly one parcel).
4. **Owner guard.** If the existing parcel's owner agrees with the lead's owner and the new parcel's does not, the address is more likely a typo than the
   parcel a neighbour's, so the parcel stays. A lead owner that is the old parcel's owner spelled exactly as the cache spells it is treated as copied by
   the join, not as evidence (both verdicts become unknown).

What a replacement writes: `parcel_id` (the board's own spelling of the new parcel when one is on the board), and `raw['parcel_from_address']`
as the resolver writes it plus `replaced_parcel`, `replaced_situs`, `replaced_cache_owner`, `replaced_owner_agrees`, `cleared_from_old_parcel` and
`verified: address_exact_unique_replaced_disagreeing_parcel`. The old parcel id and everything cleared go to the returned `_backup`
(`backups/repair_parcel_from_address_replaced_<stamp>.json`, keyed by row index, with source_url, old and new parcel, old and new situs and owner, and each
cleared value).

**What it clears.** The join writes no provenance, so nothing is cleared on suspicion: a field is cleared only when its value equals what the OLD parcel's cache row
holds, or (for a parcel-layer block) when the block names the old parcel. The next join step refills them from the new parcel.

| Field | Cleared when |
|---|---|
| `market_value`, `tax_value`, `living_sqft`, `acreage`, `land_use` | equal to the old cache row's |
| `owner_name` | exactly the old cache owner string (the join copies it verbatim) |
| `raw.gis` `mailing`, `owner`, `market_value`, `tax_value`, `acreage`, `living_sqft`, `land_use` | equal to the old cache row's (mailing and owner compared without case or punctuation) |
| `raw.gis.last_sale` | its amount equals the old cache sale price |
| `raw.owner_mailing` (whole block) | its `source` is a parcel layer (none, `county_gis`, `nc_onemap`, `scdot_sc`, `sc_assessor_roll`, `county_tax_roll`, `henderson_county_gis`) AND its mailing equals the old cache mailing or it names the old parcel. A filing's own block (`liensnc_filing`) is never cleared |
| `raw.gis_attrs_full` (NC OneMap bag) | a parcel-number field (`parno`, `pin`, `reid`, ...) is the old parcel, or its `siteadd` and `ownname` are the old cache row's |

Not cleared, because they are derived and the chain recomputes them (`recompute_valuation.py`, `rank_board_standalone.py`): `raw.calc`, `raw.distress_stack`, and the
scores. A few `raw.gis` keys that do not match the old cache row stay (owner 12, last_sale 5, mailing 4 of the 3,644).

### 11.2 Which sources

A tax roll's `parcel_id` is what the bill is for. When its street differs, the street is the taxpayer's mailing address or a lot description, and the parcel is right.
Measured on the 2,243 parcel-bearing rows of sources that own their parcel where the situs clearly disagrees with the street (qpaybill 474, charlotte_open_data 420, rutherford_tax 399,
buncombe_elderly 276, new_hanover_demolition_permits 152, berkeley_paystar_tax 108, spartanburg_delinquent_tax 45, and others): the parcel's owner agrees with the row's owner on
1,275 (57%). Examples: `36 PIERCY ST` against a parcel at `38 PIERCY ST`, both GOEHRING KITTY; `660 BEE TREE RD` against `662 BEE TREE RD`, both MARINELL LEDFORD. Replacing those
parcels would break the debt they belong to, so they are never touched.

For the repairable sources the same measure is 2.7% (the old parcel's owner agrees with the lead's on 98 of the 3,644 replaced): the parcel was attached later, and the owner does not match.

`REPAIRABLE_SOURCES` lists the sources whose scraper source contains no `parcel_id`, so any parcel on their rows was attached by an enricher. Each is a source whose street is the
property or facility site: liensnc, sc_dew_lien_registry, nc_ust_incidents, nc_dam_safety, sc_ust_registry, fannie_homepath, brock_scott.
`tests/test_dq_repair_parcel_from_address.py::test_every_repairable_source_has_a_scraper_that_never_sets_a_parcel_id` reads the scraper files and fails if one starts setting a parcel id.
Not included although their scrapers set no parcel id, because their street may not be the property: courtlistener_bankruptcy (the debtor's address; 25 disagreeing rows), hud_section8_contracts (8), hutchens (7),
estate_sales, crexi_multifamily, zillow_bulk, sc_public_index_lis_pendens (under 5 each).

### 11.3 Results

Parcel-bearing rows of the repairable sources, and how they classed (the other columns of the 6,342 are in the next table):

| Source | Checked | Existing parcel agrees | Disagrees | Situs not comparable | Id not in cache |
|---|--:|--:|--:|--:|--:|
| liensnc | 13,626 | 3,445 | 6,212 | 3,490 | 479 |
| sc_dew_lien_registry | 1,385 | 1,315 | 52 | 13 | 5 |
| nc_ust_incidents | 350 | 301 | 38 | 9 | 2 |
| sc_ust_registry | 761 | 732 | 14 | 14 | 1 |
| nc_dam_safety | 61 | 52 | 4 | 4 | 1 |
| fannie_homepath | 176 | 153 | 12 | 10 | 1 |
| brock_scott | 60 | 46 | 10 | 3 | 1 |

(Rows whose parcel the address resolver wrote in the last apply, 16,329 board-wide, are skipped: they agree with their street by construction.)

**6,342 disagreeing parcels. 3,644 replaced** (NC 3,632, SC 12). By source: liensnc 3,623, sc_dew_lien_registry 9, brock_scott 5, nc_ust_incidents 5, fannie_homepath 2.
The other 2,698 have no unique replacement: the street matches no cache parcel 2,569, its id is a shared placeholder 58, two parcels 30, ZIP conflict 28, owner guard 9, unit 4. Section 12 withdraws 2,323 of them. The 3,644 is below the
4,000 of section 5.5, which was measured on the resolver's hold-out extract and counted any unique different parcel; the repair also leaves parcels that agree by the Burke test (a suffix-only difference) and applies the owner guard and the eligibility gates.

By county (86 counties; the dry run prints all of them):

| State | County | Replaced | Disagreeing |
|---|---|--:|--:|
| NC | Mecklenburg | 469 | 807 |
| NC | Wake | 459 | 617 |
| NC | New Hanover | 368 | 701 |
| NC | Durham | 220 | 279 |
| NC | Iredell | 160 | 322 |
| NC | Brunswick | 152 | 225 |
| NC | Buncombe | 144 | 213 |
| NC | Henderson | 137 | 209 |
| NC | Catawba | 126 | 178 |
| NC | Forsyth | 97 | 168 |
| NC | Burke | 91 | 147 |
| NC | Cumberland | 73 | 116 |
| NC | Moore | 70 | 96 |
| NC | Union | 59 | 95 |
| NC | Onslow | 54 | 103 |
| NC | Johnston | 52 | 103 |
| NC | Currituck | 43 | 48 |
| NC | Dare | 41 | 61 |
| NC | Craven | 40 | 49 |
| NC | Rowan | 39 | 109 |
| NC | Alamance | 37 | 73 |
| NC | Pitt | 37 | 54 |
| NC | Pasquotank | 35 | 39 |
| NC | Watauga | 34 | 46 |
| NC | Chatham | 32 | 56 |
| | 61 other counties (SC: Spartanburg 5, Pickens 4, Laurens 3) | 575 | 1,326 |
| | **Total** | **3,644** | **6,240** |

(102 more disagreeing leads sit in counties with no replacement.)

Owner evidence on the replaced (old parcel agrees with the lead's owner, new parcel agrees): (no, no) 2,002; (no, yes) 1,534; (yes, yes) 98 (a builder with adjacent lots, so the
address decides); unknown 10. The new parcel's owner agrees on 1,633 of 3,644 (44.8%), the old parcel's on 98 (2.7%), the same contrast section 5.5 measured on the extract. The join
withholds the parcel owner's mailing where `owner_agrees` is false, so for the 2,002 leads whose new owner differs the old mailing is cleared and not replaced; a liensnc lead keeps the
mailing from its own filing.

Cleared, counts of leads (all 3,644 lose at least one field): `raw.gis.mailing` 3,635, `raw.gis_attrs_full` 3,605, `raw.gis.owner` 3,596, `market_value` 3,503, `acreage` 3,433, `tax_value` 600,
`living_sqft` 107, `raw.gis.last_sale` 72, `raw.owner_mailing` 18, `owner_name` 7, `land_use` 2.

**The values these leads carried were wrong.** Of the 3,245 replaced leads that held the old parcel's market value, the median was 456,930 and the new parcel's is 305,200; the new value differs from
the old by more than 20% on 2,142 of them (66%). Those leads' equity and ARV were computed from a neighbour's house.

**Not replaced:** 2,698 disagreeing leads have no unique replacement. Each still carried a parcel at another address and values copied from it (`raw.gis.mailing` 2,682, `market_value` 2,555, `acreage` 2,541,
`raw.gis_attrs_full` 2,232, `raw.gis.owner` 2,160, `tax_value` 817, `owner_mailing` 110, `living_sqft` 109). Section 12 withdraws them (2,323) or keeps them under the owner guard (375).

### 11.4 Hold-out

**Agreeing parcels are never touched.** Only a lead classed "disagrees" reaches the replacement step. On the hold-out (39,085 leads from any source with a parcel and a street, parcels the resolver wrote
excluded) 19,506 agree and are never touched, 6,374 disagree, 8,574 are not comparable and 4,631 have an id that is not in the cache. In the dry run, 0 of the 3,644 replaced leads has an existing parcel that agrees with
the street by the Burke or the name test (the guard check line). Tests cover suffix-only, unit, leading-zero, missing, legal-text and not-in-cache parcels: none is replaced.

**Corrupt and repair.** Each verified hold-out lead (its own parcel is at its address) is given a wrong parcel from the same county, then the production path runs (disagreement test, unique resolution, owner guard) and the
true parcel is checked:

| Wrong parcel given | Corrupted | Restored | Wrong | Precision | Recall | Not restored |
|---|--:|--:|--:|--:|--:|---|
| same street, another house number | 9,500 | 8,774 | 17 | 99.81% | 92.4% | withdrawn 656, kept because the owner agrees with the wrong parcel 19, owner guard on a unique match 34 |
| another street | 18,691 | 17,471 | 27 | 99.85% | 93.5% | withdrawn 1,182, kept (owner agrees) 1, owner guard on a unique match 10 |

Precision is restored over restored plus wrong. A lead that is not restored is withdrawn (section 12: the wrong parcel is blanked, which is right because it is wrong by construction) or kept by a guard; neither counts as wrong. The wrong ones are the resolver's known kind (section 5.2): the source's own parcel is at `341 ALLEN CT` and the street says `341 Allen St.`;
`133 LAVERNE AVE` against a unit parcel; `15 MCLEOD ST` against `15 W MCLEOD ST`. That is the resolver's 99.8%, unchanged, because a replacement is the resolver's answer.

What the hold-out cannot show: the wrong parcels in the real data are the ones liensnc attached from coordinates, and the decoys here are random parcels of the same county. The independent evidence for the real data is the owner
contrast above (44.8% against 2.7%) and the 24-row sample read by eye, which showed the neighbour at the old parcel (`1709 Sunset Dr` carried `1701 SUNSET DR`) and the address's own parcel owned by the lead's owner
(HERNANDEZ JUAN F).

### 11.5 Applying it

* `python scripts/apply_board_fixes.py --apply` runs it in the chain (`parcel_repair` sits after `parcel`); or `--steps county,parcel,parcel_repair,address,join --apply`. The join must run after it, in the same load or a later one, to refill what was cleared, then
  `recompute_valuation.py` and `rank_board_standalone.py` for `calc` and the scores. Standalone: `python scripts/repair_parcel_from_address.py --apply`. Run it as the only board process.
* The step returns `_backup`; the driver writes it under `backups/`. To undo one lead, write `old_parcel_id` back and restore the entries in `cleared`.
* Idempotent: a replaced lead's parcel now agrees with its street, so a second run touches nothing.
* The RAW_KEY is the resolver's, already registered.
* `resolve_parcel_from_address.py` now leaves parcels it wrote out of its own hold-out (`raw.parcel_from_address` counts as derived). On a board where it has been applied those parcels agree with the address by construction, and counting
  them would inflate the resolver's hold-out; the counts in sections 1 to 9 were taken before the apply and do not change.
* Residual risks: the repair trusts the lead's street. A filer's mistyped house number that happens to match another real parcel would replace a right parcel with a wrong one; the owner guard catches it only when the owner agrees with the old parcel.
  Sources outside `REPAIRABLE_SOURCES` keep whatever parcel they have.

* Tests: `tests/test_dq_repair_parcel_from_address.py` (54 tests, offline, synthetic caches): the disagreement test, source and provenance gates, the scraper check on the list, replacement with backup and provenance, each clearing rule and its negative, the owner guard, unique
  resolution, idempotence, the RAW_KEEP refusal, the driver step and its backup file, the dry-run report, and the corrupt-and-repair hold-out. `tests/test_apply_board_fixes.py` asserts `county < parcel < parcel_repair < address < join`.

## 12. Withdrawal: a neighbour's parcel with no replacement

Decision from the lead: a wrong value or a stranger's mailing is worse than none, because it feeds ARV, equity and outreach. So a lead whose existing parcel clearly disagrees with its own street and whose
street resolves to no unique parcel loses the parcel and everything copied from it. It lives in the same `parcel_repair` step (`apply_rows(..., withdraw=True)`; the dry run takes `--no-withdraw`).
Counts are the live dry run of section 11 (182,388 rows, one pass, 72 s, 469 MB).

### 12.1 The rule

A lead is withdrawn when it is in the disagreeing set of section 11.1 (repairable source, existing id in the cache, numbered situs on both sides that clearly disagree) and one of these left it with no replacement:
no cache parcel has the street (`no_match`), the matching parcel's id is a shared placeholder (`no_specific_id`), two parcels have the street (`ambiguous`), the ZIP conflicts (`zip_conflict`), or the unit is not in the cache
(`unit_rejected`). Then, exactly as for a replacement, only values equal to the old cache row's are cleared (section 11.1 table), and `parcel_id` is cleared too, because the join needs a parcel_id to copy from.

Left untouched, everything the guards protect: a lead whose owner independently agrees with the old parcel (`left_owner_agrees_with_existing`: the street is more likely the typo, or one builder owns adjacent lots);
a unique replacement whose owner does not agree while the old one does (`left_owner_favours_existing`); the same parcel; an unreadable cache; an existing id that is not in the cache; a missing, unparseable or
legal-text situs; a suffix, unit, leading-zero or direction difference; a lead street that is a range or road-only; sources whose scraper sets a real parcel_id; denied sources; overage claims. The street stays on the
lead. The old parcel id and the cleared values go to `_backup` (`"action": "withdrawn"`), and `raw['parcel_from_address']` becomes
`{"source": "repair_parcel_from_address", "withdrawn_parcel": <old id>, "reason": "street_disagrees_no_unique_match", "match_status": "left_no_match" | ..., "withdrawn_situs", "withdrawn_cache_owner", "withdrawn_owner_agrees", "cleared_from_old_parcel", "county", "state"}`.
It has no `owner_agrees`, so the join's withholding rule is not triggered, and the join has nothing to do with it: no parcel_id.

### 12.2 Counts

Of the 6,342 disagreeing parcels: **3,644 replaced, 2,323 withdrawn, 366 kept because the owner agrees with the old parcel, 9 kept because a unique replacement's owner does not** (total 6,342).
The coordinator's estimate was about 2,600 withdrawals: 2,689 leads have no unique replacement, and the owner guard keeps 366 of them, leaving 2,323.

* Why there is no replacement: no match 2,211, placeholder id 53, ambiguous 28, ZIP conflict 27, unit 4.
* By source: liensnc 2,222, sc_dew_lien_registry 43, nc_ust_incidents 29, sc_ust_registry 14, fannie_homepath 10, brock_scott 4, nc_dam_safety 1. By state: NC 2,262, SC 61.
* The old parcel sits on the same street at another house number on 1,033 of them, on another street on 1,290 (`4116 Balsam Drive` carrying `4028 BALSAM DR`; a new-construction lot carrying `100 RALEIGH ST`, owned by the NORTH CAROLINA STATE PORTS AUTHORITY).
* The lead's owner against the old parcel's: disagrees on 2,286, unknown (blank owner) on 37. None agrees, by construction.
* Cleared, counts of leads (all 2,323 lose at least one field and the parcel_id): `raw.gis.mailing` 2,310, `market_value` 2,206, `acreage` 2,186, `raw.gis_attrs_full` 2,050, `raw.gis.owner` 1,978, `tax_value` 616, `owner_mailing` 102,
  `living_sqft` 90, `raw.gis.last_sale` 76, `owner_name` 32, `land_use` 1.
* Guard check: 0 of the 5,967 replaced or withdrawn leads has an existing parcel that agrees with its street by the Burke or the name test.
* The 366 kept by the owner guard: 358 liensnc, 4 nc_ust_incidents, 3 nc_dam_safety, 1 brock_scott. In 149 the old parcel is on the same street. They are a holding company or builder that owns the neighbouring lot
  (Q Edgewater Holdings on Sunrise Valley Pl, Davidson Homes on Well Fleet Dr, TRWG Holdings on Ridge Ave), so the owner and its mailing are right and only the lot's values are approximate. They keep the parcel.

Withdrawn by county (93 counties; the dry run prints all of them):

| State | County | Withdrawn | Disagreeing |
|---|---|--:|--:|
| NC | Mecklenburg | 320 | 807 |
| NC | New Hanover | 314 | 701 |
| NC | Iredell | 145 | 322 |
| NC | Wake | 95 | 617 |
| NC | Rowan | 65 | 109 |
| NC | Henderson | 64 | 209 |
| NC | Forsyth | 60 | 168 |
| NC | Brunswick | 59 | 225 |
| NC | Harnett | 58 | 95 |
| NC | Buncombe | 55 | 213 |
| NC | Burke | 51 | 147 |
| NC | Onslow | 49 | 103 |
| NC | Johnston | 47 | 103 |
| NC | Rutherford | 46 | 50 |
| NC | Cumberland | 39 | 116 |
| NC | Durham | 38 | 279 |
| NC | Polk | 37 | 39 |
| NC | Catawba | 35 | 178 |
| NC | Union | 33 | 95 |
| NC | Alamance | 33 | 73 |
| NC | Randolph | 32 | 46 |
| SC | Spartanburg | 31 | 36 |
| NC | Rockingham | 27 | 52 |
| NC | Cleveland | 27 | 37 |
| NC | Davidson | 26 | 61 |
| | 68 other counties (SC: Laurens 18, Pickens 5, Anderson 5, Colleton 1, Charleston 1) | 537 | 1,460 |
| | **Total** | **2,323** | **6,341** |

### 12.3 Hold-out

Withdrawal changes what happens to a corrupt-and-repair lead that is not restored (the table in 11.4): the wrong parcel is blanked (656 and 1,182 leads) or kept by the owner guard (19 and 1). Agreeing parcels are never touched:
19,506 of the 39,085 hold-out leads agree with their own parcel, and neither step reaches them. The false-withdrawal risk is a lead whose existing parcel is RIGHT while its street is wrong, and the owner does not agree; the hold-out
cannot measure that, the owner test is what covers it, and it found none among the 2,323 (2,286 owners disagree, 37 unknown). Read by eye (20 random withdrawals): every old parcel is at a different address and most are a different property altogether
(`539 N MAIN ST`, First Citizens Bank, for a lead in a subdivision; `100 RALEIGH ST`, NORTH CAROLINA STATE PORTS AUTHORITY, for D.R. Horton lots).

### 12.4 A hazard outside this script: coordinates

**2,263 of the 2,323 withdrawn leads carry coordinates.** `enrichment_parcel_from_geo` targets every lead with no parcel_id and coordinates in the state's box, and attached these leads' parcels in the first place. On a full pipeline run
(network) it would attach the same neighbour's parcel again, and the next join would refill the values. The chain in `apply_board_fixes` is offline and does not run it, so nothing is undone by `--apply`. To keep the withdrawal on a full run, add this to
`src/foreclosure_scraper/enrichment_parcel_from_geo.py` (not my file, not changed):

```python
def _withdrawn(li) -> bool:
    pfa = li.raw.get("parcel_from_address") if isinstance(li.raw, dict) else None
    return isinstance(pfa, dict) and bool(pfa.get("withdrawn_parcel"))

# _resolve_one, after `if li.parcel_id: return`:
    if _withdrawn(li):
        return
# enrich_parcel_from_geo, in the `targets` list comprehension:  ... and not _withdrawn(li)
```

Other enrichers that can write a parcel_id (`enrichment_county_pin`, `enrichment_ncpts_lrc`, `enrichment_sc_cama`, `enrichment_assessor_card` and the name resolvers) were not reviewed; they work from names, PINs in text or a
county lookup rather than from the coordinates, and none runs in the chain.

### 12.5 Later runs and reversal

* `join_parcel_cache_to_board.py` skips a lead with no parcel_id, so it cannot refill a withdrawn lead (tested, twice in a row).
* `resolve_parcel_from_address.py` (step `parcel`) treats a withdrawn lead as any address-only lead. If a cache later gains its street it resolves the lead, and now carries the withdrawal forward in the block
  (`withdrawn_parcel`, `withdrawn_reason`, `withdrawn_situs`); the repair then skips it. This chain runs `parcel` before `parcel_repair`, so a lead withdrawn in a run is next looked at on the following run.
* A second run of the repair finds nothing to do (a lead with no parcel_id is not looked at).
* To restore one lead: write `old_parcel_id` from the `_backup` entry back into `parcel_id` and put each `cleared` value back where its `kind` and `key` say.
* Derived fields (`raw.calc`, `raw.distress_stack`, scores) still reflect the old values until `recompute_valuation.py` and `rank_board_standalone.py` run; a withdrawn lead then has no value and no equity, where before it had a neighbour's.

### 12.6 Tests

`tests/test_dq_repair_parcel_from_address.py` (54 tests) now also covers: a withdrawal with its backup, block and cleared fields; each reason (no match, ambiguous, unit, ZIP, placeholder id) withdrawing; every guard protecting a lead from
withdrawal (owner agrees, id not in cache, road-only street, agreeing parcel, suffix-only, source's own parcel, denied source, name-resolved parcel, overage); a copied owner not counting as a guard; the join not refilling a
withdrawn lead across two runs; the resolver resolving a withdrawn lead once its cache gains the street, with the withdrawal kept on the record and the repair then skipping it; a replacement and a withdrawal in one run and one backup;
the driver step (repair, address, join) leaving the lead empty and writing the backup; `withdraw=False`; and the dry-run report.
