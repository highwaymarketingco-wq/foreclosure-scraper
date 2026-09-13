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
