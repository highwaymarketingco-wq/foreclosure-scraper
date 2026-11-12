"""Per-county ARV calibration (valuation/calc.py).

Corrects the measured systematic per-county ARV bias via a factor table
(scripts/backtest_arv.py --emit-calibration). These tests drive the module
cache directly so they don't depend on the on-disk table.
"""
import pytest

from foreclosure_scraper.models import Listing
from foreclosure_scraper.valuation import calc


@pytest.fixture(autouse=True)
def _restore_cache():
    """Isolate each test's cache override; restore real loading after."""
    saved = calc._CALIB_CACHE
    yield
    calc._CALIB_CACHE = saved


def _li(county, **kw):
    return Listing(source="s", source_url="https://x", county=county, **kw)


def test_factor_lookup_and_default():
    calc._CALIB_CACHE = {"spartanburg": 0.5285, "charleston": 1.5714}
    assert calc._arv_calibration_factor(_li("Spartanburg")) == 0.5285
    assert calc._arv_calibration_factor(_li("charleston")) == 1.5714  # case-insensitive
    assert calc._arv_calibration_factor(_li("Greenville")) == 1.0     # not in table -> inert
    assert calc._arv_calibration_factor(_li(None)) == 1.0             # no county -> inert


def test_factor_out_of_range_is_ignored():
    calc._CALIB_CACHE = {"wild": 9.9, "tiny": 0.01}
    assert calc._arv_calibration_factor(_li("Wild")) == 1.0
    assert calc._arv_calibration_factor(_li("Tiny")) == 1.0


def test_calibration_shrinks_overvalued_county_arv():
    calc._CALIB_CACHE = {"spartanburg": 0.5}
    li = _li("Spartanburg", living_sqft=1000, raw={"comp_median_ppsf_recorded": 200})
    out = calc.compute(li)  # calibration lives in compute(), the chokepoint
    # baseline 200*1000=200,000 -> calibrated *0.5 = 100,000; band scales too
    assert out.arv_expected == pytest.approx(100_000, abs=200)
    assert out.arv_low < out.arv_expected < out.arv_high
    assert any("calibration" in n.lower() for n in out.notes)


def test_calibration_inert_for_uncalibrated_county():
    calc._CALIB_CACHE = {"spartanburg": 0.5}
    li = _li("Greenville", living_sqft=1000, raw={"comp_median_ppsf_recorded": 200})
    out = calc.compute(li)
    assert out.arv_expected == pytest.approx(200_000, abs=200)  # unchanged
    assert not any("calibration" in n.lower() for n in out.notes)
