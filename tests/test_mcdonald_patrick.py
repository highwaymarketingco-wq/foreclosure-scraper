"""McDonald Patrick SC trustee foreclosure scraper.

Added 2026-06-16. Parses per-county foreclosure sale notices that carry a
real situs address (unlike the SC court rosters, which give only a TMS).
"""
from __future__ import annotations

import asyncio
import os

import pytest

from foreclosure_scraper.scrapers.law_firms.mcdonald_patrick import (
    COUNTY_PAGES,
    McDonaldPatrick,
    NOTICE_RE,
)


def test_notice_re_parses_standard_notice():
    text = "US Bank v Randall, et. al., C/A No. 2023CP2400921- 1103 Gary Rd, Hodges, SC (Land Only)"
    m = NOTICE_RE.search(text)
    assert m
    assert m.group("case") == "2023CP2400921"
    assert "Randall" in m.group("defendant")
    assert m.group("address").strip() == "1103 Gary Rd"
    assert m.group("city") == "Hodges"


def test_notice_re_parses_state_agency_plaintiff():
    text = "SC State Housing v Latham, et. al., C/A No. 2025CP2401323- 234 Greenway Dr, Greenwood, SC"
    m = NOTICE_RE.search(text)
    assert m
    assert m.group("case") == "2025CP2401323"
    assert m.group("address").strip() == "234 Greenway Dr"
    assert m.group("city") == "Greenwood"


def test_notice_re_ignores_non_notice_text():
    assert NOTICE_RE.search("Attorneys: Kenneth W. Poston, Partner") is None


def test_in_scope_counties_only():
    assert set(COUNTY_PAGES) == {"Abbeville", "Greenwood", "Newberry"}


def test_scraper_registered():
    from foreclosure_scraper.scrapers._registry import all_scrapers
    assert "law_firms.mcdonald_patrick" in {s.slug for s in all_scrapers()}


@pytest.mark.skipif(
    os.environ.get("RUN_NETWORK_TESTS") != "1",
    reason="hits live mcdonaldpatrick.com — set RUN_NETWORK_TESTS=1",
)
def test_live_returns_addressed_foreclosures():
    out = list(asyncio.run(McDonaldPatrick().fetch()))
    for li in out:
        assert li.state == "SC"
        assert li.county in COUNTY_PAGES
        assert li.case_number and li.case_number.count("CP") == 1
        # The whole point of this source: it carries a real street address.
        assert li.street_address and li.street_address[0].isdigit()
