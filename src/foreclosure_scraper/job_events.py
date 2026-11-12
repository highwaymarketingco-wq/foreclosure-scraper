"""One JSON line per scheduled-job outcome, appended to logs/job_events.jsonl.

WHY THIS EXISTS (audit 2026-09-21, O4/O9/O10). Every scheduled job here used to
print its outcome to a log under /tmp and exit 0: a skipped lock, a refused
count guard, a failed push and a clean run were indistinguishable to anything
that was not a person reading the log. The dailycourt job failed 31 days in a
row (exit 127, "uv: command not found") and nobody was told. This file is the
one place a watcher (scripts/job_watch.py) can ask "when did job X last succeed".

The shell twin is scripts/job_event.sh. Both write the SAME shape, so a reader
never has to care which side wrote a line:

    {"ts": "...Z", "kind": "job", "job": "lrcpwa", "start": "...Z", "end": "...Z",
     "outcome": "ok", "rows_changed": 12, "duration_s": 431,
     "swapouts_start": N, "swapouts_end": N, "swap_out_mb": N, "rss_peak_mb": N,
     "note": "..."}

`outcome` is one of OUTCOMES. Non-job lines (lock breaks, memory-gate waits,
skips noticed inside the lock code) use kind="note" with an `event` field, so a
watcher that only wants job outcomes filters on kind == "job".

Everything here NEVER raises. A job must not fail because its own bookkeeping
could not be written.
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

EVENTS_FILENAME = "job_events.jsonl"
# ok            job ran and did its work
# no_change     job ran, found nothing to do (a clean result, not a failure)
# skipped_lock  another board writer held the lock
# skipped_memory  the memory gate (swap / free RAM) refused the start
# failed        job ran and failed, or exited without reporting an outcome
# push_failed   the board was committed locally but the push did not land
OUTCOMES = ("ok", "no_change", "skipped_lock", "skipped_memory", "failed", "push_failed")
# The file is rotated once past this size so a chatty job cannot fill the disk.
MAX_BYTES = int(os.environ.get("JOB_EVENTS_MAX_BYTES", str(5 * 1024 * 1024)))

_SAFE_RE = re.compile(r"[^\w .:/=,+@()\[\]-]")


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def events_path(root: Path | str | None = None) -> Path:
    env = os.environ.get("JOB_EVENTS_FILE")
    if env:
        return Path(env)
    return Path(root or _repo_root()) / "logs" / EVENTS_FILENAME


def iso(ts: float | None = None) -> str:
    dt = datetime.fromtimestamp(ts if ts is not None else time.time(), tz=timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def _clean(value, limit: int = 200):
    """Strings are stripped of anything that could confuse a downstream reader."""
    if isinstance(value, str):
        return _SAFE_RE.sub("", value)[:limit]
    return value


def _append(line: dict, root: Path | str | None = None) -> None:
    path = events_path(root)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        try:
            if path.exists() and path.stat().st_size > MAX_BYTES:
                os.replace(path, path.with_name(path.name + ".1"))
        except OSError:
            pass
        with open(path, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(line, separators=(",", ":"), default=str) + "\n")
    except Exception:  # noqa: BLE001 - bookkeeping must never fail the job
        pass


def swapouts_pages() -> int | None:
    """Cumulative swap-outs since boot, in pages, from vm_stat. None if unknown."""
    fake = os.environ.get("JOB_EVENTS_FAKE_SWAPOUTS")
    if fake is not None:
        try:
            return int(fake)
        except ValueError:
            return None
    try:
        out = subprocess.run(["vm_stat"], capture_output=True, text=True, timeout=5).stdout
    except Exception:  # noqa: BLE001
        return None
    m = re.search(r"^Swapouts:\s+(\d+)", out, re.M)
    return int(m.group(1)) if m else None


def page_size() -> int:
    try:
        out = subprocess.run(["vm_stat"], capture_output=True, text=True, timeout=5).stdout
        m = re.search(r"page size of (\d+) bytes", out)
        if m:
            return int(m.group(1))
    except Exception:  # noqa: BLE001
        pass
    return 16384


def peak_rss_mb(children: bool = False) -> float | None:
    """Peak resident set of this process (or its waited-for children), in MiB.

    macOS reports ru_maxrss in BYTES, Linux in KiB. Note the caveat the audit
    hit: macOS shows a tiny RSS for a process whose pages are compressed, so this
    is a floor, not a ceiling."""
    try:
        import resource
        who = resource.RUSAGE_CHILDREN if children else resource.RUSAGE_SELF
        rss = resource.getrusage(who).ru_maxrss
    except Exception:  # noqa: BLE001
        return None
    if sys.platform == "darwin":
        return round(rss / (1024 * 1024), 1)
    return round(rss / 1024, 1)


def record(job: str, outcome: str, start: float | None = None, end: float | None = None,
           rows_changed: int | None = None, note: str = "", root: Path | str | None = None,
           **extra) -> dict:
    """Append one job-outcome line. Returns the dict that was written."""
    if outcome not in OUTCOMES:
        outcome = "failed"
        note = (note + " invalid_outcome").strip()
    end_ts = end if end is not None else time.time()
    line: dict = {
        "ts": iso(end_ts),
        "kind": "job",
        "job": _clean(job, 80),
        "start": iso(start) if start is not None else None,
        "end": iso(end_ts),
        "outcome": outcome,
        "rows_changed": rows_changed,
        "duration_s": int(end_ts - start) if start is not None else None,
        "pid": os.getpid(),
    }
    if note:
        line["note"] = _clean(note)
    for k, v in extra.items():
        if v is not None:
            line[k] = _clean(v)
    _append(line, root)
    return line


def note(event: str, root: Path | str | None = None, **fields) -> dict:
    """A non-outcome line: lock_break, mem_gate, lock_skip and the like."""
    line: dict = {"ts": iso(), "kind": "note", "event": _clean(event, 60), "pid": os.getpid()}
    for k, v in fields.items():
        if v is not None:
            line[k] = _clean(v)
    _append(line, root)
    return line


class JobTracker:
    """Context manager: times a job and writes its outcome line on exit.

        with JobTracker("lrcpwa") as jt:
            ...
            jt.rows_changed = 120       # optional
            jt.outcome = "no_change"    # optional; default ok
        # an unhandled exception is recorded as failed, then re-raised

    Records swap-out delta (pages -> MiB) and peak RSS alongside the outcome so
    the next audit has measurements instead of inference (audit O9)."""

    def __init__(self, job: str, root: Path | str | None = None):
        self.job = job
        self.root = root
        self.outcome: str | None = None
        self.rows_changed: int | None = None
        self.note = ""
        self.extra: dict = {}
        self._start = 0.0
        self._swap0: int | None = None

    def __enter__(self) -> "JobTracker":
        self._start = time.time()
        self._swap0 = swapouts_pages()
        return self

    def __exit__(self, exc_type, exc, tb) -> bool:
        outcome = self.outcome or ("failed" if exc_type else "ok")
        swap1 = swapouts_pages()
        extra = dict(self.extra)
        if self._swap0 is not None and swap1 is not None:
            extra["swapouts_start"] = self._swap0
            extra["swapouts_end"] = swap1
            extra["swap_out_mb"] = round((swap1 - self._swap0) * page_size() / (1024 * 1024), 1)
        extra["rss_peak_mb"] = peak_rss_mb()
        note_txt = self.note
        if exc_type:
            note_txt = (note_txt + f" {exc_type.__name__}").strip()
        record(self.job, outcome, start=self._start, rows_changed=self.rows_changed,
               note=note_txt, root=self.root, **extra)
        return False


def read_events(root: Path | str | None = None) -> list[dict]:
    """All parseable lines, oldest first (current file only). For the watcher and tests."""
    path = events_path(root)
    out: list[dict] = []
    try:
        for raw in path.read_text(encoding="utf-8").splitlines():
            raw = raw.strip()
            if not raw:
                continue
            try:
                out.append(json.loads(raw))
            except ValueError:
                continue
    except OSError:
        pass
    return out
