"""Regression guards for orchestrator-level bugs unit tests don't exercise.

Pass 3 caught a catastrophic NameError/UnboundLocalError: `Path` was used at
function scope in run() while `from pathlib import Path` appeared LATER inside the
same function, making `Path` a function-local that was unbound earlier — crashing
EVERY run before the dashboard/Sheets/email (suppressing all failure alarms). No
unit test ran the full run(), so 933 green tests missed it. These guards catch the
whole class cheaply.
"""
from __future__ import annotations

import ast
import inspect
import pathlib

import foreclosure_scraper.main as m


def test_path_is_module_level():
    assert m.Path is pathlib.Path


def test_run_has_no_function_local_pathlib_import():
    """A function-local `from pathlib import Path` re-shadows the module-level one
    and reintroduces the UnboundLocalError. Forbid it in run()."""
    tree = ast.parse(inspect.getsource(m.run))
    offenders = [
        n for n in ast.walk(tree)
        if isinstance(n, ast.ImportFrom) and n.module == "pathlib"
        and any(a.name == "Path" and a.asname is None for a in n.names)
    ]
    assert not offenders, "run() re-imports pathlib.Path locally — shadows module-level Path"
