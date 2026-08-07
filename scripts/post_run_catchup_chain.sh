#!/usr/bin/env bash
# Fires once the live weekly run (started 2026-08-06 09:29) finishes and
# releases the board, then lands everything that's been waiting on it:
# new sources + the coastal bypass fix, geocode payoff, skip-trace at the
# raised caps, and vision (free pool + the $38 Anthropic budget).
#
# Waits rather than running now because the main run holds the board in
# memory and will overwrite docs/listings.json wholesale when it publishes —
# anything scored against the current (Aug 3) published board before then is
# thrown away the moment the live run finishes. One board-writer at a time.
set -uo pipefail
ROOT="/Users/cashhigh/foreclosure-scraper"
cd "$ROOT"
SECRETS="$ROOT/.secrets"
LOG="$ROOT/logs/post-run-catchup-$(date +%Y%m%dT%H%M%S).log"
UV="$HOME/.local/bin/uv"

echo "==> waiting for the live run + any merge to clear $(date)" | tee -a "$LOG"
while pgrep -f "foreclosure_scraper.__main__|-m foreclosure_scraper|run_local.sh|merge_today_sources.py" >/dev/null; do
  sleep 300
done
echo "==> board is clear, starting catchup chain $(date)" | tee -a "$LOG"

load() { [[ -f "$2" ]] && export "$1"="$(cat "$2")"; }

# --- 1. land the sources built today + the coastal bypass fix -------------
# merge_today_sources.py imports main._in_scope FRESH, so this is also how
# the 450-lead coastal fix actually reaches the published board — the live
# run loaded main.py before that fix existed.
echo "==> merge_today_sources $(date)" | tee -a "$LOG"
ASSESSOR_CARD_ON=1 ASSESSOR_CARD_SKIP_RENDER=1 "$UV" run python scripts/merge_today_sources.py >>"$LOG" 2>&1
echo "==> merge exit=$? $(date)" | tee -a "$LOG"

# --- 2. pay off the geocode budget the run's 600s cap left unmapped -------
echo "==> catchup_geocode $(date)" | tee -a "$LOG"
"$UV" run python scripts/catchup_geocode.py >>"$LOG" 2>&1
echo "==> geocode exit=$? $(date)" | tee -a "$LOG"

# --- 3. skip trace at the raised caps (free: address always, phone widened) ---
echo "==> skip_trace catchup $(date)" | tee -a "$LOG"
"$UV" run python scripts/catchup_failed_enrichers.py --only skip_trace >>"$LOG" 2>&1
echo "==> skip_trace exit=$? $(date)" | tee -a "$LOG"

# --- 4. vision: full free pool + the funded $38 Anthropic budget ----------
for i in $(seq 1 60); do load "GEMINI_API_KEY_$i" "$SECRETS/gemini_api_key_$i.txt"; done
load GITHUB_MODELS_TOKEN "$SECRETS/github_models_token.txt"
[[ -z "${GITHUB_MODELS_TOKEN:-}" ]] && export GITHUB_MODELS_TOKEN="$(gh auth token 2>/dev/null || true)"
load GROQ_API_KEY          "$SECRETS/groq_api_key.txt"
load OPENROUTER_API_KEY    "$SECRETS/openrouter_api_key.txt"
load MISTRAL_API_KEY       "$SECRETS/mistral_api_key.txt"
load CLOUDFLARE_API_TOKEN  "$SECRETS/cloudflare_api_token.txt"
load CLOUDFLARE_ACCOUNT_ID "$SECRETS/cloudflare_account_id.txt"
load NVIDIA_API_KEY        "$SECRETS/nvidia_api_key.txt"
load ANTHROPIC_API_KEY     "$SECRETS/anthropic_api_key.txt"

export VISION_USE_OLLAMA=0
export VISION_INCLUDE_ANTHROPIC=1        # opt-in: mix paid into the free pool
export VISION_MAX_SPEND_USD=38           # hard $ stop on the anthropic path only
export ANTHROPIC_VISION_MODEL=claude-haiku-4-5
export VISION_MAX_LISTINGS=15000         # covers the full measured backlog
export VISION_INTER_CALL_DELAY=4
export VISION_BACKEND_STRIKES=10
export VISION_BACKEND_COOLDOWN=70
export VISION_MAX_SECONDS=28800          # 8h ceiling
export PYTHONUNBUFFERED=1

echo "==> vision catchup (free pool + \$38 anthropic budget) $(date)" | tee -a "$LOG"
"$UV" run python scripts/patch_vision_gemini.py >>"$LOG" 2>&1
RC=$?
echo "==> vision exit=$RC $(date)" | tee -a "$LOG"

echo "==> catchup chain complete $(date)" | tee -a "$LOG"
