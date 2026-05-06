"""Pin the GitHub Actions weekly workflow's critical behaviors.

The audit found the workflow was running every Tuesday but never
publishing docs/listings.json back to the repo, so dashboard never
updated. This commit added the publish step, plus contents:write
permission, plus a regression banner in the workflow summary.
These tests prevent any of those from regressing.
"""
from __future__ import annotations

from pathlib import Path

import yaml


WORKFLOW = Path(__file__).resolve().parent.parent / ".github" / "workflows" / "weekly.yml"


def _load() -> dict:
    return yaml.safe_load(WORKFLOW.read_text())


def test_workflow_has_contents_write_permission():
    """Required for the publish step to push commits."""
    y = _load()
    perms = y.get("permissions") or {}
    assert perms.get("contents") == "write"


def test_workflow_runs_on_tuesday_morning():
    y = _load()
    triggers = y.get("on") or y.get(True)  # PyYAML parses "on:" as True
    cron = triggers["schedule"][0]["cron"]
    # 0 9 * * 2 = Tue 09:00 UTC
    assert cron == "0 9 * * 2"


def test_workflow_supports_manual_dispatch():
    y = _load()
    triggers = y.get("on") or y.get(True)
    assert "workflow_dispatch" in triggers


def test_workflow_publishes_dashboard_data():
    y = _load()
    steps = y["jobs"]["scrape"]["steps"]
    publish = next((s for s in steps if "Publish" in s.get("name", "")), None)
    assert publish is not None, "no publish step in workflow"
    cmd = publish.get("run", "")
    assert "docs/listings.json" in cmd
    assert "git commit" in cmd
    assert "git push" in cmd


def test_workflow_verifies_artifact_before_publish():
    """Hard-fail the workflow if the orchestrator didn't write listings.json
    — better than silently committing nothing."""
    y = _load()
    steps = y["jobs"]["scrape"]["steps"]
    verify = next((s for s in steps if "Verify run" in s.get("name", "")), None)
    assert verify is not None
    assert "test -f docs/listings.json" in verify["run"]


def test_workflow_uploads_run_log_artifact():
    y = _load()
    steps = y["jobs"]["scrape"]["steps"]
    upload = next((s for s in steps if "Upload run log" in s.get("name", "")), None)
    assert upload is not None
    assert upload.get("if") == "always()", "log upload must run even on failure"


def test_workflow_backs_up_listings_before_publish():
    """The 2026-05-06 incident: Run #14 finished its scrape work, wrote
    docs/listings.json on the runner, but the publish step failed due to
    a git conflict. The listings.json was on ephemeral runner storage
    only (not in the run-log artifact), so ~3 hours of work was lost.
    This step uploads listings.json BEFORE publish so a publish failure
    can never lose the data again."""
    y = _load()
    steps = y["jobs"]["scrape"]["steps"]
    backup = next((s for s in steps
                   if "Backup listings to artifact" in s.get("name", "")), None)
    assert backup is not None, "no listings-backup step before publish"
    assert backup.get("if") == "always()"
    # Must run BEFORE the publish step
    publish_idx = next(i for i, s in enumerate(steps)
                       if "Publish dashboard data" in s.get("name", ""))
    backup_idx = steps.index(backup)
    assert backup_idx < publish_idx, "backup must run BEFORE publish"


def test_workflow_publish_handles_concurrent_commits():
    """The publish step must survive other commits landing during the run
    (the Run #14 failure mode). Strategy: re-fetch + reset + re-apply
    docs commit on each retry, with at least 5 attempts."""
    y = _load()
    steps = y["jobs"]["scrape"]["steps"]
    publish = next((s for s in steps
                    if "Publish dashboard data" in s.get("name", "")), None)
    assert publish is not None
    cmd = publish.get("run", "")
    assert "git fetch origin" in cmd
    assert "git reset --hard" in cmd
    # At least 5 retry attempts
    for n in ("1", "2", "3", "4", "5"):
        assert n in cmd, f"retry attempt {n} not present"


def test_workflow_passes_required_secrets_as_env():
    """The audit identified missing env wiring for ANTHROPIC_API_KEY,
    COURTLISTENER_TOKEN, RENTCAST_API_KEY, FORECLOSURE_DOT_COM_*. These
    must reach the orchestrator process."""
    y = _load()
    env = y["jobs"]["scrape"]["env"]
    required = {
        "ANTHROPIC_API_KEY", "COURTLISTENER_TOKEN", "RENTCAST_API_KEY",
        "FORECLOSURE_DOT_COM_USER", "FORECLOSURE_DOT_COM_PASS",
        "APIFY_TOKEN", "GOOGLE_SERVICE_ACCOUNT_JSON",
    }
    missing = required - set(env.keys())
    assert not missing, f"workflow missing env vars: {missing}"


def test_workflow_installs_playwright():
    """Scrapling stealth needs Chromium installed on the runner."""
    y = _load()
    steps = y["jobs"]["scrape"]["steps"]
    pw = next((s for s in steps if "Playwright" in s.get("name", "")), None)
    assert pw is not None, "missing Playwright install step"
    assert "chromium" in pw["run"]


def test_workflow_surfaces_regressions_in_summary():
    """A REGRESSED source should be visible in the GitHub Actions
    workflow summary so on-call doesn't miss it."""
    y = _load()
    steps = y["jobs"]["scrape"]["steps"]
    summary = next((s for s in steps if "summary" in s.get("name", "").lower()), None)
    assert summary is not None
    assert "GITHUB_STEP_SUMMARY" in summary["run"]
    assert "regressions" in summary["run"].lower()
