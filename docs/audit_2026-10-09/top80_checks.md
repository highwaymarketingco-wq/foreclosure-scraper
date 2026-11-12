# Audit 2026-10-09, area top80_checks: the "check" group of the top-80 build list

Set: every layer == `check` item of the top 80 that is not a `register:` item and not in the fill / verify
sets: the tax-roll family (`two_year_delinquent`, `multi_year_delinquent_tax`, `tax_aging_surfaced`,
`repeat_tax_loss`, `atty_tax_verified_confirmed`), `rollback_exposure`, `heir_estate`, `vacant_lot`,
`probate`, and the two notice columns (`heir_naming_publication`, `quiet_title`).

## 1. What was built and how it was measured

Every number below was read live on 2026-10-09 (one request at a time per host, at least 2 s apart, ordinary
browser User-Agent; no CAPTCHA, login or paywall touched). Ids and counts only.

### 1.1 ITSPublic tax-bill portals: 10 more NC counties (items 37, 38, 39; 35 for the verdicts)

`scrapers/counties_nc/nc_its_public_tax.py` read Onslow and Graham. The same vendor runs the county portals of
Alleghany, Anson, Caswell, Duplin, Granville, Harnett, Jones, Person, Scotland and Yadkin on a newer build that
answers the old JSON model with HTTP 500 (the cause of the "Jones returned a 500" note in the module doc). The
build wants every `.search-value` field of the page, form-encoded, and prints its columns in a different order
per county, so the grid's own `<th id>` list drives the parse (`parse_row_cols`). Three description layouts
(parcel and alternate id with the situs in an Address column; parcel, situs and acreage in the description;
situs and acreage only, no parcel id: Caswell and Jones) are handled.

Live proof: 40 real bills read from each of the 10 counties (400 bills, 399 leads after grouping by parcel);
every lead carries `raw.nc_its_public_tax` with years, balance and the published `two_year_delinquent`. Parcel
join to the NC OneMap parcel layer (exact, normalised): 5 of 8 sampled ids join directly; Scotland joins after
the space is removed (the roll prints `010075 02001`), Duplin prints a map block, Person prints a short
account-style id, so those two place by street. Caswell and Jones print no parcel id: 38 and 32 of 40 leads
place by street only (`parcel_id` None; grouped by account and situs).

Per-county time budget `ITS_TAX_COUNTY_BUDGET_S` (default 420 s). A run is reported PARTIAL (so the screen
ledger claims nothing) when any county failed or ran out of time before its newest delinquent year was
complete. 2025 unpaid-bill counts per county on the day: Alleghany 482, Anson 2,870, Caswell 800, Duplin 6,790,
Granville 1,374, Harnett 5,881, Jones 1,043, Person 1,669, Scotland 3,493, Yadkin 1,635 (personal property
included; it is dropped).

Verdicts (not gaps): **Clay, Swain, Surry** run the old ITS 1.0 build: no JSON grid routes (404) and Clay's plain
results form answers HTTP 500 (Swain and Surry serve the same page; their form was not posted). **Warren, Gates** answer 0 bills, paid or unpaid, for 2022-2025.
`UNREADABLE_PORTALS` in the module carries the reasons.

Verifier (`atty_tax_verified_confirmed`): `tax_lien_itspublic` now holds Anson, Granville, Harnett, Yadkin
(Onslow cell order) and Alleghany, Scotland (ITSNet cell order), all with the full search model. Live: 23 board-shaped
rows through `verify()` gave 15 confirmed, 8 unconfirmed `parcel_not_found` (Person 3 of 3, which is why Person
was taken out again; Harnett 2, Scotland 1 stay: the ids on those bills do not always search). Caswell and Jones
cannot be bound to a row (no parcel id on their bills).

### 1.2 NC OneMap statewide sweeps (items 6 and 19, NC half)

`enrichment_onemap_sweeps.py`, two keyset-paged statewide passes (about 2 s a page; about 57 and 63 pages; cached
7 days in `data/onemap_sweeps`):

* `heir_estate`: the 400-per-county lead cap of `nc_heir_estate_parcels` left 49 of the 99 NC counties that have a
  match sampled, not screened (65,037 matching parcels statewide; Forsyth 3,062, Catawba 2,208, Halifax 2,153).
  The sweep reads all of them (113,729 rows read, 105,978 index keys), flags every NC board row whose parcel is
  titled `<name> HEIRS` / `ESTATE OF <name>` (any source), and screens all 100 counties.
* `rollback_exposure`: the statewide layer has a per-parcel present-use flag `presentval` (Y/N). Where it behaves as
  a flag it is used: 44 counties (Y on at most 25% of parcels; farm parcels average 42 acres against 2 for the rest in Alamance).
  Seven counties carry Y on nearly every parcel (Johnston 99%, Rowan 99%, Wayne 97%, Wilson 97%, Yadkin 100%,
  Caswell 99%, Carteret 49%) and 49 counties are N on every parcel: not used. A flag says a deferral exists, not
  its size, so `deferred_value` stays None (no dollar figure invented); a county layer's richer stamp is never
  overwritten (wire it after `enrich_with_rollback_exposure`).

Live proof: 230 real parcels (6 counties: a random slice plus targeted heir-titled and flagged parcels, ground
truth read independently from the layer) through `apply_indexes`: heir_estate 47 true positives, 0 false
positives, 0 missed; rollback flag 49 true positives, 0 false positives, 0 missed.

### 1.3 Spartan public probate inquiry: Greenwood, Newberry, Calhoun (item 51)

`enrichment_probate_spartan.py`. Three of the five SC probate cells run on one vendor app whose grid reads a
JSON handler; an empty last name with party type DEC lists every decedent party (Greenwood 20,480, Newberry
13,366, Calhoun 3,674 on the day). The module reads the whole index once (100 per request, 2 s apart, resumable,
cached 30 days; first full build about 420 requests, budget 1,500 s) and matches every board owner of those counties
offline with the obituary matcher's name rules. A name match is written only as `raw.probate_index_match`
(case numbers); `raw.probate` is written only when the fit is full / middle initial (or a unique thin fit) AND the
row already shows a death on the roll, so a namesake never raises a probate score. The county is screened only
when its index is complete.

Live proof: Calhoun built through the module's own path (3,674 of 3,674 decedent parties, 38 requests, 78 s);
40 owner strings made from real index entries (both name orders) matched 38 to the exact case; 4 invented names
matched nothing.

Not built: **Lexington** (verify group's matrix record: statutory solicitation notice and CAPTCHA), **Richland**
(name-only decedent search, no listing: the county cannot be screened; a per-name lookup for death-signal rows
alone would not close the cell).

### 1.4 vacant_lot land use (item 15, NC and the cached SC counties)

`enrichment_vacant_landuse.py` skipped every county that is not in `PARCEL_LAYERS` (`cached_counties()` lists 36 of
the 126 cache files), so the ~60 NC counties cached off the statewide layer never contributed, and for the rest it
kept the land use only inside `raw.vacant_lot`, so a row that is not a vacant lot carried no land use and the cube
counted `vacant_lot` unchecked on it (Mecklenburg 5 of 17,733 rows). It now looks for the cache file by state and
county and keeps the county's class string on `Listing.land_use` when empty. Live proof: 240 real cached parcels in
6 counties (Mecklenburg, Wake, Forsyth, Spartanburg, Alamance, Pitt): all 240 filled; 25 carry a county class that
reads VACANT and were stamped. Note: several NC counties publish a class code only (`R`, `RA`), which counts as a
land-use value for the cube but does not name vacancy.

## 2. Cells closed (computed, not estimated)

`scripts/gap_matrix.py` classification (`classify_cell`) applied to the 10/9 matrix cells with the new ledger
(ITS counties for the three roster tax columns; every NC county for heir_estate; the 44 present-use counties for
rollback_exposure): **118 cells** go to at target: heir_estate 40, rollback_exposure 42, and 12 each for
`two_year_delinquent`, `multi_year_delinquent_tax`, `tax_aging_surfaced` (10 new counties plus Onslow and Graham, whose cells were
built-but-low-yield without a screen). Not simulated (needs a board pass): the three Spartan probate cells, `vacant_lot`, and the
`atty_tax_verified_confirmed` cells of the six verifier counties.

## 3. Defects found

| defect | scale | cause | fix | test | invariant |
|---|---|---|---|---|---|
| ITSPublic newer build unreadable | 10 counties | JSON model answers HTTP 500; per-county column order | form-encoded full model, header-driven parse | tests/test_nc_its_public_tax.py | `top80-its-roll-shape`, `top80-its-county-silent` |
| heir/estate parcels sampled at 400 per county | 49 counties | lead cap read as a screen | statewide sweep + ledger screen | tests/test_enrichment_onemap_sweeps.py | `top80-onemap-heir-shape` |
| present-use flag unused; flag unreliable in 7 counties | 44 usable of 100 | never read; Y on nearly every parcel elsewhere | reliability rule (share <= 25%) | same | `top80-onemap-flag-shape`, `top80-onemap-flag-share` |
| land use dropped for non-vacant rows and for statewide-layer counties | about 60 NC counties | `cached_counties()` is PARCEL_LAYERS only | cache-file lookup, keep `land_use` | tests/test_enrichment_vacant_landuse_fill.py | `top80-vacant-lot-shape` |
| Spartan probate index never read | 3 SC counties | not on southcarolinaprobate.net | decedent index + offline match | tests/test_enrichment_probate_spartan.py | `top80-probate-match-shape` |

## 4. Open items

* `repeat_tax_loss` (36 cells): the module is a deed-index join (county register sweeps), not a tax-roll read; the
  cube's definition "checked = tax roll read" is looser than the module. Not claimed from the roll; follows the
  register group's county sweeps. Decision for the lead whether the definition stands.
* Tax counties with no county-wide unpaid list found in this pass (23 of the 33): per-parcel lookup only (the
  `ustaxdata.com` search of Robeson was opened: name / address / parcel boxes, no list; Alexander and Rockingham use
  the same vendor, not opened), JavaScript property-card apps (Alamance, Davie), Munis self-service (Greene, Sampson),
  and others (Avery, Cabarrus, Edgecombe, Franklin, Johnston, Lee, Montgomery, Nash, Pamlico, Pasquotank, Watauga,
  Wilkes, Yancey): not probed one by one. They remain sourced-not-built.
* `rollback_exposure`: 56 NC counties (flag unpopulated or unreliable) and 43 SC counties: no per-parcel source read.
* `vacant_lot` SC (42 counties) and `heir_estate` SC (38): need the county parcel layers in `parcel_cache`; the fill
  group's `gis_fill` SC layer list is the place; this group added no SC layer.
* `heir_naming_publication` / `quiet_title`: found built by the verify group (`nc_heir_notices`, untracked at the
  time, tests present); not touched here. It is not in main.py's scraper list yet (their report has the line).

## 5. Wiring (lead)

```
# main.py, right after the enrich_with_rollback_exposure try/except (after tax_relief and the rollback block)
try:
    from .enrichment_onemap_sweeps import enrich_onemap_sweeps
    s = await _await_capped(enrich_onemap_sweeps(enriched), "onemap_sweeps", default_s=900)
    if s and "skipped" not in s:
        enrichment_stats["onemap_sweeps"] = s
except Exception:
    log.error("onemap_sweeps.failed", traceback=traceback.format_exc())

# main.py, after enrich_life_events (death_signal_on_roll reads the estate wording), before enrich_court_owner_verify
try:
    from .enrichment_probate_spartan import enrich_probate_spartan
    s = await _await_capped(enrich_probate_spartan(enriched), "probate_spartan",
                            default_s=float(os.environ.get("FORECLOSURE_PROBATE_SPARTAN_BUDGET_S", "1500")) + 180)
    if s and "skipped" not in s:
        enrichment_stats["probate_spartan"] = s
except Exception:
    log.error("probate_spartan.failed", traceback=traceback.format_exc())
```

Already in place: `counties_nc.nc_its_public_tax` is in main.py's scraper list (nothing to add); the
`FORECLOSURE_PROBATE_SPARTAN` flags are in vm_lib.sh and run_profile.json; `probate_index_match` is in
`web_artifact.RAW_KEEP`; screen_ledger reads `enrichment_stats['onemap_sweeps']` and `['probate_spartan']`.

## 6. Not verified

No board pass was run for the cube numbers of section 2's "not simulated" cells. The ITS crawl was read at
sample size (40 bills a county), not in full; the per-county time budget is untested at full size. The Spartan
index was built live for Calhoun only; Greenwood and Newberry were read at page-1 level (counts and sort).
`tests/test_audit_checks_tax_checkers_2.py::test_a_county_with_no_checker_and_no_recorded_wall_is_counted` and two
`tests/test_prerun_gate.py` tests fail in the working tree; they sit in the verify group's and the lead's files
(Chowan now has a checker; pending wiring entries are non-empty by design) and were not caused by this group.

## 7. Seen outside this area

* The 7-county present-use flag anomaly above suggests those counties' `presentval` means "any use value".
* `enrichment_vacant_landuse` now fills `Listing.land_use`; the comps pass runs earlier in the same run, but the
  next run's comps classification reads `land_use` of carried rows (manufactured-home detection): intended, noted.
