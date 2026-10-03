# Signal-accuracy validation — 2026-10-02

Real, live, auditable validation of 10 distress-signal types against their actual
authoritative sources (county tax/GIS, Register of Deeds, CourtListener, NC voter
file, county jail rosters, SC Public Index). Not sampling-free-text anecdotes —
every number below has a script + raw per-row JSON backing it in this directory.

Run this before editing scoring/matching logic for any of these fields: `scripts/`
has the validator, `results/` has the raw evidence. Scripts assume
`~/foreclosure-scraper/.venv/bin/python3` and import `foreclosure_scraper` from
`src/` via `sys.path.insert`.

---

## 1. `tax_lien` / `two_year_delinquent` / `tax_aging_surfaced` — Buncombe NC

**Script:** `scripts/validate_tax_lien_buncombe.py`
**Evidence:** `results/tax_lien_validation_results.json`
**Sample:** N=60 random of 1,176 Buncombe-NC candidates, 59/60 fetched live.

**Finding A — presence-check inflation hits `tax_lien` directly, not just
divorce/probate/vacancy (the already-known bug class):** only 11.9% have ANY
real unpaid prior-year balance; only 5.1% show true 2+-year delinquency; 5 of
those 7 are under $500 total. ~88% of this signal is a false positive.

**Finding B — new, distinct value bug:** even restricted to the 41 rows where
owner name clearly matches (ruling out a wrong-parcel confound), only 2.4%
land within 10% of real assessed value. Median error 77.6%. Direction is NOT
random: 39/41 overstated, median ratio **1.78x** board-vs-real — a tight,
consistent ratio is the signature of a mechanical bug (double-counted field,
or wrong source field mapped to `assessed_value`), not a stale estimate.
**Action: find what currently populates `assessed_value`/`market_value` for
Buncombe tax-delinquent-sourced rows and diff it against the real figure
exposed at `https://tax.buncombenc.gov/Parcel/Details/{15-digit-pin}` (plain
HTML, no auth — see the script's `OWNER_RE`/`VALUE_RE`/`BILL_RE` regexes,
already tested and working).**

**Finding C — separate from value, 12/53 (22.6%) rows show a COMPLETELY
different current owner than the board lists for that exact parcel** — real
turnover not refreshed, or a parcel-matching defect. Needs its own
investigation; can't disambiguate from this data alone.

---

## 2. `bankruptcy_stay` name-matching — board-wide

**Script:** `scripts/validate_bankruptcy_namematch.py`
**Evidence:** `results/bankruptcy_namematch_results.json`
**Scope:** FULL CENSUS, not a sample — all 234 rows board-wide that carry both
an `owner_name` and a bankruptcy `case` name (out of 5,750 total flagged;
the other ~5,516 are missing one of those two fields, status unknown).

**File to fix:** `src/foreclosure_scraper/enrichment_bankruptcy.py` — this is
the cross-reference step `courtlistener_bankruptcy.py`'s own docstring names
as matching debtor names to existing listing defendants.

**Finding:** using Jaccard token-overlap (penalizes a case name that shares
only one common token with an otherwise-different full name — plain
intersection/min overstates match quality for short owner names, which is
exactly the failure regime): only **56.0%** are a strong real match
(Jaccard ≥0.5). **38.5%** are weak matches — almost certainly the wrong
person (e.g. owner "JONES RAY" matched to real debtor "Billy Ray Jones";
owner "Robert A Jones" matched to real debtor "Robert Curtis Best and
Shannon Marie Jones"). **5.6%** share zero tokens at all.

**Action:** apply `src/foreclosure_scraper/name_normalize.py`'s
`party_middle_verdict()` (already built and used to fix the identical problem
in SC divorce matching) to this cross-reference step — require a middle
name/initial agreement before accepting a match, not just first+last token
overlap.

---

## 3. `code_enforcement` — Henderson County NC (two separate source lanes)

**Script:** `scripts/validate_code_enforcement.py`
**Evidence:** `results/code_enforcement_validation_results.json`
**Sample:** N=60 of 238 Henderson candidates, 60/60 fetched live (96.7% found
a live matching record).

**Real endpoints (no auth, no CAPTCHA, confirmed live):**
- County dashboard: `https://services1.arcgis.com/ZfV5vUaX5QvLLBi9/arcgis/rest/services/OVT_PublicDashboard_View/FeatureServer/1/query`
- Hendersonville's separate vacant-structures register: `.../VACANT_STRUCTURES_7_24_24/FeatureServer/0`

**Finding A — county dashboard lane (49/60 sampled), mis-categorization:**
only 46.9% are genuinely vacancy-adjacent (`Nuisance`, condemnation-type).
**53.1% — the majority — are a different category (dominated by `Zoning`)
riding the same distress flag**, because scoring counts any open case
regardless of `violationType`. 12.2% are already closed/resolved (stale).
**File to fix:** `src/foreclosure_scraper/scrapers/counties_nc/henderson_code_violations.py`
(confirm it preserves `violationType`) and wherever that gets folded into the
distress-score bucket (`distress_score.py` or equivalent) — filter to real
vacancy/condemnation categories only.

**Finding B — Hendersonville vacant-structures lane (11/60 sampled), pure
staleness, not mis-categorization:** only 27.3% still confirmed vacant today.
54.5% now occupied, 18.2% dropped off the register entirely. Needs a
freshness/re-check cadence, not a category filter.

---

## 4. `builder_distress` — Buncombe NC

**Script:** `scripts/validate_builder_distress_v2.py` (v2 is the working one;
v1 kept in this dir for reference/history only)
**Evidence:** `results/builder_distress_validation_results.json`
**Sample:** N=50 of 846 Buncombe candidates, 50/50 successfully queried live
against Buncombe's Register of Deeds (Cott Systems eSearch v4).

**Source of the flag:** `scripts/ingest_liensnc.py:140` — sets
`raw["builder_distress"]` from a cluster/related-filings heuristic over
LiensNC "Appointment of Lien Agent" notices (confirmed by reading the script
directly — line 15's own comment: "Those get a `builder_distress` signal").

**Finding — fully replicated 0%, not just plausible:**
- Genuine mechanic's/contractor's lien or nonpayment claim: **0% (0/50)**
- Routine ROD activity only (deed/deed-of-trust/satisfaction/easement, i.e.
  ordinary property activity, not distress): **72% (36/50)**
- No record at all under that name: **28% (14/50)**
- Across 176 total recorded instruments pulled for these 50 properties, not
  ONE contained the word "LIEN" in any form.

This is the exact same false-positive pattern already confirmed board-wide on
the 56,452-row raw LiensNC pool, now independently confirmed on the
`builder_distress` derived field too, at full replication.

**Action: drop `builder_distress` as currently derived, or redefine it to
require an actual recorded Claim of Lien / mechanic's lien document type —
not an Appointment of Lien Agent notice.** Note:
`normalize_doc_type()` (used somewhere in the `rod/` module — check
`rod/acclaim.py` and any shared ROD doc-type normalizer) currently collapses
"Notice of Appointment of Lien Agent" and "Claim of Lien" into the same
bucket; that collapse needs to be undone for this specific check. The v2
validator script's raw-grid parser (preserves literal "Type" column text
instead of calling `normalize_doc_type()`) is a working reference for how to
read the distinction correctly.

**Reusable code:** the validator reuses `rod/aumentum.py`'s
`AUMENTUM_COUNTIES[("NC","Buncombe")]` session/handshake protocol for
Buncombe's Cott Systems eSearch v4 — same vendor family, live-verified
same-day. `rod/acclaim.py` is a DIFFERENT vendor (Harris AcclaimWeb, Pickens
SC only) — do not conflate the two when reusing ROD-query code elsewhere.

---

## 5. `jail_booking` / `jail_booking_new` — board-wide

**Scripts:** `scripts/collect_candidates.py` + `scripts/validate_live.py`
**Evidence:** `results/jail_validation_results.json`
**Scope:** FULL POPULATION, not a sample — all 322 rows board-wide carrying
`raw['jail_booking']` truthy (0 rows currently carry `jail_booking_new` —
that tier exists in code but is empty on the current board snapshot). 322/322
reachable live across all 10 relevant counties (Zuercher, P2C, Citizen
Connect, Tyler, LANSA vendor families), no CAPTCHA anywhere.

**File:** `src/foreclosure_scraper/scrapers/national/jail_bookings.py` — the
same-county match tier (`match_rosters` per the validating agent's reading of
the file) is bare first+last name matching with zero corroboration BY DESIGN
— the file's own 2026-10-02 docstring notes a newer cross-county tier already
got a disambiguation fix for the identical problem; this older tier didn't.

**Finding:**
- 85.4% (275/322) still genuinely in custody today per live roster.
- 14.6% (47/322) stale — released/transferred, board still says `in_custody`
  (one case flagged in_custody for ~2 years).
- Of 275 current matches, 147 had a middle name available on both sides to
  check: **12.9% (19/147) are a CONFIRMED different real person** — same
  failure mode as the bankruptcy bug (e.g. owner "DAWKINS CHRISTOPHER A" vs.
  live inmate "Christopher **Keith** Dawkins").
- The other 128/275 (46.5%) of current matches can't be identity-checked at
  all — 2 of the 4 major vendors (including Buncombe's P2C) never publish a
  disambiguating field on the public feed.

**Action:** apply `name_normalize.party_middle_verdict()` to the same-county
tier wherever a middle name/initial is available (Zuercher/Citizen
Connect/Tyler/LANSA feeds carry one; P2C doesn't — those stay unverifiable
without a different data source). Also add a live-roster freshness recheck
before trusting `release_status`.

---

## 6. `elderly_disabled` — Buncombe NC

**Script:** `scripts/validate_elderly_disabled_buncombe.py`
**Evidence:** `results/elderly_validation_results.json`
**Sample:** N=50, 50/50 checked both ways (tax + voter status).

**New reusable production code shipped (not scratchpad-only — already in the
real repo):** `src/foreclosure_scraper/enrichment_nc_voter_lookup.py` —
`nc_voter_lookup(first_name, last_name, county="ALL")`. Reverse-engineered
live: `GET /RegLkup/` (antiforgery token + cookie) → `POST /RegLkup` → `GET
/RegLkup/SearchResults?handler=LoadResults` (JSON). **Gotcha documented in
the module:** the server session is sticky — reusing one cookie jar for a
second search silently returns the FIRST search's cached results; the
function opens a fresh client per call to avoid this. Also ships
`split_owner_name()` for this project's "LASTNAME FIRSTNAME" GIS convention
and a full `NC_COUNTY_IDS` map — reusable directly for heir-tracing on any
probate/heir-signal lead, not just elderly ones.

**Finding:**
- 0% (0/50) had any real prior-year tax delinquency — none at all.
- 64% (32/50) confirmed ACTIVE voters with clean taxes — the "ordinary
  stable owner, no real distress" pattern.
- 26% (13/50) had a real corroborating signal: inactive/removed (4) or
  not-found (9, one of which is a name-parse artifact from an "(ETAL)"
  owner string — ~24% genuine).
- 10% (5/50) ambiguous (multiple same-name voter matches).

**Action:** wire `nc_voter_lookup()` into scoring as a corroborating filter
for `elderly_disabled` leads — it already cleanly separates the ~1-in-4
worth pursuing from the ~2-in-3 that aren't.

---

## 7. `divorce` — South Carolina, all 8 core counties

**Evidence:** `results/divorce_validation_results.json` (N=60 sample) +
`results/sc_divorce_full_population.json` (full 5,052-row population dump,
large file — 4.3MB) + `results/sc_divorce_sample.json`
**Scope:** population of 5,052 SC rows with a real-positive `divorce` flag
(using the ALREADY-CORRECTED check — `case_count > 0` or non-empty `cases`,
not bare presence). 60 sampled, 58 live-checkable against SC Public Index
(publicindex.sccourts.org), no CAPTCHA across 58 searches / 8 counties.

**Finding — most severe result of the whole sweep: 0.0% confirmed real.**
57/58 (98.3%) genuine negatives, 1/58 inconclusive (hit the portal's 250-row
display cap on a very common name). Even the board's single
highest-confidence match (exact full name, 32 live records under that name)
had zero in family court.

**Corroborating zero-network check:** re-running the repo's existing
`src/foreclosure_scraper/enrichment_sc_divorce.py`'s `_owner_in_case()`
namesake check against CURRENT board `owner_name` for the full 5,052-row
population (no browser needed) independently flags **177/5,052 (3.5%)** as
locally inconsistent on their face — e.g. a divorce flag sourced from a case
where the board owner shares no surname with either party, or sourced from a
case where the only name match was a divorce ATTORNEY, not a client.

**Action:** this needs more than tightening `_owner_in_case()` — a 0% hit
rate on a strict random sample means the underlying case-to-property
attachment logic itself is likely wrong (wrong case-type filter when
originally harvesting "divorce" cases, or matching on too loose a basis
upstream of `_owner_in_case()`). Find whatever source/enrichment originally
tags a property's `raw.divorce` block and re-verify its case-type filtering
against SC Public Index's real category taxonomy before trusting
`_owner_in_case()` as the fix — the namesake check can only catch
wrong-person matches, not wrong-case-type matches, and this result pattern
(zero real divorces found at all) looks more like the latter.

---

## 8. `lis_pendens` / `foreclosure_sale` — Buncombe NC

**Script:** `scripts/validate_lis_pendens_buncombe.py`
**Evidence:** `results/lis_pendens_validation_results.json`
**Sample:** N=50 of 156 Buncombe candidates (no `sheriff_sale` rows present).

**New reusable code:** a working `httpx` POST client for
`registerofdeeds.buncombenc.gov`'s legacy ASP.NET WebForms search (Cott
Systems eSearch, pre-dates the v4 JSON API used in #4 above). Two real,
non-obvious gotchas documented in the script: (1) the
`ctl00_cphMain_tcMain_ClientState` hidden field's value is
HTML-entity-escaped JSON — POST it unescaped
(`html.unescape()` every hidden field first) or the server throws a generic
error. (2) The two date-filter inputs are watermark-style fields that
literally submit the strings `"From"`/`"Thru"` when untouched — an empty
string also errors. No CAPTCHA token exists anywhere in the form despite
reCAPTCHA v3 being loaded in `<head>` (decorative, not enforced, as of
2026-10-02).

**Finding A — value accuracy:** only 10/50 had a usable 15-digit parcel_id
(38/50 carried SOME parcel_id but in a format `tax.buncombenc.gov` can't
resolve — **separate pipeline gap, worth its own fix**: check
`src/foreclosure_scraper/enrichment_lis_pendens_resolver.py` and whatever
populates `parcel_id` for `nc_ecourts_judgments`-sourced rows). Of the 10
checkable: only 40% within 10% of real value, median error 80.4%, bimodal
(close or wildly off, nothing between). Board overstates in 6/10 — same
direction as the original single-case finding (+76%).

**Finding B — ROD corroboration:** of 33 successfully checked (40/50 had a
human name to search; 7 entity defendants + 3 no-name skipped; 7 of the 40
failed due to garbage defendant strings like an email address, not site
blocking), only **39.4% (13/33) show any real active lien/judgment/notice**.
**60.6% show either a clean benign-history record (exactly the original
Burton pattern) or no record at all.** Split by `listing_type`, worse for
`lis_pendens` specifically: only **22% (2/9) show real corroboration, 78%
don't** — `foreclosure_sale` fares better (46%, 11/24), consistent with
later-stage trustee filings leaving a clearer paper trail than an early civil
lis pendens.

**Finding C — name-collision risk, confirmed near-universal, not a
one-off:** 93.9% (31/33) of checked leads had at least one unrelated
same-surname person show up in ROD results; 87.9% (29/33) had two or more.

**File to fix:** `src/foreclosure_scraper/enrichment_resolve_name_to_property.py`
and the lis-pendens-specific resolver — needs the same disambiguation
treatment (`name_normalize.party_middle_verdict` or address-level
corroboration) already prescribed for bankruptcy and jail above.

**Methodology note worth preserving:** the validating agent caught its own
bug mid-run (a bare single-character first-initial token was over-matching
any first name starting with that letter via a bidirectional substring
check), fixed it by requiring both name tokens to be ≥3 chars before
prefix-matching, and re-ran — only ONE case flipped classification,
confirming the fix was narrow and didn't invalidate the rest of the sample.

---

## Cross-cutting pattern

Four independent validators (bankruptcy #2, jail #5, lis_pendens #8, and the
implicit pattern in the owner-mismatch findings in #1 and #4) all converge on
the SAME root defect: **weak name-matching with no secondary corroboration**
(middle name, address, parcel, or case-type) is responsible for a large
chunk of false-positive signal board-wide. `name_normalize.party_middle_verdict()`
already exists and is already proven (it's what fixed SC divorce's
*namesake*-level false positives, distinct from the case-type problem found
in #7). The highest-leverage single fix across this whole sweep is wiring
that function (or an address/parcel-level equivalent where no middle name
exists) into the matching step of #2, #5, and #8, in that priority order
(bankruptcy and jail have a full/near-full population already validated and
ready to re-score; lis_pendens needs the resolver fix first).
