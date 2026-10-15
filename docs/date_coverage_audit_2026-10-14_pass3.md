# Date-coverage audit — Pass 3 — 2026-10-15

Pass 1 (`docs/date_coverage_audit_2026-10-14.md`) and Pass 2
(`docs/date_coverage_audit_2026-10-14_pass2.md`) covered 215 scraper files total
(127 "current-state roll" candidates in Pass 1, 88 "event-stream" candidates in
Pass 2 — with some overlap in which files each pass actually read, since both
started from independent keyword sweeps of the same source tree). This is Pass 3,
covering the **remaining ~88 scraper files neither pass had reviewed** —
enumerated by diffing the full set of `.py` files under
`src/foreclosure_scraper/scrapers/` (every package `_registry.py.discover()`
actually imports, i.e. every non-`__init__`, non-underscore-prefixed module)
against every file path named in Pass 1's and Pass 2's own text. 88 files came
back uncovered; all 88 were reviewed this pass.

**Method.** The same two questions as before, applied to whatever shape each file
actually turned out to be:

1. **Current-state-roll shape** (Pass 1's question): does the code impose an
   artificial date/lookback cap narrower than what the source itself offers?
2. **Event-stream shape representing an ongoing status** (Pass 2's question):
   does the scraper rely solely on "new event in the last N days" for something
   that's really an ongoing case/status, with no board-retention protection
   (`board_persist.AGE_EXEMPT_SOURCES` / `OPEN_CASE_SOURCES` / a status-aware
   `open_case_hold()` branch) and no status field actually checked?

Most of the 88 files turned out to be **neither shape** — national real-estate
listing aggregators (self-correcting: a delisted property really was sold/
withdrawn most of the time, the same reasoning Pass 2 already applied to Zillow/
Trulia/auction.com), one-time-event feeds (obituaries, fire incidents, disaster
declarations, jail bookings viewed as a point-in-time booking record), disabled/
dead modules, and a few registry/enrichment helpers with zero callers or a
`fetch()` that always returns `[]`. Those were classified `N/A-not-applicable-
shape` quickly, per the task's own framing. Real effort went into anything that
looked like a genuine roll or an ongoing-status event stream — live HTTP checks
were used only where a wall/CAPTCHA or a source's own data shape needed
confirming, not to re-derive conclusions code-reading alone already settled
(the same rigor split Pass 1/2 used for their own bulk-CLEAN groups).

This pass was split into 6 parallel batches of ~15 files apiece; each batch read
both prior audit docs in full first, then classified its files using the same
taxonomy and reported back with line-number evidence before anything was fixed.

**Result: 88 files reviewed. 36 CLEAN, 41 N/A-not-applicable-shape,
10 FLAGGED-no-ongoing-tracking (9 fixed this pass, 1 left open pending a live
check that needs more than plain httpx), 1 UNCLEAR (needs a live check, same
reason), 0 FLAGGED-code-limit, 0 FLAGGED-source-limit.**

The 0/0 on Pass 1's own pattern (an artificial *date-cap* on a current-state
roll) makes sense in retrospect: Pass 1 already read essentially every roll-
shaped scraper in the codebase. What was left for Pass 3 was almost entirely
either "not this shape at all" or Pass 2's ongoing-status gap recurring on
files Pass 2's own keyword sweep had missed.

---

## CLEAN (36)

Grouped by why each is clean; one line per file except where worth naming.

**Flag/status-filtered current-state rolls, no date logic (current-state-roll
shape, scoped correctly)** — `counties_generic/arcgis_distress_layers.py` (~26
county ArcGIS layers in one config table; every WHERE clause across all 1205
lines is status/value-based — `real_value>0`, `STATUS='Open'`,
`TOTTAX>0 AND PAIDDATE IS NULL` — zero date/since/cutoff logic anywhere),
`counties_generic/epa_frs_sites.py`, `counties_generic/state_contamination.py`
(NC DEQ UST/LUR/hazardous/dam registries, county-prefix filter only),
`counties_nc/asheville_helene.py` (`current_posting IN ('Unsafe','Restricted')`),
`counties_nc/asheville_str_permits.py` (`record_status IN ('Expired','Revoked')`),
`counties_nc/gaston_vacant.py` (`VacantImpro='Vacant'`; docstring documents a
2026-09-15 fix for the *inverse* failure — `SALEDATE` was wrongly read as
`sale_date`, dropping all 21k rows — now correctly dateless),
`counties_nc/mcdowell_probate.py` (`ownname LIKE '%DECEASED%'`),
`counties_sc/sc_ust_registry.py` (46 SC counties, no date/year param at all —
same shape as Pass 1's gold-standard `sc_dew_lien_registry.py`).

**Live current-snapshot crawls / full-document reads, no code-side date
window** — `counties_generic/sitemap_walker.py` (14 counties; re-fetches each
county's sitemap + re-parses whatever's currently published every run; its
`ADDR_RE` already carries the apostrophe character class the Wayne-County fix
added to its sibling `nc_civicplus_tax_sale.py`, so it doesn't have that bug),
`counties_nc/gaston_surplus_properties.py` (whole published PDF, dateless by
design), `counties_nc/mcdowell_tax_foreclosure.py` (NC in-rem tax-foreclosure
sale docket — same family Pass 1/2 already confirmed CLEAN), `counties_nc/
nc_bankruptcy_sales.py` (bankruptcy trustee sale notices — durable point-in-time
facts, same reasoning as the newspaper/law-firm-sale-list CLEAN group),
`counties_nc/nc_deq_dsca.py` (whole xlsx workbook every run, filtered to
footprint counties only), `counties_nc/nc_heir_estate_parcels.py` (live GIS
owner-of-record query), `counties_nc/nchfa_reo.py` (live for-sale listing, no
date logic — separate from its already-known Drupal-migration parser bug,
tracked elsewhere), `counties_sc/sc_coastal_rosters.py` and `counties_sc/
sc_county_rosters.py` (Master-in-Equity live-roster shape Pass 2 already
cleared).

**Probate/estate scrapers that already re-check open/closed status every
run — the probate analogue of Pass 2's Charleston reference pattern** —
`counties_sc/greenville_probate.py` (`is_current()` keeps any estate with no
Closed Date regardless of age) and `counties_sc/sc_probate_net.py` (same
`is_current()` shape). `counties_sc/sc_probate_notices.py` is clean for a
different reason: a published legal notice is a durable point-in-time fact
(Pass 2's newspaper-notice reasoning), not a status to re-check.

**Live, self-correcting national listing/auction feeds (re-derived fresh every
run — a delisted property really was sold/withdrawn most of the time; this is
the generic `pulled_sale` miss-counter's designed-for job, not a gap)** —
`national/auction_bank_reo.py`, `national/bid4assets.py`, `national/
craigslist_fsbo.py`, `national/crexi_multifamily.py`, `national/cws_marketing.py`,
`national/fannie_homepath.py`, `national/first_citizens_reo.py`, `national/
foreclosure_dot_com.py` (currently 403-walled — an access issue, not a date-
coverage one), `national/freddie_homesteps.py`, `national/govdeals.py` (status
filter `assetstatus`/`searchStatus`, not a date window), `national/
gsa_surplus.py`, `national/hibid_real_estate.py`, `national/homepath_json.py`,
`national/hubzu.py`, `national/hud_homestore.py`, `national/irs_treasury_
auctions.py` (same shape as the already-CLEAN sibling `irs_judicial_sales.py`),
`national/landandfarm.py`, `national/landwatch.py`, `national/seeclickfix.py`
(current-state-roll shape, correctly un-windowed — current API access is itself
Cloudflare-walled, noted as a follow-up, not a date bug), `national/
servicelink_auction.py`, `national/sheriff_sales.py` (938 lines, zero LOOKBACK/
since/cutoff constants anywhere; `sale_date` populated at all 5 `Listing()`
sites), `national/homeharvest.py` (its own `past_days=30` call was already
removed 2026-10-08 after a live-verified active-listing drop; the module
docstring is just stale about it — a one-line comment fix, not a behavior bug,
left as a note rather than an edit this pass).

**Current-state rolls with no date filter, read in full** — `national/
hud_reac_inspection.py` (entire ~26k-row national inspection-score dataset
downloaded every run, filtered to NC/SC after the fact — Pass 1's exact
gold-standard shape), `national/hud_section8_contracts.py` (same: full national
property+contract files streamed every run; `EXPIRING_SOON_DAYS=365` only sets a
cosmetic flag, nothing is excluded by it), `national/jail_bookings.py` (checked
the specific risk the task flagged: does NOT use "booked in the last N days" as
a stale proxy for "currently incarcerated" — every one of its 5 vendor fetchers
re-reads that vendor's own real-time in-custody roster fresh each run;
`booking_date` is display metadata only, never a re-fetch gate — correct design).

---

## N/A — not applicable shape (41)

**Disabled / dead / zero-caller modules (nothing live to audit a date window
on):** `counties_sc/sc_qpublic.py`, `national/epa_superfund.py`, `national/
landsofamerica.py` (Akamai Sensor wall, re-confirmed 2026-10-13), `national/
liensnc.py` (a different, separately-disabled file from `counties_generic/
liensnc.py`, which is the real, active AGE_EXEMPT_SOURCES member — confirmed by
reading its own docstring, not assumed from the shared filename), `national/
nc_sos_ucc.py`, `national/opencorporates.py`, `national/probate_foreclosure_
leads.py` (disabled stub), `national/propwire_foreclosures.py` (disabled stub),
`national/sc_sos_entity.py`, `national/va_acquired.py`, `counties_nc/
nc_tylertech_estates.py` (confirmed redundant with a working sibling).

**Helper/enrichment modules that never touch the board directly:** `national/
people_search.py` (`fetch()` always returns `[]`; writes only to its own
side-ledger), `national/stealth_handoff.py` (a Mac→VM transport layer, not a
scraper — passes through each lead's *original* source field, so it carries no
date-window logic of its own; the real sources behind it are each audited on
their own terms elsewhere).

**One-time point-in-time events (not an accumulating debt roll, not a case with
an open/closed status):** `city_websites/raleigh_structure_fires.py` (a fire),
`national/fdic_failed_banks.py` and `national/fema_disasters.py` (each has an
explicit, reasoned 730-day decay window with its own docstring rationale — a
bank failure or a disaster declaration is a terminal event with no accruing
balance and no case to lose track of; judged as correctly-designed decay, not a
bug, medium confidence since this is a design judgment rather than an HTTP
fact), `national/estate_sales.py`, `national/legacy_obituaries.py`, `national/
usda_properties.py`, `national/usmarshals_realproperty.py` (its own
`_CLOSED_STATUSES` already filters resolved rows — a status filter, not a date
cutoff), `national/zillow_bulk.py` (feeds the sold-comp pool, not active leads —
`listing_type` is hardcoded `REO`/sold-comp, no case/status concept at all),
`public_notices/echovita_obituaries.py`, `public_notices/funeral_home_rss.py`,
`public_notices/gannett_obituaries.py`, `public_notices/obituary_feeds.py`,
`reo/gsa_realproperty.py`, `reo/treasury_seized.py` (considered the "long-lived
forfeiture case" angle specifically — this file only reads the current auction
*listing* page, not a case docket, so it's self-correcting like the national
listing group above, not a forfeiture-case tracker), `reo/usda_rd.py`, `reo/
vrm_va_reo.py`.

**Live marketplace feeds (self-correcting, same reasoning as the CLEAN national-
aggregator group — listed here rather than CLEAN only because no CLEAN-worth-
naming mechanism needed calling out):** `national/loopnet.py`.

---

## FLAGGED — no ongoing-case tracking (10) — 9 fixed this pass

Same fix shape Pass 2 established: add the scraper's slug (or its bare slug
*component*, for the `AGE_EXEMPT_SOURCES` any-dotted-part match) to `board_
persist.py`'s `AGE_EXEMPT_SOURCES` (a recorded/filed fact that doesn't need
"is this still true" rechecking) or to a status-aware `*_open_hold()`
frozenset (when a real status field exists to branch on). Confirmed for every
item below by directly reading the scraper's `Listing()` construction (does it
ever set `sale_date`? does it write a raw status field anything already reads?)
and grepping `board_persist.py`/`main.py` for the slug — not by trusting a
sub-agent's summary at face value.

### 1. `counties_nc/nc_ecourts_divorce.py` — HIGH confidence, FIXED
Same vendor/API as the already-protected `counties_nc/nc_ecourts_lis_pendens.py`
(Pass 2 item #1): `JUDGMENT_LOOKBACK_DAYS = 120` on `orderedDate`, `sale_date`
always `None`, and it already writes `raw["nc_ecourts"]["civilJudgmentStatus"]`
+ `raw["nc_ecourts"]["orderedDate"]` — the *exact* raw block name and field
names `board_persist.nc_ecourts_open_hold()` already reads. It was simply never
added to `NC_ECOURTS_OPEN_SOURCES` when that frozenset was built for its
sibling. **Fix:** added `"counties_nc.nc_ecourts_divorce"` to
`NC_ECOURTS_OPEN_SOURCES` (`board_persist.py`). No scraper edit needed — the
raw shape already matched. (Already in `main.DATELESS_OK_SOURCES`, confirmed —
no prerequisite gap here.)

### 2. `counties_nc/nc_rowan_cott.py` — HIGH confidence, FIXED (two stacked bugs)
(a) `Listing()` never sets `sale_date` (confirmed: no `sale_date` anywhere in
the file) and the slug was **not** in `main.DATELESS_OK_SOURCES` — every row
this scraper ever produced was being deleted by `_active_only()` before
reaching the board at all, independent of any retention question. (b) Even
once (a) is fixed, a Rowan County deed-index recording is discovered only
through this scraper's own sweep window with no case-status field, and the
slug was not in `AGE_EXEMPT_SOURCES` either — a real, resurfaced row would
still age out within a few runs. **Fix:** added `"counties_nc.nc_rowan_cott"`
to `main.DATELESS_OK_SOURCES` (prerequisite) and `"nc_rowan_cott"` to
`board_persist.AGE_EXEMPT_SOURCES`.

### 3. `counties_sc/anderson_acpass_deeds.py` — HIGH confidence, FIXED
Already in `main.DATELESS_OK_SOURCES`. Confirmed absent from `AGE_EXEMPT_
SOURCES` — same ROD/NOD-family gap Pass 2 fixed for 9 other files, just missed
on this one. **Fix:** added `"anderson_acpass_deeds"` to `AGE_EXEMPT_SOURCES`.

### 4. `counties_sc/horry_probate.py` — HIGH confidence, FIXED
Pure 365-day filed-date cutoff (`HORRY_PROBATE_LOOKBACK_DAYS`), no status/
disposition field read anywhere in the file despite the search API exposing
one (per its own docstring) — an open SC estate stays open far longer than 365
days. Already in `main.DATELESS_OK_SOURCES`. **Fix:** added `"horry_probate"`
to `AGE_EXEMPT_SOURCES` (no status field reachable to build a status-aware
hold instead, same `liensnc` model as the rest of this list).

### 5. `national/cash_buyer_deeds.py` — HIGH confidence, FIXED
A NC ROD recording sweep dressed up as a "national" module: `LOOKBACK_DAYS =
30` across the same 10-county Aumentum/CCHS/Cott/Logan vendor machinery Pass
2's already-fixed ROD/NOD family uses. A cash-buyer deed finding is a
permanent recorded fact (the grantee really did buy in cash; that doesn't
become untrue later) — same reasoning as its 9 siblings, not an open-case
shape. `sale_date = deed.recorded_date` is a real historical date (not a
fabricated one like `nod_discovery`'s old bug), so the unconditional terminal-
sale-date rule still correctly ages out a stale row once exempted. Already in
`main.DATELESS_OK_SOURCES`. **Fix:** added `"cash_buyer_deeds"` to `AGE_EXEMPT_
SOURCES`. (Separate, unrelated CCHS-vendor-wall/completeness issues on this
same file were handled earlier in this session's Job 1 — see `docs/
silent_failure_sweep_2026-10-14.md` — and are out of scope here.)

### 6. `national/nc_unclaimed.py` — HIGH confidence, FIXED (two stacked bugs)
Same shape as `nc_rowan_cott.py` above: (a) `Listing()` never sets `sale_date`
and the slug was **not** in `main.DATELESS_OK_SOURCES` — every row was being
deleted before reaching the board. (b) The scraper's own per-surname search
ledger never re-searches a surname once searched, so a genuinely still-
unclaimed property can never be re-matched by a fresh scrape; no status field
exists to check (the search, by construction, only ever returns *currently*
unclaimed rows), so `AGE_EXEMPT_SOURCES` (the `liensnc` model) is the only
available fix, not a status-aware hold. **Fix:** added `"national.nc_
unclaimed"` to `main.DATELESS_OK_SOURCES` and `"nc_unclaimed"` to `AGE_EXEMPT_
SOURCES`.

### 7. `public_notices/nc_heir_notices.py` — HIGH confidence, FIXED
Already in `main.DATELESS_OK_SOURCES`. A NC quiet-title/heir-naming court
notice (real case numbers, `WINDOW_DAYS = 180`) with no status field to check
— the underlying heir/estate situation stays actionable for months to years
after the notice itself ages out of the sweep window. **Fix:** added `"nc_heir_
notices"` to `AGE_EXEMPT_SOURCES`.

### 8. `public_notices/publicnoticesc_estates.py` — HIGH confidence, FIXED
Same shape as #7: already in `main.DATELESS_OK_SOURCES`, 60-day default
window, no status field reachable (the real disposition/rep-status page is
CAPTCHA-walled). A SC estate stays open for months (creditor-claim period +
administration). **Fix:** added `"publicnoticesc_estates"` to `AGE_EXEMPT_
SOURCES`.

### 9. `counties_nc/nc_cchs_deeds.py` — MED confidence (latent, zero current board impact), FIXED anyway
Same ROD/NOD recorded-deed shape as the rest of this list (`90`-day cutoff, no
case-status field), but this file's own 2026-10-13 docstring — written and
live-verified by an earlier pass the same day, not re-verified live by this
pass — documents that it currently returns 0 rows for all 6 counties for
independent reasons (a guessed search URL that 404s, a genuine Cloudflare wall
on 2 hosts, and reproducible backend 524 timeouts on the other 4). Nothing is
actually dropping off the board today, so this is lower-confidence than items
1-8 above in the sense that it has no live-verified-today behavioral effect to
point to. **Fixed anyway** (added `"nc_cchs_deeds"` to `AGE_EXEMPT_SOURCES`)
following the exact precedent already on record for `"cherokee_rod"` in the
same frozenset — a currently-dormant source exempted preemptively so the
retention gap isn't silently reintroduced whenever its separate, already-
documented fetch bug gets fixed. No fetch-mechanism change made (out of this
pass's scope, and this file's own docstring already explains why a rewrite
wasn't safe to ship unverified).

### 10. `counties_nc/nc_ecourts_estates.py` — FLAGGED, NOT fixed — needs a live check
Same NC eCourts family as #1, `LOOKBACK_DAYS = 120` on a date field, and it
captures a status field in its raw block that is not currently read for
retention purposes. Two things stood out that make this different from #1:
its `LOOKBACK_DAYS` constant appears to be dead/unused code (not actually
wired into the live query path as read), and confirming the real behavior
needs clearing this portal's AWS WAF CAPTCHA, which is out of this pass's
plain-httpx-only scope (no CAPTCHA-solving, per this project's standing
policy). **Left as an open follow-up** rather than guessed either way — see
queue below.

---

## UNCLEAR — needs a live check (1)

- **`counties_sc/lexington_probate.py`** — reCAPTCHA-gated detail page; the
  list-level scraper captures a status field that is read nowhere for
  retention, and the parsing selectors read as generic/unconfirmed rather than
  reproduced against a real captured page. Could not be resolved with plain
  httpx. **Left as an open follow-up.**

---

## Prioritized follow-up queue (not done this pass)

1. **`counties_nc/nc_ecourts_estates.py`** — clear the AWS WAF CAPTCHA (a real
   browser session, not plain httpx) to confirm whether its `LOOKBACK_DAYS`
   constant is genuinely dead code and whether its captured status field
   should get the same `nc_ecourts_open_hold()`-style treatment as `nc_ecourts_
   divorce.py` (#1 above) and `nc_ecourts_lis_pendens.py` (Pass 2 item #1).
2. **`counties_sc/lexington_probate.py`** — same CAPTCHA blocker; confirm the
   real selectors against a captured page and decide whether its status field
   is reachable for an `AGE_EXEMPT_SOURCES`/status-aware fix.
3. **`national/seeclickfix.py`** — its measured 1,500-rows/city pagination cap
   could not be live-verified this pass (the API is now Cloudflare-walled to
   plain curl); low priority, current-state-roll shape is already correctly
   un-windowed in the code.
4. **`national/homeharvest.py`** — stale docstring (still says `past_days=30`
   even though that argument was removed 2026-10-08 after a live-verified
   active-listing drop). Cosmetic only; no behavior change needed. A one-line
   comment fix next time this file is touched for something else.

Everything else flagged above (items 1-9 in the FLAGGED section) is fixed; see
each item's own note for the exact `board_persist.py`/`main.py` change.

---

## Tests

New/updated tests, all passing:

- `tests/test_open_case_hold_pass2.py` — updated `test_nc_ecourts_other_source_
  is_not_held` (it used to pin `nc_ecourts_divorce` as an example of an
  *unrelated* source — the exact gap this pass fixed — switched to a genuinely
  unrelated source) and added `test_nc_ecourts_divorce_open_judgment_is_held`,
  `test_nc_ecourts_divorce_dismissed_status_is_not_held`, `test_nc_ecourts_
  divorce_merge_holds_open_and_ages_dismissed` (item #1); added `_PASS3_AGE_
  EXEMPT_FAMILY` plus one membership test and 7 per-source miss-survival tests
  for items #2-9, plus a terminal-check regression test for `cash_buyer_deeds`
  (a REAL recorded date, unlike `nod_discovery`'s old fabricated one, must
  still age out past `TERMINAL_SALE_GRACE_DAYS`).
- `tests/test_liensnc_filing_date_and_aging.py` — updated `test_the_exempt_
  set_is_liensnc_plus_the_rod_nod_family`'s exact-membership pin to include all
  8 new `AGE_EXEMPT_SOURCES` entries.
- `tests/test_dateless_ok_sources.py` — added `counties_nc.nc_rowan_cott` and
  `national.nc_unclaimed` to the required-whitelist guard, plus a direct `_active_
  only()` behavioral test for both.

Full run (every file touched or exercising the changed code): `tests/test_board_
persist.py tests/test_open_case_hold.py tests/test_open_case_hold_pass2.py
tests/test_liensnc_filing_date_and_aging.py tests/test_dateless_ok_sources.py
tests/test_anderson_acpass_deeds.py tests/test_nc_rod.py tests/test_wnc_rod_
foreclosure_starts.py tests/test_nod_discovery.py tests/test_cash_buyer_deeds.py
tests/test_cchs_deed_sweep.py tests/test_nc_rod_logan_sale_date.py tests/
test_run_scoped_scrapers.py tests/test_pre_run15_audit.py` — **220 passed, 0
failed.** (One pre-existing, unrelated failure was found and confirmed
pre-existing on `main` before this pass's changes:
`tests/test_new_sources_2026_10_07.py::test_kit_fetch_drops_sensitive_columns`,
a test fixture out of sync with `_layer_kit.fetch_attrs`'s `max_records`
parameter added by an earlier fix this same session — not touched here, out of
this pass's scope.)

## NEW RAW KEYS TO REGISTER

none — every change this pass was a `frozenset` membership addition in
`board_persist.py`/`main.py` (plus tests); no scraper code was edited, no new
`raw` dict key was introduced anywhere, and `web_artifact.py` was not touched.
