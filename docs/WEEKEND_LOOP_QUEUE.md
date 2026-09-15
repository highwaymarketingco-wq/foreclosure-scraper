# Weekend loop queue

Durable state for the self-paced loop. **Read this first every iteration.** Update the
status inline as things land, so a context reset never redoes finished work or loses a
finding.

Rules for every iteration:
1. Run `scripts/loop_guard.sh` FIRST. If it prints `WAIT`, do only light work
   (reading, parsing, writing code/tests) and do not start a heavy job.
   Heavy = anything that loads the board (~2GB) or downloads a county.
2. ONE heavy job at a time. The machine is an 8GB Air with ~9GB disk free.
3. Anything that writes the board: dry-run first, read the number, then write.
4. Never claim a source works without a live fetch and a real record quoted.
5. Commit + push after each item. Unpushed work is lost work.

## IN FLIGHT
- [~] parcel cache backfill, all NC + footprint counties — running, 42/100 at 17:10 Fri.
      Fills `owner_mailing` + `sale_price`. Log: `logs/cache_build_all.log`.

## PER-COUNTY GAPS, measured 2026-09-14 on the live 115,991-row board
(this corrected two assumptions — check the table before picking work)

    county            rows   sqft%  value%  parcel%
    Spartanburg,SC  11,302     55%     58%      74%
    Buncombe,NC      6,516     83%     82%      83%
    Rutherford,NC    4,738     93%     90%      88%
    Pickens,SC       3,034     89%     70%      72%
    Oconee,SC        2,894     45%      1%      79%
    Henderson,NC     2,394     68%     68%      69%
    Laurens,SC       2,356     42%      9%      64%
    Cherokee,SC      2,156     53%      1%      67%
    Gaston,NC        1,917     25%     26%      27%
    McDowell,NC      1,772     87%     87%      89%
    Anderson,SC      1,716     72%     23%      21%
    Union,SC         1,183     42%      1%      58%
    Lincoln,NC       1,101     48%     58%      34%
    Cleveland,NC       865     24%     35%      31%
    Burke,NC           657     35%     39%      43%
    Transylvania,NC    443     47%     44%      46%
    Polk,NC            339     57%     59%      60%
    Mitchell,NC        164     75%     76%      76%

TWO CORRECTIONS THIS TABLE FORCED:
  * VALUE is a worse gap than sqft. Oconee, Cherokee and Union sit at 1% value.
    The qPayBill DETAIL page carries Total Appraisal for all three — code written on
    day one and never run for them. Running it now.
  * Buncombe sqft was ASSUMED to be the gap and is 83% (only 194 of 5,433 parcelled rows
    lack it). The Buncombe appraisal layer (98,170 buildings with SqFeet) was verified
    live and NOT wired, because it would serve 194 rows. It also carries MULTIPLE
    buildings per PIN, so a naive join picks an arbitrary one — note that if it is ever
    wired for another purpose.

## QUEUE — sources to build or fix
- [~] BT appraisal cards — PARTIAL, and the remaining blocker is identified.
      39 rows on the board carry a card; 9 gained living_sqft, 33 a sale price.
      Tax-year discovery now resolves 9 of 14 counties (Carteret and Anson are 2026,
      the rest 2027). Still unresolved: Caswell, Duplin, Person, Scotland, Warren.
      THE REAL LIMIT is not the year — it is the ID FORMAT. The portal keys on the
      county's own ACCOUNT id and the board often holds a different identifier for the
      same parcel: Moore 855215723667 (12-digit GIS PIN) returns a stub in every year,
      Moore 00049504 (8-digit account) returns a 20,397-byte PDF. Closing the rest needs
      a parcel->account crosswalk per county, which is its own piece of work.
- [x] BT TaxPayer Portal — DONE as an appraisal-card enricher, 14 VERIFIED counties.
      Gives HEATED SQFT + appraised value + beds/baths + recorded sale price.
      5 proposed tenants were dead stubs; ITSPublicMA was proposed for Martin and
      actually serves PERSON COUNTY — rejected. Still to do: run it over the board.
- [!] Catalis/Sturgis for NC — SAME HOST, now 403-blocking. Do not attempt.
- [!] Catalis Pickens — BLOCKED 2026-09-11, pulled from the runner. DO NOT RETRY without
      a deliberate decision. The host went 429 -> hard 403 even after we paced to 8s,
      dropped to concurrency 1 and honored every Retry-After. It serves `Disallow: /`
      and has now declined in the clearest terms available to it. Evading that is bypass
      behaviour the operator ruled out. COST: Pickens loses its delinquent-tax lane
      (qPayBill does not cover Pickens). MITIGATION: the Pickens PARCEL cache is intact
      and unaffected — 132,782 rows, 132,716 with owner mailing — which was always the
      more valuable half.
- [ ] Spartanburg CAMA: 146,582 parcels with heated sqft, 123,678 with sale price.
      This is the sqft->ARV gap (memory: SF sqft 13%, 38% need it).
- [ ] York SC: 63,288 parcels with recorded sale price AND finished sqft.
- [ ] Column legal-notice API — the nested date filter works; ~104 SC foreclosure-sale
      notices per 120 days currently discarded.
- [ ] NC OneMap statewide: 85 NC counties still have no cache entry beyond the backfill.
- [x] Greer SC code enforcement — EVALUATED AND REJECTED 2026-09-11, do not rebuild.
      The claim (2,035 cases with owner names, 99% populated) is TRUE and the
      operational value is still near zero:
        * the org's only case layers are Q4-2022 and 2023 — there is no 2024/2025/2026
          layer, so this is a one-off historical export, not a live feed
        * 1,429 of 1,743 rows (82%) are COMPLIANT CLOSED — already resolved
        * the genuinely distressed slice is ~200 rows (48 LIEN, 37 CONDEMNATION,
          117 IN PROGRESS, 9 SUMMONS) and all of it is 2+ years stale
      Wiring it would put a dead source in SOURCE_REGISTER that LOOKS live. If Greer
      publishes a current-year layer later, revisit — the schema is good
      (USER_CASE_NO, USER_OWNER_NAME2, USER_SITE_APN, USER_CaseType, USER_STATUS).
- [ ] Kofile/Oconee ROD — JSON API found, 501 instruments per 10 days.
- [ ] AcclaimWeb Pickens — consideration (sale price) is on the DETAIL page, not the grid.

## FINDINGS 2026-09-11 evening — measured on the LIVE board, not assumed

DASHBOARD IS SERVING. First time this was actually checked rather than assumed:
  index.html 200 · listings.json.gz 200, 53,590,857 B — byte-identical to origin/main
  listings_slim.json.gz 200 · run_meta.json 200

THE BIG MISS: the parcel caches were built and NEVER JOINED TO THE BOARD.
  11.5M parcels cached with 10.8M owner mailing addresses, and board mailing is 65%.
  enrich_gis_attrs has not run since the caches were filled. THIS IS THE NEXT ACTION.

BOARD COVERAGE (107,071 rows)
  a NAME 98.5% · street_address 81% · zip 71% · owner MAILING 65% · lat/lng 31%
  parcel_id 49.6% · a VALUE 21.7% · sqft 30.9% · a PHONE 15.2%

IN-FOOTPRINT COUNTIES THAT ARE NOT AT 100% (addr% / mail%)
  Anderson SC    34 / 25      Cherokee SC  48 /  1      Union SC     58 /  3
  Laurens SC     54 / 10      Oconee SC    61 / 33      Pickens SC   70 / 77
  Spartanburg SC 75 / 45      NC counties run 74-96 addr, 64-96 mail (OneMap fed them)

WHY THE SC COUNTIES STARVE — two different causes, both fixable
  NO CACHE AT ALL : Cherokee SC, Union SC (both excluded from the NC OneMap fallback
                    because the county NAME exists in both states), Oconee SC
  CACHE, NO MAIL  : Anderson 208,476 rows / 0 mailing · Spartanburg 364,771 / 0
                    — their configured layers publish no mailing field
  WORKING         : Pickens 132,716 mailing · Laurens 89,272 mailing

OCONEE — half the recorded verdict is stale, corrected here
  parcel_cache.py says arcserver2.oconeesc.com "rejects bulk paginated export" and
  "carries no situs street field". Tested 2026-09-11 against Parcels_OpenData/MapServer/0:
    pagination WORKS (resultOffset=1000 returns rows), 63,432 parcels  -> claim FALSE
    no owner, no mailing, no situs; only TMS_NUMBER, acres, LOTNUMBER, X/Y -> claim TRUE
  Usable for TMS + acreage + LAT/LNG (board lat/lng is 31%), not for contact.

## QUEUE — verification and integrity (the "nothing is broken" half)
- [ ] RUN enrich_gis_attrs over the board to join the 11.5M-parcel cache — biggest win
- [ ] Find owner-mailing layers for Cherokee SC, Union SC, Anderson SC, Spartanburg SC
- [ ] Oconee: cache TMS+acres+lat/lng from Parcels_OpenData (needs a lat/lng column)
- [ ] Re-run the 146-county sweep (221/450 agents cached). LOW concurrency.
- [ ] Mine the remaining 875 county claims — only the top 25 hosts were looked at.
- [ ] Audit every scraper that reports rows but lands 0 on the board (the RAW_KEEP class).
- [ ] Confirm every source in SOURCE_REGISTER.md still returns records; retire dead ones.
- [ ] Check each DATELESS_OK source actually needs it (the junk-row hazard class).
- [ ] Verify no scraper is truncating: budget_exhausted / depth_truncated / lost_prefixes
      must be zero or explained per county.

## DONE (this session)
- [x] SC delinquent roll: 19 counties, 18,503 net-new leads on the board
- [x] Board normalisation 112,887 -> 103,683 (95% of it one source, liensnc)
- [x] dedupe: unit/lot identity + house-number guard — 14,243 properties preserved/run
- [x] Greenville MIE adverts — 770 cases, 768 with judgment debt, $819M
- [x] SC DEW lien registry — 2,879 -> 10,508 leads, browser removed
- [x] NC OneMap — owner mailing + value for 96 NC counties
- [x] parcel cache — owner_mailing + sale_price columns (10 counties had it unmapped)
- [x] Catalis/Pickens source built (429-aware, paced)
- [x] Charlotte code enforcement + orders-to-demolish
- [x] fullmer rank read absentee from two empty keys — 45,450 rows were invisible
- [x] owner_name_signal was at 0 rows while the ranker scored 12 points on it

## STANDING CONSTRAINTS
- FREE only. No paid API, no Apify, no Bright Data, no paid skip-trace.
- robots.txt `Disallow` on an open public-records site: APPROVED by the operator
  2026-09-11. Be gentle — pace, honor 429/Retry-After.
- A WRITTEN ToS prohibition is OUT. publicindex.sccourts.org stays closed.
- Logins, paywalls, CAPTCHA walls, credential entry: OUT.
- Do NOT modify `scripts/scrape_liensnc.py`.
- Greenville is pruned from the FORECLOSURE footprint; it stays in SC DISTRESSED scope.

## 2026-09-13 — dashboard never showed the buy-box rank (FIXED)

`raw.fullmer` was on **0 of 115,994** rows of the slim payload the dashboard
actually fetches, and `fullmer` had **zero** references in `dashboard.js`. It was
in `RAW_KEEP`, so it survived to the full board — but the SLIM payload has its
own allowlist (`_SLIM_RAW` / `_LEAN_RAW`, mirrored, asserted equal by
`tests/test_board_slim.py`) and `fullmer` was in neither. The whole weekend's
ranking work (in-footprint 60+: 397 -> 3,350) reached nothing a phone could see.

Fixed:
- `fullmer: "*"` appended to `_SLIM_RAW` (web_artifact.py) and `_LEAN_RAW`
  (dashboard.js). Whole-block, per the file's own drift rule.
- New sortable **Buy Box** column (`_fullmer`) in the table, mobile sort option,
  colour-banded rank pill whose tooltip prints `why` and `flags`.
- `?v=` bumped to 20260913a (Jekyll/Pages cache).
- Verified: `_project_slim_record` now carries `fullmer.rank` on 500/500 sampled
  rows. **Still needs a board republish for the live file to carry it.**

Note: `grade` is on 107,071 rows and the board is 115,994 — that gap is just the
8,923 rows added since the last publish, not a second allowlist bug.

## 2026-09-13 — parcel cache could not tell NC Cherokee from SC Cherokee (FIXED)

`parcel_cache` keyed its SQLite files on the county NAME only
(`data/parcel_cache/<county>.sqlite`). Cherokee, Union, Lee, Beaufort, Anson and
Chester exist in BOTH states. The queue's next item was "build Cherokee SC and
Union SC caches" — doing that first would have served SC parcels (wrong owner,
wrong situs) to NC Cherokee/Union listings and vice versa, silently.

Caught BEFORE either cache existed, so nothing on the live board was ever
mis-joined (verified: no cherokee/union/lee/beaufort file on disk, and the NC
OneMap county list already excluded all four).

Fixed: `DUAL_STATE_COUNTIES`; `_db_path(county, state)` writes
`cherokee_sc.sqlite` and raises on a dual-state name with no state;
`lookup(county, pid, state)` returns None rather than guessing; connection cache
re-keyed on filename not county; all four call sites now pass `li.state`.
Unambiguous counties keep their bare filename, so the 100 caches on disk stay
warm. Pinned by `tests/test_parcel_cache_state_aware.py`.

NEXT: Cherokee SC / Union SC layer configs must now carry `"state": "SC"`.

## 2026-09-13 — York SC parcel layer wired; there is NO SC statewide layer

Searched the ArcGIS portal for an SC equivalent of NC OneMap. **There isn't one** —
SC RFA publishes only per-county web maps, so SC has to stay county-by-county.
(Do not re-search this; it is a dead end, recorded as such.)

The search did surface York County SC's own open service:
`services1.arcgis.com/2AGLxyiJoNiVHKwq/.../Parcels/FeatureServer/0` —
**134,479 parcels**, open Query, 67 fields, and it carries the OWNER'S MAILING
ADDRESS as fields separate from situs, so it cannot repeat the Spartanburg
situs-was-the-mailing-address bug. Wired as `PARCEL_LAYERS["York"]` with
`"state": "SC"`, mapping owner / situs / mailing / market+tax value / acreage /
sqft / land use / sale price / sale date.

**Honest caveat: the board has ZERO York SC rows**, so this cache serves nothing
today. The real York gap is upstream — no source produces York leads at all. Cache
is ready for when one does; do not count it as coverage yet.

### Two bugs found while wiring it

1. **Epoch-millis sale dates.** York's `DateSold` is an ArcGIS date field = epoch
   MILLISECONDS, and `sale_date` is not in `_NUMERIC`, so it would have been stored
   as the literal string `'1747267200000'`. Added `_iso_date()`. Two fabrication
   traps came out of it, both now pinned: a magnitude floor silently dropped real
   pre-1970 sales (small NEGATIVE epoch), and `0` — ArcGIS's null-date placeholder
   — converted into a confident, wrong `1970-01-01`. Text dates (Anderson's
   `saledatetx`) pass through untouched. `tests/test_parcel_cache_sale_date.py`.

2. **`"McDowell".title() == "Mcdowell"` — STRIKE THREE.** `_NC_COUNTY_NAMES`, the
   NC OneMap eligibility list, held `"Mcdowell"`. The board spells it `"McDowell"`,
   so the membership test in `resolve_layer_cfg` missed it and the statewide
   fallback **never fired for McDowell's 1,772 NC rows**. Corrected the spelling
   AND made county matching case-insensitive (`_nc_name_ci`, `_layer_cfg_ci`) so a
   fourth occurrence of this mistake cannot break anything. Guard test asserts no
   Mc- name in the list looks like `.title()` output; Macon is pinned as the
   don't-corrupt case.

## 2026-09-13 — statewide SC coverage is 32/46 counties (OPEN, measured)

Distressed is supposed to be ALL of SC. Measured against the 46-county list:

- **14 counties with ZERO rows:** Aiken, Bamberg, Chester, Dillon, Dorchester,
  Edgefield, Fairfield, Greenwood, Hampton, Jasper, Kershaw, Lexington, Saluda, York
- **5 effectively empty:** Richland=1, Sumter=1, Berkeley=2, Marion=2, Florence=7.
  Richland is Columbia — the state capital, 400k+ people. One row is a source
  failure, not a real absence. Same for Lexington (Columbia metro) at zero.
- SC total 47,041 rows across 32 counties; NC 68,953 across 100.

This is the concrete statewide-distressed gap and it is UPSTREAM of parcel data —
these counties need a source, not an enricher. Aiken, Lexington, Richland,
Dorchester and Kershaw are the population centres and should go first.

## 2026-09-13 — qPayBill depth ceiling was silently losing rows on EVERY large county

Found by reading the run logs rather than the code. `sweep_county` walks name
prefixes and deepens any prefix that fills its pages. The loop is:

    while frontier and depth <= MAX_PREFIX_DEPTH

so when the frontier is still non-empty at the ceiling those prefixes are assigned
to `frontier` and then **dropped by the condition — never walked**. Every row under
them past the parent's first pages is simply absent from the roll.

Unwalked prefixes per county at depth 4:

| county | unwalked | | county | unwalked |
|---|---|---|---|---|
| Orangeburg | 141 | | Marlboro | 33 |
| Spartanburg | 120 | | Cherokee | 17 |
| Oconee | 44 | | Darlington | 16 |
| Abbeville | 14 | | Clarendon | 7 |

The paired runs prove the missing rows are real, not phantom:

- Spartanburg **10,094** rows at trunc=0 vs **12,256** at trunc=120 — +2,162, and
  still more beyond
- Orangeburg **11,450** vs **14,169** — +2,719

The old log line said "still filling pages at max depth", which reads like a tuning
note, so it was ignored for weeks.

**Fixed:** `MAX_PREFIX_DEPTH` default 4 -> 6, and the warning now says
`ROWS LOST ... the roll for this county is INCOMPLETE`. Depth was the wrong brake:
`REQUEST_BUDGET_PER_COUNTY` already bounds the crawl by requests *and* warns when a
county exhausts it — a limit that reports itself. Pinned by
`tests/test_qpaybill_depth_and_names.py`.

**STILL TO DO: re-run all 19 qPayBill counties at depth 6** to actually recover the
rows. Cherokee/Oconee first (run in flight was depth 4, so it too is short). Expect
a meaningful row gain in Orangeburg and Spartanburg especially. One county group at
a time — the 2-county depth-4 sweep cost ~6,000 queries / 20 min.

### Strike FOUR for `.title()`
`QPAYBILL_SUBS` keyed the county `"Mccormick"`, so every row it produced carried a
misspelled county that `validation.py` then had to repair downstream. Fixed to
`"McCormick"`; a test now asserts **every** qPayBill key equals
`canonical_county()` of itself, so a fifth occurrence fails the suite instead of
shipping. Note this same mistake now has four confirmed sites (BT appraisal-card
lookup, board county values, `_NC_COUNTY_NAMES`, `QPAYBILL_SUBS`) and is patched
ad-hoc as inline `{"Mcdowell": "McDowell", ...}` dicts in four more files —
`canonical_county()` exists precisely for this and those sites should adopt it.

### Confirms the state-aware cache fix was live, not theoretical
Three qPayBill counties — **Cherokee, Lee, Union** — are names that exist in both NC
and SC. Their SC rows would have joined against NC caches of the same name.

## 2026-09-13 08:57 — detail harvest landed; fullmer now LIVE in the payload

qPayBill detail re-run (cap 6000) finished clean: 8,541 of 8,543 rows filled,
`skipped_over_cap=0`, 3,105 of 3,108 parcels carrying a value.

Ingested additive (NOT superseding — it reads fewer parcels than the base roll,
so superseding would drop the difference, same reasoning as detail4):
- 915 existing rows gained fields: **+904 tax_value, +770 legal_description, +53 acreage**
- 0 net-new rows, as expected — these counties were already on the board
- **Oconee tax_value 1% -> 50%, Cherokee 1% -> 51%**
- the house-number guard blocked 7,822 bad fuzzy merges on the way in

`write_artifact` regenerated the slim payload, so **raw.fullmer is now on
115,994 of 115,994 slim rows** (was 0). Slim .gz 14.96 -> 17.16 MB; the shards
shrank in exchange, since a "*" block is skipped there.

Committed and pushed to main (da28bb1). **Pages had NOT rebuilt at first check** —
still serving `?v=20260906a` with zero fullmer refs — so a poll is watching for the
deploy. Do not call this done until the live dashboard.js shows fullmer.

## IN FLIGHT
- depth-6 re-run, Orangeburg + Spartanburg, budget 30,000/county -> `logs/qpb6.log`,
  output `logs/qpaybill_depth6.json`. These are the two worst-hit counties (141 and
  120 unwalked prefixes). Expect a row GAIN; compare against base 14,169 / 12,256.
- Pages deploy poll.

## NEXT
1. Ingest the depth-6 output, measure the recovered rows.
2. Then depth-6 the remaining 17 qPayBill counties, a few at a time.
3. The 14 zero-row SC counties (Aiken, Lexington, Richland, Dorchester, Kershaw
   first) — these need a SOURCE, not an enricher.

## 2026-09-13 09:00 — VERIFIED LIVE on the dashboard, end to end

Pages rebuilt ~80s after the push. Verified at every layer, not just the push:

- live `dashboard.js?v=20260913a`, 6 fullmer refs (was 0)
- live `listings_slim.json.gz` = 17,160,100 bytes, byte-identical to local
- **live payload: 115,994 of 115,994 rows carry `raw.fullmer.rank`** (was 0)
- **3,800 rows at rank >= 60** — the call list, now reachable from a phone
- Buy Box column renders; pills band correctly (fm-hot 81, fm-warm 45/49, fm-cold 37)
- sort works both directions (asc 3,3,3... / desc 100,100,100,92,92...)
- tooltip prints the full reasoning, e.g. rank 100 = "cad_mid +20, tax_lawsuit +20,
  many_owners +14, probate_heirs +16, absentee +8, liquidity_mid +8, margin_strong +15"
- top-ranked rows are real in-footprint leads with addresses (Buncombe, Lincoln)

The rank-100 profile is exactly the Fullmer thesis: named in a tax LAWSUIT, probate
or heirs, absentee, margin covers curative 4x.

## 2026-09-13 09:30 — qPayBill covers 27 SC counties, not 19. EIGHT were missing.

Worked the "14 SC counties with ZERO rows" gap and found the source roster was
short. This was NOT guesswork: Lexington's own property-search SPA links out to
`lexingtoncountytreasurer.qpaybill.com`, which proved the list was incomplete.
Probing every SC county against the vendor's subdomain patterns found eight live
portals we were not reading:

| county | subdomain | board rows before |
|---|---|---|
| **Horry** | horrycountytreasurer | (Myrtle Beach — largest of the find) |
| **Lexington** | lexingtoncountytreasurer | **0** |
| **Kershaw** | kershawcounty | **0** |
| **Bamberg** | bambergcountytreasurer | **0** |
| **Saluda** | saludacountytreasurer | **0** |
| Sumter | sumtercounty | 1 |
| Marion | marioncounty | 2 |
| Colleton | colleton | (had sc_dew only) |

All eight verified to serve the SAME Type4 form this scraper already posts to
(SearchType / ddlCriteriaList / ddlYearList / PaidStatus all present), so they
needed no new parsing code — just the roster entry.

**Hampton is deliberately EXCLUDED.** `hamptontreasurer.qpaybill.com` answers 200,
but the body is an "Object moved / Error" stub with no form. Listing it would
manufacture a county that reports zero rows forever and reads like a scraper bug.
A test pins it out.

**Live smoke test, Lexington:** 839 leads in 44 seconds on a deliberately tiny
120-request budget, carrying parcel/TMS, owner name, situs address and
`balance_owed` (e.g. $8,150.61). A full-budget run will be far larger. The new
loud truncation warning fired correctly during it.

### And it immediately exposed an address bug — 4,327 rows already corrupted
Several of these portals render an absent city and ZIP as literal zero columns, so
situs cells read `128 PHOENIX LN 00000 0000` / `9523 HWY 260 0 0000`. Stored that
way it is not an address: it fails geocoding, it defeats dedupe (two rows for the
same house differ only by padding), and it prints on a call sheet as somewhere
nobody can drive to. Already on the board: **Spartanburg 3,060, Clarendon 928,
Abbeville 214, McCormick 98**, 4,327 total.

`_clean_situs()` now strips it at parse time. Only tokens made ENTIRELY of zeros,
only from the END, so `0 MAIN ST` (vacant parcels really are numbered 0) and
`123 COUNTY ROAD 40` survive. A line that was nothing but padding returns None —
"no address" is the truth, and a blank-looking string is worse, because such a row
is never sent for resolution. Pinned by `tests/test_qpaybill_situs_padding.py`.

`scripts/clean_qpaybill_situs_padding.py` repairs the 4,326 existing rows.
**BLOCKED: board lock held by run_daily_vision.sh — retry.** (The lock worked.)

Note: the first draft of that script ran over EVERY row, and since `_clean_situs`
also strips whitespace it silently proposed edits to ~60 NC rows from other
scrapers whose only issue was surrounding spaces. Scoped to qPayBill rows instead.
Those ~60 whitespace-padded addresses are a real but SEPARATE finding — not fixed here.

## 2026-09-13 10:05 — new-county verification, and what each one actually gives

Smoke-tested the two biggest finds on tiny budgets (heavy slot was busy):

**Lexington** — 839 leads / 44s / 120 requests. Full record: TMS, owner, situs
address, balance owed. Good source.

**Horry** — 583 leads / 100 requests, and 206 leads on just 20 requests. Carries
parcel, owner, balance owed and years delinquent, but **ZERO situs addresses** —
`property_address` is None on 206/206. Verified this is the PORTAL, not our parser:
Horry's results grid simply does not publish the address column that Lexington's
does. So Horry lands as parcel+owner+debt and needs address resolution from Horry
GIS before those leads are routable. Recording it rather than letting Horry look
like an address-coverage regression later.

Worth noting what Horry's roll contains: the first row sampled is **11 years
delinquent (2015-2025)**, $1,072.97 owed. Deep-arrears rows like that are the
strongest distress signal in the whole dataset.

### The other 10 zero-row SC counties — status after probing
- **Aiken** — `aikencountysctax.com` is a Wildfire SPA behind reCAPTCHA (out of
  bounds). Its Delinquent Tax Sale page currently publishes only bidder
  instructions; the property list appears closer to the November sale. NOT a
  missing source — not published yet. Re-check in October.
- **York** — `evolvepublic.yorkcountygov.com` is an open ASP.NET property-CARD
  search (no captcha). That is enrichment, not distress: it cannot generate leads.
  York's real gap stays upstream.
- **Jasper** — `taxes.paystar.io/app/customer/jasper-county-tax` (Paystar vendor,
  new family). Unprobed — next candidate.
- **Greenwood** — county-hosted Tax Collector / Treasurer pages, unprobed.
- **Chester, Dillon, Dorchester, Edgefield, Fairfield, Hampton** — no tax portal
  found from the county homepage. Dorchester and Edgefield 403 plain curl.

CAUTION on method: my link-scraper re-read a stale temp file when a curl failed,
and printed Aiken's links under Chester's heading. Chester actually returned
nothing. Any county above marked "no portal found" should be re-probed with a
per-county file before being called a dead end.

## 2026-09-13 10:35 — re-probe of the "no portal found" counties (correcting my own artifact)

Re-ran the earlier probe with a SEPARATE file per county, because the first pass
re-read a stale temp file on curl failure and attributed Aiken's links to Chester.
Corrected results:

| county | site | tax/treasurer page found |
|---|---|---|
| Dillon | dilloncountysc.org | yes — Assessor + Treasurer |
| Fairfield | fairfieldsc.com | yes — Treasurer |
| Greenwood | greenwoodcounty-sc.gov | yes — Assessor / Tax Collector / Treasurer |
| Hampton | hamptoncountysc.org | yes — **/29/Delinquent-Tax** |
| Chester | both domains fail (000 / 403) | none reachable |
| Dorchester | 403 to curl | none reachable |
| Edgefield | 403, body returned but no tax links | none found |

So Chester/Dorchester/Edgefield are BLOCKED-TO-CURL, which is NOT the same as
"no source" — they need a browser-grade fetch before anyone calls them dead.

### CoreBT / corebtpay.com — a possible SECOND vendor family (UNPROVEN)
Greenwood's tax collector links to `greenwoodco.corebtpay.com` — the BT TaxPayer
Portal family this codebase already knows from NC. Its property-tax page exposes
two search prefixes in its JS validation config:
`ebillSearch_accountNumFld` and **`ebillSearch_fullNameFld` (Full Name)**.

A name search is exactly what makes qPayBill enumerable, so this is worth real
work. **But I have NOT proven it enumerates.** The visible form posts by Map
Number; the name field's markup is not in the page's forms, so the actual request
has to be captured from a browser session. It is also a PAYMENT portal, so it may
return a bill only for an exact known account.

Next heavy slot: drive it in the browser, capture the real POST, and check whether
a one-letter surname returns many rows (enumerable) or demands an exact match
(dead). If it enumerates, probe corebtpay.com subdomains for every SC/NC county the
same way the qPayBill sweep found eight.

Hampton's `/29/Delinquent-Tax` page is also unprobed — and Hampton is the county
whose qPayBill subdomain was a dead stub, so this may be its real route.

## 2026-09-13 10:55 — CORRECTION: the depth fix was right in code, wrong in magnitude

The depth-6 re-run finished. It does not support what I claimed earlier today, so
the earlier entry is corrected here rather than left standing.

Measured, depth 6 vs depth 4 **at the same high budget**:

| county | depth 4 (high budget) | depth 6 | delta |
|---|---|---|---|
| Orangeburg | 6,669 parcels | 6,660 | **-9** |
| Spartanburg | 4,789 parcels | 4,813 | **+24** |

6,872 seconds of runtime against 2,727, for nothing.

**Where my reasoning went wrong.** I cited "Spartanburg 10,094 rows at trunc=0 vs
12,256 at trunc=120" as proof the depth ceiling was costing thousands of rows.
Those two runs differ in **BUDGET**, not depth — the second is literally the
`roll_top5` re-run at a raised request budget. I compared two runs that varied in
two ways and attributed the whole difference to the one I was investigating.

**What is still true:** prefixes left on the frontier at the ceiling really are
dropped and never walked; that code reading holds, and the warning stays. What is
false is that they contain much. Both counties still reported unwalked prefixes at
depth 6 (93 and 68) while parcel counts did not move — the tell that those prefixes
hold DUPLICATES already read under their parents, since the sweep dedupes by parcel.

**The budget is the real lever**, and the evidence was in the same numbers all along:
Orangeburg 5,495 -> 6,669 and Spartanburg 4,069 -> 4,789 came from raising the
budget. Unlike a depth ceiling, `REQUEST_BUDGET_PER_COUNTY` reports when it stops.

Default reverted to 4. Warning reworded to say "raise QPAYBILL_ROLL_BUDGET FIRST".
Test now pins depth == 4 with the measurement in its comment, so the next person
tempted to raise it reads the result before spending two hours on it.

## IN FLIGHT
- **8 new qPayBill counties harvesting** (Horry, Lexington, Kershaw, Sumter, Marion,
  Bamberg, Saluda, Colleton) at depth 4, budget 10,000/county -> `logs/qpb_new8.log`,
  output `logs/qpaybill_new8.json`. Writes only to logs/, not the board.
- board lock still held by run_daily_vision.sh, so BOTH the situs-padding repair and
  the depth-6 ingest remain queued.

## 2026-09-13 11:27 — the board lock is held by the daily vision pass (BOUNDED, not stuck)

Board writes have been blocked since ~09:30 by `run_daily_vision.sh` ->
`patch_vision_gemini.py`. Diagnosed rather than assumed:

- it IS progressing (heartbeat every 60s, log written seconds ago)
- but slowly: **185 scored out of a 4,597 queue in 1h45m**, 761 attempts — a 76%
  miss rate, 143 of them `vision.api_error backend=nvidia:...` with an EMPTY error
  string
- at that rate the queue needs ~40 hours

**I first read that as a 40-hour lock hold. It is not.** `VISION_MAX_SECONDS`
defaults to 14400 (4h) with a hard `asyncio.wait_for` cap, and on timeout the
script keeps partial progress and proceeds to write. Started 09:30 -> **lock
releases ~13:36.** The 40-hour figure was time-to-drain-the-queue, which is a
different number from the job's actual bound. No intervention needed; killing it
would have thrown away the scored work for nothing.

The script's own header documents why this matters: on 2026-08-10 a long hold wrote
back a board loaded 4h earlier and **reverted 1,064 resolved parcels, 343 county
values and 410 absentee tags, with nothing erroring**. Two consequences for today:
1. My 08:57 ingest is SAFE — vision loaded the board at 09:33, after it.
2. The situs repair and depth-6 ingest MUST land after ~13:36, or they would be
   clobbered by that stale snapshot. The lock enforces this for me.

**Separate finding, not chased today:** a 76% vision miss rate with empty-string API
errors on the free NIM backend. `project_vision_pool_repair` says the dead-model
problem was fixed and not to re-diagnose — but errors are clearly still occurring at
volume, so that note may be stale. Worth a look when the board work is done.

Also: the queue contains at least one non-image URL being retried into an image
model — Rutherford's `TR-452 Delinquent Bills Report w Parcel Id.xlsx`, 6 attempts.
A spreadsheet can never be scored by vision; it should never enter the queue. Small,
but it is pure waste and it is the kind of thing that inflates the miss rate.

## 2026-09-13 11:57 — RETRACTION: no spreadsheet is being fed to the vision model

Last entry claimed the vision queue contained a non-image URL (Rutherford's
`TR-452 ... .xlsx`) being retried into an image model. **That is wrong.** The log
field is `source_url=li.source_url` — the LISTING's provenance, printed as a debug
label. The model receives `payloads`, already-fetched image bytes with mime types.
The .xlsx is simply where those Rutherford leads came from. Checked before
"fixing" it; there was nothing to fix.

### The real defect there: the errors were invisible
`error=str(exc)[:160]` produced 143 lines reading `error=` with nothing after it,
because several client libraries raise exceptions whose `__str__` is blank (bare
API errors, timeouts, cancellations). An error line that names no error cannot be
acted on — a 76% miss rate reporting nothing looks like a slow backend rather than
a failing one. That is plausibly why `project_vision_pool_repair`'s "already fixed,
do not re-diagnose" note went unchallenged while errors kept happening at volume.

`_exc_label()` now logs the exception TYPE alongside the message at all 6 vision
log sites, so the next daily pass says what is actually failing.
Pinned by `tests/test_vision_error_label.py`.

This does not fix the miss rate — it makes the next run able to explain it.

## 2026-09-13 12:28 — Paystar (Jasper) probed: auth-gated, DEFERRED

`taxes.paystar.io/app/customer/jasper-county-tax` is a Vite SPA. Pulled its bundle
and mapped the API: the useful routes are
`/api/business-units/{slug}/invoices/search-configurations/{id}/search` and
`/suggest`.

- `/api/business-units/jasper-county-tax` -> **401 "You must be logged in to
  perform this action."**
- `/api/business-units/jasper-county-tax/invoices/search-configurations` -> 400
  "The invoice could not be found" (reachable, but needs a searchConfigurationId
  the SPA obtains at runtime)

Login-gated is out of bounds per the standing constraint. The anonymous public
search may still work with a config id lifted from a browser session, but Jasper
is ~30k people — the cost/benefit against Horry and Lexington already landing is
poor. **Deferred, not dead.** Revisit only if Paystar turns out to host larger
counties; the slug pattern `{county}-county-tax` would make that cheap to test.

### Caveat on my own depth finding
The measurement that depth buys ~nothing was taken on Orangeburg and Spartanburg —
both counties ALREADY harvested several times at high budget. The mechanism
(deeper prefixes re-find parcels already read under a parent) should generalise,
but a county being read for the FIRST time may behave differently. Colleton is
reporting 164 unwalked prefixes in the current run, far more than the others.
If Colleton's final parcel count looks short against its population, re-test depth
there specifically before trusting the generalisation.

## 2026-09-13 13:00 — ingest path prepared while the lock is held

Wired `logs/qpaybill_new8.json` into `scripts/ingest_sc_delinquent_roll.py` as an
**additive** entry (it shares no county with the base roll; superseding would at
best be a no-op and at worst replace a fuller read with a thinner one).

Verified the new counties survive the pipeline before spending a harvest on them:
all eight are in `validation.SC_COUNTIES` (46 entries), so none gets nulled. And a
county OUTSIDE that set is nulled rather than the row dropped, so no lead is lost
either way.

**Ordering trap caught.** The depth-6 harvest ran 08:59-10:54; the situs-padding fix
landed at ~11:01. So that file was produced by the PRE-FIX parser and carried
**3,984 padded addresses** ("461 SIBLEY ST 00000 0000"). Ingesting it first would
have poured freshly-corrupted addresses onto the board.

Cleaned the file itself rather than relying on ingest order — bad data stopped at
the door beats bad data cleaned up afterwards. 3,984 addresses repaired, 0 cleared,
0 padded remaining. Original preserved at `logs/qpaybill_depth6.json.prefix-bak`.

The `new8` harvest started 11:00, after the fix, so its output is clean by
construction.

### Order when the lock frees (~13:36)
1. ingest `qpaybill_depth6.json` (now clean)
2. ingest `qpaybill_new8.json` when the harvest lands (clean by construction)
3. `scripts/clean_qpaybill_situs_padding.py` for the 4,326 rows already on the board
4. verify, commit, push, confirm live on Pages

## 2026-09-13 13:00 — the 8-county harvest landed, and it was 55% FAKE

Harvest finished: **30,563 leads** across 7 counties (Marion returned 0 — see below),
26,000 with addresses. Before ingesting I asked why Colleton had returned **18,289
parcels for a county of ~38,000 people** — about 60% of every parcel it owns.

The unpaid filter had held (all rows "Unpaid" or "Sold at Tax Sale"), so the rows
were real bills. The problem was the tax YEAR:

    years_unpaid across the sweep:  2024: 2,592   2025: 12,929   2026: 18,289

**2026 appeared exactly 18,289 times — Colleton's entire parcel count.** Colleton's
portal had already loaded the 2026 tax year; every other county reported ~0 for it.
SC bills a tax year in the autumn and it falls due 15 JANUARY of the following year,
so in September 2026 a 2026 bill is not late — it is not yet owed. Median balance
$504: an ordinary annual tax bill.

**16,790 Colleton owners would have been put on a distressed-property board for not
paying a bill that was not due**, and Colleton would have become the largest
"distressed" county in the dataset.

Fixed in the scraper: `_delinquent_years()` keeps only tax years the calendar has
passed. A row with BOTH a real arrear and the current year keeps the arrear and
drops the not-yet-due year (1,410 rows); a row with nothing but the current year is
not a lead at all. Conservative at the 1-15 January boundary on purpose: a missed
delinquency costs a lead, a fabricated one costs a call to someone who owes nothing.
Pinned by `tests/test_qpaybill_current_year_not_delinquent.py`.

Re-filtered the harvest file (original at `.prefilter-bak`):

| county | raw | real |
|---|---|---|
| Colleton | 18,289 | **1,499** |
| Sumter | 4,028 | 4,028 |
| Lexington | 2,921 | 2,832 |
| Horry | 2,463 | 2,463 |
| Kershaw | 1,815 | 1,815 |
| Bamberg | 578 | 578 |
| Saluda | 469 | 469 |
| **total** | **30,563** | **13,684** |

13,684 genuine net-new delinquent leads; 16,879 false ones stopped at the door.

**Marion returned 0 rows on 36 queries** — not yet diagnosed. Its portal answered the
form probe earlier, so this is either a stub like Hampton's or a different grid.
Do NOT record Marion as covered until it is checked.

## 2026-09-13 13:30 — Marion diagnosed and REMOVED: a working portal with no data

Marion returned 0 parcels on 36 queries in the harvest. Diagnosed rather than
assumed:

- its page carries the correct Type4 form and the SAME field names as the working
  counties (`ctl00$MainContent$txtCriteriaBox` etc.), so it is not a parser mismatch
- driven through the scraper's own `_walk_prefix`: **0 rows for every prefix** tried
  (SMITH, A, B) while Sumter returned 59 / 88 / 90 on the identical code path
- 0 rows for `radUnpaidButton`, `radPaidButton` AND `radAllButton`
- 0 rows for all four search types: RealEstate, Personal, Vehicle, Watercraft

So marioncounty.qpaybill.com is a fully functional portal that has **no records
loaded at all**. Removed from the roster, same precedent as Hampton: a listed county
that can never produce a row is worse than an absent one, because it reads as a
scraper bug forever and invites someone to "fix" a portal with nothing in it.
Pinned by a test; re-test before re-adding.

**Working qPayBill roster: 26 counties** (was 19 before today; 8 found, Marion
removed on evidence). Honest count, not the headline one.

## 2026-09-13 14:10 — the new leads landed UNRANKED and UNGRADED (caught, fixed)

Board is live at **127,779** (verified against the live payload, not the push:
36 SC counties, all seven new ones present, 1 padded address left on purpose).

But `fullmer.rank` was on exactly **115,994** rows — the pre-ingest total. **Every
one of the 11,785 new leads was on the board and invisible to the call list**:
Sumter 3,084 unranked, Horry 2,463, Lexington 2,214, Kershaw 1,727. Reporting "new
counties live" there would have been true and useless.

`scripts/rank_board_standalone.py` exists for exactly this (ranking otherwise waits
on a 6-10h full run). Ranked all 127,779; row count asserted unchanged.

### And the rank tells us the real gap
Ranked, the new counties are: **max rank 42, median 12, zero at 60+.**
All 13,609 rows carry the flag `no_county_value`, and:

    with tax_value  : 0
    with owner mail : 0
    with address    : 10,240 / 13,609

So the ranking is not broken — its INPUTS are missing. These counties have no
parcel cache, so no assessed value and no mailing address, and without a value the
buy-box arithmetic (margin vs curative cost) cannot score them above D.

Note `grade` is also still on 115,994 — grading needs ARV, which needs value/sqft,
so it is blocked behind the same gap.

**IN FLIGHT:** qPayBill DETAIL pass for the 7 new counties (`QPAYBILL_ROLL_DETAIL=1`,
cap 16,000) -> `logs/qpaybill_new_detail.json`. This is the same pass that took
Oconee and Cherokee from 1% to 50% tax_value. Expect ranks to rise once merged.

### Honest note on my own verification
My Pages poll reported nothing live because it read a `count` key; run_meta uses
`total`. The deploy had been fine for minutes. A verification bug looks exactly
like the failure it is meant to detect — worth remembering.

## 2026-09-13 14:40 — parcel layers for the new counties (the real fix for their D ranks)

The detail pass gives appraised value only. A GIS parcel layer gives value AND the
owner's mailing address AND situs — which is what the new counties actually need.

**Sumter: WIRED.** `gis.sumter-sc.com/.../Sumter_City_County/FeatureServer/7` —
61,684 parcels, open Query, full record: situs `parcel_address_one`, owner, the
MAILING address in separate fields, `market_value_total`, acreage, deed book/page.
Board ids for Sumter are the undashed form, which is exactly `parid` (the dashed
`parcel_number` is indexed too). Unlocks value + absentee for Sumter's 3,084 rows.
Sampled rows are textbook absentees: situs 8415 ST JOHNS RD, owner mails to COLUMBIA.

**Horry: FOUND BUT PARTIAL — do not treat as coverage.**
`services.arcgis.com/NuWFvHYDMVmmxMeM/.../HorryCountySCParcels` is open and carries
PARNO / OWNNAME / PARVAL, but it holds **20,429 parcels against Horry's ~240,000**.
It is hosted by *NCDOT Photogrammetry*, so it is almost certainly a border-strip
extract, not the county. Useful as a partial value source; it is NOT a Horry parcel
layer and must not be logged as one.

**Kershaw: rejected.** `KershawGIS/Parcels_view` carries only FID / PRSNTP_ID /
acreage — no owner, no value, no address. Nothing we need.

**SCDOT statewide parcels: CONFIRMED TOKEN-WALLED.**
`smpesri.scdot.org/.../SC_Parcels/MapServer` has per-county layers (31 = Lexington,
27 = Kershaw) and answers `{"code":499,"message":"Token Required"}`. This REFINES
the earlier "there is no SC statewide parcel layer" note: one exists, it is just not
free. Same conclusion, better reason — and it matches the standing SCDOT wall.

Still needed: Lexington (2,214 rows), Kershaw (1,727), Colleton (1,480), Bamberg,
Saluda parcel sources.

## 2026-09-13 16:00 — Lexington enriched; and I walked into the RAW_KEEP trap myself

**New free source.** Lexington has no parcel layer (maps.lex-co.com is a bare
Apache "It works!" page; SCDOT's statewide parcel service is token-walled), so the
value comes from the county's own `PropSearchAPI`. Most of it needs a
reCAPTCHA-issued Bearer token — out of bounds — but two endpoints answer with NO
token: `/property` and `/assessment`.

**Gotcha worth remembering: the TMS must be UNDASHED.** `004121-01-024` returns
`[]`, which reads as "no such parcel"; `00412101024` returns 22 records. A source
that answers 200-with-empty on a format error looks dead when it is not.

**The assessment ratio is a free owner-occupancy signal.** SC assesses an
owner-occupied legal residence at 4% and everything else at 6%, so
`assessment / fmv` separates a homeowner from a landlord, second-home owner or LLC
with no mailing address needed. Deliberately reported as `owner_occupied` and NOT
as `owner_mailing.absentee`: "not a legal residence" and "mails from elsewhere" are
different claims. Ratios in neither band (ag, manufacturing) return None.

Result: **1,159 values filled, 0 errors, 755 not owner-occupied, 363 owner-occupied.**

### The trap
The first run reported 1,159 enriched — and the board showed **0**. Every block was
silently dropped because `lexington_assessment` was not in `RAW_KEEP`. `tax_value`
survived only because it is a TOP-LEVEL field, so the run looked partly successful,
which is what makes this failure so good at hiding. Same allowlist that dropped 160
scraper keys before; same shape as this morning's `fullmer` bug, which I had
already fixed today.

**Rule now written into the code:** a new raw key needs `RAW_KEEP`, `_SLIM_RAW` AND
`dashboard.js`'s `_LEAN_RAW`, or it does not exist. Mirror test passes.

### Honest limits
- ranks moved modestly: 285 rows D->C, Lexington max rank 59, only 3 at 50+.
  Value alone does not satisfy the buy-box margin test.
- **1,053 of Lexington's 2,214 rows carry an ACCOUNT number, not a TMS**, so about
  half cannot be enriched by this route at all. That is a ceiling, not a bug.

## 2026-09-13 16:30 — FULLNESS AUDIT, and the foreclosure lane is the real gap

Board 127,779. Measured live, not from memory.

**NC vs SC is still the binding constraint:**

|  | rows | addr | owner | value | mail | phone | absentee | counties |
|---|---|---|---|---|---|---|---|---|
| NC | 68,953 | 89% | 94% | 27% | 93% | **82%** | 68% | 100/100 |
| SC | 58,826 | 75% | 80% | 31% | **25%** | **3%** | 16% | 36/46 |

Cherokee SC (0% mail, 0% absentee) and Union SC (3%, 2%) are the worst footprint
counties, and both are blocked on the same thing: no state-specific parcel cache.

**THE LANE GAP.** `foreclosure_sale` is **1,189 rows board-wide, 520 in footprint,
and only 99 with a FUTURE sale date.** Ninety-nine actionable foreclosures is the
entire live pipeline for the fix-and-flip business line. (My first signal query
reported 0 — that was my own wrong enum, `foreclosure` vs `foreclosure_sale`, not a
missing lane. Checked before reporting it.)

Diagnosed why, rather than assuming a bug:
- Column NC "Foreclosure Sale" returns 250 on statewide page 1 over 120 days
- per-county: Burke 44, Gaston 15, Rutherford 8 — but **Buncombe 0, Cleveland 0,
  Henderson 0**
- Burke returns MORE per-county (44) than it shows on statewide page 1 (22), so the
  county filter is working correctly

So the zeroes are real COVERAGE, not a parsing loss: those counties' legal notices
run in papers Column does not carry. Not a bug to fix — a source to add.

Current foreclosure sources: greenville_mie 584 (out of footprint),
foreclosure.com 75, brock_scott 71, hutchens 70, shapiro_ingle 65, column 62.
That is three trustee law firms carrying most of the footprint volume.

**NEXT for this lane:** NC foreclosures run through SUBSTITUTE TRUSTEES, so the
firms are the source. Probed: substitutetrusteeservices.com and goddardfirm.com do
not resolve; trusteeservicesofcarolina.com returns a 114-byte stub;
rogerstownsend.com and sellersayers.com resolve but expose no listing index from
the homepage. Needs a proper per-firm look rather than homepage link-scraping.

## 2026-09-13 17:00 — FORECLOSURE LANE: the trustee gap, enumerated from our own data

Instead of guessing firm domains, mined the `trustee` field on the board. NC
foreclosures run through SUBSTITUTE TRUSTEES, so the firms named in our own
notices ARE the source list. In-footprint volume:

| trustee | rows | scraped? |
|---|---|---|
| Shapiro & Ingle, LLP | 70 | YES (PowerBI) |
| **Bell Carrington Price & Gregg** | **25** | **NO** |
| **Philip A. Glass** | **19** | **NO** |
| **Rogers Townsend** | **16** | **NO** |
| **Wright, Anna Cotten** | **12** | **NO** |
| Brock & Scott | 9 | YES |
| **Riley Pope & Laney, LLC** | **9** | **NO** |
| **Taylor, John W.** | **9** | **NO** |
| **Raubach, Melanie** | **9** | **NO** |
| **Foundation Legal Group** | **6** | NO (Hutchens merger — check dup) |
| **Hayes, Cole** | **6** | **NO** |
| **RAS (Robertson Anschutz Schneid)** | **4** | **NO** |
| Hutchens Law Firm | 3 | YES |
| **Scott & Corley / McCalla** | **3** | **ToS-WALLED, see below** |

**We scrape 3 of ~14 firms.** That is the foreclosure lane's real problem — not a
parser bug, not a wall. It is unbuilt work, and it explains 99 actionable sales.

### McCalla Raymer (foreclosurehotline.net) — ToS WALL, DO NOT SCRAPE
Its written terms say users "may not copy, download, store, publish, transmit,
transfer, sell or otherwise use the data contained in this website, or any portion
of that data, in any form or by any means", may print "for personal use only", and
may not use the data "as a component or as a basis for any material offered for
sale" or to create "mailing or marketing lists". That is precisely our use.
**Out of bounds under the standing written-ToS rule.** Recorded so nobody re-probes
it. Note this removes Scott & Corley's volume from reach permanently.

### Bell Carrington — reachable, needs a browser
`bellcarrington.com/foreclosure-sales/` returned 406 to a plain curl; that was a
USER-AGENT block, not a wall — it serves 77 KB with browser headers. No restrictive
ToS language found. But the listings are JS-rendered: no `<table>`, no `<tr>`, and
the WordPress REST API exposes no custom post type for sales. Needs a rendered
browser session to capture the real data call, same as CoreBT.

### Dead / unreachable hosts
substitutetrusteeservices.com, goddardfirm.com, rtt-law.com, rileypopelaney.com,
nodellglass.com, jwtaylorlaw.com — all fail to resolve. Firm sites move; these need
a name search rather than a guessed domain.

**NEXT (highest value in the repo right now):** work the untapped firms one at a
time with a browser, starting with Bell Carrington (25), Philip A. Glass (19) and
Rogers Townsend (16). Together the unscraped firms represent ~115 in-footprint
notices already visible in our own data — and that is only what leaked through
other sources, so the true volume is higher.

## 2026-09-13 17:30 — Bell Carrington: reachable, but it does not publish the data

Drove `bellcarrington.com/foreclosure-sales/` in a real browser (the earlier 406 was
a user-agent block, not a wall — it serves fine with browser headers, and its text
carries no use restriction, only sale-procedure disclaimers).

The page promises exactly what we want: *"listings of all active foreclosure sales
for the states of Georgia, South Carolina, North Carolina, Alabama, and Tennessee...
updated in real time."*

**But the listings are not there.** Verified four ways rather than assuming:
- network log: 47 requests, ALL static assets — no XHR/fetch data call
- `document.body.innerText` is 2,853 chars, and all of it is disclaimer
- the only iframe is a 1x1 base64 spacer
- WP sitemap + `wp-json/wp/v2/pages?search=foreclosure` return exactly ONE page,
  id 5534, which is the disclaimer page itself

So the "report" the text refers to is not served at any reachable URL. This is a
DEAD END, not a wall to route around — there is nothing to fetch. Re-check later;
a firm that says "updated in real time" probably serves it somewhere, but it is not
on their site today.

### Running tally for the foreclosure lane
- 3 of ~14 in-footprint trustee firms scraped
- McCalla Raymer: **ToS-walled, permanently out**
- Bell Carrington (largest unscraped, 25 rows): **publishes nothing fetchable**
- rtt-law.com, rileypopelaney.com, nodellglass.com, jwtaylorlaw.com,
  substitutetrusteeservices.com, goddardfirm.com: **do not resolve**

That is a harder lane than it looked this morning. The firms that DO publish
machine-readable sales (Shapiro PowerBI, Brock & Scott, Hutchens) are already wired
— which now reads less like neglect and more like "the easy ones were taken".

**Revised next step:** stop guessing firm domains. NC sale notices are published as
NEWSPAPER LEGAL NOTICES by statute, so the complete-by-law route is the papers that
serve the zero-coverage counties (Buncombe, Cleveland, Henderson). Column does not
carry them; identify which paper runs each county's notices and whether it publishes
them online. That is a per-county question with a definite answer, unlike domain
guessing.

## 2026-09-13 19:00 — NC statutory notices: 561 net-new leads, ZERO new actionable sales

Ran the NC press-association county scrape (45-day window, 8 pages). It reached the
counties Column cannot see, which was the whole point:

    Buncombe 180   Gaston 65   Rutherford 52   Burke 33   McDowell 30
    Cleveland 28   Henderson 28

787 notices, 310 typed `foreclosure_sale`. Dedupe found only **5 already on the
board** — these leads were genuinely invisible to us. Board 127,779 -> **128,340**.

### But the actionable count did not move, and that is the headline
    foreclosure_sale total : 1,189 -> 1,338
    in footprint           :   520 ->   620
    FUTURE-dated (usable)  :    99 ->    99   <-- NO CHANGE

Because of what the notices carry:

    with case_number : 225 / 310
    with defendant   : 141 / 310
    with address     :  57 / 310
    with sale_date   :   0 / 310
    with opening_bid :   0 / 310

`_press_assoc.py` says why, and it was known: the full notice body sits behind an
"I Agree" + reCAPTCHA gate, so only the ~300-char PREVIEW is parsed. The preview
carries the caption, case number and party name — **not the sale date, not the bid,
usually not the address.**

So "the foreclosure lane grew 26%" would be a misleading way to report this. The
COUNT grew. The number of foreclosures anyone can actually act on is still 99.

### What these 561 leads ARE good for
A defendant name + an SP case number in a county IS a real pre-foreclosure signal —
it just is not an auction listing. 141 defendant names and 225 case numbers are
resolvable to PROPERTIES via owner-name -> parcel lookup, which is a lane we now
have parcel caches for in 18 counties.

**NEXT: name -> parcel resolution for these defendants.** That converts a name into
an address, an owner and a value, which is what makes them rankable. It is also the
cross-referencing approach that was explicitly asked for, and it is the only route
to the sale details that the captcha gate blocks.

## 2026-09-13 19:50 — name -> parcel resolver: built, MARGINAL, and my first metric was 4x too generous

21,208 board leads carry a party name but no address. The existing resolver cannot
touch them: it reads `owner_name` (these carry the name in `defendant`) and has no
NC endpoints, only five SC layers. But we hold 103 parcel caches and NC owner
coverage is ~100% (Buncombe 398,939/398,939), so the match runs LOCALLY, offline.

Name shape was the trick: parcel layers write owners last-first ("LEWIS NANCY
GAIL"), court notices write parties first-last ("NANCY GAIL LEWIS"). Both reduce to
a sorted TOKEN SET, which is order-free.

### Measured outcome
    no cache for county              9,899
    no owner match                   6,563
    AMBIGUOUS (left alone)           3,386
    name too thin to match             981
    RESOLVED                           379  <- first run
      of which usable address           ~121 across both runs
      of which vacant-land placeholder  ~258

**I reported 344 addresses and 82 landed.** The dry run counted an address by
truthiness, but the cache's address for an heirs-owned vacant parcel is
"0 SHERWOOD PL" — and the board write path strips those (verified: ZERO board rows
carry an address starting "0 "). The pipeline was right; my metric was wrong. The
counter now tests what the pipeline will actually keep.

**Verdict: marginal, keep it.** ~121 usable addresses out of 21,208 names is under
1%. The parcel_ids it does commit are still joinable to value and mailing, so it is
not worthless — but this is not the lever for the 21k unresolved names.

Two safety properties worth keeping regardless:
- a bare surname ("SMITH") returns None — one token identifies nobody
- a name commits ONLY on a UNIQUE county match; the 3,386 ambiguous are refused.
  Committing one would attach a real person's foreclosure to a stranger's house.

### RAW_KEEP, third occurrence today
`name_resolution` was dropped at write exactly like `lexington_assessment` and
`fullmer` before it. Registered. This trap has now cost three separate enrichers in
one day — the rule is documented in the code, but nothing FAILS when a key is
missing, which is why documentation alone keeps not working.

**THE REAL BLOCKER for these 21k names: 9,899 are in counties with no parcel cache
at all.** That is a bigger, more tractable target than tuning the matcher.

## 2026-09-13 20:00 — where the 9,071 cache-less leads actually are

    Horry SC 2,463 | Cherokee SC 857 | Williamsburg SC 831 | Darlington SC 760
    Allendale 518 | Union SC 471 | Marlboro 471 | Barnwell 401 | Clarendon 321
    Charleston 265 | Georgetown 252 | Kershaw 210 | McCormick 209 | Lee NC 206

All but one are SC. This is the same NC/SC asymmetry as phone (82% vs 3%) and
mailing (93% vs 25%) — SC counties simply publish less, and every downstream gap
traces back to it.

### Horry: NO public parcel layer (checked properly, not guessed)
Horry is the biggest single gap — 2,463 cache-less leads and only 41% addresses on
its 4,191 board rows. Probed four county GIS hostnames (all dead) and then listed
its actual ArcGIS org, `services1.arcgis.com/If0JkGr8ABreBTuS`: **114 services, and
not one is a parcel layer with addresses.**
- `DelinquentTaxParcels2025` -> 47 rows, no address field
- `SouthernBoundaryParcels` -> 3 rows, it is boundary CORNERS, not parcels
- the only Horry parcel layer on the portal is the NCDOT 20,429-row border extract
  already recorded as partial

So Horry's addresses are not free via GIS. Its leads keep parcel + owner + debt and
stay unroutable until another route appears. Recorded so this is not re-probed.

### Small real find: Horry Forfeited Land Commission
`DelinquentTaxParcels2025` is the FLC list — 47 properties with `FLC_Bid_Amount`,
owner and description. FLC = failed to sell at tax sale and reverted to the county.
That is genuine, acquirable distress, just a small pool. Not yet ingested.

## 2026-09-13 20:08 — sale dates were sitting in text we already had

The NC notices landed with sale_date EMPTY on 310/310. But the preview often reads
"NOTICE OF FORECLOSURE SALE **Date of Sale: September 15, 2026**" — the date was in
text already on the board, unparsed. Without it a foreclosure is not actionable: it
cannot be sorted by urgency and never reaches the future-dated call list.

**Only the explicit cue is matched.** A notice carries SEVERAL dates — deed of
trust, recording, sale. 103 of 310 previews contain some date; only 45 label one
"Date of Sale". Taking any date would stamp deed dates as auction dates, and
someone would drive to a sale that already happened. The other 58 are reported and
left alone. Verified the parser ignores "Deed of Trust dated March 3, 2019".

Recovered 27 sale dates on the board (8 future-dated). Fewer than the harvest's 45
because dedupe merged 566 of 787 notices — checked that it was NOT truncation:
descriptions are 200 chars in both the file and the board.

### The 200-char cap was the real limiter — raised to 400
`description=text[:200]` while the site's preview is ~300 chars. "Date of Sale"
frequently sits past char 200, which is why only 45 of 310 kept a parseable cue.
The preview is ALL we can get (full body is captcha-gated), so discarding a third
of it was pure loss. Future runs should recover substantially more sale dates.

**Re-run the NC notices scrape to benefit** — this fix only helps new harvests; the
rows already on the board kept their 200-char descriptions.

## 2026-09-13 21:00 — REFUTED: the 200-char cap was NOT the sale-date limiter

I raised `description` 200 -> 400 and predicted "future runs should recover
substantially more sale dates". **Re-scraped and measured. That is false.**

    OLD (200-char): 310 foreclosure_sale | desc median 200 | Date-of-Sale cue 45
    NEW (400-char): 310 foreclosure_sale | desc median 291 | Date-of-Sale cue 45

Descriptions really did get ~91 chars longer. The cue count did not move at all.
The reason: the site's own preview is ~300 chars and ends "... click 'view' to open
the full text". When a notice shows its sale date it does so EARLY, near the
caption. The ones that do not show it never do — the date is deeper in the body,
behind the reCAPTCHA gate. More of a truncated preview is still a truncated preview.

Every parsed field is identical old vs new: street_address 69, case_number 405,
defendant 551, owner_name 551. The only measurable difference is 6 more
street-like strings appearing in the text (46 -> 52), which the parser does not
extract anyway.

**Keeping the 400 cap** — it is harmless, costs nothing, and more source text is
better for any future parser. But it is NOT a fix, and the sale-date ceiling stands
at 45 of 310.

### Two extractable fields sitting unparsed in that text
- `trustee`: **0 of 310** extracted, yet the previews plainly read
  "Trustee: Philip A. Glass" / "Substitute Trustee: ...". This is the exact field
  used to enumerate the firm gap earlier today.
- 6 street-like strings beyond the 69 addresses already parsed.

Neither is large. Logged rather than built, because 6 addresses is not worth a
parser and the trustee field is analytical rather than callable.

**The honest ceiling for this lane remains: 99 actionable foreclosures + 8
recovered = 107.** The rest of the sale dates are behind the captcha gate and no
amount of preview parsing reaches them.

## 2026-09-13 22:50 — qPayBill detail was doing 14x the work it needed (FIXED)

Colleton's re-run at a 40,000 budget still came back with value on only **136 of
1,495 parcels**, and the log said `skipped_over_cap=16895`. The cause is not budget:

`fetch_details` was called once per ROW, and the grid returns a row per unpaid
YEAR. Colleton is **20,895 rows for 1,495 parcels** — about 14 rows each. The detail
page yields the APPRAISED VALUE, which is a property attribute, not a per-year one,
so 13 of every 14 fetches bought a number we already had.

It is worse than plain waste: the pass sorts by arrears descending, and the
highest-arrears rows are exactly the parcels with the MOST duplicate years. So the
budget concentrated itself on a few hundred deeply-delinquent properties and never
reached the rest.

**Fixed:** dedupe by parcel `ident` before applying DETAIL_MAX, keeping the
highest-amount row per parcel so the sort still decides which parcels are reached
when the cap bites. The log now reports `rows=` and `parcels=` separately.

**This likely affected every county detailed today.** Sumter, Horry, Kershaw and
Lexington all returned ~86% value coverage, which looked good enough that I did not
question it — they may have been leaving parcels unreached for the same reason.
Colleton only exposed it because its arrears are deep enough to make the duplication
ratio extreme. Re-detail every county once the fix is confirmed.

## Negative results this tick (recorded so they are not re-probed)
- **No other SC county publishes an FLC layer** on the ArcGIS portal. Horry's was
  only visible inside its own org, so this cannot be found by portal search — it
  needs a per-county org listing.
- **Colleton's org (113 services)** carries only tax parcel BOUNDARIES, labels and
  a 2014 snapshot. No delinquent or FLC list.
- **Sumter's `CodeEnforcement` folder is not violations.** It is a single
  "Enforcement Zone" layer of 5 rows — officer zone boundaries with headshots. Code
  enforcement stays at <1% board-wide; this was not the source.

## 2026-09-14 00:00 — CONFIRMED: detail was competing with not-yet-due bills. 98 -> 1,492

Colleton, same county, three runs:

| run | budget | detail cap | requests used | parcels with value |
|---|---|---|---|---|
| original | 10,000 | 16,000 | capped | **23** |
| higher budget | 40,000 | 4,000 | 4,000 | **136** |
| per-parcel dedupe | 40,000 | 3,000 | 3,000 | **98** |
| **filter-first** | 40,000 | 3,000 | **1,495** | **1,492 (99.8%)** |

`parcels=1495 requested=1495 skipped_over_cap=0`. Half the requests, 15x the result.

**The cause was ORDERING, not budget and not duplication.** The detail pass ran on
RAW grid rows while `_to_listings` had already dropped every parcel whose only unpaid
year is the current one. Colleton is 18,285 raw idents against 1,494 real
delinquents, so ~92% of the budget was spent on bills that are not late yet and get
discarded moments later.

Two wrong diagnoses on the way, both recorded rather than quietly dropped:
1. "raise the budget" — 10k -> 40k moved 23 -> 136. Real but marginal.
2. "the grid returns ~14 rows per parcel, dedupe it" — it returns 1.14
   (20,876 rows / 18,285 idents). That change bought nothing and coverage went
   DOWN. I had inferred the ratio from two numbers taken at DIFFERENT pipeline
   stages — one pre-filter, one post-filter. The instrumentation added in that
   commit is what exposed the error.

Ingested: **1,364 Colleton rows gained tax_value**, 50 gained acreage.

**Re-detailing Sumter, Horry, Kershaw, Lexington, Bamberg and Saluda now.** All
returned ~86% value coverage earlier, which looked good enough that I never
questioned it — they were competing with the same not-yet-due bills and should now
approach 99%.

## 2026-09-14 01:10 — the new drop-reporter's first run: 103 keys, and one real problem

Ran `_report_slim_drops` against the live board. **103 raw keys sit on 100+ rows and
never reach the slim payload.** Most are correctly excluded (images, link_check,
census_rent, hud_fmr — bulky or analytical). Triage of the notable ones:

**`owner_email` — 79,433 blocks, 275 with an actual email (0.3%).**
Not lost contact data: the block is written EMPTY (`emails: []`, `best_email: null`)
on 79,158 rows, each carrying an `extracted_at` timestamp. Excluding it from slim is
correct. But two real issues:
1. 79k empty blocks is pure board bloat — the enricher should not write a block when
   it found nothing.
2. The sampled hit is `fgreene@alaw.net`, `classification: "attorney"`. That is the
   FORECLOSING FIRM's address, not the owner's. An "owner_email" that holds
   opposing counsel is worse than an empty one — anyone reading it as owner contact
   would be emailing the law firm about their own client's house. The
   classification field is there, so the data is honest; the KEY NAME is not.

**Judgment calls, NOT actioned unilaterally** (payload is already 17 MB, and adding
to slim is a size decision that should be deliberate):
- `condition_tier` 30,993 non-empty (e.g. "cosmetic") — a rehab signal a reader
  would want on the card.
- `red_flags` 23,313 — severity/type/description, e.g. eviction_market_high.
- `amount_owed` 33,147 — but it is an ESTIMATE (`source: estimated_tax_2yr,
  confidence: low`); the authoritative balance lives in `qpaybill_roll.balance_owed`,
  which is also not in slim.

This is exactly what the reporter was built for: it turns "something might be
missing" into a list a human can triage in one sitting. Nothing here is being
changed on my own judgment at 1am — recorded for a decision.

## 2026-09-14 01:40 — owner_email's empty block: the marker does not do its job

Looked at `enrichment_email_extract` before calling those 79,158 empty blocks bloat.
They are deliberate — the code says so:

    else:
        # Mark as scanned (empty) so we don't re-scan
        raw["owner_email"] = {"emails": [], "best_email": None, ...}

**But the idempotence guard does not honour the marker:**

    existing = raw.get("owner_email")
    if isinstance(existing, dict) and existing.get("emails"):   # [] is falsy
        ... continue

An empty marker fails `existing.get("emails")`, so the row is re-scanned on every
run anyway. We pay the storage for a marker AND still do the work it was meant to
prevent. One of the two is wrong.

**NOT changing it.** The fix is either "honour the marker" (skip any row already
scanned — but then a row that later gains a source_url or a longer description is
never re-read) or "stop writing the marker" (accept re-scanning, drop 79k blocks).
That is a real trade-off between storage and freshness, and it belongs to whoever
owns the enricher's cadence. I have already twice today changed something on an
inferred premise and had the data refute me — this one gets recorded, not guessed.

Related, and the sharper issue: `owner_email.best_email` on the sampled hit is
`fgreene@alaw.net`, `classification: "attorney"` — the FORECLOSING FIRM. The block
records the classification honestly, so the data is fine; the field NAME is the
problem. Anything reading `owner_email` as owner contact is reading opposing
counsel. `campaign_export.py:146` does exactly that: `email = st.get("owner_email")`.
**That one is worth checking before any email campaign goes out.**

## 2026-09-14 02:55 — the six-county re-detail was largely UNNECESSARY. My call, wrongly made.

Re-detailed Sumter, Horry, Kershaw, Lexington, Bamberg and Saluda on the theory that
their "~86% value coverage" was the same ordering bug that crippled Colleton.
2.5 hours of harvesting. **Result: 13 net-new rows, 52 enriched, 5 tax_values.**

Because they were never at 86%. Board coverage now:

    Sumter    99%   Lexington 99%   Saluda 100%
    Bamberg   99%   Kershaw   95%   Horry     52%

The "86%" I kept quoting was an AVERAGE across a set that included Colleton at ~2%
and Horry at 52%. I attributed a low average to every county in it, then spent the
night acting on that. The five healthy counties had nothing to recover.

**What was actually true:** the ordering bug bit in proportion to how many
not-yet-due bills a county's portal carries. Colleton is 18,285 raw idents against
1,494 real delinquents — 92% waste, hence 23 -> 1,492. The others carry few 2026
bills, so their detail pass was never crowded out. One extreme county is not a
pattern, and I generalised from it without checking the others' raw-to-filtered
ratio first — which is one cheap query.

**Horry's 52% is NOT this bug either.** Its 4,213 board rows exceed the 2,450 parcels
qPayBill exposes; the remainder arrive from sc_dew and other sources with no detail
page to fetch. Its ceiling is source coverage, not budget or ordering.

The fix itself is still correct and worth keeping — it made Colleton possible and it
makes every future detail pass cheaper (requests now equal surviving parcels, and
every county logged `skipped_over_cap=0`). But the re-run was avoidable.

## 2026-09-14 03:55 — SC voter cross-reference: ~3,700 phones available, NOT RUN. Needs a decision.

SC phone coverage is 1,850 of 58,861 (3%) — the worst gap on the board — and 45,708
SC rows have an owner name but no phone. `enrichment_sc_voter_xref` exists to close
it by matching SC owners against the NC voter file. It has produced ZERO rows so far.

**It works. I am not running it.** Measured on a RANDOM 1,500-row sample: 8.1% match
rate, which extrapolates to roughly **3,700 phones**. But the match is FIRST + LAST
NAME ONLY, across state lines, with no middle name and no address:

    owner "ALLISON STEVEN M & PATRICIA A"  ->  NC voter "ALLISON,STEVEN"
    owner "CAIN ELIZABETH M"               ->  NC voter "CAIN,ELIZABETH"
    owner "GIBBS DONNA D"                  ->  NC voter "GIBBS,DONNA"

The enricher's safeguard is that the name must be UNIQUE in the NC voter file. That
is not identity: it means one NC voter has that name, not that the SC owner IS them.

**The geography settles it.** Matches by county: Sumter 14, Lexington 9, Darlington
9, Williamsburg 6 — only 47 of 121 are in NC-border counties. Sumter and Lexington
are the middle of the state. A Sumter owner sharing a name with the single NC voter
of that name is a coincidence, not a lead.

**Consequence of running it:** ~3,700 leads get a stranger's phone number, and
someone dials an uninvolved person in NC about a property in SC they do not own.
Wrong contact data is worse than none — it wastes the caller, harasses a third
party, and the numbers are tagged needs_dnc_scrub but not "needs_identity_check".

**What would make it safe:** require corroboration — an NC mailing address on the SC
row (absentee owners who genuinely live in NC), or a middle initial, or restrict to
border counties where cross-border ownership is ordinary. Border-only would keep
~47 of every 121 matches and drop the implausible majority.

**DECISION NEEDED** — this is a precision/recall trade-off with third-party
consequences, not a technical call. Left unrun.

## 2026-09-14 04:20 — the FLC pattern DOES repeat. Anderson's list found (scanned).

Horry's Forfeited Land Commission list was not a one-off. SC counties are required
to maintain them, and they publish on county SITES, not the ArcGIS portal — which is
why the earlier portal search found nothing. Probing the footprint counties'
delinquent-tax pages directly:

- **Anderson — FOUND:** `andersoncountysc.org/wp-content/uploads/2026/09/2025-FLC-RE.pdf`
  ("FLC RE" = Forfeited Land Commission Real Estate). 3 pages, 201 KB.
  **SCANNED — pypdf extracts 0 characters.** Needs OCR.
- **Cherokee — adjacent find:** `cherokeecountysc.gov/.../TAX-SALE-TAB.pdf` (tax sale
  tabulation — which properties sold and which did not; the unsold ones become FLC)
  plus TAX-SALE-BIDDERS.pdf.
- Pickens: delinquent-tax page exists, no documents linked.
- Spartanburg, Oconee: no delinquent/tax-sale links from the homepage.
- Laurens: site does not resolve (000).

**Why this matters:** FLC properties are not leads to chase — they are inventory the
county will sell, which is the buy-cheap/clear-title line. Horry's 46 had a median
bid of $1,590.

**BUILD-READY, not built.** `enrichment_doc_ocr` is Gemini-first and free, but it is
shaped to enrich an EXISTING lead from its document, not to parse a PDF TABLE into
NEW leads. That is a genuinely different parser (multi-row table extraction +
dedupe against the board), and starting it at 04:20 was not the right call. The URL,
page count and format are all recorded above so it is a clean start.

**Method note for the next person:** the ArcGIS portal search for "Forfeited Land
Commission" returns nothing useful. These live as PDFs on county treasurer pages.
Probe `<county>/delinquent-tax` and `<county>/tax-sale` directly.

## 2026-09-14 04:55 — FLC sweep complete. Two counties publish, the rest do not.

| county | result |
|---|---|
| **Horry** | FLC layer in its ArcGIS org — 46 properties, INGESTED, median bid $1,590 |
| **Anderson** | `2025-FLC-RE.pdf` — 3 pages, SCANNED, needs a table parser. BUILD-READY |
| Cherokee | TAX-SALE-TAB.pdf (tabulation; unsold -> FLC). Adjacent, unparsed |
| Spartanburg | delinquent-tax page reachable, NO documents, no FLC mention |
| Oconee | delinquent-tax page reachable, only unrelated PDFs |
| Pickens | page exists, no documents |
| Laurens, Darlington, Williamsburg | paths 404 / do not resolve |

Two of ~10 counties publish a usable FLC list. That is the honest yield — the
pattern repeats, but not widely, and the ones that do publish mostly do it as
scanned PDFs rather than data.

**This vein is now worked out.** Remaining FLC value needs the PDF table parser
(Anderson, Cherokee), not more probing.

## 2026-09-14 05:25 — the SC phone opportunity was mostly illusory. 32 safe phones taken.

Followed up my own "~3,700 SC phones available, needs a decision" by building the
SAFE subset instead of waiting: require the SC row's OWNER MAILING ADDRESS to be in
NC, so the owner demonstrably lives there and a unique-name match against the NC
voter file is corroboration rather than coincidence.

**The population is 342, not 45,708.** Only 357 SC rows have an NC mailing address at
all. Match rate 9.4% -> **32 phones**. Taken; tagged
`corroboration="nc_mailing_address"` so the basis is auditable.

That reframes the decision I flagged: the ~3,700 figure was almost ENTIRELY the
unsafe majority — SC owners in Sumter, Lexington and Darlington sharing a common
name with the single NC voter of that name. The defensible slice is ~1% of it.

**So there is no large safe SC phone win here.** SC phone coverage stays ~3% and the
constraint is real, not a missing enricher. Anyone revisiting this should know the
ceiling before spending time on it.

The unguarded enricher remains UNRUN and still needs a decision if the recall is
ever judged worth the precision — but it should now be judged against ~3,700
mostly-wrong numbers, not ~3,700 leads.

## 2026-09-14 05:55 — FLC PDF route assessed, NOT built. Reasons recorded.

- OCR is POSSIBLE here: `enrichment_doc_ocr` is Gemini -> GitHub Models -> Groq, and
  **only GROQ_API_KEY has a value** in .env. Gemini/GitHub/NVIDIA are absent, so the
  free-first providers are unavailable and Groq is the only path.
- Anderson `2025-FLC-RE.pdf`: 3 pages, **0 extractable chars** — scanned.
- Cherokee `TAX-SALE-TAB.pdf`: 1 page, **0 extractable chars**, and only 18 KB —
  almost certainly a notice image, not a property table. Low expected payoff.

**Not building it now, deliberately.** It needs PDF->image conversion, a vision call,
table extraction, then dedupe into the board. OCR'd property records feeding a lead
board fail SILENTLY — a mis-read parcel id or owner name looks like data. Today
already produced four silent-loss bugs found only by checking afterwards; adding an
un-verifiable OCR path at 06:00 would be the fifth.

What a clean start needs (all recorded): the two URLs, page counts, the fact that
both are scanned, and that Groq is the only configured provider.

**Cheap source-discovery is now exhausted.** Everything remaining is either a build
(FLC OCR parser), a decision (unguarded SC xref), or a genuine wall (SC parcel data,
trustee firms that do not publish, captcha-gated sale details).

# ============================================================
# START HERE — state at 2026-09-14 07:00, end of the weekend run
# ============================================================

**Board 128,391 rows, live and verified.** Suite 3,935 passed / 0 failed. Tree clean.

    callable (rank 60+, in footprint)   3,715
    with a phone                       58,810
    absentee flagged                   57,010
    with an address                   105,847  (82%)
    SC counties represented                36  (was 32)

## Do these first — they need YOU, not more scraping

1. **DECIDE: the unguarded SC voter cross-reference.** It offers ~3,700 phones and I
   showed they are ~99% name coincidences (matches land in Sumter, Lexington,
   Darlington — the middle of the state, nowhere near NC). The safe 32 with NC
   mailing corroboration are already taken. My recommendation: leave it unrun.
2. **CHECK before any email campaign:** `campaign_export.py:146` reads
   `st.get("owner_email")` directly, and `owner_email.best_email` can be the
   FORECLOSING ATTORNEY (classification field says so; the field NAME does not).
3. **DECIDE: three slim-payload candidates** the drop-reporter surfaced —
   `condition_tier` (30,993), `red_flags` (23,313), `amount_owed` (33,147, an
   ESTIMATE). Adding to a 17 MB payload is a size call, not a technical one.

## Build next, in value order

4. **FLC PDF table parser.** Anderson `2025-FLC-RE.pdf` (3 pages, scanned) and
   Cherokee `TAX-SALE-TAB.pdf` (1 page, 18 KB). ONLY `GROQ_API_KEY` is configured —
   the free-first Gemini/GitHub providers are absent. FLC = county-held inventory
   you can buy; Horry's 46 had a median bid of $1,590.
5. **owner_email**: decide whether to honour its scan marker or stop writing it.
   Today it writes 79,158 EMPTY blocks and re-scans them anyway — the guard tests
   `existing.get("emails")`, which an empty marker fails.
6. **Rank the 13 unranked rows** from the last ingest (not worth a 740 MB rewrite
   alone; fold into the next pass).

## Do NOT re-probe these — verified dead

- **McCalla / foreclosurehotline.net** — written ToS bans copying/marketing use
- **Bell Carrington** — reachable, no restrictive terms, but publishes NO listings
  (47 requests, all static; body is 2,853 chars of disclaimer)
- **SCDOT SC_Parcels** — token-walled (code 499)
- **Horry parcel layer** — 114 services checked, none carry parcels with addresses
- **ncnotices/scpublicnotices** — user decided 2026-09-13 to keep both running
- rtt-law, rileypopelaney, nodellglass, jwtaylorlaw, substitutetrusteeservices,
  goddardfirm — none resolve
- Sumter `CodeEnforcement` — 5 rows of officer ZONE boundaries, not violations

## Method notes worth keeping
- FLC lists are PDFs on county treasurer pages. **ArcGIS portal search does not find
  them.** Probe `<county>/delinquent-tax` and `/tax-sale` directly.
- A new raw key needs `RAW_KEEP` **and** `_SLIM_RAW` **and** dashboard.js's
  `_LEAN_RAW`. Nothing fails when one is missing — that cost four enrichers in a day.
  Every publish now logs the keys slim leaves behind.
- Averages hid two bugs today. Check per-county before generalising.

## 2026-09-14 07:30 — the notice detail gate is TURNSTILE, and it is a click-through ToS. NOT bypassed.

Corrections first: the gate is **Cloudflare Turnstile** (sitekey `0x4AAAAAA...`,
`challenges.cloudflare.com`), NOT reCAPTCHA — `_press_assoc.py`'s docstring and my
own earlier reports both said reCAPTCHA. There is no Google reCAPTCHA script on the
page. Our `enrichment_capsolver` implements only `AntiAwsWafTaskProxyLess` (AWS WAF,
for Tyler/eCourts), so it would need a new task type either way.

CapSolver DOES solve Turnstile and there is a free monthly pool, so cost is not the
blocker. **The agreement text is.** To reach the full notice body you must click:

    "I agree ... that I may not use the content of this site in any database,
     compilation, archive or cache and that I may not engage in any unauthorized
     screen scraping, database scraping, or spidering, or ... any other automated
     means to collect information from the site."

Solving the challenge to pass that gate IS the automated means it prohibits, and
accepting the agreement programmatically means agreeing to it and breaking it in the
same request. This is a stronger case than the site's passive Terms of Use page (on
which the user decided 2026-09-13 to keep reading SEARCH RESULTS) — that decision
does not extend to affirmatively accepting a no-scraping agreement.

**NOT BYPASSED. Do not revisit with a different solver.**

Consequence: full notice bodies (sale date, opening bid, situs) stay out of reach.
The ~107 actionable footprint foreclosures stands, and the 45 notices whose PREVIEW
carried a "Date of Sale" cue are already captured. That is the ceiling for this
source, not a to-do.

## 2026-09-14 07:45 — PROBATE: a working source went dark, and we already own the key that fits it

`counties_sc.sc_probate_net` has **265 rows, all Charleston**, with `first_seen`
stopping at **2026-08-16**. Its own docstring says the site is "NOT bot-walled —
plain httpx with a real-browser UA gets HTTP 200". That is no longer true:

    GET southcarolinaprobate.net/search/  ->  403
    server: awselb/2.0     (AWS Elastic Load Balancer, bare 403, no cf-ray)

**It is AWS WAF.** And `enrichment_capsolver.solve_aws_waf` implements exactly
`AntiAwsWafTaskProxyLess` — built for the Tyler/eCourts wall, the same gate type.
The solver already exists; it needs `CAPSOLVER_API_KEY` staged (the user reports a
free monthly pool).

**This is a different case from the notice-detail Turnstile gate I declined an hour
ago, and the difference matters:** that one required affirmatively clicking an
agreement that says "I may not engage in ... automated means to collect information
from the site". This is a silent technical block with no agreement presented —
the same category as the robots.txt Disallow the user already approved for otherwise
open public records.

**CAVEAT I cannot resolve while blocked:** I could not read the site's Terms of Use,
because the 403 covers every page. Before harvesting post-bypass, load the terms and
check them the way the press-association sites were checked. If they carry a
no-scraping clause, this stops there.

### Why it is worth it
The scraper is already configured for FIVE courts — Charleston, Colleton,
Georgetown, Oconee, Cherokee — and has only ever produced Charleston. Restoring
access should widen it to all five at once. It also sweeps only TEN surnames
("Smith, Johnson, Williams...") as a sample of the index; that list is trivially
expandable once the source is live again.

Probate is 1,953 rows board-wide (1.5%) and the single largest untapped signal.

## Cherokee/Union SC parcel data — CANNOT BUILD (2026-09-14)

Investigated why Cherokee SC sits at 0% absentee / 51% value despite an existing
`assessor_cards/cherokee_sc.py` module. Findings:

- **No free bulk parcel layer exists for Cherokee or Union SC.** Neither county
  hosts an ArcGIS Feature/Map service (confirmed: no `gis.<county>.gov` DNS, no
  `/arcgis/rest/services` on their main domains). Both counties' parcel lookup is
  **qPublic (Schneider Corp / Spatialest)** — a per-parcel search UI, not a bulk
  export. This is a different vendor from the ArcGIS layers every other county in
  this dataset uses, which is why portal search never surfaces it.

- **The existing Cherokee qPublic scraper (`assessor_cards/cherokee_sc.py`) is
  broken and its bypass claim is stale.** Its docstring says curl_cffi TLS
  impersonation defeats the 403 because "the TLS/JA3 fingerprint... not a real
  Cloudflare challenge." Live-tested 2026-09-14 on 3 real Cherokee parcel_ids from
  the board: curl_cffi → 403, httpx → 403, and the stealth-render fallback (which
  is supposed to solve exactly this) returns a genuine Cloudflare **"Just a
  moment..." interstitial page**, not the card. qPublic/Schneider has evidently
  hardened its edge since that module was written. Result: `fetch()` returns
  `None` for every parcel, silently — it's wired via auto-discovery and running
  on every daily pass, and has been contributing nothing.

- **Union SC has no equivalent module at all** — no `assessor_cards/union_sc.py`,
  and no bulk source found on searching.

**This is a real "cannot," not a "didn't try":**
1. No free bulk parcel data for either county — confirmed by direct probing of
   likely GIS hosts and the county sites' own GIS-mapping pages.
2. The one existing per-parcel scraper is blocked by a live Cloudflare challenge
   our stealth-render path does not solve.
3. Building a Union SC scraper would hit the same wall Cherokee already hits.

Getting past this needs either (a) a Cloudflare-challenge solver we don't have
wired for qPublic specifically, or (b) accepting per-parcel scraping at whatever
rate a browser-automation approach can sustain against an active bot wall — both
outside today's scope. Flagging rather than leaving Cherokee/Union silently at 0%.

## York County SC — first-ever lead source built (2026-09-14)

York was a zero-row county (its only entry, `york_delinquent_tax`, is gated to
Oct-Jan and had nothing off-season). Found and built its Overage Claim List:
when a delinquent parcel sells at tax auction for more than the taxes owed, the
county owes the surplus back to the FORMER owner — a live-maintained PDF
(`**UPDATED 8/11/26**`), text-extractable, 119 usable claims / $1.26M total
across 4 tax-sale years (2021-2024).

Built:
- New `ListingType.TAX_SALE_OVERAGE` (models.py) — this lead shape doesn't fit
  any existing type: the property is already GONE, the "lead" is a person owed
  money, not an acquisition target.
- `counties_sc.york_overage_claims` — strict NAME/MAP#/$AMOUNT state-machine
  parser (validates every line's shape, never assumes position), situs pulled
  from a freshly-built York parcel cache (134,479 parcels) for context only.
- **Real bug caught before it shipped**: the parcel cache's owner/mailing
  fields describe whoever owns the property NOW (verified live — claimant
  ANDREWS MINERVA W ETAL's old parcel 070-09-01-017 is now owned by TORRES
  JUAN C GARCIA). Four generic enrichers resolve owner/mailing FROM a
  parcel/address with "fill if blank" logic and would have silently attached
  the current owner's mailing address under the claimant's name:
  `join_parcel_cache_to_board.py`, `enrichment_gis_attrs.py`,
  `enrichment_owner_mailing.py`, `enrichment_arcgis.py`. All four now skip
  `TAX_SALE_OVERAGE` rows entirely. `sc_parcel_mailing`/`parcel_resolver.py`
  is scoped to 5 counties, none of which is York — not a live risk today, but
  flagged here as a watch item if a future overage-claim source targets
  Spartanburg/Oconee/Anderson/Laurens/Union.
- 10 parser tests (`test_york_overage_claims.py`), including the section-
  boundary and blank-line cases actually present in the real PDF, and a
  malformed-row recovery case (a broken record must not smear into its
  neighbor's data).

Verified live 2026-09-14 ~16:43: 119 `counties_sc.york_overage_claims` rows on
the published board, `raw.tax_sale_overage` intact, no owner_mailing /
market_value / tax_value leakage onto any row. Board: 128,391 → 128,510.

**Next**: apply the same "find a live document/API, verify it's current, parse
strictly, cross-reference the parcel cache for context only, guard against
wrong-person contamination" method to the remaining zero-row SC counties —
Aiken, Chester, Dillon, Dorchester, Edgefield, Fairfield, Greenwood, Hampton,
Jasper — and the thin ones (Berkeley 2, Florence 7, Marion 2, Richland 1).

## Chester County SC — investigated, deferred (2026-09-14)

Next zero-row county in the sweep. Findings:

- The existing `chester_delinquent_tax.py` scraper targets a dead URL — the
  county site was restructured (same class of break as York's delinquent-tax
  scraper before today's fix): `chestercountysc.gov/treasurer/delinquent-tax-sale`
  now serves the homepage. Live content moved to
  `chestercountysc.gov/departments/tax-and-finance-departments/{tax-collector,
  treasurer}/` — both checked, both are prose-only "what this office does"
  pages with NO parcel list, PDF, or DocumentCenter link (unlike York).
- The county's `boards/tax-and-assessment/forfeited-land-commission` page is
  likewise prose-only, no document — Chester was already correctly excluded
  from `sc_flc.py`'s curated list, not an oversight.
- The REAL tax roll lives on a separate domain, `chestercountysctax.com` — a
  legacy AngularJS 1.x SPA (angular-ui-bootstrap), same shape as the DEW Lien
  Registry SPA this session already solved by calling the app's own fetch()
  from inside the rendered page. Confirmed live: plain httpx/curl-impersonation
  gets an empty loader shell; StealthyFetcher with network_idle + a
  page_action that waits for networkidle renders real Angular CSS but no data
  grid yet — the search form needs interaction (a county/parcel/name query)
  before the backend call fires, and that backend endpoint hasn't been found.

**Deferred, not abandoned**: this needs the same treatment DEW got (find the
in-page JS call the search form fires, replicate it via page.evaluate()) but
is a standalone investigation, not a quick win — moving on to the rest of the
zero-row sweep and will return to this if time allows.

Remaining zero-row SC counties to check: Aiken, Dillon, Dorchester, Edgefield,
Greenwood, Hampton, Jasper.

## SC mailing/phone gap — root-caused (2026-09-14)

User asked for the precise county x source x signal picture and a 100% plan.
Ran a live audit against the board (128,510 rows) rather than relying on
memory. Real numbers:

    NC: 69,530 rows — address 88.8% / owner 94.1% / mailing 92.6% / phone 81.9%
    SC: 58,980 rows — address 75.0% / owner 95.8% / mailing 29.6% / phone  3.2%

SC mailing is THE binding constraint, and it is NOT spread evenly — most of it
is concentrated in ~20 counties with thousands of real board rows sitting at
literal 0.0% mailing: Charleston 4,843, Horry 4,213, Darlington 2,689,
Williamsburg 2,391, Lexington 2,214, Kershaw 1,727, Clarendon 1,272,
Marlboro 1,061, Lancaster 911, Barnwell 886, Newberry 719, Chesterfield 687,
Abbeville 632, Allendale 590, Greenville 584, Calhoun 512, Lee 504, Bamberg
486, Saluda 428, McCormick 311, Orangeburg 107. (Only 11 of SC's 46 counties
have a local parcel_cache built at all: Anderson, Cherokee, Colleton, Laurens,
Oconee, Pickens, Spartanburg, Sumter, Union, York, + Beaufort partially.)

Diagnosed why, with live probes, not guessing:

1. **SCDOT (`smpesri.scdot.org/.../SC_Parcels`) — confirmed DEAD, not
   recoverable free.** Designed as the statewide owner+mailing+value fallback
   for all 46 SC counties, keyed by TMS. Live-probed 2026-09-14: every query
   returns HTTP 200 + `{"error":{"code":499,"message":"Token Required"}}`, and
   the service isn't even listed in its own `/GISMapping` folder catalog
   anymore — a deliberate lock, not a glitch. Already known-walled since
   2026-08-12 (see `tests/test_scdot_breaker.py`) after it dragged a run to
   16 hours; three enrichers were patched to short-circuit on it that day.

2. **`enrichment_owner_mailing.py` — the actual mailing enricher — was NEVER
   one of the three patched modules.** Its own ArcGIS query function
   (`_query_page`) treated an error body as an empty result set (`{"error":
   ...}` has no `"features"` key, so `.get("features") or []` silently became
   `[]`), so it kept spending a full request per SC lead against the dead
   SCDOT host with zero data gained and zero log line, for over a month,
   regardless of what any other module's breaker state was. **Fixed**: it now
   detects the ArcGIS error shape and trips the shared breaker itself.

3. **Charleston (4,843 rows) and Beaufort (875 rows) have their OWN free,
   live ArcGIS parcel layers — confirmed working, confirmed NO mailing field
   exists on either.** Charleston's public FeatureServer schema (queried
   live): `OBJECTID, PID, OWNER, ADDR, Lot_Blk, SUBD, WServiceArea,
   SServiceArea, Shape__Area, Shape__Length` — no mailing column, full stop.
   Separately, the code's waterfall (`res is None` gate) meant that once
   EITHER county's dedicated layer resolved owner+situs, the SCDOT-mailing
   fallback was never even attempted — so these two counties could never have
   gotten mailing through this code path even while SCDOT was still alive.
   **Fixed**: added a mailing-only supplement step (same pattern as the
   existing NC-OneMap value-supplement), inert until SCDOT (or a future
   statewide replacement) is reachable again.

4. **Went looking for a free alternative to dead SCDOT — found one, then it
   died too.** ArcGIS Online hosts a complete, uniformly-named 46-item series
   "Parcels - SC - <County> County" from publisher account `GDITAdmin` —
   every single SC county, one consistent schema, exactly the shortcut that
   would have turned 20 one-off county investigations into one. Queried it
   live: `{"error":{"code":403,"message":"Subscription is canceled, the item
   is not accessible"}}` on every item. The publisher's ArcGIS Online org
   subscription has lapsed — a dead end on THEIR end, not a token/paywall we
   could work around. Noting this explicitly so nobody re-discovers it and
   burns time re-verifying the same dead lead.

5. **SC phone (3.2%) is a different, already-near-ceiling problem, not a
   mailing side-effect.** It comes entirely from `enrichment_sc_voter_xref.py`
   cross-referencing SC owner NAMES against the free NC voter file (unambiguous
   name matches only) — SC has no free bulk voter file with phones at all
   (confirmed prior session). This is name-dependent (SC owner-name coverage
   is already 95.8%), not address/mailing-dependent, so fixing mailing does
   NOT cascade into phone. 3.2% is close to the real free-tier ceiling for SC
   phone; the only way past it is a paid source (already costed in
   `docs/path_to_100.md`).

**What's left, in priority order**:
- Build free per-county parcel caches (the proven York/11-county pattern) for
  the ~20 real-row, 0%-mailing counties, one county at a time — genuinely
  bespoke work, no shortcut found today. Prioritize by row count: Horry,
  Darlington, Williamsburg, Lexington, Kershaw, Clarendon next.
- Continue the zero-row-county sweep (Aiken, Dillon, Dorchester, Edgefield,
  Fairfield, Greenwood, Hampton, Jasper — Chester deferred, needs SPA reverse
  engineering) — a SEPARATE problem from the mailing gap (no leads exist yet
  at all, vs. leads exist but can't be mailed).
- SC phone stays capped near 3.2% on free sources; no further free lever
  found today beyond the existing NC-voter name cross-reference.

## Per-county SC mailing cache build-out — iteration 1 (2026-09-14)

Continuing the priority list from the SCDOT root-cause audit above. Each
county below: found via live probing (ArcGIS Online item search, county
website JS bundles, or the county's own GIS account catalog — SCDOT and the
dead GDITAdmin statewide series are NOT viable, see above), verified schema
+ sample match against real board parcel_ids BEFORE wiring, built with the
existing completeness-gated `refresh_county()`, joined board-wide via
`join_parcel_cache_to_board.py` (fills-only), then mailing % measured before
AND after the write plus a York-overage-rows-still-clean check every time.

**Done, verified, live**:
- **Horry** (4,213 rows) — own MapServer at `horrycountysc.gov/parcelapp/`
  (layer 24, 301,323 parcels), found via the rezonings GIS app's JS bundle.
  No situs field on this layer at all (owner+mailing+value only). Board
  parcel_id = legacy PIN, matched via the layer's PINtext field.
  **Mailing: 0.0% -> 35.3%** (1,486/4,213 — the rest have no parcel_id,
  mostly `sc_dew_lien_registry` which is address-only, a separate follow-up).
- **Darlington** (2,689 rows) — own FeatureServer, found via its "Parcel
  Viewer" Web Map's operationalLayers (not exposed on the Web Map item
  itself). Zip_Code deliberately excluded (malformed ZIP*10000+ZIP4 integer,
  no transform hook in this module — see the code comment).
  **Mailing: 0.0% -> 69.7%** (1,875/2,689).
- **Lexington** (2,214 rows) — own rich CAMA MapServer via the county's
  ArcGIS Online account ("lexcogis"), a plain Map Service this time (not
  buried in a Web Map config). Carries split mailing/situs, sqft, sale
  price/date, both market and taxable value — the richest layer found all
  session. **Mailing: 0.0% -> 51.7%** (1,144/2,214).

Combined board-wide join also picked up 1,795 new absentee flags and 1,134
last-sale records as a side effect (Lexington's rich schema feeding fields
Horry's couldn't). Every write verified: row count unchanged (128,510),
York's 119 TAX_SALE_OVERAGE rows still carry zero mailing after all three
writes (the wrong-person guard holds under repeated real board-wide joins).

**Investigated this iteration, not yet resolved** (honest status, not silent
skips):
- **Kershaw** (1,727 rows) — the only AGOL item found is a bare 4-field
  geometry-only boundary layer (`FID, PRSNTP_ID, taxTotalAc, GlobalID` — no
  owner/mailing/value at all). The county's own site (`kershaw.sc.gov`)
  timed out on every fetch attempt (30s, no bytes). No usable layer found
  yet.
- **Clarendon** (1,272 rows) — checked its Assessor page directly: it links
  straight to `qpublic.net/sc/clarendon` (Schneider Corp) — the SAME
  Cloudflare-walled vendor already confirmed blocking Cherokee/Union SC
  parcel data earlier this session. Not a new investigation; joins that
  CapSolver-gated list (blocked purely on `CAPSOLVER_API_KEY` being staged).
- **Williamsburg** (2,391 rows) — DOES have its own live GIS host
  (`williamsburgsc.wthgis.com`), but it runs a proprietary "TGIS" engine
  (`tgisServer2.js`, `.ashx` handlers like `tgis/search.ashx?S=`), not
  standard ArcGIS REST. A real, different integration (protocol reverse-
  engineering), not a quick win — deferred, same class of work as Chester's
  AngularJS SPA.

**Next in priority order** (by row count, from the original audit):
Clarendon (retry — check the Assessor page directly), Marlboro (1,061),
Lancaster (911), Barnwell (886), Newberry (719), Chesterfield (687),
Abbeville (632), Allendale (590), Greenville (584), Calhoun (512), Lee (504),
Bamberg (486), Saluda (428), McCormick (311), Orangeburg (107). Then back to
Kershaw/Williamsburg/Chester with more time budgeted for their non-standard
backends. Then the zero-row county sweep (Aiken, Dillon, Dorchester,
Edgefield, Fairfield, Greenwood, Hampton, Jasper).

## Per-county SC mailing cache build-out — iteration 2, mostly negative results (2026-09-14)

Continued down the priority list. This pass found NO new wireable mailing
source (unlike iteration 1's 4-for-4), but every negative result below is a
confirmed live finding, not a skip — worth keeping so nobody re-burns time
re-checking the same dead ends.

- **Marlboro, Barnwell** (1,061 / 886 rows) — only the dead GDITAdmin item
  exists on ArcGIS Online for either. No independent county-hosted layer
  found.
- **Newberry** (719 rows) — found "Newberry County, SC (CAMA Integration)"
  and a sibling "Laurens County, SC (CAMA Integration)" under a GIS
  contractor account (BPBarberGIS), but both point to a bare IP
  (`http://68.156.95.35/newberrygis/...`) tagged `typeKeywords: ["Flex"]` —
  an Adobe Flex app, a technology dead since ~2020. Genuinely unreachable,
  not a bypass problem.
- **Chesterfield** (687 rows) — has a live "CivicPlusLayers" FeatureServer,
  but its only parcel layer is "City Parcels" (layer 3) — the small city of
  Chesterfield, not the county. Would help few if any of the 687 county rows.
- **Abbeville, Bamberg, Saluda, McCormick** (632/486/428/311 rows) — zero
  relevant ArcGIS Online hits of any kind (dead GDITAdmin item only, or not
  even that).
- **Greenville** (584 rows, SC's largest county by population) — has its own
  GIS domain (`gcgis.org`) with a live ArcGIS REST catalog, but the only
  publicly listed service is a geocoder (`GVL_COMPOSITE_LOC`) — no parcels
  service exposed at the root. Its property-tax page doesn't link a GIS
  vendor either. Needs deeper digging (a hidden folder, or a separate
  assessor portal) — not ruled out, just not found in a first pass.
- **Calhoun, Lee** (512/504 rows) — AGOL search returns only noise (Florida
  statewide parcels, Palm Beach County FL layers matching on generic terms).
  No SC-specific hit.
- **Orangeburg** (107 rows) — DID find a real, rich layer
  (`Main_Public_Tax_Parcel_Map_WFL1`, 62,519 parcels, owner1/parcel_id/
  own_street/own_city/own_state/own_zip) via its own GIS account. NOT wired
  yet: checked first and **zero of Orangeburg's 107 board rows carry a
  parcel_id at all** (all address-only), so a parcel-id-keyed join would
  recover nothing today regardless of cache quality. Worth revisiting once
  an address-based resolver exists (the fuzzy address->parcel resolver from
  earlier this session, or a similar pass against this specific layer's
  own_street/situs-adjacent fields).

**Zero-row county sweep, resumed** — Aiken, Dillon, Dorchester checked:
- **Aiken**: DOES have a dedicated "Tax Collector Overage Claims" page,
  unlike most — but unlike York, it is NOT a public list. It's a reCAPTCHA +
  click-through-disclaimer gated CLAIM FORM ("you must agree to the
  following... to access Overage Claim Forms"). The disclaimer itself is a
  plain liability waiver (not a scraping prohibition like notices.com's), so
  it isn't a ToS wall — but getting past the reCAPTCHA needs CapSolver
  (still blocked on the unstaged key), AND even then this looks like an
  intake form for filing a claim, not a roster of names/amounts to build
  leads from. Real uncertainty here about whether a public list exists at
  all; not pursued further without the CapSolver key to even test past the
  gate.
- **Dillon**: has a Tax Assessor "Documents" library (Revize CMS document
  center) but only generic exemption/appeal forms surfaced in a static-HTML
  pass; the Treasurer page's document center loads via a JS widget this pass
  didn't render. Not ruled out — needs a browser-rendered pass, not just
  `get_text`.
- **Dorchester**: checked its delinquent-tax page directly — no mention of
  "overage," "surplus," or "excess" anywhere on it, no linked document. No
  overage-claims source found (may simply not publish one).

**Next**: Greenville (deeper GIS-catalog dig), Dillon (browser-rendered
document center), then Edgefield/Fairfield/Hampton/Jasper (zero-row,
unstarted) and Chester/Kershaw/Williamsburg (deferred, non-standard
backends).

## Greenville County SC — new delinquent-tax source, 584 -> 2,871 rows (2026-09-14)

While hunting Greenville's GIS layer for the mailing-gap audit (Greenville's
own `gcgis.org` only exposes a geocoder publicly, no parcels service — still
open), its property-tax page's disclaimer gate led to
`greenvillecounty.org/appsAS400/Taxsale/` — an "AS/400" path that sounded
like a legacy mainframe wall but is actually a plain, clean, uniform HTML
table: `Item # | Map # | Name | Amount Due`, 2,338 rows, no existing scraper
covered it at all (SC's LARGEST county had only 584 rows on the whole
board). Built `counties_sc.greenville_delinquent_tax`.

**Two real bugs caught and fixed before/immediately after shipping** (this
is exactly the kind of thing "double-check your work" is for):

1. **Parcel-format bug**: Greenville's Map# is usually 13 digits, but 383 of
   2,112 real-estate rows use an alpha-prefixed condo/mobile-home-park code
   (e.g. `WG02060100500`). A first-draft digits-only regex silently
   reclassified all 383 as parcel-less "personal property" rows. Caught by
   inspecting a specific duplicate-amount cluster (BBJ EQUITIES FL LLC, 12
   parcels) instead of trusting the aggregate counts. Fixed: any non-empty
   Map# is a parcel, since blank-vs-populated is the table's only real
   signal (verified: exactly 226 truly blank, 1,729 pure-digit, 383
   alpha-prefixed, zero of any other shape).
2. **Dedupe self-collision bug**: the 226 genuine personal-property/vehicle
   rows have no parcel_id AND no street_address, so `Listing.dedupe_key()`
   fell through to `url:{source_url}` — and all 226 share the SAME
   source_url (one page for the whole county), which would have collapsed
   them into a SINGLE board row on ingest. Fixed by setting `case_number =
   Item#` (unique per row in the county's own table) on every row, which
   dedupe_key() checks before the source_url fallback.

**A third bug found in a SHARED module, not just this scraper**: ingesting
via the standard `dedupe()` merge (correct here — unlike York's
TAX_SALE_OVERAGE, a Greenville parcel already on the board from
`greenville_mie_adverts` matching this new list is the SAME property/person
seen from a second angle, a corroboration signal, not a wrong-person
hazard) surfaced that `enrichment_tax_owed.py`'s generic Pass B gated on the
MERGED row's primary `source` name looking tax-ish -- but `merge()` keeps
the bucket-holder's original source (the foreclosure lead), so a real
`raw["greenville_delinquent_tax"]["total_due"]` sitting right there in
`raw` was invisible to the normalizer. Fixed: the gate now also checks each
raw sub-block's own NAME for a tax-ish substring, a strict superset of the
old behavior. Re-running the normalizer board-wide picked up 1,448
additional rows beyond Greenville alone — a real, pre-existing gap this
incidentally closed everywhere a tax record has ever merged into a
differently-named lead.

**Performance note for future large ingests**: a full `dedupe(board +
new_rows)` over the ~130K-row board hadn't finished after 2m49s of 100% CPU
on this 8GB Mac — killed it and switched to a SCOPED dedupe (existing
Greenville rows + new rows only, spliced back into the rest of the
untouched board). 17 seconds, identical result (every dedupe_key these new
rows can produce is Greenville-scoped; they carry no zip_code, so pass 2's
cross-county zip-blocking branch can't reach them either). Worth reusing
this pattern for any future large single-county ingest rather than a
full-board dedupe() call.

Verified live: 2,287 net-new Greenville rows (25 merged into existing
`greenville_mie_adverts` records), 100% carry a normalized `tax_owed`
balance, York's 119 TAX_SALE_OVERAGE rows still untouched. Greenville
county total: 584 -> 2,871 rows. Row count math checked at every step.

## Zero-row county sweep, resumed: Edgefield, Hampton, Jasper — no clean win (2026-09-14)

- **Edgefield**: treasurer/tax-collector pages carry only a generic "Welcome
  Packet" PDF, no delinquent/overage list of any kind.
- **Hampton**: its Tax-Services page (`/367/Tax-Services`) has no document
  links at all.
- **Jasper**: has a Forfeited Land page, but its own PDF is literally named
  `flc-none-available.pdf` (confirmed: no current FLC inventory) alongside
  stale 2024 meeting agendas. Its delinquent-tax page cites SC Code 12-51-40
  directly and states the roster is published via "a paper of general
  circulation within the county for three consecutive Wednesdays prior to
  the tax sale" — i.e. Jasper's list lives in a LOCAL NEWSPAPER legal
  notice, not on the county site. Not yet in `sc_tax_delinquent.py`'s
  newspaper-outlet config; would need identifying which specific paper
  serves Jasper and adding it there, not a new standalone scraper.

**RESOLVED (reclassified) 2026-09-14: Chester + Fairfield's shared tax SPA
is CapSolver-gated, not a reverse-engineering problem.** Drove Chester's
`chestercountysctax.com` into its actual search page (`/taxes.html#/`) with
a real browser and captured live network requests: the page loads Google
reCAPTCHA v2 (`size=invisible`, explicit render) immediately, before any
search form is usable — hosted on a CloudFront-fronted, Azure-App-Insights-
instrumented SaaS product (likely serving other SC counties too, not just
these two). This is the SAME class of wall as Cherokee/Union qPublic and the
SC probate AWS-WAF block: solvable with the already-authorized CapSolver
integration once `CAPSOLVER_API_KEY` is staged (still unset as of this
check), NOT a bespoke API-reverse-engineering task like DEW was (DEW had no
CAPTCHA on its search paths at all). Fairfield's identical hash-routing +
CSS bundle shape strongly suggests the same platform and the same gate,
though not independently confirmed live this pass. Filed alongside the other
two CapSolver-blocked walls so all three get attempted in one pass whenever
the key lands.

**Greenwood** checked too: real domain is `greenwoodcounty-sc.gov` (the
`.gov` bare domain meta-refreshes there). Its tax-collector and treasurer
pages are large (800K+ chars) but neither mentions "overage," "surplus,"
"excess," or a delinquent-tax-sale document/link anywhere. No source found.

**Status after this iteration**: Aiken (reCAPTCHA-gated claim form),
Dillon (document center needs a working browser-rendered pass — first
attempt timed out waiting for networkidle), Dorchester (no overage content
found), Edgefield/Hampton (no document of any kind), Jasper (published via
newspaper, not the county site), Chester + Fairfield (same vendor SPA,
needs one real reverse-engineering pass), Kershaw (only a bare geometry
GIS layer, county site unreachable), Williamsburg (own GIS host but a
different proprietary "TGIS" engine), and Greenwood (no source found) all
remain open.

## Per-county SC mailing cache build-out — iteration 3 (2026-09-14)

**Barnwell (886 rows) — done, verified, live.** Found via an AGOL
account-name GUESS (`barnwellcountysc`) after generic keyword search
returned nothing — worth trying the `<county>countysc` pattern class before
concluding a county has no independent layer (this is the second time it's
worked, after Lexington/Lancaster's "own account, different search angle"
pattern). Very rich CAMA export (110 fields — mailing, situs, sqft,
beds/baths, year built, owner-occupied flag). One real limitation found and
respected rather than worked around: board parcel_ids with a trailing
".NN" sub-parcel suffix (about 2 of 5 sampled) have no match at all on this
layer (it only tracks the PARENT parcel) — left as a miss rather than
falling back to parent data, which could be a different owner for a split
sub-parcel. Verified: **mailing 0.0% -> 58.4%** (517/886). York's 119
TAX_SALE_OVERAGE rows still untouched.

**Tried the same account-name-guessing approach for Abbeville, Bamberg,
Saluda, McCormick, Lee, Calhoun, Marlboro, Allendale — no parcel layer
found for any of them.** All eight turned up only a "KIP `<County>` County,
SC" Web Map from a recurring `evoss_BRPF` account (a boundary/demographic
map product by its naming and type, not a parcel-data Feature Service —
didn't chase further) plus assorted irrelevant noise (Florida statewide
parcels, other states' Lee/Calhoun counties). These eight are genuinely
the hardest remaining counties for the mailing gap; no lead found today.

**Chester + Fairfield's shared tax SPA — reclassified, not solved.**
Actually drove the search page with a real browser this time (previous
passes only loaded the landing page): `chestercountysctax.com/taxes.html#/`
loads an invisible Google reCAPTCHA v2 the instant the search page opens,
before any form is usable. This is the SAME wall class as Cherokee/Union
qPublic and the SC probate AWS-WAF block — solvable via the already-
authorized CapSolver integration once `CAPSOLVER_API_KEY` is staged (still
unset), not a bespoke reverse-engineering task like DEW was. All three
CapSolver-gated walls should be attempted together whenever the key lands.
