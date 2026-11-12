"""scripts/job_watch.py, scripts/check_payload_size.py and foreclosure_scraper.job_events (audit O4, O1, O9, O10)."""
from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from foreclosure_scraper import job_events

REPO = Path(__file__).resolve().parent.parent
WATCH = REPO / "scripts" / "job_watch.py"
SIZE = REPO / "scripts" / "check_payload_size.py"
NOW = datetime(2026, 9, 21, 12, 0, 0, tzinfo=timezone.utc)


def _ts(hours_ago: float) -> str:
    return (NOW - timedelta(hours=hours_ago)).strftime("%Y-%m-%dT%H:%M:%SZ")


def _job(job, outcome, hours_ago):
    return {"ts": _ts(hours_ago), "kind": "job", "job": job, "start": _ts(hours_ago + 0.1), "end": _ts(hours_ago),
            "outcome": outcome, "rows_changed": None, "duration_s": 60}


def _watch(tmp_path, events, *args, first_run_hours_ago=500):
    logs = tmp_path / "logs"
    logs.mkdir(exist_ok=True)
    (logs / "job_events.jsonl").write_text("".join(json.dumps(e) + "\n" for e in events))
    state = logs / ".job_watch_state.json"
    if not state.exists():
        state.write_text(json.dumps({"first_run": _ts(first_run_hours_ago)}))
    return subprocess.run(
        [sys.executable, str(WATCH), "--root", str(tmp_path), "--now", NOW.strftime("%Y-%m-%dT%H:%M:%SZ"),
         "--no-notify", "--no-payload", "--expect", "only_job:48", *args],
        capture_output=True, text=True)


def _only(events_for):     # restrict the default expectations to one job for readable tests
    return events_for


def test_a_job_with_a_recent_ok_is_healthy_and_one_without_alarms(tmp_path):
    ev = [_job("lrcpwa", "ok", 10), _job("sosagent", "ok", 60)]
    out = _watch(tmp_path, ev, "--expect", "lrcpwa:48", "--expect", "sosagent:48")
    assert out.returncode == 1
    alerts = (tmp_path / "logs" / "job_alerts.log").read_text()
    assert "sosagent: no healthy outcome for 60 h (limit 48 h)" in alerts
    assert "lrcpwa:" not in alerts


def test_no_change_counts_as_healthy_but_skips_and_failures_do_not(tmp_path):
    ev = [_job("sosagent", "no_change", 5), _job("lrcpwa", "skipped_lock", 5), _job("lrcpwa", "push_failed", 4),
          _job("lrcpwa", "skipped_memory", 3)]
    out = _watch(tmp_path, ev, "--expect", "sosagent:48", "--expect", "lrcpwa:48", first_run_hours_ago=500)
    alerts = (tmp_path / "logs" / "job_alerts.log").read_text()
    assert "lrcpwa:" in alerts and "sosagent:" not in alerts


def test_three_failures_in_a_row_alarm_even_with_an_old_ok_inside_the_window(tmp_path):
    ev = [_job("lrcpwa", "ok", 40), _job("lrcpwa", "failed", 30), _job("lrcpwa", "failed", 20), _job("lrcpwa", "push_failed", 10)]
    _watch(tmp_path, ev, "--expect", "lrcpwa:48")
    assert "last 3 runs all failed" in (tmp_path / "logs" / "job_alerts.log").read_text()


def test_a_job_that_never_reported_only_alarms_once_the_watcher_has_run_longer_than_its_window(tmp_path):
    young = tmp_path / "young"
    young.mkdir()
    _watch(young, [], "--expect", "lrcpwa:48", first_run_hours_ago=5)
    log = young / "logs" / "job_alerts.log"
    assert not log.exists() or "lrcpwa" not in log.read_text()
    old = tmp_path / "old"
    old.mkdir()
    _watch(old, [], "--expect", "lrcpwa:48", first_run_hours_ago=100)
    assert "no healthy outcome has ever been reported" in (old / "logs" / "job_alerts.log").read_text()


def test_the_same_alarm_is_not_repeated_within_the_realert_window(tmp_path):
    ev = [_job("lrcpwa", "failed", 90)]
    _watch(tmp_path, ev, "--expect", "lrcpwa:48")
    first = (tmp_path / "logs" / "job_alerts.log").read_text().count("lrcpwa")
    _watch(tmp_path, ev, "--expect", "lrcpwa:48")
    assert (tmp_path / "logs" / "job_alerts.log").read_text().count("lrcpwa") == first
    state = json.loads((tmp_path / "logs" / ".job_watch_state.json").read_text())
    assert "job:lrcpwa" in state["last_alert"]


def test_report_mode_prints_a_table_and_raises_nothing(tmp_path):
    out = _watch(tmp_path, [_job("lrcpwa", "ok", 3)], "--report", "--expect", "lrcpwa:48")
    assert out.returncode == 0 and "lrcpwa" in out.stdout and "verdict" in out.stdout
    assert not (tmp_path / "logs" / "job_alerts.log").exists()


def test_the_watcher_runs_under_the_system_python_39_it_is_launched_with():
    py = "/usr/bin/python3"
    if not os.path.exists(py):
        pytest.skip("no system python")
    out = subprocess.run([py, str(WATCH), "--report"], capture_output=True, text=True)
    assert out.returncode == 0, out.stderr
    out = subprocess.run([py, str(SIZE), "--json", "--no-site"], capture_output=True, text=True)
    assert out.returncode in (0, 1, 2), out.stderr


# ---- check_payload_size -----------------------------------------------------------------

def _sparse(path: Path, mib: float):
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "wb") as fh:
        fh.truncate(int(mib * 1024 * 1024))


def test_payload_size_reports_each_file_against_the_limits(tmp_path):
    _sparse(tmp_path / "docs" / "listings.json.gz", 96)
    _sparse(tmp_path / "docs" / "listings_slim.json.gz", 60)
    _sparse(tmp_path / "docs" / "listings_detail.json.gz", 16)
    _sparse(tmp_path / "docs" / "detail_shards" / "00000.json.gz", 3)
    out = subprocess.run([sys.executable, str(SIZE), "--root", str(tmp_path), "--json", "--no-site"], capture_output=True, text=True)
    assert out.returncode == 2
    data = json.loads(out.stdout)
    by = {f["path"]: f for f in data["files"]}
    assert by["docs/listings.json.gz"]["status"] == "BLOCK" and by["docs/listings.json.gz"]["pct_of_github_limit"] == 96.0
    assert by["docs/listings_slim.json.gz"]["status"] == "WARN"
    assert by["docs/listings_detail.json.gz"]["status"] == "ok"
    assert data["files"][0]["path"] == "docs/listings.json.gz", "biggest file first"
    assert data["limits"]["github_hard_mib"] == 100


def test_payload_size_exit_codes(tmp_path):
    _sparse(tmp_path / "docs" / "listings.json.gz", 10)
    run = lambda *a: subprocess.run([sys.executable, str(SIZE), "--root", str(tmp_path), "--no-site", *a],
                                    capture_output=True, text=True)
    assert run().returncode == 0
    _sparse(tmp_path / "docs" / "listings.json.gz", 55)
    assert run().returncode == 1
    assert "result: WARN" in run().stdout
    _sparse(tmp_path / "docs" / "listings.json.gz", 97)
    assert run().returncode == 2
    assert run("--gate-mib", "120", "--warn-mib", "200").returncode == 0


def test_job_watch_raises_a_payload_alarm_near_github_limit(tmp_path):
    _sparse(tmp_path / "docs" / "listings.json.gz", 88)
    (tmp_path / "scripts").mkdir()
    (tmp_path / "scripts" / "check_payload_size.py").write_text(SIZE.read_text())
    logs = tmp_path / "logs"
    logs.mkdir()
    out = subprocess.run([sys.executable, str(WATCH), "--root", str(tmp_path), "--no-notify", "--expect", "x:1"],
                         capture_output=True, text=True)
    assert "docs/listings.json.gz is 88.0 MiB" in (logs / "job_alerts.log").read_text()


# ---- the python job_events twin ---------------------------------------------------------

def test_record_writes_the_same_shape_as_the_shell_helper(tmp_path):
    line = job_events.record("lrcpwa", "ok", start=time.time() - 5, rows_changed=7, note="x", root=tmp_path)
    (got,) = job_events.read_events(tmp_path)
    assert got == line
    assert got["kind"] == "job" and got["outcome"] == "ok" and got["rows_changed"] == 7 and got["duration_s"] >= 4
    assert got["end"].endswith("Z") and got["start"].endswith("Z")


def test_an_invalid_outcome_is_recorded_as_failed(tmp_path):
    line = job_events.record("j", "banana", root=tmp_path)
    assert line["outcome"] == "failed" and "invalid_outcome" in line["note"]


def test_job_tracker_records_ok_failed_and_measurements(tmp_path, monkeypatch):
    monkeypatch.setenv("JOB_EVENTS_FAKE_SWAPOUTS", "1000")
    with job_events.JobTracker("a", root=tmp_path) as jt:
        jt.rows_changed = 5
        monkeypatch.setenv("JOB_EVENTS_FAKE_SWAPOUTS", "1160")
    with pytest.raises(ValueError):
        with job_events.JobTracker("b", root=tmp_path):
            raise ValueError("x")
    with job_events.JobTracker("c", root=tmp_path) as jt:
        jt.outcome = "no_change"
    a, b, c = job_events.read_events(tmp_path)
    assert a["outcome"] == "ok" and a["rows_changed"] == 5
    assert a["swapouts_start"] == 1000 and a["swapouts_end"] == 1160 and a["swap_out_mb"] > 0 and "rss_peak_mb" in a
    assert b["outcome"] == "failed" and "ValueError" in b["note"]
    assert c["outcome"] == "no_change"


def test_the_events_file_rotates_and_strings_are_cleaned(tmp_path, monkeypatch):
    monkeypatch.setattr(job_events, "MAX_BYTES", 300)
    for i in range(20):
        job_events.record("j", "ok", note='say "hi"\nnow', root=tmp_path)
    live = job_events.events_path(tmp_path)          # conftest points JOB_EVENTS_FILE at a scratch file
    assert live.with_name(live.name + ".1").exists()
    assert all('"' not in (e.get("note") or "") for e in job_events.read_events(tmp_path))


def test_note_lines_are_not_job_outcomes(tmp_path):
    job_events.note("lock_break", root=tmp_path, reason="expired")
    (ev,) = job_events.read_events(tmp_path)
    assert ev["kind"] == "note" and ev["event"] == "lock_break" and "outcome" not in ev
