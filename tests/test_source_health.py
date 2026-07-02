"""Source-health monitor — flag logic."""
from __future__ import annotations

import importlib.util
from datetime import datetime, timezone
from pathlib import Path

_spec = importlib.util.spec_from_file_location(
    "source_health_monitor",
    Path(__file__).resolve().parent.parent / "scripts" / "source_health_monitor.py",
)
mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(mod)
evaluate = mod.evaluate

NOW = datetime(2026, 7, 2, tzinfo=timezone.utc)
FRESH = "2026-07-01T12:00:00Z"   # within 3 days of NOW


def _rows(counts: dict[str, int]) -> list[dict]:
    out = []
    for src, n in counts.items():
        out += [{"source": src, "last_seen": FRESH} for _ in range(n)]
    return out


def _hist(runs: list[dict[str, int]]) -> list[dict]:
    return [{"ts": f"2026-06-{20+i}", "fresh": r, "total": r} for i, r in enumerate(runs)]


def test_cratered_source_flagged():
    hist = _hist([{"a": 50}, {"a": 48}, {"a": 52}])
    _, flags = evaluate(_rows({"a": 5}), hist, NOW)
    assert any(f["source"] == "a" and f["severity"] == "CRATERED" for f in flags)


def test_healthy_source_not_flagged():
    hist = _hist([{"a": 50}, {"a": 48}, {"a": 52}])
    _, flags = evaluate(_rows({"a": 45}), hist, NOW)
    assert not flags


def test_gone_source_flagged():
    # 'a' was healthy in history but emits nothing fresh this run
    hist = _hist([{"a": 40}, {"a": 44}, {"a": 41}])
    _, flags = evaluate(_rows({"b": 10}), hist, NOW)
    assert any(f["source"] == "a" and f["severity"] == "GONE" for f in flags)


def test_baseline_run_no_flags():
    _, flags = evaluate(_rows({"a": 50}), [], NOW)
    assert not flags


def test_tiny_source_ignored():
    # median below MIN_BASELINE (5) -> never flagged even at 0
    hist = _hist([{"a": 3}, {"a": 2}, {"a": 3}])
    _, flags = evaluate(_rows({"b": 1}), hist, NOW)
    assert not flags


def test_snapshot_shape():
    snap, _ = evaluate(_rows({"a": 4, "b": 2}), [], NOW)
    assert snap["fresh"] == {"a": 4, "b": 2} and snap["total"] == {"a": 4, "b": 2}
