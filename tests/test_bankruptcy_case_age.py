"""Tests for the bankruptcy case-age / long-open signal (Dirty Deeds Tier B
#28: "bankruptcies open 10-15 years are the strongest variant").

Covers:
  * signal_freshness.bankruptcy_case_age — pure date math.
  * enrichment_bankruptcy._docket_year_matches_filed — the PACER-test-entry
    filter live-verified against real CourtListener data (00-18888 filed
    2013 is synthetic; 13-50207 filed 2013 is real).
  * enrichment_bankruptcy._fetch_long_open_bankruptcies — the chapter /
    docket-year / test-name filters over mocked search results, no network.
  * enrich_with_bankruptcy — long-open matches get case_age_days/
    is_long_open/signal alongside the existing recent-filing matches.
"""
from __future__ import annotations

import asyncio
from datetime import date, timedelta
from unittest.mock import AsyncMock, patch

from foreclosure_scraper import enrichment_bankruptcy as eb
from foreclosure_scraper.models import Listing, ListingType
from foreclosure_scraper.signal_freshness import bankruptcy_case_age


# --- signal_freshness.bankruptcy_case_age ---------------------------------------------


def test_case_age_recent_filing_not_long_open():
    today = date(2026, 9, 29)
    out = bankruptcy_case_age({"date_filed": "2026-07-10"}, today=today)
    assert out["case_age_days"] == 81
    assert out["is_long_open"] is False


def test_case_age_old_and_unterminated_is_long_open():
    today = date(2026, 9, 29)
    filed = (today - timedelta(days=365 * 12)).isoformat()  # 12 years ago
    out = bankruptcy_case_age({"date_filed": filed}, today=today)
    assert out["case_age_days"] >= 3650
    assert out["is_long_open"] is True
    assert 11.5 < out["case_age_years"] < 12.5


def test_case_age_old_but_terminated_is_not_long_open():
    """A case that ran 12 years and then formally closed is not the anomaly
    the synthesis flags -- only a case with NO recorded closure is."""
    today = date(2026, 9, 29)
    filed = (today - timedelta(days=365 * 12)).isoformat()
    terminated = (today - timedelta(days=365 * 6)).isoformat()
    out = bankruptcy_case_age({"date_filed": filed, "date_terminated": terminated}, today=today)
    assert out["is_long_open"] is False


def test_case_age_missing_date_filed_returns_empty():
    assert bankruptcy_case_age({"date_terminated": "2020-01-01"}) == {}
    assert bankruptcy_case_age({}) == {}
    assert bankruptcy_case_age(None) == {}


def test_case_age_just_under_threshold_not_long_open():
    today = date(2026, 9, 29)
    filed = (today - timedelta(days=3649)).isoformat()
    out = bankruptcy_case_age({"date_filed": filed}, today=today)
    assert out["is_long_open"] is False


# --- enrichment_bankruptcy._docket_year_matches_filed ---------------------------------


def test_docket_year_matches_real_case():
    # live-verified 2026-09-29: Robert Lee Newman, 13-10701, filed 2013-10-30
    assert eb._docket_year_matches_filed("13-10701", "2013-10-30") is True


def test_docket_year_rejects_pacer_test_entry():
    # live-verified 2026-09-29: "Ted Mark Test and Tess Test", docket 00-18888,
    # dateFiled 2013-03-22 -- a real 2013 case would be prefixed "13-", not "00-".
    assert eb._docket_year_matches_filed("00-18888", "2013-03-22") is False


def test_docket_year_missing_inputs():
    assert eb._docket_year_matches_filed("", "2013-03-22") is False
    assert eb._docket_year_matches_filed("13-10701", "") is False
    assert eb._docket_year_matches_filed("not-a-docket", "2013-03-22") is False


# --- enrichment_bankruptcy._fetch_long_open_bankruptcies (mocked network) -------------


def _search_hit(case_name, docket_number, date_filed, chapter, date_terminated=None):
    return {
        "caseName": case_name,
        "docketNumber": docket_number,
        "dateFiled": date_filed,
        "dateTerminated": date_terminated,
        "chapter": chapter,
        "court_id": "ncwb",
        "docket_absolute_url": f"/docket/1/{docket_number}/",
    }


def test_long_open_fetch_filters_adversary_test_and_year_mismatch():
    """One real long-open debtor mixed with three kinds of noise the live probe
    actually turned up: an adversary proceeding (blank chapter), a PACER test
    entry, and a docket/filed-year mismatch. Only the real one should survive."""
    results = [
        _search_hit("Robert Lee Newman and Sharon Elaine Newman", "13-10701", "2013-10-30", "7"),
        _search_hit("Unsecured Creditors Committee v. Insider", "11-00101", "2011-07-05", None),
        _search_hit("Ted Mark Test and Tess Test", "00-18888", "2013-03-22", "7"),
        _search_hit("Some Test Debtor", "13-00099", "2013-01-01", "7"),  # "Test" in name
    ]

    async def _run():
        # A minimal stand-in for the httpx-like client `_fetch_long_open_bankruptcies`
        # calls .get() on — no real network involved.
        class _FakeResp:
            status_code = 200

            def __init__(self, results):
                self._results = results

            def json(self):
                return {"results": self._results, "next": None}

        class _FakeClient:
            async def get(self, url, headers=None):
                return _FakeResp(results)

        return await eb._fetch_long_open_bankruptcies(_FakeClient(), "ncwb", "faketoken")

    out = asyncio.run(_run())
    names = [d["case_name"] for d in out]
    assert names == ["Robert Lee Newman and Sharon Elaine Newman"]
    assert out[0]["chapter"] == "7"
    assert out[0]["date_filed"] == "2013-10-30"


def test_long_open_fetch_empty_on_no_results():
    class _FakeResp:
        status_code = 200

        def json(self):
            return {"results": [], "next": None}

    class _FakeClient:
        async def get(self, url, headers=None):
            return _FakeResp()

    out = asyncio.run(eb._fetch_long_open_bankruptcies(_FakeClient(), "scb", "faketoken"))
    assert out == []


# --- enrich_with_bankruptcy end-to-end (recent + long-open, mocked network) -----------


def _fc(name):
    return Listing(source="counties_generic.some_tax_source", source_url="u",
                   listing_type=ListingType.TAX_LIEN, defendant=name, raw={})


def test_enrich_with_bankruptcy_tags_long_open_match_with_age_and_signal():
    """A current tax-delinquent defendant name-matches a long-open (12-year-old,
    unterminated) bankruptcy debtor. The resulting raw.bankruptcy block must carry
    signal='long_open', is_long_open=True, and a real case_age_days."""
    today = date(2026, 9, 29)
    filed = (today - timedelta(days=365 * 12)).isoformat()
    long_open_hit = {
        "case_name": "Jane Q Homeowner", "docket_number": "14-40183",
        "date_filed": filed, "date_terminated": None, "chapter": "13",
        "absolute_url": "/docket/1/jane-q-homeowner/",
    }
    listing = _fc("Homeowner, Jane Q")

    async def _run():
        with patch.object(eb, "_load_token", return_value="faketoken"), \
             patch.object(eb, "_fetch_recent_bankruptcies", new=AsyncMock(return_value=[])), \
             patch.object(eb, "_fetch_long_open_bankruptcies",
                           new=AsyncMock(side_effect=lambda c, court, tok, today=None: (
                               [long_open_hit] if court == "ncwb" else []
                           ))):
            await eb.enrich_with_bankruptcy([listing])

    asyncio.run(_run())
    bk = listing.raw.get("bankruptcy")
    assert bk is not None
    assert bk["signal"] == "long_open"
    assert bk["chapter"] == "13"
    assert bk["case_age_days"] >= 3650
    assert bk["is_long_open"] is True


def test_enrich_with_bankruptcy_recent_match_not_long_open():
    listing = _fc("Homeowner, Jane Q")
    recent_hit = {
        "case_name": "Jane Q Homeowner", "docket_number": "26-40183",
        "date_filed": "2026-09-01", "absolute_url": "/docket/2/jane-q-homeowner/",
    }

    async def _run():
        with patch.object(eb, "_load_token", return_value="faketoken"), \
             patch.object(eb, "_fetch_recent_bankruptcies",
                           new=AsyncMock(side_effect=lambda c, court, tok: (
                               [recent_hit] if court == "ncwb" else []
                           ))), \
             patch.object(eb, "_fetch_chapter", new=AsyncMock(return_value="13")), \
             patch.object(eb, "_fetch_long_open_bankruptcies", new=AsyncMock(return_value=[])):
            await eb.enrich_with_bankruptcy([listing])

    asyncio.run(_run())
    bk = listing.raw.get("bankruptcy")
    assert bk is not None
    assert bk["signal"] == "recent_filing"
    assert bk["is_long_open"] is False
