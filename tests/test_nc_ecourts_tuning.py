"""Regression tests for NC eCourts scraper tuning.

  * Lookback was 60 days; bumped to 90 to catch sales still in their
    10-day upset-bid window from 60-90 days ago.
  * Cause-of-action distribution is logged each run so silent
    drops of newly-added foreclosure cause codes get surfaced.
"""
from __future__ import annotations

from foreclosure_scraper.scrapers.counties_nc.nc_ecourts_lis_pendens import (
    NCECourtsLisPendens,
    FORECLOSURE_CAUSES,
)


def test_lookback_is_90_days():
    assert NCECourtsLisPendens.LOOKBACK_DAYS == 90


def test_foreclosure_causes_set_is_frozen():
    """The cause set must be a fixed collection so adding/removing items
    is a clear code change (not a runtime drift)."""
    assert isinstance(FORECLOSURE_CAUSES, (set, frozenset, tuple, list))
    # Spot-check known causes
    assert "CV - Lis Pendens" in FORECLOSURE_CAUSES


def test_cause_distribution_logging_present():
    """Source must log cause distribution so newly-added cause codes
    surface in weekly run logs."""
    import inspect
    from foreclosure_scraper.scrapers.counties_nc import nc_ecourts_lis_pendens
    src = inspect.getsource(nc_ecourts_lis_pendens)
    assert "cause_distribution" in src
    assert "uncovered_top" in src
