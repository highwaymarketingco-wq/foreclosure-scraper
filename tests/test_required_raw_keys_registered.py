"""Every raw key a board-fix script declares it will stamp must survive write_artifact.

`web_artifact._slim_raw` keeps only the keys named in RAW_KEEP and drops the rest with no error
and no log line (see tests/test_raw_keep_covers_enrichers.py for the enrichers). The scripts under
scripts/ that fix the board declare what they write in a module-level `REQUIRED_RAW_KEYS` and
refuse to run when a key is unregistered (scripts/_dq_common.assert_raw_keep), so a missing entry
is a blocker at apply time. This is the same check at test time, which is where a new script's
author will see it first.

The scan is a source scan (ast), not an import: importing these scripts must not have side effects.
Names are resolved against the module's own top-level constants, and `*NAME` unpacks a
module-level tuple or list of strings.
"""
from __future__ import annotations

import ast
from pathlib import Path

import pytest

from foreclosure_scraper.web_artifact import RAW_KEEP, _slim_raw

SCRIPTS = Path(__file__).resolve().parent.parent / "scripts"


def _consts(tree: ast.Module) -> dict:
    out: dict = {}
    for n in tree.body:
        if isinstance(n, ast.Assign) and len(n.targets) == 1 and isinstance(n.targets[0], ast.Name):
            v = n.value
            if isinstance(v, ast.Constant) and isinstance(v.value, str):
                out[n.targets[0].id] = v.value
            elif isinstance(v, (ast.Tuple, ast.List)) and all(
                    isinstance(e, ast.Constant) and isinstance(e.value, str) for e in v.elts):
                out[n.targets[0].id] = [e.value for e in v.elts]
    return out


def _required(path: Path) -> list:
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"))
    except (SyntaxError, UnicodeDecodeError):
        return []
    consts = _consts(tree)
    keys: list = []
    for n in tree.body:
        if not (isinstance(n, ast.Assign) and any(isinstance(t, ast.Name) and t.id == "REQUIRED_RAW_KEYS"
                                                  for t in n.targets)):
            continue
        for e in getattr(n.value, "elts", []):
            if isinstance(e, ast.Constant) and isinstance(e.value, str):
                keys.append(e.value)
            elif isinstance(e, ast.Name) and isinstance(consts.get(e.id), str):
                keys.append(consts[e.id])
            elif isinstance(e, ast.Starred) and isinstance(e.value, ast.Name) \
                    and isinstance(consts.get(e.value.id), list):
                keys.extend(consts[e.value.id])
            else:
                pytest.fail(f"{path.name}: cannot resolve a REQUIRED_RAW_KEYS element "
                            f"({ast.dump(e)[:80]}); use a string literal or a module-level constant")
    return keys


def _scripts_with_required_keys() -> list:
    return sorted(p for p in SCRIPTS.glob("*.py") if "REQUIRED_RAW_KEYS" in p.read_text(encoding="utf-8", errors="ignore"))


def test_the_scan_finds_the_fix_scripts():
    names = {p.name for p in _scripts_with_required_keys()}
    assert {"backfill_missing_county.py", "quarantine_flip_leaks.py",
            "undo_resolver_middle_conflicts.py"} <= names


@pytest.mark.parametrize("script", _scripts_with_required_keys(), ids=lambda p: p.name)
def test_every_required_raw_key_is_in_raw_keep(script):
    keys = _required(script)
    assert keys, f"{script.name} declares REQUIRED_RAW_KEYS but none could be read"
    missing = [k for k in keys if k not in RAW_KEEP]
    assert not missing, (f"{script.name} stamps raw key(s) {missing} that are not in "
                         f"web_artifact.RAW_KEEP, so write_artifact drops them silently")


def test_the_three_new_blocks_survive_the_publish_slim():
    raw = {"county_backfill": {"county": "Gaston", "evidence": "zip", "basis": "28052"},
           "scope": "flip_outside_footprint",
           "resolver_conflict_undone": {"action": "undone", "query_name": "A B", "matched_owner": "A C"},
           "not_registered_anywhere": {"x": 1}}
    kept = _slim_raw(raw)
    assert kept["county_backfill"] == raw["county_backfill"]
    assert kept["scope"] == "flip_outside_footprint"
    assert kept["resolver_conflict_undone"] == raw["resolver_conflict_undone"]
    assert "not_registered_anywhere" not in kept
