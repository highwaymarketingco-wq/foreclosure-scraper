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

# Skip on full-run days — run_local.sh (the full weekly pipeline) fires at 9:30 on
# these weekdays and is a SUPERSET of this daily refresh, so running both would
# race on docs/listings.json + the git push. date +%u: 1=Mon..7=Sun. 2=Tuesday.
FULL_RUN_DAYS="${FULL_RUN_DAYS:-2 5}"   # space/comma-free list of weekday numbers
if [[ " ${FULL_RUN_DAYS//,/ } " == *" $(date +%u) "* ]]; then
  echo "==> $(date '+%a') is a full-run day; the weekly run_local.sh handles today — skipping daily." | tee -a "$LOG"
  exit 0
fi

# ONE BOARD WRITER AT A TIME — a real lock, held for this whole script.
#
# This replaces two weaker guards that used to sit here: a pgrep list (TOCTOU by
# construction — a check before the critical section can always lose to a writer
# that starts after it) and a private .daily-vision.lock that only ever excluded
# ANOTHER COPY OF THIS SCRIPT. The second one is the important loss: this job
# holds a loaded board for up to VISION_MAX_SECONDS=14400 (4h), and the private
# lock did nothing to stop the noon lrcpwa pass and the 2pm SOS pass writing
# inside that window. On 2026-08-10 this job wrote its 09:33 board back at 13:36
# and reverted the noon pass's 1,064 resolved parcels, 343 county values and 410
# absentee tags. Nothing errored.
#
# The lock covers daily_api_refresh.py AND patch_vision_gemini.py, both of which
# are board writers, and it is reentrant via FORECLOSURE_BOARD_LOCK_HELD so each
# of them proceeds inside this lock rather than deadlocking against it. A lock
# left behind by a killed run is broken automatically — see scripts/board_lock.sh.
. "$ROOT/scripts/board_lock.sh"
if ! board_lock_acquire "$ROOT" "run_daily_vision.sh"; then
  echo "==> another board writer ($(board_lock_holder)) holds the board; skipping daily-vision." | tee -a "$LOG"
  exit 0
fi
trap 'board_lock_release' EXIT INT TERM

# Local Ollama removed (redundant vs the 4 cloud pools; too slow/weak on 8GB).
# Re-enable by installing Ollama + `ollama pull qwen2.5vl:3b` and unsetting this.
export VISION_USE_OLLAMA=0

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
# More free API pools — each activates only if its key file exists.
load OPENROUTER_API_KEY    "$SECRETS/openrouter_api_key.txt"
load MISTRAL_API_KEY       "$SECRETS/mistral_api_key.txt"
load CLOUDFLARE_API_TOKEN  "$SECRETS/cloudflare_api_token.txt"
load CLOUDFLARE_ACCOUNT_ID "$SECRETS/cloudflare_account_id.txt"
# NVIDIA NIM (free) — one key, many vision models (each its own ~40 RPM lane).
load NVIDIA_API_KEY        "$SECRETS/nvidia_api_key.txt"

export VISION_PROVIDER=gemini
# Let the free DAILY QUOTA (and the 4h wall clock below) be the limiter, not an
# arbitrary count. 1500 was NOT letting quota be the limiter: every recent pass
# drained its 1500 and exited with unscored_remaining=0 in 5-17 minutes out of a
# 4-hour budget (logs/daily-vision-*.log: 972 scored in 999s, 976 in 1006s, 956
# in 991s). 6000 was raised for the same reason on 2026-07: measured 2026-08-07,
# the eligible-and-unscored backlog is 9,326 (board has grown since 6000 was
# set), so 6000 was ITSELF now the arbitrary limiter it was raised to eliminate.
# 15000 comfortably clears today's backlog with room for board growth; quota/
# time remain the real stop, same as the 6000->1500 change.
export VISION_MAX_LISTINGS="${VISION_MAX_LISTINGS:-15000}"
export VISION_INTER_CALL_DELAY="${VISION_INTER_CALL_DELAY:-4}"
# Free-tier 429s are usually PER-MINUTE rate limits, not daily exhaustion. Keep a
# rate-limited backend cooling-down-and-retrying instead of retiring it after 2
# strikes (which used to kill the whole 9-key Gemini fleet in ~2 min). High strike
# tolerance + a cooldown that outlasts the 1-min window keeps the pool alive so it
# scores steadily whenever quota frees up.
export VISION_BACKEND_STRIKES="${VISION_BACKEND_STRIKES:-10}"
export VISION_BACKEND_COOLDOWN="${VISION_BACKEND_COOLDOWN:-70}"
# Wall-clock cap so a slow local-Ollama floor pass can't run into the next
# scheduled job (which the lock above would otherwise make skip). 4h.
export VISION_MAX_SECONDS="${VISION_MAX_SECONDS:-14400}"
export PYTHONUNBUFFERED=1

# Daily API refresh FIRST: re-pull the browserless JSON sources (Fannie REO,
# HUD, VA, foreclosure.com, CourtListener…) and merge, so day-old REO that has
# sold drops out and its deep-link stops 404'ing, and fresh inventory appears.
# Runs before vision so vision scores the now-current set. Non-fatal: if it
# fails we still run vision on yesterday's data.
echo "==> daily api refresh (fresh Fannie/REO links, kills 404s) $(date)" | tee -a "$LOG"
uv run python scripts/daily_api_refresh.py >>"$LOG" 2>&1 \
  || echo "==> api refresh failed (continuing to vision on existing data)" | tee -a "$LOG"

echo "==> daily vision $(date)" | tee -a "$LOG"
uv run python scripts/patch_vision_gemini.py >>"$LOG" 2>&1
RC=$?
echo "==> exit=$RC $(date)" | tee -a "$LOG"

# Keep 14 most recent daily-vision logs.
ls -1t "$ROOT"/logs/daily-vision-*.log 2>/dev/null | tail -n +15 | xargs rm -f 2>/dev/null || true
exit $RC
