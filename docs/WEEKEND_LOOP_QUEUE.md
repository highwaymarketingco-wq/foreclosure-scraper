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

## QUEUE — sources to build or fix
- [ ] RUN enrichment_bt_appraisal_card over the board (needs a GO from loop_guard)
- [x] BT TaxPayer Portal — DONE as an appraisal-card enricher, 14 VERIFIED counties.
      Gives HEATED SQFT + appraised value + beds/baths + recorded sale price.
      5 proposed tenants were dead stubs; ITSPublicMA was proposed for Martin and
      actually serves PERSON COUNTY — rejected. Still to do: run it over the board.
- [ ] Catalis/Sturgis for NC — Caldwell, Carteret, Stanly, Stokes each have their own
      GUID under d1ebsyxxbc7tep.cloudfront.net. Scraper exists; add the county GUIDs.
      PACE 8s — this host 429s hard.
- [ ] Catalis Pickens full run — needs ~2 unattended hours at the 8s pace.
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
