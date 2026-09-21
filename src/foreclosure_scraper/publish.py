"""Bounded git push for the Python publishers (audit 2026-09-21 O7).

The shell twin is scripts/publish_helper.sh (publish_push). daily_api_refresh.py and
patch_vision_gemini.py each did

    git pull --rebase --autostash origin main
    git push origin main            # no timeout, INSIDE the board lock

One publish is 118 to 172 MB. On 2026-09-20 the pushes failed with "unexpected disconnect
while reading sideband packet" and "Could not resolve host", each printed and exited 0, and a
stalled push would have held the board lock for as long as git chose to wait while every other
scheduled job skipped. This module bounds every network step and reports the outcome instead of
printing and moving on.

    ok, tail = push_with_retries(root)

`ok` False means the commit stays LOCAL: the next publisher's push carries it. Callers print
"PUBLISH_PUSH_FAILED" so scripts/run_daily_vision.sh can turn it into a push_failed job event.

Set BOARD_PUSH_DEFERRED=1 (run_daily_vision.sh does) and the publishers COMMIT but do not push;
the wrapper releases the board lock and pushes with scripts/publish_helper.sh, which is the whole
point of moving the push out of the lock.
"""
from __future__ import annotations

import os
import subprocess
import time
from pathlib import Path


def push_deferred() -> bool:
    return os.environ.get("BOARD_PUSH_DEFERRED", "").strip().lower() in ("1", "true", "yes")


def ensure_git_config(root: str | Path) -> None:
    """A stalled transfer aborts after http.lowSpeedTime seconds below http.lowSpeedLimit
    bytes/s. Local repo config only."""
    for key, val in (("http.lowSpeedLimit", os.environ.get("PUBLISH_LOW_SPEED_LIMIT", "1000")),
                     ("http.lowSpeedTime", os.environ.get("PUBLISH_LOW_SPEED_TIME", "120"))):
        try:
            subprocess.run(["git", "-C", str(root), "config", "--local", key, val],
                           capture_output=True, timeout=30)
        except Exception:  # noqa: BLE001
            pass


def _git(root, *args, timeout, check=False):
    return subprocess.run(["git", "-C", str(root), *args], capture_output=True, text=True,
                          timeout=timeout, check=check)


def push_with_retries(root: str | Path, attempts: int | None = None,
                      fetch_timeout: float | None = None,
                      push_timeout: float | None = None,
                      backoff_base: float | None = None) -> tuple[bool, str]:
    """Fetch, rebase if origin moved, push. Every step has a timeout; up to `attempts`
    tries with 30 s, 90 s, 180 s back-off (PUBLISH_BACKOFF_BASE scales it). Never raises."""
    attempts = attempts or int(os.environ.get("PUBLISH_PUSH_ATTEMPTS", "3"))
    fetch_timeout = fetch_timeout or float(os.environ.get("PUBLISH_FETCH_TIMEOUT", "300"))
    push_timeout = push_timeout or float(os.environ.get("PUBLISH_PUSH_TIMEOUT", "900"))
    backoff_base = backoff_base if backoff_base is not None else float(os.environ.get("PUBLISH_BACKOFF_BASE", "30"))
    ensure_git_config(root)
    tail = ""
    for i in range(1, attempts + 1):
        try:
            _git(root, "fetch", "-q", "origin", "main", timeout=fetch_timeout)
            behind = _git(root, "rev-list", "--count", "HEAD..origin/main", timeout=60).stdout.strip()
            if behind.isdigit() and int(behind) > 0:
                # The caller holds the board lock here (or is the deferred wrapper that
                # re-took it), so rewriting the working tree is safe.
                r = _git(root, "rebase", "--autostash", "origin/main", timeout=600)
                if r.returncode != 0:
                    _git(root, "rebase", "--abort", timeout=60)
                    tail = "rebase onto origin/main failed"
            p = _git(root, "push", "origin", "main", timeout=push_timeout)
            if p.returncode == 0:
                return True, ""
            tail = "\n".join((p.stdout + p.stderr).strip().splitlines()[-3:])
        except subprocess.TimeoutExpired as exc:
            tail = f"timed out after {int(exc.timeout)}s: {' '.join(str(a) for a in exc.cmd[-3:])}"
        except Exception as exc:  # noqa: BLE001
            tail = f"{type(exc).__name__}: {exc}"
        if i < attempts:
            time.sleep(backoff_base * (i * i + i) / 2)
    return False, tail


def manifest_pathspec(root: str | Path) -> list[str]:
    """['docs/board.manifest.json'] when it exists or is tracked, else []. Staged with the
    rest of the payload so a commit that carries a new board carries the manifest that
    describes it (a stale committed manifest makes a gz-only reader refuse the board)."""
    root = Path(root)
    rel = "docs/board.manifest.json"
    if (root / rel).exists():
        return [rel]
    try:
        r = subprocess.run(["git", "-C", str(root), "ls-files", "--error-unmatch", rel],
                           capture_output=True, timeout=30)
        return [rel] if r.returncode == 0 else []
    except Exception:  # noqa: BLE001
        return []
