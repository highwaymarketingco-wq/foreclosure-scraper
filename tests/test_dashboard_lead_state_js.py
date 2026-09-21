"""Runs tests/js/*.test.mjs (node's built-in test runner) under pytest.

  lead_state.test.mjs  the lead-lifecycle logic in docs/dashboard.js (audit F2,
                       F3, F13, F15, F19 in docs/audit_signal_logic_2026-09-21.md)
  io_guard.test.mjs    login-page detection for a private host, and CRM
                       export/import merging

They are JavaScript, so their tests are too. This file only makes them part of
the suite; it skips, rather than fails, on a machine with no node. The JS tests
slice their code out of docs/dashboard.js, so they test what ships.
"""
import os
import shutil
import subprocess
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
JS_TESTS = sorted((REPO / "tests" / "js").glob("*.test.mjs"))


@pytest.mark.skipif(shutil.which("node") is None, reason="node is not installed")
def test_dashboard_js_logic():
    assert JS_TESTS, "tests/js has no *.test.mjs files"
    # Pin a timezone: the clock code compares LOCAL calendar days, and the JS test
    # builds its dates in local time, so it must pass anywhere; run it in a zone
    # far from UTC to prove it.
    env = {**os.environ, "TZ": "Pacific/Auckland"}
    proc = subprocess.run(
        ["node", "--test", *map(str, JS_TESTS)],
        cwd=REPO, env=env, capture_output=True, text=True, timeout=120,
    )
    assert proc.returncode == 0, proc.stdout[-4000:] + proc.stderr[-2000:]
