#!/usr/bin/env bash
# Local weekly run — the free, stealth-browser pipeline on this Mac.
#
# Loads secrets from .secrets/, runs the full foreclosure pipeline (which
# writes the Google Sheet + emails Greg & Cash), and logs to logs/.
#
# Run manually:           bash scripts/run_local.sh
# Run via launchd:        installed by scripts/install_local_schedule.sh
#
# 100% free: no Apify, no proxies. Anti-bot sites (Zillow/Tyler/law firms)
# are handled by the local Scrapling stealth browser — which is exactly why
# this runs on your Mac and not on headless CI.
set -uo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

SECRETS="$ROOT/.secrets"
mkdir -p "$ROOT/logs"
STAMP="$(date +%Y%m%dT%H%M%S)"
LOG="$ROOT/logs/local-run-$STAMP.log"

# ONE BOARD WRITER AT A TIME, for the whole multi-hour run + publish.
#
# This is the longest board-holder there is, so it is also the one most often on
# the losing side of a silent revert: every guard elsewhere was a pgrep taken
# BEFORE the other job's critical section opened, which cannot see a writer that
# starts later. The lock is held from here through `git push`, is reentrant via
# FORECLOSURE_BOARD_LOCK_HELD (so the pipeline's own board writers proceed
# inside it), and a lock left by a killed run is broken automatically. See
# scripts/board_lock.sh.
. "$ROOT/scripts/board_lock.sh"
. "$ROOT/scripts/board_payload.sh"
if ! board_lock_acquire "$ROOT" "run_local.sh"; then
  echo "==> another board writer ($(board_lock_holder)) holds the board; refusing to start." | tee -a "$LOG"
  exit 0
fi
trap 'board_lock_release' EXIT INT TERM

# ---- load secrets from .secrets/ -------------------------------------------
load() {  # load <ENV_NAME> <file> [required]
  local name="$1" file="$2" required="${3:-}"
  if [[ -f "$file" ]]; then
    export "$name"="$(cat "$file")"
  elif [[ "$required" == "required" ]]; then
    echo "FATAL: required secret $name missing ($file)" | tee -a "$LOG"
    exit 1
  fi
}

load GOOGLE_SERVICE_ACCOUNT_JSON "$SECRETS/service_account.json" required
load SHEET_ID                    "$SECRETS/sheet_id.txt"         required
load GMAIL_APP_PASSWORD          "$SECRETS/gmail_app_password.txt" required
load ANTHROPIC_API_KEY           "$SECRETS/anthropic_api_key.txt"
load COURTLISTENER_TOKEN         "$SECRETS/courtlistener_token.txt"
load NC_ECOURTS_USERNAME         "$SECRETS/nc_ecourts_username.txt"
load NC_ECOURTS_PASSWORD         "$SECRETS/nc_ecourts_password.txt"

# Gemini Vision keys — one per Google account (free tier 1500 req/day each).
# The vision code auto-rotates to the next key when one hits its daily limit,
# so 4 keys = ~6000 free calls/day. Drop each account's key in its own file:
#   .secrets/gemini_api_key_1.txt  (account 1)  ... gemini_api_key_4.txt
load GEMINI_API_KEY              "$SECRETS/gemini_api_key.txt"
# One free key per Gemini project; auto-load every gemini_api_key_N.txt.
for i in $(seq 1 60); do load "GEMINI_API_KEY_$i" "$SECRETS/gemini_api_key_$i.txt"; done
# GitHub Models (free, separate pool) — saved token or gh CLI fallback.
load GITHUB_MODELS_TOKEN         "$SECRETS/github_models_token.txt"
[[ -z "${GITHUB_MODELS_TOKEN:-}" ]] && export GITHUB_MODELS_TOKEN="$(gh auth token 2>/dev/null || true)"
# Groq (free, separate pool) — optional.
load GROQ_API_KEY                "$SECRETS/groq_api_key.txt"
# Local Ollama removed (redundant vs cloud pools; slow/weak on 8GB).
export VISION_USE_OLLAMA=0
# More free API pools — each activates only if its key file exists.
load OPENROUTER_API_KEY          "$SECRETS/openrouter_api_key.txt"
load MISTRAL_API_KEY             "$SECRETS/mistral_api_key.txt"
load CLOUDFLARE_API_TOKEN        "$SECRETS/cloudflare_api_token.txt"
load CLOUDFLARE_ACCOUNT_ID       "$SECRETS/cloudflare_account_id.txt"
# NVIDIA NIM (free) — one key, many vision models (each its own ~40 RPM lane).
load NVIDIA_API_KEY             "$SECRETS/nvidia_api_key.txt"

# ---- defaults (config.py also defaults these, set here for clarity) --------
export GMAIL_SENDER="${GMAIL_SENDER:-highwaymarketingco@gmail.com}"
export EMAIL_RECIPIENTS="${EMAIL_RECIPIENTS:-greghhigh@gmail.com,cashrandolphhigh@gmail.com}"
# Vision provider: prefer FREE Gemini when any Gemini key is present
# (4 accounts auto-rotate); fall back to Anthropic only if no Gemini key.
if [[ -n "${GEMINI_API_KEY:-}${GEMINI_API_KEY_1:-}${GEMINI_API_KEY_2:-}" ]]; then
  export VISION_PROVIDER="${VISION_PROVIDER:-gemini}"
else
  export VISION_PROVIDER="${VISION_PROVIDER:-anthropic}"
fi
export LOG_LEVEL="${LOG_LEVEL:-INFO}"
export PYTHONUNBUFFERED=1

# Free skip tracing: reliable tax-records owner + mailing address, plus
# best-effort people-search phone for the most imminent sales. Zero cost.
export SKIP_TRACE_PROVIDER="${SKIP_TRACE_PROVIDER:-free}"
export FREE_SKIPTRACE_PHONE_MAX="${FREE_SKIPTRACE_PHONE_MAX:-40}"

# Photo supply (operator-enabled 2026-07-29): free assessor drive-by photos +
# Street View at 300/run (= the Google-side daily quota; monthly ledger clamped
# under the 10k free tier — STREETVIEW_ALLOW_PAID stays unset, so \$0.00).
export FORECLOSURE_ASSESSOR_PHOTO="${FORECLOSURE_ASSESSOR_PHOTO:-1}"
export FORECLOSURE_STREETVIEW="${FORECLOSURE_STREETVIEW:-1}"
export STREETVIEW_MAX="${STREETVIEW_MAX:-300}"
load GOOGLE_MAPS_API_KEY "$SECRETS/google_maps_api_key.txt"

# Assessor property-card enricher — ON for the weekly run. The default cap
# (150) is below the ~280 live targets, so raise it to 400 to cover them all.
export ASSESSOR_CARD_ON="${ASSESSOR_CARD_ON:-1}"
export ASSESSOR_CARD_MAX="${ASSESSOR_CARD_MAX:-400}"

# Enrichment budget — keep the run finishing in a sane window. The cloud
# run died at 4h partly on a Gemini-quota Vision spiral; locally we use
# Anthropic (set above) and cap Vision so the run completes. ROD deed
# enrichment stays OFF (broken vendor portals = 27 min for 0 matches).
#
# Vision budget — the pool is FREE and 26 backends wide (9 Gemini keys +
# GitHub Models + Groq + Mistral + Cloudflare + 13 NVIDIA NIM lanes), one
# worker per backend off a shared queue. Measured drain: ~90 listings/min
# (logs/daily-vision-*.log). 800 was a paid-Anthropic-era number and left
# most of the free capacity unused — the board carries ~5.9k photo-bearing
# leads, so 800/run could never cover it.
#
# 2500 (prioritized: soonest sale date, then never-scored) ≈ 28 min at the
# measured rate. TRADEOFF: ~15 min more wall clock than the 800 cap for
# ~3x the condition coverage. Unscored fall back to the regex/age tier.
export VISION_MAX_LISTINGS="${VISION_MAX_LISTINGS:-2500}"
export VISION_INTER_CALL_DELAY="${VISION_INTER_CALL_DELAY:-4}"
# Wall-clock cap — THE stop. The count above only sets how much we try; this
# is what guarantees the phase ends. 45 min covers 2500 at the measured rate
# with headroom for a degraded pool, and can never hang the run.
export VISION_MAX_SECONDS="${VISION_MAX_SECONDS:-2700}"
# Sold-comp pool gets its own (smaller) cap + budget so it can't eat the
# active-listing pass; ~89-400 comps ≈ a few minutes.
export SOLD_POOL_VISION_MAX_LISTINGS="${SOLD_POOL_VISION_MAX_LISTINGS:-400}"
export SOLD_POOL_VISION_MAX_SECONDS="${SOLD_POOL_VISION_MAX_SECONDS:-600}"
# Catch-up pass for leads the name-resolver just gave an address to.
export VISION_CATCHUP_MAX_LISTINGS="${VISION_CATCHUP_MAX_LISTINGS:-1500}"
export VISION_CATCHUP_MAX_SECONDS="${VISION_CATCHUP_MAX_SECONDS:-900}"

# Photo gallery budget — the UPSTREAM unlock for Vision (no photo = no
# condition grade, whatever the Vision cap is). ~10.1k board leads have an
# address but <3 photos and the old 500 cap reached 5% of them per run.
# HomeHarvest is slow (~19 leads/min on 4 threads), so the honest limiter is
# the 40-min wall clock, not the count: expect ~750-800 leads/run.
# TRADEOFF: ~14 min more wall clock than the old count-capped ~26 min.
export FORECLOSURE_PHOTO_MAX_TARGETS="${FORECLOSURE_PHOTO_MAX_TARGETS:-2500}"
export FORECLOSURE_PHOTO_MAX_SECONDS="${FORECLOSURE_PHOTO_MAX_SECONDS:-2400}"
# Keep rate-limited vision backends alive (cooldown+retry) instead of retiring
# them after 2 strikes — a too-low threshold killed the whole Gemini fleet in
# ~2 min. See run_daily_vision.sh for the rationale.
export VISION_BACKEND_STRIKES="${VISION_BACKEND_STRIKES:-10}"
export VISION_BACKEND_COOLDOWN="${VISION_BACKEND_COOLDOWN:-70}"
# ROD_ENRICH_ON unset = skipped (default).

# If no NC eCourts creds are present, fall back to anonymous access.
if [[ -z "${NC_ECOURTS_USERNAME:-}" ]]; then
  export NC_ECOURTS_USE_ANONYMOUS=1
fi

# Stealth-browser tuning (real browsers are heavy; keep concurrency modest).
export RENDER_HEADLESS="${RENDER_HEADLESS:-1}"
export RENDER_CONCURRENCY="${RENDER_CONCURRENCY:-2}"

echo "==> foreclosure-scraper local run $STAMP" | tee -a "$LOG"
echo "==> sheet=${SHEET_ID:0:8}…  vision=$VISION_PROVIDER  log=$LOG" | tee -a "$LOG"

# Ensure deps + the stealth browser are present (idempotent, fast if cached).
uv sync --frozen >>"$LOG" 2>&1 || uv sync >>"$LOG" 2>&1
uv run python -m playwright install chromium >>"$LOG" 2>&1 || true
uv run scrapling install >>"$LOG" 2>&1 || true

# ---- run the pipeline ------------------------------------------------------
# caffeinate -is: hold OFF idle sleep (-i) and system sleep (-s) for the whole
# multi-hour run. The board froze for ~3 weeks because the laptop slept mid-run
# and the pipeline never reached the artifact write. This is the single biggest
# reliability fix short of an always-on host. caffeinate propagates the child's
# exit code, so RC=$? below stays correct. (A closed lid on battery can still
# sleep — a plugged-in machine with the lid open is the reliable setup.)
START=$(date +%s)
caffeinate -is uv run python -m foreclosure_scraper >>"$LOG" 2>&1
RC=$?
END=$(date +%s)

echo "==> exit=$RC  elapsed=$(( (END-START)/60 ))m  $(date)" | tee -a "$LOG"

# Surface the fail-loud signals from the run so they're visible at the
# tail of the log (and to anything tailing it / parsing exit status).
if grep -q "count_drop_alert" "$LOG"; then
  echo "==> ⚠️  COUNT-DROP ALERT fired this run — a source may be broken. See log above." | tee -a "$LOG"
  RC=2
fi
# Read the REAL listing count from the artifact-write event (not a stray
# "total": from some sub-summary — that false-positived a 47 once and blocked
# a healthy 5073-listing publish). Fall back to run_meta.json if absent.
TOTAL=$(grep '"event": "web_artifact.written"' "$LOG" | grep -oE '"listings": [0-9]+' | tail -1 | grep -oE '[0-9]+' || echo "")
if [ -z "$TOTAL" ] && [ -f "$ROOT/docs/run_meta.json" ]; then
  TOTAL=$(grep -oE '"total": [0-9]+' "$ROOT/docs/run_meta.json" | head -1 | grep -oE '[0-9]+' || echo "")
fi
if [ -n "$TOTAL" ]; then
  echo "==> total listings this run: $TOTAL" | tee -a "$LOG"
  if [ "$TOTAL" -lt 200 ]; then
    echo "==> ⚠️  LOW TOTAL ($TOTAL < 200) — likely a broad failure. Investigate." | tee -a "$LOG"
    RC=2
  fi
fi

# ---- publish dashboard data to GitHub Pages --------------------------------
# The pipeline wrote docs/listings.json (with images, Vision condition,
# A-F grade, ARV/max-bid, comps, amount_owed) + run_health.json locally.
# The retired cloud workflow used to push these so GitHub Pages served the
# live dashboard; now the local run must do it. Only publish on a healthy
# run so we never overwrite a good dashboard with a broken/empty one.
if [[ "$RC" -eq 0 && -f "$ROOT/docs/listings.json" ]]; then
  # The payload list — and every "exists OR is already tracked" rule behind it —
  # lives in ONE place now: scripts/board_payload.sh, sourced above. Five
  # publishers were each maintaining their own copy of that list and they had
  # already drifted apart (see D4 in sos_agent_refresh.sh).
  if command -v git >/dev/null 2>&1; then
    cd "$ROOT"
    # Prove GitHub Pages will actually serve what we are about to push: Jekyll's
    # exclude/include are PREFIX matches, so `exclude: listings.json` also drops
    # listings.json.gz. That trap has 404'd this site's data three times, and
    # until now the script that detects it had no caller anywhere in the repo.
    # Loud but non-fatal here (the payload is not what is broken when it fires,
    # docs/_config.yml is); the hard gate is in .github/workflows/pages.yml.
    board_payload_check "$ROOT" | tee -a "$LOG"
    board_payload_add "$ROOT"
    if ! git diff --staged --quiet 2>/dev/null; then
      git commit -q -m "local run: refresh dashboard data ($(date +%Y-%m-%d))" 2>>"$LOG" || true
      # Rebase over any remote changes, then push (docs/ doesn't touch
      # .github/workflows, so the normal token can push it).
      git pull --rebase --autostash origin main >>"$LOG" 2>&1 || true
      if git push origin main >>"$LOG" 2>&1; then
        echo "==> ✓ dashboard published to GitHub (Pages will update in ~1 min)" | tee -a "$LOG"
      else
        echo "==> ⚠️  dashboard commit made locally but push failed — see log" | tee -a "$LOG"
      fi
    else
      echo "==> dashboard data unchanged — nothing to publish" | tee -a "$LOG"
    fi
  fi
else
  echo "==> skipping dashboard publish (run unhealthy: RC=$RC)" | tee -a "$LOG"
fi

# Keep the 12 most recent run logs; prune older.
ls -1t "$ROOT"/logs/local-run-*.log 2>/dev/null | tail -n +13 | xargs rm -f 2>/dev/null || true

exit $RC
