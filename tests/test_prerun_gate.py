"""scripts/prerun_gate.py (and scripts/run_test_suite.py, scripts/pipeline_wiring.py): the checks
that refuse a run outdated or broken on arrival. Every git check runs against a throwaway repo."""
from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
import time
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "scripts"))


def _load(name: str):
    spec = importlib.util.spec_from_file_location(name, REPO / "scripts" / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


G = _load("prerun_gate")
T = _load("run_test_suite")
W = _load("pipeline_wiring")


def _git(repo: Path, *args) -> str:
    env = {**os.environ, "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@example.org",
           "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@example.org"}
    return subprocess.run(["git", *args], cwd=repo, capture_output=True, text=True, check=True,
                          env=env).stdout.strip()


@pytest.fixture
def repo(tmp_path):
    r = tmp_path / "r"
    (r / "src" / "foreclosure_scraper").mkdir(parents=True)
    (r / "docs" / "handoff" / "verification").mkdir(parents=True)
    (r / "src" / "foreclosure_scraper" / "__init__.py").write_text("")
    (r / "src" / "foreclosure_scraper" / "main.py").write_text("x = 1\n")
    (r / "docs" / "handoff" / "verification" / "tax_lien.json").write_text("{}\n")
    _git(r, "init", "-q", "-b", "main")
    _git(r, "add", "-A")
    _git(r, "commit", "-q", "-m", "one")
    return r


PROFILE = {"ledgers": {"dir": "docs/handoff/verification", "max_age_h": 36},
           "test_results": "data/test_results/latest.json", "code_paths": ["src", "scripts", "tests"]}


# ------------------------------------------------------------------------------------------- git
def test_git_clean_untracked_and_ledger_mid_write(repo):
    assert G.check_git(repo, PROFILE)[0] == G.PASS
    (repo / "notes.txt").write_text("x")
    assert G.check_git(repo, PROFILE)[0] == G.WARN
    (repo / "docs" / "handoff" / "verification" / "tax_lien.json").write_text('{"a": 1}\n')
    st, why = G.check_git(repo, PROFILE)
    assert st == G.FAIL and "sweep is mid-write" in why and "docs/handoff/verification/tax_lien.json" in why


def test_pin_must_be_head(repo):
    first = _git(repo, "rev-parse", "HEAD")
    assert G.check_pin(repo, None)[0] == G.FAIL
    assert G.check_pin(repo, "nope")[0] == G.FAIL
    assert G.check_pin(repo, first)[0] == G.PASS
    (repo / "src" / "foreclosure_scraper" / "main.py").write_text("x = 2\n")
    _git(repo, "commit", "-qam", "fix")
    st, why = G.check_pin(repo, first)
    assert st == G.FAIL and "1 commit(s) the pin lacks" in why


def test_pushed_uses_the_local_remote_ref_only(repo):
    assert G.check_pushed(repo)[0] == G.WARN                   # no origin/main ref at all
    _git(repo, "update-ref", "refs/remotes/origin/main", "HEAD")
    assert G.check_pushed(repo)[0] == G.PASS
    (repo / "src" / "foreclosure_scraper" / "main.py").write_text("x = 3\n")
    _git(repo, "commit", "-qam", "local only")
    st, why = G.check_pushed(repo)
    assert st == G.FAIL and "1 commit(s) ahead" in why


# ----------------------------------------------------------------------------------------- tests
def _results(repo: Path, **kw) -> None:
    p = repo / "data" / "test_results" / "latest.json"
    p.parent.mkdir(parents=True, exist_ok=True)
    doc = {"kind": "full", "green": True, "tree_dirty": False, "passed": 10, "failed": 0, "errors": 0,
           "commit": _git(repo, "rev-parse", "HEAD"), "finished_at": "2026-10-09T00:00:00+00:00"}
    doc.update(kw)
    p.write_text(json.dumps(doc))


def test_tests_must_be_full_green_and_cover_the_code(repo):
    assert G.check_tests(repo, PROFILE)[0] == G.FAIL                       # none recorded
    _results(repo, kind="targeted")
    assert "not the full suite" in G.check_tests(repo, PROFILE)[1]
    _results(repo, green=False, failed=2)
    assert "NOT green" in G.check_tests(repo, PROFILE)[1]
    _results(repo, tree_dirty=True)
    assert "dirty tree" in G.check_tests(repo, PROFILE)[1]
    _results(repo)
    assert G.check_tests(repo, PROFILE)[0] == G.PASS
    (repo / "docs" / "note.md").write_text("docs only")                    # not a code path
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", "docs")
    assert G.check_tests(repo, PROFILE)[0] == G.PASS
    (repo / "src" / "foreclosure_scraper" / "main.py").write_text("x = 9\n")
    _git(repo, "commit", "-qam", "code")
    st, why = G.check_tests(repo, PROFILE)
    assert st == G.FAIL and "src/foreclosure_scraper/main.py" in why


def test_run_test_suite_parses_pytest_summaries():
    out = ("....F.\nFAILED tests/test_a.py::test_x - AssertionError\nERROR tests/test_b.py::test_y\n"
           "= 1 failed, 40 passed, 2 skipped, 1 error, 3 warnings in 9.1s =")
    res = T.parse_summary(out)
    assert (res["passed"], res["failed"], res["errors"], res["skipped"]) == (40, 1, 1, 2)
    assert res["failed_ids"] == ["tests/test_a.py::test_x", "tests/test_b.py::test_y"]
    assert T.parse_summary("10 passed in 1.0s")["passed"] == 10
    chunks = T.chunked([f"t{i}" for i in range(7)], 3)
    assert sorted(sum(chunks, [])) == sorted(f"t{i}" for i in range(7)) and len(chunks) == 3


# --------------------------------------------------------------------------------------- ledgers
def test_ledgers(repo):
    assert G.check_ledgers(repo, PROFILE, sweep_running=lambda: False)[0] == G.PASS
    assert "sweep is running" in G.check_ledgers(repo, PROFILE, sweep_running=lambda: True)[1]
    (repo / "docs" / "handoff" / "verification" / "tax_lien.json").write_text('{"b": 2}\n')
    assert G.check_ledgers(repo, PROFILE, sweep_running=lambda: False)[0] == G.FAIL
    old = {**PROFILE, "ledgers": {"dir": "docs/handoff/verification", "max_age_h": -1}}
    _git(repo, "commit", "-qam", "ledger")
    assert "h old" in G.check_ledgers(repo, old, sweep_running=lambda: False)[1]


# ---------------------------------------------------------------------------------------- memory
def test_memory_projection_uses_the_worst_measured_cost():
    mem = {"kill_mb": 25600, "warn_fraction": 0.9, "growth_factor": 1.15,
           "calibration": [{"run": "a", "rows_out": 350013, "peak_mb": 19731},
                           {"run": "b", "rows_out": 350013, "peak_mb": 17021}]}
    p = G.memory_projection(350013, mem)
    assert p["basis"] == "a" and p["projected_rows"] == 402514
    assert p["ok"] and p["projected_peak_mb"] == round(19731 / 350013 * 402514)
    assert p["max_rows_before_kill"] == int(25600 / (19731 / 350013))
    assert not G.memory_projection(500_000, mem)["ok"]           # ~28 GB: killed
    assert G.memory_projection(380_000, mem)["warn"]              # over 90% of the line


def test_memory_check_reads_the_manifest_count(repo):
    (repo / "docs" / "board.manifest.json").write_text(json.dumps({"count": 1000}))
    mem = {"memory": {"kill_mb": 1000, "growth_factor": 1.0,
                      "calibration": [{"run": "x", "rows_out": 1000, "peak_mb": 2000}]}}
    st, why = G.check_memory(repo, mem)
    assert st == G.FAIL and "1,000 rows" in why


# ------------------------------------------------------------------------- static: wiring, loads
def _tree(repo: Path, files: dict[str, str]) -> None:
    for rel, body in files.items():
        p = repo / "src" / "foreclosure_scraper" / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(body)


CARRYOVER_LIKE = '''
import json
from pathlib import Path
def load_prior_listings(docs):
    listings_path = Path(docs) / "listings.json"
    return json.loads(listings_path.read_text())
'''


def test_board_loads_catch_the_carryover_pattern(repo):
    _tree(repo, {"main.py": "from .carryover import load_prior_listings\n",
                 "carryover.py": CARRYOVER_LIKE,
                 "small.py": "import json\ndef f(p):\n    return json.loads(p.read_text())\n"})
    hits = W.whole_file_json_loads(repo)
    assert [h["site"] for h in hits] == ["carryover:load_prior_listings"]
    st, why = G.check_board_loads(repo, {})
    assert st == G.FAIL and "carryover:load_prior_listings" in why
    assert G.check_board_loads(repo, {"board_load_allowlist": {"carryover:load_prior_listings": "x"}})[0] == G.PASS


def test_streamed_reads_are_not_whole_file_loads(repo):
    _tree(repo, {"main.py": "from . import carry\n",
                 "carry.py": ("import json\nfrom .board_parts import iter_plain_rows\n"
                              "def f(docs):\n    p = docs / 'listings.json'\n"
                              "    return [json.loads(t) for t in iter_plain_rows(p, want_text=True)]\n")})
    assert W.whole_file_json_loads(repo) == []


def test_unwired_modules_need_a_reason(repo):
    _tree(repo, {"main.py": "from .enrichment_a import enrich_a\n",
                 "enrichment_a.py": "def enrich_a(x): return x\n",
                 "enrichment_b.py": "def enrich_b(x): return x\n",
                 "helpers.py": "def enrich_c(x): return x\n"})
    (repo / "scripts").mkdir(exist_ok=True)
    (repo / "scripts" / "fill_b.py").write_text("from foreclosure_scraper.enrichment_b import enrich_b\n")
    rows = {r["module"]: r for r in W.unwired(repo)}
    assert set(rows) == {"enrichment_b", "helpers"}
    assert rows["enrichment_b"]["status"] == "script_only" and rows["helpers"]["status"] == "dead"
    st, why = G.check_unwired(repo, {})
    assert st == G.FAIL and "enrichment_b" in why
    allow = {"unwired_allowlist": {"enrichment_b": "r", "helpers": "r", "enrichment_gone": "r"}}
    st, why = G.check_unwired(repo, allow)
    assert st == G.WARN and "enrichment_gone" in why


def test_dynamic_package_loads_count_as_wired(repo):
    _tree(repo, {"main.py": "from .enrichment_rod import go\n",
                 "enrichment_rod.py": ("import importlib\n"
                                       "def go(n): return importlib.import_module(f'foreclosure_scraper.rod.{n}')\n"),
                 "rod/__init__.py": "", "rod/enrichment_rod_adapter.py": "def enrich(): pass\n"})
    assert W.unwired(repo) == []


# ----------------------------------------------------------------------------------------- flags
VM_LIB = '''vm_load_env() {
  export FORECLOSURE_ROLE=vm
  export FORECLOSURE_ROD_CHAIN="${FORECLOSURE_ROD_CHAIN:-1}"
  export FORECLOSURE_NC_HARRIS_ROD="${FORECLOSURE_NC_HARRIS_ROD:-0}"
  export EMAIL_RECIPIENTS="${EMAIL_RECIPIENTS:-a@example.org}"
}
'''


def test_flags_match_the_profile(repo):
    (repo / "deploy" / "oracle").mkdir(parents=True)
    (repo / "deploy" / "oracle" / "vm_lib.sh").write_text(VM_LIB)
    prof = {"profile": "p", "flags": {"FORECLOSURE_ROLE": "vm", "FORECLOSURE_ROD_CHAIN": "1",
                                      "FORECLOSURE_NC_HARRIS_ROD": "0"},
            "must_not_set": {"GRANDFATHER_CARRIED": {"values": ["1"], "why": "x"},
                             "ENRICH_PHASE_MAX_SECONDS": {"values": ["*"], "why": "y"}}}
    assert G.check_flags(repo, prof, env={})[0] == G.PASS
    st, why = G.check_flags(repo, prof, env={"FORECLOSURE_NC_HARRIS_ROD": "1"})
    assert st == G.WARN and "overrides" in why
    assert "GRANDFATHER_CARRIED=1" in G.check_flags(repo, prof, env={"GRANDFATHER_CARRIED": "1"})[1]
    assert G.check_flags(repo, prof, env={"ENRICH_PHASE_MAX_SECONDS": "60"})[0] == G.FAIL
    drift = {**prof, "flags": {**prof["flags"], "FORECLOSURE_NC_HARRIS_ROD": "1"}}
    st, why = G.check_flags(repo, drift, env={})
    assert st == G.FAIL and "FORECLOSURE_NC_HARRIS_ROD: vm_lib 0 != profile 1" in why


def test_the_real_profile_matches_vm_lib_and_the_real_code():
    """The committed profile is the one the next run is held to: it must agree with today's code."""
    prof = G.load_profile()
    assert G.check_flags(REPO, prof, env={})[0] == G.PASS
    assert G.check_board_loads(REPO, prof)[0] == G.PASS
    assert G.check_unwired(REPO, prof)[0] in (G.PASS, G.WARN)


def test_exit_codes():
    assert G.exit_code([{"status": G.PASS}, {"status": G.WARN}]) == 0
    assert G.exit_code([{"status": G.PASS}, {"status": G.SKIP}]) == 2
    assert G.exit_code([{"status": G.SKIP}, {"status": G.FAIL}]) == 1


def test_a_crashing_check_is_a_failed_check(repo, monkeypatch):
    monkeypatch.setattr(G, "check_handoff", lambda *a: 1 / 0)
    res = G.run_gate(repo, PROFILE, pin=None, checkpoint=None,
                     skip=set(G.CHECK_ORDER) - {"handoff"})
    st = {r["check"]: r["status"] for r in res}
    assert st["handoff"] == G.FAIL and G.exit_code(res) == 1


def test_frozen_keys_known_in_the_real_profile():
    prof = G.load_profile()
    assert G.check_frozen_keys(REPO, prof)[0] in (G.PASS, G.WARN)
    st, why = G.check_frozen_keys(REPO, {**prof, "frozen_keys_known": []})
    assert st == G.FAIL and f"{len(prof['frozen_keys_known'])} published key(s)" in why
    st, why = G.check_frozen_keys(REPO, {**prof, "frozen_keys_known": [k for k in prof["frozen_keys_known"]
                                                                       if k != "flood_zone"]})
    assert st == G.FAIL and "flood_zone <- enrichment_flood_zone" in why


def test_raw_key_producers_sees_wired_and_unwired_writers(repo):
    _tree(repo, {"main.py": "from .enrichment_a import enrich_a\n",
                 "enrichment_a.py": "def enrich_a(li):\n    li.raw['alpha'] = 1\n",
                 "enrichment_b.py": "def enrich_b(li):\n    li.raw.setdefault('beta', {})\n    li.raw['alpha'] == 2\n"})
    prod = W.raw_key_producers(["alpha", "beta", "gamma"], repo)
    assert prod["alpha"] == {"writers": ["enrichment_a"], "in_run": ["enrichment_a"]}   # == is not a write
    assert prod["beta"] == {"writers": ["enrichment_b"], "in_run": []}
    assert prod["gamma"] == {"writers": [], "in_run": []}
