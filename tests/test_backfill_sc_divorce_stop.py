"""Stop conditions for scripts/backfill_sc_divorce.py.

2026-09-18: round 4 tripped the enricher's throttle guard (51 errors) and the
script, which only stopped on a failed handshake, would have started round 5
immediately against a portal that was already failing.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

from backfill_sc_divorce import (  # noqa: E402
    LOW_YIELD_MIN_SEARCHED, LOW_YIELD_ROUNDS, stop_decision,
)


def _stats(searched, hits, **extra):
    return {"searched": searched, "with_divorce": hits, "errors": 0, **extra}


def test_throttle_abort_stops_even_with_a_healthy_hit_rate():
    # Round 4's real numbers: 13.9% hit rate, but the portal was failing.
    stop, reason, _ = stop_decision(_stats(662, 92, errors=51, aborted_throttled=True), 0)
    assert stop and "failing calls" in reason and "51" in reason


def test_handshake_failure_stops():
    stop, reason, _ = stop_decision({"error": "handshake_failed"}, 0)
    assert stop and "handshake" in reason


def test_healthy_round_continues_and_resets_the_low_yield_streak():
    stop, _, low = stop_decision(_stats(1500, 180), 1)
    assert not stop and low == 0


def test_low_yield_needs_consecutive_rounds():
    s = _stats(1583, 10)                                  # 0.6%: round 3's real numbers
    stop, _, low = stop_decision(s, 0)
    assert not stop and low == 1
    stop, reason, low = stop_decision(s, low)
    assert stop and low == LOW_YIELD_ROUNDS and "low-yield" in reason


def test_tiny_rounds_do_not_count_as_low_yield():
    stop, _, low = stop_decision(_stats(LOW_YIELD_MIN_SEARCHED - 1, 0), LOW_YIELD_ROUNDS - 1)
    assert not stop and low == 0
