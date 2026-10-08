"""scripts/audit_checks/valuation.py on made-up rows (audit 2026-10-09)."""
from __future__ import annotations

import importlib.util
from datetime import date
from pathlib import Path

_P = Path(__file__).resolve().parents[1] / "scripts" / "audit_checks" / "valuation.py"
_spec = importlib.util.spec_from_file_location("audit_valuation", _P)
V = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(V)


def _run(check, rows):
    for r in rows:
        check.feed(r)
    return check.finish()


def _row(arv=None, tier="WARM", market=None, comps=None, check=None, kind="single_family",
         **raw):
    calc = {}
    if arv is not None:
        calc["arv_expected"] = arv
    if check is not None:
        calc["arv_basis_check"] = check
    return {"state": "NC", "county": "Polk", "parcel_id": "P-1", "property_kind": kind,
            "market_value": market,
            "raw": {"calc": calc, "comps": comps or [], "distress_stack": {"tier": tier}, **raw}}


def test_interface_shape():
    checks = V.make_checks()
    assert {c.name for c in checks} == {"valuation-outlier-explained", "valuation-hot-arv-supported",
                                        "valuation-comps-kind-fits", "valuation-comps-age"}
    for c in checks:
        res = c.finish()
        assert set(res) == {"name", "checked", "violations", "max_violations", "ok", "detail"}
    assert V.DETAIL_KEYS == ("comps", "cama")


def test_outlier_explained():
    ok = _row(1_500_000, market=1_200_000,
              check={"verdict": "explained", "basis": ["county value $1,200,000 (1.2x)"],
                     "triggers": ["over $1,000,000"]})
    bad_no_check = _row(1_500_000, market=1_200_000)
    bad_8x = _row(400_000, market=40_000)
    plain = _row(250_000, market=200_000)
    res = _run(V.OutlierExplained(), [ok, bad_no_check, bad_8x, plain])
    assert res["checked"] == 4 and res["violations"] == 2 and not res["ok"]


def test_outlier_against_cited_comps():
    comps = [{"sold_price": 50_000}, {"sold_price": 60_000}]
    res = _run(V.OutlierExplained(), [_row(400_000, comps=comps)])
    assert res["violations"] == 1


def test_hot_arv_supported():
    by_county = _row(300_000, tier="HOT", market=250_000)
    by_comp = _row(300_000, tier="HOT", comps=[{"sold_price": 280_000}])
    by_basket = _row(300_000, tier="HOT", recorded_comps={"count": 12, "median_ppsf": 150})
    bare = _row(300_000, tier="HOT", market=40_000, comps=[{"sold_price": 20_000}])
    warm_bare = _row(300_000, tier="WARM")
    res = _run(V.HotArvSupported(), [by_county, by_comp, by_basket, bare, warm_bare])
    assert res["checked"] == 4 and res["violations"] == 1


def test_comps_kind_fits():
    lot_with_house_comps = _row(kind="land", comps=[{"kind": "sfr", "sold_price": 1}])
    house_with_townhouse = _row(comps=[{"kind": "townhouse", "sold_price": 1}])
    house_with_house = _row(comps=[{"kind": "sfr", "sold_price": 1}])
    res = _run(V.CompsKindFits(), [lot_with_house_comps, house_with_townhouse, house_with_house])
    assert res["checked"] == 3 and res["violations"] == 1


def test_comps_age():
    today = date(2026, 10, 9)
    fresh = _row(comps=[{"sold_date": "2026-08-01"}])
    old = _row(comps=[{"sold_date": "2025-06-01"}])
    carried_no_age = _row(comps=[{"sold_date": "2026-08-01", "carried": True}])
    carried_ok = _row(comps=[{"sold_date": "2026-08-01", "carried": True, "age_days": 69}])
    res = _run(V.CompsAge(today), [fresh, old, carried_no_age, carried_ok])
    assert res["checked"] == 4 and res["violations"] == 2
