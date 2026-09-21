"""src/foreclosure_scraper/publish.py: the bounded push the Python publishers use (audit O7)."""
from __future__ import annotations

import os
import subprocess
import time

import pytest

from foreclosure_scraper import publish
from tests._ops_helpers import make_repo, _run


@pytest.fixture(autouse=True)
def _fast(monkeypatch):
    monkeypatch.setenv("PUBLISH_BACKOFF_BASE", "0")
    for k in ("GIT_CONFIG_GLOBAL",):
        monkeypatch.setenv(k, "/dev/null")


def _commit(root, msg="change"):
    (root / "docs" / "listings.json.gz").write_bytes(msg.encode())
    _run(["git", "add", "docs"], cwd=root)
    _run(["git", "commit", "-q", "-m", msg], cwd=root)


def test_push_succeeds_and_sets_the_low_speed_limits(tmp_path):
    root = make_repo(tmp_path, scripts=False)
    _commit(root)
    ok, tail = publish.push_with_retries(root, attempts=1)
    assert ok and tail == ""
    assert _run(["git", "rev-parse", "HEAD"], cwd=root).stdout == _run(["git", "rev-parse", "origin/main"], cwd=root).stdout
    cfg = _run(["git", "config", "--local", "--list"], cwd=root).stdout
    assert "http.lowspeedlimit=1000" in cfg and "http.lowspeedtime=120" in cfg


def test_a_failing_remote_is_reported_after_the_retries_never_raised(tmp_path):
    root = make_repo(tmp_path, scripts=False)
    _commit(root)
    _run(["git", "remote", "set-url", "origin", str(tmp_path / "nowhere.git")], cwd=root)
    t0 = time.time()
    ok, tail = publish.push_with_retries(root, attempts=2)
    assert ok is False and tail
    assert time.time() - t0 < 30


def test_a_moved_origin_is_rebased_before_the_push(tmp_path):
    root = make_repo(tmp_path, scripts=False)
    other = tmp_path / "other"
    _run(["git", "clone", "-q", str(tmp_path / "origin.git"), str(other)])
    (other / "x.txt").write_text("x")
    _run(["git", "add", "-A"], cwd=other)
    _run(["git", "-c", "user.name=o", "-c", "user.email=o@e.com", "commit", "-q", "-m", "other"], cwd=other)
    _run(["git", "push", "-q", "origin", "main"], cwd=other)
    _commit(root, "mine")
    ok, tail = publish.push_with_retries(root, attempts=1)
    assert ok, tail
    log = _run(["git", "log", "--format=%s", "-3"], cwd=root).stdout.split("\n")
    assert log[:2] == ["mine", "other"]


def test_a_stalled_push_is_killed_by_the_timeout(tmp_path):
    root = make_repo(tmp_path, scripts=False)
    _commit(root)
    hook = root / ".git" / "hooks" / "pre-push"
    hook.write_text("#!/bin/sh\nsleep 30\n")
    hook.chmod(0o755)
    t0 = time.time()
    ok, tail = publish.push_with_retries(root, attempts=1, push_timeout=2)
    assert ok is False and "timed out after 2s" in tail
    assert time.time() - t0 < 15


def test_deferral_flag_and_manifest_pathspec(tmp_path, monkeypatch):
    monkeypatch.delenv("BOARD_PUSH_DEFERRED", raising=False)
    assert publish.push_deferred() is False
    monkeypatch.setenv("BOARD_PUSH_DEFERRED", "1")
    assert publish.push_deferred() is True
    root = make_repo(tmp_path, scripts=False)
    assert publish.manifest_pathspec(root) == []
    (root / "docs" / "board.manifest.json").write_text("{}")
    assert publish.manifest_pathspec(root) == ["docs/board.manifest.json"]
    _run(["git", "add", "docs/board.manifest.json"], cwd=root)
    _run(["git", "commit", "-q", "-m", "m"], cwd=root)
    (root / "docs" / "board.manifest.json").unlink()
    assert publish.manifest_pathspec(root) == ["docs/board.manifest.json"], "tracked-but-deleted must still be staged"
