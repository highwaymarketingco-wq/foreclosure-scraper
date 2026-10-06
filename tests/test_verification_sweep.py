"""scripts/verification_sweep.py on a scratch board: selection order (HOT -> WARM -> COLD, then
oldest check), one check per property, TTL skip, county filter, cap, incremental ledger, and
the board is never written. No network (a fake verifier)."""
from __future__ import annotations

import gzip
import hashlib
import importlib.util
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from foreclosure_scraper.verification import core
from foreclosure_scraper.verification import ledger as L
from foreclosure_scraper.verification.registry import Verifier

REPO = Path(__file__).resolve().parent.parent
NOW = datetime(2026, 10, 5, 12, 0, tzinfo=timezone.utc)


def _load_script():
    spec = importlib.util.spec_from_file_location("verification_sweep", REPO / "scripts" / "verification_sweep.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _row(pid, tier, county="Buncombe", addr=None):
    return {"source": "s", "source_url": "https://x/roll.pdf", "listing_type": "tax_lien",
            "state": "NC", "county": county, "parcel_id": pid, "street_address": addr or f"{pid[-3:]} Main St",
            "raw": {"distress_stack": {"tier": tier}}}


ROWS = [_row("1000000001", "COLD"), _row("1000000002", "WARM"), _row("1000000003", "HOT"),
        _row("1000000004", "WARM"), _row("1000000003", "COLD", addr="Other Name Rd"),   # same parcel
        _row("1000000005", "HOT", county="Henderson"), _row("1000000006", "HOT")]


@pytest.fixture
def board(tmp_path):
    docs = tmp_path / "docs"
    docs.mkdir()
    (docs / "listings.json.gz").write_bytes(gzip.compress(json.dumps(ROWS).encode()))
    return docs


def _fake_verifier(calls):
    async def verify(row, client):
        calls.append(row["parcel_id"])
        verdict = "refuted" if row["parcel_id"].endswith("2") else "confirmed"
        return core.result("tax_lien", verdict, {"pid": row["parcel_id"]}, source="fake",
                           version="v1", verifier="fake_tax")
    return Verifier(name="fake_tax", signal="tax_lien", version="v1", ttl_days=30,
                    applies=lambda r: r.get("listing_type") == "tax_lien", verify=verify,
                    governs=("tax_lien",))


def test_selection_order_dedupe_ttl_county_and_cap(board):
    sw = _load_script()
    v = _fake_verifier([])
    led = L.Ledger("tax_lien")
    # 1000000006 (HOT) was checked yesterday: not due; 1000000004 (WARM) checked 40 days ago: due
    led.record(ROWS[6], core.result("tax_lien", "confirmed", {}, version="v1", verifier="fake_tax",
                                    now=NOW - timedelta(days=1)), ttl_days=30, now=NOW)
    led.record(ROWS[3], core.result("tax_lien", "confirmed", {}, version="v1", verifier="fake_tax",
                                    now=NOW - timedelta(days=40)), ttl_days=30, now=NOW)
    plan, why = sw.select(board / "listings.json.gz", [v], {"tax_lien": led}, county="Buncombe",
                          cap=10, now=NOW)
    order = [row["parcel_id"] for _p, _k, row, _v in plan["tax_lien"]]
    # HOT first; WARM never-checked before WARM re-check; COLD last; same parcel once (the HOT
    # row kept); Henderson filtered; the fresh HOT row not due
    assert order == ["1000000003", "1000000002", "1000000004", "1000000001"]
    assert plan["tax_lien"][0][2]["raw"]["distress_stack"]["tier"] == "HOT"
    assert why["tax_lien"]["same_property_queued"] == 1
    assert why["tax_lien"]["not_due_ttl"] == 1 and why["tax_lien"]["due_ttl"] == 1
    capped, _ = sw.select(board / "listings.json.gz", [v], {"tax_lien": led}, county=None,
                          cap=2, now=NOW)
    assert [r["parcel_id"] for _p, _k, r, _v in capped["tax_lien"]] == ["1000000003", "1000000005"]


def test_end_to_end_writes_the_ledger_and_never_the_board(board, tmp_path, monkeypatch):
    sw = _load_script()
    calls: list[str] = []
    monkeypatch.setattr(sw, "discover", lambda: [_fake_verifier(calls)])
    monkeypatch.setattr(sw, "RUN_LOCK", tmp_path / "sweep.lock")
    monkeypatch.setenv("HANDOFF_PUSH", "0")
    before = hashlib.sha256((board / "listings.json.gz").read_bytes()).hexdigest()
    ldir = tmp_path / "ledger"
    rc = sw.main(["--signal", "tax_lien", "--county", "Buncombe", "--max-rows", "50",
                  "--docs", str(board), "--ledger-dir", str(ldir), "--save-every", "1"])
    assert rc == 0
    assert hashlib.sha256((board / "listings.json.gz").read_bytes()).hexdigest() == before
    assert sorted(calls) == ["1000000001", "1000000002", "1000000003", "1000000004", "1000000006"]
    led = L.Ledger.load("tax_lien", ldir)
    assert led.counts()["rows"] == 5 and led.counts()["refuted"] == 1
    assert led.last_run["result"]["checked"] == 5
    # a second run finds nothing due
    calls.clear()
    assert sw.main(["--signal", "tax_lien", "--docs", str(board), "--ledger-dir", str(ldir)]) == 0
    assert calls == ["1000000005"]      # only the Henderson row the first run filtered out


def test_a_crashing_verifier_is_an_unconfirmed_answer(board, tmp_path, monkeypatch):
    sw = _load_script()

    async def verify(row, client):
        raise RuntimeError("parser exploded")
    v = Verifier(name="boom", signal="tax_lien", version="v1", ttl_days=30,
                 applies=lambda r: r["parcel_id"] == "1000000003", verify=verify)
    monkeypatch.setattr(sw, "discover", lambda: [v])
    monkeypatch.setattr(sw, "RUN_LOCK", tmp_path / "sweep.lock")
    monkeypatch.setenv("HANDOFF_PUSH", "0")
    ldir = tmp_path / "ledger"
    assert sw.main(["--docs", str(board), "--ledger-dir", str(ldir)]) == 0
    e = next(iter(L.Ledger.load("tax_lien", ldir).rows.values()))
    assert e["latest"]["verdict"] == "unconfirmed"
    assert e["latest"]["evidence"]["reason"] == "verifier_error"


def test_the_sweep_holds_no_board_write_path():
    src = (REPO / "scripts" / "verification_sweep.py").read_text()
    for banned in ("patch_existing_rows(", "write_artifact(", "load_board(", "append_new_rows("):
        assert banned not in src


def test_recheck_only_takes_just_rows_already_in_the_ledger(board):
    sw = _load_script()
    v = _fake_verifier([])
    led = L.Ledger("tax_lien")
    led.record(ROWS[0], core.result("tax_lien", "confirmed", {}, version="v0", verifier="fake_tax",
                                    now=NOW - timedelta(days=1)), ttl_days=30, now=NOW)
    plan, why = sw.select(board / "listings.json.gz", [v], {"tax_lien": led}, county=None,
                          cap=10, now=NOW, recheck_only=True)
    assert [r["parcel_id"] for _p, _k, r, _v in plan["tax_lien"]] == ["1000000001"]
    assert why["tax_lien"]["due_version"] == 1


def test_tier_filter(board):
    sw = _load_script()
    plan, _ = sw.select(board / "listings.json.gz", [_fake_verifier([])], {"tax_lien": L.Ledger("tax_lien")},
                        county=None, cap=10, now=NOW, tiers={"COLD"})
    # the two COLD rows (1000000003's second row is COLD; its HOT twin is filtered out)
    assert sorted(r["parcel_id"] for _p, _k, r, _v in plan["tax_lien"]) == ["1000000001", "1000000003"]


def test_source_filter(board):
    sw = _load_script()
    plan, _ = sw.select(board / "listings.json.gz", [_fake_verifier([])], {"tax_lien": L.Ledger("tax_lien")},
                        county=None, cap=10, now=NOW, sources={"nope"})
    assert plan["tax_lien"] == []
    plan, _ = sw.select(board / "listings.json.gz", [_fake_verifier([])], {"tax_lien": L.Ledger("tax_lien")},
                        county=None, cap=10, now=NOW, sources={"s"})
    assert len(plan["tax_lien"]) == 6
