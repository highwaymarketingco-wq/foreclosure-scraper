"""deploy/oracle/run_failures.py: the swallowed step failures and time caps of a run log."""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
_SPEC = importlib.util.spec_from_file_location("run_failures", REPO / "deploy" / "oracle" / "run_failures.py")
R = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(R)


def _l(**kw) -> str:
    return json.dumps(kw, sort_keys=True)


LOG = [
    "==> VM run 20261008T014033  role=vm",
    _l(event="geocode.failed", level="error", traceback="Traceback ..."),
    _l(event="geocode.failed", level="error", traceback="Traceback ..."),
    _l(event="enrich.time_capped", level="warning", phase="doc_ocr", budget_s=900),
    _l(event="gis_attrs.time_capped", level="warning", note="proceeding"),
    _l(event="cchs.search_by_name_failed", level="error", name="x"),
    _l(event="orchestrator.count_drop_alert", level="error", prev=1, curr=0),
    _l(event="checkpoint.saved", level="info", phase="gis"),
    _l(event="something.odd", level="error"),
    "HTTP Request: GET https://example.org 200",
    "{not json",
]


def test_scan_separates_step_failures_caps_and_item_failures():
    res = R.scan(LOG)
    assert res["failed"] == {"geocode.failed": 2}
    assert res["time_capped"] == {"doc_ocr": 1, "gis_attrs": 1}
    assert res["item_failures"] == {"cchs.search_by_name_failed": 1}
    assert res["errors_other"] == 1          # the count-drop alert is reported elsewhere


def test_cli_report(tmp_path, capsys):
    p = tmp_path / "run.log"
    p.write_text("\n".join(LOG) + "\n")
    assert R.main([str(p)]) == 0
    out = capsys.readouterr().out
    assert "2 swallowed step failure(s)" in out and "geocode.failed x2" in out
    assert "doc_ocr x1" in out
    assert R.main([str(p), "--json"]) == 0
    assert json.loads(capsys.readouterr().out)["failed"] == {"geocode.failed": 2}


def test_clean_log_and_missing_log(tmp_path, capsys):
    p = tmp_path / "ok.log"
    p.write_text(_l(event="orchestrator.done", level="info") + "\n")
    assert R.main([str(p)]) == 0
    assert "none" in capsys.readouterr().out
    assert R.main([str(tmp_path / "missing.log")]) == 0


def test_vm_scripts_report_what_the_run_swallowed(tmp_path):
    """vm_run.sh and vm_resume.sh print the swallowed failures at the end of the run log."""
    import subprocess
    for name in ("vm_run.sh", "vm_resume.sh"):
        assert 'vm_report_swallowed "$LOG"' in (REPO / "deploy" / "oracle" / name).read_text(), name
    log = tmp_path / "run.log"
    log.write_text("\n".join(LOG) + "\n")
    out = subprocess.run(["bash", "-c", f'ROOT="{REPO}"; . "$ROOT/deploy/oracle/vm_lib.sh"; '
                                         f'vm_report_swallowed "{log}"; echo rc=$?'],
                         capture_output=True, text=True, timeout=60).stdout
    assert "geocode.failed x2" in out and "rc=0" in out
    assert "geocode.failed x2" in log.read_text()          # appended to the run log itself


def test_a_reconcile_counts_as_a_board_job():
    lib = (REPO / "deploy" / "oracle" / "vm_lib.sh").read_text()
    assert "reconcile_board\\.py" in lib
