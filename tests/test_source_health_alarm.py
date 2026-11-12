"""Per-source silent-failure alarm: rolling-baseline / consecutive-zero /
sustained-bleed detection, email surfacing, run_health severity."""
from __future__ import annotations

import json

from foreclosure_scraper.source_health_tracker import (
    evaluate_source, update_source_health,
)
from foreclosure_scraper.email_sender import _source_alarm_banner
from foreclosure_scraper.run_health import _severity


# --- pure evaluation ---
def test_needs_history():
    assert evaluate_source([]) is None
    assert evaluate_source([5]) is None  # one run, can't judge


def test_dead_after_two_consecutive_zeros():
    a = evaluate_source([14, 14, 14, 0, 0], expected_min=5)
    assert a and a["kind"] == "dead" and a["streak"] == 2 and a["baseline"] == 14


def test_single_zero_is_a_blip_not_dead():
    assert evaluate_source([14, 14, 14, 0]) is None  # only 1 trailing zero


def test_sparse_seasonal_source_does_not_false_alarm():
    # mostly-zero source with one spike, then zeros: not "reliable" -> no alarm
    assert evaluate_source([0, 0, 0, 30, 0, 0]) is None


def test_bleeding_sustained_drop():
    a = evaluate_source([40, 40, 40, 5, 5])
    assert a and a["kind"] == "bleeding" and a["drop_pct"] >= 60


def test_single_week_dip_is_not_bleeding():
    assert evaluate_source([40, 40, 40, 5]) is None  # one depressed run only


def test_healthy_no_alarm():
    assert evaluate_source([40, 40, 38]) is None


def test_never_produced_no_alarm():
    # always-zero (e.g. expected_min 0 source) -> no baseline -> no dead alarm
    assert evaluate_source([0, 0, 0]) is None


def test_recovered_no_alarm():
    assert evaluate_source([0, 0, 14]) is None


# --- integration (file-backed) ---
def test_update_persists_and_alarms(tmp_path):
    (tmp_path / "source_history.json").write_text(json.dumps({"x": {"counts": [14, 14, 14, 0]}}))
    alarms = update_source_health({"x": 0}, {"x": 5}, tmp_path)
    assert "x" in alarms and alarms["x"]["kind"] == "dead"
    hist = json.loads((tmp_path / "source_history.json").read_text())
    assert hist["x"]["counts"][-1] == 0  # appended this run
    assert hist["x"]["alarm"]["kind"] == "dead"


def test_update_healthy_no_alarm_and_clears(tmp_path):
    # had an alarm; recovers -> alarm cleared from history
    (tmp_path / "source_history.json").write_text(
        json.dumps({"y": {"counts": [40, 0, 0], "alarm": {"kind": "dead"}}}))
    alarms = update_source_health({"y": 42}, {"y": 5}, tmp_path)
    assert "y" not in alarms
    hist = json.loads((tmp_path / "source_history.json").read_text())
    assert "alarm" not in hist["y"]


def test_tracker_never_raises_on_bad_dir():
    # resilient: a tracker failure must not crash the run
    assert update_source_health({"a": 1}, {"a": 1}, "/nonexistent\0/bad") == {}


# --- email + run_health surfacing ---
def test_email_banner_renders_alarms():
    html = _source_alarm_banner({"source_alarms": {
        "counties_sc.spartanburg": {"reason": "0 listings for 2 consecutive runs"}}})
    assert "SOURCE HEALTH" in html and "spartanburg" in html
    assert _source_alarm_banner({}) == ""


def test_alarm_severity_is_top():
    assert _severity("🔴 ALARM — 0 listings for 2 consecutive runs") == 4
    assert _severity("REGRESSED (expected >= 5)") == 3
    assert _severity("OK (12)") == 0
