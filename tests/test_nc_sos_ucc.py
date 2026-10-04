"""NC SOS UCC fixture-filing search.

Disabled 2026-10-01: confirmed live that _UCC_SEARCH_URL 307-redirects into
sosnc.gov's generic Business Registration search (zero UCC-related content
anywhere on the destination page), and that the live search page has no
date-range input at all -- the module used to claim broad "filed in last N
days" discovery was possible, which was never true of this page's actual
controls (name-only search: Organization/Individual + Starting
With/All/Any/Exact Match).

FIXED 2026-10-04 (HERMES extraction-completeness audit, batch 17), same bug
class as law_firms.korn's 2026-10-01 fix: `fetch()` was a hardcoded
`return []` with no `disabled` flag set, so BaseScraper.safe_run recorded
the ambiguous OUTCOME_ZERO ("ran clean but returned 0 rows") every run --
indistinguishable from a real source having a quiet week. Fixed by setting
`disabled = True` (this source is a confirmed, permanent dead-end, not an
intermittent one -- re-verified live 2026-10-04 it's now ALSO behind an
active Cloudflare challenge on top of the original redirect finding), which
safe_run reports as the accurate OUTCOME_DORMANT instead.
"""
import asyncio

from foreclosure_scraper.base_scraper import OUTCOME_DORMANT
from foreclosure_scraper.scrapers.national.nc_sos_ucc import (
    NcSosUccScraper,
    _is_fixture,
    _parse_date,
)


def test_disabled_with_a_reason():
    s = NcSosUccScraper()
    assert s.disabled is True
    assert s.disabled_reason  # non-empty, explains the redirect + CF finding


def test_fetch_is_a_safe_noop_for_direct_callers():
    """Even though safe_run short-circuits before ever calling fetch() for a
    disabled scraper, fetch() itself must stay a harmless no-op for any
    direct caller (tests, __main__ probes) that bypasses safe_run."""
    rows = asyncio.run(NcSosUccScraper().fetch())
    assert rows == []


def test_safe_run_reports_dormant_not_zero():
    s = NcSosUccScraper()
    out = asyncio.run(s.safe_run())
    assert out == []
    assert s.last_outcome == OUTCOME_DORMANT
    assert "disabled" in s.last_reason.lower()


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
