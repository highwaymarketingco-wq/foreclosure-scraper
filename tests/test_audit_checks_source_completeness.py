"""scripts/audit_checks/source_completeness.py: the source-completeness invariants (audit 2026-10-09).
Made-up rows in the published board shape (source, county, state, raw)."""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path

_PATH = Path(__file__).resolve().parents[1] / "scripts" / "audit_checks" / "source_completeness.py"
_spec = importlib.util.spec_from_file_location("audit_source_completeness", _PATH)
sc = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(sc)

KEYS = {"name", "checked", "violations", "max_violations", "ok", "detail"}


def _row(source, county="Sampleton", state="SC", misses=0, carry=False, lt="tax_lien"):
    raw = {}
    if misses:
        raw["pulled_sale"] = {"consecutive_misses": misses, "presumed_withdrawn": True}
    if carry:
        raw["carryover"] = {"stale": True}
    return {"source": source, "county": county, "state": state, "listing_type": lt, "raw": raw}


def test_interface():
    checks = sc.make_checks()
    assert [c.name for c in checks] == ["source-county-refreshed", "source-county-floor", "source-cap-not-hit"]
    for c in checks:
        c.feed(_row("counties_sc.example_roll"))
        assert set(c.finish()) == KEYS


def test_a_county_the_run_did_not_reread_is_flagged():
    # the qPayBill shape: one county refreshed, another last read weeks ago (2 misses)
    c = sc.CountyRefreshed()
    for i in range(30):
        c.feed(_row("counties_sc.example_roll", county="Freshton"))
    for i in range(30):
        c.feed(_row("counties_sc.example_roll", county="Staleton", misses=2 if i < 20 else 0))
    r = c.finish()
    assert r["violations"] == 1 and not r["ok"]
    assert "Staleton|SC 20/30" in r["detail"] and "Freshton" not in r["detail"]


def test_carryover_replays_count_as_not_reread_and_small_cells_are_ignored():
    c = sc.CountyRefreshed()
    for i in range(25):
        c.feed(_row("counties_nc.example_tax", county="Carried", state="NC", carry=True))
    for i in range(19):
        c.feed(_row("counties_nc.example_tax", county="Tiny", state="NC", misses=3))
    r = c.finish()
    assert r["violations"] == 1 and "Carried|NC 25/25" in r["detail"]


def test_recorded_filing_lanes_are_exempt():
    c = sc.CountyRefreshed()
    for src in ("counties_generic.liensnc", "liensnc", "nc_ecourts_judgments", "manual.watchlist"):
        for i in range(30):
            c.feed(_row(src, misses=2))
    r = c.finish()
    assert r["violations"] == 0 and r["checked"] == 0


def test_floor_flags_a_county_that_lost_most_of_its_rows_and_a_source_that_vanished():
    base = {"counties_sc.example_roll": {"class": "tax", "rows": 100,
                                         "counties": {"Keepton|SC": 40, "Lostton|SC": 60}},
            "counties_nc.example_gone": {"class": "tax", "rows": 50, "counties": {"Gone|NC": 50}}}
    c = sc.CountyFloor(baseline=base)
    for i in range(40):
        c.feed(_row("counties_sc.example_roll", county="Keepton"))
    for i in range(29):
        c.feed(_row("counties_sc.example_roll", county="Lostton"))
    r = c.finish()
    assert r["violations"] == 2
    assert "Lostton|SC 29/60" in r["detail"] and "counties_nc.example_gone 0/50" in r["detail"]


def test_floor_without_a_baseline_is_not_ok():
    c = sc.CountyFloor(baseline={})
    assert not c.finish()["ok"]


def test_a_count_equal_to_the_scrapers_cap_is_flagged():
    cap = sc.CapNotHit._cap(*sc.CAPS[0][2:])
    c = sc.CapNotHit()
    for i in range(cap):
        c.feed(_row("counties_nc.nc_heir_estate_parcels", county="Capped", state="NC", lt="estate_lead"))
    for i in range(cap - 1):
        c.feed(_row("counties_nc.nc_heir_estate_parcels", county="Under", state="NC", lt="estate_lead"))
    r = c.finish()
    assert r["violations"] == 1 and f"Capped|NC {cap}=cap" in r["detail"]


def test_lead_class():
    assert sc.lead_class("x", "tax_sale") == "tax"
    assert sc.lead_class("counties_nc.gaston_vacant", "distressed") == "code"
    assert sc.lead_class("counties_generic.state_contamination.nc_ust_incidents", "distressed") == "env"
    assert sc.lead_class("x", "lis_pendens") == "lis_pendens"


def test_write_baseline_keeps_high_value_cells_only(tmp_path, monkeypatch):
    rows = ([_row("counties_sc.example_roll", county="Bigton") for _ in range(25)]
            + [_row("counties_sc.example_roll", county="Smallton") for _ in range(5)]
            + [_row("counties_generic.state_contamination.example", county="Bigton", lt="distressed")
               for _ in range(30)]
            + [_row("liensnc", county="Bigton") for _ in range(30)])
    import foreclosure_scraper.board_stream as bs
    monkeypatch.setattr(bs, "iter_board_rows", lambda path=None: iter(rows))
    out = tmp_path / "baseline.json"
    doc = sc.write_baseline("unused", out)
    assert set(doc["sources"]) == {"counties_sc.example_roll"}
    assert doc["sources"]["counties_sc.example_roll"] == {"class": "tax", "rows": 30,
                                                          "counties": {"Bigton|SC": 25}}
    assert json.loads(out.read_text())["sources"] == doc["sources"]
