# version_compare: compare every candidate board with the live one before it can replace it

Owner's standing instruction (2026-10-08): whenever a new board could replace the live one, compare
the two and publish whichever is better; never publish blind. This area builds that comparison:
`scripts/compare_boards.py` (tests `tests/test_compare_boards.py`) and two invariants in
`scripts/audit_checks/version_compare.py`. Everything below is counts, slugs, county and column
names, parcel ids and opaque row references; no owner name, phone, e-mail or address.

## 1. What it measures and how (repeatable)

Two streaming passes, one row at a time: pass 1 reads the baseline (the live `docs/`, or a
checkpoint) and keeps a fixed 92-byte record per row (tier, source, county, 11 field hashes, a
column bitmask, a signal bitmask) in one bytearray, plus each row's identity keys as two flat arrays
sorted once (64-bit key hash, row number). Pass 2 streams the candidate (another board directory,
or a checkpoint read exactly as `board_selfcheck.py --checkpoint` and `audit_suite.py --checkpoint`
read one: `Listing.model_validate` then `web_artifact._to_dict`, the row write_artifact would
publish) and joins each row to the baseline on `verification.core.row_keys` (parcel, then numbered
address, then case; the keys the verification ledger matches on, because `Listing.dedupe_key`
moves when a parcel is backfilled), with the as-scraped fingerprint as the last resort. A key shared
by 4+ live rows with as many addresses (board_selfcheck.FUSION_THRESHOLD) is never a join key; on
a shared key the same street address, then the same source, wins.

Sections of the report (JSON + plain-words markdown):

1. **Rows**: totals by state, county and source for both; live rows missing from the candidate by
   source and by the reason the row itself shows (folded into another row's key, source gone,
   `board_persist._is_terminal_dict`, the pulled-sale miss limit, `drop_countyless_national`,
   `prune_stale_reo`, `main._active_only`'s window, else unexplained); new rows by source; sources
   under 90% of live or at zero.
2. **Coverage**: every gap_matrix column (the owner's 73 and the 9 attorney columns, computed by
   `gap_matrix.owner_columns` / `positive_columns`, not restated), three extra fields (mailing
   address, tax balance, late tax years) and every distress signal. ROW COUNTS first, then the share
   of all rows, of HOT+WARM rows and of rows present in BOTH boards. Classes: improved, flat,
   dilution (count up, all-rows share down), rows_left (count down, like-for-like held), regression
   (like-for-like share down more than 0.5 point, or the HOT+WARM share down more than 0.5 point
   with fewer HOT+WARM rows holding the value than the rows that left explain). Never judged on the
   all-rows share alone.
3. **Fields on rows in both**: lost / changed / gained for owner name, street address, parcel id,
   phone, email, mailing address, tax balance, tax years, tax levy year, assessed value, comps, and
   each signal flag; up to 20 sample ids per class.
4. **Tiers**: HOT/WARM/COLD counts, the transition matrix (including `X->left` and `new->X`), HOT
   rows leaving or entering with the signals they lost or gained.
5. **Invariants**: every `scripts/audit_checks/*` check (loaded by `audit_suite.discover`, a fresh
   set per board) and `board_selfcheck.invariants`, fed inside the same two passes; a check that is
   ok on the live board and not on the candidate is a blocker.
6. **Publish safety**: parts against the manifest (sha256), manifest / run_meta / sidecar / slim /
   shard counts aligned (`BoardIntegrityError` paths), every payload file valid gzip JSON, each file
   against `check_payload_size.py`'s limits (50 MiB warn, 95 MiB gate, 24 MiB part cap), the deployed
   site measured exactly as `.github/workflows/pages.yml` measures it (tracked docs/ files Jekyll
   publishes; 600 MB warn, 950 MB fail), and the heir publishing rule. A checkpoint has no files yet:
   its published sizes are estimated by compressing each row as write_artifact would (gzip 9).
7. **Process and structure**: per board, what produced it (commit pin, run flags, phases and their
   seconds, phases that hit their time cap or failed, scrapers, peak memory against the kill line,
   rows dropped by each named filter, how fresh its verification ledgers were, unscored rows,
   selfcheck and audit results) from the checkpoint manifest, `resume_state.json`, `run_meta.json`,
   the run log and the watchdog log; "not recorded" otherwise, and which board has fewer process
   flags.
8. **Verdict**: PASS / PASS_WITH_NOTES / HOLD, each blocker with the threshold it crossed (constants
   at the top of the script, reason beside each), and the BEST-OF-BOTH list: every good value the
   live board holds that the candidate lost (`--best-of-both-out`, JSON lines of row refs + field).
   Also the iteration ledger: `docs/board_versions/<date>_<label>.json` (counts only) on every run,
   and with `--append-changelog` an entry in `docs/board_versions/CHANGELOG.md` in that file's style
   (Improved / Flat / Looked like regressions but are dilution or rows leaving / Real regressions /
   Defects found later), appended, never rewriting earlier entries.

Thresholds that block (HOLD): a source under 90% of its live count with at least 50 live rows (or
any accepted with `--accept-source-drop`); total rows under 95% of live; a like-for-like or HOT+WARM
coverage drop over 0.5 point (columns; signals are notes, since verification removes them on
purpose); a field lost on more than 1% of the rows in both that had it (at least 100 rows); more
than 0.1% unscored rows; a newly breached selfcheck or audit check; any heir rule violation; any
publish-safety problem; a checkpoint that is not `pre_publish`, too old for `--publish-only`, or
lost more than 0.1% of its rows on load. Exit 0 PASS or PASS_WITH_NOTES, 1 HOLD, 2 could not compare.

## 2. Proof on the Mac (2026-10-08)

**A. The published 10/7 board against itself, full size** (350,013 rows each pass; the identity
case must show nothing lost): baseline pass 216 s, candidate pass 239 s, safety and process 35 s
(491 s in all). Peak: 521 MB maximum resident set, 792 MB peak memory footprint (`/usr/bin/time -l`;
the first version of the key index, a dict, measured 512 MB / 891 MB). Result: 350,013 matched
(parcel 185,121, address 81,154, fingerprint 47,473, case 36,265; 78 fused keys refused), 0 missing,
0 new, 0 lost and 0 changed on all 11 fields, all 109 coverage metrics flat, tiers equal (HOT 46,
WARM 45,476, COLD 304,489, none 2), slim 350,013 rows and shards 350,013 records equal to the
manifest, selfcheck matching its own published result (809 duplicate identifiable properties; every
ARV invariant 0). Verdict HOLD, for one reason that is real (finding D1 below).

**B. A 5,000-row sample of the 10/7 board against a copy with planted defects** (every 70th row,
5,001 rows, written with write_artifact into the scratchpad; the copy written both as a board
directory and as a `pre_publish` checkpoint with `checkpoint.save_pre_publish`). Every planted defect
was recovered exactly, and the board-directory and checkpoint candidates gave the same numbers:

| planted | found |
|---|---|
| source `counties_nc.transylvania_vacant` removed (157 rows) | 157 -> 0, reason source_gone; blocker |
| 15% of `counties_generic.liensnc` removed (85 rows) | 567 -> 482, reason unexplained (LiensNC is age-exempt and filing-dated, so no rule explains it); blocker |
| phone removed on 29 rows | phone lost 29 of 998 rows in both (2.91%); blocker; like-for-like 20.97% -> 20.36% |
| parcel id removed on 49 rows | parcel lost 49 (1.98%); 11 of those rows had no other key and still joined on the fingerprint |
| owner name changed on 43 rows | owner changed 43 (0.98%), not a blocker (re-scrapes change owners) |
| tax_owed removed on 33 rows | tax balance lost 33, tax years lost 14, levy year lost 12 |
| tax_lien signal removed on 50 rows | signal lost 50 of 966; a note, never a blocker |
| 2 HOT demoted, 3 WARM promoted | HOT->WARM 2, WARM->HOT 3 (signal gained shown) |
| 400 sparse new rows | new 400 (new->COLD 346, new->WARM 54); email, comps, mailing classed rows_left, not regression |
| 2 rows with heir candidates (a grandchild; a son with a phone) | 6 heir violations (2 relation, 2 contact field, 2 phone); blocker, and the new audit check `version-heir-publishing-rule` 0 -> 2 |

Best of both: 137 good live values the copy lost (parcel 49, tax balance 33, phone 29, tax years 14,
levy year 12), one JSON line each. Size estimate for the checkpoint against what write_artifact then
wrote for the same rows: parts 4,352,836 vs 4,352,835 bytes, detail 392,275 vs 392,275, slim
1,379,776 vs 1,379,775, shards 2,864,240 vs 2,874,755 (-0.4%). Speed: checkpoint rows cost about
1.2 ms each with the estimate (5,159 rows in 6.4 s), so about 8 minutes for 383K rows on the Mac.

The process section was proven on the real 10/8 gated run's log and watchdog log (event lines
grepped read-only from the VM): pin d42058b3 (pinned), exit 0 after 1,147 minutes, 225 scrapers
(199 started: 182 ok, 11 timed out; 26 disabled), peak 16,174 MB against the 25,600 MB kill line, 34
phases hit their time cap, named filters in_scope 3,564, flip 277, dedupe 28,084, dedupe2 1,778,
scope_repass 126, oceanfront 79, countyless national 3,767, aged out terminal 13 and by misses 422,
prune_stale_reo 0; phase seconds start to link_validation 3,828, to gis 2,588, to county_normalized
20,584, to dot_ocr 29,257, to pre_publish 12,581; scorer HOT 107, WARM 66,270, COLD 316,115.

## 3. Defects found

| # | class | scale | cause | fix | invariant |
|---|---|---|---|---|---|
| D1 | every Pages deploy fails, live now | the whole dashboard: the 'Deploy docs to Pages' workflow has FAILED on every push since 2026-10-08 11:46 UTC (5 runs, first one the commit "mac stealth hand-off: 51730 leads"; last success 01:36 UTC), at its "Measure the deployed site" step: "Deployed site is 972 MB, over the 950 MB limit". The site was 896.3 MB at the 10/7 publish (6a2b3f36); 977 MB in this working tree | `docs/handoff/` grew 48 -> 118 MB: `handoff/stealth_leads.json` 46.1 -> 98.4 MB, `handoff/verification/tax_lien.json` 0.6 -> 13.3 MB. Nothing on the dashboard reads `handoff/` (no reference in dashboard.js or index.html), yet Jekyll publishes it. `check_payload_size.py` reports `result: BLOCK` on the Mac working tree (whether job_watch's alert fired was not checked) | NOT made (docs/_config.yml is not this area's): add `- handoff/` to `exclude` in `docs/_config.yml` (nothing fetches a `.gz` twin from there, so the prefix-trap rule does not apply), or stop committing the hand-off into docs/. Until then no board publish reaches the live site: the 10/7 board stays live whatever is pushed | compare_boards publish safety measures the site exactly as the workflow does (`Pages site ... >= 950 MB`), a HOLD |
| D2 | single file near GitHub's limit | `docs/handoff/stealth_leads.json` 93.8 MiB: 1.2 MiB under the 95 MiB commit gate, 6.2 MiB under GitHub's 100 MiB refusal | the Mac stealth hand-off grew from 46.1 MB at the 10/7 publish to 98.4 MB at HEAD | not this area: split it like the board parts, or trim it per run | compare_boards notes every published file over 50 MiB; over 95 MiB it is a blocker |
| D3 | heir names with no relation on the public board | live 10/7 board: `heir_estate.heir_names` on 4,550 rows, `obituary.survivors` on 8 rows, `heir_naming_publication.named_heirs` on 1 row | blocks published before the 10/7 rule; the rule (`PUBLISHABLE_HEIR_RELATIONS`) covers `heir_candidates` only. Whether the 8 survivor lists hold grandchildren or minors cannot be told from a list of names | owner decision (whether these older blocks follow the same rule); counted, not changed | compare_boards notes each count; `version-heir-publishing-rule` fails on any phone, e-mail, age or minor inside these lists |
| D4 | rows a later version cannot follow | 47,460 of 350,013 live rows (13.6%) have no parcel id, no numbered address and no case number | sources that emit neither | none needed now; a jump means a source stopped emitting identity | `version-join-identity` (max 18% of rows) |

The comparison itself found no lost data on the identity run (A); D1 and D2 are about publishing
any board at all, so they hold the coming publish whichever board wins.

## 4. Open items

- Not run: the tool against the real 383K-row pending checkpoint (the lead runs it on the VM, section
  5); nothing was started, written or killed on the VM (two read-only greps of the run log and a
  read of its watchdog log).
- The missing-row reasons are inferred from the row (what the run's rules would do to it), not
  traced through the run. The run's own named-filter counts (section 7 of the report, from its log)
  are the cross-check.
- The HOT+WARM lens is judged only when the HOT+WARM rows holding a value fell by more than the
  HOT+WARM rows with it that left; tier changes move rows in and out of that set, so a column can
  read diluted there while the like-for-like lens is the real test.
- `board_selfcheck` reads its previous board from git for MOVEMENT; this tool does not use that part.
- Two live rows carry no HOT/WARM/COLD tier in my count while the `pipeline-row-scored` check counts
  0 on the same board: the two definitions differ; not investigated.
- The size estimate was checked on 5,159 rows only; on 383K rows parts are cut by the writer, so only
  their total is estimated.
- The VM run's EFFECTIVE environment is not recorded anywhere; the report shows `run_profile.json`'s
  declared flags and vm_lib.sh's defaults, labelled as such.

## 5. Commands: the pending checkpoint on the VM (the lead runs these)

The gated run pinned d42058b3 finished (exit 0) and left `data/checkpoint` at phase `pre_publish`.
The VM checkout is pinned and must not move, so the tool runs from a separate worktree of the commit
you will pass as `RESUME_PIN_COMMIT` (its readers are then exactly the publish's), with the main
checkout's virtualenv; it only reads `docs/` and `data/checkpoint`.

```bash
ssh -i ~/.ssh/oracle_foreclosure ubuntu@129.146.23.144
cd ~/foreclosure-scraper
cat data/checkpoint/manifest.json                 # phase must be "pre_publish"
free -m                                           # the compare peaks under 1 GB
PIN=<commit to publish with, at or after the commit that added scripts/compare_boards.py>
git fetch origin
git worktree add --detach /tmp/compare_tool "$PIN"
STAMP=$(date +%Y%m%dT%H%M%S)
nice -n 10 .venv/bin/python /tmp/compare_tool/scripts/compare_boards.py \
  --baseline ~/foreclosure-scraper/docs \
  --candidate ~/foreclosure-scraper/data/checkpoint \
  --candidate-log logs/vm-run-20261008T014033.log \
  --candidate-memlog logs/vm-run-20261008T014033.mem.log \
  --label gated_d42058b3 \
  --out logs/compare-$STAMP.json \
  --ledger-dir logs/board_versions \
  > logs/compare-$STAMP.out 2>&1
echo "exit $?"                                    # 0 PASS / PASS_WITH_NOTES, 1 HOLD, 2 could not compare
tail -25 logs/compare-$STAMP.out
less logs/compare-$STAMP.md                       # the plain-words verdict
git worktree remove /tmp/compare_tool
```

Optional evidence for the live board's own run: `--baseline-log logs/<the 10/7 vm-resume log>` and
`--baseline-state <a resume_state.json of the 10/7 run>` (checkpoint.archive() copies only the board
and manifest, so an archived pre_publish directory may not hold one). Intended drops are accepted
explicitly, one flag each: `--accept-source-drop national.fannie_homepath` (HANDOFF item 78: 857 ->
about 45 on purpose), `--accept-coverage-drop COLUMN`, `--accept-field-loss FIELD`; each then shows
as a note with the reason. Expected time: about 4 minutes for the live board and 8 to 10 for the
checkpoint (row validation plus the size estimate; `--no-size-estimate` skips the estimate).

Then on the Mac, record the iteration (the ledger record and the changelog entry live in the repo):

```bash
scp -i ~/.ssh/oracle_foreclosure ubuntu@129.146.23.144:foreclosure-scraper/logs/compare-<STAMP>.json /tmp/
cd ~/foreclosure-scraper
uv run python scripts/compare_boards.py --from-report /tmp/compare-<STAMP>.json \
  --label gated_d42058b3 --append-changelog --date 2026-10-09
git commit -m "board versions: gated_d42058b3 vs the 10/7 board" -- docs/board_versions/
```

Read before publishing: D1 holds ANY publish until `docs/handoff/` stops counting toward the Pages
site (the report will show it as a blocker on every board; the Pages workflow is already refusing
every deploy, `gh run list --workflow pages.yml`).

## 6. Wiring the lead should apply

1. `deploy/oracle/vm_run.sh`: compare automatically when a gated run stops before publish. Anchor:
   the `} | tee -a "$LOG"` that closes the "STOPPED BEFORE PUBLISH" block (line 125). Insert after
   it:
   ```bash
       if [[ "${VM_COMPARE_AFTER_RUN:-1}" == "1" ]]; then
         nice -n 10 .venv/bin/python scripts/compare_boards.py --candidate "$CKPT_DIR" \
           --out "$ROOT/logs/compare-$STAMP.json" --candidate-log "$LOG" --candidate-memlog "$MEMLOG" \
           --label "vm_run_$STAMP" --ledger-dir "$ROOT/logs/board_versions" >>"$LOG" 2>&1
         echo "==> compare with the live board: exit $? (0 PASS or PASS_WITH_NOTES, 1 HOLD); read logs/compare-$STAMP.md" | tee -a "$LOG"
       fi
   ```
2. `deploy/oracle/vm_resume.sh`: refuse `--publish-only` on a HOLD. Anchor: the line
   `START=$(date +%s)` (before `vm_run_watched ... resume_from_checkpoint.py "$MODE"`). Insert before it:
   ```bash
   if [[ "$MODE" == "--publish-only" && "${PUBLISH_COMPARE_OVERRIDE:-0}" != "1" ]]; then
     CMP="$ROOT/logs/compare-publish-$STAMP.json"
     .venv/bin/python scripts/compare_boards.py --candidate "$ROOT/data/checkpoint" --out "$CMP" \
       --ledger-dir "$ROOT/logs/board_versions" ${PUBLISH_COMPARE_ARGS:-} >>"$LOG" 2>&1
     CRC=$?
     if [[ "$CRC" -ne 0 ]]; then
       echo "==> compare_boards exit $CRC (1 HOLD, 2 could not compare): NOT publishing. Read ${CMP%.json}.md." \
            "Accept intended changes with PUBLISH_COMPARE_ARGS='--accept-source-drop SLUG ...';" \
            "PUBLISH_COMPARE_OVERRIDE=1 publishes anyway." | tee -a "$LOG"
       exit 1
     fi
   fi
   ```
3. `src/foreclosure_scraper/main.py`, so the next board records what this one did not (the compare
   already reads both keys from `resume_state.json` when present). Add after
   `log = structlog.get_logger()` (line 78):
   ```python
   def _code_pin() -> str | None:
       """The commit this run executes, for scripts/compare_boards.py's process section."""
       import subprocess
       try:
           return subprocess.run(["git", "rev-parse", "--short", "HEAD"], capture_output=True, text=True,
                                 timeout=10, cwd=Path(__file__).resolve().parents[2]).stdout.strip() or None
       except Exception:  # noqa: BLE001
           return None
   ```
   and in the `summary = {` dict of `run_enrich_tail` (about line 4181), after the `"notes": ...`
   entry (`os` and `re` are imported at the top of main.py):
   ```python
        "code_pin": _code_pin(),
        "run_env": {k: v for k, v in os.environ.items()
                    if k.startswith(("FORECLOSURE_", "FULLRUN_", "ASSESSOR_", "STREETVIEW_", "BOARD_",
                                     "VISION_", "SKIP_TRACE_", "ENRICH_", "RESUME_", "VERIFICATION_"))
                    and not re.search(r"KEY|TOKEN|PASSWORD|SECRET|EMAIL|SHEET|RECIPIENT|SENDER", k)},
   ```
   The named-filter counts and per-phase seconds stay in the run log, where the compare reads them;
   carrying them in `summary` too is the next step (`TailState` already carries
   `off_footprint_removed` the same way).
4. `docs/_config.yml` (D1): `- handoff/` under `exclude`. Check with
   `python3 scripts/check_pages_publish.py` and `python3 scripts/check_payload_size.py`; the repo's
   model of Jekyll's rule (`check_pages_publish.prefix_match`) strips the slash, so it also drops
   `handoff_scorer_to_others_2026-09-21.md` (an internal note). Expected site after it: about
   977 - 118 = 859 MB.

## 7. Seen outside this area (one line each)

- The VM gated run hit 34 phase time caps (lrcpwa_parcel, bk_property, owner_mailing, gis_attrs,
  parcel_lookup, comps, recorded_sales, doc_ocr and others): those enrichers are partial on the
  pending board.
- The Mac's git-ignored plain twins (`docs/listings.json`, `listings_detail.json`,
  `listings_slim.json`) are the 10/1 board and disagree with the 10/7 manifest; manifest-verified
  readers ignore them, a script reading the plain file directly reads a 10/1 board.
- `listings_slim.json.gz` is 69.7 MiB, one file, over GitHub's 50 MiB warning and growing with the
  board.
