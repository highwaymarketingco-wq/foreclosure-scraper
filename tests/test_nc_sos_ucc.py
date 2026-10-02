"""NC SOS UCC fixture-filing search.

Disabled 2026-10-01: confirmed live that _UCC_SEARCH_URL 307-redirects into
sosnc.gov's generic Business Registration search (zero UCC-related content
anywhere on the destination page), and that the live search page has no
date-range input at all -- the module used to claim broad "filed in last N
days" discovery was possible, which was never true of this page's actual
controls (name-only search: Organization/Individual + Starting
With/All/Any/Exact Match).
"""
import asyncio

from foreclosure_scraper.scrapers.national.nc_sos_ucc import (
    NcSosUccScraper,
    _is_fixture,
    _parse_date,
)


def test_fetch_is_disabled_and_returns_no_rows():
    rows = asyncio.run(NcSosUccScraper().fetch())
    assert rows == []


def test_fixture_keyword_detection_still_works_for_a_future_rebuild():
    """The helper logic itself isn't wrong, just unreachable -- kept for a
    future rebuild against a real UCC data source."""
    assert _is_fixture("Collateral: all fixtures and real property improvements")
    assert not _is_fixture("Collateral: accounts receivable and inventory")
    assert not _is_fixture("")


def test_parse_date_handles_nc_sos_date_format():
    dt = _parse_date("9/15/2026")
    assert dt is not None and dt.year == 2026 and dt.month == 9 and dt.day == 15
    assert _parse_date("") is None
    assert _parse_date("not a date") is None
