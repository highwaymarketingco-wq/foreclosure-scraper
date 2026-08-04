"""The wall-clock budget must scale with the queue, not sit at a flat 900s.

Every measured run hit name_resolve.hard_timeout with a flat budget: 568 of
1,060 targets on 2026-08-02, 241 of 400 on 2026-07-26. With 3,688 leads still
eligible and twice-weekly runs, the backlog needed roughly three weeks to drain
while every run paid the full 900s to make that sliver of progress.

The queue is self-limiting — a queried lead is marked and skipped forever — so
the big number is a one-time backlog and the steady state is small. That is
exactly the shape a flat budget gets wrong.
"""
from __future__ import annotations

import importlib

import foreclosure_scraper.enrichment_resolve_name_to_property as R


def _reload(monkeypatch, **env):
    for k in ("FORECLOSURE_NAME_RESOLVE_BUDGET_S",
              "FORECLOSURE_NAME_RESOLVE_SEC_PER_LEAD",
              "FORECLOSURE_NAME_RESOLVE_BUDGET_MIN_S",
              "FORECLOSURE_NAME_RESOLVE_BUDGET_MAX_S"):
        monkeypatch.delenv(k, raising=False)
    for k, v in env.items():
        monkeypatch.setenv(k, v)
    return importlib.reload(R)


def test_backlog_gets_enough_time_to_actually_drain(monkeypatch):
    """The real backlog: 3,688 eligible leads at a measured ~1.6s each. A flat
    900s pass reaches ~568 of them; the budget must cover the whole queue."""
    m = _reload(monkeypatch)
    budget = m._budget_for(3688)
    assert budget >= 3688 * 1.6, (
        f"budget {budget}s cannot drain 3,688 leads at 1.6s each")
    assert budget > 900, "still stuck at the old flat ceiling"


def test_steady_state_is_cheap(monkeypatch):
    """Once the backlog is gone only the week's new leads qualify, and the pass
    must not keep reserving an hour to process forty of them."""
    m = _reload(monkeypatch)
    assert m._budget_for(40) <= 300, "small queue still reserves a long pass"


def test_budget_is_bounded_so_a_stalled_county_cannot_run_forever(monkeypatch):
    m = _reload(monkeypatch)
    assert m._budget_for(10_000_000) == m._BUDGET_MAX_S


def test_zero_targets_still_returns_the_floor_not_zero(monkeypatch):
    """_budget_for(0) must not produce a 0s budget: the pass would bail on its
    own first lead."""
    m = _reload(monkeypatch)
    assert m._budget_for(0) == m._BUDGET_MIN_S > 0


def test_explicit_env_still_pins_the_budget(monkeypatch):
    """The operator override has to keep winning, including over the scaling."""
    m = _reload(monkeypatch, FORECLOSURE_NAME_RESOLVE_BUDGET_S="120")
    assert m._budget_for(50_000) == 120.0
    assert m._budget_for(1) == 120.0
    _reload(monkeypatch)


def test_budget_scales_monotonically_with_the_queue(monkeypatch):
    m = _reload(monkeypatch)
    vals = [m._budget_for(n) for n in (0, 100, 500, 2000, 3688, 10000)]
    assert vals == sorted(vals), f"budget not monotonic in queue size: {vals}"


def test_cap_no_longer_binds_before_the_budget(monkeypatch):
    """The cap is a runaway backstop, not the throttle. It must sit above what
    the budget ceiling can physically process, or it silently becomes the
    limiter again — which is how the 3,688-lead backlog stalled at 1,200."""
    m = _reload(monkeypatch)
    reachable = m._BUDGET_MAX_S / 1.6      # measured throughput, leads
    assert m._CAP >= reachable, (
        f"cap {m._CAP} is below the {reachable:.0f} leads the budget allows")
    assert m._CAP > 3688, "cap still binds before the real backlog is drained"
