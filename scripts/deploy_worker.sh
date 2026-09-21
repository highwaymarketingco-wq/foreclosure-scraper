#!/bin/sh
# scripts/deploy_worker.sh
#
# Deploys the private dashboard Worker (worker/) to Cloudflare, smoke-tests it,
# and rolls a release back. DRY RUN BY DEFAULT: it prints exactly what it would
# do and touches no network, no account and no bucket.
#
#   scripts/deploy_worker.sh                       dry run: local tests, shell check, the rendered
#                                                  config and the exact commands --apply would run
#   scripts/deploy_worker.sh --apply               build shell, render config, check wrangler login,
#                                                  `wrangler deploy`
#   scripts/deploy_worker.sh --smoke-test URL      dry run: print the curl checks
#   scripts/deploy_worker.sh --smoke-test URL --apply
#                                                  run them against the deployed URL (see below)
#   scripts/deploy_worker.sh --rollback-release ID point current.json at release ID (dry run without
#                                                  --apply; needs rclone and PRIVATE_HOST_TARGET)
#
# It refuses to act without --apply. For --apply it also needs a configured
# account (CF_ACCOUNT_ID), a chosen URL_MODE, `wrangler` on PATH, and a wrangler
# login that can see that account.
#
# CONFIGURATION (no secrets): copy worker/deploy.conf.example to worker/deploy.conf.
# Keys can also be given as environment variables, which win over the file:
#   CF_ACCOUNT_ID        32 hex characters (dashboard address bar; not a secret)
#   URL_MODE             workers-dev | custom-domain
#   WORKER_HOSTNAME      board.example.com     (custom-domain only)
#   ACCESS_TEAM_DOMAIN   your Zero Trust team, e.g. acme or acme.cloudflareaccess.com
#   ACCESS_AUD           Application Audience (AUD) tag of the Access application, 64 hex
#                        (leave empty for the first deploy: the Worker then answers 503 to everything)
#   WORKER_NAME          default foreclosure-board
#   BUCKET_NAME          default foreclosure-board
#   R2_TARGET            rclone remote:bucket for --rollback-release, default r2:$BUCKET_NAME
#   CSP_RELAXED          true = break-glass: allow inline scripts if the page breaks (default false)
#   AUTH_DEBUG           true = refusals carry an X-Auth-Deny reason header (default false; smoke tests only)
#
# CREDENTIALS. This script never reads .secrets/ or .env and never prints a
# token. wrangler uses either its own `wrangler login` (OAuth, you click Allow in
# the browser) or CLOUDFLARE_API_TOKEN from your environment. For the smoke test,
# an Access service token is read from CF_ACCESS_CLIENT_ID and
# CF_ACCESS_CLIENT_SECRET in the environment and sent to curl on stdin, so it
# never appears in the process list or in output.
#
# SMOKE TEST (--smoke-test URL --apply). Without credentials it proves the front
# door: the URL must NOT hand out the app or any data. With a service token
# (Zero Trust, Access controls, Service credentials; add a Service Auth policy
# for it on the Worker's Access application; delete the token afterwards) it also
# checks the Worker itself: healthz, headers, gzip bytes, Range, ETag, denials.
#
# Exit codes: 0 ok, 1 refused or a check failed, 2 bad usage.

set -eu

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
APPLY=0
SMOKE_URL=""
ROLLBACK_ID=""
SKIP_TESTS=0
SKIP_ACCOUNT_CHECK=0
CONF=""
WRANGLER="${WRANGLER:-wrangler}"

die() { echo "REFUSED: $*" >&2; exit 1; }
usage() {
  sed -n '2,/^set -eu/p' "$0" | sed '$d' | sed 's/^# \{0,1\}//'
  cat <<'EOF'

Options
  --apply                  really do it (default is a dry run)
  --smoke-test URL         test a deployed URL (https, or http://localhost)
  --rollback-release ID    release folder id, e.g. 20260921T141132Z
  --target R:B             rclone remote:bucket for --rollback-release
  --conf FILE              settings file (default worker/deploy.conf)
  --skip-tests             do not run the node tests during the dry run
  --skip-account-check     do not require the login to list CF_ACCOUNT_ID
                           (for a scoped API token that cannot list accounts)
  --root DIR               repo root (for tests)
  -h, --help               this text
EOF
}

TARGET_ARG=""
while [ $# -gt 0 ]; do
  case "$1" in
    --apply) APPLY=1 ;;
    --skip-tests) SKIP_TESTS=1 ;;
    --skip-account-check) SKIP_ACCOUNT_CHECK=1 ;;
    --smoke-test)         [ $# -ge 2 ] || { echo "--smoke-test needs a URL" >&2; exit 2; }; SMOKE_URL="$2"; shift ;;
    --rollback-release)   [ $# -ge 2 ] || { echo "--rollback-release needs a release id" >&2; exit 2; }; ROLLBACK_ID="$2"; shift ;;
    --target)             [ $# -ge 2 ] || { echo "--target needs remote:bucket" >&2; exit 2; }; TARGET_ARG="$2"; shift ;;
    --conf)               [ $# -ge 2 ] || { echo "--conf needs a file" >&2; exit 2; }; CONF="$2"; shift ;;
    --root)               [ $# -ge 2 ] || { echo "--root needs a directory" >&2; exit 2; }; ROOT="$(cd "$2" && pwd)"; shift ;;
    -h|--help) usage; exit 0 ;;
    *) echo "unknown option: $1" >&2; usage >&2; exit 2 ;;
  esac
  shift
done

if [ -n "$SMOKE_URL" ] && [ -n "$ROLLBACK_ID" ]; then
  echo "choose one of --smoke-test and --rollback-release" >&2; exit 2
fi

WORKER="$ROOT/worker"
[ -d "$WORKER" ] || die "no worker/ directory under $ROOT"
[ -n "$CONF" ] || CONF="$WORKER/deploy.conf"

# ---------------------------------------------------------------------------
# Settings: environment wins over the file. The file is parsed, never sourced.

KEYS="CF_ACCOUNT_ID URL_MODE WORKER_HOSTNAME ACCESS_TEAM_DOMAIN ACCESS_AUD WORKER_NAME BUCKET_NAME R2_TARGET CSP_RELAXED AUTH_DEBUG"
for k in $KEYS; do
  eval "ENV_$k=\${$k:-}"
  eval "$k="
done

if [ -f "$CONF" ]; then
  while IFS= read -r line || [ -n "$line" ]; do
    line="$(printf '%s' "$line" | sed -e 's/^[[:space:]]*//' -e 's/[[:space:]]*$//')"
    case "$line" in ''|'#'*) continue ;; esac
    case "$line" in *=*) ;; *) die "$CONF: not KEY=VALUE: $line" ;; esac
    key="${line%%=*}"
    val="${line#*=}"
    key="$(printf '%s' "$key" | tr -d '[:space:]')"
    val="$(printf '%s' "$val" | sed -e 's/^[[:space:]]*//' -e 's/[[:space:]]*$//' -e 's/^"\(.*\)"$/\1/' -e "s/^'\(.*\)'\$/\1/")"
    case " $KEYS " in
      *" $key "*) eval "$key=\$val" ;;
      *) die "$CONF: unknown setting '$key' (allowed: $KEYS)" ;;
    esac
  done < "$CONF"
fi
for k in $KEYS; do
  eval "e=\$ENV_$k"
  if [ -n "$e" ]; then eval "$k=\$e"; fi
done

[ -n "$WORKER_NAME" ] || WORKER_NAME="foreclosure-board"
[ -n "$BUCKET_NAME" ] || BUCKET_NAME="foreclosure-board"
[ -z "$TARGET_ARG" ] || R2_TARGET="$TARGET_ARG"
[ -n "$R2_TARGET" ] || R2_TARGET="${PRIVATE_HOST_TARGET:-r2:$BUCKET_NAME}"

BAD=0
bad() { echo "  BAD SETTING: $*" >&2; BAD=$((BAD + 1)); }
check_re() { # name value regex hint
  [ -z "$2" ] && return 0
  printf '%s' "$2" | grep -Eq "$3" || bad "$1 is not valid ($4)"
}
check_re CF_ACCOUNT_ID "$CF_ACCOUNT_ID" '^[0-9a-f]{32}$' "32 lowercase hex characters"
check_re WORKER_NAME "$WORKER_NAME" '^[a-z0-9][a-z0-9-]{0,52}[a-z0-9]$' "lowercase letters, digits, hyphens"
check_re BUCKET_NAME "$BUCKET_NAME" '^[a-z0-9][a-z0-9-]{1,61}[a-z0-9]$' "lowercase letters, digits, hyphens"
check_re URL_MODE "$URL_MODE" '^(workers-dev|custom-domain)$' "workers-dev or custom-domain"
check_re WORKER_HOSTNAME "$WORKER_HOSTNAME" '^([a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z]{2,}$' "a bare hostname such as board.example.com"
check_re ACCESS_TEAM_DOMAIN "$ACCESS_TEAM_DOMAIN" '^[a-z0-9][a-z0-9-]{0,62}(\.cloudflareaccess\.com)?$' "your team name or team.cloudflareaccess.com"
check_re ACCESS_AUD "$ACCESS_AUD" '^[0-9a-f]{64}$' "64 lowercase hex characters"
check_re CSP_RELAXED "$CSP_RELAXED" '^(true|false)$' "true or false"
check_re AUTH_DEBUG "$AUTH_DEBUG" '^(true|false)$' "true or false"
check_re R2_TARGET "$R2_TARGET" '^[A-Za-z0-9_.-]+:[a-z0-9][a-z0-9-]+$' "rclone-remote:bucket"
if [ "$URL_MODE" = "custom-domain" ] && [ -z "$WORKER_HOSTNAME" ]; then bad "URL_MODE=custom-domain needs WORKER_HOSTNAME"; fi
if [ "$URL_MODE" = "workers-dev" ] && [ -n "$WORKER_HOSTNAME" ]; then bad "WORKER_HOSTNAME is only used with URL_MODE=custom-domain"; fi
[ "$BAD" -eq 0 ] || { echo "Fix the settings above (file: $CONF) and run again." >&2; exit 1; }

first_word() { printf '%s' "$1" | awk '{print $1}'; }

# ===========================================================================
# MODE: smoke test
# ===========================================================================
if [ -n "$SMOKE_URL" ]; then
  BASE="${SMOKE_URL%/}"
  case "$BASE" in
    https://*) ;;
    http://localhost|http://localhost:*|http://127.0.0.1|http://127.0.0.1:*) ;;
    *) die "smoke test URL must be https:// (or http://localhost for a local run), got '$SMOKE_URL'" ;;
  esac
  printf '%s' "$BASE" | grep -Eq '^https?://[A-Za-z0-9.:-]+$' || die "smoke test URL must be a bare origin like https://host, got '$SMOKE_URL'"

  HAVE_TOKEN=0
  if [ -n "${CF_ACCESS_CLIENT_ID:-}" ] && [ -n "${CF_ACCESS_CLIENT_SECRET:-}" ]; then HAVE_TOKEN=1; fi
  if [ "$HAVE_TOKEN" -eq 1 ]; then
    printf '%s' "$CF_ACCESS_CLIENT_ID" | grep -Eq '^[A-Za-z0-9._-]+$' || die "CF_ACCESS_CLIENT_ID has unexpected characters"
    printf '%s' "$CF_ACCESS_CLIENT_SECRET" | grep -Eq '^[A-Za-z0-9._-]+$' || die "CF_ACCESS_CLIENT_SECRET has unexpected characters"
  fi

  echo "deploy_worker.sh --smoke-test : $([ "$APPLY" -eq 1 ] && echo APPLY || echo 'DRY RUN (no request is made)')"
  echo "url                           : $BASE"
  echo "service token                 : $([ "$HAVE_TOKEN" -eq 1 ] && echo 'CF_ACCESS_CLIENT_ID / CF_ACCESS_CLIENT_SECRET are set (values not shown)' || echo 'not set: only the no-credentials checks will run')"
  echo
  echo "Checks WITHOUT credentials (the front door must not hand out anything):"
  echo "  GET  /                                 must not be 200 (expect an Access login redirect, or 403/503 from the Worker)"
  echo "  GET  /healthz /run_meta.json /current.json /listings_slim.json.gz (range 0-1) /parcel_photos/x.jpg"
  echo "                                         must not be 200 or 206, and must not contain data"
  if [ "$HAVE_TOKEN" -eq 1 ]; then
    echo "Checks WITH the service token (header CF-Access-Client-Id / CF-Access-Client-Secret):"
    echo "  GET  /healthz                          200, ok:true, prints the live release and how the Worker authenticated the call"
    echo "  GET  /                                 200 html; Content-Security-Policy present; x-csp-mode hashed"
    echo "  GET  /run_meta.json                    200; Cache-Control no-store; has run_time"
    echo "  HEAD /listings_slim.json.gz?t=<run_time>   200; application/gzip; NO Content-Encoding; Accept-Ranges; ETag"
    echo "  GET  same, Range bytes=0-1             206; Content-Range; first two bytes are 1f8b"
    echo "  GET  /run_meta.json with If-None-Match 304"
    echo "  GET  /detail_shards/00000.json.gz?t=<run_time>   served from the same release"
    echo "  GET  /.env /crm.json /listings.json /README.md /detail_shards/00000.json   404"
    echo "  GET  /current.json                     Cache-Control no-store;  /robots.txt disallows all"
    echo "  OPTIONS /                              405, and no Access-Control-Allow-Origin on any response"
  fi
  if [ "$APPLY" -ne 1 ]; then
    echo
    echo "Dry run complete. Add --apply to send these requests."
    exit 0
  fi

  command -v curl >/dev/null 2>&1 || die "curl is not installed"
  TMP="$(mktemp -d "${TMPDIR:-/tmp}/smoke.XXXXXX")"
  trap 'rm -rf "$TMP"' EXIT INT TERM
  PASS=0; FAIL=0; WARN=0
  ok()   { PASS=$((PASS + 1)); printf '  PASS  %s\n' "$*"; }
  nope() { FAIL=$((FAIL + 1)); printf '  FAIL  %s\n' "$*"; }
  warn() { WARN=$((WARN + 1)); printf '  WARN  %s\n' "$*"; }

  # req <anon|auth> <curl args...> ; sets STATUS, writes $TMP/h and $TMP/b
  STATUS=""
  req() {
    mode="$1"; shift
    : > "$TMP/h"; : > "$TMP/b"
    if [ "$mode" = auth ]; then
      STATUS="$(printf 'header = "CF-Access-Client-Id: %s"\nheader = "CF-Access-Client-Secret: %s"\n' "$CF_ACCESS_CLIENT_ID" "$CF_ACCESS_CLIENT_SECRET" \
        | curl -K - -sS --max-time 60 -D "$TMP/h" -o "$TMP/b" -w '%{http_code}' "$@" 2>"$TMP/e")" || STATUS="000"
    else
      STATUS="$(curl -sS --max-time 60 -D "$TMP/h" -o "$TMP/b" -w '%{http_code}' "$@" 2>"$TMP/e")" || STATUS="000"
    fi
  }
  # hdr <name>: last value of a response header, CR stripped, empty if absent
  hdr() { grep -i "^$1:" "$TMP/h" | tail -n 1 | sed -e 's/^[^:]*:[[:space:]]*//' -e 's/[[:space:]]*$//' || true; }
  body_has() { grep -q "$1" "$TMP/b" 2>/dev/null; }

  echo
  echo "== without credentials =="
  req anon "$BASE/"
  case "$STATUS" in
    200) nope "GET / returned 200 with no login: THE SITE IS PUBLIC" ;;
    301|302|303|307|308)
      loc="$(hdr location)"
      case "$loc" in
        *cloudflareaccess.com*) ok "GET / redirects to the Access login ($STATUS -> $(printf '%s' "$loc" | sed -e 's#^\(https://[^/]*\).*#\1#'))" ;;
        *) warn "GET / redirects ($STATUS) but not to cloudflareaccess.com: $(printf '%s' "$loc" | cut -c1-80)" ;;
      esac ;;
    401|403) ok "GET / refused with $STATUS$( [ -n "$(hdr x-robots-tag)" ] && echo ' (the Worker refused it: defence in depth is active)' )" ;;
    503) warn "GET / answered 503: the Worker is deployed but ACCESS_TEAM_DOMAIN / ACCESS_AUD are not set yet (fails closed, expected before checklist Part 7b)" ;;
    000) nope "GET / could not connect: $(tr '\n' ' ' < "$TMP/e" | cut -c1-120)" ;;
    *) warn "GET / answered $STATUS (not a login redirect)" ;;
  esac
  body_has 'dashboard.js' && nope "the response body for / contains the app (dashboard.js)"

  for p in /healthz /run_meta.json /current.json /listings_slim.json.gz /parcel_photos/x.jpg; do
    extra=""; [ "$p" = /listings_slim.json.gz ] && extra="-r 0-1"
    # shellcheck disable=SC2086
    req anon $extra "$BASE$p"
    case "$STATUS" in
      200|206) nope "GET $p returned $STATUS with no login: DATA IS PUBLIC" ;;
      *) if body_has '"run_time"' || body_has '"release"'; then nope "GET $p ($STATUS) leaked data in the body"; else ok "GET $p refused ($STATUS)"; fi ;;
    esac
  done

  if [ "$HAVE_TOKEN" -eq 1 ]; then
    echo
    echo "== with the service token =="
    req auth "$BASE/healthz"
    RELEASE=""
    if [ "$STATUS" = 200 ] && body_has '"ok":true'; then
      RELEASE="$(sed -n 's/.*"release":"\([^"]*\)".*/\1/p' "$TMP/b" | head -n 1)"
      via="$(sed -n 's/.*"auth":"\([^"]*\)".*/\1/p' "$TMP/b" | head -n 1)"
      ok "healthz 200, live release $RELEASE, Worker authenticated the call via: $via"
      [ "$via" = "jwt" ] || warn "authenticated via '$via', not the Cf-Access-Jwt-Assertion header: fine, but note it for docs/HOSTING_WORKER_2026-09-21.md (risk R3)"
    else
      nope "healthz with the token: status $STATUS (is a Service Auth policy on the Access application for this token? set AUTH_DEBUG=true to see the reason)"
      echo "        $(head -c 200 "$TMP/b" | tr '\n' ' ')"
    fi
    if [ "$STATUS" != 200 ]; then
      echo "  The remaining token checks need healthz to pass; stopping."
    else
      req auth "$BASE/"
      if [ "$STATUS" = 200 ]; then
        ok "GET / 200 html"
        [ -n "$(hdr content-security-policy)" ] && ok "Content-Security-Policy present" || nope "no Content-Security-Policy on /"
        mode="$(hdr x-csp-mode)"
        case "$mode" in hashed) ok "CSP is in hashed mode (no unsafe-inline for scripts)" ;; *) warn "x-csp-mode is '$mode': scripts are allowed inline; rebuild the shell (worker/scripts/build_shell.mjs) and redeploy" ;; esac
        body_has 'dashboard.js' && ok "index.html served (references dashboard.js)" || nope "GET / 200 but the body is not the dashboard"
      else nope "GET / with the token: $STATUS"; fi

      req auth "$BASE/run_meta.json"
      RUN_TIME=""
      if [ "$STATUS" = 200 ] && body_has '"run_time"'; then
        RUN_TIME="$(sed -n 's/.*"run_time": *"\([^"]*\)".*/\1/p' "$TMP/b" | head -n 1)"
        ok "run_meta.json 200, run_time $RUN_TIME"
        [ "$(hdr cache-control)" = "no-store" ] && ok "run_meta.json is no-store" || nope "run_meta.json Cache-Control is '$(hdr cache-control)', expected no-store"
      else nope "run_meta.json: status $STATUS or no run_time in the body"; fi
      ETAG_META="$(hdr etag)"

      Q=""; [ -n "$RUN_TIME" ] && Q="?t=$RUN_TIME"
      req auth --head "$BASE/listings_slim.json.gz$Q"
      if [ "$STATUS" = 200 ]; then
        ok "HEAD listings_slim.json.gz 200, $(hdr content-length) bytes"
        [ "$(hdr content-type)" = "application/gzip" ] && ok "content-type application/gzip" || nope "content-type is '$(hdr content-type)', expected application/gzip"
        [ -z "$(hdr content-encoding)" ] && ok "no Content-Encoding (dashboard.js inflates the raw gzip itself)" || nope "Content-Encoding '$(hdr content-encoding)' is present on a .gz payload"
        [ "$(hdr accept-ranges)" = "bytes" ] && ok "Accept-Ranges: bytes" || nope "no Accept-Ranges: bytes"
        [ -n "$(hdr etag)" ] && ok "ETag present" || nope "no ETag"
        [ -n "$RELEASE" ] && [ "$(hdr x-release)" != "" ] && ok "served from release $(hdr x-release)"
      else nope "HEAD listings_slim.json.gz: status $STATUS"; fi

      req auth -r 0-1 "$BASE/listings_slim.json.gz$Q"
      if [ "$STATUS" = 206 ]; then
        magic="$(od -An -tx1 -N2 "$TMP/b" | tr -d ' \n')"
        [ "$magic" = "1f8b" ] && ok "Range bytes=0-1 -> 206, Content-Range '$(hdr content-range)', first bytes 1f8b (gzip magic)" || nope "Range 206 but first bytes are '$magic', not 1f8b"
      else nope "Range bytes=0-1: status $STATUS, expected 206"; fi

      if [ -n "$ETAG_META" ]; then
        req auth -H "If-None-Match: $ETAG_META" "$BASE/run_meta.json"
        [ "$STATUS" = 304 ] && ok "If-None-Match on run_meta.json -> 304" || nope "If-None-Match on run_meta.json: status $STATUS, expected 304"
      else warn "run_meta.json had no ETag; conditional request not tested"; fi

      req auth --head "$BASE/detail_shards/00000.json.gz$Q"
      [ "$STATUS" = 200 ] && ok "detail shard 00000 reachable ($STATUS)" || nope "detail shard 00000: status $STATUS"

      for p in /.env /crm.json /listings.json /README.md /detail_shards/00000.json /.git/config; do
        req auth "$BASE$p"
        [ "$STATUS" = 404 ] && ok "GET $p -> 404" || nope "GET $p -> $STATUS, expected 404"
      done

      req auth "$BASE/current.json"
      [ "$STATUS" = 200 ] && [ "$(hdr cache-control)" = "no-store" ] && ok "current.json is no-store" || nope "current.json: status $STATUS, cache-control '$(hdr cache-control)'"
      req auth "$BASE/robots.txt"
      body_has 'Disallow: /' && ok "robots.txt disallows everything" || nope "robots.txt: status $STATUS"

      req auth -X OPTIONS "$BASE/"
      [ "$STATUS" = 405 ] && ok "OPTIONS / -> 405 (no CORS preflight answered)" || nope "OPTIONS /: status $STATUS, expected 405"
      [ -z "$(hdr access-control-allow-origin)" ] && ok "no Access-Control-Allow-Origin header" || nope "Access-Control-Allow-Origin present: '$(hdr access-control-allow-origin)'"
    fi
  else
    echo
    echo "== with the service token: SKIPPED (set CF_ACCESS_CLIENT_ID and CF_ACCESS_CLIENT_SECRET) =="
  fi

  echo
  echo "smoke test: $PASS passed, $FAIL failed, $WARN warnings"
  [ "$FAIL" -eq 0 ] || exit 1
  exit 0
fi

# ===========================================================================
# MODE: roll a release back (rclone, no wrangler)
# ===========================================================================
if [ -n "$ROLLBACK_ID" ]; then
  printf '%s' "$ROLLBACK_ID" | grep -Eq '^[0-9A-Za-z_-]{8,40}$' || die "release id must look like 20260921T141132Z, got '$ROLLBACK_ID'"
  echo "deploy_worker.sh --rollback-release : $([ "$APPLY" -eq 1 ] && echo APPLY || echo 'DRY RUN (no network)')"
  echo "target                              : $R2_TARGET"
  echo "release                             : $ROLLBACK_ID"
  echo
  echo "Steps:"
  echo "  1) rclone lsf --dirs-only $R2_TARGET/releases/     the release folder must exist"
  echo "  2) rclone cat $R2_TARGET/releases/$ROLLBACK_ID/run_meta.json     must be readable; board count read from it"
  echo "  3) rclone rcat $R2_TARGET/current.json      {\"release\":\"$ROLLBACK_ID\",\"published_at\":...,\"board_count\":N}   (same format publish_private.sh writes)"
  echo "  4) rclone cat $R2_TARGET/current.json       read it back"
  echo "The Worker follows within POINTER_TTL_SECONDS (default 30 s). Open pages keep working: their ?t= pins the release they loaded."
  if [ "$APPLY" -ne 1 ]; then
    echo
    echo "Dry run complete. Add --apply to move the pointer. Do not run this while scripts/publish_private.sh is running."
    exit 0
  fi
  command -v rclone >/dev/null 2>&1 || die "rclone is not installed"
  REMOTE="${R2_TARGET%%:*}"
  rclone listremotes 2>/dev/null | grep -qx "$REMOTE:" || die "rclone remote '$REMOTE' is not configured (docs/HOSTING_SETUP_CHECKLIST.md Part 3)"
  if pgrep -f "scripts/publish_private.sh" >/dev/null 2>&1; then die "publish_private.sh is running; it would overwrite the pointer when it finishes. Try again after it exits."; fi
  rclone lsf --dirs-only "$R2_TARGET/releases/" 2>/dev/null | sed 's:/$::' | grep -qx "$ROLLBACK_ID" || die "no folder releases/$ROLLBACK_ID in $R2_TARGET (it may have been pruned)"
  COUNT="$(rclone cat "$R2_TARGET/releases/$ROLLBACK_ID/run_meta.json" 2>/dev/null | python3 -c 'import json,sys; m=json.load(sys.stdin); print(int((m.get("board") or {}).get("count") or 0))' 2>/dev/null)" \
    || die "releases/$ROLLBACK_ID/run_meta.json is missing or unreadable; not a complete release"
  [ "${COUNT:-0}" -gt 0 ] || die "releases/$ROLLBACK_ID/run_meta.json has no board.count; not a complete release"
  printf '{"release":"%s","published_at":"%s","board_count":%s}\n' "$ROLLBACK_ID" "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$COUNT" \
    | rclone rcat "$R2_TARGET/current.json" --s3-no-check-bucket
  echo "pointer now:"
  rclone cat "$R2_TARGET/current.json"
  echo "rolled back to $ROLLBACK_ID ($COUNT records)"
  exit 0
fi

# ===========================================================================
# MODE: deploy (dry run unless --apply)
# ===========================================================================
echo "deploy_worker.sh : $([ "$APPLY" -eq 1 ] && echo APPLY || echo 'DRY RUN (no network, no account, nothing is deployed)')"
echo "repo root        : $ROOT"
echo "settings file    : $CONF$([ -f "$CONF" ] || echo '  (not found; copy worker/deploy.conf.example)')"
echo

# ---- local checks: always, no network ----
command -v node >/dev/null 2>&1 || die "node is not installed (needed for the tests, the shell build and the config render)"
for f in src/index.js src/access.js src/bucket.js src/routes.js src/security.js src/csp.js wrangler.jsonc \
         scripts/build_shell.mjs scripts/render_config.mjs scripts/shell_lib.mjs scripts/config_lib.mjs; do
  [ -f "$WORKER/$f" ] || die "missing worker/$f"
done

if [ "$SKIP_TESTS" -eq 1 ]; then
  echo "tests            : skipped (--skip-tests)"
else
  TEST_OUT="$(cd "$WORKER" && node --test test/*.test.mjs 2>&1 || true)"
  T_PASS="$(printf '%s\n' "$TEST_OUT" | sed -n 's/^# pass \([0-9]*\).*/\1/p' | tail -n 1)"
  T_FAIL="$(printf '%s\n' "$TEST_OUT" | sed -n 's/^# fail \([0-9]*\).*/\1/p' | tail -n 1)"
  echo "tests            : ${T_PASS:-?} passed, ${T_FAIL:-?} failed (node --test worker/test/*.test.mjs)"
  if [ "${T_FAIL:-1}" != "0" ] || [ -z "$T_PASS" ]; then
    printf '%s\n' "$TEST_OUT" | grep -E '^(not ok|# Subtest)' | head -n 20 >&2
    die "worker tests do not pass; not deploying"
  fi
fi

echo "shell check      : node worker/scripts/build_shell.mjs --check"
if ! SHELL_OUT="$(node "$WORKER/scripts/build_shell.mjs" --check 2>&1)"; then
  printf '%s\n' "$SHELL_OUT" >&2
  die "the app shell cannot be built from docs/"
fi
printf '%s\n' "$SHELL_OUT" | sed -e 's/^/  /'
echo

# ---- what will be deployed ----
echo "account          : ${CF_ACCOUNT_ID:-(not set)}"
echo "worker name      : $WORKER_NAME"
echo "R2 bucket        : $BUCKET_NAME (binding BOARD; must already exist and stay private)"
echo "URL mode         : ${URL_MODE:-(not set)}${WORKER_HOSTNAME:+  hostname $WORKER_HOSTNAME}"
echo "Access team      : ${ACCESS_TEAM_DOMAIN:-(not set)}"
[ "$CSP_RELAXED" != "true" ] || echo "CSP              : RELAXED (scripts may run inline; break-glass, set CSP_RELAXED=false when fixed)"
[ "$AUTH_DEBUG" != "true" ] || echo "auth debug       : ON (refusals name their reason in X-Auth-Deny; turn off after testing)"
echo "Access AUD tag   : $([ -n "$ACCESS_AUD" ] && echo "set (${#ACCESS_AUD} characters)" || echo '(not set)')"
if [ -z "$ACCESS_TEAM_DOMAIN" ] || [ -z "$ACCESS_AUD" ]; then
  echo "                   The Worker still deploys safely: with either value missing it answers 503 to"
  echo "                   every request and serves nothing. Set both after checklist Part 7 and deploy again."
fi
if [ -n "${CLOUDFLARE_API_TOKEN:-}" ]; then
  echo "wrangler auth    : CLOUDFLARE_API_TOKEN is set in this environment (value not shown)"
else
  echo "wrangler auth    : no CLOUDFLARE_API_TOKEN; wrangler will use its own login (\`$WRANGLER login\`)"
fi
echo

set --
[ -z "$CF_ACCOUNT_ID" ] || set -- "$@" --account "$CF_ACCOUNT_ID"
set -- "$@" --name "$WORKER_NAME" --bucket "$BUCKET_NAME"
[ -z "$ACCESS_TEAM_DOMAIN" ] || set -- "$@" --team "$ACCESS_TEAM_DOMAIN"
[ -z "$ACCESS_AUD" ] || set -- "$@" --aud "$ACCESS_AUD"
[ -z "$URL_MODE" ] || set -- "$@" --url-mode "$URL_MODE"
[ -z "$CSP_RELAXED" ] || set -- "$@" --csp-relaxed "$CSP_RELAXED"
[ -z "$AUTH_DEBUG" ] || set -- "$@" --auth-debug "$AUTH_DEBUG"
[ -z "$WORKER_HOSTNAME" ] || set -- "$@" --hostname "$WORKER_HOSTNAME"

echo "rendered config (worker/wrangler.rendered.jsonc), exactly what would be deployed:"
if ! RENDERED="$(node "$WORKER/scripts/render_config.mjs" --print "$@" 2>&1)"; then
  printf '%s\n' "$RENDERED" >&2
  die "the configuration is not valid"
fi
printf '%s\n' "$RENDERED" | sed -e 's/^/  /'
echo

echo "commands that --apply will run:"
echo "  1) node worker/scripts/build_shell.mjs                       (copies the allowlisted app files into worker/shell/)"
echo "  2) node worker/scripts/render_config.mjs --out worker/wrangler.rendered.jsonc ...   (as printed above)"
echo "  3) $WRANGLER whoami --json                                     (must list account ${CF_ACCOUNT_ID:-<CF_ACCOUNT_ID>}; output is not printed)"
echo "  4) cd worker && $WRANGLER deploy --config wrangler.rendered.jsonc"
echo
echo "Not done by this script: creating the bucket, uploading data (scripts/publish_private.sh), turning on"
echo "Cloudflare Access, or adding people. See docs/HOSTING_SETUP_CHECKLIST.md and worker/README.md."

if [ "$APPLY" -ne 1 ]; then
  echo
  echo "Dry run complete. Nothing was deployed. Re-run with --apply when the checklist is done."
  exit 0
fi

# ---- APPLY: every guard must pass before anything remote happens ----
[ -n "$CF_ACCOUNT_ID" ] || die "no account configured. Set CF_ACCOUNT_ID in worker/deploy.conf (checklist Part 1)."
[ -n "$URL_MODE" ] || die "no URL mode. Set URL_MODE=workers-dev or URL_MODE=custom-domain in worker/deploy.conf."
WR1="$(first_word "$WRANGLER")"
command -v "$WR1" >/dev/null 2>&1 || die "'$WR1' is not on PATH. Install it with: npm install -g wrangler   (or set WRANGLER='npx wrangler')"

echo
echo "== 1/4 build shell =="
node "$WORKER/scripts/build_shell.mjs"

echo "== 2/4 render config =="
node "$WORKER/scripts/render_config.mjs" --out "$WORKER/wrangler.rendered.jsonc" "$@"

echo "== 3/4 check wrangler login =="
if ! WHO="$(cd "$WORKER" && $WRANGLER whoami --json 2>/dev/null)"; then
  die "wrangler is not logged in. Run: $WRANGLER login   (click Allow in the browser), then run this again."
fi
if [ "$SKIP_ACCOUNT_CHECK" -eq 1 ]; then
  echo "account check skipped (--skip-account-check)"
elif printf '%s' "$WHO" | grep -q "$CF_ACCOUNT_ID"; then
  echo "logged in, and the login can see account $CF_ACCOUNT_ID"
else
  die "wrangler is logged in, but not to an account with id $CF_ACCOUNT_ID. Check worker/deploy.conf, or use --skip-account-check for a scoped API token."
fi

echo "== 4/4 wrangler deploy =="
( cd "$WORKER" && $WRANGLER deploy --config wrangler.rendered.jsonc )

echo
echo "Deployed. Next:"
if [ -z "$ACCESS_TEAM_DOMAIN" ] || [ -z "$ACCESS_AUD" ]; then
  echo "  - The Worker is answering 503 to everything until you finish checklist Part 7:"
  echo "    turn on Access for the Worker (All traffic), add the people, copy the Application Audience (AUD) tag,"
  echo "    put ACCESS_TEAM_DOMAIN and ACCESS_AUD in worker/deploy.conf, and run this script with --apply again."
else
  echo "  - Run the smoke test:   scripts/deploy_worker.sh --smoke-test https://<your-address> --apply"
fi
