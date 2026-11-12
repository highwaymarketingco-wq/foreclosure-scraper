"""scripts/repo_size_check.py and the prerun gate's repo-size, ci and handoff checks.

Two size walls were hit for real in October 2026: the Mac's stealth hand-off file reached 93.8 MiB
(the pre-commit gate refuses 95 MiB, GitHub 100 MiB), and the Pages site reached 972 MB (pages.yml
stops a deploy at 950 MB). The check fails at 90 MiB per tracked file and 900 MB of deployed site.
Every repository here is a throwaway one with made-up files; limits are scaled down so the files
stay a few KiB."""
from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "scripts"))


def _load(name: str):
    spec = importlib.util.spec_from_file_location(name, REPO / "scripts" / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


S = _load("repo_size_check")
G = _load("prerun_gate")
KIB = 1024


def _git(repo: Path, *args) -> str:
    env = {**os.environ, "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@example.org",
           "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@example.org"}
    return subprocess.run(["git", "-c", "core.hooksPath=/dev/null", *args], cwd=repo,
                          capture_output=True, text=True, check=True, env=env).stdout.strip()


CONFIG = """title: x
exclude:
  - README.md
  - handoff/
include:
  - listings_part_
"""


@pytest.fixture
def repo(tmp_path):
    r = tmp_path / "r"
    files = {
        "docs/_config.yml": CONFIG.encode(),
        "docs/index.html": b"<html></html>",
        "docs/listings_part_000.json.gz": b"p" * (30 * KIB),        # published
        "docs/handoff/stealth_leads/a.one.000.jsonl": b"h" * (50 * KIB),   # excluded: handoff/
        "docs/README.md": b"r" * (40 * KIB),                         # excluded by name
        "docs/_drafts/x.md": b"d" * (40 * KIB),                      # Jekyll special: never published
        "data.bin": b"b" * (20 * KIB),                               # outside docs/: not the site
    }
    for rel, body in files.items():
        p = r / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(body)
    _git(r, "init", "-q", "-b", "main")
    _git(r, "add", "-A")
    _git(r, "commit", "-q", "-m", "one")
    return r


def _limits(**kw):
    base = dict(max_file_mib=60 * KIB / S.MIB, warn_file_mib=25 * KIB / S.MIB,
                max_pages_mb=0.1, warn_pages_mb=0.05)
    base.update(kw)
    return base


def test_the_pages_size_is_tracked_docs_minus_the_config_excludes(repo):
    r = S.measure(repo, **_limits())
    # published: _config.yml is special (leading _), so index.html + the part only
    assert r["pages_files"] == 2
    assert r["pages_mb"] == round((30 * KIB + len(b"<html></html>")) / S.MB, 1)
    assert {t["entry"] for t in r["pages_top"]} == {"listings_part_000.json.gz", "index.html"}


def test_a_tracked_file_over_the_limit_fails_and_is_named(repo):
    r = S.measure(repo, **_limits(max_file_mib=45 * KIB / S.MIB))
    assert not r["ok"]
    assert r["problems"] == [f"docs/handoff/stealth_leads/a.one.000.jsonl is "
                             f"{50 * KIB / S.MIB:.1f} MiB (limit {45 * KIB / S.MIB:.0f} MiB)"]
    assert [f["path"] for f in r["files_over_warn"]] == [
        "docs/handoff/stealth_leads/a.one.000.jsonl", "docs/README.md", "docs/_drafts/x.md",
        "docs/listings_part_000.json.gz"]


def test_under_every_limit_passes_with_warnings_for_the_big_files(repo):
    r = S.measure(repo, **_limits())
    assert r["ok"] and r["problems"] == []
    assert any("a.one.000.jsonl" in w for w in r["warnings"])


def test_untracked_and_uncommitted_files_do_not_count(repo):
    (repo / "docs" / "huge.bin").write_bytes(b"x" * (200 * KIB))
    assert S.measure(repo, **_limits())["ok"]


def test_the_pages_limit_fails_on_deployed_bytes_only(repo):
    r = S.measure(repo, **_limits(max_pages_mb=0.02))
    assert not r["ok"] and r["problems"] == ["the Pages site is 0.0 MB (limit 0 MB)"]
    # the 50 KiB hand-off shard is excluded from the site, so it never counts toward the site
    (repo / "docs" / "_config.yml").write_text(CONFIG.replace("  - handoff/\n", ""))
    _git(repo, "commit", "-qam", "stop excluding handoff/")
    assert S.measure(repo, **_limits())["pages_mb"] == round((80 * KIB + 13) / S.MB, 1)


def test_exit_codes(repo):
    args = ["--repo", str(repo), "--warn-file-mib", "0.02", "--max-pages-mb", "1"]
    assert S.main(args + ["--max-file-mib", "1"]) == 0
    assert S.main(args + ["--max-file-mib", "0.04"]) == 1
    assert S.main(["--repo", str(repo), "--ref", "no-such-ref"]) == 2


def test_the_real_repo_is_measurable():
    r = S.measure(REPO)
    assert r["tracked_files"] > 1000 and r["pages_files"] > 0
    assert r["pages_exclude_rules"] >= 10, "docs/_config.yml was parsed"


# ---- the prerun gate ----------------------------------------------------------------------------

def test_gate_repo_size_fails_passes_and_warns_from_the_profile(repo):
    tight = {"repo_size": {"max_file_mib": 45 * KIB / S.MIB, "max_pages_mb": 1}}
    st, why = G.check_repo_size(repo, tight)
    assert st == G.FAIL and "a.one.000.jsonl" in why
    loose = {"repo_size": {"max_file_mib": 1, "warn_file_mib": 1, "max_pages_mb": 1,
                           "warn_pages_mb": 1}}
    assert G.check_repo_size(repo, loose)[0] == G.PASS
    warn = {"repo_size": {"max_file_mib": 1, "warn_file_mib": 45 * KIB / S.MIB, "max_pages_mb": 1}}
    assert G.check_repo_size(repo, warn)[0] == G.WARN


def test_gate_repo_size_is_in_the_check_order_and_the_real_profile_sets_the_limits():
    assert "repo-size" in G.CHECK_ORDER and "ci" in G.CHECK_ORDER
    prof = G.load_profile()["repo_size"]
    assert (prof["max_file_mib"], prof["max_pages_mb"]) == (90, 900)


def test_gate_handoff_age_is_the_newer_of_the_shards_and_the_legacy_file(repo):
    old = _git(repo, "log", "-1", "--format=%ct")
    profile = {"handoff": {"dir": "docs/handoff/stealth_leads",
                           "file": "docs/handoff/stealth_leads.json", "max_age_h": 36}}
    st, why = G.check_handoff(repo, profile)
    assert st == G.PASS and old
    gone = {"handoff": {"dir": "docs/handoff/nothing", "file": "docs/handoff/none.json"}}
    assert G.check_handoff(repo, gone)[0] == G.WARN


def _fake_gh(runs, rc=0):
    def gh(repo, args):
        assert args[:4] == ["run", "list", "--workflow", "Tests"] and "--commit" in args
        return rc, json.dumps(runs) if rc == 0 else "gh: not logged in"
    return gh


def test_gate_ci_refuses_a_pin_whose_tests_workflow_failed(repo):
    pin = _git(repo, "rev-parse", "HEAD")
    runs = [{"databaseId": 2, "status": "completed", "conclusion": "failure",
             "createdAt": "2026-10-08T18:35:44Z"},
            {"databaseId": 1, "status": "completed", "conclusion": "cancelled",
             "createdAt": "2026-10-08T18:00:00Z"}]
    st, why = G.check_ci(repo, pin, gh=_fake_gh(runs))
    assert st == G.FAIL and "run 2" in why and "--log-failed" in why
    ok = [{"databaseId": 3, "status": "completed", "conclusion": "success",
           "createdAt": "2026-10-09T10:00:00Z"}] + runs
    assert G.check_ci(repo, pin, gh=_fake_gh(ok))[0] == G.PASS


def test_gate_ci_warns_when_it_cannot_tell(repo):
    pin = _git(repo, "rev-parse", "HEAD")
    assert G.check_ci(repo, None)[0] == G.WARN
    assert G.check_ci(repo, pin, gh=_fake_gh([]))[0] == G.WARN
    assert G.check_ci(repo, pin, gh=_fake_gh([], rc=1))[0] == G.WARN
    running = [{"databaseId": 4, "status": "in_progress", "conclusion": "",
                "createdAt": "2026-10-09T10:00:00Z"}]
    assert "has not finished" in G.check_ci(repo, pin, gh=_fake_gh(running))[1]


# ---- CI -----------------------------------------------------------------------------------------

def test_ci_runs_the_size_check_in_its_own_job():
    wf = yaml.safe_load((REPO / ".github" / "workflows" / "tests.yml").read_text())
    job = wf["jobs"]["repo-size"]
    runs = "\n".join(step.get("run", "") for step in job["steps"])
    assert "python3 scripts/repo_size_check.py" in runs and 'exit "$rc"' in runs
    assert "needs" not in job, "independent of the pytest job: one result never hides the other"
