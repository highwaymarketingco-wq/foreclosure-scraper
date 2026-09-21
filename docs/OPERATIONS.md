# Operations

How this system runs when nobody is watching it, how to tell when it has quietly stopped, and what to do about it.

Rewritten 2026-09-21 against the operations audit (`docs/audit_operations_2026-09-21.md`) and the fixes in `docs/ops_fixes_2026-09-21.md`. The 2026-08-11 edition had drifted: it described four jobs and a 38,500-lead board. Numbers here were measured on 2026-09-21 (board and job facts from `docs/run_meta.json`, `launchctl` and the job logs; repo and site sizes from the audit); where a number will drift, the thing that measures it is named so you can re-read it rather than trust this file.

- Live board: <https://highwaymarketingco-wq.github.io/foreclosure-scraper/>
- Repo: `~/foreclosure-scraper` on the operator's Mac, pushing to `main`
- Restore procedure: [`RESTORE.md`](RESTORE.md)

Some parts below describe files that exist in the working tree but are **not installed yet** (the plist templates, the family jobs, the backup). Each says so.

---

## 1. The model

The Mac is the engine. Scheduled `launchd` jobs load the board, change some part of it, write it back, commit and push. GitHub is only a delivery mechanism: a push to `main` triggers the Pages workflow, which builds `docs/` and deploys it. **No data is produced on GitHub.** If the Mac is asleep, off, or has lost its lock, nothing publishes and nothing complains, which is why section 5 exists.

The board on 2026-09-21: **170,066 leads** (NC 93,030, SC 77,036) from **156 sources**, in `docs/listings.json` (about 1.1 GB, gitignored), its `.gz` twin (84.0 MiB), a 171-file shard set and a slim phone payload. Of those leads, about 2,200 come from the 14 sources any scheduler refreshes daily; the other 98%+ came from the last full run (8/28 to 8/29) or from hand-run ingest scripts. That is the reason for the per-family jobs in section 2.

---

## 2. What runs when

### Installed today (five LaunchAgents in `~/Library/LaunchAgents/`)

`launchctl list | grep highway.foreclosure` shows five. A `-` in the first column means "not currently running"; a non-zero third column is the last exit status. The plists are recorded verbatim in `deploy/mac/installed-2026-09-21/`.

| When | Job | Script | Notes |
| --- | --- | --- | --- |
| Daily 09:30 (not Tue/Fri until the patch is applied) | `com.highway.foreclosure.dailyvision` | `scripts/run_daily_vision.sh` | API refresh of 14 sources, then vision. Logs `logs/dailyvision.{out,err}.log`, `logs/daily-vision-*.log` |
| Daily 12:00 | `com.highway.foreclosure.lrcpwa` | `scripts/lrcpwa_refresh.sh` | NC land-records addresses, values, photos |
| Daily 14:00 | `com.highway.foreclosure.sosagent` | `scripts/sos_agent_refresh.sh` | NC SOS registered-agent contacts, about 40 a day |
| Sunday 04:00 | `com.highway.foreclosure.parcelcache` | `scripts/parcel_cache_refresh.sh` | Rebuilds 26 county parcel caches in `data/parcel_cache`; does not touch the board |
| Tue and Fri 09:30 | `com.highway.foreclosure.weekly` | `scripts/prompt_run.sh` | A two-step popup: ingest saved court pages, then offer the full run. Does nothing unless a human answers |

`dailycourt` (02:00, per-case court detail) was **disabled on 2026-09-20** (`com.highway.foreclosure.dailycourt.plist.disabled-2026-09-20`). It had failed 31 of 31 logged runs with exit 127, "uv: command not found", because its plist PATH lacked `~/.local/bin`. It has no template and will not come back by accident.

### The schedule after the templates are applied (not installed)

`deploy/mac/*.plist` are templates with `__ROOT__` and `__HOME__` placeholders. `scripts/install_launchd.sh` renders them; with no flags it only prints a diff per job. They change the day so the jobs that produce contact data stop losing to a four-hour vision job:

| Time | Job |
| --- | --- |
| 01:00 Mon, Thu | `family-nc-tax`: NC delinquent-tax family merge |
| 01:30 Tue, Fri | `family-sc-tax`: SC delinquent-tax family merge |
| 03:00 daily | `family-nc-ecourts`: NC eCourts judgments |
| 04:00 Sun | `parcelcache` |
| 05:30 daily | `backup`: nightly copy of the local-only state |
| **08:00 daily** | `lrcpwa` (was 12:00) |
| **08:30 daily** | `sosagent` (was 14:00) |
| 09:30 daily | `dailyvision`: API refresh, then vision boxed to 90 minutes |
| 09:30 Tue, Fri | `weekly` popup |
| 23:00 Wed | `family-qpaybill`: qPayBill SC delinquent roll |
| hourly | `jobwatch`: alerts when a job stops reporting (section 5) |

Each family job scrapes with no lock and takes the board lock only for the merge (`scripts/family_merge.py`, `scripts/family_common.sh`). Every plist sets `BOARD_MEM_GATE=warn` (section 3) and sends launchd output to `logs/`.

### What each one publishes

Commit subjects: `daily api refresh: N listings (date)`, `daily vision: N listings scored (date)`, `Scheduled land-records refresh: ...`, `Scheduled SOS pass: ...`, `Scheduled family merge (nc_tax): N rows staged`, `local run: refresh dashboard data (date)`. The SOS and family jobs commit only when a payload file other than `run_meta.json` changed, so a walled or empty run makes no empty commit.

### The full run

`scripts/run_local.sh` (several hours, 15 to 57 on record) is started from the Tue/Fri popup or the Desktop app **Run Foreclosure Engine** (`scripts/gui_run.sh`). **The last full run to land on the board was 2026-08-28 to 8/29.** Three attempts on 8/29 to 8/30 were killed (exit 137) and the 9/8 run wrote nothing (the count guard refused it). The 9/9 guard fix has never been exercised end to end, and the board is now 1.8 times larger on the same 8 GB. Treat the next one as a supervised test: plugged in, other apps closed. It now exits non-zero when the board write fails (3), when no `web_artifact.written` event exists (4), on a busy lock (75), and refuses to run without `uv` (127).

### On GitHub

| Workflow | Trigger | What it does |
| --- | --- | --- |
| `pages.yml` | every push to `main` | Verifies payloads survive Jekyll, measures the deploy, builds and deploys |
| `repo-size.yml` | Mondays 13:00 UTC | Measures repo growth; opens one issue (#131, opened 9/14, no comment as of 9/21) |
| `patch-listings.yml`, `patch-run-scrapers.yml` | manual | Targeted re-runs |
| `weekly.yml` | | **disabled_manually.** The cloud full run cannot do the stealth-browser sources |
| `porsche-refresh.yml` | schedule | Unrelated side project |
| `Tests` | pull requests only | No job tests a push to `main` |

`pages.yml` serializes on `concurrency: pages` with `cancel-in-progress: true`; a **cancelled** Pages run is normal.

---

## 3. The board lock, the memory gate and the job log

### The lock

**The problem.** The critical section is `load_board -> mutate -> write_artifact` and it runs for minutes to hours. On 2026-08-10 the noon pass resolved 1,064 parcels, filled 343 county values and tagged 410 absentee owners, and the vision job wrote its 09:33 board back at 13:36 and reverted all of it. Nothing errored.

**The lock is enforced, not advisory.** `write_artifact` refuses (`BoardLockNotHeld`) unless the process holds the lock, and refuses (`BoardChangedSinceLoad`) when `listings.json` changed after it loaded it. Before 2026-09-21, 54 board-writing modules never took it. To run one of them:

```sh
scripts/with_board_lock.sh <name> -- uv run python scripts/<script>.py
```

It exits 75 when a live writer holds the lock. `BOARD_LOCK_BYPASS=1` is the explicit escape for tests and one-off tools; a docs directory that is not the live one needs nothing.

**What the lock is.** `logs/.board.lock`, a directory (`mkdir` is atomic). `pid` has six lines: pid, owner label, start epoch, heartbeat epoch, max runtime in seconds, token. `children/<pid>` lists writers running inside a wrapper's lock. Implemented twice, `scripts/board_lock.sh` and `board_lock()` in `src/foreclosure_scraper/web_artifact.py`, held together by tests that run each against the other.

**Rules:**

- **Reentrant** through `FORECLOSURE_BOARD_LOCK_HELD`: a wrapper's Python child proceeds inside its lock. The child registers itself in `children/` so the lock survives a killed wrapper.
- **Stale** when the owner and every registered child are dead, or when a **live** holder is older than its declared max runtime plus 30 minutes (default 6 h; the full run declares 72 h, the daily job 4 h). A stale lock is broken automatically and logged as a `lock_break` job event. A hung holder that is fenced out cannot write: `FORECLOSURE_BOARD_LOCK_TOKEN` must match the token on disk.
- **The heartbeat** (line 4 of `pid`, every 60 s) is diagnostic. A quiet heartbeat is not staleness: a 1.1 GB JSON parse holds the GIL long enough on this Mac.
- A losing job logs `board-writer active (<pid> <label>) - skipping` and exits 0, and writes a `skipped_lock` job event. One skip is normal; a pattern is a signal.
- Long manual sessions (a divorce backfill, a resolver campaign) hold the lock for hours and starve the schedulers with no alarm. Pass a `max_runtime` that says so, and expect the schedulers to skip.

**Inspect it:**

```sh
cat ~/foreclosure-scraper/logs/.board.lock/pid       # pid, owner, start, heartbeat, max runtime, token
ps -p "$(head -1 ~/foreclosure-scraper/logs/.board.lock/pid)"
```

If `ps` shows nothing the lock is stale and the next job breaks it. Remove it by hand (`rm -rf ~/foreclosure-scraper/logs/.board.lock`) only after confirming the PID is dead and a job is refusing to start.

### The memory gate

Before taking the lock, `board_lock_acquire` (shell) and `board_lock()` (Python) check swap and free RAM: swap used above 3,072 MB, or free plus inactive below 1,024 MB. `BOARD_MEM_GATE` is `warn` (default: log a `mem_gate` job event and proceed), `enforce` (wait up to `BOARD_MEM_GATE_WAIT`, 900 s, then refuse with exit code 2 and a `skipped_memory` event) or `off`. It defaults to `warn` because this Mac reads 6,300 to 7,200 MB of swap used with a single job running, so the specified thresholds would refuse every job every day. Read the `mem_gate` lines for a week, choose thresholds the machine can meet (`BOARD_GATE_SWAP_MB`, `BOARD_GATE_FREE_MB`), then set `enforce` in the plists.

### The job log

Every scheduled wrapper appends one JSON line to `logs/job_events.jsonl`: `job`, `start`, `end`, `outcome` (`ok`, `no_change`, `skipped_lock`, `skipped_memory`, `failed`, `push_failed`), `rows_changed`, `duration_s`, swap-out delta and peak RSS. Lock breaks, skips and gate decisions are `kind: "note"` lines. Read it:

```sh
tail -20 ~/foreclosure-scraper/logs/job_events.jsonl
/usr/bin/python3 ~/foreclosure-scraper/scripts/job_watch.py --report
```

Job logs live in `logs/` (the audit found `lrcpwa`, `sosagent` and `parcelcache` writing to /tmp, which a reboot empties).

---

## 4. What a "publish" consists of

`scripts/board_payload.sh` is the single definition. Every path is staged in its own `git add`, so one bad pathspec cannot void the whole publish.

```
docs/listings.json.gz          docs/board.manifest.json
docs/listings_detail.json.gz   docs/run_meta.json
docs/listings_slim.json.gz     docs/run_health.json
docs/detail_shards/            docs/foreclosure_sold_pool.json
docs/parcel_photos/            docs/multifamily.json
```

**The join across the payloads is BY ARRAY INDEX**, and only holds within one `write_artifact` call. Index `i` of `listings.json` is index `i` of `listings_detail.json` is record `i % 1000` of `detail_shards/{i//1000:05d}`. Publishing a fresh board beside a stale slim file or stale shards hands one lead's comps, vision and CAMA to another lead's address on every phone while desktop looks perfect.

**The manifest seals the set.** `write_artifact` writes `docs/board.manifest.json` last: size, sha256 and record count of every payload file. `load_board` and `read_board_json` verify the file they read against it, refuse the plain-over-gz preference when the plain file disagrees, and raise `BoardIntegrityError` when neither twin matches (a torn or mixed set). A publisher that stages the payload without the manifest leaves a stale one committed; stage with `board_payload_add`, or add `docs/board.manifest.json`. Check with `scripts/board_manifest.py --verify`; re-seal after checking with `--rebuild`. `BOARD_MANIFEST_SKIP=1` loads without checking.

`docs/listings.json`, `listings_detail.json` and `listings_slim.json` are **gitignored** (over GitHub's 100 MB limit). Only the `.gz` twins are committed.

### Pushing

The lock protects the write and the commit, not the network. Publishers commit inside the lock, release it, then push (`scripts/publish_helper.sh`, `src/foreclosure_scraper/publish.py`): `timeout 900` (macOS has no `timeout`; `scripts/run_timeout.pl` is the portable one), three attempts with 30 s, 90 s, 180 s back-off, a rebase only under a brief re-acquired lock, and `http.lowSpeedLimit 1000` with `http.lowSpeedTime 120` in the repo's local git config. A failed push is a `push_failed` event and the commit stays local; the next publisher's push carries it.

### Size gate

`listings.json.gz` was 34 MiB on 8/26 and **84.0 MiB on 9/21** (GitHub's hard limit is 100 MiB, warning at 50). `scripts/git_size_gate.sh` (a pre-commit hook) blocks a commit at 95 MiB; `scripts/check_payload_size.py` reports every payload file against the limits, and the hourly watcher alerts above 80 MiB. The payload split is still open.

### The Jekyll prefix trap

Jekyll's `exclude`/`include` are **prefix** matches, so `exclude: listings.json` also drops `listings.json.gz`. This 404'd the live data **three times**. Every `- <name>.json` added to `exclude` in `docs/_config.yml` needs `- <name>.json.gz` in `include` in the same edit. `scripts/check_pages_publish.py` reimplements Jekyll's decision and runs first in `pages.yml` on bare `python3`. Run it after any `_config.yml` edit.

---

## 5. Telling whether publishing has silently stopped

This system's characteristic failure is a job that exits 0 having done nothing. Real examples: a lost push race leaves `main` diverged and every later run reports "no changes"; a writer silently reverts another's work (section 3); a payload 404s behind the Jekyll rule; a job is skipped for days because vision held the lock (lrcpwa had no commit from 9/14 to 9/21); a job fails 31 days with exit 127 (dailycourt).

**The watcher** (`scripts/job_watch.py`, template `deploy/mac/com.highway.foreclosure.jobwatch.plist`, **not installed yet**) reads `logs/job_events.jsonl` and alerts, as a macOS notification and a line in `logs/job_alerts.log`, when a job has no `ok` or `no_change` in 48 hours (200 for weekly jobs, 240 for the full run), when its last three runs all failed, or when a payload nears 100 MiB. Until it is installed, do the checks by hand:

```sh
# 1. What the world can see. run_time older than ~36 h means publishing has stopped.
curl -s https://highwaymarketingco-wq.github.io/foreclosure-scraper/run_meta.json \
  | python3 -c "import json,sys;d=json.load(sys.stdin);print(d['run_time'], d['total'], d.get('health_age_hours'))"

# 2. Is the Mac ahead of GitHub? "ahead N" means pushes are failing.
cd ~/foreclosure-scraper && git fetch origin main -q && git status -sb | head -1

# 3. Did each job do something?
tail -20 ~/foreclosure-scraper/logs/job_events.jsonl
tail -20 ~/foreclosure-scraper/logs/lrcpwa_refresh.log ~/foreclosure-scraper/logs/sos_agent_refresh.log
ls -lt ~/foreclosure-scraper/logs/daily-vision-*.log | head -3

# 4. Did the deploy succeed? "cancelled" is normal.
gh run list --workflow=pages.yml --limit 5
```

**`run_meta.json` is not proof of health.** Its `run_time` moves on every write, including manual ones. What it says about sources is labelled by age since 2026-09-21: `health_as_of` (when `source_status` was computed), `health_age_hours`, `health_stale`. When the age exceeds 48 hours `source_status` and `errors` are `null` ("unknown"), not carried as if current. `source_last_success` is the per-source last successful refresh; row `last_seen` is not a freshness measure (a merge bumps it).

Log lines to read:

| Log line | Meaning |
| --- | --- |
| `committed + pushed` | healthy |
| `board-writer active (...) - skipping` / `memory gate refused` | normal once; a pattern is not |
| `no board changes to commit` | healthy only if `git status -sb` is clean |
| `!! commit made locally but PUSH FAILED` | push_failed; the next publisher carries it; check `git status -sb` |
| `!! COUNT GUARD ...`, `SCORE_BOARD_FAILED`, `carried over` | the daily job's loud failures (after the patch); the job exits 4 |

---

## 6. The manual court-page lane

SC PublicIndex and NC eCourts Smart Search are behind a ToS wall and AWS WAF (a wall as defined in `CLAUDE.md`). The workaround is manual: a human saves the pages, offline parsers ingest them. The Tue/Fri popup asks about this first. Or drop pages into `~/Desktop/Court Pages (drop here)` and run **Ingest Saved Court Pages.app** (`scripts/ingest_saved.sh`): it scans the drop folder, the repo root and `~/Downloads`, is idempotent (dedupes by case number), and takes the board lock with a 2 hour max runtime. A saved *list* page carries the list, not the detail.

The popup now logs every decision to `logs/prompt_run.log` and writes a `prompt_run` job event (`no_change` with `declined`, `popup_unanswered` or `run_already_active`; `ok` with `full_run_started`).

| App | Script | Does |
| --- | --- | --- |
| **Run Foreclosure Engine** | `scripts/gui_run.sh` | Starts the full run under `caffeinate`. Refuses a second run. Reports exit 75 (board busy) and 127 (no `uv`) in plain words |
| **Ingest Saved Court Pages** | `scripts/ingest_saved.sh` | The lane above |
| **Check Engine Status** | `scripts/run_status.sh` | Plain-English status dialog for the weekly run |

---

## 7. Recovery

**Publishing stopped because `main` diverged** (`git status -sb` says `ahead N`): `git fetch origin main && git pull --rebase --autostash origin main && git push origin main`. Payload files are regenerated wholesale, so resolving in favour of the newest board is correct. Never force-push `main`; the operator's clone is what every job pushes from.

**A bad board, or `BoardIntegrityError`:** `scripts/restore_board.sh <commit>`. Full procedure, backups and the encrypted secrets archive: [`RESTORE.md`](RESTORE.md).

**A job refuses to start and the holder is dead:** section 3.

**The full run died partway:** `scripts/recover_from_checkpoint.py` exists for this. Do not start a second full run; `gui_run.sh` will refuse anyway. A run that failed its board write or its scoring exits non-zero and keeps its checkpoint (`data/checkpoint`).

**The site 404s its data:** `python3 scripts/check_pages_publish.py`; if it passes, `gh run list --workflow=pages.yml`.

**Backups.** `scripts/backup_local_state.sh` (template `deploy/mac/com.highway.foreclosure.backup.plist`, **not installed**) copies the local-only state nightly with a 7-day rotation. As of 2026-09-21 Time Machine has no destination and nothing else is backed up; see `RESTORE.md`.

---

## 8. Repo size

Measured 2026-09-21 by the audit (`gh api`): **12.7 GiB** on GitHub against the watchdog's 5 GB soft limit, up from 889 MB on 2026-08-11. Issue #131 (opened 9/14 at 7,115 MB, growth 249.9 MB/day) has no comment; growth since is about 800 MiB a day. The local `.git` is 18 GB, 13.7 GB of it loose objects (`git gc` repacks it; it touches no history). One publish of the current board adds **118 to 172 MiB** of new objects (listings.json.gz 84 MiB, slim 31 MiB, about 100 changed shards 54 MiB), and there were 9 to 24 board commits a day on 9/13 to 9/20.

Why it grows: the `.gz` payloads are incompressible and every publish rewrites them; history retains every one. The 8/11 analysis still holds in shape (the `.gz` files and JPEGs are the repository; 7 GB of plain-JSON history compresses to almost nothing), but not in scale.

What would move the number (all in the publishers, not the Pages build): (1) publish the payloads to one force-pushed orphan branch so history stops growing and all four payloads stay in one commit (the join is preserved by construction); (2) release assets (not atomic; a partial upload mixes boards); (3) a one-time `git filter-repo` on a fresh clone, manual only. Cheap now: batch manual sessions to at most one board commit an hour, delete the stale `bot/porsche-refresh-*` branches (about 125 of 149), and act on or close issue #131.

**Deployed site** (`pages.yml` measures it every build): **561.6 MB** of tracked published files on 9/21 (parcel_photos 326.6, listings.json.gz 88.4, detail_shards 69.2, slim 32.5, detail 16.5, handoff 12.3, outreach_maillist.csv 5.9). It warns at 600 MB and fails the build at 950 MB. `scripts/check_payload_size.py` prints the same figure.

**Public repo and PII.** The repo is public, the full board carries `owner_email` on 78,504 rows, and `docs/outreach_maillist.csv` (owner, mailing address, phone) is tracked and deployed although `.gitignore` lists it. This is open and needs an owner decision (audit O8).
