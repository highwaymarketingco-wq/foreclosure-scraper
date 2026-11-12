"""scripts/audit_checks/cube.py on made-up rows."""
from __future__ import annotations

import importlib.util
import json
from datetime import date
from pathlib import Path

_P = Path(__file__).resolve().parents[1] / "scripts" / "audit_checks" / "cube.py"
_S = importlib.util.spec_from_file_location("audit_checks_cube", _P)
cube = importlib.util.module_from_spec(_S)
_S.loader.exec_module(cube)


def row(**kw):
    base = {"source": "t.src", "listing_type": "tax_lien", "state": "NC", "county": "Buncombe",
            "parcel_id": "9648-12-3456", "raw": {}}
    base.update(kw)
    return base


def test_interface():
    names = [c.name for c in cube.make_checks()]
    assert names == ["cube-unscreened-county-signal-cells", "cube-flip-row-outside-flip-scope",
                     "cube-negative-wrapper-dated"]
    for c in cube.make_checks():
        r = c.finish()
        assert set(r) == {"name", "checked", "violations", "max_violations", "ok", "detail"}


def test_flip_row_outside_scope():
    c = cube.FlipRowOutsideFlipScope()
    c.feed(row(listing_type="foreclosure_sale", county="Alamance"))   # outside: violation
    c.feed(row(listing_type="foreclosure_sale", county="Buncombe"))   # footprint
    c.feed(row(listing_type="reo", county="Dare"))                    # oceanfront
    c.feed(row(listing_type="tax_lien", county="Alamance"))           # distressed: not checked
    r = c.finish()
    assert (r["checked"], r["violations"]) == (3, 1) and not r["ok"]


def test_negative_wrapper_dated():
    c = cube.NegativeWrapperDated()
    c.feed(row(raw={"incarceration_check": {"result": "no_match", "checked_at": "2026-10-01"}}))
    c.feed(row(raw={"bop_check": {"result": "no_match"}}))
    c.feed(row(raw={"divorce": {"case_count": 0, "fetched_at": "2026-10-02"}}))
    r = c.finish()
    assert (r["checked"], r["violations"]) == (3, 1)


def test_unscreened_cells_and_the_ledger_closing_them(tmp_path):
    rows = [row(county="Polk", owner_name="DOE JOHN", raw={"entity_type": "individual"}) for _ in range(2)]
    c = cube.UnscreenedCountySignalCells(ledger_path=tmp_path / "none.json", today=date(2026, 10, 9))
    for r in rows:
        c.feed(r)
    before = c.finish()
    assert before["violations"] > 0
    led = {"schema": "screen-ledger-v1", "run_at": "2026-10-08T00:00:00Z", "cells_screened": 1,
           "screens": {"lt_bankruptcy": {"NC|Polk": {"sources": ["national.courtlistener_bankruptcy"]}}}}
    (tmp_path / "led.json").write_text(json.dumps(led))
    c2 = cube.UnscreenedCountySignalCells(ledger_path=tmp_path / "led.json", today=date(2026, 10, 9))
    for r in rows:
        c2.feed(r)
    after = c2.finish()
    assert after["violations"] == before["violations"] - 1
    # a stale ledger screens nothing
    c3 = cube.UnscreenedCountySignalCells(ledger_path=tmp_path / "led.json", today=date(2026, 12, 1))
    for r in rows:
        c3.feed(r)
    assert c3.finish()["violations"] == before["violations"]
