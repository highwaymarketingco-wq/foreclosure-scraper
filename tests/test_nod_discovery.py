"""counties.nod_discovery — the fabricated-sale_date prerequisite fix (2026-10-14).

Pass2 of the date-coverage audit found that this scraper used to set
Listing.sale_date = recorded_date + NC_NOD_TO_SALE_DAYS (a GUESS, not a real fact from the
recording). board_persist._is_terminal_dict() runs unconditionally, before any
AGE_EXEMPT_SOURCES check, and drops any prior-only row whose sale_date is more than
TERMINAL_SALE_GRACE_DAYS (365d) in the past -- so every nod_discovery row was being
force-dropped at recorded_date + 90 + 365 ~= 455 days regardless of whether the underlying
case was still alive, which would have silently defeated this source's own addition to
AGE_EXEMPT_SOURCES the same day it landed. The fix: sale_date stays None (matching
nc_rod_substitute_trustee.py's own pre-sale convention); the 90-day guess survives only as a
non-authoritative estimate inside raw['nod']. Made-up names/books; no fetched content.
"""
from __future__ import annotations

from datetime import datetime, timedelta

from foreclosure_scraper.board_persist import AGE_EXEMPT_SOURCES, merge_prior_board
from foreclosure_scraper.scrapers.counties_generic.nod_discovery import (
    NC_NOD_TO_SALE_DAYS,
    _to_listing,
)
from foreclosure_scraper.rod.models import RodDoc

from tests.test_board_persist import _li, _write_board


def _doc(recorded_date, **kw):
    base = dict(
        state="NC", county="Buncombe", doc_type="S/TR", recorded_date=recorded_date,
        grantor="SMITH JOHN", grantee="ACME BANK NA", book="1161", page="815",
        instrument_no=None, notes=None,
    )
    base.update(kw)
    return RodDoc(**base)


def test_listing_sale_date_is_none_not_a_guess():
    recorded = datetime(2026, 1, 1)
    li = _to_listing(_doc(recorded), "counties.nod_discovery")
    assert li.sale_date is None


def test_estimate_survives_only_as_a_non_authoritative_raw_field():
    recorded = datetime(2026, 1, 1)
    li = _to_listing(_doc(recorded), "counties.nod_discovery")
    expected = (recorded + timedelta(days=NC_NOD_TO_SALE_DAYS)).isoformat()
    assert li.raw["nod"]["estimated_sale_date"] == expected


def test_slug_is_in_age_exempt_sources():
    assert "nod_discovery" in AGE_EXEMPT_SOURCES


def test_old_nod_row_survives_far_past_the_old_455_day_terminal_bug(tmp_path):
    """Before the fabricated-sale_date fix, a nod_discovery row recorded ~500 days ago would
    have had sale_date ~= recorded + 90 days ~= 410 days in the past -- past
    TERMINAL_SALE_GRACE_DAYS (365d) -- and been force-dropped by _is_terminal_dict() before the
    AGE_EXEMPT_SOURCES check ever ran. With sale_date=None and the slug in AGE_EXEMPT_SOURCES, it
    must now survive indefinitely (no miss counted, not terminal)."""
    recorded = datetime(2026, 10, 14) - timedelta(days=500)
    old_row = _li(
        source="counties.nod_discovery",
        street_address="10 Sample St", zip_code="28801", state="NC", county="Buncombe",
        sale_date=None, first_seen=recorded,
        raw={"nod": {"estimated_sale_date": (recorded + timedelta(days=NC_NOD_TO_SALE_DAYS)).isoformat()}},
    )
    _write_board(tmp_path, [old_row])
    out, stats = merge_prior_board(
        [_li(street_address="99 Elsewhere Rd", zip_code="28803")],
        docs_dir=tmp_path, now=datetime(2026, 10, 14), max_misses=4,
    )
    by = {li.street_address: li for li in out}
    assert "10 Sample St" in by
    assert stats["aged_out_terminal"] == 0
    assert stats["prior_only_kept_age_exempt"] == 1
