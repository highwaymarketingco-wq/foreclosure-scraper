# Date-coverage audit — 2026-10-14

Triggered by the owner's question tonight: "if we're not pulling old dates, are we
capturing all listings that have real issues and not just the new ones that have less
equity and less delinquent taxes?" The business logic behind the question: the longer a
property has been delinquent (more back tax, more accrued interest, less remaining
equity), the more motivated the seller — so a source that silently drops the OLDEST
debt is systematically keeping the most valuable leads off the board in favor of the
newest, least-distressed ones. That is the one failure mode this audit hunts for.

**Method.** Two source shapes behave correctly under very different rules:

- **Event streams** (ROD recordings, court filings, foreclosure-sale calendars, legal
  notices, auction catalogs) — a rolling lookback window is *correct design*. An old
  filing with no further activity usually isn't still actionable, and the county's own
  docket already drops resolved cases.
- **Current-state rolls** (delinquent-tax lists, FLC/forfeited-land registries,
  code-violation/vacant/condemned registries, overage-claims lists, lien registries) —
  these should capture the FULL current roll regardless of how old the underlying debt
  is. A parcel delinquent five years should appear with its whole accumulated balance.

Every file below was read in full (fetch logic, query/body construction, any
date/year/`since`/`cutoff` constant) and classified. Where code-reading alone couldn't
settle the question, a light live check was done with plain `curl`/`httpx`/`pandas` —
no browser automation, no scraper code touched. One live check (Rowan County's own
2024 vs. 2025 delinquent-tax spreadsheets, parcel-by-parcel) turned out to resolve the
same structural question for the whole NCGS 105-369 annual-advertisement family at
once — see the cross-cutting note below.

**Result.** 127 files reviewed (126 from the candidate list + 1 real miss found by a
supplementary keyword sweep, `counties_generic/multi_year_delinquent_tax.py`). Of
those, **41 are not roll sources** (event streams, confirmed-dead/disabled modules, or
not scrapers at all) and were set aside quickly. Of the **86 genuine current-state-roll
sources**: **78 CLEAN**, **4 FLAGGED — code-imposed limit** (the real, actionable
target of this audit), **3 FLAGGED — source limitation**, **1 UNCLEAR**.

The headline finding is reassuring: this codebase already has a strong, deliberate
pattern for getting this right (qPayBill's `Year=All`, the Catalis roll's per-bill year
key, `rutherford_wildfire_tax.py`'s ten-year sweep, the SC overage-claims PDFs that
parse 4 sale-years from one document, and especially `multi_year_delinquent_tax.py`,
which exists *specifically* to answer this exact question). But four real files do
have a code-side constant narrower than what their own source provides, and they are
not small: two of the four are two- and four-metro-wide ArcGIS feeds, and the other two
cover the thin SC/NC-coverage counties Transylvania and (ITSPublic) Onslow/Graham.

---

## Cross-cutting pattern: the NCGS 105-369 "one annual PDF/XLSX" family is CLEAN — verified live, not assumed

A large share of the NC delinquent-tax scrapers (`cumberland_delinquent_tax.py`,
`rowan_delinquent_tax.py`, `mecklenburg_delinquent_tax.py`, `buncombe_delinquent_tax.py`,
`nc_tax_lien_ads.py`, `nc_county_pdf_delinquent_tax.py`, `nc_county_csv_delinquent_tax.py`,
`iredell_delinquent_tax.py`'s sibling pattern) fetch only the county's *single newest*
annual NCGS 105-369 advertisement, selected via `tax_calendar.latest_delinquent_levy_year`
or a hardcoded year. Read alone, that looks exactly like the bug this audit was sent to
find: why read only one year when the county's page often lists nine years of archived
PDFs?

Live-checked directly (downloaded Rowan County's real 2024 and 2025 XLS delinquent
lists, matched 955 overlapping parcels by PIN): the per-parcel `balance_due` field is
**not** reset to "this year's new levy" each year — it is the account's running
*cumulative* balance as of that list's snapshot date (e.g. parcel 625-055 went
$1,707.36 → $2,813.59 year over year as a new levy stacked on top of the unpaid prior
balance; parcel 258-082 went *down* $187.35 → $182.51 on a partial payment). So reading
only the newest annual advertisement is correct: it already carries the full currently
owed amount for every parcel still delinquent, including parcels that have been
delinquent for years. Fetching the OLDER archived PDFs as well would add stale,
already-superseded balances, not more completeness. This resolves the question for the
whole family at once — classified CLEAN below, each with a one-line note rather than
re-deriving the same finding seven times. (One real, separate soft-spot: this family's
single-year read means `years_delinquent` metadata is usually undercounted to "1" even
when the true arrears run longer, since there's no cross-year join. That affects a
*severity/scoring* signal, not which parcels make the board or their dollar balance —
noted per-file, not treated as a listing-exclusion bug.)

---

## Not a roll source — skipped (41)

**Event streams (auction/sale-date listings, legal-notice feeds, ROD/court sweeps) —
correct to window by lookback, no further action needed:**
`counties_nc/brunswick_legal_notices.py`, `counties_nc/nc_ecourts_lis_pendens.py`
(explicit `LOOKBACK_DAYS = 90`, court filings), `counties_nc/nc_rod_captcha.py`,
`counties_nc/nc_rod_logan.py` (ROD recording sweeps), `counties_nc/nc_govdeals_real_property.py`
(auction listings), `counties_nc/rutherford_foreclosure.py`, `counties_nc/new_hanover_foreclosures.py`,
`counties_nc/henderson_tax.py`, `counties_nc/cleveland_tax.py`,
`counties_nc/stokes_delinquent_tax.py` (misnamed — it's actually the Kania statewide
sale-listings table), `counties_nc/nc_coastal_tax_foreclosure.py`,
`counties_nc/nc_county_tax_foreclosure.py`, `counties_nc/cumberland_tax_foreclosure.py`,
`counties_nc/edgecombe_tax_foreclosure.py`, `counties_nc/gaston_tax_foreclosures.py`,
`counties_nc/guilford_tax_foreclosures.py`, `counties_nc/haywood_tax_foreclosures.py`,
`counties_nc/mecklenburg_tax_foreclosures.py`, `counties_nc/swain_tax_foreclosures.py`,
`counties_nc/wnc_tax_foreclosures.py`, `counties_nc/buncombe_tax_foreclosure.py`,
`counties_nc/wake_tax_foreclosure.py` — all of these are NC's in-rem *tax-foreclosure
sale docket* (case number, sale date, upset-bid deadline), a fundamentally different
stage from the delinquent-tax roll, correctly bounded by the county's own currently
active case list, not by a code-side date cutoff on debt age.
`counties_sc/spartan_weekly_legals.py`, `counties_sc/sc_public_notices.py` (legal-notice
aggregators), `counties_sc/terry_howe_auctions.py` (auction catalog).

**Confirmed dead / disabled / superseded (no live data flows, so there is nothing to
date-window):**
`city_websites/cities.py` (disabled — confirmed garbage keyword-search emitter),
`city_websites/asheville_min_housing.py` (disabled — page has no case data at all),
`counties_sc/city_of_union.py` (disabled — site rebuilt, no data pages left),
`counties_sc/marlboro_delinquent_tax.py`, `counties_sc/sc_delinquent_tax_list.py`,
`counties_sc/sc_dor_delinquent.py`, `counties_sc/greenwood_delinquent_tax.py`,
`counties_sc/clarendon_tax_auction.py`, `counties_sc/sumter_surplus.py`,
`counties_sc/kershaw_flc.py`, `counties_sc/oconee_flc.py`, `counties_sc/sc_flc.py`,
`counties_sc/lancaster_delinquent_tax.py`, `counties_sc/saluda_delinquent_tax.py`,
`counties_sc/sc_tax_delinquent.py` — each disabled with a documented reason (dead URL,
confirmed strictly-redundant duplicate, or superseded by a better sibling scraper
already on the board — `qpaybill_delinquent_roll.py` in most of these cases).

**Not a scraper at all:**
`counties_sc/zombie_properties.py` — its own docstring says it plainly: "This is NOT a
web scraper." It derives a DISTRESSED signal from listings already on the board
(lis pendens older than 12 months with no sale progression); there is no external
source being queried, so there is nothing to under-fetch by date.

---

## CLEAN — confirmed full current-pull, no artificial narrowing (78)

Grouped; one line each except where a specific mechanism is worth naming.

**Gold-standard examples, worth naming by name:**
- `counties_generic/multi_year_delinquent_tax.py` — purpose-built to answer exactly
  tonight's question. Reads EVERY annual ArcGIS service for Buncombe NC / Oconee SC /
  Pickens SC back a decade+, auto-discovers new years as counties publish them, and
  structurally distinguishes "current levy not yet due" from "matured arrears" by row-
  count ratio rather than a hardcoded year — then requires ≥2 years AND ≥1 matured year
  before emitting, so single-year noise is dropped but real multi-year depth survives.
  This is the reference implementation the flagged files below should be made to match.
- `counties_sc/qpaybill_delinquent_roll.py` (19 SC counties) — explicitly queries
  `PaidStatus=Unpaid&SearchType=RealEstate&Year=All`, and separately solved a real
  *volume*-completeness bug (a lossy ASP.NET pager silently dropping 13% of a county)
  by unioning prefix-enumeration with paging rather than trusting either alone.
- `counties_sc/sc_catalis_delinquent_roll.py` (Pickens/Chester/Hampton) — `"year": -1`
  in the API body, and keys results by `BillingID:Year:RecordType` specifically so a
  parcel delinquent since 2016 doesn't collapse into one bill.
- `counties_nc/rutherford_wildfire_tax.py` — deliberately pulls ten tax years
  (TY2016–TY2025, 29,319 rows) and explicitly excludes only the *not-yet-due* current
  year, never older ones.
- `counties_sc/sc_dew_lien_registry.py` — tries `Export_All_Ind="Y"` first (the
  "active registry as of now" bulk dump) with `IssuedFrom`/`IssuedTo` left blank.
- `counties_nc/buncombe_tax.py` — `LOOKBACK_DAYS = 2000` (~5.5 years), a real historical
  fix (2026-08-02) for the exact failure mode this audit is about: a 90-day/forward-only
  window was returning 0 rows because the standing foreclosure list's dates are all in
  the past. Already fixed; a good worked example of what "fixed" looks like.
- `counties_sc/oconee_flc_assignment.py` — preserves `Year (1999–2019)` per row, no
  truncation.
- SC overage-claims family (`counties_sc/calhoun_overage_claims.py`,
  `counties_sc/fairfield_overage_claims.py`, `counties_sc/laurens_overage_claims.py`,
  `counties_sc/orangeburg_overage_claims.py`, `counties_sc/york_overage_claims.py`)
  — every one of these parses a single PDF that already contains 3-5 separate tax-sale
  years' rosters; none restrict to the newest year only.

**NCGS 105-369 single-annual-advertisement family** (see cross-cutting note above —
live-verified cumulative balance, reading the newest list is correct):
`counties_nc/cumberland_delinquent_tax.py`, `counties_nc/rowan_delinquent_tax.py`,
`counties_nc/mecklenburg_delinquent_tax.py`, `counties_nc/buncombe_delinquent_tax.py`,
`counties_nc/nc_tax_lien_ads.py` (Hoke/Lee/Davidson/Randolph), `counties_nc/nc_county_pdf_delinquent_tax.py`
(Lincoln/Catawba/McDowell — note: hardcoded `tax_year: 2025` per county, a maintenance/
staleness risk when the county rolls to 2026, not a date-exclusion bug), `counties_nc/nc_county_csv_delinquent_tax.py`
(New Hanover — explicitly sums multi-year bills per parcel), `counties_nc/nc_ptscloud_delinquent_tax.py`
(explicitly dedupes/sums multi-year rows by parcel).

**Full current-roll, status- or flag-filtered rather than date-filtered (the right
way to scope a roll):**
`counties_nc/asheville_code_enforcement.py` (`where="1=1"`, dead-feed health-check is
separate from row filtering), `counties_nc/henderson_code_violations.py` and
`counties_nc/lincoln_code_violations.py` (`_OPEN_WHERE` on status, not date),
`counties_nc/lincoln_vacant.py` and `counties_nc/transylvania_vacant.py` (`VACANT='YES'`
/ building-value flag, not date), `counties_nc/hendersonville_vacant_structures.py`
(docstring explicitly rejects an age cutoff: "27.3% are STILL actually vacant despite
the age"), `counties_sc/spartanburg_vacant.py`, `counties_sc/spartanburg_condemned.py` and
`counties_sc/spartanburg_city_condemned.py` (`where="1=1"` / condition-code filter, no
date logic anywhere in any of the three), `counties_nc/henderson_foreclosure_parcels.py`
(live `definitionExpression` walk, no date filter), `counties_nc/buncombe_elderly.py`
(bulk exemption-code query, no date filter), `city_websites/charlotte_open_data.py`
(`CaseStatus='Open'`, pages to exhaustion, explicitly keeps multi-year case histories).

**Other full-roll / full-document parses with no date-window code:**
`counties_nc/dc_ip_block.py`, `counties_nc/kinston_proposed_demolition.py`,
`counties_nc/rocky_mount_blight_survey.py` (one-time 2025 city survey snapshot — the
year is metadata about the survey date, not a filter), `counties_nc/gastonia_code_enforcement.py`,
`counties_nc/henderson_foreclosure_parcels.py`, `counties_nc/morganton_nc.py`,
`counties_nc/polk_tax.py`, `counties_nc/rutherford_tax.py` (TR-452 export, single current
snapshot, supplemented by the sibling ten-year `rutherford_wildfire_tax.py`),
`counties_nc/nc_avalon_tax.py` (no facets/year restriction sent at all — broader than
its sibling, paginated to exhaustion), `counties_nc/albemarle_observer_tax_lists.py`
(`MAX_AGE_DAYS` only skips a *stale* republished post whose debts have since been paid —
correctly avoids re-surfacing paid-off amounts, not an exclusion of real current debt),
`counties_sc/berkeley_paystar_tax.py` (server-side prior-years facet filter explicitly
built to avoid dropping true delinquents, with a documented 2026-10-03 regression fix),
`counties_sc/charleston_delinquent_tax.py`, `counties_sc/charleston_tax_sale_xlsx.py`,
`counties_sc/dorchester_billtrax_delinquent_tax.py`, `counties_sc/horry_delinquent_xlsx.py`,
`counties_sc/greenwood_corebtpay_delinquent_tax.py` (last-name prefix enumeration,
multi-year accounts handled via tax-year-suffix stripping), `counties_sc/greenville_delinquent_tax.py`
(explicit "Treated as a STANDING roster... not a scheduled future event"),
`counties_sc/greenville_hard_distress.py` (`TOTTAX > 0 AND PAIDDATE IS NULL`, no date
filter; tax-sale roster and probate name-index are both dateless by design),
`counties_sc/pickens_delinquent_parcels.py` (explicitly keeps 2020–2026 as separate
layers and flags prior-cycle-only parcels rather than dropping them — a strong example),
`counties_sc/pickens_tax_sale.py`, `counties_sc/spartanburg_delinquent_tax.py` (the
`datetime.utcnow().year` in both of these is only used to compute a *display* redemption
deadline, never to filter which rows are kept), `counties_sc/colleton_tax_sale.py`,
`counties_sc/oconee_tax_sale.py` (currently genuinely 0 rows off-season — correct, not a
parse failure), `counties_sc/york_tax_sale_parcels.py`,
`counties_sc/sc_tax_walled.py` (CAPTCHA/Turnstile-walled and currently
non-functional; no date logic present in what does run, and all three counties it targets
— Charleston, Dorchester, Georgetown — already have dedicated, working CLEAN scrapers
elsewhere, so this file is low-priority regardless), FLC family: `counties_sc/beaufort_flc.py`,
`counties_sc/horry_flc.py`, `counties_sc/lexington_flc.py`, `counties_sc/mccormick_flc.py`
(genuinely zero rows — confirmed no FLC list published anywhere, a source wall not a
code bug), `counties_sc/oconee_forfeited_land.py`, `counties_sc/richland_flc.py`,
`counties_sc/spartanburg_flc.py`, `counties_sc/terry_howe_flc.py`.

**Plain single-page/PDF SC delinquent-tax parsers** (no query params at all — the whole
published page/PDF is read every run, so there is no code-side mechanism by which these
could narrow the date range even if someone wanted to): `counties_sc/abbeville_delinquent_tax.py`,
`counties_sc/aiken_delinquent_tax.py`, `counties_sc/chester_delinquent_tax.py`,
`counties_sc/cherokee_delinquent_tax.py` (multi-year PDF discovery across 2021-2026 +
OCR fallback for scanned PDFs — above-average engineering for this group),
`counties_sc/darlington_delinquent_tax.py`, `counties_sc/dillon_delinquent_tax.py`,
`counties_sc/edgefield_delinquent_tax.py`, `counties_sc/fairfield_delinquent_tax.py`,
`counties_sc/florence_delinquent_tax.py`, `counties_sc/laurens_delinquent_tax.py`,
`counties_sc/newberry_delinquent_tax.py`, `counties_sc/union_delinquent_tax.py`,
`counties_sc/york_delinquent_tax.py`, `counties_sc/georgetown_civicengage.py` (its FLC
and tax-sale PDFs are both dateless standing lists with no date filter; its monthly
Master-in-Equity rosters cap at the 4 most recent — correctly, since that part is a sale
calendar, not a debt roll).

---

## FLAGGED — code-imposed limit (4) — the actionable target of this audit

### 1. `counties_nc/nc_its_public_tax.py` — HIGH confidence, HIGH board impact
Covers Onslow (7,428 unpaid 2025 bills alone) and Graham via the ITSPublic/bitek
`TaxBillSearch` portal. The portal is queried **per tax year** (`fetch_year(client,
portal, year, ...)` loops and POSTs `{"TaxYear": str(year), "UnpaidBillsOnly": true}`),
proving the source itself will answer for any year asked. But the code only asks for
`YEARS_BACK = int(os.getenv("ITS_TAX_YEARS_BACK", "3"))` years — the three most recent
delinquent tax years, no further. A parcel delinquent for 4+ years has its oldest
year(s) never queried at all, which both understates its true balance (each year here
is a separate billed amount, summed — unlike the NCGS 105-369 cumulative-snapshot
family above) and understates `years_delinquent`, the exact severity signal the scoring
model should be rewarding most. **Fix shape:** raise `ITS_TAX_YEARS_BACK` (or make it
unbounded / "all years with an outstanding bill") — the per-year loop and pagination
machinery already exist; this is a one-constant change, not a rebuild.

**RESOLVED 2026-10-14 (Phase 2).** `YEARS_BACK` raised `3 -> 20` (a safety ceiling, not a
target), with a new "two consecutive empty years" early stop so a shallower portal does not
pay for guaranteed-empty years and a single-year blip (see below) never trips it early.
Live-verified real depth before changing anything: Onslow answers nonzero unpaid bills back
to 2010 (16 years; one genuine blip at 2015 — 0 bills, with 2014 and 2010 both nonzero either
side of it), Graham back to 2015 (11 years, monotonic), and a spot-checked "full_model"
county from the 2026-10-09 build (Harnett) nonzero at 2025/2020/2015/2010 alike — this
widening matters beyond just Onslow/Graham. Tests added
(`tests/test_nc_its_public_tax.py`): `YEARS_BACK == 20`; a synthetic 6-year crawl proving a
lone empty year does not stop the read but two in a row does; and a direct aggregation test
showing a parcel delinquent 10 straight years now reports `years_delinquent == 10` and
`total_due == $500.00`, where feeding the SAME 10 years through the old `back=3` window
recovers only `years_delinquent == 3` and `total_due == $150.00`. All 34 pre-existing tests
plus 3 new ones pass (37 total).

### 2. `counties_nc/transylvania_delinquent_tax.py` — HIGH confidence
Same ITSPublic/bitek platform and API shape as #1 above (`TaxBillSearch` ->
`GetSearchTablePartial` -> `GetSearchTableData`), but this file has **no year loop at
all** — it queries a single hardcoded `FORECLOSURE_TRANSYLVANIA_TAX_YEAR` (default
`"2025"`) and stops. Its own sibling file proves the exact same vendor platform
supports a multi-year sweep; this file was simply never generalized the same way. A
Transylvania parcel that caught up on 2025 but still owes 2022-2024 would never surface.
**Fix shape:** port `nc_its_public_tax.py`'s `fetch_year`/`YEARS_BACK` loop onto this
county's `_search_model(tax_year)` — the request model is already parameterized by
year, it just isn't called more than once.

**RESOLVED 2026-10-14 (Phase 2).** Live-verified real depth first: every tax year
2014-2025 (12 years) answers a nonzero unpaid-bill count on this portal; 2013 and every
year before it answers 0. Ported the sibling's multi-year loop (`YEARS_BACK` default 15,
same two-consecutive-empty-years early stop) onto `_search_model(tax_year)`, grouping
every bill read by PARCEL (falling back to account when the grid carries no parcel id) and
summing balance/levy across years — the same per-parcel-sum shape
`nc_its_public_tax.aggregate` already uses, publishing `years`/`years_delinquent`/
`oldest_year`/`two_year_delinquent`/`tax_owed` (both of the latter two keys already
registered in `web_artifact.py` via `nc_its_public_tax.py`, so nothing new to register).
Only the group's newest-year bill gets the expensive `ViewTaxBill` detail fetch (owner
mailing / parcel / value are account-level, not per-year), so enrichment cost tracks
distinct parcels, not bill-rows read. **Before/after, live:** the old single-year behavior
(reproduced via the still-supported `FORECLOSURE_TRANSYLVANIA_TAX_YEAR=2025` override) —
235 listings, 0 with any multi-year depth. The fixed default (2014-2025) — **308 listings**,
**134 (44%) delinquent in 2+ separate years**, the three deepest delinquent all **12
straight years** (2014-2025) with real accumulated balances ($1,166.41 / $1,738.97 /
$1,319.97). Tests added (`tests/test_transylvania_delinquent_tax.py`, 11 new) plus the 8
pre-existing tests for this file (personal-property filter, `ViewTaxBill` field parsing)
all pass unchanged (19 total for this module).

### 3. `counties_sc/charleston_energov_history.py` — HIGH confidence, board-wide impact (Charleston)
Queries Charleston's EnerGov history layer with an explicit `since = now - timedelta(days
= FORECLOSURE_CHARLESTON_ENERGOV_DAYS)` WHERE-clause, default **730 days**. The file's
own docstring states the full layer holds 386,391 rows updated daily with "1,871 [building
code cases] since 2010" and "3,222 [demolition permits] since 2010" — i.e., the source
is a complete 16-year history, and the code only ever asks for the newest 2 years of it.
An old, unresolved code case or a demolition permit pulled years ago on a structure still
standing (a textbook zombie/vacant-property signal) is invisible to this scraper, not
because the county doesn't have the record, but because the query never asks for it.
**Fix shape:** widen or remove `FORECLOSURE_CHARLESTON_ENERGOV_DAYS`'s 730-day default;
the existing `stale_after`/365-day-open heuristic already handles deciding whether an
old case is still "live" for scoring purposes downstream — it doesn't need the fetch
itself pre-filtered to 2 years to do that job.

**RESOLVED 2026-10-14 (Phase 2).** Date floor dropped by default (`since=None`); the env
var still narrows it for an explicit sample run. A `_MAX_RECORDS_PER_SLICE=50,000` safety
cap (not a relevance filter) was added to the now-unbounded query, matching this
codebase's convention for a dateless WHERE clause. Live-verified before/after: the 730-day
window pulled 1,049 cases -> 469 leads; the fixed default pulls **5,046 cases -> 2,778
leads** (a 5.9x increase), code cases now reaching back to 2010-11-04 (vs. 125/1,873 all-
time inside the old window, 93% excluded) and demolition permits to 2016-04-11 (944/3,228
inside the old window, 71% excluded). Tests added (new file
`tests/test_charleston_energov_history.py`, 5 tests): `where_clauses` with/without a date
floor, a 2010 case flowing through `unique_cases`/`group_by_property`/`to_listing` with no
date logic standing in its way, and a full `fetch()` integration test (mocked ArcGIS
transport) proving a 2010 code case and a 2016 demolition permit are both included by
default and both dropped when `FORECLOSURE_CHARLESTON_ENERGOV_DAYS=730` is set explicitly.

### 4. `counties_nc/nc_metro_demolition_permits.py` — MEDIUM-HIGH confidence, 4-metro impact (Mecklenburg/Charlotte, Greensboro, Durham, Cary)
Same shape as #3: `FORECLOSURE_DEMOLITION_DAYS` defaults to **730 days**, applied as a
WHERE-clause date filter against all four metro feeds. The file's own measured counts
make the gap concrete: Mecklenburg shows 1,760 demolition permits "all-time" vs. 1,486
"issued in the window" (274 silently excluded in Mecklenburg alone); Greensboro shows
3,023 all-time vs. 149 in the window — a 95% exclusion rate in that one feed. A
demolition permit pulled years ago where the structure is still standing is one of the
strongest "zombie property" signals this engine has, and this window is actively
discarding most of them.
**Fix shape:** same as #3 — widen the default or drop the WHERE-clause date filter
entirely and let a downstream staleness heuristic (if one is wanted) operate on the full
pull instead of gating the fetch itself.

**RESOLVED 2026-10-14 (Phase 2) — plus a separate break found live.** Date floor dropped
by default on all 4 feeds (`since=None`), bounded by a new `_MAX_RECORDS_PER_FEED=50,000`
safety cap passed through a `fetch_attrs(..., max_records=...)` parameter added to the
shared `_layer_kit.py` helper (backward-compatible: every other caller of `fetch_attrs`
is unaffected, since the new parameter defaults to `None`). Live-verifying Mecklenburg
turned up a SEPARATE, unrelated break: the `AccelaAllPermits` FeatureServer this file
pointed at since 2026-10-07 now 404s outright — the county migrated to a `BuildingPermits`
service with a completely different field schema, AND its own classification of "this is a
demolition permit" changed shape at the same time (`worktype='Demolish'` is a legacy tag
used only through 2017-03-09; every demolition since is identifiable only by `permitdesc
LIKE '%Demolish/Move Off%'`). Both are fixed together: the Feed definition now points at
the live service with the OR'd classification, and `_get` gained a tuple-fallback-chain
mode so a row's `type` field still resolves even when the legacy tag is blank. **Before/
after, live, full `fetch()` run:** under the OLD 730-day window (still reproducible via
`FORECLOSURE_DEMOLITION_DAYS=730`) — Mecklenburg 0 (dead URL, independent of any date
logic), Greensboro 143, Durham 209, Cary 134 — 486 total. Fixed default (no floor, URL
repointed) — **Mecklenburg 10,800, Greensboro 2,928, Durham 1,671, Cary 414 — 15,813 total
leads**, spanning 1991-04-11 to 2026-10-14. Tests added (new file
`tests/test_nc_metro_demolition_permits.py`, 13 tests): WHERE-clause construction with/
without a date floor for every feed, the `_get` fallback chain, real-shaped 1991/1997/2007
rows becoming listings with no date logic in the way, and a full `fetch()` integration
test (mocked transport honoring the literal `DATE '...'` floor) proving decades-old
permits are included by default and excluded when the env var is set.

A fifth candidate, `counties_nc/nc_civicplus_tax_sale.py`, looked similar at first read
but turned out to be a different kind of question — see UNCLEAR below rather than here,
since the open issue on that file is about per-county page content (verified per
county, not a single code constant to change).

---

## FLAGGED — source limitation (3)

- **`counties_nc/wake_code_cases.py`** — Wake County's own published ArcGIS layer is
  literally named `codecases_90days_test` and is itself a rolling 90-day window; there is
  no fuller public layer behind it to query instead. Not fixable at the code level.
- **`counties_nc/iredell_delinquent_tax.py`** — the ArcGIS layer this reads carries only
  a boolean "Delinquent Taxes Owed" flag, no levy year and no balance at all. The code
  conservatively reports exactly one delinquent year (the newest one that can legally be
  late) rather than guessing a deeper history it has no evidence for. The real multi-year
  data would come from Iredell's own PTS tenant, which the docstring notes currently
  answers HTTP 500 — a live-site outage, not something this scraper's code controls.
- **`counties_sc/sc_state_tax_lien.py`** — SCDOR itself only publishes a curated "Top
  Delinquent Taxpayers" list (quarterly), not the state's full lien registry; the code
  was recently fixed (2026-10-01) to read every page of that published list plus the
  business tab, so nothing within SCDOR's own publication is missed, but the ceiling is
  SCDOR's choice of what to publish, not this code's.

Separately worth a mention even though it is not one of the three above and stays
classified CLEAN: `counties_nc/nc_county_pdf_delinquent_tax.py`'s three hardcoded URLs
each carry a literal `tax_year: 2025`; when Lincoln/Catawba/McDowell roll to their 2026
advertisement, this file goes silently stale until someone manually updates the URL.
That is a maintenance risk adjacent to this audit's concern, not a date-window
exclusion bug — it doesn't drop old debt, it just needs an annual URL refresh.

---

## UNCLEAR — needs live check (1)

- **`counties_nc/nc_civicplus_tax_sale.py`** — this is a generic sitemap-discovery +
  regex crawler covering roughly 40 NC counties that don't have a dedicated scraper. No
  date-window code was found anywhere in it (no `since`/`cutoff`/`year=` query param);
  it parses whatever text is currently on each county's own tax-foreclosure/tax-sale
  page. That means its date-coverage is entirely a function of *what each of those ~40
  individual county pages currently contains* — which cannot be determined by reading
  this one file, because the answer is different for every county and changes whenever a
  county redesigns its site. **What a live check needs to confirm:** pull a handful of
  the ~40 covered county pages directly (the module's own docstring and `COUNTY_PAGES`-
  style config should list them) and classify each landing page as (a) a genuine current
  delinquent/sale roll — fine, matches the rest of this audit's CLEAN group, (b) an
  event-type sale-date notice — fine, no fix needed, or (c) frozen/stale content that's
  been superseded by a URL change the crawler never caught — the same failure mode
  already found and fixed on `morganton_nc.py` and `rutherford_tax.py` elsewhere in this
  codebase. Given ~40 counties behind one file, even a handful of (c) results would be a
  meaningful board-impact fix.

**RESOLVED 2026-10-14 (Phase 2) — FLAGGED, real issue found and fixed (not CLEAN).** This
file actually covers 67 counties, not ~40. Live spot-checked 8 (Gaston, Guilford, Harnett,
Union, Wayne, Johnston, Davidson, Cherokee): Davidson and Cherokee confirmed healthy
(PDF/case-table parsing already correct, matching prior fixes); Guilford has a dedicated
scraper elsewhere so a miss here costs nothing; Union is behind a WAF (403 on the bare
domain itself — a wall, not a code bug, consistent with this codebase's no-bypass policy);
Johnston's site isn't CivicPlus at all (no `/sitemap.aspx`, 404) — a per-county coverage
gap, not fixable by this generic crawler. Harnett returned real listings. **Wayne surfaced
a genuine, fixable parsing bug:** its real tax-foreclosure page is a CivicPlus "News Flash"
index whose own per-sale-event article (reached one hop further, e.g.
`/CivicAlerts.aspx?AID=1058`) read, live: *"Tract 1: Located at: 302 Grace's Farm Rd., La
Grange, NC Parcel: 3546118609 File Number: 26CV000314-950 OPENING BID: $10,303.43"* —
`PARCEL_RE` and `MONEY_RE` both matched this text fine, but `ADDR_RE`'s middle character
class had no apostrophe, so "302 Grace's Farm Rd" (a real, common rural-NC road-name shape)
never matched at all, and Pattern 2 (the free-text fallback) is driven by iterating
`ADDR_RE`'s own matches — so this real, live, $10,303.43 pending tax-sale lead was
**silently dropped entirely** (0 listings parsed from a page that had exactly 1 real one).
**Fix:** added both apostrophe forms (straight `'` and the curly `’` CivicPlus
actually renders) to `ADDR_RE`'s two character classes — additive only, every existing
fabrication-prevention test (the `Address`/`...Dr` and `auction`/`...Ct` substring-match
regressions) is unchanged since neither forbidden match contains an apostrophe. Live
re-verified: `_parse_tax_sale_page` on the real Wayne page now returns exactly the 1 real
listing (0 -> 1). Tests added to the existing `tests/test_nc_civicplus_tax_sale.py` (2 new,
13 total, all pass): `ADDR_RE` matching a street name with an apostrophe while the existing
fabrication guards stay intact, and a field-faithful reproduction of the live Wayne page
recovering the real lead end-to-end. **Separately noted, not fixed this pass (future
follow-up, out of this task's scope):** the News-Flash "index page -> per-event article"
two-hop pattern Wayne uses is a common CivicPlus module likely shared by other counties in
this same 67-county list; `_find_tax_sale_links` only scans a CANDIDATE page's links for
keyword matches, it never re-scans a page it already decided WAS the destination, so a
county whose real content sits one hop past its discovered landing page is still missed
today. Worth a dedicated look, but out of scope for the apostrophe fix that resolved this
file's UNCLEAR status.

---

## Prioritized Phase-2 live-verify-and-fix list

**STATUS 2026-10-14: all 5 done.** 1-4 fixed for real, live-verified before/after (see the
"RESOLVED 2026-10-14 (Phase 2)" note inline under each item above); 5 resolved from
UNCLEAR to FLAGGED-and-fixed (a real apostrophe-regex bug found and fixed on live Wayne
County data, plus a separate News-Flash two-hop pattern noted as a future follow-up, not
fixed this pass). Tests added per file; full before/after row counts inline above.

1. **`counties_nc/nc_metro_demolition_permits.py`** — four of NC's largest metro areas
   (Mecklenburg/Charlotte, Greensboro, Durham, Cary) behind one file, one constant
   (`FORECLOSURE_DEMOLITION_DAYS=730`) to change, and the file's own numbers already
   prove the gap (up to 95% of Greensboro's demolition history excluded). Highest
   volume, lowest effort — do this first.
2. **`counties_nc/nc_its_public_tax.py`** — Onslow alone carries 7,428 unpaid 2025 bills
   through this file; raising/removing `ITS_TAX_YEARS_BACK` recovers every parcel whose
   arrears run past 3 years, using machinery (the per-year loop) that already exists.
3. **`counties_sc/charleston_energov_history.py`** — Charleston is SC's largest coastal
   county in this footprint; the 730-day code-recall window is hiding most of a 16-year
   source (386k rows) behind one constant, same fix shape as #1.
4. **`counties_nc/transylvania_delinquent_tax.py`** — smaller county, but the fix is
   nearly free: copy `nc_its_public_tax.py`'s already-proven multi-year loop onto the
   same vendor platform's `_search_model(tax_year)` call.
5. **`counties_nc/nc_civicplus_tax_sale.py`** — lowest confidence, highest potential
   surface area (~40 counties behind one generic crawler). A one-afternoon live spot
   check of a dozen of its covered county pages would either clear this file entirely or
   surface a short list of specific counties worth a dedicated fix — worth doing early
   precisely because it's cheap to resolve and currently the only files-count unknown in
   this whole audit.

Everything else flagged above (`iredell_delinquent_tax.py`'s boolean-flag layer,
`sc_state_tax_lien.py`'s state-curated top-list, `wake_code_cases.py`'s 90-day-only
public layer, `nc_county_pdf_delinquent_tax.py`'s hardcoded-year maintenance risk) is a
genuine source ceiling or a staleness/maintenance item rather than a fixable date-window
bug, and does not need to be on this list.
