# HANDOFF: current state of play

**Rewritten 2026-09-21.** Read this first in a new session, then go straight to work. Every statement is either verified today (with where) or explicitly marked as not re-verified. The previous edition was stamped 2026-08-20 and had drifted to a fifth of the board's real size; the dated statements it carried are kept at the bottom under a clear heading instead of being asserted as current.

Keep this file current. It exists so a fresh session costs one file read instead of an hour of rediscovery.

---

## Where the board is (2026-09-21)

Source: `docs/run_meta.json` (written 10:11 EDT), `docs/AUDIT_2026-09-21.md`, `docs/audit_operations_2026-09-21.md`.

- **170,066 leads** (NC 93,030, SC 77,036) from **156 sources**. High-water mark 175,941 (9/15).
- Files: `docs/listings.json` about 1.1 GB (gitignored), `listings.json.gz` 84.0 MiB (GitHub's hard limit is 100 MiB; it was 34 MiB on 8/26), a 171-file shard set, a slim phone payload, and since 2026-09-21 `docs/board.manifest.json` once the first write by the new code seals it.
- Largest sources on the board: liensnc 40,909 (plus 6,080 under the bare `liensnc` slug; all construction lien-agent filings, not distress), `qpaybill_delinquent_roll` 33,527, `sc_dew_lien_registry` 8,810, `gaston_vacant` 7,035, `transylvania_vacant` 5,332, `sc_public_index` 5,050, `rutherford_tax` 4,164.
- **Freshness is not what `last_seen` says.** About 2,200 rows (1.3%) come from the 14 sources a scheduler refreshes daily. The last full run to land on the board was 2026-08-28 to 8/29. Nineteen sources with 100+ rows have 80% or more of their leads last seen over 30 days ago. `run_meta.source_last_success` (new) measures freshness per source.
- Tiering: HOT 1,646, WARM at least 71,010 (43% of leads with a county) before the 9/21 rescore, which the scorer changes will reduce sharply. See `docs/AUDIT_2026-09-21.md` and `docs/scoring_fixes_2026-09-21.md`.
- Repo 12.7 GiB on GitHub, deployed site 561.6 MB (Pages fails a build at 950 MB). Time Machine has no destination.

## What runs (verified with `launchctl` and the job logs on 2026-09-21)

Five LaunchAgents are loaded: `dailyvision` (09:30 daily, skipped Tue and Fri until a patch is applied), `lrcpwa` (12:00), `sosagent` (14:00), `parcelcache` (Sunday 04:00), `weekly` (Tue and Fri 09:30, a popup that needs a human). **`dailycourt` was disabled 9/20** after 31 of 31 runs exited 127 (`uv: command not found`). The full run (`scripts/run_local.sh`) starts only from the popup or the Desktop app and has not landed since 8/29.

Templates for a better day (lrcpwa 08:00, sosagent 08:30, per-family merges, backup, job watcher) are in `deploy/mac/`; nothing is installed. Details: `docs/OPERATIONS.md`.

## Rules for working on the board

- **One writer at a time, and it is enforced.** `write_artifact` refuses unless the process holds `logs/.board.lock`. Run any board-writing script with `scripts/with_board_lock.sh <name> -- uv run python scripts/<x>.py`. Check the holder before starting: `cat logs/.board.lock/pid` (pid, owner, start, heartbeat, max runtime, token). A job that finds it held skips (exit 0) and logs a `skipped_lock` event.
- **Load through `web_artifact.load_board()`** (or `read_board_records`), or the vision, comps and CAMA sidecars are wiped. `load_board` now counts every row it drops and fails above 0.1%.
- **Never load the board in more than one process at a time.** One load is about 2.8 GB; three concurrent loads reached about 20 GB and forced a restart. The Mac is an 8 GB Air with 6 to 7 GB of swap in use under a single job.
- **The manifest.** After a write, `docs/board.manifest.json` names every payload file. If a load raises `BoardIntegrityError`, the set is torn or the manifest is stale: `scripts/board_manifest.py --verify`, then restore (`docs/RESTORE.md`) or, once you have checked the files, `--rebuild`.
- **Stage payloads with `board_payload_add`** (`scripts/board_payload.sh`) so the manifest travels with the board.
- **Do not push inside the lock**, and do not run `git add` on the payload by hand without the manifest.
- **A bad board:** `scripts/restore_board.sh <commit>` (`--list` first). One commit, every payload file. `docs/RESTORE.md`.
- **Compliance line** (owner rule, 2026-09-20): a `robots.txt` Disallow is not a wall; a CAPTCHA, a login, a Cloudflare challenge and click-through terms are. See `CLAUDE.md`.

## What was done on 2026-09-21

Audit: `docs/AUDIT_2026-09-21.md` (findings register, section 11) and `docs/audit_operations_2026-09-21.md`. Fixes: `docs/ops_fixes_2026-09-21.md` (operations), `docs/scoring_fixes_2026-09-21.md` (scorer), `docs/data_quality_fixes_2026-09-21.md` (data). The operations work, in one table:

| Area | What exists now |
|---|---|
| Lock | Enforced in `write_artifact`; start time, heartbeat, max runtime, token, registered children; stale by max runtime; memory gate (default `warn`) |
| Board integrity | Manifest written last and verified on load; changed-since-load check; dropped rows counted and capped |
| Health | `health_as_of`, `health_age_hours`, `health_stale` (nulls `source_status` and `errors` past 48 h); `source_last_success` per source |
| Failures | `main.py` exits 3 on a failed board write and skips the export and the email; exit 6 on a scorer failure; `run_local.sh` aborts on both |
| Job log and watcher | `logs/job_events.jsonl`, `scripts/job_watch.py`, `scripts/check_payload_size.py` |
| Pushes | `scripts/publish_helper.sh`, `src/foreclosure_scraper/publish.py`: commit in the lock, push outside it with a timeout and retries |
| Refresh | Per-family merge jobs `scripts/run_family_{qpaybill,nc_tax,sc_tax,nc_ecourts}.sh` |
| Backup | `scripts/backup_local_state.sh`, `scripts/restore_board.sh`, `docs/RESTORE.md` |
| Scope and window | Flip leads only in the 18 counties (coastal carve-outs no longer shelter a flip); the sold-pool partition waits out the upset window; `auction_date` is kept apart from the docket date |

Four files a running job owns are shipped as patches, not applied: `run_daily_vision.sh`, `daily_api_refresh.py`, `patch_vision_gemini.py`, and optionally `enrichment_vision.py` and `pyproject.toml` (`docs/ops_fixes_2026-09-21.md`, section 16).

**Tests.** I ran targeted files only, never the whole suite. The last whole-suite count in this file (3201 passed, 2 failed) is from 8/20 and was not re-run; the audit noted CI runs only on pull requests.

## Do next, in order

1. When the 09:30 job has finished: apply the patches, commit, then `scripts/board_manifest.py --validate-rows` once (the real load drop rate has never been measured), then `--rebuild` to seal the board.
2. Preview and install the schedule: `scripts/install_launchd.sh` (dry run), then `--apply`. Create the backup passphrase in the keychain first (`docs/RESTORE.md`, section 3).
3. Run each family job once by hand and read `logs/family_<name>.log` before scheduling it. None has run against the real board.
4. Watch `mem_gate` lines in `logs/job_events.jsonl` for a week, then choose `BOARD_MEM_GATE=enforce` thresholds.
5. The payload split (audit O1): `listings.json.gz` is 16 MiB from GitHub's limit and the 95 MiB commit gate. Decide the split or the trim.
6. Owner decisions still open: public repo and owner PII (audit O8); the memory gate mode; whether the vision backends are replaced or retired (only about 13% of rows have a vision score; the pool collapses from 21 workers to 1 in 40 minutes).
7. Route the scripts that write `docs/listings.json` directly (listed in `docs/ops_fixes_2026-09-21.md`, section 2) through `write_artifact`.
8. The first full run on a 170k board is a supervised test (plugged in, other apps closed). It has never completed since the count-guard fix.

## Blocked / not worth building (as of 2026-08-20; not re-verified on 2026-09-21)

Retained from the previous edition. Re-probe before believing a "dead" entry (`docs/MASTER_GAPS_WALLS_AND_MANUAL_LANES.md` rule 4).

- PACER: paid. CourtListener covers bankruptcy.
- Oconee parcel cache: the ArcGIS server rejected bulk export. (The 9/20 parcel-cache refresh log lists Anderson and Oconee caches as OK, so the older "Anderson, Cherokee, Union, Oconee blocked" line is superseded; Cherokee and Union are not in the refresh list.)
- Several REO sources (BofA, First Bank, Founders FCU, UCBI, RealtyBid): dead, 403, 404 or SPA-walled.
- Census ACS needs a free key (`api.census.gov/data/key_signup.html`); a tract-level geocoder fallback works without one.
- FBI UCR host was unreachable. SC SOS UCC costs $5 a search. Zillow's API is discontinued. No free MLS access exists.
- doc_ocr: the first board-wide backfill ran 9/16 (commit 3ba7337, 46 rows). The 8/20 claim of "3,388 PDFs linked, 0 parsed" is superseded.

## Register of deeds (last verified 2026-08-12; not re-verified)

Two platforms, not one.

| | The Lookup | Online Record System |
|---|---|---|
| entry | `index.php?Accept=Accept` | `NameSearch.php?Accept=Accept` |
| search | `content.php` (GET) | `NamePick.php` then `NameDisplay.php` (POST) |
| amount in index | no | yes |
| counties | clay, haywood, yancey (NC) | 8 SC |
| reader | `enrichment_rod_lookup.py` | `enrichment_rod_name_index.py` |

**Wrong-state hosts are a standing trap:** `<county>deeds.com` never states its state. `hendersondeeds.com` is Henderson County, Kentucky; `wilsondeeds.com` is Wilson County, Tennessee. Full derivation: [`ROD_PORTAL_ACCESS.md`](ROD_PORTAL_ACCESS.md).

## API details (last verified 2026-08-20; not re-verified)

- GovDeals: `POST https://maestro.lqdt1.com/search/list` with `x-api-key` and `Ocp-Apim-Subscription-Key` (both in `.env`), `businessId: "GD"` as a STRING; `isAPIFailureActive: true` is normal; real property is rare on that site. Akamai-walled unless `curl_cffi` impersonates Chrome.
- HomePath: `GET https://homepath.fanniemae.com/cfl/property-inventory/search?state=NC&page=1&pageSize=5`.
- NCPTS Cloud: `https://lrcpwa.ncptscloud.com/api/SimpleParcelSearch?query={q}&pageIndex=0&pageSize=10` with an `X-Tenant: {CountyName}` header (17 NC counties).
- Listing model: `street_address` not `address`, `source_url` not `url`, `ListingType.TAX_SALE`, extras go in the `raw` dict. Registry slugs carry different suffixes (`chester_delinquent_tax`); the registry returns classes, instantiate before calling.

## Reference

| doc | what |
|---|---|
| `OPERATIONS.md` | how the engine runs, the lock, the job log, publishing, recovery, repo size |
| `RESTORE.md` | restoring a bad board and the Mac itself |
| `ops_fixes_2026-09-21.md` | the operations fixes, patches to apply, what remains |
| `AUDIT_2026-09-21.md`, `audit_operations_2026-09-21.md`, `audit_signal_logic_2026-09-21.md` | the audits |
| `SOURCE_REGISTER.md` | every source with URL, gate, cost, cadence (regenerated 2026-08-20; 205 scrapers then, 209 logged on 8/28) |
| `COUNTY_SYSTEMS_REGISTRY.md` | 146 counties x 4 systems |
| `ROD_PORTAL_ACCESS.md` | both recorder platforms, request recipes |
| `MASTER_GAPS_WALLS_AND_MANUAL_LANES.md` | what cannot be done and why (see its 2026-09-21 correction block) |
| `path_to_100.md`, `gap_ledger.md` | costed blueprint; ledger |

## Commands

```bash
cd ~/foreclosure-scraper
.venv/bin/python -m pytest -q -p no:cacheprovider tests/test_<file>.py     # targeted; the suite is large
.venv/bin/python scripts/board_selfcheck.py                                # invariants, exit 1 on breach
.venv/bin/python scripts/board_manifest.py --verify
scripts/with_board_lock.sh <name> -- uv run python scripts/<writer>.py
scripts/restore_board.sh --list 10
/usr/bin/python3 scripts/job_watch.py --report
```

Never run `regenerate_dashboard.py` to fix valuations: it is a network re-enrichment of many hours. `scripts/recompute_valuation.py` does it offline.
