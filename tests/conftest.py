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
from foreclosure_scraper import jail_roster_history as _jail_history
from foreclosure_scraper import web_artifact as _web_artifact


@pytest.fixture(autouse=True)
def _reset_arcgis_breaker():
    _arcgis._WALLED_HOSTS.clear()
    _arcgis._HOST_FAILS.clear()
    yield
    _arcgis._WALLED_HOSTS.clear()
    _arcgis._HOST_FAILS.clear()


@pytest.fixture(autouse=True)
def _reset_board_load_stamps():
    """web_artifact._LOAD_STAMPS is a process-wide dict keyed by the RESOLVED
    `<docs>/listings.json` path string, remembering what load_board()/patch_existing_rows()/etc.
    last read there so a later write_artifact() in the SAME process can detect another writer
    having replaced the board underneath it (audit O3) -- correct for production (one process,
    one board) but leaks between tests, because it is keyed by a path STRING, not an inode or a
    per-test identity.

    This is not a hypothetical collision (found 2026-10-03 bisecting
    test_dedupe_key_collision_with_different_scores_is_dropped_not_misapplied, which failed only
    in a full run, never alone): pytest's own `tmp_path` fixture truncates the test's name to 30
    chars before appending a numbered suffix (`_pytest/tmpdir.py:_mk_tmp`), so two tests whose
    names share the same first 30 characters --
    test_dedupe_key_collision_with_identical_scores_is_still_applied_once and
    test_dedupe_key_collision_with_different_scores_is_dropped_not_misapplied both truncate to
    "test_dedupe_key_collision_with" -- request the same numbered-dir prefix. Under this repo's
    own tmp_path_retention_count=1 / tmp_path_retention_policy="failed" (pyproject.toml, commit
    03888576, added the same day to stop pytest's tmp_path from piling up to 57GB), a PASSING
    test's tmp_path dir is rmtree'd immediately at teardown, which frees its numbered suffix for
    the very next test to reuse -- so the two tests above end up with the LITERALLY IDENTICAL
    resolved docs/listings.json path string. Without this fixture, the second test inherits the
    first test's stale _LOAD_STAMPS entry and write_artifact() raises a false-positive
    BoardChangedSinceLoad, even though the two tests share no fixture, no data and no explicit
    state at all."""
    _web_artifact._LOAD_STAMPS.clear()
    yield
    _web_artifact._LOAD_STAMPS.clear()


@pytest.fixture(autouse=True)
def _isolate_jail_roster_history(monkeypatch, tmp_path_factory):
    """enrichment_jail_bookings._load_roster writes every fetch to the
    jail_roster_history sidecar with no opt-out (best-effort, see its own
    docstring). Without this, any test that exercises it — including ones that
    predate this sidecar and never asked for one — would create/append to the
    real data/jail_roster_history.db. Redirect to a throwaway file per test."""
    monkeypatch.setattr(_jail_history, "DB_PATH",
                        tmp_path_factory.mktemp("jail_history") / "jail_roster_history.db")


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
