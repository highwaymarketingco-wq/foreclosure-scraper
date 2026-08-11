#!/bin/sh
# The publishable dashboard payload, in ONE place. Source this; do not execute.
#
#   . "$ROOT/scripts/board_payload.sh"
#   board_payload_add "$ROOT"
#   if board_payload_changed "$ROOT"; then git commit …; fi
#
# NEVER `git add $(board_payload_paths …)`. Two of the callers are #!/bin/zsh,
# and zsh does not word-split unquoted command substitution — that would hand
# git ONE pathspec containing newlines. board_payload_add loops instead, which
# is also strictly safer: staging each path in its own `git add` means a single
# bad pathspec can no longer take the whole publish down with it (that failure
# mode — one ignored path silently voiding the entire add — is D1).
#
# WHAT IS IN IT, and why each rule exists (all of these have bitten this repo):
#
#  * .gz TWINS ONLY. docs/listings.json, docs/listings_detail.json and
#    docs/listings_slim.json are GITIGNORED (they exceed GitHub's 100MB/file
#    limit and docs/_config.yml excludes them from Pages). `git add` on an
#    ignored path fails the WHOLE add — every other path in the same command is
#    silently skipped. Two live GitHub Actions workflows ran
#    `git add docs/listings.json docs/run_health.json 2>/dev/null || true`
#    and, because the error was swallowed, published run_health.json ALONE: a
#    health report describing a board it did not ship.
#
#  * "EXISTS OR IS ALREADY TRACKED", never plain "exists". A pathspec matching
#    no file AND absent from the index makes `git add` exit 128 and stage
#    NOTHING AT ALL. But once a file is tracked we must still be able to stage
#    its DELETION — that is how _emit_slim's delete-on-failure path, and the
#    FORECLOSURE_SLIM=0 emergency stop, actually reach the live site.
#
#  * DIRECTORIES BEHAVE THE SAME. docs/detail_shards absent AND untracked exits
#    128; tracked, `git add docs/detail_shards` stages additions, modifications
#    AND deletions inside it.
#
#  * ONE PUBLISH, ALL SIX FILES. index i is the join across listings.json,
#    listings_detail.json, listings_slim.json and detail_shards/, and that
#    alignment only holds within a single write_artifact() call. Staging some
#    and not others ships a mis-joined board: one property's comps, vision and
#    CAMA under a different property's address. That is exactly what happened
#    when the fat board was committed without the fresh slim file — desktop
#    looked perfect the whole time.

# board_payload_paths <repo-root> — newline-separated, safe to hand to `git add`.
board_payload_paths() {
  _bproot="$1"
  for _bp in \
      docs/listings.json.gz \
      docs/listings_detail.json.gz \
      docs/listings_slim.json.gz \
      docs/detail_shards \
      docs/run_meta.json \
      docs/run_health.json \
      docs/foreclosure_sold_pool.json \
      docs/multifamily.json \
      docs/parcel_photos
  do
    if [ -e "$_bproot/$_bp" ] \
       || git -C "$_bproot" ls-files --error-unmatch "$_bp" >/dev/null 2>&1; then
      printf '%s\n' "$_bp"
    fi
  done
}

# board_payload_add <repo-root> — stage every payload path that is safe to stage.
board_payload_add() {
  board_payload_paths "$1" | while IFS= read -r _bpp; do
    [ -n "$_bpp" ] && git -C "$1" add "$_bpp" 2>/dev/null
  done
  return 0
}

# board_payload_changed <repo-root> — 0 when something in the payload actually
# moved, 1 when nothing did.
#
# run_meta.json is deliberately EXCLUDED: its run_time changes on every write, so
# a gate that watched it would fire every run and could never do its job, which
# is to stop a rate-limited / walled pass from creating an empty commit. Every
# OTHER staged path is watched. sos_agent_refresh.sh used to watch only
# board/detail/shards while its else-branch `git reset -q` threw away everything
# staged — so a run whose only effect was on docs/listings_slim.json.gz (the
# payload phones fetch) staged the fresh slim, was told "no change", reset it,
# and never published it.
board_payload_changed() {
  # `for x in $(cmd)` splits on IFS in sh, bash AND zsh (zsh's no-split rule
  # covers $var, not $(cmd) — verified). None of these paths contains a space.
  _bpc=1
  for _bpp in $(board_payload_paths "$1" | grep -v '^docs/run_meta\.json$'); do
    if ! git -C "$1" diff --cached --quiet -- "$_bpp" 2>/dev/null; then
      _bpc=0
    fi
  done
  return $_bpc
}

# board_payload_stash / board_payload_unstash <repo-root> <tarfile>
#
# For the GitHub Actions publishers, which `git reset --hard origin/main` to
# rebase their output onto whatever landed during a two-hour run. That reset
# destroys every tracked payload file. They used to `cp docs/listings.json` and
# `cp docs/run_health.json` aside and restore those two — which was consistent
# with staging only those two, and both of those choices were wrong: listings.json
# is gitignored, so what actually survived and got committed was run_health.json
# ALONE, a health report describing a board the workflow did not ship.
#
# tar, not cp: the payload includes a DIRECTORY (docs/detail_shards) and must
# come back with the same layout, and tar preserves an absent member silently
# instead of failing the step.
board_payload_stash() {
  _bsroot="$1"; _bstar="$2"
  ( cd "$_bsroot" && board_payload_paths "$_bsroot" | tar -cf "$_bstar" -T - 2>/dev/null ) || true
}

board_payload_unstash() {
  _buroot="$1"; _butar="$2"
  [ -f "$_butar" ] || return 0
  ( cd "$_buroot" && tar -xf "$_butar" ) || true
}

# board_payload_check <repo-root> — prove GitHub Pages will actually serve what
# we are about to publish. Jekyll's exclude/include are PREFIX matches, so
# `exclude: listings.json` also drops listings.json.gz; that trap has 404'd this
# site's data three times. Non-fatal here on purpose: the payload is not the
# thing that is broken when this fails, docs/_config.yml is, and the hard gate
# lives in .github/workflows/pages.yml where a failure keeps the last good
# deploy live instead of replacing it with a 404.
board_payload_check() {
  _bcroot="$1"
  if [ -x "$_bcroot/scripts/check_pages_publish.py" ] || [ -f "$_bcroot/scripts/check_pages_publish.py" ]; then
    if ! python3 "$_bcroot/scripts/check_pages_publish.py" >/dev/null 2>&1; then
      echo "==> !! PAGES PUBLISH CHECK FAILED — a required payload file would 404" \
           "on the live site. Run: python3 scripts/check_pages_publish.py"
      return 1
    fi
  fi
  return 0
}
