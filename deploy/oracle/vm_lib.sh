#!/usr/bin/env bash
# Shared by deploy/oracle/vm_run.sh (the full run) and deploy/oracle/vm_resume.sh (finishing a
# run from its checkpoint), so both load the same secrets and run config, run under the same
# safety (disk / swap / reference-data preflights, the commit pin, the memory watchdog; bottom of
# this file) and publish the same way. Source this; do not execute. Requires ROOT to be set and
# the CWD to be $ROOT.

# vm_load_env <log>: secrets from .secrets/ + the VM run config, exported. Exits 1 when a
# required secret is missing. (Moved verbatim from vm_run.sh, 2026-10-05.)
vm_load_env() {
  local LOG="$1"
  local SECRETS="$ROOT/.secrets"
  # ---- load secrets from .secrets/ (same shape as run_local.sh) --------------
  load() {  # load <ENV_NAME> <file> [required]
    local name="$1" file="$2" required="${3:-}"
    if [[ -f "$file" ]]; then
      export "$name"="$(cat "$file")"
    elif [[ "$required" == "required" ]]; then
      echo "FATAL: required secret $name missing ($file)" | tee -a "$LOG"; exit 1
    fi
  }
  load GOOGLE_SERVICE_ACCOUNT_JSON "$SECRETS/service_account.json" required
  load SHEET_ID                    "$SECRETS/sheet_id.txt"           required
  load GMAIL_APP_PASSWORD          "$SECRETS/gmail_app_password.txt" required
  load ANTHROPIC_API_KEY           "$SECRETS/anthropic_api_key.txt"
  load COURTLISTENER_TOKEN         "$SECRETS/courtlistener_token.txt"
  load GEMINI_API_KEY              "$SECRETS/gemini_api_key.txt"
  for i in $(seq 1 60); do load "GEMINI_API_KEY_$i" "$SECRETS/gemini_api_key_$i.txt"; done
  load GITHUB_MODELS_TOKEN         "$SECRETS/github_models_token.txt"
  load GROQ_API_KEY                "$SECRETS/groq_api_key.txt"
  load OPENROUTER_API_KEY          "$SECRETS/openrouter_api_key.txt"
  load MISTRAL_API_KEY             "$SECRETS/mistral_api_key.txt"
  load NVIDIA_API_KEY              "$SECRETS/nvidia_api_key.txt"
  load GOOGLE_MAPS_API_KEY         "$SECRETS/google_maps_api_key.txt"

  # ---- run config ------------------------------------------------------------
  export GMAIL_SENDER="${GMAIL_SENDER:-highwaymarketingco@gmail.com}"
  export EMAIL_RECIPIENTS="${EMAIL_RECIPIENTS:-greghhigh@gmail.com,cashrandolphhigh@gmail.com}"
  if [[ -n "${GEMINI_API_KEY:-}${GEMINI_API_KEY_1:-}" ]]; then
    export VISION_PROVIDER="${VISION_PROVIDER:-gemini}"
  else
    export VISION_PROVIDER="${VISION_PROVIDER:-anthropic}"
  fi
  export VISION_USE_OLLAMA=0
  export SKIP_TRACE_PROVIDER="${SKIP_TRACE_PROVIDER:-free}"
  export LOG_LEVEL="${LOG_LEVEL:-INFO}"
  export PYTHONUNBUFFERED=1

  # THE SPLIT: run only datacenter-safe sources; the Mac runs the 39 stealth ones
  # and feeds their leads back through national.stealth_handoff.
  export FORECLOSURE_ROLE=vm

  # 24 GB VM has no OOM ceiling, so the assessor-card enricher can run at the
  # higher throughput the 8 GB Mac could not sustain.
  export ASSESSOR_CARD_ON="${ASSESSOR_CARD_ON:-1}"
  export ASSESSOR_CARD_MAX="${ASSESSOR_CARD_MAX:-900}"
  export FORECLOSURE_ASSESSOR_PHOTO="${FORECLOSURE_ASSESSOR_PHOTO:-1}"
  # Street View stays OFF by default on the VM unless a maps key is present, so a
  # fresh VM never risks paid calls.
  if [[ -n "${GOOGLE_MAPS_API_KEY:-}" ]]; then
    export FORECLOSURE_STREETVIEW="${FORECLOSURE_STREETVIEW:-1}"
    export STREETVIEW_MAX="${STREETVIEW_MAX:-300}"
    # Owner-approved 2026-10-05: use Google's free 10,000/month. enrichment_streetview's
    # FREE_TIER_GUARD still clamps this to 9,000 unless STREETVIEW_ALLOW_PAID=1, so it stays free.
    export STREETVIEW_MONTHLY_MAX="${STREETVIEW_MONTHLY_MAX:-9000}"
  fi

  # merge_prior_board() streams the published board rather than fully materializing
  # it (2026-10-04 fix for the BoardLoadTooLarge crash that blocked every VM run
  # from ever reaching write_artifact -- see board_persist.py's module docstring
  # and web_artifact.BOARD_PRIOR_MERGE_MAX_SOURCE_MB's comment), but its ceiling is
  # still calibrated to the 8 GB Mac (same board, same pipeline, same function) --
  # a real, supervised, dual-signal (VmRSS + smaps_rollup Pss) trial on THIS VM
  # against the real board (223,832 rows, 2,667 MiB combined source) measured a
  # clean 11.84 GiB peak and exit 0, comfortably inside this VM's 23 GiB with no
  # swap -- the same "24 GB VM has no OOM ceiling" reasoning ASSESSOR_CARD_ON above
  # already overrides for. Override per-host here, not by raising the shared
  # default and risking the Mac.
  export BOARD_PRIOR_MERGE_ALLOW_LARGE="${BOARD_PRIOR_MERGE_ALLOW_LARGE:-1}"

  # 2026-10-07 register-of-deeds readers and deed chain (HANDOFF item 82). The plain-HTTP platforms were
  # proven live on real board owners, so they run on the VM; the per-platform caps keep one run polite
  # (30 name searches per county per run, coverage grows across runs). The BROWSER-rendered platforms
  # (Harris, Logan Blazor, Logan Remote Access) stay OFF for the run that measures peak memory and time;
  # turn them on per platform with FORECLOSURE_NC_HARRIS_ROD=1 etc. The Mecklenburg delinquent list stays
  # OFF (one-year balances, +29k rows): FORECLOSURE_MECKLENBURG_DELINQUENT=1 to add it.
  export FORECLOSURE_ROD_CHAIN="${FORECLOSURE_ROD_CHAIN:-1}"
  export FORECLOSURE_ROD_CHAIN_BUDGET_S="${FORECLOSURE_ROD_CHAIN_BUDGET_S:-1800}"
  export FORECLOSURE_NC_COTT_ROD="${FORECLOSURE_NC_COTT_ROD:-1}"
  export FORECLOSURE_NC_LOOKUP_ROD="${FORECLOSURE_NC_LOOKUP_ROD:-1}"
  export FORECLOSURE_NC_ORS_ROD="${FORECLOSURE_NC_ORS_ROD:-1}"
  export FORECLOSURE_NC_CCHS_CLASSIC_ROD="${FORECLOSURE_NC_CCHS_CLASSIC_ROD:-1}"
  export FORECLOSURE_NC_TYLER_ROD="${FORECLOSURE_NC_TYLER_ROD:-1}"
  export FORECLOSURE_SC_ORS_ROD="${FORECLOSURE_SC_ORS_ROD:-1}"
  export FORECLOSURE_SC_ACPASS_ROD="${FORECLOSURE_SC_ACPASS_ROD:-1}"
  export FORECLOSURE_NC_HARRIS_ROD="${FORECLOSURE_NC_HARRIS_ROD:-0}"
  export FORECLOSURE_NC_HARRIS_MARRIAGE="${FORECLOSURE_NC_HARRIS_MARRIAGE:-0}"
  export FORECLOSURE_NC_LOGAN_BLAZOR_ROD="${FORECLOSURE_NC_LOGAN_BLAZOR_ROD:-0}"
  export FORECLOSURE_NC_LOGAN_REMOTE_ROD="${FORECLOSURE_NC_LOGAN_REMOTE_ROD:-0}"

  # 2026-10-09 audit (additions_verify): the SC register platforms that are ON by their code default are
  # declared here too, so a changed default can never switch one off unseen; the register passes run
  # their counties side by side (one request at a time per county host still) under their own budgets
  # (the 10/8 run reached 5 of ~60 register counties in the 900 s ROD group cap and the deed chain the
  # same 6 alphabetical counties). Obituary lookups and the Mecklenburg delinquent list stay OFF on
  # purpose (owner decisions pending), declared so the gate sees the choice.
  export FORECLOSURE_SC_PUBLICSEARCH_ROD="${FORECLOSURE_SC_PUBLICSEARCH_ROD:-1}"
  export FORECLOSURE_SC_ACCLAIM_ROD="${FORECLOSURE_SC_ACCLAIM_ROD:-1}"
  export FORECLOSURE_SC_GREENWOOD_ROD="${FORECLOSURE_SC_GREENWOOD_ROD:-1}"
  export FORECLOSURE_SC_RECORDROOM_ROD="${FORECLOSURE_SC_RECORDROOM_ROD:-1}"
  export FORECLOSURE_SC_COTT_ESEARCH_ROD="${FORECLOSURE_SC_COTT_ESEARCH_ROD:-1}"
  export FORECLOSURE_SC_LOOKUP_ROD="${FORECLOSURE_SC_LOOKUP_ROD:-1}"
  # 2026-10-09 top80 (Logan/Harris): county-wide adverse-lien sweep of the two AcclaimWeb registers (Horry,
  # Pickens) matched to every board owner offline; plain HTTP, about 5 s a month of data, cached in data/lien_sweep.
  export FORECLOSURE_SC_LIEN_SWEEP="${FORECLOSURE_SC_LIEN_SWEEP:-1}"
  export FORECLOSURE_LIEN_SWEEP_BUDGET_S="${FORECLOSURE_LIEN_SWEEP_BUDGET_S:-600}"
  # 2026-10-09 top80 (register_other): marriage-index check on the six Cott v4 tenants that publish one
  # (Onslow, Alamance, Alexander, Pamlico, Edgecombe, Rutherford); plain HTTP, 1.6 s a host, 30 lookups a
  # county a run on its own budget; also gated by FORECLOSURE_NC_COTT_ROD.
  # 2026-10-09 top80 (register_cchs_kofile): county-wide adverse-instrument sweeps of 22 Courthouse Computer
  # Systems (classic ASP, LRSearch), GovOS CountyFusion and GovOS/Kofile PublicSearch counties, matched to every
  # board owner offline, plus Beaufort's Marriages index; plain HTTP, cached in data/county_sweeps. Sumter
  # (CountyFusion) and Beaufort (LRSearch) are also read by owner name (30 lookups a county a run).
  export FORECLOSURE_COUNTY_LIEN_SWEEP="${FORECLOSURE_COUNTY_LIEN_SWEEP:-1}"
  export FORECLOSURE_COUNTY_MARRIAGE_SWEEP="${FORECLOSURE_COUNTY_MARRIAGE_SWEEP:-1}"
  export FORECLOSURE_COUNTY_SWEEP_BUDGET_S="${FORECLOSURE_COUNTY_SWEEP_BUDGET_S:-900}"
  export FORECLOSURE_SC_COUNTYFUSION_ROD="${FORECLOSURE_SC_COUNTYFUSION_ROD:-1}"
  export FORECLOSURE_NC_LRSEARCH_ROD="${FORECLOSURE_NC_LRSEARCH_ROD:-1}"
  export FORECLOSURE_REGISTER_CHECKS="${FORECLOSURE_REGISTER_CHECKS:-1}"
  export FORECLOSURE_REGISTER_CHECKS_BUDGET_S="${FORECLOSURE_REGISTER_CHECKS_BUDGET_S:-900}"
  export FORECLOSURE_GENERIC_ROD_BUDGET_S="${FORECLOSURE_GENERIC_ROD_BUDGET_S:-2400}"
  export GENERIC_ROD_COUNTY_CONCURRENCY="${GENERIC_ROD_COUNTY_CONCURRENCY:-8}"
  export ROD_CHAIN_COUNTY_CONCURRENCY="${ROD_CHAIN_COUNTY_CONCURRENCY:-8}"
  # 2026-10-09 top80 (fill group): deed book/page, short legal, value and acreage off the county's own free
  # parcel layer (NC OneMap for every NC county, 15 SC county layers); plain HTTP, 40 parcels a request, 2 s a
  # host, round-robin over counties inside the budget (gis_fill.py). Needs the main.py wiring line in
  # docs/audit_2026-10-09/top80_fill.md.
  export FORECLOSURE_GIS_FILL="${FORECLOSURE_GIS_FILL:-1}"
  export FORECLOSURE_GIS_FILL_BUDGET_S="${FORECLOSURE_GIS_FILL_BUDGET_S:-2400}"
  export OBITUARY_LOOKUPS="${OBITUARY_LOOKUPS:-0}"
  export FORECLOSURE_MECKLENBURG_DELINQUENT="${FORECLOSURE_MECKLENBURG_DELINQUENT:-0}"
  # Richland map-viewer reader: about 4 s a row on one host; 500 fits the 2,400 s resolver cap (the 10/8
  # run read 300 and left 1,775 Richland rows waiting).
  export RICHLAND_PARCEL_MAX="${RICHLAND_PARCEL_MAX:-500}"
}

# vm_publish_board <log> <commit message>: stage the dashboard payload, commit, pull --rebase,
# push. Returns 0 when published or unchanged, 1 when the commit was made but the push failed,
# 2 when the staged payload failed verification (nothing committed).
vm_publish_board() {
  local LOG="$1" MSG="$2"
  . "$ROOT/scripts/board_payload.sh" 2>/dev/null || true
  if command -v board_payload_add >/dev/null 2>&1; then
    board_payload_add "$ROOT"
  else
    git add docs
  fi
  if command -v board_payload_verify_staged >/dev/null 2>&1 && [[ "${VM_PUBLISH_VERIFY:-0}" == "1" ]]; then
    if ! board_payload_verify_staged "$ROOT" >>"$LOG" 2>&1; then
      echo "==> ⚠️  staged board payload failed verification — NOT committing" | tee -a "$LOG"
      return 2
    fi
  fi
  if ! git diff --staged --quiet 2>/dev/null; then
    git commit -q -m "$MSG" 2>>"$LOG" || true
    if ! git pull --rebase --autostash origin main >>"$LOG" 2>&1; then
      # never leave the checkout mid-rebase (the next run would start on a detached HEAD);
      # the push below then fails non-fast-forward and the local commit is kept for a human
      git rebase --abort >>"$LOG" 2>&1 || true
      echo "==> ⚠️  pull --rebase failed (conflict?) — rebase aborted, see log" | tee -a "$LOG"
    fi
    if git push origin main >>"$LOG" 2>&1; then
      echo "==> ✓ dashboard published (Pages updates in ~1 min)" | tee -a "$LOG"
    else
      echo "==> ⚠️  commit made but push failed — see log" | tee -a "$LOG"
      return 1
    fi
  else
    echo "==> dashboard unchanged — nothing to publish" | tee -a "$LOG"
  fi
  return 0
}

# =================================================================================================
# Run safety, shared by vm_run.sh (the full run) and vm_resume.sh (finishing one from a
# checkpoint), 2026-10-06. The 10/5 full run was killed by the KERNEL's OOM killer because
# vm_run.sh had none of what vm_resume.sh already had; both now use these. docs/HANDOFF.md item 72.
# =================================================================================================

# ---- disk -----------------------------------------------------------------------------------------
# What the board PUBLISH needs free, from the capacity proof on this VM (cf372926, scratchpad
# scale/vm_evidence/pub2: the real 270,481-row checkpoint padded to 355,000 rows, the top of the
# 320-355K projection for the next board; expected ~330K):
#   * VM_PUBLISH_BASE_MB 7000: write_artifact's own writes at 355K rows, measured 6,612 MiB at the
#     lowest point: the new listings.json (4.0 GiB) + detail sidecar, slim, parts and shards beside
#     the old ones until the renames, and the 0.3 GiB pre_publish checkpoint; +6% margin.
#   * + the size of the board being REPLACED (docs/listings.json; its parts when there is none):
#     write_artifact copies it to backups/ first (pub2 hard-linked it: 2,432 MiB not counted
#     there), so 9,044 MiB in all for today's 223,832-row board -> 9,432 here. A 355K board
#     replacing a 355K board needs ~11.1 GB. backups/ keeps BOARD_BACKUP_KEEP (3) such copies.
#   * the publish commit's git objects (~0.55 GB at 355K: today's committed payload is 343 MB at
#     223,832 rows, already gzipped, stored ~1:1) land after the write's temp files are gone
#     (pub2 freed 617 MiB between its low point and its end), so they do not raise the peak.
VM_PUBLISH_BASE_MB="${VM_PUBLISH_BASE_MB:-7000}"
# What the full run writes BEFORE it publishes, on top of that:
#   * checkpoints: 0.3 GiB at 355K rows (311 MB measured), twice that while a save replaces the
#     previous one, plus the archived pre-scoring checkpoint a --stop-before-publish run keeps
#     (checkpoint.archive()): ~1 GB
#   * the run log, new parcel photos under docs/parcel_photos (capped per run), data/ caches and
#     browser temp files: not measured on the VM, budgeted at 1 GB
VM_RUN_GROWTH_MB="${VM_RUN_GROWTH_MB:-2000}"

# vm_board_bytes_mb: the size, in MB, of the board a publish replaces (and backs up).
vm_board_bytes_mb() {
  local kb
  if [[ -f "$ROOT/docs/listings.json" ]]; then
    kb=$(du -k "$ROOT/docs/listings.json" 2>/dev/null | awk '{print $1}')
  else
    kb=$(du -ck "$ROOT"/docs/listings_part_*.json.gz 2>/dev/null | awk 'END{print $1}')
  fi
  echo $(( ${kb:-0} / 1024 ))
}

# vm_publish_need_mb / vm_full_run_need_mb: the two disk thresholds, in MB (see above).
vm_publish_need_mb() { echo $(( VM_PUBLISH_BASE_MB + $(vm_board_bytes_mb) )); }
vm_full_run_need_mb() { echo $(( $(vm_publish_need_mb) + VM_RUN_GROWTH_MB )); }

vm_free_mb() { df -Pm "$ROOT" | awk 'NR==2{print $4}'; }

# vm_preflight_disk <log> <need_mb> <why>: 1 (refuse) when $ROOT's filesystem has less free.
vm_preflight_disk() {
  local LOG="$1" NEED="$2" WHY="$3" FREE
  FREE=$(vm_free_mb)
  if [[ -z "$FREE" || "$FREE" -lt "$NEED" ]]; then
    echo "==> disk: ${FREE:-?} MB free, need ${NEED} MB ($WHY) — not starting." \
         "Grow the volume or clear space (backups/, data/checkpoint_archive/, logs/)." | tee -a "$LOG"
    return 1
  fi
  echo "==> disk: ${FREE} MB free, need ${NEED} MB ($WHY)" | tee -a "$LOG"
  return 0
}

# ---- swap -----------------------------------------------------------------------------------------
# vm_preflight_swap <log>: never refuses; LOUD when no swap is active. The VM's 4 GB swapfile was
# enabled by hand and is not in /etc/fstab, so it is gone after any reboot. The publish peaks at
# ~17.8 GB of the 23.4 GiB VM (cf372926); swap is the slack between that and the watchdog's
# MemAvailable+SwapFree kill, and without it the watchdog kills at MemAvailable < 700 MB alone.
vm_preflight_swap() {
  local LOG="$1" SW="${VM_PROC_SWAPS:-/proc/swaps}" FSTAB="${VM_FSTAB:-/etc/fstab}" MB DEVS
  MB=$(awk 'NR>1{s+=$3} END{print int(s/1024)}' "$SW" 2>/dev/null)
  DEVS=$(awk 'NR>1{printf "%s%s", (n++?",":""), $1}' "$SW" 2>/dev/null)
  if [[ -z "$MB" || "$MB" -le 0 ]]; then
    {
      echo "==> !!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!"
      echo "==> !! NO SWAP IS ACTIVE. The 4 GB swapfile is not in /etc/fstab and vanishes on reboot."
      echo "==> !! Re-enable it before a full run:  sudo swapon /swapfile   (swapon --show to check)"
      echo "==> !! Persist it:  echo '/swapfile none swap sw 0 0' | sudo tee -a /etc/fstab"
      echo "==> !! Without swap the publish (~17.8 GB peak) has no slack and the memory watchdog"
      echo "==> !! stops the run as soon as MemAvailable drops under 700 MB."
      echo "==> !!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!"
    } | tee -a "$LOG"
    return 0
  fi
  echo "==> swap: ${MB} MB active (${DEVS})" | tee -a "$LOG"
  if ! awk '$1 !~ /^#/ && $3 == "swap" {f=1} END{exit !f}' "$FSTAB" 2>/dev/null; then
    echo "==> ⚠️  swap is not in $FSTAB: it will be gone after a reboot" \
         "(echo '/swapfile none swap sw 0 0' | sudo tee -a /etc/fstab)" | tee -a "$LOG"
  fi
  return 0
}

# ---- reference data -------------------------------------------------------------------------------
# vm_preflight_refdata <log>: 1 (refuse) when the Mac reference data the run reads is missing or
# damaged (deploy/oracle/refdata_check.py: parcel cache, footprints, parcel inventory, sources).
vm_preflight_refdata() {
  local LOG="$1"
  python3 "$ROOT/deploy/oracle/refdata_check.py" verify --root "$ROOT" 2>&1 | tee -a "$LOG"
  return "${PIPESTATUS[0]}"
}

# ---- the code to run ------------------------------------------------------------------------------
# vm_checkout <log> <pin>: put the checkout at the code to run, or return 1 (refuse).
#   pin set:   fast-forward to EXACTLY that commit; refuse unless HEAD is the pin afterwards (a
#              checkout already past it is refused too). Never pulls anything newer: origin/main
#              moves all day (other agents push). The Mac's stealth hand-off files come with the
#              pinned commit too, so pin a commit made after the day's hand-off landed.
#   no pin:    pull origin/main (code + the Mac's latest hand-off files), as before.
vm_checkout() {
  local LOG="$1" PIN="$2" WANT
  if [[ -n "$PIN" ]]; then
    git fetch origin >>"$LOG" 2>&1 || true
    git merge --ff-only --autostash "$PIN" >>"$LOG" 2>&1 || true
    WANT=$(git rev-parse --verify --quiet "$PIN^{commit}" || echo "unknown")
    if [[ "$(git rev-parse HEAD)" != "$WANT" ]]; then
      echo "==> code is $(git rev-parse --short HEAD), pinned $PIN ($WANT) — not starting" | tee -a "$LOG"
      return 1
    fi
  else
    git pull --rebase --autostash origin main >>"$LOG" 2>&1 || true
  fi
  echo "==> code at $(git rev-parse --short HEAD)${PIN:+ (pinned)}" | tee -a "$LOG"
  return 0
}

# vm_handoff_note <log>: which stealth hand-off the run will ingest, and whether origin has a newer one.
# The hand-off is the sharded directory docs/handoff/stealth_leads/ since 2026-10-09 (the legacy
# single file docs/handoff/stealth_leads.json is read as a fallback): the newest commit touching
# either one is the hand-off this checkout carries.
vm_handoff_note() {
  local LOG="$1" F="docs/handoff/stealth_leads" L="docs/handoff/stealth_leads.json" HERE THERE
  HERE=$(git log -1 --format='%ct %h %ci' -- "$F" "$L" 2>/dev/null)
  THERE=$(git log -1 --format='%ct %h %ci' origin/main -- "$F" "$L" 2>/dev/null)
  if [[ -z "$HERE" ]]; then
    echo "==> ⚠️  no stealth hand-off ($F/ or $L) in this checkout" | tee -a "$LOG"; return 0
  fi
  echo "==> stealth hand-off: ${HERE#* } ($(( ($(date +%s) - ${HERE%% *}) / 3600 ))h old)" | tee -a "$LOG"
  if [[ -n "$THERE" && "${THERE%% *}" -gt "${HERE%% *}" ]]; then
    echo "==> ⚠️  origin/main has a newer hand-off (${THERE#* }) than this pinned checkout" | tee -a "$LOG"
  fi
  return 0
}

# ---- one board job at a time ----------------------------------------------------------------------
vm_board_job_active() {
  pgrep -f -- "${VM_BOARD_JOB_PATTERN:--m foreclosure_scraper|resume_from_checkpoint\.py|reconcile_board\.py}" >/dev/null 2>&1
}

# ---- what the run swallowed -----------------------------------------------------------------------
# vm_report_swallowed <log>: every step that logged <step>.failed (with a traceback) or hit its time
# cap, counted, at the end of the run log (deploy/oracle/run_failures.py). main.py carries on past
# each, and neither the summary, run_health, the digest email nor the exit code says so. Report
# only: never changes the exit code. (audit 2026-10-09, pipeline_gate)
vm_report_swallowed() {
  local LOG="$1"
  python3 "$ROOT/deploy/oracle/run_failures.py" "$LOG" 2>/dev/null | tee -a "$LOG" || true
}

# ---- the memory watchdog --------------------------------------------------------------------------
# vm_alive <pid>: 0 while the process runs (an exited child not yet reaped is a zombie: not alive)
vm_alive() { local s; s=$(ps -o stat= -p "$1" 2>/dev/null | tr -d ' '); [[ -n "$s" && "$s" != Z* ]]; }

# vm_run_watched <log> <memlog> <env prefix> <command...>: run the command in the background under
# deploy/oracle/mem_watchdog.py (dual signal: tree rss+swap > <P>_KILL_TOTAL_MB, or MemAvailable <
# <P>_KILL_AVAIL_MB with SwapFree < <P>_KILL_SWAPFREE_MB; defaults 25600 / 700 / 400, the limits
# vm_resume.sh has used since 10/5), wait, and set VM_RC: the command's exit code, 137 when the
# watchdog stopped it, 70 when the watchdog could not run (the job is then stopped: never unwatched).
vm_run_watched() {
  local LOG="$1" MEMLOG="$2" P="$3"; shift 3
  local KT="${P}_KILL_TOTAL_MB" KA="${P}_KILL_AVAIL_MB" KS="${P}_KILL_SWAPFREE_MB"
  local WATCHDOG="${VM_MEM_WATCHDOG:-$ROOT/deploy/oracle/mem_watchdog.py}" PID WD
  "$@" >>"$LOG" 2>&1 &
  PID=$!
  python3 "$WATCHDOG" --pid "$PID" --log "$MEMLOG" \
    --kill-total-mb "${!KT:-25600}" --kill-avail-mb "${!KA:-700}" \
    --kill-swapfree-mb "${!KS:-400}" >>"$LOG" 2>&1 &
  WD=$!
  sleep "${VM_WATCHDOG_GRACE_S:-3}"
  if ! vm_alive "$WD"; then
    # it exits 0 when the job ended and 9 when it killed it; anything else is a watchdog that
    # never ran (no python3, no /proc, bad arguments)
    wait "$WD"; local WRC=$?
    if [[ "$WRC" -ne 0 && "$WRC" -ne 9 ]]; then
      echo "==> ⚠️  the memory watchdog failed (exit $WRC, see the log): stopping the job rather" \
           "than running it unwatched" | tee -a "$LOG"
      if vm_alive "$PID"; then pkill -TERM -P "$PID" 2>/dev/null; kill -TERM "$PID" 2>/dev/null; fi
      wait "$PID" 2>/dev/null
      VM_RC=70
      return 0
    fi
  fi
  wait "$PID"
  VM_RC=$?
  wait "$WD" 2>/dev/null
  tail -1 "$MEMLOG" 2>/dev/null | tee -a "$LOG"
  if grep -q "^KILLED" "$MEMLOG" 2>/dev/null; then
    echo "==> ⚠️  stopped by the memory watchdog: $(grep '^KILLED' "$MEMLOG" | tail -1)" | tee -a "$LOG"
    VM_RC=137
  fi
  return 0
}
