"""scripts/reconcile_board.py: main.run_enrich_tail on a scored checkpoint with the network stubbed
and blocked. Made-up rows only; the real tail runs end to end on them."""
from __future__ import annotations

import ast
import asyncio
import gzip
import importlib.util
import json
import socket
import sys
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace

import pytest

REPO = Path(__file__).resolve().parent.parent
_SPEC = importlib.util.spec_from_file_location("reconcile_board", REPO / "scripts" / "reconcile_board.py")
R = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(R)


def _tail_imports() -> set[tuple[str, str]]:
    src = (REPO / "src" / "foreclosure_scraper" / "main.py").read_text()
    tree = ast.parse(src)
    fn = next(n for n in tree.body if isinstance(n, ast.AsyncFunctionDef) and n.name == "run_enrich_tail")
    out = set()
    for node in ast.walk(fn):
        if isinstance(node, ast.ImportFrom) and node.level == 1:
            out |= {(node.module, a.name) for a in node.names}
        elif isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) \
                and isinstance(node.func.value, ast.Name) and node.func.value.id == "valuation_rentcast":
            out.add(("valuation.rentcast", node.func.attr))
    return out


def test_every_tail_step_is_classified():
    """A new step in run_enrich_tail must be declared network (stubbed) or local (run) before a
    reconcile can run it: an unclassified network step would be blocked mid-tail and look broken."""
    known = set(R.NETWORK_STUBS) | set(R.LOCAL_STEPS) | {("valuation.rentcast", "update_grade_with_rentcast")}
    missing = sorted(_tail_imports() - known)
    assert not missing, f"classify these run_enrich_tail steps in scripts/reconcile_board.py: {missing}"


def test_every_stub_names_a_real_attribute_the_tail_uses():
    used = _tail_imports()
    for (mod, attr) in R.NETWORK_STUBS:
        m = importlib.import_module(f"foreclosure_scraper.{mod}")
        assert hasattr(m, attr), (mod, attr)
        if (mod, attr) in R.AWAITING_MAIN_WIRING:
            continue
        assert (mod, attr) in used, f"stale stub: run_enrich_tail no longer uses {mod}.{attr}"


def test_awaiting_steps_are_classified_and_real():
    for (mod, attr) in R.AWAITING_MAIN_WIRING:
        assert (mod, attr) in R.NETWORK_STUBS or (mod, attr) in R.LOCAL_STEPS, (mod, attr)
        assert hasattr(importlib.import_module(f"foreclosure_scraper.{mod}"), attr), (mod, attr)


def test_awaiting_steps_are_wired():
    missing = sorted(R.AWAITING_MAIN_WIRING - _tail_imports())
    assert not missing, f"not yet in run_enrich_tail: {missing}"


def test_network_is_blocked_inside_and_restored_after():
    with R.network_blocked():
        with pytest.raises(R.NetworkBlocked):
            socket.create_connection(("example.org", 80), timeout=1)
        with pytest.raises(R.NetworkBlocked):
            socket.getaddrinfo("example.org", 443)
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        with pytest.raises(OSError):
            s.connect(("127.0.0.1", 9))
        s.close()
        a, b = socket.socketpair()            # local IPC still works
        a.sendall(b"x")
        assert b.recv(1) == b"x"
        a.close(), b.close()
    assert socket.create_connection.__name__ == "create_connection"


def test_stubs_are_installed_and_removed():
    from foreclosure_scraper import enrichment_reo_freshness as reo
    orig = reo.prune_stale_reo
    with R.network_stubbed():
        assert reo.prune_stale_reo is not orig
        rows, stats = asyncio.run(reo.prune_stale_reo(["a", "b"]))
        assert rows == ["a", "b"] and stats == {"skipped": "reconcile"}
    assert reo.prune_stale_reo is orig


def test_catchup_is_held_and_released():
    li = SimpleNamespace(raw={"resolved_from_name": {"confidence": "unique_match"}}, street_address="1 A St",
                         parcel_id=None)
    done = SimpleNamespace(raw={"resolved_from_name": {"confidence": "unique_match"},
                                "_resolved_deep_enriched": True}, street_address="2 A St", parcel_id=None)
    held = R.hold_catchup([li, done])
    assert held == [li] and li.raw["_resolved_deep_enriched"] == R.HOLD
    R.release_catchup(held)
    assert "_resolved_deep_enriched" not in li.raw and done.raw["_resolved_deep_enriched"] is True


# ------------------------------------------------------------------------------- end to end
def _rows():
    from foreclosure_scraper.models import Listing, ListingType
    t = datetime(2026, 9, 1)
    return [
        Listing(source="counties_nc.polk_tax", source_url="https://example.org/tax/1", county="Polk",
                state="NC", parcel_id="P-1001", street_address="10 Test Ridge Rd", city="Columbus",
                listing_type=ListingType.TAX_LIEN, owner_name="SAMPLE OWNER A", assessed_value=120000,
                first_seen=t, last_seen=t, raw={"tax_owed": {"balance": 900.0, "kind": "delinquent_tax",
                                                             "source": "polk_tax", "parcel": "P-1001",
                                                             "year": 2024, "years_delinquent": 2}}),
        Listing(source="law_firms.example_trustee", source_url="https://example.org/sale/2", county="Union",
                state="SC", street_address="22 Sample Ln", city="Union", listing_type=ListingType.FORECLOSURE_SALE,
                opening_bid=85000, first_seen=t, last_seen=t,
                raw={"resolved_from_name": {"confidence": "unique_match"}}),
        Listing(source="counties_sc.example_vacant", source_url="https://example.org/v/3", county="Abbeville",
                state="SC", parcel_id="A-3", listing_type=ListingType.DISTRESSED, first_seen=t, last_seen=t, raw={}),
    ]


def _write_pre_publish(ck: Path, rows, monkeypatch):
    from foreclosure_scraper import checkpoint
    monkeypatch.setattr(checkpoint, "CHECKPOINT_DIR", ck)
    st = SimpleNamespace(enriched=rows, enrichment_stats={"geocode": {"n": 3}}, errors=["counties_nc.dead"],
                         scoring_failed=None, write_sold_pool=True, sold_pool=rows[:1], write_run_health=True,
                         export_and_email=True)
    summary = {"total": 3, "by_source": {"counties_nc.polk_tax": 1}, "source_status": {"counties_nc.polk_tax": "OK (1)"},
               "source_alarms": {}, "regressions": [], "errors": ["counties_nc.dead"], "off_footprint_removed": 0,
               "notes": "full run"}
    assert checkpoint.save_pre_publish(st, summary, extra={"origin": "main.run"})


@pytest.fixture
def quiet_board(monkeypatch):
    """Keep the tail off the real docs/listings.json (the prior-board key scan and count guard)."""
    from foreclosure_scraper import new_listings, web_artifact
    monkeypatch.setattr(new_listings, "_prior_keys_streamed", lambda *a, **k: (set(), 0))
    monkeypatch.setattr(web_artifact, "plain_board_row_count", lambda *a, **k: None)
    monkeypatch.setattr(web_artifact, "board_lock", _no_lock)


from contextlib import contextmanager


@contextmanager
def _no_lock(*a, **k):
    yield


def _dump(ck: Path) -> list[dict]:
    with gzip.open(ck / "board.json.gz", "rt") as fh:
        return json.load(fh)


VOLATILE = ("checked_at", "computed_at", "scored_at", "as_of", "generated_at", "expires_at", "is_new")


def _strip(o):
    if isinstance(o, dict):
        return {k: _strip(v) for k, v in o.items() if k not in VOLATILE}
    if isinstance(o, list):
        return [_strip(v) for v in o]
    return o


def test_reconcile_end_to_end_keeps_publish_inputs(tmp_path, monkeypatch, quiet_board):
    ck = tmp_path / "checkpoint"
    _write_pre_publish(ck, _rows(), monkeypatch)
    rc = R.main(["--checkpoint", str(ck), "--no-checks", "--max-rows", "100"])
    assert rc == 0
    man = json.loads((ck / "manifest.json").read_text())
    assert man["phase"] == "pre_publish" and man["count"] == 3
    assert man["reconciled_from"]["phase"] == "pre_publish" and man["origin"] == "main.run"
    state = json.loads((ck / "resume_state.json").read_text())
    assert state["publish"] == {"write_sold_pool": True, "write_run_health": True, "export_and_email": True}
    assert state["errors"] == ["counties_nc.dead"]
    assert state["summary"]["by_source"] == {"counties_nc.polk_tax": 1}
    assert state["summary"]["source_status"] == {"counties_nc.polk_tax": "OK (1)"}
    assert "reconciled" in state["summary"]["notes"]
    assert state["enrichment_stats"]["geocode"] == {"n": 3} and "reconcile" in state["enrichment_stats"]
    assert (ck / "sold_pool.json.gz").exists()
    assert list((tmp_path / "checkpoint_archive").iterdir())          # the replaced board is kept
    rows = _dump(ck)
    assert all((r["raw"].get("distress_stack") or {}).get("tier") in ("HOT", "WARM", "COLD") for r in rows)
    assert all(isinstance(r["raw"].get("calc"), dict) for r in rows)
    # the held catch-up row was not stamped deep-enriched by stubs that did nothing
    assert not any("_resolved_deep_enriched" in r["raw"] for r in rows)


def test_a_second_tail_pass_changes_nothing(tmp_path, monkeypatch, quiet_board):
    ck = tmp_path / "checkpoint"
    _write_pre_publish(ck, _rows(), monkeypatch)
    assert R.main(["--checkpoint", str(ck), "--no-checks", "--max-rows", "100"]) == 0
    first = _strip(_dump(ck))
    assert R.main(["--checkpoint", str(ck), "--no-checks", "--max-rows", "100"]) == 0
    assert _strip(_dump(ck)) == first, "a second pass of the tail changed the board"


def test_reconcile_refuses_what_it_cannot_do(tmp_path, monkeypatch, quiet_board):
    ck = tmp_path / "checkpoint"
    assert R.main(["--checkpoint", str(ck), "--no-checks"]) == 1                 # nothing there
    _write_pre_publish(ck, _rows(), monkeypatch)
    assert R.main(["--checkpoint", str(ck), "--no-checks", "--max-rows", "2"]) == 1   # too big here
    assert R.main(["--checkpoint", str(ck), "--no-checks", "--allow-phase", "dot_ocr"]) == 1
    (ck / "resume_state.json").unlink()                                          # inputs missing
    assert R.main(["--checkpoint", str(ck), "--no-checks", "--max-rows", "100"]) == 1
