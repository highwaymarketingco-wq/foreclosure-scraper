# Operations and pipeline health audit, 2026-09-21

Independent, read-only audit of how the foreclosure engine actually runs on the one 8 GB Mac. Audit clock: Mon 2026-09-21, about 09:30 to 10:00 EDT, while the daily 09:30 job was mid-run and holding the board lock.

Method and limits. I read launchd plists, wrapper scripts, logs/, /tmp job logs, run_meta.json, git history, and used read-only `gh api` calls. I did NOT load the board, run scrapers or backfills, or edit anything except this file. Every board number below comes from run_meta.json, job logs, or git object sizes, not from opening listings.json. All times are EDT unless marked Z.

---

## (a) Summary: the 8 most important findings

1. **O1 (critical): the published board file is about 4 to 8 days from GitHub's 100 MiB per-file limit.** docs/listings.json.gz is 84.3 MiB (88,397,406 bytes) and was 34 MiB on 8/26, 65 MiB on 9/16, 78 MiB on 9/18, 80.1 MiB on 9/20. When it crosses 100 MiB every publisher's push is rejected, the commit stays local, and every later push (including code) carries the poisoned blob until history is fixed by hand. All publishers print a failure and exit 0.
2. **O2 (critical): the full pipeline has not written the board since 2026-08-29 05:43, and 98.7% of board rows come from sources no scheduler refreshes.** Since then: three OOM kills (exit 137) on 8/29 to 8/30, and a 15 hour run on 9/8 to 9/9 that exited 0 but was refused by the count guard. Only 2,207 of 170,528 rows come from the 14 sources the daily job refreshes. The Tue/Fri "weekly" job is a popup that needs a human click, and it makes the daily job skip those two days, so Tue/Fri currently refresh nothing.
3. **O3 (high): the write path is advisory, not enforced.** 54 board-writing modules never take the board lock (including main.py), write_artifact() neither checks the lock nor checks that the board on disk is the one that was loaded, and the six payload files are written one after another with no manifest check on load. A kill, disk-full, or OOM between files leaves a mixed set that loads without error.
4. **O4 (high): health reporting is stale and reports itself as current.** run_meta by_source sums to 94,384 while total is 170,528; per-source status, errors and alarms are frozen from 8/29; `health_carried_from` always names the previous write (today 05:28Z), never the true origin. A failed board write on 9/9 still exited 0 and still sent the digest email.
5. **O5 (high): there is no backup of anything that matters except the board-in-git.** Time Machine: "No destinations configured". Local-only: sc_parcel_mailing.db, sc_footprints.db (2.5 GB), docs/crm.json (CRM state for 18,280 leads), .secrets, .env, the LaunchAgent plists. Rolling board backups hold only the last 3 writes, which on 9/21 span about 90 minutes. There is no written restore procedure.
6. **O6 (high): the daily jobs starve each other and mostly do little.** The 09:30 vision job holds the board lock 3h51m to 5h55m to score 371 to 759 listings per day (live workers collapse from 21 to 1 within 40 minutes). Noon lrcpwa is skipped whenever vision runs past 12:00 (no lrcpwa commit since 9/14). The daily API refresh carried over 8 of its 14 sources on 9/20 and had no successful commit between 8/26 and 9/17.
7. **O7 (high): the repo is 12.7 GiB on GitHub against a 5 GB soft limit, and each publish pushes 120 to 180 MB.** Issue #131 (opened 9/14 by the watchdog, 7,115 MB then) has no comment. Growth since then is about 800 MiB per day. Pushes have no timeout and run inside the board lock. Deployed site is 561.6 MB against a 950 MB build-fail threshold.
8. **O8 (high): a public repo publishes owner PII.** The repo is public. The board .gz carries owner_email on 78,504 rows (per the write_artifact slim-drop log), and docs/outreach_maillist.csv (owner, mailing address, phone) is tracked in git and deployed to Pages despite being listed in .gitignore.

Also serious, ranked 9th: **O9 memory and disk wear.** Since the 9/19 13:15 boot the Mac has swapped out about 1.1 TB (69.8M pages at 16 KiB), swap is 4.5 GB of 5.1 GB used, and PhysMem shows 62 MB unused with the daily job running.

---

## (b) Job table

"Board" means docs/listings.json (1.1 GB, 170,528 rows) plus its detail sidecar and gz/slim/shard twins.

| Job | Schedule | What it writes to the board | Last successful run (log + git) | Typical duration and memory | If it fails |
| --- | --- | --- | --- | --- | --- |
| dailyvision, API phase (`daily_api_refresh.py` via `run_daily_vision.sh`) | 09:30 daily, skipped Tue and Fri | Replaces rows for 14 REO/API sources (2,207 rows on the board). Because it round-trips the whole board it also re-grades, re-scores HOT/WARM/COLD, re-dedupes and rewrites all rows and all gz/slim/shard files. Commit "daily api refresh" | 9/20 10:03 (62e01dc, 170,528 rows). Before that 9/17 10:01 (fe5fb34). Before that 8/26 10:18 (d02d6e8). None 8/27 to 9/16 | 12 to 33 min normal (9/17 32 min, 9/20 33 min); 5h37m on 9/10 when it failed on a thrashing Mac. Memory not logged; operator note says one load is 2.8 GB | Wrapper does `|| echo "api refresh failed (continuing...)"` and goes on to vision. No alert. dailyvision.out.log shows that line on 9/5, 9/6, 9/7, 9/9, 9/10, 9/12, 9/13, 9/14. Verified cause on 9/10, 9/13, 9/14: COUNT GUARD refused the write |
| dailyvision, vision phase (`patch_vision_gemini.py`) | Same job, starts after API phase | Adds photo-condition scores for a few hundred listings and rewrites the whole board. Commit "daily vision: N listings scored" | 9/20 13:20 (4d08ac0). 9/17 ran 4h37m and died before writing (no commit, no exit line) | 3h51m (9/20), 4h14m (9/13), 5h55m (9/12), hard cap 14,400 s. Holds the board lock the whole time | Killed runs (no `exit=` line) on 8/27, 9/7, 9/10, 9/17; exit 137 on 8/30 and 8/31. Lock goes stale and is auto-broken by the next job. Nothing is published, no alert |
| lrcpwa (`lrcpwa_refresh.sh`) | 12:00 daily | Fills NC land-records addresses, county values, parcel photos; recomputes strategy and buyer tags; whole-board write, commit "Scheduled land-records refresh" | 9/14 12:20 (f99198c). Seven days ago | About 20 min from commit stamps (12:16 to 12:38 across history) | Lock busy: prints "skipping this noon run", exit 0, log in /tmp (confirmed skipped 9/20 12:00, holder was run_daily_vision.sh). Pass failure: exit 1 to /tmp only |
| sosagent (`sos_agent_refresh.sh`) | 14:00 daily | Adds NC SoS registered-agent contacts for up to 40 entity-owned leads; whole-board write; commits only if contacts landed | 9/20 14:07 (262f319). 9/20 run: 40 targets, 24 resolved, log 14:00:05 to 14:09:34 | About 9 min | Lock busy: exit 0. 9/20 push failed ("unexpected disconnect while reading sideband packet"), script printed the failure and exited 0; commit reached origin only with a later push |
| parcelcache (`parcel_cache_refresh.sh`) | Sun 04:00 | Does not touch the board. Rebuilds 26 county SQLite parcel caches in data/parcel_cache (3.0 GB); joining them to the board is a manual script | 9/20 04:00:05 to 04:34:27, "26 refreshed, 0 failed" | 34 min, no lock | Exit status of python is not propagated; log in /tmp. A failed county keeps the old cache (atomic replace, completeness check) |
| weekly popup (`prompt_run.sh`) | Tue and Fri 09:30 | Step 1 optionally ingests hand-saved court pages, step 2 optionally starts the full run. Does nothing unless a human clicks | See full-run history below | Popup gives up after 7,200 s | No log of whether the popup appeared or was answered. `exit 0` always |
| full run (`run_local.sh` then `python -m foreclosure_scraper`) | Only via the popup or the Desktop app | Scrapes about 209 sources, merges into the prior board, enriches, writes board, Sheet and email digest, commits | **Last board write: 2026-08-29 05:43** (run 20260828T073514, 1,329 min, commit 307de5f). Last attempt 9/8 15:57 to 9/9 07:00, wrote nothing | 15 to 57 hours. Memory not logged; killed by SIGKILL (137) on 6/30 and three times on 8/29 to 8/30 | See O2 and O13 |
| dailycourt (disabled 9/20) | 02:00 daily | NC eCourts / SC PublicIndex per-case detail via `patch_court_detail.py` | No success in retained logs | Failed in 0 seconds | 31 of 31 logged runs (8/20 to 9/20) exit 127 "uv: command not found". plist PATH lacked ~/.local/bin; plist was rewritten 8/19 23:07 |
| GitHub: pages.yml | Every push | Builds and deploys docs/ | Last deploy 9/21 12:55Z success. Last 40 runs: 37 success, 3 cancelled. Last 100 runs: 0 failures | 1.5 to 2 min | Failed build keeps previous deploy live |
| GitHub: repo-size watchdog | Mondays 13:00Z | Nothing on the board | 9/14 run opened issue #131 | 2 min | Alert goes to an issue nobody reads |
| Manual campaigns (SC divorce supervisor, resolvers, backfills) | Human or agent started | Most of the recent board commits: 9/13 18, 9/14 18, 9/15 24, 9/16 13, 9/19 11, 9/20 21 commits touching listings.json.gz | Ongoing | Hours each; they hold the lock and starve the scheduled jobs (9/16: daily vision skipped because `resolver_backfill_parcel` held it) | Skips are exit 0 |

### B1. What the daily API refresh actually refreshes

Fourteen sources, all plain HTTP/JSON: national.distressed, fannie_homepath, foreclosure_dot_com, freddie_homesteps, homeharvest, hud_homestore, irs_treasury, realtor_foreclosures, sc_public_index, tranzon, williams, and reo.treasury_seized, usda_rd, vrm_va_reo. A source that returns fewer than 3 rows is treated as failed and its prior rows are carried over untouched. On 9/20 eight of the fourteen were carried over (fannie_homepath 0, irs_treasury 0, sc_public_index 0, tranzon 0, williams 0, treasury_seized 1, usda_rd 1, vrm_va_reo 0). Fannie HomePath, whose stale links are the stated reason for the job, returns 0 every day and hits `scraper.timeout` in the daily log. So the job's headline purpose (stop sold REO 404s) is not being met, and the rows it carries over never age out.

### B2. Full-pipeline history (from logs/local-run-*.log and launchd.out.log)

| Start | Elapsed | Exit | Outcome |
| --- | --- | --- | --- |
| 6/30 09:30 | 574 min | 137 | OOM class kill, no publish |
| 7/3, 7/7, 7/10, 7/14 | n/a | no exit line | Started, never finished |
| 7/24 09:30 | 3,433 min (57 h) | 0 | Count-drop alert, 22,387 rows, publish skipped |
| 8/6 09:29 | 2,749 min | 0 | Published 35,957 rows (8/8 07:19, 5b62662) |
| 8/16 15:35 | 2,033 min | 0 | Published 40,593 rows (8/18 01:28, 63ec7d9) |
| 8/27 12:05 | 1,168 min | 143 | Terminated |
| **8/28 07:35** | **1,329 min** | **0** | **Published 94,384 rows (8/29 05:45, 307de5f). Last full run to land on the board** |
| 8/29 11:12, 15:12 | 226 min, 66 min | 137, 137 | OOM class kills |
| 8/29 17:30 | 922 min | 137 | OOM class kill |
| 9/8 15:57 | 902 min | 0 | web_artifact.failed: COUNT GUARD refused 39,088 rows over high-water 94,384. Process still returned 0, Sheet export and email digest still went out |

Commit 9747b96 (9/9) confirms: "The board has not been republished by a real scrape since 2026-08-29." It fixed the guard deadlock, but no full run has been attempted since, so the fix is unexercised. No local-run log exists after 9/8 (the wrapper keeps the newest 12).

### B3. Which source families are therefore stale

Board rows by family (run_meta by_source_on_board, current as of 9/21 05:33Z). Only the first row is refreshed on a schedule.

| Family | Rows | How it last changed |
| --- | --- | --- |
| 14 daily API sources | 2,207 (1.3%) | Daily, if the API phase succeeds (partly carried over, see B1) |
| counties_sc (qpaybill_delinquent_roll 33,528; sc_dew_lien_registry 8,818; sc_public_index 5,064; berkeley_paystar 2,310; greenville_delinquent_tax 2,287; florence 2,005; pickens 1,854; spartanburg_*; charleston_delinquent_tax 1,125, and more) | 70,105 | Last full run 8/28 to 8/29, or a one-off hand-run `ingest_*` script (qpaybill 9/11, Berkeley 9/15, Dillon 9/14, York 9/14). No scheduler |
| counties_generic (liensnc 40,909; state_contamination; arcgis_distress.*) | 51,414 | Same. LiensNC is a manual-login lane |
| counties_nc (gaston_vacant 7,035; transylvania_vacant 5,332; rutherford_tax 4,164; buncombe_elderly 2,988; lincoln_vacant 2,191; nc_county_pdf_delinquent_tax 1,772 and more) | 29,613 | Same |
| liensnc, nc_ecourts_judgments, city_websites, public_notices, courtlistener, law_firms, newspapers | 14,725 combined | Same, or manual court-page lane |

run_meta.source_status (frozen from 8/29) still lists 15 red ALARM rows (TIMEOUT for crexi, landandfarm, landsofamerica, landwatch, xome, zillow_foreclosures, sc_coastal_rosters, nc_rod_logan and others), 3 CARRYOVER (sc_public_index 3,735 stale rows, sc_public_index_lis_pendens, sc_public_notices), 13 EMPTY, 8 DORMANT, and a 39-entry errors list. None has been re-evaluated in 23 days. Foreclosure.com is marked "DORMANT, disabled: edge-WAF 403" in that frozen status, yet the 9/21 daily log shows it returning 512 NC and 882 SC rows, so the frozen status is also wrong in the other direction.

### B4. Lock map and overlap windows

Lock holders (take `board_lock` or `board_lock_acquire`): 95 Python files, plus the shell wrappers run_daily_vision.sh, lrcpwa_refresh.sh, sos_agent_refresh.sh, run_local.sh, ingest_saved.sh. All five scheduled board jobs and both manual-lane wrappers use it.

Board writers with NO lock reference: **54 modules** (49 scripts, 5 in src including main.py, board_persist.py, checkpoint.py, hourly_refresh.py). Examples: daily_api_refresh.py (protected only when launched by the wrapper, because the child inherits FORECLOSURE_BOARD_LOCK_HELD), merge_today_sources.py, enrich_board.py, regenerate_dashboard.py, ingest_liensnc.py, qpaybill_tax_refresh.py, catchup_geocode.py, recompute_equity.py, stamp_corroboration.py, plus the legacy chains auto_rerun.sh and post_run_catchup_chain.sh, which guard with `pgrep` only. `write_artifact()` itself does not check for the lock.

Concrete windows (from schedules and observed durations):

| Window | What is exposed |
| --- | --- |
| 09:30 to 13:21 on 9/20 (also 09:30 to 14:06 on 9/17, to 15:25 on 9/12) | Vision loaded the board at 10:05:01 and wrote it at 13:20:52. Any unlocked writer that runs in that window is silently overwritten at write time. Any locked writer skips. lrcpwa (12:00) is always inside the window; SOS (14:00) is inside it on 9/12 and 9/17 |
| Tue or Fri 09:30 to the end of a 15 to 34 hour full run | Lock held by run_local.sh. lrcpwa, SOS and the next day's daily vision all skip with exit 0 |
| Sunday 04:00 to 04:34 (parcelcache) | Takes no lock and no memory gate. On 9/20 it overlapped the overnight SC divorce backfill rounds committing at 04:30 |
| Any hand-run of the 54 unlocked writers while any scheduled job holds the board | Last-writer-wins. This is the 8/10 incident (1,064 parcels, 343 county values, 410 absentee tags reverted) still open for every unlocked script |
| Every scheduled publisher's `git commit` | Commits everything already staged in the shared working tree, including whatever an operator or agent session had staged at that moment. `git pull --rebase --autostash` also stashes and re-applies the operator's uncommitted work |

I found no commit message after 8/11 describing a collision or revert, so the risk is structural, not observed since the lock landed.

---

## (c) Findings

### O1. Board gz file approaching GitHub's 100 MiB per-file limit (CRITICAL)

Evidence:
- docs/listings.json.gz measured from git blobs: 34 MiB (8/26), 43 (8/29), 50 (9/11), 57 (9/14), 65 (9/16), 78 (9/18), 80.1 (9/20 10:03, printed in the push log as "File docs/listings.json.gz is 80.11 MB; larger than GitHub's recommended maximum file size of 50.00 MB"), 84.3 MiB now (88,397,406 bytes, written 9/21 01:32).
- Headroom 15.7 MiB. Rate over the last 5 days is 2.1 to 3.9 MiB per day; the 9/16 to 9/18 landing alone added 13 MiB in two days.
- The 50 MB warning is printed on every publish and no script or human reads it. gzip level 9 is already used, so there is no compression slack.

Failure scenario: a routine enrichment pushes the file over 100 MiB. `git push` is rejected (GH001). Every publisher prints its failure and exits 0. Because the oversized blob is now in a local commit, every later push, including small code or doc pushes, is rejected too until the commit is undone. The live dashboard freezes on the last good board and nothing alarms.

Fix and effort:
- Same day (S, about 1 hour): add a size gate to `board_payload_add` in scripts/board_payload.sh that refuses to stage any payload above 95 MiB and writes a loud line to a persistent log; add a `.git/hooks/pre-push` that rejects blobs above 95 MiB so a bad local commit never forms.
- This week (M, 1 to 2 days): stop shipping the monolithic listings.json.gz to Pages. Publish the desktop board as 4 or more parts of about 20 MiB with a manifest (dashboard.js concatenates), or trim the published `raw` (this also addresses O8). The 31 MiB slim file and 171 detail shards already exist as the phone path.

### O2. The full pipeline is effectively dead and most rows have no scheduled refresh (CRITICAL)

Evidence: see B2, B3. Last board write by a full run 8/29 05:43 (307de5f); 9/9 commit message says so in its own words. Three SIGKILL exits on 8/29 to 8/30 and one at 6/30. 2,207 of 170,528 rows (1.3%) are refreshed daily. `run_daily_vision.sh` sets `FULL_RUN_DAYS="2 5"` and exits 0 on Tue and Fri "because the weekly run_local.sh handles today", but the weekly job is a popup (prompt_run.sh) that does nothing unless a human answers two dialogs within 2 hours, and it writes no log. Since 8/29 the six Tue/Fri days (9/1, 9/4, 9/8, 9/11, 9/15, 9/18) had a skipped daily job; only 9/8 had a full-run attempt, and it wrote nothing. The dailycourt job that drilled per-case court detail failed for 31 days. Cadence of successful full-run publishes since June is 7 in about 14 weeks (6/18, 6/24, 6/26, 8/2, 8/8, 8/18, 8/29), not the twice-weekly the docs describe.

Failure scenario: sale dates, upset-bid windows, tax-sale dates and delinquency balances age silently. The board still ranks and displays them, and run_meta still looks alive because `run_time` and `total` move on every manual write.

Fix and effort:
- S: delete the FULL_RUN_DAYS skip in run_daily_vision.sh. The board lock already prevents overlap with a real full run, so the skip only creates dead days.
- M: replace the 15 to 57 hour monolith with per-family scheduled jobs that merge into the board under the lock (the merge_today_sources.py pattern), highest rows first: qpaybill_tax_refresh (33,528 rows), NC and SC delinquent-tax pulls, nc_ecourts judgments. Each gets its own timeout and its own line in the job event log (O4).
- M: before any further full run, dry-run a 5-source sample on the 170k board with memory sampled (see O13).

### O3. Board write path is unenforced and not atomic across its files (HIGH)

Evidence:
- 54 unlocked writers (B4). `write_artifact()` (web_artifact.py line 1656) has no lock assertion and no check that listings.json is unchanged since load.
- `load_board` and `read_board_records` (lines 250 to 300) merge the detail sidecar by array index with only `if i < len(details)`; run_meta stores `detail_count` and `detail_digest`, but nothing verifies them at load. `read_board_json` prefers the plain .json over its .gz twin.
- write_artifact writes listings.json, listings_detail.json, then both .gz twins, then slim, then shards, then run_meta, each atomically per file but not as a set. The function's own comments describe the failure: a mixed set "loaded without exception, 25,000 of 25,000 leads carrying the neighbour's vision and comps".
- The window is real: `disk to 0 bytes free` on 9/17 (commit 0cd2d26, "tee: No space left on device"), and unexplained deaths of the vision job on 9/7, 9/10, 9/17 plus SIGKILL exits 8/29 to 8/31.
- `load_board` also does `except Exception: pass` around `Listing.model_validate`, so any row that fails validation is dropped on every load-then-write cycle with no log line (count unknown, I did not load the board).

Failure scenario: a process is killed or the disk fills after listings.json is replaced but before the detail file is. The next writer loads a new board with an old sidecar, joins them by index, and republishes. Comps, vision and CAMA belong to the wrong properties, run_meta looks normal, and the count guard passes.

Fix and effort:
- S: in write_artifact raise unless `FORECLOSURE_BOARD_LOCK_HELD` equals the lock path (with an explicit `BOARD_LOCK_BYPASS=1` for tests). This turns all 54 unlocked writers into fail-closed with no per-script edits.
- S: record `(st_mtime_ns, st_size)` of listings.json inside load_board and compare in write_artifact; abort on mismatch ("board changed since you loaded it").
- M: write `docs/board.manifest.json` last (counts and sha256 of all payload files); have load_board and read_board_json verify it and refuse the plain-over-gz preference when they disagree.
- S: log every dropped row in load_board with a counter, and fail if the drop rate exceeds 0.1%.

### O4. Health and status fields are stale and report themselves as current (HIGH)

Evidence:
- run_meta.json (9/21 05:33Z): total 170,528 but `sum(by_source)` is 94,384 and `source_status` has 140 entries, both identical in every commit I sampled from 307de5f (8/29) to today. `errors` has 39 entries, frozen the same way.
- `health_carried_from` is written as `prior_meta.get("run_time")` (web_artifact.py around line 1971), the previous write's time. It therefore always looks minutes old: 9/21 05:28Z today, 9/20 22:22Z a day earlier, and so on, hiding a true origin of 8/29.
- docs/run_health.json is committed and deployed with generated_at 2026-09-09 (the failed 9/8 run), 12 days older than the board it ships beside. It reports total_listings 39,088, a board that was never written.
- run_local.sh reads "total listings this run" from the log and falls back to run_meta.json; on 8/30 and 9/9 the fallback printed 94,384 for runs that wrote nothing.
- main.py catches a write_artifact failure at line 3466 (`log.error("web_artifact.failed")`) and carries on: sold pool, run_health, Google Sheet export and the digest email to Greg and Cash all still ran on 9/9, and the process returned 0.
- The 9/20 vision summary prints `unscored_remaining=0` while its heartbeat 33 seconds earlier read `queue=4406`.

Failure scenario: an operator reads run_meta or the emailed digest, sees fresh timestamps and a green status, and concludes sources are healthy when their last real evaluation is 23 days old.

Fix and effort:
- S: carry `health_as_of` forward unchanged from the first write that computed it, add `health_age_hours`, and null out `source_status` and `errors` when the age exceeds 48 hours so consumers see "unknown".
- S: make main.py return non-zero when write_artifact raises and skip the Sheet and email in that case; have run_local.sh abort on that.
- S: give every scheduled job one JSON line in `logs/job_events.jsonl` (job, start, end, outcome in ok, skipped_lock, no_change, failed, push_failed, rows_changed). A 20 line watcher run from launchd alerts when any job has no `ok` in 48 hours.

### O5. No backup of anything except the board-in-git (HIGH)

Evidence:
- `tmutil destinationinfo`: "No destinations configured". Only Google Drive.app, NinjaRMM and Webroot are installed; I found no backup agent.
- Gitignored and local-only: data/sc_parcel_mailing.db (148 MB, 8/3), data/sc_footprints.db (2.5 GB), data/parcel_inventory.db (246 MB), data/sc_cama.db (66 MB), data/notice_pdfs (43 directories), data/ncvoter (565 MB), data/checkpoint/board.json.gz (65 MB, 9/9), docs/crm.json (15 MB, CRM tracking for 18,280 leads, 9/9), logs/ (472 MB), .secrets/ (nine Gemini keys, Anthropic, Google service account JSON, Gmail app password, Groq, NVIDIA, Cloudflare), .env, and the five LaunchAgent plists (the repo has no copy of them).
- backups/ holds exactly 3 pre-write copies of the board plus detail (3 x 1.3 GB). Retention is by write count, so after 9/21's session they are all from a 90 minute span (mtimes 00:03, 01:23, 01:27). On 9/13 to 9/15 with 18 to 24 writes per day a bad write followed by two more would leave nothing older than 30 minutes.
- The board itself is recoverable: 224 commits touch listings.json.gz, and GitHub has them. But no document says how to restore (which files must come from the same commit, that the plain .json must be deleted first because readers prefer it). OPERATIONS.md section 7 covers a diverged main and a died full run, not a bad board.
- Disk history: 0 bytes free on 9/17 (commit 0cd2d26: detail backups never pruned, 214 files, 24 GB), and 9/19 (commit e2563ec: cut backups from 12.1 GB to 3.6 GB, "a laptop that needed 50 to 80 GB back"). Now 61 GiB free of 228 GiB (70% used). Local .git is 18 GB (13.7 GB of it loose objects; git gc has not compacted it).

Failure scenario: the SSD fails, or the laptop is lost or stolen. The board survives via GitHub, but the parcel mailing database, footprints database, CRM state, API keys and schedules are gone. The API keys must be re-issued, the schedules recreated from memory.

Fix and effort:
- S (an hour): turn on Time Machine to an external disk, or a nightly script that copies data/*.db, data/checkpoint, data/notice_pdfs, docs/crm.json, .env, ~/Library/LaunchAgents/com.highway.*, and an encrypted archive of .secrets to Google Drive.
- S: keep one daily verified last-known-good copy of the gz set (about 135 MiB) for 7 days, separate from backups/.
- S: write `scripts/restore_board.sh <commit>` (checks out all gz twins from one commit, removes plain json, prints digests) and a short runbook, and test it once on a scratch clone.
- S: check whether sc_parcel_mailing.db can be rebuilt by scripts/build_sc_parcel_mailing.py from a live source; if not, treat it as irreplaceable and back it up first.

### O6. Daily jobs starve each other and mostly do little (HIGH)

Evidence:
- Vision yield is collapsing while it holds the lock 3h51m to 5h55m: scored 371 (9/9), 711 (9/12), 587 (9/13), 759 (9/17, lost), 635 (9/20). `live_workers` falls from 21 to 1 within about 40 minutes on every run (9/12, 9/13, 9/17, 9/20). Causes visible in the 9/10 log: NVIDIA NIM models returning 410 end-of-life, Mistral 402 subscription errors, GitHub Models "retirement brownout" 410s. Only about 13% of rows (22,326 of 170,528) have any vision score.
- lrcpwa: last commit 9/14. Confirmed skipped 9/20 12:00 because the lock holder was run_daily_vision.sh. Any day vision runs past noon skips it, which is every non-Tue/Fri day at the current 4 hour cap.
- SOS ran on 9/20 only because vision ended at 13:21. Vision ended 14:06 on 9/17 and 15:25 on 9/12. SOS commits exist for 9/14, 9/15 and 9/20 but not 9/12 or 9/13, 9/16 to 9/19.
- The API phase: no successful commit between 8/26 and 9/17 (21 days) although the job ran daily; then B1 carryover.
- 9/19 (Saturday): no daily-vision log at all, following the 13:15 reboot (commit 26fced9 calls it "the laptop crash"). The jobs cannot catch up because a missed calendar slot is only replayed if the Mac was asleep, not off.

Failure scenario: four hours of daily lock time buy a few hundred vision scores, while the two jobs that produce contact data (lrcpwa, SOS) and the API refresh that keeps REO links alive are the ones that lose.

Fix and effort:
- S: time-box vision to 60 to 90 minutes with a yield stop (exit when live_workers is 2 or fewer for 15 minutes or scored per hour drops under 100). Order the day: lrcpwa 08:00, SOS 08:30, API refresh 09:30, vision after.
- S: make the daily wrapper fail loudly (job event, nonzero exit) when the COUNT GUARD fires or more than 4 of 14 sources are carried over.
- M: replace the dead vision backends (NVIDIA EOL models, Mistral, GitHub Models) or retire vision for rows with no photo.
- S: make the guard's "intentional off-footprint removals" allowance visible to daily_api_refresh.py (it passes no `off_footprint_removed`, so its scope re-filter trips the guard whenever the board changed shape).

### O7. Repository and publish weight (HIGH)

Evidence:
- `gh api` size: 13,034,104 KB (12.7 GiB) against the watchdog's 5 GB soft limit. Issue #131, opened 9/14 with 7,115 MB and "growth 249.9 MB/day, runway -8 days", is still open with zero comments. Growth since then is about 800 MiB per day. 149 branches on GitHub, about 125 of them `bot/porsche-refresh-*`.
- One publish of the current board (6d41e4e) adds about 172 MiB of new objects (listings.json.gz 84 MiB, slim 31 MiB, 99 changed detail shards 54 MiB; the detail file was unchanged); 262f319 added 118 MiB. Board commits per day: 9/13 18, 9/14 18, 9/15 24, 9/16 13, 9/18 9, 9/19 11, 9/20 21.
- Push failures observed 9/20: "unexpected disconnect while reading sideband packet" (SOS, 14:09) and "Could not resolve host: github.com" (vision, 13:21). Both printed and exited 0. Earlier /tmp logs are gone (see below), so I could not count 408s. Only `http.postbuffer 1048576000` is configured; there is no `http.lowSpeedLimit`/`lowSpeedTime`, and `git push` in daily_api_refresh.py (line 358), patch_vision_gemini.py (line 258), lrcpwa_refresh.sh and sos_agent_refresh.sh runs with no timeout while the board lock is held.
- Recovery depends on a later push succeeding. Nothing tests that. Current state at audit time is healthy: `git status -sb` shows `main...origin/main` with 0 ahead and 0 behind, and the last Pages deploy succeeded.
- Deployed site: I computed 561.6 MB of tracked, published files (parcel_photos 326.6, listings.json.gz 88.4, detail_shards 69.2, slim 32.5, detail 16.5, handoff 12.3, outreach_maillist.csv 5.9). pages.yml warns at 600 MB and fails the build at 950 MB. OPERATIONS.md still says 398 MB.
- What depends on Pages being current: the dashboard (index.html, dashboard.js) and the phone client, which read listings.json.gz, listings_slim.json.gz, detail_shards/ and run_meta.json from Pages. A stale Pages means stale leads for whoever uses the site.

Failure scenario: GitHub throttles or contacts the owner over repo size; or a stalled push holds the board lock for hours (every other job skips with exit 0); or an interrupted push leaves a local commit that later publishers push in a batch.

Fix and effort:
- S: `git config http.lowSpeedLimit 1000; http.lowSpeedTime 120`, wrap pushes in `timeout 900`, and move each wrapper's push out of the lock (commit inside, release, then push with retries).
- S: rate-limit publishes: batch manual sessions to at most one board commit per 60 minutes.
- M: adopt OPERATIONS.md section 8 option 1 (payloads on one force-pushed orphan branch) so history stops growing by 800 MiB a day; afterwards a one-time, human-run `git filter-repo` on a fresh clone. Delete the stale bot/porsche-refresh-* branches and run `git gc` locally.
- S: act on issue #131 or close it with a decision; a watchdog nobody reads is a silent failure.

### O8. Owner PII is published from a public repo (HIGH, policy)

Evidence: `gh api` reports `"private": false`. The write_artifact slim-drop log lists keys present on the board but not the phone payload, including `owner_email: 78504`, so owner email is in the full board that ships as docs/listings.json.gz. `docs/outreach_maillist.csv` (5.9 MB; columns include owner, mailing_address, property_address, phone, absentee) is tracked in git (added 8/26, re-committed 9/10) although .gitignore lists it, and `check_pages_publish.py` logic treats it as deployed. I did not download the live files, so I have not confirmed they are reachable at the Pages URL; the evidence is repo visibility, git tracking, the Jekyll decision function and the log line.

Failure scenario: anyone can download names, mailing addresses, phone numbers and emails of distressed homeowners from a public GitHub repo and its history. That is a compliance and reputational exposure for the operator, and it cannot be undone by deleting the file later because history persists.

Fix and effort:
- S: `git rm --cached docs/outreach_maillist.csv` and exclude it in docs/_config.yml (with the include/exclude prefix rule from OPERATIONS.md section 4).
- M, needs an operator decision: either make the repo private, or publish only fields the dashboard needs and keep owner contact fields in local-only sidecars. Note this interacts with O1, since dropping `raw` fields also shrinks the file. I make no legal claim; this needs the operator, and counsel if the operator wants one.

### O9. Memory, swap and SSD wear on an 8 GB machine (HIGH)

Evidence:
- 09:34: swap 4,500 MB of 5,120 MB used. 09:47: PhysMem 7,545 MB used (compressor 2,859 MB, wired 1,776 MB), 62 MB unused, while the daily API job was the only board job running.
- `top` cumulative counters since the 9/19 13:15 boot (about 44.7 h): 69,790,940 swap-outs and 63,690,424 swap-ins (16 KiB pages, so about 1.1 TB out and 1.0 TB in), and 1,306 GB written to disk in total. This is the single largest resource cost on the machine. A caveat: I could not separate swap from other writes precisely.
- One board load is 2.8 GB (operator note); three concurrent loads reached about 20 GB and forced a restart (memory file). write_artifact holds several representations of the board at once: the Listing objects, the payload dicts, a second full read of listings.json and listings_detail.json inside `_load_prior_details_by_key`, then the 1.1 GB serialized bytes. The code comments "free ~350 MB before projecting (8 GB box)". That is inferred from the code, not measured.
- Each write also copies a 1.3 GB backup first. On 9/10 the API refresh took 55 minutes between its last scraper line and `equity.done` (re-grade plus equity on a 68k-row merge) on a thrashing machine.
- Nothing prevents two board readers from running together: the lock covers writers only. parcelcache (Sun 04:00) and scrapers take no memory gate. The Claude renderer, the claude CLI and Chrome hold roughly 700 MB or more.
- The Mac is on battery (99%, "10:39 remaining") with sleep held off by caffeinate. run_local.sh's own comment says a closed lid on battery can still sleep.
- The three OOM-class kills (137) on 8/29 to 8/30 happened against a 94k-row board; the board is now 170k.

Fix and effort:
- S: add a memory gate to `board_lock_acquire` and to parcelcache: refuse or wait when swap used exceeds 3 GB or free plus inactive is under 1 GB, and log the reason as a job event.
- S: log swap-out delta and RSS peak at the start and end of each job into job_events.jsonl so the next audit has measurements.
- M: pass the already-loaded detail into write_artifact instead of re-reading both files (removes one full copy), and stream the JSON write.
- S: require AC power for any run expected to last more than an hour.

### O10. Silent-failure inventory (MEDIUM)

Each item is quoted evidence, not inference.

| Item | Evidence |
| --- | --- |
| dailycourt failed every day for a month | dailycourt-stdout.log: 31 lines "exit=127", 0 "exit=0" (8/20 to 9/20); court-20260920T020005.log: "run_daily_court.sh: line 21: uv: command not found". Disabled 9/20. Nobody was told |
| "Run finished" false success | gui_run.sh notifies "Run finished - dashboard updated." whenever `run_local.sh` exits 0, and run_local.sh does `exit 0` when it cannot get the board lock ("refusing to start") |
| Popup leaves no trace | prompt_run.sh has no log writes and always `exit 0`; the plist logs (launchd.out.log last touched 7/26) show nothing about the popup |
| Job logs in /tmp | lrcpwa, sos, parcelcache log to /tmp. /tmp/lrcpwa_refresh.log currently contains only the 9/20 entry: everything earlier was cleared by the 9/19 13:15 reboot. I cannot say what lrcpwa or SOS did on 9/15 to 9/19 |
| Push failures print and exit 0 | daily_api_refresh.py (`"push failed"` then `return 0`), lrcpwa_refresh.sh and sos_agent_refresh.sh ("commit made locally but PUSH FAILED" then exit 0), 9/20 vision log "push failed" then `exit=0` |
| Backup failure does not block the write | web_artifact.py: `except Exception: log.warning("web_artifact.backup_failed")`, "backup failure must not block the write" |
| Skipped-lock exit 0 with no aggregate | 9/16 daily vision skipped ("another board writer (24437 resolver_backfill_parcel)"); 9/20 lrcpwa skipped; no counter, no alert |
| Monitors that vanished | ~/.hermes/cron/jobs.json is `{"jobs": []}` (updated 8/19 15:04), but HANDOFF.md says "Monitor cron foreclosure-enrich-monitor pings every 30 min". The Claude scheduled task `foreclosure-daily-harvest` (daily digest to Cash) has a SKILL.md edited 8/6 but is absent from `list_scheduled_tasks`. The GitHub `Tests` workflow only triggers on pull requests (last run 5/28), so no job ever tests a push to main |
| Alerts nobody reads | Issue #131 (repo size) open 7 days, 0 comments; push-size warnings on every publish; run_meta "errors" (39 entries, frozen) |
| Vision "unscored_remaining" | 9/20: `unscored_remaining=0` in vision.done, `queue=4406` 33 seconds earlier |

Fixes: the job event log and 48 hour watcher from O4 cover most of these (S). Also: write launchd job logs under logs/ instead of /tmp (S); give prompt_run.sh one log line per decision (S); make run_local.sh exit 75 on lock refusal and have gui_run.sh report it (S); stop treating a nonzero `uv` lookup as success by adding `command -v uv` checks at the top of every wrapper (S).

### O11. Lock design gaps (MEDIUM)

Evidence from board_lock.sh and web_artifact.board_lock: ownership is the wrapper's PID (`$$`); children inherit the lock through an env var and never register their own PID. If a wrapper is killed but its Python child survives (a `pkill` of the shell, a terminal close), the lock looks stale, the next job breaks it and starts a second writer while the child is still writing. Stale detection is `kill -0` only: a hung holder with a live PID blocks every other job forever, and a recycled PID makes a dead lock look alive. Manual agent sessions take the same lock for hours (9/16), so they starve the schedulers with no alarm. `logs/.board.lock` currently belongs to pid 11347 (run_daily_vision.sh, healthy).

Fix (S to M): store start time and a heartbeat timestamp in the lock; treat a lock older than the job's max runtime plus 30 minutes as stale even if the PID is alive, and log the break; have child writers re-stamp the pid file with their own PID; record every skip in job_events.jsonl.

### O12. Environment drift and PATH fragility (MEDIUM)

Evidence:
- The 9/8 full-run log opens with "Uninstalled 25 packages" from `uv sync --frozen` in run_local.sh, including easyocr, scipy, shapely, opencv-python-headless, openpyxl, pytesseract, networkx, scikit-image, nodriver. pyproject.toml declares none of them except nodriver (added 9/16, commit 95974a9). `.venv` currently lacks all eight others. easyocr is imported by src/foreclosure_scraper/enrichment_ocr.py. So every full run silently removes hand-installed packages.
- dailycourt's root cause was a plist PATH without ~/.local/bin (`uv: command not found`).
- lrcpwa and sos hardcode /Users/cashhigh/.local/bin/uv; dailyvision depends on its plist PATH; parcelcache uses .venv/bin/python. The five plists exist only in ~/Library/LaunchAgents.
- Unverified: the Desktop applet "Run Foreclosure Engine.app" runs `do shell script "bash $HOME/foreclosure-scraper/scripts/gui_run.sh"`, and neither gui_run.sh nor run_local.sh sets PATH. A Finder-launched applet normally gets a minimal PATH without ~/.local/bin, which would reproduce the dailycourt failure. My test of `do shell script` inherited my shell's PATH, so it proved nothing; treat this as a probable defect to check.

Fix (S): declare every imported dependency in pyproject or stop using exact `uv sync` in run_local.sh; add `export PATH="$HOME/.local/bin:/opt/homebrew/bin:$PATH"` and a `command -v uv || exit 127` guard at the top of run_local.sh, gui_run.sh, run_daily_court.sh; copy the plists into the repo under deploy/mac with an install script.

### O13. The next full run is untested on a 170k board and will probably be killed (MEDIUM)

Evidence: the three 8/29 to 8/30 attempts were killed with exit 137 against a 94k-row board. The board is now 1.8 times larger with the same 8 GB. The 9/9 count-guard fix (9747b96) has never run end to end. The launcher used on 8/27 to 8/30 printed "FULL local run", "board_allow_shrink=1 fullrun_persist=1"; that launcher is not in the repo. The current run_local.sh (last committed 9/9) does not set BOARD_ALLOW_SHRINK and has never completed a run. A popup click on Tuesday will start a job that holds the board lock 15 to 57 hours and blocks everything else, on battery power if the laptop is unplugged.

Fix (M): treat the first post-fix run as a supervised test: plug in, close other apps, run a 5 to 10 source sample first, sample memory every 5 minutes into job_events.jsonl, and have a rollback ready (see O5).

### O14. Documentation is stale in ways that mislead (LOW to MEDIUM)

See appendix C1 for the statement-by-statement list. Headline: HANDOFF.md says 42,257 leads (now 170,528), OPERATIONS.md says four jobs and 889 MB on GitHub, MASTER_GAPS says 40,702 leads and an "exactly 18 counties" footprint while the board holds New Hanover (2,230) and Charleston (1,455) rows. CLAUDE.md permits CAPTCHA solving and Cloudflare bypass while MASTER_GAPS rule 2 forbids defeating CAPTCHAs and WAF checks, and run_daily_court.sh enables `TYLER_USE_WAF_SOLVER=1` by default. Two governing documents disagree on the compliance line; the operator should pick one.

---

## (d) What I checked and found sound

- **Board lock protocol.** mkdir-atomic directory lock, stale-break by atomic rename with re-check, reentrancy via env var, implemented in both shell and Python and tested against each other (tests/test_publish_plumbing.py). All five scheduled board jobs and both manual-lane wrappers use it. The live lock at audit time (pid 11347) matches a running process.
- **Count guard.** It did its job four times: refused 68,264 vs 94,384 (9/10), 97,342 vs 115,994 (9/13), 98,805 vs 128,391 (9/14), 39,088 vs 94,384 (9/9). Fails safe. The footprint allowance fix is tested (tests/test_count_guard_footprint.py). High-water is 175,941 (9/15), so an accidental 10% shrink on today's board would still be refused.
- **Per-file atomic writes.** `_atomic_write_bytes` uses PID-named temp files and `os.replace`. The 9/17 disk-full event did not corrupt the live board (verified by the author before and after, per commit 0cd2d26).
- **Backup pruning** was fixed and has a regression test (tests/test_backup_prune.py); backups/ is bounded at 3.7 GB.
- **Publish payload definition** is in one file (board_payload.sh), stages each path separately, and includes "exists or already tracked" rules. All publishers rebase before pushing. At audit time local and origin/main are identical.
- **Pages pipeline.** check_pages_publish.py passes; pages.yml gates the Jekyll prefix trap and measures deploy size. 0 failures in the last 100 deploys.
- **Repo-size watchdog** works: it measured, projected and opened issue #131. The failure is that nobody acted.
- **Timeouts in the scraping path.** The shared http_client sets hard connect, pool and read timeouts (30 s default); every scraper runs under `asyncio.wait_for` with a soft timeout; main.py has phase wall-clock caps (scrape 10,800 s, link validation 600 s, GIS and resolver 2,400 s, court 1,800 s). Of 14 raw `requests/urlopen/httpx.get` call sites in src, 5 lack a timeout argument (I did not trace them). The remaining hang risks are `git push` (O7) and synchronous calls inside async scrapers, which `wait_for` cannot interrupt.
- **Parcel cache refresh.** Verifies expected versus downloaded counts, writes to a temp SQLite file and atomically replaces the old cache; 26 of 26 counties refreshed 9/20 with 0 failures.
- **Daily API refresh safeguards.** It aborts if the merge would shrink the board below 65% of prior, carries over sources that return under 3 rows, and never drops a row on a single miss (4 consecutive misses).
- **Full-run design intent.** caffeinate, per-phase caps, cumulative-board persistence (merge_prior_board) and the shrink allowance are sensible; the problem is that the run has not completed under current conditions.
- **Logs rotate** for daily-vision (14), local-run (12) and court (9) logs; the write_artifact backups rotate; no launchd job is looping (all five show last exit status 0).

---

## (e) What I could not verify

- **What lrcpwa and SOS did on 9/15 to 9/19.** Their logs are in /tmp and the 9/19 13:15 reboot cleared them. Git shows no lrcpwa commit after 9/14 and no SOS commit on 9/16 to 9/19, but "no commit" could mean skipped, ran with no change, or never fired.
- **Why the vision job died on 8/27, 9/7, 9/10 and 9/17** (no exit line). I infer external kill (SIGKILL/OOM, reboot or sleep); I have no log naming the cause. Same for the 9/19 crash.
- **Per-job memory.** Nothing logs RSS. My only sample was misleading (macOS showed 32 MB RSS for a process that had loaded 170k rows because pages were compressed). The 2.8 GB and 20 GB figures are the operator's notes.
- **The 1.1 TB swap figure.** It is derived from `top` cumulative counters since boot; I did not confirm they are not reset by other events.
- **Silent row loss in load_board** (the `except Exception: pass`): count unknown because I did not load the board.
- **Whether PII files are reachable on the live Pages URL.** I did not fetch them. Evidence is repo visibility, tracking and the Jekyll decision function.
- **The Desktop applet's PATH** (O12).
- **HTTP 408 push failures.** I found a sideband disconnect and a DNS failure but no 408 text; the older logs are gone.
- **Whether the 9/21 09:30 job completes.** It was still running when I finished (API phase at dedupe stage, holding the lock).
- **Test suite health.** I did not run tests. HANDOFF's "3201 passed, 2 failed" is unverified; CI only runs on pull requests.
- **sc_parcel_mailing.db and other local databases: whether they can be rebuilt.** I did not open their build scripts.
- **Any off-machine backup** other than Time Machine (I checked installed backup agents and found none). NinjaRMM's scope is unknown.

---

## Appendix C1. Documentation statements that are now false or misleading

### docs/HANDOFF.md (stamped 2026-08-20, file last committed 8/25)

| Statement | What is true now, with evidence |
| --- | --- |
| "~42,257 leads, 29 counties, 95 sources" | 170,528 rows, 156 sources on the board, NC 93,073 and SC 77,455 (run_meta 9/21) |
| "205 scraper modules registered, 24 parallel" | orchestrator.start logged 209 scrapers (8/28); run_local.sh now defaults PARALLEL_SCRAPERS=8 (commit c039888) |
| "Parcel caches cover 14 of 18 counties. 4 blocked: Anderson, Cherokee, Union (SCDOT), Oconee (no bulk)" | The 9/20 refresh log lists 26 county caches including Anderson and Oconee, all OK. Cherokee and Union are not in the refresh list |
| "launchd: 6 jobs active" | 5 loaded (dailyvision, lrcpwa, sosagent, parcelcache, weekly). dailycourt disabled 9/20 after 31 failed runs |
| "Monitor cron foreclosure-enrich-monitor pings every 30 min" | ~/.hermes/cron/jobs.json is `{"jobs": []}` since 8/19 |
| "Pass 8 completed... check /tmp/enrich_pass8.log" | /tmp is cleared at reboot; the file is gone |
| "The TUI session should check with Cash before starting any board-writing process to avoid dual-writer collision" | Advisory only. Enforcement is the board lock, which 54 writers bypass (B4) |
| "doc_ocr: 3,388 PDFs linked, 0 parsed" | Commit 3ba7337 (9/16) ran the first board-wide doc_ocr backfill: 46 rows |
| "Test status: 3201 passed, 50 skipped, 2 failed" | Not re-run; tests/ now has 325 entries and CI runs only on pull requests |
| "Read this first... kept current" | Not updated since 8/25 while the board grew 4x and the full run stopped landing |

### docs/OPERATIONS.md (written 2026-08-11, never revised)

| Statement | What is true now, with evidence |
| --- | --- |
| "Four launchd jobs... You should see four lines" | `launchctl list` shows five com.highway.foreclosure jobs; parcelcache and dailycourt are not documented |
| "Daily 12:00 lrcpwa" and "Daily 14:00 SOS" as reliable daily jobs | They skip whenever the 4 hour vision job holds the lock. No lrcpwa commit since 9/14 |
| "Skipping is normal once; a pattern is not" | The pattern exists and nothing measures it; the skip line lives in /tmp |
| "[Vision] skips itself on Tue and Fri because the weekly full run is a superset" | The full run needs a manual click and last landed 8/29, so those days refresh nothing |
| "Tue/Fri popup... shows a two-step popup... this one is not silent" | It writes no log and cannot record whether it was seen or answered |
| Section 5: run_meta.json "is the ground truth" and 36 hour rule on `run_time` | run_time moves on every write, including manual ones; the per-source health inside is 23 days old |
| "889 MB on GitHub... 43 MB/day... runway about 3 months" | 12.7 GiB on GitHub; issue #131 shows 249.9 MB/day at 7.1 GB on 9/14; about 800 MiB/day since; runway already negative |
| "Per publish at the 38,500-lead board: listings.json.gz 26.6 MB... cadence about 1.3 publishes/day" | listings.json.gz is 84.3 MiB, a publish adds 120 to 180 MB, and 9 to 24 board commits per day on 9/13 to 9/20 |
| "The Mac's .git is about 1.0 GB, 846 MB loose... run git gc" | .git is 18 GB, 13.7 GB loose |
| "Deployed site about 398 MB" | 561.6 MB tracked and published; the 600 MB warning is near |
| Recovery section covers diverged main and a died full run | No procedure for restoring a bad board from history; no backup section |
| Section 6: the ingest lane "takes the board lock, so it cannot collide" | True of ingest_saved.sh; the underlying ingest_publicindex_files.py and ingest_fresh_court_leads.py have no lock of their own |

### docs/MASTER_GAPS_WALLS_AND_MANUAL_LANES.md (2026-08-18)

| Statement | What is true now, with evidence |
| --- | --- |
| "Built against the live committed board (data/checkpoint/board.json.gz, 40,702 leads)" | data/ is gitignored, so that file is not committed. It is a 65 MB checkpoint dated 9/9. The live board is 170,528 rows |
| "Board = 40,702 leads. NC 22,872 / SC 17,830" | 170,528; NC 93,073 / SC 77,455 |
| "The footprint is exactly 18 counties... eastern/coastal NC (New Hanover) DENIED... Every in-scope county has coverage" | by_county_top includes NC/New Hanover 2,230 and SC/Charleston 1,455. config.py added `in_scope_distressed` on 9/15 (a wider distressed-lead scope), and the parcel cache covers Horry, Colleton, Sumter, York, Lexington and others |
| Fill rates: owner_mailing 74.5%, owner_phone 21.4%, parcel 72.5%, real CAMA 32%, equity 30.2%, vision 32.7% | Measured on the 40.7k board. Vision alone is now 22,326 of 170,528 (about 13%) |
| "Board-writer mutex prevents an ingest colliding with a full run" | Only for the writers that use it (B4) |
| Rule 2: defeating a CAPTCHA, login wall, or WAF bot-check "is NOT permitted... even when directed to" | CLAUDE.md "Hard constraints" says CAPTCHA solving, Cloudflare bypass and anti-bot evasion are allowed if free, and run_daily_court.sh sets `TYLER_USE_WAF_SOLVER=1` by default. The two documents contradict each other |
| Currency note: dates "true when probed" | Nothing in the document was re-probed after 8/18 while the source set changed by 15,000+ rows in September |

---

## Appendix C2. Top risks ranked (likelihood x impact) with the smallest fix

Scores are 1 to 5 each; product shown. Likelihood is over the next 30 days.

| Rank | Risk | L | I | Score | Smallest fix |
| --- | --- | --- | --- | --- | --- |
| 1 | O1 board .gz crosses 100 MiB, publishing halts and local history is poisoned | 5 | 5 | 25 | pre-push hook and payload size gate at 95 MiB (1 hour); split or trim the payload (1 to 2 days) |
| 2 | O2 stale data: no full run since 8/29, 98.7% of rows unscheduled, Tue/Fri dead | 5 | 4 | 20 | remove FULL_RUN_DAYS skip (10 minutes); then per-family scheduled merges |
| 3 | O3 unenforced lock and non-atomic payload set: silent mixed or reverted board | 3 | 5 | 15 | write_artifact refuses without the lock; mtime compare at write (half a day) |
| 4 | O7 repo 12.7 GiB and 172 MiB pushes; stalled push under the lock | 4 | 3 | 12 | lowSpeed limits, push outside the lock, batch publishes (1 hour) |
| 5 | O8 public owner PII | 3 | 4 | 12 | untrack outreach_maillist.csv (10 minutes); operator decides on private repo or field trimming |
| 6 | O9 swap thrash, OOM kills, SSD wear | 4 | 3 | 12 | memory gate on lock acquire; log swap deltas; AC power for long runs |
| 7 | O5 no backup: disk loss destroys parcel DBs, CRM state, keys, schedules | 2 | 5 | 10 | Time Machine or nightly copy of a fixed list; restore script (half a day) |
| 8 | O4 stale health hides all of the above | 5 | 2 | 10 | age-stamped health and a 48 hour job-event watcher (half a day) |
| 9 | O6 daily jobs starve each other; vision burns the lock for little | 5 | 2 | 10 | time-box vision, reorder the day (1 hour) |
| 10 | O10 to O13 silent failures, lock gaps, env drift, unproven full run | 3 | 3 | 9 | job event log; PATH guards; declare dependencies; supervised test run |
