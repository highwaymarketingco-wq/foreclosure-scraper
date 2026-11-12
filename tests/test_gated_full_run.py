"""The gated VM launch, Python side (docs/HANDOFF.md item 72, 2026-10-06).

``vm_run.sh --stop-before-publish`` sets FULLRUN_STOP_BEFORE_PUBLISH: main.run() runs everything,
then ``main.stop_before_publish`` saves the scored board as a pre_publish checkpoint through the
SAME ``checkpoint.save_pre_publish`` the checkpoint resume uses, and publishes nothing. The
reviewed publish is ``vm_resume.sh --publish-only`` (scripts/resume_from_checkpoint.py), which must
then do what the full run's own publish would have done: the board, the sold pool, run_health,
the Sheet export and the digest email. A resume's checkpoint keeps publishing the board only.

main.run() itself is 2,900 lines of scrape + enrichment, so its hand-off is pinned by source
order (like tests/test_main_failure_paths.py) and everything after the hand-off runs for real
here, with the tail's output (a TailState) and the publish side effects stubbed.
"""
from __future__ import annotations

import contextlib
import gzip
import importlib.util
import inspect
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

import foreclosure_scraper.main as M
from foreclosure_scraper import checkpoint as C
from foreclosure_scraper.models import Listing, ListingType

REPO = Path(__file__).resolve().parent.parent


def _script(name: str):
    spec = importlib.util.spec_from_file_location(name.removesuffix(".py"), REPO / "scripts" / name)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _leads(n=4, prefix="A"):
    t = datetime(2026, 10, 6)
    return [Listing(source="s", source_url=f"https://x/{prefix}{i}", listing_type=ListingType.TAX_LIEN,
                    state="NC", county="Gaston", street_address=f"{i} {prefix} St", first_seen=t,
                    last_seen=t, raw={"k": i}) for i in range(n)]


@pytest.fixture
def ckdir(tmp_path, monkeypatch):
    monkeypatch.setattr(C, "CHECKPOINT_DIR", tmp_path / "data" / "checkpoint")
    monkeypatch.setattr(C, "ENABLED", True)
    return C.CHECKPOINT_DIR


@pytest.fixture
def no_publish(monkeypatch):
    """Every publish side effect fails the test if it is reached."""
    import foreclosure_scraper.run_health as RH
    for mod, name in ((M, "write_artifact"), (M, "write_listings"), (M, "send_digest"),
                      (RH, "write_health_artifact")):
        monkeypatch.setattr(mod, name, lambda *a, **k: pytest.fail("published during stop-before-publish"))


def _full_run_tail(n=4, sold=2, scoring_failed=None):
    """A TailState as main.run() builds it (every publish side effect on) after run_enrich_tail."""
    st = M.TailState(enriched=_leads(n), enrichment_stats={"distress_stack": {"HOT": 1, "WARM": 2}},
                     errors=["one source timed out"], cfg=None, sold_pool=_leads(sold, prefix="SOLD"))
    st.scoring_failed = scoring_failed
    return st


SUMMARY = {"total": 4, "new_this_week": 3, "by_state": {"NC": 4}, "by_source": {"s": 4},
           "by_county_top": [["Gaston", 4]], "regressions": [], "source_alarms": {},
           "notes": "horizon=60d, scrapers=91, regressions=0"}


def _resume(monkeypatch, *argv):
    from foreclosure_scraper import web_artifact as wa

    @contextlib.contextmanager
    def fake_lock(*a, **k):           # never touch the real repo's lock from a test
        yield "lock"
    monkeypatch.setattr(wa, "board_lock", fake_lock)
    mod = _script("resume_from_checkpoint.py")
    monkeypatch.setattr(mod.os, "chdir", lambda *_: None)
    monkeypatch.setattr(sys, "argv", ["resume_from_checkpoint.py", *argv])
    return mod.main()


# ---------------------------------------------------------------------------------------------
# main.run()'s hand-off
# ---------------------------------------------------------------------------------------------

def test_run_checks_the_switch_after_the_tail_and_before_the_publish():
    src = inspect.getsource(M.run)
    tail = src.index("summary = await run_enrich_tail(_tail)")
    switch = src.index("STOP_BEFORE_PUBLISH_ENV")
    stop = src.index("return stop_before_publish(_tail, summary)")
    publish = src.index("return publish_tail(_tail, summary)")
    assert tail < switch < stop < publish, "the stop must come after scoring and before any publish step"
    assert M.STOP_BEFORE_PUBLISH_ENV == "FULLRUN_STOP_BEFORE_PUBLISH"
    vm_run = (REPO / "deploy" / "oracle" / "vm_run.sh").read_text()
    assert "FULLRUN_STOP_BEFORE_PUBLISH=1" in vm_run, "vm_run.sh --stop-before-publish must set the switch"


def test_stop_before_publish_saves_what_publish_only_consumes_and_publishes_nothing(ckdir, no_publish):
    st = _full_run_tail()
    assert M.stop_before_publish(st, dict(SUMMARY)) == M.EXIT_OK
    m = C.manifest()
    assert m["phase"] == C.PRE_PUBLISH == "pre_publish" and m["count"] == 4
    assert m["origin"] == "main.run" and m["publish_state"] == C.STATE_FILE and m["state_token"]
    state = json.loads((ckdir / C.STATE_FILE).read_text())
    assert state["state_token"] == m["state_token"]
    assert state["publish"] == {"write_sold_pool": True, "write_run_health": True, "export_and_email": True}
    assert state["summary"]["total"] == 4 and state["errors"] == ["one source timed out"]
    assert state["enrichment_stats"]["distress_stack"] == {"HOT": 1, "WARM": 2}
    with gzip.open(ckdir / C.SOLD_POOL_FILE, "rt") as fh:
        assert [r["source_url"] for r in json.load(fh)] == ["https://x/SOLD0", "https://x/SOLD1"]
    assert [li.source_url for li in C.load(max_age_h=1)] == [f"https://x/A{i}" for i in range(4)]


def test_publish_only_then_does_what_the_full_runs_publish_would_have(ckdir, no_publish, monkeypatch):
    assert M.stop_before_publish(_full_run_tail(), dict(SUMMARY)) == M.EXIT_OK
    # the reviewed publish: the REAL publish_tail, with its side effects recorded instead of done
    calls = []
    import foreclosure_scraper.run_health as RH
    monkeypatch.setattr(M, "write_artifact", lambda enriched, summary, **k: calls.append(("board", len(enriched), summary["total"])))
    monkeypatch.setattr(M, "write_listings", lambda **k: calls.append(("sheet", len(k["listings"]))) or "url")
    monkeypatch.setattr(M, "send_digest", lambda **k: calls.append(("email", k["run_summary"]["notes"])))
    monkeypatch.setattr(RH, "write_health_artifact", lambda **k: calls.append(("health", k["summary"]["total"])))
    real_write_text = Path.write_text

    def write_text(self, data, *a, **k):
        if self.name == "foreclosure_sold_pool.json":       # never the real repo's docs/
            return calls.append(("sold_pool", [r["source_url"] for r in json.loads(data)]))
        return real_write_text(self, data, *a, **k)
    monkeypatch.setattr(Path, "write_text", write_text)
    monkeypatch.setattr(M, "run_enrich_tail", lambda st: pytest.fail("must not re-run the tail"))
    monkeypatch.setenv("SHEET_ID", "sheet")
    monkeypatch.setenv("GOOGLE_SERVICE_ACCOUNT_JSON", "{}")
    monkeypatch.setenv("GMAIL_APP_PASSWORD", "pw")
    monkeypatch.setenv("GMAIL_SENDER", "sender@example.com")
    monkeypatch.setenv("EMAIL_RECIPIENTS", "r@example.com")
    assert _resume(monkeypatch, "--publish-only") == M.EXIT_OK
    assert calls == [("board", 4, 4),
                     ("sold_pool", ["https://x/SOLD0", "https://x/SOLD1"]),
                     ("health", 4), ("sheet", 4),
                     ("email", "horizon=60d, scrapers=91, regressions=0")]
    assert not ckdir.exists(), "a successful publish drops the checkpoint"


def test_a_resumes_checkpoint_still_publishes_the_board_only(ckdir, monkeypatch):
    C.save(_leads(), "dot_ocr")

    async def fake_enrich(st):
        return {"total": len(st.enriched), "notes": "tail"}
    import foreclosure_scraper.sos_agent_handoff as H
    monkeypatch.setattr(H, "apply_sos_agent_handoff", lambda ls: {})
    monkeypatch.setattr(M, "run_enrich_tail", fake_enrich)
    assert _resume(monkeypatch, "--enrich-only") == M.EXIT_OK
    state = json.loads((ckdir / C.STATE_FILE).read_text())
    assert state["publish"] == {"write_sold_pool": False, "write_run_health": False, "export_and_email": False}
    assert not (ckdir / C.SOLD_POOL_FILE).exists()
    assert C.manifest()["resumed_from"]["phase"] == "dot_ocr"
    got = {}
    monkeypatch.setattr(M, "publish_tail", lambda st, summary: got.update(st=st) or M.EXIT_OK)
    assert _resume(monkeypatch, "--publish-only") == M.EXIT_OK
    st = got["st"]
    assert (st.write_sold_pool, st.write_run_health, st.export_and_email, st.update_source_health) == \
        (False, False, False, False)


def test_the_replaced_pre_scoring_checkpoint_is_archived_for_a_rejected_review(ckdir, no_publish):
    C.save(_leads(), "dot_ocr")
    saved_at = C.manifest()["saved_at"].replace(":", "")
    assert M.stop_before_publish(_full_run_tail(), dict(SUMMARY)) == M.EXIT_OK
    arch = ckdir.parent / "checkpoint_archive" / f"dot_ocr_{saved_at}"
    assert (arch / C.BOARD_FILE).exists() and json.loads((arch / C.MANIFEST_FILE).read_text())["phase"] == "dot_ocr"


def test_a_failed_save_exits_3_and_publishes_nothing(ckdir, no_publish, monkeypatch):
    monkeypatch.setattr(C, "ENABLED", False)          # FORECLOSURE_CHECKPOINT=0, or a full disk
    assert M.stop_before_publish(_full_run_tail(), dict(SUMMARY)) == M.EXIT_WRITE_FAILED
    assert not (ckdir / C.MANIFEST_FILE).exists()


def test_stale_tiers_are_saved_and_exit_6(ckdir, no_publish):
    st = _full_run_tail(scoring_failed="ScoreBoardError: boom")
    assert M.stop_before_publish(st, dict(SUMMARY)) == M.EXIT_SCORE_FAILED
    assert json.loads((ckdir / C.STATE_FILE).read_text())["scoring_failed"] == "ScoreBoardError: boom"


@pytest.mark.parametrize("damage", ["missing", "other_token", "garbage"])
def test_publish_only_refuses_a_board_without_its_own_publish_inputs(ckdir, no_publish, monkeypatch, damage):
    assert M.stop_before_publish(_full_run_tail(), dict(SUMMARY)) == M.EXIT_OK
    p = ckdir / C.STATE_FILE
    if damage == "missing":
        p.unlink()
    elif damage == "other_token":
        p.write_text(json.dumps({**json.loads(p.read_text()), "state_token": "another-run"}))
    else:
        p.write_text("{not json")
    monkeypatch.setattr(M, "publish_tail", lambda *a: pytest.fail("published a board without its summary"))
    assert _resume(monkeypatch, "--publish-only") == 1


def test_a_crash_between_board_and_state_cannot_pair_old_inputs_with_a_new_board(ckdir, no_publish, monkeypatch):
    assert M.stop_before_publish(_full_run_tail(), dict(SUMMARY)) == M.EXIT_OK
    real = C._atomic_write_text

    def crash(path, text):
        if path.name == C.STATE_FILE:
            raise OSError("disk full")
        return real(path, text)
    monkeypatch.setattr(C, "_atomic_write_text", crash)
    assert M.stop_before_publish(_full_run_tail(n=5), {**SUMMARY, "total": 5}) == M.EXIT_WRITE_FAILED
    assert C.manifest()["count"] == 5 and not (ckdir / C.STATE_FILE).exists()
    state, why = C.load_publish_state()
    assert state == {} and "missing" in why


def test_pre_publish_age_limit_is_96h_by_default_and_overridable(ckdir, no_publish, monkeypatch):
    assert C.PRE_PUBLISH_MAX_AGE_H == 96.0
    assert M.stop_before_publish(_full_run_tail(), dict(SUMMARY)) == M.EXIT_OK
    mp = ckdir / C.MANIFEST_FILE

    def age(hours):
        m = json.loads(mp.read_text())
        m["saved_at"] = (datetime.now(timezone.utc) - timedelta(hours=hours)).isoformat(timespec="seconds")
        mp.write_text(json.dumps(m))
    seen = []
    monkeypatch.setattr(M, "publish_tail", lambda st, summary: seen.append(len(st.enriched)) or M.EXIT_OK)
    age(72)       # a Friday-night run reviewed on Monday: past the 48 h general limit, inside 96 h
    assert _resume(monkeypatch, "--publish-only") == 0 and seen == [4]
    age(100)
    assert _resume(monkeypatch, "--publish-only") == 1 and seen == [4]
    assert _resume(monkeypatch, "--publish-only", "--max-age-h", "120") == 0 and seen == [4, 4]


def test_the_preview_shows_the_runs_summary_and_what_will_publish(ckdir, no_publish, monkeypatch, capsys):
    s = {**SUMMARY, "regressions": ["COUNT DROP 30%: 300 -> 210 listings vs last run"],
         "count_drop_alert": {"prev_total": 300, "curr_total": 210, "drop_pct": 30},
         "source_alarms": {"nc_x": {"reason": "BLOCKED: 403"}}}
    assert M.stop_before_publish(_full_run_tail(), s) == M.EXIT_OK
    before = (ckdir / C.MANIFEST_FILE).read_text()
    assert _resume(monkeypatch) == 0
    out = capsys.readouterr().out
    assert "phase='pre_publish' leads=4" in out and "origin: main.run" in out
    assert "the board, sold pool, run_health.json, Sheet export + digest email" in out
    assert "COUNT DROP ALERT" in out and "nc_x: BLOCKED: 403" in out and "tiers: {'HOT': 1, 'WARM': 2}" in out
    assert (ckdir / C.MANIFEST_FILE).read_text() == before


# ---------------------------------------------------------------------------------------------
# board_selfcheck --checkpoint: the review grades the board as it would publish
# ---------------------------------------------------------------------------------------------

def test_selfcheck_grades_a_checkpoint_as_it_would_publish(ckdir, monkeypatch, capsys):
    sc = _script("board_selfcheck.py")
    flag = next(iter(sc.CONTRADICTED))
    good = _leads(2)
    bad = _leads(1, prefix="B")[0]
    bad.raw = {"calc": {"arv_flags": [flag], "max_bid_70": 150_000}, "not_in_raw_keep": {"x": 1}}
    C.save(good + [bad], "pre_publish")
    rows = list(sc._checkpoint_rows(ckdir))
    assert len(rows) == 3 and "not_in_raw_keep" not in rows[2]["raw"], "rows are the published shape"
    inv = {i["name"]: i for i in sc.invariants(rows)}
    assert inv["no max_bid_70 on a contradicted ARV"]["count"] == 1
    monkeypatch.setattr(sc, "_previous", lambda ref: None)
    monkeypatch.setattr(sys, "argv", ["board_selfcheck.py", "--checkpoint", str(ckdir)])
    assert sc.main() == 1
    assert "3 leads (checkpoint" in capsys.readouterr().out
    C.save(good, "pre_publish")
    assert sc.main() == 0
