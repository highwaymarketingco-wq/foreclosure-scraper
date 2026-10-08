"""scripts/audit_suite.py: one streaming pass of a board through every scripts/audit_checks module.

The runner is what the pre-run gate, the canary and a human run after every board, so it must
never let one broken check hide the others, and must compute `ok` itself (BRIEF.md interface)."""
from __future__ import annotations

import gzip
import importlib.util
import json
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
_SPEC = importlib.util.spec_from_file_location("audit_suite", REPO / "scripts" / "audit_suite.py")
S = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(S)

GOOD = '''
class C:
    name = "count-odd"
    def __init__(self): self.n = 0; self.bad = 0
    def feed(self, row):
        self.n += 1
        if row.get("v", 0) % 2: self.bad += 1
    def finish(self):
        return {"name": self.name, "checked": self.n, "violations": self.bad,
                "max_violations": 1, "ok": True, "detail": "odd values"}
def make_checks(): return [C()]
'''
RAISES_IN_FEED = '''
class C:
    name = "feeds-badly"
    def feed(self, row): raise ValueError("boom")
    def finish(self): return {"name": self.name, "checked": 0, "violations": 0, "max_violations": 0, "ok": True, "detail": ""}
def make_checks(): return [C()]
'''
NO_IMPORT = "import this_module_does_not_exist_anywhere\n"
NO_MAKE = "X = 1\n"


def _dir(tmp_path: Path, files: dict[str, str]) -> Path:
    d = tmp_path / "checks"
    d.mkdir()
    for name, body in files.items():
        (d / name).write_text(body)
    return d


def test_one_pass_feeds_every_check_and_recomputes_ok(tmp_path):
    d = _dir(tmp_path, {"a_good.py": GOOD, "b_good.py": GOOD.replace("count-odd", "count-odd-2")})
    checks = S.discover(d)
    rows = ({"v": i} for i in range(5))           # a generator: consumed exactly once
    results, n = S.run_suite(rows, checks)
    assert n == 5
    assert [r["name"] for r in results] == ["count-odd", "count-odd-2"]
    for r in results:
        assert (r["checked"], r["violations"], r["max_violations"]) == (5, 2, 1)
        assert r["ok"] is False                   # the check said ok=True; 2 > 1 decides
        assert "recomputed" in r["detail"]


def test_a_broken_check_never_hides_the_others(tmp_path):
    d = _dir(tmp_path, {"a.py": NO_IMPORT, "b.py": NO_MAKE, "c.py": RAISES_IN_FEED, "d.py": GOOD,
                        "_helper.py": NO_IMPORT})
    checks = S.discover(d)
    results, n = S.run_suite(iter([{"v": 2}, {"v": 4}]), checks)
    by = {r["name"]: r for r in results}
    assert by["a:import"]["ok"] is False and "import failed" in by["a:import"]["detail"]
    assert by["b:make_checks"]["ok"] is False
    assert by["feeds-badly"]["ok"] is False and "feed() raised on 2 rows" in by["feeds-badly"]["detail"]
    assert by["count-odd"]["ok"] is True and by["count-odd"]["checked"] == 2
    assert not any(k.startswith("_helper") for k in by)       # underscore modules are helpers


def test_finish_with_a_bad_shape_is_not_ok(tmp_path):
    body = '''
class C:
    name = "bad-shape"
    def feed(self, row): pass
    def finish(self): return {"name": self.name, "checked": "many", "violations": 0, "max_violations": 0}
def make_checks(): return [C()]
'''
    results, _ = S.run_suite(iter([{}]), S.discover(_dir(tmp_path, {"x.py": body})))
    assert results[0]["ok"] is False and "not an int" in results[0]["detail"]


def test_result_file_holds_counts_only(tmp_path):
    d = _dir(tmp_path, {"a.py": GOOD})
    board = tmp_path / "listings.json.gz"
    with gzip.open(board, "wt") as fh:
        json.dump([{"v": 1, "raw": {}}, {"v": 2, "raw": {}}], fh)
    out = tmp_path / "suite_result.json"
    rc = S.main(["--board", str(board), "--checks-dir", str(d), "--out", str(out)])
    assert rc == 0
    doc = json.loads(out.read_text())
    assert doc["rows"] == 2 and doc["ok"] is True
    assert doc["checks"] == [{"name": "count-odd", "module": "a", "checked": 2, "violations": 1,
                              "max_violations": 1, "ok": True}]
    assert "detail" not in json.dumps(doc["checks"])          # details may hold parcel ids


def test_exit_code_is_nonzero_when_any_check_fails(tmp_path):
    d = _dir(tmp_path, {"a.py": GOOD})
    board = tmp_path / "listings.json.gz"
    with gzip.open(board, "wt") as fh:
        json.dump([{"v": 1}, {"v": 3}, {"v": 5}], fh)
    assert S.main(["--board", str(board), "--checks-dir", str(d), "--no-out"]) == 1


def test_checkpoint_rows_are_in_the_published_shape(tmp_path):
    """A checkpoint row goes through Listing + web_artifact._to_dict, like board_selfcheck."""
    from foreclosure_scraper.models import Listing
    li = Listing(source="counties_nc.x", source_url="https://example.org/1", county="Polk", state="NC",
                 raw={"distress_stack": {"tier": "COLD"}, "not_a_published_key_zz": 1})
    ck = tmp_path / "ck"
    ck.mkdir()
    with gzip.open(ck / "board.json.gz", "wt") as fh:
        json.dump([li.model_dump(mode="json"), {"source": None, "bogus": True, "raw": 5}], fh)
    bad: list = []
    rows = list(S.checkpoint_rows(ck, bad))
    assert len(rows) == 1 and len(bad) == 1
    assert "not_a_published_key_zz" not in (rows[0].get("raw") or {})   # RAW_KEEP trim applied
    assert rows[0]["raw"]["distress_stack"]["tier"] == "COLD"


def test_the_real_checks_dir_loads():
    checks = S.discover()
    names = [getattr(c, "name", "") for _, c, _ in checks]
    assert "pipeline-row-scored" in names
    assert not [n for n in names if n.endswith((":import", ":make_checks"))], names
