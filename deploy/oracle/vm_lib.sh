#!/usr/bin/env bash
# Shared by deploy/oracle/vm_run.sh (the full run) and deploy/oracle/vm_resume.sh (finishing a
# run from its checkpoint), so both load the same secrets and run config and publish the same
# way. Source this; do not execute. Requires ROOT to be set and the CWD to be $ROOT.

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
