"""Shared pytest fixtures.

The ArcGIS circuit-breaker (enrichment_arcgis) keeps process-wide state in
``_WALLED_HOSTS`` / ``_HOST_FAILS`` — correct in production (one process = one
run), but it leaks BETWEEN tests: a test that trips a host (e.g. nconemap.gov)
would leave it walled and silently short-circuit a later test's _arc_query. This
autouse fixture clears that state before every test so each starts with a clean
breaker.
"""
import pytest

from foreclosure_scraper import enrichment_arcgis as _arcgis


@pytest.fixture(autouse=True)
def _reset_arcgis_breaker():
    _arcgis._WALLED_HOSTS.clear()
    _arcgis._HOST_FAILS.clear()
    yield
    _arcgis._WALLED_HOSTS.clear()
    _arcgis._HOST_FAILS.clear()


@pytest.fixture(autouse=True)
def _isolate_board_ops(monkeypatch, tmp_path_factory):
    """Keep every test off the real machine and the real repo logs (audit O3/O9).

    * BOARD_MEM_GATE=off: the memory gate reads swap and free RAM of the machine the
      tests happen to run on (7 GB of swap used at audit time), so a test that takes the
      board lock would otherwise depend on it. Gate tests set it explicitly.
    * JOB_EVENTS_FILE: lock breaks, skips and gate notes go to a scratch file, never to
      the real logs/job_events.jsonl.
    * The two lock-enforcement switches are cleared so a developer shell that exports
      BOARD_LOCK_BYPASS or a held lock cannot change what a test asserts.
    """
    monkeypatch.setenv("BOARD_MEM_GATE", "off")
    monkeypatch.setenv("JOB_EVENTS_FILE",
                       str(tmp_path_factory.mktemp("job_events") / "job_events.jsonl"))
    for var in ("BOARD_LOCK_BYPASS", "BOARD_MANIFEST_SKIP", "BOARD_LOAD_ALLOW_DROPS",
                "BOARD_GATE_FAKE_SWAP_MB", "BOARD_GATE_FAKE_FREE_MB",
                "BOARD_PARTS_ALLOW_UNLISTED", "BOARD_PART_MAX_BYTES"):
        monkeypatch.delenv(var, raising=False)
    yield
