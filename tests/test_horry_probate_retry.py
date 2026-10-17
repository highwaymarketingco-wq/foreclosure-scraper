"""horry_probate.HorryProbate.fetch: transient transport/timeout errors on either
network call get retried, not treated as "the whole scrape (or that year) is empty."

Found 2026-10-17 (gap-sweep): two unprotected SPOF sites in fetch() -- (1) the
priming ``await http.get(PAGE_URL)``, whose except-block does ``return []`` on
ANY error, zeroing 100% of this file's output; (2) the paginated
``await http.get(DATA_URL, ...)`` inside the per-year/per-page loop, whose
except-block ``break``s the page loop with no retry/resume, so a transient
failure on the very first page (start=0) of a year silently zeroed that whole
year's ~3-4k estates. Same root cause, same fix, as the Column legal-notice
API scrapers, spartan_weekly_legals.py, and arcgis_webmap.query_features(),
all fixed the same night: http_client.client()'s own docstring says every
caller is expected to wrap its own AsyncRetrying -- this file didn't, until
now.
"""
from __future__ import annotations

import asyncio
import json
from types import SimpleNamespace

import httpx
import pytest
from tenacity import wait_exponential_jitter

from foreclosure_scraper.scrapers.counties_sc import horry_probate as mod


def _row(case="2026ES2699001", name="TESTPERSON, ALEXANDRA Q", filed="09/15/2026"):
    return {"APPCODE": "26500", "CMSCASE": 999001.0, "WARANTNO": case, "CASENBR": "",
            "PROSCODE": "ZZZ", "CseFilDt": filed, "CseTypIn": "E", "PPTYSEQ": 1.0,
            "PPTYNAME": name, "PPTYLNAME": "TESTPERSON", "PPTYFNAME": "ALEXANDRA",
            "PROSNAME": "PLACEHOLDER, CLERK", "PPTYTYPE": "Deceased Person"}


def _payload(rows, total):
    return {"d": json.dumps({"Error": None, "sEcho": 1, "recordsFiltered": total,
                             "recordsTotal": total, "aaData": rows})}


class _Resp:
    def __init__(self, payload, status_code=200):
        self._p, self.status_code = payload, status_code

    def json(self):
        return self._p


class _Ctx:
    """Mimics the ``async with client(...) as http:`` context manager."""

    def __init__(self, http):
        self.http = http

    async def __aenter__(self):
        return self.http

    async def __aexit__(self, *a):
        return False


@pytest.fixture(autouse=True)
def _fast_backoff(monkeypatch):
    monkeypatch.setattr(mod, "wait_exponential_jitter",
                        lambda **kw: wait_exponential_jitter(initial=0.001, max=0.002))


@pytest.fixture(autouse=True)
def _clean_env_and_pauses(monkeypatch):
    monkeypatch.setattr(mod, "_PAUSE_S", 0)
    monkeypatch.delenv(mod.ENV_OFF, raising=False)


# --- site 1: the priming ``await http.get(PAGE_URL)`` ----------------------

def test_priming_fetch_transient_timeout_is_retried_and_then_succeeds(monkeypatch):
    calls = {"page": 0, "data": 0}

    async def get(url, params=None, headers=None):
        if url == mod.PAGE_URL:
            calls["page"] += 1
            if calls["page"] < 3:
                raise httpx.ConnectTimeout("boom")
            return _Resp({})
        calls["data"] += 1
        return _Resp(_payload([], 0))

    http = SimpleNamespace(get=get)
    monkeypatch.setattr(mod, "client", lambda *a, **kw: _Ctx(http))
    rows = asyncio.run(mod.HorryProbate().fetch())
    assert calls["page"] == 3                 # 2 failures + the succeeding 3rd attempt
    assert calls["data"] >= 1, "must have proceeded past the priming fetch into the page loop"
    assert rows == []


def test_priming_fetch_timeout_that_never_clears_still_ends_cleanly_not_hangs(monkeypatch):
    calls = {"page": 0, "data": 0}

    async def get(url, params=None, headers=None):
        if url == mod.PAGE_URL:
            calls["page"] += 1
            raise httpx.ConnectTimeout("always boom")
        calls["data"] += 1
        return _Resp(_payload([], 0))

    http = SimpleNamespace(get=get)
    monkeypatch.setattr(mod, "client", lambda *a, **kw: _Ctx(http))
    rows = asyncio.run(mod.HorryProbate().fetch())
    assert calls["page"] == 3                 # stop_after_attempt(3), then gives up -- not a hang
    assert calls["data"] == 0, "the priming fetch's own except-block aborts the whole scrape"
    assert rows == []


# --- site 2: the paginated ``await http.get(DATA_URL, ...)`` ---------------

def test_data_fetch_transient_timeout_on_first_page_is_retried_and_then_succeeds(monkeypatch):
    calls = {"data": 0}

    async def get(url, params=None, headers=None):
        if url == mod.PAGE_URL:
            return _Resp({})
        calls["data"] += 1
        if params.get("iDisplayStart") == "0" and calls["data"] < 3:
            raise httpx.ReadTimeout("boom")
        return _Resp(_payload([_row()], 1))

    http = SimpleNamespace(get=get)
    monkeypatch.setattr(mod, "client", lambda *a, **kw: _Ctx(http))
    rows = asyncio.run(mod.HorryProbate().fetch())
    assert [li.case_number for li in rows] == ["2026ES2699001"]
    assert calls["data"] >= 3


def test_data_fetch_timeout_that_never_clears_zeroes_only_that_years_remaining_pages(monkeypatch):
    seen_years: list[str] = []
    current_year_prefix = f"{mod.datetime.utcnow().year}ES26"

    async def get(url, params=None, headers=None):
        if url == mod.PAGE_URL:
            return _Resp({})
        year_prefix = params.get("CaseNumber", "")
        if year_prefix == current_year_prefix:
            raise httpx.ConnectTimeout("always boom")
        seen_years.append(year_prefix)
        return _Resp(_payload([_row("2025ES2699004", filed="12/01/2025")], 1))

    http = SimpleNamespace(get=get)
    monkeypatch.setattr(mod, "client", lambda *a, **kw: _Ctx(http))
    rows = asyncio.run(mod.HorryProbate().fetch())
    # The current year's page loop breaks after its 3 exhausted retry attempts
    # (not a hang) -- but that failure is confined to that year's page loop;
    # the previous year's pages are unaffected and still land their estate.
    assert [li.case_number for li in rows] == ["2025ES2699004"]
    assert seen_years, "the previous year must still have been queried"


def test_data_fetch_non_transport_error_is_not_retried(monkeypatch):
    calls = {"data": 0}

    async def get(url, params=None, headers=None):
        if url == mod.PAGE_URL:
            return _Resp({})
        calls["data"] += 1
        raise RuntimeError("not a transport/timeout error")

    http = SimpleNamespace(get=get)
    monkeypatch.setattr(mod, "client", lambda *a, **kw: _Ctx(http))
    rows = asyncio.run(mod.HorryProbate().fetch())
    # One immediate, unretried failure per year (current year, then previous
    # year) -- never 3 attempts per year the way a transport/timeout error gets.
    assert calls["data"] == 2, "a non-transport/timeout exception must not be retried"
    assert rows == []
