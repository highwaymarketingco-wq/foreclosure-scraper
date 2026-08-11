#!/bin/bash
# One-click ingest of operator-saved court pages (SC PublicIndex + NC eCourts).
# No terminal needed — the Desktop "Ingest Saved Court Pages" app calls this.
#
# SAFE BY DESIGN:
#  - refuses to run while a full engine run is writing the board (would clobber it)
#  - refuses to run twice at once (atomic lock dir)
#  - idempotent: the underlying ingesters dedupe by case number, so re-running
#    never creates duplicates.
# It scans the Desktop drop folder + the repo root + ~/Downloads, so wherever you
# saved the pages, they get picked up.
set -uo pipefail
REPO="$HOME/foreclosure-scraper"
DROP="$HOME/Desktop/Court Pages (drop here)"
DL="$HOME/Downloads"
UV="$HOME/.local/bin/uv"
notify(){ osascript -e "display notification \"$1\" with title \"Court Pages\"" >/dev/null 2>&1; }

cd "$REPO" 2>/dev/null || { osascript -e 'display alert "Court Pages" message "Could not find ~/foreclosure-scraper."' >/dev/null 2>&1; exit 1; }
mkdir -p "$DROP" logs

# NEVER write the board while ANY other board writer holds it — and never run
# two ingests at once. One lock now does both jobs.
#
# What was here was a pgrep list plus a private .ingest.lock. The pgrep was
# TOCTOU-racy (a check before the critical section cannot see a writer that
# starts after it) and it did not list the daily vision job, the noon lrcpwa
# pass or the 2pm SOS pass — each of which holds a loaded board for minutes to
# hours and would silently revert whatever this ingest added. The private lock
# only ever excluded another copy of this same script. See scripts/board_lock.sh.
. "$REPO/scripts/board_lock.sh"
if ! board_lock_acquire "$REPO" "ingest_saved.sh"; then
  notify "Another board job ($(board_lock_holder)) is running — I won't touch the board now. Try again after it finishes."
  exit 0
fi
trap 'board_lock_release' EXIT INT TERM

LOG="logs/ingest-saved.log"
{ echo; echo "=== ingest_saved $(date) ==="; } >>"$LOG"

shopt -s nullglob nocaseglob

# Anything to do?
have=0
for d in "$DROP" "$REPO" "$DL"; do
  for f in "$d"/*.html "$d"/*.htm "$d"/*.csv; do have=1; break; done
done
if [ "$have" -eq 0 ]; then
  notify "No saved pages found. Save the court pages into the folder first, then run this again."
  open "$DROP" >/dev/null 2>&1
  exit 0
fi

notify "Ingesting saved court pages… you'll get a summary when it's done."

# ---- SC PublicIndex: dedicated direct-to-board ingester (auto-detects PI pages) ----
sc_out=$("$UV" run python scripts/ingest_publicindex_files.py "$DROP" "$REPO" "$DL" 2>&1)
printf '%s\n' "$sc_out" >>"$LOG"
sc_add=$(printf '%s\n' "$sc_out" | grep -oE '\+[0-9]+ leads' | grep -oE '[0-9]+' | head -1)
sc_add=${sc_add:-0}

# ---- NC eCourts: parse each saved page -> aggregate JSON -> fresh_court ingester ----
nc_found=0
STAGE="$(mktemp -d)"
i=0
for d in "$DROP" "$REPO" "$DL"; do
  for f in "$d"/*_nc_*.html "$d"/*ecourts*.html "$d"/*tylertech*.html "$d"/*odyssey*.html; do
    base=$(basename "$f")
    county=$(printf '%s' "$base" | sed -E 's/_nc_.*//; s/\.[^.]*$//' | tr '_' ' ')
    if "$UV" run python scripts/parse_nc_ecourts_export.py "$f" --as-listings ${county:+--county "$county"} --out "$STAGE/nc_$i.json" 2>>"$LOG"; then
      i=$((i+1))
    fi
  done
done
if [ "$i" -gt 0 ]; then
  nc_found=$("$UV" run python - "$STAGE" <<'PY'
import json, sys, glob, os
out = []
for p in glob.glob(os.path.join(sys.argv[1], "nc_*.json")):
    try:
        out += json.load(open(p))
    except Exception:
        pass
json.dump(out, open(os.path.join(sys.argv[1], "all.json"), "w"))
print(len(out))
PY
)
  nc_found=${nc_found:-0}
  if [ "$nc_found" -gt 0 ]; then
    nc_out=$(FRESH_FILE="$STAGE/all.json" MERGE_FAST=1 "$UV" run python scripts/ingest_fresh_court_leads.py 2>&1)
    printf '%s\n' "$nc_out" >>"$LOG"
  fi
fi
rm -rf "$STAGE"

# Tidy: move the processed files OUT of the drop folder so it stays clean.
# (Only the Desktop drop folder — never touch repo root / Downloads other files.)
moved=0
DONE="$DROP/Ingested $(date +%Y-%m-%d_%H%M)"
for f in "$DROP"/*.html "$DROP"/*.htm "$DROP"/*.csv; do
  mkdir -p "$DONE"; mv "$f" "$DONE"/ 2>/dev/null && moved=1
done
[ "$moved" -eq 0 ] && rmdir "$DONE" 2>/dev/null

notify "Done. Added $sc_add SC lead(s); found $nc_found NC court record(s). Dashboard updated."
echo "=== done $(date): +$sc_add SC, $nc_found NC ===" >>"$LOG"
exit 0
