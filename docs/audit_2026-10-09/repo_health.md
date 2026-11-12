# Audit 2026-10-09: repo_health

Three things: why GitHub's Tests workflow was red on every push since 2026-10-07, the Mac's stealth
hand-off file running into the repo's 95 MiB commit gate, and a guard that catches both kinds of
size wall before they stop a job.

## 1. What was measured and how

**CI.** `gh run list --workflow Tests` (30 runs) and the job logs through
`gh api repos/<repo>/actions/jobs/<id>/logs` (the `--log-failed` view came back empty). Then a fresh
`git worktree` of d0422771 (origin/main) in a scratch directory, `uv sync --frozen` and Python 3.12.13
as the workflow does, and the suite run there in 10 chunks of about 78 files, one process at a time,
with `TZ=UTC CI=true GITHUB_ACTIONS=true` and no RUN_NETWORK_TESTS / RUN_LIVE.

| run | commit | result |
| --- | --- | --- |
| 37687497571 | 853ceb5c | 4 failed (3 since fixed by d6677be5 and later) |
| 37692291677 to 37825501623 (9 runs) | cc73b284 to b2e8e99f | 1 failed, 11,171 to 11,210 passed, 132 skipped, 509 to 703 s |
| the other runs of 10/7 | | cancelled by the workflow's concurrency group |

All nine failures are the same test:
`tests/test_scraper_revival_2026_09_21.py::test_funeral_rows_are_name_resolver_targets`.

**Hand-off size.** `git log` of `docs/handoff/stealth_leads.json`: 45.9 MB (10/5), 46.0 MB (10/6),
46.1 MB (10/7), 98,406,892 bytes = 93.8 MiB (10/8, 51,730 leads). Pack growth measured with
`git pack-objects` on the real blobs; the sharded layout measured by converting the real 10/7 and
10/8 files in a scratch directory (never committed).

**Tracked files over 40 MiB at HEAD** (`git ls-tree -r -l`): `docs/handoff/stealth_leads.json`
93.8 MiB and `docs/listings_slim.json.gz` 69.7 MiB. Nothing else.

**Pages size** (tracked docs minus the `_config.yml` excludes, Jekyll's prefix rules from
`scripts/check_pages_publish.py`): 858.9 MB at d0422771, 859.2 MB at af83ee6b.

## 2. Defects

### D1. A test depended on a gitignored local database (CI red 2 days)
- Scale: 1 test, every push from 10/7 21:51 UTC to 10/8 18:35 UTC (9 runs).
- Cause: `_is_target` reaches Anderson SC only through the offline assessor roll, and
  `_offline_roll_cfg` returns a backend only when `sc_parcel_mailing.covered_counties()` finds
  `data/sc_parcel_mailing.db`. That file is gitignored and exists only on the Mac, so the test passed
  on every local run and failed on every runner. Not the Python pin, timezone, ordering, timeout
  (job limit 25 min, runs take 9 to 12) or memory.
- Fix: the test pins the roll's presence the way `tests/test_resolve_offline_roll_anderson.py`
  already does, and a new test asserts the documented wall when the roll is absent (Anderson rows are
  not targets). No assertion weakened.
- Proof: in the fresh worktree the test failed before (1 failed, 37 passed) and passes after
  (39 passed). The full suite at af83ee6b plus the fix, in that worktree: 11,597 passed, 66 skipped,
  1 failed, peak RSS 959 MB per chunk. The one failure is
  `test_geocode_backfill_hard_timeout.py::test_sigint_kills_a_hung_sync_census_call_within_a_few_seconds`,
  a 5-second SIGINT timing test. It passed in all 9 CI runs and in 2 of 2 reruns here, so it is load
  on this Mac (5.9 of 7 GB swap in use), not a CI defect.
- Invariant: `ci` in `scripts/prerun_gate.py`. It reads the Tests workflow result for the pinned
  commit with `gh` and fails the gate when that run failed. Checked live: it returns FAIL for
  b2e8e99f (run 37825501623). The local `tests` check could not catch this because it runs on the
  machine that has the database.

### D2. The stealth hand-off was one file 1.2 MiB under the commit gate
- Scale: 1 file, 51,730 leads from 40 sources. It doubled in one day (liensnc 11,483 and eCourts
  lis pendens 27,407 leads).
- Cause: `scripts/run_stealth_sources.py` wrote every lead into one JSON file. The pre-commit gate
  (`scripts/git_size_gate.sh`) refuses 95 MiB. The writer prints a line and exits 0 when its commit
  fails, so the VM would have kept ingesting an older file.
- Fix: `src/foreclosure_scraper/stealth_handoff_store.py` defines a new layout,
  `docs/handoff/stealth_leads/manifest.json` plus `<scraper slug>.<NNN>.jsonl`:
  - one JSON line per lead, and one producing scraper per shard
  - a 20 MiB cap per shard
  - a sha256 for each shard in the manifest
  - an atomic directory swap
  - the writer deletes the legacy file in the same commit

  The VM reader (`national.stealth_handoff`, which `scripts/ingest_stealth_handoff.py` also uses)
  reads the manifest first and falls back to the legacy file. If both exist it reads whichever is
  newer. A missing or corrupt shard sets PARTIAL and the rest still ingest.

  The writer now commits with a pathspec, so anything else staged in the working tree stays out of
  the hand-off commit. Updated to match: `prerun_gate` (handoff age), `run_profile.json`,
  `canary_run` excludes, `vm_lib.sh` (`vm_handoff_note`) and the docs.
- On the real 10/8 data: 34 shards, the largest 20.0 MiB, 88.0 MiB in total.
- Why plain JSON and not gzip: git compresses blobs and stores plain text as deltas against the
  previous version; gzip output does not delta. Pack growth from 10/7 to 10/8 was 4.12 MB for the
  single file and 3.98 MB for the shards. The 10/8 gzip is 6.36 MB, all of it new every day. For a
  quieter day (10/6 to 10/7) the delta was 0.81 MB against a 3.1 MB gzip. The reader also accepts
  `.jsonl.gz` (writer flag `HANDOFF_SHARD_GZIP=1`).
- Tests: `tests/test_stealth_handoff.py`, 12 new, all with made-up rows. They cover:
  - the round trip and the shard cap
  - stale shards removed and the legacy file deleted
  - legacy fallback and newer-wins
  - missing, tampered and path-traversal shards
  - an unreadable manifest
  - gzip shards, and freshness read from the manifest
  - the writer's `main()` end to end with fake scrapers
  - the pathspec commit and push into a throwaway repo with a bare origin
- Invariant: `repo-size` (below).

### D3. Size walls were found only after they had stopped something
- Fix: `scripts/repo_size_check.py`, standard library only, reads the committed tree with
  `git ls-tree`. It fails when a tracked file is over 90 MiB or the Pages site is over 900 MB. It
  lists files over 40 MiB and warns when the site is over 800 MB. It runs in three places:
  - CI: a separate `repo-size` job in `.github/workflows/tests.yml`
  - the pre-run gate: the `repo-size` check
  - by hand: `python3 scripts/repo_size_check.py`

  Limits are in `run_profile.json` under `repo_size`.
- Tests: `tests/test_repo_size_check.py` (13 tests).
- Current verdict at HEAD: FAIL on the legacy `stealth_leads.json` (93.8 MiB) until the first
  sharded hand-off deletes it. Also WARN for `listings_slim.json.gz` (69.7 MiB) and the 859 MB site.

## 3. Open items
- **`docs/handoff/verification/tax_lien.json` will cross the gate (not done: owner decision
  needed).**
  - Growth: 0.69 MB (10/7 14:14), 4.9 MB (10/7 18:37), 13.3 MB committed (10/8 14:35), and
    20.1 MB in the working tree now (13,165 entries at 1,529 bytes each).
  - The sweep running now selects 12,500 rows out of 71,592 board rows the tax_lien verifier applies
    to. At today's entry size full coverage could reach about 104 MiB (less where several rows of
    one property share an entry), and the file crosses 90 MiB at about 61,700 entries. That is roughly 3 more sweeps of this size after the current one, sooner as
    rechecks grow `history`.
  - Proposed fix, the same pattern as the hand-off: `Ledger.save` writes
    `verification/<signal>/<bucket>.jsonl`, with the bucket a stable hash of the entry key (32
    buckets) so each entry stays in the same shard and deltas stay small. `Ledger.load_file` and
    `load_all` read both layouts, `publish_ledgers` does `git add -A` on the directory, and
    `prerun_gate.check_ledgers` globs both.
  - Not implemented: this audit's rules put `docs/handoff/verification/*` off limits, a sweep is
    writing it right now, and the module belongs to the verification work. The guard warns at
    40 MiB, which this sweep will reach or come close to, and fails at 90 MiB.
- **The first sharded hand-off has not run.** It runs at the next 06:00 launchd job; the real job
  was not run here.
- **`docs/listings_slim.json.gz` (69.7 MiB)** is the next per-file risk. It is published to Pages,
  so it cannot simply be excluded.

## 4. Outside this area
- **The 06:00 hand-off job pushes everything.** It runs `git push origin main`, which sends every
  local commit on the Mac's `main`, including other agents' unpushed local commits. The
  verification ledger publisher (`publish_ledgers`) does the same.
- **`pull --rebase --autostash` unstages work.** It hands staged changes back unstaged, so anyone's
  staged work in this tree is unstaged after a hand-off or ledger publish.
- **Two ruff errors in lines this work did not touch:** `scripts/canary_run.py:307` (F541) and
  `tests/test_scraper_revival_2026_09_21.py:9` (F401).
- **GitHub Actions runner changes:**
  - `actions/checkout@v4` and `astral-sh/setup-uv@v3` run on the deprecated Node 20.
  - `ubuntu-latest` moves to Ubuntu 26 on 2026-10-19.
  - The uv cache restore fails with a 400.
