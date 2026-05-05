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
