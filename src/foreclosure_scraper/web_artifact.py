"""Generate the static-site JSON files consumed by docs/index.html (the live dashboard).

Writes (every one of these, plus a .gz twin for the four payloads, in ONE call —
a publish that stages some and not others ships a mis-joined board):
  docs/listings.json        — array of sanitized listings (Pydantic-dumped, raw kept slim)
  docs/listings_detail.json — index-aligned sidecar: the heavy comps/vision keys
  docs/listings_slim.json   — SLIM-V1, the board payload phones fetch
  docs/detail_shards/*.json.gz — index-aligned detail, cut so a phone can fetch one lead
  docs/run_meta.json        — run timestamp, source_status, totals, sources contributing
"""
from __future__ import annotations

import hashlib
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

import structlog

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


class BoardIntegrityError(RuntimeError):
    """A board file on disk does not match its manifest (torn or mixed write)."""


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


def _choose_board_file(p: Path) -> tuple[Path, str]:
    """Which file to read for `p` (docs/listings.json or its sibling), plus its
    role. Honors the manifest when it names the file; otherwise the legacy rule
    (plain if present, else its .gz)."""
    gz = p.with_name(p.name + ".gz")
    man = load_manifest(p.parent)
    entry_plain = man["files"].get(p.name) if man else None
    if not entry_plain:
        if p.exists():
            return p, "plain"
        if gz.exists():
            return gz, "gz"
        raise FileNotFoundError(f"{p} (and {p.name}.gz) not found")
    entry_gz = man["files"].get(gz.name)
    plain_ok, plain_why = (False, "missing")
    if p.exists():
        plain_ok, plain_why = _file_matches_manifest(p, entry_plain)
    if plain_ok:
        return p, "plain"
    gz_ok, gz_why = (False, "missing")
    if gz.exists() and entry_gz:
        gz_ok, gz_why = _file_matches_manifest(gz, entry_gz)
    if gz_ok:
        if p.exists():
            log.error("board.plain_disagrees_with_manifest", file=p.name, why=plain_why,
                      using=gz.name)
        return gz, "gz"
    raise BoardIntegrityError(
        f"{p.name} does not match {MANIFEST_NAME} (plain: {plain_why}; "
        f"gz: {gz_why}). The payload set is torn or mixed. Restore a consistent set "
        f"(scripts/restore_board.sh <commit>) or, if you know the files are right, "
        f"scripts/board_manifest.py --rebuild. BOARD_MANIFEST_SKIP=1 bypasses this check."
    )


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
    used, role = _choose_board_file(p)
    if role == "plain":
        return json.loads(used.read_text()), used
    import gzip as _gzip
    return json.loads(_gzip.decompress(used.read_bytes()).decode("utf-8")), used


def read_board_json(path: Path | str):
    """Read a board JSON file, transparently falling back to its ``.gz`` twin.

    The uncompressed docs/listings.json (~1.1GB now) is NOT committed to git — it
    exceeds GitHub's 100MB/file limit, and the dashboard only ever loads the
    gzipped copy. The local runner regenerates the plain .json every write, so on
    that machine this reads the plain file directly. Everywhere else (a fresh
    clone, a cloud CI/patch job, disaster recovery) only the committed .gz exists,
    so we decompress that instead. Either way the whole system can rebuild the
    board from just the .gz — nothing depends on the big file being present.

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
    return p.exists() or p.with_name(p.name + ".gz").exists()


def _register_if_held() -> None:
    """A process inside a wrapper-held lock registers itself when it starts
    working on the board (audit O11), not only when it writes."""
    try:
        d = _repo_lock_dir()
        if os.environ.get(BOARD_LOCK_ENV) == str(d):
            _bl_register_child(d)
    except Exception:  # noqa: BLE001
        pass


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
    """
    docs = Path(docs_dir)
    records, used = _read_board_json_ex(docs / "listings.json")
    _remember_load(docs, used)
    _register_if_held()
    detail_path = docs / "listings_detail.json"
    strict = load_manifest(docs) is not None
    details: list = []
    if _board_file_present(detail_path):
        try:
            details = read_board_json(detail_path)
        except BoardIntegrityError:
            raise
        except Exception:  # noqa: BLE001
            if strict:
                raise
            details = []
    if strict and len(details) != len(records):
        raise BoardIntegrityError(
            f"listings_detail has {len(details)} rows for {len(records)} listings: "
            f"the sidecar is index-aligned, so this board is a mixed set")
    for i, rec in enumerate(records):
        if i < len(details) and isinstance(details[i], dict) and details[i]:
            raw = rec.get("raw")
            if isinstance(raw, dict):
                raw.update(details[i])
    return records


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

    Reads via read_board_json, so it works from either the plain .json (local
    runner) or the committed .gz (fresh clone / cloud) — see that helper.

    A row that fails validation is DROPPED (the board is rewritten without it), and
    that used to be `except Exception: pass`: no log line, no count. Now every drop
    is counted and logged (first LOAD_DROP_LOG_LIMIT to logs/board_load_dropped.jsonl),
    and the load FAILS when the drop rate exceeds `max_drop_rate` (default: env
    BOARD_LOAD_MAX_DROP_RATE, else 0.001 = 0.1%). BOARD_LOAD_ALLOW_DROPS=1 loads anyway.
    A caller with its own recovery for invalid rows (patch_vision_gemini's
    load_board_no_shrink) passes max_drop_rate=1.0 and re-hydrates the strays itself.
    """
    recs = read_board_records(docs_dir)
    out: list[Listing] = []
    dropped: list[tuple[int, str, str, str]] = []
    for i, rec in enumerate(recs):
        try:
            out.append(Listing.model_validate(rec))
        except Exception as exc:  # noqa: BLE001
            src = str(rec.get("source", "")) if isinstance(rec, dict) else ""
            url = str(rec.get("source_url", ""))[:120] if isinstance(rec, dict) else ""
            dropped.append((i, src, url, f"{type(exc).__name__}: {str(exc)[:160]}"))
    total = len(recs)
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
    "lien_priority": "*",             # senior/junior liens + super-priority warnings
    "propwire": "*",                  # equity, owner, last sale (when present)
    "loopnet": "*",                   # multifamily-specific cap rate, units, etc.
    "reac": "*",                      # HUD REAC inspection scores {latest_score, scores[], distressed}
    "images": "*",                    # {primary, map, street} fallback image map
    "flood": "*",                     # FEMA flood-zone tag {zone, in_sfha, ...}
    "nod": "*",                       # ROD-discovered Notice of Default
    "bankruptcy": "*",                # CourtListener bankruptcy match on defendant name
    "courtlistener": "*",             # raw bankruptcy docket data when emitted as a listing
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
    "geo_imprecise": "*",             # out_of_bbox (geo nulled) | centroid_snap (county/town-center fallback)
    "stale_case": "*",                # presumed_withdrawn lis-pendens — likely resolved, down-ranked from HOT
    "staleness": "*",                 # staleness_sweep verdict {state: upset_closed|sale_passed|gone_quiet, ...} for dashboard filtering
    "life_events": "*",               # elderly/probate signals: life_estate | estate_probate | multiple_heirs | trust
    "probate": "*",                   # probate court case search result: case_number, filing_date, court, decedent, status
    "gis_exempt": "*",                # statutory tax-relief exemption (ELD/DIS/BLD/VET) -> hard elderly/disabled signal
    "owner_name_source": "*",         # provenance when owner_name was promoted from tax/GIS
    "notice_contact": "*",            # attributable attorney/trustee email from the legal-notice body
    "incarceration": "*",             # owner matched a state corrections roster (NC DAC) — low-conf stack signal
    "incarceration_check": "*",       # answered NO-match stamp {checked_at, name, source, result}: lets the enricher rotate past checked leads instead of re-querying the same 150
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
    "pickens_mie": "*",               # Pickens MIE results PDF parse provenance
    "anderson_mie_results": "*",      # Anderson MIE Sale-Results parse provenance
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
    "owner_email": "*",               # surfaced owner email from OCR/skip-trace
    "red_flags": "*",                  # unified red flag array [{severity, type, description, source}]
    "sos_dissolution": "*",            # NC SOS LLC dissolution status
    "tax_aging_surfaced": "*",         # surfaced tax aging status for all listings
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
    "greenville_mie": "*",
    "bt_appraisal_card": "*",

    # cross-cutting distress signals
    "absentee_owner": "*", "bank_name": "*", "case": "*",
    "cash_buyer_deeds": "*", "court": "*", "document_url": "*",
    "epa_id": "*", "filing_number": "*", "flc": "*",
    "geo_missing": "*", "geo_source": "*", "heir_estate": "*",
    "irs": "*", "irs_treasury": "*", "legacy": "*",
    "mtg_file": "*", "multiple_owners": "*", "notice_url": "*",
    "obituary": "*", "onemap_resolved": "*", "owner": "*",
    "permit_type": "*", "sale_type": "*", "scdot_parcel_resolved": "*",
    "status": "*", "tax_sale_status": "*", "tms": "*",
    "upset_bid_deadline": "*", "violation_type": "*", "zombie_property": "*",

    # third-party listing / property identifiers, needed to re-find a lead upstream
    "fc_listing_id": "*", "govdeals_asset_id": "*", "homesteps_kind": "*",
    "hud_property_id": "*", "reo_id": "*", "trulia_id": "*",
    "usda_property_id": "*", "vrm_id": "*", "xome_listing_id": "*",
    "zpid": "*",

    # per-source provenance: the parsed cells, case numbers and notice URLs behind
    # each lead, which is what an operator opens a row to check
    "aiken_delinquent_tax": "*", "anderson_sheriff": "*", "arcgis_distress": "*",
    "asheville_min_housing": "*", "auction_bank_reo": "*", "auction_dot_com": "*",
    "bamberg_sheriff": "*", "barnwell_sheriff": "*", "brunswick_legal_notices": "*",
    "buncombe_tax": "*", "charleston_delinquent_tax": "*", "charleston_mie": "*",
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
    "horry_flc": "*", "hubzu": "*", "ingle_firm": "*",
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
    "treasury_seized": "*", "tryon_bulletin": "*", "union_delinquent_tax": "*",
    "usda_rd": "*", "usmarshals": "*", "wake_tax_foreclosure": "*",
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
    "resolver_conflict_undone": "*",   # withdrawn name-to-property resolution {action, query_name, matched_owner, removed}
    # Read by the scorer (docs/handoff_scorer_to_others_2026-09-21.md section 2). Without an
    # entry a board reloaded from the published files loses them, so the tax_lien_chronic weight
    # (Pickens, 3+ roll years) and the vacant_structure PROPERTY signal (Hendersonville register)
    # fire on a full run only. Pickens keeps just what the scorer and the card need (the
    # `publications` list is the bulky part); the vacancy block is four small keys.
    "pickens_delinquent": ("chronic", "repeat_delinquent", "cycle_count", "pre_sale",
                           "first_cycle", "latest_cycle"),
    "vacancy": "*",

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
# THE THREE RULES THIS FILE IS UNDER:
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
    "sos_agent": ("sosid", "best_contact_name", "best_contact_address"),
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
    "bankruptcy": ("chapter", "date_filed", "case_name", "docket_number", "court"),
    "courtlistener": ("chapter", "date_filed", "court"),
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


def build_manifest(docs: Path | str, precomputed: dict | None = None,
                   meta: dict | None = None, slim_count: int | None = None,
                   shard_meta: dict | None = None) -> dict:
    """Manifest for whatever payload files are on disk right now.

    `precomputed` maps a file name to an entry already known (write_artifact hashes
    the two 1.1 GB files from memory instead of re-reading them). Everything else
    is hashed from disk. run_meta.json is included, so a tool that edits it must go
    through write_manifest again (scripts/board_manifest.py --rebuild does)."""
    docs = Path(docs)
    pre = precomputed or {}
    files: dict = {}
    for name in ("listings.json", "listings_detail.json", "listings.json.gz",
                 "listings_detail.json.gz", "listings_slim.json", "listings_slim.json.gz",
                 "run_meta.json"):
        if name in pre:
            files[name] = pre[name]
            continue
        fp = docs / name
        if not fp.is_file():
            continue
        recs = slim_count if name.startswith("listings_slim") else None
        files[name] = _manifest_entry(fp, recs)
    sd = docs / DETAIL_SHARD_DIR
    if sd.is_dir():
        for fp in sorted(sd.iterdir()):
            if fp.is_file() and not fp.name.endswith(".tmp"):
                files[f"{DETAIL_SHARD_DIR}/{fp.name}"] = _manifest_entry(fp)
    count = (files.get("listings.json") or files.get("listings.json.gz") or {}).get("records")
    return {
        "schema": MANIFEST_SCHEMA,
        "written_at": datetime.utcnow().isoformat() + "Z",
        "run_time": (meta or {}).get("run_time"),
        "count": count,
        "detail_count": (files.get("listings_detail.json") or {}).get("records"),
        "slim_count": slim_count,
        "shards": shard_meta,
        "files": files,
    }


def write_manifest(docs: Path | str, precomputed: dict | None = None,
                   meta: dict | None = None, slim_count: int | None = None,
                   shard_meta: dict | None = None) -> Path:
    docs = Path(docs)
    man = build_manifest(docs, precomputed, meta, slim_count, shard_meta)
    mp = docs / MANIFEST_NAME
    _atomic_write_bytes(mp, json.dumps(man, indent=1, sort_keys=False).encode("utf-8"))
    return mp


def verify_manifest(docs: Path | str, full: bool = True) -> dict:
    """Check every file the manifest names. Returns {"ok", "checked", "problems"}.
    `full` hashes each file; otherwise only size is compared. Used by
    scripts/board_manifest.py --verify and the restore script; never raises."""
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
    return {"ok": not problems, "checked": checked, "problems": problems,
            "count": man.get("count"), "written_at": man.get("written_at")}


# Rolling pre-write backups kept per pattern (main board + detail sidecar). Each
# main copy is ~1.04GB, so 10 of them was 12GB of a laptop that needed 50-80GB
# back (2026-09-19). Every committed board is also in git history and the live
# board is the newest state; 3 still covers the "a bad write just landed" case
# the backup exists for. Override with BOARD_BACKUP_KEEP.
_BACKUP_KEEP = max(1, int(os.environ.get("BOARD_BACKUP_KEEP", "3")))


def write_artifact(
    listings: list[Listing],
    summary: dict,
    docs_dir: Path | str = "docs",
) -> tuple[Path, Path]:
    """Write the whole payload set, then the manifest that seals it.

    Refuses (BoardLockNotHeld) unless the caller holds the board lock, and
    (BoardChangedSinceLoad) if listings.json is not the file this process loaded
    — see require_board_lock / _check_not_changed_since_load and audit O3.
    """
    docs = Path(docs_dir)
    docs.mkdir(parents=True, exist_ok=True)

    listings_path = docs / "listings.json"
    meta_path = docs / "run_meta.json"

    # FIRST, before any expensive work and before a single byte is touched.
    require_board_lock(docs)
    _check_not_changed_since_load(listings_path)

    payload = [_to_dict(li) for li in listings]

    # Split the heavy, detail-panel-only raw keys (comps/vision arrays — the
    # most deeply nested payload) into an index-aligned sidecar the dashboard
    # fetches lazily on the first card open. Index alignment (not a per-lead id)
    # is the join: both files are built from `payload` in the same order, so
    # detail[i] belongs to listing[i]. Popping happens LAST (after _to_dict /
    # _slim_raw / annotate_stale_links) so nothing re-adds these keys. Additive:
    # if listings_detail.json is missing/mismatched, those panels render empty.
    # Prior sidecar, keyed by identity — lets a full re-scrape (which only
    # re-visions a capped subset) KEEP vision/comps/cama for the leads it
    # didn't touch this run, instead of overwriting details[i] with {}.
    # Fresh detail from THIS run always wins; prior only backfills missing keys.
    prior = _load_prior_details_by_key(docs)
    # Guard BOTH sides: a key can be unique in the prior board yet ambiguous in
    # what we are about to write (e.g. a re-scrape that pulled 3,293 leads from
    # one ArcGIS URL). Carrying detail across it would fan one report out to all
    # of them, so only keys unique on BOTH sides are allowed to match.
    payload_unique = _unique_key_map(payload) if prior else {}
    details = []
    for rec in payload:
        raw = rec.get("raw")
        d = {}
        if isinstance(raw, dict):
            for k in LAZY_DETAIL_KEYS:
                if k in raw:
                    d[k] = raw.pop(k)
        if prior:
            pri = None
            for key in _identity_keys(rec):
                if payload_unique.get(key) and key in prior:
                    pri = prior[key]
                    break
            if pri:
                for k in LAZY_DETAIL_KEYS:
                    if k not in d and k in pri:
                        d[k] = pri[k]
        details.append(d)
    import gzip
    listings_bytes = json.dumps(payload, ensure_ascii=False, default=str).encode("utf-8")
    detail_path = docs / "listings_detail.json"
    detail_bytes = json.dumps(details, ensure_ascii=False, default=str).encode("utf-8")
    # Atomic writes (temp + os.replace) so a kill mid-write can never leave a
    # truncated 100MB+ file — the prior good file survives. git history is the
    # rollback backup for a completed-but-bad write (the count-drop guard flags
    # those before publish).
    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    # BACKUP-BEFORE-OVERWRITE + COUNT GUARD
    #
    # Two data-loss events (actions #16, #22) happened because a script wrote
    # a smaller board (scope filter dropped 16K+ leads) and the prior data was
    # gone — _atomic_write_bytes replaces the file, so the old content is lost.
    #
    # This block does TWO things before any write:
    #   1. COUNT GUARD — if the new board is >10% smaller than the existing
    #      board AND the caller didn't set BOARD_ALLOW_SHRINK, it RAISES.
    #      This catches the exact bug that killed 53K→37K: a script calling
    #      write_artifact with a filtered subset. The caller must either fix
    #      their data or explicitly opt in with BOARD_ALLOW_SHRINK=1.
    #   2. TIMESTAMPED BACKUP — copies the existing listings.json + detail
    #      to backups/ with a timestamp, so even if the guard is bypassed,
    #      the prior board is recoverable. Keeps the last 10 backups.
    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
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

        if _highwater_count is not None and len(payload) < _effective_baseline:
            _shrink_pct = (1 - len(payload) / _effective_baseline) * 100
            _allow = os.environ.get("BOARD_ALLOW_SHRINK", "").strip()
            if _shrink_pct > 10 and _allow not in ("1", "true", "yes"):
                raise RuntimeError(
                    f"COUNT GUARD: refusing to write {len(payload):,} listings "
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
            import shutil as _sh
            _sh.copy2(listings_path, _backup_dir / f"listings_{_ts}.json")
            if (docs / "listings_detail.json").exists():
                _sh.copy2(docs / "listings_detail.json",
                          _backup_dir / f"listings_detail_{_ts}.json")
            elif (docs / "listings_detail.json.gz").exists():
                _sh.copy2(docs / "listings_detail.json.gz",
                          _backup_dir / f"listings_detail_{_ts}.json.gz")
            log.info("web_artifact.backup_saved", path=str(_backup_dir / f"listings_{_ts}.json"))
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
        try:
            for _pattern in ("listings_2*.json", "listings_detail_2*.json*"):
                _old = sorted(_backup_dir.glob(_pattern),
                              key=lambda p: p.stat().st_mtime, reverse=True)[_BACKUP_KEEP:]
                for _f in _old:
                    _f.unlink(missing_ok=True)
        except Exception:  # noqa: BLE001
            pass
    # The manifest (written LAST) needs each big file's size and sha256. Take them
    # from the bytes already in memory rather than re-reading 1.1 GB from disk.
    _manifest_pre: dict = {
        "listings.json": {"bytes": len(listings_bytes),
                          "sha256": hashlib.sha256(listings_bytes).hexdigest(),
                          "records": len(payload)},
        "listings_detail.json": {"bytes": len(detail_bytes),
                                 "sha256": hashlib.sha256(detail_bytes).hexdigest(),
                                 "records": len(details)},
    }
    _atomic_write_bytes(listings_path, listings_bytes)
    _atomic_write_bytes(detail_path, detail_bytes)
    # Also emit gzipped copies the dashboard fetches (16x smaller). The .json
    # files remain the local source-of-truth + a fallback. mtime=0 keeps the gzip
    # header deterministic so identical data produces identical bytes (no git churn).
    listings_gz = gzip.compress(listings_bytes, compresslevel=9, mtime=0)
    _manifest_pre["listings.json.gz"] = {"bytes": len(listings_gz),
                                         "sha256": hashlib.sha256(listings_gz).hexdigest(),
                                         "records": len(payload)}
    _atomic_write_bytes(docs / "listings.json.gz", listings_gz)
    del listings_gz
    detail_gz = gzip.compress(detail_bytes, compresslevel=9, mtime=0)
    _manifest_pre["listings_detail.json.gz"] = {"bytes": len(detail_gz),
                                                "sha256": hashlib.sha256(detail_gz).hexdigest(),
                                                "records": len(details)}
    _atomic_write_bytes(docs / "listings_detail.json.gz", detail_gz)
    # Identity of the sidecar THIS call wrote — see the detail_count/
    # detail_digest note where run_meta is assembled. Deterministic (sha256 of
    # deterministic gzip bytes), so a republish of identical data does not churn.
    detail_digest = hashlib.sha256(detail_gz).hexdigest()[:16]
    del detail_gz

    # SLIM-V1, the mobile payload. Derived from the SAME `payload` list, and
    # deliberately emitted only after the two authoritative files are already on
    # disk: nothing below this line can change listings.json's bytes, and a bug
    # in the derivative cannot cost a run its board. See the SLIM-V1 block above.
    del listings_bytes, detail_bytes    # free ~350 MB before projecting (8 GB box)
    _report_slim_drops(listings)   # loud about what slim leaves behind — see the docstring
    slim_count = _emit_slim(docs, payload)

    # DETAIL SHARDS, the mobile detail payload. Same contract as the slim file
    # and deliberately last: every authoritative byte is already on disk, this
    # reads `payload` and `details` without mutating either, and a failure here
    # costs a derivative, never a board. Gated on the slim emit having succeeded
    # — the two are one mobile payload, advertised in one metadata block. See
    # the DETAIL SHARDS block above.
    shard_meta = _emit_detail_shards(docs, payload, details,
                                     slim_ok=slim_count is not None)

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
        "detail_count": len(details),
        "detail_digest": detail_digest,
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

    # PRESERVE per-source health across partial writers.
    # Fourteen maintenance scripts (sos_agent_refresh, lrcpwa_refresh,
    # owner_mailing_refresh, the ingest_* family, ...) call write_artifact with a
    # one-key summary like {"notes": "scheduled NC SOS refresh"}. Each one then
    # blanked by_source / source_status / by_state, so run_meta.json - the ONLY
    # per-source health report there is - showed "by_source": {} for days after a
    # full run, and neither the operator nor a dashboard could answer "which
    # sources are actually contributing". Carry the prior run's values forward
    # when this writer did not compute its own, and mark the file so the staleness
    # is visible rather than implied.
    #
    # THIS ONLY WORKS IF CALLERS STOP LAUNDERING THE PRIOR FILE BACK IN.
    # health_carried_from is stamped only when a key is ABSENT from `meta`, i.e.
    # only when THIS writer genuinely had nothing to say. Two callers used to
    # read the prior run_meta.json themselves, strip `board`, and hand the rest
    # back as their summary (recompute_valuation.py, patch_vision_gemini's
    # _prior_meta) — so every key arrived already populated, the branch below
    # never fired, and the published file asserted a months-old per-source
    # health report as current. Both now pass only their own notes and let this
    # block do the carrying, which produces the same values plus the label.
    #
    # by_state is NOT in this list: it is derived above from the board being
    # written, so there is never a stale value to carry.
    #
    # AUDIT O4 (2026-09-21): health_carried_from used to be the PRIOR WRITE's
    # run_time, so it always looked minutes old while the per-source status it
    # labelled was 23 days old (the last full run to compute it landed 8/29).
    # Now:
    #   health_as_of         when THIS status was computed: stamped when the writer
    #                        computed its own source_status, otherwise carried
    #                        forward UNCHANGED from the first write that computed it
    #   health_carried_from  same instant (kept for existing readers)
    #   health_age_hours     now - health_as_of, so nobody has to do the subtraction
    #   health_stale         True when the age exceeds HEALTH_MAX_AGE_HOURS (48) or
    #                        the origin is unknown
    # and once stale, source_status and errors are NULLED so a consumer sees
    # "unknown" instead of a frozen green board. by_source and by_county_top keep
    # being carried (they are counts, labelled by health_as_of).
    _carried: list[str] = []
    prior_meta: dict = {}
    if meta_path.exists():
        try:
            prior_meta = json.loads(meta_path.read_text())
        except Exception:  # noqa: BLE001 - a corrupt prior file must not block the write
            prior_meta = {}
        if not isinstance(prior_meta, dict):
            prior_meta = {}
    _own_health = bool(summary.get("source_status"))
    for key in ("by_source", "by_county_top", "source_status",
                "regressions", "errors"):
        if not meta.get(key) and prior_meta.get(key):
            meta[key] = prior_meta[key]
            _carried.append(key)
    if _own_health:
        health_as_of = _now_iso
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
            age_h = round(max(0.0, (_now - _t).total_seconds() / 3600.0), 2)
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
                _ls[slug] = _now_iso
    _refreshed = summary.get("source_refreshed")
    if isinstance(_refreshed, dict):
        for slug, when in _refreshed.items():
            _ls[slug] = when if isinstance(when, str) and when else _now_iso
    elif isinstance(_refreshed, (list, tuple, set)):
        for slug in _refreshed:
            _ls[str(slug)] = _now_iso
    if _ls:
        meta["source_last_success"] = dict(sorted(_ls.items()))
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
        write_manifest(docs, _manifest_pre, meta, slim_count=slim_count, shard_meta=shard_meta)
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

    log.info("web_artifact.written", listings=len(listings), bytes=listings_path.stat().st_size)
    return listings_path, meta_path
