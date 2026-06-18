#!/usr/bin/env bash
# Daily incremental Gemini Vision pass.
#
# The weekly crawl (run_local.sh) refreshes the data; this fills in AI
# condition-analysis on the un-scored listings each day, up to whatever free
# Gemini quota allows that day. Over the week, coverage builds up. Then it
# republishes the dashboard. Free — uses the rotating Gemini keys in .secrets/.
set -uo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
SECRETS="$ROOT/.secrets"
mkdir -p "$ROOT/logs"
LOG="$ROOT/logs/daily-vision-$(date +%Y%m%dT%H%M%S).log"

# Load every free vision credential present. The vision pool uses ALL of them
# (each Gemini key = one project's free quota; GitHub Models + Groq + local
# Ollama are separate free pools) and rotates across them.
load() { [[ -f "$2" ]] && export "$1"="$(cat "$2")"; }
load GEMINI_API_KEY   "$SECRETS/gemini_api_key.txt"
for i in $(seq 1 60); do load "GEMINI_API_KEY_$i" "$SECRETS/gemini_api_key_$i.txt"; done

# GitHub Models (free) — prefer a saved token, else fall back to the gh CLI.
load GITHUB_MODELS_TOKEN "$SECRETS/github_models_token.txt"
[[ -z "${GITHUB_MODELS_TOKEN:-}" ]] && export GITHUB_MODELS_TOKEN="$(gh auth token 2>/dev/null || true)"
# Groq (free) — optional, only if a key is dropped in.
load GROQ_API_KEY "$SECRETS/groq_api_key.txt"

export VISION_PROVIDER=gemini
export VISION_MAX_LISTINGS="${VISION_MAX_LISTINGS:-1500}"   # let daily quota be the limiter
export VISION_INTER_CALL_DELAY="${VISION_INTER_CALL_DELAY:-4}"
export PYTHONUNBUFFERED=1

echo "==> daily vision $(date)" | tee -a "$LOG"
uv run python scripts/patch_vision_gemini.py >>"$LOG" 2>&1
RC=$?
echo "==> exit=$RC $(date)" | tee -a "$LOG"

# Keep 14 most recent daily-vision logs.
ls -1t "$ROOT"/logs/daily-vision-*.log 2>/dev/null | tail -n +15 | xargs rm -f 2>/dev/null || true
exit $RC
