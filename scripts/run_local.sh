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

# Assessor property-card enricher — ON for the weekly run. The default cap
# (150) is below the ~280 live targets, so raise it to 400 to cover them all.
export ASSESSOR_CARD_ON="${ASSESSOR_CARD_ON:-1}"
export ASSESSOR_CARD_MAX="${ASSESSOR_CARD_MAX:-400}"

# Enrichment budget — keep the run finishing in a sane window. The cloud
# run died at 4h partly on a Gemini-quota Vision spiral; locally we use
# Anthropic (set above) and cap Vision so the run completes. Raise
# VISION_MAX_LISTINGS later for deeper condition coverage. ROD deed
# enrichment stays OFF (broken vendor portals = 27 min for 0 matches).
# Vision budget — now FREE Gemini with 4-account key rotation. The vision
# code runs one parallel stream per key, so throughput ≈ keys / delay.
# Cap at 800 (prioritized by soonest sale date) to stay within Gemini's
# free per-day quota across 4 keys; ~4s/key pacing keeps each under its
# per-minute rate limit → ~800 scored in ~15 min. Unscored fall back to
# the regex/age condition tier.
export VISION_MAX_LISTINGS="${VISION_MAX_LISTINGS:-800}"
export VISION_INTER_CALL_DELAY="${VISION_INTER_CALL_DELAY:-4}"
# Generous wall-clock cap so it can finish the 800 but can never hang.
export VISION_MAX_SECONDS="${VISION_MAX_SECONDS:-1800}"
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
START=$(date +%s)
uv run python -m foreclosure_scraper >>"$LOG" 2>&1
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
  PUB_FILES=(docs/listings.json docs/run_meta.json docs/run_health.json
             docs/foreclosure_sold_pool.json docs/multifamily.json)
  if command -v git >/dev/null 2>&1; then
    cd "$ROOT"
    git add "${PUB_FILES[@]}" 2>/dev/null || true
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
