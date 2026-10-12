"""scripts/export_wall_punchlist.py on made-up ledgers and a made-up board."""
from __future__ import annotations

import csv
import gzip
import importlib.util
import json
import types
from pathlib import Path

from foreclosure_scraper.verification.core import result
from foreclosure_scraper.verification.ledger import Ledger
from foreclosure_scraper.verification.registry import from_module

_SPEC = importlib.util.spec_from_file_location(
    "export_wall_punchlist", Path(__file__).resolve().parents[1] / "scripts" / "export_wall_punchlist.py")
ewp = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(ewp)


def _mod(name, signal, applies, wall=False):
    m = types.ModuleType(name)
    m.SIGNAL, m.VERSION, m.TTL_DAYS, m.WALL = signal, "v1", 30, wall
    m.applies = applies

    async def verify(row, client=None):
        return result(signal, "wall", {"reason": "fake walled portal", "card": "fake_card"},
                      version="v1", verifier=name)
    m.verify = verify
    return from_module(m, name)


def _row(parcel, source, lt="tax_lien", county="Testco", state="NC"):
    return {"state": state, "county": county, "parcel_id": parcel, "street_address": f"{parcel[-3:]} Sample Rd",
            "listing_type": lt, "source": source, "source_url": f"https://example.test/{parcel}", "raw": {}}


ROWS = {
    "wall": _row("1000000001", "fake.tax"),
    "unconf_blocked": _row("1000000002", "fake.tax"),
    "unconf_transient": _row("1000000003", "fake.tax"),
    "confirmed": _row("1000000004", "fake.tax"),
    "stale": _row("1000000005", "fake.tax"),
    "refuted": _row("1000000006", "fake.tax"),
    "never_checked_polite": _row("1000000007", "fake.tax"),
    "wall_unlabelled": _row("1000000008", "fake.court", lt="lis_pendens"),
    "uncovered": _row("1000000009", "fake.nothing", lt="foreclosure_sale"),
}


def _setup(tmp_path: Path):
    tax = _mod("fake_tax", "tax_lien", lambda r: r.get("source") == "fake.tax")
    court = _mod("fake_court_wall", "court_wall", lambda r: r.get("source") == "fake.court", wall=True)
    verifiers = [court, tax]
    led = Ledger("tax_lien")
    ans = {"wall": ("wall", {"reason": "rod_blocked", "blocked": "login_redirect"}),
           "unconf_blocked": ("unconfirmed", {"reason": "tenant_unhealthy",
                                               "tenant_health": "TenantDown: http_403: circuit blocked",
                                               "url": "https://portal.example.test/search"}),
           "unconf_transient": ("unconfirmed", {"reason": "tenant_unhealthy",
                                                 "tenant_health": "TenantDown: http_503 (2 failure(s))"}),
           "confirmed": ("confirmed", {}), "stale": ("stale", {}), "refuted": ("refuted", {})}
    for k, (verdict, ev) in ans.items():
        led.record(ROWS[k], result("tax_lien", verdict, ev, version="v1", verifier="fake_tax"),
                   ttl_days=30, keys=tax.ledger_keys(ROWS[k]))
    ldir = tmp_path / "ledgers"
    led.save(ldir / "tax_lien")
    board = tmp_path / "board.json.gz"
    with gzip.open(board, "wt", encoding="utf-8") as f:
        json.dump(list(ROWS.values()) + [ROWS["wall"]], f)      # a duplicate row: listed once
    return board, ldir, verifiers


def _run(tmp_path, board, ldir, verifiers):
    out = tmp_path / "out"
    s = ewp.export(board, ldir, out, tmp_path / "summary.json", verifiers=verifiers)
    return s, json.loads((out / "wall_punchlist.json").read_text()), out


def test_categories(tmp_path):
    board, ldir, verifiers = _setup(tmp_path)
    s, items, out = _run(tmp_path, board, ldir, verifiers)
    by_parcel = {it["parcel_id"]: it for it in items}
    assert set(by_parcel) == {"1000000001", "1000000002", "1000000008", "1000000009"}
    assert by_parcel["1000000001"]["wall_state"] == "recorded"
    assert by_parcel["1000000001"]["signal"] == "tax_lien"
    assert by_parcel["1000000002"]["wall_state"] == "unconfirmed_blocked"
    assert by_parcel["1000000002"]["checked_url"] == "https://portal.example.test/search"
    assert by_parcel["1000000008"]["wall_state"] == "not_yet_labelled"
    assert by_parcel["1000000008"]["wall_path"] == "fake_card"
    assert by_parcel["1000000009"]["category"] == "uncovered"
    assert all(it["ledger_key"].startswith("parcel:NC:testco:") for it in items)
    assert s["by_category"] == {"uncovered": 1, "wall": 3}
    with open(out / "wall_punchlist.csv", newline="") as f:
        assert len(list(csv.DictReader(f))) == 4


def test_idempotent(tmp_path):
    board, ldir, verifiers = _setup(tmp_path)
    _run(tmp_path, board, ldir, verifiers)
    a = [(tmp_path / "out" / n).read_bytes() for n in ("wall_punchlist.json", "wall_punchlist.csv")]
    sa = (tmp_path / "summary.json").read_bytes()
    _run(tmp_path, board, ldir, verifiers)
    b = [(tmp_path / "out" / n).read_bytes() for n in ("wall_punchlist.json", "wall_punchlist.csv")]
    assert a == b and sa == (tmp_path / "summary.json").read_bytes()


def test_blocked_evidence_rules():
    assert ewp.is_blocked_evidence({"reason": "login_redirect"})
    assert ewp.is_blocked_evidence({"http_status": 403})
    assert not ewp.is_blocked_evidence({"reason": "portal_unhealthy", "portal_health": "timeout"})
    assert not ewp.is_blocked_evidence({"reason": "tenant_unhealthy", "tenant_health": "http_503"})
