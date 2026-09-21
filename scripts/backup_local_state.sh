#!/bin/bash
# Nightly copy of everything that exists ONLY on this Mac (audit 2026-09-21 O5).
#
#   scripts/backup_local_state.sh                  # back up to $BACKUP_DEST
#   BACKUP_DEST=/Volumes/Backup/foreclosure scripts/backup_local_state.sh
#
# WHY. The board itself survives a lost disk (224 commits on GitHub). Nothing else does:
# `tmutil destinationinfo` says "No destinations configured". Local-only and irreplaceable
# or slow to rebuild: data/sc_parcel_mailing.db, data/sc_footprints.db (2.5 GB),
# data/parcel_inventory.db, data/sc_cama.db, data/notice_pdfs, data/ncvoter, the last full-run
# checkpoint, docs/crm.json (CRM state for 18,280 leads), the harvest outputs in logs/, the
# API keys in .secrets/ and .env, and the launchd plists (which the repo had no copy of).
#
# WHERE. $BACKUP_DEST, default ~/Documents/foreclosure-backups/. One directory per night,
# named YYYYmmdd-HHMMSS, and the newest BACKUP_KEEP_DAYS (7) are kept. Files that did not
# change since the previous night are HARD-LINKED, not copied, so a night in which the 2.5 GB
# footprints database did not change costs no extra disk. NOTE: the default lives on the SAME
# disk as the data, so it protects against a deleted or corrupted file, not a dead SSD. To
# survive the disk, point BACKUP_DEST at an external drive or a synced folder.
#
# SECRETS (.secrets/ and .env). NEVER copied in the clear. They go into ONE archive,
# secrets.tar.gz.enc, encrypted with `openssl enc -aes-256-cbc -pbkdf2 -iter 200000`. The
# passphrase is read from the macOS KEYCHAIN, item service "foreclosure-backup-passphrase"
# (account = your login name), and never from a file, an argument or a log. Create it once,
# typing the passphrase yourself at the prompt:
#     security add-generic-password -a "$USER" -s foreclosure-backup-passphrase -w
# If the item is missing the secrets are simply NOT backed up and the job says so. To restore:
#     security find-generic-password -a "$USER" -s foreclosure-backup-passphrase -w \
#       | { read -r p; openssl enc -d -aes-256-cbc -pbkdf2 -iter 200000 -pass fd:3 3<<<"$p" \
#           -in secrets.tar.gz.enc | tar xzf -; }
#
# SQLite files are copied with `sqlite3 .backup` (a consistent snapshot, safe while a job has
# the file open), other files with cp -p.
#
# Knobs: BACKUP_DEST, BACKUP_KEEP_DAYS (7), BACKUP_ENCRYPT_SECRETS (1), BACKUP_KEYCHAIN_SERVICE,
# BACKUP_MIN_FREE_GB (5), FORECLOSURE_ROOT. Tests may set BACKUP_PASSPHRASE_CMD to stand in for
# the keychain lookup; production never does.
set -uo pipefail
export PATH="$HOME/.local/bin:/opt/homebrew/bin:$PATH"
ROOT="${FORECLOSURE_ROOT:-$(cd "$(dirname "$0")/.." && pwd)}"
cd "$ROOT" || exit 1
mkdir -p "$ROOT/logs"
BACKUP_DEST="${BACKUP_DEST:-$HOME/Documents/foreclosure-backups}"
KEEP="${BACKUP_KEEP_DAYS:-7}"
KSVC="${BACKUP_KEYCHAIN_SERVICE:-foreclosure-backup-passphrase}"
LOG="$ROOT/logs/backup.log"
exec >> "$LOG" 2>&1
echo "=== backup_local_state $(date) -> $BACKUP_DEST ==="

. "$ROOT/scripts/job_event.sh"
JOB_EVENT_ROOT="$ROOT"
job_event_begin backup_local_state
trap 'job_event_finalize' EXIT INT TERM

# The fixed list: paths relative to ROOT. A missing item is skipped and reported, never fatal.
ITEMS=(
  data/sc_parcel_mailing.db
  data/sc_footprints.db
  data/parcel_inventory.db
  data/sc_cama.db
  data/notice_pdfs
  data/ncvoter
  data/checkpoint/board.json.gz
  docs/crm.json
)
# harvest outputs and the event log from logs/ (the *.log files are not worth keeping)
LOG_GLOBS=( "logs/*.json" "logs/*.jsonl" "logs/*.jsonl.1" )

mkdir -p "$BACKUP_DEST" || { echo "!! cannot create $BACKUP_DEST"; job_event_end failed "" "dest_unwritable"; exit 1; }
FREE_KB=$(df -k "$BACKUP_DEST" | awk 'NR==2 {print $4}')
if [ -n "$FREE_KB" ] && [ "$FREE_KB" -lt $(( ${BACKUP_MIN_FREE_GB:-5} * 1024 * 1024 )) ]; then
  echo "!! less than ${BACKUP_MIN_FREE_GB:-5} GB free at $BACKUP_DEST - refusing to back up"
  job_event_end failed "" "low_disk"; exit 1
fi

STAMP=$(date +%Y%m%d-%H%M%S)
SNAP="$BACKUP_DEST/$STAMP"
PREV=$(ls -1d "$BACKUP_DEST"/[0-9]*-[0-9]* 2>/dev/null | grep -E '/[0-9]{8}-[0-9]{6}$' | tail -1)
mkdir -p "$SNAP.partial" || { job_event_end failed "" "mkdir_failed"; exit 1; }
WORK="$SNAP.partial"
: > "$WORK/MANIFEST.tsv"
NCOPIED=0; NLINKED=0; NSKIPPED=0; NFAILED=0

is_sqlite() { [ "$(head -c 15 "$1" 2>/dev/null)" = "SQLite format 3" ]; }
fstat() { stat -f '%z %m' "$1" 2>/dev/null; }     # size mtime

# copy_one <src-file> <rel-path>
copy_one() {
  local src="$1" rel="$2" dst="$WORK/$2" st prevst
  mkdir -p "$(dirname "$dst")"
  st=$(fstat "$src")
  if [ -n "$PREV" ] && [ -f "$PREV/$rel" ]; then
    prevst=$(awk -F'\t' -v r="$rel" '$1 == r { print $2; exit }' "$PREV/MANIFEST.tsv" 2>/dev/null)
    if [ -n "$prevst" ] && [ "$prevst" = "$st" ] && ln "$PREV/$rel" "$dst" 2>/dev/null; then
      NLINKED=$((NLINKED+1)); printf '%s\t%s\n' "$rel" "$st" >> "$WORK/MANIFEST.tsv"; return 0
    fi
  fi
  if is_sqlite "$src" && command -v sqlite3 >/dev/null 2>&1; then
    if sqlite3 "$src" ".backup '$dst'" >/dev/null 2>&1; then NCOPIED=$((NCOPIED+1)); else
      echo "  sqlite backup failed for $rel, falling back to cp"; cp -p "$src" "$dst" && NCOPIED=$((NCOPIED+1)) || { NFAILED=$((NFAILED+1)); return 1; }
    fi
  else
    cp -p "$src" "$dst" && NCOPIED=$((NCOPIED+1)) || { NFAILED=$((NFAILED+1)); return 1; }
  fi
  printf '%s\t%s\n' "$rel" "$st" >> "$WORK/MANIFEST.tsv"
}

for item in "${ITEMS[@]}"; do
  if [ -d "$item" ]; then
    while IFS= read -r f; do copy_one "$f" "${f#./}"; done < <(cd "$ROOT" && find "./$item" -type f 2>/dev/null)
  elif [ -f "$item" ]; then
    copy_one "$ROOT/$item" "$item"
  else
    echo "  skip (absent): $item"; NSKIPPED=$((NSKIPPED+1))
  fi
done
for g in "${LOG_GLOBS[@]}"; do
  for f in $ROOT/$g; do [ -f "$f" ] && copy_one "$f" "${f#$ROOT/}"; done
done
# launchd plists: the repo had no copy of them
for f in "$HOME"/Library/LaunchAgents/com.highway.*.plist*; do
  [ -f "$f" ] && copy_one "$f" "LaunchAgents/$(basename "$f")"
done

# ---- secrets: encrypted or not at all -----------------------------------------------------
SECRETS_STATE="skipped"
if [ "${BACKUP_ENCRYPT_SECRETS:-1}" != "0" ] && { [ -d "$ROOT/.secrets" ] || [ -f "$ROOT/.env" ]; }; then
  if [ -n "${BACKUP_PASSPHRASE_CMD:-}" ]; then PASS=$(eval "$BACKUP_PASSPHRASE_CMD" 2>/dev/null)
  else PASS=$(security find-generic-password -a "$USER" -s "$KSVC" -w 2>/dev/null); fi
  if [ -z "${PASS:-}" ]; then
    echo "!! secrets NOT backed up: no keychain item '$KSVC' for account $USER (see this script's header)"
    SECRETS_STATE="no_passphrase"
  else
    members=(); [ -d "$ROOT/.secrets" ] && members+=(.secrets); [ -f "$ROOT/.env" ] && members+=(.env)
    if tar czf - -C "$ROOT" "${members[@]}" 2>/dev/null \
       | openssl enc -aes-256-cbc -pbkdf2 -iter 200000 -salt -pass fd:3 3<<<"$PASS" -out "$WORK/secrets.tar.gz.enc" 2>/dev/null; then
      SECRETS_STATE="encrypted"
    else
      rm -f "$WORK/secrets.tar.gz.enc"; SECRETS_STATE="encrypt_failed"; NFAILED=$((NFAILED+1))
      echo "!! secrets archive failed"
    fi
  fi
  unset PASS
fi

# ---- seal the snapshot, then rotate -------------------------------------------------------
if [ "$NFAILED" -gt 0 ]; then
  echo "!! $NFAILED item(s) failed; keeping the partial snapshot at $WORK for inspection"
  job_event_end failed "" "failed=$NFAILED copied=$NCOPIED"; exit 1
fi
mv "$WORK" "$SNAP" || { job_event_end failed "" "seal_failed"; exit 1; }
# Rotation touches ONLY directories named YYYYmmdd-HHMMSS inside BACKUP_DEST. Hard links mean
# deleting an old snapshot never removes a file a newer snapshot still shares.
NSNAP=$(ls -1d "$BACKUP_DEST"/[0-9]*-[0-9]* 2>/dev/null | grep -cE '/[0-9]{8}-[0-9]{6}$')
if [ "$NSNAP" -gt "$KEEP" ]; then
  ls -1d "$BACKUP_DEST"/[0-9]*-[0-9]* | grep -E '/[0-9]{8}-[0-9]{6}$' | sort | awk -v n=$(( NSNAP - KEEP )) 'NR<=n' | while IFS= read -r old; do
    echo "  rotate: removing $old"; rm -rf "$old"
  done
fi
echo "done: copied=$NCOPIED linked=$NLINKED skipped=$NSKIPPED secrets=$SECRETS_STATE snapshot=$SNAP"
job_event_end ok "$NCOPIED" "linked=$NLINKED skipped=$NSKIPPED secrets=$SECRETS_STATE"
