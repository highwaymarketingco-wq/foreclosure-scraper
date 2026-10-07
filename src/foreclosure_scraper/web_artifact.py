"""Generate the static-site JSON files consumed by docs/index.html (the live dashboard).

Writes (every one of these, plus a .gz twin for the sidecar and slim payloads, in ONE call;
a publish that stages some and not others ships a mis-joined board):
  docs/listings.json        : array of sanitized listings (Pydantic-dumped, raw kept slim);
                              gitignored local working copy
  docs/listings_part_NNN.json.gz : the SAME array cut into contiguous, independently gzipped
                              parts of at most board_parts.PART_MAX_BYTES each (audit O1: the
                              single 84 MiB listings.json.gz was days from GitHub's 100 MiB
                              limit). The committed, published form of the board.
  docs/listings_detail.json — index-aligned sidecar: the heavy comps/vision keys
  docs/listings_slim.json   — SLIM-V1, the board payload phones fetch
  docs/detail_shards/*.json.gz — index-aligned detail, cut so a phone can fetch one lead
  docs/run_meta.json        : run timestamp, source_status, totals, sources contributing,
                              and the list of board parts (board_parts)
  docs/board.manifest.json  : written LAST: size + sha256 + rows of every file above
"""
from __future__ import annotations

import collections
import hashlib
import itertools
import json
import os
import re
import shutil
import sys
import time
import uuid
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Iterator

import structlog

from . import board_parts as _bp
from .board_parts import BoardIntegrityError  # noqa: F401  (one class: re-exported here)
from .models import Listing
from .stale_link_fallback import annotate_stale_links

log = structlog.get_logger()


# ===========================================================================
# THE BOARD LOCK — one board writer at a time, across shell AND Python.
#
# The critical section is `load_board -> mutate -> write_artifact`, and it is
# MINUTES to HOURS long. Every guard this project had before was a pgrep check
# taken BEFORE that span opened, which is TOCTOU-racy by construction: a check
# that happens before the section can always lose to a writer that starts after
# it. On 2026-08-10 the noon lrcpwa pass (1,064 parcels resolved, 343 county
# values, 410 absentee tags) was silently reverted by the 09:30 vision job
# writing back a board it had loaded at 09:33. Nothing errored, and the revert
# survived three publishes.
#
# WHY NOT flock / shlock.
#   * flock(1) does not exist on macOS (fcntl.flock(2) does, but it dies with
#     the file descriptor, so it cannot be handed from a shell wrapper to the
#     Python child it spawns, and a shell has no portable way to hold one).
#   * /usr/bin/shlock IS present, and it does NOT break stale locks. Measured on
#     this machine (shell_cmds-326, macOS 25.1): a lock whose owner PID is
#     genuinely dead is refused forever —
#         shlock: process 4514 is dead 4514
#         shlock: lock time changed 1786455189 >= 0    -> exit 1
#     Three consecutive invocations, and a hand-written dead-PID lock, all give
#     exit 1. Building on it would have stopped every scheduled job the first
#     time a job was killed mid-run. tests/test_publish_plumbing.py pins the
#     stale-break behaviour we actually need.
#
# THE PROTOCOL (implemented twice — here, and in scripts/board_lock.sh — so a
# shell wrapper and a Python board-writer contend for the SAME lock. The two
# implementations are held together by test_publish_plumbing.py, which drives
# each against the other; do not change one side alone):
#
#   lock      = a DIRECTORY, <repo>/logs/.board.lock  (mkdir is atomic
#               everywhere, and unlike a lockfile it needs no O_EXCL dance)
#   ownership = <lock>/pid, two lines: "<pid>\n<owner label>\n"
#   acquire   = mkdir; on EEXIST read the pid and kill(pid, 0) it
#   stale     = pid file unreadable after a 1s regrace, or the pid is dead
#   break     = rename the whole directory aside, re-check the pid inside it,
#               then remove it. rename() is atomic, so of N racers exactly one
#               wins the right to delete, and the re-check puts it back if a
#               live owner appeared in the gap.
#   release   = remove the directory
#   reentrant = env FORECLOSURE_BOARD_LOCK_HELD carries the lock path to child
#               processes, so `run_daily_vision.sh` (holding the lock) can run
#               patch_vision_gemini.py (which also asks for it) without
#               deadlocking. A child that inherits it never releases it.
#
# ADDED 2026-09-21 (audit O3, O9, O11):
#   record    = the pid file now also carries start epoch, heartbeat epoch, the
#               job's max runtime and a random TOKEN (lines 3 to 6). Old readers
#               read lines 1 and 2 only and are unaffected.
#   children  = <lock>/children/<pid>: a Python writer running INSIDE a wrapper's
#               lock registers itself, so the lock outlives a killed wrapper.
#   stale     = owner AND every registered child dead, OR a live holder older
#               than max runtime + 30 min (broken, logged, and the hung holder is
#               fenced out of write_artifact by the token).
#   enforce   = write_artifact refuses without the lock (require_board_lock).
#   gate      = a memory gate (swap / free RAM) runs before the lock is taken.
# ===========================================================================

BOARD_LOCK_SUBDIR = "logs"
BOARD_LOCK_DIRNAME = ".board.lock"
BOARD_LOCK_PID_FILE = "pid"
BOARD_LOCK_ENV = "FORECLOSURE_BOARD_LOCK_HELD"
# A per-acquisition random token, exported next to BOARD_LOCK_ENV and stored in
# the lock. write_artifact compares the two, so a holder whose lock was broken as
# stale (and re-taken by another job) is fenced OUT of the board even though its
# inherited BOARD_LOCK_ENV still names the path (audit O11).
BOARD_LOCK_TOKEN_ENV = "FORECLOSURE_BOARD_LOCK_TOKEN"
# Explicit escape hatch for tests and one-off tools (audit O3). Never set by a job.
BOARD_LOCK_BYPASS_ENV = "BOARD_LOCK_BYPASS"
BOARD_LOCK_CHILDREN_DIR = "children"
# A lock directory with no readable pid file is either 20 microseconds old (the
# window between mkdir and the pid write) or wreckage. Re-read once after this
# long before calling it wreckage.
BOARD_LOCK_PID_GRACE = 1.0
# A live holder older than its declared max runtime plus this is treated as hung.
BOARD_LOCK_STALE_GRACE = 30 * 60
BOARD_LOCK_DEFAULT_MAX_RUNTIME = 6 * 3600
BOARD_LOCK_HEARTBEAT_SECONDS = 60.0

# --- the memory gate (audit O9) --------------------------------------------
# "Refuse or wait when swap used > 3 GB or free + inactive < 1 GB." Mode:
#   BOARD_MEM_GATE = warn     (DEFAULT) log the pressure as a job event and proceed
#                    enforce  wait up to BOARD_MEM_GATE_WAIT seconds, then refuse
#                    off      do not look
# WHY warn IS THE DEFAULT (both here and in scripts/board_lock.sh): measured
# 2026-09-21 12:40 on this 8 GB Mac with ONE job running, swap used was 7,015 MB
# (4,500 to 5,400 MB all morning per the audit). Against a 3,072 MB threshold that
# is a permanent refusal, so enforcing it by default would skip every scheduled job
# every day. Run in warn for a week, read the mem_gate lines in logs/job_events.jsonl,
# pick thresholds this machine can meet, then set BOARD_MEM_GATE=enforce in the
# launchd plists. A wrapper that already passed the gate holds the lock, and its
# Python children re-enter it without being gated a second time.
BOARD_GATE_SWAP_MB = 3072
BOARD_GATE_FREE_MB = 1024

# --- the board SIZE guard (audit O13, 2026-09-29; ceiling re-measured same day
# after the real streaming fix landed -- see _iter_board_records) --------------
# Separate from the memory-pressure gate above: refuses read_board_records()/
# load_board() BEFORE starting the load when the on-disk source is bigger than
# this machine has been shown to handle safely.
#
# WHAT WAS FIXED. read_board_records()/load_board() used to json.loads() the
# whole board file (the file's full decoded TEXT and its full parsed dict/list
# TREE alive together), then, for load_board(), build a SECOND, completely
# separate graph of validated Listing objects from it, both alive at once. Against
# the real board as it stood on 2026-09-29 (217,773 rows, listings.json
# 2,522,435,265 bytes + listings_detail.json 248,977,252 bytes, combined ~2,643
# MiB) a `--apply` run using that path hit a 26.3 GB footprint and never finished
# (killed after 24 minutes, still climbing); load_board() alone reproduced a
# GC-thrashing sawtooth that never completed in 240s. The fix (this same day)
# streams both files (board_parts.iter_plain_rows/iter_gz_rows/iter_rows: an
# incremental JSON-array decoder, never json.loads() of the whole file) and, for
# load_board(), validates each row into a Listing and lets its raw dict become
# garbage immediately, so only ONE full graph is ever held, never two.
#
# WHAT THE NEW CEILING IS BASED ON. The double-materialization bug above is
# fixed, but read_board_records()'s/load_board()'s CONTRACT is still "hand back
# a full, mutable board" -- so peak memory is still proportional to ROW COUNT,
# and that part is NOT free just because the parsing is streamed. Measured on
# this machine (2026-09-29) by streaming real slices of the actual board (via
# board_parts.iter_plain_rows, so slicing itself never held the whole 2.4 GB
# file either) through the NEW load_board():
#     20,000 rows,  329 MB combined source -> completed in  2.7s,  ~1.40 GiB peak RSS, ~2.13 GiB peak footprint
#     60,000 rows,  877 MB combined source -> completed in 10.1s,  ~2.79 GiB peak RSS, ~3.64 GiB peak footprint
#    100,000 rows, 1562 MB combined source -> completed in 31-44s, ~2.87 GiB peak RSS, ~6.39 GiB peak footprint
# (peak footprint = macOS's `/usr/bin/time -l` "peak memory footprint", which
# counts compressed pages RSS does not -- it is the more honest number under
# real background memory pressure, and it scales far more consistently here:
# ~4.4x the combined source size at both 60K and 100K rows). Extrapolating that
# ~4.4x ratio to the FULL board's current 2,643 MiB combined source projects
# roughly 10-12 GiB of peak footprint to fully materialize it as Listing
# objects -- more than this 8 GB Mac can safely give up, even with the
# double-materialization bug gone, WITHOUT risking the exact kind of harm this
# guard exists to prevent. A fourth, larger real-data trial (approaching the
# full board) was deliberately NOT run to get a tighter number: this machine
# was already showing real paging/compression activity at the 100,000-row
# trial (19.3s of system time, vs. 5.6s at 60,000), and running an even larger
# one unattended is exactly what this codebase's memory-safety rules say not to
# do. 1,200 MB is set with a margin above the cleanly-fast 877 MB point and
# below the 1,562 MB point that already showed real system-wide paging stress.
#
# WHAT IS STILL OPEN. This ceiling does NOT cover the full current board -- a
# `run_scoped_scrapers.py --apply` run against ALL 217,773 rows still refuses
# here, honestly, because fully materializing that many validated Listings
# still doesn't fit this machine, not because the load is broken. The actual
# fix for THAT case is different in kind: avoid re-validating the ~217K
# existing/untouched rows on every write when only a handful of new rows are
# being landed (this file's docstring approach (b); flagged as a follow-up, not
# attempted this session). BOARD_LOAD_ALLOW_LARGE=1 remains the deliberate,
# monitored override for a human who has decided a specific run is worth it.
#
# REAL FULL-BOARD ATTEMPT, 2026-09-29 (task_0658b33b follow-up), CEILING NOT RAISED.
# append_new_rows() had just been measured at only 2.46 GB peak RSS against the real board
# (217,773 -> 217,883 rows, ~2,643 MiB combined source), well under its ~5.3 GB extrapolated
# estimate -- a reasonable hint that this constant's own 10-12 GiB extrapolation (above) might
# also be pessimistic. It was not: load_board(), BOARD_LOAD_ALLOW_LARGE=1, run against the real
# 217,883-row board under an external RSS-polling watchdog (RLIMIT_AS confirmed unusable on this
# Darwin machine -- raises ValueError outright) capped at 6 GiB RSS / 1800s wall clock. `ps`-
# reported RSS stayed under ~1.1 GB and oscillated there (400 MB-1.1 GB) for the entire 12+
# minutes it ran, never tripping the watchdog. A `sample <pid> -f <file>` taken at the 12-minute
# mark, BUT READING ITS "Physical footprint" LINE rather than the RSS this file's other
# measurements already knew to distrust, showed 11.1 GB (peak 11.3 GB) -- essentially exactly
# this constant's own 10-12 GiB extrapolation, and the call stack was parked inside
# gc_collect_main, called from the zip_longest/gen_iternext chain _iter_board_records uses: the
# same GC-thrashing signature BoardLoadTooLarge's docstring describes for the pre-streaming bug,
# just expressed in compressed/swapped pages instead of RSS this time. The run was killed by
# hand (not by the watchdog, which an RSS-only cap would not have tripped until far too late, if
# ever, at this ratio); PhysMem freed ~3 GB the instant it died, confirming the footprint was
# real, not a `sample` artifact. RSS/footprint gap WIDENS with scale -- 2.2x at the 100,000-row
# trial above, ~5.7x here (2.0 GB RSS per the watchdog's own peak vs. 11.1+ GB footprint) --
# which is why an RSS-based watchdog cap alone is NOT a sufficient safety net for a load_board()
# scale experiment; a live `sample`/`/usr/bin/time -l` footprint check is required too. VERDICT:
# the full board still does not fit this 8 GB Mac even with the streaming fix landed --
# BOARD_LOAD_MAX_SOURCE_MB stays at 1,200 MB, not raised. The real board (docs/listings.json,
# docs/listings_detail.json) was never mutated by this attempt -- load_board() only reads;
# nothing called write_artifact.
BOARD_LOAD_MAX_SOURCE_MB = 1200.0

# --- the append-only SIZE guard (task_0658b33b's follow-up, 2026-09-29) -----
# append_new_rows() (below) is a SEPARATE code path from load_board()/read_board_records(): it
# never validates the existing board into Listing objects and never holds a full parsed-dict
# copy of it either -- each existing row is popped (LAZY_DETAIL_KEYS out of raw), re-encoded to
# JSON bytes, and discarded immediately, one row at a time, so it is measurably cheaper than
# either of the two operations BOARD_LOAD_MAX_SOURCE_MB's ceiling was calibrated against. It
# gets its OWN, separately-measured ceiling rather than reusing that one.
#
# MEASURED (2026-09-29), by slicing REAL rows off the actual board with
# board_parts.iter_plain_rows (never json.loads-ing the whole file) into scratch boards, then
# running append_new_rows's own streaming pass (pop + encode + discard) against each slice,
# under /usr/bin/time -l for macOS's real "peak memory footprint" (the same metric
# BOARD_LOAD_MAX_SOURCE_MB's comment uses, for the same reason: it counts compressed pages RSS
# does not, so it is the more honest number under this machine's real background memory
# pressure):
#     20,000 rows,  312 MiB combined source -> 746 MiB peak footprint  (2.39x)
#     40,000 rows,  570 MiB combined source -> 1,118 MiB peak footprint (1.96x)
# compared, on the SAME 40,000-row slice, to load_board()'s existing Listing-based path:
#     40,000 rows,  570 MiB combined source -> 2,719 MiB peak footprint (4.77x)
# and to a plain list[dict] materialization (no Listing, but still ONE long-lived list held for
# the whole pass -- i.e. read_board_records()'s own shape, not append_new_rows's):
#     40,000 rows,  570 MiB combined source -> 2,791 MiB peak footprint (4.90x)
# The last two numbers were the real surprise: skipping Listing.model_validate() ALONE barely
# helps (4.77x vs 4.90x) -- the expensive part is not pydantic, it is holding ANY full-length
# list of parsed rows alive for the whole pass, dict or Listing. Discarding each row immediately
# after it is re-encoded to bytes (never appending it to a long-lived list) is what actually
# cuts the ratio, to under half. This machine's own background load (verified with `top` before
# every trial: as little as ~100-150 MB physically free, 500 MB-4.5 GB of swap already in use,
# from the always-on background stack this box also runs) left too little headroom to safely
# run a 100,000+ row real-data trial this session; a larger trial, and a tighter ceiling, is a
# reasonable follow-up once that headroom exists.
#
# WHAT THE CEILING IS SET TO. Scaling BOARD_LOAD_MAX_SOURCE_MB's own margin (877 MB measured
# clean, 1,562 MB measured stressed, ceiling set to 1,200 MB) by the ~2.4x efficiency this ratio
# represents (roughly the midpoint of the two measured ratios above) gives a bit under 2,900 MB;
# 2,400 MB is used instead, deliberately short of that, as extra margin given the larger,
# real-board-scale trial above was NOT safe to run this session. The board's current combined
# source (2,643 MB) is STILL over this, honestly -- append_new_rows refuses on today's exact
# board too, same as load_board() -- but the gap is now small (2,400 vs 2,643 MB, 9% over)
# rather than load_board's (1,200 vs 2,643 MB, 120% over), and BOARD_APPEND_ALLOW_LARGE=1 is the
# deliberate override for a supervised run (plugged in, other apps closed) given the real,
# measured efficiency gain.
#
# RECONSIDERED 2026-09-30 (see BOARD_PATCH_MAX_SOURCE_MB's comment for the full writeup): three
# real, supervised, full-board-scale BOARD_APPEND_ALLOW_LARGE=1 runs landed overnight --
# 7d7fe05f (source 2,643 MB, peak RSS ~2.46 GiB, no footprint logged), e5922a1f (source 2,644 MB,
# peak footprint ~3.3 GiB, ratio ~1.28x), and 49ab8c1a (source ~2,653 MB est., peak footprint
# 4.2 GiB, ratio ~1.62x -- the worst observed). That worst ratio is BETTER (lower) than the 2.39x/
# 1.96x small-scale synthetic ratios this ceiling was originally derived from, which would argue
# for raising it; but 4,608 MB (a ~4.5 GiB footprint budget, chosen for the same reason
# BOARD_PATCH_MAX_SOURCE_MB's comment gives: real margin under the 5.9 GiB watchdog cap tonight's
# runs actually used) / 1.62 ~= 2,845 MB raw, and applying this file's own ~83% margin convention
# (2,400 / "under 2,900" from the original derivation) lands within a few percent of the CURRENT
# 2,400 MB value -- i.e. today's real data does not clearly justify moving this number either way,
# only three data points exist (all from one overnight session), and the board's current combined
# source (2,651 MB) is still safely close enough to today's exact ceiling that BOARD_APPEND_
# ALLOW_LARGE=1 stays required either way. Left at 2,400 MB rather than moved on marginal grounds.
BOARD_APPEND_MAX_SOURCE_MB = 2400.0

# --- the patch-only SIZE guard (follow-up to append_new_rows(), 2026-09-29) -----------------
# patch_existing_rows() (below) is a THIRD separate code path, alongside load_board() and
# append_new_rows(): like append_new_rows(), it never validates the existing board into
# Listing objects and never holds a full parsed-dict copy of it either -- each existing row is
# identity-checked (one dedupe_key() string, cheaper than append_new_rows()'s multi-signature
# set union), patched in place if it matches a pending patch, then popped (LAZY_DETAIL_KEYS out
# of raw), re-encoded to JSON bytes, and discarded immediately, one row at a time. It gets its
# OWN, separately-measured ceiling rather than assuming it inherits append_new_rows()'s: a
# structurally similar per-row shape is not proof of an identical cost, and BOARD_APPEND_MAX_
# SOURCE_MB's own history is that "obviously cheaper" assumptions have been wrong here before
# (skipping Listing.model_validate() ALONE barely helped there; the real win was never holding
# a full-length list of parsed rows at all, patched or not).
#
# MEASURED (2026-09-29), same method as BOARD_APPEND_MAX_SOURCE_MB's own trial: synthetic
# boards shaped like the real one (write_artifact() with Listing rows padded so combined
# per-row size lands close to the real board's own measured ~12.7 KB/row average -- deliberately
# NOT test_board_load_memory.py's _fat_lead()'s own padding, which measured ~35 KB/row here, too
# fat for a clean comparison; chosen so the trial does not need to touch the real 2.6+ GB
# production board to get a realistic per-row size), patched with ~1,200 pending patches
# (resolver_backfill_parcel.py's real per-checkpoint scale) against patch_existing_rows()'s real
# streaming code path, run as a monitored CHILD PROCESS and measured with BOTH signals the
# load_board() incident called for: RSS via a polling `ps -o rss=` watchdog, AND macOS's real
# physical footprint via `sample <pid> 1 -f <file>` (RSS alone undercounts compressed/swapped
# pages and was measured to look safe on load_board() while the real footprint reached 11.1 GB --
# see BOARD_LOAD_MAX_SOURCE_MB's comment):
#     20,000 rows, 312 MiB combined source -> RSS peak 549 MiB, footprint peak 746.5 MiB (2.39x)
#     40,000 rows, 625 MiB combined source -> RSS peak 1,083 MiB, footprint peak 1,433.6 MiB (2.29x)
# Directly comparable to BOARD_APPEND_MAX_SOURCE_MB's own two numbers at the SAME two scales
# (2.39x at 20,000 rows -- identical; 1.96x at 40,000 rows, i.e. append_new_rows() measured about
# 17% MORE footprint-efficient here): the two paths are close but not proven identical, which is
# exactly why this got its own trial instead of assuming equality. RSS again undercounted the
# real cost at this scale (549-1,083 MiB RSS vs 746-1,434 MiB footprint, a 1.3-1.4x gap) --
# smaller than load_board()'s catastrophic RSS/footprint gap, but the same DIRECTION of error, so
# still worth having measured both rather than trusting RSS alone.
#
# WHAT THE CEILING WAS ORIGINALLY SET TO (2026-09-29). Scaling BOARD_APPEND_MAX_SOURCE_MB's own
# 2,400 MB down by the ~17% relative efficiency gap measured at the 40,000-row (worse-case) point
# (2,400 / 1.17 ~= 2,051 MB) gives the raw number; 2,000 MB was used instead, a clean figure with
# real margin below that, deliberately conservative given the 20K/40K measurements did not fully
# agree with each other on how patch_existing_rows() compares to append_new_rows() (equal at 20K,
# ~17% worse at 40K) and a larger, real-board-scale trial was not run that session (same caution
# BOARD_APPEND_MAX_SOURCE_MB's own comment took).
#
# REAL FULL-BOARD PATCH ATTEMPTS, 2026-09-30 (overnight follow-up), CEILING RAISED A LITTLE, NOT
# REMOVED. Two real, supervised, full-board-scale patch_existing_rows() runs landed since the
# above was written, both under BOARD_PATCH_ALLOW_LARGE=1 with the dual RSS + `sample -f`
# physical-footprint watchdog this file's other ceilings require, both exiting clean (code 0, no
# manual kill):
#     adacbef5 (23:24): source 2,415 MB -> peak RSS 1.27 GiB, peak footprint 3,584.0 MB (1.484x)
#     fb30764f (02:12): source ~2,650 MB (board unchanged at 219,530 rows since 49ab8c1a) ->
#                        peak footprint ~4.0 GiB / 4,096 MiB (~1.546x), watchdog cap 5.9 GiB
# Two more same-night patch landings, 44d2becd (04:04) and d204cabb (04:59), also ran clean under
# BOARD_PATCH_ALLOW_LARGE=1 but did not log a paired source/footprint number in their commit
# messages, so they are NOT used as measurement data points here -- only the two above are.
# Worst real ratio measured (~1.546x, fb30764f) is BETTER (lower) than the 2026-09-29 small-scale
# synthetic trial's worse-case 17%-over-append assumption -- at real full-board scale,
# patch_existing_rows() is close to append_new_rows()'s own real worst ratio (1.62x, 49ab8c1a in
# BOARD_APPEND_MAX_SOURCE_MB's comment), not meaningfully worse the way the 40K-row synthetic
# trial predicted. That justifies raising this ceiling somewhat.
#
# It does NOT justify raising it to clear the current board outright, for two reasons. First,
# sample size: two real data points (vs. append's three), both from the SAME overnight session,
# is not enough to retire the margin discipline this file uses everywhere else. Second, and more
# important: BOARD_LOAD_MAX_SOURCE_MB's own 2026-09-29 real-full-board attempt is the direct
# precedent for what happens when a ceiling gets raised on the strength of a successful supervised
# run -- that attempt ALSO succeeded under its watchdog (RSS never exceeded ~1.1 GB) and the
# ceiling was STILL correctly left unraised, because the real physical footprint (11.1-11.3 GB,
# read via `sample -f`, not `ps`) told a completely different story than RSS did. The lesson there
# was not "load_board() is uniquely bad" -- it was that a size-based ceiling cannot see the
# machine's ACTUAL memory pressure at the moment a run starts, only its own file-size proxy for
# it, and this machine's real headroom fluctuates independently of board size: the successful
# adacbef5 patch run itself started at only 267-550 MB free / ~73.5% swap used, and a live check
# on 2026-09-30 while writing this comment showed conditions already WORSE than that (79 MB free,
# 84% of 5,120 MB swap used) with no patch process running at all -- just this machine's normal
# background stack. A higher static ceiling would not have made either moment safer; the watchdog
# and the human decision behind BOARD_PATCH_ALLOW_LARGE=1 are what actually kept every run above
# this ceiling safe tonight, not the ceiling's number, and that is the actual reason it stays
# required rather than being widened away.
#
# WHAT THE CEILING IS SET TO NOW. Applying the corrected ratio relationship (patch now measured
# ~4.6% cheaper than append's own worst real ratio, 1.546 vs 1.62, not 17% worse) to
# BOARD_APPEND_MAX_SOURCE_MB's 2,400 MB gives ~2,502 MB raw (2,400 * 1.62 / 1.546); 2,300 MB is
# used instead, short of that for the sample-size and headroom-volatility reasons above. The
# board's current combined source (2,651 MB, verified 2026-09-30) is STILL over this, deliberately
# -- BOARD_PATCH_ALLOW_LARGE=1 plus the dual RSS/footprint watchdog remains the required path for
# a run against the current (or any larger) board, exactly as before this comment was updated.
BOARD_PATCH_MAX_SOURCE_MB = 2300.0

# --- the merge-only SIZE guard (follow-up to patch_existing_rows(), 2026-09-30) --------------
# merge_duplicate_rows() (below) is a FOURTH separate code path: like append_new_rows() and
# patch_existing_rows(), it streams _iter_board_records() exactly once and never holds a full
# parsed-dict or Listing copy of the board. Per UNTOUCHED row (the overwhelming majority -- this
# function exists for a SMALL, known set of duplicate groups, not a board-wide pass) the cost is
# actually LOWER than patch_existing_rows()'s: patch computes a Listing.model_construct() +
# dedupe_key() for every single row to test for a match; merge instead computes
# row_identity_hash() (one sha256 over the row's already-serialized bytes -- the exact bytes
# this function needs to write out anyway, so the hash is close to free) and does a single dict
# lookup against the small `merge_groups` key set. Only rows that ARE part of a merge group (at
# most a few thousand, by this function's own contract -- "a SMALL, KNOWN set") pay
# Listing.model_validate() + Listing.merge()'s real cost, exactly the way append_new_rows() only
# pays Listing construction cost for its (also small) `new_listings` argument, never for the
# existing board it streams past.
#
# NOT INDEPENDENTLY MEASURED YET. Unlike BOARD_APPEND_MAX_SOURCE_MB and BOARD_PATCH_MAX_SOURCE_MB
# (both scaled from real `/usr/bin/time -l` trials, per-path, before being trusted -- see their
# own comments), this ceiling has had NO dedicated trial: this codebase's own history is that
# "structurally similar per-row shape is not proof of an identical cost" (BOARD_PATCH_MAX_SOURCE_MB's
# own comment, written after patch turned out NOT to simply inherit append's number). The
# per-row reasoning above argues merge_duplicate_rows() is at least as cheap as
# patch_existing_rows() for the untouched majority of rows, and cheaper by construction for the
# design chosen here (no Listing objects at all outside the tiny matched set) -- but that is an
# argument, not a measurement, and this file's own discipline is not to skip the measurement on
# the strength of an argument alone (see BOARD_PATCH_MAX_SOURCE_MB's "REAL FULL-BOARD PATCH
# ATTEMPTS" section for what happened the one time reasoning-by-analogy was trusted without
# updating the ceiling: it undersold the real risk once, at BOARD_LOAD_MAX_SOURCE_MB, before this
# file's discipline hardened around always measuring the ACTUAL path).
#
# WHAT THE CEILING IS SET TO. BOARD_PATCH_MAX_SOURCE_MB's own value (2,300 MB) is inherited
# UNCHANGED, not scaled up despite the argument above that merge should be cheaper -- deliberately
# conservative pending a real measured trial (same dual RSS + `sample -f` physical-footprint
# watchdog every other ceiling in this file was calibrated with). Raise this only after that
# trial, the same way BOARD_APPEND_MAX_SOURCE_MB and BOARD_PATCH_MAX_SOURCE_MB themselves were
# only raised after real supervised runs, never on reasoning alone.
BOARD_MERGE_MAX_SOURCE_MB = 2300.0

# The delete-only counterpart of BOARD_MERGE_MAX_SOURCE_MB, for delete_rows() (task_board_dedupe_
# stream, 2026-10-01): removing a SMALL, KNOWN set of rows by row_identity_hash() (no fold, no
# Listing.merge(), not even Listing.model_validate() for the dropped rows -- a match is simply
# never re-emitted) is at least as cheap per untouched row as merge_duplicate_rows(), which this
# inherits its ceiling from unchanged -- same "argument, not a measurement" caveat as
# BOARD_MERGE_MAX_SOURCE_MB's own comment: raise only after a real measured trial.
BOARD_DELETE_MAX_SOURCE_MB = 2300.0

# --- the prior-board MERGE guard, for board_persist.merge_prior_board() (2026-10-04) --------
# merge_prior_board() used to fold the full pipeline's fresh scrape into the published board by
# calling load_board() -- paying BOARD_LOAD_MAX_SOURCE_MB's own worst case (a full list[Listing]
# of the WHOLE board) -- and THEN running dedupe() over a doubled `fresh + prior` combined list
# on top of that. That second part is the "26.3 GB peak footprint, killed after 24 minutes" real
# full-board attempt BOARD_LOAD_MAX_SOURCE_MB's own comment describes: dedupe()'s bucket dict,
# zip/locale blocking indexes, `final` list and union-find `parent` array are all sized to the
# COMBINED (fresh+prior) row count, every one of them a full-length structure alive on top of
# the two full-length row lists (`prior`, `combined`) merge_prior_board() built to feed it. On
# the Oracle VM (2026-10-04), this chain's FIRST link -- load_board() -- raised BoardLoadTooLarge
# outright (board 2,668 MB source, against the Mac-calibrated 1,200 MB BOARD_LOAD_MAX_SOURCE_MB
# ceiling) before the run ever got far enough to find out whether the VM's 23 GB would have
# survived the rest of that chain anyway.
#
# THE FIX removes merge_prior_board()'s dependency on load_board()/dedupe() entirely: it streams
# _iter_board_records() once and matches each prior row against a SMALL index built from the
# fresh scrape only (new_listings-sized, not board-sized) -- the same _append_row_sigs()/
# _append_dict_sigs() signature trick append_new_rows() already uses and already has its own
# measured ceiling for (see BOARD_APPEND_MAX_SOURCE_MB's comment). A prior row is validated into
# a Listing ONLY when it is either part of that small matched set (to Listing.merge() to the
# fresh copy) or survives the aging check into the kept-prior-only set -- never for a row that
# gets aged out and dropped, and never twice for the same row. No `combined` list, no doubled
# `prior` list, no dedupe()'s full-board auxiliary structures exist at all.
#
# A deliberate, disclosed scope-narrowing: matching is via dedupe_key()/strong-signature equality
# only (append_new_rows()'s own "additive dedupe" level of fidelity), not dedupe()'s pass-2 fuzzy
# address scoring (rapidfuzz token_set_ratio >= 92 with no shared key/signature). A fresh/prior
# pair that would only have matched via that fuzzy pass now surfaces as two rows for one run (the
# fresh copy re-enriched from scratch, the prior copy aging down the SAME miss counter every
# other prior-only lead uses) instead of one carried-enrichment merge -- a quota-cost regression
# (re-grading a lead whose enrichment already existed), not a data-loss or safety one, and
# self-healing within BOARD_APPEND_... max_misses runs since the prior copy still ages out on
# schedule rather than accumulating as a permanent duplicate.
#
# WHAT THIS DOES NOT FIX. merge_prior_board()'s own CONTRACT -- unlike append_new_rows()/
# patch_existing_rows()/merge_duplicate_rows(), which stream straight to disk and never return
# more than a stats dict -- is to RETURN a full list[Listing] of the merged board (fresh + kept
# prior) to main.py's run(), which runs that list through ~2,400 more lines of enrichment/
# filtering before ITS OWN eventual write_artifact() call. That return value is still
# proportional to the FINAL kept-row count, the same way load_board()'s always was (see
# BOARD_LOAD_MAX_SOURCE_MB's comment: a plain list[dict] materialization measured almost as
# expensive as a list[Listing] one at the same scale -- the costly part is holding ANY
# full-length list of parsed rows alive for a sustained pass, not which type it holds). This fix
# removes the EXTRA multiplicative cost stacked on top of that one (load_board()'s own full
# materialization, a doubled combined list, and dedupe()'s full-board structures, all at once) --
# it does not make holding the final merged board's worth of Listing objects free.
#
# MEASURED (2026-10-04), on the Oracle VM (aarch64, 23 GiB RAM, 0 swap) against the REAL board
# (listings.json 2,550,229,241 bytes + listings_detail.json 247,715,947 bytes = 2,667.4 MiB
# combined source, 223,832 rows) under a supervised trial, polling BOTH /proc/<pid>/status:VmRSS
# and /proc/<pid>/smaps_rollup:Pss every ~1-2s (the Linux analog of this file's established
# "never trust RSS alone" dual-signal discipline -- see BOARD_LOAD_MAX_SOURCE_MB's comment for
# why the Mac side of that gap was real):
#     merge_prior_board(fresh=28,989 real stealth-handoff rows) against the real 223,832-row
#     prior board -> peak VmRSS 11,842.4 MiB, peak Pss 11,836.8 MiB, wall 125.1s, exit 0.
#     matched=16,723 fresh_only=12,266 prior_only_kept=205,808 aged_out=1,294 merged_count=234,797.
#     load_board() ALONE (the function this replaces), same board, same host, same watchdog,
#     BOARD_LOAD_ALLOW_LARGE=1 overridden for this one measurement run only -> peak VmRSS
#     11,739.4 MiB, peak Pss 11,734.2 MiB, wall 95.4s, exit 0, 223,832 rows.
#
# TWO REAL FINDINGS, not assumptions. First: unlike the Mac (BOARD_LOAD_MAX_SOURCE_MB's own
# 5.7x RSS/footprint gap from macOS's memory compressor), VmRSS and Pss track within 0.05% of
# each other on this Linux VM at this scale -- the compressed/swapped-pages blind spot that made
# RSS alone look safe on the Mac while the real footprint hit 11.1 GB does not reproduce here,
# at least not at this magnitude; RSS is a trustworthy proxy for the real cost on THIS host,
# though the dual-signal watchdog stays required (a single trial is not proof it never diverges).
# Second, and more important for what this ceiling should actually BE: merge_prior_board()'s
# measured peak (11,842 MiB, ratio ~4.44x the 2,667 MiB source) is essentially IDENTICAL to
# load_board()'s own (11,739 MiB, ~4.40x) -- not the half-or-less ratio append_new_rows()/
# patch_existing_rows()/merge_duplicate_rows() each earned their own more generous ceilings with.
# That is NOT this fix failing; it is this fix's own docstring's "WHAT THIS DOES NOT FIX" section
# confirmed empirically: merge_prior_board()'s OWN output is unavoidably a full list[Listing]
# proportional to the final row count, the same shape load_board()'s always was, so of course its
# per-source-MB cost lands in the same class. The real, measured win here is everything this
# number is NOT paying for anymore -- the doubled `fresh + prior` combined list and dedupe()'s
# full-board bucket/blocking/union-find structures BOARD_LOAD_MAX_SOURCE_MB's own "26.3 GB,
# killed" precedent describes for that chain -- which was never safe to re-measure at real-board
# scale on this run (it would risk exceeding this VM's own 23 GiB), so this ceiling is set the
# same way BOARD_LOAD_MAX_SOURCE_MB's was: a direct ratio match, not a discount.
#
# WHAT THE CEILING IS SET TO. Because this function's real measured cost class matches
# load_board()'s, not its cheaper streaming siblings', it gets load_board()'s OWN number, for the
# same reason BOARD_LOAD_MAX_SOURCE_MB itself was never raised after being measured safe-ish on
# this one VM trial: this ceiling has to stay safe on the SAME 8 GB Mac load_board() protects
# (merge_prior_board() runs there too, same board, same pipeline), and an 11+ GiB operation does
# not fit there regardless of what this one VM run showed. BOARD_PRIOR_MERGE_ALLOW_LARGE=1 is the
# deliberate, per-host override -- set in deploy/oracle/vm_run.sh (see its own comment) on the
# strength of today's real, supervised, successful trial on THIS host, exactly the way
# ASSESSOR_CARD_ON/ASSESSOR_CARD_MAX are already overridden there for the same "23 GiB VM, not an
# 8 GB Mac" reason. Left UNSET (refusing) everywhere else, including the Mac, until a Mac-scale
# trial says otherwise.
BOARD_PRIOR_MERGE_MAX_SOURCE_MB = 1200.0

# run_meta health older than this is nulled (audit O4).
HEALTH_MAX_AGE_HOURS = 48.0


class BoardLockBusy(RuntimeError):
    """Raised when another live board writer holds the lock."""

    def __init__(self, path: Path, pid: int | None, owner: str, detail: str = ""):
        self.path = Path(path)
        self.pid = pid
        self.owner = owner
        super().__init__(
            f"board lock {path} is held by pid {pid} ({owner or 'unknown owner'})"
            + (f"; {detail}" if detail else "")
        )


class BoardLockNotHeld(RuntimeError):
    """write_artifact refused: the caller does not hold the board lock (audit O3)."""


class BoardLockLost(BoardLockNotHeld):
    """The lock this process inherited was broken as stale and re-taken."""


class BoardMemoryPressure(RuntimeError):
    """The memory gate refused to start a board writer (audit O9)."""


class BoardLoadTooLarge(RuntimeError):
    """read_board_records()/load_board() refused: the on-disk board is bigger than
    this machine can safely fully materialize (audit O13, 2026-09-29).

    WHY THIS EXISTS. board_memory_gate() (audit O9, just above) only samples
    CURRENT swap/free RAM once, at board_lock() entry, before the expensive load
    even starts -- it says nothing about whether the load about to happen will
    fit. A `run_scoped_scrapers.py --apply` run on 2026-09-29 passed that gate
    fine (the 8 GB Mac had headroom at lock time) and then load_board() alone --
    plain json.load of docs/listings.json (217,773 rows, 2.52 GB, up from the
    ~1.1 GB / 170k rows this codebase's comments and thresholds were written
    against) PLUS a full separate Listing.model_validate() pass, both held in
    memory at once -- ran for 24 minutes, reached a 26.3 GB physical footprint
    and was still climbing when killed; a bounded re-run of load_board() alone
    against the same real board (no scraper involved) reproduced the same
    signature: RSS oscillating under 1.1 GB in a GC-thrashing sawtooth, never
    completing in 240s. See docs/HANDOFF.md / the 2026-09-29 apply-runaway note.

    UPDATE, SAME DAY: the double-materialization this describes (full parsed
    JSON tree ALONGSIDE a full separate Listing graph) is fixed -- see
    _iter_board_records's docstring -- so a load that gets past this guard now
    completes deterministically instead of GC-thrashing. This guard still
    exists and still fires on the full board, but for a narrower, now-measured
    reason: read_board_records()'s/load_board()'s contract is a full, mutable
    board, so peak memory is still proportional to row count even with the
    parsing streamed, and the current board's row count has been measured (by
    extrapolation from real, safely-sized trials) to likely need more memory
    than this 8 GB Mac can safely give up. See BOARD_LOAD_MAX_SOURCE_MB's
    comment for the real numbers this ceiling is based on.

    This is a SIZE check, not a memory-pressure check: it fires even on an idle
    machine with RAM to spare, because the operation itself does not scale to
    the board's current size yet, not because anything is currently busy.
    BOARD_LOAD_ALLOW_LARGE=1 overrides it for one run; BOARD_LOAD_MAX_SOURCE_MB
    raises (or lowers) the ceiling."""


def board_lock_dir(root: Path | str | None = None) -> Path:
    """The one lock path. Under logs/ because logs/ is gitignored — a lock that
    shows up in `git status` ends up in somebody's `git add -A`."""
    if root is None:
        root = Path(__file__).resolve().parents[2]
    return Path(root) / BOARD_LOCK_SUBDIR / BOARD_LOCK_DIRNAME


def _bl_int(s: str | None) -> int | None:
    try:
        return int(str(s).strip())
    except (TypeError, ValueError):
        return None


def _bl_info(d: Path) -> dict:
    """Everything the pid file says. Lines: pid, owner, start epoch, heartbeat
    epoch, max runtime seconds, token. A legacy lock has only the first two; its
    start time falls back to the pid file's mtime."""
    info: dict = {"pid": None, "owner": "", "start": None, "heartbeat": None,
                  "max_runtime": None, "token": ""}
    pf = d / BOARD_LOCK_PID_FILE
    try:
        lines = pf.read_text().splitlines()
    except OSError:
        return info
    if lines:
        info["pid"] = _bl_int(lines[0])
    if len(lines) > 1:
        info["owner"] = lines[1].strip()
    if len(lines) > 2:
        info["start"] = _bl_int(lines[2])
    if len(lines) > 3:
        info["heartbeat"] = _bl_int(lines[3])
    if len(lines) > 4:
        info["max_runtime"] = _bl_int(lines[4])
    if len(lines) > 5:
        info["token"] = lines[5].strip()
    if info["start"] is None:
        try:
            info["start"] = int(pf.stat().st_mtime)
        except OSError:
            pass
    return info


def _bl_owner(d: Path) -> tuple[int | None, str]:
    info = _bl_info(d)
    return info["pid"], info["owner"]


def _bl_write_info(d: Path, pid: int, owner: str, start: int, heartbeat: int,
                   max_runtime: int, token: str) -> None:
    """Atomic rewrite (temp + rename) so a reader never sees half a line set."""
    pf = d / BOARD_LOCK_PID_FILE
    tmp = d / f"{BOARD_LOCK_PID_FILE}.{os.getpid()}.tmp"
    tmp.write_text(f"{pid}\n{owner}\n{start}\n{heartbeat}\n{max_runtime}\n{token}\n")
    os.replace(tmp, pf)


def _bl_alive(pid: int | None) -> bool:
    """kill(pid, 0). EPERM means alive-but-not-ours, which still counts."""
    if not pid or pid <= 0:
        return False
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except OSError:
        return True
    return True


def _bl_children(d: Path) -> list[int]:
    """PIDs registered as running INSIDE this lock (child writers). Dead ones are
    pruned as a side effect."""
    out: list[int] = []
    cd = d / BOARD_LOCK_CHILDREN_DIR
    try:
        entries = list(cd.iterdir())
    except OSError:
        return out
    for e in entries:
        pid = _bl_int(e.name)
        if pid is None:
            continue
        if _bl_alive(pid):
            out.append(pid)
        else:
            try:
                e.unlink()
            except OSError:
                pass
    return out


_CHILD_REGISTERED: set = set()


def _bl_register_child(d: Path, label: str = "") -> bool:
    """Record THIS process as a live holder inside the lock (audit O11).

    The lock's owner is the wrapper's PID. If the wrapper is killed but its Python
    child survives (pkill of the shell, a closed terminal) the lock looked stale
    and the next job broke it while the child was still writing the board. A
    registered child keeps the lock alive for as long as it lives."""
    try:
        cd = d / BOARD_LOCK_CHILDREN_DIR
        if not d.is_dir():
            return False
        cd.mkdir(exist_ok=True)
        (cd / str(os.getpid())).write_text(label or Path(sys.argv[0] or "python").name)
        if d not in _CHILD_REGISTERED:
            import atexit
            _CHILD_REGISTERED.add(d)
            # A pid file left behind by a finished child could match a RECYCLED pid
            # and keep a dead lock looking alive, so remove it at exit.
            atexit.register(_bl_unregister_child, d)
        return True
    except OSError:
        return False


def _bl_unregister_child(d: Path) -> None:
    try:
        (d / BOARD_LOCK_CHILDREN_DIR / str(os.getpid())).unlink()
    except OSError:
        pass


def _bl_stale_reason(d: Path, now: float | None = None) -> str | None:
    """None when the lock is healthy, else why it should be broken:

      dead_owner  the owner PID and every registered child are gone
      expired     a LIVE holder is older than its max runtime + 30 minutes
                  (a hung holder with a live PID used to block every other job
                  forever; a recycled PID made a dead lock look alive)
      unreadable  no readable pid file
    """
    info = _bl_info(d)
    if info["pid"] is None:
        return "unreadable"
    alive = _bl_alive(info["pid"]) or bool(_bl_children(d))
    if not alive:
        return "dead_owner"
    now = now if now is not None else time.time()
    start = info["start"]
    if start is not None:
        limit = (info["max_runtime"] or BOARD_LOCK_DEFAULT_MAX_RUNTIME) + BOARD_LOCK_STALE_GRACE
        if now - start > limit:
            return "expired"
    return None


def board_lock_describe(d: Path, now: float | None = None) -> str:
    info = _bl_info(d)
    now = now if now is not None else time.time()
    bits = []
    if info["start"]:
        bits.append(f"held {int((now - info['start']) / 60)} min")
    if info["heartbeat"]:
        bits.append(f"heartbeat {int(now - info['heartbeat'])}s ago")
    if info["max_runtime"]:
        bits.append(f"max runtime {int(info['max_runtime'] / 60)} min")
    kids = _bl_children(d)
    if kids:
        bits.append(f"children {kids}")
    return ", ".join(bits)


def _bl_break(d: Path, expect_pid: int | None, force: bool = False) -> bool:
    """Remove a stale lock. Exactly one racer can win the rename. `force` is for
    an EXPIRED lock, whose owner is legitimately still alive."""
    victim = d.with_name(f"{d.name}.stale.{os.getpid()}")
    shutil.rmtree(victim, ignore_errors=True)
    try:
        os.rename(d, victim)
    except OSError:
        return False          # somebody else broke it, or it went away
    pid, _owner = _bl_owner(victim)
    if not force and pid is not None and pid != expect_pid and _bl_alive(pid):
        # A live writer claimed the lock in the gap between our staleness
        # verdict and the rename. Put it back and lose the race honestly.
        try:
            os.rename(victim, d)
            return False
        except OSError:
            pass
    shutil.rmtree(victim, ignore_errors=True)
    return True


def _bl_try_mkdir(d: Path, owner: str, max_runtime: int | None = None,
                  token: str = "") -> bool:
    try:
        d.mkdir(parents=True)
    except FileExistsError:
        return False
    now = int(time.time())
    _bl_write_info(d, os.getpid(), owner, now, now,
                   int(max_runtime or BOARD_LOCK_DEFAULT_MAX_RUNTIME), token)
    return True


def _bl_event(event: str, root: Path | str | None = None, **fields) -> None:
    """A lock break, skip or gate wait goes to logs/job_events.jsonl so a watcher
    can count them. Never raises."""
    try:
        from . import job_events
        job_events.note(event, root=root, **fields)
    except Exception:  # noqa: BLE001
        pass


class _Heartbeat:
    """Daemon thread that re-stamps the lock's heartbeat line while we hold it.

    Diagnostic, NOT a staleness criterion: json.loads / json.dumps on a 1.1 GB
    board hold the GIL for a long time on a thrashing 8 GB Mac, so a quiet
    heartbeat is not proof of a dead holder and breaking a live writer's lock
    would put two writers on the board."""

    def __init__(self, d: Path, owner: str, start: int, max_runtime: int, token: str,
                 interval: float):
        import threading
        self._d, self._owner, self._start = d, owner, start
        self._max, self._token, self._interval = max_runtime, token, interval
        self._stop = threading.Event()
        self._t = threading.Thread(target=self._run, name="board-lock-heartbeat", daemon=True)

    def start(self) -> None:
        self._t.start()

    def stop(self) -> None:
        self._stop.set()

    def _run(self) -> None:
        while not self._stop.wait(self._interval):
            try:
                info = _bl_info(self._d)
                if info["token"] != self._token or info["pid"] != os.getpid():
                    return          # we no longer own it
                _bl_write_info(self._d, os.getpid(), self._owner, self._start,
                               int(time.time()), self._max, self._token)
            except Exception:  # noqa: BLE001
                return


def board_memory_state() -> dict:
    """swap used and free+inactive, in MB, plus whether the gate would pass.

    Test hooks BOARD_GATE_FAKE_SWAP_MB / BOARD_GATE_FAKE_FREE_MB stand in for the
    machine. Unknown (non-macOS, command failure) reads as healthy."""
    swap_mb: float | None = None
    free_mb: float | None = None
    fs, ff = os.environ.get("BOARD_GATE_FAKE_SWAP_MB"), os.environ.get("BOARD_GATE_FAKE_FREE_MB")
    if fs is not None or ff is not None:
        swap_mb = float(fs) if fs not in (None, "") else 0.0
        free_mb = float(ff) if ff not in (None, "") else 1e9
    else:
        import subprocess
        try:
            out = subprocess.run(["sysctl", "-n", "vm.swapusage"], capture_output=True,
                                 text=True, timeout=5).stdout
            m = re.search(r"used = ([0-9.]+)M", out)
            swap_mb = float(m.group(1)) if m else None
        except Exception:  # noqa: BLE001
            swap_mb = None
        try:
            out = subprocess.run(["vm_stat"], capture_output=True, text=True, timeout=5).stdout
            ps = re.search(r"page size of (\d+) bytes", out)
            psz = int(ps.group(1)) if ps else 16384
            pages = 0
            for label in ("Pages free", "Pages inactive"):
                mm = re.search(rf"^{label}:\s+(\d+)", out, re.M)
                pages += int(mm.group(1)) if mm else 0
            free_mb = pages * psz / (1024 * 1024)
        except Exception:  # noqa: BLE001
            free_mb = None
    max_swap = float(os.environ.get("BOARD_GATE_SWAP_MB", BOARD_GATE_SWAP_MB))
    min_free = float(os.environ.get("BOARD_GATE_FREE_MB", BOARD_GATE_FREE_MB))
    reasons = []
    if swap_mb is not None and swap_mb > max_swap:
        reasons.append(f"swap_used_mb={swap_mb:.0f}>{max_swap:.0f}")
    if free_mb is not None and free_mb < min_free:
        reasons.append(f"free_plus_inactive_mb={free_mb:.0f}<{min_free:.0f}")
    return {"swap_mb": swap_mb, "free_mb": free_mb, "ok": not reasons,
            "reason": ",".join(reasons)}


def board_memory_gate(owner: str = "", mode: str | None = None,
                      wait: float | None = None, poll: float = 30.0,
                      root: Path | str | None = None) -> dict:
    """Wait or refuse when the machine is thrashing. Raises BoardMemoryPressure in
    enforce mode once `wait` seconds have passed without the pressure clearing.
    Every wait, refusal and warn-and-go is written to logs/job_events.jsonl."""
    mode = (mode or os.environ.get("BOARD_MEM_GATE") or "warn").strip().lower()
    if mode == "off":
        return {"ok": True, "mode": "off"}
    wait_s = float(wait if wait is not None else os.environ.get("BOARD_MEM_GATE_WAIT", 900))
    t0 = time.monotonic()
    state = board_memory_state()
    waited = False
    while not state["ok"]:
        if mode == "warn":
            _bl_event("mem_gate", root=root, owner=owner, mode="warn", action="proceed",
                      reason=state["reason"])
            log.warning("board_lock.memory_pressure", owner=owner, reason=state["reason"])
            return {**state, "mode": mode}
        if time.monotonic() - t0 >= wait_s:
            _bl_event("mem_gate", root=root, owner=owner, mode=mode, action="refused",
                      reason=state["reason"], waited_s=int(time.monotonic() - t0))
            raise BoardMemoryPressure(
                f"memory gate refused {owner or 'board writer'}: {state['reason']} "
                f"after {int(time.monotonic() - t0)}s (BOARD_MEM_GATE=warn overrides)")
        if not waited:
            waited = True
            _bl_event("mem_gate", root=root, owner=owner, mode=mode, action="waiting",
                      reason=state["reason"])
        time.sleep(max(0.05, min(poll, wait_s - (time.monotonic() - t0))))
        state = board_memory_state()
    if waited:
        _bl_event("mem_gate", root=root, owner=owner, mode=mode, action="cleared",
                  waited_s=int(time.monotonic() - t0))
    return {**state, "mode": mode}


@contextmanager
def board_lock(root: Path | str | None = None, owner: str = "",
               wait: float = 0.0, poll: float = 5.0,
               max_runtime: float | None = None):
    """Hold the board-writer lock for the WHOLE load -> mutate -> write span.

        with board_lock(owner="patch_vision_gemini"):
            listings = load_board(DOCS)
            ...
            write_artifact(listings, summary, docs_dir=DOCS)

    Raises BoardLockBusy when another live writer holds the lock and `wait` seconds
    have elapsed (default: do not wait at all — a scheduled pass that collides
    should skip today, not queue up behind a four-hour vision job).

    A lock left behind by a dead process is broken automatically; if it were
    not, one killed run would stop every scheduled job forever. A lock held by a
    LIVE process past `max_runtime` + 30 minutes (default 6 h) is broken too and
    the break is logged: the hung holder is then fenced out of write_artifact by
    the lock token. Pass a larger `max_runtime` for a job that legitimately runs
    longer.
    """
    d = board_lock_dir(root)
    if os.environ.get(BOARD_LOCK_ENV) == str(d):
        # An ancestor in this process tree already holds it. Register as a live
        # holder so the lock outlives a killed wrapper, and refuse to proceed if
        # the lock this process inherited has since been broken and re-taken.
        tok = os.environ.get(BOARD_LOCK_TOKEN_ENV)
        if tok and _bl_info(d)["token"] != tok:
            raise BoardLockLost(
                f"the board lock {d} this process inherited was broken as stale "
                f"and is now held by someone else; refusing to proceed")
        _bl_register_child(d, owner)
        try:
            yield d
        finally:
            _bl_unregister_child(d)
        return
    owner = owner or Path(sys.argv[0] or "python").name or "python"
    d.parent.mkdir(parents=True, exist_ok=True)
    _root = d.parent.parent
    board_memory_gate(owner, root=_root)
    deadline = time.monotonic() + max(0.0, wait)
    token = uuid.uuid4().hex
    maxrt = int(max_runtime or os.environ.get("BOARD_LOCK_MAX_RUNTIME")
                or BOARD_LOCK_DEFAULT_MAX_RUNTIME)
    while True:
        if _bl_try_mkdir(d, owner, maxrt, token):
            break
        info = _bl_info(d)
        if info["pid"] is None:
            time.sleep(BOARD_LOCK_PID_GRACE)
            info = _bl_info(d)
        pid, holder = info["pid"], info["owner"]
        reason = _bl_stale_reason(d)
        if reason:
            log.warning("board_lock.stale_break", path=str(d), reason=reason,
                        dead_pid=pid, prior_owner=holder)
            _bl_event("lock_break", root=_root, owner=owner, prior_owner=holder, prior_pid=pid,
                      reason=reason, detail=board_lock_describe(d))
            if _bl_break(d, pid, force=(reason == "expired")):
                continue
        if time.monotonic() >= deadline:
            _bl_event("lock_skip", root=_root, owner=owner, holder=holder, holder_pid=pid,
                      detail=board_lock_describe(d))
            raise BoardLockBusy(d, pid, holder, board_lock_describe(d))
        time.sleep(max(0.1, poll))
    prior = os.environ.get(BOARD_LOCK_ENV)
    prior_tok = os.environ.get(BOARD_LOCK_TOKEN_ENV)
    os.environ[BOARD_LOCK_ENV] = str(d)
    os.environ[BOARD_LOCK_TOKEN_ENV] = token
    hb = _Heartbeat(d, owner, int(time.time()), maxrt, token,
                    float(os.environ.get("BOARD_LOCK_HEARTBEAT_S", BOARD_LOCK_HEARTBEAT_SECONDS)))
    hb.start()
    try:
        yield d
    finally:
        hb.stop()
        for env, was in ((BOARD_LOCK_ENV, prior), (BOARD_LOCK_TOKEN_ENV, prior_tok)):
            if was is None:
                os.environ.pop(env, None)
            else:
                os.environ[env] = was
        # Only remove the lock if it is still OURS: an expired lock that another
        # job broke and re-took must not be deleted out from under it.
        if _bl_info(d)["token"] == token:
            shutil.rmtree(d, ignore_errors=True)


def _live_docs_dir() -> Path:
    """The board this repo publishes. Split out so tests can point it at a tmp dir."""
    return Path(__file__).resolve().parents[2] / "docs"


def _repo_lock_dir() -> Path:
    """This repo's lock directory, derived from the live docs dir (so a test that points
    _live_docs_dir at a scratch tree moves the lock with it)."""
    return board_lock_dir(_live_docs_dir().parent)


def require_board_lock(docs: Path | str) -> None:
    """Refuse to write the live board unless the caller holds the board lock
    (audit O3). The lock was advisory: 54 board-writing modules never took it, and
    write_artifact() itself never looked. Now it looks.

    Passes when ANY of:
      * BOARD_LOCK_BYPASS=1 (explicit, for tests and one-off tools; logged)
      * `docs` is not the live docs directory (a scratch board shares nothing)
      * FORECLOSURE_BOARD_LOCK_HELD names this repo's lock AND, when the holder
        exported a token, the lock on disk still carries that token.
    """
    if os.environ.get(BOARD_LOCK_BYPASS_ENV, "").strip().lower() in ("1", "true", "yes"):
        log.warning("web_artifact.lock_bypass", docs=str(docs))
        return
    try:
        if Path(docs).resolve() != _live_docs_dir().resolve():
            return
    except OSError:
        pass
    d = _repo_lock_dir()
    if os.environ.get(BOARD_LOCK_ENV) != str(d):
        raise BoardLockNotHeld(
            "write_artifact refused: this process does not hold the board lock "
            f"({d}). A board writer that does not hold it can be silently reverted by, "
            "or silently revert, the scheduled jobs (the 2026-08-10 incident). "
            "Run it under the lock:  scripts/with_board_lock.sh <owner> -- <command>  "
            "or wrap the load_board -> write_artifact span in "
            "`with board_lock(owner=...)`. Tests and one-off tools may set "
            "BOARD_LOCK_BYPASS=1."
        )
    tok = os.environ.get(BOARD_LOCK_TOKEN_ENV)
    if tok:
        on_disk = _bl_info(d)["token"]
        if on_disk != tok:
            raise BoardLockLost(
                "write_artifact refused: the board lock was broken as stale (or "
                "released) and is no longer this process's. Another job may be writing. "
                f"lock={d} on_disk_token={'present' if on_disk else 'missing'}"
            )
    else:
        log.warning("web_artifact.lock_legacy_holder", lock=str(d),
                    note="holder exported no token; ownership not verifiable")
    _bl_register_child(d)


# ===========================================================================
# THE BOARD MANIFEST + LOAD INTEGRITY (audit O3)
#
# write_artifact writes six payload families one after another, each atomically
# but not as a SET. A kill, a full disk or an OOM between two of them leaves a
# mixed set (listings.json from write N, listings_detail.json from write N-1)
# that loads without an error: detail[i] is joined to listing[i] BY INDEX, so
# every lead carries a neighbour's comps and vision, run_meta looks normal and
# the count guard passes. The 2026-09-17 disk-full and the unexplained vision
# deaths are exactly that window.
#
# docs/board.manifest.json is written LAST, after every payload file, and names
# the size, sha256 and record count of each. load_board / read_board_json verify
# the file they are about to read against it, and REFUSE the "plain .json beats
# its .gz twin" preference when the plain file disagrees with the manifest.
#
# Escape hatches, because a fail-closed reader with no way out is an outage:
#   BOARD_MANIFEST_SKIP=1   do not verify (one-off recovery only)
#   scripts/board_manifest.py --rebuild   re-derive the manifest from disk
# ===========================================================================

MANIFEST_NAME = "board.manifest.json"
MANIFEST_SCHEMA = "board-manifest-v1"


class BoardLoadDropError(RuntimeError):
    """load_board dropped more rows than BOARD_LOAD_MAX_DROP_RATE allows."""


class BoardChangedSinceLoad(RuntimeError):
    """write_artifact refused: listings.json changed after this process loaded it."""


def _sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        while True:
            chunk = fh.read(8 * 1024 * 1024)
            if not chunk:
                break
            h.update(chunk)
    return h.hexdigest()


def load_manifest(docs: Path | str) -> dict | None:
    """The parsed manifest, or None when absent/unreadable/unknown schema."""
    if os.environ.get("BOARD_MANIFEST_SKIP", "").strip().lower() in ("1", "true", "yes"):
        return None
    mp = Path(docs) / MANIFEST_NAME
    try:
        m = json.loads(mp.read_text())
    except (OSError, ValueError):
        return None
    if not isinstance(m, dict) or m.get("schema") != MANIFEST_SCHEMA:
        return None
    if not isinstance(m.get("files"), dict):
        return None
    return m


# (resolved path, mtime_ns, size, sha) -> True once its sha256 matched the
# manifest. The same 1.1 GB file is read more than once per process (load, then
# the prior sidecar read inside write_artifact); hash it once.
_VERIFIED: dict = {}


def _file_matches_manifest(path: Path, entry: dict) -> tuple[bool, str]:
    try:
        st = path.stat()
    except OSError:
        return False, "missing"
    if entry.get("bytes") is not None and st.st_size != entry["bytes"]:
        return False, f"size {st.st_size} != manifest {entry['bytes']}"
    key = (str(path.resolve()), st.st_mtime_ns, st.st_size, entry.get("sha256"))
    if key in _VERIFIED:
        return True, ""
    want = entry.get("sha256")
    if want:
        got = _sha256_file(path)
        if got != want:
            return False, f"sha256 {got[:12]} != manifest {want[:12]}"
    _VERIFIED[key] = True
    return True, ""


def plain_board_row_count(path: Path | str) -> int | None:
    """Number of rows in a plain JSON-array board file (docs/listings.json), WITHOUT holding it.

    The sealed manifest's record count is used when the manifest's sha256 for this exact file
    matches (hashing is cached per process by _file_matches_manifest, and write_artifact re-reads
    the same file anyway); otherwise the rows are streamed and counted one at a time. Returns
    None when the file is absent. Raises on a malformed file, like the json.loads it replaces.

    Why: main.py's count-drop guard used json.loads(path.read_text()) only to take len() of the
    result -- the full 2.5 GB text plus every parsed row, on top of ~270K live Listings, a minute
    before write_artifact (the 2026-10-05 VM OOM, see write_artifact's MEMORY note)."""
    path = Path(path)
    if not path.is_file():
        return None
    man = load_manifest(path.parent)
    ent = (man or {}).get("files", {}).get(path.name) if man else None
    if isinstance(ent, dict) and isinstance(ent.get("records"), int):
        ok, _why = _file_matches_manifest(path, ent)
        if ok:
            return ent["records"]
    n = 0
    for _row in _bp.iter_plain_rows(path):
        n += 1
    return n


def _choose_listings_source(p: Path):
    """Source selection for docs/listings.json specifically, now that the published board is
    a set of PARTS (audit O1). Returns (path, role, resolution) or None to fall through to the
    legacy single-gz rules.

      manifest with a parts block   the plain file when it matches the manifest, else the parts
                                    (every part verified against the manifest; any mismatch is a
                                    BoardIntegrityError, an interrupted write is never read)
      manifest WITHOUT a parts block  legacy: None (the single .gz rules apply)
      no manifest                   plain if present, else the parts found on disk (contiguous
                                    from 000, unverified), else None
    """
    docs = p.parent
    man = load_manifest(docs)
    if man is not None:
        if _bp.manifest_parts_block(man) is None:
            return None
        entry_plain = man["files"].get(p.name)
        plain_why = "missing"
        if p.exists():
            plain_why = "not named by the manifest"
            if entry_plain:
                plain_ok, plain_why = _file_matches_manifest(p, entry_plain)
                if plain_ok:
                    return p, "plain", None
        try:
            res = _bp.resolve(docs, man=man)
        except BoardIntegrityError as exc:
            raise BoardIntegrityError(
                f"{p.name} does not match {MANIFEST_NAME} (plain: {plain_why}). {exc}") from exc
        if p.exists():
            log.error("board.plain_disagrees_with_manifest", file=p.name, why=plain_why,
                      using=res.paths[0].name + " (+ %d more parts)" % (len(res.paths) - 1))
        return res.paths[0], "parts", res
    if p.exists():
        return p, "plain", None
    try:
        res = _bp.resolve(docs)
    except _bp.UnlistedPartsError:
        # part files nobody lists (an interrupted first write, a migration mid-flight): the
        # single listings.json.gz, when there is one, is still a complete board. Otherwise refuse.
        if p.with_name(p.name + ".gz").exists():
            return None
        raise
    if res is not None:
        return res.paths[0], "parts", res
    return None


def _choose_board_source(p: Path):
    """(path, role, resolution) for `p` (docs/listings.json or a sibling). role is "plain",
    "gz" or "parts"; resolution is set only for "parts". Honors the manifest when it names the
    file; otherwise the legacy rule (plain if present, else its .gz)."""
    if p.name == "listings.json":
        got = _choose_listings_source(p)
        if got is not None:
            return got
    gz = p.with_name(p.name + ".gz")
    man = load_manifest(p.parent)
    entry_plain = man["files"].get(p.name) if man else None
    if not entry_plain:
        if p.exists():
            return p, "plain", None
        if gz.exists():
            return gz, "gz", None
        raise FileNotFoundError(f"{p} (and {p.name}.gz"
                                + (" or its listings_part_NNN.json.gz parts" if p.name == "listings.json" else "")
                                + ") not found")
    entry_gz = man["files"].get(gz.name)
    plain_ok, plain_why = (False, "missing")
    if p.exists():
        plain_ok, plain_why = _file_matches_manifest(p, entry_plain)
    if plain_ok:
        return p, "plain", None
    gz_ok, gz_why = (False, "missing")
    if gz.exists() and entry_gz:
        gz_ok, gz_why = _file_matches_manifest(gz, entry_gz)
    if gz_ok:
        if p.exists():
            log.error("board.plain_disagrees_with_manifest", file=p.name, why=plain_why,
                      using=gz.name)
        return gz, "gz", None
    raise BoardIntegrityError(
        f"{p.name} does not match {MANIFEST_NAME} (plain: {plain_why}; "
        f"gz: {gz_why}). The payload set is torn or mixed. Restore a consistent set "
        f"(scripts/restore_board.sh <commit>) or, if you know the files are right, "
        f"scripts/board_manifest.py --rebuild. BOARD_MANIFEST_SKIP=1 bypasses this check."
    )


def _choose_board_file(p: Path) -> tuple[Path, str]:
    """Which file to read for `p`, plus its role (kept for callers that predate the parts)."""
    used, role, _ = _choose_board_source(p)
    return used, role


# {resolved listings.json path: (file actually read, st_mtime_ns, st_size)} —
# what THIS process saw when it loaded the board. write_artifact compares it.
_LOAD_STAMPS: dict = {}


def _stamp_of(path: Path) -> tuple[int, int] | None:
    try:
        st = path.stat()
    except OSError:
        return None
    return (st.st_mtime_ns, st.st_size)


def _remember_load(docs: Path, used: Path) -> None:
    st = _stamp_of(used)
    if st is not None:
        _LOAD_STAMPS[str(docs.resolve() / "listings.json")] = (str(used), st[0], st[1])


def _bypass_on() -> bool:
    return os.environ.get(BOARD_LOCK_BYPASS_ENV, "").strip().lower() in ("1", "true", "yes")


def _check_not_changed_since_load(listings_path: Path) -> None:
    """Abort when listings.json is not the file this process loaded (audit O3).

    Only checked for a process that actually called load_board / read_board_records
    (a full re-scrape that never loaded has nothing to compare), and only when what it
    read was the PLAIN listings.json. It is NOT checked when load_board read the .gz twin
    (a fresh clone, a CI job, a restore, a gz-only rewrite) or when the rows came from a
    different docs directory: stamps are keyed by the docs dir that was loaded, and a .gz
    read is exactly the flow whose plain twin the writer is about to (re)create, so there
    is no "the file I loaded" to compare against. Bypassed by BOARD_LOCK_BYPASS, like the
    lock check."""
    if _bypass_on():
        return
    stamp = _LOAD_STAMPS.get(str(listings_path.resolve()))
    if not stamp:
        return
    used, mt, size = stamp
    if str(used).endswith(".gz"):
        return
    now = _stamp_of(Path(used))
    if now != (mt, size):
        raise BoardChangedSinceLoad(
            f"write_artifact refused: {used} changed since this process loaded it "
            f"(loaded mtime_ns={mt} size={size}; now {now}). Another writer replaced the "
            f"board while this one worked on a stale copy; writing now would silently "
            f"revert it. Re-run from a fresh load."
        )


def _read_board_json_ex(path: Path | str):
    p = Path(path)
    used, role, res = _choose_board_source(p)
    if role == "plain":
        return json.loads(used.read_text()), used
    if role == "parts":
        # concatenated in name order; every part already verified against the manifest
        return _bp.read_rows(p.parent, res=res), used
    import gzip as _gzip
    return json.loads(_gzip.decompress(used.read_bytes()).decode("utf-8")), used


def _open_board_source_rows(p: Path) -> tuple[Path, Iterator[dict]]:
    """(file actually read, streaming row iterator) for a board JSON file -- the same source
    selection _read_board_json_ex uses (honors the manifest, parts vs. gz vs. plain), except
    the rows are handed back one at a time instead of as one fully parsed list (audit O13's
    real fix, 2026-09-29, see _iter_board_records below). The path is resolved and returned
    immediately (a plain function call); the iterator itself does no work until consumed."""
    used, role, res = _choose_board_source(p)
    if role == "parts":
        return used, _bp.iter_rows(p.parent, res=res)
    if role == "gz":
        return used, _bp.iter_gz_rows(used)
    return used, _bp.iter_plain_rows(used)


def read_board_json(path: Path | str):
    """Read a board JSON file, transparently falling back to its ``.gz`` twin.

    The uncompressed docs/listings.json (~1.1GB now) is NOT committed to git — it
    exceeds GitHub's 100MB/file limit, and the dashboard only ever loads the
    gzipped copy. The local runner regenerates the plain .json every write, so on
    that machine this reads the plain file directly. Everywhere else (a fresh
    clone, a cloud CI/patch job, disaster recovery) only the committed .gz exists,
    so we decompress that instead. Either way the whole system can rebuild the
    board from just the .gz — nothing depends on the big file being present.

    For listings.json the "twin" is the PARTS board (docs/listings_part_NNN.json.gz, audit
    O1): the parts are verified against the manifest, concatenated in order, and returned as
    the same list the single file used to hold. See board_parts.py.

    When docs/board.manifest.json exists it is authoritative: the file is verified
    against it first, and the plain-over-gz preference is refused when the plain
    file disagrees (see THE BOARD MANIFEST above).
    """
    return _read_board_json_ex(path)[0]


def _board_file_present(path: Path) -> bool:
    """True when a board file exists as either the plain .json or its .gz twin.

    The presence test that pairs with read_board_json. `path.exists()` alone is
    the wrong question anywhere the uncompressed twin is gitignored.
    """
    p = Path(path)
    if p.exists() or p.with_name(p.name + ".gz").exists():
        return True
    return p.name == "listings.json" and _bp.has_parts(p.parent)


def _register_if_held() -> None:
    """A process inside a wrapper-held lock registers itself when it starts
    working on the board (audit O11), not only when it writes."""
    try:
        d = _repo_lock_dir()
        if os.environ.get(BOARD_LOCK_ENV) == str(d):
            _bl_register_child(d)
    except Exception:  # noqa: BLE001
        pass


def _board_source_bytes(docs_dir: Path) -> int | None:
    """On-disk size of what read_board_records() is about to fully materialize:
    listings.json (plain, .gz twin, or summed .gz parts) plus listings_detail.json
    (plain or .gz twin). None when nothing is found (a fresh/empty board — never
    block that)."""
    docs = Path(docs_dir)
    total = 0
    found = False
    for name in ("listings.json", "listings_detail.json"):
        p = docs / name
        gz = p.with_name(p.name + ".gz")
        if p.exists():
            total += p.stat().st_size
            found = True
        elif gz.exists():
            total += gz.stat().st_size
            found = True
        elif name == "listings.json" and _bp.has_parts(docs):
            try:
                total += sum(part.stat().st_size for part in _bp.list_part_files(docs))
                found = True
            except Exception:  # noqa: BLE001
                pass
    return total if found else None


def board_load_size_state(docs_dir: Path | str, *, max_mb: float | None = None) -> dict:
    """Would read_board_records()/load_board() be safe to run against this board,
    judging ONLY by its on-disk size (audit O13) -- never by current memory
    pressure, that is board_memory_state()'s job. Returns
    {source_mb, max_mb, ok, reason}; source_mb is None when no board was found
    (treated as ok — nothing to load yet)."""
    n = _board_source_bytes(Path(docs_dir))
    limit = float(max_mb if max_mb is not None
                  else os.environ.get("BOARD_LOAD_MAX_SOURCE_MB", BOARD_LOAD_MAX_SOURCE_MB))
    if n is None:
        return {"source_mb": None, "max_mb": limit, "ok": True, "reason": ""}
    source_mb = n / (1024 * 1024)
    ok = source_mb <= limit
    reason = "" if ok else f"board source is {source_mb:.0f} MB, over the {limit:.0f} MB ceiling"
    return {"source_mb": source_mb, "max_mb": limit, "ok": ok, "reason": reason}


def _raise_if_board_too_large_to_load(docs: Path, *, who: str) -> None:
    """The BoardLoadTooLarge guard (audit O13, 2026-09-29). Called EAGERLY, as a plain
    function, by both read_board_records() and load_board() before either does any work --
    deliberately NOT inside _iter_board_records() below, because a generator function's body
    does not execute at all until first iterated, so a check placed there would not fire
    until the caller's first `next()`, which is later than "before attempting the load" for
    a caller that does setup of its own first. BOARD_LOAD_ALLOW_LARGE=1 overrides for one
    run; BOARD_LOAD_MAX_SOURCE_MB (see its comment above) is the ceiling, raised once a new
    approach is measured to handle a given size safely on this machine.
    """
    if os.environ.get("BOARD_LOAD_ALLOW_LARGE", "").strip().lower() in ("1", "true", "yes"):
        return
    size_state = board_load_size_state(docs)
    if size_state["ok"]:
        return
    log.error("board.load_too_large", **size_state, docs_dir=str(docs))
    raise BoardLoadTooLarge(
        f"{who} refused to load {docs}: {size_state['reason']}. See BoardLoadTooLarge's "
        f"docstring and BOARD_LOAD_MAX_SOURCE_MB's comment in web_artifact.py for the "
        f"measurement this ceiling is based on. BOARD_LOAD_ALLOW_LARGE=1 overrides for one "
        f"run; BOARD_LOAD_MAX_SOURCE_MB raises the ceiling once a larger size is measured "
        f"safe on this machine."
    )


def board_append_size_state(docs_dir: Path | str, *, max_mb: float | None = None) -> dict:
    """Would append_new_rows() be safe to run against this board, judging ONLY by its on-disk
    size -- the append-only counterpart of board_load_size_state(), against
    BOARD_APPEND_MAX_SOURCE_MB's separately measured ceiling instead of
    BOARD_LOAD_MAX_SOURCE_MB's (see that constant's comment for why append_new_rows earns its
    own, more generous ceiling). Same shape as board_load_size_state(): {source_mb, max_mb, ok,
    reason}; source_mb is None when no board was found (treated as ok -- nothing to append to
    yet, a fresh publish)."""
    n = _board_source_bytes(Path(docs_dir))
    limit = float(max_mb if max_mb is not None
                  else os.environ.get("BOARD_APPEND_MAX_SOURCE_MB", BOARD_APPEND_MAX_SOURCE_MB))
    if n is None:
        return {"source_mb": None, "max_mb": limit, "ok": True, "reason": ""}
    source_mb = n / (1024 * 1024)
    ok = source_mb <= limit
    reason = "" if ok else f"board source is {source_mb:.0f} MB, over the {limit:.0f} MB ceiling"
    return {"source_mb": source_mb, "max_mb": limit, "ok": ok, "reason": reason}


def _raise_if_board_too_large_to_append(docs: Path) -> None:
    """The append-only counterpart of _raise_if_board_too_large_to_load(): called eagerly by
    append_new_rows() before it does any work. BOARD_APPEND_ALLOW_LARGE=1 overrides for one
    run; BOARD_APPEND_MAX_SOURCE_MB (see its comment above BOARD_LOAD_MAX_SOURCE_MB) is the
    ceiling."""
    if os.environ.get("BOARD_APPEND_ALLOW_LARGE", "").strip().lower() in ("1", "true", "yes"):
        return
    size_state = board_append_size_state(docs)
    if size_state["ok"]:
        return
    log.error("board.append_too_large", **size_state, docs_dir=str(docs))
    raise BoardLoadTooLarge(
        f"append_new_rows refused to load {docs}: {size_state['reason']}. append_new_rows is "
        f"measurably cheaper than load_board() (see BOARD_APPEND_MAX_SOURCE_MB's comment) but "
        f"is still proportional to the existing board's size, and this board is over even its "
        f"more generous ceiling. BOARD_APPEND_ALLOW_LARGE=1 overrides for one supervised run; "
        f"BOARD_APPEND_MAX_SOURCE_MB raises the ceiling once a larger size is measured safe on "
        f"this machine."
    )


def board_patch_size_state(docs_dir: Path | str, *, max_mb: float | None = None) -> dict:
    """Would patch_existing_rows() be safe to run against this board, judging ONLY by its
    on-disk size -- the patch-only counterpart of board_load_size_state()/
    board_append_size_state(), against BOARD_PATCH_MAX_SOURCE_MB's separately measured ceiling.
    Same shape as the other two: {source_mb, max_mb, ok, reason}; source_mb is None when no
    board was found (treated as ok -- nothing to patch onto yet)."""
    n = _board_source_bytes(Path(docs_dir))
    limit = float(max_mb if max_mb is not None
                  else os.environ.get("BOARD_PATCH_MAX_SOURCE_MB", BOARD_PATCH_MAX_SOURCE_MB))
    if n is None:
        return {"source_mb": None, "max_mb": limit, "ok": True, "reason": ""}
    source_mb = n / (1024 * 1024)
    ok = source_mb <= limit
    reason = "" if ok else f"board source is {source_mb:.0f} MB, over the {limit:.0f} MB ceiling"
    return {"source_mb": source_mb, "max_mb": limit, "ok": ok, "reason": reason}


def _raise_if_board_too_large_to_patch(docs: Path) -> None:
    """The patch-only counterpart of _raise_if_board_too_large_to_load()/_to_append(): called
    eagerly by patch_existing_rows() before it does any work. BOARD_PATCH_ALLOW_LARGE=1
    overrides for one run; BOARD_PATCH_MAX_SOURCE_MB (see its comment above
    BOARD_LOAD_MAX_SOURCE_MB) is the ceiling."""
    if os.environ.get("BOARD_PATCH_ALLOW_LARGE", "").strip().lower() in ("1", "true", "yes"):
        return
    size_state = board_patch_size_state(docs)
    if size_state["ok"]:
        return
    log.error("board.patch_too_large", **size_state, docs_dir=str(docs))
    raise BoardLoadTooLarge(
        f"patch_existing_rows refused to load {docs}: {size_state['reason']}. "
        f"patch_existing_rows is measurably cheap per row (see BOARD_PATCH_MAX_SOURCE_MB's "
        f"comment) but is still proportional to the existing board's size, and this board is "
        f"over its ceiling. BOARD_PATCH_ALLOW_LARGE=1 overrides for one supervised run; "
        f"BOARD_PATCH_MAX_SOURCE_MB raises the ceiling once a larger size is measured safe on "
        f"this machine."
    )


def board_merge_size_state(docs_dir: Path | str, *, max_mb: float | None = None) -> dict:
    """Would merge_duplicate_rows() be safe to run against this board, judging ONLY by its
    on-disk size -- the merge-only counterpart of board_patch_size_state(), against
    BOARD_MERGE_MAX_SOURCE_MB's own ceiling (see that constant's comment for why it gets one
    separate from patch's, and why it currently just inherits patch's number). Same shape as the
    other three: {source_mb, max_mb, ok, reason}; source_mb is None when no board was found
    (treated as ok -- nothing to merge onto yet)."""
    n = _board_source_bytes(Path(docs_dir))
    limit = float(max_mb if max_mb is not None
                  else os.environ.get("BOARD_MERGE_MAX_SOURCE_MB", BOARD_MERGE_MAX_SOURCE_MB))
    if n is None:
        return {"source_mb": None, "max_mb": limit, "ok": True, "reason": ""}
    source_mb = n / (1024 * 1024)
    ok = source_mb <= limit
    reason = "" if ok else f"board source is {source_mb:.0f} MB, over the {limit:.0f} MB ceiling"
    return {"source_mb": source_mb, "max_mb": limit, "ok": ok, "reason": reason}


def _raise_if_board_too_large_to_merge(docs: Path) -> None:
    """The merge-only counterpart of _raise_if_board_too_large_to_load()/_to_append()/_to_patch():
    called eagerly by merge_duplicate_rows() before it does any work. BOARD_MERGE_ALLOW_LARGE=1
    overrides for one run; BOARD_MERGE_MAX_SOURCE_MB (see its comment above
    BOARD_LOAD_MAX_SOURCE_MB) is the ceiling."""
    if os.environ.get("BOARD_MERGE_ALLOW_LARGE", "").strip().lower() in ("1", "true", "yes"):
        return
    size_state = board_merge_size_state(docs)
    if size_state["ok"]:
        return
    log.error("board.merge_too_large", **size_state, docs_dir=str(docs))
    raise BoardLoadTooLarge(
        f"merge_duplicate_rows refused to load {docs}: {size_state['reason']}. "
        f"merge_duplicate_rows is measurably cheap per untouched row (see "
        f"BOARD_MERGE_MAX_SOURCE_MB's comment) but is still proportional to the existing "
        f"board's size, and this board is over its ceiling. BOARD_MERGE_ALLOW_LARGE=1 overrides "
        f"for one supervised run; BOARD_MERGE_MAX_SOURCE_MB raises the ceiling once a larger "
        f"size is measured safe on this machine."
    )


def board_delete_size_state(docs_dir: Path | str, *, max_mb: float | None = None) -> dict:
    """Would delete_rows() be safe to run against this board, judging ONLY by its on-disk size --
    the delete-only counterpart of board_merge_size_state(), against BOARD_DELETE_MAX_SOURCE_MB's
    own ceiling. Same shape as the other four: {source_mb, max_mb, ok, reason}; source_mb is None
    when no board was found (treated as ok -- nothing to delete from yet)."""
    n = _board_source_bytes(Path(docs_dir))
    limit = float(max_mb if max_mb is not None
                  else os.environ.get("BOARD_DELETE_MAX_SOURCE_MB", BOARD_DELETE_MAX_SOURCE_MB))
    if n is None:
        return {"source_mb": None, "max_mb": limit, "ok": True, "reason": ""}
    source_mb = n / (1024 * 1024)
    ok = source_mb <= limit
    reason = "" if ok else f"board source is {source_mb:.0f} MB, over the {limit:.0f} MB ceiling"
    return {"source_mb": source_mb, "max_mb": limit, "ok": ok, "reason": reason}


def _raise_if_board_too_large_to_delete(docs: Path) -> None:
    """The delete-only counterpart of _raise_if_board_too_large_to_merge(): called eagerly by
    delete_rows() before it does any work. BOARD_DELETE_ALLOW_LARGE=1 overrides for one run;
    BOARD_DELETE_MAX_SOURCE_MB (see its comment above BOARD_MERGE_MAX_SOURCE_MB) is the ceiling."""
    if os.environ.get("BOARD_DELETE_ALLOW_LARGE", "").strip().lower() in ("1", "true", "yes"):
        return
    size_state = board_delete_size_state(docs)
    if size_state["ok"]:
        return
    log.error("board.delete_too_large", **size_state, docs_dir=str(docs))
    raise BoardLoadTooLarge(
        f"delete_rows refused to load {docs}: {size_state['reason']}. delete_rows is measurably "
        f"cheap per untouched row (see BOARD_DELETE_MAX_SOURCE_MB's comment) but is still "
        f"proportional to the existing board's size, and this board is over its ceiling. "
        f"BOARD_DELETE_ALLOW_LARGE=1 overrides for one supervised run; BOARD_DELETE_MAX_SOURCE_MB "
        f"raises the ceiling once a larger size is measured safe on this machine."
    )


def board_prior_merge_size_state(docs_dir: Path | str, *, max_mb: float | None = None) -> dict:
    """Would board_persist.merge_prior_board() be safe to run against this board, judging ONLY
    by its on-disk size -- against BOARD_PRIOR_MERGE_MAX_SOURCE_MB's own ceiling (see that
    constant's comment for the real VM trial it is based on). Same shape as the other five:
    {source_mb, max_mb, ok, reason}; source_mb is None when no board was found (treated as ok --
    nothing to merge onto yet, a first-ever run)."""
    n = _board_source_bytes(Path(docs_dir))
    limit = float(max_mb if max_mb is not None
                  else os.environ.get("BOARD_PRIOR_MERGE_MAX_SOURCE_MB",
                                      BOARD_PRIOR_MERGE_MAX_SOURCE_MB))
    if n is None:
        return {"source_mb": None, "max_mb": limit, "ok": True, "reason": ""}
    source_mb = n / (1024 * 1024)
    ok = source_mb <= limit
    reason = "" if ok else f"board source is {source_mb:.0f} MB, over the {limit:.0f} MB ceiling"
    return {"source_mb": source_mb, "max_mb": limit, "ok": ok, "reason": reason}


def _raise_if_board_too_large_to_prior_merge(docs: Path) -> None:
    """The prior-board-merge counterpart of _raise_if_board_too_large_to_merge()/_to_delete():
    called eagerly by board_persist.merge_prior_board() before it streams anything.
    BOARD_PRIOR_MERGE_ALLOW_LARGE=1 overrides for one run; BOARD_PRIOR_MERGE_MAX_SOURCE_MB (see
    its comment above BOARD_LOAD_MAX_SOURCE_MB) is the ceiling. Imported directly by
    board_persist.py (a sibling module, not this one) the same way append_new_rows() already
    imports dedupe.py's _strong_sigs across module lines -- a leading underscore here means
    "internal to this file's own callers," not "may not be imported by name."""
    if os.environ.get("BOARD_PRIOR_MERGE_ALLOW_LARGE", "").strip().lower() in ("1", "true", "yes"):
        return
    size_state = board_prior_merge_size_state(docs)
    if size_state["ok"]:
        return
    log.error("board.prior_merge_too_large", **size_state, docs_dir=str(docs))
    raise BoardLoadTooLarge(
        f"merge_prior_board refused to stream {docs}: {size_state['reason']}. "
        f"merge_prior_board() streams the existing board (see BOARD_PRIOR_MERGE_MAX_SOURCE_MB's "
        f"comment) but its own return contract is still a full list[Listing] of the merged "
        f"board, so peak memory stays proportional to the board's size. "
        f"BOARD_PRIOR_MERGE_ALLOW_LARGE=1 overrides for one supervised run; "
        f"BOARD_PRIOR_MERGE_MAX_SOURCE_MB raises the ceiling once a larger size is measured "
        f"safe on this machine."
    )


def _safe_row_iter(it: Iterator, *, strict: bool) -> Iterator:
    """Wrap a sidecar row iterator so a read/parse failure becomes silent exhaustion in
    non-strict mode -- matching read_board_records()'s original all-or-nothing "the sidecar
    could not be read reliably, treat it as absent" behavior for a caller with no manifest to
    hold it to a hard contract, except that here a failure partway through the file keeps the
    rows already read (a torn sidecar used to lose ALL of it; this is only strictly kinder).
    BoardIntegrityError always propagates -- a manifest- or run_meta-verified sidecar that is
    torn is never silently downgraded to "no sidecar", strict or not."""
    try:
        for item in it:
            yield item
    except BoardIntegrityError:
        raise
    except Exception:  # noqa: BLE001
        if strict:
            raise
        return


def _iter_board_records(docs: Path) -> Iterator[dict]:
    """Body of read_board_records(), STREAMED (audit O13's real fix, 2026-09-29): yields each
    board row (a raw dict) with the lazy-detail sidecar merged into its `raw`, one row at a
    time, in board order -- never holding the whole parsed listings.json array, or the whole
    parsed listings_detail.json array, in memory at once.

    THE BUG THIS REPLACES. read_board_records() used to call _read_board_json_ex(), which
    does json.loads(path.read_text()): the file's full decoded TEXT and its full parsed
    dict/list TREE were alive together for as long as anything referenced either, and for
    load_board() specifically that whole tree then stayed alive for the ENTIRE second pass
    that built a completely separate graph of validated Listing objects. Measured on
    2026-09-29 against the real board (217,773 rows, 2.52 GB listings.json + 249 MB
    listings_detail.json): 26.3 GB peak RSS, killed after 24 minutes, still climbing.

    THE FIX. _open_board_source_rows() resolves which file to read exactly as
    _read_board_json_ex() did (honors the manifest, parts vs. gz vs. plain) but hands back a
    generator instead of a parsed list; board_parts.iter_plain_rows/iter_gz_rows/iter_rows all
    decode one top-level JSON-array element at a time from a bounded read buffer, never the
    whole file. The two streams (listings.json, listings_detail.json) are walked in lockstep
    with itertools.zip_longest so the sidecar is merged in as each row arrives, with no need
    to know either stream's length up front.

    WHAT THIS DOES NOT FIX. Whatever the caller builds FROM this generator is still
    proportional to the ROW COUNT, and that is unavoidable: read_board_records()'s contract is
    a full list[dict], load_board()'s is a full list[Listing]. See BOARD_LOAD_MAX_SOURCE_MB's
    comment for what that costs, measured, on this machine. load_board() (below) consumes
    this generator directly -- validating each row into a Listing and letting the raw dict be
    garbage the moment it is done with it -- so it never holds a full parsed-dict copy of the
    board at all, only the one Listing graph it is building.
    """
    used, rows_iter = _open_board_source_rows(docs / "listings.json")
    _remember_load(docs, used)
    _register_if_held()
    detail_path = docs / "listings_detail.json"
    strict = load_manifest(docs) is not None
    details_iter: Iterator = iter(())
    if _board_file_present(detail_path):
        try:
            _, raw_details_iter = _open_board_source_rows(detail_path)
        except BoardIntegrityError:
            raise
        except Exception:  # noqa: BLE001
            if strict:
                raise
            raw_details_iter = iter(())
        details_iter = _safe_row_iter(raw_details_iter, strict=strict)
    _MISSING = object()
    n = 0
    for rec, det in itertools.zip_longest(rows_iter, details_iter, fillvalue=_MISSING):
        if rec is _MISSING:
            # listings_detail has MORE rows than listings.json: index-alignment is broken.
            if strict:
                extra = 1 + sum(1 for _ in details_iter)
                raise BoardIntegrityError(
                    f"listings_detail has {n + extra} rows for {n} listings: "
                    f"the sidecar is index-aligned, so this board is a mixed set")
            break  # legacy behavior: only listings.json ever drove iteration
        if det is _MISSING:
            if strict:
                extra = 1 + sum(1 for _ in rows_iter)
                raise BoardIntegrityError(
                    f"listings_detail has {n} rows for {n + extra} listings: "
                    f"the sidecar is index-aligned, so this board is a mixed set")
            # legacy behavior: rows past the end of a short/absent sidecar are yielded as-is
        elif isinstance(det, dict) and det:
            raw = rec.get("raw")
            if isinstance(raw, dict):
                raw.update(det)
        yield rec
        n += 1


def read_board_records(docs_dir: Path | str = "docs") -> list[dict]:
    """The published board as RAW dicts, with the lazy-detail sidecar merged
    back into each record's raw. load_board() minus the Listing validation.

    Use this in a pass that works on dicts and has its own lenient hydrator
    (patch_run_scrapers.py, patch_listings.py, retry_vision.py all do). Those
    three used to call read_board_json() directly, which reads ONLY the slim
    listings.json — so every one of them loaded a board with no comps (33,484
    records), no vision (13,088), no CAMA (12,952), no rent comps (6,401) and no
    foreclosure sold comps (5,524), and then wrote that back.

    Bare read_board_json() is correct only when the caller does not write the
    board back. If it writes, it must come through here or through load_board().

    Records what it read (path, mtime, size) so write_artifact can refuse to
    overwrite a board that changed after this load.

    Raises BoardLoadTooLarge BEFORE attempting the load when the on-disk board
    exceeds BOARD_LOAD_MAX_SOURCE_MB (audit O13). This is a size check, independent
    of board_memory_gate()'s live swap/free check — it can fire on an idle,
    otherwise-healthy machine. BOARD_LOAD_ALLOW_LARGE=1 overrides it for one run;
    BOARD_LOAD_MAX_SOURCE_MB raises or lowers the ceiling.

    Streamed since audit O13's real fix (2026-09-29) — see _iter_board_records — but
    this function's OWN contract is still a full list[dict], built here with one
    list(...) call, for the dict-level board writers that need to mutate rows directly.
    """
    docs = Path(docs_dir)
    _raise_if_board_too_large_to_load(docs, who="read_board_records")
    return list(_iter_board_records(docs))


# Rows load_board could not validate on the last call (tests and callers read it).
LAST_LOAD_STATS: dict = {}
LOAD_DROP_LOG_LIMIT = 200


def load_board(docs_dir: Path | str = "docs", *,
               max_drop_rate: float | None = None) -> list[Listing]:
    """Load the published board as Listing objects WITH the lazy-detail sidecar
    merged back into each lead's raw.

    listings.json is slim (the heavy comps/vision keys live in the index-aligned
    listings_detail.json). Any incremental board-writer that reads listings.json
    directly and re-runs write_artifact would drop that detail — the sidecar gets
    rebuilt from raw, which no longer has those keys. Loading through this helper
    merges detail[i] back into listing[i].raw first, so the round-trip preserves
    it. Always use this instead of a hand-rolled json.loads loop in a board pass.

    Streamed since audit O13's real fix (2026-09-29): consumes _iter_board_records()
    directly, validating each row into a Listing and discarding the raw dict as it
    goes, rather than materializing read_board_records()'s full list[dict] first and
    then building a second, separate list[Listing] from it — the double-materialization
    that reached 26.3 GB against the real board on 2026-09-29 (see BoardLoadTooLarge and
    _iter_board_records's docstrings). The only full structure load_board() ever holds is
    the Listing list it returns.

    A row that fails validation is DROPPED (the board is rewritten without it), and
    that used to be `except Exception: pass`: no log line, no count. Now every drop
    is counted and logged (first LOAD_DROP_LOG_LIMIT to logs/board_load_dropped.jsonl),
    and the load FAILS when the drop rate exceeds `max_drop_rate` (default: env
    BOARD_LOAD_MAX_DROP_RATE, else 0.001 = 0.1%). BOARD_LOAD_ALLOW_DROPS=1 loads anyway.
    A caller with its own recovery for invalid rows (patch_vision_gemini's
    load_board_no_shrink) passes max_drop_rate=1.0 and re-hydrates the strays itself.
    """
    docs = Path(docs_dir)
    _raise_if_board_too_large_to_load(docs, who="load_board")
    out: list[Listing] = []
    dropped: list[tuple[int, str, str, str]] = []
    total = 0
    for i, rec in enumerate(_iter_board_records(docs)):
        total = i + 1
        try:
            out.append(Listing.model_validate(rec))
        except Exception as exc:  # noqa: BLE001
            src = str(rec.get("source", "")) if isinstance(rec, dict) else ""
            url = str(rec.get("source_url", ""))[:120] if isinstance(rec, dict) else ""
            dropped.append((i, src, url, f"{type(exc).__name__}: {str(exc)[:160]}"))
    rate = (len(dropped) / total) if total else 0.0
    LAST_LOAD_STATS.clear()
    LAST_LOAD_STATS.update({"total": total, "loaded": len(out), "dropped": len(dropped),
                            "drop_rate": rate})
    if dropped:
        by_src: dict = {}
        for _, s, _, _ in dropped:
            by_src[s] = by_src.get(s, 0) + 1
        log.error("board.load_rows_dropped", dropped=len(dropped), total=total,
                  rate=round(rate, 6),
                  by_source=dict(sorted(by_src.items(), key=lambda kv: -kv[1])[:10]),
                  first=dropped[:5])
        try:
            # next to the board that was loaded (repo/logs for the live docs dir)
            lp = Path(docs_dir).resolve().parent / "logs" / "board_load_dropped.jsonl"
            lp.parent.mkdir(parents=True, exist_ok=True)
            with open(lp, "a", encoding="utf-8") as fh:
                for idx, s, u, e in dropped[:LOAD_DROP_LOG_LIMIT]:
                    fh.write(json.dumps({"at": datetime.utcnow().isoformat() + "Z",
                                         "index": idx, "source": s, "source_url": u,
                                         "error": e}) + "\n")
        except Exception:  # noqa: BLE001
            pass
        limit = float(max_drop_rate if max_drop_rate is not None
                      else os.environ.get("BOARD_LOAD_MAX_DROP_RATE", "0.001"))
        if rate > limit and os.environ.get("BOARD_LOAD_ALLOW_DROPS", "").strip().lower() not in ("1", "true", "yes"):
            raise BoardLoadDropError(
                f"load_board dropped {len(dropped):,} of {total:,} rows ({rate:.3%}), over "
                f"the {limit:.3%} limit. Writing this board back would delete them. "
                f"See logs/board_load_dropped.jsonl. BOARD_LOAD_ALLOW_DROPS=1 loads anyway; "
                f"BOARD_LOAD_MAX_DROP_RATE raises the limit."
            )
    return out


# Whitelist of `raw` sub-keys to keep in the output (keep file small + privacy-OK)
RAW_KEEP = {
    "gis": ("owner", "mailing", "last_sale"),
    "zillow": ("zpid", "homeType", "zestimate", "yearBuilt", "bedrooms", "bathrooms",
               "livingArea", "lotSize", "taxAssessedValue", "description", "photo", "photos"),
    "flags": "*",
    "assessment": "*",
    "calc": "*",      # ARV / rehab / max_bid / ROI / cash-on-cash
    "amount_owed": "*",  # cross-sourced debt figure {value, source, label, confidence, is_actual_debt}
    "equity": "*",       # owner equity = ARV − payoff − senior liens {value, pct, payoff_source, ...}
    "liens": "*",        # joined lien stack (state tax liens etc.) [{type, amount, source, super_priority}]
    "skip_trace": "*",   # owner name / mailing address / phone for outreach (free)
    "is_new": "*",       # new-this-run flag (early-access highlight)
    "first_seen_run": "*",
    # Found while verifying THIS dict for the new Dorchester BillTrax scraper
    # (2026-09-29): scripts/run_scoped_scrapers.py stamps raw["landed_by"] =
    # "scripts/run_scoped_scrapers.py" on every row it lands (both apply_rows and
    # apply_rows_streaming — see its own test_new_rows_get_offline_valuation_and_
    # landed_by_stamp), but this key was never in RAW_KEEP, so _slim_raw() has
    # silently dropped it from the full board's published raw at every landing
    # through this script -- confirmed on the live board's own
    # web_artifact.slim_dropped_keys log line, which reported 897 rows carrying it
    # (this landing) after it had already reported 750 in the prior qpaybill/
    # Edgefield landing (e5922a1f) with nobody registering it. A pre-existing gap
    # unrelated to this scraper, fixed here rather than left for a future "why is
    # landed_by empty on every landed row" investigation.
    "landed_by": "*",
    "outreach": "*",     # owner contact + letter/email/sms drafts + channels
    "crm": "*",          # lead status + notes (persisted across runs)
    "grade": "*",     # A-F per-dimension + overall
    "location": ("median_household_income", "median_home_value",
                 "owner_occupied_pct", "unemployment_pct"),
    "comps": "*",                     # 3 sold comps per listing (HomeHarvest)
    "rent_comps": "*",                # 3 rent comps per listing (HomeHarvest)
    "comps_note": "*",                # explanation when no like-for-like found
    "comp_median_ppsf": "*",
    "market_velocity": "*",           # months-of-inventory + holding-period estimate
    "recorded_comps": "*",            # county-GIS recorded arms-length sales (median $/sqft, Tier-0 ARV)
    "comp_median_ppsf_recorded": "*",
    "recorded_sales": "*",            # county sales-roll transactions: price/date/deed/parties (audit trail)
    "recorded_ratio_comps": "*",      # median sale-to-assessed ratio from nearby recorded sales
    "comp_median_ppa_recorded": "*",  # median $/acre from recorded vacant-lot sales
    "condition_tier": "*",            # move_in_ready / cosmetic / major / gut
    "condition_source": "*",          # "vision-HIGH" / "vision-MEDIUM" / regex/age default
    "vision": "*",                    # full Claude Vision condition report
    # Sticky "image download failed" marker {urls, attempts, at} (2026-09-23).
    # enrichment_vision._needs_vision() reads this so a listing whose photo
    # URL(s) could not be fetched isn't re-selected to the front of the vision
    # queue on EVERY subsequent run -- confirmed live 2026-09-23 across 3
    # consecutive scripts/backfill_vision_haiku.py runs, each hitting the
    # identical image_fetch_failing circuit-breaker while `scored` roughly
    # halved (299 -> 150 -> 77) because the same dead-image leads got re-tried
    # from scratch every day. Must be registered here (per this dict's own
    # 2026-09-13 comment) or it never round-trips through a persist and the
    # sticky behavior silently stops working across runs. Cleared automatically
    # once the listing is actually scored (see enrichment_vision._apply).
    "vision_fetch_failed": "*",
    "doc_ocr": "*",                   # OCR of scanned legal-notice/deed docs: owner+address+debt$
    "dot_ocr": "*",                   # recorded Deed-of-Trust ORIGINAL principal + labelled
                                      # ESTIMATED current balance (never a payoff) + provenance
    "loan_amount": "*",               # scalar mirror of dot_ocr.loan_amount (recorded principal)
    "nc_ptscloud_delinquent_tax": "*",
    "lrcpwa": "*",                       # land-records parcel resolve: assessed/mailing/absentee   # PTS delinquent roll: parcel/assessed/mailing/tax_year (skip-trace)
    "nc_county_pdf_delinquent_tax": "*",
    "nc_county_csv_delinquent_tax": "*",
    "buncombe_delinquent_tax": "*",     # delinquent tax roll: balance + tax_year (needed for tax_owed year extraction)
    "rutherford_wildfire": "*",         # delinquent tax roll: taxes_owed + tax_years (list)
    "multi_year_delinquent_tax": "*",   # delinquent tax roll: total_due + year
    "spartanburg_delinquent_tax": "*",  # SC delinquent tax: balance
    "sc_state_tax_lien": "*",           # SC DeptRev state tax lien: balance
    # 2026-10-01 per-source audit hardening: the scraper itself is disabled=True
    # on the board (cross-reference only, read in-memory by enrichment_dew_liens,
    # which never persists this key -- so this was not a LIVE drop). Added as a
    # defensive completeness measure per the same RAW_KEEP-omission pattern this
    # file's own comments document repeatedly, in case the slug is ever
    # re-enabled as a board source.
    "sc_dew_lien_registry": "*",        # SC DEW UI-tax/benefit lien: balance + tax/interest/penalty breakdown
    "deed_chain": "*",                  # synthesized ownership transfer timeline + summary
    # 2026-09-13. Lexington's assessment ratio (4% owner-occupied vs 6% everything
    # else) plus fmv. Added the same hour the enricher was written, because the
    # enricher ran first and all 1,159 of its blocks were silently dropped here —
    # tax_value survived only because it is a TOP-LEVEL field. Any new raw key needs
    # RAW_KEEP, _SLIM_RAW and dashboard.js's _LEAN_RAW or it does not exist.
    "lexington_assessment": "*",
    # Name->parcel resolution provenance (matched owner, parcel, method). THIRD time
    # today a new enricher's key was dropped here before anyone noticed.
    "name_resolution": "*",
    # Same-owner parcel clustering (Dirty Deeds Tier A #2): cluster_id, size,
    # confidence, total_value, parcel_ids, member_sources. Registered BEFORE
    # the enricher's first run this time, learning from parcel_from_geo/
    # owner_cluster's own siblings landing here late three separate times
    # already today.
    "owner_cluster": "*",
    # Repeat tax/foreclosure-sale loser (Dirty Deeds Tier A #34): prior_losses,
    # most_recent_loss_date/doc_type, county, state. Registered before first run.
    "repeat_tax_loss": "*",
    # The recorded instruments behind a repeat_tax_loss tag: [{inst_class, date,
    # book, page, role, county}], newest first, at most 5. Written by the same
    # enricher. Registered here BEFORE its first run. Deliberately NOT in _SLIM_RAW
    # or dashboard.js _LEAN_RAW, so it reaches the full board but not the payload
    # phones fetch (repeat_tax_loss is in the same position). Add it to both gates
    # if the dashboard should list the deeds.
    "deed_index": "*",
    # Point-in-polygon parcel-resolution provenance (source: nc_onemap_point/
    # scdot_point, lat/lng at resolution time). Found 2026-09-16: this key has
    # been written by enrichment_parcel_from_geo.py since it was built, but was
    # never registered here — every write silently dropped it, even though
    # li.parcel_id itself (a top-level field) always survived fine. Caught only
    # after actually running the enricher board-wide for the first time via a
    # standalone backfill; the audit trail for those resolutions is unrecoverable,
    # but future runs now round-trip it.
    "parcel_from_geo": "*",
    # Horry Forfeited Land Commission — county-held inventory with a standing bid.
    # Registered BEFORE the first ingest this time; three enrichers were silently
    # dropped here today by adding the key afterwards.
    "horry_flc": "*",
    "dot_ocr": "*",                     # recorded deed-of-trust principal + estimated balance
    "loan_amount": "*",                 # scalar loan principal from dot_ocr
    "property_category": "*",           # foreclosure | preforeclosure | tax_delinquency | distressed_property
    "child_support": "*",              # child support obligation flag from court detail parser
    "rent_median_ppsf": "*",
    "estimated_monthly_rent": "*",
    "data_quality": "*",              # investor-facing caveats: synthetic_address / no_sqft / low_arv_confidence
    "parcel_resolution": "*",         # parcel + centroid reverse-geo (Cleveland NC / Cherokee SC fallback)
    "situs_road_only": "*",           # road name for a parcel with NO house number — CONTEXT, never mailable
    "lis_pendens_resolution": "*",    # SC lis-pendens GIS resolver provenance
    "rod_docs": "*",                  # ROD recorded documents (deeds, mortgages, satisfactions)
    # Deed chain + lien picture from an NC register name index (enrichment_rod_chain.py, shape in
    # rod/nc_chain.py). Registered 2026-10-07 BEFORE its first run (the enricher ships off).
    "rod_chain": "*",
    "lien_priority": "*",             # senior/junior liens + super-priority warnings
    "propwire": "*",                  # equity, owner, last sale (when present)
    "loopnet": "*",                   # multifamily-specific cap rate, units, etc.
    "reac": "*",                      # HUD REAC inspection scores {latest_score, scores[], distressed}
    "images": "*",                    # {primary, map, street} fallback image map
    "flood": "*",                     # FEMA flood-zone tag {zone, in_sfha, ...}
    "nod": "*",                       # ROD-discovered Notice of Default
    "bankruptcy": "*",                # CourtListener bankruptcy match on defendant name
    "courtlistener": "*",             # raw bankruptcy docket data when emitted as a listing
    # Bankruptcy + large delinquent-tax-balance join (Dirty Deeds Tier B #28,
    # 2026-09-29). Registered BEFORE enrichment_bankruptcy_tax_combo.py's first
    # run, per this dict's own standing lesson about new keys landing silently
    # dropped otherwise.
    "bankruptcy_tax_combo": "*",
    "distressed": "*",                # HomeHarvest distressed-keyword matches
    "epa": "*",                       # EPA ECHO environmental hazards
    "crime": "*",                     # FBI UCR / per-zip crime stats
    "fema_repetitive_loss": "*",      # NFIP multiple-loss properties (much stronger than flood zone alone)
    "code_enforcement": "*",          # City open code violations (Charlotte 311 etc.)
    "sc_tax_delinquent": "*",         # SC delinquent tax / pre-tax-sale tag
    "building_permits": "*",          # recent permits = positive, stale open = negative
    "bid4assets": "*",                # auction-site raw payload
    "sos_status": "*",                # NC SOS LLC dissolution status (when defendant is LLC)
    "sos_agent": "*",                 # NC SOS registered agent + officers = free entity-owner contact
    # Per-listing verification verdicts, one record per signal ({signal, verdict, evidence,
    # source, checked_at, verifier_version, verifier, expires_at, governs}), attached by
    # verification.apply from docs/handoff/verification/<signal>.json (HANDOFF item 66).
    "verification": "*",
    "rent_comps_extra": "*",          # broader rent comp pool when strict was empty
    "rent_median_ppsf_extra": "*",
    "estimated_monthly_rent_extra": "*",
    "schools": "*",                   # GreatSchools per-address ratings (when key set)
    "walk_score": "*",                # Walk Score per-address (when key set)
    "nc_ecourts": "*",                # NC Tyler Odyssey judgment-search row
    "upset_bid": "*",                 # NCGS §45-21.27 10-day upset-bid window
    "nc_case_status": "*",            # NC eCourts case status (pending/sold/upset)
    "court_documents": "*",           # Tyler RegisterOfActions sale paper trail [{type,date,available}]
    "court_balance_due": "*",         # live court-derived debt (judgment + accrued interest)
    "court_balance_due_as_of": "*",
    "court_record_url": "*",          # deep link to the Tyler case page
    # The court-record BLOCK itself (cause of action, court location, ordered
    # date) was written by enrichment_courts._apply_nc_hit for every NC case
    # match and then stripped here because it was never whitelisted: 621
    # matches on the 2026-08-04 run, ZERO of them on the published board.
    "court_record": "*",
    # 2026-08-30 gap-audit fix: enrichment_case_detail._apply_court_detail writes
    # these 11 court_* keys (SC PublicIndex + NC eCourts case-detail: judgment $,
    # parties, costs, docket) and they were NEVER whitelisted — parsed on every
    # run, stripped at publish. Same class of bug as court_record above.
    "court_case_number": "*",
    "court_case_caption": "*",
    "court_parties": "*",
    "court_judgment": "*",            # the money figure — parties owe $X
    "court_judgment_details": "*",
    "court_docket": "*",
    "court_summary": "*",
    "court_costs": "*",
    "court_payments": "*",
    "court_property": "*",
    "court_associated_cases": "*",
    # Also stripped-but-fetched (2026-08-30): real tax status/balance, tax relief,
    # jail-booking DOB+charges, multifamily + FEMA signals, ACPASS resolution.
    "tax_status": "*",                # paid_through / actual balance from GIS/qPayBill
    "tax_relief": "*",                # deferral / exemption (York HOMESTEAD, Anderson AG-rollback)
    "jail_booking": "*",             # net-new owner DOB + charges (contactability)
    "mf_signal": "*",                 # multifamily classification
    "fema_disaster": "*",             # FEMA declared-disaster overlay
    "acpass_resolved": "*",           # Anderson ACPASS owner/parcel resolution
    # County sales roll: the parcel's own sale history (date/price/sqft/
    # arms-length flag) plus the fields it backfills. comps sat at 0% on the
    # 2026-08-03 board; forgetting to whitelist this would gather them and
    # throw them away at publish, exactly as happened to court_record.
    "county_sales": "*",
    "auction_date": "*",              # F8: the TRUE auction date (never the docket's last event)
    "docket_last_event_date": "*",    # F8: last docket event; NOT a sale date
    "sale_date_source": "*",          # F8: set to "docket_last_event" when sale_date is only a docket stand-in
    "court_sale_status": "*",         # confirmed / sold_unconfirmed / sale_noticed / judgment
    "sold_confirmed": "*",            # court-confirmed sale → already sold, filter off active board
    "owner_mailing": "*",             # #0 contactability: owner name + mailing addr + absentee/out-of-state flags
    "owner_phone": "*",               # NC voter-file phone (name+address match) — DNC-gated, needs_dnc_scrub
    "free_phones": "*",               # TruePeopleSearch/FastPeopleSearch phones (free, bot-protected)
    "sc_voter_xref": "*",             # SC phone via NC voter file cross-reference (free, unambiguous match)
    "rod": "*",                       # Gaston NC ROD lien existence (D/T mortgage + adverse liens) by owner name
    "divorce": "*",                   # SC Family-Court divorce / marital-dissolution match on owner party-name (FCCMS)
    "geo_imprecise": "*",             # out_of_bbox (geo nulled) | centroid_snap/county_centroid/county_centroid_no_addr (no real address, shared fallback point) | census_geocode (REAL resolved address, not a shared point — valuation/calc.py treats it as full precision, see its geo_imprecise_comps comment)
    "stale_case": "*",                # presumed_withdrawn lis-pendens — likely resolved, down-ranked from HOT
    "parcel_id_nulled": "*",          # {value, reason}: the source's id validation nulled (too short / bad pattern); merge_prior_board re-keys the published row with it
    "staleness": "*",                 # staleness_sweep verdict {state: upset_closed|sale_passed|gone_quiet, ...} for dashboard filtering
    "life_events": "*",               # elderly/probate signals: life_estate | estate_probate | multiple_heirs | trust
    "probate": "*",                   # probate court case search result: case_number, filing_date, court, decedent, status
    "gis_exempt": "*",                # statutory tax-relief exemption (ELD/DIS/BLD/VET) -> hard elderly/disabled signal
    "owner_name_source": "*",         # provenance when owner_name was promoted from tax/GIS
    "owner_name_as_of": "*",          # freshness stamp (ISO date) for the CURRENT-state owner_name refresh
                                       # policy — see owner_freshness.py. Without this RAW_KEEP entry
                                       # _slim_raw() silently drops the stamp at publish and every board
                                       # row's owner_name would look permanently unstamped (= always
                                       # "unknown age") the very next run after this landed, defeating the
                                       # whole point of the staleness gate (same failure mode this file's
                                       # own landed_by/entity_type comments above already warn about).
    "notice_contact": "*",            # attributable attorney/trustee email from the legal-notice body
    "incarceration": "*",             # owner matched a state corrections roster (NC DAC) — low-conf stack signal
    "incarceration_check": "*",       # answered NO-match stamp {checked_at, name, source, result}: lets the enricher rotate past checked leads instead of re-querying the same 150
    # Dirty Deeds Tier B #36 (2026-09-29): jail-roster persistence + BOP.gov federal locator.
    "jail_booking_new": "*",          # jail_roster_history-confirmed NEW booking in a DIFFERENT county than the
                                      # listing's own property county (ep 069 "fugitive heir" case) — distinct from
                                      # jail_booking/incarceration by design, see enrichment_jail_bookings.match_cross_county
    "bop_federal": "*",               # BOP.gov Inmate Locator name match: facility code/name/type, release dates
    "bop_check": "*",                 # answered NO-match stamp for enrichment_bop_federal, same shape as incarceration_check
    # Dirty Deeds Tier B #37 (2026-09-29): foreclosure docket history sidecar.
    "repeat_foreclosure_filing": "*",  # foreclosure_docket_history-confirmed 2+ directly-observed
                                       # Dismissed/Terminated/Withdrawn cases against this owner in this
                                       # county — never inferred from a case disappearing from a later
                                       # scrape, see enrichment_foreclosure_docket_history.py
    "distress_stack": "*",
    "strategy_fit": "*",
    "eviction_market": "*",           # LSC county eviction-pressure market signal (context)
    "cama": "*",                      # county CAMA distress (condition/last-sale/deed-ref/owner-occupancy)
    "footprint": "*",                 # footprint-derived sqft ESTIMATE (area/stories/match) — transparency for estimated living_sqft
    "relationship_signal": "*",       # probate / divorce / partition deed signal
    "refresh_misses": "*",            # daily-refresh consecutive-absence counter (drop after N)
    "last_refresh_seen": "*",         # date a refreshed source last confirmed this listing in inventory
    "carryover": "*",                 # Last-known-good replay marker
    "filed_date": "*",                # Generic file-date for lis pendens / liens
    "county_pin": "*",                # Case#-encoded venue county correction
    "geo_attribution": "*",           # 'state-only' marker for unattributed BK listings
    "foreclosure_sold_comps": "*",    # Per-listing like-for-like recently-sold foreclosure comps
    "foreclosure_sold_comp_summary": "*",  # County-level sold-comp rollup
    "actual_sold_price": "*",         # Real hammer price (Pickens MIE results PDFs etc.)
    "sold_to": "*",                   # Who won a results PDF's sale: {type: plaintiff|third_party|unknown, name}
                                       # (law_firms.finkel, added 2026-10-04)
    "pickens_mie": "*",               # Pickens MIE results PDF parse provenance
    "anderson_mie_results": "*",      # Anderson MIE Sale-Results parse provenance
    "anderson_mie": "*",              # Anderson MIE Sale-List (upcoming) parse provenance: legal_description, sale_notes
    "anderson_mie_deficiency": "*",   # Anderson MIE 30-day Deficiency-Sale (reopened-bidding) PDF provenance +
                                       # the floor-bid-not-a-sale-price caution note (commit 584bba59)
    "anderson_acpass": "*",           # Anderson ACPASS deed-search (POA/COURT ORDER) instrument provenance: parties, book/page, image_url
    "spartanburg_pdf": "*",           # Spartanburg MIE PDF parse provenance (now includes is_results_pdf)
    "assessor_card": "*",             # on-demand per-parcel card: recorded sale price + history + sqft source
    "pulled_sale": "*",               # cross-run withdrawn/pulled-sale aging counter
    "comps_geo_warning": "*",         # low-confidence ARV note (comps out of geo radius)
    "link_check": "*",                # link-validator reachability tag {status, http}
    "fallback_links": "*",            # reliable backups for stale aggregator links {google, maps, parcel_gis}
    "link_may_be_stale": "*",         # True for old/carryover aggregator leads (operator "verify link" hint)
    "fhfa_value": "*",                # FHFA HPI-adjusted value estimate {value, source, ...}
    "title_risk": "*",                # title-defect / cloud-on-title risk assessment
    "zls": "*",                       # ZLS status field
    "qa_flags": "*",                  # automated data-quality flags (dup_address, arv_below_asis, etc.)
    "last_sale": "*",                 # display-ready last sale {date, amount, basis, source} for the dashboard
    "also_seen_in": "*",              # every other source + link this property was seen at (kept on merge)
    "corroboration": "*",             # court-confirmed vs single-source-aggregator flag {court_confirmed, tier, sources, label}
    "competition": "*",               # publication-reach/competition tag {level, reason, widely_published, sources}
    "signal_stack": "*",              # list-stacking: {count, signals[]} distinct distress signals per property
    "intent_score": "*",              # normalized 0-100 seller-intent score
    "intent_band": "*",               # hot/warm/cool/cold band
    "condition_cama": "*",            # CAMA per-parcel condition/grade/year_built
    "storm_damage": "*",              # Hurricane Helene damage-assessment match {damage_level, estimated_loss, ...}
    "rollback_exposure": "*",         # present-use/elderly deferral: rollback tax that comes due ON SALE
    "condemned": "*",                 # condemned/dilapidated flag from county condemned inventory
    "vacant_lot": "*",                # undeveloped/vacant land-use from the parcel cache (land-wholesale signal)
    "bankruptcy_stay": "*",           # foreclosure stayed by an automatic stay (§362) + resume-risk
    "liensnc": "*",                   # LiensNC lien-agent filing (builder/investor distress)
    # Followed-through LiensNC related filings: the Notice-to-Lien-Agent filings a
    # supplier or sub recorded against the project (which NAMES them), plus the
    # OWNER's phone / email / mailing address off the same report. 18,932 board rows
    # carry related_filings="Yes" and none had ever been followed; measured
    # 2026-09-10 the owner phone + email come back on 1500/1500 fetches, against a
    # published outreach file that reported with_phone=0. Contactability, not lead
    # count, is this engine's real ceiling — so this must survive the publish slim.
    "liensnc_related": "*",
    # Dirty Deeds Tier B #24 (docs/dirty_deeds_synthesis_2026-09-10.md): LiensNC
    # filing-date vs owner-death-date mismatch, or the deed owner's own name
    # already reading as a decedent's estate/heirs at filing time. Registered
    # BEFORE enrichment_liensnc_posthumous.py's first run — see the RAW_KEEP
    # audit trail immediately above and below for why that order matters here.
    "liensnc_posthumous_filing": "*",
    # Dirty Deeds Tier A #9 (docs/dirty_deeds_synthesis_2026-09-10.md):
    # multi_lot (2+ platted lots named in the legal/tax description) and/or
    # acreage_mismatch (legal-text acreage vs assessor Listing.acreage, >20%
    # + >0.1ac apart). Registered BEFORE enrichment_platted_lots.py's first
    # run. Deliberately NOT in _SLIM_RAW or dashboard.js _LEAN_RAW yet, same
    # position as deed_index/repeat_tax_loss above -- reaches the full board
    # for analyst review but not the lean payload phones fetch. Add it to
    # both gates if the dashboard should surface it per-row.
    "platted_lots": "*",
    # Dirty Deeds Tier B #20 (docs/dirty_deeds_synthesis_2026-09-10.md):
    # divorce judgment where both ex-spouses still clear match_owner against
    # the same current GIS/tax-roll owner-of-record cell in
    # raw['resolved_from_name'] -- "still 50/50 on record" with no deed ever
    # moving the property to one of them alone. Registered BEFORE
    # enrichment_divorce_no_subsequent_deed.py's first run, same lesson as
    # liensnc_posthumous_filing/platted_lots immediately above.
    "divorce_no_subsequent_deed": "*",
    # Dirty Deeds Tier B #30 (docs/dirty_deeds_synthesis_2026-09-10.md): a
    # tax-foreclosure defendant served by publication/alternative service whose
    # name resolves to a real mailing or situs address in the SAME county's
    # assessor/GIS data (raw['owner_mailing'] / raw['resolved_from_name'], both
    # already RAW_KEEP'd above) -- a notice-defect claim, leverage to pull a
    # pending sale or cloud a tax deed. Registered BEFORE
    # enrichment_notice_service_defect.py's first run, same lesson as
    # divorce_no_subsequent_deed immediately above.
    "notice_service_defect": "*",
    # Dirty Deeds Tier B #26 (docs/dirty_deeds_synthesis_2026-09-10.md): a SC
    # quiet-tax-title suit's constructive-service publication naming the
    # decedent's heirs {is_quiet_title, plaintiff, case_number, county,
    # street_address, parcel_id, decedents[], named_heirs[]} -- someone else's
    # paid-for heir search, published. Written by
    # column_legal_notices._sc_probate_listing. Registered BEFORE its first
    # run, same lesson as notice_service_defect immediately above.
    "heir_naming_publication": "*",
    # Dirty Deeds Tier B #35 (docs/dirty_deeds_synthesis_2026-09-10.md): land
    # buildability layer. "landlocked" = a rank-up CANDIDATE flag (parcel
    # boundary farther than 30m from every mapped NC OneMap road centerline;
    # NC only, see enrichment_land_buildability.py for the SC gap).
    # "cemetery_proximity" = a hit against the small, live-verified per-county
    # cemetery-layer registry (Buncombe, Gaston). Registered BEFORE
    # enrichment_land_buildability.py's first run, same lesson as
    # heir_naming_publication immediately above.
    "landlocked": "*",
    "cemetery_proximity": "*",
    # Fullmer deal-economics rank {rank, why, flags, cad_value, owner_count,
    # liquidity, margin_coverage}. The dashboard sorts and filters on it, so
    # stripping it here would make the whole ranking invisible.
    "fullmer": "*",
    # --- keys the 2026-09-10 RAW_KEEP audit found were being silently dropped ---
    # tests/test_raw_keep_covers_enrichers.py now fails if a new enricher joins them.
    # SC probate Notice-to-Creditors: decedent, case number, date of death, and the
    # PERSONAL REPRESENTATIVE plus their mailing address. That PR is a named,
    # mail-reachable human who controls the property -- and SC is mail-only
    # (measured phone coverage 8-18% across all seven SC counties), so this is the
    # SC contact lane. Dropping it discarded exactly the field the source exists for.
    # Graded death / fractured-ownership signal read out of the owner name itself.
    # A county only rewrites the owner of record when a survivor rings the tax office,
    # so "HEIRS OF" / "ESTATE OF" / "ET AL" implies a death AND an engaged, reachable
    # survivor. Measured 2026-09-10: 2,414 rows carry a token and are NOT on any
    # probate or obituary source (1,352 in-footprint) against 358 the dedicated
    # scrapers surface -- roughly 7x, for a regex over a column already stored.
    "owner_name_signal": "*",
    "co_defendant_signal": "*",         # SC judicial-foreclosure co-defendants: junior lienholders / gov liens / HOA / estate, read off court/sc_public_index co_defendants
    # 2026-10-02 lt_hoa_sale investigation: HOA/POA/COA plaintiff classifier over
    # already-collected foreclosure_sale/lis_pendens plaintiff text. Registered
    # BEFORE enrichment_hoa_plaintiff_signal.py's first run, same lesson as
    # heir_naming_publication / landlocked / lexington_assessment above.
    "hoa_plaintiff_signal": "*",
    "sc_probate_notice": "*",
    "life_event": "*",                  # death / divorce marker the resolver keys off
    "estimated_monthly_rent_acs": "*",  # ACS $/sqft rent estimate — the rental-exit number
    "land_use_commercial_hint": "*",    # commercial land-use signal (warehouse/retail/MF)
    "environmental_risk": "*",          # contamination / UST / brownfield proximity
    "dnc_scrub": "*",                   # DNC check result per phone — needed to show WHY a
                                        # number is or is not dialable, not just to filter
    "marriage_license": "*",            # marriage/divorce distress match
    "address_is_approximate": "*",      # DATA QUALITY: without it an approximated address
                                        # renders as though it were surveyed-exact
    "rod_lookup": "*",                  # Register of Deeds lookup result
    "assessor_photo": "*",              # which county/endpoint supplied the photo in
                                        # zillow.photo — provenance for image trust
    # NOT "vision_unscored". It was in the 2026-09-10 dropped-key audit and I added it
    # here, which broke test_ungraded_report_never_reaches_the_published_board -- a
    # guard placed deliberately. An UNGRADED vision report must not ship: on the board
    # it is indistinguishable from a real grade to anything reading raw['vision*'],
    # and the dashboard would present a failed model call as a condition assessment.
    # The diagnostic stays in-process (vision.listing_ungraded logs it). Correctly
    # excluded, not an oversight -- see INTENTIONALLY_INTERNAL in
    # tests/test_raw_keep_covers_enrichers.py.
    "builder_distress": "*",          # LiensNC cluster/related-filings = over-leveraged flipper
    "owner_mismatch": "*",            # court lead whose geo-snapped property was stripped (name-only, unverified)
    "resolved_from_name": "*",        # name->property resolver provenance {county, strategy, confidence}
    "_resolved_deep_enriched": "*",   # marker: resolved lead already got the same-run comps/Vision catch-up
    "tax_owed": "*",                  # normalized delinquent-tax balance {balance, kind, source, year, basis}
    "tenure": "*",                    # owner tenure {years_held, long_tenure} — high-equity proxy
    "contact": "*",                   # ingested skip-trace contact {phones, emails, mailing, needs_dnc_scrub}
    "link_kind": "*",                 # 'record' (real per-record link) | 'search' (portal only)
    "search_url": "*",                # portal search page when there's no direct record link
    "derivation_flags": "*",          # free_and_clear / tired_landlord / divorce derivation
    "burke_history": "*",             # Burke County ownership changes + structure loss
    "buyer_match": "*",               # buyer pool match {by_type, count, category, note}
    "derived_signals": "*",           # discount_to_arv / lien_to_value ratios
    "opportunity_zone": "*",         # OZ tract GEOID + designation
    "sale_date_passed": "*",         # flag: auction/sale date has passed
    "sale_date_passed_days": "*",    # days since sale date passed
    "propwire": "*",                  # already above, keep for safety
    "loopnet": "*",                   # already above, keep for safety
    "ocr_extraction": "*",            # OCR of legal notice PDFs: case#s, sale dates, phones, emails
    "sale_date": "*",                 # sale/auction date surfaced from OCR or scrape
    "fmr_monthly": "*",               # HUD Fair Market Rent amounts by bedroom count
    "fmr_area": "*",                  # HUD FMR area name for this listing
    "fmr_bedrooms": "*",              # HUD FMR bedroom count matched to listing
    "hud_fmr": "*",                   # HUD FMR enricher output block
    "census_rent": "*",               # rent data (sourced from HUD FMR or Census ACS)
    # ZCTA-level income/home value/owner-occ%/vacancy%/median year built
    # (Census ACS, same free key as census_rent). Registered BEFORE the
    # enricher's first run per this session's discipline.
    "census_demographics": "*",
    # Land vs improvement value split + land share (Dirty Deeds Tier A #11).
    # Registered before the first run.
    "land_ratio": "*",
    "court_bid": "*",                 # court auction bid/upset/sale status
    "rod_name_index": "*",            # ROD name-based lien index provenance
    "usps_vacancy": "*",              # USPS vacancy scan result
    "recap": "*",                     # PACER/RECAP document fetch
    "septic": "*",                    # septic system status
    "land_distress": "*",             # land-specific distress flag
    "flood_zone": "*",                # FEMA flood-zone tag (alternate key name)
    "courtlistener_adversary": "*",  # bankruptcy adversary proceeding
    "geocoded_by_name": "*",          # name-based geocoding provenance
    "gis_attrs_full": "*",            # full GIS attribute snapshot
    "situs_address_source": "*",      # situs address provenance
    "address_not_property": "*",      # {address, reason, notices}: a court/office address taken from the notice text, removed (enrichment_address_final)
    # enrichment_prior_correction (HANDOFF item 71): audit records of carried data corrected in a run.
    "parcel_withdrawn_fallback_point": "*",  # {parcel_id, reason, point, cleared, raw_removed}: a parcel resolved at a geocoder fallback point, withdrawn
    "address_was_owner_mailing": "*",        # {class, street_address, city, zip_code, situs, ...}: the owner's mailing shown as the property, replaced by the situs
    "superseded_mailing_copies": "*",        # [{street_address, first_seen, source}]: aged copies of this row that showed the owner's mailing, dropped
    "county_was_name_derived": "*",          # {county, legacy_counties, point, cleared, parcel_withdrawn}: a county read out of a debtor's case name (pre-6de9dba1 _county_from_text), cleared
    "exempt_claim_withdrawn": "*",           # {reason, claim, merged_pins, row_pin, lien_pin, cleared}: an elderly/disabled exemption claim that was another parcel's (merged in, or matched by point), withdrawn
    "owner_email": "*",               # surfaced owner email from OCR/skip-trace
    "red_flags": "*",                  # unified red flag array [{severity, type, description, source}]
    "sos_dissolution": "*",            # NC SOS LLC dissolution status
    "tax_aging_surfaced": "*",         # surfaced tax aging status for all listings
    # 2026-10-03: real sibling key scripts/surface_tax_aging.py always wrote alongside
    # tax_aging_surfaced, read directly by enrichment_equity.py's 0.70-vs-0.60 payoff-
    # estimate branch -- but never registered here, so every value was silently dropped
    # at publish (confirmed: 0 of 219,143 live rows carried it; that branch has therefore
    # always taken 0.60, never 0.70). Same bug class as dd19fa6a/6e00d55b/b88e81a5. Now
    # written every pipeline run by enrichment_tax_aging.enrich_tax_aging(), not just the
    # old one-shot script.
    "tax_aging_high": "*",             # 2yr+ delinquent flag read by enrichment_equity.py
    "two_year_delinquent": "*",        # 2yr+ delinquent flag for all listings

    # ------------------------------------------------------------------
    # 2026-09-10 SCRAPER-KEY AUDIT. Measured, not suspected: of 191 distinct raw
    # keys written by the 219 scrapers, 160 were absent from this allowlist, and a
    # scan of the live 94,384-row board found ZERO rows carrying ANY key outside it.
    # The allowlist is total, and it is silent -- _slim_raw drops an unlisted key at
    # write with no error and no log line.
    #
    # So these scrapers were working, their rows were reaching the board, and the
    # parsed detail behind every one of those rows was being thrown away at publish.
    # Confirmed at 0 rows each on the live board before this change:
    #     absentee_owner  heir_estate  nc_ecourts_divorce  upset_bid_deadline
    #     tax_sale_status  obituary  sc_public_index  mcdowell_probate
    # That is the absentee-owner signal, the heirship signal, the divorce join, the
    # upset-bid clock and the probate feed -- the fields this engine is FOR.
    #
    # This is the same mechanism that discarded 1,500 harvested owner phones earlier
    # today via the missing `liensnc_related` key. That was fixed one key at a time;
    # this is the class.
    #
    # tests/test_raw_keep_covers_enrichers.py now asserts scraper keys as well as
    # enricher keys, so key 192 fails a test instead of vanishing.

    # 2026-09-10: caught by test_every_scraper_raw_key_survives_publish on the very next
    # source written after that test landed. Without this line the Catalis roll's owner
    # MAILING address -- the field the whole source exists for -- would have been dropped
    # at publish exactly like the 160 keys before it.
    "catalis_roll": "*",
    # Dorchester SC delinquent real-property tax roll via the county's BillTrax vendor
    # (counties_sc.dorchester_billtrax_delinquent_tax, added 2026-09-29): parcel/owner/
    # situs + per-bill-year balances for a county that had zero tax-delinquent coverage.
    # Registered before the scraper's first live run, learning from every "160 keys
    # dropped at publish" entry already in this file.
    "billtrax_dorchester_delinquent_tax": "*",
    # Greenwood County SC delinquent real-property tax roll via the county's CORE/eGov
    # payment portal (counties_sc.greenwood_corebtpay_delinquent_tax, added 2026-09-30,
    # commit e38c1ec9): parcel_id/owner/service_address/bills/total_due -- the same shape
    # as billtrax_dorchester_delinquent_tax above, for a county whose only prior coverage
    # (greenwood_delinquent_tax) is the ANNUAL tax-SALE list, not this STANDING roll.
    # Registered before the scraper is wired into main.py/the board (deliberately deferred
    # for memory-safety reasons -- see the commit message), so this key never actually
    # reached publish yet, but test_every_scraper_raw_key_survives_publish correctly flags
    # it now regardless of wiring status, same posture as every other entry in this file.
    "greenwood_corebtpay_delinquent_tax": "*",
    "greenville_mie": "*",
    # 2026-09-23: caught by the greenville_tax_distress zero-net-new audit
    # (see that scraper's own docstring, "ZERO-NET-NEW AUDIT"). This module
    # writes every fact -- lanes, tax_sale echo, probate match, situs/
    # absentee provenance -- into raw["greenville_distress"], and without
    # this line it was dropped at publish exactly like the 160+ keys this
    # dict already documents above. Confirmed by grepping the entire
    # published board for the literal string "greenville_distress": zero
    # hits anywhere, including on rows that carry this source only via
    # raw["also_seen_in"] (i.e. even a merge this scraper WINS shipped none
    # of its payload before this line existed).
    "greenville_distress": "*",
    "bt_appraisal_card": "*",

    # cross-cutting distress signals
    "absentee_owner": "*", "bank_name": "*", "case": "*",
    "cash_buyer_deeds": "*", "court": "*", "document_url": "*",
    # document_links.stamp_documents() -- the shared harvester HERMES sec 5
    # calls out as THE way to wire PDFs/notices into the board (used by the
    # "8 already-harvesting scrapers" that section calls worked examples) --
    # fills BOTH raw['documents'] (the full capped list) and raw['document_url']
    # (the primary scalar, already registered just above). Found 2026-10-04
    # (national.* extraction-completeness audit, batch 15) while wiring fresh
    # CourtListener RECAP PDF URLs through this exact helper: document_url
    # alone was registered, so every call site's SECOND-and-later harvested
    # document (deed + notice on the same row, multiple RECAP filings, etc.)
    # has been silently stripped at publish since stamp_documents() was
    # written -- live-confirmed via _slim_raw() directly (documents=[...]
    # goes in, comes back out missing; document_url alone survives). Same
    # bug class as every other entry in this file's history, just upstream
    # of any one scraper rather than caused by one.
    "documents": "*",
    "epa_id": "*", "filing_number": "*", "flc": "*",
    "geo_missing": "*", "geo_source": "*", "heir_estate": "*",
    "irs": "*", "irs_treasury": "*", "legacy": "*",
    "mtg_file": "*", "multiple_owners": "*", "notice_url": "*",
    "obituary": "*", "onemap_resolved": "*", "owner": "*",
    "permit_type": "*", "sale_type": "*", "scdot_parcel_resolved": "*",
    "status": "*", "tax_sale_status": "*", "tms": "*",
    "upset_bid_deadline": "*", "violation_type": "*", "zombie_property": "*",

    # national.govdeals raw payload (lot_id, auction_id, bid_count, category,
    # seller_name, start/end dates, is_sold, has_reserve) -- namespaced under
    # one key 2026-10-01 (national-auction-tier audit, batch 4) after finding
    # these were flat top-level raw keys with no RAW_KEEP entry (silently
    # dropped at publish; only govdeals_asset_id below survived).
    "govdeals": "*",
    # national.xome raw payload (transaction_type, auction_date_text,
    # status_text, bid_type, flags) -- added 2026-10-01 (national-auction-
    # tier audit, batch 4) alongside the scraper's rewrite against the
    # site's new server-rendered card markup. xome_listing_id below is the
    # older, separate flat key and is unaffected.
    "xome": "*",

    # national.fdic_failed_banks raw payload -- added 2026-10-01 (batch-5
    # extraction-completeness audit). bank_name was already RAW_KEEP'd above,
    # but cert_number/acquiring_institution/failure_date/fund_number are flat
    # top-level keys on the same raw dict that had no entry here and were
    # being silently stripped at publish since the scraper's first commit.
    # fund_number is new (the scraper previously dropped the table's 7th
    # column outright; now captured).
    "cert_number": "*", "acquiring_institution": "*", "failure_date": "*",
    "fund_number": "*",

    # third-party listing / property identifiers, needed to re-find a lead upstream
    "fc_listing_id": "*", "govdeals_asset_id": "*", "homesteps_kind": "*",
    # national.freddie_homesteps added homesteps_details/homesteps_img_kind_slug
    # on 2026-10-01 (national/reo per-source audit) alongside homesteps_kind
    # above, but only homesteps_kind was ever registered here -- confirmed via a
    # direct _slim_raw() round-trip, both have been silently dropped at every
    # publish since 2026-10-01. Found 2026-10-04 (national.* extraction-
    # completeness audit, batch 16) while adding this SAME scraper's new
    # homesteps_agent/homesteps_specs keys (the per-listing detail-page
    # enrichment -- county/full photo gallery/lat-lng/listing-agent contact).
    "homesteps_details": "*", "homesteps_img_kind_slug": "*",
    "homesteps_agent": "*", "homesteps_specs": "*",
    "hud_property_id": "*", "reo_id": "*", "trulia_id": "*",
    "usda_property_id": "*", "vrm_id": "*", "xome_listing_id": "*",
    "zpid": "*",
    # reo.vrm_va_reo: beds/baths/sqft/list_price were flat, unregistered
    # RAW_KEEP keys (only vrm_id/images above survived) -- found 2026-10-04,
    # final extraction-completeness batch, a 9th+ instance of this exact
    # bug class this session. Namespaced here along with the per-row
    # detail-page fields (mls_id/status/stories/hoa/property_type/agent_*)
    # this same batch added.
    "vrm_va_reo": "*",

    # per-source provenance: the parsed cells, case numbers and notice URLs behind
    # each lead, which is what an operator opens a row to check
    "aiken_delinquent_tax": "*", "alaw": "*", "aldridge_pite": "*", "anderson_sheriff": "*", "arcgis_distress": "*",
    "asheville_min_housing": "*", "auction_bank_reo": "*", "auction_dot_com": "*",
    "bamberg_sheriff": "*", "barnwell_sheriff": "*", "brunswick_legal_notices": "*",
    "buncombe_tax": "*", "buncombe_tax_fcl": "*", "charleston_delinquent_tax": "*", "charleston_mie": "*",
    "charlotte_code_enforcement": "*",
    "chester_delinquent_tax": "*", "clarendon_tax_auction": "*", "cleveland_tax": "*",
    "cleveland_tax_foreclosure": "*", "coastland_times": "*", "colleton_tax_sale": "*",
    "courtlistener_civil": "*", "craigslist": "*", "cumberland_tax_foreclosure": "*",
    "cws": "*", "daily_courier": "*", "darlington_delinquent_tax": "*",
    "dillon_sheriff": "*", "edgecombe_tax_foreclosure": "*", "edgefield_delinquent_tax": "*",
    "epa_frs": "*", "estate_sales": "*", "fairfield_delinquent_tax": "*",
    "first_citizens_reo": "*", "florence_delinquent_tax": "*", "gaston_gis": "*",
    "gaston_surplus": "*", "gaston_tax_foreclosures": "*", "georgetown_civicengage": "*",
    "greenwood_delinquent_tax": "*", "gsa": "*", "gsa_surplus": "*", "haywood_tax_foreclosures": "*",
    "helene": "*", "henderson_tax": "*", "hendersonville_delinquent_tax": "*",
    "hendersonville_lightning": "*", "hibid": "*", "homeharvest": "*",
    "horry_flc": "*", "hubzu": "*",
    # national.fannie_homepath added 2026-10-04 (HERMES extraction-
    # completeness audit, batch 18): the exact same bug as the sibling
    # national.homepath_json (fixed batch 17, commit c81124b6) -- this
    # scraper's raw dict was line-for-line identical in shape, and none of
    # mls_id/property_uuid/retail_status/online_offer_only/first_look were
    # ever registered here, so they were silently dropped at every publish
    # since this scraper was built. bedrooms/bathrooms/sqft/year_built
    # promoted to first-class Listing fields instead (sidesteps RAW_KEEP),
    # same pattern.
    "fannie_homepath": "*",
    # national.homepath_json added 2026-10-04 (HERMES extraction-completeness
    # audit, batch 17): mls_id/property_uuid/retail_status/online_offer_only/
    # first_look were all flat top-level raw keys, none registered -- a
    # direct _slim_raw() round-trip confirmed only reo_id/images survived
    # publish on every one of this scraper's ~4,605 live rows since its
    # 2026-10-01 rewrite. bedrooms/bathrooms/sqft/year_built promoted to
    # first-class Listing fields instead (sidesteps RAW_KEEP), same pattern
    # batch 16 used for hud_homestore.
    "homepath_json": "*",
    # national.zillow_foreclosures added 2026-10-04 (HERMES extraction-
    # completeness audit, batch 18): marketing_status/status_text/home_type/
    # beds/baths/area were all flat top-level raw keys, none registered here
    # (only zpid/images were) -- a direct _slim_raw() round-trip confirmed
    # the rest were silently dropped at every publish since this scraper
    # was built. Also adds brokerName/listing_sub_type/isNonOwnerOccupied/
    # isZillowOwned/daysOnZillow/rentZestimate, all free, all previously
    # unread on the same already-fetched item.
    "zillow_foreclosures": "*",
    # national.zillow_bulk added 2026-10-04 (national.* extraction-
    # completeness audit, batch 5): same bug, same sibling file
    # (zillow_bulk.py is a near-line-for-line copy of zillow_foreclosures.py
    # for the sold-comp feed) -- marketing_status/status_text/home_type/
    # beds/baths/area/sold_comp were all flat top-level raw keys, none
    # registered here (only zpid/images were), silently dropped at every
    # publish since this scraper was built. "sold_comp" is a third,
    # separate flat key the same scraper writes on every row (distinct from
    # the unrelated enrichment_foreclosure_sold_comps.py "foreclosure_sold_
    # comps"/"foreclosure_sold_comp_summary" keys, already registered below)
    # -- caught by this fix's own new test (test_zillow_bulk_extraction_
    # gaps.py's _slim_raw round-trip test), registered for the same reason.
    "zillow_bulk": "*",
    "sold_comp": "*",
    # national.hud_homestore added 2026-10-04 (national.* extraction-
    # completeness audit, batch 16): 9 of this scraper's 11 raw keys
    # (fha_financing/listing_period/property_status/bid_open_date/
    # period_deadline_date/bedrooms/bathrooms/sqft/year_built) were flat
    # top-level keys never registered here at all -- confirmed via a direct
    # _slim_raw() round-trip -- so they were silently dropped at every
    # publish since this scraper was built. bedrooms/bathrooms/sqft/
    # year_built are now promoted to first-class Listing fields (no
    # registration needed); the rest moved under this new nested key,
    # which also now carries the per-case Listing Broker contact
    # (name/phone/email) fetched from each case's own /propertydetails page.
    "hud_homestore": "*", "ingle_firm": "*",
    # 2026-10-02 Kania-statewide follow-up audit: law_firms.kania (built 2026-07-31,
    # still live and correct today -- 190 rows across 24 counties) stamps
    # raw={"kania": {our_file, court_file, property_type, current_bid, sale_status,
    # row_id}} via an indirection (`raw_common = {"kania": {...}}; raw=dict(raw_common)`)
    # that test_raw_keep_covers_enrichers.py's scraper-key regex scan does not match
    # (it only catches `raw = {"key": ...}` and `raw["key"] = ...` literally), so this
    # key was never registered and _slim_raw() has been silently dropping the entire
    # block at every publish since the scraper was built. Same failure shape as the
    # landed_by/liensnc_related losses documented elsewhere in this dict.
    "kania": "*",
    "kershaw_flc": "*", "lancaster_delinquent_tax": "*", "landandfarm": "*",
    "landsofamerica": "*", "landwatch": "*", "laurens_delinquent_tax": "*",
    "lincoln_code": "*", "lincoln_vacant": "*", "marlboro_delinquent_tax": "*", "mccormick_flc": "*",
    "mcdowell_probate": "*", "mcdowell_tax_foreclosure": "*", "meares": "*",
    "mewborn_deselms": "*", "nc_bankruptcy_sales": "*", "nc_civicplus_tax_sale": "*",
    "nc_coastal_tax_foreclosure": "*", "nc_deq_dsca": "*", "nc_ecourts_divorce": "*",
    "nc_ecourts_estates": "*", "nc_govdeals_real_property": "*", "nc_rod": "*",
    "nchfa_reo": "*", "new_hanover_foreclosures": "*", "newberry_delinquent_tax": "*",
    "oconee_flc": "*", "oconee_flc_assignment": "*", "oconee_forfeited_land": "*",
    "oconee_tax_sale": "*", "pickens_tax_sale": "*", "polk_tax": "*",
    "qpaybill_roll": "*", "realtor": "*", "rutherford_foreclosure": "*",
    "rutherford_tax": "*", "saluda_delinquent_tax": "*", "sc_coastal_roster": "*",
    "sc_county_roster": "*", "sc_delinquent_tax": "*", "sc_des_brownfield": "*",
    "sc_dor_delinquent": "*", "sc_flc": "*", "sc_probate_net": "*",
    "sc_public_index": "*", "sc_ust_registry": "*", "seeclickfix": "*",
    "servicelink": "*", "shapiro_ingle_pbi": "*", "shelby_star": "*",
    "sheriff_sale": "*", "sitemap_walker": "*", "spartanburg_flc": "*",
    "state_contamination": "*", "stokes_delinquent_tax": "*", "sumter_surplus": "*",
    "surplus_auction": "*", "swain_tax_foreclosures": "*", "townnews_legal": "*",
    "transylvania_tax": "*", "transylvania_vacant": "*", "tranzon": "*",
    # national.trulia added 2026-10-04 (national.* extraction-completeness
    # audit, batch 5): is_foreclosure/is_recently_sold/beds_raw/baths_raw/
    # floor_space_raw were all flat top-level raw keys with no RAW_KEEP
    # entry (only trulia_id/images were) -- silently dropped at every
    # publish since this scraper was built.
    "trulia": "*",
    "treasury_seized": "*", "tryon_bulletin": "*", "union_delinquent_tax": "*",
    "usda_rd": "*", "usmarshals": "*", "wake_tax_foreclosure": "*",
    # national.usda_properties added 2026-10-04 (national.* extraction-
    # completeness audit, batch 5): usda_data_type/usda_eligible/facts were
    # flat top-level raw keys with no RAW_KEEP entry -- silently dropped at
    # every publish. Namespaced under this new key (also carries the new
    # detail-page fields: lot_acres/new_construction/garage_spaces/hoa/
    # hoa_fee/condition/listed_by/brokerage).
    "usda_properties": "*",
    "williams": "*", "wnc_rod": "*", "wnc_tax_foreclosures": "*",
    "york_delinquent_tax": "*",
    # York's Overage Claim List (tax-sale surplus owed BACK to the former
    # owner). Kept OUT of amount_owed -- that field is read everywhere as a
    # DEBT (equity/distress math subtracts it), and this is the opposite: a
    # credit. Own block so downstream math can't confuse the two.
    "tax_sale_overage": "*",
    # County breadth build 2026-09-21 (docs/new_county_sources_2026-09-21.md): source-specific detail
    # blocks of the new scrapers, plus Column's own block, which was silently dropped at publish before.
    "nc_its_public_tax": "*", "horry_delinquent_xlsx": "*", "albemarle_observer_tax_list": "*",
    "column": "*",
    "greenville_delinquent_tax": "*",
    "richland_flc": "*",
    "dillon_delinquent_tax": "*",
    "berkeley_paystar_tax": "*",
    # 2026-09-21 data-quality fixes (docs/data_quality_fixes_2026-09-21.md section 1). The
    # apply scripts stamp these; without an entry here write_artifact drops them silently.
    "county_backfill": "*",            # county filled from ZIP / city / parcel evidence {county, evidence, basis}
    "scope": "*",                      # 'flip_outside_footprint': a flip outside the 18 counties, scorer excludes it
    "resolver_conflict_undone": "*",
    "parcel_from_address": "*",        # parcel resolved from the lead's own street address {source, verified, county, state, matched_situs, cache_owner, owner_agrees, id_basis, cache_ids}   # withdrawn name-to-property resolution {action, query_name, matched_owner, removed}
    # Read by the scorer (docs/handoff_scorer_to_others_2026-09-21.md section 2). Without an
    # entry a board reloaded from the published files loses them, so the tax_lien_chronic weight
    # (Pickens, 3+ roll years) and the vacant_structure PROPERTY signal (Hendersonville register)
    # fire on a full run only. Pickens keeps just what the scorer and the card need (the
    # `publications` list is the bulky part); the vacancy block is four small keys.
    "pickens_delinquent": ("chronic", "repeat_delinquent", "cycle_count", "pre_sale",
                           "first_cycle", "latest_cycle"),
    "vacancy": "*",

    # docs/extraction_gaps.md verification pass (2026-09-28): these scrapers were fixed
    # on 2026-08-14 to stop dropping fetched fields, and the data DOES reach Listing.raw
    # (confirmed by reading the scrapers), but the keys were never added here — so
    # _slim_raw/_to_dict silently stripped them again at publish, one hop downstream of
    # the bug the original audit checked for. Same recurring pattern this file's own
    # comment trail warns about ("any new raw key needs RAW_KEEP ... or it does not exist").
    "cama_specs": "*",           # spartanburg_vacant/_condemned: beds/baths/sqft/year_built/land_use/last_sale
    "vacant": "*",               # spartanburg_vacant: {source, condition} from the city vacant-property registry
    "public_notice": "*",        # spartan_weekly_legals: raw notice body text backing the parsed sale fields
    "ncnotices": "*",            # ncpublicnotices: named_party + notice metadata (case_number/sale_date/plaintiff
                                  # are already first-class Listing fields; this is the supporting raw)
    "nc_county_tax_foreclosure": "*",  # county tag alongside the first-class tax_sale_status/upset_bid_deadline

    # 2026-10-02 entity_type gap closure (docs/HANDOFF.md): one shared classification of
    # owner_name (individual/entity/trust/estate/government/unknown), computed once by
    # enrichment_entity_type.py instead of recomputed independently by ~10 call sites.
    "entity_type": "*",

    # 2026-10-04: found by extending tests/test_raw_keep_covers_enrichers.py's scraper
    # scan to walk the actual AST of `raw={...}` dict literals instead of a regex that
    # could only ever see the FIRST key of such a literal (the exact blind spot that let
    # reo/vrm_va_reo's beds/baths/sqft/list_price ship silently-dropped for this whole
    # extraction-completeness audit -- see _scraper_raw_dict_literal_keys() docstring).
    # Every key below is a real, previously-unregistered, previously-silently-dropped
    # scraper raw key the new scan surfaced; duplicates of an already-published
    # top-level Listing field went to SCRAPER_KEYS_INTENTIONALLY_INTERNAL in that test
    # file instead (same precedent as this dict's own "source_url" exclusion there).
    "absentee": "*",              # counties_sc.spartanburg_vacant: mails from outside SPT/SC or a PO box
    "anonymized_address": "*", "fc_city_page": "*", "fc_price_emv": "*", "fc_search_view": "*",
    "beds": "*", "baths": "*", "sqft": "*",
    # ^ national.foreclosure_dot_com: street NUMBER is masked on this source (hence
    # anonymized_address), but city/state/zip/beds/baths/sqft and which internal code
    # path (search-view vs. city-page JSON-LD) produced the row are all real and were
    # all silently dropped.
    "collateral": "*", "debtor": "*", "filing_date": "*", "secured_party": "*",
    # ^ national.nc_sos_ucc: the UCC-1 filing itself -- who filed against whom, when,
    # and over what collateral. nc_sos_ucc's own raw["source"]="nc_sos_ucc" duplicated
    # the top-level Listing.source field and went to SCRAPER_KEYS_INTENTIONALLY_INTERNAL
    # instead of here.
    "contamination_type": "*", "npl_status": "*", "site_name": "*",
    # ^ national.epa_superfund: National Priorities List status + contamination type
    # for the site named in site_name.
    "dateless": "*",              # public_notices.funeral_home_rss: True marks a row AS
                                   # intentionally missing a sale_date (a death has none);
                                   # operator context, same precedent as link_may_be_stale
    "item_number": "*",           # counties_sc.cherokee_delinquent_tax: the county's own
                                   # tax-sale item #, distinct from parcel_id/TMS
    "property_name": "*", "units": "*", "owner_contact": "*", "section8": "*",
    "oceanfront_candidate": "*",
    # ^ national.hud_section8_contracts: owner_contact is organization/phone/email on
    # the property's HUD contract -- direct contactability (HERMES sec 9 priority #1) --
    # and section8 is the contract_expiration/expiring_soon motivated-seller signal.
    # Both were being computed and then thrown away at every publish.
    "str_permit_lapsed": "*",
    # ^ counties_nc.asheville_str_permits: status/business_name/license_number/reason
    # behind a lapsed short-term-rental permit. Already scored (distress_score.py FINANCIAL,
    # weight 12) before this fix, so the number on the board was right but the evidence
    # an operator would open the row to check was not there to back it up.

}


# Court-doc / lien / placeholder markers that scrapers sometimes drop into
# street_address when no real parcel address was resolved. These are NOT
# properties and must not render on the dashboard/map as one.
_INVALID_ADDR_MARKERS = (
    "lis pendens",
    "claim of lien",
    "notice to",
    "tract",
    "property in",
)

# A real street address starts with a house number ("123 Main St") or is a
# recognized rural form: a state/secondary road designator (SR 1135, US 221 N,
# NC 12, Hwy 9), a "Lot N" form, or a named road with a street-type suffix
# (e.g. "Riverfork Road", "Antreville Highway"). Anything else that matches an
# invalid marker (or is empty) is treated as junk.
_HOUSE_NUM_RE = re.compile(r"^\d+\s+\S")
_RURAL_DESIGNATOR_RE = re.compile(
    r"^(?:sr|us|nc|sc|hwy|highway|county\s+road|cr|state\s+road|lot)\b",
    re.IGNORECASE,
)
_ROAD_SUFFIX_RE = re.compile(
    r"\b(?:road|rd|street|st|drive|dr|highway|hwy|lane|ln|court|ct|avenue|ave|"
    r"boulevard|blvd|circle|cir|way|place|pl|trail|trl|pike|loop|run|path|"
    r"terrace|ter|parkway|pkwy|cove|point|pointe|ridge|creek|branch|crossing|"
    r"bend|pass|row|alley)\b",
    re.IGNORECASE,
)

# "No house number assigned" sentinels that county layers put in the house-number
# slot of an otherwise real road ("99999 MEADOW RD", "0 CEDAR SPRINGS RD"). NC
# alone publishes 17,788 parcels as "99999 <ROAD>" and 285,716 as "0 <ROAD>", and
# SC's split situs uses PROP_ST_NO="0" for the same thing — every one of them a
# vacant / unnumbered lot. They are NOT mailable, but they lead with digits, so
# _HOUSE_NUM_RE waves them through and they reach the mail merge, the geocoder
# and the board looking like fact. Rejected outright: falling through to the
# road-suffix rule would just re-accept them on the strength of the "RD".
# NOTE: no re.ASCII — GIS situs strings carry non-breaking spaces, and an
# ASCII-only \s let "0\xa0MEADOW RD" slip straight through this guard.
_PLACEHOLDER_HOUSE_NUM_RE = re.compile(r"^(?:0+|9{4,})(?:\s| )+\S")


def is_pinpointable_address(addr: str | None) -> bool:
    """True only when `addr` identifies ONE BUILDING — i.e. it leads with a real
    house number.

    STRICTER than _is_valid_street_address on purpose. That one answers "is this
    a plausible address string" and deliberately accepts bare rural roads via the
    road-suffix rule ("MEADOW RD", "NC HWY 9"), which is right for display.

    But a bare road is NOT a building. Geocoding it returns the ROAD CENTROID, so
    anything that spends money or asserts fact per-property must use this gate
    instead. Measured on the live board: 1,237 addressed leads are numberless and
    84% of them still return Street View imagery — of a random stretch of road,
    which would then be attached to the lead and condition-graded as if it were
    the house. Use this for Street View targeting, mail merges, and any
    "resolved" marker; use _is_valid_street_address for rendering.
    """
    if not _is_valid_street_address(addr):
        return False
    return bool(_HOUSE_NUM_RE.match(str(addr).strip()))


def _is_valid_street_address(addr: str | None) -> bool:
    """True if `addr` looks like a real, mailable street address (house number or
    a recognized rural road form), False for court-doc/lien placeholders,
    no-house-number sentinels and empties. Defensive: bad input -> False, never
    raises."""
    if not isinstance(addr, str):
        return False
    s = addr.strip()
    if not s:
        return False
    low = s.lower()
    if any(m in low for m in _INVALID_ADDR_MARKERS):
        return False
    if _PLACEHOLDER_HOUSE_NUM_RE.match(s):
        return False
    if _HOUSE_NUM_RE.match(s):
        return True
    if _RURAL_DESIGNATOR_RE.match(s):
        return True
    if _ROAD_SUFFIX_RE.search(s):
        return True
    return False


# Heavy raw keys read ONLY by the detail panel (audited: absent from every
# filter/sort/card-render path). Moved to the index-aligned listings_detail.json
# so the initial board parse skips ~10MB of comps/vision arrays.
LAZY_DETAIL_KEYS = ("vision", "foreclosure_sold_comps", "comps", "cama", "rent_comps")


# ===========================================================================
# SLIM-V1 — docs/listings_slim.json(.gz), the mobile payload
#
# 2026-08-10: the board was killing the WebContent process on two iPhones on
# every launch. docs/dashboard.js now streams listings.json.gz and projects each
# record down to a field allowlist as it parses (521 MB heap -> 167 MB), which
# fixed the crash but still makes a phone download and inflate 272 MB to throw
# ~85% of it away. This emits that projection build-side instead: ~52 MB of JSON
# and ~4 MB on the wire.
#
# THE FOUR RULES THIS FILE IS UNDER:
#
# 1. ADDITIVE, NEVER AUTHORITATIVE. listings.json + listings_detail.json are
#    TOGETHER the only full-fidelity board on disk — both are gitignored, only
#    the .gz twins are committed. Drop a key from either and the next
#    load_board() returns Listings without it, the next write_artifact()
#    re-serializes from that lobotomized raw, and the enrichment is gone
#    permanently, with three unattended launchd jobs (dailyvision 09:30, lrcpwa
#    12:00, sosagent 14:00) doing it within hours. So the slim file is derived
#    from the same `payload` list AFTER both authoritative files are already on
#    disk, it never mutates `payload`, and load_board() must NEVER read it.
#
# 2. IT IS THE BUILD-SIDE COPY OF THE CLIENT'S PROJECTOR, and the two can drift.
#    _SLIM_TOP / _SLIM_RAW / _SLIM_RAW_SCALARS mirror _LEAN_TOP / _LEAN_RAW /
#    _LEAN_RAW_SCALARS in docs/dashboard.js, and _project_slim_record mirrors
#    projectRecord(rec, true) — including the four fields the client derives
#    from `description` (kw_vacant, the flattened acres probe,
#    lrcpwa.mail_state, life_events as an int) and the Helene placard regex, all
#    of which are precomputed here so the slim file does not have to ship
#    `description` at all. The projector is idempotent, so a LEAN client running
#    it over an already-slim record is a no-op and one code path reads both
#    files. tests/test_board_slim.py parses the JS and asserts the two lists are
#    equal — if that test fails, the client changed and this must follow.
#
# 3. NOTE _SLIM_RAW's "*" SENTINEL. Six blocks are kept WHOLE, for two separate
#    reasons.
#
#    grade and calc: they were sub-allowlisted client-side and both drifted
#    within hours — the grade badge row rendered "undefined undefined undefined
#    undefined" and every listing on every phone claimed "CONFIDENCE: LOW". A
#    fabricated number on a board people bid money off is worse than a missing
#    one. Do not sub-allowlist them here.
#
#    data_quality, qa_flags, equity and distress_stack: these are FAST-CHANGING
#    DERIVED values, and whole-block here is what keeps them out of the SHARDS.
#    _SHARD_SKIP_RAW (below) skips only "*" blocks and scalars, so a block held
#    as a sub-tuple ships partly in slim and WHOLE in the shard — where it
#    churns 29 MB of committed .gz on every publish that so much as re-runs the
#    valuation. Measured on the real board: across the ARV fix (3b60fa0 ->
#    a767377) all 39 shard files changed, 24,253 of 38,500 records differed, and
#    the ONLY keys that moved board-wide were these four (data_quality 22,374,
#    qa_flags 21,678, equity 8,892, distress_stack 2,387) plus `gis` on exactly
#    one record. Whole-block here, absent from the shard, 39 changed files
#    becomes 1. Slim is rewritten every publish anyway, so it is the right file
#    to carry them. Do not sub-allowlist these back.
#
# 4. THIS FILE CAN LAG THE REAL BOARD. append_new_rows() and patch_existing_rows()
#    (2026-09-29, commits 3272b3c0/758d0bb5) are now the write path for most board
#    landings on a board too big for load_board()/write_artifact() to
#    re-materialize (see BOARD_APPEND_MAX_SOURCE_MB), and BOTH deliberately do
#    NOT regenerate listings_slim.json(.gz) or the detail shards -- see either
#    function's own docstring ("WHAT THIS DELIBERATELY DOES NOT DO"). Regenerating
#    slim needs the parsed-dict form of the WHOLE board (_emit_slim takes
#    `payload`, the full list), which is exactly the cost those two functions
#    exist to avoid; there is no cheap incremental slim update, because a phone's
#    slim file is a single gzipped JSON array, not something rows can be appended
#    into without rewriting it whole. Confirmed live 2026-09-30: the slim file sat
#    at 217,773 rows (last regenerated by a full write, commit ba3e57b3) while
#    append/patch landings had taken the real board to 219,530 -- a 0.8% phone
#    undercount with no error anywhere, and every board_selfcheck.py invariant
#    run in between had been grading the smaller, stale board instead of the one
#    actually published (fixed the same day: board_selfcheck.py now reads
#    board_stream.iter_board_rows() directly). ANY caller that needs the CURRENT
#    board -- a self-check, an audit, a count a human will act on -- must read it
#    live via board_stream.iter_board_rows() (or load_board() when it needs the
#    lazy-detail sidecar too), never listings_slim.json(.gz). The desktop
#    dashboard is unaffected (it reads listings.json/listings_detail.json
#    directly, which append/patch DO keep current); only the mobile/LEAN client
#    (docs/dashboard.js, which fetches slim first) and detail shards lag until
#    the next full write_artifact() run.
# ===========================================================================

# Top-level scalars. Mirrors _LEAN_TOP. `description` is deliberately absent —
# everything the client derived from it is precomputed below.
_SLIM_TOP = (
    "source", "source_url", "listing_type", "property_kind",
    "street_address", "city", "state", "zip_code", "county", "parcel_id",
    "latitude", "longitude",
    "sale_date", "sale_time", "sale_location", "upset_bid_deadline", "redemption_deadline",
    "opening_bid", "judgment_amount", "tax_value", "auction_status", "foreclosure_process",
    "bedrooms", "bathrooms", "living_sqft", "year_built", "acreage", "zoning",
    "case_number", "plaintiff", "defendant", "trustee", "owner_name",
)

# Per-block sub-key allowlist. Mirrors _LEAN_RAW. A block present in the source
# is ALWAYS emitted even when none of its sub-keys survive, because several
# client call sites test the block for existence rather than reading it
# (raw.upset_bid, raw.bankruptcy). "*" keeps the block whole — see rule 3.
_SLIM_RAW: dict[str, str | tuple[str, ...]] = {
    "grade": "*",
    "calc": "*",
    # data_quality.summary is 5.7 MB of prose and reads like an obvious cut. It
    # stays: it is the CSV's data_quality_note column, and the export must be
    # byte-identical on every device. Whole-block ("*") rather than
    # ("flags", "summary") for the churn reason in rule 3 — the only sub-key the
    # tuple was dropping is arv_confidence, 26 KB per 1,000 records, against
    # 354 KB per 1,000 of shard rewrite.
    "data_quality": "*",
    # The sub-tuple already listed every sub-key this block carries on the live
    # board, so "*" adds ZERO bytes to slim and takes 242 KB per 1,000 records
    # out of the shard. Pure win.
    "distress_stack": "*",
    "signal_stack": ("count",),
    "strategy_fit": ("tags",),
    "owner_mailing": ("mailing", "mail_state", "absentee", "out_of_state"),
    # The four keys after needs_dnc_scrub are the SC phone gate's flags (docs/phone_gate_2026-09-21.md):
    # without them the slim board, which the dashboard list, the "has phone" filter and the CSV export
    # read, would drop the do-not-dial verdict. Must stay identical to _LEAN_RAW in docs/dashboard.js
    # (tests/test_board_slim.py parses the JS and asserts equality).
    "owner_phone": ("phone", "source", "needs_dnc_scrub", "do_not_dial", "do_not_dial_reason",
                    "identity_check", "role"),
    "free_phones": ("phone", "source", "confidence", "needs_dnc_scrub"),
    "sc_voter_xref": ("phone", "source", "match_type", "needs_dnc_scrub"),
    # resolved_for_entity added 2026-10-03 (provenance only, see enrichment_sos_agent.py's
    # docstring): the entity name this profile was actually resolved FOR, so a human
    # reading the dashboard can compare it against the lead's current owner_name/defendant
    # themselves instead of the slim view silently showing a stranded contact with no way
    # to tell it apart from a still-good one.
    "sos_agent": ("sosid", "best_contact_name", "best_contact_address", "resolved_for_entity"),
    "rod": ("has_mortgage", "has_adverse_lien", "has_hoa_lien", "hoa_lien_count"),
    # Whole-block: withheld_reason / withheld / arv_trust / arv_flags are the
    # sentences that say WHY a figure is missing, the detail panel reads them,
    # and they change with the valuation. This is the largest of the four moves
    # — ~169 KB per 1,000 records into slim — and still cheaper than the shard
    # rewrite it stops.
    "equity": "*",
    "title_risk": ("surviving_senior_debt_risk",),
    "corroboration": ("court_confirmed", "label", "tier", "multi_source"),
    "helene": ("worst_placard", "worst_damage_pct", "damaged_buildings"),
    # case_age_days/case_age_years/is_long_open (2026-09-29, Tier B #28): derived purely
    # from date_filed (+ date_terminated when known) — see signal_freshness.bankruptcy_
    # case_age. "signal" distinguishes a recent-filing match from a long-open one (a case
    # filed 10-15 years ago with no recorded closure — the synthesis's "strongest variant").
    "bankruptcy": ("chapter", "date_filed", "case_name", "docket_number", "court",
                   "case_age_days", "case_age_years", "is_long_open", "signal"),
    "courtlistener": ("chapter", "date_filed", "court",
                       "case_age_days", "case_age_years", "is_long_open"),
    "last_sale": ("date", "amount", "basis"),
    "zillow": ("photo",),
    "gis": ("owner",),
    "lrcpwa": ("absentee", "mail_state"),
    "tax_owed": ("balance",),
    # deadline_iso (2026-09-21, scorer handoff): the scorer reads the deadline when present and
    # falls back to the in_window flag, so a scorer run over slim-only rows treated a frozen
    # in_window=true as open. With the deadline in slim the read-time check is exact (F15).
    # Mirrors docs/dashboard.js _LEAN_RAW.upset_bid; tests/test_board_slim.py pins them equal.
    "upset_bid": ("in_window", "days_remaining", "deadline_iso"),
    # APPENDED, deliberately last. Two things about this entry:
    #
    # It is a LIST, not a dict, so neither projector's "*" branch is what
    # carries it — both fall through their shape-drift branch ("not a dict" here,
    # `Array.isArray` in the client) and copy it verbatim. Same result, and it is
    # still declared "*" because _SHARD_SKIP_RAW reads that literal to decide the
    # shard skips it. Do not "fix" it to a tuple.
    #
    # It is NEW to the allowlist, not a re-shaping of an existing entry, and it
    # goes at the END so no other key's position in the record moves — key order
    # here is the key order of every record in the slim file.
    #
    # It also closes a real gap. qa_flags is enrichment_board_qa's output and
    # arvTrust() (dashboard.js) reads it as a reason to distrust a published ARV
    # — arv_above_asis, arv_below_asis, verdict_on_flagged_arv,
    # bid_on_contradicted_arv, derived_without_arv, gis_row_shared. Until now it
    # was in no slim allowlist at all, so a phone had no board-QA backstop: on
    "qa_flags": "*",
    # New enrichment fields — keep whole so dashboard can read all sub-keys.
    "property_category": "*",
    "deed_chain": "*",
    # APPENDED LAST. fullmer is fullmer_rank.py's output — the buy-box RANK the
    # call list is ordered by. It was in RAW_KEEP (so it survived to the full
    # board) but in NEITHER allowlist, so raw.fullmer was on 0 of 115,994 slim
    # rows and no phone could see a rank. Whole-block: rank/why/flags are read
    # together and the block gains keys whenever the buy-box arithmetic changes.
    "fullmer": "*",
    # Owner-occupancy derived from the SC assessment ratio. Ships because it is a
    # contact-quality signal the detail panel shows next to absentee.
    "lexington_assessment": ("assessment_ratio", "owner_occupied", "fmv", "tax_year"),
    # Narrow tuples, not "*": the actionable parts of both blocks are already
    # TOP-LEVEL fields (opening_bid, street_address, parcel_id). What ships here is
    # the provenance a reader needs to trust the row.
    "horry_flc": ("Item_Number", "FLC_Bid_Amount", "Description"),
    "name_resolution": ("matched_owner", "method"),
    "tax_sale_overage": ("amount", "tax_sale_date", "map_number"),
    # APPENDED LAST (2026-09-21, lead request): the stored bankruptcy-stay verdict and the
    # withdrawn/pulled-sale aging counter, so a phone shows a stayed or pulled sale as
    # stayed or pulled instead of live. Whole blocks (both are a few keys); "*" so
    # _SHARD_SKIP_RAW skips them in the shards. Mirrors the two matching entries appended
    # at the end of _LEAN_RAW in docs/dashboard.js (test_board_slim pins them equal).
    "bankruptcy_stay": "*",
    "pulled_sale": "*",
    # APPENDED LAST (2026-09-29, Tier B #28): the bankruptcy+large-delinquent-tax-balance
    # combo flag (enrichment_bankruptcy_tax_combo.py). Whole block, "*", same reasoning as
    # the other combo/rank blocks above — a handful of keys, all read together. Mirrors the
    # matching entry appended at the end of _LEAN_RAW in docs/dashboard.js.
    "bankruptcy_tax_combo": "*",
}


# Mirrors _LEAN_RAW_SCALARS.
_SLIM_RAW_SCALARS = (
    "intent_score", "intent_band", "multifamily_class",
    "stale_case", "geo_imprecise", "sold_confirmed", "kw_vacant", "acres",
    "child_support",
)

# Mirrors _ACRE_KEYS. The client probes three containers x four names = the
# 12-way acreage probe; the result is flattened to raw.acres here so the slim
# file carries one number instead of three blocks kept alive to hold it.
_SLIM_ACRE_KEYS = ("acreage", "acres", "calculatedAcres", "deededAcres")

# Mirrors the two regexes in heleneInfo()'s description fallback. Only Asheville
# Helene leads carry a placard in prose rather than in the dedup meta.
_HELENE_PLACARD_RE = re.compile(r"Helene damage:\s*([A-Za-z]+)\s+placard")
_HELENE_PCT_RE = re.compile(r"placard\s*-\s*([0-9]+)%")
_HELENE_SOURCE = "counties_nc.asheville_helene"

_VACANT_MARKERS = ("vacant lot", "vacant land", "vacant parcel")

# JS parseFloat: optional sign, leading numeric prefix, trailing garbage ignored
# ("12.5 acres" -> 12.5). Anchored at the start after stripping leading space.
_JS_FLOAT_RE = re.compile(r"[+-]?(?:\d+\.?\d*|\.\d+)(?:[eE][+-]?\d+)?")


def _js_parse_float(v):
    """Python stand-in for JS ``parseFloat``, which is what the client's acreage
    probe uses. Non-numeric -> None (JS NaN). Booleans are NOT numbers in JS, and
    Python's bool-is-int would otherwise turn ``acreage: true`` into 1 acre.

    Integral results come back as ``int`` so json.dumps emits ``12`` and not
    ``12.0`` — matching JSON.stringify, which has no float/int distinction.
    """
    if isinstance(v, bool):
        return None
    if isinstance(v, (int, float)):
        f = float(v)
    elif isinstance(v, str):
        m = _JS_FLOAT_RE.match(v.strip())
        if not m:
            return None
        try:
            f = float(m.group(0))
        except ValueError:
            return None
    else:
        return None
    if f != f or f in (float("inf"), float("-inf")):  # NaN / Infinity
        return None
    return int(f) if f.is_integer() and abs(f) < 2 ** 53 else f


def _slim_acres_probe(raw: dict):
    """Mirrors _acresProbe: first hit across (raw.lrcpwa, raw.gis, raw) x the
    four acreage spellings. Returns None when nothing parses."""
    r = raw if isinstance(raw, dict) else {}
    for src in (r.get("lrcpwa"), r.get("gis"), r):
        if not isinstance(src, dict):
            continue
        for k in _SLIM_ACRE_KEYS:
            v = _js_parse_float(src.get(k))
            if v is not None:
                return v
    return None


def _slim_life_event_count(le) -> int | float:
    """Mirrors _lifeEventCount. raw.life_events is a list of probate/elderly
    signals but the client only ever reads ``.length``, so the slim file ships
    the count. Matches the JS exactly, including that a bool has no .length."""
    if le is None or isinstance(le, bool):
        return 0
    if isinstance(le, (int, float)):
        return le
    try:
        return len(le) or 0
    except TypeError:
        return 0


def _project_slim_record(rec: dict) -> dict:
    """Build-side ``projectRecord(rec, lean=true)``.

    Pure: never mutates `rec` or anything reachable from it. The "*" blocks are
    passed through by REFERENCE (they are large and this runs 38,500 times), so
    every derived value below is written into a dict this function created.
    """
    if not isinstance(rec, dict):
        return rec

    out: dict = {}
    for k in _SLIM_TOP:
        if k in rec:
            out[k] = rec[k]

    desc = rec.get("description")
    if not isinstance(desc, str):
        desc = ""
    # kw_vacant replaces the three description probes in _catOf(), which decide
    # land vs residential and therefore which buyers match a lead. Precomputing
    # it is what lets `description` (6.1 MB) leave the payload without mobile
    # silently classifying leads differently from desktop.
    #
    # The `elif desc` (rather than a plain else) is what makes the CLIENT's
    # projector a strict fixed point on this file's output: with no description
    # in hand it emits no kw_vacant, so writing `kw_vacant: false` here for the
    # 65-odd records that carry an empty description would make
    # projectRecord(slim) stop deep-equalling slim. _catOf reads an absent
    # kw_vacant and a false one identically once description is also gone, so
    # this is byte-saving, not behaviour.
    kwv = rec.get("kw_vacant")
    if kwv is not None:
        out["kw_vacant"] = bool(kwv)
    elif desc:
        low = desc.lower()
        out["kw_vacant"] = any(m in low for m in _VACANT_MARKERS)

    raw = rec.get("raw")
    if not isinstance(raw, dict):
        if "raw" in rec:
            out["raw"] = raw
        return out

    r: dict = {}
    for k, subs in _SLIM_RAW.items():
        src = raw.get(k)
        if src is None:
            continue
        if not isinstance(src, dict):
            r[k] = src            # shape drift: keep verbatim, same as the client
            continue
        if subs == "*":
            r[k] = src            # by reference — never mutated
            continue
        r[k] = {sk: src[sk] for sk in subs if sk in src}

    for k in _SLIM_RAW_SCALARS:
        if k in raw:
            r[k] = raw[k]

    asi = raw.get("also_seen_in")
    if isinstance(asi, list):
        # Mirrors the client's {url, source} map. Absent sub-keys stay absent
        # rather than becoming nulls — JSON.stringify drops undefined.
        r["also_seen_in"] = [
            ({sk: s[sk] for sk in ("url", "source") if sk in s} if isinstance(s, dict) else s)
            for s in asi
        ]

    if "life_events" in raw:
        r["life_events"] = _slim_life_event_count(raw["life_events"])

    # lrcpwa.mail_state is the flattened form of lrcpwa.mailing.state, which the
    # out-of-state chip reads. Today's board carries only the nested key, so
    # without this the chip vanishes for 270 of the 3,062 leads with an lrcpwa
    # block. (r["lrcpwa"] is our own dict, so this mutation cannot reach payload.)
    lr = r.get("lrcpwa")
    if isinstance(lr, dict) and "mail_state" not in lr:
        src_lr = raw.get("lrcpwa")
        mailing = src_lr.get("mailing") if isinstance(src_lr, dict) else None
        if isinstance(mailing, dict) and mailing.get("state") is not None:
            lr["mail_state"] = mailing["state"]

    if "acres" not in r:
        a = _slim_acres_probe(raw)
        if a is not None:
            r["acres"] = a

    # heleneInfo() falls back to a regex over `description` when the dedup meta
    # carries no placard. Run that fallback here, while description is still in
    # hand, so worst_placard is always populated in the slim file.
    if desc and rec.get("source") == _HELENE_SOURCE:
        h = r.get("helene")
        if h is None:
            h = {}
        if isinstance(h, dict) and not h.get("worst_placard"):
            m = _HELENE_PLACARD_RE.search(desc)
            p = _HELENE_PCT_RE.search(desc)
            if m:
                h["worst_placard"] = m.group(1)
            if p:
                h["worst_damage_pct"] = int(p.group(1))
            if m or p:
                r["helene"] = h

    out["raw"] = r
    return out


def _slim_payload_bytes(payload: list) -> bytes:
    """Serialize the slim projection of `payload`.

    Record-at-a-time and joined, rather than json.dumps over a projected list,
    so the whole projected object graph is never resident — this runs right
    after two multi-hundred-MB serializations on an 8 GB machine.

    COMPACT SEPARATORS, and only here: default separators cost 17.1 MB of pure
    whitespace at this record count. listings.json keeps its default separators
    because its bytes must not change.
    """
    parts = [
        json.dumps(_project_slim_record(rec), ensure_ascii=False, default=str,
                   separators=(",", ":")).encode("utf-8")
        for rec in payload
    ]
    return b"[" + b",".join(parts) + b"]"


def _report_slim_drops(listings) -> None:
    """Log raw keys that are on the BOARD in volume but absent from _SLIM_RAW.

    THE PROBLEM THIS SOLVES. RAW_KEEP and _SLIM_RAW are two separate gates: the
    first decides what reaches the full board, the second what reaches the payload
    phones fetch. Registering one is not registering the other, and NOTHING FAILS
    when a key is missing from either — the data simply does not arrive.

    On 2026-09-13 that cost four enrichers in a single day: `fullmer` (0 of 115,994
    slim rows, the whole buy-box rank invisible), `lexington_assessment` (1,159
    blocks written and dropped), `name_resolution`, and `horry_flc` — the last two
    registered in RAW_KEEP only, by someone who had just written "registered BEFORE
    the first ingest this time" in a commit message.

    Documentation did not fix it, because the failure is silent. This makes it loud:
    every publish now prints what it is leaving out and how many rows carry it.
    A key on thousands of rows and absent from slim is almost always a mistake; a
    key on a handful is usually deliberate. The log lets a human tell the difference
    instead of discovering it weeks later from a zero on a dashboard.
    """
    try:
        counts: dict[str, int] = {}
        for li in listings:
            raw = getattr(li, "raw", None)
            if not isinstance(raw, dict):
                continue
            for k in raw:
                counts[k] = counts.get(k, 0) + 1
        dropped = sorted(
            ((k, n) for k, n in counts.items()
             if k not in _SLIM_RAW and k not in _SLIM_RAW_SCALARS and n >= 100),
            key=lambda kv: -kv[1])
        if dropped:
            log.info("web_artifact.slim_dropped_keys",
                     note="on the board but NOT in the slim payload — intended?",
                     keys={k: n for k, n in dropped[:15]},
                     total_dropped=len(dropped))
    except Exception:  # noqa: BLE001 — a diagnostic must never break a publish
        pass


def _emit_slim(docs: Path, payload: list) -> int | None:
    """Write listings_slim.json + .gz. Returns the record count, or None if the
    slim payload could not be produced.

    Never raises. This runs inside three unattended daily jobs, after the
    authoritative board is already safely on disk, and a derivative file is not
    worth failing a run over.

    On failure the slim files are REMOVED rather than left behind. Index i is
    the join across listings.json / listings_detail.json / listings_slim.json,
    and that alignment only holds within one write_artifact call — a stale slim
    file beside a fresh board is a silently mis-joined board on a phone, which is
    strictly worse than no slim file at all (the client 404s and streams the fat
    one, which is exactly what it does today).
    """
    slim_path = docs / "listings_slim.json"
    gz_path = docs / "listings_slim.json.gz"
    if os.getenv("FORECLOSURE_SLIM") == "0":   # emergency stop for the launchd jobs
        # DELETE, do not merely decline to rewrite. Returning None here left the
        # PREVIOUS board's slim files on disk: meta["board"] was then omitted,
        # which sets boardExpectedCount() null and DISABLES the client's
        # record-count gate, while the LEAN client still fetches
        # listings_slim.json.gz FIRST and gets it. Phones rendered the previous
        # board's addresses and sale dates beside a current desktop, with no
        # error anywhere — the exact failure the flag exists to prevent, caused
        # by the flag. Executed on a seeded temp dir before the fix: both slim
        # files survived with previous-board content and only detail_shards was
        # removed. Removing them makes the client 404 and stream the fat board,
        # which is the documented fallback.
        for p in (slim_path, gz_path):
            try:
                p.unlink(missing_ok=True)
            except OSError:
                pass
        return None
    try:
        import gzip as _gzip
        slim_bytes = _slim_payload_bytes(payload)
        _atomic_write_bytes(slim_path, slim_bytes)
        _atomic_write_bytes(gz_path, _gzip.compress(slim_bytes, compresslevel=9, mtime=0))
        return len(payload)
    except Exception as exc:  # noqa: BLE001
        # Only the finished files: _atomic_write_bytes now names its temp with
        # the PID and unlinks it itself on failure, so there is no fixed ".tmp"
        # left here to sweep. Naming one would sweep another process's.
        for p in (slim_path, gz_path):
            try:
                p.unlink(missing_ok=True)
            except OSError:
                pass
        log.warning("web_artifact.slim_failed", error=str(exc))
        return None


# ===========================================================================
# DETAIL SHARDS — docs/detail_shards/NNNNN.json.gz, the mobile detail payload
#
# Phase 3 gave phones docs/listings_slim.json.gz, so the BOARD fits. Opening one
# lead still did not: listings_detail.json inflates to 70.8 MB and the client
# Object.assigns all 38,500 of them permanently into LISTINGS[i].raw, so on the
# device whose whole problem is memory the first tap finished it. dashboard.js
# therefore skips the sidecar entirely on LEAN and prints "Open this lead on a
# desktop for comps, photo analysis and CAMA."
#
# A shard is that file, cut into 39 index-aligned pieces. Shard k covers board
# indices [k*SIZE, (k+1)*SIZE). A phone fetches the ONE shard holding the lead
# it opened — 413 KB at the median, 6 MB inflated — instead of 7.6 MB / 70.8 MB.
#
# WHY THE CONTENT IS THE COMPLEMENT OF SLIM AND NOT JUST LAZY_DETAIL_KEYS.
# The detail panel's "Everything We Found" (dashboard.js:1641) is not a named
# read, it is a reflective sweep over Object.keys(raw). The slim projection is a
# name allowlist, and a name allowlist cannot preserve a reflective reader: the
# board carries 107 distinct raw.* keys and slim keeps 29. A shard carrying only
# the five LAZY_DETAIL_KEYS would restore comps/vision/CAMA and leave ~46 other
# blocks blank — eviction_market (80.9% of records), amount_owed (59.9%), tenure
# (43.7%), recorded_comps, recorded_sales, condemned, divorce, nc_ecourts. So a
# shard record is listings_detail.json[i] MERGED WITH every raw key that
# listings.json carries and the slim projection does NOT reproduce in full.
#
# _SHARD_SKIP_RAW is derived from _SLIM_RAW / _SLIM_RAW_SCALARS rather than
# written out, so it cannot drift from the projector the way a hand-kept second
# list would. Only two classes of key are skipped:
#   * _SLIM_RAW entries marked "*" (grade, calc, data_quality, distress_stack,
#     equity, qa_flags) — slim ships them WHOLE.
#   * _SLIM_RAW_SCALARS — slim ships the scalar verbatim.
# A block slim keeps only a SUB-TUPLE of (zillow -> photo, gis -> owner,
# signal_stack -> count, ...) is emitted here in FULL, on purpose: the panel
# reads exactly the sub-keys slim drops (zillow.description, gis.mailing,
# signal_stack.signals). The duplicated sub-keys cost bytes; a half-populated
# block costs facts.
#
# THIS ONLY WORKS BECAUSE THE CLIENT MERGE DEEPENS. It did not until 2026-08-11.
# docs/dashboard.js _shardMerge skipped any key already present on the record,
# and the slim projector emits an allowlisted block whenever the source has it
# EVEN WHEN NO SUB-KEY SURVIVES — so for every sub-tupled block the key was
# always already there, the skip always fired, and the full copy below was never
# applied. Measured at 375x812 on the live board: zillow.description 0/10 leads,
# gis.mailing 0/10, signal_stack.signals 0/10, corroboration.sources 0/10;
# 50,459,084 of 216,924,819 shard bytes (23.3%) were unreachable duplicates
# shipped to phones that could not read them. The merge now copies in only the
# sub-keys the record lacks and records them at sub-key granularity so LRU
# eviction can take back exactly what it added.
#
# If that merge ever reverts to a top-level assign, every sub-tuple below turns
# back into dead weight — silently, because the panel simply renders less.
#
# WHICH SIDE OF THAT LINE A BLOCK BELONGS ON IS A CHURN DECISION, NOT ONLY A
# SIZE ONE. Duplicating a block here costs its bytes once per publish; carrying
# it here at all costs a full rewrite of every shard file that holds a record
# whose copy changed, and a gzip blob does not delta-compress. Four blocks —
# data_quality, qa_flags, equity, distress_stack — are derived from the
# valuation and change on essentially every publish while vision/comps/cama sit
# still, which is the exact inverse of what a shard is for. They were moved to
# "*" in _SLIM_RAW so they leave here entirely. Measured on the real board: the
# ARV-fix publish (3b60fa0 -> a767377) changed all 39 shard files and 24,253 of
# 38,500 records, and those four keys plus `gis` on ONE record were the only
# things that had moved. Under this rule that publish rewrites 1 shard, not 39.
#
# THE INVARIANT THIS CODE IS UNDER, same as SLIM-V1's rule 1: ADDITIVE, NEVER
# AUTHORITATIVE. listings.json + listings_detail.json are TOGETHER the only
# full-fidelity board on disk. Shards are emitted from the SAME payload/details
# lists AFTER all six authoritative files are already written, they never mutate
# either list, and load_board() must NEVER read them.
# ===========================================================================

DETAIL_SHARD_DIR = "detail_shards"
DETAIL_SHARD_SIZE = 1000          # records per shard -> 39 files at 38,500 leads
DETAIL_SHARD_SCHEMA = "shard-v1"

# Raw keys the slim payload already reproduces IN FULL, so a shard would only
# duplicate them. Derived, never hand-listed — see the block comment above.
_SHARD_SKIP_RAW = frozenset(k for k, v in _SLIM_RAW.items() if v == "*") | frozenset(_SLIM_RAW_SCALARS)


def _shard_record(rec: dict, det) -> dict:
    """One shard entry: the raw keys slim does not carry, plus the sidecar.

    Pure — never mutates `rec`, `rec["raw"]` or `det`. Sub-objects are passed by
    REFERENCE (this runs 38,500 times right after two multi-hundred-MB
    serializations), so nothing below may write into them.

    `det` is applied LAST. It cannot collide today — write_artifact pops every
    LAZY_DETAIL_KEY out of raw before building details, so the two key sets are
    disjoint — but if that ever changes, the sidecar is the copy that survived
    the identity-keyed cross-run backfill and is the one to keep.

    An empty result is still emitted by the caller: index alignment IS the join.
    """
    out: dict = {}
    raw = rec.get("raw") if isinstance(rec, dict) else None
    if isinstance(raw, dict):
        for k, v in raw.items():
            if k not in _SHARD_SKIP_RAW:
                out[k] = v
    if isinstance(det, dict) and det:
        out.update(det)
    return out


def _rm_detail_shards(shard_dir: Path) -> None:
    """Remove the shard directory and any temp files, never raising.

    Deliberately a real deletion and not a no-op: index i is the join across
    listings.json / listings_detail.json / detail_shards, and that alignment
    only holds within one write_artifact call. Shards left behind from a
    PREVIOUS board would silently show one lead's comps and vision under another
    lead's address — worse than the honest "open on desktop" note the client
    falls back to when the metadata is absent.

    Leaving the (now-empty) directory would be equally wrong: every publish site
    gates `git add docs/detail_shards` on "exists OR already tracked", and the
    tracked half of that gate is what lets this deletion reach the repo.
    """
    try:
        import shutil
        shutil.rmtree(shard_dir, ignore_errors=True)
    except Exception:  # noqa: BLE001
        pass


def _emit_detail_shards(docs: Path, payload: list, details: list,
                        slim_ok: bool = True) -> dict | None:
    """Write docs/detail_shards/NNNNN.json.gz. Returns the run_meta board
    sub-block describing them, or None when no usable shard set exists.

    Never raises. This runs inside four unattended launchd jobs, after the
    authoritative board is already safely on disk, and a derivative file is not
    worth failing a run over.

    On ANY failure — or when `slim_ok` is False — the whole directory is REMOVED
    rather than left half-written or left behind: the client keys off the
    metadata, which is omitted in lockstep, so it falls back to today's
    desktop-only note instead of rendering half a lead or a stale one.

    `slim_ok` is the deliberate coupling of the two mobile derivatives. Shards
    are only ever fetched by the LEAN client, they are advertised inside the
    same run_meta "board" block the slim payload owns, and that block is defined
    as describing the payload THIS call wrote. So when slim is absent — the
    FORECLOSURE_SLIM=0 emergency stop, or a projection failure — the honest
    outcome is that the whole mobile payload is absent together, and mobile
    degrades to exactly what it does today. Emitting 28 MB of shards that
    nothing advertises would be the worst of both.
    """
    shard_dir = docs / DETAIL_SHARD_DIR
    if not slim_ok:
        _rm_detail_shards(shard_dir)
        return None
    if os.getenv("FORECLOSURE_DETAIL_SHARDS") == "0":   # emergency stop
        # Unlike the slim stop, this REMOVES. A stale shard set is mis-joined
        # data on a phone; a stale slim file at least still describes a board.
        _rm_detail_shards(shard_dir)
        return None
    if not payload:
        _rm_detail_shards(shard_dir)
        return None
    try:
        import gzip as _gzip
        shard_dir.mkdir(parents=True, exist_ok=True)
        written: set[str] = set()
        for start in range(0, len(payload), DETAIL_SHARD_SIZE):
            stop = start + DETAIL_SHARD_SIZE
            recs = payload[start:stop]
            dets = details[start:stop]
            # Joined bytes rather than json.dumps over a built list, matching
            # _slim_payload_bytes: the merged object graph is never resident.
            parts = [
                json.dumps(_shard_record(rec, dets[i] if i < len(dets) else None),
                           ensure_ascii=False, default=str,
                           separators=(",", ":")).encode("utf-8")
                for i, rec in enumerate(recs)
            ]
            body = b"[" + b",".join(parts) + b"]"
            name = f"{start // DETAIL_SHARD_SIZE:05d}.json.gz"
            _atomic_write_bytes(shard_dir / name,
                                _gzip.compress(body, compresslevel=9, mtime=0))
            written.add(name)
        # Purge shards from a LARGER previous board plus any orphaned .tmp. A
        # board that shrinks from 38,500 to 20,000 leaves shards 20..38 on disk
        # holding indices that no longer exist.
        for stale in shard_dir.iterdir():
            if stale.name not in written:
                try:
                    stale.unlink()
                except OSError:
                    pass
        return {
            "schema": DETAIL_SHARD_SCHEMA,
            "dir": DETAIL_SHARD_DIR,
            "size": DETAIL_SHARD_SIZE,   # records per shard: index i -> i // size
            "count": len(written),       # number of shard files
            "records": len(payload),     # indices covered: must equal board.count
        }
    except Exception as exc:  # noqa: BLE001
        _rm_detail_shards(shard_dir)
        log.warning("web_artifact.detail_shards_failed", error=str(exc))
        return None


def _identity_keys(rec: dict):
    """Candidate cross-run identity keys for a published record.

    Used to carry a lead's prior sidecar detail (vision/comps/cama) across a
    FULL re-scrape, where index alignment is meaningless (order + count change
    every run).

    CAUTION — a key here is only a CANDIDATE, never trusted on its own. None of
    these is unique by construction: on the live board 652 source_urls are shared
    by 19,392 leads (one ArcGIS service URL alone is shared by 3,293, and county
    PDF rolls give every lead in the file the same URL), and 82 address+county
    pairs collide on placeholders like "0 no address assigned". Callers MUST
    discard any key claimed by more than one record — see _unique_key_map. An
    earlier version trusted source_url as "most unique" and handed one property's
    vision report to 985 unrelated leads.
    """
    keys: list[str] = []
    su = rec.get("source_url")
    if isinstance(su, str) and su.strip():
        keys.append("u:" + su.strip())
    pid = rec.get("parcel_id")
    if isinstance(pid, str) and pid.strip():
        keys.append("p:" + pid.strip().lower())
    addr = rec.get("street_address")
    cnty = rec.get("county")
    if isinstance(addr, str) and addr.strip() and isinstance(cnty, str) and cnty.strip():
        keys.append("a:" + addr.strip().lower() + "|" + cnty.strip().lower())
    return keys


def _load_prior_details_by_key(docs: Path) -> dict:
    """Map identity-key -> prior sidecar detail dict from the currently-published
    board, so write_artifact can preserve vision/comps/cama for leads that
    persist across runs but weren't re-enriched this run.

    Without this, a completed full run (which only re-visions a capped subset)
    writes details[i]={} for every un-re-visioned lead, WIPING the sidecar for
    the ~29k leads it didn't touch. Keyed by identity (not index) so it survives
    the reordering a full re-scrape produces. Returns {} if the board is absent
    or unreadable (fresh publish, or first run) — never raises.

    Reads through read_board_json, exactly like load_board at :59. It used to use
    plain .exists() + plain json.loads on the uncompressed twins ONLY, and both
    of those are gitignored (.gitignore:77-78) — only listings.json.gz and
    listings_detail.json.gz are committed. So on a fresh clone, a cloud/CI run or
    a disaster-recovery restore — the exact machines read_board_json's docstring
    was written for — this returned {} and the safety net silently disappeared.
    The next write_artifact would then publish details[i]={} for every lead it
    hadn't re-enriched, and since listings.json + listings_detail.json are
    TOGETHER the only full-fidelity board on disk, the next load_board would bake
    that loss in permanently. Silent, unattended, unrecoverable. Never narrow
    this back to the plain files.
    """
    lp = docs / "listings.json"
    dp = docs / "listings_detail.json"
    if not _board_file_present(lp) or not _board_file_present(dp):
        return {}
    try:
        recs = read_board_json(lp)
        dets = read_board_json(dp)
    except BoardIntegrityError:
        # NOT swallowed: an empty prior map would let this write publish
        # details[i] = {} for every lead it did not re-enrich, on top of a torn set.
        raise
    except Exception:  # noqa: BLE001
        return {}
    unique = _unique_key_map(recs)
    out: dict = {}
    for i, rec in enumerate(recs):
        if i >= len(dets):
            break
        d = dets[i]
        if not isinstance(d, dict) or not d or not isinstance(rec, dict):
            continue
        for key in _identity_keys(rec):
            if unique.get(key):
                out[key] = d
    return out


def _unique_key_map(recs: list) -> dict:
    """key -> True only when EXACTLY ONE record in `recs` claims it.

    An ambiguous key cannot identify a lead, so carrying detail across it hands
    one property's vision/comps report to every other lead behind the same key.
    Counting first (rather than first-wins) is what makes the backfill safe.
    """
    freq: dict = {}
    for rec in recs:
        if not isinstance(rec, dict):
            continue
        for key in _identity_keys(rec):
            freq[key] = freq.get(key, 0) + 1
    return {k: (n == 1) for k, n in freq.items()}


def _atomic_write_bytes(path: Path, data: bytes) -> None:
    """Write bytes atomically: a temp file in the same dir + os.replace, so a
    kill mid-write leaves the PRIOR file intact instead of a truncated,
    corrupt one. os.replace is atomic within a filesystem.

    The temp name carries the PID. It did not until 2026-08-11, and a shared
    "<name>.tmp" is not a private scratch file — it is a rendezvous point. Two
    concurrent writers were reproduced three times out of three: writer B
    reports success, writer A raises FileNotFoundError on os.replace, and A's
    bytes are what land on disk. The damage is not the crash; it is that the
    payload set ends up MIXED. Measured on a 25,000-record board, listings.json
    belonged to the crashed writer while the gz twin, the detail sidecar, slim
    and every shard belonged to the survivor. read_board_json prefers the .json
    over the .gz, so the next load_board() merged the survivor's sidecar into
    the loser's board BY INDEX — 25,000 of 25,000 leads carrying the neighbour's
    vision and comps, no exception raised, run_meta looking perfect.

    A per-process name does not prevent the race (see the flock in the job
    wrappers for that); it prevents two writers from silently swapping halves of
    the same publish."""
    tmp = path.with_name(f"{path.name}.{os.getpid()}.tmp")
    try:
        tmp.write_bytes(data)
        os.replace(tmp, path)
    except BaseException:
        try:
            tmp.unlink()
        except OSError:
            pass
        raise


def _slim_raw(raw: dict | None) -> dict:
    if not isinstance(raw, dict):
        return {}
    out: dict = {}
    for k, keep in RAW_KEEP.items():
        v = raw.get(k)
        if v is None:
            continue
        if keep == "*":
            out[k] = v
        elif isinstance(v, dict):
            out[k] = {sk: v[sk] for sk in keep if sk in v}
    return out


def _to_dict(li: Listing) -> dict:
    d = li.model_dump(mode="json", exclude_none=False)
    # Trim raw payload
    d["raw"] = _slim_raw(li.raw)
    # Null junk addresses in the PUBLISHED record so the dashboard/map don't
    # render a court-doc/lien placeholder ("Lis Pendens …", "Tract …", etc.)
    # as if it were a property. The listing is kept; raw is untouched.
    if not _is_valid_street_address(d.get("street_address")):
        d["street_address"] = None
    # Drop legal_description from public view (often huge)
    if "legal_description" in d and d["legal_description"]:
        d["legal_description"] = d["legal_description"][:200]
    # Stale-link safety net: for per-property aggregator leads (realtor/
    # zillow/trulia/homes.com/foreclosure.com) add reliable fallback links
    # (county GIS + Google + Maps) into raw and flag old carryover leads as
    # link_may_be_stale. NEVER touches source_url; never drops the lead.
    annotate_stale_links(d)
    return d


def _count_by(listings: list[Listing], attr: str) -> dict[str, int]:
    """Count the board being written by one Listing attribute, biggest first.

    Derived, never carried: these two run_meta keys are pure functions of the
    payload, so a stale one is a bug with no upside. See the by_state note in
    write_artifact.
    """
    counts: dict[str, int] = {}
    for li in listings:
        v = getattr(li, attr, None)
        v = str(v).strip() if v is not None else ""
        counts[v or "unknown"] = counts.get(v or "unknown", 0) + 1
    return dict(sorted(counts.items(), key=lambda kv: (-kv[1], kv[0])))


def _manifest_entry(path: Path, records: int | None = None) -> dict:
    ent = {"bytes": path.stat().st_size, "sha256": _sha256_file(path)}
    if records is not None:
        ent["records"] = records
    return ent


def _derive_parts_block(docs: Path, meta: dict | None) -> dict | None:
    """The parts block for whatever listings_part_NNN.json.gz files are on disk, or None when
    there are none (a legacy single-gz board). Sizes and sha256 come from the files themselves;
    each part's ROW COUNT comes from run_meta's board_parts when it names the same bytes and
    sha256, and is otherwise counted by streaming the part (a rebuild of a set nobody recorded)."""
    names = _bp.list_part_files(docs)
    if not names:
        return None
    known: dict = {}
    try:
        for e in _bp.normalize_entries((meta or {}).get("board_parts") or {}):
            known[e["name"]] = e
    except BoardIntegrityError:
        known = {}
    entries = []
    row = 0
    for i, fp in enumerate(names):
        if _bp.part_index(fp.name) != i:
            raise BoardIntegrityError(f"board parts are not contiguous: expected {_bp.part_name(i)}, "
                                      f"found {fp.name}")
        size = fp.stat().st_size
        sha = _sha256_file(fp)
        k = known.get(fp.name)
        if k and k["bytes"] == size and k["sha256"] == sha:
            n = k["records"]
        else:
            n = sum(1 for _ in _bp.iter_gz_rows(fp))
        entries.append({"name": fp.name, "start": row, "end": row + n, "records": n,
                        "bytes": size, "sha256": sha})
        row += n
    rpp = ((meta or {}).get("board_parts") or {}).get("rows_per_part")
    return _bp.make_block(entries, rows_per_part=rpp)


def build_manifest(docs: Path | str, precomputed: dict | None = None,
                   meta: dict | None = None, slim_count: int | None = None,
                   shard_meta: dict | None = None, parts_block: dict | None = None) -> dict:
    """Manifest for whatever payload files are on disk right now.

    `precomputed` maps a file name to an entry already known (write_artifact hashes
    the big files from memory instead of re-reading them). Everything else is hashed from
    disk. run_meta.json is included, so a tool that edits it must go through write_manifest
    again (scripts/board_manifest.py --rebuild does).

    The board itself is described by the "parts" block (audit O1): one entry per
    listings_part_NNN.json.gz with size, sha256 and its row range, mirrored under "files" so
    every file the manifest names is checked the same way. A board with no part files on disk
    (the legacy single-gz layout) lists listings.json.gz instead."""
    docs = Path(docs)
    pre = precomputed or {}
    files: dict = {}
    if parts_block is None:
        parts_block = _derive_parts_block(docs, meta)
    names = ["listings.json", "listings_detail.json", "listings_detail.json.gz",
             "listings_slim.json", "listings_slim.json.gz", "run_meta.json"]
    if parts_block is None:
        names.insert(2, "listings.json.gz")
    for name in names:
        if name in pre:
            files[name] = pre[name]
            continue
        fp = docs / name
        if not fp.is_file():
            continue
        recs = slim_count if name.startswith("listings_slim") else None
        files[name] = _manifest_entry(fp, recs)
    if parts_block is not None:
        for e in parts_block["files"]:
            files[e["name"]] = {"bytes": e["bytes"], "sha256": e["sha256"], "records": e["records"],
                                "start": e["start"], "end": e["end"]}
    sd = docs / DETAIL_SHARD_DIR
    if sd.is_dir():
        for fp in sorted(sd.iterdir()):
            if fp.is_file() and not fp.name.endswith(".tmp"):
                files[f"{DETAIL_SHARD_DIR}/{fp.name}"] = _manifest_entry(fp)
    count = (files.get("listings.json") or files.get("listings.json.gz") or {}).get("records")
    if count is None and parts_block is not None:
        count = parts_block["records"]
    man = {
        "schema": MANIFEST_SCHEMA,
        "written_at": datetime.utcnow().isoformat() + "Z",
        "run_time": (meta or {}).get("run_time"),
        "count": count,
        "detail_count": (files.get("listings_detail.json") or {}).get("records"),
        "slim_count": slim_count,
        "shards": shard_meta,
        "files": files,
    }
    if parts_block is not None:
        man["parts"] = parts_block
    return man


def write_manifest(docs: Path | str, precomputed: dict | None = None,
                   meta: dict | None = None, slim_count: int | None = None,
                   shard_meta: dict | None = None, parts_block: dict | None = None) -> Path:
    docs = Path(docs)
    man = build_manifest(docs, precomputed, meta, slim_count, shard_meta, parts_block)
    mp = docs / MANIFEST_NAME
    _atomic_write_bytes(mp, json.dumps(man, indent=1, sort_keys=False).encode("utf-8"))
    return mp


def verify_manifest(docs: Path | str, full: bool = True) -> dict:
    """Check every file the manifest names. Returns {"ok", "checked", "problems"}.
    `full` hashes each file; otherwise only size is compared. Used by
    scripts/board_manifest.py --verify and the restore script; never raises.

    For a parts board it also reports part files the manifest does not list (a stale
    higher-numbered part) and a parts total that disagrees with the manifest's count, and it
    checks that run_meta.json's board_parts is the same list as the manifest's."""
    docs = Path(docs)
    mp = docs / MANIFEST_NAME
    try:
        man = json.loads(mp.read_text())
    except (OSError, ValueError) as exc:
        return {"ok": False, "checked": 0, "problems": [f"manifest unreadable: {exc}"]}
    problems: list[str] = []
    checked = 0
    for name, ent in (man.get("files") or {}).items():
        fp = docs / name
        if not fp.is_file():
            # The plain twins are gitignored: a fresh clone legitimately lacks them.
            if name in ("listings.json", "listings_detail.json", "listings_slim.json"):
                continue
            problems.append(f"{name}: missing")
            continue
        checked += 1
        try:
            size = fp.stat().st_size
            if ent.get("bytes") is not None and size != ent["bytes"]:
                problems.append(f"{name}: size {size} != manifest {ent['bytes']}")
                continue
            if full and ent.get("sha256") and _sha256_file(fp) != ent["sha256"]:
                problems.append(f"{name}: sha256 mismatch")
        except OSError as exc:
            problems.append(f"{name}: {exc}")
    blk = _bp.manifest_parts_block(man)
    if blk is not None:
        try:
            entries = _bp.normalize_entries(blk)
        except BoardIntegrityError as exc:
            problems.append(f"parts block: {exc}")
            entries = []
        extra = _bp.stray_parts(docs, entries)
        if extra:
            problems.append("part file(s) on disk that the manifest does not list: " + ", ".join(extra[:4]))
        if entries and man.get("count") is not None and man["count"] != entries[-1]["end"]:
            problems.append(f"manifest count {man['count']} != parts total {entries[-1]['end']}")
        try:
            rm = json.loads((docs / "run_meta.json").read_text())
            rb = rm.get("board_parts") if isinstance(rm, dict) else None
        except (OSError, ValueError):
            rb = None
        if entries and rb is not None:
            try:
                same = [(e["name"], e["bytes"], e["sha256"]) for e in _bp.normalize_entries(rb)] == \
                       [(e["name"], e["bytes"], e["sha256"]) for e in entries]
            except BoardIntegrityError:
                same = False
            if not same:
                problems.append("run_meta.json board_parts is not the manifest's part list "
                                "(the dashboard would read a different set than the loaders)")
    return {"ok": not problems, "checked": checked, "problems": problems,
            "count": man.get("count"), "written_at": man.get("written_at")}


def _write_plain_array(path: Path, blobs: list) -> dict:
    """Write `[blob0, blob1, ...]` (the same bytes json.dumps of the list produces) to `path`
    atomically, hashing as it goes. Returns {"bytes", "sha256"}. Streams the rows to a temp
    file instead of joining them, so the 1.1 GB document is never one bytes object."""
    tmp = path.with_name(f"{path.name}.{os.getpid()}.tmp")
    h = hashlib.sha256()
    n = 0
    try:
        with open(tmp, "wb") as fh:
            def put(b: bytes) -> None:
                nonlocal n
                fh.write(b)
                h.update(b)
                n += len(b)
            put(b"[")
            for i, b in enumerate(blobs):
                if i:
                    put(b", ")
                put(b)
            put(b"]")
        os.replace(tmp, path)
    except BaseException:
        try:
            tmp.unlink()
        except OSError:
            pass
        raise
    return {"bytes": n, "sha256": h.hexdigest()}


def _seal_precompute(docs: Path, meta: dict, block: dict | None) -> dict:
    """Manifest entries for the big files that are hashed from disk: the plain twins, the detail
    sidecar and (legacy layout only) the single listings.json.gz. Slow (1.1 GB of sha256), so
    callers that must keep the window between "parts in place" and "manifest written" short
    (scripts/migrate_board_to_parts.py) compute it FIRST and pass it to reseal_board."""
    total = block["records"] if block is not None else meta.get("total")
    dcount = meta.get("detail_count", total)
    pre: dict = {}
    for name, recs in (("listings.json", total), ("listings_detail.json", dcount),
                       ("listings_detail.json.gz", dcount)) + \
                      ((("listings.json.gz", total),) if block is None else ()):
        fp = docs / name
        if fp.is_file():
            pre[name] = {"bytes": fp.stat().st_size, "sha256": _sha256_file(fp), "records": recs}
    return pre


def reseal_board(docs_dir: Path | str = "docs", *, resplit: bool = False,
                 source: Path | str | None = None, precomputed: dict | None = None) -> dict:
    """Bring run_meta.json's board_parts and the manifest into line with the board files on
    disk, WITHOUT load_board and without validating or rewriting any row.

    resplit=False   the parts on disk are right (restored by hand, a manifest that went stale):
                    hash them, take their row counts from run_meta.board_parts when it names the
                    same bytes (else count by streaming), and reseal.
    resplit=True    re-cut the parts from `source` (default docs/listings.json, the local working
                    copy a direct writer just rewrote), streaming it row by row, then reseal. This
                    is what the one-shot scripts that write listings.json themselves
                    (enrich_zip_codes.py, flood_zone_batch.py, ...) call instead of gzipping the
                    old single listings.json.gz, and what scripts/migrate_board_to_parts.py calls
                    with source=docs/listings.json.gz.

    Does not take the board lock: the caller owns the load -> mutate -> write span (run it under
    scripts/with_board_lock.sh). Returns the parts block."""
    docs = Path(docs_dir)
    meta_path = docs / "run_meta.json"
    try:
        meta = json.loads(meta_path.read_text())
    except (OSError, ValueError):
        meta = {}
    if not isinstance(meta, dict):
        meta = {}
    plain = docs / "listings.json"
    if resplit:
        src = Path(source) if source is not None else plain
        if not src.is_file():
            raise FileNotFoundError(f"cannot re-cut the board parts: {src} does not exist")
        hint = ((_bp.manifest_parts_block(_bp.read_manifest(docs)) or meta.get("board_parts") or {})
                .get("rows_per_part"))
        res = _bp.write_parts(docs, _bp.iter_row_texts(src), hint_rows=hint)
        block = _bp.make_block(res["entries"], rows_per_part=res["rows_per_part"], cap=res["cap"])
    else:
        block = _derive_parts_block(docs, meta)
    if block is not None and meta.get("board_parts") != block:
        meta["board_parts"] = block
        _atomic_write_bytes(meta_path, json.dumps(meta, ensure_ascii=False, default=str, indent=2).encode("utf-8"))
    pre = precomputed if precomputed is not None else _seal_precompute(docs, meta, block)
    board = meta.get("board") or {}
    write_manifest(docs, pre, meta, slim_count=board.get("count"),
                   shard_meta=board.get("detail_shards"), parts_block=block)
    return block or {}


# Rolling pre-write backups kept per pattern (main board + detail sidecar). Each
# main copy is ~1.04GB, so 10 of them was 12GB of a laptop that needed 50-80GB
# back (2026-09-19). Every committed board is also in git history and the live
# board is the newest state; 3 still covers the "a bad write just landed" case
# the backup exists for. Override with BOARD_BACKUP_KEEP.
_BACKUP_KEEP = max(1, int(os.environ.get("BOARD_BACKUP_KEEP", "3")))


def _backup_listings_board(listings_path: Path, backup_dir: Path, ts: str) -> Path:
    """Copy whatever on-disk representation of docs/listings.json currently exists into
    backup_dir, tagged with timestamp `ts`, WITHOUT ever parsing/materializing the board into
    memory -- that would turn a cheap file copy into a ~1GB-in-RAM operation on the Mac's 8GB
    budget (see _BACKUP_KEEP's comment on why even keeping a few whole-board copies on disk is
    already tight).

    docs/listings.json has three possible on-disk shapes, all already understood by the READ
    side (_choose_board_source, which this reuses rather than re-deriving source selection):
      - "plain"  docs/listings.json itself (the local runner regenerates this every write).
      - "gz"     docs/listings.json.gz, a single-file compressed twin (the pre-split layout).
      - "parts"  docs/listings_part_NNN.json.gz shards named by docs/board.manifest.json --
                 the current layout, because the uncompressed board (~1GB+) exceeds GitHub's
                 100MB/file limit even gzipped as one file. THIS is the shape a fresh
                 `git clone` produces: plain and single-gz are both gitignored/uncommitted
                 (see .gitignore), so only the manifest + parts exist until something writes a
                 fresh plain copy locally.

    Returns the path the backup landed at: a file for "plain"/"gz", a directory for "parts".

    Fixes the 2026-09-30 VM finding: the old code here did a bare
    `shutil.copy2(listings_path, ...)`, which only ever succeeds for the "plain" shape. On a
    fresh VM clone (parts only, no plain, no single .gz) it raised FileNotFoundError, which the
    caller's `except Exception: log.warning(...)` swallows -- so every write against a freshly
    cloned working tree ran with NO real backup, silently, while looking identical in the logs
    to a normal successful backup (a `web_artifact.backup_failed` warning line is easy to miss
    among the rest of a run's output). A real vision-grading write on the VM that day hit
    exactly this.
    """
    used, role, res = _choose_board_source(listings_path)
    if role == "plain":
        dest = backup_dir / f"listings_{ts}.json"
        shutil.copy2(used, dest)
        return dest
    if role == "gz":
        dest = backup_dir / f"listings_{ts}.json.gz"
        shutil.copy2(used, dest)
        return dest
    # role == "parts": the shard set is already small, gzip-compressed files on disk -- copying
    # all of them (manifest + every part) is still a cheap set of file copies, never a parse.
    # Kept together in their own timestamped directory so a restore just points board_parts at
    # it (it is a self-contained docs/ dir: manifest + parts, same layout board_parts.resolve()
    # expects).
    dest_dir = backup_dir / f"listings_{ts}_parts"
    dest_dir.mkdir(parents=True, exist_ok=True)
    manifest_path = listings_path.parent / _bp.MANIFEST_NAME
    if manifest_path.exists():
        shutil.copy2(manifest_path, dest_dir / _bp.MANIFEST_NAME)
    parts = res.paths if res is not None else _bp.list_part_files(listings_path.parent)
    for part in parts:
        shutil.copy2(part, dest_dir / part.name)
    return dest_dir


def _count_guard_and_backup(docs: Path, listings_path: Path, new_count: int, summary: dict) -> int:
    """BACKUP-BEFORE-OVERWRITE + COUNT GUARD, extracted from write_artifact (2026-09-29) so
    append_new_rows() can share this exact, incident-hardened logic instead of re-implementing
    it against a different row-count source and risking a subtly different bug. Pure extraction:
    same behavior, `new_count` stands in for what was `len(payload)`. See write_artifact's
    history for the two real data-loss incidents (#16, #22, the 72K-dropped-silently case) this
    guards against.

    Two data-loss events happened because a script wrote a smaller board (scope filter dropped
    16K+ leads) and the prior data was gone -- _atomic_write_bytes replaces the file, so the old
    content is lost.

    This does TWO things before any write:
      1. COUNT GUARD -- if the new board is >10% smaller than the existing board AND the caller
         didn't set BOARD_ALLOW_SHRINK, it RAISES. This catches the exact bug that killed
         53K->37K: a script calling write_artifact with a filtered subset. The caller must
         either fix their data or explicitly opt in with BOARD_ALLOW_SHRINK=1.
      2. TIMESTAMPED BACKUP -- copies the existing listings.json + detail to backups/ with a
         timestamp, so even if the guard is bypassed, the prior board is recoverable. Keeps the
         last _BACKUP_KEEP backups.

    Returns the accepted intentional-shrink allowance (0 when no board existed yet, or none was
    claimed), which the caller's high-water-mark update needs to REBASE correctly.
    """
    _backup_dir = docs.parent / "backups"
    _backup_dir.mkdir(parents=True, exist_ok=True)
    # Set unconditionally: the high-water block below reads it, and on a first run
    # (no board file yet) the guard block never executes.
    _accepted_intentional = 0
    if _board_file_present(listings_path):
        # --- count guard (high-water mark) ---
        # Bug fix: the old guard compared against the current on-disk board.
        # Once a bad 22K run published, the guard's baseline became 22K — so
        # the NEXT 22K run looked flat and passed. The guard measured
        # run-over-run drift, not drift from the true high-water mark, so it
        # structurally could not catch a drop that already landed.
        #
        # Fix: compare against a persisted high-water mark
        # (board_highwater.json), not the last board. A poisoned baseline
        # can no longer hide the drop.
        _highwater_path = docs / "board_highwater.json"
        _highwater_count = None
        try:
            if _highwater_path.exists():
                _hw = json.loads(_highwater_path.read_text())
                _highwater_count = _hw.get("count")
        except Exception:  # noqa: BLE001
            pass
        # Fallback to on-disk board if no high-water mark exists (first run)
        if _highwater_count is None:
            try:
                _prior_data = read_board_json(listings_path)
                _highwater_count = len(_prior_data) if isinstance(_prior_data, list) else None
            except Exception:  # noqa: BLE001
                pass
        # Rows the run removed ON PURPOSE because they are not in the buy box
        # (resolved to an off-footprint county; national/REO rows that never
        # resolved to one) are not shrink. The guard exists to catch a source
        # dying silently or a script writing a filtered subset -- it must compare
        # like with like, or a correct cleanup reads as a catastrophe.
        #
        # This is not hypothetical. On 2026-09-08 a 15h run scraped fine, merged
        # to 80,789, then scope_repass correctly dropped 30,509 off-footprint
        # rows (mostly statewide-NC LiensNC construction filings whose real
        # county only resolves during enrichment). Final board 39,088 vs a
        # high-water of 94,384 that had been set while those very rows were still
        # unresolved -> 59% "shrink" -> write refused, dashboard not published.
        # Because the mark only ever moves UP, that was permanent: every honest
        # run afterwards hit the same wall and the board stayed frozen on a stale
        # count inflated by rows that were never in the footprint.
        _intentional = 0
        try:
            _intentional = max(0, int(summary.get("off_footprint_removed") or 0))
        except (TypeError, ValueError):
            _intentional = 0
        # Never let the allowance swallow the whole baseline -- a run claiming it
        # meant to remove everything is exactly the bug this guard is for.
        _intentional = min(_intentional, int(_highwater_count * 0.6)) if _highwater_count else 0
        _effective_baseline = max(1, (_highwater_count or 0) - _intentional)

        if _highwater_count is not None and new_count < _effective_baseline:
            _shrink_pct = (1 - new_count / _effective_baseline) * 100
            _allow = os.environ.get("BOARD_ALLOW_SHRINK", "").strip()
            if _shrink_pct > 10 and _allow not in ("1", "true", "yes"):
                raise RuntimeError(
                    f"COUNT GUARD: refusing to write {new_count:,} listings "
                    f"over high-water mark {_highwater_count:,} "
                    f"(effective baseline {_effective_baseline:,} after "
                    f"{_intentional:,} intentional off-footprint removals; "
                    f"{_shrink_pct:.1f}% unexplained shrink). "
                    f"This has happened before (72K dropped silently). If this "
                    f"shrink is intentional, set BOARD_ALLOW_SHRINK=1."
                )
        # Remember the accepted allowance so the high-water update below can
        # REBASE rather than keep a baseline that describes a different
        # population than the one we now publish.
        _accepted_intentional = _intentional
        # --- timestamped backup ---
        _ts = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
        try:
            _dest = _backup_listings_board(listings_path, _backup_dir, _ts)
            if (docs / "listings_detail.json").exists():
                shutil.copy2(docs / "listings_detail.json",
                             _backup_dir / f"listings_detail_{_ts}.json")
            elif (docs / "listings_detail.json.gz").exists():
                shutil.copy2(docs / "listings_detail.json.gz",
                             _backup_dir / f"listings_detail_{_ts}.json.gz")
            log.info("web_artifact.backup_saved", path=str(_dest))
        except Exception:  # noqa: BLE001 - backup failure must not block the write
            log.warning("web_artifact.backup_failed", exc_info=True)
        # --- prune old backups (keep the newest _BACKUP_KEEP of each) ---
        # Bug found 2026-09-17: the sibling-cleanup below rsplit() the main
        # file's stem on "_" to derive a prefix meant to also catch its
        # listings_detail_<ts>.json(.gz) pair, but "listings_<ts>".rsplit("_",1)[0]
        # produces "listings_<date>" -- a prefix that never matches
        # "listings_detail_..." (detail comes right after "listings_", not
        # after the date). listings_2*.json (main) pruned fine at 10 files;
        # listings_detail_2*.json never matched ANY prune glob and grew
        # unbounded -- 214 files / 24GB found live, which drove the disk to
        # 0 bytes free mid-backfill (tee errors, real corruption risk on the
        # next atomic write). Prune both patterns independently by their own
        # recency now, instead of relying on one glob's leftovers to also
        # catch the other's files.
        #
        # 2026-09-30: added a third pattern for the "parts" backup shape (a
        # directory, not a file -- _backup_listings_board's fresh-clone fix) so
        # those don't grow unbounded the same way the 2026-09-17 bug let the
        # detail pattern grow: _BACKUP_KEEP directories of small gzipped shards
        # is still bounded, but ungoverned growth on an always-fresh-clone host
        # (the VM) would otherwise repeat that incident.
        try:
            for _pattern in ("listings_2*.json*", "listings_detail_2*.json*"):
                _old = sorted(_backup_dir.glob(_pattern),
                              key=lambda p: p.stat().st_mtime, reverse=True)[_BACKUP_KEEP:]
                for _f in _old:
                    _f.unlink(missing_ok=True)
            _old_dirs = sorted(_backup_dir.glob("listings_2*_parts"),
                               key=lambda p: p.stat().st_mtime, reverse=True)[_BACKUP_KEEP:]
            for _d in _old_dirs:
                shutil.rmtree(_d, ignore_errors=True)
        except Exception:  # noqa: BLE001
            pass
    return _accepted_intentional


def _apply_health_freshness(meta: dict, prior_meta: dict, summary: dict, now_iso: str,
                            now: datetime) -> None:
    """PRESERVE per-source health across partial writers, extracted from write_artifact
    (2026-09-29) so append_new_rows() -- which never computes its own source_status, being an
    additive-only landing rather than a scrape -- carries it forward the identical way instead
    of reimplementing the staleness math. Mutates `meta` in place.

    Fourteen maintenance scripts (sos_agent_refresh, lrcpwa_refresh, owner_mailing_refresh, the
    ingest_* family, ...) call write_artifact with a one-key summary like {"notes": "scheduled
    NC SOS refresh"}. Each one then blanked by_source / source_status / by_state, so
    run_meta.json - the ONLY per-source health report there is - showed "by_source": {} for days
    after a full run, and neither the operator nor a dashboard could answer "which sources are
    actually contributing". Carry the prior run's values forward when this writer did not
    compute its own, and mark the file so the staleness is visible rather than implied.

    THIS ONLY WORKS IF CALLERS STOP LAUNDERING THE PRIOR FILE BACK IN. health_carried_from is
    stamped only when a key is ABSENT from `meta`, i.e. only when THIS writer genuinely had
    nothing to say. Two callers used to read the prior run_meta.json themselves, strip `board`,
    and hand the rest back as their summary (recompute_valuation.py, patch_vision_gemini's
    _prior_meta) — so every key arrived already populated, the branch below never fired, and the
    published file asserted a months-old per-source health report as current. Both now pass only
    their own notes and let this function do the carrying, which produces the same values plus
    the label.

    by_state is NOT in this list: it is derived from the board being written, so there is never
    a stale value to carry.

    AUDIT O4 (2026-09-21): health_carried_from used to be the PRIOR WRITE's run_time, so it
    always looked minutes old while the per-source status it labelled was 23 days old (the last
    full run to compute it landed 8/29). Now:
      health_as_of         when THIS status was computed: stamped when the writer
                           computed its own source_status, otherwise carried
                           forward UNCHANGED from the first write that computed it
      health_carried_from  same instant (kept for existing readers)
      health_age_hours     now - health_as_of, so nobody has to do the subtraction
      health_stale         True when the age exceeds HEALTH_MAX_AGE_HOURS (48) or
                           the origin is unknown
    and once stale, source_status and errors are NULLED so a consumer sees "unknown" instead of
    a frozen green board. by_source and by_county_top keep being carried (they are counts,
    labelled by health_as_of).
    """
    _carried: list[str] = []
    _own_health = bool(summary.get("source_status"))
    for key in ("by_source", "by_county_top", "source_status", "regressions", "errors"):
        if not meta.get(key) and prior_meta.get(key):
            meta[key] = prior_meta[key]
            _carried.append(key)
    if _own_health:
        health_as_of = now_iso
    else:
        health_as_of = prior_meta.get("health_as_of") or os.environ.get("BOARD_HEALTH_AS_OF") or None
    if _carried:
        meta["health_carried_from"] = health_as_of
        meta["health_carried_keys"] = _carried
    meta["health_as_of"] = health_as_of
    age_h = None
    if health_as_of:
        try:
            _t = datetime.fromisoformat(str(health_as_of).replace("Z", "+00:00")).replace(tzinfo=None)
            age_h = round(max(0.0, (now - _t).total_seconds() / 3600.0), 2)
        except ValueError:
            age_h = None
    meta["health_age_hours"] = age_h
    _max_age = float(os.environ.get("HEALTH_MAX_AGE_HOURS", HEALTH_MAX_AGE_HOURS))
    meta["health_stale"] = bool(age_h is None or age_h > _max_age)
    if meta["health_stale"] and (meta.get("source_status") or meta.get("errors")):
        # Unknown origin counts as stale: on the live file this is what stops a
        # status frozen at 8/29 from posing as current at the first new write.
        meta["source_status"] = None
        meta["errors"] = None
        meta["health_nulled"] = ["source_status", "errors"]
    # Per-source last-success stamps (audit A2): freshness measured per SOURCE,
    # not by row last_seen (which a merge or an enrichment pass bumps).
    _ls = dict(prior_meta.get("source_last_success") or {})
    if _own_health:
        for slug, status in (summary.get("source_status") or {}).items():
            if isinstance(status, str) and status.startswith("OK"):
                _ls[slug] = now_iso
    _refreshed = summary.get("source_refreshed")
    if isinstance(_refreshed, dict):
        for slug, when in _refreshed.items():
            _ls[slug] = when if isinstance(when, str) and when else now_iso
    elif isinstance(_refreshed, (list, tuple, set)):
        for slug in _refreshed:
            _ls[str(slug)] = now_iso
    if _ls:
        meta["source_last_success"] = dict(sorted(_ls.items()))


class _ArrayFileWriter:
    """Stream `[row0<sep>row1<sep>...]` into a PID-named temp file next to `path`, hashing as it
    goes; nothing at `path` changes until commit(). Same bytes as joining the rows in memory
    (and, with sep b", ", as json.dumps of the list: what _write_plain_array/json.dumps wrote)."""

    def __init__(self, path: Path, sep: bytes = b", "):
        self.path = path
        self.tmp = path.with_name(f"{path.name}.{os.getpid()}.tmp")
        self.sep = sep
        self._fh = open(self.tmp, "wb")
        self._h = hashlib.sha256()
        self.nbytes = 0
        self.rows = 0
        self._put(b"[")

    def _put(self, b: bytes) -> None:
        self._fh.write(b)
        self._h.update(b)
        self.nbytes += len(b)

    def add(self, blob: bytes) -> None:
        if self.rows:
            self._put(self.sep)
        self._put(blob)
        self.rows += 1

    def finish(self) -> dict:
        """Close the array; returns {"bytes", "sha256"} of the finished file."""
        self._put(b"]")
        self._fh.close()
        return {"bytes": self.nbytes, "sha256": self._h.hexdigest()}

    def commit(self) -> None:
        os.replace(self.tmp, self.path)

    def abort(self) -> None:
        try:
            self._fh.close()
        except Exception:  # noqa: BLE001
            pass
        try:
            self.tmp.unlink()
        except OSError:
            pass


def _open_board_source_texts(p: Path) -> Iterator[str]:
    """Each row of a board JSON file as its exact source TEXT, with the same source selection
    as read_board_json (manifest-verified plain/gz; listings.json may be parts)."""
    used, role, res = _choose_board_source(p)
    if role == "parts":
        return (b.decode("utf-8") for part in res.paths for b in _bp.iter_row_texts(part))
    if role == "gz":
        return _bp.iter_gz_rows(used, want_text=True)
    return _bp.iter_plain_rows(used, want_text=True)


def _nonempty_dict_text(t: str) -> bool:
    """True when `t` is the JSON text of a dict with at least one key, without parsing it."""
    s = t.strip()
    return s.startswith("{") and bool(s[1:-1].strip())


def _prior_detail_index(docs: Path, wanted: dict) -> dict:
    """identity key -> prior sidecar detail (as its JSON TEXT), streamed.

    The same join as _load_prior_details_by_key -- a key qualifies only when exactly one prior
    row claims it (counted over every prior row, like _unique_key_map) and that row's sidecar
    entry is a non-empty dict -- restricted to the keys write_artifact can actually look up
    (`wanted`: the keys unique on the NEW board), and holding each detail as compact text rather
    than parsed objects. _load_prior_details_by_key read the whole prior board AND sidecar with
    read_board_json (2.5 GB of parsed rows on the 2026-10-05 VM board) to build that map; here
    one prior row and its sidecar entry are alive at a time. Same failure contract: a torn set
    raises BoardIntegrityError; anything else unreadable returns {} (fresh publish)."""
    lp = docs / "listings.json"
    dp = docs / "listings_detail.json"
    if not wanted or not _board_file_present(lp) or not _board_file_present(dp):
        return {}
    try:
        _used, rows = _open_board_source_rows(lp)
        dets = _open_board_source_texts(dp)
        freq: dict = {}
        held: list = []
        for rec in rows:
            d_text = next(dets, None)        # index-aligned, exactly like dets[i]
            if not isinstance(rec, dict):
                continue
            keys = _identity_keys(rec)
            for k in keys:
                freq[k] = freq.get(k, 0) + 1
            if d_text is not None and _nonempty_dict_text(d_text):
                ks = [k for k in keys if wanted.get(k)]
                if ks:
                    held.append((ks, d_text))
    except BoardIntegrityError:
        raise
    except Exception:  # noqa: BLE001
        return {}
    out: dict = {}
    for ks, t in held:
        for k in ks:
            if freq.get(k) == 1:
                out[k] = t
    return out


def write_artifact(
    listings: list[Listing],
    summary: dict,
    docs_dir: Path | str = "docs",
    *,
    no_prior_detail_rows: list[Listing] | tuple = (),
    no_prior_detail_keys: set[str] | frozenset = frozenset(),
) -> tuple[Path, Path]:
    """Write the whole payload set, then the manifest that seals it.

    Refuses (BoardLockNotHeld) unless the caller holds the board lock, and
    (BoardChangedSinceLoad) if listings.json is not the file this process loaded
    — see require_board_lock / _check_not_changed_since_load and audit O3.

    PRIOR-DETAIL EXCLUSIONS (2026-10-06, placeholder_twins.apply_collapse). The sidecar of a row
    in ``no_prior_detail_rows`` (Listing objects that must be in ``listings``) is exactly its own:
    the cross-run backfill from the prior board is skipped for it. A key in
    ``no_prior_detail_keys`` is never used to join a row to the prior board. The twin collapse
    passes its kept rows (the prior board's row for their parcel is the aged copy it refused)
    and its dropped copies' keys (dropping a copy can make a key unique that was not, and would
    join another row to the copy's prior detail). Both default to empty: nothing changes. A row
    that is not in ``listings`` raises ValueError before anything is written.

    MEMORY (rewritten 2026-10-05). The VM's 18h full run (270,232 rows) was OOM-killed one
    step short of this call: on top of the ~270K live Listings the publish tail held, in
    sequence, a full parsed copy of the prior board (mark_new_listings, the count-drop guard,
    and _load_prior_details_by_key here), then `payload` (a dict copy of every row), the
    serialized bytes of every row (`listing_blobs`, ~3 GB), the sidecar dicts and bytes, and
    the slim payload joined in memory twice. Now nothing proportional to the board is held
    beyond the Listings themselves:
      pass 1  one _to_dict per row, keeping only its identity keys (for the cross-run sidecar
              join, which must know which keys are unique on the NEW board before it can match);
      prior   _prior_detail_index streams the prior board + sidecar, keeping only the matching
              sidecar entries, as text;
      pass 2  one _to_dict per row again; the row is encoded ONCE and the bytes go straight to
              listings.json's temp file and to the parts writer (which cuts parts exactly where a
              full list would, from the same samples: board_parts.sample_groups_for), its
              sidecar entry to listings_detail.json's temp file, its slim projection to the slim
              temp file and its shard entry into the current 1,000-row shard (gzipped as each
              fills). Then the row is dropped.
    Every file is still written to a temp name and only renamed into place after every row has
    converted, so a failure mid-pass leaves the published set exactly as it was (as before,
    when nothing was written until `payload` was complete). The bytes are the same as the
    single-list version produced for the same input (tests/test_write_artifact_streaming.py
    holds that version verbatim and compares every output file).

    Why two _to_dict passes and not one: _to_dict -> annotate_stale_links setdefault()s keys
    into raw['fallback_links'] BY REFERENCE, so it can mutate an object a later row shares;
    the list version encoded only after every row had been converted, so pass 1 does all the
    conversions first and pass 2 encodes, giving the same bytes even then.
    """
    import gzip
    docs = Path(docs_dir)
    docs.mkdir(parents=True, exist_ok=True)

    listings_path = docs / "listings.json"
    meta_path = docs / "run_meta.json"

    # FIRST, before any expensive work and before a single byte is touched.
    require_board_lock(docs)
    _check_not_changed_since_load(listings_path)

    n = len(listings)

    def _row(li: Listing) -> tuple[dict, dict]:
        """(published record, its sidecar entry): _to_dict, then the heavy detail-panel-only
        raw keys (comps/vision/cama...) popped into the index-aligned sidecar the dashboard
        fetches lazily (detail[i] belongs to listing[i]). Popping happens LAST (after _to_dict /
        _slim_raw / annotate_stale_links) so nothing re-adds these keys."""
        rec = _to_dict(li)
        raw = rec.get("raw")
        d: dict = {}
        if isinstance(raw, dict):
            for k in LAZY_DETAIL_KEYS:
                if k in raw:
                    d[k] = raw.pop(k)
        return rec, d

    # One encoder for every board row: json.dumps over the whole list is exactly
    # "[" + ", ".join(rows) + "]" with this same encoder, so listings.json is byte-identical to
    # the single dumps it once was (audit O1: the parts cut the same rows, and need per-row
    # bytes to land on a row boundary).
    _row_enc = json.JSONEncoder(ensure_ascii=False, default=str)

    def _blob(rec: dict) -> bytes:
        return _row_enc.encode(rec).encode("utf-8")

    # PASS 1: identity keys of the board being written. A key can be unique in the prior board
    # yet ambiguous in what we are about to write (e.g. a re-scrape that pulled 3,293 leads
    # from one ArcGIS URL); carrying detail across it would fan one report out to all of them,
    # so only keys unique on BOTH sides are allowed to match.
    _key_freq: dict = {}
    _skip_rows = {id(li) for li in no_prior_detail_rows}
    _skip_found = 0
    for li in listings:
        _skip_found += id(li) in _skip_rows
        for key in _identity_keys(_to_dict(li)):
            _key_freq[key] = _key_freq.get(key, 0) + 1
    if _skip_found != len(_skip_rows):
        raise ValueError(f"write_artifact: {len(_skip_rows) - _skip_found} of {len(_skip_rows)} "
                         "no_prior_detail_rows are not on the board being written")
    payload_unique = {k: (c == 1 and k not in no_prior_detail_keys) for k, c in _key_freq.items()}
    _keys_withheld = {k for k, c in _key_freq.items() if c == 1 and k in no_prior_detail_keys}
    del _key_freq
    prior_withheld: collections.Counter = collections.Counter()

    # Prior sidecar, keyed by identity — lets a full re-scrape (which only re-visions a capped
    # subset) KEEP vision/comps/cama for the leads it didn't touch this run, instead of
    # overwriting details[i] with {}. Fresh detail from THIS run always wins; prior only
    # backfills missing keys.
    # (the withheld keys are looked up too, only so the log can count the joins they would make)
    prior = _prior_detail_index(docs, {**payload_unique, **dict.fromkeys(_keys_withheld, True)})
    if not prior:
        payload_unique = {}

    # BACKUP-BEFORE-OVERWRITE + COUNT GUARD (extracted to _count_guard_and_backup, shared with
    # append_new_rows -- see that function's docstring for the two real incidents it guards
    # against). Still before a single published byte changes: everything below writes temp
    # files until the commit step.
    _accepted_intentional = _count_guard_and_backup(docs, listings_path, n, summary)

    # The PUBLISHED form of the board: contiguous, independently gzipped parts, each under
    # board_parts.PART_MAX_BYTES (audit O1). The single docs/listings.json.gz is no longer
    # written: it was 84 MiB against GitHub's 100 MiB limit. A stale copy left by an older
    # version is not touched here and is ignored by every reader once the manifest lists parts.
    # mtime=0 keeps the gzip deterministic so identical rows produce identical bytes (no git
    # churn), and the row-per-part count is kept from write to write so a change confined to
    # some rows rewrites only the parts that hold them. Rows per part come from the same
    # contiguous samples a full list would give (only those <= 2,400 rows are encoded early).
    _prior_parts = _bp.manifest_parts_block(_bp.read_manifest(docs)) or {}
    _samples = _bp.sample_groups_for(n, lambda i: _blob(_row(listings[i])[0]))
    _sample_lookup = {i: b for r, g in zip(_bp.sample_index_groups(n), _samples) for i, b in zip(r, g)}

    _slim_on = os.getenv("FORECLOSURE_SLIM") != "0"      # emergency stop, see _emit_slim
    _shards_on = os.getenv("FORECLOSURE_DETAIL_SHARDS") != "0"
    slim_path = docs / "listings_slim.json"
    slim_gz_path = docs / "listings_slim.json.gz"
    detail_path = docs / "listings_detail.json"
    shard_dir = docs / DETAIL_SHARD_DIR

    plain_w: _ArrayFileWriter | None = None
    detail_w: _ArrayFileWriter | None = None
    slim_w: _ArrayFileWriter | None = None
    slim_err: Exception | None = None
    shard_gz: dict = {}          # name -> gzipped shard bytes, written after the board
    shard_err: Exception | None = None
    staged: list = []            # (final part path, staged temp path)
    sample_mismatch = 0

    def _stage_part(path: Path, data: bytes) -> None:
        tmp = path.with_name(f"{path.name}.{os.getpid()}.staged.tmp")
        staged.append((path, tmp))
        _bp.atomic_write_bytes(tmp, data)

    def _rows_for_parts():
        """Pass 2. Yields each row's bytes, in board order, to write_parts; writes everything
        else derived from the row as a side effect, then drops the row."""
        nonlocal slim_w, slim_err, shard_err, sample_mismatch
        shard_buf: list = []
        for i, li in enumerate(listings):
            rec, d = _row(li)
            if prior:
                pri_text = None
                for key in _identity_keys(rec):
                    if payload_unique.get(key) and key in prior:
                        pri_text = prior[key]
                        break
                if pri_text is None and _keys_withheld:
                    if any(k in _keys_withheld and k in prior for k in _identity_keys(rec)):
                        prior_withheld["rows_by_excluded_key"] += 1
                if pri_text and id(li) in _skip_rows:
                    pri = json.loads(pri_text)
                    if any(k not in d and k in pri for k in LAZY_DETAIL_KEYS):
                        prior_withheld["rows"] += 1
                        prior_withheld.update(f"withheld_{k}" for k in LAZY_DETAIL_KEYS
                                              if k not in d and k in pri)
                    pri_text = None
                if pri_text:
                    pri = json.loads(pri_text)
                    for k in LAZY_DETAIL_KEYS:
                        if k not in d and k in pri:
                            d[k] = pri[k]
            blob = _blob(rec)
            if i in _sample_lookup and blob != _sample_lookup[i]:
                sample_mismatch += 1
            plain_w.add(blob)
            detail_w.add(_row_enc.encode(d).encode("utf-8"))
            # Derivatives (SLIM-V1 + DETAIL SHARDS, see their blocks above): a failure here
            # costs the derivative, never the board. Projections are pure (never mutate rec).
            if _slim_on and slim_err is None:
                try:
                    if slim_w is None:
                        slim_w = _ArrayFileWriter(slim_path, sep=b",")
                    slim_w.add(json.dumps(_project_slim_record(rec), ensure_ascii=False, default=str,
                                          separators=(",", ":")).encode("utf-8"))
                except Exception as exc:  # noqa: BLE001
                    slim_err = exc
            if _slim_on and _shards_on and slim_err is None and shard_err is None:
                try:
                    shard_buf.append(json.dumps(_shard_record(rec, d), ensure_ascii=False,
                                                default=str, separators=(",", ":")).encode("utf-8"))
                    if len(shard_buf) == DETAIL_SHARD_SIZE or i == n - 1:
                        name = f"{(i // DETAIL_SHARD_SIZE):05d}.json.gz"
                        shard_gz[name] = gzip.compress(b"[" + b",".join(shard_buf) + b"]",
                                                       compresslevel=9, mtime=0)
                        shard_buf = []
                except Exception as exc:  # noqa: BLE001
                    shard_err = exc
                    shard_gz.clear()
            del rec, d
            yield blob

    try:
        plain_w = _ArrayFileWriter(listings_path)
        detail_w = _ArrayFileWriter(detail_path)
        _parts = _bp.write_parts(docs, _rows_for_parts(), hint_rows=_prior_parts.get("rows_per_part"),
                                 write=_stage_part, remove_stale=False, sample_groups=_samples)
        if plain_w.rows != n:
            raise RuntimeError(f"write_artifact: streamed {plain_w.rows} rows, expected {n}")
        _plain_ent = plain_w.finish()
        _detail_ent = detail_w.finish()
        if slim_w is not None and slim_err is None:
            slim_w.finish()
        elif _slim_on and slim_err is None and n == 0:
            slim_w = _ArrayFileWriter(slim_path, sep=b",")
            slim_w.finish()
    except BaseException:
        for w in (plain_w, detail_w, slim_w):
            if w is not None:
                w.abort()
        for _final, tmp in staged:
            try:
                tmp.unlink()
            except OSError:
                pass
        raise
    if sample_mismatch:
        # Cannot happen unless a row's conversion is not repeatable; the parts are still a
        # correct cut of the rows, only possibly a different one than a full list would give.
        log.warning("web_artifact.part_sample_drift", rows=sample_mismatch)

    # ---- COMMIT: every row converted; now replace the published files, in the old order.
    # Atomic renames (temp + os.replace) so a kill mid-write can never leave a truncated file —
    # the prior good file survives. git history is the rollback backup for a completed-but-bad
    # write (the count-drop guard flags those before publish).
    plain_w.commit()
    detail_w.commit()
    for final, tmp in staged:
        _bp.commit_staged_part(tmp, final)
    _bp.remove_stale_parts(docs, len(_parts["entries"]))
    _parts_block = _bp.make_block(_parts["entries"], rows_per_part=_parts["rows_per_part"],
                                  cap=_parts["cap"])
    # The manifest (written LAST) needs each big file's size and sha256: taken as the bytes
    # streamed out, never by re-reading 1.1 GB from disk.
    _manifest_pre: dict = {
        "listings.json": {**_plain_ent, "records": n},
        "listings_detail.json": {**_detail_ent, "records": n},
    }
    # Also emit a gzipped copy of the sidecar the dashboard fetches (16x smaller). The .json
    # files remain the local source-of-truth + a fallback. mtime=0 as above. (~250 MB read
    # back here, once, when nothing board-sized is held any more.)
    detail_gz = gzip.compress(detail_path.read_bytes(), compresslevel=9, mtime=0)
    _manifest_pre["listings_detail.json.gz"] = {"bytes": len(detail_gz),
                                                "sha256": hashlib.sha256(detail_gz).hexdigest(),
                                                "records": n}
    _atomic_write_bytes(docs / "listings_detail.json.gz", detail_gz)
    # Identity of the sidecar THIS call wrote — see the detail_count/
    # detail_digest note where run_meta is assembled. Deterministic (sha256 of
    # deterministic gzip bytes), so a republish of identical data does not churn.
    detail_digest = hashlib.sha256(detail_gz).hexdigest()[:16]
    del detail_gz

    # SLIM-V1, the mobile payload. Emitted only after the authoritative files are on disk:
    # nothing below this line can change listings.json's bytes, and a bug in the derivative
    # cannot cost a run its board. Same outcomes as _emit_slim: FORECLOSURE_SLIM=0 or a
    # projection failure DELETES the slim files (a stale slim file beside a fresh board is a
    # silently mis-joined board on a phone), otherwise both are replaced.
    _report_slim_drops(listings)   # loud about what slim leaves behind — see the docstring
    slim_count: int | None = None
    if _slim_on and slim_err is None and slim_w is not None:
        try:
            slim_w.commit()
            _atomic_write_bytes(slim_gz_path, gzip.compress(slim_path.read_bytes(),
                                                            compresslevel=9, mtime=0))
            slim_count = n
        except Exception as exc:  # noqa: BLE001
            slim_err = exc
    if slim_count is None:
        if slim_w is not None:
            slim_w.abort()
        for p in (slim_path, slim_gz_path):
            try:
                p.unlink(missing_ok=True)
            except OSError:
                pass
        if slim_err is not None:
            log.warning("web_artifact.slim_failed", error=str(slim_err))

    # DETAIL SHARDS, the mobile detail payload. Same outcomes as _emit_detail_shards: gated on
    # the slim emit having succeeded (the two are one mobile payload, advertised in one
    # metadata block); FORECLOSURE_DETAIL_SHARDS=0, an empty board or any failure REMOVES the
    # directory (index i is the join; shards from another write are mis-joined data).
    shard_meta: dict | None = None
    if slim_count is None or not _shards_on or n == 0 or shard_err is not None:
        _rm_detail_shards(shard_dir)
        if shard_err is not None and slim_count is not None:
            log.warning("web_artifact.detail_shards_failed", error=str(shard_err))
    else:
        try:
            shard_dir.mkdir(parents=True, exist_ok=True)
            for name in sorted(shard_gz):
                _atomic_write_bytes(shard_dir / name, shard_gz[name])
            # Purge shards from a LARGER previous board plus any orphaned .tmp.
            for stale in shard_dir.iterdir():
                if stale.name not in shard_gz:
                    try:
                        stale.unlink()
                    except OSError:
                        pass
            shard_meta = {
                "schema": DETAIL_SHARD_SCHEMA,
                "dir": DETAIL_SHARD_DIR,
                "size": DETAIL_SHARD_SIZE,   # records per shard: index i -> i // size
                "count": len(shard_gz),      # number of shard files
                "records": n,                # indices covered: must equal board.count
            }
        except Exception as exc:  # noqa: BLE001
            _rm_detail_shards(shard_dir)
            log.warning("web_artifact.detail_shards_failed", error=str(exc))
            shard_meta = None
    shard_gz.clear()

    _now = datetime.utcnow()
    _now_iso = _now.isoformat() + "Z"
    meta = {
        "run_time": _now_iso,
        "total": len(listings),
        "by_source": summary.get("by_source", {}),
        # by_state is DERIVED from the board being written, never taken from the
        # caller and never carried forward. It is a pure function of `listings`,
        # so there is no reason for it ever to disagree with the board — and it
        # did: the live file said NC 18,712 / SC 17,348, summing 36,060 against a
        # 38,500 board, while the real split was NC 20,654 / SC 17,846. 2,440
        # leads (6.3%) unaccounted for, on the only per-source health report
        # there is. A scrape-time count is not a description of what shipped.
        "by_state": _count_by(listings, "state"),
        # Same argument, for sources: this is what is ON the board right now,
        # which is the question run_meta exists to answer ("which sources are
        # actually contributing"). It is NOT `by_source`: that one is the
        # scrape-time per-scraper yield the full run computes (pre-dedup,
        # pre-scope-filter), it is carried forward by partial writers, and on
        # the live board it listed 85 sources summing 38,650 while omitting
        # reo.vrm_va_reo entirely. Both are useful; only one of them describes
        # the published board, and it is this one.
        "by_source_on_board": _count_by(listings, "source"),
        "by_county_top": summary.get("by_county_top", []),
        "source_status": summary.get("source_status", {}),
        "regressions": summary.get("regressions", []),
        "errors": summary.get("errors", []),
        "notes": summary.get("notes", ""),
        # THE DESKTOP DETAIL JOIN, declared. dashboard.js ensureDetails() merges
        # listings_detail.json into LISTINGS whenever details.length ===
        # LISTINGS.length — length equality with a payload that may itself be a
        # cached copy from another publish. The board has been exactly 38,500 for
        # four consecutive publishes, so that test proves nothing, and a
        # cross-publish sidecar Object.assigns one property's comps, vision and
        # CAMA onto a different property's address with no error.
        #
        # run_meta.json is fetched with `?t=${Date.now()}` (dashboard.js:681), so
        # it is the one payload that is ALWAYS current. These two keys are
        # therefore a fresh statement to check a possibly-cached sidecar against:
        #   detail_count  — len(listings_detail.json) as written by THIS call
        #   detail_digest — sha256 of listings_detail.json.gz's bytes, first 16
        #                   hex chars; changes whenever the sidecar's content
        #                   changes even if its length does not
        # Top level, NOT inside meta["board"]: tests/test_board_slim.py pins the
        # board block's key set to {schema, count, detail_shards}, and the block
        # is deliberately absent whenever the slim payload was not written, while
        # the desktop sidecar is written unconditionally.
        "detail_count": n,
        "detail_digest": detail_digest,
        # THE BOARD, AS PARTS (audit O1). The dashboard reads this list (same ?t=<run_time>
        # cache key as every payload file), fetches the parts in parallel and concatenates them
        # in order; each entry carries its row range, size and sha256. Top level for the same
        # reason as detail_count: the "board" block's key set is pinned by tests and describes
        # the slim payload only. Always describes the parts THIS call wrote.
        "board_parts": _parts_block,
    }
    # Board block: how the dashboard learns the slim payload exists and how many
    # records it must contain. run_meta.json is already in every publish list, so
    # this adds zero new entries to the five hardcoded ones. Absent whenever the
    # slim emit was skipped or failed — and it is NOT carried forward from the
    # prior meta by the health-preservation block below, which is the point: a
    # board block always describes the slim file written by THIS call.
    #
    # detail_shards is a SIBLING key, added without touching schema/count: the
    # client's boardExpectedCount() (dashboard.js:469) gates on board.schema ===
    # "slim-v1" and returns null for anything else, so renaming or re-shaping
    # the outer block would silently disable the record-count gate that stops a
    # short payload rendering as a whole board. It carries `size` so the client
    # derives shard index i // size instead of hardcoding 1000, and `records` so
    # a client that fetched a shard set from a different write can tell.
    if slim_count is not None:
        meta["board"] = {"schema": "slim-v1", "count": slim_count}
        if shard_meta is not None:
            meta["board"]["detail_shards"] = shard_meta

    # PRESERVE per-source health across partial writers (extracted to
    # _apply_health_freshness, shared with append_new_rows -- see its docstring).
    prior_meta: dict = {}
    if meta_path.exists():
        try:
            prior_meta = json.loads(meta_path.read_text())
        except Exception:  # noqa: BLE001 - a corrupt prior file must not block the write
            prior_meta = {}
        if not isinstance(prior_meta, dict):
            prior_meta = {}
    _apply_health_freshness(meta, prior_meta, summary, _now_iso, _now)
    _atomic_write_bytes(meta_path, json.dumps(meta, ensure_ascii=False, default=str, indent=2).encode("utf-8"))

    # --- update high-water mark ---
    # After a successful write, persist the new count as the high-water mark.
    # This is what the count guard above compares against next run. Only moves
    # UP (a smaller board never lowers the high-water mark — that's the point).
    try:
        _hw_path = docs / "board_highwater.json"
        _prev_hw = 0
        if _hw_path.exists():
            _prev_hw = json.loads(_hw_path.read_text()).get("count", 0)
        # Normally the mark only moves UP -- a smaller board must never lower the
        # bar the next run has to clear. The ONE exception is a shrink we just
        # accepted as an intentional buy-box correction: after removing rows that
        # were never in the footprint, the old mark describes a DIFFERENT
        # population, and leaving it in place deadlocks every future run (see the
        # 2026-09-08 note on the guard above). So rebase down by at most the
        # allowance we actually granted, never further.
        if len(listings) > _prev_hw:
            _atomic_write_bytes(_hw_path, json.dumps({
                "count": len(listings),
                "updated_at": datetime.utcnow().isoformat() + "Z",
            }, indent=2).encode("utf-8"))
            log.info("web_artifact.highwater_updated",
                     old=_prev_hw, new=len(listings))
        elif _accepted_intentional > 0 and len(listings) >= _prev_hw - _accepted_intentional:
            _atomic_write_bytes(_hw_path, json.dumps({
                "count": len(listings),
                "updated_at": datetime.utcnow().isoformat() + "Z",
                "rebased_from": _prev_hw,
                "reason": f"{_accepted_intentional:,} off-footprint rows removed",
            }, indent=2).encode("utf-8"))
            log.warning("web_artifact.highwater_rebased",
                        old=_prev_hw, new=len(listings),
                        off_footprint_removed=_accepted_intentional)
    except Exception:  # noqa: BLE001
        pass

    # THE MANIFEST, last. Everything above is on disk; this seals the set. A kill
    # before this line leaves a stale manifest that DISAGREES with the new files,
    # which is exactly the signal the next reader needs (BoardIntegrityError).
    try:
        write_manifest(docs, _manifest_pre, meta, slim_count=slim_count, shard_meta=shard_meta,
                       parts_block=_parts_block)
    except Exception:  # noqa: BLE001
        # A manifest we could not write must not pass for a current one.
        try:
            (docs / MANIFEST_NAME).unlink(missing_ok=True)
        except OSError:
            pass
        log.error("web_artifact.manifest_failed", exc_info=True)
    # The board on disk is now the one THIS process wrote: refresh the load stamp so
    # a second write in the same process is not mistaken for someone else's.
    # Only when this process had loaded before: a full re-scrape that never loaded has no
    # stamp, and inventing one would just add a check nobody asked for.
    if str(listings_path.resolve()) in _LOAD_STAMPS:
        _remember_load(docs, listings_path)

    if _skip_rows or no_prior_detail_keys:
        log.info("web_artifact.prior_detail_withheld", rows_excluded=len(_skip_rows),
                 keys_excluded=len(no_prior_detail_keys), **dict(prior_withheld))
    log.info("web_artifact.written", listings=len(listings), bytes=listings_path.stat().st_size)
    return listings_path, meta_path


# ===========================================================================
# append_new_rows: land a SMALL number of new rows without materializing the
# existing board (task_0658b33b, follow-up to audit O13). See
# BOARD_APPEND_MAX_SOURCE_MB's comment for the measurements this is based on.
# ===========================================================================

_APPEND_SIG_FIELDS = ("state", "county", "parcel_id", "street_address", "zip_code",
                     "case_number", "source_url", "listing_type")


def _append_row_sigs(li: Listing) -> set:
    """Same-property signatures for a Listing. Duplicates scripts/run_scoped_scrapers.py's
    _sigs_of()/board_overlap() exactly (not imported: scripts/ is a collection of entry points,
    not an importable package this library module should depend on -- the dependency would also
    point the wrong way). Keep the two in sync if dedupe.py's signature set changes."""
    from .dedupe import _strong_sigs
    out = set(_strong_sigs(li))
    try:
        out.add(("k", li.dedupe_key()))
    except Exception:  # noqa: BLE001
        pass
    return out


def _append_dict_sigs(row: dict) -> set:
    """Same signatures as _append_row_sigs, for a raw board row dict, WITHOUT validating it
    into a full Listing: a cheap Listing.model_construct() of just the identity fields (no
    pydantic validation, no type coercion) is enough for _strong_sigs()/dedupe_key(), which
    only ever read these fields. This is what lets append_new_rows() dedupe the small candidate
    set against the existing board while only ever streaming it -- the same trick
    board_overlap() already uses for the SAME purpose in the dry-run path."""
    light = Listing.model_construct(**{k: row.get(k) for k in _APPEND_SIG_FIELDS})
    return _append_row_sigs(light)


def append_new_rows(new_listings: list[Listing], summary: dict,
                    docs_dir: Path | str = "docs") -> dict:
    """Land a SMALL number of new, already-validated Listing objects onto the board WITHOUT
    fully re-validating or holding in memory the (potentially hundreds of thousands of)
    existing/untouched rows already on it.

    THE PROBLEM THIS SOLVES. The normal pattern -- load_board() (validates EVERY row into a
    Listing), mutate/append in Python, write_artifact() (re-serializes EVERY row) -- is exactly
    right for a full rescrape where every row genuinely might change and the whole thing is
    rewritten anyway. An in-place enrichment pass that re-tags EXISTING rows but only actually
    CHANGES a few of them (run_pending_signal_enrichers.py was this shape until its 2026-10-02
    migration -- docs/HANDOFF.md item 42 -- off load_board()/write_artifact() onto
    board_stream.iter_board_rows() + a pre/post snapshot diff + patch_existing_rows(), the same
    double-materialization fix run_tax_owed_normalize.py/backfill_derivation_flags.py/
    lrcpwa_refresh.py/_dq_common.run_apply() already got) is a better fit for patch_existing_rows()
    (below), not this function -- it is still the wrong tool for "scrape a handful of new listings,
    check they are not already on the board, add them"
    (scripts/run_scoped_scrapers.py --apply's real use case): the existing rows never need to
    be parsed into a mutable Listing, or even held as a parsed dict for the whole pass, at all.

    HOW. `new_listings` is the only thing this function ever validates -- and since callers
    already hold them as Listing objects (pydantic validated them at construction), that means
    nothing here re-validates anything; the "validation" already happened before this function
    was ever called. The existing board is streamed EXACTLY ONCE via _iter_board_records() (the
    incremental JSON-array decoder from audit O13's streaming fix -- never a whole-file
    json.loads(), never a whole-board list held in memory): each existing row is popped
    (LAZY_DETAIL_KEYS out of `raw`, mirroring write_artifact's own round-trip), immediately
    re-encoded to the exact JSON bytes it would have had, and then the parsed dict is dropped --
    at most one existing row's parsed dict is alive at a time, for however many hundreds of
    thousands there are. Only the already-serialized bytes (a list[bytes], not a list[dict] or
    list[Listing]) and the tiny popped detail dicts (usually {} — most rows have no
    vision/comps) accumulate for the whole pass.

    MEASURED (BOARD_APPEND_MAX_SOURCE_MB's comment has the numbers): discarding each row's
    parsed form immediately, rather than keeping ANY full-length list of parsed rows alive
    (dict or Listing), is what actually cuts the peak footprint -- to roughly HALF of either
    load_board()'s list[Listing] or a plain list[dict] materialization, on the same real board
    slices. Skipping Listing.model_validate() by itself was a much smaller win than expected.

    DEDUPE. Additive only: a candidate matching an existing row by any of dedupe.py's strong
    same-property signatures, or its own dedupe_key(), is skipped (reported in
    `skipped_by_source`), never appended, and the existing row it matched is never touched. The
    check is folded into the SAME streaming pass (a lightweight Listing.model_construct() of
    just the identity fields per existing row -- see _append_dict_sigs -- rather than a second
    read of the board).

    ADDITIVE-ONLY IS ENFORCED BY CONSTRUCTION, not by fingerprint-diffing before/after the way
    scripts/run_scoped_scrapers.py's old apply_rows() asserted it (it held all existing rows as
    Listing objects and hashed each one before and after, to catch a bug in ITS OWN merge step
    mutating one). Here, existing rows are streamed straight from disk into the rewritten board
    and never pass through caller code or become a mutable Python object anything else could
    reach -- there is no code path left that could silently modify one, so there is nothing to
    diff.

    WHAT THIS DELIBERATELY DOES NOT DO:
      * Does NOT regenerate the mobile SLIM/detail-shard payloads (listings_slim.json,
        detail_shards/). Those describe the board as of the last full write_artifact() call and
        are left untouched here (their manifest entries are re-hashed from disk unchanged,
        their run_meta.json `board` block is carried forward verbatim) -- regenerating them
        needs the parsed-dict form of the WHOLE board (see _emit_slim/_emit_detail_shards),
        which is exactly the cost this function exists to avoid. The desktop dashboard
        (listings.json + listings_detail.json, read directly) sees new rows immediately; the
        mobile payload catches up at the next full write_artifact() run. This is a known,
        disclosed gap: a caller that needs the mobile payload fresh immediately should keep
        using load_board()/write_artifact().
      * Does NOT backfill vision/comps/cama from a "prior" identity-keyed board the way
        write_artifact does for a full rescrape's reordered rows: new rows here are, by
        definition (they survived the dedupe check above), not already on the board under any
        identity key, so there is nothing to backfill from, and skipping the check avoids an
        extra full (non-streaming) read of the board that _load_prior_details_by_key would
        otherwise do.
      * Is gated by its OWN size ceiling, BOARD_APPEND_MAX_SOURCE_MB, separate from
        load_board()'s BOARD_LOAD_MAX_SOURCE_MB -- see that constant's comment for the measured
        numbers behind both and why they differ.

    Returns {existing, candidates, added, already_on_board, added_by_source, skipped_by_source,
    total_after, written} -- when new_listings is empty, {existing: None, candidates: 0,
    added: 0, already_on_board: 0, added_by_source: {}, skipped_by_source: {}, written: False,
    total_after: None} without touching the board at all (existing/total_after are None because
    nothing was scanned -- there was nothing to check them against).

    Refuses (BoardLockNotHeld) unless the caller holds the board lock, exactly like
    write_artifact(); refuses (BoardChangedSinceLoad) if listings.json changed since this
    process last loaded it; refuses (BoardLoadTooLarge) if the existing board is over
    BOARD_APPEND_MAX_SOURCE_MB (BOARD_APPEND_ALLOW_LARGE=1 overrides for one supervised run).
    """
    docs = Path(docs_dir)
    docs.mkdir(parents=True, exist_ok=True)
    listings_path = docs / "listings.json"

    require_board_lock(docs)
    _check_not_changed_since_load(listings_path)

    if not new_listings:
        return {"existing": None, "candidates": 0, "added": 0, "already_on_board": 0,
                "added_by_source": {}, "skipped_by_source": {}, "written": False,
                "total_after": None}

    _raise_if_board_too_large_to_append(docs)

    new_payload = [_to_dict(li) for li in new_listings]
    # Diagnostic only (never blocks a write): report on the NEW rows' raw keys, not the whole
    # board's -- the existing rows were already reported when THEY were first written, and
    # re-scanning all of them here would need exactly the full parsed-dict pass this function
    # exists to avoid.
    _report_slim_drops(new_listings)

    cand_sigs: dict = collections.defaultdict(list)
    for i, li in enumerate(new_listings):
        for sig in _append_row_sigs(li):
            cand_sigs[sig].append(i)
    hit: dict[int, str] = {}

    # --- ONE streaming pass over the existing board: dedupe-check + pop + encode + count ---
    # A board that does not exist yet at all (the very first write -- write_artifact() is
    # normally what bootstraps that, called directly with the full set; append_new_rows()
    # tolerates it too, rather than making "is there a board yet" the caller's problem) has
    # nothing to stream: skip straight to writing new_listings as the whole board.
    row_enc = json.JSONEncoder(ensure_ascii=False, default=str)
    listing_blobs: list[bytes] = []
    details: list[dict] = []
    by_state: collections.Counter = collections.Counter()
    by_source: collections.Counter = collections.Counter()
    existing_total = 0
    _existing_rows = _iter_board_records(docs) if _board_file_present(listings_path) else ()
    for rec in _existing_rows:
        existing_total += 1
        if cand_sigs and isinstance(rec, dict):
            src = str(rec.get("source") or "?")
            for sig in _append_dict_sigs(rec):
                for i in cand_sigs.get(sig, ()):
                    hit.setdefault(i, src)
        by_state[str(rec.get("state") or "").strip() or "unknown"] += 1
        by_source[str(rec.get("source") or "").strip() or "unknown"] += 1
        raw = rec.get("raw")
        d: dict = {}
        if isinstance(raw, dict):
            for k in LAZY_DETAIL_KEYS:
                if k in raw:
                    d[k] = raw.pop(k)
        details.append(d)
        listing_blobs.append(row_enc.encode(rec).encode("utf-8"))

    fresh_idx = [i for i in range(len(new_listings)) if i not in hit]
    skipped_by_source = collections.Counter(
        new_listings[i].source for i in range(len(new_listings)) if i in hit)
    added_by_source: collections.Counter = collections.Counter()
    for i in fresh_idx:
        rec = new_payload[i]
        added_by_source[new_listings[i].source] += 1
        by_state[str(rec.get("state") or "").strip() or "unknown"] += 1
        by_source[str(rec.get("source") or "").strip() or "unknown"] += 1
        raw = rec.get("raw")
        d = {}
        if isinstance(raw, dict):
            for k in LAZY_DETAIL_KEYS:
                if k in raw:
                    d[k] = raw.pop(k)
        details.append(d)
        listing_blobs.append(row_enc.encode(rec).encode("utf-8"))

    total = existing_total + len(fresh_idx)
    stats: dict = {
        "existing": existing_total, "candidates": len(new_listings), "added": len(fresh_idx),
        "already_on_board": len(hit), "written": False,
        "added_by_source": dict(added_by_source), "skipped_by_source": dict(skipped_by_source),
        "total_after": total,
    }
    if not fresh_idx:
        return stats

    # --- count guard + timestamped backup (shared with write_artifact) ---
    _accepted_intentional = _count_guard_and_backup(docs, listings_path, total, summary)

    # --- write listings.json + gzipped parts (the SAME low-level writers write_artifact uses) ---
    _manifest_pre: dict = {
        "listings.json": {**_write_plain_array(listings_path, listing_blobs), "records": total},
    }
    detail_path = docs / "listings_detail.json"
    detail_count = len(details)
    detail_bytes = json.dumps(details, ensure_ascii=False, default=str).encode("utf-8")
    del details
    _manifest_pre["listings_detail.json"] = {"bytes": len(detail_bytes),
                                             "sha256": hashlib.sha256(detail_bytes).hexdigest(),
                                             "records": detail_count}
    _atomic_write_bytes(detail_path, detail_bytes)
    _prior_parts = _bp.manifest_parts_block(_bp.read_manifest(docs)) or {}
    _parts = _bp.write_parts(docs, listing_blobs, hint_rows=_prior_parts.get("rows_per_part"))
    _parts_block = _bp.make_block(_parts["entries"], rows_per_part=_parts["rows_per_part"],
                                  cap=_parts["cap"])
    del listing_blobs
    import gzip
    detail_gz = gzip.compress(detail_bytes, compresslevel=9, mtime=0)
    _manifest_pre["listings_detail.json.gz"] = {"bytes": len(detail_gz),
                                                "sha256": hashlib.sha256(detail_gz).hexdigest(),
                                                "records": detail_count}
    _atomic_write_bytes(docs / "listings_detail.json.gz", detail_gz)
    detail_digest = hashlib.sha256(detail_gz).hexdigest()[:16]
    del detail_gz, detail_bytes

    # --- run_meta.json: same shape write_artifact writes, minus the fields that need the
    # slim/shard payload regenerated (which this function deliberately does not do) ---
    meta_path = docs / "run_meta.json"
    prior_meta: dict = {}
    if meta_path.exists():
        try:
            prior_meta = json.loads(meta_path.read_text())
        except Exception:  # noqa: BLE001 - a corrupt prior file must not block the write
            prior_meta = {}
        if not isinstance(prior_meta, dict):
            prior_meta = {}
    prior_board_block = prior_meta.get("board")
    if not isinstance(prior_board_block, dict):
        prior_board_block = None
    slim_count = prior_board_block.get("count") if prior_board_block else None
    shard_meta = prior_board_block.get("detail_shards") if prior_board_block else None

    _now = datetime.utcnow()
    _now_iso = _now.isoformat() + "Z"
    meta = dict(prior_meta)
    meta.update({
        "run_time": _now_iso,
        "total": total,
        "by_state": dict(sorted(by_state.items(), key=lambda kv: (-kv[1], kv[0]))),
        "by_source_on_board": dict(sorted(by_source.items(), key=lambda kv: (-kv[1], kv[0]))),
        "notes": summary.get("notes", prior_meta.get("notes", "")),
        "detail_count": detail_count,
        "detail_digest": detail_digest,
        "board_parts": _parts_block,
    })
    if summary.get("by_source"):
        meta["by_source"] = summary["by_source"]
    if prior_board_block is not None:
        # Unchanged by this call -- carried forward verbatim, not recomputed, since this
        # function never touches the slim/shard files (see the docstring above).
        meta["board"] = prior_board_block
    _apply_health_freshness(meta, prior_meta, summary, _now_iso, _now)
    _atomic_write_bytes(meta_path, json.dumps(meta, ensure_ascii=False, default=str, indent=2).encode("utf-8"))

    # --- update high-water mark (identical logic to write_artifact's) ---
    try:
        _hw_path = docs / "board_highwater.json"
        _prev_hw = 0
        if _hw_path.exists():
            _prev_hw = json.loads(_hw_path.read_text()).get("count", 0)
        if total > _prev_hw:
            _atomic_write_bytes(_hw_path, json.dumps({
                "count": total, "updated_at": _now_iso,
            }, indent=2).encode("utf-8"))
            log.info("web_artifact.highwater_updated", old=_prev_hw, new=total)
        elif _accepted_intentional > 0 and total >= _prev_hw - _accepted_intentional:
            _atomic_write_bytes(_hw_path, json.dumps({
                "count": total, "updated_at": _now_iso, "rebased_from": _prev_hw,
                "reason": f"{_accepted_intentional:,} off-footprint rows removed",
            }, indent=2).encode("utf-8"))
            log.warning("web_artifact.highwater_rebased", old=_prev_hw, new=total,
                        off_footprint_removed=_accepted_intentional)
    except Exception:  # noqa: BLE001
        pass

    # THE MANIFEST, last (same reasoning as write_artifact: everything above is on disk by now).
    try:
        write_manifest(docs, _manifest_pre, meta, slim_count=slim_count, shard_meta=shard_meta,
                       parts_block=_parts_block)
    except Exception:  # noqa: BLE001
        try:
            (docs / MANIFEST_NAME).unlink(missing_ok=True)
        except OSError:
            pass
        log.error("web_artifact.manifest_failed", exc_info=True)
    if str(listings_path.resolve()) in _LOAD_STAMPS:
        _remember_load(docs, listings_path)

    log.info("web_artifact.appended", existing=existing_total, added=len(fresh_idx), total=total,
             bytes=listings_path.stat().st_size)
    stats["written"] = True
    return stats


# ===========================================================================
# patch_existing_rows: mutate a SMALL, known subset of EXISTING rows in place,
# without materializing the board (follow-up to append_new_rows(), 2026-09-29).
# See BOARD_PATCH_MAX_SOURCE_MB's comment for the measurements this is based on.
# ===========================================================================

class BoardPatchCountMismatch(RuntimeError):
    """patch_existing_rows() refused: the number of rows streamed off the existing board did
    not match the board manifest's last-sealed record count for listings.json.

    patch_existing_rows() never adds or removes a row -- every row it streams in is re-emitted
    exactly once, patched or not -- so its row count is an INVARIANT, not merely an expectation
    with a tolerance. append_new_rows()/write_artifact() share one _count_guard_and_backup()
    that only refuses a shrink over 10% (right for a scrape, which legitimately adds or drops
    rows); a patch pass has no legitimate reason to see ANY difference at all, so this checks
    for EXACT equality against the manifest, strictly before anything is written. A real
    mismatch here means the on-disk board and its own manifest already disagree (a torn write,
    a hand-edited file) -- exactly the corruption verify_manifest()/board_manifest.py --verify
    exist to catch, just caught here too, before a patch pass could make it worse."""


def patch_existing_rows(patches: dict[str, dict], summary: dict,
                        docs_dir: Path | str = "docs") -> dict:
    """Mutate a SMALL, known set of EXISTING board rows in place -- set specific fields on the
    rows matching given identities -- WITHOUT materializing the (potentially hundreds of
    thousands of) other, untouched rows into Listing objects or even a full parsed-dict list,
    and without re-validating even the rows actually being touched.

    THE PROBLEM THIS SOLVES. append_new_rows() (above) solved "add a handful of NEW rows"
    without load_board()'s full materialization. It deliberately left a gap: a script that
    needs to MUTATE a small, known SUBSET of EXISTING rows -- not add, not remove -- still had
    no safe path, and had to fall back to load_board() -> mutate the Listing objects in Python
    -> write_artifact(), which is exactly the double materialization BOARD_LOAD_MAX_SOURCE_MB's
    ceiling now refuses on this board. scripts/resolver_backfill_parcel.py is the concrete
    case: each run resolves a parcel_id for roughly 1,000-1,500 leads (a point-in-polygon
    ArcGIS lookup, one Listing at a time) out of a 217,000+-row board, then needs to land just
    those onto the board -- it has no reason to touch, hold, or even parse the other 99.5%.

    HOW. `patches` maps Listing.dedupe_key() -- computed by the CALLER from each target row's
    PRE-patch identity fields (state/county/parcel_id/street_address/zip_code/case_number/
    source_url; see Listing.dedupe_key()) -- to the field updates to apply to that one row.
    dedupe_key() is deliberately the NARROW, single-valued identity here, not
    append_new_rows()'s/board_overlap()'s full _strong_sigs() union: those exist to catch
    LOOSE, fuzzy same-property matches across independently-scraped candidates (a new row from
    a different source, with no shared id, describing the same house) so a true duplicate is
    never added twice -- exactly the dedupe_key() fallback branch _append_row_sigs() itself
    adds (`("k", li.dedupe_key())`) for when no stronger signature exists. A patch, by
    contrast, is issued by a caller that already knows EXACTLY which board row it means (it
    read that row directly off the board to decide what to patch), so the precise, single
    dedupe_key() match is the SAFER choice here, not a compromise: it patches the row the
    caller meant, never some unrelated row that happens to share a looser fuzzy signature.

    The existing board is streamed EXACTLY ONCE via _iter_board_records() (the same
    incremental JSON-array decoder append_new_rows() uses -- never a whole-file json.loads(),
    never a whole-board list held in memory). For each row: its dedupe_key() is computed from
    a light Listing.model_construct() of just the identity fields (no pydantic validation, no
    type coercion -- append_new_rows()'s _append_dict_sigs() trick, reused via the same
    _APPEND_SIG_FIELDS); if it matches a pending patch, the patch's field updates are applied
    DIRECTLY to the raw dict -- never Listing.model_validate(), for either the patched rows or
    the untouched ones: patch values are already simple, well-typed JSON values the caller
    built (e.g. a parcel_id string, a small provenance dict), so there is nothing left for
    full-model validation to do that plain dict assignment does not. A `raw` update is MERGED
    into the row's existing raw dict rather than replacing it -- an existing row's raw commonly
    carries grade/calc/skip_trace/vision/comps/cama that a patch must never destroy. Every row
    -- patched or not -- then goes through the exact same lazy-detail pop + re-encode + discard
    append_new_rows() already uses, so at most one row's parsed dict is ever alive at a time,
    for however many hundreds of thousands there are.

    COUNT GUARD, STRICTER THAN append_new_rows()'s. A patch pass never adds or removes a row,
    so on top of the shared _count_guard_and_backup (kept here for its backup-before-overwrite
    side effect), this checks the streamed row count against the board manifest's own
    last-sealed record count for listings.json (when a manifest exists) and raises
    BoardPatchCountMismatch on ANY difference, before anything is written -- narrower than the
    10%-shrink tolerance append_new_rows()/write_artifact() apply, which is right for a scrape
    (legitimately adds/drops rows) but wrong for a pass whose entire contract is "same rows,
    some fields changed."

    WHAT THIS DELIBERATELY DOES NOT DO (same reasoning as append_new_rows(), see its
    docstring):
      * Does NOT regenerate listings_slim.json / detail_shards/ -- carried forward unchanged,
        the same disclosed gap append_new_rows() has.
      * Does NOT validate patch VALUES against the Listing schema -- a patch is a small,
        well-typed field update the caller already knows the shape of. A caller that needs
        full validation (e.g. it is not sure its values are well-typed) should use
        load_board()/write_artifact() instead.
      * A dedupe_key() matching MORE than one existing row (only possible if the board already
        has a duplicate under that key -- dedupe()'s own job is to prevent that) gets the SAME
        patch applied to every match, not just the first: the same identity is, by this
        codebase's own definition, the same property, so the same field update is correct for
        all of them. Counted in `duplicate_key_matches` for visibility; this should be rare
        and is never silent.

    Returns {existing, patches, matched, applied, not_found, duplicate_key_matches, written,
    total_after} -- when `patches` is empty, {existing: None, patches: 0, matched: 0,
    applied: 0, not_found: 0, duplicate_key_matches: 0, written: False, total_after: None}
    without touching the board at all. When the board has no rows to patch onto yet (no
    listings.json present), every patch is reported `not_found` and nothing is written --
    unlike append_new_rows(), a patch pass has no legitimate "first ever write" case, because
    there is nothing to MUTATE on a board that does not exist.

    Refuses (BoardLockNotHeld) unless the caller holds the board lock, exactly like
    write_artifact()/append_new_rows(); refuses (BoardChangedSinceLoad) if listings.json
    changed since this process last loaded it; refuses (BoardLoadTooLarge) if the existing
    board is over BOARD_PATCH_MAX_SOURCE_MB (BOARD_PATCH_ALLOW_LARGE=1 overrides for one
    supervised run); refuses (BoardPatchCountMismatch) if the streamed row count does not
    exactly match the manifest's last-sealed count.
    """
    docs = Path(docs_dir)
    docs.mkdir(parents=True, exist_ok=True)
    listings_path = docs / "listings.json"

    require_board_lock(docs)
    _check_not_changed_since_load(listings_path)

    if not patches:
        return {"existing": None, "patches": 0, "matched": 0, "applied": 0, "not_found": 0,
                "duplicate_key_matches": 0, "written": False, "total_after": None}

    _raise_if_board_too_large_to_patch(docs)

    if not _board_file_present(listings_path):
        # Nothing to patch onto. Unlike append_new_rows()'s bootstrap case (a fresh publish is
        # a legitimate first write), a patch with no board yet is a caller error: there is no
        # row to MUTATE, so every pending patch is unmatched by definition.
        return {"existing": 0, "patches": len(patches), "matched": 0, "applied": 0,
                "not_found": len(patches), "duplicate_key_matches": 0, "written": False,
                "total_after": 0}

    pending: dict = dict(patches)
    matched_keys: set = set()
    dup_keys: set = set()

    # --- ONE streaming pass over the existing board: identity-match + patch + pop + encode ---
    row_enc = json.JSONEncoder(ensure_ascii=False, default=str)
    listing_blobs: list[bytes] = []
    details: list[dict] = []
    by_state: collections.Counter = collections.Counter()
    by_source: collections.Counter = collections.Counter()
    existing_total = 0
    applied = 0
    for rec in _iter_board_records(docs):
        existing_total += 1
        if isinstance(rec, dict) and pending:
            light = Listing.model_construct(**{k: rec.get(k) for k in _APPEND_SIG_FIELDS})
            try:
                key = light.dedupe_key()
            except Exception:  # noqa: BLE001 - a row too malformed to key is simply unmatched
                key = None
            if key is not None and key in pending:
                if key in matched_keys:
                    dup_keys.add(key)
                matched_keys.add(key)
                update = pending[key]
                raw_update = update.get("raw")
                if isinstance(raw_update, dict):
                    raw = rec.get("raw")
                    if not isinstance(raw, dict):
                        raw = {}
                        rec["raw"] = raw
                    raw.update(raw_update)
                for field, value in update.items():
                    if field != "raw":
                        rec[field] = value
                applied += 1
        by_state[str(rec.get("state") or "").strip() or "unknown"] += 1
        by_source[str(rec.get("source") or "").strip() or "unknown"] += 1
        raw = rec.get("raw")
        d: dict = {}
        if isinstance(raw, dict):
            for k in LAZY_DETAIL_KEYS:
                if k in raw:
                    d[k] = raw.pop(k)
        details.append(d)
        listing_blobs.append(row_enc.encode(rec).encode("utf-8"))

    not_found = len(pending) - len(matched_keys)
    stats: dict = {
        "existing": existing_total, "patches": len(patches), "matched": len(matched_keys),
        "applied": applied, "not_found": not_found, "duplicate_key_matches": len(dup_keys),
        "written": False, "total_after": existing_total,
    }
    if applied == 0:
        return stats

    # --- STRICT count guard (this function's OWN, tighter than the shared 10% one below) ---
    _manifest_now = load_manifest(docs)
    if _manifest_now:
        _expected = ((_manifest_now.get("files") or {}).get("listings.json") or {}).get("records")
        if isinstance(_expected, int) and existing_total != _expected:
            raise BoardPatchCountMismatch(
                f"patch_existing_rows refused: streamed {existing_total:,} rows off "
                f"{listings_path}, but {docs / MANIFEST_NAME} records {_expected:,} for it. "
                f"A patch pass must never see a different row count than the board's own "
                f"manifest -- they already disagree, which this must not make worse. Verify "
                f"with `scripts/board_manifest.py --verify` before retrying."
            )

    # --- shared backup-before-overwrite (count is unchanged, so the shrink check is a no-op) ---
    _count_guard_and_backup(docs, listings_path, existing_total, summary)

    # --- write listings.json + gzipped parts (the SAME low-level writers write_artifact/
    # append_new_rows use) ---
    total = existing_total
    _manifest_pre: dict = {
        "listings.json": {**_write_plain_array(listings_path, listing_blobs), "records": total},
    }
    detail_path = docs / "listings_detail.json"
    detail_count = len(details)
    detail_bytes = json.dumps(details, ensure_ascii=False, default=str).encode("utf-8")
    del details
    _manifest_pre["listings_detail.json"] = {"bytes": len(detail_bytes),
                                             "sha256": hashlib.sha256(detail_bytes).hexdigest(),
                                             "records": detail_count}
    _atomic_write_bytes(detail_path, detail_bytes)
    _prior_parts = _bp.manifest_parts_block(_bp.read_manifest(docs)) or {}
    _parts = _bp.write_parts(docs, listing_blobs, hint_rows=_prior_parts.get("rows_per_part"))
    _parts_block = _bp.make_block(_parts["entries"], rows_per_part=_parts["rows_per_part"],
                                  cap=_parts["cap"])
    del listing_blobs
    import gzip
    detail_gz = gzip.compress(detail_bytes, compresslevel=9, mtime=0)
    _manifest_pre["listings_detail.json.gz"] = {"bytes": len(detail_gz),
                                                "sha256": hashlib.sha256(detail_gz).hexdigest(),
                                                "records": detail_count}
    _atomic_write_bytes(docs / "listings_detail.json.gz", detail_gz)
    detail_digest = hashlib.sha256(detail_gz).hexdigest()[:16]
    del detail_gz, detail_bytes

    # --- run_meta.json: same shape append_new_rows() writes, minus the fields that need the
    # slim/shard payload regenerated (which this function deliberately does not do) ---
    meta_path = docs / "run_meta.json"
    prior_meta: dict = {}
    if meta_path.exists():
        try:
            prior_meta = json.loads(meta_path.read_text())
        except Exception:  # noqa: BLE001 - a corrupt prior file must not block the write
            prior_meta = {}
        if not isinstance(prior_meta, dict):
            prior_meta = {}
    prior_board_block = prior_meta.get("board")
    if not isinstance(prior_board_block, dict):
        prior_board_block = None
    slim_count = prior_board_block.get("count") if prior_board_block else None
    shard_meta = prior_board_block.get("detail_shards") if prior_board_block else None

    _now = datetime.utcnow()
    _now_iso = _now.isoformat() + "Z"
    meta = dict(prior_meta)
    meta.update({
        "run_time": _now_iso,
        "total": total,
        "by_state": dict(sorted(by_state.items(), key=lambda kv: (-kv[1], kv[0]))),
        "by_source_on_board": dict(sorted(by_source.items(), key=lambda kv: (-kv[1], kv[0]))),
        "notes": summary.get("notes", prior_meta.get("notes", "")),
        "detail_count": detail_count,
        "detail_digest": detail_digest,
        "board_parts": _parts_block,
    })
    if summary.get("by_source"):
        meta["by_source"] = summary["by_source"]
    if prior_board_block is not None:
        meta["board"] = prior_board_block
    _apply_health_freshness(meta, prior_meta, summary, _now_iso, _now)
    _atomic_write_bytes(meta_path, json.dumps(meta, ensure_ascii=False, default=str, indent=2).encode("utf-8"))

    # --- high-water mark: unaffected by a patch pass (total is unchanged by construction), but
    # kept in the same shape as append_new_rows()/write_artifact() so a reader never sees a gap ---
    try:
        _hw_path = docs / "board_highwater.json"
        _prev_hw = 0
        if _hw_path.exists():
            _prev_hw = json.loads(_hw_path.read_text()).get("count", 0)
        if total > _prev_hw:
            _atomic_write_bytes(_hw_path, json.dumps({
                "count": total, "updated_at": _now_iso,
            }, indent=2).encode("utf-8"))
            log.info("web_artifact.highwater_updated", old=_prev_hw, new=total)
    except Exception:  # noqa: BLE001
        pass

    # THE MANIFEST, last (same reasoning as write_artifact/append_new_rows: everything above is
    # on disk by now).
    try:
        write_manifest(docs, _manifest_pre, meta, slim_count=slim_count, shard_meta=shard_meta,
                       parts_block=_parts_block)
    except Exception:  # noqa: BLE001
        try:
            (docs / MANIFEST_NAME).unlink(missing_ok=True)
        except OSError:
            pass
        log.error("web_artifact.manifest_failed", exc_info=True)
    if str(listings_path.resolve()) in _LOAD_STAMPS:
        _remember_load(docs, listings_path)

    log.info("web_artifact.patched", existing=existing_total, applied=applied, total=total,
             not_found=not_found, bytes=listings_path.stat().st_size)
    stats["written"] = True
    return stats


# ===========================================================================
# merge_duplicate_rows: fold a SMALL, KNOWN set of duplicate-row GROUPS into one
# surviving row each and drop the rest -- without materializing the board (follow-up to
# patch_existing_rows(), 2026-09-30, task: clean up ~1,361 real duplicate rows left behind
# when a scraper wrote a mailing address instead of a situs address, so dedupe() never
# recognized the two rows as the same property at scrape time).
# ===========================================================================

class BoardMergeGroupMismatch(RuntimeError):
    """merge_duplicate_rows() refused: at least one merge group did not resolve to EXACTLY its
    expected rows on the CURRENT board -- either an identity key was not found at all (the board
    changed since the caller computed merge_groups: a later scrape/patch/append touched one of
    the target rows, or simply re-derived a different hash for it), or an identity key matched
    MORE than one row (the key is not actually unique, or the same row was hashed twice).

    Unlike patch_existing_rows()'s BoardPatchCountMismatch (which fires on the WHOLE board's row
    count disagreeing with the manifest), this can fire because of a SINGLE group among many --
    and the whole call still refuses to write ANYTHING, deliberately: merge_duplicate_rows()
    changes row count, so a partially-applied merge (some groups folded, others silently
    skipped) would publish a board whose total is neither the old count nor the count the caller
    asked for, with no record of which groups actually landed. A small, human-reviewed batch
    like this should fail loudly and let the caller re-derive merge_groups against the current
    board, not guess."""


# Fields used for row_identity_hash(). Deliberately narrower than a full row dump: every field
# left OUT here is one this codebase's own targeted backfill/patch scripts are known to touch on
# an EXISTING row after it is first published (parcel_id: resolver_backfill_parcel.py;
# owner_name/land_use: enrichment_gis_attrs, documented on the model as GIS-backfilled;
# latitude/longitude: resolver_backfill_geocode.py; living_sqft: sqft_backfill.py; assessed/
# market/tax_value, acreage, bedrooms, bathrooms, year_built: various CAMA/qPublic enrichers;
# raw.* entirely: grade/calc/data_quality/skip_trace/comps/vision/... are recomputed or
# backfilled by name on a schedule). A key that includes any of those would go stale the moment
# an unrelated, perfectly legitimate patch run touches one of the two rows in a pending merge
# group -- which, on this board's own recent history (multiple BOARD_PATCH_ALLOW_LARGE=1 landings
# most nights), is not a rare edge case. What is left IS the set of fields a scraper writes ONCE,
# at first_seen, and essentially never revises afterward -- the closest thing this board has to
# an immutable "as originally scraped" fingerprint for a row.
_MERGE_HASH_FIELDS = (
    "source", "source_url", "listing_type", "street_address", "city", "state", "zip_code",
    "county", "case_number", "plaintiff", "defendant", "trustee", "sale_date", "sale_time",
    "sale_location", "opening_bid", "judgment_amount", "legal_description",
)


def row_identity_hash(rec: dict) -> str:
    """A content fingerprint for ONE published board row, stable across re-serialization and
    independent of position in the file -- the identity-key type merge_duplicate_rows()'s
    `merge_groups` argument is made of.

    WHY NOT dedupe_key(), source_url, or any single field. This codebase has already measured,
    more than once, that no single field on this board is safe to trust as a unique row
    identifier: _identity_keys()'s own docstring records 652 source_urls shared by 19,392 leads
    (one ArcGIS service URL alone shared by 3,293 rows; county PDF rolls give every lead in the
    file the same URL), and dedupe_key() is disqualified for a DIFFERENT reason specific to this
    tool's whole reason for existing -- the 1,361 duplicate rows this was built to clean up have
    DIFFERENT dedupe_key()s by construction (that is exactly why dedupe() never merged them at
    scrape time: one copy's street_address was a mailing address, the other's a situs address,
    so the address branch of dedupe_key() computed two different keys for the same property).
    Any single field used alone would either collide across unrelated rows (source_url, a bare
    parcel_id, a bare address) or fail to distinguish the very rows this tool targets
    (dedupe_key()).

    WHAT THIS DOES INSTEAD. Hashes the JSON encoding of a fixed, deliberately narrow subset of
    fields (_MERGE_HASH_FIELDS -- see its own comment for exactly which fields and why those):
    stable "as scraped" identity fields only, excluding every field this codebase's own
    enrichment/backfill scripts are known to revise on an already-published row. The combination
    of ~17 fields colliding by chance across two unrelated rows is astronomically less likely
    than any one of them alone, while still being far more resistant to going stale between "an
    audit computes merge_groups" and "this function runs" than a full-row hash would be.

    MUST be computed on the row in exactly the form docs/listings*.json PUBLISHES it -- i.e.
    WITHOUT the lazy-detail sidecar (vision/foreclosure_sold_comps/comps/cama/rent_comps) merged
    into `raw`. `board_stream.iter_board_rows()` (the safe, constant-memory board reader this
    codebase's own scripts are required to use for read-only work) already yields rows in
    exactly this form, so an audit script computing merge_groups from it needs no extra
    stripping. Internally, merge_duplicate_rows() computes this AFTER popping LAZY_DETAIL_KEYS
    back out of each streamed row -- the same point in the pass append_new_rows()/
    patch_existing_rows() re-encode from -- so the two sides always see identical bytes for the
    same published row.

    Deliberately NOT the row's full JSON encoding: hashing only the narrow field subset (rather
    than, say, sha256 of the whole `row_enc.encode(rec)` bytes already computed by the caller)
    means a change to some OTHER field between audit-time and merge-time -- e.g. a resolver
    backfilling parcel_id, a CAMA enricher filling in assessed_value -- does not silently
    invalidate this row's identity and turn a real duplicate into a BoardMergeGroupMismatch. A
    caller that wants maximum freshness regardless should still re-derive merge_groups
    immediately before calling merge_duplicate_rows(), in the same operator session; this
    function's field selection only narrows how much intervening activity can break that
    contract, it does not remove the value of re-deriving it fresh.

    Returns a 32-hex-char (128-bit) prefix of the sha256 hex digest -- short enough to be a
    cheap dict key for the (at most a few thousand) rows this function ever tracks, long enough
    that a collision between two DIFFERENT real rows on a ~220K-row board is not a realistic
    concern (a 128-bit space against a few hundred thousand items is nowhere near its birthday
    bound)."""
    enc = json.JSONEncoder(ensure_ascii=False, default=str, sort_keys=True)
    payload = {k: rec.get(k) for k in _MERGE_HASH_FIELDS}
    return hashlib.sha256(enc.encode(payload).encode("utf-8")).hexdigest()[:32]


def merge_duplicate_rows(merge_groups: list[list[str]], summary: dict,
                         docs_dir: Path | str = "docs") -> dict:
    """Fold a SMALL, KNOWN set of duplicate-row GROUPS into one surviving row per group and
    DROP the rest -- without materializing the (potentially hundreds of thousands of) other,
    untouched rows into Listing objects or even a full parsed-dict list, and reusing
    dedupe.py's real Listing.merge() for the fold instead of reimplementing field-precedence
    rules a second time.

    THE PROBLEM THIS SOLVES. append_new_rows() lands new rows, patch_existing_rows() mutates a
    known subset of existing rows in place -- neither can REMOVE a row, because neither was
    built to change the board's row count. The only existing path that can actually delete/merge
    rows is load_board() -> dedupe() -> write_artifact(), which needs the whole board held as
    Listing objects twice over (once as parsed input, once as the deduped output) -- exactly the
    materialization this board's current size (~2.65 GB combined source) no longer fits on this
    8 GB Mac (scripts/normalize_board_duplicates.py needed ~11 GB peak the one time it ran, back
    when the board was smaller). A caller that already knows EXACTLY which small set of rows are
    duplicates (a targeted audit found them, not a full dedupe() re-run) has no reason to touch,
    hold, or even parse the other 99%+ of the board to fix just those.

    HOW. `merge_groups` is a list of duplicate groups; each group is a list of 2+
    row_identity_hash() values (see that function's docstring for why a content hash of a
    narrow, stable field subset -- not dedupe_key(), not source_url, not any single field -- is
    the safe choice of identity key here). Within a group, index 0 is the KEPT row: the survivor
    whose identity (source/source_url, and precedence on any field both copies disagree about)
    the merged row inherits. The remaining entries are DROP rows: their data is folded into the
    kept row via the REAL Listing.merge() (dedupe.py's own merge semantics -- money fields treat
    0 as missing, first_seen takes the earliest, last_seen the latest, raw is deep-merged with
    LATER rows winning on leaf conflicts, also_seen_in gains an attribution entry for each
    dropped row's source), then omitted from the output entirely. The CALLER decides which
    member is index 0 -- typically the copy with the correct situs address, since
    Listing.merge()'s top-level field precedence prefers the KEPT (self) row's own non-null
    values over an incoming row's on a genuine conflict; picking the row with the wrong
    (mailing) address as index 0 would keep the wrong address as the published one.

    The existing board is streamed EXACTLY ONCE via _iter_board_records() (the same incremental
    JSON-array decoder append_new_rows()/patch_existing_rows() use). For each row: LAZY_DETAIL_
    KEYS are popped from `raw` (mirroring every other write path's round-trip) and
    row_identity_hash() is computed on the result. A row whose hash is not in ANY pending group
    is re-encoded and passed straight through, exactly like the other two functions -- this is
    the overwhelming majority of the board and is never touched, held, or even looked up beyond
    one dict membership test. A row whose hash IS a group member is held (not yet written) until
    the whole board has been scanned: every group's members can arrive in any order and from
    anywhere in the file, so the actual Listing.merge() fold only happens after the full pass
    confirms every expected member was found EXACTLY once. Folded rows are appended to the
    output after every untouched row -- board order is not treated as meaningful elsewhere in
    this codebase's own additive tool (append_new_rows() already appends new rows at the end
    regardless of geography), so this does the same rather than trying to preserve the kept
    row's original file position.

    SAFETY INVARIANT (replaces patch_existing_rows()'s exact-count-unchanged guard, which does
    not apply here -- this function EXISTS to change the count). Before ANYTHING is written:
      1. `merge_groups` itself is validated (cheap, no I/O): every group has >= 2 members, no
         key repeats within a group, and no key appears in more than one group (a key needed in
         two groups is a caller bug -- a transitive duplicate chain that needed ONE group of 3,
         not two overlapping groups of 2 -- and merging it into two different survivors would be
         wrong however it were resolved).
      2. After the streaming pass, EVERY key in EVERY group must have matched EXACTLY ONE row.
         Zero matches (BoardMergeGroupMismatch) or more than one match for the same key
         (BoardMergeGroupMismatch) refuses the ENTIRE call -- no partial merge, nothing written.
      3. The exact row-count arithmetic is asserted, not merely checked to be "roughly close":
         `total_after == existing_total - sum(len(group) - 1 for group in merge_groups)`, and
         `len(listing_blobs) == len(details) == total_after`, both by construction (every group
         contributes exactly one output row, every non-grouped row contributes exactly one) and
         reconfirmed with a bare assert immediately before writing.
      4. The existing board's streamed row count is also checked against the board manifest's
         own last-sealed record count for listings.json (when a manifest exists), the same
         corruption check patch_existing_rows() runs -- this function must not compound an
         already-disagreeing board and its manifest.

    WHAT THIS DELIBERATELY DOES NOT DO (same reasoning as append_new_rows()/
    patch_existing_rows(), see their docstrings):
      * Does NOT regenerate listings_slim.json / detail_shards/ -- carried forward unchanged,
        the same disclosed gap the other two streaming writers have.
      * Does NOT re-run dedupe()'s fuzzy/signature passes over the whole board to FIND
        duplicates -- merge_groups must already be known. Finding them is a separate, read-only
        audit step (stream the board with board_stream.iter_board_rows(), group candidates by
        whatever signal the audit trusts, hash each with row_identity_hash()).
      * Does NOT touch listings_slim.json's/board's `board` block's `count` -- carried forward
        from the prior run_meta.json exactly as append_new_rows()/patch_existing_rows() do,
        since this function never regenerates the slim payload either.
      * The high-water mark IS allowed to move DOWN here (unlike patch's, which never changes
        total, so never needed a down case) -- `summary["off_footprint_removed"]` is set to the
        number of rows this call dropped before `_count_guard_and_backup` runs, reusing that
        existing "this shrink is intentional, rebase the mark" plumbing (write_artifact's own
        mechanism -- see `_count_guard_and_backup`'s docstring) rather than inventing a second
        one. At ~1,361 rows out of ~220,000 (well under 1%), this is also nowhere near the
        guard's 10%-unexplained-shrink threshold, so BOARD_ALLOW_SHRINK is not expected to be
        needed for the real cleanup this was built for.
      * Is gated by its OWN size ceiling, BOARD_MERGE_MAX_SOURCE_MB, separate from the other
        three -- see that constant's comment for why, and why it currently just inherits
        BOARD_PATCH_MAX_SOURCE_MB's number pending a dedicated measured trial.

    Returns {existing, groups, rows_targeted, rows_dropped, total_after, written} -- when
    `merge_groups` is empty, {existing: None, groups: 0, rows_targeted: 0, rows_dropped: 0,
    written: False, total_after: None} without touching the board at all. When the board has no
    rows to merge onto yet (no listings.json present), {existing: 0, groups: N, rows_targeted: M,
    rows_dropped: 0, written: False, total_after: 0} -- like patch_existing_rows(), a merge with
    no board yet is a caller error, not a bootstrap case.

    Refuses (BoardLockNotHeld) unless the caller holds the board lock, exactly like
    write_artifact()/append_new_rows()/patch_existing_rows(); refuses (BoardChangedSinceLoad) if
    listings.json changed since this process last loaded it; refuses (BoardLoadTooLarge) if the
    existing board is over BOARD_MERGE_MAX_SOURCE_MB (BOARD_MERGE_ALLOW_LARGE=1 overrides for one
    supervised run); refuses (ValueError) on a malformed `merge_groups` argument (see invariant 1
    above); refuses (BoardMergeGroupMismatch) if any group fails to resolve to exactly its
    expected rows on the current board (invariant 2 above).
    """
    docs = Path(docs_dir)
    docs.mkdir(parents=True, exist_ok=True)
    listings_path = docs / "listings.json"

    require_board_lock(docs)
    _check_not_changed_since_load(listings_path)

    if not merge_groups:
        return {"existing": None, "groups": 0, "rows_targeted": 0, "rows_dropped": 0,
                "written": False, "total_after": None}

    # --- validate merge_groups shape BEFORE any I/O (cheap, catches caller bugs immediately) ---
    key_to_group: dict[str, int] = {}
    for gi, group in enumerate(merge_groups):
        if len(group) < 2:
            raise ValueError(
                f"merge group {gi} has fewer than 2 rows ({group!r}) -- nothing to merge")
        seen_in_group: set = set()
        for key in group:
            if key in seen_in_group:
                raise ValueError(f"merge group {gi} lists identity key {key!r} more than once")
            seen_in_group.add(key)
            if key in key_to_group:
                raise ValueError(
                    f"identity key {key!r} appears in both group {key_to_group[key]} and group "
                    f"{gi} -- a row can only belong to ONE merge group. This is usually a "
                    f"transitive duplicate chain (A~B, B~C) that needs ONE group of 3 "
                    f"([A, B, C]), not two overlapping groups of 2; resolve the overlap in the "
                    f"caller before retrying."
                )
            key_to_group[key] = gi

    rows_targeted = len(key_to_group)

    if not _board_file_present(listings_path):
        # Like patch_existing_rows(): nothing to merge onto. Every group is unmatched by
        # definition -- there is no row to fold.
        return {"existing": 0, "groups": len(merge_groups), "rows_targeted": rows_targeted,
                "rows_dropped": 0, "written": False, "total_after": 0}

    _raise_if_board_too_large_to_merge(docs)

    # --- ONE streaming pass: untouched rows pass straight through; group members are held ---
    row_enc = json.JSONEncoder(ensure_ascii=False, default=str)
    listing_blobs: list[bytes] = []
    details: list[dict] = []
    by_state: collections.Counter = collections.Counter()
    by_source: collections.Counter = collections.Counter()
    existing_total = 0
    # gi -> {identity_key: (row_dict, popped_detail_dict)} -- at most rows_targeted entries
    # total, across every group; never the whole board.
    found: dict[int, dict] = collections.defaultdict(dict)

    for rec in _iter_board_records(docs):
        existing_total += 1
        raw = rec.get("raw")
        d: dict = {}
        if isinstance(raw, dict):
            for k in LAZY_DETAIL_KEYS:
                if k in raw:
                    d[k] = raw.pop(k)
        gi = None
        key = None
        if key_to_group:
            key = row_identity_hash(rec)
            gi = key_to_group.get(key)
        if gi is not None:
            if key in found[gi]:
                raise BoardMergeGroupMismatch(
                    f"identity key {key!r} (merge group {gi}) matched more than one row on the "
                    f"board -- refusing to guess which one was meant. Nothing written; "
                    f"re-derive merge_groups against the current board."
                )
            found[gi][key] = (rec, d)
            continue  # held -- may be re-emitted later as part of the group's merged output
        by_state[str(rec.get("state") or "").strip() or "unknown"] += 1
        by_source[str(rec.get("source") or "").strip() or "unknown"] += 1
        details.append(d)
        listing_blobs.append(row_enc.encode(rec).encode("utf-8"))

    # --- verify EVERY group resolved to EXACTLY its expected rows before computing anything ---
    _missing: list[tuple[int, str]] = []
    for gi, group in enumerate(merge_groups):
        got = found.get(gi, {})
        for key in group:
            if key not in got:
                _missing.append((gi, key))
    if _missing:
        _groups_affected = sorted({gi for gi, _ in _missing})
        raise BoardMergeGroupMismatch(
            f"{len(_missing)} identity key(s) across {len(_groups_affected)} group(s) were not "
            f"found on the board -- it likely changed since merge_groups was computed (another "
            f"scrape/patch/append touched a target row, or its row_identity_hash() shifted). "
            f"Nothing written. Re-scan the board and re-derive merge_groups before retrying. "
            f"First few misses: {_missing[:5]}"
        )

    # --- fold each group with the REAL Listing.merge() logic and append the result ---
    rows_dropped = 0
    for gi, group in enumerate(merge_groups):
        rows_dropped += len(group) - 1
        kept_rec, kept_det = found[gi][group[0]]
        if kept_det:
            kept_rec.setdefault("raw", {}).update(kept_det)
        kept_li = Listing.model_validate(kept_rec)
        for key in group[1:]:
            drop_rec, drop_det = found[gi][key]
            if drop_det:
                drop_rec.setdefault("raw", {}).update(drop_det)
            drop_li = Listing.model_validate(drop_rec)
            kept_li = kept_li.merge(drop_li)  # dedupe.py's real merge, reused verbatim

        # _to_dict() is the SAME publish transform every other row on this board already went
        # through once (RAW_KEEP slim, invalid-address nulling, stale-link annotation) -- safe
        # to re-apply here: both kept_rec.raw and every drop_rec.raw are ALREADY-published,
        # already-RAW_KEEP-slimmed dicts (each only ever contained allowed keys/subkeys to begin
        # with), so their deep-merge cannot contain anything _slim_raw() would newly strip;
        # re-slimming the merged result is a no-op, not a data-loss risk.
        merged_rec = _to_dict(kept_li)
        m_raw = merged_rec.get("raw")
        m_det: dict = {}
        if isinstance(m_raw, dict):
            for k in LAZY_DETAIL_KEYS:
                if k in m_raw:
                    m_det[k] = m_raw.pop(k)
        details.append(m_det)
        listing_blobs.append(row_enc.encode(merged_rec).encode("utf-8"))
        by_state[str(merged_rec.get("state") or "").strip() or "unknown"] += 1
        by_source[str(merged_rec.get("source") or "").strip() or "unknown"] += 1

    total = existing_total - rows_dropped
    # Exact arithmetic, asserted -- not "roughly close" (task's own framing). Both sides are
    # already true by construction (every group emits exactly one row; every non-grouped row
    # emits exactly one row); this is a belt-and-suspenders check immediately before writing.
    assert total == len(listing_blobs) == len(details), (
        f"merge_duplicate_rows internal invariant broken: total={total}, "
        f"len(listing_blobs)={len(listing_blobs)}, len(details)={len(details)}"
    )

    stats: dict = {
        "existing": existing_total, "groups": len(merge_groups), "rows_targeted": rows_targeted,
        "rows_dropped": rows_dropped, "written": False, "total_after": total,
    }

    # --- manifest count check (same corruption guard patch_existing_rows() runs) ---
    _manifest_now = load_manifest(docs)
    if _manifest_now:
        _expected = ((_manifest_now.get("files") or {}).get("listings.json") or {}).get("records")
        if isinstance(_expected, int) and existing_total != _expected:
            raise BoardPatchCountMismatch(
                f"merge_duplicate_rows refused: streamed {existing_total:,} rows off "
                f"{listings_path}, but {docs / MANIFEST_NAME} records {_expected:,} for it. "
                f"Verify with `scripts/board_manifest.py --verify` before retrying."
            )

    # --- shared backup-before-overwrite + count guard. The shrink is intentional (this
    # function's whole job): flagged via off_footprint_removed so the guard treats it as an
    # accepted allowance rather than unexplained shrink, and so the high-water mark can rebase
    # down by exactly this much below. ---
    _summary = dict(summary)
    _summary["off_footprint_removed"] = (
        int(_summary.get("off_footprint_removed") or 0) + rows_dropped
    )
    _accepted_intentional = _count_guard_and_backup(docs, listings_path, total, _summary)

    # --- write listings.json + gzipped parts (the SAME low-level writers the other writers use) ---
    _manifest_pre: dict = {
        "listings.json": {**_write_plain_array(listings_path, listing_blobs), "records": total},
    }
    detail_path = docs / "listings_detail.json"
    detail_count = len(details)
    detail_bytes = json.dumps(details, ensure_ascii=False, default=str).encode("utf-8")
    del details
    _manifest_pre["listings_detail.json"] = {"bytes": len(detail_bytes),
                                             "sha256": hashlib.sha256(detail_bytes).hexdigest(),
                                             "records": detail_count}
    _atomic_write_bytes(detail_path, detail_bytes)
    _prior_parts = _bp.manifest_parts_block(_bp.read_manifest(docs)) or {}
    _parts = _bp.write_parts(docs, listing_blobs, hint_rows=_prior_parts.get("rows_per_part"))
    _parts_block = _bp.make_block(_parts["entries"], rows_per_part=_parts["rows_per_part"],
                                  cap=_parts["cap"])
    del listing_blobs
    import gzip
    detail_gz = gzip.compress(detail_bytes, compresslevel=9, mtime=0)
    _manifest_pre["listings_detail.json.gz"] = {"bytes": len(detail_gz),
                                                "sha256": hashlib.sha256(detail_gz).hexdigest(),
                                                "records": detail_count}
    _atomic_write_bytes(docs / "listings_detail.json.gz", detail_gz)
    detail_digest = hashlib.sha256(detail_gz).hexdigest()[:16]
    del detail_gz, detail_bytes

    # --- run_meta.json: same shape append_new_rows()/patch_existing_rows() write ---
    meta_path = docs / "run_meta.json"
    prior_meta: dict = {}
    if meta_path.exists():
        try:
            prior_meta = json.loads(meta_path.read_text())
        except Exception:  # noqa: BLE001 - a corrupt prior file must not block the write
            prior_meta = {}
        if not isinstance(prior_meta, dict):
            prior_meta = {}
    prior_board_block = prior_meta.get("board")
    if not isinstance(prior_board_block, dict):
        prior_board_block = None
    slim_count = prior_board_block.get("count") if prior_board_block else None
    shard_meta = prior_board_block.get("detail_shards") if prior_board_block else None

    _now = datetime.utcnow()
    _now_iso = _now.isoformat() + "Z"
    meta = dict(prior_meta)
    meta.update({
        "run_time": _now_iso,
        "total": total,
        "by_state": dict(sorted(by_state.items(), key=lambda kv: (-kv[1], kv[0]))),
        "by_source_on_board": dict(sorted(by_source.items(), key=lambda kv: (-kv[1], kv[0]))),
        "notes": summary.get("notes", prior_meta.get("notes", "")),
        "detail_count": detail_count,
        "detail_digest": detail_digest,
        "board_parts": _parts_block,
    })
    if summary.get("by_source"):
        meta["by_source"] = summary["by_source"]
    if prior_board_block is not None:
        meta["board"] = prior_board_block
    _apply_health_freshness(meta, prior_meta, summary, _now_iso, _now)
    _atomic_write_bytes(meta_path, json.dumps(meta, ensure_ascii=False, default=str, indent=2).encode("utf-8"))

    # --- high-water mark: CAN move down here (unlike patch's), via the same rebase mechanism
    # write_artifact()/append_new_rows() use for an accepted intentional shrink ---
    try:
        _hw_path = docs / "board_highwater.json"
        _prev_hw = 0
        if _hw_path.exists():
            _prev_hw = json.loads(_hw_path.read_text()).get("count", 0)
        if total > _prev_hw:
            _atomic_write_bytes(_hw_path, json.dumps({
                "count": total, "updated_at": _now_iso,
            }, indent=2).encode("utf-8"))
            log.info("web_artifact.highwater_updated", old=_prev_hw, new=total)
        elif _accepted_intentional > 0 and total >= _prev_hw - _accepted_intentional:
            _atomic_write_bytes(_hw_path, json.dumps({
                "count": total, "updated_at": _now_iso, "rebased_from": _prev_hw,
                "reason": f"{_accepted_intentional:,} duplicate rows merged away",
            }, indent=2).encode("utf-8"))
            log.warning("web_artifact.highwater_rebased", old=_prev_hw, new=total,
                        duplicates_merged=_accepted_intentional)
    except Exception:  # noqa: BLE001
        pass

    # THE MANIFEST, last (same reasoning as the other three writers).
    try:
        write_manifest(docs, _manifest_pre, meta, slim_count=slim_count, shard_meta=shard_meta,
                       parts_block=_parts_block)
    except Exception:  # noqa: BLE001
        try:
            (docs / MANIFEST_NAME).unlink(missing_ok=True)
        except OSError:
            pass
        log.error("web_artifact.manifest_failed", exc_info=True)
    if str(listings_path.resolve()) in _LOAD_STAMPS:
        _remember_load(docs, listings_path)

    log.info("web_artifact.merged", existing=existing_total, groups=len(merge_groups),
             rows_dropped=rows_dropped, total=total, bytes=listings_path.stat().st_size)
    stats["written"] = True
    return stats


# ===========================================================================
# delete_rows: remove a SMALL, KNOWN set of existing board rows entirely -- no survivor, no
# fold -- without materializing the board (task_board_dedupe_stream, 2026-10-01).
#
# THE GAP THIS CLOSES. append_new_rows() adds, patch_existing_rows() mutates a known subset in
# place, merge_duplicate_rows() folds a known set of duplicate GROUPS into one survivor each --
# none of the three can remove a row with NO survivor. `daily_api_refresh.py`'s stale-REO prune
# (`enrichment_reo_freshness.prune_stale_reo`: a property that has sold/left inventory, confirmed
# by consecutive daily misses against the live feed) is exactly this shape: a row that should
# simply stop existing, not be folded into anything. Until this function, the only way to drop a
# row at all was load_board() -> filter -> write_artifact(), the same whole-board materialization
# every other primitive in this file exists to avoid.
# ===========================================================================

class BoardDeleteMismatch(RuntimeError):
    """delete_rows() refused: at least one requested row_identity_hash() did not resolve to
    EXACTLY one row on the CURRENT board -- not found at all (the board changed since the caller
    computed `hashes`: a later scrape/patch/append touched the target row, or its
    row_identity_hash() shifted), or matched MORE than one row (the hash is not unique on this
    board, or the same row was listed twice).

    Deletion is irreversible (a backup is taken first -- see _count_guard_and_backup -- but
    nothing in the normal publish path un-deletes a row), so this mirrors
    BoardMergeGroupMismatch's all-or-nothing refusal exactly, rather than patch_existing_rows()'s
    "apply the same update to every match" tolerance: a destructive call that cannot tell which
    single physical row was meant must refuse the WHOLE batch, not guess, and not delete the
    unambiguous majority while silently skipping the ambiguous few -- a caller that asked to
    delete 40 stale REO rows and got back "38 deleted, 2 skipped" with no exception has no reason
    to notice the 2, and a wrong guess here is unrecoverable in a way a wrong patch is not."""


def board_delete_hash_fields() -> tuple[str, ...]:
    """The identity-key type delete_rows() expects: row_identity_hash() (see that function's own
    docstring for why -- a narrow, stable, "as scraped" field subset, not dedupe_key(), not
    source_url, not any single field). Exposed as a function (not a re-export of the constant)
    so a caller introspects the contract without depending on _MERGE_HASH_FIELDS' name."""
    return _MERGE_HASH_FIELDS


def delete_rows(hashes: list[str], summary: dict, docs_dir: Path | str = "docs") -> dict:
    """Remove a SMALL, KNOWN set of EXISTING board rows entirely -- identified by
    row_identity_hash(), the SAME narrow "as scraped, rarely revised" content fingerprint
    merge_duplicate_rows() uses (see that function's docstring for why no single existing field,
    and no dedupe_key(), is safe to use as a destructive op's identity key) -- WITHOUT
    materializing the (potentially hundreds of thousands of) other, untouched rows into Listing
    objects or even a full parsed-dict list.

    HOW. `hashes` is a flat list of row_identity_hash() values, each naming exactly one row to
    drop. The existing board is streamed EXACTLY ONCE via _iter_board_records() (the same
    incremental JSON-array decoder append_new_rows()/patch_existing_rows()/merge_duplicate_rows()
    use). For each row: LAZY_DETAIL_KEYS are popped from `raw` (mirroring every other write
    path's round-trip, so listings_detail.json stays correct for every row that survives) and
    row_identity_hash() is computed on the result. A row whose hash is not requested is re-encoded
    and passed straight through -- untouched, exactly like the other three writers. A row whose
    hash IS requested is held (not yet dropped, not yet written) until the whole board has been
    scanned, so every hash's match count is known before anything is decided.

    SAFETY INVARIANT (same all-or-nothing shape as merge_duplicate_rows(), see
    BoardDeleteMismatch's docstring for why a DESTRUCTIVE op gets this instead of
    patch_existing_rows()'s "apply to every match" tolerance). Before ANYTHING is written:
      1. `hashes` itself has no repeats (ValueError otherwise -- a caller bug, the same hash
         cannot name two different "this one row" deletions).
      2. After the streaming pass, EVERY requested hash must have matched EXACTLY ONE row. Zero
         matches or more than one match for the same hash (BoardDeleteMismatch) refuses the
         ENTIRE call -- no partial delete, nothing written.
      3. The existing board's streamed row count is checked against the board manifest's own
         last-sealed record count for listings.json (when a manifest exists), the same
         corruption check patch_existing_rows()/merge_duplicate_rows() run.

    WHAT THIS DELIBERATELY DOES NOT DO (same reasoning as merge_duplicate_rows(), see its
    docstring):
      * Does NOT regenerate listings_slim.json / detail_shards/ -- carried forward unchanged.
      * Does NOT decide WHICH rows are stale -- that is a separate, caller-owned judgment (e.g.
        enrichment_reo_freshness.prune_stale_reo's consecutive-miss count). This function only
        removes rows the caller already named.
      * The high-water mark IS allowed to move DOWN here, via the same `off_footprint_removed`
        rebase mechanism merge_duplicate_rows() uses (write_artifact()'s own "this shrink is
        intentional" plumbing) -- a deletion is definitionally a shrink.
      * Is gated by its OWN size ceiling, BOARD_DELETE_MAX_SOURCE_MB, separate from the other
        four -- see that constant's comment for why it currently just inherits
        BOARD_MERGE_MAX_SOURCE_MB's number pending a dedicated measured trial.

    Returns {existing, requested, matched, deleted, not_found, written, total_after} -- when
    `hashes` is empty, {existing: None, requested: 0, matched: 0, deleted: 0, not_found: 0,
    written: False, total_after: None} without touching the board at all. When the board has no
    rows yet (no listings.json present), every hash is reported `not_found` and nothing is
    written -- there is nothing to delete FROM.

    Refuses (BoardLockNotHeld) unless the caller holds the board lock, exactly like
    write_artifact()/append_new_rows()/patch_existing_rows()/merge_duplicate_rows(); refuses
    (BoardChangedSinceLoad) if listings.json changed since this process last loaded it; refuses
    (BoardLoadTooLarge) if the existing board is over BOARD_DELETE_MAX_SOURCE_MB
    (BOARD_DELETE_ALLOW_LARGE=1 overrides for one supervised run); refuses (ValueError) on a
    `hashes` list with a repeated entry; refuses (BoardDeleteMismatch) if any hash fails to
    resolve to exactly one row on the current board.
    """
    docs = Path(docs_dir)
    docs.mkdir(parents=True, exist_ok=True)
    listings_path = docs / "listings.json"

    require_board_lock(docs)
    _check_not_changed_since_load(listings_path)

    if not hashes:
        return {"existing": None, "requested": 0, "matched": 0, "deleted": 0, "not_found": 0,
                "written": False, "total_after": None}

    seen_hashes: set = set()
    for h in hashes:
        if h in seen_hashes:
            raise ValueError(f"delete_rows: identity hash {h!r} appears more than once in "
                             f"`hashes` -- each row should be named once")
        seen_hashes.add(h)
    target_set = set(hashes)

    if not _board_file_present(listings_path):
        # Nothing to delete FROM. Every hash is unmatched by definition.
        return {"existing": 0, "requested": len(hashes), "matched": 0, "deleted": 0,
                "not_found": len(hashes), "written": False, "total_after": 0}

    _raise_if_board_too_large_to_delete(docs)

    # --- ONE streaming pass: untouched rows pass straight through; targets are HELD (not yet
    # dropped) until the whole board is scanned, so every hash's match count is known first ---
    row_enc = json.JSONEncoder(ensure_ascii=False, default=str)
    listing_blobs: list[bytes] = []
    details: list[dict] = []
    by_state: collections.Counter = collections.Counter()
    by_source: collections.Counter = collections.Counter()
    existing_total = 0
    found: dict[str, int] = collections.defaultdict(int)   # hash -> match count, targets only

    for rec in _iter_board_records(docs):
        existing_total += 1
        raw = rec.get("raw")
        d: dict = {}
        if isinstance(raw, dict):
            for k in LAZY_DETAIL_KEYS:
                if k in raw:
                    d[k] = raw.pop(k)
        h = row_identity_hash(rec) if target_set else None
        if h in target_set:
            found[h] += 1
            continue  # held (and its popped sidecar `d` discarded) -- the row is being deleted
        by_state[str(rec.get("state") or "").strip() or "unknown"] += 1
        by_source[str(rec.get("source") or "").strip() or "unknown"] += 1
        details.append(d)
        listing_blobs.append(row_enc.encode(rec).encode("utf-8"))

    # --- verify EVERY requested hash resolved to EXACTLY one row before deciding anything ---
    _missing = [h for h in hashes if found.get(h, 0) == 0]
    _ambiguous = [h for h in hashes if found.get(h, 0) > 1]
    if _missing or _ambiguous:
        raise BoardDeleteMismatch(
            f"delete_rows refused: {len(_missing)} hash(es) not found, {len(_ambiguous)} "
            f"hash(es) matched more than one row -- it likely changed since `hashes` was "
            f"computed (another scrape/patch/append touched a target row, or its "
            f"row_identity_hash() shifted), or two distinct rows genuinely collide on this "
            f"narrow hash. Nothing written. Re-derive `hashes` from the current board before "
            f"retrying. First few missing: {_missing[:5]}; first few ambiguous: {_ambiguous[:5]}"
        )

    deleted = len(target_set)
    total = existing_total - deleted
    assert total == len(listing_blobs) == len(details), (
        f"delete_rows internal invariant broken: total={total}, "
        f"len(listing_blobs)={len(listing_blobs)}, len(details)={len(details)}"
    )

    stats: dict = {
        "existing": existing_total, "requested": len(hashes), "matched": deleted,
        "deleted": deleted, "not_found": 0, "written": False, "total_after": total,
    }

    # --- manifest count check (same corruption guard the other three writers run) ---
    _manifest_now = load_manifest(docs)
    if _manifest_now:
        _expected = ((_manifest_now.get("files") or {}).get("listings.json") or {}).get("records")
        if isinstance(_expected, int) and existing_total != _expected:
            raise BoardPatchCountMismatch(
                f"delete_rows refused: streamed {existing_total:,} rows off {listings_path}, "
                f"but {docs / MANIFEST_NAME} records {_expected:,} for it. Verify with "
                f"`scripts/board_manifest.py --verify` before retrying."
            )

    # --- shared backup-before-overwrite + count guard. The shrink is intentional (this
    # function's whole job): flagged via off_footprint_removed, same mechanism
    # merge_duplicate_rows() uses, so the high-water mark can rebase down by exactly this much. ---
    _summary = dict(summary)
    _summary["off_footprint_removed"] = int(_summary.get("off_footprint_removed") or 0) + deleted
    _accepted_intentional = _count_guard_and_backup(docs, listings_path, total, _summary)

    # --- write listings.json + gzipped parts (the SAME low-level writers the other writers use) ---
    _manifest_pre: dict = {
        "listings.json": {**_write_plain_array(listings_path, listing_blobs), "records": total},
    }
    detail_path = docs / "listings_detail.json"
    detail_count = len(details)
    detail_bytes = json.dumps(details, ensure_ascii=False, default=str).encode("utf-8")
    del details
    _manifest_pre["listings_detail.json"] = {"bytes": len(detail_bytes),
                                             "sha256": hashlib.sha256(detail_bytes).hexdigest(),
                                             "records": detail_count}
    _atomic_write_bytes(detail_path, detail_bytes)
    _prior_parts = _bp.manifest_parts_block(_bp.read_manifest(docs)) or {}
    _parts = _bp.write_parts(docs, listing_blobs, hint_rows=_prior_parts.get("rows_per_part"))
    _parts_block = _bp.make_block(_parts["entries"], rows_per_part=_parts["rows_per_part"],
                                  cap=_parts["cap"])
    del listing_blobs
    import gzip
    detail_gz = gzip.compress(detail_bytes, compresslevel=9, mtime=0)
    _manifest_pre["listings_detail.json.gz"] = {"bytes": len(detail_gz),
                                                "sha256": hashlib.sha256(detail_gz).hexdigest(),
                                                "records": detail_count}
    _atomic_write_bytes(docs / "listings_detail.json.gz", detail_gz)
    detail_digest = hashlib.sha256(detail_gz).hexdigest()[:16]
    del detail_gz, detail_bytes

    # --- run_meta.json: same shape the other three writers write ---
    meta_path = docs / "run_meta.json"
    prior_meta: dict = {}
    if meta_path.exists():
        try:
            prior_meta = json.loads(meta_path.read_text())
        except Exception:  # noqa: BLE001 - a corrupt prior file must not block the write
            prior_meta = {}
        if not isinstance(prior_meta, dict):
            prior_meta = {}
    prior_board_block = prior_meta.get("board")
    if not isinstance(prior_board_block, dict):
        prior_board_block = None
    slim_count = prior_board_block.get("count") if prior_board_block else None
    shard_meta = prior_board_block.get("detail_shards") if prior_board_block else None

    _now = datetime.utcnow()
    _now_iso = _now.isoformat() + "Z"
    meta = dict(prior_meta)
    meta.update({
        "run_time": _now_iso,
        "total": total,
        "by_state": dict(sorted(by_state.items(), key=lambda kv: (-kv[1], kv[0]))),
        "by_source_on_board": dict(sorted(by_source.items(), key=lambda kv: (-kv[1], kv[0]))),
        "notes": summary.get("notes", prior_meta.get("notes", "")),
        "detail_count": detail_count,
        "detail_digest": detail_digest,
        "board_parts": _parts_block,
    })
    if summary.get("by_source"):
        meta["by_source"] = summary["by_source"]
    if prior_board_block is not None:
        meta["board"] = prior_board_block
    _apply_health_freshness(meta, prior_meta, summary, _now_iso, _now)
    _atomic_write_bytes(meta_path, json.dumps(meta, ensure_ascii=False, default=str, indent=2).encode("utf-8"))

    # --- high-water mark: CAN move down here, via the same rebase mechanism
    # merge_duplicate_rows() uses for an accepted intentional shrink ---
    try:
        _hw_path = docs / "board_highwater.json"
        _prev_hw = 0
        if _hw_path.exists():
            _prev_hw = json.loads(_hw_path.read_text()).get("count", 0)
        if total > _prev_hw:
            _atomic_write_bytes(_hw_path, json.dumps({
                "count": total, "updated_at": _now_iso,
            }, indent=2).encode("utf-8"))
            log.info("web_artifact.highwater_updated", old=_prev_hw, new=total)
        elif _accepted_intentional > 0 and total >= _prev_hw - _accepted_intentional:
            _atomic_write_bytes(_hw_path, json.dumps({
                "count": total, "updated_at": _now_iso, "rebased_from": _prev_hw,
                "reason": f"{_accepted_intentional:,} rows deleted",
            }, indent=2).encode("utf-8"))
            log.warning("web_artifact.highwater_rebased", old=_prev_hw, new=total,
                        rows_deleted=_accepted_intentional)
    except Exception:  # noqa: BLE001
        pass

    # THE MANIFEST, last (same reasoning as the other three writers).
    try:
        write_manifest(docs, _manifest_pre, meta, slim_count=slim_count, shard_meta=shard_meta,
                       parts_block=_parts_block)
    except Exception:  # noqa: BLE001
        try:
            (docs / MANIFEST_NAME).unlink(missing_ok=True)
        except OSError:
            pass
        log.error("web_artifact.manifest_failed", exc_info=True)
    if str(listings_path.resolve()) in _LOAD_STAMPS:
        _remember_load(docs, listings_path)

    log.info("web_artifact.deleted", existing=existing_total, deleted=deleted, total=total,
             bytes=listings_path.stat().st_size)
    stats["written"] = True
    return stats
