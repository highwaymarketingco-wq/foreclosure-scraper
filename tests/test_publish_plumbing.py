"""The plumbing between a written board and a live dashboard.

Every failure pinned here was silent in production: the board was correct on
disk and the site did not get it, or got half of it, or got two halves from
different publishes. None of them raised.

Covered:
  1. THE BOARD LOCK — one writer at a time, across shell AND Python, with a
     stale lock from a dead PID broken automatically.
  2. THE PUBLISH PATHSPEC LIST — what `git add` is handed, and the two ways
     (gitignored path, absent-and-untracked path) it silently stages nothing.
  3. THE JEKYLL PREFIX TRAP — check_pages_publish.py must FAIL when a payload
     would be dropped, including the detail shards.
  4. run_meta's honesty — carried health is labelled, derived counts describe
     the board that was actually written.
  5. FORECLOSURE_SLIM=0 as a real emergency stop.
  6. read_board_records — the sidecar-merging read the board writers must use.
"""
from __future__ import annotations

import gzip
import json
import os
import subprocess
import sys
import time
from pathlib import Path

import pytest

from foreclosure_scraper.models import Listing, ListingType
from foreclosure_scraper.web_artifact import (
    BOARD_LOCK_ENV,
    BoardLockBusy,
    DETAIL_SHARD_DIR,
    board_lock,
    board_lock_dir,
    load_board,
    read_board_records,
    write_artifact,
)

REPO = Path(__file__).resolve().parent.parent
SCRIPTS = REPO / "scripts"
LOCK_SH = SCRIPTS / "board_lock.sh"
PAYLOAD_SH = SCRIPTS / "board_payload.sh"


def _lead(i: int) -> Listing:
    return Listing(source=f"src.{i % 2}", source_url=f"u{i}",
                   listing_type=ListingType.FORECLOSURE_SALE,
                   state="NC" if i % 3 else "SC", county="Gaston",
                   parcel_id=f"P{i}", street_address=f"{i} Main St",
                   raw={"grade": {"overall": "B"},
                        "comps": [{"addr": f"{i} Elm", "sold_price": 200000 + i}],
                        "vision": {"parsed": True}})


# ===========================================================================
# 1. THE BOARD LOCK
#
# The critical section is load_board -> mutate -> write_artifact and it runs for
# minutes to hours. The pgrep guards it replaces were TOCTOU-racy by
# construction: a check taken BEFORE the section cannot see a writer that starts
# after it. On 2026-08-10 the noon lrcpwa pass (1,064 parcels resolved, 343
# county values, 410 absentee tags) was silently reverted by the vision job
# writing back a four-hour-old board.
#
# The protocol is implemented TWICE — web_artifact.board_lock and
# scripts/board_lock.sh — so a shell wrapper and a Python board-writer contend
# for the same lock. These tests drive each implementation against the other.
# That cross-check IS the anti-drift guard; without it the two sides can
# disagree about what the lock is and neither will ever say so.
# ===========================================================================

def _shell_lock_script(tmp_path: Path) -> Path:
    """A shell process that takes the lock, holds it, then releases."""
    p = tmp_path / "hold.sh"
    p.write_text(
        f'. "{LOCK_SH}"\n'
        'if board_lock_acquire "$1" "$2"; then\n'
        '  echo ACQUIRED; sleep "$3"; board_lock_release; echo RELEASED\n'
        'else\n'
        '  echo "DECLINED $(board_lock_holder)"\n'
        'fi\n'
    )
    return p


def _sh(script: Path, *args, shell="/bin/sh", **kw):
    return subprocess.run([shell, str(script), *[str(a) for a in args]],
                          capture_output=True, text=True, **kw)


def _py_lock_script(tmp_path: Path) -> Path:
    p = tmp_path / "hold.py"
    p.write_text(
        "import sys, time\n"
        f"sys.path.insert(0, {str(REPO / 'src')!r})\n"
        "from foreclosure_scraper.web_artifact import board_lock, BoardLockBusy\n"
        "try:\n"
        "    with board_lock(sys.argv[1], owner='pytest-py'):\n"
        "        print('ACQUIRED', flush=True); time.sleep(float(sys.argv[2]))\n"
        "    print('RELEASED')\n"
        "except BoardLockBusy as e:\n"
        "    print('DECLINED', e)\n"
    )
    return p


def test_python_lock_excludes_a_second_python_writer(tmp_path):
    with board_lock(tmp_path, owner="first"):
        with pytest.raises(BoardLockBusy) as ei:
            # A nested acquire from a DIFFERENT logical owner: clear the
            # reentrancy marker the outer `with` exported, which is what a
            # genuinely separate process would see.
            held = os.environ.pop(BOARD_LOCK_ENV)
            try:
                with board_lock(tmp_path, owner="second"):
                    pytest.fail("second writer must not get the lock")
            finally:
                os.environ[BOARD_LOCK_ENV] = held
        assert "first" in str(ei.value)


def test_lock_is_released_on_exit_and_on_exception(tmp_path):
    with board_lock(tmp_path, owner="a"):
        assert board_lock_dir(tmp_path).is_dir()
    assert not board_lock_dir(tmp_path).exists()

    with pytest.raises(ValueError):
        with board_lock(tmp_path, owner="b"):
            raise ValueError("boom")
    assert not board_lock_dir(tmp_path).exists(), (
        "a lock that survives an exception stops every scheduled job forever"
    )


def test_a_lock_held_by_a_dead_pid_is_broken_automatically(tmp_path):
    """THE failure mode that would take the whole system down.

    /usr/bin/shlock — the obvious macOS answer, and the one the audit assumed
    would work — does NOT do this. Measured on this machine (shell_cmds-326):
    a lock whose owner is genuinely dead gives `process N is dead N` followed by
    `lock time changed <mtime> >= 0` and exit 1, on every invocation. Built on
    that, one killed run would stop every scheduled job permanently.
    """
    d = board_lock_dir(tmp_path)
    d.mkdir(parents=True)
    (d / "pid").write_text("99998\nzombie\n")          # a PID that is not alive
    assert not _pid_alive(99998), "fixture PID is somehow running"

    with board_lock(tmp_path, owner="survivor"):
        pid, owner = (d / "pid").read_text().splitlines()
        assert int(pid) == os.getpid()
        assert owner == "survivor"


def test_a_lock_directory_with_no_pid_file_is_broken(tmp_path):
    """Wreckage from a process killed between mkdir and the pid write."""
    board_lock_dir(tmp_path).mkdir(parents=True)
    with board_lock(tmp_path, owner="survivor"):
        assert (board_lock_dir(tmp_path) / "pid").exists()


def test_lock_is_reentrant_through_the_environment(tmp_path):
    """A shell wrapper holds the lock and runs a Python writer that also asks
    for it. Without this the daily vision job deadlocks against itself."""
    d = board_lock_dir(tmp_path)
    d.mkdir(parents=True)
    (d / "pid").write_text(f"{os.getpid()}\nparent-wrapper\n")
    os.environ[BOARD_LOCK_ENV] = str(d)
    try:
        with board_lock(tmp_path, owner="child"):
            # the child must NOT overwrite the parent's ownership record
            assert (d / "pid").read_text().splitlines()[1] == "parent-wrapper"
        # and must NOT release what it did not take
        assert d.is_dir(), "a reentrant child released its parent's lock"
    finally:
        os.environ.pop(BOARD_LOCK_ENV, None)


def _pid_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


@pytest.mark.parametrize("shell", ["/bin/sh", "/bin/bash", "/bin/zsh"])
def test_shell_lock_excludes_a_second_shell_writer(tmp_path, shell):
    if not Path(shell).exists():
        pytest.skip(f"{shell} not present")
    hold = _shell_lock_script(tmp_path)
    root = tmp_path / "repo"
    root.mkdir()
    first = subprocess.Popen([shell, str(hold), str(root), "first", "3"],
                             stdout=subprocess.PIPE, text=True)
    try:
        _wait_for_lock(root, "first")
        second = _sh(hold, root, "second", "0", shell=shell)
        assert "DECLINED" in second.stdout, second.stdout
        assert "first" in second.stdout
    finally:
        first.terminate()
        first.wait(timeout=10)


def test_shell_lock_blocks_python_and_python_blocks_shell(tmp_path):
    """The cross-implementation check. Two lock implementations that do not
    exclude each other are not a lock — and this system's board writers are
    half shell wrappers and half Python."""
    hold_sh = _shell_lock_script(tmp_path)
    hold_py = _py_lock_script(tmp_path)
    root = tmp_path / "repo"
    root.mkdir()

    # shell holds -> python must decline
    p = subprocess.Popen(["/bin/sh", str(hold_sh), str(root), "shellowner", "5"],
                         stdout=subprocess.PIPE, text=True)
    try:
        _wait_for_lock(root, "shellowner")
        r = subprocess.run([sys.executable, str(hold_py), str(root), "0"],
                           capture_output=True, text=True, env=_clean_env())
        assert "DECLINED" in r.stdout, r.stdout + r.stderr
        assert "shellowner" in r.stdout
    finally:
        p.terminate()
        p.wait(timeout=10)

    # python holds -> shell must decline
    p = subprocess.Popen([sys.executable, str(hold_py), str(root), "5"],
                         stdout=subprocess.PIPE, text=True, env=_clean_env())
    try:
        _wait_for_lock(root, "pytest-py")
        r = _sh(hold_sh, root, "shell2", "0")
        assert "DECLINED" in r.stdout, r.stdout + r.stderr
        assert "pytest-py" in r.stdout
    finally:
        p.terminate()
        p.wait(timeout=10)


def test_shell_lock_breaks_a_dead_pid_lock(tmp_path):
    root = tmp_path / "repo"
    (root / "logs" / ".board.lock").mkdir(parents=True)
    (root / "logs" / ".board.lock" / "pid").write_text("99998\nzombie\n")
    r = _sh(_shell_lock_script(tmp_path), root, "survivor", "0")
    assert "ACQUIRED" in r.stdout, r.stdout + r.stderr


def _clean_env() -> dict:
    env = dict(os.environ)
    env.pop(BOARD_LOCK_ENV, None)
    return env


def _wait_for_lock(root: Path, owner: str, timeout: float = 15.0) -> None:
    """Wait for a SPECIFIC owner to hold the lock.

    Not "a pid file exists": a holder killed with SIGTERM leaves its lock
    directory behind (that is the stale lock the next writer is supposed to
    break), so a generic wait matches the corpse of the previous phase and the
    test races itself rather than the code.
    """
    pid_file = root / "logs" / ".board.lock" / "pid"
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        try:
            lines = pid_file.read_text().splitlines()
        except OSError:
            lines = []
        if len(lines) > 1 and lines[1].strip() == owner:
            return
        time.sleep(0.05)
    raise AssertionError(f"{owner} never took the lock")


# ===========================================================================
# 2. THE PUBLISH PATHSPEC LIST
#
# `git add docs/listings.json docs/run_health.json 2>/dev/null || true` is what
# two ACTIVE workflows ran. docs/listings.json is gitignored, so git skipped it,
# staged the rest, exited non-zero — and the redirect swallowed both the message
# and the status. The workflows committed run_health.json alone: a health report
# describing a board they did not ship.
# ===========================================================================

def _git(root: Path, *args) -> subprocess.CompletedProcess:
    return subprocess.run(["git", "-C", str(root), *args],
                          capture_output=True, text=True)


def _tiny_repo(tmp_path: Path) -> Path:
    root = tmp_path / "repo"
    (root / "docs").mkdir(parents=True)
    _git(root.parent, "init", "-q", str(root))
    _git(root, "config", "user.email", "t@t")
    _git(root, "config", "user.name", "t")
    (root / ".gitignore").write_text("docs/listings.json\n")
    return root


def test_git_add_of_an_ignored_path_stages_the_rest_but_fails(tmp_path):
    """The exact mechanism behind D1, proven rather than assumed."""
    root = _tiny_repo(tmp_path)
    (root / "docs" / "listings.json").write_text("[]")
    (root / "docs" / "run_health.json").write_text("{}")
    r = _git(root, "add", "docs/listings.json", "docs/run_health.json")
    assert r.returncode != 0, "an ignored pathspec must make git add fail"
    staged = _git(root, "diff", "--cached", "--name-only").stdout.split()
    assert staged == ["docs/run_health.json"], (
        "git staged the rest and only the STATUS said so — which `2>/dev/null "
        "|| true` threw away"
    )


def test_git_add_of_an_absent_untracked_path_stages_nothing_at_all(tmp_path):
    """The other half: this one is worse, because it takes the whole publish
    down rather than one file. It is why every pathspec is gated on
    'exists OR is already tracked'."""
    root = _tiny_repo(tmp_path)
    (root / "docs" / "run_health.json").write_text("{}")
    r = _git(root, "add", "docs/run_health.json", "docs/listings_slim.json.gz")
    assert r.returncode == 128
    assert _git(root, "diff", "--cached", "--name-only").stdout.strip() == "", (
        "an absent+untracked pathspec makes git add stage NOTHING AT ALL"
    )


def _payload_paths(root: Path) -> list[str]:
    r = subprocess.run(
        ["/bin/sh", "-c", f'. "{PAYLOAD_SH}"; board_payload_paths "$1"', "sh", str(root)],
        capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    return r.stdout.split()


def test_payload_list_never_names_a_gitignored_board_file(tmp_path):
    root = _tiny_repo(tmp_path)
    for name in ("listings.json", "listings_detail.json", "listings_slim.json"):
        (root / "docs" / name).write_text("[]")
        (root / "docs" / f"{name}.gz").write_bytes(gzip.compress(b"[]"))
    paths = _payload_paths(root)
    for name in ("docs/listings.json", "docs/listings_detail.json",
                 "docs/listings_slim.json"):
        assert name not in paths, f"{name} is gitignored; naming it voids the add"
    assert "docs/listings.json.gz" in paths
    assert "docs/listings_slim.json.gz" in paths


def test_payload_list_skips_absent_untracked_and_keeps_tracked_deletions(tmp_path):
    root = _tiny_repo(tmp_path)
    (root / "docs" / "listings.json.gz").write_bytes(gzip.compress(b"[]"))
    assert "docs/listings_slim.json.gz" not in _payload_paths(root), (
        "absent AND untracked must be skipped or `git add` exits 128 and stages "
        "nothing at all"
    )
    # once tracked, its DELETION must still be stageable — that is how the
    # slim emitter's delete-on-failure path and FORECLOSURE_SLIM=0 reach the site
    (root / "docs" / "listings_slim.json.gz").write_bytes(gzip.compress(b"[]"))
    _git(root, "add", "docs/listings_slim.json.gz")
    _git(root, "commit", "-qm", "seed")
    (root / "docs" / "listings_slim.json.gz").unlink()
    assert "docs/listings_slim.json.gz" in _payload_paths(root)


def test_payload_add_stages_the_whole_payload(tmp_path):
    root = _tiny_repo(tmp_path)
    write_artifact([_lead(i) for i in range(3)], {"notes": "t"},
                   docs_dir=root / "docs")
    (root / "docs" / "run_health.json").write_text("{}")
    r = subprocess.run(
        ["/bin/sh", "-c", f'. "{PAYLOAD_SH}"; board_payload_add "$1"', "sh", str(root)],
        capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    staged = set(_git(root, "diff", "--cached", "--name-only").stdout.split())
    for required in ("docs/listings.json.gz", "docs/listings_detail.json.gz",
                     "docs/listings_slim.json.gz", "docs/run_meta.json",
                     "docs/run_health.json"):
        assert required in staged, f"{required} was not staged"
    assert any(p.startswith(f"docs/{DETAIL_SHARD_DIR}/") for p in staged), (
        "the detail shards are the payload phones fetch to open a lead"
    )


def test_payload_stash_survives_a_hard_reset(tmp_path, monkeypatch):
    """The workflows `git reset --hard origin/main` to rebase their output onto
    whatever landed during the run. That destroys every tracked payload file;
    the old cp/mv preserved exactly the two files it (wrongly) staged."""
    root = _tiny_repo(tmp_path)
    (root / "docs" / "run_health.json").write_text("{}")
    write_artifact([_lead(i) for i in range(3)], {"notes": "t"},
                   docs_dir=root / "docs")
    subprocess.run(["/bin/sh", "-c",
                    f'. "{PAYLOAD_SH}"; board_payload_add "$1"', "sh", str(root)],
                   check=True)
    _git(root, "commit", "-qm", "seed")
    before = (root / "docs" / "listings.json.gz").read_bytes()
    n_shards = len(list((root / "docs" / DETAIL_SHARD_DIR).iterdir()))

    tar = tmp_path / "payload.tar"
    subprocess.run(["/bin/sh", "-c",
                    f'. "{PAYLOAD_SH}"; board_payload_stash "$1" "$2"',
                    "sh", str(root), str(tar)], check=True)
    # The clobber deliberately shrinks the board 3 -> 1 to prove the stash
    # survives a destructive overwrite. That shrink now trips the count guard,
    # so opt in exactly as a real caller with an intentional shrink would.
    monkeypatch.setenv("BOARD_ALLOW_SHRINK", "1")
    write_artifact([_lead(0)], {"notes": "clobbered"}, docs_dir=root / "docs")
    monkeypatch.delenv("BOARD_ALLOW_SHRINK", raising=False)
    assert (root / "docs" / "listings.json.gz").read_bytes() != before
    subprocess.run(["/bin/sh", "-c",
                    f'. "{PAYLOAD_SH}"; board_payload_unstash "$1" "$2"',
                    "sh", str(root), str(tar)], check=True)

    assert (root / "docs" / "listings.json.gz").read_bytes() == before
    assert len(list((root / "docs" / DETAIL_SHARD_DIR).iterdir())) == n_shards, (
        "the shard DIRECTORY must come back too — cp could not do that"
    )


# ===========================================================================
# 3. THE JEKYLL PREFIX TRAP
#
# Jekyll's exclude/include are PREFIX matches, so `exclude: listings.json` also
# drops listings.json.gz. It has 404'd this site's data three times.
# check_pages_publish.py exists to catch it and, until now, had NO CALLER
# anywhere in the repo.
# ===========================================================================

def _load_checker():
    import importlib.util
    spec = importlib.util.spec_from_file_location(
        "check_pages_publish", SCRIPTS / "check_pages_publish.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_pages_check_lists_the_detail_shards_as_required():
    mod = _load_checker()
    assert any(p.startswith(f"{DETAIL_SHARD_DIR}/") for p in mod.REQUIRED), (
        "the shard set is the only payload the LEAN client fetches to open a "
        "lead; excluding it 404s every mobile detail panel"
    )
    assert any(p.startswith(f"{DETAIL_SHARD_DIR}/") for p in mod.SIMULATED), (
        "it must be simulated too, or the check passes vacuously on a checkout "
        "where no publish has run"
    )


def test_pages_check_reads_the_shard_dir_name_from_the_source():
    """Hardcoding it would let a rename leave this check asking about a path
    that no longer exists — passing, vacuously, forever."""
    assert _load_checker().DETAIL_SHARD_DIR == DETAIL_SHARD_DIR


@pytest.mark.parametrize("excluded", ["detail_shards", "listings.json",
                                      "listings_slim.json"])
def test_pages_check_fails_when_a_payload_would_be_dropped(tmp_path, excluded):
    """Adding `- detail_shards` to exclude turned tests/test_detail_shards.py
    red and left this script at exit 0. It must now be the script that says so.
    """
    mod = _load_checker()
    docs = tmp_path / "docs"
    (docs / DETAIL_SHARD_DIR).mkdir(parents=True)
    for name in ("index.html", "dashboard.js", "style.css", "premium.css",
                 "run_meta.json", "multifamily.json", "foreclosure_sold_pool.json"):
        (docs / name).write_text("x")
    (docs / "_config.yml").write_text(f"exclude:\n  - {excluded}\n")
    mod.DOCS, mod.CONFIG = docs, docs / "_config.yml"
    assert mod.main() == 1, f"excluding {excluded} must fail the check"

    # ...and the same config plus the matching include must pass, or the check
    # is just refusing everything.
    (docs / "_config.yml").write_text(
        f"exclude:\n  - {excluded}\ninclude:\n  - {excluded}\n")
    assert mod.main() == 0


def test_pages_check_passes_on_the_real_repo():
    mod = _load_checker()
    assert mod.main() == 0, "the live docs/_config.yml would 404 a payload"


def test_pages_check_is_wired_into_the_publish_paths():
    """It had no caller. A guard nobody runs is documentation."""
    callers = {
        ".github/workflows/pages.yml": "the deploy itself",
        ".github/workflows/patch-listings.yml": "the active patch workflow",
        ".github/workflows/patch-run-scrapers.yml": "the active re-run workflow",
        "scripts/board_payload.sh": "every local publisher, via board_payload_check",
    }
    for rel, why in callers.items():
        text = (REPO / rel).read_text()
        assert "check_pages_publish" in text, f"{rel} ({why}) stopped calling it"
    # and the local wrappers must call board_payload_check
    for rel in ("scripts/run_local.sh", "scripts/lrcpwa_refresh.sh",
                "scripts/sos_agent_refresh.sh"):
        assert "board_payload_check" in (REPO / rel).read_text(), rel


# ===========================================================================
# 4. run_meta HONESTY
#
# run_meta.json is the only per-source health report there is, and it had
# stopped labelling its stale half. The live file's by_state summed 36,060
# against a 38,500 board.
# ===========================================================================

def test_carried_health_is_labelled_and_derived_counts_are_not(tmp_path):
    leads = [_lead(i) for i in range(9)]
    write_artifact(leads, {"notes": "full run",
                           "by_source": {"scraper.a": 999},
                           "source_status": {"scraper.a": "ok"}},
                   docs_dir=tmp_path)
    first = json.loads((tmp_path / "run_meta.json").read_text())
    assert "health_carried_from" not in first, "nothing was carried on run 1"

    # a partial writer, passing only its own notes — the shape every
    # maintenance script now uses
    write_artifact(leads, {"notes": "scheduled pass"}, docs_dir=tmp_path)
    second = json.loads((tmp_path / "run_meta.json").read_text())
    assert second["by_source"] == {"scraper.a": 999}, "health must survive"
    assert second["health_carried_from"] == first["run_time"], (
        "carried health that is not labelled is asserted as current"
    )
    assert "by_source" in second["health_carried_keys"]
    assert "by_state" not in second["health_carried_keys"], (
        "by_state is derived from the board, so there is nothing to carry"
    )


def test_by_state_and_by_source_on_board_describe_the_board_written(tmp_path):
    """The live file said NC 18,712 / SC 17,348 — 36,060 against a 38,500 board,
    2,440 leads unaccounted for — because it was a scrape-time count carried
    forward across writers. These two are pure functions of the payload."""
    leads = [_lead(i) for i in range(9)]
    write_artifact(leads, {"notes": "t", "by_state": {"NC": 1, "SC": 1}},
                   docs_dir=tmp_path)
    meta = json.loads((tmp_path / "run_meta.json").read_text())
    assert sum(meta["by_state"].values()) == len(leads) == meta["total"], (
        "by_state must sum to the board it describes, whatever the caller said"
    )
    assert sum(meta["by_source_on_board"].values()) == len(leads)
    assert meta["by_state"] == {"NC": 6, "SC": 3}


def test_run_meta_declares_the_detail_sidecar_this_publish_wrote(tmp_path):
    """dashboard.js ensureDetails() merges listings_detail.json whenever
    details.length === LISTINGS.length. The board has been exactly 38,500 for
    four publishes, so that proves nothing and a cross-publish sidecar
    Object.assigns one property's comps onto another's address.

    run_meta.json is fetched cache-busted on every load, so these two keys are
    the one always-current statement a possibly-cached sidecar can be checked
    against."""
    write_artifact([_lead(i) for i in range(4)], {"notes": "t"}, docs_dir=tmp_path)
    meta = json.loads((tmp_path / "run_meta.json").read_text())
    detail = json.loads((tmp_path / "listings_detail.json").read_text())
    assert meta["detail_count"] == len(detail) == 4

    import hashlib
    gz = (tmp_path / "listings_detail.json.gz").read_bytes()
    assert meta["detail_digest"] == hashlib.sha256(gz).hexdigest()[:16]

    # a different publish with the SAME record count must get a different digest
    write_artifact([_lead(i + 100) for i in range(4)], {"notes": "t"},
                   docs_dir=tmp_path)
    other = json.loads((tmp_path / "run_meta.json").read_text())
    assert other["detail_count"] == meta["detail_count"] == 4
    assert other["detail_digest"] != meta["detail_digest"], (
        "length equality cannot distinguish publishes; the digest must"
    )


def test_detail_declaration_is_top_level_not_inside_the_board_block(tmp_path):
    """The board block is pinned to {schema, count, detail_shards} by
    tests/test_board_slim.py AND is deliberately absent when the slim payload is
    not written — while the desktop sidecar is written unconditionally."""
    write_artifact([_lead(0)], {"notes": "t"}, docs_dir=tmp_path)
    meta = json.loads((tmp_path / "run_meta.json").read_text())
    assert set(meta["board"]) - {"schema", "count"} <= {"detail_shards"}
    assert "detail_count" in meta and "detail_digest" in meta


def test_detail_declaration_survives_the_slim_emergency_stop(tmp_path, monkeypatch):
    monkeypatch.setenv("FORECLOSURE_SLIM", "0")
    write_artifact([_lead(0), _lead(1)], {"notes": "t"}, docs_dir=tmp_path)
    meta = json.loads((tmp_path / "run_meta.json").read_text())
    assert "board" not in meta                    # mobile payload is off
    assert meta["detail_count"] == 2              # desktop join still declared


# ===========================================================================
# 5. FORECLOSURE_SLIM=0 AS A REAL EMERGENCY STOP
# ===========================================================================

def test_slim_emergency_stop_deletes_the_previous_slim_files(tmp_path, monkeypatch):
    """It returned None BEFORE the try block, so it never removed anything.
    Both slim files survived with PREVIOUS-BOARD content while meta["board"] was
    omitted — which sets boardExpectedCount null and DISABLES the client's
    record-count gate — and the LEAN client still fetches
    listings_slim.json.gz FIRST. Phones rendered the previous board's addresses
    and sale dates beside a current desktop, with no error: the exact failure
    the flag exists to prevent, caused by the flag."""
    write_artifact([_lead(i) for i in range(4)], {"notes": "t"}, docs_dir=tmp_path)
    slim = tmp_path / "listings_slim.json"
    gz = tmp_path / "listings_slim.json.gz"
    assert slim.exists() and gz.exists()
    stale = gz.read_bytes()

    monkeypatch.setenv("FORECLOSURE_SLIM", "0")
    write_artifact([_lead(i + 50) for i in range(4)], {"notes": "t"},
                   docs_dir=tmp_path)
    assert not slim.exists() and not gz.exists(), (
        "the previous board's slim payload survived an emergency stop"
    )
    assert stale  # the bytes that used to be served to phones
    assert not (tmp_path / DETAIL_SHARD_DIR).exists()
    assert "board" not in json.loads((tmp_path / "run_meta.json").read_text())


# ===========================================================================
# 6. read_board_records — the sidecar-merging read every board writer needs
#
# patch_run_scrapers.py, patch_listings.py and retry_vision.py read via
# read_board_json, which reads ONLY the slim listings.json, and then wrote the
# board back: comps (33,484 records), vision (13,088), CAMA (12,952), rent comps
# (6,401) and foreclosure sold comps (5,524), stripped on every run.
# ===========================================================================

def test_read_board_records_merges_the_sidecar(tmp_path):
    write_artifact([_lead(0), _lead(1)], {"notes": "t"}, docs_dir=tmp_path)
    plain = json.loads((tmp_path / "listings.json").read_text())
    assert "comps" not in (plain[0].get("raw") or {}), "fixture must exercise the split"

    merged = read_board_records(tmp_path)
    assert merged[0]["raw"]["comps"][0]["sold_price"] == 200000
    assert merged[0]["raw"]["vision"]["parsed"] is True
    assert len(merged) == len(plain)


def test_read_board_records_round_trips_without_losing_detail(tmp_path):
    """The write-back path the three converted scripts take: dicts in, Listings
    out, write_artifact. The sidecar must still be there afterwards."""
    write_artifact([_lead(0), _lead(1)], {"notes": "t"}, docs_dir=tmp_path)
    recs = read_board_records(tmp_path)
    recs[0]["owner_name"] = "NEW OWNER"
    write_artifact([Listing.model_validate(r) for r in recs], {"notes": "t2"},
                   docs_dir=tmp_path)
    detail = json.loads((tmp_path / "listings_detail.json").read_text())
    assert detail[0]["comps"][0]["sold_price"] == 200000, (
        "a dict-level board writer must not strip the sidecar"
    )
    assert load_board(tmp_path)[0].owner_name == "NEW OWNER"


def test_read_board_records_falls_back_to_the_committed_gz(tmp_path):
    """Every CI checkout and every fresh clone has ONLY the .gz — the
    uncompressed twins are gitignored (>100MB)."""
    write_artifact([_lead(0)], {"notes": "t"}, docs_dir=tmp_path)
    (tmp_path / "listings.json").unlink()
    (tmp_path / "listings_detail.json").unlink()
    merged = read_board_records(tmp_path)
    assert merged[0]["raw"]["comps"][0]["sold_price"] == 200000


def test_board_writers_do_not_read_past_the_sidecar():
    """A source-level guard: any script that writes the board must read it
    through load_board() or read_board_records(). read_board_json() alone is
    correct only for a reader."""
    for rel in ("scripts/patch_run_scrapers.py", "scripts/patch_listings.py",
                "scripts/retry_vision.py", "scripts/patch_vision_gemini.py",
                "scripts/recompute_valuation.py"):
        src = (REPO / rel).read_text()
        assert "write_artifact(" in src, f"{rel} is expected to publish"
        assert ("read_board_records(" in src) or ("load_board(" in src), (
            f"{rel} writes the board but does not read the lazy-detail sidecar"
        )


def test_the_scheduled_board_writers_all_take_the_lock():
    """Every entry point that can hold a board while another job wants it."""
    for rel in ("scripts/run_local.sh", "scripts/run_daily_vision.sh",
                "scripts/lrcpwa_refresh.sh", "scripts/sos_agent_refresh.sh",
                "scripts/ingest_saved.sh"):
        src = (REPO / rel).read_text()
        assert "board_lock_acquire" in src, f"{rel} does not take the board lock"
        assert "board_lock_release" in src, f"{rel} never releases the board lock"
    for rel in ("scripts/patch_vision_gemini.py", "scripts/recompute_valuation.py",
                "scripts/lrcpwa_refresh.py", "scripts/sos_agent_refresh.py",
                "scripts/patch_court_detail.py", "scripts/patch_owner_mailing.py",
                "scripts/patch_distress_score.py", "scripts/patch_listings.py",
                "scripts/patch_run_scrapers.py", "scripts/retry_vision.py"):
        assert "board_lock(" in (REPO / rel).read_text(), (
            f"{rel} writes the board without taking the lock"
        )
