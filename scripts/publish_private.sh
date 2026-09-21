#!/bin/sh
# scripts/publish_private.sh
#
# PROTOTYPE. Publishes the dashboard payload to a PRIVATE object store (the
# Cloudflare R2 bucket in docs/HOSTING_OPTIONS_2026-09-21.md) instead of git.
#
#   scripts/publish_private.sh                 dry run: local checks + plan, NO network
#   scripts/publish_private.sh --apply         really upload (needs a configured target)
#
# It refuses to touch anything remote unless BOTH are true:
#   1. you passed --apply, and
#   2. a target is configured: PRIVATE_HOST_TARGET=<rclone-remote>:<bucket>
#      (or --target). The rclone remote must already exist in your rclone config.
#
# Credentials live in rclone's own config (~/.config/rclone/rclone.conf) or in
# RCLONE_CONFIG_<REMOTE>_* environment variables. This script never reads
# .secrets/ or .env.
#
# LAYOUT IN THE BUCKET
#   releases/<release-id>/...   the index-aligned board files. One release is one
#                               publish; files inside a release are never mixed.
#   parcel_photos/...           shared, append-mostly, only new/changed files sent
#   current.json                tiny pointer, written LAST. The Worker serves the
#                               release it names, so the flip is the atomic step.
#
# WHY A POINTER: dashboard.js joins listings, slim, detail and shards by array
# index, and that only holds within ONE write_artifact() call. Uploading files
# one by one into a single flat prefix would expose a mis-joined board for as long
# as the upload runs. A release prefix plus a last-written pointer cannot.
#
# NOT HANDLED HERE: the app shell (index.html, dashboard.js, css, manifest, icons).
# That ships with `wrangler deploy` and changes rarely.
#
# Exit codes: 0 ok, 1 refused or failed a check, 2 bad usage.

set -eu

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
APPLY=0
PRUNE=0
KEEP=3
TARGET="${PRIVATE_HOST_TARGET:-}"

die() { echo "REFUSED: $*" >&2; exit 1; }

usage() {
  sed -n '2,/^set -eu/p' "$0" | sed '$d' | sed 's/^# \{0,1\}//'
  cat <<'EOF'

Options
  --apply         perform the upload (default is a dry run)
  --target R:B    rclone remote and bucket, e.g. r2:foreclosure-board
                  (or set PRIVATE_HOST_TARGET)
  --prune         after a successful publish, delete release prefixes older
                  than the newest --keep (needs --apply; off by default)
  --keep N        releases to keep when pruning (default 3, minimum 2)
  --root DIR      repo root (for tests)
  -h, --help      this text
EOF
}

while [ $# -gt 0 ]; do
  case "$1" in
    --apply) APPLY=1 ;;
    --prune) PRUNE=1 ;;
    --keep)   [ $# -ge 2 ] || { echo "--keep needs a number" >&2; exit 2; }; KEEP="$2"; shift ;;
    --target) [ $# -ge 2 ] || { echo "--target needs remote:bucket" >&2; exit 2; }; TARGET="$2"; shift ;;
    --root)   [ $# -ge 2 ] || { echo "--root needs a directory" >&2; exit 2; }; ROOT="$(cd "$2" && pwd)"; shift ;;
    -h|--help) usage; exit 0 ;;
    *) echo "unknown option: $1" >&2; usage >&2; exit 2 ;;
  esac
  shift
done

case "$KEEP" in ''|*[!0-9]*) echo "--keep must be a whole number" >&2; exit 2 ;; esac
[ "$KEEP" -ge 2 ] || { echo "--keep must be at least 2" >&2; exit 2; }
if [ "$PRUNE" -eq 1 ] && [ "$APPLY" -ne 1 ]; then
  echo "--prune only makes sense with --apply" >&2; exit 2
fi

DOCS="$ROOT/docs"
[ -d "$DOCS" ] || die "no docs/ directory under $ROOT"

# The explicit allowlist. Anything not named here is never uploaded.
#
# THE BOARD is not in this list: since the payload split (audit O1) it is
# listings_part_NNN.json.gz, as many as run_meta.json's board_parts names (each under 24 MiB, so
# each fits Cloudflare's 25 MiB per-asset cap), added to the release below after every one is
# checked against run_meta (present, right size, right sha256, none extra). A release built from
# a pre-split run_meta (no board_parts) falls back to the single listings.json.gz.
REQUIRED_FILES="listings_slim.json.gz listings_detail.json.gz run_meta.json"
OPTIONAL_FILES="run_health.json multifamily.json land_buyers.json foreclosure_sold_pool.json"
SHARD_DIR="detail_shards"
PHOTO_DIR="parcel_photos"

human() { awk -v b="$1" 'BEGIN { printf "%.1f MiB", b / 1048576 }'; }
fsize() { wc -c < "$1" | tr -d ' '; }

# Defence in depth: even an allowlisted name may not look like operator/PII/secret data.
is_denied() {
  case "$1" in
    *crm*|*outreach*|*maillist*|*skiptrace*|*porsche*|*.csv|*.md|*.env*|*secret*|*.pem|*.key|*.sqlite|*.db) return 0 ;;
  esac
  return 1
}

# ---- 1. build the release file list and check every file exists ---------------
LIST="$(mktemp "${TMPDIR:-/tmp}/publish_private.XXXXXX")"
cleanup() { rm -f "$LIST"; }
trap cleanup EXIT

: > "$LIST"
for f in $REQUIRED_FILES; do
  [ -f "$DOCS/$f" ] || die "required file missing: docs/$f"
  printf '%s\n' "$f" >> "$LIST"
done
for f in $OPTIONAL_FILES; do
  [ -f "$DOCS/$f" ] && printf '%s\n' "$f" >> "$LIST"
done
[ -d "$DOCS/$SHARD_DIR" ] || die "docs/$SHARD_DIR is missing; the phone detail panel would break"
SHARDS_ACTUAL=0
for s in "$DOCS/$SHARD_DIR"/[0-9][0-9][0-9][0-9][0-9].json.gz; do
  [ -f "$s" ] || continue
  printf '%s/%s\n' "$SHARD_DIR" "$(basename "$s")" >> "$LIST"
  SHARDS_ACTUAL=$((SHARDS_ACTUAL + 1))
done

# ---- 1b. the board parts named by run_meta.json ---------------------------------
PARTS_INFO="$(python3 - "$DOCS" <<'PY'
import hashlib, json, os, re, sys
docs = sys.argv[1]
CAP = 25 * 1024 * 1024          # Cloudflare's per-asset cap; the writer's own cap is 24 MiB
try:
    m = json.load(open(os.path.join(docs, "run_meta.json")))
except Exception as e:
    print("ERR|run_meta.json unreadable: %s" % e); sys.exit(0)
bp = m.get("board_parts")
if not isinstance(bp, dict) or not isinstance(bp.get("files"), list) or not bp["files"]:
    if os.path.isfile(os.path.join(docs, "listings.json.gz")):
        print("LEGACY|listings.json.gz"); sys.exit(0)
    print("ERR|run_meta.json has no board_parts and there is no docs/listings.json.gz: no board to publish")
    sys.exit(0)
names, total, expect = [], 0, 0
for i, e in enumerate(bp["files"]):
    n = e.get("name") if isinstance(e, dict) else None
    if n != "listings_part_%03d.json.gz" % i:
        print("ERR|board_parts entry %d is %r, expected listings_part_%03d.json.gz" % (i, n, i)); sys.exit(0)
    p = os.path.join(docs, n)
    if not os.path.isfile(p):
        print("ERR|board part missing: docs/%s" % n); sys.exit(0)
    size = os.path.getsize(p)
    if size != e.get("bytes"):
        print("ERR|docs/%s is %d bytes, run_meta.json says %s (a torn or mixed part set)" % (n, size, e.get("bytes"))); sys.exit(0)
    if size > CAP:
        print("ERR|docs/%s is %d bytes, over Cloudflare's 25 MiB per-asset cap (the split did not run?)" % (n, size)); sys.exit(0)
    h = hashlib.sha256()
    with open(p, "rb") as fh:
        for c in iter(lambda: fh.read(8 << 20), b""):
            h.update(c)
    if h.hexdigest() != e.get("sha256"):
        print("ERR|docs/%s does not match its sha256 in run_meta.json (a torn or mixed part set)" % n); sys.exit(0)
    if e.get("start") != expect:
        print("ERR|docs/%s starts at row %s, expected %d" % (n, e.get("start"), expect)); sys.exit(0)
    expect = e.get("end")
    total += e.get("records", 0)
    names.append(n)
extra = sorted(f for f in os.listdir(docs) if re.match(r"^listings_part_\d{3,}\.json\.gz$", f) and f not in names)
if extra:
    print("ERR|part file(s) on disk that run_meta.json does not list: %s" % ", ".join(extra[:4])); sys.exit(0)
print("OK|%d|%d|%s" % (len(names), total, ",".join(names)))
PY
)"
PARTS_N=0; PARTS_ROWS=""
case "$PARTS_INFO" in
  OK\|*)
    _old_ifs="$IFS"; IFS='|'
    set -- $PARTS_INFO
    IFS="$_old_ifs"
    PARTS_N="$2"; PARTS_ROWS="$3"
    _old_ifs="$IFS"; IFS=','
    for _pn in $4; do printf '%s\n' "$_pn" >> "$LIST"; done
    IFS="$_old_ifs"
    ;;
  LEGACY\|*)
    printf '%s\n' "listings.json.gz" >> "$LIST"
    echo "note: run_meta.json has no board_parts; releasing the single listings.json.gz (pre-split layout)" >&2 ;;
  ERR\|*) die "${PARTS_INFO#ERR|}" ;;
  *) die "could not check the board parts" ;;
esac

while IFS= read -r rel; do
  if is_denied "$rel"; then die "allowlist entry looks sensitive, not uploading: $rel"; fi
done < "$LIST"

# ---- 2. read run_meta.json and prove the shards belong to this board ----------
META="$(python3 - "$DOCS/run_meta.json" <<'PY'
import json, re, sys
try:
    m = json.load(open(sys.argv[1]))
except Exception as e:
    print("ERR|run_meta.json unreadable: %s" % e); sys.exit(0)
rt = str(m.get("run_time") or "")
if not rt:
    print("ERR|run_meta.json has no run_time"); sys.exit(0)
rel = re.sub(r"[^0-9A-Za-z]", "", rt.split(".")[0]) + "Z"
b = m.get("board") or {}
ds = b.get("detail_shards") or {}
print("OK|%s|%s|%s|%s|%s" % (rel, b.get("count", ""), ds.get("count", 0), ds.get("size", ""), ds.get("records", "")))
PY
)"
case "$META" in
  OK\|*) ;;
  ERR\|*) die "${META#ERR|}" ;;
  *) die "could not read run_meta.json" ;;
esac
IFS='|' read -r _ok REL BCOUNT SCOUNT SSIZE SRECORDS <<EOF
$META
EOF
[ -n "$REL" ] || die "empty release id"
[ -n "$BCOUNT" ] || die "run_meta.json has no board.count, so the board/shard pairing cannot be proven"
if [ "${PARTS_N:-0}" -gt 0 ]; then
  [ "$PARTS_ROWS" = "$BCOUNT" ] || die "the $PARTS_N board parts hold $PARTS_ROWS rows but run_meta.json declares board.count $BCOUNT (the slim payload and the parts are from different writes)"
fi
[ "$SHARDS_ACTUAL" -eq "$SCOUNT" ] || die "run_meta declares $SCOUNT detail shards but docs/$SHARD_DIR holds $SHARDS_ACTUAL (a mis-joined board would ship)"
# contiguous names 00000..N-1
i=0
while [ "$i" -lt "$SHARDS_ACTUAL" ]; do
  name="$(printf '%05d.json.gz' "$i")"
  [ -f "$DOCS/$SHARD_DIR/$name" ] || die "shard sequence has a gap at $name"
  i=$((i + 1))
done

# ---- 3. every .gz must actually be a valid gzip --------------------------------
GZ_BAD=0
while IFS= read -r rel; do
  case "$rel" in
    *.gz) gzip -t "$DOCS/$rel" 2>/dev/null || { echo "corrupt gzip: docs/$rel" >&2; GZ_BAD=$((GZ_BAD + 1)); } ;;
  esac
done < "$LIST"
[ "$GZ_BAD" -eq 0 ] || die "$GZ_BAD corrupt .gz file(s); refusing to publish"

# ---- 4. sizes for the plan ------------------------------------------------------
TOTAL=0
FILES=0
while IFS= read -r rel; do
  s="$(fsize "$DOCS/$rel")"
  TOTAL=$((TOTAL + s)); FILES=$((FILES + 1))
done < "$LIST"

PHOTO_COUNT=0
PHOTO_KIB=0
if [ -d "$DOCS/$PHOTO_DIR" ]; then
  PHOTO_COUNT="$(find "$DOCS/$PHOTO_DIR" -type f \( -iname '*.jpg' -o -iname '*.jpeg' -o -iname '*.png' -o -iname '*.webp' \) | wc -l | tr -d ' ')"
  PHOTO_KIB="$(du -sk "$DOCS/$PHOTO_DIR" | cut -f1)"
fi

# ---- 5. print the plan ----------------------------------------------------------
if [ "$APPLY" -eq 1 ]; then MODE="APPLY"; else MODE="DRY RUN (nothing is uploaded, no network is used)"; fi
echo "publish_private.sh : $MODE"
echo "repo root          : $ROOT"
echo "target             : ${TARGET:-(not configured)}"
echo "release id         : $REL   (from run_meta.json run_time)"
echo "board              : $BCOUNT records; $SCOUNT detail shards (size ${SSIZE:-?}, records ${SRECORDS:-?}) declared and verified"
if [ "${PARTS_N:-0}" -gt 0 ]; then
  echo "board parts        : $PARTS_N parts, $PARTS_ROWS rows, each size and sha256 checked against run_meta.json"
else
  echo "board parts        : none (pre-split layout: single listings.json.gz)"
fi
echo "gzip integrity     : all $((FILES)) release files checked"
echo
echo "1) release files -> releases/$REL/   ($FILES files, $(human "$TOTAL"))"
while IFS= read -r rel; do
  case "$rel" in "$SHARD_DIR"/*) continue ;; esac
  printf '     %12s  %s\n' "$(human "$(fsize "$DOCS/$rel")")" "$rel"
done < "$LIST"
echo "     ... plus $SHARDS_ACTUAL files under $SHARD_DIR/"
echo "2) photos          -> $PHOTO_DIR/   ($PHOTO_COUNT image files, about $((PHOTO_KIB / 1024)) MiB on disk; only new or changed files are sent)"
echo "3) verify          -> size check of everything just uploaded"
echo "4) pointer         -> current.json = {\"release\":\"$REL\"}   (written LAST, this is the atomic flip)"
if [ "$PRUNE" -eq 1 ]; then
  echo "5) prune           -> delete releases/* older than the newest $KEEP"
else
  echo "5) prune           -> off (add --prune, or use an R2 lifecycle rule)"
fi
echo
echo "Never uploaded: crm.json, outreach_maillist.csv, skiptrace_worksheet.csv, porsche.*, *.md, uncompressed listings*.json, anything in .secrets/ or .env"
echo "A release carries ALL board parts and never a subset: one release is one publish."
echo "App shell (index.html, dashboard.js, css, manifest, icons) is deployed separately with wrangler."

if [ "$APPLY" -ne 1 ]; then
  echo
  echo "Dry run complete. To publish for real: set PRIVATE_HOST_TARGET and re-run with --apply."
  exit 0
fi

# ---- 6. APPLY: every guard must pass before anything remote happens -------------
[ -n "$TARGET" ] || die "no target configured. Set PRIVATE_HOST_TARGET=<rclone-remote>:<bucket> or pass --target."
case "$TARGET" in
  *:?*) ;;
  *) die "target must look like <rclone-remote>:<bucket>, got '$TARGET'" ;;
esac
command -v rclone >/dev/null 2>&1 || die "rclone is not installed"
REMOTE="${TARGET%%:*}"
rclone listremotes 2>/dev/null | grep -qx "$REMOTE:" || die "rclone remote '$REMOTE' is not configured (see docs/HOSTING_SETUP_CHECKLIST.md)"

# One board writer at a time; do not publish while a writer is mid-write.
. "$ROOT/scripts/board_lock.sh"
set +u
if ! board_lock_acquire "$ROOT" "publish_private.sh" 0; then
  # board_lock_refusal_message words both refusals (writer active, memory gate).
  if command -v board_lock_refusal_message >/dev/null 2>&1; then
    die "$(board_lock_refusal_message 'the private publish'); nothing was uploaded, try again later"
  fi
  die "a board writer is active ($(board_lock_holder)); try again when it finishes"
fi
# errexit off inside the trap: board_lock_release ends with `wait` on the killed
# heartbeat, which returns 143, and under `set -e` that would abort the release
# before it removed the lock (found by the local fixture test).
trap 'set +eu; board_lock_release; cleanup' EXIT INT TERM
set -u

RC_FLAGS="--s3-no-check-bucket --transfers 8 --checkers 16"

echo
echo "== 1/5 uploading release files =="
# shellcheck disable=SC2086
rclone copy "$DOCS" "$TARGET/releases/$REL" --files-from "$LIST" $RC_FLAGS -v

echo "== 2/5 syncing photos =="
if [ -d "$DOCS/$PHOTO_DIR" ]; then
  # shellcheck disable=SC2086
  rclone copy "$DOCS/$PHOTO_DIR" "$TARGET/$PHOTO_DIR" --size-only --ignore-case \
    --include '*.jpg' --include '*.jpeg' --include '*.png' --include '*.webp' $RC_FLAGS -v
fi

echo "== 3/5 verifying =="
# shellcheck disable=SC2086
rclone check "$DOCS" "$TARGET/releases/$REL" --files-from "$LIST" --size-only --one-way $RC_FLAGS \
  || die "verification failed; the pointer was NOT moved, so the live board is unchanged"

echo "== 4/5 flipping the pointer =="
printf '{"release":"%s","published_at":"%s","board_count":%s}\n' \
  "$REL" "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$BCOUNT" \
  | rclone rcat "$TARGET/current.json" --s3-no-check-bucket
echo "live release is now $REL"

if [ "$PRUNE" -eq 1 ]; then
  echo "== 5/5 pruning old releases (keeping newest $KEEP) =="
  rclone lsf --dirs-only "$TARGET/releases/" 2>/dev/null | sed 's:/$::' | sort -r | tail -n +"$((KEEP + 1))" \
  | while IFS= read -r old; do
      [ -n "$old" ] && [ "$old" != "$REL" ] || continue
      echo "  deleting releases/$old"
      rclone purge "$TARGET/releases/$old" --s3-no-check-bucket
    done
else
  echo "== 5/5 prune skipped =="
fi
echo "done."
