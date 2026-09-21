# Payload split, 2026-09-21 (audit O1)

`docs/listings.json.gz` was 84 MiB (88,098,890 bytes, 170,066 rows), growing 2 to 4 MiB a day and about 8 MiB when a county source lands, against GitHub's 100 MiB per-file limit and the repo's 95 MiB pre-commit gate (`scripts/git_size_gate.sh`). Publishing would have stopped within days. The board is now published as **N independently gzipped JSON-array parts, each under 24 MiB**. This is built and tested on branch `payload-split` (worktree `/Users/cashhigh/foreclosure-worktrees/payload-split`); nothing was run against the real repo, the real board or the network.

Style: no em dashes. Nothing here loads the real board, pushes, or touches the real `docs/`.

## 1. Design

### Layout

```
docs/listings_part_000.json.gz   rows [0, n0)
docs/listings_part_001.json.gz   rows [n0, n0 + n1)
...
```

Each part is a complete gzip of a complete JSON array (`[row, row, ...]`, separator `, ` exactly as `json.dumps` writes it). Concatenating the parts' arrays in name order is exactly the array the single file held. **Row order is the contract**: index `i` joins `listings`, `listings_detail`, `listings_slim` and `detail_shards`, and a part boundary never moves a row.

The single `docs/listings.json.gz` is no longer written or staged. The plain `docs/listings.json` (gitignored, about 1.1 GB) stays as the local working copy, byte-identical to what `json.dumps` of the payload produced (it is now streamed row by row, so the 1.1 GB document is never one string). A stale single file left in the tree is never rewritten or deleted by `write_artifact`; every reader ignores it once the manifest lists parts; `check_payload_size.py` warns until it is `git rm`'d.

### Naming (Jekyll and the Worker)

`listings_part_NNN.json.gz`: three digits, growing to four past 999. Jekyll's `exclude`/`include` are prefix matches (`docs/OPERATIONS.md` section 4). The excluded names are `listings.json`, `listings_detail.json` and `listings_slim.json`; none is a prefix of `listings_part_`, so the parts publish with no `include`. `docs/_config.yml` still gets `- listings_part_` (a prefix, on purpose: the count grows) so a future `exclude: listings_` cannot 404 the board. `scripts/check_pages_publish.py` requires every part on disk, simulates part 000, and its test now also fails an `exclude` of `listings_part_` or `listings_p`. The Worker matches `^/listings_part_\d{3,4}\.json\.gz$` exactly (`worker/src/routes.js`); `/listings_part_000.json` (plain) is denied by the existing uncompressed-listings rule.

### The list of parts (recorded twice)

* `docs/board.manifest.json`, `parts`: `{schema: "board-parts-v1", count, records, max_bytes, rows_per_part, files: [{name, start, end, records, bytes, sha256}]}`. Every part is also a `files` entry (size, sha256, records, start, end). The legacy `files["listings.json.gz"]` entry exists only for a board with no parts.
* `docs/run_meta.json`, `board_parts`: the same block. The dashboard reads this copy (top level, like `detail_count`; the `board` block's key set is pinned by tests).

The manifest is still sealed **last**. Readers verify against it.

### Part sizing (`board_parts.write_parts`, `PART_MAX_BYTES = 24 MiB`)

* Rows per part comes from the compression ratio measured on contiguous sample chunks, aimed at 80% of the cap, rounded down to a multiple of 500, and **kept equal to the previous write's value** while the estimate stays within 0.75x to 1.20x of it, so boundaries stay put from one write to the next. A change confined to some rows then rewrites only the parts that hold them (git stores an unchanged part once). Deterministic gzip (`mtime=0`).
* Whatever the estimate says, **every part is compressed and measured**. A part over the cap is cut to the rows that fit (94% safety) and the rest moves to the next part, so the cap is never exceeded. A single row that alone exceeds the cap raises `PartTooLargeError`.
* On the real board (518 compressed bytes per row) the estimate is about 38,500 rows per part: four parts of about 19 MiB and a fifth of about 8 MiB, growing into a sixth about every 4 to 8 days. Not measured on the real board (section 6).
* `PART_MAX_BYTES` is a module constant; `BOARD_PART_MAX_BYTES` overrides it at import. Code reads `board_parts.PART_MAX_BYTES` at call time (tests patch it).

### One helper module: `src/foreclosure_scraper/board_parts.py`

Stdlib only, Python 3.9 compatible, imports nothing from the package. `check_staged_parts.py`, `check_pages_publish.py`-style bare-python scripts load it by file path. It owns: names and listing (`list_part_files`), the parts block (`normalize_entries`, `make_block`), resolution and verification (`resolve`, `verify_dir`), streaming reads (`iter_gz_rows`, `iter_rows`, `iter_row_texts`), whole reads (`read_rows`), and the writer (`write_parts`, `remove_stale_parts`). `BoardIntegrityError` is defined here and re-exported by `web_artifact`.

### Reading rules (never read a half-written set)

`resolve(docs)`:

1. Manifest with a `parts` block: authoritative. Every part must exist with the recorded size and sha256 (cached per file mtime), else `BoardIntegrityError`. Extra part files the manifest does not name are ignored by readers and reported by `verify_manifest`, `verify_dir` and `check_payload_size.py`.
2. Manifest **without** a parts block (a pre-split manifest): legacy single-file rules; parts on disk are not consulted.
3. No manifest (lost, or `BOARD_MANIFEST_SKIP=1`): `run_meta.board_parts` is the listing, verified the same way. `write_artifact` writes it after the last part.
4. No listing anywhere: `UnlistedPartsError` (a `BoardIntegrityError`). A part directory can be a finished board or the first four of seven; without a listing it is not read. A caller that holds a complete single `listings.json.gz` falls back to it (the last consistent board). `BOARD_PARTS_ALLOW_UNLISTED=1` reads contiguous parts unverified.

`web_artifact._choose_listings_source`: the plain `listings.json` still wins when it matches the manifest; otherwise the parts; a torn set raises. `read_board_json`, `read_board_records`, `load_board`, `_load_prior_details_by_key`, the count guard and `_board_file_present` all go through it. `board_stream.iter_board_rows(path)` keeps its signature: given `docs/listings.json.gz` (the path about 25 scripts name) it streams the parts beside it in order after a manifest check, one row at a time; a scratch directory with only a single gz reads as before.

### Interrupted write

`write_artifact` order: plain `listings.json`, plain detail, **parts** (atomic, one by one; stale higher-numbered parts are removed after the last new part is on disk), detail gz, slim, shards, `run_meta.json`, manifest last. A kill after part 1 leaves part 0 and 1 new, later parts old, and the manifest still the previous write's: the sha256 check fails, `read_board_json`, `load_board`, `read_board_records`, `iter_board_rows` and the next `write_artifact` all raise `BoardIntegrityError`, `verify_manifest` and `check_payload_size.py` report it, and a fresh clone (no plain files) is refused too (tests: section 5).

### Publishing: all parts or none

* `scripts/board_payload.sh`: `board_payload_part_paths` (parts on disk plus tracked ones, so a part a shorter board dropped has its deletion staged; `find`, not a glob, because an unmatched glob is a zsh error), `board_payload_paths` (no `listings.json.gz`), `board_payload_add` (all parts in ONE `git add`; if it fails it unstages the whole board payload, prints `PARTS_STAGE_FAILED` and returns 1), `board_payload_verify_staged` (runs `scripts/check_staged_parts.py`), `board_payload_unstash` (after `git reset --hard origin/main` it removes part files the stash did not carry, so origin's extra parts do not ride into our commit).
* `scripts/check_staged_parts.py` (also called from `scripts/git_size_gate.sh`, the pre-commit hook, and from `publish_commit`, and from the three workflows): reads the **index**. The staged parts must be exactly the parts the staged manifest lists, each with the recorded size and sha256; the manifest's parts block must be well formed; staged `run_meta.json` must be the one the manifest hashed and carry the same part list. A commit touching no part and not the manifest is not checked. Exit 1 refuses the commit.
* `src/foreclosure_scraper/publish.py`: `parts_pathspec(root)`, `board_seal_pathspec(root)` (parts plus manifest); `daily_api_refresh.py` and `patch_vision_gemini.py` use them for their inline `pub` lists.
* The 95 MiB size gate stays. `check_payload_size.py` adds the per-part check (`OVER_PART` over 24 MiB, exit 1), the board total line, and a parts-versus-manifest check (exit 2); a lingering single file is a warning (exit 1). `job_watch.py` alarms on both.

### Dashboard (`docs/dashboard.js`, `docs/index.html?v=20260921b`)

`loadBoardStreaming(bust, onProgress, board, parts)`: when `run_meta.board_parts` validates (`boardPartsFromMeta`), the FULL board is the listed parts. Every request is issued up front on the desktop (a phone, which only reaches the fat board as the fallback for a missing slim file, keeps two in flight), each is consumed in order with its own scanner state (`consumeBoardResponse`), the row count is checked after every part against run_meta's row range and at the end against both the parts total and the slim `board.count` (the existing mid-publish message, no laundering through the fetch fallback). Same `?t=<run_time>` cache key. Same fetch guard: a part URL is a `.json.gz` data URL, so a login page in its place is caught by the existing session handling. `fetchFullBoardFallback` fetches the parts in parallel for the no-streaming path. **When run_meta lists no parts, the single `listings.json.gz` is fetched exactly as before** (a pre-split publish, or a rollback). The sha256 in run_meta is not checked in the browser (section 6).

### Worker and private host

`worker/src/routes.js`: `PART_RE` classifies `/listings_part_NNN.json.gz` as a release file (immutable when pinned by `?t=`). `/listings.json.gz` stays allowlisted for a rollback. `scripts/publish_private.sh`: the single gz is no longer REQUIRED; parts come from `run_meta.board_parts`, each checked for presence, size, sha256, contiguity, no extras, and refused over 25 MiB (Cloudflare's per-asset cap); the row total must equal `board.count`; a run_meta with no `board_parts` falls back to `listings.json.gz`.

## 2. Files changed (file:line, at commit)

New:

* `src/foreclosure_scraper/board_parts.py` (the helper): `write_parts` :537, `resolve` :308, `iter_rows` :413, `read_rows` :431, `resolve_source` :448, `verify_dir` :660, `UnlistedPartsError` :88, `PART_MAX_BYTES` :61.
* `scripts/check_staged_parts.py`, `scripts/migrate_board_to_parts.py`.
* `tests/test_payload_split.py` (57 tests), `tests/js/board_parts.test.mjs` (15 tests).

Changed:

* `src/foreclosure_scraper/web_artifact.py`: `_choose_listings_source` :726, `_choose_board_source` :775, `_read_board_json_ex` :874, `_board_file_present` :908, `_derive_parts_block` :2441, `build_manifest` :2475, `verify_manifest` :2544, `_write_plain_array` :2608, `reseal_board` :2655, `write_artifact` :2709 (per-row blobs :2775, `write_parts` :2924, `board_parts` in run_meta :3012, manifest `parts_block` :3169).
* `src/foreclosure_scraper/board_stream.py` :30, `src/foreclosure_scraper/publish.py` :120 and :137.
* `scripts/board_payload.sh` :56 to :190, `scripts/publish_helper.sh` (`stage_failed`, `parts_inconsistent`), `scripts/git_size_gate.sh` :29, `scripts/restore_board.sh`, `scripts/publish_private.sh` :128, `scripts/check_pages_publish.py` :59 to :95, `scripts/check_payload_size.py` :104 to :190, `scripts/job_watch.py` :170, `scripts/board_manifest.py` (`--rebuild --resplit`), `scripts/daily_api_refresh.py` :358, `scripts/patch_vision_gemini.py` :231 and :35.
* Readers moved to the parts-aware path: `scripts/county_coverage_matrix.py`, `contradiction_check.py`, `source_signal_county_matrix.py`, `fullmer_buybox_audit.py` (their own gzip loops now delegate to `iter_board_rows`), `comprehensive_audit.py`, `resolve_court_names_dryrun.py`, `split_out_of_scope.py`, `gen_source_register.py`, `patch_run_scrapers.py` :555, `auto_rerun.sh`, `run_status.sh`. Already transparent through `iter_board_rows` (no edit needed): `backfill_deed_index.py`, `_dq_common.py`, `ingest_new_county_sources.py`, `flag_unverified_sc_phones.py`, `backfill_jail_rosters.py`, `coverage_100_ledger.py`, `run_scoped_scrapers.py`, `reset_divorce_slow_rounds.py`, `resolve_anderson_from_roll.py`, `repair_burke_storm_damage_parcels.py`, `repair_pickens_acreage_as_value.py`, `annotate_divorce_match.py`.
* **Direct writers** that used to gzip `listings.json` into the single file now call `web_artifact.reseal_board(docs, resplit=True)` (re-cuts the parts from the plain file, streaming, then reseals `run_meta.board_parts` and the manifest): `enrich_batch.py`, `enrich_zip_codes.py`, `enrich_zip_codes_phase2.py`, `flood_zone_batch.py`, `courts_only.py`, `fixup_valuation.py`, `title_search_pipeline.py`, `patch_distress_score.py`, `patch_owner_mailing.py`, `patch_court_detail.py`, `geocode_catchup.py`. Without this a stale single gz would be written beside parts the loaders trust, and the edit would be invisible. They still bypass the lock check (`docs/ops_fixes_2026-09-21.md` section 2); run them under `scripts/with_board_lock.sh`. Untouched on purpose: `merge_title_search.py` (a one-shot that restores a 2026-08 commit's board).
* Workflows: `.github/workflows/weekly.yml`, `patch-run-scrapers.yml`, `patch-listings.yml` (parts check, `board_payload_add` failure is fatal, `board_payload_verify_staged` before every commit), `repo-size.yml` (measures the parts too).
* `docs/_config.yml`, `docs/dashboard.js` :683 (BOARD-LOADER region), :705 `boardPartsFromMeta`, :781 `loadBoardStreaming`, :911 `consumeBoardResponse`, :973 `fetchFullBoardFallback`, :1034 and :1061 (call sites), `docs/index.html` (`dashboard.js?v=20260921b`), `worker/src/routes.js` :76 and :119, `docs/OPERATIONS.md`, `docs/HANDOFF.md`, `docs/RESTORE.md`, `docs/HOSTING_WORKER_2026-09-21.md`.
* Tests updated for the new layout: `tests/test_board_slim.py`, `test_detail_shards.py`, `test_board_integrity.py`, `test_publish_plumbing.py`, `tests/conftest.py`, `tests/_ops_helpers.py` and `tests/test_ops_daily_wrapper.py` (the wrapper tests' stub "board change" now touches a non-part payload file, because the parts gate correctly refuses a staged part that disagrees with a manifest), `worker/test/routes.test.mjs`, `worker.test.mjs`, `helpers.mjs`.

### `scripts/patch_vision_gemini.py` (another agent is rewriting it in the real repo): the edit to re-apply

Two places, four lines:

```python
# with the other imports
from foreclosure_scraper.publish import board_seal_pathspec       # or add it to their existing publish import
...
# in the publish block, replace:  pub = ["docs/listings.json.gz", "docs/listings_detail.json.gz", "docs/run_meta.json"]
pub = [*board_seal_pathspec(root), "docs/listings_detail.json.gz", "docs/run_meta.json"]
```

`board_seal_pathspec` is the parts plus `docs/board.manifest.json`, so if their version also does `pub += manifest_pathspec(root)` the manifest is listed twice, which `git add` does not mind. The slim and shards lines are unchanged. Use `parts_pathspec` instead if they keep their own manifest line.

## 3. Migration and rollout (order matters)

Do not start while a board job holds the lock (the daily job holds it for hours; `scripts/job_watch.py --report`, `cat logs/.board.lock/pid`).

**Step 1. Land the code in ONE commit** (branch `payload-split`): `web_artifact` + readers + publishers + dashboard + worker + docs + tests. `git -C ~/foreclosure-scraper merge payload-split` (or cherry-pick), re-apply the `patch_vision_gemini.py` edit above if that file changed, then `git add`, commit, push. Safe before any migration: with no manifest and a single gz, every reader still reads the single file; `run_meta.json` has no `board_parts`, so the new dashboard fetches `listings.json.gz`. If a scheduled job writes the board first, `write_artifact` publishes parts and the manifest by itself and leaves the old gz alone; skip to step 3.

**Step 2. Migrate** (no other board job running):

```sh
cd ~/foreclosure-scraper
.venv/bin/python scripts/migrate_board_to_parts.py            # DRY RUN: temp dir, layout, round trip, nothing under docs/ changes
.venv/bin/python scripts/migrate_board_to_parts.py --apply    # takes the board lock; about 3 to 5 minutes, ~300 MB RSS
```

It streams the gz row by row (no `load_board`, no row is decoded into a `Listing`), copies each row's exact source text into the parts, proves the cut by streaming the parts back against the source (every row's bytes, in order), refuses if the row count is not the count `run_meta.json` declares (`board.count`, else `total`; the dashboard would refuse such a board), stages the parts in `docs/.migrate_parts.<pid>/`, hashes the plain files first (the slow part), then moves the parts into place and writes `run_meta.board_parts` and the manifest in quick succession, re-verifies (`verify_manifest`, full hashes) and re-runs the round trip from the final files. It never deletes `docs/listings.json.gz`. Refuses with exit 75 when the lock is held, exit 1 when already migrated (`--force` overrides the count and already-migrated checks).

**Step 3. Publish the parts.**

```sh
python3 scripts/check_pages_publish.py                        # every part survives the Jekyll build
git add docs/listings_part_*.json.gz docs/board.manifest.json docs/run_meta.json
python3 scripts/check_staged_parts.py                         # the pre-commit hook runs this too
git commit -m "Payload split: publish the board as listings_part_NNN.json.gz (audit O1)"
git push origin main
```

**Step 4. Verify it is live**, then and only then retire the old file:

```sh
curl -s https://highwaymarketingco-wq.github.io/foreclosure-scraper/run_meta.json | python3 -c "import json,sys;d=json.load(sys.stdin);print(d['run_time'], d['board_parts']['count'], d['board_parts']['records'])"
curl -sI "https://highwaymarketingco-wq.github.io/foreclosure-scraper/listings_part_000.json.gz" | head -3
```

Open the dashboard (desktop, then a phone); the board count matches `total`.

**Step 5. Retire the single file** (after step 4):

```sh
cp docs/listings.json.gz backups/listings.json.gz.pre-split       # optional local rollback copy (backups/ is untracked)
git rm docs/listings.json.gz
git commit -m "Payload split: retire the single listings.json.gz"
git push origin main
```

`git rm` removes it from the deployed site too (about 88 MB less per deploy). Its history stays in git. A rollback needs it (section 4), which is why it goes last.

**Step 6. Private host (only if `publish_private.sh` is in use).** Deploy the Worker first (`scripts/deploy_worker.sh`, it carries `PART_RE`), otherwise the private site 404s on the parts; then `scripts/publish_private.sh` (dry run, then `--apply`).

**Step 7 (a week later).** Delete the rollback conveniences together: `- listings.json.gz` in `docs/_config.yml` include, `LEGACY_SINGLE_GZ` and its `SIMULATED` entry in `scripts/check_pages_publish.py`, `/listings.json.gz` in `worker/src/routes.js` RELEASE_FILES, and `BOARD_FAT_FILE` plus the `else` branch in `loadBoardStreaming` and `fetchFullBoardFallback`. `tests/js/board_parts.test.mjs` pins the current single mention of `listings.json.gz` in `dashboard.js`.

The pre-commit hook needs no reinstall: `.git/hooks/pre-commit` already delegates to the versioned `scripts/git_size_gate.sh`.

## 4. Rollback

* **Before step 5 (old gz still in the tree):** revert the code commit. The plain `docs/listings.json` is still in the manifest's `files`, so the pre-split reader accepts it; the parts and the extra manifest keys are ignored. If the plain file is missing, restore a single-file board first (next bullet). `run_meta.board_parts` is ignored by the old dashboard, which fetches the single gz.
* **After step 5:** `scripts/restore_board.sh --list 20`, pick the last commit that holds `docs/listings.json.gz` (the listing shows `[N parts]` for parts commits and none for single-file ones), `scripts/restore_board.sh <commit> --yes`. It moves the current parts to `backups/pre-restore-<stamp>/`, restores the single gz and that commit's manifest, and checks it. Revert the code commit. Tested: `test_restore_of_a_pre_split_commit_removes_the_parts_and_brings_back_the_single_file`.
* A torn part set on the live tree: `scripts/restore_board.sh <commit-of-the-last-good-board>` (post-split commits restore exactly that commit's parts and remove the rest), or, if you have checked the files, `scripts/board_manifest.py --rebuild`.
* The cap in an emergency: `BOARD_PART_MAX_BYTES=<bytes>`; a part over 24 MiB after a hand edit: `scripts/board_manifest.py --rebuild --resplit`.

## 5. Tests run (targeted only, never the whole suite)

`PYTHONPATH=$PWD/src /Users/cashhigh/foreclosure-scraper/.venv/bin/python -m pytest -q -p no:cacheprovider ...` with `foreclosure_scraper.__file__` confirmed to resolve to the worktree.

New, `tests/test_payload_split.py` (57): a synthetic **60k-row board with a tiny cap** splits into many parts (each under the cap, contiguous ranges, total 60,000) and round-trips row for row, byte for byte, in order; the cap holds when the sample-based estimate is wrong (a compressible region followed by random hex, list and iterator sources); one oversized row raises; the empty board; determinism and stable boundaries (only the part holding a changed row differs); growth adds parts; a shrinking board removes stale parts; a write that dies mid-part leaves no temp file. `write_artifact`: parts and manifest, plain bytes equal to `json.dumps` of the payload, stale single gz untouched and ignored, legacy layout upgrades in place, a 60k-lead end to end, `iter_board_rows` stays a generator. **Interrupted write**: part i written and the manifest not updated raises `BoardIntegrityError` in `read_board_json`, `load_board`, `read_board_records`, `iter_board_rows` and the next `write_artifact`, including on a checkout with no plain files; truncated, flipped-byte, missing and stray parts; unlisted parts refused unless a single gz exists. Migration (dry run touches nothing, apply, refusals, lock, never calls `load_board`), `reseal_board`, `board_manifest.py --rebuild --resplit`, `board_payload.sh` (all parts staged in one add, a part that cannot be staged unstages everything, deleted tracked part staged as a deletion, unstash drops origin's extra parts), `check_staged_parts.py` and the real pre-commit hook (mixed set refused, consistent set commits, the size gate still blocks), `publish_commit`, `publish.py`, the workflows, `check_payload_size.py`, `job_watch.py`, `check_pages_publish.py`, `publish_private.sh` (tampered, missing, extra, oversized, pre-split fallback), `restore_board.sh` (post-split, pre-split, `--list`).

New, `tests/js/board_parts.test.mjs` (15): `boardPartsFromMeta` validation, parallel requests with out-of-order arrival, order, count gates, missing and truncated parts, inflated-by-the-server parts, the single-file fallback, phone behavior, the fetch fallback, session handling of a part URL, the cache-buster.

Results (final run, this worktree, macOS, Python 3.12, node 22):

| Command | Result |
|---|---|
| One run of `pytest tests/test_payload_split.py test_board_slim.py test_detail_shards.py test_board_integrity.py test_board_split.py test_board_roundtrip.py test_board_stream.py test_board_persist.py test_vision_patch_board_io.py test_publish_plumbing.py test_publish_py.py test_job_watch.py test_ops_shell.py test_ops_daily_wrapper.py test_dashboard_lead_state_js.py test_backfill_jail_rosters.py test_backfill_deed_index.py test_ingest_new_county_sources.py test_sc_phone_gate.py test_main_failure_paths.py test_family_merge.py test_required_raw_keys_registered.py` | **448 passed** (112 s; `test_payload_split.py` is 57 of them) |
| 19 further test files that import `web_artifact`, `board_stream`, `write_artifact` or the patched scripts (`test_backup_prune`, `test_checkpoint`, `test_count_guard_footprint`, `test_run_scoped_scrapers`, `test_repeat_tax_loss`, ...) | 533 passed, 1 skipped |
| `node --test tests/js/*.test.mjs` (also with `TZ=Pacific/Auckland`; also run by `tests/test_dashboard_lead_state_js.py`) | 72 passed (15 new) |
| `cd worker && node --test test/*.test.mjs` | 111 passed |
| `node worker/scripts/build_shell.mjs --check` | ok |
| `python3 scripts/check_pages_publish.py`; `/usr/bin/python3` (3.9) importing `board_parts.py`, `check_staged_parts.py`, `check_payload_size.py`, `check_pages_publish.py`, `job_watch.py` | ok |

Existing tests changed for the new layout, on purpose: `test_board_slim.py` (byte identity and gz-only checks name the parts), `test_detail_shards.py` (authoritative-file list), `test_board_integrity.py` (the manifest lists a part, not `listings.json.gz`), `test_publish_plumbing.py` (the payload list, the stash test, and two new prefix-trap parameters), `tests/_ops_helpers.py` and `test_ops_daily_wrapper.py` (the stub "board change" touches a payload file that is not a part).

## 6. Risks, and what I could not verify

Not verified:

* **Nothing ran against the real board.** I never loaded it and did not read the real `docs/listings*.gz` (only file sizes from the brief). The part count (about five) and per-part size (about 19 MiB) are an estimate from 518 compressed bytes per row; the migration's dry run prints the real layout before anything is written. Timing (about 21 MiB/s of raw JSON through gzip level 9, measured on synthetic rows, about 1 minute for the whole board plus about 15 seconds per streaming pass) and memory (about 100 MB RSS for a 36 MiB synthetic board; the writer holds one part's rows) are extrapolated.
* **Dashboard in a real browser.** Tested under node with real `Response`, `ReadableStream`, `DecompressionStream` and `TextDecoderStream` against real gzip, not in Chrome or Safari. Desktop memory with all parts in flight (up to about 100 MiB of compressed bytes buffered) and iOS Safari behavior are unmeasured; a phone only reaches the parts as the fallback for a missing slim file and keeps two in flight.
* **The Worker and R2** ran against the test fakes only; the release layout and the 25 MiB per-asset cap were not exercised on Cloudflare.
* **GitHub Pages and CDN behavior** for a publish that adds parts. The `?t=<run_time>` key makes each part URL immutable per publish, and the client checks per-part and total row counts, but a browser cannot prove a part's bytes: **the sha256 in run_meta is not verified in the browser** (a stale edge serving another publish's part of identical row counts would pass). Adding `crypto.subtle.digest` per part is a follow-up.
* The workflows run only on GitHub; I reasoned about GNU `xargs`, `find` and `tar` there but only executed on macOS.
* I did not run the whole test suite. The 11 direct-writer scripts were compile-checked and reviewed, not run (they need the real board).

Risks:

* **Repo growth (O7) is not solved by this.** Each publish still adds the changed parts. Stable boundaries help changes confined to some rows; a full re-score touches every row and rewrites every part. The 12.7 GiB repo problem still needs the orphan-branch or filter-repo work in `docs/OPERATIONS.md` section 8.
* Rows-per-part is re-chosen when the previous value falls outside 0.75x to 1.20x of the fresh estimate (the board's compression ratio or row size drifted); that rewrites every part once, about once every week or two at today's growth.
* The direct writers (section 2) now take a minute or two longer (they re-cut the parts) and need `docs/listings.json` on disk.
* `run_meta.board_parts` and the manifest's parts block must never be edited by hand; a hand edit is caught by `verify_manifest` and the commit hook, but not by the dashboard.
* `git_size_gate.sh` now runs Python on a commit that touches parts or the manifest (about one second: it hashes the staged parts). If `python3` is missing it skips the parts check and keeps the size check.
* Old cached dashboards (`dashboard.js` before `?v=20260921b`) request `listings.json.gz`; after step 5 they 404 until the page is reloaded. The HTML is cached for at most Pages' 10 minutes.
* Between "parts in place" and "manifest written" (a second or so in the migration, milliseconds in `write_artifact`'s tail) a reader with no manifest and no plain file finds parts nobody lists and is refused (or falls back to the single gz), never handed a partial board.
