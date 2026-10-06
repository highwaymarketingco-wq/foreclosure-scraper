"""The gated VM launch, shell side (docs/HANDOFF.md item 72, 2026-10-06).

deploy/oracle/vm_run.sh now has what vm_resume.sh had (the memory watchdog, a disk preflight, a
commit pin) plus swap and reference-data preflights, a pending-checkpoint guard and
--stop-before-publish; both share them through vm_lib.sh. install_timer.sh is fixed and a dry run
by default.

Every test copies the REAL scripts into a throwaway repo with a bare origin, a stub `uv` (the
"python run" is a few lines of shell that print the log lines main.py prints), a stub memory
watchdog (the real one reads Linux /proc) and tiny but real SQLite/zip reference data. Nothing
touches the real repo, the VM or the network.
"""
from __future__ import annotations

import gzip
import json
import os
import shutil
import sqlite3
import stat
import subprocess
import sys
import time
import zipfile
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
ORACLE = REPO / "deploy" / "oracle"

STUB_UV = r'''#!/bin/sh
# stand-in for uv: records each call (and the stop switch the run saw), then acts per STUB_RUN
echo "uv $* stop=${FULLRUN_STOP_BEFORE_PUBLISH:-unset}" >> "$STUB_LOG"
[ "$1" = "sync" ] && exit 0
echo "head=$(git rev-parse HEAD)" >> "$STUB_LOG"
case "${STUB_RUN:-stop}" in
  stop)    echo '{"leads": 7, "event": "orchestrator.stopped_before_publish", "level": "info"}'; exit 0 ;;
  publish) printf 'x%s' "$$" >> docs/listings_detail.json.gz
           echo '{"bytes": 10, "listings": 7, "event": "web_artifact.written", "level": "info"}'; exit 0 ;;
  fail)    exit 3 ;;
  sleep)   sleep 30; exit 0 ;;
esac
'''

STUB_WATCHDOG = r'''#!/usr/bin/env python3
import argparse, os, signal, sys, time
ap = argparse.ArgumentParser()
ap.add_argument("--pid", type=int); ap.add_argument("--log")
ap.add_argument("--kill-total-mb"); ap.add_argument("--kill-avail-mb"); ap.add_argument("--kill-swapfree-mb")
a = ap.parse_args()
mode = os.environ.get("STUB_WD_MODE", "ok")
with open(os.environ["STUB_LOG"], "a") as fh:
    fh.write(f"watchdog total={a.kill_total_mb} avail={a.kill_avail_mb} swapfree={a.kill_swapfree_mb}\n")
if mode == "crash":
    sys.exit(2)
def alive(pid):
    try:
        os.kill(pid, 0)
    except OSError:
        return False
    import subprocess
    st = subprocess.run(["ps", "-o", "stat=", "-p", str(pid)], capture_output=True, text=True).stdout.strip()
    return bool(st) and not st.startswith("Z")
with open(a.log, "a") as fh:
    if mode == "kill":
        time.sleep(0.5)
        os.kill(a.pid, signal.SIGKILL)
        fh.write("KILLED 1: tree rss+swap 30000 MB > 25600 MB\n")
        fh.write("PEAK rss_mb=30000 killed=yes\n"); sys.exit(9)
    while alive(a.pid):
        time.sleep(0.1)
    fh.write("PEAK rss_mb=1 swap_mb=0 total_mb=1 killed=no\n")
'''


def _exe(p: Path, body: str) -> Path:
    p.write_text(body)
    p.chmod(p.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    return p


def _git(root, *a, check=True):
    return subprocess.run(["git", *a], cwd=root, capture_output=True, text=True, check=check)


def _sqlite(p: Path, table: str, rows=1):
    p.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(p)
    con.execute(f"CREATE TABLE {table} (id TEXT, v TEXT)")
    con.executemany(f"INSERT INTO {table} VALUES (?, ?)", [(str(i), "x" * 2000) for i in range(rows)])
    con.commit()
    con.close()


def _zip(p: Path):
    p.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(p, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr(p.stem, '{"type": "Feature"}\n' * 50)


def make_refdata(root: Path, manifest=True):
    d = root / "data"
    for county in ("aiken", "buncombe", "cherokee_nc"):
        _sqlite(d / "parcel_cache" / f"{county}.sqlite", "parcels", rows=40)
    _sqlite(d / "sc_footprints.db", "footprints")
    _sqlite(d / "parcel_inventory.db", "parcels")
    _zip(d / "footprints_src" / "NorthCarolina.geojson.zip")
    _zip(d / "footprints_src" / "SouthCarolina.geojson.zip")
    (d / "ncvoter").mkdir(parents=True, exist_ok=True)
    (d / "ncvoter" / "ncvoter11.txt").write_text("voter_reg_num\tfull_phone_number\n1\t8285550100\n")
    _sqlite(d / "sc_parcel_mailing.db", "sc_parcel_mailing")
    _sqlite(d / "sc_cama.db", "sc_cama")
    if manifest:
        out = subprocess.run([sys.executable, str(root / "deploy/oracle/refdata_check.py"),
                              "write-manifest", "--root", str(root)], capture_output=True, text=True)
        assert out.returncode == 0, out.stderr


@pytest.fixture
def vm(tmp_path):
    """<tmp>/repo: the real deploy/oracle scripts + scripts/board_payload.sh, a docs/ board, secrets,
    reference data, git history and a bare origin; <tmp>/stubs: uv and the watchdog."""
    root = tmp_path / "repo"
    (root / "deploy").mkdir(parents=True)
    shutil.copytree(ORACLE, root / "deploy" / "oracle", ignore=shutil.ignore_patterns("__pycache__"))
    (root / "scripts").mkdir()
    shutil.copy2(REPO / "scripts" / "board_payload.sh", root / "scripts" / "board_payload.sh")
    (root / "docs" / "detail_shards").mkdir(parents=True)
    (root / "docs" / "listings.json").write_bytes(b"[" + b" " * (3 * 1024 * 1024) + b"]")   # 3 MB board
    (root / "docs" / "listings_detail.json.gz").write_bytes(b"detail-v1")
    (root / "docs" / "run_meta.json").write_text('{"total": 7}')
    (root / "docs" / "handoff").mkdir()
    (root / "docs" / "handoff" / "stealth_leads.json").write_text("[]")
    sec = root / ".secrets"
    sec.mkdir()
    for name in ("service_account.json", "sheet_id.txt", "gmail_app_password.txt"):
        (sec / name).write_text("x")
    make_refdata(root)
    (root / ".gitignore").write_text("logs/\ndata/\n.secrets/\ndocs/listings.json\n")
    origin = tmp_path / "origin.git"
    subprocess.run(["git", "init", "-q", "--bare", "-b", "main", str(origin)], check=True)
    _git(root, "init", "-q", "-b", "main")
    _git(root, "config", "user.name", "t")
    _git(root, "config", "user.email", "t@example.com")
    _git(root, "remote", "add", "origin", str(origin))
    _git(root, "add", "-A")
    _git(root, "commit", "-q", "-m", "base")
    _git(root, "push", "-q", "-u", "origin", "main")

    stubs = tmp_path / "stubs"
    stubs.mkdir()
    _exe(stubs / "uv", STUB_UV)
    wd = _exe(stubs / "watchdog.py", STUB_WATCHDOG)
    home = tmp_path / "home"
    home.mkdir()
    swaps = tmp_path / "swaps"
    swaps.write_text("Filename\tType\tSize\tUsed\tPriority\n/swapfile file 4194300 0 -2\n")
    fstab = tmp_path / "fstab"
    fstab.write_text("LABEL=root / ext4 defaults 0 1\n/swapfile none swap sw 0 0\n")
    env = {k: v for k, v in os.environ.items()
           if not k.startswith(("RUN_", "RESUME_", "VM_", "FULLRUN_", "FORECLOSURE_", "GIT_", "STUB_"))}
    env.update({
        "HOME": str(home),
        "PATH": f"{stubs}:{Path(sys.executable).parent}:/usr/bin:/bin:/usr/sbin:/sbin",
        "STUB_LOG": str(tmp_path / "stub.log"),
        "VM_MEM_WATCHDOG": str(wd),
        "VM_WATCHDOG_GRACE_S": "0.5",
        "VM_PROC_SWAPS": str(swaps),
        "VM_FSTAB": str(fstab),
        "VM_BOARD_JOB_PATTERN": f"no-such-board-job-{tmp_path.name}",
        "RUN_MIN_FREE_MB": "1",
        "RESUME_MIN_FREE_MB": "1",
        "GIT_CONFIG_GLOBAL": "/dev/null", "GIT_CONFIG_NOSYSTEM": "1",
        "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@example.com",
        "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@example.com",
    })
    return {"root": root, "origin": origin, "env": env, "tmp": tmp_path, "swaps": swaps, "fstab": fstab}


def run(vm, script="vm_run.sh", *args, timeout=90, **env):
    e = {**vm["env"], **{k: str(v) for k, v in env.items()}}
    return subprocess.run(["bash", str(vm["root"] / "deploy" / "oracle" / script), *args],
                          capture_output=True, text=True, env=e, cwd=str(vm["root"]), timeout=timeout)


def stub_log(vm) -> str:
    p = vm["tmp"] / "stub.log"
    return p.read_text() if p.exists() else ""


def run_log(vm, prefix="vm-run") -> str:
    logs = sorted(p for p in (vm["root"] / "logs").glob(f"{prefix}-*.log") if not p.name.endswith(".mem.log"))
    return logs[-1].read_text()


def head(root):
    return _git(root, "rev-parse", "HEAD").stdout.strip()


def origin_head(vm):
    return subprocess.run(["git", "--git-dir", str(vm["origin"]), "rev-parse", "main"],
                          capture_output=True, text=True).stdout.strip()


def commit_on_origin(vm, path: str, body: str, msg: str) -> str:
    """A commit pushed to origin from a second clone (the way other agents' pushes arrive)."""
    other = vm["tmp"] / f"other-{time.time_ns()}"
    subprocess.run(["git", "clone", "-q", str(vm["origin"]), str(other)], check=True,
                   env=vm["env"], capture_output=True)
    (other / path).parent.mkdir(parents=True, exist_ok=True)
    (other / path).write_text(body)
    _git(other, "add", path)
    _git(other, "-c", "user.name=t", "-c", "user.email=t@example.com", "commit", "-q", "-m", msg)
    _git(other, "push", "-q", "origin", "main")
    return head(other)


# =================================================================================================
# syntax
# =================================================================================================

def test_every_shell_script_parses_and_the_python_helpers_compile():
    scripts = sorted([*REPO.glob("deploy/**/*.sh"), *REPO.glob("scripts/*.sh")])
    assert len(scripts) > 10
    bad = []
    for s in scripts:
        r = subprocess.run(["bash", "-n", str(s)], capture_output=True, text=True)
        if r.returncode:
            bad.append(f"{s.relative_to(REPO)}: {r.stderr.strip()}")
    assert not bad, bad
    for py in ("mem_watchdog.py", "refdata_check.py"):
        subprocess.run([sys.executable, "-m", "py_compile", str(ORACLE / py)], check=True)


# =================================================================================================
# vm_run.sh --stop-before-publish
# =================================================================================================

def test_stop_before_publish_runs_watched_saves_and_publishes_nothing(vm):
    before = origin_head(vm)
    r = run(vm, "vm_run.sh", "--stop-before-publish")
    assert r.returncode == 0, r.stdout + r.stderr
    log = run_log(vm)
    assert "uv run python -m foreclosure_scraper stop=1" in stub_log(vm)
    assert "watchdog total=25600 avail=700 swapfree=400" in stub_log(vm), "the run is not under the watchdog"
    assert "STOPPED BEFORE PUBLISH: 7 scored rows saved" in log
    assert "vm_resume.sh --publish-only" in log and f"RESUME_PIN_COMMIT={head(vm['root'])}" in log
    assert "PEAK rss_mb=1" in log, "the watchdog's last line is not in the run log"
    assert origin_head(vm) == before and _git(vm["root"], "log", "--oneline").stdout.count("\n") == 1
    assert not _git(vm["root"], "status", "--porcelain", "docs").stdout.strip()


def test_the_env_switch_is_the_same_as_the_flag(vm):
    r = run(vm, FULLRUN_STOP_BEFORE_PUBLISH="1")
    assert r.returncode == 0
    assert "stop=1" in stub_log(vm) and "STOPPED BEFORE PUBLISH" in run_log(vm)


def test_without_the_switch_the_run_publishes_as_before(vm):
    r = run(vm, STUB_RUN="publish", FULLRUN_STOP_BEFORE_PUBLISH="0")
    assert r.returncode == 0, r.stdout + r.stderr
    assert "uv run python -m foreclosure_scraper stop=unset" in stub_log(vm)
    log = run_log(vm)
    assert "total listings this run: 7" in log and "dashboard published" in log
    assert origin_head(vm) == head(vm["root"]) and "vm run: refresh dashboard data" in \
        _git(vm["root"], "log", "-1", "--format=%s").stdout


def test_a_stop_run_that_saved_nothing_says_so(vm):
    r = run(vm, "vm_run.sh", "--stop-before-publish", STUB_RUN="fail")
    assert r.returncode == 3
    assert "no pre_publish checkpoint was saved (RC=3)" in run_log(vm)


def test_unknown_arguments_are_refused(vm):
    r = run(vm, "vm_run.sh", "--stop-befor-publish")
    assert r.returncode == 64 and not stub_log(vm)


# =================================================================================================
# the memory watchdog
# =================================================================================================

def test_a_watchdog_kill_is_137_and_publishes_nothing(vm):
    before = origin_head(vm)
    r = run(vm, STUB_RUN="sleep", STUB_WD_MODE="kill")
    assert r.returncode == 137, r.stdout + r.stderr
    log = run_log(vm)
    assert "stopped by the memory watchdog: KILLED" in log and "skipping publish (RC=137)" in log
    assert origin_head(vm) == before


def test_a_watchdog_that_cannot_run_stops_the_job(vm):
    t0 = time.monotonic()
    r = run(vm, STUB_RUN="sleep", STUB_WD_MODE="crash")
    assert r.returncode == 70, r.stdout + r.stderr
    assert time.monotonic() - t0 < 20, "the unwatched job was left running"
    assert "the memory watchdog failed (exit 2" in run_log(vm)


def test_the_watchdog_limits_are_overridable(vm):
    r = run(vm, "vm_run.sh", "--stop-before-publish", RUN_KILL_TOTAL_MB=20000,
            RUN_KILL_AVAIL_MB=900, RUN_KILL_SWAPFREE_MB=300)
    assert r.returncode == 0
    assert "watchdog total=20000 avail=900 swapfree=300" in stub_log(vm)


# =================================================================================================
# preflights
# =================================================================================================

def test_disk_preflight_refuses_and_explains(vm):
    r = run(vm, RUN_MIN_FREE_MB=10**9)
    assert r.returncode == 1
    log = run_log(vm)
    assert "need 1000000000 MB (RUN_MIN_FREE_MB override; computed full run: publish 7000 + " \
           "replaced board 3 + in-run 2000 = 9003" in log
    assert "not starting" in log and "python -m foreclosure_scraper" not in stub_log(vm)


def test_the_disk_need_is_publish_base_plus_the_replaced_board_plus_in_run_growth(vm):
    out = subprocess.run(["bash", "-c", 'ROOT="$PWD"; . deploy/oracle/vm_lib.sh; '
                          'echo "$(vm_board_bytes_mb) $(vm_publish_need_mb) $(vm_full_run_need_mb)"'],
                         capture_output=True, text=True, cwd=vm["root"], env=vm["env"])
    assert out.stdout.split() == ["3", "7003", "9003"]
    # without docs/listings.json the replaced board is its parts
    (vm["root"] / "docs" / "listings.json").unlink()
    (vm["root"] / "docs" / "listings_part_000.json.gz").write_bytes(b"x" * (2 * 1024 * 1024))
    out = subprocess.run(["bash", "-c", 'ROOT="$PWD"; . deploy/oracle/vm_lib.sh; vm_publish_need_mb'],
                         capture_output=True, text=True, cwd=vm["root"], env=vm["env"])
    assert out.stdout.strip() == "7002"


def test_no_swap_is_a_loud_warning_not_a_refusal(vm):
    vm["swaps"].write_text("Filename\tType\tSize\tUsed\tPriority\n")
    r = run(vm, "vm_run.sh", "--stop-before-publish")
    assert r.returncode == 0
    assert "NO SWAP IS ACTIVE" in run_log(vm) and "sudo swapon /swapfile" in run_log(vm)


def test_swap_outside_fstab_is_flagged(vm):
    vm["fstab"].write_text("LABEL=root / ext4 defaults 0 1\n# /swapfile none swap sw 0 0\n")
    assert run(vm, "vm_run.sh", "--stop-before-publish").returncode == 0
    log = run_log(vm)
    assert "swap: 4095 MB active (/swapfile)" in log and "swap is not in" in log


@pytest.mark.parametrize("damage, expect", [
    ("missing_footprints", "data/sc_footprints.db: missing"),
    ("truncated_cache", "data/parcel_cache/buncombe.sqlite: "),
    ("county_not_copied", "data/parcel_cache/cherokee_nc.sqlite: missing"),
    ("empty_table", "data/parcel_inventory.db: table 'parcels' is empty"),
    ("bad_zip", "data/footprints_src/SouthCarolina.geojson.zip: zip"),
    ("no_manifest", "no manifest at"),
])
def test_reference_data_preflight_refuses(vm, damage, expect):
    d = vm["root"] / "data"
    if damage == "missing_footprints":
        (d / "sc_footprints.db").unlink()
    elif damage == "truncated_cache":
        p = d / "parcel_cache" / "buncombe.sqlite"
        p.write_bytes(p.read_bytes()[: p.stat().st_size // 2])      # an interrupted copy
    elif damage == "county_not_copied":
        (d / "parcel_cache" / "cherokee_nc.sqlite").unlink()
    elif damage == "empty_table":
        con = sqlite3.connect(d / "parcel_inventory.db")
        con.execute("DELETE FROM parcels")
        con.commit()
        con.close()
    elif damage == "bad_zip":
        p = d / "footprints_src" / "SouthCarolina.geojson.zip"
        p.write_bytes(p.read_bytes()[:-40])
    else:
        (d / "refdata_manifest.json").unlink()
    r = run(vm, "vm_run.sh", "--stop-before-publish")
    assert r.returncode == 1, r.stdout + r.stderr
    log = run_log(vm)
    assert expect in log and "reference data not ready" in log
    assert "python -m foreclosure_scraper" not in stub_log(vm)


def test_reference_data_warnings_do_not_refuse(vm):
    d = vm["root"] / "data"
    shutil.rmtree(d / "ncvoter")
    old = time.time() - 12 * 86400
    os.utime(d / "parcel_cache" / "aiken.sqlite", (old, old))
    r = run(vm, "vm_run.sh", "--stop-before-publish")
    assert r.returncode == 0, run_log(vm)
    log = run_log(vm)
    assert "data/ncvoter: missing (recommended" in log
    assert "1 parcel-cache counties older than 10 days" in log and "aiken" in log
    assert "refdata: OK: 3 parcel-cache counties" in log


def test_a_board_waiting_to_be_published_is_never_overwritten_silently(vm):
    ck = vm["root"] / "data" / "checkpoint"
    ck.mkdir(parents=True)
    (ck / "manifest.json").write_text(json.dumps({"phase": "pre_publish", "count": 330000,
                                                  "saved_at": "2026-10-07T09:00:00+00:00"}))
    r = run(vm, "vm_run.sh", "--stop-before-publish")
    assert r.returncode == 1
    assert "330000 rows saved 2026-10-07T09:00:00+00:00" in run_log(vm) and not stub_log(vm).count("python")
    r = run(vm, "vm_run.sh", "--stop-before-publish", RUN_DISCARD_PENDING_PUBLISH=1)
    assert r.returncode == 0 and "discarding the unpublished pre_publish checkpoint" in run_log(vm)
    # any other phase (a dead run's dot_ocr) is not a pending publish
    (ck / "manifest.json").write_text(json.dumps({"phase": "dot_ocr", "count": 5}))
    assert run(vm, "vm_run.sh", "--stop-before-publish").returncode == 0


def test_another_board_job_is_75(vm):
    token = vm["env"]["VM_BOARD_JOB_PATTERN"]
    p = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(30)", token])
    try:
        time.sleep(0.3)
        r = run(vm, "vm_run.sh", "--stop-before-publish")
        assert r.returncode == 75 and "another board run is active" in run_log(vm)
    finally:
        p.kill()


# =================================================================================================
# RUN_PIN_COMMIT
# =================================================================================================

def test_a_pin_runs_exactly_that_commit_never_anything_newer(vm):
    pinned = commit_on_origin(vm, "src_change_1.txt", "reviewed", "reviewed change")
    newer = commit_on_origin(vm, "src_change_2.txt", "not reviewed", "someone else's push")
    r = run(vm, "vm_run.sh", "--stop-before-publish", RUN_PIN_COMMIT=pinned)
    assert r.returncode == 0, run_log(vm)
    assert head(vm["root"]) == pinned != newer and f"head={pinned}" in stub_log(vm)
    assert f"code at {pinned[:7]}" in run_log(vm) and "(pinned)" in run_log(vm)
    assert not (vm["root"] / "src_change_2.txt").exists()


def test_a_pin_that_cannot_be_reached_exactly_is_refused(vm):
    r = run(vm, RUN_PIN_COMMIT="0123456789abcdef0123456789abcdef01234567")
    assert r.returncode == 1 and "— not starting" in run_log(vm)
    assert "python -m foreclosure_scraper" not in stub_log(vm)
    # a checkout already past the pin is refused too (ff-only never goes back)
    base = head(vm["root"])
    commit_on_origin(vm, "later.txt", "x", "later")
    _git(vm["root"], "pull", "-q", "origin", "main")
    r = run(vm, RUN_PIN_COMMIT=base)
    assert r.returncode == 1 and f"pinned {base}" in run_log(vm)


def test_unpinned_runs_pull_origin_main(vm):
    newer = commit_on_origin(vm, "docs/handoff/stealth_leads.json", '[{"x": 1}]', "mac hand-off")
    assert run(vm, "vm_run.sh", "--stop-before-publish").returncode == 0
    assert head(vm["root"]) == newer and "stealth hand-off:" in run_log(vm)


def test_a_checkout_that_changes_the_script_reruns_the_checked_out_copy(vm):
    src = (vm["root"] / "deploy" / "oracle" / "vm_run.sh").read_text()
    marked = src.replace("set -uo pipefail\n", "set -uo pipefail\necho MARKER-PINNED-COPY\n", 1)
    pinned = commit_on_origin(vm, "deploy/oracle/vm_run.sh", marked, "pinned script")
    r = run(vm, "vm_run.sh", "--stop-before-publish", RUN_PIN_COMMIT=pinned)
    assert r.returncode == 0, r.stdout + r.stderr
    assert "re-running the checked-out copy" in r.stdout and "MARKER-PINNED-COPY" in r.stdout
    assert r.stdout.count("re-running the checked-out copy") == 1
    assert len([p for p in (vm["root"] / "logs").glob("vm-run-*.log") if ".mem." not in p.name]) == 1, \
        "the re-run keeps the same log"


# =================================================================================================
# vm_resume.sh on the shared helpers
# =================================================================================================

def test_resume_publish_only_publishes_a_gated_runs_checkpoint_under_the_pin(vm):
    pinned = head(vm["root"])
    commit_on_origin(vm, "unreviewed.txt", "x", "unreviewed")
    r = run(vm, "vm_resume.sh", "--publish-only", STUB_RUN="publish", RESUME_PIN_COMMIT=pinned)
    assert r.returncode == 0, r.stdout + r.stderr
    log = run_log(vm, "vm-resume")
    assert "uv run python scripts/resume_from_checkpoint.py --publish-only" in stub_log(vm)
    assert "watchdog total=25600 avail=700 swapfree=400" in stub_log(vm)
    assert "dashboard published" in log
    assert "published from the run's pre_publish checkpoint" in _git(vm["root"], "log", "-1", "--format=%s").stdout
    assert f"head={pinned}" in stub_log(vm), "the publish ran other code than the pin"
    # (the publish commit itself is rebased onto origin/main before the push, as always)


def test_resume_refuses_below_the_publish_need(vm):
    env = {k: v for k, v in vm["env"].items() if k != "RESUME_MIN_FREE_MB"}
    out = subprocess.run(["bash", "-c", 'ROOT="$PWD"; . deploy/oracle/vm_lib.sh; vm_publish_need_mb'],
                         capture_output=True, text=True, cwd=vm["root"], env=env)
    assert out.stdout.strip() == "7003"
    r = run(vm, "vm_resume.sh", "--publish-only", RESUME_MIN_FREE_MB=10**9)
    assert r.returncode == 1 and "need 1000000000 MB (RESUME_MIN_FREE_MB override; computed publish: " \
        "7000 + replaced board 3 = 7003" in run_log(vm, "vm-resume")


# =================================================================================================
# install_timer.sh
# =================================================================================================

def test_install_timer_is_a_dry_run_by_default_with_the_fixed_values(vm, tmp_path):
    units = tmp_path / "units"
    r = run(vm, "install_timer.sh", UNIT_DIR=units)
    assert r.returncode == 0, r.stderr
    out = r.stdout
    assert "DRY RUN" in out and not units.exists()
    assert "TimeoutStartSec=30h" in out and "TimeoutStartSec=6h" not in out
    assert "OnCalendar=*-*-* 13:00:00 UTC" in out
    exec_line = next(line for line in out.splitlines() if line.startswith("ExecStart="))
    assert exec_line.endswith("deploy/oracle/vm_run.sh"), "the unattended run publishes (no --stop-before-publish)"


def test_install_timer_install_refuses_without_persistent_swap_then_writes(vm, tmp_path):
    units = tmp_path / "units"
    units.mkdir()
    stubs = tmp_path / "stubs"
    _exe(stubs / "sudo", '#!/bin/sh\nexec "$@"\n')
    _exe(stubs / "systemctl", '#!/bin/sh\necho "systemctl $*" >> "$STUB_LOG"\n')
    no_swap = tmp_path / "fstab-no-swap"
    no_swap.write_text("LABEL=root / ext4 defaults 0 1\n")
    r = run(vm, "install_timer.sh", "--install", UNIT_DIR=units, FSTAB=no_swap)
    assert r.returncode == 1 and "no swap entry" in r.stderr and not list(units.iterdir())
    r = run(vm, "install_timer.sh", "--install", UNIT_DIR=units, FSTAB=vm["fstab"])
    assert r.returncode == 0, r.stderr
    assert "TimeoutStartSec=30h" in (units / "foreclosure.service").read_text()
    assert "13:00:00 UTC" in (units / "foreclosure.timer").read_text()
    assert "systemctl enable --now foreclosure.timer" in stub_log(vm)
    assert run(vm, "install_timer.sh", RUN_AT="7am", UNIT_DIR=units).returncode == 64


# =================================================================================================
# refdata_check.py
# =================================================================================================

def _refdata(vm, *args):
    return subprocess.run([sys.executable, str(vm["root"] / "deploy/oracle/refdata_check.py"), *args,
                           "--root", str(vm["root"])], capture_output=True, text=True)


def test_refdata_manifest_lists_every_county_and_refuses_an_incomplete_source(vm):
    man = json.loads((vm["root"] / "data/refdata_manifest.json").read_text())
    assert sorted(k for k in man["files"] if k.startswith("data/parcel_cache/")) == [
        "data/parcel_cache/aiken.sqlite", "data/parcel_cache/buncombe.sqlite",
        "data/parcel_cache/cherokee_nc.sqlite"]
    assert man["files"]["data/sc_footprints.db"]["size"] > 0
    (vm["root"] / "data/parcel_inventory.db").unlink()
    r = _refdata(vm, "write-manifest")
    assert r.returncode == 1 and "data/parcel_inventory.db" in r.stderr


def test_refdata_verify_reports_a_changed_size_as_a_warning(vm):
    p = vm["root"] / "data/parcel_cache/aiken.sqlite"
    con = sqlite3.connect(p)
    con.executemany("INSERT INTO parcels VALUES (?, ?)", [(str(i), "y" * 4000) for i in range(50)])
    con.commit()
    con.close()
    r = _refdata(vm, "verify")
    assert r.returncode == 0, r.stdout
    assert "aiken.sqlite" in r.stdout and "the manifest says" in r.stdout and "WARNING" in r.stdout
