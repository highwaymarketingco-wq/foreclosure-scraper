"""The patched scripts/run_daily_vision.sh (audit 2026-09-21 O2, O6, O7, O10, O11).

run_daily_vision.sh could not be edited in place while the 09:30 job held the board lock, so the
change ships as a patch (docs/ops_fixes_2026-09-21.md, "Patches to apply"). This test runs the
wrapper against a throwaway repo, a stub `uv` and a local bare remote. It exercises whatever
scripts/run_daily_vision.sh contains and SKIPS while the patch has not been applied (it looks
for the job_event_begin marker). To check a patched copy before applying it:

    DAILY_VISION_WRAPPER=/path/to/patched/run_daily_vision.sh pytest tests/test_ops_daily_wrapper.py
"""
from __future__ import annotations

import os
import shutil
import stat
import subprocess
import sys
import time
from pathlib import Path

import pytest

from tests._ops_helpers import REPO, _run, git_log, job_events, make_env, make_repo

WRAPPER = Path(os.environ.get("DAILY_VISION_WRAPPER") or (REPO / "scripts" / "run_daily_vision.sh"))

pytestmark = [
    pytest.mark.skipif(sys.platform != "darwin", reason="scripts target macOS"),
    pytest.mark.skipif("job_event_begin dailyvision" not in WRAPPER.read_text(),
                       reason="run_daily_vision.sh patch (ops_patches/run_daily_vision.sh.patch) not applied yet"),
]

STUB = r'''#!/bin/sh
echo "uv $*" >> "$STUB_UV_LOG"
commit_board() {
  printf 'x%s' "$(date +%s%N 2>/dev/null || date +%s)" >> "$FORECLOSURE_ROOT/docs/listings_detail.json.gz"
  git -C "$FORECLOSURE_ROOT" add docs >/dev/null 2>&1
  git -C "$FORECLOSURE_ROOT" commit -q -m "$1" >/dev/null 2>&1
}
case "$*" in
  *daily_api_refresh.py*)
    echo "deferred=${BOARD_PUSH_DEFERRED:-unset} lock_held=$([ -d "$FORECLOSURE_ROOT/logs/.board.lock" ] && echo yes || echo no)" >> "$FORECLOSURE_ROOT/logs/stub_env.txt"
    [ -n "$STUB_API_TEXT" ] && printf '%s\n' "$STUB_API_TEXT"
    [ "$STUB_API_COMMIT" = "1" ] && commit_board "daily api refresh: stub"
    exit "${STUB_API_RC:-0}" ;;
  *patch_vision_gemini.py*)
    echo "vision_max_seconds=${VISION_MAX_SECONDS:-unset}" >> "$FORECLOSURE_ROOT/logs/stub_env.txt"
    [ "$STUB_VISION_COMMIT" = "1" ] && commit_board "daily vision: stub"
    exit "${STUB_VISION_RC:-0}" ;;
esac
exit 0
'''


def _setup(tmp_path, extra=None):
    root = make_repo(tmp_path)
    shutil.copyfile(WRAPPER, root / "scripts" / "run_daily_vision.sh")
    (root / "scripts" / "run_daily_vision.sh").chmod(0o755)
    env = make_env(root, extra)
    uv = Path(env["PATH"].split(":")[0]) / "uv"
    uv.write_text(STUB)
    uv.chmod(uv.stat().st_mode | stat.S_IXUSR)
    stubs = uv.parent
    (stubs / "osascript").write_text('#!/bin/sh\necho "$*" >> "$FORECLOSURE_ROOT/logs/notifications.txt"\n')
    (stubs / "osascript").chmod(0o755)
    return root, env


def _run_wrapper(root, env):
    return subprocess.run(["/bin/bash", str(root / "scripts" / "run_daily_vision.sh")], capture_output=True,
                          text=True, env=env, cwd=str(root), timeout=180)


def test_a_clean_day_runs_both_phases_pushes_outside_the_lock_and_reports_ok(tmp_path):
    root, env = _setup(tmp_path, {"STUB_API_COMMIT": "1", "STUB_VISION_COMMIT": "1"})
    hook = root / ".git" / "hooks" / "pre-push"
    hook.write_text('#!/bin/sh\nR=$(git rev-parse --show-toplevel)\n'
                    '[ -d "$R/logs/.board.lock" ] && echo LOCKED >> "$R/logs/push_lock_state.txt" || '
                    'echo FREE >> "$R/logs/push_lock_state.txt"\n')
    hook.chmod(0o755)
    out = _run_wrapper(root, env)
    assert out.returncode == 0, out.stdout + out.stderr
    (ev,) = job_events(root, "dailyvision")
    assert ev["outcome"] == "ok"
    stub_env = (root / "logs" / "stub_env.txt").read_text()
    assert "deferred=1" in stub_env, "the python publishers must COMMIT but leave the push to the wrapper"
    assert "lock_held=yes" in stub_env
    assert "vision_max_seconds=5400" in stub_env, "vision is boxed to 90 minutes"
    assert (root / "logs" / "push_lock_state.txt").read_text().split() == ["FREE"], "the push must run OUTSIDE the lock"
    assert _run(["git", "rev-parse", "HEAD"], cwd=root).stdout == _run(["git", "rev-parse", "origin/main"], cwd=root).stdout
    assert not (root / "logs" / ".board.lock").exists()


def test_tuesday_and_friday_are_no_longer_skipped():
    text = WRAPPER.read_text()
    code = [ln for ln in text.splitlines() if not ln.lstrip().startswith("#")]
    assert not any("FULL_RUN_DAYS" in ln or "date +%u" in ln for ln in code), \
        "the Tue/Fri skip was dead time: the weekly job is a popup nobody has to answer"


def test_the_count_guard_a_scorer_failure_and_a_failed_api_phase_fail_loudly(tmp_path):
    root, env = _setup(tmp_path, {"STUB_API_TEXT": "RuntimeError: COUNT GUARD: refusing to write 68,264 listings",
                                  "STUB_API_RC": "1"})
    out = _run_wrapper(root, env)
    assert out.returncode == 4, out.stdout + out.stderr
    ev = job_events(root, "dailyvision")[-1]
    assert ev["outcome"] == "failed" and "count_guard" in ev["note"] and "api_rc=1" in ev["note"]
    assert "daily vision" in (root / "logs" / "notifications.txt").read_text()
    assert "--phase" not in (root / "logs" / "stub_uv_calls.txt").read_text()
    assert "patch_vision_gemini.py" in (root / "logs" / "stub_uv_calls.txt").read_text(), \
        "vision still runs on yesterday's data, as before"
    root2, env2 = _setup(tmp_path / "b", {"STUB_API_TEXT": "SCORE_BOARD_FAILED: tiers on this board are STALE"})
    _run_wrapper(root2, env2)
    assert "score_board_failed" in job_events(root2, "dailyvision")[-1]["note"]


def test_more_than_four_carried_over_sources_is_a_failure_and_four_is_not(tmp_path):
    five = "⚠ carryover (fresh<3, keeping prior): fannie_homepath=0, irs_treasury=0, sc_public_index=0, tranzon=0, williams=0"
    root, env = _setup(tmp_path, {"STUB_API_TEXT": five})
    out = _run_wrapper(root, env)
    assert out.returncode == 4
    ev = job_events(root, "dailyvision")[-1]
    assert ev["outcome"] == "failed" and "carried_over=5" in ev["note"]
    four = "⚠ carryover (fresh<3, keeping prior): fannie_homepath=0, irs_treasury=0, sc_public_index=0, tranzon=0"
    root2, env2 = _setup(tmp_path / "b", {"STUB_API_TEXT": four})
    out2 = _run_wrapper(root2, env2)
    assert out2.returncode == 0 and job_events(root2, "dailyvision")[-1]["outcome"] == "ok"


def test_a_push_that_cannot_land_is_push_failed_and_the_commit_stays_local(tmp_path):
    root, env = _setup(tmp_path, {"STUB_API_COMMIT": "1"})
    _run(["git", "remote", "set-url", "origin", str(tmp_path / "nowhere.git")], cwd=root)
    out = _run_wrapper(root, env)
    assert out.returncode == 0, out.stdout + out.stderr
    assert job_events(root, "dailyvision")[-1]["outcome"] == "push_failed"
    assert git_log(root, 1)[0] == "daily api refresh: stub"


def test_a_busy_lock_or_missing_uv_is_reported_not_silent(tmp_path):
    root, env = _setup(tmp_path)
    d = root / "logs" / ".board.lock"
    d.mkdir(parents=True)
    now = int(time.time())
    (d / "pid").write_text(f"{os.getpid()}\nresolver_backfill_parcel\n{now}\n{now}\n21600\nT\n")
    out = _run_wrapper(root, env)
    assert out.returncode == 0
    ev = job_events(root, "dailyvision")[-1]
    assert ev["outcome"] == "skipped_lock" and "resolver_backfill_parcel" in ev["note"]
    assert not (root / "logs" / "stub_uv_calls.txt").exists()
    root2, env2 = _setup(tmp_path / "b")
    env2["PATH"] = "/usr/bin:/bin:/usr/sbin:/sbin"
    env2["HOME"] = str(tmp_path / "emptyhome")
    out2 = _run_wrapper(root2, env2)
    assert out2.returncode == 127
    ev2 = job_events(root2, "dailyvision")[-1]
    assert ev2["outcome"] == "failed" and ev2["note"] == "uv_not_found"


def test_a_killed_run_still_leaves_a_failed_event(tmp_path):
    """8/27, 9/7, 9/10 and 9/17: the job died and left no exit line and no event."""
    root, env = _setup(tmp_path)
    (Path(env["PATH"].split(":")[0]) / "uv").write_text('#!/bin/sh\nkill -9 $PPID\nsleep 5\n')
    _run_wrapper(root, env)
    evs = job_events(root, "dailyvision")
    assert evs and evs[-1]["outcome"] in ("failed",), evs
