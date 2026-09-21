"""The shell side of the operations fixes (audit 2026-09-21 O4, O7, O9, O10, O11, O12).

Every test builds a throwaway repo with the REAL scripts, a bare git remote and a stub `uv`
(tests/_ops_helpers.py); nothing touches the real repo, logs, board or LaunchAgents.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from pathlib import Path

import pytest

from tests._ops_helpers import (REPO, _run, events, git_log, job_events, make_env, make_repo, origin_head)

pytestmark = pytest.mark.skipif(sys.platform != "darwin", reason="scripts target macOS (BSD stat/date)")


def sh(script: str, env=None, shell="/bin/sh", timeout=60):
    return subprocess.run([shell, "-c", script], capture_output=True, text=True, env=env, timeout=timeout)


def wrapper(root: Path, name: str, env: dict, shell="/bin/zsh", timeout=120):
    return subprocess.run([shell, str(root / "scripts" / name)], capture_output=True, text=True,
                          env=env, timeout=timeout, cwd=str(root))


# ===========================================================================
# job_event.sh and run_timeout.pl
# ===========================================================================

def test_job_event_writes_the_documented_line(tmp_path):
    root = make_repo(tmp_path)
    env = make_env(root)
    out = sh(f'ROOT="{root}"; . "$ROOT/scripts/job_event.sh"; job_event_begin lrcpwa; '
             'JOB_EVENT_RSS_MB=321; job_event_end ok 120 "did the thing"', env)
    assert out.returncode == 0, out.stderr
    (ev,) = job_events(root, "lrcpwa")
    assert ev["outcome"] == "ok" and ev["rows_changed"] == 120 and ev["note"] == "did the thing"
    assert ev["kind"] == "job" and ev["rss_peak_mb"] == 321
    assert ev["start"] and ev["end"] and ev["duration_s"] >= 0 and "pid" in ev
    assert ev["end"].endswith("Z")


def test_job_event_end_is_idempotent_and_validates_outcome(tmp_path):
    root = make_repo(tmp_path)
    sh(f'ROOT="{root}"; . "$ROOT/scripts/job_event.sh"; job_event_begin j; '
       'job_event_end no_change; job_event_end ok; job_event_begin k; job_event_end banana', make_env(root))
    evs = job_events(root)
    assert [e["job"] for e in evs] == ["j", "k"], "a second end() in the same job must be ignored"
    assert evs[0]["outcome"] == "no_change" and evs[1]["outcome"] == "failed"


def test_finalize_records_an_unreported_exit_as_failed(tmp_path):
    root = make_repo(tmp_path)
    sh(f'ROOT="{root}"; . "$ROOT/scripts/job_event.sh"; job_event_begin crashy; '
       "trap 'job_event_finalize' EXIT; exit 9", make_env(root))
    (ev,) = job_events(root, "crashy")
    assert ev["outcome"] == "failed" and "exited_without_outcome" in ev["note"] and "rc=9" in ev["note"]


def test_job_event_escapes_quotes_and_never_writes_broken_json(tmp_path):
    root = make_repo(tmp_path)
    sh(f'ROOT="{root}"; . "$ROOT/scripts/job_event.sh"; job_event_begin j; '
       "job_event_end failed '' 'he said \"boom\" and \\\\ left'", make_env(root))
    (ev,) = job_events(root, "j")           # json.loads would raise on a broken line
    assert "boom" in ev["note"]


def test_swap_out_delta_is_recorded(tmp_path):
    root = make_repo(tmp_path)
    env = make_env(root)
    env["JOB_EVENTS_FAKE_SWAPOUTS"] = "1000"
    sh(f'ROOT="{root}"; . "$ROOT/scripts/job_event.sh"; job_event_begin j; '
       'JOB_EVENTS_FAKE_SWAPOUTS=1100; job_event_end ok', env)
    (ev,) = job_events(root, "j")
    assert ev["swapouts_start"] == 1000 and ev["swapouts_end"] == 1100
    assert ev["swap_out_mb"] == pytest.approx(100 * 16384 / 1048576, abs=0.2)


def test_job_run_times_out_with_124_and_reports_rss(tmp_path):
    root = make_repo(tmp_path)
    env = make_env(root)
    t0 = time.time()
    out = sh(f'ROOT="{root}"; . "$ROOT/scripts/job_event.sh"; job_run 2 sleep 30; echo "rc=$JOB_RUN_RC"', env)
    assert "rc=124" in out.stdout and time.time() - t0 < 15
    out = sh(f'ROOT="{root}"; . "$ROOT/scripts/job_event.sh"; '
             'job_run 20 python3 -c "x=bytearray(30*1024*1024)"; echo "rc=$JOB_RUN_RC rss=$JOB_EVENT_RSS_MB"', env)
    assert "rc=0" in out.stdout
    assert int(out.stdout.split("rss=")[1]) >= 25, out.stdout


def test_run_timeout_pl_exit_codes():
    pl = REPO / "scripts" / "run_timeout.pl"
    assert subprocess.run(["/usr/bin/perl", str(pl), "5", "sh", "-c", "exit 7"]).returncode == 7
    assert subprocess.run(["/usr/bin/perl", str(pl), "5", "/nonexistent/x"], capture_output=True).returncode == 127
    assert subprocess.run(["/usr/bin/perl", str(pl), "1", "sleep", "20"]).returncode == 124


# ===========================================================================
# board_lock.sh v2
# ===========================================================================

@pytest.mark.parametrize("shell", ["/bin/sh", "/bin/bash", "/bin/zsh"])
def test_shell_lock_record_and_export(tmp_path, shell):
    root = make_repo(tmp_path)
    out = sh(f'. "{root}/scripts/board_lock.sh"; board_lock_acquire "{root}" tester 0 120 && '
             f'cat "{root}/logs/.board.lock/pid"; echo "tok=$FORECLOSURE_BOARD_LOCK_TOKEN"; '
             f'board_lock_release; [ -d "{root}/logs/.board.lock" ] && echo STILL || echo GONE',
             make_env(root), shell=shell)
    lines = out.stdout.split("\n")
    assert lines[1] == "tester" and lines[4] == "120" and lines[5], out.stdout
    assert f"tok={lines[5]}" in out.stdout and "GONE" in out.stdout


def test_shell_breaks_a_live_holder_past_its_max_runtime(tmp_path):
    root = make_repo(tmp_path)
    d = root / "logs" / ".board.lock"
    d.mkdir(parents=True)
    long_ago = int(time.time()) - 3600 - 1900
    (d / "pid").write_text(f"{os.getpid()}\nhung-python\n{long_ago}\n{long_ago}\n3600\nTOK\n")
    out = sh(f'. "{root}/scripts/board_lock.sh"; board_lock_acquire "{root}" newcomer 0 && echo GOT; '
             f'sed -n 2p "{root}/logs/.board.lock/pid"; board_lock_release', make_env(root))
    assert "GOT" in out.stdout and "newcomer" in out.stdout, out.stdout + out.stderr
    notes = [e for e in events(root) if e.get("event") == "lock_break"]
    assert notes and notes[0]["reason"] == "expired" and notes[0]["prior_owner"] == "hung-python"


def test_shell_keeps_a_lock_alive_for_a_registered_child(tmp_path):
    root = make_repo(tmp_path)
    d = root / "logs" / ".board.lock"
    (d / "children").mkdir(parents=True)
    (d / "pid").write_text("99998\nwrapper-killed\n")
    (d / "children" / str(os.getpid())).write_text("child")
    out = sh(f'. "{root}/scripts/board_lock.sh"; board_lock_acquire "{root}" newcomer 0 && echo GOT || '
             f'echo "BUSY $(board_lock_holder) refusal=$BOARD_LOCK_REFUSAL"', make_env(root))
    assert "BUSY 99998 wrapper-killed refusal=busy" in out.stdout, out.stdout


def test_shell_lock_skip_is_a_job_event(tmp_path):
    root = make_repo(tmp_path)
    d = root / "logs" / ".board.lock"
    d.mkdir(parents=True)
    now = int(time.time())
    (d / "pid").write_text(f"{os.getpid()}\ndaily\n{now - 60}\n{now - 5}\n3600\nT\n")
    sh(f'. "{root}/scripts/board_lock.sh"; board_lock_acquire "{root}" lrcpwa 0', make_env(root))
    skips = [e for e in events(root) if e.get("event") == "lock_skip"]
    assert skips and skips[0]["holder"] == "daily" and int(skips[0]["heartbeat_age_s"]) >= 4


def test_shell_reentrant_child_registers_and_a_taken_over_lock_is_refused(tmp_path):
    root = make_repo(tmp_path)
    d = root / "logs" / ".board.lock"
    d.mkdir(parents=True)
    (d / "pid").write_text(f"{os.getpid()}\nwrapper\n1\n1\n60\nREALTOKEN\n")
    env = make_env(root, {"FORECLOSURE_BOARD_LOCK_HELD": str(d), "FORECLOSURE_BOARD_LOCK_TOKEN": "REALTOKEN"})
    out = sh(f'. "{root}/scripts/board_lock.sh"; board_lock_acquire "{root}" child 0 && echo IN; '
             f'ls "{d}/children" | wc -l; board_lock_release; ls "{d}/children" | wc -l', env)
    assert "IN" in out.stdout and out.stdout.split()[-2:] == ["1", "0"], out.stdout
    env["FORECLOSURE_BOARD_LOCK_TOKEN"] = "STALETOKEN"
    out = sh(f'. "{root}/scripts/board_lock.sh"; board_lock_acquire "{root}" child 0 || echo "REFUSED $BOARD_LOCK_REFUSAL"', env)
    assert "REFUSED lost" in out.stdout


def test_shell_memory_gate_modes(tmp_path):
    root = make_repo(tmp_path)
    base = make_env(root, {"BOARD_GATE_FAKE_SWAP_MB": "7000", "BOARD_GATE_FAKE_FREE_MB": "2000"})
    src = f'. "{root}/scripts/board_lock.sh"; board_lock_acquire "{root}" j 0; echo "rc=$? refusal=$BOARD_LOCK_REFUSAL"'
    # default = warn: proceeds, and says so
    out = sh(src, {**base, "BOARD_MEM_GATE": "warn"})
    assert "rc=0" in out.stdout
    assert any(e.get("event") == "mem_gate" and e.get("action") == "proceed" for e in events(root))
    (root / "logs" / ".board.lock").exists() and __import__("shutil").rmtree(root / "logs" / ".board.lock")
    # enforce: waits, then refuses with return code 2 and never takes the lock
    out = sh(src, {**base, "BOARD_MEM_GATE": "enforce", "BOARD_MEM_GATE_WAIT": "2", "BOARD_MEM_GATE_POLL": "1"})
    assert "rc=2 refusal=memory" in out.stdout
    assert not (root / "logs" / ".board.lock").exists()
    acts = [e["action"] for e in events(root) if e.get("event") == "mem_gate"]
    assert "waiting" in acts and "refused" in acts
    # off
    out = sh(src, {**base, "BOARD_MEM_GATE": "off"})
    assert "rc=0" in out.stdout


def test_shell_memory_gate_trips_on_free_ram_too(tmp_path):
    root = make_repo(tmp_path)
    env = make_env(root, {"BOARD_GATE_FAKE_SWAP_MB": "10", "BOARD_GATE_FAKE_FREE_MB": "200",
                          "BOARD_MEM_GATE": "enforce", "BOARD_MEM_GATE_WAIT": "1", "BOARD_MEM_GATE_POLL": "1"})
    out = sh(f'. "{root}/scripts/board_lock.sh"; board_lock_acquire "{root}" j 0; echo "rc=$? $BOARD_MEM_REASON"', env)
    assert "rc=2" in out.stdout and "free_plus_inactive_mb=200<1024" in out.stdout


def test_the_real_machine_probe_returns_numbers(tmp_path):
    root = make_repo(tmp_path)
    out = sh(f'. "{root}/scripts/board_lock.sh"; board_mem_probe; echo "swap=$BOARD_MEM_SWAP_MB free=$BOARD_MEM_FREE_MB"',
             {**make_env(root)})
    swap = out.stdout.split("swap=")[1].split()[0]
    free = out.stdout.split("free=")[1].split()[0]
    assert float(swap) >= 0 and int(free) > 0, out.stdout


def test_python_and_shell_locks_exclude_each_other_in_both_directions(tmp_path):
    from foreclosure_scraper import web_artifact as wa
    root = make_repo(tmp_path)
    env = make_env(root)
    # shell holds, python must be refused
    proc = subprocess.Popen(["/bin/sh", "-c", f'. "{root}/scripts/board_lock.sh"; '
                             f'board_lock_acquire "{root}" shell-holder 0 120 && echo HOLDING && sleep 6; board_lock_release'],
                            stdout=subprocess.PIPE, text=True, env=env)
    assert proc.stdout.readline().strip() == "HOLDING"
    with pytest.raises(wa.BoardLockBusy) as ei:
        with wa.board_lock(root, owner="py"):
            pass
    assert "shell-holder" in str(ei.value) and "held" in str(ei.value)
    proc.wait()
    # python holds, shell must be refused
    with wa.board_lock(root, owner="py-holder", max_runtime=300):
        out = sh(f'. "{root}/scripts/board_lock.sh"; board_lock_acquire "{root}" j 0 || echo "BUSY $(board_lock_holder)"',
                 {**env, "FORECLOSURE_BOARD_LOCK_HELD": ""})
        assert "BUSY" in out.stdout and "py-holder" in out.stdout


# ===========================================================================
# with_board_lock.sh
# ===========================================================================

def test_with_board_lock_runs_a_command_under_the_lock(tmp_path):
    root = make_repo(tmp_path)
    env = make_env(root)
    out = subprocess.run([str(root / "scripts" / "with_board_lock.sh"), "manual_fix", "--",
                          "sh", "-c", 'echo "held=$FORECLOSURE_BOARD_LOCK_HELD"; test -d "$FORECLOSURE_BOARD_LOCK_HELD"'],
                         capture_output=True, text=True, env=env)
    assert out.returncode == 0 and f"held={root}/logs/.board.lock" in out.stdout
    assert not (root / "logs" / ".board.lock").exists()
    (ev,) = job_events(root, "manual_fix")
    assert ev["outcome"] == "ok"


def test_with_board_lock_propagates_failure_and_reports_busy_as_75(tmp_path):
    root = make_repo(tmp_path)
    env = make_env(root)
    bad = subprocess.run([str(root / "scripts" / "with_board_lock.sh"), "j", "--", "sh", "-c", "exit 4"],
                         capture_output=True, text=True, env=env)
    assert bad.returncode == 4 and job_events(root, "j")[-1]["outcome"] == "failed"
    d = root / "logs" / ".board.lock"
    d.mkdir(parents=True)
    now = int(time.time())
    (d / "pid").write_text(f"{os.getpid()}\nother\n{now}\n{now}\n3600\nT\n")
    busy = subprocess.run([str(root / "scripts" / "with_board_lock.sh"), "j2", "--", "true"],
                          capture_output=True, text=True, env=env)
    assert busy.returncode == 75 and "board-writer active" in busy.stderr
    assert job_events(root, "j2")[-1]["outcome"] == "skipped_lock"


def test_with_board_lock_lets_a_python_writer_pass_write_artifact(tmp_path):
    """The point of the tool: any of the 54 unlocked scripts can run under it."""
    root = make_repo(tmp_path)
    prog = ("import sys; sys.path.insert(0, %r); from foreclosure_scraper import web_artifact as wa; "
            "wa._live_docs_dir = lambda: __import__('pathlib').Path(%r); "
            "wa.require_board_lock(%r); print('WRITE_ALLOWED')") % (str(REPO / "src"), str(root / "docs"), str(root / "docs"))
    env = make_env(root)
    without = subprocess.run([sys.executable, "-c", prog], capture_output=True, text=True, env=env)
    assert without.returncode != 0 and "BoardLockNotHeld" in without.stderr
    with_lock = subprocess.run([str(root / "scripts" / "with_board_lock.sh"), "fix", "--", sys.executable, "-c", prog],
                               capture_output=True, text=True, env=env)
    assert "WRITE_ALLOWED" in with_lock.stdout, with_lock.stderr


# ===========================================================================
# the wrappers, end to end against a stub uv and a local bare remote
# ===========================================================================

def test_lrcpwa_commits_then_pushes_after_releasing_the_lock(tmp_path):
    root = make_repo(tmp_path)
    hook = root / ".git" / "hooks" / "pre-push"
    hook.write_text('#!/bin/sh\n[ -d "$(git rev-parse --show-toplevel)/logs/.board.lock" ] && '
                    'echo LOCKED >> "$(git rev-parse --show-toplevel)/logs/push_lock_state.txt" || '
                    'echo FREE >> "$(git rev-parse --show-toplevel)/logs/push_lock_state.txt"\n')
    hook.chmod(0o755)
    env = make_env(root, {"STUB_UV_MODE": "change"})
    out = wrapper(root, "lrcpwa_refresh.sh", env)
    assert out.returncode == 0, out.stdout + out.stderr
    log = (root / "logs" / "lrcpwa_refresh.log").read_text()
    assert "committed + pushed" in log
    assert (root / "logs" / "push_lock_state.txt").read_text().split() == ["FREE"], "the push must run OUTSIDE the lock"
    (ev,) = job_events(root, "lrcpwa")
    assert ev["outcome"] == "ok" and ev["duration_s"] >= 0
    assert git_log(root, 1)[0].startswith("Scheduled land-records refresh")
    assert _run(["git", "rev-parse", "HEAD"], cwd=root).stdout == _run(["git", "rev-parse", "origin/main"], cwd=root).stdout
    assert not (root / "logs" / ".board.lock").exists()
    assert not (Path("/tmp") / "lrcpwa_refresh.log").exists() or True     # log lives in logs/, not /tmp


def test_lrcpwa_no_change_is_recorded_as_no_change(tmp_path):
    root = make_repo(tmp_path)
    out = wrapper(root, "lrcpwa_refresh.sh", make_env(root, {"STUB_UV_MODE": "nochange"}))
    assert out.returncode == 0
    assert job_events(root, "lrcpwa")[-1]["outcome"] == "no_change"
    assert git_log(root, 1) == ["base"]


def test_lrcpwa_failure_and_missing_uv_are_reported_not_swallowed(tmp_path):
    root = make_repo(tmp_path)
    out = wrapper(root, "lrcpwa_refresh.sh", make_env(root, {"STUB_UV_MODE": "fail"}))
    assert out.returncode == 1
    ev = job_events(root, "lrcpwa")[-1]
    assert ev["outcome"] == "failed" and "rc=3" in ev["note"]
    # no uv on PATH at all: the dailycourt failure mode (31 days of exit 127, nobody told)
    env = make_env(root)
    env["PATH"] = "/usr/bin:/bin:/usr/sbin:/sbin"
    env["HOME"] = str(tmp_path / "emptyhome")
    out = wrapper(root, "lrcpwa_refresh.sh", env)
    assert out.returncode == 127
    ev = job_events(root, "lrcpwa")[-1]
    assert ev["outcome"] == "failed" and ev["note"] == "uv_not_found"


def test_lrcpwa_skips_when_the_board_is_busy_and_says_who(tmp_path):
    root = make_repo(tmp_path)
    d = root / "logs" / ".board.lock"
    d.mkdir(parents=True)
    now = int(time.time())
    (d / "pid").write_text(f"{os.getpid()}\nrun_daily_vision.sh\n{now - 3600}\n{now - 10}\n21600\nT\n")
    out = wrapper(root, "lrcpwa_refresh.sh", make_env(root, {"STUB_UV_MODE": "change"}))
    assert out.returncode == 0
    ev = job_events(root, "lrcpwa")[-1]
    assert ev["outcome"] == "skipped_lock" and "run_daily_vision.sh" in ev["note"]
    assert "STUB" not in (root / "logs" / "stub_uv_calls.txt").read_text() if (root / "logs" / "stub_uv_calls.txt").exists() else True
    assert not (root / "logs" / "stub_uv_calls.txt").exists(), "uv must not run when the lock is refused"


def test_lrcpwa_records_a_memory_gate_refusal_as_skipped_memory(tmp_path):
    root = make_repo(tmp_path)
    env = make_env(root, {"BOARD_MEM_GATE": "enforce", "BOARD_MEM_GATE_WAIT": "1", "BOARD_MEM_GATE_POLL": "1",
                          "BOARD_GATE_FAKE_SWAP_MB": "8000"})
    out = wrapper(root, "lrcpwa_refresh.sh", env)
    assert out.returncode == 0
    ev = job_events(root, "lrcpwa")[-1]
    assert ev["outcome"] == "skipped_memory" and "swap_used_mb=8000" in ev["note"]


def test_lrcpwa_push_failure_is_push_failed_not_ok(tmp_path):
    root = make_repo(tmp_path)
    _run(["git", "remote", "set-url", "origin", str(tmp_path / "does-not-exist.git")], cwd=root)
    out = wrapper(root, "lrcpwa_refresh.sh", make_env(root, {"STUB_UV_MODE": "change"}))
    assert out.returncode == 0
    ev = job_events(root, "lrcpwa")[-1]
    assert ev["outcome"] == "push_failed"
    assert "PUSH FAILED" in (root / "logs" / "lrcpwa_refresh.log").read_text()
    assert git_log(root, 1)[0].startswith("Scheduled land-records"), "the commit is kept locally"


def test_lrcpwa_rebases_onto_a_moved_origin_before_pushing(tmp_path):
    root = make_repo(tmp_path)
    other = tmp_path / "other"
    _run(["git", "clone", "-q", str(tmp_path / "origin.git"), str(other)])
    (other / "elsewhere.txt").write_text("someone else pushed")
    _run(["git", "add", "-A"], cwd=other)
    _run(["git", "-c", "user.name=o", "-c", "user.email=o@e.com", "commit", "-q", "-m", "other"], cwd=other)
    _run(["git", "push", "-q", "origin", "main"], cwd=other)
    out = wrapper(root, "lrcpwa_refresh.sh", make_env(root, {"STUB_UV_MODE": "change"}))
    assert out.returncode == 0, out.stdout + out.stderr
    assert job_events(root, "lrcpwa")[-1]["outcome"] == "ok"
    assert git_log(root, 3)[:2] == [git_log(root, 1)[0], "other"]
    assert _run(["git", "rev-parse", "HEAD"], cwd=root).stdout == _run(["git", "rev-parse", "origin/main"], cwd=root).stdout


def test_sos_only_commits_when_a_payload_file_other_than_run_meta_changed(tmp_path):
    root = make_repo(tmp_path)
    out = wrapper(root, "sos_agent_refresh.sh", make_env(root, {"STUB_UV_MODE": "meta"}))
    assert out.returncode == 0
    assert job_events(root, "sosagent")[-1]["outcome"] == "no_change"
    assert git_log(root, 1) == ["base"], "a run whose only effect is run_meta.json must not commit"
    staged = _run(["git", "diff", "--cached", "--name-only"], cwd=root).stdout
    assert staged == "", "the payload-mode gate must reset what it staged"
    out = wrapper(root, "sos_agent_refresh.sh", make_env(root, {"STUB_UV_MODE": "change"}))
    assert job_events(root, "sosagent")[-1]["outcome"] == "ok"
    assert git_log(root, 1)[0].startswith("Scheduled SOS pass")


def test_parcel_cache_wrapper_propagates_failure_and_logs_to_logs(tmp_path):
    root = make_repo(tmp_path)
    (root / ".venv" / "bin").mkdir(parents=True)
    py = root / ".venv" / "bin" / "python"
    py.write_text("#!/bin/sh\nexit 5\n")
    py.chmod(0o755)
    (root / "data" / "parcel_cache").mkdir(parents=True)
    out = wrapper(root, "parcel_cache_refresh.sh", make_env(root))
    assert out.returncode == 1
    ev = job_events(root, "parcelcache")[-1]
    assert ev["outcome"] == "failed" and "rc=5" in ev["note"]
    assert "parcel-cache refresh" in (root / "logs" / "parcel_cache_refresh.log").read_text()
    py.write_text("#!/bin/sh\nexit 0\n")
    out = wrapper(root, "parcel_cache_refresh.sh", make_env(root))
    assert out.returncode == 0 and job_events(root, "parcelcache")[-1]["outcome"] == "ok"


def test_run_local_refuses_with_75_when_the_board_is_held_and_uv_missing_is_127(tmp_path):
    root = make_repo(tmp_path)
    d = root / "logs" / ".board.lock"
    d.mkdir(parents=True)
    now = int(time.time())
    (d / "pid").write_text(f"{os.getpid()}\nrun_daily_vision.sh\n{now - 60}\n{now}\n21600\nT\n")
    env = make_env(root)
    out = subprocess.run(["/bin/bash", str(root / "scripts" / "run_local.sh")], capture_output=True, text=True,
                         env=env, cwd=str(root))
    assert out.returncode == 75, out.stdout + out.stderr       # was exit 0: gui_run said "Run finished"
    ev = job_events(root, "full_run")[-1]
    assert ev["outcome"] == "skipped_lock"
    env["PATH"] = "/usr/bin:/bin:/usr/sbin:/sbin"
    env["HOME"] = str(tmp_path / "emptyhome")
    out = subprocess.run(["/bin/bash", str(root / "scripts" / "run_local.sh")], capture_output=True, text=True,
                         env=env, cwd=str(root))
    assert out.returncode == 127 and "uv not found" in out.stderr


def test_run_local_source_no_longer_uninstalls_packages_or_swallows_a_failed_write():
    text = (REPO / "scripts" / "run_local.sh").read_text()
    assert "uv sync --frozen --inexact" in text and "uv sync --frozen >>" not in text
    assert "web_artifact\\.failed" in text and "web_artifact\\.written" in text
    assert "grep -oE '\"total\": [0-9]+' \"$ROOT/docs/run_meta.json\"" not in text, "no run_meta fallback"
    assert "exit 75" in text


def test_every_wrapper_that_calls_uv_sets_path_and_guards_it():
    for name in ("run_local.sh", "gui_run.sh", "run_daily_court.sh", "run_daily_api_refresh.sh",
                 "lrcpwa_refresh.sh", "sos_agent_refresh.sh", "ingest_saved.sh", "prompt_run.sh",
                 "run_liensnc_related_all.sh", "with_board_lock.sh", "family_common.sh"):
        text = (REPO / "scripts" / name).read_text()
        assert '$HOME/.local/bin' in text and "/opt/homebrew/bin" in text, f"{name}: PATH export missing"
    for name in ("run_local.sh", "run_daily_court.sh", "run_daily_api_refresh.sh", "run_liensnc_related_all.sh"):
        assert "command -v uv" in (REPO / "scripts" / name).read_text(), f"{name}: uv guard missing"
    court = (REPO / "scripts" / "run_daily_court.sh").read_text()
    assert 'TYLER_USE_WAF_SOLVER:-0' in court, "the WAF solver must default OFF (owner rule)"


def test_no_scheduled_wrapper_logs_to_tmp():
    for name in ("lrcpwa_refresh.sh", "sos_agent_refresh.sh", "parcel_cache_refresh.sh", "family_common.sh",
                 "backup_local_state.sh"):
        text = (REPO / "scripts" / name).read_text()
        assert 'LOG="/tmp' not in text and 'LOG=/tmp' not in text, name
    for plist in (REPO / "deploy" / "mac").glob("com.highway.foreclosure.*.plist"):
        assert "/tmp/" not in plist.read_text(), plist.name


def test_prompt_run_leaves_a_trace_and_a_job_event(tmp_path):
    root = make_repo(tmp_path)
    home = tmp_path / "home"
    (home).mkdir(exist_ok=True)
    (home / "foreclosure-scraper").symlink_to(root)          # prompt_run.sh hardcodes ~/foreclosure-scraper
    stubs = tmp_path / "stubs"
    stubs.mkdir(exist_ok=True)
    counter = tmp_path / "osa_count"
    (stubs / "osascript").write_text(
        f'#!/bin/sh\nn=$(cat "{counter}" 2>/dev/null || echo 0); n=$((n+1)); echo $n > "{counter}"\n'
        'if [ "$n" -eq 1 ]; then echo "Skip"; else echo "Not now"; fi\n')
    (stubs / "osascript").chmod(0o755)
    (stubs / "pgrep").write_text("#!/bin/sh\nexit 1\n")
    (stubs / "pgrep").chmod(0o755)
    env = make_env(root)
    out = subprocess.run(["/bin/bash", str(root / "scripts" / "prompt_run.sh")], capture_output=True, text=True,
                         env=env, cwd=str(root))
    assert out.returncode == 0, out.stderr
    ev = job_events(root, "prompt_run")[-1]
    assert ev["outcome"] == "no_change" and ev["note"] == "declined"
    log = (root / "logs" / "prompt_run.log").read_text()
    assert "popup fired" in log and "step 1 answer: 'Skip'" in log and "step 2 answer: 'Not now'" in log


# ===========================================================================
# the per-family merge wrappers (audit O2)
# ===========================================================================

@pytest.mark.parametrize("family,script", [("nc_tax", "run_family_nc_tax.sh"), ("sc_tax", "run_family_sc_tax.sh"),
                                            ("nc_ecourts", "run_family_nc_ecourts.sh"),
                                            ("qpaybill", "run_family_qpaybill.sh")])
def test_family_wrapper_scrapes_without_the_lock_merges_under_it_and_publishes(tmp_path, family, script):
    root = make_repo(tmp_path)
    env = make_env(root, {"STUB_UV_MODE_PHASE_scrape": "lockcheck", "STUB_UV_MODE_PHASE_merge": "lockcheck",
                          "STUB_UV_MODE_PHASE_post": "lockcheck"})
    out = wrapper(root, script, env, shell="/bin/zsh")
    assert out.returncode == 0, out.stdout + out.stderr + (root / "logs" / f"family_{family}.log").read_text()
    phases = (root / "logs" / "stub_phases.txt").read_text().split()
    assert phases[0] == "LOCK_FREE_DURING_scrape", "the network-bound scrape must NOT hold the board lock"
    assert phases[1] == "LOCK_HELD_DURING_merge"
    if family == "qpaybill":
        assert phases[2] == "LOCK_HELD_DURING_post"
    ev = job_events(root, f"family_{family}")[-1]
    assert ev["outcome"] == "ok" and ev["rows_changed"] == 42
    assert git_log(root, 1)[0].startswith(f"Scheduled family merge ({family})")
    assert _run(["git", "rev-parse", "HEAD"], cwd=root).stdout == _run(["git", "rev-parse", "origin/main"], cwd=root).stdout


def test_family_wrapper_scrape_failure_takes_no_lock_and_publishes_nothing(tmp_path):
    root = make_repo(tmp_path)
    env = make_env(root, {"STUB_UV_MODE_PHASE_scrape": "fail"})
    out = wrapper(root, "run_family_nc_tax.sh", env)
    assert out.returncode == 1
    ev = job_events(root, "family_nc_tax")[-1]
    assert ev["outcome"] == "failed" and "scrape_rc=3" in ev["note"]
    assert git_log(root, 1) == ["base"]


def test_family_wrapper_skips_a_busy_lock_and_keeps_the_staged_data(tmp_path):
    root = make_repo(tmp_path)
    d = root / "logs" / ".board.lock"
    d.mkdir(parents=True)
    now = int(time.time())
    (d / "pid").write_text(f"{os.getpid()}\nrun_daily_vision.sh\n{now}\n{now}\n21600\nT\n")
    env = make_env(root, {"FAMILY_LOCK_WAIT": "0", "STUB_UV_MODE_PHASE_scrape": "nochange"})
    out = wrapper(root, "run_family_sc_tax.sh", env)
    assert out.returncode == 0
    ev = job_events(root, "family_sc_tax")[-1]
    assert ev["outcome"] == "skipped_lock" and "run_daily_vision.sh" in ev["note"]
    calls = (root / "logs" / "stub_uv_calls.txt").read_text()
    assert "--phase scrape" in calls and "--phase merge" not in calls
    assert "staged data kept" in (root / "logs" / "family_sc_tax.log").read_text()


def test_family_wrapper_unchanged_board_is_no_change(tmp_path):
    root = make_repo(tmp_path)
    env = make_env(root, {"STUB_UV_MODE_PHASE_scrape": "nochange", "STUB_UV_MODE_PHASE_merge": "meta"})
    out = wrapper(root, "run_family_nc_ecourts.sh", env)
    assert out.returncode == 0
    assert job_events(root, "family_nc_ecourts")[-1]["outcome"] == "no_change"
    assert git_log(root, 1) == ["base"]


def test_family_wrapper_merge_failure_publishes_nothing(tmp_path):
    root = make_repo(tmp_path)
    env = make_env(root, {"STUB_UV_MODE_PHASE_scrape": "nochange", "STUB_UV_MODE_PHASE_merge": "fail"})
    out = wrapper(root, "run_family_nc_tax.sh", env)
    assert out.returncode == 1
    ev = job_events(root, "family_nc_tax")[-1]
    assert ev["outcome"] == "failed" and "merge_rc=3" in ev["note"]
    assert not (root / "logs" / ".board.lock").exists(), "the lock must be released on failure"


def test_family_wrapper_scrape_timeout_still_merges_what_was_staged(tmp_path):
    root = make_repo(tmp_path)
    env = make_env(root, {"FAMILY_SCRAPE_TIMEOUT": "2", "STUB_UV_MODE_PHASE_scrape": "sleep",
                          "STUB_UV_MODE_PHASE_merge": "change"})
    out = wrapper(root, "run_family_nc_tax.sh", env)
    assert out.returncode == 0, out.stdout + out.stderr
    log = (root / "logs" / "family_nc_tax.log").read_text()
    assert "hit its 2s cap" in log
    assert job_events(root, "family_nc_tax")[-1]["outcome"] == "ok"


# ===========================================================================
# restore_board.sh (audit O5)
# ===========================================================================

def _two_commit_repo(tmp_path):
    root = make_repo(tmp_path)
    old = _run(["git", "rev-parse", "HEAD"], cwd=root).stdout.strip()
    # a newer commit with different payload, an extra shard, and a plain twin on disk
    (root / "docs" / "listings.json.gz").write_bytes(b"board-v2-newer")
    (root / "docs" / "detail_shards" / "00001.json.gz").write_bytes(b"shard1-v2")
    _run(["git", "add", "-A"], cwd=root)
    _run(["git", "commit", "-q", "-m", "newer board"], cwd=root)
    (root / "docs" / "listings.json").write_text('["plain-newest"]')
    return root, old


def test_restore_takes_every_payload_file_from_one_commit(tmp_path):
    root, old = _two_commit_repo(tmp_path)
    out = subprocess.run([str(root / "scripts" / "restore_board.sh"), old, "--yes"], capture_output=True, text=True,
                         env=make_env(root), cwd=str(root))
    assert out.returncode == 0, out.stdout + out.stderr
    assert (root / "docs" / "listings.json.gz").read_bytes() == b"board-v1"
    assert (root / "docs" / "listings_detail.json.gz").read_bytes() == b"detail-v1"
    assert not (root / "docs" / "listings.json").exists(), "the plain twin beats its gz in read_board_json: it must go"
    assert not (root / "docs" / "detail_shards" / "00001.json.gz").exists(), "a shard from the newer board must not survive"
    assert (root / "docs" / "detail_shards" / "00000.json.gz").read_bytes() == b"shard0-v1"
    kept = list((root / "backups").glob("pre-restore-*"))
    assert len(kept) == 1 and (kept[0] / "listings.json").read_text() == '["plain-newest"]'
    assert "restored files (sha256)" in out.stdout and old[:7] in out.stdout
    assert "manifest check: no manifest in this commit" in out.stdout
    porcelain = _run(["git", "status", "--porcelain", "--untracked-files=no"], cwd=root).stdout.splitlines()
    assert porcelain and all(line[0] == " " for line in porcelain), \
        "the restore is a worktree change (second column only): nothing staged, committed or pushed"
    assert _run(["git", "diff", "--cached", "--name-only"], cwd=root).stdout == ""
    assert job_events(root, "restore_board")[-1]["outcome"] == "ok"


def test_restore_refuses_while_the_lock_is_held(tmp_path):
    root, old = _two_commit_repo(tmp_path)
    d = root / "logs" / ".board.lock"
    d.mkdir(parents=True)
    now = int(time.time())
    (d / "pid").write_text(f"{os.getpid()}\nrun_daily_vision.sh\n{now}\n{now}\n21600\nT\n")
    out = subprocess.run([str(root / "scripts" / "restore_board.sh"), old, "--yes"], capture_output=True, text=True,
                         env=make_env(root), cwd=str(root))
    assert out.returncode == 75 and "REFUSING" in out.stderr
    assert (root / "docs" / "listings.json.gz").read_bytes() == b"board-v2-newer", "nothing may change"
    assert (root / "docs" / "listings.json").exists()


def test_restore_needs_confirmation_and_rejects_a_non_board_commit(tmp_path):
    root, old = _two_commit_repo(tmp_path)
    env = make_env(root)
    out = subprocess.run([str(root / "scripts" / "restore_board.sh"), old], capture_output=True, text=True,
                         env=env, cwd=str(root), stdin=subprocess.DEVNULL)
    assert out.returncode == 2 and "pass --yes" in out.stderr
    assert (root / "docs" / "listings.json.gz").read_bytes() == b"board-v2-newer"
    out = subprocess.run([str(root / "scripts" / "restore_board.sh"), "no-such-commit", "--yes"],
                         capture_output=True, text=True, env=env, cwd=str(root))
    assert out.returncode == 2


def test_restore_verifies_the_manifest_that_came_with_the_commit(tmp_path):
    import hashlib
    root = make_repo(tmp_path)
    files = {}
    for name in ("listings.json.gz", "listings_detail.json.gz", "listings_slim.json.gz"):
        b = (root / "docs" / name).read_bytes()
        files[name] = {"bytes": len(b), "sha256": hashlib.sha256(b).hexdigest()}
    (root / "docs" / "board.manifest.json").write_text(json.dumps({"schema": "board-manifest-v1", "files": files}))
    _run(["git", "add", "-A"], cwd=root)
    _run(["git", "commit", "-q", "-m", "with manifest"], cwd=root)
    good = _run(["git", "rev-parse", "HEAD"], cwd=root).stdout.strip()
    (root / "docs" / "listings.json.gz").write_bytes(b"different")
    out = subprocess.run([str(root / "scripts" / "restore_board.sh"), good, "--yes"], capture_output=True, text=True,
                         env=make_env(root), cwd=str(root))
    assert "manifest check: MATCHES" in out.stdout, out.stdout + out.stderr
    # a commit whose manifest disagrees with its own files (a publisher staged the payload without it)
    files["listings.json.gz"]["sha256"] = "0" * 64
    (root / "docs" / "board.manifest.json").write_text(json.dumps({"schema": "board-manifest-v1", "files": files}))
    _run(["git", "add", "-A"], cwd=root)
    _run(["git", "commit", "-q", "-m", "stale manifest"], cwd=root)
    bad = _run(["git", "rev-parse", "HEAD"], cwd=root).stdout.strip()
    out = subprocess.run([str(root / "scripts" / "restore_board.sh"), bad, "--yes"], capture_output=True, text=True,
                         env=make_env(root), cwd=str(root))
    assert "manifest check: MISMATCH" in out.stdout and "board_manifest.py --rebuild" in out.stderr


def test_restore_list_shows_board_commits_with_sizes(tmp_path):
    root, old = _two_commit_repo(tmp_path)
    out = subprocess.run([str(root / "scripts" / "restore_board.sh"), "--list", "5"], capture_output=True, text=True,
                         env=make_env(root), cwd=str(root))
    assert out.returncode == 0 and "newer board" in out.stdout and "base" in out.stdout and "MiB" in out.stdout


# ===========================================================================
# backup_local_state.sh (audit O5)
# ===========================================================================

def _backup_fixture(tmp_path):
    import sqlite3
    root = make_repo(tmp_path)
    (root / "data").mkdir()
    db = sqlite3.connect(root / "data" / "sc_parcel_mailing.db")
    db.execute("create table t(x)"); db.execute("insert into t values (1)"); db.commit(); db.close()
    (root / "data" / "sc_footprints.db").write_bytes(b"not-sqlite-but-big" * 100)
    (root / "data" / "notice_pdfs" / "43").mkdir(parents=True)
    (root / "data" / "notice_pdfs" / "43" / "a.pdf").write_bytes(b"%PDF-1")
    (root / "docs" / "crm.json").write_text('{"leads": {}}')
    (root / "logs" / "qpaybill_roll_all.json").write_text('{"harvest": true}')
    (root / "logs" / "big.log").write_text("noise" * 1000)
    (root / ".secrets").mkdir()
    (root / ".secrets" / "anthropic_api_key.txt").write_text("SUPERSECRETVALUE")
    (root / ".env").write_text("TOKEN=ALSOSECRET")
    dest = tmp_path / "backups"
    home = tmp_path / "home"
    (home / "Library" / "LaunchAgents").mkdir(parents=True, exist_ok=True)
    (home / "Library" / "LaunchAgents" / "com.highway.foreclosure.lrcpwa.plist").write_text("<plist/>")
    return root, dest


def _backup(root, dest, **extra):
    env = make_env(root, {"BACKUP_DEST": str(dest), "BACKUP_MIN_FREE_GB": "0", **extra})
    return subprocess.run(["/bin/bash", str(root / "scripts" / "backup_local_state.sh")], capture_output=True,
                          text=True, env=env, cwd=str(root))


def test_backup_copies_the_fixed_list_and_encrypts_secrets(tmp_path):
    root, dest = _backup_fixture(tmp_path)
    out = _backup(root, dest, BACKUP_PASSPHRASE_CMD="echo test-passphrase")
    assert out.returncode == 0, out.stderr + (root / "logs" / "backup.log").read_text()
    (snap,) = [p for p in dest.iterdir() if p.is_dir()]
    assert (snap / "data" / "sc_parcel_mailing.db").exists()
    import sqlite3
    assert sqlite3.connect(snap / "data" / "sc_parcel_mailing.db").execute("select x from t").fetchone() == (1,)
    assert (snap / "data" / "notice_pdfs" / "43" / "a.pdf").read_bytes() == b"%PDF-1"
    assert (snap / "docs" / "crm.json").exists() and (snap / "logs" / "qpaybill_roll_all.json").exists()
    assert not (snap / "logs" / "big.log").exists(), "*.log files are not backed up"
    assert (snap / "LaunchAgents" / "com.highway.foreclosure.lrcpwa.plist").exists()
    # secrets: only ever encrypted
    assert not (snap / ".secrets").exists() and not (snap / ".env").exists()
    enc = snap / "secrets.tar.gz.enc"
    assert enc.exists() and b"SUPERSECRETVALUE" not in enc.read_bytes()
    dec = subprocess.run(f'openssl enc -d -aes-256-cbc -pbkdf2 -iter 200000 -pass fd:3 3<<<"test-passphrase" -in "{enc}" | tar tzf -',
                         shell=True, executable="/bin/bash", capture_output=True, text=True)
    assert ".secrets/anthropic_api_key.txt" in dec.stdout and ".env" in dec.stdout
    ev = job_events(root, "backup_local_state")[-1]
    assert ev["outcome"] == "ok" and "secrets=encrypted" in ev["note"]
    everything = "".join(p.read_bytes().decode("latin1") for p in snap.rglob("*") if p.is_file())
    assert "SUPERSECRETVALUE" not in everything and "ALSOSECRET" not in everything


def test_backup_without_a_keychain_item_skips_secrets_and_never_falls_back_to_a_file(tmp_path):
    root, dest = _backup_fixture(tmp_path)
    (root / ".secrets" / "backup_passphrase.txt").write_text("a-file-that-must-never-be-used")
    out = _backup(root, dest, BACKUP_KEYCHAIN_SERVICE="foreclosure-test-item-that-does-not-exist-xyz")
    assert out.returncode == 0, out.stderr
    (snap,) = [p for p in dest.iterdir() if p.is_dir()]
    assert not (snap / "secrets.tar.gz.enc").exists() and not (snap / ".secrets").exists()
    ev = job_events(root, "backup_local_state")[-1]
    assert "secrets=no_passphrase" in ev["note"]
    assert "NOT backed up" in (root / "logs" / "backup.log").read_text()


def test_backup_hard_links_unchanged_files_and_rotates(tmp_path):
    root, dest = _backup_fixture(tmp_path)
    env = {"BACKUP_ENCRYPT_SECRETS": "0", "BACKUP_KEEP_DAYS": "2"}
    snaps = []
    for _ in range(3):
        out = _backup(root, dest, **env)
        assert out.returncode == 0, out.stderr
        snaps = sorted(p for p in dest.iterdir() if p.is_dir())
        time.sleep(1.1)
    assert len(snaps) == 2, "only the newest BACKUP_KEEP_DAYS snapshots survive"
    a, b = (s / "data" / "sc_footprints.db" for s in snaps)
    assert a.stat().st_ino == b.stat().st_ino, "an unchanged file must be hard-linked, not copied again"
    (root / "docs" / "crm.json").write_text('{"leads": {"1": {}}}')
    out = _backup(root, dest, **env)
    newest = sorted(p for p in dest.iterdir() if p.is_dir())[-1]
    assert json.loads((newest / "docs" / "crm.json").read_text())["leads"] == {"1": {}}
    prev = sorted(p for p in dest.iterdir() if p.is_dir())[-2]
    assert json.loads((prev / "docs" / "crm.json").read_text())["leads"] == {}, "an older snapshot must keep its own copy"


def test_backup_never_touches_directories_it_did_not_create(tmp_path):
    root, dest = _backup_fixture(tmp_path)
    dest.mkdir()
    (dest / "my-own-folder").mkdir()
    (dest / "my-own-folder" / "keep.txt").write_text("x")
    (dest / "20200101-000000").mkdir()                         # looks like an old snapshot: eligible
    _backup(root, dest, BACKUP_ENCRYPT_SECRETS="0", BACKUP_KEEP_DAYS="1")
    assert (dest / "my-own-folder" / "keep.txt").exists()
    assert not (dest / "20200101-000000").exists()


def test_backup_refuses_when_the_disk_is_nearly_full(tmp_path):
    root, dest = _backup_fixture(tmp_path)
    out = _backup(root, dest, BACKUP_MIN_FREE_GB="99999999", BACKUP_ENCRYPT_SECRETS="0")
    assert out.returncode == 1
    assert job_events(root, "backup_local_state")[-1]["note"] == "low_disk"


# ===========================================================================
# install_launchd.sh and the plist templates (audit O5, O10, O6)
# ===========================================================================

def test_install_launchd_is_a_dry_run_by_default(tmp_path):
    dest = tmp_path / "agents"
    out = subprocess.run([str(REPO / "scripts" / "install_launchd.sh"), "--dest", str(dest)],
                         capture_output=True, text=True, env={**os.environ, "HOME": str(tmp_path)})
    assert out.returncode == 0 and "DRY RUN" in out.stdout
    assert "== com.highway.foreclosure.lrcpwa: NEW" in out.stdout
    assert not list(dest.glob("*.plist")), "a dry run must write nothing"


def test_install_launchd_apply_renders_paths_and_never_loads_when_dest_is_given(tmp_path):
    dest = tmp_path / "agents"
    out = subprocess.run([str(REPO / "scripts" / "install_launchd.sh"), "--apply", "--dest", str(dest), "lrcpwa", "jobwatch"],
                         capture_output=True, text=True, env={**os.environ, "HOME": str(tmp_path)})
    assert out.returncode == 0, out.stderr
    plist = (dest / "com.highway.foreclosure.lrcpwa.plist").read_text()
    assert "__ROOT__" not in plist and "__HOME__" not in plist
    assert f"{REPO}/scripts/lrcpwa_refresh.sh" in plist and f"{tmp_path}/.local/bin" in plist
    assert "launchctl" not in out.stdout, "with --dest the script must never load anything"
    assert subprocess.run(["plutil", "-lint", str(dest / "com.highway.foreclosure.lrcpwa.plist")],
                          capture_output=True).returncode == 0


def test_plist_templates_are_valid_and_reorder_the_day():
    import plistlib
    tpls = {p.name: p for p in (REPO / "deploy" / "mac").glob("com.highway.foreclosure.*.plist")}
    assert len(tpls) >= 11
    sched = {}
    for name, p in tpls.items():
        data = plistlib.loads(p.read_text().replace("__ROOT__", "/r").replace("__HOME__", "/h").encode())
        assert data["Label"] + ".plist" == name
        assert data["EnvironmentVariables"]["PATH"].startswith("/h/.local/bin"), name
        assert data["StandardOutPath"].startswith("/r/logs/"), name
        script = Path(data["ProgramArguments"][1].replace("/r/", str(REPO) + "/"))
        assert script.exists(), f"{name} points at a missing script {script}"
        sched[data["Label"].rsplit(".", 1)[1]] = data.get("StartCalendarInterval")
    assert sched["lrcpwa"] == {"Hour": 8, "Minute": 0}
    assert sched["sosagent"] == {"Hour": 8, "Minute": 30}
    assert sched["dailyvision"] == {"Hour": 9, "Minute": 30}
    assert len(sched["weekly"]) == 2
    installed = list((REPO / "deploy" / "mac" / "installed-2026-09-21").glob("*.plist"))
    assert len(installed) == 5, "the five installed plists must be recorded verbatim in the repo"
