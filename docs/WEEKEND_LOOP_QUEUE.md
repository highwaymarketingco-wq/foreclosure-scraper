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
- [ ] BT TaxPayer Portal — 14 NC counties, delinquent balances, one vendor family.
      Alleghany Anson Carteret Caswell Craven Duplin Graham Jones Person Scotland (+4)
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
- [ ] Greer SC code enforcement — 2,035 cases WITH owner name (code_vacancy is 2/18).
- [ ] Kofile/Oconee ROD — JSON API found, 501 instruments per 10 days.
- [ ] AcclaimWeb Pickens — consideration (sale price) is on the DETAIL page, not the grid.

## QUEUE — verification and integrity (the "nothing is broken" half)
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
