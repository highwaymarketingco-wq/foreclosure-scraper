"""scripts/carry_publish_state.py puts a gated full run's publish inputs onto a tail re-run's checkpoint.

A resume (vm_resume.sh --enrich-only) saves a pre_publish checkpoint whose publish switches are all off
and that has no scrape-phase health, so publishing it writes the board alone. HANDOFF item 81.
"""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest

_SPEC = importlib.util.spec_from_file_location(
    "carry_publish_state", Path(__file__).resolve().parent.parent / "scripts" / "carry_publish_state.py")
C = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(C)

FULL_SUMMARY = {"total": 350013, "new_this_week": 173863, "new_lis_pendens": 13169, "outreach": {"a": 1},
                "by_state": {"NC": 241524, "SC": 109050}, "by_county_top": [["x", 1]], "by_source": {"s": 5},
                "errors": ["counties_sc.a", "counties_sc.b"], "regressions": [], "off_footprint_removed": 5481,
                "source_status": {"counties_sc.a": "ok"}, "source_alarms": {"national.x": "0 for 2 runs"},
                "notes": "full run"}
FULL_STATE = {"summary": FULL_SUMMARY, "enrichment_stats": {"geocode": {"n": 1}, "score": {"old": True}},
              "errors": ["counties_sc.a", "counties_sc.b"], "scoring_failed": None,
              "publish": {"write_sold_pool": True, "write_run_health": True, "export_and_email": True},
              "state_token": "full-1"}
FULL_MANIFEST = {"phase": "pre_publish", "count": 350013, "saved_at": "2026-10-07T12:02:12+00:00",
                 "publish_state": "resume_state.json", "state_token": "full-1", "origin": "main.run"}

RERUN_SUMMARY = {"total": 350100, "new_this_week": 173900, "new_lis_pendens": 13170, "outreach": {"a": 2},
                 "by_state": {"NC": 241600, "SC": 109100}, "by_county_top": [["y", 2]], "by_source": {"s": 6},
                 "errors": [], "regressions": [], "off_footprint_removed": 0, "source_status": {},
                 "source_alarms": {}, "notes": "resumed from checkpoint phase 'dot_ocr'"}
RERUN_STATE = {"summary": RERUN_SUMMARY, "enrichment_stats": {"score": {"new": True}}, "errors": [],
               "scoring_failed": None,
               "publish": {"write_sold_pool": False, "write_run_health": False, "export_and_email": False},
               "state_token": "re-1"}
RERUN_MANIFEST = {"phase": "pre_publish", "count": 350100, "saved_at": "2026-10-07T17:00:00+00:00",
                  "publish_state": "resume_state.json", "state_token": "re-1",
                  "resumed_from": {"phase": "dot_ocr", "saved_at": "2026-10-07T08:28:41+00:00", "count": 350574}}


def _dirs(tmp_path, *, full_manifest=None, full_state=None, rerun_manifest=None, rerun_state=None,
          sold=True):
    src, live = tmp_path / "archive", tmp_path / "live"
    src.mkdir(); live.mkdir()
    (src / "manifest.json").write_text(json.dumps(full_manifest or FULL_MANIFEST))
    (src / "resume_state.json").write_text(json.dumps(full_state or FULL_STATE))
    if sold:
        (src / "sold_pool.json.gz").write_bytes(b"SOLDPOOL")
    (live / "manifest.json").write_text(json.dumps(rerun_manifest or RERUN_MANIFEST))
    (live / "resume_state.json").write_text(json.dumps(rerun_state or RERUN_STATE))
    (live / "board.json.gz").write_bytes(b"BOARD")
    return src, live


def test_carry_sets_the_full_runs_inputs_and_keeps_what_the_tail_recomputed():
    out = C.carry(FULL_STATE, RERUN_STATE, old_saved_at=FULL_MANIFEST["saved_at"])
    assert out["publish"] == FULL_STATE["publish"]
    assert out["errors"] == FULL_STATE["errors"]
    s = out["summary"]
    for k in ("source_status", "source_alarms", "regressions", "errors", "off_footprint_removed"):
        assert s[k] == FULL_SUMMARY[k]
    for k in ("total", "by_state", "by_county_top", "by_source", "outreach", "new_this_week", "new_lis_pendens"):
        assert s[k] == RERUN_SUMMARY[k]                      # the new board's own numbers
    assert out["state_token"] == "re-1"                      # still pairs with the live manifest
    assert "carried from the full run saved 2026-10-07T12:02:12" in s["notes"]
    assert s["notes"].startswith("resumed from checkpoint")


def test_enrichment_stats_union_with_the_rerun_winning():
    out = C.carry(FULL_STATE, RERUN_STATE)
    assert out["enrichment_stats"] == {"geocode": {"n": 1}, "score": {"new": True}}


def test_carry_does_not_modify_its_inputs():
    a, b = json.loads(json.dumps(FULL_STATE)), json.loads(json.dumps(RERUN_STATE))
    C.carry(a, b)
    assert a == FULL_STATE and b == RERUN_STATE


def test_main_rewrites_the_state_and_copies_the_sold_pool(tmp_path):
    src, live = _dirs(tmp_path)
    assert C.main(["--from", str(src), "--live", str(live)]) == 0
    st = json.loads((live / "resume_state.json").read_text())
    assert st["publish"] == FULL_STATE["publish"] and st["summary"]["source_alarms"]
    assert (live / "sold_pool.json.gz").read_bytes() == b"SOLDPOOL"
    assert (live / "board.json.gz").read_bytes() == b"BOARD"          # the board is never touched
    assert not list(live.glob("*.tmp"))


def test_dry_run_changes_nothing(tmp_path, capsys):
    src, live = _dirs(tmp_path)
    before = (live / "resume_state.json").read_text()
    assert C.main(["--from", str(src), "--live", str(live), "--dry-run"]) == 0
    assert (live / "resume_state.json").read_text() == before and not (live / "sold_pool.json.gz").exists()
    out = capsys.readouterr().out
    assert "publish will write: the board, sold pool, run_health.json, Sheet export + digest email" in out


@pytest.mark.parametrize("case", ["full_not_pre_publish", "full_token_mismatch", "full_no_switch",
                                  "sold_pool_missing", "live_not_a_resume", "live_token_mismatch",
                                  "live_not_pre_publish", "count_drift", "no_count"])
def test_refuses_and_changes_nothing(tmp_path, case, capsys):
    fm, fs, rm, rs, sold = dict(FULL_MANIFEST), json.loads(json.dumps(FULL_STATE)), \
        dict(RERUN_MANIFEST), json.loads(json.dumps(RERUN_STATE)), True
    if case == "full_not_pre_publish": fm["phase"] = "dot_ocr"
    if case == "full_token_mismatch": fs["state_token"] = "other"
    if case == "full_no_switch": fs["publish"] = {"write_sold_pool": False, "write_run_health": False,
                                                  "export_and_email": False}
    if case == "sold_pool_missing": sold = False
    if case == "live_not_a_resume": rm.pop("resumed_from")
    if case == "live_token_mismatch": rs["state_token"] = "other"
    if case == "live_not_pre_publish": rm["phase"] = "dot_ocr"
    if case == "count_drift": rm["count"] = 300000
    if case == "no_count": fm.pop("count")
    src, live = _dirs(tmp_path, full_manifest=fm, full_state=fs, rerun_manifest=rm, rerun_state=rs, sold=sold)
    before = (live / "resume_state.json").read_text()
    assert C.main(["--from", str(src), "--live", str(live)]) == 1
    assert (live / "resume_state.json").read_text() == before
    assert not (live / "sold_pool.json.gz").exists()
    assert "refused" in capsys.readouterr().err


def test_a_missing_file_is_a_refusal_not_a_crash(tmp_path, capsys):
    assert C.main(["--from", str(tmp_path / "nope"), "--live", str(tmp_path / "nope2")]) == 1
    assert "refused" in capsys.readouterr().err


def test_a_switch_off_for_the_sold_pool_copies_no_file(tmp_path):
    fs = json.loads(json.dumps(FULL_STATE))
    fs["publish"]["write_sold_pool"] = False
    src, live = _dirs(tmp_path, full_state=fs, sold=False)
    assert C.main(["--from", str(src), "--live", str(live)]) == 0
    assert not (live / "sold_pool.json.gz").exists()
    assert json.loads((live / "resume_state.json").read_text())["publish"]["write_sold_pool"] is False


def test_a_resume_with_no_scrape_counts_gets_the_full_runs_by_source():
    """A real resume's summary has by_source {} (TailState's empty Counter). Publishing that made the
    10/7 run_health.json show all 204 sources at count 0 beside 'OK (n)' statuses (audit 2026-10-09)."""
    rerun = json.loads(json.dumps(RERUN_STATE))
    rerun["summary"]["by_source"] = {}
    out = C.carry(FULL_STATE, rerun)
    assert out["summary"]["by_source"] == FULL_SUMMARY["by_source"]
