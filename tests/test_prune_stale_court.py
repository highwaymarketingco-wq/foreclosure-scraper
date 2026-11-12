"""Unit tests for the stale-court prune predicate (pure, no board write).

The prune lane is narrow ON PURPOSE: only the manual SC PublicIndex export
source, only rows that never got a sale_date, are old (first_seen year <= max),
and have gone cold (last_seen older than the stale window). Anything else stays.
"""
from __future__ import annotations

import importlib.util
from datetime import datetime, timedelta
from pathlib import Path

from foreclosure_scraper.models import Listing, ListingType

# The prune script lives under scripts/ (not an installed package); load by path.
_MOD_PATH = Path(__file__).resolve().parents[1] / "scripts" / "prune_stale_court.py"
_spec = importlib.util.spec_from_file_location("prune_stale_court", _MOD_PATH)
mod = importlib.util.module_from_spec(_spec)
assert _spec and _spec.loader
_spec.loader.exec_module(mod)

is_stale_court = mod.is_stale_court
STALE_COURT_SOURCE = mod.STALE_COURT_SOURCE

NOW = datetime(2026, 7, 30)


def _mk(source=STALE_COURT_SOURCE, *, first_seen, last_seen, sale_date=None, **kw) -> Listing:
    return Listing(
        source=source,
        source_url=f"https://example.test/{source}",
        listing_type=ListingType.FORECLOSURE_SALE,
        first_seen=first_seen,
        last_seen=last_seen,
        sale_date=sale_date,
        **kw,
    )


def test_classic_stale_2025_court_lead_is_pruned():
    li = _mk(first_seen=datetime(2025, 3, 1), last_seen=datetime(2026, 1, 1))
    assert is_stale_court(li, now=NOW) is True


def test_wrong_source_is_kept():
    li = _mk(source="law_firms.hutchens",
             first_seen=datetime(2025, 3, 1), last_seen=datetime(2026, 1, 1))
    assert is_stale_court(li, now=NOW) is False


def test_lead_with_sale_date_is_kept():
    li = _mk(first_seen=datetime(2025, 3, 1), last_seen=datetime(2026, 1, 1),
             sale_date=datetime(2025, 9, 1))
    assert is_stale_court(li, now=NOW) is False


def test_recent_first_seen_is_kept():
    li = _mk(first_seen=datetime(2026, 3, 1), last_seen=datetime(2026, 1, 1))
    assert is_stale_court(li, now=NOW) is False


def test_recently_refreshed_lead_is_kept():
    # first_seen old, but last_seen only 10 days ago -> still live, keep it.
    li = _mk(first_seen=datetime(2025, 3, 1), last_seen=NOW - timedelta(days=10))
    assert is_stale_court(li, now=NOW) is False


def test_boundary_last_seen_exactly_at_cutoff_is_kept():
    # last_seen exactly stale_days old is NOT strictly older than the cutoff.
    li = _mk(first_seen=datetime(2025, 3, 1), last_seen=NOW - timedelta(days=120))
    assert is_stale_court(li, now=NOW, stale_days=120) is False
    # one day past the window flips it to prunable.
    li2 = _mk(first_seen=datetime(2025, 3, 1), last_seen=NOW - timedelta(days=121))
    assert is_stale_court(li2, now=NOW, stale_days=120) is True


def test_env_tunable_year_and_days():
    li = _mk(first_seen=datetime(2024, 1, 1), last_seen=datetime(2024, 6, 1))
    # default (max_year=2025) prunes a 2024 lead...
    assert is_stale_court(li, now=NOW) is True
    # ...but tightening the year to 2023 keeps it.
    assert is_stale_court(li, now=NOW, max_first_seen_year=2023) is False


def test_2025_boundary_year_is_inclusive():
    li = _mk(first_seen=datetime(2025, 12, 31), last_seen=datetime(2026, 1, 1))
    assert is_stale_court(li, now=NOW, max_first_seen_year=2025) is True
