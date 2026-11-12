# Hermes directives — 2026-10-15

Supersedes `hermes_directives_2026-10-14_part2.md` (and the two docs before it) for anything
they conflict on. Those stay as history; this is the current state. Same structure as always:
Part 1 what got done, Part 2 what's left (yours or the owner's), Part 3 what I genuinely don't
know.

## Part 1 — What happened overnight (2026-10-14 night → 2026-10-15 morning)

### 1. The 9 remaining CAPTCHA/WAF-gated ROD + document sources — DONE

All resolved with the owner present clearing reCAPTCHAs live (never by me — same boundary as
always). Built/extended:

- `rod/ccs_devexpress.py` (new) — shared parser for the CCS DevExpress grid platform, generalized
  via a live `header_map` resolution to handle both Jasper's combined-role-cell layout and the
  split-column layout Iredell/Craven/Greene/Harnett/Randolph/Stokes all share.
- `rod/nc_tyler.py`'s `parse_selfservice()` — shared by Durham and Wake (Tyler "Self-Service"
  platform); fixed `_SS_HEAD` regex for multi-tract (dual book/page) headers.
- `rod/beaufort_dmp.py` (new) — Beaufort County's free JSON document API.
- `rod/acclaim.py` — Pickens fix + `discover_recent_nods_via_browser()` for Clarendon's
  Cloudflare-cleared-tab reuse.
- `sc_rod_cott.py`/`cott_recordroom.py`/`doc_images.py` — Union County confirmed free (resolved a
  contradiction in the prior notes that had it flagged pay-per-view).
- `nc_rod_captcha.py`'s `_COUNTY_SITES` now covers: wake, durham, brunswick, iredell, craven,
  greene, harnett, randolph, stokes.
- `math_captcha.py` — fixed a false-positive (`solve_math_captcha()` was regexing the whole page
  body and catching phone numbers as fake math expressions); added `_solve_image_question()` using
  the existing Gemini OCR plumbing to genuinely solve Brunswick's image-based question, with real
  post-submit verification.

Measured session-reuse floors (all "at least," none exact): Wake ≥7m14s, Jasper ≥22min (12hr
platform timeout), Iredell ≥11m19s — Iredell confirmed does NOT survive a fresh tab navigation,
must drive the same already-loaded page in place.

Every new `raw` key from this work is registered in `web_artifact.py`'s `RAW_KEEP` (verified via
`tests/test_raw_keep_covers_enrichers.py` before each commit): `brunswick_detail`, `wake_detail`,
`acclaim_rod`, `cott_image_fetch`, `beaufort_rod`, `beaufort_pdf_fetch`, `clarendon_pdf_fetch`,
`jasper_doc_image`, `ccs_devexpress_rod`, `iredell_doc_image`, `craven_doc_image`,
`greene_doc_image`, `harnett_doc_image`, `randolph_doc_image`, `stokes_doc_image`.

### 2. Date-coverage / completeness audit — DONE, all 3 passes

The owner's concern (do rolling lookback windows silently exclude the MOST distressed, oldest-
debt properties?) turned out to be real, but structural rather than in the roll-source scrapers
themselves:

- **Pass 1** (`docs/date_coverage_audit_2026-10-14.md`, current-state-roll sources — tax
  delinquent lists, FLC/forfeited-land, code-enforcement, overage claims): the ~129 candidate
  files were checked for a hidden/code-imposed date filter. Mostly clean; a few real fixes landed
  (`nc_metro_demolition_permits.py`'s stale 730-day window removed + a Mecklenburg endpoint
  migration, 486→15,813 leads; a few tax/demolition scrapers in the same commit `34f70cdb`).
- **Pass 2** (`..._pass2.md`, event-stream sources — ROD recordings, NOD filings, court cases):
  found the real structural gap. `board_persist.py`'s generic "4 consecutive misses → drop" rule
  was dropping rows from sources whose underlying case/lien was still genuinely open, just because
  the source wasn't re-emitting that row every single run. Fixed by extending `AGE_EXEMPT_SOURCES`
  and building real status-aware holds: `nc_ecourts_open_hold()`, `courtlistener_open_hold()`,
  `sc_upstate_open_hold()`. Also fixed `nod_discovery.py`'s fabricated `sale_date` bug (it was
  force-computing `recorded_date+90d` and getting dropped by an unrelated terminal-date rule
  regardless of exemptions — now stores a non-authoritative `raw['nod']['estimated_sale_date']`
  instead).
- **Pass 3** (`..._pass3.md`, consolidation): 8 more sources added to `AGE_EXEMPT_SOURCES`
  (`cash_buyer_deeds`, `anderson_acpass_deeds`, `nc_rowan_cott`, `horry_probate`,
  `nc_heir_notices`, `publicnoticesc_estates`, `nc_unclaimed`, `nc_cchs_deeds`), plus
  `nc_ecourts_divorce` added to the open-judgment hold family, plus two missing
  `DATELESS_OK_SOURCES` entries fixed (`nc_rowan_cott`, `nc_unclaimed` were losing 100% of their
  rows at ingest because `sale_date is None` was tripping `main.py`'s `_active_only()` drop before
  the age-exempt logic ever got a chance to run).

All landed in commits `1e76fc88`, `9fc5c0dd`, `a4e0093d` (the last one also carries item 3 below).
220 tests passing across the touched area; one unrelated pre-existing test failure found during
this work (`test_kit_fetch_drops_sensitive_columns`, a stub signature out of sync with
`_layer_kit.fetch_attrs`'s `max_records` param) was fixed separately in `a23b0d1d` — not part of
the audit itself, just something the full-suite run surfaced.

### 3. CCHS BLOCKED-outcome visibility — DONE

Scrapers hitting a CCHS wall used to silently report `OK (0)`. `rod/cchs.py`'s `_cchs_fetch()` now
re-raises `CchsWall`; each caller (`cash_buyer_deeds.py`, `nc_rod_substitute_trustee.py`,
`nod_discovery.py`) tracks attempted-vs-blocked counties and sets `OUTCOME_PARTIAL`/
`OUTCOME_BLOCKED`; `main.py`'s status line now shows `⚠️ PARTIAL (n) — reason` instead of a
silent `OK (n)`. Commit `a4e0093d`.

### 4. `situs_sanity.py` apostrophe bug — DONE

The shared `_EMBEDDED_ADDR_RE` regex was dropping apostrophes from addresses pipeline-wide (every
source routes through this guard in `main.py`). Fixed, commit `fa1fbe97`.

### 5. Tonight's production backfill — IN PROGRESS, started twice

First attempt launched via `scripts/run_local.sh` SSH'd onto the VM (after fixing a real
cross-platform bug there: unconditional `caffeinate -is`, macOS-only, was exit-127 on Linux —
fixed in `de602de5`). That run completed scraping + dedup cleanly (357,373 deduped rows) but then
**crashed** at `merge_prior_board()` with `BoardLoadTooLarge`: the existing board (4,247 MB)
exceeded `web_artifact.BOARD_PRIOR_MERGE_MAX_SOURCE_MB` (1,200 MB, deliberately calibrated to the
8 GB Mac, not this 23 GiB VM — see that constant's own comment).

Root cause wasn't the ceiling — it's correct and intentional. It was the entry point:
`scripts/run_local.sh` is the Mac-only stealth-browser weekly script; it does not export
`BOARD_PRIOR_MERGE_ALLOW_LARGE=1`, which `deploy/oracle/vm_run.sh` already sets by default
(`vm_lib.sh`, wired after an earlier session's own measured-safe VM trial at 223,832 rows /
2,667 MiB → 11.84 GiB peak, exit 0). Running the Mac script on the VM skipped that override, plus
every other VM-specific safety rail vm_run.sh has (disk/swap/refdata preflights, the memory
watchdog, auto-publish-on-success, checkpoint resumability).

Fix: cleaned up the crashed run's 337 partially-written `docs/` files (shards/manifest mid-stream
from the aborted merge — confirmed safe to discard, not meaningful state) and a 6-day-stale
abandoned `pre_publish` checkpoint from 2026-10-09 (383,378 rows, never published), then relaunched
through the correct script: `RUN_DISCARD_PENDING_PUBLISH=1 setsid nohup bash
deploy/oracle/vm_run.sh` — detached, as its own usage comment specifies. This pulled latest
(`git pull --rebase --autostash`) and landed on `a4e0093d`, so this run carries every fix above,
including Pass 3's. Started 2026-10-15 06:00:16 UTC. **Still running as of this doc** — on
success it auto-publishes to GitHub Pages; check `logs/vm-run-20261015T060016.log` on the VM for
current status.

## Part 2 — What's left

1. **`counties_nc/nc_ecourts_estates.py` and `counties_sc/lexington_probate.py`** — still
   CAPTCHA-gated, same shape as everything fixed in Part 1 item 1. Needs a live-cleared session to
   confirm real selectors and decide whether each source's status field is reachable for an
   `AGE_EXEMPT_SOURCES`/open-hold-style fix. This is squarely your lane.
2. **Once tonight's VM run finishes and publishes**: a zero-row re-triage sweep against the fresh
   board (which sources are still returning 0 that shouldn't be), and a column-accuracy
   re-measurement against current data (baseline: `docs/audit_2026-10-09/column_accuracy.md`, now
   stale). Both explicitly depend on the backfill landing — neither has started.
3. **`national/seeclickfix.py`** — its 1,500-rows/city pagination cap couldn't be live-verified
   this pass; the API is now Cloudflare-walled to plain curl. Low priority — the current-state-
   roll shape is already correctly un-windowed in the code, this is just an unconfirmed cap.
4. **`counties_nc/nc_ecourts_lis_pendens.py`** — a minor dead-code constant from Pass 2; worth
   confirming it's genuinely unused and whether its captured status field deserves the same
   open-hold treatment `nc_ecourts_divorce.py` just got. Low priority.
5. Carried over, still open, unchanged from Part 2:
   - `sc_qpublic.py` — disabled for a real architectural reason (stateful ASP.NET POST form, this
     codebase's tooling is GET-only), not a login/CAPTCHA wall. Bigger project if ever prioritized.
   - `loopnet.py` — confirmed Akamai-walled (403) as of 2026-10-14, a regression from working
     cleanly on 2026-10-04. Worth a fresh check.

## Part 3 — Things I explicitly do not know

- Whether this VM run will complete end-to-end at this scale. The one prior supervised trial that
  calibrated `BOARD_PRIOR_MERGE_ALLOW_LARGE` measured 223,832 rows / 2,667 MiB → 11.84 GiB peak.
  Tonight's board is already 4,247 MB combined source going in — real headroom (23 GiB VM, no
  swap needed last time) but genuinely unconfirmed at this larger size until it actually finishes.
- Whether the three audit passes move the column-accuracy numbers once re-measured — won't know
  until Part 2 item 2 actually runs.
- Whether Hermes's own solver has ever cleared a reCAPTCHA v2 checkbox widget (as opposed to the
  AWS-WAF image-CAPTCHA it's confirmed to solve) — still worth testing directly rather than
  assuming either way. Carried from the prior doc, still unresolved.
- The real ceiling (not just the measured floor) on the CCS DevExpress / Tyler Self-Service
  session-reuse windows.
