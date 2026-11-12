"""Regression test for the flood_zone -> flood dashboard-field derivation.

Real bug found 2026-09-16: two separate FEMA-NFHL flood enrichers exist.
enrichment_flood.py (wired into main.py) writes raw['flood'], which is the
ONLY key docs/dashboard.js's badges and Risk & Environment panel read.
enrichment_flood_zone.py (not wired into main.py) writes raw['flood_zone'].
Today's board-wide backfill ran the second, dashboard-invisible one,
reaching 85.6% coverage on a field the UI never looks at while raw['flood']
sat at 16.7%. This script derives the former from the latter for free.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

from backfill_flood_dashboard_field import _derive  # noqa: E402


def test_high_risk_zone_maps_correctly():
    fz = {"in_sfha": True, "zone": "AE", "zone_description": "1% annual flood", "flood_risk": "high"}
    out = _derive(fz)
    assert out["zone"] == "AE"
    assert out["in_sfha"] is True
    assert out["sfha_tf"] is True
    assert out["note"] == "1% annual flood"
    assert out["derived_from"] == "flood_zone_backfill"


def test_low_risk_zone_maps_correctly():
    fz = {"in_sfha": False, "zone": "X", "zone_description": "Area of moderate/low flood hazard", "flood_risk": "low"}
    out = _derive(fz)
    assert out["zone"] == "X"
    assert out["in_sfha"] is False
    assert out["sfha_tf"] is False


def test_missing_in_sfha_coerces_to_false_not_none():
    """dashboard.js checks `_fl.in_sfha` truthily -- None would render the
    same as False visually, but the field must never be a non-bool."""
    fz = {"zone": "X"}
    out = _derive(fz)
    assert out["in_sfha"] is False
    assert out["sfha_tf"] is False
