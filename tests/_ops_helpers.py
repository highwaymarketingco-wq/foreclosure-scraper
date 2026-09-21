"""Shared scaffolding for the operations tests: a throwaway 'repo' with the real scripts,
a bare git remote, a stub `uv`, and helpers to read logs/job_events.jsonl.

Nothing here touches the real repo, the real docs/, the real logs/ or the real
~/Library/LaunchAgents: every run gets its own root and its own HOME.
"""
from __future__ import annotations

import json
import os
import shutil
import stat
import subprocess
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent

STUB_UV = r'''#!/bin/sh
# Stand-in for uv. STUB_UV_MODE picks the behaviour; every call is appended to $STUB_UV_LOG.
echo "uv $*" >> "${STUB_UV_LOG:-/dev/null}"
phase=""
for a in "$@"; do
  case "$prev" in --phase) phase="$a" ;; esac
  prev="$a"
done
mode="${STUB_UV_MODE:-change}"
if [ -n "$phase" ]; then eval "pm=\${STUB_UV_MODE_PHASE_$phase:-}"; [ -n "$pm" ] && mode="$pm"; fi
touch_board() { printf 'x%s' "$(date +%s%N 2>/dev/null || date +%s)" >> "$FORECLOSURE_ROOT/docs/listings.json.gz"; }
case "$mode" in
  change)   touch_board ;;
  meta)     printf ' ' >> "$FORECLOSURE_ROOT/docs/run_meta.json" ;;
  nochange) ;;
  fail)     exit 3 ;;
  sleep)    sleep 30 ;;
  lockcheck) [ -d "$FORECLOSURE_ROOT/logs/.board.lock" ] && echo "LOCK_HELD_DURING_$phase" >> "$FORECLOSURE_ROOT/logs/stub_phases.txt" || echo "LOCK_FREE_DURING_$phase" >> "$FORECLOSURE_ROOT/logs/stub_phases.txt"; touch_board ;;
esac
[ -n "$FAMILY_ROWS_FILE" ] && [ "$phase" = "scrape" ] && printf '42' > "$FAMILY_ROWS_FILE"
exit 0
'''


def _run(cmd, cwd=None, env=None, check=True, **kw):
    return subprocess.run(cmd, cwd=cwd, env=env, check=check, capture_output=True, text=True, **kw)


def make_env(root: Path, extra: dict | None = None) -> dict:
    """Environment for a wrapper run: own HOME, stub uv first on PATH, scratch job-event file
    left at its default (root/logs/job_events.jsonl) so tests read what production would write."""
    home = root.parent / "home"
    home.mkdir(exist_ok=True)
    stubs = root.parent / "stubs"
    stubs.mkdir(exist_ok=True)
    uv = stubs / "uv"
    if not uv.exists():
        uv.write_text(STUB_UV)
        uv.chmod(uv.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    env = {k: v for k, v in os.environ.items()
           if not k.startswith(("BOARD_", "FORECLOSURE_", "FAMILY_", "JOB_EVENT", "STUB_", "PUBLISH_",
                                "LRCPWA_", "SOS_", "PARCELCACHE_", "BACKUP_"))}
    env.update({
        "HOME": str(home),
        "FORECLOSURE_ROOT": str(root),
        "PATH": f"{stubs}:/usr/bin:/bin:/usr/sbin:/sbin",
        "BOARD_MEM_GATE": "off",
        "STUB_UV_LOG": str(root / "logs" / "stub_uv_calls.txt"),
        "PUBLISH_BACKOFF_BASE": "0",
        "PUBLISH_PUSH_ATTEMPTS": "2",
        "PUBLISH_FETCH_TIMEOUT": "20",
        "PUBLISH_PUSH_TIMEOUT": "30",
        "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@example.com",
        "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@example.com",
        "GIT_CONFIG_GLOBAL": "/dev/null", "GIT_CONFIG_NOSYSTEM": "1",
    })
    if extra:
        env.update(extra)
    return env


def make_repo(tmp_path: Path, scripts=True) -> Path:
    """<tmp>/repo: real scripts/, a docs/ payload, git history, and a bare origin."""
    root = tmp_path / "repo"
    (root / "docs" / "detail_shards").mkdir(parents=True)
    (root / "logs").mkdir()
    if scripts:
        shutil.copytree(REPO / "scripts", root / "scripts",
                        ignore=shutil.ignore_patterns("__pycache__", "*.json", "screaming_frog", "*.pyc"))
    for name, body in (("listings.json.gz", b"board-v1"), ("listings_detail.json.gz", b"detail-v1"),
                       ("listings_slim.json.gz", b"slim-v1")):
        (root / "docs" / name).write_bytes(body)
    (root / "docs" / "run_meta.json").write_text('{"total": 5, "run_time": "t"}')
    (root / "docs" / "detail_shards" / "00000.json.gz").write_bytes(b"shard0-v1")
    origin = tmp_path / "origin.git"
    _run(["git", "init", "-q", "--bare", "-b", "main", str(origin)])
    _run(["git", "init", "-q", "-b", "main"], cwd=root)
    _run(["git", "remote", "add", "origin", str(origin)], cwd=root)
    (root / ".gitignore").write_text("logs/\n")
    _run(["git", "add", "-A"], cwd=root)
    _run(["git", "-c", "user.name=t", "-c", "user.email=t@example.com", "commit", "-q", "-m", "base"], cwd=root)
    _run(["git", "push", "-q", "origin", "main"], cwd=root)
    _run(["git", "config", "user.name", "t"], cwd=root)
    _run(["git", "config", "user.email", "t@example.com"], cwd=root)
    return root


def events(root: Path) -> list:
    p = root / "logs" / "job_events.jsonl"
    if not p.exists():
        return []
    return [json.loads(x) for x in p.read_text().splitlines() if x.strip()]


def job_events(root: Path, job: str | None = None) -> list:
    return [e for e in events(root) if e.get("kind") == "job" and (job is None or e.get("job") == job)]


def git_log(root: Path, n=5) -> list:
    return _run(["git", "log", f"-{n}", "--format=%s"], cwd=root).stdout.splitlines()


def origin_head(root: Path) -> str:
    return _run(["git", "rev-parse", "origin/main"], cwd=root).stdout.strip()
