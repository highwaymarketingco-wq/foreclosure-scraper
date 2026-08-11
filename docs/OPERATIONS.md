# Operations

How this system runs when nobody is watching it, how to tell when it has quietly
stopped, and what to do about it.

Written 2026-08-11. Every number in here was measured, not estimated; where a
number will drift, the thing that measures it is named so you can re-read it
rather than trust this file.

- Live board: <https://highwaymarketingco-wq.github.io/foreclosure-scraper/>
- Repo: `~/foreclosure-scraper` on the operator's Mac, pushing to `main`

---

## 1. The one-paragraph model

The Mac is the engine. Four `launchd` jobs run on it, each of which loads the
board, changes some part of it, writes it back, commits and pushes. GitHub is
only a delivery mechanism: a push to `main` triggers the Pages workflow, which
builds `docs/` and deploys it. **No data is produced on GitHub.** If the Mac is
asleep, off, or has lost its lock, nothing publishes and nothing complains.

That last sentence is the reason this file exists.

---

## 2. What runs when

All four are user LaunchAgents in `~/Library/LaunchAgents/`. They only fire when
the Mac is awake; if it was asleep at the scheduled time, macOS fires them at
next wake.

| When | Job | Script | Log |
| --- | --- | --- | --- |
| Daily 09:30 (not Tue/Fri) | `com.highway.foreclosure.dailyvision` | `scripts/run_daily_vision.sh` | `logs/dailyvision.{out,err}.log`, `logs/daily-vision-*.log` |
| Daily 12:00 | `com.highway.foreclosure.lrcpwa` | `scripts/lrcpwa_refresh.sh` | `/tmp/lrcpwa_refresh.log` |
| Daily 14:00 | `com.highway.foreclosure.sosagent` | `scripts/sos_agent_refresh.sh` | `/tmp/sos_agent_refresh.log` |
| Tue + Fri 09:30 | `com.highway.foreclosure.weekly` | `scripts/prompt_run.sh` | `logs/launchd.{out,err}.log`, `logs/local-run-*.log` |

Confirm they are loaded:

```sh
launchctl list | grep highway.foreclosure
```

You should see four lines. A `-` in the first column means "not currently
running", which is normal between fires. A non-zero **third** column is the last
exit status and is worth reading.

### What each one publishes

**09:30 daily vision** — `daily_api_refresh.py` then `patch_vision_gemini.py`.
Refreshes API-sourced listings, then spends free Gemini/GitHub-Models/Groq/NIM
quota scoring un-scored listings with photo condition analysis. Commit subjects
look like `daily api refresh: 38500 listings (…)` and
`daily vision: 10317 listings scored (…)`. It **skips itself on Tue and Fri**
because the weekly full run is a superset (`FULL_RUN_DAYS="2 5"`).

**12:00 lrcpwa** — land-records pass against `lrcpwa.ncptscloud.com`: fills
addresses, county values and parcel photos the API rate limit deferred, then
recomputes tags. Commit subject: `Scheduled land-records refresh: …`.

**14:00 SOS agent** — NC Secretary of State registered-agent lookups, ~40 new
LLC-owned leads a day. Commits **only if new contacts actually landed**, because
a Cloudflare-walled run must not create an empty commit. Subject:
`Scheduled SOS pass: …`.

**Tue/Fri 09:30 weekly** — this one is *not* silent. It shows a two-step popup
(see §6), because a silent auto-run was being missed whenever the Mac was asleep
at 09:30. Step 1 offers to ingest manually-saved court pages; step 2 offers to
start the full engine (`scripts/run_local.sh`, several hours).

### On GitHub

| Workflow | Trigger | What it does |
| --- | --- | --- |
| `pages.yml` | every push to `main` | Verifies payloads survive Jekyll, measures the deploy, builds and deploys the site |
| `repo-size.yml` | Mondays 13:00 UTC | Measures repo growth and runway; opens/updates one issue if the runway drops under 120 days |
| `patch-listings.yml`, `patch-run-scrapers.yml` | manual | Targeted re-runs |
| `weekly.yml` | — | **disabled_manually.** The cloud version of the full run. It cannot do the stealth-browser sources, which is why the real run is on the Mac |
| `porsche-refresh.yml` | schedule | Unrelated side project |

`pages.yml` serializes on `concurrency: pages` with `cancel-in-progress: true`,
so overlapping pushes cancel the older deploy rather than colliding. A
**cancelled** Pages run is normal and is not a failure.

---

## 3. The board lock

**The problem it solves.** The critical section is `load_board → mutate →
write_artifact`, and it runs for minutes to hours. The 09:30 vision job can hold
a board for up to 4 hours (`VISION_MAX_SECONDS=14400`), which means it is still
holding a board it loaded at 09:33 when the noon and 2pm jobs fire. On
2026-08-10 the noon pass resolved 1,064 parcels, filled 343 county values and
tagged 410 absentee owners — and the vision job wrote its 09:33 board back at
13:36 and reverted every one of them. **Nothing errored.**

**What it is.** `logs/.board.lock` — a *directory*, because `mkdir` is atomic.
Inside it, `pid` holds two lines: the owner PID and a label.

- Implemented twice, deliberately: `scripts/board_lock.sh` (shell) and
  `board_lock()` in `src/foreclosure_scraper/web_artifact.py` (Python), so a
  shell wrapper and a Python writer contend for the *same* lock.
  `tests/test_publish_plumbing.py` drives the two against each other — changing
  one side alone fails the suite, which is the point.
- **Reentrant** via `FORECLOSURE_BOARD_LOCK_HELD`, so a wrapper holding the lock
  can run a Python writer that also asks for it.
- **Stale locks break automatically**: if the owner PID is dead, the directory is
  `mv`'d aside (atomic, so exactly one racer wins) and removed.
- Not `shlock` (does not break stale locks — one killed run would have stopped
  every scheduled job forever) and not `flock` (does not exist on macOS).

**Normal behaviour when it is held:** the losing job logs
`board-writer active (<pid> <label>) — skipping this run` and exits **0**. A
skipped run is not an error. Two skips in a row for the same job is a signal.

**Inspect it:**

```sh
cat ~/foreclosure-scraper/logs/.board.lock/pid   # "<pid>\n<owner label>"
ps -p "$(head -1 ~/foreclosure-scraper/logs/.board.lock/pid)"
```

If that `ps` shows nothing, the lock is stale and the next job will break it by
itself. Only remove it by hand if you have confirmed the PID is dead **and** a
job is refusing to start:

```sh
rm -rf ~/foreclosure-scraper/logs/.board.lock
```

---

## 4. What a "publish" consists of

`scripts/board_payload.sh` is the single definition, because five publishers were
each keeping their own copy and they had drifted apart. Every path is staged in
its own `git add`, so one bad pathspec cannot void the whole publish.

```
docs/listings.json.gz          docs/run_meta.json
docs/listings_detail.json.gz   docs/run_health.json
docs/listings_slim.json.gz     docs/foreclosure_sold_pool.json
docs/detail_shards/            docs/multifamily.json
docs/parcel_photos/
```

**The join across the payloads is BY ARRAY INDEX**, and it only holds within one
`write_artifact` call. Index `i` of `listings.json` is index `i` of
`listings_detail.json` is record `i % 1000` of `detail_shards/{i//1000:05d}`.
Publishing a fresh board with a stale slim file or stale shards hands one lead's
comps, vision and CAMA to a different lead's address on every phone, while
desktop looks perfect. This is why `_emit_detail_shards` **deletes** the whole
shard directory on any failure rather than leaving it half-written, and why the
shard metadata in `run_meta.json` is omitted in lockstep — absent metadata makes
the client fall back to an honest "open on desktop" note.

`docs/listings.json`, `docs/listings_detail.json` and `docs/listings_slim.json`
are **gitignored** — they exceed GitHub's 100 MB/file limit. Only the `.gz` twins
are committed, and the dashboard fetches those.

### The Jekyll prefix trap

Jekyll's `exclude`/`include` are **prefix** matches, not globs
(`entry.start_with?(pattern)`), so `exclude: listings.json` also drops
`listings.json.gz`. This has silently 404'd the live board **three times**.

The rule: every `- <name>.json` added to `exclude` in `docs/_config.yml` must be
accompanied, *in the same edit*, by `- <name>.json.gz` in `include`.

`scripts/check_pages_publish.py` reimplements Jekyll's decision over the real
contents of `docs/` and fails if any payload would be dropped. It existed for
months with **no caller anywhere in the repo**; it now runs as the first step of
`pages.yml`, on bare `python3` with no dependencies, on purpose — a failed build
leaves the previous deploy live, which is better than shipping data the site
404s on.

Run it after any `_config.yml` edit:

```sh
python3 scripts/check_pages_publish.py
```

---

## 5. Telling whether publishing has silently stopped

This system's characteristic failure is **not** an error. It is a job that exits
0 having done nothing. Four real examples, all of which happened:

1. A job loses a push race, `main` diverges, and every later run stages a diff
   that is already committed, sees an empty staged diff, prints
   `no board changes to commit`, and stops publishing — forever.
2. A board writer silently reverts another's work (§3).
3. A payload file 404s behind the Jekyll prefix rule (§4).
4. The Mac is simply asleep at every scheduled time.

### The 30-second check

The live `run_meta.json` is the ground truth for "what the world can see":

```sh
curl -s https://highwaymarketingco-wq.github.io/foreclosure-scraper/run_meta.json \
  | python3 -c "import json,sys;d=json.load(sys.stdin);print(d['run_time'], d['total'])"
```

If `run_time` is more than ~36 hours old, publishing has stopped. (Three of the
four jobs run daily, so a healthy system moves this at least once a day.)

### Is the Mac ahead of GitHub?

The single highest-value check, because this is failure mode 1:

```sh
cd ~/foreclosure-scraper
git fetch origin main -q
git status -sb | head -1        # "ahead N" means pushes are failing
git log origin/main -1 --format='%h %ad %s' --date=iso
```

`## main...origin/main` with no `ahead`/`behind` is healthy. **`ahead N` is the
alarm** — commits exist locally that never reached GitHub, and every subsequent
run will report "no board changes" because the changes *are* committed, just not
pushed.

### Did each job actually do something?

```sh
tail -20 /tmp/lrcpwa_refresh.log
tail -20 /tmp/sos_agent_refresh.log
tail -40 ~/foreclosure-scraper/logs/dailyvision.out.log
ls -lt ~/foreclosure-scraper/logs/daily-vision-*.log | head -3
```

What you are reading for:

| Log line | Meaning |
| --- | --- |
| `committed + pushed` | healthy |
| `board-writer active (…) — skipping` | normal once; a pattern is not |
| `no board changes to commit` | healthy **only** if `git status -sb` is clean |
| `!! commit made locally but PUSH FAILED — main has diverged, publishing is stopped` | failure mode 1, act now |
| `no new contacts (sosnc.gov may be rate-limited)` | normal for the SOS job |

### Did the deploy succeed?

```sh
gh run list --workflow=pages.yml --limit 5
```

`cancelled` is normal (a newer push superseded it). `failure` is not — read the
run; the most likely cause is `check_pages_publish.py` refusing to ship a board
whose payload would 404, which is the guard doing its job.

The Desktop app **Check Engine Status** (`scripts/run_status.sh`) gives the same
picture in a dialog for the weekly run specifically.

---

## 6. The manual court-page lane

SC PublicIndex and NC eCourts cannot be scraped directly — SC PublicIndex is a
ToS wall and NC eCourts' Smart Search is behind AWS WAF. The workaround is
manual: a human saves the pages, and offline parsers ingest them.

**How it is meant to happen.** The Tue/Fri 09:30 popup (`scripts/prompt_run.sh`)
asks about this *first*, before offering the full run:

- **Step 1** — "If you've saved the latest SC PublicIndex / NC eCourts pages into
  the drop folder, click *Ingest what I saved*." *Open folder + guide* opens
  `~/Desktop/Court Pages (drop here)` and its `_READ ME` guide.
- **Step 2** — "Run the full engine now?" (several hours).

**Doing it by hand,** any time: drop the saved pages into
`~/Desktop/Court Pages (drop here)` and double-click
**Ingest Saved Court Pages.app** (`scripts/ingest_saved.sh`). It scans the drop
folder, the repo root and `~/Downloads`, so wherever you saved them they get
picked up. It is idempotent — the ingesters dedupe by case number, so re-running
never creates duplicates — and it takes the board lock, so it cannot collide with
a scheduled job or a full run.

**Gotcha:** a saved *list* page carries the list, not the detail. If you want
case detail, save the detail pages.

The Desktop apps:

| App | Script | Does |
| --- | --- | --- |
| **Run Foreclosure Engine** | `scripts/gui_run.sh` | Starts the full run, `caffeinate`d so the Mac cannot sleep through it. Safe to press twice — it refuses to start a second run |
| **Ingest Saved Court Pages** | `scripts/ingest_saved.sh` | The lane above |
| **Check Engine Status** | `scripts/run_status.sh` | Plain-English status dialog |

---

## 7. Recovery

**Publishing stopped because `main` diverged** (`git status -sb` says `ahead N`):

```sh
cd ~/foreclosure-scraper
git fetch origin main
git pull --rebase --autostash origin main
git push origin main
```

The three Python publishers and both shell publishers already rebase before
pushing; if you are here, the rebase itself failed (usually a genuine conflict in
a payload file). Payload files are regenerated wholesale, so resolving in favour
of the newest board and re-publishing is correct.

**A job is refusing to start and the lock holder is dead** — see §3.

**The full run died partway:** `scripts/recover_from_checkpoint.py` exists for
this. Do not start a second full run to "catch up"; `gui_run.sh` will refuse
anyway.

**The site 404s its data:** run `python3 scripts/check_pages_publish.py`. If it
fails, `docs/_config.yml` has sprung the prefix trap (§4). If it passes, check
`gh run list --workflow=pages.yml`.

**Never** force-push `main`. The operator's clone is what all four unattended
jobs push from; rewriting history under them stops publishing silently.

---

## 8. Repo size

**The situation, measured 2026-08-11.**

The repo is **889 MB on GitHub**, against a soft limit around **5 GB**. Growth is
**~43 MB/day** over the trailing 21 days (~12 MB/day over 90 days — the recent
figure is inflated by two one-time events, see below). That is a runway of
roughly **3 months at the recent rate**, and it is measured every Monday by
`.github/workflows/repo-size.yml`, which opens a single tracking issue if the
runway drops below 120 days.

**Why it grows, and why it is not what it looks like.** Total unique blob content
across all history is **8.62 GB**, of which `docs/listings.json` alone is
**7.31 GB (84.9%)**. And yet the repo is 889 MB. Both are true, and the gap *is*
the explanation: `listings.json` is plain JSON, so git's delta + zlib compression
collapses 7.3 GB of it into near-nothing. What survives packing roughly 1:1 is
everything incompressible:

| path | lifetime blob bytes | compresses? |
| --- | ---: | --- |
| `docs/listings.json.gz` | 428 MB | no — gzip |
| `docs/parcel_photos/` | 298 MB | no — JPEG (gzip -1 gains 0.2%) |
| `docs/detail_shards/` | 84 MB | no — gzip |
| `docs/listings_detail.json.gz` | 74 MB | no — gzip |
| `docs/listings_slim.json.gz` | 28 MB | no — gzip |
| **sum** | **912 MB** | vs **889 MB** actually on GitHub |

**The `.gz` payloads and the JPEGs are the repository.** Every line of source,
every research document and 7.3 GB of board history round to zero against them.

Per publish, at the current 38,500-lead board:

| file | bytes | churns |
| --- | ---: | --- |
| `listings.json.gz` | 26.6 MB | every publish |
| `listings_slim.json.gz` | 7.8 MB | every publish |
| `listings_detail.json.gz` | 7.6 MB | most publishes |
| `detail_shards/` | 0.6–26.5 MB | 1 shard on a valuation-only republish; all 39 on a vision pass |

So a light publish costs ~43 MB and a heavy one ~69 MB, and the measured cadence
is ~1.3 publishes/day.

### Why the shards were left committed

The obvious idea is to stop committing `detail_shards/` and generate it during
the Pages build instead. It was measured and rejected:

- Shards are **1.0% of lifetime repo bytes** and about **20% of a heavy publish**.
  Moving them to the build saves ~11 MB/publish, which extends the runway by
  roughly **two weeks**. It does not change the shape of the problem;
  `listings.json.gz` alone is half of all growth and is untouched by it.
- The generator (`_shard_record` / `_SHARD_SKIP_RAW` in `web_artifact.py`) is
  **derived from `_SLIM_RAW`** and cannot be imported on bare `python3` — it
  needs `structlog`, `.models` and `.stale_link_fallback`. So the build would
  need either a full `uv sync` on the critical publish path (which today runs
  dependency-free so a PyPI outage cannot stop a deploy), or a **second
  implementation** of the projection.
- That second implementation is the dangerous part. The failure mode is silent:
  the shard merge already shipped 50,459,084 of 216,924,819 bytes (23.3%) as
  unreachable duplicates once, and nothing errored — the detail panel simply
  rendered less. A projector that drifts from the slim allowlist fails exactly
  that way.
- Today a shard defect ships bad shards. With generation in the build, a shard
  defect **fails the build**, and a failed build means no deploy at all.

Two weeks of runway is not worth a second copy of the index-aligned join.

*(For the record, feasibility was not the blocker: decompressing the board takes
0.56 s, and gzip -9 over the whole 229 MB shard body takes 3.2 s. Deriving shards
from the committed `.gz` twins of the **same commit** would also be index-safe by
construction, since it is the same tree. The objection is drift and blast radius,
not time.)*

### What would actually move the number

All of these live in the publisher scripts (`scripts/board_payload.sh` and the
five publishers), not in the Pages build:

1. **Stop retaining history for current-state payloads.** Nobody diffs last
   month's `listings.json.gz`; its history is pure cost. Publishing the payloads
   to an **orphan branch force-pushed to a single rootless commit** each time
   keeps steady-state growth near zero and — critically — keeps all four payloads
   in **one commit**, so the index join is preserved by construction. Pages would
   check out `main` for code and that branch for data.
2. **Release assets instead of git objects.** Same effect, but four separate
   uploads are *not* atomic, so a partial upload mixes payloads from two boards.
   Given what that does on a phone, option 1 is safer.
3. **Periodic history prune** (`git filter-repo` + force-push). Effective and
   fully reversible in principle, but it rewrites history under the operator's
   working clone, which is what all four unattended jobs push from. **Manual
   only, never automated**, and every clone must be re-cloned afterwards.

### Local cleanup (safe, do this first)

The Mac's `.git` is ~1.0 GB, but `git count-objects -vH` shows **846 MB loose**
against only 205 MB packed. Loose objects are neither deltified nor repacked, so
most of that is reclaimable locally without touching GitHub:

```sh
cd ~/foreclosure-scraper
git count-objects -vH     # before
git gc                    # repack; safe, does not rewrite history
git count-objects -vH     # after
```

This changes nothing on GitHub — it only shrinks the working clone.

---

## 9. Deploy size

Separate from repo size, and also worth watching: the **deployed site** is
~398 MB (tracked files only, which is what CI checks out), against **GitHub
Pages' 1 GB published-site limit**.

`pages.yml` now measures this every build and prints a per-entry table to the run
summary, because the hand-written figure in `docs/_config.yml` had been wrong by
~9x for months. It warns at 600 MB and fails at 950 MB. Failing is deliberate at
that point: Pages will not publish a site over 1 GB either way, so failing with a
clear message keeps the last good deploy live.

`docs/parcel_photos/` is 326.6 MB of that 398 MB. It used to be excluded from the
deploy as "not referenced by dashboard.js" — which was wrong. The board
references `parcel_photos/…` **12,115 times** as relative URLs, the writers put
those paths in the exact field the card photo reads
(`tests/test_assessor_photo.py:174` asserts
`raw["zillow"]["photo"] == "parcel_photos/…"`), and roughly 970 of 38,500 leads
were rendering an empty photo box over a real, committed assessor photograph.
Verified against the live site on 2026-08-11: those URLs returned **404**. The
exclusion has been removed.
