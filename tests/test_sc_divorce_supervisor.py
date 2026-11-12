"""Decision helpers for scripts/sc_divorce_when_healthy.py."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

from sc_divorce_when_healthy import HEALTHY_S, classify_exit, is_healthy  # noqa: E402


def test_classify_exit_reads_each_backfill_ending():
    assert classify_exit("round 3: {...}\nno targets left this round — backfill complete.\n") == "done"
    assert classify_exit("2 consecutive rounds under 1% hit rate — remaining leads are low-yield, stopping (resumable).") == "low_yield"
    assert classify_exit("FCCMS is failing calls (throttle guard tripped after 21 errors) — stopping") == "throttled"
    assert classify_exit("FCCMS handshake failed — stopping (resumable).") == "throttled"
    assert classify_exit("Traceback (most recent call last): ...") == "error"
    assert classify_exit("") == "error"


def test_health_is_a_latency_ceiling_and_a_failed_probe_is_unhealthy():
    assert is_healthy(HEALTHY_S) is True
    assert is_healthy(3.0) is True
    assert is_healthy(9.7) is True              # the steady per-request delay since 2026-09-18 15:15
    assert is_healthy(HEALTHY_S + 0.1) is False
    assert is_healthy(25.0) is False            # timing out, not merely slow
    assert is_healthy(None) is False
