#!/usr/bin/env bash
# The VM side of the cloud split — the datacenter host's run.
#
# Linux analog of scripts/run_local.sh, minus the macOS bits (no caffeinate /
# launchd). It runs only the datacenter-safe sources (FORECLOSURE_ROLE=vm),
# ingests the Mac's stealth hand-off (national.stealth_handoff), does ALL the
# RAM-heavy enrichment, and publishes the board to GitHub Pages.
#
# Run manually:   bash deploy/oracle/vm_run.sh
# Scheduled:      systemd timer (deploy/oracle/install_timer.sh)
set -uo pipefail

ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
cd "$ROOT"
export PATH="$HOME/.local/bin:$PATH"

SECRETS="$ROOT/.secrets"
mkdir -p "$ROOT/logs" "$ROOT/docs/handoff"
STAMP="$(date +%Y%m%dT%H%M%S)"
LOG="$ROOT/logs/vm-run-$STAMP.log"

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
fi

echo "==> VM run $STAMP  role=vm  vision=$VISION_PROVIDER  log=$LOG" | tee -a "$LOG"
uv sync --frozen >>"$LOG" 2>&1 || uv sync >>"$LOG" 2>&1

# Pull the Mac's stealth hand-off (+ any board changes) before running.
git pull --rebase --autostash origin main >>"$LOG" 2>&1 || true

START=$(date +%s)
uv run python -m foreclosure_scraper >>"$LOG" 2>&1
RC=$?
echo "==> exit=$RC  elapsed=$(( ($(date +%s)-START)/60 ))m  $(date)" | tee -a "$LOG"

# Fail-loud signals surfaced at the tail (mirror run_local.sh).
if grep -q "count_drop_alert" "$LOG"; then
  echo "==> ⚠️  COUNT-DROP ALERT — a source may be broken. See log." | tee -a "$LOG"; RC=2
fi
TOTAL=$(grep '"event": "web_artifact.written"' "$LOG" | grep -oE '"listings": [0-9]+' | tail -1 | grep -oE '[0-9]+' || echo "")
[[ -n "$TOTAL" ]] && echo "==> total listings this run: $TOTAL" | tee -a "$LOG"

# ---- publish board to GitHub Pages on a healthy run ------------------------
if [[ "$RC" -eq 0 && -f "$ROOT/docs/listings.json" ]]; then
  . "$ROOT/scripts/board_payload.sh" 2>/dev/null || true
  if command -v board_payload_add >/dev/null 2>&1; then
    board_payload_add "$ROOT"
  else
    git add docs
  fi
  if ! git diff --staged --quiet 2>/dev/null; then
    git commit -q -m "vm run: refresh dashboard data ($(date +%Y-%m-%d))" 2>>"$LOG" || true
    git pull --rebase --autostash origin main >>"$LOG" 2>&1 || true
    if git push origin main >>"$LOG" 2>&1; then
      echo "==> ✓ dashboard published (Pages updates in ~1 min)" | tee -a "$LOG"
    else
      echo "==> ⚠️  commit made but push failed — see log" | tee -a "$LOG"
    fi
  else
    echo "==> dashboard unchanged — nothing to publish" | tee -a "$LOG"
  fi
else
  echo "==> skipping publish (RC=$RC)" | tee -a "$LOG"
fi

ls -1t "$ROOT"/logs/vm-run-*.log 2>/dev/null | tail -n +13 | xargs rm -f 2>/dev/null || true
exit $RC
