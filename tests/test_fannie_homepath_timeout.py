"""FannieHomePath's soft timeout must give it room to finish under contention.

MEASURED 2026-09-22 in the daily API refresh log: the scraper needs 53s to complete a full
NC+SC bbox sweep (8,277 rows) when run alone, but the daily job runs it inside a 14-way
asyncio.gather where it consistently timed out at 60s, read 0 rows, and was carried over
every day -- defeating the refresh's stated purpose (clearing sold Fannie Mae REO listings
whose per-property page has gone client-side-404). This just pins the fix so a future edit
cannot quietly shrink it back under the measured floor.
"""
from __future__ import annotations

from foreclosure_scraper.scrapers.national.fannie_homepath import FannieHomePath


def test_timeout_is_comfortably_above_the_measured_solo_runtime():
    # measured solo runtime was 53s; this is not "any bigger number", it is a floor with
    # real margin for the contention case that caused the daily carryover
    assert FannieHomePath.timeout_s >= 120.0


def test_timeout_is_well_inside_the_daily_api_refresh_phase_budget():
    # scripts/run_daily_vision.sh gives the whole daily_api_refresh.py script 5400s; one
    # scraper's soft timeout must stay a small fraction of that
    assert FannieHomePath.timeout_s <= 600.0
