# Source backlog: what was actually left, and what it turned out to be

**2026-08-05.** Written after working the enumeration backlog end to end, in
response to a fair challenge: *"each county should and does have their own
sources like the others do."*

That was right, and the engine did not reflect it. This records what the
backlog actually contained so nobody re-walks it.

---

## The headline number was wrong three times

| Count | Where it came from | Why it was wrong |
|---|---|---|
| 339 | the docs' own `NEW` markers | 86 had been built after the docs were written |
| 263 | matching full URLs against the source tree | missed scrapers that build URLs from a base + service name |
| 230 | matching service names too | still counts reference layers as if they were leads |
| **~14 + ~12** | after inspecting every candidate | the real buildable tail |

**525 endpoints enumerated across 18 counties, plus 63 municipal = 586.** Of the
447 that looked unbuilt:

- **368** are parcel / CAMA / address / footprint layers. These are
  **enrichment, not leads**. Six-figure row counts that would swamp the board
  with non-distressed property. Correctly not built.
- **34** were already built; the doc markers were stale.
- **5** are ordinance or policy pages, not records.
- **~40** were genuinely worth inspecting. **16 became layers.**

---

## What got built

`counties_generic/arcgis_distress_layers.py` — one config table, because a
bespoke module per layer is exactly what kept this tail unbuilt. Adding the next
verified endpoint is now a few lines.

**16 layers, 4,863 leads, 8 counties**, `declared=16 failed=[] never_run=[]`.

| layer | rows | fills |
|---|---:|---|
| `spartanburg_infill_eligible` | 1,076 | curated redevelopment list |
| `buncombe_unpaid_bills` | 1,049 | 675 parcels the advertisement PDF misses |
| `burke_storm_damage` | 456 | Burke storm cell was **empty** |
| `buncombe_landslide_damage` | 415 | |
| `pickens_flood_damage` | 372 | condition + depreciation per element |
| `buncombe_unpaid_bills_2024` | 372 | two levies behind |
| `buncombe_hmgp_buyout` | 266 | applied to be bought out |
| `lincoln_county_owned` | 169 | |
| `spartanburg_city_tax_sale` | 163 | |
| `transylvania_damage_assessment` | 146 | Transylvania storm cell was **empty** |
| `hendersonville_flood_zone_structures` | 121 | NCDPS buyout pool |
| `buncombe_county_owned` | 98 | |
| `laurens_county_owned` | 69 | |
| `lincoln_code_violations` | 66 | Lincoln code cell was **empty** |
| `pickens_county_owned` | 14 | |
| `burke_county_owned` | 11 | Burke was near-empty |

Burke and Transylvania read **zero** on storm damage beforehand. Not because
they were undamaged — only Buncombe's roll had ever been wired. That is the
shape of the whole backlog.

---

## Rejected after inspection — do not re-chase

The headline row count was misleading more often than not. Every one of these
was counted as a find by the enumeration.

| Source | Looked like | Actually |
|---|---|---|
| Buncombe Unpaid Bills **2026** | 103,191 delinquent | the entire current-year unpaid levy: everyone who has not paid yet |
| Buncombe Unpaid Bills 2025 | 7,900 delinquent | 6,873 are **vehicle tax**. Admitted at `real_value>0` only |
| Burke `Tax_Sales_FS` | tax foreclosure | schema has `GRANTOR/GRANTEE/Qualified/Appraiser/Week` — the assessor's qualified-sales roll. Comps |
| Anderson city code violations | 10 open cases | every address, owner and TMS **null**; `CaseNumber '123'`. A stub, on both its FeatureServer and MapServer copies |
| Anderson "Property Type" | 13,374 unsafe structures | a parcel/zoning join |
| Anderson City Parcels / Kings Mountain / Clinton Parcels | 14,121 / 7,902 / 3,828 | parcel masters |
| Pickens `Citizen_Problems` | code enforcement | complainant phone/email, **no property locator at all** |
| Buncombe "abandoned/towed titled property" | abandoned property | "titled property" means **vehicles** |
| Gastonia CityView | the biggest city win (Gaston code = 0) | endpoint 302s to NotFound. Dead |
| Gaston Blight Problems | regional blight reporter | live, **0 rows** |
| Rutherford TR-452 xlsx | 9,351 delinquent bills | already built — `rutherford_tax` reads it (9,328) |
| Henderson foreclosure `definitionExpression` | curated roster | already built — reads 15 of 15 REIDs |
| Spartanburg Master Condemnation List | condemned list | already built as `spartanburg_city_condemned` |
| Pickens `dqnt_*`, Oconee `DT2025` | ~1,500 net-new | already built by `pickens_delinquent_parcels` / `multi_year_delinquent_tax` |
| Laurens estate WP-JSON feed | probate feed | **1 post total**, ever |
| Oconee qPayBill balances | unpaid RE balances | JS payment portal, not a list |
| Mitchell Helene demolition notice | acquisition list | **404** |
| Shelby / Greer minimum-housing | condemnation lists | all exactly 3,038 bytes — a JS shell |

---

## Genuine walls (compliant paths exhausted)

- **Cherokee delinquent tax list.** Cherokee's tax cell is **zero** and this
  would fill it. The 2024 list parses cleanly — 639 rows, 528 parcels, all with
  a situs. But it is the **November 2024** sale, and SC's 12-month redemption
  has already run, so those rows are not a live seller signal. The current list
  cannot be reached: county HTML pages return **403** to any client, and no
  current-year PDF exists at any predictable `/wp-content/uploads/` path (75
  probed). robots permits the uploads directory, so the PDFs themselves are
  fair game the moment a current one is published or its URL is known.
  **Do not engineer around the 403.**
- **Anderson / Cherokee owner-name resolution.** No free owner-searchable
  parcel layer exists for either. Anderson's viewer has no owner column
  (`TAXOWNSTR` is a district code), ACPASS is robots-disallowed, Cherokee is
  qPublic-only, and ArcGIS Online publishes nothing. 1,187 leads sit behind
  this, marked `no_owner_search_backend` on the board rather than dropped.
- **SC divorce, all 7 counties.** SC Public Index forbids automated search
  under Rule 610. Permanently zero.

---

## Left for a decision, not built

**Spartanburg "Tarp Requests"** — 2,096 rows carrying
`USER_Contact_First_Name`, `USER_Contact_Last_Name` and the household address.
These are disaster victims who asked for emergency help after roof damage.

Roof damage is a fair property signal. A list of people who requested aid,
repurposed as an acquisition target list, is a different thing. That is a
business call, not a technical one, so it is not built.

---

## Where the remaining value actually is

Not in more sources. The queryable seam is worked out. What is left:

1. **~65 HTML/PDF distress pages**, each needing a bespoke parser, and the
   sample above shows the hit rate is poor — dead URLs, JS shells, aggregator
   redirects and ordinance text.
2. **Contactability**, not coverage. 37.8% of the board has no usable street
   address and the name-to-property resolver had a 3,688-lead backlog it could
   not drain until the budget was fixed.
3. **The signals already collected**, acted on faster. A tax-sale list is worth
   nothing if nobody works it before the sale date.
