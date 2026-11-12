"""gannett_obituaries: a throttled detail pass must not cost later papers their whole list.

Source-completeness audit 2026-10-08: 39 rows on the VM's gated run (was ~140), with
HTTP 429 on the last two papers' LIST pages. The old loop fetched ~20 detail pages per
paper between list pages, so a paper later in the order was asked for its list only
after ~100 detail requests, and a detail 429 never stopped the pass. These tests fail on
that code. Fixtures are invented (made-up names in the real Tukios link shape).
"""
from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from unittest.mock import MagicMock

import foreclosure_scraper.scrapers.public_notices.gannett_obituaries as M

LIST_A = ('<a href="/obituaries/testa-placeholder">x</a><a href="/obituaries/morrow-sample">x</a>'
          '<a href="/obituaries/quill-example">x</a>')
LIST_B = ('<a href="/obituaries/arden-mockname">x</a><a href="/obituaries/bexley-fakeperson">x</a>'
          '<a href="/obituaries/corwin-madeup">x</a>')
DETAIL = ('<html><head><meta name="description" content="Testa Placeholder, 77, of Nowhere, '
          'North Carolina, passed away on September 30, 2026."></head></html>')


def _fake_client(get_handler):
    @asynccontextmanager
    async def _cm(*a, **kw):
        stub = MagicMock()
        stub.get = get_handler
        yield stub
    return _cm


def _run(monkeypatch, ok_budget: int):
    """The papers' edge answers the first `ok_budget` requests, then 429 to everything."""
    calls: list[str] = []

    async def get(url, **kw):
        calls.append(url)
        if len(calls) > ok_budget:
            return MagicMock(status_code=429, text="Too Many Requests")
        if url.endswith("citizen-times.com/obituaries/"):
            return MagicMock(status_code=200, text=LIST_A)
        if url.endswith("independentmail.com/obituaries/"):
            return MagicMock(status_code=200, text=LIST_B)
        return MagicMock(status_code=200, text=DETAIL)

    monkeypatch.setattr(M, "client", _fake_client(get))
    monkeypatch.setattr(M, "PAPERS", {"citizen-times.com": ("Buncombe", "NC"),
                                      "independentmail.com": ("Anderson", "SC")})
    monkeypatch.setattr(M, "_GAP_S", 0.0, raising=False)
    rows = list(asyncio.run(M.GannettObituaries().fetch()))
    return rows, calls


def test_a_detail_429_does_not_cost_a_later_paper_its_list(monkeypatch):
    rows, calls = _run(monkeypatch, ok_budget=2)
    assert sorted(li.county for li in rows) == ["Anderson"] * 3 + ["Buncombe"] * 3


def test_the_detail_pass_stops_at_the_first_refusal(monkeypatch):
    rows, calls = _run(monkeypatch, ok_budget=2)
    # 2 list pages, then ONE refused detail request, then nothing more.
    assert len(calls) == 3
    assert all("age" not in li.raw["obituary"] for li in rows)


def test_details_still_land_when_nothing_is_refused(monkeypatch):
    rows, calls = _run(monkeypatch, ok_budget=100)
    assert len(rows) == 6 and len(calls) == 8
    assert all(li.raw["obituary"]["age"] == 77 for li in rows)
    assert all("age 77" in li.description for li in rows)


def test_a_list_page_429_stops_the_pass_instead_of_asking_the_next_paper(monkeypatch):
    """The papers share one edge (live 2026-10-08: 429 on 5 of 7 list pages within ~3 s),
    so a 429 is not answered by immediately asking the next paper."""
    calls: list[str] = []

    async def get(url, **kw):
        calls.append(url)
        if url.endswith("blueridgenow.com/obituaries/"):
            return MagicMock(status_code=429, text="Too Many Requests")
        return MagicMock(status_code=200, text=LIST_A)

    monkeypatch.setattr(M, "client", _fake_client(get))
    monkeypatch.setattr(M, "PAPERS", {"citizen-times.com": ("Buncombe", "NC"),
                                      "blueridgenow.com": ("Henderson", "NC"),
                                      "gastongazette.com": ("Gaston", "NC")})
    monkeypatch.setattr(M, "_GAP_S", 0.0, raising=False)
    monkeypatch.setenv("FORECLOSURE_OBIT_DETAIL", "0")
    rows = list(asyncio.run(M.GannettObituaries().fetch()))
    assert [u.split("/")[2] for u in calls] == ["www.citizen-times.com", "www.blueridgenow.com"]
    assert {li.county for li in rows} == {"Buncombe"} and len(rows) == 3


def test_requests_to_different_papers_are_spaced(monkeypatch):
    import time as _time
    stamps: list[float] = []

    async def get(url, **kw):
        stamps.append(_time.monotonic())
        return MagicMock(status_code=200, text=LIST_A if url.endswith("/obituaries/") else DETAIL)

    monkeypatch.setattr(M, "client", _fake_client(get))
    monkeypatch.setattr(M, "PAPERS", {"citizen-times.com": ("Buncombe", "NC"),
                                      "blueridgenow.com": ("Henderson", "NC")})
    monkeypatch.setattr(M, "_GAP_S", 0.05, raising=False)
    monkeypatch.setenv("FORECLOSURE_OBIT_DETAIL", "0")
    asyncio.run(M.GannettObituaries().fetch())
    assert len(stamps) == 2 and stamps[1] - stamps[0] >= 0.045
