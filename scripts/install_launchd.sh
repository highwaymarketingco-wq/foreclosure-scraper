#!/bin/bash
# Render deploy/mac/*.plist templates into ~/Library/LaunchAgents.
#
# DRY RUN BY DEFAULT. With no flags this prints, per template, whether the installed plist
# is SAME, CHANGED (with a diff) or NEW, and touches nothing.
#
#   scripts/install_launchd.sh                       dry run, every template
#   scripts/install_launchd.sh lrcpwa sosagent       dry run, just these (name = label suffix)
#   scripts/install_launchd.sh --apply [names]       write the plists, then (re)load them
#   scripts/install_launchd.sh --unload names        unload them (launchctl bootout)
#   scripts/install_launchd.sh --dest DIR ...        render into DIR instead; never loads anything
#
# What --apply does, in order, per template: render (__ROOT__ and __HOME__ substituted),
# `plutil -lint` it, copy the previous plist to <dest>/.backup-<stamp>/, write the new one,
# then `launchctl bootout` + `launchctl bootstrap` for the gui/<uid> domain. Nothing else is
# ever loaded, and the disabled dailycourt job has no template so it can never come back by
# accident.
#
# Templates are the source of truth for the schedule; the installed set as of 2026-09-21 is
# kept verbatim in deploy/mac/installed-2026-09-21/.
set -uo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
TPL="$ROOT/deploy/mac"
DEST="$HOME/Library/LaunchAgents"
APPLY=0; UNLOAD=0; DEST_GIVEN=0
NAMES=()
while [ $# -gt 0 ]; do
  case "$1" in
    --apply) APPLY=1 ;;
    --unload) UNLOAD=1 ;;
    --dest) DEST="$2"; DEST_GIVEN=1; shift ;;
    -h|--help) sed -n 2,20p "$0"; exit 0 ;;
    *) NAMES+=("$1") ;;
  esac
  shift
done

render() { sed -e "s|__ROOT__|$ROOT|g" -e "s|__HOME__|$HOME|g" "$1"; }

all_templates() { ls "$TPL"/com.highway.foreclosure.*.plist 2>/dev/null; }
selected() {
  if [ "${#NAMES[@]}" -eq 0 ]; then all_templates; return; fi
  for n in "${NAMES[@]}"; do
    f="$TPL/com.highway.foreclosure.$n.plist"
    [ -f "$f" ] && echo "$f" || echo "no template named '$n' (looked for $f)" >&2
  done
}

STAMP=$(date +%Y%m%dT%H%M%S)
UIDN=$(id -u)
mkdir -p "$DEST" 2>/dev/null
[ "$APPLY" -eq 1 ] && echo "APPLY mode: writing to $DEST" || echo "DRY RUN (nothing is written or loaded). Add --apply to install."
for tpl in $(selected); do
  base=$(basename "$tpl"); label=${base%.plist}
  if [ "$UNLOAD" -eq 1 ]; then
    if [ "$APPLY" -eq 1 ] && [ "$DEST_GIVEN" -eq 0 ]; then
      launchctl bootout "gui/$UIDN/$label" 2>&1 | sed "s|^|  $label: |"
    else
      echo "would unload $label"
    fi
    continue
  fi
  out=$(mktemp)
  render "$tpl" > "$out"
  if ! plutil -lint "$out" >/dev/null 2>&1; then echo "!! $label: rendered plist is invalid"; rm -f "$out"; continue; fi
  cur="$DEST/$base"
  if [ ! -f "$cur" ]; then status="NEW"
  elif cmp -s "$out" "$cur"; then status="SAME"
  else status="CHANGED"; fi
  echo "== $label: $status"
  if [ "$status" = "CHANGED" ]; then diff -u "$cur" "$out" | sed 's/^/     /' | head -40; fi
  if [ "$APPLY" -eq 1 ] && [ "$status" != "SAME" ]; then
    if [ -f "$cur" ]; then mkdir -p "$DEST/.backup-$STAMP"; cp "$cur" "$DEST/.backup-$STAMP/"; fi
    cp "$out" "$cur"
    echo "   wrote $cur"
    if [ "$DEST_GIVEN" -eq 0 ]; then
      launchctl bootout "gui/$UIDN/$label" >/dev/null 2>&1
      launchctl bootstrap "gui/$UIDN" "$cur" 2>&1 | sed 's/^/   launchctl: /'
    fi
  fi
  rm -f "$out"
done
