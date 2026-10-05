"""scripts/resume_from_checkpoint.py finishes a dead run through main.py's OWN tail.

The 2026-10-05 VM run died after its dot_ocr checkpoint; the only recovery tool then published
the checkpoint unscored. The resume path must (a) call the same run_enrich_tail/publish_tail
that main.run() calls, (b) run the SOS hand-off apply step that sits before the checkpoint,
(c) keep the scored board as a pre_publish checkpoint before publishing, and (d) skip the four
side effects a resume has no data for (sold pool, run_health, Sheet + digest email, source
history), while the board write itself is the normal one.
"""
from __future__ import annotations

import importlib.util
import json
import sys
from datetime import datetime
from pathlib import Path

import pytest

import foreclosure_scraper.main as M
from foreclosure_scraper import checkpoint as C
from foreclosure_scraper.models import Listing, ListingType

REPO = Path(__file__).resolve().parent.parent


def _script():
    spec = importlib.util.spec_from_file_location("resume_from_checkpoint",
                                                  REPO / "scripts" / "resume_from_checkpoint.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _leads(n=4):
    t = datetime(2026, 10, 5)
    return [Listing(source="s", source_url=f"https://x/{i}", listing_type=ListingType.TAX_LIEN,
                    state="NC", county="Gaston", street_address=f"{i} A St", first_seen=t,
                    last_seen=t, raw={"k": i}) for i in range(n)]


@pytest.fixture
def ckpt(tmp_path, monkeypatch):
    monkeypatch.setattr(C, "CHECKPOINT_DIR", tmp_path / "data" / "checkpoint")
    monkeypatch.setattr(C, "ENABLED", True)
    C.save(_leads(), "dot_ocr")
    return tmp_path


def _run(monkeypatch, *argv):
    import contextlib
    from foreclosure_scraper import web_artifact as wa

    @contextlib.contextmanager
    def fake_lock(*a, **k):           # never touch the real repo's lock from a test
        yield "lock"
    monkeypatch.setattr(wa, "board_lock", fake_lock)
    mod = _script()
    monkeypatch.setattr(mod.os, "chdir", lambda *_: None)
    monkeypatch.setattr(sys, "argv", ["resume_from_checkpoint.py", *argv])
    return mod.main()


def test_run_uses_mains_tail_with_the_resume_switches(ckpt, monkeypatch):
    seen = {}

    async def fake_enrich(st):
        seen["enrich"] = st
        assert st.update_source_health is False
        assert (st.write_sold_pool, st.write_run_health, st.export_and_email) == (False, False, False)
        assert len(st.enriched) == 4
        st.enrichment_stats["distress_stack"] = {"HOT": 1}
        return {"total": len(st.enriched), "notes": "tail"}

    def fake_publish(st, summary):
        seen["publish"] = (st, summary)
        # the scored board was checkpointed BEFORE the publish was attempted
        assert C.manifest()["phase"] == "pre_publish"
        state = json.loads((C.CHECKPOINT_DIR / "resume_state.json").read_text())
        assert state["enrichment_stats"]["distress_stack"] == {"HOT": 1}
        return M.EXIT_OK

    applied = {}
    import foreclosure_scraper.sos_agent_handoff as H
    monkeypatch.setattr(H, "apply_sos_agent_handoff", lambda ls: applied.setdefault("n", len(ls)) and {"attached": 0})
    monkeypatch.setattr(M, "run_enrich_tail", fake_enrich)
    monkeypatch.setattr(M, "publish_tail", fake_publish)
    assert _run(monkeypatch, "--run") == 0
    assert applied["n"] == 4, "the SOS hand-off apply step (before the dot_ocr checkpoint in run()) was skipped"
    st, summary = seen["publish"]
    assert st is seen["enrich"]
    assert summary["recovered_from_checkpoint"] is True and summary["checkpoint_phase"] == "dot_ocr"
    assert "resumed from checkpoint phase 'dot_ocr'" in summary["notes"]
    arch = list((C.CHECKPOINT_DIR.parent / "checkpoint_archive").glob("dot_ocr_*/board.json.gz"))
    assert arch, "the dot_ocr checkpoint was not archived before being replaced"


def test_publish_only_republishes_the_pre_publish_checkpoint(ckpt, monkeypatch):
    C.save(_leads(3), "pre_publish")
    (C.CHECKPOINT_DIR / "resume_state.json").write_text(json.dumps(
        {"summary": {"total": 3, "notes": "x"}, "enrichment_stats": {"a": {}}, "errors": ["e"],
         "scoring_failed": None}))
    got = {}

    def fake_publish(st, summary):
        got["st"], got["summary"] = st, summary
        return M.EXIT_OK
    monkeypatch.setattr(M, "publish_tail", fake_publish)
    monkeypatch.setattr(M, "run_enrich_tail", lambda st: pytest.fail("must not re-run the tail"))
    assert _run(monkeypatch, "--publish-only") == 0
    assert len(got["st"].enriched) == 3 and got["st"].errors == ["e"]
    assert got["st"].write_sold_pool is False and got["st"].export_and_email is False


def test_wrong_phase_is_refused(ckpt, monkeypatch):
    monkeypatch.setattr(M, "run_enrich_tail", lambda st: pytest.fail("ran on the wrong phase"))
    assert _run(monkeypatch, "--publish-only") == 1      # checkpoint is dot_ocr, not pre_publish


def test_dry_run_changes_nothing(ckpt, monkeypatch):
    before = (C.CHECKPOINT_DIR / C.MANIFEST_FILE).read_text()
    assert _run(monkeypatch) == 0
    assert (C.CHECKPOINT_DIR / C.MANIFEST_FILE).read_text() == before


def test_publish_tail_honours_the_resume_switches(tmp_path, monkeypatch):
    """publish_tail with the resume switches writes the board and nothing else."""
    calls = []
    monkeypatch.setattr(M, "write_artifact", lambda enriched, summary: calls.append("board"))
    monkeypatch.setattr(M.checkpoint, "clear", lambda: calls.append("clear"))
    monkeypatch.setattr(M, "write_listings", lambda **k: calls.append("sheet"))
    monkeypatch.setattr(M, "send_digest", lambda **k: calls.append("email"))
    import foreclosure_scraper.run_health as RH
    monkeypatch.setattr(RH, "write_health_artifact", lambda **k: calls.append("health"))
    cfg = type("Cfg", (), {"sheet_id": "s", "google_service_account_json": "{}", "gmail_app_password": "p",
                           "gmail_sender": "a@b", "email_recipients": ["c@d"]})()
    st = M.TailState(enriched=_leads(2), enrichment_stats={}, errors=[], cfg=cfg,
                     write_sold_pool=False, write_run_health=False, export_and_email=False)
    assert M.publish_tail(st, {"total": 2}) == M.EXIT_OK
    assert calls == ["board", "clear"]
    st_full = M.TailState(enriched=_leads(2), enrichment_stats={}, errors=[], cfg=cfg)
    monkeypatch.setattr(M.Path, "write_text", lambda *a, **k: calls.append("sold_pool"))
    calls.clear()
    assert M.publish_tail(st_full, {"total": 2}) == M.EXIT_OK
    assert calls == ["board", "clear", "sold_pool", "health", "sheet", "email"]
