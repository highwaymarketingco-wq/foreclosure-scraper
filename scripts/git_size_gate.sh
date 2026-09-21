#!/bin/sh
# Pre-commit size gate: refuse to commit any file over 95 MiB.
#
# GitHub rejects a push that contains a file over 100 MiB. Every publisher here commits
# first and pushes second, and prints a message and exits 0 when the push fails, so a board
# gz that crosses the limit leaves an oversized blob in LOCAL history and every later push,
# code and docs included, is rejected too until someone rewrites history by hand.
# docs/listings.json.gz was 84 MiB on 2026-09-21 and growing 2 to 4 MiB a day (now split into
# parts, see below).
#
# This runs as .git/hooks/pre-commit (install: scripts/install_size_gate.sh). Failing here
# stops the commit from forming, so history stays clean and the next push still works.
# The board on disk is untouched; only the publish is held back.
#
#   BOARD_SIZE_GATE_BYTES  block above this many bytes  (default 99614720 = 95 MiB)
#   BOARD_SIZE_WARN_BYTES  log a warning above this     (default 94371840 = 90 MiB)
#   git commit --no-verify skips the gate. Do not use it for the board files.
# Since the payload split (audit O1) the board is docs/listings_part_NNN.json.gz, each part
# under 24 MiB, so this per-file gate should never fire on the board again. It stays as the
# backstop for everything else, and a second check runs first: a commit whose staged parts are
# not exactly the set the staged manifest lists (a mixed publish) is refused as well.
LIMIT="${BOARD_SIZE_GATE_BYTES:-99614720}"
WARN="${BOARD_SIZE_WARN_BYTES:-94371840}"
ROOT="$(git rev-parse --show-toplevel 2>/dev/null)" || exit 0
LOG="$ROOT/logs/publish_blocked.log"
TMP="$(mktemp 2>/dev/null || echo "/tmp/size_gate.$$")"
trap 'rm -f "$TMP"' EXIT

if [ -f "$ROOT/scripts/check_staged_parts.py" ] && command -v python3 >/dev/null 2>&1; then
  if ! python3 "$ROOT/scripts/check_staged_parts.py" --root "$ROOT"; then
    mkdir -p "$ROOT/logs" 2>/dev/null
    printf '%s BLOCKED inconsistent board parts\n' "$(date '+%Y-%m-%d %H:%M:%S')" >> "$LOG" 2>/dev/null
    exit 1
  fi
fi

git diff --cached --name-only --diff-filter=AM | while IFS= read -r path; do
  [ -n "$path" ] || continue
  size="$(git cat-file -s ":$path" 2>/dev/null)" || continue
  if [ "$size" -gt "$LIMIT" ]; then
    printf 'BLOCK %s %s\n' "$size" "$path" >> "$TMP"
  elif [ "$size" -gt "$WARN" ]; then
    printf 'WARN %s %s\n' "$size" "$path" >> "$TMP"
  fi
done

[ -s "$TMP" ] || exit 0

stamp="$(date '+%Y-%m-%d %H:%M:%S')"
mkdir -p "$ROOT/logs" 2>/dev/null
blocked=0
while IFS=' ' read -r kind size path; do
  mib="$(awk -v s="$size" 'BEGIN { printf "%.1f", s / 1048576 }')"
  if [ "$kind" = "BLOCK" ]; then
    blocked=1
    echo "size gate: BLOCKED $path is $mib MiB, over the 95 MiB limit (GitHub rejects 100 MiB)." >&2
    printf '%s BLOCKED %s %s MiB\n' "$stamp" "$path" "$mib" >> "$LOG" 2>/dev/null
  else
    echo "size gate: warning, $path is $mib MiB (limit 95). Trim or split the payload soon." >&2
    printf '%s WARN %s %s MiB\n' "$stamp" "$path" "$mib" >> "$LOG" 2>/dev/null
  fi
done < "$TMP"

if [ "$blocked" -eq 1 ]; then
  echo "size gate: nothing was committed. The board on disk is unchanged. See logs/publish_blocked.log." >&2
  exit 1
fi
exit 0
