"""main.py must fail loudly (audit 2026-09-21 O4, F17).

run() is a 3,500 line coroutine that no unit test executes, so these pin the failure paths
structurally (source order) and the entry point behaviourally (cli() exit codes).

O4: a failed write_artifact used to be logged and ignored: run_health.json was written for a
board that never shipped, the Google Sheet was exported, the digest email went to Greg and Cash,
and the process returned 0, so run_local.sh called it a run.
F17: a scorer failure used to be logged and ignored: the board published with the PRIOR run's
tiers on every row.
"""
from __future__ import annotations

import contextlib
import inspect

import pytest

import foreclosure_scraper.main as m
from foreclosure_scraper import web_artifact as wa


def _fake_lock(exc=None):
    @contextlib.contextmanager
    def lock(*a, **k):
        if exc is not None:
            raise exc
        yield "lock"
    return lock


def _cli(monkeypatch, run_result=None, run_raises=None, lock_exc=None):
    async def fake_run():
        if run_raises is not None:
            raise run_raises
        return run_result
    monkeypatch.setattr(m, "run", fake_run)
    monkeypatch.setattr(wa, "board_lock", _fake_lock(lock_exc))
    with pytest.raises(SystemExit) as ei:
        m.cli()
    return ei.value.code


def test_cli_passes_the_run_result_through(monkeypatch):
    assert _cli(monkeypatch, run_result=0) == 0
    assert _cli(monkeypatch, run_result=m.EXIT_WRITE_FAILED) == 3
    assert _cli(monkeypatch, run_result=m.EXIT_SCORE_FAILED) == 6


def test_cli_maps_a_scoring_failure_to_exit_6(monkeypatch):
    assert _cli(monkeypatch, run_raises=m.ScoreBoardFailed("boom")) == m.EXIT_SCORE_FAILED == 6


def test_cli_exits_75_when_the_board_lock_is_busy_or_memory_refuses(monkeypatch, tmp_path):
    busy = wa.BoardLockBusy(tmp_path / ".board.lock", 123, "run_daily_vision.sh")
    assert _cli(monkeypatch, lock_exc=busy) == m.EXIT_LOCK_BUSY == 75
    assert _cli(monkeypatch, lock_exc=wa.BoardMemoryPressure("swap")) == 75


def test_cli_takes_the_board_lock_for_the_whole_run(monkeypatch):
    seen = {}

    @contextlib.contextmanager
    def lock(*a, **k):
        seen["owner"] = k.get("owner")
        seen["max_runtime"] = k.get("max_runtime")
        yield "lock"
    monkeypatch.setattr(wa, "board_lock", lock)

    async def fake_run():
        seen["ran_inside"] = True
        return 0
    monkeypatch.setattr(m, "run", fake_run)
    with pytest.raises(SystemExit):
        m.cli()
    assert seen["owner"] == "foreclosure_scraper.main" and seen["ran_inside"]
    assert seen["max_runtime"] >= 24 * 3600, "a 15 to 57 hour run needs a max runtime that long"


def test_a_failed_board_write_skips_every_downstream_export():
    src = inspect.getsource(m.run)
    abort = src.index("orchestrator.aborted_board_not_written")
    assert "return EXIT_WRITE_FAILED" in src[abort: abort + 400]
    for later in ("foreclosure_sold_pool.json", "write_health_artifact(", "write_listings(", "send_digest("):
        assert src.index(later, abort) > abort, f"{later} must come AFTER the abort"
    # ...and no export appears BEFORE the write attempt
    write = src.index("write_artifact(enriched, summary)")
    for early in ("write_health_artifact(", "write_listings(", "send_digest("):
        assert src.find(early) == -1 or src.find(early) > write, f"{early} runs before the board write"
    assert "checkpoint.clear()" in src[write: write + 400], "the checkpoint is dropped only on success"


def test_a_scoring_failure_refuses_the_write_and_lands_in_the_health_alarms():
    src = inspect.getsource(m.run)
    assert "except ScoreBoardError as exc:" in src
    assert "raise ScoreBoardFailed(" in src
    assert "SCORE_BOARD_FAIL_SOFT" in src
    assert 'checkpoint.save(enriched, "score_failed")' in src
    assert "distress_stack_failed" in src and "price_index_error" in src
    assert "if _scoring_failed:" in src and "return EXIT_SCORE_FAILED" in src


def test_the_docs_directory_is_not_written_before_the_lock_is_taken():
    """cli() must take the lock BEFORE asyncio.run(run()): write_artifact refuses without it,
    and a multi-hour scrape refused at the very end is the worst place to learn that."""
    src = inspect.getsource(m.cli)
    assert src.index("board_lock(") < src.index("asyncio.run(run())")
