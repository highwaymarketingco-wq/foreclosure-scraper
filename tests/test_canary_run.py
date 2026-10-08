"""scripts/canary_run.py: the scratch workspace, the env, and the verdict (made-up inputs only;
the pipeline itself is not run here)."""
from __future__ import annotations

import gzip
import importlib.util
import json
import os
import subprocess
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
_SPEC = importlib.util.spec_from_file_location("canary_run", REPO / "scripts" / "canary_run.py")
C = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(C)


def _git(repo, *args):
    env = {**os.environ, "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@example.org",
           "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@example.org"}
    subprocess.run(["git", *args], cwd=repo, check=True, capture_output=True, env=env)


def _fake_repo(tmp_path):
    r = tmp_path / "real"
    for rel, body in {"src/foreclosure_scraper/__init__.py": "", "scripts/x.py": "", "pyproject.toml": "",
                      "docs/handoff/verification/tax_lien.json": "{}", "docs/run_meta.json": "{}",
                      "docs/handoff/stealth_leads.json": "[]", "docs/listings_part_000.json.gz": "x",
                      "docs/board.manifest.json": "{}", "docs/parcel_photos/a.jpg": "x"}.items():
        p = r / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(body)
    _git(r, "init", "-q", "-b", "main")
    _git(r, "add", "-A")
    _git(r, "commit", "-qm", "x")
    (r / "src" / "foreclosure_scraper" / "__init__.py").write_text("UNCOMMITTED = 1\n")   # never exported
    for d in ("parcel_cache", "checkpoint", "heirs", "footprints"):
        (r / "data" / d).mkdir(parents=True)
    (r / ".secrets").mkdir()
    return r


def test_export_is_the_committed_code_without_the_board(tmp_path):
    real = _fake_repo(tmp_path)
    dest = tmp_path / "ws" / "repo"
    n = C.export_code(dest, real)
    assert n >= 4
    assert (dest / "docs" / "handoff" / "verification" / "tax_lien.json").exists()
    assert (dest / "docs" / "run_meta.json").exists()
    for gone in ("docs/listings_part_000.json.gz", "docs/board.manifest.json", "docs/parcel_photos",
                 "docs/handoff/stealth_leads.json"):
        assert not (dest / gone).exists(), gone
    assert (dest / "src" / "foreclosure_scraper" / "__init__.py").read_text() == ""


def test_data_is_shared_except_what_the_canary_writes(tmp_path):
    real = _fake_repo(tmp_path)
    dest = tmp_path / "ws" / "repo"
    linked = C.link_data(dest, real)
    assert sorted(linked) == ["footprints", "parcel_cache"]
    assert (dest / "data" / "parcel_cache").is_symlink()
    assert not (dest / "data" / "checkpoint").exists() and not (dest / "data" / "heirs").exists()
    assert (dest / ".secrets").is_symlink()


def test_prior_board_shares_and_roundtrip(tmp_path):
    from foreclosure_scraper.board_parts import iter_gz_rows
    rows = [{"state": "NC", "county": "Polk", "raw": {"equity": {"v": 1}, "calc": {}}},
            {"state": "SC", "county": "Union", "raw": {"equity": {"v": 2}}},
            {"state": "NC", "county": "Union", "raw": {}},        # Union NC is not a canary county
            {"state": "SC", "county": "greenwood", "raw": {}}]
    kept = [r for r in rows if C.in_canary(r)]
    assert len(kept) == 3
    shares, n = C.key_shares(kept, ["equity", "calc", "nope"])
    assert n == 3 and shares == {"equity": round(2 / 3, 4)}        # an empty {} does not count
    p = tmp_path / "listings.json.gz"
    assert C.write_prior(kept, p) == 3
    assert list(iter_gz_rows(p)) == kept


def test_env_runs_the_profile_scoped_and_never_publishes(tmp_path):
    base = {"FORECLOSURE_ROLE": "vm", "GRANDFATHER_CARRIED": "1", "ENRICH_PHASE_MAX_SECONDS": "5"}
    env = C.canary_env(tmp_path, base)
    assert env["FORECLOSURE_ROLE"] == "vm"
    assert env["FULLRUN_STOP_BEFORE_PUBLISH"] == "1"
    assert env["FORECLOSURE_ONLY_SOURCES"] == ",".join(C.SOURCE_SUBSTRINGS)
    assert env["FORECLOSURE_CHECKPOINT_DIR"] == str(tmp_path / "repo" / "data" / "checkpoint")
    assert env["PYTHONPATH"].split(os.pathsep)[0] == str(tmp_path / "repo" / "src")
    assert "GRANDFATHER_CARRIED" not in env and "ENRICH_PHASE_MAX_SECONDS" not in env
    assert "CASE_DETAIL_OFF" not in env
    assert C.canary_env(tmp_path, base, no_stealth=True)["CASE_DETAIL_OFF"] == "1"


def _ok_inputs(**kw):
    d = dict(rc=0, manifest={"phase": "pre_publish", "count": 3300},
             failures={"failed": {}, "time_capped": {"comps": 1}},
             expectations={"key_share": {"equity": 0.6, "calc": 0.99, "rare": 0.01},
                           "stripped_keys": ["calc", "equity"], "frozen_keys": ["flood_zone"]},
             fresh_shares={"equity": 0.3, "calc": 1.0}, fresh_n=40,
             stats={"geocode": {}, "equity": {}}, stats_baseline=["geocode", "equity"], suite_rc=0)
    d.update(kw)
    return d


def test_evaluate_passes_a_good_run():
    res = C.evaluate(**_ok_inputs())
    assert res["ok"] and res["time_capped"] == {"comps": 1}


def test_evaluate_names_each_failure():
    bad = {
        "exit": _ok_inputs(rc=137),
        "checkpoint": _ok_inputs(manifest={"phase": "dot_ocr"}),
        "no-swallowed-failures": _ok_inputs(failures={"failed": {"geocode.failed": 2}}),
        "raw-keep-produced": _ok_inputs(fresh_shares={"calc": 1.0}),
        "enrichment-stats": _ok_inputs(stats={"geocode": {}}),
        "audit-suite": _ok_inputs(suite_rc=1),
    }
    for name, inputs in bad.items():
        res = C.evaluate(**inputs)
        failed = [c["check"] for c in res["checks"] if not c["ok"]]
        assert failed == [name], (name, failed)
    res = C.evaluate(**_ok_inputs(fresh_shares={"calc": 1.0}))
    det = next(c for c in res["checks"] if c["check"] == "raw-keep-produced")["detail"]
    assert "not produced" in det and "equity 0.00/0.60" in det and "frozen" in det
    assert not C.evaluate(**_ok_inputs(fresh_n=0))["ok"]
    # back, but on far fewer rows than the run that built the prior board
    assert not C.evaluate(**_ok_inputs(fresh_shares={"equity": 0.1, "calc": 1.0}))["ok"]


def test_fresh_rows_are_the_ones_first_seen_after_prepare():
    rows = [{"first_seen": "2026-10-09T01:00:00"}, {"first_seen": "2026-10-01T00:00:00"}, {}]
    assert len(list(C.fresh_rows(rows, "2026-10-09T00:00:00"))) == 1
