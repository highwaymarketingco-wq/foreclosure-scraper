#!/usr/bin/env python3
"""Run the full pytest suite in sequential chunks and record the result for the pre-run gate.

WHY (audit 2026-10-09, pipeline_gate)
    "Full suite on 7d5b7ae1: 9,698 passed, 0 failed (651 files, 6 sequential chunks)" lived only in
    HANDOFF prose, so nothing could tell whether the commit about to be pinned was the one tested.
    This writes data/test_results/latest.json (git-ignored) with the commit, whether the tree was
    clean, and the counts; scripts/prerun_gate.py refuses a run unless it is green and no code
    changed between that commit and the pin.

    Chunks run one after another (never in parallel) so an 8 GB Mac stays inside its memory: one
    pytest process per chunk, each exiting before the next starts.

USAGE
    uv run python scripts/run_test_suite.py                 # every tests/test_*.py, 6 chunks
    uv run python scripts/run_test_suite.py --chunks 8
    uv run python scripts/run_test_suite.py --files tests/test_a.py tests/test_b.py   # a TARGETED
        record (kind "targeted"): the gate never accepts it as the full suite
Exit 0 when every chunk passed, 1 otherwise.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
OUT = REPO / "data" / "test_results" / "latest.json"

_SUMMARY = re.compile(r"(\d+) (passed|failed|errors?|skipped|xfailed|xpassed|deselected|warnings?)")
_FAILED_LINE = re.compile(r"^(FAILED|ERROR) (\S+)")


def parse_summary(text: str) -> dict:
    """Counts from pytest's last summary line(s); FAILED/ERROR node ids from the short summary."""
    counts = {"passed": 0, "failed": 0, "errors": 0, "skipped": 0, "xfailed": 0, "xpassed": 0}
    tail = "\n".join(text.strip().splitlines()[-5:])
    for n, kind in _SUMMARY.findall(tail):
        k = {"error": "errors", "errors": "errors"}.get(kind, kind)
        if k in counts:
            counts[k] = int(n)
    failed = [m.group(2) for line in text.splitlines() if (m := _FAILED_LINE.match(line.strip()))]
    counts["failed_ids"] = failed[:200]
    return counts


def chunked(files: list[str], n: int) -> list[list[str]]:
    n = max(1, min(n, len(files) or 1))
    return [files[i::n] for i in range(n)]


def _git(*args) -> str:
    try:
        return subprocess.run(["git", *args], cwd=REPO, capture_output=True, text=True,
                              timeout=60).stdout.strip()
    except (OSError, subprocess.SubprocessError):
        return ""


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--chunks", type=int, default=6)
    ap.add_argument("--files", nargs="*", default=None)
    ap.add_argument("--out", default=str(OUT))
    ap.add_argument("--pytest-args", default="-q -p no:cacheprovider")
    a = ap.parse_args(argv)

    kind = "targeted" if a.files else "full"
    files = sorted(a.files) if a.files else sorted(str(p.relative_to(REPO))
                                                   for p in (REPO / "tests").glob("test_*.py"))
    commit = _git("rev-parse", "HEAD")
    dirty = bool(_git("status", "--porcelain", "--untracked-files=no"))
    started = datetime.now(timezone.utc).isoformat(timespec="seconds")
    t0 = time.monotonic()
    total = {"passed": 0, "failed": 0, "errors": 0, "skipped": 0, "xfailed": 0, "xpassed": 0}
    failed_ids: list[str] = []
    chunk_rcs = []
    for i, chunk in enumerate(chunked(files, a.chunks)):
        cmd = [sys.executable, "-m", "pytest", *a.pytest_args.split(), *chunk]
        print(f"chunk {i + 1}: {len(chunk)} files", flush=True)
        r = subprocess.run(cmd, cwd=REPO, capture_output=True, text=True, env=os.environ.copy())
        res = parse_summary(r.stdout + "\n" + r.stderr)
        for k in total:
            total[k] += res[k]
        failed_ids += res["failed_ids"]
        # rc 5 = no tests collected in that chunk (all skipped modules): not a failure
        chunk_rcs.append(r.returncode)
        print(f"  rc={r.returncode} " + " ".join(f"{k}={res[k]}" for k in total), flush=True)
    green = total["failed"] == 0 and total["errors"] == 0 and all(rc in (0, 5) for rc in chunk_rcs)
    doc = {"kind": kind, "commit": commit, "tree_dirty": dirty, "started_at": started,
           "finished_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
           "seconds": round(time.monotonic() - t0), "files": len(files), "chunks": len(chunk_rcs),
           "chunk_rcs": chunk_rcs, **total, "failed_ids": failed_ids[:200], "green": green}
    out = Path(a.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    tmp = out.with_suffix(".tmp")
    tmp.write_text(json.dumps(doc, indent=1) + "\n")
    os.replace(tmp, out)
    print(f"{'GREEN' if green else 'NOT GREEN'}: {total} -> {out}")
    return 0 if green else 1


if __name__ == "__main__":
    sys.exit(main())
