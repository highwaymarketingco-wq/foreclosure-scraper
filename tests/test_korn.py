"""Korn Law Firm (SC) — confirmed-dead domain, re-verified 2026-10-04.

kornlawfirm.com has served a parking page since 2026-05-13 (re-verified live
today: a plain "domain may be for sale" page, no redirect, no successor
site found). The scraper was already skipping network work via a hardcoded
`return []` in fetch(), but that made BaseScraper.safe_run record
OUTCOME_ZERO ("ran clean but returned 0 rows") -- indistinguishable from a
real source having a quiet week. Fixed by setting `disabled = True`
(the same convention counties_sc.sumter_surplus uses for a confirmed
permanent dead-end), which safe_run reports as the accurate OUTCOME_DORMANT
and skips calling fetch() at all.
"""
from __future__ import annotations

import asyncio

from foreclosure_scraper.base_scraper import OUTCOME_DORMANT
from foreclosure_scraper.scrapers.law_firms.korn import Korn


def test_scraper_registered():
    from foreclosure_scraper.scrapers._registry import all_scrapers
    assert "law_firms.korn" in {s.slug for s in all_scrapers()}


def test_disabled_with_a_reason():
    k = Korn()
    assert k.disabled is True
    assert k.disabled_reason  # non-empty, explains the domain-parked finding


def test_fetch_is_a_safe_noop_for_any_direct_caller():
    """Even though safe_run short-circuits before ever calling fetch() for a
    disabled scraper, fetch() itself must stay a harmless no-op for any
    direct caller (tests, __main__ probes) that bypasses safe_run."""
    out = asyncio.run(Korn().fetch())
    assert list(out) == []


def test_safe_run_reports_dormant_not_zero():
    k = Korn()
    out = asyncio.run(k.safe_run())
    assert out == []
    assert k.last_outcome == OUTCOME_DORMANT
    assert "disabled" in k.last_reason.lower()
