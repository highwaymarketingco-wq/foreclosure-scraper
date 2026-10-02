"""national.fannie_homepath: 2026-10-01 national/reo per-source extraction audit.

_fetch_bbox used to fetch exactly ONE page per grid cell, trusting the
module's own "no cell in NC/SC exceeds ~200 results" tuning comment. Live
2026-10-01: 13 of the 32 current NC+SC cells return EXACTLY 400 properties
(the API's hard per-request cap) -- a round-number cap CLAUDE.md explicitly
warns to treat as a cap, not a real count, until proven otherwise. A live
15-page probe on one saturated cell found the union of distinct
propertyUuids growing 400 -> 544 -> 638 -> 658 -> 667 -> 671 -> ... -> 915,
confirming real additional rows existed beyond page 1 -- and also that the
API's pagination is NOT a stable, disjoint offset (the same top property
reappeared on every page, pages overlapped 40-70%), so paging must dedupe by
propertyUuid WITHIN one cell's own fetch, not only rely on the caller's
cross-cell dedup.

MAX_PAGES_PER_CELL=10 was tried first and MEASURED to regress the whole
scraper (32 cells each doing up to 10 sequential pages blew timeout_s=150s,
salvaging only 83 rows via the timeout-partial path -- far worse than the
pre-fix baseline of ~8,277 rows OK). Settled on 4 pages/cell + timeout_s=300,
MEASURED live to finish OUTCOME_OK in ~152s with 10,186 unique rows, zero
duplicates.
"""
from __future__ import annotations

import asyncio

from foreclosure_scraper.scrapers.national import fannie_homepath as m


def _page(uuids: list[str], state: str = "NC") -> dict:
    return {
        "properties": [
            {
                "propertyUuid": u,
                "addressLine1": f"{i} Test St",
                "city": "Asheville",
                "state": state,
                "zipCode": "28801",
                "county": "BUNCOMBE COUNTY",
                "propertyType": "Single Family",
                "price": 100000,
            }
            for i, u in enumerate(uuids)
        ],
        "totalProperties": 12345,
    }


def test_short_first_page_stops_after_one_request(monkeypatch):
    """A page smaller than _PAGE_CAP means that was the whole cell -- no
    second request should be made."""
    calls = []

    class _FakeResp:
        status_code = 200

        def json(self):
            return _page(["a", "b", "c"])  # well under _PAGE_CAP

    class _FakeClient:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def get(self, url, params=None, headers=None, follow_redirects=True):
            calls.append(params)
            return _FakeResp()

    monkeypatch.setattr(m, "client", lambda timeout=30.0: _FakeClient())

    out = asyncio.run(m._fetch_bbox("NC", 0, 0, 1, 1, m.FannieHomePath.slug))

    assert len(out) == 3
    assert len(calls) == 1, "a short page must not trigger a second request"


def test_full_page_fetches_a_second_page_and_dedupes_overlap(monkeypatch):
    """A full page (== _PAGE_CAP) must trigger page 2; overlapping uuids
    across pages (the real API's actual behavior, confirmed live) must not
    produce duplicate Listings."""
    full_page_1 = [f"id-{i}" for i in range(m._PAGE_CAP)]
    # page 2 overlaps heavily with page 1 (first 350 ids repeat) plus 50 new,
    # then page 3 is short (stop).
    full_page_2 = full_page_1[50:] + [f"new-{i}" for i in range(50)]
    short_page_3 = [f"final-{i}" for i in range(5)]
    pages = [full_page_1, full_page_2, short_page_3]

    class _FakeResp:
        def __init__(self, uuids):
            self._uuids = uuids
            self.status_code = 200

        def json(self):
            return _page(self._uuids)

    class _FakeClient:
        def __init__(self):
            self.call_count = 0

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def get(self, url, params=None, headers=None, follow_redirects=True):
            idx = int(params["page"]) - 1
            return _FakeResp(pages[idx])

    monkeypatch.setattr(m, "client", lambda timeout=30.0: _FakeClient())

    out = asyncio.run(m._fetch_bbox("NC", 0, 0, 1, 1, m.FannieHomePath.slug))

    # Distinct uuids across all 3 pages: 400 (page1) + 50 new (page2) + 5 (page3).
    expected_distinct = m._PAGE_CAP + 50 + 5
    assert len(out) == expected_distinct, (
        "overlapping pages must be deduped by propertyUuid within one cell's "
        f"own fetch, got {len(out)} expected {expected_distinct}")


def test_hits_max_pages_per_cell_and_stops(monkeypatch):
    """A pathologically always-full cell must stop at MAX_PAGES_PER_CELL,
    never loop forever."""
    call_count = 0

    class _FakeResp:
        status_code = 200

        def json(self):
            nonlocal call_count
            # Every page full of brand-new, never-repeating uuids.
            return _page([f"p{call_count}-{i}" for i in range(m._PAGE_CAP)])

    class _FakeClient:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def get(self, url, params=None, headers=None, follow_redirects=True):
            nonlocal call_count
            call_count += 1
            return _FakeResp()

    monkeypatch.setattr(m, "client", lambda timeout=30.0: _FakeClient())

    out = asyncio.run(m._fetch_bbox("NC", 0, 0, 1, 1, m.FannieHomePath.slug))

    assert call_count == m.MAX_PAGES_PER_CELL
    assert len(out) == m.MAX_PAGES_PER_CELL * m._PAGE_CAP
