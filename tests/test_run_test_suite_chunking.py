"""run_test_suite.chunked() pulls ISOLATE_ALONE files into their own solo chunk, placed first.

2026-10-17: test_sigint_kills_a_hung_sync_census_call_within_a_few_seconds (in
tests/test_geocode_backfill_hard_timeout.py) flaked 3 times on the VM's full 6-chunk run at
margins 5s/15s/30s -- never standalone, never even when its own ~155-file round-robin chunk ran
alone. The cause is cumulative OS scheduling pressure from ~300 files run in EARLIER chunks (each
its own subprocess), not a correctness bug in the SIGINT-handling code itself. Isolating that one
file into its own chunk, run before any other chunk builds up pressure, removes the flake's actual
cause without loosening the test's own assertion.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

from run_test_suite import ISOLATE_ALONE, chunked  # noqa: E402


def test_an_isolated_file_gets_its_own_solo_chunk_placed_first():
    files = sorted(["tests/test_a.py", "tests/test_b.py",
                     "tests/test_geocode_backfill_hard_timeout.py",
                     "tests/test_c.py", "tests/test_d.py", "tests/test_e.py"])
    chunks = chunked(files, 3)
    assert chunks[0] == ["tests/test_geocode_backfill_hard_timeout.py"]
    assert all("tests/test_geocode_backfill_hard_timeout.py" not in c for c in chunks[1:]), (
        "the isolated file must not also land in a shared chunk")


def test_isolation_never_drops_or_duplicates_a_file():
    files = sorted(["tests/test_a.py", "tests/test_b.py",
                     "tests/test_geocode_backfill_hard_timeout.py",
                     "tests/test_c.py", "tests/test_d.py", "tests/test_e.py", "tests/test_f.py"])
    chunks = chunked(files, 3)
    flat = sorted(f for c in chunks for f in c)
    assert flat == files


def test_with_no_isolated_file_present_behaves_like_plain_round_robin():
    files = sorted(["tests/test_a.py", "tests/test_b.py", "tests/test_c.py", "tests/test_d.py"])
    chunks = chunked(files, 2)
    assert chunks == [files[0::2], files[1::2]]


def test_the_known_flaky_sigint_file_is_on_the_isolate_list():
    assert "tests/test_geocode_backfill_hard_timeout.py" in ISOLATE_ALONE
