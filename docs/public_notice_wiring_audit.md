# Public-Notice Lane Wiring Audit

Read-only audit (2026-08-12). Verifies that the free press-association notice
portals — **ncnotices.com** (NC Press Association) and **scpublicnotices.com**
(SC Press Association) — are wired for every footprint county's **foreclosure**,
**estate / notice-to-creditors**, and **tax-sale** notices. These portals route
around the walled court portals, so any footprint county not configured is
leaving free leads on the table.

## Which scraper owns which portal

| File | Slug | Portal | County config | Status |
|------|------|--------|---------------|--------|
| `scrapers/public_notices/nc_notices_counties.py` | `public_notices.nc_notices_counties` | ncnotices.com | `FOOTPRINT` tuple (L86-89), ticks county checkboxes server-side | **ACTIVE — the NC lane** |
| `scrapers/public_notices/ncpublicnotices.py` | `public_notices.ncnotices` | ncnotices.com | none — statewide keyword search, county recovered by `COUNTY_RE` (L114-118) | Legacy/statewide; under-captures (per county module docstring). `COUNTY_RE` lists **no** coastal county, so it does not backstop the gaps below. |
| `scrapers/counties_sc/sc_public_notices.py` | `counties_sc.sc_public_notices` | scpublicnotices.com | `_COUNTIES` (L105) + `_IN_SCOPE` (L103) | **ACTIVE — the SC lane** |
| `scrapers/public_notices/publicnoticesc.py` | `public_notices.publicnoticesc` | publicnoticesc.com | none — returns `[]` | Dead (Cloudflare wall). Not the same host as scpublicnotices.com. |

All four are auto-discovered by `_registry.py` (scans the `public_notices` and
`counties_sc` packages; no explicit registration needed).

## How counties are configured

- **NC (`nc_notices_counties.py`):** a single `FOOTPRINT` tuple (L86-89). Each
  name is ticked as a checkbox in the advanced-search sidebar (one postback
  each). The tuple also **derives** `_FOOTPRINT_LOWER` (L90), `_BODY_COUNTY_RE`
  (L193-194) and `_COUNTY_OF_RE` (L195-196), so editing the tuple alone wires
  both county selection and body-county recognition.
- **SC (`sc_public_notices.py`):** `_COUNTIES` (L105, the checkbox labels to
  drive) plus `_IN_SCOPE` (L103, the lowercase allow-list `_to_listing` filters
  on, L424). A county must appear in **both**. `_COUNTY_CODE` (L107-108) is an
  optional case-number cross-check.

## Notice types captured per active lane

Both active lanes already capture all three required notice types footprint-wide
(for the counties they list):

- **NC** `_QUERIES` (L108-118): `foreclosure` (→ FORECLOSURE_SALE / LIS_PENDENS),
  `delinquent taxes` + `advertisement of tax liens` (→ TAX_LIEN / TAX_SALE),
  `notice to creditors` (→ PROBATE_NOTICE). Foreclosure + tax + estate: covered.
- **SC** `_CATEGORIES` (L94-101): Foreclosures, Tax Sales, Delinquent Taxes,
  Public sales, Notice to Creditors, Probate Notices. Foreclosure + tax + estate:
  covered.

So there is **no notice-type gap for any configured county** — the only gaps are
whole counties that are absent from the county lists.

## Live portal confirmation (WebFetch 2026-08-12)

- **ncnotices.com/Search.aspx** — county filter exposes all 100 NC counties
  (Currituck, Dare, Hyde, Carteret, Onslow, Pender, New Hanover, Brunswick all
  present); Foreclosure category present.
- **scpublicnotices.com/Search.aspx** — county filter exposes all 46 SC counties
  including **Charleston, Georgetown, Colleton, Beaufort**; categories include
  Foreclosures, Tax Sales, Delinquent Taxes, Notice to Creditors, Probate
  Notices, Public sales.

Every missing county below exists on its portal with the needed categories. The
gaps are code-side, not portal-side.

## Coverage matrix (30 footprint counties × notice type)

NC counties live only on ncnotices; SC counties live only on scpublicnotices.
Horry SC is excluded per scope.

### NC core (11) — ncnotices via `nc_notices_counties.py`

| County | Foreclosure | Estate (NtC) | Tax sale |
|--------|:-----------:|:------------:|:--------:|
| Buncombe | WIRED | WIRED | WIRED |
| Henderson | WIRED | WIRED | WIRED |
| Cleveland | WIRED | WIRED | WIRED |
| Gaston | WIRED | WIRED | WIRED |
| Rutherford | WIRED | WIRED | WIRED |
| Polk | WIRED | WIRED | WIRED |
| Transylvania | WIRED | WIRED | WIRED |
| McDowell | WIRED | WIRED | WIRED |
| Lincoln | WIRED | WIRED | WIRED |
| Mitchell | WIRED | WIRED | WIRED |
| Burke | WIRED | WIRED | WIRED |

### NC coastal (8) — ncnotices via `nc_notices_counties.py`

| County | Foreclosure | Estate (NtC) | Tax sale |
|--------|:-----------:|:------------:|:--------:|
| Currituck | MISSING | MISSING | MISSING |
| Dare | MISSING | MISSING | MISSING |
| Hyde | MISSING | MISSING | MISSING |
| Carteret | MISSING | MISSING | MISSING |
| Onslow | MISSING | MISSING | MISSING |
| Pender | MISSING | MISSING | MISSING |
| New Hanover | MISSING | MISSING | MISSING |
| Brunswick | MISSING | MISSING | MISSING |

### SC core (7) — scpublicnotices via `sc_public_notices.py`

| County | Foreclosure | Estate (NtC) | Tax sale |
|--------|:-----------:|:------------:|:--------:|
| Spartanburg | WIRED | WIRED | WIRED |
| Anderson | WIRED | WIRED | WIRED |
| Pickens | WIRED | WIRED | WIRED |
| Oconee | WIRED | WIRED | WIRED |
| Cherokee | WIRED | WIRED | WIRED |
| Union | WIRED | WIRED | WIRED |
| Laurens | WIRED | WIRED | WIRED |

### SC coastal (4) — scpublicnotices via `sc_public_notices.py`

| County | Foreclosure | Estate (NtC) | Tax sale |
|--------|:-----------:|:------------:|:--------:|
| Charleston | MISSING | MISSING | MISSING |
| Georgetown | MISSING | MISSING | MISSING |
| Colleton | MISSING | MISSING | MISSING |
| Beaufort | MISSING | MISSING | MISSING |

**Totals:** 18 of 30 counties fully wired (NC core 11 + SC core 7). 12 counties
(all coastal) missing all three notice types = **36 county×notice-type gaps**.

## Exact code changes to close the gaps

### 1. NC coastal — closes 24 gaps (8 counties × 3 types) in ONE edit

**File:** `src/foreclosure_scraper/scrapers/public_notices/nc_notices_counties.py`
**Lines 86-89**, the `FOOTPRINT` tuple. Add the 8 coastal counties (exact
portal-label spelling; "New Hanover" is two words):

```python
FOOTPRINT: tuple[str, ...] = (
    "Buncombe", "Henderson", "Gaston", "Cleveland", "Rutherford", "Burke",
    "Lincoln", "McDowell", "Polk", "Transylvania", "Mitchell",
    # coastal footprint
    "Currituck", "Dare", "Hyde", "Carteret", "Onslow", "Pender",
    "New Hanover", "Brunswick",
)
```

This is sufficient by itself: `_FOOTPRINT_LOWER` (L90), `_BODY_COUNTY_RE`
(L193-194) and `_COUNTY_OF_RE` (L195-196) are all derived from `FOOTPRINT`, so
county selection, the in-scope filter, and body-county recognition all update
together. Secondary note: 19 county postbacks (was 11) plus 4 queries stay
inside `_RENDER_TIMEOUT_MS = 600_000` (L83) / `timeout_s = 900.0` (L535), but
watch runtime on the first full run; if it strains, raise the caps or split the
county set.

### 2. SC coastal — closes 12 gaps (4 counties × 3 types)

**File:** `src/foreclosure_scraper/scrapers/counties_sc/sc_public_notices.py`
Two required edits (a county must be in both lists):

- **Line 103** `_IN_SCOPE`:
```python
_IN_SCOPE = {"spartanburg", "anderson", "pickens", "oconee", "cherokee",
             "union", "laurens", "charleston", "georgetown", "colleton", "beaufort"}
```
- **Line 105** `_COUNTIES`:
```python
_COUNTIES = ("Spartanburg", "Anderson", "Pickens", "Oconee", "Cherokee", "Union",
             "Laurens", "Charleston", "Georgetown", "Colleton", "Beaufort")
```

Optional (improves the case-number cross-check only) **Line 107-108**
`_COUNTY_CODE`: add SC judicial codes `"10": "Charleston"`, `"22": "Georgetown"`,
`"15": "Colleton"`, `"07": "Beaufort"`. Not required for capture.

### Single edit that closes the most gaps

**Edit #1** — adding the 8 NC coastal counties to `FOOTPRINT` in
`nc_notices_counties.py` (L86-89) — closes **24 of the 36** gaps in one change,
because every downstream NC structure derives from that tuple.
