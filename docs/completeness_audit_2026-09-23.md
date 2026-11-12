# Completeness audit, 2026-09-23

Measured read-only on the live board, 192,805 rows (NC 115,471, SC 77,334), streamed once with `board_stream.iter_board_rows` (plus two more scoped streaming passes for the parcel-cache check, four passes total, against a budget of five; no `load_board`, no scraper or writer ran, no git command ran).

This is the second reading of the same board this month. The prior baseline is `docs/AUDIT_2026-09-21.md` sections 4, 5, 6 and 16, taken 2026-09-21 on a 170,528-row board (170,066 after that day's rescore, which is what section 16's address numbers use). This run published this morning (file timestamps 04:43-04:45), adding a net 22,277 rows since the baseline. Every number below is fresh; deltas against the baseline are called out explicitly, not implied.

## Bottom line

**No. Not one of the 146 counties, and none of the 18 footprint counties, meets a reasonable 100% bar.** Details and exact shortfalls follow. In summary:

- Address completeness *fell* since the baseline, not rose: 78.1% of rows have a street address now versus 80% on 2026-09-21, and rows with *neither* an address nor a parcel id grew from 9% to 11.5%. The board got bigger and less located at the same time.

- The address-quality bugs the September audit named (legal descriptions and generic placeholders stored as `street_address`) are still present, and the parcel-cache situs-disagreement class of error (the one the 2026-09-22 fix targeted) is **not fixed board-wide**: 4,803 rows (4.5% of the rows where the row's own address and the county parcel cache can both be checked) disagree with the county's own parcel record, across at least 25 different sources and inside footprint counties (Buncombe, Spartanburg, McDowell, Rutherford, Henderson, Gaston, Pickens, Lincoln, Burke among them).

- Of 146 NC+SC counties, only **5** carry all 7 distress families measured here, all 5 inside the 18-county footprint (Burke, Cleveland, Rutherford, Buncombe, Henderson NC). 141 of 146 are missing at least one family. That is real progress on the baseline's headline number (73 of 146 counties had exactly one family; now 65 do, plus 2 with zero rows at all), but it is not close to 100% breadth.

- None of the 18 footprint counties has its flip-type leads (foreclosure_sale, auction, reo, sheriff_sale, hoa_sale) fully identified, valued and mailable. The best is Gaston NC at 71% (45 of 63 flip leads have identity + value + mail together); the worst are Cherokee, Oconee and Union SC at 0%. Across all 18 counties combined, 32% of flip leads clear all three bars.


## 1. Address completeness

| Group | Rows | Street address | With a house number | Neither address nor parcel |
|---|--:|--:|--:|--:|
| **All (now)** | 192,805 | 150,617 (78.1%) | 139,069 (72.1%) | 22,092 (11.5%) |
| All (2026-09-21 baseline, 170,066 rows) | 170,066 | 136,056 (80%) | 124,905 (73%) | 15,743 (9%) |
| **NC (now)** | 115,471 | 88,682 (76.8%) | 79,942 (69.2%) | 14,668 (12.7%) |
| **SC (now)** | 77,334 | 61,935 (80.1%) | 59,127 (76.5%) | 7,424 (9.6%) |
| NC (2026-09-21 baseline) | 93,030 | 90% | 80% | 6% |
| SC (2026-09-21 baseline) | 77,036 | 68% | 65% | 13% |

Deltas: address share NC 90%→77%, SC 68%→80%; house-number share NC 80%→69%, SC 65%→77%. NC fell sharply and SC rose; net effect on the combined board is a small decline (address 80%→78%, house number 73%→72%) because NC is the larger state and NC's fall outweighs SC's rise. "Neither" rose in NC (6%→13%) and fell in SC (13%→9.6%). This is consistent with this run adding a large number of address-poor NC records (see Section 6: `albemarle_observer_tax_lists`, `rutherford_wildfire_tax`) while the SC parcel-cache backbone (Section 6, Berkeley/Horry/Charleston additions) kept lifting SC.

### Address-quality spot checks (item 2)

- **Legal-description-as-address**: 423 rows carry an address string that contains a legal-description marker (LOT/BLOCK/PHASE/PLAT/PARCEL) with no leading house number. Concentrated in `national.landandfarm` (land-listing scrape) and the ArcGIS distress feeds. Examples:
  - `Lot #44, Sardis Ct` (Lincoln NC, `counties_generic.arcgis_distress.lincoln_code_violations`)
  - `Parcel-3 Main Street` (Transylvania NC, `counties_generic.arcgis_distress.transylvania_damage_assessment`)
  - `Lot 25 Panther Mountain Road CVN-CVN-025` (Henderson NC, `national.landandfarm`)
  - `Lot 3B Broad River Highlands Dr` (Cleveland NC, `national.landandfarm`)
  - `Kiser Rd, Lot#WP009` (Rutherford NC, `national.landandfarm`)
  - `Coxe Rd, Lot#WP001` (Rutherford NC, `national.landandfarm`)
- **County-office / placeholder addresses**: 8 rows match a courthouse / government-center / clerk pattern. Two are a real bug, not a real street name: `224 GOVERNMENT CENTER DR` and `235 GOVERNMENT CENTER DR` on two different New Hanover demolition-permit parcels (`R05013-008-043-002`, `R05017-001-008-000`) - that is New Hanover's own county government building address, stamped onto two unrelated demolition records. One qPayBill Colleton SC row stores `REBECCA HILL CLERK OF COURT FRIERSON ALL` as the street address (parcel `164-11-00-001.000`) - a person's name and title, not an address at all. The repeated `Tryon Courthouse Road` hits in Gaston are a real street name in Gastonia, not a bug, and are included in the count as a false-positive caveat.
- **PO-Box addresses**: 24 rows, almost all `nc_ust_incidents` / `nc_dam_safety` facility registries (already excluded from PROPERTY scoring by the 2026-09-21 fix, A3) - these are legitimate facility mailing addresses, not situs, and were never meant to geocode a property.
- **A broken small scraper, confirmed and reproducible**: `national.estate_sales` (29 rows total) recycles a handful of malformed, glued-together address strings across *different* counties and states as if each were a distinct property's real address. `5986 springs rd, conover, ncHickory, NC 28601` (two city names run together with no separator) appears on 5 rows in Cleveland NC, Gaston NC, Spartanburg SC, Greenville SC and Mecklenburg NC - five different counties, five different (sometimes populated) parcel ids, one copy-pasted broken address. `210 s. piedmont aveKings Mountain, NC 28086` does the same across Buncombe, Henderson, Spartanburg and Gaston (4 rows). 12 of the source's 29 rows carry one of these recycled/malformed strings.
- **Document title stored as an address**: `counties_nc.albemarle_observer_tax_lists` stores the literal string `2025 delinquent property tax list` as `street_address` on 4 of its 1,756 rows (Tyrrell, Washington, Gates, Bertie NC) - a parsing miss where a list header leaked into the address field. Small in count, but the same source is also the single biggest driver of "has an address but the wrong kind" volume (see Section 6).
- **Road-name-only** (address present, no leading house number): 11,548 rows board-wide - this is the same phenomenon the baseline flagged for Transylvania's vacant-parcel source (75% address, 10% house number).

### Parcel-cache situs disagreement (the 2026-09-22 fix's own check, re-run fresh)

`parcel_cache.lookup()` was run for every row that carries a `parcel_id`, a `county` and a state of NC or SC - 129,387 rows, using the exact join the county GIS caches were built for. 107,857 of those found a cache match. Comparing the cache's own situs address to the row's own `street_address` (matching leading house numbers, or token overlap when neither has one):

- **4,803 rows (4.5% of rows with a cache hit) genuinely disagree** - the row's own address and the county's own record for that same parcel id describe two different locations.
- A further 366 rows only *look* like a mismatch because Buncombe's own parcel-cache data uses a `99999 ...` sentinel house number as its null placeholder for some parcels; those are excluded from the count above as a cache-side artifact, not a join error.
- **This is the same error class the 2026-09-22 fix (`8c8a91e`, "Never group or join on a parcel id shared by many distinct addresses") targeted, and it has reappeared on the fresh board.** That fix wired `dedupe.suspicious_parcel_keys()` into the *scorer's* grouping and the *parcel-cache join*, guarding against one parcel id being shared by many distinct addresses. It does not, and cannot, fix a source handing the wrong parcel id (or a mailing/suite address instead of a situs) to a *single* row in the first place - which is most of what is measured here. A clean live example of the exact bug the fix targeted, in a source the fix does not cover: parcel `4053-00-30-0529` in Pickens SC (`arcgis_distress.pickens_flood_damage`) is shared by 4 rows with 4 different Clemson addresses (`114 Baseball Dr`, `200 Avenue of Champions`, `142 Delta St`, `291 Gamma St`), and the parcel cache's own situs for that id is a fifth address, `140 Alpha St 137`.
- Genuine mismatches were NOT concentrated in one source: at least 25 distinct sources contribute (the table below is capped at the top 15), topped by the two `liensnc` slugs combined (1,123), `charlotte_open_data` (471), `qpaybill_delinquent_roll` (453), `nc_county_pdf_delinquent_tax` (420), `buncombe_elderly` (356).

**Top 15 sources by genuine mismatch count:**

| Source | Genuine mismatches |
|---|--:|
| `counties_generic.liensnc` | 655 |
| `city_websites.charlotte_open_data` | 471 |
| `liensnc` | 468 |
| `counties_sc.qpaybill_delinquent_roll` | 453 |
| `counties_nc.nc_county_pdf_delinquent_tax` | 420 |
| `counties_nc.buncombe_elderly` | 356 |
| `counties_generic.state_contamination.nc_ust_incidents` | 272 |
| `counties_generic.arcgis_distress.buncombe_unpaid_bills` | 235 |
| `counties_generic.arcgis_distress.new_hanover_demolition_permits` | 160 |
| `counties_nc.rutherford_tax` | 155 |
| `counties_nc.nc_ptscloud_delinquent_tax` | 131 |
| `counties_sc.berkeley_paystar_tax` | 107 |
| `counties_generic.arcgis_distress.pickens_flood_damage` | 78 |
| `counties_nc.nc_county_csv_delinquent_tax` | 61 |
| `counties_sc.spartanburg_vacant` | 59 |

**Top 15 counties by genuine mismatch count:**

| County | State | Genuine mismatches |
|---|---|--:|
| Buncombe | NC | 976 |
| Mecklenburg | NC | 517 |
| Spartanburg | SC | 505 |
| McDowell | NC | 423 |
| Rutherford | NC | 278 |
| New Hanover | NC | 267 |
| Henderson | NC | 252 |
| Gaston | NC | 132 |
| Pickens | SC | 127 |
| Berkeley | SC | 107 |
| Wake | NC | 103 |
| Rowan | NC | 98 |
| Lancaster | SC | 79 |
| Lincoln | NC | 69 |
| Burke | NC | 62 |

**Illustrative examples (row's own address vs. the county parcel cache's situs, same parcel id), one non-Buncombe example per top source:**

| County/State | Source | Parcel | Row's `street_address` | Parcel-cache situs |
|---|---|---|---|---|
| Mecklenburg NC | `city_websites.charlotte_open_data` | 08114106 | 912 PARKWOOD AV | 914 PARKWOOD AV CHARLOTTE NC |
| Berkeley SC | `counties_sc.berkeley_paystar_tax` | 250-00-00-015 | 5338 HALFWAY CREEK RD | 5344 HALFWAY CREEK RD |
| McDowell NC | `counties_nc.nc_county_pdf_delinquent_tax` | 079700586730 | 307 BLUERIDGE DR S UT1 LND TST | 012255 NC 226 A |
| Rutherford NC | `counties_nc.rutherford_tax` | 1605025 | 1799, Memorial Highway, Lake Lure, Rutherford County, North Carolina, 28746, United States | 0 RABBITS PL |
| New Hanover NC | `counties_generic.arcgis_distress.new_hanover_demolition_permits` | R04919-001-008-000 | 2464 PLAYA WAY | 2400  PLAYA WAY |
| Rowan NC | `liensnc` | 209 056 | 5560 Creekwood Dr. | 0 CREEKWOOD |
| Lancaster SC | `counties_sc.qpaybill_delinquent_roll` | 0081H-0G-006.00 | 985 15TH ST | 1524 15TH ST |
| Mecklenburg NC | `counties_generic.liensnc` | 17324103 | 8625 Winter Oaks Ln | 8617 WOOD LAKE CT CHARLOTTE NC |
| Buncombe NC | `counties_nc.buncombe_elderly` | 0607507809 | 36 DALTON RIDGE RD | 48 DALTON RIDGE  RD |
| Pickens SC | `counties_generic.arcgis_distress.pickens_flood_damage` | 4053-00-30-0529 | 114 BASEBALL DR, CLEMSON | 140  ALPHA ST  137 |
| Gaston NC | `counties_generic.state_contamination.nc_ust_incidents` | 3575-29-6044 | 107 CHURCH ST | 204 W FIRST ST |

## 2. Owner mailing, owner name, market value, tax value (item 3)

| Group | Rows | Owner mailing | Owner name | Market value | Tax value | Either value |
|---|--:|--:|--:|--:|--:|--:|
| **All (now)** | 192,805 | 125,323 (65.0%) | 184,649 (95.8%) | 107,188 (55.6%) | 89,116 (46.2%) | 117,581 (61.0%) |
| **NC (now)** | 115,471 | 86,005 (74.5%) | 111,789 (96.8%) | 76,742 (66.5%) | 61,010 (52.8%) | 78,983 (68.4%) |
| **SC (now)** | 77,334 | 39,318 (50.8%) | 72,860 (94.2%) | 30,446 (39.4%) | 28,106 (36.3%) | 38,598 (49.9%) |

Baseline comparison (2026-09-21, after the 11:50 rescore, `docs/AUDIT_2026-09-21.md` section 15's state table - the closest prior by-state readout; it does not split market vs tax value, and "mail" there is `owner_mailing_address`/`mailing_address` presence, the same field family read here via `mailing_shape.mailing_of`):

| State | Rows | Mail | Value (combined) |
|---|--:|--:|--:|
| NC | 93,030 | 90% | 51% |
| SC | 77,036 | 37% | 39% |

NC mail fell sharply (90%→74%) mostly because the baseline's NC mail figure was propped up by `liensnc` (46,989 rows, 100% mail at the time - finding A8). SC mail rose (37%→51%), consistent with the SC parcel-cache backbone additions (Berkeley, Horry, Charleston, Lexington, York, etc., Section 6 of the baseline and Section 3 here). Combined "either value" coverage rose from roughly 45% (weighted NC 51%/SC 39% blend) to 61% - real gain, driven by the same SC parcel-cache work plus growth in NC's own tax-roll sources.


## 3. Distress-family breadth, all 146 NC+SC counties (item 4)

Family definitions match the baseline's section 4c taxonomy directly off `listing_type`: tax delinquent = `tax_lien`, tax sale = `tax_sale`, lis pendens = `lis_pendens`, probate = `probate_notice`+`estate_lead` (baseline's "probate/estate"), divorce = `divorce_notice`, bankruptcy = `bankruptcy`, code/vacant = `distressed` (baseline's "distressed (code/vacant/storm/other)"). FLIP types and `elderly_disabled`/`unknown` are out of scope for this item (covered in item 5 and item 1).

**5 of 146 counties have all 7 families present** (true 100% breadth): Buncombe NC, Burke NC, Cleveland NC, Henderson NC, Rutherford NC. All five sit inside the 18-county footprint; not one of the other 128 counties has full breadth.

**141 of 146 are missing at least one family**, including **2 counties with zero rows at all** (Chester SC, Fairfield SC).

Family-count histogram, all 146 counties (0 = no rows at all):

| Families present | Counties |
|--:|--:|
| 0/7 | 2 |
| 1/7 | 65 |
| 2/7 | 27 |
| 3/7 | 18 |
| 4/7 | 8 |
| 5/7 | 9 |
| 6/7 | 12 |
| 7/7 | 5 |

Baseline (2026-09-21, 9 families measured incl. FLIP types and elderly/disabled, not directly comparable in family count but same headline shape): 3 counties had 0 rows, 73 had exactly 1 family, 31 had 2. Now (7 families measured): 2 have 0 rows, 65 have exactly 1, 27 have 2. Genuine improvement in the tail (fewer zero/one-family counties), but the shape - most counties clustered at 1-2 families - is unchanged.

**Families most commonly missing (of 146):**

| Family | Missing in | Present in | Baseline (2026-09-21) present in |
|---|--:|--:|--:|
| Divorce | 127 | 19 | 18 |
| Bankruptcy | 123 | 23 | 18 |
| Probate/estate | 108 | 38 | 27 |
| Lis pendens | 105 | 41 | 39 |
| Code enforcement/vacant | 97 | 49 | 33 |
| Tax sale | 88 | 58 | 62 |
| Tax delinquent | 17 | 129 | 128 |

### Full county table (all 146)

Rows, families present (X/7) and which families are missing. Sorted NC then SC, by rows descending within state.

| County | State | Rows | Addr | Mail | Value | Fam | Missing families |
|---|---|--:|--:|--:|--:|--:|---|
| Buncombe | NC | 10,365 | 92% | 73% | 87% | 7/7 | (none) |
| Gaston | NC | 9,086 | 94% | 88% | 74% | 6/7 | TaxS |
| Rutherford | NC | 8,677 | 64% | 70% | 85% | 7/7 | (none) |
| Mecklenburg | NC | 8,425 | 99% | 92% | 63% | 5/7 | TaxS, LisP |
| Transylvania | NC | 6,261 | 74% | 88% | 93% | 6/7 | TaxS |
| Forsyth | NC | 5,829 | 20% | 20% | 85% | 3/7 | LisP, Prob, Div, BK |
| Wake | NC | 5,603 | 99% | 99% | 70% | 3/7 | LisP, Prob, Div, BK |
| Catawba | NC | 4,935 | 24% | 20% | 21% | 4/7 | Prob, Div, BK |
| New Hanover | NC | 4,558 | 81% | 77% | 66% | 5/7 | TaxS, BK |
| Guilford | NC | 4,203 | 33% | 31% | 76% | 3/7 | LisP, Prob, Div, BK |
| Brunswick | NC | 3,842 | 82% | 81% | 49% | 6/7 | CV |
| Lincoln | NC | 3,519 | 91% | 82% | 91% | 6/7 | Div |
| Henderson | NC | 3,135 | 70% | 66% | 87% | 7/7 | (none) |
| McDowell | NC | 2,669 | 65% | 62% | 62% | 6/7 | TaxS |
| Pitt | NC | 2,094 | 26% | 27% | 89% | 1/7 | TaxS, LisP, Prob, Div, BK, CV |
| Orange | NC | 1,785 | 30% | 31% | 73% | 1/7 | TaxS, LisP, Prob, Div, BK, CV |
| Durham | NC | 1,714 | 99% | 99% | 68% | 2/7 | TaxS, LisP, Prob, Div, BK |
| Onslow | NC | 1,377 | 79% | 78% | 33% | 5/7 | TaxS, CV |
| Burke | NC | 1,339 | 93% | 81% | 73% | 7/7 | (none) |
| Johnston | NC | 1,315 | 98% | 100% | 36% | 1/7 | TaxS, LisP, Prob, Div, BK, CV |
| Harnett | NC | 1,293 | 99% | 100% | 44% | 1/7 | TaxS, LisP, Prob, Div, BK, CV |
| Union | NC | 1,232 | 99% | 100% | 59% | 1/7 | TaxS, LisP, Prob, Div, BK, CV |
| Bertie | NC | 1,100 | 100% | 100% | 99% | 1/7 | TaxS, LisP, Prob, Div, BK, CV |
| Cleveland | NC | 1,002 | 87% | 70% | 74% | 7/7 | (none) |
| Madison | NC | 880 | 39% | 8% | 94% | 3/7 | TaxS, Prob, Div, CV |
| Cabarrus | NC | 816 | 99% | 97% | 27% | 3/7 | LisP, Prob, Div, BK |
| Iredell | NC | 747 | 99% | 98% | 83% | 3/7 | LisP, Prob, Div, BK |
| Alamance | NC | 731 | 99% | 100% | 43% | 1/7 | TaxS, LisP, Prob, Div, BK, CV |
| Rowan | NC | 685 | 96% | 100% | 40% | 1/7 | TaxS, LisP, Prob, Div, BK, CV |
| Cumberland | NC | 672 | 97% | 96% | 49% | 2/7 | TaxS, LisP, Prob, Div, BK |
| Pender | NC | 659 | 83% | 85% | 66% | 5/7 | TaxS, CV |
| Moore | NC | 618 | 99% | 100% | 71% | 1/7 | TaxS, LisP, Prob, Div, BK, CV |
| Davidson | NC | 580 | 100% | 100% | 45% | 1/7 | TaxS, LisP, Prob, Div, BK, CV |
| Graham | NC | 525 | 83% | 81% | 79% | 1/7 | TaxS, LisP, Prob, Div, BK, CV |
| Chatham | NC | 460 | 98% | 100% | 51% | 3/7 | LisP, Prob, Div, BK |
| Carteret | NC | 446 | 91% | 84% | 61% | 5/7 | TaxS, Div |
| Gates | NC | 443 | 99% | 83% | 80% | 1/7 | TaxS, LisP, Prob, Div, BK, CV |
| Craven | NC | 429 | 90% | 90% | 53% | 3/7 | TaxS, Prob, BK, CV |
| Franklin | NC | 423 | 99% | 100% | 17% | 1/7 | TaxS, LisP, Prob, Div, BK, CV |
| Polk | NC | 411 | 88% | 68% | 73% | 6/7 | TaxS |
| Nash | NC | 411 | 97% | 100% | 35% | 1/7 | TaxS, LisP, Prob, Div, BK, CV |
| Randolph | NC | 400 | 98% | 100% | 44% | 1/7 | TaxS, LisP, Prob, Div, BK, CV |
| Stanly | NC | 340 | 97% | 100% | 44% | 1/7 | TaxS, LisP, Prob, Div, BK, CV |
| Dare | NC | 326 | 91% | 92% | 62% | 4/7 | TaxS, BK, CV |
| Currituck | NC | 307 | 91% | 93% | 82% | 3/7 | TaxS, Prob, BK, CV |
| Wayne | NC | 302 | 98% | 100% | 26% | 1/7 | TaxS, LisP, Prob, Div, BK, CV |
| Lee | NC | 296 | 60% | 100% | 28% | 1/7 | TaxS, LisP, Prob, Div, BK, CV |
| Hoke | NC | 292 | 97% | 100% | 0% | 1/7 | TaxS, LisP, Prob, Div, BK, CV |
| Watauga | NC | 279 | 91% | 100% | 80% | 1/7 | TaxS, LisP, Prob, Div, BK, CV |
| Tyrrell | NC | 274 | 100% | 100% | 99% | 1/7 | TaxS, LisP, Prob, Div, BK, CV |
| Rockingham | NC | 268 | 97% | 100% | 47% | 1/7 | TaxS, LisP, Prob, Div, BK, CV |
| Granville | NC | 251 | 97% | 100% | 35% | 2/7 | TaxS, LisP, Prob, Div, BK |
| Haywood | NC | 244 | 93% | 100% | 74% | 2/7 | LisP, Prob, Div, BK, CV |
| Mitchell | NC | 238 | 91% | 67% | 71% | 5/7 | TaxS, Div |
| Caldwell | NC | 207 | 98% | 100% | 75% | 1/7 | TaxS, LisP, Prob, Div, BK, CV |
| Wilson | NC | 202 | 100% | 100% | 45% | 1/7 | TaxS, LisP, Prob, Div, BK, CV |
| Jackson | NC | 172 | 83% | 100% | 58% | 1/7 | TaxS, LisP, Prob, Div, BK, CV |
| Surry | NC | 168 | 85% | 100% | 62% | 1/7 | TaxS, LisP, Prob, Div, BK, CV |
| Cherokee | NC | 165 | 94% | 100% | 56% | 1/7 | TaxS, LisP, Prob, Div, BK, CV |
| Person | NC | 144 | 97% | 100% | 59% | 1/7 | TaxS, LisP, Prob, Div, BK, CV |
| Yadkin | NC | 137 | 94% | 100% | 67% | 1/7 | TaxS, LisP, Prob, Div, BK, CV |
| Duplin | NC | 137 | 95% | 100% | 57% | 1/7 | TaxS, LisP, Prob, Div, BK, CV |
| Ashe | NC | 133 | 71% | 100% | 56% | 1/7 | TaxS, LisP, Prob, Div, BK, CV |
| Stokes | NC | 133 | 98% | 100% | 55% | 1/7 | TaxS, LisP, Prob, Div, BK, CV |
| Robeson | NC | 128 | 93% | 97% | 38% | 2/7 | LisP, Prob, Div, BK, CV |
| Beaufort | NC | 121 | 88% | 89% | 65% | 3/7 | TaxS, Prob, BK, CV |
| Wilkes | NC | 121 | 83% | 100% | 40% | 1/7 | TaxS, LisP, Prob, Div, BK, CV |
| Davie | NC | 120 | 98% | 100% | 43% | 1/7 | TaxS, LisP, Prob, Div, BK, CV |
| Yancey | NC | 111 | 98% | 100% | 0% | 1/7 | TaxS, LisP, Prob, Div, BK, CV |
| Montgomery | NC | 110 | 92% | 100% | 57% | 1/7 | TaxS, LisP, Prob, Div, BK, CV |
| Columbus | NC | 102 | 92% | 100% | 38% | 1/7 | TaxS, LisP, Prob, Div, BK, CV |
| Macon | NC | 96 | 77% | 100% | 58% | 1/7 | TaxS, LisP, Prob, Div, BK, CV |
| Pasquotank | NC | 96 | 99% | 100% | 82% | 1/7 | TaxS, LisP, Prob, Div, BK, CV |
| Lenoir | NC | 95 | 100% | 100% | 49% | 1/7 | TaxS, LisP, Prob, Div, BK, CV |
| Sampson | NC | 92 | 91% | 100% | 40% | 1/7 | TaxS, LisP, Prob, Div, BK, CV |
| Richmond | NC | 91 | 96% | 100% | 48% | 2/7 | LisP, Prob, Div, BK, CV |
| Avery | NC | 86 | 95% | 100% | 67% | 1/7 | TaxS, LisP, Prob, Div, BK, CV |
| Edgecombe | NC | 84 | 94% | 100% | 68% | 2/7 | LisP, Prob, Div, BK, CV |
| Scotland | NC | 78 | 88% | 100% | 54% | 2/7 | LisP, Prob, Div, BK, CV |
| Camden | NC | 77 | 94% | 100% | 0% | 1/7 | TaxS, LisP, Prob, Div, BK, CV |
| Warren | NC | 76 | 99% | 97% | 53% | 2/7 | LisP, Prob, Div, BK, CV |
| Pamlico | NC | 75 | 91% | 93% | 60% | 3/7 | TaxS, Prob, BK, CV |
| Chowan | NC | 66 | 98% | 98% | 0% | 2/7 | LisP, Prob, Div, BK, CV |
| Vance | NC | 64 | 94% | 100% | 67% | 1/7 | TaxS, LisP, Prob, Div, BK, CV |
| Clay | NC | 63 | 62% | 100% | 30% | 1/7 | TaxS, LisP, Prob, Div, BK, CV |
| Caswell | NC | 60 | 90% | 98% | 48% | 2/7 | TaxS, LisP, Prob, Div, BK |
| Alexander | NC | 57 | 96% | 100% | 70% | 1/7 | TaxS, LisP, Prob, Div, BK, CV |
| Alleghany | NC | 56 | 75% | 100% | 55% | 1/7 | TaxS, LisP, Prob, Div, BK, CV |
| Halifax | NC | 55 | 95% | 100% | 56% | 1/7 | TaxS, LisP, Prob, Div, BK, CV |
| Perquimans | NC | 53 | 94% | 98% | 28% | 2/7 | LisP, Prob, Div, BK, CV |
| Hyde | NC | 48 | 96% | 88% | 79% | 3/7 | TaxS, Div, BK, CV |
| Swain | NC | 48 | 90% | 98% | 42% | 2/7 | TaxS, LisP, Prob, Div, BK |
| Anson | NC | 48 | 79% | 100% | 42% | 1/7 | TaxS, LisP, Prob, Div, BK, CV |
| Bladen | NC | 43 | 100% | 100% | 30% | 1/7 | TaxS, LisP, Prob, Div, BK, CV |
| Greene | NC | 26 | 81% | 100% | 38% | 1/7 | TaxS, LisP, Prob, Div, BK, CV |
| Northampton | NC | 24 | 100% | 100% | 71% | 1/7 | TaxS, LisP, Prob, Div, BK, CV |
| Martin | NC | 24 | 100% | 100% | 75% | 1/7 | TaxS, LisP, Prob, Div, BK, CV |
| Jones | NC | 24 | 100% | 100% | 62% | 1/7 | TaxS, LisP, Prob, Div, BK, CV |
| Hertford | NC | 22 | 86% | 91% | 59% | 2/7 | TaxS, LisP, Div, BK, CV |
| Washington | NC | 11 | 100% | 91% | 55% | 1/7 | TaxS, LisP, Prob, Div, BK, CV |
| Spartanburg | SC | 17,462 | 86% | 83% | 77% | 6/7 | Div |
| Horry | SC | 4,890 | 82% | 50% | 74% | 4/7 | LisP, Div, BK |
| Pickens | SC | 4,702 | 71% | 69% | 5% | 6/7 | Div |
| Charleston | SC | 4,428 | 92% | 13% | 24% | 5/7 | Div, BK |
| Greenville | SC | 3,222 | 91% | 68% | 93% | 5/7 | Div, BK |
| Oconee | SC | 3,195 | 71% | 63% | 40% | 6/7 | Div |
| Sumter | SC | 3,094 | 99% | 76% | 94% | 4/7 | Prob, Div, BK |
| Laurens | SC | 2,690 | 62% | 50% | 43% | 6/7 | Div |
| Cherokee | SC | 2,684 | 57% | 9% | 38% | 5/7 | Div, BK |
| Anderson | SC | 2,597 | 60% | 35% | 38% | 6/7 | Div |
| Darlington | SC | 2,520 | 79% | 69% | 69% | 2/7 | TaxD, LisP, Prob, Div, BK |
| Williamsburg | SC | 2,252 | 71% | 0% | 0% | 1/7 | TaxD, LisP, Prob, Div, BK, CV |
| Lexington | SC | 2,229 | 98% | 52% | 72% | 3/7 | LisP, Prob, Div, BK |
| Berkeley | SC | 2,127 | 80% | 99% | 95% | 4/7 | Div, BK, CV |
| Kershaw | SC | 1,699 | 91% | 0% | 78% | 2/7 | LisP, Prob, Div, BK, CV |
| Florence | SC | 1,668 | 74% | 84% | 0% | 4/7 | LisP, Div, BK |
| Colleton | SC | 1,317 | 82% | 61% | 82% | 4/7 | Div, BK, CV |
| Union | SC | 1,287 | 66% | 41% | 38% | 6/7 | Div |
| Clarendon | SC | 1,221 | 79% | 0% | 0% | 2/7 | LisP, Prob, Div, BK, CV |
| Marlboro | SC | 1,063 | 57% | 0% | 0% | 2/7 | TaxD, LisP, Div, BK, CV |
| Lancaster | SC | 896 | 99% | 72% | 0% | 2/7 | LisP, Prob, Div, BK, CV |
| Beaufort | SC | 879 | 99% | 0% | 0% | 3/7 | TaxS, Div, BK, CV |
| Richland | SC | 860 | 99% | 0% | 0% | 3/7 | LisP, Prob, Div, BK |
| Dillon | SC | 825 | 82% | 1% | 1% | 1/7 | TaxD, LisP, Prob, Div, BK, CV |
| Jasper | SC | 824 | 70% | 1% | 0% | 2/7 | LisP, Prob, Div, BK, CV |
| Barnwell | SC | 800 | 63% | 56% | 56% | 2/7 | TaxD, LisP, Prob, Div, BK |
| Newberry | SC | 722 | 96% | 0% | 0% | 3/7 | LisP, Prob, Div, BK |
| Chesterfield | SC | 654 | 78% | 0% | 0% | 2/7 | TaxD, LisP, Prob, Div, BK |
| Abbeville | SC | 597 | 97% | 0% | 0% | 1/7 | TaxD, LisP, Prob, Div, BK, CV |
| Georgetown | SC | 577 | 55% | 0% | 0% | 4/7 | Div, BK, CV |
| Allendale | SC | 509 | 53% | 0% | 0% | 1/7 | TaxD, LisP, Prob, Div, BK, CV |
| Calhoun | SC | 497 | 83% | 80% | 80% | 1/7 | TaxD, LisP, Prob, Div, BK, CV |
| Bamberg | SC | 474 | 93% | 0% | 84% | 1/7 | TaxD, LisP, Prob, Div, BK, CV |
| Lee | SC | 460 | 74% | 0% | 0% | 1/7 | TaxD, LisP, Prob, Div, BK, CV |
| Saluda | SC | 418 | 86% | 58% | 81% | 2/7 | LisP, Prob, Div, BK, CV |
| McCormick | SC | 277 | 40% | 0% | 0% | 1/7 | TaxD, LisP, Prob, Div, BK, CV |
| York | SC | 131 | 96% | 2% | 2% | 2/7 | TaxS, LisP, Prob, Div, BK |
| Orangeburg | SC | 113 | 98% | 0% | 0% | 3/7 | LisP, Prob, Div, BK |
| Marion | SC | 33 | 48% | 0% | 0% | 2/7 | TaxS, LisP, Div, BK, CV |
| Aiken | SC | 27 | 59% | 0% | 0% | 3/7 | TaxS, Prob, Div, BK |
| Dorchester | SC | 8 | 0% | 0% | 0% | 2/7 | TaxD, TaxS, Div, BK, CV |
| Greenwood | SC | 6 | 67% | 0% | 0% | 2/7 | TaxD, TaxS, Prob, Div, BK |
| Hampton | SC | 1 | 0% | 0% | 0% | 1/7 | TaxS, LisP, Prob, Div, BK, CV |
| Edgefield | SC | 1 | 0% | 0% | 0% | 1/7 | TaxD, TaxS, LisP, Prob, Div, BK |
| Chester | SC | 0 | - | - | - | 0/7 | ALL |
| Fairfield | SC | 0 | - | - | - | 0/7 | ALL |

## 4. Foreclosure/flip lane, 18 footprint counties (item 5)

Scope: `listing_type` in foreclosure_sale, auction, reo, sheriff_sale, hoa_sale, in the 18 footprint counties only (matches the engine's own `config.in_scope` flip footprint, not the broader `in_scope_distressed`). "Sale date today or later" uses 2026-09-23. "Value" is market_value or a published `calc.arv` (not a withheld/flagged ARV). "Identity" is parcel_id AND street_address both present. "All 3" is identity AND mail AND value together - the bar for "this lead is actually workable."

| County | State | Flip rows | foreclosure_sale | auction | reo | sheriff_sale | hoa_sale | Sale ≥ today | Mail | Value | Identity | All 3 (workable) |
|---|---|--:|--:|--:|--:|--:|--:|--:|--:|--:|--:|--:|
| Rutherford | NC | 21 | 19 | 0 | 2 | 0 | 0 | 6 | 71% | 71% | 48% | **48%** (10/21) |
| Cleveland | NC | 46 | 39 | 6 | 0 | 1 | 0 | 12 | 74% | 74% | 0% | **0%** (0/46) |
| Henderson | NC | 22 | 19 | 2 | 1 | 0 | 0 | 6 | 55% | 55% | 55% | **55%** (12/22) |
| Polk | NC | 7 | 2 | 1 | 4 | 0 | 0 | 1 | 57% | 57% | 29% | **29%** (2/7) |
| Gaston | NC | 63 | 58 | 1 | 4 | 0 | 0 | 27 | 73% | 71% | 71% | **71%** (45/63) |
| Buncombe | NC | 110 | 106 | 4 | 0 | 0 | 0 | 19 | 78% | 83% | 76% | **75%** (82/110) |
| Transylvania | NC | 6 | 5 | 0 | 1 | 0 | 0 | 1 | 50% | 17% | 17% | **17%** (1/6) |
| McDowell | NC | 20 | 19 | 1 | 0 | 0 | 0 | 5 | 50% | 60% | 55% | **40%** (8/20) |
| Lincoln | NC | 13 | 13 | 0 | 0 | 0 | 0 | 4 | 69% | 77% | 69% | **69%** (9/13) |
| Mitchell | NC | 4 | 1 | 3 | 0 | 0 | 0 | 2 | 50% | 50% | 50% | **50%** (2/4) |
| Burke | NC | 44 | 39 | 3 | 2 | 0 | 0 | 6 | 64% | 64% | 68% | **61%** (27/44) |
| Spartanburg | SC | 422 | 109 | 142 | 171 | 0 | 0 | 30 | 66% | 69% | 66% | **62%** (260/422) |
| Anderson | SC | 236 | 92 | 49 | 95 | 0 | 0 | 16 | 40% | 49% | 42% | **36%** (85/236) |
| Pickens | SC | 127 | 33 | 10 | 84 | 0 | 0 | 15 | 41% | 1% | 39% | **1%** (1/127) |
| Oconee | SC | 118 | 26 | 10 | 82 | 0 | 0 | 8 | 14% | 0% | 4% | **0%** (0/118) |
| Cherokee | SC | 124 | 40 | 7 | 77 | 0 | 0 | 3 | 8% | 2% | 2% | **0%** (0/124) |
| Union | SC | 83 | 9 | 3 | 71 | 0 | 0 | 0 | 4% | 0% | 2% | **0%** (0/83) |
| Laurens | SC | 267 | 34 | 122 | 111 | 0 | 0 | 7 | 23% | 5% | 21% | **3%** (9/267) |
| **Total** | | **1,733** | 663 | 364 | 705 | 1 | 0 | 168 | 44% | 39% | 40% | **32%** (553/1733) |

### Verdict

**No county is at 100%.** Across all 18 footprint counties combined, 553 of 1,733 flip-type leads (32%) have identity, a value and a mailing address together - the minimum bar for "a buyer could act on this lead today." Ranked best to worst by that measure:

- Buncombe NC: 82/110 (75%)
- Gaston NC: 45/63 (71%)
- Lincoln NC: 9/13 (69%)
- Spartanburg SC: 260/422 (62%)
- Burke NC: 27/44 (61%)
- Henderson NC: 12/22 (55%)
- Mitchell NC: 2/4 (50%)
- Rutherford NC: 10/21 (48%)
- McDowell NC: 8/20 (40%)
- Anderson SC: 85/236 (36%)
- Polk NC: 2/7 (29%)
- Transylvania NC: 1/6 (17%)
- Laurens SC: 9/267 (3%)
- Pickens SC: 1/127 (1%)
- Cleveland NC: 0/46 (0%)
- Oconee SC: 0/118 (0%)
- Cherokee SC: 0/124 (0%)
- Union SC: 0/83 (0%)

Best: Buncombe NC at 75% and Gaston NC at 71% - both still a quarter to a third short. Worst: Cherokee SC, Oconee SC and Union SC all at 0% (Cherokee has 124 flip rows, none with identity+value+mail together; Oconee 118; Union 83). Pickens SC (127 rows) is at under 1%. Cleveland NC shows 0% for a different reason: all 46 of its flip rows come from national trustee/auction feeds (Hutchens, ServiceLink, auction.com, sheriff-sale listings) that carry a street address but never a parcel id at all, so "identity" as defined here (parcel + address) cannot be met structurally - that is a scraper-coverage gap, not a join failure.

Only 168 of 1,733 footprint flip leads have a sale date today or later (baseline: 119 of 690 foreclosure_sale-only rows on 2026-09-21, not a like-for-like base since this count spans all 5 flip types) - the actionable window remains the tightest constraint regardless of the identity/value/mail question.


## 5. New-source coverage (item 6)

| Source | Rows | Address | Mail | Value |
|---|--:|--:|--:|--:|
| `counties_sc.horry_delinquent_xlsx` | 2,235 | 92% | 95% | 96% |
| `counties_nc.rutherford_wildfire_tax` | 499 | 18% | 96% | 100% |
| `counties_sc.charleston_tax_sale_xlsx` | 121 | 95% | 92% | 100% |
| `counties_nc.albemarle_observer_tax_lists` | 1,756 | 100% | 96% | 96% |

| County (new-ingest counties) | Rows | Address | Mail | Value |
|---|--:|--:|--:|--:|
| Onslow NC | 1,377 | 79% | 78% | 33% |
| Graham NC | 525 | 83% | 81% | 79% |

- **Rutherford wildfire tax**: landed, but at 499 rows, far short of the ~2,000-3,000 expected. Mail (96%) and value (100%) are excellent - it is a tax-bill roll with owner and amount - but address is 18% (90/499): the source publishes billing records tied to owner, not situs, and has not been joined to the parcel cache for address backfill yet (the same gap the baseline named in section 16 for qPayBill/Florence/Greenville: "has a parcel but no address... that join has not been run").
- **Albemarle Observer tax lists**: 1,756 rows, good mail (96%) and value (96%), and address is actually 100% by the crude presence check - but 4 of those "addresses" are the literal document title (Section 1), a real quality miss inside a source that otherwise looks complete on the raw numbers.
- **Charleston tax-sale xlsx**: small (121 rows) and clean across the board (95% address, 92% mail, 100% value).
- **Horry delinquent xlsx**: the biggest of the four (2,235 rows), and solidly populated (92% address, 95% mail, 96% value) - this is the strongest of the four new sources.
- **Onslow NC and Graham NC** (both out-of-footprint, in-scope-for-distressed counties named in the prior ingest): Onslow 1,377 rows, 79% address, 78% mail, but only 33% value (449/1,377) - the weakest layer for Onslow is value, not address or mail. Graham 525 rows, 83% address, 81% mail, 79% value - the most balanced of the new/expanded counties checked here.

**Overall**: the new sources did not land with big gaps across the board the way some September additions did (contrast qPayBill's 25% missing-address rate at baseline). The real gaps are narrower and specific - wildfire tax's address field, Onslow's value field - and are backfill-join problems (the county's own parcel cache has the missing field but has not been joined to these particular rows yet), the same pattern the baseline described for qPayBill and Florence in its own section 16.

