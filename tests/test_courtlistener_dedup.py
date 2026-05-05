"""Regression test for the CourtListener bankruptcy scraper deduplication.

The audit measured 181 duplicate case_numbers per weekly run because
CourtListener pagination occasionally returns the same docket twice
(cursor-based pagination overlaps when records are edited between
page fetches). The scraper now dedupes at output time using
(court, docket_number) as the key.

Same docket# across different bankruptcy courts (NCWB 26-02017 vs
NCEB 26-02017) is legitimately distinct and must NOT be deduped.
"""
from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, patch

from foreclosure_scraper.scrapers.national.courtlistener_bankruptcy import (
    CourtListenerBankruptcy,
)


def _docket(docket_no, case_name, **kw):
    return {
        "docket_number": docket_no,
        "case_name": case_name,
        "absolute_url": f"http://courtlistener/{docket_no}",
        "date_filed": "2026-04-15",
        **kw,
    }


def test_dedups_repeated_docket_in_same_court():
    """Two API responses for the same court return the same docket twice.
    Output must contain it exactly once."""
    dockets_with_dupe = [
        _docket("26-02017", "John Doe", cause="Foreclosure / Ch.13"),
        _docket("26-02018", "Jane Smith", cause="Liquidation / Ch.7"),
        _docket("26-02017", "John Doe", cause="Foreclosure / Ch.13"),  # dupe!
    ]

    async def _run():
        scraper = CourtListenerBankruptcy()
        with patch(
            "foreclosure_scraper.scrapers.national.courtlistener_bankruptcy._fetch_court",
            new=AsyncMock(side_effect=lambda c, court, tok: (
                dockets_with_dupe if court == "ncwb" else []
            )),
        ), patch(
            "foreclosure_scraper.scrapers.national.courtlistener_bankruptcy._load_token",
            return_value="fake",
        ), patch(
            "foreclosure_scraper.scrapers.national.courtlistener_bankruptcy._fetch_chapter",
            new=AsyncMock(return_value="13"),
        ):
            return await scraper.fetch()

    result = list(asyncio.run(_run()))
    docket_nums = [li.case_number for li in result]
    assert docket_nums.count("26-02017") == 1, (
        f"expected 1 instance of 26-02017 after dedup, got {docket_nums.count('26-02017')}"
    )
    assert "26-02018" in docket_nums


def test_keeps_same_docket_across_different_courts():
    """NCWB 26-02017 and NCEB 26-02017 are different cases — both must
    appear in the output."""
    async def _run():
        scraper = CourtListenerBankruptcy()
        per_court = {
            "ncwb": [_docket("26-02017", "Western Debtor")],
            "nceb": [_docket("26-02017", "Eastern Debtor")],
        }
        with patch(
            "foreclosure_scraper.scrapers.national.courtlistener_bankruptcy._fetch_court",
            new=AsyncMock(side_effect=lambda c, court, tok: per_court.get(court, [])),
        ), patch(
            "foreclosure_scraper.scrapers.national.courtlistener_bankruptcy._load_token",
            return_value="fake",
        ), patch(
            "foreclosure_scraper.scrapers.national.courtlistener_bankruptcy._fetch_chapter",
            new=AsyncMock(return_value="13"),
        ):
            return await scraper.fetch()

    result = list(asyncio.run(_run()))
    docket_nums = [li.case_number for li in result]
    assert docket_nums.count("26-02017") == 2, (
        "same docket# in different courts must both be kept"
    )
    debtors = sorted(li.defendant for li in result if li.defendant)
    assert debtors == ["Eastern Debtor", "Western Debtor"]
