#!/bin/bash
# Restore the published board from ONE git commit (audit 2026-09-21 O5).
#
#   scripts/restore_board.sh --list [N]        show the last N commits that touched the board
#   scripts/restore_board.sh <commit>          restore (asks you to type RESTORE)
#   scripts/restore_board.sh <commit> --yes    restore without the prompt (for scripts)
#
# WHAT IT DOES, in this order:
#   1. REFUSES (exit 75) while any job holds the board lock; otherwise takes the lock itself
#      and holds it for the whole restore, so a scheduled job cannot start halfway through.
#   2. Moves the current PLAIN twins (docs/listings.json, listings_detail.json,
#      listings_slim.json), the board PARTS (docs/listings_part_NNN.json.gz) and the shard
#      directory into backups/pre-restore-<stamp>/ (a rename, not a delete). The plain .json MUST
#      go first: read_board_json prefers it over the .gz, so leaving a newer plain file beside an
#      older .gz restores nothing. The parts MUST go too: a commit with four parts restored over a
#      tree holding six would leave two strays the manifest does not list.
#   3. Restores every payload file from THAT ONE COMMIT: the board parts (or, for a commit from
#      before the payload split, the single listings.json.gz), the two other .gz twins, the whole
#      docs/detail_shards/ directory (index i is the join across all of them, so a mix of
#      commits is a mis-joined board: one property's comps under another's address), run_meta,
#      run_health and board.manifest.json.
#   4. Prints the sha256 of every restored file and checks the manifest that came with the
#      commit. A commit from before 2026-09-21 has no manifest; the script says so.
#   5. Warns when the restored board is smaller than docs/board_highwater.json allows: the
#      count guard will REFUSE the next write until you set BOARD_ALLOW_SHRINK=1 once or lower
#      the high-water mark.
#
# It touches the working tree only (git restore --worktree): nothing is staged, committed or
# pushed. Publishing the restored board is a separate, deliberate step.
# Full procedure and failure cases: docs/RESTORE.md
set -uo pipefail
export PATH="$HOME/.local/bin:/opt/homebrew/bin:$PATH"
ROOT="${FORECLOSURE_ROOT:-$(cd "$(dirname "$0")/.." && pwd)}"
cd "$ROOT" || exit 1

PAYLOAD_FILES=(docs/listings_detail.json.gz docs/listings_slim.json.gz \
               docs/run_meta.json docs/run_health.json docs/board.manifest.json)
PAYLOAD_DIR=docs/detail_shards
PLAIN_FILES=(docs/listings.json docs/listings_detail.json docs/listings_slim.json)

# the board files a commit holds: the parts (listings_part_NNN.json.gz) and, before the payload
# split, the single listings.json.gz. Direct children of docs/ only (git ls-tree, not -r: the
# photo directory has thousands of files).
board_names_in() {   # <commit> -> one docs/<name> per line
  git ls-tree --name-only "$1" docs/ 2>/dev/null | grep -E '^docs/(listings_part_[0-9]+\.json\.gz|listings\.json\.gz)$'
}

if [ "${1:-}" = "--list" ]; then
  N="${2:-15}"
  echo "last $N commits touching the board (sha, date, board size in all its files, subject):"
  git log -n "$N" --format='%h %ad %s' --date=short -- docs/listings.json.gz 'docs/listings_part_*.json.gz' | while read -r sha rest; do
    sz=$(git ls-tree -l "$sha" docs/ 2>/dev/null | awk '$NF ~ /(listings_part_[0-9]+\.json\.gz|\/listings\.json\.gz)$/ {s += $4} END {print s + 0}')
    np=$(git ls-tree --name-only "$sha" docs/ 2>/dev/null | grep -cE '^docs/listings_part_[0-9]+\.json\.gz$')
    printf '  %s  %6s MiB  %s%s\n' "$sha" "$(awk -v s="${sz:-0}" 'BEGIN { printf "%.1f", s/1048576 }')" "$rest" "$([ "${np:-0}" -gt 0 ] && echo "  [${np} parts]")"
  done
  exit 0
fi

COMMIT="${1:-}"; YES=0
[ "${2:-}" = "--yes" ] && YES=1
[ -n "$COMMIT" ] || { sed -n 2,8p "$0"; exit 2; }
FULL=$(git rev-parse --verify --quiet "$COMMIT^{commit}") || { echo "not a commit: $COMMIT" >&2; exit 2; }
SHORT=$(git rev-parse --short "$FULL")

. "$ROOT/scripts/job_event.sh"
. "$ROOT/scripts/board_lock.sh"
JOB_EVENT_ROOT="$ROOT"
job_event_begin restore_board
trap 'job_event_finalize; board_lock_release' EXIT INT TERM

# 1. the lock: refuse while held
if ! board_lock_acquire "$ROOT" "restore_board" 0 3600; then
  echo "REFUSING to restore: $(board_lock_refusal_message 'the restore')." >&2
  echo "Wait for that job to finish (see logs/.board.lock/pid), then run this again." >&2
  job_event_end skipped_lock "" "$(board_lock_holder)"
  exit 75
fi

# which payload paths does the commit actually contain?
have() { git cat-file -e "$FULL:$1" 2>/dev/null; }
RESTORE=()
BOARD_IN_COMMIT=$(board_names_in "$FULL")
[ -n "$BOARD_IN_COMMIT" ] || { echo "$SHORT has no docs/listings_part_NNN.json.gz and no docs/listings.json.gz: not a board commit" >&2; job_event_end failed "" "not_a_board_commit"; exit 2; }
for f in $BOARD_IN_COMMIT; do RESTORE+=("$f"); done
for f in "${PAYLOAD_FILES[@]}"; do have "$f" && RESTORE+=("$f") || echo "note: $SHORT has no $f"; done
have "$PAYLOAD_DIR" && RESTORE+=("$PAYLOAD_DIR") || echo "note: $SHORT has no $PAYLOAD_DIR (mobile detail will fall back to desktop-only)"

echo "About to restore the board to commit $SHORT ($(git log -1 --format='%ad %s' --date=short "$FULL"))"
for f in "${RESTORE[@]}"; do
  sz=$(git cat-file -s "$FULL:$f" 2>/dev/null); [ "$f" = "$PAYLOAD_DIR" ] && sz=$(git ls-tree -r -l "$FULL" -- "$PAYLOAD_DIR" | awk '{s+=$4} END {print s}')
  printf '  %-34s %8s MiB\n' "$f" "$(awk -v s="${sz:-0}" 'BEGIN { printf "%.1f", s/1048576 }')"
done
echo "The current plain .json twins, board parts and shards will be MOVED to backups/pre-restore-<stamp>/ first."
if [ "$YES" -ne 1 ]; then
  [ -t 0 ] || { echo "not a terminal: pass --yes to confirm" >&2; job_event_end failed "" "needs_yes"; exit 2; }
  printf 'Type RESTORE to continue: '; read -r ans
  [ "$ans" = "RESTORE" ] || { echo "cancelled"; job_event_end no_change "" "cancelled"; exit 1; }
fi

# 2. plain twins and shards out of the way (moved, never deleted)
STAMP=$(date +%Y%m%dT%H%M%S)
KEEPDIR="$ROOT/backups/pre-restore-$STAMP"
mkdir -p "$KEEPDIR"
for f in "${PLAIN_FILES[@]}"; do [ -e "$f" ] && mv "$f" "$KEEPDIR/"; done
[ -d "$PAYLOAD_DIR" ] && mv "$PAYLOAD_DIR" "$KEEPDIR/"
# every current board part goes (moved, not copied): the commit being restored may hold fewer
# parts than the tree, and a stray part the restored manifest does not list is a torn set
for f in docs/listings_part_[0-9]*.json.gz; do [ -e "$f" ] && mv "$f" "$KEEPDIR/"; done
for f in docs/listings.json.gz docs/listings_detail.json.gz docs/listings_slim.json.gz docs/board.manifest.json; do
  [ -e "$f" ] && cp -p "$f" "$KEEPDIR/" 2>/dev/null
done
echo "previous state kept in $KEEPDIR"

# 3. everything from ONE commit
if ! git restore --source="$FULL" --worktree -- "${RESTORE[@]}"; then
  echo "!! git restore failed. The previous files are in $KEEPDIR." >&2
  job_event_end failed "" "git_restore_failed"; exit 1
fi
# a commit that predates the manifest must not leave a NEWER manifest describing other files
have docs/board.manifest.json || { [ -e docs/board.manifest.json ] && mv docs/board.manifest.json "$KEEPDIR/board.manifest.json.stale"; }

# 4. digests, and the manifest check
echo "restored files (sha256):"
for f in docs/listings_part_[0-9]*.json.gz docs/listings.json.gz docs/listings_detail.json.gz docs/listings_slim.json.gz docs/run_meta.json; do
  [ -f "$f" ] && printf '  %s  %s\n' "$(shasum -a 256 "$f" | cut -c1-16)" "$f"
done
if [ -d "$PAYLOAD_DIR" ]; then
  printf '  %s  %s (%s files)\n' "$(cat "$PAYLOAD_DIR"/*.json.gz | shasum -a 256 | cut -c1-16)" "$PAYLOAD_DIR" "$(ls "$PAYLOAD_DIR" | wc -l | tr -d ' ')"
fi
MAN_OK="no manifest in this commit"
if [ -f docs/board.manifest.json ]; then
  MAN_OK=$(/usr/bin/python3 - <<'PY'
import hashlib, json, os
m = json.load(open("docs/board.manifest.json"))
bad = []
for name, ent in m.get("files", {}).items():
    p = os.path.join("docs", name)
    if not os.path.isfile(p):
        if name in ("listings.json", "listings_detail.json", "listings_slim.json"):
            continue                   # plain twins are gitignored; a fresh restore lacks them
        bad.append(name + " (missing)")        # a part or .gz the manifest names must be there
        continue
    if os.path.getsize(p) != ent.get("bytes"):
        bad.append(name + " (size)"); continue
    h = hashlib.sha256()
    with open(p, "rb") as fh:
        for chunk in iter(lambda: fh.read(8 << 20), b""):
            h.update(chunk)
    if h.hexdigest() != ent.get("sha256"):
        bad.append(name + " (sha256)")
print("MATCHES" if not bad else "MISMATCH: " + ", ".join(bad[:5]))
PY
)
fi
echo "manifest check: $MAN_OK"
case "$MAN_OK" in
  MISMATCH*) echo "!! the manifest committed with $SHORT disagrees with its own files (a publisher staged the payload without the manifest)." >&2
             echo "   Run scripts/board_manifest.py --rebuild once you have checked the files, or BOARD_MANIFEST_SKIP=1 to load without checking." >&2 ;;
  "no manifest"*) echo "   $SHORT predates docs/board.manifest.json. Loading works (no manifest = legacy checks); run scripts/board_manifest.py --rebuild to seal it." ;;
esac

# 5. the count guard
TOTAL=$(grep -oE '"total": [0-9]+' docs/run_meta.json 2>/dev/null | head -1 | grep -oE '[0-9]+')
HW=$(grep -oE '"count": [0-9]+' docs/board_highwater.json 2>/dev/null | head -1 | grep -oE '[0-9]+')
if [ -n "${TOTAL:-}" ] && [ -n "${HW:-}" ] && [ "$TOTAL" -lt $(( HW * 9 / 10 )) ]; then
  echo "!! restored board has $TOTAL rows; docs/board_highwater.json says $HW. The COUNT GUARD will refuse the next write"
  echo "   (more than 10% below the mark). Run the next writer once with BOARD_ALLOW_SHRINK=1, or edit the mark."
fi
echo "restore complete: commit $SHORT, ${TOTAL:-?} rows. Nothing was staged, committed or pushed."
job_event_end ok "${TOTAL:-}" "restored=$SHORT"
